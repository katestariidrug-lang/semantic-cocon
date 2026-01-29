"""
Textual TUI (read-only dashboard).

TYPE: helper
ROLE: UI only. No lifecycle logic. No writes. No subprocess/CLI запусков.

Показывает факты по диску (state/ + outputs/), ничего не запускает.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import sys

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Static, Select, TextArea


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

    # snapshot доказательства для S1 (FSM)
    selected_snapshot_json_exists: bool
    selected_snapshot_canonical_exists: bool
    selected_snapshot_sha_file_exists: bool
    selected_snapshot_ready: bool  # json + canonical + sha256

    selected_snapshot_sha256: str | None
    selected_snapshot_approved: bool  # approvals/<sha>.approved

    selected_run_id: str | None
    selected_run_exists: bool

    # run доказательства для S3/S4
    selected_run_core_exists: bool
    selected_run_anchors_exists: bool

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


def _list_files_recursive(root: Path) -> list[str]:
    """
    Read-only: список файлов внутри root (рекурсивно).
    Возвращает относительные POSIX-пути (для стабильного отображения).
    """
    if not root.exists() or not root.is_dir():
        return []
    out: list[str] = []
    for p in root.rglob("*"):
        if p.is_file():
            out.append(p.relative_to(root).as_posix())
    return sorted(out)


def _safe_read_raw_preview(path: Path) -> str:
    """
    Read-only: безопасный raw preview.
    - utf-8 текст показываем как есть
    - бинарник/нечитаемо -> заглушка
    """
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return "(unavailable)"
    except OSError:
        return "(unavailable)"

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return "(binary file; raw preview disabled)"


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

    # Minimal TUI v0: no "latest" heuristics
    latest_snapshot_id = None

    # инвентарь run_id (факт на диске)
    runs: list[str] = []
    pass2_dir = outputs_dir / "pass_2"
    if pass2_dir.exists():
        runs = sorted([p.name for p in pass2_dir.iterdir() if p.is_dir()])

    # Minimal TUI v0: no "latest" heuristics
    latest_run_id = None

    # Minimal TUI v0: user selection only (no defaults)
    eff_snapshot_id = selected_snapshot_id
    eff_run_id = selected_run_id

    # факты по выбранному snapshot (FSM S1/S2 доказательства)
    selected_snapshot_json_exists = False
    selected_snapshot_canonical_exists = False
    selected_snapshot_sha_file_exists = False
    selected_snapshot_ready = False

    selected_snapshot_sha256 = None
    selected_snapshot_approved = False

    if eff_snapshot_id:
        snap_json = snapshots_dir / f"{eff_snapshot_id}.snapshot.json"
        snap_canonical = snapshots_dir / f"{eff_snapshot_id}.canonical.json"
        snap_sha = snapshots_dir / f"{eff_snapshot_id}.sha256"

        selected_snapshot_json_exists = snap_json.exists()
        selected_snapshot_canonical_exists = snap_canonical.exists()
        selected_snapshot_sha_file_exists = snap_sha.exists()
        selected_snapshot_ready = (
            selected_snapshot_json_exists
            and selected_snapshot_canonical_exists
            and selected_snapshot_sha_file_exists
        )

        sha_val = _safe_read_text(snap_sha)
        if sha_val:
            selected_snapshot_sha256 = sha_val
            selected_snapshot_approved = (approvals_dir / f"{sha_val}.approved").exists()

    # факты по выбранному run (FSM S3/S4 доказательства)
    selected_run_exists = False
    selected_run_core_exists = False
    selected_run_anchors_exists = False

    selected_merge_id = None
    selected_merge_state_exists = False

    if eff_run_id:
        run_root = pass2_dir / eff_run_id
        selected_run_exists = run_root.exists()

        core_dir = run_root / "core"
        anchors_dir = run_root / "anchors"
        selected_run_core_exists = core_dir.exists() and core_dir.is_dir()
        selected_run_anchors_exists = anchors_dir.exists() and anchors_dir.is_dir()

        # immutable_fingerprint is an enforcement concern and is NOT inspected by TUI

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
        selected_snapshot_json_exists=selected_snapshot_json_exists,
        selected_snapshot_canonical_exists=selected_snapshot_canonical_exists,
        selected_snapshot_sha_file_exists=selected_snapshot_sha_file_exists,
        selected_snapshot_ready=selected_snapshot_ready,
        selected_snapshot_sha256=selected_snapshot_sha256,
        selected_snapshot_approved=selected_snapshot_approved,
        selected_run_id=eff_run_id,
        selected_run_exists=selected_run_exists,
        selected_run_core_exists=selected_run_core_exists,
        selected_run_anchors_exists=selected_run_anchors_exists,
        selected_merge_id=selected_merge_id,
        selected_merge_state_exists=selected_merge_state_exists,
    )


def format_facts(f: RepoFacts) -> str:
    def yn(v: bool) -> str:
        return "yes" if v else "no"


    lines: list[str] = []
    lines.append("READ-ONLY DASHBOARD (v3)")
    lines.append("")
    lines.append(f"repo_root: {f.repo_root}")
    lines.append("")

    lines.append("OBSERVED EVIDENCE (read-only facts; no FSM inference)")
    lines.append("")

    # Контрактный маркер для smoke_tui_read_only:
    # наблюдаемое состояние = классификация только по фактам на диске (без S0..S6).
    lines.append("OBSERVED FACTS (no FSM inference; no lifecycle decisions)")
    lines.append("")

    # Allowed/Forbidden = read-only список контрактных предикатов (инфо, не “разрешение”).

    actions = [
        ("DECIDE", "python -m scripts.orchestrator decide", "requires: any state"),
        ("APPROVE", "python -m scripts.orchestrator approve --snapshot <snapshot_id>", "requires: snapshot_ready (json + canonical + sha256)"),
        ("EXECUTE CORE", "python -m scripts.orchestrator execute --stage core", "requires: snapshot approved"),
        ("EXECUTE ANCHORS", "python -m scripts.orchestrator execute --stage anchors", "requires: snapshot approved"),
        ("MERGE", "python -m scripts.merge_pass2", "requires: core + anchors outputs for same approved snapshot"),
        ("POST-CHECK", "python scripts/check_deliverables.py <merge_id>", "requires: merge-state exists"),
    ]

    lines.append("ALLOWED ACTIONS (contract predicates only; NOT evaluated)")
    for name, cmd, reason in actions:
        lines.append(f"- {name}: {cmd}")
        lines.append(f"  - {reason}")
    lines.append("")

    lines.append(f"state/snapshots: {len(f.snapshots)} file(s)")
    lines.append(f"latest_snapshot_id: {f.latest_snapshot_id or '—'}")
    lines.append(f"selected_snapshot_id: {f.selected_snapshot_id or '—'}")
    lines.append(f"selected_snapshot_ready (json+canonical+sha): {yn(f.selected_snapshot_ready)}")
    lines.append(f"selected_snapshot_sha256: {f.selected_snapshot_sha256 or '—'}")
    lines.append(f"selected_snapshot_approved: {yn(f.selected_snapshot_approved) if f.selected_snapshot_sha256 else '—'}")
    lines.append("")

    lines.append(f"outputs/pass_2 runs: {len(f.runs)} dir(s)")
    lines.append(f"latest_run_id: {f.latest_run_id or '—'}")
    lines.append(f"selected_run_id: {f.selected_run_id or '—'}")
    lines.append(f"selected_run_core_exists: {yn(f.selected_run_core_exists)}")
    lines.append(f"selected_run_anchors_exists: {yn(f.selected_run_anchors_exists)}")

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

            yield Static("snapshot file:", id="lbl_snapshot_file")
            yield Select([], id="sel_snapshot_file", prompt="select snapshot file")
            yield TextArea("", id="snapshot_content")

            yield Static("run:", id="lbl_run")
            yield Select([], id="sel_run", prompt="select run")

            yield Static("run file:", id="lbl_run_file")
            yield Select([], id="sel_run_file", prompt="select run file")
            yield TextArea("", id="run_content")

            yield Static("", id="facts")
        yield Footer()

    def on_mount(self) -> None:
        # Вьюверы строго read-only
        self.query_one("#snapshot_content", TextArea).read_only = True
        self.query_one("#run_content", TextArea).read_only = True
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

        # Виджеты
        sel_snapshot = self.query_one("#sel_snapshot", Select)
        sel_run = self.query_one("#sel_run", Select)
        sel_snapshot_file = self.query_one("#sel_snapshot_file", Select)
        sel_run_file = self.query_one("#sel_run_file", Select)
        snapshot_content = self.query_one("#snapshot_content", TextArea)
        run_content = self.query_one("#run_content", TextArea)

        # 1) (опционально) перезагрузка inventory snapshot/run
        if reload_options:
            self._reloading_options = True
            try:
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

        # 2) Snapshot file viewer (ровно один файл)
        snap_file_rel: str | None = None
        snap_file_abs: Path | None = None
        if facts.selected_snapshot_id:
            snap_file_abs = facts.repo_root / "state" / "snapshots" / f"{facts.selected_snapshot_id}.snapshot.json"
            if snap_file_abs.exists():
                snap_file_rel = f"state/snapshots/{facts.selected_snapshot_id}.snapshot.json"

        self._reloading_options = True
        try:
            if snap_file_rel:
                sel_snapshot_file.set_options([(snap_file_rel, snap_file_rel)])
                sel_snapshot_file.value = snap_file_rel
            else:
                sel_snapshot_file.set_options([])
                sel_snapshot_file.value = None
        finally:
            self._reloading_options = False

        if snap_file_abs and snap_file_abs.exists():
            snapshot_content.text = _safe_read_raw_preview(snap_file_abs)
        else:
            snapshot_content.text = "(unavailable)"

        # 3) Run file viewer (рекурсивный список файлов)
        run_root = facts.repo_root / "outputs" / "pass_2" / facts.selected_run_id if facts.selected_run_id else None
        run_files = _list_files_recursive(run_root) if run_root else []

        # current selection (если пользователь уже выбирал файл)
        current_run_file = sel_run_file.value if isinstance(sel_run_file.value, str) else None
        if current_run_file not in run_files:
            current_run_file = run_files[0] if run_files else None

        self._reloading_options = True
        try:
            sel_run_file.set_options([(p, p) for p in run_files])
            sel_run_file.value = current_run_file
        finally:
            self._reloading_options = False

        if run_root and current_run_file:
            run_content.text = _safe_read_raw_preview(run_root / current_run_file)
        else:
            run_content.text = "(unavailable)"

        # 4) Summary facts (как было)
        self.query_one("#facts", Static).update(format_facts(facts))


def main() -> int:
    # В non-TTY (smoke/CI) Textual может не успеть отрендерить UI.
    # В этом режиме печатаем read-only проекцию контракта и выходим.
    if not sys.stdout.isatty():
        facts = collect_facts()
        print(format_facts(facts))
        return 0

    ReadOnlyDashboard().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
