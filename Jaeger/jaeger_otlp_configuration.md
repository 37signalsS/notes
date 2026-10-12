# OTLP Configuration для Jaeger

**Актуально для:** Jaeger v2.x / OpenTelemetry Protocol v1.x

> **Важно:** Документация описывает детальную конфигурацию протокола OTLP для **Jaeger v2** (архитектура Unified Binary на базе каркаса OpenTelemetry Collector). В Jaeger v2 протокол OTLP (OpenTelemetry Protocol) является основным нативным протоколом для приема распределенных трассировок. Все архитектурные решения, сетевые параметры и практические сценарии ориентированы на on-premise и bare-metal инфраструктуру (Linux, systemd, Docker, локальный Kubernetes) без применения проприетарных облачных сервисов.

**OTLP Configuration для Jaeger** — это регламент настройки и оптимизации протокола OpenTelemetry Protocol на уровне сетевых приемников (receivers) Jaeger Collector. Конфигурация управляет параметрами gRPC и HTTP транспортов, компрессией входящих пакетов (zstd, gzip, snappy), политиками взаимной TLS-аутентификации (mTLS), защитой памяти процесса от OOM (backpressure через `memory_limiter`), а также системными буферами сокетов ядра Linux. Корректный тюнинг OTLP-конвейера исключает потерю спанов при пиковых нагрузках, минимизирует сетевой оверхед и предотвращает каскадные сбои распределенной системы сбора телеметрии.

Общая спецификация и формат протокола: **[Протокол OTLP](../OpenTelemetry/otlp_protocol.md)**.  
Архитектура компонентов и пайплайнов v2: **[Архитектура Jaeger](./jaeger_architecture.md)**.  
Варианты развертывания на on-premise инфраструктуре: **[Варианты развертывания Jaeger](./jaeger_deployment_options.md)**.  
Сетевая безопасность и харденинг: **[Безопасность и харденинг Jaeger](./jaeger_security_hardening.md)**.  
Расчет емкости и сайзинг буферов: **[Планирование емкости Jaeger](./jaeger_capacity_planning.md)**.  
Отказоустойчивость и балансировка: **[Отказоустойчивость Jaeger](./jaeger_high_availability.md)**.  
Организация и схемы хранения трейсов: **[Storage Deep Dive для Jaeger](./jaeger_storage_deep_dive.md)**.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **OTLP (OpenTelemetry Protocol)** | Стандартизированный протокол передачи телеметрии (трассировки, метрики, логи, профили) на базе сериализации Protocol Buffers (Protobuf) |
| **OTLP gRPC Receiver** | Сетевой приемник OTLP на TCP-порту 4317. Использует протокол HTTP/2 с бинарными фреймами, двунаправленным стримингом и мультиплексированием запросов в рамках одного соединения |
| **OTLP HTTP Receiver** | Сетевой приемник OTLP на TCP-порту 4318. Принимает данные через POST-запросы к эндпоинту `/v1/traces` с бинарным Protobuf (`application/x-protobuf`) или JSON (`application/json`) |
| **Payload Compression** | Механизм сжатия сетевых пакетов на лету (алгоритмы `zstd`, `gzip`, `snappy`). Снижает объем сетевого трафика в 2–10 раз за счет расхода процессорного времени |
| **mTLS (Mutual TLS)** | Двусторонняя криптографическая аутентификация: клиент и сервер проверяют X.509 сертификаты друг друга перед установкой защищенной TCP-сессии |
| **Bearer Token Auth** | Механизм проверки подлинности через статический или ротируемый токен в HTTP-заголовке `Authorization: Bearer <token>`, реализуемый расширением `bearertokenauth` |
| **Backpressure** | Механизм обратного давления, при котором приемник сигнализирует клиентам о невозможности обработки входящего потока (коды gRPC `ResourceExhausted` и HTTP `429 Too Many Requests`) |
| **Load Shedding** | Контролируемый сброс избыточного трафика при исчерпании лимитов памяти или процессора во избежание аварийной остановки процесса операционной системой (OOMKilled) |
| **HTTP/2 Keepalive** | Протокольный механизм проверки жизнеспособности TCP-соединения с помощью PING-фреймов. Требует согласования политик на клиенте и сервере во избежание ошибок `GOAWAY` |
| **Flow Control Window** | Ограничение объема неподтвержденных данных на уровне потока (`InitialStreamWindowSize`) и соединения (`InitialConnWindowSize`) в протоколе HTTP/2 |
| **BatchSpanProcessor** | Клиентский компонент OpenTelemetry SDK, накапливающий спаны в кольцевом буфере памяти приложения и отправляющий их пачками по таймеру или при заполнении лимита |

---

## Базовые концепции

### Архитектура конвейера OTLP в Jaeger v2

В Jaeger v2 сетевой приемник OTLP базируется на кодовой базе `receiver/otlpreceiver` каркаса OpenTelemetry Collector. Прием спанов интегрирован в сквозной асинхронный пайплайн, где сетевой ввод-вывод изолирован от медленных операций записи в дисковые или сетевые базы данных (ClickHouse, Elasticsearch).

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                Входящий сетевой трафик                                      │
│                                                                                             │
│   [App 1 (OTel Go SDK)] ───────(gRPC 4317 + zstd)────────┐                                  │
│   [App 2 (OTel Java SDK)] ────(HTTP 4318 + Protobuf)─────┼────────┐                         │
│   [HAProxy / Envoy L7] ───────(gRPC 4317 + mTLS)─────────┘        │                         │
└───────────────────────────────────┬───────────────────────────────┼─────────────────────────┘
                                    │                               │
                                    ▼                               ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 Jaeger v2 Unified Binary                                    │
