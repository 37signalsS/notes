## Хранилище (Volumes) в подах

**Volume** — это абстракция файлового хранилища, которая решает следующие ключевые проблемы:

* Файловая система контейнера существует только до его удаления. `Volume` позволяет сохранять данные даже после перезапуска контейнера.
* Некоторым контейнерам в одном поде требуется общее пространство для обмена файлами.
* Абстрагирование приложения от конкретных технологий хранения данных на узле.

Жизненный цикл `Volume` совпадает с жизненным циклом **пода**, а не отдельного контейнера. Это означает, что данные в томе сохраняются при перезапуске контейнеров и теряются только тогда, когда удаляется сам под.

Механизм состоит из двух частей в манифесте пода:

1. `spec.volumes`: На уровне пода определяется список томов, которые будут доступны в этом поде. Здесь указывается имя тома и его тип (источник данных).
2. `spec.containers[*].volumeMounts`: На уровне каждого контейнера определяется, куда (`mountPath`) в его файловой системе будет смонтирован том, определенный в `spec.volumes`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: test-pd
spec:
  containers:
  - image: k8s.gcr.io/test-webserver
    name: test-container
    # Монтируем том 'test-volume' в директорию /test внутри контейнера
    volumeMounts:
    - mountPath: /test
      name: test-volume
  # На уровне пода определяем, что такое 'test-volume'
  volumes:
  - name: test-volume
    # В данном примере используется временный том emptyDir
    emptyDir: {}
```

### Основные типы томов

* **`emptyDir`**:
  * **Что это:** Каталог, который создается вместе с подом и живет, пока под не будет удален. Все контейнеры в поде могут читать и записывать данные в этот том.
  * **Источник:** По умолчанию используется файловая система узла. Также можно использовать `medium: Memory` для хранения в оперативной памяти (tmpfs).
  * **Использование:** Идеально подходит для временного хранения данных (например, кэша) или как общее пространство для обмена данными между контейнерами в одном поде. Данные **сохраняются** при перезапуске контейнера, но **теряются** при удалении пода.
  * **Параметры:**
    * `medium: Memory` — использовать RAM (tmpfs). **Важно:** потребляемая память учитывается в лимитах памяти контейнера. Без установленных лимитов памяти использование `medium: Memory` опасно — может привести к OOMKill.
    * `sizeLimit` — ограничение размера тома (например, `1Gi`). При превышении лимита под **evicted** (выселяется) с ноды.
  * **Важно:** Не используйте emptyDir для баз данных или персистентных данных — это эфемерное хранилище.
  * **Создание:** Создается kubelet на ноде, где работает под (директория `/var/lib/kubelet`).

* **`hostPath`**:
  * **Что это:** Монтирует уже существующий файл или директорию с файловой системы хостовой машины (Node) внутрь пода.
  * **Использование:** Применяется в специфичных случаях, когда поду нужен доступ к системным файлам узла. Например, для агентов мониторинга, которые должны читать системные логи, или для доступа к Docker-сокету.
  * **Ключи `DirectoryOrCreate` и `FileOrCreate`:** Эти опции указывают Kubernetes, что перед монтированием нужно проверить наличие директории или файла на хосте и создать их, если они отсутствуют.
  * **ВНИМАНИЕ:** Использование `hostPath` является **угрозой безопасности**. Это нарушает изоляцию контейнера и дает ему прямой доступ к файловой системе хоста, что может привести к компрометации узла. В правильно настроенных кластерах использование `hostPath` обычно строго ограничено или запрещено политиками безопасности (`PodSecurityPolicy` или `Pod Security Admission`).

* **`configMap` и `secret`**:
  * **Что это:** Позволяют "пробросить" данные из [ConfigMap](./configmap.md) или [Secret](../secrets/secrets_basics.md) в под в виде файлов.
  * **Использование:** Основной способ передачи конфигурационных файлов, TLS-сертификатов и других данных в приложение.

* **`persistentVolumeClaim`**:
  * **Что это:** Способ смонтировать постоянное (persistent) хранилище, жизненный цикл которого не зависит от пода.
  * **Использование:** Это стандартный и правильный способ для хранения данных приложений, которые должны сохраняться (базы данных, пользовательские файлы и т.д.). Подробнее см. в [PV, PVC и StorageClass](../Storage/pv_and_pvc.md).

#### Практический пример: обмен данными между контейнерами через emptyDir

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: producer-consumer
spec:
  volumes:
  - name: shared-data
    emptyDir: {}
  containers:
  # Контейнер-производитель: пишет данные
  - name: producer
    image: busybox
    command: ["sh", "-c", "while true; do echo $(date) >> /shared/data.txt; sleep 5; done"]
    volumeMounts:
    - name: shared-data
      mountPath: /shared
  # Контейнер-потребитель: читает данные
  - name: consumer
    image: busybox
    command: ["sh", "-c", "tail -f /shared/data.txt"]
    volumeMounts:
    - name: shared-data
      mountPath: /shared
```

