# Blackbox Exporter — Grafana-дашборды

## Определения

**Дашборд Blackbox Exporter** — визуальная панель в Grafana, отображающая результаты синтетических проверок доступности, латентности и SSL-сертификатов эндпоинтов. Дашборд строится на метриках, генерируемых Blackbox Exporter (`probe_success`, `probe_duration_seconds`, `probe_ssl_earliest_cert_expiry` и др.) и позволяет в реальном времени отслеживать здоровье сервисов с точки зрения внешнего клиента.

*   **Переменная (Variable)** — параметр дашборда, позволяющий динамически фильтровать данные по модулю, цели или окружению без редактирования панелей.
*   **Threshold (порог)** — цветовое ограничение на панели, визуально меняющее цвет индикатора при превышении заданного значения (зелёный/жёлтый/красный).
*   **Annotation** — маркер на временной шкале, отмечающий событие (деплой, инцидент, перезагрузку) для контекстного анализа изменения метрик.
*   **Stat Panel** — компактная панель, отображающая одно текущее значение с цветовым индикатором (идеальна для总体 состояния доступности).

**Связанные документы:**
*   [Обзор и концепции](./blackbox_exporter_overview.md)
*   [Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md)
*   [Конфигурация модулей](./blackbox_exporter_modules_configuration.md)
*   [Grafana: Дашборды](../../../Grafana/grafana-dashboards.md)

## Основные концепции

### Архитектура дашборда

Рекомендуемая структура дашборда для Blackbox Exporter организована в четыре логических уровня:

```
┌─────────────────────────────────────────────────────────┐
│  L1: Обзор (Onepager)                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ Availability│ │ Avg Latency│ │ SSL Days │ │ Active  │   │
│  │   (Stat)    │ │  (Stat)   │ │ (Stat)  │ │ Probes  │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
├─────────────────────────────────────────────────────────┤
│  L2: Детализация по целям                               │
│  ┌─────────────────────────────────────────────────────┐│
│  │ Таблица: target | status | latency | ssl_expiry    ││
│  └─────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────┤
│  L3: Временные ряды                                     │
│  ┌──────────────────────┐ ┌──────────────────────┐     │
│  │ probe_success (time) │ │ probe_duration (time)│     │
│  └──────────────────────┘ └──────────────────────┘     │
├─────────────────────────────────────────────────────────┤
│  L4: Диагностика фаз                                    │
│  ┌─────────────────────────────────────────────────────┐│
│  │ HTTP Phases: resolve | connect | tls | processing  ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

### Переменные дашборда

Для интерактивной навигации рекомендуется определить следующие переменные:

| Переменная | Тип | Источник данных | Назначение |
|:---|:---|:---|:---|
| `$instance` | Query | `label_values(up{job="blackbox"}, instance)` | Выбор инстанса Blackbox Exporter |
| `$module` | Query | `label_values(probe_success, module)` | Фильтрация по типу проверки |
| `$target` | Query | `label_values(probe_success{instance=~"$instance"}, target)` | Выбор конкретной цели |
| `$env` | Custom | `prod,staging,dev` | Фильтрация по окружению |

**Пример query для переменной `$target`:**
```promql
label_values(probe_success{instance=~"$instance", module=~"$module"}, target)
```

### Цветовые пороги (Thresholds)

Стандартная конфигурация порогов для ключевых метрик:

| Метрика | Зелёный | Жёлтый | Красный | Описание |
|:---|:---|:---|:---|:---|
| `probe_success` | = 1 | — | = 0 | Доступность цели |
| `probe_duration_seconds` | < 2s | 2–5s | > 5s | Общее время ответа |
| `probe_ssl_days_remaining` | > 30 | 7–30 | < 7 | Дней до истечения SSL |
| `probe_http_status_code` | 2xx | 3xx/4xx | 5xx | HTTP-код ответа |

## Практические сценарии

### 1. Базовый дашборд: Обзор доступности

**Панель 1: Доля доступных эндпоинтов (Stat)**

```promql
# Query (Stat panel)
count(avg_over_time(probe_success[5m]) == 1) or vector(0)
# → Количество целей с доступностью 100% за 5 минут
```

Настройки панели:
- Тип: `Stat`
- Цветовой режим: `Background`
- Пороги: `< 90` (красный), `90–99` (жёлтый), `> 99` (зелёный)
- Формат: `Percent (0-100)`

**Панель 2: Средняя латентность (Stat)**

```promql
# Query
avg(probe_duration_seconds{module=~"$module"})
```

Настройки:
- Тип: `Stat`
- Единицы: `seconds (s)`
- Пороги: `< 1` (зелёный), `1–3` (жёлтый), `> 3` (красный)

**Панель 3: SSL-сертификаты (Stat)**

```promql
# Query — минимальное количество дней до истечения
min(
  (probe_ssl_earliest_cert_expiry - time()) / 86400
)
```

Настройки:
- Тип: `Stat`
- Единицы: `days`
- Пороги: `< 7` (красный), `7–30` (жёлтый), `> 30` (зелёный)

**Панель 4: Количество активных проверок (Stat)**

```promql
# Query
count(probe_success)
```

### 2. Таблица детализации по целям

**Панель: Таблица состояний (Table)**

```promql
# Query A — Статус и латентность
probe_success{instance=~"$instance", module=~"$module"}
  * on(target, instance, module) group_left()
  probe_duration_seconds{instance=~"$instance", module=~"$module"}

