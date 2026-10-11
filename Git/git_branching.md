# Ветвление в Git: механизмы, стратегии и управление

**Актуально для:** Git 2.56+

## Определения

* **Ветка (Branch):** Подвижный указатель на один из коммитов. Ветка всегда указывает на **последний коммит** в своей цепочке. Это изолированная линия разработки, позволяющая вести параллельную работу над разными задачами. Внутренне хранится как файл в `.git/refs/heads/` или запись в `packed-refs`.
* **HEAD:** Указатель на текущую позицию в истории коммитов. Обычно `HEAD` указывает на имя текущей ветки (символическая ссылка `.git/HEAD -> refs/heads/main`). В состоянии "detached HEAD" указывает напрямую на хэш коммита.
* **Слияние (Merge):** Процесс интеграции изменений из одной ветки в другую. Результатом является новый "коммит слияния" (merge commit), который имеет двух родителей и объединяет истории обеих веток. Поддерживает стратегии: `ort` (по умолчанию с Git 2.33+), `recursive`, `ours`, `theirs`, `octopus`.
* **Перебазирование (Rebase):** Альтернативный метод интеграции. `rebase` перемещает коммиты из одной ветки и "накладывает" их поверх последнего коммита другой ветки, создавая линейную историю. При этом коммиты **переписываются** (получают новые хэши).
* **Удаленная ветка (Remote-tracking branch):** Локальная ссылка на состояние ветки в удаленном репозитории (например, `origin/main`). Она обновляется при выполнении `fetch` или `pull` и не предназначена для прямого редактирования. Хранится в `.git/refs/remotes/`.
* **Upstream (Tracking branch):** Конфигурация `branch.<name>.remote` и `branch.<name>.merge`, связывающая локальную ветку с удалённой. Позволяет использовать `git pull`/`git push` без аргументов.
* **Orphan-ветка:** Ветка, не имеющая родительских коммитов (пустая история). Используется для создания новой ветки с нуля в существующем репозитории (например, для документации или `gh-pages`).
* **Cherry-pick (Выборочное копирование):** Механизм применения изменений, представленных одним или несколькими конкретными коммитами из одной ветки, в текущую ветку без полного слияния веток.
* **Fast-forward (FF):** Слияние без создания коммита слияния, когда целевая ветка является прямым предком исходной. Указатель просто передвигается вперёд.
* **Reflog:** Журнал изменений указателей (HEAD, веток). Позволяет восстановить удалённые ветки и откатить ошибочные операции. Хранится в `.git/logs/`.

---

## Базовые концепции

### Эволюция команд: switch против checkout
Исторически для переключения веток и восстановления файлов использовалась перегруженная команда `git checkout`. Начиная с Git 2.23, функционал разделен на две специализированные команды:
* `git switch` — исключительно для переключения веток и создания новых.
* `git restore` — для восстановления файлов в рабочем дереве или индексе.
*Использование `git switch` предпочтительнее, так как оно исключает случайную перезапись файлов.*

### Upstream (Tracking) — связь с удалённой веткой
Каждая локальная ветка может быть настроена на отслеживание удалённой ветки (upstream). Это делается автоматически при клонировании или командой `git push -u` / `git branch -u`.
Конфигурация хранится в `.git/config`:
```ini
[branch "feature/auth"]
    remote = origin
    merge = refs/heads/feature/auth
```
**Польза:** позволяет использовать `git pull`, `git push`, `git status` (показывает ahead/behind), `git branch -vv` без указания remote/branch. Команда `git branch --delete-merged` (Git 2.56+) использует эту связь для безопасной очистки слитых веток.

### Конвенции именования веток

Правильное именование веток обеспечивает понимание их назначения и упрощает навигацию по графу коммитов. Существует несколько распространенных конвенций:

**Типовые префиксы (Conventional Branches):**

| Префикс | Назначение | Пример |
|---------|------------|--------|
| `feature/` | Разработка новой функциональности | `feature/user-auth` |
| `bugfix/` | Исправление бага | `bugfix/login-error` |
| `hotfix/` | Срочное исправление в production | `hotfix/security-patch` |
| `release/` | Подготовка релиза | `release/v1.2.0` |
| `chore/` | Техническая работа (рефакторинг, обновление зависимостей) | `chore/update-deps` |
| `docs/` | Документация | `docs/api-reference` |
| `test/` | Тестирование | `test/e2e-flows` |
| `fix/` | Исправление (альтернатива `bugfix/`) | `fix/memory-leak` |
| `refactor/` | Рефакторинг без изменения функционала | `refactor/auth-module` |
| `experiment/` | Экспериментальные изменения, не для слияния | `experiment/new-algo` |
| `wip/` | Работа в процессе (Work In Progress) | `wip/refactor-db` |

