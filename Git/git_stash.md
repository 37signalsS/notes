# Git Stash — временное хранение изменений

## Определения

**Stash (git stash)** — механизм временного сохранения незавершённых изменений рабочего каталога и индекса в отдельном хранилище, позволяющий переключиться на другую ветку без создания «грязного» коммита.

**Физическая реализация:** Stash — это специальный вид коммита. Git создаёт коммиты на основе текущего индекса и рабочего каталога, но помещает их не в историю ветки, а в `refs/stash`. Эти коммиты имеют родительские ссылки на состояние до stash и на индекс. Git не синхронизирует `refs/stash` с удалённым репозиторием.

### Почему stash существует

Git не позволяет переключиться на другую ветку (`git switch` / `git checkout`), если есть незакоммиченные изменения, которые конфликтуют с состоянием целевой ветки. Альтернативы stash:

| Подход | Проблема |
|--------|----------|
| Создать временный коммит | Засоряет историю «мусорными» коммитами |
| Просто переключиться | Untracked файлы переносятся между ветками, tracked changes могут вызвать конфликт |
| Принудительный checkout | Потеря незакоммиченных изменений |

Stash решает эту проблему, убирая изменения в «карман» и восстанавливая чистое состояние.

---

## Базовые концепции

### Stash как стек

Stash организован по принципу LIFO (Last In, First Out):

```bash
# Положить изменения на стек
git stash
# → Saved working directory and index state WIP on main: a1b2c3d last commit

# Список всех stash
git stash list
# → stash@{0}: WIP on main: a1b2c3d last commit
# → stash@{1}: WIP on feature: e5f6g7h previous commit

# Применить верхний stash и удалить его из стека
git stash pop

# Применить верхний stash без удаления
git stash apply

# Применить конкретный stash
git stash apply stash@{1}
```

### Типы stash

```bash
# Обычный stash — сохраняет только tracked изменения (staged + unstaged)
git stash

# Включить untracked файлы (-u / --include-untracked)
git stash -u

# Включить все файлы, включая ignored (-a / --all)
git stash -a
```

### Управление stash

```bash
# Удалить конкретный stash
git stash drop stash@{0}

# Очистить весь стек
git stash clear

# Посмотреть изменения в stash (без применения)
git stash show -p stash@{0}

# Создать ветку из stash (полезно, если конфликт при pop)
git stash branch new-feature-branch stash@{0}
```

---

## Практические сценарии

### Сценарий 1: Срочный баг-фикс

Работа над фичей прервана срочным багом на main:

```bash
# Текущее состояние: dirty working directory на feature
git stash -u                          # Сохранить всё включая новые файлы
git switch main                       # Чистое переключение
# ... правим баг, коммитим ...
git switch feature                    # Вернуться к фиче
git stash pop                         # Восстановить изменения
```

### Сценарий 2: Untracked файлы переносятся при switch

Если файл не отслеживается (untracked), Git переносит его между ветками при `git switch`. Это может привести к тому, что код появится в чужой ветке:

```bash
# На ветке feature создан untracked файл debug.log
git status
# → ?? debug.log

git switch main
# debug.log появляется на main — неожиданно

# Решение: stash с -u перед switch
git stash -u
git switch main                       # Чисто
```

### Сценарий 3: Частичное stash

Stash только staged-изменения, оставив unstaged:

```bash
git stash --staged                    # Git 2.35+
```

Stash только определённые файлы:

```bash
git stash push -m "wip" src/app.js tests/
```

### Сценарий 4: Конфликт при stash pop

Если с момента stash изменилась ветка, `git stash pop` может вызвать конфликт:

```bash
git stash pop
# → Auto-merging file.txt
# → CONFLICT (content): Merge conflict in file.txt

# Создать ветку из stash — самый безопасный выход
git stash branch recovery-branch stash@{0}
```

---

## Особенности и ограничения

- **Локальность:** Stash существует только в локальном `.git/refs/stash`. Команда `git push` не отправляет stash на сервер.
- **Не привязан к ветке:** Stash глобален для репозитория. Можно применить stash из любой ветки (однако это может вызвать конфликты).
- **Срок жизни:** Stash не удаляется автоматически. Только явные `git stash drop` / `git stash clear` или сборщик мусора для объектов, на которые перестали ссылаться.
- **Auto-stash при rebase:** При `git rebase` с непустым working directory Git может автоматически сделать stash и применить его после rebase.

---

## Дополнительная информация

### Связанные темы

- [Git — основы](./git_basics.md) — базовые команды
- [Внутреннее устройство Git](./git_internals.md) — объектная модель, refs
- [Git Worktree](./git_worktree.md) — альтернатива stash для параллельной работы

### Официальные ресурсы

- **Git Stash docs:** [git-scm.com/docs/git-stash](https://git-scm.com/docs/git-stash)
- **Pro Git — Stashing:** [git-scm.com/book/ru/v2/Git-tools-Stashing](https://git-scm.com/book/ru/v2/Git-инструменты-Stashing)
