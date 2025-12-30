<!--
ФАЙЛ: prompts/pass_2_execute.md
НАЗНАЧЕНИЕ: PASS_2 / EXECUTE — исполнение по зафиксированной архитектуре из ARCH_DECISION_JSON.
ИСПОЛЬЗУЕТСЯ: scripts/orchestrator.py командой execute (только после verify + approval).
ВХОД: TASK_JSON + ARCH_DECISION_JSON (подаются Python-скриптом).
ВЫХОД: Финальные артефакты (семантика/анкоры/вопросы/тексты/таблицы) строго в рамках разрешённых mutable-полей.
ЗАПРЕЩЕНО: менять immutable_architecture, пересобирать hub_chain, менять owner_status/canonical_home, “улучшать” структуру.
КТО МЕНЯЕТ: человек (ты). LLM НЕ должна модифицировать этот файл.
-->

# PASS_2 / EXECUTE

## ROLE
You execute the task using a LOCKED architecture snapshot (ARCH_DECISION_JSON).

## INPUT CONTRACT
You will receive TWO inputs inside one request:
1) TASK_JSON
2) ARCH_DECISION_JSON (LOCKED snapshot from PASS_1)

Rules:
- You MUST treat ARCH_DECISION_JSON.immutable_architecture as immutable.
- You MUST NOT modify hub_chain, node_registry structure, owner_map, linking_matrix_skeleton.
- You MAY only generate mutable deliverables (semantics, keywords, anchors, patient questions, final texts/tables) that fit the locked architecture.

## HARD BANS (CRITICAL)
Never:
- propose architecture changes
- reorder hub_chain
- introduce new nodes not present in node_registry
- change owner_status or canonical_home
- output self-audit or validation steps
- output any text about immutability checks (Python handles it)

## OUTPUT FORMAT
Return a single JSON object named EXECUTION_RESULT_JSON.
No explanations. No markdown. No code fences.

## EXECUTION_RESULT_JSON STRUCTURE
The JSON MUST have:
- "task": copy of TASK_JSON core fields
- "used_snapshot_hash": string (leave empty, Python may fill later)
- "deliverables": object with:
  - "semantic_enrichment": per-node intent + coverage notes (no long texts)
  - "keywords": per-node keyword groups
  - "anchors": per allowed link pair (from_node_id,to_node_id) propose anchor variants
  - "patient_questions": per-node Q&A questions list
  - "final_artifacts": optional texts/tables placeholders or short drafts

## QUALITY RULES
- Keep outputs aligned with: domain, region, strategic_goal, main_topic.
- No keyword stuffing.
- Use node_id to reference nodes (no free-form naming).
