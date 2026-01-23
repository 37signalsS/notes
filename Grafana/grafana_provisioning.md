# Grafana Provisioning

## Определения

**Провиженинг (Provisioning)** в Grafana — это процесс автоматического управления конфигурациями (источниками данных, дашбордами, плагинами и др.) как кодом. Этот подход обеспечивает автоматизацию, версионирование и согласованность между различными экземплярами Grafana, что особенно важно в динамических средах, таких как Kubernetes.

## Основные концепции

### Принципы работы

Grafana поддерживает провиженинг через конфигурационные файлы (YAML для большинства ресурсов, JSON для дашбордов), которые размещаются в специальной директории (по умолчанию `/etc/grafana/provisioning`). При запуске Grafana сканирует эту директорию, считывает файлы и применяет описанные в них конфигурации.

Этот механизм является центральным для автоматизированного развертывания Grafana в различных средах:

*   **Standalone-установка:** Файлы провиженинга размещаются в `/etc/grafana/provisioning`.
*   **Docker-контейнер:** Директория с файлами провиженинга монтируется как том (`volume`) в контейнер.
*   **Kubernetes (Helm-чарты):** Конфигурации встраиваются в `values.yaml` или ConfigMaps и развертываются вместе с Grafana.
*   **IaC (Terraform, Pulumi):** Инструменты "инфраструктура как код" могут управлять конфигурационными файлами или напрямую взаимодействовать с API Grafana для применения изменений.

### Преимущества провиженинга

*   **Автоматизация:** Устраняет ручные операции по настройке Grafana.
*   **Версионирование:** Конфигурации хранятся в системе контроля версий (например, Git), что позволяет отслеживать изменения и откатываться к предыдущим версиям.
*   **Согласованность (Consistency):** Обеспечивает одинаковую конфигурацию Grafana во всех окружениях (разработка, тестирование, продакшн).
*   **GitOps:** Идеально подходит для реализации подхода GitOps, где репозиторий Git является единственным источником правды о желаемом состоянии инфраструктуры.

## Практические сценарии

Существует три основных подхода к провиженингу: файловый, с помощью Helm в Kubernetes и через API с использованием инструментов автоматизации, таких как Ansible.

### 1. Файловый провиженинг

Этот подход наиболее удобен при работе с Docker. Grafana при старте сканирует директорию `/etc/grafana/provisioning/`, где можно создать поддиректории для разных типов ресурсов:

*   `datasources/`
*   `dashboards/`
*   `plugins/`
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

В файле `datasources/datasources.yaml` можно определить один или несколько источников данных.

**Пример для InfluxDB:**
```yaml
apiVersion: 1
datasources:
- name: InfluxDB
  type: influxdb
  url: http://influxdb:8086
  database: telegraf
  user: telegraf
  password: your_password # Рекомендуется использовать переменные окружения или секреты
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
    # Пример дополнительных настроек
    timeInterval: "15s"
```

#### Провиженинг дашбордов

Сначала создается файл-провайдер (`dashboards/dashboards.yaml`), который указывает Grafana, где искать JSON-модели дашбордов.

```yaml
apiVersion: 1
providers:
- name: 'rotation-provider'
  orgId: 1
  folder: 'Rotation' # Дашборды будут помещены в папку 'Rotation' в UI
  type: file
  options:
    path: /etc/grafana/provisioning/dashboards/rotation # Путь к JSON-файлам внутри контейнера
```
JSON-модели (`rotation-dash-1.json`) — это обычные файлы, которые можно получить, экспортировав существующий дашборд из UI Grafana.

#### Провиженинг плейлистов

Аналогично можно автоматически создать плейлист для ротации дашбордов.

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
          folderName: 'Rotation' # Указываем папку, все дашборды из которой попадут в плейлист
        title: 'Dashboards from Rotation Folder'
```

### 2. Провиженинг в Kubernetes с помощью Helm

Helm-чарт для Grafana позволяет определять все ресурсы провиженинга напрямую в файле `values.yaml`.

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
        editable: false
```
*   `editable: false` запрещает изменение источника данных через UI.

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
      
      # Встраивание дашборда напрямую в values.yaml
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
Grafana при запуске установит указанные плагины.

### 3. Автоматизация через API с помощью Ansible

Ansible позволяет управлять ресурсами Grafana через её API, что идеально подходит для динамической генерации конфигураций.

#### Динамическая генерация дашбордов

С помощью шаблонизатора **Jinja2** можно создавать множество однотипных дашбордов из одного шаблона (например, `dashboard.json.j2`), подставляя в него переменные (имена сервисов, ID команд и т.д.).

Плейбук Ansible генерирует финальные JSON-файлы и развертывает их с помощью модуля `community.grafana.grafana_dashboard`.

```yaml
- name: Deploy Grafana Dashboard
  community.grafana.grafana_dashboard:
    grafana_url: "https://grafana.example.com"
    grafana_api_key: "{{ grafana_api_key }}" # API-ключ из Ansible Vault
    state: present
    path: "/path/to/generated_dashboard.json"
    folder: "My Team Dashboards"
```

*   **`grafana_api_key`**: API-ключ с правами Editor или Admin. Его можно создать в UI Grafana: `Configuration -> API Keys`. Подробнее см. в [документе по управлению пользователями](./grafana_user_management_and_authentication.md).
*   **`state`**: `present` (создать/обновить) или `absent` (удалить).

## Дополнительная информация

### Важные замечания

*   **Источники данных:** Ресурсы, созданные через провиженинг с флагом `editable: false`, нельзя изменить через UI. Если `isDefault` установлено в `true`, провижионированный источник данных переопределит дефолтный источник, настроенный вручную.
*   **Дашборды:** Имя JSON-файла дашборда не должно совпадать с именем директории, в которой он находится, во избежание ошибок.
*   **Секреты:** Пароли и API-ключи не следует хранить в открытом виде. Используйте переменные окружения, Ansible Vault, Kubernetes Secrets или другие системы управления секретами.

### Будущее развитие

В будущих версиях Grafana ожидается более глубокая нативная интеграция с Git-репозиториями, что позволит реализовать подход, где Grafana будет автоматически отслеживать изменения в репозитории и применять их без дополнительных инструментов.
