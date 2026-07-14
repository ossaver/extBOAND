from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch


if "pddl" not in sys.modules:
    pddl = ModuleType("pddl")
    pddl.parse_problem = None
    sys.modules["pddl"] = pddl

import pddl_utility_parser
import sas
import sas_heuristics
import sas_search


class ProblemExtensionParserTests(unittest.TestCase):
    def parse_text(self, text):
        captured = {}

        def fake_parse_problem(path):
            captured["text"] = Path(path).read_text(encoding="utf-8")
            return SimpleNamespace()

        with tempfile.TemporaryDirectory() as tmp_dir:
            problem_path = Path(tmp_dir) / "problem.pddl"
            problem_path.write_text(text, encoding="utf-8")
            with patch.object(
                pddl_utility_parser,
                "parse_problem",
                fake_parse_problem,
            ):
                problem = pddl_utility_parser.parse_problem_with_utility(
                    problem_path
                )
        return problem, captured["text"]

    def test_custom_sections_are_removed_and_preserved_on_problem(self):
        problem, parser_input = self.parse_text(
            """
            (define (problem sample)
                (:domain sample)
                (:init (= (total-cost) 0))
                (:utility (= (reward) 5))
                (:bound 17)
            )
            """
        )

        self.assertNotIn(":utility", parser_input)
        self.assertNotIn(":bound", parser_input)
        self.assertIn("(:goal (and))", parser_input)
        self.assertEqual(problem.bound, 17)
        self.assertEqual(len(problem.utility), 1)
        self.assertEqual(problem.utility[0].value, 5.0)
        self.assertFalse(problem.utility[0].negated)

    def test_negated_utility_literal_is_parsed(self):
        problem, _parser_input = self.parse_text(
            """
            (define (problem sample)
                (:domain sample)
                (:init (is-target p1))
                (:utility (= (not (is-target p1)) 16))
            )
            """
        )

        self.assertEqual(len(problem.utility), 1)
        assignment = problem.utility[0]
        self.assertEqual(assignment.predicate, "is-target")
        self.assertEqual(assignment.arguments, ("p1",))
        self.assertEqual(assignment.value, 16.0)
        self.assertTrue(assignment.negated)

    def test_existing_goal_is_not_replaced(self):
        _problem, parser_input = self.parse_text(
            """
            (define (problem sample)
                (:domain sample)
                (:init)
                (:goal (ready))
                (:bound 4)
            )
            """
        )

        self.assertEqual(parser_input.count(":goal"), 1)
        self.assertIn("(:goal (ready))", parser_input)

    def test_bound_must_be_an_integer(self):
        with self.assertRaisesRegex(ValueError, "Invalid integer bound"):
            self.parse_text(
                """
                (define (problem sample)
                    (:domain sample)
                    (:init)
                    (:bound 2.5)
                )
                """
            )

    def test_multiple_bound_sections_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "at most one :bound"):
            self.parse_text(
                """
                (define (problem sample)
                    (:domain sample)
                    (:init)
                    (:bound 2)
                    (:bound 3)
                )
                """
            )


class NegatedUtilityTranslationTests(unittest.TestCase):
    def make_task(self, assignments):
        variable = SimpleNamespace(
            index=0,
            fncIndex="is-target",
            params=(0,),
            isNumeric=False,
            initialValues=(SimpleNamespace(value=sas.BOOL_TRUE),),
        )
        task = SimpleNamespace(variables=[variable], actions=[], goals=[])
        grounder = SimpleNamespace(
            objects=[SimpleNamespace(name="p1")],
            problem=SimpleNamespace(bound=2, init=[]),
        )
        return sas.translate(task, grounder, assignments)

    def test_negated_utility_maps_to_boolean_false_value(self):
        assignment = pddl_utility_parser.UtilityAssignment(
            "is-target",
            ("p1",),
            16.0,
            negated=True,
        )

        task = self.make_task([assignment])

        self.assertEqual(task.variables[0].values, [sas.SAS_FALSE, sas.SAS_TRUE])
        self.assertEqual(task.utility_by_sas_value, {(0, 0): 16.0})
        self.assertEqual(task.utility_of_sas_state((1,)), 0.0)
        self.assertEqual(task.utility_of_sas_state((0,)), 16.0)

    def test_positive_and_negative_utilities_can_share_an_atom(self):
        assignments = [
            pddl_utility_parser.UtilityAssignment("is-target", ("p1",), 3.0),
            pddl_utility_parser.UtilityAssignment(
                "is-target",
                ("p1",),
                16.0,
                negated=True,
            ),
        ]

        task = self.make_task(assignments)

        self.assertEqual(task.utility_by_sas_value, {(0, 1): 3.0, (0, 0): 16.0})


