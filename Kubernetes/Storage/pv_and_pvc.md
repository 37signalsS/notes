# Хранение данных: PV, PVC и StorageClass

## Определения

* **`PersistentVolume` (PV)** — ресурс кластера, представляющий "кусок" хранилища (NFS, RBD, CephFS, облачный диск). Имеет независимый от подов жизненный цикл. Содержит параметры СХД: тип, размер, путь, ID тома.

* **`PersistentVolumeClaim` (PVC)** — запрос к PV на выделение места. По аналогии с подами, запрашивающими CPU/память, PVC запрашивает у PV объём хранилища и режим доступа. При связывании PVC с PV, PV переходит в статус `Bound`.

* **`StorageClass` (SC)** — механизм описания "классов" или "профилей" хранилища ("быстрый-ssd", "медленный-hdd"). Ключевой компонент — **`provisioner`** (плагин для взаимодействия с СХД). Современный стандарт — **[Container Storage Interface (CSI)](./CSI/csi_overview.md)**.

## Базовые концепции

### Проблема прямого управления томами

Изначально в Kubernetes тома определялись непосредственно в манифесте пода (`awsElasticBlockStore`, `gcePersistentDisk`).

Недостатки:

1. **Ручное создание томов** — администратор создаёт диски в СХД вручную.
2. **Жёсткая связь с инфраструктурой** — параметры доступа прописаны в манифесте приложения.
3. **Сложность миграции** — при смене облака требуется изменять манифесты всех приложений.

### Решение: трёхуровневая абстракция

* **Разработчик** — описывает требования: "нужно 10 ГБ быстрого хранилища с эксклюзивным доступом".
* **Администратор** — настраивает способы удовлетворения: "быстрое хранилище = SSD в облаке".

### Режимы выделения хранилища

#### Динамическое выделение (Dynamic Provisioning) — рекомендуемый способ

Автоматический, событийно-ориентированный подход, который является стандартом для большинства кластеров.

**Пошаговый рабочий процесс:**

1.  **Администратор** настраивает `StorageClass` и разворачивает в кластере **provisioner** — специальное приложение-контроллер, которое умеет работать с конкретной системой хранения.
2.  **Разработчик** создает `PersistentVolumeClaim` (PVC), в котором запрашивает нужный объем и указывает `storageClassName`. Запрос уходит в Kubernetes API.
3.  **Provisioner**, который подписан на события создания PVC, обнаруживает новый PVC, соответствующий его `StorageClass`.
4.  Provisioner обращается к API системы хранения (например, AWS API или NFS сервер) и отдает команду на создание физического хранилища (диска, директории).
5.  После успешного создания хранилища, provisioner создает в Kubernetes объект `PersistentVolume` (PV) с информацией о новом ресурсе.
6.  Kubernetes автоматически **связывает (binds)** этот новый PV с PVC разработчика. PVC переходит в статус `Bound`.
7.  Теперь под может использовать этот PVC для монтирования тома.

**Преимущество:** Полная автоматизация. Разработчику не нужно знать детали инфраструктуры, а администратору не нужно вручную создавать тома под каждый запрос.

#### Статическое выделение (Static Provisioning)

Для интеграции с существующими СХД, где тома уже созданы:

1. **Администратор** вручную создаёт в Kubernetes объект PV, описывающий существующий том.
2. **Разработчик** создаёт PVC с параметрами, подходящими под существующий PV.
3. **Kubernetes** связывает PVC с подходящим PV.

> **Разница:** статически — PVC получает весь PV (может быть избыточно); динамически — создаётся PV точно под запрошенный размер.

### Логика связывания PV и PVC

1. **Фильтрация по `StorageClassName`**: рассматриваются PV, у которых `storageClassName` совпадает с запрошенным в PVC. Если в PVC класс не указан, используются PV без класса.
2. **Фильтрация по `accessModes`**: отбрасываются PV, которые не поддерживают режим доступа из PVC (например, PVC хочет `RWX`, а PV предоставляет только `RWO`).
3. **Фильтрация по размеру**: отбрасываются PV меньше запрошенного.
4. **Best Fit**: из оставшихся PV выбирается наименьший подходящий PV.

