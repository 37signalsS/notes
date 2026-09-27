# Recording Rules при масштабировании

Recording Rules — критический инструмент масштабирования Prometheus. При росте инфраструктуры (десятки кластеров, миллионы серий, тяжелые PromQL-запросы) recording rules позволяют перенести вычислительную нагрузку с момента запроса на момент записи, обеспечивая стабильную работу дашбордов и алертов в масштабе.

> **См. также:** [Правила в Prometheus](../rules.md), [Масштабирование Prometheus: обзор](./overview.md), [Кардинальность](../concepts/labels_and_cardinality.md).

## Определения

| Термин | Описание |
|:---|:---|
| **Recording Rule** | Правило, предварительно вычисляющее PromQL-выражение и сохраняющее результат как новую временную серию. Результат доступен мгновенно при запросе. |
| **Виртуальная метрика** | Метрика, созданная recording rule (например, `job:http_requests:rate5m`). Не существует в приложении — только в TSDB. |
| **Rule Federation** | Паттерн, при котором recording rules создаются на одном уровне (Leaf) и используются другим уровнем (Master/Query) через федерацию или Thanos. |
| **Downsampling через rules** | Использование recording rules для создания агрегированных копий данных (5m, 1h) вместо стандартного downsampling в LTS. |
| **Burn Rate Rule** | Recording rule для вычисления скорости сжигания error budget (SLO). Критична для масштабированных SLO-систем. |

## Базовые концепции

### Зачем recording rules при масштабировании

При масштабировании возникают три проблемы, которые решают recording rules:

1. **Производительность запросов:** Запрос `sum(rate(http_requests_total{status=~"5.."}[5m])) by (job)` по миллиарду рядов может занимать секунды. Recording rule вычисляет это один раз и сохраняет результат.

2. **Стабильность алертов:** Алерты на сложные выражения могут «дрожать» из-за вариативности данных. Recording rules вычисляются с фиксированным интервалом, обеспечивая стабильные пороги.

3. **Кросс-кластерная агрегация:** При федерации или Thanos recording rules позволяют агрегировать данные на уровне Leaf и передавать на Master только готовые агрегаты.

### Паттерны recording rules для масштабирования

#### Паттерн 1: Предварительная агрегация для алертов

**Без recording rule (тяжелый запрос при каждом eval):**
```yaml
# Алерт: оценивается каждый evaluation_interval
- alert: HighErrorRate
  expr: |
    sum(rate(http_requests_total{status=~"5.."}[5m])) by (job)
    / sum(rate(http_requests_total[5m])) by (job) > 0.05
```

**С recording rule (вычисляется один раз, алерт использует готовый результат):**
```yaml
groups:
  - name: http_agg
    interval: 30s
    rules:
      - record: job:http_requests:rate5m
        expr: sum(rate(http_requests_total[5m])) by (job)

      - record: job:http_requests_errors:rate5m
        expr: sum(rate(http_requests_total{status=~"5.."}[5m])) by (job)

      - record: job:http_errors:ratio5m
        expr: job:http_requests_errors:rate5m / job:http_requests:rate5m

  - name: http_alerts
    rules:
      - alert: HighErrorRate
        expr: job:http_errors:ratio5m > 0.05
        for: 5m
```

#### Паттерн 2: Агрегация для федерации (Leaf → Master)

На Leaf-сервере создаем recording rules, а Master забирает только готовые агрегаты:

**Leaf-сервер (запись агрегатов):**
```yaml
groups:
  - name: federation_aggregates
    interval: 1m
    rules:
      # Агрегация по кластеру
      - record: cluster:http_requests:rate5m
        expr: sum(rate(http_requests_total[5m])) by (cluster, job)

      # Агрегация по ноде
      - record: node:cpu:utilization
        expr: 100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
```

**Master-сервер (забирает агрегаты через федерацию):**
```yaml
scrape_configs:
  - job_name: 'federate-leaf'
    honor_labels: true
    metrics_path: '/federate'
    params:
      'match[]':
        - '{__name__=~"cluster:.*"}'     # Только recording rules
        - '{__name__=~"node:.*"}'
    static_configs:
      - targets: ['leaf-dc1:9090']
```

#### Паттерн 3: Downsampling через rules

Вместо стандартного downsampling в Thanos/VictoriaMetrics можно использовать recording rules для создания агрегированных копий:

```yaml
groups:
  - name: downsampling_5m
    interval: 5m
    rules:
      - record: instance:node_cpu:avg_rate5m
        expr: avg by (instance) (rate(node_cpu_seconds_total[5m]))

  - name: downsampling_1h
    interval: 1h
    rules:
      - record: instance:node_cpu:avg_rate1h
        expr: avg by (instance) (rate(node_cpu_seconds_total[1h]))
```

#### Паттерн 4: Burn Rate для SLO (Multi-window)

