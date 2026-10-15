# Crossplane: Управление ресурсами Kubernetes (provider-kubernetes)

**Актуально для:** Crossplane v2.x / provider-kubernetes v1.3.x; Kubernetes 1.28–1.32+; On-Premise / Bare-Metal

---

## Определения

**provider-kubernetes** — специализированный провайдер Crossplane (пакет `xpkg.upbound.io/crossplane-contrib/provider-kubernetes`), предназначенный для декларативного управления нативными и кастомными объектами Kubernetes (Namespaces, ConfigMaps, Secrets, Deployments, StatefulSets, CRD, Custom Resources) как внутри управляющего кластера (Control Plane), так и во внешних целевых кластерах через общий декларативный интерфейс.

**Object** — низкоуровневый управляемый ресурс (Managed Resource, MR) провайдера, инкапсулирующий произвольный манифест целевого объекта Kubernetes внутри поля `spec.forProvider.manifest`. Доступен в двух вариантах: кластерном (`kubernetes.crossplane.io/v1alpha1`) и пространствозависимом (`kubernetes.m.crossplane.io/v1beta1`).

**ProviderConfig** — конфигурационный ресурс провайдера (`kind: ProviderConfig`), определяющий сетевой эндпоинт целевого кластера, способ аутентификации (встроенный сервисный аккаунт `InjectedIdentity` либо ссылка на Kubernetes Secret с `kubeconfig`) и параметры взаимодействия с API-сервером.

**ClusterProviderConfig** — кластерный ресурс Crossplane v2 (`kind: ClusterProviderConfig`, API-группа `kubernetes.m.crossplane.io`), позволяющий пространствозависимым ресурсам `Object` ссылаться на единую общекластерную точку подключения без дублирования секретов по пространствам имен.

**Server-Side Apply (SSA)** — механизм применения конфигураций Kubernetes API (начиная с Kubernetes 1.18+), при котором вычисление различий, слияние полей и трекинг владения (Field Management) производятся на стороне `kube-apiserver`. Провайдер выступает менеджером полей с идентификатором `provider-kubernetes`.

**Management Policies (`spec.managementPolicies`)** — гранулярный перечень атомарных операций (`Create`, `Update`, `Delete`, `Observe`, `LateInitialize`), разрешенных контроллеру Crossplane над целевым ресурсом. Позволяет организовать безопасный импорт инфраструктуры, режим аудита (`ObserveOnly`) или предотвратить физическое удаление критичных ресурсов.

**DeletionPropagationPolicy (`spec.forProvider.deletionPropagationPolicy`)** — директива управления каскадным удалением зависимых дочерних ресурсов в целевом кластере (`Background`, `Foreground`, `Orphan`) при удалении объекта `Object`.

**Readiness Checks (`spec.readinessChecks`)** — декларативные правила оценки готовности целевого ресурса на основе анализа значений его `status`-полей (`MatchString`, `MatchCondition`, `MatchTrue`, `MatchFalse`, `NonEmpty`), транслируемые в условие `Ready` манифеста `Object`.

**ObservedObjectCollection** — ресурс провайдера (`kind: ObservedObjectCollection`), выполняющий пакетный сбор и агрегацию состояния набора однотипных объектов в целевом кластере в режиме только для чтения (инвентаризация и аудит).

**InjectedIdentity** — режим авторизации провайдера, при котором контроллер использует права собственного ServiceAccount внутри управляющего кластера через монтируемый проецируемый токен (TokenRequest API).

---

## Базовые концепции и архитектура

### Назначение и мультикластерная топология (Fleet Management)

В архитектуре корпоративной инфраструктуры без облачных провайдеров управляющий кластер Kubernetes (Management Cluster / Control Plane) выполняет роль единого центра оркестрации платформенных сервисов для парка рабочих кластеров (Fleet / Downstream Clusters — Bare-Metal, тестовые стенды, DMZ, Edge):

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    MANAGEMENT CONTROL PLANE (KUBERNETES)                        │
│                                                                                 │
│   GitOps (Argo CD / Flux) ────▶ kube-apiserver                                  │
│                                       │                                         │
│                      ┌────────────────┴────────────────┐                        │
│                      ▼                                 ▼                        │
│             Composite Resource (XR)        ProviderConfig / Secret              │
│                      │                       (kubeconfig / token)               │
│                      ▼                                 │                        │
│             Composition Pipeline                       │                        │
│                      │                                 │                        │
│                      ▼                                 ▼                        │
│             Object (Namespace, RBAC) ──▶ provider-kubernetes Controller        │
└──────────────────────────────────────────────────┬──────────────────────────────┘
                                                   │
                ┌──────────────────────────────────┴──────────────────┐
                │ gRPC / REST API (mTLS, Bearer Token)                │
                ▼                                                     ▼
