# Разрешение конфликтов в Git

## Определения

**Merge conflict (Конфликт слияния)** — ситуация, когда Git не может автоматически объединить изменения из двух веток, поскольку обе ветки модифицировали одни и те же строки в одном файле.

**Conflict marker (Маркер конфликта)** — специальные строки `<<<<<<<`, `=======`, `>>>>>>>`, вставляемые Git в файл для обозначения конфликтующих участков.

**Rerere (Reuse Recorded Resolution)** — механизм Git для автоматического запоминания и повторного использования разрешений конфликтов. Включается через `git config rerere.enabled true`.

**Working tree / Index / Repository** — три стадии файла: рабочее дерево (файл на диске), индекс (staging area), коммит (HEAD).

---

## Базовые концепции

### Структура конфликта

```
<<<<<<< HEAD
текущая версия (из текущей ветки)
=======
версия из присоединяемой ветки
>>>>>>> feature
```

| Маркер | Значение |
| :--- | :--- |
| `<<<<<<< HEAD` | Начало текущей версии (наша) |
| `=======` | Разделитель |
| `>>>>>>> feature` | Конец присоединяемой версии (их) |

### Когда возникают конфликты

| Операция | Конфликт возможен? | Комментарий |
| :--- | :--- | :--- |
| `git merge` | Да | Обе ветки изменили один файл |
| `git rebase` | Да | Коммиты конфликтуют с целевой веткой |
| `git stash pop` | Да | Stash конфликтует с текущим состоянием |
| `git cherry-pick` | Да | Коммит конфликтует с текущей веткой |
| `git pull` | Да | Удалённые изменения конфликтуют с локальными |
| `git push` | Нет | Push отклоняется, если remote изменился |

### Стратегии разрешения

| Подход | Когда использовать |
| :--- | :--- |
| Ручное редактирование | Сложные конфликты, требующие анализа |
| `--ours` / `--theirs` | Принятие одной из версий полностью |
| `git mergetool` | Визуальный инструмент для разрешения |
| `rerere` | Повторяющиеся конфликты (rebase) |

---

## Практические сценарии

### Сценарий 1: Стандартное разрешение конфликта при merge

```bash
# Начать слияние
git merge feature
# → CONFLICT (content): Merge conflict in src/app.py

# Просмотреть конфликтные файлы
git status
# → Unmerged paths:
# →   both modified:   src/app.py

# Открыть файл и разрешить конфликт вручную
# Удалить маркеры <<<<<<<, =======, >>>>>>> и оставить нужный код

# Зафиксировать результат
git add src/app.py
git commit -m "merge: resolve conflict in app.py"
```

**Edge cases:**
- После `git add` файл попадает в индекс. Если передумали — `git reset HEAD <file>`.

### Сценарий 2: Автоматическое принятие нашей версии

```bash
# Принять OURS (текущая ветка) для конфликтующих файлов
git merge -X ours feature
# Или после конфликта:
git checkout --ours src/app.py
git add src/app.py
git commit -m "merge: accept our version"
```

### Сценарий 3: Автоматическое принятие их версии

```bash
# Принять THEIRS (присоединяемая ветка)
git merge -X theirs feature
# Или после конфликта:
git checkout --theirs src/app.py
git add src/app.py
git commit -m "merge: accept their version"
```

### Сценарий 4: Разрешение конфликтов при rebase

```bash
# Начать rebase
git rebase main
# → CONFLICT (content): Merge conflict in src/utils.js

# Разрешить конфликт
git checkout --ours src/utils.js  # или --theirs
git add src/utils.js

# Продолжить rebase
git rebase --continue

# Или отменить rebase
git rebase --abort
```

**Edge cases:**
- При `rebase` маркеры могут содержать разные версии (OURS = rebase target, THEIRS = коммит).
- Используйте `rerere` для автоматического разрешения повторяющихся конфликтов.

### Сценарий 5: Включение rerere

```bash
# Включить rerere
git config rerere.enabled true

# Или глобально
git config --global rerere.enabled true

# Теперь Git запомнит разрешение и применит его автоматически
# при повторном конфликте в том же участке кода
```

**Валидация:**
```bash
# Просмотреть записанные разрешения
git rerere status
# → src/app.py

# Просмотреть diff разрешения
git rerere diff
```

### Сценарий 6: Использование mergetool

```bash
# Запустить визуальный инструмент
git mergetool
# → Мердж-тур запустится (opendiff, vimdiff, meld и др.)

# Указать конкретный инструмент
git mergetool --tool=meld
```

**Настройка инструмента:**
```bash
git config merge.tool meld
git config mergetool.meld.cmd 'meld "$LOCAL" "$BASE" "$REMOTE" --output "$MERGED"'
```

### Сценарий 7: Отмена слияния/merge в процессе

```bash
# Отменить merge (до коммита)
git merge --abort

# Отменить rebase (до завершения)
git rebase --abort

# Отменить cherry-pick (до завершения)
git cherry-pick --abort

# Отменить stash pop (при конфликте — stash остаётся)
# Просто не делайте git add, stash на месте
```

### Сценарий 8: Конфликт при pull

```bash
# Вытянуть с merge-стратегией
git pull origin main

# Если конфликт:
git status
# → both modified: config.yml

# Разрешить и зафиксировать
git add config.yml
git commit -m "merge: resolve config conflict"
```

---

## Особенности и ограничения

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `CONFLICT (content): Merge conflict in file` | Конфликтующие изменения | Разрешить вручную или через `-X ours`/`theirs` |
| `error: path 'file' unmerged` | Файл в состоянии unmerged | `git add <file>` или `git reset HEAD <file>` |
| `fatal: You are in the middle of a merge` | Merge не завершён | `git merge --abort` или завершить merge |
| Маркеры `<<<<<<<` в коммите | Конфликт не был разрешён | Исправить файл, сделать `git add` и `git commit --amend` |
| `rerere` не работает | `rerere.enabled` не включён | `git config rerere.enabled true` |

### Best Practices

1. **Включите `rerere`** — он автоматически разрешает повторяющиеся конфликты.
2. **Используйте mergetool** для визуального разрешения сложных конфликтов.
3. **Не коммитьте маркеры** — всегда проверяйте `git diff` перед коммитом.
4. **Делайте `git pull --rebase`** — минимизирует merge-коммиты и упрощает историю.
5. **Разрешайте конфликты сразу** — не откладывайте, иначе забудете контекст.
6. **Используйте `--no-commit`** для проверки результата перед фиксацией.

---

## Дополнительная информация

### Связанные темы

- [Git Merge — стратегии](./git_merge_strategies.md) — recursive, ours, theirs, patience, octopus.
- [Ветвление в Git](./git_branching.md) — merge vs rebase, --no-ff, squash merge.
- [Git History Manipulation](./git_history_manipulation.md) — rebase, cherry-pick и откат изменений.
- [Git Stash](./git_stash.md) — конфликты при stash pop и восстановление.
- [Устранение неполадок Git](./git_troubleshooting.md) — диагностика и восстановление после конфликтов.

### Официальные ресурсы

- **Git Merge Documentation:** [git-scm.com/docs/git-merge](https://git-scm.com/docs/git-merge)
- **Pro Git Book — Basic Merging:** [git-scm.com/book/ru/v2/Ветвление-в-Git](https://git-scm.com/book/ru/v2/Ветвление-в-Git)
