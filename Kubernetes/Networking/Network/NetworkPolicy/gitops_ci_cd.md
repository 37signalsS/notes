# NetworkPolicy: CI/CD и GitOps

## Определения

**Policy-as-Code** — подход к управлению сетевыми политиками, при котором все манифесты NetworkPolicy хранятся в Git, проходят код-ревью и применяются через автоматизированные пайплайны CI/CD. Обеспечивает воспроизводимость, аудит и откат.

**GitOps** — методология доставки инфраструктуры, при которой Git является единственным источником истины (SSoT). Изменения в кластер применяются автоматически синхронизацией из Git-репозитория (ArgoCD, Flux).

**Policy Validation (Валидация политик)** — проверка манифестов NetworkPolicy перед применением: синтаксис, семантика, соответствие organizational standards. Инструменты: `conftest` (OPA/Rego), `kubeconform`, Kyverno CLI.

**Drift Detection (Обнаружение дрифта)** — механизм обнаружения расхождений между желаемым состоянием в Git и фактическим состоянием в кластере. GitOps-операторы (ArgoCD, Flux) автоматически исправляют drift.

**NetworkPolicy Testing** — тестирование эффекта NetworkPolicy перед деплоем: проверка что политика не заблокирует необходимый трафик. Инструменты: `kuttl`, `politest`, `netpol-verifier`.

**Audit Mode (Режим аудита)** — временное включение мониторинга NetworkPolicy без фактического исполнения правил. Позволяет оценить impact перед enforce. Поддерживается Cilium (CiliumNetworkPolicy `enableAudit`) и Calico (GlobalNetworkPolicy `log` action).

## Базовые Концепции

### Зачем GitOps для NetworkPolicy

| Проблема | Решение через GitOps |
| :--- | :--- |
| Ручное применение политик → ошибки | Автоматическая синхронизация из Git |
| Нет аудита изменений | История коммитов + code review |
| Сложный откат | `git revert` → автоматический откат в кластер |
| Drift между средами | Единый источник истины в Git |
| Нет валидации перед применением | CI pipeline с conftest/kubeconform |
| Секреты в манифестах | Sealed Secrets / External Secrets Operator |

### Pipeline: NetworkPolicy в CI/CD

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  Git Push │────►│   CI     │────►│  Policy  │────►│  Deploy  │
│  (PR/MR) │     │  Build   │     │ Validation│     │ (GitOps) │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
                      │                 │                │
                      ▼                 ▼                ▼
                 lint/makefile    conftest         ArgoCD/Flux
                                  kubeconform      sync
                                  kuttl test       to cluster
```

### Инструменты валидации

| Инструмент | Тип проверки | Интеграция | Язык политик |
| :--- | :--- | :--- | :--- |
| **conftest** | Семантическая (OPA/Rego) | CI (GitHub Actions, GitLab CI) | Rego |
| **kubeconform** | Синтаксическая (schema) | CI, pre-commit | JSON Schema |
| **kuttl** | E2E-тестирование | CI (kubectl) | YAML + bash |
| **Kyverno CLI** | Policy-as-Code тесты | CLI, CI | Kyverno policies |
| **politest** | Reachability testing | CLI | NetworkPolicy |
| **netpol-verifier** | Network reachability | CLI | NetworkPolicy |

### Структура репозитория для NetworkPolicy GitOps

```
gitops-networkpolicy/
├── base/                           # Базовые политики (общие для всех кластеров)
│   ├── default-deny.yaml
│   ├── allow-dns.yaml
│   ├── block-metadata.yaml
│   └── shared-monitoring.yaml
├── overlays/                       # Специфичные для окружений
│   ├── production/
│   │   ├── kustomization.yaml
│   │   └── additional-policies.yaml
│   └── staging/
│       ├── kustomization.yaml
│       └── relaxed-policies.yaml
├── tenant/                         # Политики тенантов
│   ├── team-alpha/
│   │   ├── kustomization.yaml
│   │   └── app-policies.yaml
│   └── team-beta/
│       ├── kustomization.yaml
│       └── app-policies.yaml
├── tests/                          # Тесты
│   ├── conftest/
│   │   └── policy_test.rego
│   ├── kuttl/
│   │   └── networkpolicy-test/
│   │       └── 00-default-deny.yaml
│   └── kubeconform/
│       └── schema.yaml
└── .github/
    └── workflows/
        └── validate-policies.yaml
```

## Практические сценарии

### Сценарий 1: conftest для валидации NetworkPolicy

Rego-политика для проверки наличия DNS-правил:

```rego
# tests/conftest/policy_test.rego
package main

deny[msg] {
  input.kind == "NetworkPolicy"
  not has_egress_dns
  msg := sprintf("NetworkPolicy %s не содержит Egress правил для DNS (UDP 53)", [input.metadata.name])
}

deny[msg] {
  input.kind == "NetworkPolicy"
  not has_egress_policytype
  msg := sprintf("NetworkPolicy %s не содержит policyTypes с Egress", [input.metadata.name])
}

