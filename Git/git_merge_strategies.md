# Git Merge — стратегии слияния

**Актуально для:** Git 2.33+ (ort по умолчанию) / Git 2.54+ (актуальная версия)

## Определения

**Merge strategy (Стратегия слияния)** — алгоритм, которым Git определяет, как объединить изменения из разных веток в один коммит слияния (merge commit). Выбирается через флаг `-s` или `-X` к `git merge`.

**Fast-forward (FF)** — слияние без создания merge-коммита. HEAD перемещается на коммит целевой ветки, если он является потомком текущего. Не изменяет историю.

**Recursive** — классическая стратегия (default до Git 2.33). Создаёт merge-коммит с двумя или более родителями. Рекурсивно объединяет общих предков при наличии нескольких.

**merge-ort** — стратегия по умолчанию с Git 2.33 (Ort = "Ostensibly Recursive's Twin"). Быстрее recursive, точнее обрабатывает переименования, меньше ложных конфликтов. Использует другой алгоритм поиска общего предка.

**Octopus** — стратегия для слияния трёх и более веток одновременно. Не поддерживает конфликты.

**Ours** — стратегия, которая при каждом конфликте сохраняет текущую версию (OURS), игнорируя изменения из другой ветки.

**Theirs** — стратегия (как опция `-X theirs`), которая при конфликте принимает версию из другой ветки (THEIRS).

**Resolve** — упрощённая стратегия (аналог рекурсивной для двух веток), требующая наличия уникального общего предка.

---

## Базовые концепты

### Основные стратегии (-s)

| Стратегия | Описание | Когда использовать |
| :--- | :--- | :--- |
| `ort` | По умолчанию с Git 2.33+. Быстрее recursive, лучше переименования, меньше ложных конфликтов. | Стандартное слияние двух веток (современный default) |
| `recursive` | Классическая стратегия (default до 2.33). Рекурсивно объединяет общих предков. | Совместимость, если ort ведёт себя иначе |
| `ours` | Игнорирует все изменения из присоединяемой ветки. Создаёт merge-коммит, но результат — наша версия. | Сохранение текущего состояния при слиянии «шумных» веток, vendoring |
| `octopus` | Сливает несколько веток без конфликтов (3+ ветки). | Массовое обновление зависимостей, release branches |
| `resolve` | Упрощённая стратегия для двух веток с одним общим предком. | Редко используется (legacy) |

> **Важно:** `ort` стал default в Git 2.33 (август 2021). В Git 2.54 (текущая) это подтверждённый, стабильный default. Флаг `-s recursive` всё ещё работает для обратной совместимости.

### Опции слияния (-X)

Опции применяются к стратегиям `ort` и `recursive`. Не работают с `ours`, `octopus`, `resolve`.

| Опция | Описание |
| :--- | :--- |
| `ours` | При конфликте сохраняет OURS (текущая ветка) |
| `theirs` | При конфликте принимает THEIRS (присоединяемая ветка) |
| `patience` | Использует алгоритм patience для поиска общих строк (точнее для переименований) |
| `diff-algorithm=patience` | Синоним `patience` |
| `diff-algorithm=minimal` | Минимальный diff (медленнее, точнее) |
| `diff-algorithm=histogram` | Гистограммный diff (хорош для больших файлов) |
| `ignore-all-space` | Игнорирует изменения в пробелах |
| `ignore-space-at-eol` | Игнорирует пробелы в конце строк |
| `ignore-cr-at-eol` | Игнорирует `\r` в конце строк |
| `ignore-blank-lines` | Игнорирует изменения, состоящие только из пустых строк |
| `ignore-space-change` | Игнорирует количество пробелей (но не их наличие) |
| `find-renames[=n]` | Включает детект переименований с порогом n% (default 50%) |
| `rename-threshold=n` | Синоним `find-renames=n` |
| `no-renames` | Отключает детект переименований |
| `no-renormalize` | Отключает `merge.renormalize` для этого merge |

> **Важно:** `-X ours` / `-X theirs` — это *опции стратегии ort/recursive*, а не отдельные стратегии. Они применяются только к конфликтующим участкам, не ко всему файлу. Стратегия `-s ours` игнорирует **все** изменения входящей ветки.

### Типы слияния

