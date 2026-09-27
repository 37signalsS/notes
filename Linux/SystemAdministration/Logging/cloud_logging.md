# Централизованное логирование (Centralized Logging)

## Определения

**Централизованное логирование** — архитектурный подход, при котором логи со всех хостов и сервисов инфраструктуры собираются в единое хранилище, индексируются и становятся доступными для поиска, анализа и визуализации через единый интерфейс.

**Ключевые компоненты:**
- **Collector (агент сбора):** Запускается на каждом хосте, читает локальные логи (файлы, journald, syslog) и отправляет их в канал.
- **Broker/Aggregator (брокер):** Принимает потоки от множества коллекторов, выполняет буферизацию, парсинг, обогащение и маршрутизацию.
- **Storage (хранилище):** Оптимизировано для хранения и поиска по тексту логов. Может быть колоночным (Elasticsearch), объектным + индексным (Loki) или специализированным (VictoriaLogs).
- **Visualization (визуализация):** Интерфейс для выполнения запросов, построения дашбордов и настройки алертов (Grafana, Kibana).
- **Alerting (алертинг):** Правила, реагирующие на паттерны в логах (ошибки, аномалии, ключевые слова).

**Преимущества перед децентрализованным подходом:**
- Единый источник правды для инцидентов
- Возможность корреляции событий между хостами
- Централизованное управление retention и доступом
- Снижение нагрузки на хосты (индексирование вынесено на бэкенд)
- Возможность долгосрочного хранения на дешевых хранилищах

## Архитектура конвейера

### Стандартный pipeline

```
[Источники логов]
    ├── /var/log/*.log (файлы)
    ├── journald (структурированные)
    └── syslog (UDP/TCP 514)
         │
         ▼
[Collector / Agent] — чтение, парсинг, буферизация, сжатие
         │
         ▼
[Transport] — TLS, gRPC, HTTP/2, Kafka
         │
         ▼
[Aggregator / Broker] — Fan-in, enrichment, deduplication
         │
         ▼
[Indexer / Storage] — инвертированный индекс или label-based index
         │
         ▼
[Query Engine] — LogQL, KQL, Lucene
         │
         ▼
[Visualization] — Grafana, Kibana
```

### Модели доставки

| Модель | Описание | Пример |
|--------|----------|---------|
| **Push** | Агент инициирует соединение к бэкенду | Fluent Bit → Loki |
| **Pull** | Бэкенд забирает логи с агентов/хостов | Promtail tail-ом читает файлы |
| **Hybrid** | Агент буферизует, бэкенд запрашивает при необходимости | Vector + buffer |

## Форматы логов и парсинг

### Стандартные форматы

**Plain text (syslog традиционный):**
```
Jan 15 10:23:45 web-01 nginx[1234]: 192.168.1.1 - - [15/Jan/2026:10:23:45 +0000] "GET /api HTTP/1.1" 200 1234
```

**Structured logging (JSON):**
```json
{
  "timestamp": "2026-01-15T10:23:45.123Z",
  "level": "error",
  "service": "webapp",
  "message": "Failed to connect to database",
  "error": "connection_timeout",
  "duration_ms": 5000
}
```

**Logfmt (key=value pairs):**
```
timestamp=2026-01-15T10:23:45Z level=error service=webapp msg="Failed to connect" error=connection_timeout duration=5000
```

### Парсинг и трансформация

**Grok-паттерны** (Elasticsearch/Logstash):
```
%{TIMESTAMP_ISO8601:timestamp} %{LOGLEVEL:level} %{WORD:service}: %{GREEDYDATA:message}
```

**Вектор VRL** (Vector Remap Language):
```vrl
parse_json!(.message)
. = {
  "timestamp": .timestamp,
  "level": .level,
  "service": "webapp",
  "message": .msg
}
```

**Лучшие практики парсинга:**
- Парсите как можно раньше в pipeline (на агенте или брокере)
- Используйте структурированные логи на уровне приложения (JSON/logfmt)
- Для legacy-приложений используйте grok-паттерны на коллекторе
- Валидируйте парсинг: отбрасывайте или помечайте строки, которые не распарсились

### Уровни важности (Severity)

Стандарт RFC 5424:

| Код | Уровень | Описание |
|-----|---------|----------|
| 0 | Emergency | Система неработоспособна |
| 1 | Alert | Требуется немедленное действие |
| 2 | Critical | Критическая ошибка |
| 3 | Error | Ошибка |
| 4 | Warning | Предупреждение |
| 5 | Notice | Нормальное, но значимое событие |
| 6 | Informational | Информационное сообщение |
| 7 | Debug | Отладочное сообщение |

## Гарантии доставки и backpressure

### Модели доставки

**At-most-once (0 или 1):**
- Агент отправляет лог и не ждет подтверждения
- При перезагрузке агента или недоступности бэкенда логи теряются
- Подходит только для не критичных данных (debug-логи)

**At-least-once (1 или больше):**
- Агент подтверждает запись в локальный буфер перед отправкой
- При сбое отправки логи ретраятся
- Риск дублирования; хранилище должно быть идемпотентным
- Используется в большинстве production-сценариев

**Exactly-once (ровно 1):**
- Требует координации между агентом и бэкендом
- Высокая сложность реализации; редко используется на практике
- Вектор и Fluent Bit поддерживают exactly-once через персистентные очереди и дедупликацию

### Обработка обратного давления (Backpressure)

**Проблема:** Агент генерирует логи быстрее, чем бэкенд может их обработать.

**Решения:**
- **Очереди на агенте (disk-based):** Агент буферизует логи на диск при переполнении памяти
- **Ограничение скорости (rate limiting):** Агент или брокер ограничивает скорость отправки
- **Sampling:** Пропуск части логов при перегрузке (с сохранением всех ошибок)
- **Встроенный backpressure в Kafka:** Kafka выступает буфером между агентами и хранилищем

