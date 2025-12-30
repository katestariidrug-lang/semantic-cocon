import json, glob, os
from collections import Counter

snap_id = "demo_001__d4724601bde0"

candidates = [
    f"state/snapshots/{snap_id}.canonical.json",
    f"state/snapshots/{snap_id}.snapshot.json",
    f"state/snapshots/{snap_id}.json",
]

files = [p for p in candidates if os.path.exists(p)]
if not files:
    files = sorted(glob.glob(f"state/snapshots/{snap_id}*.json"))

if not files:
    raise SystemExit(f"Snapshot files not found for {snap_id}")

path = files[0]
print(f"[OK] Using: {path}")

with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

# --- node registry extraction (your schema) ---
ia = data.get("immutable_architecture", {})
registry = ia.get("node_registry")

if not isinstance(registry, (list, dict)):
    print("[FAIL] immutable_architecture.node_registry not found or wrong type.")
    print("Top keys:", list(data.keys()))
    print("immutable_architecture keys:", list(ia.keys()) if isinstance(ia, dict) else str(type(ia)))
    raise SystemExit(2)

reg_key = "immutable_architecture.node_registry"
nodes = list(registry.values()) if isinstance(registry, dict) else list(registry)

print(f"[OK] registry_key = {reg_key}")
print(f"node_registry_len = {len(nodes)}")

type_fields = ["node_type", "type", "kind", "role", "class", "archetype", "category", "tier"]

def classify(node):
    for f in type_fields:
        v = node.get(f)
        if isinstance(v, str):
            vv = v.upper()
            for t in ("HUB", "SPOKE", "SUPPORT"):
                if t in vv:
                    return t
    meta = node.get("meta") or node.get("metadata")
    if isinstance(meta, dict):
        for f in type_fields:
            v = meta.get(f)
            if isinstance(v, str):
                vv = v.upper()
                for t in ("HUB", "SPOKE", "SUPPORT"):
                    if t in vv:
                        return t
    return "UNKNOWN"

cnt = Counter(classify(n) for n in nodes)
print("distribution =", dict(cnt))

unknown = [n for n in nodes if classify(n) == "UNKNOWN"]
if unknown:
    print(f"UNKNOWN nodes: {len(unknown)}")
    print("Sample keys:", list(unknown[0].keys()))
