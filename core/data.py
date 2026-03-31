from __future__ import annotations

from pathlib import Path

from core.models import CaseData, Row


def load_optimal_total_costs(path: Path) -> dict[str, float]:
    total_costs: dict[str, float] = {}
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            case_name, total_cost_text = line.split("\t")
            total_costs[case_name] = float(total_cost_text)
    return total_costs


def load_case_data(case_path: Path) -> CaseData:
    rows: list[Row] = []
    order_set: set[int] = set()
    rider_set: set[int] = set()

    with case_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue

            parts = line.split("\t")
            if len(parts) != 3:
                raise ValueError(
                    f"Malformed line {line_number} in {case_path}: expected 3 tab-separated fields."
                )

            orders_text, rider_text, cost_text = parts
            orders = tuple(sorted(int(token) for token in orders_text.split(",")))
            rider = int(rider_text)
            cost = float(cost_text)

            rows.append(
                Row(
                    id=len(rows),
                    orders=orders,
                    rider=rider,
                    cost=cost,
                )
            )
            order_set.update(orders)
            rider_set.add(rider)

    return CaseData(
        case_name=case_path.name,
        case_path=case_path,
        rows=tuple(rows),
        orders=tuple(sorted(order_set)),
        riders=tuple(sorted(rider_set)),
    )
