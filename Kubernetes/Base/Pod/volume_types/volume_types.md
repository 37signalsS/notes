# Тома в Kubernetes

**Актуально для:** Kubernetes 1.30–1.32+

---

## Определения

**Volume (том)** — логическая абстракция хранилища данных, предоставляющая контейнерам Pod доступ к файловой системе или блочному устройству вне жизненного цикла отдельных контейнеров. В Kubernetes тома имеют жизненный цикл, привязанный к Pod: они инициализируются при запуске Pod и уничтожаются при его удалении (за исключением томов, опирающихся на независимые персистентные ресурсы PV/PVC).

**CSI (Container Storage Interface)** — отраслевой стандарт интеграции оркестраторов с внешними системами хранения. Начиная с Kubernetes 1.25–1.27, устаревшие встроенные (in-tree) драйверы для облачных хранилищ и специализированных СХД полностью удалены либо перенаправлены на CSI-миграцию. На узлах bare-metal и on-premise CSI-драйверы взаимодействуют с Kubelet через локальные UNIX-сокеты (`/var/lib/kubelet/plugins/...`).

**Ephemeral Storage (эфемерное хранилище)** — тома, предназначенные для временных данных (кэш, промежуточный буфер, разделяемая память, инъекция учетных данных). Данные удаляются при уничтожении Pod или его перепланировании на другой узел.

**Persistent Storage (персистентное хранилище)** — тома, данные в которых сохраняются независимо от жизненного цикла Pod. Реализуются через связку объектов `PersistentVolume` (PV), `PersistentVolumeClaim` (PVC) и `StorageClass`.

**Kubelet Volume Manager** — внутренний контроллер в составе Kubelet, запускающий цикл синхронизации (reconciliation loop) между желаемым состоянием монтирований (`DesiredStateOfWorld`) и фактическим состоянием файловой системы узла (`ActualStateOfWorld`). Отвечает за вызов плагинов монтирования, форматирование устройств и контроль прав.

**Raw Block Volume** — режим использования тома без файловой системы (`volumeMode: Block`). Блочное устройство передается непосредственно в контейнер через секцию `volumeDevices`, минуя слой VFS ядра на узле.

---

## Архитектура и базовые концепции

### Назначение томов

| Проблема | Архитектурное решение в Kubernetes |
| :--- | :--- |
| **Эфемерность контейнера** | Сохранение файлов при аварийном падении и перезапуске контейнера внутри того же Pod. |
| **Shared Storage внутри Pod** | Общий доступ к данным для нескольких контейнеров в одном Pod (например, паттерн Sidecar для обработки логов или прокси-кэширования). |
| **Инъекция конфигураций** | Безопасная передача `ConfigMap`, `Secret` и системных метаданных ([Downward API](../downward_api.md)) непосредственно в файловую систему контейнера. |
| **Разделение прав доступа** | Монтирование конфигурационных данных в режиме `readOnly` с гранулярным управлением `defaultMode` (POSIX-права 0400, 0440). |
| **Доставка неизменяемых артефактов** | Использование OCI-образов реестра в качестве томов через драйвер `image` (Beta в v1.31+). |
| **Высокопроизводительный I/O** | Предоставление низкоуровневых блочных устройств напрямую базам данных через `volumeDevices`. |

### Архитектура подсистемы хранения в Kubelet

Монтирование тома в контейнер представляет собой многоуровневый процесс, разделенный между управляющим контуром кластера и подсистемой узла:

```
+-----------------------------------------------------------------------------------------+
|                                Control Plane (kube-controller-manager)                  |
|  Attach/Detach Controller: сопоставляет Pod, Node и PV; отдает команды на подключение  |
+-----------------------------------------------------------------------------------------+
                                           |
                                           v  (Node API / RPC)
+-----------------------------------------------------------------------------------------+
|                                    Kubelet на Node                                      |
|                                                                                         |
|  1. Volume Manager: сверяет DesiredStateOfWorld и ActualStateOfWorld (каждые 100 мс)    |
|  2. NodeStageVolume: форматирование ФС и первичное монтирование блочного устройства      |
|     в системный каталог: /var/lib/kubelet/plugins/kubernetes.io/csi/...                 |
|  3. NodePublishVolume: создание Bind Mount в каталог конкретного Pod:                    |
|     /var/lib/kubelet/pods/<pod-uid>/volumes/<plugin-name>/<volume-name>                 |
|  4. Subpath Bind Mount: изоляция подпапок в:                                            |
|     /var/lib/kubelet/pods/<pod-uid>/volume-subpaths/<volume-name>/...                   |
|  5. Container Runtime (CRI / containerd): проброс Mount Namespace в контейнер          |
+-----------------------------------------------------------------------------------------+
```

### Физические пути на файловой системе узла (Linux)

Системному администратору и SRE критически важно понимать структуру каталогов Kubelet на узле:

- `/var/lib/kubelet/pods/<pod-uid>/volumes/kubernetes.io~empty-dir/<vol-name>` — данные томов `emptyDir` (на диске или смонтированный `tmpfs`).
- `/var/lib/kubelet/pods/<pod-uid>/volumes/kubernetes.io~secret/<vol-name>` — смонтированные секреты (в оперативной памяти `tmpfs`).
- `/var/lib/kubelet/pods/<pod-uid>/volumes/kubernetes.io~configmap/<vol-name>` — файлы конфигураций ConfigMap.
- `/var/lib/kubelet/pods/<pod-uid>/volume-subpaths/<vol-name>/<container-name>/<index>` — служебные bind-монтирования для параметров `subPath`.
- `/var/lib/kubelet/plugins/kubernetes.io/csi/pv/<pv-name>/mount` — глобальная точка монтирования устройства CSI на узле до привязки к конкретному Pod.

