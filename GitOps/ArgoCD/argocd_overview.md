# Argo CD — декларативный GitOps для Kubernetes

**Актуально для:** Argo CD v3.5+ (покрывает v3.4.x, v3.5.x, v3.6.x; Kubernetes 1.28–1.32+; bare-metal / on-premise)

> **Ключевые возможности ветки v3.x:** Server-Side Apply по умолчанию, Progressive Sync для ApplicationSets, PreDelete-хуки (v3.3+), PostDelete-хуки (v2.10+), OCI-артефакты (v3.1+), Shallow Git Cloning (v3.3+), Server-Side Diff (v3.5+), флаг `syncOverrun` в окнах синхронизации (v3.5+).

## Определения

**Argo CD** — декларативный GitOps-инструмент непрерывной доставки (CD) для Kubernetes. Автоматизирует развертывание манифестов и поддерживает состояние кластеров синхронизированным с Git-репозиториями, выступающими эталонным источником конфигурации.

**Желаемое состояние (Desired State)** — эталонная конфигурация ресурсов (YAML, Helm, Kustomize, Jsonnet, OCI-артефакты), зафиксированная в Git-репозитории.

**Фактическое состояние (Live State)** — текущее состояние объектов, функционирующих непосредственно в кластере Kubernetes (получаемое из API-сервера).

**Цикл сверки (Reconciliation Loop)** — непрерывный процесс сравнения желаемого и фактического состояний с последующим устранением расхождений (Drift).

**Детекция расхождений (Drift Detection)** — обнаружение отклонений между состоянием объектов в Git и их реальными параметрами в кластере.

**Самовосстановление (Self-Healing)** — автоматический возврат конфигурации ресурсов кластера к эталонному состоянию из Git при несанкционированных ручных правках.

**Application (Приложение)** — кастомный ресурс Kubernetes (`applications.argoproj.io`), связывающий источник конфигурации в Git с целевым кластером и пространством имен.

**AppProject (Проект)** — кастомный ресурс Kubernetes (`appprojects.argoproj.io`), определяющий логические границы безопасности и мультитенантности (разрешенные репозитории, кластеры, типы ресурсов и роли).

**ApplicationSet** — контроллер и CRD (`applicationsets.argoproj.io`) для массовой генерации объектов `Application` на основе шаблонов и генераторов (List, Git, Cluster, Matrix, Merge).

**Sync Wave** — механизм фазовой синхронизации (аннотация `argocd.argoproj.io/sync-wave`), определяющий строгий порядок применения манифестов по числовым уровням.

**Resource Tracking** — механизм отслеживания принадлежности ресурсов конкретному приложению Argo CD через метки (`app.kubernetes.io/instance`) или аннотации (`argocd.argoproj.io/tracking-id`).

**Server-Side Apply (SSA)** — нативный механизм Kubernetes API для отслеживания владения полями объектов (`fieldManager`), позволяющий разрешать конфликты манифестов на уровне сервера.

## Архитектура и основные концепции

### Назначение и принципы GitOps

Argo CD реализует парадигму GitOps с архитектурой Pull-модели:
- **Декларативность:** Инфраструктура и рабочие нагрузки описываются декларативно в версионируемых Git-репозиториях.
- **Pull-модель вместо Push:** Контроллер Argo CD выполняется внутри кластера и самостоятельно забирает изменения из Git, исключая необходимость открытия прямого доступа к API-серверу Kubernetes из внешних CI-систем.
- **Непрерывный мониторинг:** Контроллер постоянно опрашивает API-сервер и сверяет состояние объектов с целевой ревизией в Git.
- **Аудит и воспроизводимость:** Любое изменение инфраструктуры проходит через Git-коммиты, код-ревью и журнал версий.

### Компоненты системы

Контрольная плоскость Argo CD разделена на специализированные микросервисы:

| Компонент | Процесс в K8s | Роль и назначение в архитектуре |
| :--- | :--- | :--- |
| **API Server** | `argocd-server` | Предоставляет Web UI, gRPC и REST API интерфейсы. Обрабатывает входящие вызовы CLI, вебхуки Git-провайдеров и передает команды контроллерам. |
| **Repo Server** | `argocd-repo-server` | Автономный сервис клонирования Git-репозиториев, рендеринга шаблонов (Helm, Kustomize, CMP-плагины) и кэширования манифестов. Не имеет прямого доступа к кластерам. |
| **Application Controller** | `argocd-application-controller` | Ключевой оператор. Опрашивает API-серверы управляемых кластеров, сравнивает Live State с Desired State и применяет изменения через K8s API. |
| **ApplicationSet Controller** | `argocd-applicationset-controller` | Обрабатывает CRD `ApplicationSet`, опрашивает генераторы и создает/удаляет дочерние ресурсы `Application`. Встроен в дистрибутив v3.x. |
| **Notifications Controller** | `argocd-notifications-controller` | Отслеживает изменения состояний приложений и отправляет уведомления по триггерам (Telegram, Slack, Email, Webhooks). |
| **Dex Server** | `argocd-dex-server` | Встроенный брокер аутентификации. Обеспечивает интеграцию с корпоративными провайдерами (Keycloak, GitLab, LDAP/FreeIPA). |
| **Redis** | `argocd-redis` / `argocd-redis-ha` | Высокопроизводительное хранилище кэша состояния кластеров, отрендеренных манифестов и пользовательских сессий. |

### Сетевая схема взаимодействия

