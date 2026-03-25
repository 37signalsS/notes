# Monitoring Methodologies

## Определения

**Методология мониторинга** — структурированный подход к определению ключевых метрик, которые наиболее точно отражают здоровье системы и пользовательский опыт.

**Цель методологий:** ответить на вопрос *«какие метрики мониторить?»* до начала настройки инструментов, чтобы избежать «шума» и сосредоточиться на значимых сигналах.

## Базовые концепции

### Сравнение методологий

| Методология | Фокус | Уровень | Автор |
| :--- | :--- | :--- | :--- |
| **Four Golden Signals** | Пользовательский опыт | Сервис | Google SRE |
| **RED Method** | Микросервисы | Сервис | Tom Wilkie |
| **USE Method** | Ресурсы | Инфраструктура | Brendan Gregg |

### Когда какую методологию применять

| Сценарий | Рекомендуемая методология |
| :--- | :--- |
| **Микросервисы (request/response)** | RED Method |
| **Монолиты и общие сервисы** | Four Golden Signals |
| **Инфраструктура (CPU, память, диск)** | USE Method |
| **Комплексный мониторинг** | Комбинация всех трёх |

### Связь с SLO/SLI

Методологии помогают определить **SLI (Service Level Indicators)** — метрики, которые отслеживают качество сервиса с точки зрения пользователя. На основе SLI устанавливаются **SLO (Service Level Objectives)** — целевые значения надёжности.

> **Подробно:** [SRE концепции: SLA, SLO, SLI и бюджет ошибок](../sre_concepts_main.md)

## Практические сценарии

### 1. Four Golden Signals (Четыре золотых сигнала)

Подход из книги Google «Site Reliability Engineering». Рекомендуется для общих сервисов и как основа для других методологий.

| Сигнал | Описание | Примеры метрик |
| :--- | :--- | :--- |
| **Задержка (Latency)** | Время обслуживания запроса. Отслеживайте перцентили (p95, p99), а не среднее. | `http_request_duration_seconds`, `query_duration_ms` |
| **Трафик (Traffic)** | Нагрузка на сервис в специфичных единицах. | `requests_per_second`, `bytes_per_second`, `concurrent_users` |
| **Ошибки (Errors)** | Частота неудачных запросов. Явные (HTTP 5xx) и неявные (некорректный ответ). | `http_requests_total{status=~"5.."}`, `error_rate` |
| **Насыщенность (Saturation)** | Насколько система близка к пределу производительности. | `memory_usage_percent`, `cpu_usage_percent`, `disk_queue_length` |

**Пример PromQL для Golden Signals:**

```promql
# Latency (p99)
histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))

# Traffic (RPS)
sum(rate(http_requests_total[5m]))

# Errors (error rate)
sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))

# Saturation (memory)
(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100
```

### 2. USE Method (Utilization, Saturation, Errors)

Метод Брендана Грегга для мониторинга ресурсов инфраструктуры.

| Компонент | Описание | Примеры метрик |
| :--- | :--- | :--- |
| **Утилизация (Utilization)** | % времени, когда ресурс занят работой. Высокая утилизация (>90%) — признак узкого места. | `cpu_usage_percent`, `disk_io_util`, `network_utilization` |
| **Насыщенность (Saturation)** | Величина очереди к ресурсу. Работа, которая не может быть выполнена немедленно. | `load_average`, `disk_queue_length`, `tcp_backlog` |
| **Ошибки (Errors)** | Ошибки, связанные с работой ресурса. | `disk_errors_total`, `network_dropped_packets`, `memory_oom_kills` |

**Чек-лист для проверки ресурсов (по Б. Греггу):**

- **CPU:** `usage%`, `load average`, `run queue length`
- **Память:** `used%`, `swap usage`, `oom_kills`
- **Диск:** `util%`, `await`, `queue_length`, `errors`
- **Сеть:** `util%`, `drop_rate`, `error_rate`, `connections`

### 3. RED Method

Метод Тома Уилки для микросервисов. Упрощение Golden Signals для request/response систем.

| Метрика | Описание | Примеры метрик |
| :--- | :--- | :--- |
| **Частота (Rate)** | Запросов в секунду к сервису. | `http_requests_total`, `grpc_server_started_total` |
| **Ошибки (Errors)** | Неудачных запросов в секунду. | `http_requests_total{status=~"5.."}`, `grpc_server_handled_total{grpc_code!="OK"}` |
| **Длительность (Duration)** | Распределение времени обработки (гистограммы). | `http_request_duration_seconds_bucket`, `rpc_duration_seconds_bucket` |

**Пример дашборда для RED Method:**

1. **Rate:** график RPS за последние 15 минут
2. **Errors:** процент ошибок (5xx / total * 100)
3. **Duration:** heatmap или гистограмма времени ответа с перцентилями (p50, p95, p99)

## Дополнительная информация

**Связанные темы:**

- [Определения Observability](./observability_definitions.md) — различия мониторинга и наблюдаемости
- [SRE концепции](../sre_concepts_main.md) — SLA, SLO, SLI, бюджет ошибок
- [Четыре столпа Observability](./four_pillars_of_observability.md) — логи, метрики, трассировки, профилирование
- [Метрики: детали](./metrics_deep_dive.md) — типы метрик и стратегии сбора
