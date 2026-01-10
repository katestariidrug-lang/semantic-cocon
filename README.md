# semantic-cocon

## Назначение проекта

> Workflow для работы с LLM, где сначала принимаются архитектурные решения,
> затем выполняется строго ограниченная генерация структурированных артефактов,
> а результат можно проверить и воспроизвести.

⚠️ ЖЁСТКОЕ ОГРАНИЧЕНИЕ PASS_2

Проект **не предназначен для генерации публикуемого текста**.

Любая попытка генерации текстового контента в PASS_2
считается **нарушением архитектурного контракта проекта**.

## Stateless-природа LLM (жёсткий архитектурный контракт)

LLM в проекте **semantic-cocon является строго stateless-компонентом**.

## Статус архитектуры

Архитектурный контракт проекта зафиксирован и enforced кодом.

- PRE-FLIGHT gate перед PASS_2 — **обязателен**
- EXECUTE невозможен без approve, immutability и совпадения fingerprints
- PASS_2 физически не может стартовать при нарушении контракта
- Контроль выполняется внешним кодом, до любого вызова LLM

Проект находится в состоянии **строгого fail-fast исполнения архитектуры**.

Проект решает типичную проблему LLM-подходов:

- архитектура «плывёт» от запуска к запуску,
- результат невозможно воспроизвести,
- нельзя доказать, что выход соответствует принятой структуре.

В `semantic-cocon` это запрещено на уровне пайплайна.

---

## Быстрый старт (Quick Start)

Ниже — минимальный сценарий, который позволяет запустить проект и пройти весь цикл от архитектуры до проверенного результата.

```bash
# PASS_1 — принять архитектурные решения
python -m scripts.orchestrator decide

# (внутренняя техническая проверка snapshot выполняется orchestrator)
# пользователь НЕ запускает gate_snapshot вручную

# APPROVE — человеческий шаг (механизирован, но не автоматизирован)
python -m scripts.orchestrator approve --snapshot <snapshot_id>

# PASS_2A — CORE (per-node артефакты)
python -m scripts.orchestrator execute \
  --stage core \
  --snapshot state/snapshots/<snapshot_id>.snapshot.json

# PASS_2B — ANCHORS (link-level артефакты)
python -m scripts.orchestrator execute \
  --stage anchors \
  --snapshot state/snapshots/<snapshot_id>.snapshot.json

# MERGE — обязательный терминальный шаг (external, deterministic)
# Точный формат команды и аргументы см. в разделе
# «merge_pass2 — публичный CLI-контракт».

# POST-CHECK — выполняется ТОЛЬКО по merge_id (который печатает merge_pass2)
python scripts/check_deliverables.py <merge_id>

```

⚠️ Повторный запуск execute для того же snapshot и stage запрещён по умолчанию.
`--force` разрешает перегенерацию только ДО MERGE.
После MERGE любые execute запрещены **включая попытки запуска с флагом `--force`**.

Если любой шаг завершается с ошибкой — процесс считается неуспешным.

---

## Как понимать PASS_1 и PASS_2 (если коротко)

Проект намеренно разделяет работу с LLM на два разных шага, потому что это **разные по смыслу действия**.

### PASS_1 — DECIDE (принять решения)

На этом шаге мы решаем **ЧТО именно будем делать**, но ничего ещё не генерируем.

Проще всего думать о PASS_1 как о **плане или чертеже**:

- какие страницы (узлы) будут существовать;
- какая страница главная;
- какие страницы второстепенные;
- какие страницы вспомогательные;
- какие страницы должны ссылаться друг на друга.

На PASS_1 LLM **запрещено писать контент**. Она не генерирует тексты, вопросы или ключевые слова. Она только описывает структуру будущего результата.

Результат PASS_1 — это зафиксированная архитектура (snapshot). Контрактом (immutable) она становится после approve; до approve допускается только выпуск нового snapshot, а не правки старого.

### PASS_2 — EXECUTE (stage-based execution)

PASS_2 разделён на **два независимых stage**, каждый из которых исполняется отдельным вызовом LLM и имеет собственный контракт:

- **PASS_2A / CORE** — per-node артефакты
- **PASS_2B / ANCHORS** — link-level артефакты

Stage-split является архитектурным решением и не может быть отключён без изменения контракта проекта.

### Stage-level invariants (CORE ↔ ANCHORS)

Эти правила запрещают "подмешивание" архитектуры и обязанностей между стадиями.

**Invariant #1 — общий immutable snapshot**
CORE и ANCHORS обязаны исполняться по одному и тому же approved snapshot (одинаковый immutable_snapshot sha256 / snapshot identity в контексте запуска). Если snapshot различается — merge запрещён.

**Invariant #2 — архитектура immutable**
Между стадиями запрещено менять любые архитектурные поля snapshot, включая (не ограничиваясь):

- состав и типы узлов (node_registry, HUB/SPOKE/SUPPORT, уровни, hub_chain),
- связи (linking_matrix / edges),
- ownership/owner_status,
- canonical_home, recommended_variant_id и любые id/ключи, которые идентифицируют архитектуру.

**Invariant #3 — разделение ответственности**

- PASS_2A / CORE: генерирует только per-node артефакты `semantic_enrichment.json`, `keywords.json`, `patient_questions.json`.
- PASS_2B / ANCHORS: генерирует только link-level артефакт `anchors.json` (ровно 1 anchor на пару связей).
Любая попытка создать/изменить "чужие" артефакты считается нарушением контракта.

**Invariant #4 — no self-control**
LLM не выполняет merge, не запускает post-check и не решает "можно ли продолжать".
Post-check разрешён только после внешнего MERGE (external, deterministic).

⚠️ Это **единственный шаг всего workflow, на котором LLM генерирует выходные артефакты** (структурированные данные), а не принимает решения.

На этом шаге мы делаем ровно то, что уже решили на PASS_1.

LLM получает готовый "чертёж" (ARCH_DECISION_JSON),
который является ЕДИНСТВЕННЫМ источником истины для PASS_2, и:

⚠️ ЖЁСТКОЕ ОГРАНИЧЕНИЕ PASS_2

см. архитектурный контракт «Запрет на генерацию публикуемого контента» (раздел «ВАЖНО»).

PASS_2:

- генерирует **исключительно структурированные JSON-артефакты**;
- не генерирует публикуемый текст (страницы, блоки, абзацы, описания, черновики);
- не формирует контент, пригодный для прямой публикации;
- не вводит новые медицинские сущности
  (заболевания, симптомы, методы диагностики или лечения),
  отсутствующие в snapshot.

Любая попытка генерации текстового контента в PASS_2
считается **нарушением архитектурного контракта проекта**.

