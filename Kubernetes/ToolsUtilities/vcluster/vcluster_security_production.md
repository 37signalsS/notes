# vCluster — безопасность на продакшне

> Документ описывает расширенные аспекты безопасности vCluster: интеграция с OPA/Kyverno, управление секретами, аудит, CIS Benchmark, compliance. Базовая безопасность — в [vcluster_security_and_sync.md](./vcluster_security_and_sync.md), мониторинг — в [vcluster_monitoring.md](./vcluster_monitoring.md).

## Определения

**OPA Gatekeeper** — policy-engine для Kubernetes, реализующий Rego-политики как Admission Webhook. Блокирует нарушения политик до создания объектов.

**Kyverno** — policy-engine для Kubernetes, использующий YAML-политики вместо Rego. Интегрируется с CRD Kubernetes.

**External Secrets Operator (ESO)** — контроллер, синхронизирующий секреты из внешних хранилищ (Vault, AWS Secrets Manager) в Kubernetes Secrets.

**Vault** — система управления секретами от HashiCorp. Хранит, генерирует и ротирует секреты с динамическими credentials.

**CIS Benchmark** — набор рекомендаций по безопасности от Center for Internet Security. Включает проверки RBAC, сетевой безопасности, логирования.

**Admission Webhook** — компонент, перехватывающий запросы к API-серверу Kubernetes и проверяющий их на соответствие политикам.

**Audit Log** — журнал всех запросов к API-серверу. Критичен для compliance (PCI DSS, HIPAA, ФЗ-152).

**Secret Store CSI Driver** — драйвер, монтирующий секреты из внешних хранилищ (Vault, AWS) как volume в поды.

## Основные концепции

### Архитектура безопасности vCluster

```text
┌─────────────────────────────────────────────────────────────────┐
│                    Host Cluster                                  │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ OPA Gatekeeper / Kyverno (на хосте)                         │ │
│  │   └── Admission Webhook для проверки политик               │ │
│  └─────────────────────────────────────────────────────────────┘ │
│         │                                                       │
│         ▼                                                       │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ vCluster Namespace: team-alpha                               │ │
│  │                                                              │ │
│  │  ┌──────────────────────────────────────────────────────┐   │ │
│  │  │ Control Plane                                         │   │ │
│  │  │   ├── kube-apiserver (audit-log, OIDC)               │   │ │
│  │  │   ├── etcd (encryption at-rest)                      │   │ │
│  │  │   └── Syncer (RBAC, NetworkPolicy)                   │   │ │
│  │  └──────────────────────────────────────────────────────┘   │ │
│  │                                                              │ │
│  │  ┌──────────────────────────────────────────────────────┐   │ │
│  │  │ External Secrets Operator                             │   │ │
│  │  │   └── синхронизация секретов из Vault                │   │ │
│  │  └──────────────────────────────────────────────────────┘   │ │
│  │                                                              │ │
│  │  ┌──────────────────────────────────────────────────────┐   │ │
│  │  │ Tenant Pods                                           │   │ │
│  │  │   ├── PSA: restricted                                 │   │ │
│  │  │   └── readOnlyRootFilesystem: true                    │   │ │
│  │  └──────────────────────────────────────────────────────┘   │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Практические сценарии

### Интеграция с OPA Gatekeeper

```yaml
# gatekeeper-constraint-template.yaml
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: k8srequiredlabels
spec:
  crd:
    spec:
      names:
        kind: K8sRequiredLabels
      validation:
        openAPIV3Schema:
          type: object
          properties:
            labels:
              type: array
              items:
                type: string
  targets:
    - target: admission.k8s.gatekeeper.sh
      rego: |
        package k8srequiredlabels
        violation[{"msg": msg}] {
          provided := {label | input.review.object.metadata.labels[label]}
          required := {label | label := input.parameters.labels[_]}
          missing := required - provided
          count(missing) > 0
          msg := sprintf("Missing required labels: %v", [missing])
        }
