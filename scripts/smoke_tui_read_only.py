from __future__ import annotations

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