### Политика возврата (reclaimPolicy)

Политика `reclaimPolicy` указывается в `PersistentVolume` и определяет, что произойдет с нижележащим томом (диском в облаке) после того, как `PersistentVolume` будет освобожден (т.е. удален PVC, который его использовал).

* **`Retain` (Сохранить) — Рекомендуется для важных данных.**
  * **Что происходит:** После удаления PVC объект PV переходит в статус `Released`, но сам PV и физический том на СХД **сохраняются**.
  * **Действия администратора:** Данные остаются нетронутыми. Администратор должен вручную очистить том и либо удалить его, либо сделать доступным для другого PVC (удалив и пересоздав объект PV).
* **`Delete` (Удалить) — По умолчанию для динамических provisioner'ов.**
  * **Что происходит:** После удаления PVC **удаляются и объект PV, и физический том** в системе хранения.
  * **Использование:** Удобно для временных данных или в средах разработки/тестирования, где не страшно потерять данные. **Опасно для production!**
* **`Recycle` (Переиспользовать) — Устарело (Deprecated).**
  * **Что происходит:** Выполнялась базовая очистка (`rm -rf /thevolume/*`) тома. Этот метод больше не рекомендуется из-за проблем с безопасностью и неэффективности.

### Режимы доступа (accessModes)

* `ReadWriteOnce` (RWO): Том может быть смонтирован для чтения и записи **одним узлом**.
* `ReadOnlyMany` (ROX): Том может быть смонтирован только для чтения **многими узлами**.
* `ReadWriteMany` (RWX): Том может быть смонтирован для чтения и записи **многими узлами**.
* `ReadWriteOncePod` (RWOP): Том может быть смонтирован для чтения и записи **одним подом** (эксклюзивный доступ для пода).

## Практические сценарии

### Пример: Динамическое выделение в облаке (AWS EBS)

```yaml
# 1. StorageClass (обычно уже предоставлен облачным провайдером)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: standard-ssd
provisioner: ebs.csi.aws.com # Пример для AWS (CSI-драйвер)
parameters:
  type: gp2
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer

---
# 2. PersistentVolumeClaim (PVC)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-app-pvc
spec:
  accessModes:
    - ReadWriteOnce # Эксклюзивный доступ на чтение/запись
  storageClassName: standard-ssd # Запрос к конкретному классу хранилища
  resources:
    requests:
      storage: 10Gi # Запрос на 10 ГиБ

---
# 3. Pod, использующий PVC
apiVersion: v1
kind: Pod
metadata:
  name: my-app-pod
spec:
  containers:
    - name: my-app
      image: nginx
      ports:
        - containerPort: 80
      volumeMounts:
        # Монтируем том, предоставленный PVC, в контейнер
        - name: my-storage
          mountPath: /usr/share/nginx/html
  volumes:
    - name: my-storage
      # Указываем, что источником тома является наш PVC
      persistentVolumeClaim:
        claimName: my-app-pvc
```

### Пример: Динамическое выделение с NFS Provisioner (Out-of-Tree)

В bare-metal или тестовых окружениях часто используется `nfs-client-provisioner` для динамического создания томов на NFS-сервере.

1.  **Развертывание Provisioner'а:** Сначала в кластер устанавливается сам provisioner (например, через Helm-чарт). Это `Deployment`, который будет следить за PVC.

2.  **Создание `StorageClass`:** Администратор создает `StorageClass`, который указывает на этот provisioner.

    ```yaml
    # sc-nfs.yaml
    apiVersion: storage.k8s.io/v1
    kind: StorageClass
    metadata:
      name: managed-nfs-storage
    # Указываем имя нашего provisioner'а
    provisioner: cluster.local/nfs-client-provisioner
    parameters:
      archiveOnDelete: "false"
    ```

