# Тома в Kubernetes

## Определения

**Volume (том)** — логическая абстракция хранилища данных, предоставляющая Pod (подам) доступ к файловой системе вне жизненного цикла отдельных контейнеров. В Kubernetes тома имеют жизненный цикл, строго привязанный к Pod: они создаются при запуске Pod и (в большинстве случаев) уничтожаются при его удалении.

**CSI (Container Storage Interface)** — стандарт де-факто для интеграции Kubernetes с внешними системами хранения. В 2026 году все встроенные (in-tree) плагины для облачных провайдеров (AWS, GCP, Azure) и систем хранения (Ceph, GlusterFS) полностью удалены из кодовой базы Kubernetes в пользу соответствующих CSI-драйверов.

**Ephemeral Storage (эфемерное хранилище)** — тома, предназначенные для временных данных. Их содержимое теряется при удалении Pod или его перезапуске на другом узле.

**Persistent Storage (персистентное хранилище)** — тома, данные в которых сохраняются независимо от состояния Pod. Реализуются через механизмы `PersistentVolume` (PV) и `PersistentVolumeClaim` (PVC).

---

## Базовые концепции

### Назначение томов

| Проблема | Решение через Volume |
| :--- | :--- |
| **Эфемерность контейнера** | Сохранение файлов при аварийном перезапуске контейнера внутри того же Pod. |
| **Shared Storage** | Совместный доступ к данным для нескольких контейнеров в одном Pod (например, Sidecar паттерн). |
| **Инъекция конфигураций** | Подстановка `ConfigMap`, `Secret` и метаданных ([Downward API](../downward_api.md)) прямо в ФС. |
| **Доставка артефактов** | Использование OCI-образов как источника данных через тип `image` (v1.31+). |

### Механизм подключения

Описание тома в манифесте Pod состоит из двух этапов:

1.  **Спецификация тома (`spec.volumes`)**: определение источника данных и присвоение ему имени.
2.  **Монтирование тома (`spec.containers[*].volumeMounts`)**: указание пути внутри контейнера (`mountPath`) и параметров доступа (например, `readOnly: true`).

### Классификация типов томов

| Тип | Категория | Статус (2026) | Основное назначение |
| :--- | :--- | :--- | :--- |
| `emptyDir` | Эфемерное | Stable | Кэш, временные файлы, RAM-диски, shared memory. |
| `hostPath` | Эфемерное | Stable | Доступ к ресурсам Node (мониторинг, логи, системные задачи). |
| `secret` | Эфемерное | Stable | Инъекция секретов (пароли, токены, ключи) в ФС контейнера. |
| `configMap` | Эфемерное | Stable | Инъекция конфигурационных файлов и переменных окружения. |
| `downwardAPI` | Эфемерное | Stable | Доступ к метаданным Pod и контейнера (IP, имя, лимиты). |
| `projected` | Эфемерное | Stable | Агрегация нескольких источников (secret, configMap, downwardAPI) в один путь. |
| `image` | Эфемерное | Beta (v1.31+) | Монтирование OCI-образов как источника данных. |
| `nfs` | Эфемерное/Персистентное | Stable | Общий доступ к данным через NFS-сервер (ReadWriteMany). |
| `local` | Персистентное | Stable | Привязка к локальному диску конкретного узла (высокая производительность). |
| `csi` (inline) | Эфемерное | Stable | Временные тома через CSI-драйверы (Secret Store, вどうしても drivers). |
| `ephemeral` | Эфемерное | Stable | Generic Ephemeral Volumes (динамические временные PVC). |
| `pvc` | Персистентное | Stable | Постоянное хранение данных через PersistentVolumeClaim. |

---

## Основные типы томов

### emptyDir

