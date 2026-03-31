# Downward API в Kubernetes

## Определения

**Downward API** — механизм Kubernetes, позволяющий приложениям в контейнерах получать метаданные пода без обращения к Kubernetes API. Упрощает архитектуру и устраняет необходимость в RBAC для получения базовых метаданных.

---

## Базовые концепции

### Доступные параметры

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

### Способы получения данных

Downward API предоставляет два способа доступа к метаданным:

1. **Переменные окружения** (`env.valueFrom`) — значения доступны при старте контейнера
2. **Тома** (`volumes.downwardAPI`) — данные доступны через файловую систему

### Особенности реализации

**Container vs Pod level:** Для `resourceFieldRef` (ресурсы контейнера) необходимо указывать `containerName`, так как в поде может быть несколько контейнеров.

**Динамические обновления:** При использовании томов изменения в метках и аннотациях пода отражаются в файловой системе автоматически. При использовании переменных окружения — только при перезапуске пода. Реализация использует symlinks (аналогично ConfigMap): файл в `/etc/podinfo/labels` ссылается на файл в директории `..data`.

**Синтаксис fieldPath:** Записывается через точку (например, `metadata.name`), что соответствует JSONPath в Kubernetes API.

**Ограничения:** Через Downward API нельзя получить полный манифест пода или информацию о других ресурсах. Для этого потребуется обращение к Kubernetes API с соответствующими правами (RBAC).

**Аннотация `kubernetes.io/config.last-applied`:** При монтировании аннотаций пода в файл попадает служебная аннотация, содержащая полный JSON манифеста пода. Это объясняет ограничение на размер данных в ConfigMap: если ConfigMap монтируется в под, его содержимое сохраняется в эту аннотацию, а размер поля аннотации в Kubernetes ограничен.

---

## Практические сценарии

### Пример 1: Переменные окружения

Использование Downward API через переменные окружения для передачи метаданных в контейнер:

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

### Пример 2: Том для доступа через файловую систему

Монтирование Downward API как тома для доступа к метаданным через файловую систему:

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

### Пример 3: Комбинирование с Projected Volume

Downward API может использоваться в составе [Projected Volume](./volume_types/projected_volumes.md) для объединения с другими источниками данных (Secret, ConfigMap, ServiceAccountToken) в одной точке монтирования.

---

## Дополнительная информация

**Связанные темы:** [Базовые концепции Volume](./volume_types/volumes_basics.md), [Projected Volumes](./volume_types/projected_volumes.md), [ConfigMap](../../ConfigMap/configmap.md).
