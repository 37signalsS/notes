# Full-Stack Observability для PostgreSQL

## Определения

**Full-Stack Observability** — подход к наблюдаемости, объединяющий метрики, логи и трассировки PostgreSQL с данными приложения для сквозной диагностики проблем.

**Ключевые понятия:**

- **Наблюдаемость (Observability)** — способность системы отвечать на вопросы о внутреннем состоянии по внешним данным. Подробнее — **[Observability Definitions](../../../Concepts/Observability_and_Monitoring/observability_definitions.md)**.
- **4 столпа Observability** — логи, метрики, трассировки, профилирование. Детали — **[Four Pillars of Observability](../../../Concepts/Observability_and_Monitoring/four_pillars_of_observability.md)**.

## Основные концепции

### Проблема мониторинга PostgreSQL

Стандартные метрики (CPU, память) могут быть в норме, но система деградирует из-за неоптимальных запросов или блокировок. Для ответа на вопрос **"почему система тормозит?"** необходимо связать активность приложения с поведением внутри БД.

**Ключевая идея:** прокинуть сквозной `trace_id` от клиентского запроса через микросервисы до конкретного SQL-запроса.

### Ключевые области мониторинга

1. **Активные соединения:** Рост к лимиту `max_connections` — проблема в приложении или нехватка ресурсов. Решение — PgBouncer.
2. **Дисковый I/O:** Высокие IOPS — нехватка RAM (`shared_buffers`), неэффективные запросы (full scan) или медленные диски.
3. **Отставание репликации:** Критично для HA-кластеров. Рост lag увеличивает риск потери данных при failover.
4. **Блокировки:** Длительные блокировки таблиц — деградация всей системы.
5. **Резервные копии:** Возраст последнего успешного бэкапа.

## Практический сценарий: Архитектура стека

### Компоненты

1. **Приложение:** Инструментируется **OpenTelemetry SDK**. Добавляет SQL-комментарий `sqlcommenter` с `trace_id` к запросам.

2. **PostgreSQL:**
   - `trace_id` попадает в логи через `sqlcommenter`
   - Расширение **`pg_tracing`** создаёт спаны для фаз выполнения SQL
   - **`postgres_exporter`** собирает метрики из `pg_stat_*`

3. **Grafana Alloy (агент-коллектор):**
   - Принимает трейсы от приложения и `pg_tracing`
   - Собирает метрики с `postgres_exporter`
   - Читает логи, извлекает `trace_id`
   - Отправляет данные в бэкенды Grafana

4. **Бэкенд (Grafana Stack):**
   - **[Tempo](../../../Tempo/index.md)** — хранение трейсов
   - **[Loki](../../../Loki/loki_overview.md)** — хранение логов
   - **[Mimir](../../../Mimir/mimir_overview.md)** или Prometheus — хранение метрик

5. **Grafana:** Визуализация и корреляция сигналов.

### Настройка sqlcommenter

**sqlcommenter** — конвенция и библиотеки для добавления метаданных в SQL-комментарии:

```sql
-- Без sqlcommenter
SELECT * FROM users WHERE id = 1;

-- С sqlcommenter
SELECT * FROM users WHERE id = 1 /*application='backend',traceparent='00-traceid-spanid-01'*/;
```

**Библиотеки:** SQLAlchemy, GORM и другие ORM поддерживают автоматическое добавление комментариев. Примеры — **[OpenTelemetry Overview](../../../OpenTelemetry/opentelemetry_overview.md#практический-пример-инструментация-запросов-к-postgresql)**.

### Расширения для мониторинга

| Расширение | Назначение |
| :--- | :--- |
| `pg_stat_statements` | Агрегированные метрики по запросам |
| `pg_stat_monitor` | Продвинутая версия с планами запросов |
| `auto_explain` | Логирование планов медленных запросов |
| `pg_tracing` | Создание спанов для трассировки (экспериментальное) |

Подробнее об использовании — **[Оптимизация производительности](./performance_tuning.md#мониторинг-и-диагностика)**.

### pg_tracing (экспериментальное)

**Функционал:**

- Создаёт спаны для фаз выполнения (parsing, planning, execution)
- Читает `traceparent` из `sqlcommenter`
- Экспортирует спаны по протоколу OTLP

**Статус:** Экспериментальное, может требовать сборки PostgreSQL из исходников.

## Дополнительная информация

### Grafana Alloy

Alloy — агент-коллектор для сбора всех сигналов observability. Пример настройки для PostgreSQL — **[Grafana Alloy Overview](../../../Grafana/grafana_alloy_overview.md#сценарий-2-full-stack-observability-для-postgresql)**.

### Связанные документы

- **Observability основы:** **[Observability Definitions](../../../Concepts/Observability_and_Monitoring/observability_definitions.md)**
- **4 столпа:** **[Four Pillars of Observability](../../../Concepts/Observability_and_Monitoring/four_pillars_of_observability.md)**
- **OpenTelemetry:** **[OpenTelemetry Overview](../../../OpenTelemetry/opentelemetry_overview.md)**
- **Оптимизация:** **[Performance Tuning](./performance_tuning.md)**
- **Docker:** **[PostgreSQL в Docker](./docker_deployment.md)**
- **Kubernetes:** **[PostgreSQL в Kubernetes](./kubernetes_deployment.md)**
