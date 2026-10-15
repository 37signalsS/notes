# Flux — обзор и ключевые концепции

**Актуально для:** Flux v2.9.x

**Flux** — это модульный и расширяемый набор инструментов для построения GitOps-конвейеров в Kubernetes. Проект является частью CNCF (Graduated) и следует философии «Unix-way»: каждый контроллер решает строго определенную задачу (работа с источниками, сборка Kustomize, управление Helm-релизами, нотификации), а взаимодействие между ними организуется через стандартные ресурсы Kubernetes (CRD) и Kubernetes API.

Актуальная линейка версий — **Flux v2.9.x** (GA-релиз v2.9.0 — 30 июня 2026, текущий патч — v2.9.4, август 2026). Поддерживаются Kubernetes 1.34–1.36 и OpenShift 4.21; ветка v2.6 достигла статуса end-of-life (EOL). Flux следует релизному циклу Kubernetes (три минорных релиза в год) и гарантирует поддержку N-2 минорных версий платформы. Данное руководство ориентировано на эксплуатацию в частных инфраструктурах, on-premise и bare-metal кластерах.

---

## Определения

- **Flux**: Набор операторов (GitOps Toolkit), автоматизирующих синхронизацию состояния кластера с эталонными конфигурациями из Git-репозиториев, OCI-реестров и S3-совместимых хранилищ.
- **GitOps Toolkit (GOTK)**: Модульная кодовая база и экосистема специализированных контроллеров Kubernetes, из которых скомпонован Flux.
- **Reconciliation (Согласование / Реконсиляция)**: Непрерывный процесс, при котором контроллер сравнивает декларативное эталонное состояние из внешнего источника с фактическим состоянием в кластере и устраняет расхождения. В основе лежит паттерн **Reconciliation Loop** (цикл сверки).
- **Drift Detection & Correction (Обнаружение и устранение дрейфа)**: Механизм автоматического выявления несанкционированных или ручных изменений в объектах кластера (`kubectl edit`, случайное удаление) и принудительного возврата их к эталону из Git/OCI.
- **Server-Side Apply (SSA)**: Механизм применения манифестов на стороне Kubernetes API (`fieldManager`), позволяющий отслеживать владение отдельными полями ресурсов и бесконфликтно сосуществовать с внешними контроллерами (например, HPA).
- **Bootstrap**: Процесс первичной инициализации Flux в кластере, при котором управляющие манифесты контроллеров коммитятся в Git-репозиторий, а кластер настраивается на синхронизацию собственного состояния из этого репозитория.
- **Artifact (Артефакт)**: Сжатый tar-архив с манифестами или Helm-чартом, сформированный контроллером `source-controller` на основе определенной ревизии источника (коммита, тега или OCI-digest). Служит внутренней неизменяемой единицей передачи данных между контроллерами.
- **Impersonation (Олицетворение ServiceAccount)**: Механизм безопасности Kubernetes, позволяющий контроллерам Flux применять манифесты не от имени привилегированного аккаунта Flux, а от имени выделенного ограниченного `ServiceAccount` тенанта.
- **DAG (Directed Acyclic Graph)**: Направленный ациклический граф зависимостей между объектами `Kustomization` (через поле `dependsOn`), гарантирующий строгий порядок применения (например, сначала CRD, затем операторы, затем кастомные ресурсы).

---

## Архитектура и базовые концепции

### Архитектура набора инструментов GitOps (GitOps Toolkit)

Flux состоит из набора независимых контроллеров, взаимодействующих исключительно через Kubernetes API:

| Контроллер | Основные CRD | Назначение |
| :--- | :--- | :--- |
| `source-controller` | `GitRepository`, `HelmRepository`, `OCIRepository`, `Bucket` | Загрузка артефактов из внешних источников (Git, Helm HTTP/OCI, S3/MinIO), вычисление контрольных сумм и раздача архивов остальным контроллерам через внутренний HTTP-сервер. |
| `source-watcher` | `ArtifactGenerator` | Оптимизация работы с монорепозиториями: генерирует составные артефакты для конкретных путей, снижая сетевую нагрузку и исключая лишние пересборки. Включается в базовую поставку начиная с v2.9. |
| `kustomize-controller` | `Kustomization` | Генерация и валидация манифестов с помощью Kustomize, расшифровка секретов (SOPS), Server-Side Apply и проверка доступности ресурсов (`healthChecks`). |
| `helm-controller` | `HelmRelease` | Декларативное управление жизненным циклом Helm-чартов: рендеринг, установка, обновление, тестирование и автоматический откат при сбоях. |
| `notification-controller` | `Provider`, `Alert`, `Receiver` | Прием внутренних событий кластера и отправка алертов во внешние системы (Mattermost, Telegram, Slack, Webhooks), а также прием входящих webhook-запросов (`Receiver`) для мгновенного запуска реконсиляции из CI. |
| `image-reflector-controller` | `ImageRepository`, `ImagePolicy` | Сканирование реестров контейнеров (Harbor, локальные registry) и выбор актуальных тегов по заданным политикам (SemVer, regex, алфавитный порядок). |
| `image-automation-controller` | `ImageUpdateAutomation` | Автоматическая модификация файлов манифестов в Git-репозитории и создание коммитов при обнаружении новых образов. |

Ключевые архитектурные принципы:
- **Отсутствие прямого межконтроллерного взаимодействия**: контроллеры не вызывают RPC друг друга. `source-controller` поднимает легковесный HTTP-сервер внутри кластера (порт 80), а другие контроллеры скачивают артефакты по URL, указанному в `.status.artifact.url`.
- **Изоляция в namespace `flux-system`**: все компоненты работают в выделенном пространстве имен с раздельными `ServiceAccount`.
- **Встроенная наблюдаемость (Observability)**: каждый контроллер отдает Prometheus-метрики на порту `8080` (эндпоинт `/metrics`) и генерирует события Kubernetes (`Normal`, `Warning`) для управляемых объектов.

