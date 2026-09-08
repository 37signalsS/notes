# Longhorn — распределённое блочное хранилище для Kubernetes

Документ охватывает архитектуру, установку, эксплуатацию и устранение неполадок Longhorn. Актуален для версий **1.8.x – 1.12.x**.

---

## Определения

### Основные понятия

**Longhorn** — cloud-native распределённое блочное хранилище с открытым исходным кодом для Kubernetes. Превращает локальные диски узлов в отказоустойчивый пул хранения, обеспечивая синхронную репликацию данных, создание снимков (snapshots) и инкрементальное резервное копирование.

**CSI (Container Storage Interface)** — стандартный интерфейс, через который Kubernetes взаимодействует с системами хранения. Longhorn реализует CSI-драйвер, состоящий из three компонентов: **controller** (coordinator), **node** (attacher + mounter) и **provisioner**. Каждый компонент работает как отдельный под, управляемый StatefulSet или DaemonSet.

**StorageClass** — объект Kubernetes, описывающий параметры динамического provisioning томов (провайдер, replication factor, filesystem, I/O parameters). Longhorn регистрирует provisioner `driver.longhorn.io` и создаёт StorageClass `longhorn` по умолчанию при установке.

**Replication Factor (Фактор репликации)** — количество копий данных тома, размещаемых на разных узлах. Определяется параметром `numberOfReplicas` в StorageClass. Значение **3** — рекомендация для production (выдерживает потерю 2 из 3 узлов). Значение **1** — только для dev/test (нет отказоустойчивости).

**Snapshot (Снимок)** — мгновенный снимок состояния тома в определённый момент времени. Longhorn создаёт инкрементальные снимки через механизм COW (Copy-on-Write). Снимки используются для восстановления данных, создания клонов и отправки в backup.

### Движки данных

**Data Engine (Движок данных)** — программный слой, отвечающий за операции ввода-вывода.

- **V1 (Engine)** — классический движок на базе разреженных файлов (sparse files) в `/var/lib/longhorn`. Данные записываются через FUSE (Filesystem in Userspace) с использованием iSCSI между Engine и Replicas. Стабилен, является выбором по умолчанию.
- **V2 (SPDK)** — высокопроизводительный движок на базе Storage Performance Development Kit (SPDK), работающий напрямую с NVMe-дисками через пользовательское пространство (userspace). Исключает накладные расходы FUSE и iSCSI. Находится в статусе Preview (в версии 1.8+), требует предварительной настройки узлов (HugePages, выделенные CPU).

### Зависимости хостов

**open-iscsi** — пакет, предоставляющий iSCSI Initiator для подключения к блочным устройствам. Longhorn V1 использует iSCSI для передачи данных между Engine и Replicas. На каждом рабочем узле **обязателен** запущенный сервис `iscsid`.

**nfs-common** — пакет NFS-клиента. Требуется для работы Share Manager (встроенный NFS-сервер), который обеспечивает доступ типа ReadWriteMany (RWX) к томам. На каждом рабочем узле **обязателен**.

### Тома и доступ

**defaultReplicaCount** — количество реплик тома по умолчанию. Для production-сред рекомендуется значение **3**.

**ReplicaSoftAntiAffinity** — параметр, позволяющий размещать несколько реплик одного тома на одном узле (при значении `true`). Полезно для кластеров с малым количеством узлов (1-2), но значительно снижает отказоустойчивость.

**DR Volume (Disaster Recovery Volume)** — специальный тип тома, который создаётся из бэкапа в другом кластере и находится в режиме ожидания (Standby). Позволяет быстро переключить нагрузку при отказе основного кластера.

**Overprovisioning (Избыточное provisionирование)** — параметр `storageOverProvisioningPercentage`, определяющий, сколько "виртуального" места можно выделить сверх физически доступного. По умолчанию 200%: при 100 ГБ физического места Longhorn позволит выделить до 200 ГБ томов (с учётом репликации).

**Air-gapped (закрытый контур)** — изолированная среда без доступа к интернету. Полная процедура установки в такой среде описана в [Longhorn — установка в закрытом контуре](./longhorn-air-gapped.md).

---

## Основные концепции

### Архитектура Longhorn

Longhorn работает как набор микросервисов внутри Kubernetes. Управление осуществляется через Custom Resources (CRD).

