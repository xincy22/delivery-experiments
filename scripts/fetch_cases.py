"""Fetch the repository's original Git LFS datasets using only Python's standard library."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://media.githubusercontent.com/media/xincy22/delivery-experiments/master/Case/'


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', nargs='+')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'Case/manifest.json').read_text(encoding='utf-8'))
    names = args.cases or sorted(manifest)
    for name in names:
        name = name if name.endswith('.tsv') else name + '.tsv'
        if name not in manifest:
            parser.error(f'Unknown case: {name}')
        expected, path = manifest[name], ROOT / 'Case' / name
        if (path.exists() and path.stat().st_size == expected['bytes']
                and digest(path) == expected['sha256']):
            print(f'{name}: SHA-256 verified', flush=True)
            continue
        if args.verify_only:
            raise SystemExit(f'{name}: missing, LFS pointer, or checksum mismatch')
        if path.exists():
            with path.open('rb') as handle:
                first = handle.readline(256)
            if not first.startswith(b'version https://git-lfs.github.com/spec/v1'):
                raise SystemExit(f'{name}: will not overwrite a modified non-pointer input')
        temporary = path.with_suffix('.tsv.part')
        owned_temporary = False
        try:
            request = urllib.request.Request(BASE + name, headers={'User-Agent': 'delivery-experiments-data-fetch'})
            sha = hashlib.sha256()
            size = 0
            with temporary.open('xb') as target:
                owned_temporary = True
                with urllib.request.urlopen(request, timeout=60) as response:
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        target.write(block)
                        sha.update(block)
                        size += len(block)
            if size != expected['bytes'] or sha.hexdigest() != expected['sha256']:
                raise ValueError(f'{name}: downloaded object failed size/SHA-256 verification')
            temporary.replace(path)
            print(f'{name}: fetched and SHA-256 verified ({size} bytes)', flush=True)
        finally:
            if owned_temporary:
                temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
