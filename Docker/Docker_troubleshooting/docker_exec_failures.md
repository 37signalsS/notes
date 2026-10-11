# Ошибки docker exec (Exec Failures)

**Актуально для:** Docker Engine 20.10+ / 28.x–29.x; `docker debug` — Docker Desktop 4.33+

## Определения

**`docker exec`** — команда запуска процесса внутри **работающего** контейнера (документация CLI: «Execute a command in a running container»). Процесс создаётся в namespaces контейнера, но **не является PID 1** — сигналы от `docker stop` доставляются PID 1, а не exec-процессу. Exec-процесс живёт, пока жив PID 1, и **не перезапускается** при перезапуске контейнера.

**Exec failure** — класс ошибок, когда команда не запускается: контейнер не в состоянии `running`, в образе нет нужного исполняемого файла, нет прав, нет TTY. Каждая причина имеет свой текст ошибки, свой код завершения и своё решение.

## Основные концепции

### Почему exec требует running-контейнер

`docker exec` создаёт процесс через OCI runtime в namespaces существующего контейнера. Если контейнер остановлен или приостановлен — namespaces недоступны, запускать нечего. Демон проверяет состояние **до** создания процесса и отвечает отказом:

| Состояние контейнера (`docker ps`) | `docker exec` | Текст ошибки |
| :--- | :--- | :--- |
| `running` | работает | — |
| `paused` | отказ (exit 1) | `Container <id> is paused, unpause the container before exec` |
| `restarting` | отказ (exit 1) | `Container <id> is restarting, wait until the container is running` |
| `created` / `exited` / `dead` | отказ (exit 1) | `Container <id> is not running` или `OCI runtime exec failed: ... cannot exec a container that has stopped` |

**Гонка (race condition):** контейнер был `running` на момент `docker ps`, но умер до `docker exec` — типично для crash-loop (см. **[Коды завершения](./docker_exit_codes.md)**, Сценарий 6).

### TTY и интерактивность

Флаг `-t` выделяет pseudo-TTY. В неинтерактивной среде (CI, скрипты, пайпы, `cron`) TTY нет — и `-t` падает:

```bash
docker exec -t my-app ls | grep app
# → the input device is not a TTY
```

**Правило:** `-it` — только для интерактивных сессий человека; в скриптах — без `-t`. Флаг `-i` (stdin) допустим без TTY. Отсоединить интерактивную сессию exec, не убивая её, — клавиши отсоединения (по умолчанию `Ctrl-p Ctrl-q`, как у `docker attach` и `docker run -it`; переопределяются через `--detach-keys`).

### Команда, оболочка и пайпы

Аргумент `COMMAND` exec — это **исполняемый файл**, а не строка shell: цепочки (`&&`, `;`), пайпы и подстановки не работают без оболочки:

```bash
docker exec my-app "ls | grep app"
# → exec: "ls | grep app": executable file not found in $PATH

docker exec my-app sh -c 'ls | grep app'
# → (вывод grep — подсчёт внутри контейнера)
```

Пайп и редирект **вне** кавычек выполняются на **хосте**: `grep` в `docker exec my-app ls | grep app` работает на хосте, фильтруя вывод exec. Пайп **внутрь** контейнера — через `-i`:

```bash
cat data.csv | docker exec -i my-app sh -c 'cat > /tmp/data.csv'
```

### Окружение, пользователь и рабочая директория

Exec-процесс **наследует окружение контейнера** (переменные из `ENV` образа и `docker run -e`). Флаги exec (полный список опций CLI):

| Флаг | Действие | Пример |
| :--- | :--- | :--- |
| `-e VAR=val` (`--env`, API 1.25+) | Добавить/переопределить переменную **только для exec-процесса** | `docker exec -e DEBUG=1 my-app ./run.sh` |
| `--env-file <file>` (API 1.25+) | Переменные из файла | `docker exec --env-file prod.env my-app ./run.sh` |
| `-u <name\|uid>[:<group\|gid>]` (`--user`) | Пользователь exec; дефолт — `USER` из образа (часто root) | `docker exec -u 1000:1000 my-app id` |
| `-w <dir>` (`--workdir`, API 1.35+) | Рабочая директория; дефолт — `WORKDIR` контейнера | `docker exec -w /app my-app pwd` |
| `--privileged` | Расширенные привилегии (например, для `mount` внутри) | `docker exec --privileged my-app mount -t tmpfs ...` |
| `-d` (`--detach`) | Фоновый режим без вывода | `docker exec -d my-app /app/task.sh` |

