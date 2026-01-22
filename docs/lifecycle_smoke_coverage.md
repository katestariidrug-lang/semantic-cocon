# Lifecycle smoke coverage

Этот документ фиксирует, какие правила lifecycle-FSM (см. README.md) покрыты
интеграционным smoke-тестом `scripts/smoke_test_lifecycle.py`.

Smoke запускается в детерминированном режиме (без реального LLM):

```bash
SMOKE_TEST=1 python -m scripts.smoke_test_lifecycle
```

## Coverage
| Правило FSM (контракт)                              | Smoke-шаг                     | Ожидаемый результат | Статус  |
| --------------------------------------------------- | ----------------------------- | ------------------- | ------- |
| `DECIDE` создаёт snapshot                           | `snapshot/decide`             | PASS/0              | COVERED |
| `EXECUTE` до `APPROVE` запрещён                     | `execute-before-approve`      | BLOCKER/2           | COVERED |
| `APPROVE` без snapshot (несуществующий snapshot_id) | `approve-missing-snapshot`    | FAIL/1 (IO_ERROR)   | COVERED |
| `APPROVE` после snapshot допустим                   | `approve`                     | PASS/0              | COVERED |
| `EXECUTE` CORE после approve допустим               | `execute/core`                | PASS/0              | COVERED |
| `EXECUTE` ANCHORS после approve допустим            | `execute/anchors`             | PASS/0              | COVERED |
| `POST-CHECK` до MERGE запрещён                      | `post-check-before-merge`     | BLOCKER/2           | COVERED |
| `POST-CHECK` по task_id запрещён                    | `post-check-by-task-id`       | BLOCKER/2           | COVERED |
| `MERGE` после CORE+ANCHORS допустим                 | `merge`                       | PASS/0              | COVERED |
| `POST-CHECK` без merge_id запрещён                  | `post-check-missing-merge-id` | BLOCKER/2           | COVERED |
| `POST-CHECK` по merge_id допустим                   | `post-check`                  | PASS/0              | COVERED |
| STOP-condition: `EXECUTE` после `MERGE` запрещён    | `execute-after-merge`         | BLOCKER/2           | COVERED |

## Notes
- Smoke проверяет внешний CLI-контракт: формат первой строки [LEVEL] CODE: message и допустимые exit codes 0/1/2.
- Класс ошибки approve-missing-snapshot — FAIL/IO_ERROR, так как отсутствуют snapshot-артефакты (это не lifecycle-переход, а ошибка ввода/IO).