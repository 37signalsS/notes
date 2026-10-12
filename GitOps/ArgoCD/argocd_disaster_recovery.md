# Argo CD: Disaster Recovery — бэкап, восстановление и отказоустойчивость

**Актуально для:** Argo CD v3.6.x / v2.14

> **Контекст применения (DevOps / SRE / Sysadmin):** Руководство ориентировано на эксплуатацию Argo CD в корпоративных контурах, локальных дата-центрах (on-premise) и на bare-metal инфраструктуре Kubernetes (kubeadm, RKE2, Talos). Исключены зависимости от проприетарных облачных сервисов; в качестве объектных хранилищ используются S3-совместимые решения локального развертывания (MinIO, Ceph Object Gateway).

## Предварительные требования

1. **Kubernetes кластер:** v1.26+ (kubeadm, RKE2, k3s или bare-metal инсталляция).
2. **Установленный Argo CD:** версии v2.14+ или v3.x (см. [Установка и настройка](./argocd_installation_and_setup.md)).
3. **Утилиты управления:**
   - `kubectl` с правами `cluster-admin` для управления ресурсами кластера.
   - `argocd` CLI соответствующей версии сервера.
   - `etcdctl` / `etcdutl` v3.5+ (для прямого создания и восстановления снапшотов etcd на control-plane нодах).
   - `mc` (MinIO Client) для работы с локальным S3-хранилищем резервных копий.
4. **Хранилище резервных копий:** Доступ к локальному S3-совместимому хранилищу (MinIO / Ceph RGW) или выделенному NFS/iSCSI разделу с гарантированной изоляцией от основного кластера.
5. **Git-репозитории:** Доступ по SSH/HTTPS к корпоративному Git-серверу (GitLab, Gitea) с манифестами инфраструктуры и приложений.

## Определения

**Disaster Recovery (DR, Аварийное восстановление)** — комплекс регламентов, архитектурных решений и автоматизированных процедур, обеспечивающих восстановление работоспособности управляющего контура GitOps и целевых кластеров после катастрофических аппаратных сбоев, повреждения баз данных, сетевых разделений ЦОД или компрометации окружения.

**Recovery Point Objective (RPO)** — максимально допустимый объем потенциально потерянных данных управляющего контура, выраженный во времени (например, дельта между созданием снапшота и моментом аварии). Для GitOps-состояния RPO стремится к нулю, так как истинное состояние зафиксировано в Git-коммитах.

**Recovery Time Objective (RTO)** — целевое время, необходимое для полного восстановления управляющего контура Argo CD, синхронизации статусов приложений и возобновления автоматической доставки манифестов.

**State Export (`argocd admin export`)** — процедура выгрузки декларативного состояния всех сущностей Argo CD (Applications, AppProjects, ApplicationSets, ConfigMaps, Secrets, сертификаты и репозитории) из etcd в единый сериализованный YAML-поток.

**State Import (`argocd admin import`)** — процедура инъекции ранее экспортированного декларативного состояния в чистый или восстанавливаемый кластер с опциональной очисткой отсутствующих сущностей (`--prune`) и подавлением конфликтов отслеживания ресурсов.

**Decoupled Runtime (Развязка управляющего и исполнительного контуров)** — фундаментальное свойство архитектуры GitOps: при полном отказе подов и баз данных Argo CD все рабочие нагрузки (Deployments, StatefulSets, Pods), запущенные в целевых кластерах, продолжают непрерывно функционировать без деградации. DR затрагивает исключительно плоскость управления доставкой (Control Plane).

**Split-Brain в GitOps** — катастрофическое состояние при наличии двух одновременно активных контроллеров Argo CD в разных дата-центрах (Active-Active), пытающихся синхронизировать одну и ту же целевую инфраструктуру с расходящимися параметрами, что приводит к циклическому взаимному удалению и пересозданию ресурсов.

**Sync Windows** — механизм временных окон в `AppProject`, блокирующий автоматическую или ручную синхронизацию приложений. В сценариях DR используется для перевода резервного кластера в режим заморозки (Safe Standby) без риска несанкционированного внесения изменений.

**Finalizer Cascade Trap** — ситуация, при которой удаление ресурсов `Application` или `ApplicationSet` с установленным финализатором `resources-finalizer.argocd.argoproj.io` в процессе аварийной миграции приводит к физическому уничтожению всей полезной нагрузки в целевом кластере.

## Базовые концепции и архитектура

### Что и где хранит Argo CD

