# Custom Dashboards в OpenSearch Dashboards для Wazuh

## Определения

**OpenSearch Dashboards** — визуальный интерфейс для анализа данных OpenSearch (включая Wazuh Indexer). В **Wazuh 5.0** Dashboard интегрирован с нативными индексами `wazuh-events-*` и `wazuh-alerts-*`.

**Saved Object** — сохранённый запрос, визуализация или дашборд в OpenSearch Dashboards. Может быть экспортирован/импортирован через API или UI.

**Visualization** — графическое представление данных: bar chart, pie chart, metric, data table, histogram, line chart.

**Lens** — современный конструктор визуализаций в OpenSearch Dashboards с drag-and-drop интерфейсом и интеллектуальными рекомендациями.

**Index Pattern** — шаблон индекса для запросов (e.g., `wazuh-events-*`). Определяет доступные поля и их типы.

## Основные концепции

### Структура Wazuh-дашбордов

```
Wazuh Overview Dashboard
├── Agent Status (stat: active/disconnected/pending)
├── EPS (timeseries: events per second)
├── Alert Distribution by Level (pie: level distribution)
├── Top 10 Alert Rules (bar: rule descriptions)
├── Alerts by Agent (bar: alerts per agent)
├── MITRE ATT&CK Heatmap (table: tactics/techniques)
├── SCA Compliance Score (gauge: pass/fail ratio)
├── FIM Changes (table: recent file changes)
└── Vulnerability Findings (bar: CVE by severity)
```

### Ключевые индексы

| Индекс | Содержимое | Использование |
|:---|:---|:---|
| `wazuh-events-*` | Все события (Full Visibility) | Threat hunting, отладка |
| `wazuh-alerts-*` | Только алерты/finding'и | Мониторинг, дашборды |
| `wazuh-sca-*` | Результаты SCA | Compliance |
| `wazuh-vulnerability-*` | Уязвимости | Vulnerability management |
| `wazuh-fim-*` | События FIM | File integrity |

## Практические сценарии

### 1. Ключевые KQL-запросы для дашбордов

```kql
# Все критические алерты (level >= 12)
rule.level: >= 12

# Brute-force SSH за 24 часа
rule.id: (5716 OR 5720) AND rule.level: >= 10

# Malware detections
rule.mitre.id: (T1059 OR T1055 OR T1003 OR T1021)

# Active Response events
rule.group: active_response

# Agent disconnected
status: disconnected

# SCA failed checks
data.sca.check.result: fail

# FIM critical changes
syscheck.event: modified AND syscheck.path: (/etc/shadow OR /etc/sudoers OR /etc/passwd)

# Vulnerability critical
data.vulnerability.severity: Critical

# Windows: Suspicious PowerShell
data.win.system.channel: Microsoft-Windows-PowerShell/Operational AND data.win.eventdata.scriptBlockText: (FromBase64String OR Invoke-Expression)

# Linux: Sudo usage
data.win.system.channel: sudo
```

### 2. API: создание дашборда

```python
#!/usr/bin/env python3
"""Создание Wazuh Overview Dashboard через API."""
import requests
import json

API = "https://localhost:5601"  # OpenSearch Dashboards
INDEX_PATTERN = "wazuh-events-*"

# Авторизация (Basic Auth для Dashboards)
auth = ("admin", "admin")

# 1. Создание Index Pattern
index_pattern = {
    "attributes": {
        "title": INDEX_PATTERN,
        "timeFieldName": "timestamp",
        "fields": "[]"
    }
}

resp = requests.post(
    f"{API}/api/saved_objects/index-pattern/{INDEX_PATTERN}",
    headers={
        "Content-Type": "application/json",
        "osd-xsrf": "true"
    },
    json=index_pattern,
    auth=auth,
    verify=False
)
print(f"Index Pattern: {resp.status_code}")

# 2. Создание визуализации: Active Agents
vis_active_agents = {
    "attributes": {
        "title": "Active Agents",
        "visState": json.dumps({
            "title": "Active Agents",
            "type": "metric",
            "aggs": [{
                "id": "1",
                "enabled": True,
                "type": "filter",
                "params": {"query": "status:active"},
                "schema": "metric"
            }],
            "params": {
                "addTooltip": True,
                "addLegend": False
            }
        }),
        "uiStateJSON": "{}",
        "kibanaSavedObjectMeta": {
            "searchSourceJSON": json.dumps({
                "query": {"query": "", "language": "kuery"},
                "filter": []
            })
        }
    },
    "type": "visualization"
}

resp = requests.post(
    f"{API}/api/saved_objects/visualization/active-agents",
    headers={"Content-Type": "application/json", "osd-xsrf": "true"},
    json=vis_active_agents,
    auth=auth,
    verify=False
)
print(f"Visualization: {resp.status_code}")

# 3. Создание дашборда
dashboard = {
    "attributes": {
        "title": "Wazuh Security Overview",
        "description": "Overview of Wazuh SIEM metrics and alerts",
        "panelsJSON": json.dumps([
            {
                "version": "5.0.0",
                "type": "visualization",
                "gridData": {"x": 0, "y": 0, "w": 6, "h": 4},
                "panelIndex": "1",
                "embeddableConfig": {},
                "panelRefName": "panel_1"
            }
        ]),
        "optionsJSON": json.dumps({
            "hidePanelTitles": False,
            "useMargins": True
        }),
        "timeRestore": True,
        "timeTo": "now",
        "timeFrom": "now-24h",
        "refreshInterval": {"pause": False, "value": 30000}
    },
    "type": "dashboard"
}

resp = requests.post(
    f"{API}/api/saved_objects/dashboard/wazuh-overview",
    headers={"Content-Type": "application/json", "osd-xsrf": "true"},
    json=dashboard,
    auth=auth,
    verify=False
)
print(f"Dashboard: {resp.status_code}")
```

