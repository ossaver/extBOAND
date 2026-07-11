import contextlib
import io
import math
import unittest
from unittest.mock import patch

import sas_search
from sas import SASCondition, SASTranslatedAction


ORDER = ("Umin", "Cmax", "Umax", "Cmin")


def values(q1, q2, tie1=0.0, tie2=0.0, size=1):
    return {
        "Umin": 100.0 - q1,
        "Cmax": q2,
        "Umax": 100.0 - tie1,
        "Cmin": tie2,
        "loss_max": q1,
        "loss_min": tie1,
        "size": size,
    }


class FakePolicy:
    def __init__(self, name, f_values, children=()):
        self.name = name
        self.f_values = f_values
        self.values = f_values
        self.children = tuple(children)
        self.pending = {name} if self.children else set()
        self.strategy = {}


class FakeTask:
    initial_state = (0,)
    numeric_initial_state = (0.0,)

    def state_key(self, _state, _numeric_state):
        return ("root",)


class BiObjectiveHelperTests(unittest.TestCase):
    def test_key_maps_utilities_to_losses_and_keeps_tie_breakers(self):
        item = values(4.0, 7.0, tie1=2.0, tie2=9.0, size=3)

        self.assertEqual(
            sas_search._values_order_key(item, ORDER),
            (4.0, 7.0, 2.0, 9.0, -3),
        )

    def test_q2_check_ignores_tie_breaker_values(self):
        bound = values(500.0, 8.0, tie1=-100.0, tie2=-100.0)

        self.assertFalse(
            sas_search._bound_pruned_by_last_solution(
                bound,
                ORDER[:2],
                math.inf,
            )
        )
        self.assertTrue(
            sas_search._bound_pruned_by_last_solution(bound, ORDER[:2], 7.0)
        )
        self.assertFalse(
            sas_search._bound_pruned_by_last_solution(bound, ORDER[:2], 9.0)
        )

    def test_infinite_tie_breaker_does_not_make_policy_infeasible(self):
        bound = values(1.0, 2.0, tie1=math.inf, tie2=math.inf)

        self.assertFalse(
            sas_search._has_infinite_objective_component(bound, ORDER[:2])
        )
        self.assertTrue(
            sas_search._has_infinite_objective_component(
                bound,
                ("Umin", "Umax"),
            )
        )

    def test_goal_aware_check_rejects_an_inexact_solution_bound(self):
        bound = values(1.0, 2.0)
        exact = values(1.0, 3.0)

        with self.assertRaisesRegex(ValueError, "goal-aware.*Cmax"):
            sas_search._require_goal_aware_objectives(
                bound,
                exact,
                ORDER[:2],
            )

    def test_incumbent_pruning_uses_safe_utility_bound(self):
        incumbent = sas_search.SearchSolution(
            policy=object(),
            values=values(186.0, 0.0),
        )
        misleading_bound = values(198.0, 1.0, tie1=0.0)

        self.assertFalse(
            sas_search._bound_dominated_by_incumbent(
                misleading_bound,
                [incumbent],
                ORDER[:2],
            )
        )

        safely_dominated = values(198.0, 1.0, tie1=200.0)
        self.assertTrue(
            sas_search._bound_dominated_by_incumbent(
                safely_dominated,
                [incumbent],
                ORDER[:2],
            )
        )

    def test_bootstrap_is_returned_as_uncertified_on_early_stop(self):
        bootstrap = sas_search.SearchSolution(
            policy=object(),
            values=values(5.0, 2.0),
        )

        merged = sas_search._merge_bootstrap_solution(
            [],
            bootstrap,
            ORDER[:2],
            certified=False,
        )

        self.assertEqual(merged, [bootstrap])
        self.assertFalse(bootstrap.certified)

    def test_incumbent_set_compares_only_primary_exact_objectives(self):
        old = sas_search.SearchSolution(
            policy=object(),
            values=values(10.0, 2.0, tie1=0.0),
        )
        better_umin = sas_search.SearchSolution(
            policy=object(),
            values=values(5.0, 2.0, tie1=20.0),
        )

        updated = sas_search._update_incumbents(
            [old],
            better_umin,
            ORDER[:2],
        )

        self.assertEqual(updated, [better_umin])

    def test_soft_goals_close_in_one_canonical_order(self):
        task = type("ClosureTask", (), {"soft_goal_closure_vars": [2, 3]})()
        normal = SASTranslatedAction(index=0, name="move")
        close_first = SASTranslatedAction(
            index=1,
            name="close-v2",
            effects=(SASCondition(2, 1),),
            is_fictitious=True,
        )
        close_second = SASTranslatedAction(
            index=2,
            name="close-v3",
            effects=(SASCondition(3, 1),),
            is_fictitious=True,
        )

        all_open = (0, 0, 0, 0)
        self.assertTrue(
            sas_search._canonical_closure_action_allowed(task, all_open, normal)
        )
        self.assertTrue(
            sas_search._canonical_closure_action_allowed(
                task, all_open, close_first
            )
        )
        self.assertFalse(
            sas_search._canonical_closure_action_allowed(
                task, all_open, close_second
            )
        )

        closure_started = (0, 0, 1, 0)
        self.assertFalse(
            sas_search._canonical_closure_action_allowed(
                task, closure_started, normal
            )
        )
        self.assertTrue(
            sas_search._canonical_closure_action_allowed(
                task, closure_started, close_second
            )
        )