┌───────────────────────────────────────────────┐ ┌───────────────────────────────┐
│           LOCAL CONTROL PLANE                 │ │      TARGET ON-PREM CLUSTER   │
│  (In-Cluster via InjectedIdentity)            │ │  (Downstream Cluster / Edge)  │
│                                               │ │                               │
│  - System Namespaces                          │ │  - Ingress Controllers        │
│  - ClusterRoles & Bindings                    │ │  - Monitoring Agents          │
│  - Local Platform CRDs                        │ │  - NetworkPolicies, Quotas    │
└───────────────────────────────────────────────┘ └───────────────────────────────┘
```

Ключевые сценарии использования:
- **Централизованное управление парком кластеров (Fleet Orchestration):** Декларативное развертывание базового платформенного стека (NetworkPolicy, LimitRange, ResourceQuota, DaemonSet агентов логирования и мониторинга, операторы) во все целевые кластеры из единого репозитория GitOps.
- **Инфраструктурные композиции платформы:** Включение инфраструктурных примитивов Kubernetes (базы данных операторов, служебные секреты, сервисные аккаунты) в состав Composite Resource Definitions (XRD) наряду с физическими серверами, сетевыми коммутаторами и хранилищами.
- **Импорт и инвентаризация без риска разрушения:** Подключение существующих системных кластеров в режиме `Observe` для отслеживания конфигурационного дрейфа без риска несанкционированной модификации или удаления ресурсов.

### Архитектура и цикл реконсиляции (Reconciliation Loop)

`provider-kubernetes` развертывается как Deployment в пространстве имен `crossplane-system`. Контроллер реализует непрерывный цикл реконсиляции:

1. **Обнаружение и чтение спецификации:** Информер контроллера отслеживает создание и модификацию ресурсов `Object`.
2. **Разрешение учетных данных:** Контроллер считывает `ProviderConfig`, на который ссылается `spec.providerConfigRef`. При источнике `InjectedIdentity` используются локальные учетные данные пода; при `Secret` — извлекается и валидируется `kubeconfig` целевого кластера.
3. **Инициализация динамического клиента:** Контроллер строит динамический REST-клиент и discovery-клиент Kubernetes к целевому API-серверу с поддержкой динамического кэширования схем OpenAPI и CRD.
4. **Server-Side Apply (SSA):** Контроллер отправляет вложенный манифест (`spec.forProvider.manifest`) на целевой API-сервер методом `PATCH` с заголовком `Content-Type: application/apply-patch+yaml` и параметром `fieldManager=provider-kubernetes`. Если обнаружен конфликт владения полями, контроллер может форсировать владение (`force=true`), если это задано политикой.
5. **Сбор статуса и оценка готовности:** Фактическое состояние целевого ресурса считывается и записывается в `status.atProvider.manifest`. Если в ресурсе объявлен блок `spec.readinessChecks`, контроллер выполняет инспекцию указанных полей и транслирует результат в статус `Ready=True/False`.

### Аутентификация и источники учетных данных

Провайдер поддерживает два механизма аутентификации (`spec.credentials.source`):

1. **`InjectedIdentity` (локальный кластер):**
   - Провайдер использует ServiceAccount собственного пода.
   - Взаимодействие осуществляется через стандартный projected volume (`/var/run/secrets/kubernetes.io/serviceaccount/token`).
   - Требует настройки локальных `ClusterRole` и `ClusterRoleBinding` для сервисного аккаунта провайдера.
2. **`Secret` (внешние и удаленные кластеры):**
   - Учетные данные считываются из Kubernetes Secret в управляющем кластере (`spec.credentials.secretRef`).
   - Значением секрета является валидный файл `kubeconfig` со статическим bearer-токеном сервисного аккаунта удаленного кластера либо с взаимными TLS-сертификатами (client-certificate-data и client-key-data).
   - **Важное архитектурное ограничение:** Контейнер `provider-kubernetes` работает в минималистичном изолированном окружении. Любые динамические CLI-плагины аутентификации (`exec`-секция в `kubeconfig`) **не поддерживаются**, так как соответствующие бинарные файлы отсутствуют в образе. Для подключения к удаленным кластерам следует использовать долгоживущие ServiceAccount-токены или автоматизировать ротацию статичных kubeconfig через External Secrets Operator и HashiCorp Vault.

### Области видимости и API-группы (Crossplane v2)

Архитектура Crossplane v2 разделяет API провайдера на два взаимодополняющих контура:

| Характеристика | Классический контур (Cluster-scoped) | Контур Crossplane v2 (Namespace-scoped MR) |
| --- | --- | --- |
| API-группа | `kubernetes.crossplane.io/v1alpha1` | `kubernetes.m.crossplane.io/v1beta1` |
| Область видимости `Object` | Кластерная (Cluster-wide) | Пространство имен (`Namespace-scoped`) |
| Назначение | Общесистемные ресурсы платформы, глобальный RBAC | Мультитенантная изоляция команд и сред |
| Конфигурация подключения | `ProviderConfig.kubernetes.crossplane.io` | `ProviderConfig` (в том же NS) или `ClusterProviderConfig` |
| Разрешение по умолчанию | `ProviderConfig/default` | `ClusterProviderConfig/default` |

### Политики управления жизненным циклом (Management Policies)

Управление ресурсом через `spec.managementPolicies` заменяет бинарную модель владения гибким списком атомарных привилегий контроллера:

| Политика | Действие контроллера `provider-kubernetes` |
| --- | --- |
| `All` (или `*`) | Полный жизненный цикл: Create, Update, Delete, Observe, LateInitialize (по умолчанию) |
| `Create` | Создание ресурса в целевом кластере при его отсутствии |
| `Update` | Синхронизация полей манифеста при обнаружении расхождений |
| `Delete` | Физическое удаление ресурса из целевого кластера при удалении `Object` |
| `Observe` | Периодическое чтение состояния ресурса без внесения изменений |
| `LateInitialize` | Дозаполнение неуказанных полей манифеста значениями, назначенными admission-контроллерами целевого кластера |

Политика `["Create", "Update", "Observe"]` позволяет создавать и непрерывно поддерживать ресурс, гарантируя, что случайное удаление CRD `Object` в управляющем кластере не приведет к удалению критически важного Namespace или базы данных в целевом окружении.

Политика `["Observe"]` реализует режим аудита (Observe-Only), гарантируя нулевое вмешательство в целевой кластер при постоянном мониторинге дрейфа.

### Политики каскадного удаления (DeletionPropagationPolicy)

Директива `spec.forProvider.deletionPropagationPolicy` определяет стратегию API-сервера целевого кластера при удалении составных объектов (Namespaces, Deployments, ReplicaSets):

- `Background` (по умолчанию): Объект удаляется немедленно, а фоновый Garbage Collector API-сервера асинхронно удаляет зависимые дочерние ресурсы.
- `Foreground`: Объект переводится в состояние удаления (`deletionTimestamp`), но физически не удаляется до тех пор, пока все дочерние ресурсы с блокирующими финализаторами не будут полностью уничтожены.
- `Orphan`: Объект удаляется, но все его дочерние ресурсы остаются нетронутыми в кластере (становятся сиротами).

---

## Практические сценарии и конфигурация

### Предварительные требования

- **Управляющий кластер (Management Cluster):** Kubernetes v1.28–1.32+ с развернутым ядром Crossplane v2.x (инструкция: [Обзор Crossplane](./overview.md)).
- **Пакетный менеджер:** Helm v3.12+ с включенной поддержкой OCI-реестров.
- **Сетевая связность:** Прямой сетевой доступ (L3/L4) из подов пространства имен `crossplane-system` управляющего кластера к API-серверам целевых кластеров (порт 6443 или балансировщик API).
- **Права доступа:** Начальные привилегии `cluster-admin` в управляющем и целевых кластерах для развертывания провайдера и первичной генерации сервисных учетных записей.

### Установка провайдера и настройка рантайма (DeploymentRuntimeConfig)

Для промышленной эксплуатации провайдера в SRE-практике обязательно создание `DeploymentRuntimeConfig`. Это позволяет зафиксировать лимиты памяти, политику планирования подов и настроить производительность цикла реконсиляции (`--max-reconcile-rate`):

```yaml
apiVersion: pkg.crossplane.io/v1beta1
kind: DeploymentRuntimeConfig
metadata:
  name: kubernetes-provider-runtime
