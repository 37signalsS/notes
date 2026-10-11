# etcd Operator и автоматизация

**Актуально для:** etcd-operator v0.2.0 (prerelease, 2026-03) / Bitnami etcd chart 12.x (appVersion etcd 3.6.4)

> **Статус:** etcd-operator v0.2.0 — prerelease. Для production оценивайте зрелость проекта; проверенные альтернативы — Bitnami Helm chart или self-managed подход (CronJob + etcdctl).

**etcd Operator** — Kubernetes-оператор, автоматизирующий жизненный цикл внешнего etcd-кластера: развёртывание, масштабирование, rolling upgrade и TLS. Оригинальный `coreos/etcd-operator` архивирован в 2020; проект возрождён рабочей группой WG etcd-operator под эгидой etcd-io: v0.1.0 (2025-03) и v0.2.0 (2026-03).

## Определения

| Термин | Описание |
| :--- | :--- |
| **etcd Operator** | Kubernetes Operator (Kubebuilder), управляющий жизненным циклом etcd-кластера через CRD. |
| **EtcdCluster CR** | Custom Resource (`operator.etcd.io/v1alpha1`) с желаемым состоянием кластера: `version`, `size`, `tls`. |
| **EtcdMember CR** | Custom Resource, представляющий отдельный участник кластера. |
| **CertificateProvider CR** | Custom Resource, описывающий провайдера сертификатов для TLS. |
| **Auto provider** | Провайдер TLS для dev/test: оператор сам выпускает сертификаты. |
| **Cert-Manager provider** | Провайдер TLS для production: сертификаты выпускает cert-manager; Issuer/ClusterIssuer создаёт пользователь. |
| **etcd-backup-restore** | Компонент (gardener/etcd-backup-restore): full + incremental снапшоты, валидация data directory, zero-downtime recovery, авто-defrag. |
| **etcdadm** | CLI-инструмент для управления etcd на VMs/bare metal (создаёт systemd-сервис). **Не является оператором**; репозиторий kubernetes-retired/etcdadm помечен EOL (2024). |
| **Self-healing** | Автоматическое восстановление после отказа узла: удаление участника из кластера и добавление нового. |

---

## Основные концепции

### Зачем нужна автоматизация

Ручное управление etcd в production включает:
- Rolling upgrade (drain, upgrade, add, remove).
- Backup scheduling и verification.
- Automatic failover (detect unhealthy node → replace).
- Certificate rotation.

Оператор автоматизирует это через **declarative management**: пользователь описывает желаемое состояние в `EtcdCluster`, а controller-manager сводит реальное состояние кластера к нему.

### История проекта

> **Статус:** `coreos/etcd-operator` не развивается с 2020 (последний релиз v0.9.4, 2019-02; поддержка etcd ≤ 3.4). Существует только для исторической справки.

