#!/usr/bin/env python3
"""Snapshot the source corresponding to an isolated prepared replay build."""
import argparse, datetime, hashlib, json, shutil, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--build-dir', type=Path, required=True)
    args = parser.parse_args()
    out = args.output_root.resolve()
    files = [ROOT/'CMakeLists.txt']
    for folder in ['src', 'include', 'Examples/Multi-Inertial', 'scripts']:
        files += [p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in {'.cc', '.cpp', '.h', '.hpp', '.py', '.sh'}]
    snapshot = out/'build_source_snapshot'
    hashes = {}
    for source in files:
        relative = source.relative_to(ROOT)
        target = snapshot/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[str(relative)] = hashlib.sha256(source.read_bytes()).hexdigest()
    cache = args.build_dir/'CMakeCache.txt'
    shutil.copyfile(cache, snapshot/'CMakeCache.txt')
    git = lambda *args: subprocess.check_output(['git', *args], cwd=ROOT)
    (out/'build.patch').write_bytes(git('diff', 'HEAD', '--binary'))
    record = {'built_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'git_head': git('rev-parse', 'HEAD').decode().strip(),
              'git_status': git('status', '--short').decode(), 'source_sha256': hashes,
              'build_dir': str(args.build_dir.resolve()), 'output_root': str(out)}
    (out/'build_provenance.json').write_text(json.dumps(record, indent=2)+'\n')

if __name__ == '__main__':
    main()
