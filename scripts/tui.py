"""
Textual TUI (read-only dashboard).

TYPE: helper
ROLE: UI only. No lifecycle logic. No writes. No subprocess/CLI запусков.

Показывает факты по диску (state/ + outputs/), ничего не запускает.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
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

    # immutable_fingerprint наблюдение (best-effort, read-only)
    selected_core_immutable_fingerprint: str | None
    selected_anchors_immutable_fingerprint: str | None
    selected_stage_fingerprints_match: bool  # core == anchors and not None

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


def _safe_read_json(path: Path) -> Any | None:
    """
    Read-only: best-effort JSON reader.
    Любая ошибка => None (UI не является гейтом).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _extract_immutable_fingerprint(execution_result_path: Path) -> str | None:
    """
    Read-only: пытаемся вытащить immutable_fingerprint из execution_result.json.
    Это НЕ enforcement и НЕ гарантия; только наблюдение.
    """
    obj = _safe_read_json(execution_result_path)
    if not isinstance(obj, dict):
        return None
    val = obj.get("immutable_fingerprint")
    return val if isinstance(val, str) and val.strip() else None


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

    selected_core_immutable_fingerprint = None
    selected_anchors_immutable_fingerprint = None
    selected_stage_fingerprints_match = False

    selected_merge_id = None
    selected_merge_state_exists = False

    if eff_run_id:
        run_root = pass2_dir / eff_run_id
        selected_run_exists = run_root.exists()

        core_dir = run_root / "core"
        anchors_dir = run_root / "anchors"
        selected_run_core_exists = core_dir.exists() and core_dir.is_dir()
        selected_run_anchors_exists = anchors_dir.exists() and anchors_dir.is_dir()

        if selected_run_core_exists:
            selected_core_immutable_fingerprint = _extract_immutable_fingerprint(core_dir / "execution_result.json")
        if selected_run_anchors_exists:
            selected_anchors_immutable_fingerprint = _extract_immutable_fingerprint(anchors_dir / "execution_result.json")

        if (
            selected_core_immutable_fingerprint
            and selected_anchors_immutable_fingerprint
            and selected_core_immutable_fingerprint == selected_anchors_immutable_fingerprint
        ):
            selected_stage_fingerprints_match = True

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
        selected_core_immutable_fingerprint=selected_core_immutable_fingerprint,
        selected_anchors_immutable_fingerprint=selected_anchors_immutable_fingerprint,
        selected_stage_fingerprints_match=selected_stage_fingerprints_match,
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
    def observed_fsm_state() -> str:
        ev_snapshot_ready = f.selected_snapshot_ready
        ev_approved = bool(f.selected_snapshot_sha256) and f.selected_snapshot_approved
        ev_core = f.selected_run_core_exists
        ev_anchors = f.selected_run_anchors_exists
        ev_fp_match = f.selected_stage_fingerprints_match
        ev_merge = (f.selected_merge_id is not None and f.selected_merge_state_exists)

        if ev_merge:
            return "MERGED"
        if ev_core and ev_anchors and ev_fp_match:
            return "EXECUTED_CORE_AND_ANCHORS"
        if ev_approved:
            return "APPROVED"
        if ev_snapshot_ready:
            return "SNAPSHOT_READY"
        if f.snapshots:
            return "HAS_SNAPSHOTS"
        return "EMPTY"

    lines.append(f"OBSERVED_FSM_STATE: {observed_fsm_state()}")
    lines.append("")

    # Allowed/Forbidden = read-only проекция контрактных предикатов (инфо, не “разрешение”).

    ev_snapshot_ready = f.selected_snapshot_ready
    ev_approved = bool(f.selected_snapshot_sha256) and f.selected_snapshot_approved
    ev_core = f.selected_run_core_exists
    ev_anchors = f.selected_run_anchors_exists
    ev_fp_match = f.selected_stage_fingerprints_match
    ev_merge_id_present = (f.selected_merge_id is not None)
    ev_merge_state_exists = bool(f.selected_merge_id) and f.selected_merge_state_exists
    ev_merge = ev_merge_id_present and ev_merge_state_exists

    actions = [
        ("DECIDE", "python -m scripts.orchestrator decide", True, "requires: any state"),
        ("APPROVE", "python -m scripts.orchestrator approve --snapshot <snapshot_id>", ev_snapshot_ready, f"requires: snapshot_ready(json+canonical+sha)={yn(ev_snapshot_ready)}"),
        ("EXECUTE CORE", "python -m scripts.orchestrator execute --stage core --snapshot state/snapshots/<snapshot_id>.snapshot.json", ev_approved, f"requires: snapshot_approved={yn(ev_approved)}"),
        ("EXECUTE ANCHORS", "python -m scripts.orchestrator execute --stage anchors --snapshot state/snapshots/<snapshot_id>.snapshot.json", ev_approved, f"requires: snapshot_approved={yn(ev_approved)}"),
        ("MERGE", "python -m scripts.merge_pass2 --core-snapshot-id <run_id> --anchors-snapshot-id <run_id>", (ev_core and ev_anchors and ev_fp_match), f"requires: core_exists={yn(ev_core)}, anchors_exists={yn(ev_anchors)}, immutable_fingerprint_match={yn(ev_fp_match)}"),
        ("POST-CHECK", "python scripts/check_deliverables.py <merge_id>", ev_merge, f"requires: merge_id_present={yn(ev_merge_id_present)}, merge_state_exists={yn(ev_merge_state_exists)}"),
    ]

    lines.append("ALLOWED ACTIONS (info only; NOT permission; NOT advice; NOT execution)")
    for name, cmd, ok, reason in actions:
        if ok:
            lines.append(f"- {name}: {cmd}")
            lines.append(f"  - {reason}")
    lines.append("")

    lines.append("FORBIDDEN ACTIONS (info only; NOT permission; NOT advice; NOT execution)")
    for name, cmd, ok, reason in actions:
        if not ok:
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
    lines.append(f"immutable_fingerprint (core): {f.selected_core_immutable_fingerprint or '—'}")
    lines.append(f"immutable_fingerprint (anchors): {f.selected_anchors_immutable_fingerprint or '—'}")
    lines.append(f"immutable_fingerprint match: {yn(f.selected_stage_fingerprints_match)}")
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
