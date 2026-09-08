# Taints и Tolerations (Отравления и Терпимость): Управление размещением подов

## Определения

* **Taints (отравления)**: Механизм, применяемый к узлам Kubernetes, который «отталкивает» поды, не имеющие соответствующего `toleration`. Состоит из ключа (`key`), значения (`value`) и эффекта (`effect`).

    ```bash
    kubectl taint nodes <node-name> <key>=<value>:<effect>
    # Пример:
    kubectl taint nodes worker-1 dedicated=ml:NoSchedule
    # → node/worker-1 tainted
    # Пример удаления (дефис в конце):
    kubectl taint nodes worker-1 dedicated=ml:NoSchedule-
    ```

* **Tolerations (терпимость)**: Свойство, задаваемое в спецификации пода (`pod.spec`), которое позволяет ему «терпеть» `taint` на узле и быть размещённым на нём.
* **Node Controller (Контроллер узлов)**: Системный компонент Control Plane, который следит за состоянием узлов и автоматически накладывает Taints при аппаратных или сетевых сбоях.

### Эффекты Taint

* **`NoSchedule`**: Kubernetes не размещает на узле **новые** поды без `toleration`. Существующие поды продолжают работать.
* **`PreferNoSchedule`**: «Мягкая» версия `NoSchedule`. Kubernetes старается не размещать на узле новые поды без `toleration`, но сделает это при отсутствии альтернатив.
* **`NoExecute`**: Самый строгий эффект. Новые поды без `toleration` не размещаются, а существующие поды без `toleration` **вытесняются (evicted)**.

---

## Предварительные требования

### Требования к кластеру

* **Kubernetes**: версия 1.17+ (DaemonSet планируется стандартным планировщиком), 1.28+ (Non-Graceful Node Shutdown), 1.31+ (DisruptionTarget GA, безопасная обработка выселений)
* **Kubelet**: настроены параметры `--node-monitor-grace-period` (по умолчанию 40с) и `--pod-eviction-timeout` (по умолчанию 5м) для управления автоматическими taints
* **Container Runtime**: containerd 1.6+ или CRI-O 1.20+

### Инструменты

* **kubectl**: версия 1.20+ (для управления taints и проверки tolerations)
* **Metrics Server**: для мониторинга состояния узлов
* **kubectl-debug** (опционально): для диагностики проблем с размещением

### Проверка готовности

```bash
# Проверка версии кластера
kubectl version --short
# Client Version: v1.28.0
# Server Version: v1.28.0

# Проверка текущих taints на узлах
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
# NAME     TAINTS
# master1  [map[effect:NoSchedule key:node-role.kubernetes.io/control-plane]]
# worker1  <none>

# Проверка состояния узлов
kubectl get nodes
# NAME     STATUS   ROLES           AGE   VERSION
# master1  Ready    control-plane   10d   v1.28.0
# worker1  Ready    <none>          10d   v1.28.0

# Проверка настроек Node Controller
ps aux | grep kube-controller-manager | grep node-monitor-grace-period
# --node-monitor-grace-period=40s
```

### Начальное состояние

Перед выполнением сценариев убедитесь, что:
* Кластер находится в исправном состоянии (все узлы `Ready`)
* Нет критических подов, которые могут быть выселены при выполнении сценариев с `NoExecute`
* Вы имеете доступ к управлению узлами (права `update` на ресурс `nodes`)

---

## Основные концепции

### Зачем нужны Taints и Tolerations?

В больших кластерах Kubernetes не все узлы одинаковы. Некоторые могут иметь специализированное оборудование (GPU), другие — быть выделены под конкретные задачи. Без механизмов ограничения планировщик может разместить любой под на любом свободном узле, что приведет к неэффективному использованию ресурсов или проблемам с производительностью. Основные сценарии применения:

