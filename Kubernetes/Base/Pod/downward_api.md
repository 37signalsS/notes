# Downward API в Kubernetes

**Актуально для:** Kubernetes 1.30–1.35

## Определения

* **Downward API** — встроенный механизм Kubernetes, позволяющий контейнерам получать метаданные о самих себе, о Pod и об исполняющем узле без прямого обращения к API-серверу Kubernetes и без предоставления сервисному аккаунту прав RBAC.
* **`fieldRef` (`ObjectFieldSelector`)** — селектор поля манифеста Pod (имя, namespace, UID, метки, аннотации, IP-адреса, имя узла).
* **`resourceFieldRef` (`ResourceFieldSelector`)** — селектор вычислительных ресурсов контейнера (requests и limits для CPU, памяти, временного хранилища и Hugepages).
* **`divisor`** — коэффициент масштабирования численных ресурсов в `resourceFieldRef` (например, `1m` для милли-ядер CPU или `1Mi` для мегабайт), приводящий сырые значения к целому числу с округлением вверх.
* **In-Place Pod Vertical Scaling** — механизм изменения лимитов и запросов CPU/памяти контейнера без перезапуска Pod. Тома Downward API отражают эти изменения динамически, в то время как переменные окружения остаются статичными.
* **Атомарное обновление symlink (`..data`)** — паттерн монтирования томов ConfigMap, Secret и Downward API Kubelet'ом, при котором файлы монтируются через символические ссылки на версионированные подкаталоги с последующим атомарным переключением ссылки `..data`.

---

## Базовые концепции и архитектура

### Принцип работы

Downward API устраняет жесткую связность (coupling) между приложением и API-сервером Kubernetes. Вместо выполнения сетевых вызовов `GET /api/v1/namespaces/{ns}/pods/{name}` (требующих ServiceAccount, роли RBAC, сетевой доступности kube-apiserver и логики обработки сетевых сбоев) Kubelet самостоятельно извлекает метаданные из локального состояния Pod и передает их в контейнер одним из двух способов:
1. **Переменные окружения (`env.valueFrom`)**: инжектируются в процесс контейнера при старте.
2. **Файлы тома (`volumes.downwardAPI`)**: монтируются в файловую систему контейнера и поддерживают динамическое обновление.

```
+-----------------------------------------------------------------------------------+
| Kubelet (Node Worker)                                                             |
|                                                                                   |
|  1. Разрешает метаданные Pod локально (без запросов контейнера в API-server)      |
|  2. Инжектирует env vars при создании контейнера (CRI)                             |
|  3. Создает tmpfs том downwardAPI с атомарной symlink-структурой                  |
+-----------------------------------------------------------------------------------+
         |                                           |
         v (при запуске)                             v (периодический sync)
+-----------------------+                   +---------------------------------------+
| Переменные окружения  |                   | Том Downward API (/etc/podinfo)       |
| POD_NAME, POD_IP, ... |                   | ..2026_10_17_... (директория)         |
| (Статичны до рестарта)|                   | ..data -> ..2026_10_17_... (symlink)  |
|                       |                   | labels -> ..data/labels               |
+-----------------------+                   +---------------------------------------+
```

### Матрица доступности полей (`fieldRef`)

Не все поля доступны одинаково через переменные окружения и тома. Нарушение правил совместимости приводит к фатальной ошибке `CreateContainerConfigError`.

