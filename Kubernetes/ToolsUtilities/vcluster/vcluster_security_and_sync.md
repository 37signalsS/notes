# vCluster — безопасность и синхронизация

> Документ покрывает модель безопасности vCluster: изоляцию тенантов, Pod Security Standards, RBAC для Syncer, Network Policies, нативную синхронизацию CRD (Generic Sync), CEL-патчи, Rootless Mode и Namespace 1:1. Архитектура Syncer и общий обзор — в [vcluster_overview.md](./vcluster_overview.md), установка и режимы развёртывания — в [vcluster_installation.md](./vcluster_installation.md), сетевой доступ и публикация API — в [vcluster_connectivity.md](./vcluster_connectivity.md).

## Определения

**Pod Security Admission (PSA)** — встроенный механизм Kubernetes (v0.35+ полностью интегрирован в vCluster), позволяющий применять стандарты безопасности (Privileged, Baseline, Restricted) на уровне виртуального кластера. Автоматически блокирует запуск небезопасных подов внутри vCluster.

**ResourceQuota (Ресурсные квоты)** — объект в хост-кластере, ограничивающий суммарное потребление ресурсов (CPU, RAM, количество объектов) пространством имен, в котором работает vCluster.

**LimitRange (Диапазоны ограничений)** — политика внутри vCluster, устанавливающая значения по умолчанию и границы для ресурсов подов тенанта.

**Generic Sync (Нативная синхронизация CRD)** — механизм (v0.35+), позволяющий декларативно синхронизировать произвольные Custom Resource Definitions (например, Cert-Manager, Istio) между виртуальным и хостовым окружениями без внешних плагинов.

**Sync Patches (CEL-патчи)** — инструмент модификации ресурсов "на лету" при синхронизации, использующий Common Expression Language (CEL). Позволяет динамически изменять поля объектов (например, добавлять префиксы к именам секретов) при их переносе на хост.

**Namespace 1:1 Syncing** — режим работы, при котором пространства имен внутри vCluster отображаются в хост-кластер без изменения имен (no rewriting), что упрощает работу инструментов безопасности и мониторинга.

**Rootless Mode (Безрутовый режим)** — запуск компонентов vCluster с минимальными привилегиями (non-root UID/GID) для минимизации рисков при потенциальном взломе контейнера.

**Syncer ServiceAccount (Сервис-аккаунт синхронизатора)** — служебный SA, под которым работает Syncer в хост-кластере. Через него vCluster получает права на создание/изменение теневых объектов (pods, services, ingresses) в своём namespace хоста. По умолчанию создаётся автоматически, но может быть переопределён через `controlPlane.serviceAccount`.

**Tenant (Тенант)** — пользователь, команда или проект, использующий отдельный vCluster. Изоляция тенантов — основная задача модели безопасности vCluster: один тенант не должен иметь возможность влиять на workload-поды, данные или RBAC другого тенанта.

**Isolated Control Plane (Изолированный Control Plane)** — режим (включается флагом `networking.isolatedControlPlane.enabled`), при котором Syncer автоматически генерирует NetworkPolicy, запрещающие workload-подам vCluster обращаться к API хост-кластера и наоборот.

**Multi-namespace Sync (Много-неймспейс синхронизация)** — режим, при котором все namespace виртуального кластера отображаются в **один** namespace хоста (по умолчанию) с префиксом `vcluster-<name>-`. Альтернатива Namespace 1:1.

**PSP (Pod Security Policy)** — устаревший механизм (удалён в Kubernetes v1.25), заменён на PSA. vCluster никогда не использовал PSP внутри; интегрируется только с современным PSA.

**CIS Kubernetes Benchmark** — набор рекомендаций по безопасности от Center for Internet Security. vCluster при правильной конфигурации (`podSecurityStandard: restricted`, `runAsNonRoot: true`, Network Policies) помогает соответствовать большинству требований CIS для multi-tenant кластеров.

**Service Account Token Volume Projection (Projected SA Token)** — механизм (v1.20+), при котором токен SA монтируется в под как projected volume с ограниченным сроком жизни (по умолчанию 1 час) и аудитом. vCluster использует его для всех внутренних SA.

**OPA Gatekeeper / Kyverno** — внешние policy-движки, которые могут работать **поверх** vCluster на уровне хост-кластера. Не заменяют, а дополняют встроенные `policies` в `vcluster.yaml`. Допустимо использовать совместно.