1. **Выделение узлов для специфических задач**: Гарантия того, что дорогостоящие ресурсы (например, узлы с GPU) используются только теми подами, которым они действительно необходимы для работы (машинное обучение, обработка графики).
2. **Изоляция узлов для обслуживания или устранения неполадок**: Вы можете «испортить» (taint) узел, на котором проводится обслуживание, чтобы предотвратить планирование новых подов, при этом разрешая работу только критически важным нагрузкам (имеющим соответствующий `toleration`).
3. **Защита от проблемных узлов**: Если на узле возникают системные ошибки (проблемы с диском, сетью), Kubernetes автоматически применяет taints. Это позволяет запретить планирование новых подов на нестабильном оборудовании до тех пор, пока проблема не будет решена.
4. **Удаление подов с узлов (Eviction)**: Использование эффекта `NoExecute` позволяет принудительно выселить все поды с узла при обнаружении критических проблем.

### Как действуют запятнания и терпимость?

Механизм работает по принципу «отталкивания» и «допуска»:
* **Taint (Запятнание)** применяется к **узлу**. Оно сигнализирует планировщику, что узел «отталкивает» все поды, которые не имеют специфического разрешения.
* **Toleration (Терпимость)** применяется к **поду**. Она позволяет модулю игнорировать («терпеть») пятно на узле и быть запланированным на нем.

### Эффекты Taint и поведение подов

| Taint Effect | Поведение для **новых** подов (без toleration) | Поведение для **существующих** подов (без toleration) |
| :--- | :--- | :--- |
| `NoSchedule` | Не размещаются | Продолжают работать |
| `PreferNoSchedule` | Kubernetes старается не размещать | Продолжают работать |
| `NoExecute` | Не размещаются | Вытесняются (evicted) |

### Операторы Toleration

В `toleration` пода указывается оператор для сопоставления с `taint` узла:

* `operator: "Equal"`: `toleration` срабатывает, если `key`, `value` и `effect` точно совпадают с `taint`.
* `operator: "Exists"`: `toleration` срабатывает для любого `taint` с указанным `key` и `effect`, независимо от `value`. Если указан только `operator: "Exists"`, под стерпит **любые** taints на узле.

> **Важно**: `toleration` не гарантирует, что под попадёт именно на ноду с соответствующим `taint` — он лишь снимает запрет на размещение. Для направления пода на конкретную ноду используйте `nodeSelector` или `nodeAffinity`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-pod
spec:
  tolerations:
  - key: "key1"
    operator: "Equal"
    value: "value1"
    effect: "NoSchedule"
  - key: "key2"
    operator: "Exists"
    effect: "NoExecute"