## Сравнение on-premises решений

### Elastic Stack (ELK/Elasticsearch)

**Состав:** Elasticsearch + Logstash/Filebeat + Kibana.

**Принцип работы:** Logstash или Filebeat собирают логи, применяют фильтры (grok, mutate), отправляют в Elasticsearch, где индексируется каждая строка. Kibana предоставляет UI для поиска по Lucene Query Syntax.

**Преимущества:**
- Полнотекстовый поиск по содержимому логов
- Мощный парсинг через grok-паттерны
- Зрелая экосистема (SIEM, APM)
- Широкие возможности визуализации

**Недостатки:**
- Высокое потребление RAM (JVM heap 4-32 ГБ)
- Сложность масштабирования шардов и mapping'ов
- Высокая стоимость оперативной памяти на объем данных
- Требует обязательного управления mapping'ом при изменении формата логов

### Grafana Loki

**Состав:** Loki (хранилище) + Promtail/Alloy (агент) + Grafana (визуализация).

**Принцип работы:** Loki не индексирует текст логов, только метки (labels). Promtail читает файлы или принимает данные через Push, отправляет в Loki. Индексация происходит только по меткам, что делает систему легковесной.

**Преимущества:**
- Низкое потребление ресурсов (нет JVM)
- Масштабирование через разделение данных по меткам
- Естественная интеграция с метриками Prometheus в Grafana
- Поддержка структурированных метаданных (Loki 3.x)

**Недостатки:**
- Полнотекстовый поиск менее эффективен, чем в Elasticsearch
- Зависимость от правильной структуры меток (label cardinality)
- Требует аккуратного проектирования схемы меток

### Graylog

**Состав:** Graylog Server + Elasticsearch + MongoDB.

**Принцип работы:** Graylog принимает логи через GELF (Graylog Extended Log Format) или syslog, индексирует в Elasticsearch, метаданные хранит в MongoDB. Предоставляет web UI для поиска и потоковой обработки.

**Преимущества:**
- Встроенные потоковые правила (streams, pipelines)
- Поддержка GELF из большинства SDK
- RBAC на уровне потоков
- Сообщество и документация

**Недостатки:**
- Зависимость от Elasticsearch с его проблемами
- MongoDB как обязательный компонент
- Меньшая популярность, чем ELK или Loki

### Splunk

**Состав:** Splunk Universal Forwarder + Splunk Indexer + Splunk Web.

**Принцип работы:** Universal Forwarder устанавливается на хосты, отправляет данные в Indexer, который парсит и индексирует. Поиск через SPL (Search Processing Language).

**Преимущества:**
- Мощный язык запросов SPL
- Встроенные приложения для разных сценариев
- Корпоративная поддержка

**Недостатки:**
- Высокая стоимость лицензий
- Высокие требования к hardware
- Проприетарный формат

### VictoriaLogs

**Состав:** VictoriaLogs (единый бинарный файл) + экосистема VictoriaMetrics.

**Принцип работы:** Специализированное хранилище для логов с поддержкой Elasticsearch Bulk API, Prometheus remote write, Splunk HEC и OTLP. Использует columnar storage с высокой компрессией и отсутствием shared state между инстансами.

**Преимущества:**
- Высокая плотность хранения (компрессия 10:1 - 20:1)
- Горизонтальное масштабирование без shared storage
- Совместимость с Elasticsearch Bulk API для миграции
- Поддержка Splunk HEC

**Недостатки:**
- Меньшая зрелость экосистемы, чем у ELK
- Требует понимания принципов работы VictoriaMetrics

### Сводная таблица

| Критерий | Elasticsearch | Loki | Graylog | Splunk | VictoriaLogs |
|----------|---------------|------|---------|--------|--------------|
| **Индексация** | Полнотекстовая | Только метки | Полнотекстовая | Полнотекстовая | Полнотекстовая + колоночная |
| **Потребление RAM** | Высокое (4-32 ГБ) | Низкое (<1 ГБ) | Среднее/Высокое | Высокое | Низкое/Среднее |
| **Сложность деплоя** | Высокая | Низкая | Средняя | Средняя | Низкая |
| **Поиск по телу** | Отличный | Ограниченный | Отличный | Отличный | Хороший |
| **Цена** | Бесплатно/Enterprise | Бесплатно/Enterprise | Бесплатно/Enterprise | Коммерческая | Бесплатно/Enterprise |
| **Масштабирование** | Шарды + реплики | Микросервисное | Шарды | Индексеры | Горизонтальное |

## Высокая доступность и масштабирование

### Архитектура HA для Elasticsearch

**Минимальная конфигурация:**
- 3 мастера (master-eligible nodes) для кворума
- 2+ data-ноды с репликацией (replicas: 1 minimum)
- Отдельный coordinating node для тяжелых запросов

**Рекомендации:**
- Разделите master- и data-роли на разные ноды для средних/больших кластеров
- Настройте shard allocation awareness (zone, rack)
- Используйте ILM (Index Lifecycle Management) для автоматической ротации и миграции shard'ов

### Архитектура HA для Loki

**Минимальная конфигурация:**
- 3 distributor инстанса за балансировщиком (HAProxy/Nginx)
- 3+ ingester инстанса с replication_factor: 3
- 1-2 querier инстанса
- 1 compactor инстанс
- Объектное хранилище (MinIO/Ceph) с репликацией

**Важно:** Loki не требует shared storage между инстансами. Состояние хранится в ring (Consul/etcd/in-memory для dev).

### Архитектура HA для VictoriaLogs