Для построения надежного плана DR необходимо разделять компоненты системы по степени критичности данных и источникам истины:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                          ГДЕ ХРАНИТСЯ СОСТОЯНИЕ                        │
├──────────────────────────┬─────────────────────────────────────────────┤
│ 1. Git / OCI Реестры     │ • Исходные манифесты, Helm-чарты, Kustomize │
│ (Single Source of Truth) │ • Конфигурация кластеров (App-of-Apps)      │
│                          │ • RPO = 0 (гарантируется распределенным Git)│
├──────────────────────────┼─────────────────────────────────────────────┤
│ 2. Kubernetes etcd       │ • CRD: Application, AppProject, AppSet      │
│ (Кластерное состояние)   │ • Секреты: cluster credentials, repo creds  │
│                          │ • Конфигурации: argocd-cm, argocd-rbac-cm   │
│                          │ • Пользовательские токены и ключи шифрования│
├──────────────────────────┼─────────────────────────────────────────────┤
│ 3. Redis / Redis-HA      │ • Кэш манифестов Git-репозиториев           │
│ (Эфемерный кэш)          │ • Кэш версий объектов API Kubernetes        │
│                          │ • Сессионные токены веб-интерфейса          │
│                          │ • НЕ ТРЕБУЕТ БЭКАПА (пересобирается на лету)│
└──────────────────────────┴─────────────────────────────────────────────┘
```

> **Важно для SRE:** Redis является исключительно кэширующим слоем. При полной потере или перезапуске Redis контроллер `argocd-application-controller` и `argocd-repo-server` просто выполнят повторное клонирование Git-репозиториев и повторный опрос API Kubernetes. Бэкапить Redis не требуется.

### Стратегии Disaster Recovery

| Стратегия | Реализация | RPO | RTO | Сложность | Область применения |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1. GitOps Re-bootstrap** | Развертывание чистого Argo CD из Helm/Kustomize + запуск корневого App-of-Apps | ~0 (Git) | 15–30 мин | Низкая | Полный снос кластера; секреты хранятся в HashiCorp Vault или SOPS |
| **2. `argocd admin export`** | Периодический экспорт всех CRD и секретов в S3 (MinIO) | Интервал бэкапа (15–60 мин) | 5–10 мин | Средняя | Стандартный корпоративный регламент для локальных инсталляций |
| **3. Velero (On-Premise)** | Бэкап пространства имен `argocd` и CRD через Velero в MinIO | Интервал бэкапа (1–4 ч) | 5–15 мин | Средняя | Комплексный бэкап инфраструктурных неймспейсов кластера |
| **4. etcd Snapshot** | Снапшот BoltDB на уровне bare-metal нод control plane | Интервал снапшота (1–6 ч) | 20–40 мин | Высокая | Катастрофический сбой кластера управления Kubernetes целиком |
| **5. Warm Standby (Multi-DC)** | Резервный инстанс Argo CD во втором ЦОД с замороженным циклом синхронизации | ~0 | 1–3 мин | Высокая | Критичные контуры 24/7 с жесткими SLA по доступности доставки |

### Архитектура резервного копирования и восстановления (On-Premise)

```text
[ ОСНОВНОЙ ЦОД (DC-1) ]                                [ ХРАНИЛИЩЕ БЭКАПОВ (S3 / MinIO) ]
┌───────────────────────────────────────┐              ┌─────────────────────────────────┐
│ Kubernetes Control Plane              │              │ Локальный отказоустойчивый пул  │
│  ┌──────────────┐   ┌──────────────┐  │              │ MinIO / Ceph Object Gateway     │
│  │ argocd-server│   │ repo-server  │  │              │                                 │
│  └──────┬───────┘   └──────┬───────┘  │              │  s3://k8s-backups/argocd/       │
│         │                  │          │              │  ├── 2026-10-12-0000.yaml.enc   │
│  ┌──────┴──────────────────┴───────┐  │              │  ├── 2026-10-12-0100.yaml.enc   │
│  │ argocd-application-controller   │  │   CronJob    │  └── latest.yaml.enc            │
│  └─────────────────┬───────────────┘  │   Export     │                                 │
│                    │                  │─────────────▶│                                 │
│  ┌─────────────────▼───────────────┐  │              └────────────────┬────────────────┘
│  │ etcd (CRDs, Secrets, ConfigMaps)│  │                               │
│  └─────────────────────────────────┘  │                               │
└───────────────────────────────────────┘                               │
                                                                        │ Failover /
                                                                        │ Import
[ РЕЗЕРВНЫЙ ЦОД (DC-2) — АВАРИЙНОЕ ВОССТАНОВЛЕНИЕ ]                     │
┌──────────────────────────────────────────────────────────────────┐    │
│ Чистый кластер Kubernetes / Standby контур                       │    │
│  ┌────────────────────────────────────────────────────────────┐  │    │
│  │ 1. Установка базового Argo CD (Helm / manifests)           │  │    │
│  │ 2. argocd admin import < latest.yaml                       │◀─┼────┘
│  │ 3. Валидация подключений к кластерам и Git                 │  │
│  │ 4. Снятие блокировок Sync Windows и включение reconciler   │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

