import math
import re

from grounderTypes import Assignment, GroundedNumericExpressionType


DETDUP_RE = re.compile(r"_DETDUP_\d+$")
DEFAULT_ANDOR_DEPTH = None
EPS = 1e-9
IN_PROGRESS = object()


# Computes all heuristic estimates used for a SAS state.
def evaluate_state(sas_task, state_key):
    value_costs = relaxed_value_costs(sas_task, state_key)
    remaining_budget = _remaining_budget(sas_task, state_key)
    guaranteed_utility = andor_guaranteed_utility(
        sas_task,
        state_key,
        remaining_budget=remaining_budget,
        depth=DEFAULT_ANDOR_DEPTH,
    )
    relaxed_goal = relaxed_goal_distance(sas_task, state_key, value_costs)
    guaranteed_cost = andor_guaranteed_goal_cost(
        sas_task,
        state_key,
        remaining_budget=remaining_budget,
        depth=DEFAULT_ANDOR_DEPTH,
        fallback_cost=relaxed_goal,
    )
    conditional_cost = andor_goal_cost_with_utility_target(
        sas_task,
        state_key,
        target_utility=guaranteed_utility,
        remaining_budget=remaining_budget,
        depth=DEFAULT_ANDOR_DEPTH,
        fallback_cost=relaxed_goal,
    )
    return {
        "h_loss": max(0.0, sas_task.max_utility - guaranteed_utility),
        "h_loss_min": relaxed_utility_loss(sas_task, state_key, value_costs),
        "h_cmax": max(guaranteed_cost, conditional_cost),
        "h_cmax_unconditional": guaranteed_cost,
        "h_cmin": relaxed_goal,
        "h_goal": max(guaranteed_cost, conditional_cost),
    }


# Returns a cached AND-OR estimate of guaranteed remaining utility.
def andor_guaranteed_utility(sas_task, state_key, remaining_budget=None, depth=None):
    cache = getattr(sas_task, "_andor_heuristic_cache", None)
    if cache is None:
        cache = {}
        setattr(sas_task, "_andor_heuristic_cache", cache)

    key = (
        _andor_cache_state_key(sas_task, state_key),
        _budget_cache_key(remaining_budget),
        depth,
    )
    cached = cache.get(key)
    if cached is IN_PROGRESS:
        return relaxed_utility_upper_bound(
            sas_task,
            state_key,
            remaining_budget,
        )
    if cached is not None:
        return cached

    cycle_key = _andor_cycle_key(sas_task, state_key, remaining_budget)
    active = _andor_active_cycles(sas_task, "_andor_utility_active")
    if cycle_key in active:
        return relaxed_utility_upper_bound(
            sas_task,
            state_key,
            remaining_budget,
        )

    active.add(cycle_key)
    cache[key] = IN_PROGRESS
    try:
        value = _compute_andor_guaranteed_utility(
            sas_task,
            state_key,
            remaining_budget,
            depth,
        )
    except BaseException:
        cache.pop(key, None)
        raise
    finally:
        active.remove(cycle_key)
    cache[key] = value
    return value


# Computes andor guaranteed utility.
def _compute_andor_guaranteed_utility(
    sas_task,
    state_key,
    remaining_budget,
    depth,
):
    if remaining_budget is not None and remaining_budget < -EPS:
        return -math.inf

    if _base_goal_satisfied(sas_task, state_key):
        return sas_task.utility_of_sas_state(state_key[0])

    if depth is not None and depth <= 0:
        return relaxed_utility_upper_bound(
            sas_task,
            state_key,
            remaining_budget,
        )

    groups = _nondeterministic_successor_groups(sas_task, state_key)
    if not groups:
        return relaxed_utility_upper_bound(
            sas_task,
            state_key,
            remaining_budget,
        )

    best_action_value = -math.inf
    current_cost = _numeric_cost(sas_task, state_key[1])

    for successors in groups.values():
        merged_successors = _merge_successors_by_remaining_budget(
            successors,
            remaining_budget,
            current_cost,
            sas_task,
        )
        if not merged_successors:
            continue

        worst_outcome_value = math.inf
        next_depth = None if depth is None else depth - 1
        for successor, successor_budget in merged_successors:
            successor_value = andor_guaranteed_utility(
                sas_task,
                successor,
                remaining_budget=successor_budget,
                depth=next_depth,
            )
            worst_outcome_value = min(worst_outcome_value, successor_value)

        best_action_value = max(best_action_value, worst_outcome_value)

    if best_action_value == -math.inf:
        return relaxed_utility_upper_bound(
            sas_task,
            state_key,
            remaining_budget,
        )
    return best_action_value