- заполняет каждый узел структурированными данными (deliverables),
  строго в рамках intent и границ узла, заданных в snapshot;
- генерирует вопросы, ключевые слова и анкоры (в JSON),
  не расширяя архитектуру и не добавляя новые смысловые области;
- собирает execution_result.json (служебный результат исполнения).

При этом LLM **не может**:

- добавлять новые страницы;
- удалять существующие;
- менять структуру;
- изменять связи между страницами.

PASS_2 — строгое исполнение зафиксированной архитектуры
(архитектурные решения на этом этапе запрещены).

### Почему это разделено

Если не разделять эти шаги, LLM будет одновременно:

- менять структуру,
- писать контент,
- «улучшать» задним числом.

В таком режиме результат невозможно проверить или воспроизвести.

Разделение PASS_1 / PASS_2:

- лишает LLM права самовольно менять структуру;
- даёт контроль над процессом;
- делает результат проверяемым.

---

## Единое правило кодировки (обязательный контракт)

Проект **semantic-cocon** обязан быть воспроизводимым на Windows / Linux / CI.
Для этого кодировка файлов **не может быть неявной**.

Важно: все JSON-файлы в проекте должны быть сохранены в UTF-8 **без BOM**.
UTF-8 с BOM считается некорректным вводом и приводит к FAIL при чтении/валидации JSON.

### Правило

1) Любые текстовые файлы читаются и пишутся **только** с явным указанием:

- `encoding="utf-8"` для `open(...)`
- `Path.read_text(encoding="utf-8")`
- `Path.write_text(..., encoding="utf-8")`

2) Любые JSON-файлы при записи обязаны сохранять Unicode-символы:

- `json.dump(..., ensure_ascii=False)` (вместе с `encoding="utf-8"` на файле)

### Запрещённые паттерны (нарушение контракта)

- `open(...)` без `encoding`
- `read_text()` / `write_text()` без `encoding="utf-8"`
- `json.dump()` без `ensure_ascii=False`

Нарушение этого правила считается **ошибкой воспроизводимости** и подлежит исправлению
в рамках проекта как инфраструктурный дефект (regression).

## Обязательные проверки (гейты/контракты)

### Smoke-test lifecycle (внешний гейт, обязательный)

Smoke-test обязан быть **детерминированным** и не зависеть от реального LLM-провайдера
(запускается в stub-режиме, без сети и внешних SDK).

Для этого используется stub-режим LLM-bridge:

- `SMOKE_TEST=1` — `scripts/llm_cli_bridge.py` не вызывает провайдера, а пишет минимально валидный JSON-ответ.

Пример (PowerShell):

```powershell
$env:SMOKE_TEST="1"
python scripts/smoke_test_lifecycle.py
```

Важно: smoke-test запускает subprocess-команды, поэтому `SMOKE_TEST=1` должен быть выставлен в окружении **процесса** до запуска smoke-test
(и до запуска `orchestrator`, если вы хотите принудительно работать в stub-режиме).

`.env` сам по себе не является “магией”: наличие строки `SMOKE_TEST=1` в `.env`
ничего не гарантирует, если процесс не делает `load_dotenv()` и если значение не унаследовано дочерними процессами.

Пример (PowerShell):

```powershell
$env:SMOKE_TEST="1"
python -m scripts.orchestrator decide
```

В проекте зафиксирован **внешний smoke-test lifecycle**, проверяющий
систему как «чёрный ящик» через CLI-интерфейсы.

Назначение smoke-test:

- защита lifecycle от регрессий;
- защита CLI-контракта (`[LEVEL] ERROR_CODE: message`);
- защита STOP-condition после MERGE;
- обнаружение нарушений порядка состояний.

Smoke-test **не использует внутренние API** и
работает исключительно через запуск CLI-команд.

Сценарий smoke-test (канонический):

1. `DECIDE` → snapshot
2. `APPROVE`
3. `EXECUTE / CORE`
4. `EXECUTE / ANCHORS`
5. `MERGE`
6. `POST-CHECK`
7. Повторный `EXECUTE` → **ожидается BLOCKER**

Smoke-test проверяет (без участия реального LLM, в stub-режиме):

- exit codes строго `0 / 1 / 2`;
- формат первой строки вывода: `[PASS] / [FAIL] / [BLOCKER]`;
- запрет `EXECUTE` после MERGE (STOP-condition).

Реализация:

- `scripts/smoke_test_lifecycle.py`

Удаление, игнорирование или «ослабление» smoke-test
считается нарушением архитектурного контракта проекта.

### Соглашение о проверках (архитектурный контракт)

Проверки являются частью архитектуры проекта. Их состав, имена, формат вывода и семантика статусов фиксируются в README и не могут изменяться неявно.

Любое изменение соглашения о проверках считается архитектурным изменением и требует пересмотра проекта.

#### Канонические файлы проверок

Следующие проверки считаются обязательными и каноническими:

- `scripts/gate_snapshot.py` — структурный гейт snapshot (валидность `immutable_architecture` в canonical snapshot).
- `scripts/orchestrator.py` — PRE-FLIGHT проверки перед PASS_2 (включая approve + immutability + fingerprints).
- `scripts/check_deliverables.py` — post-check результатов PASS_2 по `merge_id` (покрытие node_id, валидность anchors).

Переименование, удаление или подмена этих файлов без обновления соглашения считается нарушением архитектурного контракта.

#### Единый формат вывода проверок

Единый внешний CLI-контракт для всех гейтов/проверок:

```text
[LEVEL] ERROR_CODE: message
```

Где:

- LEVEL — PASS, FAIL, BLOCKER
- ERROR_CODE — канонический код ошибки (UPPER_SNAKE_CASE)
- message — человекочитаемое описание

#### Правила FAIL / BLOCKER

- `FAIL` = ошибка проверки/данных (exit code 1).
- `BLOCKER` = нарушение архитектурного/ lifecycle-контракта (exit code 2).
- Любой `FAIL` или `BLOCKER` останавливает pipeline.
- Статусы `WARNING`, `PARTIAL`, `SKIPPED`, `SOFT_FAIL` запрещены.
- Pipeline валиден **только если все шаги завершаются `PASS`**.

Проект не допускает частично корректных результатов.

---

## Lifecycle (канонический, enforced)

Lifecycle проекта является **конечным автоматом**.  
Переходы между состояниями жёстко зафиксированы и проверяются кодом.
Никакие шаги не могут быть выполнены «повторно» или «обходным путём».

Диаграмма состояний (каноническая):