class CostBoundConsumerTests(unittest.TestCase):
    def make_pure_cost_task(self, criterion="Cmin"):
        return sas.SASTask(
            numeric_variables=[
                SimpleNamespace(index=0, fncIndex="total-cost"),
            ],
            cost_bound_criterion=criterion,
        )

    def test_bound_criterion_follows_relative_cost_order(self):
        self.assertEqual(
            sas_search._cost_bound_criterion(
                ("Umin", "Cmin", "Umax", "Cmax")
            ),
            "Cmin",
        )
        self.assertEqual(
            sas_search._cost_bound_criterion(
                ("Umin", "Cmax", "Umax", "Cmin")
            ),
            "Cmax",
        )

    def test_cmax_bound_prunes_when_any_trajectory_exceeds_it(self):
        task = SimpleNamespace(
            cost_bound=10,
            cost_bound_criterion="Cmax",
        )

        self.assertFalse(
            sas_search._violates_total_cost_bound(
                task,
                {"Cmin": 2, "Cmax_budget": 10},
            )
        )
        self.assertTrue(
            sas_search._violates_total_cost_bound(
                task,
                {"Cmin": 2, "Cmax_budget": 11},
            )
        )

    def test_cmin_bound_allows_more_expensive_trajectories(self):
        task = SimpleNamespace(
            cost_bound=10,
            cost_bound_criterion="Cmin",
        )

        self.assertFalse(
            sas_search._violates_total_cost_bound(
                task,
                {"Cmin": 10, "Cmax_budget": 20},
            )
        )
        self.assertTrue(
            sas_search._violates_total_cost_bound(
                task,
                {"Cmin": 11, "Cmax_budget": 11},
            )
        )

    def test_cmax_heuristic_budget_uses_current_total_cost(self):
        task = SimpleNamespace(
            cost_bound=10,
            cost_bound_criterion="Cmax",
            numeric_variables=[SimpleNamespace(fncIndex="total-cost")],
        )

        self.assertEqual(
            sas_heuristics._remaining_budget(task, ((), (4.0,))),
            6.0,
        )

    def test_relaxed_utility_upper_bound_includes_constant_utility(self):
        task = sas.SASTask(
            variables=[
                sas.SASVariable(0, "goldcount", ["not-three", "three"], 1),
            ],
            utility_by_sas_value={(0, 1): 19.0},
            constant_utility=17.0,
            max_utility=36.0,
        )
        state = ((1,), ())

        upper_bound = sas_heuristics.relaxed_utility_upper_bound(task, state)

        self.assertEqual(upper_bound, 36.0)

    def test_relaxed_cost_for_utility_builds_hmax_utility_envelope(self):
        task = sas.SASTask(
            variables=[
                sas.SASVariable(0, "u1", ["off", "on"], 0),
                sas.SASVariable(1, "u2", ["off", "on"], 0),
            ],
            utility_by_sas_value={(0, 1): 5.0, (1, 1): 7.0},
            constant_utility=3.0,
            max_utility=15.0,
        )
        state = ((0, 0), ())
        value_costs = {
            (0, 0): 0.0,
            (0, 1): 2.0,
            (1, 0): 0.0,
            (1, 1): 4.0,
        }

        self.assertEqual(
            sas_heuristics.relaxed_cost_for_utility(
                task, state, 3.0, value_costs=value_costs
            ),
            0.0,
        )
        self.assertEqual(
            sas_heuristics.relaxed_cost_for_utility(
                task, state, 8.0, value_costs=value_costs
            ),
            2.0,
        )
        self.assertEqual(
            sas_heuristics.relaxed_cost_for_utility(
                task, state, 15.0, value_costs=value_costs
            ),
            4.0,
        )
        self.assertEqual(
            sas_heuristics.relaxed_cost_for_utility(
                task,
                state,
                15.0,
                remaining_budget=3.0,
                value_costs=value_costs,
            ),
            float("inf"),
        )

    def test_relaxed_action_data_is_precomputed_once_for_multiple_states(self):
        task = sas.SASTask(
            variables=[
                sas.SASVariable(0, "v0", ["off", "on"], 0),
                sas.SASVariable(1, "v1", ["off", "on"], 0),
            ],
            actions=[
                sas.SASTranslatedAction(
                    0,
                    "enable-v0",
                    conditions=(sas.SASCondition(0, 0),),
                    effects=(sas.SASCondition(0, 1),),
                ),
                sas.SASTranslatedAction(
                    1,
                    "enable-v1",
                    conditions=(sas.SASCondition(0, 1),),
                    effects=(sas.SASCondition(1, 1),),
                ),
            ],
        )

        with patch.object(
            sas_heuristics,
            "_constant_budget_cost",
            return_value=1.0,
        ) as cost:
            first = sas_heuristics.relaxed_value_costs(task, ((0, 0), ()))
            second = sas_heuristics.relaxed_value_costs(task, ((1, 0), ()))

        self.assertEqual(first[(1, 1)], 2.0)
        self.assertEqual(second[(1, 1)], 1.0)
        self.assertEqual(cost.call_count, 2)

    def test_relaxed_state_summary_is_shared_by_all_relaxed_queries(self):
        task = sas.SASTask(
            variables=[
                sas.SASVariable(0, "v0", ["off", "on"], 0),
                sas.SASVariable(1, "v1", ["off", "on"], 0),
            ],
            actions=[
                sas.SASTranslatedAction(
                    0,
                    "enable-v0",
                    conditions=(sas.SASCondition(0, 0),),
                    effects=(sas.SASCondition(0, 1),),
                ),
                sas.SASTranslatedAction(
                    1,
                    "enable-v1",
                    conditions=(sas.SASCondition(0, 1),),
                    effects=(sas.SASCondition(1, 1),),
                ),
            ],
            goals=[
                sas.SASTranslatedAction(
                    0,
                    "goal",
                    conditions=(sas.SASCondition(1, 1),),
                    is_goal=True,
                ),
            ],
            utility_by_sas_value={(0, 1): 5.0, (1, 1): 7.0},
            constant_utility=3.0,
            max_utility=15.0,
        )
        state = ((0, 0), ())
        compute = sas_heuristics._compute_relaxed_value_costs

        with (
            patch.object(
                sas_heuristics,
                "_constant_budget_cost",
                return_value=1.0,
            ),
            patch.object(
                sas_heuristics,
                "_compute_relaxed_value_costs",
                wraps=compute,
            ) as relaxed_compute,
        ):
            value_costs = sas_heuristics.relaxed_value_costs(task, state)
            goal_cost = sas_heuristics.relaxed_goal_distance(task, state)
            utility_at_one = sas_heuristics.relaxed_utility_upper_bound(
                task,
                state,
                remaining_budget=1.0,
            )
            utility_at_two = sas_heuristics.relaxed_utility_upper_bound(
                task,
                state,
                remaining_budget=2.0,
            )
            utility_cost = sas_heuristics.relaxed_cost_for_utility(
                task,
                state,
                target_utility=15.0,
                remaining_budget=2.0,
            )

        self.assertEqual(value_costs[(1, 1)], 2.0)
        self.assertEqual(goal_cost, 2.0)
        self.assertEqual(utility_at_one, 8.0)
        self.assertEqual(utility_at_two, 15.0)
        self.assertEqual(utility_cost, 2.0)
        self.assertEqual(relaxed_compute.call_count, 1)

    def test_static_andor_depth_uses_relaxed_utility_layers(self):
        actions = []
        for layer in range(3):
            conditions = (sas.SASCondition(0, layer),)
            actions.extend(
                (
                    sas.SASTranslatedAction(
                        len(actions),
                        f"step-{layer}_DETDUP_1",
                        conditions=conditions,
                        effects=(sas.SASCondition(0, layer + 1),),
                    ),
                    sas.SASTranslatedAction(
                        len(actions) + 1,
                        f"step-{layer}_DETDUP_2",
                        conditions=conditions,
                    ),
                )
            )
        task = sas.SASTask(
            variables=[
                sas.SASVariable(
                    0,
                    "progress",
                    ["zero", "one", "two", "three"],
                    0,
                ),
            ],
            actions=actions,
            initial_state=(0,),
            numeric_initial_state=(),
            utility_by_sas_value={(0, 3): 9.0},
            max_utility=9.0,
        )

        estimate = sas_heuristics.estimate_andor_depth(task, max_depth=4)

        self.assertEqual(estimate["relaxed_layers"], 3.0)
        self.assertEqual(estimate["depth"], 4)
        self.assertEqual(estimate["nondeterministic_groups"], 3)
        self.assertEqual(estimate["relevant_nondeterministic_groups"], 3)

    def test_static_andor_depth_is_one_for_deterministic_task(self):
        task = sas.SASTask(
            variables=[sas.SASVariable(0, "goal", ["off", "on"], 0)],
            actions=[
                sas.SASTranslatedAction(
                    0,
                    "enable",
                    conditions=(sas.SASCondition(0, 0),),
                    effects=(sas.SASCondition(0, 1),),
                ),
            ],
            initial_state=(0,),
            numeric_initial_state=(),
            utility_by_sas_value={(0, 1): 1.0},
            max_utility=1.0,
        )

        estimate = sas_heuristics.estimate_andor_depth(task, max_depth=4)

        self.assertEqual(estimate["depth"], 1)
        self.assertEqual(estimate["relevant_nondeterministic_groups"], 0)

    def test_cmin_heuristics_do_not_restrict_expensive_branches(self):
        task = SimpleNamespace(
            cost_bound=10,
            cost_bound_criterion="Cmin",
            numeric_variables=[SimpleNamespace(fncIndex="total-cost")],
        )

        self.assertIsNone(
            sas_heuristics._remaining_budget(task, ((), (12.0,)))
        )

    def test_unbounded_andor_detects_cost_increasing_logical_cycle(self):
        task = self.make_pure_cost_task()
        initial_state = ((0,), (0.0,))

        def cost_increasing_loop(_task, state_key):
            successor = (state_key[0], (state_key[1][0] + 1.0,))
            return {"loop": (successor,)}

        with (
            patch.object(
                sas_heuristics,
                "_base_goal_satisfied",
                return_value=False,
            ),
            patch.object(
                sas_heuristics,
                "_nondeterministic_successor_groups",
                side_effect=cost_increasing_loop,
            ),
            patch.object(
                sas_heuristics,
                "relaxed_utility_upper_bound",
                return_value=7.0,
            ),
        ):
            value = sas_heuristics.andor_guaranteed_utility(
                task,
                initial_state,
                remaining_budget=None,
                depth=None,
            )

        self.assertEqual(value, 7.0)

    def test_soft_goal_base_state_uses_optimistic_utility_at_depth_limit(self):
        task = SimpleNamespace(
            soft_goals_compiled=True,
        )
        state = ((0,), ())

        with (
            patch.object(
                sas_heuristics,
                "_base_goal_satisfied",
                return_value=True,
            ),
            patch.object(
                sas_heuristics,
                "relaxed_utility_upper_bound",
                return_value=100.0,
            ),
        ):
            value = sas_heuristics._compute_andor_guaranteed_utility(
                task,
                state,
                remaining_budget=10.0,
                depth=0,
            )

        self.assertEqual(value, 100.0)

    def test_soft_goal_base_state_can_continue_for_utility_target(self):
        task = SimpleNamespace(
            soft_goals_compiled=True,
            utility_of_sas_state=lambda _state: 40.0,
        )
        state = ((0,), ())

        with (
            patch.object(
                sas_heuristics,
                "_base_goal_satisfied",
                return_value=True,
            ),
            patch.object(
                sas_heuristics,
                "relaxed_cost_for_utility",
                return_value=5.0,
            ),
        ):
            value = sas_heuristics._compute_andor_goal_cost_with_utility_target(
                task,
                state,
                target_utility=100.0,
                remaining_budget=10.0,
                depth=0,
                fallback_cost=3.0,
            )

        self.assertEqual(value, 5.0)

    def test_cmax_pairs_with_utility_but_budget_cost_stays_unconditional(self):
        task = SimpleNamespace(
            max_utility=100.0,
        )
        state = ((0,), ())

        with (
            patch.object(
                sas_heuristics,
                "relaxed_value_costs",
                return_value={},
            ),
            patch.object(
                sas_heuristics,
                "_remaining_budget",
                return_value=10.0,
            ),
            patch.object(
                sas_heuristics,
                "andor_guaranteed_utility",
                return_value=90.0,
            ),
            patch.object(
                sas_heuristics,
                "relaxed_goal_distance",
                return_value=1.0,
            ),
            patch.object(
                sas_heuristics,
                "andor_guaranteed_goal_cost",
                return_value=2.0,
            ),
            patch.object(
                sas_heuristics,
                "andor_goal_cost_with_utility_target",
                return_value=4.0,
            ),
            patch.object(
                sas_heuristics,
                "relaxed_utility_loss",
                return_value=0.0,
            ),
        ):
            value = sas_heuristics.evaluate_state(task, state)

        self.assertEqual(value["h_loss"], 10.0)
        self.assertEqual(value["h_cmax"], 4.0)
        self.assertEqual(value["h_cmax_unconditional"], 2.0)
        self.assertEqual(value["h_utility_cost"], 4.0)

    def test_policy_bound_keeps_conditional_and_budget_costs_separate(self):
        task = sas.SASTask(max_utility=36.0)
        state = task.state_key((), ())
        policy = sas_search.BasicPolicy.make_initial(state)
        heuristic = {
            "h_loss": 0.0,
            "h_loss_min": 0.0,
            "h_cmax": 9.0,
            "h_cmax_unconditional": 0.0,
            "h_cmin": 0.0,
            "h_goal": 9.0,
        }

        with patch.object(
            sas_search,
            "_heuristic_value",
            return_value=heuristic,
        ):
            bound = sas_search.evaluate_policy_lower_bound(task, policy)

        self.assertEqual(bound["Umin"], 36.0)
        self.assertEqual(bound["Cmax"], 9.0)
        self.assertEqual(bound["Cmax_budget"], 0.0)

    def test_canonical_soft_goal_closure_is_one_search_macro(self):
        task = sas.SASTask(
            variables=[
                sas.SASVariable(0, "u0", ["off", "on"], 1),
                sas.SASVariable(1, "u1", ["off", "on"], 0),
            ],
            utility_by_sas_value={(0, 1): 5.0, (1, 1): 7.0},
        )
        sas.compile_soft_goals(task)
        state = task.state_key(task.initial_state, task.numeric_initial_state)
        policy = sas_search.BasicPolicy.make_initial(state)
        sas_search._prepare_policy_for_queue(task, policy)
        groups = sas_search._cached_applicable_action_groups(task, state)
        closure_group = next(
            (group_key, actions)
            for group_key, actions in groups
            if all(action.is_fictitious for action in actions)
        )

        child = sas_search._extend_policy(
            task,
            policy,
            state,
            closure_group[0],
            closure_group[1],
        )

        self.assertIsNotNone(child)
        self.assertEqual(child.pending, set())
        self.assertEqual(len(child.strategy), 2)
        self.assertTrue(
            all(
                all(action.is_fictitious for action, _successor in outcomes)
                for _group, outcomes in child.strategy.values()
            )
        )

    def test_logical_state_key_ignores_only_pure_total_cost(self):
        task = sas.SASTask(
            numeric_variables=[
                SimpleNamespace(index=0, fncIndex="total-cost"),
                SimpleNamespace(index=1, fncIndex="fuel"),
            ],
        )

        self.assertTrue(task.can_abstract_total_cost())
        self.assertEqual(
            task.logical_state_key(((2,), (9.0, 3.0))),
            ((2,), (3.0,)),
        )

    def test_total_cost_in_a_condition_disables_abstraction(self):
        cost_expression = SimpleNamespace(
            type=sas.GroundedNumericExpressionType.GE_VAR,
            index=0,
            terms=(),
        )
        zero = SimpleNamespace(
            type=sas.GroundedNumericExpressionType.GE_NUMBER,
            value=0.0,
            terms=(),
        )
        action = SimpleNamespace(
            numeric_conditions=(
                SimpleNamespace(terms=(cost_expression, zero)),
            ),
            numeric_effects=(),
        )
        task = self.make_pure_cost_task()
        task.actions.append(action)

        self.assertFalse(task.can_abstract_total_cost())
        self.assertEqual(
            task.logical_state_key(((2,), (9.0,))),
            ((2,), (9.0,)),
        )

    def test_policy_cycle_detection_ignores_accumulated_cost(self):
        task = self.make_pure_cost_task()
        first_a = ((0,), (0.0,))
        state_b = ((1,), (1.0,))
        second_a = ((0,), (2.0,))
        policy = SimpleNamespace(
            initial_state=first_a,
            strategy={
                first_a: ("to-b", ((None, state_b),)),
                state_b: ("to-a", ((None, second_a),)),
            },
        )

        self.assertTrue(
            sas_search._has_reachable_strategy_cycle(task, policy)
        )

    def test_cmin_search_heuristic_is_memoized_by_logical_state(self):
        task = self.make_pure_cost_task(criterion="Cmin")
        first = ((0,), (3.0,))
        second = ((0,), (8.0,))
        cache = {}
        estimate = {"h_loss": 1.0, "h_goal": 2.0}

        with patch.object(
            sas_heuristics,
            "evaluate_state",
            return_value=estimate,
        ) as evaluate:
            sas_search._heuristic_value(task, first, cache, True)
            sas_search._heuristic_value(task, second, cache, True)

        self.assertEqual(evaluate.call_count, 1)

    def test_andor_heuristic_is_memoized_by_logical_state(self):
        task = self.make_pure_cost_task()
        first = ((0,), (3.0,))
        second = ((0,), (8.0,))

        with patch.object(
            sas_heuristics,
            "_compute_andor_guaranteed_utility",
            return_value=4.0,
        ) as compute:
            first_value = sas_heuristics.andor_guaranteed_utility(task, first)
            second_value = sas_heuristics.andor_guaranteed_utility(task, second)

        self.assertEqual(first_value, second_value)
        self.assertEqual(compute.call_count, 1)

    def test_andor_cache_keeps_remaining_budget_in_its_key(self):
        task = self.make_pure_cost_task(criterion="Cmax")
        first = ((0,), (3.0,))
        second = ((0,), (8.0,))

        with patch.object(
            sas_heuristics,
            "_compute_andor_guaranteed_utility",
            return_value=4.0,
        ) as compute:
            sas_heuristics.andor_guaranteed_utility(
                task,
                first,
                remaining_budget=7.0,
            )
            sas_heuristics.andor_guaranteed_utility(
                task,
                second,
                remaining_budget=2.0,
            )

        self.assertEqual(compute.call_count, 2)


if __name__ == "__main__":
    unittest.main()
