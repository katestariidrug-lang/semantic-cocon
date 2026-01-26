"""
CLI Wizard (driver)

Контракт: thin driver. Не добавляет шагов, не принимает решений, не интерпретирует lifecycle.
В этой заготовке: только CLI-скелет без side-effects.
"""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scripts.cli_wizard",
        description="Thin driver for the canonical pipeline described in README.md (no side-effects in this stub).",
    )
    p.add_argument(
        "--version",
        action="store_true",
        help="Print version info (placeholder).",
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
