# Kustomize — Security Hardening манифестов

## 1. Определения

**Security Hardening через Kustomize** — процесс систематического применения политик безопасности (Pod Security Standards, NetworkPolicies, ResourceQuotas, OPA/Kyverno) к Kubernetes-манифестам через overlays и компоненты Kustomize, обеспечивая единообразную безопасность во всех окружениях без дублирования конфигурации.

**Component-based security** — паттерн, при котором политики безопасности выносятся в переиспользуемые Kustomize-компоненты (monitoring, logging, security) и «подмешиваются» к приложениям через `components` в kustomization.yaml.

**Pipeline validation** — многоуровневая цепочка проверок манифестов перед применением: схематическая (kubeconform) → семантическая (conftest/OPA) → серверная (dry-run=server) → admission (Kyverno/Gatekeeper).

## 2. Основные концепции

### Цепочка валидации манифестов

```text
kustomize build  →  kubeconform  →  conftest (OPA)  →  polaris  →  kubectl apply --dry-run=server  →  Kyverno/Gatekeeper (admission)
     1                   2                3                 4                    5                                    6
```

| Уровень | Инструмент | Что проверяет | Скорость |
| :--- | :--- | :--- | :--- |
| 1. Сборка | `kustomize build` | Синтаксис YAML, ссылки на файлы | Мгновенно |
| 2. Схема | `kubeconform` | Соответствие схемам Kubernetes API | Мгновенно |
| 3. Политики | `conftest` (OPA/Rego) | Организационные политики (нет :latest, limits обязательны) | ~1 сек |
| 4. Best practices | `polaris` | Рекомендации по безопасности и ресурсам | ~2 сек |
| 5. Серверная | `kubectl apply --dry-run=server` | RBAC, quotas, CRD существуют | ~1 сек |
| 6. Admission | Kyverno/Gatekeeper | Runtime-политики в кластере | ~0.5 сек |

### Pod Security Standards через Kustomize

**Профили PSS:**
- `privileged` — все разрешено (только для system pods)
- `baseline` — минимальные ограничения (запрет privileged, hostNetwork, hostPID)
- `restricted` — строгие ограничения (runAsNonRoot, drop ALL capabilities, seccomp)

**Применение PSS через labels namespace:**
```yaml
# base/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: web-server
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

**Массовое применение через патч:**
```yaml
# overlays/production/kustomization.yaml
patches:
  - target:
      kind: Namespace
    patch: |-
      - op: add
        path: /metadata/labels/pod-security.kubernetes.io~1enforce
        value: restricted
      - op: add
        path: /metadata/labels/pod-security.kubernetes.io~1audit
        value: restricted
      - op: add
        path: /metadata/labels/pod-security.kubernetes.io~1warn
        value: restricted
```

### Security Context через компоненты

```yaml
# components/security-context/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

patches:
  - target:
      kind: Deployment
    patch: |-
      - op: add
        path: /spec/template/spec/securityContext
        value:
          runAsNonRoot: true
          fsGroup: 65534
          seccompProfile:
            type: RuntimeDefault
  - target:
      kind: Deployment
      containerTypes: [initContainers, containers]
    patch: |-
      - op: add
        path: /spec/template/spec/containers/0/securityContext
        value:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
              - ALL
```

**Использование в overlay:**
```yaml
# overlays/production/kustomization.yaml
components:
  - ../../components/security-context
```

## 3. Практические сценарии

### 3.1. Массовое добавление security context ко всем Deployment

```yaml
# components/hardened-base/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

patches:
  # Запрет privileged контейнеров
  - target:
      kind: Deployment
    patch: |-
      - op: add
        path: /spec/template/spec/containers/0/securityContext/allowPrivilegeEscalation
        value: false
      - op: add
        path: /spec/template/spec/containers/0/securityContext/capabilities/drop
        value: ["ALL"]
      - op: add
        path: /spec/template/spec/containers/0/securityContext/runAsNonRoot
        value: true
      - op: add
        path: /spec/template/spec/containers/0/securityContext/seccompProfile/type
        value: RuntimeDefault

  # Resource requests/limits
  - target:
      kind: Deployment
    patch: |-
      - op: add
        path: /spec/template/spec/containers/0/resources/requests/cpu
        value: "100m"
      - op: add
        path: /spec/template/spec/containers/0/resources/requests/memory
        value: "128Mi"
      - op: add
        path: /spec/template/spec/containers/0/resources/limits/cpu
        value: "500m"
      - op: add
        path: /spec/template/spec/containers/0/resources/limits/memory
        value: "512Mi"

  # automountServiceAccountToken: false (если не нужен доступ к API)
  - target:
      kind: Deployment
    patch: |-
      - op: add
        path: /spec/template/spec/automountServiceAccountToken
        value: false
```

### 3.2. NetworkPolicy как компонент

```yaml
# components/network-isolation/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - network-policies.yaml

# components/network-isolation/network-policies.yaml
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all-default
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
spec:
  podSelector: {}
  policyTypes:
    - Egress
  egress:
    - to: []
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
```

**Использование:**
```yaml
# overlays/production/kustomization.yaml
components:
  - ../../components/network-isolation
