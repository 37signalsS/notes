# Настройка Grafana в Docker Compose

**Актуально для:** Grafana 13.2.x / Prometheus 3.15.x / Grafana Alloy 1.20.x (Docker Compose CLI v2.20+ / v5, спецификация Compose)

## Определения

**Grafana** — универсальная open-source платформа для аналитики, мониторинга и интерактивной визуализации данных телеметрии (метрик, логов, трассировок, профилей). Grafana не хранит собираемые данные, а выступает интерфейсом для внешних источников. По умолчанию работает на порту `3000` (протокол HTTP/HTTPS). Управление параметрами сервера осуществляется через файл `grafana.ini` или переменные окружения (формат `GF_<SECTION>_<KEY>`). См. [Обзор Grafana](../grafana_overview.md).

**Docker Compose** — инструмент для декларативного описания и управления многоконтейнерными приложениями. В контексте мониторинга позволяет развернуть полный стек (Grafana + Prometheus + Alloy) одной командой. Актуальными являются версии CLI Compose v2.20+/v5 (плагин к Docker CLI); устаревшая утилита `docker-compose` v1 (Python) признана EOL в июне 2023 года. Подробнее об основах: [Обзор Docker Compose](../../Docker/Docker_compose/docker_compose_overview.md).

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
| **Grafana** | `grafana/grafana` | 13.2.3 | Current (стабильная) |
| **Prometheus** | `prom/prometheus` | 3.15.0 | Поддержка OTLP и Auto-tuning |
| **Grafana Alloy** | `grafana/alloy` | 1.20.1 | Актуальный стандарт сбора телеметрии |