### Классификация типов томов

| Тип | Категория | Статус в K8s | Основное назначение |
| :--- | :--- | :--- | :--- |
| `emptyDir` | Эфемерное | Stable | Кэш, временные файлы компиляции, разделяемая память `/dev/shm`. |
| `hostPath` | Узел (Node) | Stable | Доступ к ресурсам хоста (сокеты CRI, логи `/var/log`, системные устройства). |
| `secret` | Эфемерное (RAM) | Stable | Инъекция паролей, TLS-сертификатов, ключей API в память `tmpfs`. |
| `configMap` | Эфемерное | Stable | Инъекция файлов конфигурации (`nginx.conf`, `settings.toml`). |
| `downwardAPI` | Эфемерное | Stable | Предоставление метаданных Pod (IP, лимиты CPU/RAM, метки) в виде файлов. |
| `projected` | Эфемерное | Stable | Объединение Secret, ConfigMap, Downward API и токенов сервисных аккаунтов в один путь. |
| `persistentVolumeClaim` | Персистентное | Stable | Подключение постоянного хранилища (Ceph, iSCSI, локальный диск, NFS) через PVC. |
| `ephemeral` | Эфемерное (PVC) | Stable | Generic Ephemeral Volumes — динамические тома с жизненным циклом Pod. |
| `csi` (inline) | Эфемерное | Stable | Прямой вызов CSI-драйвера без предварительного создания PV/PVC (HashiCorp Vault CSI). |
| `nfs` | Сетевое | Stable | Общий сетевой каталог (ReadWriteMany) для legacy-сервисов без CSI-драйвера. |
| `image` | Эфемерное (OCI) | Beta (v1.31+) | Монтирование содержимого OCI-образа контейнера в режиме ReadOnly. |

> **Примечание по типу `local`:** В спецификации Pod (`spec.volumes`) тип `local` отсутствует. Локальные физические диски узлов подключаются исключительно через объект `PersistentVolume` (`spec.local.path`) с обязательным `nodeAffinity` и запрашиваются приложениями через `persistentVolumeClaim`.

### Режимы монтирования: Filesystem (`volumeMounts`) vs Raw Block (`volumeDevices`)

По умолчанию все тома монтируются как форматированная файловая система через секцию `volumeMounts`. Однако Kubernetes поддерживает передачу блочного устройства напрямую:

```yaml
spec:
  containers:
  - name: storage-engine
    image: scylladb/scylla:6.0.0
    # Монтирование блочного устройства без ФС
    volumeDevices:
    - name: raw-block-vol
      devicePath: /dev/xvdf
  volumes:
  - name: raw-block-vol
    persistentVolumeClaim:
      claimName: raw-block-pvc
```

**Преимущества Raw Block для SRE:**
- Исключение накладных расходов VFS и журналов файловой системы (ext4/xfs).
- Прямой асинхронный ввод-вывод (`Direct I/O` / `io_uring`) для СУБД (PostgreSQL, ScyllaDB, Ceph OSD).
- Сокращение задержек (Latency) на операциях записи.

### Управление ресурсами и квотами эфемерного хранилища

Временные файлы на узле потребляют емкость корневой файловой системы Kubelet (`nodefs`) или выделенного диска контейнеров (`imagefs`). Неконтролируемая запись в `emptyDir` способна вызвать системную аварию узла (`Node DiskPressure`).

Для предотвращения этого используются механизмы квотирования:
1. **`sizeLimit` внутри `emptyDir`:** принудительный порог размера для конкретного тома.
2. **Лимиты `ephemeral-storage` в `resources`:**
   ```yaml
   resources:
     requests:
       ephemeral-storage: "2Gi"
     limits:
       ephemeral-storage: "8Gi"
   ```
   Суммарное потребление рассчитывается как: `размер слоя записи контейнера (rootfs) + все тома emptyDir на диске`. При превышении лимита Kubelet немедленно отправляет Pod в состояние `Evicted`.

---

## Основные типы томов и их конфигурация

### emptyDir

**Описание:** пустая директория, создаваемая в момент запуска Pod на узле.

**Параметры:**
- `medium: ""` — том создается на физическом диске узла в каталоге `/var/lib/kubelet/pods/<pod-uid>/volumes/kubernetes.io~empty-dir/<name>`.
- `medium: Memory` — том монтируется как Linux `tmpfs` в оперативной памяти узла. Быстрый I/O, но потребляет лимиты RAM контейнера (`resources.limits.memory`).
- `medium: HugePages-2Mi` / `HugePages-1Gi` — монтирование памяти со страницами HugePages для высокопроизводительных сетевых приложений (DPDK/VPP).
- `sizeLimit` — жесткий лимит объема (например, `512Mi`, `10Gi`).

**Жизненный цикл данных в emptyDir:**

