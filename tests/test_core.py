from __future__ import annotations

import unittest
from pathlib import Path

from core.data import load_case_data, load_optimal_total_costs
from core.models import Row
from core.validate import assert_valid_solution


TEST_DATA = Path(__file__).parent / "data"


class CoreTests(unittest.TestCase):
    def test_load_case_data_preserves_raw_rows(self) -> None:
        optimal_total_costs = load_optimal_total_costs(TEST_DATA / "Optimal objectives.tsv")
        case_data = load_case_data(TEST_DATA / "toy_case.tsv")
        self.assertEqual(optimal_total_costs["toy_case.tsv"], 4.5)
        self.assertEqual(len(case_data.rows), 13)
        self.assertEqual(case_data.rows[0].orders, (1,))
        self.assertEqual(case_data.rows[0].rider, 11)
        self.assertAlmostEqual(case_data.rows[0].cost, 2.0)
        self.assertEqual(case_data.orders, (1, 2, 3))
        self.assertEqual(case_data.riders, (11, 12, 13, 14, 15, 16))

    def test_assert_valid_solution_accepts_feasible_rows(self) -> None:
        case_data = load_case_data(TEST_DATA / "toy_case.tsv")
        selected_rows = (case_data.rows[0], case_data.rows[2], case_data.rows[4])
        assert_valid_solution(case_data, selected_rows, expected_total_cost=4.5)

    def test_assert_valid_solution_rejects_duplicate_riders(self) -> None:
        case_data = load_case_data(TEST_DATA / "toy_case.tsv")
        selected_rows = (case_data.rows[0], case_data.rows[2], case_data.rows[5])
        with self.assertRaises(ValueError):
            assert_valid_solution(case_data, selected_rows)

    def test_assert_valid_solution_rejects_fabricated_row(self) -> None:
        case_data = load_case_data(TEST_DATA / "toy_case.tsv")
        selected_rows = (
            case_data.rows[0],
            case_data.rows[2],
            Row(id=999, orders=(3,), rider=14, cost=1.0),
        )
        with self.assertRaises(ValueError):
            assert_valid_solution(case_data, selected_rows)


if __name__ == "__main__":
    unittest.main()