Отдельные экспортеры (Node Exporter, cAdvisor) в стек не включаются: их коллекторы встроены в Alloy (см. [Сценарий 4](#сценарий-4-конфигурация-grafana-alloy-configalloy)).

Информация актуальна на **октябрь 2026 года**.

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
    image: prom/prometheus:v3.15.0
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
      # Включает Admin API (/api/v1/admin/*): снапшоты TSDB для резервного копирования.
      # Расширяет атакованную поверхность (включая delete_series) — отключайте, если бэкапы
      # снимаются иначе (см. Сценарий 9)
      - '--web.enable-admin-api'
      # Auto GOMEMLIMIT: в Prometheus v3 включён по умолчанию (ratio 0.9 от лимита контейнера).
      # Флаг оставлен для наглядности — GOMEMLIMIT подстраивается под 2G из deploy.limits
      - '--auto-gomemlimit'
      # Auto GOMAXPROCS: в v3 включён по умолчанию, потоки Go подстраиваются под CPU quota
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
    image: grafana/alloy:v1.20.1
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
    image: grafana/grafana:13.2.3
    container_name: monitoring-grafana
    # UID/GID 472 — стандартный пользователь Grafana в образе
    user: "472:472"
    restart: unless-stopped
    environment:
      # Пароль администратора (из .env или значение по умолчанию)
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASS:-admin}
      # Отключаем самостоятельную регистрацию пользователей
      - GF_USERS_ALLOW_SIGN_UP=false
      # Каталог конфигураций провиженинга (путь по умолчанию в образе; задан явно для наглядности).
      # Интерполяция ${VAR} в YAML-файлах провиженинга работает автоматически — отдельный флаг не требуется
      - GF_PATHS_PROVISIONING=/etc/grafana/provisioning
      # Разрешает встраивание Grafana в iframe (например, дашборд внутри внешней системы).
      # Ослабляет защиту от clickjacking — отключайте, если встраивание не требуется
      - GF_SECURITY_ALLOW_EMBEDDING=true
    volumes:
      # Named volume: база данных Grafana (дашборды, пользователи)
      - grafana_data:/var/lib/grafana
      # Bind mount: конфигурации провиженинга (read-only)
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    ports:
      # Порт UI Grafana, проброшенный на хост для доступа пользователей
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

Ожидаемый вывод: `{"database": "ok", "version": "13.2.3"}`

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

### Сценарий 8: Правила алертинга и самоконтроль стека

`prometheus.yml` уже ссылается на каталог правил (`rule_files`), но по умолчанию он пуст. Ниже приведены базовые правила самоконтроля стека, работающие на метриках, которые стеку доступны «из коробки»:

- `up` — результат scrape-джобов (`alloy`, `prometheus`);
- `node_*` — метрики хоста, приходящие в Prometheus через `remote_write` из Alloy (встроенный Node Exporter);
- `container_*` — метрики контейнеров из встроенного cAdvisor.

```yaml
# monitoring-stack/prometheus/alerts/stack.yml

groups:
  - name: stack
    rules:
      # Любая цель сбора недоступна (Alloy, Prometheus или сторонний экспортёр)
      - alert: TargetDown
        expr: up == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Цель {{ $labels.instance }} (job={{ $labels.job }}) недоступна"

      # Контейнер устойчиво потребляет более 1.5 GB рабочей памяти
      - alert: HighMemoryContainer
        expr: container_memory_working_set_bytes{image!=""} > 1500000000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Контейнер {{ $labels.name }} потребляет более 1.5 GB памяти"

      # Осталось менее 10% места на корневом разделе хоста
      - alert: HostDiskAlmostFull
        expr: (node_filesystem_avail_bytes{mountpoint="/",fstype!~"tmpfs|overlay"}
               / node_filesystem_size_bytes{mountpoint="/",fstype!~"tmpfs|overlay"}) * 100 < 10
        for: 15m
        labels:
          severity: critical
        annotations:
          summary: "На корневом разделе хоста осталось менее 10% места"
```

После сохранения файла перезапустите Prometheus или перезагрузите конфигурацию через API:

```bash
# Hot reload конфигурации и правил (работает благодаря --web.enable-lifecycle)
curl -s -X POST http://localhost:9090/-/reload

# Проверка: активные правила
curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[].rules[]?.name'
```

> **Важно:** Правила срабатывают в Prometheus (UI на порту `9090`, вкладка Alerts) даже без Alertmanager, но доставка уведомлений (email, Slack, PagerDuty, webhook) требует Alertmanager. Полный стек с Alertmanager описан в [Конфигурация Docker Compose для Prometheus](../../Prometheus/installation/docker_stack/docker-compose_config.md).

### Сценарий 9: Резервное копирование и восстановление

Резервному копированию подлежат два компонента с персистентными данными: TSDB Prometheus и база Grafana. Конфигурации (`compose.yml`, `prometheus.yml`, `config.alloy`, провиженинг) хранятся в Git и копий не требуют.

#### Снимок TSDB Prometheus (консистентная точка)

Требует флага `--web.enable-admin-api` (уже включён в `compose.yml`). Снимок создаётся через hard-link и почти мгновенен, после чего архивируется из именованного тома.

```bash
# 1) Создание снимка; ответ содержит имя каталога снимка
SNAP=$(curl -s -X POST http://localhost:9090/api/v1/admin/tsdb/snapshot | jq -r '.data.name')
echo "$SNAP"   # → 20261011T120000Z-8f3b2c1d...

# 2) Упаковка снимка из тома prometheus_data в /backup
docker run --rm \
  -v monitoring-stack_prometheus_data:/prometheus \
  -v /backup:/backup \
  alpine tar czf /backup/prom-${SNAP}.tar.gz -C /prometheus/snapshots "${SNAP}"

# 3) Удаление снимка из тома (архив уже создан)
docker run --rm \
  -v monitoring-stack_prometheus_data:/prometheus \
  alpine rm -rf /prometheus/snapshots/"${SNAP}"
```

#### Полная резервная копия тома

Самый надёжный вариант для одиночной инсталляции — остановка сервиса и снятие копии тома целиком. Это же покрывает и снимок.

```bash
# Prometheus
docker compose stop prometheus
docker run --rm -v monitoring-stack_prometheus_data:/prometheus -v /backup:/backup \
  alpine tar czf /backup/prom-full.tar.gz -C /prometheus .
docker compose start prometheus

# Grafana (см. детали в [Резервное копирование Grafana](../grafana_backup_restore.md))
docker compose stop grafana
docker run --rm -v monitoring-stack_grafana_data:/var/lib/grafana -v /backup:/backup \
  alpine tar czf /backup/grafana-full.tar.gz -C /var/lib/grafana .
docker compose start grafana
```

> **Примечание:** Имена томов привязаны к имени проекта Docker Compose (по умолчанию — имя каталога `monitoring-stack`). Если задан `COMPOSE_PROJECT_NAME`, имя тома изменится.

#### Восстановление

```bash
# Останавливаем сервис, очищаем том, распаковываем архив, запускаем снова
docker compose stop prometheus
docker run --rm -v monitoring-stack_prometheus_data:/prometheus -v /backup:/backup \
  alpine sh -c 'rm -rf /prometheus/* && tar xzf /backup/prom-full.tar.gz -C /prometheus'
docker compose start prometheus
```

Для Grafana процедура аналогична (том `monitoring-stack_grafana_data`). Перед восстановлением обязательно убедитесь, что версия Grafana в архиве и в текущем образе совместима — миграции БД не откатываются.

#### Автоматизация

Для регулярного бэкапа разместите шаги снимка в cron/systemd-timer. Срок хранения архивов ограничивайте, например, `find /backup -name 'prom-*.tar.gz' -mtime +14 -delete`.

### Сценарий 10: Обновление версий стека и откат

Перед обновлением сделайте резервную копию томов (Сценарий 9) — Grafana при старте выполняет миграции БД, которые не подлежат откату. Подробнее: [Обновление и миграция Grafana](../grafana_upgrade_migration.md).

```bash
# 1) Текущие образы
docker compose images

# 2) Обновляйте теги в compose.yml (только фиксированные версии) и фиксируйте в Git

# 3) Загрузка образов
docker compose pull

# 4) Применение: пересоздаются только контейнеры с изменёнными образами
docker compose up -d

# 5) Проверка
docker compose ps
curl -s http://localhost:9090/api/v1/status/buildinfo | jq '.data.version'
curl -s http://localhost:3000/api/health | jq .
```

Откат в случае проблем:

```bash
# Возврат предыдущих версий из Git и пересоздание контейнеров
git checkout <предыдущий-коммит> -- compose.yml
docker compose up -d
```

Для воспроизводимости и защиты от подмены образов закрепляйте digest вместо плавающего тега:

```bash
docker buildx imagetools inspect grafana/grafana:13.2.3
# в compose.yml:
#   image: grafana/grafana:13.2.3@sha256:<digest>
```

> **Практика:** Проверяйте совместимость связки Grafana / Prometheus / Alloy перед обновлением. Alloy и Prometheus обычно обновляются независимо, Grafana может требовать миграций БД; протокольная совместимость `remote_write` и scrape-протоколов сохраняется, но читайте release notes каждой мажорной версии.

## Безопасность

### Основные принципы безопасности

При развёртывании стека мониторинга необходимо придерживаться принципа наименьших привилегий. Ниже приведён чек-лист, позволяющий снизить атакованную поверхность без потери функциональности.

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
| **Admin API Prometheus** | Флаг `--web.enable-admin-api` нужен для снапшотов TSDB, но включает и `delete_series`. Отключайте, если бэкапы снимаются без API (том целиком). |
| **Embedding Grafana** | `GF_SECURITY_ALLOW_EMBEDDING=true` разрешает встраивание в iframe и ослабляет защиту от clickjacking. Включайте только при реальной необходимости. |

## Операции и команды

Для удобства ежедневной эксплуатации ниже собраны основные команды работы со стеком.

| Действие | Команда / Метод |
| :--- | :--- |
| **Запуск стека** | `docker compose up -d` |
| **Остановка без удаления данных** | `docker compose down` |
| **Остановка с очисткой томов** | `docker compose down -v` (удаляет все тома с данными) |
| **Перезапуск одного сервиса** | `docker compose restart grafana` |
| **Просмотр логов** | `docker compose logs -f grafana` |
| **Проверка конфига** | `docker compose config` (валидация YAML) |
| **Просмотр финальных переменных** | `docker compose config --environment` |
| **Проверка Prometheus** | `docker exec monitoring-prometheus promtool check config /etc/prometheus/prometheus.yml` |
| **Hot reload конфигурации** | `curl -s -X POST http://localhost:9090/-/reload` |
| **Снимок TSDB (бэкап)** | `curl -s -X POST http://localhost:9090/api/v1/admin/tsdb/snapshot` (требует `--web.enable-admin-api`) |
| **Использование диска** | `docker system df`; рост томов: `docker system df -v` |
| **Очистка неиспользуемых образов** | `docker image prune -a` |
| **Резервное копирование данных** | `docker run --rm -v monitoring-stack_grafana_data:/data -v /backup:/backup alpine tar czf /backup/grafana.tar.gz /data` |

## Troubleshooting

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



## Best Practices

### Граничные случаи и ограничения

1. **WSL2 и файловые системы:** На Windows с WSL2 избегайте размещения `monitoring-stack` на примонтированных дисках (например, `/mnt/c/`). Резкое снижение производительности IOPS приведет к деградации Prometheus и Grafana. Используйте каталоги внутри WSL2 (`~/monitoring-stack`).

2. **Синхронизация времени:** Разница во времени между хостами более 500 мс в HA-кластерах гарантированно приводит к дублированию алертов. Используйте NTP/Chrony.

3. **Остановка Alloy:** При остановке контейнера Alloy данные в WAL сохраняются. Однако при удалении тома `alloy_data` неподтвержденные метрики теряются.

4. **Grafana и SQLite:** При интенсивной нагрузке (множество одновременных пользователей или частые обновления дашбордов) SQLite может стать узким местом. Переход на PostgreSQL решает проблему, но требует изменения конфигурации и миграции данных. Подробная пошаговая инструкция — в [Обновление и миграция Grafana](../grafana_upgrade_migration.md).

5. **Docker Desktop Resource Limits:** На macOS и Windows Docker Desktop по умолчанию выделяет только 2 GB RAM. Для стека требуется минимум 4 GB. Настройте лимиты в Docker Desktop → Settings → Resources.

6. **SELinux/AppArmor:** На RHEL-подобных системах с включенным SELinux может потребоваться добавить контекст `:z` к bind mounts: `- ./grafana:/etc/grafana:ro,z`.

### Рекомендации

- Всегда используйте именованные тома для персистентных данных — это гарантирует сохранность TSDB и базы Grafana при пересоздании контейнеров.
- Придерживайтесь подхода Infrastructure as Code: храните конфигурации в Git, не вносите изменения через UI (за исключением временной отладки).
- Старайтесь ограничивать внешний доступ только к Grafana (порт 3000). Debug UI Alloy (12345) должен быть доступен только с локального хоста.
- Фиксируйте полные версии образов (например, `13.2.3`, а не `latest`); для supply chain — закрепляйте digest (`image@sha256:...`).
- Перед изменением версии образов проверяйте совместимость компонентов между Grafana, Prometheus и Alloy (Сценарий 10).
- Регулярно выполняйте резервное копирование томов Grafana и Prometheus согласно плану восстановления и проверяйте процедуру восстановления на тестовом хосте (Сценарий 9).
- Отключайте Admin API Prometheus и embedding Grafana, если соответствующие функции не используются — это снижает атакованную поверхность.

## Дополнительная информация

**См. также:**

*   [Обзор Grafana](../grafana_overview.md) — основные концепции и архитектура.
*   [Провиженинг Grafana (подробно)](../grafana_provisioning.md) — декларативное управление дашбордами и плагинами.
*   [Резервное копирование и восстановление Grafana](../grafana_backup_restore.md) — практика работы с базой и файлами Grafana.
*   [Высокая доступность Grafana](../high_availability.md) — развертывание с внешней БД и Redis.
*   [Обновление и миграция Grafana](../grafana_upgrade_migration.md) — обновление и миграция между версиями.
*   [Grafana Alloy: Обзор](../grafana_alloy_overview.md) — сбор телеметрии через Alloy.
*   [Конфигурация Docker Compose для стека мониторинга](../../Prometheus/installation/docker_stack/docker-compose_config.md) — полный стек с Alertmanager и экспортерами.
*   [Loki в Docker Compose](../../Loki/Docker_Compose/loki_docker_compose_setup.md) — расширение стека сбором логов.
