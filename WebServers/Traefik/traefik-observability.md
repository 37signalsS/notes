# Наблюдаемость Traefik: метрики, трейсинг, логи

**Актуально для:** Traefik v3.x / v2.11+ (с фокусом на архитектуру v3 и стандарт OTLP)

## Определения

**Observability (Наблюдаемость)** — способность оценивать внутреннее состояние proxy-сервера и маршрутизируемого трафика на основе генерируемых телеметрических данных: метрик, журналов событий (логов) и распределенных трассировок (трейсов).

**EntryPoints Metrics** — метрики сетевого периметра Traefik, фиксирующие входящий трафик на слушающих портах (L4/L7) до применения правил маршрутизации.

**Prometheus Metrics** — экспорт агрегированных счетчиков (Counters), калибровочных шкал (Gauges) и гистограмм (Histograms) в стандартном текстовом формате OpenMetrics/Prometheus через выделенный HTTP-эндпоинт.

**AccessLog** — журнал обработанных HTTP/HTTPS/TCP-сессий в форматах `common` (CLF) или `json`, содержащий гранулярные данные о времени обработки, статусах upstream, размерах полезной нагрузки и заголовках.

**Process Log (Traefik Daemon Log)** — системный журнал событий самого процесса Traefik (старт, остановка, парсинг конфигурации, обновление провайдеров, генерация сертификатов ACME) с уровнями детализации от `DEBUG` до `PANIC`.

**OTLP (OpenTelemetry Protocol)** — открытый стандартизированный протокол передачи телеметрии (трассировок и метрик) поверх gRPC (порт по умолчанию 4317) или HTTP/Protobuf (порт по умолчанию 4318). Начиная с Traefik v3, OTLP является единственным встроенным механизмом экспорта трейсов (устаревшие коннекторы Jaeger и Zipkin удалены).

**Trace Context Propagation** — сквозная передача идентификаторов трассировки (`traceparent`, `tracestate` по стандарту W3C Trace Context либо B3) через HTTP-заголовки между клиентом, прокси-сервером и downstream-микросервисами.

**Span** — неделимый отрезок работы внутри распределенной трассировки, описывающий операцию маршрутизации в Traefik (на уровнях EntryPoint, Router, Service) с метками времени и метаданными.

**Cardinality (Кардинальность метрик)** — число уникальных комбинаций меток (labels) временного ряда Prometheus. Включение меток отдельных роутеров (`addRoutersLabels`) или клиентских заголовков (`headerLabels`) при динамическом трафике может привести к экспоненциальному росту потребления памяти базой Prometheus (кардинальный взрыв).

**Log Buffering** — механизм асинхронного накопления строк журнала в кольцевом буфере памяти (`bufferingSize`) перед пакетным сбросом на диск для снижения нагрузки на подсистему дискового ввода-вывода (I/O wait).

---

## Архитектура и базовые концепции

### Потоки данных телеметрии

Traefik разделяет обработку трафика data plane и генерацию телеметрии control/observability plane:

```text
[ Клиентский запрос ]
         │
         ▼
 ┌─────────────────────────────────────────────────────────────┐
 │                      TRAEFIK CORE                           │
 │                                                             │
 │  [ EntryPoint: 80/443 ] ──► traefik_entrypoint_* метрики    │
 │           │                                                 │
 │           ▼                                                 │
 │      [ Routers ]        ──► traefik_router_* метрики        │
 │           │                                                 │
 │           ▼                                                 │
 │     [ Middlewares ]     ──► Извлечение / Инъекция Tracing   │
 │           │                                                 │
 │           ▼                                                 │
 │      [ Services ]       ──► traefik_service_* метрики       │
 │           │                                                 │
 └───────────┼─────────────────────────────────────────────────┘
             │
             ├──► [ AccessLog Engine ] ──► /var/log/traefik/access.log (JSON/CLF)
             ├──► [ Daemon Logger ]   ──► /var/log/traefik/traefik.log (или stdout)
             ├──► [ Prometheus Engine] ──► http://127.0.0.1:8082/metrics
             ├──► [ OTLP Exporter ]   ──► gRPC/HTTP ──► OpenTelemetry Collector
             │
             ▼
   [ Upstream Services ]
```