| Поле `fieldPath` | Описание | `env` | `volume` | Примечание |
| :--- | :--- | :---: | :---: | :--- |
| `metadata.name` | Имя Pod | Да | Да | Имя пода, сгенерированное контроллером |
| `metadata.namespace` | Пространство имен | Да | Да | Namespace, в котором запущен Pod |
| `metadata.uid` | Уникальный ID (UID) | Да | Да | UUID объекта в etcd |
| `metadata.labels['<KEY>']` | Значение конкретной метки | Да | Да | Регистрозависимый ключ метки |
| `metadata.annotations['<KEY>']` | Значение конкретной аннотации | Да | Да | Регистрозависимый ключ аннотации |
| `metadata.labels` | **Все** метки Pod списком | **Нет** | **Да** | Формат: `key="value"` (построчно) |
| `metadata.annotations` | **Все** аннотации Pod списком | **Нет** | **Да** | Формат: `key="value"` (построчно) |
| `spec.nodeName` | Имя рабочего узла | **Да** | **Нет** | Назначается после фазы Scheduling |
| `spec.serviceAccountName` | Имя ServiceAccount | **Да** | **Нет** | Имя сервисного аккаунта Pod |
| `status.hostIP` | Основной IPv4/IPv6 узла | **Да** | **Нет** | IP-адрес сетевого интерфейса ноды |
| `status.hostIPs` | Список IP узла (Dual-Stack) | **Да** | **Нет** | Список через запятую (v1.28+) |
| `status.podIP` | Основной IP-адрес Pod | **Да** | **Нет** | Назначается CNI плагином |
| `status.podIPs` | Список IP Pod (Dual-Stack) | **Да** | **Нет** | Список через запятую (v1.28+) |

> [!WARNING]
> Поля `spec.nodeName`, `spec.serviceAccountName`, `status.hostIP`, `status.hostIPs`, `status.podIP` и `status.podIPs` **не поддерживаются** в спецификации томов `downwardAPI.items[*].fieldRef`. Попытка указать их в томе вызовет сбой запуска контейнера с ошибкой `CreateContainerConfigError`.

### Ресурсы контейнера (`resourceFieldRef`)

Через `resourceFieldRef` контейнер может узнать свои собственные ограничения или ограничения соседних контейнеров внутри одного Pod.

| Ресурс | Описание | Обязательность `containerName` |
| :--- | :--- | :--- |
| `limits.cpu` | Верхний лимит CPU | В `volume` — **обязательно**. В `env` — опционально (по умолчанию текущий контейнер). |
| `requests.cpu` | Гарантированный запрос CPU | В `volume` — **обязательно**. В `env` — опционально. |
| `limits.memory` | Верхний лимит оперативной памяти | В `volume` — **обязательно**. В `env` — опционально. |
| `requests.memory` | Гарантированный запрос оперативной памяти | В `volume` — **обязательно**. В `env` — опционально. |
| `limits.ephemeral-storage` | Лимит временного дискового пространства | В `volume` — **обязательно**. В `env` — опционально. |
| `requests.ephemeral-storage`| Запрос временного дискового пространства | В `volume` — **обязательно**. В `env` — опционально. |
| `limits.hugepages-<size>` | Лимит Hugepages заданного размера (напр. `hugepages-2Mi`) | В `volume` — **обязательно**. В `env` — опционально. |
| `requests.hugepages-<size>`| Запрос Hugepages заданного размера | В `volume` — **обязательно**. В `env` — опционально. |

### Механизм масштабирования (divisor)

По умолчанию значения ресурсов передаются в неделимых базовых величинах: ядра для CPU (в формате float/integer) и байты для памяти. Параметр `divisor` масштабирует значение и округляет его **вверх до ближайшего целого числа** (ceil):

$$\text{Итоговое целое} = \left\lceil \frac{\text{Значение ресурса}}{\text{divisor}} \right\rceil$$

`divisor` поддерживается как в `volume`, так и в `env.valueFrom.resourceFieldRef`:

| Целевой ресурс | Пример `divisor` | Исходный лимит | Расчет | Результат в env / файле |
| :--- | :--- | :--- | :--- | :--- |
| `limits.cpu` | `1m` (милли-ядра) | `250m` | $250\text{m} / 1\text{m}$ | `250` |
| `limits.cpu` | `1` (целые ядра) | `2500m` | $\lceil 2.5 \rceil$ | `3` |
| `limits.memory`| `1Mi` (мебибайты) | `512Mi` | $536870912 / 1048576$ | `512` |
| `limits.memory`| `1Gi` (гибибайты) | `1500Mi` | $\lceil 1.464 \rceil$ | `2` |

