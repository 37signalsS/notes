# Crossplane: Защита зависимостей (Usage)

## Определения

**Usage** (`protection.crossplane.io/v1beta1`) — ресурс, объявляющий отношение «используется кем-то». Две главные цели: (1) **защита от удаления** — заблокировать удаление ресурса, пока существует использующий его объект; (2) **упорядочивание удаления** — не удалять ресурс, пока не удалены его зависимые.

**ClusterUsage** — то же для cluster-scoped ресурсов (например, защита важных CRD или Provider от случайного удаления).

> Usages — beta-фича (включена по умолчанию в Crossplane v2). Отключается флагом `--enable-usages=false`.

## Базовые концепции

- Поля `spec.of` (защищаемый ресурс) и `spec.by` (использующий). Обязательно хотя бы одно. `reason` — текст причины блокировки.
- `selectors` (`resourceSelector`/`matchControllerRef`) позволяют выбирать ресурсы по labels вместо имени (разрешаются один раз).
- `replayDeletion: true` — после исчезновения использующего ресурса удаление защищаемого «повторяется» немедленно (полезно внутри композиции, ускоряет очистку).
- **Важно для композиций:** чтобы `Usage` с `by: XR` реально блокировал удаление дочерних ресурсов, у XRD должна быть `spec.defaultCompositeDeletePolicy: Foreground` (иначе по умолчанию `Background` и блокировка не сработает до удаления самого XR).

## Практические сценарии

### 1. Защита БД от удаления, пока есть приложение
```yaml
apiVersion: protection.crossplane.io/v1beta1
kind: Usage
metadata:
  name: app-uses-db
  namespace: default
spec:
  of:
    apiVersion: rds.aws.m.upbound.io/v1beta1
    kind: Instance
    resourceRef:
      name: my-database
  by:
    apiVersion: apps/v1
    kind: Deployment
    resourceRef:
      name: my-app
  reason: "Production DB — удаляется только вместе с приложением"
```
```bash
kubectl delete instance my-database
# Error: cannot delete resource while usage exists
```

### 2. Упорядочивание удаления (Release использует Cluster)
```yaml
apiVersion: protection.crossplane.io/v1beta1
kind: Usage
metadata:
  name: release-uses-cluster
spec:
  of:
    apiVersion: eks.m.upbound.io/v1beta1
    kind: Cluster
    resourceRef:
      name: my-cluster
  by:
    apiVersion: helm.m.crossplane.io/v1beta1
    kind: Release
    resourceRef:
      name: my-prometheus
```

### 3. Защита cluster-scoped ресурса (ClusterUsage)
```yaml
apiVersion: protection.crossplane.io/v1beta1
kind: ClusterUsage
metadata:
  name: protect-provider
spec:
  of:
    apiVersion: pkg.crossplane.io/v1
    kind: Provider
    resourceRef:
      name: provider-aws
  reason: "Provider с активными MR — не удалять"
```

### 4. Usage внутри композиции + Foreground-удаление XR
```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: CompositeResourceDefinition
metadata:
  name: xapplications.platform.example.com
spec:
  group: platform.example.com
  names:
    kind: XApplication
    plural: xapplications
  claimNames:
    kind: Application
    plural: applications
  defaultCompositeDeletePolicy: Foreground   # XR ждёт удаления дочерних ресурсов
  # ...
```
А в Composition добавляется `Usage` (через `function-patch-and-transform` или отдельный `base`), гарантирующий, что общая сетевая инфраструктура не удалится, пока живёт XR приложения.

### 5. Диагностика заблокированного удаления
```bash
kubectl get usage -A
kubectl describe usage <name>        # причина блокировки в Events/status
kubectl get <protected-kind> <name>  # удалите сначала использующий ресурс
# либо принудительно «повторить» удаление после исчезновения by-ресурса:
kubectl patch usage <name> --type merge -p '{"spec":{"replayDeletion":true}}'
```

## Дополнительная информация

- [Usages (официальная документация)](https://docs.crossplane.io/latest/managed-resources/usages/)

Смежные темы:
- [Мультитенантность и OOO](./multi_tenancy.md) — изоляция и `ownerOnlyOrphan`.
- [Обновление и миграция](./upgrade_migration.md) — семантика удаления/отката при смене Composition.
- [Политики и Governance](./policy_governance.md) — нативная защита удаления через admission.
- [Обзор Crossplane](./overview.md).
