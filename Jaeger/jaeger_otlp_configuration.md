# OTLP Configuration для Jaeger

> **Важно:** Документация описывает **Jaeger v2** (текущая версия).

**OTLP Configuration для Jaeger** — это детальная настройка протокола OpenTelemetry Protocol (OTLP) на уровне Collector для приема трейсов от приложений. В Jaeger v2 OTLP является единственным нативным протоколом, и правильная конфигурация receivers (compression, retry, auth, batch limits) напрямую влияет на стабильность сбора данных, сетевой overhead и безопасность. В 2026 году production-системы требуют mTLS, compression и circuit breaker на уровне OTLP receiver.

Общий обзор протокола: **[Протокол OTLP](../OpenTelemetry/otlp_protocol.md)**.
Архитектура Jaeger: **[Архитектура Jaeger](./jaeger_architecture.md)**.
Развертывание: **[Варианты развертывания Jaeger](./jaeger_deployment_options.md)**.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **OTLP (OpenTelemetry Protocol)** | Унифицированный протокол для передачи телеметрии (traces, metrics, logs, profiles) на основе Protocol Buffers |
| **gRPC Transport** | Бинарный транспорт OTLP на порту 4317. Предпочтительный для high-load благодаря HTTP/2 и streaming |
| **HTTP/Protobuf Transport** | OTLP поверх HTTP/1.1 или HTTP/2 с Protobuf body на порту 4318 |
| **HTTP/JSON Transport** | OTLP поверх HTTP с JSON body. Наименее эффективный, используется для совместимости |
| **Compression** | Сжатие payload OTLP: `gzip`, `snappy`, `zstd`. Снижает сетевой overhead в 2–10 раз |
| **Retry Policy** | Политика повторных попыток при временных сбоях (network errors, 5xx) |
| **mTLS (mutual TLS)** | Взаимная TLS-аутентификация между отправителем и Collector |
| **Circuit Breaker** | Механизм отключения receiver при превышении лимитов для защиты Collector от OOM |

---

## Базовые концепции

### Сравнение транспортов OTLP

| Характеристика | gRPC (4317) | HTTP/Protobuf (4318) | HTTP/JSON (4318) |
| :--- | :--- | :--- | :--- |
| **Производительность** | Высокая (HTTP/2, multiplexing) | Средняя | Низкая |
| **Compression** | gzip, snappy, zstd | gzip, deflate, snappy, zstd | gzip |
| **Streaming** | Да (bidirectional) | Нет | Нет |
| **Metadata/Headers** | binary headers | HTTP headers | HTTP headers |
| **Рекомендация** | Production, high-load | Совместимость, firewalls | Отладка, legacy |

### Параметры конфигурации receiver

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
        max_recv_msg_size: 4mb
        max_connection_age: 1h
        max_connection_age_grace: 30s
        tls:
          cert_file: /etc/jaeger/certs/server.crt
          key_file: /etc/jaeger/certs/server.key
          client_ca_file: /etc/jaeger/certs/ca.crt
        # Примечание: compression и retry настраиваются на стороне exporter/клиента
      
      http:
        endpoint: 0.0.0.0:4318
        cors:
          allowed_origins: ["*"]
        # Для HTTP/Protobuf используется тот же endpoint
```

### Compression

| Алгоритм | Степень сжатия | Скорость | Использование |
| :--- | :--- | :--- | :--- |
| **gzip** | Средняя (2–3x) | Средняя | Стандартный выбор, совместимость |
| **snappy** | Низкая (1.5–2x) | Очень высокая | Low-latency системы |
| **zstd** | Высокая (3–10x) | Высокая | Рекомендуется для high-load (2026) |

**Конфигурация на стороне Collector (exporter):**

```yaml
exporters:
  otlp:
    endpoint: "jaeger-collector:4317"
    compression: zstd
    retry:
      initial_interval: 1s
      max_interval: 30s
      max_elapsed_time: 300s
    timeout: 10s
    sending_queue:
      size: 1000
      num_consumers: 4