```

### Стандартные Taints узлов (Taint-based Eviction)

Kubernetes автоматически применяет следующие `taints` к узлам:

| Taint | Описание | Условие (Condition) |
| :--- | :--- | :--- |
| `node.kubernetes.io/not-ready:NoExecute` | Узел не готов | `Ready=False` |
| `node.kubernetes.io/unreachable:NoExecute` | Узел недоступен | `Ready=Unknown` |
| `node.kubernetes.io/memory-pressure:NoSchedule` | Нехватка памяти | `MemoryPressure=True` |
| `node.kubernetes.io/disk-pressure:NoSchedule` | Нехватка диска | `DiskPressure=True` |
| `node.kubernetes.io/pid-pressure:NoSchedule` | Исчерпание PID | `PIDPressure=True` |
| `node.kubernetes.io/network-unavailable:NoSchedule` | Сеть недоступна | `NetworkUnavailable=True` |
| `node-role.kubernetes.io/control-plane:NoSchedule` | Узел управления | Роль Control Plane |

### Процесс выселения (Eviction Timeline)

При потере связи с узлом процесс выселения подов проходит следующие этапы:

1. **Обнаружение**: `node-controller` ждёт время, указанное в `--node-monitor-grace-period` (по умолчанию 40с).
2. **Маркировка**: Состояние узла меняется на `Unknown`, добавляется taint `unreachable:NoExecute`.
3. **Ожидание**: Поды без специфических `tolerations` начинают выселяться по истечении `tolerationSeconds` (по умолчанию 300с для стандартных taints `not-ready` и `unreachable`). Для каждого пода запускается индивидуальный таймер.
4. **Удаление**: Поды удаляются из API и планируются на другие узлы.

### Параметры Node Controller

| Параметр | По умолчанию | Описание |
| :--- | :--- | :--- |
| `--node-monitor-grace-period` | 40s | Время до присвоения статуса `Unknown` |
| `--pod-eviction-timeout` | 5m | Интервал между попытками выселения (в современных версиях приоритет отдается логике `tolerationSeconds`) |

### Поведение DaemonSet

Начиная с Kubernetes 1.17, поды DaemonSet планируются стандартным планировщиком (kube-scheduler), но с определенными послаблениями:
* **Автоматические Tolerations:** DaemonSet Controller автоматически добавляет tolerations для `node.kubernetes.io/unreachable:NoExecute` и `node.kubernetes.io/not-ready:NoExecute` без таймаута (`tolerationSeconds: null`), чтобы агент сбора логов или CNI никогда не выселялся с проблемного узла.
* **Игнорирование изоляции:** DaemonSet автоматически получает `toleration` для `node.kubernetes.io/unschedulable:NoSchedule` (при `kubectl cordon`).
* **Control Plane:** Однако, для запуска DaemonSet на master-узлах (Control Plane) **необходимо явно** прописать `toleration` в манифесте, так как этот taint имеет пользовательскую (административную) природу.

### Сравнение с Affinity

* **Taints и Tolerations работают «от ноды»**: Нода «отталкивает» поды. Используется для изоляции ресурсов (GPU, выделенные узлы).
* **Node Affinity работает «от пода»**: Под «тянется» к нодам. Используется для выбора узлов по характеристикам (тип диска, зона).
* **Совместное использование**: Taints удерживают лишние поды, а Node Affinity гарантирует попадание нужных подов на правильные узлы. Подробнее в [Affinity и Anti-Affinity](./affinity.md).

---

## Практические сценарии

### Сценарий 1: Выделение узлов под специфические задачи (GPU)

Узлы с дорогостоящим оборудованием (GPU, FPGA, SSD) «отравляются», чтобы на них не попадали обычные поды. Это оптимизирует использование специализированного оборудования. Однако самих `tolerations` недостаточно для гарантии того, что под попадет именно на узел с GPU — они лишь снимают запрет. Для точного планирования необходимо комбинировать их с **Node Affinity**.

**Настройка узла:**
```bash
# Применение taint для защиты узла от посторонних нагрузок
kubectl taint nodes node1 gpu=true:NoSchedule
# → node/node1 tainted

# Применение метки для притяжения нужных нагрузок
kubectl label nodes node1 gpu=true
# → node/node1 labeled

# Проверка применённых taints
kubectl describe node node1 | grep Taints
# → Taints:             gpu=true:NoSchedule
```

**Настройка пода:**
Поды приложения, требующие GPU, должны иметь и терпимость, и аффинити:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: gpu-workload
  namespace: default
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: gpu
            operator: In
            values:
            - "true"
  tolerations:
  - key: "gpu"
    operator: "Equal"
    value: "true"
    effect: "NoSchedule"
  containers:
  - name: cuda-container
    image: nvidia/cuda:12.0-base
    resources:
      limits:
        nvidia.com/gpu: 1
```