```bash
DECIDE
↓
SNAPSHOT (canonical + sha256)
↓
APPROVE ← POINT OF NO RETURN
↓
EXECUTE / PASS_2A (CORE)
↓
EXECUTE / PASS_2B (ANCHORS)
↓
MERGE
↓
POST-CHECK

```

### Описание состояний и ограничений

| Состояние | Source of truth | Разрешено | Запрещено |
|----------|----------------|-----------|-----------|
| DECIDE | LLM output | Формирование ARCH_DECISION_JSON | Генерация контента |
| SNAPSHOT | `state/snapshots/*.snapshot.json` | Проверка, хеширование | Любые изменения архитектуры |
| APPROVE | `state/approvals/<hash>.approved` | EXECUTE | Изменение уже approved snapshot (разрешён только новый DECIDE → новый snapshot) |
| EXECUTE (CORE / ANCHORS) | `outputs/pass_2/<run_id>/` | Генерация артефактов | Изменение snapshot |
| MERGE | `state/merges/<merge_id>.json` | POST-CHECK | Любой EXECUTE |
| POST-CHECK | merge-state | Валидация deliverables | Генерация артефактов |

### Ключевые инварианты

- После **APPROVE** архитектура immutable.
- После **MERGE** любые попытки `EXECUTE` **обязаны завершаться ошибкой**.
- MERGE является **единственной точкой входа** для post-check.
- После MERGE источником истины считается **только** `state/merges/<merge_id>.json`.
- LLM никогда не участвует в MERGE и post-check.

Нарушение любого из этих правил считается **ошибкой lifecycle**, а не допустимым сценарием.

Запреты (не обсуждаются):

- post-check запрещён до MERGE (post-check выполняется только по merge_id).
- EXECUTE (CORE/ANCHORS) запрещён после MERGE для данного snapshot и данного merge_id, включая попытки запуска с флагом `--force`.
- MERGE запрещён, если immutable_fingerprint (и prompts fingerprints) не совпадают между snapshot и текущим окружением.

> Примечание: определения состояний см. в таблице «Описание состояний и ограничений» выше.

### Соответствие CLI-команд состояниям lifecycle

| Команда | Допустимое состояние | Проверяется | Поведение при нарушении |
|-------|---------------------|-------------|--------------------------|
| `python -m scripts.orchestrator decide` | DECIDE | — | BLOCKER |
| `python -m scripts.orchestrator execute --stage core` | APPROVE | approve + snapshot immutability | BLOCKER |
| `python -m scripts.orchestrator execute --stage anchors` | APPROVE | approve + snapshot immutability | BLOCKER |
| `python -m scripts.merge_pass2` | EXECUTE (CORE + ANCHORS завершены) | merge-state terminal + immutable_fingerprint | BLOCKER |
| `python scripts/check_deliverables.py <merge_id>` | MERGE | merge-state | BLOCKER |
| Любой `execute` после MERGE | ❌ запрещено | merge-state | BLOCKER (STOP-condition) |

Команды, вызванные вне допустимого состояния lifecycle,  
**обязаны завершаться ошибкой**, а не выполнять частичное действие.

### Точка невозврата

(см. раздел APPROVE)

### Что запрещено делать после approve

После `approve` запрещено:

- менять `node_registry`, типы узлов, `hub_chain`, `linking_matrix_skeleton`, ownership;
- менять любые поля, входящие в immutable-часть snapshot;
- менять `input/task.json`, если он считается источником для данного snapshot;
- изменять `prompts/pass_1_decide.md`, `prompts/pass_2_execute_core.md` или `prompts/pass_2_execute_anchors.md` **без выпуска нового snapshot и нового approve**;
- исполнять PASS_2, если hash / fingerprints не совпадают с зафиксированными в snapshot;
- вручную редактировать файлы в `outputs/` (такие результаты считаются архитектурно недействительными).

Единственный допустимый способ "что-то поправить" после approve:
**выпустить новый snapshot (DECIDE заново) и получить новый approve.**

## Инварианты проекта

Следующие правила являются **архитектурным контрактом** проекта и не подлежат «аккуратным улучшениям» или смягчению формулировок:

- PASS_1 и PASS_2 никогда не объединяются.
- PASS_2 не может менять архитектуру snapshot.
- Snapshot после approve считается immutable.
- Snapshot валиден только вместе с исходным `input/task.json`  и зафиксированными версиями системных prompt-файлов.
- Любой результат без post-check считается недействительным.
- LLM не является источником истины о состоянии проекта.
- LLM запрещено генерировать публикуемый контент.
- PASS_2 допускает только структурированные JSON-артефакты.
- Ручное редактирование любых файлов в `outputs/` запрещено.
- Повторная генерация артефактов PASS_2 запрещена без явного `--force`.

Любое изменение, нарушающее эти правила, считается архитектурной ошибкой.

Это означает:

- LLM **не хранит состояние** между шагами, вызовами или фазами workflow.
- LLM **не обладает памятью о предыдущих шагах**, если соответствующее состояние
  не передано ей явно во входных данных текущего шага.
- LLM **не может быть источником истины** о прошлом, текущем или будущем состоянии pipeline.

### Где живёт состояние проекта

Единственным источником истины о состоянии проекта являются:

- каталог `state/`, включая:
  - `state/snapshots/`
  - `state/approvals/`
- результаты проверок, выполняемых кодом (`gate`, `post-check`).

LLM **не имеет права**:

- утверждать, что предыдущий шаг был выполнен успешно;
- предполагать наличие approve без явного approval-файла;
- считать snapshot актуальным без его явной передачи;
- опираться на историю диалога как на подтверждение состояния.

### Запрещённые предположения

Считается архитектурным нарушением, если LLM:

- использует формулировки вида:
  - «как мы уже сделали ранее»,
  - «на прошлом шаге было подтверждено»,
  - «мы уже зафиксировали архитектуру» — без переданного snapshot;
- продолжает workflow без явного сигнала пользователя;
- принимает решения на основе неявных предположений о прошлом состоянии.

### Следствие

Каждый шаг workflow LLM обязана рассматривать **как изолированный и не связанный с предыдущими**, если состояние не передано явно через:

- snapshot,
- входной JSON,
- аргументы команды,
- или иные формализованные артефакты.

Любая логика, основанная на «памяти» или «контексте диалога», считается недействительной.

## Общая архитектура workflow

Workflow состоит из **двух жёстко разделённых проходов**:

- **PASS_1 — DECIDE**: принятие архитектурных решений
- **PASS_2 — EXECUTE**: исполнение строго по зафиксированной архитектуре

Полная последовательность состояний и запреты зафиксированы в разделе  
**Lifecycle (канонический, enforced)**.

