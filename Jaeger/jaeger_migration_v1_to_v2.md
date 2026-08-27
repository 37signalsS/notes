# Миграция Jaeger с v1 на v2

> **Важно:** Документация описывает **Jaeger v2** (текущая версия). Jaeger v1 достиг **EOL (End of Life)** и больше не поддерживается.

**Миграция Jaeger v1 → v2** — это процесс перехода от архитектуры с отдельными бинарными файлами (Agent, Collector, Query, UI) к единому бинарному файлу на базе OpenTelemetry Collector. Миграция затрагивает конфигурацию, хранилище, порты, инструментацию приложений и процесс развертывания. В 2026 году большинство production-систем еще находятся на v1, поэтому понимание миграционного пути критично для SRE- и backend-инженеров.

Общий обзор архитектуры v2: **[Архитектура Jaeger](./jaeger_architecture.md)**.
Варианты развертывания: **[Варианты развертывания Jaeger](./jaeger_deployment_options.md)**.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **EOL (End of Life)** | Прекращение поддержки версии. Jaeger v1 достиг EOL,这意味着 безопасности и баг-фиксы больше не выпускаются |
| **Unified Binary** | Концепция v2: один бинарный файл `jaeger` выполняет все роли (Collector, Query, Ingester) в зависимости от конфигурации |
| **Storage Extension** | Механизм v2 для интеграции с бэкендами хранения через OTel Collector framework |
| **OTLP (OpenTelemetry Protocol)** | Единый протокол для приема трейсов в v2, заменяющий Thrift, gRPC и Zipkin форматы v1 |
| **Backward Compatibility** | Способность v2 работать со старыми агентами и портами v1 для плавной миграции |
| **Rolling Upgrade** | Стратегия обновления без остановки сервиса, приложения постепенно переходят на v2 |
| **Canary Migration** | Постепенный перевод части трафика на v2 с контролем метрик перед полным переходом |

---

## Базовые концепции

### Фундаментальные изменения в v2

| Аспект | Jaeger v1 | Jaeger v2 |
| :--- | :--- | :--- |
| **Архитектура** | Отдельные бинарники: Agent, Collector, Query, UI | Единый бинарный файл на базе OpenTelemetry Collector |
| **Протоколы** | Thrift, gRPC, Zipkin, Proto | Нативный OTLP (gRPC: 4317, HTTP: 4318) |
| **Конфигурация** | Флаги CLI, YAML-файлы специфичные для каждого компонента | Единый YAML-формат OpenTelemetry Collector |
| **Хранилище** | Собственные драйверы (ES, Cassandra, Badger) | Storage Extension с пулом соединений и retry-логикой |
| **Сэмплирование** | Централизованное управление через Agent | Adaptive Sampling extension, Tail-based sampling processor |
| **Развертывание** | Docker Compose, Helm charts v1, Operator v1 | OpenTelemetry Operator, Helm charts v2, Kubernetes-native CRDs |

### Совместимость портов

Jaeger v2 поддерживает устаревшие порты v1 для обратной совместимости во время миграции:

| Порт | Протокол | Назначение v1 | Статус в v2 |
| :--- | :--- | :--- | :--- |
| **4317** | gRPC | — | OTLP (основной порт) |
| **4318** | HTTP | — | OTLP HTTP |
| **14250** | gRPC | Collector (gRPC) | Обратная совместимость |
| **14268** | HTTP | Collector (Thrift HTTP) | Обратная совместимость |
| **9411** | HTTP | Zipkin | Обратная совместимость |
| **6831** | UDP | Agent (Thrift compact) | Обратная совместимость |
| **5778** | HTTP | Конфигурация Agent | Обратная совместимость |
| **16686** | HTTP | UI | Query/UI (основной порт) |

**Важно:** После завершения миграции отключите устаревшие порты в production для снижения поверхности атаки.

### Поддерживаемые пути миграции

Существует три основных стратегии миграции:

1.  **Flat Migration (Прямая):** Одновременный переход всех компонентов на v2. Подходит для сред с низкой нагрузкой или короткими окнами обслуживания.
2.  **Parallel Run (Параллельная работа):** v1 и v2 работают одновременно. Приложения постепенно переводятся на OTLP, пока v1 продолжает обслуживать старых клиентов.
3.  **Side-by-Side (Изоляция):** Отдельные окружения (staging → production) мигрируют независимо. Минимальный риск, но требует поддержки двух версий.

---

## Практические сценарии

### Сценарий 1: Подготовка к миграции

**Ситуация:** Перед миграцией необходимо проинвентаризировать текущую инфраструктуру и убедиться в готовности.

**Шаги:**

1.  **Инвентаризация v1:**
    ```bash
    # Проверка запущенных контейнеров v1
    docker ps | grep jaeger

    # Проверка портов
    netstat -tlnp | grep -E '14250|14268|6831|16686'

    # Проверка хранилища
    curl -s http://localhost:9200/_cluster/health  # Elasticsearch
    # или
    curl -s http://localhost:9000/  # ClickHouse
    ```

