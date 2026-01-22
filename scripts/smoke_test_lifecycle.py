from __future__ import annotations

import json
import os
import re
import sys
import time
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

LEVEL_RE = re.compile(r"^\[(PASS|FAIL|BLOCKER)\]\s+([A-Z0-9_]+):\s+(.+)$")


@dataclass
class StepResult:
    cmd: List[str]
    rc: int
    out: str
    err: str
    level: str
    code: str
    message: str


def _die(msg: str) -> None:
    print(f"[BLOCKER] LIFECYCLE_VIOLATION: {msg}")
    raise SystemExit(2)


def _run(cmd: List[str], cwd: Optional[Path] = None) -> StepResult:
    p = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )

    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()

    combined_first_line = ""
    if out:
        combined_first_line = out.splitlines()[0].strip()
    elif err:
        combined_first_line = err.splitlines()[0].strip()

    if p.returncode not in (0, 1, 2):
        _die(f"Exit code must be 0/1/2, got {p.returncode} for: {' '.join(cmd)}")

    m = LEVEL_RE.match(combined_first_line)
    if not m:
        _die(
            "First line must match `[LEVEL] ERROR_CODE: message` "
            f"but got: `{combined_first_line}` for: {' '.join(cmd)}"
        )

    level, code, message = m.group(1), m.group(2), m.group(3)

    return StepResult(
        cmd=cmd, rc=p.returncode, out=out, err=err, level=level, code=code, message=message
    )


def _expect_pass(r: StepResult, step_name: str) -> None:
    if r.rc != 0 or r.level != "PASS":
        details = []
        details.append(f"Step `{step_name}` expected PASS/0, got {r.level}/{r.rc}.")
        details.append(f"First line: [{r.level}] {r.code}: {r.message}")
        if r.out:
            details.append("STDOUT:\n" + r.out)
        if r.err:
            details.append("STDERR:\n" + r.err)
        _die("\n".join(details))


def _expect_blocker(r: StepResult, step_name: str) -> None:
    if r.rc != 2 or r.level != "BLOCKER":
        details = []
        details.append(f"Step `{step_name}` expected BLOCKER/2, got {r.level}/{r.rc}.")
        details.append(f"First line: [{r.level}] {r.code}: {r.message}")
        if r.out:
            details.append("STDOUT:\n" + r.out)
        if r.err:
            details.append("STDERR:\n" + r.err)
        _die("\n".join(details))


def _expect_fail(r: StepResult, step_name: str) -> None:
    if r.rc != 1 or r.level != "FAIL":
        details = []
        details.append(f"Step `{step_name}` expected FAIL/1, got {r.level}/{r.rc}.")
        details.append(f"First line: [{r.level}] {r.code}: {r.message}")
        if r.out:
            details.append("STDOUT:\n" + r.out)
        if r.err:
            details.append("STDERR:\n" + r.err)
        _die("\n".join(details))

def _extract_snapshot_id_from_output(text: str) -> Optional[str]:
    # We try to be resilient to exact message wording:
    # Look for common tokens like `snapshot_id = ...` or `snapshot_id=...`
    m = re.search(r"\bsnapshot_id\b\s*[:=]\s*([A-Za-z0-9][A-Za-z0-9_.-]*__[^ \n\r\t]+)", text)
    if m:
        return m.group(1).strip()

    # Fallback: find something that looks like `<task_id>__<hashprefix>` (used widely in the repo).
    # This is intentionally conservative: require at least one `__` and a hash-ish tail.
    m2 = re.search(r"\b([A-Za-z0-9][A-Za-z0-9_.-]*__([0-9a-f]{8,64}))\b", text, re.IGNORECASE)
    if m2:
        return m2.group(1).strip()

    return None


def _list_merge_id_files(by_run_dir: Path) -> set[Path]:
    if not by_run_dir.exists():
        _die(f"Missing merges/by_run directory: {by_run_dir}")
    return set(by_run_dir.glob("*.merge_id"))


def _read_merge_id_from_file(p: Path) -> str:
    merge_id = p.read_text(encoding="utf-8").strip()
    if not merge_id:
        _die(f"Empty merge_id in file: {p}")
    return merge_id


