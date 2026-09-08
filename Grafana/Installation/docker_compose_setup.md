# Настройка Grafana в Docker Compose — Modern Observability Stack

## Определения

**Grafana** — универсальная open-source платформа для аналитики, мониторинга и интерактивной визуализации данных телеметрии (метрик, логов, трассировок, профилей). Grafana не хранит собираемые данные, а выступает интерфейсом для внешних источников. По умолчанию работает на порту `3000` (протокол HTTP/HTTPS). Управление параметрами сервера осуществляется через файл `grafana.ini` или переменные окружения (формат `GF_<SECTION>_<KEY>`). См. [Обзор Grafana](../grafana_overview.md).

**Docker Compose** — инструмент для декларативного описания и управления многоконтейнерными приложениями. В контексте мониторинга позволяет развернуть полный стек (Grafana + Prometheus + Alloy) одной командой. Актуальной является версия Compose Specification v5+ (плагин к Docker CLI), устаревшая утилита `docker-comply` (Python) признана EOL в 2025 году. Подробнее об основах: [Обзор Docker Compose](../../Docker/Docker_compose/docker_compose_overview.md).

**Grafana Alloy** — универсальный агент для сбора метрик, логов, трейсов и профилей. В 2026 году является основным стандартом для сбора телеметрии, заменяя связку Promtail, Node Exporter и старые версии Grafana Agent. Alloy построен на базе OpenTelemetry Collector и использует декларативный язык конфигурации River. См. [Grafana Alloy: Обзор](../grafana_alloy_overview.md).

**Провиженинг (Provisioning)** — механизм автоматической настройки ресурсов Grafana (источники данных, дашборды) через конфигурационные файлы при старте контейнера. Позволяет применять подход Infrastructure as Code (IaC) и обеспечивает идентичное состояние Grafana во всех окружениях. См. [Провиженинг Grafana (подробно)](../grafana_provisioning.md).

**Unified Observability** — архитектурный подход, при котором единый агент (Alloy) собирает все типы телеметрии (метрики, логи, трейсы) и отправляет их в специализированные бэкенды (Prometheus, Loki, Tempo). Это заменяет разрозненные экспортеры и упрощает управление пайплайнами данных.

**Named Volumes** — томы Docker, управляемые плагином. Данные в них сохраняются даже после удаления контейнеров, что критично для персистентности TSDB Prometheus и базы данных Grafana. В отличие от bind mounts, не требуют настройки прав доступа на хосте.

## Предварительные требования

### Аппаратные требования
| Компонент | Минимум | Рекомендуется |
| :--- | :--- | :--- |
| **CPU** | 2 ядра | 4+ ядра |
| **RAM** | 4 GB | 8+ GB |
| **Диск** | 20 GB (SSD) | 50+ GB (SSD/NVMe) |

### Программные требования
- **Docker Engine:** 24.0+ (с включенным containerd)
- **Docker Compose:** v2.20+ (плагин к Docker CLI)
- **ОС:** Linux (Debian 12+, Ubuntu 22.04+, RHEL 9+), macOS 13+, Windows 11 Pro/Enterprise с WSL2

### Начальное состояние окружения
1. Docker Engine установлен и служба активна: `systemctl status docker` # → active (running)
2. Пользователь добавлен в группу `docker`: `sudo usermod -aG docker $USER` (требует перелогина)
3. Достаточно свободного места в `/var/lib/docker/` для образов и томов
4. Порт `3000` (Grafana) свободен на хосте: `ss -tlnp | grep :3000` # → нет вывода

## Основные концепции

### Архитектура стека

Современный подход к развертыванию через Docker Compose (2026+) базируется на концепции **Unified Observability**. Grafana выступает уровнем представления, Prometheus — хранилищем метрик, а Alloy — единым сборщиком телеметрии, который заменяет специализированные экспортеры.

