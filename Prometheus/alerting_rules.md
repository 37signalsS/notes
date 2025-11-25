# Настройка Alert Rules

## Общие сведения

Alert Rules очень похожи на [Record Rules](./concepts/recording_rules.md), рассмотренные в предыдущей главе. Они располагаются в тех же группах, что и rules. Допускается комбинировать alert и record rules в одном файле. Но они также могут быть вынесены и в отдельный файл.

Пример:
```yaml
groups:
  - name: node_rules
    rules:
    - record: job:up:avg
      expr: avg without(instance)(up{job="node_exporter"})
    - alert: ManyInstancesDown
      expr: job:up:avg{job="node_exporter"} < 0.5
```

## Синтаксис Alert Rules 

Правила уведомлений также формируются по группам:

```yaml
groups:
  - name: example
    rules:
    - alert: ManyInstancesDown
      for: 5m
      expr: avg without(instance)(up{job="node_exporter"}) * 100 < 50
      labels:
        severity: warning
      annotations:
        summary: 'More than half of instances are down.'
        dashboard: http://some.grafana:3000/dashboard/db/prometheus
```

-   **`name`**: Имя для группы правил. Оно должно быть уникальным и является обязательным.
-   **`alert`**: Имя алерта.
-   **`for`**: Задержка с момента выполнения условий для срабатывания до начала обработки. Пока условие `for` не выполнено, данные в Alertmanager не отправляются.
-   **`expr`**: Задает условие, и если оно истинное, то начинается обработка alert.
-   **`labels`**: Задает произвольный набор labels для alert. **NB!** alert labels никак не связаны с metrics labels и используются для обработки алертов на стороне Alertmanager.
-   **`annotations`**: Набор дополнительных произвольных меток (ключ: значение), которые передаются вместе с алертом. В отличие от меток, которые передаются в `labels`, метки из `annotations` не используются для группировки и маршрутизации уведомлений.

`alert annotation` поддерживает шаблоны GO, а также PromQL запросы. Например, можно добавить список недоступных `node_exporter`:

```yaml
description: >
  Down instances: {{ range query "up{job=\"node\"} == 0" }} 
    {{ .Labels.instance }}
  {{ end }}
```

## Добавление правил уведомлений

*Этот раздел представляет собой практическое руководство, которое может быть выделено в отдельный документ или оставлено здесь как пример.*

Практика выполняется на monitoring сервере, доступ к нему осуществляется по IP адресу и выполняется с root привилегиями.

1.  **Сохраняем правила в файл `rules_alert.yml`:**
    ```bash
    cat <<EOF > /etc/prometheus/rules_alert.yml
groups:
- name: PrometheusGroup
  rules:
  - alert: PrometheusConfigurationReload
    expr: prometheus_config_last_reload_successful != 1
    for: 1m
    labels:
      severity: critical
      service: prom
    annotations:
      summary: "Prometheus configuration reload (instance {{ \$labels.instance }})"
      description: "Prometheus configuration reload error\n  VALUE = {{ \$value }}\n  LABELS: {{ \$labels }}"

- name: NodeExporterGroup
  rules:
  - alert: ExporterDown
    expr: up == 0
    for: 1m
    labels:
      severity: error
      service: prom
    annotations:
      summary: "Exporter down (instance {{ \$labels.instance }})"
      description: "Prometheus exporter down\n  VALUE = {{ \$value }}\n  LABELS: {{ \$labels }}"

  - alert: HighCpuLoad
    expr: 100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High CPU load (instance {{ \$labels.instance }})"
      description: "CPU load is > 80%\n  VALUE = {{ \$value }}\n  LABELS: {{ \$labels }}"

  - alert: SystemdServiceCrashed
    expr: node_systemd_unit_state{state="failed"} == 1
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "SystemD service crashed (instance {{ \$labels.instance }})"
      description: "SystemD service crashed\n  VALUE = {{ \$value }}\n  LABELS: {{ \$labels }}"
EOF
    ```

2.  **Проверяем правила:**
    Для проверки правил также используется утилита `promtool`.
    ```bash
    promtool check rules /etc/prometheus/rules_alert.yml
    ```

3.  **Добавляем данные о Rules в основной конфигурационный файл Prometheus:**
    Откройте `/etc/prometheus/prometheus.yml` и после `rule_files` добавьте `"rules_*.yml"`.
    ```yaml
    rule_files:
      - rules.yml
      - "rules_*.yml"
    ```

4.  **Проверяем корректность:**
    ```bash
    promtool check config /etc/prometheus/prometheus.yml 
    ```

5.  **Применяем настройки:**
    ```bash
    systemctl reload prometheus.service
    ```
    > **NB!** `reload` предпочтительнее `restart`, так как в случае ошибки в конфигурации сервис не остановится.

6.  **Проверяем в UI:**
    *   Откройте UI Prometheus, раздел **Rules** (`http://<server_ip>:9090/rules`). Должны отображаться новые правила.
    *   Перейдите в раздел **Alerts** (`http://<server_ip>:9090/alerts`). На этой странице отображается состояние всех правил.

7.  **Тестирование:**
    *   Отключите `node_exporter`:
        ```bash
        systemctl stop node_exporter.service
        ```
    *   В разделе **Alerts** одно из правил должно перейти в состояние `PENDING`, а через время, указанное в `for`, в `FIRING`.

---
**Связанные темы:**
*   [[./alertmanager_overview.md]]
*   [[./concepts/recording_rules.md]]
*   [[./prometheus_configuration.md]]