```
┌─────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                    │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ Node 1   │  │ Node 2   │  │ Node 3   │              │
│  │ /var/    │  │ /var/    │  │ /var/    │              │
│  │ longhorn │  │ longhorn │  │ longhorn │              │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
│       │              │              │                   │
│       └──────────────┼──────────────┘                   │
│                      │                                  │
│              ┌───────▼────────┐                         │
│              │ Longhorn       │                         │
│              │ Manager        │                         │
│              └───────┬────────┘                         │
│                      │                                  │
│              ┌───────▼────────┐                         │
│              │ CSI Driver     │                         │
│              │ (attacher,     │                         │
│              │  provisioner,  │                         │
│              │  node-driver)  │                         │
│              └────────────────┘                         │
└─────────────────────────────────────────────────────────┘
```

### Ключевые компоненты

| Компонент | Назначение | Тип |
|---|---|---|
| **Longhorn Manager** | Управляет жизненным циклом томов, реплик и узлов. Обрабатывает API-запросы CSI. | DaemonSet |
| **Longhorn Engine** | Процесс, отвечающий за репликацию данных для конкретного тома. Один Engine на том. | Pod (per volume) |
| **CSI Driver** | Обеспечивает интеграцию с Kubernetes (Create, Attach, Mount, Detach, Delete). | StatefulSet + DaemonSet |
| **Instance Manager** | Управляет процессами Engine и Replica на каждом узле. | DaemonSet |
| **Share Manager** | Обеспечивает поддержку RWX-томов через встроенный NFS-сервер. | Pod (per RWX volume) |
| **Backing Image Manager** | Управляет образами, которые могут использоваться как основа для томов. | DaemonSet |

### Поток данных (Data Flow)

Понимание потока данных критично для диагностики проблем производительности и понимания отказоустойчивости.

**Запись (Write):**

```
Pod (Application)
    │
    ▼
PersistentVolumeClaim (PVC)
    │
    ▼
CSI Node Driver (на узле пода)
    │
    ▼
Longhorn Engine (на узле пода)  ◄─── Координирует запись
    │
    ├──► Replica 1 (узел 1)  ◄─── Синхронная запись
    ├──► Replica 2 (узел 2)  ◄─── Синхронная запись
    └──► Replica 3 (узел 3)  ◄─── Синхронная запись (если 3 реплики)
    │
    ▼
ACK (подтверждение) → Pod
```

**Ключевой момент:** Longhorn выполняет **синхронную** репликацию. Запись считается завершённой только после подтверждения **всех** активных реплик. Это гарантирует, что данные не потеряны при отказе одного узла, но увеличивает latency записи (задержка = максимальный latency среди реплик + network round-trip).

**Чтение (Read):**

```
Pod (Application)
    │
    ▼
CSI Node Driver
    │
    ▼
Longhorn Engine (на узле пода)
    │
    └──► Replica на том же узле (предпочтительно) или любой доступной Replica
    │
    ▼
Данные → Pod
```

**Ключевой момент:** Чтение выполняется с **ближайшей** реплики (на том же узле, если доступна). Это минимизирует network overhead для read-операций.

### Жизненный цикл тома (Volume Lifecycle)

| Этап | Описание | Ключевые команды |
|------|----------|------------------|
| **Create** | Kubernetes вызывает CSI CreateVolume. Longhorn Manager создает CRD Volume, запускает Engine и Replicas. | `kubectl get pvc` |
| **Attach** | Под调度ывается на узел. CSI Controller вызывает ControllerPublish (iSCSI-подключение). | `kubectl describe pvc` → Status: Bound |
| **Mount** | CSI Node Driver монтирует iSCSI-LUN в `/var/lib/longhorn/` и подключает его к поду через bind-mount. | `kubectl exec <pod> -- df -h /data` |
| **Use** | Приложение работает с данными через файловую систему (ext4/xfs) поверх iSCSI-LUN. | — |
| **Detach** | При остановке пода CSI вызывает ControllerUnpublish (iSCSI-отключение). | `kubectl delete pod` |
| **Delete** | CSI вызывает DeleteVolume. Longhorn удаляет Engine, Replicas и данные. | `kubectl delete pvc` |

### Обработка отказа узла (Node Failure Handling)

При отказе узла Longhorn работает следующим образом:

1. **Обнаружение:** Longhorn Manager обнаруживает, что узел недоступен (heartbeat timeout ~30 секунд).
2. **Определение потерь:** Если на отказавшем узле была **primary replica** (и файловая система смонтирована), Longhorn:
   - Выбирает новую primary replica на здоровом узле (если доступна)
   - Начинает **rebuilding** недостающих реплик на других узлах
3. **Восстановление:** Кластер возвращается в состояние healthy после завершения rebalancing.

