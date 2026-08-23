# Синхронизация репозиториев — git fetch, pull, push

## Определения

*   **Удаленный репозиторий (Remote):** Версия проекта, размещенная на внешнем сервере (GitHub, GitLab, локальный сервер). Служит центральным узлом для обмена данными.
*   **Синхронизация:** Процесс согласования состояний локальной и удаленной копий репозитория через передачу объектов (коммитов, деревьев) и обновление указателей веток.
*   **Удаленная ветка отслеживания (Remote-tracking branch):** Локальная ссылка-закладка на состояние ветки в удаленном репозитории (например, `refs/remotes/origin/main`). Обновляется только при выполнении сетевых операций.
*   **Вверх по течению (Upstream):**
    1.  Оригинальный репозиторий, от которого был сделан форк.
    2.  Удаленная ветка, связанная с текущей локальной веткой (upstream branch).
*   **Fast-forward:** Тип слияния, при котором указатель ветки просто перемещается вперед по истории, так как в целевой ветке нет новых коммитов, отсутствующих в источнике.
*   **`git fetch`:** Загрузка новых объектов и ссылок из удаленного репозитория. Самая безопасная операция, так как она не изменяет локальное рабочее дерево.
*   **`git pull`:** Высокоуровневая команда, объединяющая `fetch` и последующую интеграцию изменений (`merge` или `rebase`) в текущую ветку.
*   **`git push`:** Передача локальных коммитов в удаленный репозиторий и попытка обновить указатель ветки на сервере.
*   **Refspec:** Спецификация отображения ссылок между локальным и удаленным репозиторием в формате `<src>:<dst>`. Определяет, какие refs загружать/отправлять и как их переименовывать. Пример: `refs/heads/main:refs/heads/main`.
*   **`origin`:** Стандартное имя для основного удаленного репозитория, добавляемого автоматически при `git clone`. Может быть изменено или добавлены дополнительные remotes.
*   **`push.default`:** Конфигурационный параметр, определяющий поведение `git push` при отсутствии явного указания ветки. Значения: `simple` (современный стандарт), `current`, `upstream`, `matching` (устарел).
*   **Трехстороннее слияние (3-way merge):** Алгоритм, используемый Git для автоматического объединения изменений из двух веток на основе общего предка (base). При невозможности автоматического слияния возникает конфликт.

---

## Базовые концепции

### Архитектура удаленных репозиториев

Git работает по модели **peer-to-peer**: каждый клон является полным репозиторием с собственной историей. Удаленный репозиторий (`origin`) — это просто еще одна копия, с которой синхронизируются локальные изменения. Это означает:

*   **Нет центрального авторитета:** Любой клон может получать и отправлять данные в любой другой клон (при наличии доступа).
*   **Локальная автономность:** Все команды чтения истории (`log`, `diff`, `blame`) работают без сетевого подключения.
*   **Сетевая операция — только exchange:** `fetch`, `push`, `pull` — единственные команды, взаимодействующие с удаленным сервером.

**Remote-tracking ветки** (`refs/remotes/<name>/<branch>`) — это локальные, неизменяемые указатели. Они обновляются только при `fetch`/`pull` и никогда не перемещаются автоматически при локальных коммитах. Это обеспечивает безопасную «точку отсчета» для сравнения локальных изменений с удаленными.

### Механизм работы `git fetch`

`fetch` выполняет два действия:

1.  **Загрузка объектов:** Git запрашивает у сервера все коммиты, деревья и blobs, которых нет в локальном репозитории. Это инкрементальный процесс: передаются только недостающие объекты (pack-file протокол).
2.  **Обновление refs:** Git обновляет remote-tracking ветки (`origin/main`, `origin/feature/x`) в соответствии с полученными объектами.

**Важно:** `fetch` **не** меняет локальные ветки и не трогает рабочее дерево. Локальная `main` остается на старом коммите, пока вы явно не выполните `merge` или `rebase` с `origin/main`.

