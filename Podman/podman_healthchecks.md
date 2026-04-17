# Проверки состояния (Healthcheck) в Podman

## Определения

**Healthcheck** — механизм проверки работоспособности приложения внутри контейнера. В отличие от Docker, где за проверку отвечает центральный демон, в Podman выполнение проверок делегируется внешним инструментам или системе инициализации (`systemd`).

**Quadlet** — современный способ описания контейнеров Podman как системных юнитов (`systemd units`). Является рекомендуемой заменой устаревшему `podman generate systemd`.

## Основные концепции

### Различия между Podman и Docker

| Особенность | Docker | Podman |
| :--- | :--- | :--- |
| **Управление** | Централизованный демон (`dockerd`) | Без демона (`daemonless`) |
| **Исполнение** | Демон сам запускает проверки каждые N секунд | Проверки выполняются через `systemd` или `podman healthcheck run` |
| **Автоматизация** | Встроена в демон и restart policy | Требует настройки через `systemd` (Quadlet) |
| **Формат образа** | Docker format (поддерживает `HEALTHCHECK`) | OCI (по умолчанию, НЕ поддерживает `HEALTHCHECK`) |

### Проблема формата OCI

По умолчанию Podman собирает образы в формате **OCI (Open Container Initiative)**. Инструкция `HEALTHCHECK` в `Dockerfile` игнорируется при сборке OCI-образа:
`HEALTHCHECK is not supported for OCI image format and will be ignored. Must use docker format`.

**Решения:**

1. Сборка в старом формате Docker: `podman build --format docker -t my-app .`
2. Определение параметров проверки при запуске контейнера (через CLI или Quadlet).

## Практические сценарии

### 1. Подготовка приложения (Flask)

Для демонстрации создадим простое приложение на Python с эндпоинтом `/health`.

**app.py**:

```python
from flask import Flask, jsonify
import os
app = Flask(__name__)

@app.route("/")
def index():
    return "Hello from Podman!"

@app.route("/health")
def health():
    if os.getenv("FAIL", "false") == "true":
        return jsonify({"status": "unhealthy"}), 500
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
```

**Dockerfile**:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY app.py .
RUN pip install flask
# Важно: установите curl, так как его обычно нет в slim-образах
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
EXPOSE 8080
CMD ["python", "app.py"]
```

### 2. Запуск через CLI (podman run)

Если в образе нет встроенного healthcheck (формат OCI), его нужно указать при запуске:

```bash
podman run -d \
  --name health-demo \
  --replace \
  -p 8080:8080 \
  --health-cmd="curl --fail http://localhost:8080/health || exit 1" \
  --health-interval=10s \
  --health-timeout=3s \
  --health-retries=3 \
  healthcheck-demo
```

**Ключевые флаги:**

- `--replace`: автоматически удаляет старый контейнер с тем же именем перед запуском (предотвращает ошибки `name already in use`).
- `--health-cmd`: команда, выполняемая ВНУТРИ контейнера в том же неймспейсе.

### 3. Ручная логика ожидания (wait-logic)

Самый простой и популярный способ — циклическая проверка доступности порта или сервиса прямо в команде запуска.

```bash
podman run --rm --pod mypod postgres sh -c 'until pg_isready -h localhost -p 5432; do sleep 1; done; echo ready'
```

## Зависимости через Notify=healthy

В Podman нет прямого аналога `depends_on` из Docker Compose. Однако, используя **Quadlet** и **systemd**, можно добиться более надежного поведения: запуск зависимого сервиса только после того, как основной станет **`healthy`**.

### Как это работает: Notify=healthy

Параметр `Notify=healthy` связывает статус `healthcheck` контейнера с механизмом нотификации `systemd`. Сервис в `systemd` будет считаться "запущенным" только тогда, когда контейнер успешно пройдет проверку работоспособности.

### Пример реализации (Quadlet)

**db.container (База данных)**

```ini
[Unit]
Description=PostgreSQL container

[Container]
Image=postgres
ContainerName=db
Environment=POSTGRES_PASSWORD=secret
# Указываем проверку здоровья
HealthCmd=pg_isready -U postgres
HealthInterval=5s
HealthRetries=5
# Связываем статус с systemd
Notify=healthy

[Install]
WantedBy=multi-user.target
```

**app.container (Приложение)**

```ini
[Unit]
Description=My Application
# Устанавливаем жесткие зависимости в systemd
Requires=db.service
After=db.service

[Container]
Image=my-app-image
Exec=sh -c "echo app started && sleep infinity"

[Install]
WantedBy=multi-user.target
```

**Результат:**

1. `systemd` начинает запуск `db.service`.
2. `db.service` переходит в статус `active` только после того, как `pg_isready` вернет успех.
3. Только после этого `systemd` начнет запуск `app.service`.

## Параметры и тюнинг

| Параметр | Описание | Dev (рекомендовано) | Prod (рекомендовано) |
| :--- | :--- | :--- | :--- |
| **Interval** | Частота выполнения проверки | `5s` (быстрый фидбек) | `30s` (меньше нагрузки) |
| **Timeout** | Время ожидания ответа | `3s` | `5s` |
| **Retries** | Кол-во попыток до смены статуса | `1` | `3-5` (защита от лагов) |

## Статусы и диагностика

### Статусы Healthcheck

- **starting**: контейнер только запущен, первая проверка еще не завершена.
- **healthy**: команда проверки вернула код `0`.
- **unhealthy**: команда вернула ошибку (код `1`) `retries` раз подряд.

### Диагностика

Чтобы понять, почему контейнер стал `unhealthy`, используйте:

```bash
podman inspect demo --format '{{json .State.Health}}'
```

В выводе будет видна история последних проверок и ошибки (например, отсутствие `curl` в контейнере).

## Дополнительная информация

### Важные нюансы

- **Healthcheck ≠ Restart**: Сам по себе Podman не перезапускает контейнер, если он стал `unhealthy`. Для автоперезапуска используйте `systemd` с опцией `Restart=always` в юните.
- **Внутренняя проверка**: Команда выполняется в неймспейсе контейнера. Она проверяет внутреннее состояние, а не доступность порта снаружи хоста.
- **Инструментарий**: Убедитесь, что в образе установлены необходимые утилиты (`curl`, `wget`, `nc`).

### См. также

- **[Daemonless архитектура](./podman_daemonless_architecture.md)** — основы работы Podman.
- **[Миграция с Docker](./migration-from-docker.md)** — замена Compose на Quadlet.
- **[HEALTHCHECK в Dockerfile](../Docker/Dockerfile/Instructions/health_signals.md)** — синтаксис инструкции для Docker-формата.