**Валидация:**
```bash
# Создание пода
kubectl apply -f gpu-workload.yaml
# → pod/gpu-workload created

# Проверка, что под разместился на нужном узле
kubectl get pod gpu-workload -o wide
# NAME          READY   STATUS    RESTARTS   AGE   IP            NODE
# gpu-workload  1/1     Running   0          10s   10.244.1.5    node1

# Проверка tolerations пода
kubectl get pod gpu-workload -o jsonpath='{.spec.tolerations}'
# → [{"effect":"NoSchedule","key":"gpu","operator":"Equal","value":"true"}]

# Попытка создать под без toleration — должен попасть на другой узел или остаться в Pending
kubectl run test-pod --image=nginx
kubectl get pod test-pod -o wide
# NAME       READY   STATUS    RESTARTS   AGE   IP            NODE
# test-pod   1/1     Running   0          5s    10.244.2.3    worker1  # Не node1
```

**Cleanup:**
```bash
# Удаление тестовых подов
kubectl delete pod gpu-workload test-pod
# → pod "gpu-workload" deleted
# → pod "test-pod" deleted

# Удаление taint с узла
kubectl taint nodes node1 gpu=true:NoSchedule-
# → node/node1 untainted

# Удаление метки
kubectl label nodes node1 gpu-
# → node/node1 unlabeled
```

**Граничные случаи:**
* Если все GPU-узлы заняты, под останется в `Pending` — необходимо мониторить доступность ресурсов.
* При использовании `PreferNoSchedule` вместо `NoSchedule` под может попасть на не-GPU узел, если GPU-узлы недоступны.
* При автоматическом масштабовании (Cluster Autoscaler) убедитесь, что настроены правила расширения для GPU-узлов.

---

### Сценарий 2: Разрешение запуска на Control Plane

По умолчанию узлы управления имеют taint, запрещающий запуск рабочих подов. Чтобы запустить на них, например, агент мониторинга через `DaemonSet`:

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-exporter
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: node-exporter
  template:
    metadata:
      labels:
        app: node-exporter
    spec:
      tolerations:
      - key: "node-role.kubernetes.io/control-plane"
        operator: "Exists"
        effect: "NoSchedule"
      containers:
      - name: node-exporter
        image: prom/node-exporter:v1.6.0
        ports:
        - containerPort: 9100
```

**Валидация:**
```bash
# Создание DaemonSet
kubectl apply -f node-exporter-ds.yaml
# → daemonset.apps/node-exporter created

# Проверка, что поды запущены на всех узлах (включая Control Plane)
kubectl get pods -n monitoring -o wide
# NAME                  READY   STATUS    RESTARTS   AGE   IP            NODE
# node-exporter-abc12   1/1     Running   0          30s   10.244.0.5    master1
# node-exporter-def34   1/1     Running   0          30s   10.244.1.3    worker1

# Проверка событий (не должно быть ошибок планирования)
kubectl get events -n monitoring --field-selector reason=FailedScheduling
# No resources found
```

**Cleanup:**
```bash
kubectl delete daemonset node-exporter -n monitoring
# → daemonset.apps "node-exporter" deleted
```

**Граничные случаи:**
* DaemonSet Controller автоматически добавляет tolerations для `node.kubernetes.io/unreachable` и `node.kubernetes.io/not-ready`, но НЕ для `node-role.kubernetes.io/control-plane` — последний нужно указывать явно.
* При использовании `operator: "Exists"` без указания `key` под будет терпеть ВСЕ taints — это может привести к нежелательному размещению на проблемных узлах.

---

### Сценарий 3: Управление временем выселения (Graceful Eviction)

Если под должен оставаться на недоступном узле дольше стандартных 5 минут (например, при кратковременных сбоях сети или для StatefulSet, который болезненно переносит смену хоста):

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: database
spec:
  serviceName: postgres
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      tolerations:
      - key: "node.kubernetes.io/unreachable"
        operator: "Exists"
        effect: "NoExecute"
        tolerationSeconds: 900  # 15 минут
      - key: "node.kubernetes.io/not-ready"
        operator: "Exists"
        effect: "NoExecute"
        tolerationSeconds: 900  # 15 минут
      containers:
      - name: postgres
        image: postgres:15
        env:
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-secret
              key: password
```

