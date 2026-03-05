# Настройка Loki с помощью Docker Compose

## Определения

**[Loki](loki_overview.md)** — это система агрегации логов, разработанная Grafana Labs. Она индексирует только метаданные (метки), а не полный текст логов, что делает ее экономичной и быстрой для большинства задач мониторинга.

## Основные концепции

Для полноценного сбора логов в Docker с использованием Loki требуется три компонента:

| Компонент | Назначение | Образ / Примечание |
| :--- | :--- | :--- |
| **Loki** | Сервер для приема, хранения и индексации логов | `grafana/loki` |
| **Promtail** | Агент для сбора логов с хоста и контейнеров | `grafana/promtail` ⚠️ Deprecated |
| **Grafana** | Визуализация и запросы (LogQL) | `grafana/grafana` |
| **Alloy** | Универсальный агент (альтернатива Promtail) | `grafana/alloy` ✅ Рекомендовано |

> **Важно:** Без агента-сборщика (Promtail/Alloy) логи не будут попадать в Loki. Данная заметка описывает настройку сервисов `loki`, `promtail` и `grafana`. Для настройки Alloy см. [Grafana Alloy](../Grafana/grafana_alloy_overview.md).

## Практические сценарии

### 1. Конфигурация Docker Compose

Добавим сервисы `loki`, `promtail` и `grafana` в основной файл `docker-compose.yml` вашего стека мониторинга.

#### docker-compose.yml

```yaml
# monitoring/docker-compose.yml

version: '3.8'

services:
  loki:
    image: grafana/loki:3.0.0  # Фиксируем версию для production
    container_name: ${PROJECT_NAME:-monitoring}-loki
    ports:
      - "3100:3100"
    command: -config.file=/etc/loki/local-config.yaml
    volumes:
      - loki_data:/loki
    restart: always
    networks:
      - monitoring

  promtail:
    image: grafana/promtail:3.0.0  # Фиксируем версию
    container_name: ${PROJECT_NAME:-monitoring}-promtail
    volumes:
      - /var/log:/var/log:ro           # Логи хоста
      - /var/lib/docker/containers:/var/lib/docker/containers:ro  # Логи контейнеров
      - promtail_config:/etc/promtail  # Конфигурация
    command: -config.file=/etc/promtail/config.yml
    restart: always
    networks:
      - monitoring
    depends_on:
      - loki

  grafana:
    image: grafana/grafana:11.0.0  # Фиксируем версию
    container_name: ${PROJECT_NAME:-monitoring}-grafana
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro  # Provisioning datasource
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=admin  # Смените на надежный пароль!
    restart: always
    networks:
      - monitoring
    depends_on:
      - loki

volumes:
  loki_data:
  grafana_data:
  promtail_config:

networks:
  monitoring:
    driver: bridge
```

**Ключевые параметры:**

| Параметр | Описание |
| :--- | :--- |
| **`image: grafana/loki:3.0.0`** | Фиксированная версия для production (избегайте `latest`) |
| **`volumes: loki_data`** | Персистентное хранилище для Loki (логи не потеряются при перезапуске) |
| **`/var/log:/var/log:ro`** | Доступ Promtail к системным логам хоста |
| **`/var/lib/docker/containers`** | Доступ к логам контейнеров Docker |
| **`./grafana/provisioning`** | Автоматическая настройка datasource Loki в Grafana |

#### datasources.yaml для Grafana

Чтобы Grafana могла запрашивать логи из Loki, необходимо добавить Loki как источник данных через провиженинг.

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

**Параметры:**

| Параметр | Описание |
| :--- | :--- |
| **`type: loki`** | Указывает на тип источника данных |
| **`url: http://loki:3100`** | Адрес сервиса Loki в Docker-сети |
| **`access: proxy`** | Запросы через бэкенд Grafana (рекомендуется) |
| **`editable: false`** | Запрет редактирования через UI (управляется кодом) |
| **`isDefault: true`** | Loki как источник по умолчанию для Explore |

### 2. Конфигурация Promtail

Promtail требует отдельной конфигурации для сбора логов.

