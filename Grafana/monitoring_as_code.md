# Monitoring as Code (MaC): Grafana и GitOps

**Monitoring as Code (MaC)** — методология управления инфраструктурой наблюдаемости, при которой конфигурации инструментов (дашборды, источники данных, правила алертинга) описываются декларативно в виде кода, проходят через процесс Code Review и автоматически развертываются через CI/CD или GitOps-контроллеры.

## Определения

- **MaC (Monitoring as Code)**: Применение принципов Software Engineering (версионирование, тестирование, автоматизация) к процессам мониторинга.
- **GitOps в мониторинге**: Использование Git как единственного источника правды для всех объектов наблюдаемости. Изменения в Git автоматически синхронизируются с инстансами Grafana.
- **Dashboard-as-Code (DaC)**: Подмножество MaC, сфокусированное на генерации и управлении JSON-моделями дашбордов через шаблонизаторы.
- **Sidecar (k8s-sidecar)**: Вспомогательный контейнер, работающий рядом с Grafana, который обнаруживает ConfigMap с дашбордами в Kubernetes и загружает их "на лету".
- **Провиженинг (Provisioning)**: Подход Infrastructure as Code (IaC) для декларативного описания ресурсов Grafana (источники данных, дашборды, алерты, плагины) через YAML/JSON-файлы в директории `/etc/grafana/provisioning`.
- **Конфигурационный дрейф (Configuration Drift)**: Расхождение между задекларированным состоянием в Git и фактическим состоянием Grafana, возникающее из-за ручных правок в UI. MaC устраняет дрейф через регулярную сверку (reconcile) или запрет ручного редактирования (`editable: false`).
- **Grizzly (`grzl`)**: CLI-утилита от Grafana Labs для управления ресурсами Grafana через YAML-обёртки над JSON-моделями и синхронизации через HTTP API.
- **Jsonnet / Grafonnet**: Функциональный язык конфигурации и библиотека `grafonnet-lib` для генерации типовых JSON-дашбордов из параметризованных шаблонов (Dashboard-as-Code).
- **Git Sync (Grafana 13.x)**: Нативная двусторонняя синхронизация Grafana с Git-репозиторием без внешних sidecar-контейнеров — редактирование в UI коммитится в Git, а изменения из Git подтягиваются в инстанс.
- **Service Account (Сервисный аккаунт)**: Токен-идентификация для CI/CD и API-клиентов (вместо пользовательского логина), с назначенной ролью (Viewer/Editor/Admin).
- **Declarative config (Декларативная конфигурация)**: Описание желаемого состояния ("что должно быть"), а не последовательности шагов ("как сделать").

---

## Базовые концепции

### Жизненный цикл MaC

Процесс управления мониторингом как кодом состоит из трех уровней:

1.  **Генерация (Generation)**: Использование языков высокого уровня (Jsonnet, Python) вместо ручного редактирования гигантских JSON-файлов. Результат — стабильная JSON-модель дашборда.
2.  **Валидация (Validation)**: Проверка синтаксиса, линтинг PromQL-запросов и соблюдение стандартов оформления до деплоя (линтеры, `promtool`, CI-гейты).
3.  **Доставка (Delivery)**: Синхронизация кода с Grafana через API, провиженинг-файлы или нативные механизмы Kubernetes.

```text
Git ──▶ CI (lint/test) ──▶ Push API / Provisioning / Sidecar / Git Sync ──▶ Grafana
  ▲                                                                          │
  └──────────────────── Reconcile / Drift detection ◀────────────────────────┘
```

### Сравнение инструментов

| Инструмент | Подход | Когда использовать |
| :--- | :--- | :--- |
| **Grizzly** | CLI / YAML | Быстрая синхронизация дашбордов и алертов через API. Идеально для небольших команд. |
| **Terraform / OpenTofu** | IaC / HCL | Управление всей инфраструктурой Grafana (пользователи, папки, источники данных, Cloud-инстансы). |
| **Jsonnet (Grafonnet)**| Templating | Массовое создание типовых дашбордов для сотен однотипных микросервисов. |
| **Crossplane** | K8s Control Plane | Управление ресурсами Grafana Cloud напрямую через манифесты Kubernetes. |
| **Grafana Operator** | K8s Operator | Нативное управление инстансами и дашбордами внутри кластера Kubernetes (CRD). |
| **Git Sync (13.x)** | Нативный Git | Двусторонняя синхронизация с Git без sidecar; редактирование в UI → авто-коммит. |
| **k8s-sidecar + ArgoCD** | GitOps | Синхронизация ConfigMap с дашбордами в Kubernetes-кластерах. |

