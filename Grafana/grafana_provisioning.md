# Grafana: Провиженинг (Configuration as Code)

Провиженинг в Grafana позволяет управлять конфигурациями (источниками данных, дашбордами, плагинами) как кодом, обеспечивая автоматизацию, версионирование и согласованность между различными экземплярами Grafana. Это особенно актуально в средах Kubernetes, где Grafana часто развертывается с использованием Helm.

## Принципы провиженинга

Grafana поддерживает провиженинг через конфигурационные файлы (например, JSON для дашбордов, YAML для источников данных), которые могут быть расположены в специальной директории `provisioning`. При запуске Grafana автоматически подхватывает эти файлы и применяет описанные в них конфигурации, создавая необходимые дашборды и источники данных в системе. Это позволяет инициализировать Grafana с предустановленными конфигурациями.

В контексте Kubernetes и Helm, эти конфигурационные файлы часто встраиваются в Helm `values.yaml` и развертываются вместе с Grafana. Также для управления конфигурациями Grafana как кодом активно используются инструменты Infrastructure as Code, такие как Terraform или Pulumi, которые позволяют менеджить дашборды и источники данных, изменяя `values` и распространяя конфигурации через CI/CD пайплайны.

## Провиженинг источников данных (Data Sources)

Источники данных могут быть определены в файле `values.yaml` Helm-чарта Grafana. Это позволяет автоматически создавать и настраивать источники данных при развертывании Grafana.

Пример конфигурации источника данных Prometheus через `values.yaml`:

```yaml
grafana:
  datasources:
    datasources.yaml:
      apiVersion: 1
      datasources:
      - name: Prometheus1
        type: prometheus
        url: http://prometheus-server.monitoring.svc.cluster.local
        access: proxy
        isDefault: true
        version: 1
        editable: false
```

**Важные замечания по провиженингу источников данных:**
*   Источники данных, созданные вручную через UI Grafana, сохраняются даже после провиженинга новых источников данных.
*   Провизионированный источник данных может переопределить "defaultность" другого источника данных, если в его конфигурации `isDefault` установлено в `true`.
*   Источники данных, добавленные через провиженинг, не могут быть изменены через UI Grafana, о чем обычно сообщается в интерфейсе ("Please contact your server admin to update this data source").

**Пояснения:**
*   `name`: Уникальное имя источника данных.
*   `type`: Тип источника данных (например, `prometheus`, `loki`, `influxdb`).
*   `url`: URL-адрес сервера источника данных.
*   `access`: Метод доступа (`proxy` для серверного прокси, `direct` для прямого доступа из браузера).
*   `isDefault`: Указывает, является ли этот источник данных по умолчанию.
*   `editable`: Если `false`, источник данных нельзя будет изменить через UI Grafana.

## Провиженинг дашбордов (Dashboards)

Дашборды также могут быть провижены с помощью Helm. Grafana может загружать дашборды из файлов JSON, из библиотеки Grafana.com, напрямую из встроенного JSON в `values.yaml`, или из Kubernetes ConfigMaps.

Пример конфигурации провиженинга дашбордов через `values.yaml`:

```yaml
grafana:
  dashboardProviders:
    dashboardproviders.yaml:
      apiVersion: 1
      providers:
      - name: monitoring
        orgId: 1
        folder: ''
        type: file
        disableDeletion: false
        editable: true
        options:
          path: /var/lib/grafana/dashboards/monitoring
  dashboards:
    monitoring:
      node-exporter-full:
        gnetId: 1860
        revision: 21
        datasource: Prometheus1
      new-dash:
        json: |-
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
                "datasource": "Prometheus1",
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
                  "graphMode": "none",
                  "justifyMode": "auto",
                  "orientation": "auto",
                  "reduceOptions": {
                    "calcs": [
                      "lastNotNull"
                    ],
                    "fields": "",
                    "values": false
                  },
                  "showPercent": false,
                  "textMode": "value",
                  "thresholdsStyle": "text"
                },
                "pluginVizId": "stat",
                "targets": [
                  {
                    "expr": "up{job=\"node-exporter\"}",
                    "refId": "A"
                  }
                ],
                "title": "Node Exporter Up",
                "type": "stat"
              }
            ],
            "schemaVersion": 27,
            "style": "dark",
            "tags": [],
            "templating": {
              "list": []
            },
            "time": {
              "from": "now-6h",
              "to": "now"
            },
            "timepicker": {},
            "timezone": "",
            "title": "New Dash",
            "type": "dashboard",
            "uid": null,
            "version": 0
          }
```

