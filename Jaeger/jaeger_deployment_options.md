# Варианты развертывания Jaeger

> **Важно:** Документация описывает **Jaeger v2**. Jaeger v1 достиг **EOL (End of Life)**.

Jaeger v2 радикально упрощает процесс развертывания за счет перехода на архитектуру единого бинарного файла. В зависимости от масштаба системы и требований к надежности, Jaeger может быть запущен как в упрощенном режиме "все-в-одном", так и в виде распределенной масштабируемой системы с разделением ролей.

Общий обзор системы: **[Обзор Jaeger](./jaeger_overview.md)**.
Детальное описание ролей и портов: **[Архитектура Jaeger](./jaeger_architecture.md)**.

---

## Определения

| Вариант | Описание | Основные характеристики |
| :--- | :--- | :--- |
| **All-in-one** | Запуск всех компонентов (Collector, Query, UI) в одном процессе | Идеально для локальной разработки. Использует In-memory или Badger хранилище |
| **Production (Распределенный)** | Развертывание компонентов как независимых, горизонтально масштабируемых сервисов | Использует внешние отказоустойчивые БД (ClickHouse, Elasticsearch). Подходит для высоких нагрузок |
| **Streaming (Асинхронный)** | Архитектура с использованием Kafka для буферизации данных перед записью в хранилище | Обеспечивает максимальную устойчивость к пиковым нагрузкам и сбоям БД |
| **Unified Binary** | Концепция v2, при которой один бинарный файл `jaeger` выполняет разные функции в зависимости от конфигурации | Позволяет гибко менять роль узла без смены Docker-образа |
| **Agent Mode** | Режим работы OTel Collector как локального edge-агента, заменяющий Jaeger Agent v1 | Выполняет батчинг, обогащение метаданными и пересылку в центральный коллектор |

---

## Базовые концепции

### Сравнение моделей развертывания

| Критерий | All-in-one | Production (Direct) | Streaming (Kafka) |
| :--- | :--- | :--- | :--- |
| **Назначение** | Локальная отладка, CI/CD, демо | Средняя нагрузка, стабильная БД | Высокая нагрузка (High Load), риск пиков |
| **Хранение** | In-memory / Badger | ClickHouse / Elasticsearch | ClickHouse / Elasticsearch |
| **Масштабирование** | Только вертикальное | Горизонтальное (Collector/Query) | Горизонтальное (Collector/Ingester/Query) |
| **Сложность** | Минимальная | Средняя | Высокая |

### Паттерны развертывания коллектора

В Kubernetes и оркестраторах выбор паттерна развертывания коллектора определяет баланс между потреблением ресурсов и сетевой сложностью:

| Паттерн | Описание | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Sidecar** | Collector запускается как второй контейнер в каждом поде приложения | Прямая связь по localhost. Индивидуальная настройка для каждого сервиса | Оверхед по ресурсам на каждый инстанс приложения |
| **DaemonSet** | Один экземпляр Collector на каждом узле кластера | Оптимальное использование ресурсов узла. Удобно для сбора системных метрик | Требует настройки `hostPort` и корректной передачи IP узла из приложений |
| **Deployment** | Централизованный кластер коллекторов за Service | Удобство масштабирования (HPA). Централизованное управление политиками сэмплирования | Дополнительный сетевой переход (Extra Hop), требующий учета задержек |

### Выбор стратегии развертывания

**Используйте All-in-one**, если:
* Вам нужно быстро проверить инструментирование приложения.
* Данные не требуют сохранения после перезапуска контейнера (например, в CI).
* Ресурсы ограничены (минимум 512MB RAM).

**Переходите к Production-модели**, если:
* Требуется хранение истории трасс более 24 часов.
* Количество спанов превышает 10,000 в секунду.
* Необходима интеграция с корпоративными системами аутентификации (OIDC).
* Вы используете **Adaptive Sampling** для управления затратами на хранение.

**Используйте Streaming-архитектуру (Kafka)**, если:
* Нагрузка подвержена резким пикам (например, распродажи, Black Friday).
* Доступность данных важнее, чем актуальность (допустима задержка 1–5 секунд).
* Требуется максимальная отказоустойчивость: при падении ClickHouse спаны накапливаются в Kafka и записываются после восстановления БД.

### Ресурсные рекомендации (на один инстанс v2)

