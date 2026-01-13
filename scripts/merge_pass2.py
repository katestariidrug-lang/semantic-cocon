import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional


# -------------------------
# Unified CLI contract (merge_pass2)
# -------------------------
EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_BLOCKER = 2

LEVEL_PASS = "PASS"
LEVEL_FAIL = "FAIL"
LEVEL_BLOCKER = "BLOCKER"

ERROR_CODES = {
    "OK",
    "INVALID_ARGUMENT",
    "IO_ERROR",
    "TASK_ID_MISMATCH",
    "SNAPSHOT_IMMUTABLE_VIOLATION",
    "MERGE_FINGERPRINT_MISMATCH",
    "MERGE_STATE_EXISTS",
    "MERGE_STATE_INVALID",
    "LIFECYCLE_VIOLATION",
}

def emit(level: str, code: str, message: str, evidence: Optional[dict] = None) -> None:
    if code not in ERROR_CODES:
        # неизвестный код = нарушение контракта => BLOCKER, но формат строки не ломаем
        print(f"[{LEVEL_BLOCKER}] LIFECYCLE_VIOLATION: unknown error code used")
        payload = {"bad_code": code}
        if evidence is not None:
            payload.update(evidence)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        raise SystemExit(EXIT_BLOCKER)

    print(f"[{level}] {code}: {message}")
    if evidence is not None:
        print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))

class MergeContractViolation(RuntimeError):
    """
    Нарушение контракта MERGE (инварианты, повторный merge, fingerprint mismatch).
    Должно приводить к exit code 2 (BLOCKER).
    """
    def __init__(self, code: str, message: str, evidence: Optional[dict] = None) -> None:
        super().__init__(message)
        self.code = code
        self.evidence = evidence or {}

ROOT = Path(__file__).resolve().parents[1]  # project-root/
STATE_DIR = ROOT / "state"


def _read_json(path: Path) -> Any:
    # existence is enforced by _require_file before reading
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        emit(
            LEVEL_FAIL,
            "MERGE_STATE_INVALID",
            "invalid json",
            evidence={"path": str(path), "error": str(e)},
        )
        raise SystemExit(EXIT_FAIL)
    except OSError as e:
        emit(
            LEVEL_FAIL,
            "IO_ERROR",
            "io error while reading json",
            evidence={"path": str(path), "error": str(e)},
        )
        raise SystemExit(EXIT_FAIL)

def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")

def _require_dir(path: Path, name: str) -> None:
    if not path.exists() or not path.is_dir():
        emit(
            LEVEL_FAIL,
            "IO_ERROR",
            f"missing required directory: {name}",
            evidence={"path": str(path)},
        )
        raise SystemExit(EXIT_FAIL)


def _require_file(path: Path, name: str) -> None:
    if not path.exists() or not path.is_file():
        emit(
            LEVEL_FAIL,
            "IO_ERROR",
            f"missing required file: {name}",
            evidence={"path": str(path)},
        )
        raise SystemExit(EXIT_FAIL)