**Описание:** пустая директория, создаваемая на узле при запуске Pod.
- **`medium: Memory`**: создает том в оперативной памяти (tmpfs). Это значительно ускоряет ввод-вывод, но данные потребляют лимиты памяти контейнера (`Memory Limits`).
- **`sizeLimit`**: ограничивает максимальный объем тома. При превышении лимита Kubelet выселяет (evict) Pod с узла.
- **Применение:** обмен данными между `initContainer` и основным приложением, временные папки компиляции.

**Жизненный цикл данных в emptyDir:**

| Событие | Данные в emptyDir |
|:---|:---|
| Перезапуск контейнера (OOM, crash) | **Сохраняются** — том привязан к Pod, а не к контейнеру |
| Перезапуск Pod (рестарт узла, обновление) | **Теряются** — Pod удаляется, том уничтожается |
| Drain узла с подом | **Теряются** — Pod выселяется и пересоздается на другом узле |
| Удаление Pod | **Теряются** — том удаляется вместе с Pod |

**Разница между перезапуском контейнера и Pod:**
- При перезапуске контейнера (например, при OOMKilled с кодом 137) том `emptyDir` **сохраняется**, так как перезапускается только процесс контейнера внутри существующего Pod. Это позволяет сохранить кэш или временные данные между перезапусками.
- При перезапуске Pod (удаление и создание нового) том `emptyDir` **уничтожается** вместе со старым Pod.

**Работа с несколькими контейнерами:**
Если в Pod два контейнера и один из них монтирует `emptyDir`, а другой нет — данные в `emptyDir` принадлежат Pod целиком. Контейнер без монтирования не видит данные, но они физически существуют на узле. При перезапуске контейнера данные сохраняются для обоих. При перезапуске Pod данные теряются для обоих.

**Пример использования с `medium: Memory` для shared memory:**
```yaml
volumeMounts:
- name: dshm
  mountPath: /dev/shm
volumes:
- name: dshm
  emptyDir:
    medium: Memory
    sizeLimit: 256Mi
```

### hostPath

**Описание:** монтирование файла или папки с файловой системы узла (Node) в контейнер. Один из наиболее используемых типов для системных задач и инфраструктурных компонентов.

**Типы (`type`) и их поведение:**

| Тип | Поведение при отсутствии пути | Применение |
| :--- | :--- | :--- |
| `DirectoryOrCreate` | Создаёт директорию с правами `0755`, владелец — Kubelet. | Кэш, временные данные, подготовка путей для DaemonSet. |
| `Directory` | **Фейл** если путь не существует. | Монтирование заранее подготовленных путей (`/var/log`). |
| `FileOrCreate` | Создаёт пустой файл с правами `0644`, владелец — Kubelet. | Конфигурационные файлы, PID-файлы. |
| `File` | **Фейл** если путь не существует. | Монтирование конкретных файлов (например, `/etc/resolv.conf`). |
| `Socket` | **Фейл** если не Unix-сокет. | Docker-сокет (`/var/run/docker.sock`) для Dind-сценариев. |
| `CharDevice` | **Фейл** если не символьное устройство. | Доступ к `/dev/kmsg`, `/dev/null`. |
| `BlockDevice` | **Фейл** если не блочное устройство. | Raw-доступ к дискам, LVM-устройствам. |

**Безопасность и ограничения:**
- Требует привилегированного режима или разрешений в [Pod Security Standards](../../Security/pod_security_context.md). В режиме `restricted` PSA `hostPath` запрещён.
- Дает контейнеру полный доступ к файловой системе хоста, что מהווה критический вектор атаки.
- Нарушает мобильность приложений — Pod будет работать корректно только на тех узлах, где подготовлены соответствующие пути.
- **Рекомендация:** избегайте `hostPath` для приложений; используйте `PersistentVolume` или `CSI`-драйверы. Применяйте только для инфраструктурных компонентов (node-exporter, Fluentd, CNI-плагины).

**Типичные сценарии использования:**
- Монтирование `/var/log` для сбора логов агентами (Fluentd, Filebeat).
- Монтирование `/var/run/docker.sock` для управления Docker из контейнера.
- Монтирование `/etc/machine-id` для идентификации узла.
- Монтирование `/dev` для прямого доступа к устройствам (GPU-операции, LVM).

