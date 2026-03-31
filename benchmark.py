from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

from core.data import load_optimal_total_costs
from core.models import RunResult

SOLVERS: dict = {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark dispatch solvers.")
    parser.add_argument("--solver", choices=["all", *sorted(SOLVERS)], default="all")
    parser.add_argument("--case-dir", type=Path, default=Path("Case"))
    parser.add_argument("--cases", nargs="*", default=None)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs") / "benchmark")
    parser.add_argument("--time-limit-sec", type=float, default=None)
    return parser.parse_args()


def write_solution(path: Path, result: RunResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["orders", "rider", "cost"])
        for row in result.selected_rows:
            writer.writerow(
                [
                    ",".join(str(order_id) for order_id in row.orders),
                    row.rider,
                    f"{row.cost:.6f}",
                ]
            )


def main() -> None:
    args = parse_args()
    case_paths = [args.case_dir / case_name for case_name in args.cases] if args.cases else sorted(
        args.case_dir.glob("case*.tsv")
    )
    solver_names = sorted(SOLVERS) if args.solver == "all" else [args.solver]
    total_runs = len(solver_names) * len(case_paths) * args.repeats
    optimal_total_costs_path = args.case_dir / "Optimal objectives.tsv"
    optimal_total_costs = (
        load_optimal_total_costs(optimal_total_costs_path)
        if optimal_total_costs_path.exists()
        else {}
    )
    benchmark_start = time.perf_counter()
    completed_runs = 0

    time_limit_text = "none" if args.time_limit_sec is None else f"{args.time_limit_sec:.2f}s"
    print(
        f"benchmark | solvers={','.join(solver_names)} | cases={len(case_paths)} | "
        f"repeats={args.repeats} | time_limit={time_limit_text}"
    )

    for solver_name in solver_names:
        solver = SOLVERS[solver_name]
        for case_path in case_paths:
            for repeat in range(1, args.repeats + 1):
                completed_runs += 1
                elapsed_before_run = time.perf_counter() - benchmark_start
                print(
                    f"\n[{completed_runs}/{total_runs}] start | "
                    f"solver={solver_name} | case={case_path.name} | repeat={repeat} | "
                    f"elapsed={elapsed_before_run:.2f}s"
                )
                if args.time_limit_sec is None:
                    result = solver(case_path)
                else:
                    result = solver(case_path, time_limit_sec=args.time_limit_sec)
                optimal_total_cost = optimal_total_costs.get(case_path.name)
                gap = None
                if result.feasible and optimal_total_cost not in (None, 0.0):
                    gap = (result.total_cost - optimal_total_cost) / optimal_total_cost

                solution_path = (
                    args.output_dir
                    / solver_name
                    / case_path.name
                    / f"repeat-{repeat}.tsv"
                )
                write_solution(solution_path, result)
                optimal_text = "n/a" if optimal_total_cost is None else f"{optimal_total_cost:.4f}"
                gap_text = "n/a" if gap is None else f"{gap:.4%}"
                print(
                    f"[{completed_runs}/{total_runs}] done | {solver_name} | {case_path.name} | repeat={repeat} | "
                    f"feasible={result.feasible} | total_cost={result.total_cost:.4f} | "
                    f"selected_rows={len(result.selected_rows)} | "
                    f"optimal_total_cost={optimal_text} | gap={gap_text} | "
                    f"runtime={result.runtime_sec:.2f}s"
                )
                print(f"saved_solution={solution_path}")

    total_elapsed = time.perf_counter() - benchmark_start
    print(f"\nbenchmark_done | runs={total_runs} | elapsed={total_elapsed:.2f}s")


if __name__ == "__main__":
    main()