## Практические сценарии

### Сценарий 1: Декларативный бэкап через argocd admin export

Утилита `argocd admin export` извлекает все связанные сущности Argo CD напрямую через API Kubernetes (требуются права доступа к API, запущенный сервер Argo CD не обязателен).

#### 1. Полный экспорт всех данных в единый файл
```bash
# Экспорт ресурсов пространства имен argocd
argocd admin export -n argocd -o /var/backups/argocd/argocd-backup-$(date +%F_%H%M%S).yaml
# → Exporting all Argo CD data to /var/backups/argocd/argocd-backup-2026-10-12_133000.yaml
```

Если приложения распределены по нескольким пространствам имен (Applications in any namespace):
```bash
argocd admin export -n argocd \
  --application-namespaces "team-*,prod-*,stage-*" \
  --applicationset-namespaces "team-*,prod-*" \
  -o /var/backups/argocd/argocd-backup-full.yaml
# → Successfully exported Argo CD data from control-plane and matched namespaces
```

#### 2. Запуск экспорта через изолированный контейнер без установки локального CLI
Если на хосте администратора не установлен бинарник `argocd`, экспорт выполняется через официальный образ контейнера:
```bash
docker run --rm \
  -v "${HOME}/.kube/config:/home/argocd/.kube/config:ro" \
  quay.io/argoproj/argocd:v3.6.0 \
  argocd admin export -n argocd > /var/backups/argocd/argocd-export-standalone.yaml
# → Файл содержит манифесты ConfigMaps, Secrets, Applications, AppProjects
```

#### 3. Гранулярный экспорт отдельных сущностей через kubectl
Если требуется сделать выборочный бэкап конкретных типов ресурсов для последующего избирательного наката:
```bash
BACKUP_DIR="/var/backups/argocd/granular_$(date +%F)"
mkdir -p "${BACKUP_DIR}"

# Экспорт проектов
kubectl get appprojects.argoproj.io -n argocd -o yaml > "${BACKUP_DIR}/01-appprojects.yaml"

# Экспорт приложений
kubectl get applications.argoproj.io -n argocd -o yaml > "${BACKUP_DIR}/02-applications.yaml"

# Экспорт генераторов ApplicationSet
kubectl get applicationsets.argoproj.io -n argocd -o yaml > "${BACKUP_DIR}/03-applicationsets.yaml"

# Экспорт учетных записей репозиториев и кластеров
kubectl get secrets -n argocd -l "argocd.argoproj.io/secret-type" -o yaml > "${BACKUP_DIR}/04-argocd-secrets.yaml"

# Экспорт настроек и RBAC
kubectl get configmap argocd-cm argocd-rbac-cm argocd-cmd-params-cm -n argocd -o yaml > "${BACKUP_DIR}/05-argocd-cms.yaml"

# Проверка сформированных файлов
ls -lh "${BACKUP_DIR}"
# → -rw-r--r-- 1 root root  45K Oct 12 13:35 01-appprojects.yaml
# → -rw-r--r-- 1 root root 320K Oct 12 13:35 02-applications.yaml
# → -rw-r--r-- 1 root root  28K Oct 12 13:35 03-applicationsets.yaml
# → -rw-r--r-- 1 root root  14K Oct 12 13:35 04-argocd-secrets.yaml
# → -rw-r--r-- 1 root root 8.2K Oct 12 13:35 05-argocd-cms.yaml
```

---

### Сценарий 2: Восстановление через argocd admin import

Операция импорта принимает ранее сформированный файл бэкапа и атомарно применяет манифесты к целевому пространству имен.

#### 1. Предварительная валидация (Dry-Run)
Перед выполнением боевого импорта обязательно проверяется синтаксис и отсутствие блокирующих коллизий:
```bash
argocd admin import -n argocd --dry-run /var/backups/argocd/argocd-backup-full.yaml
# → [DRY-RUN] Verification completed. 142 resources parsed, 0 errors detected.
```

#### 2. Боевой импорт данных
```bash
# Импорт с перезаписью при возникновении конфликтов
argocd admin import -n argocd --override-on-conflict /var/backups/argocd/argocd-backup-full.yaml
# → Successfully imported 12 projects, 85 applications, 6 secrets, 3 configmaps
```

> **Предупреждение по флагу `--prune`:** Использование `argocd admin import --prune` приведет к немедленному физическому удалению из кластера всех объектов `Application`, `AppProject` и секретов, отсутствующих в файле бэкапа. Применяйте `--prune` исключительно при восстановлении кластера в идентичное прошлое состояние при ликвидации последствий несанкционированного изменения.

