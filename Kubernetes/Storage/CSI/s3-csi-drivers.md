# S3 CSI-драйверы в Kubernetes

S3 (Simple Storage Service) — это объектное хранилище, которое при использовании специальных драйверов можно монтировать в Kubernetes как файловую систему. Это решение идеально подходит для Read-Heavy нагрузок (статический контент, медиа-архивы, большие датасеты и артефакты), но имеет ограничения по сравнению с традиционными блочными хранилищами.

## Определения

**S3 CSI Driver** — программный интерфейс, позволяющий Kubernetes-кластеру взаимодействовать с объектными хранилищами по протоколу S3, представляя бакеты как стандартные тома (`PersistentVolumes`).

**Маунтер (Mounter)** — утилита (обычно на базе FUSE), которая выполняет фактическое преобразование вызовов файловой системы (POSIX) в API-запросы S3 (GET, PUT, LIST). Маунтер запускается драйвером на узле в момент `NodePublishVolume` и монтирует бакет (или его префикс) в каталог пода.
*   **GeeseFS** — высокопроизводительный маунтер (форк Goofys, написан на Go), оптимизированный для агрессивного параллелизма и асинхронных операций. Даёт почти полную POSIX-совместимость (частичные записи, truncate, fsync), но по умолчанию не сохраняет права доступа и пользовательские времена изменения файлов.
*   **Mountpoint for Amazon S3** — официальный FUSE-маунтер от AWS на Rust, ориентированный на максимальную пропускную способность при чтении больших объёмов. Реализует ограниченное подмножество POSIX-семантики, детально описанное в [SEMANTICS.md](https://github.com/awslabs/mountpoint-s3/blob/main/doc/SEMANTICS.md).
*   **JuiceFS** — распределённая файловая система, использующая S3 для хранения данных и внешнюю БД (Redis, SQL) для метаданных, обеспечивающая полную POSIX-совместимость и безопасный параллельный доступ.

---

## Базовые концепции

### Архитектура и компоненты
Типичный S3 CSI-драйвер состоит из стандартных Sidecar-контейнеров и специфичных компонентов поставщика:

1.  **Controller Plugin (Deployment):** Отвечает за создание/удаление бакетов (Dynamic Provisioning) и управление `VolumeAttachments`.
2.  **Node Plugin (DaemonSet):** Работает на каждом узле, выполняет монтирование бакета через FUSE в файловую систему хоста, а затем в контейнер пода.

### Типы монтирования
*   **Статическое (Static):** Бакет (или префикс внутри бакета) уже существует, драйверу передаются только учетные данные и имя бакета. Драйвер **не создаёт и не удаляет** бакет — при удалении PV объекты в хранилище сохраняются. Подходит для подключения уже наполненных бакетов (архивы, общие данные).
*   **Динамическое (Dynamic):** Драйвер сам создает бакет в S3 при создании `PersistentVolumeClaim` (при удалении PVC бакет/префикс удаляется). Поддерживается не всеми драйверами (например, AWS Mountpoint поддерживает только статическое провижионирование).

### Маунтеры: модель данных и ограничения объектных хранилищ

Объектное хранилище принципиально отличается от файловой системы: бакет — это плоское пространство имён, где «папки» и «файлы» — лишь ключи объектов. Любой FUSE-маунтер эмулирует иерархию и POSIX-семантику, что накладывает ограничения:

*   **Операции с метаданными дорогие:** каждый `stat`/`ls` превращается в S3-запросы (HEAD/LIST). Маунтеры кэшируют метаданные (в GeeseFS — `--entry-limit` и `--stat-cache-ttl`, по умолчанию 100000 записей и TTL 60 с), поэтому активный листинг одной директории с многих узлов — плохая нагрузка на хранилище.
*   **Права и время файлов не сохраняются:** по умолчанию GeeseFS не хранит `chmod`/`chown` и custom `mtime` — глобальные права задаются опциями `--dir-mode`/`--file-mode`. Полноценная поддержка прав, владельца и симлинков есть только у Yandex S3 (включается `--enable-perms`, `--enable-mtime`); для остальных S3 `chmod`/`chown` на смонтированном бакете не персистятся.
*   **Нет жёстких ссылок и файловых блокировок:** нет `hard link`, нет `flock`/`fcntl`-локов — параллельная запись из нескольких подов в один файл ядром не координируется.
*   **`fsync` — эмуляция записи на сервер:** асинхронные маунтеры буферизуют изменения и сбрасывают их на хранилище асинхронно; чтобы гарантировать сохранность, приложение должно явно вызывать `fsync` (иначе данные долго не попадают в S3). Системный `sync`/`syncfs` через FUSE не работает.
*   **Перезапись существующих объектов:** поддержка частичных перезаписей/дозаписи зависит от маунтера и бэкенда; GeeseFS для обновления объекта выполняет серверную side-copy (`UploadPartCopy`), а дешёвые partial updates (`--enable-patch`) доступны только для Yandex S3.
*   **Консистентность зависит от бэкенда:** AWS S3 гарантирует сильную консистентность read-after-write для новых объектов (с 2020 года); для self-hosted решений (MinIO, Ceph RGW) наблюдаемые гарантии могут отличаться. Матрица проверок — [are-we-consistent-yet](https://github.com/gaul/are-we-consistent-yet).

**Практическое следствие:** режим доступа `ReadWriteMany` означает «много подов могут читать и писать», но **не** «много подов могут писать в один и тот же файл параллельно». Для надёжности на FUSE-маунтерах (GeeseFS, s3fs) выдерживайте правило одного писателя на файл либо используйте JuiceFS (у него метаданные и блокировки реализованы в собственной мета-БД). Запуск реляционных СУБД (PostgreSQL, MySQL) поверх таких томов недопустим — им нужны файловые блокировки и случайная перезапись. Подробнее о механике FUSE — [FUSE (Filesystem in Userspace)](../../../Linux/FileSystems/fuse.md).

Сравнение совместимости маунтеров: [матрица GeeseFS](https://github.com/yandex-cloud/geesefs#posix-compatibility-matrix) и [поведение Mountpoint](https://github.com/awslabs/mountpoint-s3/blob/main/doc/SEMANTICS.md).

### Обзор актуальных решений

#### 1. Yandex Cloud CSI (k8s-csi-s3)

Универсальное решение для S3-совместимых хранилищ (Yandex Object Storage, MinIO, Ceph RGW). Пригодно и для on-prem, и для публичных облаков.

*   **GitHub:** [yandex-cloud/k8s-csi-s3](https://github.com/yandex-cloud/k8s-csi-s3)
*   **Имя драйвера / провижионер:** `ru.yandex.s3.csi` (`CSIDriver` создаётся с `attachRequired: false`, `podInfoOnMount: true`).
*   **Маунтер:** GeeseFS (по умолчанию), также поддерживаются `s3fs` и `rclone`.
*   **Преимущества:** поддержка динамического провижионирования (бакет на том), высокая стабильность, частичная запись (overwrite).
*   **Требования:** Kubernetes 1.17+, разрешены привилегированные поды, на узлах установлен FUSE и доступен `/dev/fuse`.

Установка через Terraform (Helm):

```hcl
resource "helm_release" "yandex-csi-s3" {
  name             = "yandex-csi-s3"
  repository       = "https://yandex-cloud.github.io/k8s-csi-s3/charts"
  chart            = "csi-s3"
  namespace        = "kube-system"

  values = [
    <<-EOT
      secret:
        accessKey: "${var.s3_access_key}"
        secretKey: "${var.s3_secret_key}"
        endpoint: "http://minio.minio.svc.cluster.local:9000"  # для on-prem MinIO/RGW
        region: "us-east-1"                                    # для MinIO; можно оставить пустым
    EOT
  ]
}
```

Или через Helm CLI:

```bash
helm repo add yandex-s3 https://yandex-cloud.github.io/k8s-csi-s3/charts
helm install --namespace kube-system csi-s3 yandex-s3/csi-s3 \
  --set secret.accessKey=<ACCESS_KEY> \
  --set secret.secretKey=<SECRET_KEY> \
  --set secret.endpoint=http://minio.minio.svc.cluster.local:9000 \
  --set secret.region=us-east-1
```

Чарт автоматически создаёт `Secret` (ключи `accessKeyID`, `secretAccessKey`, `endpoint`, `region`) и `StorageClass` `csi-s3` с полным набором secret-ссылок. Имя Secret и его namespace должны совпадать со ссылками в StorageClass (см. [Динамическое провижионирование](#динамическое-провижионирование-minio--ceph-rgw)).

#### 2. AWS Mountpoint S3 CSI Driver (v2.x)

*   **GitHub:** [awslabs/mountpoint-s3-csi-driver](https://github.com/awslabs/mountpoint-s3-csi-driver)
*   **Helm:** `helm repo add aws-mountpoint-s3-csi-driver https://awslabs.github.io/mountpoint-s3-csi-driver`
*   **Статус:** v2 — GA с июля 2025; для v2 требуется Kubernetes ≥ 1.31, поддерживаются x86-64 и arm64.
*   **Особенности:** только **статическое провижионирование** (бакет должен существовать); **Mountpoint Pod Sharing** (несколько подов разделяют один инстанс маунтера на узле — экономия ресурсов); управляемый локальный кэш (`emptyDir` / generic ephemeral volume); в v2 добавлены EKS Pod Identity и поддержка SELinux-окружений.
*   **Сценарий:** стандарт для инфраструктуры на AWS; в EKS устанавливается через managed add-on. Полнота POSIX отличается от классических ФС — проверяйте совместимость приложения по [SEMANTICS.md](https://github.com/awslabs/mountpoint-s3/blob/main/doc/SEMANTICS.md).

#### 3. JuiceFS CSI Driver

*   **GitHub:** [juicedata/juicefs-csi-driver](https://github.com/juicedata/juicefs-csi-driver)
*   **Преимущества:** полная POSIX-совместимость, атомарные операции, распределённое кэширование (метаданные в БД, данные на локальных дисках узлов), корректный параллельный доступ благодаря мета-БД.
*   **Особенность архитектуры:** по умолчанию используется режим **mount pod** — для каждого тома запускается отдельный под с клиентом JuiceFS, а приложение подключается к нему через FUSE (маунт не зависит от контейнера node-plugin). Рекомендуемые ресурсы mount-пода: `requests` ≥ 1 CPU / 1 GiB, `limits` ≥ 2 CPU / 5 GiB.
*   **Сценарии:** высокопроизводительные вычисления (HPC), общие домашние каталоги (Shared Home), Big Data; также замещает классические файловые хранилища, где нужен полный POSIX.

Пример установки:

```bash
helm repo add juicefs-csi-driver https://juicedata.github.io/charts/
helm repo update
helm upgrade --install juicefs-csi-driver juicefs-csi-driver/juicefs-csi-driver \
  --namespace kube-system \
  --set storageClasses[0].name=juicefs-s3 \
  --set storageClasses[0].backend.type=s3 \
  --set storageClasses[0].backend.name=my-bucket \
  --set storageClasses[0].backend.metaurl=redis://redis.storage.svc.cluster.local:6379/1
```

#### 4. ctrox/csi-s3 (DEPRECATED)

> [!WARNING]
> Проект **архивирован** (17.04.2025) и не поддерживается. Использование в продуктовых средах запрещено. В README автор рекомендует в качестве замены форк [yandex-cloud/k8s-csi-s3](https://github.com/yandex-cloud/k8s-csi-s3).

---

## Практические сценарии

### Динамическое провижионирование (MinIO / Ceph RGW)

**Шаг 1. Учётные данные драйвера (`Secret`).** Драйвер берёт ключи только из Secret; для всех фаз жизненного цикла используется один и тот же Secret.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: csi-s3-secret
  namespace: kube-system
stringData:
  accessKeyID: <ACCESS_KEY>
  secretAccessKey: <SECRET_KEY>
  endpoint: http://minio.minio.svc.cluster.local:9000
  region: "" # для MinIO/RGW можно оставить пустым
```

Параметры:
- `accessKeyID` / `secretAccessKey` — ключи доступа S3 (в MinIO — создаются через `mc admin user add`, у Ceph RGW — `radosgw-admin user create`).
- `endpoint` — адрес хранилища, **доступный с рабочих узлов** кластера (для внутренних MinIO/RGW — `http://`, для публичных — `https://`).
- `region` — для self-hosted решений обычно пустой или `us-east-1` (дефолт MinIO).

**Шаг 2. StorageClass.** Без secret-ссылок динамическое провижионирование не работает: PVC зависнет в `Pending`, а в логах provisioner будет ошибка авторизации.

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: s3-geesefs
provisioner: ru.yandex.s3.csi
parameters:
  mounter: geesefs
  options: "--memory-limit 1000 --dir-mode 0777 --file-mode 0666"
  bucket: "" # Если пусто — бакет создаётся на том (имя = Volume ID); иначе — общий бакет, каждый том получает префикс = Volume ID
  csi.storage.k8s.io/provisioner-secret-name: csi-s3-secret
  csi.storage.k8s.io/provisioner-secret-namespace: kube-system
  csi.storage.k8s.io/controller-publish-secret-name: csi-s3-secret
  csi.storage.k8s.io/controller-publish-secret-namespace: kube-system
  csi.storage.k8s.io/node-stage-secret-name: csi-s3-secret
  csi.storage.k8s.io/node-stage-secret-namespace: kube-system
  csi.storage.k8s.io/node-publish-secret-name: csi-s3-secret
  csi.storage.k8s.io/node-publish-secret-namespace: kube-system
reclaimPolicy: Delete
```

Пояснения:
- `mounter` — какой маунтер использовать (`geesefs` / `s3fs` / `rclone`).
- `options` — опции маунтера: `--memory-limit 1000` ограничивает кэш данных в RAM (1 ГБ), `--dir-mode`/`--file-mode` задают глобальные права (права в объектном хранилище не хранятся).
- `bucket` — пустой → «бакет на том»; непустой → один общий бакет с префиксами; при удалении тома удаляется только префикс.
- `reclaimPolicy: Delete` — при удалении PVC удаляется префикс/бакет; `Retain` оставляет данные в хранилище (понадобится [статическое провижионирование](#статическое-провижионирование-существующий-бакет-или-префикс)).

**Шаг 3. PVC и использование в поде.**

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: s3-pvc
spec:
  accessModes:
    - ReadWriteMany # S3 по своей природе RWX
  resources:
    requests:
      storage: 50Gi
  storageClassName: s3-geesefs
```

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: s3-app
spec:
  containers:
    - name: app
      image: nginx
      volumeMounts:
        - name: data
          mountPath: /s3
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: s3-pvc
```

**Важно (devops):** `requests.storage` у объектного тома — «номинальное» значение; реальный объём он не ограничивает. Ограничьте бакет квотой на стороне хранилища (в MinIO — bucket quota, у RGW — жизненный цикл/квоты) и обязательно используйте один писатель на файл (`RWX` ≠ параллельные записи в один файл).

**Шаг 4. Проверка.**

```bash
kubectl get pvc s3-pvc
# → NAME     STATUS   VOLUME ...  ACCESS MODES   STORAGECLASS   AGE
# → s3-pvc   Bound    pvc-...      RWX            s3-geesefs     9s
```

### Статическое провижионирование (существующий бакет или префикс)

Если бакет уже существует и удалять его нельзя (архив, данные общего пользования), создайте PV вручную и привяжите PVC через `claimRef`. При удалении таких томов контент в хранилище **не** трогается.

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: s3-existing-bucket
spec:
  storageClassName: csi-s3
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteMany
  claimRef:
    namespace: default
    name: csi-s3-manual-pvc
  csi:
    driver: ru.yandex.s3.csi
    controllerPublishSecretRef:
      name: csi-s3-secret
      namespace: kube-system
    nodePublishSecretRef:
      name: csi-s3-secret
      namespace: kube-system
    nodeStageSecretRef:
      name: csi-s3-secret
      namespace: kube-system
    volumeAttributes:
      mounter: geesefs
      options: --memory-limit 1000 --dir-mode 0777 --file-mode 0666
    volumeHandle: "my-bucket"       # или <bucket>/<prefix> — монтируется префикс
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: csi-s3-manual-pvc
spec:
  storageClassName: "" # пустое значение отключает динамическое провижионирование
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 10Gi
```

Пояснения:
- `volumeHandle` — что именно монтируется (`bucket` или `bucket/prefix`); не удаляется при удалении PV.
- `claimRef` связывает PV с конкретным PVC до появления пода (без него PV останется `Available`).
- `storageClassName: ""` в PVC критичен — иначе появится динамический том вместо статического.

### Особенности on-prem объектных хранилищ (MinIO, Ceph RGW)

*   **Доступность endpoint с узлов:** перед проверкой пода выполните с узла `curl -I http://minio.minio.svc.cluster.local:9000` — FUSE-маунтер работает с узла, а не из пода.
*   **Path-style адресация:** внутренние хранилища обычно принимают path-style запросы (`http://host:port/bucket`); виртуально-хостовая адресация (`bucket.host:port`) требует настройки DNS-домена. Указывайте endpoint явно.
*   **Листинг:** для всех не-Yandex S3-бэкендов в GeeseFS рекомендуется задавать `--list-type 2` (или `--list-type 1`) в `options` — иначе возможны проблемы с перечислением каталогов.
*   **TLS:** если RGW отдаёт self-signed сертификат (cephadm ingress), добавьте корневой CA бэкенда в доверенные или используйте `http://` внутри кластера.
*   **FUSE на узлах:** установите пакет FUSE (`fuse3`) и проверьте наличие устройства монтирования: `ls -l /dev/fuse`. Подготовка узлов к другим драйверам описана в [Сравнении и эксплуатации CSI-драйверов](./csi_drivers_comparison.md), устройство Ceph RGW — в [Обзоре Ceph](../Ceph/ceph_overview.md).

### Проверка работоспособности после установки

```bash
# 1. Драйвер зарегистрирован и поды работают
kubectl get csidriver ru.yandex.s3.csi
kubectl get pods -n kube-system -l app=csi-s3

# 2. PVC в статусе Bound
kubectl get pvc s3-pvc
# → s3-pvc  Bound  pvc-...  RWX  s3-geesefs

# 3. Запись и чтение внутри пода
kubectl exec -it s3-app -- touch /s3/hello_world
kubectl exec -it s3-app -- ls -la /s3/

# 4. Тип маунта внутри пода
kubectl exec -it s3-app -- mount | grep fuse
# → <bucket>: on /s3 type fuse.geesefs (rw,nosuid,nodev,relatime,user_id=65534,group_id=0,default_permissions,allow_other)

# 5. На узле: маунт и systemd-сервис GeeseFS
mount | grep geesefs
systemctl status geesefs
# → The service geesefs has been started

# 6. Объект реально появился в хранилище (проверка снаружи кластера)
s3cmd ls s3://<bucket>/hello_world   # или mc ls <alias>/<bucket>/hello_world
```

GeeseFS по умолчанию монтирует бакеты **вне контейнера драйвера через systemd** — это сохраняет маунт живым при обновлении/перезапуске `csi-s3` и защищает от ошибки «Transport endpoint is not connected». Отключить такое поведение можно опцией `--no-systemd`.

### Тюнинг производительности

Опции GeeseFS задаются в поле `options` StorageClass/PV:

*   **Память:** `--memory-limit` (по умолчанию 1 ГБ — буферы чтения и записи), `--read-ahead-large` (по умолчанию 100 МБ линейного упреждающего чтения; снижайте до ~20 МБ при многих параллельных читателях), `--use-enomem` — жёсткий лимит с возвратом `ENOMEM`.
*   **Метаданные:** `--entry-limit` (кэш листингов, по умолчанию 100000 записей) и `--stat-cache-ttl` (по умолчанию 60 с) — уменьшают число HEAD/LIST-запросов к хранилищу.
*   **Пропускная способность записи:** `--no-checksum --max-flushers 32 --max-parallel-parts 32 --part-sizes 25` увеличивают параллелизм (цена — рост памяти и снижение максимального размера файла до ~250 ГБ). Пишите в несколько файлов одновременно, а не в один.
*   **Диагностика маунтера:** `--debug_s3 --debug_fuse --log-file /var/log/geesefs.log` — подробный лог запросов S3 и операций FUSE.
*   **Read-heavy нагрузки:** чтение больших файлов с линейным доступом эффективнее мелких файлов; избегайте массовых `stat` (например, `find`/`grep -r` по всему бакету).

---

## Дополнительная информация

### Сравнение производительности и лимитов

| Характеристика | AWS Mountpoint | Yandex (GeeseFS) | JuiceFS |
| :--- | :--- | :--- | :--- |
| **POSIX-совместимость** | Низкая | Средняя | **Полная** |
| **Dynamic Provisioning** | Нет | **Да** | **Да** |
| **Производительность (Small Files)** | Низкая | Средняя | **Высокая** |
| **Сценарии** | Big Data, Датасеты | CMS, Архивы | Shared Home, HPC |

> **Примечание:** «POSIX-совместимость» — характеристика не только маунтера, но и связки «маунтер + бэкенд»: гарантии консистентности у MinIO/RGW могут отличаться от AWS S3. Актуальные матрицы — [GeeseFS POSIX compatibility](https://github.com/yandex-cloud/geesefs#posix-compatibility-matrix) и [проверки консистентности](https://github.com/gaul/are-we-consistent-yet).

### Диагностика и устранение проблем

1.  **Ошибка монтирования (Mount failed):**
    *   Проверьте наличие установленного `fuse` на рабочих узлах кластера и устройства `/dev/fuse`.
    *   Убедитесь, что `endpoint` S3 доступен с узлов (проверка через `curl -I`).
2.  **Проблемы с правами (403 Forbidden):**
    *   Проверьте `Secret` с ключами доступа и совпадение его имени/namespace со ссылками в StorageClass или PV.
    *   Для AWS: проверьте IAM Role for Service Accounts (IRSA).
3.  **Низкая скорость:**
    *   Увеличьте количество параллельных потоков в параметрах маунтера (`--max-parallel-parts`, `--max-flushers`).
    *   Настройте локальное кэширование метаданных (`--entry-limit`, `--stat-cache-ttl`), проверьте `--memory-limit` (не упирается ли кэш).
4.  **PVC завис в `Pending`:** проверьте логи провижионера — `kubectl logs -n kube-system -l app=csi-provisioner-s3 -c csi-s3`. Типичные причины: отсутствует Secret, несовпадение namespace ссылок, StorageClass без `csi.storage.k8s.io/*-secret-*` параметров, а также ошибки создания бакета (ключам не хватает прав `s3:CreateBucket`, имя бакета в недопустимом регистре).
5.  **«Transport endpoint is not connected»:** маунт-процесс упал/перезапущен. С systemd-маунтом GeeseFS восстанавливается сам (`systemctl status geesefs`); после перезапуска csi-s3 проверьте, что маунт на узле жив (`mount | grep geesefs`).
6.  **Пустые каталоги / неверный листинг на не-Yandex S3:** добавьте `--list-type 2` (или `--list-type 1`) в `options` StorageClass.
7.  **Потеря обновлений при конкурентной записи:** в логах GeeseFS — `File xxx is deleted or resized remotely, discarding local changes`. Причина — несколько писателей в один файл с разных узлов. Соблюдайте правило одного писателя; после изменений на других хостах вызывайте принудительный refresh кэша: `setfattr -n .invalidate <filename>`.
8.  **`chmod`/`chown` не применяются:** GeeseFS не хранит права и владельца (кроме Yandex S3 с `--enable-perms`); глобальные права задаются `--dir-mode`/`--file-mode`. Ошибки «Permission denied» лечат настройкой этих опций, а не `chmod` на смонтированном бакете.

---

## См. также
* [Обзор CSI](./csi_overview.md)
* [Сравнение CSI-драйверов](./csi_drivers_comparison.md)
* [Объектное хранилище (S3) — концепции](../../../Concepts/Storage/data_storage_overview.md)
* [Persistent Volumes и PVC в Kubernetes](../pv_and_pvc.md)