Изменения окружения через `-e` **не сохраняются** в контейнере и не видны другим процессам — только текущему exec-процессу.

### Коды завершения exec

`docker exec` возвращает код завершения запущенной команды; ошибки запуска следуют chroot-стандарту (`man docker-container-exec`):

| Код | Источник | Значение |
| :--- | :--- | :--- |
| **1** | CLI/daemon | Ошибка состояния: контейнер не `running` (stopped/paused/restarting), недоступен демон |
| **126** | chroot | Команда найдена, но не исполнима (нет права `x`) |
| **127** | chroot | Команда не найдена в `$PATH` контейнера |
| **128+N** | ядро | Exec-процесс убит сигналом `N` (137 — SIGKILL, в т.ч. OOM) |
| **0–255** | команда | Код завершения команды — транслируется как есть |

```bash
docker exec my-app foo; echo $?
# → exec: "foo": executable file not found in $PATH
# → docker: Error response from daemon: Contained command not found or does not exist
# → 127

docker exec my-app /bin/sh -c 'exit 3'; echo $?
# → 3
```

Текст ошибки запуска зависит от версии runc: старые демоны отвечают `Error response from daemon: exec: ...: unknown`, современные — `OCI runtime exec failed: exec failed: unable to start container process: ...`.

### Exec и ресурсы контейнера

Exec-процесс живёт в **том же cgroup**, что и PID 1: лимиты `--memory`/`--cpus` применяются к сумме всех процессов контейнера, а не к каждому по отдельности. При нехватке памяти OOM killer выбирает самого «жадного» процесс cgroup:

- убит exec-процесс → он завершается с **137**, контейнер **продолжает работать** (`docker inspect --format '{{.State.OOMKilled}}'` → `false`);
- убит PID 1 → контейнер умирает с **137** и `OOMKilled: true`.

`docker stats` показывает агрегат по cgroup — тяжёлый exec (бэкап, отчёт) виден в нём и может вытеснить приложение.

## Практические сценарии

### Сценарий 1: «Container is not running»

```bash
docker exec my-app ls
# → Error response from daemon: Container abc123 is not running

# 1. Состояние контейнера
docker ps -a --filter name=my-app
# → my-app   Exited (1)  2 minutes ago

# 2. Почему упал
docker logs --tail 30 my-app
docker inspect my-app --format 'ExitCode: {{.State.ExitCode}}, OOM: {{.State.OOMKilled}}'
```

Вариант **crash-loop с restart-политикой** — контейнер в цикле перезапусков:

```bash
docker exec my-app ls
# → Error response from daemon: Container abc123 is restarting, wait until the container is running

docker ps -a --filter name=my-app
# → my-app   Restarting (1) 5 seconds ago   ← цикл: entrypoint падает сразу после старта
```

**Решения по ситуации:**

| Ситуация | Решение |
| :--- | :--- |
| Контейнер упал один раз | `docker start my-app`, затем `docker exec` |
| Crash-loop | Отладка без restart-политики: `docker run --restart=no <image>` (см. **[docker_exit_codes.md](./docker_exit_codes.md)**) |
| Нужен shell в stopped-контейнере | `docker debug my-app` (Docker Desktop 4.33+, работает на stopped-контейнерах — см. **[docker_debug.md](./docker_debug.md)**) |
| Нужны файлы из stopped-контейнера | `docker cp my-app:/path/file ./` (работает на stopped) |
| Нужна интерактивная отладка ФС | `docker commit my-app tmp-img && docker run -it --entrypoint /bin/sh tmp-img` (создаёт новый контейнер без volumes оригинала) |

### Сценарий 2: «Container is paused»

```bash
docker pause my-app
docker exec my-app sh
# → Error response from daemon: Container my-app is paused, unpause the container before exec
# → echo $? → 1

# Диагностика: пауза всегда явная (docker pause)
docker ps --filter name=my-app
# → my-app   Up 5 minutes (Paused)
docker inspect my-app --format 'Paused: {{.State.Paused}}'
# → Paused: true

docker unpause my-app
docker exec my-app sh   # → работает
```