Для масштабированных SLO-систем multi-window burn rate требует двух recording rules с разными окнами:

```yaml
groups:
  - name: slo_burn_rate
    interval: 1m
    rules:
      # Быстрое окно (5 минут)
      - record: slo:error_ratio:burn_rate_5m
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m])) by (job)
          / sum(rate(http_requests_total[5m])) by (job)

      # Медленное окно (1 час)
      - record: slo:error_ratio:burn_rate_1h
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[1h])) by (job)
          / sum(rate(http_requests_total[1h])) by (job)

  - name: slo_alerts
    rules:
      # Быстрое сжигание (14.4x за 5 минут)
      - alert: SLOBurnRateFast
        expr: slo:error_ratio:burn_rate_5m > 14.4 * 0.001
        for: 2m

      # Медленное сжигание (3x за 1 час)
      - alert: SLOBurnRateSlow
        expr: slo:error_ratio:burn_rate_1h > 3 * 0.001
        for: 15m
```

### Именование recording rules

Стандарт паттерна `level:metric:operations`:

| Уровень | Описание | Пример |
|:---|:---|:---|
| **level** | Область агрегации | `job`, `cluster`, `instance` |
| **metric** | Исходная метрика | `http_requests`, `cpu` |
| **operations** | Операции | `rate5m`, `ratio`, `sum` |

**Примеры:**
```
job:http_requests:rate5m          # rate http_requests за 5m по job
job:http_errors:ratio5m           # доля ошибок по job
cluster:node_cpu:utilization      # Utilization CPU по кластеру
instance:node_memory:available    # Доступная память по инстансу
```

### Оптимизация производительность recording rules

**Проблема:** recording rules выполняются на каждом evaluation_interval. Тяжелые выражения с большими окнами могут перегружать CPU.

**Решения:**

1. **Синхронизация интервалов:**
   ```yaml
   # Правило вычисляется каждые 30s
   groups:
     - name: agg
       interval: 30s  # Кратно scrape_interval (15s)
       rules:
         - record: job:http_requests:rate5m
           expr: sum(rate(http_requests_total[5m])) by (job)
   ```

2. **Ограничение кардинальности:**
   ```yaml
   groups:
     - name: agg
       limit: 10000  # Максимум 10 000 серий от правила
       rules:
         - record: pod:http_requests:rate5m
           expr: sum(rate(http_requests_total[5m])) by (pod)
   ```

3. **Разделение по группам:**
   ```yaml
   # Легкие правила — часто
   - name: fast_agg
     interval: 15s
     rules:
       - record: job:http_requests:rate15s
         expr: sum(rate(http_requests_total[15s])) by (job)

   # Тяжелые правила — реже
   - name: slow_agg
     interval: 5m
     rules:
       - record: job:http_requests:rate5m
         expr: sum(rate(http_requests_total[5m])) by (job)
   ```

## Практические сценарии

### Сценарий 1: Recording Rules для шардированного Prometheus

При шардировании (несколько инстансов Prometheus) recording rules выполняются на каждом шарде. Для глобальных агрегатов используйте Thanos Ruler или Mimir Ruler:

**На каждом шарде (local rules):**
```yaml
groups:
  - name: shard_local
    rules:
      - record: shard:http_requests:rate5m
        expr: sum(rate(http_requests_total[5m])) by (job)
```

**Thanos Ruler (глобальные rules):**
```yaml
# thanos-ruler.yml
rule:
  - /etc/thanos/rules/global.yml

# global.yml
groups:
  - name: global_agg
    rules:
      - record: global:http_requests:rate5m
        expr: sum(thanos_rule_evaluation_duration_seconds{job="thanos-ruler"})
        # Фактически Thanos Ruler опрашивает Thanos Query
        # и вычисляет агрегаты по всем кластерам
```

### Сценарий 2: Recording Rules для Federation

**Leaf (запись):**
```yaml
groups:
  - name: leaf_federation
    interval: 1m
    rules:
      - record: leaf:node_cpu:avg
        expr: avg by (instance) (rate(node_cpu_seconds_total{mode!="idle"}[5m])) * 100

      - record: leaf:node_memory:available_ratio
        expr: node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes
```

**Master (забирает через /federate):**
```yaml
scrape_configs:
  - job_name: 'federate'
    honor_labels: true
    metrics_path: '/federate'
    params:
      'match[]':
        - '{__name__=~"leaf:.*"}'
    static_configs:
      - targets: ['leaf-1:9090', 'leaf-2:9090']
```

### Сценарий 3: Recording Rules для Kubernetes Operator

В Prometheus Operator recording rules описываются через CRD `PrometheusRule`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: app-scaling-rules
  namespace: monitoring
  labels:
    prometheus: main
    role: alert-rules