- Stateless архитектура; инстансы не делят состояние
- Развертывание за балансировщиком с round-robin
- Объектное хранилище обеспечивает durability
- Отсутствие single point of failure

### Стратегии масштабирования

**Vertical scaling:**
- Добавление RAM/CPU для Elasticsearch data nodes
- Подходит до 50-100 ГБ heap на ноду

**Horizontal scaling:**
- Elasticsearch: добавление data-нод + ребалансировка shard'ов
- Loki: добавление ingester/querier инстансов
- VictoriaLogs: добавление read-нод

## Агенты сбора

### Выбор агента

| Агент | Язык | Потребление RAM | Kubernetes | systemd | Особенности |
|-------|------|-----------------|------------|---------|-------------|
| **rsyslog** | C | <50 МБ | Нет | Да | Надежный, модульная архитектура |
| **Filebeat** | Go | ~100 МБ | Да (DaemonSet) | Да | Elastic ecosystem, модули |
| **Fluent Bit** | C | ~20 МБ | Да (DaemonSet) | Да | Стандарт для K8s, минимальный footprint |
| **Promtail** | Go | ~100 МБ | Да | Да | Loki-специфичный, tail + push |
| **Grafana Alloy** | Go | ~50 МБ | Да | Да | Замена Promtail, OTLP поддержка |
| **Vector** | Rust | ~50 МБ | Да | Да | VRL трансформации, высокая производительность |

### Рекомендации

- **Одиночные хосты / systemd-сервисы:** rsyslog с модулем `omfwd` или `mmnormalize`.
- **Kubernetes-кластеры:** Fluent Bit как DaemonSet.
- **Микросервисная архитектура на хостах:** Promtail/Alloy или Vector.
- **Микросервисная архитектура в K8s:** Fluent Bit + Loki.

### Интеграция с systemd-journald

Если используется journald как основной источник логов, коллектор может читать напрямую из journal или из файлов `/run/log/journal/`. Подробнее о конфигурации journald: [journald.md](./journald.md).

## Хранилища

### Выбор хранилища

**Elasticsearch:**
- Подходит, если требуется полнотекстовый поиск по телу логов
- Минимум 3 мастера для HA
- Рекомендуемый объем диска: SSD, 30-60 дней retention

**Loki:**
- Подходит, если логи структурированы по сервисам (метки: service, env, host)
- Может использовать MinIO или Ceph для долгосрочного хранения
- Дешевле в эксплуатации, чем ELK

**VictoriaLogs:**
- Подходит для high-cardinality сценариев (множество уникальных trace_id, user_id)
- Требует меньше оперативной памяти на объем данных
- Подходит для инфраструктур 100+ хостов

### Стратегии retention

| Стратегия | Использование | Пример |
|-----------|---------------|--------|
| **Hot-Warm-Cold** | Недавние логи на SSD, старые на HDD или объектное хранилище | Elasticsearch ILM |
| **Time-based** | Удаление старше N дней | Loki retention period |
| **Size-based** | Удаление при превышении объема | logrotate + external storage |
| **Compliance** | Обязательное хранение N лет для audit | WORM-хранилище |

Подробнее о ротации и сжатии на уровне ОС: [logrotate.md](./logrotate.md).

### Стратегии резервного копирования

**Elasticsearch snapshot:**
```bash
# Регистрация snapshot repository
PUT /_snapshot/backup
{
  "type": "fs",
  "settings": {
    "location": "/mnt/backups/elasticsearch"
  }
}

# Создание snapshot
PUT /_snapshot/backup/snapshot_2026_01_15?wait_for_completion=true
{
  "indices": "logs-*",
  "ignore_unavailable": true,
  "include_global_state": false
}
```

**Loki бэкап:**
```bash
# Использование boltdb-shipper для бэкапа
loki -config.file=/etc/loki/config.yaml -target=export -boltdb-shipper.backup-source=/tmp/loki/tsdb
```

**Проверка бэкапа (обязательно):**
```bash
# Тест восстановления Elasticsearch snapshot
POST /_snapshot/backup/snapshot_2026_01_15/_restore
{
  "indices": "logs-2026.01.15",
  "rename_pattern": "restored_(.*)",
  "rename_replacement": "restored_$1"
}
```

## Сетевая конфигурация и брандмауэры

### Порты и протоколы

| Компонент | Порт | Протокол | Назначение |
|-----------|------|----------|------------|
| **rsyslog (TCP)** | 514 | TCP | Прием логов от агентов (reliable) |
| **rsyslog (UDP)** | 514 | UDP | Прием логов от агентов (unreliable, legacy) |
| **Loki HTTP** | 3100 | TCP | Push API и запросы |
| **Loki gRPC** | 9096 | TCP | gRPC API (Alloy, Promtail) |
| **Elasticsearch** | 9200 | TCP | REST API |
| **Elasticsearch transport** | 9300 | TCP | Межнодное взаимодействие |
| **Kafka** | 9092 | TCP | Брокер сообщений |

### Правила брандмауэра (nftables пример)

```bash
# /etc/nftables.d/logging.nft

table inet filter {
  chain input {
    type filter hook input priority 0; policy accept;
    
    # rsyslog прием от доверенных сетей
    ip saddr 10.0.0.0/8 tcp dport 514 accept
    ip saddr 10.0.0.0/8 udp dport 514 accept
    
    # Loki - только от внутренней сети
    ip saddr 10.0.0.0/8 tcp dport 3100 accept
    ip saddr 10.0.0.0/8 tcp dport 9096 accept
  }
}
```

### TLS/mTLS конфигурация

**Генерация CA и сертификатов:**
```bash
# Создание CA
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt

# Сертификат для Loki
openssl genrsa -out loki.key 2048
openssl req -new -key loki.key -out loki.csr
openssl x509 -req -in loki.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out loki.crt -days 365 -sha256
```