### Резервное значение (Node Allocatable Fallback)

Если в спецификации контейнера **не указаны** лимиты или запросы (`limits` / `requests`), при обращении к ним через Downward API Kubelet не возвращает ошибку, а подставляет максимальное доступное значение ресурса на узле (**Node Allocatable**).
* Если для контейнера не задан `limits.cpu`, Downward API вернет полное количество Allocatable CPU узла.
* Если для контейнера не задан `limits.memory`, Downward API вернет полный объем Allocatable RAM узла.
Это позволяет приложениям (например, сборщикам мусора JVM) безопасно рассчитывать размеры пулов без падения при ненастроенных лимитах.

### Внутреннее устройство томов и динамическое обновление

1. **Atomic Symlink Swap**:
   Kubelet создает в точке монтирования специальную файловую структуру:
   ```text
   /etc/podinfo/
   ├── ..2026_10_17_13_30_00.123456789/  <- Реальная директория с данными
   │   ├── labels
   │   └── annotations
   ├── ..data -> ..2026_10_17_13_30_00.123456789  <- Символическая ссылка
   ├── labels -> ..data/labels                    <- Пользовательская ссылка
   └── annotations -> ..data/annotations          <- Пользовательская ссылка
   ```
   При изменении меток Kubelet записывает новую директорию `..2026_10_17_13_31_00...` и меняет symlink `..data` атомарным системным вызовом `rename()`. Это гарантирует отсутствие состояния "частично записанного файла".

2. **Периодичность синхронизации**:
   Kubelet обновляет тома в своем цикле управления (`syncLoopFrequency`, по умолчанию раз в несколько секунд, максимальная задержка обновления кэша Kubelet составляет до 1 минуты).

3. **In-Place Pod Vertical Scaling (Kubernetes 1.27+, GA в 1.35)**:
   При динамическом изменении `limits.cpu` или `limits.memory` работающего контейнера:
   * Файлы в томе `downwardAPI` обновляются Kubelet'ом автоматически.
   * Переменные окружения контейнера **не изменяются** (окружение процесса в Linux фиксируется при системном вызове `execve`).

4. **Файловые дескрипторы Linux**:
   Если процесс открыл файл `/etc/podinfo/labels` и удерживает открытый файловый дескриптор, он продолжит читать старый inode даже после смены symlink `..data`. Для получения свежих данных процесс обязан либо периодически выполнять `open()` заново, либо слушать события `inotify` (`IN_MOVED_TO` / `IN_CREATE`) на родительской директории.

---

## Практические сценарии и конфигурация

### Сценарий 1: Самоидентификация приложения и обогащение логов/трассировок (env)

Передача сетевых реквизитов и топологии в сервис для простановки тегов в distributed tracing (OpenTelemetry) и структурированных логах.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: telemetry-demo
  namespace: backend
  labels:
    app: order-processor
    tier: api
spec:
  serviceAccountName: order-sa
  containers:
    - name: app
      image: alpine:3.20
      command: ["sh", "-c", "env | grep APP_ && sleep 3600"]
      env:
        - name: APP_POD_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: APP_POD_NAMESPACE
          valueFrom:
            fieldRef:
              fieldPath: metadata.namespace
        - name: APP_POD_UID
          valueFrom:
            fieldRef:
              fieldPath: metadata.uid
        - name: APP_NODE_NAME
          valueFrom:
            fieldRef:
              fieldPath: spec.nodeName
        - name: APP_HOST_IP
          valueFrom:
            fieldRef:
              fieldPath: status.hostIP
        - name: APP_POD_IP
          valueFrom:
            fieldRef:
              fieldPath: status.podIP
        - name: APP_SERVICE_ACCOUNT
          valueFrom:
            fieldRef:
              fieldPath: spec.serviceAccountName
        - name: APP_LABEL_TIER
          valueFrom:
            fieldRef:
              fieldPath: metadata.labels['tier']
