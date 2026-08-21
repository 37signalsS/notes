# Инструкции Dockerfile: HEALTHCHECK и STOPSIGNAL

## Определения

**`HEALTHCHECK`** — инструкция Dockerfile, предназначенная для мониторинга работоспособности приложения внутри контейнера. Она позволяет Docker Engine (или оркестратору, например Docker Swarm) автоматически определять статус контейнера: `starting` (запуск), `healthy` (исправен) или `unhealthy` (неисправен).

**`STOPSIGNAL`** — инструкция, устанавливающая системный сигнал, который Docker будет отправлять основному процессу контейнера (PID 1) для его корректного завершения при выполнении команды `docker stop`.

## Предварительные требования

Для работы с инструкциями `HEALTHCHECK` и `STOPSIGNAL` необходимо:

- **Docker** версии 20.10 или новее (для `--start-interval` требуется Docker 25.0+).
- **BuildKit** — активирован по умолчанию в Docker 23.0+. Для более ранних версий: `DOCKER_BUILDKIT=1`.
- Понимание базовых концепций: **[CMD и ENTRYPOINT](./runtime_execution.md)** (exec-form vs shell-form, PID 1), **[WORKDIR](./working_context.md)**.
- Утилита `curl` или `wget` в образе для HTTP-проверок здоровья (или альтернативный инструмент проверки).
- Базовое понимание Linux-сигналов: что такое SIGTERM, SIGKILL, PID 1 и зачем нужна обработка сигналов.

## Основные концепции

### Проверка здоровья: HEALTHCHECK

Инструкция встраивает логику проверки готовности приложения непосредственно в образ, обеспечивая самодокументируемость и автоматизацию управления жизненным циклом.

#### Синтаксис

```dockerfile
# Выполнение команды (exec-форма, рекомендуется для скорости и безопасности)
HEALTHCHECK [OPTIONS] CMD ["executable", "arg1", "arg2"]

# Выполнение через оболочку (shell-форма, позволяет использовать пайпы и переменные)
HEALTHCHECK [OPTIONS] CMD command

# Отключение проверок, унаследованных от базового образа
HEALTHCHECK NONE
```

#### Параметры конфигурации (Options)

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| `--interval` | Время между плановыми проверками | `30s` |
| `--timeout` | Максимальное время ожидания ответа команды | `30s` |
| `--start-period` | Льготный период для старта приложения (ошибки не засчитываются) | `0s` |
| `--start-interval` | Интервал проверок **только** во время старта (Docker 25.0+) | `5s` |
| `--retries` | Количество неудач подряд до смены статуса на `unhealthy` | `3` |

#### Коды возврата (Exit Codes)

Процесс проверки должен возвращать строго определенные коды:
- `0`: **Успех** (healthy) — контейнер готов к работе.
- `1`: **Ошибка** (unhealthy) — контейнер неисправен и может быть перезапущен оркестратором.
- `2`: **Зарезервировано** — не используйте этот код в своих скриптах.

#### Наследование и отключение

1. **Наследование:** Инструкция `HEALTHCHECK` наследуется от базового образа (`FROM`).
2. **Переопределение:** Любая новая инструкция `HEALTHCHECK` в Dockerfile полностью заменяет старую.
3. **Отключение (`NONE`):** Чтобы полностью убрать мониторинг, заданный в родительском образе, используйте `HEALTHCHECK NONE`. Это критично при миграции в Kubernetes, где используются нативные пробы.

### Сигнал остановки: STOPSIGNAL

Обеспечивает **Graceful Shutdown** (корректное завершение), позволяя приложению закрыть соединения, сохранить данные и освободить ресурсы.

#### Синтаксис и значения

```dockerfile
STOPSIGNAL SIGTERM
```

**Рекомендация:** Всегда используйте **имена сигналов** (`SIGTERM`, `SIGQUIT`), а не числовые значения (15, 3). Числовые значения могут различаться в зависимости от архитектуры процессора (x86 vs MIPS/Alpha), что нарушает портативность образа.

#### Механизм работы и проблема PID 1

1. При `docker stop` Docker отправляет сигнал из `STOPSIGNAL` (по умолчанию `SIGTERM`) процессу с **PID 1**.
2. **Проблема PID 1:** В Linux процесс с PID 1 не имеет обработчиков сигналов по умолчанию. Если приложение не зарегистрировало обработчик явно, оно **игнорирует** сигнал.
3. **Решение:** Использование систем инициализации (**tini**, **dumb-init**). Они запускаются как PID 1, корректно пробрасывают сигналы дочерним процессам и активируют стандартное поведение ОС для тех, кто не умеет обрабатывать сигналы.