### Модель реконсиляции и жизненный цикл объекта

Жизненный цикл ресурсов `Kustomization` и `HelmRelease`:

```
[Триггер: интервал / webhook / dependsOn]
                   │
                   ▼
       [source-controller]
   Проверка новой ревизии (commit/digest)
                   │
                   ▼
     [Генерация внутреннего артефакта]
                   │
                   ▼
     [kustomize / helm-controller]
  Скачивание артефакта + Валидация + SOPS
                   │
                   ▼
         [Server-Side Apply]
  Сверка с kube-apiserver и учет spec.ignore
                   │
                   ▼
         [healthChecks / Ready?]
                   │
       ┌───────────┴───────────┐
       ▼                       ▼
    [Успех]                 [Ошибка]
Статус: Ready=True      Статус: Ready=False
ReconciliationSucceeded  Backoff retry / Alert
```

1. **Триггер**: истечение таймера `spec.interval`, входящий webhook через `Receiver`, ручная аннотация `reconcile.fluxcd.io/requestedAt` (команда `flux reconcile`) или успешный переход зависимого объекта (`dependsOn`) в статус `Ready=True`.
2. **Получение источника**: контроллер сверяет ревизию артефакта (`status.artifact.revision`) с последней доступной ревизией источника.
3. **Сборка и валидация**: для `Kustomization` выполняется сборка Kustomize (с подстановкой переменных `postBuild.substitute` и расшифровкой SOPS); для `HelmRelease` — рендеринг values и post-renderers.
4. **Применение (Apply)**: манифесты передаются в `kube-apiserver` через Server-Side Apply.
5. **Проверка готовности (Health Checks)**: контроллер ожидает готовности подов, сервисов и CRD согласно списку `spec.healthChecks`.
6. **Фиксация статуса**: обновляются поля `status.lastAppliedRevision`, условия `Ready`, публикуются события Kubernetes.

Параметры управления жизненным циклом:
- `spec.interval` — обязательный интервал периодической сверки (например, `10m`).
- `spec.timeout` — максимальное время выполнения одной итерации (по умолчанию `1m`–`5m`).
- `spec.retry` / экспоненциальный backoff — защита API-сервера от шторма запросов при перманентных сбоях.
- `spec.suspend: true` — заморозка цикла сверки (объект не обновляется и не исправляет дрейф).

### Ключевые ресурсы (CRD) и версии API

Актуальные стабильные версии API во Flux v2.9.x:

| Ресурс | apiVersion | Статус | Назначение |
| :--- | :--- | :--- | :--- |
| `GitRepository` | `source.toolkit.fluxcd.io/v1` | GA | Подключение Git-репозиториев (SSH/HTTPS) |
| `HelmRepository` | `source.toolkit.fluxcd.io/v1` | GA | Подключение HTTP/OCI Helm-репозиториев |
| `OCIRepository` | `source.toolkit.fluxcd.io/v1beta2` | Beta | Подключение OCI-артефактов с манифестами/чартами |
| `Bucket` | `source.toolkit.fluxcd.io/v1` | GA | Подключение S3-совместимых объектных хранилищ (MinIO, Ceph) |
| `Kustomization` | `kustomize.toolkit.fluxcd.io/v1` | GA | Развертывание директорий с манифестами/оверлеями |
| `HelmRelease` | `helm.toolkit.fluxcd.io/v2` | GA | Управление Helm-релизами и их откатами |
| `ImageRepository` | `image.toolkit.fluxcd.io/v1` | GA | Сканирование реестров образов |
| `ImagePolicy` | `image.toolkit.fluxcd.io/v1` | GA | Правила отбора тегов образов (SemVer) |
| `ImageUpdateAutomation` | `image.toolkit.fluxcd.io/v1` | GA | Автокоммит обновленных тегов в Git |
| `Provider`, `Alert`, `Receiver` | `notification.toolkit.fluxcd.io/v1beta3` | Beta | Маршрутизация событий и входящие вебхуки |

> [!WARNING]
> Во Flux v2.9 из CRD полностью удалены устаревшие версии API (`v1beta1`, `v2beta1`, `v2beta2`). Перед обновлением кластера выполните миграцию манифестов командой `flux migrate`.

### Граф зависимостей развертывания (dependsOn)

Параметр `dependsOn` в ресурсе `Kustomization` формирует детерминированный граф развертывания:
- Зависимый объект не начнет реконсиляцию, пока родительский не перейдет в состояние `Ready=True` (все манифесты применены, а `healthChecks` успешно пройдены).
- Запрещены циклические зависимости. При обнаружении цикла контроллер переводит объекты в `Ready=False` с диагностической ошибкой `dependency cycle detected`.
- Рекомендуемая структура слоев: `infra-crds` → `infra-controllers` → `apps-backend` → `apps-frontend`.

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: cert-manager-crds
  namespace: flux-system
spec:
  interval: 1h
  path: ./infrastructure/cert-manager/crds
  prune: true
  sourceRef:
    kind: GitRepository
    name: fleet-infra
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: cert-manager-app
  namespace: flux-system
spec:
  interval: 15m
  dependsOn:
    - name: cert-manager-crds
  path: ./infrastructure/cert-manager/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: fleet-infra
  healthChecks:
    - apiVersion: apps/v1
      kind: Deployment
      name: cert-manager
      namespace: cert-manager
