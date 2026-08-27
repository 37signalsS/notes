# Архитектура Jaeger

> **Важно:** Документация описывает **Jaeger v2**. Jaeger v1 достиг **EOL (End of Life)**.

**Архитектура Jaeger v2** спроектирована как нативное расширение **OpenTelemetry Collector**. Это означает, что компоненты Jaeger теперь интегрированы непосредственно в бинарный файл OpenTelemetry, что обеспечивает унификацию пайплайнов телеметрии, нативную поддержку протокола OTLP и бесшовную интеграцию с экосистемой OpenTelemetry.

Общий обзор возможностей системы: **[Обзор Jaeger](./jaeger_overview.md)**.

---

## Определения

| Компонент | Назначение |
| :--- | :--- |
| **OpenTelemetry SDK** | Библиотека для инструментирования кода приложения. Генерирует спаны и передает их в коллектор по протоколу OTLP. Рекомендуется как замена устаревшим Jaeger Clients |
| **Jaeger Binary (v2)** | Единый бинарный файл, который может запускаться в различных ролях (Collector, Query, All-in-one). Построен на базе OTel Collector |
| **OTEL_COLLECTOR_ROLE** | Концепция v2, где роль компонента определяется конфигурационным файлом YAML, а не отдельными исполняемыми файлами |
| **Storage Extension** | Специализированный модуль Jaeger v2 для взаимодействия с бэкендами хранения (Elasticsearch, ClickHouse и др.) в рамках OTel Collector |
| **Sampling Extension** | Модуль для реализации стратегий адаптивного сэмплирования, заменяющий централизованное управление сэмплированием из v1 |
| **Jaeger Ingester** | Роль бинарного файла, считывающая данные из Kafka и записывающая их в Storage с использованием Jaeger Storage API |
| **Jaeger Query** | Сервис, предоставляющий API и UI для извлечения данных из хранилища |
| **Jaeger UI** | Веб-интерфейс на React для поиска, просмотра и анализа трассировок. В v2 интегрирован в Query extension |
| **Agent Mode (OTel Collector)** | Режим работы коллектора как локального edge-агента, заменяющий Jaeger Agent v1. Выполняет батчинг, обогащение метаданными и пересылку в центральный коллектор |

---

## Базовые концепции

### Трансформация из Jaeger v1 в v2

Jaeger v1 использовал архитектуру с отдельными бинарными файлами для каждой роли:
- **Jaeger Agent** — sidecar или локальный процесс для приема спанов от SDK
- **Jaeger Collector** — серверный компонент для валидации и обработки
- **Jaeger Query** — сервис доступа к данным
- **Jaeger UI** — отдельный процесс

В v2 эта модель заменена на **единый бинарный файл на базе OpenTelemetry Collector**. Ключевые преимущества перехода:
- **Унификация протоколов:** Нативный OTLP вместо смеси Thrift, gRPC и Zipkin форматов
- **Гибкость пайплайнов:** Возможность использования любых стандартных процессоров OpenTelemetry (transform, k8sattributes, spanmetrics и др.)
- **Упрощение эксплуатации:** Один образ Docker вместо нескольких, единая модель конфигурации YAML
- **Расширяемость:** Добавление новых функциональных блоков через механизм Extensions без изменения ядра

### Поток данных в Jaeger v2

В версии v2 путь прохождения трассировки базируется на пайплайнах OpenTelemetry:

`Приложение (OTel SDK) → [OTel Collector (Agent Mode)] → Jaeger v2 (Collector Mode) → [Kafka → Ingester] → Storage → Query → UI`

1.  **Инструментированное приложение:** Отправляет трейсы по OTLP (gRPC: 4317, HTTP: 4318).
2.  **OTel Collector (Agent Mode):** Заменяет `jaeger-agent`. Принимает данные локально, выполняет первичную обработку (батчинг, добавление метаданных инфраструктуры) и пересылает в центральный коллектор.
3.  **Jaeger v2 (Collector Mode):** Принимает данные через `otlp` receiver, обрабатывает их через `processors` и передает в `jaeger_storage_exporter`.
4.  **Kafka & Ingester:** Используются для сглаживания пиков. Collector пишет в Kafka (через `kafka` exporter), а Ingester читает из нее и пишет в финальное хранилище.
5.  **Storage:** Elasticsearch, Cassandra или ClickHouse.
6.  **Query & UI:** Предоставляет доступ к данным через HTTP (порт 16686).

### Ролевая модель (Roles)

В Jaeger v2 один и тот же бинарный файл может выполнять разные задачи в зависимости от набора включенных компонентов в YAML-конфигурации:

