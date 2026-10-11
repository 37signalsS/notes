# Podman: Централизованное логирование

## Определения

**Централизованное логирование** — архитектура сбора, агрегации и хранения логов из всех контейнеров Podman в единой системе для обеспечения видимости, поиска и анализа.

**journald** — систем службы journal (systemd), которая автоматически собирает stdout/stderr контейнеров Podman. Является лог-драйвером по умолчанию для rootless Podman.

**Fluentd** — агент сбора логов (log collector) с плагинной архитектурой для маршрутизации, трансформации и доставки логов в различные хранилища (ELK, Loki, S3).

**Fluent Bit** — облегчённый агент сбора логов (аналог Fluentd, но легче и быстрее), оптимизированный для контейнерных сред.

**Grafana Loki** — индексируемое хранилище логов, индексирующее только метаданные (labels), а не содержимое логов. Оптимизировано для Kubernetes/Podman.

**ELK Stack** — стек Elasticsearch + Logstash + Kibana для полнотекстового индексирования и поиска логов.

**Log driver** — плагин, определяющий куда и как Podman отправляет stdout/stderr контейнера (journald, fluentd, loki, syslog).

---

## Теоретический блок

### Архитектура логирования Podman

```
┌─────────────────────────────────────────────────────────────┐
│                    Целевая система                          │
│         (Elasticsearch, Loki, S3, Syslog server)            │
└──────────────────────▲──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│                    Агент сбора логов                         │
│           (Fluentd / Fluent Bit / Vector / Alloy)           │
└───┬──────────────┬──────────────────────┬───────────────────┘
    │ read files   │ read journald        │ HTTP push
┌───▼────┐   ┌─────▼──────┐   ┌──────────▼──────────┐
│Log files│   │ journald   │   │ Log driver          │
│on disk  │   │ (systemd)  │   │ (fluentd/loki/      │
│         │   │            │   │  syslog)            │
└────────┘   └────────────┘   └─────────────────────┘
    │              │                    │
┌───▼──────────────▼────────────────────▼─────────────────────┐
│                  Podman контейнеры                           │
│              (stdout → log driver → destination)            │
└─────────────────────────────────────────────────────────────┘
```

### Методы сбора логов Podman

| Метод | Описание | Преимущества | Недостатки |
|---|---|---|---|
| **podman logs CLI** | Чтение локальных логов | Просто, без настройки | Только на хосте |
| **journald** | Сбор через systemd | Автоматически, структурировано | Ограниченный поиск |
| **Log driver (push)** | Прямая отправка по сети | Без агента на хосте | Зависимость от сети |
| **Агентный сбор** | Чтение файлов с диска | Гибкость, fault-tolerance | Дополнительный агент |

### Хранение логов Podman

| Драйвер | По умолчанию | Хранение | Поддержка `podman logs` |
|---|---|---|---|
| `journald` | Да (systemd) | Systemd journal | Да |
| `k8s-file` | Да (без systemd) | `/var/lib/containers/storage/overlay-containers/` | Да |
| `json-file` | Нет | `/var/lib/containers/storage/overlay-containers/` | Да |
| `fluentd` | Нет | На стороне Fluentd | Только при dual logging |
| `loki` | Нет | На стороне Loki | Только при dual logging |
| `syslog` | Нет | На syslog-сервере | Только при dual logging |

---

## Практический блок

### 1. Базовое чтение логов

```bash
# Логи конкретного контейнера
podman logs my-app

# В реальном времени (follow)
podman logs -f my-app

# Последние N строк
podman logs --tail 100 my-app

# С определённого времени
podman logs --since 2024-01-01T10:00:00 my-app

# До определённого времени
podman logs --until 2024-01-01T11:00:00 my-app

# С метками времени
podman logs --timestamps my-app

# Формат для парсинга
podman logs --format "{{.Time}} {{.Tag}} {{.Message}}" my-app
```

### 2. Настройка log driver