**Рекомендации по именованию:**

* **Используйте нижний регистр и дефисы:** `feature/user-auth` (а не `Feature/UserAuth` или `feature/user_auth`).
* **Будьте описательными:** `bugfix/fix-null-pointer-in-login` лучше, чем `bugfix/fix1`.
* **Включайте ID задачи (если есть):** `feature/JIRA-123-user-profile` или `feature/123-user-profile`.
* **Избегайте:** личных имен (`john/feature`), общих слов (`fix`, `new`), специальных символов.
* **Длина:** Стремитесь к краткости, но сохраняйте осмысленность (обычно 3-5 слов).
* **Для автоматизации CI/CD:** Имена веток часто используются в паттернах триггеров (например, `feature/**`, `release/*`), поэтому согласованность критична.

**Иерархическая структура:** Ветки могут использовать `/` для создания иерархии: `feature/auth/oauth2`, `bugfix/payment/timeout`. Это позволяет группировать связанные задачи и упрощает визуализацию в графе коммитов.

### Состояние "Отсоединенный HEAD" (Detached HEAD)

Это состояние, когда `HEAD` ссылается не на ветку, а напрямую на хэш конкретного коммита. Это происходит при переключении на коммит, не являющийся концом ветки (например, `git switch --detach a1b2c3d` или переключение на тег).

**Технические нюансы:**
* Полезно для инспекции истории, запуска тестов для старой версии или временных экспериментов.
* **Риск:** Новые коммиты, созданные в этом состоянии, не принадлежат ни одной ветке. После переключения на существующую ветку (например, `main`), эти коммиты станут недоступными по имени и будут удалены сборщиком мусора (`git gc`).
* **Решение:** Чтобы сохранить работу, сделанную в состоянии "detached HEAD", необходимо создать новую ветку: `git switch -c <имя_новой_ветки>`.
* **Восстановление:** Если уже переключились — найдите коммит через `git reflog` и создайте ветку: `git branch recovery <хэш>`.

### Перенос незакоммиченных изменений

В Git ветка — это лишь именованный указатель (ссылка) на конкретный коммит. Рабочее дерево (Working Directory) и индекс (Staging Area) не "принадлежат" конкретной ветке до момента совершения коммита.

**Ключевая особенность:**
Если у вас есть незакоммиченные изменения (dirty state) и вы создаете новую ветку (`git switch -c`), эти изменения "следуют" за вами на новую ветку. Это позволяет начать работу в `main`, осознать необходимость отдельной ветки и перенести все наработки в один шаг, не используя `stash`.

**Условия переноса:**
* Перенос успешен, если изменения в рабочем дереве не конфликтуют с файлами в целевой ветке.
* Если конфликты есть, Git заблокирует переключение и предложит сделать `stash` или `commit`.

### Сравнение Merge и Rebase

#### 1. Механизм Merge (Сохранение истории)
`git merge` создает новый "коммит слияния" (`F`), объединяющий истории обеих веток.

**Исходное состояние:**
```text
      D---E <-- feature
     /
A---B---C <-- main
```
**Результат после `git merge feature` в ветке `main`:**
```text
      D---E
     /     \
A---B---C---F <-- main, feature
```
* **Fast-Forward:** Если в `main` не было новых коммитов с момента ветвления, Git просто передвинет указатель `main` вперед. Чтобы принудительно создать коммит слияния для сохранения структуры, используйте `git merge --no-ff`.
* **Squash merge:** `git merge --squash` объединяет все коммиты в один без создания merge commit. Полезно для очистки истории feature-ветки перед вливанием в main.
* **Стратегии слияния:** `ort` (по умолчанию, быстрее recursive), `recursive`, `ours` (игнорирует входящие изменения), `theirs`, `octopus` (3+ веток).

#### 2. Механизм Rebase (Переписывание истории)
`rebase` перемещает коммиты ветки, применяя их поверх последнего коммита целевой ветки.