| Событие | Состояние данных в `emptyDir` | Причина |
| :--- | :--- | :--- |
| **Авария процесса в контейнере (OOM / SEGV)** | **Сохраняются** | Pod остается на узле, перезапускается только Linux cgroup/контейнер. |
| **Удаление или обновление Pod (`RollingUpdate`)** | **Уничтожаются** | Pod удаляется из API, каталог тома физически стирается Kubelet. |
| **Drain узла (`kubectl drain`)** | **Уничтожаются** | Pod выселяется и пересоздается на другом узле с абсолютно чистым томом. |
| **Перезагрузка физического сервера (Reboot)** | **Уничтожаются** | После старта Kubelet переинициализирует окружение Pod. |

**Пример shared memory (`/dev/shm`) для многопоточных вычислений и Python/PyTorch:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: worker-shm
spec:
  containers:
  - name: worker
    image: python:3.12-slim
    command: ["sh", "-c", "df -h /dev/shm && sleep 3600"]
    resources:
      limits:
        memory: "2Gi"
    volumeMounts:
    - name: dshm
      mountPath: /dev/shm
  volumes:
  - name: dshm
    emptyDir:
      medium: Memory
      sizeLimit: 1Gi
```

### hostPath

**Описание:** монтирование файла, каталога или сокета с файловой системы узла хоста (Node) внутрь контейнера.

**Поддерживаемые типы (`type`):**

| Тип | Поведение Kubelet при отсутствии пути | Типичное применение в SRE/Sysadmin |
| :--- | :--- | :--- |
| `DirectoryOrCreate` | Создает каталог с правами `0755` (владелец root). | Буферы очередей DaemonSet, локальные кэши. |
| `Directory` | Ошибка монтирования (`FailedMount`), если путь не существует. | Чтение системных логов `/var/log` агентами fluentbit/promtail. |
| `FileOrCreate` | Создает пустой файл с правами `0644`. | Точки синхронизации, файлы блокировок. |
| `File` | Ошибка монтирования, если файла нет на диске хоста. | Монтирование `/etc/os-release`, `/etc/localtime`. |
| `Socket` | Ошибка монтирования, если путь не является UNIX-сокетом. | Доступ к сокетам CRI (`/run/containerd/containerd.sock`). |
| `CharDevice` | Ошибка, если путь не является символьным устройством. | Прямой доступ к `/dev/kmsg`, `/dev/fuse`. |
| `BlockDevice` | Ошибка, если путь не является блочным устройством. | Raw-доступ к дискам хоста (`/dev/sdb`, `/dev/nvme0n1`). |

**Политики безопасности и риски:**
- **Pod Security Standards (PSS):** использование `hostPath` категорически запрещено в профиле `restricted` и разрешено только в профилях `baseline` (с оговорками) и `privileged`. См. детальный разбор в [Pod Security Context](../../../Security/pod_security_context.md).
- **Побег из контейнера (Container Escape):** монтирование путей вроде `/`, `/proc`, `/sys` или Docker/CRI сокетов позволяет процессам контейнера получить полный контроль над хостом.
- **Привязка к конкретному узлу:** Pod с `hostPath` теряет мобильность. Если путь подготовлен только на сервере `node-01`, планирование на `node-02` завершится ошибкой.

### secret

**Описание:** проецирует данные объекта [Secret](../../secrets/secrets_basics.md) в виде файлов. По умолчанию Kubelet монтирует секреты в оперативную память через подсистему `tmpfs`, предотвращая сохранение чувствительных данных на незашифрованных дисках узла.

**Ключевые параметры:**
- `defaultMode`: восьмеричные POSIX-права доступа на создаваемые файлы (например, `0400` — только чтение для владельца процесса).
- `items`: список явного проецирования ключей Secret на конкретные относительные пути файлов.
- `optional: true`: предотвращает сбой старта Pod (`CreateContainerConfigError`), если Secret еще не создан в кластере.

**Механизм обновления через символические ссылки:**
Kubelet создает в каталоге тома трехуровневую иерархию символических ссылок:
```
/etc/secrets/
├── ..2026_10_13_16_40_12.123456789/  <- Реальная директория с версией
│   ├── password
│   └── username
├── ..data -> ..2026_10_13_16_40_12.123456789  <- Символическая ссылка
├── password -> ..data/password                 <- Файловая ссылка
└── username -> ..data/username                 <- Файловая ссылка
```
При обновлении Secret в API-сервере Kubelet скачивает новые данные во временный каталог `..data_tmp`, переключает ссылку `..data` атомарным вызовом `rename()` и удаляет старый каталог. Это гарантирует, что читающее приложение никогда не увидит частично записанные данные.

```yaml
volumes:
- name: cert-secret
  secret:
    secretName: app-tls-cert
    defaultMode: 0400
    optional: false
    items:
    - key: tls.crt
      path: certs/server.crt
    - key: tls.key
      path: certs/server.key
