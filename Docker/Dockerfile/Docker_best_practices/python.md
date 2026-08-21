# Dockerfile: Лучшие практики для Python

## Определения

- **Wheels (*.whl):** Предварительно скомпилированный формат дистрибуции пакетов. Позволяет избежать компиляции на этапе установки, что критично для библиотек с нативными расширениями (C/C++, Rust).
- **uv:** Сверхбыстрый менеджер пакетов и установщик Python (написан на Rust). К 2026 году является стандартом для замены `pip`, `poetry` и `venv` в Docker-контейнерах благодаря экстремальной скорости и встроенному кэшированию.
- **Байт-код (.pyc):** Скомпилированная форма исходного кода Python. В контейнерах часто отключается (`PYTHONDONTWRITEBYTECODE=1`) для уменьшения размера образа.
- **Distroless (Python):** Минималистичные образы (например, от Google), содержащие только интерпретатор и необходимые системные библиотеки, без пакетных менеджеров и shell.
- **Py-Spy:** Инструмент для профилирования работающих Python-приложений без изменения их кода и без остановки процесса (используется как sidecar).
- **SBOM (Software Bill of Materials):** Декларативный список всех компонентов и зависимостей, входящих в состав образа, необходимый для аудита безопасности и CVE-мониторинга.
- **Site-packages:** Директория, в которую устанавливаются сторонние библиотеки Python.
- **tini:** Легковесный init-процесс (PID 1) для контейнеров. Решает проблему обработки сигналов и удаления зомби-процессов. Для Python-приложений с multiprocessing является обязательным.
- **pip-audit:** Инструмент для сканирования зависимостей Python на известные CVE. Работает с `requirements.txt`, `pyproject.toml` и установленными пакетами.

## Базовые концепции

### Специфика интерпретатора в контейнерах (2026)

Python 3.14+ принес значительные улучшения в производительности и работе с памятью в контейнерах:
*   **Тип:** Интерпретируемый (но с поддержкой JIT в современных версиях).
*   **Артефакт:** Исходный код (`.py`) + зависимости в `site-packages`.
*   **Multi-stage:** Обязателен для системных зависимостей сборки (`gcc`, `g++`, `rustc`). Инструменты сборки должны оставаться в `builder`-слое.
*   **Кэширование BuildKit:** Использование `--mount=type=cache,target=/root/.cache/uv` является обязательным стандартом для ускорения CI/CD.

### Выбор базового образа (Сравнение 2026)

| Образ | Рекомендация | Техническое обоснование |
| :--- | :--- | :--- |
| **`python:3.14-slim`** | **Рекомендуется** | Баланс между размером и совместимостью (`glibc`). Большинство бинарных `wheels` работают из коробки. |
| **`python:3.14-alpine`** | С осторожностью | Минимальный размер, но требует компиляции многих пакетов из-за `musl`, что замедляет сборку в разы. |
| **`Wolfi / Chainguard`** | **Для High-Security** | 0 CVE образы, ориентированные на безопасность. Используют `glibc`. |
| **`python:3.14` (Full)** | Не рекомендуется | Огромный размер (>900МБ), содержит сотни лишних пакетов. |

### Сравнение менеджеров пакетов для Docker (2026)

| Характеристика | uv | pip | poetry |
| :--- | :--- | :--- | :--- |
| **Скорость установки** | Экстремальная (Rust) | Базовая | Средняя |
| **Кэширование** | Встроенное, автоматическое | Требует `--cache-dir` и монтирования | Встроенное |
| **Lock-файл** | `uv.lock` ( детерминированный) | Нет нативного | `poetry.lock` |
| **Multi-stage** | Идеально (`uv sync --no-dev`) | Требует `pip wheel` | Сложнее |
| **Размер образа builder** | ~15 МБ (бинарник) | ~50 МБ (pip + setuptools) | ~100 МБ (poetry + зависимости) |
| **Workspace (монорепозитории)** | Нативная поддержка | Нет | Ограниченная |
| **Рекомендация 2026** | **Стандарт** | Legacy | Для специфичных случаев |

### Тюнинг рантайма и ресурсов

