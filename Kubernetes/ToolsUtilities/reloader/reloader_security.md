# Reloader — Безопасность и hardening

## Определения

**Безопасность Reloader** — совокупность мер по защите контроллера автоматической перезагрузки конфигураций от несанкционированного доступа, ограничению радиуса поражения при компрометации и соответствию требованиям комплаенса. Фокус — на Reloader-специфичных аспектах; общие принципы безопасности Kubernetes (RBAC, NetworkPolicy, Pod Security Standards) описаны в [Kubernetes/Security](../../Security/).

**Основной источник:** [Обзор Reloader](./reloader_overview.md)

---

## Основные концепции

### Модель угроз Reloader

Reloader обладает уникальным набором привилегий, которые делают его целью для атак:

```text
┌───────────────────────────────────────────────────────────────┐
│                   Модель угроз Reloader                       │
├───────────────────────────────────────────────────────────────┤
│ 1. Чтение всех ConfigMap/Secret в отслеживаемых namespace    │
│ 2. Запись (patch) к Deployment/StatefulSet/DaemonSet         │
│ 3. Доступ к API Server для watch-событий                     │
│ 4. Возможность инициирования массовых перезапусков           │
│ 5. Доступ к Secrets Store CSI (при включенной интеграции)    │
└───────────────────────────────────────────────────────────────┘
```

**Ключевой риск:** Если Reloader скомпрометирован, атакующий может:
- Прочитать любые Secret в отслеживаемых namespace
- Инициировать массовый restart всех подов (DoS)
- Изменить конфигурацию подов через patch Deployment
- Получить доступ к внешним хранилищам секретов через CSI

### Принцип наименьших привилегий для Reloader

В отличие от generic RBAC-рекомендаций, для Reloader критически важно:

1. **Scoped Roles вместо ClusterRole** — ограничение конкретными namespace
2. **Однонаправленный доступ** — только чтение ConfigMap/Secret, только patch к workload
3. **Исключение системных namespace** — `kube-system`, `kube-public`, `kube-node-lease`
4. **Изоляция между tenant** — отдельный Reloader на tenant или strict namespace filtering

---

## Практические сценарии

### Сценарий 1: Scoped RBAC для мультитенантного кластера

**Задача:** Каждый tenant (команда) имеет свой namespace. Reloader должен отслеживать только его.

**ClusterRole (общий шаблон):**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: reloader-role
rules:
  - apiGroups: [""]
    resources: ["secrets", "configmaps"]
    verbs: ["list", "get", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "daemonsets", "statefulsets"]
    verbs: ["list", "get", "watch", "update", "patch"]
  - apiGroups: ["argoproj.io"]
    resources: ["rollouts"]
    verbs: ["list", "get", "watch", "update", "patch"]
  - apiGroups: ["secrets-store.csi.x-k8s.io"]
    resources: ["secretproviderclasspodstatuses"]
    verbs: ["list", "get", "watch"]
```

**Role для конкретного tenant (рекомендуется):**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: reloader-tenant-role
  namespace: team-alpha
rules:
  - apiGroups: [""]
    resources: ["secrets", "configmaps"]
    verbs: ["list", "get", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "daemonsets", "statefulsets"]
    verbs: ["list", "get", "watch", "update", "patch"]
```

**RoleBinding для tenant:**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: reloader-tenant-binding
  namespace: team-alpha
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: reloader-tenant-role
subjects:
  - kind: ServiceAccount
    name: reloader
    namespace: reloader-system
```

**Валидация:**

```bash
# Проверка прав в конкретном namespace
kubectl auth can-i patch deployments \
  --as=system:serviceaccount:reloader-system:reloader \
  -n team-alpha
# → result: yes

# Проверка, что доступ ОГРАНИЧЕН (не должен работать в другом tenant)
kubectl auth can-i patch deployments \
  --as=system:serviceaccount:reloader-system:reloader \
  -n team-beta
# → result: no
```

### Сценарий 2: NetworkPolicy для контроллера Reloader

**Задача:** Ограничить сетевой доступ контроллера только до API Server и целевых namespace.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: reloader-network-policy
  namespace: reloader-system
spec:
  podSelector:
    matchLabels:
      app: reloader
  policyTypes:
    - Egress
    - Ingress
  # Входящий трафик — только healthcheck и metrics
  ingress:
    - ports:
        - protocol: TCP
          port: 9090
  # Исходящий трафик — только API Server и DNS
  egress:
    # DNS
    - ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # Kubernetes API Server
    - to:
        - ipBlock:
            cidr: 10.0.0.0/8  # CIDR API Server
      ports:
        - protocol: TCP
          port: 443
    # Secrets Store CSI Driver (если включена интеграция)
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              app: secrets-store-csi-driver
      ports:
        - protocol: TCP
          port: 9808
```

### Сценарий 3: Pod Security Standards для namespace Reloader

**Задача:** Применить строгие политики безопасности к namespace контроллера.

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: reloader-system
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/audit: restricted
```

**Требования для `restricted` уровня (важно для манифестов Reloader):**

```yaml
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 65534
    runAsGroup: 65534
    fsGroup: 65534
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: reloader
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
```

**Валидация:**

```bash
# Проверка PSA-меток на namespace
kubectl get ns reloader-system -o jsonpath='{.metadata.labels}' | jq .

# Проверка, что поды соответствуют политике
kubectl label ns reloader-system pod-security.kubernetes.io/warn=restricted --dry-run=server
```

### Сценарий 4: Supply Chain Security (OCI Artifact Signing)

**Задача:** Верифицировать подпись образа Reloader перед деплоем.

**Проверка подписи через Cosign:**

```bash
# Установка Cosign
go install github.com/sigstore/cosign/v2/cmd/cosign@latest

