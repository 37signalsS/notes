# Интеграция Argo CD с Helm

**Актуально для:** Argo CD v3.5+ (покрывает v3.4.x, v3.5.x, v3.6.x; Helm v3.14–v3.16+ / Helm v4.x; Kubernetes 1.28–1.32+; bare-metal / on-premise)

## Определения

- **Helm** — пакетный менеджер для Kubernetes, использующий формат чартов для декларативного описания и шаблонизации ресурсов кластера.
- **Helm-чарт (Chart)** — структурированный архив или каталог, содержащий манифесты Go-шаблонов (`templates/`), метаданные (`Chart.yaml`), переменные по умолчанию (`values.yaml`), схему валидации (`values.schema.json`) и блокировки зависимостей (`Chart.lock`).
- **Файлы значений (Values Files)** — YAML-документы конфигурации, передаваемые в шаблонизатор Helm для переопределения переменных чарта под конкретные окружения (development, staging, production).
- **OCI-артефакты (OCI Artifacts)** — открытый стандарт упаковки и распространения Helm-чартов через реестры контейнеров OCI (Harbor, Gitea, Quay, Docker Registry) с использованием протокола `oci://`.
- **Multiple Sources** — механизм Argo CD (`spec.sources`), позволяющий объединять в рамках одного объекта `Application` базовый чарт из внешнего реестра (HTTP/OCI) и файлы конфигурации (`values.yaml`) из приватного Git-репозитория с адресацией через `$ref`.
- **sourceHydrator (Hydration Engine)** — внутренний компонент `argocd-repo-server`, отвечающий за подготовку источников, параллельное клонирование/скачивание, компиляцию зависимостей (`helm dependency build`) и генерацию плоского YAML-потока.
- **Server-Side Apply (SSA)** — механизм применения конфигураций Kubernetes через API-сервер (`fieldManager=argocd`), устраняющий ограничение аннотации `kubectl.kubernetes.io/last-applied-configuration` (лимит 262 144 байт / 256 KB) и предотвращающий коллизии полей.
- **Helm Hooks** — аннотации жизненного цикла чарта (`helm.sh/hook`), управляющие запуском вспомогательных ресурсов (миграции БД, проверка готовности) до или после развертывания основного релиза.
- **Sync Waves** — механизм упорядочивания синхронизации Argo CD (`argocd.argoproj.io/sync-wave`), делящий развертывание на фазы от отрицательных к положительным индексам с ожиданием перехода ресурсов в состояние `Healthy`.
- **Resource Tracking Collision** — конфликт владения ресурсом, возникающий при совпадении метки отслеживания Argo CD (`app.kubernetes.io/instance`) с именем Helm-релиза (`{{ .Release.Name }}`), приводящий к сбою синхронизации из-за неизменяемости селекторов `spec.selector.matchLabels`.
- **AppProject** — логическая граница безопасности Argo CD, изолирующая приложения по разрешенным репозиториям источников (`sourceRepositories`), целевым кластерам и типам манифестов.
- **Config Management Plugins (CMP v2)** — механизм расширения рендеринга через sidecar-контейнеры в поде `argocd-repo-server`, применяемый для запуска утилит шифрования (Helm-secrets, SOPS, AVP) поверх стандартного Helm.

## Архитектура и базовые концепции

### Внутренний конвейер рендеринга в `argocd-repo-server`