*   **Логирование:** `PYTHONUNBUFFERED=1` гарантирует немедленный вывод логов в `stdout`/`stderr` без буферизации.
*   **Память (cgroups v2):** Python 3.14+ лучше понимает лимиты контейнера, но для тяжелых ML/Data-приложений рекомендуется ограничивать аллокатор через `MALLOC_ARENA_MAX=2`.
*   **Оптимизация:** `PYTHONOPTIMIZE=1` удаляет инструкции `assert` и документацию (`__doc__`), что немного ускоряет работу и экономит память.

**Практическое применение MALLOC_ARENA_MAX:**

```dockerfile
# Для ML-приложений (TensorFlow, PyTorch) с высоким потреблением памяти
ENV MALLOC_ARENA_MAX=2 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
```

Значение `2` рекомендуется для контейнеров, так как увеличение этого параметра повышает потребление памяти на управление аллокатором. Для обычных веб-приложений этот параметр можно не задавать — Python 3.14+ корректно работает с дефолтными настройками `malloc`.

### Обработка сигналов и PID 1

Python не обрабатывает системные сигналы корректно при запуске напрямую как PID 1. Проблемы:
*   `SIGTERM` не достигает приложения (контейнер завершается через `SIGKILL` после таймаута).
*   Зомби-процессы накапливаются (не.Charting через `wait()`).

**Решения:**

1.  **tini (рекомендуется):** Легковесный init-процесс.
2.  **`--init` флаг:** Docker автоматически добавляет tini.
3.  **Docker Compose `init: true`:** Аналог `--init` для Compose.

```bash
# Запуск с tini через --init
docker run --init my-python-app:latest

# Проверка PID 1
docker exec <container> ps -p 1 -o pid,comm,args
# → PID   COMMAND  COMMAND
#   1   tini     /sbin/tini -- python app.py
```

**Docker Compose:**
```yaml
services:
  app:
    image: my-python-app:latest
    init: true  # Автоматически добавляет tini
```

### Alpine musl vs glibc: подводные камни для Python

Alpine использует `musl libc` вместо `glibc`. Это вызывает проблемы с бинарными `wheels`:

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `pip install` компилирует из исходников | Нет pre-built wheels для musl | Использовать `slim` (Debian) или `manylinux` wheels |
| Ошибка `libc.so.6: version 'GLIBC_2.28' not found` | Бинарник скомпилирован под glibc | `apk add --no-cache gcompat` или перейти на slim |
| Долгая сборка (numpy, pandas, scipy) | Компиляция из C/C++ исходников | Кэширование wheels или Wolfi |
| Несовместимость расширений | Разные ABI между musl и glibc | Построить собственные wheels в Alpine builder |

**Паттерн: компиляция в Alpine с установкой в Alpine (если нужен минимальный образ):**

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.14-alpine AS builder

# Временные зависимости для компиляции
RUN apk add --no-cache --virtual .build-deps \
    build-base \
    libffi-dev \
    postgresql-dev

WORKDIR /app
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# Удаляем виртуальные зависимости (компиляторы)
RUN apk del .build-deps

# --- Финальный этап ---
FROM python:3.14-alpine

# Только рантайм-библиотеки (без компиляторов!)
RUN apk add --no-cache libpq-libs

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

COPY . .
USER 10001
CMD ["python", "app.py"]
```

## Практические сценарии

### Сценарий 1: Эталонная сборка с использованием `uv` (2026)

Использование `uv` позволяет сократить время установки зависимостей с минут до секунд.

```dockerfile
# syntax=docker/dockerfile:1
# check=error=true

# --- Этап 1: Сборка (builder) ---
FROM python:3.14-slim AS builder

# Установка uv через официальный бинарник
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Копируем манифесты зависимостей
COPY pyproject.toml uv.lock ./

# Устанавливаем зависимости с использованием кэша монтирования
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Копируем исходный код
COPY . .

# Окончательная установка проекта (создание entrypoints)
RUN uv sync --frozen --no-dev

# --- Этап 2: Финальный образ (runtime) ---
FROM python:3.14-slim

WORKDIR /app

# Настройка рантайма
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONOPTIMIZE=1 \
    PATH="/app/.venv/bin:$PATH"

# Создаем пользователя с минимальными правами
RUN groupadd -r app && useradd -r -g app -u 10001 appuser

# Копируем только виртуальное окружение и код
COPY --from=builder /app/.venv /app/.venv
COPY . .

RUN chown -R appuser:app /app
USER appuser

