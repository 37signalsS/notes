# Monitoring as Code (MaC): Grafana и GitOps

**Актуально для:** Grafana 13.2.x (нативный Git Sync, CLI `gcx`)

**Monitoring as Code (MaC)** — методология управления инфраструктурой наблюдаемости, при которой конфигурации инструментов (дашборды, источники данных, правила алертинга) описываются декларативно в виде кода, проходят через процесс Code Review и автоматически развертываются через CI/CD или GitOps-контроллеры.

## Определения

- **MaC (Monitoring as Code)** — применение принципов Software Engineering (версионирование, тестирование, автоматизация) к процессам мониторинга.
- **GitOps в мониторинге** — использование Git как единственного источника правды для всех объектов наблюдаемости. Изменения в Git автоматически синхронизируются с инстансами Grafana.
- **Dashboard-as-Code (DaC)** — подмножество MaC, сфокусированное на генерации и управлении JSON-моделями дашбордов через шаблонизаторы и SDK.
- **Observability as Code (OaC)** — более широкая парадигма, которой Grafana Labs обозначает управление как кодом всего стека наблюдаемости (дашборды, алерты, SLO, источники данных). MaC — частный случай OaC.
- **Sidecar (k8s-sidecar)** — вспомогательный контейнер, работающий рядом с Grafana, который обнаруживает ConfigMap с дашбордами в Kubernetes и загружает их "на лету".
- **Провиженинг (Provisioning)** — подход Infrastructure as Code (IaC) для декларативного описания ресурсов Grafana (источники данных, дашборды, алерты, плагины) через YAML/JSON-файлы в директории `/etc/grafana/provisioning`.
- **Конфигурационный дрейф (Configuration Drift)** — расхождение между задекларированным состоянием в Git и фактическим состоянием Grafana, возникающее из-за ручных правок в UI. MaC устраняет дрейф через регулярную сверку (reconcile) или запрет ручного редактирования (`editable: false`).
- **gcx (Grafana CLI)** — актуальная CLI-утилита Grafana Labs для управления ресурсами Grafana как кодом: `gcx resources pull/push/validate`, `gcx dev ...`. Пришла на смену `grafanactl`, который, в свою очередь, заменил Grizzly. GA с июля 2026; полноценно поддерживается Grafana 13+ (OSS/Enterprise и Cloud), на Grafana 12.x ядро работает, но не развивается активно.
- **Grizzly (`grr`) — устаревшая** — первая CLI-утилита Grafana Labs для управления ресурсами через YAML-обёртки над JSON-моделями. **Удалена и не поддерживается**; её функциональность поглощена `grafanactl`, а затем `gcx`. Приводится только как исторический контекст.
- **grafanactl — устаревшая** — CLI, заменившая Grizzly; сама выведена из эксплуатации в пользу `gcx` (репозиторий заархивирован 1 июня 2026). Миграция выполняется заменой `grafanactl` → `gcx` (для `grafanactl resources serve` — `gcx dev serve`).
- **Jsonnet / Grafonnet** — функциональный язык конфигурации и библиотека для генерации типовых JSON-дашбордов из параметризованных шаблонов (Dashboard-as-Code). Актуальна новая `grafonnet`; старая `grafonnet-lib` — deprecated.
- **grafana-foundation-sdk** — официальные SDK (Go, TypeScript, Python) для описания дашбордов типизированным кодом; интегрированы в `gcx dev` (`gcx dev scaffold`, `gcx dev import`).
- **Git Sync (Grafana 13.x)** — нативная двусторонняя синхронизация Grafana с Git-репозиторием без внешних sidecar-контейнеров — редактирование в UI коммитится в Git, а изменения из Git подтягиваются в инстанс.
- **Repository (ресурс Git Sync)** — CRD группы `provisioning.grafana.app/v0alpha1`, описывающий подключение группы репозиториев к инстансу: URL, ветку, путь внутри репозитория, интервал синхронизации, sync target и набор workflows (`write` — прямые коммиты, `branch` — коммиты через PR).
- **Connection (ресурс Git Sync)** — CRD той же группы, описывающий аутентификацию Grafana к Git-провайдеру. Нужен при подключении через GitHub App; один `Connection` переиспользуется несколькими `Repository`.
- **Service Account (Сервисный аккаунт)** — токен-идентификация для CI/CD и API-клиентов (вместо пользовательского логина), с назначенной ролью (Viewer/Editor/Admin).
- **Declarative config (Декларативная конфигурация)** — описание желаемого состояния ("что должно быть"), а не последовательности шагов ("как сделать").

---

## Базовые концепции

### Жизненный цикл MaC

Процесс управления мониторингом как кодом состоит из трех уровней:

1.  **Генерация (Generation)**: Использование языков высокого уровня (Jsonnet, Go/TypeScript/Python через `grafana-foundation-sdk`) вместо ручного редактирования гигантских JSON-файлов. Результат — стабильная JSON-модель дашборда.
2.  **Валидация (Validation)**: Проверка синтаксиса, линтинг PromQL-запросов и соблюдение стандартов оформления до деплоя (линтеры, `promtool`, `gcx dev lint`, CI-гейты).
3.  **Доставка (Delivery)**: Синхронизация кода с Grafana через API (`gcx`, Terraform), провиженинг-файлы или нативные механизмы Kubernetes.

```text
Git ──▶ CI (lint/test) ──▶ gcx / Terraform / Provisioning / Sidecar / Git Sync ──▶ Grafana
  ▲                                                                                   │
  └──────────────────────────── Reconcile / Drift detection ◀─────────────────────────┘
```

### Сравнение инструментов

| Инструмент | Подход | Когда использовать |
| :--- | :--- | :--- |
| **gcx** | CLI / YAML | Актуальная CLI Grafana Labs. Синхронизация дашбордов, папок, алертов и источников через API. Идеально для небольших команд и CI/CD. |
| **Terraform / OpenTofu** | IaC / HCL | Управление всей инфраструктурой Grafana (пользователи, папки, источники данных, дашборды, алерты) декларативно, с состоянием и графом зависимостей. |
| **Jsonnet (Grafonnet) / grafana-foundation-sdk** | Templating / SDK | Массовое создание типовых дашбордов для сотен однотипных микросервисов. |
| **Grafana Operator** | K8s Operator | Нативное управление инстансами и дашбордами внутри кластера Kubernetes (CRD). |
| **Git Sync (13.x)** | Нативный Git | Двусторонняя синхронизация с Git без sidecar; редактирование в UI → авто-коммит/PR. |
| **k8s-sidecar + ArgoCD** | GitOps | Синхронизация ConfigMap с дашбордами в Kubernetes-кластерах. |
| **(legacy) Grizzly** | CLI / YAML | Не поддерживается. Для новых проектов используйте `gcx`. |

### Подходы к автоматизации мониторинга

**1. Provisioning (File-based):**
- Описание источников данных, дашбордов и алертов в YAML/JSON файлах.
- Grafana сканирует директорию `/etc/grafana/provisioning` при запуске (и подхватывает изменения "на лету" — Hot Reload — для большинства ресурсов).
- Идеально для статичных конфигураций, не требующих частых изменений.

**2. GitOps через Kubernetes Sidecar:**
- Дашборды и алерты хранятся в Git в виде ConfigMap.
- ArgoCD/Flux синхронизируют ConfigMap в кластере.
- Sidecar-контейнер (`k8s-sidecar`) обнаруживает ConfigMap и загружает их в Grafana.

**3. Infrastructure as Code (Terraform / gcx):**
- Terraform управляет всей инфраструктурой Grafana (пользователи, папки, источники данных, дашборды, алерты) с ведением состояния.
- gcx описывает ресурсы в YAML/JSON и синхронизирует их через API без написания HCL и без управления состоянием (`resources pull` / `resources push`).

**4. API-based (Programmatic):**
- Использование Grafana HTTP API для создания/обновления ресурсов.
- Позволяет генерировать дашборды динамически (например, для каждого микросервиса свой дашборд).

**5. Native Git Sync (Grafana 13.x):**
- Встроенная двусторонняя синхронизация: правки в UI коммитятся в Git (и оформляются PR), а изменения из репозитория подтягиваются в инстанс.
- Вытесняет внешние sidecar-контейнеры для сценариев "Git как источник правды".

### Сравнение подходов

| Подход | Сложность | Когда использовать |
| :--- | :--- | :--- |
| **Provisioning** | Низкая | Статичные дашборды, неизменные источники данных |
| **GitOps + Sidecar** | Средняя | Kubernetes-среды, непрерывная доставка |
| **Terraform / gcx** | Средняя | Управление несколькими инстансами Grafana; Terraform — когда нужно состояние и граф зависимостей |
| **API-based** | Высокая | Динамическая генерация ресурсов, интеграция с CI/CD |
| **Native Git Sync** | Низкая | Grafana 13.x, двусторонняя синхронизация без операторов |

### Порядок применения и разрешение зависимостей

