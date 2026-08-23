# Git Merge — стратегии слияния

## Определения

**Merge strategy (Стратегия слияния)** — алгоритм, которым Git определяет, как объединить изменения из разных веток в один коммит слияния (merge commit). Выбирается через флаг `-s` или `-X` к `git merge`.

**Fast-forward (FF)** — слияние без создания merge-коммита. HEAD перемещается на коммит целевой ветки, если он является потомком текущего. Не изменяет историю.

**Recursive** — стратегия по умолчанию. Создаёт merge-коммит с двумя или более родителями. Рекурсивно объединяет общих предков при наличии нескольких.

**Octopus** — стратегия для слияния трёх и более веток одновременно. Не поддерживает конфликты.

**Ours** — стратегия, которая при каждом конфликте сохраняет текущую версию (OURS), игнорируя изменения из другой ветки.

**Theirs** — стратегия, которая при каждом конфликте принимает версию из другой ветки (THEIRS).

**Resolve** — упрощённая стратегия (аналог рекурсивной для двух веток), требующая наличие уникального общего предка.

---

## Базовые концепции

### Основные стратегии (-s)

| Стратегия | Описание | Когда использовать |
| :--- | :--- | :--- |
| `recursive` | По умолчанию. Рекурсивно объединяет общих предков. | Стандартное слияние двух веток |
| `ours` | Игнорирует все изменения из присоединяемой ветки. | Сохранение текущего состояния при слиянии «шумных» веток |
| `octopus` | Сливает несколько веток без конфликтов. | Массовое обновление зависимостей, release branches |
| `resolve` | Упрощённая стратегия для двух веток с одним общим предком. | Редко используется (legacy) |

### Опции слияния (-X)

| Опция | Описание |
| :--- | :--- |
| `ours` | При конфликте сохраняет OURS (текущая ветка) |
| `theirs` | При конфликте принимает THEIRS (присоединяемая ветка) |
| `patience` | Использует алгоритм patience для поиска общих строк (точнее для переименований) |
| `ignore-all-space` | Игнорирует изменения в пробелах |
| `ignore-space-at-eol` | Игнорирует пробелы в конце строк |
| `ignore-cr-at-eol` | Игнорирует `\r` в конце строк |
| `ignore-blank-lines` | Игнорирует изменения, состоящие только из пустых строк |
| `ignore-space-change` | Игнорирует количество пробелов (но не их наличие) |

### Типы слияния

| Тип | Команда | Результат |
| :--- | :--- | :--- |
| Fast-forward | `git merge feature` (если возможно) | HEAD перемещается, merge-коммит не создаётся |
| No fast-forward | `git merge --no-ff feature` | Всегда создаёт merge-коммит |
| Squash merge | `git merge --squash feature` + `git commit` | Все изменения схлопываются в один коммит |
| Rebase + FF | `git rebase feature && git merge feature` | Плоская история без merge-коммитов |

---

## Практические сценарии

### Сценарий 1: Стандартное слияние (recursive)

```bash
# Слить ветку feature в main
git checkout main
git merge feature
# → Merge made by the 'recursive' strategy.
```

**Валидация:**
```bash
git log --oneline --graph -5
# → *   e5f6g7h Merge branch 'feature'
# → |\
# → | * abc1234 feature: add validation
# → | * def5678 feature: add tests
# → * | a1b2c3d main: fix typo
```

### Сценарий 2: Fast-forward слияние

```bash
# Если feature — прямой потомок main
git checkout main
git merge feature
# → Fast-forward
```

**Валидация:**
```bash
git log --oneline --graph -5
# → * abc1234 feature: add validation
# → * def5678 feature: add tests
# → * a1b2c3d main: fix typo
# (нет merge-коммита)
```

### Сценарий 3: Слияние с игнорированием пробелов

```bash
# Слить, игнорируя изменения пробелов
git merge -X ignore-all-space feature
# → Если конфликты были только из-за пробелов — они разрешатся автоматически
```

**Валидация:**
```bash
# Проверить, что слияние прошло
git status
# →nothing to commit, working tree clean
```