```

### configMap

**Описание:** проецирует содержимое объекта [ConfigMap](../../ConfigMap/best_practices.md) в файлы конфигурации. В отличие от Secret, ConfigMap по умолчанию сохраняется в файловой структуре узла на диске.

**Особенности применения:**
- Поддерживает аналогичный атомарный механизм symlink-ротации.
- **Проблема `subPath`:** если ключ ConfigMap монтируется через `subPath` в конкретный файл, Linux контейнер выполняет прямой bind mount inode файла. **Автоматическое обновление содержимого файла при изменении ConfigMap в этом случае не происходит.**
- `optional: true` позволяет запускать приложения при отсутствии внешней конфигурации (с использованием дефолтных значений в коде).

### downwardAPI

**Описание:** создает виртуальные файлы, содержащие информацию о самом Pod и окружении узла, избавляя приложение от необходимости иметь ServiceAccount с правами на обращение к Kubernetes API.

Подробнее: [Downward API — доступ к метаданным Pod](../downward_api.md).

**Поддерживаемые поля в томах:**
- Метаданные Pod: `metadata.name`, `metadata.namespace`, `metadata.uid`, `metadata.labels`, `metadata.annotations` (а также отдельные ключи `labels['key']`, `annotations['key']`).
- Лимиты и реквесты ресурсов (`resourceFieldRef`): `limits.cpu`, `requests.cpu`, `limits.memory`, `requests.memory`, `limits.ephemeral-storage`, `requests.ephemeral-storage`, `hugepages-*`.
- *Примечание:* сетевые и узловые поля (`status.podIP`, `status.podIPs`, `status.hostIP`, `status.hostIPs`, `spec.nodeName`, `spec.serviceAccountName`) доступны **только** через переменные окружения (`env.valueFrom.fieldRef`), но **не** поддерживаются в томах `downwardAPI`.

```yaml
volumes:
- name: pod-metadata
  downwardAPI:
    defaultMode: 0444
    items:
    - path: "labels"
      fieldRef:
        fieldPath: metadata.labels
    - path: "cpu_limit"
      resourceFieldRef:
        containerName: main-app
        resource: limits.cpu
        divisor: "1m"
```

### projected

**Описание:** позволяет объединить несколько независимых источников данных в единую файловую директорию внутри контейнера.

Подробнее: [Projected Volumes — агрегация источников](./projected_volumes.md).

**Источники данных для `projected`:**
1. `secret`
2. `configMap`
3. `downwardAPI`
4. `serviceAccountToken` (Bound Service Account Tokens с ограничением аудитории `audience` и времени жизни `expirationSeconds`).
5. `clusterTrustBundle` (инъекция централизованных CA-сертификатов кластера).

### persistentVolumeClaim

**Описание:** связывает Pod с постоянным томом (PV), выделенным статически администратором или динамически через CSI-драйвер и `StorageClass`.

```yaml
volumes:
- name: data-store
  persistentVolumeClaim:
    claimName: postgres-data-pvc
    readOnly: false
```
Подробнее: [PV, PVC и StorageClass — детальный разбор](../../../Storage/pv_and_pvc.md) и [Продвинутая работа с PV и PVC](../../../Storage/pv_pvc_advanced.md).

### ephemeral (Generic Ephemeral Volumes)

**Описание:** механизм динамического создания временных томов с использованием стандартных классов хранилищ (`StorageClass`). В манифесте Pod описывается шаблон `volumeClaimTemplate`.

**Архитектура и жизненный цикл:**
1. При создании Pod Kubelet/контроллер автоматически создает связанный объект `PersistentVolumeClaim`.
2. Владельцем PVC объявляется Pod (устанавливается `metadata.ownerReferences`).
3. CSI-драйвер динамически выделяет том (например, быстрый локальный SSD через [Local Path Provisioner](../../../Storage/local-path-provisioner.md) или сетевой блочный том Ceph RBD).
4. При удалении Pod механизм сборки мусора (Garbage Collector) Kubernetes автоматически удаляет и PVC, и базовый том.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: build-agent
spec:
  containers:
  - name: builder
    image: golang:1.24
    volumeMounts:
    - name: scratch-volume
      mountPath: /go/pkg
  volumes:
  - name: scratch-volume
    ephemeral:
      volumeClaimTemplate:
        metadata:
          labels:
            type: temporary-build-scratch
        spec:
          accessModes: [ "ReadWriteOnce" ]
          storageClassName: "fast-local-ssd"
          resources:
            requests:
              storage: 20Gi
```

### csi (Inline Ephemeral Volumes)

**Описание:** создание временного тома напрямую через CSI-драйвер без создания объектов PVC/PV.

**Область применения в SRE:**
- Интеграция с внешними менеджерами секретов: **Secrets Store CSI Driver** (инъекция паролей из HashiCorp Vault напрямую в память).
- Инъекция динамических TLS-сертификатов на базе `cert-manager-csi`.
- Драйвер должен явно поддерживать эфемерный режим (`volumeLifecycleModes: [Ephemeral]`).

```yaml
volumes:
- name: vault-secrets
  csi:
    driver: secrets-store.csi.k8s.io
    readOnly: true
    volumeAttributes:
      secretProviderClass: "vault-app-kv"
```

### nfs (Network File System)

**Описание:** прямое монтирование сетевого каталога NFS в контейнер средствами ядра хост-узла Linux (через встроенный in-tree драйвер).

**Особенности и ограничения:**
- Поддерживает режим общего доступа нескольких узлов `ReadWriteMany` (RWX).
- **Сетевая зависимость:** узел хоста должен иметь установленный пакет клиента (`nfs-common` в Debian/Ubuntu или `nfs-utils` в RHEL/Rocky), иначе Kubelet завершит монтирование с системной ошибкой `bad option; for several filesystems (e.g. nfs, cifs) you might need a /sbin/mount.<type> helper program`.
- **Single Point of Failure (SPOF):** сбой NFS-сервера приводит к зависанию процессов ввода-вывода в D-state (Uninterruptible Sleep), блокируя размонтирование томов при остановке Pod.
- **Рекомендация для Production:** избегать прямого использования типа `nfs` в Pod; использовать CSI-драйвер NFS (`csi-driver-nfs`) или PV/PVC с контролем опций монтирования (`mountOptions: [hard, noatime, nfsvers=4.2]`).

