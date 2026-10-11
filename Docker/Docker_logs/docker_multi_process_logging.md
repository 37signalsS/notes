# Паттерн "Multi-Process" в Docker

**Актуально для:** Docker Engine 29.x, s6-overlay v3.2.3.x, Alpine Linux 3.24.x

## Определения

**Паттерн "Multi-Process"** — архитектурный подход, при котором внутри одного Docker-контейнера запускается несколько тесно связанных процессов, образующих единый функциональный блок (микрослужбу). Примером может служить связка `Nginx + PHP-FPM` или `App + Sidecar-агент`.

**Проблема PID 1** — техническая особенность ядра Linux, при которой процесс с идентификатором 1 (init) имеет особые обязанности:
1.  **Reaping (Утилизация зомби)**: PID 1 обязан "усыновлять" процессы-сироты и считывать их код завершения, предотвращая появление "зомби".
2.  **Signal Forwarding (Проброс сигналов)**: Docker отправляет сигналы остановки (`SIGTERM`) только процессу PID 1. Если это обычное приложение или shell-скрипт, он может не передать сигнал дочерним процессам, что приведет к их принудительному завершению (`SIGKILL`) по таймауту.

**Init-система для контейнеров** — легковесный менеджер процессов, который берет на себя роль PID 1 в контейнере: корректно пробрасывает сигналы дочерним процессам и очищает зомби. Основные реализации: `tini`, `dumb-init`, `s6-overlay`.

**Zombie Process (Процесс-зомби)** — завершенный процесс, который уже не выполняется, но запись о нем остается в таблице процессов, так как родитель (PID 1) не вызвал `wait()` для сбора статуса. Зомби не потребляют ресурсы, но занимают запись в таблице процессов. При переполнении таблицы (~32768 записей) ядро отказывает в создании новых процессов.

## Предпосылки

- **Docker Engine** версии 29.x (актуальная версия на 2026 год, Dual Logging доступен с 20.10+)
- **Docker CLI** с правами root или членство в группе `docker`
- **Понимание POSIX-сигналов**: `SIGTERM`, `SIGKILL`, `SIGCHLD`, `SIGINT` — что делает каждый сигнал и как приложение должен его обрабатывать
- **Понимание Exec Form vs Shell Form** в Dockerfile: Exec Form (`CMD ["app"]`) делает приложение PID 1, Shell Form (`CMD app`) — PID 1 получает `/bin/sh -c`
- **Доступ к базе знаний**: Смежные файлы для глубокого изучения:
  - **[Выполнение приложений в контейнере](../Dockerfile/Docker_best_practices/container_execution.md)** — глубокое погружение в PID 1, сигналы и Exec/Shell Form
  - **[Systemd в Docker: анти-паттерн](../docker_systemd.md)** — почему полноценная ОС в контейнере обычно является ошибкой

**Быстрая диагностика PID 1:**
```bash
# Кто PID 1 в контейнере?
docker exec <container> ps -p 1 -o comm=
# → tini (хорошо) | node (риск) | /bin/sh (плохо)

# Есть ли зомби?
docker exec <container> ps aux | grep -w Z
# → В норме: пусто
# → Проблема: видны <defunct> строки
```

## Базовые концепции

### Философия "Функционального блока" (2026)

Классическая догма "один процесс на контейнер" в современной практике заменена на **"один функциональный блок на контейнер"**. Это допустимо при соблюдении условий:
*   Процессы имеют одинаковый жизненный цикл (если падает один, контейнер должен быть перезапущен).
*   Процессы тесно связаны (обмен через Unix-сокеты, разделяемая память или `localhost`).
*   Используется специализированная система инициализации (Init system).
*   Существует единая точка наблюдения (health-check) и стратегия сбора логов.

**Когда Multi-Process оправдан:**
*   **App + Sidecar**: приложение + агент мониторинга/метрик (Prometheus exporter, Fluentd-агент)
*   **Web + Worker**: Nginx + PHP-FPM, App + Celery worker (общий жизненный цикл)
*   **App + Миграции**: приложение + скрипт миграции БД (одноразовый запуск при старте)
*   **Legacy-моноролит**: миграция на микросервисы невозможна в краткосрочной перспективе, разделение требует рефакторинга архитектуры

**Когда Multi-Process НЕ оправдан:**
*   Процессы имеют разные жизненные циклы (БД + приложение)
*   Процессы не связаны между собой
*   Нет средств инициализации (tini/s6) — риск накопления зомби
*   Процессы требуют разных политик безопасности (разные `USER`, `CAP_ADD`)

### Exec Form vs Shell Form и PID 1

Выбор формы записи в Dockerfile критически влияет на PID 1 и проброс сигналов:

| Характеристика | Exec Form (`["app", "arg"]`) | Shell Form (`app arg`) |
| :--- | :--- | :--- |
| **PID процесса** | Приложение получает PID 1 | `/bin/sh` получает PID 1 |
| **Проброс сигналов** | Напрямую приложению | Блокируется оболочкой |
| **Зомби-процессы** | Не обрабатываются (требует init) | Оболочка частично обрабатывает |

**Антипаттерн:**
```dockerfile
# ПЛОХО: sh станет PID 1, SIGTERM не дойдет до приложения
CMD node server.js

# ХОРОШО: node становится PID 1 напрямую
CMD ["node", "server.js"]
```

### Сравнение систем инициализации

| Характеристика | systemd (внутри) | Tini / dumb-init | Supervisord / s6 |
| :--- | :--- | :--- | :--- |
| **Цель** | Эмуляция полной ОС | Только решение проблемы PID 1 | Групповой запуск служб |
| **Сложность** | Максимальная | Минимальная | Средняя |
| **Изоляция** | Требует `SYS_ADMIN` | Стандартная | Стандартная |
| **Сбор зомби** | Да | Да | Да |
| **Управление логами** | Полное (journalctl) | Нет (только проброс) | Перенаправление stdout/stderr |
| **Зависимости** | Да (systemd units) | Нет | Да (s6-rc dependencies) |
| **Overhead** | ~50-100 МБ RAM | ~20 КБ | ~1-5 МБ RAM |
| **Рекомендация** | Антипаттерн для Docker | Для одиночных процессов | Для multi-process контейнеров |

**Подробнее:**
- **[Systemd в Docker](../docker_systemd.md)** — детальный разбор почему systemd является анти-паттерном
- **[Выполнение приложений в контейнере](../Dockerfile/Docker_best_practices/container_execution.md)** — Exec Form vs Shell Form, STOPSIGNAL, пошаговый разбор `docker stop`

### Механизм захвата логов в s6-overlay

`s6-overlay` использует двухуровневую архитектуру для управления логами:
1. **s6-svscan** (PID 1) — сканирует директорию `/etc/s6-overlay/s6-rc.d/` и управляет жизненным циклом сервисов.
2. **s6-log** — утилита, которая запускается для каждого `longrun` сервиса и перехватывает его stdout/stderr через именованный канал (FIFO). `s6-log` добавляет к каждой строке префикс с именем сервиса и временной меткой, затем передаёт в общий stdout контейнера.

**Преимущество для логов**: s6-overlay автоматически перехватывает вывод сервисов и добавляет к ним метаданные (имя сервиса, timestamp) перед отправкой в основной лог контейнера. Каждый процесс получает свой префикс, что упрощает фильтрацию.

**Ограничение**: `s6-log` добавляет overhead в виде дополнительного процесса на каждый сервис. При >10 сервисах в одном контейнере это может сказаться на потреблении памяти. Для критичных по памяти сред используйте `logger` или `syslogd` из `s6-overlay-syslogd` пакета.

### Health-checks в multi-process контейнерах

В контейнере с несколькими сервисами единый `HEALTHCHECK` должен проверять готовность **всех** процессов, а не только основного. Docker Health-check работает на уровне контейнера, поэтому его реализация зависит от выбранного менеджера процессов:

**Вариант A: Единый health-check скрипт (s6-overlay)**
```bash
#!/bin/sh
# healthcheck.sh

# Проверка nginx
if ! curl -sf http://localhost:8080/healthz > /dev/null; then
  exit 1
fi

# Проверка php-fpm через FastCGI
if ! echo -e "GET / HTTP/1.1\r\n\r\n" | timeout 2 nc -U /run/php/php-fpm.sock > /dev/null 2>&1; then
  exit 1
fi

exit 0
```

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
  CMD ["/bin/sh", "/etc/s6-overlay/healthcheck.sh"]
```

**Вариант B: Per-service health-check (Supervisord)**
```ini
[program:app]
command=/usr/bin/app
autostart=true
autorestart=true
startsecs=5
stdout_logfile=/dev/stdout
stderr_logfile=/dev/stderr

[eventlistener:app_health]
command=supervisor-healthcheck
events=TICK
autostart=true
autostart=false
# Supervisord не имеет встроенного health-check per-service
# Используйте внешний скрипт или watchdog в приложении
```

**SRE-практика:**
- Health-check должен проверять **зависимости в правильном порядке** (БД → кэш → приложение).
- Используйте `start-period` для приложений с долгим стартом (Java, миграции БД).
- `retries=3` с `interval=30s` даёт 90 секунд на восстановление перед marking as unhealthy.
- При `unhealthy` статусе `docker-compose` или оркестратор может перезапустить контейнер.

**Валидация:**
```bash
# Проверка статуса health-check
docker inspect --format='{{.State.Health.Status}}' <container>
# → starting | healthy | unhealthy