### Подходы к автоматизации мониторинга

**1. Provisioning (File-based):**
- Описание источников данных, дашбордов и алертов в YAML/JSON файлах.
- Grafana сканирует директорию `/etc/grafana/provisioning` при запуске (и подхватывает изменения "на лету" — Hot Reload — для большинства ресурсов).
- Идеально для статичных конфигураций, не требующих частых изменений.

**2. GitOps через Kubernetes Sidecar:**
- Дашборды и алерты хранятся в Git в виде ConfigMap.
- ArgoCD/Flux синхронизируют ConfigMap в кластере.
- Sidecar-контейнер (`k8s-sidecar`) обнаруживает ConfigMap и загружает их в Grafana.

**3. Infrastructure as Code (Terraform / Grizzly / Crossplane):**
- Terraform управляет всей инфраструктурой Grafana (пользователи, папки, источники данных, дашборды, алерты).
- Grizzly позволяет описывать ресурсы Grafana в YAML и синхронизировать через API без написания HCL.
- Crossplane управляет Grafana Cloud через Kubernetes API (Control Plane).

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
| **Terraform/Grizzly** | Средняя | Управление несколькими инстансами Grafana |
| **API-based** | Высокая | Динамическая генерация ресурсов, интеграция с CI/CD |
| **Native Git Sync** | Низкая | Grafana 13.x, двусторонняя синхронизация без операторов |

### Порядок применения и разрешение зависимостей

- **Зависимости имеют значение:** источники данных должны быть провиженины до дашбордов, ссылающихся на них, а папки (`folder`) — до ресурсов, помещаемых в папку.
- **Провиженинг** применяет ресурсы в порядке: `datasources` → `dashboards` → `alerting`/`contactpoints`/`policies`.
- **Terraform** требует явных `depends_on` (например, `grafana_dashboard` зависит от `grafana_folder` и `grafana_data_source`) для корректного графа зависимостей.
- **UID-стабильность:** фиксированный `uid` дашборда гарантирует, что ссылки (`/d/<uid>/...`), импорт и перекрёстные переходы не сломаются при повторном применении кода.

---

## Практические сценарии

### Предварительные требования

- **Версия Grafana**: 11.x (базовый MaC), 12.x (LTS), 13.1.x (актуальная; для нативного Git Sync). См. [Обзор Grafana](./grafana_overview.md).
- **Git-репозиторий**: с дашбордами/алертами в формате JSON (или генерируемыми из Jsonnet/YAML).
- **Доступы**: Service Account с ролью Editor/Admin и токеном, либо SSH-ключ/GitHub App (для Git Sync), либо `kubectl` (для Kubernetes-сценариев).
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
        grafana_dashboard_folder: "Applications" # Автоматическое создание папки
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
  http://grafana.monitoring.svc:3000/api/search?folderIds=0 | jq '.[].uid'
# → должен содержать uid вашего дашборда

# Логи sidecar-контейнера пода Grafana
kubectl -n monitoring logs deploy/kube-prometheus-stack-grafana -c grafana-sc-dashboard
# → "Dashboard ... has been added/changed"
```

**Типичные проблемы:**
- Дашборд не появляется — отсутствует метка `grafana_dashboard: "1"` на ConfigMap.
- ConfigMap > 1 МБ — Kubernetes отклоняет; включите `sidecar.dashboards.GZIP: true` в Helm values или разбейте на несколько ConfigMap.
- Дашборд попадает в `General` — нет аннотации `grafana_dashboard_folder`.

### Сценарий 2: Использование Grizzly для CI/CD пайплайнов

**Grizzly** (`grzl`) — утилита от Grafana Labs, позволяющая управлять ресурсами через YAML-обертки над JSON-моделями.

**Пайплайн валидации (GitLab CI):**
```yaml
validate_dashboards:
  stage: test
  image: grafana/grizzly:latest
  script:
    - grzl lint dashboards/ # Проверка синтаксиса и структуры
    - dashboard-linter lint my-dashboard.json # Глубокая проверка PromQL
