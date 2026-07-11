from pathlib import Path
import tempfile
import unittest

from pddl import parse_domain, parse_problem

from grounder import Grounder
from grounderTypes import TermType


class GrounderForallTests(unittest.TestCase):
    def parse_task(self, forall):
        domain_text = f"""
        (define (domain forall-test)
            (:requirements :strips :typing :universal-preconditions)
            (:types person aircraft)
            (:predicates
                (not-boarding ?p - person)
                (not-debarking ?p - person)
            )
            (:action start-flying
                :parameters (?a - aircraft)
                :precondition {forall}
                :effect (and)
            )
        )
        """
        problem_text = """
        (define (problem forall-problem)
            (:domain forall-test)
            (:objects p0 p1 - person a0 - aircraft)
            (:init
                (not-boarding p0) (not-debarking p0)
                (not-boarding p1) (not-debarking p1)
            )
            (:goal (and))
        )
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            domain_path = Path(tmp_dir) / "domain.pddl"
            problem_path = Path(tmp_dir) / "problem.pddl"
            domain_path.write_text(domain_text, encoding="utf-8")
            problem_path.write_text(problem_text, encoding="utf-8")
            return parse_domain(domain_path), parse_problem(problem_path)

    def test_single_typed_variable_and_body_is_expanded(self):
        domain, problem = self.parse_task(
            "(forall (?p - person) "
            "(and (not-boarding ?p) (not-debarking ?p)))"
        )
        grounder = Grounder((domain, problem))
        grounder.initTypesMatrix()
        grounder.initObjects()
        grounder.objects = list(grounder.object_list)
        action = next(iter(domain.actions))

        boolean, numeric, equality = grounder._extract_preconditions(
            action.precondition,
            action,
        )

        self.assertEqual(len(boolean), 4)
        self.assertEqual(numeric, [])
        self.assertEqual(equality, [])
        self.assertEqual(
            {precondition.variable.fncIndex for precondition in boolean},
            {"not-boarding", "not-debarking"},
        )
        object_indices = {
            precondition.variable.params[0].index for precondition in boolean
        }
        self.assertEqual(
            object_indices,
            {grounder.object_to_index["p0"], grounder.object_to_index["p1"]},
        )
        self.assertTrue(
            all(
                precondition.variable.params[0].type == TermType.TERM_CONSTANT
                for precondition in boolean
            )
        )

    def test_more_general_forall_is_rejected_explicitly(self):
        domain, problem = self.parse_task(
            "(forall (?p - person) (not-boarding ?p))"
        )
        grounder = Grounder((domain, problem))
        grounder.initTypesMatrix()
        grounder.initObjects()
        grounder.objects = list(grounder.object_list)
        action = next(iter(domain.actions))

        with self.assertRaisesRegex(NotImplementedError, "cuerpo conjuntivo"):
            grounder._extract_preconditions(action.precondition, action)


if __name__ == "__main__":
    unittest.main()
