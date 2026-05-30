# Grafana: Провиженинг

## Определения

**Провиженинг (Provisioning)** — подход Infrastructure as Code для автоматизированного управления конфигурацией Grafana (источники данных, дашборды, оповещения, плагины).

**Текущая версия (март 2026):** Grafana 12.x

**Связанные темы:**

- [Обзор Grafana](./grafana_overview.md) — общая информация о платформе
- [Источники данных](./grafana_datasources.md) — провижинг источников
- [Дашборды](./dashboards/definitions_and_concepts.md) — провижинг дашбордов
- [Алертинг](./alerting/concepts.md) — провижинг правил оповещений
- [Плагины](./grafana_plugins.md) — установка плагинов

### Преимущества

| Преимущество | Описание |
| :--- | :--- |
| **Автоматизация** | Устраняет ручную настройку |
| **Версионирование** | Конфигурации в Git, отслеживание изменений |
| **Согласованность** | Идентичная конфигурация во всех окружениях |
| **GitOps** | Git — единственный источник правды |

## Основные концепции

### Принципы работы

Grafana сканирует `/etc/grafana/provisioning` при старте и применяет конфигурации из YAML/JSON-файлов.

**Структура директорий:**

```
/etc/grafana/provisioning/
├── datasources/      # Источники данных
├── dashboards/       # Дашборды (YAML-провайдеры + JSON)
├── alerting/         # Правила оповещений
├── contactpoints/    # Контакт-пойнты
├── policies/         # Политики уведомлений
└── plugins/          # Плагины (устарело)
```

**Поддерживаемые окружения:**

| Окружение | Метод |
| :--- | :--- |
| **Standalone** | Файлы в `/etc/grafana/provisioning` |
| **Docker** | Volume: `./provisioning:/etc/grafana/provisioning` |
| **Kubernetes** | ConfigMaps + Helm `values.yaml` |
| **IaC** | Terraform/Pulumi + Ansible API |

### Преимущества провиженинга

- **Автоматизация:** Устраняет ручные операции настройки.
- **Версионирование:** Конфигурации хранятся в Git, позволяя отслеживать изменения и откатываться к предыдущим версиям.
- **Согласованность:** Обеспечивает идентичную конфигурацию Grafana во всех окружениях.
- **GitOps:** Идеально подходит для реализации подхода [GitOps](../GitOps/GitOps_overview.md), где Git-репозиторий служит единственным источником правды о желаемом состоянии инфраструктуры.

## Практические сценарии

Существуют основные подходы к провиженингу: файловый, с помощью Helm в Kubernetes и через API с использованием Ansible.

### 1. Файловый провиженинг

Этот подход часто используется с Docker. Grafana сканирует `/etc/grafana/provisioning/`, где создаются поддиректории для типов ресурсов:

- `datasources/`
- `dashboards/`
- `alerting/` (для правил оповещений)
- `playlists/`

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

Конфигурационные файлы в директории `datasources/` позволяют автоматически подключать внешние системы. Подробные примеры YAML-конфигураций для различных баз данных (Prometheus, InfluxDB и др.) приведены в разделе **[Практические сценарии — Настройка источников данных](./grafana_datasources.md#практические-сценарии)**.

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

Автоматизация установки плагинов (включая примеры конфигурации Helm и Docker Compose) подробно описана в разделе [Практические сценарии — Управление плагинами](./grafana_plugins.md#управление-плагинами).

### 3. Механизм Grafana Sidecar и ConfigMap в Kubernetes

В контексте `kube-prometheus-stack` (особенно при развертывании через Rancher) используется механизм **Grafana Sidecar** для автоматического обнаружения и загрузки дашбордов.

#### Назначение и принцип работы

Вместо хранения дашбордов в файловой системе Grafana (которая может быть эфемерной), `sidecar`-контейнер, запущенный в том же поде, что и Grafana, сканирует указанные Kubernetes `ConfigMap` или `Secret` ресурсы.

`Sidecar` постоянно отслеживает изменения в `ConfigMap` с определенными метками и при обнаружении новых или измененных дашбордов автоматически импортирует их в Grafana. Это позволяет версионировать дашборды в Git и централизованно развертывать, не требуя ручных действий по импорту через UI.

#### Провижионинг пользовательских дашбордов через ConfigMap

1. **Экспортируйте JSON**: Используйте локальный экземпляр Grafana для создания дашборда и экспортируйте его в формате JSON.
2. **Создайте `ConfigMap`**: Оберните экспортированный JSON дашборда в `ConfigMap`. **Ключевым моментом является добавление метки `grafana-dashboard: "1"`** (или другой, указанной в конфигурации `sidecar`), которая будет использоваться для обнаружения.

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
         "title": "Test Application Dashboard",
         "type": "dashboard",
         "uid": "test-app-dashboard",
         ...
       }
   ```

3. **Разверните `ConfigMap`**: Примените этот ресурс в вашем кластере. Дашборд появится в Grafana автоматически.
   *Примечание: для обнаружения в других `namespaces`, убедитесь, что соответствующая настройка включена в `values.yaml` Helm-чарта (например, `sidecar.dashboards.searchNamespace: ALL`).*

### 4. Автоматизация через API с помощью Ansible

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

- **`grafana_api_key`**: API-ключ с правами Editor или Admin, создается в `Configuration -> API Keys`. Подробнее см. [управление пользователями](./grafana_user_management_and_authentication.md).

## Дополнительная информация

### Важные замечания

| Замечание | Описание |
| :--- | :--- |
| **`editable: false`** | Запрещает изменение через UI |
| **`isDefault: true`** | Переопределяет ручной дефолтный источник |
| **Имя JSON** | Не должно совпадать с именем директории |

Подробная [документация провиженинга](https://grafana.com/docs/grafana/latest/administration/provisioning/) доступна на сайте Grafana Labs. Дополнительные примеры: [Provisioning дашбордов](./dashboards/provisioning_configmap.md) и [Provisioning алертов](./alerting/provisioning.md).