| Этап | Дата | Суть |
| :--- | :--- | :--- |
| coreos/etcd-operator | 2016–2020 | Первый оператор; CRD `etcd.database.coreos.com/v1beta2` (EtcdCluster, EtcdBackup, EtcdRestore); бэкапы — отдельный etcd-backup-operator (Job'ы, не sidecar). Архивирован. |
| etcd-io/etcd-operator v0.1.0 | 2025-03 | Возрождение проекта (WG etcd-operator); Kubebuilder; новый API `operator.etcd.io/v1alpha1`. |
| etcd-io/etcd-operator v0.2.0 | 2026-03 | TLS-управление (Auto/Cert-Manager), upgrade с валидацией пути, scaling. Prerelease. |

### Что умеет v0.2.0 — и чего не умеет

**Умеет:**
- Создание кластера и масштабирование (`spec.size`).
- TLS для client и inter-member трафика: провайдеры `auto` (dev/test) и `cert-manager` (production).
- Upgrade etcd: patch внутри minor (3.6.0 → 3.6.2) и один minor за раз (3.5 → 3.6); для официальных образов etcd оператор валидирует путь автоматически.

**Не умеет (на v0.2.0):**
- **Бэкапы и restore** — в API нет backup/restore CR. Снапшоты делаются отдельно: CronJob с `etcdctl snapshot save` или gardener/etcd-backup-restore.
- Управление etcd вне Kubernetes (VM/bare metal) — для этого существовал etcdadm (EOL); сейчас — ручные процедуры.

### Архитектура

| Компонент | Назначение |
| :--- | :--- |
| **controller-manager** | Deployment в namespace `etcd-operator-system`; следит за EtcdCluster CR и сводит состояние к desired. |
| **CRD `etcdclusters.operator.etcd.io`** | Определяет ресурс EtcdCluster (связанные: EtcdMember, CertificateProvider). |
| **RBAC** | ClusterRole/ClusterRoleBinding для управления StatefulSet, Service, PVC, Secret. |

Поды etcd создаются с именами `<cluster>-<ordinal>` и меткой `controller=<cluster-name>`.

### Альтернативы автоматизации

| Решение | Тип | Статус | Когда использовать |
| :--- | :--- | :--- | :--- |
| **etcd-operator v0.2.0** | Kubernetes Operator | prerelease, активная разработка | Declarative управление внешним etcd в K8s: TLS, scaling, upgrade |
| **Bitnami etcd chart 12.x** | Helm chart (StatefulSet) | Активно поддерживается; etcd 3.6.4 | Быстрое развёртывание external etcd; встроенный DR (CronJob + авто-restore) |
| **gardener/etcd-backup-restore** | Компонент/sidecar | Активно поддерживается (Gardener) | Бэкапы (full + incremental), валидация data directory, zero-downtime recovery |
| **Self-managed (CronJob + etcdctl)** | Скрипты | — | Полный контроль; бэкапы без оператора |
| **OpenShift cluster-etcd-operator** | Vendor-специфичный | Активен в OpenShift | Только для etcd внутри OpenShift (автоматическая ротация сертификатов) |

---

## Практические сценарии

### Установка etcd-operator

**Prerequisites:** Kubernetes 1.30+, `kubectl`, service account с правами на ClusterRoles, CRDs, Deployments, Namespaces, Services.

```bash
# Установить оператор (install-файл из релиза v0.2.0)
curl -L https://github.com/etcd-io/etcd-operator/releases/download/v0.2.0/install-v0.2.0.yaml | kubectl apply -f -

# Проверить статус
kubectl get deployment -n etcd-operator-system
# → etcd-operator-controller-manager   1/1   1   1   49s
```

Удаление: `kubectl delete -f install-v0.2.0.yaml`.

### Создание кластера и валидация

```yaml
apiVersion: operator.etcd.io/v1alpha1
kind: EtcdCluster
metadata:
  name: test-cluster
spec:
  version: v3.6.15
  size: 3
```

```bash
kubectl apply -f etcdcluster.yaml

# Поды: <cluster>-<ordinal> с меткой controller=<cluster-name>
kubectl get pod -o wide -l controller=test-cluster
# → test-cluster-0/1/2   1/1   Running

# Собрать endpoints и записать ключ через etcdctl
ETCD_CLUSTER_IP_ADDRESSES=$(kubectl get pod -l controller=test-cluster -o jsonpath='{range .items[*]}{.status.podIP}:2379,{end}')
kubectl run etcd-client --attach --restart=Never --rm \
  --image gcr.io/etcd-development/etcd:<VERSION> \
  -- etcdctl --endpoints="$ETCD_CLUSTER_IP_ADDRESSES" put foo bar
# → OK
```

`<VERSION>` — тег etcd, совпадающий с `spec.version` (в примерах оператора используется `v3.5.21`).

### TLS через cert-manager (production)

Создание Issuer/ClusterIssuer — ответственность пользователя; оператор только использует указанный Issuer:

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: selfsigned
spec:
  selfSigned: {}
---
apiVersion: operator.etcd.io/v1alpha1
kind: EtcdCluster
metadata:
  name: etcd-cluster-tls
spec:
  version: v3.6.15
  size: 3
  tls:
    provider: "cert-manager"
    providerCfg:
      certManagerCfg:
        commonName: "etcd-operator-system"
        validityDuration: "8760h"
        issuerKind: "ClusterIssuer"
        issuerName: "selfsigned"
```

Если TLS включён, но провайдер не указан — по умолчанию `auto` (только dev/test).

### Upgrade кластера

Правила (совпадают с правилами проекта etcd):
- **Patch**: внутри одной minor (3.6.0 → 3.6.2).
- **Minor**: по одной версии за раз (3.5 → 3.6); пропуск minor не поддерживается.
- Перед переходом на следующую minor рекомендуется обновиться до последнего patch.
- Для официальных образов etcd оператор валидирует путь автоматически. **Кастомные теги без SemVer не валидируются** — ответственность пользователя.

### Масштабирование

Измените `spec.size` в EtcdCluster — оператор добавит/удалит участники через etcd API (member add/remove):

```bash
kubectl patch etcdcluster test-cluster --type merge -p '{"spec":{"size":5}}'
```

### Self-managed: Bitnami Helm chart

Чарт 12.x (appVersion etcd 3.6.4; prerequisites: K8s 1.23+, Helm 3.8+):

```bash
helm install my-release oci://registry-1.docker.io/bitnamicharts/etcd \
  --set replicaCount=3 \
  --set persistence.storageClass=local-nvme \
  --set persistence.size=20Gi \
  --set auth.rbac.rootPassword=<ROOT_PASSWORD> \
  --set auth.peer.secureTransport=true \
  --set auth.peer.useAutoTLS=true
```

Параметры: `auth.rbac.create` включён по умолчанию (создаёт пользователя `root`); TLS client-to-server — `auth.client.secureTransport=true` + `auth.client.existingSecret=<SECRET>`; метрики — `metrics.enabled=true`, `metrics.podMonitor.enabled=true`.

**Валидация:**
```bash
kubectl get pods -l app.kubernetes.io/name=etcd
# → my-release-etcd-0, my-release-etcd-1, my-release-etcd-2 — Running

kubectl exec my-release-etcd-0 -- etcdctl endpoint health
# → ...:2379 is healthy
```

**Как чарт обеспечивает self-healing:** pre-stop lifecycle hook выполняет `etcdctl member remove` при удалении пода (scale-down, drain узла); при старте пода участник добавляется обратно через `etcdctl member add`. Если hook отработал с ошибкой, логика инициализации обнаруживает это по выводу, сохранённому в PV, и добавляет участника через `etcdctl member update`.

**Встроенный DR:** `disasterRecovery.enabled=true` + `disasterRecovery.pvc.size=2Gi` + `disasterRecovery.pvc.storageClassName=<RWX_CLASS>` — CronJob периодически снапшотит keyspace в ReadWriteMany volume; при потере кворума поды восстанавливаются из последнего снапшота.

### Backup через CronJob (self-managed)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: etcd-backup
  namespace: default
spec:
  schedule: "0 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: gcr.io/etcd-development/etcd:<VERSION>
            env:
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
              etcdutl snapshot status /backup/etcd-${DATE}.db -w table
              # Скопировать снапшот в object storage (S3-compatible) или на отдельный PVC
          restartPolicy: OnFailure
```

Валидация целостности каждого снапшота (`etcdutl snapshot status`) обязательна — см. [Стратегии резервного копирования](./backup_strategies.md).

### Self-healing: замена отказавшего узла

Ручной playbook (member remove → member add --learner → promote) детально описан в [Кластеризация и восстановление](./clustering_and_recovery.md). Оператор и Bitnami chart выполняют те же шаги автоматически через etcd API.

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Operator не создаёт кластер | Нет StorageClass, PVC pending | `kubectl get pvc`; создать StorageClass |
| Operator не реагирует на изменения | CRD не установлена или RBAC запрещает | `kubectl get crd etcdclusters.operator.etcd.io`; проверить ClusterRole оператора |
| TLS не поднимается | Issuer/ClusterIssuer не создан или недоступен | Создать Issuer (ответственность пользователя); проверить `issuerKind`/`issuerName` в `providerCfg` |
| Upgrade не валидируется | Кастомный тег образа не соответствует SemVer | Валидация работает только для официальных образов etcd; проверяйте путь вручную |
| Backup Job FAIL | Неверные TLS-сертификаты или endpoints | Проверить env-переменные; `etcdctl endpoint health` |
| Restore не завершается | Недостаточно места на диске | `df -h`; освободить место |
| Bitnami: ошибки `rafthttp: failed to dial` после перепланирования пода | pre-stop hook не отработал; участник не удалён | Чарт сам восстановит через `member update`; при сохранении — удалить участника вручную (`etcdctl member remove`) |

---

## Best Practices

- **Тестируйте в staging:** upgrade, restore, failover — перед применением в production.
- **cert-manager для production TLS:** провайдер `auto` — только для dev/test.
- **Immutable tags:** пините версию etcd в `spec.version` и образах; не используйте `latest`.
- **Бэкапы вне кластера:** снапшоты — в object storage или отдельный PVC; храните копии offsite.
- **Проверяйте снапшоты:** `etcdutl snapshot status` после каждого бэкапа.
- **StatefulSet для etcd:** стабильные DNS-имена (`etcd-0.etcd-headless...`) обязательны для peer discovery.
- **Local PV на NVMe** вместо network storage для data-томов — см. [Тестирование производительности](./benchmarking.md).

---

## Edge Cases

- **Prerelease-статус v0.2.0:** функциональность может меняться; проверяйте compatibility перед апгрейдом оператора.
- **Кастомные образы без SemVer:** оператор не валидирует upgrade path — проверяйте вручную.
- **Restore создаёт новый кластер:** восстановление из снапшота — это новый кластер (новый `cluster-token`); «восстановить в живой кластер» нельзя — см. [Аварийное восстановление](./emergency_recovery.md).
- **Split-brain при self-healing:** если старый узел «воскреснет» после замены, убедитесь, что он полностью удалён из кластера (`member remove`).
- **Bitnami DR требует ReadWriteMany** volumes (например, NFS) — не работает с RWO-томами.
- **Operator не управляет бэкапами:** на v0.2.0 бэкапы — отдельная задача (CronJob или etcd-backup-restore).

---

## См. также

* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — member add/remove, learner, restore.
* **[Стратегии резервного копирования](./backup_strategies.md)** — snapshot vs logical backup.
* **[Аварийное восстановление](./emergency_recovery.md)** — `--force-new-cluster` и DR.
* **[Безопасность etcd](./security.md)** — ротация сертификатов, RBAC.
* **[Конфигурация и развертывание](./configuration_and_deployment.md)** — etcd.conf.yml, systemd, Static Pod.
* **[Шпаргалка etcdctl](./etcdctl_cheatsheet.md)** — snapshot и member-команды.
* **[etcd в Kubernetes](./kubernetes_integration.md)** — etcd как часть Control Plane.
* **[Систематический troubleshooting](./troubleshooting.md)** — playbook для production.