#### Таблица сигналов

| Сигнал | Назначение | Типичное применение |
| :--- | :--- | :--- |
| `SIGTERM` (15) | Просьба завершиться | Стандарт по умолчанию |
| `SIGQUIT` (3) | Быстрый выход | Nginx, JVM |
| `SIGINT` (2) | Прерывание | PostgreSQL (Fast Shutdown) |
| `SIGWINCH` (28) | Изменение окна | Sidekiq, Apache (Graceful stop) |
| `SIGUSR1` (10) | Пользовательский | Лог-ротация, перечитывание конфига |

#### Механизм docker stop: пошагово

1. Docker отправляет SIGTERM (или сигнал из `STOPSIGNAL`) процессу PID 1.
2. Docker ожидает **stop timeout** (по умолчанию 10 секунд для Linux-контейнеров).
3. Если процесс не завершился — Docker отправляет SIGKILL (сигнал 9), который **невозможно перехватить**.
4. Контейнер завершается с кодом 137 (128 + 9 = SIGKILL).

Настройка таймаута:

```bash
# Ожидание 30 секунд перед SIGKILL
docker stop --timeout 30 my-container

# В docker-compose.yml
services:
  app:
    stop_grace_period: 30s
```

## Практические сценарии

### Сценарий 1: Быстрое обнаружение готовности (Docker 25.0+)

Использование `--start-interval` позволяет Docker зафиксировать переход в `healthy` за считанные секунды после старта, не ожидая основного длинного интервала.

```dockerfile
# Проверяем каждые 2 секунды во время старта, затем раз в 5 минут
HEALTHCHECK --interval=5m --timeout=3s --start-period=30s --start-interval=2s \
  CMD curl -f http://localhost:8080/health || exit 1
```

**Результат:** Приложение переходит в `healthy` через 2-4 секунды после готовности, а не через 30 секунд (станартный интервал).

### Сценарий 2: Веб-сервер Nginx (Graceful Exit)

Nginx предпочитает `SIGQUIT` для завершения работы, так как это позволяет ему закрыть активные соединения перед выходом.

```dockerfile
FROM nginx:alpine
STOPSIGNAL SIGQUIT
# Проверка через wget (spider mode - не скачивает контент)
HEALTHCHECK --interval=30s --timeout=3s \
  CMD wget --no-verbose --tries=1 --spider http://localhost/ || exit 1
```

**Важно:** Если использовать `SIGTERM` (по умолчанию), Nginx завершится немедленно, разорвав все активные соединения.

### Сценарий 3: Интеграция с tini (PID 1 Reaper)

Гарантирует, что сигналы дойдут до приложения, даже если оно не умеет их обрабатывать.

```dockerfile
FROM node:22-alpine
RUN apk add --no-cache tini
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "app.js"]
# Сигнал SIGTERM будет проброшен tini к node
STOPSIGNAL SIGTERM
```

**Альтернатива без установки tini:** Docker предоставляет флаг `--init` при запуске контейнера:

```bash
docker run --init myapp:1.0.0
```

### Сценарий 4: База данных PostgreSQL (Fast Shutdown)

По умолчанию Postgres выполняет "Smart Shutdown" (ждет завершения всех сессий), что часто приводит к таймауту Docker и жесткому `SIGKILL`. `SIGINT` инициирует "Fast Shutdown".

```dockerfile
FROM postgres:16-alpine
STOPSIGNAL SIGINT
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s \
  CMD pg_isready -U postgres || exit 1
```

### Сценарий 5: Фоновый воркер без HTTP-эндпоинта

Воркеры не обрабатывают HTTP-запросы, поэтому проверка здоровья должна основываться на проверке процесса или файле-сердцебиении:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY worker.py .
COPY healthcheck.sh /usr/local/bin/healthcheck.sh
RUN chmod +x /usr/local/bin/healthcheck.sh

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD /usr/local/bin/healthcheck.sh

CMD ["python", "worker.py"]
```

Скрипт проверки (`healthcheck.sh`):

```bash
#!/bin/bash
# Проверка по PID-файлу
if [ -f /tmp/worker.pid ]; then
    PID=$(cat /tmp/worker.pid)
    if kill -0 "$PID" 2>/dev/null; then
        # Проверка актуальности heartbeat-файла (не старше 60 секунд)
        if [ -f /tmp/worker-heartbeat ]; then
            AGE=$(( $(date +%s) - $(stat -c %Y /tmp/worker-heartbeat) ))
            if [ "$AGE" -lt 60 ]; then
                exit 0
            fi
        fi
    fi
