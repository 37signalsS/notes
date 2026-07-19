# Dockerfile: Лучшие практики для Python

## Определения

- **Wheels (*.whl):** Предварительно скомпилированный формат дистрибуции пакетов. Позволяет избежать компиляции на этапе установки, что критично для библиотек с нативными расширениями (C/C++, Rust).
- **uv:** Сверхбыстрый менеджер пакетов и установщик Python (написан на Rust). К 2026 году является стандартом для замены `pip`, `poetry` и `venv` в Docker-контейнерах благодаря экстремальной скорости и встроенному кэшированию.
- **Байт-код (.pyc):** Скомпилированная форма исходного кода Python. В контейнерах часто отключается (`PYTHONDONTWRITEBYTECODE=1`) для уменьшения размера образа.
- **Distroless (Python):** Минималистичные образы, содержащие только интерпретатор и необходимые системные библиотеки, без пакетных менеджеров и оболочки (shell).

## Базовые концепции

### Особенности сборки Python (Интерпретируемый язык)

*   **Тип:** Интерпретируемый. Требует наличия рантайма Python в финальном образе.
*   **Артефакт:** Исходный код и установленные зависимости в `site-packages`.
*   **Multi-stage:** Обязателен при использовании библиотек, требующих сборки (Pandas, NumPy, Psycopg). Инструменты сборки (`gcc`, `g++`, `musl-dev`) должны оставаться в builder-слое.
*   **Кэширование BuildKit:** Использование `--mount=type=cache,target=/root/.cache/uv` или `pip` позволяет сохранять загруженные пакеты между сборками, не раздувая при этом слои образа.

### Выбор базового образа

| Образ | Рекомендация | Причина |
| :--- | :--- | :--- |
| **`python:3.14-slim`** | **Рекомендуется** | Баланс между размером и совместимостью (`glibc`). Большинство `wheels` устанавливаются мгновенно. |
| **`python:3.14-alpine`** | С осторожностью | Минимальный размер, но требует компиляции многих пакетов из-за `musl`, что замедляет сборку. |
| **`python:3.14` (Full)** | Не рекомендуется | Слишком большой размер (>900МБ) и широкая поверхность атаки. |

### Оптимизация рантайма

Для production-среды необходимо установить следующие переменные окружения:
- `PYTHONUNBUFFERED=1`: Немедленный вывод логов (важно для сбора логов в K8s/Docker).
- `PYTHONDONTWRITEBYTECODE=1`: Отключение записи `.pyc` файлов для экономии места.
- `PYTHONOPTIMIZE=1`: Базовая оптимизация (удаление `assert` и `__debug__` кода).

### Безопасность

- **Непривилегированный пользователь:** Всегда создавайте и используйте `useradd` для запуска приложения.
- **Сканирование зависимостей:** Рекомендуется запускать `pip-audit` или `uv pip compile` с последующим сканированием в CI/CD.

## Практические сценарии

### Сценарий 1: Современная сборка с использованием `uv` (Рекомендуемый)

`uv` значительно ускоряет сборку и обеспечивает детерминированность зависимостей.

```dockerfile
# syntax=docker/dockerfile:1
# --- Этап 1: Сборка (builder) ---
FROM python:3.14-slim AS builder

# Установка uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Копируем манифесты зависимостей
COPY pyproject.toml uv.lock ./

# Устанавливаем зависимости в системную директорию (без venv для простоты Docker)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Копируем код и устанавливаем проект
COPY . .
RUN uv sync --frozen --no-dev

# --- Этап 2: Финальный образ ---
FROM python:3.14-slim

WORKDIR /app

# Настройка рантайма
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONOPTIMIZE=1

# Создаем пользователя
RUN groupadd -r app && useradd -r -g app appuser

# Копируем только установленные пакеты и код
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY . .

RUN chown -R appuser:app /app
USER appuser

EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "myapp.wsgi:application"]
```

### Сценарий 2: Многоэтапная сборка с компиляцией (Стандартный pip)

Используется, если проект требует компиляции C-расширений.

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.14-slim AS builder

# Устанавливаем инструменты сборки
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# Собираем Wheels во временную директорию
RUN --mount=type=cache,target=/root/.cache/pip \
    pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt

# --- Финальный этап ---
FROM python:3.14-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Копируем и устанавливаем готовые Wheels
COPY --from=builder /app/wheels /wheels
RUN pip install --no-cache /wheels/* && rm -rf /wheels

COPY . .
USER 10001
CMD ["python", "app.py"]
```

### Сценарий 3: Правильный Entrypoint для обработки сигналов

Python должен получать сигналы `SIGTERM` для корректного завершения. Всегда используйте форму JSON для `CMD`.

```dockerfile
# Правильно: процесс получает PID 1 и обрабатывает сигналы
CMD ["python", "main.py"]

# Неправильно: сигналы перехватываются оболочкой /bin/sh
CMD python main.py
```

## Дополнительная информация

### Смотрите также

- [Оптимизация сборки Docker-образов](./build_optimization.md) — детали кэширования и multi-stage.
- [Безопасность в Dockerfile](./security.md) — работа с пользователями и сканирование CVE.
- [Выполнение приложений в контейнере](./container_execution.md) — жизненный цикл процесса и сигналы.
- [Dockerfile: Лучшие практики для Go](./go.md) — сравнение с компилируемыми языками.