**Включение TLS в Loki:**
```yaml
server:
  http_listen_port: 3100
  grpc_listen_port: 9096
  tls_ cert: /etc/loki/tls/loki.crt
  tls_key: /etc/loki/tls/loki.key
  tls_client_ca: /etc/loki/tls/ca.crt
  tls_client_auth_type: RequireAndVerifyClientCert
```

**Включение TLS в Fluent Bit:**
```ini
[OUTPUT]
    Name              http
    Match             *
    Host              loki.internal:3100
    URI               /loki/api/v1/push
    tls               on
    tls.verify        on
    tls.ca_file       /etc/fluent-bit/ca.crt
    tls.crt_file      /etc/fluent-bit/tls.crt
    tls.key_file      /etc/fluent-bit/tls.key
```

## Практические сценарии

### Сценарий 1: Малая инфраструктура (<10 хостов)

**Задача:** Собрать логи с 5 веб-серверов и 2 СУБД в единый интерфейс.

**Решение:** rsyslog на каждом хосте → центральный rsyslog → Loki + Grafana.

Конфигурация центрального rsyslog (`/etc/rsyslog.d/central.conf`):
```
# Прием от удаленных хостов
module(load="imtcp")
input(type="imtcp" port="514")

# Запись в файлы по хостам
template(name="PerHostLog" type="string" string="/var/log/remote/%HOSTNAME%/%programname%.log")

if $fromhost-ip != '127.0.0.1' then {
    action(type="omfile" dynaFile="PerHostLog")
    stop
}
```

Конфигурация Loki (`/etc/loki/local-config.yaml`):
```yaml
auth_enabled: false
server:
  http_listen_port: 3100
  grpc_listen_port: 9096

ingester:
  wal:
    dir: /tmp/wal
  lifecycler:
    ring:
      kvstore:
        store: inmemory
      replication_factor: 1

schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

storage:
  filesystem:
    directory: /tmp/loki/chunks
  tsdb:
    dir: /tmp/loki/tsdb

limits_config:
  enforce_metric_name: false
  reject_old_samples: true
  reject_old_samples_max_age: 168h
```

### Сценарий 2: Средняя инфраструктура (10-100 хостов)

**Задача:** CentOS/RHEL-парк с разными сервисами, требующими поиска по ошибкам за 30 дней.

**Решение:** Vector на хостах → Kafka как брокер → Elasticsearch + Kibana.

Конфигурация Vector (`/etc/vector/vector.yaml`):
```yaml
sources:
  journald:
    type: journald
    include_units:
      - sshd.service
      - nginx.service
      - postgresql.service
  syslog:
    type: syslog
    mode: udp
    address: 0.0.0.0:514

transforms:
  parse_nginx:
    type: remap
    inputs:
      - syslog
    source: |
      .message = parse_nginx_log!(.message)

sinks:
  kafka_access:
    type: kafka
    inputs:
      - parse_nginx
    bootstrap_servers: kafka.internal:9092
    topic: nginx-access
  kafka_system:
    type: kafka
    inputs:
      - journald
    bootstrap_servers: kafka.internal:9092
    topic: system-logs
```

### Сценарий 3: Kubernetes-кластер

**Задача:** Сбор логов контейнеров, Pod'ов и systemd-сервисов узлов.

**Решение:** Fluent Bit DaemonSet на каждый узел → Loki Gateway.

Пример RBAC для Fluent Bit:
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: fluent-bit
  namespace: logging
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: fluent-bit
rules:
  - apiGroups: [""]
    resources:
      - namespaces
      - pods
      - pods/logs
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: fluent-bit
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: fluent-bit
subjects:
  - kind: ServiceAccount
    name: fluent-bit
    namespace: logging
```

### Сценарий 4: Высокая доступность logging stack

**Задача:** Развернуть отказоустойчивый стек Loki + Grafana.

**Решение:** 3 distributor + 3 ingester + 1 querier + MinIO кластер.

Конфигурация Loki с HA (`/etc/loki/ha-config.yaml`):
```yaml
auth_enabled: false

server:
  http_listen_port: 3100
  grpc_listen_port: 9096

ingester:
  wal:
    dir: /tmp/wal
  lifecycler:
    ring:
      kvstore:
        store: inmemory
      replication_factor: 3
    join_after: 10s
    max_returned_server_age: 1h

distributor:
  ring:
    kvstore:
      store: inmemory

limits_config:
  enforce_metric_name: false
  reject_old_samples: true
  reject_old_samples_max_age: 168h

schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

storage:
  filesystem:
    directory: /tmp/loki/chunks
  tsdb:
    dir: /tmp/loki/tsdb
```

### Сценарий 5: Disaster Recovery

**Задача:** Обеспечить восстановление logging stack после сбоя.

**RTO/RPO цели:**

| Компонент | RTO (Время восстановления) | RPO (Потеря данных) |
|:---|:---|:---|
| Loki ingest | < 15 минут | 0 (данные в object storage) |
| Loki query | < 30 минут | 0 |
| Elasticsearch cluster | < 4 часа | < 1 час (snapshot) |
| Агенты (Vector/Fluent Bit) | < 5 минут (автовосстановление) | Зависит от disk buffer |
| Конфигурации | < 10 минут (Git) | 0 (Git history) |

**План восстановления (Disaster Recovery Plan):**

```yaml
# dr_plan.yaml
title: "Disaster Recovery: Logging Stack"
version: "1.0"
last_tested: "2026-09-15"

