# Варианты развертывания Jaeger

**Актуально для:** Jaeger v2.x

> **Важно:** Документация описывает **Jaeger v2**. Jaeger v1 достиг **EOL (End of Life)**.

**Варианты развертывания Jaeger v2** охватывают архитектурные и инфраструктурные сценарии развертывания распределенной трассировки на on-premise инфраструктуре (bare-metal серверы, виртуальные машины, контейнеры Docker и кластеры Kubernetes). Переход на архитектуру единого бинарного файла (**Unified Binary**) на базе OpenTelemetry Collector устранил необходимость в раздельных бинарниках v1 (`jaeger-collector`, `jaeger-query`, `jaeger-ingester`, `jaeger-agent`) и позволил гибко комбинировать роли процесса через декларативные YAML-манифесты.

Общий обзор системы: **[Обзор Jaeger](./jaeger_overview.md)**.  
Архитектура и внутренние конвейеры: **[Архитектура Jaeger](./jaeger_architecture.md)**.  
Бэкенды хранения и структуры таблиц: **[Storage Deep Dive для Jaeger](./jaeger_storage_deep_dive.md)**.  
Оркестрация и операторы в Kubernetes: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**.  
Расчет ресурсов и сайзинг: **[Capacity Planning для Jaeger](./jaeger_capacity_planning.md)**.  
Отказоустойчивость и кластеризация: **[High Availability и DR](./jaeger_high_availability.md)**.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **All-in-one** | Запуск всех подсистем (прием спанов, буферизация, запись в локальное хранилище, Query API и UI) в рамках одного процесса. Предназначен для локальной разработки, CI/CD и автономных стендов |
| **Distributed Production (Direct)** | Раздельное развертывание пула инстансов Collector и пула инстансов Query с прямой синхронной/асинхронной записью в централизованную СУБД (ClickHouse или Elasticsearch) |
| **Streaming (Kafka-buffered)** | Отказоустойчивая архитектура с буферизацией телеметрии в Apache Kafka между Collector и Ingester для сглаживания пиковых нагрузок и изоляции отказа БД |
| **Unified Binary** | Архитектурная модель Jaeger v2, в которой единый исполняемый файл `jaeger` выполняет функции Collector, Ingester, Query или All-in-one исключительно на основе переданного конфигурационного файла |
| **Systemd Service Mode** | Развертывание бинарника Jaeger как системной службы Linux с изоляцией cgroups, лимитами дескрипторов файлов (`LimitNOFILE`), управлением памятью и автоперезапуском |
| **Ingester** | Специализированная роль Jaeger v2, работающая как consumer в группе Kafka, извлекающая пачки спанов из топиков и сохраняющая их в ClickHouse |
| **OTLP Receiver / Exporter** | Стандартные компоненты OpenTelemetry Collector для приема (порты 4317 gRPC / 4318 HTTP) и передачи трейсов по протоколу OTLP Protobuf |
| **Storage Extension (`jaeger_storage`)** | Расширение Jaeger v2, создающее общий пул соединений с базой данных для экспортеров записи (`jaeger_storage_exporter`) и интерфейсов чтения (`jaeger_query`) |
| **Backpressure** | Механизм защитного ограничения входящего потока данных при переполнении внутренних очередей или нехватке оперативной памяти процесса |
| **Memory Limiter** | Процессор конвейера, отслеживающий потребление RAM процессом и упреждающе отбрасывающий спаны для предотвращения аварийного завершения по Linux OOM Killer |

---

## Базовые концепции

### Сравнение моделей развертывания

Выбор топологии Jaeger v2 зависит от интенсивности входящего потока спанов (spans/s), требований к доступности при деградации СУБД и допустимого времени восстановления:

| Критерий | All-in-one | Distributed Production (Direct) | Streaming (Kafka-buffered) |
| :--- | :--- | :--- | :--- |
| **Назначение** | Локальная разработка, стенды CI/CD, демо | Постоянные production-контуры со стабильной СУБД | Высоконагруженные системы (High Load), всплески трафика |
| **Интенсивность потока** | До 2 000 спанов/с | От 2 000 до 50 000 спанов/с | Более 50 000 спанов/с |
| **Бэкенд хранения** | In-memory / Badger (локальный диск) | ClickHouse (рекомендуется) / Elasticsearch | ClickHouse кластер |
| **Буфер перед БД** | Очередь в RAM процесса | Очередь в RAM коллектора (`queue_size`) | Распределенный журнал Apache Kafka |
| **Поведение при падении БД** | Ошибки записи, переполнение буфера | Сброс спанов при заполнении очереди в RAM | Спаны накапливаются в Kafka до восстановления БД |
| **Масштабирование** | Только вертикальное (RAM/CPU узла) | Независимое горизонтальное (Collector, Query) | Независимое масштабирование Collector, Ingester, Query |
| **Сложность эксплуатации** | Минимальная (один сервис/контейнер) | Средняя (отдельные пулы сервисов и СУБД) | Высокая (требуется поддержка кластера Kafka) |

### Сравнение сред развертывания

