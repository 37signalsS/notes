# Dockerfile: Лучшие практики для Python

## Определения

- **Wheels (*.whl):** Предварительно скомпилированный формат дистрибуции пакетов. Позволяет избежать компиляции на этапе установки, что критично для библиотек с нативными расширениями (C/C++, Rust).
- **uv:** Сверхбыстрый менеджер пакетов и установщик Python (написан на Rust). К 2026 году является стандартом для замены `pip`, `poetry` и `venv` в Docker-контейнерах благодаря экстремальной скорости и встроенному кэшированию.
- **Байт-код (.pyc):** Скомпилированная форма исходного кода Python. В контейнерах часто отключается (`PYTHONDONTWRITEBYTECODE=1`) для уменьшения размера образа.
- **Distroless (Python):** Минималистичные образы (например, от Google), содержащие только интерпретатор и необходимые системные библиотеки, без пакетных менеджеров и shell.
- **Py-Spy:** Инструмент для профилирования работающих Python-приложений без изменения их кода и без остановки процесса (используется как sidecar).
- **SBOM (Software Bill of Materials):** Декларативный список всех компонентов и зависимостей, входящих в состав образа, необходимый для аудита безопасности и CVE-мониторинга.
- **Site-packages:** Директория, в которую устанавливаются сторонние библиотеки Python.

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

### Тюнинг рантайма и ресурсов

*   **Логирование:** `PYTHONUNBUFFERED=1` гарантирует немедленный вывод логов в `stdout`/`stderr` без буферизации.
*   **Память (cgroups v2):** Python 3.14+ лучше понимает лимиты контейнера, но для тяжелых ML/Data-приложений рекомендуется ограничивать аллокатор через `MALLOC_ARENA_MAX=2`.
*   **Оптимизация:** `PYTHONOPTIMIZE=1` удаляет инструкции `assert` и документацию (`__doc__`), что немного ускоряет работу и экономит память.

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

## Дополнительная информация

### Смотрите также

- **[Оптимизация сборки Docker-образов](./build_optimization.md)** — глубокий разбор кэширования и Multi-stage.
- **[Безопасность в Dockerfile](./security.md)** — аудит, сканирование CVE и работа с пользователями.
- **[Выполнение приложений в контейнере](./container_execution.md)** — жизненный цикл процесса и сигналы.
- **[Dockerfile: Лучшие практики для Go](./go.md)** — сравнение с компилируемыми языками.
- **[Проблема glibc/musl](../../Docker_troubleshooting/alpine_glibc_compatibility.md)** — детали совместимости в Alpine.