```

### Мультитенантность и изоляция (Multi-tenancy)

Flux поддерживает строгую мультитенантность на базе механизмов Kubernetes RBAC:
1. **ServiceAccount Impersonation**: Параметр `spec.serviceAccountName` в `Kustomization` или `HelmRelease` заставляет контроллер выполнять все вызовы к `kube-apiserver` от имени указанного ServiceAccount с правами, ограниченными целевым пространством имен (через `RoleBinding`).
2. **Lockdown-режим**: При запуске контроллеров с флагами `--default-service-account=default` и `--no-cross-namespace-refs=true` запрещаются перекрестные ссылки на секреты и источники из чужих пространств имен, а также блокируется эскалация привилегий через манифесты в Git.

### Управление секретами и расшифровка SOPS

Безопасное хранение секретов в Git без утечки открытых данных:
- **Mozilla SOPS**: Файлы секретов шифруются публичным ключом age или PGP и сохраняются в Git в виде зашифрованных YAML-манифестов (`*.enc.yaml`). Расшифровка выполняется на лету в оперативной памяти `kustomize-controller` перед передачей в API Kubernetes. Приватный ключ хранится исключительно в кластере Kubernetes в Secret `sops-age`.
- **Хранилища секретов (Vault / OpenBao)**: Аутентификация `kustomize-controller` в HashiCorp Vault или OpenBao через Kubernetes Workload Identity (токен `ServiceAccount` контроллера обменивается на авторизационный токен хранилища без постоянных статических паролей) либо через External Secrets Operator (ESO).

### Контроль дрейфа и игнорирование полей (Drift Control)

Server-Side Apply фиксирует принадлежность каждого поля менеджеру (`fieldManager: kustomize-controller`). Однако сторонние контроллеры могут модифицировать поля тех же ресурсов:
- HPA динамически меняет `spec.replicas`.
- Ingress-контроллеры или операторы сертификатов обновляют статусы и аннотации.

Механизмы игнорирования:
1. **Структурированные правила `spec.ignore` (Flux v2.9+)**:
   ```yaml
   spec:
     ignore:
       - paths:
           - /spec/replicas
   ```
2. **Строковое поле `spec.ignore` (JSON Pointer / RFC 6901)**:
   ```yaml
   spec:
     ignore: |
       /spec/replicas
   ```

Настройка правил исключает бесконечные конфликты между контроллерами и предотвращает ложные алерты о дрейфе.

### Верификация источников (Source Integrity)

Для предотвращения supply-chain атак Flux поддерживает обязательную проверку подлинности манифестов:
- **SSH-подписи коммитов (v2.9+)**: верификация коммитов Git, подписанных SSH-ключами (`spec.verify.mode: HEAD`), а также классических GPG-подписей.
- **Верификация OCI-артефактов (Cosign)**: проверка криптографической подписи Sigstore/Cosign для контейнерных артефактов перед распаковкой манифестов.

### Нововведения версии v2.9.x (On-Premise / Bare-Metal)

GA-релиз v2.9.0 (июнь 2026), текущий патч — v2.9.4:
- **Система плагинов CLI (RFC-0013)**: CLI-расширения (`flux plugin install`) с независимым версионированием и digest-пиннингом (плагины Mirror для оффлайн-синхронизации, Schema для валидации CRD).
- **ArtifactGenerator API**: поддержка монорепозиториев в компоненте `source-watcher` — генерация артефактов из нескольких источников с изоляцией изменений по директориям.
- **Поддержка алгоритмов Age для SOPS**: квантовоустойчивые алгоритмы шифрования секретов в рабочем процессе GitOps.
- **Workload Identity для HashiCorp Vault и OpenBao**: бесшовная аутентификация контроллера через Kubernetes SA токен без долгоживущих паролей.
- **Изменение стратегии Helm post-render**: стратегия по умолчанию изменена с `nohooks` на `combined` (хуки чарта теперь участвуют в постобработке Kustomize, что соответствует стандартному поведению Helm).
- **OIDC-secured Webhook Receivers**: проверка токенов OIDC при вызове входящих вебхуков и CLI-команда `flux trigger receiver`.

---

## Практические сценарии и настройка

### Предварительные требования

Для развертывания Flux v2.9.x в частном кластере требуются:

| Компонент | Минимальная версия / Требование | Проверка |
| :--- | :--- | :--- |
| Kubernetes | 1.34, 1.35 или 1.36 (bare-metal, kubeadm, RKE2, Talos) | `kubectl version --short` |
| `flux` CLI | v2.9.4 | `flux --version` |
| `kubectl` | Совместимая с версией API кластера | `kubectl get nodes` |
| Git-сервер | Self-hosted GitLab, Forgejo, Gitea, GitHub или локальный Git по SSH/HTTPS | Доступ по сети с мастер-узлов |
| Права доступа | Администратор кластера (`cluster-admin`), deploy key или токен репозитория с правами read/write | Проверка прав SSH/API |

Установка CLI:

```bash
# Загрузка и установка бинарного файла flux
curl -s https://fluxcd.io/install.sh | sudo bash

# Проверка установленной версии
flux --version
# → flux version 2.9.4

# Предварительная проверка совместимости кластера
flux check --pre
# ► checking prerequisites
# ✔ Kubernetes 1.35.3 >=1.34.0-0
# ✔ prerequisites checks passed
```

---

### Сценарий 1: Первоначальная установка (Bootstrap через Generic Git / GitLab)

Процедура bootstrap генерирует манифесты компонентов Flux, коммитит их в Git-репозиторий и применяет в кластер:

```bash
# 1. Запуск bootstrap для generic Git-сервера по SSH (например, локальный GitLab / Forgejo)
flux bootstrap git \
  --url=ssh://git@git.internal.domain/infrastructure/fleet-infra.git \
  --branch=main \
  --path=./clusters/production \
  --private-key-file=/root/.ssh/id_ed25519_deploy \
  --components-extra=image-reflector-controller,image-automation-controller \
  --silent=false
