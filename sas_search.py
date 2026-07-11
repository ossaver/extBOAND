from collections import deque
from dataclasses import dataclass, field
import heapq
import math
import re
import time

import sas_heuristics


DETDUP_RE = re.compile(r"_DETDUP_\d+$")
EPS = 1e-9


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
    _configure_cost_bound_criterion(sas_task, optimization_order)
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
            if _has_reachable_strategy_cycle(sas_task, child):
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
    _configure_cost_bound_criterion(sas_task, optimization_order)
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


# Runs bi-objective BOAND* over the first two optimization criteria.
def boand_star_policy_search(
    sas_task,
    max_expansions=None,
    optimization_order=("Umin", "Cmax", "Umax", "Cmin"),
    use_heuristics=True,
    max_solutions=None,
    report_every=10000,
    on_solution=None,
):
    objective_order = tuple(optimization_order[:2])
    tie_break_order = tuple(optimization_order[2:])
    if len(objective_order) != 2:
        raise ValueError("BOAND* requires exactly two primary objectives")
    _configure_cost_bound_criterion(sas_task, optimization_order)

    initial_key = sas_task.state_key(
        sas_task.initial_state,
        sas_task.numeric_initial_state,
    )
    initial_policy = BasicPolicy.make_initial(initial_key)
    heuristic_cache = {}
    open_list = []
    seen = set()
    solutions = []
    q2_last = math.inf
    counter = 0
    expansions = 0
    generated = 1
    max_open = 0
    iterations = 0
    start_time = time.time()
    bootstrap_solution = _bootstrap_feasible_solution(
        sas_task,
        optimization_order,
        max_expansions=1000,
        use_heuristics=use_heuristics,
    )
    incumbents = [bootstrap_solution] if bootstrap_solution is not None else []
    anytime_solution_offset = 0

    if bootstrap_solution is not None:
        print(
            "Bootstrap feasible solution: "
            + _format_order_values(bootstrap_solution.values, optimization_order)
            + f" size={len(bootstrap_solution.policy.strategy)}",
            flush=True,
        )
        if on_solution is not None:
            on_solution(
                bootstrap_solution,
                1,
                {
                    "iterations": 0,
                    "expansions": 0,
                    "generated": 1,
                    "max_open": 0,
                    "elapsed_time": time.time() - start_time,
                },
            )
            anytime_solution_offset = 1

    _ensure_search_caches(sas_task)

    print(f"BOAND* objectives: {','.join(objective_order)}", flush=True)
    print(
        f"Cost bound criterion: {sas_task.cost_bound_criterion}",
        flush=True,
    )
    print(
        "Open-list tie-breakers: "
        + (",".join(tie_break_order) if tie_break_order else "<none>"),
        flush=True,
    )
    if max_expansions is None:
        print("Max expansions: unbounded", flush=True)
    else:
        print(f"Max expansions: {max_expansions}", flush=True)
    andor_depth = getattr(sas_heuristics, "DEFAULT_ANDOR_DEPTH", None)
    if andor_depth is None:
        print("AND/OR Umin depth: unbounded", flush=True)
    else:
        print(f"AND/OR Umin depth: {andor_depth}", flush=True)

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

    while open_list:
        max_open = max(max_open, len(open_list))
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

        if _violates_total_cost_bound(sas_task, f_values):
            continue
        if _bound_dominated_by_incumbent(
            f_values,
            incumbents,
            objective_order,
        ):
            continue
        if _bound_pruned_by_last_solution(f_values, objective_order, q2_last):
            continue

        _prepare_policy_for_queue(sas_task, policy)

        if not policy.pending:
            if _policy_is_strong_acyclic_solution(sas_task, policy):
                values = evaluate_policy(sas_task, policy)
                if _violates_total_cost_bound(sas_task, values):
                    continue
                if any(
                    _solution_values_dominate(
                        incumbent.values,
                        values,
                        objective_order,
                    )
                    for incumbent in incumbents
                ):
                    continue
                _require_goal_aware_objectives(
                    f_values,
                    values,
                    objective_order,
                )
                q2_last = _criterion_min_value(values, objective_order[1])
                accepted = SearchSolution(
                    policy,
                    values,
                    certified=True,
                )
                solutions.append(accepted)
                incumbents = _update_incumbents(
                    incumbents,
                    accepted,
                    objective_order,
                )
                _print_solution_progress(
                    values,
                    optimization_order,
                    iteration=iterations,
                    expansions=expansions,
                    generated=generated,
                    solution_count=len(solutions),
                    start_time=start_time,
                )
                if on_solution is not None:
                    on_solution(
                        accepted,
                        len(solutions) + anytime_solution_offset,
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
                        "solution limit reached; Pareto coverage is incomplete",
                    )
            continue

        if _has_reachable_strategy_cycle(sas_task, policy):
            continue

        if max_expansions is not None and expansions >= max_expansions:
            reason = (
                f"max expansions reached ({max_expansions}); "
                "Pareto coverage is incomplete"
            )
            partial_solutions = _merge_bootstrap_solution(
                solutions,
                bootstrap_solution,
                objective_order,
                certified=False,
            )
            return _make_front_result(
                partial_solutions,
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
            if _has_reachable_strategy_cycle(sas_task, child):
                continue

            child_f = evaluate_policy_lower_bound(
                sas_task,
                child,
                heuristic_cache,
                use_heuristics,
            )
            if _has_infinite_objective_component(child_f, objective_order):
                continue
            if _violates_total_cost_bound(sas_task, child_f):
                continue
            if _bound_dominated_by_incumbent(
                child_f,
                incumbents,
                objective_order,
            ):
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

    solutions = _merge_bootstrap_solution(
        solutions,
        bootstrap_solution,
        objective_order,
        certified=True,
    )
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
    logical_state = _logical_state_key(sas_task, state_key)
    if state_key in solved:
        return dict(solved[state_key])
    if state_key in failed or logical_state in path:
        return None
    if max_expansions is not None and counters["expansions"] >= max_expansions:
        return None

    counters["expansions"] += 1
    path.add(logical_state)

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

        path.remove(logical_state)
        solved[state_key] = dict(candidate_strategy)
        return candidate_strategy

    path.remove(logical_state)
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


# Returns a criterion value in the common minimization orientation.
def _criterion_min_value(values, criterion):
    if criterion == "Umin":
        return values["loss_max"]
    if criterion == "Cmax":
        return values["Cmax"]
    if criterion == "Umax":
        return values["loss_min"]
    if criterion == "Cmin":
        return values["Cmin"]
    raise ValueError(f"Unsupported optimization criterion: {criterion}")


# Applies the bound to whichever cost criterion appears first in the key.
def _cost_bound_criterion(optimization_order):
    try:
        cmin_index = optimization_order.index("Cmin")
        cmax_index = optimization_order.index("Cmax")
    except ValueError as exc:
        raise ValueError(
            "The optimization order must contain both Cmin and Cmax"
        ) from exc
    return "Cmin" if cmin_index < cmax_index else "Cmax"


# Configures the budget semantics before any heuristic evaluation.
def _configure_cost_bound_criterion(sas_task, optimization_order):
    sas_task.cost_bound_criterion = _cost_bound_criterion(
        tuple(optimization_order)
    )


# Finds a quick feasible policy used only as a dominance incumbent.
def _bootstrap_feasible_solution(
    sas_task,
    optimization_order,
    max_expansions,
    use_heuristics,
):
    if not getattr(sas_task, "soft_goals_compiled", False):
        return None

    result = depth_first_and_or_search(
        sas_task,
        max_expansions=max_expansions,
        optimization_order=optimization_order,
        use_heuristics=use_heuristics,
    )
    if not result.found or _violates_total_cost_bound(sas_task, result.values):
        return None
    return SearchSolution(result.policy, result.values, certified=False)


# Checks whether a feasible incumbent weakly dominates an optimistic bound.
def _bound_dominated_by_incumbent(bound, incumbents, objective_order):
    return any(
        all(
            _criterion_min_value(incumbent.values, criterion)
            <= _safe_dominance_bound_value(bound, criterion) + EPS
            for criterion in objective_order
        )
        for incumbent in incumbents
    )


# Returns a conservative optimistic value suitable for incumbent pruning.
def _safe_dominance_bound_value(bound, criterion):
    if criterion == "Umin":
        # The guaranteed-utility heuristic can stop at an already satisfied
        # base goal.  loss_min is the relaxed best-outcome loss and is therefore
        # a safe lower bound for every descendant's worst-outcome loss.
        return bound["loss_min"]
    if criterion == "Cmax":
        return bound.get("Cmax_budget", bound["Cmax"])
    return _criterion_min_value(bound, criterion)


# Maintains the nondominated feasible incumbent set.
def _update_incumbents(incumbents, candidate, objective_order):
    if any(
        _solution_values_dominate(
            incumbent.values,
            candidate.values,
            objective_order,
        )
        for incumbent in incumbents
    ):
        return incumbents

    return [
        incumbent
        for incumbent in incumbents
        if not _solution_values_dominate(
            candidate.values,
            incumbent.values,
            objective_order,
        )
    ] + [candidate]


# Compares two complete feasible objective vectors.
def _solution_values_dominate(left, right, objective_order):
    return all(
        _criterion_min_value(left, criterion)
        <= _criterion_min_value(right, criterion) + EPS
        for criterion in objective_order
    )


# Adds the bootstrap policy to the returned Pareto set when it remains relevant.
def _merge_bootstrap_solution(
    solutions,
    bootstrap_solution,
    objective_order,
    certified,
):
    if bootstrap_solution is None:
        return solutions

    merged = _update_incumbents(
        list(solutions),
        bootstrap_solution,
        objective_order,
    )
    if bootstrap_solution in merged:
        bootstrap_solution.certified = certified
    return sorted(
        merged,
        key=lambda solution: tuple(
            _criterion_min_value(solution.values, criterion)
            for criterion in objective_order
        ),
    )


# Builds the fixed lexicographic key; criteria after the first two only break ties.
def _values_order_key(values, optimization_order):
    key = [
        _criterion_min_value(values, criterion)
        for criterion in optimization_order
    ]
    key.append(-values.get("size", 0))
    return tuple(key)


# Applies BOAND*'s constant-time dominance check at extraction time.
def _bound_pruned_by_last_solution(bound_values, objective_order, q2_last):
    if q2_last == math.inf:
        return False
    f2 = _criterion_min_value(bound_values, objective_order[1])
    return q2_last <= f2 + EPS


# Enforces the goal-aware condition required by BOAND*.
def _require_goal_aware_objectives(bound_values, solution_values, objective_order):
    for criterion in objective_order:
        bound = _criterion_min_value(bound_values, criterion)
        exact = _criterion_min_value(solution_values, criterion)
        if not math.isclose(bound, exact, rel_tol=0.0, abs_tol=EPS):
            raise ValueError(
                f"BOAND* requires a goal-aware f-value for {criterion}: "
                f"bound={bound}, exact={exact}"
            )


# Ignores infinite tie-breaker values when deciding objective feasibility.
def _has_infinite_objective_component(values, objective_order):
    return any(
        math.isinf(_criterion_min_value(values, criterion))
        for criterion in objective_order
    )


# Handles the internal violates total cost bound step.
def _violates_total_cost_bound(sas_task, values):
    bound = getattr(sas_task, "cost_bound", None)
    if bound is None:
        return False

    criterion = getattr(sas_task, "cost_bound_criterion", "Cmax")
    if criterion == "Cmin":
        return values["Cmin"] > bound + EPS
    if criterion != "Cmax":
        raise ValueError(f"Unsupported cost bound criterion: {criterion}")

    budget_cmax = values.get("Cmax_budget")
    if budget_cmax is None:
        budget_cmax = values["Cmax"]
    return budget_cmax > bound + EPS


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
):
    elapsed = time.time() - start_time
    print(
        f"SOLUTION at it={iteration}: "
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
    print(
        f"[{elapsed:8.1f}s] "
        f"it={iterations} exp={expansions} gen={generated} "
        f"open={open_size} max_open={max_open} "
        f"key={order_key} "
        f"bound={_format_order_values(values, optimization_order)} "
        f"policy_size={len(policy.strategy)} pending={len(policy.pending)} "
        f"solutions={len(solutions)} best={best_text} "
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
    if _has_reachable_strategy_cycle(sas_task, policy):
        return False
    return _policy_has_only_goal_terminals(sas_task, policy)


# Checks for cycles over logical states, ignoring pure accumulated cost.
def _has_reachable_strategy_cycle(sas_task, policy):
    visiting = set()
    visited = set()

    # Visits a state while detecting reachable strategy cycles.
    def visit(state):
        logical_state = _logical_state_key(sas_task, state)
        if logical_state in visiting:
            return True
        if state in visited:
            return False

        visited.add(state)
        decision = policy.strategy.get(state)
        if decision is None:
            return False

        visiting.add(logical_state)
        _group_key, outcomes = decision
        for _action, successor in outcomes:
            if visit(successor):
                return True
        visiting.remove(logical_state)
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
        if not _canonical_closure_action_allowed(sas_task, sas_state, action):
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


# Removes equivalent permutations of the compiled soft-goal closure phase.
def _canonical_closure_action_allowed(sas_task, sas_state, action):
    closure_vars = tuple(getattr(sas_task, "soft_goal_closure_vars", ()))
    if not closure_vars:
        return True

    open_vars = [var for var in closure_vars if sas_state[var] == 0]
    closure_started = len(open_vars) < len(closure_vars)

    if not action.is_fictitious:
        # Once one utility has been frozen, closure is an atomic terminal phase.
        return not closure_started

    if not open_vars:
        return False

    # All closure actions commute.  Closing the first open variable gives one
    # canonical representative for every equivalent permutation.
    next_var = open_vars[0]
    return any(
        effect.var == next_var and effect.value == 1
        for effect in action.effects
    )


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
    cache_key = _heuristic_cache_key(sas_task, state_key)
    cached = heuristic_cache.get(cache_key)
    if cached is not None:
        return cached
    value = sas_heuristics.evaluate_state(sas_task, state_key)
    heuristic_cache[cache_key] = value
    return value


# Reuses Cmin heuristics across states that differ only in accumulated cost.
def _heuristic_cache_key(sas_task, state_key):
    if getattr(sas_task, "cost_bound_criterion", "Cmax") == "Cmin":
        return _logical_state_key(sas_task, state_key)
    return state_key


# Returns the state identity relevant to planning decisions.
def _logical_state_key(sas_task, state_key):
    key_builder = getattr(sas_task, "logical_state_key", None)
    if key_builder is None:
        return state_key
    return key_builder(state_key)


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
