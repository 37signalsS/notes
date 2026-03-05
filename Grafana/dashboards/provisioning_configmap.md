# Grafana: Провижионинг дашбордов через ConfigMap

## Механизм Grafana Sidecar для обнаружения дашбордов

В контексте `kube-prometheus-stack` (особенно при развертывании через Rancher) используется механизм **Grafana Sidecar** для автоматического обнаружения и загрузки дашбордов.

### Назначение

Вместо того чтобы хранить дашборды непосредственно в файловой системе Grafana (которая может быть эфемерной), `sidecar`-контейнер, запущенный в том же поде, что и Grafana, сканирует указанные Kubernetes `ConfigMap` или `Secret` ресурсы в различных `namespaces`.

### Принцип работы

`Sidecar` постоянно отслеживает изменения в `ConfigMap` с определенными метками (или в указанных `namespaces`) и при обнаружении новых или измененных дашбордов автоматически импортирует их в Grafana.

### Директория `Graphana Cattle Dashboards`

Для системных дашбордов, поставляемых Rancher, используется предопределенная директория в файловой системе Grafana (смонтированная из `ConfigMap` или `Secret`), откуда `sidecar` загружает их. Для кастомных дашбордов `sidecar` может быть настроен на поиск в других `namespaces`.

### Преимущества

Этот подход упрощает управление дашбордами, позволяет версионировать их в Git и централизованно развертывать, не требуя ручных действий по импорту через UI Grafana. Он также обеспечивает большую гибкость в организации дашбордов по `namespaces` и проектам.

---

## Сценарий 6: Провижионинг пользовательских дашбордов через ConfigMap

В Rancher, когда используется общий экземпляр Grafana, пользователи не могут напрямую создавать и сохранять дашборды через UI. Вместо этого они должны предоставлять свои дашборды в виде Kubernetes `ConfigMap`.

### 1. Создайте дашборд в своей Grafana и экспортируйте JSON

Используйте локальный или тестовый экземпляр Grafana для создания нужного дашборда. Экспортируйте его в формате JSON.

### 2. Создайте `ConfigMap` с JSON дашборда

Оберните экспортированный JSON дашборда в Kubernetes `ConfigMap`. **Ключевым моментом является добавление метки `grafana-dashboard: "1"`**, которая будет использоваться Grafana Sidecar для обнаружения.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-app-dashboard
  namespace: test-app # Разверните в namespace вашего приложения
  labels:
    grafana-dashboard: "1" # Обязательная метка для обнаружения Grafana Sidecar
data:
  my-app-dashboard.json: |-
    {
      "annotations": {
        "list": [
          {
            "builtIn": 1,
            "datasource": "-- Grafana --",
            "enable": true,
            "hide": true,
            "iconColor": "rgba(0, 211, 255, 1)",
            "name": "Annotations & Alerts",
            "type": "dashboard"
          }
        ]
      },
      "editable": true,
      "gnetId": null,
      "graphTooltip": 1,
      "id": null,
      "links": [],
      "panels": [
        {
          "datasource": "Prometheus",
          "fieldConfig": {
            "defaults": {
              "custom": {},
              "mappings": [],
              "thresholds": {
                "mode": "absolute",
                "steps": [
                  {
                    "color": "green",
                    "value": null
                  },
                  {
                    "color": "red",
                    "value": 80
                  }
                ]
              }
            },
            "overrides": []
          },
          "gridPos": {
            "h": 9,
            "w": 12,
            "x": 0,
            "y": 0
          },
          "id": 2,
          "options": {
            "colorMode": "value",
            "graphMode": "area",
            "justifyMode": "auto",
            "orientation": "auto",
            "reduceOptions": {
              "calcs": [
                "lastNotNull"
              ]
            },
            "textMode": "auto"
          },
          "pluginVsersion": "8.3.3",
          "targets": [
            {
              "datasource": "Prometheus",
              "expr": "api_http_requests_total{job=\"test-app\",namespace=\"test-app\"}",
              "interval": "",
              "legendFormat": "{{pod}}",
              "refId": "A"
            }
          ],
          "title": "Application Requests Total",
          "type": "stat"
        }
      ],
      "schemaVersion": 30,
      "style": "dark",
      "tags": [],
      "templating": {
        "list": []
      },
      "time": {
        "from": "now-5m",
        "to": "now"
      },
      "timepicker": {},
      "timezone": "",
      "title": "Test Application Dashboard",
      "type": "dashboard",
      "uid": "test-app-dashboard",
      "version": 1
    }
```

### 3. Разверните `ConfigMap`

Примените этот `ConfigMap` в `namespace` вашего приложения (например, `test-app`).

### 4. Проверьте в Grafana

Дашборд появится в разделе "Manage" в общей Grafana Rancher. Grafana Sidecar автоматически импортирует его.

> **Важно**: Для того чтобы Grafana Sidecar мог обнаруживать дашборды в других `namespaces`, необходимо убедиться, что соответствующая настройка включена в `values.yaml` Helm-чарта `kube-prometheus-stack` при его развертывании (это, как правило, задача администратора кластера).

---

## Хранение в системе контроля версий

Хранение JSON-моделей дашбордов в системе контроля версий (например, Git) является лучшей практикой. Это позволяет отслеживать изменения, откатываться к предыдущим версиям и интегрировать дашборды в CI/CD пайплайны.

---

## Ссылки

- **[Определения и концепции](./definitions_and_concepts.md)** — базовая информация
- **[Практические сценарии](./practical_scenarios.md)** — создание и настройка
- **[Provisioning](../grafana_provisioning.md)** — управление дашбордами как код
