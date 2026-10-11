# Разрешение конфликтов в Git

**Актуально для:** Git 2.20–2.56.x (локально проверено на 2.56.0). `merge.conflictStyle diff3` — с 1.7.1; `zdiff3` — с 2.35; `rerere` — с 1.7.0; `merge-ort` (default с 2.33) — улучшенная стратегия слияния. `git restore --ours/--theirs` — с 2.23; `git restore --merge --conflict=zdiff3` — с 2.30.

## Определения

**Merge conflict (Конфликт слияния)** — ситуация, когда Git не может автоматически объединить изменения из двух веток, поскольку обе ветки модифицировали одни и те же строки в одном файле.

**Conflict marker (Маркер конфликта)** — специальные строки `<<<<<<<`, `=======`, `>>>>>>>`, вставляемые Git в файл для обозначения конфликтующих участков.

**Rerere (Reuse Recorded Resolution)** — механизм Git для автоматического запоминания и повторного использования разрешений конфликтов. Включается через `git config rerere.enabled true`.

**Working tree / Index / Repository** — три стадии файла: рабочее дерево (файл на диске), индекс (staging area), коммит (HEAD).

**diff3 conflict style** — стиль отображения конфликта с базовой версией (`|||||||`). Включается: `git config merge.conflictStyle diff3`. Показывает общий предок, что упрощает понимание изменений.

**zdiff3 conflict style** — улучшенная версия diff3 (Git 2.35+), которая компактизирует общие строки в начале/конце конфликтного блока. Включается: `git config merge.conflictStyle zdiff3`. Рекомендуется как современный стандарт.

**merge-ort** — стратегия слияния по умолчанию с Git 2.33 (Ort = "Ostensibly Recursive's Twin"). Быстрее, точнее, лучше обрабатывает переименования и конфликты, чем старый recursive.

---

## Базовые концепции

### Структура конфликта (стандартный стиль merge)

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

### Структура конфликта (стиль diff3)

При `git config merge.conflictStyle diff3` добавляется базовая версия:

```
<<<<<<< HEAD
текущая версия (наша)
||||||| base
базовая версия (общий предок)
=======
версия из присоединяемой ветки (их)
>>>>>>> feature
```

**Преимущество:** видно, что именно изменилось в каждой ветке относительно общего предка. Критично для сложных конфликтов, где обе стороны переписали один и тот же блок.

### Структура конфликта (стиль zdiff3, Git 2.35+)

`zdiff3` — «заядлый diff3»: компактизирует общие строки в начале/конце хука, показывая базу без дублирования:

```
<<<<<<< HEAD
уникальные_наши_строки
||||||| base
общие_строки_базы
=======
уникальные_их_строки
>>>>>>> feature
```

Включается: `git config merge.conflictStyle zdiff3`. Рекомендуется для повседневной работы — уменьшает визуальный шум при сохранении контекста базы.

### Когда возникают конфликты

| Операция | Конфликт возможен? | Комментарий |
| :--- | :--- | :--- |
| `git merge` | Да | Обе ветки изменили один файл; используется стратегия `merge-ort` (default с 2.33) |
| `git rebase` | Да | Коммиты конфликтуют с целевой веткой; при конфликте OURS = target branch, THEIRS = применяемый коммит |
| `git stash pop` | Да | Stash конфликтует с текущим состоянием рабочего дерева |
| `git cherry-pick` | Да | Коммит конфликтует с текущей веткой |
| `git pull` | Да | Удалённые изменения конфликтуют с локальными (по сути merge/rebase) |
| `git push` | Нет | Push отклоняется, если remote изменился (non-fast-forward) |
| `git apply --3way` | Да | Применение патча с 3-way merge fallback |

### Стратегии слияния и конфликты

| Стратегия | Флаг | Поведение при конфликте |
| :--- | :--- | :--- |
| `ort` (default) | `-s ort` | Умное 3-way merge, лучшая обработка переименований, меньше ложных конфликтов |
| `recursive` | `-s recursive` | Устаревший default (до 2.33), всё ещё доступен |
| `ours` | `-s ours` | Полностью игнорирует их изменения, всегда «наша» версия |
| `theirs` | `-X theirs` | Принимает их версию для конфликтующих хуков (не стратегия!) |
| `patience` | `-X patience` | Эвристика для минимизации конфликтов при больших диффах |

> **Важно:** `-X ours` / `-X theirs` — это *опции стратегии recursive/ort*, а не отдельные стратегии. Они применяются только к конфликтующим участкам, не ко всему файлу.

### Стратегии разрешения