**Backing Store Access Policy** — политика доступа к etcd (или внешнему Kine) из Syncer. В default конфигурации Syncer работает в одной поде с etcd, доступ через localhost; внешний Backing Store требует отдельной секретной авторизации.

**Reverse Proxy (Обратный прокси) внутри vCluster** — компонент, через который Syncer обращается к API виртуального кластера. По умолчанию прокси работает в privilege-режиме (нужен доступ к поду kube-apiserver). Может быть вынесен в отдельный `kube-vip`-style sidecar.

## Основные концепции

### Векторы синхронизации

Синхронизатор (Syncer) управляет потоками данных между плоскостями:

1.  **toHost (vCluster → Host):** Репликация подов, сервисов и маршрутов. Syncer создает "теневые" объекты на хосте для фактического исполнения нагрузки.
2.  **fromHost (Host → vCluster):** Импорт инфраструктурных ресурсов (StorageClasses, Nodes, ClusterIssuers). Позволяет тенантам использовать ресурсы физического кластера.

#### Подробная матрица `toHost` ресурсов (v0.35+)

| Ресурс | По умолчанию | Особенности синхронизации |
| :--- | :--- | :--- |
| `pods` | enabled | Синхронизируются как обычные Pod'ы хоста, scheduling через хост-scheduler. |
| `services` | enabled | ClusterIP/NodePort остаются, LoadBalancer — опционально трансформируется. |
| `endpoints` | enabled | Конечные точки сервисов. |
| `configmaps` | enabled | Доступны read-only и read-write. |
| `secrets` | enabled | Шифруются at-rest на стороне хоста (если включено). |
| `persistentvolumeclaims` | enabled | Создаются в namespace хоста с префиксом. |
| `events` | enabled | Локальные события vCluster остаются в виртуальном кластере. |
| `ingresses` | enabled | Поддержка как Ingress API, так и Gateway API. |
| `networkpolicies` | enabled | Генерируются автоматически при `policies.networkPolicy.enabled=true`. |
| `serviceaccounts` | enabled | SA создаётся в namespace хоста, в виртуальный кластер пробрасывается токен. |
| `crds` | opt-in | Generic Sync — синхронизация любых CRD (cert-manager, istio и т.д.). |
| `priorityclasses` | opt-in | Полезно для приоритизации multi-tenant подов. |

#### Подробная матрица `fromHost` ресурсов (v0.35+)

| Ресурс | По умолчанию | Когда включать |
| :--- | :--- | :--- |
| `nodes` | enabled | Всегда — для корректного планирования и Auto Nodes. |
| `storageclasses` | enabled | Всегда — для динамического provisioning. |
| `ingressclasses` | enabled | При использовании Ingress в виртуальном кластере. |
| `priorityclasses` | opt-in | Если используются хост-классом приоритеты. |
| `csinodes` | opt-in | При наличии CSI-драйверов, которые тенант должен видеть. |
| `volumeattachments` | opt-in | Редко; при миграции PV между namespace. |
| `clusterissuers.cert-manager.io` | opt-in | При централизованном cert-manager на хосте. |
| `customResources` | opt-in | Generic Sync — любой CRD с хоста. |

### Изоляция и стандарты безопасности (PSS)

vCluster v0.35+ поддерживает автоматическое применение **Pod Security Standards**. При установке уровня `restricted` в конфигурации, виртуальный API-сервер будет отклонять любые запросы на создание подов, не соответствующих жестким требованиям безопасности (запрет root, hostPath, привилегий).

#### Сравнение профилей PSS для vCluster

| Профиль | Запрет root | Запрет hostPath | readOnlyRootFS | seccompProfile | drop ALL caps | Когда использовать |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `privileged` | Нет | Нет | Нет | Нет | Нет | Никогда для tenant-кластеров. |
| `baseline` | Да (ограниченно) | Нет (с ограничениями) | Нет | Нет | Частично | Миграция legacy workloads. |
| `restricted` | Да | Да | Да | RuntimeDefault | Да | Production multi-tenancy. |

> **Предупреждение:** применение `restricted` может сломать существующие workload'ы тенанта. Паттерн безопасного перехода: `audit → warn → enforce`. vCluster поддерживает это через `policies.podSecurityStandard` в `vcluster.yaml`, но фактическая миграция требует участия разработчиков.