has_egress_dns {
  egress := input.spec.egress[_]
  egress.ports[_].port == 53
  egress.ports[_].protocol == "UDP"
}

has_egress_policytype {
  input.spec.policyTypes[_] == "Egress"
}
```

```bash
# Запуск проверки
conftest test kubernetes/networkpolicy/
# → FAIL: policy_test.rego - NetworkPolicy default-deny не содержит Egress правил для DNS
```

### Сценарий 2: kubeconform для schema-валидации

```bash
# Установка
brew install kubeconform

# Валидация всех манифестов
kubeconform -summary -output json kubernetes/networkpolicy/
# → {"summary":{"valid":12,"invalid":0,"errors":0,"skipped":0}}

# Валидация с кастомными схемами
kubeconform -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/{{.ResourceKind}}_schema.json' \
  kubernetes/networkpolicy/
```

### Сценарий 3: kuttl для E2E-тестирования NetworkPolicy

```bash
# Установка
brew install kuttl

# Структура теста
# tests/kuttl/networkpolicy-test/
# ├── 00-create-namespace.yaml
# ├── 01-apply-default-deny.yaml
# ├── 02-apply-allow-dns.yaml
# ├── 03-deploy-test-pods.yaml
# └── 04-assert-connectivity.yaml
```

```yaml
# 04-assert-connectivity.yaml
apiVersion: kuttl.dev/v1beta1
kind: TestAssert
commands:
- command: kubectl exec -n test test-pod-a -- wget -qO- --timeout=5 http://test-pod-b.test.svc
  # Должен success (DNS + internal)
- command: kubectl exec -n test test-pod-a -- wget -qO- --timeout=3 https://google.com
  # Должен timeout (blocked egress)
timeout: 30
```

### Сценарий 4: ArgoCD Application для NetworkPolicy

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: network-policies-production
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/gitops-networkpolicy.git
    targetRevision: main
    path: overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: production
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
    - PrunePropagationPolicy=foreground
```

### Сценарий 5: GitHub Actions Pipeline

```yaml
# .github/workflows/validate-policies.yaml
name: Validate NetworkPolicy
on:
  pull_request:
    paths:
    - 'kubernetes/networkpolicy/**'
    - 'tenant/**'

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Install tools
      run: |
        brew install conftest kubeconform

    - name: Schema validation
      run: kubeconform -summary kubernetes/networkpolicy/ tenant/

    - name: Policy validation (conftest)
      run: conftest test kubernetes/networkpolicy/ tenant/

    - name: Dry-run apply
      run: |
        kubectl apply --dry-run=client -f kubernetes/networkpolicy/
        kubectl apply --dry-run=client -f tenant/
```

### Сценарий 6: Kyverno для Policy-as-Code

```yaml
# Kyverno policy: требовать DNS-правила в NetworkPolicy
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-dns-egress
spec:
  validationFailureAction: Enforce
  rules:
  - name: check-dns-egress
    match:
      any:
      - resources:
          kinds:
          - NetworkPolicy
    validate:
      message: "NetworkPolicy должен содержать Egress-правило для DNS (port 53)"
      pattern:
        spec:
          policyTypes:
          - Egress
          egress:
          - ports:
            - protocol: UDP
              port: 53
```

```bash
# Тестирование Kyverno policy
kyverno apply --policy-report --results-dir ./results/ kubernetes/networkpolicy/
# → Policyreport created with 2 pass, 0 fail, 0 warn
```

## Дополнительная информация

### Лучшие практики CI/CD для NetworkPolicy

| # | Практика | Описание |
| :--- | :--- | :--- |
| 1 | **PR/MR required** | NetworkPolicy применяются только через PR с code review |
| 2 | **Automated validation** | conftest + kubeconform в CI pipeline |
| 3 | **Dry-run в staging** | `kubectl apply --dry-run=server` перед production |
| 4 | **GitOps sync** | ArgoCD/Flux для автоматической синхронизации |
| 5 | **Drift detection** | ArgoCD selfHeal / Flux drift detection |
| 6 | **Audit mode** | Включение audit перед enforce в production |
| 7 | **Rollback strategy** | `git revert` + автоматический откат через GitOps |
| 8 | **Versioned releases** | Теги для версий политик (netpol-v1.2.0) |
| 9 | **Monitoring** | Prometheus alerts на изменения NetworkPolicy |
| 10 | **Documentation** | README в каждом directory с описанием политик |

### Связанные темы

* [GitOps: Управление политиками](../../GitOps/Concepts/gitops-policy-management.md) — общие концепции
* [Kyverno: Тестирование](../../Security/kyverno/additional.md) — Kyverno CLI и тесты
* [ArgoCD Security Hardening](../../GitOps/ArgoCD/argocd_security_hardening.md) — NetworkPolicy для ArgoCD
* [Лучшие практики NetworkPolicy](./best_practices.md) — рекомендации
* [conftest в CI/CD](../../CI-CD/Testing/tdd_bdd_overview.md) — тестирование политик