```

**Пайплайн деплоя:**
```yaml
deploy_prod:
  stage: deploy
  script:
    - grzl push dashboards/ --endpoint $GRAFANA_URL --token $GRAFANA_TOKEN
```

**Ожидаемый результат:** `grzl lint` завершается с кодом 0; `grzl push` создаёт/обновляет ресурсы в Grafana.

**Валидация:**
```bash
grzl list --endpoint $GRAFANA_URL --token $GRAFANA_TOKEN
# → список управляемых ресурсов (dashboards, datasources, alert rules)
```

**Типичные проблемы:**
- `401 Unauthorized` — неверный/просроченный токен Service Account; проверьте `GRAFANA_TOKEN` и роль аккаунта.
- `lint` ругается на PromQL — исправьте запрос или добавьте исключение в конфиг линтера.

### Сценарий 3: Terraform для Managed Grafana (Grafana Cloud)

Для управления пользователями, плагинами и источниками данных в облачной или корпоративной Grafana рекомендуется использовать официальный провайдер.

```hcl
resource "grafana_folder" "team_a" {
  title = "Team A"
}

resource "grafana_data_source" "prometheus" {
  type       = "prometheus"
  name       = "Prometheus"
  url        = "https://prom.example.com"
  is_default = true
}

resource "grafana_service_account" "ci_cd" {
  name = "CI/CD Deployer"
  role = "Admin"
}

resource "grafana_dashboard" "metrics" {
  config_json = file("dashboards/service_metrics.json")
  folder      = grafana_folder.team_a.id
  overwrite   = true
}
```

**Ожидаемый результат:** `terraform apply` создаёт папку, источник данных, сервисный аккаунт и загружает дашборд в папку `Team A`.

**Валидация:**
```bash
terraform plan   # → показывает ресурсы к созданию/изменению
terraform apply  # → Apply complete! Resources: 4 added
```

**Типичные проблемы:**
- `overwrite = false` + существующий дашборд — ошибка; выставьте `overwrite = true` для управления через код.
- Дашборд не видит источник — убедитесь, что в JSON дашборда `datasource` ссылается на `uid` созданного `grafana_data_source`.
- Циклическая зависимость — не ссылайтесь дашбордом на ресурс, который зависит от самого дашборда.

### Сценарий 4: Нативная синхронизация Git Sync (Grafana 13.x)

С выходом Grafana 13.x нативная двусторонняя синхронизация вытесняет внешние sidecar-контейнеры для сценария "Git как источник правды".

**Предварительные требования:**
- Grafana 13.x с включённой функцией Git Sync (GA).
- Git-репозиторий с дашбордами в формате JSON.
- SSH-ключ или GitHub App с правами на запись.

**Шаги:**
1.  **Подключение репозитория:** в UI `Admin → Git Sync` укажите URL репозитория, ветку и учётные данные (SSH-ключ/GitHub App).
2.  **Режим:** выберите `Bidirectional` (правки в UI → коммит; изменения в Git → подтягиваются).
3.  **Синхронизация:** правки дашбордов в UI автоматически создают коммит (опционально через PR); другие инстансы Grafana подтягивают изменения из этого репозитория.

**Валидация:**
```bash
# Проверка статуса Git Sync через API
curl -s -H "Authorization: Bearer <SA_TOKEN>" \
  http://grafana:3000/api/git/settings | jq .
# → ожидаемый результат: enabled=true, mode="bidirectional"