### Модель метрик Prometheus

Traefik предоставляет встроенный сервер метрик, не требующий внешних сайдкаров. Метрики группируются по уровням абстракции:

1. **Глобальные метрики (Global):**
   - `traefik_open_connections` — общее число активных L4-соединений в разрезе `entrypoint` и `protocol` (введено в v3 взамен раздельных метрик v2).
   - `traefik_config_reloads_total` — счетчик попыток перезагрузки конфигурации провайдеров.
   - `traefik_config_last_reload_success` — Unix-таймштамп (в секундах) последней успешной синхронизации конфигурации (gauge).
   - `traefik_tls_certs_not_after` — таймштамп окончания срока действия управляемых TLS-сертификатов.

2. **Метрики точек входа (EntryPoints):**
   - `traefik_entrypoint_requests_total` — счетчик входящих запросов с метками `code`, `method`, `protocol` (`http`/`https`), `entrypoint`.
   - `traefik_entrypoint_request_duration_seconds` — гистограмма времени от получения первого байта запроса до отправки последнего байта ответа клиенту.

3. **Метрики сервисов (Services):**
   - `traefik_service_requests_total` — количество запросов, переданных на бэкенды сервиса.
   - `traefik_service_request_duration_seconds` — гистограмма времени ответа конкретных upstream-бэкендов.
   - `traefik_service_server_up` — бинарный статус доступности бэкенда по результатам встроенного health check (`1` — доступен, `0` — исключен из пула).

4. **Метрики маршрутизаторов (Routers):**
   - `traefik_router_requests_total` — детализация трафика по именам роутеров (выключено по умолчанию для предотвращения взрыва кардинальности).
   - `traefik_router_request_duration_seconds` — гистограмма задержек в разрезе роутеров.

### Подсистема логирования (Process Log vs Access Log)

Traefik четко разделяет два типа журналов:

| Характеристика | Process Log (`log`) | Access Log (`accessLog`) |
| :--- | :--- | :--- |
| **Назначение** | Жизненный цикл демона, ошибки конфигурации, ACME, TLS | Детализация каждого прошедшего HTTP/TCP запроса |
| **Уровень детализации**| `PANIC`, `FATAL`, `ERROR`, `WARN`, `INFO`, `DEBUG`, `TRACE` | Фиксация по факту завершения сессии |
| **Форматы** | `common` (текст с цветами или без), `json` | `common` (CLF), `json` |
| **Буферизация** | Отсутствует (синхронная запись сообщений) | Настраиваемый буфер строк в памяти (`bufferingSize`) |
| **Фильтрация** | По уровню важности (`level`) | По статус-кодам, времени выполнения (`minDuration`), повторам (`retryAttempts`) |
| **Безопасность** | Трассировка ошибок провайдеров | Маскирование чувствительных заголовков (`redact`/`drop`) |

#### Сигнал USR1 и ротация без перезапуска

При получении POSIX-сигнала `SIGUSR1` Traefik атомарно закрывает текущие файловые дескрипторы для `log.filePath` и `accessLog.filePath` и переоткрывает их по тем же путям. Это позволяет использовать стандартную утилиту `logrotate` без обрыва клиентских соединений и перезапуска процесса.

### Распределенная трассировка (OpenTelemetry OTLP)

В архитектуре Traefik v3 подсистема трассировки полностью переведена на спецификацию OpenTelemetry Semantic Conventions v1.26+:

- **Протокол:** Экспорт выполняется исключительно через OTLP. Старые драйверы прямого подключения к Jaeger, Zipkin и Datadog удалены из ядра. Вся телеметрия отправляется в локальный или сетевой OpenTelemetry Collector, который выполняет дальнейшую маршрутизацию и сохранение (Jaeger, Tempo, ClickHouse).
- **Транспорт:** Поддерживаются `grpc` (порт 4317) и `http` (эндпоинт `/v1/traces`, порт 4318).
- **Сэмплирование:** Директива `tracing.sampleRate` определяет долю трассируемых сессий (от `0.0` до `1.0`). Для высоконагруженных инсталляций критично устанавливать значение `0.05`–`0.2` либо настраивать хвостовое сэмплирование (tail-based sampling) на уровне OTel Collector.
- **Пропагаторы контекста:** По умолчанию используется связка W3C `tracecontext` и `baggage`. Переопределение выполняется через системную переменную окружения `OTEL_PROPAGATORS` (например, `tracecontext,b3`).

### Проверка работоспособности (Healthcheck / Ping)

Встроенный сервис `ping` (`ping@internal`) предоставляет легковесный эндпоинт для внешних балансировщиков (Keepalived, HAProxy, AWS NLB) и системных супервизоров (systemd, Docker):
- Отвечает кодом `200 OK` и телом `OK` при нормальной работе runtime-движка.
- Может быть изолирован на отдельном порту или точке входа без публикации во внешнюю сеть.

---

## Практические сценарии и конфигурация

### Сценарий 1: Производственная конфигурация метрик с изоляцией сетевого периметра

Для исключения несанкционированного доступа к метрикам и API создается отдельный локальный слушатель `metrics`, привязанный к loopback-интерфейсу или служебной подсети управления.

```yaml
# /etc/traefik/traefik.yml
global:
  checkNewVersion: false
  sendAnonymousUsage: false

# 1. Определение сетевых слушателей
entryPoints:
  web:
    address: ":80"
  websecure:
    address: ":443"
  # Изолированный порт для мониторинга и служебных проверок
  metrics:
    address: "127.0.0.1:8082"

# 2. Включение метрик Prometheus
metrics:
  prometheus:
    entryPoint: metrics           # Привязка к изолированному порту
    addEntryPointsLabels: true    # Метрики по входящим портам
    addServicesLabels: true       # Метрики по целевым сервисам
    addRoutersLabels: false       # Защита от высокой кардинальности
    manualRouting: false          # Автоматическая публикация на /metrics
    # Настройка гистограмм задержек (секунды) под строгие SLA
    buckets:
      - 0.005
      - 0.01
      - 0.025
      - 0.05
      - 0.1
      - 0.25
      - 0.5
      - 1.0
      - 2.5
      - 5.0

# 3. Служебный эндпоинт проверки жизнеспособности процесса
ping:
  entryPoint: metrics
  manualRouting: false

# 4. Процессный лог демона
log:
  level: INFO
  filePath: "/var/log/traefik/traefik.log"
  format: json
```

### Сценарий 2: Высокопроизводительный Access Log в формате JSON с маскированием данных

Конфигурация оптимизирована для систем агрегации логов (Loki, Elasticsearch, Vector). Включает буферизацию строк, фильтрацию рутинных запросов и удаление конфиденциальных заголовков (PII, авторизационные токены).

```yaml
# /etc/traefik/traefik.yml (секция accessLog)
accessLog:
  filePath: "/var/log/traefik/access.log"
  format: json
  # Асинхронный сброс: накопление до 200 строк в памяти перед записью
  bufferingSize: 200

  # Фильтрация: логировать только медленные запросы, повторы или серверные ошибки
  filters:
    statusCodes:
      - "400-599"        # Ошибки клиентов и серверов фиксируются всегда
    minDuration: "100ms" # Успешные (2xx/3xx) фиксируются только при деградации скорости
    retryAttempts: true  # Сессии, потребовавшие retry через middleware, логируются всегда

  fields:
    defaultMode: keep
    names:
      ClientUsername: drop     # Удаление логинов из URL
      ClientPort: drop         # Случайный порт клиента не имеет ценности для аналитики
    headers:
      defaultMode: drop        # По умолчанию заголовки не пишутся в лог
      names:
        User-Agent: keep       # Сохранить для анализа ботов и клиентов
        X-Forwarded-For: keep  # Реальный IP клиента за внешним прокси/L4
        Authorization: redact  # Замена значения на [REDACTED]
        Cookie: redact         # Маскирование сессионных кук
        Proxy-Authorization: redact
```