Процессы контейнера заморожены cgroup freezer, и демон отказывает exec ещё до создания процесса. Для отладки paused-контейнера без разморозки подходит `docker debug` (см. **[docker_debug.md](./docker_debug.md)** — работает и на `paused`).

### Сценарий 3: «the input device is not a TTY»

```bash
# В CI/скрипте — без -t
docker exec my-app ls /app
# → (вывод команды)

# Интерактивно — только с -it и живым stdin
docker exec -it my-app /bin/bash
```

**Диагностика:** если команда в пайпе (`| grep`, `| jq`) или в `cron`/CI — убрать `-t`. Флаг `-i` (stdin) допустим без TTY; `-t` — нет.

### Сценарий 4: «executable file not found in $PATH» / «OCI runtime exec failed»

**Причина:** в образе нет нужного исполняемого файла — distroless/scratch (см. **[debugging_distroless.md](./debugging_distroless.md)**) или slim-база (Alpine не содержит `bash`, только `sh`/`ash`).

```bash
docker exec my-app sh
# → Error response from daemon: exec: "sh": executable file not found in $PATH: unknown
# (современные runc:)
# → OCI runtime exec failed: exec failed: unable to start container process:
#    exec: "sh": executable file not found in $PATH
# → exit code 127
```

**Диагностика:**

```bash
# PATH внутри контейнера — это PATH образа, а не хоста
docker exec my-app sh -c 'echo $PATH; command -v my-tool'
# → /usr/local/sbin:... (и пустой вывод command -v, если инструмента нет)

# Бинарник есть, но не запускается: архитектура или shebang
docker exec my-app /app/tool
# → OCI runtime exec failed: ... exec format error
#   ← бинарник другой архитектуры (amd64 в arm64-контейнере и наоборот)

docker exec my-app /app/run.sh
# → /app/run.sh: /bin/sh: bad interpreter: No such file or directory
#   ← CRLF-окончания (Windows) или неверный shebang
```

**Альтернативы:**

```bash
docker debug my-app                           # Docker Desktop 4.33+
docker top my-app                             # процессы без shell
docker cp my-app:/etc/app/config.yaml ./      # файлы
docker run --rm --network=container:my-app nicolaka/netshoot ss -tulpn   # sidecar
```

### Сценарий 5: Exec зависает / нет вывода

**Причины:**