**Критические условия:**
- Если **все** узлы с репликами тома отказали — данные **потеряны**
- Если хотя бы одна реплика доступна — том восстанавливается
- Если primary replica недоступна, но secondary доступна — автоматический failover (при определённых условиях)

### Требования к инфраструктуре

#### Аппаратные требования

| Ресурс | Минимум | Рекомендация | Примечание |
|--------|---------|--------------|------------|
| **CPU** | 2 ядра | 4+ ядер | Для Engine V2 (SPDK) рекомендуется выделение CPU cores |
| **RAM** | 2 ГБ | 4+ ГБ | Longhorn Manager + Instance Manager: ~512 МБ на узел |
| **Диски** | 1 HDD/SSD | SSD/NVMe | Минимум 50 ГБ свободного места для данных |
| **Сеть** | 1 Гбит/с | 10+ Гбит/с | Критично для репликации между узлами |

#### Сетевые требования

| Порт | Назначение | Протокол |
|------|-----------|----------|
| 9500 | Longhorn Manager (API) | TCP |
| 9501 | Longhorn Manager ( replication traffic) | TCP |
| 9502 | Longhorn Engine ( replication) | TCP |
| 3260 | iSCSI (V1 Engine) | TCP |
| 2049 | NFS (RWX volumes) | TCP |

> **Важно:** между узлами кластера должны быть открыты порты 9500-9502 для репликации. Закрытие этих портов приведёт к невозможности создания реплик на удалённых узлах.

#### Ресурсные квоты (рекомендуемые)

```yaml
# Рекомендуемые ресурсы для Longhorn компонентов
resources:
  longhorn-manager:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi
  longhorn-driver:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 256Mi
```

### StorageClass: параметры и конфигурация

Longhorn создаёт StorageClass `longhorn` по умолчанию. Кастомные StorageClass'ы позволяют создавать тома с разными параметрами для разных сценариев.

```yaml
# StorageClass для Production (3 реплики, no overprovisioning)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: longhorn-production
provisioner: driver.longhorn.io
parameters:
  numberOfReplicas: "3"
  staleReplicaTimeout: "2880"
  fromBackup: ""
  fsType: "ext4"
  # Отключаем overprovisioning для production
  # ( Longhorn не позволит выделить больше, чем физически доступно)
reclaimPolicy: Delete
allowVolumeExpansion: true
volumeBindingMode: Immediate
```

```yaml
# StorageClass для Dev/Test (1 реплика, soft anti-affinity)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: longhorn-dev
provisioner: driver.longhorn.io
parameters:
  numberOfReplicas: "1"
  staleReplicaTimeout: "2880"
  fsType: "ext4"
reclaimPolicy: Delete
allowVolumeExpansion: true
```

---

## Практические сценарии

### 1. Подготовка и проверка окружения

#### 1.1 Установка зависимостей (Ubuntu/Debian)

```bash
sudo apt update && sudo apt install -y open-iscsi nfs-common
sudo systemctl enable --now iscsid
```

#### 1.2 Установка зависимостей (RHEL/CentOS)

```bash
sudo dnf install -y iscsi-initiator-utils nfs-utils
sudo systemctl enable --now iscsid
```

#### 1.3 Проверка соответствия требованиям

Используйте официальный скрипт для автоматической проверки (замените версию на актуальную):

```bash
curl -sSfL https://raw.githubusercontent.com/longhorn/longhorn/v1.12.0/scripts/environment_check.sh | bash
```

Пример вывода при успешной проверке:

```
[INFO]  Required packages 'open-iscsi' and 'nfs-common' are installed.
[INFO]  Service 'iscsid' is enabled and running.
[INFO]  MultipathDevices check passed.
[INFO]  Default CPU manager policy is 'none'.
[INFO]  All checks passed.
```

#### 1.4 Проверка NTP на всех узлах

Longhorn требует синхронизированного времени для корректной работы таймстампов снимков и бэкапов:

```bash
# На каждом узле
chronyc tracking
# → Leap status: Normal (synchronized)

# Если не синхронизировано:
sudo chronyc makestep
```

### 2. Онлайн установка через Helm

**Требования:** Kubernetes >= 1.25, Helm 3.x.

**Шаг 1. Настройка параметров (`longhorn-values.yaml`):**

```yaml
defaultSettings:
  defaultReplicaCount: 3
  replicaSoftAntiAffinity: false
  storageOverProvisioningPercentage: 200
  storageMinimalAvailablePercentage: 15
  # Настройка бэкапов (S3)
  backupTarget: "s3://my-backup-bucket@us-east-1/"
  backupTargetCredentialSecret: "s3-secret"
  # Автоматическое перераспределение реплик (1.7+)
  replicaAutoBalance: "best-effort"
longhornUI:
  replicas: 1
```