spec:
  deploymentTemplate:
    spec:
      replicas: 1
      template:
        spec:
          containers:
            - name: package-runtime
              args:
                - --debug
                - --max-reconcile-rate=100
                - --poll=1m
              resources:
                requests:
                  cpu: 100m
                  memory: 256Mi
                limits:
                  cpu: 1000m
                  memory: 1Gi
---
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-kubernetes
spec:
  package: xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v1.3.0
  runtimeConfigRef:
    name: kubernetes-provider-runtime
```

Применение манифеста:

```bash
kubectl apply -f provider.yaml
# → deploymentruntimeconfig.pkg.crossplane.io/kubernetes-provider-runtime created
# → provider.pkg.crossplane.io/provider-kubernetes created
```

Проверка статуса установки и ревизии провайдера:

```bash
kubectl get providers
# → NAME                 INSTALLED  HEALTHY  PACKAGE                                                         AGE
#   provider-kubernetes  True       True     xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v1.3.0   45s

kubectl get providerrevisions
# → NAME                            HEALTHY   REVISION   IMAGE                                                           STATE    AGE
#   provider-kubernetes-a1b2c3d4e5   True      1          xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v1.3.0   Active   48s

kubectl -n crossplane-system get pods -l pkg.crossplane.io/provider=provider-kubernetes
# → NAME                                   READY   STATUS    RESTARTS   AGE
#   provider-kubernetes-a1b2c3d4e5-79b8f   1/1     Running   0          52s
```

### Сценарий 1: Локальное управление ресурсами (In-Cluster) с минимальными привилегиями

Для управления ресурсами внутри того же кластера, где работает Crossplane, категорически не рекомендуется использовать неизбирательный `cluster-admin`. Настроим ограниченную роль (Principle of Least Privilege).

**Шаг 1: Определение имени ServiceAccount провайдера и выпуск scoped RBAC:**

```bash
SA_NAME=$(kubectl -n crossplane-system get sa -o jsonpath='{.items[?(@.metadata.annotations.pkg\.crossplane\.io/package=="provider-kubernetes")].metadata.name}')
echo "ServiceAccount провайдера: ${SA_NAME}"
# → ServiceAccount провайдера: provider-kubernetes-a1b2c3d4e5
```

Создание целевой `ClusterRole` и `ClusterRoleBinding`:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: crossplane-provider-kubernetes-scoped
rules:
  - apiGroups: [""]
    resources: ["namespaces", "configmaps", "secrets", "serviceaccounts", "resourcequotas", "limitranges"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["networkpolicies", "ingresses"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["*"]
    resources: ["*"]
    verbs: ["get", "list", "watch"] # Только чтение для режима Observe
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: crossplane-provider-kubernetes-scoped-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: crossplane-provider-kubernetes-scoped
subjects:
  - kind: ServiceAccount
    name: provider-kubernetes-a1b2c3d4e5
    namespace: crossplane-system
```

