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

## Основные концепции

### Принципы работы

Grafana сканирует директорию `/etc/grafana/provisioning` при запуске и применяет конфигурации. Для большинства ресурсов (источники данных, дашборды) изменения в файлах подхватываются "на лету" без перезагрузки сервиса, если настроены соответствующие интервалы сканирования.

**Структура директорий:**

```
/etc/grafana/provisioning/
├── datasources/      # Источники данных (Prometheus, SQL, etc.)
├── dashboards/       # Описания провайдеров дашбордов (YAML)
├── alerting/         # Правила, политики и контакт-пойнты
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
| **IaC** | Terraform (Grafana Provider), Pulumi или Ansible API |

## Практические сценарии

### 1. Файловый провиженинг (Docker и Standalone)

#### Провиженинг источников данных
Конфигурационные файлы в `datasources/` позволяют автоматически подключать внешние системы.

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
    secureJsonData:
      basicAuthPassword: "${PROM_PASSWORD}" # Переменная окружения
```
*Подробности по специфическим БД см. в [Практические сценарии — Настройка источников данных](./grafana_datasources.md#практические-сценарии).*

#### Провиженинг дашбордов
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
    updateIntervalSeconds: 30
    options:
      path: /etc/grafana/provisioning/dashboards/json # Путь к JSON-файлам
```

#### Провиженинг плейлистов
Автоматическое создание плейлистов для ротации панелей на мониторах.

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

Helm-чарт Grafana позволяет описывать все ресурсы провиженинга в `values.yaml`.

#### Конфигурация источников и дашбордов

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

Используется для динамического обнаружения дашбордов в кластере (например, в `kube-prometheus-stack`).

#### Принцип работы
Контейнер `k8s-sidecar` (часто называемый `grafana-sc-dashboards`) сканирует ConfigMaps в указанных неймспейсах. При нахождении ConfigMap с правильной меткой, он копирует JSON во временную директорию Grafana.

#### Пример ConfigMap для дашборда

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: business-metrics-dashboard
  namespace: my-app
  labels:
    grafana_dashboard: "1" # Метка для обнаружения sidecar-ом
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

Ansible позволяет динамически генерировать и обновлять дашборды, используя шаблоны **Jinja2**.

#### Динамическое развертывание
В Grafana 13 API-ключи заменены на **Service Accounts**, что является более безопасным методом.

```yaml
- name: Deploy Dynamic Dashboard
  community.grafana.grafana_dashboard:
    grafana_url: "https://grafana.example.com"
    grafana_token: "{{ service_account_token }}" # Токен Service Account (Ansible Vault)
    state: present
    path: "/path/to/generated_from_jinja.json"
    folder: "Team Dashboards"
    overwrite: true
```

### 5. Провиженинг Service Accounts и RBAC (v11+)

Современный способ управления доступом без использования ручных API Keys.

```yaml
# /etc/grafana/provisioning/service-accounts/sa.yaml
apiVersion: 1
serviceAccounts:
  - name: "Automation-SA"
    role: "Editor"
    orgId: 1
    tokens:
      - name: "ansible-token"
        expires: "2027-01-01"
```

## Дополнительная информация

### Важные технические нюансы

| Нюанс | Описание |
| :--- | :--- |
| **`editable: false`** | Запрещает изменения через UI, предотвращая расхождение между Git и живой системой. |
| **Фиксация UID** | Всегда определяйте `uid` в JSON дашбордах. Без этого при изменении имени файла в провиженинге Grafana создаст дубликат. |
| **Конфликты имен** | Имя JSON-файла не должно совпадать с именем директории провайдера, так как Grafana использует файловую систему как базу для путей. |
| **Использование переменных** | Grafana поддерживает интерполяцию `${VAR_NAME}` во всех YAML-файлах провиженинга (требуется включение в `grafana.ini`). |

**См. также:**
- [Официальная документация по провиженингу](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [Provisioning алертов](./alerting/provisioning.md) — подробные примеры для правил и политик
- [Grafana: RBAC](./grafana_user_management_and_authentication.md#rbac) — подробности управления ролями