fi
exit 1
```

### Сценарий 6: Stateful-сервис (Redis)

Проверка должна подтверждать не только работоспособность процесса, но и способность чтения/записи:

```dockerfile
FROM redis:7-alpine
HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
  CMD redis-cli ping | grep -q PONG && redis-cli set healthcheck_test 1 EX 5 > /dev/null || exit 1
```

### Сценарий 7: RabbitMQ с кастомной проверкой

RabbitMQ предоставляет встроенную утилиту диагностики:

```dockerfile
FROM rabbitmq:3-management-alpine
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD rabbitmq-diagnostics -q check_running && rabbitmq-diagnostics -q check_local_alarms || exit 1
```

### Сценарий 8: Java/Spring Boot с Actuator

```dockerfile
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY target/app.jar .
# start-period увеличен для JVM (долгая инициализация)
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD curl -f http://localhost:8080/actuator/health || exit 1
CMD ["java", "-XX:MaxRAMPercentage=80.0", "-jar", "app.jar"]
```

### Сценарий 9: Сигнал в entrypoint-скрипте (exec-форма)

Когда entrypoint — shell-скрипт, который запускает основной процесс:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY entrypoint.sh app.py ./
RUN chmod +x entrypoint.sh
STOPSIGNAL SIGTERM
ENTRYPOINT ["./entrypoint.sh"]
CMD ["python", "app.py"]
```

Скрипт `entrypoint.sh`:

```bash
#!/bin/bash
# Предварительная настройка
echo "Setting up environment..."
export DATABASE_URL="${DATABASE_URL:-postgres://localhost/mydb}"

# Ключевой момент: exec заменяет shell процесс приложением
# Приложение становится PID 1 и получает сигналы напрямую
exec "$@"
```

**Важно:** Без `exec "$@"` shell останется PID 1 и будет перехватывать SIGTERM, не пробрасывая его к дочернему процессу.

### Сценарий 10: Настраиваемый health-скрипт с градациями

Для приложений с несколькими компонентами проверка может возвращать разные коды:

```dockerfile
FROM python:3.12-slim
COPY healthcheck.py /usr/local/bin/healthcheck.py
RUN chmod +x /usr/local/bin/healthcheck.py
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD python /usr/local/bin/healthcheck.py
```

```python
#!/usr/bin/env python3
import sys
import urllib.request

checks = {
    "app": "http://localhost:8080/health",
    "cache": "http://localhost:6379",  # TCP check placeholder
}

critical_failed = False

for name, url in checks.items():
    try:
        if url.startswith("http"):
            urllib.request.urlopen(url, timeout=3)
    except Exception:
        if name == "app":
            critical_failed = True
        print(f"WARN: {name} check failed", file=sys.stderr)

if critical_failed:
    sys.exit(1)  # unhealthy

sys.exit(0)  # healthy (даже если cache недоступен)
```

## Типичные ошибки и их решение

### Ошибка 1: Контейнер бесконечно перезапускается (restart loop)

**Причина:** Слишком короткий `--start-period` для медленно стартующего приложения (Java, большие ML-модели).

**Диагностика:**
```bash
docker inspect --format='{{json .State.Health}}' <container_id> | jq
# Смотрите лог-хроницию: если failures идут сразу после создания -- start-period слишком короткий
```

**Решение:** Увеличьте `--start-period` до 1.5x от наблюдаемого максимального времени старта:

```dockerfile
# Было (приложение стартует за 45 секунд):
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s ...

# Стало:
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s ...
```

### Ошибка 2: Контейнер помечен unhealthy, но приложение работает

**Причина:** Проверка здоровья обращается к внешним сервисам (БД, API), которые временно недоступны.

**Решение:** Проверяйте только локальную работоспособность. Внешние зависимости — тема для `readinessProbe` (Kubernetes), не для `HEALTHCHECK`:

```dockerfile
# ПЛОХО: зависит от внешней БД
HEALTHCHECK CMD curl -f http://localhost:8080/api/users/count || exit 1

# ХОРОШО: проверяет только локальный процесс
HEALTHCHECK CMD curl -f http://localhost:8080/health || exit 1
```

### Ошибка 3: Сигнал не доходит до приложения

**Причина:** Используется shell-form CMD/ENTRYPOINT — оболочка становится PID 1 и не пробрасывает сигналы.