**Шаг 2. Установка:**

```bash
helm repo add longhorn https://charts.longhorn.io
helm repo update
helm install longhorn longhorn/longhorn \
  -n longhorn-system \
  --create-namespace \
  -f longhorn-values.yaml
```

**Шаг 3. Проверка установки:**

```bash
kubectl get pods -n longhorn-system
# → longhorn-manager-xxxxx        1/1     Running   0          2m
# → longhorn-driver-deployer-xxx  1/1     Running   0          2m
# → longhorn-ui-xxxxx             1/1     Running   0          2m

kubectl get storageclass
# → longhorn (default)   driver.longhorn.io   Delete   WaitForFirstConsumer   false
```

### 3. Настройка мониторинга

Longhorn экспортирует метрики в формате Prometheus через сервис `longhorn-backend`.

**ServiceMonitor:** Если используется `kube-prometheus-stack`, включите создание ServiceMonitor в `values.yaml`:

```yaml
metrics:
  serviceMonitor:
    enabled: true
```

**Дашборды:** Официальные дашборды доступны в Grafana Labs (ID: 13070, 16888 для V2).

**Ключевые метрики для алертинга:**

| Метрика | Описание | Алерт |
|---------|----------|-------|
| `longhorn_volume_state` | Статус тома (1 = healthy) | < 1 → том деградирован |
| `longhorn_node_disk_capacity_bytes` | Свободное место на дисках | < 15% → приближение к порогу |
| `longhorn_instance_manager_cpu_usage` | Потребление ресурсов Engine | > 80% ядра → бутылочное горлышко |
| `longhorn_volume_snapshot_persistent_volume_snapshot_count` | Количество снимков на томе | > 25 → необходима очистка |

**Пример Prometheus alerting rule:**

```yaml
groups:
  - name: longhorn
    rules:
      - alert: LonghornVolumeDegraded
        expr: longhorn_volume_state != 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Longhorn volume {{ $labels.volume }} is degraded"
      - alert: LonghornDiskSpaceLow
        expr: (longhorn_node_disk_capacity_bytes - longhorn_node_disk_available_bytes) / longhorn_node_disk_capacity_bytes > 0.85
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Longhorn disk {{ $labels.node }} is >85% full"
```

### 4. Безопасность и шифрование

#### 4.1 Шифрование томов (dm-crypt)

Longhorn поддерживает шифрование томов "на лету" с использованием `dm-crypt`.

**Настройка через StorageClass:**

```yaml
kind: StorageClass
apiVersion: storage.k8s.io/v1
metadata:
  name: longhorn-crypto
provisioner: driver.longhorn.io
parameters:
  numberOfReplicas: "3"
  staleReplicaTimeout: "2880"
  encrypted: "true"
  # Имя секрета с ключом шифрования
  csi.storage.k8s.io/node-publish-secret-name: "longhorn-crypto-key"
  csi.storage.k8s.io/node-publish-secret-namespace: "longhorn-system"
```

**Создание секрета:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: longhorn-crypto-key
  namespace: longhorn-system
type: Opaque
stringData:
  CRYPTO_KEY_VALUE: "my-secret-encryption-key"
```

> Секрет должен содержать поле `CRYPTO_KEY_VALUE`. Также поддерживается интеграция с внешними KMS.

#### 4.2 Network Policies

Для ограничения сетевого доступа к Longhorn компонентам:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: longhorn-network-policy
  namespace: longhorn-system
spec:
  podSelector:
    matchLabels:
      app: longhorn-manager
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: longhorn-system
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: longhorn-system
```

#### 4.3 RBAC

Longhorn создаёт ServiceAccount, ClusterRole и ClusterRoleBinding автоматически при установке. Основные роли:

| Роль | Права |
|------|-------|
| `longhorn-manager` | Управление CRD (volumes, replicas, engines), доступ к узлам |
| `longhorn-driver` | Создание/удаление томов через CSI |
| `longhorn-ui` | Доступ к API для UI |

### 5. Настройка хранилища бэкапов (S3)

Для обеспечения сохранности данных Longhorn должен сохранять бэкапы во внешнее хранилище.

**Шаг 1. Создание секрета с учетными данными:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: s3-secret
  namespace: longhorn-system
type: Opaque
stringData:
  AWS_ACCESS_KEY_ID: "your_key"
  AWS_SECRET_ACCESS_KEY: "your_secret"
  AWS_ENDPOINTS: "https://s3.your-provider.com"  # Для S3-совместимых хранилищ