**Refspec по умолчанию:**
При `git fetch origin` Git использует refspec из конфигурации remote:
```
[remote "origin"]
    url = https://github.com/user/repo.git
    fetch = +refs/heads/*:refs/remotes/origin/*
```
Зеркальная звездочка (`*`) означает: взять все ветки с удаленного `refs/heads/` и создать соответствующие remote-tracking ветки в `refs/remotes/origin/`. Знак `+` принудительно обновляет remote-tracking ветки даже если это non-fast-forward (что безопасно, так как это только локальные ссылки).

**`--all` и `--prune`:**
*   `--all`: запрашивает все настроенные remotes (`origin`, `upstream`, `fork`).
*   `--prune`: удаляет remote-tracking ветки, которые исчезли на сервере (например, `origin/old-feature` после удаления ветки на GitHub).

### Механизм работы `git pull`

`git pull` — это `git fetch` + `git merge FETCH_HEAD` (по умолчанию) или `git rebase` (при `pull.rebase=true`).

**Merge-режим (по умолчанию):**
Git создает merge-коммит, объединяющий локальную ветку и удаленную. Это сохраняет полную историю обеих линий, но добавляет «шумные» merge-коммиты при частых пуллах.

**Rebase-режим (`git pull --rebase`):**
Git временно откладывает локальные коммиты, обновляет ветку до состояния удаленной, а затем применяет локальные коммиты поверх. Это дает линейную историю, но переписывает хэши локальных коммитов.

**Выбор стратегии:**
*   **Линейная история (Trunk-Based, GitHub Flow):** `pull.rebase=true` — минимизирует merge-коммиты.
*   **Полная история (Git Flow, сложные feature-ветки):** `pull.rebase=false` — merge-коммит сохраняет контекст интеграции.
*   **Сложные ветки с вложенными merges:** `pull.rebase=merges` — rebase с сохранением merge-коммитов (Git 2.18+).

### Механизм работы `git push`

`push` отправляет локальные объекты на сервер и пытается обновить указатель ветки.

**Fast-forward vs Non-fast-forward:**
*   **Fast-forward:** Удаленная ветка является прямым предком локальной. Git просто перемещает указатель. Это безопасно и выполняется без флагов.
*   **Non-fast-forward:** Удаленная ветка содержит коммиты, отсутствующие локально. Git отклоняет push по умолчанию, чтобы предотвратить случайную потерю чужих изменений.

**Refspec для push:**
По умолчанию push использует `refs/heads/<branch>:refs/heads/<branch>` (текущая локальная ветка в одноименную удаленную). При `push.default=simple` Git дополнительно проверяет, совпадает ли имя локальной ветки с удаленной.

### Взаимодействие с хуками

```
git push
  ├── pre-push           ← может проверить тесты, секреты, форматирование
  └── серверные хуки     ← CI, branch protection, commit verification
```

`git pull` не вызывает client-side хуки напрямую, но может активировать `post-merge` (после успешного merge) и `post-checkout` (при переключении веток).

### Стратегии отправки изменений (`push`)

*   **Standard Push:** Работает только в режиме fast-forward. Если удаленная ветка ушла вперед, Git отклонит push.
*   **Safe Force Push (`--force-with-lease`):** Проверяет, совпадает ли состояние удаленной ветки с вашим последним `fetch`. Это предотвращает случайную перезапись коммитов, которые запушили коллеги, пока вы работали.
*   **Safety Lock (`--force-if-includes`):** (Git 2.30+) Дополнительная проверка, гарантирующая, что удаленные коммиты, о которых знает ваш локальный репозиторий, действительно интегрированы в вашу ветку перед принудительной отправкой.

### Очистка и обслуживание (`prune`)

Когда ветка удаляется на сервере, локальная ссылка на нее (`origin/branch-name`) остается. Флаг `--prune` (или `-p`) при выполнении `fetch` или `pull` автоматически удаляет эти «мертвые» ссылки, поддерживая чистоту списка веток.

---

## Практические сценарии

### Сценарий 1: Исследование перед интеграцией

