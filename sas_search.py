from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
import heapq
import math
import re
import time

from grounderTypes import Comparator, GroundedNumericExpressionType

import sas_heuristics


DETDUP_RE = re.compile(r"_DETDUP_\d+$")
NO_COST_BOUND = object()


@dataclass
class BasicSearchResult:
    found: bool
    policy: object = None
    values: dict = field(default_factory=dict)
    solutions: list = field(default_factory=list)
    expansions: int = 0
    generated: int = 0
    max_open: int = 0
    reason: str = ""


@dataclass
class SearchSolution:
    policy: object
    values: dict
    certified: bool = False
    discovery_iteration: int = 0


@dataclass
class StateMetrics:
    cost_min: float = 0.0
    cost_max: float = 0.0
    loss_min: float = 0.0
    loss_max: float = 0.0

    # Returns the metrics as a tuple for copying and comparison.
    def as_tuple(self):
        return (
            self.cost_min,
            self.cost_max,
            self.loss_min,
            self.loss_max,
        )


@dataclass
class BasicPolicy:
    initial_state: tuple
    pending: set = field(default_factory=set)
    strategy: dict = field(default_factory=dict)
    terminal_goals: set = field(default_factory=set)
    state_metrics: dict = field(default_factory=dict)

    # Handles make initial.
    @classmethod
    def make_initial(cls, state_key):
        return cls(
            initial_state=state_key,
            pending={state_key},
            state_metrics={state_key: StateMetrics()},
        )

    # Returns a shallow structural copy of this object.
    def copy(self):
        return BasicPolicy(
            initial_state=self.initial_state,
            pending=set(self.pending),
            strategy=dict(self.strategy),
            terminal_goals=set(self.terminal_goals),
            state_metrics={
                state: StateMetrics(*metrics.as_tuple())
                for state, metrics in self.state_metrics.items()
            },
        )


# Runs the simple breadth-first baseline policy search.
def breadth_first_policy_search(
    sas_task,
    max_expansions=10000,
    optimization_order=("Umin", "Cmax", "Umax", "Cmin"),
    use_heuristics=True,
):
    initial_key = sas_task.state_key(
        sas_task.initial_state,
        sas_task.numeric_initial_state,
    )
    initial_policy = BasicPolicy.make_initial(initial_key)

    open_list = deque([initial_policy])
    seen = {policy_signature(initial_policy)}
    expansions = 0
    generated = 1
    heuristic_cache = {}

    while open_list:
        policy = open_list.popleft()
        _close_goal_pending_states(sas_task, policy)

        if not policy.pending:
            if _policy_has_only_goal_terminals(sas_task, policy):
                return BasicSearchResult(
                    found=True,
                    policy=policy,
                    values=evaluate_policy(sas_task, policy),
                    solutions=[SearchSolution(policy, evaluate_policy(sas_task, policy))],
                    expansions=expansions,
                    generated=generated,
                    max_open=len(open_list),
                    reason="solution found",
                )
            continue

        if max_expansions is not None and expansions >= max_expansions:
            return BasicSearchResult(
                found=False,
                expansions=expansions,
                generated=generated,
                max_open=len(open_list),
                reason=f"max expansions reached ({max_expansions})",
            )

        state_key = _select_pending_state(
            sas_task,
            policy,
            optimization_order,
            heuristic_cache,
            use_heuristics,
        )
        action_groups = _applicable_action_groups(
            sas_task,
            state_key,
            optimization_order,
            heuristic_cache,
            use_heuristics,
        )
        expansions += 1

        for group_key, actions in action_groups:
            child = _extend_policy(sas_task, policy, state_key, group_key, actions)
            if child is None:
                continue
            signature = policy_signature(child)
            if signature in seen:
                continue
            seen.add(signature)
            generated += 1
            open_list.append(child)

    return BasicSearchResult(
        found=False,
        expansions=expansions,
        generated=generated,
        max_open=len(open_list),
        reason="open list exhausted",
    )


# Runs the simple recursive AND-OR depth-first baseline search.
def depth_first_and_or_search(
    sas_task,
    max_expansions=10000,
    optimization_order=("Umin", "Cmax", "Umax", "Cmin"),
    use_heuristics=True,
):
    initial_key = sas_task.state_key(
        sas_task.initial_state,
        sas_task.numeric_initial_state,
    )
    counters = {"expansions": 0, "generated": 1}
    failed = set()
    solved = {}
    heuristic_cache = {}

    strategy = _solve_state_dfs(
        sas_task,
        initial_key,
        path=set(),
        failed=failed,
        solved=solved,
        counters=counters,
        max_expansions=max_expansions,
        optimization_order=optimization_order,
        heuristic_cache=heuristic_cache,
        use_heuristics=use_heuristics,
    )

    if strategy is None:
        reason = (
            f"max expansions reached ({max_expansions})"
            if max_expansions is not None
            and counters["expansions"] >= max_expansions
            else "no strong acyclic policy found"
        )
        return BasicSearchResult(
            found=False,
            expansions=counters["expansions"],
            generated=counters["generated"],
            reason=reason,
        )

    policy = BasicPolicy.make_initial(initial_key)
    policy.pending.clear()
    policy.strategy = strategy
    _populate_terminal_goals(sas_task, policy)

    return BasicSearchResult(
        found=True,
        policy=policy,
        values=evaluate_policy(sas_task, policy),
        solutions=[SearchSolution(policy, evaluate_policy(sas_task, policy))],
        expansions=counters["expansions"],
        generated=counters["generated"],
        reason="solution found",
    )


