"""Small exhaustive oracles and independent output/dual verification (stdlib only)."""
from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verify import verify


def exhaustive(rows):
    orders = set().union(*(set(orders) for orders, _, _ in rows))
    best = math.inf

    def dfs(left, used_riders, cost):
        nonlocal best
        if not left:
            best = min(best, cost)
            return
        order = min(left, key=lambda o: sum(
            o in bundle and set(bundle) <= left and rider not in used_riders
            for bundle, rider, _ in rows))
        for bundle, rider, row_cost in rows:
            if order in bundle and set(bundle) <= left and rider not in used_riders:
                dfs(left - set(bundle), used_riders | {rider}, cost + row_cost)

    dfs(orders, set(), 0.)
    return best


class NativeSolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        override = os.environ.get('NATIVE_TEST_BINARY')
        if override:
            cls.binary = Path(override).resolve()
        else:
            from benchmark import build
            cls.binary = build()

    def check_case(self, rows, seconds=.35, mode='descent'):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            case, prefix = directory / 'toy.tsv', directory / 'solution'
            case.write_text(''.join(','.join(map(str, orders)) + f'\t{rider}\t{cost:.17g}\n'
                                    for orders, rider, cost in rows), encoding='utf-8')
            command = [str(self.binary), str(case), str(prefix), str(seconds), '23', '100', mode]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=15)
            optimum = exhaustive(rows)
            if not math.isfinite(optimum):
                self.assertEqual(completed.returncode, 3, completed.stderr)
                self.assertFalse(Path(str(prefix) + '.tsv').exists())
                return
            self.assertEqual(completed.returncode, 0, completed.stderr)
            audit = verify(case, prefix, manifest_path=directory / 'absent.json')
            self.assertTrue(audit['passed'])
            self.assertLessEqual(audit['full_lower_bound'], optimum + 1e-7)
            self.assertAlmostEqual(audit['total_cost'], optimum, places=7, msg=completed.stderr)
            metrics = json.loads(Path(str(prefix) + '.json').read_text())
            self.assertLessEqual(metrics['first_feasible_sec'], metrics['best_found_sec'])
            self.assertLessEqual(metrics['best_found_sec'], metrics['runtime_sec'])

    def test_toy(self):
        rows = []
        for line in (ROOT / 'tests/data/toy_case.tsv').read_text().splitlines():
            orders, rider, cost = line.split('\t')
            rows.append((tuple(map(int, orders.split(','))), int(rider), float(cost)))
        self.check_case(rows)

    def test_bundling_required(self):
        self.check_case([((1,), 1, 1.), ((2,), 1, 1.), ((1, 2), 1, 3.)])

    def test_no_singleton_candidates(self):
        self.check_case([((1, 2), 1, 8.), ((3, 4), 2, 3.), ((1, 2, 3, 4), 3, 9.)])

    def test_rider_augmenting_chain(self):
        self.check_case([((1,), 1, 1.), ((1,), 2, 2.), ((2,), 2, 1.),
                         ((2,), 3, 2.), ((3,), 1, 1.)])

    def test_negative_costs(self):
        self.check_case([((1,), 1, -3.), ((2,), 1, -4.), ((2,), 2, 2.), ((1, 2), 3, -7.)])

    def test_zero_costs(self):
        self.check_case([((1,), 1, 0.), ((2,), 2, 0.), ((1, 2), 1, 1.)])

    def test_duplicate_candidates_and_unsorted_orders(self):
        self.check_case([((1, 2), 1, 5.), ((2, 1), 1, 3.), ((1,), 2, 6.), ((2,), 3, 7.)])

    def test_infeasible_is_not_published(self):
        self.check_case([((1,), 1, 1.), ((2,), 1, 1.)], seconds=.1)

    def test_all_modes(self):
        rows = [((1,), 1, 3.), ((2,), 1, 1.), ((2,), 2, 3.), ((1, 2), 3, 2.)]
        for mode in ('descent', 'annealed', 'directed'):
            with self.subTest(mode=mode):
                self.check_case(rows, mode=mode)

    def test_random_small_against_exhaustive(self):
        for seed in range(30):
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                count = rng.randint(3, 6)
                rows = [((o,), 100 + o, rng.uniform(1, 9)) for o in range(count)]
                for _ in range(28):
                    bundle = tuple(sorted(rng.sample(range(count), rng.randint(1, min(count, 3)))))
                    rows.append((bundle, 100 + rng.randrange(count + 2), rng.uniform(.2, 10)))
                self.check_case(rows, seconds=.4)

    def test_invalid_inputs_and_cli(self):
        texts = ['version https://git-lfs.github.com/spec/v1\n', '1,1\t1\t2\n',
                 '1\t2\tnan\n', '1\t2\t3\textra\n', '', '99999999999999999999999\t1\t1\n',
                 '1\t99999999999999999999999\t1\n',
                 ','.join(map(str, range(61))) + '\t1\t1\n']
        for text in texts:
            with self.subTest(text=text[:50]), tempfile.TemporaryDirectory() as directory:
                directory = Path(directory)
                case = directory / 'bad.tsv'
                case.write_text(text)
                completed = subprocess.run([str(self.binary), str(case), str(directory / 'out'), '.1'],
                                           capture_output=True, timeout=10)
                self.assertNotEqual(completed.returncode, 0)
        with tempfile.TemporaryDirectory() as directory:
            for seconds in ['nan', 'inf', '-1']:
                completed = subprocess.run([str(self.binary), str(ROOT / 'tests/data/toy_case.tsv'),
                                            str(Path(directory) / 'out'), seconds], capture_output=True)
                self.assertNotEqual(completed.returncode, 0)

    def test_no_stale_output_reuse_and_corrupted_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            prefix = directory / 'solution'
            case = ROOT / 'tests/data/toy_case.tsv'
            command = [str(self.binary), str(case), str(prefix), '2', '1', '100']
            subprocess.run(command, capture_output=True, check=True)
            original = Path(str(prefix) + '.tsv').read_bytes()
            completed = subprocess.run(command, capture_output=True)
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(Path(str(prefix) + '.tsv').read_bytes(), original)
            certificate = Path(str(prefix) + '.dual.tsv')
            text = certificate.read_text().splitlines()
            fields = text[1].split('\t')
            fields[2] = '1000000000'
            text[1] = '\t'.join(fields)
            certificate.write_text('\n'.join(text) + '\n')
            with self.assertRaises(ValueError):
                verify(case, prefix)

    def test_benchmark_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, str(ROOT / 'benchmark.py'), '--case-dir', str(ROOT / 'tests/data'),
                       '--cases', 'toy_case.tsv', '--time-limit-sec', '2', '--output-dir',
                       str(Path(directory) / 'experiment'), '--verify']
            subprocess.run(command, capture_output=True, text=True, timeout=120, check=True)
            summary = json.loads((Path(directory) / 'experiment/summary.json').read_text())
            self.assertTrue(summary[0]['audit_passed'])
            self.assertAlmostEqual(summary[0]['total_cost'], 4.5)


if __name__ == '__main__':
    unittest.main()
