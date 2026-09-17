"""Independently check a saved solution and dual certificate against raw TSV rows.

This module imports no solver code and uses no optimization or numerical package.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parent


def verify(case_path: Path, prefix: Path, *, manifest_path: Path | None = None) -> dict:
    """Stream every raw row, checking primal feasibility and all dual inequalities."""
    started = time.perf_counter()
    case_path, prefix = Path(case_path), Path(prefix)
    with Path(str(prefix) + '.tsv').open(encoding='utf-8') as handle:
        selected = list(csv.DictReader(handle, delimiter='\t'))
    by_id = {int(row['row_id']): row for row in selected}
    if len(by_id) != len(selected) or any(index < 0 for index in by_id):
        raise ValueError('Repeated or artificial selected row ID')

    pi: dict[int, float] = {}
    mu: dict[int, float] = {}
    with Path(str(prefix) + '.dual.tsv').open(encoding='utf-8') as handle:
        for row in csv.DictReader(handle, delimiter='\t'):
            if row['kind'] not in ('order', 'rider'):
                raise ValueError('Unknown dual kind')
            target = pi if row['kind'] == 'order' else mu
            index, value = int(row['id']), float(row['value'])
            if index in target or not math.isfinite(value):
                raise ValueError('Repeated ID or nonfinite dual value')
            target[index] = value
    if not pi or any(value > 0 for value in mu.values()):
        raise ValueError('Order prices are missing or a rider dual is positive')

    all_orders: set[int] = set()
    all_riders: set[int] = set()
    order_counts: Counter[int] = Counter()
    rider_counts: Counter[int] = Counter()
    found: set[int] = set()
    costs: list[float] = []
    sha = hashlib.sha256()
    raw_id, min_slack = -1, math.inf
    with case_path.open('rb') as handle:
        for raw in handle:
            sha.update(raw)
            if not raw.strip():
                continue
            raw_id += 1
            parts = raw.decode('utf-8').strip().split('\t')
            if len(parts) != 3:
                raise ValueError(f'Malformed raw row {raw_id}')
            orders_text, rider_text, cost_text = parts
            orders = tuple(sorted(map(int, orders_text.split(','))))
            rider, cost = int(rider_text), float(cost_text)
            if not orders or len(set(orders)) != len(orders) or not math.isfinite(cost):
                raise ValueError(f'Invalid raw row {raw_id}')
            all_orders.update(orders)
            all_riders.add(rider)
            try:
                slack = cost - math.fsum(pi[order] for order in orders) - mu[rider]
            except KeyError as error:
                raise ValueError(f'Missing dual ID at raw row {raw_id}') from error
            min_slack = min(min_slack, slack)
            if slack < -1e-7:
                raise ValueError(f'Dual inequality fails at row {raw_id}: slack={slack}')
            if raw_id in by_id:
                row = by_id[raw_id]
                if (tuple(sorted(map(int, row['orders'].split(',')))) != orders
                        or int(row['rider']) != rider
                        or not math.isclose(float(row['cost']), cost,
                                            abs_tol=1e-10, rel_tol=1e-12)):
                    raise ValueError(f'Selected row {raw_id} differs from raw input')
                found.add(raw_id)
                order_counts.update(orders)
                rider_counts[rider] += 1
                costs.append(cost)

    if found != set(by_id):
        raise ValueError('Selected row IDs do not exist in the input')
    if set(order_counts) != all_orders or any(count != 1 for count in order_counts.values()):
        raise ValueError('Each order must be covered exactly once')
    if any(count != 1 for count in rider_counts.values()):
        raise ValueError('A rider is used more than once')
    if set(pi) != all_orders or set(mu) != all_riders:
        raise ValueError('Certificate ID sets differ from the raw input')

    total = math.fsum(costs)
    lower = math.fsum(pi.values()) + math.fsum(mu.values())
    with Path(str(prefix) + '.json').open(encoding='utf-8') as handle:
        metrics = json.load(handle)
    if (not metrics.get('feasible')
            or not math.isclose(total, metrics['total_cost'], rel_tol=1e-12, abs_tol=1e-7)
            or not math.isclose(lower, metrics['lower_bound'], rel_tol=1e-12, abs_tol=1e-7)):
        raise ValueError('Saved metrics disagree with the independently reconstructed values')

    manifest_path = manifest_path or ROOT / 'Case' / 'manifest.json'
    matched = False
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        expected = manifest.get(case_path.name)
        if expected is not None:
            if sha.hexdigest() != expected['sha256'] or case_path.stat().st_size != expected['bytes']:
                raise ValueError('Input does not match its original Git LFS object')
            matched = True
    return {
        'case': case_path.name, 'passed': True, 'raw_rows_checked': raw_id + 1,
        'orders': len(all_orders), 'riders': len(all_riders),
        'selected_rows': len(selected), 'total_cost': total,
        'full_lower_bound': lower, 'min_dual_slack': min_slack,
        'global_gap_bound_pct': 100 * (total / lower - 1) if lower > 0 else None,
        'sha256': sha.hexdigest(), 'manifest_matched': matched,
        'audit_sec': time.perf_counter() - started,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    parser.add_argument('prefix', type=Path, help='Output prefix, without .tsv or .json')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify(args.case, args.prefix)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