### Сценарий 4: Слияние сours стратегией

```bash
# Взять только текущую версию при конфликтах
git merge -s ours feature
# → Merge made by the 'ours' strategy.
# Все изменения feature проигнорированы
```

**Валидация:**
```bash
# Проверить, что файлы НЕ изменились
git diff HEAD~1 --stat
# → (пусто — наша версия сохранена)
```

### Сценарий 5: Squash merge

```bash
# Схлопнуть все коммиты feature в один
git checkout main
git merge --squash feature
# → С Bloody ready (squash коммиты в индексе)
git commit -m "feature: add complete validation module"
```

**Валидация:**
```bash
git log --oneline -3
# → abc1234 feature: add complete validation module
# → def5678 main: fix typo
```

**Edge cases:**
- После squash merge.originalная ветка feature остаётся нетронутой.
- История feature не попадает в main — только итоговый результат.

### Сценарий 6: Слияние с patience стратегией

```bash
# Использовать patience для более точного поиска общих строк
git merge -X patience feature
# Полезно при больших переименованиях функций
```

### Сценарий 7: Массовое слияние (octopus)

```bash
# Слить несколько веток одновременно (без конфликтов)
git merge feature-a feature-b feature-c
# → Merge made by the 'octopus' strategy.
```

**Edge cases:**
- Если хотя бы одна ветка вызывает конфликт — octopus откажет.
- Используется в CI/CD для параллельного обновления зависимостей.

### Сценарий 8: Отмена слияния

```bash
# До коммита слияния (в процессе)
git merge --abort

# После коммита слияния (через revert)
git revert -m 1 <merge-commit-sha>
# → Создаёт коммит, отменяющий изменения из feature
```

---

## Особенности и ограничения

### Стратегия vs опции

| Флаг | Тип | Пример |
| :--- | :--- | :--- |
| `-s recursive` | Стратегия | `git merge -s recursive feature` |
| `-X ours` | Опция (модификатор) | `git merge -X ours feature` |
| `-s ours -X theirs` | Комбинация | Редко — ours игнорирует, theirs не нужен |

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `CONFLICT (content): Merge conflict in file.py` | Конфликтующие изменения | Разрешить вручную или использовать `-X ours`/`theirs` |
| `fatal: refusing to merge unrelated histories` | Ветки не связаны общим предком | `git merge --allow-unrelated-histories feature` |
| `error: Merging is not possible` | octopus strategy не поддерживает конфликты | Использовать `recursive` или разрешить конфликты |
| Merge commit не создаётся | Fast-forward сработал автоматически | `git merge --no-ff feature` для принудительного merge-коммита |

### Best Practices

1. **Используйте `--no-ff`** для сохранения контекста ветки в истории.
2. **Squash merge для фичей** — если промежуточные коммиты не важны.
3. **`-X ours` для частых конфликтов** — при уверенности, что наша версия приоритетна.
4. **Не используйте `-s ours` для реальных слияний** — он отбрасывает ВСЕ изменения.
5. **Patience для переименований** — улучшает качество diff при больших рефакторингах.
6. **Тестируйте перед слиянием** — `git merge --no-commit feature` для проверки.
7. **Используйте `rerere`** для автоматического разрешения повторяющихся конфликтов.

---

## Дополнительная информация

### Связанные темы

- [Ветвление в Git](./git_branching.md) — merge vs rebase, fast-forward, squash merge.
- [Разрешение конфликтов](./git_conflict_resolution.md) — паттерны, mergetool, rerere при слиянии.
- [Git Rebase](./git_history_manipulation.md) — альтернатива merge для плоской истории.
- [Внутреннее устройство Git](./git_internals.md) — как Git разрешает общих предков при recursive.

### Официальные ресурсы

- **Git Merge Documentation:** [git-scm.com/docs/git-merge](https://git-scm.com/docs/git-merge)
- **Pro Git Book — Basic Branching:** [git-scm.com/book/ru/v2/Ветвление-в-Git](https://git-scm.com/book/ru/v2/Ветвление-в-Git)
