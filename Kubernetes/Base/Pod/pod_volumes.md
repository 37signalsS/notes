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
  - image: registry.k8s.io/test-webserver
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
  * **Что это:** Пустой каталог, который создается вместе с подом на узле и существует, пока под работает на этом узле. Все контейнеры в поде могут читать и записывать данные в этот том.
  * **Жизненный цикл:** Данные в `emptyDir` **сохраняются** при перезапуске или падении контейнера, но **полностью удаляются** при удалении самого пода (например, при выкатке новой версии `Deployment` или при перемещении пода на другой узел).
  * **Источник:** По умолчанию `emptyDir` создается на диске узла (в директории `/var/lib/kubelet/pods/...`). Также можно использовать оперативную память.
  * **Использование:**
    1.  **Временное хранилище (кэш):** Для данных, которые не страшно потерять.
    2.  **Обмен данными между контейнерами:** Основной способ для обмена файлами между несколькими контейнерами в одном поде (например, по паттерну "сайдкар").
    3.  **Инициализация данных:** `initContainer` может подготовить данные или скрипты в `emptyDir` перед запуском основных контейнеров.
  * **Параметры:**
    *   `medium: Memory` — предписывает Kubernetes создать `emptyDir` в оперативной памяти узла, используя `tmpfs`. Это значительно ускоряет файловые операции. **Важно:** потребляемая в `tmpfs` память учитывается в лимитах памяти (`resources.limits.memory`) контейнера. Без установленных лимитов использование `medium: Memory` опасно, так как может привести к `OOMKill` пода или всего узла.
    *   `sizeLimit` — ограничение размера тома (например, `1Gi`). При превышении лимита под будет принудительно выселен (`evicted`) с узла.
  * **Важно:** Не используйте `emptyDir` для хранения персистентных данных, таких как базы данных. Это эфемерное хранилище.

* **`hostPath`**:
  * **Что это:** Монтирует файл или директорию с файловой системы хостовой машины (Node) внутрь пода. В отличие от `emptyDir`, где путь на хосте неизвестен, `hostPath` позволяет указать точный путь.
  * **Типы (`type`):** Поле `type` в определении `hostPath` контролирует его поведение:
      * **`type: Directory`**: Указанный путь должен существовать и быть директорией. Если его нет, под не запустится.
      * **`type: DirectoryOrCreate`**: Если директория по указанному пути не существует, `kubelet` создаст ее с правами `0755` и владельцем `root`.
      * **Другие типы:** `File`, `FileOrCreate`, `Socket`, `CharDevice`, `BlockDevice`.
  * **Проблема с правами доступа:** При использовании `DirectoryOrCreate` созданная директория принадлежит `root`. Если контейнер в поде запускается от имени непривилегированного пользователя (например, с `securityContext: { runAsUser: 1000 }`), он не сможет записывать данные в эту директорию.
  * **Решение:** Для записи в `hostPath` из-под непривилегированного пользователя необходимо **заранее** создать директорию на целевом узле и выставить на нее правильные права (`chown`). Чтобы под гарантированно попал на этот подготовленный узел, следует использовать `nodeAffinity`.
  * **Основное применение:** Предоставление подам доступа к системным ресурсам узла. Чаще всего используется в `DaemonSet`-ах для агентов мониторинга (node-exporter), сборщиков логов (fluent-bit) или плагинов CNI. В таких случаях том часто монтируется в режиме "только для чтения" (`readOnly: true`).
  * **Пример: Сборщик логов:**
    ```yaml
    # ... в манифесте DaemonSet ...
    spec:
      template:
        spec:
          containers:
          - name: log-collector
            image: fluent/fluent-bit
            volumeMounts:
            - name: varlog
              mountPath: /var/log
              readOnly: true # Монтируем только для чтения
          volumes:
          - name: varlog
            hostPath:
              path: /var/log
              type: Directory # /var/log всегда существует
    ```
  * **ВНИМАНИЕ: УГРОЗА БЕЗОПАСНОСТИ.** Использование `hostPath` является **опасной практикой** для обычных приложений. Это нарушает изоляцию контейнера, предоставляет ему доступ к файловой системе хоста и может привести к компрометации всего узла. В кластерах с настроенными политиками безопасности (PSA, OPA) использование `hostPath` обычно запрещено для большинства рабочих нагрузок.

* **`configMap` и `secret`**:
  * **Что это:** Позволяют "пробросить" данные из [ConfigMap](../configmap.md) или [Secret](../secrets/secrets_basics.md) в под в виде файлов.
  * **Использование:** Основной способ передачи конфигурационных файлов, TLS-сертификатов и других данных в приложение.

* **`projected`**:
  * **Что это:** Позволяет объединить несколько источников (`secret`, `configMap`, `downwardAPI`) в один том, который монтируется как единая директория.
  * **Использование:** Удобно для сбора различных типов конфигурационных данных и метаданных в одном месте, доступном для приложения.

* **`persistentVolumeClaim`**:
  * **Что это:** Способ смонтировать постоянное (persistent) хранилище, жизненный цикл которого не зависит от пода.
  * **Использование:** Это стандартный и правильный способ для хранения данных приложений, которые должны сохраняться (базы данных, пользовательские файлы и т.д.). Подробнее см. в [PV, PVC и StorageClass](../../Storage/pv_and_pvc.md).

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

#### Практический пример: Projected Volume

Этот пример показывает, как объединить данные из `Secret`, `ConfigMap` и `DownwardAPI` в одну директорию `/projected-volume`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: projected-volume-pod
spec:
  volumes:
  - name: all-in-one
    projected:
      sources:
      - secret:
          name: user-password-secret # Предполагается, что этот Secret существует
          items:
            - key: username
              path: app-credentials/user.txt
      - configMap:
          name: app-config # Предполагается, что этот ConfigMap существует
          items:
            - key: config.yaml
              path: app-config/settings.yaml
      - downwardAPI:
          items:
            - path: "pod-labels"
              fieldRef:
                fieldPath: metadata.labels
            - path: "container-cpu-limit"
              resourceFieldRef:
                containerName: test-container
                resource: limits.cpu
  containers:
  - name: test-container
    image: busybox
    command: ["sh", "-c", "sleep 3600"]
    volumeMounts:
    - name: all-in-one
      mountPath: "/projected-volume"
      readOnly: true
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