# ► connecting to ssh://git@git.internal.domain/infrastructure/fleet-infra.git
# ► cloning branch "main"
# ► generating manifests
# ► applying manifests to the cluster
# ✔ source-controller: deployment ready
# ✔ kustomize-controller: deployment ready
# ✔ helm-controller: deployment ready
# ✔ notification-controller: deployment ready
# ✔ image-reflector-controller: deployment ready
# ✔ image-automation-controller: deployment ready
# ✔ bootstrap finished
```

Валидация состояния компонентов:

```bash
# Комплексная проверка здоровья GOTK
flux check
# ► checking components
# ✔ source-controller is healthy
# ✔ kustomize-controller is healthy
# ✔ helm-controller is healthy
# ✔ notification-controller is healthy
# ✔ image-reflector-controller is healthy
# ✔ image-automation-controller is healthy
# ✔ all components are healthy

# Проверка корневой Kustomization
flux get kustomizations -n flux-system
# → NAME         REVISION             SUSPENDED READY MESSAGE
# → flux-system  main@sha1:9a8b7c6d   False     True  Applied revision: main@sha1:9a8b7c6d
```

---

### Сценарий 2: Развертывание приложения через Kustomize

Создание пары ресурсов: источник манифестов (`GitRepository`) и контроллер применения (`Kustomization`).

Манифест источника (`gitrepository.yaml`):

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: fleet-infra
  namespace: flux-system
spec:
  interval: 1m
  url: ssh://git@git.internal.domain/infrastructure/fleet-infra.git
  ref:
    branch: main
  secretRef:
    name: flux-system-git-deploy-key
  timeout: 60s
```

Манифест применения (`kustomization.yaml`):

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: web-app-prod
  namespace: flux-system
spec:
  interval: 5m
  path: ./apps/production/web-app
  prune: true
  wait: true
  timeout: 3m
  sourceRef:
    kind: GitRepository
    name: fleet-infra
  healthChecks:
    - apiVersion: apps/v1
      kind: Deployment
      name: web-app
      namespace: apps
```

Применение и проверка статуса:

```bash
# Применение манифестов в кластер
kubectl apply -f gitrepository.yaml -f kustomization.yaml
# → gitrepository.source.toolkit.fluxcd.io/fleet-infra created
# → kustomization.kustomize.toolkit.fluxcd.io/web-app-prod created

# Проверка загрузки артефакта источником
flux get sources git -n flux-system
# → NAME         REVISION             SUSPENDED READY MESSAGE
# → fleet-infra  main@sha1:9a8b7c6d   False     True  stored artifact for revision 'main@sha1:9a8b7c6d'

# Проверка статуса применения
flux get kustomizations -n flux-system
# → NAME          REVISION             SUSPENDED READY MESSAGE
# → web-app-prod  main@sha1:9a8b7c6d   False     True  Applied revision: main@sha1:9a8b7c6d
```

---

### Сценарий 3: Развертывание Helm-релиза с автоматическим откатом

Управление релизом чарта из репозитория с настроенной политикой автоматического отката (remediation rollback):

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: bitnami-mirror
  namespace: flux-system
spec:
  interval: 1h
  url: https://charts.internal.domain/repository/bitnami
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: redis-cluster
  namespace: database
spec:
  interval: 15m
  timeout: 5m
  chart:
    spec:
      chart: redis
      version: ">=18.0.0 <19.0.0"
      sourceRef:
        kind: HelmRepository
        name: bitnami-mirror
        namespace: flux-system
  install:
    remediation:
      retries: 3
  upgrade:
    remediation:
      retries: 3
      strategy: rollback
  test:
    enable: true
  values:
    architecture: replication
    auth:
      existingSecret: redis-password
      existingSecretPasswordKey: password
    replica:
      replicaCount: 3
```

Проверка релиза:

```bash
flux get helmreleases -n database
# → NAME           REVISION SUSPENDED READY MESSAGE
# → redis-cluster  18.6.1   False     True  Helm upgrade succeeded
```

---

### Сценарий 4: Настройка мультитенантности (ServiceAccount Impersonation)

Изоляция привилегий тенанта `team-billing`:

1. Создание пространства имен, ServiceAccount и RoleBinding:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: team-billing
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: billing-reconciler
  namespace: team-billing
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: billing-reconciler-admin
  namespace: team-billing
subjects:
  - kind: ServiceAccount
    name: billing-reconciler
    namespace: team-billing
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: admin
```

2. Привязка аккаунта к `Kustomization`:

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: billing-services
  namespace: team-billing
spec:
  interval: 10m
  targetNamespace: team-billing
  serviceAccountName: billing-reconciler
  path: ./tenants/billing
  prune: true
  sourceRef:
    kind: GitRepository
    name: fleet-infra
    namespace: flux-system
```

Попытка манифестов тенанта развернуть объекты за пределами `team-billing` (например, `ClusterRole` или ресурсы в `default`) будет немедленно заблокирована API-сервером Kubernetes с ошибкой `Forbidden`.

---

### Сценарий 5: Использование OCI-репозиториев для доставки манифестов («Gitless GitOps»)

Публикация манифестов как OCI-артефакта в локальный реестр Harbor:

```bash
# 1. Сборка директории и пуш артефакта в Harbor
flux push artifact oci://harbor.internal.domain/gitops/manifests/auth-service:v1.4.2 \
  --path=./apps/production/auth-service \
  --source="ssh://git@git.internal.domain/apps/auth.git" \
  --revision="v1.4.2@sha1:$(git rev-parse HEAD)"
# ► pushing artifact to harbor.internal.domain/gitops/manifests/auth-service:v1.4.2
# ✔ artifact successfully pushed to harbor.internal.domain/gitops/manifests/auth-service:v1.4.2@sha256:d41d8cd98f00b204e9800998ecf8427e...
```