*   **All-in-one:** Включает все компоненты (receiver, storage, query, UI) и использует in-memory или Badger хранилище.
*   **Collector:** Включает только `receivers` (OTLP) и `exporters` для записи в БД или Kafka.
*   **Ingester:** Включает `receiver` для Kafka и `exporter` для записи в БД.
*   **Query:** Включает `jaeger_query` extension и предоставляет доступ к данным и UI.

### Механизм расширений (Extensions)

В отличие от v1, где каждый компонент был отдельным сервисом, v2 использует механизм **Extensions** OTel Collector для добавления функциональности Jaeger:

- **Storage Extension:** Предоставляет единый интерфейс для всех бэкендов хранения. Управляет пулом соединений, повторными попытками и retry-логикой.
- **Sampling Extension:** Реализует стратегии сэмплирования (probabilistic, rate limiting, remote). В v2 стратегии могут быть частью пайплайна, что позволяет применять их до экспорта данных.
- **Query Extension:** Заменяет отдельный Query-сервис v1. Предоставляет REST API и статические файлы UI.
- **jaeger_storage_exporter:** Специализированный exporter, который преобразует OTLP-спаны в формат хранения Jaeger и использует Storage Extension для записи.

### Порты Jaeger v2

| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| **4317** | gRPC | OTLP приемник (основной для v2) |
| **4318** | HTTP | OTLP приемник |
| **16686** | HTTP | Jaeger UI и Query API |
| **14250** | gRPC | Jaeger Collector (для обратной совместимости с агентами v1) |
| **14268** | HTTP | Прием Jaeger Thrift (устарело) |
| **9411** | HTTP | Прием Zipkin спанов |
| **8888** | HTTP | Метрики самого Jaeger (Prometheus format) |
| **6831** | UDP | Jaeger Agent (только для обратной совместимости с v1 SDK) |
| **5778** | HTTP | Конфигурация агента (tracing sampling, v1) |

### Хранилище и расширение Storage

Jaeger v2 использует механизм расширений (**Extensions**) для интеграции с базами данных. Это позволяет:
- Использовать единый пул соединений для всех пайплайнов.
- Поддерживать специфичные для Jaeger индексы и оптимизации.
- **ClickHouse:** В v2 стал первоклассным гражданином (first-class citizen). Архитектура ClickHouse позволяет хранить миллиарды спанов с минимальными затратами на ресурсы по сравнению с Elasticsearch.

### Адаптивное сэмплирование (Adaptive Sampling)

В v2 адаптивное сэмплирование реализовано через `sampling` extension.
1.  Коллектор анализирует входящий поток данных по каждому сервису и операции.
2.  На основе целевого RPS (например, 10 трейсов в секунду на сервис) рассчитывается вероятность сэмплирования.
3.  Вероятности отдаются SDK приложений через расширение (бинарный файл Jaeger выступает в роли сервера стратегий).

### Обработка пиковых нагрузок и backpressure

Архитектура Jaeger v2 включает несколько механизмов для устойчивости к перегрузкам:

- **Memory Limiter Processor:** Предотвращает исчерпание памяти коллектора при всплесках трафика. Конфигурирует лимиты памяти и принудительно сбрасывает данные при превышении.
- **Batch Processor:** Группирует спаны перед отправкой, уменьшая количество сетевых вызовов и сглаживая пики.
- **Kafka как буфер:** В streaming-архитектуре Kafka выступает как промежуточный буфер между Collector и Ingester. Это отделяет SLA приема данных от скорости записи в хранилище.
- **Circuit Breaker в Storage Extension:** При недоступности хранилища экспортер может включать circuit breaker, чтобы не перегружать сеть futile retry-запросами.

### Ограничения архитектуры

- **In-memory хранилище:** Поддерживается только в All-in-one режиме. Данные теряются при перезапуске. Не рекомендуется для production.
- **Badger:** Встраиваемое хранилище на основе LSM-tree. Подходит для небольших инсталляций (до 1M спанов/день), но не поддерживает горизонтальное масштабирование.
- **Elasticsearch:** Требует тщательного планирования индексов и шардирования. При росте выше 10TB требует использования ISM (Index State Management).
- **ClickHouse:** Не имеет встроенного механизма TTL на уровне строк — требует явной конфигурации партиций и TTL на уровне таблицы.
- **Latency penalty в Kafka-пайплайне:** Добавляет задержку 1-5 секунд (зависит от `decision_wait` в tail-sampling) перед записью в хранилище.
- **Cardinality тегов:** Высокая кардинальность тегов (например, `user_id` с миллионами значений) приводит к взрыву индексов в Elasticsearch и росту потребления памяти в ClickHouse.

---

## Практические сценарии

### Подготовка окружения

