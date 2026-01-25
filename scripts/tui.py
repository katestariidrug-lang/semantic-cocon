"""
Textual TUI thin-wrapper над CLI workflow.

TYPE: helper
ROLE: UI only. No lifecycle logic. No writes to state.

v0 (read-only): показывает факты по диску (state/ + outputs/), ничего не запускает.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Static


@dataclass(frozen=True)
class RepoFacts:
    repo_root: Path
    snapshots: list[str]
    latest_snapshot_id: str | None
    latest_snapshot_sha256: str | None
    latest_snapshot_approved: bool
    runs: list[str]
    latest_run_id: str | None
    latest_merge_id: str | None
    merge_state_exists: bool


def _find_repo_root(start: Path) -> Path:
    """
    Ищем корень репозитория по наличию README.md.
    Никаких догадок о CWD, никаких write-side-effects.
    """
    for p in [start, *start.parents]:
        if (p / "README.md").exists():
            return p
    # Фолбэк: текущая директория (в худшем случае UI покажет "не найдено")
    return start


def _safe_read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError:
        return None


def collect_facts() -> RepoFacts:
    here = Path(__file__).resolve()
    repo_root = _find_repo_root(here.parent)

    state_dir = repo_root / "state"
    outputs_dir = repo_root / "outputs"

    snapshots_dir = state_dir / "snapshots"
    approvals_dir = state_dir / "approvals"
    merges_dir = state_dir / "merges"
    by_run_dir = merges_dir / "by_run"

    snapshots = sorted([p.stem.replace(".snapshot", "") for p in snapshots_dir.glob("*.snapshot.json")])
    latest_snapshot_id = None
    latest_snapshot_sha256 = None
    latest_snapshot_approved = False

    # latest snapshot = по mtime файла *.snapshot.json (факт на диске)
    latest_snapshot_path = None
    for p in snapshots_dir.glob("*.snapshot.json"):
        if latest_snapshot_path is None or p.stat().st_mtime > latest_snapshot_path.stat().st_mtime:
            latest_snapshot_path = p

    if latest_snapshot_path is not None:
        # имя вида: <snapshot_id>.snapshot.json
        latest_snapshot_id = latest_snapshot_path.name.removesuffix(".snapshot.json")
        sha_path = snapshots_dir / f"{latest_snapshot_id}.sha256"
        sha_val = _safe_read_text(sha_path)
        if sha_val:
            latest_snapshot_sha256 = sha_val
            latest_snapshot_approved = (approvals_dir / f"{sha_val}.approved").exists()

    # run_id’ы = директории outputs/pass_2/<run_id> (факт на диске)
    runs = []
    pass2_dir = outputs_dir / "pass_2"
    if pass2_dir.exists():
        runs = sorted([p.name for p in pass2_dir.iterdir() if p.is_dir()])

    latest_run_id = None
    latest_run_path = None
    for p in (pass2_dir.iterdir() if pass2_dir.exists() else []):
        if p.is_dir() and (latest_run_path is None or p.stat().st_mtime > latest_run_path.stat().st_mtime):
            latest_run_path = p
    if latest_run_path is not None:
        latest_run_id = latest_run_path.name

    # merge_id: читаем pointer state/merges/by_run/<run_id>.merge_id, если есть
    latest_merge_id = None
    merge_state_exists = False
    if latest_run_id:
        merge_id_text = _safe_read_text(by_run_dir / f"{latest_run_id}.merge_id")
        if merge_id_text:
            latest_merge_id = merge_id_text
            merge_state_exists = (merges_dir / f"{latest_merge_id}.json").exists()

    return RepoFacts(
        repo_root=repo_root,
        snapshots=snapshots,
        latest_snapshot_id=latest_snapshot_id,
        latest_snapshot_sha256=latest_snapshot_sha256,
        latest_snapshot_approved=latest_snapshot_approved,
        runs=runs,
        latest_run_id=latest_run_id,
        latest_merge_id=latest_merge_id,
        merge_state_exists=merge_state_exists,
    )


def format_facts(f: RepoFacts) -> str:
    def yn(v: bool) -> str:
        return "yes" if v else "no"

    lines: list[str] = []
    lines.append("READ-ONLY DASHBOARD (v0)")
    lines.append("")
    lines.append(f"repo_root: {f.repo_root}")
    lines.append("")
    lines.append(f"state/snapshots: {len(f.snapshots)} file(s)")
    lines.append(f"latest_snapshot_id: {f.latest_snapshot_id or '—'}")
    lines.append(f"latest_snapshot_sha256: {f.latest_snapshot_sha256 or '—'}")
    lines.append(f"approved_for_latest_snapshot: {yn(f.latest_snapshot_approved) if f.latest_snapshot_id else '—'}")
    lines.append("")
    lines.append(f"outputs/pass_2 runs: {len(f.runs)} dir(s)")
    lines.append(f"latest_run_id: {f.latest_run_id or '—'}")
    lines.append("")
    lines.append(f"latest_merge_id (by_run pointer): {f.latest_merge_id or '—'}")
    lines.append(f"merge_state_exists: {yn(f.merge_state_exists) if f.latest_merge_id else '—'}")
    lines.append("")
    lines.append("Keys: [r] refresh  |  [q] quit")
    return "\n".join(lines)


class ReadOnlyDashboard(App):
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static("", id="facts")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_facts()

    def action_refresh(self) -> None:
        self.refresh_facts()

    def refresh_facts(self) -> None:
        facts = collect_facts()
        self.query_one("#facts", Static).update(format_facts(facts))


if __name__ == "__main__":
    ReadOnlyDashboard().run()
