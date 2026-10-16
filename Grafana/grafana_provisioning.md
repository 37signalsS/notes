# Grafana: Провиженинг

**Актуально для:** Grafana 13.2.x / 12.x (LTS)

## Определения

**Провиженинг (Provisioning)** — подход Infrastructure as Code (IaC) для автоматизированного управления конфигурацией Grafana. Он позволяет декларативно описывать источники данных, дашборды, правила оповещений, конфигурацию плагинов и роли RBAC через конфигурационные файлы (YAML/JSON).

**File-based provisioning** — механизм, при котором Grafana сама читает конфигурационные файлы из файловой системы (директория `provisioning`) при старте и, для части ресурсов, периодически (hot reload). Это отличает его от управления через HTTP API / Terraform, где изменения применяются по явному запросу извне. Провиженинг идеален для **bootstrap**-конфигурации (начальное состояние инстанса), тогда как API/Terraform — для динамического управления в рамках GitOps (см. [Monitoring as Code](./monitoring_as_code.md)).

**Связанные темы:**
- [Обзор Grafana](./grafana_overview.md) — общая информация о платформе
- [Monitoring as Code (MaC)](./monitoring_as_code.md) — концепция и GitOps-пайплайны
- [Источники данных](./grafana_datasources.md) — детали настройки подключений
- [Дашборды](./grafana-dashboards.md) — создание и управление визуализациями
- [Плагины](./grafana_plugins.md) — автоматизация установки расширений
- [Fine-grained RBAC](./grafana_rbac_fine_grained.md) — кастомные роли и права

### Что можно провижинить файлами

| Тип ресурса | Директория | Обновление без рестарта | Примечание |
| :--- | :--- | :--- | :--- |
| Источники данных (Data Sources) | `datasources/` | Да | Регулярное переприменение; поле `version` защищает от отката |
| Дашборды (провайдеры + JSON) | `dashboards/` | Да | Опрос/watcher по `updateIntervalSeconds` |
| Alerting: правила, контакт-пойнты, политики, mute timings, шаблоны | `alerting/` | Да | Полное описание — [Провиженинг алертов](./alerting/provisioning.md) |
| Конфигурация плагинов (app plugins) | `plugins/` | Нет (при старте) | Только настройки **уже установленных** app-плагинов, не их установка |
| RBAC: кастомные роли и назначения | `access-control/` | Да (перечитывается в рантайме) | Только Grafana **Enterprise**, self-managed |

> **Что НЕ провижинится файлами.** Сервисные аккаунты, пользователи, организации и плейлисты не имеют файлового провиженинга. Они создаются через HTTP API, Terraform или UI. Подробнее — в разделе «Ограничения и особые случаи».

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

Grafana сканирует директорию провиженинга при запуске и применяет конфигурации. Для источников данных и дашбордов изменения в файлах подхватываются «на лету» (Hot Reload) без перезагрузки сервиса.

**Как происходит загрузка:**
1. При старте Grafana определяет корневую директорию провиженинга: секция `[paths]`, ключ `provisioning` в `grafana.ini` (по умолчанию `/etc/grafana/provisioning`); переопределяется переменной окружения `GF_PATHS_PROVISIONING`.
2. В поддиректориях (`datasources/`, `dashboards/`, `plugins/`, `alerting/`) рекурсивно ищутся файлы с расширениями `.yaml`, `.yml`, `.json`.
3. Ресурсы применяются при старте: Grafana создаёт или обновляет объекты, совпадающие по `name`/`uid`.
4. Источники данных и дашборды далее отслеживаются: изменение файла приводит к переприменению без рестарта. Дашборды опрашиваются по `updateIntervalSeconds` (см. ниже про порог 10 секунд).
5. Логи загрузки помечены `logger=provisioning` — основной источник диагностики (см. раздел «Устранение неполадок»).

**Поле `version` у источников данных.** Если инстансов Grafana несколько, каждому источнику в конфигурации задают номер `version` и увеличивают его при изменении. Grafana обновляет источник, только если его версия в БД не превышает указанную в файле. Это защищает от перезаписи новой конфигурации старой при одновременном рестарте инстансов.

