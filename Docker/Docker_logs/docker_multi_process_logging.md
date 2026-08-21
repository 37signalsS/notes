# Паттерн "Multi-Process" в Docker

## Определения

**Паттерн "Multi-Process"** — архитектурный подход, при котором внутри одного Docker-контейнера запускается несколько тесно связанных процессов, образующих единый функциональный блок (микрослужбу). Примером может служить связка `Nginx + PHP-FPM` или `App + Sidecar-агент`.

**Проблема PID 1** — техническая особенность ядра Linux, при которой процесс с идентификатором 1 (init) имеет особые обязанности:
1.  **Reaping (Утилизация зомби)**: PID 1 обязан "усыновлять" процессы-сироты и считывать их код завершения, предотвращая появление "зомби".
2.  **Signal Forwarding (Проброс сигналов)**: Docker отправляет сигналы остановки (`SIGTERM`) только процессу PID 1. Если это обычное приложение или shell-скрипт, он может не передать сигнал дочерним процессам, что приведет к их принудительному завершению (`SIGKILL`) по таймауту.

**Init-система для контейнеров** — легковесный менеджер процессов, который берет на себя роль PID 1 в контейнере: корректно пробрасывает сигналы дочерним процессам и очищает зомби. Основные реализации: `tini`, `dumb-init`, `s6-overlay`.

**Zombie Process (Процесс-зомби)** — завершенный процесс, который уже не выполняется, но запись о нем остается в таблице процессов, так как родитель (PID 1) не вызвал `wait()` для сбора статуса. Зомби не потребляют ресурсы, но занимают запись в таблице процессов. При переполнении таблицы (~32768 записей) ядро отказывает в создании новых процессов.

## Предпосылки

- **Docker Engine** версии 20.10 или выше (для Dual Logging и стабильной работы init-систем)
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
# → Проблема:看到 <defunct> строки
```

## Базовые концепции

### Философия "Функционального блока" (2026)

Классическая догма "один процесс на контейнер" в современной практике заменена на **"один функциональный блок на контейнер"**. Это допустимо при соблюдении условий:
*   Процессы имеют одинаковый жизненный цикл (если падает один, контейнер должен быть перезапущен).
*   Процессы тесно связаны (обмен через Unix-сокеты, разделяемая память или `localhost`).
*   Используется специализированная система инициализации (Init system).

**Когда Multi-Process оправдан:**
*   **App + Sidecar**: приложение + агент мониторинга/метрик (Prometheus exporter, Fluentd-агент)
*   **Web + Worker**: Nginx + PHP-FPM, App + Celery worker (общий жизненный цикл)
*   **App + Миграции**: приложение + скрипт миграции БД (одноразовый запуск при старте)

**Когда Multi-Process НЕ оправдан:**
*   Процессы имеют разные жизненные циклы (БД + приложение)
*   Процессы не связаны между собой
*   Нет средств инициализации (tini/s6) — риск накопления зомби

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

### Стратегии логирования в multi-process контейнерах

В многопроцессной среде возникает проблема перемешивания логов в `stdout`. Для ее решения применяются следующие подходы:

| Стратегия | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Префиксация** | Добавление имени процесса в начало каждой строки (`[nginx] ...`) | Простые логи, legacy-приложения |
| **Structured JSON** | Каждый процесс выводит JSON с полем `component` или `logger` | Production, централизованный сбор |
| **Перенаправление** | Именованные каналы или симлинки (`ln -sf /dev/stdout /var/log/app.log`) | Приложения, пишущие в файлы |
| **s6-overlay logging** | Автоматическое перехватывание вывода сервисов с метаданными | Multi-process с s6-overlay |

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
FROM alpine:3.20

ARG S6_OVERLAY_VERSION=3.2.0.2
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
FROM node:22-alpine

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
| **Legacy enterprise** (сложная логика перезапуска) | `supervisord` | Зрелость,丰富的 CLI и RPC API, документация |
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

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `docker stop` не завершает контейнер (10 сек → SIGKILL) | Приложение не обрабатывает SIGTERM | Используйте Exec Form + tini |
| Зомби накапливаются, `fork()` возвращает EAGAIN | PID 1 не вызывает `wait()` | Добавьте tini или dumb-init |
| `Permission denied` при запуске tini | tini установлен без executable-прав | `RUN chmod +x /sbin/tini` или используйте `--init` |
| s6-overlay: сервис не запускается | Отсутствует файл `type` или `run` | Проверьте структуру: `type` = "longrun", `run` = executable скрипт |
| Supervisord: "ERROR: couldn't set SIGTERM handler" | Supervisord пытается перехватить сигнал | Добавьте `nodaemon=true` в `[supervisord]` |
| `supervisorctl` не подключается | Unix socket не создан | Проверьте `[unix_http_server]` section в конфиге |

### Безопасность

- **Минимальные привилегии**: Multi-process контейнеры не должны использовать `--privileged`. Для systemd требуется `CAP_SYS_ADMIN`, что является антипаттерном.
- **Сетевая изоляция**: Sidecar-процесс (exporter, агент) не должен иметь доступа к сети контейнера, если это не требуется. Используйте `network_mode: "service:main"` в Docker Compose.
- **Ресурсные ограничения**: Ограничьте CPU и RAM для каждого процесса через cgroups (Docker `--cpus`, `--memory`). Для supervisord используйте `startretries` и `startsecs` для контроля зависаний.

### Производительность и масштабирование

| Параметр | Tini | s6-overlay | Supervisord |
| :--- | :--- | :--- | :--- |
| **Overhead RAM** | ~20 КБ | ~1-5 МБ | ~10-50 МБ |
| **Overhead CPU** | Незначимый | Незначимый | Минимальный |
| **Время старта** | ~1 мс | ~100 мс | ~500 мс |
| **Рекомендация по масштабу** | До 1000+ контейнеров | До 500+ контейнеров | До 100+ контейнеров |

**Рекомендация:** При масштабировании (>200 контейнеров на хост) используйте `tini` для одиночных процессов и `s6-overlay` для multi-process. Supervisord рекомендуется только для legacy-систем.

### Ссылки на смежные темы

*   **[Выполнение приложений в контейнере](../Dockerfile/Docker_best_practices/container_execution.md)** — глубокое погружение в PID 1, Exec/Shell Form, STOPSIGNAL, пошаговый разбор `docker stop`.
*   **[Systemd в Docker: анти-паттерн](../docker_systemd.md)** — детальный разбор, почему запуск полноценной ОС в контейнере обычно является ошибкой.
*   **[Настройка лог-драйвера Grafana Loki](./loki_logging_driver_setup.md)** — как настроить централизованный сбор логов для многопроцессных контейнеров.
*   **[Агентный сбор логов Docker](./docker_agent_based_logging.md)** — альтернатива прямой отправке: Vector, Alloy, Fluentd.
*   **[Централизованное логирование: Лог-драйверы](./docker_centralized_logging.md)** — сравнение всех лог-драйверов Docker.
*   **[Управление ротацией логов Docker](./docker_log_rotation.md)** — защита диска от переполнения.
*   **[s6-overlay Documentation](https://github.com/just-containers/s6-overlay)** — официальное руководство по настройке сервисов и логов.