```mermaid
flowchart TD
    subgraph GitOps_Sources["Источники конфигурации"]
        GitRepo["Git-репозиторий (GitLab / Gitea)"]
        HelmRepo["OCI / Helm Registry (Harbor)"]
    end

    subgraph ArgoCD_Namespace["Контрольная плоскость Argo CD (Namespace: argocd)"]
        Server["argocd-server (UI / API) :8080/8083"]
        RepoServer["argocd-repo-server :8081"]
        AppController["argocd-application-controller"]
        AppSetController["argocd-applicationset-controller"]
        RedisNode["argocd-redis :6379"]
        DexNode["argocd-dex-server :5556"]
    end

    subgraph Managed_Clusters["Целевые кластеры"]
        K8sLocal["Локальный K8s API (:6443)"]
        K8sRemote["Удаленный K8s API (:6443)"]
    end

    DevOps["Инженер / CI Runner"] -->|HTTPS/gRPC :443| Server
    Server -->|Аутентификация :5556| DexNode
    Server -->|Чтение кэша :6379| RedisNode
    Server -->|Команды синхронизации| AppController

    RepoServer -->|Git Fetch / SSH :22 / HTTPS :443| GitRepo
    RepoServer -->|Pull Helm / OCI :443| HelmRepo
    RepoServer -->|Кэширование манифестов :6379| RedisNode

    AppController -->|Запрос отрендеренных YAML :8081| RepoServer
    AppController -->|Кэш состояния ресурсов :6379| RedisNode
    AppController -->|Reconcile / Apply :6443| K8sLocal
    AppController -->|Reconcile / Apply :6443| K8sRemote
    AppSetController -->|Создание Application CR| AppController
```

### Архитектурный цикл сверки (Reconciliation Loop)

Сверка выполняется циклически (по умолчанию каждые 3 минуты либо мгновенно по событию Git Webhook):

1. **Refresh (Обновление):** `argocd-application-controller` запрашивает у `argocd-repo-server` манифесты целевой ревизии Git. `repo-server` проверяет кэш Redis. Если манифесты отсутствуют или ревизия изменилась, репозиторий опрашивается через Git/Helm, генерируется чистый YAML и результат сохраняется в кэш.
2. **Diff (Сравнение):** Контроллер опрашивает API-сервер целевого кластера через Informer-кэш, получая актуальный Live State. Выполняется сравнение (Client-Side или Server-Side Diff в v3.5+) с учетом фильтров `ignoreDifferences`.
3. **Sync (Синхронизация):** Если обнаружены расхождения (`OutOfSync`) и активирован режим `Automated Sync`, контроллер выстраивает граф выполнения с учетом волн (`Sync Waves`) и хуков (`Hooks`), применяя манифесты через Server-Side Apply.
4. **Health Assessment (Оценка здоровья):** Контроллер анализирует состояние дочерних ресурсов (Pods, Deployments, StatefulSets, CRD) и вычисляет общий статус здоровья приложения.

### Статусы синхронизации и здоровья

**Статусы синхронизации (Sync Status):**
- **Synced:** Фактическое состояние объектов в кластере идентично манифестам в Git.
- **OutOfSync:** Обнаружены расхождения (новые коммиты в Git, ручные правки в кластере либо отсутствие объектов).
- **Unknown:** Состояние не определено (ошибка связи с API-сервером или ошибка генерации манифестов в repo-server).

**Статусы здоровья (Health Status):**

| Статус | Описание состояния | Типичные причины |
| :--- | :--- | :--- |
| **Healthy** | Все ресурсы функционируют штатно и готовы к обслуживанию трафика. | Pods `Running`, Endpoints обновлены, Jobs завершились успешно (`Completed`). |
| **Progressing** | Ресурсы находятся в переходном состоянии обновления. | Идет rolling update Deployment, скачиваются образы, отрабатывают поды InitContainer. |
| **Degraded** | Ресурс перешел в состояние неустранимого сбоя. | `CrashLoopBackOff`, `ImagePullBackOff`, `OOMKilled`, не пройдены readiness-пробы. |
| **Suspended** | Выполнение ресурса приостановлено конфигурацией. | `CronJob` с `suspend: true`, приостановленный пайплайн. |
| **Missing** | Ресурс описан в Git, но отсутствует в кластере Kubernetes. | Первоначальное создание приложения до первого синка. |
| **Unknown** | Статус здоровья не может быть рассчитан. | Отсутствует Lua-скрипт оценки здоровья для сторонней CRD. |

### Кастомные проверки здоровья (Lua Health Checks)

Для пользовательских CRD Argo CD использует Lua-скрипты, настраиваемые в `argocd-cm`. Без скрипта CRD автоматически получает статус `Healthy`, маскируя реальные сбои оператора.

**Пример 1: Health Check для Cert-Manager Certificate:**
```yaml
# ConfigMap argocd-cm
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  resource.customizations.health.cert-manager.io_Certificate: |
    hs = {}
    if obj.status ~= nil and obj.status.conditions ~= nil then
      for _, condition in ipairs(obj.status.conditions) do
        if condition.type == "Ready" then
          if condition.status == "True" then
            hs.status = "Healthy"
            hs.message = "Certificate is valid and ready"
            return hs
          elseif condition.status == "False" then
            hs.status = "Degraded"
            hs.message = condition.message or "Certificate issuance failed"
            return hs
          end
        end
      end
    end
    hs.status = "Progressing"
    hs.message = "Waiting for Certificate issuance"
    return hs
```

**Пример 2: Health Check для PostgreSQL-кластера (Zalando Postgres Operator):**
```yaml
# ConfigMap argocd-cm
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  resource.customizations.health.acid.zalan.do_postgresql: |
    hs = {}
    if obj.status ~= nil then
      if obj.status.PostgresClusterStatus == "Running" then
        hs.status = "Healthy"
        hs.message = "PostgreSQL cluster is running"
        return hs
      elseif obj.status.PostgresClusterStatus == "UpdateFailed" or obj.status.PostgresClusterStatus == "CreateFailed" then
        hs.status = "Degraded"
        hs.message = "PostgreSQL cluster provisioning failed"
        return hs
      end
    end
    hs.status = "Progressing"
    hs.message = "PostgreSQL cluster is creating or updating"
    return hs
```

### Отслеживание ресурсов (Resource Tracking)

Чтобы контроллер знал, какими ресурсами кластера управляет конкретный `Application`, используется механизм Resource Tracking (параметр `application.resourceTrackingMethod` в `argocd-cm`):