```dockerfile
# ПЛОХО: /bin/sh -c становится PID 1
CMD node server.js

# ХОРОШО: node становится PID 1
CMD ["node", "server.js"]
```

Если shell-скрипт обязателен — используйте `exec`:

```bash
#!/bin/bash
# ... настройка ...
exec node server.js  # заменяет shell приложением
```

### Ошибка 4: Контейнер завершается с кодом 137

**Причина:** Docker отправил SIGKILL — приложение не успело завершиться за отведенное время.

**Диагностика:**
```bash
docker inspect --format='{{.State.ExitCode}}' <container_id>
# 137 = 128 + 9 (SIGKILL)
# Проверьте stop_grace_period
docker inspect --format='{{.HostConfig.StopTimeout}}' <container_id>
```

**Решение:** Увеличьте таймаут:

```bash
docker stop --timeout 60 my-container
# Или в docker-compose.yml:
services:
  app:
    stop_grace_period: 60s
```

### Ошибка 5: Healthcheck тратит слишком много ресурсов

**Причина:** Тяжелые проверки (запросы к БД,大型 скрипты) на каждом интервале нагружают систему.

**Решение:**
- Используйте `wget --spider` вместо полного скачивания.
- Для TCP-проверок используйте `timeout 2 bash -c 'cat < /dev/null > /dev/tcp/localhost/3306'`.
- Увеличьте интервал для фоновых воркеров: `--interval=60s`.

### Ошибка 6: HEALTHCHECK NONE не отключает проверку

**Причина:** `HEALTHCHECK NONE` отключает только наследуемую проверку. Если в текущем Dockerfile есть другая инструкция `HEALTHCHECK`, она будет выполняться.

**Решение:** Убедитесь, что `HEALTHCHECK NONE` — единственная инструкция HEALTHCHECK в Dockerfile (или расположите её после всех других).

### Ошибка 7: В Kubernetes HEALTHCHECK не работает

**Причина:** Kubernetes игнорирует `HEALTHCHECK` из Dockerfile, если определены нативные пробы (`livenessProbe`, `readinessProbe`, `startupProbe`).

**Решение:** В Kubernetes используйте кастомные пробы в манифесте. `HEALTHCHECK` в Dockerfile полезен как fallback для локальной разработки и не-Kubernetes окружений.

## Лучшие практики

### Выбор интервала проверки

| Интервал | Время обнаружения | Нагрузка | Применение |
| :--- | :--- | :--- | :--- |
| `5s` | Быстрое (15-20с) | Высокая CPU/сеть | Критические сервисы (платежи, авторизация) |
| `30s` | Среднее (90-120с) | Умеренная | Стандартные приложения (API, веб) |
| `60s` | Медленное (180-240с) | Низкая | Фоновые воркеры, batch-задачи |

### Настройка таймаута

Устанавливайте `--timeout` на основе p99 времени ответа приложения плюс запас:

```dockerfile
# API с p99 = 500ms
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1
```

**Рекомендация:** Не превышайте 5 секунд — длинные таймауты маскируют деградацию производительности и вызывают каскадные сбои.

### Настройка start-period

Рассчитывайте `--start-period` на основе:
- Времени старта приложения (boot time)
- Времени выполнения миграций БД
- Времени прогрева кэша
- Времени подключения к внешним сервисам

```dockerfile
# Java: наблюдаемое время старта ~45 секунд, запас 1.5x
HEALTHCHECK --start-period=90s --interval=30s --timeout=5s --retries=3 ...
```

### Порядок инструкций в Dockerfile

```dockerfile
FROM node:22-alpine
WORKDIR /app

# 1. Сначала зависимости (кэшируются)
COPY package.json package-lock.json ./
RUN npm ci --production

# 2. Затем исходный код
COPY src/ ./src/

# 3. Настройка прав (exec-form для PID 1)
EXPOSE 3000

# 4. HEALTHCHECK — после всех инструкций, до CMD
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3000/health || exit 1

CMD ["node", "src/server.js"]
```

### Сохранение логов healthcheck

Вывод последней проверки доступен через `docker inspect`:

```bash
# Полный JSON со всеми проверками
docker inspect --format='{{json .State.Health}}' <container_id> | jq

# Только статус
docker inspect --format='{{.State.Health.Status}}' <container_id>

# Последний лог (stdout/stderr команды проверки)
docker inspect --format='{{range .State.Health.Log}}{{.Output}}{{end}}' <container_id>
```

### Отключение healthcheck при отладке