Манифест `OCIRepository` и `Kustomization` в кластере:

```yaml
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: OCIRepository
metadata:
  name: auth-service-manifests
  namespace: flux-system
spec:
  interval: 5m
  url: oci://harbor.internal.domain/gitops/manifests/auth-service
  ref:
    tag: v1.4.2
  secretRef:
    name: harbor-registry-credentials
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: auth-service
  namespace: flux-system
spec:
  interval: 10m
  path: ./
  prune: true
  sourceRef:
    kind: OCIRepository
    name: auth-service-manifests
```

Валидация OCI источника:

```bash
flux get sources oci -n flux-system
# → NAME                    REVISION                            SUSPENDED READY MESSAGE
# → auth-service-manifests  v1.4.2@sha256:d41d8cd98f00b204...   False     True  stored artifact for digest 'sha256:d41d8...'
```

---

### Сценарий 6: Шифрование секретов через SOPS и Age

Пошаговая настройка локального шифрования секретов без облачных KMS:

1. Генерация ключа Age и сохранение в кластере:

```bash
# Генерация ключевой пары
age-keygen -o age.key.txt
# → Public key: age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p

# Создание Secret в пространстве имен flux-system
kubectl create secret generic sops-age \
  --namespace flux-system \
  --from-file=age.agekey=age.key.txt
# → secret/sops-age created
```

2. Файл `.sops.yaml` в корне Git-репозитория:

```yaml
creation_rules:
  - path_regex: .*\.enc\.yaml$
    encrypted_regex: ^(data|stringData)$
    age: age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p
```

3. Шифрование секрета и коммит:

```bash
# Создание шаблона секрета
cat <<EOF > secret-database.enc.yaml
apiVersion: v1
kind: Secret
metadata:
  name: db-credentials
  namespace: apps
type: Opaque
stringData:
  DB_PASSWORD: "SuperSecretProductionPassword123!"
EOF

# Шифрование файла на месте
sops --encrypt --in-place secret-database.enc.yaml

# Проверка содержимого (пароль зашифрован, метаданные открыты)
grep "DB_PASSWORD" secret-database.enc.yaml
# → DB_PASSWORD: ENC[AES256_GCM,data:...,iv:...,tag:...]
```

4. Подключение расшифровки в `Kustomization`:

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: app-secrets
  namespace: flux-system
spec:
  interval: 10m
  path: ./apps/production/secrets
  prune: true
  sourceRef:
    kind: GitRepository
    name: fleet-infra
  decryption:
    provider: sops
    secretRef:
      name: sops-age
```

5. Валидация в кластере:

```bash
# Проверка расшифрованного секрета в целевом namespace
kubectl get secret db-credentials -n apps -o jsonpath='{.data.DB_PASSWORD}' | base64 -d
# → SuperSecretProductionPassword123!
```

---

### Сценарий 7: Автоматизация обновления тегов образов (Image Automation)

Автоматический мониторинг реестра контейнеров и коммит новых тегов в Git:

```yaml
apiVersion: image.toolkit.fluxcd.io/v1
kind: ImageRepository
metadata:
  name: backend-service
  namespace: flux-system
spec:
  interval: 5m
  image: harbor.internal.domain/apps/backend-service
  secretRef:
    name: harbor-registry-credentials
---
apiVersion: image.toolkit.fluxcd.io/v1
kind: ImagePolicy
metadata:
  name: backend-service-semver
  namespace: flux-system
spec:
  imageRepositoryRef:
    name: backend-service
  policy:
    semver:
      range: '>=1.2.0 <2.0.0'
---
apiVersion: image.toolkit.fluxcd.io/v1
kind: ImageUpdateAutomation
metadata:
  name: fleet-infra-automation
  namespace: flux-system
spec:
  interval: 15m
  sourceRef:
    kind: GitRepository
    name: fleet-infra
  git:
    checkout:
      ref:
        branch: main
    commit:
      author:
        name: flux-automation-bot
        email: fluxbot@internal.domain
      messageTemplate: 'chore(gitops): update {{ .Updated.Image }} to {{ .Updated.NewTag }}'
    push:
      branch: main
  update:
    path: ./apps/production
    strategy: setters
```

Маркер в целевом манифесте (`deployment.yaml`):

```yaml
spec:
  template:
    spec:
      containers:
        - name: backend
          image: harbor.internal.domain/apps/backend-service:1.2.4 # {"$imagepolicy": "flux-system:backend-service-semver"}
```

Контроллер `image-automation-controller` заменит `1.2.4` на последний тег, удовлетворяющий диапазону SemVer, и сделает `git push` в ветку `main`.

---

### Сценарий 8: Мгновенная синхронизация через входящие вебхуки (Notification Receiver)

Настройка мгновенной реакции на `git push` без ожидания интервала опроса `spec.interval`:

```yaml
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Receiver
metadata:
  name: gitlab-receiver
  namespace: flux-system
spec:
  type: gitlab
  interval: 1m
  secretRef:
    name: webhook-token-secret
  resources:
    - kind: GitRepository
      name: fleet-infra
```

Получение адреса webhook и тестирование:

```bash
# Извлечение сгенерированного URL вебхука
kubectl get receiver gitlab-receiver -n flux-system -o jsonpath='{.status.webhookPath}'
# → /hook/c4ca4238a0b923820dcc509a6f75849b

# Запуск триггера через CLI v2.9+
flux trigger receiver gitlab-receiver -n flux-system
# ► triggering receiver gitlab-receiver
# ✔ webhook successfully invoked
```

---

### Сценарий 9: Обновление Flux и миграция устаревших CRD

Порядок безопасного обновления минорной версии (до v2.9.4):

```bash
# 1. Проверка текущей установленной версии CLI
flux --version
# → flux version 2.9.4