```yaml
volumes:
- name: shared-reports
  nfs:
    server: nfs.internal.infra
    path: /srv/nfs/shared_reports
    readOnly: false
```

### image (v1.31+ Beta)

**Описание:** монтирование OCI-образа из реестра артефактов в качестве тома файловой системы.

**Особенности:**
- Том всегда монтируется строго в режиме **ReadOnly**.
- Позволяет доставлять тяжелые статические ассеты, бинарные плагины или утилиты трассировки без загрязнения основного runtime-образа приложения.
- Требует поддержки контейнерным рантаймом узла (CRI-O 1.31+, containerd 2.0+).

```yaml
volumes:
- name: static-tools
  image:
    reference: harbor.internal.infra/tools/debug-tools:v1.2.0
    pullPolicy: IfNotPresent
```

---

## Безопасность и параметры монтирования

### Права доступа к файлам (fsGroup и fsGroupChangePolicy)

Когда процесс контейнера запускается от непривилегированного пользователя (например, `UID 10001`), он сталкивается с ошибкой `Permission Denied` при попытке записи в смонтированный том, принадлежащий `root:root`.

Решение на уровне спецификации Pod:
```yaml
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    fsGroup: 20000
    fsGroupChangePolicy: OnRootMismatch
```

**Механизм работы `fsGroup`:**
1. Kubelet монтирует том.
2. GID группы владельца каталога и файлов изменяется на значение `fsGroup`.
3. Устанавливается флаг SGID (`chmod g+s`), благодаря чему все новые файлы, создаваемые внутри тома, автоматически наследуют группу `fsGroup`.

**Политика `fsGroupChangePolicy`:**
- `Always` (по умолчанию): Kubelet выполняет рекурсивный обход `chown -R` и `chmod -R` при каждом запуске Pod. На томах с миллионами файлов (кэши, хранилища картинок) это приводит к зависанию старта Pod на 10–30 минут и падению по таймауту.
- `OnRootMismatch`: Kubelet проверяет права только на корневом каталоге тома. Если владелец и права корня уже совпадают с `fsGroup`, рекурсивная смена прав пропускается. Это сокращает время запуска Pod до долей секунды.

### Режимы распространения монтирования (mountPropagation)

Параметр `mountPropagation` управляет передачей событий монтирования между пространствами имен монтирования (`mount namespaces`) хоста и контейнера:

| Режим | Поведение ядра Linux | Применение |
| :--- | :--- | :--- |
| `None` (по умолчанию) | Контейнер изолирован. Монтирования хоста, выполненные после старта контейнера, внутри не видны. | Обычные рабочие нагрузки (Deployments, StatefulSets). |
| `HostToContainer` | Контейнер видит новые точки монтирования, добавленные на хосте после его запуска (режим `rslave`). | Агенты резервного копирования, сканеры антивирусов. |
| `Bidirectional` | Точки монтирования, созданные контейнером, проецируются на хост и во все другие контейнеры (режим `rshared`). | CSI Node-драйверы, CNI-плагины. **Требует `privileged: true` в SecurityContext.** |

### Подпути монтирования (subPath и subPathExpr)

Параметр `subPath` указывает конкретную поддиректорию внутри тома вместо его корня:

```yaml
volumeMounts:
- name: data-volume
  mountPath: /etc/nginx/conf.d/vhost.conf
  subPath: vhost.conf
```

**Механизм `subPathExpr` (динамическая подстановка):**
Позволяет использовать переменные окружения контейнера (например, имя Pod или IP из Downward API) для создания изолированных поддиректорий внутри общего тома:

```yaml
spec:
  containers:
  - name: app
    env:
    - name: POD_NAME
      valueFrom:
        fieldRef:
          fieldPath: metadata.name
    volumeMounts:
    - name: cluster-logs
      mountPath: /var/log/app
      subPathExpr: $(POD_NAME)
  volumes:
  - name: cluster-logs
    persistentVolumeClaim:
      claimName: shared-logs-nfs-pvc
```

### Рекурсивная блокировка записи (recursiveReadOnly)

Начиная с Kubernetes 1.30 (Alpha) и 1.31 (Beta), параметр `recursiveReadOnly` в `volumeMounts` усиливает безопасность монтирования:

```yaml
volumeMounts:
- name: host-system
  mountPath: /host/etc
  readOnly: true
  recursiveReadOnly: Enabled
```

**Зачем это нужно:** обычный флаг `readOnly: true` блокирует запись только в корневую точку монтирования. Если внутри монтируемого дерева каталогов присутствуют вложенные точки монтирования (`mount points`), ядро Linux могло оставлять их доступными для записи. `recursiveReadOnly` применяет флаг `MS_RDONLY` рекурсивно ко всем поддеревьям на уровне системного вызова `mount_setattr()`.

### Маркировка SELinux и оптимизация SELinuxMountReadWriteOncePod

В дистрибутивах Linux с активным SELinux (RHEL, Rocky Linux, AlmaLinux) каждый Pod получает уникальную категорию MCS (Multi-Category Security), например `s0:c123,c456`.
По умолчанию Kubelet вынужден рекурсивно выполнять `chcon -R` для всех файлов тома, что создает колоссальную нагрузку на I/O.

