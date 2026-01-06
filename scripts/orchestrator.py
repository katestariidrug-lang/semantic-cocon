from __future__ import annotations

import argparse
import json
import sys
import subprocess
import shutil
from pathlib import Path
from typing import Any, Dict

from scripts.state_utils import (
    save_snapshot,
    verify_snapshot_files,
    fingerprint_immutable_architecture,
    fingerprint_file,
    read_sha256_file,
)

from scripts.lifecycle import LifecycleViolation

# -------------------------
# Unified CLI contract (orchestrator)
# -------------------------
EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_BLOCKER = 2

LEVEL_PASS = "PASS"
LEVEL_FAIL = "FAIL"
LEVEL_BLOCKER = "BLOCKER"

ERROR_CODES = {
    "DECIDE_OK",
    "APPROVE_OK",
    "EXECUTE_OK",
    "LIFECYCLE_VIOLATION",
    "ORCHESTRATOR_FAILED",
}

def emit(level: str, code: str, message: str, evidence: dict | None = None) -> None:
    if code not in ERROR_CODES:
        # неизвестный код = нарушение контракта => BLOCKER, но exit решает main()
        print(f"[{LEVEL_BLOCKER}] ORCHESTRATOR_FAILED: unknown error code used")
        payload = {"bad_code": code}
        if evidence is not None:
            payload.update(evidence)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return

    print(f"[{level}] {code}: {message}")
    if evidence is not None:
        print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))

ROOT = Path(__file__).resolve().parents[1]  # project-root/
PROMPTS_DIR = ROOT / "prompts"
INPUT_DIR = ROOT / "input"
STATE_DIR = ROOT / "state"
OUTPUTS_DIR = ROOT / "outputs"

SNAPSHOTS_DIR = STATE_DIR / "snapshots"
APPROVALS_DIR = STATE_DIR / "approvals"