2.  **Проверка инструментации приложений:**
    ```bash
    # Перечень переменных окружения Jaeger SDK
    kubectl get pods -A -o jsonpath='{range .items[*]}{.spec.containers[*].env[*].name}{"\n"}{end}' | grep JAEGER

    # Проверка версий SDK
    kubectl get pods -A -o jsonpath='{range .items[*]}{.spec.containers[*].image}{"\n"}{end}' | grep -E 'java|python|nodejs'
    ```

3.  **Бэкап хранилища:**
    ```bash
    # Elasticsearch snapshot
    curl -X PUT "http://localhost:9200/_snapshot/backup/snapshot_1?wait_for_completion=true" -H 'Content-Type: application/json' -d'
    {
      "indices": "jaeger-*",
      "ignore_unavailable": true,
      "include_global_state": false
    }'

    # ClickHouse бэкап
    clickhouse-client --query "BACKUP TABLE jaeger_v2.spans TO 's3://backups/jaeger/$(date +%Y%m%d)'"
    ```

### Сценарий 2: Параллельный запуск v1 и v2

**Ситуация:** Нужно перевести приложения на OTLP без остановки текущей системы.

```yaml
# docker-compose.yml с параллельным запуском
services:
  # Jaeger v1 (существующая инфраструктура)
  jaeger-v1:
    image: jaegertracing/jaeger:1.50
    ports:
      - "14250:14250"
      - "16686:16686"
    environment:
      - SPAN_STORAGE_TYPE=elasticsearch
      - ES_SERVER_URLS=http://elasticsearch:9200

  # Jaeger v2 (новая инфраструктура)
  jaeger-v2:
    image: jaegertracing/jaeger:2.0
    ports:
      - "4317:4317"
      - "4318:4318"
      - "16687:16686"
    environment:
      - SPAN_STORAGE_TYPE=memory
```

**Миграция приложения по Canary:**

1.  Первое приложение переводится на OTLP exporter (OpenTelemetry SDK).
2.  Трафик направляется на v2 порт 4317.
3.  Мониторинг: сравнение количества спанов в v1 и v2.
4.  При стабильности — перевод следующего сервиса.

**Валидация:**

```bash
# Проверка спанов в v2
curl -s http://localhost:16687/api/services | jq .

# Проверка метрик
curl -s http://localhost:14269/metrics | grep otelcol_receiver_accepted_spans
```

### Сценарий 3: Полная миграция конфигурации

**Ситуация:** Необходимо перенести существующую конфигурацию v1 (флаги CLI, опции) в YAML-формат v2.

**v1 (флаги CLI):**
```bash
jaeger-collector --storage.type=cassandra --cassandra.keyspace=jaeger --log-level=debug --processor.jaeger-compact.server-host-port=0.0.0.0:6831
```

**v2 (YAML конфигурация):**
```yaml
# collector-config.yaml
receivers:
  otlp:
    protocols:
      grpc:
      http:

processors:
  batch:
  memory_limiter:
    check_interval: 1s
    limit_mib: 512

exporters:
  jaeger_storage:
    trace_storage:
      type: cassandra
      options:
        cassandra:
          servers: ["cassandra:9042"]
          keyspace: jaeger

service:
  extensions: [jaeger_storage]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [jaeger_storage]
```

**Запуск:**
```bash
jaeger --config collector-config.yaml
```

**Валидация:**

1.  Отправить тестовый спан на `localhost:4317`.
2.  Проверить запись в Cassandra: `SELECT count() FROM jaeger_v2.spans`.
3.  Проверить UI: `http://localhost:16686`.

### Сценарий 4: Миграция хранилища Elasticsearch

**Ситуация:** Хранилище Elasticsearch уже настроено для v1, нужно сохранить данные и перенаправить v2 на тот же кластер.

**Шаги:**

1.  **Проверка индексов v1:**
    ```bash
    curl -s http://localhost:9200/_cat/indices/jaeger-* | awk '{print $3}'
    ```

2.  **Настройка v2 на существующий Elasticsearch:**
    ```yaml
    extensions:
      jaeger_storage:
        trace_storage:
          type: elasticsearch
          options:
            elasticsearch:
              server-urls: ["http://elasticsearch:9200"]
              index: jaeger_v2
    ```

3.  **Постепенное перенаправление:**
    ```bash
    # Запуск v2 с новым индексом
    kubectl apply -f jaeger-v2-collector.yaml

    # Мониторинг записи в новый индекс
    curl -s http://localhost:9200/_cat/indices/jaeger_v2*
    ```

4.  **Валидация:**
    ```bash
    # Сравнение количества записей
    curl -s http://localhost:9200/jaeger-*/_count | jq '.count'
    curl -s http://localhost:9200/jaeger_v2*/_count | jq '.count'
    ```

