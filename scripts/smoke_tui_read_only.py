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

    # Запрещённые enforcing-модули по README.
    # ВАЖНО: "scripts" сам по себе НЕ запрещён, запрещены конкретные enforcing-модули.
    forbidden_short = {
        "orchestrator",
        "lifecycle",
        "llm_cli_bridge",
        "merge_pass2",
        "check_deliverables",
        "audit_entrypoints",
        "cli_wizard",
    }
    forbidden_full = {f"scripts.{m}" for m in forbidden_short}

    offenders: list[str] = []

    def _is_forbidden_module(mod: str) -> bool:
        mod = (mod or "").strip()
        if not mod:
            return False

        # Точные запрещённые: scripts.<enforcing>
        if mod in forbidden_full:
            return True

        # Также запрещаем импорт "коротких" enforcing-модулей, если кто-то делает short-import
        # (например "import orchestrator" или "from X import orchestrator").
        if mod in forbidden_short:
            return True

        # И ещё вариант: строка вида "scripts.<name>.<sub>"
        if mod.startswith("scripts."):
            parts = mod.split(".")
            if len(parts) >= 2 and parts[1] in forbidden_short:
                return True

        return False


    # Минимальный статический трекинг алиасов/присваиваний (без выполнения кода).
    # Цель: детектировать alias-based и indirect dynamic imports одной строкой.
    importlib_aliases: set[str] = set()  # имена, указывающие на модуль importlib (включая alias)
    const_str: dict[str, str] = {}       # name -> строковый литерал
    dyn_import_funcs: set[str] = set()   # name -> callable, ведущий к динамическому импорту

    def _note_const_str(target: ast.expr, value: ast.expr) -> None:
        if isinstance(target, ast.Name) and isinstance(value, ast.Constant) and isinstance(value.value, str):
            const_str[target.id] = value.value

    def _mark_dyn_import_func(target: ast.expr) -> None:
        if isinstance(target, ast.Name):
            dyn_import_funcs.add(target.id)

    def _resolve_str(expr: ast.expr) -> str | None:
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return expr.value
        if isinstance(expr, ast.Name) and expr.id in const_str:
            return const_str[expr.id]
        return None

    def _is_importlib_name(expr: ast.expr) -> bool:
        return isinstance(expr, ast.Name) and expr.id in importlib_aliases

    def _is_direct_import_module_attr(expr: ast.expr) -> bool:
        # X.import_module где X = importlib или alias
        return isinstance(expr, ast.Attribute) and expr.attr == "import_module" and _is_importlib_name(expr.value)

    def _is_getattr_import_module_call(expr: ast.expr) -> bool:
        # getattr(X, "import_module") где X = importlib или alias
        if not isinstance(expr, ast.Call):
            return False
        if not (isinstance(expr.func, ast.Name) and expr.func.id == "getattr"):
            return False
        if len(expr.args) < 2:
            return False
        if not _is_importlib_name(expr.args[0]):
            return False
        return isinstance(expr.args[1], ast.Constant) and expr.args[1].value == "import_module"

    def _is_dyn_import_callee(expr: ast.expr) -> bool:
        # __import__(...) или alias на __import__
        if isinstance(expr, ast.Name):
            if expr.id == "__import__":
                return True
            if expr.id in dyn_import_funcs:
                return True
        # importlib.import_module(...) или alias.import_module(...)
        if _is_direct_import_module_attr(expr):
            return True
        # getattr(importlib, "import_module")(...)
        if _is_getattr_import_module_call(expr):
            return True
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name or ""

                # Трекаем alias importlib as X
                if name == "importlib":
                    importlib_aliases.add(alias.asname or "importlib")

                # Запрещаем только enforcing-модули, не весь "scripts".
                if _is_forbidden_module(name):
                    offenders.append(f"import {name}")


        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            # from scripts.orchestrator import X
            if _is_forbidden_module(mod):
                offenders.append(f"from {mod} import ...")
            else:
                # from scripts import orchestrator
                for alias in node.names:
                    nm = alias.name or ""
                    if _is_forbidden_module(nm) or _is_forbidden_module(f"{mod}.{nm}" if mod else nm):
                        offenders.append(f"from {mod or '(relative)'} import {nm}")


        elif isinstance(node, ast.Assign):
            # a = "scripts.orchestrator"
            for t in node.targets:
                _note_const_str(t, node.value)

            # fn = importlib.import_module  (или alias.import_module)
            if _is_direct_import_module_attr(node.value):
                for t in node.targets:
                    _mark_dyn_import_func(t)

            # fn = getattr(importlib, "import_module")
            if _is_getattr_import_module_call(node.value):
                for t in node.targets:
                    _mark_dyn_import_func(t)

            # fn = __import__
            if isinstance(node.value, ast.Name) and node.value.id == "__import__":
                for t in node.targets:
                    _mark_dyn_import_func(t)

        # dynamic imports (любая форма) — запрещены контрактом, и особенно если ведут к enforcing-модулям.
        elif isinstance(node, ast.Call):
            fn = node.func

            # (intentionally removed duplicate _is_dyn_import_callee;
            # use the top-level helper definition)

            if _is_dyn_import_callee(fn):
                # Аргумент модуля может быть литералом или именем переменной со строкой.
                mod0 = _resolve_str(node.args[0]) if node.args else None

                # Если строка известна — проверяем точечно на enforcing.
                if mod0 is not None:
                    if _is_forbidden_module(mod0):
                        offenders.append(f"indirect dynamic import: {mod0}")
                else:
                    # Нелитеральный/неразрешённый динамический импорт — сам по себе нарушение:
                    # иначе это один-лайн обход.
                    offenders.append("indirect dynamic import: <non-literal module>")


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
        print("[BLOCKER] GOVERNANCE_VIOLATION: indirect dynamic enforcing import detected: " + "; ".join(offenders))
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
        out, err = proc.communicate(timeout=1.0)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            out, err = proc.communicate(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate(timeout=2.0)

    # ---- UX contract checks (read-only projection) ----
    stdout = out or ""

    if "OBSERVED_FSM_STATE:" not in stdout:
        print("[FAIL] UX_CONTRACT_VIOLATION: OBSERVED_FSM_STATE not found in TUI output")
        return 1

    if "ALLOWED ACTIONS" not in stdout:
        print("[FAIL] UX_CONTRACT_VIOLATION: ALLOWED ACTIONS section not found in TUI output")
        return 1

    if "FORBIDDEN ACTIONS" not in stdout:
        print("[FAIL] UX_CONTRACT_VIOLATION: FORBIDDEN ACTIONS section not found in TUI output")
        return 1

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

    print("[PASS] OK: TUI read-only + UX contract projection доказаны")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