### Динамическая модификация (Resource Patching)

Патчи позволяют адаптировать ресурсы виртуального кластера под требования хоста.
- **Маскировка имен:** Добавление уникальных суффиксов к именам ресурсов для предотвращения коллизий.
- **Изменение типов:** Например, принудительное преобразование `LoadBalancer` в `ClusterIP` при синхронизации на хост для экономии публичных IP.
- **Инъекция Sidecar:** Добавление агентов мониторинга или безопасности во все синхронизируемые поды.

#### Типы патчей в vCluster

| Тип | Синтаксис | Применение |
| :--- | :--- | :--- |
| **value** | `value: "literal-string"` | Статическая подстановка. |
| **expression** | `expression: 'CEL-expression'` | Динамическая модификация через CEL. |
| **reverseExpression** | `reverseExpression: 'CEL'` | Модификация при обратной синхронизации (fromHost → vCluster). |
| **reference** | `reference: "path.to.field"` | Копирование значения из другого поля объекта. |

### Сетевая изоляция и NetworkPolicies

vCluster может автоматически генерировать `NetworkPolicies` на хосте, которые:
- Разрешают трафик только между компонентами одного vCluster.
- Изолируют Control Plane от подов тенанта.
- Блокируют доступ подов vCluster к API-серверу хост-кластера (`isolatedControlPlane`).

#### Автогенерируемые NetworkPolicy при `policies.networkPolicy.enabled=true`

| Политика | Назначение | Направление |
| :--- | :--- | :--- |
| `allow-vcluster-<name>` | Разрешает pod-to-pod внутри vCluster. | Ingress внутри namespace. |
| `allow-host-to-vc` | Разрешает Syncer ↔ kube-apiserver vCluster. | Host → vCluster. |
| `deny-vc-to-host-api` | Блокирует workload'ам vCluster доступ к API хоста. | Egress vCluster → host API. |
| `allow-vc-dns` | Разрешает DNS-запросы (kube-dns/CoreDNS). | Egress на :53. |
| `deny-other-namespaces` | Default-deny на другие namespace. | Ingress/Egress. |

> **Важно:** на хосте должен быть CNI-плагин с поддержкой NetworkPolicy (Calico, Cilium, Weave). Kindnet и flannel (без addon) **не** поддерживают NetworkPolicy — автогенерация не сработает.

## Практические сценарии

### Настройка безопасности и квот в vcluster.yaml (v0.35+)

Централизованное управление стандартами безопасности и ресурсными ограничениями.

```yaml
# vcluster.yaml
policies:
  # Применение Pod Security Standards (Restricted по умолчанию)
  podSecurityStandard: restricted
  
  # Автоматическая генерация NetworkPolicies для изоляции
  networkPolicy:
    enabled: true
    
  # Ресурсные квоты на уровне неймспейса хоста
  resourceQuota:
    enabled: true
    quota:
      requests.cpu: "4"
      requests.memory: 8Gi
      pods: "50"
      
  # Лимиты по умолчанию внутри vCluster
  limitRange:
    enabled: true
    default:
      cpu: 500m
      memory: 512Mi
```

### Настройка нативной синхронизации CRD (Generic Sync)

Синхронизация объектов `cert-manager` с использованием CEL-патчей для предотвращения конфликтов.

```yaml
# vcluster.yaml
sync:
  toHost:
    customResources:
      certificates.cert-manager.io:
        enabled: true
        patches:
          - path: spec.secretName
            # Добавление префикса к имени секрета на хосте
            expression: '"v-secret-" + value'
      issuers.cert-manager.io:
        enabled: true
  fromHost:
    customResources:
      clusterissuers.cert-manager.io:
        enabled: true
```

### Использование CEL-патчей для модификации ресурсов

Пример изменения типа сервиса и добавления метаданных при синхронизации.

```yaml
# vcluster.yaml
sync:
  toHost:
    services:
      enabled: true
      patches:
        - path: metadata.annotations["managed-by"]
          value: "vcluster-prod"
        - path: spec.type
          # Преобразование LoadBalancer в ClusterIP для экономии ресурсов хоста
          expression: 'value == "LoadBalancer" ? "ClusterIP" : value'
```

### Сетевая изоляция и Rootless Mode

Максимальное ужесточение безопасности для Control Plane.