В Kubernetes 1.30+ механизм **`SELinuxMountReadWriteOncePod`** (GA) позволяет Kubelet монтировать тома сразу с нужным контекстом ядра через опцию монтирования:
`-o context="system_u:object_r:container_file_t:s0:c123,c456"`
Рекурсивная смена меток пропускается, решая проблему задержек запуска Pod на RHEL-системах.

---

## Практические сценарии

### Сценарий 1: Инъекция секретов и сертификатов с жестким ограничением прав

Задача: безопасно пробросить приватный ключ и сертификат в контейнер приложения с правами доступа `0400`, гарантируя запуск от непривилегированного пользователя.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secured-api-gateway
  namespace: production
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 10005
    runAsGroup: 10005
    fsGroup: 10005
    fsGroupChangePolicy: OnRootMismatch
  containers:
  - name: gateway
    image: nginx:1.27-alpine
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop: ["ALL"]
    volumeMounts:
    - name: tls-certs
      mountPath: /etc/ssl/certs/app
      readOnly: true
    - name: nginx-cache
      mountPath: /var/cache/nginx
  volumes:
  - name: tls-certs
    secret:
      secretName: api-gateway-tls
      defaultMode: 0400
  - name: nginx-cache
    emptyDir:
      sizeLimit: 256Mi
```

**Проверка прав внутри контейнера:**
```bash
kubectl exec -n production secured-api-gateway -- ls -la /etc/ssl/certs/app
# → -r-------- 1 10005 10005 1675 Oct 13 16:45 tls.key
# → -r-------- 1 10005 10005 2145 Oct 13 16:45 tls.crt
```

### Сценарий 2: Shared Memory (`/dev/shm`) и локальный кэш через emptyDir

Задача: настроить ускоренный обмен данными между процессами через shared memory без риска заполнения оперативной памяти сервера хоста.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: ml-inference-node
spec:
  containers:
  - name: model-server
    image: python:3.12-slim
    resources:
      requests:
        memory: "4Gi"
      limits:
        memory: "8Gi"
    volumeMounts:
    - name: shm-memory
      mountPath: /dev/shm
  volumes:
  - name: shm-memory
    emptyDir:
      medium: Memory
      sizeLimit: 4Gi
```

**Проверка точки монтирования:**
```bash
kubectl exec ml-inference-node -- df -h /dev/shm
# → Filesystem  Size  Used  Avail  Use%  Mounted on
# → tmpfs       4.0G     0   4.0G    0%  /dev/shm
```

### Сценарий 3: Сбор логов узла через hostPath с правами ReadOnly

Задача: развернуть агент сбора системных журналов в виде DaemonSet, обеспечив безопасный доступ к файлам логов узла.

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-log-collector
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: node-log-collector
  template:
    metadata:
      labels:
        app: node-log-collector
    spec:
      tolerations:
      - operator: Exists
      containers:
      - name: promtail
        image: grafana/promtail:3.0.0
        securityContext:
          readOnlyRootFilesystem: true
          runAsUser: 0
        volumeMounts:
        - name: host-varlog
          mountPath: /var/log
          readOnly: true
        - name: host-machine-id
          mountPath: /etc/machine-id
          readOnly: true
      volumes:
      - name: host-varlog
        hostPath:
          path: /var/log
          type: Directory
      - name: host-machine-id
        hostPath:
          path: /etc/machine-id
          type: File
```

### Сценарий 4: Generic Ephemeral Volume для CI/CD раннеров

Задача: предоставить агенту компиляции изолированный SSD-диск размером 50 ГБ, который будет гарантированно очищен и удален вместе с завершением Pod.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: ci-build-runner-4921
  namespace: ci-runners
spec:
  restartPolicy: Never
  containers:
  - name: runner
    image: maven:3.9-eclipse-temurin-21
    command: ["mvn", "clean", "package"]
    volumeMounts:
    - name: build-cache
      mountPath: /root/.m2
  volumes:
  - name: build-cache
    ephemeral:
      volumeClaimTemplate:
        metadata:
          labels:
            lifecycle: ephemeral-ci-build
        spec:
          accessModes: [ "ReadWriteOnce" ]
          storageClassName: "local-fast-nvme"
          resources:
            requests:
              storage: 50Gi
```

### Сценарий 5: Raw Block Volume (`volumeDevices`) для высокопроизводительной СУБД

Задача: передать неформатированный блочный LUN напрямую в контейнер базы данных.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: high-performance-db
spec:
  containers:
  - name: db-engine
    image: postgres:17-bookworm
    volumeDevices:
    - name: raw-storage
      devicePath: /dev/xvdba
  volumes:
  - name: raw-storage
    persistentVolumeClaim:
      claimName: fast-nvme-block-pvc