**Валидация:**
```bash
# Проверка настроек tolerationSeconds
kubectl get pod postgres-0 -n database -o jsonpath='{.spec.tolerations}' | jq .
# [
#   {
#     "effect": "NoExecute",
#     "key": "node.kubernetes.io/unreachable",
#     "operator": "Exists",
#     "tolerationSeconds": 900
#   },
#   {
#     "effect": "NoExecute",
#     "key": "node.kubernetes.io/not-ready",
#     "operator": "Exists",
#     "tolerationSeconds": 900
#   }
# ]

# Симуляция недоступности узла (для тестирования)
# На узле выполняем: sudo systemctl stop kubelet

# Проверка состояния узла через 40 секунд
kubectl get nodes
# NAME     STATUS     ROLES    AGE   VERSION
# worker1  NotReady   <none>   10d   v1.28.0

# Проверка taints на узле
kubectl describe node worker1 | grep Taints
# → Taints: node.kubernetes.io/not-ready:NoExecute

# Под должен оставаться Running до истечения 900 секунд
kubectl get pod postgres-0 -n database -o wide
# NAME        READY   STATUS    RESTARTS   AGE   IP            NODE
# postgres-0  1/1     Running   0          2m    10.244.1.10   worker1
```

**Cleanup:**
```bash
# Восстановление узла (перезапуск kubelet)
# sudo systemctl start kubelet

# Удаление тестового StatefulSet
kubectl delete statefulset postgres -n database
# → statefulset.apps "postgres" deleted
```

**Граничные случаи:**
* Для stateless-микросервисов можно установить `tolerationSeconds: 30` для быстрого выселения.
* При значении `tolerationSeconds: null` (по умолчанию для DaemonSet) под никогда не выселяется автоматически.
* Слишком большое значение `tolerationSeconds` может задержать восстановление при реальном отказе узла.

---

### Сценарий 4: Динамическое управление и обслуживание (Maintenance)

Использование `taint` для временного вывода узла из планирования без его полной остановки, сохраняя при этом работу критических сервисов.

**Процесс обслуживания:**

1. **Применение taint**: Устанавливается запрет на новые поды, кроме критических.
   ```bash
   kubectl taint nodes worker-1 maintenance=true:NoSchedule
   # → node/worker-1 tainted
   ```

2. **Настройка критических подов**: Сервисы, которые должны продолжать работу во время обслуживания (или сам процесс обслуживания), снабжаются допуском:
   ```yaml
   apiVersion: v1
   kind: Pod
   metadata:
     name: critical-service
   spec:
     tolerations:
     - key: "maintenance"
       operator: "Equal"
       value: "true"
       effect: "NoSchedule"
     containers:
     - name: app
       image: my-app:latest
   ```

3. **Валидация**:
   ```bash
   # Проверка, что новые поды не размещаются на узле
   kubectl describe node worker-1 | grep Taints
   # → Taints: maintenance=true:NoSchedule

   # Проверка, что критический под работает
   kubectl get pod critical-service -o wide
   # NAME               READY   STATUS    RESTARTS   AGE   IP            NODE
   # critical-service   1/1     Running   0          5m    10.244.1.5    worker-1

   # Попытка создать обычный под — должен попасть на другой узел
   kubectl run test-pod --image=nginx
   kubectl get pod test-pod -o wide
   # NAME       READY   STATUS    RESTARTS   AGE   IP            NODE
   # test-pod   1/1     Running   0          10s   10.244.2.8    worker-2  # Не worker-1
   ```

4. **Завершение работ**: Удаление taint (дефис в конце).
   ```bash
   kubectl taint nodes worker-1 maintenance=true:NoSchedule-
   # → node/worker-1 untainted
   ```

**Cleanup:**
```bash
kubectl delete pod critical-service test-pod
# → pod "critical-service" deleted
# → pod "test-pod" deleted
```