components:
  - name: "Loki"
    recovery_steps:
      1. "Развернуть Loki из Helm chart / Ansible playbook"
      2. "Подключить object storage (MinIO/Ceph/S3)"
      3. "Восстановить TSDB из snapshot"
      4. "Проверить ingestion через healthcheck"
    estimated_time: "30 мин"
    backup_location: "s3://backups/loki/snapshots/"

  - name: "Grafana"
    recovery_steps:
      1. "Развернуть Grafana"
      2. "Восстановить дашборды из Git provisioning"
      3. "Подключить Loki как datasource"
      4. "Проверить alerting rules"
    estimated_time: "15 мин"
    backup_location: "git://grafana-dashboards"

  - name: "Vector/Fluent Bit"
    recovery_steps:
      1. "Установить агенты на хосты (Ansible)"
      2. "Развернуть конфигурации из Git"
      3. "Проверить подключение к бэкенду"
    estimated_time: "5 мин (автоматически)"
    backup_location: "git://infrastructure-configs"

  - name: "Elasticsearch"
    recovery_steps:
      1. "Развернуть кластер (3+ мастера)"
      2. "Восстановить snapshot"
      3. "Проверить cluster health: green"
    estimated_time: "2-4 часа"
    backup_location: "/mnt/backups/elasticsearch/"
```

**Автоматический DR-скрипт:**

```bash
#!/bin/bash
# /usr/local/bin/dr-logging.sh
set -euo pipefail

LOKI_BACKUP="s3://backups/loki/snapshots/"
GRAFANA_GIT="git@github.com:org/grafana-dashboards.git"
VECTOR_CONFIGS="git@github.com:org/infrastructure-configs.git"

echo "=== DR: Logging Stack Recovery ==="

# 1. Восстановление Loki
echo "[1/4] Восстановление Loki..."
helm install loki grafana/loki -f /tmp/loki-ha-values.yaml
sleep 30
loki -config.file=/etc/loki/config.yaml -target=restore -boltdb-shipper.backup-source="$LOKI_BACKUP"

