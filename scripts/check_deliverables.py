import json
import sys
import argparse
from pathlib import Path

p = argparse.ArgumentParser(description="Post-check deliverables by merge-state (authoritative).")
p.add_argument("merge_id", nargs="?", help="merge_id (positional)")
p.add_argument("--merge-id", dest="merge_id_flag", help="merge_id (optional flag alias)")
args = p.parse_args()

merge_id = args.merge_id_flag or args.merge_id
if not merge_id:
    print("[USAGE] python scripts/check_deliverables.py <merge_id>")
    raise SystemExit(1)

def load(p: Path):
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

# Authoritative source of truth after MERGE
merge_state_path = Path("state/merges") / f"{merge_id}.json"
if not merge_state_path.exists():
    print(f"[FAIL] missing merge-state: {merge_state_path}")
    raise SystemExit(1)

merge_state = load(merge_state_path)

# Snapshot canonical is addressed by merge_id (= run_id = <task_id>__<hashprefix>)
snap_path = Path("state/snapshots") / f"{merge_id}.canonical.json"
if not snap_path.exists():
    print(f"[FAIL] missing snapshot canonical for post-check: {snap_path}")
    raise SystemExit(1)

snap = load(snap_path)
reg = snap["immutable_architecture"]["node_registry"]

# Resolve artifact paths from merge-state (authoritative)
art = merge_state.get("artifacts") or {}
core_art = art.get("core") or {}
anch_art = art.get("anchors") or {}

core_sem_path = Path(core_art.get("semantic_enrichment_path", ""))
core_kw_path = Path(core_art.get("keywords_path", ""))
core_q_path = Path(core_art.get("patient_questions_path", ""))
anchors_path = Path(anch_art.get("anchors_path", ""))

missing_paths = [str(p) for p in [core_sem_path, core_kw_path, core_q_path, anchors_path] if not str(p)]
if missing_paths:
    print("[FAIL] merge-state missing artifacts paths:", missing_paths)
    raise SystemExit(1)

for pth, label in [
    (core_sem_path, "semantic_enrichment_path"),
    (core_kw_path, "keywords_path"),
    (core_q_path, "patient_questions_path"),
    (anchors_path, "anchors_path"),
]:
    if not pth.exists():
        print(f"[FAIL] missing artifact file ({label}): {pth}")
        raise SystemExit(1)

# run_root for optional artifacts (e.g., final_artifacts.json)
run_root = core_sem_path.parent.parent  # .../<run_id>/core/<file> -> .../<run_id>/

if isinstance(reg, dict):
    node_ids = list(reg.keys())
else:
    node_ids = [n.get("node_id") for n in reg if isinstance(n, dict) and n.get("node_id")]

print("expected_node_count =", len(node_ids))

def extract_ids(obj):
    ids = set()
    if isinstance(obj, dict):
        # if dict keyed by node_id
        for k, v in obj.items():
            if isinstance(k, str) and k.startswith("node_"):
                ids.add(k)
            if isinstance(v, dict) and isinstance(v.get("node_id"), str):
                ids.add(v["node_id"])
        # also check common fields
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

expected = set(node_ids)

files = [
    ("keywords.json", core_kw_path),
    ("patient_questions.json", core_q_path),
    ("semantic_enrichment.json", core_sem_path),
]

for fn, p in files:
    obj = load(p)
    got = extract_ids(obj)
    missing = sorted(list(expected - got))
    extra = sorted([x for x in got - expected])
    print("\nFILE:", fn)
    print("  path =", p)
    print("  got_node_ids =", len(got))
    print("  missing =", len(missing), (missing[:6] if missing else []))
    print("  extra =", len(extra), (extra[:6] if extra else []))
    if missing or extra:
        print("  [FAIL] per-node coverage mismatch (missing/extra node_id).")
        raise SystemExit(1)

# --- anchors.json: validate links use valid node_ids + length matches linking skeleton ---
anchors = load(anchors_path)
if not isinstance(anchors, list):
    print("\nFILE: anchors.json")
    print("  [FAIL] anchors.json must be a list, got:", type(anchors).__name__)
    raise SystemExit(1)
else:
    got_ids = set()
    bad_rows = 0
    for a in anchors:
        if not isinstance(a, dict):
            bad_rows += 1
            continue
        fr = a.get("from_node_id")
        to = a.get("to_node_id")
        if isinstance(fr, str): got_ids.add(fr)
        if isinstance(to, str): got_ids.add(to)
        if fr not in expected or to not in expected:
            bad_rows += 1
    print("\nFILE: anchors.json")
    print("  anchors_len =", len(anchors))
    print("  unique_node_ids_in_links =", len(got_ids))
    print("  bad_rows =", bad_rows)
    if bad_rows > 0:
        print("  [FAIL] anchors.json contains rows with invalid node_id(s) (not in snapshot node_registry).")
        raise SystemExit(1)


# --- final_artifacts.json: optional aggregate artifact ---
fa_path = run_root / "final_artifacts.json"
print("\nFILE: final_artifacts.json")
if not fa_path.exists():
    print("  [SKIP] missing (optional in current contract).")
else:
    fa = load(fa_path)
    if not isinstance(fa, dict):
        print("  [FAIL] must be dict, got:", type(fa).__name__)
        raise SystemExit(1)
    ok_key = "main_summary_table" in fa and isinstance(fa.get("main_summary_table"), str) and fa["main_summary_table"].strip()
    print("  has_main_summary_table =", bool(ok_key))
    if not ok_key:
        print("  [FAIL] final_artifacts.json missing non-empty main_summary_table.")
        raise SystemExit(1)
    print("  main_summary_table_chars =", len(fa["main_summary_table"]))

print("\n[PASS] deliverables OK for merge_id =", merge_id)
