from grounderTypes import (Comparator, Assignment,
                           GroundedNumericExpressionType,
                           BOOL_TRUE, BOOL_FALSE)
from pathlib import Path

# Finds a numeric variable by its grounded function name.
def find_numeric_variable_by_name(task, name):
    for v in task.variables:
        if v.isNumeric and str(v.fncIndex) == name:
            return v.index
    return None

# Extracts the total-cost budget constraint from the task goals.
def extract_budget_constraint(task, grounder):
    if len(task.goals) == 0:
        return {"enabled": False, "value": None}

    if len(task.goals) > 1:
        raise ValueError("Se esperaba un único goal sintético al extraer el budget.")

    goal_action = task.goals[0]
    budget_value = None

    for cond in goal_action.numericConditions:
        maybe_budget = _extract_budget_from_numeric_condition(task, cond)
        if maybe_budget is None:
            continue

        if budget_value is not None:
            raise ValueError(
                "Se han detectado varias restricciones de budget sobre total-cost. "
                "De momento solo se soporta una."
            )

        budget_value = maybe_budget

    if budget_value is None:
        return {"enabled": False, "value": None}

    return {"enabled": True, "value": budget_value}

# Checks whether a numeric condition is a total-cost budget bound.
def is_budget_numeric_condition(task, cond):
    return _extract_budget_from_numeric_condition(task, cond) is not None
    
# Extracts budget from numeric condition.
def _extract_budget_from_numeric_condition(task, cond):
    if len(cond.terms) != 2:
        return None

    left, right = cond.terms

    # Caso canónico: total-cost <= N
    if (
        cond.comparator == Comparator.CMP_LESS_EQ
        and _is_total_cost_var(task, left)
        and right.type == GroundedNumericExpressionType.GE_NUMBER
    ):
        return float(right.value)

    # Caso robusto equivalente: N >= total-cost
    if (
        cond.comparator == Comparator.CMP_GREATER_EQ
        and left.type == GroundedNumericExpressionType.GE_NUMBER
        and _is_total_cost_var(task, right)
    ):
        return float(left.value)

    return None

# Checks whether total cost var.
def _is_total_cost_var(task, expr):
    if expr.type != GroundedNumericExpressionType.GE_VAR:
        return False

    if expr.index < 0 or expr.index >= len(task.variables):
        return False

    var = task.variables[expr.index]
    return bool(var.isNumeric) and str(var.fncIndex) == "total-cost"

# Builds the legacy search initial state.
def get_initial_state(search_task):
    task = search_task.task

    true_props = set()
    numeric_values = [0.0] * len(search_task.numeric_var_indices)

    for var in task.variables:
        if var.isNumeric:
            pos = search_task.numeric_var_to_pos[var.index]
            if len(var.initialValues) > 0:
                numeric_values[pos] = float(var.initialValues[0].numericValue)
            else:
                numeric_values[pos] = 0.0
        else:
            if len(var.initialValues) > 0 and var.initialValues[0].value == BOOL_TRUE:
                true_props.add(var.index)

    state = (frozenset(true_props), tuple(numeric_values))
    search_task.initial_state = state
    return state
    
# Checks whether a propositional variable is true in a legacy state.
def is_prop_true(state, var_index):
    true_props, _ = state
    return var_index in true_props

# Reads a numeric variable value from a legacy state.
def get_numeric_value(state, search_task, var_index):
    _, numeric_values = state
    pos = search_task.numeric_var_to_pos[var_index]
    return numeric_values[pos]

# Checks whether an action can be applied in a SAS and numeric state.
def is_action_applicable(state, action, search_task):
    if not check_boolean_conditions(state, action.conditions):
        return False

    if not check_numeric_conditions(state, action.numericConditions, search_task):
        return False

    return True

# Checks legacy propositional action conditions.
def check_boolean_conditions(state, conditions):
    true_props, _ = state

    for cond in conditions:
        if cond.valueIndex == BOOL_TRUE:
            if cond.varIndex not in true_props:
                return False
        elif cond.valueIndex == BOOL_FALSE:
            if cond.varIndex in true_props:
                return False
        else:
            raise NotImplementedError(
                f"Solo se soportan condiciones booleanas TRUE/FALSE. "
                f"Encontrado valueIndex={cond.valueIndex}"
            )

    return True

# Checks legacy numeric action or goal conditions.
def check_numeric_conditions(state, numeric_conditions, search_task):
    for cond in numeric_conditions:
        if not _evaluate_numeric_condition(state, cond, search_task):
            return False
    return True

