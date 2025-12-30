"""
ФАЙЛ: scripts/orchestrator.py
НАЗНАЧЕНИЕ: Оркестратор двухпроходного workflow:
  - decide  : запуск PASS_1 → получить ARCH_DECISION_JSON → сохранить snapshot+hash
  - approve : человеческое подтверждение конкретного snapshot-hash
  - execute : запуск PASS_2 только если snapshot верифицирован и подтверждён

ИСПОЛЬЗУЕТСЯ: VS Code tasks / CLI.
ДОСТУП LLM: запрещён (LLM не управляет state, не проверяет immutability).
"""

from __future__ import annotations

import argparse
import json
import sys
import subprocess
from pathlib import Path
from typing import Any, Dict, Tuple

from scripts.state_utils import save_snapshot, verify_snapshot_files, fingerprint_immutable_architecture

ROOT = Path(__file__).resolve().parents[1]  # project-root/
PROMPTS_DIR = ROOT / "prompts"
INPUT_DIR = ROOT / "input"
STATE_DIR = ROOT / "state"
OUTPUTS_DIR = ROOT / "outputs"

SNAPSHOTS_DIR = STATE_DIR / "snapshots"
APPROVALS_DIR = STATE_DIR / "approvals"

PASS_1_PROMPT_PATH = PROMPTS_DIR / "pass_1_decide.md"
PASS_2_PROMPT_PATH = PROMPTS_DIR / "pass_2_execute.md"

TASK_JSON_PATH = INPUT_DIR / "task.json"
ARCH_SCHEMA_PATH = STATE_DIR / "arch_decision_schema.json"


def read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")
    return path.read_text(encoding="utf-8")


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(read_text(path))


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json_pretty(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def build_pass_1_request(task_json: Dict[str, Any], arch_schema_json: Dict[str, Any], pass_1_prompt: str) -> str:
    """
    Склеиваем единый запрос: промпт + TASK_JSON + ARCH_SCHEMA_JSON.
    Это нужно, чтобы модель не "забыла" схему и не придумала свою.
    """
    payload = {
        "TASK_JSON": task_json,
        "ARCH_SCHEMA_JSON": arch_schema_json
    }

    return (
        pass_1_prompt.strip()
        + "\n\n"
        + "TASK_JSON:\n"
        + json.dumps(payload["TASK_JSON"], ensure_ascii=False, indent=2)
        + "\n\n"
        + "ARCH_SCHEMA_JSON:\n"
        + json.dumps(payload["ARCH_SCHEMA_JSON"], ensure_ascii=False, indent=2)
        + "\n"
    )


def extract_json_strict(text: str) -> Dict[str, Any]:
    """
    Строго ожидаем, что ответ = JSON-объект, без префиксов/суффиксов.
    Если модель добавила лишний текст — это ошибка ранна.
    """
    s = text.strip()
    if not (s.startswith("{") and s.endswith("}")):
        raise ValueError("LLM_OUTPUT_NOT_PURE_JSON: ответ не является чистым JSON-объектом")
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM_OUTPUT_INVALID_JSON: {e}") from e


import subprocess

RUNTIME_DIR = STATE_DIR / "runtime"
REQ_PATH = RUNTIME_DIR / "last_request.txt"
RESP_PATH = RUNTIME_DIR / "last_response.txt"

def run_llm(prompt_text: str) -> str:
    """
    Реальный вызов LLM через CLI-команду.
    Требования:
      - записать запрос в файл (для воспроизводимости)
      - вызвать внешнюю команду
      - прочитать ответ из файла
    """
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    REQ_PATH.write_text(prompt_text, encoding="utf-8")

    # Здесь мы вызываем внешнюю утилиту, которая:
    # - читает запрос из REQ_PATH
    # - пишет ответ в RESP_PATH
    #
    # Пока это "провод" без привязки к провайдеру.
    cmd = ["python", "-m", "scripts.llm_cli_bridge", "--in", str(REQ_PATH), "--out", str(RESP_PATH)]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"LLM_CLI_FAILED: {proc.stderr.strip() or proc.stdout.strip()}")

    if not RESP_PATH.exists():
        raise FileNotFoundError(f"LLM_NO_RESPONSE_FILE: {RESP_PATH}")

    return RESP_PATH.read_text(encoding="utf-8")