На on-premise инфраструктуре системные администраторы и инженеры SRE выбирают среду исполнения в соответствии со стандартами предприятия:

| Среда | Преимущества | Недостатки | Сценарий применения |
| :--- | :--- | :--- | :--- |
| **Bare-Metal / Linux VM (Systemd)** | Максимальная производительность сетевого стека, прямой доступ к ресурсам ядра, отсутствие оверхеда оверлейных сетей CNI | Ручное управление версиями бинарников или потребность в Ansible/Puppet | Высоконагруженные пулы Collector с трафиком 10+ Гбит/с, выделенные серверы Ingester |
| **Docker / Docker Compose** | Изоляция окружения, простота обновления образов, фиксированные конфигурации в Git | Ограниченное автоматическое масштабирование, базовый мониторинг контейнеров | Стенды тестирования, интеграционные контуры, предварительная валидация конфигов |
| **On-Premise Kubernetes** | Автомасштабирование (HPA), управление через Helm и OpenTelemetry Operator, встроенная балансировка Service | Оверхед CNI, дополнительный сетевой переход (hop), сложность отладки сети ядра | Микросервисные платформы с динамической нагрузкой, стандартизированный мониторинг |

### Сетевая топология и назначение портов

В Jaeger v2 задействованы сетевые порты на базе спецификации OpenTelemetry:

| Порт | Протокол | Компонент / Роль | Назначение |
| :--- | :--- | :--- | :--- |
| **4317** | TCP (gRPC) | OTLP Receiver | Прием телеметрии от сервисов и агентов по gRPC |
| **4318** | TCP (HTTP) | OTLP Receiver | Прием телеметрии от сервисов по HTTP (JSON/Protobuf) |
| **16686** | TCP (HTTP) | `jaeger_query` Extension | Web UI интерфейс поиска трейсов и HTTP Query API |
| **16685** | TCP (gRPC) | `jaeger_query` Extension | Внутренний gRPC Query API для интеграции с Grafana |
| **13133** | TCP (HTTP) | `healthcheckv2` Extension | Проверка работоспособности (Liveness/Readiness probes) |
| **8888** | TCP (HTTP) | Prometheus Exporter | Метрики состояния самого процесса Jaeger v2 |
| **9000** | TCP (Native) | ClickHouse Server | Исходящее подключение к СУБД от Collector/Ingester/Query |
| **9092** | TCP (Kafka) | Apache Kafka Brokers | Исходящее подключение Producer (Collector) и Consumer (Ingester) |

```
                       Сетевая схема взаимодействия компонентов
                       
   [Микросервисы / SDK]          [Grafana / SRE Инженеры]
            │                                    │
            │ OTLP gRPC (4317)                   │ HTTP UI (16686)
            ▼                                    ▼
┌─────────────────────────┐          ┌─────────────────────────┐
│     Jaeger Collector    │          │       Jaeger Query      │
│  (порт метрик: 8888)    │          │  (порт метрик: 8888)    │
└────────────┬────────────┘          └────────────▲────────────┘
             │                                    │
    ┌────────┴────────┐                           │
    │ Прямая запись   │ Буферизация               │ Чтение трейсов
    │ (Direct Mode)   │ (Streaming Mode)          │ (Query)
    ▼                 ▼                           │
┌──────────────┐   ┌───────────────────────┐      │
│  ClickHouse  │   │     Apache Kafka      │      │
│     СУБД     │   │ (топик: jaeger-spans) │      │
└──────▲───────┘   └───────────┬───────────┘      │
       │                       │                  │
       │ Запись пачками        │ Вычитывание      │
       │                       ▼                  │
       │           ┌───────────────────────┐      │
       └───────────┤    Jaeger Ingester    │      │
                   │  (порт метрик: 8888)  │      │
                   └───────────────────────┘      │
                               │                  │
                               └──────────────────┘
```

### Выбор топологии: Direct Storage против Kafka Streaming

1. **Direct Storage Topology (Прямая запись):**
   - Коллекторы напрямую форматируют спаны и отправляют пачки запросов в ClickHouse.
   - Минимальная задержка появления трейса в интерфейсе (менее 1 секунды).
   - Меньше компонентов инфраструктуры для обслуживания.
   - *Риск:* Если ClickHouse испытывает перегрузку дискового ввода-вывода (IOPS) во время слияний (merges), внутренние очереди коллекторов переполняются, и коллекторы начинают отбрасывать спаны при помощи `memory_limiter`.

2. **Streaming Topology (Буферизация через Kafka):**
   - Коллекторы принимают OTLP и сразу пересылают данные в Kafka без сложной обработки.
   - Ingester работает с постоянной комфортной для ClickHouse скоростью, сбрасывая спаны большими батчами.
   - Защита от пиковых нагрузок: при всплеске трафика в 10 раз данные оседают в партициях Kafka и догоняются по мере спада.
   - *Компромисс:* Задержка появления спана в UI может составлять от 2 до 10 секунд при нормальной работе и часы при ликвидации отставания (lag).

---

## Подготовка окружения

### Системные требования для On-Premise узлов

