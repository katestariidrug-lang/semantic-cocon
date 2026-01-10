from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Set

from dotenv import load_dotenv, find_dotenv


def _is_valid_json_with_keys(s: str, required_keys: list[str]) -> bool:

    if not s or not s.strip():
        return False
    try:
        obj = json.loads(s)
    except Exception:
        return False
    if not isinstance(obj, dict):
        return False
    return all(k in obj for k in required_keys)

def _collect_node_ids(obj: Any) -> List[str]:

    """
    Пытаемся извлечь node_id из TASK_JSON / ARCH_DECISION_JSON максимально терпимо,
    чтобы smoke-test не зависел от конкретной формы task.json.
    """
    ids: Set[str] = set()

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "node_id" and isinstance(v, str) and v:
                    ids.add(v)
                walk(v)
        elif isinstance(x, list):
            for it in x:
                walk(it)

    walk(obj)
    out = sorted(ids)
    if out:
        return out
    # запасной минимум для smoke-test, если в task.json нет явных node_id
    return ["node_1", "node_2"]


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

    # Подхватываем .env строго из текущего проекта (cwd), чтобы не словить "левый" .env выше по дереву
    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path)
    else:
        # нет .env — ок, работаем только с реальным окружением процесса
        load_dotenv(override=False)


    inp = Path(args.inp).read_text(encoding="utf-8")

    # SMOKE_TEST=1: детерминированный stub без внешнего LLM
    if os.getenv("SMOKE_TEST", "").strip() == "1":
        is_decide = "# PASS_1 / DECIDE" in inp
        is_execute = "# PASS_2 / EXECUTE" in inp
        if not (is_decide or is_execute):
            raise RuntimeError("UNKNOWN_PASS: cannot detect PASS_1/PASS_2 in request text")

        # TASK_JSON присутствует в обоих проходах
        task_json_text = extract_block(inp, "TASK_JSON:\n", "\n\nARCH_")
        task = json.loads(task_json_text)
        node_ids = _collect_node_ids(task)

        if is_decide:
            # Минимально достаточный arch_decision для оркестратора:
            # - pass = DECIDE (обязательное)
            # - immutable_architecture.node_registry (нужно post-check'у)
            out_obj: Dict[str, Any] = {
                "pass": "DECIDE",
                "immutable_architecture": {
                    "node_registry": {nid: {"node_id": nid} for nid in node_ids}
                },
                "meta": {"smoke_test": True},
            }
            Path(args.out).write_text(json.dumps(out_obj, ensure_ascii=False, indent=2), encoding="utf-8")
            return 0

        # EXECUTE: генерируем deliverables по node_ids, без immutable_architecture
        # Stage определяем ДЕТЕРМИНИРОВАННО по пути --out (это стабильнее, чем маркеры в промпте).
        out_s = str(Path(args.out)).replace("\\", "/").lower()
        if "/core/" in out_s:
            is_core = True
            is_anchors = False
        elif "/anchors/" in out_s:
            is_core = False
            is_anchors = True
        else:
            # fallback: если путь неожиданно не содержит stage
            is_core = "pass_2_execute_core" in inp or "PASS_2A" in inp or "\n# CORE" in inp
            is_anchors = "pass_2_execute_anchors" in inp or "PASS_2B" in inp or "\n# ANCHORS" in inp

            # В smoke-режиме не падаем из-за ambiguous: выбираем core по умолчанию.
            if is_core and is_anchors:
                is_anchors = False

        if is_core:

            deliverables = {
                "semantic_enrichment": {nid: {"node_id": nid, "text": f"semantic {nid}"} for nid in node_ids},
                "keywords": {nid: {"node_id": nid, "keywords": [f"kw_{nid}_1", f"kw_{nid}_2"]} for nid in node_ids},
                "patient_questions": {nid: {"node_id": nid, "questions": [f"q_{nid}_1"]} for nid in node_ids},
            }
        elif is_anchors:
            # anchors.json MUST be a list (post-check contract)
            anchors = []
            if len(node_ids) >= 2:
                anchors.append({
                    "from_node_id": node_ids[0],
                    "to_node_id": node_ids[1],
                    "anchor_text": "stub",
                })
            deliverables = {"anchors": anchors}
        else:
            raise RuntimeError("SMOKE_STUB_STAGE_UNKNOWN: cannot detect core/anchors markers in prompt")

        out_obj = {"deliverables": deliverables, "meta": {"smoke_test": True}}

        Path(args.out).write_text(json.dumps(out_obj, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    # --- REAL LLM PATH (non-smoke) ---
    # Импортируем SDK только тут, чтобы SMOKE_TEST не тащил deprecated пакет и warning'и.
    import google.generativeai as genai  # type: ignore

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

        reason_str = None
        try:
            reason_str = finish_reason.name  # Enum-like
        except Exception:
            reason_str = str(finish_reason) if finish_reason is not None else None

        if reason_str and reason_str not in ("STOP", "FinishReason.STOP"):
            # Иногда провайдер помечает ответ как "не STOP", но JSON уже полный и валидный.
            # В этом случае принимаем результат, иначе — это реальная обрезка.
            if not _is_valid_json_with_keys(output_text, ["immutable_architecture"]):
                # Сохраняем сырой (возможно обрезанный) вывод для диагностики
                Path(args.out).write_text(output_text, encoding="utf-8")
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

    reason_str = None
    try:
        reason_str = finish_reason.name  # Enum-like
    except Exception:
        reason_str = str(finish_reason) if finish_reason is not None else None

    if reason_str and reason_str not in ("STOP", "FinishReason.STOP"):
        # Аналогично: если JSON валиден и содержит deliverables — принимаем.
        if not _is_valid_json_with_keys(output_text, ["deliverables"]):
            Path(args.out).write_text(output_text, encoding="utf-8")
            raise RuntimeError(f"LLM_OUTPUT_TRUNCATED: finish_reason={finish_reason}")


    Path(args.out).write_text(output_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
