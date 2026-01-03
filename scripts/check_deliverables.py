import json
import sys
from pathlib import Path

if len(sys.argv) < 2:
    print("[USAGE] python scripts/check_deliverables.py <snapshot_id>")
    sys.exit(1)

snap_id = sys.argv[1]

snap_path = Path("state/snapshots") / f"{snap_id}.canonical.json"
out_dir   = Path("outputs/pass_2") / snap_id

def load(p: Path):
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

snap = load(snap_path)
reg = snap["immutable_architecture"]["node_registry"]
if isinstance(reg, dict):
    node_ids = list(reg.keys())
else:
    node_ids = [n.get("node_id") for n in reg if isinstance(n, dict) and n.get("node_id")]

print("expected_node_count =", len(node_ids))

files = [
    "keywords.json",
    "patient_questions.json",
    "semantic_enrichment.json",
]

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

for fn in files:
    p = out_dir / fn
    obj = load(p)
    got = extract_ids(obj)
    missing = sorted(list(expected - got))
    extra = sorted([x for x in got - expected])
    print("\nFILE:", fn)
    print("  got_node_ids =", len(got))
    print("  missing =", len(missing), (missing[:6] if missing else []))
    print("  extra =", len(extra), (extra[:6] if extra else []))
    if missing or extra:
        print("  [FAIL] per-node coverage mismatch (missing/extra node_id).")
        raise SystemExit(1)

# --- anchors.json: validate links use valid node_ids + length matches linking skeleton ---
anchors = load(out_dir / "anchors.json")
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


# --- final_artifacts.json: validate expected keys (aggregate artifact, not per-node) ---
fa = load(out_dir / "final_artifacts.json")
print("\nFILE: final_artifacts.json")
if not isinstance(fa, dict):
    print("  [FAIL] must be dict, got:", type(fa).__name__)
    raise SystemExit(1)
else:
    ok_key = "main_summary_table" in fa and isinstance(fa.get("main_summary_table"), str) and fa["main_summary_table"].strip()
    print("  has_main_summary_table =", bool(ok_key))
    if not ok_key:
        print("  [FAIL] final_artifacts.json missing non-empty main_summary_table.")
        raise SystemExit(1)
    print("  main_summary_table_chars =", len(fa["main_summary_table"]))
    