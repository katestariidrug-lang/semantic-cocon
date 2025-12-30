<!--
ФАЙЛ: prompts/pass_1_decide.md
НАЗНАЧЕНИЕ: PASS_1 / DECIDE — принять архитектурные решения и вернуть ARCH_DECISION_JSON.
ИСПОЛЬЗУЕТСЯ: scripts/orchestrator.py командой decide.
ВХОД: TASK_JSON + ARCH_SCHEMA_JSON (оба подаются Python-скриптом).
ВЫХОД: ТОЛЬКО JSON-объект ARCH_DECISION_JSON (без текста до/после).
ЗАПРЕЩЕНО: семантика, ключевые слова, анкоры, вопросы пациента, финальные тексты/таблицы, self-audit, контроль неизменности.
КТО МЕНЯЕТ: человек (ты). LLM НЕ должна модифицировать этот файл.
-->

# PASS_1 / DECIDE

## ROLE
You generate architectural decisions only.

## YOU MAY
- Define structural entities and their relations
- Define hierarchy and ownership
- Define immutable architecture skeleton

## YOU MUST NOT
- Generate keywords
- Generate semantic content
- Generate texts, questions, tables
- Perform validation or self-audit
- Enforce immutability
- Abort execution

## INPUT CONTRACT
You will receive TWO inputs inside one request:
1) TASK_JSON: the task input (domain, region, strategic_goal, main_topic, etc.)
2) ARCH_SCHEMA_JSON: canonical structure for ARCH_DECISION_JSON

Rules:
- You MUST copy TASK_JSON fields into ARCH_DECISION_JSON.task (task_id, domain, region, strategic_goal, main_topic).
- You MUST follow ARCH_SCHEMA_JSON structure EXACTLY.
- You MUST output ONLY keys that exist in ARCH_SCHEMA_JSON (except you may fill empty strings/arrays with values).

## HARD BANS (CRITICAL)
Never output:
- explanations
- markdown
- code fences (``` or ~~~)
- comments
- any text before/after the JSON
- extra keys not present in ARCH_SCHEMA_JSON

Never generate:
- keywords or keyword lists
- anchors, anchor texts, internal link texts
- patient questions
- semantic enrichment
- final texts, paragraphs, tables (content)

## ARCHITECTURE RULES
Fill ONLY the immutable architecture skeleton:

- immutable_architecture.hub_chain:
  Ordered list of node_id representing the main navigation spine.
  Node IDs MUST exist in node_registry.

- immutable_architecture.node_registry:
  List of nodes following immutable_architecture.node_schema_min.
  Provide only structural fields:
  node_id, node_type, title (generic), intent (generic), owner_status, canonical_home, children (node_id list or nested nodes).
  IMPORTANT: title and intent must be structural/generic (no keyword stuffing, no content).

- immutable_architecture.owner_map:
  List mapping node_id -> owner_status and canonical_home.
  MUST be consistent with node_registry.

- immutable_architecture.linking_matrix_skeleton:
  List of allowed internal links as pairs (from_node_id, to_node_id).
  NO anchors, NO link text, NO semantics.

## OUTPUT FORMAT (STRICT)
Return ONLY one JSON object: ARCH_DECISION_JSON.

If you output anything else (any text before/after JSON, markdown, code fences), the run is invalid.

## OUTPUT CONTENT RULES
- "pass" MUST be "DECIDE".
- "version" MUST be "1.0" unless TASK_JSON explicitly overrides it.
- "constraints" MUST match TASK_JSON.constraints when provided; otherwise keep schema defaults.
- "meta.created_utc" MUST be an empty string (Python will fill it).
- "meta.decide_model" MUST be an empty string (Python will fill it).
- "meta.notes" MAY be empty or short, but do not add narrative.

## LANGUAGE CONSTRAINT (CRITICAL)

Все семантические интенты, логика разбиения темы, группировка узлов и смысловые названия
должны формироваться для русскоязычной аудитории и русской поисковой выдачи (Россия).

Это не влияет на формат JSON и enum’ы, но влияет на архитектурные решения.

## ARCHITECTURE MINIMUM (HARD REQUIREMENTS)

Ты ОБЯЗАН построить архитектуру, подходящую для strategic_goal=topical_authority.

Минимум:
- node_registry: НЕ МЕНЕЕ 18 узлов (HUB+SPOKE+SUPPORT суммарно)
- Ровно 1 HUB (node_type="HUB")
- SPOKE: НЕ МЕНЕЕ 10 (node_type="SPOKE")
- SUPPORT: НЕ МЕНЕЕ 7 (node_type="SUPPORT")

Покрытие интентов (обязательные группы SPOKE/SUPPORT по теме "норма сахара в крови"):
- нормы по возрастам
- нормы при беременности (и смежно: гестационный диабет как SUPPORT или SPOKE)
- натощак / после еды / случайное измерение
- венозная vs капиллярная кровь
- единицы измерения и конверсия
- HbA1c как метрика контроля
- пороги предиабет/диабет и когда к врачу
- подготовка к анализу и типичные ошибки
- домашний контроль/глюкометр и погрешности
- причины отклонений и влияющие факторы
- маршрутизация: эндокринолог/обследования (SUPPORT)

Если ты не можешь выполнить минимум — верни JSON как обычно, НО заполни meta.notes причиной и всё равно выдай максимально близкую архитектуру.

## FINAL REMINDER
Return JSON only. No extra text.