```

### 3.3. OPA-политики (Rego) для Kustomize output

**Пример Rego-политики:**
```rego
# policies/kustomize-policy.rego
package main

deny[msg] {
  input.kind == "Deployment"
  not input.spec.template.spec.containers[0].resources.limits.cpu
  msg := "CPU limits are required for all containers"
}

deny[msg] {
  input.kind == "Deployment"
  input.spec.template.spec.containers[0].image
  endswith(input.spec.template.spec.containers[0].image, ":latest")
  msg := "Image tag :latest is not allowed"
}

deny[msg] {
  input.kind == "Deployment"
  not input.spec.template.spec.containers[0].securityContext.runAsNonRoot
  msg := "runAsNonRoot must be set to true"
}

deny[msg] {
  input.kind == "Deployment"
  input.spec.template.spec.containers[0].securityContext.privileged == true
  msg := "Privileged containers are not allowed"
}
```

**Интеграция в CI:**
```bash
# Сборка и валидация
kustomize build overlays/production/ > /tmp/manifests.yaml

# 1. Схематическая валидация
kubeconform -strict -summary /tmp/manifests.yaml

# 2. OPA-политики
conftest test /tmp/manifests.yaml --policy policies/

# 3. Best practices
polaris audit --file /tmp/manifests.yaml --set-exit-code-on-error

# 4. Dry-run на сервере
kubectl apply --dry-run=server -f /tmp/manifests.yaml
```

### 3.4. Kyverno ClusterPolicy + Kustomize

```yaml
# policies/require-labels.yaml (Kyverno ClusterPolicy)
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-labels
spec:
  validationFailureAction: Enforce
  background: false
  rules:
    - name: check-app-label
      match:
        any:
          - resources:
              kinds:
                - Deployment
      validate:
        message: "Label 'app' is required"
        pattern:
          metadata:
            labels:
              app: "?*"
    - name: check-team-label
      match:
        any:
          - resources:
              kinds:
                - Deployment
      validate:
        message: "Label 'team' is required"
        pattern:
          metadata:
            labels:
              team: "?*"
```

**Применение через Kustomize:**
```yaml
# overlays/security-policies/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - policies/require-labels.yaml
  - policies/deny-privileged.yaml
  - policies/require-limits.yaml
```

### 3.5. Pod Security Standards: запрет root-подов

```yaml
# components/restricted-pss/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

patches:
  # Все Deployment'ы в restricted PSS
  - target:
      kind: Deployment
    patch: |-
      - op: add
        path: /spec/template/spec/securityContext/runAsNonRoot
        value: true
      - op: add
        path: /spec/template/spec/securityContext/seccompProfile/type
        value: RuntimeDefault
      - op: add
        path: /spec/template/spec/containers/0/securityContext/allowPrivilegeEscalation
        value: false
      - op: add
        path: /spec/template/spec/containers/0/securityContext/capabilities/drop
        value: ["ALL"]
      - op: add
        path: /spec/template/spec/containers/0/securityContext/readOnlyRootFilesystem
        value: true
```

### 3.6. Цепочка валидации в GitHub Actions

```yaml
name: Security Validation
on: [pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Kustomize
        run: |
          curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash
          sudo mv kustomize /usr/local/bin/

      - name: Setup tools
        run: |
          # kubeconform
          curl -sL https://github.com/yannh/kubeconform/releases/latest/download/kubeconform-linux-amd64.tar.gz | tar xz
          sudo mv kubeconform /usr/local/bin/
          # conftest
          curl -sL https://github.com/open-policy-agent/conftest/releases/latest/download/conftest_Linux_x86_64.tar.gz | tar xz
          sudo mv conftest /usr/local/bin/

      - name: Build manifests
        run: kustomize build overlays/production/ > /tmp/manifests.yaml

      - name: Schema validation (kubeconform)
        run: kubeconform -strict -summary /tmp/manifests.yaml

      - name: OPA policies (conftest)
        run: conftest test /tmp/manifests.yaml --policy policies/

      - name: Server-side dry-run
        run: kubectl apply --dry-run=server -f /tmp/manifests.yaml
        env:
          KUBECONFIG: ${{ secrets.KUBECONFIG }}
```

## 4. Дополнительная информация

### Чеклист безопасности перед деплоем

- [ ] `runAsNonRoot: true` во всех Deployment
- [ ] `readOnlyRootFilesystem: true` где возможно
- [ ] `capabilities.drop: ["ALL"]` во всех контейнерах
- [ ] `allowPrivilegeEscalation: false` везде
- [ ] `seccompProfile.type: RuntimeDefault` везде
- [ ] Resource requests и limits заданы
- [ ] NetworkPolicy (deny-all-default) применен
- [ ] Namespace labels для PSS restricted установлены
- [ ] Образы не содержат :latest теги
- [ ] `automountServiceAccountToken: false` где не нужен API

### См. также

- [Pod Security Context](../../Security/pod_security_context.md) — полная теория PSS/PSA
- [NetworkPolicy](../../Networking/Network/NetworkPolicy/practical_scenarios.md) — сценарии сетевых политик
- [Conftest/OPA](../../../CI-CD/Testing/tdd_bdd_overview.md#пример-conftest-oparego) — policy-тестирование
