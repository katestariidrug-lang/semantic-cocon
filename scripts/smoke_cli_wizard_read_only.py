from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Tuple


FileStamp = Tuple[int, int]  # (size_bytes, mtime_ns)


def snapshot_tree(root: Path) -> Dict[str, FileStamp]:
    """
    Snapshot of all files under repo root, excluding .git.
    Any new/changed/deleted file after running cli_wizard is a FAIL.
    """
    out: Dict[str, FileStamp] = {}
    root = root.resolve()

    for dirpath, dirnames, filenames in os.walk(root):
        # Never care about .git internals here (too noisy, not relevant to our driver).
        if ".git" in dirnames:
            dirnames.remove(".git")

        for name in filenames:
            p = Path(dirpath) / name
            try:
                st = p.stat()
            except FileNotFoundError:
                # If something races with us, treat as a change by omission.
                continue
            rel = str(p.relative_to(root)).replace("\\", "/")
            out[rel] = (st.st_size, st.st_mtime_ns)

    return out


def run_cli_wizard_help() -> int:
    cmd = [sys.executable, "-m", "scripts.cli_wizard", "--help"]
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    # Always print output to help debugging in CI/local runs.
    if r.stdout:
        print(r.stdout.rstrip())
    if r.stderr:
        print(r.stderr.rstrip(), file=sys.stderr)
    return r.returncode


def main() -> int:
    root = Path.cwd()

    before = snapshot_tree(root)
    rc = run_cli_wizard_help()
    after = snapshot_tree(root)

    if rc != 0:
        print(f"[FAIL] cli_wizard --help exited with {rc}", file=sys.stderr)
        return 1

    if before == after:
        print("[PASS] cli_wizard is read-only (no filesystem changes detected).")
        return 0

    # Compute diffs
    before_keys = set(before)
    after_keys = set(after)

    added = sorted(after_keys - before_keys)
    removed = sorted(before_keys - after_keys)
    changed = sorted(k for k in (before_keys & after_keys) if before[k] != after[k])

    print("[FAIL] cli_wizard caused filesystem changes:", file=sys.stderr)
    if added:
        print("  Added:", file=sys.stderr)
        for p in added:
            print(f"    + {p}", file=sys.stderr)
    if removed:
        print("  Removed:", file=sys.stderr)
        for p in removed:
            print(f"    - {p}", file=sys.stderr)
    if changed:
        print("  Changed:", file=sys.stderr)
        for p in changed:
            b = before[p]
            a = after[p]
            print(f"    * {p}  {b} -> {a}", file=sys.stderr)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