#### Настройка logrotate для ротации без простоя

Создайте конфигурационный файл для демона `logrotate`:

```bash
# /etc/logrotate.d/traefik
/var/log/traefik/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 traefik traefik
    sharedscripts
    postrotate
        # Отправка сигнала USR1 процессу Traefik для переоткрытия дескрипторов
        /bin/kill -USR1 $(pidof traefik) 2>/dev/null || true
    endscript
}
```

### Сценарий 3: Распределенная трассировка OpenTelemetry (OTLP gRPC)

Интеграция Traefik v3 с OpenTelemetry Collector через протокол gRPC с ограничением накладных расходов через сэмплирование.

```yaml
# /etc/traefik/traefik.yml (секция tracing)
tracing:
  serviceName: "traefik-edge"
  sampleRate: 0.1              # Трассировка 10% входящих сессий
  addInternals: false          # Исключить внутренние запросы /ping и /metrics

  otlp:
    grpc:
      endpoint: "127.0.0.1:4317"
      insecure: true           # Локальное межсерверное соединение без TLS
      # При необходимости передачи токенов авторизации в Collector:
      # headers:
      #   x-scope-orgid: "production"
```

Для использования экспорта по HTTP вместо gRPC применяется блок `tracing.otlp.http`:

```yaml
tracing:
  serviceName: "traefik-edge"
  sampleRate: 0.1
  otlp:
    http:
      endpoint: "http://127.0.0.1:4318/v1/traces"
      tls:
        insecureSkipVerify: false
```

### Сценарий 4: Конфигурация сбора метрик в Prometheus (On-Premises)

Конфигурационный блок для сервера Prometheus (`prometheus.yml`):

```yaml
# prometheus.yml
scrape_configs:
  - job_name: "traefik"
    scrape_interval: 15s
    scrape_timeout: 10s
    metrics_path: /metrics
    static_configs:
      - targets: ["127.0.0.1:8082"]
        labels:
          environment: "production"
          datacenter: "dc-01"
          role: "edge-router"
```

### Сценарий 5: Полнофункциональный локальный стек наблюдаемости в Docker Compose

Автономный стенд без внешних облачных зависимостей: Traefik v3 + OTel Collector + Prometheus + Jaeger (OTLP receiver) + Loki.

```yaml
# docker-compose.observability.yml
version: "3.8"

networks:
  monitoring:
    driver: bridge

services:
  traefik:
    image: traefik:v3.1
    container_name: traefik
    restart: unless-stopped
    command:
      - "--global.checknewversion=false"
      - "--global.sendanonymoususage=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.metrics.address=:8082"
      - "--metrics.prometheus=true"
      - "--metrics.prometheus.entrypoint=metrics"
      - "--metrics.prometheus.addserviceslabels=true"
      - "--metrics.prometheus.addentrypointslabels=true"
      - "--ping=true"
      - "--ping.entrypoint=metrics"
      - "--accesslog=true"
      - "--accesslog.format=json"
      - "--accesslog.bufferingsize=100"
      - "--tracing=true"
      - "--tracing.servicename=traefik-gateway"
      - "--tracing.samplerate=1.0"
      - "--tracing.otlp.grpc=true"
      - "--tracing.otlp.grpc.endpoint=otel-collector:4317"
      - "--tracing.otlp.grpc.insecure=true"
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
    ports:
      - "80:80"
      - "127.0.0.1:8082:8082"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
    networks:
      - monitoring

  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.104.0
    container_name: otel-collector
    restart: unless-stopped
    command: ["--config=/etc/otelcol-config.yaml"]
    volumes:
      - ./otelcol-config.yaml:/etc/otelcol-config.yaml:ro
    ports:
      - "127.0.0.1:4317:4317" # OTLP gRPC
      - "127.0.0.1:4318:4318" # OTLP HTTP
    networks:
      - monitoring

  jaeger:
    image: jaegertracing/all-in-one:1.58
    container_name: jaeger
    restart: unless-stopped
    environment:
      - COLLECTOR_OTLP_ENABLED=true
    ports:
      - "127.0.0.1:16686:16686" # Web UI
    networks:
      - monitoring

  prometheus:
    image: prom/prometheus:v2.53.0
    container_name: prometheus
    restart: unless-stopped
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports:
      - "127.0.0.1:9090:9090"
    networks:
      - monitoring
```