Argo CD не выполняет команды `helm install` или `helm upgrade` в целевом кластере. Вместо этого компонент `argocd-repo-server` компилирует манифесты локально в оперативной памяти и изолированной файловой системе, после чего передает сгенерированный чистый поток YAML в `argocd-application-controller` для применения через стандартный Kubernetes API.

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        argocd-repo-server (Контейнер генерации)                        │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│   Входящие источники (spec.sources / spec.source):                                     │
│   ├── Git Репозиторий (манифесты, values, local chart) ──▶ Bare Cache Repo             │
│   ├── OCI Реестр (Harbor: oci://harbor.internal/...)   ──▶ Ephemeral Cache (/tmp)     │
│   └── HTTP Helm Repo (ChartMuseum / Nexus)             ──▶ Helm Cache (/tmp/helm)      │
│                                                                                        │
│                                           │                                            │
│                                           ▼                                            │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │                      sourceHydrator Workspace (/tmp/_app/...)                  │   │
│   ├────────────────────────────────────────────────────────────────────────────────┤   │
│   │ 1. Git Fetch / Shallow Clone (--depth=1)                                       │   │
│   │ 2. Helm / OCI Pull (извлечение .tgz архива чарта)                              │   │
│   │ 3. Разрешение subcharts: `helm dependency build` (при наличии Chart.lock)      │   │
│   │ 4. Монтирование вторичных источников: $values/ -> /tmp/values/values/          │   │
│   └────────────────────────────────────────────────────────────────────────────────┘   │
│                                           │                                            │
│                                           ▼                                            │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │                         Helm Engine (helm template)                            │   │
│   ├────────────────────────────────────────────────────────────────────────────────┤   │
│   │ Выполнение:                                                                    │   │
│   │ helm template <releaseName> <chartDir> \                                       │   │
│   │   --namespace <targetNamespace> \                                              │   │
│   │   --values /tmp/values/values-base.yaml \                                      │   │
│   │   --values /tmp/values/values-prod.yaml \                                      │   │
│   │   --set key=value ...                                                          │   │
│   │                                                                                │   │
│   │ Валидация: проверка values.schema.json (при наличии)                           │   │
│   │ Фильтрация: обработка флага --skip-crds (настраивается в spec.source.helm)     │   │
│   └────────────────────────────────────────────────────────────────────────────────┘   │
│                                           │                                            │
│                                           ▼                                            │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │                        In-Memory / Redis Manifest Cache                        │   │
│   │    Ключ: mfst|<repoURL>|<revision>|<app-signature> (TTL: по умолчанию 5 мин)   │   │
│   └────────────────────────────────────────────────────────────────────────────────┘   │
│                                           │                                            │
└───────────────────────────────────────────┼────────────────────────────────────────────┘
                                            │ gRPC (:8081)
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              argocd-application-controller                             │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. Вычисление Diff (Live State кластера vs Target State из Manifest Cache)             │
│ 2. Преобразование Helm Hooks в Argo CD Resource Hooks и Sync Waves                     │
│ 3. Внедрение метаданных отслеживания (Tracking ID: annotation или label)               │
│ 4. Применение через Kube API: Client-Side Apply или Server-Side Apply (fieldManager)   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### Отличия модели Argo CD от классического Helm CLI

Понимание архитектурных различий между Argo CD и Helm CLI критично для предотвращения ошибок сопровождения в производственной среде:

| Характеристика | Helm CLI (`helm install / upgrade`) | Argo CD GitOps (`argocd-repo-server`) |
| :--- | :--- | :--- |
| **Хранение состояния (Release State)** | Создает Secret вида `sh.helm.release.v1.<name>.v<num>` в целевом namespace. | **Не создает** Secret релиза. Состояние фиксируется декларативно в объекте `Application` и кеше Git. |
| **Управление релизами** | `helm list`, `helm history`, `helm status` отображают релиз и его ревизии. | Helm CLI видит namespace пустым. Управление выполняется через `argocd app get`, `argocd app history`. |
| **Механизм отката** | `helm rollback <name> <rev>` восстанавливает состояние из Secret релиза. | `argocd app rollback` переключает целевой Git-коммит или ревизию OCI в манифесте `Application`. |
| **Дрейф конфигурации (Drift Detection)** | Отсутствует. Ручные изменения через `kubectl edit` игнорируются до следующего `upgrade`. | Непрерывный мониторинг дрейфа. При `selfHeal: true` ручные правки немедленно перезаписываются. |
| **Жизненный цикл CRD** | Каталог `crds/` устанавливается только при первой установке, обновления CRD игнорируются. | Управляется флагом `skipCrds` и Sync Waves. Позволяет непрерывно и безопасно обновлять CRD. |
| **Объем манифестов** | Ограничен аннотацией `last-applied-configuration` (256 KB) при использовании 3-way merge. | Поддерживает Server-Side Apply (`ServerSideApply=true`), обходя любые ограничения размера аннотаций. |

### Режимы подключения Helm-источников

Argo CD поддерживает три архитектурных формата поставки чартов:

1. **Традиционный HTTP/HTTPS Helm-репозиторий:**
   - Хранилища: ChartMuseum, Nexus Repository, JFrog Artifactory, внутренний HTTP-сервер.
   - Метаданные: `index.yaml`, содержащий ссылки на архивы `.tgz`.
   - Настройка в Argo CD: тип репозитория `helm`.
2. **OCI-совместимый реестр контейнеров:**
   - Хранилища: Harbor (on-premise), Quay, Gitea Container Registry, локальный Docker Distribution Registry.
   - Спецификация: OCI Image Manifest с `mediaType: application/vnd.cncf.helm.chart.content.v1.tar+gzip`.
   - Адресация: `repoURL` указывает на путь реестра без протокола или с `oci://`, `chart` задает имя артефакта, `targetRevision` строго фиксирует SemVer-тег (`1.2.3`) или SHA256-дайджест.
3. **Локальный чарт из Git-репозитория:**
   - Размещение: каталог с чартом хранится в общем репозитории инфраструктуры (монорепозиторий).
   - `repoURL` указывает на Git-репозиторий (`git@gitlab.internal:...` или `https://...`), а `path` — на относительный путь к каталогу с `Chart.yaml`.

### Иерархия разрешения параметров и значений (Precedence Hierarchy)

При сборке чарта `argocd-repo-server` объединяет значения из нескольких источников в строгом порядке приоритета. Каждое последующее значение переопределяет предыдущее:

```text
1. Базовый values.yaml внутри чарта (Chart.yaml defaults)
   │
   ▼
2. Файлы valuesFiles (в порядке их перечисления в Application)
   ├── $values/environments/base/values.yaml
   └── $values/environments/production/values.yaml (переопределяет base)
   │
   ▼
3. Блок инлайн-значений helm.values (многострочный YAML-текст)
   │
   ▼
4. Блок структурированных инлайн-значений helm.valuesObject (YAML/JSON объект)
   │
   ▼
5. Параметры helm.parameters (--set name=value)
   │
   ▼
6. Файловые параметры helm.fileParameters (--set-file name=path) [Высший приоритет]
```

### Преобразование Helm Hooks в нативные хуки и волны Argo CD

Стандартные хуки жизненного цикла Helm транслируются компонентом `argocd-application-controller` в фазы синхронизации GitOps:

| Helm Hook (`helm.sh/hook`) | Преобразование в Argo CD Hook | Поведение в Argo CD |
| :--- | :--- | :--- |
| `pre-install`, `pre-upgrade` | `argocd.argoproj.io/hook: PreSync` | Выполняется перед применением основных манифестов релиза. |
| `post-install`, `post-upgrade` | `argocd.argoproj.io/hook: PostSync` | Выполняется после перехода всех основных манифестов в состояние `Synced` и `Healthy`. |
| `pre-delete` | `argocd.argoproj.io/hook: PreDelete` | Выполняется перед удалением приложения (при каскадном удалении). |
| `post-delete` | `argocd.argoproj.io/hook: PostDelete` | Выполняется после полного удаления ресурсов приложения. |
| `test` | **Игнорируется** | Не выполняется при обычной синхронизации; не блокирует деплой. |
| `helm.sh/hook-weight: "<n>"` | `argocd.argoproj.io/sync-wave: "<n>"` | Числовой вес транслируется в соответствующую волну синхронизации. |
| `helm.sh/hook-delete-policy: hook-succeeded` | `argocd.argoproj.io/hook-delete-policy: HookSucceeded` | Хук-ресурс удаляется после успешного выполнения задачи. |
| `helm.sh/hook-delete-policy: before-hook-creation` | `argocd.argoproj.io/hook-delete-policy: BeforeHookCreation` | Предыдущий экземпляр хука удаляется перед созданием нового. |

> [!WARNING]
> Если чарт содержит одновременно аннотации `helm.sh/hook` и `argocd.argoproj.io/hook`, аннотации Argo CD имеют абсолютный приоритет. Для обеспечения детерминированности в GitOps рекомендуется переводить хуки на нативные аннотации Argo CD.

### Конфликт метки отслеживания ресурсов (`app.kubernetes.io/instance`)

В стандартных чартах Helm (включая популярные библиотеки Bitnami и Helm Classic) общепринятый шаблон селекторов ресурсов генерирует метку:

```yaml
metadata:
  labels:
    app.kubernetes.io/name: {{ include "common.names.name" . }}
    app.kubernetes.io/instance: {{ .Release.Name }}
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "common.names.name" . }}
      app.kubernetes.io/instance: {{ .Release.Name }}
```

**Механика коллизии:**
1. По умолчанию в устаревших версиях Argo CD метод отслеживания ресурсов использовал метку `app.kubernetes.io/instance: <Application-Name>`.
2. Если имя объекта `Application` (`corp-redis-app`) не совпадает со значением `spec.source.helm.releaseName` (`redis-cluster`), Argo CD принудительно перезаписывает метку `app.kubernetes.io/instance` на `corp-redis-app`.
3. Так как поле `spec.selector.matchLabels` у объектов `Deployment`, `StatefulSet` и `DaemonSet` в Kubernetes является **неизменяемым (immutable)** после создания, API-сервер отвергает обновление с фатальной ошибкой:
   ```text
   The Deployment "redis-cluster" is invalid: spec.template.metadata.labels: Invalid value: field is immutable
   ```
4. Приложение блокируется в состоянии `SyncFailed` и бесконечного цикла расхождения `OutOfSync`.

**Системное решение:**
В корпоративном кластере администраторы обязаны настроить метод отслеживания на использование аннотаций в ConfigMap `argocd-cm`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  # Полностью исключает перезапись метки app.kubernetes.io/instance
  application.resourceTrackingMethod: annotation
```

После переключения Argo CD фиксирует право собственности через аннотацию `argocd.argoproj.io/tracking-id`, сохраняя исходную метку релиза Helm нетронутой.

## Практические сценарии и конфигурация

### Предварительные требования и валидация окружения

Перед настройкой интеграции проверьте соответствие версий компонентов и сетевую доступность инфраструктуры:

```bash
# 1. Проверка версии сервера и клиента Kubernetes (требуется v1.28+)
kubectl version --output=yaml
# → clientVersion:
# →   gitVersion: v1.31.1
# → serverVersion:
# →   gitVersion: v1.30.4

# 2. Проверка состояния подов ядра Argo CD в пространстве имен argocd
kubectl get pods -n argocd -l app.kubernetes.io/part-of=argocd
# → NAME                                                READY   STATUS    RESTARTS   AGE
# → argocd-application-controller-0                     1/1     Running   0          14d
# → argocd-repo-server-678b7c5b6b-q7w2x                 1/1     Running   0          14d
# → argocd-server-5d688cf86d-p4vlm                      1/1     Running   0          14d

# 3. Проверка установленного Helm CLI на рабочей станции инженера
helm version --short
# → v3.16.2+g136519f

# 4. Проверка прав ServiceAccount на управление ресурсами Application
kubectl auth can-i create applications.argoproj.io -n argocd
# → yes
```

---

### Сценарий 1: Декларативное развертывание из On-Premise OCI-реестра (Harbor)

Развертывание чарта из корпоративного реестра Harbor с самоподписанным сертификатом удостоверяющего центра (Corporate Internal CA) и аутентификацией по роботу-токену.

#### Шаг 1: Добавление CA-сертификата реестра в Argo CD

Для предотвращения ошибки `x509: certificate signed by unknown authority` добавьте корневой сертификат Harbor в ConfigMap `argocd-tls-certs-cm`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-tls-certs-cm
  namespace: argocd
  labels:
    app.kubernetes.io/part-of: argocd
data:
  # Имя ключа должно совпадать с FQDN хоста реестра
  harbor.corp.internal: |
    -----BEGIN CERTIFICATE-----
    MIIExtCCA0mgAwIBAgIUQ7m... (Содержимое Root CA в PEM-формате)
    -----END CERTIFICATE-----
```

```bash
kubectl apply -f harbor-ca-cm.yaml
# → configmap/argocd-tls-certs-cm configured
```

#### Шаг 2: Создание секрета учетных данных OCI-репозитория

Репозитории OCI настраиваются через секреты с меткой `argocd.argoproj.io/secret-type: repository`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: repo-harbor-oci-charts
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
type: Opaque
stringData:
  type: helm
  enableOCI: "true"
  name: harbor-corp-oci
  url: harbor.corp.internal/helm-charts
  username: "robot$argocd-puller"
  password: "HarborRobotTokenSecretValue123"
```

```bash
kubectl apply -f repo-harbor-secret.yaml
# → secret/repo-harbor-oci-charts created

# Проверка регистрации репозитория в Argo CD
argocd repo list
# → TYPE  NAME             REPO                                    STATUS      MESSAGE
# → helm  harbor-corp-oci  harbor.corp.internal/helm-charts       Successful
```

#### Шаг 3: Манифест Application для OCI-чарта

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ingress-nginx-prod
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: harbor.corp.internal/helm-charts
    chart: ingress-nginx
    targetRevision: 4.11.2
    helm:
      releaseName: ingress-nginx
      values: |
        controller:
          replicaCount: 3
          metrics:
            enabled: true
          service:
            externalTrafficPolicy: Local
  destination:
    server: https://kubernetes.default.svc
    namespace: ingress-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
```

---

### Сценарий 2: Production Multi-Source паттерн (Разделение чарта и конфигураций)

Изоляция версионирования публичного или платформенного чарта (находящегося в общем OCI-реестре) от прикладных конфигураций окружений (находящихся в приватном репозитории GitLab).

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: postgresql-ha-cluster
  namespace: argocd
spec:
  project: default
  sources:
    # Первичный источник: бинарный Helm-чарт из OCI-реестра
    - repoURL: harbor.corp.internal/helm-charts
      chart: postgresql-ha
      targetRevision: 14.2.1
      helm:
        releaseName: postgres-main
        valueFiles:
          - $configs/clusters/baremetal-prod/base-values.yaml
          - $configs/clusters/baremetal-prod/postgres-overrides.yaml
    # Вторичный источник: Git-репозиторий конфигураций окружений
    - repoURL: git@gitlab.corp.internal:sre-team/cluster-configs.git
      targetRevision: release/2026.4
      ref: configs
  destination:
    server: https://kubernetes.default.svc
    namespace: database
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - RespectIgnoreDifferences=true
  ignoreDifferences:
    - group: apps
      kind: StatefulSet
      jsonPointers:
        - /spec/replicas
```

---

### Сценарий 3: Локальные сабчарты и зависимости в Air-Gapped контуре

В закрытых промышленных сегментах (Air-Gap / без прямого доступа в Интернет) чарты часто оформляются в виде Umbrella-структуры с локальными зависимостями через протокол `file://`.

#### Структура репозитория чарта:

```text
gitops-monorepo/
└── charts/
    └── platform-portal/
        ├── Chart.yaml
        ├── Chart.lock
        ├── values.yaml
        ├── charts/
        │   ├── common-lib-1.2.0.tgz
        │   └── worker-backend-3.4.1.tgz
        └── templates/
            └── portal-deployment.yaml
```

#### Файл `Chart.yaml`:

```yaml
apiVersion: v2
name: platform-portal
version: 1.0.0
dependencies:
  - name: common-lib
    version: 1.2.0
    repository: "file://./charts/common-lib-1.2.0.tgz"
  - name: worker-backend
    version: 3.4.1
    repository: "file://./charts/worker-backend-3.4.1.tgz"
```

#### Манифест Application:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: platform-portal-airgap
  namespace: argocd
spec:
  project: default
  source:
    repoURL: git@gitlab.corp.internal:enterprise/gitops-apps.git
    targetRevision: main
    path: charts/platform-portal
    helm:
      releaseName: platform-portal
      valueFiles:
        - ../../environments/prod/portal-values.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: platform
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
```

> [!IMPORTANT]
> Если файл `Chart.lock` присутствует в каталоге, `argocd-repo-server` автоматически выполняет `helm dependency build`. При использовании локальных архивов в каталоге `charts/` эти архивы обязаны быть закоммичены в Git, иначе процесс сборки в изолированном контуре завершится сбоем.

---

### Сценарий 4: Декларативное управление CRD и операторами с Server-Side Apply

При развертывании тяжелых инфраструктурных чартов (например, `kube-prometheus-stack` или `victoria-metrics-k8s-stack`) стандартный клиентский `kubectl apply` падает из-за превышения лимита 256 KB в аннотации `last-applied-configuration`. Кроме того, ресурсы оператора пытаются создаться до того, как API-сервер зарегистрирует CRD.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: monitoring-stack
  namespace: argocd
spec:
  project: default
  source:
    repoURL: harbor.corp.internal/helm-charts
    chart: kube-prometheus-stack
    targetRevision: 62.6.0
    helm:
      releaseName: monitoring
      skipCrds: false
      values: |
        prometheus:
          prometheusSpec:
            retention: 30d
            storageSpec:
              volumeClaimTemplate:
                spec:
                  storageClassName: local-nvme-sc
                  resources:
                    requests:
                      storage: 200Gi
  destination:
    server: https://kubernetes.default.svc
    namespace: monitoring
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      # Включает применение через API server с менеджером fieldManager=argocd (обходит лимит 256 KB)
      - ServerSideApply=true
      # Игнорирует отсутствие CRD на этапе валидации dry-run при первом развертывании
      - SkipDryRunOnMissingResource=true
```

---

### Сценарий 5: Масштабирование через ApplicationSet с Git-генератором

Шаблонизация сотен инсталляций сервисов по каталогам bare-metal кластеров с автоматическим извлечением значений.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: internal-services-helm
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
  generators:
    - git:
        repoURL: git@gitlab.corp.internal:platform/cluster-workloads.git
        revision: main
        directories:
          - path: workloads/prod/*
  template:
    metadata:
      name: 'prod-{{ index (split "/" .path) 2 }}'
      labels:
        environment: production
        workload-type: microservice
    spec:
      project: default
      sources:
        - repoURL: harbor.corp.internal/helm-charts
          chart: corp-microservice-archetype
          targetRevision: 2.5.0
          helm:
            releaseName: '{{ index (split "/" .path) 2 }}'
            valueFiles:
              - '$config/{{ .path }}/values.yaml'
        - repoURL: git@gitlab.corp.internal:platform/cluster-workloads.git
          targetRevision: main
          ref: config
      destination:
        server: https://kubernetes.default.svc
        namespace: 'app-{{ index (split "/" .path) 2 }}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
          - ServerSideApply=true
```

---

### Сценарий 6: Шифрование секретов поверх Helm через CMP v2 и SOPS

Для безопасного хранения значений с паролями и токенами в Git используется связка Helm и Mozilla SOPS через изолированный Config Management Plugin (CMP v2).

#### Шаг 1: Конфигурация плагина `plugin.yaml`

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cmp-helm-sops-config
  namespace: argocd
data:
  plugin.yaml: |
    apiVersion: argoproj.io/v1alpha1
    kind: ConfigManagementPlugin
    metadata:
      name: helm-sops-renderer
    spec:
      version: v1.0
      discover:
        fileName: "sops-values.enc.yaml"
      generate:
        command: ["bash", "-c"]
        args:
          - |
            set -euo pipefail
            sops -d sops-values.enc.yaml > /tmp/decrypted-values.yaml
            helm template "$ARGOCD_APP_NAME" . \
              --namespace "$ARGOCD_APP_NAMESPACE" \
              -f values.yaml \
              -f /tmp/decrypted-values.yaml
            rm -f /tmp/decrypted-values.yaml
```

#### Шаг 2: Использование плагина в манифесте `Application`

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: secured-api-gateway
  namespace: argocd
spec:
  project: default
  source:
    repoURL: git@gitlab.corp.internal:infra/secured-apps.git
    targetRevision: main
    path: apps/gateway
    plugin:
      name: helm-sops-renderer
  destination:
    server: https://kubernetes.default.svc
    namespace: gateway
```

---

### Сценарий 7: On-Premise CI-пайплайн (GitLab CI) для валидации Helm-чартов

Предотвращение попадания синтаксических ошибок и некорректных значений в GitOps-репозиторий.

```yaml
# .gitlab-ci.yml
stages:
  - lint-and-test
  - conformance

variables:
  HELM_VERSION: "v3.16.2"
  KUBECONFORM_VERSION: "v0.6.7"

helm-lint:
  stage: lint-and-test
  image: harbor.corp.internal/ci-tools/helm-ci:latest
  script:
    - echo "==> Запуск Helm lint для всех чартов"
    - helm lint charts/my-service -f environments/production/values.yaml
    - echo "==> Локальная проверка схемы values.schema.json"
    - helm template test-release charts/my-service -f environments/production/values.yaml --dry-run > /dev/null

kubeconform-validate:
  stage: conformance
  image: harbor.corp.internal/ci-tools/kubeconform:latest
  script:
    - echo "==> Рендеринг манифестов"
    - helm template test-release charts/my-service -f environments/production/values.yaml > rendered-manifests.yaml
    - echo "==> Валидация схемы Kubernetes 1.30"
    - kubeconform -schema-location default -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' -strict -summary rendered-manifests.yaml
```

## Операции и команды

Практический справочник команд для инженера DevOps и SRE при эксплуатации интеграции:

### Проверка репозиториев и рендеринга

```bash
# Просмотр подключенных репозиториев
argocd repo list
# → TYPE  NAME             REPO                                    STATUS      MESSAGE
# → helm  harbor-corp-oci  harbor.corp.internal/helm-charts       Successful

# Принудительная очистка кеша репозитория и проверка доступности
argocd repo get harbor.corp.internal/helm-charts --refresh
# → Name: harbor-corp-oci
# → Type: helm
# → URL: harbor.corp.internal/helm-charts
# → Connection Status: Successful

# Просмотр скомпилированных манифестов приложения без применения в кластер
argocd app manifests ingress-nginx-prod | head -n 30
# → ---
# → # Source: ingress-nginx/templates/controller-deployment.yaml
# → apiVersion: apps/v1
# → kind: Deployment
# → metadata:
# →   name: ingress-nginx-controller
```

### Анализ различий (Diff) и валидация

```bash
# Просмотр расхождений между Git/Helm и текущим состоянием кластера
argocd app diff ingress-nginx-prod
# → ===== apps/Deployment ingress-system/ingress-nginx-controller ======
# → 28c28
# → <   replicas: 2
# → ---
# → >   replicas: 3

# Проверка расхождений с использованием Server-Side Diff (учитывает мутирующие вебхуки)
argocd app diff ingress-nginx-prod --server-side-diff
# → (Выводит только реальные смысловые изменения без мутаций кластера)

# Проверка рендеринга с локальными значениями перед коммитом
argocd app diff ingress-nginx-prod --local ./charts/ingress-nginx -f custom-values.yaml
# → (Показывает изменения, которые произойдут при применении локального каталога)
```

### Синхронизация, откат и управление

```bash
# Ручной запуск синхронизации с принудительной очисткой кеша repo-server
argocd app sync ingress-nginx-prod --force --prune
# → TIMESTAMP                  GROUP        KIND   NAMESPACE       NAME    STATUS    HEALTH        HOOK  MESSAGE
# → 2026-10-12T20:45:10+03:00  apps   Deployment  ingress-system  ingress  Synced   Healthy              deployment.apps/ingress-nginx-controller configured

# Откат приложения к предыдущей успешной ревизии
argocd app rollback ingress-nginx-prod
# → Rollback to revision 4.11.1 initiated successfully

# Просмотр истории версий и изменений приложения
argocd app history ingress-nginx-prod
# → ID  DATE                           REVISION  SOURCE
# → 1   2026-10-10 11:20:00 +0300 MSK  4.10.0    harbor.corp.internal/helm-charts
# → 2   2026-10-11 14:15:30 +0300 MSK  4.11.1    harbor.corp.internal/helm-charts
# → 3   2026-10-12 20:45:10 +0300 MSK  4.11.2    harbor.corp.internal/helm-charts
```

## Диагностика и устранение неисправностей

### Алгоритм систематической диагностики инцидентов

При возникновении сбоев синхронизации Helm-приложений SRE-инженер следует алгоритму декомпозиции проблемы:

```text
1. Определение статуса приложения:
   argocd app get <app-name>
   ├── ComparisonError? ──▶ Ошибка рендеринга манифестов в repo-server (Шаг 2)
   ├── Synced / Degraded? ──▶ Манифесты применились, сбой на уровне Pod/Workload (Шаг 5)
   └── OutOfSync / SyncFailed? ──▶ Ошибка Kube API при применении (SSA / Селекторы) (Шаг 4)

2. Проверка генерации манифестов:
   argocd app manifests <app-name>
   ├── Ошибка "Helm template failed"? ──▶ Ошибка синтаксиса шаблонов или schema validation (Шаг 3)
   ├── Ошибка "values file not found"? ──▶ Ошибка в пути $ref или имени ветки Multiple Sources
   └── Ошибка "DeadlineExceeded"? ──▶ Таймаут repo-server при клонировании или выполнении

3. Локальная проверка шаблонизатора (эмуляция repo-server):
   helm template <release> <chart-source> -f <values-files...>
   ├── Воспроизводится локально? ──▶ Исправить опечатки в values.yaml или шаблоне Go
   └── Локально успешно? ──▶ Проблема в сетевом доступе или OCI credentials в кластере

4. Анализ логов применения в Application Controller:
   kubectl logs -n argocd deploy/argocd-application-controller --tail=100 | grep <app-name>
   ├── "field is immutable" ──▶ Конфликт метки instance с неизменяемым matchLabels
   └── "annotation length limit exceeded" ──▶ Включить ServerSideApply=true

5. Анализ логов вычислительного ядра repo-server:
   kubectl logs -n argocd deploy/argocd-repo-server -c repo-server --tail=100
   ├── "x509: certificate signed by unknown authority" ──▶ Добавить CA в argocd-tls-certs-cm
   └── "OOMKilled / signal: killed" ──▶ Увеличить memory limit пода repo-server
```

### Команды глубокой инспекции среды `argocd-repo-server`

```bash
# 1. Поиск критических ошибок компиляции шаблонов в логах repo-server
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -c repo-server --tail=200 | grep -E "level=error|helm template|sourceHydrator"

# 2. Проверка утилизации памяти и обнаружение OOMKilled перезапусков
kubectl describe pod -n argocd -l app.kubernetes.io/name=argocd-repo-server | grep -E "Limits:|Requests:|Last State:|Exit Code:"
# → Limits:
# →   memory:  4Gi
# → Last State: Terminated
# →   Exit Code: 137 (137 свидетельствует об OOMKilled)

# 3. Принудительный сброс дискового и оперативного кеша рендеринга
kubectl rollout restart deployment argocd-repo-server -n argocd
# → deployment.apps/argocd-repo-server restarted

# 4. Проверка времени рендеринга манифестов через Prometheus метрики
kubectl port-forward -n argocd deploy/argocd-repo-server 8084:8084 > /dev/null 2>&1 &
curl -s http://127.0.0.1:8084/metrics | grep "argocd_git_request_duration_seconds"
```

### Таблица типовых инцидентов и решений

| Симптом / Текст ошибки | Первопричина | Метод диагностики | Инженерное решение |
| :--- | :--- | :--- | :--- |
| `Helm template failed: execution error at (my-chart/templates/...): nil pointer evaluating interface` | В переданных `values.yaml` отсутствует обязательная переменная, требуемая шаблоном. | `helm template test ./chart -f values.yaml` | Добавить недостающую секцию в переопределения `values.yaml` или объявить значение по умолчанию в чарте. |
| `stat /tmp/_app/.../values-prod.yaml: no such file or directory` | Опечатка в пути `helm.valueFiles` или неверное имя псевдонима `$ref` во вторичном источнике. | `argocd app get <app> -o yaml \| grep -A 10 sources:` | Проверить чувствительность к регистру (case-sensitive) и точное совпадение алиаса `$ref`. |
| `spec.template.metadata.labels: Invalid value: field is immutable` | Конфликт метки отслеживания `app.kubernetes.io/instance` между именем Application и `releaseName`. | `argocd app diff <app>` показывает изменение селектора в `Deployment` | Переключить отслеживание на аннотации в `argocd-cm`: `application.resourceTrackingMethod: annotation`. |
| `x509: certificate signed by unknown authority` при OCI pull | Реестр Harbor использует корпоративный или самоподписанный SSL/TLS сертификат. | Логи `argocd-repo-server`: `failed to do request: Head ...` | Добавить корневой сертификат реестра в ConfigMap `argocd-tls-certs-cm`. |
| `dry-run failed: CustomResourceDefinition ... not found` | Чарт создает CRD и экземпляры Custom Resource в одной транзакции синхронизации. | Ошибка на этапе пре-валидации dry-run перед развертыванием | Добавить флаг в спецификацию: `syncOptions: ["SkipDryRunOnMissingResource=true"]`. |
| `metadata.annotations: Too long: must have at most 262144 bytes` | Размер генерируемого манифеста превысил 256 KB лимит аннотации `last-applied-configuration`. | Ошибка API сервера `422 Unprocessable Entity` | Включить применение на стороне сервера: `syncOptions: ["ServerSideApply=true"]`. |
| `rpc error: code = DeadlineExceeded desc = context deadline exceeded` | Repo-server не успел склонировать монорепозиторий или скомпилировать зависимости за 90 секунд. | Метрика `argocd_git_request_duration_seconds` превышает порог | Увеличить `controller.repo.server.timeout.seconds: "180"` в ConfigMap `argocd-cmd-params-cm`. |
| `command 'helm dependency build' failed: exit status 1` | Отсутствует доступ к внешнему репозиторию сабчарта из закрытого контура. | Логи `repo-server`: `no repository definition -- unable to update` | Предварительно упаковать зависимости в каталог `charts/` и зафиксировать `Chart.lock` в Git. |
| `values.schema.json validation failed: field 'replicas' must be integer` | Значение в `values.yaml` нарушает JSON-схему чарта (например, передана строка `"3"` вместо числа `3`). | `helm lint ./chart -f values.yaml` | Привести типы данных в соответствие с требованиями схемы `values.schema.json`. |
| `repo-server OOMKilled (Exit Code 137)` | Всплеск аллокации памяти при параллельном рендеринге нескольких тяжелых чартов. | `kubectl describe pod argocd-repo-server` показывает `OOMKilled: true` | Увеличить `resources.limits.memory` до `4Gi–8Gi`, включить `repo.server.use.shallow.clone: "true"`. |
| `Out of Sync: drift on replicas` при использовании HPA | Контроллер HPA динамически масштабирует реплики, а Argo CD воспринимает это как дрейф. | `argocd app diff` постоянно указывает на расхождение в `/spec/replicas` | Добавить секцию `ignoreDifferences` для пути `/spec/replicas` целевого контроллера. |
| `Target revision 'v2.x' not found in OCI registry` | В OCI-реестре запрошен динамический диапазон версий или тег, не поддерживаемый реестром. | `helm pull oci://... --version v2.x` завершается ошибкой 404 | В OCI-реестрах указывать только фиксированные SemVer теги (`2.1.4`) или точный дайджест. |

## Лучшие практики

### Архитектура и надежность

1. **Декомпозиция Umbrella-чартов:**
   - Избегайте монолитных чартов, объединяющих десятки независимых компонентов кластера (база данных, бэкенд, ingress, мониторинг) в единый релиз.
   - Используйте паттерн **ApplicationSet** или **Multiple Sources**: каждый компонент развертывается как независимый объект `Application`. Это изолирует радиус поражения (blast radius) при сбое и ускоряет рендеринг.
2. **Фиксация ревизий и блокировка зависимостей:**
   - Запрещено использовать псевдо-теги `latest`, плавающие ветки `main` или динамические диапазоны версий `1.x` в продуктивных средах.
   - Всегда фиксируйте `targetRevision` на конкретном SemVer-теге чарта (`1.14.2`) и фиксируйте файл `Chart.lock` в Git для исключения неожиданных обновлений сабчартов.
3. **Строгая валидация схем (Contract Testing):**
   - Разрабатывайте файл `values.schema.json` для каждого внутреннего чарта. Это позволяет отклонять синтаксически неверные конфигурации на этапе pre-commit / CI до их передачи в `argocd-repo-server`.

### Системное администрирование и сайзинг `argocd-repo-server`

1. **Гарантированные ресурсы (QoS Guaranteed):**
   - Нагрузка на процессор и оперативную память в `argocd-repo-server` носит резко выраженный пиковый характер при синхронизации десятков приложений.
   - Для стабильной работы на bare-metal кластерах задайте следующие параметры ресурсов в `argocd-repo-server`:
     ```yaml
     resources:
       requests:
         cpu: 1000m
         memory: 2Gi
       limits:
         cpu: 4000m
         memory: 6Gi
     ```
2. **Оптимизация работы с Git:**
   - Включите shallow cloning в ConfigMap `argocd-cmd-params-cm` для ускорения выгрузки монорепозиториев:
     ```yaml
     data:
       repo.server.use.shallow.clone: "true"
       repo.server.parallelism.limit: "10"
     ```
3. **Изоляция дискового пространства `/tmp`:**
   - Смонтируйте том `emptyDir` с типом `Memory` или скоростным NVMe-диском для каталога `/tmp` пода `argocd-repo-server` для минимизации задержек ввода-вывода при частой распаковке архивов чартов.

### Безопасность в On-Premise контуре

1. **Изоляция через AppProject:**
   - Ограничивайте список доверенных репозиториев (`sourceRepositories`) в манифестах `AppProject`. Это предотвращает загрузку неавторизованных чартов из внешних источников.
     ```yaml
     spec:
       sourceRepositories:
         - 'harbor.corp.internal/helm-charts'
         - 'git@gitlab.corp.internal:apps/*'
     ```
2. **Исключение секретов из Git:**
   - Не передавайте чувствительные параметры через `helm.parameters` в открытом виде в манифесте `Application`.
   - Используйте расширения CMP v2 (SOPS, HashiCorp Vault / OpenBao, External Secrets Operator) для доставки секретов в кластер.
3. **Сетевые политики (NetworkPolicies):**
   - Ограничьте исходящий трафик (Egress) пода `argocd-repo-server` только внутренними адресами корпоративных Git-серверов (GitLab, Gitea) и OCI-реестров (Harbor), заблокировав неконтролируемый доступ во внешние сегменты сети.

## Дополнительная информация

### Связанные материалы базы знаний

- [Обзор архитектуры Argo CD](./argocd_overview.md) — компоненты ядра, модель синхронизации и жизненный цикл приложений.
- [Multiple Sources и sourceHydrator](./argocd_multi_source_apps.md) — детальная архитектура гидрации манифестов, объединение репозиториев и разрешение конфликтов LWW.
- [Отслеживание ресурсов и Tracking ID](./argocd_resource_tracking.md) — специфика методов `annotation`, `label`, предотвращение коллизий селекторов.
- [Диагностика и мониторинг Argo CD](./argocd_troubleshooting_and_monitoring.md) — сбор метрик Prometheus, трассировка gRPC и решение проблем производительности.
- [Custom Tooling и плагины (CMP v2)](./argocd_custom_tooling.md) — разработка и интеграция sidecar-плагинов для нестандартных инструментов сборки манифестов.
- [Интеграция с Vault](./argocd_vault_integration.md) — динамическая интерполяция секретов в манифесты при рендеринге.
- [Управление через ApplicationSets](./argocd_applicationsets.md) — генераторы Git, List, Matrix для масштабного развертывания чартов.
- [Политики синхронизации и Sync Options](./synchronization.md) — детальный разбор параметров `ServerSideApply`, `SkipDryRunOnMissingResource`, `Replace`.

### Ссылки на базу знаний Helm

- [Обзор Helm и концепции чартов](../../Kubernetes/ToolsUtilities/Helm/helm_overview.md)
- [Структура Helm-чарта и управление зависимостями](../../Kubernetes/ToolsUtilities/Helm/helm_chart_structure.md)
- [Хуки и тестирование в Helm](../../Kubernetes/ToolsUtilities/Helm/helm_hooks_and_tests.md)
- [Шаблонизация и функции Go-templates в Helm](../../Kubernetes/ToolsUtilities/Helm/helm_templating.md)
- [Основные команды и рабочий процесс Helm](../../Kubernetes/ToolsUtilities/Helm/helm_commands_and_workflow.md)

### Официальная документация

- [Argo CD Documentation: Helm](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/)
- [Argo CD Documentation: Multiple Sources](https://argo-cd.readthedocs.io/en/stable/user-guide/multiple-sources/)
- [Helm Official Documentation: Chart Development Guide](https://helm.sh/docs/topics/charts/)