#### config.yml для Promtail

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
  # Логи контейнеров Docker
  - job_name: containers
    static_configs:
      - targets:
          - localhost
        labels:
          job: container_logs
          __path__: /var/lib/docker/containers/*/*-json.log

    # Парсинг JSON-логов Docker
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

  # Системные логи (syslog)
  - job_name: syslog
    static_configs:
      - targets:
          - localhost
        labels:
          job: syslog
          __path__: /var/log/syslog

  # Логи приложений
  - job_name: app_logs
    static_configs:
      - targets:
          - localhost
        labels:
          job: app
          __path__: /var/log/myapp/*.log
```

**Ключевые секции:**

| Секция | Назначение |
| :--- | :--- |
| **`clients`** | Адрес Loki для отправки логов |
| **`positions`** | Файл для отслеживания прочитанных позиций (избежание дубликатов) |
| **`scrape_configs`** | Источники логов (контейнеры, системные, приложения) |
| **`pipeline_stages`** | Парсинг и обогащение логов метаданными |

> **Примечание:** Для Kubernetes используется другая конфигурация с фильтром `kubernetes`. См. [loki_stack_setup_guide.md](./loki_stack_setup_guide.md).

### 3. Запуск и проверка

1. Создайте структуру директорий:

   ```bash
   mkdir -p monitoring/grafana/provisioning/datasources
   mkdir -p monitoring/promtail
   ```

2. Разместите файлы конфигурации:
   - `monitoring/docker-compose.yml`
   - `monitoring/grafana/provisioning/datasources/datasources.yaml`
   - `monitoring/promtail/config.yml`

3. Запустите стек:

   ```bash
   cd monitoring
   docker-compose up -d
   ```

4. Проверьте статус контейнеров:

   ```bash
   docker-compose ps
   # или
   docker ps --filter "name=monitoring"
   ```

5. Проверьте логи Loki:

   ```bash
   docker-compose logs loki
   ```

6. Откройте Grafana в браузере: `http://localhost:3000`
   - Логин: `admin`
   - Пароль: `admin` (или тот, что указан в `GF_SECURITY_ADMIN_PASSWORD`)

7. Перейдите в **Explore** → выберите источник данных **Loki** → выполните запрос `{}` для проверки доступности.

### 4. Альтернатива: Grafana Alloy вместо Promtail

Для новых развертываний рекомендуется использовать **Grafana Alloy** вместо Promtail.

#### docker-compose.yml с Alloy

```yaml
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
```

#### config.alloy для Alloy

```alloy
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

> **Подробнее:** [Grafana Alloy](../Grafana/grafana_alloy_overview.md) — полный обзор и руководство по миграции.

## Дополнительная информация

### Постоянное хранилище (Persistence)

В базовой конфигурации выше используются Docker volumes (`loki_data`, `grafana_data`), что обеспечивает **персистентность данных** при перезапуске контейнеров.

Для production-окружения рассмотрите:

| Тип хранилища | Описание | Пример |
| :--- | :--- | :--- |
| **Файловая система** | Простой вариант для тестовых сред | `directory: /loki/chunks` |
| **S3-совместимое** | Масштабируемое хранилище для production | MinIO, Ceph, AWS S3, Yandex Object Storage |
| **GCS** | Google Cloud Storage | Для GCP-окружений |

> **Конфигурация S3:** [loki_overview.md](./loki_overview.md#конфигурация) — пример настройки хранения в S3.

### Troubleshooting

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Loki не принимает логи** | Неправильный URL в Promtail | Проверьте `clients.url` в config.yml |
| **Дубликаты логов** | Сбой positions-файла | Удалите `/tmp/positions.yaml` и перезапустите Promtail |
| **Grafana не видит Loki** | Проблема с сетью Docker | Убедитесь, что сервисы в одной сети (`networks: - monitoring`) |
| **413 Request Entity Too Large** | Превышен размер батча | Уменьшите `batch_size` в Promtail или увеличьте лимит в Loki |

### Дополнительные ресурсы

- **[loki_overview.md](./loki_overview.md)** — базовые концепции и архитектура Loki
- **[loki_stack_setup_guide.md](./loki_stack_setup_guide.md)** — развертывание в Kubernetes
- **[fluentbit_integration.md](./fluentbit_integration.md)** — интеграция Fluent Bit вместо Promtail
- **[Loki Docker Driver](../Docker/Docker_logs/loki_logging_driver_setup.md)** — отправка логов напрямую из Docker
- **[Grafana Alloy](../Grafana/grafana_alloy_overview.md)** — рекомендуемый агент для новых развертываний