**Результат после `git rebase main` в ветке `feature`:**
```text
A---B---C---D'---E' <-- feature
```
* **Важно:** Коммиты `D` и `E` заменяются на новые `D'` и `E'` с другими хешами.
* **Золотое правило:** НИКОГДА не используйте rebase для публичных веток (доступных другим разработчикам), так как это разрушает их локальную историю и вызывает рассинхронизацию при `git pull` у остальных участников.
* **Rebase с сохранением merge-коммитов:** `git rebase --rebase-merges` сохраняет структуру слияний внутри ветки.

#### 3. Критерии выбора стратегии

1. **Публичность ветки:** Только merge для общих веток (`main`, `develop`, `release/*`).
2. **Чистота истории:** Rebase дает идеальную линию (удобно для feature-веток одного разработчика), Merge сохраняет контекст "когда и что влито".
3. **Сложность отмены:** Merge отменяется легко (`git revert -m 1`), Rebase требует работы с `reflog`.
4. **Автоматизация CI/CD:** Rebase часто предпочтителен для фича-веток перед вливанием в `main` для поддержания линейности, но требует осторожности при совместной работе.
5. **Командная политика:** В trunk-based development — rebase/squash; в Git Flow — merge с `--no-ff`.

### Стратегии ветвления (Branching Strategies)

Стратегия ветвления определяет, как команда организует процесс разработки через ветки. Выбор стратегии зависит от частоты релизов, требований к стабильности и зрелости команды. Подробное описание каждой модели (Git Flow, GitHub Flow, Trunk-Based, GitLab Flow, Forking) см. в **[Рабочие процессы Git](./git_workflows.md)**.

**Краткий обзор для выбора:**

| Стратегия | Ветки | Релизы | Подходит для |
|-----------|-------|--------|--------------|
| **Trunk-Based** | `main` + короткоживущие feature | Непрерывные | Высокочастотные релизы, CI/CD, DevOps |
| **GitHub Flow** | `main` + feature | По готовности feature | Веб-приложения, непрерывный деплой |
| **GitLab Flow** | `main`, `pre-production`, `production` + feature | По средам | Среды стейджинга/продакшена |
| **Git Flow** | `main`, `develop`, `feature/*`, `release/*`, `hotfix/*` | Планируемые версии | Десктоп/мобильные apps, версионирование |
| **Forking** | Форк + PR | Различные | Open source, внешние контрибьюторы |

---

## Практические сценарии

### Предварительные требования
* **Git версии 2.23+** — для современных команд `git switch` / `git restore`.
* **Git версии 2.56+** — для команды `git branch --delete-merged`, `git history drop`, `git refs` toolbox.
* Инициализированный репозиторий с хотя бы одним коммитом.
* Настроенные `user.name` и `user.email`.

### Управление ветками

