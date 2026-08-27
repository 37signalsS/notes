# Grafana: Провиженинг

## Определения

**Провиженинг (Provisioning)** — подход Infrastructure as Code (IaC) для автоматизированного управления конфигурацией Grafana. Он позволяет декларативно описывать источники данных, дашборды, правила оповещений, плагины и другие ресурсы через конфигурационные файлы (YAML/JSON).

**File-based provisioning** — механизм, при котором Grafana сама читает конфигурационные файлы из файловой системы (директория `provisioning`) при старте и периодически (hot reload). Это отличает его от управления через HTTP API / Terraform, где изменения применяются по явному запросу извне. Провиженинг идеален для **bootstrap**-конфигурации (начальное состояние кластера), тогда как API/Terraform — для динамического управления в рамках GitOps (см. [Monitoring as Code](./monitoring_as_code.md)).

**Связанные темы:**
- [Обзор Grafana](./grafana_overview.md) — общая информация о платформе
- [Monitoring as Code (MaC)](./monitoring_as_code.md) — концепция и GitOps-пайплайны
- [Источники данных](./grafana_datasources.md) — детали настройки подключений
- [Дашборды](./grafana-dashboards.md) — создание и управление визуализациями
- [Плагины](./grafana_plugins.md) — автоматизация установки расширений

### Что можно провижинить

| Тип ресурса | Директория | Поддержка hot reload |
| :--- | :--- | :--- |
| Источники данных (Data Sources) | `datasources/` | Да |
| Дашборды (Dashboard providers + JSON) | `dashboards/` | Да (по `updateIntervalSeconds`) |
| Правила и папки оповещений (Unified Alerting) | `alerting/` | Частично (часто требует перезапуска) |
| Контакт-пойнты | `contactpoints/` | Частично |
| Политики уведомлений | `policies/` | Частично |
| Сервисные аккаунты | `service-accounts/` | Нет (при старте) |
| Роли RBAC | `access-control/` | Нет (при старте) |
| Плейлисты | `playlists/` | Да |
| Плагины (устаревает) | `plugins/` | Нет |

### Преимущества подхода

| Преимущество | Описание |
| :--- | :--- |
| **Автоматизация** | Устраняет необходимость ручной настройки через интерфейс, ускоряя развертывание. |
| **Версионирование** | Конфигурации хранятся в Git, позволяя отслеживать историю изменений и проводить Code Review. |
| **Согласованность** | Обеспечивает идентичное состояние Grafana во всех окружениях (Dev, Test, Prod). |
| **GitOps** | Идеально вписывается в модель [GitOps](../GitOps/GitOps_overview.md), где Git — единственный источник истины. См. подробнее **[Monitoring as Code (MaC)](./monitoring_as_code.md)**. |
| **Безопасность** | Позволяет использовать переменные окружения и внешние хранилища для управления секретами. |

---

## Базовые концепции

### Принципы работы

Grafana сканирует директорию провиженинга при запуске и применяет конфигурации. Для большинства ресурсов (источники данных, дашборды) изменения в файлах подхватываются «на лету» (Hot Reload) без перезагрузки сервиса, если настроены соответствующие интервалы сканирования.

**Как происходит загрузка:**
1. При старте Grafana читает `grafana.ini` (секция `[paths]`, ключ `provisioning`) или переменную окружения `GF_PATHS_PROVISIONING`, чтобы определить корневую директорию провиженинга (по умолчанию `/etc/grafana/provisioning`).
2. В каждой поддиректории рекурсивно ищутся файлы с расширениями `.yaml`, `.yml`, `.json`.
3. Файлы одного типа применяются в **алфавитном порядке**; при конфликте (одинаковый `name`/`uid`) побеждает последний обработанный файл.
4. Источники данных и дашборды отслеживаются файловым watcher-ом: изменение файла приводит к переприменению без рестарта. Дашборды дополнительно опрашиваются по `updateIntervalSeconds`.
5. Логи загрузки помечены `logger=provisioning` — основной источник диагностики (см. раздел «Устранение неполадок»).

