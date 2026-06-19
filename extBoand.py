from pathlib import Path
import argparse
from types import SimpleNamespace
import time

from pddl import parse_domain

from fondutils.determizer import determinize
from grounder import Grounder
from pddl_utility_parser import parse_problem_with_utility
import sas
import sas_heuristics
import sas_output
import sas_search


# Parses and validates the requested optimization criteria order.
def optimization_order(value):
    valid_values = {"Umin", "Cmax", "Umax", "Cmin"}
    parts = value.split(",")

    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "Debe indicar cuatro valores separados por comas: Umin,Cmax,Umax,Cmin."
        )

    if any(part != part.strip() or part == "" for part in parts):
        raise argparse.ArgumentTypeError(
            "Los valores deben ir separados solo por comas, sin espacios."
        )

    received = set(parts)
    if received != valid_values:
        raise argparse.ArgumentTypeError(
            "La opcion -o debe contener exactamente Umin, Cmax, Umax y Cmin, una vez cada uno."
        )

    return tuple(parts)


# Builds the grounded and SAS-translated planning task from PDDL files.
def build_sas_task(domain_file, problem_file, compile_soft_goals=False):
    domain = parse_domain(domain_file)
    problem = parse_problem_with_utility(problem_file)
    det_domain = determinize(domain)

    grounder = Grounder((det_domain, problem))
    grounded_task = grounder.ground()
    sas_task = sas.translate(grounded_task, grounder)
    if compile_soft_goals:
        sas.compile_soft_goals(sas_task)

    return domain, problem, grounded_task, sas_task, grounder


# Prints a compact summary of the parsed, grounded, and SAS task.
def print_summary(domain, problem, grounded_task, sas_task, order):
    print(f"Domain: {domain.name}")
    print(f"Problem: {problem.name}")
    print(f"Optimization order: {','.join(order)}")
    print("")
    print("Grounded task:")
    print(f"  variables: {len(grounded_task.variables)}")
    print(f"  actions:   {len(grounded_task.actions)}")
    print(f"  goals:     {len(grounded_task.goals)}")
    print("")
    print("SAS task:")
    print(f"  variables:         {len(sas_task.variables)}")
    print(f"  numeric variables: {len(sas_task.numeric_variables)}")
    print(f"  actions:           {len(sas_task.actions)}")
    print(f"  goals:             {len(sas_task.goals)}")
    print(f"  initial state:     {sas_task.initial_state}")
    print(f"  numeric initial:   {sas_task.numeric_initial_state}")
    print(f"  utilities:         {len(sas_task.utility_by_sas_value)}")
    print(f"  soft goals closed: {sas_task.soft_goals_compiled}")
    if sas_task.soft_goals_compiled:
        fictitious = sum(1 for action in sas_task.actions if action.is_fictitious)
        print(f"  max utility M:     {sas_task.max_utility}")
        print(f"  closure variables: {len(sas_task.soft_goal_closure_vars)}")
        print(f"  fictitious actions:{fictitious}")


# Prints each SAS variable with its possible values.
def print_variables(sas_task):
    print("SAS variables:")
    for var in sas_task.variables:
        initial = var.values[var.initial_value]
        print(f"  {var.index}: {var.name}")
        print(f"    initial: {var.initial_value} = {initial}")
        for value_index, value_name in enumerate(var.values):
            print(f"    {value_index}: {value_name}")

    if sas_task.numeric_variables:
        print("")
        print("Numeric variables:")
        for pos, var in enumerate(sas_task.numeric_variables):
            initial = sas_task.numeric_initial_state[pos]
            print(f"  {pos}: {var.fncIndex} = {initial}")


# Prints the utility assigned to each SAS variable-value pair.
def print_utilities(sas_task):
    if not sas_task.utility_by_sas_value:
        print("Utilities: none")
        return

    print("Utilities:")
    for (var_index, value_index), utility in sorted(
        sas_task.utility_by_sas_value.items()
    ):
        var = sas_task.variables[var_index]
        value = var.values[value_index]
        print(f"  {var_index}={value_index} ({value}): {utility}")


