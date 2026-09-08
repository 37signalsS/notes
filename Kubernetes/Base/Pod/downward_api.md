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
*   **Механизм обновления томов:** Изменения в `labels` и `annotations` отражаются в смонтированных файлах через механизм atomарных обновлений symlinks (аналогично ConfigMap). Kubelet периодически (по умолчанию каждые 60 секунд) проверяет изменения и обновляет ссылки. При этом процессы, уже открывшие файл, продолжают работать со старой версией до повторного открытия.

### Делители ресурсов (divisor)

При монтировании ресурсов контейнера через `resourceFieldRef` в том можно указать `divisor` для перевода значений в удобные единицы:

| Ресурс | `divisor` по умолчанию | Пример `divisor` | Результат |
| :--- | :--- | :--- | :--- |
| `limits.cpu` / `requests.cpu` | `1` (ядра) | `1m` | В милли-ядрах (например, `500m`) |
| `limits.memory` / `requests.memory` | `1` (байты) | `1Mi` | В мегабайтах (например, `256`) |
| `limits.ephemeral-storage` | `1` (байты) | `1Gi` | В гигабайтах |

**Пример с divisor:**
```yaml
resources:
  - name: cpu-limit
    resourceFieldRef:
      containerName: app
      resource: limits.cpu
      divisor: 1m  # Значение будет в милли-ядрах
```

В переменных окружения делители не поддерживаются — значения всегда в базовых единицах (cores для CPU, bytes для памяти).

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

### Пример 4: Sidecar для сбора логов с метаданными Pod

Типичный паттерн для DevOps/SRE: sidecar-контейнер собирает логи основного приложения и обогащает их метаданными Pod (имя, namespace, IP-адрес узла) для централизованного поиска и корреляции инцидентов.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-sidecar-logging
  labels:
    app: web-api
    tier: frontend
spec:
  containers:
    # Основной контейнер с приложением
    - name: app
      image: nginx:1.25
      volumeMounts:
        - name: shared-logs
          mountPath: /var/log/nginx
    # Sidecar для сбора и обогащения логов
    - name: log-collector
      image: busybox
      command: ["sh", "-c", "while true; do sleep 30; done"]
      env:
        - name: NODE_NAME
          valueFrom:
            fieldRef:
              fieldPath: spec.nodeName
        - name: POD_NAMESPACE
          valueFrom:
            fieldRef:
              fieldPath: metadata.namespace
        - name: POD_IP
          valueFrom:
            fieldRef:
              fieldPath: status.podIP
      volumeMounts:
        - name: shared-logs
          mountPath: /var/log/nginx
        - name: pod-metadata
          mountPath: /etc/podinfo
  volumes:
    - name: shared-logs
      emptyDir: {}
    - name: pod-metadata
      downwardAPI:
        items:
          - path: "labels"
            fieldRef:
              fieldPath: metadata.labels
          - path: "annotations"
            fieldRef:
              fieldPath: metadata.annotations
          - path: "node-name"
            fieldRef:
              fieldPath: spec.nodeName
```

**Проверка:**
```bash
# Убедиться, что файлы метаданных созданы
kubectl exec app-with-sidecar-logging -c log-agent -- ls /etc/podinfo/
# → labels
# → annotations
# → node-name

# Прочитать содержимое меток
kubectl exec app-with-sidecar-logging -c log-agent -- cat /etc/podinfo/labels
# → app="web-api"
# → tier="frontend"
```

### Пример 5: DaemonSet с обогащением логов на уровне узла

DaemonSet автоматически запускает контейнер-агент на каждом узле. Downward API предоставляет метаданные Pod и узла для маршрутизации логов в централизованное хранилище.

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-log-agent
  namespace: logging
spec:
  selector:
    matchLabels:
      app: log-agent
  template:
    metadata:
      labels:
        app: log-agent
    spec:
      serviceAccountName: log-agent-sa
      tolerations:
        - operator: Exists  # Запуск на всех узлах, включая control-plane
      containers:
        - name: agent
          image: fluentd:v1.16
          env:
            - name: NODE_NAME
              valueFrom:
                fieldRef:
                  fieldPath: spec.nodeName
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: POD_NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 256Mi
          volumeMounts:
            - name: varlog
              mountPath: /var/log
              readOnly: true
            - name: podinfo
              mountPath: /etc/podinfo
              readOnly: true
      volumes:
        - name: varlog
          hostPath:
            path: /var/log
        - name: podinfo
          downwardAPI:
            items:
              - path: "labels"
                fieldRef:
                  fieldPath: metadata.labels
              - path: "node-name"
                fieldRef:
                  fieldPath: spec.nodeName
```

