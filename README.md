Зачем каждый каталог

**prompts/**
- pass_1_decide.md — промпт, который ТОЛЬКО принимает архитектурные решения.
- pass_2_execute.md — промпт, который ТОЛЬКО исполняет зафиксированную архитектуру.

**input/**
- task.json — вход задачи: domain, goal, region, seed-данные.
Этот файл один и тот же для PASS_1 и PASS_2.

**state/**
- snapshots/ — сохранённые ARCH_DECISION_JSON + hash.
- approvals/ — файлы человеческого подтверждения (флаг, подпись, whatever).
LLM сюда не пишет. Только Python.

**outputs/**
- pass_2/ — финальные артефакты: тексты, таблицы, JSON, MD.
Всё, что можно отдать дальше в работу.

**scripts/**
- state_utils.py — canonicalize, hash, save, load, verify.
- orchestrator.py — decide / approve / execute.
Без классов ради классов. Это не фреймворк, это инструмент.