```bash
# Список всех веток (локальные и удаленные)
git branch -a

# Список веток и их связи с удаленными (upstream)
git branch -vv

# Поиск веток по коммиту (в каких ветках содержится конкретный коммит)
git branch --contains <хэш_коммита>

# Список веток, которые уже слиты в текущую (безопасно удалять)
git branch --merged
# →   feature/login-fix
# → * main

# Список веток, содержащих уникальные коммиты (не слитые в текущую)
git branch --no-merged

# НОВОЕ в Git 2.56+: Массовое удаление слитых веток (safe cleanup)
# Параметр — паттерн remote-tracking веток, например 'origin/*'
# --dry-run показывает что бы удалилось без реального удаления
git branch --delete-merged 'origin/*' --dry-run
# → Would delete branch feature/login (was abc1234).
# → Would delete branch feature/login-fix (was def5678).

# Без --dry-run удаляет локальные ветки, чей tip достижим из настроенного upstream.
# Не удаляются, если:
# - у ветки нет настроенного upstream или upstream больше не существует;
# - ветка открыта в каком-либо worktree;
# - пуш в её remote обновил бы её own upstream (нельзя отличить от только что слитой);
# - она является локальным upstream для ветки, которая не удаляется;
# - для неё задано branch.<name>.deleteMerged = false.
# Ветки с неразлитой работой (tip не достижим из upstream) пропускаются без предупреждения.
git branch --delete-merged 'origin/*'
# → Deleted branch feature/login (was abc1234).
# → Deleted branch feature/login-fix (was def5678).

# Точечная очистка по категориям
git branch --delete-merged 'origin/feature/*' --dry-run
git branch --delete-merged 'origin/topic/*' --dry-run

# Защита ветки от авто-удаления через --delete-merged
git config branch.feature/long-term.deleteMerged false

# Создание и переход (Современные команды)
git switch -c feature/cool-stuff
# → Switched to a new branch 'feature/cool-stuff'

# Переключение на существующую
git switch main

# Переименование текущей ветки
git branch -m <новое_имя>

# Удаление ветки
git branch -d feature/name      # Удалить, только если она слита
git branch -D feature/name      # Принудительное удаление

# Удаление удаленной ветки
git push origin --delete feature/name  # Удалить ветку на сервере
git push origin -d feature/name        # Короткая форма

# Очистка удаленных веток из локального кэша
git fetch --prune                  # Удалить remote-tracking ветки, которых нет на сервере
git remote prune origin            # То же самое (устаревший способ)

# Привязка локальной ветки к удаленной (upstream)
git branch -u origin/<имя_ветки>

# Публикация новой ветки на сервер с одновременной установкой upstream
git push -u origin feature/cool-stuff

# Создание Orphan-ветки (без истории)
git switch --orphan docs
git rm -rf .

# Работа с несколькими удаленными репозиториями (remote)
git remote add upstream https://github.com/original/repo.git  # Добавить upstream
git remote -v                                                # Просмотреть все remote
git fetch upstream                                           # Загрузить изменения из upstream
git merge upstream/main                                      # Влить изменения из upstream в локальную ветку
git push upstream feature/branch                             # Отправить ветку в upstream

# НОВОЕ в Git 2.56+: Управление референциями через git refs (low-level)
git refs create refs/heads/new-topic <commit-hash>
git refs update refs/heads/topic <new-commit-hash> [<old-commit-hash>]  # compare-and-swap
git refs delete refs/heads/old-topic [<old-commit-hash>]
git refs rename refs/heads/old-name refs/heads/new-name
```

**Примечание:** Подробное описание работы с удалёнными репозиториями, включая `fetch`, `pull`, `push` и синхронизацию, см. в **[Синхронизация репозиториев](./git_synchronization.md)**.

### Слияние веток (Merge)

```bash
# Обычное слияние (Fast-forward, если возможно)
git merge <имя_ветки>

# Слияние без Fast-forward (принудительное создание merge commit)
git merge --no-ff <имя_ветки>

# Слияние с объединением всех коммитов в один (Squash)
# Полезно для "грязных" feature-веток. Не создает коммит автоматически.
git merge --squash <имя_ветки>

# Использование специфической стратегии (например, octopus для 3+ веток)
git merge branch1 branch2 branch3

# Стратегия ort (по умолчанию в Git 2.33+, быстрее recursive)
git merge -s ort <имя_ветки>

# Стратегия ours (игнорировать изменения из входящей ветки)
git merge -s ours <имя_ветки>

# Отмена слияния при возникновении конфликтов
git merge --abort

# Автоматическое разрешение конфликтов в пользу "нашей" версии (для CI)
git merge -X ours <имя_ветки>
git merge -X theirs <имя_ветки>
```

### Выборочное копирование коммитов (Cherry-pick)

