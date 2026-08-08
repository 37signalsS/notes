# Downward API в Kubernetes

## Определения

**Downward API** — механизм Kubernetes, позволяющий контейнерам получать метаданные о самих себе и о Pod, в котором они запущены, без прямого обращения к API-серверу Kubernetes. Это устраняет необходимость в предоставлении подам прав RBAC для чтения собственной конфигурации и упрощает архитектуру приложений.

---

## Базовые концепции

### Доступные параметры

Параметры Downward API делятся на две категории в зависимости от источника: поля объекта Pod (`fieldRef`) и поля ресурсов контейнера (`resourceFieldRef`).

#### Поля Pod (fieldRef)

| Параметр | Описание | Доступность (v1.30+) |
| :--- | :--- | :---: |
| `metadata.name` | Имя Pod | env, volume |
| `metadata.namespace` | Пространство имен (Namespace) | env, volume |
| `metadata.uid` | Уникальный идентификатор (UID) | env, volume |
| `metadata.labels['<KEY>']` | Значение конкретной метки (Label) | env, volume |
| `metadata.annotations['<KEY>']` | Значение конкретной аннотации | env, volume |
| `spec.nodeName` | Имя узла (Node), на котором запущен Pod | env, volume |
| `spec.serviceAccountName` | Имя используемого ServiceAccount | env, volume |
| `status.podIP` | Основной IP-адрес Pod | env, volume |
| `status.podIPs` | Список всех IP-адресов Pod (Dual-stack IPv4/IPv6) | **только env** |
| `status.hostIP` | Основной IP-адрес узла | env, volume |
| `status.hostIPs` | Список всех IP-адресов узла | **только env** |

#### Поля ресурсов контейнера (resourceFieldRef)

Для этих полей необходимо указывать `containerName`, если данных несколько.

| Параметр | Описание |
| :--- | :--- |
| `limits.cpu` | Лимит CPU |
| `requests.cpu` | Запрос CPU |
| `limits.memory` | Лимит памяти |
| `requests.memory` | Запрос памяти |
| `limits.ephemeral-storage` | Лимит временного хранилища |
| `requests.ephemeral-storage` | Запрос временного хранилища |

### Способы получения данных

1.  **Переменные окружения** (`env.valueFrom`):
    *   Значения устанавливаются в момент запуска контейнера.
    *   **Ограничение:** Не обновляются динамически при изменении меток или аннотаций Pod (требуется перезапуск).
    *   **Преимущество:** Единственный способ получить списки IP (`podIPs`, `hostIPs`).

2.  **Тома** (`volumes.downwardAPI`):
    *   Метаданные монтируются как файлы в файловую систему контейнера.
    *   **Особенность:** Изменения в `labels` и `annotations` отражаются в файлах автоматически без перезапуска контейнера (через механизм symlinks, аналогично ConfigMap).
    *   **Ограничение:** Не поддерживает списки IP-адресов.

### Особенности реализации

*   **Синтаксис fieldPath:** Используется точечная нотация (например, `metadata.labels['app']`), соответствующая путям в JSON-манифесте Kubernetes.
*   **Единицы измерения ресурсов:** При получении ресурсов через тома можно использовать параметр `divisor` для приведения значений к нужным единицам (например, `1m` для CPU или `1Mi` для памяти). В переменных окружения значения передаются в базовых единицах (bytes, cores).
*   **Динамическое масштабирование (v1.31+):** При использовании In-place Pod Vertical Scaling изменения в `resourceFieldRef` корректно отражаются в Downward API, позволяя приложению адаптироваться к новым лимитам без рестарта.
*   **Аннотация `last-applied-configuration`:** При монтировании всех аннотаций (`metadata.annotations`) в файл попадает и служебная аннотация `kubectl.kubernetes.io/last-applied-configuration`, содержащая полный JSON последнего примененного манифеста. Это может значительно увеличить размер монтируемых данных.
*   **Ограничения:** Downward API не позволяет получить информацию о других объектах кластера или полный манифест Pod (кроме хака с `last-applied-configuration`). Для более сложных задач требуется полноценный доступ к API через клиентские библиотеки.

---

## Практические сценарии

### Пример 1: Использование переменных окружения

Передача метаданных и лимитов для логирования и самоидентификации приложения:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: downward-api-env
spec:
  containers:
    - name: app-container
      image: busybox
      command: ["sh", "-c", "env | grep MY_"]
      env:
        - name: MY_POD_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: MY_POD_IPS
          valueFrom:
            fieldRef:
              fieldPath: status.podIPs
        - name: MY_CPU_LIMIT
          valueFrom:
            resourceFieldRef:
              containerName: app-container
              resource: limits.cpu
```

### Пример 2: Монтирование меток и аннотаций через том

Сценарий, где приложение (например, sidecar для сбора метрик) должно реагировать на изменение меток Pod в реальном времени:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: downward-api-vol
  labels:
    version: "v1"
    team: "devops"
spec:
  containers:
    - name: agent
      image: busybox
      command: ["sh", "-c", "watch cat /etc/podinfo/labels"]
      volumeMounts:
        - name: podinfo
          mountPath: /etc/podinfo
  volumes:
    - name: podinfo
      downwardAPI:
        items:
          - path: "labels"
            fieldRef:
              fieldPath: metadata.labels
          - path: "annotations"
            fieldRef:
              fieldPath: metadata.annotations
```

### Пример 3: Совмещение с Projected Volumes

Агрегация Downward API с токенами и конфигурациями в одну директорию:

```yaml
volumes:
  - name: all-in-one
    projected:
      sources:
        - downwardAPI:
            items:
              - path: "pod-name"
                fieldRef:
                  fieldPath: metadata.name
        - configMap:
            name: app-config
        - secret:
            name: app-secret
```

---

## Дополнительная информация

**Связанные темы:**

- [Тома в Kubernetes](./volume_types/volume_types.md) — обзор всех типов томов.
- [Projected Volumes](./volume_types/projected_volumes.md) — детали агрегации источников данных.
- [ConfigMap в Kubernetes](../configmap.md) — управление конфигурациями.
- [Инъекция ресурсов в контейнеры](../../Scheduling/qos_limit_and_requests.md) — подробнее о CPU/Memory requests и limits.