3.  **Создание `PVC`:** Разработчик создает PVC, как и в облачном сценарии, но указывает `storageClassName: managed-nfs-storage`.

    ```yaml
    # pvc-nfs-dynamic.yaml
    apiVersion: v1
    kind: PersistentVolumeClaim
    metadata:
      name: my-dynamic-nfs-pvc
    spec:
      storageClassName: managed-nfs-storage
      accessModes:
        - ReadWriteMany
      resources:
        requests:
          storage: 1Gi
    ```
    **Результат:** `nfs-client-provisioner` создаст на NFS-сервере уникальную директорию (например, `pvc-xxxx-xxxx`) и создаст `PV`, который на нее ссылается.

### Пример: статическое выделение для NFS

Этот сценарий подходит, когда нужно подключить **уже существующий** NFS-ресурс к кластеру.

1.  **Создание `PersistentVolume` (PV) (задача администратора):**
    Администратор описывает доступный NFS-том как ресурс кластера.

    ```yaml
    # pv-nfs.yaml
    apiVersion: v1
    kind: PersistentVolume
    metadata:
      name: nfs-logs-pv
    spec:
      capacity:
        storage: 10Gi
      accessModes:
        - ReadWriteMany # NFS поддерживает одновременную запись с нескольких узлов
      # Политика сохранения данных после удаления PVC
      persistentVolumeReclaimPolicy: Retain
      # Указываем тип тома - NFS
      nfs:
        path: /var/k8s-logs # Путь на NFS-сервере
        server: 192.168.1.100 # IP-адрес NFS-сервера
    ```

2.  **Создание `PersistentVolumeClaim` (PVC) (задача разработчика):**
    Разработчик запрашивает хранилище, не зная деталей реализации.

    ```yaml
    # pvc-nfs.yaml
    apiVersion: v1
    kind: PersistentVolumeClaim
    metadata:
      name: fluentd-logs-pvc
      namespace: logging
    spec:
      accessModes:
        - ReadWriteMany # Запрашиваемый режим доступа должен поддерживаться PV
      resources:
        requests:
          storage: 10Gi # Запрашиваемый объем
      # storageClassName: "" # Пустое имя класса, чтобы Kubernetes искал среди PV без класса
    ```
    Kubernetes найдет `nfs-logs-pv`, так как он удовлетворяет требованиям по `accessModes` и `storage`, и свяжет его с `fluentd-logs-pvc`.

3.  **Использование в поде:**
    Под `fluentd` монтирует хранилище через PVC.

    ```yaml
    # fluentd-pod.yaml
    apiVersion: v1
    kind: Pod
    metadata:
      name: fluentd
      namespace: logging
    spec:
      containers:
        - name: fluentd
          image: fluent/fluentd
          volumeMounts:
            - name: log-storage
              mountPath: /fluentd/log
      volumes:
        - name: log-storage
          persistentVolumeClaim:
            claimName: fluentd-logs-pvc
    ```

### StatefulSet с PersistentVolume

Для Stateful-приложений (БД) используется **[StatefulSet](../Base/statefulset.md)**. Он автоматически создаёт уникальный PVC для каждого пода с именем `<claimName>-<podName>` на основе `volumeClaimTemplates`.

## Дополнительная информация

* **CSI (Container Storage Interface):** стандартный интерфейс для интеграции СХД — см. [Container Storage Interface (CSI)](./CSI/csi_overview.md)
* **StatefulSet и PVC:** подробнее в [StatefulSet](../Base/statefulset.md)
* **VolumeSnapshots:** см. [CSI Volume Snapshots](../CSI/csi_overview.md#работа-с-snapshots)
* **Официальная документация:** [Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/), [Storage Classes](https://kubernetes.io/docs/concepts/storage/storage-classes/)