#### 3. Перезапуск компонентов для сброса кэша и инициализации
После наката секретов и конфигураций перезапустите контроллеры для применения новых параметров и прогрева внутреннего кэша:
```bash
kubectl rollout restart deployment argocd-server -n argocd
# → deployment.apps/argocd-server restarted

kubectl rollout restart statefulset argocd-application-controller -n argocd || \
kubectl rollout restart deployment argocd-application-controller -n argocd
# → statefulset.apps/argocd-application-controller restarted

# Ожидание готовности подов
kubectl rollout status statefulset argocd-application-controller -n argocd --timeout=120s
# → statefulset rolling update complete 2 pods at revision ...
```

#### 4. Пост-проверка контура восстановления
```bash
# Проверка доступности подключенных кластеров
argocd cluster list
# → SERVER                          NAME        STATUS      MESSAGE
# → https://kubernetes.default.svc  in-cluster  Successful  
# → https://192.168.10.50:6443      k8s-prod-1  Successful  

# Проверка общего статуса синхронизации и здоровья
argocd app list
# → NAME         CLUSTER     STATUS    HEALTH   AUTO-SYNC
# → ingress-ctl  k8s-prod-1  Synced    Healthy  Manual
# → payment-api  k8s-prod-1  Synced    Healthy  Auto
```

---

### Сценарий 3: Автоматический CronJob с выгрузкой в MinIO и шифрованием