# Runs the Pareto-oriented BOAND-style policy search.
def boand_star_policy_search(
    sas_task,
    max_expansions=None,
    optimization_order=("Umin", "Cmax", "Umax", "Cmin"),
    use_heuristics=True,
    max_solutions=None,
    report_every=10000,
    on_solution=None,
):
    initial_key = sas_task.state_key(
        sas_task.initial_state,
        sas_task.numeric_initial_state,
    )
    initial_policy = BasicPolicy.make_initial(initial_key)
    heuristic_cache = {}
    open_list = []
    seen = set()
    solutions = []
    incumbents = []
    counter = 0
    expansions = 0
    generated = 1
    max_open = 0
    iterations = 0
    accepted_count = 0
    start_time = time.time()

    _ensure_search_caches(sas_task)

    print(f"Open-list order: {','.join(optimization_order)}", flush=True)
    if max_expansions is None:
        print("Max expansions: unbounded", flush=True)
    else:
        print(f"Max expansions: {max_expansions}", flush=True)
    andor_depth = getattr(sas_heuristics, "DEFAULT_ANDOR_DEPTH", None)
    if andor_depth is None:
        print("AND/OR Umin depth: unbounded", flush=True)
    else:
        print(f"AND/OR Umin depth: {andor_depth}", flush=True)

    for seed_order, seed_solution in _initial_seed_solutions(
        sas_task,
        optimization_order,
    ):
        values = seed_solution.values
        if _is_solution_dominated(values, solutions):
            continue
        solutions = _remove_solutions_dominated_by(values, solutions)
        incumbents = _remove_solutions_dominated_by(values, incumbents)
        seed_solution.certified = False
        seed_solution.discovery_iteration = 0
        solutions.append(seed_solution)
        incumbents.append(seed_solution)
        solutions.sort(
            key=lambda solution: _values_order_key(
                solution.values,
                optimization_order,
            )
        )
        accepted_count += 1
        _print_solution_progress(
            seed_solution.values,
            optimization_order,
            iteration=0,
            expansions=expansions,
            generated=generated,
            solution_count=len(solutions),
            start_time=start_time,
            label=f"SEED {','.join(seed_order)}",
        )
        if on_solution is not None:
            on_solution(
                seed_solution,
                accepted_count,
                {
                    "iterations": iterations,
                    "expansions": expansions,
                    "generated": generated,
                    "max_open": max_open,
                    "elapsed_time": time.time() - start_time,
                },
            )
        if max_solutions is not None and len(solutions) >= max_solutions:
            return _make_front_result(
                solutions,
                expansions,
                generated,
                max_open,
                "solution limit reached",
            )

    _prepare_policy_for_queue(sas_task, initial_policy)
    initial_f = evaluate_policy_lower_bound(
        sas_task,
        initial_policy,
        heuristic_cache,
        use_heuristics,
    )
    heapq.heappush(
        open_list,
        (
            _values_order_key(initial_f, optimization_order),
            counter,
            initial_f,
            initial_policy,
        ),
    )
    seen.add(policy_signature(initial_policy))
    _prune_open_by_solutions(open_list, incumbents)
    _mark_certified_solutions(
        solutions,
        open_list,
        optimization_order,
        start_time,
        iteration=0,
        expansions=expansions,
        generated=generated,
    )

    while open_list:
        max_open = max(max_open, len(open_list))
        if solutions:
            _order_key, _counter, f_values, policy = _pop_pareto_open_entry(
                open_list,
                optimization_order,
                iterations,
            )
        else:
            _order_key, _counter, f_values, policy = heapq.heappop(open_list)
        iterations += 1

        if report_every and iterations % report_every == 0:
            _print_search_progress(
                start_time=start_time,
                iterations=iterations,
                expansions=expansions,
                generated=generated,
                open_size=len(open_list),
                max_open=max_open,
                order_key=_order_key,
                values=f_values,
                optimization_order=optimization_order,
                policy=policy,
                solutions=solutions,
                sas_task=sas_task,
            )

        if _is_bound_weakly_dominated_by_solutions(f_values, incumbents):
            continue

        _prepare_policy_for_queue(sas_task, policy)

        if not policy.pending:
            if _policy_is_strong_acyclic_solution(sas_task, policy):
                values = evaluate_policy(sas_task, policy)
                if not _is_solution_dominated(values, solutions):
                    solutions = _remove_solutions_dominated_by(values, solutions)
                    accepted = SearchSolution(
                        policy,
                        values,
                        certified=False,
                        discovery_iteration=iterations,
                    )
                    solutions.append(accepted)
                    solutions.sort(
                        key=lambda solution: _values_order_key(
                            solution.values,
                            optimization_order,
                        )
                    )
                    if not _is_solution_dominated(values, incumbents):
                        incumbents = _remove_solutions_dominated_by(
                            values,
                            incumbents,
                        )
                        incumbents.append(accepted)
                    accepted_count += 1
                    pruned = _prune_open_by_solutions(open_list, incumbents)
                    _print_solution_progress(
                        values,
                        optimization_order,
                        iteration=iterations,
                        expansions=expansions,
                        generated=generated,
                        solution_count=len(solutions),
                        start_time=start_time,
                    )
                    if pruned:
                        print(
                            f"  pruned_open={pruned} open={len(open_list)}",
                            flush=True,
                        )
                    if on_solution is not None:
                        on_solution(
                            accepted,
                            accepted_count,
                            {
                                "iterations": iterations,
                                "expansions": expansions,
                                "generated": generated,
                                "max_open": max_open,
                                "elapsed_time": time.time() - start_time,
                            },
                        )
                    if max_solutions is not None and len(solutions) >= max_solutions:
                        return _make_front_result(
                            solutions,
                            expansions,
                            generated,
                            max_open,
                            "solution limit reached",
                        )
            continue

        if _has_reachable_strategy_cycle(policy):
            continue

        if max_expansions is not None and expansions >= max_expansions:
            reason = f"max expansions reached ({max_expansions})"
            _mark_certified_solutions(
                solutions,
                open_list,
                optimization_order,
                start_time,
                iteration=iterations,
                expansions=expansions,
                generated=generated,
            )
            return _make_front_result(
                solutions,
                expansions,
                generated,
                max_open,
                reason,
            )

        state_key = _select_pending_state(
            sas_task,
            policy,
            optimization_order,
            heuristic_cache,
            use_heuristics,
        )
        action_groups = _applicable_action_groups(
            sas_task,
            state_key,
            optimization_order,
            heuristic_cache,
            use_heuristics,
        )
        expansions += 1

        for group_key, actions in action_groups:
            child = _extend_policy(sas_task, policy, state_key, group_key, actions)
            if child is None:
                continue

            _prepare_policy_for_queue(sas_task, child)
            if _has_reachable_strategy_cycle(child):
                continue

            child_f = evaluate_policy_lower_bound(
                sas_task,
                child,
                heuristic_cache,
                use_heuristics,
            )
            if _has_infinite_component(child_f):
                continue
            if _violates_total_cost_bound(sas_task, child_f):
                continue
            if _is_bound_weakly_dominated_by_solutions(child_f, incumbents):
                continue

            signature = policy_signature(child)
            if signature in seen:
                continue
            seen.add(signature)

            counter += 1
            generated += 1
            heapq.heappush(
                open_list,
                (
                    _values_order_key(child_f, optimization_order),
                    counter,
                    child_f,
                    child,
                ),
            )

        if report_every and iterations % report_every == 0:
            _mark_certified_solutions(
                solutions,
                open_list,
                optimization_order,
                start_time,
                iteration=iterations,
                expansions=expansions,
                generated=generated,
            )

    for solution in solutions:
        solution.certified = True
    return _make_front_result(
        solutions,
        expansions,
        generated,
        max_open,
        "open list exhausted",
    )