```

**Проверка смонтированных переменных:**
```bash
kubectl exec telemetry-demo -n backend -- env | grep APP_
# → APP_POD_NAME=telemetry-demo
# → APP_POD_NAMESPACE=backend
# → APP_POD_UID=8a9b3c4d-1234-5678-90ab-cdef12345678
# → APP_NODE_NAME=k8s-worker-02
# → APP_HOST_IP=192.168.10.22
# → APP_POD_IP=10.244.2.45
# → APP_SERVICE_ACCOUNT=order-sa
# → APP_LABEL_TIER=api
```

---

### Сценарий 2: Адаптация рантайма к ресурсам контейнера (JVM / Go / Worker Pools)

Автоматический расчет параметров многопоточности и пулов памяти без жесткого хардкода в манифестах с помощью `resourceFieldRef` и `divisor`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: adaptive-runtime
  namespace: production
spec:
  containers:
    - name: worker
      image: alpine:3.20
      resources:
        requests:
          cpu: "500m"
          memory: "512Mi"
        limits:
          cpu: "4"
          memory: "2Gi"
      env:
        # Лимит CPU в целых ядрах (для thread pool или GOMAXPROCS)
        - name: WORKER_CPU_CORES
          valueFrom:
            resourceFieldRef:
              containerName: worker
              resource: limits.cpu
              divisor: "1"
        # Лимит памяти в мегабайтах (для расчета heap cache)
        - name: WORKER_MAX_MEMORY_MB
          valueFrom:
            resourceFieldRef:
              containerName: worker
              resource: limits.memory
              divisor: "1Mi"
        # Запрос памяти в мегабайтах
        - name: WORKER_REQ_MEMORY_MB
          valueFrom:
            resourceFieldRef:
              containerName: worker
              resource: requests.memory
              divisor: "1Mi"
      command:
        - sh
        - -c
        - |
          echo "Starting worker with ${WORKER_CPU_CORES} cores and max ${WORKER_MAX_MEMORY_MB} MB RAM..."
          sleep 3600
```

**Проверка значений:**
```bash
kubectl exec adaptive-runtime -n production -- env | grep WORKER_
# → WORKER_CPU_CORES=4
# → WORKER_MAX_MEMORY_MB=2048
# → WORKER_REQ_MEMORY_MB=512
```

---

### Сценарий 3: Динамическое обновление конфигурации через том Downward API

Sidecar-агент отслеживает смену меток и аннотаций Pod без необходимости перезапуска контейнеров и без прав RBAC на чтение Pod.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: dynamic-meta-pod
  namespace: monitoring
  labels:
    environment: staging
    log-level: debug
  annotations:
    ops.alert/channel: "slack-sre"
spec:
  containers:
    - name: watcher
      image: alpine:3.20
      command:
        - sh
        - -c
        - |
          echo "=== Initial labels ==="
          cat /etc/podinfo/labels
          echo "=== Watch directory ==="
          while true; do
            sleep 10
          done
      volumeMounts:
        - name: podinfo-volume
          mountPath: /etc/podinfo
          readOnly: true
  volumes:
    - name: podinfo-volume
      downwardAPI:
        defaultMode: 0444
        items:
          - path: "labels"
            fieldRef:
              fieldPath: metadata.labels
          - path: "alert-channel"
            fieldRef:
              fieldPath: metadata.annotations['ops.alert/channel']
```

**Проверка чтения и динамического обновления:**
```bash
# Чтение текущего состояния
kubectl exec dynamic-meta-pod -n monitoring -- cat /etc/podinfo/labels
# → environment="staging"
# → log-level="debug"

# Обновление метки пода на лету
kubectl label pod dynamic-meta-pod -n monitoring log-level=warn --overwrite
# → pod/dynamic-meta-pod labeled

