from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import json


class LifecycleViolation(RuntimeError):
    """
    Lifecycle violation = ошибка состояния пайплайна, а не "не получилось".
    Должна приводить к fail-fast (ненулевой exit code) на уровне CLI.
    """
    pass


class LifecycleState(str, Enum):
    # Snapshot-level lifecycle (authoritative via filesystem state)
    NO_SNAPSHOT = "NO_SNAPSHOT"                 # snapshot отсутствует
    SNAPSHOT_PRESENT = "SNAPSHOT_PRESENT"       # snapshot есть, approve нет
    APPROVED = "APPROVED"                       # approve есть
    EXECUTED_CORE = "EXECUTED_CORE"             # outputs core есть
    EXECUTED_ANCHORS = "EXECUTED_ANCHORS"       # outputs anchors есть
    EXECUTED_BOTH = "EXECUTED_BOTH"             # core+anchors есть
    MERGED = "MERGED"                           # merge-state есть (terminal для execute)
    # POSTCHECKED намеренно не вводим, пока нет канонического state-файла post-check


@dataclass(frozen=True)
class SnapshotPaths:
    snapshot_json: Path
    sha256_file: Path
    approvals_dir: Path
    outputs_dir: Path
    merges_by_run_dir: Path
    task_json: Path


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8").strip()


def _load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _sha_prefix(sha256_hex: str, n: int = 12) -> str:
    s = sha256_hex.strip()
    if len(s) < n:
        return s
    return s[:n]


def default_paths(repo_root: Path, snapshot_id: str) -> SnapshotPaths:
    return SnapshotPaths(
        snapshot_json=repo_root / "state" / "snapshots" / f"{snapshot_id}.snapshot.json",
        sha256_file=repo_root / "state" / "snapshots" / f"{snapshot_id}.sha256",
        approvals_dir=repo_root / "state" / "approvals",
        outputs_dir=repo_root / "outputs" / "pass_2" / snapshot_id,
        merges_by_run_dir=repo_root / "state" / "merges" / "by_run",
        task_json=repo_root / "input" / "task.json",
    )


def infer_snapshot_state(snapshot_id: str, repo_root: str | Path = ".") -> LifecycleState:
    """
    Детерминированно определяет lifecycle-state для snapshot_id
    по факту файлов/директорий.

    Важно: НЕ делает выводов по "истории диалога" и не читает логи.
    Только filesystem -> state.
    """
    root = Path(repo_root)
    paths = default_paths(root, snapshot_id)

    if not paths.snapshot_json.exists():
        return LifecycleState.NO_SNAPSHOT

    approved = False
    sha256_hex = None

    if paths.sha256_file.exists():
        sha256_hex = _read_text(paths.sha256_file)

        approval_file = paths.approvals_dir / f"{sha256_hex}.approved"
        approved = approval_file.exists()

    # outputs
    core_dir = paths.outputs_dir / "core"
    anchors_dir = paths.outputs_dir / "anchors"
    has_core = core_dir.exists()
    has_anchors = anchors_dir.exists()

    # merge-state pointer (by_run)
    # merge_id := <task_id>__<hashprefix>
    merged = False
    if sha256_hex and paths.task_json.exists():
        task = _load_json(paths.task_json)
        task_id = task.get("task_id")
        if isinstance(task_id, str) and task_id:
            merge_id = f"{task_id}__{_sha_prefix(sha256_hex)}"
            pointer = paths.merges_by_run_dir / f"{merge_id}.merge_id"
            if pointer.exists():
                merged = True

    if merged:
        return LifecycleState.MERGED

    if has_core and has_anchors:
        return LifecycleState.EXECUTED_BOTH
    if has_anchors:
        return LifecycleState.EXECUTED_ANCHORS
    if has_core:
        return LifecycleState.EXECUTED_CORE

    if approved:
        return LifecycleState.APPROVED

    return LifecycleState.SNAPSHOT_PRESENT


def require_not_merged(snapshot_id: str, repo_root: str | Path = ".") -> None:
    """
    Жёсткий стоп: после MERGE любые EXECUTE обязаны падать.
    В этом шаге функция просто существует; в следующем шаге её вызовет orchestrator.
    """
    st = infer_snapshot_state(snapshot_id, repo_root=repo_root)
    if st == LifecycleState.MERGED:
        raise LifecycleViolation(f"EXECUTE forbidden after MERGE (snapshot_id={snapshot_id})")

