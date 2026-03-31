from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Row:
    id: int
    orders: tuple[int, ...]
    rider: int
    cost: float


@dataclass(frozen=True, slots=True)
class CaseData:
    case_name: str
    case_path: Path
    rows: tuple[Row, ...]
    orders: tuple[int, ...]
    riders: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RunResult:
    solver_name: str
    case_name: str
    total_cost: float
    runtime_sec: float
    feasible: bool
    selected_rows: tuple[Row, ...]