Каждый шаг либо проходит валидацию, либо останавливает процесс.

---

## PASS_1: DECIDE

### Назначение

PASS_1 **не генерирует контент**.
Он принимает **архитектурные решения**, которые фиксируются в snapshot и становятся контрактом (immutable) **после approve**.

---

### `prompts/pass_1_decide.md` — контракт архитектурного мышления

`pass_1_decide.md` — это **канонический системный промпт PASS_1**, отвечающий
**исключительно** за принятие архитектурных решений.

Он используется **только** на этапе `DECIDE`
и **никогда** не участвует в генерации семантики или контента.

#### Что делает этот промпт

`pass_1_decide.md` определяет:

- состав и структуру `node_registry`;
- типы узлов (`HUB / SPOKE / SUPPORT`);
- `hub_chain` — основную навигационную цепочку;
- `linking_matrix_skeleton` — допустимые внутренние связи;
- ownership узлов (`owner_status`, `canonical_home`);
- архитектурные альтернативы (forced contradiction), если они предусмотрены схемой;
- архитектурные якоря (в частности, `clinical_entity_registry`).

Если схема ARCH_DECISION_JSON предусматривает `salient_terms`
в составе клинических сущностей, они рассматриваются как
архитектурный механизм различения медицинских интентов
и предотвращения скрытой каннибализации узлов.

`salient_terms` в PASS_1:

- не являются семантикой;
- не используются для генерации ключевых слов или контента;
- служат исключительно для архитектурного разведения сущностей и узлов.

Если `clinical_entity_registry` присутствует в схеме ARCH_DECISION_JSON,
он является обязательным архитектурным якорем:
архитектура формируется ИСКЛЮЧИТЕЛЬНО на основе сущностей,
описанных в этом реестре.

Важно:
PASS_1 не просто "описывает структуру",
а жёстко ограничивает допустимую архитектуру правилами проектирования
(медицинская валидность, запрет ассоциативного расширения,
анти-каннибализация на уровне сущностей).

Результатом работы промпта является **только** `ARCH_DECISION_JSON`, который далее:

- канонизируется;
- хешируется;
- сохраняется как snapshot-кандидат;
- становится immutable **только после approve**.

#### Чего **никогда** не должно быть в `pass_1_decide.md`

Следующие вещи являются **архитектурно запрещёнными** для PASS_1
и считаются нарушением контракта проекта:

- генерация любого контента:
  - текстов страниц,
  - абзацев,
  - описаний,
  - черновиков;
- генерация семантики:
  - ключевых слов,
  - анкоров,
  - вопросов пациента,
  - semantic enrichment;
- self-audit и внутренняя валидация:
  - «проверь, что…»,
  - «если нарушено…»,
  - «убедись, что…»,
  - «остановись, если…»;
- контроль состояния или жизненного цикла:
  - проверка approve,
  - проверка immutability,
  - решение о возможности перехода к PASS_2;
- любые попытки:
  - хранить состояние,
  - ссылаться на предыдущие шаги,
  - использовать историю диалога как источник истины.

PASS_1 **не проверяет себя**
и **не решает, можно ли продолжать workflow**.

Его задача — выдать архитектурное решение
строго в рамках заданных ограничений,
а не оценивать корректность или исполнимость результата.

Все проверки и контроль выполняются **вне LLM**, в коде.

#### Что считается допустимым внутри PASS_1

В рамках `pass_1_decide.md` **допустимы**:

- декларативные правила генерации архитектуры
  (жёсткие ограничения пространства решений, но не их проверка),
  включая:
  - использование клинического реестра сущностей как источника истины;
  - запрет расширения архитектуры "по ассоциации" без клинического обоснования;
  - запрет латентной каннибализации одной и той же сущности
    через несколько доминирующих узлов.
- требование обоснования архитектурных решений
  (например, ownership rationale или why-variant-is-worse);
- жёсткие доменные и медицинские приоритеты;
- формирование альтернатив архитектуры
  без оценки «качества результата».

Это **не self-audit**, а часть процесса принятия решений.

#### Статус промпта как артефакта

`prompts/pass_1_decide.md` является **частью immutable-контракта snapshot**:

- его fingerprint включается в `*.sha256`;
- любое изменение файла:
  - считается изменением архитектурной логики;
  - требует выпуска нового snapshot;
  - требует нового approve;
- изменение промпта **после approve** запрещено
  для текущего snapshot.

Если `pass_1_decide.md` был изменён —
**старые snapshot’ы считаются несовместимыми
с новой версией архитектуры системы**.

### Что именно определяется

- `node_registry` — список узлов
- типы узлов: `HUB / SPOKE / SUPPORT`
- `hub_chain` — цепочка главного хаба
- `linking_matrix_skeleton` — скелет внутренней линковки
- ownership узлов (owner records)

### Источники данных

- `input/task.json` — входная постановка задачи
- `prompts/pass_1_decide.md` — системный промпт PASS_1
- LLM вызывается через `scripts/llm_cli_bridge.py`

### Результат PASS_1

PASS_1 формирует snapshot архитектуры и фиксирует fingerprint всех системных prompt-файлов, используемых для данного workflow.

Fingerprint prompt-файла — это детерминированный hash его канонического содержимого.

Fingerprint используется:

- при формировании `*.sha256`;
- при проверке неизменяемости snapshot перед EXECUTE;
- для доказательства воспроизводимости результата.

PASS_1 формирует snapshot архитектуры:

- `*.snapshot.json` — зафиксированное решение архитектуры  вместе с версиями используемых системных prompts
- `*.canonical.json` — каноническое представление
- `*.sha256` — hash immutable-части snapshot, включая архитектуру и fingerprint используемых prompt-файлов

Файлы сохраняются в:

```bash
state/snapshots/
```

После этого архитектура считается **кандидатом на approve**: её нельзя "подкручивать" в рамках PASS_2, а любые изменения оформляются только через новый snapshot и повторный approve.

---

## Snapshot и принцип immutability

Snapshot — это фиксация архитектурного решения в JSON вместе с входными данными, на основе которых оно было принято.

Snapshot после approve считается immutable.
Контракт вступает в силу (становится immutable) **только после шага APPROVE**.

Snapshot считается валидным **только в связке с тем `input/task.json`**, на основе которого он был сформирован.
Любая подмена или изменение `task.json` после PASS_1 аннулирует валидность snapshot.

В блоке `immutable_architecture` находятся поля, которые считаются immutable **после approve**:

- `node_registry`
- `hub_chain`
- `linking_matrix_skeleton`
- `owner_map` (фактически список owner-records)
- fingerprints системных prompt-файлов:
  - `prompts/pass_1_decide.md`
  - `prompts/pass_2_execute_core.md`
  - `prompts/pass_2_execute_anchors.md`