# Computes a relaxed upper bound on reachable utility.
def relaxed_utility_upper_bound(sas_task, state_key, remaining_budget=None):
    if remaining_budget is not None and remaining_budget < -EPS:
        return -math.inf

    value_costs = relaxed_value_costs(sas_task, state_key)
    total = 0.0
    for var_index in _utility_vars(sas_task):
        best_utility = 0.0
        for value_index in range(len(sas_task.variables[var_index].values)):
            cost = value_costs.get((var_index, value_index), math.inf)
            if remaining_budget is not None and cost > remaining_budget + EPS:
                continue
            if cost < math.inf:
                best_utility = max(
                    best_utility,
                    sas_task.utility_by_sas_value.get((var_index, value_index), 0.0),
                )
        total += best_utility
    return total


# Returns a cached AND-OR estimate of guaranteed goal cost.
def andor_guaranteed_goal_cost(
    sas_task,
    state_key,
    remaining_budget=None,
    depth=None,
    fallback_cost=None,
):
    cache = getattr(sas_task, "_andor_cost_cache", None)
    if cache is None:
        cache = {}
        setattr(sas_task, "_andor_cost_cache", cache)

    key = (
        _andor_cache_state_key(sas_task, state_key),
        _budget_cache_key(remaining_budget),
        depth,
    )
    cached = cache.get(key)
    if cached is IN_PROGRESS:
        return _goal_cost_fallback(sas_task, state_key, fallback_cost)
    if cached is not None:
        return cached

    cycle_key = _andor_cycle_key(sas_task, state_key, remaining_budget)
    active = _andor_active_cycles(sas_task, "_andor_cost_active")
    if cycle_key in active:
        return _goal_cost_fallback(sas_task, state_key, fallback_cost)

    active.add(cycle_key)
    cache[key] = IN_PROGRESS
    try:
        value = _compute_andor_guaranteed_goal_cost(
            sas_task,
            state_key,
            remaining_budget,
            depth,
            fallback_cost,
        )
    except BaseException:
        cache.pop(key, None)
        raise
    finally:
        active.remove(cycle_key)
    cache[key] = value
    return value


# Computes andor guaranteed goal cost.
def _compute_andor_guaranteed_goal_cost(
    sas_task,
    state_key,
    remaining_budget,
    depth,
    fallback_cost,
):
    if remaining_budget is not None and remaining_budget < -EPS:
        return math.inf

    if _base_goal_satisfied(sas_task, state_key):
        return 0.0

    if depth is not None and depth <= 0:
        return _goal_cost_fallback(sas_task, state_key, fallback_cost)

    groups = _nondeterministic_successor_groups(sas_task, state_key)
    if not groups:
        return _goal_cost_fallback(sas_task, state_key, fallback_cost)

    current_cost = _numeric_cost(sas_task, state_key[1])
    best_action_cost = math.inf
    next_depth = None if depth is None else depth - 1

    for successors in groups.values():
        merged_successors = _merge_successors_by_remaining_budget(
            successors,
            remaining_budget,
            current_cost,
            sas_task,
        )
        if not merged_successors:
            continue

        worst_outcome_cost = -math.inf
        action_is_feasible = True
        for successor, successor_budget in merged_successors:
            successor_cost = _numeric_cost(sas_task, successor[1])
            transition_cost = successor_cost - current_cost
            if transition_cost < -EPS:
                action_is_feasible = False
                break

            remaining_cost = andor_guaranteed_goal_cost(
                sas_task,
                successor,
                remaining_budget=successor_budget,
                depth=next_depth,
            )
            if remaining_cost == math.inf:
                action_is_feasible = False
                break

            worst_outcome_cost = max(
                worst_outcome_cost,
                transition_cost + remaining_cost,
            )

        if action_is_feasible and worst_outcome_cost < best_action_cost:
            best_action_cost = worst_outcome_cost

    if best_action_cost == math.inf:
        return _goal_cost_fallback(sas_task, state_key, fallback_cost)
    return best_action_cost


# Handles the internal goal cost fallback step.
def _goal_cost_fallback(sas_task, state_key, fallback_cost):
    if fallback_cost is not None:
        return fallback_cost
    return relaxed_goal_distance(sas_task, state_key)


