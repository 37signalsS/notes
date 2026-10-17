# Сравнение Argo CD и Flux: архитектура, манифесты и эксплуатация

**Актуально для:** Argo CD v3.5+ / Flux v2.9.x (Kubernetes 1.34–1.36; on-premise / bare-metal)

**Argo CD** и **Flux** — два ведущих GitOps-инструмента в экосистеме CNCF (оба имеют статус Graduated), реализующие непрерывную доставку манифестов в Kubernetes на базе противоположных архитектурных парадигм. Argo CD ориентирован на централизованное управление (Hub-and-Spoke), развитый графический интерфейс и комплексную абстракцию проектов. Flux следует классическому принципу Unix-way: он состоит из независимых микроконтроллеров (GitOps Toolkit), управляется исключительно через нативные примитивы Kubernetes API и ориентирован на децентрализованное развертывание в каждом кластере.

---

## Определения

- **Argo CD**: Декларативный инструмент непрерывной доставки (CD) по методологии GitOps, выполненный в виде монолитной контрольной плоскости с собственным API-сервером, Web UI, кэшем состояний в Redis и ролевой моделью доступа (RBAC).
- **Flux**: Модульный набор независимых контроллеров (GitOps Toolkit), взаимодействующих через Kubernetes API. Не имеет собственного API-сервера или обязательного Web UI, функционирует как «чистый» оператор Kubernetes.
- **GitOps Toolkit (GOTK)**: Композиция специализированных контроллеров Flux (`source-controller`, `kustomize-controller`, `helm-controller`, `notification-controller`, `image-reflector-controller`, `image-automation-controller`), взаимодействующих через артефакты в локальном хранилище и статусы CRD.
- **Application**: Основной кастомный ресурс Argo CD (`argoproj.io/v1alpha1`), связывающий в единой декларации источник манифестов (Git, Helm, OCI), целевой кластер, пространство имен и политики синхронизации.
- **AppProject**: Кастомный ресурс Argo CD, задающий логический периметр изоляции для команд: список доверенных репозиториев, разрешенных кластеров/неймспейсов, белые/черные списки видов ресурсов (Kinds) и локальные роли с OIDC-маппингом.
- **Kustomization (Flux)**: Кастомный ресурс Flux (`kustomize.toolkit.fluxcd.io/v1`), определяющий конвейер сборки и применения манифестов из артефакта источника с поддержкой Server-Side Apply, валидации здоровья (Health Checks), подстановки переменных и расшифровки секретов.
- **HelmRelease**: Кастомный ресурс Flux (`helm.toolkit.fluxcd.io/v2`), декларативно описывающий жизненный цикл Helm-релиза: источник чарта, semver-диапазоны версий, переопределения values, тесты и автоматический откат при сбое.
- **Server-Side Apply (SSA)**: Механизм Kubernetes API для отслеживания владения отдельными полями объектов через структуры `managedFields`. Предотвращает конфликты между несколькими контроллерами и является стандартом применения манифестов в обоих инструментах.
- **Детекция и коррекция дрейфа (Drift Detection & Correction)**: Процесс выявления несоответствия между эталонным состоянием в Git/OCI и фактическим состоянием объектов в etcd. Коррекция восстанавливает эталонную конфигурацию при несанкционированных ручных изменениях (`kubectl edit`).
- **Resource Tracking**: Механизм Argo CD для однозначной идентификации ресурсов, порожденных конкретным `Application`, с помощью аннотаций (`argocd.argoproj.io/tracking-id`) или меток (`app.kubernetes.io/instance`).
- **ServiceAccount Impersonation**: Механизм Kubernetes API, позволяющий контроллеру выполнять операции от имени другого сервисного аккаунта с ограниченными правами. Базовый метод изоляции тенантов во Flux.
- **OCI-артефакт (OCI Artifact)**: Неизменяемый образ спецификации Open Container Initiative, используемый для упаковки и распространения манифестов Kubernetes или Helm-чартов через реестр контейнеров (например, Harbor) вместо прямого обращения к Git.

---

## Архитектура и основные концепции

### 1. Архитектурная топология и потребление ресурсов

| Характеристика | Argo CD (v3.5+) | Flux (v2.9.x) |
| :--- | :--- | :--- |
| **Архитектурный стиль** | Монолитная плоскость управления (Application Controller, Repo Server, API Server, Dex, Redis) | Модульный набор микроконтроллеров (GitOps Toolkit на контроллерах `controller-runtime`) |
| **Топология развертывания** | Hub-and-Spoke (один центральный кластер управляет сотнями целевых) либо Standalone | In-Cluster Agent (независимый агент в каждом кластере, децентрализованная топология) |
| **Потребление памяти (RAM)** | Высокое: кэширует в Redis полное дерево ресурсов всех управляемых кластеров для UI и diff | Низкое: контроллеры кэшируют только свои CRD и сжатые tar-артефакты в ephemeral storage |
| **Потребление CPU** | Скачкообразное: частые пересборки шаблонов на `repo-server` при массовых вебхуках | Равномерное: конвейер разбит на независимые воркеры (`source` скачивает, `kustomize` применяет) |
| **Сетевые требования** | Требует прямого доступа от Hub-кластера к API-серверам всех управляемых кластеров | Требует только исходящего доступа из кластера к Git-серверу и OCI-реестру (без входящих портов) |
| **Шардирование** | Шардирование `argocd-application-controller` по алгоритму round-robin между репликами | Шардирование реконсиляции через контроллер Flux Operator (`FluxInstance`) или раздельные инстансы |
| **Хранилище состояния** | Redis (кэш манифестов, сессий, токенов и дерева ресурсов) | etcd кластера (исключительно через CRD и аннотации объектов) |

