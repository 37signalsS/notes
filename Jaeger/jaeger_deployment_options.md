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

---

## Базовые концепции

### Сравнение моделей развертывания

| Критерий | All-in-one | Production (Direct) | Streaming (Kafka) |
| :--- | :--- | :--- | :--- |
| **Назначение** | Локальная отладка, CI/CD, демо | Средняя нагрузка, стабильная БД | Высокая нагрузка (High Load), риск пиков |
| **Хранение** | In-memory / Badger | ClickHouse / Elasticsearch | ClickHouse / Elasticsearch |
| **Масштабирование** | Только вертикальное | Горизонтальное (Collector/Query) | Горизонтальное (Collector/Ingester/Query) |
| **Сложность** | Минимальная | Средняя | Высокая |

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

### Ресурсные рекомендации (на один инстанс v2)

| Роль | CPU | RAM | Примечание |
| :--- | :--- | :--- | :--- |
| **All-in-one** | 0.5 - 1 | 512MB - 2GB | Зависит от объема данных в Badger |
| **Collector** | 1 - 4 | 1GB - 4GB | Зависит от количества OTLP-соединений и размера батчей |
| **Ingester** | 1 - 2 | 1GB - 2GB | Зависит от пропускной способности Kafka |
| **Query** | 0.5 - 2 | 512MB - 2GB | Зависит от сложности аналитических запросов и числа пользователей |

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
      - "16686:16686" # UI
      - "4317:4317"   # OTLP gRPC
      - "4318:4318"   # OTLP HTTP
    environment:
      - SPAN_STORAGE_TYPE=memory
      - METRICS_STORAGE_TYPE=prometheus
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

### Сценарий 3: Безопасность и аутентификация (TLS + OIDC)

В Jaeger v2 поддержка TLS и аутентификации встроена на уровне OTel-компонентов.

1.  **TLS для OTLP:** Настройка `certificates` в разделе `receivers.otlp.protocols.grpc.tls`.
2.  **Auth для Query/UI:** Использование расширения `bearertokenauth` или внешнего Proxy (например, OAuth2 Proxy) перед портом 16686.

---

## Дополнительная информация

### Миграция с v1 на v2

1.  **Замена бинарников:** Перейдите на единый образ `jaegertracing/jaeger:2.x`.
2.  **Обновление конфигов:** Флаги командной строки v1 (`--storage.type`) заменяются на YAML-конфигурацию OpenTelemetry.
3.  **Переход на OTLP:** Рекомендуется перевести приложения с Jaeger SDK на OpenTelemetry SDK для использования портов 4317/4318.

**Смежные темы:**

* Детальная архитектура компонентов: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Специфика работы в Kubernetes: **[Интеграция с Kubernetes](./jaeger_kubernetes_integration.md)**
* Анализ производительности и Tail-sampling: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**
* Стандарты и протоколы: **[OpenTelemetry Overview](../OpenTelemetry/opentelemetry_overview.md)**

### См. также
* [Official Jaeger Deployment Guide](https://www.jaegertracing.io/docs/next/deployment/)
* [Jaeger v2 Configuration Schema](https://github.com/jaegertracing/jaeger/tree/main/cmd/jaeger/config-schema.json)