Позволяет оценить объем изменений и потенциальные конфликты.

```bash
# 1. Загрузить данные со всех удаленных репозиториев
git fetch --all --prune

# 2. Посмотреть список новых коммитов в удаленном main
git log main..origin/main --oneline
# → a1b2c3d (origin/main) fix: API endpoint timeout
# → e4f5g6h feat: add auth validation tests

# 3. Сравнить код визуально
git diff main origin/main

# 4. Интегрировать изменения, если все в порядке
git merge origin/main
```

**Валидация:**
```bash
# Проверить, что локальная ветка обновилась
git log --oneline -3
# → должен появиться коммит из origin/main

# Проверить статус синхронизации
git status
# → Your branch is ahead of 'origin/main' by N commits (если локально впереди)
```

### Сценарий 2: Синхронизация форка с оригиналом (upstream)

Классический рабочий процесс в Open Source проектах. Подробное описание контекста и правил доступно в файле **[Рабочие процессы в Git](./git_workflows.md#5-forking-workflow-открытое-по)**.

```bash
# 1. Добавить ссылку на оригинал (делается один раз)
git remote add upstream https://github.com/original-owner/project.git

# 2. Получить свежие данные из оригинала
git fetch upstream

# 3. Перебазировать свою работу на актуальный main из оригинала
git checkout main
git rebase upstream/main

# 4. Обновить свой публичный форк
git push origin main
```

**Валидация:**
```bash
# Проверить, что upstream/main действительно обновился
git log --oneline -3 upstream/main

# Проверить divergence
git rev-list --left-right --count main...upstream/main
# → 0 3 (локальных коммитов нет, upstream впереди на 3)
```

### Сценарий 3: Установка и изменение upstream-ветки

Связывает локальную ветку с удаленной для упрощения `pull`/`push` без указания remote и ветки.

```bash
# Установить upstream для текущей ветки при первой отправке
git push -u origin feature/auth

# Проверить текущий upstream
git rev-parse --abbrev-ref --symbolic-full-name @{u}
# → origin/main

# Изменить upstream на другую ветку
git branch --set-upstream-to=origin/develop main

# Отключить upstream (переключиться в独立 режим)
git branch --unset-upstream
```

**Валидация:**
```bash
# Показать связи веток с upstream
git branch -vv
# → * main  abc1234 [origin/main] Commit message
# →   feature/auth  def5678 [origin/feature/auth] Commit message
```

### Сценарий 4: Чистая синхронизация с авто-сохранением (Autostash)

Позволяет выполнить `pull --rebase`, даже если у вас есть незакоммиченные изменения.

```bash
# Стянуть изменения, временно спрятать локальные правки и накатить их поверх свежего rebase
git pull --rebase --autostash origin main

# Если возникли конфликты:
# 1. Исправить файлы
# 2. git add <file>
# 3. git rebase --continue
```

**Валидация:**
```bash
# Проверить, что stash был применен
git stash list
# → (должен быть пустым после успешного autostash)

# Проверить, что локальные изменения на месте
git status
# → working tree clean (или только planned изменения)
```

### Сценарий 5: Обновление веток без переключения (Background Update)

Позволяет обновить локальный `main`, пока вы работаете в `feature`-ветке.

```bash
# Синхронизировать локальный main с удаленным напрямую
git fetch origin main:main
# → 123abcd..456efgh  main       -> main
```

**Валидация:**
```bash
# Проверить, что main обновился, не переключаясь
git log main --oneline -3
# → 456efgh (HEAD -> main) Latest upstream commit
```

### Сценарий 6: Безопасное обновление истории на сервере

Используется после `commit --amend` или `rebase` в фича-ветке. Подробнее о переписывании истории: **[Манипуляции с историей](./git_history_manipulation.md)**.

```bash
# Принудительная отправка с максимальной защитой
git push origin feature/auth --force-with-lease --force-if-includes
```

**Валидация:**
```bash
# Проверить, что push прошел
git log origin/feature/auth --oneline -3
# → должен совпадать с локальной историей
```

### Сценарий 7: Изменение URL удаленного репозитория

Переезд на новый сервер или смена протокола (HTTPS → SSH).

```bash
# Изменить URL существующего remote
git remote set-url origin git@github.com:user/repo.git

# Или удалить и добавить заново
git remote remove origin
git remote add origin git@github.com:user/repo.git

# Проверить новое значение
git remote -v
# → origin  git@github.com:user/repo.git (fetch)
# → origin  git@github.com:user/repo.git (push)
```

**Валидация:**
```bash
# Проверить доступ к новому URL
git ls-remote origin
# → Вывод списка refs с нового сервера
```

### Сценарий 8: Удаление неиспользуемого remote

Очистка списка серверов после завершения проекта или ухода из организации.

```bash
# Удалить remote (не удаляет локальные ветки)
git remote remove upstream

# Удалить remote и все связанные remote-tracking refs
git remote remove upstream
git fetch --prune
```

**Валидация:**
```bash
# Проверить список оставшихся remotes
git remote -v
# → должен отображаться только origin
```

### Сценарий 9: Синхронизация тегов

По умолчанию `git push` не отправляет теги.

```bash
# Отправить конкретный тег
git push origin v1.0.0

# Отправить все локальные теги
git push origin --tags

# Рекомендуемый способ: отправлять теги вместе с коммитами, которые к ним привели
git push origin --follow-tags
```

**Валидация:**
```bash
# Проверить теги на сервере
git ls-remote --tags origin
# → Вывод всех тегов с хэшами
```

### Сценарий 10: Разрешение конфликтов при `pull`

Стратегия зависит от выбранного режима (`merge` или `rebase`).

**Merge-режим (по умолчанию):**
```bash
# 1. Получить и попытаться слить
git pull origin main
# → CONFLICT (content): Merge conflict in src/app.js

# 2. Открыть конфликтные файлы, найти маркеры <<<<<<<, =======, >>>>>>> и исправить

# 3. Проиндексировать решения
git add src/app.js

# 4. Завершить merge-коммит
git commit
# → Merge branch 'main' of origin into feature/auth
```

**Rebase-режим (`pull --rebase`):**
```bash
# 1. Получить и перебазировать
git pull --rebase origin main
# → CONFLICT (content): Merge conflict in src/app.js

# 2. Исправить конфликтные файлы

# 3. Проиндексировать
git add src/app.js

# 4. Продолжить rebase
git rebase --continue

# При ошибках: отменить rebase
git rebase --abort
```

**Принудительная стратегия слияния (редко используется):**
```bash
# Отдать приоритет локальным изменениям (ours)
git merge -X ours origin/main

# Отдать приоритет удаленным изменениям (theirs)
git merge -X theirs origin/main
```

**Валидация:**
```bash
# Проверить, что конфликты разрешены
git status
# → All conflicts fixed but you are still merging/re basing

# Проверить итоговый diff
git diff HEAD
# → Должен показывать только planned изменения без маркеров конфликтов
```

### Сценарий 11: Dry-run перед push

Проверка, что push будет успешным, без фактической отправки данных.

```bash
# Проверить, что push пройдет (dry-run)
git push --dry-run origin feature/auth
# → To https://github.com/user/repo.git
# →  * [new branch]      feature/auth -> feature/auth
# → (или отклонение, если есть проблемы)

# Проверить, какие теги будут отправлены
git push --dry-run --tags origin
```

**Валидация:**
```bash
# Dry-run не изменяет состояние remote, но показывает planned действия
git log origin/feature/auth --oneline -1
# → (не изменилось, если dry-run был отклонен)
```

### Сценарий 12: Синхронизация с несколькими remotes

Работа с `origin` (основной форк) и `upstream` (оригинал) одновременно.

```bash
# 1. Загрузить изменения из обоих remotes
git fetch origin upstream --prune

# 2. Сравнить состояние origin и upstream
git log origin/main..upstream/main --oneline
# → a1b2c3d (upstream/main) feat: new upstream feature

# 3. Обновить локальный main из upstream
git checkout main
git merge upstream/main

# 4. Отправить обновленный main в origin
git push origin main
```

**Валидация:**
```bash
# Проверить remote-tracking ветки
git branch -r
# → origin/main
# → origin/feature/auth
# → upstream/main
```

---

## Дополнительная информация

### Рекомендуемая конфигурация

Для предсказуемого и безопасного поведения команд синхронизации рекомендуется настроить следующие параметры. Полный список настроек доступен в **[Конфигурация Git](./git_configuration.md)**.

```bash
# Всегда использовать rebase при pull
git config --global pull.rebase true

# Автоматически чистить удаленные ссылки при fetch
git config --global fetch.prune true

# Создать безопасный алиас для force push
git config --global alias.pushf "push --force-with-lease --force-if-includes"

# Автоматически сохранять/восстанавливать stash при rebase
git config --global rebase.autostash true

# Современная стратегия push (только текущая ветка в одноименную)
git config --global push.default simple
```

### Оптимизация для больших репозиториев

*   **Бэкенд `reftable`:** (Git 3.0+) Значительно ускоряет чтение и запись ссылок при тысячах веток.
*   **Параллельный fetch:** `git config --global fetch.parallel 8` — ускоряет загрузку объектов в многопоточном режиме.
*   **Shallow Fetch:** `git fetch --depth 1` — загружает только последний коммит, экономя трафик и время (полезно в CI).
*   **Commit-Graph:** `git config --global fetch.writeCommitGraph true` — ускоряет обход истории при `git log`, `merge`, `rebase` на десятки процентов в репозиториях с >100k коммитов.

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `error: failed to push some refs` | Удаленная ветка ушла вперед | `git pull --rebase origin <branch>`, затем `git push` |
| `fatal: refusing to merge unrelated histories` | Независимые истории репозиториев | `git pull --allow-unrelated-histories` (осторожно) |
| `fatal: unable to access '...'` | Сетевая ошибка (DNS, SSL, прокси) | Проверить `GIT_CURL_VERBOSE=1 git ls-remote ...`, настроить `http.proxy` |
| `remote: Permission denied (publickey)` | SSH-ключ не добавлен в агент или не настроен | `ssh-add ~/.ssh/id_ed25519`, проверить `ssh -T git@github.com` |
| `error: RPC failed; HTTP 413 curl 22` | Файл превышает лимит GitHub (100 MB) | Использовать Git LFS или уменьшить файл |
| `hint: Updates were rejected because the tip of your current branch is behind` | Non-fast-forward | `git pull --rebase` или `git pull --ff-only`, затем `git push` |
| `fatal: 'origin' does not appear to be a git repository` | Remote не настроен или URL неверный | `git remote -v`, добавить/исправить remote через `git remote add` или `set-url` |

### Ограничения и особенности

*   **Пропуск шаблона:** Команда `git commit -m "..."` полностью игнорирует `commit.template`. Для принудительного соблюдения правил используйте хук `commit-msg`.
*   **Глобальный шаблон:** При установке `commit.template` на глобальном уровне (`--global`) шаблон применяется ко всем репозиториям пользователя. Для проектно-специфичных шаблонов используйте `--local`.
*   **IDE:** JetBrains (IntelliJ, WebStorm) и VS Code имеют встроенную поддержку `commit.template`, но могут требовать включения в настройках ("Use commit template").
*   **Revert:** При использовании `git revert` Git автоматически создает сообщение `revert: <original subject>`. Не рекомендуется менять этот формат вручную, так как он используется инструментами анализа истории.
*   **Squash и merge:** При squash-слиянии Git создает автоматическое сообщение с перечислением коммитов. Шаблон не применяется, но `commit-msg` хук может его изменить.
*   **Rebase и amend:** `git commit --amend` открывает редактор с предыдущим сообщением, к которому применяется шаблон как основа. После сохранения старые строки комментариев из шаблона не дублируются.
*   **Защищенные ветки:** На GitHub/GitLab/Bitbucket ветки `main`, `master`, `develop` могут иметь защиту (Branch Protection), блокирующую обычный `git push` и `git push --force`. Force-push доступен только при явном отключении защиты или использовании админ-панели.
*   **LFS объекты:** При `git push` с файлами Git LFS происходит двухэтапная отправка: сначала обычные объекты Git, затем LFS-объекты через отдельный протокол. При обрыве соединения повторный push может потребовать `git lfs push --all`.

### Лучшие практики

1.  **Всегда делайте `fetch` перед `push`:** Проверяйте состояние удаленной ветки через `git fetch` перед отправкой, чтобы избежать не-fast-forward отклонений.
2.  **Используйте `--force-with-lease`, а не `--force`:** Защищает от перезаписи чужих коммитов. Никогда не делайте force-push в общие ветки (`main`, `develop`).
3.  **Настройте `pull.rebase=true` глобально:** Для линейной истории в проектах с Trunk-Based Development или GitHub Flow. Для Git Flow оставьте `false`.
4.  **Включите `fetch.prune=true`:** Предотвращает накопление мертвых remote-tracking веток.
5.  **Используйте `--autostash` при rebase:** Позволяет пуллить изменения даже с незакомиченными правками.
6.  **Не храните большие файлы в Git напрямую:** Используйте Git LFS для бинарных артефактов. Превышение лимитов серверов (100 MB на GitHub) приведет к отклонению push.
7.  **Синхронизируйте форки регулярно:** Частые `git fetch upstream && git rebase upstream/main` минимизируют divergence и упрощают поддержание PR актуальными.
8.  **Используйте SSH вместо HTTPS для автоматизации:** SSH-ключи не требуют ввода пароля при каждом push/pull, что критично для CI/CD.
9.  **Проверяйте upstream перед пуллом:** `git remote -v` и `git branch -vv` помогают убедиться, что вы синхронизируетесь с правильным сервером и веткой.
10. **Документируйте корпоративные remotes:** В `README.md` или `CONTRIBUTING.md` укажите canonical URLs для `origin` и `upstream`, чтобы новые участники не ошиблись с форком.

### Устранение неполадок: распространенные сценарии

**Сеть и доступ:**
```bash
# Диагностика SSH-подключения
ssh -T git@github.com
# → Hi <user>! You've successfully authenticated, but GitHub does not provide shell access.

# Диагностика HTTPS-подключения
GIT_CURL_VERBOSE=1 git ls-remote https://github.com/user/repo.git
# → Показывает детали TLS-рукопожатия и возможные проблемы с прокси

# Проверка настроек прокси
git config --global --get http.proxy
# → http://proxy.company.com:8080
```

**Конфликты:**
```bash
# Отменить текущий merge/rebase
git merge --abort
git rebase --abort

# Использовать rerere для автоматического применения запомненных решений
git config --global rerere.enabled true
```

**Размер и производительность:**
```bash
# Проверить размер пакетов перед push
git count-objects -vH
# → count: 0, size: 0 bytes, in-pack: 1500, packs: 1, size-pack: 12.34 MiB

# Уменьшить размер перед push
git repack -a -d --depth=250 --window=250
```

### См. также

*   [Конфигурация Git (`git config`)](./git_configuration.md) — настройка remote, autostash, pull.rebase и других параметров синхронизации.
*   [Ветвление в Git (`git branching`)](./git_branching.md) — механизмы работы с ветками и их переключение.
*   [Манипуляции с историей (`git history manipulation`)](./git_history_manipulation.md) — подробнее о Rebase и Force Push.
*   [Внутреннее устройство Git](./git_internals.md) — как Git хранит ссылки (refs) и удалённые ветки.
*   [Производительность Git](./git_performance.md) — оптимизация fetch/pull для больших репозиториев.
*   [Устранение неполадок](./git_troubleshooting.md) — детальный разбор конфликтов и сетевых ошибок.