# Query B — SSL-дней до истечения
(probe_ssl_earliest_cert_expiry{instance=~"$instance"} - time()) / 86400

# Query C — HTTP-код
probe_http_status_code{instance=~"$instance", module=~"$module"}
```

Настройки:
- Тип: `Table`
- Колонки: `target` (link), `module`, `probe_success` (value to text: 1="UP", 0="DOWN"), `probe_duration_seconds` (formatted), `ssl_days` (thresholds), `http_status_code`
- Transform: `Organize fields by name` — скрыть технические колонки

### 3. Временные ряды: Доступность и латентность

**Панель: probe_success во времени (Time series)**

```promql
# Query
probe_success{instance=~"$instance", module=~"$module", target=~"$target"}
```

Настройки:
- Тип: `Time series`
- Y-ось: `0–1` (binary), отображение как `State timeline`
- Legend: `{{ target }} ({{ module }})`

**Панель: probe_duration_seconds по фазам (Time series)**

```promql
# Query A — resolve
probe_http_duration_seconds{instance=~"$instance", target=~"$target", phase="resolve"}

# Query B — connect
probe_http_duration_seconds{instance=~"$instance", target=~"$target", phase="connect"}

# Query C — tls
probe_http_duration_seconds{instance=~"$instance", target=~"$target", phase="tls"}

# Query D — processing (TTFB)
probe_http_duration_seconds{instance=~"$instance", target=~"$target", phase="processing"}

# Query E — transfer
probe_http_duration_seconds{instance=~"$instance", target=~"$target", phase="transfer"}
```

Настройки:
- Тип: `Time series`
- Стек: `Normal` (каждая фаза — отдельный слой)
- Legend: `{{ phase }}`
- Единицы: `seconds (s)`

### 4. SSL-мониторинг

**Панель: Дней до истечения сертификатов (Bar gauge)**

```promql
# Query
(probe_ssl_earliest_cert_expiry{instance=~"$instance"} - time()) / 86400
```

Настройки:
- Тип: `Bar gauge`
- Legend: `{{ target }}`
- Пороги: `< 7` (красный), `7–30` (жёлтый), `> 30` (зелёный)
- Единицы: `days`

**Панель: Версия TLS (Table)**

```promql
# Query
probe_tls_version_info{instance=~"$instance"}
```

Настройки:
- Тип: `Table`
- Колонки: `target`, `version` (TLS 1.2 / TLS 1.3)

### 5. Аннотации для корреляции событий

Добавьте аннотации из Prometheus для отображения деплоев и инцидентов:

```yaml
# В provisioning/dashboards/annotations.yml
apiVersion: 1
annotations:
  - name: Deployments
    datasource: Prometheus
    query: |
      kube_deployment_status_replicas_available
  - name: Blackbox Alerts
    datasource: Prometheus
    query: |
      ALERTS{alertname=~"Blackbox.*"}