# 2. Восстановление Grafana
echo "[2/4] Восстановление Grafana..."
git clone "$GRAFANA_GIT" /tmp/grafana-dashboards
cp -r /tmp/grafana-dashboards/dashboards/* /var/lib/grafana/dashboards/
systemctl restart grafana-server

# 3. Восстановление конфигов агентов
echo "[3/4] Восстановление Vector configs..."
git clone "$VECTOR_CONFIGS" /tmp/infrastructure-configs
cp -r /tmp/infrastructure-configs/vector/* /etc/vector/
systemctl restart vector

# 4. Проверка
echo "[4/4] Проверка работоспособности..."
sleep 10
curl -sf http://localhost:3100/ready || { echo "FAIL: Loki not ready"; exit 1; }
curl -sf http://localhost:3000/api/health || { echo "FAIL: Grafana not ready"; exit 1; }
curl -sf http://localhost:9000/health || { echo "FAIL: Vector not ready"; exit 1; }

echo "=== DR Complete ==="
```

**Проверка бэкапа (обязательно раз в квартал):**

```bash
# 1. Тест восстановления Loki snapshot
loki -config.file=/etc/loki/config.yaml -target=restore \
  -boltdb-shipper.backup-source=/tmp/test-restore/

# 2. Проверка целостности
curl -s "http://loki:3100/loki/api/v1/query?query={test=\"dr-test\"}" | jq .

# 3. Проверка Git-бэкапов конфигов
git -C /tmp/grafana-dashboards log --oneline -5

# 4. Документирование результатов
echo "DR test $(date -u +%Y-%m-%dT%H:%M:%SZ): PASS" >> /var/log/dr-tests.log
```

### Сценарий 6: Планирование мощности (Capacity Planning)

**Задача:** Определить требуемые ресурсы для инфраструктуры 100 хостов.

**Формула оценки:**
```
Объем логов = Количество хостов × Логов на хост/день × Средний размер лога
```

**Пример расчета:**
- 100 хостов × 500 МБ/день × 1.5 (compression overhead) = 75 ГБ/день
- Retention 30 дней = 2.25 ТБ
- Сжатие 5:1 → 450 ГБ на диске
- Elasticsearch: 3 data-ноды по 32 ГБ RAM, 2 ТБ SSD каждая
- Loki: 2 ingester по 4 ГБ RAM, 1 ТБ SSD

**Мониторинг роста:**
```bash
# Отслеживание роста индексов Elasticsearch
curl -s http://es:9200/_cat/indices?h=index,store.size,health

# Отслеживание chunks в Loki
curl -s http://loki:3100/metrics | grep loki_ingester_chunks
```

### Сценарий 7: Миграция между бэкендами

**Задача:** Мигрировать с ELK на Loki.

**Этапы:**
1. **Параллельный запуск:** Запустите Loki рядом с ELK
2. **Дублирование трафика:** Настройте Vector для отправки в оба бэкенда
3. **Валидация:** Сравните результаты поиска в Grafana (Loki) и Kibana (ELK)
4. **Переключение:** Перенаправьте весь трафик на Loki
5. **Деcommission:** Выключите ELK после подтверждения стабильности

**Конфигурация Vector для dual-write:**
```yaml
sinks:
  loki:
    type: loki
    inputs: [parsed_logs]
    endpoint: http://loki:3100
  elasticsearch:
    type: elasticsearch
    inputs: [parsed_logs]
    endpoints: ["http://elasticsearch:9200"]
```

### Сценарий 8: Соответствие compliance (PCI DSS, GDPR, ФЗ-152)

**Требования:**
- Хранение audit-логов не менее 1 года
- Защита от изменения (immutability)
- Контроль доступа на уровне пользователей

**Решение:**
- Loki с объектным хранилищем с поддержкой WORM (MinIO, Ceph)
- RBAC в Grafana: разделение по проектам/окружениям
- Регулярная проверка целостности через checksum'ы

Конфигурация retention в Loki:
```yaml
limits_config:
  retention_period: 8760h  # 1 год
  ingestion_rate_mb: 10
  ingestion_burst_size_mb: 20
```

### Сценарий 9: Инцидент "Отказ сервиса"

**Задача:** Найти причину отказа веб-приложения за последний час.

**Действия:**
1. В Grafana открыть Explore → источник Loki
2. Выполнить LogQL-запрос:
   ```
   {service="webapp", severity="error"} | json | line_format "{{.timestamp}} {{.message}}"
   ```
3. Если метка `service` неизвестна, искать по хосту:
   ```
   {host="web-01"} |~ "(?i)(error|panic|fatal|oom)"
   ```
4. Найти Boot ID и сопоставить с journald:
   ```bash
   journalctl -b --since "1 hour ago" -p err
   ```

### Сценарий 10: Мониторинг работоспособности pipeline

**Задача:** Убедиться, что логи доставляются и индексируются.

**Метрики Loki (через /metrics):**
- `loki_request_duration_seconds` — задержка запросов
- `loki_distributor_lines_received_total` — количество принятых строк
- `loki_ingester_streams_errors_total` — ошибки инжестинга
- `loki_compactor_errors_total` — ошибки компакции

**Метрики Fluent Bit:**
- `fluentbit_input_processed_bytes_total` — обработанные байты
- `fluentbit_output_retries_total` — количество ретраев
- `fluentbit_output_proc_records_total` — отправленные записи

**Базовый health-check скрипт:**
```bash
#!/bin/bash
# Проверка доставки тестового события в Loki

TEST_LABELS='test="healthcheck"'
TEST_MSG="healthcheck-$(date +%s)"

curl -s -XPOST "http://loki:3100/loki/api/v1/push" \
  -H "Content-Type: application/json" \
  -d "{\"streams\":[{\"stream\":{$TEST_LABELS},\"values\":[[\"$(date +%s)000000000\",\"$TEST_MSG\"]]}]}"

sleep 5

RESULT=$(curl -s "http://loki:3100/loki/api/v1/query_range?query={test=\"healthcheck\"}&limit=1&start=$(date -d '5 minutes ago' +%s)000000000&end=$(date +%s)000000000" | jq -r '.data.result[0].values[0][1]')

if [ "$RESULT" = "$TEST_MSG" ]; then
    echo "OK: Тестовое событие доставлено"
else
    echo "FAIL: Тестовое событие не найдено"
    exit 1
fi
```

### Сценарий 11: Автоматизация через Ansible

**Задача:** Развернуть Fluent Bit + Loki на 50 хостах.

```yaml
- name: Установка Fluent Bit
  ansible.builtin.apt:
    name: fluent-bit
    state: present
  when: ansible_os_family == "Debian"

- name: Конфигурация Fluent Bit
  ansible.builtin.template:
    src: fluent-bit.conf.j2
    dest: /etc/fluent-bit/fluent-bit.conf
  notify: restart fluent-bit

- name: Установка Loki
  ansible.builtin.unarchive:
    src: https://github.com/grafana/loki/releases/download/v3.0.0/loki-linux-amd64.zip
    dest: /usr/local/bin/
    remote_src: yes

- name: Systemd unit для Loki
  ansible.builtin.template:
    src: loki.service.j2
    dest: /etc/systemd/system/loki.service
  notify: daemon-reload
```

## Безопасность

### Транспортное шифрование

Все соединения между агентами и бэкендом должны быть защищены TLS:

```yaml
# Пример: Fluent Bit с TLS
[OUTPUT]
    Name              http
    Match             *
    Host              loki.internal:3100
    URI               /loki/api/v1/push
    tls               on
    tls.verify        on
    tls.ca_file       /etc/fluent-bit/ca.crt
    tls.crt_file      /etc/fluent-bit/tls.crt
    tls.key_file      /etc/fluent-bit/tls.key
```

### Контроль доступа

- **Grafana:** Настройка RBAC через Team и Permission. Org → Team → Folder → Dashboard.
- **Loki:** Multi-tenancy через заголовок `X-Scope-OrgID`. Каждый проект = отдельный OrgID.
- **Elasticsearch:** RBAC через Security API. Роли: `logs_reader`, `logs_writer`, `logs_admin`.

### Журналирование действий (audit trail)

Включите аудит доступа к панелям Grafana и изменений в конфигурациях Logstash/Vector.

### Управление секретами в пайплайне

**Проблема:** Креды для подключения к Loki/Elasticsearch/Kafka не должны храниться в открытом виде в конфигах агентов.

**Решения:**

**1. Vector с Vault:**
```yaml
sources:
  vault:
    type: vault
    address: https://vault.internal:8200
    token: ${VAULT_TOKEN}
    path: secret/data/vector/loki
```

**2. Environment variables (Ansible):**
```yaml
- name: Deploy Fluent Bit config with secrets
  ansible.builtin.template:
    src: fluent-bit.conf.j2
    dest: /etc/fluent-bit/fluent-bit.conf
  vars:
    loki_password: "{{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/loki password') }}"
```

**3. File-based secrets (systemd):**
```ini
# /etc/systemd/system/vector.service.d/override.conf
[Service]
EnvironmentFile=/etc/vector/secrets.env
```

**Безопасность логов:**
- Санитайзеры секретов на агенте (Vector `redact`-процессоры)
- Исключение чувствительных полей до отправки в бэкенд
- Шифрование at rest для всех хранилищ

## Производительность

### Ресурсы бэкенда

| Компонент | Минимум | Рекомендуется |
|-----------|---------|---------------|
| **Elasticsearch data node** | 8 ГБ RAM, 4 vCPU | 16-32 ГБ RAM, 8 vCPU |
| **Loki ingester** | 2 ГБ RAM, 2 vCPU | 4-8 ГБ RAM, 4 vCPU |
| **VictoriaLogs** | 4 ГБ RAM, 4 vCPU | 8-16 ГБ RAM, 4 vCPU |

### Сжатие

- **Elasticsearch:** `best_compression` (DEFLATE) для индексов. Увеличивает индексацию на 10-20%, уменьшает объем в 2-3 раза.
- **Loki:** snappy для chunks в TSDB. Сжатие 5:1 - 10:1 для текстовых логов.
- **VictoriaLogs:** Встроенное сжатие columnar storage.

### Буферизация

Используйте очередь на агенте для предотвращения потерь при недоступности бэкенда:

```yaml
# Vector buffer
sinks:
  loki:
    type: loki
    buffer:
      type: disk
      max_size: 1073741824  # 1 ГБ
      when_full: block
```

## Мониторинг

### Мониторинг самого logging stack

**Elasticsearch:**
- `cluster_health_status` — RED/YELLOW/GREEN
- `jvm_memory_used_bytes` — использование heap
- `indices_search_query_time_seconds` — задержка поиска

**Loki:**
- `loki_request_duration_seconds_bucket` — latency percentiles
- `loki_ingester_memory_chunks` — утечки памяти
- `loki_distributor_bytes_received_total` — пропускная способность

**Fluent Bit:**
- `fluentbit_input_processed_records_total` — обработанные записи
- `fluentbit_output_retries_total` — количество ретраев
- `fluentbit_output_proc_records_total` — отправленные записи

### Алертинг

**Правила для Prometheus Alertmanager:**

```yaml
# logging_alerts.yaml
groups:
  - name: logging_stack
    rules:
      - alert: LokiDown
        expr: up{job="loki"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Loki недоступен"

      - alert: ElasticsearchClusterRed
        expr: elasticsearch_cluster_health_status{color="red"} == 1
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Elasticsearch кластер в состоянии RED"

      - alert: FluentBitOutputErrors
        expr: rate(fluentbit_output_retries_total[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Fluent Bit имеет ошибки отправки"

      - alert: LogDeliveryLag
        expr: time() - max(timestamp_overflows_by_source{source=~".+"}) > 300
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Запаздывание доставки логов > 5 минут"
```

### Sampling и оптимизация объема

**Когда использовать sampling:**
- DEBUG-логи в production (сохраняйте 1-5%)
- Обычные HTTP-запросы (сохраняйте 10-20%)
- ВСЕГДА сохраняйте ошибки и критические события (100%)

**Vector sampling конфигурация:**
```yaml
transforms:
  sample_debug:
    type: sample
    inputs: [journald]
    rate: 10  # Сохранять 1 из 10 записей
    sample_probability: 0.1
    # Исключать ошибки из sampling
    exclude_levels: ["error", "critical"]
```

## Устранение неполадок

| Проблема | Причина | Решение |
|----------|---------|---------|
| **Потеря логов при перезагрузке агента** | Буфер в памяти, не подтверждено бэкендом | Используйте disk-based buffer с `when_full: block` |
| **Высокое потребление RAM Elasticsearch** | Большие shards, heap слишком большой | Уменьшите heap до 50% от RAM, настройте ILM для shard rotation |
| **Loki: "out of order samples"** | Два инстанса отправляют логи с одинаковыми метками одновременно | Добавьте `instance` метку для разделения |
| **Поиск работает медленно** | Слишком широкий временной диапазон, нет нужных меток | Добавьте `service` и `severity` метки, сузьте `range` |
| **Grafana: "Data source not reachable"** | Firewall, TLS, аутентификация | Проверьте `curl` из ноды Grafana к Loki, проверьте сертификаты |
| **Диск заполнен логами** | Отсутствует retention, бэкапы | Настройте `limits_config.retention_period`, включите сжатие, добавьте alerting |
| **Неверный парсинг Nginx/Apache** | Нет grok-паттерна, изменился формат логов | Используйте `logfmt` parser в Loki или Filebeat модуль |
| **Elasticsearch: "cluster_block_exception"** | Превышен watermark | Очистите старые индексы, увеличьте disk или добавьте ноды |
| **Loki: "ingestion rate limit exceeded"** | Превышен `ingestion_rate_mb` | Увеличьте лимит или добавьте distributor инстансы |
| **Vector: "Connection refused"** | Бэкенд недоступен, неправильный адрес | Проверьте DNS, firewall, статус сервиса бэкенда |
| **rsyslog: "imuxsock lost messages"** | Переполнение буфера journald → rsyslog | Увеличьте `RateLimitBurst` в journald или используйте прямой вывод в файл |
| **Elasticsearch: "mapper_parsing_exception"** | Изменился формат поля, conflict с mapping | Используйте dynamic mapping или обновите mapping вручную |
| **Grafana: пустые результаты поиска** | Неправильные метки, отсутствие данных за период | Проверьте метки через `logcli` или запрос без фильтров |
| **Kafka: "NotLeaderForPartition"** | Брокер-лидер недоступен | Проверьте статус брокера, reassign partitions |
| **Высокое использование CPU на агенте** | Слишком много парсинга, сложные regex | Вынесите парсинг на брокер (Kafka → Vector transform), упростите regex |
| **Elasticsearch: "search_phase_execution_exception"** | Timeout запроса, слишком широкий диапазон | Увеличьте `request_timeout`, добавьте `_source` фильтр, сузьте временной диапазон |
| **Loki: "too many outstanding requests"** | Долгие запросы заблокировали querier | Увеличьте количество querier инстансов, оптимизируйте LogQL |
| **Циклический рост диска MinIO** | Отсутствует lifecycle policy | Настройте MinIO lifecycle для удаления старых объектов |
| **Нестабильная работа TLS** | Истек сертификат, несовпадение CN/SAN | Проверьте срок действия: `openssl x509 -in server.crt -noout -dates` |

## Рекомендации

1. **Структура меток:** Всегда добавляйте `service`, `env` (dev/staging/prod), `host`. Это обязательный минимум для корреляции.
2. **Retention:** Определите retention по категориям логов:
   - Application logs: 14-30 дней
   - Audit logs: 1-7 лет
   - Metrics/Traces: 7-90 дней
3. **Буферизация:** Всегда используйте disk buffer на агенте, если uptime бэкенда < 99.9%.
4. **Сжатие:** Включите gzip/snappy на транспортном уровне.
5. **Тишина (quiet logs):** Исключайте DEBUG-логи на уровне агента для production. Это экономит 60-80% объема.
6. **Алертинг:** Настройте алерты на:
   - Падение доставки логов > 5 минут
   - Рост ошибок 5xx в access-логах > 1% за 5 минут
   - Получение logs_reader доступом для production-сервисных аккаунтов
7. **Структурированные логи:** Используйте JSON или logfmt вместо plain text.
8. **Документация:** Ведите реестр сервисов с указанием: `service=`, формат логов, retention, ответственный.
9. **Тестирование:** Периодически проверяйте восстановление из бэкапа и поиск по архивным логам.
10. **Сервис-аккаунты:** Не используйте общие ключи; каждый сервис должен иметь свой `X-Scope-OrgID` или credentials.

### Автоматизация и управление конфигурацией

**Ansible playbook для полного стека:**

```yaml
# playbooks/logging_stack.yml
- name: Развертывание logging stack
  hosts: logging
  become: true
  vars:
    loki_version: "3.0.0"
    vector_version: "0.40.0"
    grafana_version: "11.0.0"
  tasks:
    - name: Установка зависимостей
      ansible.builtin.apt:
        name:
          - curl
          - gnupg
          - lsb-release
          - prometheus-node-exporter
        state: present
        update_cache: yes

    - name: Создание пользователя vector
      ansible.builtin.user:
        name: vector
        system: yes
        shell: /usr/sbin/nologin

    - name: Распаковка Vector
      ansible.builtin.unarchive:
        src: "https://github.com/vectordotdev/vector/releases/download/v{{ vector_version }}/vector-{{ vector_version }}-x86_64-unknown-linux-musl.tar.gz"
        dest: /usr/local/bin/
        remote_src: yes
        extra_opts: ["--strip-components=1"]

    - name: Развертывание конфигурации Vector
      ansible.builtin.template:
        src: vector.yaml.j2
        dest: /etc/vector/vector.yaml
      notify: restart vector

    - name: Развертывание systemd unit для Vector
      ansible.builtin.copy:
        content: |
          [Unit]
          Description=Vector
          After=network.target

          [Service]
          Type=simple
          ExecStart=/usr/local/bin/vector
          Restart=always
          RestartSec=5

          [Install]
          WantedBy=multi-user.target
        dest: /etc/systemd/system/vector.service
      notify: daemon-reload

    - name: Включение и запуск Vector
      ansible.builtin.systemd:
        name: vector
        enabled: yes
        state: started

    - name: Проверка работы Vector
      ansible.builtin.uri:
        url: http://localhost:9000/health
        status_code: 200
      retries: 3
      delay: 5

  handlers:
    - name: restart vector
      ansible.builtin.systemd:
        name: vector
        state: restarted

    - name: daemon-reload
      ansible.builtin.systemd:
        daemon_reload: yes
```

**Terraform для инфраструктуры (пример):**
```hcl
# main.tf
resource "local_file" "vector_config" {
  content  = templatefile("${path.module}/vector.yaml.tftpl", {
    loki_endpoint = var.loki_endpoint
    kafka_brokers = var.kafka_brokers
  })
  filename = "${path.module}/generated/vector.yaml"
}

resource "null_resource" "deploy_vector" {
  triggers = {
    config_hash = filesha256(local_file.vector_config.filename)
  }

  provisioner "remote-exec" {
    inline = [
      "sudo systemctl restart vector"
    ]
  }
}
```

## Соответствие требованиям

| Стандарт | Требование к логированию | Рекомендация |
|----------|-------------------------|--------------|
| **PCI DSS** | Хранение audit логов минимум 1 год, 3 месяца онлайн | Loki + объектное хранилище с WORM, Grafana RBAC |
| **GDPR** | Право на удаление данных, минимизация | Анонимизация PII на уровне агента |
| **ФЗ-152** | Защита персональных данных, контроль доступа | Шифрование at rest, audit trail |
| **ФЗ-187** | Требования к АСУ ТЭК, хранение событий | Долгосрочное архивирование, WORM |

## Дополнительная информация

### См. также
- [Обзор логирования в Linux](./logging_overview.md) — общая архитектура сбора данных.
- [rsyslog: Настройка и администрирование](./rsyslog.md) — SSoT для rsyslog, центральный агрегатор логов.
- [journald: Системный журнал systemd](./journald.md) — structured logging на уровне ОС.
- [logrotate: Ротация и сжатие логов](./logrotate.md) — управление размером файлов логов.
- [Интеграция Fluent Bit с Loki](../../../Loki/fluentbit_integration.md) — развертывание агента в Kubernetes.
- [Обзор Grafana Loki](../../../Loki/loki_overview.md) — архитектура и концепции Loki.
- [VictoriaMetrics: Обзор](../../../VictoriaMetrics/overview.md) — сравнение VictoriaLogs с конкурентами.