| Метод | Идентификатор | Особенности и рекомендации |
| :--- | :--- | :--- |
| **label** | `app.kubernetes.io/instance: <app-name>` | Традиционный метод. Ограничение: длина значения метки в K8s ограничена 63 символами. Конфликтует с чартами Helm, перезаписывающими эту метку. |
| **annotation** | `argocd.argoproj.io/tracking-id: <app-name>:<group>/<kind>:<ns>/<name>` | **Рекомендуемый стандарт**. Исключает конфликты длины имен и безопасно работает с Helm-релизами на on-premise инфраструктуре. |
| **annotation+label** | Использует оба атрибута | Обеспечивает обратную совместимость при миграциях с ранних версий ценой дополнительного объема метаданных. |

### Сравнение: Argo CD vs Flux v2

| Критерий | Argo CD | Flux v2 |
| :--- | :--- | :--- |
| **Архитектурная модель** | Централизованный сервер управления с многопользовательским UI. | Распределенный набор независимых контроллеров (Source, Kustomize, Helm). |
| **Интерфейс** | Полнофункциональный Web UI + развитый CLI. | Консольная утилита `flux` (UI через сторонний Weave GitOps). |
| **Мультикластерность** | Управление сотнями удаленных кластеров из одного центрального Hub. | Рекомендуется автономная установка контроллеров в каждый целевой кластер. |
| **Управление порядком** | Числовые уровни Sync Waves (`-5`, `0`, `5`) + хуки жизненного цикла. | Декларативные зависимости между ресурсами (`dependsOn`). |
| **Мультитенантность** | Нативная изоляция через `AppProject`, встроенный RBAC и SSO. | Изоляция через ServiceAccount impersonation и K8s RBAC пространств имен. |
| **Шифрование секретов** | Интеграция через плагины (AVP, SOPS via CMP, Sealed Secrets). | Нативная встроенная поддержка SOPS в `Kustomization` контроллере. |

## Установка и базовая конфигурация

### Предварительные требования

Для развертывания Argo CD в bare-metal / on-premise окружении необходимо подготовить:

1. **Kubernetes кластер:** v1.28–1.32+ (kubeadm, Talos, RKE2, k3s). Наличие стабильного кворума etcd с задержкой fsync < 10 мс.
2. **Аппаратные ресурсы контрольной плоскости (SRE Sizing):**
   - **Тестовый контур (Non-HA):** 2 vCPU, 4 GiB RAM, 10 GiB локального диска (для кэша Git repo-server).
   - **Production контур (HA Mode):** 3 ноды; суммарно 8 vCPU, 16 GiB RAM. 3 реплики `argocd-server`, `argocd-repo-server`, Redis Sentinel (3 реплики с HAProxy).
3. **Сетевой доступ:** Доступ по портам HTTPS (443) или SSH (22) до локального Git-сервера (GitLab, Gitea) и OCI/Helm реестра (Harbor, Nexus).
4. **Привилегии:** Учетная запись с правами `cluster-admin` для первичного создания CRD и ClusterRole.

### Пошаговая установка

#### Шаг 1: Создание пространства имен и установка манифестов

Применяем официальный манифест стабильной ветки с использованием Server-Side Apply:

```bash
kubectl create namespace argocd
# → namespace/argocd created

kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
# → customresourcedefinition.apiextensions.k8s.io/applications.argoproj.io serverside-applied
# → customresourcedefinition.apiextensions.k8s.io/appprojects.argoproj.io serverside-applied
# → customresourcedefinition.apiextensions.k8s.io/applicationsets.argoproj.io serverside-applied
# → serviceaccount/argocd-server serverside-applied
# → deployment.apps/argocd-server serverside-applied
# → deployment.apps/argocd-repo-server serverside-applied
# → deployment.apps/argocd-application-controller serverside-applied
```

#### Шаг 2: Ожидание готовности контрольной плоскости

```bash
kubectl wait --for=condition=available deployment/argocd-server -n argocd --timeout=300s
# → deployment.apps/argocd-server condition met

kubectl get pods -n argocd -o wide
# → NAME                                             READY   STATUS    RESTARTS   AGE
# → argocd-application-controller-0                  1/1     Running   0          45s
# → argocd-applicationset-controller-7bb96f9-x2k4l   1/1     Running   0          45s
# → argocd-notifications-controller-5c98d6-k9p2w    1/1     Running   0          45s
# → argocd-redis-74b8f68d95-8m2qx                    1/1     Running   0          45s
# → argocd-repo-server-6785b99f57-df4jl              1/1     Running   0          45s
# → argocd-server-54d7677bf-v7nm9                   1/1     Running   0          45s
```

#### Шаг 3: Получение начального пароля администратора

Пароль учетной записи `admin` генерируется автоматически при первом запуске и сохраняется в зашифрованном виде в секрете:

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d; echo
# → a8B9xZ_10KlmPQrs
```

> **Безопасность:** После завершения начальной настройки и смены пароля секрет `argocd-initial-admin-secret` необходимо удалить командой `kubectl delete secret -n argocd argocd-initial-admin-secret`.

#### Шаг 4: Организация доступа к Web UI и CLI

Для временного доступа с рабочего места:
```bash
kubectl port-forward svc/argocd-server -n argocd 8080:443
# → Forwarding from 127.0.0.1:8080 -> 8080
```

Для постоянного on-premise доступа через Ingress NGINX (с пробросом gRPC-трафика для CLI):

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: argocd-server-ingress
  namespace: argocd
  annotations:
    cert-manager.io/cluster-issuer: "internal-ca-issuer"
    nginx.ingress.kubernetes.io/backend-protocol: "HTTPS"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
    nginx.ingress.kubernetes.io/ssl-passthrough: "false"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - argocd.internal.infra
    secretName: argocd-server-tls
  rules:
  - host: argocd.internal.infra
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: argocd-server
            port:
              name: https
```

#### Шаг 5: Аутентификация через CLI

```bash
argocd login argocd.internal.infra:443 --username admin --password "a8B9xZ_10KlmPQrs"
# → 'admin:login' logged in successfully
# → Context 'argocd.internal.infra:443' updated
```

### Настройка доступа к корпоративному Git

