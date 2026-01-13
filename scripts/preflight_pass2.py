# scripts/preflight_pass2.py
from __future__ import annotations

import json
import sys
from pathlib import Path
import hashlib

from scripts.state_utils import read_sha256_file, fingerprint_file


# NOTE:
# - Это PRE-FLIGHT до любого вызова LLM.
# - Никакой "проверки внутри LLM".
# - Любой FAIL = BLOCKER и exit(2).

STATE_DIR = Path("state")
APPROVALS_DIR = STATE_DIR / "approvals"

def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _require(condition: bool, msg: str) -> None:
    if not condition:
        print(f"[BLOCKER] LIFECYCLE_VIOLATION: {msg}", file=sys.stderr)
        raise SystemExit(2)


def _require_approved(snapshot_sha: str) -> None:
    approval_file = APPROVALS_DIR / f"{snapshot_sha}.approved"
    _require(approval_file.exists(), f"Нет approve-файла: {approval_file}")


def _require_immutable_fingerprint(snapshot: dict) -> None:
    fp = snapshot.get("immutable_fingerprint")
    _require(isinstance(fp, str) and fp.strip(), "В snapshot отсутствует immutable_fingerprint.")


def _require_prompt_fingerprints(snapshot: dict) -> None:
    """
    Минимальный enforcement:
    - snapshot должен содержать sha256 промптов PASS_2
    - текущие файлы в репе должны совпадать с ними

    IMPORTANT:
    Здесь используются самые ожидаемые поля. Если у тебя ключи названы иначе,
    меняешь только mapping ниже, логика остаётся той же.
    """
    prompts = (snapshot.get("meta", {}) or {}).get("prompts_fingerprint") or snapshot.get("prompts") or snapshot.get("prompt_fingerprints") or {}
    _require(isinstance(prompts, dict), "Snapshot.prompts/prompt_fingerprints должен быть dict.")

    # ---- MAPPING: canonical source = snapshot["meta"]["prompts_fingerprint"] ----
    expected = {
        "pass_2_execute_core": prompts.get("pass_2_execute_core_md") or prompts.get("pass_2_execute_core_sha256") or prompts.get("pass_2_execute_core"),
        "pass_2_execute_anchors": prompts.get("pass_2_execute_anchors_md") or prompts.get("pass_2_execute_anchors_sha256") or prompts.get("pass_2_execute_anchors"),
    }

    # ----------------------------------------------------------------------

    _require(expected["pass_2_execute_core"], "В snapshot нет sha256 для prompts/pass_2_execute_core.md")
    _require(expected["pass_2_execute_anchors"], "В snapshot нет sha256 для prompts/pass_2_execute_anchors.md")

    core_path = Path("prompts") / "pass_2_execute_core.md"
    anchors_path = Path("prompts") / "pass_2_execute_anchors.md"

    _require(core_path.exists(), f"Не найден файл промпта: {core_path}")
    _require(anchors_path.exists(), f"Не найден файл промпта: {anchors_path}")

    actual_core = fingerprint_file(core_path)
    actual_anchors = fingerprint_file(anchors_path)

    _require(
        actual_core == expected["pass_2_execute_core"],
        f"Несовпадение fingerprint для {core_path}: snapshot={expected['pass_2_execute_core']} repo={actual_core}",
    )
    _require(
        actual_anchors == expected["pass_2_execute_anchors"],
        f"Несовпадение fingerprint для {anchors_path}: snapshot={expected['pass_2_execute_anchors']} repo={actual_anchors}",
    )


def _require_gate_snapshot_ok(snapshot_path: Path) -> None:
    """
    Самый минимальный способ: переиспользовать твой существующий gate_snapshot как subprocess.
    Он уже должен падать ненулевым кодом на FAIL.

    Если у тебя gate_snapshot доступен как import-функция, можешь заменить на import.
    """
    import subprocess

    # В README ты явно показываешь вызов `python scripts/gate_snapshot.py <snapshot_id>`
    # но orchestrator execute обычно получает путь к snapshot.json.
    # Поэтому: пробуем сначала передать snapshot_id из имени файла, иначе путь.
    arg = snapshot_path.stem.replace(".snapshot", "")
    cmd = [sys.executable, "scripts/gate_snapshot.py", arg]
    p = subprocess.run(cmd)
    _require(p.returncode == 0, f"gate_snapshot FAIL for canonical snapshot_id={arg} (see stderr).")


def _require_immutable_fingerprint_matches(snapshot: dict) -> None:
    """
    Сильный enforcement: immutable_fingerprint должен совпадать с вычисленным внешним кодом.
    Мы НЕ придумываем алгоритм заново: переиспользуем то, что уже используется в MERGE.
    """
    try:
        from scripts.merge_pass2 import compute_immutable_fingerprint  # ожидаемая точка истины
    except Exception as e:
        _require(False, f"Не удалось импортировать compute_immutable_fingerprint из scripts.merge_pass2: {e}")

    expected = snapshot.get("immutable_fingerprint")
    actual = compute_immutable_fingerprint(snapshot)
    _require(
        actual == expected,
        f"immutable_fingerprint mismatch: snapshot={expected} computed={actual}",
    )


def run(snapshot_path_str: str) -> None:
    snapshot_path = Path(snapshot_path_str)
    _require(snapshot_path.exists(), f"Snapshot файл не найден: {snapshot_path}")

    snapshot = _load_json(snapshot_path)

    # 1) Корректность snapshot (структура+canonical/sha256) через существующий gate
    _require_gate_snapshot_ok(snapshot_path)

    # 2) Approval (sha256 берём из canonical .sha256 файла рядом со snapshot)
    sha_path = Path(str(snapshot_path).replace(".snapshot.json", ".sha256"))
    _require(sha_path.exists(), f"Hash file не найден: {sha_path}")
    snapshot_sha = read_sha256_file(sha_path)
    _require(isinstance(snapshot_sha, str) and len(snapshot_sha) == 64, "Snapshot sha256 отсутствует или некорректен.")

    _require_approved(snapshot_sha)

    # 3) Immutability (fingerprints промптов)
    _require_prompt_fingerprints(snapshot)

    # 4) immutable_fingerprint присутствует и совпадает с вычисленным
    _require_immutable_fingerprint(snapshot)
    _require_immutable_fingerprint_matches(snapshot)

    print("[PASS] OK: pre-flight checks passed")