git -C /path/to/repo log --oneline -1
# → должен содержать описание изменения дашборда
```

**Очистка:** отключите Git Sync в UI перед удалением репозитория, чтобы предотвратить автоматические коммиты от инстанса.

**Типичные проблемы:**
- `Git Sync не работает` — ошибки аутентификации/прав доступа; проверьте SSH-ключ/токен и доступность репозитория из сети Grafana.
- Конфликт при одновременных правках в UI и в Git — разрешается через PR-воркфлоу или приоритет ветки.

### Сценарий 5: File-based Provisioning (YAML)

Декларативное описание источника данных и провайдера дашбордов в файлах (см. детали в [Провиженинг](./grafana_provisioning.md)).

```yaml
# /etc/grafana/provisioning/datasources/prom.yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
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
  http://localhost:3000/api/datasources/name/Prometheus | jq '.name'
# → "Prometheus"
```

**Типичные проблемы:**
- Дашборды не загружаются — неверный `options.path` или дашборд не валиден по JSON.
- Ручные правки затираются — ожидаемое поведение при `editable: false`; правьте код в Git.

### Сценарий 6: Dashboard-as-Code на Jsonnet (Grafonnet)

Генерация типовых дашбордов для множества сервисов из одного шаблона.

```jsonnet
// dashboard.libsonnet
local grafana = import 'grafonnet/grafana.libsonnet';
local dashboard = grafana.dashboard;
local prometheus = grafana.datasource.prometheus;
local panel = grafana.panel.graphPanel;

dashboard.new('Service: %s' % std.extVar('service'))
  .addPanel(
    panel.new('CPU', datasource=prometheus.default.uid)
      .addTarget({ expr: 'rate(container_cpu_usage_seconds_total{service="%s"}[5m])' % std.extVar('service') })
  )