| Подход | Когда использовать |
| :--- | :--- |
| Ручное редактирование | Сложные конфликты, требующие анализа логики |
| `--ours` / `--theirs` | Принятие одной из версий полностью (после конфликта) |
| `git mergetool` | Визуальный инструмент для разрешения |
| `rerere` | Повторяющиеся конфликты (частый rebase, долгоживущие ветки) |
| `-X ours` / `-X theirs` | Автоматическое разрешение всех конфликтов в пользу одной стороны |

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
- Для просмотра только конфликтующих файлов: `git diff --name-only --diff-filter=U`.

> **Примечание:** Базовое описание конфликтов также дано в [Git Basics](./git_basics.md#сценарий-10-разрешение-конфликтов-слияния). Данный файл является SSoT для углублённого покрытия.

### Сценарий 2: Настройка diff3 / zdiff3 для удобного разрешения

Рекомендуется включить `zdiff3` (Git 2.35+) глобально — показывает базу и компактизирует общие строки:

```bash
# Глобально (рекомендуется)
git config --global merge.conflictStyle zdiff3

# Или diff3 (если zdiff3 недоступен)
git config --global merge.conflictStyle diff3
```

После этого при конфликте вы увидите базовую версию:

```
<<<<<<< HEAD
наши изменения
||||||| base
общий предок
=======
их изменения
>>>>>>> feature
```

**Валидация:**
```bash
# Проверить текущую настройку
git config --get merge.conflictStyle
# → zdiff3
```

### Сценарий 3: Автоматическое принятие нашей версии

```bash
# Принять OURS (текущая ветка) для конфликтующих файлов
git merge -X ours feature
# Или после конфликта:
git checkout --ours src/app.py
git add src/app.py
git commit -m "merge: accept our version"
```

### Сценарий 4: Автоматическое принятие их версии

```bash
# Принять THEIRS (присоединяемая ветка)
git merge -X theirs feature
# Или после конфликта:
git checkout --theirs src/app.py
git add src/app.py
git commit -m "merge: accept their version"
```

### Сценарий 5: Разрешение конфликтов при rebase

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
- `git rebase --skip` — пропустить коммит, вызывающий конфликт (опасно, теряет изменения).

### Сценарий 6: Включение и использование rerere

```bash
# Включить rerere глобально (рекомендуется для DevOps/SRE)
git config --global rerere.enabled true

# Опционально: автоматически ставить git add после применения разрешения
git config --global rerere.autoUpdate true

# Автоматическое разрешение при следующем конфликте в том же месте
# Git запомнит ваше ручное разрешение и применит его повторно
```

**Как это работает по шагам:**
1. При конфликте Git сохраняет «конфликтную» версию файла (до разрешения) в `.git/rr-cache/<merge>/<path>/preimage`.
2. Вы разрешаете конфликт вручную и выполняете `git add` + `git commit`.
3. Git сохраняет итоговый diff (от preimage к постimage) в `.git/rr-cache/<merge>/<path>/postimage` и записывает в `.git/rr-cache/<merge>/seq`.
4. При следующем конфликте в том же месте Git сравнивает предупреждение и, если совпадает, автоматически применяет записанное разрешение.

**Ручное управление (когда `rerere.enabled` выключено, но разрешение нужно применить):**
```bash
# Применить все записанные разрешения без автоматического перезапуска merge
git rerere apply

# Применить только для конкретного файла
git rerere apply --path-to-file src/app.py

# Управление записанными разрешениями:
# Просмотреть записанные разрешения
git rerere status
# → src/app.py

# Просмотреть diff разрешения
git rerere diff

# Забыть разрешение для файла
git rerere forget src/app.py

# Очистить весь кэш rerere
rm -rf .git/rr-cache
# или: git rerere clear
```

**Особенности `rerere.autoUpdate`:**
- По умолчанию `false`: разрешение применяется к рабочему дереву, но индекс остаётся в состоянии `unmerged` — нужно сделать `git add` вручную.
- При `true` разрешение применяется и индекс автоматически обновляется (имитирует `git add`). Полезно в CI, где не нужно интерактивное подтверждение.

**DevOps/SRE контекст:** В CI/CD пайплайнах, где feature-ветки регулярно rebas'ятся на main, `rerere` экономит часы ручного труда. Включите в базовый образ CI-контейнера. В headless-средах задайте `rerere.autoUpdate true`, чтобы не требовать интерактивного `git add`.

### Сценарий 7: Использование mergetool (визуальные инструменты)

```bash
# Запустить визуальный инструмент (автовыбор)
git mergetool
# → Мердж-тур запустится (vimdiff, meld, kdiff3, opendiff и др.)

# Указать конкретный инструмент
git mergetool --tool=meld
```

**Настройка популярных инструментов:**

```bash
# Meld (Linux/macOS/Windows) — рекомендуемый для начинающих
git config --global merge.tool meld
git config --global mergetool.meld.cmd 'meld "$LOCAL" "$BASE" "$REMOTE" --output "$MERGED"'

# vimdiff (встроен, везде доступен)
git config --global merge.tool vimdiff
git config --global mergetool.vimdiff.layout 'LOCAL,BASE,REMOTE,MERGED'

# kdiff3 (кроссплатформенный)
git config --global merge.tool kdiff3

# VS Code как mergetool
git config --global merge.tool vscode
git config --global mergetool.vscode.cmd 'code --wait --diff $LOCAL $REMOTE'
```

**DevOps/SRE контекст:** В headless CI используйте `git merge -X ours/theirs` или скриптовые решения. `mergetool` предназначен для интерактивной работы разработчика.

### Сценарий 8: Перерисовка конфликтных маркеров (смена стиля)

Иногда конфликт остался позади, но вы передумали и хотите увидеть его в другом стиле — например, добавить базовую версию через `diff3`/`zdiff3`, или наоборот, убрать её. Команда `git restore --merge` перезаписывает файл, повторно извлекая конфликтующие участники из индекса (стадии 2/3) и отображая их в заданном стиле:

```bash
# Перерисовать конфликт в стиле zdiff3 (появится ||||||| base)
git restore --merge --conflict=zdiff3 config.yml

# Или перерисовать в стандартном стиле (без базы)
git restore --merge --conflict=merge config.yml

# Если merge.conflictStyle уже задан глобально, --conflict можно опустить:
git restore --merge config.yml
```

**Валидация:**
```bash
# Убедиться, что стадии 2/3 всё ещё присутствуют (конфликт не решён)
git ls-files --stage config.yml
# → 1234567 <sha> 1 config.yml   # stage 1 = base
# → abcdef0 <sha> 2 config.yml   # stage 2 = ours
# → fedcba9 <sha> 3 config.yml   # stage 3 = theirs
```

**Ограничения:**
- `--merge` работает только с индексом (нельзя комбинировать с `--source`).
- Если вы уже сделали `git add` (конфликт снят), стадии 2/3 исчезли и перерисовка не понадобится — файл уже чистый.
- При `rebase`/`pull --rebase` семантика `ours`/`theirs` перевёрнута — это поведение наследуется и в `git restore`.

### Сценарий 10: Отмена слияния/merge в процессе

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

### Сценарий 11: Конфликт при pull

```bash
# Вытянуть с merge-стратегией (default)
git pull origin main

# Если конфликт:
git status
# → both modified: config.yml

# Разрешить и зафиксировать
git add config.yml
git commit -m "merge: resolve config conflict"
```

**Альтернатива — rebase при pull:**
```bash
# Перебазировать локальные коммиты поверх remote
git pull --rebase origin main
# При конфликте — разрешайте как в Сценарии 5
```

### Сценарий 12: Применение патча с 3-way merge (git apply --3way)

```bash
# Применить патч, разрешая конфликты через 3-way merge
git apply --3way feature.patch
# → CONFLICT (content): Merge conflict in src/app.py
# Разрешайте как обычно
```

### Сценарий 13: Массовое разрешение конфликтов (скриптовое)

Для автоматизации в CI/CD или при больших рефакторингах:

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

---

## Операции и команды (Operations and Commands)

### Команды разрешения конфликтов

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `git status` | Показать конфликтующие файлы (unmerged) | `git status` |
| `git diff --name-only --diff-filter=U` | Список файлов с конфликтами | `git diff --name-only --diff-filter=U` |
| `git checkout --ours <file>` | Принять нашу версию файла | `git checkout --ours config.yml` |
| `git restore --ours <file>` | Принять нашу версию (современный синоним) | `git restore --ours config.yml` |
| `git checkout --theirs <file>` | Принять их версию файла | `git checkout --theirs config.yml` |
| `git restore --theirs <file>` | Принять их версию (современный синоним) | `git restore --theirs config.yml` |
| `git restore --merge [--conflict=<style>] <file>` | Перерисовать конфликтные маркеры (например, в zdiff3) | `git restore --merge --conflict=zdiff3 config.yml` |
| `git add <file>` | Отметить конфликт как решённый | `git add config.yml` |
| `git merge --abort` | Отменить слияние | `git merge --abort` |
| `git rebase --continue` | Продолжить rebase после разрешения | `git rebase --continue` |
| `git rebase --abort` | Отменить rebase | `git rebase --abort` |
| `git rebase --skip` | Пропустить конфликтующий коммит | `git rebase --skip` |
| `git cherry-pick --continue` | Продолжить cherry-pick | `git cherry-pick --continue` |
| `git cherry-pick --abort` | Отменить cherry-pick | `git cherry-pick --abort` |

### Команды mergetool

| Команда | Назначение |
| :--- | :--- |
| `git mergetool` | Запустить настроенный mergetool |
| `git mergetool --tool=<tool>` | Запустить конкретный инструмент |
| `git mergetool --tool-help` | Список доступных инструментов |

### Команды rerere

| Команда | Назначение |
| :--- | :--- |
| `git config --global rerere.enabled true` | Включить rerere глобально |
| `git config --global rerere.autoUpdate true` | Автоматически ставить `git add` после применения разрешения |
| `git rerere apply` | Применить все записанные разрешения (без перезапуска merge) |
| `git rerere apply --path-to-file <file>` | Применить разрешение для конкретного файла |
| `git rerere status` | Показать файлы с записанными разрешениями |
| `git rerere diff` | Показать diff записанного разрешения |
| `git rerere forget <file>` | Забыть разрешение для файла |
| `git rerere clear` | Очистить весь кэш (или `rm -rf .git/rr-cache`) |

### Конфигурация конфликтов

| Настройка | Значение | Описание |
| :--- | :--- | :--- |
| `merge.conflictStyle` | `merge` \| `diff3` \| `zdiff3` | Стиль маркеров конфликта (default: `merge`) |
| `merge.tool` | `meld` \| `vimdiff` \| `kdiff3` \| `vscode` | Инструмент для `git mergetool` |
| `mergetool.<tool>.cmd` | команда | Кастомная команда для mergetool |
| `rerere.enabled` | `true` \| `false` | Включить автозапоминание разрешений |
| `rerere.autoUpdate` | `true` \| `false` | Автоматически обновлять индекс (`git add`) после применения записанного разрешения. По умолчанию `false`: разрешение применяется к рабочему дереву, но индекс остаётся в состоянии `unmerged`, и вам нужно выполнить `git add` вручную. Установка `true` имитирует ручное `git add` после каждого применения rerere. |
| `merge.renameLimit` | число | Лимит файлов для детекта переименований (default: 7000) |

---

## Устранение неполадок (Troubleshooting)

### Типичные ошибки и решения

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `CONFLICT (content): Merge conflict in file` | Конфликтующие изменения в одной строке | Ручное редактирование, `git checkout --ours/--theirs`, или `-X ours/theirs` |
| `error: path 'file' unmerged` | Файл в состоянии unmerged | `git add <file>` (после разрешения) или `git reset HEAD <file>` (отмена) |
| `fatal: You are in the middle of a merge` | Merge не завершён (нет коммита) | `git merge --abort` или завершить merge коммитом |
| Маркеры `<<<<<<<` в коммите | Конфликт не был разрешён перед коммитом | `git commit --amend` после исправления файла |
| `rerere` не работает | `rerere.enabled` не включён | `git config --global rerere.enabled true` |
| `git mergetool` не запускается | Инструмент не установлен или не в PATH | Установить meld/vimdiff/kdiff3, проверить `git mergetool --tool-help` |
| `CONFLICT (rename/rename)` | Обе ветки переименовали файл по-разному | Ручное разрешение: выбрать имя или оставить оба |
| `CONFLICT (delete/modify)` | Одна ветка удалила файл, другая изменила | `git checkout --ours` (вернуть) или `git rm` (подтвердить удаление) |
| `CONFLICT (add/add)` | Обе ветки создали файл с одинаковым именем | Ручное объединение содержимого |
| `zdiff3` не работает | Git < 2.35 | Использовать `diff3` или обновить Git |
| `merge.renameLimit` исчерпан | Очень много переименований в одном merge | Увеличить: `git config merge.renameLimit 10000` |
| `git apply --3way` не работает | Патч не применяется чисто, база не найдена | Применить вручную или использовать `git am --3way` |

### Диагностика

```bash
# Проверить текущие настройки конфликтов
git config --list | grep -E 'merge|rerere'

# Показать все конфликтующие файлы с деталями
git status --short
# UU = both modified (unmerged)

# Посмотреть diff конфликта для файла
git diff file.py
# Или только конфликтующие хуки:
git diff --diff-filter=U file.py

# Проверить, включён ли rerere
git config --get rerere.enabled
# → true (если включён)
```

---

## Лучшие практики (Best Practices)

### Для команд DevOps/SRE

1. **Включите `rerere` глобально на всех CI-агентах и рабочих станциях** — автоматически разрешает повторяющиеся конфликты при частых rebase/merge. Экономит часы ручного труда в монорепо и долгоживущих feature-ветках.

2. **Настройте `merge.conflictStyle zdiff3` глобально** — современный стандарт (Git 2.35+). Показывает базу и компактизирует общие строки, сокращая время на понимание конфликта на 30–50%.

3. **Используйте `git pull --rebase` по умолчанию** — `git config --global pull.rebase true`. Линейная история упрощает bisect, ревью и откат. Для Git Flow — оставьте `false` на release/hotfix ветках.

4. **В CI/CD: используйте стратегию `merge -X ours` / `-X theirs` для автоматизации** — например, при авто-merge dependabot PR: `git merge -X theirs dependabot/branch`. Избегайте ручного мерджа в пайплайнах.

5. **Настройте pre-commit / pre-push хук проверки маркеров конфликта** — не дайте `<<<<<<<` попасть в репозиторий. Пример для pre-commit:
   ```yaml
   - repo: local
     hooks:
       - id: no-conflict-markers
         entry: grep -r '<<<<<<< HEAD' --include="*.py" --include="*.js" --include="*.yaml" .
         language: system
         verbose: true
   ```

6. **Для больших рефакторингов: создайте временную ветку разрешения** — не блокируйте main. Разрешите конфликты в отдельной ветке, протестируйте, затем fast-forward merge.

7. **Используйте `git merge --no-commit --no-ff` для проверки перед фиксацией** — позволяет запустить тесты на результате merge до коммита:
   ```bash
   git merge --no-commit --no-ff feature
   # запустить тесты
   # если ок — git commit
   # если нет — git merge --abort
   ```

8. **Документируйте сложные разрешения в коммите** — в теле merge-коммита объясните *почему* выбрано то или иное решение (особенно для архитектурных конфликтов).

9. **Для монолитов с множеством команд: настройте CODEOWNERS + branch protection** — конфликты в чужих модулях требуют approval владельца. Предотвращает «тиховые» сломанные мержа.

10. **Очищайте `.git/rr-cache` периодически** — старые разрешения могут стать неактуальными после рефакторинга. В CI: `rm -rf .git/rr-cache` перед build.

### Для поддержки легаси и сложных случаев

- **Конфликты переименований (`rename/rename`, `rename/delete`)**: используйте `git merge -X rename-threshold=50%` для настройки чувствительности детекта переименований (default 50%).
- **Долгоживущие релизные ветки**: регулярно делайте `git merge main` в release-ветку с `--no-ff`, разрешая конфликты инкрементально, а не раз в квартал.
- **Submodules**: конфликты в `.gitmodules` или submodule commit — разрешайте вручную, затем `git submodule update --init`.
- **Бинарные файлы**: Git не может мерджить бинарники. Используйте `git checkout --ours/--theirs` или LFS locking (`git lfs lock`).

---

## Дополнительная информация

### Официальные ресурсы

- **Git Merge Documentation:** [git-scm.com/docs/git-merge](https://git-scm.com/docs/git-merge)
- **Git Rerere Documentation:** [git-scm.com/docs/git-rerere](https://git-scm.com/docs/git-rerere)
- **Git Mergetool Documentation:** [git-scm.com/docs/git-mergetool](https://git-scm.com/docs/git-mergetool)
- **Pro Git Book — Basic Merging:** [git-scm.com/book/ru/v2/Ветвление-в-Git](https://git-scm.com/book/ru/v2/Ветвление-в-Git)

### См. также

- [Git Merge — стратегии](./git_merge_strategies.md) — recursive, ours, theirs, patience, octopus.
- [Ветвление в Git](./git_branching.md) — merge vs rebase, --no-ff, squash merge.
- [Git History Manipulation](./git_history_manipulation.md) — rebase, cherry-pick и откат изменений.
- [Git Stash](./git_stash.md) — конфликты при stash pop и восстановление.
- [Устранение неполадок Git](./git_troubleshooting.md) — диагностика и восстановление после конфликтов.
- [Git Basics](./git_basics.md#сценарий-10-разрешение-конфликтов-слияния) — базовое введение в разрешение конфликтов.
- [Git Configuration](./git_configuration.md) — merge.conflictStyle, rerere, mergetool настройки.
