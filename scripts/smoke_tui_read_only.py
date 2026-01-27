from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path



def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for p in [here.parent, *here.parents]:
        if (p / "README.md").exists():
            return p
    return here.parent


def _audit_tui_imports(repo: Path) -> list[str]:
    """
    Governance enforcement (read-only):
    TUI не имеет права импортировать enforcing-модули напрямую или через локальные short-imports.

    Проверка статическая (AST), без выполнения кода.
    Возвращает список нарушений (строки для сообщения).
    """
    tui_path = repo / "scripts" / "tui.py"
    try:
        src = tui_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [f"tui.py not found at {tui_path}"]
    except OSError:
        return [f"tui.py unreadable at {tui_path}"]

    try:
        tree = ast.parse(src, filename=str(tui_path))
    except SyntaxError as e:
        return [f"tui.py syntax error: {e.msg} (line {e.lineno})"]

    # Запрещённые enforcing-модули по README (и их локальные short-import варианты).
    forbidden = {
        "scripts",
        "orchestrator",
        "lifecycle",
        "llm_cli_bridge",
        "merge_pass2",
        "check_deliverables",
        "audit_entrypoints",
        "cli_wizard",
    }

    offenders: list[str] = []

    def _base(mod: str) -> str:
        mod = mod.strip()
        if not mod:
            return ""
        return mod.split(".", 1)[0]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name or ""
                if _base(name) in forbidden:
                    offenders.append(f"import {name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            # from X import Y  (X может быть '', тогда это относительный импорт)
            if _base(mod) in forbidden:
                offenders.append(f"from {mod} import ...")
            else:
                # ловим from something import orchestrator (редко, но на всякий)
                for alias in node.names:
                    nm = alias.name or ""
                    if _base(nm) in forbidden:
                        offenders.append(f"from {mod or '(relative)'} import {nm}")

    return sorted(set(offenders))


def _snapshot_tree(root: Path) -> list[tuple[str, int, float]]:
    """
    Read-only "fingerprint" дерева репозитория для smoke-доказательства.
    Возвращает список (relative_path, size, mtime_ns) для всех файлов под root,
    исключая .git и __pycache__.

    mtime_ns используем вместо mtime, чтобы ловить любые реальные изменения.
    """
    out: list[tuple[str, int, float]] = []
    for p in root.rglob("*"):
        if p.is_dir():
            # игнорируем мусор
            if p.name in {".git", "__pycache__"}:
                # не спускаемся глубже
                continue
            continue
        # фильтры по частям пути
        parts = set(p.parts)
        if ".git" in parts or "__pycache__" in parts:
            continue

        st = p.stat()
        rel = str(p.relative_to(root))
        out.append((rel, st.st_size, st.st_mtime_ns))
    out.sort()
    return out


def main() -> int:
    repo = _repo_root()

    offenders = _audit_tui_imports(repo)
    if offenders:
        print("[BLOCKER] GOVERNANCE_VIOLATION: TUI imports enforcing modules (forbidden): " + "; ".join(offenders))
        return 2

    before = _snapshot_tree(repo)

    # Запускаем TUI на короткое время.
    # Мы НЕ можем гарантировать интерактив в CI, поэтому просто стартуем и сразу гасим.
    env = os.environ.copy()
    proc = subprocess.Popen(
        [sys.executable, str(repo / "scripts" / "tui.py")],
        cwd=str(repo),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        proc.communicate(timeout=1.0)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.communicate(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate(timeout=2.0)

    after = _snapshot_tree(repo)

    if before != after:
        # Печатаем мини-дифф, чтобы было чем тыкать.
        before_set = set(before)
        after_set = set(after)
        added = sorted(after_set - before_set)
        removed = sorted(before_set - after_set)

        print("[FAIL] IO_ERROR: TUI изменил дерево репозитория (read-only нарушен)")
        if added:
            print("Added:")
            for rel, size, mtime in added[:50]:
                print(f"  + {rel} (size={size}, mtime_ns={mtime})")
        if removed:
            print("Removed:")
            for rel, size, mtime in removed[:50]:
                print(f"  - {rel} (size={size}, mtime_ns={mtime})")
        return 1

    print("[PASS] OK: TUI не изменил дерево репозитория (read-only доказан)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