**Три ключевых переключателя защиты от дрейфа:**
- `editable` (на ресурсе дашборда/источника) — можно ли менять объект из UI.
- `allowUiUpdates` (только в `providers` дашбордов) — разрешать ли сохранение изменений дашборда из UI в БД Grafana (файл провайдера при этом не перезаписывается).
- `disableDeletion` (в `providers` дашбордов) — запрещать ли удаление дашборда из UI/при исчезновении файла.

Для production рекомендуется комбинация `editable: false` + `allowUiUpdates: false` + `disableDeletion: true`, чтобы состояние Git оставалось единственным источником истины.

> При каждом применении провиженинга Grafana **перезаписывает** дашборд в БД версией из файла и игнорирует поле `version` в JSON-модели дашборда. Если в UI сохранены изменения при `allowUiUpdates: true`, а затем обновлён файл — побеждает файл.

### Структура директорий

```
/etc/grafana/provisioning/
├── datasources/      # Источники данных (YAML)
├── dashboards/       # Описания провайдеров дашбордов (YAML) + JSON-модели
├── plugins/          # Конфигурация app-плагинов (apps:) — не установка плагинов
├── alerting/         # Unified Alerting
│   ├── rules/        # Alerting и Recording rules
│   ├── contactpoints/# Контакт-пойнты (каналы уведомлений)
│   ├── policies/     # Политики уведомлений (дерево маршрутизации)
│   ├── mute_timings/ # Интервалы подавления
│   └── templates/    # Go-шаблоны уведомлений
└── access-control/   # RBAC: кастомные роли и назначения (только Enterprise)
```

> Папка `notifiers/` из старых версий Grafana (legacy alerting) считается устаревшей; в Unified Alerting используются подпапки `alerting/`. Файлы алертинга могут лежать и в одной плоской папке `alerting/` — важен корневой ключ (`rules`/`contactPoints`/`policies`/`muteTimes`/`templates`), а не имя файла.

### Поддерживаемые окружения

| Окружение | Метод реализации |
| :--- | :--- |
| **Standalone** | Локальные файлы в `/etc/grafana/provisioning/` |
| **Docker** | Монтирование тома: `-v ./provisioning:/etc/grafana/provisioning:ro` |
| **Kubernetes** | ConfigMaps/Secrets + Helm `values.yaml` + `k8s-sidecar` |
| **IaC** | Terraform/OpenTofu (Grafana Provider), `gcx` CLI — см. [Monitoring as Code](./monitoring_as_code.md) |

### Безопасность и секреты

Провиженинг поддерживает интерполяцию переменных окружения во всех YAML/JSON-**файлах конфигурации**, включая секцию `secureJsonData` (Grafana подставляет значение из окружения процесса при загрузке). Это основной способ передачи паролей и токенов без коммита в Git.

Синтаксис: `$VAR_NAME` или `${VAR_NAME}`. Порядок подстановки:
1. Сначала раскрываются переменные вида `${VAR_NAME}`.
2. Затем — вида `$VAR_NAME`.

Из этого следует важный нюанс: если значение содержит символ `$` (например, пароль `Pa$sw0rd`), форма `${VAR_NAME}` даст двойное раскрытие — `${PASSWORD}` станет `Pa` (потому что `$sw0rd` будет принят за ещё одну переменную). Для значений с `$` используйте форму `$VAR_NAME` либо экранируйте символ двойным `$$`: `Pa$$sw0rd`.

> **Важно:** переменные окружения работают в **файлах конфигурации провиженинга**, но не в **определениях дашбордов** (JSON-моделях). Секреты передавайте через `secureJsonData` источника данных или конфигурацию провайдера, а не через модель дашборда.

Альтернативные паттерны для секретов:
- **Монтирование файла секрета** (Kubernetes Secret, Vault Agent sidecar, init-контейнер), который экспортирует переменную в окружение Grafana перед стартом.
- **Vault Agent sidecar** — паттерн, при котором агент Vault рендерит секреты в файл/переменные локально; см. [Vault Agent basics](../Vault/guides/vault_agent/basics.md).

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