Конфигурация агента `otelcol-config.yaml`:

```yaml
# otelcol-config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 1s
    send_batch_size: 256

exporters:
  otlp/jaeger:
    endpoint: jaeger:4317
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/jaeger]
```

---

## Операции и команды

### 1. Проверка доступности метрик и парсинг значений

```bash
# Проверка кода ответа эндпоинта метрик
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8082/metrics
# → 200

# Получение метрик открытых соединений в Traefik v3
curl -s http://127.0.0.1:8082/metrics | grep '^traefik_open_connections'
# → traefik_open_connections{entrypoint="web",protocol="http"} 4
# → traefik_open_connections{entrypoint="websecure",protocol="https"} 18

# Проверка счетчика запросов по целевым сервисам
curl -s http://127.0.0.1:8082/metrics | grep 'traefik_service_requests_total' | head -n 5
# → traefik_service_requests_total{code="200",method="GET",protocol="http",service="api-service@file"} 14205
# → traefik_service_requests_total{code="502",method="POST",protocol="http",service="auth-service@file"} 3

# Контроль статуса бэкендов в пуле
curl -s http://127.0.0.1:8082/metrics | grep 'traefik_service_server_up'
# → traefik_service_server_up{server="http://10.0.1.10:8080",service="api-service@file"} 1
# → traefik_service_server_up{server="http://10.0.1.11:8080",service="api-service@file"} 1

# Проверка времени последней успешной перезагрузки конфигурации
curl -s http://127.0.0.1:8082/metrics | grep 'traefik_config_last_reload_success'
# → traefik_config_last_reload_success 1.7291736e+09
```

### 2. Проверка работоспособности через ping

```bash
# Диагностика доступности Traefik
curl -i -s http://127.0.0.1:8082/ping
# → HTTP/1.1 200 OK
# → Content-Type: text/plain; charset=utf-8
# → Content-Length: 2
# → Date: Sat, 17 Oct 2026 13:35:00 GMT
# → 
# → OK
```

### 3. Анализ JSON Access Log в командной строке

```bash
# Просмотр последних 5 запросов с ошибками 5xx через jq
tail -n 1000 /var/log/traefik/access.log | jq -c 'select(.DownstreamStatus >= 500) | {time: .StartLocal, client: .ClientHost, status: .DownstreamStatus, service: .ServiceName, duration_ms: (.Duration / 1000000)}' | head -n 5
# → {"time":"2026-10-17T16:30:12+03:00","client":"192.168.1.55","status":502,"service":"billing-service@docker","duration_ms":12.4}

# Подсчет топ-10 самых медленных запросов
tail -n 5000 /var/log/traefik/access.log | jq -r '[.Duration/1000000, .RequestMethod, .RequestPath, .ServiceName] | @tsv' | sort -rn | head -n 10
```

### 4. Выполнение ротации логов без даунтайма