**Граничные случаи:**
* `NoSchedule` не выселяет существующие поды — для принудительного выселения используйте `NoExecute` (с осторожностью).
* При использовании `kubectl cordon` автоматически создаётся taint `node.kubernetes.io/unschedulable:NoSchedule`, DaemonSet игнорирует его автоматически.

---

### Сценарий 5: Безопасное выселение при отказе узла (Non-Graceful Node Shutdown)

Начиная с Kubernetes 1.28, для безопасного выселения подов с отказавшего узла используется taint `node.kubernetes.io/out-of-service`.

```bash
# Убедитесь, что узел физически выключен (не перезагружается)
# Наложение taint для принудительного выселения
kubectl taint nodes worker-1 node.kubernetes.io/out-of-service=nodeshutdown:NoExecute
# → node/worker-1 tainted
```

**Валидация:**
```bash
# Проверка taints на узле
kubectl describe node worker-1 | grep Taints
# → Taints: node.kubernetes.io/out-of-service=nodeshutdown:NoExecute

# Поды без toleration должны начать выселяться на другие узлы
kubectl get pods -A -o wide --field-selector spec.nodeName=worker-1
# (список должен уменьшаться по мере выселения)

# Проверка событий выселения
kubectl get events --field-selector reason=TaintManagerEviction
# LAST SEEN   TYPE     REASON                 OBJECT         MESSAGE
# 30s         Normal   TaintManagerEviction   pod/my-app-0   Marking for deletion Pod default/my-app-0
```

**Cleanup (после восстановления узла):**
```bash
# Удаление taint после возврата узла в строй
kubectl taint nodes worker-1 node.kubernetes.io/out-of-service=nodeshutdown:NoExecute-
# → node/worker-1 untainted

# Возврат узла в планирование
kubectl uncordon worker-1
# → node/worker-1 uncordoned
```

**Граничные случаи:**
* Для StatefulSet принудительное выселение при недоступном узле несёт риск **split-brain** — применяйте только после подтверждения физического отключения узла.
* Taint `out-of-service` игнорирует PDB — используйте с осторожностью в production.
* Подробнее о рисках и безопасных методах: [Недоступность узла: Taints и выселение](../Troubleshooting/Common_Errors/NodeUnavailability/taints_and_eviction.md).

---

### Сценарий 6: Ручное выселение в обход PDB через Taints

Когда PDB блокирует `kubectl drain` и необходимо очистить узел:

```bash
# Наложение taint для принудительного выселения всех подов без toleration
kubectl taint node worker-1 manual-eviction=true:NoExecute
# → node/worker-1 tainted
```

**Валидация:**
```bash
# Поды начнут выселяться немедленно (без ожидания tolerationSeconds для подов без соответствующего toleration)
kubectl get pods -A -o wide --field-selector spec.nodeName=worker-1
# (список должен быстро опустеть)

# Поды с соответствующим toleration останутся
kubectl get pod tolerant-pod -o wide
# NAME           READY   STATUS    RESTARTS   AGE   IP            NODE
# tolerant-pod   1/1     Running   0          10m   10.244.1.20   worker-1
```

**Cleanup:**
```bash
# Удаление taint после завершения работ
kubectl taint node worker-1 manual-eviction=true:NoExecute-
# → node/worker-1 untainted
```

**Граничные случаи:**
* Этот метод **игнорирует PDB** — используйте только в экстренных ситуациях или при некорректной настройке PDB.
* Для StatefulSet высок риск split-brain — подробности в [Выселение подов: Блокировки PDB и Taint-based Eviction](../Troubleshooting/Common_Errors/PodEvicted/pdb_and_taint_eviction.md).

---

## Рекомендации (Best Practices)

