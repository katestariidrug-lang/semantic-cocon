"""
CLI Wizard (static contract viewer, non-enforcing)

Контракт:
- helper / read-only
- НЕ driver
- НЕ участвует в lifecycle
- НЕ интерпретирует состояние проекта
- НЕ определяет порядок шагов
- НЕ запускает CLI и не имеет side-effects

Назначение:
- печать статического инструктивного текста и help/usage
  на основе README.md
"""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scripts.cli_wizard",
        description="Static, read-only contract viewer based on README.md (no lifecycle logic, no side-effects).",
    )
    p.add_argument(
        "--version",
        action="store_true",
        help="Print static version info (read-only).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        # Intentionally static placeholder. Do not infer repo state here.
        print("cli_wizard (stub) 0.0.0")
        return 0

    # Default behavior: show help, do nothing.
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
