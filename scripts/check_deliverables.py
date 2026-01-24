#!/usr/bin/env python3
import json
import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# -------------------------
# Unified post-check contract
# -------------------------
EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_BLOCKER = 2

LEVEL_PASS = "PASS"
LEVEL_FAIL = "FAIL"
LEVEL_BLOCKER = "BLOCKER"

ERROR_CODES = {
    "OK",
    "DELIVERABLES_CHECK_FAILED",
    "NODE_COVERAGE_INCOMPLETE",
    "ANCHORS_INVALID",
    "IO_ERROR",
    "LIFECYCLE_VIOLATION",
    "MERGE_STATE_INVALID",
    "SNAPSHOT_INVALID",
    "FINGERPRINT_MISMATCH",
}


@dataclass
class Finding:
    level: str
    code: str
    message: str
    evidence: Optional[dict] = None

    def line(self) -> str:
        return f"[{self.level}] {self.code}: {self.message}"


class Reporter:
    def __init__(self) -> None:
        self.findings: List[Finding] = []

    def pass_(self, code: str, message: str, evidence: Optional[dict] = None) -> None:
        self._add(LEVEL_PASS, code, message, evidence)

    def fail(self, code: str, message: str, evidence: Optional[dict] = None) -> None:
        self._add(LEVEL_FAIL, code, message, evidence)

    def blocker(self, code: str, message: str, evidence: Optional[dict] = None) -> None:
        self._add(LEVEL_BLOCKER, code, message, evidence)

    def _add(self, level: str, code: str, message: str, evidence: Optional[dict]) -> None:
        if code not in ERROR_CODES:
            # If someone uses a non-canonical code, that's a contract breach.
            self.findings.append(Finding(
                level=LEVEL_BLOCKER,
                code="LIFECYCLE_VIOLATION",
                message=f"Unknown error code used: {code}",
                evidence={"bad_code": code},
            ))
            return
        self.findings.append(Finding(level=level, code=code, message=message, evidence=evidence))

    def exit_code(self) -> int:
        if any(f.level == LEVEL_BLOCKER for f in self.findings):
            return EXIT_BLOCKER
        if any(f.level == LEVEL_FAIL for f in self.findings):
            return EXIT_FAIL
        return EXIT_PASS

    def emit(self) -> None:
        for f in self.findings:
            print(f.line())
            if f.evidence is not None:
                print(json.dumps(f.evidence, ensure_ascii=False, sort_keys=True))


ROOT = Path(__file__).resolve().parents[1]  # project-root/
STATE_DIR = ROOT / "state"

README_PATH = ROOT / "README.md"
README_FP_PATH = STATE_DIR / "architecture" / "README.sha256"


def enforce_readme_fingerprint_or_blocker(r: "Reporter") -> bool:
    """
    Drift guard for README.md (architectural truth).
    mismatch or missing fingerprint file => BLOCKER + FINGERPRINT_MISMATCH
    """
    try:
        expected = README_FP_PATH.read_text(encoding="utf-8").strip().lower()
    except Exception as e:
        r.blocker(
            "FINGERPRINT_MISMATCH",
            f"README fingerprint file missing/unreadable: {README_FP_PATH}",
            evidence={"error": str(e), "path": str(README_FP_PATH)},
        )
        return False

    if not expected:
        r.blocker(
            "FINGERPRINT_MISMATCH",
            f"README fingerprint file is empty: {README_FP_PATH}",
            evidence={"path": str(README_FP_PATH)},
        )
        return False

    try:
        data = README_PATH.read_bytes()
    except Exception as e:
        r.blocker(
            "FINGERPRINT_MISMATCH",
            f"README missing/unreadable: {README_PATH}",
            evidence={"error": str(e), "path": str(README_PATH)},
        )
        return False

    actual = hashlib.sha256(data).hexdigest().lower()

    if actual != expected:

        r.blocker(
            "FINGERPRINT_MISMATCH",
            "README.md fingerprint mismatch",
            evidence={"expected": expected, "actual": actual},
        )
        return False

    return True


def load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, "file not found"
    except json.JSONDecodeError as e:
        return None, f"invalid json: {e}"
    except OSError as e:
        return None, f"io error: {e}"


def extract_ids(obj: Any) -> Set[str]:
    ids: Set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.startswith("node_"):
                ids.add(k)
            if isinstance(v, dict) and isinstance(v.get("node_id"), str):
                ids.add(v["node_id"])
        for key in ("nodes", "items", "artifacts", "data"):
            v = obj.get(key)
            if isinstance(v, list):
                for it in v:
                    if isinstance(it, dict) and isinstance(it.get("node_id"), str):
                        ids.add(it["node_id"])
    elif isinstance(obj, list):
        for it in obj:
            if isinstance(it, dict) and isinstance(it.get("node_id"), str):
                ids.add(it["node_id"])
    return ids


