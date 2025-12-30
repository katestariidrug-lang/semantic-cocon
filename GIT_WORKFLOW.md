# Git workflow для проекта Semantic Cocon

Этот документ — практическая инструкция, как работать с git именно в этом проекте:
когда коммитить, когда пушить, что хранить в GitHub, как восстанавливаться, если что-то сломалось.

Без теории. Только рабочие команды и правила.

---

## Что хранится в репозитории

### Коммитим (код и логика проекта)

- scripts/
- prompts/
- файлы .py
- файлы .md
- README.md, SYSTEM_CONTEXT.md, to_do.md
- схемы и конфиги, необходимые для воспроизведения логики  
  например state/arch_decision_schema.json

### НЕ коммитим (артефакты выполнения)

- outputs/
- state/runtime/
- state/snapshots/
- state/approvals/
- .env

Артефакты остаются локально и не засоряют историю git.

---

## Базовый цикл работы

### Перед началом работы

    git status

Если:
- working tree clean — можно работать
- есть изменения — сначала понять, откуда они

---

### Когда делать коммит

Коммит делается по смыслу, а не по времени.

Коммитим, если:
- закончена логическая часть работы
- изменение можно описать одним предложением
- проект остаётся в рабочем состоянии

Команды:

    git status
    git add <нужные_файлы>
    git status
    git commit -m "Краткое описание изменения"

    git add -A использовать ТОЛЬКО если:
    - все изменения одного смыслового типа
    - ты понимаешь каждый файл в списке
    - в staging не попадают outputs/ и state/*

---

### Когда делать push

Push — это фиксация результата в GitHub.

    git status
    git fetch origin
    git status

Если видишь:
- behind → нужно git pull --rebase
- diverged → обязательно git pull --rebase
- up to date → можно push

Перед каждым push ОБЯЗАТЕЛЬНО:

Пушить, если:
- закончена задача или подзадача
- нужен бэкап
- работа завершена на сегодня

Команда:

    git push

Коммиты можно делать часто. Пушить — по необходимости.

Если git push отклонён (fetch first):

    git status
    git fetch origin
    git pull --rebase
    git push

НИКОГДА не использовать git push --force.

---

## Контроль перед коммитом

Перед каждым коммитом:

    git status

Если видишь:
- outputs/
- state/runtime
- state/snapshots
- state/approvals

→ не коммить, сначала проверь .gitignore.

---

## Просмотр изменений и истории

Посмотреть изменения:

    git diff

Посмотреть историю:

    git log --oneline --decorate -10

Посмотреть, какие файлы реально отслеживает git (PowerShell):

    git ls-files | Select-String outputs
    git ls-files | Select-String state

Если команды ничего не выводят — эти папки не tracked (это правильно).

Проверить, почему конкретный файл игнорируется:

    git check-ignore -v <путь_к_файлу>


---

## Восстановление и откаты

### Изменила файл, но не делала git add

    git restore README.md

Файл возвращается к последнему коммиту.

---

### Сделала git add, но передумала

Убрать файл из staging:

    git restore --staged README.md

Полностью отменить изменения:

    git restore README.md

---

### Сделала коммит, но НЕ пушила

Удалить последний коммит:

    git reset --hard HEAD~1

---

### Сделала коммит и УЖЕ пушила

Безопасный способ отменить:

    git revert HEAD
    git push

История сохраняется, изменения отменяются новым коммитом.

---

### Вернуть всё как в GitHub

Перед reset ОБЯЗАТЕЛЬНО:

    git status
    git stash -u   (если есть незакоммиченные правки)

Затем:

    git reset --hard origin/main

ВНИМАНИЕ: без stash изменения будут потеряны.

---

## Временное сохранение (stash)

Если нужно срочно переключиться и не коммитить:

    git stash push -m "WIP"

Вернуть изменения:

    git stash pop

Посмотреть список stash:

    git stash list

---

## Редактор сообщений коммитов

Используется стандартный Windows Notepad:

    git config --global core.editor notepad

Проверка:

    git config --global core.editor

---

## Основные правила проекта

1. .env никогда не коммитится  
2. Артефакты прогонов не часть репозитория  
3. Коммит = один смысловой шаг  
4. Перед любым действием — git status  
5. После push — только git revert, не reset  

---

## Шпаргалка (самое частое)

Проверить состояние:

    git status

Добавить файлы в коммит (ТОЛЬКО осознанно):

    git status
    git add README.md
    git add GIT_WORKFLOW.md
    git status


Коммит (сохранить состояние проекта):

    git commit -m "Обновлена шпаргалка Git: контроль перед push и безопасный add"

Push (отправить сохранённое в GitHub):

    git push

Откат файла:

    git restore <file>

Убрать из staging:

    git restore --staged <file>

Отменить последний коммит (не пушила):

    git reset --hard HEAD~1

Отменить последний коммит (пушила):

    git revert HEAD
    git push

Вернуть состояние как в GitHub:

    git reset --hard origin/main