- **Grafana**: 12.x (LTS) или 13.x (3.2.x — актуальная ветка). Файловый провиженинг RBAC требует Grafana **Enterprise**; остальные ресурсы доступны в OSS.
- **Доступ к ФС**: директория провиженинга смонтирована и читаема процессом Grafana (проверка: `ls -l /etc/grafana/provisioning` внутри контейнера/пода).
- **Секреты**: переменные окружения (`${VAR}`) или смонтированные секрет-файлы подготовлены **до** старта Grafana; не коммитятся в Git.
- **Сетевая доступность**: Grafana должна достигать `URL` источников данных (для `Server`/proxy доступа) — проверка `curl -v <URL>` из пода Grafana.
- **RBAC для API-методов** (Ansible/Terraform): выделенный Service Account с ролью Editor (или кастомной ролью); API-ключи (API keys) устарели и заменены сервисными аккаунтами. См. [Управление пользователями и аутентификация](./grafana_user_management_and_authentication.md).
- **Ограничение**: Unified Alerting не поддерживает dashboard-переменные в запросах правил оповещений (вычисляются сервером вне контекста дашборда).

### 1. Файловый провиженинг (Docker и Standalone)

#### Монтирование и запуск (Docker Compose)

```yaml
# docker-compose.yml (фрагмент)
services:
  grafana:
    image: grafana/grafana:13.2.3
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

# Источники, которые нужно удалить ПЕРЕД применением списка datasources
deleteDatasources:
  - name: Legacy-Influx
    orgId: 1

# Удалять провиженинные источники, исчезнувшие из файлов провиженинга
prune: true

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
    secureJsonData:
      basicAuthPassword: "${PROM_PASSWORD}" # Переменная окружения
```

**Ключи жизненного цикла:**
- `deleteDatasources` — список `{name, orgId}` источников, удаляемых до применения `datasources`.
- `prune: true` — при удалении источника из файла (или удалении самого файла) Grafana удаляет его и из БД.

**Валидация:**
```bash
curl -s -H "Authorization: Bearer <SA_TOKEN>" \
  http://grafana:3000/api/datasources/uid/prometheus-prod | jq '.id, .uid'
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
    folderUid: 'infra-folder' # Стабильный uid папки (опционально)
    type: file
    disableDeletion: true     # Запретить удаление из UI/при исчезновении файла
    updateIntervalSeconds: 30 # Интервал сканирования папки (см. про порог 10 c ниже)
    allowUiUpdates: false     # Запрет сохранения изменений из UI в БД
    options:
      path: /etc/grafana/provisioning/dashboards/json # Путь к JSON-файлам
      foldersFromFilesStructure: true # Создание вложенных папок по структуре ФС
```

**Порог `updateIntervalSeconds = 10`.** Механизм отслеживания изменений зависит от значения:
- **Больше 10 секунд** — Grafana опрашивает путь (polling) с этим интервалом.
- **10 секунд и меньше** — Grafana использует события файловой системы (watch). При монтировании через Docker bind mount или сетевые ФС события могут не доходить до процесса. В этом случае задайте `updateIntervalSeconds` больше 10, чтобы принудительно включить polling.

**`foldersFromFilesStructure`** воссоздаёт структуру каталогов диска как вложенные папки Grafana. Ограничения:
- Требует, чтобы `folder` и `folderUid` провайдера были **не заданы** (пусты).
- Дашборды в корне `path` попадают в корень Grafana.
- Глубина вложенности папок ограничена **4 уровнями**.

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

> **Дашборды v2 (dynamic dashboards, Grafana 12+).** Для них JSON-модель должна быть в Kubernetes-формате: `"kind": "Dashboard"`, `"apiVersion": "dashboard.grafana.app/v1"`, содержимое — в `metadata`/`spec`. Классический «плоский» JSON (как выше) используется для схемы Classic. При экспорте из UI Grafana 13 позволяет выбрать модель **Classic** или **V2 Resource**.