#### Глобально (containers.conf)

```toml
# /etc/containers/containers.conf (или ~/.config/containers/containers.conf)
[containers]
log_driver = "journald"
log_size_max = 104857600  # 100 МБ

[engine]
events_logger = "journald"
```

#### Для конкретного контейнера

```bash
# journald
podman run --log-driver=journald my-app:latest

# fluentd
podman run --log-driver=fluentd \
  --log-opt fluentd-address=localhost:24224 \
  --log-opt fluentd-async-connect=true \
  my-app:latest

# loki
podman run --log-driver=loki \
  --log-opt loki-url="http://loki:3100/loki/api/v1/push" \
  my-app:latest

# syslog
podman run --log-driver=syslog \
  --log-opt syslog-address=tcp://syslog-server:514 \
  my-app:latest
```

#### Docker Compose (podman-compose)

```yaml
# docker-compose.yml
version: '3.8'

services:
  my-app:
    image: my-app:latest
    logging:
      driver: fluentd
      options:
        fluentd-address: "localhost:24224"
        fluentd-async-connect: "true"
        fluentd-retry-wait: "1s"
        fluentd-max-retries: "30"
```

### 3. Интеграция с journald

```bash
# Чтение логов Podman через journalctl
journalctl -u podman-my-app.service

# Все логи Podman
journalctl -u "podman*" --no-pager

# Фильтрация по уровню
journalctl -u podman-my-app.service -p err

# В реальном времени
journalctl -u podman-my-app.service -f

# Экспорт в файл
journalctl -u podman-my-app.service --no-pager > /var/log/podman-app.log
```

#### Настройка journalctl для Podman

```ini
# /etc/systemd/journald.conf
[Journal]
SystemMaxUse=2G          # Макс. объём журнала
MaxRetentionSec=30day    # Хранить 30 дней
Compress=yes             # Сжимать старые записи
ForwardToSyslog=yes      # Дублировать в syslog (опционально)
```

```bash
sudo systemctl restart systemd-journald
```

### 4. Деплой Fluent Bit + Loki

```yaml
# docker-compose-fluentbit.yml
version: '3.8'

services:
  loki:
    image: grafana/loki:3.4.2
    container_name: loki
    volumes:
      - ./loki-config.yml:/etc/loki/local-config.yaml
    command: -config.file=/etc/loki/local-config.yaml
    ports:
      - "3100:3100"
    restart: unless-stopped

  fluent-bit:
    image: cr.fluentbit.io/fluent/fluent-bit:3.1
    container_name: fluent-bit
    volumes:
      - ./fluent-bit.conf:/fluent-bit/etc/fluent-bit.conf:ro
      - /var/log:/var/log:ro
      - /var/lib/containers:/var/lib/containers:ro
    depends_on:
      - loki
    restart: unless-stopped

  grafana:
    image: grafana/grafana:13.2.3
    container_name: grafana
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    ports:
      - "3000:3000"
    restart: unless-stopped

volumes:
  grafana_data:
```

#### Конфигурация Fluent Bit

```ini
# fluent-bit.conf
[SERVICE]
    Flush        5
    Log_Level    info
    Parsers_File parsers.conf

# Чтение логов Podman с диска
[INPUT]
    Name              tail
    Path              /var/lib/containers/storage/overlay-containers/*/*-json.log
    Parser            docker
    Tag               podman.*
    Mem_Buf_Limit     5MB
    Refresh_Interval  10

# Чтение journald
[INPUT]
    Name              systemd
    Tag               journal.*
    Systemd_Filter    _SYSTEMD_UNIT=podman*.service

# Парсинг JSON логов
[FILTER]
    Name          parser
    Match         podman.*
    Key_Name      log
    Parser        json

# Добавление метаданных
[FILTER]
    Name          modify
    Match         podman.*
    Add           source podman
    Add           environment production

# Отправка в Loki
[OUTPUT]
    Name          loki
    Match         podman.*
    Url           http://loki:3100/loki/api/v1/push
    Labels        job=podman, source=container
    Label_Keys    $container_name
    Remove_Keys   container_name
    Line_format   json

# Отправка journal в Loki
[OUTPUT]
    Name          loki
    Match         journal.*
    Url           http://loki:3100/loki/api/v1/push
    Labels        job=journal, source=systemd
```

