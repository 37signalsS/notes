# Практическая настройка Loki в Docker Compose

## Определения

**Loki** — система агрегации логов от Grafana Labs, индексирующая только метаданные (метки), а не полный текст логов. Подробная архитектура: [loki_overview.md](../loki_overview.md).

**Docker Compose** — инструмент для определения и запуска многоконтейнерных Docker-приложений с помощью одного YAML (YAML Ain't Markup Language) файла.

**UI (User Interface)** — пользовательский интерфейс для взаимодействия с системой.

## Основные концепции

Для полноценного сбора логов в Docker с использованием Loki требуется три компонента:

| Компонент | Назначение | Образ / Примечание |
| :--- | :--- | :--- |
| **Loki** | Сервер для приема, хранения и индексации логов | `grafana/loki` |
| **Promtail** | Агент для сбора логов с хоста и контейнеров | `grafana/promtail` (Deprecated) |
| **Grafana** | Визуализация и запросы (LogQL) | `grafana/grafana` |
| **Alloy** | Универсальный агент (альтернатива Promtail) | `grafana/alloy` (Рекомендовано) |

Без агента-сборщика (Promtail/Alloy) логи не будут попадать в Loki.

> **Важно:** Promtail в статусе deprecated, для новых развёртываний рекомендуется Grafana Alloy. Для настройки Alloy см. [Grafana Alloy](../../Grafana/grafana_alloy_overview.md).

## Практические сценарии

### Конфигурация Docker Compose

Сервисы `loki`, `promtail` (legacy) или `alloy` (рекомендуется) и `grafana` добавляются в основной файл `docker-compose.yml` стека мониторинга. Ниже приведен пример с использованием **Grafana Alloy** (рекомендуемый агент).

```yaml
# monitoring/docker-compose.yml

version: '3.8'

services:
  loki:
    image: grafana/loki:3.0.0
    container_name: ${PROJECT_NAME:-monitoring}-loki
    ports:
      - "3100:3100"
    command: -config.file=/etc/loki/local-config.yaml
    volumes:
      - loki_data:/loki
    restart: always
    networks:
      - monitoring

  alloy:
    image: grafana/alloy:v1.0.0
    container_name: ${PROJECT_NAME:-monitoring}-alloy
    volumes:
      - /var/log:/var/log:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - ./alloy/config.alloy:/etc/alloy/config.alloy:ro
    command: run --server.http.listen-addr=0.0.0.0:12345 /etc/alloy/config.alloy
    restart: always
    networks:
      - monitoring
    depends_on:
      - loki

  grafana:
    image: grafana/grafana:11.0.0
    container_name: ${PROJECT_NAME:-monitoring}-grafana
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=admin
    restart: always
    networks:
      - monitoring
    depends_on:
      - loki

volumes:
  loki_data:
  grafana_data:

networks:
  monitoring:
    driver: bridge
```

### Ключевые параметры

| Параметр | Описание |
| :--- | :--- |
| **`image: grafana/loki:3.0.0`** | Фиксированная версия для production |
| **`volumes: loki_data`** | Персистентное хранилище для Loki |
| **`/var/log:/var/log:ro`** | Доступ Alloy к системным логам хоста |
| **`/var/lib/docker/containers`** | Доступ к логам контейнеров Docker |
| **`./grafana/provisioning`** | Автоматическая настройка datasource Loki в Grafana |

### datasources.yaml для Grafana

Grafana требует настройки источника данных Loki через провиженинг.

```yaml
# monitoring/grafana/provisioning/datasources/datasources.yaml

apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    isDefault: false
    editable: true

  - name: Loki
    type: loki
    url: http://loki:3100
    access: proxy
    basicAuth: false
    editable: false
    version: 1
    isDefault: true
```

| Параметр | Описание |
| :--- | :--- |
| **`type: loki`** | Тип источника данных |
| **`url: http://loki:3100`** | Адрес Loki в Docker-сети (URL — Uniform Resource Locator) |
| **`access: proxy`** | Запросы через бэкенд Grafana |
| **`editable: false`** | Запрет редактирования через UI |
| **`isDefault: true`** | Loki как источник по умолчанию |

### Конфигурация Grafana Alloy (рекомендуется)

Grafana Alloy использует язык River для настройки пайплайнов сбора и отправки логов.

```alloy
# monitoring/alloy/config.alloy

// Сбор логов контейнеров
loki.source.file "containers" {
  path    = "/var/lib/docker/containers/*/*-json.log"
  labels  = { job = "container_logs" }
  forward = [loki.write.default.receiver]
}

// Отправка в Loki
loki.write "default" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
```

### Конфигурация Promtail (legacy)

Если используется Promtail, конфигурация сбора логов выполняется через YAML.

```yaml
# monitoring/promtail/config.yml

server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: containers
    static_configs:
      - targets:
          - localhost
        labels:
          job: container_logs
          __path__: /var/lib/docker/containers/*/*-json.log

    pipeline_stages:
      - json:
          expressions:
            output: log
            stream: stream
            attrs:
      - json:
          expressions:
            tag:
          source: attrs
      - regex:
          expression: (?P<container_name>^(?:[^_]+_){3}))
          source: tag
      - labels:
          - container_name
          - stream

  - job_name: syslog
    static_configs:
      - targets:
          - localhost
        labels:
          job: syslog
          __path__: /var/log/syslog

  - job_name: app_logs
    static_configs:
      - targets:
          - localhost
        labels:
          job: app
          __path__: /var/log/myapp/*.log
```

| Секция | Назначение |
| :--- | :--- |
| **`clients`** | Адрес Loki для отправки логов |
| **`positions`** | Файл отслеживания прочитанных позиций (только Promtail) |
| **`scrape_configs`** | Источники логов (контейнеры, системные, приложения) |
| **`pipeline_stages`** | Парсинг и обогащение логов метаданными |

Для Kubernetes используется другая конфигурация с фильтром `kubernetes`. См. [loki_installation.md](../loki_stack_setup/loki_installation.md).

### Запуск и проверка

1. Создание структуры директорий:

```bash
mkdir -p monitoring/grafana/provisioning/datasources
mkdir -p monitoring/alloy  # Или monitoring/promtail
```

1. Размещение файлов конфигурации:
   - `monitoring/docker-compose.yml`
   - `monitoring/grafana/provisioning/datasources/datasources.yaml`
   - `monitoring/alloy/config.alloy` (или `monitoring/promtail/config.yml`)

2. Запуск стека:

```bash
cd monitoring
docker-compose up -d
```

1. Проверка статуса контейнеров:

```bash
docker-compose ps
# или
docker ps --filter "name=monitoring"
```

1. Проверка логов Loki:

```bash
docker-compose logs loki
```

1. Проверка в Grafana: откройте `http://localhost:3000`, перейдите в **Explore** → выберите источник **Loki** → выполните запрос `{}`.

### Поиск и устранение неисправностей

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Loki не принимает логи** | Неправильный URL в агенте | Проверьте `clients.url` (Promtail) или `endpoint` (Alloy) |
| **Дубликаты логов** | Сбой positions-файла | Удалите `/tmp/positions.yaml` (Promtail) и перезапустите агента |
| **Grafana не видит Loki** | Проблема с сетью Docker | Убедитесь, что сервисы в одной сети (`networks: - monitoring`) |
| **413 Request Entity Too Large** | Превышен размер батча | Уменьшите размер батча в агенте или увеличьте лимит в Loki |

## Дополнительная информация

Развёртывание в Kubernetes: [loki_installation.md](../loki_stack_setup/loki_installation.md). Рекомендуемый агент для новых развёртываний: [Grafana Alloy](../../Grafana/grafana_alloy_overview.md). Хранилища для production: [loki_overview.md](../loki_overview.md#конфигурация).