│                                                                                             │
│  ┌────────────────────── Receivers (otlp) ───────────────────────────────────────────────┐  │
│  │  gRPC Engine (:4317)                        HTTP Engine (:4318)                       │  │
│  │  - HTTP/2 Demux & Decompress (zstd/gzip)    - HTTP/1.1 & HTTP/2 Parser (/v1/traces)   │  │
│  │  - TLS / mTLS Handshake                     - Bearer Token Auth Extractor             │  │
│  │  - Keepalive Enforcement Policy             - Unmarshal Protobuf / JSON Payload       │  │
│  └───────────────────────────────┬───────────────────────────────┬───────────────────────┘  │
│                                  └───────────────┬───────────────┘                          │
│                                                  ▼                                          │
│  ┌────────────────────── Processors (Строгий порядок!) ──────────────────────────────────┐  │
│  │  1. memory_limiter: Проверка лимитов RAM (80% Soft Limit).                            │  │
│  │     Если лимит превышен ──► возврат ResourceExhausted (gRPC) / HTTP 429 Backpressure  │  │
│  │                                                                                       │  │
│  │  2. batch: Буферизация спанов в пачки (send_batch_size: 2048, timeout: 2s)            │  │
│  └───────────────────────────────────────────────┬───────────────────────────────────────┘  │
│                                                  ▼                                          │
│  ┌────────────────────── Exporters (jaeger_storage_exporter) ────────────────────────────┐  │
│  │  - Internal Queue (queue_size: 5000, num_consumers: 16)                              │  │
│  │  - retry_on_failure (initial: 1s, max: 10s, max_elapsed: 30s)                         │  │
│  └───────────────────────────────────────────────┬───────────────────────────────────────┘  │
│                                                  ▼                                          │
│  ┌────────────────────── Extensions (Пул соединений к хранилищу) ────────────────────────┐  │
│  │  jaeger_storage.backends.prod_ch (Драйвер ClickHouse TCP порт 9000)                   │  │
│  └───────────────────────────────────────────────┬───────────────────────────────────────┘  │
└──────────────────────────────────────────────────┼──────────────────────────────────────────┘
                                                   ▼
                                      [ClickHouse Кластер / БД]
```

### Сравнение транспортов OTLP: gRPC, HTTP/Protobuf и HTTP/JSON

Выбор сетевого транспорта определяет утилизацию ресурсов CPU, накладные расходы полосы пропускания и особенности маршрутизации трафика через балансировщики.

| Характеристика | gRPC (`4317`) | HTTP/Protobuf (`4318`) | HTTP/JSON (`4318`) |
| :--- | :--- | :--- | :--- |
| **Сетевой протокол** | HTTP/2 over TCP | HTTP/1.1 или HTTP/2 over TCP | HTTP/1.1 или HTTP/2 over TCP |
| **Формат полезной нагрузки** | Двоичный Protobuf | Двоичный Protobuf | Текстовый JSON |
| **Мультиплексирование** | Да (множество запросов в 1 TCP-сессии) | Только при включенном HTTP/2 | Только при включенном HTTP/2 |
| **Оверхед на сериализацию** | Минимальный (низкая нагрузка на CPU) | Минимальный (низкая нагрузка на CPU) | Высокий (парсинг строк, аллокации RAM) |
| **Поддержка сжатия** | `zstd`, `gzip`, `snappy` | `zstd`, `gzip`, `deflate`, `snappy` | `gzip`, `deflate` |
| **Поведение соединений** | Долгоживущие TCP-сессии (Long-lived) | Короткие или Keep-Alive HTTP-сессии | Короткие или Keep-Alive HTTP-сессии |
| **Балансировка нагрузки** | Требует L7 (Envoy, HAProxy) или client-side | Стандартная L4 или L7 балансировка | Стандартная L4 или L7 балансировка |
| **Двунаправленный стриминг** | Поддерживается | Не поддерживается | Не поддерживается |
| **Рекомендация для SRE** | **Основной стандарт для High-Load** | Ограничения сети, firewalls, прокси | Исключительно локальная отладка |

### Параметры конфигурации сетевого приемника (Receiver)

Конфигурация приемника `otlp` описывается в секции `receivers` YAML-манифеста Jaeger v2.

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        # Сетевой адрес и порт прослушивания
        endpoint: 0.0.0.0:4317
        
        # Транспортный протокол (по умолчанию tcp)
        transport: tcp
        
        # Максимальный размер входящего gRPC-сообщения (защита от переполнения буферов)
        max_recv_msg_size_mib: 16
        
        # Максимальное количество параллельных HTTP/2 потоков на одно TCP-соединение
        max_concurrent_streams: 1024
        
        # Размеры системных буферов чтения и записи для сокета (в байтах)
        read_buffer_size: 1048576
        write_buffer_size: 1048576
        
        # Управление жизненным циклом соединений и проверка активности (HTTP/2 Keepalive)
        keepalive:
          server_parameters:
            max_connection_idle: 15m
            max_connection_age: 1h
            max_connection_age_grace: 30s
            time: 2h
            timeout: 20s
          enforcement_policy:
            min_time: 5s
            permit_without_stream: true
            
        # Настройки криптографической защиты TLS / mTLS
        tls:
          cert_file: /etc/jaeger/certs/server.crt
          key_file: /etc/jaeger/certs/server.key
          client_ca_file: /etc/jaeger/certs/ca.crt
          min_version: "1.2"
          reload_interval: 5m
          
        # Передача метаданных входящего контекста (заголовки gRPC) в контекст спанов
        include_metadata: true

      http:
        # Сетевой интерфейс для приема HTTP-трафика
        endpoint: 0.0.0.0:4318
        
        # Лимит размера тела HTTP-запроса (в байтах, например 20 МБ)
        max_request_body_size: 20971520
        
        # Политика Cross-Origin Resource Sharing (CORS) для веб-клиентов
        cors:
          allowed_origins:
            - "https://internal-portal.company.lan"
          allowed_headers:
            - "Authorization"
            - "Content-Type"
            - "User-Agent"
          max_age: 7200
          
        # TLS-конфигурация для HTTP-порта
        tls:
          cert_file: /etc/jaeger/certs/server.crt
          key_file: /etc/jaeger/certs/server.key
          client_ca_file: /etc/jaeger/certs/ca.crt
          min_version: "1.2"
          
        # Дополнительные HTTP-заголовки ответа
        response_headers:
          X-Collector-Provider: "jaeger-v2"
```