# Верификация подписи официального образа
cosign verify ghcr.io/stakater/reloader:v1.4.19 \
  --certificate-identity-regexp="https://github.com/stakater/Reloader" \
  --certificate-oidc-issuer="https://token.actions.githubusercontent.com"
# → result: The following checks were performed:
#   - The claims were verified against the signature on the certificate

# Верификация SBOM
cosign verify-attestation ghcr.io/stakater/reloader:v1.4.19 \
  --type spdxjson \
  --certificate-identity-regexp="https://github.com/stakater/Reloader" \
  --certificate-oidc-issuer="https://token.actions.githubusercontent.com"
```

**Интеграция с Kyverno (автоматическая проверка):**

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-reloader-image
spec:
  validationFailureAction: Enforce
  rules:
    - name: check-image-signature
      match:
        any:
          - resources:
              kinds:
                - Pod
      validate:
        message: "Reloader image must be signed by Stakater"
        imagePattern: "ghcr.io/stakater/reloader:*"
        verifyImages:
          - imageReferences:
              - "ghcr.io/stakater/reloader:*"
            attestors:
              - entries:
                  - keyless:
                      issuer: "https://token.actions.githubusercontent.com"
                      rekor:
                        url: https://rekor.sigstore.dev
                      subjectRegExp: "https://github.com/stakater/Reloader"
```

### Сценарий 5: Изоляция в мультитенантной среде

**Задача:** Один Reloader на несколько tenant, с полной изоляцией данных.

**Метод 1: Namespace Selector (рекомендуется):**

```bash
helm install reloader stakater/reloader \
  --namespace reloader-system \
  --set reloader.watchGlobally=false \
  --set reloader.namespaces='{team-alpha,team-beta,production}'
```

**Метод 2: Несколько экземпляров Reloader (максимальная изоляция):**

```yaml
# Production Reloader — только production namespace
apiVersion: apps/v1
kind: Deployment
metadata:
  name: reloader-prod
  namespace: reloader-prod
spec:
  template:
    spec:
      containers:
        - name: reloader
          args:
            - --namespaces-to-select=production
            - --reload-strategy=annotations
---
# Team-Alpha Reloader — только namespace team-alpha
apiVersion: apps/v1
kind: Deployment
metadata:
  name: reloader-alpha
  namespace: reloader-alpha
spec:
  template:
    spec:
      containers:
        - name: reloader
          args:
            - --namespaces-to-select=team-alpha
            - --reload-strategy=annotations
```

**Валидация изоляции:**

```bash
# Проверка, что reloader-prod не видит team-alpha
kubectl logs -n reloader-prod -l app=reloader | grep team-alpha
# → result: (пусто — нет событий из team-alpha)

# Проверка相反ного
kubectl logs -n reloader-alpha -l app=reloader | grep production
# → result: (пусто)
```

### Сценарий 6: OPA/Gatekeeper для контроля аннотаций Reloader

**Задача:** Разрешить использование Reloader только в определённых namespace и запретить `auto`-режим для критических сервисов.

```yaml
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: k8sreloaderpolicy
spec:
  crd:
    spec:
      names:
        kind: K8sReloaderPolicy
      validation:
        openAPIV3Schema:
          type: object
          properties:
            allowedNamespaces:
              type: array
              items:
                type: string
            disallowAutoForCritical:
              type: boolean
  targets:
    - target: admission.k8s.gatekeeper.sh
      rego: |
        package k8sreloaderpolicy

        violation[{"msg": msg}] {
          input.review.object.metadata.annotations["reloader.stakater.com/auto"] == "true"
          not input.review.object.metadata.namespace in input.parameters.allowedNamespaces
          msg := sprintf("Reloader auto mode is not allowed in namespace %v", [input.review.object.metadata.namespace])
        }

        violation[{"msg": msg}] {
          input.parameters.disallowAutoForCritical
          input.review.object.metadata.labels["critical"] == "true"
          input.review.object.metadata.annotations["reloader.stakater.com/auto"] == "true"
          msg := "Critical workloads cannot use auto mode; use explicit annotations"
        }
---
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sReloaderPolicy
metadata:
  name: reloader-restrictions
spec:
  match:
    kinds:
      - apiGroups: ["apps"]
        kinds: ["Deployment", "StatefulSet", "DaemonSet"]
  parameters:
    allowedNamespaces:
      - production
      - staging
      - dev
    disallowAutoForCritical: true
```

---

## Дополнительная информация

### Чек-лист безопасности перед production

- [ ] RBAC: Scoped Role (не ClusterRole) для каждого tenant
- [ ] NetworkPolicy: Ограничение egress только API Server + DNS
- [ ] Pod Security Standards: `restricted` для namespace reloader-system
- [ ] Security Context: `runAsNonRoot`, `readOnlyRootFilesystem`, `drop: ["ALL"]`
- [ ] Supply Chain: Верификация подписи образа (Cosign)
- [ ] Namespace Filtering: `--namespaces-to-select` или `--namespaces-to-ignore`
- [ ] Audit Logging: Включение аудита Kubernetes API для отслеживания patch-операций
- [ ] OPA/Gatekeeper: Политики контроля аннотаций Reloader

### Связанные темы

- [RBAC — управление доступом](../../Security/rbac/rbac_overview.md) — общие принципы RBAC в Kubernetes
- [NetworkPolicy — сетевая безопасность](../../Security/network_policies.md) — микросегментация и Zero Trust
- [Pod Security Standards](../../Base/namespace.md#безопасность-pod-security-admission) — PSA на уровне namespace
- [Falco — runtime security](../../Security/Tools/falco.md) — мониторинг аномалий в контейнерах
- [Incident Response в Kubernetes](../../Security/incident_response.md) — реагирование на инциденты