def _read_new_merge_id(by_run_dir: Path, before: set[Path]) -> str:
    after = _list_merge_id_files(by_run_dir)
    created = sorted(after - before, key=lambda p: p.stat().st_mtime, reverse=True)

    if len(created) == 1:
        return _read_merge_id_from_file(created[0])

    if len(created) > 1:
        # If multiple files appeared (unexpected), pick the newest but fail loudly.
        newest = created[0]
        _die(
            "Multiple *.merge_id files created during smoke merge; cannot disambiguate reliably. "
            f"Candidates: {[p.name for p in created]}. Newest: {newest.name}"
        )

    # None created: merge either failed to create pointer or updated existing file.
    # Fallback to newest file, but still block because this breaks the black-box invariant.
    _die("MERGE did not create a new *.merge_id pointer in state/merges/by_run")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]

    state_snapshots = repo_root / "state" / "snapshots"
    if not state_snapshots.exists():
        _die(f"Missing state/snapshots directory: {state_snapshots}")

    merges_by_run = repo_root / "state" / "merges" / "by_run"

    # Ensure isolation from previous runs: use a unique task_id for this smoke run.
    task_path = repo_root / "input" / "task.json"
    if not task_path.exists():
        _die(f"Missing input/task.json: {task_path}")

    original_task_text = task_path.read_text(encoding="utf-8")
    try:
        # Parse task.json and inject a unique task_id for this smoke run.
        try:
            task_obj = json.loads(original_task_text)
        except Exception as e:
            _die(f"input/task.json is not valid JSON: {e}")

        unique_task_id = f"smoke_task__{int(time.time())}"
        task_obj["task_id"] = unique_task_id
        task_path.write_text(json.dumps(task_obj, ensure_ascii=False), encoding="utf-8")

        # 1) snapshot (DECIDE -> SNAPSHOT)
        r_decide = _run([sys.executable, "-m", "scripts.orchestrator", "decide"], cwd=repo_root)
        _expect_pass(r_decide, "snapshot/decide")

        snapshot_id = _extract_snapshot_id_from_output(r_decide.out + "\n" + r_decide.err)
        if not snapshot_id:
            _die(
                "Could not extract snapshot_id from orchestrator decide output. "
                "Expected token like `snapshot_id=<...>` somewhere in stdout/stderr.\n"
                f"STDOUT:\n{r_decide.out}\nSTDERR:\n{r_decide.err}"
            )

        snapshot_path = repo_root / "state" / "snapshots" / f"{snapshot_id}.snapshot.json"
        if not snapshot_path.exists():
            _die(f"Snapshot file not found after decide: {snapshot_path}")

        # 2) execute before approve -> BLOCKER
        r_exec_before_approve = _run(
            [
                sys.executable,
                "-m",
                "scripts.orchestrator",
                "execute",
                "--stage",
                "core",
                "--snapshot",
                str(snapshot_path.as_posix()),
            ],
            cwd=repo_root,
        )
        _expect_blocker(r_exec_before_approve, "execute-before-approve")

        # 3) approve without snapshot -> BLOCKER (guaranteed missing snapshot_id)
        missing_snapshot_id = f"missing__{int(time.time())}__00000000"
        missing_snapshot_path = repo_root / "state" / "snapshots" / f"{missing_snapshot_id}.sha256"
        if missing_snapshot_path.exists():
            _die(f"Test invariant broken: expected missing snapshot file not to exist: {missing_snapshot_path}")

        r_approve_missing = _run(
            [sys.executable, "-m", "scripts.orchestrator", "approve", "--snapshot", missing_snapshot_id],
            cwd=repo_root,
        )
        _expect_fail(r_approve_missing, "approve-missing-snapshot")

        # 4) approve (valid)
        r_approve = _run(
            [sys.executable, "-m", "scripts.orchestrator", "approve", "--snapshot", snapshot_id],
            cwd=repo_root,
        )
        _expect_pass(r_approve, "approve")

        # 5) execute (CORE)
        r_core = _run(
            [
                sys.executable,
                "-m",
                "scripts.orchestrator",
                "execute",
                "--stage",
                "core",
                "--snapshot",
                str(snapshot_path.as_posix()),
            ],
            cwd=repo_root,
        )
        _expect_pass(r_core, "execute/core")

        # 5) execute (ANCHORS)
        r_anchors = _run(
            [
                sys.executable,
                "-m",
                "scripts.orchestrator",
                "execute",
                "--stage",
                "anchors",
                "--snapshot",
                str(snapshot_path.as_posix()),
            ],
            cwd=repo_root,
        )
        _expect_pass(r_anchors, "execute/anchors")

        # 6) post-check ДО MERGE запрещён (попытка по snapshot_id) -> BLOCKER
        r_post_before_merge = _run(
            [sys.executable, "scripts/check_deliverables.py", snapshot_id], cwd=repo_root
        )
        _expect_blocker(r_post_before_merge, "post-check-before-merge")

        # 7) post-check по task_id запрещён -> BLOCKER
        r_post_by_task_id = _run(
            [sys.executable, "scripts/check_deliverables.py", unique_task_id], cwd=repo_root
        )
        _expect_blocker(r_post_by_task_id, "post-check-by-task-id")

        # 8) merge
        merge_files_before = _list_merge_id_files(merges_by_run)

        r_merge = _run(
            [
                sys.executable,
                "-m",
                "scripts.merge_pass2",
                "--core-snapshot-id",
                snapshot_id,
                "--anchors-snapshot-id",
                snapshot_id,
            ],
            cwd=repo_root,
        )
        _expect_pass(r_merge, "merge")

        # Read merge_id created by THIS merge (robust vs parallel runs / stale state).
        merge_id = _read_new_merge_id(merges_by_run, merge_files_before)

        # 9) post-check без merge_id запрещён -> BLOCKER
        r_post_missing_merge_id = _run([sys.executable, "scripts/check_deliverables.py"], cwd=repo_root)
        _expect_blocker(r_post_missing_merge_id, "post-check-missing-merge-id")

        # 10) post-check (корректный запуск по merge_id) -> PASS
        r_post = _run([sys.executable, "scripts/check_deliverables.py", merge_id], cwd=repo_root)
        _expect_pass(r_post, "post-check")


        # 11) повторный execute → BLOCKER (STOP-condition)
        r_forbidden = _run(
            [
                sys.executable,
                "-m",
                "scripts.orchestrator",
                "execute",
                "--stage",
                "core",
                "--snapshot",
                str(snapshot_path.as_posix()),
            ],
            cwd=repo_root,
        )
        _expect_blocker(r_forbidden, "execute-after-merge")

        print("[PASS] OK: lifecycle + CLI contract OK")
        return 0
    finally:
        # Restore original task.json no matter what happened.
        task_path.write_text(original_task_text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
