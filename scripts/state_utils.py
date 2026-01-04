"""
ФАЙЛ: scripts/state_utils.py
НАЗНАЧЕНИЕ: Внешняя фиксация immutability: canonicalize → hash → save/load → verify.
ИСПОЛЬЗУЕТСЯ: scripts/orchestrator.py (decide/execute).
ДОСТУП LLM: запрещён (LLM не проверяет и не “контролирует” неизменность).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple


def canonicalize_json(obj: Any) -> str:
    """
    Канонизация JSON:
    - сортировка ключей
    - стабильные разделители
    - без ASCII-эскейпа (чтобы русский не превращался в \\uXXXX)
    """
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_sha256_file(hash_path: Path) -> str:
    """
    Читает sha256 из файла.
    Контракт: берём первую непустую строку, чтобы комментарии/мусор ниже не ломали логику.
    """
    raw = hash_path.read_text(encoding="utf-8")
    for line in raw.splitlines():
        s = line.strip()
        if s:
            return s
    return ""

def canonicalize_text(text: str) -> str:
    """
    Канонизация текста для детерминированного fingerprint:
    - нормализуем переносы строк
    - убираем BOM
    """
    s = text.replace("\r\n", "\n").replace("\r", "\n")
    if s.startswith("\ufeff"):
        s = s.lstrip("\ufeff")
    return s

def fingerprint_file(path: Path) -> str:
    """
    Fingerprint файла как sha256 канонизированного текста.
    Используется для фиксации версий prompt-файлов в snapshot.
    """
    raw = path.read_text(encoding="utf-8")
    return sha256_hex(canonicalize_text(raw))

def compute_snapshot_hash(arch_decision_json: Dict[str, Any]) -> Tuple[str, str]:
    """
    Возвращает (canonical_json, sha256_hex).
    """
    canonical = canonicalize_json(arch_decision_json)
    digest = sha256_hex(canonical)
    return canonical, digest


@dataclass(frozen=True)
class SnapshotPaths:
    snapshot_path: Path
    canonical_path: Path
    hash_path: Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def save_snapshot(
    arch_decision_json: Dict[str, Any],
    snapshots_dir: Path,
    task_id: str,
    hash_prefix_len: int = 12,
) -> SnapshotPaths:
    """
    Сохраняет:
    - snapshot JSON (как есть, но с meta.created_utc заполненным)
    - canonical JSON (канонизированный текст)
    - hash (sha256)

    Имена файлов привязаны к task_id и hash-prefix, чтобы было удобно версионировать.
    """
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    # Заполняем мету здесь, а не в LLM
    arch = dict(arch_decision_json)  # shallow copy
    meta = dict(arch.get("meta", {}))
    meta.setdefault("created_utc", utc_now_iso())
    arch["meta"] = meta

    canonical, digest = compute_snapshot_hash(arch)
    prefix = digest[:hash_prefix_len]

    base = f"{task_id}__{prefix}"
    snapshot_path = snapshots_dir / f"{base}.snapshot.json"
    canonical_path = snapshots_dir / f"{base}.canonical.json"
    hash_path = snapshots_dir / f"{base}.sha256"

    snapshot_path.write_text(json.dumps(arch, ensure_ascii=False, indent=2), encoding="utf-8")
    canonical_path.write_text(canonical, encoding="utf-8")
    hash_path.write_text(digest + "\n", encoding="utf-8")

    return SnapshotPaths(snapshot_path=snapshot_path, canonical_path=canonical_path, hash_path=hash_path)


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_snapshot_content(arch_decision_json: Dict[str, Any], expected_sha256: str) -> Tuple[bool, str]:
    """
    Проверяет, что hash совпадает с канонизированной формой.
    Возвращает (ok, message).
    """
    canonical, digest = compute_snapshot_hash(arch_decision_json)
    if digest != expected_sha256:
        return False, f"HASH_MISMATCH: expected={expected_sha256} actual={digest}"
    return True, "OK"


def verify_snapshot_files(snapshot_path: Path, hash_path: Path) -> Tuple[bool, str]:
    """
    Проверка snapshot на диске:
    - читает snapshot JSON
    - читает hash
    - пересчитывает hash
    """
    arch = load_json(snapshot_path)
    expected = read_sha256_file(hash_path)
    if not expected:
        return False, f"EMPTY_SHA256_FILE: {hash_path}"
    ok, msg = verify_snapshot_content(arch, expected)
    return ok, msg

def fingerprint_immutable_architecture(arch_decision_json: Dict[str, Any]) -> str:
    """
    Отпечаток immutable_architecture.
    Используется, чтобы гарантировать: PASS_2 работает строго по зафиксированному скелету.
    """
    imm = arch_decision_json.get("immutable_architecture", {})
    canonical = canonicalize_json(imm)
    return sha256_hex(canonical)