**Ожидаемый результат:** дашборд `System Health` появляется в папке `Infrastructure` (и во вложенных папках, если включён `foldersFromFilesStructure`).

**Валидация:**
```bash
curl -s -H "Authorization: Bearer <SA_TOKEN>" \
  http://grafana:3000/api/search?folderIds=1 | jq '.[].title'
# → "System Health"
```

**Типичные проблемы:**
- Дашборд не загрузился — невалидный JSON (проверьте `jq . dashboards/json/system-health.json`) или несовпадение `uid` источника с `datasource.uid` в панели.
- Папки из `foldersFromFilesStructure` не создаются — задан `folder`/`folderUid` (их нужно очистить).

#### Провиженинг конфигурации плагинов

Директория `plugins/` управляет **настройками** app-плагинов (не их установкой). Плагин должен быть уже установлен; провиженинг лишь задаёт его конфигурацию при старте.

```yaml
# /etc/grafana/provisioning/plugins/apps.yaml
apiVersion: 1
apps:
  - type: grafana-xyz-app        # Идентификатор типа плагина
    org_id: 1
    disabled: false
    jsonData:
      someSetting: value
    secureJsonData:
      apiToken: "${APP_API_TOKEN}"
```

> Установка плагинов выполняется отдельно: через `GF_INSTALL_PLUGINS`, `grafana-cli plugins install` или образ с предустановленными плагинами. См. [Плагины](./grafana_plugins.md).

### 2. Провиженинг в Kubernetes через Helm

Helm-чарт Grafana позволяет описывать ресурсы провиженинга в `values.yaml`.

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
          uid: loki
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
            "panels": []
          }
```

**Ожидаемый результат:** после `helm install`/`helm upgrade` дашборды и источники создаются в Grafana.

**Валидация:**
```bash
helm get values my-grafana -n monitoring | grep -A3 datasources
kubectl exec -n monitoring deploy/my-grafana -- curl -s \
  http://localhost:3000/api/datasources/uid/loki | jq '.uid'
# → "loki"
```

**Типичные проблемы:**
- Ресурсы не применились — `values.yaml` не содержит ключ `grafana.datasources` в нужном формате; проверьте `helm template` и логи пода.

### 3. Механизм Sidecar и ConfigMap в Kubernetes

Используется для динамического обнаружения дашбордов в кластере без перезагрузки Grafana.

#### Принцип работы

Контейнер `k8s-sidecar` (в чарте Grafana — `grafana-sc-dashboards`) сканирует ConfigMaps в указанных неймспейсах. При нахождении ConfigMap с правильной меткой (по умолчанию `grafana_dashboard: "1"`) он копирует JSON во временную директорию Grafana. Подробная настройка — в [Установке Grafana через Helm](./Installation/grafana_helm_installation.md).

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
      "uid": "biz-perf-001"
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

#### Подготовка дашбордов к Git (GitOps)

Перед коммитом JSON-модели дашборда в репозиторий выполните подготовительные шаги — это предотвращает конфликты при переносе между кластерами и делает дашборды переносимыми:

1. **Удалите поле `id`** — оно присваивается Grafana при первом импорте и привязано к конкретному инстансу. Оставляя его, вы рискуете перезаписать существующий дашборд вместо создания нового.
2. **Замените жёстко заданные UID источников данных на переменную** — иначе дашборд будет работать только с одним источником, привязанным к конкретному `uid`:

```json
{
  "templating": {
    "list": [
      {
        "name": "datasource",
        "type": "datasource",
        "query": "prometheus"
      }
    ]
  },
  "panels": [
    {
      "datasource": {"type": "prometheus", "uid": "${datasource}"}
    }
  ]
}
```

**Kustomize** удобно использовать для сборки ConfigMap с дашбордами из отдельных JSON-файлов. При этом обязательно устанавливайте `disableNameSuffixHash: true`, чтобы хеш-суффикс не создавал дубликаты дашбордов [подробности](../Kubernetes/ToolsUtilities/kustomize/kustomize_generators.md).

> **Структура папок по доменам** (пример): `dashboards/infrastructure/`, `dashboards/application/`, `dashboards/flux/` — при включённом `foldersFromFilesStructure` папки в Grafana создаются автоматически по структуре каталогов. См. также [практику в kube-prometheus-stack](../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/grafana_config.md#сценарий-4-провижининг-кастомных-дашбордов-через-configmap).

### 4. Автоматизация через API с использованием Ansible

Ansible позволяет динамически генерировать дашборды, используя шаблоны **Jinja2**, и развертывать их через API.

#### Динамическое развертывание (Service Accounts)

В современных версиях Grafana API-ключи (API keys) устарели и заменены **Service Accounts**. Токен сервисного аккаунта передаётся в модуль вместо API-ключа.

```yaml
- name: Deploy Dynamic Dashboard
  community.grafana.grafana_dashboard:
    grafana_url: "https://grafana.example.com"
    grafana_api_key: "{{ service_account_token }}"  # Токен SA (из Ansible Vault)
    state: present
    path: "/tmp/generated_dashboard.json"
    folder: "automated-dashboards"   # uid или имя папки назначения
    overwrite: true
    commit_message: "Updated via CI/CD pipeline"