| Тип | Команда | Результат |
| :--- | :--- | :--- |
| Fast-forward | `git merge feature` (если возможно) | HEAD перемещается, merge-коммит не создаётся |
| No fast-forward | `git merge --no-ff feature` | Всегда создаёт merge-коммит |
| Squash merge | `git merge --squash feature` + `git commit` | Все изменения схлопываются в один коммит |
| Rebase + FF | `git rebase feature && git merge feature` | Плоская история без merge-коммитов |

---

## Практические сценарии

### Предварительные требования
* Git версии 2.33+ для стратегии `ort` по умолчанию
* Git версии 2.35+ для `merge.conflictStyle zdiff3`
* Инициализированный репозиторий с хотя бы одним коммитом

### Сценарий 1: Стандартное слияние (ort)

```bash
# Слить ветку feature в main
git checkout main
git merge feature
# → Merge made by the 'ort' strategy.
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

### Сценарий 3: Принудительный merge-коммит (--no-ff)

```bash
# Всегда создавать merge-коммит для сохранения контекста ветки
git merge --no-ff feature
# → Merge made by the 'ort' strategy.
```

**Валидация:**
```bash
git log --oneline --graph -3
# → *   e5f6g7h Merge branch 'feature'
# → |\
# → | * abc1234 feature: add validation
```

### Сценарий 4: Слияние с игнорированием пробелов

```bash
# Слить, игнорируя изменения пробелов
git merge -X ignore-all-space feature
# → Если конфликты были только из-за пробелов — они разрешатся автоматически
```

**Валидация:**
```bash
git status
# → nothing to commit, working tree clean
```

### Сценарий 5: Слияние с patience алгоритмом

```bash
# Использовать patience для более точного поиска общих строк
git merge -X patience feature
# Полезно при больших переименованиях функций
```

### Сценарий 6: Настройка детекта переименований

```bash
# Повысить порог детекта переименований до 70% (менее агрессивно)
git merge -X rename-threshold=70% feature

# Или через find-renames
git merge -X find-renames=70% feature

# Отключить детект переименований полностью
git merge -X no-renames feature
```

### Сценарий 7: Слияние с ours стратегией

```bash
# Взять только текущую версию при конфликтах (игнорирует ВСЕ изменения feature)
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

### Сценарий 8: Squash merge

```bash
# Схлопнуть все коммиты feature в один
git checkout main
git merge --squash feature
# → Squash commit -- not updating HEAD (squash коммиты в индексе)
git commit -m "feature: add complete validation module"
```

**Валидация:**
```bash
git log --oneline -3
# → abc1234 feature: add complete validation module
# → def5678 main: fix typo
```

**Edge cases:**
- После squash merge оригинальная ветка feature остаётся нетронутой.
- История feature не попадает в main — только итоговый результат.

### Сценарий 9: Массовое слияние (octopus)

```bash
# Слить несколько веток одновременно (без конфликтов)
git merge feature-a feature-b feature-c
# → Merge made by the 'octopus' strategy.
```

**Edge cases:**
- Если хотя бы одна ветка вызывает конфликт — octopus откажет.
- Используется в CI/CD для параллельного обновления зависимостей.

### Сценарий 10: Проверка результата перед коммитом (--no-commit)

```bash
# Слить без коммита для запуска тестов
git merge --no-commit --no-ff feature
# → Automatic merge went well; stopped before committing as requested

# Запустить тесты
make test
# или
./run-tests.sh

# Если тесты прошли — зафиксировать
git commit -m "merge: feature validation"

# Если тесты упали — откатить
git merge --abort
```

### Сценарий 11: Автоматическое разрешение конфликтов (-X ours/theirs)

```bash
# Принять нашу версию для всех конфликтов
git merge -X ours feature

# Принять их версию для всех конфликтов (полезно для dependabot)
git merge -X theirs dependabot/branch
```

### Сценарий 12: Отмена слияния

```bash
# До коммита слияния (в процессе)
git merge --abort

# После коммита слияния (через revert)
git revert -m 1 <merge-commit-sha>
# → Создаёт коммит, отменяющий изменения из feature
```

### Сценарий 13: Слияние с переименованием файлов

```bash
# При конфликтах переименований (rename/rename, rename/delete)
git merge -X rename-threshold=50% feature
# default 50% — можно настроить чувствительность
```

---

## Конфигурация (Configuration)

### Настройки merge по умолчанию