### Downward API

**Downward API** — это механизм Kubernetes, который позволяет приложениям в контейнерах получать информацию о себе (метаданных пода) без обращения к Kubernetes API. Это упрощает архитектуру приложений и устраняет необходимость в RBAC для получения базовых метаданных.

#### Что можно получить через Downward API

| Параметр | Описание |
| :--- | :--- |
| `metadata.name` | Имя пода |
| `metadata.namespace` | Имя неймспейса |
| `metadata.uid` | UID пода |
| `metadata.annotations['<KEY>']` | Значение конкретной аннотации |
| `metadata.labels['<KEY>']` | Значение конкретной метки |
| `spec.nodeName` | Имя ноды, на которой работает под |
| `spec.serviceAccountName` | Имя ServiceAccount пода |
| `status.podIP` | IP-адрес пода |
| `status.hostIP` | IP-адрес ноды |
| `resources.limits['cpu']` | Лимит CPU |
| `resources.limits['memory']` | Лимит памяти |
| `resources.requests['cpu']` | Запрос CPU |
| `resources.requests['memory']` | Запрос памяти |

#### Через переменные окружения

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: downward-api-pod
  labels:
    app: myapp
    tier: backend
  annotations:
    description: "Main application pod"
spec:
  containers:
    - name: test-container
      image: busybox
      command: ["sh", "-c", "echo POD_NAME=$POD_NAME, NS=$POD_NAMESPACE, IP=$POD_IP"]
      env:
        - name: POD_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: POD_NAMESPACE
          valueFrom:
            fieldRef:
              fieldPath: metadata.namespace
        - name: POD_IP
          valueFrom:
            fieldRef:
              fieldPath: status.podIP
        - name: APP_LABEL
          valueFrom:
            fieldRef:
              fieldPath: metadata.labels['app']
        - name: CPU_LIMIT
          valueFrom:
            resourceFieldRef:
              containerName: test-container
              resource: limits.cpu
  restartPolicy: Never
```

#### Через тома

Downward API также можно смонтировать как том, что позволяет получить доступ к метаданным через файловую систему:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: downward-api-volume-pod
  labels:
    app: myapp
  annotations:
    annotation1: "value1"
spec:
  containers:
    - name: test-container
      image: busybox
      command: ["sh", "-c", "cat /etc/podinfo/*"]
      volumeMounts:
        - name: podinfo
          mountPath: /etc/podinfo
  volumes:
    - name: podinfo
      downwardAPI:
        items:
          - path: "pod_name"
            fieldRef:
              fieldPath: metadata.name
          - path: "pod_namespace"
            fieldRef:
              fieldPath: metadata.namespace
          - path: "labels"
            fieldRef:
              fieldPath: metadata.labels
          - path: "annotations"
            fieldRef:
              fieldPath: metadata.annotations
          - path: "cpu_limit"
            resourceFieldRef:
              resource: limits.cpu
              divisor: 1m
  restartPolicy: Never
```

#### Важные особенности

1. **Container vs Pod level**: Для `resourceFieldRef` (ресурсы контейнера) необходимо указывать `containerName`, так как в поде может быть несколько контейнеров.

2. **Динамические метки и аннотации**: При использовании томов изменения в метках или аннотациях пода отражаются в файловой системе. При использовании переменных окружения — только при перезапуске пода. Реализация использует symlinks (аналогично ConfigMap): файл в `/etc/podinfo/labels` ссылается на файл в директории `..data`.

3. **Ограничения**: Через Downward API нельзя получить полный манифест пода или информацию о других ресурсах. Для этого потребуется обращение к Kubernetes API с соответствующими правами (RBAC).

4. **Синтаксис fieldPath**: Записывается через точку (например, `metadata.name`), что соответствует JSONPath в Kubernetes API.

5. **Аннотация `kubernetes.io/config.last-applied`**: При монтировании аннотаций пода в файл попадает служебная аннотация, содержащая полный JSON манифеста пода. Это объясняет ограничение на размер данных в ConfigMap: если ConfigMap монтируется в под, его содержимое сохраняется в эту аннотацию, а размер поля аннотации в Kubernetes ограничен.