```

### 6. Импорт готового дашборда

Grafana Community предоставляет несколько готовых дашбордов:

| ID | Название | Описание |
|:---|:---|:---|
| `7587` | Blackbox Exporter | Базовый дашборд с HTTP/TCP/DNS/ICMP панелями |
| `14978` | Blackbox Exporter Overview | Расширенный с SSL и фазами HTTP |
| `18691` | Blackbox SSL Certificate Monitoring | Фокус на SSL-сертификатах |

**Импорт через UI:**
1. Dashboards → Import
2. Введите ID дашборда (например, `7587`)
3. Выберите источник данных Prometheus
4. Нажмите Import

**Импорт через API:**
```bash
curl -X POST http://localhost:3000/api/dashboards/import \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{
    "dashboard": <JSON-модель>,
    "overwrite": true,
    "inputs": [{"name": "DS_PROMETHEUS", "type": "datasource", "pluginId": "prometheus", "value": "Prometheus"}]
  }'
```

### 7. Provisioning дашборда через ConfigMap (Kubernetes)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: blackbox-grafana-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"  # sidecar подхватит автоматически
data:
  blackbox-overview.json: |
    {
      "uid": "blackbox-overview",
      "title": "Blackbox Exporter — Обзор",
      "tags": ["blackbox", "synthetic", "monitoring"],
      "timezone": "browser",
      "refresh": "30s",
      "time": {"from": "now-6h", "to": "now"},
      "templating": {
        "list": [
          {
            "name": "instance",
            "type": "query",
            "query": "label_values(up{job=\"blackbox\"}, instance)",
            "refresh": 2,
            "current": {"text": "All", "value": "$__all"}
          },
          {
            "name": "module",
            "type": "query",
            "query": "label_values(probe_success, module)",
            "refresh": 2,
            "current": {"text": "All", "value": "$__all"}
          }
        ]
      },
      "panels": []
    }
```

**Helm-values для Kube-Prometheus-Stack:**
```yaml
grafana:
  sidecar:
    dashboards:
      enabled: true
      label: grafana_dashboard
      folderAnnotation: grafana_folder
      provider:
        foldersFromFilesStructure: true
```

### 8. Оптимизация производительности дашборда

| Проблема | Решение |
|:---|:---|
| Медленная загрузка при >100 targets | Используйте переменную `$target` с `multi=true` и `includeAll=true` |
| Много серий на графике | Примените `Legend: {{ target }}` и `Max series limit: 20` |
| Нагрузка на Prometheus | Создайте Recording Rules для `avg_over_time(probe_success[5m])` |
| Панели не обновляются | Проверьте `refresh` интервал дашборда (рекомендуется `30s`) |

## Дополнительная информация

### Recording Rules для дашбордов

Для ускорения работы дашбордов рекомендуется预先 вычислять тяжелые запросы:

```yaml
groups:
  - name: blackbox_dashboard_rules
    interval: 30s
    rules:
      - record: blackbox:probe_success:ratio_rate5m
        expr: avg_over_time(probe_success[5m])

      - record: blackbox:probe_duration:p95_1h
        expr: quantile_over_time(0.95, probe_duration_seconds[1h])

      - record: blackbox:ssl_days_remaining
        expr: (probe_ssl_earliest_cert_expiry - time()) / 86400

      - record: blackbox:probe_success:ratio_by_module
        expr: avg by (module) (avg_over_time(probe_success[5m]))
```

### Ссылки

- [Grafana: Дашборды](../../../Grafana/grafana-dashboards.md) — общие концепции дашбордов
- [Grafana: Provisioning](../../../Grafana/grafana_provisioning.md) — автоматический деплой дашбордов
- [Grafana: Templating](../../../Grafana/grafana_templating.md) — создание переменных

**См. также:**
*   [Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md)
*   [Обзор и концепции](./blackbox_exporter_overview.md)