Применение RBAC:

```bash
kubectl apply -f in-cluster-rbac.yaml
# → clusterrole.rbac.authorization.k8s.io/crossplane-provider-kubernetes-scoped created
# → clusterrolebinding.rbac.authorization.k8s.io/crossplane-provider-kubernetes-scoped-binding created
```

**Шаг 2: Создание локального ProviderConfig:**

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: ProviderConfig
metadata:
  name: default
spec:
  credentials:
    source: InjectedIdentity
```

```bash
kubectl apply -f providerconfig-default.yaml
# → providerconfig.kubernetes.crossplane.io/default created
```

### Сценарий 2: Мультикластерное управление парком on-premise кластеров (Multi-Cluster)

Настройка управления удаленным downstream-кластером (например, `worker-dc1`).

**Шаг 1: Создание ServiceAccount и выпуск токена в целевом удаленном кластере:**

На стороне удаленного целевого кластера:

```bash
# Создание сервисного аккаунта управления
kubectl create namespace platform-system
kubectl -n platform-system create serviceaccount crossplane-agent

# Привязка роли администратора платформы (или аналогичной scoped роли)
kubectl create clusterrolebinding crossplane-agent-binding \
  --clusterrole=cluster-admin \
  --serviceaccount=platform-system:crossplane-agent

# Создание статичного секрета с сервисным токеном
kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: crossplane-agent-token
  namespace: platform-system
  annotations:
    kubernetes.io/service-account.name: crossplane-agent
type: kubernetes.io/service-account-token
EOF
# → secret/crossplane-agent-token created
```

**Шаг 2: Сборка статического kubeconfig без плагинов:**

```bash
TARGET_API="https://k8s-worker-dc1.corp.internal:6443"
CA_DATA=$(kubectl -n platform-system get secret crossplane-agent-token -o jsonpath='{.data.ca\.crt}')
TOKEN_DATA=$(kubectl -n platform-system get secret crossplane-agent-token -o jsonpath='{.data.token}' | base64 --decode)

cat <<EOF > kubeconfig-worker-dc1.yaml
apiVersion: v1
kind: Config
clusters:
- cluster:
    certificate-authority-data: ${CA_DATA}
    server: ${TARGET_API}
  name: worker-dc1
contexts:
- context:
    cluster: worker-dc1
    user: crossplane-agent
  name: worker-dc1
current-context: worker-dc1
users:
- name: crossplane-agent
  user:
    token: ${TOKEN_DATA}
EOF
```

**Шаг 3: Сохранение секрета и настройка ProviderConfig в управляющем кластере:**

В управляющем кластере (Control Plane):

```bash
kubectl -n crossplane-system create secret generic cluster-worker-dc1-creds \
  --from-file=kubeconfig=kubeconfig-worker-dc1.yaml
# → secret/cluster-worker-dc1-creds created

rm -f kubeconfig-worker-dc1.yaml
```

Создание `ProviderConfig` для удаленного кластера:

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: ProviderConfig
metadata:
  name: worker-dc1
spec:
  credentials:
    source: Secret
    secretRef:
      namespace: crossplane-system
      name: cluster-worker-dc1-creds
      key: kubeconfig
```

```bash
kubectl apply -f providerconfig-worker-dc1.yaml
# → providerconfig.kubernetes.crossplane.io/worker-dc1 created
```

### Сценарий 3: Декларативное развертывание платформенных объектов (Object)

Создание изолированного пространства имен с квотами и тестовым приложением на удаленном кластере `worker-dc1`.

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: Object
metadata:
  name: prod-billing-ns
spec:
  # Запрет на физическое удаление пространства имен при удалении манифеста Object
  managementPolicies: ["Create", "Update", "Observe"]
  forProvider:
    manifest:
      apiVersion: v1
      kind: Namespace
      metadata:
        name: prod-billing
        labels:
          environment: production
          tier: platform
          managed-by: crossplane
  providerConfigRef:
    name: worker-dc1
---
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: Object
metadata:
  name: prod-billing-quota