# 2. Обновление манифестов в кластере и Git-репозитории
flux bootstrap git \
  --url=ssh://git@git.internal.domain/infrastructure/fleet-infra.git \
  --branch=main \
  --path=./clusters/production \
  --version=v2.9.4
# ► updating components to v2.9.4
# ✔ components updated in git and applied to cluster

# 3. Автоматическая миграция устаревших beta-версий API в репозитории
flux migrate
# ► migrating resources to stable API versions
# ✔ converted Kustomization, HelmRelease, and Notification resources in Git

# 4. Проверка здоровья кластера после апгрейда
flux check
# ✔ all components are healthy
```

---

### Сценарий 10: Аварийное восстановление кластера (Disaster Recovery)

Порядок восстановления инфраструктуры на новом «чистом» bare-metal кластере:

1. **Предварительные резервные копии (хранятся вне Git)**:
   - Приватный ключ Age (`age.key.txt`).
   - SSH Deploy key с правами доступа к Git-репозиторию.
   - Секреты учетных записей хранилищ и реестров (Harbor, Vault).

2. **Шаги восстановления**:

```bash
# Шаг 1: Проверка доступности нового пустого кластера
kubectl get nodes
# → Все мастер и воркер-ноды в статусе Ready

# Шаг 2: Создание пространства имен flux-system и загрузка ключа SOPS ДО bootstrap
kubectl create namespace flux-system
# → namespace/flux-system created

kubectl create secret generic sops-age -n flux-system \
  --from-file=age.agekey=/secure/backups/age.key.txt
# → secret/sops-age created

# Шаг 3: Повторный запуск команды bootstrap против существующего репозитория
flux bootstrap git \
  --url=ssh://git@git.internal.domain/infrastructure/fleet-infra.git \
  --branch=main \
  --path=./clusters/production \
  --private-key-file=/secure/backups/deploy_key
# ► components verified
# ► applying existing manifests from Git
# ✔ source-controller reconciled
# ✔ kustomization flux-system reconciled

# Шаг 4: Контроль каскадного восстановления всех объектов
flux get all -A --status-selector ready=False
# → пустой вывод свидетельствует об успешном переходе всех объектов в Ready=True

# Шаг 5: Проверка состояния подов приложений
kubectl get pods -A | grep -v "Running\|Completed"
# → пустой вывод (все приложения успешно подняты)
```

---

## Операции и команды

Справочник базовых команд администратора Flux:

| Операция | Команда | Описание |
| :--- | :--- | :--- |
| **Проверка здоровья** | `flux check` | Проверка статуса подов, деплойментов и контроллеров Flux. |
| **Сводка ресурсов** | `flux get all -A` | Kustomizations, HelmReleases и Sources со статусом синхронизации. |
| **Список с ошибками** | `flux get all -A --status-selector ready=False` | Поиск всех сбойных источников, kustomization и helm-релизов. |
| **Принудительная сверка** | `flux reconcile kustomization <name> --with-source` | Немедленный запуск сверки источника и применения манифестов. |
| **Сверка HelmRelease** | `flux reconcile helmrelease <name> --with-source` | Немедленный цикл Helm install/upgrade с перечитыванием источника. |
| **Перечитать git-источник** | `flux reconcile source git <name>` | Немедленная загрузка последнего коммита без касания зависимых кастомизаций. |
| **Заморозка синхронизации** | `flux suspend kustomization <name>` | Временная остановка применения изменений и детекции дрейфа. |
| **Возобновление** | `flux resume kustomization <name>` | Возобновление автоматического цикла сверки. |
| **Трассировка объекта** | `flux trace <kind>/<name>` | Вывод цепочки: источник → коммит → статус применения. |
| **Дерево управляемых объектов** | `flux tree kustomization <name>` | Все объекты, которыми владеет кастомизация, включая вложенные. |
| **Хронология событий** | `flux events --for Kustomization/<name>` | История событий согласования объекта для диагностики дрейфа и сбоев. |
| **Просмотр логов** | `flux logs --level=error --tail=100` | Вывод последних 100 строк ошибок всех контроллеров. |
| **Локальная сборка** | `flux build kustomization <name> --path ./path` | Рендеринг манифестов локально без подключения к кластеру. |
| **Сравнение дрейфа** | `flux diff kustomization <name> --path ./path` | Сравнение локальных манифестов с текущим состоянием в кластере. |
| **Автоматизация образов** | `flux get images all -A` | Все ImageRepository, ImagePolicy и ImageUpdateAutomation по кластеру. |
| **Экспорт конфига** | `flux export kustomization --all > clusters/cluster.yaml` | Бэкап текущих ресурсов Flux как YAML для бутстрапа другого кластера. |
| **Удаление ресурса** | `flux delete kustomization <name>` | Удаление Kustomization или HelmRelease из кластера. |
| **Удаление компонентов** | `flux uninstall --namespace=flux-system --crds` | Полное удаление контроллеров и CRD (нагрузки приложений сохраняются). |

Создание ресурсов через CLI (альтернатива манифестам в Git):

```bash
# Источники: Git, Helm-репозиторий, OCI-артефакт по диапазону semver
flux create source git <name> --url=https://github.com/org/repo --branch=main -n flux-system
flux create source helm <name> --url=https://charts.example.com -n flux-system
flux create source oci <name> --url=oci://reg/repo --tag-semver='>=1.0.0' --interval=5m

# HelmRelease через Flux
flux create helmrelease <name> --source=HelmRepository/<repo> --chart=<chart> --chart-version='>=1.0.0' -n <ns>

# Кастомизация с порядком применения: ждёт Ready кастомизации infra
flux create kustomization app --source=GitRepository/<name> --path=./app --depends-on=infra --prune=true --interval=10m