```bash
# 1. Проверка текущего дескриптора открытого файла лога
lsof -p $(pidof traefik) | grep access.log
# → traefik  14205 traefik    3w   REG  253,1 104857600 /var/log/traefik/access.log

# 2. Ротация файла утилитой перемещения
mv /var/log/traefik/access.log /var/log/traefik/access.log.1

# 3. Отправка сигнала USR1 процессу Traefik
kill -s USR1 $(pidof traefik)

# 4. Проверка появления нового файла и переключения дескриптора
sleep 1
ls -la /var/log/traefik/access.log
# → -rw-r----- 1 traefik traefik 245 Oct 17 16:32 /var/log/traefik/access.log
```

### 5. Диагностика подключения к OpenTelemetry Collector

```bash
# Проверка сетевой доступности порта gRPC OTel Collector
nc -z -v -w 3 127.0.0.1 4317
# → Connection to 127.0.0.1 4317 port [tcp/*] succeeded!

# Фильтрация логов демона на предмет сбоев экспорта спанов
journalctl -u traefik --no-pager -n 50 | grep -i "tracing"
```

---

## Устранение неисправностей

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **HTTP 404 на `/metrics`** | Метрики не включены в конфигурации, либо запрос отправлен на публичный entrypoint вместо выделенного порта | `curl -i http://127.0.0.1:8082/metrics` | Проверить секцию `metrics.prometheus`. Если задан `entryPoint: metrics`, обращаться строго на порт этого entrypoint |
| **Всплеск RAM в Prometheus (High Cardinality)** | Включена директива `addRoutersLabels: true` или кастомные `headerLabels` при наличии сотен уникальных путей/заголовков | `curl -s localhost:8082/metrics \| wc -l` возвращает > 100 000 строк | Отключить `addRoutersLabels` в `traefik.yml`; агрегировать метрики на уровне `entryPoints` и `services` |
| **Высокий I/O wait диска из-за логов** | Директива `accessLog.bufferingSize: 0` при высоком RPS (> 2 000 req/s) | `iostat -xz 1` фиксирует 100% util на разделе `/var/log` | Задать `accessLog.bufferingSize: 100-500` для пакетной асинхронной записи |
| **Утечка токенов в логах** | Заголовки `Authorization` или `Cookie` сохраняются в открытом виде | Поиск токенов: `grep -i "bearer" /var/log/traefik/access.log` | Настроить секцию `accessLog.fields.headers.names` с режимом `redact` |
| **Трейсы не поступают в OTel Collector** | Устаревший синтаксис v2 (`tracing.openTelemetry.address`), неверный протокол (gRPC vs HTTP) или блокировка firewall | Лог Traefik: `failed to export traces: context deadline exceeded` | В v3 использовать блок `tracing.otlp.grpc` (порт 4317) или `tracing.otlp.http` (порт 4318), проверить параметр `insecure` |
| **Ротация логов не работает (файл пишется в `.1`)** | Logrotate не отправляет сигнал `USR1`, либо Traefik запущен в Windows-окружении | `lsof \| grep access.log.1` показывает, что дескриптор удерживается процессом | Добавить блок `postrotate` с `kill -USR1 $(pidof traefik)` в `/etc/logrotate.d/traefik` |
| **Метрики `traefik_service_server_up` равны 0** | Ошибки во встроенных health check сервиса, upstream возвращает код, отличный от 2xx-3xx | `curl -I http://backend_ip:port/health` | Проверить параметры `healthCheck.path`, `interval` и `timeout` в динамической конфигурации сервиса |

---

### Правила алертинга Alertmanager и SLO

Готовый набор продуктивных правил мониторинга для Prometheus Alertmanager (`traefik_alerts.yml`):