- **Зависимости имеют значение:** источники данных должны быть провиженины до дашбордов, ссылающихся на них, а папки (`folder`) — до ресурсов, помещаемых в папку.
- **Провиженинг** применяет ресурсы в порядке: `datasources` → `dashboards` → `alerting`/`contactpoints`/`policies`.
- **Terraform** требует явных `depends_on` (например, `grafana_dashboard` зависит от `grafana_folder` и `grafana_data_source`) для корректного графа зависимостей.
- **gcx** упорядочивает ресурсы автоматически: папки выталкиваются (push) раньше дашбордов, а операция идемпотентна — повторный `push` даёт тот же результат.
- **UID-стабильность:** фиксированный `uid` дашборда гарантирует, что ссылки (`/d/<uid>/...`), импорт и перекрёстные переходы не сломаются при повторном применении кода.

---

## Практические сценарии

### Предварительные требования

- **Версия Grafana**: 13.2.x (актуальная линия; Git Sync GA начиная с 13.0). CLI `gcx` полноценно поддерживает Grafana 13+ и работает с 12+. См. [Обзор Grafana](./grafana_overview.md).
- **Git-репозиторий**: с дашбордами/алертами в формате JSON (или генерируемыми из Jsonnet/YAML/Go-кода).
- **Доступы**: Service Account с ролью Editor/Admin и токеном, либо SSH-ключ/GitHub App/Personal Access Token (для Git Sync), либо `kubectl` (для Kubernetes-сценариев).
- **Окружение CI/CD**: GitLab CI, GitHub Actions или ArgoCD/Flux для автоматической доставки.
- **Секреты**: внешнее хранилище (Vault, SOPS, Kubernetes Secret) — пароли и токены не хранятся в Git в открытом виде.
- **Ограничение**: Unified Alerting в правилах алертинга не поддерживает dashboard-переменные (они вычисляются сервером вне контекста дашборда).

### Сценарий 1: GitOps через ConfigMap Sidecar (ArgoCD)

Это стандартный путь для Kubernetes-сред, использующих `kube-prometheus-stack`.

1.  **Описание дашборда**: Дашборд хранится в Git в виде JSON или генерируется из Jsonnet.
2.  **Манифест ConfigMap**:
    ```yaml
    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: my-app-dashboard
      namespace: monitoring
      labels:
        grafana_dashboard: "1" # Метка для обнаружения sidecar-ом
      annotations:
        grafana_folder: "Applications" # В какую папку Grafana положить дашборд
    data:
      dashboard.json: |
        { ... JSON ... }
    ```
3.  **Синхронизация**: ArgoCD следит за репозиторием и обновляет ConfigMap. Sidecar в поде Grafana замечает изменение и обновляет дашборд в интерфейсе без перезагрузки.

**Ожидаемый результат:** дашборд появляется в папке `Applications`; при изменении JSON в Git и синхронизации ArgoCD дашборд обновляется в течение интервала сканирования sidecar (по умолчанию ~10–30 c).

**Валидация:**
```bash
# Дашборд загружен sidecar-ом (uid задаётся в JSON)
curl -s -H "Authorization: Bearer <SA_TOKEN>" \
  http://grafana.monitoring.svc:3000/api/dashboards/uid/<DASHBOARD_UID> | jq '.dashboard.title'
# → "My App" (если дашборд загружен)

# Логи sidecar-контейнера пода Grafana
kubectl -n monitoring logs deploy/kube-prometheus-stack-grafana -c grafana-sc-dashboard
# → "Dashboard ... has been added/changed"
```

**Типичные проблемы:**
- Дашборд не появляется — отсутствует метка `grafana_dashboard: "1"` на ConfigMap.
- ConfigMap > 1 МБ — Kubernetes отклоняет; включите `sidecar.dashboards.GZIP: true` в Helm values или разбейте на несколько ConfigMap.
- Дашборд попадает в `General` — не включено группирование по папкам. В `kube-prometheus-stack` задайте `folderAnnotation: grafana_folder` и `provider.foldersFromFilesStructure: true` (см. [Установку Grafana через Helm](./Installation/grafana_helm_installation.md)).

### Сценарий 2: CLI `gcx` в CI/CD пайплайне

**gcx** — актуальная CLI-утилита Grafana Labs для управления ресурсами Grafana (дашборды, папки, алерты, источники данных) как кодом. Она пришла на смену устаревшей `grafanactl`, которая, в свою очередь, заменила Grizzly. Ресурсы хранятся локально (по умолчанию в каталоге `./resources`) и синхронизируются командами `gcx resources pull` (выгрузить из Grafana) и `gcx resources push` (загрузить в Grafana).

**Пайплайн валидации (GitLab CI):**
```yaml
validate_dashboards:
  stage: test
  script:
    - gcx resources pull --path ./resources -o yaml   # снимок текущего состояния (для diff)
    - gcx resources validate -p ./resources           # проверка схемы ресурсов
    - gcx dev lint run ./resources                    # линтинг (встроенные и кастомные Rego-правила)
```