Используется для переноса отдельных фиксов или фич между ветками (например, бэкпорт хотфикса в старый релиз). Подробные сценарии использования и флаги описаны в разделе **[Cherry-pick в Манипуляциях с историей](./git_history_manipulation.md#сценарий-4-выборочный-перенос-изменений-cherry-pick)**.

```bash
# Применить один коммит в текущую ветку
git cherry-pick <хэш_коммита>

# Применить диапазон коммитов
git cherry-pick A..B

# Без создания коммита (для ручного редактирования)
git cherry-pick -n <хэш_коммита>

# Подписать коммит (GPG)
git cherry-pick -s <хэш_коммита>
```

### Интерактивное перебазирование (Rebase Interactive)

Используется для очистки истории (объединение коммитов, изменение сообщений) перед слиянием. Полный список команд интерактивного режима и примеры их использования находятся в файле **[Манипуляции с историей](./git_history_manipulation.md#сценарий-3-интерактивное-перебазирование-rebase-i)**.

```bash
git rebase -i HEAD~3
```
**Команды управления (в редакторе):**
* `pick` (p): использовать коммит.
* `reword` (r): использовать коммит, но изменить сообщение.
* `edit` (e): использовать коммит, но остановиться для редактирования.
* `squash` (s): объединить с предыдущим коммитом, объединяя сообщения.
* `fixup` (f): объединить с предыдущим коммитом, отбросив сообщение текущего.
* `drop` (d): удалить коммит.
* `exec` (x): выполнить shell-команду (например, запустить тесты).
* `break` (b): остановиться здесь (продолжить `git rebase --continue`).
* `label` / `reset` / `merge`: для работы с `--rebase-merges`.

### Разрешение конфликтов при Rebase

В отличие от merge, при rebase конфликты разрешаются пошагово для каждого коммита в переносимой цепочке. Подробная стратегия разрешения конфликтов и трассировка доступны в файле **[Устранение неполадок](./git_troubleshooting.md)**.

1. **Остановка:** Git останавливается на коммите, который не удалось применить автоматически.
2. **Анализ:** Проверьте состояние файлов с помощью `git status`. Откройте файлы с маркерами конфликта (`<<<<<<<`, `=======`, `>>>>>>>`).
3. **Исправление:** Отредактируйте файлы, выбрав нужные строки и удалив маркеры.
4. **Фиксация шага:**
   ```bash
   git add <файл>
   git rebase --continue
   ```
5. **Пропуск:** Если изменения коммита больше не нужны (например, они уже есть в целевой ветке): `git rebase --skip`.
6. **Отмена:** Если процесс стал слишком сложным: `git rebase --abort`.
7. **Автоматизация через rerere:** Включите `git config --global rerere.enabled true` — Git запомнит ваши решения и применит их автоматически при повторных конфликтах.

### Продвинутые техники Rebase

#### 1. Автоматическое объединение (Autosquash)
Позволяет быстро исправить предыдущие коммиты без ручного выбора команд в интерактивном редакторе.
```bash
# Создать коммит, помеченный как исправление для старого коммита
git commit --fixup <хэш_коммита_для_исправления>

# Запустить rebase, который автоматически применит fixup-коммиты куда нужно
git rebase -i --autosquash <целевая_база>
```

#### 2. Перенос стека веток (`--update-refs`)
В Git 2.38+ позволяет автоматически обновлять указатели всех промежуточных веток при перебазировании стека.
```bash
# Находясь на вершине стека (v3)
git rebase main --update-refs
```

#### 3. Хирургический перенос (`--onto`)
Позволяет перенести ветку, созданную от другой фича-ветки, на `main`.
```bash
git rebase --onto main feature-A feature-B
# → Перенесет коммиты feature-B (от feature-A до конца) поверх main
```

#### 4. НОВОЕ в Git 2.56+: Удаление коммита из истории (`git history drop`)
Экспериментальная команда для удаления коммита с переигрыванием потомков на родитель.
```bash
git history drop <commit-hash>
# Удаляет коммит, реплеит его детей на родителя
# Обновляет индекс и working tree если HEAD сдвинулся
# Не работает с merge-коммитами и root-коммитами
```

### Сравнение веток

```bash
# Показать коммиты, которые есть в feature, но отсутствуют в main
git log main..feature

# Показать список коммитов с сообщениями, которых нет в целевой ветке
git cherry -v main

# Показать различия в коде между концами двух веток
git diff main..feature

# Показать статистику изменений (файлы, строки)
git diff --stat main..feature

# Показать только имена измененных файлов
git diff --name-only main..feature
```

### Поиск проблемных коммитов (Git Bisect)

`git bisect` использует бинарный поиск по истории коммитов для нахождения конкретного изменения, внесшего регрессию или ошибку. Это значительно быстрее ручного перебора.

**Основной workflow:**

```bash
# Запуск bisect с указанием "плохого" и "хорошего" коммитов
git bisect start
git bisect bad                  # Текущий коммит сломан
git bisect good v1.0            # Коммит v1.0 был рабочим

# Git автоматически переключается на промежуточный коммит
# Проверьте код и выполните тесты, затем укажите результат:
git bisect good                # Если коммит рабочий
# или
git bisect bad                 # Если коммит сломан

# Продолжайте, пока Git не найдет проблемный коммит
# После завершения:
git bisect reset               # Вернуться на исходную ветку
```

**Автоматизация bisect (для CI/CD):**

```bash
# Запуск bisect с автоматическим тестированием
git bisect start HEAD v1.0
git bisect run ./test_script.sh  # Скрипт должен вернуть 0 (good) или 1-124 (bad)
# 125 = skip (невозможно протестировать), 127 = ошибка запуска скрипта
```

**НОВОЕ в Git 2.56+: Автоматический возврат после поиска**
```bash
# Вернуться на исходную ветку автоматически после нахождения (по умолчанию)
git bisect run --reset-when-found=original ./test_script.sh

# Остаться на найденном "плохом" коммите
git bisect run --reset-when-found=found ./test_script.sh
```

**Примечание:** Подробное описание `git bisect` и других инструментов отладки см. в **[Устранение неполадок Git](./git_troubleshooting.md)**.

### Паттерны веток (Branch Patterns)

Git поддерживает использование шаблонов (паттернов) для фильтрации веток в различных командах. Это позволяет работать с группами веток одновременно.

**Символы подстановки:**

| Символ | Описание | Пример |
|--------|----------|--------|
| `*` | Заменяет любое количество любых символов (кроме `/`) | `feature/*` → `feature/auth`, `feature/pay` |
| `**` | Рекурсивное замещение (включая `/`) | `feature/**` → `feature/auth/oauth2` |
| `?` | Заменяет ровно один символ | `fix-?` → `fix-1`, `fix-a` |
| `[abc]` | Заменяет один из указанных символов | `feature-[abc]` → `feature-a`, `feature-b` |
| `[a-z]` | Заменяет один из символов в диапазоне | `release-[0-9]` → `release-1`, `release-5` |

**Примеры использования:**

```bash
# Удалить все feature-ветки
git branch | grep 'feature/' | xargs git branch -D

# Показать коммиты во всех feature-ветках
git log --oneline feature/*

# Показать различия между main и всеми feature-ветками
git diff main..feature/*

# Использование паттернов в конфигурации CI/CD (GitHub Actions)
# on:
#   push:
#     branches: [ 'feature/**', 'bugfix/**' ]

# Использование паттернов в gitignore
# *.feature-*
```

**Примечание:** Паттерны веток используются в командах `git branch`, `git log`, `git diff`, а также в конфигурации CI/CD и hook'ов.

---

## DevOps / SRE контекст

### Branch Protection (Защита веток)
Для production-веток (`main`, `production`, `release/*`) обязательна настройка защиты на стороне Git-хостинга (GitHub, GitLab, Gitea, Gogs):

* **Required reviews:** Минимум 1-2 approve от code owners.
* **Status checks:** CI pipeline должен быть зелёным (tests, lint, security scan).
* **Require linear history:** Запрет merge commits (только squash/rebase).
* **No force push:** Блокировка `git push --force` (разрешить только `--force-with-lease` для админов).
* **Signed commits:** Требование GPG/SSH подписи.
* **Dismiss stale reviews:** При новых коммитах старые approve сбрасываются.

**GitHub CLI пример:**
```bash
gh api -X PUT repos/OWNER/REPO/branches/main/protection \
  -f required_status_checks='{"strict":true,"contexts":["ci/tests","ci/lint"]}' \
  -f enforce_admins=true \
  -f required_pull_request_reviews='{"required_approving_review_count":1,"dismiss_stale_reviews":true}' \
  -f restrictions='{}'
```

**GitLab:** Settings → Repository → Protected branches (разрешить merge только для Maintainers, push — "No one"). Через CLI: `glab api -X PUT ...` или конфигурация в `.gitlab-ci.yml` / push rules.

### Стратегии для CI/CD

| Сценарий | Рекомендуемая стратегия | Настройка merge |
|----------|------------------------|-----------------|
| **Trunk-based (DevOps)** | Короткие feature-ветки (<1 дня), rebase на main | Squash merge, linear history |
| **GitHub Flow** | Feature → PR → main | Squash merge |
| **GitLab Flow** | Feature → main → pre-prod → production | Merge commit (--no-ff) для среды |
| **Git Flow** | feature → develop, release → main, hotfix → main+release | Merge commit (--no-ff) везде |
| **Release branching** | `release/v1.2` → cherry-pick hotfixes → main + release | Merge commit для traceability |

### Автоматизация очистки (Housekeeping)

```bash
# Ежедневная/еженедельная задача (cron, CI job, git maintenance)
# 1. Удаление локальных слитых веток (Git 2.56+)
git branch --delete-merged 'origin/*'

# 2. Очистка remote-tracking ссылок
git fetch --prune

# 3. Удаление worktree'ов
git worktree prune

# 4. Сборка мусора (осторожно на продакшн-репо)
git maintenance run  # или git gc --auto

# 5. НОВОЕ в Git 2.56+: Очистка больших promisor-блобов в partial clone
git repack -a --filter=blob:limit=1m --drop-filtered --dry-run
git repack -a --filter=blob:limit=1m --drop-filtered
```

### Работа с форками (Forking workflow)

```bash
# 1. Добавить upstream
git remote add upstream https://github.com/ORIGINAL/REPO.git

# 2. Синхронизировать main с upstream
git fetch upstream
git switch main
git merge upstream/main  # или rebase для линейности
git push origin main

# 3. Создать feature от актуального main
git switch -c feature/my-change

# 4. Отправить в свой форк
git push -u origin feature/my-change

# 5. Создать PR через UI или CLI
gh pr create --base main --head feature/my-change --repo ORIGINAL/REPO
```

### Hotfix / Backport процесс (SRE)

```bash
# 1. Создать hotfix от production тега/ветки
git switch -c hotfix/critical-fix v1.2.3  # или release/v1.2

# 2. Исправить, закоммитить, протестировать
# ...

# 3. Влить в production ветку
git switch release/v1.2
git merge --no-ff hotfix/critical-fix
git tag v1.2.4
git push origin release/v1.2 v1.2.4

# 4. Backport в main (через cherry-pick для сохранения истории)
git switch main
git cherry-pick <hotfix-commit-hash>
# Или merge, если стратегия позволяет
git merge --no-ff release/v1.2

# 5. Удалить hotfix ветку
git branch -d hotfix/critical-fix
git push origin --delete hotfix/critical-fix
```

---

## Устранение неполадок

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `error: cannot delete branch 'xyz' checked out at '/path'` | Попытка удалить ветку, на которой вы находитесь | Переключитесь на другую ветку (`git switch main`) и повторите удаление |
| `error: The branch 'xyz' is not fully merged` | Попытка удалить ветку с помощью `-d`, но она не слита в текущую | Используйте `-D` для принудительного удаления (если уверены) или слейте ветку |
| `fatal: 'xyz' is not a branch (or symlink to a branch)` | Неверное имя ветки | Проверьте имя с помощью `git branch` |
| `error: pathspec 'xyz' did not match any branch(s) known to repository` | Попытка переключиться на несуществующую ветку | Создайте ветку (`git switch -c xyz`) или проверьте имя |
| `fatal: refusing to merge unrelated histories` | Слияние репозиториев с независимыми историями | Используйте `git merge --allow-unrelated-histories` (осторожно) |
| `error: src refspec xyz does not match any` | Попытка отправить несуществующую ветку | Проверьте имя ветки с помощью `git branch -a` |
| `fatal: impossible to fast-forward, will need to use --force` при `git push` | Локальная и удалённая ветки расходятся (diverged) | `git pull --rebase origin <branch>` (или `git pull --ff-only`, если локально чисто), затем `git push` |
| `fatal: '<branch>' is already checked out at '<path>'` | Попытка открыть ветку в worktree, где она уже занята | Переключитесь с неё в том дереве, либо используйте `--detach`, либо создайте новую ветку через `-b` |
| `error: cannot lock ref 'refs/heads/xyz'` | Конкуренция или сбой lock-файла | `rm -f .git/refs/heads/xyz.lock` и повторите; если не помогло — `git gc` |
| `fatal: bad object <hash>` при checkout/merge | Повреждён объект или отсутствует (partial clone) | `git fetch --all` или `git fsck --full` для диагностики |

### Ограничения и особенности

* **Восстановление удаленной ветки:** Если ветка была удалена случайно, ее указатель можно восстановить с помощью `git reflog`, найдя хэш последнего коммита ветки и создав ее заново: `git branch <имя> <хэш>`.
* **Git Worktree:** Нельзя одновременно открыть (checkout/switch) одну и ту же ветку в разных рабочих директориях. Git заблокирует попытку создания второго worktree с той же веткой. Подробнее см. **[Git Worktree — параллельные рабочие директории](./git_worktree.md)**.
* **Автоматизация через `rerere`:** Если включен (`git config --global rerere.enabled true`), Git запоминает ваши решения конфликтов и применяет их автоматически при повторном возникновении. Это особенно полезно при долговременных rebase, чтобы не решать одни и те же конфликты многократно.
* **Partial Clone:** В partial clone (`git clone --filter=blob:none`) отсутствующие блобы загружаются по требованию. Git 2.56+ позволяет очистить кэш: `git repack -a --filter=blob:limit=1m --drop-filtered`.
* **Shallow Clone:** `git clone --depth=1` не имеет полной истории. Для работы с ветками нужно `git fetch --unshallow` или полная реклонация.
* **Case Sensitivity:** На case-insensitive ФС (macOS, Windows) `git branch Feature` и `git branch feature` — одна ветка. На Linux — разные. Избегайте веток, отличающихся только регистром.

---

## Лучшие практики

* **Короткоживущие ветки:** Чем дольше живёт ветка, тем выше риск конфликтов. Сливайте как можно быстрее (ideal: < 1 день для trunk-based).
* **Описательные имена:** Используйте префиксы `feature/`, `fix/`, `hotfix/`, `release/`, `chore/`, `experiment/` для читаемости и автоматизации CI/CD.
* **Защищайте `main`/`production`** через Branch Protection (обязательные ревью, статус-чеки, запрет force-push). Настройка см. в **[Рабочие процессы Git](./git_workflows.md#защита-веток-branch-protection)**.
* **Осознанный выбор стратегии слияния:** squash для чистой `main`, rebase для линейности, `--no-ff` для Git Flow и release branches.
* **Никогда не force-push в общие ветки** (`main`, `develop`, `release/*`); для своих feature-веток — только `--force-with-lease`.
* **Удаляйте слитые ветки**, чтобы не плодить «мертвые» ссылки:
  ```bash
  # Удалить локально слитые в main ветки (кроме main)
  git branch --merged main | grep -v '^main$' | xargs git branch -d

  # Очистить remote-tracking ссылки на удалённые ветки
  git fetch --prune

  # Для Git 2.56+ — встроенная безопасная альтернатива:
  git branch --delete-merged 'origin/*'
  ```
* **Используйте Conventional Commits:** `feat:`, `fix:`, `chore:`, `docs:` — основа чистой истории и автогенерации changelog.
* **Для временного хранения изменений** используйте `git stash` (подробнее в **[Git Stash](./git_stash.md)**).
* **Для параллельной работы с несколькими ветками** используйте `git worktree` (подробнее в **[Git Worktree](./git_worktree.md)**).
* **Настройте upstream** для всех рабочих веток: `git push -u origin <branch>` — упрощает pull/push/status.
* **Включите rerere** глобально: `git config --global rerere.enabled true` — экономит время при повторных конфликтах.
* **Используйте `--force-with-lease` вместо `--force`:** Защищает от случайной перезаписи чужой работы.
* **Подписывайте коммиты** (GPG/SSH): `git config --global commit.gpgsign true` — критично для безопасности供应链.
* **Автоматизируйте housekeeping:** Добавьте `git maintenance start` или cron с `git fetch --prune` и `git branch --delete-merged`.

---

## Дополнительная информация

### Официальные ресурсы
* **[Документация Git по ветвлению](https://git-scm.com/book/ru/v2/Основы-Git-Ветвление):** Фундаментальное описание.
* **[Learn Git Branching](https://learngitbranching.js.org/?locale=ru_RU):** Интерактивный визуальный тренажер.

### Связанные темы
* [Git Merge — стратегии слияния](./git_merge_strategies.md) — ort, recursive, ours, theirs, patience, octopus и их применение.
* [Разрешение конфликтов](./git_conflict_resolution.md) — паттерны, инструменты, rerere при слиянии веток.
* [Манипуляции с историей (Reset, Revert, Cherry-pick)](./git_history_manipulation.md) — откат изменений и перенос коммитов.
* [Git Reflog](./git_reflog.md) — журнал ссылок для восстановления удалённых веток.
* [Внутреннее устройство Git](./git_internals.md) — как Git хранит ветки (refs, HEAD, objects).
* [Рабочие процессы (Git Flow, GitHub Flow)](./git_workflows.md) — стратегии ветвления для команд.
* [Синхронизация с удаленным репозиторием](./git_synchronization.md) — push/pull веток.
* [Git Worktree — параллельные директории](./git_worktree.md) — работа с несколькими ветками одновременно.
* [Устранение неполадок Git](./git_troubleshooting.md) — диагностика проблем с ветками.
* [Git Stash — временное хранение изменений](./git_stash.md) — альтернатива для кратковременного припрятывания кода.
* [Git Tags](./git_tags.md) — разметка версий для релизных веток, SemVer, интеграция с CI/CD.