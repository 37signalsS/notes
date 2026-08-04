# Autoheal в Docker: Автоматическое восстановление контейнеров

## Определения

**Autoheal** — механизм или специализированный инструмент (например, `willfarrell/autoheal`), который отслеживает состояние контейнеров на основе их **Healthcheck** и автоматически перезапускает те, что перешли в статус `unhealthy`.

**Self-Healing (Самовосстановление)** — архитектурный паттерн, при котором система способна самостоятельно обнаруживать и исправлять ошибки выполнения без вмешательства администратора.

**Dependency-Aware Healing** — продвинутый метод восстановления (например, в `Docker Surgeon`), учитывающий зависимости между контейнерами (например, перезапуск API-сервиса только после успешного восстановления базы данных).

> **Важно:** Autoheal дополняет стандартную политику `restart`, решая проблему «зависших» приложений, которые продолжают работать (status `running`), но не выполняют свои функции (status `unhealthy`).

## Основные концепции

### Связка механизмов восстановления

Для полной защиты контейнера необходимо комбинировать три уровня настроек:

1.  **Restart Policy (`restart`):** Docker Engine перезапускает контейнер, если основной процесс завершился (статус `exited`).
2.  **Healthcheck:** Инструкция внутри `Dockerfile` или `compose.yaml`, позволяющая Docker Engine понять, что приложение внутри контейнера работоспособно.
3.  **Autoheal:** Внешний монитор, который инициирует `docker restart`, если Healthcheck провален (статус `unhealthy`).

### Популярные инструменты (2025–2026)

#### 1. willfarrell/autoheal
Классическое и наиболее легкое решение для одиночных хостов.
- **Принцип:** Слушает Docker Socket, ищет контейнеры с меткой `autoheal=true`.
- **Новое в 2025:** Поддержка библиотеки **Apprise** для уведомлений в 60+ сервисов (Telegram, Discord, Slack, ntfy).

#### 2. Docker Surgeon
Современная альтернатива для сложных сред.
- **Dependency Tracking:** Позволяет задавать порядок перезапуска через метки (например, `com.monitor.depends.on`).
- **Web UI:** Наличие встроенного дашборда для отслеживания истории падений и графиков здоровья.
- **Multi-host:** Возможность мониторинга нескольких удаленных хостов через агенты.

## Практические сценарии

### Сценарий 1: Настройка willfarrell/autoheal в Docker Compose

Пример с использованием уведомлений через Telegram.

```yaml
services:
  app:
    image: your-app:latest
    restart: unless-stopped
    labels:
      - "autoheal=true"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

  autoheal:
    image: willfarrell/autoheal:latest
    restart: always
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock # Критически важно для доступа к API
    environment:
      - AUTOHEAL_CONTAINER_LABEL=autoheal   # Искать контейнеры с этой меткой
      - AUTOHEAL_INTERVAL=5                 # Частота проверки в секундах
      - AUTOHEAL_DEFAULT_STOP_TIMEOUT=10    # Таймаут остановки перед рестартом
```

### Сценарий 2: Глобальный запуск через CLI

Запуск монитора, который будет следить за всеми контейнерами на хосте, имеющими соответствующую метку.

```bash
docker run -d \
  --name autoheal \
  --restart=always \
  -e AUTOHEAL_CONTAINER_LABEL=autoheal \
  -v /var/run/docker.sock:/var/run/docker.sock \
  willfarrell/autoheal
```

### Сценарий 3: Настройка Docker Surgeon для зависимых сервисов

Если ваше API падает без базы данных, используйте умный перезапуск.

```yaml
services:
  db:
    image: postgres:16
    labels:
      - "autoheal=true"

  api:
    image: my-api:v1
    labels:
      - "autoheal=true"
      - "com.monitor.depends.on=db" # Перезапустить DB перед API, если оба упали
    healthcheck:
      test: ["CMD", "nc", "-z", "localhost", "8080"]

  surgeon:
    image: krystall9/docker-surgeon:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    ports:
      - "8081:8081" # Порт для Web UI
```

### Сценарий 4: Тестирование самовосстановления

Создание контейнера, который гарантированно станет `unhealthy` через 10 секунд:

```bash
docker run -d \
  --name test-autoheal \
  --label autoheal=true \
  --health-cmd="exit 1" \
  --health-interval=5s \
  --health-retries=1 \
  alpine sleep 3600
```

## Дополнительная информация

### Сравнение методов восстановления

| Метод | Уровень | Когда использовать | Плюсы |
| :--- | :--- | :--- | :--- |
| **Restart Policy** | Процесс | Всегда | Минимум накладных расходов |
| **Autoheal** | Состояние | Single Host / Edge | Простота, уведомления |
| **Docker Surgeon** | Система | Сложные стеки | Зависимости, Web UI |
| **Orchestrator** | Кластер | Swarm / K8s | Нативное самовосстановление |

### Нюансы использования

*   **Безопасность:** Монтирование Docker Socket дает полный контроль над хостом. В 2026 году рекомендуется ограничивать доступ через **Docker Contexts** или использовать защищенные прокси (например, `tecnativa/docker-socket-proxy`) для предоставления только RO-доступа (хотя для рестарта Autoheal нужны права на запись).
*   **Логирование:** Всегда проверяйте логи Autoheal/Surgeon при отладке цикличных рестартов (Restart Loops). Если приложение падает сразу после запуска, увеличьте `start_period` в Healthcheck.
*   **Оркестрация:** В **Docker Swarm** и **Kubernetes** внешние инструменты не нужны. Оркестратор сам убивает и пересоздает задачи/поды, если пробы здоровья (`livenessProbe`) не проходят.
*   **Podman:** При использовании Podman вместо Autoheal рекомендуется использовать **systemd** таймеры и опцию `--restart-policy`, либо встроенный `podman auto-update`.

### См. также

*   **[Инструкции HEALTHCHECK](../Dockerfile/Instructions/health_signals.md)** — глубокое погружение в настройку проверок.
*   **[Политики перезапуска](../docker_commands.md#политики-перезапуска---restart)** — базовый уровень восстановления.
*   **[Диагностика через Docker Events](./debugging_with_docker_events.md)** — мониторинг событий `health_status: unhealthy` и `restart`.