```yaml
# vcluster.yaml
controlPlane:
  backingStore:
    etcd:
      embedded: true
  statefulSet:
    securityContext:
      runAsUser: 10000
      runAsNonRoot: true
      
networking:
  # Блокировка доступа к API хост-кластера для подов vCluster
  isolatedControlPlane:
    enabled: true
```

### Расширенный пример `policies` для production

Полный набор security-политик для критичных workloads (финтех, healthcare, on-prem с compliance-требованиями).

```yaml
# vcluster.yaml
policies:
  # Pod Security Standards — самый строгий
  podSecurityStandard: restricted
  
  # Автогенерация NetworkPolicy
  networkPolicy:
    enabled: true
    # Запретить весь egress за пределы vCluster
    denyAllEgress: false  # true для максимальной изоляции
  
  # ResourceQuota — на уровне namespace хоста
  resourceQuota:
    enabled: true
    quota:
      requests.cpu: "8"
      requests.memory: 16Gi
      limits.cpu: "16"
      limits.memory: 32Gi
      pods: "100"
      persistentvolumeclaims: "20"
      services: "50"
      secrets: "100"
      configmaps: "100"
  
  # LimitRange — внутри vCluster
  limitRange:
    enabled: true
    default:
      cpu: 1
      memory: 1Gi
      ephemeral-storage: 1Gi
    defaultRequest:
      cpu: 100m
      memory: 128Mi
    max:
      cpu: 4
      memory: 8Gi
    min:
      cpu: 50m
      memory: 64Mi
    maxLimitRequestRatio:
      cpu: "10"
      memory: "4"
  
  # Image policy — только из разрешённых registry
  imagePolicy:
    allowedRegistries:
      - "registry.corp.local"
      - "ghcr.io/loft-sh"
      - "registry.k8s.io"
  
  # ReadOnly root filesystem по умолчанию
  readOnlyRootFilesystem: true
  
  # Запрет привилегированных подов
  disallowPrivileged: true
  
  # Запрет host namespaces
  disallowHostNamespaces: true
```

### RBAC для Syncer (минимизация прав)

По умолчанию Syncer получает ClusterRole. В production рекомендуется ограничить Scope.

```yaml
# vcluster.yaml
controlPlane:
  serviceAccount:
    # Использовать pre-existing SA с минимальными правами
    name: "vcluster-syncer-prod"
    create: false
  # Явно указать namespace для теневых объектов
  namespace: "vcluster-prod"
```

```yaml
# --- Применяется отдельно в namespace vcluster-prod ---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: vcluster-syncer-prod
  namespace: vcluster-prod
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: vcluster-syncer-role
  namespace: vcluster-prod
rules:
  # Полный доступ к ресурсам, которые Syncer синхронизирует в этот namespace
  - apiGroups: [""]
    resources: ["pods", "services", "endpoints", "configmaps", "secrets", "events", "serviceaccounts", "persistentvolumeclaims"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses", "networkpolicies"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets", "replicasets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["policy"]
    resources: ["poddisruptionbudgets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["autoscaling"]
    resources: ["horizontalpodautoscalers"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: vcluster-syncer-binding
  namespace: vcluster-prod
subjects:
  - kind: ServiceAccount
    name: vcluster-syncer-prod
    namespace: vcluster-prod
roleRef:
  kind: Role
  name: vcluster-syncer-role
  apiGroup: rbac.authorization.k8s.io
```

> **Предупреждение:** не добавляйте `pods/exec`, `pods/portforward`, `pods/log` в `verbs` — Syncer не должен иметь доступа к shell workloads тенантов.

### Namespace 1:1 Syncing — включение

По умолчанию все namespace vCluster маппятся в один namespace хоста с префиксом `vcluster-<name>-`. Namespace 1:1 режим сохраняет оригинальные имена.

```yaml
# vcluster.yaml
sync:
  # Включение 1:1 режима для tenant namespaces
  namespacePrefix: ""
  # Альтернативный синтаксис для v0.34+
  mapping:
    namespaceMapping:
      # Все namespace vCluster → те же namespace на хосте
      enabled: true
```

Когда использовать:
- Подключение внешних систем безопасности (Falco, Sysdig) — им проще работать с едиными именами.
- Миграция с namespace-scoped инструментов (старые NetworkPolicy, RBAC манифесты).
- На хосте уже есть namespace, которые должны совпадать с namespace vCluster.