**Минимальные требования для запуска All-in-one:**
- CPU: 0.5 - 1 ядро
- RAM: 512MB - 2GB
- Docker Engine 20.10+ или Kubernetes 1.24+

**Для Production с ClickHouse:**
- CPU: 2 - 4 ядра на инстанс Collector
- RAM: 2GB - 4GB на инстанс Collector
- ClickHouse кластер: минимум 3 узла для HA

**Сетевые порты (входящие):**
- 4317/tcp — OTLP gRPC
- 4318/tcp — OTLP HTTP
- 16686/tcp — UI и Query API

### Сценарий 1: Локальная валидация архитектуры через Docker Compose

**Ситуация:** Необходимо быстро проверить, что компоненты Jaeger v2 корректно взаимодействуют между собой в режиме All-in-one, без развертывания production-инфраструктуры.

```yaml
# compose.yml
services:
  jaeger:
    image: jaegertracing/jaeger:2.0
    ports:
      - "16686:16686" # UI и Query API
      - "4317:4317"   # OTLP gRPC (основной порт для v2)
      - "4318:4318"   # OTLP HTTP
    environment:
      - SPAN_STORAGE_TYPE=memory
      - METRICS_STORAGE_TYPE=prometheus
```

**Валидация:**

1.  Отправить тестовый спан из приложения на `localhost:4317` (gRPC) или `localhost:4318` (HTTP).
2.  Открыть `http://localhost:16686` и убедиться, что сервис отображается в выпадающем списке.
3.  Выполнить поиск по `service=имя-сервиса` и проверить, что спан содержит корректные атрибуты (`http.method`, `http.status_code`).

**Ожидаемый результат:** Трасса появляется в UI в течение 1–2 секунд после отправки. При использовании in-memory хранилища данные исчезают после перезапуска контейнера.

### Сценарий 2: Production развертывание с ClickHouse

Jaeger v2 рекомендует ClickHouse как наиболее эффективное хранилище. Пример конфигурации коллектора:

```yaml
# collector-config.yaml
receivers:
  otlp:
    protocols:
      grpc:
      http:

exporters:
  jaeger_storage_exporter:
    trace_storage:
      type: clickhouse
      options:
        clickhouse:
          endpoint: "tcp://clickhouse-server:9000"
          database: jaeger_v2

service:
  extensions: [jaeger_storage]
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [jaeger_storage_exporter]
```

**Валидация:**

1.  Применить конфигурацию: `jaeger --config collector-config.yaml`.
2.  Отправить тестовый спан и убедиться, что он появился в UI через `http://localhost:16686`.
3.  Проверить метрики: `curl http://localhost:8888/metrics | grep jaeger_exporter_send_spans` — количество отправленных спанов должно расти.
4.  Проверить таблицы в ClickHouse: `SELECT count() FROM jaeger_v2.spans` — количество записей должно совпадать с отправленными спанами.

### Сценарий 3: Настройка роли Ingester (Kafka -> ClickHouse)

Пример конфигурации для асинхронной записи данных в ClickHouse:

```yaml
# ingester-config.yaml
receivers:
  kafka:
    brokers: ["kafka:9092"]
    topic: jaeger-spans
    protocol_version: 2.0.0

processors:
  batch:

exporters:
  jaeger_storage_exporter:
    trace_storage:
      type: clickhouse
      options:
        clickhouse:
          endpoint: "tcp://clickhouse:9000"
          database: jaeger

service:
  extensions: [jaeger_storage]
  pipelines:
    traces:
      receivers: [kafka]
      processors: [batch]
      exporters: [jaeger_storage_exporter]
```

**Валидация:**

1.  Запустить Ingester: `jaeger --config ingester-config.yaml`.
2.  Отправить спаны в Kafka через Collector.
3.  Проверить, что Ingester потребляет сообщения: `curl http://localhost:8888/metrics | grep kafka_received_messages`.
4.  Убедиться, что спаны появились в ClickHouse: `SELECT count() FROM jaeger.spans`.

### Сценарий 4: Настройка роли Query с UI

Конфигурация для запуска только интерфейса и API доступа к данным:

```yaml
# query-config.yaml
extensions:
  jaeger_storage:
    trace_storage:
      type: elasticsearch
      options:
        elasticsearch:
          server-urls: ["http://elasticsearch:9200"]
  jaeger_query:
    ui:
      config_file: /etc/jaeger/ui.json

service:
  extensions: [jaeger_storage, jaeger_query]
  pipelines:
    # Пайплайн traces не нужен, если Query только читает данные
    traces:
      receivers: []
      exporters: []
```

**Валидация:**

1.  Запустить Query: `jaeger --config query-config.yaml`.
2.  Открыть UI: `http://localhost:16686`.
3.  Выполнить поиск по сервису и убедиться, что UI загружает данные из Elasticsearch.