**Пайплайн деплоя:**
```yaml
deploy_prod:
  stage: deploy
  script:
    - gcx resources push -p ./resources --context prod --dry-run   # предпросмотр изменений
    - gcx resources push -p ./resources --context prod             # применение
```

**Ожидаемый результат:** `gcx resources validate` и `gcx dev lint run` завершаются без ошибок; `gcx resources push` создаёт/обновляет ресурсы в Grafana.

**Валидация:**
```bash
gcx resources get dashboards     # → список дашбордов, управляемых в текущем контексте
gcx resources list-types         # → доступные типы ресурсов (dashboards, folders, alert rules, datasources, ...)
```

**Миграция с `grafanactl` на `gcx`.** Репозиторий `grafanactl` заархивирован 1 июня 2026, все возможности перенесены в `gcx`. Миграция сводится к поиску-замене: команды `grafanactl ...` → `gcx ...`, а `grafanactl resources serve` заменяется на `gcx dev serve`. Файлы ресурсов и контексты (`config`) сохраняют совместимость, поэтому существующие пайплайны меняются минимально.

**Типичные проблемы:**
- `401 Unauthorized` — неверный/просроченный токен Service Account; проверьте контекст (`--context`) и роль аккаунта.
- `gcx dev lint run` ругается на правила — исправьте ресурс или добавьте исключение; список правил: `gcx dev lint list-rules`.
- Пустой результат `pull` — ресурсы, управляемые другим инструментом (Terraform, Git Sync), не выгружаются без флага `--include-managed`.

### Сценарий 3: Terraform для self-hosted Grafana

Для управления пользователями, папками, источниками данных, дашбордами и алертами в Grafana OSS/Enterprise используется официальный провайдер `grafana/grafana`. Провайдер хранит состояние и позволяет описывать всю конфигурацию декларативно.

```hcl
resource "grafana_folder" "team_a" {
  title = "Team A"
  uid   = "team-a"
}

resource "grafana_data_source" "prometheus" {
  type       = "prometheus"
  name       = "Prometheus"
  url        = "http://prometheus:9090"
  uid        = "prometheus"
  is_default = true
}

resource "grafana_service_account" "ci_cd" {
  name = "CI/CD Deployer"
  role = "Admin"
}

resource "grafana_service_account_token" "ci_cd" {
  name               = "ci-cd-token"
  service_account_id = grafana_service_account.ci_cd.id
}

resource "grafana_dashboard" "metrics" {
  config_json = file("dashboards/service_metrics.json")
  folder      = grafana_folder.team_a.uid
  overwrite   = true
}

output "grafana_token" {
  value     = grafana_service_account_token.ci_cd.key
  sensitive = true
}
```

**Ожидаемый результат:** `terraform apply` создаёт папку, источник данных, сервисный аккаунт с токеном и загружает дашборд в папку `Team A`; токен выводится как sensitive-значение.

**Валидация:**
```bash
terraform plan   # → показывает ресурсы к созданию/изменению
terraform apply  # → Apply complete! Resources: N added
```

**Типичные проблемы:**
- `overwrite = false` + существующий дашборд — ошибка; выставьте `overwrite = true` для управления через код.
- Дашборд не видит источник — убедитесь, что в JSON дашборда `datasource` ссылается на `uid` созданного `grafana_data_source`.
- Циклическая зависимость — не ссылайтесь дашбордом на ресурс, который зависит от самого дашборда.

### Сценарий 4: Нативная синхронизация Git Sync (Grafana 13.x)

Git Sync — нативная двусторонняя синхронизация дашбордов и папок Grafana с Git-репозиторием. Она достигла GA в Grafana 13.0 (апрель 2026) для Cloud, OSS и Enterprise: в 13.x feature toggle `provisioning` включён по умолчанию, ручная настройка не требуется. Для большинства сценариев "Git как источник правды" Git Sync заменяет внешние sidecar-контейнеры. Поддерживаются GitHub, GitHub Enterprise, GitLab, Bitbucket и любой Git-провайдер (тип Pure Git). Инстанс опрашивает репозиторий с настраиваемым интервалом либо мгновенно по webhook.

**Предварительные требования:**
- Grafana 13.x (Git Sync GA; исторически на 12.4 self-managed провайдеры включались вручную через `[provisioning] repository_types`).
- Права Grafana Admin в организации.
- Git-репозиторий с дашбордами в формате JSON; для подключения — Personal Access Token, SSH-ключ или GitHub App.
- Сетевая доступность Git-сервера из сети Grafana; для webhook — публичный эндпоинт Grafana (обратный трафик от Git-провайдера).