# Builds a canonical signature for duplicate policy detection.
def policy_signature(policy):
    strategy_items = tuple(
        sorted(
            (
                state,
                action_key,
                tuple((action.index, successor) for action, successor in outcomes),
            )
            for state, (action_key, outcomes) in policy.strategy.items()
        )
    )
    return (
        policy.initial_state,
        tuple(sorted(policy.pending)),
        tuple(sorted(policy.terminal_goals)),
        tuple(
            sorted(
                (state, _rounded_metrics(metrics))
                for state, metrics in policy.state_metrics.items()
            )
        ),
        strategy_items,
    )


# Handles the internal solve state dfs step.
def _solve_state_dfs(
    sas_task,
    state_key,
    path,
    failed,
    solved,
    counters,
    max_expansions,
    optimization_order,
    heuristic_cache,
    use_heuristics,
):
    if sas_task.is_goal_state(*state_key):
        return {}
    if state_key in solved:
        return dict(solved[state_key])
    if state_key in failed or state_key in path:
        return None
    if max_expansions is not None and counters["expansions"] >= max_expansions:
        return None

    counters["expansions"] += 1
    path.add(state_key)

    for group_key, actions in _applicable_action_groups(
        sas_task,
        state_key,
        optimization_order,
        heuristic_cache,
        use_heuristics,
    ):
        outcomes = []
        merged_strategy = {}
        action_failed = False

        for action in actions:
            successor = _cached_successor(sas_task, state_key, action)
            if not _numeric_goal_bounds_hold(sas_task, successor):
                action_failed = True
                break
            counters["generated"] += 1
            outcomes.append((action, successor))

            subpolicy = _solve_state_dfs(
                sas_task,
                successor,
                path,
                failed,
                solved,
                counters,
                max_expansions,
                optimization_order,
                heuristic_cache,
                use_heuristics,
            )
            if subpolicy is None:
                action_failed = True
                break
            if not _merge_strategy(merged_strategy, subpolicy):
                action_failed = True
                break

        if action_failed:
            continue

        candidate_strategy = {
            state_key: (group_key, tuple(outcomes)),
        }
        if not _merge_strategy(candidate_strategy, merged_strategy):
            continue

        path.remove(state_key)
        solved[state_key] = dict(candidate_strategy)
        return candidate_strategy

    path.remove(state_key)
    failed.add(state_key)
    return None


# Merges strategy.
def _merge_strategy(target, source):
    for state, decision in source.items():
        if state in target and target[state] != decision:
            return False
        target[state] = decision
    return True


# Populates terminal goals.
def _populate_terminal_goals(sas_task, policy):
    for terminal in reachable_terminal_states(policy):
        if sas_task.is_goal_state(*terminal):
            policy.terminal_goals.add(terminal)


# Computes exact utility and cost metrics for a complete policy.
def evaluate_policy(sas_task, policy):
    propagate_policy_metrics(sas_task, policy)
    terminals = reachable_terminal_states(policy)
    if not terminals:
        terminals = {policy.initial_state}

    utilities = []
    real_costs = []
    losses = []

    for terminal in terminals:
        metrics = policy.state_metrics[terminal]
        utilities.extend(
            (
                sas_task.max_utility - metrics.loss_max,
                sas_task.max_utility - metrics.loss_min,
            )
        )
        real_costs.extend((metrics.cost_min, metrics.cost_max))
        losses.extend((metrics.loss_min, metrics.loss_max))

    return {
        "Umin": min(utilities),
        "Cmax": max(real_costs),
        "Umax": max(utilities),
        "Cmin": min(real_costs),
        "loss_min": min(losses),
        "loss_max": max(losses),
        "size": len(policy.strategy),
        "terminals": len(terminals),
        "metric_states": len(policy.state_metrics),
    }


# Computes optimistic bounds for a partial policy.
def evaluate_policy_lower_bound(
    sas_task,
    policy,
    heuristic_cache=None,
    use_heuristics=True,
):
    propagate_policy_metrics(sas_task, policy)
    frontier = reachable_terminal_states(policy)
    if not frontier:
        frontier = {policy.initial_state}

    loss_max_values = []
    cost_max_values = []
    cost_max_budget_values = []
    loss_min_values = []
    cost_min_values = []

    for state_key in frontier:
        metrics = policy.state_metrics[state_key]
        if sas_task.is_goal_state(*state_key):
            h_loss = 0.0
            h_cmax = 0.0
            h_cmax_budget = 0.0
            h_cmin = 0.0
        else:
            heuristic = _heuristic_value(
                sas_task,
                state_key,
                heuristic_cache if heuristic_cache is not None else {},
                use_heuristics,
            )
            h_loss = heuristic["h_loss"]
            h_loss_min = heuristic.get("h_loss_min", 0.0)
            h_cmax = heuristic.get("h_cmax", heuristic["h_goal"])
            h_cmax_budget = heuristic.get("h_cmax_unconditional", h_cmax)
            h_cmin = heuristic.get("h_cmin", heuristic["h_goal"])
        if sas_task.is_goal_state(*state_key):
            h_loss_min = 0.0

        loss_max_values.append(metrics.loss_max + h_loss)
        cost_max_values.append(metrics.cost_max + h_cmax)
        cost_max_budget_values.append(metrics.cost_max + h_cmax_budget)
        loss_min_values.append(metrics.loss_min + h_loss_min)
        cost_min_values.append(metrics.cost_min + h_cmin)

    loss_max = max(loss_max_values) if loss_max_values else math.inf
    cost_max = max(cost_max_values) if cost_max_values else math.inf
    cost_max_budget = (
        max(cost_max_budget_values)
        if cost_max_budget_values
        else math.inf
    )
    loss_min = min(loss_min_values) if loss_min_values else math.inf
    cost_min = min(cost_min_values) if cost_min_values else math.inf

    return {
        "Umin": sas_task.max_utility - loss_max,
        "Cmax": cost_max,
        "Cmax_budget": cost_max_budget,
        "Umax": sas_task.max_utility - loss_min,
        "Cmin": cost_min,
        "loss_min": loss_min,
        "loss_max": loss_max,
        "size": len(policy.strategy),
        "terminals": len(frontier),
        "metric_states": len(policy.state_metrics),
    }