# Проверка через 15-45 секунд (после Kubelet syncLoop)
kubectl exec dynamic-meta-pod -n monitoring -- cat /etc/podinfo/labels
# → environment="staging"
# → log-level="warn"
```

---

### Сценарий 4: DaemonSet узлового агента с обогащением метаданных

Системный агент логирования и мониторинга (Vector, Fluent Bit, Promtail) на каждом физическом узле. Узел и локальный IP передаются через переменные окружения, а права доступа к файлам тома ограничиваются через `defaultMode`.

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: host-metrics-collector
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: host-metrics-collector
  template:
    metadata:
      labels:
        app.kubernetes.io/name: host-metrics-collector
    spec:
      tolerations:
        - operator: Exists
          effect: NoSchedule
      containers:
        - name: collector
          image: alpine:3.20
          command: ["sh", "-c", "echo Ready on $NODE_NAME at $NODE_IP; sleep 86400"]
          env:
            - name: NODE_NAME
              valueFrom:
                fieldRef:
                  fieldPath: spec.nodeName
            - name: NODE_IP
              valueFrom:
                fieldRef:
                  fieldPath: status.hostIP
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: POD_NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
          volumeMounts:
            - name: pod-meta
              mountPath: /etc/meta
              readOnly: true
      volumes:
        - name: pod-meta
          downwardAPI:
            defaultMode: 0440
            items:
              - path: "labels"
                fieldRef:
                  fieldPath: metadata.labels
```

**Проверка статуса демона:**
```bash
kubectl get ds host-metrics-collector -n monitoring
# → NAME                     DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR   AGE
# → host-metrics-collector   3         3         3       3            3           <none>          1m

POD=$(kubectl get pods -n monitoring -l app.kubernetes.io/name=host-metrics-collector -o jsonpath='{.items[0].metadata.name}')
kubectl logs $POD -n monitoring
# → Ready on k8s-worker-01 at 192.168.1.101
```

---

### Сценарий 5: Projected Volume — агрегация Downward API с Secrets и Bound Tokens

Единая точка монтирования конфигураций, аутентификации и метаданных в каталог `/var/run/app-identity`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secured-identity-app
  namespace: secure-workloads
spec:
  containers:
    - name: application
      image: alpine:3.20
      command: ["sh", "-c", "ls -la /var/run/app-identity && sleep 3600"]
      volumeMounts:
        - name: combined-credentials
          mountPath: /var/run/app-identity
          readOnly: true
  volumes:
    - name: combined-credentials
      projected:
        defaultMode: 0400
        sources:
          # 1. Метаданные Pod через Downward API
          - downwardAPI:
              items:
                - path: "pod_name"
                  fieldRef:
                    fieldPath: metadata.name
                - path: "namespace"
                  fieldRef:
                    fieldPath: metadata.namespace
          # 2. Сервисный токен с ограниченной аудиторией
          - serviceAccountToken:
              path: "token"
              expirationSeconds: 3600
              audience: "vault.internal.net"
```

**Проверка смонтированных файлов:**
```bash
kubectl exec secured-identity-app -n secure-workloads -- ls -la /var/run/app-identity
# → total 0
# → drwxr-xr-x    3 root     root           120 Oct 17 13:35 .
# → drwxr-xr-x    3 root     root            60 Oct 17 13:35 ..
# → drwxr-xr-x    2 root     root           100 Oct 17 13:35 ..2026_10_17_13_35_12.987654321
# → lrwxrwxrwx    1 root     root            31 Oct 17 13:35 ..data -> ..2026_10_17_13_35_12.987654321
# → lrwxrwxrwx    1 root     root            16 Oct 17 13:35 namespace -> ..data/namespace
# → lrwxrwxrwx    1 root     root            15 Oct 17 13:35 pod_name -> ..data/pod_name
# → lrwxrwxrwx    1 root     root            12 Oct 17 13:35 token -> ..data/token
```

---

## Операции и команды

### Инспекция томов и symlink-структуры

```bash
# 1. Детальный просмотр точки монтирования тома Downward API
kubectl exec <pod-name> -n <ns> -- ls -la /etc/podinfo/
# → lrwxrwxrwx 1 root root ..data -> ..2026_...
# → lrwxrwxrwx 1 root root labels -> ..data/labels

