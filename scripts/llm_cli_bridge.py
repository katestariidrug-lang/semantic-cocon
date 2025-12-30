"""
ФАЙЛ: scripts/llm_cli_bridge.py
НАЗНАЧЕНИЕ: Мост между orchestrator и конкретным LLM-провайдером.
СЕЙЧАС: тестовый режим (dummy), который:
  - для PASS_1 возвращает ARCH_DECISION_JSON с заполненным task
  - для PASS_2 возвращает EXECUTION_RESULT_JSON (минимальный каркас)
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv


def extract_block(inp: str, start_marker: str, end_marker: str) -> str:
    start = inp.find(start_marker)
    if start == -1:
        raise RuntimeError(f"MARKER_NOT_FOUND: {start_marker!r}")
    start += len(start_marker)
    end = inp.find(end_marker, start)
    if end == -1:
        raise RuntimeError(f"MARKER_NOT_FOUND: {end_marker!r}")
    return inp[start:end].strip()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--out", dest="out", required=True)
    args = p.parse_args()

    # Подхватываем .env из корня проекта (если он есть)
    load_dotenv()

    inp = Path(args.inp).read_text(encoding="utf-8")

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY не задан в переменных окружения")

    genai.configure(api_key=api_key)

    model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")
    model = genai.GenerativeModel(
        model_name,
        generation_config={"temperature": 0},
    )


    # Определяем режим по заголовку промпта
    is_decide = "# PASS_1 / DECIDE" in inp
    is_execute = "# PASS_2 / EXECUTE" in inp

    if not (is_decide or is_execute):
        raise RuntimeError("UNKNOWN_PASS: cannot detect PASS_1/PASS_2 in request text")

    # TASK_JSON присутствует в обоих проходах
    task_json_text = extract_block(inp, "TASK_JSON:\n", "\n\nARCH_")
    task = json.loads(task_json_text)

    if is_decide:
        resp = model.generate_content(inp)
        output_text = resp.text or ""
        Path(args.out).write_text(output_text, encoding="utf-8")
        return 0

    # PASS_2: EXECUTE
    # Для теста отдаём минимально валидный каркас результата.
    resp = model.generate_content(inp)
    output_text = resp.text or ""
    Path(args.out).write_text(output_text, encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