# Handles the internal make front result step.
def _make_front_result(solutions, expansions, generated, max_open, reason):
    if not solutions:
        return BasicSearchResult(
            found=False,
            expansions=expansions,
            generated=generated,
            max_open=max_open,
            reason=reason,
        )

    best = solutions[0]
    return BasicSearchResult(
        found=True,
        policy=best.policy,
        values=best.values,
        solutions=solutions,
        expansions=expansions,
        generated=generated,
        max_open=max_open,
        reason=reason,
    )


# Handles the internal prepare policy for queue step.
def _prepare_policy_for_queue(sas_task, policy):
    _close_goal_pending_states(sas_task, policy)
    propagate_policy_metrics(sas_task, policy)


# Handles the internal values order key step.
def _values_order_key(values, optimization_order):
    key = []
    for criterion in optimization_order:
        if criterion == "Umin":
            key.append(values["loss_max"])
        elif criterion == "Cmax":
            key.append(values["Cmax"])
        elif criterion == "Umax":
            key.append(values["loss_min"])
        elif criterion == "Cmin":
            key.append(values["Cmin"])
        else:
            raise ValueError(f"Unsupported optimization criterion: {criterion}")
    key.append(-values.get("size", 0))
    return tuple(key)


# Handles the internal pop pareto open entry step.
def _pop_pareto_open_entry(open_list, optimization_order, iterations):
    orders = _pareto_selection_orders(optimization_order)
    selected_order = orders[iterations % len(orders)]
    if selected_order == tuple(optimization_order):
        return heapq.heappop(open_list)

    selected_index = min(
        range(len(open_list)),
        key=lambda index: (
            _values_order_key(open_list[index][2], selected_order),
            open_list[index][1],
        ),
    )
    entry = open_list[selected_index]
    last = open_list.pop()
    if selected_index < len(open_list):
        open_list[selected_index] = last
        heapq.heapify(open_list)
    return entry


# Handles the internal pareto selection orders step.
def _pareto_selection_orders(optimization_order):
    candidates = [
        tuple(optimization_order),
        ("Cmax", "Cmin", "Umin", "Umax"),
        ("Cmin", "Cmax", "Umin", "Umax"),
        ("Umax", "Cmax", "Umin", "Cmin"),
    ]

    orders = []
    for order in candidates:
        if order not in orders:
            orders.append(order)
    return orders


# Handles the internal minimization vector step.
def _minimization_vector(values):
    return (
        values["loss_max"],
        values["Cmax"],
        values["loss_min"],
        values["Cmin"],
    )


# Handles the internal weakly dominates min step.
def _weakly_dominates_min(lhs, rhs):
    lhs_vector = _minimization_vector(lhs)
    rhs_vector = _minimization_vector(rhs)
    return all(a <= b for a, b in zip(lhs_vector, rhs_vector))


# Handles the internal dominates min step.
def _dominates_min(lhs, rhs):
    lhs_vector = _minimization_vector(lhs)
    rhs_vector = _minimization_vector(rhs)
    return (
        all(a <= b for a, b in zip(lhs_vector, rhs_vector))
        and any(a < b for a, b in zip(lhs_vector, rhs_vector))
    )


# Checks whether solution dominated.
def _is_solution_dominated(values, solutions):
    return any(
        _weakly_dominates_min(solution.values, values)
        for solution in solutions
    )


# Handles the internal remove solutions dominated by step.
def _remove_solutions_dominated_by(values, solutions):
    return [
        solution
        for solution in solutions
        if not _dominates_min(values, solution.values)
    ]


# Checks whether bound weakly dominated by solutions.
def _is_bound_weakly_dominated_by_solutions(bound_values, solutions):
    return any(
        _weakly_dominates_min(solution.values, bound_values)
        for solution in solutions
    )


# Checks whether the object has infinite component.
def _has_infinite_component(values):
    return any(math.isinf(value) for value in _minimization_vector(values))


# Handles the internal violates total cost bound step.
def _violates_total_cost_bound(sas_task, values):
    bound = _total_cost_goal_bound(sas_task)
    if bound is None:
        return False
    budget_cmax = values.get("Cmax_budget", values["Cmax"])
    return budget_cmax > bound + 1e-9


# Handles the internal total cost goal bound step.
def _total_cost_goal_bound(sas_task):
    cached = getattr(sas_task, "_total_cost_goal_bound", NO_COST_BOUND)
    if cached is not NO_COST_BOUND:
        return cached

    limits = []
    for goal in sas_task.goals:
        for condition in goal.numeric_conditions:
            limit = _extract_total_cost_upper_bound(sas_task, condition)
            if limit is not None:
                limits.append(limit)

    bound = min(limits) if limits else None
    sas_task._total_cost_goal_bound = bound
    return bound


# Extracts total cost upper bound.
def _extract_total_cost_upper_bound(sas_task, condition):
    if len(condition.terms) != 2:
        return None

    left, right = condition.terms
    if (
        condition.comparator == Comparator.CMP_LESS_EQ
        and _numeric_expression_is_total_cost(sas_task, left)
    ):
        return _constant_goal_numeric_value(sas_task, right)

    if (
        condition.comparator == Comparator.CMP_GREATER_EQ
        and _numeric_expression_is_total_cost(sas_task, right)
    ):
        return _constant_goal_numeric_value(sas_task, left)

    return None


# Handles the internal numeric expression is total cost step.
def _numeric_expression_is_total_cost(sas_task, expression):
    if expression.type != GroundedNumericExpressionType.GE_VAR:
        return False
    for var in sas_task.numeric_variables:
        if var.index == expression.index:
            return str(var.fncIndex) == "total-cost"
    return False


