# Правила в Prometheus: Recording и Alerting

В [Prometheus](./overview.md) "правила" (rules) — это набор выражений на языке [PromQL](./concepts/promql/functions.md), которые периодически вычисляются на сервере. Они используются для создания новых временных рядов и для генерации оповещений.

> **См. также:** [Типы метрик](./concepts/metric_types/alerts.md), [Лейблы и кардинальность](./concepts/labels_and_cardinality.md), [PromQL](./concepts/promql/functions.md).

---

### 1. Определения

Существует два типа правил, которые настраиваются в конфигурационных файлах Prometheus:

* **Правила записи (Recording Rules)**
    Позволяют предварительно вычислять часто используемые или ресурсоемкие PromQL-запросы и сохранять их результаты в виде нового набора временных рядов. Это "виртуальные" метрики, которые можно использовать в других запросах, дашбордах или правилах.

* **Правила оповещений (Alerting Rules)**
    Позволяют определять условия, при которых Prometheus генерирует оповещения (алерты). Если выражение в правиле становится истинным, Prometheus отправляет алерт в [Alertmanager](./alertmanager.md) для дальнейшей обработки.

---

### 2. Основные концепции

#### Назначение и синтаксис правил

Оба типа правил определяются в YAML-файлах и объединяются в группы (`groups`). Правила внутри одной группы выполняются последовательно с заданным интервалом.

**Правила записи (Recording Rules)**

* **Назначение:**
    1. **Оптимизация производительности**: Снижают нагрузку на Prometheus, избавляя от необходимости выполнять "тяжелые" запросы на лету, например, в дашбордах [Grafana](../Grafana/dashboards/definitions_and_concepts.md).
    2. **Упрощение сложных запросов**: Помогают обойти ограничения [PromQL](./concepts/promql/functions.md), сохраняя промежуточные результаты вычислений.
    3. **Создание абстракций**: Формируют слой "виртуальных" метрик со стабильными именами, не зависящими от исходных экспортеров.
* **Недостатки:** Каждое правило создает новый временной ряд, что увеличивает потребление дискового пространства.
* **Синтаксис:**
  * `record`: Имя новой метрики.
  * `expr`: PromQL-выражение для вычисления.
  * `labels`: (Опционально) Метки, которые будут добавлены к новой метрике.

**Правила оповещений (Alerting Rules)**

* **Назначение:** Определяют условия для генерации алертов.
* **Синтаксис:**
  * `alert`: Имя алерта.
  * `expr`: PromQL-выражение. Если оно истинно, алерт переходит в состояние `Pending`, а затем `Firing`.
  * `for`: Период, в течение которого `expr` должно быть истинным, чтобы алерт стал `Firing`. Помогает отсеивать кратковременные сбои.
  * `labels`: Дополнительные метки для маршрутизации в [Alertmanager](./alertmanager.md) (например, `severity`).
  * `annotations`: Дополнительная информация для уведомлений (описание, summary, ссылки), поддерживает шаблоны.

#### Управление правилами

1. **Конфигурация Prometheus**: Пути к файлам с правилами указываются в `prometheus.yml`.

    ```yaml
    rule_files:
      - "rules.yml"
      - "rules/*.yml"
    ```

2. **Проверка синтаксиса**: Для валидации используется утилита [promtool](./promtool_and_best_practices.md).

    ```bash
    promtool check rules /path/to/your/rules.yml
    ```

3. **Применение**: Конфигурация перезагружается без перезапуска сервиса.

    ```bash
    # Для systemd
    systemctl reload prometheus.service
    
    # Для Docker
    docker-compose exec prometheus kill -HUP 1 
    ```

4. **Проверка в UI**: Загруженные правила и активные алерты отображаются в разделах **Status -> Rules** и **Alerts** веб-интерфейса Prometheus.

---

### 3. Практические сценарии

Рассмотрим пример файла правил `/etc/prometheus/rules/node_rules.yml`, который объединяет оба типа правил для мониторинга состояния узлов с `node_exporter`.

```yaml
groups:
  - name: node-exporter-rules
    interval: 30s
    rules:
      # --- Recording Rules ---

      # 1. Подсчет количества CPU на каждом узле для дальнейших расчетов.
      - record: instance:node_cpus:count
        expr: count(node_cpu_seconds_total{mode="idle"}) without (cpu, mode)

      # 2. Расчет утилизации CPU в процентах.
      # Мы используем ранее созданную метрику `instance:node_cpus:count`.
      - record: instance:node_cpu_utilization:ratio
        expr: sum(rate(node_cpu_seconds_total{mode!="idle"}[5m])) without (mode) / instance:node_cpus:count

      # --- Alerting Rules ---

      # 3. Оповещение о недоступности экспортера.
      # Использует стандартную метрику `up`.
      - alert: ExporterDown
        expr: up{job="node_exporter"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Exporter down (instance {{ $labels.instance }})"
          description: "Prometheus exporter '{{ $labels.job }}' на узле {{ $labels.instance }} недоступен."

      # 4. Оповещение о высокой нагрузке на CPU.
      # Использует метрику, созданную правилом записи.
      - alert: HighCpuLoad
        expr: instance:node_cpu_utilization:ratio * 100 > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High CPU load on {{ $labels.instance }}"
          description: "Нагрузка на CPU узла {{ $labels.instance }} превышает 85%.\n  ТЕКУЩЕЕ ЗНАЧЕНИЕ: {{ $value | printf `%.2f` }}%"
```

---

### 4. Дополнительная информация

* **Именование Recording Rules**: Настоятельно рекомендуется придерживаться формата `level:metric:operations` (например, `instance:node_cpu_utilization:ratio`). Это значительно упрощает навигацию и отладку, так как имя метрики сразу говорит о уровне ее агрегации (`instance`), исходной метрике (`node_cpu`) и примененных операциях (`ratio`).
* **Шаблоны в аннотациях**: Используйте переменные, такие как `{{ $labels.<name> }}` и `{{ $value }}`, для создания информативных и динамических сообщений в алертах.

### Примеры алертов для разных типов метрик

**Алерт на основе Counter (доля ошибок):**

```yaml
- alert: HighErrorRate
  expr: |
    sum(rate(http_requests_total{status=~"5.."}[5m])) 
    / 
    sum(rate(http_requests_total[5m])) > 0.05
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Высокая доля ошибок HTTP 5xx"
    description: "Доля ошибок составляет {{ $value | humanizePercentage }}"
```

**Алерт на основе Gauge (память):**

```yaml
- alert: LowMemory
  expr: |
    (node_memory_mem_available_bytes / node_memory_mem_total_bytes) * 100 < 10
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Мало свободной памяти на {{ $labels.instance }}"
    description: "Свободно только {{ $value | humanize }}%"
```

**Алерт на основе Histogram (латентность):**

```yaml
- alert: HighLatency
  expr: |
    histogram_quantile(0.95, 
      sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
    ) > 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Высокая латентность запросов"
    description: "95-й перцентиль: {{ $value | humanizeDuration }}"
```

**Алерт на основе кардинальности:**

```yaml
- alert: HighCardinality
  expr: count({__name__=~".+"}) > 100000
  for: 15m
  labels:
    severity: warning
  annotations:
    summary: "Высокая кардинальность в Prometheus"
    description: "Общее количество временных рядов: {{ $value | humanize }}"
```