### Сценарий 5: Отключение устаревших портов v1

**Ситуация:** После успешной миграции всех приложений на OTLP необходимо отключить порты обратной совместимости.

```yaml
# collector-config.yaml (production)
receivers:
  otlp:
    protocols:
      grpc:
      http:

# Устаревшие receivers удалены или закомментированы
# receivers:
#   jaeger_thrift:
#     protocols:
#       http:
#   zipkin:

exporters:
  jaeger_storage:
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
      processors: [batch]
      exporters: [jaeger_storage]
```

**Валидация:**

```bash
# Подключение к старым портам должно отклоняться
grpcurl -plaintext localhost 14250 list
# → Error: connection error

curl -v http://localhost:14268/api/traces
# → 404 Not Found
```

### Сценарий 6: Миграция Helm-релиза

**Ситуация:** Проект развернут через официальный Helm-чарт Jaeger v1, требуется обновление до v2.

```bash
# Добавление репозитория
helm repo add jaegertracing https://jaegertracing.github.io/helm-charts
helm repo update

# Установка v2 в отдельном неймспейсе для тестирования
helm install jaeger-v2 jaegertracing/jaeger \
  --namespace observability-v2 \
  --create-namespace \
  --set mode=production \
  --set storage.type=clickhouse \
  --set storage.clickhouse.endpoint=http://clickhouse:8123 \
  --set collector.replicas=3 \
  --set query.replicas=2
```

**Валидация:**

```bash
# Проверка подов
kubectl get pods -n observability-v2 -l app.kubernetes.io/name=jaeger

# Проверка логов
kubectl logs -n observability-v2 -l app.kubernetes.io/component=collector --tail=50

# Проброс порта и проверка UI
kubectl port-forward -n observability-v2 svc/jaeger-query 16686:16686
```

---

## Типичные проблемы и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Спаны не поступают после миграции** | Приложения все еще отправляют на порты v1 | Проверить переменные окружения `OTEL_EXPORTER_OTLP_ENDPOINT`, обновить конфигурацию SDK |
| **Дублирование спанов** | v1 и v2 одновременно принимают данные от одних и тех же приложений | Отключить v1 Collector или изменить endpoint в приложениях |
| **Потеря данных при миграции ES** | Несовместимость маппингов между индексами v1 и v2 | Использовать отдельный индекс для v2 (`jaeger_v2`) или реиндексировать данные |
| **Разорванные трейсы** | Часть сервисов на v1 (Thrift/B3), часть на v2 (OTLP/W3C) | Внедрить B3-to-W3C конвертер на уровне Ingress или Collector |
| **Ошибки TLS при подключении к ClickHouse** | В v2 изменился формат конфигурации TLS | Проверить блок `tls` в `trace_storage.options.clickhouse` |
| **Нет отображения в UI после миграции** | Query v2 смотрит в новый индекс/хранилище, а данные записаны в старое | Убедиться, что Collector и Query используют одинаковый `jaeger_storage` extension |

---

## Лучшие практики

1.  **Сохраняйте v1 в рабочем состоянии до финальной валидации v2:** Не удаляйте старые порты и данные до подтверждения корректной работы новой версии.
2.  **Используйте параллельный запуск:** Настройте v2 рядом с v1 и постепенно переводите сервисы через Canary.
3.  **Переходите на OTLP повсеместно:** Обновите SDK приложений на OpenTelemetry SDK и переменные окружения `OTEL_EXPORTER_OTLP_ENDPOINT`.
4.  **Фиксируйте версии образов:** Избегайте тегов `latest` в production. Используйте конкретные версии `jaegertracing/jaeger:2.0.0`.
5.  **Тестируйте хранилище перед миграцией:** Убедитесь, что ClickHouse/Elasticsearch v2 совместим с существующими данными или подготовьте миграцию индексов.
6.  **Мониторинг во время миграции:** Сравнивайте метрики `otelcol_receiver_accepted_spans` (v2) и `jaeger_agent_spans_sent` (v1) для контроля целостности потока данных.

---

## Очистка окружения

```bash
# Удаление временных неймспейсов v2 после миграции
kubectl delete namespace observability-v2

# Удаление старых ресурсов v1 (после подтверждения успешной миграции)
helm uninstall jaeger-v1 -n observability

# Очистка Docker-контейнеров
docker compose down -v
```

---

## Дополнительная информация

**Смежные темы:**

* Архитектура v2: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Развертывание в Kubernetes: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**
* Настройка Collector: **[Варианты развертывания Jaeger](./jaeger_deployment_options.md)**
* Протокол OTLP: **[Протокол OTLP](../OpenTelemetry/otlp_protocol.md)**

### См. также

* [Official Jaeger Migration Guide](https://www.jaegertracing.io/docs/latest/upgrading/)
* [OpenTelemetry Collector Configuration](https://opentelemetry.io/docs/collector/configuration/)