| Роль | CPU | RAM | Примечание |
| :--- | :--- | :--- | :--- |
| **All-in-one** | 0.5 - 1 | 512MB - 2GB | Зависит от объема данных в Badger |
| **Collector** | 1 - 4 | 1GB - 4GB | Зависит от количества OTLP-соединений и размера батчей |
| **Ingester** | 1 - 2 | 1GB - 2GB | Зависит от пропускной способности Kafka |
| **Query** | 0.5 - 2 | 512MB - 2GB | Зависит от сложности аналитических запросов и числа пользователей |

---

## Подготовка окружения

### Минимальные требования для запуска All-in-one

- CPU: 0.5 - 1 ядро
- RAM: 512MB - 2GB
- Docker Engine 20.10+ или Kubernetes 1.24+

### Требования для Production с ClickHouse

- CPU: 2 - 4 ядра на инстанс Collector
- RAM: 2GB - 4GB на инстанс Collector
- ClickHouse кластер: минимум 3 узла для HA

### Сетевые порты (входящие)

- 4317/tcp — OTLP gRPC
- 4318/tcp — OTLP HTTP
- 16686/tcp — UI и Query API
- 8888/tcp — Метрики самого Jaeger (Prometheus format)

### Проверка окружения

```bash
# Проверка версии Docker
docker --version
# → Docker version 24.0.7, build afdd53b

# Проверка доступности портов
nc -zv localhost 4317
# → Connection to localhost 4317 port [tcp/*] succeeded!

# Проверка ресурсов
docker info | grep -E "CPUs|Total Memory"
# → CPUs: 4
# → Total Memory: 15.94GiB
```

---

## Практические сценарии

### Сценарий 1: Локальный запуск через Docker Compose (v2 OTLP-native)

Современный способ запуска Jaeger v2 для разработки с использованием нативного OTLP и UI.

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

1. Запустить окружение: `docker compose up -d`.
2. Отправить тестовый спан из приложения на `localhost:4317` (gRPC) или `localhost:4318` (HTTP).
3. Открыть `http://localhost:16686` и убедиться, что сервис отображается в выпадающем списке.
4. Выполнить поиск по `service=имя-сервиса` и проверить, что спан содержит корректные атрибуты (`http.method`, `http.status_code`).

**Ожидаемый результат:** Трасса появляется в UI в течение 1–2 секунд после отправки. При использовании in-memory хранилища данные исчезают после перезапуска контейнера.

```bash
# Проверка статуса контейнера
docker compose ps
# → jaeger   Running   0.0.0.0:16686->16686/tcp, ...

# Проверка метрик
curl -s http://localhost:8888/metrics | grep otelcol_receiver_accepted_spans
# → otelcol_receiver_accepted_spans{...} 42
```

### Сценарий 2: Production развертывание с ClickHouse

Jaeger v2 рекомендует ClickHouse как наиболее эффективное хранилище. Пример фрагмента конфигурации коллектора:

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

1. Применить конфигурацию: `jaeger --config collector-config.yaml`.
2. Отправить тестовый спан и убедиться, что он появился в UI через `http://localhost:16686`.
3. Проверить метрики: `curl http://localhost:8888/metrics | grep jaeger_exporter_send_spans` — количество отправленных спанов должно расти.
4. Проверить таблицы в ClickHouse: `SELECT count() FROM jaeger_v2.spans` — количество записей должно совпадать с отправленными спанами.

### Сценарий 3: Streaming-архитектура с Kafka и Ingester

Использование Kafka для буферизации данных между Collector и хранилищем. Это отделяет SLA приема данных от скорости записи в БД и защищает от потерь при сбоях ClickHouse.

```yaml
# collector-config.yaml (Producer)
receivers:
  otlp:
    protocols:
      grpc:
      http:

exporters:
  kafka:
    brokers: ["kafka:9092"]
    topic: jaeger-spans
    protocol_version: "2.0.0"

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [kafka]
```

```yaml
# ingester-config.yaml (Consumer)
receivers:
  kafka:
    brokers: ["kafka:9092"]
    topic: jaeger-spans
    protocol_version: "2.0.0"

processors:
  batch:

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
      receivers: [kafka]
      processors: [batch]
      exporters: [jaeger_storage_exporter]
```

**Валидация:**

1. Запустить Kafka и создать топик `jaeger-spans` с необходимым чисством партиций (рекомендуется 6–12 для высоконагруженных сред).
2. Запустить Collector с конфигурацией producer: `jaeger --config collector-config.yaml`.
3. Запустить Ingester: `jaeger --config ingester-config.yaml`.
4. Отправить тестовый спан и убедиться, что он появился в ClickHouse.
5. Проверить, что Ingester потребляет сообщения: `curl http://localhost:8888/metrics | grep kafka_received_messages`.