### image (v1.31+)

**Описание:** позволяет использовать OCI-образ (или артефакт из реестра) как источник тома.
- **Зачем:** доставка больших статических файлов (конфиги, сертификаты, бинарные утилиты) без увеличения размера основного образа приложения.
- **Особенности:** монтируется строго в режиме **ReadOnly**. Поддерживает `pullPolicy`. Требует поддержки рантайма (например, `containerd` 2.0+).

### secret

**Описание:** монтирует содержимое объекта [Secret](../../Base/secrets/secrets_basics.md) как файлы в указанной директории. Каждый ключ Secret становится отдельным файлом в томе.

**Особенности:**
- Файлы монтируются в `tmpfs` (RAM) по умолчанию — данные не пишутся на диск узла.
- Можно указать конкретные ключи через `items` или смонтировать все ключи.
- Права доступа по умолчанию `0444` (только чтение для всех). Рекомендуется переопределять через `defaultMode`.
- При обновлении Secret Kubelet обновляет файлы в томе (с задержкой до 1 минуты, см. `syncFrequency`).

**Механизм обновления:**
Kubelet монтирует Secret через символическую ссылку. При изменении содержимого Secret создаётся новая временная директория, данные копируются туда, и ссылка атомарно переключается на новую директорию. Это гарантирует, что чтение файла не увидит «половину» старых и «половину» новых данных.

**Пример использования:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-secrets
spec:
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: db-credentials
      mountPath: /etc/secrets
      readOnly: true
  volumes:
  - name: db-credentials
    secret:
      secretName: database-password
      defaultMode: 0400
      items:
      - key: password
        path: db/password.txt
      - key: username
        path: db/username.txt
```

**Ограничения:**
- Secret должен существовать в том же Namespace, что и Pod.
- Максимальный размер Secret — 1 MiB (ограничение etcd).
- Secret не шифруется на диске по умолчанию (требуется `EncryptionConfiguration`).
- При перезапуске Pod файлы Secret пересоздаются с актуальными данными.

### configMap

**Описание:** монтирует содержимое объекта [ConfigMap](../../Base/ConfigMap/best_practices.md) как файлы или переменные окружения. Аналогично Secret, но предназначен для неконфиденциальных данных.

**Особенности:**
- Каждый ключ ConfigMap становится файлом в томе.
- В отличие от Secret, файлы записываются на диск (не в tmpfs).
- Поддерживает атомарное обновление через символические ссылки (аналогично Secret).
- Обновление файла внутри контейнера происходит **только** при монтировании всего тома (не через `subPath`).

**Пример использования:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-config
spec:
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: app-config
      mountPath: /etc/app/config
      readOnly: true
  volumes:
  - name: app-config
    configMap:
      name: app-settings
      items:
      - key: nginx.conf
        path: nginx.conf
      - key: logging.yaml
        path: logging.yaml
```

**Разница между монтированием через volume и через env:**

| Способ | Механизм | Обновление | Применение |
| :--- | :--- | :--- | :--- |
| **Volume** | Файлы в директории | Атомарное обновление через symlinks | Конфигурационные файлы (`nginx.conf`, `application.yml`) |
| **env** | Переменные окружения | **Не обновляется** после запуска | Простые настройки, переменные окружения |

**Ограничения:**
- ConfigMap должен существовать в том же Namespace.
- Максимальный размер — 1 MiB (ограничение etcd).
- Ключи должны быть валидными POSIX-именами файлов (без `/`, `..`).

### downwardAPI

**Описание:** монтирует метаданные Pod и контейнера как файлы в указанной директории. Позволяет приложению получать информацию о себе без обращения к API-серверу Kubernetes.

Подробнее: [Downward API — доступ к метаданным Pod](../downward_api.md).