PASS_1_PROMPT_PATH = PROMPTS_DIR / "pass_1_decide.md"
PASS_2_PROMPT_CORE_PATH = PROMPTS_DIR / "pass_2_execute_core.md"
PASS_2_PROMPT_ANCHORS_PATH = PROMPTS_DIR / "pass_2_execute_anchors.md"

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
    Допускается наличие BOM или служебных символов в начале.
    """
    # нормализация (BOM + переносы строк)
    # BOM + типичный "невидимый мусор" из CLI/копипаста
    s = text.lstrip("\ufeff\u200b\u200e\u200f\u2060").strip()

    if not (s.startswith("{") and s.endswith("}")):
        raise ValueError("LLM_OUTPUT_NOT_PURE_JSON: ответ не является чистым JSON-объектом")

    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM_OUTPUT_INVALID_JSON: {e}") from e


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

    # 3) вызвать LLM
    llm_text = run_llm(request_text)

    # 4) сохранить сырой ответ (на случай разборок)
    write_text(raw_out_path, llm_text)

    # 5) распарсить строго JSON
    arch_decision = extract_json_strict(llm_text)

    # 6) минимальная sanity-проверка по контракту
    if arch_decision.get("pass") != "DECIDE":
        raise ValueError("ARCH_DECISION_INVALID: поле pass должно быть 'DECIDE'")

    # 7) зафиксировать task_id в snapshot (контракт: EXECUTE должен проверять соответствие input/task.json)
    arch_decision["task_id"] = task_id

    # 8) зафиксировать fingerprints системных prompt-файлов в snapshot (immutable by hash)
    meta = dict(arch_decision.get("meta", {}))

    meta["prompts_fingerprint"] = {
        "pass_1_decide_md": fingerprint_file(PASS_1_PROMPT_PATH),
        "pass_2_execute_core_md": fingerprint_file(PASS_2_PROMPT_CORE_PATH),
        "pass_2_execute_anchors_md": fingerprint_file(PASS_2_PROMPT_ANCHORS_PATH),
    }
    arch_decision["meta"] = meta

    # 9) зафиксировать immutable_fingerprint в snapshot (архитектурный контракт)
    arch_decision["immutable_fingerprint"] = fingerprint_immutable_architecture(arch_decision)

    # 10) сохранить snapshot+canonical+hash
    paths = save_snapshot(
        arch_decision_json=arch_decision,
        snapshots_dir=SNAPSHOTS_DIR,
        task_id=task_id,
    )

    # 11) вывести результат строго по контракту
    emit(
        LEVEL_PASS,
        "DECIDE_OK",
        "snapshot created (snapshot/canonical/hash written)",
        evidence={
            "snapshot": str(paths.snapshot_path),
            "canonical": str(paths.canonical_path),
            "hash_file": str(paths.hash_path),
        },
    )



def approval_file_for_hash(hash_hex: str) -> Path:
    return APPROVALS_DIR / f"{hash_hex}.approved"


def cmd_approve(snapshot_id: str) -> None:
    """
    Механизация human step: создать файл approvals/<hash>.approved
    по уже существующему state/snapshots/<snapshot_id>.sha256.

    ВАЖНО:
    - НЕ проверяет корректность snapshot
    - НЕ выполняет verify / gate
    - НЕ принимает решение "можно ли approve"
    """
    hash_path = SNAPSHOTS_DIR / f"{snapshot_id}.sha256"
    if not hash_path.exists():
        raise FileNotFoundError(f"Hash file не найден: {hash_path}")

    hash_hex = read_sha256_file(hash_path)
    if not hash_hex:
        raise ValueError(f"EMPTY_SHA256_FILE: {hash_path}")

    APPROVALS_DIR.mkdir(parents=True, exist_ok=True)
    approval_path = approval_file_for_hash(hash_hex)

    # идемпотентность: если уже есть — не падаем
    if approval_path.exists():
        emit(
            LEVEL_PASS,
            "APPROVE_OK",
            "approval already exists (idempotent)",
            evidence={"approval": str(approval_path)},
        )
        return

    approval_path.write_text("approved\n", encoding="utf-8")

    emit(
        LEVEL_PASS,
        "APPROVE_OK",
        "approval created",
        evidence={"approval": str(approval_path)},
    )


def preflight_execute_gate(snapshot_path: Path) -> tuple[Dict[str, Any], str, str]:
    """
    PRE-FLIGHT gate before PASS_2.
    Any failure here MUST abort before any LLM call.
    Returns:
      - arch_decision_json (validated, immutable)
      - hash_hex           (snapshot identity, derived)
      - immutable_fp       (authoritative, validated)
    """

    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot не найден: {snapshot_path}")

    hash_path = Path(str(snapshot_path).replace(".snapshot.json", ".sha256"))
    if not hash_path.exists():
        raise FileNotFoundError(f"Hash file не найден: {hash_path}")

    ok, msg = verify_snapshot_files(snapshot_path, hash_path)
    if not ok:
        raise ValueError(f"VERIFY_FAIL: {msg}")

    hash_hex = read_sha256_file(hash_path)
    if not hash_hex:
        raise ValueError(f"EMPTY_SHA256_FILE: {hash_path}")

    # STOP-CONDITION: EXECUTE запрещён после MERGE
    # Authoritative source of truth: state/merges/by_run/<task_id>__<hashprefix>.merge_id
    arch_decision = read_json(snapshot_path)
    task_id = arch_decision.get("task_id") or "task"
    hashprefix = hash_hex[:12]

    merges_by_run_dir = STATE_DIR / "merges" / "by_run"
    merge_ptr = merges_by_run_dir / f"{task_id}__{hashprefix}.merge_id"

    if merge_ptr.exists():
        merge_id = merge_ptr.read_text(encoding="utf-8").strip()
        raise LifecycleViolation(
            f"STOP_CONDITION: EXECUTE_FORBIDDEN_AFTER_MERGE (merge_id={merge_id})"
        )


    # README требует immutable_fingerprint как обязательный маркер snapshot-совместимости.
    # Если его нет — это BLOCKER до любого PASS_2.
    if "immutable_fingerprint" not in arch_decision:
        raise ValueError("IMMUTABLE_FINGERPRINT_MISSING_IN_SNAPSHOT")

    # IMMUTABILITY ENFORCEMENT: immutable_fingerprint must match computed value
    immutable_fp = fingerprint_immutable_architecture(arch_decision)
    if arch_decision.get("immutable_fingerprint") != immutable_fp:
        raise ValueError(
            f"IMMUTABLE_FINGERPRINT_MISMATCH: snapshot={arch_decision.get('immutable_fingerprint')} computed={immutable_fp}"
        )


    # IMMUTABILITY ENFORCEMENT: prompt fingerprints must match snapshot
    snap_fp = (arch_decision.get("meta", {}) or {}).get("prompts_fingerprint", {}) or {}
    cur_fp = {
        "pass_1_decide_md": fingerprint_file(PASS_1_PROMPT_PATH),
        "pass_2_execute_core_md": fingerprint_file(PASS_2_PROMPT_CORE_PATH),
        "pass_2_execute_anchors_md": fingerprint_file(PASS_2_PROMPT_ANCHORS_PATH),
    }

    missing_keys = [k for k in cur_fp.keys() if k not in snap_fp]
    if missing_keys:
        raise ValueError(f"PROMPT_FINGERPRINT_MISSING_IN_SNAPSHOT: missing={missing_keys}")

    mismatched = {
        k: {"snapshot": snap_fp.get(k), "current": cur_fp.get(k)}
        for k in cur_fp.keys()
        if snap_fp.get(k) != cur_fp.get(k)
    }
    if mismatched:
        raise ValueError(f"PROMPT_FINGERPRINT_MISMATCH: {mismatched}")

    return arch_decision, hash_hex, immutable_fp

def cmd_execute(snapshot_path: str, stage: str, force: bool = False) -> None:
    """
    PASS_2 выполняется ТОЛЬКО если PRE-FLIGHT gate пройден (до любого вызова LLM).
    """
    snap_path = Path(snapshot_path)

    # PRE-FLIGHT gate: fail-fast before any LLM call
    arch_decision, hash_hex, immutable_fp = preflight_execute_gate(snap_path)

    # Загружаем то, что заморожено
    task = read_json(TASK_JSON_PATH)

    # FAIL-FAST: task_id в input должен совпадать с snapshot
    snapshot_task_id = arch_decision.get("task_id")
    runtime_task_id = task.get("task_id")

    if snapshot_task_id != runtime_task_id:
        raise ValueError(
            f"TASK_ID_MISMATCH: snapshot={snapshot_task_id} runtime={runtime_task_id}"
        )

    if stage == "core":
        pass_2_prompt = read_text(PASS_2_PROMPT_CORE_PATH)
    elif stage == "anchors":
        pass_2_prompt = read_text(PASS_2_PROMPT_ANCHORS_PATH)
    else:
        raise ValueError(f"UNKNOWN_STAGE: {stage}")


    # Собираем запрос PASS_2
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

    # 1) подготовить выходную директорию (и запретить перезапись без явного --force)
    out_dir = OUTPUTS_DIR / "pass_2" / f"{task.get('task_id','task')}__{hash_hex[:12]}" / stage

    if out_dir.exists() and any(out_dir.iterdir()):
        if not force:
            raise FileExistsError(
                f"OUTPUT_DIR_EXISTS: {out_dir} (refusing to overwrite; re-run with --force to wipe and overwrite)"
            )
        # --force: wipe stage dir to avoid mixing old/new artifacts
        shutil.rmtree(out_dir)

    out_dir.mkdir(parents=True, exist_ok=True)

    llm_text = run_llm(request_text)

    # 2) сохранить сырой ответ
    raw_path = out_dir / "execution_result.raw.txt"

    write_text(raw_path, llm_text)

    # 3) строго распарсить JSON (без текста до/после)
    exec_json = extract_json_strict(llm_text)

    # Оркестратор сам фиксирует отпечаток immutable (LLM не управляет этим)
    exec_json["immutable_fingerprint"] = immutable_fp

    # Защита от подмены: deliverables не должны содержать immutable_architecture
    deliverables = exec_json.get("deliverables", {})
    if "immutable_architecture" in deliverables:
        raise ValueError("IMMUTABILITY_VIOLATION: deliverables содержит immutable_architecture")


    # 4) сохранить нормальный JSON
    json_path = out_dir / "execution_result.json"
    write_json_pretty(json_path, exec_json)

    # 5) разложить deliverables по отдельным файлам
    deliverables = exec_json.get("deliverables", {})
    if stage == "core":
        parts = {
            "semantic_enrichment": "semantic_enrichment.json",
            "keywords": "keywords.json",
            "patient_questions": "patient_questions.json",
        }
    elif stage == "anchors":
        parts = {
            "anchors": "anchors.json",
        }
    else:
        raise ValueError(f"UNKNOWN_STAGE: {stage}")


    for key, filename in parts.items():
        part_path = out_dir / filename
        write_json_pretty(part_path, deliverables.get(key, {}))

    # NOTE: Post-check is executed after CORE+ANCHORS merge (next step).
    # Running it per-stage would fail by design (missing stage-specific deliverables).
    
    emit(
        LEVEL_PASS,
        "EXECUTE_OK",
        "stage executed; artifacts written",
        evidence={"stage": stage, "out_dir": str(out_dir)},
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="orchestrator", description="Two-pass LLM workflow orchestrator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("decide", help="Run PASS_1 (DECIDE)")

    p_approve = sub.add_parser("approve", help="Approve a snapshot (human step, mechanized)")
    p_approve.add_argument("--snapshot", required=True, help="snapshot_id (without extensions)")

    p_execute = sub.add_parser("execute", help="Run PASS_2 (EXECUTE) with verified+approved snapshot")
    p_execute.add_argument("--snapshot", required=True, help="Path to *.snapshot.json")
    p_execute.add_argument(
        "--stage",
        choices=["core", "anchors"],
        required=True,
        help="PASS_2 stage: core or anchors"
    )
    p_execute.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing outputs for this stage (DANGEROUS; wipes stage dir first)"
    )


    args = parser.parse_args(argv)

    try:
        if args.cmd == "decide":
            cmd_decide()
        elif args.cmd == "approve":
            cmd_approve(args.snapshot)
        elif args.cmd == "execute":
            cmd_execute(args.snapshot, args.stage, args.force)
        else:
            raise ValueError(f"Unknown command: {args.cmd}")
        return EXIT_PASS
    except LifecycleViolation as e:
        emit(LEVEL_BLOCKER, "LIFECYCLE_VIOLATION", str(e))
        return EXIT_BLOCKER
    except Exception as e:
        emit(LEVEL_FAIL, "ORCHESTRATOR_FAILED", str(e))
        return EXIT_FAIL




if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