Для приватных Git-репозиториев (GitLab/Gitea) настраивается секрет с типом репозитория и SSH-ключом:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: repo-infra-git
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  type: git
  url: git@gitlab.internal.infra:devops/k8s-apps.git
  sshPrivateKey: |
    -----BEGIN OPENSSH PRIVATE KEY-----
    b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAABlwAAAAdzc2gtcn
    ... (приватный ключ с правами чтения репозитория) ...
    -----END OPENSSH PRIVATE KEY-----
  insecureIgnoreHostKey: "false"
```

### Базовый манифест Application

Манифест `Application` описывает декларативную связь между исходным кодом и кластером:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: payment-service-prod
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  # Проект изоляции прав и ресурсов
  project: production-apps

  # Источник манифестов (Git / Helm)
  source:
    repoURL: git@gitlab.internal.infra:devops/k8s-apps.git
    targetRevision: main
    path: environments/production/payment-service

  # Целевой кластер и namespace
  destination:
    server: https://kubernetes.default.svc
    namespace: billing

  # Политика синхронизации
  syncPolicy:
    automated:
      prune: true       # Удалять ресурсы, удаленные из Git
      selfHeal: true    # Возвращать состояние при ручных правках в K8s
      allowEmpty: false # Запретить синк при пустом репозитории (защита от удаления всего)
    syncOptions:
    - CreateNamespace=true              # Автосоздание namespace
    - ServerSideApply=true              # Использование SSA вместо CSA
    - RespectIgnoreDifferences=true     # Учет исключений при синк-проверках
    - ApplyOutOfSyncOnly=true           # Применять только изменившиеся объекты
    - SkipDryRunOnMissingResource=true  # Пропуск dry-run если CRD создается в той же волне

  # Игнорирование расхождений от внешних контроллеров (HPA, мутирующие вебхуки)
  ignoreDifferences:
  - group: apps
    kind: Deployment
    jsonPointers:
    - /spec/replicas
```

### Подключение внешних целевых кластеров

Для управления внешними bare-metal кластерами из единого Argo CD Hub используется CLI:

```bash
# Добавление контекста кластера из локального kubeconfig
argocd cluster add production-worker-cluster --name k8s-prod-worker
# → INFO[0001] ServiceAccount "argocd-manager" created in namespace "kube-system"
# → INFO[0001] ClusterRoleBinding "argocd-manager-role" created
# → Cluster 'https://10.20.0.10:6443' added

# Проверка статуса подключения
argocd cluster list
# → SERVER                          NAME             STATUS      MESSAGE
# → https://kubernetes.default.svc  in-cluster       Successful  
# → https://10.20.0.10:6443         k8s-prod-worker  Successful  
```

## Эксплуатация и команды

### Справочник основных команд CLI

| Операция | Команда | Назначение |
| :--- | :--- | :--- |
| **Список приложений** | `argocd app list -o wide` | Просмотр всех приложений, их статусов Synced/Health, проектов и ревизий. |
| **Детали приложения** | `argocd app get <app-name>` | Просмотр дерева ресурсов приложения, условий и ошибок синхронизации. |
| **Сравнение (Diff)** | `argocd app diff <app-name>` | Показ расхождений между манифестами в Git и фактическим состоянием K8s. |
| **Ручная синхронизация**| `argocd app sync <app-name> --prune` | Принудительный запуск цикла синхронизации с удалением лишних ресурсов. |
| **Сброс кэша и сверка** | `argocd app get <app-name> --refresh` | Инвалидация кэша repo-server и немедленный опрос Git-репозитория. |
| **История ревизий** | `argocd app history <app-name>` | Вывод списка ранее развернутых коммитов и меток времени. |
| **Экстренный откат** | `argocd app rollback <app-name> <id>`| Откат к конкретной исторической ревизии из кэша контроллера. |
| **Удаление приложения** | `argocd app delete <app-name> --cascade` | Удаление CR Application вместе со всеми созданными ресурсами в кластере. |

**Примеры выполнения команд с ожидаемым выводом:**

```bash
# 1. Просмотр сводки приложений
argocd app list
# → NAME                  CLUSTER                         NAMESPACE  PROJECT          STATUS  HEALTH   SYNCPOLICY  CONDITIONS
# → payment-service-prod  https://kubernetes.default.svc  billing    production-apps  Synced  Healthy  Auto-Prune  <none>

# 2. Получение детальной информации
argocd app get payment-service-prod
# → Name:               payment-service-prod
# → Project:            production-apps
# → Server:             https://kubernetes.default.svc
# → Namespace:          billing
# → URL:                https://argocd.internal.infra/applications/payment-service-prod
# → Repo:               git@gitlab.internal.infra:devops/k8s-apps.git
# → Target:             main
# → Path:               environments/production/payment-service
# → Sync Window:        Sync Allowed
# → Sync Status:        Synced to main (c8f91a2)
# → Health Status:      Healthy
# → 
# → GROUP  KIND        NAMESPACE  NAME             STATUS  HEALTH   HOOK  MESSAGE
# →        Namespace              billing          Synced                 namespace/billing unchanged
# → apps   Deployment  billing    payment-service  Synced  Healthy        deployment.apps/payment-service serverside-applied
# →        Service     billing    payment-service  Synced  Healthy        service/payment-service serverside-applied

# 3. Принудительный опрос Git без ожидания таймаута
argocd app sync payment-service-prod --force
# → TIMESTAMP                  GROUP        KIND   NAMESPACE                  NAME    STATUS    HEALTH        HOOK  MESSAGE
# → 2026-10-12T14:40:02+03:00   apps  Deployment     billing       payment-service    Synced   Healthy              deployment.apps/payment-service configured
```

### Паттерны управления: App-of-Apps vs ApplicationSet

#### Паттерн «App-of-Apps»
Базовый паттерн GitOps-бутстрапа: одно «корневое» приложение (`Root Application`) отслеживает директорию в Git, содержащую манифесты дочерних приложений `Application`.