```

**Шаг 2. Обновление настроек:**

В UI: `Settings` → `General` → `Backup Target`. Укажите путь (например, `s3://bucket@region/`) и имя секрета. В версии 1.8+ поддерживается работа с несколькими Backup Targets одновременно.

**Шаг 3. Проверка подключения:**

```bash
kubectl get backupbackuptarget -n longhorn-system
# → NAME       URL                           AVAILABLE   AGE
# → default    s3://my-backup-bucket@us-east   true        5m
```

### 6. Планирование бэкапов и ретеншн-политика

**Автоматическое планирование через UI:**

1. Перейдите в UI → `Setting` → `Backup`
2. Настройте `Recurring Backup Job` для нужного тома:
   - **Schedule:** cron-выражение (например, `0 2 * * *` — каждый день в 2:00)
   - **Retain:** количество хранимых бэкапов (например, 7 для еженедельного ротации)

**Пример через CRD (для GitOps):**

```yaml
apiVersion: longhorn.io/v1beta2
kind: RecurringJob
metadata:
  name: daily-backup
  namespace: longhorn-system
spec:
  schedule: "0 2 * * *"
  concurrency: 1
 Groups:
    - group1
  retain: 7
  disabled: false
```

**Рекомендации по ретеншн-политике:**

| Тип среды | Частота | Хранение | Пример |
|-----------|---------|----------|--------|
| Dev/Test | Ежедневно | 3 бэкапа | 3 последних бэкапа |
| Production (критичные данные) | Каждые 6 часов | 7 бэкапов | 7 дней × 4 бэкапа/день |
| Production (стандартные) | Ежедневно | 14 бэкапов | 2 недели ежедневных бэкапов |

### 7. Управление томами

#### 7.1 Создание тома через kubectl

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-pvc
  namespace: default
spec:
  accessModes:
    - ReadWriteOnce  # или ReadWriteMany для RWX
  storageClassName: longhorn
  resources:
    requests:
      storage: 10Gi
```

#### 7.2 Расширение тома (Online Expansion)

Longhorn поддерживает расширение томов "на лету", если файловая система это поддерживает (ext4, XFS).

```bash
# 1. Отредактируйте PVC
kubectl edit pvc <pvc_name>

# 2. Измените spec.resources.requests.storage на большее значение
# Например: 10Gi → 20Gi

# 3. Проверьте результат
kubectl get pvc <pvc_name>
# → STATUS: Bound, CAPACITY: 20Gi

# 4. Проверьте файловую систему в поде
kubectl exec <pod_name> -- df -h /data
# → /dev/longhorn/pvc-xxx  20G  1.2G  18G  7% /data
```

> **Важно:** расширение возможно только вверх. Уменьшение размера тома **не поддерживается**.

#### 7.3 Создание Disaster Recovery (DR) тома

```bash
# 1. Убедитесь, что Backup Target настроен
kubectl get backupbackuptarget -n longhorn-system
# → NAME      AVAILABLE   AGE
# → default   true        10m

# 2. Через UI: Backup → Выберите бэкап → Create DR Volume

# 3. Или через кubectl (создание DR тома из бэкапа)
kubectl apply -f - <<EOF
apiVersion: longhorn.io/v1beta2
kind: Volume
metadata:
  name: dr-my-database
  namespace: longhorn-system
spec:
  size: "21474836480"
  numberOfReplicas: 3
  Standby: true
  fromBackup: "backup-xxxxx"
EOF

# 4. Активация DR тома (перевод в обычный режим)
# Через UI: Volume → dr-my-database → Activate
```

#### 7.4 Доступ к панели управления (UI)

**Через Port-forward:**

```bash
kubectl port-forward service/longhorn-frontend 8080:80 -n longhorn-system
# Доступ по адресу http://localhost:8080
```

**Через Ingress (рекомендуется):**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: longhorn-ui
  namespace: longhorn-system
  annotations:
    nginx.ingress.kubernetes.io/auth-type: basic
    nginx.ingress.kubernetes.io/auth-secret: basic-auth
spec:
  ingressClassName: nginx
  rules:
  - host: longhorn.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: longhorn-frontend
            port:
              number: 80
```

### 8. Обслуживание кластера

#### 8.1 Регламентное обслуживание узлов (Node Drain)

При необходимости вывести узел из эксплуатации (обновление ядра, замена оборудования):