```bash
# Проверка сообщений в Kafka
kafka-console-consumer --topic jaeger-spans --from-beginning --max-messages 1 --bootstrap-server kafka:9092
# → {"trace_id":"...","span_id":"...",...}
```

### Сценарий 4: Безопасность и аутентификация (TLS + OIDC)

В Jaeger v2 поддержка TLS и аутентификации встроена на уровне OTel-компонентов.

```yaml
# collector-config.yaml с TLS
receivers:
  otlp:
    protocols:
      grpc:
        tls:
          cert_file: /etc/jaeger/certs/server.crt
          key_file: /etc/jaeger/certs/server.key
      http:
        tls:
          cert_file: /etc/jaeger/certs/server.crt
          key_file: /etc/jaeger/certs/server.key
```

**Auth для Query/UI:** Использование расширения `bearertokenauth` или внешнего Proxy (например, OAuth2 Proxy) перед портом 16686.

```yaml
extensions:
  bearertokenauth:
    BearerTokens:
      - "your-secure-token-here"
```

**Валидация:**

1. Проверить TLS-подключение: `openssl s_client -connect localhost:4317 -servername localhost`.
2. Проверить, что подключение без TLS отклоняется: `grpcurl -insecure localhost:4317 list` должно возвращать ошибку.
3. Для OIDC: убедиться, что редиректы ведуят на корректный issuer и токены валидируются.

### Сценарий 5: Настройка роли Query с UI

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

1. Запустить Query: `jaeger --config query-config.yaml`.
2. Открыть UI: `http://localhost:16686`.
3. Выполнить поиск по сервису и убедиться, что UI загружает данные из Elasticsearch.

### Сценарий 6: Развертывание через Helm (Kubernetes)

Для Kubernetes рекомендуется использовать официальные Helm-чарты или OpenTelemetry Operator. Пример установки через Helm:

```bash
helm repo add jaegertracing https://jaegertracing.github.io/helm-charts
helm repo update

# Установка в режиме Production
helm install jaeger jaegertracing/jaeger \
  --namespace observability --create-namespace \
  --set collector.replicas=3 \
  --set query.replicas=2 \
  --set storage.type=clickhouse \
  --set storage.clickhouse.endpoint=http://clickhouse:8123
```

**Валидация:**

1. Проверить поды: `kubectl get pods -n observability -l app.kubernetes.io/name=jaeger`.
2. Открыть порт-forward: `kubectl port-forward -n observability svc/jaeger-query 16686:16686`.
3. Перейти в UI и убедиться, что сервисы регистрируются.

---

## Типичные проблемы и устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Разорванные трейсы** | Отсутствие передачи заголовков `traceparent` в одном из узлов | Проверить наличие Propagators в SDK всех сервисов. Проверить конфигурацию Ingress/Proxy (должны пропускать заголовки) |
| **Clock Skew (Сдвиг времени)** | Рассинхронизация NTP на разных серверах | Спаны могут отображаться в будущем или иметь отрицательную длительность. Требуется синхронизация через `chrony` или `systemd-timesyncd` |
| **Высокая нагрузка на сеть** | Слишком большой объем атрибутов или отсутствие сжатия | Использовать OTLP/Arrow. Ограничить размер атрибутов (не писать полные тела запросов/ответов в теги) |
| **Missing Spans (Пропуски)** | Переполнение буфера (Backpressure) | Увеличить `send_batch_size` в коллекторе, проверить метрики `spans_dropped_total` и доступность Kafka/хранилища |
| **Дублирование спанов** | Несколько инстансов Collector отправляют данные в одно хранилище без идемпотентности | Включить дедупликацию на уровне хранилища или использовать Kafka с ключом `trace_id` |
| **Медленный поиск в UI** | Отсутствие индексов при росте объема данных в ClickHouse/Elasticsearch | Настроить TTL на старые трейсы, добавить индексы по часто используемым тегам (`service_name`, `operation_name`) |
| **Collector падает с OOM** | Отсутствует `memory_limiter` processor при высокой нагрузке | Добавить `memory_limiter` с `limit_mib: 512` и `check_interval: 1s` в начало пайплайна |
| **Ingester не потребляет сообщения** | Неверный `topic` или Consumer Group конфликт | Проверить `kafka-consumer-groups.sh --describe --group jaeger-ingester` и логи Ingester |
| **Данные не сохраняются в ClickHouse** | Неверный `endpoint` или база данных не существует | Проверить подключение: `clickhouse-client --host clickhouse-server --query "SHOW DATABASES"` |
| **UI показывает пустой список сервисов** | Query extension не настроен или хранилище пустое | Проверить конфигурацию `jaeger_storage` и наличие данных в БД |

