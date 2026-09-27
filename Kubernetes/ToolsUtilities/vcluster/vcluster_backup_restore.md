# vCluster — бэкап и восстановление

> Документ описывает стратегии резервного копирования и восстановления vCluster: бэкап Backing Store (etcd/SQLite), миграция между namespace/кластерами, тестирование процедур восстановления. Архитектура — в [обзоре](./vcluster_overview.md), установка — в [vcluster_installation.md](./vcluster_installation.md), HA — в [vcluster_high_availability.md](./vcluster_high_availability.md).

## Определения

**Backing Store (Хранилище состояния)** — компонент Control Plane vCluster, в котором хранится всё состояние: объекты Kubernetes (Deployments, Services, Secrets), CRD, RBAC-политики. Типичные реализации: embedded etcd (Vanilla K8s), SQLite (K3s), внешняя PostgreSQL/MySQL через Kine.

**Snapshot (Снапшот)** — моментальный снимок состояния Backing Store. Для etcd — `etcdctl snapshot save`, для SQLite — копирование файла.

**WAL (Write-Ahead Log)** — журнал предзаписи etcd. Все изменения сначала записываются в WAL, затем коммитятся. Потеря WAL = потеря данных.

**RPO (Recovery Point Objective)** — максимально допустимая потеря данных. RPO = 1 час означает потерю не более 1 часа данных при восстановлении.

**RTO (Recovery Time Objective)** — максимально допустимое время восстановления после сбоя.

**Point-in-time Recovery (PITR)** — восстановление к конкретному моменту времени. Требует архивации WAL-журналов.

## Основные концепции

### Что входит в бэкап vCluster

| Компонент | Что хранится | Важность |
| :--- | :--- | :--- |
| **Backing Store (etcd/SQLite)** | Все Kubernetes-объекты: Deployments, Services, Secrets, ConfigMaps, CRD, RBAC | Критическая |
| **PVC** | Файлы Backing Store на диске | Критическая |

> Объекты workload (Pods, ReplicaSets) НЕ требуют отдельного бэкапа — они регенерируются из Deployments/StatefulSets.

### Стратегии бэкапа по типам Backing Store

| Backing Store | Метод бэкапа | Частота | Хранение |
| :--- | :--- | :--- | :--- |
| **Embedded etcd** | `etcdctl snapshot save` | 1-4 часа | 7-30 дней |
| **SQLite (K3s)** | Копирование файла `db-state` | 1-4 часа | 7-30 дней |
| **External PostgreSQL** | `pg_dump` / WAL archiving | 1-4 часа | 30-90 дней |

### RPO и RTO для vCluster

| Сценарий | RPO | RTO | Метод |
| :--- | :--- | :--- | :--- |
| Dev/Test | 24 часа | 30 минут | Ежедневный снапшот |
| Staging | 4 часа | 15 минут | Снапшот каждые 4 часа |
| Production (критичный) | 1 час | 5 минут | Снапшот каждый час + external etcd |
| Production (максимальный) | 0 | 1 минута | External etcd cluster (3+ узла) |

## Практические сценарии

### Бэкап embedded etcd через CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: vcluster-backup
  namespace: team-alpha
spec:
  schedule: "0 */4 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: vcluster-backup-sa
          containers:
            - name: backup
              image: registry.k8s.io/etcd:3.5.13-0
              command:
                - /bin/sh
                - -c
                - |
                  ETCDCTL_API=3 etcdctl \
                    --endpoints=https://127.0.0.1:2379 \
                    --cacert=/etcd/ca.crt \
                    --cert=/etcd/server.crt \
                    --key=/etcd/server.key \
                    snapshot save /backup/snapshot-$(date +%Y%m%d-%H%M%S).db
                  find /backup -name "*.db" -mtime +7 -delete
              volumeMounts:
                - name: etcd-certs
                  mountPath: /etcd
                  readOnly: true
                - name: backup-volume
                  mountPath: /backup
          volumes:
            - name: etcd-certs
              secret:
                secretName: vcluster-etcd-certs
            - name: backup-volume
              persistentVolumeClaim:
                claimName: vcluster-backup-pvc
          restartPolicy: OnFailure
