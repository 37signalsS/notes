# Grafana: Провиженинг

## Определения

**Провиженинг (Provisioning)** — подход Infrastructure as Code (IaC) для автоматизированного управления конфигурацией Grafana. Он позволяет декларативно описывать источники данных, дашборды, правила оповещений, плагины и другие ресурсы через конфигурационные файлы (YAML/JSON).

**Связанные темы:**
- [Обзор Grafana](./grafana_overview.md) — общая информация о платформе
- [Monitoring as Code (MaC)](./monitoring_as_code.md) — концепция и GitOps-пайплайны
- [Источники данных](./grafana_datasources.md) — детали настройки подключений
- [Дашборды](./grafana-dashboards.md) — создание и управление визуализациями
- [Алертинг: Provisioning](./alerting/provisioning.md) — специализированный SSoT по провиженингу оповещений
- [Плагины](./grafana_plugins.md) — автоматизация установки расширений

### Преимущества подхода

| Преимущество | Описание |
| :--- | :--- |
| **Автоматизация** | Устраняет необходимость ручной настройки через интерфейс, ускоряя развертывание. |
| **Версионирование** | Конфигурации хранятся в Git, позволяя отслеживать историю изменений и проводить Code Review. |
| **Согласованность** | Обеспечивает идентичное состояние Grafana во всех окружениях (Dev, Test, Prod). |
| **GitOps** | Идеально вписывается в модель [GitOps](../GitOps/GitOps_overview.md), где Git — единственный источник истины. См. подробнее **[Monitoring as Code (MaC)](./monitoring_as_code.md)**. |
| **Безопасность** | Позволяет использовать переменные окружения и внешние хранилища для управления секретами. |

---

## Основные концепции

### Принципы работы

Grafana сканирует директорию `/etc/grafana/provisioning` при запуске и применяет конфигурации. Для большинства ресурсов (источники данных, дашборды) изменения в файлах подхватываются "на лету" (Hot Reload) без перезагрузки сервиса, если настроены соответствующие интервалы сканирования.

**Структура директорий:**

```
/etc/grafana/provisioning/
├── datasources/      # Источники данных (Prometheus, SQL, etc.)
├── dashboards/       # Описания провайдеров дашбордов (YAML)
├── alerting/         # Правила, политики и контакт-пойнты (Unified Alerting)
├── contactpoints/    # (v10+) Отдельная папка для контакт-пойнтов
├── policies/         # (v10+) Отдельная папка для политик уведомлений
├── access-control/   # (v11+) Роли RBAC и разрешения
├── service-accounts/ # (v11+) Сервисные аккаунты
├── playlists/        # Конфигурация плейлистов
└── plugins/          # Установка плагинов (устаревает, рекомендуется CLI/ENV)
```

### Поддерживаемые окружения

| Окружение | Метод реализации |
| :--- | :--- |
| **Standalone** | Локальные файлы в `/etc/grafana/provisioning/` |
| **Docker** | Монтирование тома: `-v ./provisioning:/etc/grafana/provisioning` |
| **Kubernetes** | ConfigMaps/Secrets + Helm `values.yaml` + `k8s-sidecar` |
| **IaC** | Terraform/OpenTofu (Grafana Provider), Grizzly (YAML CLI) |

---

## Практические сценарии

### 1. Файловый провиженинг (Docker и Standalone)

#### Провиженинг источников данных (Datasources)
Конфигурационные файлы в `datasources/` позволяют автоматически подключать внешние системы. Рекомендуется устанавливать `editable: false`, чтобы гарантировать соответствие UI коду в Git.

```yaml
# /etc/grafana/provisioning/datasources/datasources.yaml
apiVersion: 1
datasources:
  - name: Prometheus-Prod
    type: prometheus
    url: http://prometheus:9090
    access: proxy
    isDefault: true
    jsonData:
      timeInterval: "15s"
      httpMethod: "POST"
      queryTimeout: "60s" # (v10+) Таймаут выполнения запроса
    secureJsonData:
      basicAuthPassword: "${PROM_PASSWORD}" # Переменная окружения
```

#### Провиженинг дашбордов (Dashboards)
Создается файл-провайдер, который указывает, где искать JSON-модели.

```yaml
# /etc/grafana/provisioning/dashboards/providers.yaml
apiVersion: 1
providers:
  - name: 'System-Monitoring'
    orgId: 1
    folder: 'Infrastructure' # Дашборды помещаются в папку 'Infrastructure' в UI
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30 # Интервал сканирования папки на наличие новых JSON
    allowUiUpdates: false     # Запрет сохранения изменений из UI в файл провайдера
    options:
      path: /etc/grafana/provisioning/dashboards/json # Путь к JSON-файлам
      foldersFromFilesStructure: true # (v11+) Создание вложенных папок по структуре ФС
```

#### Провиженинг плейлистов
Автоматическое создание плейлистов для ротации панелей на NOC-мониторах.

```yaml
# /etc/grafana/provisioning/playlists/playlists.yaml
apiVersion: 1
playlists:
  - name: 'NOC-Rotation'
    interval: '1m'
    orgId: 1
    items:
      - type: dashboard_by_folder
        value: 'Infrastructure'
        title: 'All Infrastructure Dashboards'
```

### 2. Провиженинг в Kubernetes через Helm

Helm-чарт Grafana позволяет описывать все ресурсы провиженинга в `values.yaml`. Это основной метод для облачных сред.