**Три ключевых переключателя защиты от дрейфа:**
- `editable` (на ресурсе дашборда/источника) — можно ли менять объект из UI.
- `allowUiUpdates` (только в `providers` дашбордов) — записывать ли изменения из UI обратно в файл провайдера (файл не перезаписывается, но объект в БД обновляется).
- `disableDeletion` (в `providers` дашбордов) — запрещать ли удаление дашбордов из UI.

Для production рекомендуется комбинация `editable: false` + `allowUiUpdates: false` + `disableDeletion: true`, чтобы состояние Git оставалось единственным источником истины.

### Структура директорий

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

> Папка `notifiers/` из старых версий Grafana (legacy alerting) считается устаревшей; в Unified Alerting используются `contactpoints/` и `policies/`.

### Поддерживаемые окружения

| Окружение | Метод реализации |
| :--- | :--- |
| **Standalone** | Локальные файлы в `/etc/grafana/provisioning/` |
| **Docker** | Монтирование тома: `-v ./provisioning:/etc/grafana/provisioning` |
| **Kubernetes** | ConfigMaps/Secrets + Helm `values.yaml` + `k8s-sidecar` |
| **IaC** | Terraform/OpenTofu (Grafana Provider), Grizzly (YAML CLI) — см. [Monitoring as Code](./monitoring_as_code.md) |

### Безопасность и секреты

Провиженинг поддерживает интерполяцию переменных окружения `${VAR_NAME}` во всех YAML/JSON-файлах, включая секцию `secureJsonData` (Grafana подставляет значение из окружения процесса при загрузке). Это основной способ передачи паролей и токенов без коммита в Git.

Альтернативные паттерны для секретов:
- **Монтирование файла секрета** (Kubernetes Secret, Vault Agent sidecar, init-контейнер), который экспортирует переменную в окружение Grafana перед стартом.
- **Vault Agent sidecar** — паттерн, при котором агент Vault рендерит секреты в файл/переменные локально; см. [Vault Agent basics](../../Vault/guides/vault_agent/basics.md).

Важно: интерполяция выполняется **только в момент загрузки** файла. Ротация секрета требует перезапуска Grafana (или повторного триггера reload), чтобы процесс перечитал переменные окружения.

### Различия: file-based провиженинг против IaC/Terraform

| Аспект | File-based provisioning | Terraform / Grafana API |
| :--- | :--- | :--- |
| Когда применяется | При старте Grafana (hot reload) | По явному запросу (CI/CD, `terraform apply`) |
| Источник истины | Файлы в `provisioning/` | Состояние (state) в Git/Terraform |
| Двунаправленность | Нет (UI-изменения не пишутся в файл) | Да (через `terraform plan` виден дрейф) |
| Лучшее применение | Bootstrap, статичная конфигурация | Динамическое управление, GitOps-дрейф-контроль |

Не управляйте **одним и тем же ресурсом** одновременно файловым провиженингом и Terraform — возникнет конфликт двух источников истины. Выберите один подход per-ресурс. Подробнее — в [Monitoring as Code](./monitoring_as_code.md).

---

## Практические сценарии

### Предварительные требования

- **Grafana**: 11.x (минимум), 12.x (LTS) или 13.1.x (актуальная). Версии ниже 11 не поддерживают провиженинг сервисных аккаунтов и RBAC.
- **Доступ к ФС**: директория провиженинга смонтирована и читаема процессом Grafana (проверка: `ls -l /etc/grafana/provisioning` внутри контейнера/пода).
- **Секреты**: переменные окружения (`${VAR}`) или смонтированные секрет-файлы подготовлены **до** старта Grafana; не коммитятся в Git.
- **Сетевая доступность**: Grafana должна достигать `URL` источников данных (для `Server` доступа) — проверка `curl -v <URL>` из пода Grafana.
- **RBAC для API-методов** (Ansible/Terraform): выделенный Service Account с ролью Editor (или кастомной ролью); API-ключи считаются Legacy в 12+. См. [Управление пользователями и аутентификация](./grafana_user_management_and_authentication.md).
- **Ограничение**: Unified Alerting не поддерживает dashboard-переменные в запросах правил оповещений (вычисляются сервером вне контекста дашборда).

