# Проверки состояния (Healthcheck) в Podman

## Определения

**Healthcheck (Проверка состояния)** — механизм мониторинга работоспособности приложения внутри контейнера. В отличие от Docker, где за проверку отвечает центральный демон, в Podman выполнение проверок делегируется внешним инструментам или системе инициализации **systemd**.

**Quadlet** — декларативный способ описания контейнеров Podman в виде юнитов **systemd**. Является рекомендуемым стандартом и заменой устаревшему механизму `podman generate systemd`.

**OCI (Open Container Initiative)** — открытый стандарт форматов образов и сред выполнения, используемый Podman по умолчанию.

## Основные концепции

### Различия между Podman и Docker

| Особенность | Docker | Podman |
| :--- | :--- | :--- |
| **Управление** | Централизованный демон (`dockerd`) | Без демона (**daemonless**) |
| **Исполнение** | Демон запускает проверки по таймеру | Выполняется через `systemd` или `podman healthcheck run` |
| **Автоматизация** | Встроена в демон и политики перезапуска | Требует настройки через `systemd` (Quadlet) |
| **Формат образа** | Docker format (поддерживает `HEALTHCHECK`) | OCI (по умолчанию не поддерживает `HEALTHCHECK`) |

### Особенности формата OCI

Инструкция `HEALTHCHECK` в `Dockerfile` игнорируется при сборке образа в формате OCI:
`HEALTHCHECK is not supported for OCI image format and will be ignored. Must use docker format`.

Для использования проверок в Podman с OCI-образами необходимо:

1. Собрать образ в формате Docker: `podman build --format docker -t my-app .`
2. Или определить параметры проверки при запуске (CLI) или в конфигурации Quadlet.

### Статусы проверки

- **starting**: Контейнер запущен, первая проверка еще выполняется.
- **healthy**: Команда проверки вернула код `0`.
- **unhealthy**: Команда вернула ошибку количество раз, равное значению `retries`.

## Практические сценарии

### 1. Подготовка тестового приложения

Создадим приложение на Python (Flask) с эндпоинтом `/health`.

**app.py**:

```python
from flask import Flask, jsonify
import os
app = Flask(__name__)

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
RUN pip install flask && apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
COPY app.py .
CMD ["python", "app.py"]
```

### 2. Запуск через интерфейс командной строки (CLI)

Если образ в формате OCI, параметры проверки указываются при старте:

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
# → a1b2c3d4... (ID контейнера)
```

### 3. Настройка через Quadlet и зависимости

Параметр `Notify=healthy` позволяет **systemd** дождаться успешного прохождения проверки перед запуском зависимых служб.

**db.container**:

```ini
[Container]
Image=postgres
Environment=POSTGRES_PASSWORD=secret
HealthCmd=pg_isready -U postgres
Notify=healthy
```

**app.container**:

```ini
[Unit]
Requires=db.service
After=db.service

[Container]
Image=my-app-image
```

### 4. Диагностика и инспекция состояния

Для получения подробной информации о текущем статусе и логах проверок:

```bash
podman inspect health-demo --format '{{json .State.Health}}'
# → {"Status":"healthy","FailingStreak":0,"Log":[{"Start":"...","End":"...","ExitCode":0,"Output":"..."}]}
```

## Дополнительная информация

### Особенности и ограничения

- **Автоматический перезапуск:** Podman не перезапускает `unhealthy` контейнеры автоматически в обычном режиме. Для этого необходимо использовать `Restart=always` в Quadlet или внешние инструменты мониторинга.
- **Автоматический откат:** При использовании `podman auto-update` наличие `HealthCheck` позволяет системе автоматически откатывать обновление, если новый контейнер не прошел проверку.
- **Контекст выполнения:** Команда проверки выполняется внутри неймспейса контейнера. Убедитесь, что необходимые утилиты (`curl`, `wget`) установлены в образе.

### См. также

- **[Daemonless архитектура](./podman_daemonless_architecture.md)** — основы архитектуры Podman.
- **[Миграция с Docker](./migration-from-docker.md)** — использование Quadlet.
- **[HEALTHCHECK в Dockerfile](../Docker/Dockerfile/Instructions/health_signals.md)** — синтаксис инструкции для Docker-формата.
- **[Автоматические обновления](./podman_auto_update.md)** — использование проверок для отката версий.
