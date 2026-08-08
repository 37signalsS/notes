# Настройка Grafana в Docker Compose — Modern Observability Stack

## Определения

**Grafana** — платформа для визуализации, анализа и мониторинга данных из различных источников. См. [Обзор Grafana](../grafana_overview.md).

**Docker Compose** — инструмент для декларативного описания и управления многоконтейнерными приложениями. В контексте мониторинга позволяет развернуть полный стек (Grafana + Prometheus + Alloy) одной командой.

**Grafana Alloy** — универсальный агент для сбора метрик, логов, трейсов и профилей. В 2026 году является основным стандартом для сбора телеметрии, заменяя связку Promtail, Node Exporter и старые версии Grafana Agent.

**Провиженинг (Provisioning)** — механизм автоматической настройки ресурсов Grafana (источники данных, дашборды) через конфигурационные файлы при старте контейнера. См. [Провиженинг Grafana (подробно)](../grafana_provisioning.md).

## Основные концепции

Современный подход к развертыванию через Docker Compose (2026+) базируется на концепции **Unified Observability**. Вместо множества разрозненных экспортеров используется единый агент (Alloy), который собирает данные и отправляет их в бэкенды (Prometheus, Loki, Tempo).

### Структура проекта

Для чистоты конфигурации и поддержки GitOps рекомендуется следующая структура:

```text
monitoring-stack/
├── compose.yml              # Основной файл стека
├── .env                     # Секреты и переменные окружения
├── alloy/
│   └── config.alloy         # Конфигурация сбора данных
├── prometheus/
│   └── prometheus.yml       # Конфигурация хранения (минимальная)
└── grafana/
    └── provisioning/        # Автоматизация ресурсов
        ├── datasources/
        │   └── datasources.yaml
        └── dashboards/
            ├── dashboards.yaml
            └── default/     # JSON-файлы дашбордов
```

## Практические сценарии

### Сценарий 1: Конфигурация Modern Stack (Grafana 13 + Prometheus 3)

Ниже представлен файл `compose.yml`, соответствующий спецификациям 2026 года.

```yaml
# monitoring-stack/compose.yml

services:
  prometheus:
    image: prom/prometheus:v3.13.1
    container_name: monitoring-prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.enable-lifecycle'
      - '--web.enable-otlp-receiver' # Включаем прием OTLP
    volumes:
      - ./prometheus:/etc/prometheus:ro
      - prometheus_data:/prometheus
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:9090/-/healthy"]
      interval: 15s
    networks:
      - observer-net

  alloy:
    image: grafana/alloy:v1.18.1
    container_name: monitoring-alloy
    privileged: true # Необходимо для сбора системных метрик хоста
    pid: host        # Для доступа к процессам хоста
    volumes:
      - ./alloy/config.alloy:/etc/alloy/config.alloy:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /:/host/root:ro,rslave
    command: run --storage.path=/var/lib/alloy /etc/alloy/config.alloy
    depends_on:
      prometheus:
        condition: service_healthy
    networks:
      - observer-net

  grafana:
    image: grafana/grafana:13.1.3
    container_name: monitoring-grafana
    user: "472:472"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASS:-admin}
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    ports:
      - "3000:3000"
    depends_on:
      prometheus:
        condition: service_healthy
    networks:
      - observer-net
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '0.5'

volumes:
  prometheus_data:
  grafana_data:

networks:
  observer-net:
    driver: bridge
```

### Сценарий 2: Конфигурация Grafana Alloy (config.alloy)

Alloy заменяет Node Exporter и самостоятельно собирает метрики хоста и Docker-контейнеров.

```alloy
// monitoring-stack/alloy/config.alloy

// Сбор метрик хоста (замена Node Exporter)
prometheus.exporter.unix "node" {
  rootfs_path = "/host/root"
}

// Сбор метрик Docker-контейнеров (замена cAdvisor)
prometheus.exporter.cadvisor "docker" {
  docker_host = "unix:///var/run/docker.sock"
}

// Сбор метрик из экспортеров и отправка в Prometheus
prometheus.scrape "metrics" {
  targets = concat(
    prometheus.exporter.unix.node.targets,
    prometheus.exporter.cadvisor.docker.targets,
  )
  forward_to = [prometheus.remote_write.local.receiver]
}

prometheus.remote_write "local" {
  endpoint {
    url = "http://prometheus:9090/api/v1/write"
  }
}
```

### Сценарий 3: Автоматическая настройка источников данных

Файл `grafana/provisioning/datasources/datasources.yaml` гарантирует наличие Prometheus при первом входе.

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    isDefault: true
    jsonData:
      httpMethod: POST
      prometheusType: Prometheus
    editable: false
```

### Сценарий 4: Запуск и проверка

1.  **Запуск:**
    ```bash
    docker compose up -d
    ```

2.  **Проверка компонентов:**
    - **Alloy UI:** `http://localhost:12345` (граф компонентов и ошибки сбора).
    - **Prometheus Targets:** `http://localhost:9090/targets`.
    - **Grafana:** `http://localhost:3000` (логин `admin`, пароль из `.env`).

## Безопасность и эксплуатация

### Чек-лист безопасности

*   **Non-Root User:** В Grafana всегда используйте `user: "472:472"`. Для этого перед запуском выполните `chown -R 472:472 ./grafana/data` (если используете bind mounts).
*   **Секреты:** Используйте `.env` файл и переменные окружения. Никогда не храните пароли в `compose.yml`.
*   **Ресурсные лимиты:** Ограничивайте потребление памяти через `deploy.resources.limits`, чтобы Grafana или Prometheus не «уронили» хост при всплеске нагрузки.
*   **Network Isolation:** Пробрасывайте на хост только порт Grafana (3000). Остальные сервисы должны общаться внутри сети `observer-net`.

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Permission Denied на томах** | Неверный владелец файлов на хосте | `sudo chown -R 472:472 ./grafana` |
| **Alloy не видит контейнеры** | Нет доступа к `docker.sock` | Проверьте монтирование сокета и права Alloy |
| **Prometheus не принимает данные** | Не включен Remote Write/OTLP | Проверьте флаги в `command` сервиса prometheus |
| **Стек не стартует** | Ошибка в `.env` или YAML | `docker compose config` для проверки итогового файла |

## Дополнительная информация

**См. также:**

*   [Провиженинг Grafana (подробно)](../grafana_provisioning.md) — декларативное управление дашбордами и плагинами.
*   [Высокая доступность Grafana](../high_availability.md) — развертывание с внешней БД и Redis.
*   [Loki в Docker Compose](../../Loki/Docker_Compose/loki_docker_compose_setup.md) — расширение стека сбором логов.
*   [Полный мониторинг Prometheus (SSoT)](../../Prometheus/installation/docker_stack/docker-compose_config.md) — детальный разбор стека с Alertmanager.
*   [Grafana Alloy: Обзор](../grafana_alloy_overview.md) — возможности и архитектура нового агента.