# Просмотр логов health-check
docker inspect --format='{{range .State.Health.Log}}{{.Output}}{{end}}' <container>
```

### Стратегии логирования в multi-process контейнерах

В многопроцессной среде возникает проблема перемешивания логов в `stdout`. Для ее решения применяются следующие подходы:

| Стратегия | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Префиксация** | Добавление имени процесса в начало каждой строки (`[nginx] ...`) | Простые логи, legacy-приложения |
| **Structured JSON** | Каждый процесс выводит JSON с полем `component` или `logger` | Production, централизованный сбор |
| **Перенаправление** | Именованные каналы или симлинки (`ln -sf /dev/stdout /var/log/app.log`) | Приложения, пишущие в файлы |
| **s6-overlay logging** | Автоматическое перехватывание вывода сервисов с метаданными | Multi-process с s6-overlay |

### Мониторинг и алертинг multi-process контейнеров

Для SRE-практики критично отслеживать не только статус контейнера, но и состояние каждого внутреннего процесса.

**Ключевые метрики для мониторинга:**

| Метрика | Источник | Порог | Действие |
| :--- | :--- | :--- | :--- |
| **Количество зомби** | `docker exec <c> ps aux \| grep -c -w Z` | > 0 | Проверить PID 1, добавить tini/s6 |
| **Время работы процесса** | `docker exec <c> ps -p <pid> -o etime=` | < 60s после старта | Перезапуск сервиса s6/supervisord |
| **Потребление RAM** | `docker stats --no-stream` | > 80% лимита | Алерт в PagerDuty/Slack |
| **Количество процессов** | `docker exec <c> ps aux \| wc -l` | Рост > 50% | Проверить fork-бомбу |
| **Health-check статус** | `docker inspect --format='{{.State.Health.Status}}'` | unhealthy | Автоперезапуск или escalation |
| **Exit code контейнера** | `docker inspect --format='{{.State.ExitCode}}'` | 137 | OOM или SIGKILL timeout |
| **События Docker** | `docker events --filter event=die` | exit_code != 0 | Запись в SIEM, создание инцидента |

**docker events для multi-process:**
```bash
# Мониторинг событий в реальном времени
docker events --filter event=die --filter event=oom --filter event=kill \
  --format '{{.Time}} {{.Action}} {{.Actor.Attributes.name}} exit_code={{.Actor.Attributes.exitCode}}'
# → 2026-01-15T10:30:00.000000000Z die my-app exit_code=137

# Фильтр по конкретному контейнеру
docker events --filter id=<container_id> --filter event=die
```

**SRE-практика:**
- Все события контейнера должны стекаться в централизованный лог (Loki, ELK, Splunk).
- Настройте алерты на: `exit_code=137` (OOM/SIGKILL), `status=unhealthy` (>2 failures), `zombie_count > 0`.
- Используйте `docker top` для периодического снимка дерева процессов и сравнения с эталоном.

### Cgroups v2 и ограничение ресурсов per-service

В Docker 24+ с cgroups v2 все ограничения (`--cpus`, `--memory`, `--pids-limit`) применяются **ко всему контейнеру**, а не к отдельному сервису внутри него. Это критичное ограничение для multi-process:

**Ограничение:**
```bash
# Всё ограничение применяется ко всем процессам вместе
docker run --cpus=2.0 --memory=1g my-s6-container
# → nginx + php-fpm + redis делят 2 CPU и 1GB RAM
# → php-fpm может заблокировать nginx при нагрузке
```

**Обходные пути:**

1. **Внешний оркестратор (Kubernetes/Nomad):**
   - В Kubernetes используйте `resources.limits` на уровне Pod, а для per-process ограничений — отдельные контейнеры (sidecar pattern).
   - В Nomad используйте `groups` с отдельными `tasks` для каждого процесса.

2. **Cgroups v2 delegation (продвинутый):**
   - Создайте подгруппы cgroups вручную внутри контейнера и переместите процессы с помощью `cgcreate`/`cgset`.
   - Требует `CAP_SYS_ADMIN` или `cgroupns=private`.

3. **Архитектурное разделение:**
   - Если per-process лимиты критичны — разделите функциональный блок на отдельные контейнеры.
   - Используйте Docker Compose `depends_on` + shared volume/socket для связи.

**SRE-рекомендация:** Для production-систем с multi-process контейнерами всегда задавайте общий лимит на контейнер с запасом 30-50% над суммой ожидаемого потребления всех сервисов. Настройте мониторинг per-process через `docker stats` или cgroups metrics.

## Практические сценарии

### Сценарий 1: Использование s6-overlay v3 (Рекомендуемый)

`s6-overlay` — мощная и легковесная система инициализации, оптимизированная для контейнеров. Она поддерживает зависимости между сервисами и автоматическое управление логами.

**Шаг 1: Структура файлов проекта:**
```
.
├── Dockerfile
├── root/
│   └── etc/
│       └── s6-overlay/
│           └── s6-rc.d/
│               ├── user/
│               │   └── contents.d/
│               │       ├── nginx
│               │       ├── php-fpm
│               │       └── redis
│               ├── nginx/
│               │   ├── type
│               │   ├── run
│               │   └── dependencies.d/
│               │       └── php-fpm
│               ├── php-fpm/
│               │   ├── type
│               │   ├── run
│               │   └── dependencies.d/
│               │       └── redis
│               └── redis/
│                   ├── type
│                   └── run
```

**Шаг 2: Dockerfile:**
```dockerfile
FROM alpine:3.24