```

> Модуль `community.grafana.grafana_dashboard` принимает токен в параметре `grafana_api_key`; для сервисного аккаунта в это поле подставляется его токен. Официальная коллекция `grafana.grafana` (модуль `grafana.grafana.dashboard`) — современная альтернатива, но её параметры отличаются (JSON-модель передаётся inline в `dashboard`, а не через `path`).

**Ожидаемый результат:** дашборд из `/tmp/generated_dashboard.json` создаётся (или перезаписывается) в папке `automated-dashboards`.

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

### 5. Провиженинг RBAC (Grafana Enterprise)

> Файловый провиженинг RBAC доступен **только в Grafana Enterprise** для self-managed инстансов. В Grafana Cloud используйте HTTP API или Terraform (см. [Fine-grained RBAC](./grafana_rbac_fine_grained.md)). В Grafana OSS RBAC недоступен — там есть только базовые организационные роли.

Файл в `access-control/` описывает кастомные роли и их назначения командам. Изменения перечитываются в рантайме без перезапуска Grafana.

```yaml
# /etc/grafana/provisioning/access-control/roles.yaml
apiVersion: 2
roles:
  - name: 'custom:dashboard-auditor'
    uid: 'customdashboardauditor1'
    description: 'Read-only access to a team folder'
    version: 1
    orgId: 1
    permissions:
      - action: 'dashboards:read'
        scope: 'folders:uid:team-alpha-folder'
teams:
  - name: 'Auditors'
    orgId: 1
    roles:
      - uid: 'customdashboardauditor1'
```

**Ожидаемый результат:** кастомная роль `custom:dashboard-auditor` создана и назначена команде `Auditors`.

**Валидация:**
```bash
curl -s -H "Authorization: Bearer <ADMIN_TOKEN>" \
  http://grafana:3000/api/access-control/roles | jq '.items[].name'
# → содержит "custom:dashboard-auditor"
```

**Типичные проблемы:**
- Роль не появилась — сначала убедитесь, что у вас Grafana Enterprise (в OSS файлы `access-control/` игнорируются); проверьте `logger=provisioning`.

### 6. Провиженинг оповещений (Unified Alerting)

Правила, папки, контакт-пойнты, политики и шаблоны оповещений описываются в директории `alerting/`. Это самостоятельная тема — полные примеры, схема конвейера `data`, mute timings и удаление ресурсов находятся в авторитетном файле [Провиженинг алертов](./alerting/provisioning.md).

Минимальный пример правила (файл `alerting/alert_rules.yaml`):

```yaml
# /etc/grafana/provisioning/alerting/alert_rules.yaml
apiVersion: 1
groups:
  - orgId: 1
    name: infra-alerts
    folder: Infrastructure
    interval: 1m
    rules:
      - uid: prometheus-prod-down
        title: Prometheus target down
        condition: A
        for: 5m
        noDataState: NoData
        execErrState: Error
        data:
          - refId: A
            datasourceUid: prometheus-prod
            relativeTimeRange:
              from: 300
              to: 0
            model:
              expr: 'up == 0'
              instant: true
              refId: A
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