| Роль инстанса v2 | CPU | RAM | Диск | Сетевой интерфейс |
| :--- | :--- | :--- | :--- | :--- |
| **All-in-one** | 1–2 ядра | 2–4 ГБ | 20 ГБ SSD (для Badger) | 1 Гбит/с |
| **Collector Node** | 4–8 ядер | 8–16 ГБ | 50 ГБ SSD (ОС и логи) | 10 Гбит/с |
| **Ingester Node** | 4–8 ядер | 8–16 ГБ | 50 ГБ SSD (ОС и логи) | 10 Гбит/с |
| **Query Node** | 2–4 ядра | 4–8 ГБ | 20 ГБ SSD | 1 Гбит/с |

### Тюнинг параметров ядра Linux (sysctl)

Для серверов Collector под высокой нагрузкой (большое количество постоянных TCP-соединений от микросервисов) необходимо оптимизировать сетевой стек в `/etc/sysctl.d/99-jaeger.conf`:

```ini
# Максимальное число открытых дескрипторов в системе
fs.file-max = 2097152

# Увеличение длины очереди входящих соединений
net.core.somaxconn = 32768
net.ipv4.tcp_max_syn_backlog = 16384

# Буферы приема и передачи сокетов
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# Повторное использование сокетов в состоянии TIME_WAIT
net.ipv4.tcp_tw_reuse = 1
```

Применение параметров ядра:
```bash
sysctl -p /etc/sysctl.d/99-jaeger.conf
# → fs.file-max = 2097152
# → net.core.somaxconn = 32768
# → net.ipv4.tcp_max_syn_backlog = 16384
# → net.core.rmem_max = 16777216
# → net.core.wmem_max = 16777216
# → net.ipv4.tcp_rmem = 4096 87380 16777216
# → net.ipv4.tcp_wmem = 4096 65536 16777216
# → net.ipv4.tcp_tw_reuse = 1
```

### Проверка окружения перед установкой

```bash
# 1. Проверка доступности портов
ss -tulpn | grep -E "4317|4318|16686|13133"
# → (вывод пуст, порты свободны)

# 2. Проверка аппаратных ресурсов
free -h
# →               total        used        free      shared  buff/cache   available
# → Mem:           15Gi       1.2Gi        12Gi       2.0Mi       2.1Gi        14Gi

# 3. Проверка установленного лимита открытых файлов
ulimit -n
# → 65535
```

---

## Практические сценарии

### Сценарий 1: Локальное и изолированное развертывание через Docker Compose (All-in-one с Badger)

Используется для стендов интеграционного тестирования, отладки телеметрии в закрытых контурах без внешней СУБД. Хранилище Badger сохраняет данные между перезапусками контейнера на примонтированном томе.

```yaml
# /opt/jaeger/docker-compose.yml
services:
  jaeger:
    image: jaegertracing/jaeger:2.3.0
    container_name: jaeger-all-in-one
    restart: unless-stopped
    command: ["--config=/etc/jaeger/config.yaml"]
    ports:
      - "4317:4317"     # OTLP gRPC
      - "4318:4318"     # OTLP HTTP
      - "16686:16686"   # Jaeger Web UI / HTTP API
      - "13133:13133"   # Healthcheck probe
      - "8888:8888"     # Prometheus метрики
    environment:
      - GOMEMLIMIT=1800MiB
      - GOGC=100
    volumes:
      - ./config.yaml:/etc/jaeger/config.yaml:ro
      - jaeger-data:/var/lib/jaeger/data
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: 2048M
        reservations:
          cpus: "0.5"
          memory: 512M
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:13133/"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 5s

volumes:
  jaeger-data:
    driver: local
```

Конфигурационный файл All-in-one с Badger:

```yaml
# /opt/jaeger/config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    send_batch_size: 1024
    timeout: 1s

extensions:
  healthcheckv2:
    endpoint: 0.0.0.0:13133
  jaeger_storage:
    backends:
      badger_store:
        badger:
          ephemeral: false
          directory_key: /var/lib/jaeger/data/keys
          directory_value: /var/lib/jaeger/data/values
          maintenance_interval: 5m
  jaeger_query:
    storage:
      traces: badger_store
    http:
      endpoint: 0.0.0.0:16686

exporters:
  jaeger_storage_exporter:
    trace_storage: badger_store

service:
  extensions: [healthcheckv2, jaeger_storage, jaeger_query]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [jaeger_storage_exporter]
  telemetry:
    metrics:
      readers:
        - pull:
            exporter:
              prometheus:
                host: 0.0.0.0
                port: 8888
```

**Валидация запуска:**