**Настройка через UI:**
1.  **Вход:** пользователь с флагом Grafana Admin.
2.  **Раздел:** `Administration → General → Provisioning`.
3.  **Провайдер:** выберите GitHub/GitLab/Bitbucket/Pure Git и настройте аутентификацию (токен либо GitHub App).
4.  **Репозиторий:** ветка (по умолчанию `main`) и, опционально, путь внутри репозитория.
5.  **Sync target:** папка с именем репозитория (`folder`, по умолчанию) либо раскладка ресурсов на верхнем уровне (`folderless`).
6.  **Параметры:** интервал синхронизации, `Read only`, `Enable pull request`, `Enable push to configured branch`, генерация превью дашбордов, webhook.

Дефолтный интервал опроса: 60 c для OSS/Enterprise (300 c для Cloud). На self-managed число подключений по умолчанию равно 10, но это не жёсткий потолок — лимит поднимается в `grafana.ini` секцией `[provisioning] max_repositories` (значение `0` снимает ограничение); число ресурсов на репозиторий по умолчанию не ограничено (`max_resources_per_repository = 0`). Для webhook действуют лимиты Git-провайдера — например, GitHub допускает 20 webhook на каждый тип события и репозиторий.

**Настройка как код (CRD + gcx):** конфигурация Git Sync описывается ресурсами `provisioning.grafana.app/v0alpha1` (`Repository`, а для GitHub App — дополнительно `Connection`) и применяется через gcx.

```yaml
# git-sync/repository.yaml
apiVersion: provisioning.grafana.app/v0alpha1
kind: Repository
metadata:
  name: platform-dashboards
  namespace: default
spec:
  title: Platform Dashboards
  type: github
  sync:
    enabled: true
    intervalSeconds: 60
    target: folder
  workflows:
    - write   # прямые коммиты в ветку
    - branch  # коммиты через PR
  github:
    url: https://github.com/example/platform-dashboards
    branch: main
    path: grafana/
secure:
  token:
    create: '<GIT_PAT>'   # значение Personal Access Token; не коммитить
```

```bash
gcx resources push --path ./git-sync/
# → Repository создан; Grafana начинает синхронизацию указанной папки
```

> `spec.sync.target` принимает `folder` (по умолчанию) или `folderless` (ресурсы кладутся на верхний уровень без папки-обёртки). Поле `secure.token.create` содержит само значение токена, а не имя переменной окружения, поэтому файл с токеном не коммитится в Git — в CI он генерируется из секрета (Vault/SOPS) или значение задаётся через `gcx resources edit`.
>
> С Grafana 13.1.0 для Git Sync настраивается проверенная учётная запись с ключом подписи (GPG, SSH или S/MIME) — коммиты Grafana помечаются Git-провайдером как Verified.
>
> Для защиты от SSRF (Grafana 13.0.4 / 13.1.1+) Git Sync по умолчанию отвергает URL репозитория, хост которого резолвится в loopback/приватный/link-local адрес. Для self-hosted GitHub Enterprise, GitLab или Bitbucket во внутренней сети хост нужно внести в allowlist `[provisioning] allowed_git_urls` в `grafana.ini`.
>
> Альтернатива gcx для Git Sync as code — Terraform-ресурсы `grafana_apps_provisioning_repository_v0alpha1` и `grafana_apps_provisioning_connection_v0alpha1` официального провайдера `grafana/grafana`.

**Валидация:**
```bash
# Список репозиториев через CLI
gcx resources get repositories
# → platform-dashboards

# Либо в UI: Administration → General → Provisioning → вкладка Repositories

git -C /path/to/repo log --oneline -1
# → при сохранении правки в UI должен появиться новый коммит от Grafana
```

**Очистка:** отключите Git Sync в UI (`Administration → General → Provisioning → Repositories → Settings → Delete`) перед удалением репозитория, чтобы предотвратить автоматические коммиты от инстанса.

**Типичные проблемы:**
- `Git Sync не работает` — ошибки аутентификации/прав доступа; проверьте токен/SSH-ключ/GitHub App и доступность репозитория из сети Grafana.
- Конфликт при одновременных правках в UI и в Git — разрешается через PR-воркфлоу (включите `Enable pull request`) или приоритет ветки.
- Потеря дашбордов при апгрейде на 13.0.0 — известный migration-баг unified storage. Затрагивает только self-managed инстансы, у которых на 12.x были включены feature-toggle Git Sync (`provisioning`, `kubernetesClientDashboardsFolders`, `kubernetesDashboards`). Дистрибутив 13.0.0 снят с распространения, исправление вышло в 13.0.1, но апгрейд с 13.0.0 на 13.0.1 потерянные данные не восстанавливает: сначала восстановите БД из бэкапа, затем обновитесь до 13.0.1+. Всегда делайте бэкап БД перед мажорным апгрейдом (см. [Резервное копирование](./grafana_backup_restore.md)).

