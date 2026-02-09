#!/usr/bin/env python3
"""
scripts/ui.py — minimal read-only UI (helper)

ROLE:
- presentation-only
- no lifecycle logic
- no writes (state/, outputs/, anything)
- no subprocess / no invoking enforcing CLI

Shows observed facts from disk:
- inventory of state/snapshots (*.snapshot.json)
- inventory of outputs/pass_2/<run_id> directories
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Facts:
    repo_root: Path
    snapshots: list[str]
    runs: list[str]


def _find_repo_root(start: Path) -> Path:
    # Deterministic: find repo root by README.md presence
    for p in [start, *start.parents]:
        if (p / "README.md").exists():
            return p
    return start


def _list_snapshots(repo_root: Path) -> list[str]:
    snapshots_dir = repo_root / "state" / "snapshots"
    if not snapshots_dir.exists():
        return []
    # snapshot_id is filename stem without ".snapshot.json"
    out: list[str] = []
    for p in snapshots_dir.glob("*.snapshot.json"):
        stem = p.name.replace(".snapshot.json", "")
        out.append(stem)
    return sorted(out)


def _list_runs(repo_root: Path) -> list[str]:
    pass2_dir = repo_root / "outputs" / "pass_2"
    if not pass2_dir.exists():
        return []
    out: list[str] = []
    for p in pass2_dir.iterdir():
        if p.is_dir():
            out.append(p.name)
    return sorted(out)


def collect_facts() -> Facts:
    here = Path(__file__).resolve()
    repo_root = _find_repo_root(here.parent)
    return Facts(
        repo_root=repo_root,
        snapshots=_list_snapshots(repo_root),
        runs=_list_runs(repo_root),
    )


def render(f: Facts) -> str:
    lines: list[str] = []
    lines.append("READ-ONLY UI (helper)")
    lines.append("")
    lines.append(f"repo_root: {f.repo_root}")
    lines.append("")
    lines.append("OBSERVED FACTS (no inference; no decisions)")
    lines.append("")
    lines.append(f"state/snapshots (*.snapshot.json): {len(f.snapshots)}")
    for s in f.snapshots[:50]:
        lines.append(f"- {s}")
    if len(f.snapshots) > 50:
        lines.append(f"... ({len(f.snapshots) - 50} more)")
    lines.append("")
    lines.append(f"outputs/pass_2/<run_id> dirs: {len(f.runs)}")
    for r in f.runs[:50]:
        lines.append(f"- {r}")
    if len(f.runs) > 50:
        lines.append(f"... ({len(f.runs) - 50} more)")
    return "\n".join(lines)


def main() -> int:
    facts = collect_facts()
    print(render(facts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