**Вариант Б — Vault Agent sidecar (Kubernetes):** агент рендерит секрет в файл, init-контейнер экспортирует его в переменную окружения Grafana перед стартом (паттерн описан в [Vault Agent basics](../Vault/guides/vault_agent/basics.md)).

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

1.  **Фиксация UID**: Всегда жестко прописывайте `uid` в JSON-модели дашборда и в источнике данных. Если этого не сделать, Grafana создаст новый UID при каждом пересоздании, что приведет к появлению дубликатов и поломке внешних ссылок.
2.  **Configuration Drift**: При использовании провиженинга любые изменения, сделанные пользователем через UI, **не сохраняются** обратно в конфигурационные файлы. После перезапуска пода/сервиса Grafana вернет состояние, описанное в файлах. Для предотвращения путаницы устанавливайте `editable: false` (на ресурсах) и `allowUiUpdates: false` + `disableDeletion: true` (на провайдерах дашбордов).
3.  **Конфликты имен**: Имя JSON-файла не должно совпадать с именем директории провайдера в конфигурации, так как Grafana использует файловую систему как базу для формирования путей.
4.  **Переменные окружения**: Grafana поддерживает интерполяцию `$VAR`/`${VAR}` во всех файлах провиженинга, включая `secureJsonData`. Значения берутся из окружения процесса Grafana. Интерполяция выполняется один раз при загрузке файла и **не применяется** к определениям дашбордов. Для значений с символом `$` используйте форму `$VAR` или экранирование `$$`.
5.  **Несколько файлов одного типа**: разбивайте ресурсы по файлам, но избегайте пересечения `name`/`uid`. Для источников данных порядок и защита от отката регулируются полем `version`. Для предсказуемости используйте префиксы имён файлов (`10-`, `20-`) и один ресурс на файл.

### Устранение неполадок

| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Ресурс не появился** | Ошибка синтаксиса YAML/JSON | Проверьте `docker logs \| grep provisioning`; валидируйте `yamllint` и `jq .` |
| **"Datasource already exists"** | Дублирующийся `name`/`uid` в разных файлах | Задайте уникальные `name` + `uid`; используйте префиксы файлов |
| **"401 Unauthorized" от бэкенда** | Неверный секрет в `secureJsonData` | Проверьте, что `${VAR}` передана в окружение Grafana |
| **"permission denied" на чтение файла** | Неверные права/владелец тома | Исправьте `chown`/`chmod` или `securityContext` (fsGroup) в поде |
| **Дашборд не обновляется после правки файла** | `updateIntervalSeconds` <= 10 и не доходят события ФС | Задайте `updateIntervalSeconds` > 10 (polling) |
| **Папки не создаются при `foldersFromFilesStructure`** | Задан `folder`/`folderUid` | Очистите оба поля провайдера |
| **Sidecar не синхронизирует** | Неверная метка/неймспейс/путь | Сверьте `grafana_dashboard: "1"`, `searchNamespace`, путь назначения sidecar |
| **Дашборд не загружается** | Невалидный JSON или `uid` источника | `jq . file.json`; убедитесь, что `datasource.uid` совпадает с источником |
| **Дашборд v2 не грузится из JSON** | Классический JSON вместо Kubernetes-формата | Используйте `kind: Dashboard`, `apiVersion: dashboard.grafana.app/v1` |
| **Изменения из UI «исчезли»** | Configuration drift после рестарта | Установите `editable: false` / `disableDeletion: true` |
| **Роль RBAC не применилась** | Нет лицензии Grafana Enterprise | Проверьте лицензию; в OSS RBAC недоступен |
| **Секрет не подставился** | Переменная не в окружении процесса | `kubectl exec ... -- env \| grep VAR`; рестарт для ротации |