ARG S6_OVERLAY_VERSION=3.2.3.2
ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz /tmp
ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-x86_64.tar.xz /tmp
RUN tar -C / -Jxpf /tmp/s6-overlay-noarch.tar.xz && \
    tar -C / -Jxpf /tmp/s6-overlay-x86_64.tar.xz

RUN apk add --no-cache nginx php83-fpm redis

# Копирование конфигов и скриптов запуска
COPY root/ /

ENTRYPOINT ["/init"]
```

**Шаг 3: Скрипты запуска сервисов:**

`root/etc/s6-overlay/s6-rc.d/nginx/type`:
```
longrun
```

`root/etc/s6-overlay/s6-rc.d/nginx/run`:
```bash
#!/command/execlineb -P
nginx -g "daemon off;"
```

`root/etc/s6-overlay/s6-rc.d/nginx/dependencies.d/php-fpm`:
```
(empty file — определяет зависимость)
```

`root/etc/s6-overlay/s6-rc.d/php-fpm/type`:
```
longrun
```

`root/etc/s6-overlay/s6-rc.d/php-fpm/run`:
```bash
#!/command/execlineb -P
php-fpm83 --nodaemonize --force-stderr
```

`root/etc/s6-overlay/s6-rc.d/redis/type`:
```
longrun
```

`root/etc/s6-overlay/s6-rc.d/redis/run`:
```bash
#!/command/execlineb -P
redis-server --daemonize no
```

**Преимущество для логов**: s6-overlay автоматически перехватывает вывод сервисов и добавляет к ним метаданные перед отправкой в основной лог контейнера. Каждый процесс получает свой префикс, что упрощает фильтрацию.

**Валидация:**
```bash
# Проверка что все сервисы запущены
docker exec <container> s6-rc -l list | grep -E "nginx|php-fpm|redis"

# Просмотр логов с префиксами
docker logs <container> 2>&1 | grep "nginx"
docker logs <container> 2>&1 | grep "php-fpm"

# Проверка что зомби нет
docker exec <container> ps aux | grep -w Z
```

**Docker Compose:**
```yaml
services:
  web:
    build: .
    init: false  # s6-overlay берет на себя PID 1
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
```

### Сценарий 2: Tini (Для одиночных процессов с дочерними воркерами)

Если контейнер запускает одно приложение, которое порождает дочерние процессы (например, `Node.js` с `cluster`, `Python` с `multiprocessing`, Java с воркерами), достаточно легковесного "жнеца".

**Вариант A: Dockerfile с tini:**
```dockerfile
FROM node:24-alpine

RUN apk add --no-cache tini

# Копирование приложения
COPY package*.json ./
RUN npm ci --only=production
COPY . .

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "server.js"]
```

**Вариант B: Флаг --init (рекомендуется для разработки):**
```bash
docker run --init my-app
# → Docker автоматически вставляет tini как PID 1
```

```yaml
# docker-compose.yml
services:
  app:
    image: my-app
    init: true  # Эквивалент --init
```

**Важно:** `--init` и `init: true` вставляют `tini` (binary ~20KB) из собственного оркестратора Docker. Это не требует установки tini в образ.

**Сравнение tini и dumb-init:**

| Параметр | tini | dumb-init |
| :--- | :--- | :--- |
| **Размер** | ~20 КБ | ~30 КБ |
| **Установка** | `apk add tini` или `--init` | `pip install dumb-init` |
| **Process groups** | Поддержка (`-g`) | Нет |
| **Перезапись сигналов** | Нет | Да (SIGTERM → SIGQUIT) |
| **Рекомендация** | Стандарт для Docker | Legacy, Java-приложения |

**Валидация:**
```bash
# Проверка PID 1
docker exec <container> ps -p 1 -o comm=
# → s6-svscan (s6) или tini

# Проверка что приложение — дочерний процесс
docker exec <container> ps aux
# → PID 1: tini, PID 7: node server.js
```

### Сценарий 3: Sidecar внутри контейнера (Exporter / Agent)

Иногда необходимо запустить вспомогательный процесс, например `prometheus-exporter` для базы данных или агент сбора логов, внутри того же контейнера.

**Пример с использованием shell-скрипта и `exec` (Минималистичный подход):**
```bash
#!/bin/sh
# entrypoint.sh

# Запуск экспортера в фоне
/usr/bin/node_exporter &