# Проверка здоровья (требуется установленный curl или модуль в коде)
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import requests; requests.get('http://localhost:8000/health')"

EXPOSE 8000
# Используем форму массива для корректной передачи сигналов
ENTRYPOINT ["gunicorn", "--bind", "0.0.0.0:8000", "myapp.wsgi:application"]
```

### Сценарий 2: Сборка с нативными расширениями (Pandas / Psycopg2)

Использование `wheels` для исключения компиляторов из финального образа.

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.14-slim AS builder

# Инструменты сборки и системные библиотеки
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# Собираем Wheels во временную директорию с кэшем pip
RUN --mount=type=cache,target=/root/.cache/pip \
    pip wheel --wheel-dir /app/wheels -r requirements.txt

# --- Финальный этап ---
FROM python:3.14-slim

WORKDIR /app
# Только рантайм-библиотеки (без -dev пакетов)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

COPY . .
USER 10001
CMD ["python", "app.py"]
```

### Сценарий 3: Монорепозитории с `uv workspace`

Пример для проектов с несколькими внутренними пакетами.

```dockerfile
# В builder этапе
COPY pyproject.toml uv.lock ./
COPY packages/ ./packages/
COPY apps/my-service/ ./apps/my-service/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package my-service
```

### Сценарий 4: Graceful Shutdown с tini и обработчиками сигналов

Для приложений, требующих корректного завершения (закрытие соединений с БД, дренаж очередей).

**Dockerfile:**
```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.14-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends tini && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# tini как PID 1, python как дочерний процесс
USER 10001
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "app.py"]
```

**Код приложения:**
```python
import signal
import sys
import time
from contextlib import contextmanager

is_shutting_down = False

def graceful_shutdown(signum, frame):
    global is_shutting_down
    signal_name = signal.Signals(signum).name
    print(f"Получен {signal_name}, начинаю завершение...", flush=True)
    is_shutting_down = True

# Регистрация обработчиков
signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)

@contextmanager
def lifespan():
    """Контекст для управления ресурсами приложения."""
    # Startup: инициализация БД, кэша и т.д.
    print("Инициализация приложения...", flush=True)
    yield
    # Shutdown: закрытие соединений
    print("Закрытие соединений...", flush=True)

def main():
    with lifespan():
        while not is_shutting_down:
            # Основная работа приложения
            time.sleep(1)
    print("Приложение корректно завершено.", flush=True)
    sys.exit(0)

if __name__ == "__main__":
    main()
```

**Валидация:**
```bash
# Проверка корректного завершения (должен выйти с кодом 0)
docker stop --timeout 30 <container>
docker inspect <container> --format='{{.State.ExitCode}}'
# → 0

# Логи должны содержать:
# → Получен SIGTERM, начинаю завершение...
# → Закрытие соединений...
# → Приложение корректно завершено.
```