**Диагностика:** основные ошибки видны в логах Grafana (`logger=provisioning`, `logger=provisioning.alerting`, `logger=provisioning.dashboard`). Быстрая проверка: `docker logs grafana 2>&1 | grep -i provisioning` или `kubectl logs -n monitoring deploy/my-grafana | grep -i provisioning`. Статус ресурсов — через HTTP API (`/api/datasources`, `/api/search`, `/api/ruler/...`).

### Рекомендации по эксплуатации

- **Фиксируйте `uid`** для всех дашбордов и источников — гарантирует стабильность ссылок и idempotency.
- **Защищайте от дрейфа**: `editable: false` + `allowUiUpdates: false` + `disableDeletion: true` в production.
- **Один логический ресурс — один файл**; используйте префиксы `10-`, `20-` для читаемости и предсказуемости.
- **Секреты вне Git**: `${VAR}` + Vault/Kubernetes Secret; добавьте локальные секрет-файлы в `.gitignore`.
- **Монтируйте read-only** (`ro`), где возможно, чтобы UI не мог изменить файлы провайдеров.
- **Валидируйте в CI**: `yamllint provisioning/**/*.yaml` и `jq . dashboards/**/*.json` до merge.
- **Git как источник истины**: Code Review + PR; для drift-контроля в динамике комбинируйте с Terraform/MaC (см. [Monitoring as Code](./monitoring_as_code.md)).
- **Не дублируйте управление**: один ресурс — либо файловый провиженинг, либо Terraform, не оба сразу.

### Ограничения и особые случаи

- **Односторонняя синхронизация**: провиженинг не пишет изменения из UI обратно в файлы. Это по дизайну; защищайтесь флагами `editable`/`disableDeletion`.
- **Автоматическое применение при изменении файла** работает для источников данных и дашбордов (watcher/poll). Конфигурация плагинов применяется **только при старте**; RBAC перечитывается в рантайме.
- **Интерполяция только при загрузке**: ротация секрета требует перезапуска Grafana, чтобы процесс перечитал переменные окружения.
- **Не провижинится файлами**: сервисные аккаунты (HTTP API `/api/serviceaccounts`, Terraform `grafana_service_account`), пользователи (API/LDAP/SSO), организации, плейлисты (UI или HTTP API `playlist.grafana.app/v1`, Grafana 12+).
- **RBAC-провиженинг — только Enterprise.** В OSS RBAC недоступен (файлы `access-control/` игнорируются); кастомные роли задавайте через API/Terraform на Enterprise-инстансе.
- **`prune: true` и `deleteDatasources`** применяются к источникам данных; для дашбордов удаление файла удаляет дашборд из БД, если не задан `disableDeletion: true`.
- **`foldersFromFilesStructure`** требует пустых `folder`/`folderUid`; глубина вложенных папок ограничена 4 уровнями.
- **Дашборды v2 / dynamic dashboards** требуют Kubernetes-формата JSON при файловом провиженинге.
- **Конфликты порядка**: при нескольких файлах одного типа не полагайтесь на порядок — используйте уникальные `name`/`uid`; для источников данных задавайте `version`.
- **Версии**: файловый провиженинг RBAC требует Enterprise; для Git Sync и CRD — Grafana 13.x (см. [Monitoring as Code](./monitoring_as_code.md)). Фиксируйте версию Grafana в CI-образе.

### См. также

- [Официальная документация по провиженингу](https://grafana.com/docs/grafana/latest/administration/provisioning/)
- [Провиженинг алертов](./alerting/provisioning.md) — подробные примеры для правил, политик и шаблонов
- [Fine-grained RBAC](./grafana_rbac_fine_grained.md) — кастомные роли через API/Terraform
- [Управление пользователями и аутентификация](./grafana_user_management_and_authentication.md) — роли, сервисные аккаунты
- [Источники данных](./grafana_datasources.md) — параметры подключений
- [Дашборды](./grafana-dashboards.md) — модель дашборда, папки
- [Плагины](./grafana_plugins.md) — установка и конфигурация расширений
- [Monitoring as Code](./monitoring_as_code.md) — Git Sync, Terraform, `gcx`
- [Установка Grafana через Helm](./Installation/grafana_helm_installation.md) — sidecar и values.yaml
