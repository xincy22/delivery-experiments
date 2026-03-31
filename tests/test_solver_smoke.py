from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from benchmark import main as benchmark_main
from solvers.greedy_repair.solver import solve as solve_greedy_repair
from solvers.simulated_annealing import algorithm as simulated_annealing_algorithm
from solvers.simulated_annealing.solver import solve as solve_simulated_annealing


TEST_DATA = Path(__file__).parent / "data"


class SolverSmokeTests(unittest.TestCase):
    def test_greedy_repair_finds_feasible_toy_solution(self) -> None:
        result = solve_greedy_repair(TEST_DATA / "toy_case.tsv", time_limit_sec=5.0)
        self.assertTrue(result.feasible)
        self.assertGreater(len(result.selected_rows), 0)
        self.assertLessEqual(result.total_cost, 7.5)

    def test_simulated_annealing_finds_feasible_toy_solution(self) -> None:
        with mock.patch.object(simulated_annealing_algorithm, "SEED", None):
            result = solve_simulated_annealing(TEST_DATA / "toy_case.tsv", time_limit_sec=5.0)
        self.assertTrue(result.feasible)
        self.assertGreater(len(result.selected_rows), 0)
        self.assertLessEqual(result.total_cost, 7.5)

    def test_simulated_annealing_is_reproducible_with_fixed_seed(self) -> None:
        with mock.patch.object(simulated_annealing_algorithm, "SEED", 7):
            result_a = solve_simulated_annealing(TEST_DATA / "toy_case.tsv", time_limit_sec=5.0)
        with mock.patch.object(simulated_annealing_algorithm, "SEED", 7):
            result_b = solve_simulated_annealing(TEST_DATA / "toy_case.tsv", time_limit_sec=5.0)

        self.assertEqual(result_a.feasible, result_b.feasible)
        self.assertEqual(result_a.total_cost, result_b.total_cost)
        self.assertEqual(
            tuple(row.id for row in result_a.selected_rows),
            tuple(row.id for row in result_b.selected_rows),
        )

    def test_benchmark_single_case_single_repeat(self) -> None:
        workspace_tmp = Path.cwd() / ".test-tmp"
        workspace_tmp.mkdir(parents=True, exist_ok=True)
        output_dir = workspace_tmp / "benchmark-smoke"
        output_dir.mkdir(parents=True, exist_ok=True)
        args = [
            "benchmark.py",
            "--solver",
            "all",
            "--case-dir",
            str(TEST_DATA),
            "--cases",
            "toy_case.tsv",
            "--repeats",
            "1",
            "--output-dir",
            str(output_dir),
            "--time-limit-sec",
            "5",
        ]
        with mock.patch("sys.argv", args):
            benchmark_main()
        self.assertTrue((output_dir / "greedy_repair" / "toy_case.tsv" / "repeat-1.tsv").exists())
        self.assertTrue((output_dir / "simulated_annealing" / "toy_case.tsv" / "repeat-1.tsv").exists())


if __name__ == "__main__":
    unittest.main()