### Механика компрессии полезной нагрузки (Compression)

При высокой интенсивности генерации трассировок (более 50 000 спанов/сек) компрессия payload является ключевым фактором сохранения пропускной способности локальной сети:

| Алгоритм | Степень сжатия (Ratio) | Скорость сжатия | Скорость декомпрессии | Нагрузка на CPU Collector | Практическое применение |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **zstd** | Высокая (3.5–5.5x) | Очень высокая | Экстремально высокая | Минимальная | **Промышленный стандарт для High-Load** |
| **snappy** | Умеренная (1.8–2.2x) | Экстремально высокая | Очень высокая | Минимальная | Сети с минимальной latency и избытком полосы |
| **gzip** | Средняя (2.5–3.8x) | Средняя | Средняя | Заметная (CPU-bound) | Устаревшие клиенты, стандартная совместимость |
| **none** | 1.0x (без сжатия) | 0 (нет оверхеда) | 0 (нет оверхеда) | Нулевая | Только localhost/IPC сокеты |

**Принцип работы декомпрессии:**
1. Клиентский OpenTelemetry SDK упаковывает спаны в формат Protobuf и сжимает байтовый массив выбранным алгоритмом.
2. В gRPC-сессии устанавливается заголовок `grpc-encoding: zstd`, а в HTTP-запросе — заголовок `Content-Encoding: zstd`.
3. Сетевой движок `otlp` приемника считывает заголовок, задействует соответствующий декодер из пула декомпрессоров и передает восстановленные байты в Protobuf Unmarshaler.
4. **Защита от Decompression Bombs:** Если распакованный payload превышает лимит `max_recv_msg_size_mib` (или `max_request_body_size`), декодирование прерывается с ошибкой `ResourceExhausted` для предотвращения истощения кучи (heap exhaustion).

### Управление соединениями gRPC и Keepalive (SRE-аспекты)

Поскольку gRPC функционирует поверх HTTP/2, клиенты устанавливают единое долгоживущее TCP-соединение и передают все спаны в мультиплексированных стримах. Это создает две классические проблемы в распределенных средах:

1. **Неравномерное распределение нагрузки (Connection Pinning):**
   Если клиентские поды подключились к инстансам Jaeger Collector в момент запуска, L4-балансировщик (IPVS, Kubernetes Service ClusterIP) не перераспределит трафик при горизонтальном масштабировании коллектора. Для решения этой проблемы в Jaeger v2 настраивается принудительная ротация соединений:
   - `max_connection_age: 1h`: по истечении одного часа коллектор отправляет клиенту HTTP/2 фрейм `GOAWAY`.
   - `max_connection_age_grace: 30s`: время, выделяемое клиенту на завершение активных RPC до физического закрытия TCP-сокета. Клиент прозрачно открывает новое соединение через балансировщик, попадая на наименее нагруженный инстанс.

2. **Ошибки `GOAWAY` и сброс соединений из-за PING-флуда:**
   Если клиентский SDK отправляет keepalive-пинги слишком часто, сервер gRPC расценивает это как атаку и разрывает соединение с кодом `ENHANCE_YOUR_CALM` (`too_many_pings`). Для исключения сбоев на стороне сервера задается строгая политика:
   - `enforcement_policy.min_time: 5s`: минимальный интервал между ping-фреймами от клиента.
   - `enforcement_policy.permit_without_stream: true`: разрешение клиенту проверять активность соединения даже при отсутствии передаваемых спанов.

### Аутентификация и контроль доступа

В on-premise инфраструктуре незащищенный порт 4317 позволяет неавторизованным клиентам внедрять фальшивые трейсы или организовывать DoS-атаку на базу данных. Jaeger v2 поддерживает несколько уровней защиты:

1. **Взаимный TLS (mTLS):** Наиболее надежный метод. Сервер проверяет валидность сертификата клиента по доверенному `client_ca_file`. Подходит для взаимодействия сервер-сервер внутри корпоративного контура.
2. **Bearer Token Authentication:** Проверка статического или ротируемого токена в заголовке `Authorization: Bearer <secret>`. Реализуется подключением расширения `bearertokenauth` к OTLP-ресиверу.
3. **Обратный прокси (Reverse Proxy):** Вынос аутентификации и терминирования TLS на пограничный балансировщик (HAProxy, Nginx) с последующей передачей трафика в локальный порт коллектора по чистому gRPC.

### Механизмы Backpressure, буферизации и защиты от OOM

Для предотвращения падения процесса Jaeger v2 под лавиной входящего трафика критически важно согласовать работу приемников, процессоров и экспортеров:

1. **Первичный рубеж — `memory_limiter` processor:**
   - Обязан находиться **строго первым** в списке `processors`.
   - Если потребление оперативной памяти достигает порога `limit_percentage: 80`, процессор немедленно отклоняет поступившие данные.
   - При отклонении ресивер OTLP возвращает клиенту статус ошибки gRPC `codes.ResourceExhausted` (код 8) или HTTP-код `429 Too Many Requests` с метаданными задержки (`retry-info`).

2. **Реакция клиентского OpenTelemetry SDK:**
   - Получив статус `ResourceExhausted` или `429`, клиентский `BatchSpanProcessor` переходит в режим экспоненциального отката (Exponential Backoff).
   - Если внутренняя очередь спанов приложения (`OTEL_BSP_MAX_QUEUE_SIZE`, по умолчанию 2048) переполняется, клиент отбрасывает новые спаны (`drop_head` или `drop_tail`) локально, не допуская деградации основного бизнес-процесса сервиса.

