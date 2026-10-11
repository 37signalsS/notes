# Отладка Distroless-контейнеров

**Актуально для:** Docker Desktop 4.33+ (`docker debug`); Google Distroless (debian12/13, теги `:debug`/`:debug-nonroot`); Chainguard/Wolfi (`-dev`-варианты)

## Определения

**Distroless-образы** — минималистичные базовые образы, содержащие только приложение и его зависимости времени выполнения. В них отсутствуют оболочка (shell), менеджеры пакетов и стандартные Unix-утилиты.

**Проблема отладки:** стандартный подход `docker exec -it <container> /bin/sh` завершается ошибкой — в образе нет ни `/bin/sh`, ни `/bin/bash`:

```bash
docker exec -it my-distroless-app sh
# → Error response from daemon: exec: "sh": executable file not found in $PATH: unknown
```

**Типичные представители:**
- **`gcr.io/distroless/*`** — образы от Google на базе Debian (glibc). Теги: `:latest` (root), `:nonroot` (UID/GID 65532), `:debug` (добавлен BusyBox), `:debug-nonroot`. У образов рантаймов задан entrypoint (например, `nodejs` → `node`), поэтому `CMD` принимает аргументы приложения.
- **`FROM scratch`** — абсолютно пустой образ для статически скомпилированных бинарников (Go, Rust, C/C++ со статической линковкой).
- **Chainguard / Wolfi** — образы на базе «un-distro» Wolfi, скомпилированные против `glibc` (не musl, в отличие от Alpine; пакеты Wolfi и Alpine несовместимы). Shell (`ash` из BusyBox) и менеджер пакетов `apk` — только в `-dev`-вариантах и `wolfi-base`. Позиционируются как secure-by-default: запуск от non-root (UID 65532) по умолчанию, минимальная поверхность CVE.

## Основные концепции

### Почему distroless усложняют работу

| Характеристика | Стандартный образ (Debian/Alpine) | Distroless / Scratch |
| :--- | :--- | :--- |
| **Shell** | `/bin/sh`, `/bin/bash` | Отсутствует |
| **Утилиты** | `ls`, `ps`, `curl`, `netstat`, `ip` | Отсутствуют |
| **Менеджер пакетов** | `apt`, `apk`, `yum` | Отсутствует |
| **Поверхность атаки** | Большая (много лишнего ПО) | Минимальная |
| **Пользователь по умолчанию** | Часто `root` | Distroless: root (`:latest`) / UID 65532 (`:nonroot`); Chainguard: non-root (UID 65532) |

### Требования к методам отладки