---

## Типичные проблемы и устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Спаны не появляются в UI | Collector не запущен или порт 4317 закрыт | Проверить `curl localhost:4317` и логи Collector |
| Высокая задержка между отправкой и отображением | Отсутствует Batch processor или слишком большой `timeout` | Добавить `batch` processor с `timeout: 5s`, `send_batch_size: 512` |
| Collector падает с OOM | Отсутствует `memory_limiter` processor при высокой нагрузке | Добавить `memory_limiter` с `limit_mib: 512` и `check_interval: 1s` |
| Данные не сохраняются в ClickHouse | Неверный `endpoint` или база данных не существует | Проверить подключение: `clickhouse-client --host clickhouse-server --query "SHOW DATABASES"` |
| Kafka не потребляет сообщения | Ingester не запущен или неверный `topic` | Проверить `kafka-console-consumer --topic jaeger-spans --from-beginning` |
| UI показывает пустой список сервисов | Query extension не настроен или хранилище пустое | Проверить конфигурацию `jaeger_storage` и наличие данных в БД |
| Ошибка TLS при подключении к ClickHouse | Отсутствуют сертификаты или неверный `tls` конфиг | Проверить секреты и конфигурацию `tls` в Storage Extension |

---

## Лучшие практики и очистка

### Лучшие практики

- **OTLP повсеместно:** Используйте порты 4317/4318 как единственные точки входа для трейсов. Отключите устаревшие протоколы (Thrift, Zipkin) в production.
- **Memory Limiter:** Всегда добавляйте `memory_limiter` processor в начале пайплайна для защиты от OOM при всплесках.
- **Batch Processing:** Настройте `batch` processor с параметрами, соответствующими вашей нагрузке (`send_batch_size: 1024`, `timeout: 10s`).
- **Мониторинг Collector:** Экспортируйте метрики на порт 8888 и настройте алерты на `otelcol_receiver_refused_spans` и `otelcol_exporter_send_failed_spans`.
- **ClickHouse TTL:** Настройте TTL на уровне таблицы для автоматического удаления старых трейсов (`TTL createdAt + INTERVAL 7 DAY`).
- **Семантические конвенции:** Используйте стандартные атрибуты OpenTelemetry (`http.method`, `db.system`) для корректной работы UI и поиска.

### Очистка окружения

```bash
# Остановка Docker Compose окружения
docker compose down -v

# Удаление данных ClickHouse (если использовался Docker)
docker volume rm jaeger_clickhouse_data

# Очистка старых спанов из in-memory (перезапуск контейнера)
docker restart jaeger

# Удаление тестовых ресурсов Kubernetes
kubectl delete namespace jaeger-test
```

---

## Дополнительная информация

**Смежные темы:**

* Варианты развертывания и масштабирования: **[Варианты развертывания](./jaeger_deployment_options.md)**
* Специфика работы в Kubernetes: **[Интеграция с Kubernetes](./jaeger_kubernetes_integration.md)**
* Анализ производительности и Tail-sampling: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**
* Общий обзор системы: **[Обзор Jaeger](./jaeger_overview.md)**
* Query API Reference: **[Query API Jaeger](./jaeger_query_api.md)**
* Миграция с v1 на v2: **[Миграция Jaeger v1 → v2](./jaeger_migration_v1_to_v2.md)**
* Capacity Planning: **[Capacity Planning для Jaeger](./jaeger_capacity_planning.md)**
* Storage Deep Dive: **[Storage Deep Dive](./jaeger_storage_deep_dive.md)**
* HA и Disaster Recovery: **[High Availability и DR](./jaeger_high_availability.md)**
* Интеграция с Grafana: **[Интеграция Jaeger с Grafana](./jaeger_grafana_integration.md)**
* Service Mesh Integration: **[Интеграция Jaeger с Service Mesh](./jaeger_service_mesh_integration.md)**
* OTLP Configuration: **[OTLP Configuration для Jaeger](./jaeger_otlp_configuration.md)**
* eBPF и Auto-instrumentation: **[eBPF и автоматическая инструментация](./jaeger_ebpf_auto_instrumentation.md)**
* Multi-tenancy: **[Multi-tenancy и изоляция](./jaeger_multi_tenancy.md)**
* Security Hardening: **[Security Hardening для Jaeger](./jaeger_security_hardening.md)**
* Стандарт OTLP: **[OTLP Protocol](../OpenTelemetry/otlp_protocol.md)**

### См. также
* [Official Jaeger Deployment Guide](https://www.jaegertracing.io/docs/next/deployment/)
* [Jaeger v2 Configuration Schema](https://github.com/jaegertracing/jaeger/tree/main/cmd/jaeger/config-schema.json)