Когда **не** использовать:
- Один namespace на хосте уже занят другим vCluster.
- Количество namespace >50 — не масштабируется на один namespace хоста (лимиты NetworkPolicy, RBAC объектов).

### CEL-патчи: продвинутые примеры

#### Префиксация имён всех секретов (изоляция между vCluster)

```yaml
# vcluster.yaml
sync:
  toHost:
    secrets:
      enabled: true
      patches:
        - path: metadata.name
          expression: '"vc-" + object.metadata.labels["vcluster.loft.sh/name"] + "-" + value'
```

#### Удаление sensitive annotations при синхронизации

```yaml
# vcluster.yaml
sync:
  toHost:
    pods:
      enabled: true
      patches:
        # Удалить аннотации, которые не должны "утекать" на хост
        - path: metadata.annotations["vault.hashicorp.com/agent-inject-secret"]
          expression: '""'
        - path: metadata.annotations["vault.hashicorp.com/agent-inject-template"]
          expression: '""'
```

#### Трансформация storage class на хост

```yaml
# vcluster.yaml
sync:
  toHost:
    persistentvolumeclaims:
      enabled: true
      patches:
        # Маппинг dev→fast-ssd, prod→premium-ssd
        - path: spec.storageClassName
          expression: 'value == "default" ? "fast-ssd" : value'
```

#### Стрип лейблов при обратной синхронизации (fromHost → vCluster)

```yaml
# vcluster.yaml
sync:
  fromHost:
    nodes:
      enabled: true
      patches:
        # Удалить host-специфичные лейблы, чтобы не путать тенант
        - path: metadata.labels["node.kubernetes.io/instance-type"]
          expression: '""'
        # Переименовать для ясности
        - path: metadata.labels["topology.kubernetes.io/zone"]
          expression: '"dc-zone-" + value'
```

### Полный манифест NetworkPolicy для изоляции одного vCluster

Ручная альтернатива `policies.networkPolicy.enabled=true` — для случаев, когда нужен полный контроль над правилами.

```yaml
# networkpolicy-vcluster-prod.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: vcluster-prod-isolation
  namespace: vcluster-prod
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Разрешить только внутри namespace + от Syncer/Control Plane
    - from:
        - podSelector: {}
        - namespaceSelector:
            matchLabels:
              vcluster.loft.sh/parent: vcluster-prod
      ports:
        - protocol: TCP
          port: 8443  # kube-apiserver vCluster
        - protocol: TCP
          port: 53
        - protocol: UDP
          port: 53
  egress:
    # DNS наружу
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # Доступ к API хоста (только Syncer-у)
    - from:
        - namespaceSelector:
            matchLabels:
              vcluster.loft.sh/parent: vcluster-prod
      to:
        - namespaceSelector: {}
      ports:
        - protocol: HTTPS
          port: 6443
    # Блокировка всего остального (по умолчанию deny)
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except:
              - 10.0.0.0/8  # внутренние сети — block
              - 172.16.0.0/12
              - 192.168.0.0/16
```

### Цепочка PSA: безопасное применение `restricted` на существующем vCluster

```bash
# 1. Аудит текущего состояния (только логирование нарушений)
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: team-alpha-existing
  labels:
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/audit-version: latest
EOF

# 2. Проверить события audit за последние 24 часа
kubectl get events -n team-alpha-existing --field-selector reason=FailedCreate | grep -i "restricted"

# 3. Если нарушений мало — warn (разработчики видят предупреждения)
kubectl label namespace team-alpha-existing \
  pod-security.kubernetes.io/warn=restricted \
  pod-security.kubernetes.io/warn-version=latest \
  --overwrite

# 4. Через 1-2 недели (после исправления всеми командами) — enforce
kubectl label namespace team-alpha-existing \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/enforce-version=latest \
  --overwrite
```

### Multi-tenant изоляция: Host-based с NetworkPolicy

```yaml
# cluster-wide-vcluster-policies.yaml
---
# Deny-all по умолчанию для всех vCluster namespaces
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: vcluster-team-alpha
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
---
# Разрешить только intra-namespace + DNS
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-intra-namespace
  namespace: vcluster-team-alpha
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - podSelector: {}
  egress:
    - to:
        - podSelector: {}
    # DNS
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - protocol: UDP
          port: 53
```