# Запуск основного приложения через exec (оно станет PID 1 или дочерним к init)
exec /usr/bin/main_app
```
*Внимание: этот метод требует обязательного использования `--init` при запуске контейнера.*

**Пример с HTTP-exporter и health-check:**
```bash
#!/bin/sh
# entrypoint.sh
set -e

# Запуск exporter в фоне с логированием
/usr/bin/postgres_exporter \
  --web.listen-address=":9187" \
  --web.telemetry-path="/metrics" \
  >> /var/log/exporter.log 2>&1 &

EXPORTER_PID=$!

# Проверка что exporter запустился
sleep 2
if ! kill -0 $EXPORTER_PID 2>/dev/null; then
  echo "ERROR: Exporter failed to start"
  exit 1
fi

# Запуск основного приложения
exec "$@"
```

**Пример с именованным каналом для логов:**
```bash
#!/bin/sh
# entrypoint.sh

# Создание именованного канала для логов exporter
mkfifo /tmp/exporter_log || true

# Перенаправление логов exporter в канал (читается агентом)
cat /tmp/exporter_log &

# Запуск exporter с перенаправлением в канал
/usr/bin/exporter >> /tmp/exporter_log 2>&1 &

# Запуск основного приложения
exec "$@"
```

**Валидация:**
```bash
# Проверка что exporter работает
curl -s http://localhost:9187/metrics | head -5

# Проверка PID дерево
docker exec <container> ps auxf
# → tini (PID 1)
#   ├── main_app (PID 7)
#   └── postgres_exporter (PID 8)
```

### Сценарий 4: Supervisord (Legacy / Enterprise)

Используется в старых проектах или там, где требуется сложная логика перезапуска и управления очередями.

**Полная конфигурация `supervisord.conf`:**
```ini
[supervisord]
nodaemon=true
logfile=/dev/null
logfile_maxbytes=0
pidfile=/tmp/supervisord.pid

[program:app]
command=/usr/bin/app --config /etc/app/config.yaml
autostart=true
autorestart=true
startsecs=5
startretries=3
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
priority=100

[program:worker]
command=/usr/bin/app worker --concurrency=4
autostart=true
autorestart=true
startsecs=10
startretries=5
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
priority=200

[program:exporter]
command=/usr/bin/prometheus_exporter --port 9187
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
priority=300

# Health-check через RPC
[unix_http_server]
file=/tmp/supervisor.sock

[supervisorctl]
serverurl=unix:///tmp/supervisor.sock

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface
```

**Dockerfile:**
```dockerfile
FROM python:3.12-slim

RUN pip install --no-cache-dir supervisor

COPY supervisord.conf /etc/supervisord.conf
COPY app /usr/bin/app
COPY exporter /usr/bin/prometheus_exporter

CMD ["supervisord", "-c", "/etc/supervisord.conf"]
```

**Docker Compose:**
```yaml
services:
  app:
    build: .
    init: false  # supervisord берет на себя PID 1
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

**Валидация:**
```bash
# Проверка статуса всех программ
docker exec <container> supervisorctl status
# → app        RUNNING   pid 7, uptime 0:05:23
# → worker     RUNNING   pid 8, uptime 0:05:23
# → exporter   RUNNING   pid 9, uptime 0:05:23

# Перезапуск конкретной программы
docker exec <container> supervisorctl restart worker

# Просмотр логов
docker exec <container> supervisorctl tail -f app stdout
```

**Важно:** В `supervisord.conf` параметры `stdout_logfile_maxbytes=0` и `stderr_logfile_maxbytes=0` отключают запись в файлы supervisord и направляют вывод напрямую в stdout/stderr контейнера. Это критично для корректной работы `docker logs`.

## Дополнительная информация

### Полная таблица сравнения: Когда что использовать

| Сценарий | Рекомендуемое решение | Почему |
| :--- | :--- | :--- |
| **Одно приложение с воркерами** (Node.js cluster, Python multiprocessing) | `tini` или `--init` | Легковесное решение проблемы PID 1, минимальный overhead |
| **Web + PHP-FPM + Redis** | `s6-overlay v3` | Управление зависимостями, автоматические логи с префиксами |
| **App + Prometheus exporter** | Shell-скрипт с `exec` + `--init` | Минималистичный подход, не требует дополнительных зависимостей |
| **Legacy enterprise** (сложная логика перезапуска) | `supervisord` | Зрелость, богатый CLI и RPC API, документация |
| **App + Sidecar для логов** | Агентный сбор (Fluentd/Vector) | См. **[Агентный сбор логов](./docker_agent_based_logging.md)** |
| **Простая микрослужба** | Tini + Exec Form | Стандарт для Docker, нет лишних зависимостей |

### Поиск и устранение проблем