```
ARGO CD АРХИТЕКТУРА (Hub-and-Spoke):
+---------------------------------------------------------------------------------+
| Hub-кластер                                                                     |
|  [Web UI / CLI] ---> [argocd-server] ---> [Redis Cache]                         |
|                             |                   ^                               |
|                             v                   |                               |
|                     [argocd-repo-server] <------+                               |
|                             |                                                   |
|                             v                                                   |
|               [application-controller]                                          |
|                    /        |        \                                          |
+-------------------/---------|---------\-----------------------------------------+
                   /          |          \  (Прямой сетевой доступ к k8s API)
                  v           v           v
          [Кластер Dev]  [Кластер Stage]  [Кластер Prod]

FLUX АРХИТЕКТУРА (In-Cluster Agent, Unix-way):
+---------------------------------------------------------------------------------+
| Локальный кластер (Dev / Stage / Prod)                                          |
|                                                                                 |
|   [Git / OCI Репозиторий]                                                       |
|             |                                                                   |
|             v (pull артефактов)                                                 |
|     [source-controller] -----> локальный tar-архив (/data)                      |
|                                         |                                       |
|                  +----------------------+----------------------+                |
|                  |                                             |                |
|                  v                                             v                |
|        [kustomize-controller]                        [helm-controller]          |
|                  | (Server-Side Apply)                         | (Helm SDK)     |
|                  +----------------------+----------------------+                |
|                                         |                                       |
|                                         v                                       |
|                                 [kube-apiserver]                                |
+---------------------------------------------------------------------------------+
```

### 2. Модель конфигурации и цикл сверки

- **Argo CD: Подход «Все в одном» (Application)**. Все параметры развертывания сосредоточены в одном объекте `Application`. Контроллер регулярно (по умолчанию каждые 3 минуты) или по входящему вебхуку обращается к `repo-server`, который выполняет `git clone` / `git fetch`, рендерит манифесты (через Kustomize, Helm или CMP-плагин) и возвращает готовый список объектов. Контроллер сравнивает их с состоянием в etcd целевого кластера и формирует статус синхронизации.
- **Flux: Разделение ответственности (Source + Reconciler)**. Развертывание разделено на два независимых этапа:
  1. `source-controller` периодически проверяет Git-репозиторий или OCI-реестр (`GitRepository`, `OCIRepository`). При обнаружении нового коммита он упаковывает исходники в неизменяемый tar-архив, сохраняет его во внутреннем веб-хранилище и выставляет статус с хэшем артефакта.
  2. `kustomize-controller` или `helm-controller` подписывается на событие изменения источника (`sourceRef`), скачивает сжатый архив по внутренней сети кластера, собирает манифесты и применяет их в API-сервер.

Это разделение позволяет:
- Опрашивать Git-репозиторий один раз для десятков микросервисов, разделяя пути (`path`) в разных `Kustomization`.
- Настраивать независимые интервалы: опрос источника раз в 10 минут, реконсиляция состояния в кластере — раз в 1 час.

### 3. Механика обнаружения дрейфа и самовосстановления

Разница в обработке несанкционированных ручных правок в кластере (`kubectl edit`, `kubectl scale`) является фундаментальной:

1. **Argo CD: Разделение статуса и коррекции**.
   - По умолчанию Argo CD **только обнаруживает** дрейф: статус переходит в `OutOfSync`, в UI подсвечиваются измененные поля, но объекты в кластере не перезаписываются.
   - Для принудительного отката ручных правок необходимо явно активировать флаг `syncPolicy.automated.selfHeal: true`. При его наличии контроллер запускает внеочередную синхронизацию и возвращает эталонное состояние.
   - Игнорирование полей (например, `spec.replicas` при использовании HPA) настраивается через блок `ignoreDifferences` в манифесте `Application` или глобально в `argocd-cm`.
2. **Flux: Непрерывная принудительная коррекция (Continuous Reconciliation)**.
   - Во Flux коррекция дрейфа — это неотъемлемая часть каждого цикла реконсиляции. `kustomize-controller` выполняет Server-Side Apply каждые `spec.interval` (или при получении события).
   - Любые ручные правки в кластере перезаписываются эталонными значениями из Git при следующем цикле.
   - Для сосуществования с внешними операторами (HPA, cert-manager) во Flux v2.9+ используются правила `spec.ignore` и `DriftIgnoreRules`, где явно объявляются пути JSONPointer или менеджеры полей, которые контроллер обязан пропускать.

### 4. Безопасность и мультитенантность

- **Argo CD: Прикладная изоляция через AppProject**.
  - Argo CD предоставляет собственную абстракцию мультитенантности `AppProject`. Проект изолирует команды на уровне Argo CD: какие Git-репозитории разрешено использовать, в какие кластеры и неймспейсы разрешен деплой, какие ресурсы разрешено/запрещено создавать (например, запрет создания `ClusterRoleBinding` или правки `ResourceQuota`).
  - Встроенный механизм RBAC позволяет интегрироваться с корпоративными OIDC/SAML провайдерами (Keycloak, GitLab) и выдавать гранулярные права на просмотр, ручную синхронизацию или удаление приложений отдельным группам пользователей.
- **Flux: Нативная изоляция через Kubernetes RBAC и Impersonation**.
  - Flux не создает дополнительных слоев авторизации. Граница изоляции тенанта формируется средствами самого Kubernetes API.
  - Каждая `Kustomization` и `HelmRelease` может содержать поле `spec.serviceAccountName`. При применении манифестов `kustomize-controller` выполняет запрос с имперсонацией (`impersonate`) указанного ServiceAccount.
  - Если манифест разработчика попытается создать ресурс в чужом неймспейсе или запросить несанкционированные привилегии, API-сервер Kubernetes отклонит запрос с кодом `403 Forbidden`.

### 5. Управление секретами в контуре

Хранение открытых паролей и токенов в Git недопустимо. Оба инструмента решают эту задачу в on-premise инфраструктуре без применения облачных сервисов:

