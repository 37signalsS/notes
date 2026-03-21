# Настройка Loki с помощью Docker Compose — Практика

## 1. Конфигурация Docker Compose

Добавим сервисы `loki`, `promtail` и `grafana` в основной файл `docker-compose.yml` вашего стека мониторинга.

### docker-compose.yml

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

### Ключевые параметры

| Параметр | Описание |
| :--- | :--- |
| **`image: grafana/loki:3.0.0`** | Фиксированная версия для production (избегайте `latest`) |
| **`volumes: loki_data`** | Персистентное хранилище для Loki (логи не потеряются при перезапуске) |
| **`/var/log:/var/log:ro`** | Доступ Promtail к системным логам хоста |
| **`/var/lib/docker/containers`** | Доступ к логам контейнеров Docker |
| **`./grafana/provisioning`** | Автоматическая настройка datasource Loki в Grafana |

## 2. datasources.yaml для Grafana

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

### Параметры datasource

| Параметр | Описание |
| :--- | :--- |
| **`type: loki`** | Указывает на тип источника данных |
| **`url: http://loki:3100`** | Адрес сервиса Loki в Docker-сети |
| **`access: proxy`** | Запросы через бэкенд Grafana (рекомендуется) |
| **`editable: false`** | Запрет редактирования через UI (управляется кодом) |
| **`isDefault: true`** | Loki как источник по умолчанию для Explore |

## 3. Конфигурация Promtail

Promtail требует отдельной конфигурации для сбора логов.

### config.yml для Promtail

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

### Ключевые секции

| Секция | Назначение |
| :--- | :--- |
| **`clients`** | Адрес Loki для отправки логов |
| **`positions`** | Файл для отслеживания прочитанных позиций (избежание дубликатов) |
| **`scrape_configs`** | Источники логов (контейнеры, системные, приложения) |
| **`pipeline_stages`** | Парсинг и обогащение логов метаданными |

> **Примечание:** Для Kubernetes используется другая конфигурация с фильтром `kubernetes`. См. [loki_stack_setup_guide.md](../../Loki/loki_overview.md).

## 4. Запуск и проверка

### 4.1. Создание структуры директорий

```bash
mkdir -p monitoring/grafana/provisioning/datasources
mkdir -p monitoring/promtail
```

### 4.2. Размещение файлов конфигурации

- `monitoring/docker-compose.yml`
- `monitoring/grafana/provisioning/datasources/datasources.yaml`
- `monitoring/promtail/config.yml`

### 4.3. Запуск стека

```bash
cd monitoring
docker-compose up -d
```

### 4.4. Проверка статуса контейнеров

```bash
docker-compose ps
# или
docker ps --filter "name=monitoring"
```

### 4.5. Проверка логов Loki

```bash
docker-compose logs loki
```

### 4.6. Проверка в Grafana

1. Откройте Grafana в браузере: `http://localhost:3000`
2. Логин: `admin`
3. Пароль: `admin` (или тот, что указан в `GF_SECURITY_ADMIN_PASSWORD`)
4. Перейдите в **Explore** → выберите источник данных **Loki** → выполните запрос `{}` для проверки доступности.

## Связанные документы

- **[Основные концепции](./loki_docker_concepts.md)** — определения и компоненты
- **[Дополнительные темы](./loki_docker_advanced.md)** — Alloy, troubleshooting, хранение
- **[Grafana Alloy](../../Grafana/grafana_alloy_overview.md)** — рекомендуемый агент для новых развертываний
