"""Build and benchmark the self-written native solver; evaluate references afterward."""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shlex
import subprocess
import time

from verify import verify

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'solvers' / 'native_lns.cpp'


def build() -> Path:
    """Build the current source, caching by source content and compiler flags."""
    compiler = shlex.split(os.environ.get('CXX', 'g++'))
    flags = ['-std=c++11', '-O3', '-DNDEBUG', '-Wall', '-Wextra', '-Wpedantic']
    digest = hashlib.sha256(SOURCE.read_bytes() + repr(compiler + flags).encode()).hexdigest()[:16]
    directory = ROOT / '.build'
    directory.mkdir(exist_ok=True)
    binary = directory / ('native_' + digest)
    if not binary.exists():
        temporary = binary.with_suffix(f'.{os.getpid()}.tmp')
        try:
            subprocess.run(compiler + flags + [str(SOURCE), '-o', str(temporary)],
                           check=True, timeout=120)
            temporary.replace(binary)
        finally:
            temporary.unlink(missing_ok=True)
    return binary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-dir', type=Path, default=ROOT / 'Case')
    parser.add_argument('--cases', nargs='+', default=[f'case{i}.tsv' for i in range(1, 10)])
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--time-limit-sec', type=float, default=120.)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--mode', choices=['descent', 'annealed', 'directed'], default='descent')
    parser.add_argument('--pricing-rounds', type=int, default=200)
    parser.add_argument('--verify', action='store_true', help='Independently audit every completed run')
    args = parser.parse_args()
    if (not math.isfinite(args.time_limit_sec) or args.time_limit_sec <= 0
            or min(args.repeats, args.workers, args.pricing_rounds) <= 0):
        parser.error('Time must be finite and positive; counts must be positive')
    paths = [(args.case_dir / (name if name.endswith('.tsv') else name + '.tsv')).resolve()
             for name in args.cases]
    if len(set(paths)) != len(paths) or len({p.stem for p in paths}) != len(paths):
        parser.error('Cases must be distinct and have unique stems')
    for path in paths:
        if not path.is_file():
            parser.error(f'Missing case: {path}')
    output = args.output_dir.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error('Output directory is not empty; choose a new experiment directory')
    output.mkdir(parents=True, exist_ok=True)
    binary = build()
    # References are used by this reporting layer, never passed to the solver.
    reference_file = args.case_dir / 'Optimal objectives.tsv'
    references = {}
    if reference_file.exists():
        for line in reference_file.read_text(encoding='utf-8').splitlines():
            if line.strip():
                name, cost = line.split('\t')
                references[name] = float(cost)
    compiler_version = subprocess.check_output(
        shlex.split(os.environ.get('CXX', 'g++')) + ['--version'], text=True).splitlines()[0]
    config = {**vars(args), 'case_dir': str(args.case_dir), 'output_dir': str(output),
              'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
              'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'compiler': compiler_version, 'platform': platform.platform(),
              'timing': 'Per-run solver includes parsing and search, excludes build and audit; soft deadline.'}
    (output / 'configuration.json').write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
    (output / 'solver_source.cpp').write_bytes(SOURCE.read_bytes())

    def run(job: tuple[Path, int]) -> dict:
        path, repeat = job
        seed = args.seed + repeat - 1
        directory = output / path.stem / f'repeat-{repeat}'
        directory.mkdir(parents=True)
        prefix = directory / 'solution'
        command = [str(binary), str(path), str(prefix), str(args.time_limit_sec),
                   str(seed), str(args.pricing_rounds), args.mode]
        started = time.perf_counter()
        with (directory / 'solver.log').open('w', encoding='utf-8') as log:
            try:
                completed = subprocess.run(command, stdout=log, stderr=log, check=False,
                                           timeout=args.time_limit_sec + 120)
                returncode = completed.returncode
            except subprocess.TimeoutExpired:
                returncode = -1
                log.write('\nWATCHDOG_TIMEOUT\n')
        record = {'case': path.name, 'repeat': repeat, 'seed': seed, 'mode': args.mode,
                  'returncode': returncode, 'process_wall_sec': time.perf_counter() - started,
                  'feasible': False}
        metrics_path = Path(str(prefix) + '.json')
        if returncode == 0 and metrics_path.exists():
            record.update(json.loads(metrics_path.read_text(encoding='utf-8')))
            reference = references.get(path.name)
            record['reference_cost'] = reference
            record['gap_pct'] = 100 * (record['total_cost'] / reference - 1) if reference and reference > 0 else None
            if args.verify:
                try:
                    audit = verify(path, prefix)
                    (directory / 'audit.json').write_text(json.dumps(audit, indent=2) + '\n', encoding='utf-8')
                    record['audit_passed'] = True
                    record['global_gap_bound_pct'] = audit['global_gap_bound_pct']
                except Exception as error:
                    record['audit_passed'] = False
                    record['audit_error'] = str(error)
                    record['feasible'] = False
        print(json.dumps(record, ensure_ascii=False), flush=True)
        return record

    started = time.perf_counter()
    jobs = [(path, repeat) for path in paths for repeat in range(1, args.repeats + 1)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run, jobs))
    (output / 'summary.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    fields = ['case', 'repeat', 'seed', 'mode', 'feasible', 'returncode', 'total_cost',
              'reference_cost', 'gap_pct', 'runtime_sec', 'first_feasible_sec',
              'best_found_sec', 'iterations', 'nodes', 'lower_bound', 'audit_passed',
              'global_gap_bound_pct', 'process_wall_sec']
    with (output / 'summary.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore', lineterminator='\n')
        writer.writeheader()
        writer.writerows(results)
    all_ok = all(record['feasible'] and record['returncode'] == 0 for record in results)
    print('BENCHMARK_DONE', json.dumps({'runs': len(results), 'all_ok': all_ok,
                                       'wall_sec_including_audit': time.perf_counter() - started}), flush=True)
    if not all_ok:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