# Estimates goal cost while preserving a target utility level.
def andor_goal_cost_with_utility_target(
    sas_task,
    state_key,
    target_utility,
    remaining_budget=None,
    depth=None,
    fallback_cost=None,
):
    cache = getattr(sas_task, "_andor_conditional_cost_cache", None)
    if cache is None:
        cache = {}
        setattr(sas_task, "_andor_conditional_cost_cache", cache)

    target_key = round(target_utility, 9)
    key = (
        _andor_cache_state_key(sas_task, state_key),
        target_key,
        _budget_cache_key(remaining_budget),
        depth,
    )
    cached = cache.get(key)
    if cached is IN_PROGRESS:
        return _conditional_goal_cost_fallback(
            sas_task,
            state_key,
            target_utility,
            remaining_budget,
            fallback_cost,
        )
    if cached is not None:
        return cached

    cycle_key = _andor_cycle_key(sas_task, state_key, remaining_budget)
    active = _andor_active_cycles(sas_task, "_andor_conditional_active")
    if cycle_key in active:
        return _conditional_goal_cost_fallback(
            sas_task,
            state_key,
            target_utility,
            remaining_budget,
            fallback_cost,
        )

    active.add(cycle_key)
    cache[key] = IN_PROGRESS
    try:
        value = _compute_andor_goal_cost_with_utility_target(
            sas_task,
            state_key,
            target_utility,
            remaining_budget,
            depth,
            fallback_cost,
        )
    except BaseException:
        cache.pop(key, None)
        raise
    finally:
        active.remove(cycle_key)
    cache[key] = value
    return value


# Computes andor goal cost with utility target.
def _compute_andor_goal_cost_with_utility_target(
    sas_task,
    state_key,
    target_utility,
    remaining_budget,
    depth,
    fallback_cost,
):
    if remaining_budget is not None and remaining_budget < -EPS:
        return math.inf

    current_utility = sas_task.utility_of_sas_state(state_key[0])
    if _base_goal_satisfied(sas_task, state_key):
        if current_utility + EPS >= target_utility:
            return 0.0
        return math.inf

    if depth is not None and depth <= 0:
        return _conditional_goal_cost_fallback(
            sas_task,
            state_key,
            target_utility,
            remaining_budget,
            fallback_cost,
        )

    groups = _nondeterministic_successor_groups(sas_task, state_key)
    if not groups:
        return _conditional_goal_cost_fallback(
            sas_task,
            state_key,
            target_utility,
            remaining_budget,
            fallback_cost,
        )

    current_cost = _numeric_cost(sas_task, state_key[1])
    best_action_cost = math.inf
    next_depth = None if depth is None else depth - 1

    for successors in groups.values():
        merged_successors = _merge_successors_by_remaining_budget(
            successors,
            remaining_budget,
            current_cost,
            sas_task,
        )
        if not merged_successors:
            continue

        worst_outcome_cost = -math.inf
        action_is_feasible = True
        for successor, successor_budget in merged_successors:
            successor_cost = _numeric_cost(sas_task, successor[1])
            transition_cost = successor_cost - current_cost
            if transition_cost < -EPS:
                action_is_feasible = False
                break

            remaining_cost = andor_goal_cost_with_utility_target(
                sas_task,
                successor,
                target_utility=target_utility,
                remaining_budget=successor_budget,
                depth=next_depth,
                fallback_cost=None,
            )
            if remaining_cost == math.inf:
                action_is_feasible = False
                break

            worst_outcome_cost = max(
                worst_outcome_cost,
                transition_cost + remaining_cost,
            )

        if action_is_feasible and worst_outcome_cost < best_action_cost:
            best_action_cost = worst_outcome_cost

    if best_action_cost == math.inf:
        return _conditional_goal_cost_fallback(
            sas_task,
            state_key,
            target_utility,
            remaining_budget,
            fallback_cost,
        )
    return best_action_cost


# Handles the internal conditional goal cost fallback step.
def _conditional_goal_cost_fallback(
    sas_task,
    state_key,
    target_utility,
    remaining_budget,
    fallback_cost,
):
    relaxed_upper = relaxed_utility_upper_bound(
        sas_task,
        state_key,
        remaining_budget,
    )
    if relaxed_upper + EPS < target_utility:
        return math.inf
    return _goal_cost_fallback(sas_task, state_key, fallback_cost)


# Estimates the minimum utility loss under delete relaxation.
def relaxed_utility_loss(sas_task, state_key, value_costs=None):
    if value_costs is None:
        value_costs = relaxed_value_costs(sas_task, state_key)

    loss = 0.0
    for var_index in _utility_vars(sas_task):
        max_utility = _max_var_utility(sas_task, var_index)
        best_reachable_utility = 0.0
        for value_index in range(len(sas_task.variables[var_index].values)):
            if value_costs.get((var_index, value_index), math.inf) < math.inf:
                best_reachable_utility = max(
                    best_reachable_utility,
                    sas_task.utility_by_sas_value.get((var_index, value_index), 0.0),
                )
        loss += max_utility - best_reachable_utility
    return loss


