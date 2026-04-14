# Экспортеры Prometheus: Обзор

## Определения

**Экспортер (Exporter)** — программа, собирающая метрики из сторонней системы и преобразующая их в формат Prometheus. Экспортеры действуют как «переводчики» между Prometheus и monitored системой.

**Процесс экспозиции (Exposition)** — процесс предоставления данных для Prometheus. Prometheus собирает данные по HTTP в формате plain text с кодировкой UTF-8 (единственный способ с версии 0.4.0, ранее был доступен Protobuf).

## Базовые концепции

### Принцип работы экспортера

1. Экспортер запрашивает данные у целевой системы (например, базы данных или операционной системы).
2. Преобразует полученные данные в текстовый формат метрик Prometheus.
3. Открывает HTTP-эндпоинт (обычно `/metrics`), по которому Prometheus забирает (scrape) метрики.

Экспортер не хранит метрики и не знает о существовании Prometheus — постоянно парсит данные и отдаёт их по запросу. Частота сбора настраивается в [конфигурации Prometheus](../configuration.md) (`scrape_interval`).

### Формат данных

Формат экспозиции Prometheus: plain text, UTF-8, HTTP. Подробности — в [типы метрик](../concepts/metric_types/overview.md).

Основные элементы:

- Комментарии обозначаются `#`
- `# HELP <metric_name> <description>` — описание метрики
- `# TYPE <metric_name> <type>` — [тип метрики](../concepts/metric_types/overview.md) (`counter`, `gauge`, `histogram`, `summary`), объявляется до первого использования
- Формат метрики: `metric_name{label_name="label_value"} value timestamp` (timestamp опционален)

### Источники метрик для Prometheus

1. **Exporters** — сторонние приложения, собирающие метрики из существующих источников (Nginx, PostgreSQL, ОС Linux).
2. **Клиентские библиотеки** — написание кастомных экспортеров с использованием готовых библиотек для большинства языков.
3. **Прямая инструментация** — встраивание экспозиции метрик в код приложения через клиентские библиотеки.

### Нативная инструментация

Предпочтительный подход — когда приложение **само отдаёт метрики** в формате Prometheus без отдельного экспортера (**native instrumentation**).

**Преимущества:**

- **Надёжность и точность:** метрики генерируются непосредственно из кода
- **Детализация бизнес-логики:** уникальные метрики, недоступные извне
- **Упрощение архитектуры:** не нужно обслуживать дополнительный компонент

**Опасность чрезмерной инструментации:** не следует превращать мониторинг в трассировку, создавая метрики с высокой [кардинальностью](../concepts/labels_and_cardinality.md) (например, с `request_id` в лейблах). Это ведёт к разрастанию TSDB и деградации производительности. Для отслеживания отдельных запросов существуют системы трассировки ([Jaeger](../../Jaeger/jaeger_overview.md), [OpenTelemetry](../../OpenTelemetry/opentelemetry_overview.md)).

### Высокая доступность экспортеров

Экспортеры — легковесные **stateless** приложения. Запуск нескольких реплик считается избыточным.

Применяемые стратегии:

- **Алертинг на недоступность таргета:** метрика `up` становится `0` для недоступного таргета. Настройка алерта `up == 0` — обязательная практика. Подробнее: [Alertmanager](../alertmanager.md), [Правила оповещений](../rules.md).
- **Использование параллельных систем:** для расследования инцидентов во время недоступности экспортера используются логирование (ELK, Loki) или другие утилиты мониторинга ([atop](../../Linux/Diagnostics/Performance/atop.md)).

## Практические сценарии

### Whitebox vs Blackbox мониторинг

**Whitebox (белый ящик):** мониторинг внутренних метрик системы — приложение инструментируется и само отдаёт метрики (основной подход для Prometheus).

**Blackbox (черный ящик):** мониторинг внешнего поведения сервиса (доступность HTTP-эндпоинта, валидность SSL-сертификата). Реализуется через [Blackbox Exporter](./blackbox/blackbox_exporter_overview.md).

Подробнее: [Whitebox vs Blackbox в Blackbox Exporter](./blackbox/blackbox_exporter_overview.md#whitebox-vs-blackbox-мониторинг).

### Выбор экспортера для задачи

| Задача | Экспортер | Ссылка |
| :--- | :--- | :--- |
| Мониторинг Linux-хоста (CPU, память, диск, сеть) | [node_exporter](./node_exporter.md) | [Установка](../installation/node_exporter_installation.md) |
| Мониторинг контейнеров Docker | [cAdvisor](./cadvisor.md) | — |
| Проверка доступности HTTP/TCP/DNS/ICMP | [blackbox_exporter](./blackbox/blackbox_exporter_overview.md) | [Установка](../installation/Blackbox_Exporter/blackbox_exporter_installation.md) |
| Мониторинг MySQL | mysqld_exporter | [MySQL](../../Databases/MySQL/overview.md) |
| Мониторинг PostgreSQL | postgres_exporter | [PostgreSQL](../../Databases/PostgreSQL/overview.md) |
| Мониторинг Nginx | nginx-prometheus-exporter | — |
| Мониторинг RabbitMQ | rabbitmq_exporter | — |
| Мониторинг Kafka | kafka_exporter | [Kafka](../../Kafka/kafka_for_monitoring.md) |
| Кастомные метрики | [Textfile Collector](./extensibility/custom_exporters.md) / [Свой экспортер](./extensibility/custom_exporters.md) | — |

Полный каталог дополнительных экспортеров: [другие экспортеры](./other_exporters.md).

## Дополнительная информация

### Официальные и поддерживаемые сообществом экспортеры

Полный список: [official exporters](https://prometheus.io/docs/instrumenting/exporters/), [community exporters](https://prometheus.io/docs/instrumenting/exporters/#community-exporters).

### Расширяемость

Механизм для сбора произвольных метрик через внешние скрипты: [Textfile Collector](./extensibility/custom_exporters.md). Руководство по созданию кастомных экспортеров на Go: [написание своих экспортеров](./extensibility/custom_exporters.md).

### Связанные темы

[Service Discovery и Relabeling](../service_discovery_and_relabeling.md) — автоматическое обнаружение экспортеров. [Конфигурация Prometheus](../configuration.md) — настройка сбора метрик. [Типы метрик](../concepts/metric_types/overview.md) — counter, gauge, histogram, summary. [Лейблы и кардинальность](../concepts/labels_and_cardinality.md) — правильное использование лейблов. [Каталог других экспортеров](./other_exporters.md).