### 1. Файловый провиженинг (Docker и Standalone)

#### Монтирование и запуск (Docker Compose)

```yaml
# docker-compose.yml (фрагмент)
services:
  grafana:
    image: grafana/grafana:13.1.0
    environment:
      PROM_PASSWORD: "${PROM_PASSWORD}"   # Секрет из .env файла (не в коммите)
      GF_PATHS_PROVISIONING: /etc/grafana/provisioning
    volumes:
      - ./provisioning:/etc/grafana/provisioning:ro   # read-only для защиты от UI-записи
    ports:
      - "3000:3000"
```

**Ожидаемый результат:** при `docker compose up` Grafana загружает все файлы из `./provisioning` и регистрирует ресурсы.

**Валидация:**
```bash
docker logs grafana 2>&1 | grep -i provisioning
# → t=... level=info msg="Provisioning results" logger=provisioning ...
#   datasources=1 dashboards=1 plugins=0
```

#### Провиженинг источников данных (Datasources)

Конфигурационные файлы в `datasources/` позволяют автоматически подключать внешние системы. Рекомендуется устанавливать `editable: false`, чтобы гарантировать соответствие UI коду в Git.

```yaml
# /etc/grafana/provisioning/datasources/datasources.yaml
apiVersion: 1
datasources:
  - name: Prometheus-Prod
    type: prometheus
    uid: prometheus-prod        # Стабильный uid для ссылок из дашбордов/алертов
    url: http://prometheus:9090
    access: proxy
    isDefault: true
    editable: false            # Запрет правки из UI (защита от дрейфа)
    jsonData:
      timeInterval: "15s"
      httpMethod: "POST"
      queryTimeout: "60s" # (v10+) Таймаут выполнения запроса
    secureJsonData:
      basicAuthPassword: "${PROM_PASSWORD}" # Переменная окружения
```

**Валидация:**
```bash
curl -s -H "Authorization: Bearer <SA_TOKEN>" \
  http://grafana:3000/api/datasources/name/Prometheus-Prod | jq '.id, .uid'
# → 1 / "prometheus-prod"
```

**Типичные проблемы:**
- Источник не появился — неверный путь монтирования или синтаксическая ошибка YAML (см. `logger=provisioning` в логах).
- `401` от бэкенда — `PROM_PASSWORD` не подставился (переменная не передана в процесс Grafana).

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
    disableDeletion: true     # Запретить удаление из UI
    updateIntervalSeconds: 30 # Интервал сканирования папки на наличие новых JSON
    allowUiUpdates: false     # Запрет сохранения изменений из UI в файл провайдера
    options:
      path: /etc/grafana/provisioning/dashboards/json # Путь к JSON-файлам
      foldersFromFilesStructure: true # (v11+) Создание вложенных папок по структуре ФС
```

Пример минимальной JSON-модели дашборда (файл `dashboards/json/system-health.json`):

```json
{
  "uid": "system-health-01",
  "title": "System Health",
  "tags": ["infra"],
  "schemaVersion": 39,
  "panels": [
    {
      "type": "stat",
      "title": "Up",
      "datasource": { "type": "prometheus", "uid": "prometheus-prod" },
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 0 },
      "targets": [
        { "refId": "A", "expr": "up", "datasource": { "type": "prometheus", "uid": "prometheus-prod" } }
      ]
    }
  ]
}
```

**Ожидаемый результат:** дашборд `System Health` появляется в папке `Infrastructure` (и во вложенных папках, если включён `foldersFromFilesStructure`).

**Валидация:**
```bash
curl -s -H "Authorization: Bearer <SA_TOKEN>" \
  http://grafana:3000/api/search?folderIds=1 | jq '.[].title'