**Проверка:**
```bash
# Проверить запуск на всех узлах
kubectl get pods -n logging -l app=log-agent -o wide

# Прочитать метаданные на конкретном Pod'е
kubectl exec <pod-name> -n logging -- cat /etc/podinfo/labels
# → app="log-agent"

kubectl exec <pod-name> -n logging -- cat /etc/podinfo/node-name
# → worker-01
```

### Пример 6: Использование Downward API в ConfigMap/Secret манифесте

Downward API можно использовать в косвенных конфигурациях, передавая метаданные Pod через переменные окружения в ConfigMap, а затем монтируя результат в контейнер. Это полезно, когда приложение не поддерживает прямое чтение файлов метаданных.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-env-config
data:
  # Значения подставляются из переменных окружения Pod
  APP_NAME: "my-service"
---
apiVersion: v1
kind: Pod
metadata:
  name: app-with-env-injection
spec:
  containers:
    - name: app
      image: my-app:latest
      envFrom:
        - configMapRef:
            name: app-env-config
      env:
        - name: MY_POD_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: MY_NODE_NAME
          valueFrom:
            fieldRef:
              fieldPath: spec.nodeName
```

### Пример 7: Чтение ресурсов контейнера с делителем

Приложение адаптирует потребление ресурсов в зависимости от выделенных лимитов (паттерн для высоконагруженных сервисов).

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: adaptive-app
spec:
  containers:
    - name: app
      image: my-app:latest
      resources:
        requests:
          cpu: "500m"
          memory: "256Mi"
        limits:
          cpu: "2"
          memory: "1Gi"
      env:
        # В милли-ядрах
        - name: CPU_LIMIT_MILLI
          valueFrom:
            resourceFieldRef:
              containerName: app
              resource: limits.cpu
              divisor: 1m
        # В мегабайтах
        - name: MEMORY_LIMIT_MB
          valueFrom:
            resourceFieldRef:
              containerName: app
              resource: limits.memory
              divisor: 1Mi
```

**Проверка:**
```bash
kubectl exec adaptive-app -- printenv | grep -E "CPU_LIMIT|MEMORY_LIMIT"
# → CPU_LIMIT_MILLI=2000
# → MEMORY_LIMIT_MB=1024
```

---

## Сравнение с альтернативами

| Критерий | Downward API (env) | Downward API (volume) | `envFrom` + ConfigMap | Projected Volume |
| :--- | :--- | :--- | :--- | :--- |
| **Динамическое обновление** | Нет | Да (labels, annotations) | Нет | Да |
| **Списки IP (podIPs, hostIPs)** | Да | Нет | Нет | Нет |
| **resourceFieldRef** | Да | Да | Нет | Да |
| **Конфигурация + секреты** | Нет | Нет | Да | Да |
| **Агрегация нескольких источников** | Нет | Нет | Нет | Да |
| **Зависимость от RBAC** | Нет | Нет | Нет | Да (для сервисного аккаунта) |

**Когда использовать Downward API:**
- Необходимы метаданные Pod (имя, namespace, IP, лимиты) без обращения к API-серверу.
- Требуется динамическое обновление меток/аннотаций без перезапуска контейнера.
- Приложение не поддерживает чтение файлов или клиентские библиотеки Kubernetes.

**Когда использовать альтернативы:**
- Для передачи конфигурационных данных — ConfigMap/Secret.
- Для агрегации нескольких источников — Projected Volume.
- Для динамического обновления конфигурации — ConfigMap/Secret через тома (с механизмом symlink).

---

## Диагностика и типичные ошибки

### Ошибка 1: `CreateContainerConfigError` при использовании Downward API

**Причина:** Kubelet не может разрешить значение поля на этапе создания контейнера. Типичные причины:
- Обращение к `status.podIP` на ранних стадиях, когда CNI ещё не назначил IP-адрес Pod.
- Некорректный синтаксис `fieldPath` (например, `metadata.labels` вместо `metadata.labels['key']`).
- Использование полей, доступных только в `env`, через `volume` (например, `status.podIPs`).

**Диагностика:**
```bash
# Проверить события Pod
kubectl describe pod <pod-name> | grep -A 5 "Events"

# Пример ошибки в Events:
# Warning  Failed  kubelet  Error: failed to create container config...
#   for field "status.podIP": not a valid field path

# Проверить статус Pod
kubectl get pod <pod-name> -o jsonpath='{.status.conditions}'
```