```

### Ручной бэкап

```bash
VC_POD=$(kubectl -n team-alpha get pods -l app=vcluster -o jsonpath='{.items[0].metadata.name}')

kubectl -n team-alpha exec $VC_POD -c etcd -- \
  ETCDCTL_API=3 etcdctl \
    --endpoints=https://127.0.0.1:2379 \
    --cacert=/etcd/ca.crt \
    --cert=/etcd/server.crt \
    --key=/etcd/server.key \
    snapshot save /tmp/snapshot.db

kubectl -n team-alpha cp $VC_POD:/tmp/snapshot.db ./vcluster-backup-$(date +%Y%m%d).db

kubectl -n team-alpha exec $VC_POD -c etcd -- \
  ETCDCTL_API=3 etcdctl snapshot status /tmp/snapshot.db --write-out=table
```

### Бэкап SQLite (K3s)

```bash
VC_POD=$(kubectl -n team-alpha get pods -l app=vcluster -o jsonpath='{.items[0].metadata.name}')

kubectl -n team-alpha exec $VC_POD -- \
  cp /var/lib/rancher/k3s/server/db/state.db /tmp/state.db

kubectl -n team-alpha cp $VC_POD:/tmp/state.db ./vcluster-sqlite-$(date +%Y%m%d).db
```

### Восстановление из снапшота etcd

```bash
kubectl -n team-alpha scale statefulset vc-<name> --replicas=0

VC_POD=$(kubectl -n team-alpha get pods -l app=vcluster -o jsonpath='{.items[0].metadata.name}')
kubectl -n team-alpha cp ./vcluster-backup-20260910.db $VC_POD:/tmp/snapshot.db

kubectl -n team-alpha exec $VC_POD -c etcd -- \
  ETCDCTL_API=3 etcdctl snapshot restore /tmp/snapshot.db \
    --data-dir=/var/lib/etcd-restored \
    --name=vcluster

kubectl -n team-alpha patch statefulset vc-<name> -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"etcd","volumeMounts":[{"name":"data","mountPath":"/var/lib/etcd-restored"}]}]}}}}'

kubectl -n team-alpha scale statefulset vc-<name> --replicas=1
```

### Миграция vCluster между namespace

```bash
VC_POD=$(kubectl -n source-ns get pods -l app=vcluster -o jsonpath='{.items[0].metadata.name}')
kubectl -n source-ns exec $VC_POD -c etcd -- \
  ETCDCTL_API=3 etcdctl snapshot save /tmp/migration-snapshot.db
kubectl -n source-ns cp $VC_POD:/tmp/migration-snapshot.db ./migration-snapshot.db

kubectl create namespace target-ns
vcluster create <name> -n target-ns -f vcluster.yaml --no-connect

TARGET_POD=$(kubectl -n target-ns get pods -l app=vcluster -o jsonpath='{.items[0].metadata.name}')
kubectl -n target-ns cp ./migration-snapshot.db $TARGET_POD:/tmp/snapshot.db
kubectl -n target-ns exec $TARGET_POD -c etcd -- \
  ETCDCTL_API=3 etcdctl snapshot restore /tmp/snapshot.db \
    --data-dir=/var/lib/etcd-restored

kubectl -n target-ns delete pod $TARGET_POD
vcluster connect <name> -n target-ns --update-current
kubectl get deployments,services,secrets
```

### Тестирование процедуры восстановления

```bash
#!/usr/bin/env bash
set -euo pipefail

VC_NAME="test-restore-$$"
NS="restore-test-$$"
BACKUP_FILE="/tmp/restore-test-$(date +%Y%m%d).db"

cleanup() {
  vcluster delete "$VC_NAME" -n "$NS" 2>/dev/null || true
  kubectl delete namespace "$NS" --ignore-not-found 2>/dev/null || true
  rm -f "$BACKUP_FILE"
}
trap cleanup EXIT