Для воркеров, разбирающих очереди (RabbitMQ, Kafka), см. расширенный паттерн graceful shutdown в [Выполнение приложений в контейнере](./container_execution.md#сценарий-5-graceful-shutdown-воркеров-consumer-pattern).

### Сценарий 5: Distroless Python (Максимальная безопасность)

Образы `gcr.io/distroless/python3-*` содержат только интерпретатор Python и минимальные системные библиотеки. Нет shell, пакетного менеджера или стандартных утилит.

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# --- Финальный этап: Distroless ---
FROM gcr.io/distroless/python3-debian12

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Копируем виртуальное окружение и код из builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app /app

# Distroless не содержит пользователей — используем nonroot (UID 65532)
USER nonroot:nonroot

# Distroless не поддерживает HEALTHCHECK с shell — используйте exec-форму
HEALTHCHECK --interval=30s --timeout=3s \
    CMD ["/app/.venv/bin/python", "-c", "import requests; requests.get('http://localhost:8000/health')"]

CMD ["/app/.venv/bin/python", "app.py"]
```

**Валидация:**
```bash
# Проверка что shell отсутствует
docker exec <container> /bin/sh -c "echo hacked" 2>&1
# → exec: "/bin/sh": no such file or directory

# Проверка что пакетные менеджеры отсутствуют
docker exec <container> apt-get --version 2>&1 || echo "apt-get не найден"
# → apt-get не найден
```

**Отладка Distroless:** Используйте debug-тег: `gcr.io/distroless/python3-debian12:debug` — он содержит busybox shell. Подробнее: [Отладка distroless-контейнеров](../../Docker_troubleshooting/debugging_distroless.md)

### Сценарий 6: Wolfi / Chainguard Python (0 CVE)

Wolfi использует `glibc` (в отличие от Alpine), что обеспечивает полную совместимость с бинарными `wheels` при максимальной безопасности.

```dockerfile
# syntax=docker/dockerfile:1
FROM cgr.dev/chainguard/python:3.14 AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

COPY . .

# --- Финальный этап ---
FROM cgr.dev/chainguard/python:3.14

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY --from=builder /install /usr/local
COPY --from=builder /app /app

# Wolfi содержит предустроенного пользователя (UID 65532)
USER nonroot:nonroot

HEALTHCHECK --interval=30s --timeout=3s \
    CMD ["python", "-c", "import requests; requests.get('http://localhost:8000/health')"]

CMD ["python", "app.py"]
```

**Валидация:**
```bash
# Проверка отсутствия уязвимостей
trivy image <image_name> --severity HIGH,CRITICAL
# → 0 vulnerabilities found
```

### Сценарий 7: Аудит безопасности в CI/CD (pip-audit + SBOM + Trivy)

Интеграция проверки зависимостей на этапе сборки.

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./

# Устанавливаем зависимости
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

# --- Этап аудита (не попадает в финальный образ) ---
FROM python:3.14-slim AS audit

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

# Установка и запуск pip-audit
RUN uv run pip install pip-audit && \
    uv run pip-audit --strict --desc

# --- Финальный этап (только рантайм) ---
FROM python:3.14-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

RUN groupadd -r app && useradd -r -g app -u 10001 appuser

COPY --from=builder /app/.venv /app/.venv
COPY . .

RUN chown -R appuser:app /app
USER appuser

EXPOSE 8000
ENTRYPOINT ["gunicorn", "--bind", "0.0.0.0:8000", "myapp.wsgi:application"]
```

**Запуск аудита локально:**
```bash
# Через uv
uv run pip-audit --strict

# Через pip
pip install pip-audit
pip-audit -r requirements.txt

# Генерация SBOM
syft my-python-app:latest -o spdx-json > sbom.spdx.json

# Сканирование уязвимостей образа
trivy image my-python-app:latest --severity HIGH,CRITICAL
```

### Сценарий 8: Профилирование Py-Spy в контейнере

Py-Spy позволяет профилировать Python-приложение без его остановки и без изменения кода. Запускается как sidecar или через `docker exec`.

**Установка в образ (для development/staging):**
```dockerfile
FROM python:3.14-slim AS builder

# Py-Spy требует rust для компиляции, или используйте предкомпилированный бинарник
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cargo \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir py-spy

# ... далее multi-stage сборка
```

**Запуск профилирования:**
```bash
# Через docker exec (требует capabilities SYS_PTRACE)
docker exec --privileged <container> py-spy top --pid 1

# Запись профиля в формате flamegraph
docker exec --privileged <container> py-spy record \
    --output /tmp/profile.svg \
    --duration 30 \
    --pid 1

# Копирование результата с контейнера
docker cp <container>:/tmp/profile.svg ./profile.svg
```

**Дocker Compose с Py-Spy (development):**
```yaml
services:
  app:
    image: my-python-app:latest
    cap_add:
      - SYS_PTRACE  # Необходимо для py-spy
    security_opt:
      - seccomp:unconfined  # Для работы вmacs
```

**Валидация:**
```bash
# Проверка что py-spy установлен
docker exec <container> py-spy --version
# → py-spy 0.3.14
```

### Сценарий 9: Kubernetes Probes для Python

Настройка проверок состояния Python-приложения в Kubernetes.

**Python-приложение с health endpoint:**
```python
# app.py
from fastapi import FastAPI
import psycopg2

app = FastAPI()

@app.get("/health/live")
def liveness():
    """Liveness: приложение работает (без проверки зависимостей)."""
    return {"status": "alive"}

@app.get("/health/ready")
def readiness():
    """Readiness: приложение готово принимать трафик."""
    try:
        # Проверка соединения с БД
        conn = psycopg2.connect("postgresql://user:pass@db:5432/mydb")
        conn.close()
        return {"status": "ready"}
    except Exception as e:
        return {"status": "not ready", "error": str(e)}, 503
```

**Kubernetes манифест:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: python-app
spec:
  template:
    spec:
      containers:
        - name: app
          image: my-python-app:latest
          ports:
            - containerPort: 8000
          startupProbe:
            httpGet:
              path: /health/live
              port: 8000
            failureThreshold: 30  # 30 * 2s = 60 сек на старт
            periodSeconds: 2
          livenessProbe:
            httpGet:
              path: /health/live
              port: 8000
            initialDelaySeconds: 0
            periodSeconds: 10
            timeoutSeconds: 3
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /health/ready
              port: 8000
            initialDelaySeconds: 0
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 3
```

**Валидация:**
```bash
# Проверка статуса проб
kubectl get pods -l app=python-app
# → NAME                        READY   STATUS    RESTARTS   AGE
# → python-app-xxx-yyy          1/1     Running   0          5m

# Детали проб
kubectl describe pod python-app-xxx-yyy | grep -A 5 "Startup Probe"
```

Подробнее: [Пробы в Kubernetes](../../../Kubernetes/Base/probes.md)

## Безопасность и верификация

### Аудит и проверка

1.  **Проверка зависимостей:** Используйте `pip-audit` для поиска известных уязвимостей (CVE) в установленных пакетах.
2.  **SBOM:** Генерируйте состав образа на этапе CI/CD:
    ```bash
    syft <image_name> -o json > sbom.json
    ```
3.  **Обработка сигналов:** Python должен быть PID 1, чтобы `SIGTERM` доходил до приложения. Всегда используйте `ENTRYPOINT ["python", "app.py"]` вместо строковой формы.

### Права доступа

Никогда не запускайте контейнер от `root`. При использовании `slim` образов всегда создавайте системного пользователя. В образах `Wolfi` и `Distroless` используйте предопределенные UID (например, 65532).

## Типичные ошибки и их решение

### Ошибка 1: pip install медленный в Alpine

**Причина:** Отсутствуют pre-built wheels для `musl`. Пакеты компилируются из исходников.

```bash
# Симптом: установка pandas занимает 10+ минут
# Решение 1: использовать slim (Debian) вместо Alpine
FROM python:3.14-slim

# Решение 2: установить gcompat для совместимости с glibc wheels
RUN apk add --no-cache gcompat

# Решение 3: использовать кэш монтирования для ускорения повторных сборок
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```

### Ошибка 2: OOM Kill (exit code 137)

**Причина:** Python потребляет больше памяти, чем лимит контейнера.

```bash
# Диагностика
docker stats --no-stream <container>
# → MEM USAGE / LIMIT
# → 480MiB / 512MiB  (почти满了)

# Решение 1: увеличить лимит памяти
docker run -d --memory=1g my-python-app:latest

# Решение 2: ограничить аллокатор (для ML/Data приложений)
ENV MALLOC_ARENA_MAX=2

# Решение 3: найти утечку памяти
pip install memory_profiler
python -m memory_profiler app.py
```

### Ошибка 3: HEALTHCHECK всегда unhealthy

**Причина:** Приложение слушает `127.0.0.1` вместо `0.0.0.0`, или health endpoint не существует.

```bash
# Диагностика
docker exec <container> python -c "import socket; s = socket.socket(); s.connect(('127.0.0.1', 8000)); print('OK')" 2>&1
# → OK (если слушает localhost)

docker exec <container> python -c "import socket; s = socket.socket(); s.connect(('0.0.0.0', 8000)); print('OK')" 2>&1
# → OK (если слушает все интерфейсы)

# Решение: в Gunicorn/Uvicorn слушать 0.0.0.0
ENTRYPOINT ["gunicorn", "--bind", "0.0.0.0:8000", "myapp.wsgi:application"]
# Или
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Ошибка 4: Зомби-процессы в multiprocessing

**Причина:** Python не обрабатывает зомби-процессы при запуске как PID 1.

```bash
# Симптом
docker exec <container> ps aux | grep -w Z
# → root         7  0.0  0.0      0     0 ?        Z    10:05   0:00 [python] <defunct>

# Решение: добавить tini
RUN apt-get update && apt-get install -y --no-install-recommends tini
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "app.py"]
```

### Ошибка 5: Контейнер не завершается по `docker stop`

**Причина:** Python не обрабатывает `SIGTERM` (垠認ная обработка сигналов).

```bash
# Симптом: docker stop ждёт 10 секунд (дефолтный таймаут), затем SIGKILL

# Решение 1: exec-форма ENTRYPOINT
ENTRYPOINT ["python", "app.py"]  # Правильно
CMD python app.py  # Неправильно — shell-form

# Решение 2: обработчик сигналов в коде
import signal
signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

# Решение 3: увеличить таймаут в Compose
services:
  app:
    stop_grace_period: 30s
```

### Ошибка 6: uv sync падает с "uv.lock not found"

**Причина:** Отсутствует `uv.lock` файл.

```bash
# Решение 1: сгенерировать lock-файл
uv lock

# Решение 2: если используете pip, создайте uv.lock из requirements.txt
uv pip compile requirements.txt -o uv.lock
```

## Лучшие практики

### Сводка рекомендаций

| Практика | Рекомендация | Причина |
| :--- | :--- | :--- |
| **Multi-stage** | SDK для сборки, slim для запуска | Уменьшает размер на 60-80% |
| **Менеджер пакетов** | `uv` вместо `pip` | Скорость установки x10-100 |
| **Cache mount** | `--mount=type=cache,target=/root/.cache/uv` | Ускоряет повторные сборки |
| **Non-root** | `USER appuser` или `USER 10001` | Защита от Container Escape |
| **tini** | `ENTRYPOINT ["/usr/bin/tini", "--"]` | Корректная обработка сигналов |
| **PYTHONUNBUFFERED** | `ENV PYTHONUNBUFFERED=1` | Логи видны в `docker logs` |
| **PYTHONDONTWRITEBYTECODE** | `ENV PYTHONDONTWRITEBYTECODE=1` | Уменьшает размер образа |
| **pip-audit** | `RUN pip-audit --strict` в CI | Раннее обнаружение CVE |
| **HEALTHCHECK** | Встроенный в Dockerfile | Мониторинг состояния контейнера |
| **Pin by digest** | `FROM python:3.14-slim@sha256:...` | Гарантия воспроизводимости |
| **Минимальные пакеты** | `--no-install-recommends` | Уменьшает attack surface |
| **read-only FS** | `--read-only` + tmpfs | Блокировка записи в ФС |

### Чек-лист перед деплоем

**Dockerfile:**
- [ ] Multi-stage: финальная стадия не содержит SDK и build tools
- [ ] Базовый образ зафиксирован по версии или SHA256 дайджесту
- [ ] `USER` инструкция в конце (не root)
- [ ] `--mount=type=cache` для uv/pip
- [ ] `PYTHONUNBUFFERED=1` установлен
- [ ] `PYTHONDONTWRITEBYTECODE=1` установлен
- [ ] `pip-audit` интегрирован в CI
- [ ] HEALTHCHECK настроен и работает
- [ ] Нет секретов в ENV, ARG или Dockerfile

**Запуск контейнера:**
- [ ] `--init` или `init: true` в Compose (или tini в образе)
- [ ] `--read-only` с tmpfs для временных данных
- [ ] `--cap-drop=ALL` + только необходимые capabilities
- [ ] `--security-opt=no-new-privileges`
- [ ] Лимиты памяти установлены (`--memory`)
- [ ] `stop_grace_period`足够的大 для graceful shutdown

**Kubernetes:**
- [ ] StartupProbe с足够的 `failureThreshold` (60+ сек на старт)
- [ ] LivenessProbe не зависит от внешних сервисов
- [ ] ReadinessProbe проверяет зависимость от БД
- [ ] Лимиты памяти и CPU установлены
- [ ] SecurityContext с `runAsNonRoot: true`

## Дополнительная информация

### Смотрите также

- **[Оптимизация сборки Docker-образов](./build_optimization.md)** — глубокий разбор кэширования и Multi-stage.
- **[Безопасность в Dockerfile](./security.md)** — аудит, сканирование CVE и работа с пользователями.
- **[Выполнение приложений в контейнере](./container_execution.md)** — жизненный цикл процесса и сигналы.
- **[Проблема glibc/musl](../../Docker_troubleshooting/alpine_glibc_compatibility.md)** — детали совместимости в Alpine.