```bash
# 1. Запуск стека в фоновом режиме
docker compose -f /opt/jaeger/docker-compose.yml up -d
# → [+] Running 2/2
# →  ✔ Volume jaeger_jaeger-data        Created
# →  ✔ Container jaeger-all-in-one      Started

# 2. Проверка состояния здоровья контейнера
docker compose -f /opt/jaeger/docker-compose.yml ps
# → NAME                IMAGE                          COMMAND                  SERVICE   CREATED         STATUS                    PORTS
# → jaeger-all-in-one   jaegertracing/jaeger:2.3.0     "/go/bin/jaeger --co…"   jaeger    5 seconds ago   Up 4 seconds (healthy)    0.0.0.0:4317->4317/tcp, ...

# 3. Отправка тестового спана по OTLP HTTP
curl -s -X POST http://localhost:4318/v1/traces \
  -H "Content-Type: application/json" \
  -d '{"resourceSpans":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"smoke-test"}}]},"scopeSpans":[{"spans":[{"traceId":"5b8aa5a2d2c872e8329c431416d7351f","spanId":"051581bf3fe55c1b","name":"test-call","kind":1,"startTimeUnixNano":"1700000000000000000","endTimeUnixNano":"1700000000100000000","status":{"code":1}}]}]}]}'
# → {}

# 4. Проверка появления сервиса через Query API
curl -s http://localhost:16686/api/services
# → {"data":["smoke-test"],"total":1,"limit":0,"offset":0,"errors":null}
```

---

### Сценарий 2: Развертывание на Bare-Metal / Виртуальных машинах через Systemd (On-Premise)

Классический подход для корпоративной инфраструктуры: бинарник разворачивается непосредственно в ОС Linux, управляется демоном systemd с жестким контролем дескрипторов и памяти.

**1. Подготовка окружения и прав доступа:**

```bash
# Создание системной группы и пользователя без оболочки входа
useradd --system --no-create-home --user-group --shell /usr/sbin/nologin jaeger

# Создание служебных каталогов
mkdir -p /etc/jaeger /var/log/jaeger /var/lib/jaeger
chown -R jaeger:jaeger /var/log/jaeger /var/lib/jaeger
chmod 750 /etc/jaeger /var/log/jaeger /var/lib/jaeger

# Установка скомпилированного бинарника Jaeger v2
install -m 755 jaeger /usr/local/bin/jaeger

# Проверка версии
/usr/local/bin/jaeger version
# → jaeger version 2.3.0 (commit: 5a9b7c2, date: 2026-03-20T10:00:00Z)
```

**2. Создание systemd unit-файла Collector (`/etc/systemd/system/jaeger-collector.service`):**

```ini
[Unit]
Description=Jaeger v2 Collector Service
Documentation=https://www.jaegertracing.io/docs/
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=jaeger
Group=jaeger
EnvironmentFile=-/etc/default/jaeger
ExecStart=/usr/local/bin/jaeger --config /etc/jaeger/collector-clickhouse.yaml
Restart=on-failure
RestartSec=5s

# Ограничения файловых дескрипторов и ресурсов процесса
LimitNOFILE=65536
LimitNPROC=32768
LimitMEMLOCK=infinity

# Защита памяти через cgroups v2
MemoryHigh=7G
MemoryMax=8G

# Корректный останов для сброса буферов конвейера
KillSignal=SIGTERM
TimeoutStopSec=30s
ExecStop=/bin/kill -s SIGTERM $MAINPID

# Изоляция и безопасность службы
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log/jaeger /var/lib/jaeger
ReadOnlyPaths=/etc/jaeger
PrivateTmp=true
ProtectKernelTunables=true
ProtectControlGroups=true
CapabilityBoundingSets=

[Install]
WantedBy=multi-user.target
```

**3. Создание переменного окружения (`/etc/default/jaeger`):**

```bash
# Настройки Go Runtime под сервер с 8 ГБ RAM
GOMEMLIMIT=6800MiB
GOGC=100
```

**4. Конфигурация коллектора (`/etc/jaeger/collector-clickhouse.yaml`):**

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 80
    spike_limit_percentage: 20
  batch:
    send_batch_size: 2048
    timeout: 1s

extensions:
  healthcheckv2:
    endpoint: 0.0.0.0:13133
  jaeger_storage:
    backends:
      clickhouse_backend:
        clickhouse:
          endpoint: "tcp://192.168.10.20:9000"
          database: "jaeger_v2"
          username: "jaeger_writer"
          password: "WriterSecretPassword123"
          connection_params:
            dial_timeout: "5s"
            compress: "lz4"

exporters:
  jaeger_storage_exporter:
    trace_storage: clickhouse_backend
    queue:
      num_consumers: 16
      queue_size: 2000
    retry_on_failure:
      enabled: true
      initial_interval: 1s
      max_interval: 10s
      max_elapsed_time: 30s

service:
  extensions: [healthcheckv2, jaeger_storage]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [jaeger_storage_exporter]
  telemetry:
    metrics:
      level: detailed
      readers:
        - pull:
            exporter:
              prometheus:
                host: 0.0.0.0
                port: 8888
    logs:
      level: info
```

**5. Запуск службы и валидация:**

```bash
# Активация и запуск systemd сервиса
systemctl daemon-reload
systemctl enable --now jaeger-collector.service
# → Created symlink /etc/systemd/system/multi-user.target.wants/jaeger-collector.service → /etc/systemd/system/jaeger-collector.service.

