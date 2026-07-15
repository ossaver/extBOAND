# ExtBoand Planner

## References

This document describes how the planner implementation works. It does not aim to reproduce the theoretical explanation from the papers on which it is based. For the conceptual basis, the following should be cited:

- Aineto, D., & Scala, E. (2025). *Cost-Optimal FOND Planning as Bi-Objective Best-First Search*. In *Proceedings of the Thirty-Fifth International Conference on Automated Planning and Scheduling (ICAPS 2025)*.
- Katz, M., Keyder, E., Pommerening, F., & Winterer, D. (2019). *Oversubscription Planning as Classical Planning with Multiple Cost Functions*. In *Proceedings of the Twenty-Ninth International Conference on Automated Planning and Scheduling (ICAPS 2019)*.

## Objective

`ExtBoand` is a planner for oversubscription FOND problems. The main input is a PDDL domain, a PDDL problem, and an additional `:utility` section in the problem. BOAND* computes a Pareto coverage set for two objectives selected from four available metrics:

```text
Umin, Cmax, Umax, Cmin
```

The default order is:

```text
Umin,Umax,Cmax,Cmin
```

The first two positions are the bi-objective optimization criteria. The final two positions are used only as open-list tie-breakers. The order can be changed with:

```powershell
python extBoand.py -o Umin,Umax,Cmax,Cmin
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
- `-o`, `--optimization-order`: defines the two BOAND* objectives followed by two open-list tie-breakers. It must contain exactly `Umin`, `Cmax`, `Umax`, and `Cmin` once each, separated by commas. Default: `Umin,Umax,Cmax,Cmin`.
- `--variables`: displays the generated SAS variables and their values.
- `--actions`: displays the translated SAS actions.
- `--compile-soft-goals`: forces the compilation of soft goals through dummy actions. When search is executed, this is enabled automatically.
- `--no-search`: stops the program after parsing, grounding, and translation to SAS. It is useful for inspecting the task without planning.
- `--max-expansions`: limits the number of policy expansions. If not specified, the search has no limit and continues until the open list is exhausted or the process is stopped externally.
- `--search-algorithm`: selects the search algorithm. It accepts `boand`, `dfs`, and `bfs`. The normal value is `boand`.
- `-n`, `--num-solutions`: stops after the requested number of bi-objective Pareto solutions. The resulting coverage set may be incomplete.
- `--no-heuristics`: disables the relaxed and AND-OR heuristics used to guide the search.
- `--andor-depth`: sets the depth of the AND-OR heuristic explicitly. If omitted, ExtBoand estimates it from the relaxed action layers needed to reach the utility/goal target, adds one outcome layer, and caps the result at 4.
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
2. Extract the custom `:utility` and `:bound` sections.
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

This module temporarily removes the `:utility` and `:bound` sections before delegating to the standard problem parser. If the problem has no hard goal, it adds `(:goal (and))` only to the temporary parser input. It then adds the utility assignments and integer cost bound to the parsed problem object.

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

All criteria are internally converted to minimization values:

```text
loss_max, Cmax, loss_min, Cmin
```

Only the first two criteria from `-o` participate in Pareto dominance. The remaining criteria are computed and reported, but only break ties in the open list. Consequently, BOAND* returns one representative policy for each distinct non-dominated pair of objective values, not every combination of the other two metrics.

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

1. The policy with the lexicographically smallest fixed key is extracted from the open list.
2. It is discarded when its second-objective bound `f2` is not lower than `q2` of the last accepted solution.
3. If it has no pending states, the algorithm checks whether it is a strong acyclic solution.
4. If it still has pending states, one state is selected and non-deterministic action groups are expanded.
5. Each child is evaluated with heuristic bounds.
6. Infeasible children are discarded.
7. The new partial policies are inserted into the open list.

The second objective of the last solution starts at infinity. The fixed lexicographic order guarantees that accepted solutions have strictly increasing first-objective values and strictly decreasing second-objective values. Therefore, the last solution has the best `q2` found so far and the dominance check is constant time.

## Exploration Order

The same lexicographic order is used for every extraction. The first two key components are the BOAND* objectives; the third and fourth metrics, followed by policy size and insertion order, only resolve ties. No out-of-order seed solutions or alternating extraction orders are used because they would invalidate the constant-time `q2` dominance check.

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

### Why the heuristics differ by metric

The four reported metrics do not have the same semantics under action
nondeterminism, so they should not all use the same relaxation.

- `Umin` and `Cmax` are **worst-case** metrics. `Umin` is the utility that
  every outcome of the policy guarantees, while `Cmax` is the largest cost
  that any outcome can incur. Their estimates therefore use relaxed AND-OR
  exploration: selecting an action is an OR choice, but every possible
  outcome of that action is an AND obligation that the policy must handle.
  This preserves the adversarial, guarantee-oriented meaning of both
  metrics.
- `Umax` and `Cmin` are **best-case** metrics. `Umax` only requires that one
  branch can reach a given utility, and `Cmin` only requires that one branch
  can reach the goal at a given cost. They consequently use the ordinary
  relaxed graph, which computes an optimistic existential estimate: it is
  enough for a favourable relaxed continuation to exist.

Using ordinary relaxed reachability for `Umin` or `Cmax` would ignore adverse
outcomes and could overstate guaranteed utility or understate worst-case cost.
Conversely, using AND-OR reasoning for `Umax` or `Cmin` would impose a
guarantee that those metrics do not require, making their estimates needlessly
conservative and more expensive to compute.

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
- `h_cmax_unconditional`: the worst-case cost used to check budget feasibility when `Cmax` appears before `Cmin`.

This separation prevents pruning lower-utility but better-cost policies merely because they could not maintain the same utility level as another policy.

When `total-cost` is only an accumulated metric, it is excluded from logical state identity for cycle detection and heuristic memoization. The accumulated value is still retained for `Cmin`, `Cmax`, and budget calculations. Remaining budget stays in the AND/OR cache key, so states with different budget capacity are not merged. This abstraction is disabled automatically if `total-cost` appears in an action or goal condition, affects another numeric fluent, or is modified by anything other than an increment.

## Budget

The total-cost limit is specified as a custom top-level problem section:

```lisp
(:bound 20)
```

The custom parser removes this section before invoking the standard PDDL parser and stores its integer value in the SAS task. The bound applies to whichever cost criterion appears first in `-o`. If `Cmax` appears first, every trajectory must respect the bound and pruning uses the unconditional worst-case cost (`Cmax_budget`). If `Cmin` appears first, only the best-case trajectory must respect the bound; trajectories above the bound remain valid as long as the policy's `Cmin` does not exceed it.

## Solution Guarantees

With admissible and goal-aware objective bounds, every solution accepted by BOAND* is already Pareto-optimal for the selected objective pair and is saved incrementally. Exhausting the open list computes the complete Pareto coverage set. Stopping with `--max-expansions` or `--num-solutions` preserves the optimality of accepted solutions but returns incomplete coverage.

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