```bash
# Установить стратегию по умолчанию (обычно не требуется, ort — default)
git config --global merge.strategy ort

# Включить renormalize для файлов с фильтрами (LFS, git-crypt, .gitattributes)
# Виртуально прогоняет все три стадии через clean/smudge перед 3-way merge
git config --global merge.renormalize true

# Настроить стиль маркеров конфликта (рекомендуется zdiff3 для Git 2.35+)
git config --global merge.conflictStyle zdiff3
# Или diff3 для старых версий
git config --global merge.conflictStyle diff3

# Лимит файлов для детекта переименований (default: 7000)
git config --global merge.renameLimit 10000

# Включить rerere для автоматического разрешения повторяющихся конфликтов
git config --global rerere.enabled true
git config --global rerere.autoUpdate true  # автоматически git add после применения
```

### Драйвер merge=ours в .gitattributes

> **Важно:** `ours` — **не** встроенный драйвер. Без определения в конфиге Git молча применяет обычный 3-way merge.

```bash
# Настроить драйвер ours глобально
git config --global merge.ours.name "Keep ours"
git config --global merge.ours.driver true
```

```gitattributes
# .gitattributes — для lock-файлов всегда брать нашу версию
package-lock.json merge=ours
yarn.lock merge=ours
```

Альтернатива без конфига: `-merge` (встроенный драйвер `binary`) — тоже оставляет нашу версию, но помечает файл как конфликтный.

---

## Стратегия vs опции

| Флаг | Тип | Пример |
| :--- | :--- | :--- |
| `-s ort` | Стратегия | `git merge -s ort feature` |
| `-s recursive` | Стратегия | `git merge -s recursive feature` |
| `-s ours` | Стратегия | `git merge -s ours feature` |
| `-X ours` | Опция (модификатор) | `git merge -X ours feature` |
| `-X rename-threshold=70%` | Опция | `git merge -X rename-threshold=70% feature` |
| `-s ours -X theirs` | Комбинация | Редко — ours игнорирует, theirs не нужен |

---

## Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `CONFLICT (content): Merge conflict in file.py` | Конфликтующие изменения | Разрешить вручную или использовать `-X ours`/`theirs` |
| `fatal: refusing to merge unrelated histories` | Ветки не связаны общим предком | `git merge --allow-unrelated-histories feature` |
| `error: Merging is not possible` | octopus strategy не поддерживает конфликты | Использовать `ort` или разрешить конфликты |
| Merge commit не создаётся | Fast-forward сработал автоматически | `git merge --no-ff feature` для принудительного merge-коммита |
| `merge.renameLimit` исчерпан | Очень много переименований в одном merge | Увеличить: `git config merge.renameLimit 10000` |
| `zdiff3` не работает | Git < 2.35 | Использовать `diff3` или обновить Git |

---

## Устранение неполадок (Troubleshooting)

### Диагностика конфликтов

```bash
# Проверить текущие настройки merge
git config --list | grep -E 'merge|rerere'

# Показать все конфликтующие файлы с деталями
git status --short
# UU = both modified (unmerged)

# Посмотреть diff конфликта для файла
git diff file.py
# Или только конфликтующие хуки:
git diff --diff-filter=U file.py

# Проверить, какая стратегия используется
git merge --help | head -20  # в документации
# Или попробовать merge — в выводе будет: "Merge made by the 'ort' strategy."
```

### Разрешение конфликтов после merge

```bash
# После конфликта: принять нашу версию
git checkout --ours src/app.py
# или современный синоним:
git restore --ours src/app.py
git add src/app.py
git commit -m "merge: accept our version"

# Принять их версию
git checkout --theirs src/app.py
git add src/app.py
git commit -m "merge: accept their version"

# Перерисовать конфликт в стиле zdiff3 (добавит ||||||| base)
git restore --merge --conflict=zdiff3 config.yml
```

### Массовое разрешение (скриптовое)

```bash
# Принять OURS для всех конфликтующих файлов
git diff --name-only --diff-filter=U | xargs git checkout --ours
git diff --name-only --diff-filter=U | xargs git add
git commit -m "merge: accept ours for all conflicts"

# Или THEIRS
git diff --name-only --diff-filter=U | xargs git checkout --theirs
git diff --name-only --diff-filter=U | xargs git add
git commit -m "merge: accept theirs for all conflicts"
```

### Проблемы с переименованиями