```
┌─────────────────────────────────────────────────────────────┐
│                      Внешние источники                       │
│              (приложения, контейнеры, ОС хоста)              │
└──────────────────────┬──────────────────────────────────────┘
                       │ scrape / логи / трейсы
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                    Grafana Alloy                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ prometheus  │  │   loki      │  │   tempo             │  │
│  │ .exporter   │  │ .source     │  │ .receiver           │  │
│  │ .unix/cadv. │  │ .file/docker│  │ .otlp               │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         │                │                     │              │
│         ▼                ▼                     ▼              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              prometheus.remote_write                  │    │
│  │              loki.write / tempo.write                 │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────┬──────────────────────────────────────┘
                       │ OTLP / HTTP
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Prometheus (метрики) │ Loki (логи) │ Tempo (трейсы)        │
└──────────────────────┬──────────────────────────────────────┘
                       │ query API
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                      Grafana UI                             │
│           (визуализация, алертинг, дашборды)                │
└─────────────────────────────────────────────────────────────┘
```

### Сетевое взаимодействие

Все компоненты стека объединяются в выделенную bridge-сеть (в данном примере — `observer-net`). Это обеспечивает изоляцию от других контейнеров на хосте и позволяет использовать встроенный DNS Docker для обращения к сервисам по их именам (например, `prometheus:9090`). Grafana пробрасывается на порт `3000` хоста; остальные сервисы остаются изолированными внутри сети.

### Персистентность данных

| Компонент | Тип данных | Место хранения |
| :--- | :--- | :--- |
| **Prometheus TSDB** | Метрики | Именованный том `prometheus_data` |
| **Grafana DB** | Дашборды, пользователи, алерты | Именованный том `grafana_data` |
| **Alloy WAL** | Буфер телеметрии | Каталог `/var/lib/alloy` |

Grafana по умолчанию использует **SQLite** для хранения конфигураций. Для продакшен-инсталляций рекомендуется подключение к **PostgreSQL** или **MySQL** (см. [Высокая доступность Grafana](../high_availability.md)).

### Версионирование и соответствие

| Компонент | Образ | Версия | Статус |
| :--- | :--- | :--- | :--- |
| **Grafana** | `grafana/grafana` | 13.1.3 | Current (стабильная) |
| **Prometheus** | `prom/prometheus` | 3.13.1 | Поддержка OTLP и Auto-tuning |
| **Grafana Alloy** | `grafana/alloy` | 1.18.1 | Актуальный стандарт |
| **Node Exporter** | `prom/node-exporter` | 1.12.1 | Метрики хоста (через Alloy) |

Информация актуальна на **август 2026 года**.

### Структура проекта

Для чистоты конфигурации и поддержки GitOps рекомендуется следующая структура:

```text
monitoring-stack/
├── compose.yml              # Основной файл стека
├── .env                     # Секреты и переменные окружения
├── alloy/
│   └── config.alloy         # Конфигурация сбора данных
├── prometheus/
│   ├── prometheus.yml       # Конфигурация хранения и scrape
│   └── alerts/              # Правила алертинга
└── grafana/
    └── provisioning/        # Автоматизация ресурсов
        ├── datasources/
        │   └── datasources.yaml
        └── dashboards/
            ├── dashboards.yaml
            └── default/     # JSON-файлы дашбордов
```

## Практические сценарии

### Сценарий 1: Файл переменных окружения (.env)

Файл `.env` должен находиться в том же каталоге, что и `compose.yml`. Docker Compose автоматически подгружает его и интерполирует переменные в YAML. Никогда не храните пароли или секреты непосредственно в `compose.yml`.

```bash
# monitoring-stack/.env

# Grafana
GRAFANA_PASS=SecureAdminPassword2026!

# Prometheus
PROM_RETENTION_TIME=30d
PROM_RETENTION_SIZE=50GB

# Alloy
ALLOY_CLUSTER_ENABLED=false
```

> **Примечание:** Приоритет переменных окружения: переменные ОС > `.env` файл > значения в `compose.yml`. Для продакшена используйте внешние секреты (Docker Secrets, HashiCorp Vault, SOPS).

### Сценарий 2: Конфигурация Compose (compose.yml)

Ниже представлен файл `compose.yml`, соответствующий спецификациям 2026 года. Каждый параметр снабжен комментарием, объясняющим его назначение.