3. **Вторичный рубеж — внутренние очереди `jaeger_storage_exporter`:**
   - Секция `queue` сглаживает кратковременные задержки ответа ClickHouse.
   - Секция `retry_on_failure` гарантирует повторную отправку пачек спанов при кратковременных сетевых тайм-аутах базы данных.

### Оптимизация сетевого стека Linux (Sysadmin & SRE)

При приеме сотен тысяч спанов в секунду стандартные параметры сетевого стека Linux приводят к дропам пакетов на уровне очередей сокетов (`listen backlog` и `SYN backlog`).

**Необходимый тюнинг ядра (`/etc/sysctl.d/99-jaeger-otlp.conf`):**

```ini
# Максимальный размер очереди соединений (somaxconn)
net.core.somaxconn = 32768

# Максимальный размер очереди полуоткрытых соединений SYN
net.ipv4.tcp_max_syn_backlog = 16384

# Максимальные размеры системных буферов приема и отправки сокетов (16 МБ)
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216

# Автоматическая подстройка буферов TCP: min, default, max
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# Отключение сброса окна TCP после периода простоя (критично для долгоживущих gRPC сессий)
net.ipv4.tcp_slow_start_after_idle = 0

# Разрешение переиспользования сокетов в состоянии TIME_WAIT
net.ipv4.tcp_tw_reuse = 1
```

**Лимиты файловых дескрипторов (systemd):**
Для процесса коллектора необходимо выставить `LimitNOFILE=65536`, так как каждое входящее клиентское соединение и соединение с базой данных потребляет отдельный файловый дескриптор.

---

## Практические сценарии

### Сценарий 1: Высокопроизводительный production OTLP gRPC ресивер на Linux (systemd / bare-metal)

**Контекст:** Развертывание узла Jaeger v2 на выделенном сервере Linux (Debian/Ubuntu/RHEL). Требуется настроить прием трафика OTLP gRPC с компрессией `zstd`, защитой от утечек соединений через keepalive, ограничением памяти коллектора и записью в кластер ClickHouse.

#### 1. Подготовка системных параметров и каталогов

```bash
# Применение параметров сетевого стека
cat << 'EOF' | sudo tee /etc/sysctl.d/99-jaeger-otlp.conf
net.core.somaxconn = 32768
net.ipv4.tcp_max_syn_backlog = 16384
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.ipv4.tcp_slow_start_after_idle = 0
EOF

sudo sysctl --system
# → Applying /etc/sysctl.d/99-jaeger-otlp.conf ...
# → net.core.somaxconn = 32768
# → net.ipv4.tcp_max_syn_backlog = 16384
# → net.core.rmem_max = 16777216
# → net.core.wmem_max = 16777216

# Создание системного пользователя и рабочих каталогов
sudo useradd --system --no-create-home --shell /usr/sbin/nologin jaeger
sudo mkdir -p /etc/jaeger /var/log/jaeger
sudo chown -R jaeger:jaeger /etc/jaeger /var/log/jaeger
```

#### 2. Создание конфигурационного файла Jaeger v2

```yaml
# /etc/jaeger/config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
        max_recv_msg_size_mib: 16
        max_concurrent_streams: 2048
        read_buffer_size: 1048576
        write_buffer_size: 1048576
        keepalive:
          server_parameters:
            max_connection_idle: 15m
            max_connection_age: 1h
            max_connection_age_grace: 30s
            time: 2h
            timeout: 20s
          enforcement_policy:
            min_time: 5s
            permit_without_stream: true

processors:
  # Защита от OOM: ограничение 80% от лимита памяти, 20% запас на пики
  memory_limiter:
    check_interval: 500ms
    limit_percentage: 80
    spike_limit_percentage: 20

  # Оптимизация записи пачками
  batch:
    send_batch_size: 2048
    timeout: 2s
    send_batch_max_size: 4096

extensions:
  healthcheckv2:
    endpoint: 0.0.0.0:13133
  jaeger_storage:
    backends:
      clickhouse_prod:
        clickhouse:
          endpoint: "tcp://127.0.0.1:9000"
          database: "jaeger_v2"
          username: "jaeger"
          password: "SecretClickHousePassword"
  jaeger_query:
    storage:
      traces: clickhouse_prod
    http:
      endpoint: 0.0.0.0:16686

exporters:
  jaeger_storage_exporter:
    trace_storage: clickhouse_prod
    queue:
      enabled: true
      num_consumers: 16
      queue_size: 5000
    retry_on_failure:
      enabled: true
      initial_interval: 1s
      max_interval: 10s
      max_elapsed_time: 30s

service:
  extensions: [healthcheckv2, jaeger_storage, jaeger_query]
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
```

#### 3. Настройка сервиса systemd

```ini
# /etc/systemd/system/jaeger.service
[Unit]
Description=Jaeger v2 Unified Binary Collector
Documentation=https://www.jaegertracing.io/docs/latest/
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=jaeger
Group=jaeger
LimitNOFILE=65536
LimitNPROC=32768
# Жесткое ограничение кучи Go для предсказуемой работы memory_limiter
Environment=GOMEMLIMIT=3400MiB
Environment=GOCACHE=off
ExecStart=/usr/local/bin/jaeger --config=/etc/jaeger/config.yaml
Restart=always
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Запуск и включение сервиса:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now jaeger.service

# Проверка статуса сервиса
sudo systemctl status jaeger.service
# → ● jaeger.service - Jaeger v2 Unified Binary Collector
# →      Loaded: loaded (/etc/systemd/system/jaeger.service; enabled)
# →      Active: active (running) since Mon 2026-10-12 14:00:00 UTC; 10s ago
# →    Main PID: 45120 (jaeger)
```

#### 4. Настройка клиентского приложения (OpenTelemetry SDK)

Пример конфигурации клиента через системные переменные окружения:

```bash
# Переменные среды для микросервиса (OTel SDK)
export OTEL_SERVICE_NAME="payment-gateway"
export OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:4317"
export OTEL_EXPORTER_OTLP_PROTOCOL="grpc"
export OTEL_EXPORTER_OTLP_COMPRESSION="zstd"
export OTEL_EXPORTER_OTLP_TIMEOUT="10000"
export OTEL_BSP_SCHEDULE_DELAY="2000"
export OTEL_BSP_MAX_QUEUE_SIZE="4096"
export OTEL_BSP_MAX_EXPORT_BATCH_SIZE="2048"
```

#### 5. Валидация и проверка функционирования

```bash
# 1. Проверка сетевого слушателя порта 4317
ss -tlpn | grep 4317
# → LISTEN 0 32768 0.0.0.0:4317 0.0.0.0:* users:(("jaeger",pid=45120,fd=8))

# 2. Проверка доступности Health Check эндпоинта
curl -s -i http://localhost:13133/
# → HTTP/1.1 200 OK
# → Content-Length: 0

# 3. Проверка доступности сервисов через grpcurl
grpcurl -plaintext localhost:4317 list
# → grpc.health.v1.Health
# → opentelemetry.proto.collector.trace.v1.TraceService

# 4. Проверка скрапинга Prometheus-метрик
curl -s http://localhost:8888/metrics | grep otelcol_receiver_accepted_spans
# → otelcol_receiver_accepted_spans_total{receiver="otlp",transport="grpc"} 0
```

---

### Сценарий 2: Настройка взаимной TLS-аутентификации (mTLS) для OTLP gRPC

**Контекст:** Требуется обеспечить криптографическую защиту канала передачи спанов и ограничить отправку данных коллектору только доверенными микросервисами, обладающими валидным клиентским сертификатом X.509.

#### 1. Генерация внутренней инфраструктуры открытых ключей (PKI)

```bash
mkdir -p /etc/jaeger/certs && cd /etc/jaeger/certs

# 1. Корневой удостоверяющий центр (CA)
openssl req -x509 -newkey rsa:4096 -sha256 -days 1095 -nodes \
  -keyout ca.key -out ca.crt \
  -subj "/C=RU/O=Company/OU=Infrastructure/CN=Observability Internal CA"

# 2. Серверный сертификат для Jaeger Collector с Subject Alternative Name (SAN)
openssl req -newkey rsa:2048 -nodes \
  -keyout server.key -out server.csr \
  -subj "/C=RU/O=Company/CN=jaeger-collector.internal"

cat << 'EOF' > server.ext
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = jaeger-collector.internal
DNS.2 = localhost
IP.1 = 127.0.0.1
EOF

openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 365 -sha256 -extfile server.ext

# 3. Клиентский сертификат для приложения (OTel Client)
openssl req -newkey rsa:2048 -nodes \
  -keyout client.key -out client.csr \
  -subj "/C=RU/O=Company/CN=otel-client-service"

cat << 'EOF' > client.ext
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = clientAuth
EOF

openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out client.crt -days 365 -sha256 -extfile client.ext

# Выставление корректных прав доступа
chmod 600 ca.key server.key client.key
chmod 644 ca.crt server.crt client.crt
chown -R jaeger:jaeger /etc/jaeger/certs
```

#### 2. Конфигурация приемника в Jaeger v2

Вносим изменения в `/etc/jaeger/config.yaml`:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
        tls:
          cert_file: /etc/jaeger/certs/server.crt
          key_file: /etc/jaeger/certs/server.key
          client_ca_file: /etc/jaeger/certs/ca.crt
          min_version: "1.3"
          reload_interval: 10m
```

Перезапуск сервиса:

```bash
sudo systemctl restart jaeger.service
```

#### 3. Настройка клиентского окружения

```bash
export OTEL_SERVICE_NAME="billing-engine"
export OTEL_EXPORTER_OTLP_ENDPOINT="https://jaeger-collector.internal:4317"
export OTEL_EXPORTER_OTLP_PROTOCOL="grpc"
export OTEL_EXPORTER_OTLP_CERTIFICATE="/etc/jaeger/certs/client.crt"
export OTEL_EXPORTER_OTLP_CLIENT_KEY="/etc/jaeger/certs/client.key"
export OTEL_EXPORTER_OTLP_CLIENT_CA="/etc/jaeger/certs/ca.crt"
```

#### 4. Валидация mTLS-соединения

```bash
# Тест 1: Попытка подключения БЕЗ клиентского сертификата (Отказ)
openssl s_client -connect localhost:4317 -CAfile /etc/jaeger/certs/ca.crt </dev/null
# → Verification: OK
# → ...
# → TLS error: ssl/tls alert bad certificate (или handshake failure)

# Тест 2: Успешный handshake с предоставлением клиентского сертификата
openssl s_client -connect localhost:4317 \
  -cert /etc/jaeger/certs/client.crt \
  -key /etc/jaeger/certs/client.key \
  -CAfile /etc/jaeger/certs/ca.crt </dev/null
# → verify return:1
# → Master-Key: ...
# → TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384
# → DONE

# Тест 3: Проверка gRPC вызова через grpcurl с mTLS
grpcurl -cacert /etc/jaeger/certs/ca.crt \
  -cert /etc/jaeger/certs/client.crt \
  -key /etc/jaeger/certs/client.key \
  localhost:4317 list
# → grpc.health.v1.Health
# → opentelemetry.proto.collector.trace.v1.TraceService
```

---

### Сценарий 3: Аутентификация по токену (`bearertokenauth`) и балансировка HTTP/2 через HAProxy

**Контекст:** В корпоративной сети развернут пул из трех инстансов Jaeger Collector. Перед ними установлен отказоустойчивый балансировщик HAProxy. Требуется настроить балансировку HTTP/2 потоков на порту 4317 и валидацию токена приложения расширением `bearertokenauth`.

#### 1. Конфигурация Jaeger v2 с расширением `bearertokenauth`

```yaml
# /etc/jaeger/config.yaml
extensions:
  healthcheckv2:
    endpoint: 0.0.0.0:13133
  jaeger_storage:
    backends:
      clickhouse_prod:
        clickhouse:
          endpoint: "tcp://127.0.0.1:9000"
          database: "jaeger_v2"
  jaeger_query:
    storage:
      traces: clickhouse_prod
    http:
      endpoint: 0.0.0.0:16686

  # Расширение проверки подлинности токена
  bearertokenauth:
    token: "SuperSecretProductionAuthToken2026"

receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
        auth:
          authenticator: bearertokenauth
      http:
        endpoint: 0.0.0.0:4318
        auth:
          authenticator: bearertokenauth

processors:
  memory_limiter:
    check_interval: 500ms
    limit_percentage: 80
    spike_limit_percentage: 20
  batch:
    send_batch_size: 2048
    timeout: 2s

exporters:
  jaeger_storage_exporter:
    trace_storage: clickhouse_prod

service:
  # Обязательно регистрируем bearertokenauth в списке расширений процесса
  extensions: [healthcheckv2, jaeger_storage, jaeger_query, bearertokenauth]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [jaeger_storage_exporter]
```

#### 2. Конфигурация балансировщика HAProxy (`/etc/haproxy/haproxy.cfg`)

HAProxy балансирует gRPC-трафик по модели `mode tcp` с анализом HTTP/2 заголовков, распределяя сессии методом `leastconn`:

```haproxy
global
    log /dev/log local0
    maxconn 50000

defaults
    log     global
    mode    tcp
    option  tcplog
    timeout connect 5000ms
    timeout client  3600000ms
    timeout server  3600000ms

# Фронтенд для OTLP gRPC (порт 4317)
frontend otlp_grpc_front
    bind 0.0.0.0:4317 proto h2
    mode tcp
    default_backend otlp_grpc_back

backend otlp_grpc_back
    mode tcp
    balance leastconn
    # Проверка состояния через Health Check v2 эндпоинт
    option httpchk GET /
    http-check connect port 13133
    http-check expect status 200
    server jaeger-01 192.168.10.11:4317 check port 13133 inter 3s rise 2 fall 3 proto h2
    server jaeger-02 192.168.10.12:4317 check port 13133 inter 3s rise 2 fall 3 proto h2
    server jaeger-03 192.168.10.13:4317 check port 13133 inter 3s rise 2 fall 3 proto h2

# Фронтенд для OTLP HTTP (порт 4318)
frontend otlp_http_front
    bind 0.0.0.0:4318
    mode http
    default_backend otlp_http_back

backend otlp_http_back
    mode http
    balance roundrobin
    option httpchk GET /
    http-check connect port 13133
    http-check expect status 200
    server jaeger-01 192.168.10.11:4318 check port 13133
    server jaeger-02 192.168.10.12:4318 check port 13133
    server jaeger-03 192.168.10.13:4318 check port 13133
```

#### 3. Настройка клиентского приложения

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="http://haproxy.company.lan:4317"
export OTEL_EXPORTER_OTLP_PROTOCOL="grpc"
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer SuperSecretProductionAuthToken2026"
```

#### 4. Валидация авторизации

```bash
# 1. Попытка запроса без токена через OTLP HTTP (Ожидается 401 Unauthorized)
curl -s -i -X POST http://localhost:4318/v1/traces \
  -H "Content-Type: application/json" \
  -d '{"resourceSpans":[]}'
# → HTTP/1.1 401 Unauthorized
# → Content-Length: 0

# 2. Запрос с корректным Bearer Token (Ожидается 200 OK)
curl -s -i -X POST http://localhost:4318/v1/traces \
  -H "Authorization: Bearer SuperSecretProductionAuthToken2026" \
  -H "Content-Type: application/json" \
  -d '{"resourceSpans":[]}'
# → HTTP/1.1 200 OK
# → Content-Type: application/json
# → {"partialSuccess":{}}
```

---

### Сценарий 4: Настройка Backpressure и проверка поведения при перегрузке

**Контекст:** Тестирование устойчивости OTLP-ресивера при имитации недоступности базы данных ClickHouse. Коллектор должен защитить память процесса через `memory_limiter`, буферизировать данные в `queue` и возвращать сигнал обратного давления клиентам без падения по OOM.

#### 1. Конфигурация очередей экспортера и лимитов

```yaml
processors:
  memory_limiter:
    check_interval: 200ms
    limit_percentage: 75
    spike_limit_percentage: 15
  batch:
    send_batch_size: 1024
    timeout: 1s

exporters:
  jaeger_storage_exporter:
    trace_storage: clickhouse_prod
    queue:
      enabled: true
      num_consumers: 8
      queue_size: 1000
    retry_on_failure:
      enabled: true
      initial_interval: 500ms
      max_interval: 5s
      max_elapsed_time: 15s
```

#### 2. Пошаговая проверка механизма защиты

```bash
# 1. Имитация сбоя хранилища: остановка ClickHouse
sudo systemctl stop clickhouse-server

# 2. Отправка тестового потока спанов от нагрузочного генератора или приложения
# Наблюдение за метриками накопления очереди в Jaeger Collector:
curl -s http://localhost:8888/metrics | grep otelcol_exporter_queue_capacity
# → otelcol_exporter_queue_capacity{exporter="jaeger_storage_exporter"} 1000

curl -s http://localhost:8888/metrics | grep otelcol_exporter_enqueue_failed_spans
# При переполнении очереди спаны начинают отклоняться:
# → otelcol_exporter_enqueue_failed_spans_total{exporter="jaeger_storage_exporter"} 4521

# 3. При приближении к порогу RAM процессор memory_limiter активирует сброс трафика:
curl -s http://localhost:8888/metrics | grep otelcol_processor_memory_limiter_refused
# → otelcol_processor_memory_limiter_refused_spans_total 12850

# 4. Восстановление хранилища ClickHouse
sudo systemctl start clickhouse-server

# 5. Проверка восстановления нормальной отправки
sleep 5
curl -s http://localhost:8888/metrics | grep otelcol_exporter_sent_spans
# → otelcol_exporter_sent_spans_total{exporter="jaeger_storage_exporter"} 89450
```