spec:
  groups:
    - name: app.scaling
      interval: 30s
      rules:
        - record: namespace:pod_cpu:request_ratio
          expr: |
            sum(kube_pod_container_resource_requests{resource="cpu"})
              by (namespace)
            / sum(kube_pod_container_resource_limits{resource="cpu"})
              by (namespace)

        - record: namespace:pod_memory:request_ratio
          expr: |
            sum(kube_pod_container_resource_requests{resource="memory"})
              by (namespace)
            / sum(kube_pod_container_resource_limits{resource="memory"})
              by (namespace)

    - name: app.scaling.alerts
      rules:
        - alert: NamespaceCPURequestsNearLimit
          expr: namespace:pod_cpu:request_ratio > 0.9
          for: 10m
          annotations:
            summary: "Namespace {{ $labels.namespace }} uses >90% of CPU limits"
```

### Сценарий 4: Мониторинг recording rules

```promql
# Количество recording rules (оценка)
count(count by (rule_group) (prometheus_rule_group_rules{type="recording"}))

# Время выполнения групп правил (p99)
histogram_quantile(0.99,
  sum(rate(prometheus_rule_group_duration_seconds_bucket[5m])) by (le, rule_group)
)

# Ошибки recording rules
increase(prometheus_rule_group_last_errors_total{type="recording"}[5m])

# Количество серий, созданных recording rules
sum(prometheus_rule_group_series{type="recording"}) by (rule_group)
```

## Диагностика и решение проблем

| Проблема | Причина | Решение |
|:---|:---|:---|
| **Recording rule не обновляется** | Интервал правила меньше `scrape_interval` | Увеличить `interval` до >= `scrape_interval` |
| **Recording rule создает Millions серий** | Ошибка в селекторе, высокая кардинальность | Добавить `limit`, сузить селекторы |
| **Алерт дрожит (flapping)** | Recording rule вычисляется на неполных данных | Увеличить `interval` правила, увеличить `for` в алерте |
| **Гонка данных между группами** | Alerting rule использует recording rule из другой группы | Объединить в одну группу или синхронизировать `interval` |
| **Высокий CPU от rules** | Много тяжелых выражений | Разделить на fast/slow группы, упростить выражения |
| **Recording rules не видны в Thanos** | Thanos Query не опрашивает Rules API Prometheus | Проверить `--rule` флаги в Thanos Sidecar |

## Граничные случаи и ограничения

### Recording Rules и Agent Mode
- **Agent Mode не выполняет правила:** Recording и alerting rules в Agent Mode отсутствуют. Всю логику обработки переносите на LTS (Thanos Ruler, Mimir Ruler).

### Recording Rules и federation
- **Federation забирает recording rules:** При федерации recording rules Leaf-сервера доступны Master-у через `{__name__=~"job:.*"}`. Убедитесь, что имена recording rules уникальны между кластерами.
- **Конфликт external_labels:** Если recording rule создает метрику `job:foo:rate5m`, а на Master-сервере есть такая же метрика от федерации — возникает конфликт. Используйте `external_labels` для различения.

### Recording Rules и Downsampling
- **Downsampling в Thanos/VictoriaMetrics не заменяет recording rules:** Downsampling работает на сырых данных (raw → 5m/1h). Recording rules работают на агрегированном уровне (создают новые метрики). Это взаимодополняющие механизмы.

### Recording Rules и PromQL
- **Extrapolation:** `rate()` и `increase()` экстраполируют данные на границах окна. В recording rules экстраполяция происходит при каждом eval — убедитесь, что `interval` >= `scrape_interval`.
- **Zero samples:** Если scrape не происходит (target down), recording rule может вернуть NaN или пустой результат. Учитывайте это в алертах через `absent()`.

## Дополнительная информация

### Лучшие практики (2025–2026)

1. **Именование `level:metric:operations`** — единый стандарт для поиска и поддержки.
2. **`interval` >= `scrape_interval`** — иначе правила будут пропускать циклы.
3. **`limit` на каждую группу** — защита от взрывной кардинальности из-за ошибок в селекторах.
4. **Группируйте recording + alerting rules** — alerting rules должны依赖 от recording rules в той же группе.
5. **Не создавайте recording rules для каждого дашборда** — оптимизируйте только тяжелые запросы.
6. **Мониторьте `prometheus_rule_group_duration_seconds`** — если время выполнения приближается к `interval`, правило нужно оптимизировать.
7. **Используйте Thanos Ruler для глобальных правил** — в распределенных архитектурах.

### См. также
*   [Правила в Prometheus](../rules.md) — полная документация по recording и alerting rules
*   [Масштабирование Prometheus: обзор](./overview.md) — общие стратегии
*   [Alertmanager at scale](./alertmanager_scaling.md) — масштабирование доставки алертов
*   [Кардинальность](../concepts/labels_and_cardinality.md) — управление количеством серий