* **Выделение специализированного оборудования**: Всегда используйте taints для узлов с GPU, SSD или FPGA. Это гарантирует, что дорогостоящие ресурсы не будут расходоваться на задачи общего назначения.
* **Упрощение ключей и значений**: Используйте четкие, краткие и понятные ключи (например, `gpu=true`, `env=prod`). Избегайте чрезмерно сложных конфигураций, которые затрудняют чтение и обслуживание манифестов.
* **Сочетание с Node Affinity**: Для максимальной точности используйте Taints для *отталкивания* лишних подов и Node Affinity для *притяжения* нужных подов к конкретным узлам. Это особенно важно для оборудования со специфическими конфигурациями.
* **Мониторинг эффективности**: Чрезмерное использование taints может привести к фрагментации кластера и недоиспользованию ресурсов. Отслеживайте распределение подов по узлам и количество неиспользуемых ресурсов.
* **Изоляция при сбоях (Проактивная защита)**: При обнаружении проблем на узле (например, перегрев, сбои диска) немедленно применяйте `NoSchedule` taint вручную, чтобы предотвратить деградацию новых рабочих нагрузок до выяснения причин.
* **Мгновенное выселение проблемных подов (`NoExecute`)**: Если узел был скомпрометирован (Security Breach) или на нем обнаружен сбой файловой системы, наложите `NoExecute` taint. Это немедленно "смахнёт" с узла все пользовательские поды без потери времени на Graceful Shutdown.
* **Взаимодействие с Pod Disruption Budget (PDB)**: Выселение по Taint `NoExecute` игнорирует PDB в старых версиях K8s, но начиная с K8s 1.31 выселения TaintManager обрабатываются более безопасно (добавляется условие `DisruptionTarget`). Настройте `unhealthyPodEvictionPolicy: AlwaysAllow` в PDB для автоматизации выселения зависших подов.
* **Автоматические tolerations DaemonSet**: Не забывайте, что DaemonSet автоматически получает tolerations для `not-ready` и `unreachable`, но НЕ для `control-plane` — последний нужно указывать явно.
* **Документирование taints**: Ведите реестр пользовательских taints с описанием их назначения. Это поможет при расследовании инцидентов и планировании ёмкости.
* **Тестирование сценариев отказа**: Регулярно проводите учения по отказу узлов для проверки корректности настроек `tolerationSeconds` и поведения приложений.

---

## Дополнительная информация

### Troubleshooting

#### Проблема: Под завис в состоянии Pending

**Симптом:**
```
kubectl get pod my-pod
# NAME     READY   STATUS    RESTARTS   AGE
# my-pod   0/1     Pending   0          5m
```

**Диагностика:**
```bash
# Проверка событий пода
kubectl describe pod my-pod | grep -A 10 "Events:"
# Warning  FailedScheduling  0/3 nodes are available:
# 3 node(s) had taint {node-role.kubernetes.io/control-plane: },
# that the pod didn't tolerate.

# Проверка taints на всех узлах
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
```

**Решение:**
Добавьте соответствующий toleration в спецификацию пода:
```yaml
tolerations:
- key: "node-role.kubernetes.io/control-plane"
  operator: "Exists"
  effect: "NoSchedule"
```

#### Проблема: Поды не выселяются при отказе узла

**Симптом:**
Узел в `NotReady`, но поды остаются на нём дольше ожидаемого.

**Диагностика:**
```bash
# Проверка tolerations пода
kubectl get pod <pod-name> -o jsonpath='{.spec.tolerations}' | jq .
# Проверьте, есть ли toleration с большим tolerationSeconds

# Проверка текущего статуса узла
kubectl describe node <node-name> | grep -E "Conditions|Taints"
```

**Решение:**
* Уменьшите `tolerationSeconds` для ускорения выселения.
* Для немедленного выселения используйте taint `out-of-service:NoExecute` (K8s 1.28+).

#### Проблема: DaemonSet не запускается на некоторых узлах

**Симптом:**
```bash
kubectl get daemonset -n monitoring
# NAME           DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR   AGE
# node-exporter  3         2         2       2            2           <none>          10m
# DESIRED=3, но CURRENT=2
```