```

**Конфигурация на стороне приложения (OpenTelemetry SDK):**

```bash
# Environment variables
export OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger-collector:4317
export OTEL_EXPORTER_OTLP_COMPRESSION=zstd
export OTEL_EXPORTER_OTLP_TIMEOUT=10000
```

### Retry Policy

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `initial_interval` | Начальная задержка перед повторной попыткой | `1s` |
| `max_interval` | Максимальная задержка между попытками | `30s` |
| `max_elapsed_time` | Общее время повторных попыток | `300s` (5 минут) |
| `backoff_multiplier` | Множитель увеличения задержки | `1.5` |

### Аутентификация и авторизация

| Метод | Применение | Конфигурация |
| :--- | :--- | :--- |
| **mTLS** | Взаимная аутентификация между SDK и Collector | TLS на порту 4317 с client CA |
| **Bearer Token** | API-ключ в заголовке `Authorization` | `bearertokenauth` extension в Collector |
| **API Key** | Простой ключ в заголовке `x-api-key` | Прокси или OTel Collector auth extension |
| **OAuth2 / OIDC** | Корпоративные среды с SSO | Внешний прокси (OAuth2 Proxy) перед Collector |

### Batch Limits и Backpressure

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `max_recv_msg_size` | Максимальный размер входящего сообщения | `4mb` (по умолчанию 4 MB) |
| `max_connection_age` | Максимальное время жизни соединения | `1h` (prevent stale connections) |
| `memory_limiter` | Ограничение памяти Collector | `limit_mib: 1536`, `spike_limit_mib: 512` |

---

## Практические сценарии

### Сценарий 1: Конфигурация gRPC receiver с zstd compression

```yaml
# otel-collector-config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
        max_recv_msg_size: 4mb
        max_connection_age: 1h
        max_connection_age_grace: 30s
        tls:
          cert_file: /etc/jaeger/certs/server.crt
          key_file: /etc/jaeger/certs/server.key
          client_ca_file: /etc/jaeger/certs/ca.crt

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 1536
    spike_limit_mib: 512
  batch:
    send_batch_size: 1024
    timeout: 10s

exporters:
  jaeger_storage_exporter:
    trace_storage:
      type: clickhouse
      options:
        clickhouse:
          endpoint: "tcp://clickhouse:9000"
          database: jaeger_v2

service:
  extensions: [jaeger_storage]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [jaeger_storage_exporter]
```

**Клиентская конфигурация (Java):**

```java
// application.properties
otel.exporter.otlp.endpoint=http://jaeger-collector:4317
otel.exporter.otlp.compression=zstd
otel.exporter.otlp.timeout=10000
otel.traces.exporter=otlp
otel.resource.attributes=service.name=my-app,service.version=1.0.0
```

**Валидация:**

```bash
# Проверка gRPC health
grpcurl -plaintext localhost:4317 list

# Проверка метрик
curl -s http://localhost:8888/metrics | grep otelcol_receiver_accepted_spans
```

### Сценарий 2: mTLS между SDK и Collector

**Ситуация:** Необходимо настроить взаимную TLS-аутентификацию для защиты порта 4317.

```bash
# 1. Генерация CA
openssl req -x509 -newkey rsa:4096 -keyout ca.key -out ca.crt -days 365 -nodes -subj "/CN=Jaeger CA"

# 2. Генерация сертификата сервера (Collector)
openssl req -newkey rsa:4096 -keyout server.key -out server.csr -nodes -subj "/CN=jaeger-collector.observability.svc"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 365

# 3. Генерация клиентского сертификата
openssl req -newkey rsa:4096 -keyout client.key -out client.csr -nodes -subj "/CN=otel-client"
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out client.crt -days 365

# 4. Создание Secret в Kubernetes
kubectl create secret generic jaeger-certs \
  --from-file=server.crt \
  --from-file=server.key \
  --from-file=ca.crt \
  --from-file=client.crt \
  --from-file=client.key \
  -n observability
```

**Конфигурация Collector:**

```yaml
# otel-collector.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: otel-collector-config
  namespace: observability