```yaml
# root-application.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: cluster-bootstrap-root
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: git@gitlab.internal.infra:devops/k8s-apps.git
    targetRevision: main
    path: bootstrap/production-cluster
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

*Преимущества:* Простота отладки, нативное отображение иерархии приложений в дереве интерфейса Argo CD UI.  
*Недостатки:* Требует дублирования манифестов `Application` при росте количества кластеров и сред.

#### Паттерн «ApplicationSet»
Стандарт масштабирования для крупных инфраструктур (v3.x). Позволяет описать единый шаблон приложения и динамически генерировать десятки экземпляров по списку кластеров или директорий:

```yaml
# applicationset-cluster-addons.yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: infra-cluster-addons
  namespace: argocd
spec:
  goTemplate: true
  generators:
  - git:
      repoURL: git@gitlab.internal.infra:devops/k8s-apps.git
      revision: main
      directories:
      - path: infrastructure-addons/*
  template:
    metadata:
      name: 'addon-{{ .path.basename }}'
    spec:
      project: default
      source:
        repoURL: git@gitlab.internal.infra:devops/k8s-apps.git
        targetRevision: main
        path: '{{ .path.path }}'
      destination:
        server: https://kubernetes.default.svc
        namespace: '{{ .path.basename }}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
        - CreateNamespace=true
        - ServerSideApply=true
```

### Механизмы отката (Rollback)

В GitOps существует принципиальное различие между двумя методами отката:

1. **Git Revert (Рекомендуемый стандарт):**
   - Выполняется откат коммита в репозитории: `git revert <commit-sha> && git push`.
   - Argo CD обнаруживает новую ревизию, применяет стабильный код, история Git остается непрерывной и аудируемой.
2. **Экстренный откат через UI/CLI (`argocd app rollback`):**
   - Контроллер принудительно развертывает манифесты из указанной предыдущей ревизии.
   - **Критический сайд-эффект:** Приложение переходит в статус `OutOfSync` относительно Git. Argo CD **автоматически отключает `selfHeal`** для этого приложения, предотвращая повторное применение коммита из Git. Инженер обязан зафиксировать откат коммитом в Git, иначе при следующем включении `selfHeal` вернется проблемная версия.

### Удаление и очистка ресурсов

#### Каскадное удаление (Cascading Deletion)
По умолчанию при наличии финализатора `resources-finalizer.argocd.argoproj.io`:
```bash
# Каскадное удаление: сначала удаляются все управляемые K8s объекты, затем сам объект Application
argocd app delete payment-service-prod --cascade --yes
# → Application 'payment-service-prod' deleted
```

#### Некаскадное удаление (Orphan Mode)
Если необходимо исключить приложение из-под управления Argo CD, но сохранить его поды и базы данных в кластере:
```bash
# Удаляется только ресурс Application в namespace argocd, рабочие нагрузки остаются жить
argocd app delete payment-service-prod --cascade=false --yes
# → Application 'payment-service-prod' deleted (resources retained)
```

#### Хуки жизненного цикла удаления: PreDelete и PostDelete
- **PreDelete (v3.3+):** Запускает Job перед началом удаления ресурсов (например, снятие трафика на балансировщике, создание финального дампа БД в MinIO). Сбой Job переводит приложение в статус `DeletionError` и блокирует снятие финализатора.
- **PostDelete (v2.10+):** Запускается после успешного удаления всех ресурсов (отправка отчета в аудит, очистка внешних DNS-записей).

## Диагностика и устранение неполадок

### Таблица типичных сбоев и решений

| Симптом / Ошибка | Первопричина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| `ComparisonError: rpc error: context deadline exceeded` | Таймаут генерации манифестов в `argocd-repo-server` (тяжелый Helm/Kustomize). | `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server` | Увеличить `repo.server.timeout.seconds` (по дефолту 90s) в `argocd-cm` до 180s. Выделить repo-server больше CPU/RAM. |
| Бесконечный цикл `OutOfSync` при `selfHeal: true` | Мутирующий вебхук кластера или сторонний оператор меняет поля объекта (HPA, cert-manager). | `argocd app diff <app-name>` | Настроить секцию `ignoreDifferences` в манифесте `Application` для конфликтующих JSON-путей. Переключиться на `ServerSideApply=true`. |
| `Authentication failed for repository` | Протух SSH-ключ, не настроен `known_hosts` или отозван GitLab Access Token. | `argocd repo get <repo-url>` | Обновить учетные данные в секрете репозитория. Добавить публичный ключ хоста в `argocd-ssh-known-hosts-cm`. |
| `SharedResourceWarning` | Один и тот же ресурс управляется двумя разными объектами `Application`. | `argocd app get <app-name>` | Использовать `FailOnSharedResource=true` в syncOptions. Разграничить владение ресурсами в структуре Git. |
| `DeletionError: finalizer could not be removed` | Завис или завершился с ошибкой `PreDelete` Job, либо завис сторонний финализатор пода. | `kubectl get jobs -n <app-namespace>` | Проверить логи сбойного Job, устранить причину сбоя либо вручную удалить Job. Снять финализатор только в экстренном случае. |
| `repo-server OOMKilled` | Нехватка оперативной памяти при параллельном рендеринге нескольких монорепозиториев. | `kubectl describe pod -n argocd -l app.kubernetes.io/name=argocd-repo-server` | Увеличить memory limit подов `argocd-repo-server`, включить масштабирование реплик HPA, активировать Shallow Git Cloning. |

### Пошаговые процедуры диагностики

#### 1. Анализ логов контроллера приложений
```bash
# Фильтрация ошибок синхронизации по конкретному приложению
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller \
  --tail=200 | grep -E "payment-service-prod|error|failed"
# → time="2026-10-12T14:41:10Z" level=error msg="Failed to sync: Deployment.apps payment-service is invalid"
```

#### 2. Проверка событий жизненного цикла
```bash
kubectl get events -n argocd --sort-by='.lastTimestamp' | tail -n 15
# → 2m   Warning   FailedSync   application/payment-service-prod   Failed to apply: field is immutable
```

#### 3. Сброс кэша рендеринга repo-server
Если в Git отправлен коммит, но Argo CD упорно видит старую версию:
```bash
# Перезапуск подов repo-server для сброса локального кэша
kubectl rollout restart deployment/argocd-repo-server -n argocd
# → deployment.apps/argocd-repo-server restarted

kubectl rollout status deployment/argocd-repo-server -n argocd
# → deployment "argocd-repo-server" successfully rolled out
```

### Мониторинг и SRE-метрики Prometheus

Argo CD экспортирует нативные метрики для Prometheus (сервер приложений `:8082`, repo-server `:8084`):

| Метрика | Тип | Описание и пороговые значения |
| :--- | :--- | :--- |
| `argocd_app_info` | Gauge | Текущий статус приложения: `health_status`, `sync_status`, `project`. База для большинства панелей и алертов. |
| `argocd_app_reconcile` | Histogram | Длительность выполнения сверки контроллером (SLA: p99 < 5s). Рост указывает на перегрузку K8s API или задержки etcd. |
| `argocd_app_sync_total` | Counter | Количество выполненных синхронизаций с разбивкой по фазам (`phase="Failed" / "Error" / "Succeeded"`). |
| `argocd_repo_pending_request_total`| Gauge | Количество запросов к repo-server, ожидающих в очереди. Рост > 10 сигнализирует о нехватке воркеров repo-server. |
| `argocd_git_request_duration_seconds` | Histogram | Время выполнения git-операций (fetch, clone, ls-remote). Мониторинг доступности Git-сервера. |

**Практические PromQL-запросы:**

```promql
# 1. Поиск приложений в аварийном состоянии Degraded
argocd_app_info{health_status="Degraded"} == 1

# 2. Определение доли сбойных синхронизаций за последние 15 минут
sum(rate(argocd_app_sync_total{phase=~"Failed|Error"}[15m]))
/
sum(rate(argocd_app_sync_total[15m])) * 100 > 10

# 3. 95-й перцентиль времени сверки приложений (сигнал о деградации производительности)
histogram_quantile(0.95, sum(rate(argocd_app_reconcile_bucket[5m])) by (le)) > 10
```

### Валидация и проверка работоспособности (Smoke Test)

После первичного развертывания или обновления выполняется проверочный цикл:

```bash
# 1. Проверка состояния всех кластеров
argocd cluster list
# → SERVER                          NAME        STATUS      MESSAGE
# → https://kubernetes.default.svc  in-cluster  Successful

# 2. Создание тестового приложения из репозитория примеров
argocd app create smoke-test-app \
  --repo https://github.com/argoproj/argocd-example-apps.git \
  --path guestbook \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace default

# 3. Синхронизация и проверка здоровья
argocd app sync smoke-test-app
# → Phase: Synced

argocd app wait smoke-test-app --health --timeout 60
# → App 'smoke-test-app' health is 'Healthy'

# 4. Удаление тестового приложения
argocd app delete smoke-test-app --cascade --yes
# → Application 'smoke-test-app' deleted
```

## Лучшие практики

### Производительность и масштабирование (SRE)

- **Шардирование контроллера (Controller Sharding):** При управлении более чем 500 приложениями или десятками кластеров разверните `argocd-application-controller` как StatefulSet с параметром `ARGOCD_CONTROLLER_SHARDING_ALGORITHM=round-robin` в `argocd-cmd-params-cm`. Контроллер автоматически распределит кластеры между шардами.
- **Отказ от агрессивного поллинга (Webhook-Driven Sync):** По умолчанию Argo CD опрашивает Git каждые 180 секунд (`timeout.reconciliation`). При тысячах репозиториев это создает колоссальную нагрузку на GitLab/Gitea. Настройте входящие вебхуки (`/api/webhook` на `argocd-server`) и увеличьте интервал поллинга до 1–2 часов.
- **Активация Server-Side Apply:** Используйте `ServerSideApply=true` для всех приложений. Это снимает лимит аннотации `kubectl.kubernetes.io/last-applied-configuration` (262 Кб) и предотвращает циклы перезаписи полей с внешними операторами.
- **Опция `ApplyOutOfSyncOnly=true`:** Обязательна для приложений с сотнями манифестов. Контроллер применяет изменения только к тем ресурсам, где зафиксирован drift, ускоряя синк в десятки раз.
- **Shallow Git Cloning (v3.3+):** Включите клонирование с фиксированной глубиной (`--depth=1`) для монорепозиториев с многолетней историей через флаг `server.repo.git.shallow.clone: "true"`.

### Безопасность и мультитенантность (Sysadmin)

- **Изоляция через AppProject:** Никогда не используйте проект `default` в production. Каждый проект команды должен явно декларировать:
  - Белый список репозиториев (`sourceRepos`);
  - Белый список пространств имен (`destinations`);
  - Разрешенные кластерные типы объектов (`clusterResourceWhitelist`).
- **Соблюдение принципа минимальных привилегий (RBAC):** Настройте ролевую модель в `argocd-rbac-cm` (`policy.csv`), связав роли с группами в корпоративном каталоге (Keycloak / FreeIPA / GitLab). Разделяйте права на чтение, синхронизацию и деструктивное удаление (`delete`).
- **Защита секретов в Git:** Категорически запрещено хранить незашифрованные секреты в Git. Применяйте:
  - **Bitnami Sealed Secrets** — шифрование асимметричным ключом кластера;
  - **Mozilla SOPS** — шифрование значений ключами PGP / HashiCorp Vault;
  - **HashiCorp Vault Secrets Operator / AVP** — инъекция секретов на лету.
- **Hardening контейнеров:** Контейнеры Argo CD должны функционировать под непривилегированным пользователем (`runAsNonRoot: true`, UID 999), с `readOnlyRootFilesystem: true` и строгими правилами `NetworkPolicy`, блокирующими несанкционированный межнодовый трафик.

### Эксплуатационные регламенты и ограничения

- **Окна синхронизации (Sync Windows):** Настройте запрещающие окна (`deny`) в `AppProject` на время пиковой нагрузки и нерабочие часы для production-окружений. В ветке v3.5+ используйте директиву `syncOverrun: true`, чтобы разрешить начавшейся синхронизации с длительными PreSync-миграциями БД корректно завершиться при закрытии окна.
- **Заморозка сверки (Skip Reconcile):** При проведении масштабных аварийных работ на кластере установите аннотацию `argocd.argoproj.io/skip-reconcile: "true"` на объект `Application` (или с v3.4 на секрет кластера), чтобы полностью остановить цикл сверки без удаления приложений.

## Дополнительная информация

### Интеграция с Argo Rollouts

Argo CD нативно дополняется контроллером **Argo Rollouts** для реализации прогрессивной доставки (подробное руководство см. в [Прогрессивная доставка в GitOps: Argo Rollouts и Flagger](../Concepts/progressive_delivery_gitops.md)):
- **Canary:** Постепенное перенаправление процента трафика через Ingress-контроллер (NGINX / Envoy) на новую версию с автоматическим анализом метрик Prometheus и самооткатом при росте HTTP 5xx.
- **Blue/Green:** Развертывание новой версии параллельно со старой и мгновенное переключение сервиса после ручного подтверждения или успешных smoke-тестов.

### Справочные руководства базы знаний

- [Установка и настройка Argo CD](./argocd_installation_and_setup.md) — пошаговое руководство по развертыванию Standalone и HA-контуров.
- [Паттерн App of Apps и структура GitOps-репозиториев](./argocd_app_of_apps.md) — иерархическое управление приложениями, бутстрап кластера и защита от каскадного удаления.
- [Интеграция с Kustomize](./kustomize_integration.md) — оверлеи, Components, флаги сборки LoadRestrictionsNone и рендеринг Helm-чартов.
- [Интеграция с Helm](./helm_integration.md) — особенности работы с Helm-чартами и OCI-репозиториями.
- [Прогрессивная доставка в GitOps: Argo Rollouts](../Concepts/progressive_delivery_gitops.md) — канареечные релизы, Blue/Green и анализ метрик через AnalysisTemplate.
- [Управление секретами и шифрование в GitOps](../secrets_encryption.md) — безопасное хранение секретов через SOPS, age, Sealed Secrets и ESO.
- [Диагностика и мониторинг](./argocd_troubleshooting_and_monitoring.md) — поиск неисправностей, алертинг Prometheus, разбор логов.
- [Синхронизация и политики](./synchronization.md) — архитектура Sync Waves, фаз выполнения и хуков жизненного цикла.
- [ApplicationSet — генераторы приложений](./argocd_applicationsets.md) — шаблонизация, генераторы List/Git/Cluster/Matrix, Progressive Sync.
- [AppProject — изоляция проектов](./argocd_appproject_deep.md) — границы безопасности, квоты, ограничения и проектные роли.
- [RBAC — модель доступа](./argocd_rbac_deep.md) — настройка `policy.csv`, встроенные и кастомные роли, токены доступа.
- [Multiple Sources и sourceHydrator](./argocd_multi_source_apps.md) — комбинация чартов Helm с оверлеями из Git.
- [Отслеживание ресурсов](./argocd_resource_tracking.md) — методы отслеживания объектов: Label, Annotation, миграция схем.
- [Удаление и очистка](./argocd_deletion_and_cleanup.md) — каскадное удаление, финализаторы, Prune-политики, PreDelete/PostDelete.
- [Disaster Recovery](./argocd_disaster_recovery.md) — процедуры резервного копирования, восстановление etcd и экспорт `argocd-util`.
- [Безопасность и hardening](./argocd_security_hardening.md) — NetworkPolicies, GPG-подписи коммитов, изоляция подов.
- [Мультитенантность](./argocd_multi_tenancy.md) — паттерны разделения кластеров и команд в крупных инфраструктурах.
- [Настройка уведомлений](./argocd_notifications.md) — алерты в Telegram, Slack, Webhook через Notifications Controller.
- [Настройка SSO через GitLab](./argocd_sso_gitlab.md) — интеграция Dex с корпоративным GitLab.
- [Custom Tooling и CMP](./argocd_custom_tooling.md) — плагины генерации манифестов Sidecar v2.
- [Argo CD Image Updater](./argocd_image_updater.md) — автоматизация обновления тегов образов из Harbor/Docker Registry.
- [Автоматизация через API и Ansible](./argocd_api_automation.md) — программное управление через REST/gRPC API.
- [Сравнение Argo CD и Flux](../argo_vs_flux_manifests.md) — сопоставление подходов и практических сценариев.

## Вопросы для собеседования

### В чем разница между паттерном App of Apps и ApplicationSet и когда что выбирать?
- **App of Apps** оперирует статическими манифестами `Application` в Git. Он обеспечивает максимальную гетерогенность (каждое приложение может использовать свой репозиторий, чарт, Kustomize-оверлей или CMP-плагин) и позволяет задавать строгую очередность развертывания через Sync Waves на манифестах `Application`. Основное назначение — первичный бутстрап кластера и развертывание разнородной инфраструктуры.
- **ApplicationSet** — динамический контроллер-генератор, создающий множество однотипных `Application` по единым шаблонам на основе внешних источников (список каталогов Git, метки кластеров, pull requests). Идеален для массовой доставки микросервисов по десяткам кластеров, но требует единообразия структуры приложений.

### Что произойдет при удалении корневого приложения в App of Apps и как защитить кластер?
Если на корневом приложении (`Root Application`) установлен финалайзер `resources-finalizer.argocd.argoproj.io`, команда `kubectl delete app root-app` вызовет немедленное каскадное удаление всех дочерних приложений и всех связанных с ними ресурсов во всем кластере.  
Для защиты production-окружений финалайзер на корневое приложение **никогда не устанавливается** (защищаются только дочерние приложения), а удаление при необходимости выполняется строго с флагом `--cascade=false`.

### Kustomize падает в Argo CD с ошибкой "security; file is not in or below current directory". В чем причина и как исправить?
По умолчанию Kustomize v5 запрещает загрузку манифестов и баз, расположенных выше директории оверлея (`../../base`), руководствуясь политикой безопасности `LoadRestrictionsRoot`.  
Для исправления в глобальном ConfigMap `argocd-cm` прописывается флаг:
`kustomize.buildOptions: "--load-restrictor LoadRestrictionsNone"`, после чего перезапускается под `argocd-repo-server`.

### Чем Server-Side Apply превосходит Client-Side Apply в GitOps и в каких случаях он критичен?
Client-Side Apply (CSA) вычисляет diff на клиенте (`kubectl`) и сохраняет полный снимок манифеста в аннотации `kubectl.kubernetes.io/last-applied-configuration`. Это создает две критические проблемы: ограничение размера аннотации (~262 Кб), что приводит к сбоям при деплое крупных CRD (например, операторов баз данных или систем мониторинга), и постоянные конфликты с контроллерами, мутирующими те же поля (HPA меняет `replicas`, вебхуки инжектируют sidecar-контейнеры).  
Server-Side Apply (SSA) переносит вычисление diff на сторону API-сервера Kubernetes и отслеживает владение каждым полем через структуру `managedFields`. Это снимает ограничение на размер аннотации, позволяет четко разделять права владения полями между Argo CD и кластерными операторами и разрешать конфликты на уровне декларации (`force-conflicts`). В Argo CD v3.x SSA является рекомендуемым стандартом по умолчанию.

### Что произойдет при экстренном Rollback через UI/CLI при включенных automated + selfHeal?
При выполнении отката через UI или команду `argocd app rollback` контроллер применяет манифесты указанной исторической ревизии. Однако состояние в кластере больше не совпадает с актуальным коммитом в ветке Git, поэтому приложение немедленно переходит в статус `OutOfSync`.  
Чтобы предотвратить затирание выполненного отката и возврат проблемной версии из Git, Argo CD **автоматически временно отключает политику автоматической синхронизации (`selfHeal`)** для данного конкретного приложения. Для завершения инцидента инженер обязан зафиксировать откат в Git через `git revert` и запушить коммит в репозиторий. После этого состояние Git и кластера выравнивается, и автосинхронизацию можно безопасно включить обратно.

### Какие методы Resource Tracking существуют и почему режим annotation предпочтителен для Helm?
Исторически Argo CD отслеживал принадлежность ресурсов через метку `app.kubernetes.io/instance: <app-name>`. Однако этот подход имеет два существенных недостатка: ограничение K8s на длину значения метки (не более 63 символов), что часто ломает деплой при длинных именах приложений, и конфликт с Helm-чартами, где метка `app.kubernetes.io/instance` по соглашению Helm зарезервирована под имя релиза чарта.  
Режим отслеживания по аннотации (`argocd.argoproj.io/tracking-id`) решает обе проблемы: аннотации не имеют ограничения в 63 символа, безопасно содержат полную иерархию `<app-name>:<group>/<kind>:<ns>/<name>` и не конфликтуют с механизмами Helm. В on-premise инфраструктурах режим `annotation` является стандартом.


### Как масштабировать контроллер Argo CD для управления тысячами приложений в крупном on-prem кластере?
Масштабирование контрольной плоскости выполняется по следующим направлениям:
1. **Шардирование контроллера:** Развертывание `argocd-application-controller` как StatefulSet с несколькими репликами с включенным шардированием (`ARGOCD_CONTROLLER_SHARDING_ALGORITHM=round-robin`). Контроллер динамически распределяет кластеры и приложения по шардам.
2. **Отказ от поллинга Git:** Настройка Git Webhooks (GitLab/Gitea) и увеличение интервала reconciliation loop со 180 секунд до нескольких часов.
3. **Оптимизация синхронизации:** Использование `ApplyOutOfSyncOnly=true`, чтобы контроллер не тратил ресурсы на повторное применение сотен неизменившихся объектов, и Shallow Git Cloning (`--depth=1`) для тяжелых монорепозиториев.
4. **Масштабирование repo-server:** Горизонтальное масштабирование реплик `argocd-repo-server` с достаточным объемом RAM и настройка высокодоступного кэша Redis HA Sentinel.

### Какова роль AppProject по сравнению с глобальным RBAC (policy.csv)?
Глобальный RBAC (`argocd-rbac-cm`, `policy.csv`) определяет, **кто** из пользователей или сервисных аккаунтов имеет право выполнять операции в системе (нажимать кнопки в UI, вызывать методы API `applications, sync, get, delete`).  
Ресурс `AppProject` реализует концепцию Defense-in-Depth и определяет границы того, **что** в принципе разрешено делать в рамках данного логического проекта, независимо от прав конкретного пользователя. `AppProject` задает жесткие белые списки целевых кластеров, разрешенных namespaces, Git-репозиториев и допустимых типов ресурсов K8s (`clusterResourceWhitelist`). Даже если пользователь наделен широкими правами в `policy.csv`, он не сможет применить манифест из чужого Git-репозитория или задеплоить привилегированный ClusterRole, если это не разрешено политикой его `AppProject`.

### Что происходит при сбое PreDelete-хука и как безопасно разблокировать удаление Application?
PreDelete-хук запускается перед началом удаления ресурсов приложения. Если Job хука завершается с ошибкой (`Exit Code != 0`) или зависает по таймауту, контроллер переводит `Application` в состояние `DeletionError` и **не снимает финализатор** `resources-finalizer.argocd.argoproj.io`. Это защитный механизм, предотвращающий уничтожение рабочих нагрузок в случае, когда обязательная операция подготовки (создание бэкапа, дренаж трафика) не удалась.  
Для устранения проблемы инженер должен исследовать логи упавшего Job (`kubectl logs job/<hook-job>`), исправить первопричину (сетевую доступность, учетные данные) и перезапустить Job. После успешного завершения Job контроллер снимет финализатор и удалит приложение. Ручное удаление финализатора (`kubectl patch app <name> --type json -p '[{"op": "remove", "path": "/metadata/finalizers"}]'`) допускается исключительно как крайняя мера, когда данные в кластере уже удалены или заархивированы вручную.
