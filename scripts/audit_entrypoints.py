#!/usr/bin/env python3
"""
audit_entrypoints.py — deterministic enforcement check

Goal:
- Extract canonical entrypoints from README.md (authoritative contract).
- Discover actual entrypoints in repo (CLI/CI/ps1 call surfaces).
- Diff them.
- Any mismatch => BLOCKER (exit 2).

Constraints:
- No LLM.
- No decisions. Pure verification.
- Output format must be: [LEVEL] ERROR_CODE: message
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Set, Tuple


ROOT = Path(__file__).resolve().parents[1]
README_PATH = ROOT / "README.md"

# Repo scan scope: keep it deterministic and avoid scanning generated junk.
SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "outputs",
    "state",
}

TEXT_EXTS = {
    ".py",
    ".yml",
    ".yaml",
    ".md",
    ".ps1",
    ".sh",
    ".txt",
}


# Canonical CLI output contract
def _print(level: str, code: str, msg: str) -> None:
    sys.stdout.write(f"[{level}] {code}: {msg}\n")


def _blocker(code: str, msg: str) -> int:
    _print("BLOCKER", code, msg)
    return 2


def _pass(msg: str = "OK") -> int:
    _print("PASS", "OK", msg)
    return 0


@dataclass(frozen=True)
class DiffResult:
    missing_in_readme: Tuple[str, ...]
    missing_in_code: Tuple[str, ...]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _iter_text_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in TEXT_EXTS:
            yield p


def _extract_entrypoints_table(readme: str) -> List[str]:
    """
    Extract first column from the markdown table under:
    '### Явный перечень entrypoints (HARD)'
    Table header example:
    | Entrypoint | Тип | Класс | Пишет `state/` | Drift guard |
    """
    anchor = "### Явный перечень entrypoints (HARD)"
    idx = readme.find(anchor)
    if idx == -1:
        return []

    tail = readme[idx:]
    lines = tail.splitlines()

    # Find first table header line starting with '| Entrypoint'
    start = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("|") and "Entrypoint" in ln:
            start = i
            break
    if start is None:
        return []

    # Table continues while lines start with '|'
    table_lines: List[str] = []
    for ln in lines[start:]:
        if not ln.strip().startswith("|"):
            break
        table_lines.append(ln.rstrip())

    if len(table_lines) < 3:
        return []

    # Skip header and separator
    data_lines = table_lines[2:]
    entrypoints: List[str] = []
    for ln in data_lines:
        cols = [c.strip() for c in ln.strip().strip("|").split("|")]
        if not cols:
            continue
        ep = cols[0]
        # strip backticks
        ep = ep.strip("`").strip()
        if ep:
            entrypoints.append(ep)

    return entrypoints


def _normalize_entrypoint(s: str) -> str:
    """
    Normalize entrypoint identifiers to match README table format.

    README uses:
    - module calls: "python -m scripts.<module> [subcmd]"
    - file entrypoints (rare, explicit): "scripts/<name>.py"
    """
    s = s.strip()
    s = s.replace("\\", "/")

    # Normalize multiple spaces
    s = re.sub(r"\s+", " ", s)

    # README-canonical file entrypoints (keep as scripts/<name>.py)
    file_entrypoints = {
        "view_snapshot.py",
        "gate_snapshot.py",
        "smoke_test_lifecycle.py",
    }

    # Normalize direct python script invocations:
    # example: python scripts/<file>.py ... -> scripts/<file>.py (then may map to python -m)
    m = re.match(r"^python\s+scripts/([a-zA-Z0-9_]+\.py)(?:\s+.*)?$", s)
    if m:
        s = f"scripts/{m.group(1)}"

    # Normalize scripts/<name>.py to module entrypoint by default:
    # scripts/merge_pass2.py -> python -m scripts.merge_pass2
    m2 = re.match(r"^scripts/([a-zA-Z0-9_]+)\.py$", s)
    if m2:
        fname = f"{m2.group(1)}.py"
        if fname not in file_entrypoints:
            return f"python -m scripts.{m2.group(1)}"
        return s

    return s


def _is_file_entrypoint(py_path: Path) -> bool:
    """
    Treat a scripts/*.py as an entrypoint only if it declares an explicit main-guard.
    This prevents accidental expansion of the README contract to "all scripts/*.py".
    """
    try:
        txt = _read_text(py_path)
    except Exception:
        return False

    return bool(re.search(r'if\s+__name__\s*==\s*["\']__main__["\']\s*:', txt))


def _discover_entrypoints(repo_root: Path) -> Set[str]:
    """
    Discover actual entrypoints by scanning text files for invocations.

    We deliberately do NOT "invent" new entrypoints.
    We only record what is explicitly invoked as a command surface
    + known file entrypoints as executable surfaces (scripts/*.py).
    """
    found: Set[str] = set()

    # 1) CI workflow files themselves are entrypoints
    wf_dir = repo_root / ".github" / "workflows"
    if wf_dir.exists():
        for wf in wf_dir.glob("*.yml"):
            found.add(f".github/workflows/{wf.name}")
        for wf in wf_dir.glob("*.yaml"):
            found.add(f".github/workflows/{wf.name}")

    # 2) PowerShell scripts under scripts/ are entrypoints
    scripts_dir = repo_root / "scripts"
    if scripts_dir.exists():
        for ps1 in scripts_dir.glob("*.ps1"):
            found.add(f"scripts/{ps1.name}")

    # 3) File entrypoints under scripts/
    # Only scripts with an explicit main-guard are treated as entrypoints.
    # Exclusions: orchestrator.py is a module-CLI with explicit subcommands in README,
    # so we do not treat the bare file as a separate entrypoint.
    excluded_file_entrypoints = {"orchestrator.py"}

    for py in scripts_dir.glob("*.py"):
        if py.name in excluded_file_entrypoints:
            continue
        if _is_file_entrypoint(py):
            found.add(f"scripts/{py.name}")


    # 4) Discover python invocations inside repo text files
    # - python -m scripts.orchestrator decide|approve|execute
    # - python scripts/<file>.py [args]
    re_mod = re.compile(r"\bpython\s+-m\s+scripts\.([a-zA-Z0-9_]+)(?:\s+([a-zA-Z0-9_-]+))?")
    re_script = re.compile(r"\bpython\s+scripts/([a-zA-Z0-9_]+\.py)(?:\s+.*)?")

    for fp in _iter_text_files(repo_root):
        try:
            txt = _read_text(fp)
        except Exception:
            continue

        for m in re_mod.finditer(txt):
            mod = m.group(1)
            arg1 = m.group(2)

            # Only orchestrator subcommands are public module entrypoints
            if mod == "orchestrator" and arg1 in {"decide", "approve", "execute"}:
                found.add(f"python -m scripts.orchestrator {arg1}")

        for m in re_script.finditer(txt):
            fname = m.group(1)
            found.add(f"python scripts/{fname}")


    # Normalize
    return {_normalize_entrypoint(x) for x in found}



def _diff(canonical: Set[str], actual: Set[str]) -> DiffResult:
    missing_in_readme = tuple(sorted(actual - canonical))
    missing_in_code = tuple(sorted(canonical - actual))
    return DiffResult(missing_in_readme=missing_in_readme, missing_in_code=missing_in_code)


def main(argv: List[str]) -> int:
    # No flags. Deterministic behavior only.
    if len(argv) != 0:
        return _blocker("INVALID_ARGUMENT", "usage: python -m scripts.audit_entrypoints")

    if not README_PATH.exists():
        return _blocker("IO_ERROR", "README.md not found")

    readme = _read_text(README_PATH)
    canonical_list = _extract_entrypoints_table(readme)
    if not canonical_list:
        return _blocker("INVALID_ARGUMENT", "canonical entrypoints table not found in README.md")

    canonical = {_normalize_entrypoint(x) for x in canonical_list}
    actual = _discover_entrypoints(ROOT)

    d = _diff(canonical, actual)
    if d.missing_in_readme or d.missing_in_code:
        parts: List[str] = []
        if d.missing_in_readme:
            parts.append("present in code but missing in README: " + "; ".join(d.missing_in_readme))
        if d.missing_in_code:
            parts.append("present in README but missing in code: " + "; ".join(d.missing_in_code))
        # We must use an existing BLOCKER code. Governance drift is lifecycle-unsafe.
        return _blocker("LIFECYCLE_VIOLATION", "entrypoints inventory mismatch: " + " | ".join(parts))

    return _pass("entrypoints inventory matches README")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
