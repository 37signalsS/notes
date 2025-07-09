# Хранение данных: PV, PVC и StorageClass

Kubernetes предоставляет мощную и гибкую систему для управления хранилищами данных, которая абстрагирует детали конкретной системы хранения от приложений. Ключевыми компонентами этой системы являются `PersistentVolume` (PV), `PersistentVolumeClaim` (PVC) и `StorageClass`.

---

### 1. PersistentVolume (PV)

**PersistentVolume (PV)** — это "кусок" хранилища в кластере, который был предоставлен администратором. Это ресурс кластера, так же как и узел (node). PV имеет свой жизненный цикл, независимый от любого пода, который его использует.

PV содержит детали реализации хранилища: тип (NFS, iSCSI, облачное хранилище), размер, путь и т.д.

### 2. PersistentVolumeClaim (PVC)

**PersistentVolumeClaim (PVC)** — это запрос на хранилище от пользователя (или пода). Он похож на то, как под запрашивает CPU и память. Под запрашивает определенный размер и режим доступа (например, `ReadWriteOnce`), и Kubernetes находит подходящий PV для удовлетворения этого запроса.

Когда PVC связывается с PV, этот PV становится "занятым" и не может быть использован другим PVC.

### 3. StorageClass

**StorageClass** — это механизм, который позволяет **динамически создавать** PV. Вместо того чтобы администратор вручную создавал PV, он может создать один или несколько `StorageClass`, которые описывают "классы" хранилищ (например, "быстрый-ssd" и "медленный-hdd").

Когда пользователь создает PVC, указывая определенный `StorageClass`, система (с помощью специального **provisioner'а**) автоматически создает соответствующий PV и связывает его с PVC.

---

### Пример: Динамическое выделение хранилища

В этом примере под запрашивает хранилище через PVC, а `StorageClass` с `provisioner`'ом от облачного провайдера автоматически создает необходимый диск.

```yaml
# 1. StorageClass (обычно уже предоставлен облачным провайдером)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: standard-ssd
provisioner: kubernetes.io/aws-ebs # Пример для AWS
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

### Режимы доступа (`accessModes`)

*   `ReadWriteOnce` (RWO): Том может быть смонтирован для чтения и записи одним узлом.
*   `ReadOnlyMany` (ROX): Том может быть смонтирован только для чтения многими узлами.
*   `ReadWriteMany` (RWX): Том может быть смонтирован для чтения и записи многими узлами.
*   `ReadWriteOncePod` (RWOP): Том может быть смонтирован для чтения и записи одним подом.