### Pod Security Standards внутри vCluster — `vcluster.yaml` политики

```yaml
# vcluster.yaml
policies:
  podSecurityStandard: restricted
  # Дополнительные настройки, переопределяющие дефолты PSS
  podSecurity:
    enforce: "restricted"
    enforceVersion: "latest"
    audit: "restricted"
    auditVersion: "latest"
    warn: "restricted"
    warnVersion: "latest"
    exemptions:
      # Список системных SA, на которые PSA не распространяется
      usernames:
        - "system:serviceaccount:vcluster-system:*"
```

## Лучшие практики безопасности

- **Принудительное использование PSA:** Всегда устанавливайте `podSecurityStandard: restricted` для недоверенных тенантов. Это предотвращает запуск контейнеров с привилегиями root и доступ к хостовой ФС.
- **Минимизация RBAC для Syncer:** Избегайте использования `ClusterRole` для vCluster. Ограничивайте права синхронизатора только необходимым набором в целевом неймспейсе. Используйте `controlPlane.serviceAccount.name` для подключения SA с минимальными правами.
- **Включение сетевой изоляции:** Используйте `policies.networkPolicy.enabled` для автоматического создания политик, блокирующих межкластерный трафик и доступ к метаданным облачного провайдера.
- **Namespace 1:1 Syncing:** Используйте этот режим, если ваши инструменты безопасности (например, Falco или Sysdig) требуют соответствия имен неймспейсов между виртуальным и хостовым слоями.
- **Изоляция хранилищ:** При импорте `PersistentVolumes` через `fromHost` убедитесь, что политики доступа запрещают одному vCluster монтировать тома, принадлежащие другому виртуальному кластеру.

#### Чек-лист hardening для production vCluster

| Уровень | Контроль | Реализация | Приоритет |
| :--- | :--- | :--- | :--- |
| **Поды** | Запрет root | `policies.podSecurityStandard: restricted` | Критический |
| **Поды** | readOnly root FS | PSA `restricted` (по умолчанию) | Критический |
| **Поды** | Seccomp RuntimeDefault | PSA `restricted` | Высокий |
| **Поды** | drop ALL capabilities | PSA `restricted` | Высокий |
| **Syncer** | Минимальный RBAC (Role) | `controlPlane.serviceAccount.create: false` + custom Role | Критический |
| **Syncer** | Отдельный namespace на хосте | Не использовать `default` | Критический |
| **Control Plane** | Rootless Mode | `runAsUser: 10000, runAsNonRoot: true` | Высокий |
| **Control Plane** | NetworkPolicy (isolated) | `networking.isolatedControlPlane.enabled: true` | Высокий |
| **Control Plane** | etcd encryption at-rest | K8s KMS provider на хосте | Средний |
| **API** | OIDC/SSO | `vcluster connect` + `oidc.issuer` | Высокий |
| **API** | Audit log | kube-apiserver `--audit-log-*` | Критический |
| **API** | mTLS до vCluster | Front-proxy с cert-manager | Средний |
| **Network** | Default-deny | `policies.networkPolicy.enabled: true` | Критический |
| **Network** | Egress filtering | NetworkPolicy `egress` | Высокий |
| **Storage** | Изоляция PV | StorageClass per-tenant + RBAC | Высокий |
| **Observability** | Audit logs | `vcluster describe` + хост audit | Высокий |
| **Compliance** | CIS Benchmark | Запустить `kube-bench` против хост-кластера | Средний |

