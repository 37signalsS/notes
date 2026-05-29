# Метрики: детали

## Определения

**Метрики (Metrics)** — числовые значения, измеряемые через определённые интервалы времени и представляющие собой **временные ряды**. Агрегируют информацию о поведении системы, делая её удобной для анализа и визуализации.

**Назначение:**

- Мониторинг производительности в реальном времени
- Обнаружение аномалий и создание алертов
- Анализ трендов и планирование ресурсов
- Оценка SLA/SLO (Service Level Objectives)

**Инструменты:** **[Prometheus](../../Prometheus/overview.md)** (отраслевой стандарт), **[VictoriaMetrics](../../VictoriaMetrics/overview.md)**, **Grafana Mimir**, **Thanos**.

**Ключевой принцип:** «Думаем и пишем только что надо» — ценой потери деталей получаем эффективность и масштабируемость.

**См. также:** [Четыре столпа Observability](./four_pillars_of_observability.md) — фундаментальные концепции наблюдаемости; [Стратегии сбора метрик](./metrics_collection_strategies.md) — pull vs push модели.

## Базовые концепции

### Типы метрик (Prometheus)

Prometheus выделяет четыре основных типа метрик. Подробное описание каждого типа, их математических свойств и функций PromQL приведено в **[обзоре типов метрик](../../Prometheus/concepts/metric_types/overview.md)**.

| Тип | Описание | Примеры |
| :--- | :--- | :--- |
| **[Counter](../../Prometheus/concepts/metric_types/counter.md)** | Монотонно растущее значение (только увеличение или сброс до 0) | Запросы, ошибки, байты |
| **[Gauge](../../Prometheus/concepts/metric_types/gauge.md)** | Значение может увеличиваться и уменьшаться | Память, температура, задержки |
| **[Histogram](../../Prometheus/concepts/metric_types/histogram.md)** | Распределение значений по бакетам, перцентили на сервере | Время ответа, размер ответов |
| **[Summary](../../Prometheus/concepts/metric_types/summary.md)** | Перцентили вычисляются на клиенте | Длительность операций |

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

**Подробнее:** **[Лейблы и кардинальность в Prometheus](../../Prometheus/concepts/labels_and_cardinality.md)**.

## Практические сценарии

### Сценарий 1: Инструментирование приложения (Python)

**Задача:** добавить метрики к веб-приложению для мониторинга производительности.

**Решение:** использовать клиентскую библиотеку Prometheus:

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

### Сценарий 2: Инфраструктурные метрики (Node Exporter)

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

## Дополнительная информация

### Источники метрик

| Уровень | Тип | Примеры метрик |
| :--- | :--- | :--- |
| **Инфраструктура** | CPU, RAM, Disk, Network | `node_cpu_seconds_total`, `node_memory_MemAvailable_bytes` |
| **Контейнеры** | cgroups, Kubernetes | `container_cpu_usage_seconds_total`, `kube_pod_status_phase` |
| **Приложения** | Задержка (Latency), RPS, Ошибки (Errors) | `http_requests_total`, `http_request_duration_seconds` |
| **Бизнес** | Регистрации, Заказы, DAU/MAU | `user_registrations_total`, `orders_total` |
| **Безопасность** | Неудачные входы, события IDS | `login_attempts_total{status="failed"}` |

**Связь уровней:** рост активных пользователей (бизнес-метрика) → увеличение утилизации CPU (инфраструктурная метрика).

### Лучшие практики

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

### Ресурсы

- **[Prometheus: обзор](../../Prometheus/overview.md)** — архитектура и компоненты
- **[VictoriaMetrics: обзор](../../VictoriaMetrics/overview.md)** — альтернатива Prometheus
- **[Grafana: обзор](../../Grafana/grafana_overview.md)** — визуализация метрик