```yaml
# monitoring-stack/compose.yml

services:
  prometheus:
    image: prom/prometheus:v3.13.1
    container_name: monitoring-prometheus
    # Автоматический перезапуск при падении или перезагрузке хоста
    restart: unless-stopped
    command:
      # Путь к конфигурационному файлу (монтируется как read-only)
      - '--config.file=/etc/prometheus/prometheus.yml'
      # Путь к данным TSDB (персистентный том)
      - '--storage.tsdb.path=/prometheus'
      # Retention политики (можно задать в prometheus.yml или через флаг)
      - '--storage.tsdb.retention.time=${PROM_RETENTION_TIME:-30d}'
      # Позволяет применять изменения конфига через API без перезагрузки
      - '--web.enable-lifecycle'
      # Включаем прием OTLP напрямую (упрощает архитектуру)
      - '--web.enable-otlp-receiver'
      # Автоматическая настройка лимитов памяти Go runtime (обязателен при deploy.limits)
      - '--auto-gomemlimit'
      # Автоматическая настройка количества потоков Go
      - '--auto-gomaxprocs'
    volumes:
      # Bind mount: конфигурация Prometheus (read-only для безопасности)
      - ./prometheus:/etc/prometheus:ro
      # Named volume: данные метрик (персистентные)
      - prometheus_data:/prometheus
    ports:
      # Порт 9090 проброшен на хост для доступа к UI и API
      - "9090:9090"
    healthcheck:
      # Проверка готовности: Prometheus отвечает на /-/healthy
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:9090/-/healthy"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 30s
    logging:
      # Ограничение размера логов предотвращает переполнение диска
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - observer-net
    deploy:
      resources:
        limits:
          # Лимит памяти: Prometheus v3 с auto-gomemlimit эффективно работает в 2G
          memory: 2G
          cpus: '1.0'

  alloy:
    image: grafana/alloy:v1.18.1
    container_name: monitoring-alloy
    # privileged требуется для доступа к cgroup и kernel-метрикам
    privileged: true
    # Доступ к PID пространству хоста (для метрик процессов)
    pid: host
    restart: unless-stopped
    volumes:
      # Конфигурация River
      - ./alloy/config.alloy:/etc/alloy/config.alloy:ro
      # Docker socket для динамического обнаружения контейнеров
      - /var/run/docker.sock:/var/run/docker.sock:ro
      # Rootfs хоста для сбора системных метрик (аналог Node Exporter)
      - /:/host/root:ro,rslave
      # Персистентность WAL (Write-Ahead Log) и кэша
      - alloy_data:/var/lib/alloy
    command: run --storage.path=/var/lib/alloy /etc/alloy/config.alloy
    depends_on:
      # Запускаем Prometheus только после готовности
      prometheus:
        condition: service_healthy
    ports:
      # UI для отладки конфигурации (порт 12345)
      - "12345:12345"
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:12345/health"]
      interval: 15s
      timeout: 5s
      retries: 3
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - observer-net
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: '0.5'

  grafana:
    image: grafana/grafana:13.1.3
    container_name: monitoring-grafana
    # UID/GID 472 — стандартный пользователь Grafana в образе
    user: "472:472"
    restart: unless-stopped
    environment:
      # Пароль администратора (из .env или значение по умолчанию)
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASS:-admin}
      # Отключаем самостоятельную регистрацию пользователей
      - GF_USERS_ALLOW_SIGN_UP=false
      # Включаем интерполяцию переменных окружения в provisioning
      - GF_PATHS_PROVISIONING=/etc/grafana/provisioning
      # Включаем интерполяцию ${VAR} в YAML-файлах провиженинга
      - GF_SECURITY_ALLOW_EMBEDDING=true
    volumes:
      # Named volume: база данных Grafana (дашборды, пользователи)
      - grafana_data:/var/lib/grafana
      # Bind mount: конфигурации провиженинга (read-only)
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    ports:
      # Единственный проброшенный порт стека
      - "3000:3000"
    depends_on:
      prometheus:
        condition: service_healthy
      alloy:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:3000/api/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 60s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - observer-net
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '0.5'

volumes:
  prometheus_data:
    driver: local
  grafana_data:
    driver: local
  alloy_data:
    driver: local

networks:
  observer-net:
    driver: bridge
    # Внутренняя сеть: сервисы не доступны извне, кроме проброшенных портов
    internal: false
```