# Evaluates numeric condition.
def _evaluate_numeric_condition(state, cond, search_task):
    if len(cond.terms) != 2:
        raise NotImplementedError(
            "Solo se soportan comparaciones numéricas binarias."
        )

    left = _evaluate_numeric_expression(state, cond.terms[0], search_task)
    right = _evaluate_numeric_expression(state, cond.terms[1], search_task)

    cmp_ = cond.comparator

    if cmp_ == Comparator.CMP_EQ:
        return left == right
    if cmp_ == Comparator.CMP_NEQ:
        return left != right
    if cmp_ == Comparator.CMP_LESS:
        return left < right
    if cmp_ == Comparator.CMP_LESS_EQ:
        return left <= right
    if cmp_ == Comparator.CMP_GREATER:
        return left > right
    if cmp_ == Comparator.CMP_GREATER_EQ:
        return left >= right

    raise NotImplementedError(f"Comparador no soportado: {cmp_}")
    
# Evaluates numeric expression.
def _evaluate_numeric_expression(state, expr, search_task):
    t = expr.type

    if t == GroundedNumericExpressionType.GE_NUMBER:
        return float(expr.value)

    if t == GroundedNumericExpressionType.GE_VAR:
        return get_numeric_value(state, search_task, expr.index)

    if t == GroundedNumericExpressionType.GE_SUM:
        return sum(_evaluate_numeric_expression(state, sub, search_task) for sub in expr.terms)

    if t == GroundedNumericExpressionType.GE_SUB:
        vals = [_evaluate_numeric_expression(state, sub, search_task) for sub in expr.terms]
        if len(vals) == 1:
            return -vals[0]
        result = vals[0]
        for v in vals[1:]:
            result -= v
        return result

    if t == GroundedNumericExpressionType.GE_MUL:
        result = 1.0
        for sub in expr.terms:
            result *= _evaluate_numeric_expression(state, sub, search_task)
        return result

    if t == GroundedNumericExpressionType.GE_DIV:
        vals = [_evaluate_numeric_expression(state, sub, search_task) for sub in expr.terms]
        if len(vals) != 2:
            raise NotImplementedError("GE_DIV solo se soporta con dos operandos.")
        return vals[0] / vals[1]

    raise NotImplementedError(f"Expresión numérica no soportada: {t}")

# Applies a translated action to a SAS and numeric state.
def apply_action(state, action, search_task):
    true_props, numeric_values = state

    # Copias mutables
    new_true_props = set(true_props)
    new_numeric_values = list(numeric_values)

    # 1) Efectos booleanos
    for eff in action.effects:
        if eff.valueIndex == BOOL_TRUE:
            new_true_props.add(eff.varIndex)
        elif eff.valueIndex == BOOL_FALSE:
            new_true_props.discard(eff.varIndex)
        else:
            raise NotImplementedError(
                f"Solo se soportan efectos booleanos TRUE/FALSE. "
                f"Encontrado valueIndex={eff.valueIndex}"
            )

    # 2) Efectos numéricos
    for eff in action.numericEffects:
        _apply_numeric_effect(new_numeric_values, state, eff, search_task)

    return (frozenset(new_true_props), tuple(new_numeric_values))


# Applies numeric effect.
def _apply_numeric_effect(new_numeric_values, old_state, eff, search_task):
    var_index = eff.varIndex
    if var_index not in search_task.numeric_var_to_pos:
        raise ValueError(
            f"El efecto numérico referencia una variable no indexada como numérica: {var_index}"
        )

    pos = search_task.numeric_var_to_pos[var_index]
    current_value = new_numeric_values[pos]
    rhs_value = _evaluate_numeric_expression(old_state, eff.exp, search_task)

    if eff.assignment == Assignment.AS_ASSIGN:
        new_value = rhs_value
    elif eff.assignment == Assignment.AS_INCREASE:
        new_value = current_value + rhs_value
    elif eff.assignment == Assignment.AS_DECREASE:
        new_value = current_value - rhs_value
    elif eff.assignment == Assignment.AS_SCALE_UP:
        new_value = current_value * rhs_value
    elif eff.assignment == Assignment.AS_SCALE_DOWN:
        new_value = current_value / rhs_value
    else:
        raise NotImplementedError(f"Asignación numérica no soportada: {eff.assignment}")

    if var_index == search_task.total_cost_var and new_value < current_value:
        raise ValueError("No se permiten acciones que reduzcan total-cost.")

    if var_index == search_task.total_utility_var and new_value < current_value:
        raise ValueError("No se permiten acciones que reduzcan total-utility.")

    new_numeric_values[pos] = new_value

# Formats a grounded variable name for output.
def get_variable_display_name(search_task, var_index):
    task = search_task.task
    grounder = search_task.grounder

    if var_index < 0 or var_index >= len(task.variables):
        raise IndexError(f"Índice de variable fuera de rango: {var_index}")

    var = task.variables[var_index]

    params = []
    for p in var.params:
        if grounder is not None and 0 <= p < len(grounder.objects):
            obj = grounder.objects[p]
            params.append(getattr(obj, "name", str(obj)))
        else:
            params.append(str(p))

    name = str(var.fncIndex)
    if params:
        return f"{name}({', '.join(params)})"
    return name