# Estimates relaxed cost distance to the hard goal.
def relaxed_goal_distance(sas_task, state_key, value_costs=None):
    if value_costs is None:
        value_costs = relaxed_value_costs(sas_task, state_key)

    if not sas_task.goals:
        return 0.0

    closure_vars = set(sas_task.soft_goal_closure_vars)
    distances = []
    for goal in sas_task.goals:
        if not sas_task.numeric_conditions_hold(state_key[1], goal.numeric_conditions):
            continue

        goal_distance = 0.0
        reachable = True
        for condition in goal.conditions:
            if condition.var in closure_vars:
                continue
            cost = value_costs.get((condition.var, condition.value), math.inf)
            if cost == math.inf:
                reachable = False
                break
            goal_distance = max(goal_distance, cost)

        if reachable:
            distances.append(goal_distance)

    if not distances:
        return math.inf
    return min(distances)


# Computes relaxed reachability costs for SAS variable values.
def relaxed_value_costs(sas_task, state_key):
    cache = getattr(sas_task, "_relaxed_value_cost_cache", None)
    if cache is None:
        cache = {}
        setattr(sas_task, "_relaxed_value_cost_cache", cache)
    cache_key = _logical_state_key(sas_task, state_key)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    sas_state, _numeric_state = state_key
    value_costs = {}
    for var_index, value_index in enumerate(sas_state):
        value_costs[(var_index, value_index)] = 0.0

    changed = True
    while changed:
        changed = False
        for action in sas_task.actions:
            if action.is_fictitious:
                continue

            pre_cost = 0.0
            reachable = True
            for condition in action.conditions:
                cost = value_costs.get((condition.var, condition.value), math.inf)
                if cost == math.inf:
                    reachable = False
                    break
                pre_cost = max(pre_cost, cost)

            if not reachable:
                continue

            action_cost = _constant_budget_cost(sas_task, action)
            if action_cost is None:
                action_cost = 0.0
            next_cost = pre_cost + action_cost

            for effect in action.effects:
                key = (effect.var, effect.value)
                if next_cost < value_costs.get(key, math.inf):
                    value_costs[key] = next_cost
                    changed = True

    cache[cache_key] = value_costs
    return value_costs


# Handles the internal utility vars step.
def _utility_vars(sas_task):
    return sorted(
        {
            var_index
            for (var_index, _value_index), utility in sas_task.utility_by_sas_value.items()
            if utility > 0.0
        }
    )


# Handles the internal max var utility step.
def _max_var_utility(sas_task, var_index):
    return max(
        sas_task.utility_by_sas_value.get((var_index, value_index), 0.0)
        for value_index in range(len(sas_task.variables[var_index].values))
    )


# Handles the internal constant budget cost step.
def _constant_budget_cost(sas_task, action):
    total_cost = 0.0
    found = False
    for effect in action.numeric_effects:
        if not _is_total_cost_var(sas_task, effect.varIndex):
            continue
        found = True
        if effect.assignment != Assignment.AS_INCREASE:
            return None

        value = _constant_numeric_expression_value(effect.exp)
        if value is None:
            return None
        total_cost += value

    if not found:
        return 0.0

    if total_cost < 0.0:
        return None
    return total_cost


# Checks whether total cost var.
def _is_total_cost_var(sas_task, var_index):
    for var in sas_task.numeric_variables:
        if var.index == var_index:
            return str(var.fncIndex) == "total-cost"
    return False


# Handles the internal constant numeric expression value step.
def _constant_numeric_expression_value(expression):
    expression_type = expression.type

    if expression_type == GroundedNumericExpressionType.GE_NUMBER:
        return float(expression.value)

    if expression_type == GroundedNumericExpressionType.GE_SUM:
        values = [_constant_numeric_expression_value(sub) for sub in expression.terms]
        if any(value is None for value in values):
            return None
        return sum(values)

    if expression_type == GroundedNumericExpressionType.GE_SUB:
        values = [_constant_numeric_expression_value(sub) for sub in expression.terms]
        if any(value is None for value in values):
            return None
        if len(values) == 1:
            return -values[0]
        result = values[0]
        for value in values[1:]:
            result -= value
        return result

    if expression_type == GroundedNumericExpressionType.GE_MUL:
        values = [_constant_numeric_expression_value(sub) for sub in expression.terms]
        if any(value is None for value in values):
            return None
        result = 1.0
        for value in values:
            result *= value
        return result

    if expression_type == GroundedNumericExpressionType.GE_DIV:
        values = [_constant_numeric_expression_value(sub) for sub in expression.terms]
        if any(value is None for value in values) or len(values) != 2:
            return None
        return values[0] / values[1]

    return None


