# Metrics Deep Dive

## Определения

**Метрики (Metrics)** — числовые значения, измеряемые через определённые интервалы времени и представляющие собой **временные ряды**. Агрегируют информацию о поведении системы, делая её удобной для анализа и визуализации.

**Назначение:**
- Мониторинг производительности в реальном времени
- Обнаружение аномалий и создание алертов
- Анализ трендов и планирование ресурсов
- Оценка SLA/SLO (Service Level Objectives)

**Инструменты:** **[Prometheus](../../../Prometheus/overview.md)** (отраслевой стандарт), **[VictoriaMetrics](../../../VictoriaMetrics/overview.md)**, **Grafana Mimir**, **Thanos**.

**Ключевой принцип:** «Думаем и пишем только что надо» — ценой потери деталей получаем эффективность и масштабируемость.

**См. также:** [Четыре столпа Observability](./four_pillars_of_observability.md) — фундаментальные концепции наблюдаемости; [Стратегии сбора метрик](./metrics_collection_strategies.md) — pull vs push модели.

## Базовые концепции

### Типы метрик в Prometheus

| Тип | Описание | Примеры | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Counter** | Монотонно растущее значение (только увеличение или сброс до 0) | Запросы, ошибки, байты | Подсчёт событий за время |
| **Gauge** | Значение может увеличиваться и уменьшаться | Память, температура, задержки | Мгновенные значения |
| **Histogram** | Распределение значений по бакетам, перцентили на сервере | Время ответа, размер ответов | Анализ распределения |
| **Summary** | Перцентили вычисляются на клиенте | Длительность операций | Точные перцентили на instance |

### 1. Counter (Счётчик)

**Описание:** монотонно возрастающее значение, которое может только увеличиваться или сбрасываться до нуля (например, при перезапуске). Не может уменьшаться или принимать отрицательные значения.

**Примеры:**
- `http_requests_total` — общее количество HTTP-запросов
- `http_errors_total` — общее количество ошибок
- `node_network_receive_bytes_total` — всего получено байтов

**Ограничения:** не подходит для показателей, которые могут уменьшаться (свободная память, количество процессов).

**Использование:** для получения скорости изменения (запросов в секунду) используются функции `rate()` или `irate()` в **[PromQL](../../../Prometheus/concepts/promql/selectors_operators.md)**.

```promql
# Запросов в секунду за последние 5 минут
rate(http_requests_total[5m])

# Мгновенная скорость (последние 15 секунд)
irate(http_requests_total[1m])
```

**Подробнее:** **[Counter: детали](../../../Prometheus/concepts/metric_types/counter.md)**.

### 2. Gauge (Измеритель)

**Описание:** метрика, значение которой может как увеличиваться, так и уменьшаться. Отражает текущее состояние или значение в определённый момент времени.

**Примеры:**
- `node_memory_MemAvailable_bytes` — доступная память
- `process_resident_memory_bytes` — потребление памяти процессом
- `temperature_celsius` — текущая температура
- `active_users_online` — количество пользователей онлайн

**Использование:** мгновенные значения или метрики, колеблющиеся в обоих направлениях.

```promql
# Текущее потребление памяти
node_memory_MemAvailable_bytes

# Процент доступной памяти
(node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100
```

**Подробнее:** **[Gauge: детали](../../../Prometheus/concepts/metric_types/gauge.md)**.

### 3. Histogram (Гистограмма)

**Описание:** распределяет наблюдаемые значения (длительность запросов, размер ответов) по настраиваемым диапазонам (бакетам). Prometheus хранит несколько временных рядов:

| Суффикс | Описание |
| :--- | :--- |
| `_bucket` | Кумулятивные счётчики для каждого бакета (метка `le` — less than or equal) |
| `_sum` | Общая сумма всех наблюдаемых значений |
| `_count` | Общее количество всех наблюдаемых значений |

**Пример:** `le="0.1"` означает «значения, меньшие или равные 0.1 секунды».

**Использование:**

| Возможность | Описание |
| :--- | :--- |
| **Перцентили** | Вычисление на стороне сервера через `histogram_quantile()` |
| **Среднее значение** | Расчёт через `_sum` / `_count` |
| **SLI** | Отслеживание пропорций («какой процент запросов быстрее 200мс?») |