def cmd_decide() -> None:
    # 1) прочитать входы
    task = read_json(TASK_JSON_PATH)
    schema = read_json(ARCH_SCHEMA_PATH)
    pass_1_prompt = read_text(PASS_1_PROMPT_PATH)

    task_id = task.get("task_id") or "task"
    raw_out_path = OUTPUTS_DIR / "pass_1_raw.jsonl"

    # 2) собрать запрос
    request_text = build_pass_1_request(task, schema, pass_1_prompt)

    # 3) вызвать LLM (пока заглушка)
    llm_text = run_llm(request_text)

    # 4) сохранить сырой ответ (на случай разборок)
    write_text(raw_out_path, llm_text)

    # 5) распарсить строго JSON
    arch_decision = extract_json_strict(llm_text)

    # 6) минимальная sanity-проверка по контракту
    if arch_decision.get("pass") != "DECIDE":
        raise ValueError("ARCH_DECISION_INVALID: поле pass должно быть 'DECIDE'")

    # 7) сохранить snapshot+canonical+hash
    paths = save_snapshot(
        arch_decision_json=arch_decision,
        snapshots_dir=SNAPSHOTS_DIR,
        task_id=task_id,
    )

    # 8) вывести пути (для человека и для VS Code логов)
    print("DECIDE_OK")
    print(f"SNAPSHOT:  {paths.snapshot_path}")
    print(f"CANONICAL: {paths.canonical_path}")
    print(f"HASH:      {paths.hash_path}")


def approval_file_for_hash(hash_hex: str) -> Path:
    return APPROVALS_DIR / f"{hash_hex}.approved"


def cmd_approve(snapshot_path: str) -> None:
    """
    Человеческое подтверждение конкретного snapshot.
    Сценарий:
      - ты смотришь snapshot
      - если ок — создаём файл approvals/<hash>.approved
    """
    snap_path = Path(snapshot_path)
    if not snap_path.exists():
        raise FileNotFoundError(f"Snapshot не найден: {snap_path}")

    # hash рядом, по имени (task__prefix.sha256)
    hash_path = snap_path.with_suffix("").with_suffix(".sha256")  # .snapshot.json -> .sha256
    # если не угадали суффикс, попробуем простой вариант:
    if not hash_path.exists():
        # fallback: заменить ".snapshot.json" на ".sha256"
        hash_path = Path(str(snap_path).replace(".snapshot.json", ".sha256"))
    if not hash_path.exists():
        raise FileNotFoundError(f"Hash file не найден рядом со snapshot: {hash_path}")

    ok, msg = verify_snapshot_files(snap_path, hash_path)
    if not ok:
        raise ValueError(f"VERIFY_FAIL: {msg}")

    hash_hex = hash_path.read_text(encoding="utf-8").strip()
    APPROVALS_DIR.mkdir(parents=True, exist_ok=True)
    approval_path = approval_file_for_hash(hash_hex)
    approval_path.write_text("approved\n", encoding="utf-8")

    print("APPROVE_OK")
    print(f"APPROVAL: {approval_path}")