**Краткий пример:**
```yaml
volumes:
- name: pod-info
  downwardAPI:
    items:
    - path: "labels"
      fieldRef:
        fieldPath: metadata.labels
    - path: "cpu-limit"
      resourceFieldRef:
        containerName: app
        resource: limits.cpu
```

### NFS (Network File System)

**Описание:** монтирование общей NFS-директории в контейнер. Позволяет нескольким Pod'ам на разных узлах одновременно читать и записывать одни и те же данные.

**Режимы доступа:**
- `ReadWriteOnce (RWO)` — доступ только с одного узла (для одного Pod).
- `ReadOnlyMany (ROX)` — доступ на чтение с нескольких узлов.
- `ReadWriteMany (RWX)` — доступ на чтение и запись с нескольких узлов (только NFS и少数 СХД).

**Пример использования:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: nfs-pod
spec:
  containers:
  - name: app
    image: nginx:1.27
    volumeMounts:
    - name: nfs-storage
      mountPath: /usr/share/nginx/html
  volumes:
  - name: nfs-storage
    nfs:
      server: 192.168.1.100
      path: /exports/www
      readOnly: false
```

**Преимущества:**
- Простая настройка, не требует CSI-драйверов.
- Поддержка RWX (общий доступ для нескольких Pod'ов).
- Не требует динамического провижининга.

**Недостатки:**
- Точкой отказа является NFS-сервер (Single Point of Failure).
- Задержка сетевого ввода-вывода выше, чем у локальных дисков.
- Ограниченная производительность для random I/O (базы данных).
- Нет встроенной поддержки снапшотов и клонирования.

**Рекомендации для продакшена:**
- Используйте NFS v4.1+ (поддержка параллельных операций).
- Настройте `noresvport` для отказоустойчивости.
- Рассмотрите CSI-драйвер для NFS (например, `nfs-subdir-external-provisioner`) для динамического провижининга.

### Local Volume

**Описание:** привязка тома к конкретному локальному диску на узле. В отличие от `hostPath`, обеспечивает интеграцию с механизмами планирования Kubernetes — Pod будет запланирован только на узел, где доступен соответствующий `PersistentVolume`.

**Ключевые особенности:**
- Используется через механизм `PersistentVolume` (PV), а не как прямой тип тома в Pod.
- Требует предварительной подготовки дисков администратором.
- Поддерживает `nodeAffinity` для привязки PV к конкретному узлу.
- Не поддерживает динамическое провижининга (тома создаются вручную).

**Пример PV с local volume:**
```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: local-pv-ssd
spec:
  capacity:
    storage: 100Gi
  volumeMode: Filesystem
  accessModes:
  - ReadWriteOnce
  persistentVolumeReclaimPolicy: Delete
  storageClassName: local-ssd
  local:
    path: /mnt/disks/ssd1
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - node-01
```

**Сравнение с hostPath:**

| Характеристика | `hostPath` | `local` PV |
| :--- | :--- | :--- |
| **Планирование** | Без учёта наличия данных | Учитывает `nodeAffinity` |
| **Управление** | Прямое монтирование в Pod | Через PV/PVC |
| **Reclaim Policy** | Нет | `Delete` или `Retain` |
| **Рекомендация** | Инфраструктурные компоненты | StatefulSet с локальной производительностью |

### CSI (Container Storage Interface) — inline ephemeral

**Описание:** позволяет создавать временные (эфемерные) тома через CSI-драйверы без создания PV/PVC. Подходит для сценариев, где нужен быстрый доступ к временным ресурсам (HashiCorp Vault, cert-manager, Secret Store CSI Driver).

**Пример использования с Secret Store CSI Driver:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: vault-pod
spec:
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: vault-secrets
      mountPath: /etc/secrets
      readOnly: true
  volumes:
  - name: vault-secrets
    csi:
      driver: secrets-store.csi.k8s.io
      readOnly: true
      volumeAttributes:
        secretProviderClass: vault-backend
```

