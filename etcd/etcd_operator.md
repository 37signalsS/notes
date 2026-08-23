# etcd Operator и автоматизация

**etcd Operator** — это Kubernetes-оператор, который автоматизирует развертывание, масштабирование, обновление и восстановление etcd-кластера. Используется в production для снижения операционной нагрузки и обеспечения self-healing.

## Определения

| Термин | Описание |
| :--- | :--- |
| **etcd Operator** | Kubernetes Operator, управляющий жизненным циклом etcd-кластера (развертывание, backup, restore, upgrade). |
| **etcd-operator (alibaba)** | Популярный open-source operator (устарел, не поддерживает v3.7). |
| **etcd Cluster CR** | Custom Resource, определяющий желаемое состояние кластера (размер, версия, storage). |
| **Self-healing** | Автоматическое восстановление после отказа узла (добавление нового, удаление старого). |
| **Backup Sidecar** | Sidecar-контейнер в каждом etcd-поде, отвечающий за автоматические снапшоты. |
| **Restore CR** | Custom Resource для восстановления кластера из снапшота. |

---

## Основные концепции

### Зачем нужен Operator

Ручное управление etcd в production включает:
- Rolling upgrade (drain, upgrade, add, remove).
- Backup scheduling и verification.
- Automatic failover (detect unhealthy node → replace).
- Certificate rotation.

Operator автоматизирует это, обеспечивая **declarative management**:
```yaml
apiVersion: etcd.database.coreos.com/v1beta2
kind: EtcdCluster
metadata:
  name: etcd
spec:
  size: 3
  version: 3.7.1
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: local-nvme
        resources:
          requests:
            storage: 20Gi
  backup:
    backupIntervalInSecond: 900
    backupStorageType: s3
    s3:
      s3Bucket: my-etcd-backups
```

### Архитектура Operator

| Компонент | Назначение |
| :--- | :--- |
| **Operator Controller** | Отслеживает EtcdCluster CR и поддерживает desired state. |
| **Backup Sidecar** | Запускается в каждом etcd-поде. Делает снапшоты по расписанию. |
| **Restore Job** | Job, восстанавливающий кластер из снапшота при необходимости. |
| **Peer Finder** | Отвечает за обнаружение пиров (инициализация `--initial-cluster`). |

### Популярные реализации

| Operator | Поддержка v3.7 | Статус |
| :--- | :--- | :--- |
| **etcd-operator (coreos)** | Нет (последний релиз 2020) | Архивирован |
| **etcdadm** | Да (3.7+) | Активно развивается |
| **kube-etcd-operator** | Да | Используется в некоторых дистрибутивах K8s |
| **Self-managed (CronJob + scripts)** | Да | Рекомендуется для полного контроля |

**Рекомендация (2026):** Для production K8s часто проще использовать **Self-managed** подход (CronJob для бэкапов + Helm chart для развертывания), так как большинство операторов отстают от релизов etcd.

---

## Практические сценарии

### Self-managed: Развертывание через Helm

```bash
# Добавить репозиторий
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

# Установить external etcd
helm install etcd bitnami/etcd \
  --set replicaCount=3 \
  --set image.tag=3.7.1 \
  --set persistence.storageClass=local-nvme \
  --set persistence.size=20Gi \
  --set auth.rbac.create=true \
  --set auth.rbac.rootPassword=secret \
  --set tls.enabled=true
```

**Валидация:**
```bash
kubectl get pods -l app=etcd
# → etcd-0, etcd-1, etcd-2 — Running

kubectl exec -it etcd-0 -- etcdctl endpoint health --cluster
# → all endpoints healthy
```

### Self-managed: Автоматический backup через CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: etcd-backup
  namespace: kube-system
spec:
  schedule: "*/15 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: bitnami/etcd:3.7.1
            env:
            - name: ETCDCTL_API
              value: "3"
            - name: ETCDCTL_ENDPOINTS
              value: "https://etcd-0.etcd-headless.default.svc.cluster.local:2379"
            - name: ETCDCTL_CACERT
              value: "/etc/etcd/pki/ca.crt"
            - name: ETCDCTL_CERT
              value: "/etc/etcd/pki/etcd.crt"
            - name: ETCDCTL_KEY
              value: "/etc/etcd/pki/etcd.key"
            command:
            - /bin/sh
            - -c
            - |
              DATE=$(date +%Y%m%d%H%M%S)
              etcdctl snapshot save /backup/etcd-${DATE}.db
              # Upload to S3
              aws s3 cp /backup/etcd-${DATE}.db s3://my-backups/etcd/
          restartPolicy: OnFailure
```

### Self-healing: Замена отказавшего узла

Если используется External etcd + Operator:
1. Operator обнаруживает unhealthy узел через `endpoint health`.
2. Operator создает новый pod с тем же `--name` и `peer URL`.
3. Новый pod присоединяется к кластеру как learner.
4. После синхронизации learner promote до voting member.
5. Старый pod удаляется.

**Без Operator (ручной playbook):**
```bash
# 1. Проверить, что узел не leader
etcdctl endpoint status --cluster -w table

# 2. Удалить неработающий узел
etcdctl member remove <MEMBER_ID>

# 3. Добавить новый узел как learner
etcdctl member add new-node --peer-urls=https://10.0.1.15:2380 --learner

# 4. Запустить etcd на новом узле
systemctl start etcd

# 5. Промоутить
etcdctl member promote <NEW_MEMBER_ID>
```

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Operator не создает кластер | Нет StorageClass или PVC pending | Проверить `kubectl get pvc`; создать StorageClass |
| Backup Job FAIL | Неверные TLS сертификаты или endpoints | Проверить env vars; проверить `etcdctl endpoint health` |
| Restore не завершается | Недостаточно места на диске | Освободить место; проверить `df -h` |
| Operator не реагирует на changes | CRD устарел или RBAC запрещает | Проверить `kubectl get crd`; проверить RBAC оператора |
| Self-healing вызывает flapping | Learner слишком быстро промоутируется | Увеличить порог синхронизации (если operator поддерживает) |

---

## Best Practices

- **Не полагайтесь на Operator без тестирования:** Протестируйте upgrade, restore, failover в staging.
- **Backup — вне кластера:** Sidecar бэкап полезен, но храните копии вне кластера (S3, offsite).
- **Certificate rotation:** Если Operator поддерживает, используйте его. Иначе автоматизируйте через Cert Manager.
- **StatefulSet для etcd:** Все production развертывания используют StatefulSet (стабильные DNS: `etcd-0.etcd-headless`).
- **Local PV для production:** Используйте Local Persistent Volumes на NVMe, а не network storage.

---

## Edge Cases

- **Operator и rolling upgrade:** Operator должен поддерживать версию etcd, которую вы планируете использовать. Проверяйте compatibility matrix.
- **Restore на существующий кластер:** Используйте новый `cluster-token`, иначе данные "сольются".
- **Backup во время restore:** Не выполняйте backup и restore одновременно на одном кластере.
- **Split-brain при self-healing:** Если старый узел "воскреснет" после замены, убедитесь, что он полностью удален из кластера (`member remove`).

---

## См. также

* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — развертывание и DR.
* **[Шпаргалка etcdctl](./etcdctl_cheatsheet.md)** — snapshot и restore команды.
* **[Конфигурация и развертывание](./configuration_and_deployment.md)** — Static Pod и systemd.
