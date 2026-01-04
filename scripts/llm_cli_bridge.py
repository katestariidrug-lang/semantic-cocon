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
        generation_config={
            "temperature": 0,
            # PASS_2 может быть большим (18 узлов + per-node deliverables)
            "max_output_tokens": 32768,
        },
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

        finish_reason = None
        try:
            finish_reason = resp.candidates[0].finish_reason
        except Exception:
            pass

        output_text = resp.text or ""
        print(f"[llm_cli_bridge] output length = {len(output_text)} chars")

        reason_str = None
        try:
            reason_str = finish_reason.name  # Enum-like
        except Exception:
            reason_str = str(finish_reason) if finish_reason is not None else None

        if reason_str and reason_str not in ("STOP", "FinishReason.STOP"):
            raise RuntimeError(f"LLM_OUTPUT_TRUNCATED: finish_reason={finish_reason}")


        Path(args.out).write_text(output_text, encoding="utf-8")
        return 0


    # PASS_2: EXECUTE
    resp = model.generate_content(inp)

    # Gemini может молча обрезать ответ по лимиту
    finish_reason = None
    try:
        finish_reason = resp.candidates[0].finish_reason
    except Exception:
        pass

    output_text = resp.text or ""
    print(f"[llm_cli_bridge] output length = {len(output_text)} chars")

    reason_str = None
    try:
        reason_str = finish_reason.name  # Enum-like
    except Exception:
        reason_str = str(finish_reason) if finish_reason is not None else None

    if reason_str and reason_str not in ("STOP", "FinishReason.STOP"):
        raise RuntimeError(f"LLM_OUTPUT_TRUNCATED: finish_reason={finish_reason}")


    Path(args.out).write_text(output_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