```bash
# При запуске контейнера
docker run --no-healthcheck myapp:1.0

# В docker-compose.yml
services:
  app:
    image: myapp:1.0
    healthcheck:
      disable: true
```

## Граничные случаи и ограничения

### Зависимость от утилит в образе

Если в образе нет `curl` или `wget`, healthcheck не сработает. Варианты:

1. **Установите минималистичную утилиту** (для Alpine):
   ```dockerfile
   RUN apk add --no-cache wget
   ```
2. **Используйте встроенные инструменты** приложения:
   ```dockerfile
   # PostgreSQL
   HEALTHCHECK CMD pg_isready -U postgres || exit 1

   # Redis
   HEALTHCHECK CMD redis-cli ping || exit 1

   # RabbitMQ
   HEALTHCHECK CMD rabbitmq-diagnostics -q check_running || exit 1
   ```
3. **Кастомный скрипт** на Python/Bash (см. Сценарий 5).

### Пустой healthcheck и edge-case с CMD

Если healthcheck-команда всегда возвращает 0 (успех), контейнер будет помечен `healthy` даже при полной неработоспособности приложения:

```dockerfile
# ПЛОХО: проверяет только существование процесса, а не работоспособность
HEALTHCHECK CMD pgrep -x node || exit 1

# ХОРОШО: проверяет способность обрабатывать запросы
HEALTHCHECK CMD curl -f http://localhost:3000/health || exit 1
```

### HEALTHCHECK NONE и multi-stage builds

`HEALTHCHECK NONE` действует только на текущую стадию. Если на финальной стадии нет `HEALTHCHECK NONE`, а базовый образ (предыдущая стадия) имел `HEALTHCHECK`, проверка будет унаследована:

```dockerfile
FROM node:22-alpine AS builder
# ... сборка ...

FROM node:22-alpine
COPY --from=builder /app/dist /app/dist
# Если базовый образ node:22-alpine имеет HEALTHCHECK — он будет унаследован
# Чтобы отключить:
HEALTHCHECK NONE
```

### Взаимодействие с Docker Compose depends_on

В Compose можно дождаться `healthy` статуса зависимого сервиса:

```yaml
services:
  api:
    build: .
    depends_on:
      db:
        condition: service_healthy
  db:
    image: postgres:16-alpine
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 3s
      retries: 5
```

### Взаимодействие с оркестраторами

| Платформа | Как используется HEALTHCHECK | Рекомендация |
| :--- | :--- | :--- |
| **Docker Standalone** | Определяет статус в `docker ps` | Используйте как есть |
| **Docker Swarm** | Автоматический перезапуск unhealthy-контейнеров | Опционально, но рекомендуется |
| **Kubernetes** | **Игнорируется** если есть нативные пробы | Определите `livenessProbe`/`readinessProbe` |
| **Docker Compose** | Используется с `depends_on: condition: service_healthy` | Рекомендуется для зависимостей |
| **AWS ECS** | Используется для placement и health checks | Рекомендуется |

### Проверка в CI/CD

В пайплайнах проверяйте, что образ имеет HEALTHCHECK:

```bash
# Проверка наличия HEALTHCHECK в образе
docker inspect --format='{{json .Config.Healthcheck}}' myapp:latest | jq
```

Отсутствие `HEALTHCHECK` или `null` означает, что проверка здоровья не настроена.

## Дополнительная информация

### Рекомендации
1. **Легковесность:** Проверка должна быть быстрой и не потреблять много ресурсов (избегайте тяжелых скриптов).
2. **Локальность:** Направляйте запросы на `127.0.0.1` или `localhost`.
3. **Безопасность:** Запускайте проверки с минимальными привилегиями.
4. **Важно для Kubernetes:** K8s полностью игнорирует `HEALTHCHECK` из Dockerfile. Используйте `liveness/readiness/startupProbe` в манифестах.

**См. также:**
- **[Autoheal в Docker](../../Docker_troubleshooting/docker_autoheal.md)** — автоматический перезапуск unhealthy-контейнеров.
- **[Директивы Docker Compose](../../Docker_compose/docker_compose_directives.md)** — переопределение healthcheck в YAML (включая `disable: true`).
- **[Проблема PID 1 и сигналы](./runtime_execution.md#решение-проблемы-pid-1)** — детали работы систем инициализации.
- **[Healthchecks в Podman](../../Podman/podman_healthchecks.md)** — отличия в реализации.
- **[Пробы в Kubernetes](../../Kubernetes/Base/probes.md)** — мониторинг в K8s.
