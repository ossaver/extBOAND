from pathlib import Path


# Writes a policy solution in a readable text format.
def write_solution(
    problem,
    sas_task,
    result,
    ordering,
    solution_folder="solution",
    solution_number=1,
    grounder=None,
):
    Path(solution_folder).mkdir(parents=True, exist_ok=True)

    pname = getattr(problem, "name", "problem")
    filename = f"{pname}.boand.{str(solution_number).zfill(3)}.out"
    out_path = Path(solution_folder) / filename

    lines = [
        f"Problem: {pname}",
        f"Ordering: {','.join(ordering)}",
        f"Policy size: {len(result.policy.strategy)}",
        "Values:",
    ]
    for key in ("Umin", "Cmax", "Umax", "Cmin", "loss_min", "loss_max"):
        lines.append(f"  {key}: {result.values.get(key)}")
    lines.append("")

    ordered_items = sorted(
        result.policy.strategy.items(),
        key=lambda item: _state_sort_key_for_output(item[0]),
    )

    for index, (state_key, decision) in enumerate(ordered_items, 1):
        group_key, outcomes = decision
        lines.append(f"Rule {index}")
        lines.append("State:")
        lines.extend(
            _format_state(
                sas_task=sas_task,
                state_key=state_key,
                metrics=result.policy.state_metrics.get(state_key),
            )
        )
        lines.append(f"Chosen action: {_format_group_key(group_key, grounder)}")

        if outcomes:
            lines.append("Deterministic outcomes:")
            for action, successor in outcomes:
                lines.append(f"  - {_format_action(action, grounder)}")
                lines.append(f"    successor: {_compact_state(sas_task, successor)}")

        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


# Writes the summary CSV-style statistics for found solutions.
def write_stats(
    problem,
    result,
    elapsed_time,
    solution_folder="solution",
    iterations=1,
    max_open=0,
):
    Path(solution_folder).mkdir(parents=True, exist_ok=True)

    pname = getattr(problem, "name", "problem")
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

    rows = []
    solutions = getattr(result, "solutions", None)
    if solutions:
        for index, solution in enumerate(solutions, 1):
            rows.append(
                _stats_row(
                    values=solution.values,
                    elapsed_time=elapsed_time,
                    iterations=index,
                    expansions=result.expansions,
                    generated=result.generated,
                    max_open=getattr(result, "max_open", max_open),
                )
            )
    else:
        rows.append(
            _stats_row(
                values=result.values,
                elapsed_time=elapsed_time,
                iterations=iterations,
                expansions=result.expansions,
                generated=result.generated,
                max_open=getattr(result, "max_open", max_open),
            )
        )

    out_path.write_text(
        ";".join(headers) + "\n" + "\n".join(";".join(map(str, row)) for row in rows),
        encoding="utf-8",
    )
    return out_path


# Handles the internal stats row step.
def _stats_row(values, elapsed_time, iterations, expansions, generated, max_open):
    return [
        values.get("Umin"),
        values.get("Cmax"),
        values.get("Umax"),
        values.get("Cmin"),
        values.get("size"),
        f"{elapsed_time:.6f}",
        iterations,
        expansions,
        generated,
        max_open,
    ]


# Writes a Frozen Lake image for a SAS policy.
def write_frozen_lake_visualization(
    problem,
    sas_task,
    policy,
    solution_folder="solution",
    solution_number=1,
):
    import frozenLakeVisualization

    Path(solution_folder).mkdir(parents=True, exist_ok=True)

    pname = getattr(problem, "name", "problem")
    filename = f"{pname}.boand.{str(solution_number).zfill(3)}.png"
    out_path = Path(solution_folder) / filename
    frozenLakeVisualization.generate_sas_policy_visualization(
        problem=problem,
        policy=policy,
        sas_task=sas_task,
        output_image_path=out_path,
        assets_dir="frozenLake",
        tile_size=125,
    )
    return out_path


# Formats state.
def _format_state(sas_task, state_key, metrics=None):
    sas_state, numeric_state = state_key
    lines = ["  SAS values:"]
    for var_index, value_index in enumerate(sas_state):
        variable = sas_task.variables[var_index]
        lines.append(
            f"    {variable.index}:{variable.name}="
            f"{value_index}:{variable.values[value_index]}"
        )

    lines.append("  Numeric values:")
    if sas_task.numeric_variables:
        for pos, variable in enumerate(sas_task.numeric_variables):
            lines.append(f"    {variable.fncIndex}={numeric_state[pos]}")
    else:
        lines.append("    <none>")

    if metrics is not None:
        lines.append("  Metrics:")
        lines.append(f"    cost_min={metrics.cost_min}")
        lines.append(f"    cost_max={metrics.cost_max}")
        lines.append(f"    loss_min={metrics.loss_min}")
        lines.append(f"    loss_max={metrics.loss_max}")

    return lines


# Handles the internal compact state step.
def _compact_state(sas_task, state_key):
    sas_state, numeric_state = state_key
    facts = []
    for var_index, value_index in enumerate(sas_state):
        value_name = sas_task.variables[var_index].values[value_index]
        if value_name not in {"__false__", "__none_of_those__", "open"}:
            facts.append(value_name)

    numeric = []
    for pos, variable in enumerate(sas_task.numeric_variables):
        numeric.append(f"{variable.fncIndex}={numeric_state[pos]}")

    chunks = []
    if facts:
        chunks.append("{" + ", ".join(sorted(facts)) + "}")
    if numeric:
        chunks.append("{" + ", ".join(numeric) + "}")
    return " ".join(chunks) if chunks else "{}"


# Formats group key.
def _format_group_key(group_key, grounder):
    name, parameters = group_key
    return _format_name_and_parameters(name, parameters, grounder)


# Formats action.
def _format_action(action, grounder):
    label = _format_name_and_parameters(action.name, action.parameters, grounder)
    if action.is_fictitious or action.utility_loss:
        return f"{label} [loss={action.utility_loss}]"
    return label


# Formats name and parameters.
def _format_name_and_parameters(name, parameters, grounder):
    params = [_format_object(param, grounder) for param in parameters]
    if not params:
        return name
    return f"{name}({', '.join(params)})"


# Formats object.
def _format_object(param, grounder):
    if grounder is not None and 0 <= param < len(grounder.objects):
        return getattr(grounder.objects[param], "name", str(param))
    return str(param)


# Handles the internal state sort key for output step.
def _state_sort_key_for_output(state_key):
    sas_state, numeric_state = state_key
    return tuple(sas_state), tuple(numeric_state)