---

## Операции и диагностика

### Команды проверки и тестирования сетевых портов

| Действие | Команда CLI | Ожидаемый результат / Пояснение |
| :--- | :--- | :--- |
| **Проверка сетевых сокетов** | `ss -tulpn \| grep -E '4317\|4318\|13133\|8888'` | Процесс `jaeger` слушает все сконфигурированные порты |
| **Детальная статистика TCP-сокета** | `ss -it 'sport = :4317'` | Отображение размеров буферов `rcv_space`, `snd_wnd`, параметров RTT |
| **Проверка gRPC рефлексии** | `grpcurl -plaintext localhost:4317 list` | Список доступных сервисов (`TraceService`, `Health`) |
| **Проверка gRPC Health Check** | `grpcurl -plaintext localhost:4317 grpc.health.v1.Health/Check` | `{"status": "SERVING"}` |
| **Отправка пустого HTTP JSON трейса** | `curl -s -X POST http://localhost:4318/v1/traces -H "Content-Type: application/json" -d '{"resourceSpans":[]}'` | `{"partialSuccess":{}}` со статусом HTTP `200 OK` |
| **Проверка Healthcheck v2** | `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:13133/` | `# → 200` |
| **Скрапинг метрик приемника OTLP** | `curl -s http://localhost:8888/metrics \| grep -E '^otelcol_receiver_'` | Текущие счетчики принятых и отклоненных спанов |

### Мониторинг ключевых метрик OTLP в Prometheus

| Метрика | Тип | Пороговое значение (SRE Alert) | Описание и диагностика |
| :--- | :--- | :--- | :--- |
| `otelcol_receiver_accepted_spans_total` | Counter | `rate(...) > 0` | Общее количество успешно принятых спанов приемником `otlp` |
| `otelcol_receiver_refused_spans_total` | Counter | `rate(...) > 0` (Alert) | Спаны, отклоненные на входе (ошибка сериализации, переполнение буфера) |
| `otelcol_processor_memory_limiter_refused_spans_total` | Counter | `rate(...) > 0` (Warning/Critical) | Количество спанов, сброшенных процессором `memory_limiter` из-за нехватки RAM |
| `otelcol_exporter_enqueue_failed_spans_total` | Counter | `rate(...) > 0` (Alert) | Спаны, не поместившиеся во внутреннюю очередь `queue` экспортера |
| `otelcol_exporter_send_failed_spans_total` | Counter | `rate(...) > 0` (Alert) | Ошибки физической записи спанов в бэкенд ClickHouse/Elasticsearch |
| `grpc_server_handled_total` | Counter | Рост статусов `ResourceExhausted` | Статистика gRPC-кодов ответов сервера |

---

## Типичные проблемы и устранение неполадок

| Проблема | Вероятная причина | Метод диагностики | Пошаговое решение |
| :--- | :--- | :--- | :--- |
| **Connection refused на порту 4317 или 4318** | Процесс Jaeger не запущен, конфликт портов или неверный IP-адрес интерфейса в `endpoint` | 1. `systemctl status jaeger`<br>2. `ss -tlpn \| grep 4317`<br>3. `journalctl -u jaeger -n 50 --no-pager` | 1. Убедиться, что `endpoint: 0.0.0.0:4317` (не `127.0.0.1`, если трафик идет извне).<br>2. Проверить, не занят ли порт другим сервисом (`lsof -i :4317`).<br>3. Открыть входящие порты в сетевом фильтре: `sudo ufw allow 4317/tcp`. |
| **gRPC `ResourceExhausted` (код ошибки 8)** | 1. Спаны превышают `max_recv_msg_size_mib`.<br>2. Сработал `memory_limiter` из-за исчерпания RAM. | В логах Jaeger:<br>`rpc error: code = ResourceExhausted desc = grpc: received message larger than max (X vs Y)`<br>Или метрика: `otelcol_processor_memory_limiter_refused_spans_total > 0` | 1. Если сообщение превысило лимит: увеличить `max_recv_msg_size_mib: 32` в секции `grpc:`.<br>2. Если сработал memory_limiter: увеличить физическую RAM сервера, скорректировать `GOMEMLIMIT` и `limit_percentage`, либо снизить batch size на клиентах. |
| **Сброс соединений `GOAWAY` (`too_many_pings` / `ENHANCE_YOUR_CALM`)** | Клиентский SDK отправляет keepalive PING чаще, чем разрешает `enforcement_policy.min_time` | В логах Jaeger:<br>`transport: Got too many pings from the client, closing the connection` | В конфигурации приемника выставить мягкие ограничения keepalive:<br>`enforcement_policy:`<br>&nbsp;&nbsp;`min_time: 5s`<br>&nbsp;&nbsp;`permit_without_stream: true`. |
| **TLS Handshake failure: `bad certificate` или `unknown authority`** | Серверный или клиентский сертификат подписан недоверенным CA, истек срок действия или не совпадает SAN | Проверка сертификата через openssl:<br>`openssl s_client -connect localhost:4317 -CAfile /etc/jaeger/certs/ca.crt`<br>`# → verify error:num=10:certificate has expired` | 1. Проверить сроки действия: `openssl x509 -in /etc/jaeger/certs/server.crt -noout -dates`.<br>2. Проверить наличие SAN: `openssl x509 -in /etc/jaeger/certs/server.crt -noout -text \| grep -A 2 "Subject Alternative Name"`.<br>3. Перевыпустить сертификаты и обновить пути в YAML. |
| **HTTP `415 Unsupported Media Type` на порту 4318** | Клиент отправляет POST-запрос без указания корректного HTTP-заголовка `Content-Type` | Анализ заголовков клиентского запроса:<br>`curl -v -X POST http://localhost:4318/v1/traces -d "..."` | В клиентском приложении или curl явно передавать заголовок `Content-Type: application/x-protobuf` (для двоичных данных) или `Content-Type: application/json` (для JSON). |
| **HTTP `429 Too Many Requests` на порту 4318** | Срабатывание защиты памяти `memory_limiter` коллектора при пике нагрузки | В логах коллектора сообщение от memory_limiter processor о достижении лимита памяти | 1. Проверить потребление RAM процессом: `ps aux \| grep jaeger`.<br>2. Увеличить `queue_size` и количество консьюмеров ClickHouse экспортера.<br>3. Настроить в клиентском SDK экспоненциальный retry backoff. |
| **Деградация CPU из-за компрессии zstd при сверхвысоком FPS** | Огромное количество мелких батчей со сжатием перегружает декомпрессор CPU коллектора | Мониторинг CPU: `top -p $(pgrep jaeger)` показывает утилизацию 100% нескольких ядер при высоком FPS спанов | 1. На стороне клиентов увеличить `OTEL_BSP_SCHEDULE_DELAY` до 2–5 секунд и `OTEL_BSP_MAX_EXPORT_BATCH_SIZE` до 2048–4096 (сократит количество сетевых транзакций и накладные расходы).<br>2. Добавить CPU-ресурсы инстансу коллектора или запустить дополнительные инстансы за балансировщиком. |
| **`failed to get trace storage: backend not found` при старте** | Имя бэкенда в `exporters.jaeger_storage_exporter.trace_storage` не совпадает с ключом в `extensions.jaeger_storage.backends` | В логах запуска процесса:<br>`journalctl -u jaeger -n 50 \| grep "trace storage"` | Синхронизировать строковые идентификаторы бэкенда между секциями `extensions.jaeger_storage.backends` и `exporters.jaeger_storage_exporter.trace_storage`. |