```

**Сборка и применение:**
```bash
jsonnet -V service=orders dashboard.libsonnet > orders.json
grzl push orders.json --endpoint $GRAFANA_URL --token $GRAFANA_TOKEN
```

**Ожидаемый результат:** сгенерирован валидный `orders.json`, загруженный в Grafana.

**Типичные проблемы:**
- `import 'grafonnet/...'` не найден — добавьте `grafonnet-lib` в `Jsonnet` через `jb install grafana/grafonnet-lib`.
- Шаблон порождает гигантский JSON — выносите повторяющиеся панели в функции/миксы.

### Сценарий 7: Grafana Operator (Kubernetes CRD)

Нативное управление дашбордами и источниками через кастомные ресурсы.

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

Правила оповещений описываются как код (подробнее в [Алертинг: Provisioning](./alerting/provisioning.md)). Пример через Terraform:

```hcl
resource "grafana_rule_group" "infra" {
  name = "Infra Alerts"
  folder = grafana_folder.team_a.id
  rule {
    name = "High CPU"
    condition = "C"
    data {
      ref_id = "C"
      query_type = "prometheus"
      datasource_uid = grafana_data_source.prometheus.uid
      model = jsonencode({ expr = "rate(node_cpu[5m]) > 0.9", refId = "C" })
    }
  }
}
```

**Ожидаемый результат:** группа правил `Infra Alerts` применена в папке `Team A`; алерты вычисляются Unified Alerting.

**Типичные проблемы:**
- Алерт не срабатывает — проверьте `datasource_uid` и доступность источника; алерты не поддерживают dashboard-переменные.

---

## Дополнительная информация

### Рекомендации по эксплуатации

- **Стабильные UID**: Всегда фиксируйте `uid` в JSON дашборда. Если Grafana создаст случайный UID при импорте, ссылки между дашбордами сломаются.
- **Запрет ручного редактирования**: В настройках провайдера (Provisioning) или через RBAC установите `editable: false`. Это предотвратит ситуацию "дрейфа конфигурации" (Configuration Drift), когда правки в UI затираются кодом из Git.
- **Версионирование в именах**: Добавляйте версию или хеш коммита в метаданные дашборда для быстрого сопоставления интерфейса с состоянием в Git.
- **Проверка алертов**: При использовании MaC алерты должны тестироваться в CI через `promtool` (для Prometheus) или встроенные средства валидации Grizzly.
- **Service Account вместо личного токена**: Для CI/CD используйте выделенный Service Account с минимальной ролью; ротируйте токен.

### Типичные ошибки

- **Хранение секретов в Git**: Пароли от источников данных должны передаваться через переменные окружения или внешние секреты (Vault, AWS Secrets Manager, SOPS), а не жестко прописываться в коде MaC.
- **Огромные ConfigMap**: Лимит размера ConfigMap в Kubernetes — 1 МБ. Очень сложные дашборды могут не поместиться в один ресурс. В таких случаях используйте разделение на несколько файлов, `sidecar.dashboards.GZIP: true` (Helm) или деплой через API (Grizzly/Terraform).
- **Отсутствие папок**: Без указания аннотации/провайдера папки все дашборды попадут в `General`, что затруднит навигацию.
- **Отсутствие `depends_on` в Terraform**: Ресурсы применяются в неверном порядке, дашборд ссылается на ещё не созданный источник.
- **Ручные правки в Prod**: правки в UI обходят MaC и создают дрейф; блокируйте через `editable: false`/RBAC.

### Устранение неполадок

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Дашборд не появляется в UI | Нет метки `grafana_dashboard: "1"` на ConfigMap | Добавьте метку; проверьте логи sidecar |
| `ConfigMap too large` | Дашборд > 1 МБ | Включите GZIP в Helm values или разбейте на несколько ConfigMap |
| `401 Unauthorized` (Grizzly/Terraform) | Неверный токен Service Account | Проверьте `GRAFANA_TOKEN`, роль аккаунта |
| Дашборд в `General`, а не в папке | Нет аннотации/провайдера папки | Добавьте `grafana_dashboard_folder` / `folder` в провайдере |
| Terraform: циклическая зависимость | Дашборд ссылается на зависимый ресурс | Уберите обратную ссылку; используйте `uid` |
| Алерт не срабатывает | Неверный `datasource_uid` / dashboard-переменная | Проверьте UID; не используйте `$var` в алертах |
| Git Sync не работает | Ошибка SSH/токена, нет доступа к репозиторию | Проверьте ключ/GitHub App и сетевой доступ |
| Дрейф конфигурации | Ручные правки в UI | Включите `editable: false` и/или RBAC-запрет |

### Ограничения и особые случаи

- **Unified Alerting и переменные**: правила алертинга вычисляются сервером вне контекста дашборда, поэтому dashboard-переменные (`$Host`, `$Region`) в запросах алертов недопустимы.
- **Лимит ConfigMap 1 МБ**: сложные дашборды не помещаются в один ресурс; используйте GZIP, разбиение или API-доставку.
- **Hot Reload не для всего**: некоторые ресурсы (плагины, доступ-контроль) требуют перезагрузки Grafana после изменения провиженинг-файла.
- **Git Sync (13.x)**: двусторонняя синхронизация удобна, но требует продуманного воркфлоу (PR) при одновременных правках в UI и в Git во избежание конфликтов.
- **Сторонние секреты**: пароли источников нельзя коммитить; используйте `GF_<SECTION>_<KEY>` env, Vault, SOPS или Kubernetes Secret.
- **Версионность Grafana**: синтаксис провиженинг/CRD меняется между мажорными версиями (11/12/13); фиксируйте версию в CI-образе.

### Рекомендации по внедрению

1.  **Начинайте с Provisioning** для статичных ресурсов (источники данных, общие дашборды).
2.  **Используйте GitOps + Sidecar** для дашбордов, которые часто обновляются командами.
3.  **Применяйте Terraform/Grizzly** для управления инфраструктурой Grafana (пользователи, организации, папки).
4.  **Фиксируйте UID** дашбордов для обеспечения стабильности ссылок.
5.  **Запрещайте ручные изменения** через UI в production-средах (`editable: false`).
6.  **Внедряйте нативный Git Sync (13.x)** где уместна двусторонняя синхронизация без операторов.

> **См. также:**
> - **[Провиженинг Grafana](./grafana_provisioning.md)** — механизмы и конфигурация провайдеров.
> - **[Дашборды: Best Practices](./grafana-dashboards.md)** — рекомендации по проектированию визуализаций.
> - **[Интеграция с Prometheus Operator](../Prometheus/kubernetes/operator/grafana_integration.md)** — детальная работа sidecar-контейнера.