### Сценарий 5: File-based Provisioning (YAML)

Декларативное описание источника данных и провайдера дашбордов в файлах (см. детали в [Провиженинг](./grafana_provisioning.md)).

```yaml
# /etc/grafana/provisioning/datasources/prom.yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    uid: prometheus
    url: http://prometheus:9090
    isDefault: true
    editable: false
```

```yaml
# /etc/grafana/provisioning/dashboards/default.yaml
apiVersion: 1
providers:
  - name: "Default"
    orgId: 1
    folder: "Applications"
    type: file
    disableDeletion: true
    editable: false
    options:
      path: /var/lib/grafana/dashboards
```

**Ожидаемый результат:** при старте (и Hot Reload) Grafana регистрирует источник `Prometheus` и загружает дашборды из `/var/lib/grafana/dashboards` в папку `Applications` как `editable: false`.

**Валидация:**
```bash
curl -s -H "Authorization: Bearer <SA_TOKEN>" \
  http://localhost:3000/api/datasources/uid/prometheus | jq '.name'
# → "Prometheus"
```

**Типичные проблемы:**
- Дашборды не загружаются — неверный `options.path` или дашборд не валиден по JSON.
- Ручные правки затираются — ожидаемое поведение при `editable: false`; правьте код в Git.

### Сценарий 6: Dashboard-as-Code на Jsonnet (Grafonnet) и grafana-foundation-sdk

Генерация типовых дашбордов для множества сервисов из одного шаблона.

**Jsonnet + Grafonnet.** Актуальная библиотека — `grafonnet` (устанавливается через jsonnet-bundler). Старая `grafonnet-lib` объявлена deprecated и не должна использоваться в новых проектах.

```bash
# Установка jsonnet-bundler и библиотеки
go install github.com/jsonnet-bundler/jsonnet-bundler/cmd/jb@latest
jb init
jb install github.com/grafana/grafonnet/gen/grafonnet-latest@main
```

```jsonnet
// dashboard.jsonnet
local g = import 'github.com/grafana/grafonnet/gen/grafonnet-latest/main.libsonnet';

g.dashboard.new('Service: %s' % std.extVar('service'))
+ g.dashboard.withUid('svc-%s' % std.extVar('service'))
+ g.dashboard.withPanels([
  g.panel.timeSeries.new('CPU')
  + g.panel.timeSeries.queryOptions.withTargets([
    g.query.prometheus.new(
      'prometheus',
      'rate(container_cpu_usage_seconds_total{service="%s"}[5m])' % std.extVar('service'),
    ),
  ])
  + g.panel.timeSeries.standardOptions.withUnit('percentunit')
  + g.panel.timeSeries.gridPos.withW(24)
  + g.panel.timeSeries.gridPos.withH(8),
])
```

**Сборка и применение:**
```bash
jsonnet -J vendor -V service=orders dashboard.jsonnet > orders.json
gcx resources push -p ./resources   # либо Terraform, если состояние ведётся в нём
```

> Grafonnet помечен авторами как experimental и не предназначен для production-нагрузок; для стабильных проектов предпочтительнее генерация через grafana-foundation-sdk либо прямая правка JSON.

**grafana-foundation-sdk.** Официальные SDK (Go, TypeScript, Python) строят ту же модель дашборда типизированным кодом. `gcx dev` интегрирован с ними: `gcx dev scaffold --project my-dashboards` создаёт проект-заготовку, `gcx dev import dashboards` импортирует существующие дашборды как Go-код, `gcx dev serve ./resources` поднимает live-reload сервер для предпросмотра.

**Ожидаемый результат:** сгенерирован валидный `orders.json`, загруженный в Grafana.

**Типичные проблемы:**
- `import '.../main.libsonnet'` не найден — библиотека не установлена через `jb install`; проверьте каталог `vendor/`.
- Шаблон порождает гигантский JSON — выносите повторяющиеся панели в функции/локальные переменные Jsonnet.
- Медленная сборка — используйте `go-jsonnet` (`jsonnet` из Google), а не C-реализацию.

### Сценарий 7: Grafana Operator (Kubernetes CRD)

Нативное управление дашбордами и источниками через кастомные ресурсы. Проект развивается и поддерживается Grafana Labs совместно с сообществом (v5.x, без коммерческой поддержки — triage на best-effort).

```yaml
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDashboard
metadata:
  name: app-dashboard
  namespace: monitoring
spec:
  grafana:
    name: grafana
  json: |
    { ... dashboard JSON ... }
  folder: Applications
```