#### Конфигурация через values.yaml

```yaml
# values.yaml
grafana:
  datasources:
    datasources.yaml:
      apiVersion: 1
      datasources:
        - name: Loki
          type: loki
          url: http://loki-stack.monitoring:3100
          editable: false

  dashboardProviders:
    dashboardproviders.yaml:
      apiVersion: 1
      providers:
        - name: 'default'
          orgId: 1
          folder: 'General'
          type: file
          options:
            path: /var/lib/grafana/dashboards/default

  dashboards:
    default:
      # Импорт дашборда с Grafana.com по ID
      node-exporter:
        gnetId: 1860
        revision: 37
        datasource: Prometheus
      
      # Встраивание JSON-модели напрямую (не рекомендуется для больших дашбордов)
      health-check:
        json: |-
          {
            "uid": "health-01",
            "title": "System Health",
            "panels": [...]
          }
```

### 3. Механизм Sidecar и ConfigMap в Kubernetes

Используется для динамического обнаружения дашбордов в кластере без перезагрузки Grafana.

#### Принцип работы
Контейнер `k8s-sidecar` (часто называемый `grafana-sc-dashboards`) сканирует ConfigMaps в указанных неймспейсах. При нахождении ConfigMap с правильной меткой (по умолчанию `grafana_dashboard: "1"`), он копирует JSON во временную директорию Grafana.

#### Пример ConfigMap для дашборда
Использование аннотаций позволяет автоматически создавать папки.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: business-metrics-dashboard
  namespace: my-app
  labels:
    grafana_dashboard: "1" # Метка для обнаружения sidecar-ом
  annotations:
    grafana_dashboard_folder: "Business-Analytics"
data:
  business-metrics.json: |-
    {
      "title": "Business Performance",
      "type": "dashboard",
      "uid": "biz-perf-001",
      ...
    }
```
*Для поиска во всех неймспейсах установите `sidecar.dashboards.searchNamespace: ALL` в Helm values.*

### 4. Автоматизация через API с использованием Ansible

Ansible позволяет динамически генерировать дашборды, используя шаблоны **Jinja2**, и развертывать их через API.

#### Динамическое развертывание (Service Accounts v11+)
В современных версиях Grafana (v11+) использование API-ключей устарело. Рекомендуется использовать **Service Accounts**.

```yaml
- name: Deploy Dynamic Dashboard
  community.grafana.grafana_dashboard:
    grafana_url: "https://grafana.example.com"
    grafana_token: "{{ service_account_token }}" # Токен из Ansible Vault
    state: present
    path: "/tmp/generated_dashboard.json"
    folder: "Automated-Dashboards"
    overwrite: true
    commit_message: "Updated via CI/CD pipeline"
```

### 5. Провиженинг Service Accounts и RBAC (v11+)

Декларативное управление доступом позволяет избежать ручной настройки прав в интерфейсе.

#### Настройка сервисных аккаунтов

```yaml
# /etc/grafana/provisioning/service-accounts/sa.yaml
apiVersion: 1
serviceAccounts:
  - name: "CI-CD-Bot"
    role: "Admin" # Возможные значения: Admin, Editor, Viewer
    orgId: 1
    tokens:
      - name: "deployment-token"
        expires: "2027-01-01"
```

#### Настройка кастомных ролей RBAC

```yaml
# /etc/grafana/provisioning/access-control/roles.yaml
apiVersion: 1
roles:
  - name: "custom:dashboard-auditor"
    description: "Read-only access to specific team folder"
    permissions:
      - action: "dashboards:read"
        scope: "folders:uid:team-alpha-folder"
```

---

## Дополнительная информация

### Важные технические нюансы

1.  **Фиксация UID**: Всегда жестко прописывайте `uid` в JSON-модели дашборда. Если этого не сделать, Grafana создаст новый UID при каждом перезапуске провайдера, что приведет к появлению дубликатов и поломке внешних ссылок.
2.  **Configuration Drift**: При использовании провиженинга любые изменения, сделанные пользователем через UI, **не сохраняются** обратно в конфигурационные файлы. После перезапуска пода/сервиса Grafana вернет состояние, описанное в файлах. Для предотвращения путаницы устанавливайте `editable: false`.
3.  **Конфликты имен**: Имя JSON-файла не должно совпадать с именем директории провайдера в конфигурации, так как Grafana использует файловую систему как базу для формирования путей.
4.  **Переменные окружения**: Grafana поддерживает интерполяцию `${VAR_NAME}` во всех YAML-файлах провиженинга. Для активации этой функции убедитесь, что в `grafana.ini` в секции `[paths]` корректно настроены пути, или используйте системные переменные окружения напрямую (поддерживается нативно для секретов в `secureJsonData`).
5.  **Concurrent Provisioning**: При использовании множества файлов провиженинга Grafana обрабатывает их параллельно. Однако для ресурсов одного типа (например, два файла `datasources.yaml`) порядок применения может зависеть от алфавитного порядка имен файлов.

**См. также:**
- [Официальная документация по провиженингу](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [Provisioning алертов](./alerting/provisioning.md) — подробные примеры для правил и политик
- [Monitoring as Code (MaC)](./monitoring_as_code.md) — концепция управления через GitOps
- [Безопасность и RBAC](./grafana_user_management_and_authentication.md#rbac) — подробности управления ролями