| Симптом | Диагностика | Решение |
| :--- | :--- | :--- |
| **Контейнер завершается через 10 сек** | `docker inspect --format '{{.State.OOMKilled}}'` | Используйте Exec Form или tini для проброса SIGTERM |
| **Зомби накапливаются** | `docker exec <c> ps aux \| grep -w Z` | Добавьте tini/dumb-init или настройте обработку SIGCHLD |
| **Приложение не реагирует на SIGTERM** | `docker exec <c> kill -0 1` → нет обработчика | Используйте Exec Form + STOPSIGNAL |
| **Сигнал доходит не до того процесса** | `docker exec <c> ps auxf` | Используйте Exec Form вместо Shell Form |
| **s6-overlay не запускает сервисы** | `docker exec <c> s6-rc -l list` | Проверьте наличие файлов `type`, `run` и `contents.d/` |
| **Supervisord: "not running"** | `docker exec <c> supervisorctl status` | Проверьте конфиг и логи: `supervisorctl tail -f <prog> stdout` |
| **Экспортер не отвечает** | `curl localhost:9187/metrics` | Проверьте PID: `ps aux \| grep exporter` |
| **docker logs не показывает логи exporter** | Проверьте перенаправление stdout | Убедитесь что вывод идет в `/dev/stdout`, а не в файл |

### Лучшие практики

1.  **Используйте Exec Form** для `CMD` и `ENTRYPOINT` — это гарантирует, что приложение получит PID 1 и будет корректно обрабатывать сигналы.
2.  **Добавляйте tini** для любого приложения, порождающего дочерние процессы (воркеры, процессы через `fork()`, `subprocess.Popen()`).
3.  **Настройте STOPSIGNAL** в Dockerfile для каждого приложения (Nginx → `SIGQUIT`, PostgreSQL → `SIGINT`, Java → `SIGTERM`).
4.  **Используйте s6-overlay** для multi-process контейнеров с зависимостями между сервисами — это обеспечивает корректный порядок запуска и автоматические логи.
5.  **Не используйте supervisord** для новых проектов — он устарел, тяжелее s6-overlay и не оптимизирован для контейнеров.
6.  **Избегайте systemd** в контейнерах — это анти-паттерн, требующий `CAP_SYS_ADMIN` и увеличивающий поверхность атаки. Подробнее: **[Systemd в Docker](../docker_systemd.md)**.
7.  **Для логирования** используйте structured JSON с полем `component` или `logger` для идентификации процесса в централизованной системе.
8.  **Мониторьте зомби** в production: добавьте health-check, проверяющий `ps aux | grep -c -w Z`.

### Ограничения и известные проблемы