spec:
  forProvider:
    manifest:
      apiVersion: v1
      kind: ResourceQuota
      metadata:
        name: compute-quota
        namespace: prod-billing
      spec:
        hard:
          requests.cpu: "4"
          requests.memory: 8Gi
          limits.cpu: "8"
          limits.memory: 16Gi
          pods: "20"
  providerConfigRef:
    name: worker-dc1
---
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: Object
metadata:
  name: prod-billing-nginx
spec:
  forProvider:
    deletionPropagationPolicy: Foreground
    manifest:
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: billing-proxy
        namespace: prod-billing
        labels:
          app: billing-proxy
      spec:
        replicas: 2
        selector:
          matchLabels:
            app: billing-proxy
        template:
          metadata:
            labels:
              app: billing-proxy
          spec:
            containers:
              - name: nginx
                image: harbor.corp.internal/library/nginx:1.26.2
                resources:
                  requests:
                    cpu: 100m
                    memory: 128Mi
                  limits:
                    cpu: 500m
                    memory: 256Mi
                ports:
                  - containerPort: 80
  providerConfigRef:
    name: worker-dc1
```

Применение и валидация статуса объектов:

```bash
kubectl apply -f platform-workloads.yaml
# → object.kubernetes.crossplane.io/prod-billing-ns created
# → object.kubernetes.crossplane.io/prod-billing-quota created
# → object.kubernetes.crossplane.io/prod-billing-nginx created

kubectl get objects
# → NAME                 SYNCED   READY   AGE
#   prod-billing-ns      True     True    12s
#   prod-billing-quota   True     True    11s
#   prod-billing-nginx   True     True    10s
```

### Сценарий 4: Совместная работа с GitOps (Server-Side Apply и разрешение конфликтов)

При совместном использовании Crossplane и GitOps-операторов (Argo CD, Flux) возникает потенциальный конфликт реконсиляции, если оба инструмента пытаются изменять одни и те же поля одного ресурса.

**Архитектурное решение через SSA:**
1. Провайдер применяет патчи через SSA с `fieldManager=provider-kubernetes`.
2. Если манифест `Object` задает только поля `spec.template.spec.containers[0].image` и лейблы, а HPA или Argo CD управляет `spec.replicas`, конфликта не возникает: `kube-apiserver` хранит раздельные списки владельцев полей в `metadata.managedFields`.
3. Если Argo CD пытается перезаписать поле, владельцем которого является `provider-kubernetes`, поведение зависит от настроек:
   - В Argo CD рекомендуется исключать ресурсы, находящиеся под управлением Crossplane (`resource.exclusions`), либо синхронизировать только сам манифест `Object`, а не дочерние объекты на целевых кластерах.
   - Проверка структуры владения полями в целевом кластере:

```bash
kubectl --kubeconfig=kubeconfig-worker-dc1.yaml -n prod-billing get deployment billing-proxy -o jsonpath='{.metadata.managedFields}' | jq .
# → [
#     {
#       "manager": "provider-kubernetes",
#       "operation": "Apply",
#       "apiVersion": "apps/v1",
#       "fieldsType": "FieldsV1",
#       "fieldsV1": { ... }
#     }
#   ]
```

### Сценарий 5: Настройка проверок готовности (Readiness Checks)

По умолчанию `Object` переходит в состояние `Ready=True`, как только целевой API-сервер подтвердил применение манифеста (HTTP 200/201). Для сложных контроллеров (Deployments, StatefulSets, Job, CRD) факт создания манифеста не означает готовность полезной нагрузки.

Блок `readinessChecks` позволяет задать точные критерии готовности:

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: Object
metadata:
  name: internal-valkey-cluster
spec:
  readinessChecks:
    # Проверка доступности необходимого числа реплик
    - type: MatchString
      fieldPath: "status.availableReplicas"
      matchString: "3"
    # Проверка условий контроллера в status.conditions
    - type: MatchCondition
      matchCondition:
        type: Available
        status: "True"
  forProvider:
    manifest:
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: valkey
        namespace: prod-billing
      spec:
        replicas: 3
        selector:
          matchLabels:
            app: valkey
        template:
          metadata:
            labels:
              app: valkey
          spec:
            containers:
              - name: valkey
                image: harbor.corp.internal/library/valkey:7.2.5
                ports:
                  - containerPort: 6379
  providerConfigRef:
    name: worker-dc1
```

Поддерживаемые типы проверок:
- `MatchString`: прямое сравнение строкового значения произвольного поля `fieldPath`.
- `MatchCondition`: поиск объекта условия в массиве условий (`status.conditions`) по типу `type` и значению `status`.
- `MatchTrue` / `MatchFalse`: проверка логического типа `boolean` в целевом поле.
- `NonEmpty`: подтверждение того, что поле существует и содержит непустое значение (удобно для ожидания генерации IP-адресов, токенов или сертификатов).
- `None`: ресурс считается готовым сразу после успешного применения.

### Сценарий 6: Интеграция в конвейер функций композиции (Composition Functions Pipeline)

В Crossplane v2 композиции строятся через конвейер вызова Composition Functions (`mode: Pipeline`). Фрагмент шаблона композиции на базе `function-patch-and-transform`, генерирующий локальный ServiceAccount и Secret с реквизитами доступа к внутренней СУБД:

```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: onprem-app-environment
spec:
  compositeTypeRef:
    apiVersion: platform.corp.internal/v1alpha1
    kind: XAppEnvironment
  mode: Pipeline
  pipeline:
    - step: patch-and-transform
      functionRef:
        name: function-patch-and-transform
      input:
        apiVersion: pt.fn.crossplane.io/v1beta1
        kind: Resources
        resources:
          - name: target-namespace
            base:
              apiVersion: kubernetes.crossplane.io/v1alpha1
              kind: Object
              spec:
                forProvider:
                  manifest:
                    apiVersion: v1
                    kind: Namespace
            patches:
              - type: FromCompositeFieldPath
                fromFieldPath: "spec.parameters.environmentName"
                toFieldPath: "spec.forProvider.manifest.metadata.name"
          - name: db-connection-secret
            base:
              apiVersion: kubernetes.crossplane.io/v1alpha1
              kind: Object
              spec:
                forProvider:
                  manifest:
                    apiVersion: v1
                    kind: Secret
                    type: Opaque
            patches:
              - type: FromCompositeFieldPath
                fromFieldPath: "spec.parameters.environmentName"
                toFieldPath: "spec.forProvider.manifest.metadata.namespace"
              - type: FromCompositeFieldPath
                fromFieldPath: "spec.parameters.secretName"
                toFieldPath: "spec.forProvider.manifest.metadata.name"
              - type: FromCompositeFieldPath
                fromFieldPath: "status.databaseCredentials.host"
                toFieldPath: "spec.forProvider.manifest.data.DB_HOST"
                transforms:
                  - type: string
                    string:
                      type: Convert
                      convert: ToBase64
```

### Сценарий 7: Мультитенантность и пространствозависимые объекты (Namespaced MR)

В мультикомандных окружениях платформенные инженеры делегируют создание ресурсов прикладным командам без выдачи кластерных прав. Использование `kubernetes.m.crossplane.io/v1beta1`:

**Шаг 1: Создание ClusterProviderConfig платформенными администраторами:**

```yaml
apiVersion: kubernetes.m.crossplane.io/v1beta1
kind: ClusterProviderConfig
metadata:
  name: shared-worker-dc1
spec:
  credentials:
    source: Secret
    secretRef:
      namespace: crossplane-system
      name: cluster-worker-dc1-creds
      key: kubeconfig
```

```bash
kubectl apply -f clusterproviderconfig.yaml
# → clusterproviderconfig.kubernetes.m.crossplane.io/shared-worker-dc1 created
```

**Шаг 2: Создание ресурса Object прикладной командой внутри своего Namespace (`team-payments`):**

```yaml
apiVersion: kubernetes.m.crossplane.io/v1beta1
kind: Object
metadata:
  name: payments-config
  namespace: team-payments
spec:
  providerConfigRef:
    name: shared-worker-dc1
    kind: ClusterProviderConfig
  forProvider:
    manifest:
      apiVersion: v1
      kind: ConfigMap
      metadata:
        name: service-runtime-cfg
        namespace: default
      data:
        LOG_LEVEL: debug
        CACHE_ENABLED: "true"
```

```bash
kubectl apply -f team-payments-object.yaml
# → object.kubernetes.m.crossplane.io/payments-config created

kubectl -n team-payments get objects.kubernetes.m.crossplane.io
# → NAME              SYNCED   READY   AGE
#   payments-config   True     True    14s
```

### Сценарий 8: Инвентаризация и аудит кластеров (ObservedObjectCollection и ObserveOnly)

Для проведения непрерывного соответствия стандартам (Compliance Audit) и инвентаризации конфигураций downstream-кластеров используется `ObservedObjectCollection`. Ресурс непрерывно агрегирует состояние внешних объектов без попытки их создания или модификации:

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: ObservedObjectCollection
metadata:
  name: audit-worker-dc1-namespaces
spec:
  providerConfigRef:
    name: worker-dc1
  apiVersion: v1
  kind: Namespace
```

```bash
kubectl apply -f audit-namespaces.yaml
# → observedobjectcollection.kubernetes.crossplane.io/audit-worker-dc1-namespaces created

