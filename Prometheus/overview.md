# Prometheus

## Definitions

**Prometheus** — система мониторинга и оповещения с открытым исходным кодом, стандарт де-факто в Cloud Native экосистеме. Разработан в SoundCloud (вдохновлён Borgmon от Google), передан в CNCF — второй по значимости проект после [Kubernetes](../Kubernetes/kubernetes_overview.md).

**Ключевые особенности:**

- Сбор **метрик** в виде **временных рядов**
- Язык запросов [PromQL](./concepts/promql/functions.md)
- Ограничения в долгосрочном хранении и масштабировании решаются через [Mimir](../Mimir/mimir_overview.md), Thanos, [VictoriaMetrics](../VictoriaMetrics/overview.md)

## Basic Concepts

### Философия

| Принцип | Описание |
|---|---|
| **Pull-модель** | Prometheus сам опрашивает (scrapes) HTTP-эндпоинты целей. Подробнее: [Стратегии сбора метрик](../Concepts/Observability_and_Monitoring/metrics_collection_strategies.md) |
| **Многомерная модель** | Временные ряды идентифицируются **именем метрики** + **лейблами** (labels). Пример: `http_requests_total{method="POST", path="/api"}`. См. [Лейблы и кардинальность](./concepts/labels_and_cardinality.md) |
| **Service Discovery** | Автообнаружение целей (Kubernetes, Consul и др.). См. [Service Discovery и Relabeling](./service_discovery_and_relabeling.md) |
| **PromQL** | Специализированный язык запросов для временных рядов |

### Scrape-модель

**Scrape** — периодический HTTP-запрос `GET /metrics` к целевому приложению.

**Принцип работы:**

| Шаг | Действие |
|---|---|
| 1 | Приложение отдаёт метрики по HTTP (`/metrics`) в [определённом формате](./concepts/metric_types/alerts.md) |
| 2 | Prometheus делает `GET /metrics` (интервал: 15–30с) |
| 3 | Ответ сохраняется в [TSDB](./concepts/tsdb.md) с timestamp |
| 4 | Метрики остаются в памяти приложения — дополняются и агрегируются |

Prometheus собирает **срез во времени**, изменения вычисляются через PromQL (`rate()`, `increase()`).

**Поведение счётчиков:**

| Правильно | Неправильно |
|---|---|
| Монотонно инкрементить | Сбрасывать после scrape |

Сброс — только при рестарте приложения.

**Альтернативные способы скрапинга** (для сервисов без HTTP, cronjob):

| Способ | Описание |
|---|---|
| HTTP-сервер | Накладные расходы приемлемы для долгоживущих процессов |
| [Pushgateway](./pushgateway.md) | Промежуточное приложение для batch/cron задач |
| Telegraf | Универсальный конвертер/агрегатор метрик |
| StatsD Exporter | Приём метрик в формате statsd → экспорт для Prometheus |

### Архитектура

| Компонент | Роль | Ссылка |
|---|---|---|
| **Prometheus Server** | Сбор, хранение, PromQL, правила | — |
| **Exporters** | Преобразование метрик сторонних систем | [Exporters](./Exporters/overview.md) |
| **Service Discovery** | Автообнаружение целей | [Service Discovery и Relabeling](./service_discovery_and_relabeling.md) |
| **Alertmanager** | Группировка, подавление, маршрутизация алертов | [Alertmanager](./alertmanager.md) |
| **Pushgateway** | Приём метрик от кратковременных задач | [Pushgateway](./pushgateway.md) |
| **Remote Storage** | Долгосрочное хранение (Mimir, Thanos, VM) | [Remote Read/Write](./scaling/remote_read_write.md) |

> Kubernetes: [kube-prometheus-stack](./kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios.md)

### Хранение данных: TSDB

| Этап | Описание |
|---|---|
| **Запись** | WAL (write-ahead log) → память |
| **Блоки** | Каждые 2ч — сброс из памяти на диск в виде блока |
| **Компакция** | Фоновое объединение старых блоков для оптимизации |
| **Retention** | Флаги `--storage.tsdb.retention.time` и `--storage.tsdb.retention.size` |

> Концепты: [Типы метрик](./concepts/metric_types/overview.md), [Лейблы и кардинальность](./concepts/labels_and_cardinality.md), [PromQL](./concepts/promql/functions.md), [TSDB](./concepts/tsdb.md), [Безопасность](./security.md)

## Практические сценарии

### Типовой жизненный цикл метрики

1. **Инструментация**: разработчик добавляет клиентскую библиотеку Prometheus в код приложения.
2. **Экспорт**: приложение запускает HTTP-сервер, отдающий метрики по `/metrics` в текстовом формате.
3. **Сбор (Scraping)**: Prometheus периодически опрашивает `/metrics` согласно [конфигурации](./configuration.md), сохраняет данные в TSDB.
4. **Анализ и визуализация**: запросы [PromQL](./concepts/promql/functions.md) в веб-интерфейсе Prometheus или [Grafana](../Grafana/grafana_overview.md).
5. **Оповещение**: Prometheus выполняет [правила](./rules.md). При срабатывании алерт отправляется в [Alertmanager](./alertmanager.md).

> **Whitebox vs Blackbox Monitoring** — описано в [Exporters Overview](./Exporters/overview.md#whitebox-vs-blackbox-мониторинг).

## Дополнительная информация

### Масштабирование и Федерация

Изначально Prometheus спроектирован как автономный сервер. Для масштабирования используются два основных подхода:

- **Федерация ([Federation](./scaling/federation.md))**: Иерархическая модель, где один сервер Prometheus опрашивает другие, агрегируя их данные. Используется для объединения данных из разных дата-центров или команд.
- **Удаленное хранилище ([Remote Read/Write](./scaling/remote_read_write.md))**: Локальные серверы Prometheus отправляют все собираемые метрики в единое, глобальное, долгосрочное хранилище (например, Mimir, Thanos, VictoriaMetrics). Это предпочтительный современный подход.

### Сравнение с Zabbix

| Характеристика | Prometheus | Zabbix |
|---|---|---|
| Архитектура | Распределённая, независимые компоненты | Монолитная (сервер + БД + UI) |
| Модель данных | Динамическая: имя метрики + лейблы | Статическая: элементы данных (Items), шаблоны, LLD |
| Модель сбора | Pull-модель (опрос) | Гибридная (Pull для пассивных, Push для активных агентов) |
| Хранение | Встроенная TSDB | Реляционная СУБД (MySQL/PostgreSQL + опционально TimescaleDB для гипертаблиц) |
| Язык запросов | PromQL (гибкий, мощный, на лету) | Привязан к настроенным Items и триггерам |
| Целевая среда | Динамичные облачные среды, микросервисы, Kubernetes | Относительно статичные инфраструктуры, серверы, сетевое оборудование |
| Настройка графиков | Через внешнюю систему (Grafana) на основе PromQL-запросов | Встроенная веб-панель (Dashboard, Maps) с привязкой к конкретным Items |

Подробно: [Observability & Monitoring](../Concepts/Observability_and_Monitoring/observability_definitions.md)