```yaml
# /etc/prometheus/rules/traefik_alerts.yml
groups:
  - name: traefik_slo_rules
    rules:
      # Расчет суммарного RPS на уровне входных шлюзов
      - record: job:traefik_entrypoint_requests:rate5m
        expr: sum(rate(traefik_entrypoint_requests_total[5m])) by (entrypoint)

      # Доля серверных ошибок (5xx) в процентах
      - record: job:traefik_entrypoint_error_ratio:ratio5m
        expr: |
          sum(rate(traefik_entrypoint_requests_total{code=~"5.."}[5m])) by (entrypoint)
          /
          sum(rate(traefik_entrypoint_requests_total[5m])) by (entrypoint)

      # 99-й перцентиль времени обработки запросов сервисами
      - record: job:traefik_service_latency_p99:seconds
        expr: |
          histogram_quantile(0.99,
            sum(rate(traefik_service_request_duration_seconds_bucket[5m])) by (le, service)
          )

  - name: traefik_production_alerts
    rules:
      - alert: TraefikHigh5xxErrorRate
        expr: job:traefik_entrypoint_error_ratio:ratio5m > 0.02
        for: 3m
        labels:
          severity: critical
          tier: networking
        annotations:
          summary: "Высокий уровень 5xx ошибок на точке входа {{ $labels.entrypoint }}"
          description: "Доля ошибок 5xx составляет {{ $value | humanizePercentage }} за последние 5 минут (порог: 2%)."

      - alert: TraefikServiceLatencyP99Degraded
        expr: job:traefik_service_latency_p99:seconds > 1.0
        for: 5m
        labels:
          severity: warning
          tier: service
        annotations:
          summary: "Деградация задержки P99 на сервисе {{ $labels.service }}"
          description: "P99 latency сервиса {{ $labels.service }} превышает 1.0 сек (текущее: {{ $value | humanizeDuration }})."

      - alert: TraefikNoHealthyBackends
        expr: sum(traefik_service_server_up) by (service) == 0
        for: 1m
        labels:
          severity: page
          tier: infrastructure
        annotations:
          summary: "Все бэкенды сервиса {{ $labels.service }} недоступны"
          description: "Сервис {{ $labels.service }} полностью исключен из балансировки. Traefik возвращает клиентам 503 Service Unavailable."

      - alert: TraefikConfigReloadFailed
        # Фиксация попыток релоада при неизменном таймштампе успешной перезагрузки
        expr: increase(traefik_config_reloads_total[5m]) > 0 and changes(traefik_config_last_reload_success[5m]) == 0
        for: 2m
        labels:
          severity: warning
          tier: control-plane
        annotations:
          summary: "Сбой применения конфигурации Traefik"
          description: "Динамическая конфигурация содержит синтаксические или логические ошибки. Предыдущая рабочая версия сохранена."

      - alert: TraefikTLSCertificateExpiringSoon
        # Оповещение за 14 дней до истечения срока действия X.509 сертификата
        expr: (traefik_tls_certs_not_after - time()) < (86400 * 14)
        for: 1h
        labels:
          severity: warning
          tier: security
        annotations:
          summary: "Истекает срок действия TLS-сертификата"
          description: "Сертификат перестанет действовать через {{ $value | humanizeDuration }}. Проверьте ACME/Lego логи."

      - alert: TraefikHighConnectionSpike
        expr: sum(traefik_open_connections) by (entrypoint) > 10000
        for: 2m
        labels:
          severity: warning
          tier: capacity
        annotations:
          summary: "Всплеск открытых L4-соединений на {{ $labels.entrypoint }}"
          description: "Число одновременных открытых соединений достигло {{ $value }} (возможен Slowloris или всплеск нагрузки)."
```

---

## Рекомендации (Best Practices)

1. **Сетевая изоляция портов телеметрии:**
   - Никогда не совмещайте эндпоинты `/metrics`, `/ping` и Traefik Dashboard с публичными точками входа (порты 80/443).
   - Привязывайте служебный entrypoint к локальному адресу `127.0.0.1` либо к изолированному служебному интерфейсу (Management VLAN, WireGuard/Tinc).

