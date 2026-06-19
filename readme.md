# ExtBoand Planner

## References

This document describes how the planner implementation works. It does not aim to reproduce the theoretical explanation from the papers on which it is based. For the conceptual basis, the following should be cited:

- Aineto, D., & Scala, E. (2025). *Cost-Optimal FOND Planning as Bi-Objective Best-First Search*. In *Proceedings of the Thirty-Fifth International Conference on Automated Planning and Scheduling (ICAPS 2025)*.
- Katz, M., Keyder, E., Pommerening, F., & Winterer, D. (2019). *Oversubscription Planning as Classical Planning with Multiple Cost Functions*. In *Proceedings of the Twenty-Ninth International Conference on Automated Planning and Scheduling (ICAPS 2019)*.

## Objective

`ExtBoand` is a planner for oversubscription FOND problems. The main input is a PDDL domain, a PDDL problem, and an additional `:utility` section in the problem. The output is a set of non-dominated policies according to four criteria:

```text
Umin, Cmax, Umax, Cmin
```

The default optimization order is:

```text
Umin,Cmax,Umax,Cmin
```

This order can be changed with:

```powershell
python extBoand.py -o Umin,Cmax,Umax,Cmin
```

## Relevant Parameters

The executable receives the PDDL domain and problem as its main arguments:

```powershell
.\.env\Scripts\python.exe extBoand.py domain.pddl motivating.pddl
```

The default domain and problem values exist only as a convenience for local testing. For reproducible experiments and traces, both files should be specified explicitly.

Available parameters:

- `domain_file`: path to the PDDL domain.
- `problem_file`: path to the PDDL problem.
- `-o`, `--optimization-order`: defines the lexicographic optimization order. It must contain exactly `Umin`, `Cmax`, `Umax`, and `Cmin` once each, separated by commas. Default: `Umin,Cmax,Umax,Cmin`.
- `--variables`: displays the generated SAS variables and their values.
- `--actions`: displays the translated SAS actions.
- `--compile-soft-goals`: forces the compilation of soft goals through dummy actions. When search is executed, this is enabled automatically.
- `--no-search`: stops the program after parsing, grounding, and translation to SAS. It is useful for inspecting the task without planning.
- `--max-expansions`: limits the number of policy expansions. If not specified, the search has no limit and continues until the open list is exhausted or the process is stopped externally.
- `--search-algorithm`: selects the search algorithm. It accepts `boand`, `dfs`, and `bfs`. The normal value is `boand`.
- `-n`, `--num-solutions`: limits the maximum number of Pareto solutions to find.
- `--no-heuristics`: disables the relaxed and AND-OR heuristics used to guide the search.
- `--andor-depth`: sets a maximum depth for the AND-OR heuristic. If not specified, the depth is unbounded and relaxations are used as a fallback in cycles.
- `--report-every`: controls how often progress is printed, measured in policies extracted from the open list. With `0`, these periodic messages are disabled.
- `--full`: prints the complete SAS representation.

Examples:

```powershell
.\.env\Scripts\python.exe extBoand.py domain.pddl motivating.pddl --variables
```

```powershell
.\.env\Scripts\python.exe extBoand.py domain.pddl motivating.pddl --max-expansions 1200 --report-every 500
```

```powershell
.\.env\Scripts\python.exe extBoand.py domain.pddl motivating.pddl -o Cmax,Cmin,Umin,Umax
```

## General Flow

The main executable is:

```text
extBoand.py
```

The complete flow is:

1. Read the PDDL domain and problem.
2. Extract the `:utility` section.
3. Ground the problem.
4. Determinize non-deterministic actions.
5. Translate the grounded task into a reduced SAS representation.
6. Compile soft goals as closable goals through dummy actions.
7. Run the policy search.
8. Save policies, statistics, and visualizations.

## Utility Format

Utilities are specified in the PDDL problem through a section:

```lisp
(:utility
    (= (has-reward first-aid-kit) 10)
    (= (has-reward diamond) 20)
)
```

The implementation assumes that utilities are associated with literals. After translation to SAS, each useful literal is represented as a variable-value pair.

The specific parser is located in:

```text
pddl_utility_parser.py
```

This module temporarily removes the `:utility` section before delegating to the standard problem parser, and then adds a list of utility assignments to the problem object.

## Translation to SAS

The translation is implemented in:

```text
sas.py
```

The translation uses only the features required by the planner:

- Propositional SAS variables.
- Numeric variables for fluents such as `total-cost`.
- Deterministic actions.
- Propositional and numeric conditions.
- Propositional effects and numeric increases.
- Goals.
- Mapping of utilities from PDDL literals to SAS variable-value pairs.

The translation groups mutually exclusive literals into the same SAS variable when possible. For example, alternative agent positions can be represented as different values of the same variable.

## Soft Goal Compilation

During search, soft goals are closed through dummy actions. This compilation is performed in:

```text
sas.compile_soft_goals
```

For each SAS variable that can provide utility, an auxiliary closure variable is created:

```text
closed_soft_goal_vX = open | closed
```

Dummy actions are then added to close that variable. If the current value of the variable provides the maximum possible utility, the dummy action has loss 0. Otherwise, the dummy action pays as loss the utility that is left uncollected.

For a variable `v`, if its maximum utility is `Umax(v)` and the current value has utility `U(v=value)`, the associated loss is:

```text
loss = Umax(v) - U(v=value)
```

Dummy actions do not increase `total-cost`. They only serve to turn the decision not to pursue more utility into an achievable goal.

This allows a policy that does not obtain any reward to be valid if there are no active hard goals. In that case, a trivial policy will appear with:

```text
Umin = 0
Umax = 0
Cmax = 0
Cmin = 0
```

That policy can be part of the Pareto front because it represents the minimum possible cost.

## Metrics

The search works internally in terms of losses and costs, but presents four metrics:

```text
Umin
Cmax
Umax
Cmin
```

Their interpretation is:

- `Umin`: minimum utility guaranteed by the policy.
- `Cmax`: maximum cost the policy can reach.
- `Umax`: maximum utility reachable by some branch of the policy.
- `Cmin`: minimum cost reachable by some branch of the policy.

Internally:

```text
Umin = M - loss_max
Umax = M - loss_min
```

where `M` is the sum of the maximum possible utility of each useful variable.

Pareto comparison is implemented as a minimization comparison over:

```text
loss_max, Cmax, loss_min, Cmin
```

One policy dominates another if it does not worsen any of those components and improves at least one.

## Search

The main search is located in:

```text
sas_search.py
```

The main function is:

```text
boand_star_policy_search
```

It builds partial policies. A partial policy contains:

- Initial state.
- Pending states to resolve.
- Partial strategy.
- Terminal states.
- Metrics propagated by state.

In each iteration:

1. A partial policy is extracted from the open list.
2. It is discarded if it is dominated by already accepted solutions.
3. If it has no pending states, the algorithm checks whether it is a strong acyclic solution.
4. If it still has pending states, one state is selected and non-deterministic action groups are expanded.
5. Each child is evaluated with heuristic bounds.
6. Infeasible or dominated children are discarded.
7. The new partial policies are inserted into the open list.

The search keeps a set of non-dominated solutions. When a new solution appears, any previously stored solutions dominated by it are removed.

## Exploration Order

The first solution is searched for by following the optimization order specified by the user. Afterwards, selection orders are alternated to better cover the Pareto front and avoid spending too much time in a single corner of the search space.

Initial seeds are also generated for several relevant corners of the front:

- The best policy according to the main order.
- A policy oriented toward `Cmax`.
- A policy oriented toward `Cmin`.
- A policy oriented toward `Umax`.

These seeds make it possible to find low-cost policies early, which would otherwise be delayed for a long time under a purely lexicographic order.

## Heuristics

The heuristics are located in:

```text
sas_heuristics.py
```

Several estimates are combined:

- Guaranteed utility through relaxed AND-OR exploration.
- Relaxed upper bound on utility.
- Guaranteed cost to the goal.
- Cost conditioned on maintaining a utility target.
- Relaxed distance to the goal.

The evaluation of a state returns, among others:

```text
h_loss
h_loss_min
h_cmax
h_cmax_unconditional
h_cmin
```

There is an important distinction between:

- `h_cmax`: the cost used for ordering when we want to maintain a certain utility.
- `h_cmax_unconditional`: the cost used to check feasibility with respect to the budget.

This separation prevents pruning lower-utility but better-cost policies merely because they could not maintain the same utility level as another policy.

## Budget

If the goal contains a restriction on `total-cost`, for example:

```lisp
(<= (total-cost) (budget))
```

the search extracts that limit and uses it as a cost bound. Budget pruning uses the unconditional cost (`Cmax_budget`) so as not to eliminate valid policies that give up utility.

## Solution Certification

A solution can appear before the open list is exhausted. At that point, it is a valid solution and is saved incrementally.

A solution is marked as certified when the open list no longer contains any bound that could dominate it. If the search terminates because `--max-expansions` is reached, there may be valid solutions that are not yet certified.

If the open list is exhausted, all remaining solutions are marked as certified.

## Outputs

Saving is handled in:

```text
sas_output.py
```

The default output folder is:

```text
solution
```

The following are generated:

- `example.boand.001.out`, `example.boand.002.out`, etc.
- `example.stats`.
- `.png` images for Frozen Lake-style domains.

Each `.out` file contains:

- Policy metrics.
- Policy size.
- State-action rules.
- Deterministic successors.
- Metrics propagated by state.

The `.stats` file summarizes the saved solutions:

```text
Umin;Cmax;Umax;Cmin;size;time;iterations;expansions;generations;max_open
```