```bash
# Конфликт rename/rename — обе ветки переименовали файл по-разному
# Ручное разрешение: выбрать имя или оставить оба
git status  # покажет оба файла как конфликтующие
# Отредактировать вручную, git add, git commit

# Конфликт delete/modify — одна ветка удалила, другая изменила
git checkout --ours <file>  # вернуть файл
git rm <file>               # подтвердить удаление
```

---

## Лучшие практики (Best Practices)

### Для команд DevOps/SRE

1. **Используйте `--no-ff`** для сохранения контекста ветки в истории (особенно в Git Flow, release branches).

2. **Squash merge для фичей** — если промежуточные коммиты не важны (GitHub Flow, Trunk-Based).

3. **`-X ours` для частых конфликтов** — при уверенности, что наша версия приоритетна (CI/CD автоматизация).

4. **Не используйте `-s ours` для реальных слияний** — он отбрасывает ВСЕ изменения входящей ветки.

5. **Patience для переименований** — `-X patience` или `-X diff-algorithm=patience` улучшает качество diff при больших рефакторингах.

6. **Тестируйте перед слиянием** — `git merge --no-commit --no-ff feature` для проверки результата.

7. **Включите `rerere`** глобально: `git config --global rerere.enabled true` — экономит время при повторных конфликтах.

8. **Настройте `merge.conflictStyle zdiff3`** — современный стандарт (Git 2.35+). Показывает базу и компактизирует общие строки.

9. **Используйте `merge.renormalize = true`** — если в проекте есть `.gitattributes` с фильтрами (LFS, git-crypt), предотвращает ложные конфликты.

10. **Для CI/CD: `merge -X theirs` для dependabot** — автоматизация авто-merge обновлений зависимостей.

11. **Документируйте сложные разрешения в коммите** — в теле merge-коммита объясните *почему* выбрано то или иное решение.

12. **Очищайте `.git/rr-cache` периодически** — старые разрешения могут стать неактуальными после рефакторинга.

### Для поддержки легаси и сложных случаев

- **Конфликты переименований (`rename/rename`, `rename/delete`)**: используйте `git merge -X rename-threshold=50%` для настройки чувствительности детекта переименований (default 50%).

- **Долгоживущие релизные ветки**: регулярно делайте `git merge main` в release-ветку с `--no-ff`, разрешая конфликты инкрементально.

- **Submodules**: конфликты в `.gitmodules` или submodule commit — разрешайте вручную, затем `git submodule update --init`.

- **Бинарные файлы**: Git не может мерджить бинарники. Используйте `git checkout --ours/--theirs` или LFS locking (`git lfs lock`).

---

## Дополнительная информация

### Связанные темы

- [Ветвление в Git](./git_branching.md) — merge vs rebase, fast-forward, squash merge, стратегии ветвления.
- [Разрешение конфликтов](./git_conflict_resolution.md) — паттерны, инструменты, rerere при слиянии.
- [Манипуляции с историей (Reset, Revert, Cherry-pick)](./git_history_manipulation.md) — откат изменений и перенос коммитов.
- [Атрибуты Git (.gitattributes)](./git_attributes.md) — merge=ours, merge=union, merge.renormalize, кастомные драйверы слияния.
- [Git Reflog](./git_reflog.md) — журнал ссылок для восстановления после неудачного merge.
- [Внутреннее устройство Git](./git_internals.md) — как Git разрешает общих предков при ort/recursive.
- [Рабочие процессы (Git Flow, GitHub Flow)](./git_workflows.md) — стратегии ветвления для команд.
- [Синхронизация с удаленным репозиторием](./git_synchronization.md) — push/pull веток, merge при pull.
- [Устранение неполадок Git](./git_troubleshooting.md) — диагностика проблем с merge.

### Официальные ресурсы

- **Git Merge Documentation:** [git-scm.com/docs/git-merge](https://git-scm.com/docs/git-merge)
- **Pro Git Book — Basic Branching:** [git-scm.com/book/ru/v2](https://git-scm.com/book/ru/v2)
- **Git Merge Strategies:** [git-scm.com/docs/merge-strategies](https://git-scm.com/docs/merge-strategies)
- **merge-ort announcement (Git 2.33 Release Notes):** [github.com/git/git/blob/master/Documentation/RelNotes/2.33.0.adoc](https://github.com/git/git/blob/master/Documentation/RelNotes/2.33.0.adoc)