---

## Лучшие практики и очистка

### Лучшие практики

- **OTLP повсеместно:** Используйте порты 4317/4318 как единственные точки входа для трейсов. Отключите устаревшие протоколы (Thrift, Zipkin) в production.
- **Memory Limiter:** Всегда добавляйте `memory_limiter` processor в начале пайплайна для защиты от OOM при всплесках.
- **Batch Processing:** Настройте `batch` processor с параметрами, соответствующими вашей нагрузке (`send_batch_size: 1024`, `timeout: 10s`).
- **Мониторинг Collector:** Экспортируйте метрики на порт 8888 и настройте алерты на `otelcol_receiver_refused_spans` и `otelcol_exporter_send_failed_spans`.
- **ClickHouse TTL:** Настройте TTL на уровне таблицы для автоматического удаления старых трейсов (`TTL createdAt + INTERVAL 7 DAY`).
- **Семантические конвенции:** Используйте стандартные атрибуты OpenTelemetry (`http.method`, `db.system`) для корректной работы UI и поиска.
- **Kafka partitions:** При использовании streaming-архитектуры настройте минимум 6 партиций для топика `jaeger-spans`, чтобы обеспечить параллельную обработку.
- **Мониторинг самого Jaeger:** Настройте алерты на метрики `jaeger_processor_spans_success_total` (прием данных) и `jaeger_span_store_write_errors_total` (ошибки записи). Отсутствие спанов в хранилище часто является результатом падения экспортера, а не проблем в инструментации приложений.

### Очистка окружения

```bash
# Остановка Docker Compose окружения
docker compose down -v

# Удаление данных ClickHouse (если использовался Docker)
docker volume rm jaeger_clickhouse_data

# Очистка in-memory данных (перезапуск контейнера)
docker restart jaeger

# Удаление тестовых ресурсов Kubernetes
kubectl delete namespace jaeger-test
```

---

## Дополнительная информация

**Смежные темы:**

* Детальное описание компонентов и потоков данных: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Методы локального и production запуска: **[Варианты развертывания](./jaeger_deployment_options.md)**
* Использование Operator и Helm: **[Интеграция с Kubernetes](./jaeger_kubernetes_integration.md)**
* Глубокая диагностика и Query API: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**
* Query API Reference: **[Query API Jaeger](./jaeger_query_api.md)**
* Миграция с v1 на v2: **[Миграция Jaeger v1 → v2](./jaeger_migration_v1_to_v2.md)**
* Capacity Planning: **[Capacity Planning для Jaeger](./jaeger_capacity_planning.md)**
* Хранилища и бэкенды: **[Storage Deep Dive](./jaeger_storage_deep_dive.md)**
* HA и Disaster Recovery: **[High Availability и DR](./jaeger_high_availability.md)**
* Интеграция с Grafana: **[Интеграция Jaeger с Grafana](./jaeger_grafana_integration.md)**
* Service Mesh Integration: **[Интеграция Jaeger с Service Mesh](./jaeger_service_mesh_integration.md)**
* OTLP Configuration: **[OTLP Configuration для Jaeger](./jaeger_otlp_configuration.md)**
* eBPF и Auto-instrumentation: **[eBPF и автоматическая инструментация](./jaeger_ebpf_auto_instrumentation.md)**
* Multi-tenancy: **[Multi-tenancy и изоляция](./jaeger_multi_tenancy.md)**
* Security Hardening: **[Security Hardening для Jaeger](./jaeger_security_hardening.md)**
* Общий обзор системы: **[Обзор Jaeger](./jaeger_overview.md)**
* Стандарт сбора телеметрии: **[OpenTelemetry Overview](../OpenTelemetry/opentelemetry_overview.md)**

### См. также
* [Official Jaeger Deployment Guide](https://www.jaegertracing.io/docs/next/deployment/)
* [Jaeger v2 Configuration Schema](https://github.com/jaegertracing/jaeger/tree/main/cmd/jaeger/config-schema.json)