# Handles the internal constant goal numeric value step.
def _constant_goal_numeric_value(sas_task, expression):
    expression_type = expression.type
    if expression_type == GroundedNumericExpressionType.GE_NUMBER:
        return float(expression.value)

    if expression_type == GroundedNumericExpressionType.GE_VAR:
        for pos, var in enumerate(sas_task.numeric_variables):
            if var.index == expression.index:
                return sas_task.numeric_initial_state[pos]
        return None

    if expression_type == GroundedNumericExpressionType.GE_SUM:
        values = [
            _constant_goal_numeric_value(sas_task, sub)
            for sub in expression.terms
        ]
        if any(value is None for value in values):
            return None
        return sum(values)

    if expression_type == GroundedNumericExpressionType.GE_SUB:
        values = [
            _constant_goal_numeric_value(sas_task, sub)
            for sub in expression.terms
        ]
        if any(value is None for value in values):
            return None
        if len(values) == 1:
            return -values[0]
        result = values[0]
        for value in values[1:]:
            result -= value
        return result

    return None


# Prunes open by solutions.
def _prune_open_by_solutions(open_list, solutions):
    before = len(open_list)
    if before == 0 or not solutions:
        return 0

    open_list[:] = [
        entry
        for entry in open_list
        if not _is_bound_weakly_dominated_by_solutions(entry[2], solutions)
    ]
    if len(open_list) != before:
        heapq.heapify(open_list)
    return before - len(open_list)


# Marks certified solutions.
def _mark_certified_solutions(
    solutions,
    open_list,
    optimization_order,
    start_time,
    iteration,
    expansions,
    generated,
):
    if not solutions:
        return

    open_bounds = [entry[2] for entry in open_list]
    for solution in solutions:
        if solution.certified:
            continue
        if _solution_can_be_dominated_by_open(solution.values, open_bounds):
            continue
        solution.certified = True
        _print_solution_progress(
            solution.values,
            optimization_order,
            iteration=iteration,
            expansions=expansions,
            generated=generated,
            solution_count=len(solutions),
            start_time=start_time,
            label="CERTIFIED",
        )


# Handles the internal solution can be dominated by open step.
def _solution_can_be_dominated_by_open(solution_values, open_bounds):
    return any(
        _dominates_min(bound_values, solution_values)
        for bound_values in open_bounds
    )


# Ensures search caches.
def _ensure_search_caches(sas_task):
    if not hasattr(sas_task, "_successor_cache"):
        sas_task._successor_cache = {}
    if not hasattr(sas_task, "_applicable_group_cache"):
        sas_task._applicable_group_cache = {}


# Returns cached successor.
def _cached_successor(sas_task, state_key, action):
    _ensure_search_caches(sas_task)
    key = (state_key, action.index)
    cached = sas_task._successor_cache.get(key)
    if cached is not None:
        return cached
    successor = sas_task.apply_action(state_key[0], state_key[1], action)
    sas_task._successor_cache[key] = successor
    return successor


# Formats order values.
def _format_order_values(values, optimization_order):
    return " ".join(f"{name}={values[name]}" for name in optimization_order)


# Handles the internal print solution progress step.
def _print_solution_progress(
    values,
    optimization_order,
    iteration,
    expansions,
    generated,
    solution_count,
    start_time,
    label="SOLUTION",
):
    elapsed = time.time() - start_time
    print(
        f"{label} at it={iteration}: "
        f"values={_format_order_values(values, optimization_order)} "
        f"solutions={solution_count} "
        f"size={values.get('size')} "
        f"exp={expansions} gen={generated} "
        f"time={elapsed:.2f}s",
        flush=True,
    )


# Handles the internal print search progress step.
def _print_search_progress(
    start_time,
    iterations,
    expansions,
    generated,
    open_size,
    max_open,
    order_key,
    values,
    optimization_order,
    policy,
    solutions,
    sas_task,
):
    elapsed = time.time() - start_time
    best_solution = solutions[0].values if solutions else None
    best_text = (
        _format_order_values(best_solution, optimization_order)
        if best_solution is not None
        else "<none>"
    )
    cache_info = _cache_info(sas_task)
    certified_count = sum(1 for solution in solutions if solution.certified)
    print(
        f"[{elapsed:8.1f}s] "
        f"it={iterations} exp={expansions} gen={generated} "
        f"open={open_size} max_open={max_open} "
        f"key={order_key} "
        f"bound={_format_order_values(values, optimization_order)} "
        f"policy_size={len(policy.strategy)} pending={len(policy.pending)} "
        f"solutions={len(solutions)} certified={certified_count} best={best_text} "
        f"cache={cache_info}",
        flush=True,
    )


# Handles the internal cache info step.
def _cache_info(sas_task):
    successor_cache = getattr(sas_task, "_successor_cache", {})
    group_cache = getattr(sas_task, "_applicable_group_cache", {})
    heuristic_cache = getattr(sas_task, "_andor_heuristic_cache", {})
    cost_cache = getattr(sas_task, "_andor_cost_cache", {})
    conditional_cost_cache = getattr(sas_task, "_andor_conditional_cost_cache", {})
    andor_successor_cache = getattr(sas_task, "_andor_successor_cache", {})
    andor_group_cache = getattr(sas_task, "_andor_successor_group_cache", {})
    return (
        f"succ:{len(successor_cache)} "
        f"groups:{len(group_cache)} "
        f"andor_succ:{len(andor_successor_cache)} "
        f"andor_groups:{len(andor_group_cache)} "
        f"h:{len(heuristic_cache)} "
        f"cost:{len(cost_cache)} "
        f"cond_cost:{len(conditional_cost_cache)}"
    )


# Handles the internal initial seed solutions step.
def _initial_seed_solutions(sas_task, optimization_order):
    seen_values = set()
    for seed_order in _pareto_selection_orders(optimization_order):
        seed = _lexicographic_seed_solution(sas_task, seed_order)
        if seed is None:
            continue
        signature = _rounded_value_signature(seed.values)
        if signature in seen_values:
            continue
        seen_values.add(signature)
        yield seed_order, seed