# Prints the final search status and the Pareto solutions found.
def print_search_result(result, use_heuristics):
    print("Policy search:")
    print(f"  heuristics: {use_heuristics}")
    print(f"  found:      {result.found}")
    print(f"  reason:     {result.reason}")
    print(f"  expansions: {result.expansions}")
    print(f"  generated:  {result.generated}")
    print(f"  max open:   {result.max_open}")

    if not result.found:
        return

    solutions = result.solutions or [
        SimpleNamespace(policy=result.policy, values=result.values)
    ]
    certified = sum(1 for solution in solutions if getattr(solution, "certified", False))
    print(f"  pareto solutions: {len(solutions)}")
    print(f"  certified: {certified}")
    for index, solution in enumerate(solutions, 1):
        values = solution.values
        marker = " certified" if getattr(solution, "certified", False) else ""
        print(
            f"    {index}: "
            f"Umin={values['Umin']} "
            f"Cmax={values['Cmax']} "
            f"Umax={values['Umax']} "
            f"Cmin={values['Cmin']} "
            f"size={values['size']}"
            f"{marker}"
        )


# Writes final policies, statistics, and optional visualizations to disk.
def save_search_result(domain, problem, sas_task, grounder, result, ordering, elapsed_time):
    solution_folder = "solution"
    stats_path = sas_output.write_stats(
        problem=problem,
        result=result,
        elapsed_time=elapsed_time,
        solution_folder=solution_folder,
        iterations=1,
    )

    print("")
    print("Solution files:")
    print(f"  stats:  {stats_path}")

    solutions = result.solutions or [
        SimpleNamespace(policy=result.policy, values=result.values)
    ]
    for index, solution in enumerate(solutions, 1):
        single_result = SimpleNamespace(
            policy=solution.policy,
            values=solution.values,
            expansions=result.expansions,
            generated=result.generated,
            max_open=result.max_open,
        )
        solution_path = sas_output.write_solution(
            problem=problem,
            sas_task=sas_task,
            result=single_result,
            ordering=ordering,
            solution_folder=solution_folder,
            solution_number=index,
            grounder=grounder,
        )
        print(f"  policy {index}: {solution_path}")

        if str(domain.name).lower() in {"icylake", "frozenlake", "frozen-lake"}:
            image_path = sas_output.write_frozen_lake_visualization(
                problem=problem,
                sas_task=sas_task,
                policy=solution.policy,
                solution_folder=solution_folder,
                solution_number=index,
            )
            print(f"  image {index}:  {image_path}")


# Creates a callback that saves each solution as soon as it is found.
def make_anytime_solution_saver(domain, problem, sas_task, grounder, ordering):
    saved = {}
    saved_solutions = []
    solution_folder = "solution"

    # Saves one anytime solution and refreshes accumulated statistics.
    def save(solution, solution_number, progress):
        if solution_number in saved:
            return
        saved[solution_number] = True
        saved_solutions.append(
            SimpleNamespace(
                policy=solution.policy,
                values=solution.values,
            )
        )

        single_result = SimpleNamespace(
            policy=solution.policy,
            values=solution.values,
            expansions=progress["expansions"],
            generated=progress["generated"],
            max_open=progress["max_open"],
        )
        accumulated_result = SimpleNamespace(
            policy=solution.policy,
            values=solution.values,
            solutions=list(saved_solutions),
            expansions=progress["expansions"],
            generated=progress["generated"],
            max_open=progress["max_open"],
        )
        solution_path = sas_output.write_solution(
            problem=problem,
            sas_task=sas_task,
            result=single_result,
            ordering=ordering,
            solution_folder=solution_folder,
            solution_number=solution_number,
            grounder=grounder,
        )
        stats_path = sas_output.write_stats(
            problem=problem,
            result=accumulated_result,
            elapsed_time=progress["elapsed_time"],
            solution_folder=solution_folder,
            iterations=progress["iterations"],
        )
        print(
            f"  saved policy {solution_number}: {solution_path}",
            flush=True,
        )
        print(f"  saved stats: {stats_path}", flush=True)

        if str(domain.name).lower() in {"icylake", "frozenlake", "frozen-lake"}:
            image_path = sas_output.write_frozen_lake_visualization(
                problem=problem,
                sas_task=sas_task,
                policy=solution.policy,
                solution_folder=solution_folder,
                solution_number=solution_number,
            )
            print(
                f"  saved image {solution_number}: {image_path}",
                flush=True,
            )

    return save


# Checks whether the BOAND result has already been written incrementally.
def result_was_saved_anytime(result):
    return len(result.solutions) == 1 and all(
        getattr(solution, "certified", False)
        for solution in result.solutions
    )