**Отличия от Generic Ephemeral Volumes:**

| Характеристика | CSI inline | Generic Ephemeral |
| :--- | :--- | :--- |
| **Механизм** | Напрямую через CSI-драйвер | Через PVC (динамический провижининг) |
| **Размер** | Определяется драйвером | Определяется пользователем |
| **Поддержка** | Только CSI-драйверы с inline-поддержкой | Любая StorageClass |
| **Сценарий** | Secrets, сертификаты, временные ключи | Временные SSD, кэши, staging-данные |

### Projected Volume (тип projected)

Агрегирует данные из `Secret`, `ConfigMap`, `Downward API` и `ServiceAccountToken` в одну точку монтирования.
Подробнее: [Projected Volumes — агрегация источников](./projected_volumes.md).

### Generic Ephemeral Volumes (тип ephemeral)

Позволяет создавать временные тома, используя все возможности PVC (динамический провижининг, разные типы дисков), но с жизненным циклом Pod. Идеально для приложений, которым нужны быстрые локальные SSD для временных данных.

---

## Безопасность и управление монтированием

### Права доступа (fsGroup)

В `spec.securityContext` можно указать `fsGroup`. При монтировании тома Kubernetes автоматически рекурсивно изменит владельца (UID/GID) всех файлов на указанную группу.
- **`fsGroupChangePolicy`**:
    - `Always`: менять права при каждом запуске (может быть медленно на больших томах).
    - `OnRootMismatch`: менять только если права на корневой папке не совпадают (ускоряет запуск).

### recursiveReadOnly (v1.30+ Alpha/Beta)

Гарантирует, что если том помечен как `readOnly: true`, то все под-монтирования (sub-mounts) внутри него также становятся недоступными для записи на уровне ядра. Это закрывает потенциальную дыру в безопасности, связанную с `hostPath` монтированиями.

### VolumeAttributesClass (v1.31+ Beta)

Позволяет динамически изменять параметры тома (IOPS, пропускная способность — Throughput) без изменения его размера и без перезапуска приложений. Это реализуется через новый API-ресурс, который дополняет `StorageClass`.

### Параметры монтирования (volumeMounts)

Секция `volumeMounts` в описании контейнера определяет, как том будет доступен внутри контейнера.

**Основные параметры:**

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `name` | Имя тома (должно совпадать с определением в `spec.volumes`). | Обязательный |
| `mountPath` | Путь внутри контейнера, куда будет смонтирован том. | Обязательный |
| `readOnly` | Только чтение (true/false). Рекомендуется для Secret, ConfigMap, внешних хранилищ. | `false` |
| `subPath` | Поддиректория внутри тома для монтирования (вместо корня). | Корень тома |
| `subPathExpr` | Шаблон для `subPath` с использованием переменных окружения (` Downward API`). | Нет |
| `mountPropagation` | Режим распространения информации о монтировании между контейнерами и ядром. | `None` |
| `recursiveReadOnly` | Рекурсивная блокировка записи для всех подмонтированных ФС (v1.30+). | Нет |

**`subPath` — монтирование поддиректории:**
```yaml
volumeMounts:
- name: shared-data
  mountPath: /app/logs
  subPath: logs          # Монтирует /data/logs → /app/logs
  readOnly: false
```

**Важные ограничения `subPath`:**
- Обновления ConfigMap/Secret **не отражаются** в файлах, смонтированных через `subPath`.
- При использовании `subPathExpr` переменные окружения должны быть определены в Pod.

**`mountPropagation` — режимы распространения:**

| Режим | Описание | Применение |
| :--- | :--- | :--- |
| `None` | Монтирование не распространяется (по умолчанию). | Стандартные приложения. |
| `HostToContainer` | Монтирования, выполненные на хосте до запуска Pod, видны контейнеру. | Монтирование внешних дисков. |
| `Bidirectional` | Контейнер может выполнять монтирования, которые видны хосту и другим Pod'ам. | Привилегированные DaemonSet (CNI, storage-плагины). **Опасно** — требует privileged. |