**Ожидаемый результат:** Operator создаёт/обновляет дашборд в инстансе Grafana, на который указывает `spec.grafana.name`.

**Валидация:**
```bash
kubectl -n monitoring get grafanadashboard
# → app-dashboard   Synchronized
```

**Типичные проблемы:**
- `GrafanaDashboard` не синхронизируется — проверьте, что `spec.grafana.name` совпадает с именем CRD `Grafana` в том же неймспейсе.
- Большие дашборды — храните JSON в отдельном ConfigMap и ссылайтесь через `spec.jsonFrom.configMapKeyRef`.

### Сценарий 8: Alerting as Code

Правила оповещений описываются как код (подробнее в [Алертинг: Provisioning](./alerting/provisioning.md)). В Terraform правила живут внутри группы (`grafana_rule_group`), которая привязывается к папке через `folder_uid`; условие собирается из этапов `data` (query → reduce → threshold).

```hcl
resource "grafana_rule_group" "infra" {
  name             = "Infra Alerts"
  folder_uid       = grafana_folder.team_a.uid
  interval_seconds = 60

  rule {
    name      = "High CPU"
    condition = "C"

    data {
      ref_id         = "A"
      datasource_uid = grafana_data_source.prometheus.uid
      relative_time_range {
        from = 300
        to   = 0
      }
      model = jsonencode({
        expr  = "100 - (avg by(instance) (rate(node_cpu_seconds_total{mode=\"idle\"}[5m])) * 100)"
        refId = "A"
      })
    }

    data {
      ref_id         = "B"
      datasource_uid = "__expr__"
      relative_time_range {
        from = 0
        to   = 0
      }
      model = jsonencode({
        type       = "reduce"
        expression = "A"
        reducer    = "last"
      })
    }

    data {
      ref_id         = "C"
      datasource_uid = "__expr__"
      relative_time_range {
        from = 0
        to   = 0
      }
      model = jsonencode({
        type       = "threshold"
        expression = "B"
        conditions = [{
          evaluator = { type = "gt", params = [80] }
        }]
      })
    }

    labels = {
      severity = "warning"
    }
  }
}
```

**Ожидаемый результат:** группа правил `Infra Alerts` применена в папке `Team A`; алерты вычисляются Unified Alerting.

**Типичные проблемы:**
- Алерт не срабатывает — проверьте `datasource_uid` и доступность источника; алерты не поддерживают dashboard-переменные.
- Ошибка `Missing required argument "folder_uid"` — группа привязывается к папке именно через `folder_uid` (UID), а не через `folder`/`id`.
- Пустой результат вычисления — условие ссылается на этап выражения (`ref_id`) с неверным идентификатором; проверьте цепочку `query → reduce → threshold`.

---

## Устранение неполадок

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Дашборд не появляется в UI | Нет метки `grafana_dashboard: "1"` на ConfigMap | Добавьте метку; проверьте логи sidecar |
| `ConfigMap too large` | Дашборд > 1 МБ | Включите GZIP в Helm values или разбейте на несколько ConfigMap |
| `401 Unauthorized` (gcx/Terraform) | Неверный токен Service Account | Проверьте токен и роль аккаунта; сверьте активный контекст `gcx` |
| Дашборд в `General`, а не в папке | Не включено группирование по папкам | Задайте `folderAnnotation: grafana_folder` + `provider.foldersFromFilesStructure: true` |
| Terraform: циклическая зависимость | Дашборд ссылается на зависимый ресурс | Уберите обратную ссылку; используйте `uid` |
| Terraform: `Missing required argument "folder_uid"` | У `grafana_rule_group` указан `folder` вместо `folder_uid` | Используйте `folder_uid = grafana_folder.<name>.uid` |
| Алерт не срабатывает | Неверный `datasource_uid` / dashboard-переменная | Проверьте UID; не используйте `$var` в алертах |
| Git Sync не работает | Ошибка токена/SSH-ключа/GitHub App, нет доступа к репозиторию | Проверьте креденшелы и сетевой доступ из сети Grafana |
| Git Sync: репозиторий не создаётся | Превышен `max_repositories` или URL резолвится в приватный/loopback-адрес | Поднимите `[provisioning] max_repositories` или внесите хост в `allowed_git_urls` |
| Дашборды/папки пропали после апгрейда | Migration-баг unified storage в 13.0.0 (self-managed, Git Sync был включён на 12.x) | Восстановите БД из бэкапа и обновитесь до 13.0.1+ |
| Дрейф конфигурации | Ручные правки в UI | Включите `editable: false` / `Read only` и/или RBAC-запрет |

---

## Рекомендации по эксплуатации