# Defines and parses the command-line interface for the planner.
def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Parse, ground, and translate an oversubscription PDDL task "
            "to the reduced SAS representation used by ExtBoand v2."
        )
    )
    parser.add_argument(
        "domain_file",
        nargs="?",
        default="domain.pddl",
        help="Path to the PDDL domain file.",
    )
    parser.add_argument(
        "problem_file",
        nargs="?",
        default="motivating.pddl",
        help="Path to the PDDL problem file.",
    )
    parser.add_argument(
        "-o",
        "--optimization-order",
        type=optimization_order,
        default=("Umin", "Cmax", "Umax", "Cmin"),
        metavar="Umin,Cmax,Umax,Cmin",
        help=(
            "Ordering criteria for optimization. Provide exactly Umin, Cmax, "
            "Umax and Cmin once each, separated by commas."
        ),
    )
    parser.add_argument(
        "--variables",
        action="store_true",
        help="Print SAS variables and their values.",
    )
    parser.add_argument(
        "--actions",
        action="store_true",
        help="Print translated SAS actions.",
    )
    parser.add_argument(
        "--compile-soft-goals",
        action="store_true",
        help="Add fictitious soft-goal closure actions with utility loss.",
    )
    parser.add_argument(
        "--no-search",
        action="store_true",
        help="Only parse, ground, and translate to SAS; do not run search.",
    )
    parser.add_argument(
        "--max-expansions",
        type=int,
        default=None,
        help=(
            "Maximum number of policy expansions. "
            "By default there is no limit and search runs until Open is exhausted."
        ),
    )
    parser.add_argument(
        "--search-algorithm",
        choices=("boand", "dfs", "bfs"),
        default="boand",
        help="Basic search algorithm to use.",
    )
    parser.add_argument(
        "-n",
        "--num-solutions",
        type=int,
        default=None,
        help="Maximum number of Pareto solutions to keep searching for.",
    )
    parser.add_argument(
        "--no-heuristics",
        action="store_true",
        help="Disable simple relaxed heuristics for search ordering.",
    )
    parser.add_argument(
        "--andor-depth",
        type=int,
        default=None,
        help=(
            "Depth limit for the relaxed AND-OR guaranteed-utility heuristic. "
            "By default it is unbounded and falls back to the relaxed graph on cycles."
        ),
    )
    parser.add_argument(
        "--report-every",
        type=int,
        default=10000,
        help="Print BOAND* progress every N popped policies. Use 0 to disable.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Print the full SAS task representation.",
    )
    return parser.parse_args()


# Runs the full planner pipeline from parsing to optional search and output.
def main():
    args = parse_args()
    sas_heuristics.DEFAULT_ANDOR_DEPTH = args.andor_depth
    domain_file = str(Path(args.domain_file))
    problem_file = str(Path(args.problem_file))
    run_search = not args.no_search
    start_time = time.time()

    domain, problem, grounded_task, sas_task, grounder = build_sas_task(
        domain_file,
        problem_file,
        compile_soft_goals=args.compile_soft_goals or run_search,
    )

    print_summary(
        domain,
        problem,
        grounded_task,
        sas_task,
        args.optimization_order,
    )
    print("")
    print_utilities(sas_task)

    if args.variables:
        print("")
        print_variables(sas_task)

    if args.actions or args.full:
        print("")
        print(sas_task.to_string())

    if run_search:
        print("")
        if args.search_algorithm == "boand":
            on_solution = make_anytime_solution_saver(
                domain=domain,
                problem=problem,
                sas_task=sas_task,
                grounder=grounder,
                ordering=args.optimization_order,
            )
            result = sas_search.boand_star_policy_search(
                sas_task,
                max_expansions=args.max_expansions,
                optimization_order=args.optimization_order,
                use_heuristics=not args.no_heuristics,
                max_solutions=args.num_solutions,
                report_every=args.report_every,
                on_solution=on_solution,
            )
        elif args.search_algorithm == "bfs":
            result = sas_search.breadth_first_policy_search(
                sas_task,
                max_expansions=args.max_expansions,
                optimization_order=args.optimization_order,
                use_heuristics=not args.no_heuristics,
            )
        else:
            result = sas_search.depth_first_and_or_search(
                sas_task,
                max_expansions=args.max_expansions,
                optimization_order=args.optimization_order,
                use_heuristics=not args.no_heuristics,
            )
        print_search_result(result, use_heuristics=not args.no_heuristics)

        if result.found and (
            args.search_algorithm != "boand"
            or not result_was_saved_anytime(result)
        ):
            save_search_result(
                domain=domain,
                problem=problem,
                sas_task=sas_task,
                grounder=grounder,
                result=result,
                ordering=args.optimization_order,
                elapsed_time=time.time() - start_time,
            )


if __name__ == "__main__":
    main()
