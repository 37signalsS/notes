# Crossplane: Политики и Governance (Kyverno / OPA)

## Определения

**Policy-as-Code** — декларативные правила, запрещающие или требующие определённые свойства ресурсов на этапе admission (до попадания в кластер). Для Crossplane это особенно важно на уровне **Claim/XR**, т.к. именно их подают приложенческие команды.

**Kyverno / OPA Gatekeeper** — движки политик (CRD-ориентированные). С Kubernetes 1.30+ доступен нативный **ValidatingAdmissionPolicy** (CEL) — без стороннего контроллера для простых случаев.

## Базовые концепции

Где валидировать Crossplane:
- **Уровень Claim (рекомендуется):** правила на `kind: PostgreSQLInstance` и т.п. ловят ошибку до композиции — проще и ближе к потребителю.
- **Уровень XR:** то же, но до применения composed-ресурсов.
- **Уровень MR:** поздно (ресурс уже генерируется), используйте только для жёстких запретов (публичный доступ, запрет удаления).

Типичные политики: обязательные labels, запрет публичных бакетов/доступов, лимиты ресурсов, запрет обхода защиты удаления, требование `deletionPolicy`/`managementPolicy`.

## Практические сценарии

### 1. Kyverno: обязательные labels и запрет публичного доступа на Claim
```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: postgres-claim-guard
spec:
  validationFailureAction: Enforce
  rules:
    - name: require-labels
      match:
        any:
          - resources:
              kinds: ["PostgreSQLInstance.platform.example.com"]
      validate:
        message: "Требуются labels team и environment"
        pattern:
          metadata:
            labels:
              team: "?*"
              environment: "?*"
    - name: no-public-access
      match:
        any:
          - resources:
              kinds: ["PostgreSQLInstance.platform.example.com"]
      validate:
        message: "Публичный доступ запрещён"
        deny:
          conditions:
            any:
              - key: "{{ request.object.spec.parameters.publicAccess || false }}"
                operator: Equals
                value: true
```

### 2. Нативный ValidatingAdmissionPolicy: защита удаления
```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: database-deletion-protection
spec:
  matchConstraints:
    resourceRules:
      - apiGroups: ["platform.example.com"]
        apiVersions: ["*"]
        operations: ["DELETE"]
        resources: ["postgresqlinstances"]
  validations:
    - expression: >-
        oldObject.metadata.annotations['platform.example.com/delete-protected'] != 'true'
      message: "Ресурс защищён от удаления. Снимите аннотацию delete-protected."
      reason: Forbidden
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: database-deletion-protection-binding
spec:
  policyName: database-deletion-protection
  validationActions: [Deny]
  matchResources:
    namespaceSelector:
      matchLabels: { protected: "true" }
```

### 3. OPA Gatekeeper: обязательный лимит ресурсов
```yaml
apiVersion: templates.gatekeeper.sh/v1beta1
kind: ConstraintTemplate
metadata:
  name: postgresmusthavelimits
spec:
  crd:
    spec:
      names: { kind: PostgresMustHaveLimits }
      validation:
        openAPIV3Schema:
          type: object
          properties:
            maxCores: { type: integer }
  targets:
    - target: admission.k8s.gatekeeper.sh
      rego: |
        violation[{"msg": msg}] {
          cores := input.review.object.spec.parameters.cores
          cores > input.parameters.maxCores
          msg := sprintf("cores %v превышает лимит %v", [cores, input.parameters.maxCores])
        }
---
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: PostgresMustHaveLimits
metadata:
  name: max-cores
spec:
  parameters: { maxCores: 16 }
```

### 4. Интеграция с Crossplane
Политики валидируют Claim **до** того, как Crossplane начнёт композицию. Это дешевле и безопаснее, чем ловить нарушение на уровне MR. Для защиты от каскадного удаления общей инфраструктуры комбинируйте политики с [Usage](./usage_protection.md).

## Дополнительная информация

- [Kyverno документация](https://kyverno.io/docs/)
- [Open Policy Agent (OPA) документация](https://www.openpolicyagent.org/docs)
- Нативный ValidatingAdmissionPolicy: документация Kubernetes API.

Смежные темы:
- [Защита зависимостей (Usage)](./usage_protection.md) — защита удаления на уровне Crossplane.
- [Мультитенантность и OOO](./multi_tenancy.md) — изоляция команд.
- [GitOps: управление политиками](../Concepts/gitops-policy-management.md) — доставка политик через GitOps.
- [Обзор Crossplane](./overview.md).