- **Стабильные UID**: Всегда фиксируйте `uid` в JSON дашборда. Если Grafana создаст случайный UID при импорте, ссылки между дашбордами сломаются.
- **Запрет ручного редактирования**: В настройках провайдера (Provisioning), Git Sync (`Read only`) или через RBAC установите запрет правок в UI. Это предотвратит "дрейф конфигурации" (Configuration Drift), когда правки в UI затираются кодом из Git.
- **Версионирование в именах**: Добавляйте версию или хеш коммита в метаданные дашборда для быстрого сопоставления интерфейса с состоянием в Git.
- **Проверка алертов**: правила Prometheus тестируйте в CI через `promtool test rules`; Grafana-managed ресурсы — через `gcx resources validate` и `gcx dev lint run`.
- **Service Account вместо личного токена**: Для CI/CD используйте выделенный Service Account с минимальной ролью; ротируйте токен.
- **Один источник правды на ресурс**: не управляйте одним и тем же объектом одновременно через файловый провиженинг, Terraform и gcx — выберите один инструмент на ресурс.

### Типичные ошибки

- **Хранение секретов в Git**: пароли от источников данных должны передаваться через переменные окружения или внешние секреты (Vault, SOPS, Kubernetes Secret), а не жестко прописываться в коде MaC.
- **Огромные ConfigMap**: лимит размера ConfigMap в Kubernetes — 1 МБ. Очень сложные дашборды могут не поместиться в один ресурс. В таких случаях используйте разделение на несколько файлов, `sidecar.dashboards.GZIP: true` (Helm) или деплой через API (gcx/Terraform).
- **Отсутствие папок**: без указания аннотации/провайдера папки все дашборды попадут в `General`, что затруднит навигацию.
- **Отсутствие `depends_on` в Terraform**: ресурсы применяются в неверном порядке, дашборд ссылается на ещё не созданный источник.
- **Ручные правки в Prod**: правки в UI обходят MaC и создают дрейф; блокируйте через `editable: false` / `Read only` / RBAC.
- **Устаревший инструментарий**: Grizzly и `grafanactl` больше не развиваются — в новых пайплайнах используйте `gcx`.

### Рекомендации по внедрению

1.  **Начинайте с Provisioning** для статичных ресурсов (источники данных, общие дашборды).
2.  **Используйте GitOps + Sidecar** для дашбордов, которые часто обновляются командами.
3.  **Применяйте Terraform/gcx** для управления инфраструктурой Grafana (пользователи, организации, папки).
4.  **Фиксируйте UID** дашбордов для обеспечения стабильности ссылок.
5.  **Запрещайте ручные изменения** через UI в production-средах (`editable: false` / `Read only`).
6.  **Внедряйте нативный Git Sync (13.x)** где уместна двусторонняя синхронизация без операторов.

## Ограничения и особые случаи

- **Unified Alerting и переменные**: правила алертинга вычисляются сервером вне контекста дашборда, поэтому dashboard-переменные (`$Host`, `$Region`) в запросах алертов недопустимы.
- **Лимит ConfigMap 1 МБ**: сложные дашборды не помещаются в один ресурс; используйте GZIP, разбиение или API-доставку.
- **Hot Reload не для всего**: некоторые ресурсы (плагины, доступ-контроль) требуют перезагрузки Grafana после изменения провиженинг-файла.
- **Git Sync**: двусторонняя синхронизация удобна, но требует продуманного воркфлоу (PR) при одновременных правках в UI и в Git во избежание конфликтов. Число подключений на self-managed по умолчанию — 10 (`max_repositories`), ресурсов на репозиторий — без лимита; для больших объёмов шардируйте один репозиторий по нескольким путям-подключениям. Асинхронный `gcx resources push/pull` покрывает все типы ресурсов, тогда как Git Sync синхронизирует только дашборды и папки.
- **Grafonnet — experimental**: библиотека официально помечена как нестабильная и не рекомендована для production; для стабильных проектов используйте grafana-foundation-sdk или прямой JSON.
- **Версионность Grafana**: синтаксис провиженинга, CRD и CLI меняется между мажорными версиями (11/12/13); фиксируйте версию в CI-образе.

---

## Дополнительная информация

> **См. также:**
> - **[Провиженинг Grafana](./grafana_provisioning.md)** — механизмы и конфигурация провайдеров.
> - **[Дашборды: Best Practices](./grafana-dashboards.md)** — рекомендации по проектированию визуализаций.
> - **[Интеграция с Prometheus Operator](../Prometheus/kubernetes/operator/grafana_integration.md)** — детальная работа sidecar-контейнера.
> - **[GitOps: обзор](../GitOps/GitOps_overview.md)** — общие принципы GitOps-модели.