---
# gatekeeper-constraint.yaml
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sRequiredLabels
metadata:
  name: vcluster-required-labels
spec:
  match:
    kinds:
      - apiGroups: [""]
        kinds: ["Namespace"]
    labelSelector:
      matchExpressions:
        - key: vcluster.loft.sh/name
          operator: Exists
  parameters:
    labels:
      - "team"
      - "environment"
      - "cost-center"
```

### Интеграция с Kyverno

```yaml
# kyverno-policy-require-labels.yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-vcluster-labels
spec:
  validationFailureAction: Enforce
  background: false
  rules:
    - name: check-required-labels
      match:
        any:
          - resources:
              kinds:
                - Namespace
              selector:
                matchLabels:
                  vcluster.loft.sh/name: "?*"
      validate:
        message: "Label 'team' is required for vCluster namespaces"
        pattern:
          metadata:
            labels:
              team: "?*"
              environment: "?*"
---
# kyverno-policy-restrict-privileged.yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: restrict-privileged-vcluster
spec:
  validationFailureAction: Enforce
  rules:
    - name: deny-privileged-pods
      match:
        any:
          - resources:
              kinds:
                - Pod
      validate:
        message: "Privileged pods are not allowed in vCluster"
        pattern:
          spec:
            containers:
              - securityContext:
                  privileged: "false"
```

### Интеграция с Vault через External Secrets Operator

```yaml
# external-secret.yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: db-credentials
  namespace: team-alpha
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: db-credentials
  data:
    - secretKey: username
      remoteRef:
        key: secret/data/team-alpha/database
        property: username
    - secretKey: password
      remoteRef:
        key: secret/data/team-alpha/database
        property: password
---
# secret-store.yaml
apiVersion: external-secrets.io/v1
kind: SecretStore
metadata:
  name: vault-backend
  namespace: team-alpha
spec:
  provider:
    vault:
      server: "https://vault.corp.local:8200"
      path: "secret"
      version: "v2"
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "vcluster-team-alpha"
          serviceAccountRef:
            name: "vault-auth-sa"
```

### Audit Log для compliance

```yaml
# vcluster.yaml — включение аудита
controlPlane:
  distro:
    k8s:
      enabled: true
  apiserver:
    extraArgs:
      - --audit-policy-file=/etc/kubernetes/audit-policy.yaml
      - --audit-log-path=/var/log/vcluster/audit.log
      - --audit-log-maxage=30
      - --audit-log-maxbackup=10
      - --audit-log-maxsize=100
    volumeMounts:
      - name: audit-policy
        mountPath: /etc/kubernetes
        readOnly: true
  statefulSet:
    volumes:
      - name: audit-policy
        configMap:
          name: vcluster-audit-policy
---
# audit-policy-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: vcluster-audit-policy
  namespace: team-alpha
data:
  audit-policy.yaml: |
    apiVersion: audit.k8s.io/v1
    kind: Policy
    rules:
      # Записывать все запросы к API
      - level: RequestResponse
        resources:
          - group: ""
            resources: ["secrets", "configmaps"]
      - level: Metadata
        resources:
          - group: ""
            resources: ["pods", "services"]
      - level: None
        resources:
          - group: ""
            resources: ["events"]
```

### CIS Benchmark для vCluster

```bash
# 1. Установить kube-bench
curl -L -o kube-bench https://github.com/aquasecurity/kube-bench/releases/download/v0.8.1/kube-bench_linux_amd64
chmod +x kube-bench
sudo mv kube-bench /usr/local/bin/

# 2. Запустить проверку
kube-bench run --targets=master,node,policies

# 3. Проверить конкретные control-бенчмарки
kube-bench run --targets=master --check 1.2.1,1.2.2,1.2.3