| Метод | Требования |
| :--- | :--- |
| `docker debug` | Docker Desktop 4.33+ (в standalone Docker Engine недоступен — docker/roadmap#893) |
| Sidecar (`--network=container:`, `--pid=container:`) | Любой Docker Engine |
| `kubectl debug` | RBAC: `create` на `pods/ephemeralcontainers` |
| `nsenter` | `root`/`sudo` на хосте; не работает под gVisor |
| Inspektor Gadget (`ig`) | `sudo`, доступ к ядру хоста (eBPF); не работает под gVisor |
| Remote Debug | Отладочная сборка (Delve/JDWP) и открытый порт |

### Стратегии отладки

1. **Диагностика с хоста (без shell):** `docker logs`, `inspect`, `top`, `diff`, `cp`, `export` — работают извне и не требуют утилит внутри контейнера.
2. **Интерактивная среда (Docker Debug):** нативный инструмент Docker Desktop — эфемерный sidecar с Toolbox (на базе Nix).
3. **Debug-теги образов:** `:debug` (distroless, BusyBox) и `-dev` (Chainguard, apk+shell) — временная подмена базового образа.
4. **Эфемерные контейнеры (Sidecars):** временный контейнер (`nicolaka/netshoot`), разделяющий namespaces с целью.
5. **eBPF-трассировка:** Inspektor Gadget, Parca — анализ системных вызовов и сети без внедрения в контейнер.
6. **Вход через namespaces (nsenter):** прямое подключение к процессам через ядро Linux (требует привилегий хоста).
7. **Удалённая отладка (Remote Debugging):** подключение IDE к отладочному порту рантайма (Delve, JDWP, V8 inspector).

Подробно о пространствах имён: **[Namespaces](../../Linux/Core/namespaces.md)**.

## Практические сценарии

### Сценарий 1: Первая диагностика без shell

Большинство вопросов решается с хоста — вход в контейнер не нужен:

```bash
# Логи приложения (stdout/stderr PID 1)
docker logs --tail 100 my-distroless-app

# Конфигурация: переменные, код завершения, IP
docker inspect --format '{{.Config.Env}} | {{.State.ExitCode}} | {{.NetworkSettings.IPAddress}}' my-distroless-app

# Процессы внутри контейнера (ps выполняется на хосте — shell в контейнере не нужен)
docker top my-distroless-app aux
# → PID   USER     TIME  COMMAND
# → 1     root     0:00  /app/server

# Изменения файловой системы с момента запуска (A=added, C=changed, D=deleted)
docker diff my-distroless-app
# → C /app
# → A /tmp/cache.dat

# Копирование файлов наружу (работает и для остановленных контейнеров)
docker cp my-distroless-app:/app/config.yaml ./config.yaml

# Полная файловая система контейнера в tar (без данных из volumes)
docker export my-distroless-app -o filesystem.tar

# Ресурсы
docker stats --no-stream my-distroless-app

# Аргументы к entrypoint (у distroless entrypoint задан — например, node)
docker run --rm gcr.io/distroless/nodejs22-debian13 --version
# → v22.x.x
```

**Ограничения:** `docker top`/`diff`/`logs` дают наблюдение, но не интерактивную среду; `docker export` не включает содержимое volumes.

### Сценарий 2: Docker Debug (Docker Desktop 4.33+)

Рекомендуемый метод для локальной разработки: команда создаёт эфемерный отладочный контейнер с Toolbox (Nix), подключённый к namespaces цели, — работает даже для остановленных контейнеров и образов, не изменяя их.

```bash
docker debug my-distroless-app
# → [info] Starting debug session for container "my-distroless-app"...
# → [root@docker-desktop /]# ls -l /app
```

**Преимущества:**
- **Toolbox:** мгновенный доступ к `vim`, `curl`, `htop`, `ps`, `ip` там, где их нет; доустановка на лету через `install <pkg>`.
- **Безопасность:** инструменты Nix физически изолированы от приложения (директория `/nix` не видна процессам цели).

Полное описание, флаги (`--shell`, `--command`, `--host`) и Build Debugging: **[Docker Debug](./docker_debug.md)**.

### Сценарий 3: Debug-теги Google Distroless

Официальный способ получить shell в distroless — подменить тег базового образа на `:debug` (добавлен BusyBox с 380+ утилитами, бинарник `/busybox/busybox`):

```dockerfile
# Dockerfile (временно, только для отладки)
FROM gcr.io/distroless/python3-debian13:debug
COPY . /app
WORKDIR /app
CMD ["hello.py"]
```

```bash
# Запуск с переопределением entrypoint — BusyBox sh
docker run --rm -it --entrypoint=/busybox/sh gcr.io/distroless/python3-debian13:debug
# → / # ls /app

# Если тег уже занят (например, :nonroot), debug-вариант — :debug-nonroot
docker run --rm -it --entrypoint=/busybox/sh gcr.io/distroless/java17-debian13:debug-nonroot
```

**Нюансы:**
- `sh` также разрешается через симлинки BusyBox (`--entrypoint=sh`), но явный путь `/busybox/sh` гарантированно работает.
- Debug-образ больше production-образа и содержит shell — никогда не используйте его в production.
- Для образов с заданным entrypoint (`nodejs`, `java`) переопределение `--entrypoint` обязательно, иначе запустится рантайм, а не shell.

### Сценарий 4: Chainguard / Wolfi `-dev`-варианты

Chainguard-образы поставляются парами: минимальный production-тег и `-dev`-вариант с shell (`ash` из BusyBox) и менеджером пакетов `apk`:

```bash
# Production-образ (нет shell)
docker run --rm cgr.dev/chainguard/static:latest

# Debug-вариант: shell + apk
docker run --rm -it --entrypoint=/bin/sh cgr.dev/chainguard/static:latest-dev
# → / # apk add curl
# → OK: ... distinct packages available
```

**Нюансы:**
- Wolfi использует `glibc` — бинарники Alpine (musl) не запускаются в Chainguard-образах и наоборот.
- `-dev`-варианты предназначены для сборки и тестирования; в production копируйте артефакты из них через multi-stage сборку.
- `wolfi-base` (`cgr.dev/chainguard/wolfi-base`) — базовый образ с `apk` и `busybox` для сборки собственных образов.

### Сценарий 5: Эфемерные отладочные контейнеры (Sidecars)

Если `docker debug` недоступен (standalone Engine), подключите sidecar к namespaces цели через `docker run`:

**Анализ сети (через Network Namespace):**
```bash
docker run --rm -it --network=container:my-distroless-app nicolaka/netshoot ss -tulpn
# → Netid  State   Recv-Q  Send-Q  Local Address:Port
# → tcp    LISTEN  0       128     0.0.0.0:8080
```

**Анализ процессов и ФС (через PID Namespace):**
```bash
docker run --rm -it --pid=container:my-distroless-app alpine sh
# → ps aux            # процессы цели видны в общем PID namespace
# → ls /proc/1/root/etc/   # ФС цели: PID 1 — init целевого контейнера
```

**Нюансы:**
- `--privileged` не требуется для разделения namespaces — он нужен только для доступа к устройствам хоста и полного набора capabilities.
- Sidecar работает на любом Docker Engine, включая production-серверы без Desktop.
- В Kubernetes аналог — эфемерные контейнеры (Сценарий 6).

### Сценарий 6: Отладка в Kubernetes (kubectl debug)

Стандартный способ для кластеров — эфемерный контейнер внутри пода, разделяющий namespaces с целевым контейнером:

```bash
kubectl debug -it my-pod --image=nicolaka/netshoot --target=my-app-container
# / # curl localhost:8080/health
# → {"status":"ok"}
```

**Требования:** RBAC-право `create` на `pods/ephemeralcontainers`; эфемерный контейнер нельзя добавить к уже завершённому pod'у.

Подробнее: **[Ephemeral Containers](../../Kubernetes/Base/Pod/ephemeral_containers.md)**.

### Сценарий 7: Прямой вход через nsenter

Метод для глубокой диагностики при наличии доступа к хосту (требует `sudo`): выполнение команд в контексте контейнера с использованием бинарников хоста:

```bash
PID=$(docker inspect -f '{{.State.Pid}}' my-distroless-app)
sudo nsenter -t "$PID" -m -u -i -n -p sh
# → sh-5.1# ls /app     # ФС, сеть и процессы контейнера
```

Флаги `-m -u -i -n -p` подключают mount, UTS, IPC, network и PID namespaces. Пошаговое руководство: **[Утилита nsenter](../../Linux/Diagnostics/Processes/nsenter.md)**.

**Ограничение:** под sandboxed runtime (gVisor) nsenter не работает напрямую — syscalls перехватываются, а процессы гостя не видны в `/proc` хоста (см. **[Sandboxed Runtimes](../Docker_security/container_hardening.md)**).

### Сценарий 8: Трассировка через eBPF (Inspektor Gadget)

Метод без shell и sidecar: eBPF-программы собирают события в ядре, Inspektor Gadget обогащает их именами контейнеров:

```bash
# Отслеживание открываемых файлов (ENOENT — пропущенные конфиги, EACCES — права)
sudo ig trace open -c my-distroless-app
# → RUNTIME.CONTAINERNAME   PID    COMM   FD  ERR  PATH
# → my-distroless-app       1234   app    3   2    /etc/app/missing.yaml

# Отслеживание DNS-запросов
sudo ig trace dns -c my-distroless-app
# → RUNTIME.CONTAINERNAME   PID   TID   COMM   QR    TYPE     QTYPE  NAME
# → my-distroless-app       1234  1235  app    Q     OUTGOING A      api.example.com

# Полный путь файла (разрешение симлинков)
sudo ig trace open -c my-distroless-app --full-path
```

**Нюансы:**
- Требуется `sudo` (eBPF) и доступ к ядру хоста; под gVisor не работает.
- Фильтр контейнера — короткий флаг `-c` (длинная форма `--containername`); без фильтра видны все контейнеры хоста.
- В Kubernetes — плагин `kubectl gadget` (`kubectl gadget run trace_open:latest`); новая CLI-форма: `ig run trace_open:latest`.
- Проект: **[Inspektor Gadget](https://github.com/inspektor-gadget/inspektor-gadget)**.

### Сценарий 9: Удалённая отладка (Remote Debugging)

Пошаговая отладка кода, работающего в distroless. Отладчик должен быть включён в образ (multi-stage), а порт опубликован:

1. **Go (Delve):**
   ```dockerfile
   FROM golang:1.23 AS build
   RUN go build -gcflags="all=-N -l" -o /app/server ./cmd
   RUN go install github.com/go-delve/delve/cmd/dlv@latest

   FROM gcr.io/distroless/static-debian12:nonroot
   COPY --from=build /app/server /app/server
   COPY --from=build /go/bin/dlv /dlv
   USER nonroot:nonroot
   ```
   ```bash
   docker run --rm -p 40000:40000 my-app /dlv --listen=:40000 --headless=true --api-version=2 --allow-non-terminal-interactive=true exec /app/server
   ```
2. **Java (JDWP):** добавьте агент к запуску:
   ```bash
   docker run --rm -p 5005:5005 my-java-app \
     -agentlib:jdwp=transport=dt_socket,server=y,suspend=n,address=*:5005
   ```
3. **Node.js (V8 inspector):** `node --inspect=0.0.0.0:9229 app.js`, порт `9229`.
4. **Подключение:** в IDE (VS Code/JetBrains) настройте Remote Debug на опубликованный порт.

**Нюанс:** сборка с отладочной информацией (`-N -l` для Go) и открытый порт отладчика — только для сред разработки и тестирования.

### Сценарий 10: Отладка сборки (multi-stage)

Если проблема воспроизводится на этапе сборки — выделите отладочную стадию и соберите до неё:

```dockerfile
FROM golang:1.23 AS debug
WORKDIR /src
COPY . .
# Здесь можно интерактивно проверить окружение
```

```bash
docker build --target debug -t my-app:debug .
docker run --rm -it my-app:debug sh
```

Для точек останова на инструкциях `Dockerfile` — Build Debugging (Docker Desktop 4.46+, Buildx 0.29+): **[Docker Debug, сценарий 9](./docker_debug.md)**.

## Операции и команды

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `docker logs` | stdout/stderr PID 1 | `docker logs --tail 100 my-app` |
| `docker inspect` | Конфигурация, env, mounts, код завершения | `docker inspect --format '{{.State.ExitCode}}' my-app` |
| `docker top` | Процессы контейнера (`ps` на хосте) | `docker top my-app aux` |
| `docker diff` | Изменения ФС (`A`/`C`/`D`) | `docker diff my-app` |
| `docker cp` | Копирование файлов (и в stopped-контейнер) | `docker cp my-app:/app/config.yaml ./` |
| `docker export` | ФС контейнера в tar (без volumes) | `docker export my-app -o fs.tar` |
| `docker image save` | Образ со слоями в tar | `docker image save my-app:latest -o image.tar` |
| `docker stats` | Потребление ресурсов | `docker stats --no-stream my-app` |
| `docker events` | События жизненного цикла | `docker events --filter container=my-app` |
| `docker run --entrypoint` | Запуск другого бинарника из образа | `docker run --rm --entrypoint=/busybox/sh gcr.io/distroless/python3-debian13:debug` |
| `docker debug` | Отладочная сессия (Desktop 4.33+) | `docker debug my-app` |
| `docker run --network=container:` | Sidecar в сетевом namespace | `docker run --rm -it --network=container:my-app nicolaka/netshoot ss -tulpn` |
| `docker run --pid=container:` | Sidecar в PID namespace | `docker run --rm -it --pid=container:my-app alpine sh` |
| `kubectl debug` | Эфемерный контейнер в pod | `kubectl debug -it my-pod --image=nicolaka/netshoot --target=my-app` |
| `nsenter` | Вход в namespaces с хоста | `sudo nsenter -t $(docker inspect -f '{{.State.Pid}}' my-app) -m -u -i -n -p sh` |
| `ig trace open` / `ig trace dns` | eBPF-трассировка файлов/DNS | `sudo ig trace open -c my-app` |

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `exec: "sh": executable file not found in $PATH` | Нет shell в образе — норма для distroless/scratch | Не ошибка: используйте `docker debug`, sidecar, `:debug`-тег или `docker cp` |
| `docker: 'debug' is not a docker command` | Standalone Docker Engine или Desktop < 4.33 | Обновить Docker Desktop до 4.33+; на серверах — sidecar или `nsenter` (**[Docker Debug](./docker_debug.md)**) |
| `kubectl debug` → `forbidden: ... cannot create resource "pods/ephemeralcontainers"` | Нет RBAC на подресурс | Запросить у администратора кластера роль с `create` на `pods/ephemeralcontainers` |
| `nsenter: Operation not permitted` | Нет `root`/`sudo` на хосте | Запускать через `sudo`; в rootless-режиме недоступен |
| nsenter не видит процессов контейнера | Sandboxed runtime (gVisor) перехватывает syscalls | Использовать `docker debug` или sidecar; eBPF также ограничен |
| `docker cp` не записывает файл в контейнер | Read-only rootfs (`--read-only`) | Копировать только из контейнера; запись — через volumes |
| `docker export` не содержит данных приложения | Данные лежат в volumes, а не в ФС контейнера | `docker cp` из volume или хостовая директория (`docker inspect` → `.Mounts`) |
| `ig trace open` → `operation not permitted` | eBPF требует привилегий | Запускать через `sudo` |
| `docker run --entrypoint=sh` на `:debug`-образе не находит shell | BusyBox установлен в `/busybox` | Использовать явный путь: `--entrypoint=/busybox/sh` |
| Изменения в `docker debug` не видны приложению | Отлаживается остановленный контейнер или образ — изменения отбрасываются | Для горячих правок нужен running-контейнер (**[Docker Debug](./docker_debug.md)**) |

## Валидация

```bash
# 1. Диагностика без shell работает
docker top my-distroless-app
# → PID  USER  TIME  COMMAND (процессы видны без shell в контейнере)

# 2. Debug-тег distroless даёт shell
docker run --rm --entrypoint=/busybox/sh gcr.io/distroless/python3-debian13:debug -c 'ls /'
# → bin  boot  dev  etc  home  ...  busybox

# 3. Sidecar видит сеть цели
docker run --rm --network=container:my-distroless-app nicolaka/netshoot ss -tlnp
# → LISTEN на порту приложения

# 4. docker debug доступен (Docker Desktop 4.33+)
docker debug --help
# → Usage: docker debug [OPTIONS] {CONTAINER|IMAGE}
```

## Лучшие практики

1. **Debug-теги:** для Google Distroless держите рядом варианты `:debug`/`:debug-nonroot` для быстрой подмены в случае ЧП; в production используйте только минимальные теги.
2. **Chainguard Dev:** `-dev`-варианты — только на этапах сборки и тестирования; в production копируйте артефакты из них через multi-stage.
3. **Централизованное логирование:** все ошибки — в `stdout` (Loki, ELK), так как «войти» в упавший контейнер часто невозможно.
4. **Проверки здоровья:** **[HEALTHCHECK](../Dockerfile/Instructions/health_signals.md)** — Docker автоматически перезапускает зависшие процессы.
5. **Изоляция (Sandboxing):** под gVisor (**[Sandboxed Runtimes](../Docker_security/container_hardening.md)**) `nsenter` и eBPF-инструменты работают ограниченно — закладывайте альтернативы (sidecar, `docker debug`).
6. **Не фиксируйте правки в контейнере:** изменения в running-контейнере теряются при его удалении; крайний случай — **[docker commit](../Docker_fs/docker_commit.md)**, правильный путь — пересборка образа.
7. **Pin образов по digest** в production, чтобы debug-окружение совпадало с production: **[Supply Chain](../../Security/Supply_Chain_Security/container_image_supply_chain.md)**.

## Дополнительная информация

### Сравнение методов отладки

| Метод | Плюсы | Минусы | Применимость |
| :--- | :--- | :--- | :--- |
| **`docker debug`** | Встроенный Nix Toolbox, работает на stopped-контейнере и образе | Нужен Docker Desktop 4.33+; недоступен в standalone Engine | Локально, Staging |
| **`:debug`-теги distroless** | Официальный BusyBox, смена тега в Dockerfile | Пересборка/перезапуск; shell больше production-образа | Локально, CI |
| **Chainguard `-dev`** | `apk` + shell `ash` | Расширенный состав; только не-production | Сборка, тест |
| **Sidecar (Netshoot)** | Огромный набор утилит, любой Engine | Нужно имя/ID контейнера; отдельный контейнер | Универсально |
| **eBPF (`ig`)** | Без shell и sidecar, низкие накладные расходы | Нужен `sudo` и ядро хоста; не работает под gVisor | Глубокая диагностика |
| **`kubectl debug`** | Нативно для K8s, эфемерный | Требует RBAC на `pods/ephemeralcontainers` | Production (K8s) |
| **[`nsenter`](../../Linux/Diagnostics/Processes/nsenter.md)** | Нет лишних контейнеров | Нужен `root` на хосте; не работает под gVisor | Узлы инфраструктуры |
| **`docker top`/`diff`/`cp`/`export`** | Работает на любом Engine, без shell | Только наблюдение и файлы, нет интерактива | Первая диагностика |
| **Remote Debug** | Пошаговая отладка кода | Требует спец. сборки и открытых портов | Разработка / Тестирование |

### См. также

- **[Docker Debug](./docker_debug.md)** — описание нативной команды.
- **[Ephemeral Containers](../../Kubernetes/Base/Pod/ephemeral_containers.md)** — отладка в Kubernetes.
- **[Утилита lsns](../../Linux/Diagnostics/Processes/lsns.md)** — поиск и инспекция пространств имен.
- **[Утилита nsenter](../../Linux/Diagnostics/Processes/nsenter.md)** — вход в изолированные окружения.
- **[Namespaces](../../Linux/Core/namespaces.md)** — основы изоляции в Linux.
- **[Коды завершения](./docker_exit_codes.md)** — понимание причин остановки distroless-контейнеров.
- **[Google Distroless](https://github.com/GoogleContainerTools/distroless)** — официальный репозиторий образов.
- **[Inspektor Gadget](https://github.com/inspektor-gadget/inspektor-gadget)** — eBPF-инструментарий.