## Диагностика проблем безопасности и синхронизации

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `forbidden: cannot create pods in namespace` | RBAC Syncer ограничен `Role`, недостаточно прав. | Расширить `verbs` или ресурсы в Role. |
| `ImagePullBackOff` после `podSecurityStandard: restricted` | Образ запускается от root, PSA блокирует. | Пересобрать образ с `USER 1000` или добавить exemption. |
| `NetworkPolicy: 0生效` (политика не действует) | CNI не поддерживает NetworkPolicy (flannel без addon). | Перейти на Calico/Cilium или убрать `networkPolicy.enabled`. |
| `forbidden: exceeds quota` | ResourceQuota на namespace заполнена. | Увеличить quota или удалить неиспользуемые поды. |
| `CEL expression failed: unknown field` | Опечатка в `path`, либо поле отсутствует в v0.34. | Проверить путь через `kubectl get ... -o yaml`; см. release notes. |
| `vcluster create` падает с `clusterrolebindings forbidden` | Syncer требует ClusterRole (не Role) при первом создании. | При первом создании разрешить `create: true`; затем переключить на `create: false`. |
| Поды vCluster не могут подключиться к внешним сервисам | NetworkPolicy default-deny блокирует egress. | Разрешить egress в NetworkPolicy или отключить `denyAllEgress`. |
| Generic Sync не работает для CRD | CRD не установлен на хосте, либо `apiVersion` не совпадает. | Установить CRD на хосте, проверить `apiVersions` в CRD spec. |
| `metadata.annotations[...]` patch — invalid path | Старая версия vCluster (до v0.31) не поддерживает bracket syntax. | Обновить vCluster ≥ v0.31. |
| `podSecurityStandard: restricted` ломает legacy workloads | Наследие с `runAsUser: 0`. | Использовать `audit` + `warn` режим 1-2 недели, потом enforce. |
| Syncer логирует `TLS handshake error` | `kube-apiserver` перевыпустил CA после upgrade vCluster. | `kubectl -n <ns> delete pod -l app=vcluster` (форсирует рестарт). |
| Namespace 1:1 — `namespaces "x" already exists` | На хосте уже есть namespace с таким именем. | Включить `namespacePrefix` или выбрать другое имя. |
| `quota exhausted` через несколько минут после `vcluster create` | `policies.resourceQuota` не задан, Syncer потребляет ресурсы быстрее. | Задать `policies.resourceQuota.quota` явно. |

#### Команды для диагностики безопасности

```bash
# Проверить, какие PSA-метки установлены
kubectl get ns <vcluster-ns> -o jsonpath='{.metadata.labels}{"\n"}' | grep pod-security

# Посмотреть, какие NetworkPolicy сгенерированы автоматически
kubectl get networkpolicy -n <vcluster-ns> -l vcluster.loft.sh/auto-generated=true

# Аудит Syncer RBAC
kubectl auth can-i create pods --as=system:serviceaccount:<vcluster-ns>:vcluster-syncer -n <vcluster-ns>
# → yes/no

# Проверить активные PSA-нарушения (audit mode)
kubectl get events -n <vcluster-ns> --field-selector reason=FailedCreate | grep -i "restricted"

# Список патчей, применённых к синхронизированному ресурсу
kubectl get pod <pod-name> -n <host-ns> -o jsonpath='{.metadata.annotations}{"\n"}' | grep vcluster

# Проверка, что Syncer не имеет cluster-admin
kubectl auth can-i '*' '*' --as=system:serviceaccount:<vcluster-ns>:vcluster-syncer
# → no
```

## Очистка

```bash
# Полное удаление vCluster (с RBAC, NetworkPolicy, RB)
vcluster delete my-vc -n my-namespace

# Удаление без PVC (для последующего восстановления)
vcluster delete my-vc -n my-namespace --keep-pvc

# Удаление сгенерированных NetworkPolicy (если autogen не сработал)
kubectl delete networkpolicy -n <vcluster-ns> -l vcluster.loft.sh/auto-generated=true

# Удаление RBAC, созданного Syncer
kubectl delete clusterrolebinding,rolebinding,role,serviceaccount -n <vcluster-ns> -l app=vcluster

# Принудительная очистка namespace
kubectl delete namespace <vcluster-ns> --force --grace-period=0
```

> Все операции идемпотентны. При повторном `vcluster delete` ошибок не возникает, ресурсы, отсутствующие в кластере, игнорируются.

## Дополнительная информация

### Внутренние ссылки

- [vCluster — обзор и архитектура](./vcluster_overview.md)
- [vCluster — установка и развертывание](./vcluster_installation.md)
- [vCluster — подключение и доступ](./vcluster_connectivity.md)

### См. также

- [Security Context в Kubernetes](../Security/pod_security_context.md) — детали PSA и PSS.
- [Мульти-тенантность в Kubernetes](../Concepts/multi-tenancy.md) — общие подходы к изоляции.

### Внешние ссылки

- [vCluster Security Documentation](https://www.vcluster.com/docs/architecture/security)
- [Resource Syncing and Patches](https://www.vcluster.com/docs/config/sync/overview)
- [Common Expression Language (CEL) in Kubernetes](https://kubernetes.io/docs/reference/using-api/cel/)