Любая попытка:

- изменить количество узлов,
- поменять тип узла,
- изменить линковку

после approve должна приводить к отказу исполнения PASS_2.
До approve такие изменения допускаются **только через выпуск нового snapshot**, а не правку существующего.

---

## APPROVE (человеческий шаг)

Snapshot **запрещено исполнять без APPROVE**.
Отсутствие approval-файла является безусловным основанием для отказа запуска PASS_2.

Для разрешения EXECUTE требуется файл подтверждения.
Автоматическое или программное создание approval-файла запрещено.

```bash
state/approvals/<hash>.approved
```

Где `<hash>` — значение из `*.sha256` snapshot-файла.
Любое изменение snapshot (даже минимальное) требует **нового approve** и нового approval-файла.

Это:

- явная точка ответственности человека,
- момент, после которого snapshot считается immutable,
- защита от самовольного исполнения,
- жёсткое отделение «решения» от «исполнения».

---

## PASS_2: EXECUTE

### Назначение

PASS_2 **не принимает архитектурных решений**.
Он строго исполняет то, что зафиксировано в snapshot.

### Проверки перед запуском (PRE-FLIGHT gate)

Перед началом EXECUTE orchestrator выполняет детерминированный
**PRE-FLIGHT gate до любого вызова LLM**.

Проверяется одновременно:

- корректность snapshot (canonical + sha256);
- наличие approval-файла для snapshot;
- неизменяемость immutable-части snapshot;
- совпадение fingerprint системных prompt-файлов;
- наличие и корректность `immutable_fingerprint`;
- совпадение `task_id` snapshot с `input/task.json`.

Нарушение любого пункта PRE-FLIGHT = **BLOCKER** (exit code 2).

EXECUTE запрещён, LLM не вызывается, состояние проекта не изменяется.

### Запрет повторной генерации артефактов (fail-fast)

По умолчанию повторный запуск PASS_2 для одного и того же
`snapshot + stage (CORE / ANCHORS)` **запрещён**, если выходная директория
уже существует и содержит файлы.

Это правило enforced кодом orchestrator и выполняется
**до вызова LLM**.

Цель:

- сохранить воспроизводимость результатов;
- исключить случайную перегенерацию артефактов;
- защитить audit trail для каждого snapshot.

При попытке повторного запуска без явного разрешения
EXECUTE завершается с ошибкой `OUTPUT_DIR_EXISTS`,
LLM не вызывается, состояние проекта не изменяется.

#### Флаг `--force` (осознанное исключение)

Флаг `--force` разрешает **принудительную перегенерацию**
указанного stage PASS_2.

Поведение:

- существующая директория stage **полностью удаляется**;
- stage выполняется заново;
- без `--force` перезапись невозможна.

Использование `--force` означает **явный отказ от предыдущего результата**
и является ручным решением оператора, а не штатным сценарием pipeline.

### Источники данных

- `state/snapshots/*.snapshot.json` — архитектура
- `prompts/pass_2_execute_core.md` — системный промпт PASS_2A (CORE)
- `prompts/pass_2_execute_anchors.md` — системный промпт PASS_2B (ANCHORS)
- LLM через `scripts/llm_cli_bridge.py`

### Результат PASS_2

PASS_2 создаёт deliverables **поэтапно**:

outputs/pass_2/<run_id>/
├── core/
│ ├── semantic_enrichment.json
│ ├── keywords.json
│ ├── patient_questions.json
│ ├── execution_result.json
│ └── execution_result.raw.txt
│
├── anchors/
│ ├── anchors.json
│ ├── execution_result.json
│ └── execution_result.raw.txt
│
└── (MERGE фиксируется в state/merges/<merge_id>.json; post-check выполняется по merge_id)

Post-check выполняется **только после merge core + anchors**.

Merge:

- выполняется **внешним кодом (Python)**,
- не является задачей LLM,
- не допускает интерпретации или пересборки данных,
- фиксирует результат объединения стадий как merge-state в `state/merges/<merge_id>.json`
  (post-check использует merge-state как источник истины).

---

## Типы изменений и где они допустимы

Каждый тип изменения в проекте имеет **строго определённое место** в workflow.
Если изменение внесено не на своём этапе — это считается архитектурной ошибкой,
даже если результат выглядит логически корректным.

| Тип изменения | Где допустимо |
|---------------|---------------|
| Изменение структуры узлов (node_registry) | PASS_1 |
| Изменение типов узлов (HUB / SPOKE / SUPPORT) | PASS_1 |
| Изменение hub_chain | PASS_1 |
| Изменение линковки (linking_matrix_skeleton) | PASS_1 |
| Изменение ownership (canonical_home, owner_status) | PASS_1 |
| Изменение семантических артефактов (keywords, questions, enrichment, anchors) | PASS_2 |
| Изменение формата или состава deliverables | PASS_2 |
| Изменение проверок snapshot или deliverables | scripts / orchestrator |
| Изменение логики approve или enforcement immutability | orchestrator |

Если изменение не попадает ни в одну из указанных категорий, оно считается некорректно сформулированным и подлежит пересмотру постановки задачи.

## Типы deliverables

### Per-node артефакты

Должны покрывать **все `node_id` из snapshot**, включая `SUPPORT`-узлы.

Тип узла (`HUB / SPOKE / SUPPORT`) **не влияет на обязанность**
иметь per-node deliverables.

При этом:

- `SUPPORT`-узлы **могут не участвовать в anchors**,
  если это не предусмотрено `linking_matrix_skeleton`.

- `keywords.json`
- `patient_questions.json`
  (вопросы формулируются строго в рамках узла
  и не используются для расширения или коррекции архитектуры)
- `semantic_enrichment.json`

### Link-level артефакты

- `anchors.json` — **JSON array (list)** объектов-анкоров (допустимо `[]`)
- используют `from_node_id / to_node_id`
- проверяются на соответствие `linking_matrix_skeleton`

### Aggregate‑артефакты

В текущей версии pipeline aggregate-артефакты **не используются**.

---

## Post‑check deliverables (обязательный гейт)

Post-check различает два класса отказов:

- BLOCKER — нарушение lifecycle или отсутствующее обязательное состояние (merge-state, canonical snapshot).
- FAIL — некорректные deliverables при валидном lifecycle.

После успешного MERGE (core + anchors) должен быть запущен post-check (он читает пути артефактов **только из merge-state**, а не «угадывает» их по outputs):

```bash
python scripts/check_deliverables.py <merge_id>
```

Проверяется:

- покрытие всех `node_id` в per-node артефактах
- валидность anchors

Если проверка не проходит:

- EXECUTE считается **проваленным**
- пайплайн останавливается

LLM не может «протащить» некорректный результат.

---

## Структура репозитория

Этот раздел — **инвентаризация фактического дерева репозитория** (`tree /F`).
Он описывает назначение каталогов и файлов, их место в lifecycle и тип:
публичный CLI / enforcement-гейт / helper / smoke-test / runtime-артефакт.

---

### Корень репозитория

- `.env` — локальные переменные окружения (локальная среда, не контракт).
- `.gitignore` — исключения для Git (в т.ч. артефактов выполнения/кэшей).
- `README.md` — источник истины по архитектуре, lifecycle и контрактам проекта.
- `SYSTEM_CONTEXT.md` — краткий канонический контекст для работы с ChatGPT.
- `to_do.md` — backlog задач (не часть runtime-контракта).
- `work_step.txt` — локальный рабочий файл/заметки (не часть архитектурного контракта).

---

### `input/` — входная постановка задачи (архитектурный контекст)

- `task.json`
  - **Lifecycle:** PASS_1 → PASS_2
  - **Тип:** архитектурный вход
  - **Роль:** источник `task_id` и контекста задачи; участвует в связке snapshot↔task
  - **Примечание:** изменение после PASS_1 требует нового snapshot и approve

---

### `prompts/` — системные промпты (fingerprints в snapshot, immutable после approve)

- `pass_1_decide.md`
  - **Lifecycle:** PASS_1 / DECIDE
  - **Тип:** системный промпт
  - **Роль:** принимает архитектурные решения (узлы/связи/ownership)

- `pass_2_execute_core.md`
  - **Lifecycle:** PASS_2A / CORE
  - **Тип:** системный промпт
  - **Роль:** генерирует per-node deliverables

- `pass_2_execute_anchors.md`
  - **Lifecycle:** PASS_2B / ANCHORS
  - **Тип:** системный промпт
  - **Роль:** генерирует link-level deliverable `anchors.json`

---

### `state/` — **единственный source of truth** по состоянию (LLM сюда не пишет)

- `arch_decision_schema.json`
  - **Lifecycle:** PASS_1 / DECIDE (валидация/контракт формата ARCH_DECISION_JSON)
  - **Тип:** schema / контракт входа-выхода PASS_1

#### `state/snapshots/` — snapshot-артефакты PASS_1

- `*.snapshot.json` — результат PASS_1 (становится immutable после approve)
- `*.canonical.json` — каноническая форма snapshot
- `*.sha256` — hash immutable-части snapshot + fingerprints промптов

#### `state/approvals/` — approve (точка невозврата)

- `<sha256>.approved`
  - **Lifecycle:** APPROVE
  - **Тип:** внешний человеческий сигнал
  - **Контракт:** отсутствие файла = BLOCKER для PASS_2

#### `state/merges/` — merge-state (терминальное состояние)

- `<merge_id>.json`
  - **Lifecycle:** MERGE
  - **Тип:** authoritative merge-state (используется post-check)
- `by_run/<run_id>.merge_id`
  - **Lifecycle:** MERGE → POST-CHECK
  - **Тип:** pointer для привязки run → merge_id

#### `state/runtime/` — runtime-трейсы (отладка, не контракт)

- `last_request.txt` — последний запрос к LLM-bridge (для дебага)
- `last_response.txt` — последний “сырой” ответ/поток от LLM-bridge (для дебага)

Важно: `last_response.txt` **не обязан** быть валидным JSON.
При ошибках провайдера/SDK (например, `LLM_OUTPUT_TRUNCATED`) файл может содержать частичный вывод,
обрезанные строки или вообще не-JSON. Парсить его как JSON можно только если вы явно видите,
что там полный корректный объект.


---

### `outputs/` — результаты выполнения (не source of truth)

- `pass_1_raw.jsonl`
  - **Lifecycle:** PASS_1 / DECIDE
  - **Тип:** raw лог/трасса ответа LLM (для дебага/аудита)

#### `outputs/pass_2/` — результаты PASS_2 по run_id

Каждый run хранится в каталоге вида `<task_id>__<hashprefix>`.

Типовая структура:

- `core/` (PASS_2A / CORE):
  - `semantic_enrichment.json`
  - `keywords.json`
  - `patient_questions.json`
  - `execution_result.json`
  - `execution_result.raw.txt`
- `anchors/` (PASS_2B / ANCHORS):
  - `anchors.json`
  - `execution_result.json`
  - `execution_result.raw.txt`

Примечания по фактическим данным в репозитории:

- встречаются run’ы, где присутствует только `core/` или только `anchors/`
  (частичные прогоны/остановки).
- присутствуют каталоги вида `*__MERGED*__...` и `*__MERGE__SMOKE1`, которые содержат агрегированные JSON-файлы
  (`anchors.json`, `keywords.json`, `patient_questions.json`, `semantic_enrichment.json`, `execution_result.json`);
  это **артефакты объединения/экспериментов**, но источником истины для post-check всё равно является `state/merges/<merge_id>.json`.

Файлы в `outputs/` **запрещено редактировать вручную**.

---

### `scripts/` — внешний контроль lifecycle (CLI, гейты, smoke-tests)

#### Публичные CLI (контрактные точки входа)

- `orchestrator.py`
  - **Lifecycle:** DECIDE / APPROVE / EXECUTE
  - **Тип:** публичный CLI
  - **Роль:** управление шагами + enforcement порядка + запуск PRE-FLIGHT

- `merge_pass2.py`
  - **Lifecycle:** MERGE (терминальное состояние)
  - **Тип:** публичный CLI (контрактный)
  - **Роль:** детерминированный MERGE CORE + ANCHORS,
    проверка `immutable_fingerprint`, создание `state/merges/<merge_id>.json`
    и pointer `state/merges/by_run/<run_id>.merge_id`;
    повторный MERGE = BLOCKER (exit code 2).

- `check_deliverables.py`
  - **Lifecycle:** POST-CHECK
  - **Тип:** публичный CLI (enforcement-гейт)
  - **Роль:** post-check строго по `merge_id`; authoritative source —
    `state/merges/<merge_id>.json`; различает FAIL vs BLOCKER;
    exit codes: PASS=0 / FAIL=1 / BLOCKER=2.

#### Enforcement-гейты / проверки

- `gate_snapshot.py`
  - Lifecycle: PASS_1 / DECIDE
  - Тип: enforcement-гейт
  - Назначение: структурная проверка `immutable_architecture` в
    `state/snapshots/<snapshot_id>.canonical.json`
    (node_registry, owner_map, hub_chain, linking_matrix_skeleton);
    не проверяет approve, sha256 и полный lifecycle.