```bash
# 1. Отключение планирования Longhorn на узел
# Через UI: Node → <имя_узла> → Edit Node → Allow Scheduling → Disable

# 2. Дождитесь завершения rebalancing реплик
kubectl get events -n longhorn-system --field-selector reason=Rebalance
# → Все реплики должны переместиться на другие узлы

# 3. Проверьте, что все тома healthy
kubectl get volumes.longhorn.io -n longhorn-system
# → STATUS должен быть "Healthy" для всех томов

# 4. Drain узла
kubectl drain <node_name> --ignore-daemonsets --delete-emptydir-data

# 5. Выполните необходимые работы на узле

# 6. Верните узел в кластер
kubectl uncordon <node_name>

# 7. Включение планирования Longhorn
# Через UI: Node → <имя_узла> → Edit Node → Allow Scheduling → Enable

# 8. Дождитесь возврата реплик на узел
```

#### 8.2 Очистка свободного места (Volume Trim)

Longhorn поддерживает команду `fstrim`. Для автоматической очистки неиспользуемых блоков:

**Через Settings (1.7+):**

```yaml
defaultSettings:
  dataPath: "/var/lib/longhorn"
  # Включение периодического trim
  freeDiskSentencePercent: 5
```

**Через CronJob:**

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: longhorn-trim
  namespace: longhorn-system