2. **Защита от кардинального взрыва (High Cardinality):**
   - Держите параметр `addRoutersLabels: false` в продуктивных средах с большим числом микросервисов.
   - Избегайте использования заголовков с уникальными значениями (UUID, токены, URL с GET-параметрами) в директиве `metrics.prometheus.headerLabels`.
   - Настраивайте `buckets` латентности под реальные требования SLO проекта; не создавайте десятки промежуточных бакетов без необходимости.

3. **Оптимизация производительности логов:**
   - На серверах с трафиком свыше 1 000 RPS всегда используйте параметр `accessLog.bufferingSize` (рекомендуемый диапазон: `100`–`500` строк).
   - При наличии централизованного сборщика логов на хосте (Promtail, Vector, Fluentbit) рассмотрите передачу логов в `stdout` с последующей агрегацией через `systemd-journald` во избежание двойной записи на диск.
   - Используйте фильтры `minDuration` и `statusCodes`, чтобы отсекать рутинные HTTP 200/301 запросы и сохранять на диск только аномалии и деградации.

4. **Информационная безопасность и комплаенс:**
   - Обязательно настраивайте правила `redact` для заголовков `Authorization`, `Proxy-Authorization`, `Cookie`, `Set-Cookie`.
   - Исключайте поле `ClientUsername` из access-логов, чтобы пароли из basic-auth ссылок (`http://user:pass@host`) не оседали в открытом виде на диске.

5. **Оптимизация трейсинга OTLP:**
   - Всегда выставляйте `tracing.sampleRate` в диапазоне `0.01`–`0.1` на высоконагруженных шлюзах. 100% сэмплирование создает тяжелый сетевой оверхед и перегружает сборщик трейсов.
   - Подключайте Traefik к локальному экземпляру OpenTelemetry Collector (через `127.0.0.1:4317` по gRPC), а пакетную агрегацию, аутентификацию и отправку в долгосрочные хранилища делегируйте коллектору.

---

## Дополнительная информация

### Внутренние ссылки базы знаний
- [Обзор архитектуры Traefik](./traefik_overview.md) — базовые концепции, статическая и динамическая конфигурация, точки входа.
- [Отказоустойчивость и HA Traefik](./traefik-high-availability.md) — масштабирование узлов, VIP-адреса и синхронизация состояния.
- [Развертывание Traefik на Bare-Metal](./traefik-bare-metal.md) — запуск под управлением systemd, тюнинг ядра Linux и сетевого стека.
- [Мониторинг сертификатов Traefik](./traefik-cert-monitoring.md) — контроль срока действия ACME, Blackbox Exporter и алерты.
- [Миграция с Traefik v2 на v3](./traefik-migration-v2-to-v3.md) — изменения синтаксиса OTLP-трейсинга, удаление старых провайдеров и обновление метрик.
- [Диагностика и профилирование Traefik](./traefik-debugging-performance.md) — анализ производительности pprof, трейсинг узких мест и устранение деградаций.

### Внешние ресурсы
- [Официальная документация Traefik: Metrics (Prometheus)](https://doc.traefik.io/traefik/observability/metrics/prometheus/) — параметры провайдера Prometheus.
- [Официальная документация Traefik: Access Logs](https://doc.traefik.io/traefik/observability/access-logs/) — спецификация полей, фильтров и форматирования журналов.
- [Официальная документация Traefik: Tracing (OpenTelemetry)](https://doc.traefik.io/traefik/observability/tracing/opentelemetry/) — параметры OTLP-экспортера.
- [Grafana Dashboards: Официальный дашборд Traefik](https://grafana.com/grafana/dashboards/17346) — готовый шаблон визуализации метрик для On-Premises окружений (ID 17346).
- [Спецификация OpenTelemetry Semantic Conventions v1.26+](https://opentelemetry.io/docs/specs/semconv/http/http-spans/) — стандарты наименования HTTP-атрибутов и спанов.