#### Конфигурация парсеров

```ini
# parsers.conf
[PARSER]
    Name        docker
    Format      json
    Time_Key    time
    Time_Format %Y-%m-%dT%H:%M:%S.%L
    Time_Keep   On

[PARSER]
    Name        cri
    Format      regex
    Regex       ^(?<time>[^ ]+) (?<stream>stdout|stderr) (?<log>.*)$
    Time_Key    time
    Time_Format %Y-%m-%dT%H:%M:%S.%L%z
```

### 5. Деплой Fluentd + ELK

```yaml
# docker-compose-fluentd.yml
version: '3.8'

services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.14.0
    container_name: elasticsearch
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
      - "ES_JAVA_OPTS=-Xms512m -Xmx512m"
    volumes:
      - es_data:/usr/share/elasticsearch/data
    ports:
      - "9200:9200"
    restart: unless-stopped

  kibana:
    image: docker.elastic.co/kibana/kibana:8.14.0
    container_name: kibana
    environment:
      - ELASTICSEARCH_HOSTS=http://elasticsearch:9200
    ports:
      - "5601:5601"
    depends_on:
      - elasticsearch
    restart: unless-stopped

  fluentd:
    build:
      context: ./fluentd
      dockerfile: Dockerfile
    container_name: fluentd
    volumes:
      - ./fluentd/conf:/fluentd/etc:ro
      - /var/lib/containers:/var/lib/containers:ro
    ports:
      - "24224:24224"
      - "24224:24224/udp"
    depends_on:
      - elasticsearch
    restart: unless-stopped

volumes:
  es_data:
```

#### Конфигурация Fluentd

```xml
<!-- fluentd/conf/fluent.conf -->
<source>
  @type forward
  port 24224
  bind 0.0.0.0
</source>

<!-- Чтение логов Podman -->
<source>
  @type tail
  path /var/lib/containers/storage/overlay-containers/*/*-json.log
  pos_file /fluentd/pos/podman-logs.pos
  tag podman.*
  <parse>
    @type json
    time_key time
    time_format %Y-%m-%dT%H:%M:%S.%L
  </parse>
</source>

<!-- Фильтрация и обогащение -->
<filter podman.**>
  @type record_transformer
  <record>
    source "podman"
    hostname "#{Socket.gethostname}"
  </record>
</filter>

<!-- Отправка в Elasticsearch -->
<match podman.**>
  @type elasticsearch
  host elasticsearch
  port 9200
  index_name podman-logs
  type_name _doc
  logstash_format true
  logstash_prefix podman-logs
  flush_interval 5s
  <buffer>
    flush_mode interval
    retry_type exponential_backoff
    flush_interval 5s
    chunk_limit_size 2M
    queue_limit_length 32
    retry_max_interval 30
    retry_forever true
  </buffer>
</match>
```

### 6. Деплой Vector + Loki

```yaml
# docker-compose-vector.yml
version: '3.8'

services:
  loki:
    image: grafana/loki:3.4.2
    container_name: loki
    volumes:
      - ./loki-config.yml:/etc/loki/local-config.yaml
    command: -config.file=/etc/loki/local-config.yaml
    ports:
      - "3100:3100"
    restart: unless-stopped

  vector:
    image: timberio/vector:0.42.0-debian
    container_name: vector
    volumes:
      - ./vector.toml:/etc/vector/vector.toml:ro
      - /var/log:/var/log:ro
      - /var/lib/containers:/var/lib/containers:ro
    depends_on:
      - loki
    restart: unless-stopped
```

