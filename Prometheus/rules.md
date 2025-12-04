# Правила в Prometheus: Recording и Alerting

В Prometheus "правила" (rules) — это набор выражений на языке PromQL, которые периодически вычисляются на сервере. Существует два типа правил: **правила записи** (`recording rules`) и **правила оповещений** (`alerting rules`).

Оба типа правил настраиваются в одних и тех же файлах конфигурации и используют схожий синтаксис, но служат разным целям.

---

## 1. Правила записи (Recording Rules)

**Правила записи** позволяют предварительно вычислять часто используемые или ресурсоемкие PromQL-запросы и сохранять их результаты в виде нового набора временных рядов.

### Назначение

1.  **Оптимизация производительности**: "Тяжелые" запросы в дашбордах Grafana могут создавать значительную нагрузку на Prometheus. Правила записи позволяют вычислить результат один раз и затем использовать уже готовую, легкую метрику, что существенно снижает нагрузку.
2.  **Упрощение сложных запросов**: PromQL не всегда поддерживает вложенность функций. Правила записи позволяют обойти это, сохранив результат внутреннего запроса в новую метрику и работая уже с ней.
3.  **Создание абстракций**: Позволяют создать "виртуальный" слой метрик со стабильными именами, который не зависит от названий метрик в исходных экспортерах.

### Недостатки

Каждое правило записи создает новый временной ряд, что увеличивает потребление дискового пространства. Их следует использовать только при реальной необходимости.

### Синтаксис и именование

*   `record`: Имя новой метрики, которую создаст правило.
*   `expr`: PromQL-выражение для вычисления.
*   `labels`: (Опционально) Метки, которые будут добавлены к новой метрике.

Рекомендуемый формат именования: `level:metric:operations`.
*   `level`: Уровень агрегации (например, `job`, `instance`).
*   `metric`: Имя исходной метрики без суффиксов.
*   `operations`: Список примененных функций (`rate5m`, `sum`).

**Пример:**
```yaml
- record: job:request_failures_per_requests:ratio_rate5m
  expr: |
      sum without (instance, path)(rate(request_failures_total[5m]))
    /
      sum without (instance, path)(rate(requests_total[5m]))
```

---

## 2. Правила оповещений (Alerting Rules)

**Правила оповещений** позволяют определять условия, при которых Prometheus генерирует оповещения (алерты) и отправляет их в Alertmanager.

### Синтаксис

*   `alert`: Имя алерта.
*   `expr`: PromQL-выражение. Если оно истинно, алерт переходит в состояние `Pending`, а затем `Firing`.
*   `for`: Период времени, в течение которого выражение `expr` должно быть истинным, прежде чем алерт станет `Firing`. Это помогает отсеивать кратковременные сбои.
*   `labels`: Дополнительные метки для алерта. Используются для маршрутизации в Alertmanager.
*   `annotations`: Дополнительная информация (описание, ссылки на дашборды), которая отправляется в уведомлении. Поддерживают шаблоны.

**Пример:**
```yaml
- alert: HighCpuLoad
  expr: 100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High CPU load (instance {{ $labels.instance }})"
    description: "CPU load is > 80% on {{ $labels.instance }}."
```

---

## 3. Общая настройка и управление

### Структура файла правил

Оба типа правил определяются в YAML-файлах и объединяются в группы. Правила внутри одной группы выполняются последовательно с заданным интервалом.

```yaml
groups:
  - name: example_group
    interval: 30s
    rules:
    # Правило записи
    - record: job:up:avg
      expr: avg without(instance)(up{job="node_exporter"})
    # Правило оповещения
    - alert: ManyInstancesDown
      expr: job:up:avg{job="node_exporter"} < 0.5
      for: 1m
      labels:
        severity: critical
```

### Подключение и проверка

1.  **Добавление файла в `prometheus.yml`**:
    Укажите путь к файлу(ам) с правилами в основном конфигурационном файле Prometheus.
    ```yaml
    rule_files:
      - "rules.yml"
      - "rules/*.yml"
    ```

2.  **Проверка синтаксиса**:
    Используйте утилиту `promtool` для валидации файлов с правилами.
    ```bash
    promtool check rules /path/to/your/rules.yml
    ```

3.  **Применение настроек**:
    Перезагрузите конфигурацию Prometheus без перезапуска сервиса.
    ```bash
    systemctl reload prometheus.service
    # или, если Prometheus в Docker
    docker-compose exec prometheus kill -HUP 1 
    ```

4.  **Проверка в UI**:
    *   В веб-интерфейсе Prometheus (`http://<server_ip>:9090`) перейдите в раздел **Status -> Rules**. Вы должны увидеть загруженные правила.
    *   Активные алерты будут отображаться в разделе **Alerts**.

---

## 4. Практические примеры

### Пример Recording Rules

```yaml
# /etc/prometheus/rules.yml
groups:
- name: slurm-edu-example-node-exporter-rules
  rules:
  # Подсчет количества CPU на каждом узле.
  - record: instance:node_cpus:count
    expr: count(node_cpu_seconds_total{mode="idle"}) without (cpu,mode)

  # Общая утилизация CPU в процентах.
  - record: instance:node_cpu_utilization:ratio
    expr: sum(rate(node_cpu_seconds_total{mode!="idle"}[5m])) without (mode) / instance:node_cpus:count
```

### Пример Alerting Rules

```yaml
# /etc/prometheus/rules_alert.yml
groups:
- name: NodeExporterGroup
  rules:
  - alert: ExporterDown
    expr: up == 0
    for: 1m
    labels:
      severity: error
    annotations:
      summary: "Exporter down (instance {{ $labels.instance }})"
      description: "Prometheus exporter down\n  VALUE = {{ $value }}\n  LABELS: {{ $labels }}"

  - alert: HighCpuLoad
    expr: instance:node_cpu_utilization:ratio * 100 > 85
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High CPU load (instance {{ $labels.instance }})"
      description: "CPU load is > 85%\n  VALUE = {{ $value }}\n  LABELS: {{ $labels }}"
```

---
**Связанные темы:**
*   [[./overview.md]]
*   [[./alertmanager.md]]
*   [[./concepts/promql.md]]
*   [[./prometheus_configuration.md]]
*   [[./promtool_and_best_practices.md]]
