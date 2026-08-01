# Правила в Prometheus: Recording и Alerting

В [Prometheus](./overview.md) "правила" (rules) — это набор выражений на языке [PromQL](./concepts/promql/functions.md), которые периодически вычисляются на стороне сервера. Они позволяют автоматизировать создание новых временных рядов и генерацию оповещений.

> **См. также:** [Типы метрик](./concepts/metric_types/overview.md), [Алерты для типов метрик](./concepts/metric_types/alerts.md), [PromQL](./concepts/promql/functions.md), [Валидация через promtool](./promtool_and_best_practices.md).

## Определения

*   **Правила записи (Recording Rules)** — механизм предварительного вычисления сложных или тяжелых запросов. Результат сохраняется как новый набор временных рядов (виртуальные метрики), что ускоряет работу дашбордов и алертов.
*   **Правила оповещений (Alerting Rules)** — логические условия, определяющие состояние сбоя. Если выражение истинно в течение заданного времени, генерируется алерт.
*   **Группа правил (Rule Group)** — логическое объединение правил, которые выполняются последовательно внутри группы с единым интервалом вычисления.
*   **Дребезг алертов (Flapping)** — ситуация, когда алерт быстро переключается между состояниями `Firing` и `Resolved` из-за кратковременных колебаний метрики.

## Основные концепции

### Структура и параметры групп

Правила объединяются в группы в YAML-файлах. Группы позволяют изолировать выполнение правил и настраивать лимиты.

*   **Интервал вычисления (`interval`)**: Частота выполнения правил в группе. По умолчанию наследуется из `evaluation_interval` в `prometheus.yml`.
*   **Лимиты кардинальности**:
    *   `limit`: Максимальное количество временных рядов, которые могут быть созданы правилами записи в этой группе.
    *   `alert_limit`: Максимальное количество активных алертов, которые может сгенерировать группа.
*   **Последовательность**: Внутри группы правила выполняются строго одно за другим. Разные группы могут выполняться параллельно.

### Параметры Alerting Rules

| Параметр | Описание | Примечание |
| :--- | :--- | :--- |
| **`alert`** | Имя алерта | Должно быть уникальным и понятным. |
| **`expr`** | PromQL-выражение | Условие срабатывания. |
| **`for`** | Время ожидания | Алерт должен быть истинным в течение этого времени, чтобы перейти в `Firing`. |
| **`keep_firing_for`** | Удержание состояния | (v2.42+) Сохраняет алерт в `Firing`, даже если условие перестало выполняться (борьба с дребезгом). |
| **`labels`** | Дополнительные метки | Используются для маршрутизации и классификации (например, `severity`). |
| **`annotations`** | Метаданные | Описание, summary, ссылки на инструкции (runbooks). |

### Состояния алертов

1.  **Inactive**: Условие не выполняется.
2.  **Pending**: Условие истинно, но время `for` еще не истекло.
3.  **Firing**: Время `for` истекло, алерт активен и отправлен в Alertmanager.
4.  **Resolved**: Условие перестало выполняться (после учета `keep_firing_for`).

## Управление и тестирование

### Валидация и применение

Для проверки синтаксиса используется утилита `promtool`.

```bash
# Проверка синтаксиса правил
promtool check rules rules.yml
# → SUCCESS: number of rules found

# Применение изменений (Hot Reload)
curl -X POST http://localhost:9090/-/reload
```

### Модульное тестирование (Unit Testing)

Prometheus позволяет тестировать логику правил без запуска сервера. Для этого создается тестовый файл (обычно `test.yml`), где описываются входные данные и ожидаемые результаты.

```yaml
# test.yml
rule_files:
  - rules.yml

evaluation_interval: 1m

tests:
  - interval: 1m
    input_series:
      - series: 'up{job="node"}'
        values: '0 0 0' # Экспортер упал на 3 минуты
    alert_rule_test:
      - eval_time: 3m
        alertname: InstanceDown
        exp_alerts:
          - labels:
              severity: critical
              instance: localhost:9100
            annotations:
              summary: "Instance down"
```

Запуск теста:
```bash
promtool test rules test.yml
# → Unit Testing: rules.yml  PASS
```

## Практические сценарии

### Сценарий 1: Оптимизация тяжелого дашборда (Recording Rule)

Если дашборд вычисляет утилизацию CPU по 1000 серверам за 30 дней, запрос будет медленным. Создаем правило записи для агрегации данных.

```yaml
groups:
  - name: cpu-usage-optimization
    rules:
      - record: job:node_cpu_utilization:avg_rate5m
        expr: avg by (job) (rate(node_cpu_seconds_total{mode!="idle"}[5m]))
```
*В дашборде теперь достаточно запросить `job:node_cpu_utilization:avg_rate5m`.*

### Сценарий 2: Борьба с дребезгом сетевых алертов

Для нестабильных сетевых соединений используем `keep_firing_for`, чтобы не спамить уведомлениями при кратковременном восстановлении связи.

```yaml
groups:
  - name: network-alerts
    rules:
      - alert: NetworkUnstable
        expr: rate(network_errors_total[2m]) > 10
        for: 5m
        keep_firing_for: 10m # Алерт не закроется сразу, если ошибки пропадут на минуту
        labels:
          severity: warning
        annotations:
          summary: "Network instability on {{ $labels.instance }}"
```

## Дополнительная информация

### Рекомендации по именованию (Best Practices)

Для Recording Rules настоятельно рекомендуется формат `level:metric:operations`:
*   `instance:node_cpu_utilization:ratio` — утилизация на уровне инстанса.
*   `job:http_requests:rate5m` — темп запросов на уровне задания (job).

### SSoT и связанные ресурсы

*   Все алерты должны быть **actionable** (требовать конкретного действия).
*   Для настройки уведомлений (Email, Slack) см. [Alertmanager](./alertmanager.md).
*   Примеры алертов для Counter/Gauge/Histogram приведены в [Алерты для типов метрик](./concepts/metric_types/alerts.md).
*   [Prometheus: promtool и лучшие практики](./promtool_and_best_practices.md) — общие рекомендации по эксплуатации.