kubectl create namespace "$NS"
vcluster create "$VC_NAME" -n "$NS" --no-connect --skip-wait
vcluster wait --ready "$VC_NAME" -n "$NS" --timeout 5m

vcluster connect "$VC_NAME" -n "$NS" -- kubectl create deployment nginx --image=nginx
vcluster connect "$VC_NAME" -n "$NS" -- kubectl create secret generic test-secret --from-literal=key=value

VC_POD=$(kubectl -n "$NS" get pods -l app=vcluster -o jsonpath='{.items[0].metadata.name}')
kubectl -n "$NS" exec "$VC_POD" -c etcd -- \
  ETCDCTL_API=3 etcdctl snapshot save /tmp/snapshot.db
kubectl -n "$NS" cp "$VC_POD":/tmp/snapshot.db "$BACKUP_FILE"

vcluster delete "$VC_NAME" -n "$NS" --keep-pvc
vcluster create "$VC_NAME" -n "$NS" -f vcluster.yaml --no-connect
TARGET_POD=$(kubectl -n "$NS" get pods -l app=vcluster -o jsonpath='{.items[0].metadata.name}')
kubectl -n "$NS" cp "$BACKUP_FILE" "$TARGET_POD":/tmp/snapshot.db
kubectl -n "$NS" exec "$TARGET_POD" -c etcd -- \
  ETCDCTL_API=3 etcdctl snapshot restore /tmp/snapshot.db \
    --data-dir=/var/lib/etcd-restored
kubectl -n "$NS" delete pod "$TARGET_POD"

sleep 10
vcluster connect "$VC_NAME" -n "$NS" -- kubectl get deployment nginx
vcluster connect "$VC_NAME" -n "$NS" -- kubectl get secret test-secret

echo "Restore test PASSED"
```

### Рекомендуемая конфигурация бэкапов

| Параметр | Dev/Test | Staging | Production |
| :--- | :--- | :--- | :--- |
| **Частота** | 1 раз в сутки | Каждые 4 часа | Каждый час |
| **Хранение** | 7 дней | 14 дней | 30 дней |
| **Хранилище** | Локальный PVC | NFS/S3 | S3 с versioning |
| **Тест восстановления** | Нет | 1 раз в месяц | 1 раз в неделю |

### Диагностика проблем бэкапа

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `permission denied` | Нет доступа к сертификатам etcd | Проверить Secret `vcluster-etcd-certs` |
| Снапшот повреждён | etcd перезапущен во время снапшота | Использовать `--consistent` флаг |
| S3 upload `Access Denied` | Неверные credentials | Проверить Secret `s3-credentials`, IAM policy |
| Восстановление не находит данные | Неправильный `--data-dir` | Проверить путь в StatefulSet |

### Лучшие практики

- **Регулярные тесты восстановления:** 1 раз в месяц для staging, 1 раз в неделю для production
- **Хранение вне кластера:** S3/NFS, не локальный PVC
- **Версионирование:** S3 с versioning или снапшоты с меткой времени
- **Мониторинг бэкапов:** Алерт на отсутствие успешного бэкапа > RPO
- **Шифрование:** Бэкапы зашифрованы at-rest (S3 SSE, LUKS для NFS)
- **Документация:** Процедура восстановления в runbook

## Дополнительная информация

### Внутренние ссылки

- [vCluster — обзор и архитектура](./vcluster_overview.md)
- [vCluster — установка и развертывание](./vcluster_installation.md)
- [vCluster — высокая доступность](./vcluster_high_availability.md)

### См. также

- [etcd — стратегии бэкапа](../../etcd/backup_strategies.md)
- [Kubernetes — стратегии бэкапа](../../Kubernetes/Operations/backup-strategies.md)

### Внешние ссылки

- [vCluster Backup Documentation](https://www.vcluster.com/docs/provisioning/backup)
- [etcd Disaster Recovery](https://etcd.io/docs/v3.5/op-guide/recovery/)