# Handles the internal nondeterministic successor groups step.
def _nondeterministic_successor_groups(sas_task, state_key):
    cache = getattr(sas_task, "_andor_successor_group_cache", None)
    if cache is None:
        cache = {}
        setattr(sas_task, "_andor_successor_group_cache", cache)
    cached = cache.get(state_key)
    if cached is not None:
        return cached

    sas_state, numeric_state = state_key
    groups = {}

    for action in sas_task.actions:
        if action.is_fictitious:
            continue
        if not sas_task.is_action_applicable(sas_state, numeric_state, action):
            continue

        successor = _cached_successor(sas_task, state_key, action)
        if not _numeric_goal_bounds_hold(sas_task, successor):
            continue

        key = _action_group_key(action)
        groups.setdefault(key, []).append(successor)

    cached = {
        group_key: tuple(successors)
        for group_key, successors in groups.items()
    }
    cache[state_key] = cached
    return cached


# Handles the internal action group key step.
def _action_group_key(action):
    base_name = DETDUP_RE.sub("", action.name)
    return base_name, tuple(action.parameters)


# Returns cached successor.
def _cached_successor(sas_task, state_key, action):
    cache = getattr(sas_task, "_andor_successor_cache", None)
    if cache is None:
        cache = {}
        setattr(sas_task, "_andor_successor_cache", cache)

    key = (state_key, action.index)
    cached = cache.get(key)
    if cached is not None:
        return cached

    successor = sas_task.apply_action(state_key[0], state_key[1], action)
    cache[key] = successor
    return successor


# Merges successors by remaining budget.
def _merge_successors_by_remaining_budget(
    successors,
    remaining_budget,
    parent_cost,
    sas_task,
):
    best_by_state = {}

    for successor in successors:
        if remaining_budget is None:
            successor_budget = None
        else:
            successor_cost = _numeric_cost(sas_task, successor[1])
            action_cost = successor_cost - parent_cost
            if action_cost < -EPS:
                continue
            successor_budget = remaining_budget - action_cost

        if successor not in best_by_state:
            best_by_state[successor] = successor_budget
            continue

        previous_budget = best_by_state[successor]
        if previous_budget is None:
            continue
        if successor_budget is None or successor_budget > previous_budget:
            best_by_state[successor] = successor_budget

    return tuple(best_by_state.items())


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


# Computes the remaining budget from the custom problem bound.
def _remaining_budget(sas_task, state_key):
    if getattr(sas_task, "cost_bound_criterion", "Cmax") == "Cmin":
        return None

    bound = getattr(sas_task, "cost_bound", None)
    if bound is None:
        return None

    _sas_state, numeric_state = state_key
    current_cost = _numeric_cost(sas_task, numeric_state)
    return float(bound) - current_cost


# Handles the internal numeric cost step.
def _numeric_cost(sas_task, numeric_state):
    for pos, var in enumerate(sas_task.numeric_variables):
        if str(var.fncIndex) == "total-cost":
            return numeric_state[pos]
    return 0.0


# Handles the internal budget cache key step.
def _budget_cache_key(remaining_budget):
    if remaining_budget is None:
        return None
    return round(remaining_budget, 9)


# Identifies logical AND/OR cycles without treating accumulated cost as state.
def _andor_cycle_key(sas_task, state_key, remaining_budget):
    return (
        _logical_state_key(sas_task, state_key),
        _budget_cache_key(remaining_budget),
    )


# Uses logical state identity while budget remains a separate cache dimension.
def _andor_cache_state_key(sas_task, state_key):
    return _logical_state_key(sas_task, state_key)


# Returns exact identity unless the task proves total-cost is a pure metric.
def _logical_state_key(sas_task, state_key):
    key_builder = getattr(sas_task, "logical_state_key", None)
    if key_builder is None:
        return state_key
    return key_builder(state_key)


# Returns the active logical states for one recursive AND/OR estimate.
def _andor_active_cycles(sas_task, attribute):
    active = getattr(sas_task, attribute, None)
    if active is None:
        active = set()
        setattr(sas_task, attribute, active)
    return active
