from __future__ import annotations

import math

from core.models import CaseData, Row


def assert_valid_solution(
    case_data: CaseData,
    selected_rows: tuple[Row, ...] | list[Row],
    expected_total_cost: float | None = None,
) -> None:
    row_by_id = {row.id: row for row in case_data.rows}
    used_riders: set[int] = set()
    order_counts = {order_id: 0 for order_id in case_data.orders}
    total_cost = 0.0

    for row in selected_rows:
        actual = row_by_id.get(row.id)
        if actual is None:
            raise ValueError(f"Unknown row id in solution: {row.id}")
        if (
            actual.orders != row.orders
            or actual.rider != row.rider
            or not math.isclose(actual.cost, row.cost, rel_tol=1e-9, abs_tol=1e-6)
        ):
            raise ValueError(f"Solution row {row.id} does not match the instance.")

        if row.rider in used_riders:
            raise ValueError(f"Rider {row.rider} is used more than once.")
        used_riders.add(row.rider)

        for order_id in row.orders:
            if order_id not in order_counts:
                raise ValueError(f"Unknown order {order_id} in solution.")
            order_counts[order_id] += 1

        total_cost += row.cost

    missing = [order_id for order_id, count in order_counts.items() if count == 0]
    repeated = [order_id for order_id, count in order_counts.items() if count > 1]
    if missing:
        raise ValueError(f"Orders missing from solution: {missing[:10]}")
    if repeated:
        raise ValueError(f"Orders covered multiple times: {repeated[:10]}")

    if expected_total_cost is not None and not math.isclose(
        total_cost,
        expected_total_cost,
        rel_tol=1e-9,
        abs_tol=1e-6,
    ):
        raise ValueError(
            f"Total cost mismatch: reconstructed {total_cost:.6f}, expected {expected_total_cost:.6f}."
        )