# → "System Health"
```

**Типичные проблемы:**
- Дашборд не загрузился — невалидный JSON (проверьте `jq . dashboards/json/system-health.json`) или несовпадение `uid` источника с `datasource.uid` в панели.

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

**Ожидаемый результат:** после `helm install`/`helm upgrade` дашборды и источники создаются в Grafana.

**Валидация:**
```bash
helm get values my-grafana -n monitoring | grep -A3 datasources
kubectl exec -n monitoring deploy/my-grafana -- curl -s \
  http://localhost:3000/api/datasources/name/Loki | jq '.uid'
# → "loki" (или заданный uid)
```

**Типичные проблемы:**
- Ресурсы не применились — `values.yaml` не содержит ключ `grafana.datasources` в нужном формате; проверьте `helm template` и логи пода.

### 3. Механизм Sidecar и ConfigMap в Kubernetes

Используется для динамического обнаружения дашбордов в кластере без перезагрузки Grafana.

#### Принцип работы

Контейнер `k8s-sidecar` (часто называемый `grafana-sc-dashboards`) сканирует ConfigMaps в указанных неймспейсах. При нахождении ConfigMap с правильной меткой (по умолчанию `grafana_dashboard: "1"`), он копирует JSON во временную директорию Grafana. Подробная настройка — в [Установке Grafana через Helm](./Installation/grafana_helm_installation.md).

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

**Валидация (Helm values для sidecar):**
```yaml
# values.yaml (фрагмент)
sidecar:
  dashboards:
    enabled: true
    searchNamespace: ALL
    label: grafana_dashboard
  datasources:
    enabled: true
```

**Ожидаемый результат:** ConfigMap появляется в любом неймспейсе → sidecar копирует JSON в Grafana → дашборд появляется в папке `Business-Analytics`.

**Типичные проблемы:**
- Дашборд не синхронизируется — неверная метка (`grafana_dashboard: "1"` должна быть строкой), либо `searchNamespace` не включает неймспейс ConfigMap, либо путь назначения sidecar не совпадает с `path` провайдера дашбордов.

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

**Ожидаемый результат:** дашборд `System Health` появляется в папке `Automated-Dashboards` (и во вложенных папках, если включён `foldersFromFilesStructure`).

**Валидация:**
```bash
ansible-playbook deploy.yml
# → PLAY RECAP ... changed=1
curl -s -H "Authorization: Bearer <SA_TOKEN>" \
  "https://grafana.example.com/api/search?query=System" | jq '.[].uid'
# → "system-health-01"
```

**Типичные проблемы:**
- `401` от API — токен сервисного аккаунта истёк или не имеет прав; проверьте роль SA.

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

**Ожидаемый результат:** сервисный аккаунт `CI-CD-Bot` и кастомная роль созданы при старте Grafana.

**Валидация:**
```bash
curl -s -H "Authorization: Bearer <ADMIN_TOKEN>" \
  http://grafana:3000/api/serviceaccounts | jq '.serviceAccounts[].name'
# → "CI-CD-Bot"
```

**Типичные проблемы:**
- Ресурсы не создались — провиженинг SA/RBAC применяется **только при старте**; изменения требуют перезапуска Grafana (файловый watcher для них не работает).

### 6. Провиженинг оповещений (Unified Alerting)

Правила, папки, контакт-пойнты и политики оповещений описываются в директории `alerting/` (плюс `contactpoints/`, `policies/`). Это отдельный авторитетный файл — подробные примеры и структура в [Провиженинге алертов](./alerting/provisioning.md).

Минимальный пример правила (файл `alerting/alert_rules.yaml`):

```yaml
# /etc/grafana/provisioning/alerting/alert_rules.yaml
apiVersion: 1
groups:
  - name: infra-alerts
    folder: Infrastructure
    rules:
      - uid: prometheus-prod-down
        title: Prometheus target down
        condition: ''
        data:
          - refId: A
            datasourceUid: prometheus-prod
            model:
              expr: 'up == 0'
              refId: A
        triggers:
          - once
        for: 0