# Автообновление тегов образов: политика отбора + автоматизация коммитов в Git
flux create image policy <name> --image-ref=<image-repo> --select-semver='>=1.0.0' -n flux-system
flux create image update <name> --git-repo-ref=<repo> --git-repo-path=./deploy --checkout-branch=main --push-branch=main -n flux-system

# Бутстрап с GitHub (вместо bootstrap git)
flux bootstrap github --owner=<org> --repository=<repo> --branch=main --path=clusters/production --personal

# Оповещения: provider + alert; входящий webhook для мгновенной реконсиляции — receiver
flux create provider slack --type slack --secret-ref webhook
flux create alert prod --provider-ref slack --event-source 'Kustomization/*' --event-severity info
flux create receiver github --type github --event github:push --secret-ref webhook-token --resource GitRepository/<name>
```

---

## Диагностика и устранение неполадок

### Порядок расследования инцидентов

1. Определение сбойного объекта:
   ```bash
   flux get all -A --status-selector ready=False
   ```
2. Трассировка цепочки доставки:
   ```bash
   flux trace kustomization <name> -n <ns>
   ```
3. Детальный осмотр условий и событий ресурса:
   ```bash
   kubectl describe kustomization <name> -n <ns>
   # или
   kubectl describe helmrelease <name> -n <ns>
   ```
4. Изучение логов целевого контроллера:
   ```bash
   flux logs --kind=kustomize-controller --flux-namespace=flux-system --level=error
   ```

### Матрица типовых неисправностей

| Симптом / Ошибка | Первопричина | Метод диагностики | Решение |
| :--- | :--- | :--- | :--- |
| `authentication required` / `key verification failed` у `source-controller` | Истек deploy key, неверный secretRef, изменился fingerprint SSH-сервера | `kubectl describe gitrepository <name> -n flux-system` | Обновить Secret с SSH-ключом: `flux create secret git ...`; обновить known_hosts в ключе. |
| `OOMKilled` подов `kustomize-controller` | Нехватка оперативной памяти при сборке больших манифестов с десятками CRD | `kubectl get pods -n flux-system -l app=kustomize-controller` (смотрим RestartCount и Terminated: OOMKilled) | Увеличить memory limits в деплойменте контроллера (до 1–2Gi); разбить монолитную Kustomization на небольшие части. |
| `Health check failed after timeout` | Pod не переходит в статус Ready (CrashLoopBackOff, сбой Readiness Probe) | `kubectl get pods -n <app-namespace>`; `kubectl describe pod <pod-name>` | Устранить причину падения приложения; временно увеличить `spec.timeout` в манифесте `Kustomization`. |
| `Helm upgrade failed: another operation is in progress` | Предыдущий процесс Helm завис в статусе `pending-upgrade` из-за рестарта контроллера | `helm history <release> -n <ns>` | Выполнить ручную разблокировку: `flux reconcile helmrelease <name> --reset` или удалить зависший secret релиза. |
| `dependency cycle detected` | В графе `dependsOn` обнаружена замкнутая циклическая ссылка (A → B → A) | `flux get kustomizations -n flux-system` (поиск циклов в поле Depends On) | Перестроить зависимости в виде строгого DAG без взаимных ссылок. |
| Изменения `HPA` постоянно затираются `kustomize-controller` | Поле `spec.replicas` присутствует в Git и перезаписывает динамические значения HPA | `kubectl get events -n <ns>` (постоянный ReconciliationSucceeded с правкой ReplicaSet) | Добавить `/spec/replicas` в `spec.ignore` соответствующей `Kustomization`. |
| Ошибка расшифровки SOPS `failed to decrypt: no matching key` | В кластере отсутствует секрет `sops-age` или в нем лежит не тот приватный ключ | `kubectl get secret sops-age -n flux-system`; проверка логов `kustomize-controller` | Сверить публичный ключ из файла `.sops.yaml` с приватным ключом внутри Secret `sops-age`. |
| `server-side apply failed: conflict on field...` | Поле захвачено другим fieldManager (ручной `kubectl apply` или другой контроллер) | `kubectl describe <resource> -n <ns>` | Добавить флаг `force: true` в `spec` Kustomization либо передать владение полем через SSA. |

---

## Лучшие практики

### Архитектура репозиториев (Fleet Topology)

- **Паттерн «Инфраструктурный монорепозиторий»**:
  Рекомендуется организация репозитория по схеме `clusters/`, `infrastructure/` и `apps/`:
  - `clusters/`: точки входа для конкретных кластеров (`production`, `staging`), содержащие корневую `flux-system` Kustomization.
  - `infrastructure/`: базовые системные сервисы (Ingress-контроллеры, cert-manager, мониторинг, CNI).
  - `apps/`: прикладные сервисы компании.
- **Разделение Base и Overlays**: использование нативных оверлеев Kustomize для изоляции специфичных настроек окружений (dev/prod) без дублирования манифестов.

### Безопасность и отказоустойчивость

- **Отказ от ручных изменений (GitOps Enforcement)**: исключить выдачу прямых прав на запись (`write`) в кластер обычным инженерам. Любое изменение должно проходить через Pull Request в Git.
- **Обязательный флаг `prune: true`**: предотвращает появление ресурсов-сирот при удалении манифестов из репозитория.
- **Метрики готовности (`healthChecks`)**: не завершать реконсиляцию без проверки работоспособности подов, чтобы блокировать развертывание дефектных версий и останавливать цепочки `dependsOn`.
- **Пиннинг версий чартов и образов**: избегать плавающих тегов `latest`; для Helm использовать строгие SemVer-ограничения (`1.2.x`), для OCI — неизменяемые digest-хэши.
- **Ротация секретов**: регулярная смена ключей Age и использование `sops --rotate-roles` для перешифрования файлов в Git.

### Оптимизация производительности контроллеров

- **Тюнинг интервалов сверки**: для редко меняющихся компонентов (CRD, инфраструктура) устанавливать интервалы `1h`–`2h`, полагаясь на входящие вебхуки для оперативной доставки.
- **Параллелизм (`--concurrent`)**: в кластерах с тысячами объектов поднимать число воркеров контроллеров (`--concurrent=10`–`20`), синхронно увеличивая лимиты CPU/Memory.
- **Мониторинг очередей**: настраивать алертинг в Prometheus по метрике `gotk_reconcile_condition{status="False"}` и отслеживать глубину workqueue контроллеров.

### Очистка окружения (Safe Cleanup)

Для безопасного вывода Flux из эксплуатации или переустановки:

```bash
# Мягкое удаление контроллеров (рабочие нагрузки приложений ОСТАЮТСЯ в кластере):
flux uninstall --namespace=flux-system --keep-namespace