# Handles the internal lexicographic seed solution step.
def _lexicographic_seed_solution(sas_task, seed_order):
    initial_key = sas_task.state_key(
        sas_task.initial_state,
        sas_task.numeric_initial_state,
    )
    solving = set()

    # Solves the current state inside the local dynamic program.
    @lru_cache(maxsize=None)
    def solve(state_key):
        if not _numeric_goal_bounds_hold(sas_task, state_key):
            return None
        if state_key in solving:
            return None

        solving.add(state_key)
        try:
            best = None

            if _base_goal_satisfied(sas_task, state_key):
                metrics = _closure_metrics_for_state(sas_task, state_key)
                best = (metrics, ("close",))

            for group_key, actions in _normal_action_groups(sas_task, state_key):
                child_metrics = []
                valid = True
                for action in actions:
                    successor = _cached_successor(sas_task, state_key, action)
                    if successor == state_key:
                        valid = False
                        break

                    result = solve(successor)
                    if result is None:
                        valid = False
                        break
                    child_metrics.append(result[0])

                if not valid or not child_metrics:
                    continue

                metrics = StateMetrics(
                    cost_min=min(metric.cost_min for metric in child_metrics),
                    cost_max=max(metric.cost_max for metric in child_metrics),
                    loss_min=min(metric.loss_min for metric in child_metrics),
                    loss_max=max(metric.loss_max for metric in child_metrics),
                )
                candidate = (metrics, ("act", group_key, tuple(actions)))
                if best is None or _metrics_order_key(
                    metrics,
                    seed_order,
                ) < _metrics_order_key(best[0], seed_order):
                    best = candidate

            return best
        finally:
            solving.remove(state_key)

    result = solve(initial_key)
    if result is None:
        return None

    policy = BasicPolicy.make_initial(initial_key)
    building = set()

    # Reconstructs the policy choices selected by the dynamic program.
    def build(state_key):
        if state_key in policy.strategy or sas_task.is_goal_state(*state_key):
            return True
        if state_key in building:
            return False
        building.add(state_key)

        selected = solve(state_key)
        if selected is None:
            building.remove(state_key)
            return False

        _metrics, choice = selected
        if choice[0] == "close":
            ok = _add_closure_strategy(sas_task, policy, state_key)
            building.remove(state_key)
            return ok

        _kind, group_key, actions = choice
        child = _extend_policy(sas_task, policy, state_key, group_key, actions)
        if child is None:
            building.remove(state_key)
            return False

        policy.pending = child.pending
        policy.strategy = child.strategy
        policy.terminal_goals = child.terminal_goals
        policy.state_metrics = child.state_metrics

        for action in actions:
            successor = _cached_successor(sas_task, state_key, action)
            if not build(successor):
                building.remove(state_key)
                return False

        building.remove(state_key)
        return True

    if not build(initial_key):
        return None

    _prepare_policy_for_queue(sas_task, policy)
    if not _policy_is_strong_acyclic_solution(sas_task, policy):
        return None

    values = evaluate_policy(sas_task, policy)
    return SearchSolution(policy, values)


# Handles the internal closure metrics for state step.
def _closure_metrics_for_state(sas_task, state_key):
    sas_state, numeric_state = state_key
    utility = sas_task.utility_of_sas_state(sas_state)
    loss = sas_task.max_utility - utility
    cost = _numeric_cost(sas_task, numeric_state)
    return StateMetrics(
        cost_min=cost,
        cost_max=cost,
        loss_min=loss,
        loss_max=loss,
    )


# Handles the internal metrics order key step.
def _metrics_order_key(metrics, optimization_order):
    values = {
        "loss_max": metrics.loss_max,
        "Cmax": metrics.cost_max,
        "loss_min": metrics.loss_min,
        "Cmin": metrics.cost_min,
        "size": 0,
    }
    return _values_order_key(values, optimization_order)


# Rounds value signature.
def _rounded_value_signature(values):
    return (
        round(values["loss_max"], 9),
        round(values["Cmax"], 9),
        round(values["loss_min"], 9),
        round(values["Cmin"], 9),
    )


# Handles the internal maximin utility seed solution step.
def _maximin_utility_seed_solution(sas_task, optimization_order):
    initial_key = sas_task.state_key(
        sas_task.initial_state,
        sas_task.numeric_initial_state,
    )

    # Solves the current state inside the local dynamic program.
    @lru_cache(maxsize=None)
    def solve(state_key):
        if not _numeric_goal_bounds_hold(sas_task, state_key):
            return -math.inf, None

        best_value = -math.inf
        best_choice = None

        if _base_goal_satisfied(sas_task, state_key):
            best_value = sas_task.utility_of_sas_state(state_key[0])
            best_choice = ("close",)

        for group_key, actions in _normal_action_groups(sas_task, state_key):
            successor_values = []
            valid = True
            for action in actions:
                successor = _cached_successor(sas_task, state_key, action)
                if successor == state_key:
                    valid = False
                    break
                value, _choice = solve(successor)
                if value == -math.inf:
                    valid = False
                    break
                successor_values.append(value)

            if not valid or not successor_values:
                continue

            candidate_value = min(successor_values)
            if candidate_value > best_value:
                best_value = candidate_value
                best_choice = ("act", group_key, tuple(actions))

        return best_value, best_choice

    value, choice = solve(initial_key)
    if value == -math.inf or choice is None:
        return None

    policy = BasicPolicy.make_initial(initial_key)
    building = set()

    # Reconstructs the policy choices selected by the dynamic program.
    def build(state_key):
        if state_key in policy.strategy or sas_task.is_goal_state(*state_key):
            return True
        if state_key in building:
            return False
        building.add(state_key)

        _value, selected = solve(state_key)
        if selected is None:
            building.remove(state_key)
            return False

        if selected[0] == "close":
            ok = _add_closure_strategy(sas_task, policy, state_key)
            building.remove(state_key)
            return ok

        _kind, group_key, actions = selected
        child = _extend_policy(sas_task, policy, state_key, group_key, actions)
        if child is None:
            building.remove(state_key)
            return False

        policy.pending = child.pending
        policy.strategy = child.strategy
        policy.terminal_goals = child.terminal_goals
        policy.state_metrics = child.state_metrics

        for action in actions:
            successor = _cached_successor(sas_task, state_key, action)
            if not build(successor):
                building.remove(state_key)
                return False

        building.remove(state_key)
        return True

    if not build(initial_key):
        return None

    _prepare_policy_for_queue(sas_task, policy)
    if not _policy_is_strong_acyclic_solution(sas_task, policy):
        return None

    values = evaluate_policy(sas_task, policy)
    return SearchSolution(policy, values)


