# vmestimator: оценка кардинальности в реальном времени

## 1. Определения

**vmestimator** — инструмент экосистемы VictoriaMetrics для непрерывной оценки кардинальности (количества уникальных временных рядов) в реальном времени на этапе приёма метрик. Распространяется под лицензией Apache-2.0. В отличие от пост-фактум анализа TSDB, vmestimator оценивает кардинальность до записи данных в хранилище, что позволяет предотвратить взрыв кардинальности до наступления деградации системы.

Ключевая метрика, экспортируемая vmestimator, — `cardinality_estimate`. Она показывает текущую оценку количества уникальных серий за заданный интервал и группу лейблов.

## 2. Базовые концепции

### Принцип работы

vmestimator развёртывается на коллекторном узле (обычно рядом с `vmagent`) и наблюдает за входящим потоком метрик, не вмешиваясь в путь инжеста. На основе поступающих данных он строит оценки кардинальности по конфигурируемым измерениям (label dimensions) и экспортирует их в формате, совместимом с Prometheus.

```
Источники метрик → vmagent → vmestimator (наблюдатель) → VictoriaMetrics
                                   ↓
                             /metrics (scrape)
                                   ↓
                              Prometheus / VictoriaMetrics → Grafana / vmalert
```

### Зачем нужен vmestimator

Классические инструменты анализа кардинальности (`promtool tsdb analyze`, Cardinality Explorer в VMUI) работают с уже записанными данными. Это означает, что взрыв кардинальности обнаруживается постфактум, когда система уже деградировала.

vmestimator закрывает этот пробел:
- **Реальное время:** оценки строятся continuously, а не по завершении интервала сбора.
- **Проактивность:** алерты срабатывают до того, как кардинальность нанесёт ущерб.
- **Гибкость группировки:** можно оценивать кардинальность по произвольным лейблам (`job`, `__name__`, `tenant` и т.д.).

### Отличие от Cardinality Explorer (VMUI)

| Критерий | vmestimator | Cardinality Explorer (VMUI) |
| :--- | :--- | :--- |
| **Момент измерения** | До инжеста (source-side) | После записи (storage-side) |
| **Точность** | Оценка (гиперloglog) | Точный подсчёт |
| **Группировка** | Только предопределённые | Произвольные комбинации |
| **Исторические тренды** | Да | Нет |
| **Стоимость запроса** | Низкая (не нагружает хранилище) | Высокая (сканирует индекс) |
| **Алертинг** | Да (через vmalert) | Нет |

## 3. Конфигурация

Поведение vmestimator задаётся в файле `streams.yaml`. Основные параметры:

```yaml
# streams.yaml

# Глобальная оценка кардинальности с интервалом 15 минут
- interval: '15m'

# Оценка по именам метрик
- interval: '15m'
  group_by: ['__name__']

# Оценка по job с дополнительным измерением по региону
- interval: '15m'
  group_by: ['job', 'region']

# Оценка по tenant (мультитенантные среды)
- interval: '30m'
  group_by: ['tenant']
```

### Параметры

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `interval` | `duration` | Интервал оценки (например, `15m`, `30m`, `1h`). Определяет, как часто пересчитывается оценка. |
| `group_by` | `[]string` | Список лейблов для группировки. Специальное значение `__global__` (дефолт) означает оценку без группировки. |

> **Важно:** Интервал — это компромисс между скоростью обнаружения и стабильностью оценки. Слишком короткий интервал (< 5m) даёт шумные данные при переменной нагрузке; слишком длинный (> 1h) замедляет обнаружение всплесков.

### Запуск

```bash
# Docker
docker run --rm \
  -p 8490:8490 \
  -v /path/to/streams.yaml:/streams.yaml \
  docker.io/victoriametrics/vmestimator:latest \
  -config=/streams.yaml
```

```bash
# Бинарник
vmestimator -config=/streams.yaml
# → метрики доступны на http://localhost:8490/metrics
```

## 4. Метрики и запросы

### Ключевая метрика

```promql
# Глобальная оценка за 15 минут
cardinality_estimate{interval="15m0s", group_by_keys="__global__"}

# Оценка по имени метрики
cardinality_estimate{interval="15m0s", group_by_keys="__name__"}

# Оценка по job
cardinality_estimate{interval="30m0s", group_by_keys="job"}
```

### Полезные запросы

```promql
# Топ-5 метрик по кардинальности за 15 минут
topk(5, cardinality_estimate{interval="15m0s", group_by_keys="__name__"})

# Топ-5 job по кардинальности
topk(5, cardinality_estimate{interval="30m0s", group_by_keys="job"})

# Churn rate: разница между 30m и 15m оценками (в процентах)
(
  max(cardinality_estimate{interval="30m0s", group_by_keys="job"}) without(instance)
  -
  max(cardinality_estimate{interval="15m0s", group_by_keys="job"}) without(instance)
)
/
max(cardinality_estimate{interval="30m0s", group_by_keys="job"}) without(instance) * 100
```

## 5. Практические сценарии

### Сценарий 1: Обнаружение всплеска кардинальности

