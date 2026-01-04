import argparse
import json
from pathlib import Path
from typing import Any, Dict


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


def merge(core_snapshot_id: str, anchors_snapshot_id: str, merge_id: str, outputs_dir: Path) -> None:
    pass2_dir = outputs_dir / "pass_2"

    core_base = pass2_dir / core_snapshot_id
    anchors_base = pass2_dir / anchors_snapshot_id
    out_base = pass2_dir / merge_id

    _require_dir(pass2_dir, "outputs/pass_2")
    _require_dir(core_base, "CORE snapshot")
    _require_dir(anchors_base, "ANCHORS snapshot")

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

    # --- READ CORE / ANCHORS DELIVERABLES ---
    semantic_enrichment = _read_json(core_sem)
    keywords = _read_json(core_kw)
    patient_questions = _read_json(core_q)
    anchors = _read_json(anchors_json)
    
    # Materialize in out_base root (deterministic)
    _write_json(out_base / "semantic_enrichment.json", semantic_enrichment)
    _write_json(out_base / "keywords.json", keywords)
    _write_json(out_base / "patient_questions.json", patient_questions)
    _write_json(out_base / "anchors.json", anchors)

    execution_result: Dict[str, Any] = {
        "merge_id": merge_id,
        "immutable_fingerprint": core_fp,
        "source_snapshots": {
            "core_snapshot_id": core_snapshot_id,
            "anchors_snapshot_id": anchors_snapshot_id,
        },
        "stages": {
            "core": {
                "semantic_enrichment": semantic_enrichment,
                "keywords": keywords,
                "patient_questions": patient_questions,
            },
            "anchors": {
                "anchors": anchors
            },
        },
        "merge_contract": {
            "llm_involvement": False,
            "operation": "pure_copy_plus_structural_wrap",
            "out_dir": str(out_base.as_posix()),
        },
    }

    _write_json(out_base / "execution_result.json", execution_result)

    print("[MERGE] PASS")
    print(f"[MERGE] core_snapshot_id = {core_snapshot_id}")
    print(f"[MERGE] anchors_snapshot_id = {anchors_snapshot_id}")
    print(f"[MERGE] merge_id = {merge_id}")
    print(f"[MERGE] out = {out_base / 'execution_result.json'}")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Deterministic MERGE of PASS_2A (CORE snapshot) + PASS_2B (ANCHORS snapshot). LLM must not be involved."
    )
    p.add_argument("--core-snapshot-id", required=True, help="Snapshot folder name under outputs/pass_2/ that contains /core/")
    p.add_argument("--anchors-snapshot-id", required=True, help="Snapshot folder name under outputs/pass_2/ that contains /anchors/")
    p.add_argument("--merge-id", required=True, help="Output folder name under outputs/pass_2/ for merged result (must be new/unique)")
    p.add_argument("--outputs-dir", default="outputs", help="Base outputs directory (default: outputs).")
    args = p.parse_args()

    merge(
        core_snapshot_id=args.core_snapshot_id,
        anchors_snapshot_id=args.anchors_snapshot_id,
        merge_id=args.merge_id,
        outputs_dir=Path(args.outputs_dir),
    )


if __name__ == "__main__":
    main()