```

**Ожидаемый результат:** правило `Prometheus target down` появляется в папке `Infrastructure` раздела Alerting.

**Валидация:**
```bash
curl -s -H "Authorization: Bearer <SA_TOKEN>" \
  http://grafana:3000/api/ruler/grafana/api/v1/rules/Infrastructure | jq 'keys'
# → ["infra-alerts"]
```

**Типичные проблемы:** правила не загрузились — неверная структура файла или отсутствует источник с `datasourceUid: prometheus-prod`; детали в логах `logger=provisioning.alerting`.

### 7. Безопасная передача секретов

Секреты никогда не коммитятся в Git. Используйте интерполяцию `${VAR}` и внешние хранилища.

**Вариант А — переменная окружения (базовый):**
```yaml
# /etc/grafana/provisioning/datasources/secure.yaml
apiVersion: 1
datasources:
  - name: App-DB
    type: postgres
    url: postgres:5432
    user: grafana_reader
    secureJsonData:
      password: "${DB_PASSWORD}"   # Подставляется из окружения Grafana
    jsonData:
      sslmode: "verify-full"
```

**Вариант Б — Vault Agent sidecar (Kubernetes):** агент рендерит секрет в файл, init-контейнер экспортирует его в переменную окружения Grafana перед стартом (паттерн описан в [Vault Agent basics](../../Vault/guides/vault_agent/basics.md)).

**Вариант В — Kubernetes Secret, смонтированный как файл:** переменная читается из файла скриптом запуска Grafana (например, через `entrypoint` wrapper).

**Валидация:**
```bash
# Убедиться, что переменная доступна процессу Grafana
kubectl exec -n monitoring deploy/my-grafana -- env | grep DB_PASSWORD
# → DB_PASSWORD=*** (значение видно только в env процесса)
docker compose config | grep PROM_PASSWORD   # должно быть в .env, не в коммите
```

**Типичные проблемы:**
- `${VAR}` не подставилась → переменная не передана в процесс Grafana (проверьте `env` в поде/контейнере); интерполяция происходит только при загрузке, ротация требует рестарта.

---

## Дополнительная информация

### Важные технические нюансы

1.  **Фиксация UID**: Всегда жестко прописывайте `uid` в JSON-модели дашборда и в источнике данных. Если этого не сделать, Grafana создаст новый UID при каждом перезапуске провайдера, что приведет к появлению дубликатов и поломке внешних ссылок.
2.  **Configuration Drift**: При использовании провиженинга любые изменения, сделанные пользователем через UI, **не сохраняются** обратно в конфигурационные файлы. После перезапуска пода/сервиса Grafana вернет состояние, описанное в файлах. Для предотвращения путаницы устанавливайте `editable: false` (на ресурсах) и `allowUiUpdates: false` + `disableDeletion: true` (на провайдерах дашбордов).
3.  **Конфликты имен**: Имя JSON-файла не должно совпадать с именем директории провайдера в конфигурации, так как Grafana использует файловую систему как базу для формирования путей.
4.  **Переменные окружения**: Grafana поддерживает интерполяцию `${VAR_NAME}` во всех YAML-файлах провиженинга, включая `secureJsonData`. Значения берутся из окружения процесса Grafana (системные переменные или `GF_*`), а не только из `grafana.ini`. Интерполяция выполняется один раз при загрузке файла.
5.  **Concurrent Provisioning**: При использовании множества файлов провиженинга Grafana обрабатывает их параллельно. Однако для ресурсов одного типа (например, два файла `datasources.yaml`) порядок применения зависит от алфавитного порядка имен файлов — используйте префиксы (`10-`, `20-`) для детерминированности.

### Устранение неполадок

| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Ресурс не появился** | Ошибка синтаксиса YAML/JSON | Проверьте `docker logs \| grep provisioning`; валидируйте `yamllint` и `jq .` |
| **"Datasource already exists"** | Дублирующийся `name`/`uid` в разных файлах | Задайте уникальные `name` + `uid`; используйте префиксы файлов для порядка |
| **"401 Unauthorized" от бэкенда** | Неверный секрет в `secureJsonData` | Проверьте, что `${VAR}` передана в окружение Grafana |
| **"permission denied" на чтение файла** | Неверные права/владелец тома | Исправьте `chown`/`chmod` или `securityContext` (fsGroup) в поде |
| **Sidecar не синхронизирует** | Неверная метка/неймспейс/путь | Сверьте `grafana_dashboard: "1"`, `searchNamespace`, путь назначения sidecar |
| **Дашборд не загружается** | Невалидный JSON или `uid` источника | `jq . file.json`; убедитесь, что `datasource.uid` совпадает с источником |
| **Изменения из UI «исчезли»** | Configuration drift после рестарта | Установите `editable: false` / `disableDeletion: true` |
| **SA/RBAC не применились** | Провиженинг только при старте | Перезапустите Grafana (watcher для SA/RBAC не работает) |
| **Секрет не подставился** | Переменная не в окружении процесса | `kubectl exec ... -- env \| grep VAR`; рестарт для ротации |

**Диагностика:** основные ошибки видны в логах Grafana (`logger=provisioning`, `logger=provisioning.alerting`, `logger=provisioning.dashboard`). Быстрая проверка: `docker logs grafana 2>&1 | grep -i provisioning` или `kubectl logs -n monitoring deploy/my-grafana | grep -i provisioning`. Статус ресурсов — через HTTP API (`/api/datasources`, `/api/search`, `/api/ruler/...`).

### Рекомендации по эксплуатации

- **Фиксируйте `uid`** для всех дашбордов и источников — гарантирует стабильность ссылок и idempotency.
- **Защищайте от дрейфа**: `editable: false` + `allowUiUpdates: false` + `disableDeletion: true` в production.
- **Один логический ресурс — один файл**; используйте префиксы `10-`, `20-` для детерминированного порядка применения.
- **Секреты вне Git**: `${VAR}` + Vault/Kubernetes Secret; добавьте `provisioning/` в `.gitignore` для локальных секрет-файлов.
- **Монтируйте read-only** (`ro`), где возможно, чтобы UI не мог изменить файлы провайдеров.
- **Валидируйте в CI**: `yamllint provisioning/**/*.yaml` и `jq . dashboards/**/*.json` до merge.
- **Git как источник истины**: Code Review + PR; для drift-контроля в динамике комбинируйте с Terraform/MaC (см. [Monitoring as Code](./monitoring_as_code.md)).
- **Не дублируйте управление**: один ресурс — либо файловый провиженинг, либо Terraform, не оба сразу.

### Ограничения и особые случаи

- **Односторонняя синхронизация**: провиженинг не пишет изменения из UI обратно в файлы. Это по дизайну; защищайтесь флагами `editable`/`disableDeletion`.
- **Hot reload ограничен**: источники данных и дашборды переприменяются при изменении файлов; сервисные аккаунты, RBAC и плагины применяются **только при старте** (нужен рестарт).
- **Интерполяция только при загрузке**: ротация секрета требует перезапуска Grafana, чтобы процесс перечитал переменные окружения.
- **Конфликты порядка**: при нескольких файлах одного типа побеждает файл позже по алфавиту — используйте префиксы.
- **`foldersFromFilesStructure` (v11+)** требует `updateIntervalSeconds` и поддерживается только для файловых провайдеров дашбордов.
- **Alerting/plugins** могут требовать перезапуска даже при изменении файлов в некоторых версиях — проверяйте логи после правок.
- **Двойное управление**: файловый провиженинг и Terraform на одном ресурсе конфликтуют; выберите один подход per-ресурс.
- **Версии**: сервисные аккаунты и RBAC-провиженинг доступны с v11; `contactpoints/`/`policies/` — с v10. Фиксируйте версию Grafana в CI-образе.

### См. также

- [Официальная документация по провиженингу](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [Провиженинг алертов](./alerting/provisioning.md) — подробные примеры для правил и политик
- [Управление пользователями и аутентификация](./grafana_user_management_and_authentication.md) — подробности управления ролями RBAC