- `preflight_pass2.py`
  - Lifecycle: PASS_2 / PRE-FLIGHT (вспомогательный)
  - Тип: вспомогательный enforcement-скрипт
  - Назначение: экспериментальная реализация PRE-FLIGHT
    (approve, fingerprints промптов, immutable_fingerprint);
    не является каноническим enforcement и напрямую orchestrator’ом не используется.

#### Lifecycle / модели состояния

- `lifecycle.py`
  - Lifecycle: глобально
  - Тип: внутренний контрактный модуль
  - Назначение: формальное определение lifecycle-состояний snapshot
    и enforcement STOP-condition (EXECUTE запрещён после MERGE).

#### Smoke-test / smoke-инструменты

- `smoke_test_lifecycle.py`
  - Lifecycle: end-to-end (DECIDE → APPROVE → EXECUTE → MERGE → POST-CHECK)
  - Тип: smoke-test
  - Назначение: black-box проверка CLI-контрактов, lifecycle и STOP-condition;
    валидирует exit codes и формат `[LEVEL] ERROR_CODE: message`.
- `smoke_post_check.ps1` — PowerShell-обвязка для smoke/post-check сценариев (локальный запуск на Windows).

#### Внутренние helper’ы

- `state_utils.py` — canonicalize/hash/load/save для snapshot/состояния.
- `llm_cli_bridge.py`
  - Lifecycle: PASS_1 / PASS_2
  - Тип: внутренний helper
  - Назначение: единая точка вызова LLM;
    в режиме `SMOKE_TEST=1` работает как детерминированный stub без внешнего провайдера.

#### Служебное

- `__pycache__/` — Python bytecode cache (не часть контракта; должен игнорироваться Git).

---

### Краткая карта ответственности

```text
input/      — что делаем (вход задачи)
prompts/    — как LLM обязана работать (системные промпты)
state/      — что считается истиной (snapshots/approvals/merges)
outputs/    — результаты выполнения (артефакты прогонов)
scripts/    — кто и что имеет право запускать (CLI и гейты)
```

Любой файл вне своего lifecycle-контекста считается
архитектурно недействительным, даже если он “выглядит правильно”.

---

## Оркестратор

### Файл

```bash
python -m scripts.orchestrator
```

### Режимы работы

- `decide`
- `approve`
- `execute`

`approve` механизирует человеческое решение и не является автоматическим "разрешением".

Команда:

```bash
python -m scripts.orchestrator approve --snapshot <snapshot_id>
```

- НЕ принимает решение за человека
- НЕ проверяет корректность snapshot только создаёт state/approvals/<hash>.approved

Команда `execute`:

- выполняет PRE-FLIGHT gate до вызова LLM;
- запрещает перезапись существующих outputs по умолчанию;
- допускает перезапись **только** при явном указании `--force`;
- не принимает решений за человека и не ослабляет архитектурный контракт.

---

## Канонический ручной workflow

Этот раздел описывает тот же процесс, что и Quick Start, но в более формальном и проверяемом виде.

Для одного snapshot:

```bash
# (опционально) диагностический структурный гейт snapshot
# обычно вызывается внутри orchestrator как часть PRE-FLIGHT
python scripts/gate_snapshot.py <snapshot_id>

# APPROVE — человеческий шаг (механизирован, но не автоматизирован)
python -m scripts.orchestrator approve --snapshot <snapshot_id>

# PASS_2A — CORE (per-node артефакты)
python -m scripts.orchestrator execute --stage core --snapshot state/snapshots/<snapshot_id>.snapshot.json

# PASS_2B — ANCHORS (link-level артефакты)
python -m scripts.orchestrator execute --stage anchors --snapshot state/snapshots/<snapshot_id>.snapshot.json

# MERGE — обязательный шаг (external, deterministic)
# Вход MERGE: результаты PASS_2A (CORE) и PASS_2B (ANCHORS) для одного approved snapshot.
# Обычно это один и тот же <task_id>__<hashprefix> (identity snapshot/run), но два stage-выхода.
python -m scripts.merge_pass2 \
  --core-snapshot-id <task_id>__<hashprefix> \
  --anchors-snapshot-id <task_id>__<hashprefix>

# MERGE создаёт lifecycle-состояние:
# - state/merges/<merge_id>.json
# - state/merges/by_run/<task_id>__<hashprefix>.merge_id
#
# <merge_id> = <task_id>__<hashprefix>
# где:
# - task_id берётся из input/task.json и snapshot
# - hashprefix = первые 12 символов sha256 snapshot

```

⚠️ ВАЖНО:

- post-check ЗАПРЕЩЁН для snapshot_id
- post-check РАЗРЕШЁН ТОЛЬКО для merge_id
- merge-state является единственным источником истины после MERGE

```bash
# post-check разрешён ТОЛЬКО для merge_id
python scripts/check_deliverables.py <merge_id>
```

Если любой шаг падает — процесс считается неуспешным.

---

## Ответственности компонентов

| Компонент | Ответственность |
|---------|----------------|
| PASS_1 | Архитектура |
| Snapshot | Контракт (immutable после approve) |
| Approve | Человеческое решение |
| PASS_2 | Исполнение |
| Post-check | Контроль качества |
| Orchestrator | Порядок и запреты |

---

## Ответственность за артефакты и правила изменений

Каждый артефакт в проекте имеет владельца, допустимые моменты изменения
и жёсткое правило, требует ли его изменение нового approve.

Если артефакт изменён вне разрешённого окна —
результат считается **архитектурно недействительным**,
даже если pipeline технически отработал.

| Артефакт | Владелец | Когда можно менять | Требует approve |
|--------|----------|-------------------|-----------------|
| `input/task.json` | Человек | **Только до PASS_1** | Да (через новый snapshot) |
| `prompts/pass_1_decide.md` | Человек / Архитектор | До запуска PASS_1 | Да (через новый snapshot) |
| `prompts/pass_2_execute_core.md` | Человек / Архитектор | Только до формирования snapshot | Да (через новый snapshot) |
| `prompts/pass_2_execute_anchors.md` | Человек / Архитектор | Только до формирования snapshot | Да (через новый snapshot) |
| `*.snapshot.json` | PASS_1 | До approve | Нет |
| `*.canonical.json` | Python (system) | Никогда вручную | Нет |
| `*.sha256` | Python (system) | Никогда | Нет |
| `state/approvals/*.approved` | Человек | Один раз на snapshot | — |
| `outputs/pass_2/**.json` | PASS_2 | Только в рамках EXECUTE | Нет |
| `execution_result.json` | PASS_2 | Только в рамках EXECUTE | Нет |
| `execution_result.raw.txt` | System log | Никогда вручную | Нет |
| `scripts/*.py` | Человек / Архитектор | В любое время | Нет (но влияет на все future runs) |