1. Приложение захватило stdin/stdout и не отдаёт их (например, PID 1 — интерактивная программа).
2. Контейнер в D-state (см. **[hung_containers.md](./hung_containers.md)**).
3. Команда внутри ждёт ввода (например, `mysql` без `-e`).
4. PID 1 не реапит дочерние процессы exec — зомби копятся (в старых версиях containerd exec мог зависать целиком, containerd#3286; принцип — использовать `--init`/tini, см. **[init_process_tini.md](../Dockerfile/init_process_tini.md)**).

```bash
# Проверка отзывчивости контейнера
timeout 5 docker exec my-app echo alive
# → alive  (или таймаут — контейнер завис, см. hung_containers.md)

# Какие процессы внутри, включая exec-процессы
docker top my-app

# Детached-режим для долгих команд
docker exec -d my-app /app/long-task.sh
```

### Сценарий 6: Permission denied внутри exec

```bash
docker exec my-app /app/migrate.sh
# → /app/migrate.sh: Permission denied

# 1. Права на файл в образе
docker exec my-app ls -l /app/migrate.sh
# → -rw-r--r-- 1 root root ...   ← нет x

# 2. Пользователь exec (дефолт — из образа, часто root)
docker exec -u root my-app id
# → uid=0(root) ...

# 3. ФС смонтирована с noexec (часто /tmp)
docker exec my-app mount | grep noexec
```

**Решение:** `RUN chmod +x` в Dockerfile; `-u` для другого UID; не монтировать исполняемые файлы на `noexec`-разделы.

### Сценарий 7: Exec-процесс не получает сигналы при `docker stop`

```bash
# PID 1 — shell-форма CMD, exec-процесс — долгая задача
docker exec my-app /app/worker.sh &
docker stop my-app
# → SIGTERM идёт PID 1 (shell), exec-процесс может не получить сигнал
```

**Правило:** `docker stop` сигнализирует только PID 1. Долгие задачи запускайте как PID 1 (exec-форма `CMD ["..."]`) или используйте `--init`/tini для проброса сигналов (см. **[init_process_tini.md](../Dockerfile/init_process_tini.md)**).

### Сценарий 8: Exec завершился с 137, контейнер жив

```bash
docker exec my-app /app/heavy-report.sh
# → (процесс убит) → echo $? → 137

docker ps --filter name=my-app
# → my-app   Up 2 hours   ← контейнер НЕ упал

docker inspect my-app --format 'OOMKilled: {{.State.OOMKilled}}'
# → OOMKilled: false   ← убит exec-процесс, а не PID 1

docker stats --no-stream my-app   # агрегат cgroup: MEM USAGE / LIMIT
dmesg | tail -5                   # след OOM killer'а на хосте
```

**Причина:** лимит памяти контейнера (`--memory`) общий для PID 1 и всех exec-процессов; OOM killer выбрал exec-процесс как самого «жадного». **Решения:** поднять лимит, оптимизировать задачу или вынести тяжёлую работу в отдельный контейнер с собственным лимитом.

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Container <id> is not running` | Контейнер stopped/exited | `docker ps -a`, `docker logs`, `docker start` или `docker debug` |
| `Container <id> is restarting, wait until...` | Crash-loop с restart-политикой | Сценарий 1; отладка entrypoint без `--restart` |
| `Container <id> is paused, unpause...` | Контейнер на паузе (`docker pause`) | `docker unpause`; для отладки — `docker debug` |
| `cannot exec a container that has stopped` (runc) | То же, что «not running», современный runc; или race с crash-loop | Сценарий 1 |
| `the input device is not a TTY` | `-t` без интерактивного stdin (CI, пайп) | Убрать `-t`; оставить `-i` при необходимости |
| `exec: "...": executable file not found in $PATH` (127) | Нет команды в образе; `$PATH` образа ≠ `$PATH` хоста | `command -v` внутри, установить в образ; `docker debug`, sidecar — см. **[debugging_distroless.md](./debugging_distroless.md)** |
| `OCI runtime exec failed: ... exec format error` | Бинарник другой архитектуры | Проверить `uname -m` контейнера и архитектуру бинарника |
| `bad interpreter: No such file or directory` на существующем скрипте | CRLF-окончания или неверный shebang | `dos2unix`; shebang `#!/bin/sh` |
| `Permission denied` на скрипт (126/1) | Нет права `x` или `noexec`-маунт | `chmod +x` в Dockerfile; проверить `mount \| grep noexec` |
| Exec зависает | D-state контейнера, приложение блокирует stdio или зомби от exec | **[hung_containers.md](./hung_containers.md)**; `timeout N docker exec ...`; `docker top` |
| Exec завершился 137, контейнер жив | OOM kill exec-процесса (общий cgroup) | Сценарий 8; лимиты памяти, отдельный контейнер для тяжёлых задач |
| `Cannot connect to the Docker daemon` | Недоступен демон | **[docker_daemon_failures.md](./docker_daemon_failures.md)** |
| `No such container: <name>` | Контейнер удалён (`--rm` после выхода) | `docker ps -a`; запустить заново |
| Exec работает, но изменения не видны приложению | Exec-процесс в другом mount namespace (редко) или read-only rootfs | Проверить `docker inspect --format '{{.HostConfig.ReadonlyRootfs}}'` |

## Валидация

```bash
# 1. Контейнер running
docker inspect my-app --format '{{.State.Status}}'
# → running

# 2. Exec выполняется и возвращает код команды
docker exec my-app /bin/sh -c 'exit 7'; echo $?
# → 7

# 3. Без TTY в скрипте
docker exec my-app ls /app | head -1
# → (первая строка списка, без ошибки TTY)

# 4. Другой пользователь
docker exec -u nobody my-app id
# → uid=65534(nobody) ...

# 5. Пауза блокирует exec (exit 1), unpause — восстанавливает
docker pause my-app && docker exec my-app echo hi; echo "exit=$?"
# → Error response from daemon: Container my-app is paused, unpause the container before exec
# → exit=1
docker unpause my-app

# 6. Неизвестная команда — chroot-стандарт 127
docker exec my-app no-such-tool; echo $?
# → 127

# 7. Пайп внутрь контейнера через sh -c
docker exec my-app sh -c 'ls /app | grep -c .'
# → (число файлов — подсчёт внутри контейнера)

# 8. Stdin в контейнер через -i
echo test | docker exec -i my-app sh -c 'cat'
# → test
```

## Лучшие практики

1. **`-it` — только для людей.** В CI/скриптах/`cron` — без `-t`, иначе «the input device is not a TTY».
2. **Проверяйте состояние перед exec в CI:** `state=$(docker inspect -f '{{.State.Status}}' my-app); [ "$state" = running ] || { docker logs --tail 50 my-app; exit 1; }` — превращает загадочный runtime-error в понятный startup-failure.
3. **Не полагайтесь на exec для диагностики stopped-контейнера** — `docker logs`, `docker inspect`, `docker cp`, `docker debug` работают и без running-статуса.
4. **Exec не заменяет PID 1** — для корректных сигналов используйте exec-форму `CMD` и `--init`.
5. **`timeout` вокруг exec** в скриптах мониторинга — зависший exec не должен вешать runbook.
6. **Read-only rootfs** (`--read-only`) блокирует запись через exec — планируйте `tmpfs`-маунты для `/tmp` (см. **[docker_volumes.md](../Docker_fs/docker_volumes.md)**).
7. **Тяжёлые задачи — не в exec.** Бэкапы и отчёты разделяют cgroup с приложением: выносите их в отдельный контейнер с собственным лимитом памяти.
8. **Цепочки и пайпы — только через `sh -c`**, иначе exec ищет один файл с пробелами в имени; пайп вне кавычек выполняется на хосте.
9. **Аудит exec**: события `exec_create`/`exec_start`/`exec_die` в `docker events` (см. **[debugging_with_docker_events.md](./debugging_with_docker_events.md)**, Сценарий 4).

## Дополнительная информация

### Exec vs docker debug vs docker run

| Критерий | `docker exec` | `docker debug` | `docker run --entrypoint` |
| :--- | :--- | :--- | :--- |
| Состояние контейнера | только `running` (не paused/restarting/stopped) | running, paused, stopped, образ | новый контейнер |
| Shell в образе | требуется | не требуется (Toolbox Nix) | требуется |
| Изменения ФС | видны контейнеру | видны (running); отбрасываются (stopped/образ) | в новом контейнере |
| Доступность | любой Engine | Docker Desktop 4.33+ | любой Engine |

### Exec в автоматизации (API)

CLI `docker exec` — надстройка над двумя вызовами API: `POST /containers/{id}/exec` (создаёт exec-конфигурацию: команда, env, TTY, пользователь) и `POST /exec/{id}/start` (запуск с привязкой stdio). Для массовых/параллельных задач автоматизации иногда выгоднее работать с API напрямую. Минимальные версии API для флагов: `-e`/`--env-file` — 1.25+, `-w` — 1.35+ (по таблице опций документации).

### См. также

- **[Отладка контейнеров](./docker_debug.md)** — `docker debug` как замена exec для stopped/paused/distroless.
- **[Отладка distroless](./debugging_distroless.md)** — методы без shell.
- **[Зависшие контейнеры](./hung_containers.md)** — когда exec зависает.
- **[Коды завершения](./docker_exit_codes.md)** — почему контейнер не running; коды 125–143 для `docker run`.
- **[Ошибки демона](./docker_daemon_failures.md)** — когда сам демон недоступен.
- **[Init-процесс tini](../Dockerfile/init_process_tini.md)** — сигналы и зомби.

**Глубокое изучение:**
- **[moby/moby#30361](https://github.com/moby/moby/issues/30361)** — почему exec в stopped-контейнере невозможен по дизайну и обходные пути.
- **[docker exec (документация)](https://docs.docker.com/reference/cli/docker/container/exec/)** — полный список флагов и примеры, включая paused-контейнер.