def merge(core_snapshot_id: str, anchors_snapshot_id: str, outputs_dir: Path) -> None:
    outputs_dir = (ROOT / outputs_dir) if not outputs_dir.is_absolute() else outputs_dir
    pass2_dir = outputs_dir / "pass_2"

    core_base = pass2_dir / core_snapshot_id
    anchors_base = pass2_dir / anchors_snapshot_id

    # Ранние проверки входных директорий (диагностика должна быть про inputs, а не про merge-state)
    _require_dir(pass2_dir, "outputs/pass_2")
    _require_dir(core_base, "CORE snapshot")
    _require_dir(anchors_base, "ANCHORS snapshot")

    # run_id orchestrator: <task_id>__<hashprefix>, hashprefix = sha256(snapshot)[:12]
    if "__" not in core_snapshot_id:
        emit(
            LEVEL_FAIL,
            "INVALID_ARGUMENT",
            "invalid core_snapshot_id format (expected <task_id>__<hashprefix>)",
            evidence={"core_snapshot_id": core_snapshot_id},
        )
        raise SystemExit(EXIT_FAIL)

    if "__" not in anchors_snapshot_id:
        emit(
            LEVEL_FAIL,
            "INVALID_ARGUMENT",
            "invalid anchors_snapshot_id format (expected <task_id>__<hashprefix>)",
            evidence={"anchors_snapshot_id": anchors_snapshot_id},
        )
        raise SystemExit(EXIT_FAIL)

    core_task_id, core_hashprefix = core_snapshot_id.split("__", 1)
    anch_task_id, anch_hashprefix = anchors_snapshot_id.split("__", 1)

    if (core_task_id, core_hashprefix) != (anch_task_id, anch_hashprefix):
        emit(
            LEVEL_FAIL,
            "TASK_ID_MISMATCH",
            "CORE and ANCHORS belong to different runs",
            evidence={"core_snapshot_id": core_snapshot_id, "anchors_snapshot_id": anchors_snapshot_id},
        )
        raise SystemExit(EXIT_FAIL)

    task_id = core_task_id
    hashprefix = core_hashprefix
    merge_id = f"{task_id}__{hashprefix}"

    merges_dir = STATE_DIR / "merges"
    merges_by_run_dir = merges_dir / "by_run"

    merge_state_path = merges_dir / f"{merge_id}.json"
    merge_ptr_path = merges_by_run_dir / f"{task_id}__{hashprefix}.merge_id"

    # FAIL-FAST: не перезаписываем merge-state (иначе теряется точка невозврата)
    if merge_state_path.exists():
        raise MergeContractViolation(
            "MERGE_STATE_EXISTS",
            "merge-state already exists (refusing to overwrite; MERGE is terminal)",
            evidence={"path": str(merge_state_path)},
        )
    if merge_ptr_path.exists():
        raise MergeContractViolation(
            "MERGE_STATE_EXISTS",
            "merge pointer already exists (refusing to overwrite; MERGE is terminal)",
            evidence={"path": str(merge_ptr_path)},
        )

    core_dir = core_base / "core"
    anchors_dir = anchors_base / "anchors"

    _require_dir(core_dir, "core")
    _require_dir(anchors_dir, "anchors")

    core_sem = core_dir / "semantic_enrichment.json"
    core_kw = core_dir / "keywords.json"
    core_q = core_dir / "patient_questions.json"
    anchors_json = anchors_dir / "anchors.json"

    _require_file(core_sem, "core/semantic_enrichment.json")
    _require_file(core_kw, "core/keywords.json")
    _require_file(core_q, "core/patient_questions.json")
    _require_file(anchors_json, "anchors/anchors.json")

    # --- ENFORCE SNAPSHOT COMPATIBILITY ---
    core_exec_path = core_base / "core" / "execution_result.json"
    anchors_exec_path = anchors_base / "anchors" / "execution_result.json"

    _require_file(core_exec_path, "core/execution_result.json")
    _require_file(anchors_exec_path, "anchors/execution_result.json")

    core_exec = _read_json(core_exec_path)
    anchors_exec = _read_json(anchors_exec_path)

    if not isinstance(core_exec, dict):
        emit(
            LEVEL_FAIL,
            "MERGE_STATE_INVALID",
            "core execution_result.json must be a JSON object",
            evidence={"path": str(core_exec_path), "got_type": type(core_exec).__name__},
        )
        raise SystemExit(EXIT_FAIL)

    if not isinstance(anchors_exec, dict):
        emit(
            LEVEL_FAIL,
            "MERGE_STATE_INVALID",
            "anchors execution_result.json must be a JSON object",
            evidence={"path": str(anchors_exec_path), "got_type": type(anchors_exec).__name__},
        )
        raise SystemExit(EXIT_FAIL)

    core_fp = core_exec.get("immutable_fingerprint")
    anchors_fp = anchors_exec.get("immutable_fingerprint")

    if not core_fp or not anchors_fp:
        raise MergeContractViolation(
            "SNAPSHOT_IMMUTABLE_VIOLATION",
            "immutable_fingerprint missing in CORE or ANCHORS execution_result",
            evidence={"core_fp": core_fp, "anchors_fp": anchors_fp},
        )


    if core_fp != anchors_fp:
        raise MergeContractViolation(
            "MERGE_FINGERPRINT_MISMATCH",
            "immutable_fingerprint mismatch between CORE and ANCHORS",
            evidence={"core_fp": core_fp, "anchors_fp": anchors_fp},
        )

    # --- DELIVERABLES PRESENCE VERIFIED ---
    # Files are validated for presence only.
    # Content is validated later by post-check via merge-state.

    # --- WRITE MERGE-STATE (authoritative) ---
    merge_state: Dict[str, Any] = {
        "merge_id": merge_id,
        "task_id": task_id,
        "hashprefix": hashprefix,
        "immutable_fingerprint": core_fp,
        "source_runs": {
            "anchors_snapshot_id": anchors_snapshot_id,
            "core_snapshot_id": core_snapshot_id,
        },
        "snapshot_canonical": {
            "id": core_snapshot_id,
            "path": str(Path("state/snapshots") / f"{core_snapshot_id}.canonical.json"),
        },
        # где лежат артефакты (post-check будет читать отсюда)
        "artifacts": {
            "core": {
                "semantic_enrichment_path": str(core_sem.resolve().as_posix()),
                "keywords_path": str(core_kw.resolve().as_posix()),
                "patient_questions_path": str(core_q.resolve().as_posix()),
            },
            "anchors": {
                "anchors_path": str(anchors_json.resolve().as_posix()),
            },
        },
        "merge_contract": {
            "llm_involvement": False,
            "operation": "pure_validation_plus_state_write",
            "authoritative_files": {
                "merge_state": str(merge_state_path.as_posix()),
                "merge_pointer": str(merge_ptr_path.as_posix()),
            },
        },
    }

    _write_json(merge_state_path, merge_state)

    merge_ptr_path.parent.mkdir(parents=True, exist_ok=True)
    merge_ptr_path.write_text(merge_id + "\n", encoding="utf-8")

    emit(
        LEVEL_PASS,
        "OK",
        "merge completed; merge-state and pointer created",
        evidence={
            "core_snapshot_id": core_snapshot_id,
            "anchors_snapshot_id": anchors_snapshot_id,
            "merge_id": merge_id,
            "merge_state": str(merge_state_path),
            "merge_ptr": str(merge_ptr_path),
        },
    )


def main() -> int:
    p = argparse.ArgumentParser(
        description="Deterministic MERGE of PASS_2A (CORE snapshot) + PASS_2B (ANCHORS snapshot). LLM must not be involved."
    )
    p.add_argument("--core-snapshot-id", required=True, help="Snapshot folder name under outputs/pass_2/ that contains /core/")
    p.add_argument("--anchors-snapshot-id", required=True, help="Snapshot folder name under outputs/pass_2/ that contains /anchors/")
    p.add_argument("--outputs-dir", default="outputs", help="Base outputs directory (default: outputs).")
    args = p.parse_args()

    merge(
        core_snapshot_id=args.core_snapshot_id,
        anchors_snapshot_id=args.anchors_snapshot_id,
        outputs_dir=Path(args.outputs_dir),
    )
    return EXIT_PASS

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MergeContractViolation as e:
        emit(LEVEL_BLOCKER, e.code, str(e), evidence=getattr(e, "evidence", None))
        raise SystemExit(EXIT_BLOCKER)
    except SystemExit:
        raise
    except Exception as e:
        emit(LEVEL_FAIL, "IO_ERROR", f"unexpected runtime error: {e}")
        raise SystemExit(EXIT_FAIL)