Дополнительно:

- `input/task.json` считается частью архитектурного контекста snapshot.  Любое его изменение после PASS_1 автоматически требует  выпуска нового snapshot и нового approve.
Любое изменение файлов `prompts/pass_1_decide.md`, `prompts/pass_2_execute_core.md` или `prompts/pass_2_execute_anchors.md` считается **изменением архитектурной логики системы** и допускается только через выпуск нового snapshot и новый approve.
- Ручное редактирование любых файлов в `outputs/`   запрещено. Такие результаты считаются архитектурно недействительными   и не подлежат post-check.

---

## Что проект **не** делает

Важно понимать ограничения проекта:

- проект **не** предназначен для «просто генерации текста»
- LLM **не** принимает финальные решения
- результат **не** считается корректным без проверок
- пайплайн **не** продолжает работу при нарушении архитектуры

Если нужен быстрый, неконтролируемый вывод — этот проект избыточен.

---

## Итог

`semantic-cocon` превращает работу с LLM из генерации «на доверии» в **проверяемый инженерный процесс**:

- архитектура отделена от исполнения
- решения фиксируются
- каждое действие верифицируется
- результат либо доказуемо корректен, либо отвергнут

Это основа для масштабируемых и воспроизводимых LLM‑систем.

## PRE-FLIGHT STOP CONDITIONS

STOP-1: Правка размывает границу DECIDE / EXECUTE
(PASS_2 начинает принимать решения или PASS_1 начинает проверять себя )

STOP-2: Правка переносит контроль внутрь LLM
(verify / approve / "проверь" / "если не получилось" )

STOP-3: Правка расширяет смысл PASS_2
(новые сущности, новые темы через enrichment / questions / keywords )

## PRE-FLIGHT gate перед PASS_2 (каноническое резюме)

Этот раздел является кратким каноническим резюме PRE-FLIGHT gate.
Полное описание и контекст см. в разделе PASS_2: EXECUTE.

Перед запуском любого этапа PASS_2 (CORE или ANCHORS) внешний orchestrator
ОБЯЗАН выполнить детерминированную PRE-FLIGHT проверку **до любого вызова LLM**.

**Где реализуется:** `scripts/orchestrator.py`, команда `execute`,
непосредственно перед началом PASS_2.

### Условия gate (нарушение любого условия = BLOCKER)

1) **Корректность snapshot**  
   Snapshot валиден по структуре и соответствует своей canonical/sha256-идентичности.
2) **Approval**  
   Snapshot должен иметь внешнее подтверждение (точка невозврата).
3) **Immutability**  
   Immutable-поля snapshot и fingerprints промптов совпадают с текущим кодом.
4) **immutable_fingerprint**  
   Snapshot обязан содержать `immutable_fingerprint`, и его значение должно
   совпадать с вычисленным внешним кодом.
5) **Связка с входной задачей**  
   `task_id`, зафиксированный в snapshot, **обязан совпадать** с `task_id`
   из текущего `input/task.json`.

При нарушении любого условия PASS_2 **НЕ запускается**
(ни CORE, ни ANCHORS). Это **BLOCKER** (exit code 2), LLM не вызывается.

## Контракт merge-state (authoritative)

MERGE является детерминированным внешним шагом и фиксируется как состояние в `state/`.

Важно: формат `state/merges/<merge_id>.json` является частью контракта post-check.
Если контракт post-check расширился (например, post-check теперь ожидает `snapshot_canonical`),
то **старые** merge-state могут стать невалидными и давать:

`[BLOCKER] MERGE_STATE_INVALID: ...`

Что делать:

- НЕ править merge-state вручную.
- НЕ пытаться “починить” это удалением `outputs/` для уже merged snapshot (STOP-condition всё равно запретит execute).
- Выпустить новый snapshot (`DECIDE`), сделать новый `APPROVE`, выполнить `EXECUTE`, затем `MERGE` заново.

### Каноническое merge-state

- `state/merges/<merge_id>.json` — каноническая запись MERGE.
- `state/merges/by_run/<task_id>__<hashprefix>.merge_id` — pointer для конкретного run.

MERGE считается выполненным только при наличии обоих файлов.

### Инварианты

- `immutable_fingerprint` в `state/merges/<merge_id>.json` обязан совпадать с вычисленным fingerprint для approved snapshot.
- После появления merge-state любые попытки `execute --stage core|anchors` обязаны завершаться ошибкой (включая запуск с `--force`).

## merge_pass2 — публичный CLI-контракт

`merge_pass2` является **единственной допустимой точкой выполнения MERGE**
в проекте. Любая попытка объединения CORE и ANCHORS вне этого CLI
считается нарушением архитектурного контракта.

`merge_pass2` — детерминированный CLI-инструмент, выполняющий MERGE результатов
PASS_2A (CORE) и PASS_2B (ANCHORS) **без участия LLM**.

MERGE является точкой фиксации состояния и частью enforce-lifecycle проекта.

### Аргументы CLI

Обязательные аргументы:

- `--core-snapshot-id <run_id>` — run_id для результатов PASS_2A / CORE (каталог в `outputs/pass_2/`)
- `--anchors-snapshot-id <run_id>` — run_id для результатов PASS_2B / ANCHORS (каталог в `outputs/pass_2/`)

Оба аргумента обязаны ссылаться на результаты, полученные из одного и того же approved snapshot
(stage-level invariants проверяются через `immutable_fingerprint`).

⚠️ ВАЖНО: `merge_pass2` не принимает `--merge-id`.

`merge_id` вычисляется детерминированно:

```text
merge_id = <task_id>__<hashprefix>
hashprefix = первые 12 символов sha256 canonical snapshot
```

Ручная подстановка merge_id запрещена, потому что ломает воспроизводимость и audit trail.

| Exit code | Значение |
|---------|----------|
| `0` | PASS — MERGE выполнен, merge-state создан |
| `1` | FAIL — ошибка входных данных или окружения (I/O, отсутствующие файлы, некорректные аргументы) |
| `2` | BLOCKER — нарушение архитектурного или lifecycle-контракта (повторный MERGE, fingerprint mismatch, попытка нарушить lifecycle) |

### Формат вывода (stdout / stderr)

См. раздел «Единый формат вывода проверок» выше: все CLI-гейты обязаны печатать первую строку в формате `[LEVEL] ERROR_CODE: message`.
