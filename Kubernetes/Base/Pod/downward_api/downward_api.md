# Downward API в Kubernetes

## Определения

**Downward API** — это механизм Kubernetes, который позволяет приложениям в контейнерах получать информацию о себе (метаданных пода) без обращения к Kubernetes API. Это упрощает архитектуру приложений и устраняет необходимость в RBAC для получения базовых метаданных.

## Что можно получить через Downward API

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

---

## Получение через переменные окружения

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

---

## Получение через тома

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

---

## Важные особенности

1. **Container vs Pod level**: Для `resourceFieldRef` (ресурсы контейнера) необходимо указывать `containerName`, так как в поде может быть несколько контейнеров.

2. **Динамические метки и аннотации**: При использовании томов изменения в метках или аннотациях пода отражаются в файловой системе. При использовании переменных окружения — только при перезапуске пода. Реализация использует symlinks (аналогично ConfigMap): файл в `/etc/podinfo/labels` ссылается на файл в директории `..data`.

3. **Ограничения**: Через Downward API нельзя получить полный манифест пода или информацию о других ресурсах. Для этого потребуется обращение к Kubernetes API с соответствующими правами (RBAC).

4. **Синтаксис fieldPath**: Записывается через точку (например, `metadata.name`), что соответствует JSONPath в Kubernetes API.

5. **Аннотация `kubernetes.io/config.last-applied`**: При монтировании аннотаций пода в файл попадает служебная аннотация, содержащая полный JSON манифеста пода. Это объясняет ограничение на размер данных в ConfigMap: если ConfigMap монтируется в под, его содержимое сохраняется в эту аннотацию, а размер поля аннотации в Kubernetes ограничен.

## Дополнительные ссылки

- [Базовые концепции Volume](../volume_types/volumes_basics.md)
- [Projected Volumes](../volume_types/projected_volumes.md)