- **Flux (Нативная поддержка Mozilla SOPS)**: `kustomize-controller` содержит встроенную библиотеку расшифровки SOPS. Зашифрованные файлы (с использованием асимметричных ключей `age` или приватного экземпляра HashiCorp Vault) коммитятся в Git в зашифрованном виде. Применение манифестов происходит в памяти контроллера — расшифрованные данные никогда не сохраняются на диск.
- **Argo CD (Внешние операторы или CMP-плагины)**: В базовой поставке Argo CD не умеет расшифровывать SOPS нативно. Типовые архитектурные решения:
  1. Использование **External Secrets Operator (ESO)**: в Git хранятся только ссылки `ExternalSecret`, а оператор забирает секреты из корпоративного HashiCorp Vault. Это эталонный паттерн для SRE.
  2. Использование Sidecar-плагина KSOPS на `argocd-repo-server`: манифесты расшифровываются при сборке перед отправкой в Application Controller.

### 6. Отслеживание ресурсов и Server-Side Apply

Для удаления устаревших ресурсов (`pruning`) контроллер должен точно знать, какие объекты в кластере принадлежат конкретному приложению:

- **Argo CD**: Применяет трекинг ресурсов. Метод по умолчанию — аннотация `argocd.argoproj.io/tracking-id: <app-name>:<group>/<kind>:<namespace>/<name>`. Дополнительно поддерживается маркировка меткой `app.kubernetes.io/instance`. В версии v3.5+ Server-Side Apply включен по умолчанию, что позволяет регистрировать менеджер полей `argocd-controller` в `metadata.managedFields`.
- **Flux**: Полностью опирается на Server-Side Apply Kubernetes API. При применении манифестов `kustomize-controller` регистрируется как field manager (по умолчанию `kustomize-controller`). Для отслеживания состава набора ресурсов контроллер сохраняет список примененных GVK (Group/Version/Kind) и имен в статусе `Kustomization` в виде инвентаря (`spec.inventory`). Ресурсы, пропавшие из инвентаря в новой ревизии, немедленно удаляются (если включен `prune: true`).

---

## Практические сценарии

### Предварительные требования

Для воспроизведения сценариев в тестовом on-premise контуре необходимы:

1. Кластер Kubernetes версии 1.34–1.36 с поддержкой RBAC и Server-Side Apply.
2. Локальный или корпоративный Git-сервер (GitLab, Gitea) с доступом по SSH/HTTPS.
3. Локальный OCI-реестр (Harbor) для хранения артефактов и Helm-чартов.
4. Установленные утилиты администрирования:
   - `kubectl` v1.34+
   - `argocd` CLI v3.5+
   - `flux` CLI v2.9+
   - `sops` v3.9+ и `age-keygen`

Проверка готовности среды:

```bash
# Проверка версии Kubernetes API
kubectl version --short
# → Client Version: v1.35.0
# → Server Version: v1.35.0

# Проверка готовности кластера к установке Flux
flux check --pre
# → ► checking prerequisites
# → ✔ Kubernetes 1.35.0 >=1.34.0
# → ✔ prerequisites checks passed
```

---

### Сценарий 1: Первичная установка и bootstrap инструментов

Различие в процессе установки иллюстрирует философию платформ: Flux устанавливает сам себя через коммит манифестов в Git, а Argo CD развертывается как классический инфраструктурный сервис через Helm.

#### Вариант А: Bootstrap Flux (самоуправление через Git)

Команда `flux bootstrap` подключается к Git-серверу, генерирует SSH-ключ развертывания (deploy key), клонирует репозиторий, генерирует манифесты контроллеров, коммитит их в ветку и запускает первичную синхронизацию:

```bash
flux bootstrap git \
  --url=ssh://git@git.internal.corp:2222/infra/fleet-gitops.git \
  --branch=main \
  --path=clusters/production \
  --components-extra=image-reflector-controller,image-automation-controller \
  --read-write-key
# → ► connecting to ssh://git@git.internal.corp:2222/infra/fleet-gitops.git
# → ✔ cloned repository
# → ✔ generated manifests
# → ✔ committed and pushed components manifests
# → ✔ deployed components to flux-system
# → ✔ verified components health
# → ✔ bootstrap finished
```

После выполнения команды конфигурация самого Flux зафиксирована в Git по пути `clusters/production/flux-system/`. Любые изменения (обновление версии, добавление флагов контроллеров) выполняются стандартным Git-коммитом.

#### Вариант Б: Установка Argo CD (через Helm на on-premise кластер)

Argo CD устанавливается централизованно через Helm-чарт с тюнингом под on-premise инфраструктуру (включение Server-Side Apply, отключение открытых портов наружу, выпуск сертификатов через cert-manager):

```bash
# Добавление официального репозитория
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

# Установка с кастомными параметрами высокой доступности (HA)
helm upgrade --install argocd argo/argo-cd \
  --namespace argocd \
  --create-namespace \
  --version 7.8.2 \
  --set server.extraArgs="{--insecure}" \
  --set configs.params."server\.insecure"=true \
  --set configs.cm."timeout\.reconciliation"="180s" \
  --set redis-ha.enabled=true \
  --set controller.replicas=2
# → Release "argocd" has been upgraded. Happy Helming!
# → STATUS: deployed
```

Проверка состояния компонентов:

```bash
kubectl get pods -n argocd -l app.kubernetes.io/part-of=argocd
# → NAME                                             READY   STATUS    RESTARTS   AGE
# → argocd-application-controller-0                  1/1     Running   0          2m
# → argocd-application-controller-1                  1/1     Running   0          2m
# → argocd-repo-server-6789b9d-abcd1                 1/1     Running   0          2m
# → argocd-server-54d9c79f8-efgh2                    1/1     Running   0          2m
# → argocd-redis-ha-server-0                         3/3     Running   0          2m
```

---

### Сценарий 2: Развертывание приложения через Kustomize

#### Подход Argo CD: Единый манифест Application

Манифест объединяет определение источника, оверлея Kustomize, целевого кластера, политик автосинхронизации и включения Server-Side Apply:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: payment-service
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://git.internal.corp/apps/payment-service.git
    targetRevision: main
    path: deploy/overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: payments
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
      - ApplyOutOfSyncOnly=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

Проверка состояния и запуск синхронизации:

