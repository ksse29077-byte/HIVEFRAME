from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "python" / "tests" / "fixtures" / "m1_b0_counterexamples.json"


def _set_path(document: dict, dotted_path: str, value: object) -> None:
    target = document
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value


class M1B0CounterexampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    @staticmethod
    def _validate(document: dict) -> list[str]:
        from hive_benchmarks.m1_b0_contract import validate_protocol_contract

        return validate_protocol_contract(document)

    def test_predeclared_contract_is_accepted(self) -> None:
        self.assertEqual(self._validate(self.fixture["base_contract"]), [])

    def test_twenty_counterexamples_are_rejected_by_exact_rule(self) -> None:
        cases = self.fixture["counterexamples"]
        self.assertEqual(len(cases), 20)
        self.assertEqual(len({case["id"] for case in cases}), 20)
        for case in cases:
            with self.subTest(counterexample=case["id"]):
                document = deepcopy(self.fixture["base_contract"])
                _set_path(document, case["path"], case["value"])
                errors = self._validate(document)
                self.assertIn(case["expected_error"], errors)


if __name__ == "__main__":
    unittest.main()