---

## Лучшие практики

1. **Используйте gRPC + zstd как основной стандарт:** В high-load инфраструктуре связка gRPC (HTTP/2) и алгоритма сжатия `zstd` обеспечивает минимальное потребление сетевой полосы и процессора по сравнению с HTTP/JSON и gzip.
2. **Всегда помещайте `memory_limiter` первым процессором:** В конвейере обработки `memory_limiter` обязан стоять перед `batch` и любыми другими процессорами (`processors: [memory_limiter, batch]`). Это гарантирует, что избыточный трафик будет отсечен до выделения оперативной памяти на обработку и буферизацию.
3. **Фиксируйте `GOMEMLIMIT` для процесса:** В systemd-юните или контейнере выставляйте переменную окружения `GOMEMLIMIT` на уровне 80–85% от доступного физического лимита RAM. Это устраняет запаздывание сборщика мусора Go (GC) и стабилизирует работу `memory_limiter`.
4. **Настраивайте ротацию соединений `max_connection_age`:** Установка `max_connection_age: 1h` и `max_connection_age_grace: 30s` предотвращает постоянную привязку клиентов к одному инстансу коллектора при работе за L4-балансировщиком (IPVS/Keepalived).
5. **Включайте mTLS в межсегментных сетях:** Если трафик телеметрии пересекает границы сегментов сети или передается между ЦОД, использование взаимной аутентификации X.509 исключает перехват и инъекцию недостоверных спанов.
6. **Ограничивайте `max_recv_msg_size_mib`:** Установка фиксированного лимита (16–32 МБ) защищает коллектор от аномально крупных спанов с тяжелыми текстовыми атрибутами или дампами стека вызовов.
7. **Контролируйте метрики backpressure в Alertmanager:** Алерты на ненулевые значения `otelcol_processor_memory_limiter_refused_spans_total` и `otelcol_exporter_enqueue_failed_spans_total` позволяют выявить дефицит ресурсов задолго до аварии хранилища.

---

## Очистка окружения

Команды для удаления тестовых конфигураций, сертификатов и остановки сервиса:

```bash
# 1. Остановка и отключение системного сервиса Jaeger
sudo systemctl stop jaeger.service
sudo systemctl disable jaeger.service
sudo rm -f /etc/systemd/system/jaeger.service
sudo systemctl daemon-reload
# → Removed /etc/systemd/system/jaeger.service.

# 2. Удаление сгенерированных сертификатов и конфигурационных файлов
sudo rm -rf /etc/jaeger/certs /etc/jaeger/config.yaml

# 3. Удаление настроек сетевого стека ядра
sudo rm -f /etc/sysctl.d/99-jaeger-otlp.conf
sudo sysctl --system
# → Configuration reloaded without 99-jaeger-otlp.conf

# 4. Удаление системного пользователя и логов
sudo userdel jaeger
sudo rm -rf /var/log/jaeger
```

---

## Дополнительная информация

**Смежные материалы по теме:**

* Протокол OTLP и спецификация данных: **[Протокол OTLP](../OpenTelemetry/otlp_protocol.md)**
* Внутреннее устройство конвейера Jaeger v2: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Развертывание All-in-one и распределенного коллектора: **[Варианты развертывания Jaeger](./jaeger_deployment_options.md)**
* Безопасность, шифрование и харденинг: **[Безопасность и харденинг Jaeger](./jaeger_security_hardening.md)**
* Анализ производительности и тюнинг буферов: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**
* Моделирование пропускной способности и расчет памяти: **[Планирование емкости Jaeger](./jaeger_capacity_planning.md)**
* Отказоустойчивость, HAProxy и балансировка: **[Отказоустойчивость Jaeger](./jaeger_high_availability.md)**
* Интеграция с ClickHouse и схемы таблиц: **[Storage Deep Dive для Jaeger](./jaeger_storage_deep_dive.md)**

### См. также

* [OpenTelemetry Collector OTLP Receiver Specification](https://github.com/open-telemetry/opentelemetry-collector/tree/main/receiver/otlpreceiver)
* [Jaeger Documentation — Architecture and Configuration v2](https://www.jaegertracing.io/docs/latest/)
* [gRPC Keepalive Configuration Guide](https://github.com/grpc/grpc/blob/master/doc/keepalive.md)
