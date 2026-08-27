# Crossplane: Backup и Disaster Recovery control plane

## Определения

**Backup control plane Crossplane** — резервное копирование и восстановление состояния Crossplane. Критично: вся «желаемая инфраструктура» Crossplane — это объекты Kubernetes (XRD, Composition, Configuration, Provider, `ProviderConfig`, Claim/XR, MR) плюс Secrets (креды провайдеров, connection-секреты), и всё это лежит в **etcd** кластера. Потеря etcd = потеря деклараций всей облачной инфраструктуры.

**Два слоя восстановления:**
1. **Git (source of truth)** — декларативное желаемое состояние. При GitOps-модели это и есть основная «резервная копия»: манифесты в репозитории можно применить на свежий кластер.
2. **etcd / Velero snapshot** — runtime-состояние (включая `status.atProvider`, finalizers, сгенерированные имена).

## Базовые концепции

- Crossplane хранит в etcd только **желаемое** состояние и ссылки на реальные ресурсы через аннотацию `crossplane.io/external-name`. Само облако не бэкапится Crossplane — бэкапится *описание* того, что должно быть в облаке.
- После восстановления Crossplane **реконсилирует** и перевыставит состояние, заново привязываясь к облачным ресурсам по `external-name`. Поэтому целостность этой аннотации критична.
- `ProviderConfig` ссылается на Secret с кредами — его тоже надо бэкапить (или восстанавливать через ESO/SOPS, см. [GitOps Integration](./gitops_integration.md)).
- `Usage` (см. [защита зависимостей](./usage_protection.md)) мешает частичному удалению при восстановлении/миграции.

## Практические сценарии

### 1. Etcd snapshot (статический метод)
```bash
# на control-plane узле
ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  snapshot save /var/backups/etcd-crossplane-$(date +%F).db
```
В managed Kubernetes (Managed Service for Kubernetes) etcd обычно бэкапится платформой автоматически — уточняйте в документации провайдера. Восстановление: `etcdctl snapshot restore` на свежий кластер.

### 2. Velero (рекомендуемый для K8s)
```bash
# бэкап неймспейсов Crossplane + приложений (с CRD и секретами)
velero backup create crossplane-backup \
  --include-namespaces crossplane-system,app-team-a \
  --include-resources '*' --default-volumes-to-restic

# восстановление с соблюдением порядка:
# 1) CRD (Velero восстанавливает их первыми),
# 2) Provider/Configuration/XRD/Composition,
# 3) ProviderConfig + Secrets,
# 4) Claims/XR (Crossplane сам дотянет MR)
velero restore create --from-backup crossplane-backup
```
> Velero переносит объекты целиком (вместе с `status`/finalizers). Для «чистого» восстановления часто проще применить манифесты из Git (желаемое), чем etcd-снимок (с transient-статусом).

### 3. Git как backup (минимальный экспорт деклараций)
```bash
# то, что и так есть в Git при GitOps, но полезно для ad-hoc экспорта
kubectl get xrd,composition,configuration,provider,providerconfig,clusterproviderconfig \
  -A -o yaml > crossplane-declarations.yaml
kubectl get claim -A -o yaml >> crossplane-declarations.yaml
```

### 4. Playbook восстановления control plane
1. Поднять свежий кластер, установить Crossplane (Helm/GitOps).
2. Применить платформенные манифесты из Git (XRD/Composition/Configuration/Provider) — GitOps сделает это автоматически.
3. Восстановить `ProviderConfig`-секреты (из ESO/SOPS или Velero).
4. Crossplane реконсилирует; MR перевыставятся и привяжутся к облачным ресурсам по `crossplane.io/external-name`.
5. Проверить `kubectl get managed -A` и готовность Claims (`Ready=True`).

### 5. Что бэкапить обязательно
- CRD Crossplane-провайдеров и самого Crossplane (иначе MR не распарсятся при восстановлении).
- `ProviderConfig` + Secret-креды.
- Git-репозиторий (он — источник правды для деклараций).

## Дополнительная информация

- [Disaster Recovery (концепции)](../../Concepts/disaster_recovery.md)
- [etcd: кластеризация и восстановление](../../etcd/clustering_and_recovery.md)
- [Backup и восстановление (Linux)](../../Linux/SystemAdministration/backup_and_recovery.md)
- [Velero документация](https://velero.io/docs/)

Смежные темы:
- [GitOps Integration](./gitops_integration.md) — Git как source of truth, секреты (ESO/SOPS).
- [Защита зависимостей (Usage)](./usage_protection.md) — безопасное удаление/восстановление.
- [Обновление и миграция](./upgrade_migration.md) — перенос control plane на новый кластер.
- [Обзор Crossplane](./overview.md).
