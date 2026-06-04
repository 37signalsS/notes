# OpenTelemetry: Обзор

## Определения

**OpenTelemetry (OTel)** — это открытый, независимый от поставщика стандарт и набор инструментов для сбора, обработки и экспорта телеметрических данных. Проект является частью [Cloud Native Computing Foundation (CNCF)](https://www.cncf.io/).

Цель OTel — унифицировать инструментирование облачных приложений для обеспечения наблюдаемости (observability). Он возник в результате слияния проектов **OpenTracing** и **OpenCensus** в 2019 году.

Телеметрия в OpenTelemetry основана на стандартизированных **сигналах** — подробная модель данных, атрибуты и корреляция описаны в разделе **[Сигналы](./architecture_signals.md)**.

## Основные концепции

Архитектура OpenTelemetry состоит из нескольких ключевых, взаимосвязанных компонентов:

- **[API и SDK](./instrumentation_sdk.md):** Набор библиотек для инструментирования кода. **API** предоставляет интерфейсы для генерации телеметрии, а **SDK** — их конкретную реализацию, управляющую сэмплированием, обработкой и экспортом данных.
- **[Протокол OTLP](./otlp_protocol.md):** Унифицированный протокол для передачи телеметрических данных. Он определяет единый формат для всех сигналов, что упрощает их передачу и приём.
- **Collector:** Центральный компонент, который действует как конвейер для телеметрических данных.
  - **Архитектура:** Collector состоит из:
    - **Receivers (Приемники):** Принимают данные в различных форматах (OTLP, Jaeger, Prometheus, Zipkin).
    - **Processors (Обработчики):** Обрабатывают данные на лету (фильтрация, обогащение, сэмплирование, группировка).
    - **Exporters (Экспортеры):** Отправляют обработанные данные в бэкенды (OTLP, Jaeger, Loki, Prometheus).
  - **Режимы развёртывания:**
    - **Agent (Агент):** Работает локально рядом с приложением (например, как DaemonSet в Kubernetes). Снижает нагрузку на приложение и упрощает конфигурацию.
    - **Gateway (Шлюз):** Отдельный кластер Collector'ов, агрегирующий телеметрию. Позволяет централизованно управлять маршрутизацией и нагрузкой на бэкенд.
  - **Дистрибутивы:**
    - **Core (`otel/opentelemetry-collector`):** Минимальный дистрибутив со стабильными компонентами. Рекомендуется для production.
    - **Contrib (`otel/opentelemetry-collector-contrib`):** Расширенный дистрибутив с экспериментальными и специализированными компонентами.

## Практические сценарии

### Сценарий: Миграция с Jaeger на OpenSearch Observability

Этот сценарий демонстрирует использование OpenTelemetry для интеграции приложений с бэкендом, требующим OTLP, например, **OpenSearch Observability**.

**Проблема:** Приложения инструментированы для Jaeger, но OpenSearch требует OTLP и использует [**Data Prepper**](../ELK_Stack/OpenSearch/opensearch_overview.md).

**Решение:** Развернуть **OTLP Collector** как замену Jaeger Agent/Collector.

**Архитектура:**
`Приложение -> OTLP Collector -> Data Prepper -> OpenSearch`

1. **OTLP Collector** разворачивается как `DaemonSet` в Kubernetes.
2. **Конфигурация Collector:**
    - **Receiver:** Принимает данные в формате `jaeger`.
    - **Exporter:** Отправляет данные в формате `otlp` на эндпоинт `Data Prepper`.

#### Трудности и решения

- **Несовместимость полей:** Если `Data Prepper` отбрасывает спаны из-за отсутствия обязательных полей (например, `name` событий), рекомендуется переконфигурировать приложение для отправки данных в **нативном формате OTLP**.
- **Конфигурация эндпоинта:** Вместо прямого обращения на `hostIP`, используйте Kubernetes `Service` для OTLP Collector. Это упрощает конфигурацию, хотя и добавляет сетевой хоп.

### Сценарий: Прямая отправка трейсов в Jaeger Agent в Kubernetes

Метод минимизации сетевых задержек за счёт отправки UDP-пакетов напрямую на Jaeger Agent, работающий на том же узле.

**Архитектура:**
`Приложение (Pod) -> Jaeger Agent (DaemonSet на том же Node)`

**Решение:** Использование **Downward API** для передачи `hostIP` в под приложения.

```yaml
# В манифесте Deployment приложения
spec:
  template:
    spec:
      containers:
      - name: my-python-app
        env:
        - name: OTEL_TRACES_EXPORTER
          value: "jaeger"
        - name: OTEL_EXPORTER_JAEGER_AGENT_HOST
          valueFrom:
            fieldRef:
              fieldPath: status.hostIP
        - name: OTEL_EXPORTER_JAEGER_AGENT_PORT
          value: "6831"
```

### Корреляция запросов к базе данных

Для сквозной трассировки в БД используется механизм **SQLCommenter**. Он добавляет к SQL-запросам комментарий с контекстом трассировки.

```sql
-- Запрос с контекстом трассировки
SELECT * FROM users WHERE id = 1 /*traceparent='00-abc...-def...-01'*/;
```

Это позволяет инструментам (например, `pg_tracing` в PostgreSQL) связывать выполнение запроса в БД с конкретным спаном приложения.

## Дополнительная информация

### Интеграция с бэкендами

- **Стек Grafana Labs:** [Loki](../Loki/loki_overview.md), [Tempo](../Tempo/index.md), [Mimir](../Mimir/mimir_overview.md) и [Grafana](../Grafana/grafana_overview.md). Используется [Grafana Alloy](../Grafana/grafana_alloy_overview.md).
- **Стек ELK/OpenSearch:** [Elasticsearch](../ELK_Stack/Elasticsearch/elasticsearch_overview.md) / [OpenSearch](../ELK_Stack/OpenSearch/opensearch_overview.md).
- **Jaeger:** [Jaeger v2](../Jaeger/jaeger_overview.md) (построен на OTel Collector).

### Альтернативы OTel Collector

| Агент | Основан на | Язык конфигурации | Фокус |
|-------|------------|-------------------|-------|
| **OTel Collector** | — | YAML | Универсальный |
| **Grafana Alloy** | OTel Collector | River (HCL) | Экосистема Grafana |
| **Fluent Bit** | — | Lua / YAML | Логи, легковесный |

## Смотрите также

- [Архитектура и Сигналы](./architecture_signals.md)
- [Инструментация и SDK](./instrumentation_sdk.md)
- [Протокол OTLP](./otlp_protocol.md)