# Collects action groups.
def _normal_action_groups(sas_task, state_key):
    sas_state, numeric_state = state_key
    groups = {}
    for action in sas_task.actions:
        if action.is_fictitious:
            continue
        if not sas_task.is_action_applicable(sas_state, numeric_state, action):
            continue
        key = _action_group_key(action)
        groups.setdefault(key, []).append(action)
    return sorted(groups.items(), key=lambda item: (min(action.index for action in item[1]), item[0]))


# Adds closure strategy.
def _add_closure_strategy(sas_task, policy, state_key):
    current = state_key
    while not sas_task.is_goal_state(*current):
        applicable = [
            action
            for action in sas_task.actions
            if action.is_fictitious
            and sas_task.is_action_applicable(current[0], current[1], action)
        ]
        if not applicable:
            return False

        action = min(applicable, key=lambda candidate: candidate.index)
        group_key = _action_group_key(action)
        child = _extend_policy(sas_task, policy, current, group_key, (action,))
        if child is None:
            return False

        successor = _cached_successor(sas_task, current, action)
        policy.pending = child.pending
        policy.strategy = child.strategy
        policy.terminal_goals = child.terminal_goals
        policy.state_metrics = child.state_metrics
        current = successor

    return True


# Propagates cost and utility-loss metrics through a policy graph.
def propagate_policy_metrics(sas_task, policy):
    initial_metrics = policy.state_metrics.get(
        policy.initial_state,
        StateMetrics(
            cost_min=_numeric_cost(sas_task, policy.initial_state[1]),
            cost_max=_numeric_cost(sas_task, policy.initial_state[1]),
            loss_min=0.0,
            loss_max=0.0,
        ),
    )
    policy.state_metrics = {policy.initial_state: initial_metrics}

    queue = deque([policy.initial_state])
    while queue:
        state = queue.popleft()
        decision = policy.strategy.get(state)
        if decision is None:
            continue

        current = policy.state_metrics[state]
        _group_key, outcomes = decision
        for action, successor in outcomes:
            successor_metrics = _successor_metrics(
                sas_task,
                current,
                successor,
                action,
            )
            if _record_state_metrics(policy, successor, successor_metrics):
                queue.append(successor)


# Collects terminal states reachable from the policy initial state.
def reachable_terminal_states(policy):
    terminals = set()
    visited = set()
    stack = [policy.initial_state]

    while stack:
        state = stack.pop()
        if state in visited:
            continue
        visited.add(state)

        decision = policy.strategy.get(state)
        if decision is None:
            terminals.add(state)
            continue

        _action_key, outcomes = decision
        for _action, successor in outcomes:
            if successor not in visited:
                stack.append(successor)

    return terminals


# Handles the internal policy is strong acyclic solution step.
def _policy_is_strong_acyclic_solution(sas_task, policy):
    if policy.pending:
        return False
    if _has_reachable_strategy_cycle(policy):
        return False
    return _policy_has_only_goal_terminals(sas_task, policy)


# Checks whether the object has reachable strategy cycle.
def _has_reachable_strategy_cycle(policy):
    visiting = set()
    visited = set()

    # Visits a state while detecting reachable strategy cycles.
    def visit(state):
        if state in visiting:
            return True
        if state in visited:
            return False

        visited.add(state)
        decision = policy.strategy.get(state)
        if decision is None:
            return False

        visiting.add(state)
        _group_key, outcomes = decision
        for _action, successor in outcomes:
            if visit(successor):
                return True
        visiting.remove(state)
        return False

    return visit(policy.initial_state)


# Handles the internal close goal pending states step.
def _close_goal_pending_states(sas_task, policy):
    for state_key in list(policy.pending):
        sas_state, numeric_state = state_key
        if sas_task.is_goal_state(sas_state, numeric_state):
            policy.pending.remove(state_key)
            policy.terminal_goals.add(state_key)


# Handles the internal policy has only goal terminals step.
def _policy_has_only_goal_terminals(sas_task, policy):
    terminals = reachable_terminal_states(policy)
    if not terminals:
        return False
    return all(sas_task.is_goal_state(*state) for state in terminals)


# Selects pending state.
def _select_pending_state(
    sas_task,
    policy,
    optimization_order,
    heuristic_cache,
    use_heuristics,
):
    return min(
        policy.pending,
        key=lambda state: _pending_state_order_key(
            sas_task,
            state,
            optimization_order,
            heuristic_cache,
            use_heuristics,
        ),
    )


# Handles the internal applicable action groups step.
def _applicable_action_groups(
    sas_task,
    state_key,
    optimization_order,
    heuristic_cache,
    use_heuristics,
):
    groups = _cached_applicable_action_groups(sas_task, state_key)

    return sorted(
        groups,
        key=lambda item: _action_group_order_key(
            sas_task,
            state_key,
            item[0],
            item[1],
            optimization_order,
            heuristic_cache,
            use_heuristics,
        ),
    )


# Returns cached applicable action groups.
def _cached_applicable_action_groups(sas_task, state_key):
    _ensure_search_caches(sas_task)
    cached = sas_task._applicable_group_cache.get(state_key)
    if cached is not None:
        return cached

    sas_state, numeric_state = state_key
    groups = {}
    base_goal_satisfied = _base_goal_satisfied(sas_task, state_key)

    for action in sas_task.actions:
        if action.is_fictitious and not base_goal_satisfied:
            continue
        if not sas_task.is_action_applicable(sas_state, numeric_state, action):
            continue
        key = _action_group_key(action)
        groups.setdefault(key, []).append(action)

    cached = tuple(
        (group_key, tuple(actions))
        for group_key, actions in groups.items()
    )
    sas_task._applicable_group_cache[state_key] = cached
    return cached