### 3. Экспорт/импорт дашбордов

```bash
# Экспорт всех Wazuh-дашбордов
curl -sk "https://localhost:5601/api/saved_objects/_export" \
  -H "osd-xsrf: true" \
  -H "Content-Type: application/json" \
  -d '{
    "type": ["dashboard", "visualization", "search"],
    "includeReferences": true
  }' -u admin:admin -o wazuh_dashboards.ndjson

# Импорт
curl -sk "https://localhost:5601/api/saved_objects/_import" \
  -H "osd-xsrf: true" \
  -F "file=@wazuh_dashboards.ndjson" \
  -u admin:admin
```

### 4. Топ-10 правил по количеству алертов (Data Table)

```json
{
  "title": "Top 10 Alert Rules",
  "type": "visualization",
  "visState": {
    "title": "Top 10 Alert Rules",
    "type": "table",
    "aggs": [
      {
        "id": "1",
        "type": "terms",
        "params": {
          "field": "rule.description.keyword",
          "size": 10,
          "order": "desc",
          "orderBy": "2"
        },
        "schema": "bucket"
      },
      {
        "id": "2",
        "type": "count",
        "schema": "metric"
      }
    ],
    "params": {
      "perPage": 20,
      "showPartialRows": false,
      "showMetricsAtAllLevels": false,
      "showTotal": true,
      "totalFunc": "sum"
    }
  }
}
```

### 5. MITRE ATT&CK Heatmap

```json
{
  "title": "MITRE ATT&CK Tactics",
  "type": "visualization",
  "visState": {
    "title": "MITRE ATT&CK Tactics",
    "type": "heatmap",
    "aggs": [
      {
        "id": "1",
        "type": "terms",
        "params": { "field": "rule.mitre.tactic.keyword", "size": 14 },
        "schema": "segment"
      },
      {
        "id": "2",
        "type": "terms",
        "params": { "field": "rule.mitre.id.keyword", "size": 50 },
        "schema": "group"
      },
      {
        "id": "3",
        "type": "count",
        "schema": "metric"
      }
    ],
    "params": {
      "addTooltip": true,
      "colorsNumber": 5,
      "colorSchema": "Green to Red",
      " setColorRange": false,
      "colorsRange": [],
      "invertColors": false,
      "valueTemplate": ""
    }
  }
}
```

### 6. Сводка по агентам (Metric + Filter)

```json
{
  "title": "Agent Status Summary",
  "type": "visualization",
  "visState": {
    "title": "Agent Status",
    "type": "metric",
    "aggs": [
      {
        "id": "1",
        "type": "filter",
        "params": { "query": "status:active" },
        "schema": "metric"
      },
      {
        "id": "2",
        "type": "filter",
        "params": { "query": "status:disconnected" },
        "schema": "metric"
      },
      {
        "id": "3",
        "type": "filter",
        "params": { "query": "status:pending" },
        "schema": "metric"
      }
    ],
    "params": {
      "addTooltip": true,
      "addLegend": true,
      "legendPosition": "right"
    }
  }
}
```

### 7. EKS/Dashboard JSON: полный Overview Dashboard

```bash
# Импорт готового дашборда
curl -sk "https://localhost:5601/api/saved_objects/_import" \
  -H "osd-xsrf: true" \
  -H "Content-Type: application/ndjson" \
  --data-binary @wazuh_overview_dashboard.ndjson \
  -u admin:admin
```

## Дополнительная информация

### Best Practices

1. **Index Pattern**: всегда создавайте index pattern перед дашбордом.
2. **Time Filter**: настройте default time range (now-24h).
3. **Refresh**: автоматическое обновление каждые 30–60 секунд.
4. **Permissions**: разделяйте дашборды по ролям (admin, viewer, analyst).
5. **Version Control**: экспортируйте дашборды в Git для отслеживания изменений.
6. **Performance**: не используйте wildcard queries в агрегациях.

### Troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| **No data** | Index pattern не создан | Создайте `wazuh-events-*` |
| **Permission denied** | RBAC ограничивает | Проверьте roles пользователя |
| **Slow dashboard** | Слишком много агрегаций | Уменьшите time range, добавьте filters |
| **Missing fields** | Старый agent version | Обновите агента до 5.x |

### См. также
- [Health Monitoring](./wazuh-health-monitoring.md) — Golden Signals дашборд.
- [Performance Tuning](./wazuh-performance-tuning.md) — оптимизация запросов.
- [Prometheus/Grafana](./wazuh-prometheus-grafana.md) — альтернативная визуализация.
