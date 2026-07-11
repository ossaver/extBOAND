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
                "relaxed_utility_upper_bound",
                return_value=100.0,
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

        self.assertEqual(value, 3.0)

    def test_cmax_bound_does_not_condition_on_optimistic_utility(self):
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
                side_effect=AssertionError(
                    "conditional utility cost must not enter the Cmax bound"
                ),
            ),
            patch.object(
                sas_heuristics,
                "relaxed_utility_loss",
                return_value=0.0,
            ),
        ):
            value = sas_heuristics.evaluate_state(task, state)

        self.assertEqual(value["h_loss"], 10.0)
        self.assertEqual(value["h_cmax"], 2.0)

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