# 4. Результаты в формате JSON
kube-bench run --targets=master --json > cis-report.json
```

### Чек-лист безопасности vCluster

| Уровень | Проверка | Реализация | Приоритет |
| :--- | :--- | :--- | :--- |
| **Pod Security** | PSA restricted | `policies.podSecurityStandard: restricted` | Критический |
| **Pod Security** | readOnlyRootFilesystem | `policies.readOnlyRootFilesystem: true` | Высокий |
| **Pod Security** | drop ALL capabilities | PSA restricted (по умолчанию) | Высокий |
| **Pod Security** | seccomp RuntimeDefault | PSA restricted | Средний |
| **Syncer** | Минимальный RBAC | `controlPlane.serviceAccount.create: false` + custom Role | Критический |
| **Syncer** | Отдельный namespace | Не использовать `default` | Критический |
| **Control Plane** | Rootless mode | `runAsNonRoot: true` | Высокий |
| **Control Plane** | Audit log | `apiserver.auditLog.enabled: true` | Критический |
| **Control Plane** | OIDC/SSO | `apiserver.extraArgs: --oidc-*` | Высокий |
| **Network** | NetworkPolicy | `policies.networkPolicy.enabled: true` | Критический |
| **Network** | Default-deny | Автогенерация при `networkPolicy.enabled` | Высокий |
| **Storage** | Изоляция PV | StorageClass per-tenant | Высокий |
| **Secrets** | External Secrets | ESO + Vault | Высокий |
| **Policy Engine** | OPA/Kyverno | Admission webhook на хосте | Средний |
| **Compliance** | CIS Benchmark | `kube-bench`定期実行 | Средний |
| **Compliance** | Audit log → SIEM | Loki/ELK для аудит-логов | Высокий |

### Диагностика проблем безопасности

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `forbidden: violates PodSecurity` | PSA блокирует под | Проверить labels namespace, исправить deployment |
| ` admission webhook denied` | OPA/Kyverno блокирует | Проверить политики, посмотреть webhook logs |
| `forbidden: User "system:anonymous"` | RBAC не настроен | Проверить ClusterRole/RoleBinding |
| `Secret not found` | ESO не синхронизировал | Проверить ExternalSecret status |
| Audit log пустой | Аудит не включён | `apiserver.auditLog.enabled: true` |
| Vault connection refused | Vault недоступен | Проверить Vault pod, service,证书 |

### Лучшие практики

- **Принудительный PSA:** restricted для всех тенантов. Переход через audit → warn → enforce.
- **Минимальный RBAC:** Syncer должен иметь Role, не ClusterRole. Без `pods/exec`.
- **Vault для секретов:** Не храните секреты в Git. Используйте External Secrets Operator.
- **Audit log в WORM:** Для compliance храните аудит-логи в append-only хранилище.
- **Регулярный аудит:** Запускайте `kube-bench` 1 раз в месяц, исправляйте findings.
- **Сетевая изоляция:** Default-deny NetworkPolicy + явные разрешения.
- **Шифрование at-rest:** etcd encryption для sensitive данных (secrets, configmaps).

## Дополнительная информация

### Внутренние ссылки

- [vCluster — безопасность и синхронизация](./vcluster_security_and_sync.md)
- [vCluster — мониторинг и observability](./vcluster_monitoring.md)
- [vCluster — troubleshooting](./vcluster_troubleshooting.md)

### См. также

- [Vault — интеграция с Kubernetes](../../Vault/guides/vault_kubernetes_integration.md)
- [Kyverno — troubleshooting](../../Kubernetes/Security/kyverno/troubleshooting.md)

### Внешние ссылки

- [vCluster Security Documentation](https://www.vcluster.com/docs/architecture/security)
- [CIS Kubernetes Benchmark](https://www.cisecurity.org/benchmark/kubernetes)
- [OPA Gatekeeper Documentation](https://open-policy-agent.github.io/gatekeeper/)
- [Kyverno Documentation](https://kyverno.io/docs/)