```bash
argocd app sync payment-service --prune
# → TIMESTAMP                  GROUP        KIND   NAMESPACE                  NAME    STATUS    HEALTH        HOOK  MESSAGE
# → 2026-10-13T17:15:00+03:00  apps   Deployment    payments       payment-service    Synced   Healthy              deployment.apps/payment-service reconciled
# → 2026-10-13T17:15:00+03:00                 Service    payments       payment-service    Synced   Healthy              service/payment-service reconciled

argocd app get payment-service
# → Name:               argocd/payment-service
# → Project:            default
# → Server:             https://kubernetes.default.svc
# → Namespace:          payments
# → URL:                https://argocd.internal.corp/applications/payment-service
# → Repo:               https://git.internal.corp/apps/payment-service.git
# → Target:             main
# → Path:               deploy/overlays/production
# → Sync Window:        Sync Allowed
# → Sync Status:        Synced to main (a1b2c3d)
# → Health Status:      Healthy
```

#### Подход Flux: Композиция GitRepository и Kustomization

Разделение на получение артефакта и его реконсиляцию через Kustomize с привязкой к сервисному аккаунту:

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: payment-repo
  namespace: flux-system
spec:
  interval: 5m
  url: https://git.internal.corp/apps/payment-service.git
  ref:
    branch: main
  secretRef:
    name: internal-git-credentials
  timeout: 30s
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: payment-service
  namespace: flux-system
spec:
  targetNamespace: payments
  serviceAccountName: payments-reconciler
  interval: 30m
  retryInterval: 2m
  timeout: 5m
  prune: true
  wait: true
  sourceRef:
    kind: GitRepository
    name: payment-repo
  path: ./deploy/overlays/production
  force: false
```

Проверка состояния через CLI `flux`:

```bash
flux get sources git payment-repo
# → NAME         REVISION            SUSPENDED  READY  MESSAGE
# → payment-repo main@sha1:a1b2c3d   False      True   stored artifact for revision 'main@sha1:a1b2c3d'

flux get kustomizations payment-service
# → NAME             REVISION            SUSPENDED  READY  MESSAGE
# → payment-service  main@sha1:a1b2c3d   False      True   Applied revision: main@sha1:a1b2c3d
```

---

### Сценарий 3: Развертывание Helm-приложения

#### Подход Argo CD: Рендеринг чарта внутри Application

В Argo CD Helm-чарт выкачивается `repo-server`, шаблонизируется на стороне сервера (`helm template`) и применяется в кластер как набор плоских манифестов Kubernetes.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: ingress-nginx
  namespace: argocd
spec:
  project: default
  source:
    repoURL: oci://harbor.internal.corp/charts
    chart: ingress-nginx
    targetRevision: 4.11.2
    helm:
      releaseName: ingress-nginx
      valuesObject:
        controller:
          replicaCount: 3
          metrics:
            enabled: true
            serviceMonitor:
              enabled: true
  destination:
    server: https://kubernetes.default.svc
    namespace: ingress-nginx
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
```

#### Подход Flux: Нативный жизненный цикл через HelmRepository и HelmRelease

В отличие от Argo CD, Flux использует официальный Go SDK Helm внутри `helm-controller`. Это означает создание реальных записей Helm Release в secrets кластера, поддержку Helm lifecycle hooks, тестов (`helm test`) и автоматического отката (`rollback`):

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: internal-harbor
  namespace: flux-system
spec:
  type: oci
  url: oci://harbor.internal.corp/charts
  interval: 1h
  secretRef:
    name: harbor-robot-creds
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: ingress-nginx
  namespace: flux-system
spec:
  interval: 30m
  targetNamespace: ingress-nginx
  chartRef:
    kind: HelmRepository
    name: internal-harbor
    chart: ingress-nginx
    version: ">=4.11.0 <4.12.0" # Поддержка semver-диапазонов для автоматических патчей
  install:
    remediation:
      retries: 3
    createNamespace: true
  upgrade:
    remediation:
      retries: 3
      strategy: rollback # Автоматический откат к предыдущей успешной ревизии при сбое
  values:
    controller:
      replicaCount: 3
      metrics:
        enabled: true
        serviceMonitor:
          enabled: true
```

Проверка состояния Helm-релиза:

```bash
flux get helmreleases -n flux-system ingress-nginx
# → NAME           REVISION  SUSPENDED  READY  MESSAGE
# → ingress-nginx  4.11.2    False      True   Helm upgrade succeeded for release ingress-nginx/ingress-nginx.v3 with chart ingress-nginx@4.11.2
```

---

### Сценарий 4: Доставка и шифрование секретов

#### Подход Flux: Нативная расшифровка SOPS с ключом age

1. Генерация ключа шифрования `age` на рабочей станции администратора:

```bash
age-keygen -o age.agekey
# → Public key: age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p
```

2. Сохранение приватного ключа в namespace `flux-system` кластера:

```bash
cat age.agekey | kubectl create secret generic sops-age \
  --namespace=flux-system \
  --from-file=age.agekey=/dev/stdin
# → secret/sops-age created
```

3. Конфигурация файла `.sops.yaml` в корне GitOps-репозитория:

```yaml
creation_rules:
  - path_regex: .*/secrets/.*\.yaml$
    encrypted_regex: '^(data|stringData)$'
    age: 'age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p'
```

4. Шифрование манифеста секрета перед коммитом в Git:

```bash
sops --encrypt --in-place deploy/overlays/production/secrets/db-credentials.yaml
# → Файл зашифрован. Открытые пароли заменены на блоки ENC[AES256_GCM,data:...]
```

5. Манифест Flux Kustomization с декларацией провайдера расшифровки:

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: payment-secrets
  namespace: flux-system
spec:
  interval: 1h
  path: ./deploy/overlays/production/secrets
  prune: true
  sourceRef:
    kind: GitRepository
    name: payment-repo
  targetNamespace: payments
  decryption:
    provider: sops
    secretRef:
      name: sops-age
```

`kustomize-controller` считывает секрет `sops-age`, расшифровывает payload секрета в памяти и создает нативный объект `Secret` в пространстве имен `payments`.

#### Подход Argo CD: Синхронизация через External Secrets Operator (ESO) и HashiCorp Vault