### Сценарий 3: Минимальная конфигурация Prometheus (prometheus.yml)

Prometheus требует базовый конфигурационный файл для работы. Ниже приведен минимальный пример, который включает scrape-интервал и retention.

```yaml
# monitoring-stack/prometheus/prometheus.yml

global:
  scrape_interval: 15s
  scrape_timeout: 10s
  evaluation_interval: 15s
  external_labels:
    cluster: 'monitoring-stack'
    environment: 'production'

# Scrape Alloy для метрик хоста и Docker
scrape_configs:
  - job_name: 'alloy'
    static_configs:
      - targets: ['alloy:12345']

  # Self-scraping Prometheus
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

alerting:
  alertmanagers:
    - static_configs:
        - targets: []

rule_files:
  - '/etc/prometheus/alerts/*.yml'
```

> **Важно:** Для продакшен-режима добавьте `rule_files` с определёнными правилами алертинга и настройте `Alertmanager` для маршрутизации уведомлений. См. [Полный мониторинг Prometheus](../../Prometheus/installation/docker_stack/docker-compose_config.md).

### Сценарий 4: Конфигурация Grafana Alloy (config.alloy)

Alloy заменяет Node Exporter и самостоятельно собирает метрики хоста и Docker-контейнеров. Конфигурация использует декларативный язык River, где каждый компонент явно указывает, куда передавать данные через аргумент `forward_to`.

```alloy
// monitoring-stack/alloy/config.alloy

// 1. Сбор метрик хоста (замена Node Exporter)
prometheus.exporter.unix "node" {
  // Путь к rootfs хоста (монтируется как /host/root)
  rootfs_path = "/host/root"
  // Включение всех стандартных сборщиков (CPU, memory, disk, network)
  enable_collectors = ["cpu", "meminfo", "diskstats", "netdev", "stat", "uname"]
}

// 2. Сбор метрик Docker-контейнеров (замена cAdvisor)
prometheus.exporter.cadvisor "docker" {
  // Путь к Docker socket для API-запросов
  docker_host = "unix:///var/run/docker.sock"
}

// 3. Объединение целей сбора
prometheus.scrape "metrics" {
  targets = concat(
    prometheus.exporter.unix.node.targets,
    prometheus.exporter.cadvisor.docker.targets,
  )
  forward_to = [prometheus.remote_write.local.receiver]
}

// 4. Отправка метрик в Prometheus через Remote Write
prometheus.remote_write "local" {
  endpoint {
    url = "http://prometheus:9090/api/v1/write"
    // Для аутентифицированного Prometheus добавьте:
    // basic_auth:
    //   username = "${PROM_USER}"
    //   password = "${PROM_PASS}"
  }
  // Очередь для надежной доставки при перебоях сети
  queue_config {
    capacity = 10000
    max_shards = 200
  }
}

// 5. Диагностика: экспорт метрик самого Alloy
prometheus.exporter.self "alloy_self" {}

prometheus.scrape "alloy_self" {
  targets = prometheus.exporter.self.alloy_self.targets
  forward_to = [prometheus.remote_write.local.receiver]
}
```

> **Теория:** Компонент `forward_to` создает явный Directed Acyclic Graph (DAG). Это позволяет трассировать потоки данных и обеспечивает детерминированное обновление конфигурации без перезагрузки агента.

### Сценарий 5: Автоматическая настройка источников данных

Файл `grafana/provisioning/datasources/datasources.yaml` гарантирует наличие Prometheus при первом входе. Grafana сканирует директорию `/etc/grafana/provisioning` при старте и применяет конфигурации автоматически.

```yaml
# monitoring-stack/grafana/provisioning/datasources/datasources.yaml

apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    access: proxy
    isDefault: true
    jsonData:
      httpMethod: POST
      prometheusType: Prometheus
      timeInterval: "15s"
      queryTimeout: "60s"
    secureJsonData:
      # Для базовой аутентификации раскомментируйте:
      # basicAuthPassword: "${PROM_PASSWORD}"
    editable: false
```