**Решение:**
1. Проверить синтаксис `fieldPath` — используйте точечную нотацию с квадратными скобками для меток: `metadata.labels['app']`.
2. Убедиться, что поле доступно в нужном способе получения (env/volume).
3. Для `status.podIP` дождаться назначения IP-адреса (событие `Assigned` в `kubectl describe pod`).

### Ошибка 2: Пустые значения в переменных окружения

**Причина:** Значение поля ещё не заполнено в момент запуска контейнера. Типичные поля: `metadata.annotations` (могут быть пустыми), `metadata.labels` (могут отсутствовать), `spec.nodeName` (ещё не назначен).

**Диагностика:**
```bash
# Проверить, что метки и аннотации существуют
kubectl get pod <pod-name> -o jsonpath='{.metadata.labels}'
kubectl get pod <pod-name> -o jsonpath='{.metadata.annotations}'

# Проверить переменные окружения в работающем Pod'е
kubectl exec <pod-name> -- env | grep MY_
```

**Решение:**
1. Убедиться, что нужные метки/аннотации заданы в манифесте Pod.
2. Для критичных значений использовать инициализацию через init-контейнеры или ConfigMap.

### Ошибка 3: Файлы метаданных не обновляются

**Причина:** Используется `subPath` при монтировании тома — это блокирует механизм обновления через symlinks.

**Диагностика:**
```bash
# Проверить, не используется ли subPath
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].volumeMounts[*].subPath}'

# Проверить, что symlinks обновляются
kubectl exec <pod-name> -- ls -la /etc/podinfo/
```

**Решение:** Не использовать `subPath` с томами Downward API, если необходимо динамическое обновление.

### Ошибка 4: `kubectl.kubernetes.io/last-applied-configuration` в аннотациях

**Причина:** При монтировании всех аннотаций (`metadata.annotations`) в файл также попадает служебная аннотация `kubectl.kubernetes.io/last-applied-configuration`, содержащая полный JSON последнего примененного манифеста. Это может значительно увеличить размер монтируемых данных.

**Диагностика:**
```bash
# Проверить размер файла аннотаций
kubectl exec <pod-name> -- wc -c /etc/podinfo/annotations

# Проверить содержимое
kubectl exec <pod-name> -- cat /etc/podinfo/annotations
```

**Решение:** Монтировать только конкретные аннотации вместо всех:
```yaml
volumes:
  - name: podinfo
    downwardAPI:
      items:
        - path: "my-annotation"
          fieldRef:
            fieldPath: metadata.annotations['my-annotation']
```

---

## Лучшие практики для DevOps/SRE

### 1. Логирование и мониторинг

- Используйте Downward API для обогащения логов метаданными Pod: имя_pod, namespace, имя_узла, IP-адрес. Это упрощает поиск и корреляцию инцидентов в стеках ELK/Loki/Prometheus.
- Для централизованного сбора логов с обогащением метаданными используйте DaemonSet с Downward API.

### 2. Безопасность

- Не передавайте конфиденциальные данные через Downward API — для этого используйте Secret или Projected Volumes с токенами ServiceAccount.
- Монтируйте тома с метаданными в режиме `readOnly: true`.
- Избегайте передачи всех аннотаций (`metadata.annotations`) в том — это может раскрыть служебную информацию.

### 3. Производительность

- Избегайте частого чтения файлов Downward API — обновления происходят с задержкой (до 60 секунд).
- Для критичных данных, требующих мгновенного обновления, используйте переменные окружения (но тогда данные не обновляются без перезапуска).

### 4. Совместимость с Projected Volumes

- Агрегируйте Downward API с другими источниками (ConfigMap, Secret, ServiceAccountToken) через Projected Volumes для упрощения манифестов и управления томами.
- Для получения токенов ServiceAccount используйте `projected` тома с `serviceAccountToken` вместо секретов ServiceAccount.

---

## Дополнительная информация

**Связанные темы:**

- [Тома в Kubernetes](./volume_types/volume_types.md) — обзор всех типов томов.
- [Projected Volumes](./volume_types/projected_volumes.md) — детали агрегации источников данных.
- [ConfigMap в Kubernetes](../configmap.md) — управление конфигурациями.
- [Управление ресурсами: Requests, Limits и QoS](../../Scheduling/qos_limit_and_requests.md) — подробнее о CPU/Memory requests и limits.
- [DaemonSet в Kubernetes](../daemonset.md) — паттерны использования на уровне узла.
- [Troubleshooting: CreateContainerConfigError](../../Troubleshooting/Common_Errors/CreateContainerConfigError/definitions.md) — типичные ошибки при создании контейнера.
