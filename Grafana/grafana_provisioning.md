# Grafana Provisioning

## Определения

**Провиженинг (Provisioning)** в Grafana — это подход Infrastructure as Code (IaC) для автоматизированного управления конфигурациями (источниками данных, дашбордами, оповещениями, плагинами и др.). Он обеспечивает автоматизацию, версионирование и согласованность между экземплярами Grafana, что критически важно в динамических средах.

## Основные концепции

### Принципы работы

Grafana осуществляет провиженинг через конфигурационные файлы (YAML для большинства ресурсов, JSON для дашбордов), размещенные в директории провиженинга (по умолчанию `/etc/grafana/provisioning`). При запуске Grafana сканирует эту директорию, считывает файлы и применяет описанные в них конфигурации.

Этот механизм является ключевым для автоматизированного развертывания Grafana:

*   **Standalone-установка:** Файлы размещаются в `/etc/grafana/provisioning`.
*   **Docker-контейнер:** Директория монтируется как том (`volume`) в контейнер.
*   **Kubernetes (Helm-чарты):** Конфигурации встраиваются в `values.yaml` или ConfigMaps.
*   **IaC (Terraform, Pulumi):** Управляют конфигурационными файлами или взаимодействуют с API Grafana.

### Преимущества провиженинга

*   **Автоматизация:** Устраняет ручные операции настройки.
*   **Версионирование:** Конфигурации хранятся в Git, позволяя отслеживать изменения и откатываться к предыдущим версиям.
*   **Согласованность:** Обеспечивает идентичную конфигурацию Grafana во всех окружениях.
*   **GitOps:** Идеально подходит для реализации подхода [GitOps](../../GitOps/GitOps_overview.md), где Git-репозиторий служит единственным источником правды о желаемом состоянии инфраструктуры.

## Практические сценарии

Существуют основные подходы к провиженингу: файловый, с помощью Helm в Kubernetes и через API с использованием Ansible.

### 1. Файловый провиженинг

Этот подход часто используется с Docker. Grafana сканирует `/etc/grafana/provisioning/`, где создаются поддиректории для типов ресурсов:

*   `datasources/`
*   `dashboards/`
*   `alerting/` (для правил оповещений)
*   `playlists/`

**Пример структуры:**

```
/path/to/your/grafana/provisioning/
├── datasources/
│   └── datasources.yaml
├── dashboards/
│   ├── dashboards.yaml
│   └── rotation/
│       ├── rotation-dash-1.json
│       └── rotation-dash-2.json
└── playlists/
    └── playlists.yaml
```

#### Провиженинг источников данных

В `datasources/datasources.yaml` определяются источники данных.

**Пример для InfluxDB:**
```yaml
apiVersion: 1
datasources:
- name: InfluxDB
  type: influxdb
  url: http://influxdb:8086
  database: telegraf
  user: telegraf
  password: your_password # Используйте переменные окружения или секреты
  access: proxy
  isDefault: true
```

**Пример для Prometheus:**
```yaml
apiVersion: 1
datasources:
- name: Prometheus
  type: prometheus
  url: http://prometheus:9090
  access: proxy
  isDefault: false
  jsonData:
    timeInterval: "15s"
```

#### Провиженинг дашбордов

Создается файл-провайдер (`dashboards/dashboards.yaml`), указывающий Grafana, где искать JSON-модели дашбордов.

```yaml
apiVersion: 1
providers:
- name: 'rotation-provider'
  orgId: 1
  folder: 'Rotation' # Дашборды помещаются в папку 'Rotation' в UI
  type: file
  options:
    path: /etc/grafana/provisioning/dashboards/rotation # Путь к JSON-файлам внутри контейнера
```
JSON-модели дашбордов (`rotation-dash-1.json`) получаются экспортом из UI Grafana.

#### Провиженинг плейлистов

Автоматическое создание плейлистов для ротации дашбордов.

**`provisioning/playlists.yaml`:**
```yaml
apiVersion: 1
playlists:
  - name: 'Rotation Playlist'
    interval: '1m'
    orgId: 1
    items:
      - type: dashboard_by_folder
        value:
          folderName: 'Rotation' # Все дашборды из папки попадают в плейлист
        title: 'Dashboards from Rotation Folder'
```

### 2. Провиженинг в Kubernetes с помощью Helm

Helm-чарт для Grafana позволяет определять ресурсы провиженинга напрямую в `values.yaml`.

#### Источники данных (Data Sources)

```yaml
# values.yaml
grafana:
  datasources:
    datasources.yaml:
      apiVersion: 1
      datasources:
      - name: Prometheus
        type: prometheus
        url: http://prometheus-server.monitoring.svc.cluster.local
        access: proxy
        isDefault: true
        editable: false # Запрещает изменение через UI
```

#### Дашборды (Dashboards)

```yaml
# values.yaml
grafana:
  dashboardProviders:
    dashboardproviders.yaml:
      apiVersion: 1
      providers:
      - name: 'default-provider'
        orgId: 1
        folder: 'Default'
        type: file
        options:
          path: /var/lib/grafana/dashboards/default

  dashboards:
    default:
      # Импорт дашборда с Grafana.com по ID
      node-exporter-full:
        gnetId: 1860
        revision: 21
        datasource: Prometheus
      
      # Встраивание дашборда напрямую
      custom-dashboard:
        json: |-
          {
            "uid": "custom-abc",
            "title": "Custom Dashboard",
            ...
          }
```

#### Плагины (Plugins)

```yaml
# values.yaml
grafana:
  plugins:
    - grafana-piechart-panel
    - volkov-echarts-panel
```
Grafana установит указанные плагины при запуске.

### 3. Автоматизация через API с помощью Ansible

Ansible позволяет управлять ресурсами Grafana через её API, используя динамическую генерацию конфигураций.

#### Динамическая генерация дашбордов

Модуль `community.grafana.grafana_dashboard` в Ansible позволяет развертывать дашборды, созданные с помощью шаблонизатора **Jinja2**.

```yaml
- name: Deploy Grafana Dashboard
  community.grafana.grafana_dashboard:
    grafana_url: "https://grafana.example.com"
    grafana_api_key: "{{ grafana_api_key }}" # API-ключ (Ansible Vault)
    state: present # present (создать/обновить) или absent (удалить)
    path: "/path/to/generated_dashboard.json"
    folder: "My Team Dashboards"
```

*   **`grafana_api_key`**: API-ключ с правами Editor или Admin, создается в `Configuration -> API Keys`. Подробнее см. [управление пользователями](./grafana_user_management_and_authentication.md).

## Дополнительная информация

### Важные замечания

*   **Источники данных:** Ресурсы, провиженингованные с `editable: false`, нельзя изменить через UI. `isDefault: true` переопределяет дефолтный источник, настроенный вручную.
*   **Дашборды:** Имя JSON-файла дашборда не должно совпадать с именем директории.
*   **Секреты:** Пароли и API-ключи следует хранить в переменных окружения, Ansible Vault, Kubernetes Secrets или других системах управления секретами.