Для продуктивных сред создается изолированный Kubernetes CronJob, выполняющий экспорт, шифрование симметричным ключом (GnuPG) и выгрузку в локальный MinIO S3-бакет с ротацией.

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: argocd-backup-sa
  namespace: argocd
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: argocd-backup-role
rules:
  - apiGroups: [""]
    resources: ["configmaps", "secrets"]
    verbs: ["get", "list"]
  - apiGroups: ["argoproj.io"]
    resources: ["applications", "appprojects", "applicationsets"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: argocd-backup-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: argocd-backup-role
subjects:
  - kind: ServiceAccount
    name: argocd-backup-sa
    namespace: argocd
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: argocd-s3-backup
  namespace: argocd
spec:
  schedule: "0 */2 * * *" # Каждые 2 часа
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 5
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: argocd-backup-sa
          restartPolicy: OnFailure
          containers:
            - name: backup-worker
              image: minio/mc:RELEASE.2025-01-17T23-25-50Z
              env:
                - name: MINIO_ENDPOINT
                  value: "http://minio.storage.local:9000"
                - name: MINIO_ACCESS_KEY
                  valueFrom:
                    secretKeyRef:
                      name: argocd-backup-credentials
                      key: access-key
                - name: MINIO_SECRET_KEY
                  valueFrom:
                    secretKeyRef:
                      name: argocd-backup-credentials
                      key: secret-key
                - name: BACKUP_ENCRYPTION_PASSPHRASE
                  valueFrom:
                    secretKeyRef:
                      name: argocd-backup-credentials
                      key: passphrase
              command:
                - /bin/sh
                - -c
                - |
                  set -eo pipefail
                  TIMESTAMP=$(date +%Y%m%d_%H%M%S)
                  BACKUP_FILE="/tmp/argocd-backup-${TIMESTAMP}.yaml"
                  ENC_FILE="${BACKUP_FILE}.enc"

                  echo "=== Установка kubectl и argocd CLI ==="
                  curl -fsSL -o /usr/local/bin/kubectl https://dl.k8s.io/release/v1.31.0/bin/linux/amd64/kubectl
                  chmod +x /usr/local/bin/kubectl

                  curl -fsSL -o /usr/local/bin/argocd https://github.com/argoproj/argo-cd/releases/download/v3.6.0/argocd-linux-amd64
                  chmod +x /usr/local/bin/argocd

                  echo "=== Экспорт данных Argo CD ==="
                  /usr/local/bin/argocd admin export -n argocd -o "${BACKUP_FILE}"

                  echo "=== Шифрование резервной копии ==="
                  gpg --batch --yes --passphrase "${BACKUP_ENCRYPTION_PASSPHRASE}" \
                      --symmetric --cipher-algo AES256 -o "${ENC_FILE}" "${BACKUP_FILE}"

                  echo "=== Отправка в MinIO ==="
                  mc alias set onprem-minio "${MINIO_ENDPOINT}" "${MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY}"
                  mc cp "${ENC_FILE}" onprem-minio/argocd-backups/daily/

                  echo "=== Ротация: удаление бэкапов старше 14 дней ==="
                  mc rm --recursive --force --older-than 14d onprem-minio/argocd-backups/daily/

                  echo "=== Резервное копирование успешно завершено ==="
```

---

### Сценарий 4: Disaster Recovery через Velero (On-Premises / MinIO)

Velero обеспечивает консистентный бэкап ресурсов Kubernetes и связанных PVC на уровне API без привязки к внешним облакам.

#### 1. Конфигурация BackupStorageLocation для локального MinIO
```yaml
apiVersion: velero.io/v1
kind: BackupStorageLocation
metadata:
  name: minio-bsp
  namespace: velero
spec:
  provider: aws # Используется стандартный S3 API-совместимый драйвер
  objectStorage:
    bucket: velero-k8s-backups
    prefix: argocd
  config:
    region: minio
    s3ForcePathStyle: "true"
    s3Url: http://minio.storage.local:9000
```

#### 2. Создание резервной копии пространства имен Argo CD
```bash
# Создание бэкапа неймспейса и всех связанных CRD
velero backup create argocd-manual-backup \
  --include-namespaces argocd \
  --include-cluster-resources=true \
  --storage-location minio-bsp \
  --wait
# → Backup completed with status: Completed. (0 errors, 0 warnings)
```

#### 3. Аварийное восстановление из бэкапа Velero
```bash
# Запуск восстановления в восстанавливаемом кластере
velero restore create --from-backup argocd-manual-backup \
  --restore-volumes=true \
  --wait
# → Restore completed with status: Completed.

# Проверка статуса подов в пространстве имен argocd
kubectl get pods -n argocd -o wide
# → All pods transitioned to Running state
```

---

### Сценарий 5: Снапшот и восстановление etcd на Bare-Metal кластере

При аппаратной гибели всех master-нод кластера или нарушении целостности BoltDB восстановление выполняется на уровне системных демонов etcd.

#### 1. Создание снапшота на рабочей control-plane ноде
```bash
# Создание моментального снимка etcd через локальный сокет/IP
sudo ETCDCTL_API=3 etcdctl snapshot save /var/backups/etcd/etcd-snapshot-$(date +%F).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key
# → Snapshot saved at /var/backups/etcd/etcd-snapshot-2026-10-12.db

# Верификация целостности контрольной суммы снапшота
sudo ETCDCTL_API=3 etcdutl snapshot status /var/backups/etcd/etcd-snapshot-$(date +%F).db --write-out=table
# → +----------+----------+------------+------------+
# → |   HASH   | REVISION | TOTAL KEYS | TOTAL SIZE |
# → +----------+----------+------------+------------+
# → | d41d8cd9 | 18542019 |      35120 |      48 MB |
# → +----------+----------+------------+------------+
```

#### 2. Процедура восстановления etcd на резервном хосте
```bash
# 1. Остановка статических подов kube-apiserver и etcd
sudo mv /etc/kubernetes/manifests/kube-apiserver.yaml /tmp/
sudo mv /etc/kubernetes/manifests/etcd.yaml /tmp/

# 2. Остановка службы etcd (если развернута как systemd-сервис)
sudo systemctl stop etcd || true

# 3. Архивирование поврежденного каталога данных
sudo mv /var/lib/etcd /var/lib/etcd.bak.$(date +%s)

# 4. Инициализация нового каталога данных из снапшота
sudo ETCDCTL_API=3 etcdutl snapshot restore /var/backups/etcd/etcd-snapshot-2026-10-12.db \
  --data-dir=/var/lib/etcd \
  --name=master-01 \
  --initial-cluster=master-01=https://192.168.10.11:2380 \
  --initial-cluster-token=etcd-cluster-restore \
  --initial-advertise-peer-urls=https://192.168.10.11:2380

# 5. Коррекция прав доступа к файлам БД
sudo chown -R etcd:etcd /var/lib/etcd || sudo chown -R root:root /var/lib/etcd

# 6. Возврат манифестов control plane
sudo mv /tmp/etcd.yaml /etc/kubernetes/manifests/
sudo mv /tmp/kube-apiserver.yaml /etc/kubernetes/manifests/

# 7. Проверка готовности etcd и API-сервера
sudo ETCDCTL_API=3 etcdctl endpoint health \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key
# → https://127.0.0.1:2379 is healthy: successfully committed proposal: took = 2.14ms
```

---

### Сценарий 6: Multi-Cluster Failover (Active-Passive) между ЦОД без Split-Brain

Организация катастрофоустойчивости между двумя независимыми ЦОД (DC-1 и DC-2) по схеме Active-Passive.

#### Архитектурные требования:
1. **SSoT:** Единственным источником конфигурации является Git-репозиторий.
2. **Исключение Split-Brain:** В режиме ожидания инстанс Argo CD в DC-2 не должен выполнять запись в общие кластеры или бороться за владение ресурсами с контроллером DC-1.
3. **Защита ресурсов:** Резервный инстанс замораживается с помощью глобальных `Sync Windows` в `AppProject`.

```text
[ DC-1 (Активный ЦОД) ]                     [ DC-2 (Резервный ЦОД) ]
┌─────────────────────────┐                 ┌─────────────────────────┐
│ Argo CD (Active)        │                 │ Argo CD (Standby)       │
│ Replicas = 2            │                 │ Replicas = 2            │
│ Sync Windows: ALLOW     │                 │ Sync Windows: BLOCK ALL │
│ Auto-Sync: ENABLED      │                 │ Auto-Sync: SUSPENDED    │
└────────────┬────────────┘                 └────────────┬────────────┘
             │                                           │
             ▼                                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   Целевые кластеры инфраструктуры                   │
└─────────────────────────────────────────────────────────────────────┘
```

#### 1. Конфигурация Safe Standby на инстансе DC-2 через Sync Windows
В резервном кластере накладывается блокировка автоматической и ручной синхронизации на уровне проекта `default` (или кастомных `AppProject`):
```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: default
  namespace: argocd
spec:
  description: Default project with DR lock enabled
  syncWindows:
    - kind: block
      schedule: "* * * * *" # Заблокировано всегда
      duration: 24h
      applications:
        - "*"
      clusters:
        - "*"
      namespaces:
        - "*"
      manualSync: false # Запрет даже ручной синхронизации операторами
```

#### 2. Регламент переключения (Failover Playbook при аварии DC-1)

**Шаг 1: Изоляция (Fencing) упавшего ЦОД DC-1**
Если DC-1 частично доступен или испытывает сетевой flapping, принудительно останавливается его контроллер для исключения гонки:
```bash
# Остановка контроллера в DC-1 (при наличии доступа)
kubectl scale statefulset argocd-application-controller -n argocd --replicas=0 --context=ctx-dc1 || true
```

**Шаг 2: Снятие блокировки синхронизации в DC-2**
```bash
# Удаление блокирующего окна Sync Windows в DC-2
kubectl patch appproject default -n argocd --type=json \
  -p='[{"op": "remove", "path": "/spec/syncWindows"}]' --context=ctx-dc2
# → appproject.argoproj.io/default patched
```

**Шаг 3: Переключение внешнего трафика и DNS**
Сетевые балансировщики (BGP Anycast, Keepalived или внешний DNS) переводят домен `argocd.company.local` на виртуальный IP-адрес Ingress в DC-2.

**Шаг 4: Принудительный Reconcile ключевых сервисов**
```bash
argocd app sync -l "tier=critical" --context=ctx-dc2
# → Initiated sync for 15 critical applications
```

---

### Сценарий 7: Чистое пересоздание из Git (Pure GitOps Bootstrap)

Если etcd и бэкапы уничтожены безвозвратно, GitOps позволяет поднять управляющий контур "с чистого листа" за считанные минуты.

#### 1. Развертывание базового манифеста Argo CD
```bash
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/v3.6.0/manifests/ha/install.yaml
# → namespace/argocd created
# → customresourcedefinition.apiextensions.k8s.io/... configured
```

#### 2. Восстановление учетных данных (Secret Management)
Секреты репозиториев восстанавливаются из внешнего корпоративного хранилища HashiCorp Vault (через External Secrets Operator или прямой скрипт инициализации):
```bash
# Инъекция мастер-ключа репозитория Git
kubectl create secret generic gitlab-repo-creds -n argocd \
  --from-literal=type=git \
  --from-literal=url=git@gitlab.company.local:infra/k8s-apps.git \
  --from-file=sshPrivateKey=/etc/ssl/certs/argo_deploy_key
kubectl label secret gitlab-repo-creds -n argocd "argocd.argoproj.io/secret-type=repository"
# → secret/gitlab-repo-creds created
# → secret/gitlab-repo-creds labeled
```

#### 3. Накат корневого приложения App-of-Apps
```bash
kubectl apply -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: root-bootstrap
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: 'git@gitlab.company.local:infra/k8s-apps.git'
    targetRevision: HEAD
    path: bootstrap/root
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: argocd
  syncPolicy:
    automated:
      prune: false # ВАЖНО: на первой фазе DR prune отключен!
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
EOF
# → application.argoproj.io/root-bootstrap created
```

#### 4. Подхват существующих ресурсов (Resource Adoption)
Благодаря механизму Server-Side Apply (SSA) и tracking method `annotation` контроллер Argo CD обнаружит уже работающие в кластере объекты (Deployments, Services, Ingress), верифицирует соответствие манифестам из Git и возьмет их под управление **без перезапуска работающих подов**.

## Операции и команды

Сводная таблица команд администратора при выполнении регламентов DR:

| Операция | Команда | Назначение | Ожидаемый вывод |
| :--- | :--- | :--- | :--- |
| **Экспорт всех сущностей** | `argocd admin export -n argocd -o backup.yaml` | Полная выгрузка данных в файл | `# → Successfully exported data` |
| **Экспорт с учетом неймспейсов** | `argocd admin export -n argocd --application-namespaces "*"` | Выгрузка с дочерними неймспейсами | `# → Exported apps from matched namespaces` |
| **Валидация бэкапа (Dry-Run)** | `argocd admin import -n argocd --dry-run backup.yaml` | Проверка целостности манифестов | `# → [DRY-RUN] Verification completed: 0 errors` |
| **Импорт данных с перезаписью** | `argocd admin import -n argocd --override-on-conflict backup.yaml` | Накат бэкапа с разрешением коллизий | `# → Successfully imported resources` |
| **Снапшот etcd** | `ETCDCTL_API=3 etcdctl snapshot save snap.db [tls-flags]` | Создание бинарного снимка BoltDB | `# → Snapshot saved at snap.db` |
| **Проверка статуса снапшота** | `ETCDCTL_API=3 etcdutl snapshot status snap.db -w table` | Проверка хэша и ревизии BoltDB | `# → Table with HASH, REVISION, TOTAL KEYS` |
| **Проверка здоровья кластеров** | `argocd cluster list` | Проверка связи с целевыми K8s API | `# → STATUS: Successful` |
| **Массовая проверка приложений** | `argocd app list -o wide` | Проверка статуса синхронизации и здоровья | `# → Synced / Healthy` |
| **Экстренное снятие финализатора** | `kubectl patch app <name> -n argocd -p '{"metadata":{"finalizers":null}}' --type=merge` | Предотвращение каскадного сноса ресурсов | `# → application.argoproj.io/<name> patched` |

## Диагностика и устранение неполадок

### Базовые команды диагностики при аварии

```bash
# 1. Проверка доступности API-сервера и etcd
kubectl get nodes
kubectl get cs || kubectl get --raw='/readyz'
# → ok

# 2. Проверка состояния подов управляющего контура Argo CD
kubectl get pods -n argocd -o wide
# → NAME                                             READY   STATUS    RESTARTS   AGE
# → argocd-application-controller-0                  1/1     Running   0          5m
# → argocd-repo-server-5d8f6b7c4d-x9z2q              1/1     Running   0          5m
# → argocd-server-7964bbf6bb-f8m4s                   1/1     Running   0          5m

# 3. Анализ логов контроллера на предмет ошибок reconciler
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller --tail=100 | grep -E "level=error|ComparisonError"

# 4. Проверка состояния Redis
kubectl exec -n argocd deployment/argocd-redis -- redis-cli ping || \
kubectl exec -n argocd statefulset/argocd-redis-ha-server-0 -c redis -- redis-cli ping
# → PONG
```

### Типичные ошибки DR и алгоритмы устранения

| Симптом / Ошибка | Причина возникновения | Алгоритм решения |
| :--- | :--- | :--- |
| **Приложения зависают в `Terminating` при удалении/миграции** | Установлен `resources-finalizer.argocd.argoproj.io`, но целевой кластер недоступен или контроллер остановлен. | Снять финализатор вручную через patch:<br>`kubectl patch app <name> -n argocd -p '{"metadata":{"finalizers":null}}' --type=merge`. См. [Удаление и очистка ресурсов](./argocd_deletion_and_cleanup.md). |
| **`ComparisonError: repository not found / authentication failed`** | Секреты с учетными данными Git (`argocd.argoproj.io/secret-type: repository`) не восстановились из бэкапа. | Проверить наличие секрета: `kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=repository`. При необходимости пересоздать Secret со связкой SSH/Token. |
| **`cluster "https://..." not found`** | Секреты подключения к целевым кластерам (`secret-type: cluster`) отсутствуют или повреждены сертификаты. | Восстановить cluster secrets из бэкапа или выполнить команду повторного добавления: `argocd cluster add <kube-context> --name <cluster-name>`. |
| **OOMKilled у `argocd-application-controller`** | При массовом старте 500+ приложений одновременно возникает лавина запросов к API и переполнение памяти (Thundering Herd). | 1. Увеличить `limits.memory` до 4–8 GiB.<br>2. Ограничить параллелизм: задать переменную `ARGOCD_CONTROLLER_STATUS_PROCESSORS=20` и `ARGOCD_CONTROLLER_OPERATION_PROCESSORS=10`. |
| **Случайное удаление ресурсов из-за флага `--prune`** | При вызове `argocd admin import --prune` файл бэкапа был неполным (не содержал всех неймспейсов). | Немедленно восстановить отсутствующие манифесты из GitOps-репозитория; остановить контроллер на время расследования. |
| **Split-Brain: ресурсы непрерывно пересоздаются и мигают** | Два активных контроллера (в DC-1 и DC-2) конкурируют за кластер с разными версиями манифестов. | Принудительно заглушить контроллер в резервном ЦОД (`replicas=0`) до полной стабилизации основного контура. |
| **Stale Cache в Redis после отката etcd** | etcd откатился на старую ревизию, а Redis хранит закэшированные данные более новых манифестов. | Сбросить кэш Redis: `kubectl exec -n argocd deployment/argocd-redis -- redis-cli FLUSHALL` и перезапустить поды контроллера. |

## Рекомендации и лучшие практики

### 1. Принцип "Git is SSoT, Backups are Fast-Forward"
Основным источником истины для 100% манифестов является Git. Резервные копии `argocd admin export` и снапшоты etcd служат исключительно средством ускорения RTO (быстрого восстановления состояния учетных записей, истории синхронизации и локальных метаданных). Проектируйте инфраструктуру так, чтобы кластер мог быть пересоздан с нуля без наличия бэкапов.

### 2. Защита от каскадного удаления в процессе аварии
На критических фазах восстановления (особенно при подключении новых кластеров или смене control plane):
- Отключайте авто-синхронизацию: `automated: null`.
- Запрещайте удаление ресурсов при расхождении: `prune: false`.
- Включайте `prune` только после того, как все приложения перешли в статус `Healthy` и подтверждено совпадение версий.

### 3. Регламент регулярных учений (Disaster Recovery GameDay)
Раз в квартал проводите контролируемые учения по восстановлению:
1. Развертывание тестового bare-metal или staging-кластера.
2. Скачивание зашифрованного бэкапа из локального MinIO.
3. Восстановление состояния через `argocd admin import`.
4. Верификация корректности статусов 100% приложений.

### 4. Безопасность и хранение секретов в On-Premise контурах
- Бэкапы, формируемые `argocd admin export`, содержат открытые секреты (токены доступа к K8s и приватные ключи SSH).
- Обязательно шифруйте артефакты бэкапов перед выгрузкой в MinIO с использованием GPG или `age`.
- Настраивайте MinIO Object Lock (WORM / Compliance Mode) с версионированием, чтобы защитить бэкапы от программ-вымогателей (ransomware) и случайного удаления.

### 5. Тюнинг производительности контроллера при восстановлении
При одновременном подъеме сотен приложений избегайте перегрузки Git-сервера и K8s API:
- Настройте задержки ретраев и таймауты в `argocd-cmd-params-cm`:
  ```yaml
  data:
    controller.repo.server.timeout.seconds: "90"
    controller.status.processors: "30"
    controller.operation.processors: "15"
  ```
- Используйте HA-режим контроллера с шардированием по кластерам (см. [Установка и настройка](./argocd_installation_and_setup.md#сценарий-7-шардирование-контроллера)).

## Дополнительная информация

### См. также (внутренняя база знаний)

- [Argo CD: Обзор архитектуры и возможностей](./argocd_overview.md) — базовые концепции GitOps, жизненный цикл приложения.
- [Argo CD: Установка и настройка](./argocd_installation_and_setup.md) — развертывание HA-режима, шардирование контроллера.
- [Argo CD: Удаление и очистка ресурсов](./argocd_deletion_and_cleanup.md) — механизмы финализаторов, безопасный демонтаж и предупреждение каскадного сноса.
- [Argo CD: Диагностика и мониторинг](./argocd_troubleshooting_and_monitoring.md) — метрики Prometheus, алерты и анализ логов контроллера.
- [Argo CD: Безопасность и харденинг](./argocd_security_hardening.md) — сетевые политики, mTLS и защита секретов.
- [Argo CD: Ролевой доступ (RBAC)](./argocd_rbac_deep.md) — разграничение прав операторов и интеграций.
- [Резервное копирование и DR в Kubernetes](../../Kubernetes/Operations/backup-strategies.md) — пятиуровневая модель бэкапа, CSI снапшоты, Velero.
- [Практические операции с etcd](../../Kubernetes/Concepts/etcd_operations.md) — обслуживание, компакция, снапшоты etcd.
- [Паттерны Disaster Recovery](../../Concepts/disaster_recovery.md) — общая методология Cold/Warm/Hot Standby, расчет RPO/RTO.

### Ссылки на официальную документацию

- [Argo CD Disaster Recovery Guide](https://argo-cd.readthedocs.io/en/stable/operator-manual/disaster_recovery/)
- [Argo CD Backup and Restore (CLI Reference)](https://argo-cd.readthedocs.io/en/stable/user-guide/commands/argocd_admin_export/)
- [Argo CD High Availability Architecture](https://argo-cd.readthedocs.io/en/stable/operator-manual/high_availability/)
- [Velero On-Premises Object Store (MinIO) Documentation](https://velero.io/docs/v1.14/contributions/minio/)
- [etcd Disaster Recovery & Snapshotting](https://etcd.io/docs/v3.5/op-guide/recovery/)
