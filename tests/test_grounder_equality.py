from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from pddl import parse_domain

from grounder import Grounder


class GrounderEqualityTests(unittest.TestCase):
    def parse_action(self, precondition):
        domain_text = f"""
        (define (domain equality-test)
            (:requirements :strips :typing :equality)
            (:types item)
            (:predicates (ready ?x - item))
            (:action test
                :parameters (?x ?y - item)
                :precondition {precondition}
                :effect (ready ?x)
            )
        )
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            domain_path = Path(tmp_dir) / "domain.pddl"
            domain_path.write_text(domain_text, encoding="utf-8")
            domain = parse_domain(domain_path)
        return domain, next(iter(domain.actions))

    def extract_equality(self, precondition):
        domain, action = self.parse_action(precondition)
        grounder = Grounder((domain, SimpleNamespace()))
        bool_pre, numeric_pre, equality = grounder._extract_preconditions(
            action.precondition,
            action,
        )
        self.assertEqual(bool_pre, [])
        self.assertEqual(numeric_pre, [])
        self.assertEqual(len(equality), 1)
        return equality[0]

    def test_positive_object_equality_is_preserved(self):
        equality = self.extract_equality("(= ?x ?y)")
        self.assertTrue(equality.equal)

    def test_negated_object_equality_becomes_inequality(self):
        equality = self.extract_equality("(not (= ?x ?y))")
        self.assertFalse(equality.equal)


if __name__ == "__main__":
    unittest.main()