---

## Практические сценарии

### Сценарий 1: Инъекция секретов через volume

Монтирование Secret как файлов с ограниченными правами доступа. Идеально для приложений, которые читают конфигурацию из файлов.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-secrets
spec:
  securityContext:
    fsGroup: 1000
    fsGroupChangePolicy: OnRootMismatch
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: db-creds
      mountPath: /etc/secrets
      readOnly: true
  volumes:
  - name: db-creds
    secret:
      secretName: postgres-credentials
      defaultMode: 0400
      items:
      - key: password
        path: db/password
      - key: username
        path: db/username
```

**Проверка:**
```bash
kubectl exec app-secrets -- cat /etc/secrets/db/password
# → <secret-value>

kubectl exec app-secrets -- ls -la /etc/secrets/db/
# → -r-------- 1 root root 12 Aug 28 10:00 password
# → -r-------- 1 root root 8 Aug 28 10:00 username
```

### Сценарий 2: Доставка данных через image volume

Монтирование OCI-образа как источника статических данных (конфигурации, сертификаты, бинарные утилиты).

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: static-data-pod
spec:
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: static-assets
      mountPath: /app/static
      readOnly: true
  volumes:
  - name: static-assets
    image:
      reference: registry.example.com/static-assets:v2
      pullPolicy: IfNotPresent
```

### Сценарий 3: Изоляция логов через subPathExpr

Позволяет монтировать одну и ту же директорию в разные контейнеры, но в разные подпапки на основе переменных Pod.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: multi-container-logs
spec:
  containers:
  - name: app
    image: my-app:latest
    env:
    - name: POD_NAME
      valueFrom:
        fieldRef:
          fieldPath: metadata.name
    volumeMounts:
    - name: logs-volume
      mountPath: /var/log/app
      subPathExpr: $(POD_NAME)
  - name: log-reader
    image: busybox
    volumeMounts:
    - name: logs-volume
      mountPath: /var/log/reader
      subPathExpr: $(POD_NAME)
  volumes:
  - name: logs-volume
    emptyDir: {}
```

### Сценарий 4: Атомарное обновление ConfigMap

При монтировании всего тома `ConfigMap` обновления происходят атомарно через смену символических ссылок. Если монтировать через `subPath`, автоматическое обновление файла внутри контейнера **не произойдет**.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: configmap-atomic
spec:
  containers:
  - name: nginx
    image: nginx:1.27
    volumeMounts:
    - name: nginx-config
      mountPath: /etc/nginx/nginx.conf
      subPath: nginx.conf   # ← ОШИБКА: не будет обновляться!
  volumes:
  - name: nginx-config
    configMap:
      name: nginx-config
```

**Правильный подход (для обновляемых конфигов):**
```yaml
    volumeMounts:
    - name: nginx-config
      mountPath: /etc/nginx/nginx.conf
      subPath: nginx.conf
      # Для обновления: монтируйте всю директорию
    - name: nginx-config-full
      mountPath: /etc/nginx/conf.d
  volumes:
  - name: nginx-config-full
    configMap:
      name: nginx-config
```

### Сценарий 5: NFS для общего хранилища логов

Настройка общего хранилища для сбора логов с нескольких Pod'ов.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: log-collector
spec:
  containers:
  - name: fluentd
    image: fluent/fluentd-kubernetes-daemonset:latest
    volumeMounts:
    - name: shared-logs
      mountPath: /var/log/shared
  volumes:
  - name: shared-logs
    nfs:
      server: 10.0.0.5
      path: /exports/logs
```

### Сценарий 6: Local Volume для высокопроизводительных БД

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: local-ssd-postgres
spec:
  capacity:
    storage: 500Gi
  volumeMode: Filesystem
  accessModes:
  - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: local-ssd
  local:
    path: /mnt/disks/nvme0
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - db-node-01
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-data
spec:
  accessModes:
  - ReadWriteOnce
  storageClassName: local-ssd
  resources:
    requests:
      storage: 500Gi
```