```promql
# 99-й перцентиль времени ответа за 5 минут
histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))

# Среднее время ответа
rate(http_request_duration_seconds_sum[5m]) / rate(http_request_duration_seconds_count[5m])

# Процент запросов быстрее 200мс
sum(rate(http_request_duration_seconds_bucket{le="0.2"}[5m])) 
/ 
sum(rate(http_request_duration_seconds_count[5m]))
```

**Подробнее:** **[Гистограмма: детали](../../../Prometheus/concepts/metric_types/histogram.md)**, **[Перцентили и квантили](../../../Prometheus/concepts/metric_types/percentiles.md)**.

### 4. Summary (Сводка)

**Описание:** похожа на гистограмму, но перцентили **вычисляются на стороне клиента** (в приложении) за скользящий период времени и экспортируются готовыми.

**Преимущества:**

| Плюс | Описание |
| :--- | :--- |
| **Точность** | Перцентили точны для каждого отдельного экземпляра (instance) |

**Недостатки:**

| Минус | Описание |
| :--- | :--- |
| **Сложность агрегации** | Нельзя усреднить перцентили между экземплярами |
| **Ресурсы** | Расчёт квантилей на клиенте потребляет больше ресурсов |

**Использование:** измерение продолжительности событий, когда важна точность на каждом instance.

```promql
# 95-й перцентиль из Summary (уже вычислен)
http_request_duration_seconds{quantile="0.95"}
```