# Formats a grounded action name for output.
def get_action_display_name(search_task, action):
    grounder = search_task.grounder

    params = []
    for p in action.parameters:
        if grounder is not None and 0 <= p < len(grounder.objects):
            obj = grounder.objects[p]
            params.append(getattr(obj, "name", str(obj)))
        else:
            params.append(str(p))

    if params:
        return f"{action.name}({', '.join(params)})"
    return action.name

# Formats a legacy state for text output.
def state_to_string(state, search_task):
    true_props, numeric_values = state

    prop_names = sorted(
        get_variable_display_name(search_task, var_index)
        for var_index in true_props
    )

    numeric_entries = []
    for var_index in search_task.numeric_var_indices:
        pos = search_task.numeric_var_to_pos[var_index]
        value = numeric_values[pos]
        vname = get_variable_display_name(search_task, var_index)
        numeric_entries.append(f"{vname}={value}")

    lines = []
    lines.append("True propositions:")
    if prop_names:
        for name in prop_names:
            lines.append(f"  {name}")
    else:
        lines.append("  <none>")

    lines.append("Numeric values:")
    if numeric_entries:
        for entry in numeric_entries:
            lines.append(f"  {entry}")
    else:
        lines.append("  <none>")

    return "\n".join(lines)

# Formats the changes between two legacy states.
def state_diff_to_string(before_state, after_state, search_task):
    before_true, before_num = before_state
    after_true, after_num = after_state

    added = sorted(after_true - before_true)
    removed = sorted(before_true - after_true)

    lines = []

    if added:
        lines.append("Added propositions:")
        for var_index in added:
            lines.append(f"  + {get_variable_display_name(search_task, var_index)}")

    if removed:
        lines.append("Removed propositions:")
        for var_index in removed:
            lines.append(f"  - {get_variable_display_name(search_task, var_index)}")

    numeric_changes = []
    for var_index in search_task.numeric_var_indices:
        pos = search_task.numeric_var_to_pos[var_index]
        old = before_num[pos]
        new = after_num[pos]
        if old != new:
            numeric_changes.append((var_index, old, new))

    if numeric_changes:
        lines.append("Numeric changes:")
        for var_index, old, new in numeric_changes:
            lines.append(
                f"  {get_variable_display_name(search_task, var_index)}: {old} -> {new}"
            )

    if not lines:
        lines.append("No state changes.")

    return "\n".join(lines)

# Writes a policy solution in a readable text format.
def write_solution(policy, solution_number, search_task, ordering, solution_folder):
    Path(solution_folder).mkdir(parents=True, exist_ok=True)

    pname = getattr(search_task, "problem_name", "problem")
    filename = f"{pname}.boand.{str(solution_number).zfill(3)}.out"
    out_path = Path(solution_folder) / filename

    lines = []
    lines.append(f"Problem: {pname}")
    lines.append(f"Ordering: {','.join(ordering)}")
    lines.append(f"Policy size: {len(policy.strategy)}")
    lines.append("")

    ordered_items = sorted(
        policy.strategy.items(),
        key=lambda item: _state_sort_key_for_output(item[0], search_task),
    )

    for i, (state, decision) in enumerate(ordered_items, 1):
        nondet_name, det_actions = decision

        lines.append(f"Rule {i}")
        lines.append("State:")
        lines.append(state_to_string(state, search_task))
        lines.append(f"Chosen action: {nondet_name}")

        if det_actions:
            lines.append("Deterministic outcomes:")
            for det_action in det_actions:
                lines.append(f"  - {get_action_display_name(search_task, det_action)}")

        lines.append("")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path
        
# Handles the internal state sort key for output step.
def _state_sort_key_for_output(state, search_task):
    true_props, numeric_values = state
    return (
        tuple(sorted(true_props)),
        tuple(numeric_values),
    )

# Writes the summary CSV-style statistics for found solutions.
def write_stats(stats, search_task, solution_folder):
    Path(solution_folder).mkdir(parents=True, exist_ok=True)

    pname = getattr(search_task, "problem_name", "problem")
    out_path = Path(solution_folder) / f"{pname}.stats"

    headers = [
        "Umin",
        "Cmax",
        "Umax",
        "Cmin",
        "size",
        "time",
        "iterations",
        "expansions",
        "generations",
        "max_open",
    ]

    lines = []
    lines.append(";".join(headers))

    n = len(stats["Umin"])
    for i in range(n):
        row = [
            stats["Umin"][i],
            stats["Cmax"][i],
            stats["Umax"][i],
            stats["Cmin"][i],
            stats["size"][i],
            stats["time"][i],
            stats["iterations"][i],
            stats["expansions"][i],
            stats["generations"][i],
            stats["max_open"][i],
        ]
        lines.append(";".join(map(str, row)))

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
