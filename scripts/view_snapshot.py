#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import sys
from pathlib import Path


def _extract_task_id(snapshot: dict):
    # Most likely: snapshot["task_id"], but keep it robust.
    if isinstance(snapshot, dict):
        if "task_id" in snapshot:
            return snapshot.get("task_id")
        task = snapshot.get("task")
        if isinstance(task, dict):
            return task.get("task_id")
    return None


def _extract_immutable_architecture(snapshot: dict):
    if isinstance(snapshot, dict):
        imm = snapshot.get("immutable_architecture")
        if isinstance(imm, dict):
            return imm
    return None


def _extract_prompt_fingerprints(snapshot: dict, imm_arch: dict | None):
    # The canonical location (as produced by orchestrator DECIDE):
    # snapshot["meta"]["prompts_fingerprint"]
    candidates = []

    if isinstance(snapshot, dict):
        meta = snapshot.get("meta")
        if isinstance(meta, dict):
            candidates.append(meta.get("prompts_fingerprint"))

        # Backward/alternative locations (keep for robustness)
        candidates.extend([
            snapshot.get("prompt_fingerprints"),
            snapshot.get("prompts_fingerprints"),
        ])

    if isinstance(imm_arch, dict):
        candidates.extend([
            imm_arch.get("prompt_fingerprints"),
            imm_arch.get("prompts_fingerprints"),
            imm_arch.get("prompts_fingerprint_map"),
        ])

    for c in candidates:
        if isinstance(c, dict) and c:
            return c

    # Last resort: pick any fingerprint-like keys from immutable_architecture
    if isinstance(imm_arch, dict):
        fp_like = {k: v for k, v in imm_arch.items() if "fingerprint" in str(k).lower()}
        if fp_like:
            return fp_like

    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="view_snapshot",
        description="Read-only diagnostic snapshot view (canonical). Plain text output; non-enforcing.",
    )
    parser.add_argument("snapshot_id", help="Snapshot id (without extensions)")
    args = parser.parse_args()

    snapshot_id = args.snapshot_id.strip()
    if not snapshot_id:
        print("ERROR: snapshot_id is empty", file=sys.stderr)
        return 1

    path = Path("state") / "snapshots" / f"{snapshot_id}.canonical.json"
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 1

    try:
        raw = path.read_text(encoding="utf-8")
        snapshot = json.loads(raw)
    except UnicodeDecodeError as e:
        print(f"ERROR: decode error: {path}: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON: {path}: {e}", file=sys.stderr)
        return 1

    imm_arch = _extract_immutable_architecture(snapshot)
    prompt_fps = _extract_prompt_fingerprints(snapshot, imm_arch)
    task_id = _extract_task_id(snapshot)

    # Plain-text projection of structure (no PASS/FAIL/BLOCKER; no enforcement)
    print(f"snapshot_id: {snapshot_id}")
    print(f"path: {path}")
    print(f"task_id: {task_id}")

    if isinstance(snapshot, dict):
        print(f"snapshot_top_level_keys: {', '.join(sorted(map(str, snapshot.keys())))}")
    else:
        print("snapshot_top_level_keys: <non-dict>")

    if isinstance(imm_arch, dict):
        print(f"immutable_architecture_keys: {', '.join(sorted(map(str, imm_arch.keys())))}")
    else:
        print("immutable_architecture_keys: <missing>")

    if isinstance(prompt_fps, dict) and prompt_fps:
        print("prompt_fingerprints:")
        for k in sorted(prompt_fps.keys(), key=lambda x: str(x)):
            v = prompt_fps.get(k)
            print(f"  - {k}: {v}")
    else:
        print("prompt_fingerprints: <missing>")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