1.  **Dual Logging с s6-overlay**: Логи сервисов s6-overlay идут через stdout/stderr контейнера. Если используется сетевой лог-драйвер (Loki, GELF), Dual Logging может дублировать логи.
2.  **Supervisord не поддерживает process groups**: В отличие от tini, supervisord не передает сигналы группам процессов — только основному процессу каждой программы.
3.  **s6-overlay v2 → v3**: Миграция требует переработки структуры файлов (`/etc/services.d/` → `/etc/s6-overlay/s6-rc.d/`). Официальное руководство: **[s6-overlay Documentation](https://github.com/just-containers/s6-overlay)**.
4.  **Размер образа**: supervisord добавляет ~10-50 МБ (Python), s6-overlay — ~1-3 МБ, tini — ~20 КБ.
5.  **Отладка**: В контейнере с s6-overlay сложно использовать `docker exec sh` для отладки — приоритет сервисов может мешать. Используйте `docker exec -it <c> sh -c "ps aux"` вместо интерактивного shell.
6.  **Зависимости в Docker Compose**: `depends_on` не гарантирует готовность сервиса внутри контейнера — только его запуск. Для real-time проверок используйте health-check.
7.  **Ограничение `--init`**: Флаг `--init` вставляет только tini. Для multi-process с зависимостями (Nginx + PHP-FPM) используйте s6-overlay, а не `--init`.
8.  **Смешение логов в stdout**: При отсутствии префиксации или structured JSON логи разных процессов смешиваются в `docker logs`, что усложняет фильтрацию.
9.  **Ограничение health-check**: Multi-process контейнер требует единого health-check, который проверяет готовность всех сервисов. Изолированные health-check'и отдельных процессов в Docker Compose не покрывают внутренние зависимости.
10. **Ресурсные ограничения (cgroups)**: При использовании supervisord или s6-overlay контроль ресурсов на уровне процессов (`--cpus`, `--memory`) применяется ко всему контейнеру, а не к отдельному сервису. Для per-process ограничений требуется cgroups v2 delegation или внешний оркестратор (Kubernetes, Nomad).
11. **Zombie accumulation under load**: При высоком churn rate процессов (short-lived workers) даже tini может не успеть reap всех зомби, если не настроен `--pidlimit` или не используется `SIGCHLD` handler в приложении.
12. **Log driver interference**: Сетевые лог-драйверы (Loki, GELF) в `blocking` режиме блокируют весь контейнер при проблемах с сетью. Для multi-process это означает каскадный сбой всех сервисов. Используйте `non-blocking` или агентный сбор.

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `docker stop` не завершает контейнер (10 сек → SIGKILL) | Приложение не обрабатывает SIGTERM | Используйте Exec Form + tini |
| Зомби накапливаются, `fork()` возвращает EAGAIN | PID 1 не вызывает `wait()` | Добавьте tini или dumb-init |
| `Permission denied` при запуске tini | tini установлен без executable-прав | `RUN chmod +x /sbin/tini` или используйте `--init` |
| s6-overlay: сервис не запускается | Отсутствует файл `type` или `run` | Проверьте структуру: `type` = "longrun", `run` = executable скрипт |
| Supervisord: "ERROR: couldn't set SIGTERM handler" | Supervisord пытается перехватить сигнал | Добавьте `nodaemon=true` в `[supervisord]` |
| `supervisorctl` не подключается | Unix socket не создан | Проверьте `[unix_http_server]` section в конфиге |
| **s6-overlay: сервис стартует, но падает** | Отсутствует зависимость или неверный `run` скрипт | Проверьте `s6-rc -l list` и `s6-svstat /etc/s6-overlay/s6-rc.d/<service>/` |
| **Контейнер "висит" в `starting`** | Health-check слишком строгий или долгий старт | Увеличьте `start-period` в HEALTHCHECK |
| **Логи duplitцируются (s6-overlay + драйвер)** | Dual Logging + s6-log оба пишут в stdout | Отключите s6-log `printtofile` или используйте `s6-svscan -t0` |
| **Sidecar процесс "съедает" CPU** | Нет лимитов cgroups на контейнер | Задайте `--cpus` и `--memory` на уровне контейнера |
| **Signal не доходит до фонового процесса** | Shell-форма CMD или `&` без `exec` | Используйте exec-form + `tini -g` |
| **Supervisord: процесс в `FATAL`** | Команда не найдена или бинарник поврежден | Проверьте `supervisorctl tail -f <prog> stderr` |
| **s6-overlay: `s6-rc: fatal: unable to open lock file`** | `/run` не смонтирован как tmpfs | Добавьте `--tmpfs /run` при запуске |
| **Zombie в subreaper режиме** | tini запущен не как PID 1 и без `-s` | Используйте `ENTRYPOINT ["/sbin/tini", "-s", "--"]` или убедитесь что tini PID 1 |
| **Контейнер завершается с exit code 143** | Приложение получило SIGTERM и корректно завершилось | Это Нормальное поведение; настройте приложение на корректный обработчик |
| **s6-overlay: сервис не останавливается** | Сервис игнорирует SIGTERM | Добавьте обработчик в приложение или используйте `s6-svc -O` |
| **Health-check всегда `unhealthy`** | Неверный путь или порт, или сервис еще не готов | Увеличьте `start-period`, проверьте команду вручную |

### Безопасность

- **Минимальные привилегии**: Multi-process контейнеры не должны использовать `--privileged`. Для systemd требуется `CAP_SYS_ADMIN`, что является антипаттерном.
- **Сетевая изоляция**: Sidecar-процесс (exporter, агент) не должен иметь доступа к сети контейнера, если это не требуется. Используйте `network_mode: "service:main"` в Docker Compose.
- **Ресурсные ограничения**: Ограничьте CPU и RAM для каждого процесса через cgroups (Docker `--cpus`, `--memory`). Для supervisord используйте `startretries` и `startsecs` для контроля зависаний.
- **Доступ к Docker Socket**: Если sidecar-процессу нужен доступ к Docker API, монтируйте `/var/run/docker.sock` только в read-only режиме (`:ro`). Полный доступ даёт контроль над всеми контейнерами хоста.
- **Пользователь без привилегий**: Запускайте все сервисы от непривилегированного пользователя (`USER 10001`). Избегайте `USER root` даже для init-процесса — s6-overlay поддерживает `s6-setuidgid` для дропа привилегий.
- **Аудит изменений**: Версионируйте `Dockerfile`, скрипты запуска s6-overlay и `supervisord.conf` в Git. Любое изменение в entrypoint-скрипте или структуре сервисов должно проходить code review.
- **Сканирование уязвимостей**: Регулярно сканируйте образы (Trivy, Grype). Multi-process контейнеры часто содержат больше пакетов (nginx + php-fpm + redis), что увеличивает поверхность атаки.

### Производительность и масштабирование

| Параметр | Tini | s6-overlay | Supervisord |
| :--- | :--- | :--- | :--- |
| **Overhead RAM** | ~20 КБ | ~1-5 МБ | ~10-50 МБ |
| **Overhead CPU** | Незначимый | Незначимый | Минимальный |
| **Время старта** | ~1 мс | ~100 мс | ~500 мс |
| **Рекомендация по масштабу** | До 1000+ контейнеров | До 500+ контейнеров | До 100+ контейнеров |

**Детальный разбор:**

**Tini:**
- **RAM**: ~1 MB resident (ядро + обработка SIGCHLD)
- **CPU**: <0.1% на контейнер (только при завершении дочерних процессов)
- **Сценарий масштабирования**: Идеален для высоконагруженных сред (1000+ контейнеров). Минимальный overhead позволяет экономить на ресурсах хоста.

**s6-overlay:**
- **RAM**: ~1-5 MB (s6-svscan + s6-log на каждый сервис)
- **CPU**: Минимальный, кроме моментов ротации логов (s6-log буферизует вывод)
- **Сценарий масштабирования**: До 500 контейнеров на хост. При >500 контейнерах с >3 сервисами каждый — рассмотрите разделение на отдельные контейнеры.

**Supervisord:**
- **RAM**: ~10-50 MB (Python interpreter + watchdog процессы)
- **CPU**: ~1-2% на контейнер (polling статуса программ)
- **Сценарий масштабирования**: До 100 контейнеров. Для legacy-систем, где не планируется масштабирование.

**SRE-рекомендация:** При масштабировании (>200 контейнеров на хост) используйте `tini` для одиночных процессов и `s6-overlay` для multi-process. Supervisord рекомендуется только для legacy-систем.

### Миграция с single-process на multi-process

При переходе от "один процесс на контейнер" к функциональному блоку:

1. **Аудит зависимостей**: Определите процессы с общим жизненным циклом (Nginx + PHP-FPM, App + Worker).
2. **Выбор init-системы**: Для 2-3 процессов — `tini` + shell-скрипт. Для >3 с зависимостями — `s6-overlay`.
3. **Поэтапный rollout**: Сначала запустите sidecar-process в shell-скрипте с `exec`, затем добавьте health-check.
4. **Валидация логов**: Убедитесь что логи корректно разделяются (префиксы s6-overlay или structured JSON).
5. **Мониторинг**: Добавьте алерты на каждый сервис (exit code, zombie count, health status).

### Очистка и откат

**Возврат к Exec Form (без init-системы):**
```dockerfile
# Удалите ENTRYPOINT ["/init"] или ENTRYPOINT ["/sbin/tini", "--"]
# Используйте Exec Form напрямую
CMD ["node", "server.js"]
```

**Удаление s6-overlay из образа:**
```dockerfile
# Удалите слои с s6-overlay
RUN rm -rf /init /etc/s6-overlay /command

# Вернитесь к простому Exec Form
ENTRYPOINT ["/usr/bin/app"]
CMD ["--config", "/etc/app/config.yaml"]
```

**Удаление supervisord:**
```bash
# 1. Удалите пакет supervisord
apk del supervisor  # или pip uninstall supervisor

# 2. Удалите конфиг
rm /etc/supervisord.conf

# 3. Пересоберите образ с простым Exec Form
CMD ["/usr/bin/app"]
```

**Отключение `--init` в Docker Compose:**
```yaml
services:
  app:
    image: my-app
    # init: true  # Удалите или закомментируйте
    command: ["/usr/bin/app"]
```

**Архивация конфигурации перед изменением:**
```bash
# Сохраните текущий Dockerfile и docker-compose.yml
tar -czf multi-process-config-backup-$(date +%Y%m%d).tar.gz Dockerfile docker-compose.yml root/
```

### Ссылки на смежные темы

*   **[Выполнение приложений в контейнере](../Dockerfile/Docker_best_practices/container_execution.md)** — глубокое погружение в PID 1, Exec/Shell Form, STOPSIGNAL, пошаговый разбор `docker stop`.
*   **[Systemd в Docker: анти-паттерн](../docker_systemd.md)** — детальный разбор, почему запуск полноценной ОС в контейнере обычно является ошибкой.
*   **[Настройка лог-драйвера Grafana Loki](./loki_logging_driver_setup.md)** — как настроить централизованный сбор логов для многопроцессных контейнеров.
*   **[Агентный сбор логов Docker](./docker_agent_based_logging.md)** — альтернатива прямой отправке: Vector, Alloy, Fluent Bit, Fluentd.
*   **[Централизованное логирование: Лог-драйверы](./docker_centralized_logging.md)** — сравнение всех лог-драйверов Docker.
*   **[Управление ротацией логов Docker](./docker_log_rotation.md)** — защита диска от переполнения.
*   **[Команда docker logs: справочник](./docker_logs_cli.md)** — чтение логов multi-process контейнера, TTY-специфика.
*   **[Файловые логи приложений](./docker_file_based_logging.md)** — если процессы пишут в файлы, а не stdout.
*   **[Log Injection и безопасность логов](./docker_log_injection_security.md)** — санация вывода процессов перед записью в лог.
*   **[s6-overlay Documentation](https://github.com/just-containers/s6-overlay)** — официальное руководство по настройке сервисов и логов.