spec:
  schedule: "0 3 * * 0"  # Еженедельно в воскресенье в 3:00
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: fstrim
            image: alpine:3.18
            command: ["/bin/sh", "-c"]
            args:
            - |
              apk add --no-cache util-linux
              for vol in /var/lib/longhorn/replicas/*/volume.meta; do
                mount_point=$(dirname $vol)
                fstrim -v $mount_point
              done
          restartPolicy: OnFailure
```

#### 8.3 Обновление Longhorn

```bash
# 1. Прочитайте Release Notes для целевой версии
# https://github.com/longhorn/longhorn/releases

# 2. Обновите Helm-репозиторий
helm repo update

# 3. Примените новую версию
helm upgrade longhorn longhorn/longhorn \
  -n longhorn-system \
  --version 1.12.0

# 4. После обновления Manager-а Longhorn предложит обновить Engine
# для каждого тома через UI (раздел Volume -> Upgrade Engine)
# Важно: Обновление Engine приводит к кратковременному прерыванию I/O (V1 Engine)
```

### 9. Производительность и тюнинг

#### 9.1 Оптимизация для V1 Engine

| Параметр | Рекомендация | Влияние |
|----------|-------------|---------|
| **Диски** | SSD/NVMe для данных и metadata | Снижение latency в 3-5× |
| **Сеть** | 10+ Гбит/с между узлами | Ускорение репликации |
| **replicaSoftAntiAffinity** | `false` в production | Увеличение отказоустойчивости |
| **fsType** | `ext4` (по умолчанию) или `xfs` | `xfs` лучше для больших томов |
| **staleReplicaTimeout** | 2880 (48ч) | Увеличение таймаута для медленных сетей |

#### 9.2 Оптимизация для V2 Engine (SPDK)

Для V2 Engine (Preview в 1.8+):

```bash
# 1. Выделение HugePages (на каждом узле)
# В /etc/sysctl.conf:
vm.nr_hugepages = 1024  # = 2Gi (1024 × 2MB)

# 2. Проверка
cat /proc/meminfo | grep HugePages
# → HugePages_Total:    1024
# → HugePages_Free:     1024

# 3. CPU Isolation (рекомендуется)
# В GRUB: isolcpus=2,3 (выделить ядра 2,3 для SPDK)
```

#### 9.3 Мониторинг производительности

```bash
# Проверка IOPS и latency на дисках Longhorn
kubectl exec -n longhorn-system <longhorn-manager-pod> -- \
  longhorn replica list

# Просмотр статистики Engine
kubectl exec -n longhorn-system <longhorn-manager-pod> -- \
  longhorn engine list

# Проверка disk health
kubectl get nodes.longhorn.io -n longhorn-system -o yaml
```

### 10. Удаление Longhorn (Uninstall)

**Важно:** Перед удалением убедитесь, что все тома и бэкапы удалены/сохранены во внешнем хранилище.

#### 10.1 Полное удаление через Helm

```bash
# 1. Удаление всех PVC и PV, использующих Longhorn
kubectl delete pvc --all -n default  # или в нужных namespace'ах

# 2. Ожидание завершения удаления томов
kubectl get volumes.longhorn.io -n longhorn-system
# → Дождитесь пустого списка

# 3. Удаление Helm-релиза
helm uninstall longhorn -n longhorn-system

# 4. Удаление namespace
kubectl delete namespace longhorn-system

# 5. Удаление CRD (если не удалились автоматически)
kubectl delete crd volumes.longhorn.io -n longhorn-system 2>/dev/null
kubectl delete crd replicas.longhorn.io -n longhorn-system 2>/dev/null
kubectl delete crd engines.longhorn.io -n longhorn-system 2>/dev/null

# 6. Очистка данных на узлах (ОПЦИОНАЛЬНО, удаляет ВСЕ данные Longhorn)
for node in $(kubectl get nodes -o name); do
  kubectl debug node/${node#node/} -it --image=busybox -- \
    rm -rf /var/lib/longhorn
done
```

#### 10.2 Полное удаление через кubectl (без Helm)

```bash
# Скачивание YAML-манифестов для удаления
kubectl apply -f https://raw.githubusercontent.com/longhorn/longhorn/v1.12.0/uninstall/uninstall.yaml
```

> **Внимание:** удаление Longhorn **не удаляет** данные на дисках (`/var/lib/longhorn`). Если вы хотите полностью очистить данные — выполните `rm -rf /var/lib/longhorn` на каждом узле после удаления.

### 11. Диагностика и Troubleshooting

#### 11.1 Debug-команды

```bash
# Статус всех компонентов Longhorn
kubectl get pods -n longhorn-system -o wide

# Статус томов
kubectl get volumes.longhorn.io -n longhorn-system

# Статус реплик
kubectl get replicas.longhorn.io -n longhorn-system

# Статус Engine
kubectl get engines.longhorn.io -n longhorn-system

# Статус узлов
kubectl get nodes.longhorn.io -n longhorn-system

# Логи Longhorn Manager
kubectl logs -n longhorn-system <longhorn-manager-pod> --tail=100

# Логи CSI Driver
kubectl logs -n longhorn-system <longhorn-driver-pod> --tail=100

# Проверка iSCSI соединения на узле
sudo iscsiadm -m session
# → tcp: [0] 10.0.0.10:3260,1 iqn.2019-10.io.longhorn:pvc-xxx (non-flash)

# Проверка дискового пространства
kubectl exec -n longhorn-system <longhorn-manager-pod> -- \
  df -h /var/lib/longhorn
```

#### 11.2 Типичные проблемы

| Проблема | Симптомы | Причины | Решение |
|----------|----------|---------|---------|
| **Pod в ImagePullBackOff** | Под не запускается | Нет доступа к Docker Hub или образы не в Harbor | Проверить сеть и `global.imageRegistry` |
| **Ошибка `iscsid not found`** | Под не монтирует том | Не установлен/запущен open-iscsi | `apt install open-iscsi && systemctl enable --now iscsid` |
| **Volume застрял в Attaching** | PVC не привязывается | Проблема с CSI-драйвером или iscsid | Проверить логи `longhorn-manager` и `systemctl status iscsid` |
| **Volume в Degraded** | `longhorn_volume_state != 1` | Один или более реплик недоступны | Проверить узлы с репликами, перезапустить Longhorn Manager |
| **Низкая производительность** | High latency, low IOPS | Медленные диски, сеть, перегрузка | Проверить `iostat`, сеть 10Gbps+, SSD |
| **RWX Volume не монтируется** | Под с RWX не стартует | Не установлен nfs-common | `apt install nfs-common` на всех узлах |
| **V2 Engine не запускается** | SPDK-движок не стартует | Не настроены HugePages | Проверить `/proc/meminfo` → `HugePages_Total` |
| **Rebuilding stuck** | Реплики не восстанавливаются | Нет свободного места на целевых узлах | Освободить место или добавить узлы |
| **Split-brain (редко)** | Два Engine конфликтуют | Сетевая партиция | Проверить сеть, `longhorn manager repair` |

#### 11.3 Лог-анализ

```bash
# Поиск ошибок в логах Manager
kubectl logs -n longhorn-system <manager-pod> | grep -i "error\|fail\|warn" | tail -50

# Поиск событий CSI
kubectl logs -n longhorn-system <driver-pod> | grep -i "csi" | tail -30

# Просмотр Events в namespace
kubectl get events -n longhorn-system --sort-by='.lastTimestamp' | tail -20
```

#### 11.4 Восстановление после отказа узла

```bash
# 1. Проверьте статус томов
kubectl get volumes.longhorn.io -n longhorn-system -o yaml | grep -A5 "status:"
# → ищите volumes в degraded состоянии

# 2. Проверьте, какие реплики недоступны
kubectl get replicas.longhorn.io -n longhorn-system -o yaml | grep -B2 -A5 "state: stopped"

# 3. Если primary replica недоступна — Longhorn автоматически выберет новую
#    Если автоматический failover не сработал:
kubectl exec -n longhorn-system <manager-pod> -- \
  longhorn volume takeover <volume-name>

# 4. Дождитесь завершения rebuilding
kubectl get volumes.longhorn.io -n longhorn-system -o yaml | grep "robustness"
# → robustness: "healthy" (после завершения)

# 5. Проверьте целостность данных
kubectl exec -n longhorn-system <pod-with-volume> -- \
  fsck.ext4 -n /dev/longhorn/pvc-xxx
```

---

## Дополнительная информация

### Важные параметры values.yaml

| Параметр | Описание | Значение по умолчанию |
|---|---|---|
| `defaultSettings.defaultReplicaCount` | Количество реплик для новых томов | 3 |
| `defaultSettings.replicaSoftAntiAffinity` | Разрешить реплики на одном узле | `false` |
| `defaultSettings.storageOverProvisioningPercentage` | Множитель "виртуального" места | 200 |
| `defaultSettings.storageMinimalAvailablePercentage` | Порог остановки выделения места (%) | 25 |
| `defaultSettings.replicaAutoBalance` | Автобалансировка реплик | `disabled` |
| `defaultSettings.taintToleration` | Толерантность для специфичных узлов | (пусто) |
| `global.imageRegistry` | Общий префикс для всех образов | (пусто) |

### Ограничения и минусы

- **Производительность:** Движок V1 (sparse files в `/var/lib/longhorn`) уступает чистым блочным устройствам (LVM, Ceph RBD) при высокой нагрузке из-за накладных расходов на FUSE и iSCSI. Рекомендуется сеть 10Gbps и SSD.
- **RWX (ReadWriteMany):** Поддержка работает через встроенный NFS-сервер (Share Manager). При интенсивном доступе нескольких подов это может стать узким местом. Для высоконагруженных шаред-хранилищ лучше рассмотреть CephFS или NFS-провижинер.
- **V2 Engine (SPDK):** Требует предварительной настройки узлов (HugePages 2Gi, выделенные CPU). Находится в статусе Preview, не рекомендуется для production без тестирования.
- **Бэкапы:** Для disaster recovery требуется внешний S3-совместимый объектный стораж. Без него DR-тома не работают, а бэкапы остаются только на локальных дисках.
- **Зависимости хостов:** На всех рабочих узлах должны быть установлены `open-iscsi` и `nfs-common`. Это расширяет поверхность атаки и требует поддержки пакетов при обновлении ОС.
- **Режим `ReplicaSoftAntiAffinity: true`:** Позволяет размещать реплики на одном узле, что снижает отказоустойчивость. Используйте только для кластеров с 1-2 узлами в dev/test.
- **Размер тома:** Максимальный размер тома — 512 ГБ (V1 Engine). Для больших томов используйте несколько томов или рассмотрите Ceph RBD.
- **Снимки:** Longhorn хранит снимки инкрементально. При большом количестве снимков (>25) производительность может снижаться. Рекомендуется регулярная очистка.

### Edge Cases

- **Все узлы с репликами отказали:** Если все узлы, содержащие реплики конкретного тома, недоступны — данные **потеряны**. Восстановление возможно только из бэкапа.
- **Сетевая партиция (Split-Brain):** В редких случаях при сетевой партиции между узлами возможен конфликт Engine'ов. Longhorn использует机制 leader election для предотвращения этого, но в edge cases требуется ручное вмешательство (`longhorn volume takeover`).
- **Узел с single replica:** Если на узле с единственной репликой тома происходит сбой данных — том недоступен до восстановления узла.
- **Overprovisioning exhaustion:** При использовании `storageOverProvisioningPercentage: 200` и исчерпании физического места Longhorn **остановит** создание новых томов. Существующие томы продолжают работать, но новые не создаются.
- **Обновление Engine:** Обновление Engine приводит к кратковременному прерыванию I/O (1-5 секунд для V1). Для критичных приложений планируйте обновление в maintenance window.

### Связанные темы

- Концепции хранилищ: [Persistent Volumes и StorageClass](./pv_and_pvc.md)
- Сравнение CSI-драйверов: [Сравнение CSI-драйверов](./CSI/csi_drivers_comparison.md)
- Установка в закрытом контуре: [Longhorn — установка в закрытом контуре](./longhorn-air-gapped.md)
- Использование Harbor: [Использование Harbor](../../Docker/Docker_registries/Harbor/usage.md)