# 2. Проверка разрешения реального пути симлинка
kubectl exec <pod-name> -n <ns> -- readlink -f /etc/podinfo/labels
# → /etc/podinfo/..2026_10_17_13_30_00.123456789/labels

# 3. Проверка прав доступа к смонтированным файлам
kubectl exec <pod-name> -n <ns> -- stat -c "%a %n" /etc/podinfo/*
# → 444 /etc/podinfo/labels
# → 444 /etc/podinfo/annotations
```

### Инспекция переменных окружения

```bash
# 1. Поиск всех инжектированных переменных Downward API
kubectl exec <pod-name> -n <ns> -- printenv | grep -E "POD_|NODE_|HOST_"

# 2. Проверка соответствия IP адреса в Pod статусу в кластере
POD_IP=$(kubectl get pod <pod-name> -n <ns> -o jsonpath='{.status.podIP}')
CONTAINER_IP=$(kubectl exec <pod-name> -n <ns> -- printenv POD_IP)
[ "$POD_IP" = "$CONTAINER_IP" ] && echo "IP synchronized" || echo "IP mismatch"
# → IP synchronized
```

### Проверка событий при ошибках инициализации

```bash
# Вывод событий конкретного Pod при сбое инжекции
kubectl get events -n <ns> --field-selector involvedObject.name=<pod-name> --sort-by='.metadata.creationTimestamp'

# Фильтрация ошибок конфигурации контейнера
kubectl describe pod <pod-name> -n <ns> | grep -E "Failed|Error|CreateContainerConfigError"
```

---

## Диагностика и устранение неполадок

### Ошибка 1: `CreateContainerConfigError` из-за неподдерживаемого `fieldPath` в томе

**Симптомы:**
Pod переходит в статус `CreateContainerConfigError`. Контейнер не стартует.
```text
Warning  Failed   12s (x3 over 38s)  kubelet  Error: failed to create container config:
unsupported fieldPath: spec.nodeName (or status.podIP) for volume downwardAPI
```

**Причина:**
Попытка использовать сетевые (`status.podIP`, `status.hostIP`) или узловые (`spec.nodeName`, `spec.serviceAccountName`) поля внутри `volumes.downwardAPI.items[*].fieldRef`. Спецификация томов k8s поддерживает только `metadata.name`, `metadata.namespace`, `metadata.uid`, `metadata.labels`, `metadata.annotations` и `resourceFieldRef`.

**Диагностика:**
```bash
kubectl describe pod <pod-name> -n <ns> | grep -A 5 "Events:"
```

**Решение:**
Перенести запрещенные в томах поля в переменные окружения `env.valueFrom.fieldRef`:
```yaml
# Неправильно (в volume):
# - path: "node-name"
#   fieldRef:
#     fieldPath: spec.nodeName

# Правильно (в env контейнера):
env:
  - name: NODE_NAME
    valueFrom:
      fieldRef:
        fieldPath: spec.nodeName
```

---

### Ошибка 2: Файлы метаданных в томе не обновляются при изменении меток

**Симптомы:**
Метка пода изменена через `kubectl label pod <pod> key=new --overwrite`, но файл внутри контейнера содержит старое значение даже через 5 минут.

**Причины:**
1. Использование директивы `subPath` при монтировании тома. Директива `subPath` связывает одиночный файл напрямую в точку монтирования через bind mount Linux, полностью отключая механизм атомарной подмены симлинка `..data`.
2. Приложение открыло дескриптор файла (`open()`) при старте и читает его без закрытия (`close()`).

**Диагностика:**
```bash
# Проверить наличие subPath в манифесте
kubectl get pod <pod-name> -n <ns> -o jsonpath='{.spec.containers[*].volumeMounts[*].subPath}'

# Проверить, обновился ли файл на диске контейнера
kubectl exec <pod-name> -n <ns> -- cat /etc/podinfo/labels
```

**Решение:**
1. Монтировать директорию целиком без `subPath`:
   ```yaml
   volumeMounts:
     - name: podinfo
       mountPath: /etc/podinfo  # БЕЗ subPath
   ```
2. В коде приложения отслеживать события `inotify` (`IN_MOVED_TO`, `IN_CREATE`) на директории `/etc/podinfo` или переоткрывать файл перед каждым чтением.

---

### Ошибка 3: Раздувание манифеста и тома из-за `metadata.annotations`

**Симптомы:**
Файл `/etc/podinfo/annotations` весит десятки килобайт, а оперативная память контейнера тратится на парсинг огромных JSON-строк.

**Причина:**
Монтирование `fieldPath: metadata.annotations` без указания ключа дампит **все** аннотации Pod, включая служебную аннотацию `kubectl.kubernetes.io/last-applied-configuration`, в которой хранится полная JSON-копия исходного манифеста Pod или Deployment.

**Диагностика:**
```bash
kubectl exec <pod-name> -n <ns> -- wc -c /etc/podinfo/annotations
# → 48291 /etc/podinfo/annotations

kubectl exec <pod-name> -n <ns> -- grep "last-applied-configuration" /etc/podinfo/annotations
```

**Решение:**
Монтировать только строго определенные аннотации с явным указанием ключа:
```yaml
volumes:
  - name: podinfo
    downwardAPI:
      items:
        - path: "release-version"
          fieldRef:
            fieldPath: metadata.annotations['app.kubernetes.io/version']
```

---

### Ошибка 4: Неожиданно огромные значения ресурсов при `resourceFieldRef`

**Симптомы:**
Приложение считывает лимит CPU как 64 ядра или RAM как 256 ГБ, хотя планировалось потребление до 512 МБ.

**Причина:**
Сработал механизм **Node Allocatable Fallback**. Если для контейнера в спецификации опущен блок `resources.limits`, Kubelet возвращает через Downward API полные доступные ресурсы узла.

**Диагностика:**
```bash
# Проверить секцию resources контейнера
kubectl get pod <pod-name> -n <ns> -o jsonpath='{.spec.containers[*].resources}'
# → {"requests":{"cpu":"100m"}}  <-- limits отсутствуют!

# Сравнить с емкостью узла
kubectl get node <node-name> -o jsonpath='{.status.allocatable}'
```

**Решение:**
Всегда явно объявлять секцию `resources.limits` при использовании `resourceFieldRef` для лимитов, либо учитывать в коде приложения возможность возврата емкости узла по умолчанию.

---

### Ошибка 5: `CreateContainerConfigError` при обращении к несуществующей метке в `env`

**Симптомы:**
Контейнер не может запуститься, если запрошена метка через `metadata.labels['non-existent']` в блоке `env`.

**Причина:**
В отличие от томов, где отсутствие метки приводит к отсутствию записи в файле, при разрешении одиночной переменной окружения Kubelet валидирует наличие ключа. Если ключ отсутствует в манифесте, создание конфигурации завершается ошибкой.

**Диагностика:**
```bash
kubectl describe pod <pod-name> -n <ns> | grep -i "fieldpath"
# → Warning  Failed  kubelet  Error: failed to create container config:
# → fieldPath metadata.labels['non-existent'] does not exist
```

**Решение:**
1. Гарантировать наличие метки/аннотации в `metadata.labels` спецификации Pod/Deployment.
2. Либо использовать монтирование тома `metadata.labels`, в котором наличие файла гарантировано, а парсинг выполняется приложением безопасно.

---

## Лучшие практики для DevOps, SRE и системных администраторов

### 1. Архитектура и надежность
* **Разделение сфер ответственности**:
  * Используйте `env` для неизменяемых статических параметров идентификации: `metadata.name`, `metadata.namespace`, `spec.nodeName`, `status.podIP`.
  * Используйте `volume` для динамических метаданных (метки, аннотации, фиче-флаги), изменение которых должно подхватываться на лету без инвалидации кэшей и рестарта pod.
* **In-Place Resource Scaling**: Если в кластере включен In-Place Pod Resize, помните, что новые лимиты памяти и CPU будут доступны приложению на лету **только через тома Downward API**. Переменные окружения сохранят значения момента запуска.

### 2. Безопасность (Hardening)
* **Только чтение (`readOnly: true`)**: Всегда монтируйте тома Downward API с флагом `readOnly: true`, чтобы предотвратить случайную или вредоносную модификацию файлов внутри контейнера.
* **Минимальные права (`defaultMode`)**: Ограничивайте права доступа к файлам тома через `defaultMode: 0440` или `0400` в соответствии с принципом наименьших привилегий (POLP).
* **Запрет секретов в метаданных**: Никогда не передавайте токены, пароли или секретные ключи через labels или annotations Pod. Они не шифруются в etcd на уровне Secret и логируются в audit log в открытом виде.

### 3. Наблюдаемость и мониторинг (Observability)
* **Стандартизация обогащения метрик и логов**: Инжектируйте стандартный набор переменных во все базовые манифесты:
  ```text
  OTEL_RESOURCE_ATTRIBUTES="k8s.pod.name=$(POD_NAME),k8s.namespace.name=$(POD_NAMESPACE),k8s.node.name=$(NODE_NAME)"
  ```
* **Отказ от лишних ServiceAccount токенов**: Замените прямые запросы клиентов к Kubernetes API для получения собственного IP/Node на Downward API. Установите `automountServiceAccountToken: false` для сервисов, которым не требуется управлять ресурсами кластера.

### 4. Производительность файловой системы
* Не создавайте тома Downward API с сотнями отдельных файлов. Kubelet монтирует tmpfs и генерирует символические ссылки на каждый item. Монтирование 1-2 файлов (например, общего файла `labels`) предпочтительнее монтирования десятков единичных ключей.

---

## Сравнение с альтернативами

| Критерий | Downward API (env) | Downward API (volume) | ConfigMap / Secret | Projected Volumes | Прямой API-клиент |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Источник данных** | Метаданные Pod / узла | Метаданные Pod / узла | Пользовательские конфигурации | Агрегация всех источников | Kubernetes API-Server |
| **Динамическое обновление** | Нет (нужен рестарт) | Да (Kubelet sync) | Да (через тома) | Да | Да (через watch) |
| **Сетевые поля (podIP, hostIP)**| **Да** | **Нет** | Нет | Нет | Да |
| **Узловые поля (nodeName)** | **Да** | **Нет** | Нет | Нет | Да |
| **Потребность в RBAC** | Нет | Нет | Нет | Да (если есть SA token)| Да (Role/RoleBinding) |
| **Нагрузка на API-server** | Нулевая (локально) | Нулевая (локально) | Нулевая (локально) | Нулевая (локально) | Высокая при масштабировании|
| **Поддержка In-Place Resize** | Нет | **Да** | Не применимо | **Да** | Да |

---

## Дополнительная информация

**Связанные документы в базе знаний:**
- [Тома в Kubernetes](./volume_types/volume_types.md) — классификация и специфика всех типов томов.
- [Projected Volumes](./volume_types/projected_volumes.md) — агрегирование Downward API, Secret и ConfigMap в единую файловую систему.
- [ConfigMap в Kubernetes](../configmap.md) — управление внешними конфигурациями.
- [Управление ресурсами: Requests, Limits и QoS](../../Scheduling/qos_limit_and_requests.md) — математика и приоритеты выделения вычислительных ресурсов.
- [DaemonSet в Kubernetes](../daemonset.md) — архитектура запуска системных узловых агентов.
- [Troubleshooting: CreateContainerConfigError](../../Troubleshooting/Common_Errors/CreateContainerConfigError/definitions.md) — каталог типичных ошибок инициализации контейнеров.