**Диагностика:**
```bash
# Проверка событий DaemonSet
kubectl describe daemonset node-exporter -n monitoring | grep -A 10 "Events:"
# Ищите сообщения о несовпадении taints/tolerations

# Проверка taints на проблемном узле
kubectl describe node <node-name> | grep Taints
```

**Решение:**
Добавьте необходимые tolerations в шаблон DaemonSet:
```yaml
tolerations:
- key: "node-role.kubernetes.io/control-plane"
  operator: "Exists"
  effect: "NoSchedule"
```

#### Проблема: Случайное выселение подов

**Симптом:**
Поды неожиданно перезапускаются и перемещаются на другие узлы.

**Диагностика:**
```bash
# Проверка событий выселения
kubectl get events --field-selector reason=TaintManagerEviction
# LAST SEEN   TYPE     REASON                 OBJECT         MESSAGE
# 2m          Normal   TaintManagerEviction   pod/my-app-0   Marking for deletion Pod default/my-app-0

# Проверка текущих taints на узлах
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
```

**Решение:**
* Проверьте, не были ли случайно наложены taints администратором или автоматическим скриптом.
* Добавьте tolerations для критических подов, чтобы предотвратить неожиданное выселение.
* Настройте мониторинг изменений taints через Kubernetes Audit Logs.

---

### Диагностика и мониторинг

```bash
# Вывод всех узлов с их taints (кастомные колонки)
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints

# Проверка taints на узле
kubectl describe node <node-name> | grep Taints
# → Taints:             dedicated=ml:NoSchedule

# Проверка tolerations пода
kubectl get pod <pod-name> -o jsonpath='{.spec.tolerations}'
# → [{"key":"key1","operator":"Equal","value":"value1","effect":"NoSchedule"}]

# Поиск причины зависания пода в Pending
kubectl get events --field-selector reason=FailedScheduling
# Пример ошибки: "0/3 nodes are available: 1 node(s) had untolerated taint {hardware: gpu}"

# Мониторинг событий выселения
kubectl get events -A --field-selector reason=TaintManagerEviction

# Проверка условия DisruptionTarget (K8s 1.31+)
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[?(@.type=="DisruptionTarget")]}'
# → {"lastTransitionTime":"...","message":"","reason":"DeletionByTaintManager","status":"True"}
```

---

* **DaemonSet**: По умолчанию игнорирует `NoSchedule` для `node.kubernetes.io/unschedulable`. Имеет встроенные tolerations для `node-role.kubernetes.io/master` и `node-role.kubernetes.io/control-plane` (эффект `NoSchedule`), поэтому работает на master-нодах без явной toleration в манифесте.
* **QoS классы**: Влияют на приоритет вытеснения при нехватке ресурсов. Подробнее в [QoS, Requests и Limits](./qos_limit_and_requests.md).

**См. также:**
* [Недоступность узла: Taints и выселение](../Troubleshooting/Common_Errors/NodeUnavailability/taints_and_eviction.md) — глубокий разбор аварийных ситуаций, связанных с `NoExecute` taints.
* [Выселение подов: Блокировки PDB и Taint-based Eviction](../Troubleshooting/Common_Errors/PodEvicted/pdb_and_taint_eviction.md) — сравнение механизмов выселения и обход блокировок PDB.
* [Affinity и Anti-Affinity](./affinity.md) — механизм притяжения подов к узлам, работает в связке с Taints.
* [Topology Manager](./topology_manager.md) — NUMA-осознанное планирование ресурсов, координирует CPU, Memory и Device Manager.
* [Обслуживание узлов (Cordon/Drain)](../Operations/node_maintenance.md) — регламент планового вывода узлов из кластера.
* [Pod Disruption Budget](../Autoscaling/pod_disruption_budget.md) — защита от добровольных прерываний.