**Задача:** Получать алерт, когда кардинальность для любого job превышает 20 000 серий за 30 минут.

```yaml
# vmalert rules
groups:
  - name: 'cardinality'
    rules:
      - alert: 'JobTooHighCardinality'
        expr: 'max(cardinality_estimate{group_by_keys="job", interval="30m0s"}) without(instance) > 20000'
        for: '15m'
        labels:
          severity: 'warning'
        annotations:
          dashboard: "{{ $externalURL }}/d/mktd5g9?var-group_by_keys=job&var-interval={{ $labels.interval }}"
          summary: "High cardinality for job {{ $labels.group_by_values }}"
          description: "Job {{ $labels.group_by_values }} has {{ $value }} estimated series over the last {{ $labels.interval }}, exceeding the 20000 series threshold."
```

### Сценарий 2: Алерт на высокий Churn Rate

**Задача:** Обнаружить job, у которых более 10% серий «умерло» и было заменено новыми между окнами 15m и 30m.

```yaml
      - alert: 'JobTooHighChurnRate'
        expr: |
          (
              max(cardinality_estimate{group_by_keys="job", interval="30m0s"}) without (instance)
              -
              max(cardinality_estimate{group_by_keys="job", interval="15m0s"}) without (instance)
          )
          /
          max(cardinality_estimate{group_by_keys="job", interval="30m0s"}) without (instance) * 100 > 10
        for: '15m'
        labels:
          severity: 'warning'
        annotations:
          dashboard: "{{ $externalURL }}/d/mktd5g9?var-group_by_keys=job&var-churn_short=15m0s&var-churn_long=30m0s"
          summary: "High churn rate for job {{ $labels.group_by_values }}"
          description: 'Job {{ $labels.group_by_values }} has {{ printf "%.0f%%" $value }} of series churned between the 15m and 30m cardinality windows, exceeding the 10% threshold.'
```

### Сценарий 3: Визуализация в Grafana

vmestimator поставляется с двумя готовыми дашбордами:

1. **vmestimator metrics** — метрики самого приложения (CPU, RAM, ingestion rate, concurrent inserts, saturation group keys).
2. **Cardinality Estimations** — общая кардинальность, churn rate, топ-10 метрик и job.

Дашборды импортируются из репозитория vmestimator или доступны в VictoriaMetrics Grafana Playground (разделы `cardinality` и `cardinality.recording`).

### Сценарий 4: Планирование capacity

Долгосрочные тренды кардинальности, собираемые vmestimator в VictoriaMetrics, полезны для capacity planning:

```promql
# Прогноз роста кардинальности на 30 дней
predict_linear(cardinality_estimate{group_by_keys="__global__"}[30d], 30 * 24 * 3600)
```

## 6. Интеграция с vmagent

vmestimator не требует изменений в конфигурации vmagent. Достаточно запустить vmestimator рядом с vmagent и настроить scraping метрик vmestimator через Prometheus или vmagent:

```yaml
# vmagent scrape config
scrape_configs:
  - job_name: 'vmestimator'
    static_configs:
      - targets: ['localhost:8490']
```

## 7. Часто задаваемые вопросы

**В: Нужен ли VictoriaMetrics для использования vmestimator?**
Нет. vmestimator может работать автономно и экспортировать метрики через HTTP. Однако VictoriaMetrics + vmalert + Grafana дают полный цикл: хранение, запросы, визуализацию и алертинг.

**В: Совместим ли vmestimator с Prometheus?**
Да. vmestimator экспортирует метрики в формате Prometheus text exposition и совместим с любым клиентом, поддерживающим remote write v1.

**В: Какова точность оценок?**
vmestimator использует вероятностные структуры данных (HyperLogLog) для оценки кардинальности с контролируемой погрешностью. Точность зависит от выбранного интервала и объёма данных.

**В: Чем vmestimator отличается от `promtool tsdb analyze`?**
`promtool tsdb analyze` — это офлайн-инструмент для анализа уже записанных данных на диске. vmestimator работает в реальном времени на этапе сбора и позволяет получать алерты до попадания данных в TSDB.

## 8. Дополнительная информация

- **Официальная документация:** [vmestimator docs](https://docs.victoriametrics.com/vmestimator/)
- **Репозиторий:** [github.com/VictoriaMetrics/vmestimator](https://github.com/VictoriaMetrics/vmestimator)
- **Примеры конфигураций и алертов:** в репозитории vmestimator в директории `deploy/`
- **Grafana Playground:** онлайновые дашборды и алерты доступны в VictoriaMetrics Grafana Playground (разделы `cardinality` и `cardinality.recording`).

Связанные компоненты:
- [VictoriaMetrics — обзор](./overview.md) — платформа хранения метрик;
- [vmalert — обзор](./vmalert_overview.md) — алертинг на основе метрик vmestimator;
- [vmagent](./overview.md) — сбор и forwarding метрик;
- [Cardinality в Prometheus](../Prometheus/concepts/labels_and_cardinality.md) — фундаментальные концепции кардинальности;
- [Мониторинг и алертинг](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md) — методологии алертинга.