# Handles the internal extend policy step.
def _extend_policy(sas_task, policy, state_key, group_key, actions):
    child = policy.copy()
    child.pending.remove(state_key)
    current_metrics = child.state_metrics[state_key]

    outcomes = []
    for action in actions:
        successor = _cached_successor(sas_task, state_key, action)
        if not _numeric_goal_bounds_hold(sas_task, successor):
            return None
        outcomes.append((action, successor))
        successor_metrics = _successor_metrics(
            sas_task,
            current_metrics,
            successor,
            action,
        )
        _record_state_metrics(child, successor, successor_metrics)

        if sas_task.is_goal_state(*successor):
            child.terminal_goals.add(successor)
        elif successor not in child.strategy:
            child.pending.add(successor)

    child.strategy[state_key] = (group_key, tuple(outcomes))
    return child


# Handles the internal action group key step.
def _action_group_key(action):
    base_name = DETDUP_RE.sub("", action.name)
    return base_name, tuple(action.parameters)


# Handles the internal action group order key step.
def _action_group_order_key(
    sas_task,
    state_key,
    group_key,
    actions,
    optimization_order,
    heuristic_cache,
    use_heuristics,
):
    outcome_values = [
        _action_outcome_order_values(
            sas_task,
            state_key,
            action,
            heuristic_cache,
            use_heuristics,
        )
        for action in actions
    ]

    aggregate = {
        "Umin": min(value["U"] for value in outcome_values),
        "Umax": max(value["U"] for value in outcome_values),
        "Cmax": max(value["C"] for value in outcome_values),
        "Cmin": min(value["C"] for value in outcome_values),
        "Hloss": max(value["Hloss"] for value in outcome_values),
        "Hgoal": max(value["Hgoal"] for value in outcome_values),
    }

    key = []
    for criterion in optimization_order:
        if criterion in {"Umin", "Umax"}:
            key.append(aggregate["Hloss"])
            key.append(-aggregate[criterion])
        elif criterion in {"Cmax", "Cmin"}:
            key.append(aggregate["Hgoal"])
            key.append(aggregate[criterion])
        else:
            raise ValueError(f"Unsupported optimization criterion: {criterion}")

    key.append(min(action.index for action in actions))
    key.append(group_key)
    return tuple(key)


# Handles the internal pending state order key step.
def _pending_state_order_key(
    sas_task,
    state_key,
    optimization_order,
    heuristic_cache,
    use_heuristics,
):
    heuristic = _heuristic_value(
        sas_task,
        state_key,
        heuristic_cache,
        use_heuristics,
    )
    cost = _numeric_cost(sas_task, state_key[1])
    utility = sas_task.utility_of_sas_state(state_key[0])

    key = []
    for criterion in optimization_order:
        if criterion in {"Umin", "Umax"}:
            key.append(heuristic["h_loss"])
            key.append(-utility)
        elif criterion in {"Cmax", "Cmin"}:
            key.append(heuristic["h_goal"])
            key.append(cost)
        else:
            raise ValueError(f"Unsupported optimization criterion: {criterion}")
    key.append(str(state_key))
    return tuple(key)


# Handles the internal action outcome order values step.
def _action_outcome_order_values(
    sas_task,
    state_key,
    action,
    heuristic_cache,
    use_heuristics,
):
    successor = _cached_successor(sas_task, state_key, action)
    heuristic = _heuristic_value(
        sas_task,
        successor,
        heuristic_cache,
        use_heuristics,
    )
    utility = sas_task.utility_of_sas_state(successor[0]) - action.utility_loss
    cost = _numeric_cost(sas_task, successor[1])
    return {
        "U": utility,
        "C": cost,
        "Hloss": heuristic["h_loss"],
        "Hgoal": heuristic["h_goal"],
    }


# Handles the internal heuristic value step.
def _heuristic_value(sas_task, state_key, heuristic_cache, use_heuristics):
    if not use_heuristics:
        return {
            "h_loss": 0.0,
            "h_goal": 0.0,
        }
    cached = heuristic_cache.get(state_key)
    if cached is not None:
        return cached
    value = sas_heuristics.evaluate_state(sas_task, state_key)
    heuristic_cache[state_key] = value
    return value


# Handles the internal successor metrics step.
def _successor_metrics(sas_task, current_metrics, successor, action):
    cost = _numeric_cost(sas_task, successor[1])
    loss_min = current_metrics.loss_min + action.utility_loss
    loss_max = current_metrics.loss_max + action.utility_loss
    return StateMetrics(
        cost_min=cost,
        cost_max=cost,
        loss_min=loss_min,
        loss_max=loss_max,
    )


# Handles the internal record state metrics step.
def _record_state_metrics(policy, state, metrics):
    current = policy.state_metrics.get(state)
    if current is None:
        policy.state_metrics[state] = StateMetrics(*metrics.as_tuple())
        return True

    updated = StateMetrics(
        cost_min=min(current.cost_min, metrics.cost_min),
        cost_max=max(current.cost_max, metrics.cost_max),
        loss_min=min(current.loss_min, metrics.loss_min),
        loss_max=max(current.loss_max, metrics.loss_max),
    )
    if _rounded_metrics(current) == _rounded_metrics(updated):
        return False

    policy.state_metrics[state] = updated
    return True


# Rounds metrics.
def _rounded_metrics(metrics):
    return tuple(round(value, 9) for value in metrics.as_tuple())


# Handles the internal base goal satisfied step.
def _base_goal_satisfied(sas_task, state_key):
    sas_state, numeric_state = state_key
    closure_vars = set(sas_task.soft_goal_closure_vars)
    if not sas_task.goals:
        return True

    for goal in sas_task.goals:
        base_conditions = tuple(
            condition
            for condition in goal.conditions
            if condition.var not in closure_vars
        )
        if (
            sas_task.conditions_hold(sas_state, base_conditions)
            and sas_task.numeric_conditions_hold(numeric_state, goal.numeric_conditions)
        ):
            return True

    return False


# Handles the internal numeric goal bounds hold step.
def _numeric_goal_bounds_hold(sas_task, state_key):
    _sas_state, numeric_state = state_key
    if not sas_task.goals:
        return True
    return any(
        sas_task.numeric_conditions_hold(numeric_state, goal.numeric_conditions)
        for goal in sas_task.goals
    )


# Handles the internal numeric cost step.
def _numeric_cost(sas_task, numeric_state):
    for pos, var in enumerate(sas_task.numeric_variables):
        if str(var.fncIndex) == "total-cost":
            return numeric_state[pos]
    return 0.0