```

**Проверка типа блочного устройства:**
```bash
kubectl exec high-performance-db -- ls -la /dev/xvdba
# → brw-rw---- 1 root disk 259, 1 Oct 13 16:50 /dev/xvdba
```

---

## Операции и команды диагностики

### Анализ конфигурации томов через kubectl

Просмотр смонтированных томов и параметров безопасности Pod:
```bash
kubectl get pod app-worker -o jsonpath='{range .spec.volumes[*]}{.name}{"\t"}{range .}{keys .}{"\n"}{end}{end}'
# → app-config    [configMap name]
# → app-secrets   [name secret]
# → dshm          [emptyDir name]
```

Проверка событий монтирования томов планировщиком и Kubelet:
```bash
kubectl get events --field-selector reason=FailedMount --sort-by='.metadata.creationTimestamp'
# → 2m   Warning   FailedMount   pod/app-worker   MountVolume.SetUp failed for volume "db-creds" : secret "db-creds" not found
```

Проверка потребления дискового пространства эфемерными томами:
```bash
kubectl describe pod app-worker | grep -A 5 "Ephemeral Storage:"
# → Ephemeral Storage:  150Mi
# → Requests:           100Mi
# → Limits:             500Mi
```

### Диагностика монтирований на узле Linux (Sysadmin)

Определение UID пода для поиска каталогов Kubelet:
```bash
kubectl get pod app-worker -o jsonpath='{.metadata.uid}'
# → c9a3e210-9b45-4e31-8c01-f14d88e4a91b
```

Просмотр активных точек монтирования томов данного Pod на узле:
```bash
findmnt -R /var/lib/kubelet/pods/c9a3e210-9b45-4e31-8c01-f14d88e4a91b/volumes
# → TARGET                                                                      SOURCE     FSTYPE OPTIONS
# → .../volumes/kubernetes.io~empty-dir/dshm                                    tmpfs      tmpfs  rw,nosuid,nodev,size=1048576k
# → .../volumes/kubernetes.io~secret/app-secrets                                tmpfs      tmpfs  ro,relatime,size=1024k
```

Проверка использования диска внутри директорий томов Pod на узле:
```bash
du -sh /var/lib/kubelet/pods/c9a3e210-9b45-4e31-8c01-f14d88e4a91b/volumes/*
# → 24M   /var/lib/kubelet/pods/.../kubernetes.io~empty-dir/scratch
# → 4.0K  /var/lib/kubelet/pods/.../kubernetes.io~secret/tls-cert
```

### Метрики Prometheus для мониторинга томов (SRE)

Kubelet экспортирует встроенные метрики файловых систем томов:

| Метрика Prometheus | Назначение | Пороговое значение алерта |
| :--- | :--- | :--- |
| `kubelet_volume_stats_used_bytes` | Фактический объем данных в томе | > 85% от `capacity_bytes` |
| `kubelet_volume_stats_capacity_bytes` | Полная емкость смонтированного тома | Информационная |
| `kubelet_volume_stats_inodes_used` | Количество занятых индексных дескрипторов (inode) | > 85% от `inodes` |
| `container_fs_usage_bytes` | Потребление файловой системы контейнера | Приближение к `limits.ephemeral-storage` |

**PromQL-запрос для выявления томов с исчерпанием inode:**
```promql
100 * (kubelet_volume_stats_inodes_used / kubelet_volume_stats_inodes) > 85
```

---

## Диагностика и устранение неисправностей

### Ошибка 1: Pod зависает в Pending / ContainerCreating с ошибкой FailedMount

**Симптомы:** статус `ContainerCreating`, в выводе `kubectl describe pod` события:
`MountVolume.SetUp failed for volume "vault-token" : secret "vault-token" not found`.

**Причина:** объект Secret или ConfigMap не существует в том же Namespace, что и Pod, либо указано неверное имя ключа.

**Решение:**
1. Проверить существование объекта: `kubectl get secret vault-token -n <namespace>`.
2. Если Secret/ConfigMap создается асинхронно внешним оператором (External Secrets Operator, cert-manager), добавить параметр `optional: true` в спецификацию тома, если приложение допускает запуск без этих файлов.

### Ошибка 2: Файлы Secret/ConfigMap не обновляются внутри работающего контейнера

**Симптомы:** данные в Secret обновлены, но приложение продолжает читать старую конфигурацию.

**Причина:**
Монтирование выполнено через параметр `subPath`. При монтировании `subPath` контейнер связывается напрямую с inode отдельного файла, отключая механизм атомарного переключения символических ссылок Kubelet (`..data`).

**Решение:**
Монтировать весь том целиком в отдельный каталог без использования `subPath`:
```yaml
# ОШИБКА:
volumeMounts:
- name: cfg
  mountPath: /app/config.yaml
  subPath: config.yaml

# ПРАВИЛЬНО:
volumeMounts:
- name: cfg
  mountPath: /app/config
volumes:
- name: cfg
  configMap:
    name: app-cfg
```

### Ошибка 3: Выселение Pod с кодом The node was low on resource: ephemeral-storage

**Симптомы:** Pod внезапно переходит в статус `Failed` с причиной `Evicted`.

**Причина:**
Контейнер писал логи или временные файлы в директорию `emptyDir` (или собственный слой записи rootfs) без ограничений, превысив лимит `ephemeral-storage` или свободное место на системном диске узла хоста.

**Решение:**
1. Ограничить размер томов `emptyDir` параметром `sizeLimit`:
   ```yaml
   emptyDir:
     sizeLimit: 2Gi
   ```
2. Указать жесткие квоты в секции `resources.limits`:
   ```yaml
   resources:
     limits:
       ephemeral-storage: "4Gi"
   ```
3. Настроить ротацию логов внутри контейнера или перенаправить их в `stdout`/`stderr`.

### Ошибка 4: Permission Denied при записи в смонтированный том

**Симптомы:** контейнер завершается с ошибкой `open /data/app.db: permission denied`.

**Причина:**
Процесс запущен от непривилегированного пользователя (например, `UID 1000`), а каталог тома на узле принадлежит `root:root` с маской `0755`.

**Решение:**
1. Указать `fsGroup` в `securityContext` Pod:
   ```yaml
   spec:
     securityContext:
       fsGroup: 1000
       fsGroupChangePolicy: OnRootMismatch
   ```
2. Для томов `hostPath` права доступа должны быть предварительно скорректированы на файловой системе хоста либо через `initContainer`, выполняющий `chown -R 1000:1000 /mnt/path`.

### Ошибка 5: Зависание Pod в Terminating из-за сбоя размонтирования NFS/CSI

**Симптомы:** Pod удален, но висит в `Terminating` часами. `kubectl describe pod` показывает:
`Unable to unmount volume "/var/lib/kubelet/pods/.../volumes/kubernetes.io~nfs/...": device or resource busy`.

**Причина:**
Сетевое хранилище недоступно или процесс внутри контейнера завис в `D-state` (Uninterruptible Sleep), удерживая открытые файловые дескрипторы на точке монтирования.

**Диагностика и решение:**
1. Подключиться по SSH к узлу хоста.
2. Проверить процессы, удерживающие точку монтирования:
   ```bash
   lsof +D /var/lib/kubelet/pods/<pod-uid>/volumes/...
   # или
   fuser -vm /var/lib/kubelet/pods/<pod-uid>/volumes/...
   ```
3. При сетевом сбое выполнить принудительное ленивое размонтирование на хосте:
   ```bash
   umount -l /var/lib/kubelet/pods/<pod-uid>/volumes/kubernetes.io~nfs/<vol-name>
   ```
Подробнее: [Диагностика проблем размонтирования томов](../../../Troubleshooting/Common_Errors/PodTerminating/volume_unmount_issues.md).

---

## Рекомендации и Best Practices

### Чек-лист безопасности и надежности монтирования

1. **Никогда не используйте hostPath для прикладных приложений:** применяйте `hostPath` исключительно для системных DaemonSet (мониторинг, CNI, сбор логов). Для прикладного локального хранилища используйте `local` PV с `nodeAffinity` или `Generic Ephemeral Volumes`.
2. **Всегда задавайте sizeLimit для emptyDir:** отсутствие `sizeLimit` позволяет любому процессу переполнить физический диск узла, спровоцировав статус `DiskPressure` и массовое выселение всех подов с ноды.
3. **Всегда задавайте fsGroupChangePolicy: OnRootMismatch:** для всех томов с `fsGroup` объемом свыше 10 ГБ или содержащих более 10 000 файлов предотвращайте зависание старта Pod из-за рекурсивного `chown`.
4. **Монтируйте Secret и ConfigMap в режиме readOnly: true:** предотвращает случайную перезапись виртуальных файлов процессами контейнера.
5. **Используйте defaultMode 0400 или 0440 для томов Secret:** минимизирует риски чтения ключей сторонними процессами внутри многопользовательских образов.
6. **Контролируйте subPath:** помните, что `subPath` отключает автоматическую ротацию файлов при изменении ConfigMap/Secret. Если требуется динамическое обновление конфигов без перезапуска Pod, монтируйте всю директорию целиком.
7. **Для баз данных и брокеров сообщений рассмотрите Raw Block Volumes:** передача дисков через `volumeDevices` устраняет накладные расходы файловых систем ext4/xfs и повышает IOPS.

---

## Дополнительная информация

### Сравнение модели хранения Kubernetes и Docker

| Характеристика | Kubernetes Volumes | Docker Volumes |
| :--- | :--- | :--- |
| **Управление** | Декларативное через API Kubernetes (YAML, GitOps). | Императивное через Docker CLI (`docker volume create`). |
| **Жизненный цикл** | Строго привязан к Pod (кроме постоянных PV/PVC). | Независим от жизненного цикла контейнера. |
| **Масштабируемость** | Весь кластер (интеграция с CSI, динамический провижининг). | Локально в пределах одной виртуальной машины/хоста. |
| **Контроль прав** | `fsGroup`, `fsGroupChangePolicy`, PSS Admission. | Базовые права Linux-пользователя демона dockerd. |
| **Поддержка Raw Block** | Нативная поддержка (`volumeDevices`). | Требует ручной проброски через `--device`. |

### Связанные разделы базы знаний

- [Projected Volumes — агрегация источников конфигурации](./projected_volumes.md)
- [Downward API — доступ к метаданным Pod](../downward_api.md)
- [Основы работы с Secret](../../secrets/secrets_basics.md)
- [Best Practices по ConfigMap](../../ConfigMap/best_practices.md)
- [Pod Security Context и стандарты безопасности PSA](../../../Security/pod_security_context.md)
- [User Namespaces в Pod — изоляция прав](../user_namespaces.md)
- [PV, PVC и StorageClass — детальный разбор](../../../Storage/pv_and_pvc.md)
- [Продвинутая работа с PV и PVC](../../../Storage/pv_pvc_advanced.md)
- [Обзор архитектуры CSI-драйверов](../../../Storage/CSI/csi_overview.md)
- [Продвинутые возможности CSI в Kubernetes](../../../Storage/CSI/csi_advanced.md)
- [Local Path Provisioner — легковесное локальное хранилище](../../../Storage/local-path-provisioner.md)
- [Диагностика проблем размонтирования томов (Volume Unmount)](../../../Troubleshooting/Common_Errors/PodTerminating/volume_unmount_issues.md)
- [Ошибки томов при создании контейнеров (volume_issues)](../../../Troubleshooting/Common_Errors/CreateContainerConfigError/volume_issues.md)
