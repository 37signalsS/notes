# Downward API в Kubernetes

## Определения

**Downward API** — механизм Kubernetes, позволяющий приложениям в container получать метаданные Pod без обращения к Kubernetes API. Это упрощает архитектуру и устраняет необходимость в RBAC для получения базовых метаданных.

---

## Базовые концепции

### Доступные параметры

| Параметр | Описание |
| :--- | :--- |
| `metadata.name` | Имя Pod |
| `metadata.namespace` | Namespace |
| `metadata.uid` | UID |
| `metadata.annotations['<KEY>']` | Значение конкретной аннотации |
| `metadata.labels['<KEY>']` | Значение конкретной метки |
| `spec.nodeName` | Имя Node, на которой работает Pod |
| `spec.serviceAccountName` | Имя ServiceAccount |
| `status.podIP` | IP адрес Pod |
| `status.hostIP` | IP-адрес Node |
| `resources.limits['cpu']` | Лимит CPU |
| `resources.limits['memory']` | Лимит памяти |
| `resources.requests['cpu']` | Запрос CPU |
| `resources.requests['memory']` | Запрос памяти |

### Способы получения данных

Downward API предоставляет два способа доступа к метаданным:

1. **Переменные окружения** (`env.valueFrom`) — значения доступны при старте container.
2. **Тома** (`volumes.downwardAPI`) — данные доступны через файловую систему.

### Особенности реализации

**Container vs Pod level:** Для `resourceFieldRef` (ресурсы container) необходимо указывать `containerName`, так как в Pod может быть несколько container.

**Динамические обновления:** При использовании томов изменения в метках и аннотациях Pod отражаются в файловой системе автоматически. При использовании переменных окружения — только при перезапуске Pod. Реализация использует символические ссылки (symlinks) (аналогично ConfigMap): файл в `/etc/podinfo/labels` ссылается на файл в директории `..data`.

**Синтаксис fieldPath:** Записывается через точку (например, `metadata.name`), что соответствует JSONPath в Kubernetes API.

**Динамическая адаптация:** Предоставляя метаданные через Downward API, поды могут динамически настраивать свое поведение в зависимости от окружения (имя пода, namespace, лимиты) без ручного вмешательства. Это повышает гибкость и автоматизацию управления приложениями.

**Ограничения:** Через Downward API нельзя получить полный манифест Pod или информацию о других ресурсах. Для этого потребуется обращение к Kubernetes API с соответствующими правами (RBAC).

**Аннотация `kubernetes.io/config.last-applied`:** При монтировании аннотаций Pod в файл попадает служебная аннотация, содержащая полный JSON манифеста. Это объясняет ограничение на размер данных в ConfigMap: если ConfigMap монтируется в Pod, его содержимое сохраняется в эту аннотацию, а размер поля аннотации в Kubernetes ограничен.

---

## Практические сценарии

### Пример 1: Переменные окружения

Использование Downward API через переменные окружения для передачи метаданных в container:

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

**Связанные темы:**

- [Тома в Kubernetes](./volume_types/volume_types.md)
- [Projected Volumes](./volume_types/projected_volumes.md)
- [ConfigMap в Kubernetes](../configmap.md)
