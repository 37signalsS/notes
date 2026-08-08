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

---

## Базовые концепции

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

### Хранилище и расширение Storage

Jaeger v2 использует механизм расширений (**Extensions**) для интеграции с базами данных. Это позволяет:
*   Использовать единый пул соединений для всех пайплайнов.
*   Поддерживать специфичные для Jaeger индексы и оптимизации.
*   **ClickHouse:** В v2 стал первоклассным гражданином (first-class citizen). Архитектура ClickHouse позволяет хранить миллиарды спанов с минимальными затратами на ресурсы по сравнению с Elasticsearch.

### Адаптивное сэмплирование (Adaptive Sampling)

В v2 адаптивное сэмплирование реализовано через `sampling` extension.
1.  Коллектор анализирует входящий поток данных по каждому сервису и операции.
2.  На основе целевого RPS (например, 10 трейсов в секунду на сервис) рассчитывается вероятность сэмплирования.
3.  Вероятности отдаются SDK приложений через расширение (бинарный файл Jaeger выступает в роли сервера стратегий).

---

## Практические сценарии

### Настройка роли Ingester (Kafka -> ClickHouse)

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

### Настройка роли Query с UI

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

---

## Дополнительная информация

**Смежные темы:**

* Варианты развертывания: **[Варианты развертывания](./jaeger_deployment_options.md)**
* Интеграция с Kubernetes: **[Интеграция с Kubernetes](./jaeger_kubernetes_integration.md)**
* Анализ производительности: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**
* Общий обзор системы: **[Обзор Jaeger](./jaeger_overview.md)**
* Стандарт OTLP: **[OTLP Protocol](../OpenTelemetry/otlp_protocol.md)**

---

## Дополнительная информация

**Смежные темы:**

* Варианты развертывания: **[Варианты развертывания](./jaeger_deployment_options.md)**
* Интеграция с Kubernetes: **[Интеграция с Kubernetes](./jaeger_kubernetes_integration.md)**
* Анализ производительности: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**