---

## Типичные ошибки и их решение

### Ошибка 1: Файлы Secret/ConfigMap не обновляются

**Причина:** Монтирование через `subPath` отключает механизм обновления через символические ссылки.

**Решение:** Монтируйте весь том целиком и используйте `items` для выбора конкретных ключей:
```yaml
# Неправильно:
volumeMounts:
- name: config
  mountPath: /etc/app/config.yaml
  subPath: config.yaml    # ← Не обновляется!

# Правильно:
volumeMounts:
- name: config
  mountPath: /etc/app     # ← Монтируется вся директория
volumes:
- name: config
  configMap:
    name: app-config
    items:
    - key: config.yaml
      path: config.yaml
```

### Ошибка 2: Pod не запускается из-за отсутствия hostPath

**Причина:** `type: Directory` или `type: File` требуют наличия пути на хосте.

**Решение:** Используйте `type: DirectoryOrCreate` или `type: FileOrCreate`:
```yaml
volumes:
- name: cache
  hostPath:
    path: /var/cache/app
    type: DirectoryOrCreate  # Создаст папку, если её нет
```

### Ошибка 3: NFS-том недоступен после перезапуска Pod

**Причина:** NFS-сервер недоступен или Pod запланирован на узел без сетевого доступа к NFS.

**Решение:**
1. Проверьте доступность NFS-сервера: `showmount -e <nfs-server>`.
2. Убедитесь, что Pod запланирован на узел с доступом к NFS (через `nodeSelector` или `nodeAffinity`).
3. Рассмотрите использование `PersistentVolume` с `nodeAffinity` вместо прямого монтирования NFS.

### Ошибка 4: DiskPressure из-за emptyDir без sizeLimit

**Причина:** Приложения, пишущие в `emptyDir` без ограничения `sizeLimit`, могут заполнить диск узла.

**Решение:** Всегда указывайте `sizeLimit`:
```yaml
volumes:
- name: cache
  emptyDir:
    sizeLimit: 1Gi
```

Хранение emptyDir-томов на узле: `/var/lib/kubelet/pods/<pod-uid>/volumes/kubernetes.io~empty-dir/`.

### Ошибка 5: Permission denied при записи в том

**Причина:** UID/GID контейнера не совпадает с владельцем файлов в томе.

**Решение:** Используйте `fsGroup` в `securityContext`:
```yaml
spec:
  securityContext:
    fsGroup: 1000        # GID для группы
    runAsUser: 1000      # UID пользователя
```

---

## Дополнительная информация

### Сравнение с Docker Volumes

| Характеристика | Kubernetes Volume | Docker Volume |
| :--- | :--- | :--- |
| **Управление** | Декларативное (YAML, API) | Императивное (CLI) |
| **Масштаб** | Весь кластер (через CSI) | Локально на одном хосте |
| **Жизненный цикл** | Привязан к Pod (кроме PVC) | Независим от контейнера |
| **Безопасность** | `fsGroup`, `recursiveReadOnly` | Ограничено правами процесса |

**Связанные темы:**
- [PV, PVC и StorageClass — детальный разбор](../../../Storage/pv_and_pvc.md)
- [Projected Volumes — детальное описание](./projected_volumes.md)
- [Downward API — доступ к метаданным Pod](../downward_api.md)
- [Обзор CSI и современные драйверы](../../../Storage/CSI/csi_overview.md)
- [Продвинутые возможности CSI](../../../Storage/CSI/csi_advanced.md)
- [Local Path Provisioner — локальное хранилище](../../../Storage/local-path-provisioner.md)
- [Troubleshooting: проблемы с томами](../../../Troubleshooting/Common_Errors/PodTerminating/volume_unmount_issues.md)