> **Важно:** Параметр `editable: false` гарантирует, что источник данных не будет случайно изменен через интерфейс, что соответствует принципам GitOps.

### Сценарий 6: Провиженинг дашбордов

Для автоматического импорта дашбордов создайте файл-провайдер:

```yaml
# monitoring-stack/grafana/provisioning/dashboards/dashboards.yaml

apiVersion: 1

providers:
  - name: 'System-Monitoring'
    orgId: 1
    folder: 'Infrastructure'
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    allowUiUpdates: false
    options:
      path: /etc/grafana/provisioning/dashboards/default
      foldersFromFilesStructure: true
```

Поместите JSON-модели дашбордов в каталог `grafana/provisioning/dashboards/default/`. UID каждого дашборда должен быть жестко задан в JSON для избежания дублирования при перезапуске.

### Сценарий 7: Запуск и валидация

#### Шаг 1: Инициализация каталогов

```bash
mkdir -p monitoring-stack/{alloy,prometheus,grafana/provisioning/{datasources,dashboards/default}}
cd monitoring-stack
```

Ожидаемый вывод: каталоги созданы, `ls` показывает структуру.

#### Шаг 2: Развертывание стека

```bash
docker compose up -d
```

Ожидаемый вывод:
```text
✔ Network monitoring-stack_observer-net  Created
✔ Container monitoring-prometheus         Started
✔ Container monitoring-alloy              Started
✔ Container monitoring-grafana            Started
```

#### Шаг 3: Проверка статуса сервисов

```bash
docker compose ps
```

Ожидаемый вывод (все статусы `Up (healthy)` или `Up`):
```text
NAME                     SERVICE          STATUS
monitoring-grafana       grafana          Up (healthy)
monitoring-alloy         alloy            Up (healthy)
monitoring-prometheus    prometheus       Up (healthy)
```

#### Шаг 4: Проверка здоровья компонентов

```bash
# Prometheus targets (должны отображаться alloy и prometheus)
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health}'
```

Ожидаемый вывод:
```json
{"job": "alloy", "health": "up"}
{"job": "prometheus", "health": "up"}
```

```bash
# Grafana health API
curl -s http://localhost:3000/api/health | jq .
```

Ожидаемый вывод: `{"database": "ok", "version": "13.1.3"}`

```bash
# Alloy Debug UI
curl -s http://localhost:12345/health | jq .
```

Ожидаемый вывод: `{"status": "healthy"}`

#### Шаг 5: Первый вход в Grafana

1. Откройте браузер: `http://localhost:3000`
2. Логин: `admin`
3. Пароль: значение из `.env` (по умолчанию `admin`)
4. После входа перейдите в **Connections → Data sources** — должен быть автоматически подключен источник `Prometheus`.

## Безопасность и эксплуатация

### Чек-лист безопасности