def main() -> int:
    r = Reporter()

    if not enforce_readme_fingerprint_or_blocker(r):
        r.emit()
        return r.exit_code()

    p = argparse.ArgumentParser(description="Post-check deliverables by merge-state (authoritative).")
    p.add_argument("merge_id", nargs="?", help="merge_id (positional)")
    p.add_argument("--merge-id", dest="merge_id_flag", help="merge_id (optional flag alias)")
    args = p.parse_args()

    merge_id = (args.merge_id_flag or args.merge_id or "").strip()
    if not merge_id:
        r.blocker(
            "LIFECYCLE_VIOLATION",
            "Usage: python scripts/check_deliverables.py <merge_id> (post-check runs only by merge_id)",
            evidence={"argv": __import__("sys").argv},
        )
        r.emit()
        return r.exit_code()

    # Authoritative source of truth after MERGE
    merge_state_path = Path("state/merges") / f"{merge_id}.json"
    merge_state_raw, err = load_json(merge_state_path)
    if merge_state_raw is None:
        r.blocker(
            "MERGE_STATE_INVALID",
            "missing or unreadable merge-state; post-check allowed only after MERGE",
            evidence={"merge_id": merge_id, "path": str(merge_state_path), "error": err},
        )
        r.blocker(
            "LIFECYCLE_VIOLATION",
            "post-check cannot run without merge-state (MERGE is terminal state required before post-check)",
            evidence={"merge_id": merge_id},
        )
        r.emit()
        return r.exit_code()

    if not isinstance(merge_state_raw, dict):
        r.blocker(
            "MERGE_STATE_INVALID",
            "merge-state must be a JSON object",
            evidence={"merge_id": merge_id, "path": str(merge_state_path), "got_type": type(merge_state_raw).__name__},
        )
        r.emit()
        return r.exit_code()

    merge_state: Dict[str, Any] = merge_state_raw

    # Snapshot canonical is resolved ONLY via merge-state (authoritative after MERGE)
    sc = merge_state.get("snapshot_canonical")
    if not isinstance(sc, dict):
        r.blocker(
            "MERGE_STATE_INVALID",
            "merge-state missing snapshot_canonical object",
            evidence={"merge_id": merge_id, "path": str(merge_state_path)},
        )
        r.emit()
        return r.exit_code()

    sc_path = (sc.get("path") or "").strip()
    if not sc_path:
        r.blocker(
            "MERGE_STATE_INVALID",
            "merge-state snapshot_canonical.path is missing/empty",
            evidence={"merge_id": merge_id, "path": str(merge_state_path), "snapshot_canonical": sc},
        )
        r.emit()
        return r.exit_code()

    snap_path = Path(sc_path)
    snap_raw, err = load_json(snap_path)

    if snap_raw is None:
        r.blocker(
            "SNAPSHOT_INVALID",
            "missing snapshot canonical for post-check",
            evidence={"merge_id": merge_id, "path": str(snap_path), "error": err},
        )
        r.emit()
        return r.exit_code()

    if not isinstance(snap_raw, dict):
        r.blocker(
            "MERGE_STATE_INVALID",
            "snapshot canonical must be a JSON object",
            evidence={"merge_id": merge_id, "path": str(snap_path), "got_type": type(snap_raw).__name__},
        )
        r.emit()
        return r.exit_code()

    snap: Dict[str, Any] = snap_raw
    try:
        reg = snap["immutable_architecture"]["node_registry"]
    except Exception:
        r.blocker(
            "MERGE_STATE_INVALID",
            "snapshot canonical missing immutable_architecture.node_registry",
            evidence={"merge_id": merge_id, "path": str(snap_path)},
        )
        r.emit()
        return r.exit_code()

    if isinstance(reg, dict):
        node_ids = list(reg.keys())
    else:
        node_ids = [n.get("node_id") for n in reg if isinstance(n, dict) and n.get("node_id")]

    expected = set(node_ids)

    # Resolve artifact paths from merge-state (authoritative)
    art = merge_state.get("artifacts") or {}
    core_art = (art.get("core") or {}) if isinstance(art, dict) else {}
    anch_art = (art.get("anchors") or {}) if isinstance(art, dict) else {}

    core_sem_s = (core_art.get("semantic_enrichment_path") or "").strip()
    core_kw_s = (core_art.get("keywords_path") or "").strip()
    core_q_s = (core_art.get("patient_questions_path") or "").strip()
    anchors_s = (anch_art.get("anchors_path") or "").strip()

    if not all([core_sem_s, core_kw_s, core_q_s, anchors_s]):
        r.blocker(
            "MERGE_STATE_INVALID",
            "merge-state missing required artifacts paths",
            evidence={
                "merge_id": merge_id,
                "semantic_enrichment_path": core_sem_s,
                "keywords_path": core_kw_s,
                "patient_questions_path": core_q_s,
                "anchors_path": anchors_s,
            },
        )
        r.emit()
        return r.exit_code()

    core_sem_path = Path(core_sem_s)
    core_kw_path = Path(core_kw_s)
    core_q_path = Path(core_q_s)
    anchors_path = Path(anchors_s)

    # Presence checks
    missing_files: List[str] = []
    for pth, label in [
        (core_sem_path, "semantic_enrichment_path"),
        (core_kw_path, "keywords_path"),
        (core_q_path, "patient_questions_path"),
        (anchors_path, "anchors_path"),
    ]:
        if not pth.exists():
            missing_files.append(f"{label}={pth}")

    if missing_files:
        r.fail(
            "DELIVERABLES_CHECK_FAILED",
            "one or more artifact files are missing",
            evidence={"merge_id": merge_id, "missing": missing_files},
        )
        r.emit()
        return r.exit_code()

    # run_root for optional artifacts
    run_root = core_sem_path.parent.parent  # .../<run_id>/core/<file> -> .../<run_id>/

    # Per-node coverage checks
    files = [
        ("keywords.json", core_kw_path),
        ("patient_questions.json", core_q_path),
        ("semantic_enrichment.json", core_sem_path),
    ]

    for fn, path in files:
        obj, err = load_json(path)
        if obj is None:
            r.fail(
                "DELIVERABLES_CHECK_FAILED",
                f"invalid JSON deliverable: {fn}",
                evidence={"path": str(path), "error": err},
            )
            r.emit()
            return r.exit_code()

        got = extract_ids(obj)
        missing = sorted(list(expected - got))
        extra = sorted(list(got - expected))
        if missing or extra:
            r.fail(
                "NODE_COVERAGE_INCOMPLETE",
                f"per-node coverage mismatch in {fn} (missing/extra node_id)",
                evidence={
                    "path": str(path),
                    "missing_count": len(missing),
                    "extra_count": len(extra),
                    "missing_sample": missing[:10],
                    "extra_sample": extra[:10],
                },
            )
            r.emit()
            return r.exit_code()

    # anchors.json validation
    anchors_obj, err = load_json(anchors_path)
    if anchors_obj is None:
        r.fail(
            "DELIVERABLES_CHECK_FAILED",
            "invalid JSON deliverable: anchors.json",
            evidence={"path": str(anchors_path), "error": err},
        )
        r.emit()
        return r.exit_code()

    if not isinstance(anchors_obj, list):
        r.fail(
            "ANCHORS_INVALID",
            "anchors.json must be a list",
            evidence={"path": str(anchors_path), "got_type": type(anchors_obj).__name__},
        )
        r.emit()
        return r.exit_code()

    bad_rows = 0
    for a in anchors_obj:
        if not isinstance(a, dict):
            bad_rows += 1
            continue
        fr = a.get("from_node_id")
        to = a.get("to_node_id")
        if fr not in expected or to not in expected:
            bad_rows += 1

    if bad_rows > 0:
        r.fail(
            "ANCHORS_INVALID",
            "anchors.json contains rows with invalid node_id(s) (not in snapshot node_registry)",
            evidence={"path": str(anchors_path), "bad_rows": bad_rows, "anchors_len": len(anchors_obj)},
        )
        r.emit()
        return r.exit_code()

    # final_artifacts.json: optional
    fa_path = run_root / "final_artifacts.json"
    if fa_path.exists():
        fa_obj, err = load_json(fa_path)
        if fa_obj is None:
            r.fail(
                "DELIVERABLES_CHECK_FAILED",
                "invalid JSON deliverable: final_artifacts.json",
                evidence={"path": str(fa_path), "error": err},
            )
            r.emit()
            return r.exit_code()

        if not isinstance(fa_obj, dict):
            r.fail(
                "DELIVERABLES_CHECK_FAILED",
                "final_artifacts.json must be a JSON object",
                evidence={"path": str(fa_path), "got_type": type(fa_obj).__name__},
            )
            r.emit()
            return r.exit_code()

        ok_key = isinstance(fa_obj.get("main_summary_table"), str) and fa_obj["main_summary_table"].strip()
        if not ok_key:
            r.fail(
                "DELIVERABLES_CHECK_FAILED",
                "final_artifacts.json missing non-empty main_summary_table",
                evidence={"path": str(fa_path)},
            )
            r.emit()
            return r.exit_code()

    r.pass_("OK", f"deliverables OK for merge_id={merge_id}")
    r.emit()
    return r.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