В Argo CD наиболее надежный on-premise паттерн для SRE — хранение секрета в локальном HashiCorp Vault и синхронизация через External Secrets Operator. В Git коммитится декларативный объект `ExternalSecret`:

```yaml
apiVersion: external-secrets.io/v1
kind: SecretStore
metadata:
  name: vault-backend
  namespace: payments
spec:
  provider:
    vault:
      server: "https://vault.internal.corp:8200"
      path: "secret"
      version: "v2"
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "payments-workload"
          serviceAccountRef:
            name: payment-service-sa
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: db-credentials
  namespace: payments
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: payment-db-secret # Имя целевого Kubernetes Secret
    creationPolicy: Owner
  data:
    - secretKey: DB_PASSWORD
      remoteRef:
        key: payments/production/database
        property: password
```

Манифест `ExternalSecret` коммитится в Git как обычный ресурс приложения и синхронизируется Argo CD без необходимости передавать ключи расшифровки в `argocd-repo-server`.

---

### Сценарий 5: Мультитенантность и изоляция прав команд

#### Подход Argo CD: AppProject с белыми списками и OIDC-группами

Администратор платформы описывает проект, ограничивающий права команды `payments`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: payments-team
  namespace: argocd
spec:
  description: "Проект сервисов платежного шлюза"
  sourceRepos:
    - "https://git.internal.corp/apps/payment-*.git"
    - "oci://harbor.internal.corp/charts/*"
  destinations:
    - server: "https://kubernetes.default.svc"
      namespace: "payments"
    - server: "https://kubernetes.default.svc"
      namespace: "payments-staging"
  clusterResourceWhitelist: [] # Запрет создания кластерных ресурсов (ClusterRole, CRD, PV)
  namespaceResourceBlacklist:
    - group: ""
      kind: ResourceQuota      # Запрет изменения собственных квот
    - group: ""
      kind: LimitRange
  roles:
    - name: developer
      description: "Права на просмотр и ручную синхронизацию"
      policies:
        - p, proj:payments-team:developer, applications, get, payments-team/*, allow
        - p, proj:payments-team:developer, applications, sync, payments-team/*, allow
      groups:
        - "keycloak:developers-payments" # Привязка к группе корпоративного Keycloak/LDAP
```

Разработчик создает `Application` с указанием `project: payments-team`. Попытка указать репозиторий вне маски `payment-*.git` или выполнить деплой в namespace `monitoring` будет заблокирована admission-валидатором Argo CD.

#### Подход Flux: ServiceAccount Impersonation и RBAC Kubernetes

В модели Flux изоляция строится стандартными манифестами Kubernetes без участия сторонних абстракций:

1. Создание изолированного сервисного аккаунта и ограничение его роли:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: payments-reconciler
  namespace: payments
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: payments-reconciler-role
  namespace: payments
rules:
  - apiGroups: ["", "apps", "batch"]
    resources: ["services", "configmaps", "secrets", "deployments", "cronjobs"]
    verbs: ["*"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: payments-reconciler-binding
  namespace: payments
subjects:
  - kind: ServiceAccount
    name: payments-reconciler
    namespace: payments
roleRef:
  kind: Role
  name: payments-reconciler-role
  apiGroup: rbac.authorization.k8s.io
```

2. В манифесте `Kustomization` указывается созданный аккаунт:

```yaml
spec:
  serviceAccountName: payments-reconciler
  targetNamespace: payments
```

Если манифест в GitOps-репозитории содержит объект `ClusterRole` или ресурс в пространстве имен `kube-system`, запрос `kustomize-controller` к API-серверу завершится ошибкой:
`User "system:serviceaccount:payments:payments-reconciler" cannot create resource "clusterroles" at the cluster scope`.

---

### Сценарий 6: Управление дрейфом, откат версий и аварийная приостановка

#### Стратегия отката 1: Канонический GitOps (`git revert`)

Является эталонным способом для обоих инструментов. Сохраняет непрерывность истории Git и не вызывает конфликтов с контроллерами:

```bash
cd fleet-gitops
git log -n 3 --oneline
# → a1b2c3d (HEAD -> main) feat(payments): upgrade image to v2.4.0
# → 9876fed chore: update configmap
# → 1234abc fix: rollback candidate

git revert a1b2c3d --no-edit
git push origin main
# → Argo CD и Flux автоматически фиксируют коммит отката и возвращают старое состояние
```

#### Стратегия отката 2: Оперативный откат через CLI при инциденте

В условиях production-аварии ожидание CI/CD-пайплайна может быть недопустимо. Специфика поведения инструментов:

**В Argo CD:**
```bash
# 1. При наличии auto-sync откат через CLI будет немедленно перезаписан!
# Сначала обязательно временно отключаем automated sync:
argocd app set payment-service --sync-policy none
# → application 'payment-service' updated

# 2. Проверяем историю ревизий и выполняем откат на целевой ID:
argocd app history payment-service
# → ID  DATE                           REVISION
# → 1   2026-10-13 14:00:00 +0300 MSK  main (1234abc)
# → 2   2026-10-13 17:00:00 +0300 MSK  main (a1b2c3d)

argocd app rollback payment-service 1
# → Application 'payment-service' rolled back to revision 1

# 3. После устранения инцидента выполняется git revert и возвращается auto-sync:
argocd app set payment-service --sync-policy automated --auto-prune --self-heal
```

**Во Flux:**
Во Flux команда `rollback` отсутствует для обычных манифестов (так как контроллер сразу перезапишет состояние). Процедура аварийной заморозки:

```bash
# 1. Замораживаем цикл реконсиляции (останавливается детекция и коррекция дрейфа):
flux suspend kustomization payment-service
# → ► suspending kustomization payment-service in flux-system namespace
# → ✔ kustomization suspended

# 2. Теперь SRE-инженер может вручную применить временный hotfix через kubectl:
kubectl set image deployment/payment-service payment-api=payment-api:v2.3.9 -n payments
# → deployment.apps/payment-service image updated

# 3. После оформления коммита в Git возобновляем реконсиляцию:
flux resume kustomization payment-service
# → ► resuming kustomization payment-service in flux-system namespace
# → ✔ kustomization resumed

# 4. Принудительно запускаем немедленную сверку:
flux reconcile kustomization payment-service --with-source
# → ► annotating Kustomization payment-service
# → ✔ Kustomization reconciled
```

---

## Эксплуатация и команды

### Сравнительная таблица ежедневных команд SRE/DevOps

| Операция SRE | Команда Argo CD CLI | Команда Flux CLI |
| :--- | :--- | :--- |
| **Проверка статуса объектов** | `argocd app list`<br>`argocd app get <app>` | `flux get sources git`<br>`flux get kustomizations`<br>`flux get helmreleases -A` |
| **Детальное описание объекта** | `argocd app get <app> --show-params` | `flux describe kustomization <name>`<br>`flux describe helmrelease <name>` |
| **Принудительная реконсиляция** | `argocd app sync <app>`<br>`argocd app sync <app> --force` | `flux reconcile source git <name>`<br>`flux reconcile kustomization <name> --with-source` |
| **Анализ расхождений (Diff)** | `argocd app diff <app> --server-side-generate` | `flux diff kustomization <name> --path ./overlays/prod` |
| **Аварийная приостановка** | `argocd app set <app> --sync-policy none` | `flux suspend kustomization <name>`<br>`flux suspend helmrelease <name>` |
| **Возобновление синхронизации** | `argocd app set <app> --sync-policy automated` | `flux resume kustomization <name>`<br>`flux resume helmrelease <name>` |
| **Просмотр логов контроллеров** | `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller -f` | `flux logs --level=error --all-namespaces`<br>`flux logs -f --kind=Kustomization --name=<name>` |
| **Просмотр событий (Events)** | `kubectl get events -n argocd --sort-by='.lastTimestamp'` | `flux events --for Kustomization/<name>` |
| **Инспекция экспортируемых метрик** | `curl -s http://argocd-metrics:8082/metrics` | `curl -s http://kustomize-controller:8080/metrics` |

### Практические примеры вызова команд

1. **Анализ различий перед применением (Dry-run Diff)**:

```bash
# Argo CD (сравнение желаемого состояния из Git с Live-состоянием API-сервера)
argocd app diff payment-service --server-side-generate
# → ===== apps/Deployment payments/payment-service ======
# → 23c23
# → <   replicas: 2
# → ---
# → >   replicas: 4

# Flux (сравнение артефакта с состоянием кластера)
flux diff kustomization payment-service --path ./deploy/overlays/production
# → ► calculating diff for payment-service
# → --- payments/Deployment/payment-service
# → +++ payments/Deployment/payment-service
# → @@ -23,1 +23,1 @@
# → -  replicas: 2
# → +  replicas: 4
```

2. **Диагностика ошибок через события**:

```bash
# Flux: просмотр журнала событий конкретного объекта
flux events --for Kustomization/payment-service
# → 2026-10-13T17:20:00Z  Normal   Progressing  Kustomization/payment-service  Processing source revision: main@sha1:a1b2c3d
# → 2026-10-13T17:20:02Z  Warning  Failed       Kustomization/payment-service  Service/payment-service dry-run failed: port 8080 already in use
```

---

## Диагностика и устранение неполадок

### Сводная матрица типовых инцидентов

| Симптом | Инструмент | Корневая причина | Диагностика и решение |
| :--- | :--- | :--- | :--- |
| **Ручные правки откатываются каждые N минут** | Flux | Непрерывная коррекция дрейфа Server-Side Apply по расписанию | Если поле должно управляться другим контроллером (HPA), добавьте JSON-путь в `spec.ignore` либо исключите поле в `DriftIgnoreRules`. Проверьте менеджера полей: `kubectl get deploy <name> -o yaml \| grep -A5 managedFields`. |
| **Статус `OutOfSync`, но изменения не вносятся** | Argo CD | В манифесте `Application` отключен блок `automated.selfHeal` | Включите автоисправление: `argocd app set <app> --auto-prune --self-heal` либо запустите синхронизацию вручную `argocd app sync <app>`. |
| **Ошибка `403 Forbidden` при реконсиляции** | Flux | Указанный в `spec.serviceAccountName` аккаунт не имеет прав | Изучите статус: `kubectl describe kustomization <name>`. Расширьте `Role` / `RoleBinding` в целевом namespace. Убедитесь, что манифест не создает `ClusterRole` без `ClusterRoleBinding`. |
| **Репозиторий не найден (`not permitted`)** | Argo CD | URL репозитория отсутствует в белом списке `AppProject` | Добавьте URL репозитория в поле `spec.sourceRepos` ресурса `AppProject`, к которому привязано приложение. |
| **«Мигание» реплик Deployment (борьба с HPA)** | Оба | Конфликт владения полем `spec.replicas` между GitOps и HPA | **Argo CD:** добавить `ignoreDifferences` для `Deployment` по пути `/spec/replicas`.<br>**Flux:** добавить `spec.ignore: [{path: "/spec/replicas"}]` в манифест `Kustomization`. |
| **Зависание реконсиляции без сообщений об ошибках** | Flux | Объект переведен в статус `suspend: true` | Проверьте состояние: `flux get kustomizations` (столбец `SUSPENDED`). Разморозьте контроллер: `flux resume kustomization <name>`. |
| **Ошибка валидации x509 при обращении к Git/OCI** | Оба | Самоподписанный корпоративный TLS-сертификат CA не доверен | **Argo CD:** смонтировать сертификат CA в `argocd-repo-server` и `argocd-server` (`argocd-tls-certs-cm`).<br>**Flux:** передать CA через поле `spec.certSecretRef` в манифесте `GitRepository` или `HelmRepository`. |
| **Высокая задержка синхронизации в монорепозитории** | Оба | Полное клонирование объемной истории Git при каждом цикле | **Argo CD:** включить Shallow Cloning в `argocd-cm` (`git.shallow.clone: "true"`).<br>**Flux:** использовать OCI-артефакты (`OCIRepository`) вместо прямого клонирования Git. |

### Детальные сценарии устранения неисправностей

#### Сценарий А: Разрешение конфликта владения полями Server-Side Apply (Flapping с HPA)

При использовании Horizontal Pod Autoscaler и фиксации числа реплик в Git контроллер GitOps и HPA начинают попеременно перезаписывать поле `spec.replicas`.

**Диагностика:**
```bash
# Проверка менеджеров полей объекта
kubectl get deployment payment-service -n payments -o jsonpath='{.metadata.managedFields}' | jq .
# → Видны две конфликтующие записи:
# → "manager": "kustomize-controller", "fieldsV1": {"f:spec": {"f:replicas": {}}}
# → "manager": "kube-controller-manager", "subresource": "scale", "fieldsV1": {"f:spec": {"f:replicas": {}}}
```

**Решение для Argo CD:**
```yaml
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      name: payment-service
      jsonPointers:
        - /spec/replicas
```

**Решение для Flux (v2.9+):**
```yaml
spec:
  ignore:
    - paths:
        - /spec/replicas
      target:
        kind: Deployment
        name: payment-service
```

#### Сценарий Б: Сбой и зависание HelmRelease в состоянии `pending-upgrade`

При аварийном завершении пода во время обновления Helm-релиз во Flux может зависнуть в статусе блокировки.

**Диагностика:**
```bash
flux describe helmrelease ingress-nginx -n flux-system
# → Status:
# →   Conditions:
# →     Message: another operation (install/upgrade/rollback) is in progress
# →     Reason: UpgradeFailed
# →     Status: False
# →     Type: Ready
```

**Решение:**
1. Принудительно очистить блокировку Helm Secrets:
```bash
# Поиск секрета текущей заблокированной ревизии
kubectl get secrets -n ingress-nginx -l owner=helm,status=pending-upgrade
# → sh.helm.release.v1.ingress-nginx.v4

# Смена статуса на failed для разблокировки механизма remediation
kubectl patch secret sh.helm.release.v1.ingress-nginx.v4 -n ingress-nginx \
  --type=merge -p '{"metadata":{"labels":{"status":"failed"}}}'
# → secret/sh.helm.release.v1.ingress-nginx.v4 patched
```
2. Повторная реконсиляция:
```bash
flux reconcile helmrelease ingress-nginx -n flux-system --force
# → ✔ HelmRelease ingress-nginx reconciled
```

---

## Лучшие практики

### Рекомендации SRE и системных администраторов для On-Premise инфраструктуры

1. **Архитектурная организация репозиториев**:
   - Разделяйте репозитории исходного кода приложений и GitOps-репозитории конфигураций.
   - Используйте двухуровневую структуру каталогов: `infrastructure/` (CRD, ingress-контроллеры, cert-manager, драйверы CSI, сетевые плагины) и `apps/` (бизнес-сервисы по окружениям `base/`, `overlays/prod`, `overlays/stage`).
   - Системную инфраструктуру развертывайте с приоритетом Sync Waves (в Argo CD) или цепочками `dependsOn` (во Flux), гарантируя готовность операторов перед деплоем рабочих нагрузок.

2. **Оптимизация нагрузки на `kube-apiserver`**:
   - Избегайте сверхкоротких интервалов опроса Git (менее 1 минуты). В крупных кластерах с сотнями приложений одновременный опрос создает лавинообразную нагрузку на Git-сервер и API Kubernetes.
   - Настройте отправку входящих Webhook-уведомлений от локального Git-сервера (GitLab/Gitea) на контроллеры:
     - Для Argo CD: endpoint `/api/webhook` на `argocd-server`.
     - Для Flux: endpoint `notification-controller` с типом ресурса `Receiver`.
   - Увеличьте интервалы фоновой проверки дрейфа до 30–60 минут, полагаясь на мгновенную реакцию через вебхуки.

3. **Hardening контроллеров и принцип наименьших привилегий**:
   - Никогда не запускайте контроллеры GitOps от привилегированного пользователя (`root`). Используйте строгий `securityContext`:
     ```yaml
     securityContext:
       runAsNonRoot: true
       runAsUser: 10001
       readOnlyRootFilesystem: true
       allowPrivilegeEscalation: false
       capabilities:
         drop: ["ALL"]
     ```
   - Ограничивайте сетевой периметр с помощью `NetworkPolicy`: запретите входящий трафик к контроллерам из пространств имен приложений, разрешите только egress к `kube-apiserver` (порт 6443), корпоративному Git-серверу и OCI-реестру.

4. **Аварийное восстановление (Disaster Recovery)**:
   - При соблюдении принципов GitOps полный бэкап etcd кластера не является критически необходимым для восстановления сервисов: вся конфигурация сохранена в Git.
   - Для Argo CD: регулярно выполняйте экспорт конфигурации в отдельное резервное хранилище утилитой `argocd-util export > argocd-backup.yaml` (сохраняет сущности `Application`, `AppProject`, настройки SSO и историю ревизий).
   - Для Flux: при полной потере кластера достаточно запустить процедуру bootstrap на новом чистом кластере (`flux bootstrap git ...`), указав тот же репозиторий и путь. Контроллеры автоматически скачают манифесты и поднимут всю инфраструктуру с нуля.

5. **Мониторинг ключевых метрик (SLO/SLI контрольной плоскости)**:
   - В стеке Prometheus настройте сбор метрик контроллеров:
     - **Argo CD**: `argocd_app_sync_total` (счетчик синхронизаций), `argocd_app_reconcile_count` (интенсивность сверок), `argocd_git_request_duration_seconds` (задержка обращения к Git-серверу).
     - **Flux**: `gotk_reconcile_condition` (состояние Ready контроллеров), `gotk_reconcile_duration_seconds` (время выполнения цикла сверки).
   - Настройте критический алерт на зависание очереди реконсиляции: если `argocd_app_reconcile_count` падает до нуля при наличии расхождений или `gotk_reconcile_condition{status="False"} > 0` в течение более 15 минут.

---

## Дополнительная информация

### Сводная матрица архитектурных и функциональных различий

| Критерий | Argo CD (v3.5+) | Flux (v2.9.x) |
| :--- | :--- | :--- |
| **Философия** | Централизованная платформа «все-в-одном» | Модульный инструментарий (Unix-way Toolkit) |
| **Графический интерфейс** | Полнофункциональный Web UI (diff, логи, история, синхронизация) | Отсутствует в ядре (используются CLI, k9s, FreeLens или Flux Operator UI) |
| **Helm поддержка** | Рендеринг `helm template` на стороне сервера (без создания Helm secrets) | Нативный Helm Go SDK с сохранением состояния релиза в Secrets, `helm test`, `rollback` |
| **OCI-артефакты** | Поддерживаются как источник чартов и манифестов (v3.1+) | OCI является базовым транспортом (`flux push artifact`, кэширование, Cosign) |
| **Автоматизация образов** | Дополнительный контроллер Argo CD Image Updater | Встроенные контроллеры `image-reflector` и `image-automation` (коммитят теги в Git) |
| **Уведомления** | Встроенный модуль `argocd-notifications` (ConfigMap + аннотации) | Выделенный контроллер `notification-controller` (`Provider`, `Alert`, `Receiver`) |
| **Работа с монорепозиториями** | Shallow Clone (`git.shallow.clone: "true"`), выборочная генерация манифестов | `source-controller` с поддержкой `.sourceignore` и составных OCI-артефактов |
| **Прогрессивная доставка** | Интеграция с Argo Rollouts (Canary, Blue-Green, AnalysisTemplate) | Интеграция с Flagger (Canary, A/B Testing, интеграция с Ingress-контроллерами) |

### Критерии выбора инструмента для On-Premise инфраструктуры

| Ситуация и профиль команды | Рекомендуемый инструмент | Обоснование выбора |
| :--- | :--- | :--- |
| **Платформенная команда обслуживает сотни прикладных разработчиков** | **Argo CD** | Наличие интуитивного Web UI резко снижает порог входа, позволяет разработчикам самостоятельно отслеживать статус развертывания, анализировать diff и смотреть логи без выдачи прямого доступа к `kubectl`. |
| **Строгие требования к потреблению ресурсов, Edge-кластеры, bare-metal узлы** | **Flux** | Минимальный footprint контроллеров (от 150 МБ RAM на весь стек против 1.5–3 ГБ у Argo CD с Redis и UI), отсутствие внешних зависимостей. |
| **Жесткие регламенты мультитенантности и корпоративного аудита** | **Argo CD** | `AppProject` предоставляет готовую консолидированную матрицу прав доступа, белые списки ресурсов и прямую привязку к группам корпоративного OIDC (Keycloak). |
| **Команда со зрелой культурой Kubernetes и терминального администрирования** | **Flux** | Полная декларативность через стандартные CRD и `kubectl`, прозрачная интеграция с ServiceAccount impersonation, отсутствие скрытых абстракций. |
| **Глубокое использование Helm со сложными lifecycle hooks и автооткатом** | **Flux** | `helm-controller` обеспечивает 100% совместимость с оригинальным поведением Helm CLI, включая автоматический rollback при сбое тестов или health-check. |
| **Необходимость нативного шифрования секретов в Git без внешних операторов** | **Flux** | Встроенный модуль расшифровки Mozilla SOPS в `kustomize-controller` исключает необходимость обслуживания дополнительных операторов. |

**Гибридный подход:** В крупных корпоративных средах часто применяется комбинированная архитектура:
- **Flux** используется системными инженерами как фундамент кластера для развертывания системных сервисов (CSI, CNI, ingress-nginx, cert-manager, мониторинг) сразу после создания кластера через bootstrap.
- **Argo CD** развертывается поверх кластера как портал самообслуживания (Developer Platform) для продуктовых команд и микросервисов.

---

### Связанные документы

- [Обзор методологии GitOps](./GitOps_overview.md) — фундаментальные принципы декларативной инфраструктуры, pull-модели и контроля дрейфа.
- [Обзор Flux](./flux.md) — детальное руководство по архитектуре GitOps Toolkit, контроллерам и спецификациям CRD.
- [Обзор Argo CD](./ArgoCD/argocd_overview.md) — архитектура компонентов, жизненный цикл синхронизации и управление приложениями.
- [Управление мультитенантностью в Argo CD](./ArgoCD/argocd_multi_tenancy.md) — детальная настройка AppProject, ролей и OIDC-маппинга.
- [Диагностика и мониторинг Argo CD](./ArgoCD/argocd_troubleshooting_and_monitoring.md) — сбор метрик Prometheus, трассировка и отладка компонентов.
- [Синхронизация и хуки в Argo CD](./ArgoCD/synchronization.md) — волновой деплой (Sync Waves), хуки жизненного цикла и Server-Side Apply.
- [Управление секретами в GitOps](./secrets_encryption.md) — подробное сравнение SOPS, Sealed Secrets и External Secrets Operator.
- [Организация монорепозитория Argo CD](./Concepts/argocd_monorepo_organization.md) — структуры каталогов, пути Application и оптимизация сборки.
- [Прогрессивная доставка в GitOps](./Concepts/progressive_delivery_gitops.md) — канареечные релизы через Argo Rollouts и Flagger.
- [Мультикластерные паттерны](./Concepts/multi_cluster_patterns.md) — архитектура распределения приложений по нескольким кластерам.
- [Оповещения в GitOps](./gitops_notifications.md) — настройка webhook-уведомлений в мессенджеры и корпоративные чаты.
- [RBAC-паттерны: per-namespace роли в Kubernetes](./Kubernetes/Security/rbac/gitops_rbac_patterns.md) — иерархические ClusterRole с агрегацией и per-namespace RoleBinding в GitOps.

### Официальные ресурсы

- [Документация Argo CD](https://argo-cd.readthedocs.io/)
- [Документация Flux Community](https://fluxcd.io/docs/)
- [Спецификация Open Container Initiative (OCI)](https://opencontainers.org/)
- [Репозиторий Mozilla SOPS](https://github.com/getsops/sops)
