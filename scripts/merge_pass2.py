import argparse
import json
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]  # project-root/
STATE_DIR = ROOT / "state"


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def _require_dir(path: Path, name: str) -> None:
    if not path.exists() or not path.is_dir():
        raise SystemExit(f"[MERGE] FAIL: missing {name} dir: {path}")


def _require_file(path: Path, name: str) -> None:
    if not path.exists() or not path.is_file():
        raise SystemExit(f"[MERGE] FAIL: missing {name} file: {path}")


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
        raise SystemExit(
            f"[MERGE] FAIL: invalid core_snapshot_id format (expected <task_id>__<hashprefix>): {core_snapshot_id}"
        )
    if "__" not in anchors_snapshot_id:
        raise SystemExit(
            f"[MERGE] FAIL: invalid anchors_snapshot_id format (expected <task_id>__<hashprefix>): {anchors_snapshot_id}"
        )

    core_task_id, core_hashprefix = core_snapshot_id.split("__", 1)
    anch_task_id, anch_hashprefix = anchors_snapshot_id.split("__", 1)

    if (core_task_id, core_hashprefix) != (anch_task_id, anch_hashprefix):
        raise SystemExit(
            "[MERGE] FAIL: CORE and ANCHORS belong to different runs "
            f"(CORE={core_snapshot_id}, ANCHORS={anchors_snapshot_id})"
        )

    task_id = core_task_id
    hashprefix = core_hashprefix
    merge_id = f"{task_id}__{hashprefix}"

    merges_dir = STATE_DIR / "merges"
    merges_by_run_dir = merges_dir / "by_run"

    merge_state_path = merges_dir / f"{merge_id}.json"
    merge_ptr_path = merges_by_run_dir / f"{task_id}__{hashprefix}.merge_id"

    # FAIL-FAST: не перезаписываем merge-state (иначе теряется точка невозврата)
    if merge_state_path.exists():
        raise SystemExit(f"[MERGE] FAIL: merge-state already exists: {merge_state_path}")
    if merge_ptr_path.exists():
        raise SystemExit(f"[MERGE] FAIL: merge pointer already exists: {merge_ptr_path}")

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
    core_exec = _read_json(core_base / "core" / "execution_result.json")
    anchors_exec = _read_json(anchors_base / "anchors" / "execution_result.json")

    core_fp = core_exec.get("immutable_fingerprint")
    anchors_fp = anchors_exec.get("immutable_fingerprint")

    if not core_fp or not anchors_fp:
        raise SystemExit(
            "[MERGE] FAIL: immutable_fingerprint missing in CORE or ANCHORS execution_result"
        )

    if core_fp != anchors_fp:
        raise SystemExit(
            "[MERGE] FAIL: immutable_fingerprint mismatch "
            f"(CORE={core_fp}, ANCHORS={anchors_fp})"
        )

    # --- READ CORE / ANCHORS DELIVERABLES (для sanity, без переупаковки в outputs) ---
    semantic_enrichment = _read_json(core_sem)
    keywords = _read_json(core_kw)
    patient_questions = _read_json(core_q)
    anchors = _read_json(anchors_json)

    # --- WRITE MERGE-STATE (authoritative) ---
    merge_state: Dict[str, Any] = {
        "merge_id": merge_id,
        "task_id": task_id,
        "hashprefix": hashprefix,
        "immutable_fingerprint": core_fp,
        "source_runs": {
            "core_snapshot_id": core_snapshot_id,
            "anchors_snapshot_id": anchors_snapshot_id,
        },
        # где лежат артефакты (post-check будет читать отсюда)
        "artifacts": {
            "core": {
                "semantic_enrichment_path": str(core_sem.as_posix()),
                "keywords_path": str(core_kw.as_posix()),
                "patient_questions_path": str(core_q.as_posix()),
            },
            "anchors": {
                "anchors_path": str(anchors_json.as_posix()),
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

    print("[MERGE] PASS")
    print(f"[MERGE] core_snapshot_id = {core_snapshot_id}")
    print(f"[MERGE] anchors_snapshot_id = {anchors_snapshot_id}")
    print(f"[MERGE] merge_id = {merge_id}")
    print(f"[MERGE] merge_state = {merge_state_path}")
    print(f"[MERGE] merge_ptr = {merge_ptr_path}")

def main() -> None:
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

if __name__ == "__main__":
    main()
