import json
import sys
import os

def die(code: int, msg: str):
    print(msg)
    sys.exit(code)

def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    # usage:
    # python scripts/gate_snapshot.py demo_001__d4724601bde0
    if len(sys.argv) < 2:
        die(1, "[USAGE] python scripts/gate_snapshot.py <snapshot_id>")

    snap_id = sys.argv[1]
    base = os.path.join("state", "snapshots")

    canonical = os.path.join(base, f"{snap_id}.canonical.json")
    if not os.path.exists(canonical):
        die(2, f"[GATE_FAIL] canonical snapshot not found: {canonical}")

    d = load_json(canonical)
    ia = d.get("immutable_architecture")
    if not isinstance(ia, dict):
        die(3, "[GATE_FAIL] immutable_architecture missing or not dict")

    reg = ia.get("node_registry")
    if not isinstance(reg, (dict, list)):
        die(4, f"[GATE_FAIL] node_registry missing or invalid type: {type(reg).__name__}")

    # node ids (dict: keys, list: node_id field)
    if isinstance(reg, dict):
        node_ids = list(reg.keys())
    else:
        node_ids = [n.get("node_id") for n in reg if isinstance(n, dict) and n.get("node_id")]

    if not node_ids:
        die(5, "[GATE_FAIL] node_registry has no node_ids")

    # owner_map in YOUR schema is a LIST of records
    om = ia.get("owner_map")
    if not isinstance(om, list):
        die(6, f"[GATE_FAIL] owner_map must be list, got: {type(om).__name__}")

    owned_ids = {x.get("node_id") for x in om if isinstance(x, dict) and x.get("node_id")}
    missing = [nid for nid in node_ids if nid and nid not in owned_ids]
    if missing:
        print(f"[GATE_FAIL] owner_map does not cover all nodes. missing={len(missing)}")
        print("missing_sample=", missing[:8])
        sys.exit(7)

    # hub_chain sanity
    hc = ia.get("hub_chain")
    if not isinstance(hc, list) or len(hc) < 1:
        die(8, f"[GATE_FAIL] hub_chain must be non-empty list, got: {type(hc).__name__}")

    # linking matrix sanity
    lm = ia.get("linking_matrix_skeleton")
    if not isinstance(lm, list) or len(lm) < 1:
        die(9, f"[GATE_FAIL] linking_matrix_skeleton must be non-empty list, got: {type(lm).__name__}")

    print("[GATE_OK] Snapshot is approvable by structural checks.")
    print("snapshot_id=", snap_id)
    print("node_registry_len=", len(node_ids))
    print("owner_map_len=", len(om))
    print("hub_chain_len=", len(hc))
    print("linking_matrix_skeleton_len=", len(lm))

if __name__ == "__main__":
    main()
