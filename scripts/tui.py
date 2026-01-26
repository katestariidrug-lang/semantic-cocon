"""
Textual TUI (read-only dashboard).

TYPE: helper
ROLE: UI only. No lifecycle logic. No writes. No subprocess/CLI запусков.

Показывает факты по диску (state/ + outputs/), ничего не запускает.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Static, Select


@dataclass(frozen=True)
class RepoFacts:
    repo_root: Path

    # Инвентарь (факт на диске)
    snapshots: list[str]
    runs: list[str]

    # "latest" (факт на диске)
    latest_snapshot_id: str | None
    latest_run_id: str | None

    # Выбор пользователя (UI state only) + факты по выбранному
    selected_snapshot_id: str | None
    selected_snapshot_sha256: str | None
    selected_snapshot_approved: bool

    selected_run_id: str | None
    selected_merge_id: str | None
    selected_merge_state_exists: bool


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


def collect_facts(selected_snapshot_id: str | None = None, selected_run_id: str | None = None) -> RepoFacts:
    here = Path(__file__).resolve()
    repo_root = _find_repo_root(here.parent)

    state_dir = repo_root / "state"
    outputs_dir = repo_root / "outputs"

    snapshots_dir = state_dir / "snapshots"
    approvals_dir = state_dir / "approvals"
    merges_dir = state_dir / "merges"
    by_run_dir = merges_dir / "by_run"

    # инвентарь snapshot_id (факт на диске)
    snapshots = sorted([p.stem.replace(".snapshot", "") for p in snapshots_dir.glob("*.snapshot.json")])

    # latest snapshot = по mtime файла *.snapshot.json (факт на диске)
    latest_snapshot_id = None
    latest_snapshot_path = None
    for p in snapshots_dir.glob("*.snapshot.json"):
        if latest_snapshot_path is None or p.stat().st_mtime > latest_snapshot_path.stat().st_mtime:
            latest_snapshot_path = p
    if latest_snapshot_path is not None:
        latest_snapshot_id = latest_snapshot_path.name.removesuffix(".snapshot.json")

    # инвентарь run_id (факт на диске)
    runs: list[str] = []
    pass2_dir = outputs_dir / "pass_2"
    if pass2_dir.exists():
        runs = sorted([p.name for p in pass2_dir.iterdir() if p.is_dir()])

    # latest run = по mtime директории outputs/pass_2/<run_id> (факт на диске)
    latest_run_id = None
    latest_run_path = None
    for p in (pass2_dir.iterdir() if pass2_dir.exists() else []):
        if p.is_dir() and (latest_run_path is None or p.stat().st_mtime > latest_run_path.stat().st_mtime):
            latest_run_path = p
    if latest_run_path is not None:
        latest_run_id = latest_run_path.name

    # выбор пользователя: если не задан, показываем latest (UI state only)
    eff_snapshot_id = selected_snapshot_id or latest_snapshot_id
    eff_run_id = selected_run_id or latest_run_id

    # факты по выбранному snapshot
    selected_snapshot_sha256 = None
    selected_snapshot_approved = False
    if eff_snapshot_id:
        sha_val = _safe_read_text(snapshots_dir / f"{eff_snapshot_id}.sha256")
        if sha_val:
            selected_snapshot_sha256 = sha_val
            selected_snapshot_approved = (approvals_dir / f"{sha_val}.approved").exists()

    # факты по выбранному run
    selected_merge_id = None
    selected_merge_state_exists = False
    if eff_run_id:
        merge_id_text = _safe_read_text(by_run_dir / f"{eff_run_id}.merge_id")
        if merge_id_text:
            selected_merge_id = merge_id_text
            selected_merge_state_exists = (merges_dir / f"{selected_merge_id}.json").exists()

    return RepoFacts(
        repo_root=repo_root,
        snapshots=snapshots,
        runs=runs,
        latest_snapshot_id=latest_snapshot_id,
        latest_run_id=latest_run_id,
        selected_snapshot_id=eff_snapshot_id,
        selected_snapshot_sha256=selected_snapshot_sha256,
        selected_snapshot_approved=selected_snapshot_approved,
        selected_run_id=eff_run_id,
        selected_merge_id=selected_merge_id,
        selected_merge_state_exists=selected_merge_state_exists,
    )


def format_facts(f: RepoFacts) -> str:
    def yn(v: bool) -> str:
        return "yes" if v else "no"

    lines: list[str] = []
    lines.append("READ-ONLY DASHBOARD (v1)")
    lines.append("")
    lines.append(f"repo_root: {f.repo_root}")
    lines.append("")

    lines.append(f"state/snapshots: {len(f.snapshots)} file(s)")
    lines.append(f"latest_snapshot_id: {f.latest_snapshot_id or '—'}")
    lines.append(f"selected_snapshot_id: {f.selected_snapshot_id or '—'}")
    lines.append(f"selected_snapshot_sha256: {f.selected_snapshot_sha256 or '—'}")
    lines.append(f"selected_snapshot_approved: {yn(f.selected_snapshot_approved) if f.selected_snapshot_id else '—'}")
    lines.append("")

    lines.append(f"outputs/pass_2 runs: {len(f.runs)} dir(s)")
    lines.append(f"latest_run_id: {f.latest_run_id or '—'}")
    lines.append(f"selected_run_id: {f.selected_run_id or '—'}")
    lines.append("")

    lines.append(f"selected_merge_id (by_run pointer): {f.selected_merge_id or '—'}")
    lines.append(f"selected_merge_state_exists: {yn(f.selected_merge_state_exists) if f.selected_merge_id else '—'}")
    lines.append("")
    lines.append("Keys: [r] refresh  |  [q] quit")
    return "\n".join(lines)


class ReadOnlyDashboard(App):
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def on_select_changed(self, _event: Select.Changed) -> None:
        # UI-only: на любое изменение выбора перерисовываем факты.
        # Во время reload_options подавляем события, чтобы не словить рекурсию.
        if getattr(self, "_reloading_options", False):
            return
        self.refresh_facts(reload_options=False)

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static("snapshot:", id="lbl_snapshot")
            yield Select([], id="sel_snapshot", prompt="select snapshot")
            yield Static("run:", id="lbl_run")
            yield Select([], id="sel_run", prompt="select run")
            yield Static("", id="facts")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_facts(reload_options=True)

    def action_refresh(self) -> None:
        self.refresh_facts(reload_options=True)

    def _selected_ids(self) -> tuple[str | None, str | None]:
        sel_snapshot = self.query_one("#sel_snapshot", Select)
        sel_run = self.query_one("#sel_run", Select)
        snap = sel_snapshot.value if isinstance(sel_snapshot.value, str) else None
        run = sel_run.value if isinstance(sel_run.value, str) else None
        return snap, run

    def refresh_facts(self, reload_options: bool = False) -> None:
        snap_id, run_id = self._selected_ids()
        facts = collect_facts(selected_snapshot_id=snap_id, selected_run_id=run_id)

        if reload_options:
            self._reloading_options = True
            try:
                sel_snapshot = self.query_one("#sel_snapshot", Select)
                sel_run = self.query_one("#sel_run", Select)

                snap_opts = [(s, s) for s in facts.snapshots]
                run_opts = [(r, r) for r in facts.runs]

                sel_snapshot.set_options(snap_opts)
                sel_run.set_options(run_opts)

                # если значение не выбрано/устарело, выставляем latest (UI state only)
                if facts.selected_snapshot_id and facts.selected_snapshot_id in facts.snapshots:
                    sel_snapshot.value = facts.selected_snapshot_id
                else:
                    sel_snapshot.value = None

                if facts.selected_run_id and facts.selected_run_id in facts.runs:
                    sel_run.value = facts.selected_run_id
                else:
                    sel_run.value = None
            finally:
                self._reloading_options = False

        self.query_one("#facts", Static).update(format_facts(facts))


if __name__ == "__main__":
    ReadOnlyDashboard().run()