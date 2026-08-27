# Crossplane: Мультитенантность и изоляция (OOO)

## Определения

**Мультитенантность в Crossplane** — предоставление одного control plane многим командам/проектам с изоляцией их ресурсов, прав и областей видимости. Ключевой механизм — гранулярный RBAC и namespace-скоупинг.

**OOO (Only One Of / Owner Only Orphan)** — альфа-фича (`--enable-oo`), управляющая тем, сколько XR определённого kind может существовать в неймспейсе (`onlyOneOf`) и что происходит с зависимыми ресурсами при удалении XR-владельца (`ownerOnlyOrphan`).

**Namespace-scoped MR/XR** — в Crossplane v2 ресурсы могут быть ограничены неймспейсом (группа `kubernetes.m.crossplane.io`), что даёт естественную изоляцию тенантов.

## Базовые концепции

### Модель изоляции
- **Per-namespace**: каждой команде выделяется неймспейс; XR и Claims создаются в нём, `ProviderConfig` — либо namespace-scoped, либо общий `ClusterProviderConfig`.
- **RBAC**: Crossplane RBAC Manager автоматически выдаёт право управлять composed-ресурсами владельцу XR в его неймспейсе (по `spec.claimNames`/`spec.permissions`). Явно настраивается через `XlaaSConfiguration`/`Permission` (`rbac.crossplane.io/v1alpha1`).
- **OOO**: 
  - `onlyOneOf` — запрещает создание более одного XR данного `kind` в неймспейсе (полезно для «singleton»-ресурсов, например одного общего VPC на команду).
  - `ownerOnlyOrphan` — при удалении XR-владельца зависимые ресурсы (если на них нет другого владельца) переводятся в `Orphan`, а не удаляются, предотвращая каскадное разрушение.

### Чем отличается от разделения на уровне облака
Crossplane изолирует на уровне Kubernetes API и прав доступа. Реальное разделение облачных аккаунтов/проектов задаётся через `EnvironmentConfig` (аккаунт/сеть на тенант) и соответствующие `ProviderConfig` — см. [Composition Functions](./composition_functions.md).

## Практические сценарии

### 1. Per-namespace RBAC для XR
Crossplane автоматически создаёт Role, позволяющую команде управлять сгенерированными ресурсами. Для тонкой настройки используйте явные права в XRD:

```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: CompositeResourceDefinition
metadata:
  name: xpostgresqls.platform.example.com
spec:
  group: platform.example.com
  names:
    kind: XPostgreSQLInstance
    plural: xpostgresqlinstances
  claimNames:
    kind: PostgreSQLInstance
    plural: postgresqlinstances
  permissions:
    namespaced:
      # права, которые Crossplane выдаст владельцу Claim в его неймспейсе
      - apiGroups: ["sql.crossplane.io"]
        resources: ["*"]
        verbs: ["get", "list", "watch", "update", "patch"]
```

### 2. OOO на уровне XRD (альфа)
```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: CompositeResourceDefinition
metadata:
  name: xnetworks.platform.example.com
spec:
  # ...
  onlyOneOf: true            # только один XNetwork на неймспейс
  ownerOnlyOrphan: true      # зависимые ресурсы не удаляются вместе с XR-владельцем
```
> OOO — альфа; включается флагом `--enable-oo` у Deployment Crossplane. Без флага эти поля игнорируются.

### 3. Namespace-scoped MR + ClusterProviderConfig
```yaml
apiVersion: kubernetes.m.crossplane.io/v1beta1
kind: Object
metadata:
  name: team-a-namespace
  namespace: team-a
spec:
  providerConfigRef:
    name: cluster-default
    kind: ClusterProviderConfig
  forProvider:
    manifest:
      apiVersion: v1
      kind: Namespace
      metadata:
        name: team-a-apps
```
Команда `team-a` ограничена своим неймспейсом; общий `ClusterProviderConfig` (креды облака) переиспользуется, но права на создаваемые объекты скоупятся RBAC-менеджером.

### 4. Изоляция тенанта через EnvironmentConfig
См. пример выбора `EnvironmentConfig` по label тенанта в [Composition Functions](./composition_functions.md) (селектор `type: Selector` с `FromCompositeFieldPath: spec.parameters.tenantId`).

## Дополнительная информация

- [Composite Resource Definitions](https://docs.crossplane.io/latest/composition/composite-resource-definitions/)
- [Environment Configs](https://docs.crossplane.io/latest/composition/environment-configs/)

Смежные темы:
- [Защита зависимостей (Usage)](./usage_protection.md) — предотвращение каскадного удаления общей инфраструктуры.
- [Политики и Governance (Kyverno/OPA)](./policy_governance.md) — запрет опасных действий на уровне Claim.
- [GitOps ArgoCD: мультитенантность](../ArgoCD/argocd_multi_tenancy.md) — изоляция на уровне Argo CD Projects.
- [Обзор Crossplane](./overview.md).