# Полное удаление контроллеров и CRD:
flux uninstall --namespace=flux-system --crds
# ► uninstalling flux
# ✔ uninstall finished
```

> [!IMPORTANT]
> Удаление Flux не уничтожает рабочие нагрузки приложений, развернутые через `Kustomization` или `HelmRelease`. При необходимости полного демонтажа удалите манифесты приложений из Git-репозитория до деинсталляции Flux либо удалите неймспейсы вручную через `kubectl delete ns <app-namespace>`.

---

## Вопросы для собеседования

### 1. В чем фундаментальное отличие архитектуры Flux от Argo CD с точки зрения надежности при сбоях сети?
Flux спроектирован по принципу «pull-per-cluster» без выделенного централизованного управляющего сервера. Контроллеры каждого кластера автономно забирают манифесты из Git/OCI и выполняют цикл сверки локально. При полной недоступности внешнего Git-сервера кластер под управлением Flux продолжает штатно функционировать на последнем сохраненном артефакте и восстанавливает дрейф ресурсов на узлах. Argo CD при архитектуре с центральным сервером управления теряет возможность синхронизировать целевые кластеры при обрыве связи между сервером и агентом.

### 2. Что происходит внутри Flux при выполнении команды `flux suspend kustomization`?
Команда выставляет флаг `spec.suspend: true` в манифесте ресурса `Kustomization`. Контроллер `kustomize-controller` полностью прекращает обработку данного объекта: не применяются новые коммиты из Git и, что критично, **отключается коррекция дрейфа** — любые ручные правки инженеров в кластере сохраняются. Заморозка нарушает парадигму GitOps как SSoT, поэтому список suspended-объектов должен регулярно мониториться через `flux get all --status-selector ready=False`.

### 3. Как во Flux реализована защита от эскалации привилегий в мультитенантных кластерах?
Через механизм ServiceAccount Impersonation. Администратор платформы задает в манифесте тенанта `spec.serviceAccountName`. Контроллер Flux переключает контекст выполнения на этот ServiceAccount и выполняет вызовы Kubernetes API от его имени. Если манифест в Git пытается создать `ClusterRoleBinding` или получить доступ к чужому namespace, API-сервер возвращает ошибку `Forbidden`. Дополнительно режим lockdown запрещает ссылки на секреты из других namespace (`--no-cross-namespace-refs`).

### 4. Зачем использовать `OCIRepository` вместо `GitRepository` для доставки манифестов?
OCI-реестры (Harbor) обеспечивают неизменяемость артефактов через digest pinning, криптографическую верификацию подписей (Cosign), высокую скорость скачивания без накладных расходов на git clone, а также единый транспорт и механизм зеркалирования для образов, чартов и конфигураций (особенно в закрытых air-gapped контурах).

### 5. Как во Flux v2.9+ решается конфликт между `kustomize-controller` и `HPA` за поле `spec.replicas`?
С помощью Server-Side Apply и правил `spec.ignore`. В манифесте `Kustomization` объявляется путь `/spec/replicas`. Контроллер исключает это поле из расчета дрейфа и сверки, передавая полноправное владение значением реплик контроллеру HPA, что устраняет флаппинг подов.

---

## Дополнительная информация

**Связанные документы в базе знаний:**
- [Сравнение с ArgoCD](./argo_vs_flux_manifests.md) — детальное архитектурное сравнение и сопоставление манифестов.
- [Организация Flux CD monorepo: кейс](./Concepts/flux_monorepo_organization.md) — структура монорепозитория `clusters/` + `components/`, оверлеи и конвенции.
- [Управление секретами в GitOps](./secrets_encryption.md) — руководство по SOPS, age и Sealed Secrets.
- [GitOps: Уведомления и алертинг](./gitops_notifications.md) — настройка Provider, Alert и Receiver во Flux.
- [Обзор методологии GitOps](./GitOps_overview.md) — принципы OpenGitOps, сравнение pull/push моделей.
- [Сквозной пример GitOps-пайплайна](./gitops_pipeline_example.md) — интеграция CI/CD конвейера от коммита до продакшена.
- [Интеграция Kustomize в CD-пайплайны](../Kubernetes/ToolsUtilities/kustomize/kustomize_cd_integration.md) — продвинутые техники Kustomize в связке с GitOps.
- [GitOps и автомасштабирование](../Kubernetes/Autoscaling/gitops_autoscaling.md) — бесконфликтная настройка HPA и KEDA в GitOps.

**Официальные ресурсы:**
- [Официальная документация Flux CD](https://fluxcd.io/flux/) — справочники API, архитектурные гайды и CLI reference.
- [Репозиторий релизов fluxcd/flux2](https://github.com/fluxcd/flux2/releases) — changelog, security advisories и история релизов.
- [Спецификация OpenGitOps Principles](https://opengitops.dev/) — стандарты и принципы декларативного управления конфигурациями.