| Пункт | Описание |
| :--- | :--- |
| **Non-Root User** | В Grafana всегда используйте `user: "472:472"`. Для bind mounts выполните `chown -R 472:472 ./grafana` перед запуском. |
| **Секреты** | Используйте `.env` файл или внешние секреты (Docker Secrets, Vault). Никогда не храните пароли в `compose.yml`. |
| **Read-Only монтирования** | Конфигурационные файлы монтируются с флагом `:ro`. Это предотвращает случайное изменение изнутри контейнера. |
| **Ресурсные лимиты** | Ограничивайте потребление памяти через `deploy.resources.limits`, чтобы Grafana или Prometheus не «уронили» хост при всплеске нагрузки. |
| **Network Isolation** | Пробрасывайте на хост только порт Grafana (3000) и Alloy Debug UI (12345). Остальные сервисы должны общаться только внутри сети `observer-net`. |
| **Привилегии Alloy** | `privileged: true` и `pid: host` требуются для сбора системных метрик, но расширяют атакованую поверхность. Используйте только в доверенных сетях. |
| **Валидация конфига** | Перед запуском выполните `docker compose config` для проверки синтаксиса и итогового YAML. |

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Permission Denied на томах** | Неверный владелец файлов на хосте | `sudo chown -R 472:472 ./grafana` |
| **Alloy не видит контейнеры** | Нет доступа к `docker.sock` | Проверьте монтирование сокета и права Alloy (`getent group docker`) |
| **Prometheus не принимает данные** | Не включен Remote Write/OTLP | Проверьте флаги в `command` сервиса `prometheus` |
| **Grafana возвращает 502** | База еще инициализируется | Увеличьте `start_period` в healthcheck (особенно на медленных дисках) |
| **Стек не стартует** | Ошибка в `.env` или YAML | `docker compose config` для проверки итогового файла; `docker compose logs grafana` для деталей |
| **Alloy OOM** | Нет лимитов или слишком много целей | Добавьте `deploy.resources.limits.memory`; проверьте количество контейнеров на хосте |
| **Grafana Login Fail** | Неверный пароль в `.env` | Сбросьте пароль через переменную окружения или удалите том `grafana_data` (данные потеряются) |
| **Prometheus OOM** | Нет `--auto-gomemlimit` или лимитов | Убедитесь, что флаг `--auto-gomemlimit` присутствует и `deploy.resources.limits.memory >= 2G` |

### Рекомендации по эксплуатации и очистке

| Действие | Команда / Метод |
| :--- | :--- |
| **Запуск стека** | `docker compose up -d` |
| **Остановка без удаления данных** | `docker compose down` |
| **Остановка с очисткой томов** | `docker compose down -v` (удаляет все тома с данными) |
| **Перезапуск одного сервиса** | `docker compose restart grafana` |
| **Просмотр логов** | `docker compose logs -f grafana` |
| **Проверка конфига** | `docker compose config` (валидация YAML) |
| **Проверка Prometheus** | `docker exec prometheus promtool check config /etc/prometheus/prometheus.yml` |
| **Очистка неиспользуемых образов** | `docker image prune -a` |
| **Резервное копирование данных** | `docker run --rm -v monitoring-stack_grafana_data:/data -v /backup:/backup alpine tar czf /backup/grafana.tar.gz /data` |

### Граничные случаи и ограничения

1. **WSL2 и файловые системы:** На Windows с WSL2 избегайте размещения `monitoring-stack` на примонтированных дисках (например, `/mnt/c/`). Резкое снижение производительности IOPS приведет к деградации Prometheus и Grafana. Используйте каталоги внутри WSL2 (`~/monitoring-stack`).

2. **Синхронизация времени:** Разница во времени между хостами более 500 мс в HA-кластерах гарантированно приводит к дублированию алертов. Используйте NTP/Chrony.

3. **Остановка Alloy:** При остановке контейнера Alloy данные в WAL сохраняются. Однако при удалении тома `alloy_data` неподтвержденные метрики теряются.

4. **Grafana и SQLite:** При интенсивной нагрузке (множество одновременных пользователей или частые обновления дашбордов) SQLite может стать узким местом. Переход на PostgreSQL решает проблему, но требует изменения конфигурации и миграции данных. Подробная пошаговая инструкция — в [Обновление и миграция Grafana](../grafana_upgrade_migration.md).

5. **Docker Desktop Resource Limits:** На macOS и Windows Docker Desktop по умолчанию выделяет только 2 GB RAM. Для стека требуется минимум 4 GB. Настройте лимиты в Docker Desktop → Settings → Resources.

6. **SELinux/AppArmor:** На RHEL-подобных системах с включенным SELinux может потребоваться добавить контекст `:z` к bind mounts: `- ./grafana:/etc/grafana:ro,z`.

## Дополнительная информация

**См. также:**

*   [Провиженинг Grafana (подробно)](../grafana_provisioning.md) — декларативное управление дашбордами и плагинами.
*   [Высокая доступность Grafana](../high_availability.md) — развертывание с внешней БД и Redis.
*   [Loki в Docker Compose](../../Loki/Docker_Compose/loki_docker_compose_setup.md) — расширение стека сбором логов.