# Проверка статуса
systemctl status jaeger-collector.service
# → ● jaeger-collector.service - Jaeger v2 Collector Service
# →      Loaded: loaded (/etc/systemd/system/jaeger-collector.service; enabled; preset: enabled)
# →      Active: active (running) since Mon 2026-10-12 14:00:00 MSK; 10s ago
# →    Main PID: 14210 (jaeger)
# →       Tasks: 14 (limit: 32768)
# →      Memory: 112.4M (peak: 120.1M, max: 8.0G)
# →         CPU: 180ms
# →      CGroup: /system.slice/jaeger-collector.service
# →              └─14210 /usr/local/bin/jaeger --config /etc/jaeger/collector-clickhouse.yaml

# Проверка readiness через локальный сокет
curl -i http://localhost:13133/
# → HTTP/1.1 200 OK
# → Content-Type: application/json
# → Date: Mon, 12 Oct 2026 11:00:05 GMT
# → Content-Length: 0
```

---

### Сценарий 3: Распределенное Production-развертывание с ClickHouse (Direct Storage)

В распределенной среде функции разделены: пул нод **Collector** принимает спаны от приложений и пишет в ClickHouse; независимый пул нод **Query** предоставляет UI и API аналитикам и Grafana. Перед пулом коллекторов настраивается L4/L7 балансировщик (NGINX или HAProxy).

```
[Микросервисы] ─────► [NGINX / HAProxy L4:4317] ─────┬──► [Jaeger Collector Node 1] ───┐
                                                      └──► [Jaeger Collector Node 2] ───┼─► [ClickHouse Cluster]
                                                                                        │
[SRE / Grafana] ────► [NGINX L7:16686] ──────────────────► [Jaeger Query Node 1] ───────┘
```

**1. Конфигурация Query Node (`/etc/jaeger/query-clickhouse.yaml`):**

```yaml
extensions:
  healthcheckv2:
    endpoint: 0.0.0.0:13133
  jaeger_storage:
    backends:
      clickhouse_read:
        clickhouse:
          endpoint: "tcp://192.168.10.20:9000"
          database: "jaeger_v2"
          username: "jaeger_reader"
          password: "ReaderSecretPassword123"
  jaeger_query:
    storage:
      traces: clickhouse_read
    ui:
      config_file: /etc/jaeger/ui-config.json
    http:
      endpoint: 0.0.0.0:16686
    grpc:
      endpoint: 0.0.0.0:16685

service:
  extensions: [healthcheckv2, jaeger_storage, jaeger_query]
  pipelines:
    traces:
      receivers: [nop]
      processors: []
      exporters: [nop]
  telemetry:
    metrics:
      readers:
        - pull:
            exporter:
              prometheus:
                host: 0.0.0.0
                port: 8888
```

**2. Настройка NGINX в качестве балансировщика gRPC (OTLP 4317) и HTTP (UI 16686):**

```nginx
# /etc/nginx/conf.d/jaeger-lb.conf
# Балансировка gRPC потока OTLP (Stream L4 балансировка)
stream {
    upstream jaeger_collectors_grpc {
        least_conn;
        server 192.168.10.11:4317 max_fails=3 fail_timeout=5s;
        server 192.168.10.12:4317 max_fails=3 fail_timeout=5s;
    }

    server {
        listen 4317;
        proxy_pass jaeger_collectors_grpc;
        proxy_timeout 600s;
        proxy_connect_timeout 2s;
    }
}