data:
  config.yaml: |
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
            tls:
              cert_file: /etc/certs/server.crt
              key_file: /etc/certs/server.key
              client_ca_file: /etc/certs/ca.crt
```

**Клиентская конфигурация:**

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=https://jaeger-collector.observability.svc:4317
export OTEL_EXPORTER_OTLP_CERTIFICATE=/path/to/client.crt
export OTEL_EXPORTER_OTLP_CLIENT_KEY=/path/to/client.key
export OTEL_EXPORTER_OTLP_CLIENT_CA=/path/to/ca.crt
```

**Валидация:**

```bash
# Проверка mTLS handshake
openssl s_client -connect jaeger-collector:4317 -cert client.crt -key client.key -CAfile ca.crt

# Проверка без сертификата (должна быть ошибка)
openssl s_client -connect jaeger-collector:4317
# → SSL routines:ssl3_get_record:wrong version number
```

### Сценарий 3: Настройка retry и circuit breaker

**Ситуация:** При недоступности ClickHouse Collector должен повторять попытки и защищаться от каскадных сбоев.

```yaml
exporters:
  jaeger_storage_exporter:
    trace_storage:
      type: clickhouse
      options:
        clickhouse:
          endpoint: "tcp://clickhouse:9000"
          database: jaeger_v2
    retry:
      initial_interval: 1s
      max_interval: 30s
      max_elapsed_time: 300s
    sending_queue:
      size: 1000
      num_consumers: 4
    timeout: 10s

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 1536
    spike_limit_mib: 512
```

**Валидация:**

1. Остановить ClickHouse: `docker stop clickhouse`.
2. Отправить тестовые спаны.
3. Проверить метрики: `curl http://localhost:8888/metrics | grep otelcol_exporter_send_failed_spans`.
4. Запустить ClickHouse и убедиться, что спаны записались.

---

## Типичные проблемы и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Connection refused на 4317** | gRPC receiver не запущен или endpoint неверный | Проверить `kubectl get pods -l app=jaeger-collector`, логи Collector |
| **TLS handshake failure** | Неверный сертификат или клиент не предоставляет сертификат при mTLS | Проверить `tls` блок в конфигурации, логировать handshake errors |
| **High CPU на Collector** | Отсутствует compression или слишком большой `max_recv_msg_size` | Включить `zstd` compression, ограничить `max_recv_msg_size` |
| **Backpressure / OOM** | Отсутствует `memory_limiter` или `sending_queue` переполнен | Добавить `memory_limiter`, настроить `sending_queue.size` |
| **Спаны не поступают при высокой нагрузке** | `batch` processor переполнен или `send_batch_size` слишком большой | Уменьшить `send_batch_size`, увеличить `timeout` |

---

## Лучшие практики

1.  **Используйте gRPC + zstd:** Это оптимальный выбор для production в 2026 году.
2.  **Включайте mTLS на порту 4317:** Защитите Collector от несанкционированной отправки спанов.
3.  **Ограничивайте `max_recv_msg_size`:** Защита от DoS через oversized payload.
4.  **Настраивайте retry с backoff:** При падении ClickHouse спаны не должны теряться без повторов.
5.  **Используйте `memory_limiter`:** Обязательно на первом месте в пайплайне для защиты от OOM.

---

## Очистка окружения

```bash
# Удаление секретов с сертификатами
kubectl delete secret jaeger-certs -n observability

# Очистка Docker
docker compose down -v
```

---

## Дополнительная информация

**Смежные темы:**

* Протокол OTLP: **[Протокол OTLP](../OpenTelemetry/otlp_protocol.md)**
* Безопасность и RBAC: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**
* Обработка ошибок и backpressure: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**
* Интеграция с Istio: **[Интеграция Jaeger с Service Mesh](./jaeger_service_mesh_integration.md)**

### См. также

* [OpenTelemetry Collector OTLP Configuration](https://opentelemetry.io/docs/collector/configuration/#otlp)
* [Jaeger gRPC/HTTP Configuration](https://www.jaegertracing.io/docs/latest/configuration/)