#### Конфигурация Vector

```toml
# vector.toml
[sources.podman_logs]
type = "file"
include = ["/var/lib/containers/storage/overlay-containers/*/*-json.log"]
read_from = "beginning"

[transforms.parse_json]
type = "remap"
inputs = ["podman_logs"]
source = '''
  . = parse_json!(.message)
  .source = "podman"
  .timestamp = now()
'''

[sinks.loki]
type = "loki"
inputs = ["parse_json"]
endpoint = "http://loki:3100"
labels.job = "podman"
labels.source = "container"
encoding.codec = "json"
```

### 7. Log rotation

```toml
# /etc/containers/containers.conf
[containers]
log_driver = "journald"
log_size_max = 104857600  # 100 МБ на контейнер
```

```bash
# Настройка ротации journal
sudo mkdir -p /etc/systemd/journald.conf.d/
cat <<EOF | sudo tee /etc/systemd/journald.conf.d/size.conf
[Journal]
SystemMaxUse=2G
MaxRetentionSec=30day
MaxFileSec=1day
Compress=yes
EOF

sudo systemctl restart systemd-journald
```

### 8. Поиск и анализ логов

```bash
# jq для парсинга JSON логов
podman logs my-app 2>&1 | jq '.level'

# Фильтрация по уровню
podman logs my-app 2>&1 | jq 'select(.level == "error")'

# Поиск по времени
podman logs my-app 2>&1 | jq 'select(.time > "2024-01-01T10:00:00")'

# Группировка по уровню
podman logs my-app 2>&1 | jq -s 'group_by(.level) | map({level: .[0].level, count: length})'

# Loki: PromQL запрос
curl -G "http://loki:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={job="podman"} |= "error"' \
  --data-urlencode 'start=2024-01-01T00:00:00Z' \
  --data-urlencode 'end=2024-01-01T23:59:59Z'

# Elasticsearch: поиск
curl -X GET "http://elasticsearch:9200/podman-logs-*/_search" \
  -H 'Content-Type: application/json' \
  -d '{"query": {"match": {"level": "error"}}}'
```

---

## Дополнительная информация

### Dual Logging (Podman 4.1+)

Dual Logging позволяет использовать `podman logs` даже при внешнем log driver:

```bash
# Включить dual logging
podman run --log-driver=fluentd \
  --log-opt fluentd-address=localhost:24224 \
  my-app:latest

# Теперь podman logs работает даже с fluentd
podman logs my-app
```

### Сравнение агентов сбора логов

| Агент | Overhead | Язык | Производительность | Гибкость |
|---|---|---|---|---|
| Fluentd | Средний | Ruby | Средняя | Высокая |
| Fluent Bit | Низкий | C | Высокая | Средняя |
| Vector | Низкий | Rust | Очень высокая | Высокая |
| Alloy | Низкий | Go | Высокая | Средняя |

### Типичные проблемы

| Проблема | Причина | Решение |
|---|---|---|
| Логи не отправляются | Неверный адрес агента | Проверить `--log-opt fluentd-address` |
| `podman logs` не работает | Dual logging не включен | Обновить Podman до 4.1+ |
| Логи дублируются | Агент + log driver | Использовать один метод |
| Потеря логов при перезапуске | Агент не хранит offset | Настроить `pos_file` |

### Ссылки

- **[ELK Stack](../../ELK_Stack/elk_stack_overview.md)** — полный стек ELK
- **[Loki](../../Loki/loki_overview.md)** — обзор Grafana Loki
- **[Fluent Bit](../../Kubernetes/MonitoringLogging/EFK/fluentbit/fluentbit_configuration.md)** — конфигурация Fluent Bit
- **[Vector](../../Vector/vector_overview.md)** — обзор Vector
- **[Podman logs](./podman_basic_commands.md)** — CLI-команды Podman
- **[Podman secrets](./podman_secrets.md)** — управление секретами

# force reindex test