# HTTP проксирование Web UI
http {
    upstream jaeger_query_http {
        server 192.168.10.15:16686;
        server 192.168.10.16:16686 backup;
    }

    server {
        listen 80;
        server_name jaeger.corp.internal;

        location / {
            proxy_pass http://jaeger_query_http;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }
    }
}
```

**Валидация распределенного контура:**

```bash
# 1. Проверка таблиц в ClickHouse
clickhouse-client --host 192.168.10.20 --user jaeger_writer --password WriterSecretPassword123 \
  --query "SELECT count() FROM jaeger_v2.spans"
# → 1420580

# 2. Проверка метрик записи на ноде Collector
curl -s http://192.168.10.11:8888/metrics | grep -E "otelcol_exporter_sent_spans|otelcol_exporter_enqueue_failed"
# → otelcol_exporter_sent_spans{exporter="jaeger_storage_exporter"} 1420580
# → otelcol_exporter_enqueue_failed_spans{exporter="jaeger_storage_exporter"} 0

# 3. Проверка доступности UI через балансировщик
curl -s -I http://jaeger.corp.internal/
# → HTTP/1.1 200 OK
# → Content-Type: text/html; charset=utf-8
```

---

### Сценарий 4: Высоконагруженная Streaming-архитектура с Kafka и Ingester

При экстремальном потоке спанов (десятки и сотни тысяч спанов в секунду) база данных не должна быть прямой точкой отказа. Коллекторы выступают продюсерами в Kafka, а Ingester вычитывает сообщения фиксированными пулами консьюмеров.

```
[SDK / Агенты] ─► [Jaeger Collector] ─► [Kafka Broker (топик: jaeger-spans)] ─► [Jaeger Ingester] ─► [ClickHouse]
```

**1. Конфигурация Collector (Kafka Producer):**

```yaml
# /etc/jaeger/collector-kafka.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 85
    spike_limit_percentage: 15
  batch:
    send_batch_size: 4096
    timeout: 500ms

exporters:
  kafka:
    brokers:
      - "192.168.10.31:9092"
      - "192.168.10.32:9092"
      - "192.168.10.33:9092"
    topic: "jaeger-spans"
    encoding: "otlp_proto"
    producer:
      compression: "snappy"
      max_message_bytes: 1048576
      required_acks: 1
      flush_max_messages: 2048

service:
  extensions: [healthcheckv2]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [kafka]
  telemetry:
    metrics:
      readers:
        - pull:
            exporter:
              prometheus:
                host: 0.0.0.0
                port: 8888
```

**2. Конфигурация Ingester (Kafka Consumer):**

```yaml
# /etc/jaeger/ingester-clickhouse.yaml
receivers:
  kafka:
    brokers:
      - "192.168.10.31:9092"
      - "192.168.10.32:9092"
      - "192.168.10.33:9092"
    topic: "jaeger-spans"
    encoding: "otlp_proto"
    group_id: "jaeger-ingester"
    initial_offset: "latest"
    session_timeout: 30s
    heartbeat_interval: 5s

processors:
  batch:
    send_batch_size: 8192
    timeout: 2s

extensions:
  healthcheckv2:
    endpoint: 0.0.0.0:13133
  jaeger_storage:
    backends:
      clickhouse_backend:
        clickhouse:
          endpoint: "tcp://192.168.10.20:9000"
          database: "jaeger_v2"
          username: "jaeger_writer"
          password: "WriterSecretPassword123"

exporters:
  jaeger_storage_exporter:
    trace_storage: clickhouse_backend
    queue:
      num_consumers: 32
      queue_size: 5000

service:
  extensions: [healthcheckv2, jaeger_storage]
  pipelines:
    traces:
      receivers: [kafka]
      processors: [batch]
      exporters: [jaeger_storage_exporter]
  telemetry:
    metrics:
      readers:
        - pull:
            exporter:
              prometheus:
                host: 0.0.0.0
                port: 8888
```

**3. Валидация потока и контроль лага Kafka:**

```bash
# 1. Проверка создания топика и количества партиций (минимум 12-24 для параллелизма)
kafka-topics.sh --bootstrap-server 192.168.10.31:9092 --describe --topic jaeger-spans
# → Topic: jaeger-spans  TopicId: QwErTy12345  PartitionCount: 12  ReplicationFactor: 3  Configs: min.insync.replicas=2,cleanup.policy=delete,retention.ms=86400000

# 2. Мониторинг Consumer Lag группы jaeger-ingester
kafka-consumer-groups.sh --bootstrap-server 192.168.10.31:9092 --describe --group jaeger-ingester
# → GROUP           TOPIC           PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID     HOST            CLIENT-ID
# → jaeger-ingester jaeger-spans    0          1045230         1045232         2               ingester-node-1 /192.168.10.41  consumer-1
# → jaeger-ingester jaeger-spans    1          984320          984320          0               ingester-node-2 /192.168.10.42  consumer-2

# 3. Проверка скорости потребления сообщений Ingester
curl -s http://192.168.10.41:8888/metrics | grep otelcol_receiver_accepted_spans
# → otelcol_receiver_accepted_spans{receiver="kafka",transport="kafka"} 84210
```

---

### Сценарий 5: Развертывание в On-Premise Kubernetes через Helm

Для автоматизации оркестрации в кластерах Kubernetes используется официальный Helm-чарт `jaegertracing/jaeger`. Для деталей интеграции через CRD и OpenTelemetry Operator см. **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**.

**1. Продакшн манифест `values-production.yaml`:**

```yaml
# values-production.yaml
provisionDataStore:
  cassandra: false
  elasticsearch: false

storage:
  type: clickhouse
  clickhouse:
    endpoint: "tcp://clickhouse-cluster.db.svc.cluster.local:9000"
    database: "jaeger_v2"
    secretRef:
      name: jaeger-clickhouse-credentials

collector:
  enabled: true
  replicaCount: 3
  resources:
    limits:
      cpu: 2000m
      memory: 4Gi
    requests:
      cpu: 500m
      memory: 1Gi
  autoscaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 10
    targetCPUUtilizationPercentage: 75
  podDisruptionBudget:
    minAvailable: 2
  affinity:
    podAntiAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 100
          podAffinityTerm:
            labelSelector:
              matchExpressions:
                - key: app.kubernetes.io/component
                  operator: In
                  values: [collector]
            topologyKey: "kubernetes.io/hostname"

query:
  enabled: true
  replicaCount: 2
  resources:
    limits:
      cpu: 1000m
      memory: 2Gi
    requests:
      cpu: 200m
      memory: 512Mi
  podDisruptionBudget:
    minAvailable: 1
```

**2. Установка чарта в кластер:**

```bash
# 1. Добавление репозитория
helm repo add jaegertracing https://jaegertracing.github.io/helm-charts
helm repo update
# → Successfully got an update from the "jaegertracing" chart repository

# 2. Установка релиза
helm upgrade --install jaeger jaegertracing/jaeger \
  --namespace observability --create-namespace \
  -f values-production.yaml
# → Release "jaeger" has been upgraded. Happy Helming!
# → STATUS: deployed
# → REVISION: 1

# 3. Проверка статуса подов
kubectl get pods -n observability -l app.kubernetes.io/name=jaeger
# → NAME                               READY   STATUS    RESTARTS   AGE
# → jaeger-collector-58c4959bfb-2z2l7   1/1     Running   0          30s
# → jaeger-collector-58c4959bfb-6dx5f   1/1     Running   0          30s
# → jaeger-collector-58c4959bfb-x7m8p   1/1     Running   0          30s
# → jaeger-query-7bd4c849cf-h7v21       1/1     Running   0          30s
# → jaeger-query-7bd4c849cf-plm99       1/1     Running   0          30s
```

---

## Операции и команды

Сводная таблица основных административных команд для обслуживания инсталляции Jaeger v2:

| Действие | Команда | Назначение / Ожидаемый результат |
| :--- | :--- | :--- |
| **Проверка синтаксиса** | `jaeger validate --config /etc/jaeger/config.yaml` | Проверка валидности YAML схемы до применения конфигурации |
| **Статус службы systemd** | `systemctl status jaeger-collector.service` | Инспекция активного состояния процесса, PID и потребления RAM |
| **Логи процесса** | `journalctl -u jaeger-collector.service -f --output=cat` | Чтение логов в реальном времени |
| **Liveness Probe** | `curl -i http://localhost:13133/` | Проверка готовности конвейера (должен вернуть `HTTP 200 OK`) |
| **Счетчик принятых спанов** | `curl -s http://localhost:8888/metrics \| grep otelcol_receiver_accepted_spans` | Количество успешно принятых спанов по протоколам |
| **Счетчик отброшенных спанов** | `curl -s http://localhost:8888/metrics \| grep otelcol_processor_dropped_spans` | Обнаружение срабатывания `memory_limiter` |
| **Очередь экспортера** | `curl -s http://localhost:8888/metrics \| grep otelcol_exporter_queue_size` | Заполненность внутреннего буфера записи в БД |
| **Лаг партиций Kafka** | `kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group jaeger-ingester` | Инспекция отставания консьюмеров от продюсеров |
| **Количество спанов в БД** | `clickhouse-client --query "SELECT count() FROM jaeger_v2.spans"` | Подтверждение физической записи спанов в базу |

---

## Типичные проблемы и устранение неполадок

| Проблема | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Collector завершается по OOM (Exit Code 137)** | Отсутствует процессор `memory_limiter`, или его порог выше cgroup `MemoryMax` | `dmesg -T \| grep -i oom` или `journalctl -u jaeger-collector -e` | Настроить `memory_limiter` на уровень `80%`, задать переменную окружения `GOMEMLIMIT` на 85% от физического лимита памяти |
| **Ошибка `too many open files`** | Исчерпаны дескрипторы сокетов при наплыве микросервисов | `cat /proc/$(pgrep jaeger)/limits \| grep "Max open files"` | Увеличить `LimitNOFILE=65536` в systemd unit и `sysctl fs.file-max` |
| **Рост счетчика `dropped_spans`** | Бэкенд ClickHouse не успевает выполнять сбросы, очереди экспортера заполнены | `curl -s localhost:8888/metrics \| grep otelcol_processor_dropped` | Увеличить число воркеров `num_consumers`, оптимизировать ClickHouse MergeTree или внедрить буферизацию через Kafka |
| **Kafka Consumer Lag растет** | Недостаточно партиций в Kafka, число инстансов Ingester превышает число партиций | `kafka-consumer-groups.sh --describe --group jaeger-ingester` | Добавить партиции в топик `jaeger-spans`, масштабировать ноды Ingester до числа партиций |
| **Конфликт портов 4317 / 4318** | Порты уже заняты другим процессом (например, ранее установленным OTel Collector) | `ss -tulpn \| grep -E "4317\|4318"` | Остановить конкурирующий процесс или переназначить endpoint в секции `receivers.otlp` |
| **UI открывается, но сервисы не найдены** | Не настроен или не отвечает бэкенд `clickhouse_read` в секции `jaeger_storage` | `curl -i http://localhost:16686/api/services` | Проверить доступность СУБД по порту 9000, корректность логина/пароля и наличие записей в таблице `jaeger_v2.spans` |
| **Clock Skew (спаны с отрицательным временем)** | Рассинхронизация часов между гипервизорами и серверами | `chronyc tracking` или `timedatectl status` | Настроить синхронизацию времени по протоколу NTP на всех узлах через `chrony` |

### Практическая диагностика сбоя записи

```bash
# 1. Проверка состояния очередей экспортера
curl -s http://localhost:8888/metrics | grep -E "otelcol_exporter_queue_capacity|otelcol_exporter_queue_size"
# → otelcol_exporter_queue_capacity{exporter="jaeger_storage_exporter"} 2000
# → otelcol_exporter_queue_size{exporter="jaeger_storage_exporter"} 1984

# 2. Проверка ошибок записи в логах
journalctl -u jaeger-collector.service --since "10 minutes ago" | grep -i "failed to export"
# → 2026-10-12T14:15:22.102Z error exporterhelper/queued_retry.go:435 Exporting failed {"exporter": "jaeger_storage_exporter", "error": "dial tcp 192.168.10.20:9000: i/o timeout"}

# 3. Проверка сетевой связности с портом ClickHouse
nc -zvw3 192.168.10.20 9000
# → Connection to 192.168.10.20 9000 port [tcp/cslistener] succeeded!
```

---

## Лучшие практики и очистка

### Рекомендации SRE и DevOps

1. **Разделение ролей в Production:** Никогда не запускайте All-in-one на production-контурах. Разделяйте Collector (прием и запись) и Query (чтение), чтобы интенсивные поисковые запросы аналитиков не приводили к деградации приема спанов от боевых сервисов.
2. **Обязательный Memory Limiter:** Процессор `memory_limiter` должен всегда стоять первым в секции `processors: [...]` перед батчером. Это гарантирует выживание процесса при внезапных пятикратных всплесках трафика.
3. **Размер батчей:** При использовании ClickHouse выставляйте `send_batch_size` от 2048 до 8192 спанов и таймаут 1–2 секунды. ClickHouse спроектирован для пакетной вставки больших блоков и деградирует при поштучной записи.
4. **Graceful Shutdown:** При обновлении версий или конфигураций всегда настраивайте отправку `SIGTERM` и задержку `TimeoutStopSec=30s`, чтобы экспортеры успели сбросить очереди в БД без потери накопленных трейсов.
5. **Мониторинг алертов:** Ключевые метрики для настройки оповещений Prometheus Alertmanager:
   - `rate(otelcol_processor_dropped_spans[5m]) > 0` — признак перегрузки узла и потери телеметрии.
   - `otelcol_exporter_queue_size / otelcol_exporter_queue_capacity > 0.8` — угроза переполнения очередей.
   - `rate(otelcol_receiver_refused_spans[5m]) > 0` — коллектор отказывает клиентам в приеме.
6. **Политики TTL в хранилище:** Для on-premise СУБД всегда активируйте политику автоматического удаления данных на уровне таблиц ClickHouse (например, `TTL toDateTime(timestamp) + INTERVAL 14 DAY DELETE`). См. подробнее: **[Storage Deep Dive для Jaeger](./jaeger_storage_deep_dive.md)**.

### Очистка тестового окружения

```bash
# 1. Остановка и удаление контейнеров Docker Compose вместе с томами данных
docker compose -f /opt/jaeger/docker-compose.yml down -v
# → [+] Running 2/2
# →  ✔ Container jaeger-all-in-one   Removed
# →  ✔ Volume jaeger_jaeger-data     Removed

# 2. Остановка и отключение службы systemd
systemctl stop jaeger-collector.service
systemctl disable jaeger-collector.service
# → Removed "/etc/systemd/system/multi-user.target.wants/jaeger-collector.service".

# 3. Удаление временных файлов и данных Badger
rm -rf /var/lib/jaeger/data/*
rm -rf /var/log/jaeger/*

# 4. Удаление релиза Helm из кластера Kubernetes
helm uninstall jaeger -n observability
# → release "jaeger" uninstalled
```

---

## Дополнительная информация

**Смежные материалы базы знаний:**

* Базовые принципы и назначение трассировки: **[Обзор Jaeger](./jaeger_overview.md)**
* Внутренние конвейеры и компоненты Jaeger v2: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Специфика СУБД ClickHouse, Elasticsearch и Badger: **[Storage Deep Dive для Jaeger](./jaeger_storage_deep_dive.md)**
* Развертывание в Kubernetes и OpenTelemetry Operator: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**
* Инженерный расчет ресурсов и нагрузки: **[Capacity Planning для Jaeger](./jaeger_capacity_planning.md)**
* Отказоустойчивость, Multi-DC и DR сценарии: **[High Availability и DR](./jaeger_high_availability.md)**
* Защита контуров, mTLS и аутентификация: **[Security Hardening для Jaeger](./jaeger_security_hardening.md)**
* Тонкая настройка сетевых протоколов OTLP: **[OTLP Configuration для Jaeger](./jaeger_otlp_configuration.md)**
* Миграция конфигураций с версии v1 на v2: **[Миграция Jaeger v1 → v2](./jaeger_migration_v1_to_v2.md)**
* Интеграция с визуализацией в дашбордах: **[Интеграция Jaeger с Grafana](./jaeger_grafana_integration.md)**
* Спецификация HTTP и gRPC API чтения трейсов: **[Query API Jaeger](./jaeger_query_api.md)**

### См. также

* [Official Jaeger Deployment Guide](https://www.jaegertracing.io/docs/next/deployment/)
* [Jaeger v2 Architecture Documentation](https://www.jaegertracing.io/docs/next/architecture/)
* [OpenTelemetry Collector Configuration Specification](https://opentelemetry.io/docs/collector/configuration/)