def cmd_execute(snapshot_path: str) -> None:
    """
    PASS_2 выполняется ТОЛЬКО если:
      1) snapshot hash верифицируется
      2) существует approvals/<hash>.approved
    """
    snap_path = Path(snapshot_path)
    if not snap_path.exists():
        raise FileNotFoundError(f"Snapshot не найден: {snap_path}")

    hash_path = Path(str(snap_path).replace(".snapshot.json", ".sha256"))
    if not hash_path.exists():
        raise FileNotFoundError(f"Hash file не найден: {hash_path}")

    ok, msg = verify_snapshot_files(snap_path, hash_path)
    if not ok:
        raise ValueError(f"VERIFY_FAIL: {msg}")

    hash_hex = hash_path.read_text(encoding="utf-8").strip()
    approval_path = approval_file_for_hash(hash_hex)
    if not approval_path.exists():
        raise PermissionError(f"NO_APPROVAL: нет файла подтверждения {approval_path}")

    # Загружаем то, что заморожено
    task = read_json(TASK_JSON_PATH)
    arch_decision = read_json(snap_path)
    
    immutable_fp = fingerprint_immutable_architecture(arch_decision)

    pass_2_prompt = read_text(PASS_2_PROMPT_PATH)

    # Собираем запрос PASS_2 (сделаем нормально на следующем шаге)
    request = {
        "TASK_JSON": task,
        "ARCH_DECISION_JSON": arch_decision
    }
    request_text = (
        pass_2_prompt.strip()
        + "\n\n"
        + "TASK_JSON:\n"
        + json.dumps(request["TASK_JSON"], ensure_ascii=False, indent=2)
        + "\n\n"
        + "ARCH_DECISION_JSON:\n"
        + json.dumps(request["ARCH_DECISION_JSON"], ensure_ascii=False, indent=2)
        + "\n"
    )

    llm_text = run_llm(request_text)

    # 1) сохранить сырой ответ
    out_dir = OUTPUTS_DIR / "pass_2" / f"{task.get('task_id','task')}__{hash_hex[:12]}"
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_path = out_dir / "execution_result.raw.txt"
    write_text(raw_path, llm_text)

    # 2) строго распарсить JSON (без текста до/после)
    exec_json = extract_json_strict(llm_text)

    # Оркестратор сам фиксирует отпечаток immutable (LLM не управляет этим)
    exec_json["immutable_fingerprint"] = immutable_fp

    # Защита от подмены: deliverables не должны содержать immutable_architecture
    deliverables = exec_json.get("deliverables", {})
    if "immutable_architecture" in deliverables:
        raise ValueError("IMMUTABILITY_VIOLATION: deliverables содержит immutable_architecture")


    # 3) сохранить нормальный JSON
    json_path = out_dir / "execution_result.json"
    write_json_pretty(json_path, exec_json)

    # 4) разложить deliverables по отдельным файлам
    deliverables = exec_json.get("deliverables", {})
    parts = {
        "semantic_enrichment": "semantic_enrichment.json",
        "keywords": "keywords.json",
        "anchors": "anchors.json",
        "patient_questions": "patient_questions.json",
        "final_artifacts": "final_artifacts.json",
    }

    for key, filename in parts.items():
        part_path = out_dir / filename
        write_json_pretty(part_path, deliverables.get(key, {}))

    # --- POST-CHECK: validate deliverables ---
    check_script = ROOT / "scripts" / "check_deliverables.py"
    if not check_script.exists():
        raise FileNotFoundError(f"Post-check script not found: {check_script}")

    snapshot_id = snap_path.stem.replace(".snapshot", "")
    res = subprocess.run(
        [sys.executable, str(check_script), snapshot_id],
        cwd=ROOT,
    )

    if res.returncode != 0:
        raise RuntimeError("DELIVERABLES_CHECK_FAILED")

    print("DELIVERABLES_OK")
    print("EXECUTE_OK")
    print(f"RAW:  {raw_path}")
    print(f"JSON: {json_path}")

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="orchestrator", description="Two-pass LLM workflow orchestrator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("decide", help="Run PASS_1 (DECIDE)")

    p_approve = sub.add_parser("approve", help="Approve a snapshot (human step)")
    p_approve.add_argument("--snapshot", required=True, help="Path to *.snapshot.json")

    p_execute = sub.add_parser("execute", help="Run PASS_2 (EXECUTE) with verified+approved snapshot")
    p_execute.add_argument("--snapshot", required=True, help="Path to *.snapshot.json")

    args = parser.parse_args(argv)

    try:
        if args.cmd == "decide":
            cmd_decide()
        elif args.cmd == "approve":
            cmd_approve(args.snapshot)
        elif args.cmd == "execute":
            cmd_execute(args.snapshot)
        else:
            raise ValueError(f"Unknown command: {args.cmd}")
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