**Важное замечание по провиженингу дашбордов:**
*   Имя дашборда не должно совпадать с именем директории, в которой он находится. В противном случае Grafana может выдать ошибку при провиженинге.

**Пояснения:**
*   **`dashboardProviders`**: Определяет, откуда Grafana будет загружать дашборды.
    *   `name`: Имя провайдера.
    *   `type: file`: Указывает, что дашборды будут загружаться из файлов.
    *   `options.path`: Путь в контейнере Grafana, где будут находиться файлы дашбордов.
*   **`dashboards`**: Определяет сами дашборды.
    *   `node-exporter-full`: Пример импорта дашборда из Grafana.com.
        *   `gnetId`: ID дашборда на Grafana.com (например, 1860 для Node Exporter Full).
        *   `revision`: Версия дашборда.
        *   `datasource`: Имя источника данных, который будет использоваться дашбордом.
    *   `new-dash`: Пример дашборда, встроенного напрямую в `values.yaml` в формате JSON.
        *   `json`: Сырой JSON-объект дашборда.

## Провиженинг плагинов (Plugins)

Плагины Grafana также могут быть установлены автоматически при развертывании через Helm.

Пример конфигурации плагинов через `values.yaml`:

```yaml
grafana:
  plugins:
    - grafana-piechart-panel
    - trafficlight-panel
```

**Пояснения:**
*   `plugins`: Список плагинов, которые Grafana должна установить при запуске. Grafana CLI будет использовать эти имена для установки плагинов из официального репозитория Grafana.

## Преимущества провиженинга

*   **Автоматизация:** Устраняет ручные операции по настройке Grafana.
*   **Версионирование:** Конфигурации хранятся в системе контроля версий (например, Git), что позволяет отслеживать изменения и откатываться к предыдущим версиям.
*   **Согласованность:** Обеспечивает одинаковую конфигурацию Grafana в различных средах (разработка, тестирование, продакшн).
*   **GitOps:** Идеально подходит для реализации подхода GitOps, где желаемое состояние инфраструктуры описывается в Git.

## Автоматизация дашбордов с помощью Ansible

Ansible может быть использован для автоматического создания, обновления и удаления дашбордов Grafana через её API. Это позволяет интегрировать управление дашбордами в CI/CD пайплайны и хранить их конфигурацию в системе контроля версий.

### Использование шаблонов Jinja2

Для создания типовых дашбордов с небольшими отличиями (например, для разных сервисов или окружений) можно использовать шаблонизаторы, такие как Jinja2. Это позволяет генерировать множество похожих дашбордов из одного шаблона.

1.  **Создание шаблона**: Разработайте JSON-шаблон дашборда, используя переменные Jinja2 для динамических значений.
2.  **Генерация JSON**: С помощью Ansible сгенерируйте финальный JSON-файл дашборда, подставляя нужные значения в шаблон.

### Модуль `grafana_dashboard`

Ansible предоставляет модуль `grafana_dashboard`, который позволяет взаимодействовать с Grafana API для управления дашбордами.

*   **`grafana_url`**: URL вашей Grafana.
*   **`grafana_api_key`**: API-ключ с соответствующими правами (например, Editor или Admin). API-ключи можно создать в Grafana в разделе `Configuration -> API Keys`. Рекомендуется хранить API-ключи в безопасном хранилище (например, Ansible Vault). Подробнее см. в [документе по управлению пользователями](./grafana_user_management_and_authentication.md).
*   **`state`**: `present` (создать/обновить) или `absent` (удалить).
*   **`path`**: Путь к JSON-файлу дашборда (или сгенерированному из шаблона).

Пример использования Ansible для развертывания дашборда:

```yaml
- name: Deploy Grafana Dashboard
  grafana_dashboard:
    grafana_url: "https://grafana.example.com"
    grafana_api_key: "{{ grafana_api_key }}" # API-ключ из Vault или другого безопасного хранилища
    state: present
    path: "/path/to/generated_dashboard.json"
```

Этот подход позволяет полностью автоматизировать управление дашбордами, интегрируя его в CI/CD пайплайны и обеспечивая принцип "Configuration as Code".