class BiObjectiveSearchTests(unittest.TestCase):
    def run_search(self, root):
        task = FakeTask()

        def action_groups(_task, policy, *_args):
            return [
                (child.name, (child,))
                for child in policy.children
            ]

        patches = (
            patch.object(sas_search.BasicPolicy, "make_initial", return_value=root),
            patch.object(sas_search, "_prepare_policy_for_queue", lambda *_args: None),
            patch.object(
                sas_search,
                "evaluate_policy_lower_bound",
                lambda _task, policy, *_args: policy.f_values,
            ),
            patch.object(sas_search, "policy_signature", lambda policy: policy.name),
            patch.object(
                sas_search,
                "_policy_is_strong_acyclic_solution",
                lambda _task, policy: not policy.pending,
            ),
            patch.object(
                sas_search,
                "evaluate_policy",
                lambda _task, policy: policy.values,
            ),
            patch.object(
                sas_search,
                "_has_reachable_strategy_cycle",
                lambda *_args: False,
            ),
            patch.object(
                sas_search,
                "_select_pending_state",
                lambda _task, policy, *_args: policy,
            ),
            patch.object(sas_search, "_applicable_action_groups", action_groups),
            patch.object(
                sas_search,
                "_extend_policy",
                lambda _task, _policy, _state, _group, actions: actions[0],
            ),
            patch.object(
                sas_search,
                "_violates_total_cost_bound",
                lambda *_args: False,
            ),
        )

        with contextlib.ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            with contextlib.redirect_stdout(io.StringIO()):
                return sas_search.boand_star_policy_search(
                    task,
                    optimization_order=ORDER,
                    report_every=0,
                )

    def test_search_keeps_only_strictly_decreasing_q2_solutions(self):
        first = FakePolicy("first", values(1.0, 10.0, tie1=50.0))
        second = FakePolicy("second", values(2.0, 7.0, tie1=40.0))
        dominated = FakePolicy("dominated", values(3.0, 8.0, tie1=-100.0))
        third = FakePolicy("third", values(4.0, 3.0, tie1=30.0))
        root = FakePolicy(
            "root",
            values(0.0, 0.0),
            children=(dominated, third, first, second),
        )

        result = self.run_search(root)

        self.assertEqual(
            [solution.policy.name for solution in result.solutions],
            ["first", "second", "third"],
        )
        self.assertEqual(
            [solution.values["Cmax"] for solution in result.solutions],
            [10.0, 7.0, 3.0],
        )
        self.assertTrue(all(solution.certified for solution in result.solutions))

    def test_last_metrics_only_choose_representative_for_equal_pair(self):
        later_tie = FakePolicy("later-tie", values(1.0, 10.0, tie1=5.0))
        first_tie = FakePolicy("first-tie", values(1.0, 10.0, tie1=1.0))
        tradeoff = FakePolicy("tradeoff", values(2.0, 5.0, tie1=9.0))
        root = FakePolicy(
            "root",
            values(0.0, 0.0),
            children=(later_tie, tradeoff, first_tie),
        )

        result = self.run_search(root)

        self.assertEqual(
            [solution.policy.name for solution in result.solutions],
            ["first-tie", "tradeoff"],
        )


if __name__ == "__main__":
    unittest.main()