kubectl describe observedobjectcollection audit-worker-dc1-namespaces
# → Status:
#     At Provider:
#       Objects:
#         - Api Version:  v1
#           Kind:         Namespace
#           Metadata:
#             Name:       default
#             Status:     Active
#         - Api Version:  v1
#           Kind:         Namespace
#           Metadata:
#             Name:       kube-system
#             Status:     Active
```

---

## Диагностика и устранение неполадок (Troubleshooting)

### Команды диагностики и трассировки

Просмотр общего статуса и синхронизации управляемых объектов:

```bash
kubectl get objects
# → NAME                 SYNCED   READY   STATUS    AGE
#   prod-billing-ns      True     True    Active    5m
#   prod-billing-nginx   False    False   Pending   45s
```

Детальный анализ событий жизненного цикла ресурса и ошибок API-сервера:

```bash
kubectl describe object prod-billing-nginx
```

Сквозная трассировка графа реконсиляции через утилиту Crossplane CLI:

```bash
crossplane alpha trace object prod-billing-nginx
# → NAME                                     SYNCED   READY   STATUS
#   Object/prod-billing-nginx (default)      False    False   ReconcileError
#   └─ Deployment/billing-proxy (worker-dc1) -        -       ImagePullBackOff
```

Анализ логов пода провайдера в режиме отладки (фильтрация по подсистеме реконсиляции):

```bash
kubectl -n crossplane-system logs -l pkg.crossplane.io/provider=provider-kubernetes -c package-runtime --tail=100 -f
```

Проверка состояния и условий ревизии пакета провайдера:

```bash
kubectl describe providerrevision -l pkg.crossplane.io/provider=provider-kubernetes
```

### Типовые проблемы и способы решения

| Симптом | Вероятная причина | Диагностика | Решение |
| --- | --- | --- | --- |
| `Object` зависает в `Synced=False` с ошибкой `cannot apply object: ... forbidden` | Недостаточно прав у ServiceAccount в локальном или удаленном кластере | `kubectl describe object <name>` в секции `Events` содержит конкретный недостающий RBAC verb/resource | Добавить недостающие API-группы и ресурсы в `ClusterRole` сервисного аккаунта агента (обязательно проверить verb `patch` для SSA) |
| Ошибка `dial tcp ... connect: connection refused` или `i/o timeout` | Сетевая изоляция между управляющим кластером и API-сервером удаленного кластера | Проверить сетевую доступность из пода провайдера: `kubectl -n crossplane-system exec -it <pod> -- nc -zv <target-ip> 6443` | Настроить маршрутизацию, правила сетевых экранов (Firewall/Security Groups) или проверить работу балансировщика Kubernetes API |
| Постоянный дрейф и конфликт полей с Argo CD / Flux (`apply conflict`) | Контроллер GitOps и `provider-kubernetes` одновременно пытаются управлять одним и тем же полем манифеста | Выполнить `kubectl get <resource> -o yaml` и проанализировать блок `metadata.managedFields` | Разделить зоны ответственности: исключить дочерние ресурсы из синхронизации GitOps, либо убрать конфликтующие поля из манифеста `Object` |
| Ошибка `exec: executable not found in $PATH` при попытке подключения | В `kubeconfig` указан динамический плагин авторизации (`exec`-секция) | Проверить манифест секрета: `kubectl -n crossplane-system get secret <name> -o jsonpath='{.data.kubeconfig}' \| base64 -d` | Сгенерировать статичный `kubeconfig` с долгоживущим ServiceAccount-токеном или TLS-сертификатом без внешних утилит |
| `Object` зависает в `Ready=False` при успешном `Synced=True` | Не выполняются условия блока `readinessChecks` (например, поды падают в CrashLoopBackOff) | Проверить статус ресурса в целевом кластере: `kubectl describe deployment <name>` | Устранить причину сбоя целевой рабочей нагрузки (исправить конфигурацию контейнера, Secret, ConfigMap) или скорректировать правила `readinessChecks` |
| Удаление `Object` зависает бесконечно | Зависший финализатор (`crossplane.io/external-resource-evaluator`) из-за недоступности целевого кластера | `kubectl get object <name> -o jsonpath='{.metadata.finalizers}'` | Восстановить сетевой доступ к целевому кластеру. При аварийном выводе кластера из эксплуатации: снять финализатор вручную через `kubectl patch object <name> -p '{"metadata":{"finalizers":null}}' --type=merge` |
| Ошибка `cannot parse manifest: no matches for kind ... in version ...` | В целевом кластере отсутствуют необходимые CRD на момент создания ресурса `Object` | Проверить наличие CRD в целевом кластере: `kubectl get crd <crd-name>` | Убедиться, что оператор или CRD развернуты в целевом кластере до создания экземпляров кастомных ресурсов |
| Высокая утилизация памяти и OOMKilled пода провайдера | Большое количество управляемых объектов (>1000) при стандартных лимитах памяти | `kubectl -n crossplane-system describe pod -l pkg.crossplane.io/provider=provider-kubernetes` фиксирует статус `OOMKilled` | Увеличить `resources.limits.memory` до 2–4Gi в `DeploymentRuntimeConfig` и оптимизировать интервал опроса `--poll` |

---

## Рекомендации и лучшие практики (Best Practices)

### Безопасность и разграничение прав доступа (RBAC)

1. **Отказ от неизбирательного `cluster-admin`:** Для локального управления используйте узконаправленные `ClusterRole`, включающие только разрешенные API-группы инфраструктуры платформы. Запрещайте провайдеру доступ к узлам (`nodes`), сертификатам кластера (`certificates.k8s.io`) и системным пространствам имен (`kube-system`).
2. **Пространствозависимая изоляция (Namespaced Scope):** В мультиарендных платформах переводите команды разработки на пространствозависимый API `kubernetes.m.crossplane.io/v1beta1`. Это исключает возможность случайного воздействия одной команды на манифесты другой команды на уровне управляющего кластера.
3. **Аудит сетевого периметра:** Для удаленных downstream-кластеров минимизируйте число открытых эндпоинтов API-серверов. Разрешайте подключения к API только с фиксированных egress IP-адресов нод управляющего кластера.

### Производительность и тюнинг контроллеров (SRE & Scale)

1. **Тюнинг темпа реконсиляции (`--max-reconcile-rate`):** По умолчанию контроллер обрабатывает ограниченное количество очередей в секунду. При управлении сотнями объектов увеличьте этот параметр до `50–100` через `DeploymentRuntimeConfig`, чтобы избежать задержек распространения изменений.
2. **Настройка интервала опроса (`--poll`):** Стандартный интервал сверки составляет 1 минуту (`--poll=1m`). Если парк кластеров превышает десятки инстансов, увеличьте интервал до `3m` или `5m`, чтобы снизить нагрузку на целевые etcd-кластеры и предотвратить троттлинг со стороны API-серверов.
3. **Горизонтальное шардирование:** Для распределения нагрузки между сотнями кластеров развертывайте отдельные экземпляры `ProviderConfig` с привязкой к разным репликам провайдера или выделенным управляющим контурам.

### Гигиена Server-Side Apply и GitOps

1. **Разделение зон ответственности:** Никогда не управляйте одними и теми же скалярными полями ресурса из двух разных систем автоматизации. Если Crossplane создает базовый манифест Deployment, отдайте управление количеством реплик (`spec.replicas`) исключительно Horizontal Pod Autoscaler (HPA), исключив `spec.replicas` из манифеста `Object` после инициализации.
2. **Фиксация версий API:** Всегда указывайте точную и актуальную версию `apiVersion` во вложенных манифестах `spec.forProvider.manifest`. Избегайте устаревших версий API (например, `extensions/v1beta1`), чтобы не создавать избыточную нагрузку на конверсионные вебхуки API-сервера.

### Управление секретами и жизненный цикл kubeconfig

1. **Запрет хранения секретов в открытом виде в Git:** Манифесты Kubernetes Secret, содержащие `kubeconfig` удаленных кластеров, ни при каких условиях не должны попадать в репозитории в незашифрованном виде. Используйте HashiCorp Vault в связке с External Secrets Operator (ESO) для автоматической генерации и инъекции секретов в пространство имен `crossplane-system`.
2. **Плановая ротация токенов:** Включайте процедуру периодической ротации сервисных токенов удаленных кластеров без простоя. Новые токены выпускаются параллельно со старыми, обновляются в Secret через ESO, после чего старый токен аннулируется.

### Безопасный вывод из эксплуатации (Cleanup)

1. **Защита критичных данных от удаления:** Для инфраструктурных компонентов, содержащих состояние (PersistentVolumeClaims, StatefulSets, системные Namespaces), всегда устанавливайте политику:
   ```yaml
   spec:
     managementPolicies: ["Create", "Update", "Observe"]
   ```
   Это гарантирует, что при удалении манифеста `Object` из GitOps физические данные и тома в целевом кластере сохранятся.
2. **Корректный порядок вывода:** При плановом выводе кластера из управления сначала переведите все зависимые ресурсы `Object` в режим `managementPolicies: ["Observe"]`, затем удалите `ProviderConfig`, и только после этого отзывайте сервисные токены и сетевые доступы.

---

## Дополнительная информация

Внутренние разделы базы знаний:
- [Обзор Crossplane](./overview.md) — фундаментальные концепции, архитектура Composition Functions и рантайм провайдеров.
- [Интеграция с GitOps](./gitops_integration.md) — архитектура совместной работы с Argo CD и Flux, управление секретами и Server-Side Apply.
- [Мультитенантность в Crossplane](./multi_tenancy.md) — проектирование изолированных платформ на базе namespace-scoped MR и ClusterProviderConfig.
- [Observability и мониторинг Crossplane](./observability.md) — метрики Prometheus, мониторинг очередей контроллеров и алертинг.
- [Управление парком кластеров (Fleet Management)](./fleet_management.md) — ClusterProviderConfig, мультикластерный топология, CAPI-паттерны поверх provider-kubernetes.
- [Backup и Disaster Recovery Crossplane](./backup_dr.md) — резервное копирование etcd, стратегии защиты от каскадного удаления и аварийное восстановление.
- [Управление секретами в GitOps](../secrets_encryption.md) — организация безопасного хранения kubeconfig и учетных данных через SOPS и External Secrets Operator.

Официальные внешние ресурсы:
- [Документация provider-kubernetes](https://github.com/crossplane-contrib/provider-kubernetes) — официальный репозиторий проекта и документация пакета.
- [Server-Side Apply в provider-kubernetes](https://github.com/crossplane-contrib/provider-kubernetes/blob/main/docs/server-side-apply.md) — спецификация механизма слияния полей и управления конфликтами.
- [Руководство по Crossplane v2](https://docs.crossplane.io/) — официальная документация архитектуры Crossplane v2.