**Подробнее:** **[Summary: детали](../../../Prometheus/concepts/metric_types/summary.md)**, **[Histogram: сравнение с Summary](../../../Prometheus/concepts/metric_types/histogram.md#сравнение-с-summary)**, **[Агрегация Summary](../../../Prometheus/concepts/metric_types/percentiles.md#агрегация-summary-проблема-и-решение)**.

### Характеристики метрик

| Характеристика | Описание |
| :--- | :--- |
| **Общая картина** | Метрики собирают выжимку, а не все детали |
| **Масштабируемость** | Хорошо масштабируется, быстрая реакция на алерты |
| **Детализация** | Низкая — для деталей нужно добавлять метрики |
| **Трафик** | Зависит от количества метрик и интервала, а не от трафика приложения |
| **Минимализм** | Пишем только необходимое для снижения нагрузки |
| **Агрегация** | Метрики агрегируются перед отправкой |

### Метрики vs Логи: Сравнение

| Критерий | Логи | Метрики |
| :--- | :--- | :--- |
| **Детализация** | Очень высокая (каждое событие) | Ограниченная (агрегированные данные) |
| **Трафик** | Зависит от трафика приложения | Зависит от количества метрик и интервала |
| **Структура** | Часто не структурированы | Структурированные числовые данные |
| **Обработка** | Сложная, требует парсинга | Быстрая, индексация не требуется |
| **Масштабируемость** | Плохая | Хорошая |
| **Реакция** | Отстаёт от реального времени | Моментальная реакция и алерты |
| **Подход** | Пишем всё → потом думаем | Думаем → пишем только необходимое |

**Когда использовать только логи:** если у вас немного сервисов и не планируется масштабирование, можно остановиться на парсинге логов (ELK Stack имеет встроенную визуализацию).

### Многомерность: Векторы и Лейблы

**Вектор** — термин для описания многомерной природы метрик в Prometheus. Любая метрика может быть «вектором», если имеет **лейблы (labels)**.

**Лейблы** — пары ключ-значение, добавляющие измерения и контекст:

```
http_requests_total{method="POST", instance="server1", status="200"}
```

**Возможности:**
- Фильтрация метрик по лейблам
- Группировка и агрегация
- Срезы данных (by method, by instance, by status)

**Подробнее:** **[Лейблы и кардинальность в Prometheus](../../../Prometheus/concepts/labels_and_cardinality.md)**.

## Практический сценарий: Инструментирование приложения

### Сценарий 1: Метрики HTTP-сервиса

**Задача:** добавить метрики к веб-приложению для мониторинга производительности.

**Решение:** использовать клиентскую библиотеку Prometheus (пример на Python):

```python
from prometheus_client import Counter, Gauge, Histogram, start_http_server
import time
import random

# Определение метрик
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'status'])
REQUEST_LATENCY = Histogram('http_request_duration_seconds', 'HTTP request latency', 
                            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0])
ACTIVE_CONNECTIONS = Gauge('active_connections', 'Number of active connections')

def process_request(method):
    ACTIVE_CONNECTIONS.inc()
    start_time = time.time()
    status = "200"
    
    try:
        # Имитация обработки запроса
        time.sleep(random.uniform(0.01, 0.5))
    except Exception:
        status = "500"
    finally:
        duration = time.time() - start_time
        REQUEST_LATENCY.observe(duration)
        REQUEST_COUNT.labels(method=method, status=status).inc()
        ACTIVE_CONNECTIONS.dec()
```

**Результат:** эндпоинт `/metrics` с метриками для скрапинга Prometheus.

### Сценарий 2: Инфраструктурные метрики

**Задача:** собрать базовые метрики с серверов Linux.

**Решение:** установить **node-exporter** — стандартный экспортер Prometheus.

```yaml
# docker-compose.yml
version: '3'
services:
  node-exporter:
    image: prom/node-exporter:latest
    ports:
      - "9100:9100"
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
```

**Доступные метрики:**
- CPU: `node_cpu_seconds_total`, `node_load1`, `node_load5`, `node_load15`
- RAM: `node_memory_MemTotal_bytes`, `node_memory_MemAvailable_bytes`
- Disk: `node_filesystem_avail_bytes`, `node_disk_io_time_seconds_total`
- Network: `node_network_receive_bytes_total`, `node_network_transmit_bytes_total`

## Additional Information

### Источники метрик

| Уровень | Тип | Примеры метрик |
| :--- | :--- | :--- |
| **Инфраструктура** | CPU, RAM, Disk, Network | `node_cpu_seconds_total`, `node_memory_MemAvailable_bytes` |
| **Контейнеры** | cgroups, Kubernetes | `container_cpu_usage_seconds_total`, `kube_pod_status_phase` |
| **Приложения** | Latency, RPS, Errors | `http_requests_total`, `http_request_duration_seconds` |
| **Бизнес** | Регистрации, Заказы, DAU/MAU | `user_registrations_total`, `orders_total` |
| **Безопасность** | Failed logins, IDS events | `login_attempts_total{status="failed"}` |

**Связь уровней:** рост активных пользователей (бизнес-метрика) → увеличение утилизации CPU (инфраструктурная метрика).

### Best Practices

| Практика | Описание |
| :--- | :--- |
| **Именование** | Использовать суффиксы `_total` для Counter, `_seconds` для времени, `_bytes` для размера |
| **Лейблы** | Избегать высокой кардинальности (не использовать user_id, email) |
| **Документация** | Добавлять HELP и UNIT к метрикам |
| **Сэмплирование** | Для гистограмм выбирать разумные бакеты (не более 10–20) |
| **Агрегация** | Использовать recording rules для сложных запросов |

### Связанные темы

- **[Четыре столпа Observability](./four_pillars_of_observability.md)** — место метрик в наблюдаемости
- **[Стратегии сбора метрик](./metrics_collection_strategies.md)** — pull vs push модели
- **[Логи: детали](./logs_deep_dive.md)** — сравнение с логами
- **[Методологии мониторинга](./monitoring_methodologies.md)** — Golden Signals, RED, USE
- **[Лейблы и кардинальность](../../../Prometheus/concepts/labels_and_cardinality.md)** — работа с лейблами

### Дополнительные ресурсы

- **[Prometheus: обзор](../../../Prometheus/overview.md)** — архитектура и компоненты
- **[PromQL: селекторы и операторы](../../../Prometheus/concepts/promql/selectors_operators.md)** — язык запросов
- **[Типы метрик: обзор](../../../Prometheus/concepts/metric_types/overview.md)** — подробное описание типов
- **[VictoriaMetrics: обзор](../../../VictoriaMetrics/overview.md)** — альтернатива Prometheus
- **[Grafana: обзор](../../../Grafana/grafana_overview.md)** — визуализация метрик
