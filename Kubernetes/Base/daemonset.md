# DaemonSet

**Актуально для:** Kubernetes 1.30–1.35

## Определения

**DaemonSet** — это встроенный контроллер рабочей нагрузки в Kubernetes (группа API `apps/v1`), гарантирующий запуск ровно одного экземпляра пода (**Pod**) на каждом подходящем узле кластера (или на строго определенном подмножестве узлов).

В отличие от [Deployment](./Deployment/index.md) и [ReplicaSet](./replicaset.md), в спецификации `DaemonSet` отсутствует поле `spec.replicas`. Целевое количество запущенных копий вычисляется динамически на основе топологии кластера — числа доступных и удовлетворяющих селекторам рабочих узлов.

### Ключевые дифференциаторы DaemonSet

В архитектуре Kubernetes и практике системного администрирования / SRE контроллер DaemonSet выделяется следующими свойствами:

*   **Топологическая привязка (Node-bound):** Каждый под DaemonSet создается с жесткой привязкой к конкретному узлу. При отказе или удалении узла под не «переезжает» на другой узел — он удаляется вместе с узлом.
*   **Автоматическое масштабирование по топологии:** При вводе в кластер нового физического или виртуального сервера контроллер автоматически создает на нем экземпляр пода. При выводе узла из эксплуатации сборщик мусора Kubernetes удаляет соответствующий под.
*   **Идемпотентность покрытия инфраструктуры:** Контроллер гарантирует 100%-й охват требуемых узлов системными агентами без необходимости ручного вмешательства администратора при изменении размера кластера.
*   **Приоритет системных компонентов:** Поды DaemonSet обычно обслуживают сам узел (сеть, диски, метрики, логи) и требуют повышенного приоритета планирования и защиты от вытеснения по сравнению с прикладными сервисами.

### ControllerRevision — механизм версионирования

Для управления историей изменений и обеспечения надежных откатов контроллер DaemonSet использует служебные объекты **ControllerRevision** (API `apps/v1`):

*   При каждом изменении шаблона пода (`spec.template`) контроллер вычисляет хеш новой конфигурации и сохраняет снапшот состояния в объекте `ControllerRevision` с инкрементным номером ревизии.
*   Объекты `ControllerRevision` хранят сериализованные данные шаблона пода (`Data`), что позволяет возвращаться к предыдущим стабильным версиям даже при утере исходных YAML-файлов.
*   Количество сохраняемых ревизий регулируется параметром `spec.revisionHistoryLimit` (по умолчанию `10`).

---

## Основные концепции

### Архитектура и цикл согласования (Reconciliation Loop)

Управление состоянием DaemonSet осуществляется контроллером `daemonset-controller`, работающим внутри процесса `kube-controller-manager`:

1.  **Отслеживание событий (Watch):** Контроллер слушает поток событий API-сервера, реагируя на добавление/удаление/изменение объектов `DaemonSet`, `Pod` и `Node`.
2.  **Оценка пригодности узлов:** Контроллер фильтрует узлы кластера на основе правил `spec.template.spec.nodeSelector`, `spec.template.spec.affinity.nodeAffinity`, а также проверяет `taints` узлов на соответствие заданным `tolerations`.
3.  **Генерация манифестов подов:** Для каждого подходящего узла, где под еще не запущен (или требует обновления), контроллер формирует спецификацию пода. При этом контроллер внедряет в `spec.affinity.nodeAffinity` требование жесткого совпадения имени узла (`metadata.name`).
4.  **Планирование через kube-scheduler:** Начиная с версии Kubernetes 1.17, назначение подов DaemonSet на узлы выполняет стандартный **kube-scheduler** (а не сам контроллер DaemonSet, как было в ранних версиях). Планировщик полноценно учитывает:
    *   Лимиты и запросы ресурсов узла (`resources.requests`);
    *   Приоритеты и классы вытеснения (`PriorityClass`);
    *   Условия предикатов и плагинов планирования.
5.  **Контроль расхождений (Drift):** Если на узле оказывается под, который там находиться не должен (например, метка узла изменилась и перестала соответствовать селектору), счетчик `.status.numberMisscheduled` увеличивается, а контроллер отправляет команду на удаление лишнего пода.

### Автоматические допуски (Default Tolerations)

Чтобы системные агенты могли функционировать на узлах в условиях деградации или обслуживания, контроллер DaemonSet автоматически внедряет в каждый создаваемый под набор стандартных допусков (**Tolerations**):

| Taint узла | Эффект | Поведение пода DaemonSet |
| :--- | :--- | :--- |
| `node.kubernetes.io/not-ready` | `NoExecute` | Добавляется с `tolerationSeconds: 300`. Под не выселяется немедленно при кратковременном сетевом сбое kubelet. |
| `node.kubernetes.io/unreachable` | `NoExecute` | Добавляется с `tolerationSeconds: 300`. Защищает от мгновенной эвикции при потере связи мастера с узлом. |
| `node.kubernetes.io/disk-pressure` | `NoSchedule` | Добавляется автоматически. Позволяет агентам мониторинга и очистки запускаться на узле с переполненным диском. |
| `node.kubernetes.io/memory-pressure` | `NoSchedule` | Добавляется автоматически. Агенты продолжают работу для диагностики нехватки памяти. |
| `node.kubernetes.io/pid-pressure` | `NoSchedule` | Добавляется автоматически. Позволяет системным демонам работать при дефиците PID на хосте. |
| `node.kubernetes.io/unschedulable` | `NoSchedule` | Добавляется автоматически. Гарантирует, что при выполнении `kubectl cordon` поды DaemonSet продолжают обслуживать узел. |
| `node.kubernetes.io/network-unavailable` | `NoSchedule` | Добавляется **только при наличии `hostNetwork: true`**. Позволяет сетевым плагинам (CNI) запуститься и настроить сеть узла. |

> [!IMPORTANT]
> Если узел размечен пользовательскими taints (например, выделенные узлы под БД `dedicated=db:NoSchedule` или узлы с GPU), DaemonSet **не запустится** на них, пока соответствующие `tolerations` не будут явно прописаны администратором в шаблоне пода.

### Сетевое взаимодействие и хостовые пространства имен

Специфика работы системных демонов часто требует глубокой интеграции с операционной системой узла:

*   **`hostNetwork: true`:** Под подключается напрямую к сетевому стеку хоста, минуя виртуальный мост CNI и veth-пары. Необходим для CNI-агентов (Cilium, Calico), сетевых прокси (kube-proxy) и экспортеров метрик узла.
*   **`hostPID: true`:** Контейнер видит таблицу процессов всего узла (PID namespace хоста). Обязательно для агентов профилирования, безопасности (Falco) и экспортеров метрик процессов (Node Exporter).
*   **`hostIPC: true`:** Предоставляет доступ к механизмам межпроцессного взаимодействия хоста (POSIX/SysV IPC, разделяемая память).
*   **`hostPort`:** Привязывает порт контейнера напрямую к указанному порту физического сетевого интерфейса узла. В отличие от `NodePort`, трафик не маршрутизируется через kube-proxy на другие узлы.
    *   *Предупреждение:* Использование `hostPort` блокирует запуск двух подов с одинаковым портом на одном узле, что делает невозможным использование стратегии обновления `maxSurge > 0`.
*   **`internalTrafficPolicy: Local` (GA v1.26):** При создании сервиса типа `ClusterIP` для DaemonSet установка этого параметра заставляет kube-proxy направлять трафик от клиентов **строго на локальный экземпляр пода** на том же узле:
    *   Исключаются сетевые задержки (zero cross-node latency);
    *   Трафик не покидает пределы хоста;
    *   *Внимание:* Если локальный под DaemonSet не готов (`NotReady`), трафик **сбрасывается**, а не пересылается на соседние узлы.

### Хранилища и доступ к хостовой ФС (hostPath и CSI)

Для выполнения задач сбора логов, мониторинга и монтирования дисков DaemonSet использует тома типа `hostPath`:

*   `/var/log` и `/var/log/pods/` — стандартные пути чтения логов контейнеров агентами Fluent Bit, Promtail или Vector.
*   `/proc` и `/sys` — точки монтирования виртуальных файловых систем ядра для сбора аппаратных метрик (Node Exporter).
*   `/run/containerd/containerd.sock` или `/var/run/crio/crio.sock` — сокеты Container Runtime Interface (CRI) для получения метаданных контейнеров и событий безопасности.
*   `/var/lib/kubelet/plugins_registry` и `/var/lib/kubelet/pods` — пути регистрации нодовых драйверов CSI (Container Storage Interface).

> [!WARNING]
> Для предотвращения компрометации файловой системы хоста все тома `hostPath` в системных DaemonSet должны монтироваться с флагом `readOnly: true`, за исключением драйверов CSI и утилит очистки, которым явно требуется запись.

### Стратегии обновления и жизненный цикл (Rollout)

Управление процессом обновления регулируется полем `spec.updateStrategy.type`:

1.  **`RollingUpdate` (режим по умолчанию):** Автоматическая последовательная замена подов при изменении шаблона.
    *   **`maxUnavailable`:** Максимальное число (или процент) подов, которые могут быть недоступны во время обновления (по умолчанию `1`).
    *   **`maxSurge` (GA v1.25):** Максимальное число дополнительных подов, которые контроллер может создать **рядом** со старыми на тех же узлах (по умолчанию `0`).
2.  **`OnDelete`:** Контроллер не обновляет поды автоматически при изменении манифеста. Новый под создается только после того, как администратор вручную завершит старый под (`kubectl delete pod`). Рекомендуется для критических компонентов хранения (Ceph OSD, Longhorn) и сетевых драйверов в продуктовых средах с жесткими регламентами обслуживания.

**Математика и ограничения параметров RollingUpdate:**

| Конфигурация | Поведение на узле | Требования и риски |
| :--- | :--- | :--- |
| `maxUnavailable: 1`, `maxSurge: 0` | Старый под останавливается, узел временно лишается агента, после чего создается новый под. | Минимальный расход ресурсов хоста; окно недоступности мониторинга/логов на 1 узле. |
| `maxUnavailable: 0`, `maxSurge: 1` | Новый под запускается на узле параллельно со старым. Старый удаляется только после перехода нового в `Ready`. | Устраняет «слепые зоны» в мониторинге. **Несовместимо с `hostPort`** (конфликт портов) и требует запаса CPU/RAM на узле. |
| `maxUnavailable: 10%`, `maxSurge: 0` | Групповое обновление порциями по 10% кластера. | Ускоряет раскатку на кластерах от 50+ узлов, но расширяет зону временного простоя сервиса. |

**Вспомогательные параметры контроля выкатки:**
*   **`minReadySeconds`:** Время в секундах, в течение которого новый под должен проработать без сбоев со статусом `Ready`, прежде чем контроллер сочтет его работоспособным и продолжит выкатку на следующие узлы. Предотвращает быструю раскатку битых версий.
*   **`revisionHistoryLimit`:** Глубина хранения ревизий `ControllerRevision` для отката (по умолчанию `10`).

### Управление ресурсами, QoS и PriorityClass

В отличие от пользовательских сервисов, системные демоны не должны вытесняться при нехватке памяти или процессора:

*   **Классы приоритетов (PriorityClass):**
    *   `system-node-critical` — наивысший приоритет в Kubernetes (целочисленное значение `2000001000`). Назначается критическим компонентам узла: CNI (Cilium/Calico), kube-proxy, драйверам дисков CSI.
    *   `system-cluster-critical` — приоритет кластерных служб (`2000000000`). Назначается агентам телеметрии: CoreDNS, Node Exporter, Fluent Bit.
*   **Качество обслуживания (QoS):**
    *   Для критических DaemonSet рекомендуется класс **Guaranteed** (`requests.cpu == limits.cpu` и `requests.memory == limits.memory`).
    *   При классе Guaranteed и приоритете `system-node-critical` процесс получает значение `oom_score_adj = -997`, что практически исключает его завершение ядром Linux при OOM (Out Of Memory) на узле. Подробнее — в [QoS: Requests и Limits](../Scheduling/qos_limit_and_requests.md).

### Взаимодействие с PodDisruptionBudget (PDB) и kubectl drain

Поведение DaemonSet при выводе узла на обслуживание имеет критические отличия от Deployment:

1.  **Поведение при `kubectl drain`:**
    *   Команда `kubectl drain <node>` по умолчанию завершается ошибкой, если обнаруживает поды, управляемые DaemonSet:
        ```text
        error: cannot delete DaemonSet-managed Pods (use --ignore-daemonsets to ignore)
        ```
    *   Для успешного вывода узла администратор **обязан** указать флаг `--ignore-daemonsets`.
    *   При этом поды DaemonSet **не выселяются и продолжают работать** на кордонированном узле, обеспечивая базовую жизнедеятельность (логирование процесса завершения пользовательских подов, работу сети и хранилища).
2.  **Применимость PDB (PodDisruptionBudget):**
    *   Если для DaemonSet создан объект PDB, он **не учитывается** при вызове `kubectl drain --ignore-daemonsets`.
    *   PDB для DaemonSet срабатывает только при прямом вызове Eviction API сторонними утилитами автоматизации без флага игнорирования. На практике создавать PDB с `minAvailable: 100%` для DaemonSet не рекомендуется, так как это блокирует операции выселения. Подробнее — в [Обслуживание узлов (Cordon/Drain)](../Operations/node_maintenance.md).

---

## Практические сценарии и конфигурация

### Сценарий 1: Агент мониторинга хоста (Prometheus Node Exporter)

Промышленный манифест развертывания Node Exporter на bare-metal кластере с выделенной сервисной учетной записью, минимальными правами RBAC, прямым доступом к сети хоста и допуском на управляющие узлы (`control-plane`).

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: monitoring
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: node-exporter-sa
  namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: node-exporter-role
rules:
- apiGroups: [""]
  resources: ["nodes/metrics"]
  verbs: ["get"]
- nonResourceURLs: ["/metrics"]
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: node-exporter-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: node-exporter-role
subjects:
- kind: ServiceAccount
  name: node-exporter-sa
  namespace: monitoring
---
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-exporter
  namespace: monitoring
  labels:
    app.kubernetes.io/name: node-exporter
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: node-exporter
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
      maxSurge: 0
  minReadySeconds: 5
  template:
    metadata:
      labels:
        app.kubernetes.io/name: node-exporter
    spec:
      serviceAccountName: node-exporter-sa
      hostNetwork: true
      hostPID: true
      priorityClassName: system-cluster-critical
      tolerations:
      - key: node-role.kubernetes.io/control-plane
        operator: Exists
        effect: NoSchedule
      - key: node-role.kubernetes.io/master
        operator: Exists
        effect: NoSchedule
      containers:
      - name: node-exporter
        image: quay.io/prometheus/node-exporter:v1.9.0
        args:
        - --path.procfs=/host/proc
        - --path.sysfs=/host/sys
        - --path.rootfs=/host/root
        - --no-collector.wifi
        - --no-collector.hwmon
        - --collector.filesystem.mount-points-exclude=^/(dev|proc|sys|var/lib/docker/.+|var/lib/kubelet/.+)($|/)
        ports:
        - name: metrics
          containerPort: 9100
          hostPort: 9100
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 250m
            memory: 256Mi
        securityContext:
          readOnlyRootFilesystem: true
          runAsNonRoot: true
          runAsUser: 65534
        volumeMounts:
        - name: proc
          mountPath: /host/proc
          readOnly: true
        - name: sys
          mountPath: /host/sys
          readOnly: true
        - name: root
          mountPath: /host/root
          readOnly: true
          mountPropagation: HostToContainer
      volumes:
      - name: proc
        hostPath:
          path: /proc
      - name: sys
        hostPath:
          path: /sys
      - name: root
        hostPath:
          path: /
```

**Проверка развертывания и валидация:**

```bash
# Применение манифеста
kubectl apply -f node-exporter.yaml
# → namespace/monitoring unchanged
# → serviceaccount/node-exporter-sa created
# → clusterrole.rbac.authorization.k8s.io/node-exporter-role created
# → clusterrolebinding.rbac.authorization.k8s.io/node-exporter-binding created
# → daemonset.apps/node-exporter created

# Ожидание завершения раскатки по всем узлам
kubectl rollout status ds/node-exporter -n monitoring --timeout=60s
# → daemon set "node-exporter" successfully rolled out

# Проверка покрытия узлов
kubectl get ds -n monitoring
# → NAME            DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR   AGE
# → node-exporter   3         3         3       3            3           <none>          45s

# Проверка локального сбора метрик с пода
kubectl -n monitoring exec -it ds/node-exporter -c node-exporter -- wget -qO- http://127.0.0.1:9100/metrics | head -n 5
# → # HELP go_gc_duration_seconds A summary of the pause duration of garbage collection cycles.
# → # TYPE go_gc_duration_seconds summary
```

### Сценарий 2: Агент сбора логов (Fluent Bit с корректным завершением)

Конфигурация агента сбора логов контейнеров. Ключевые аспекты: чтение логов из `/var/log/pods`, монтирование метаданных контейнеров, повышенный приоритет и увеличенный `terminationGracePeriodSeconds` для гарантированного сброса (flush) буферов логов перед остановкой пода.

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: fluent-bit
  namespace: kube-system
  labels:
    app.kubernetes.io/name: fluent-bit
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: fluent-bit
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
      maxSurge: 0
  template:
    metadata:
      labels:
        app.kubernetes.io/name: fluent-bit
    spec:
      terminationGracePeriodSeconds: 30
      priorityClassName: system-node-critical
      tolerations:
      - key: node-role.kubernetes.io/control-plane
        operator: Exists
        effect: NoSchedule
      containers:
      - name: fluent-bit
        image: fluent/fluent-bit:3.2.4
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 512Mi
        volumeMounts:
        - name: varlog
          mountPath: /var/log
          readOnly: true
        - name: varlibdockercontainers
          mountPath: /var/lib/docker/containers
          readOnly: true
        - name: fluent-bit-config
          mountPath: /fluent-bit/etc/
      volumes:
      - name: varlog
        hostPath:
          path: /var/log
      - name: varlibdockercontainers
        hostPath:
          path: /var/lib/docker/containers
      - name: fluent-bit-config
        configMap:
          name: fluent-bit-config
```

### Сценарий 3: Локальная маршрутизация через Service с `internalTrafficPolicy: Local`

Сценарий развертывания локального кэширующего DNS-прокси или In-Memory хранилища (например, node-local кэш), где клиенты с того же узла обращаются к сервису без межузловых задержек.

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: local-cache
  namespace: default
  labels:
    app: local-cache
spec:
  selector:
    matchLabels:
      app: local-cache
  template:
    metadata:
      labels:
        app: local-cache
    spec:
      containers:
      - name: cache
        image: redis:7.4-alpine
        command: ["redis-server", "--protected-mode", "no", "--port", "6379"]
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
          limits:
            cpu: 200m
            memory: 256Mi
        ports:
        - name: redis
          containerPort: 6379
---
apiVersion: v1
kind: Service
metadata:
  name: local-cache-service
  namespace: default
spec:
  type: ClusterIP
  internalTrafficPolicy: Local   # ← гарантирует маршрутизацию только на локальный под
  selector:
    app: local-cache
  ports:
  - name: redis
    port: 6379
    targetPort: 6379
```

**Проверка локализации трафика:**

```bash
# Проверяем эндпоинты сервиса: каждый узел получает свой локальный EndpointSlice
kubectl get endpoints local-cache-service
# → NAME                  ENDPOINTS                               AGE
# → local-cache-service   10.244.1.15:6379,10.244.2.8:6379,...   2m

# Запрос с пода приложения попадает строго на Redis, запущенный на ТОМ ЖЕ физическом узле
kubectl run test-client --rm -it --image=redis:7.4-alpine -- redis-cli -h local-cache-service ping
# → PONG
```

### Сценарий 4: Канареечное обновление (Canary Rollout) на подмножестве узлов

Когда требуется обновить критический DaemonSet (например, сетевой CNI-плагин или агент безопасности) сначала на тестовой группе серверов, стандартный `RollingUpdate` не дает пошагового контроля. Решение — канареечное разделение через `nodeAffinity`:

1.  **Разметка канареечного узла:**
    ```bash
    kubectl label node worker-1 maintenance-tier=canary
    # → node/worker-1 labeled
    ```
2.  **Создание временного Canary-DaemonSet** (обрабатывает только узлы с меткой `maintenance-tier=canary`):
    ```yaml
    apiVersion: apps/v1
    kind: DaemonSet
    metadata:
      name: security-agent-canary
      namespace: kube-system
    spec:
      selector:
        matchLabels:
          app: security-agent
          tier: canary
      template:
        metadata:
          labels:
            app: security-agent
            tier: canary
        spec:
          affinity:
            nodeAffinity:
              requiredDuringSchedulingIgnoredDuringExecution:
                nodeSelectorTerms:
                - matchExpressions:
                  - key: maintenance-tier
                    operator: In
                    values: ["canary"]
          containers:
          - name: agent
            image: internal-repo/sec-agent:v2.4.0
    ```
3.  **Исключение канареечных узлов из основного DaemonSet:**
    В основном DaemonSet добавляется условие `operator: NotIn, values: ["canary"]`. После успешного тестирования канареечный манифест удаляется, а основной DaemonSet обновляется до `v2.4.0` на всем кластере.

### Сценарий 5: Альтернатива DaemonSet — Pod Anti-Affinity в Deployment

Если сервис должен запускаться «не более одного экземпляра на узел», но общее число экземпляров ограничено (например, пул из 3 кэширующих серверов на кластер из 20 узлов), DaemonSet не подходит. Используется [Deployment](./Deployment/index.md) с правилом `podAntiAffinity`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: exclusive-cache
  namespace: default
spec:
  replicas: 3
  selector:
    matchLabels:
      app: exclusive-cache
  template:
    metadata:
      labels:
        app: exclusive-cache
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
              - key: app
                operator: In
                values: ["exclusive-cache"]
            topologyKey: "kubernetes.io/hostname"
      containers:
      - name: redis
        image: redis:7.4-alpine
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
```

---

## Операции и команды

### Справочник команд kubectl

```bash
# 1. Просмотр всех DaemonSet в пространстве имен с ключевыми счетчиками
kubectl get daemonsets -n kube-system
# → NAME         DESIRED  CURRENT  READY  UP-TO-DATE  AVAILABLE  NODE SELECTOR  AGE
# → cilium       3        3        3      3           3          <none>         40d
# → kube-proxy   3        3        3      3           3          <none>         40d

# 2. Детальное состояние: условия, селекторы, события планировщика
kubectl describe daemonset node-exporter -n monitoring

# 3. Список подов конкретного DaemonSet с отображением узлов размещения
kubectl get pods -n monitoring -l app.kubernetes.io/name=node-exporter -o wide
# → NAME                  READY  STATUS   RESTARTS  AGE  IP           NODE
# → node-exporter-4z8qx   1/1    Running  0         1h   192.168.1.10 worker-1
# → node-exporter-9x7lp   1/1    Running  0         1h   192.168.1.11 worker-2
# → node-exporter-k2m8b   1/1    Running  0         1h   192.168.1.12 master-1

# 4. Проверка наличия пода DaemonSet на конкретном целевом узле
kubectl get pods -A --field-selector spec.nodeName=worker-1 -l app.kubernetes.io/name=node-exporter
# → NAMESPACE    NAME                  READY   STATUS    RESTARTS   AGE
# → monitoring   node-exporter-4z8qx   1/1     Running   0          1h

# 5. Экспорт манифеста live-объекта в формате YAML для анализа
kubectl get ds node-exporter -n monitoring -o yaml
```

### Поля секции status объекта DaemonSet

При мониторинге и траблшутинге вывод команды `kubectl get ds <name> -o yaml` содержит секцию `status`:

| Поле статуса | Тип | Назначение и интерпретация |
| :--- | :--- | :--- |
| `desiredNumberScheduled` | int | Общее число узлов, которые соответствуют селекторам и должны содержать под. |
| `currentNumberScheduled` | int | Число узлов, на которых уже запущен хотя бы один под данного DaemonSet. |
| `updatedNumberScheduled` | int | Число подов, обновленных до актуальной ревизии шаблона (`spec.template`). |
| `numberAvailable` | int | Число подов в статусе `Ready`, прошедших период `minReadySeconds`. |
| `numberReady` | int | Число подов, успешно прошедших проверку Readiness Probe. |
| `numberUnavailable` | int | Разность: `desiredNumberScheduled - numberAvailable`. В стабильном состоянии равно `0`. |
| `numberMisscheduled` | int | Число подов, запущенных на узлах, которые **не должны** их содержать. Требует вмешательства. |
| `collisionCount` | int | Количество коллизий при вычислении хеша для `ControllerRevision`. |

### Управление процессом выкатки (Rollout)

```bash
# Отслеживание хода выполнения выкатки в реальном времени
kubectl rollout status ds/node-exporter -n monitoring
# → Waiting for daemon set "node-exporter" rollout to finish: 1 of 3 updated pods are available...
# → daemon set "node-exporter" successfully rolled out

# Просмотр истории ревизий ControllerRevision
kubectl rollout history ds/node-exporter -n monitoring
# → daemonset.apps/node-exporter
# → REVISION  CHANGE-CAUSE
# → 1         <none>
# → 2         kubectl set image ds/node-exporter node-exporter=quay.io/prometheus/node-exporter:v1.9.0

# Откат к предыдущей ревизии (Rollback)
kubectl rollout undo ds/node-exporter -n monitoring --to-revision=1
# → daemonset.apps/node-exporter rolled back

# Перезапуск всех подов (полезно при обновлении внешних ConfigMap или Secret)
kubectl rollout restart ds/node-exporter -n monitoring
# → daemonset.apps/node-exporter restarted
```

---

## Диагностика и устранение неполадок

### Матрица типовых проблем и решений

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| Узел находится в `Ready`, но под DaemonSet на нем не создается | На узле установлен `Taint`, для которого в шаблоне пода отсутствует `Toleration`; ошибка в `nodeSelector` / `nodeAffinity` | Выполнить `kubectl describe node <node> \| grep Taints`. Сверить список taints с секцией `tolerations` в манифесте DaemonSet. Проверить метки узла: `kubectl get node <node> --show-labels`. |
| Под переходит в состояние `Pending` со сбоем планировщика | Недостаточно свободных ресурсов (CPU/RAM) на узле под запросы `resources.requests`; конфликт портов | Выполнить `kubectl describe pod <pod-name>`. В секции `Events` найти причину: `0/3 nodes are available: 1 Insufficient cpu, 1 node(s) didn't have free ports for the requested pod_ports`. Уменьшить `requests` или освободить порт. |
| Контейнер падает в `CrashLoopBackOff` | Не хватает прав доступа (RBAC `403 Forbidden`); ошибка монтирования `hostPath`; конфликт порта на узле | 1. Проверить логи: `kubectl logs <pod-name> -n <ns>`.<br>2. Проверить права: `kubectl auth can-i get nodes/metrics --as=system:serviceaccount:<ns>:<sa>`.<br>3. Проверить сокет/директорию на хосте: `ls -la /var/log/pods`. |
| Процесс обновления `RollingUpdate` завис | Значение `maxUnavailable: 0` при `maxSurge: 0`; новый под на одном из узлов не проходит Readiness Probe | 1. Проверить `kubectl get ds <name> -o yaml` (поля `updatedNumberScheduled` vs `desiredNumberScheduled`).<br>2. Найти проблемный под: `kubectl get pods -l <selector> \| grep -v Running`.<br>3. Устранить ошибку контейнера или временно увеличить `maxUnavailable: 1`. |
| Ошибка планирования: `port collision` при `maxSurge > 0` | В спецификации пода задан `hostPort`, а стратегия обновления использует `maxSurge: 1` | Два пода не могут слушать один порт на одном узле. Установить `maxSurge: 0` и `maxUnavailable: 1` в `spec.updateStrategy.rollingUpdate`. |
| Появились поды в статусе `numberMisscheduled > 0` | Изменились метки на рабочих узлах, но контроллер еще не успел очистить старые поды; ручное удаление меток | Проверить соответствие меток узлов селекторам DaemonSet. Поды на неподходящих узлах будут автоматически удалены контроллером либо удаляются вручную (`kubectl delete pod <pod>`). |
| Ошибка выполнения `kubectl drain`: процесс блокирован | Команда `kubectl drain` вызвана без обязательного флага `--ignore-daemonsets` | Повторить команду с флагом: `kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data`. Подробнее — в [Обслуживание узлов (Cordon/Drain)](../Operations/node_maintenance.md). |
| Под завис в состоянии `Terminating` при удалении | Зависший unmount сетевого тома; заблокированный `preStop` хук; узел физически выключен | Проверить финализаторы и состояние хоста. Подробный алгоритм — в [Диагностика зависания Pod Terminating](../Troubleshooting/Common_Errors/PodTerminating/daemonset_termination.md). |

### Пошаговый алгоритм расследования инцидентов

```
[Алерт: DaemonSet не покрывает все узлы]
                     │
                     ▼
1. Проверить общий статус контроллера:
   kubectl describe ds <name> -n <ns>
   (Смотрим секции: Events, Conditions, Desired/Current)
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
   [Поды не созданы]       [Поды в Pending/Crash]
         │                       │
         ▼                       ▼
2. Проверить пригодность  3. Проверить Events и логи пода:
   узлов:                    kubectl describe pod <pod>
   - kubectl get nodes       kubectl logs <pod> --previous
   - Taints узлов            - Нехватка CPU/RAM (Insufficient)
   - Соответствие labels     - Конфликт портов (hostPort)
   - Cordon статус узла      - Ошибки доступа к hostPath
```

---

## Мониторинг и наблюдаемость (SRE/DevOps)

Для мониторинга DaemonSet критически важно отслеживать не просто количество живых подов, а **полноту покрытия инфраструктуры** (`desiredNumberScheduled`) и **отсутствие ошибок раскатки** (`numberUnavailable`). Потеря системного агента (например, логов или CNI) на одном узле может долго оставаться незамеченной без правильных алертов.

### Метрики kube-state-metrics

Компонент `kube-state-metrics` экспортирует стандартные метрики состояния DaemonSet с префиксом `kube_daemonset_`:

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `kube_daemonset_status_desired_number_scheduled` | Gauge | Целевое количество подов (число подходящих узлов кластера). |
| `kube_daemonset_status_current_number_scheduled` | Gauge | Текущее количество запущенных подов на узлах. |
| `kube_daemonset_status_number_ready` | Gauge | Количество подов в состоянии `Ready`. |
| `kube_daemonset_status_number_available` | Gauge | Количество доступных подов (прошедших `minReadySeconds`). |
| `kube_daemonset_status_number_unavailable` | Gauge | Разница между `desired` и `available`. **Основная метрика для алертинга**. |
| `kube_daemonset_status_number_misscheduled` | Gauge | Количество подов, ошибочно работающих на неподходящих узлах. |
| `kube_daemonset_status_updated_number_scheduled` | Gauge | Количество подов на самой актуальной версии шаблона. |
| `kube_daemonset_metadata_generation` | Gauge | Поколение метаданных объекта (растет при изменении `spec`). |

### Правила алертинга Prometheus (PrometheusRule)

Готовый набор алертов для Prometheus / VictoriaMetrics для выявления неполного покрытия узлов и зависших раскаток:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: daemonset-alerts
  namespace: monitoring
  labels:
    role: alert-rules
spec:
  groups:
  - name: daemonset.rules
    rules:
    # 1. Системный агент отсутствует на одном или нескольких узлах
    - alert: DaemonSetPodsUnavailable
      expr: |
        kube_daemonset_status_number_unavailable{namespace!=""} > 0
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Поды DaemonSet недоступны на узлах"
        description: "В DaemonSet {{ $labels.namespace }}/{{ $labels.daemonset }} недоступно {{ $value }} подов из {{ printf \"kube_daemonset_status_desired_number_scheduled{namespace='%s', daemonset='%s'}\" $labels.namespace $labels.daemonset | query | first | value }} требуемых более 10 минут."

    # 2. Обновление DaemonSet зависло
    - alert: DaemonSetRolloutStuck
      expr: |
        (
          kube_daemonset_status_desired_number_scheduled{namespace!=""}
          -
          kube_daemonset_status_updated_number_scheduled{namespace!=""}
        ) > 0
      for: 20m
      labels:
        severity: warning
      annotations:
        summary: "Зависло обновление DaemonSet"
        description: "Обновление DaemonSet {{ $labels.namespace }}/{{ $labels.daemonset }} не может завершиться в течение 20 минут. Не обновлено подов: {{ $value }}."

    # 3. Поды размещены на неподходящих узлах
    - alert: DaemonSetMisscheduled
      expr: |
        kube_daemonset_status_number_misscheduled{namespace!=""} > 0
      for: 15m
      labels:
        severity: warning
      annotations:
        summary: "Поды DaemonSet работают на некорректных узлах"
        description: "В DaemonSet {{ $labels.namespace }}/{{ $labels.daemonset }} обнаружено {{ $value }} ошибочно размещенных подов (misscheduled)."
```

### Автоматизированная валидация в CI/CD

В пайплайнах непрерывного развертывания (GitOps, CI/CD) применение манифеста через `kubectl apply` является асинхронной операцией. Для блокировки пайплайна до подтверждения успешной раскатки на всех физических узлах используйте:

```bash
# Валидация выкатки в shell-скрипте пайплайна
kubectl apply -f daemonset.yaml
kubectl rollout status daemonset/<name> -n <namespace> --timeout=300s
# → exit code 0 при успехе, non-zero при таймауте
```

---

## Лучшие практики (Best Practices)

1.  **Всегда задавайте PriorityClass:**
    *   Сетевые агенты (CNI, kube-proxy), хранилища (CSI): используйте `system-node-critical`.
    *   Агенты мониторинга и сбора логов (Node Exporter, Fluent Bit): используйте `system-cluster-critical`.
    *   Это гарантирует, что системные демоны не будут вытеснены прикладными подами при всплеске нагрузки.
2.  **Гарантируйте качество обслуживания (QoS Guaranteed):**
    *   Задавайте равные значения `requests` и `limits` по памяти для критических демонов (`limits.memory == requests.memory`). Это снижает `oom_score_adj` и защищает демон от завершения Linux OOM-killer.
3.  **Используйте фиксированные теги образов:**
    *   Никогда не используйте тег `:latest` в производственных DaemonSet. Фиксируйте точную версию (например, `v1.9.0`) или sha256-дайджест для воспроизводимости среды.
4.  **Настраивайте Graceful Shutdown:**
    *   Для агентов с буферизацией (сборщики логов, телеметрия) задавайте достаточный `terminationGracePeriodSeconds: 30` (или `60`) и настраивайте сброс буферов по сигналу `SIGTERM` или через хук `preStop`.
5.  **Осторожно используйте `maxSurge`:**
    *   Если под использует `hostPort` или подключается к уникальному сокету на хосте, параметр `maxSurge` **обязан быть равен 0**. Установка `maxSurge: 1` приведет к ошибке конфликта портов на узле.
6.  **Монтируйте тома `hostPath` в режиме `readOnly`:**
    *   За исключением драйверов CSI и компонентов записи, все пути хоста (`/proc`, `/sys`, `/var/log`) должны монтироваться исключительно в режиме только для чтения (`readOnly: true`).
7.  **Принцип наименьших привилегий (RBAC):**
    *   Никогда не используйте служебный аккаунт `default` или роль `cluster-admin`. Создавайте выделенный `ServiceAccount` с точечным набором разрешений (например, только чтение `nodes/metrics` и `pods/log`).
8.  **Разделяйте DaemonSet для смешанных платформ:**
    *   Если в кластере присутствуют разные аппаратные архитектуры (`amd64` и `arm64`) или разные ОС (Linux и Windows), создавайте отдельные манифесты DaemonSet с фильтрацией через `nodeSelector` (`kubernetes.io/arch` и `kubernetes.io/os`), настраивая специфичные параметры запуска для каждой платформы.

---

## Дополнительная информация

### Сравнение: DaemonSet vs Static Pods

При проектировании архитектуры развертывания системных сервисов на уровне хоста системные администраторы выбирают между **DaemonSet** и **Static Pods**:

| Критерий | DaemonSet | Static Pods (Статические поды) |
| :--- | :--- | :--- |
| **Управление** | API-сервер Kubernetes (`apps/v1`). | Напрямую локальным агентом `kubelet` узла. |
| **Расположение манифестов** | В базе `etcd` кластера; управление через `kubectl`/GitOps. | Локальные файлы на хосте (обычно `/etc/kubernetes/manifests/`). |
| **Планирование** | Стандартный `kube-scheduler` (учитывает ресурсы, taints, priorities). | `kubelet` запускает под безусловно, в обход планировщика. |
| **Зависимость от Control Plane** | Требует работоспособности API-сервера и сети кластера. | Запускается даже при полностью отключенном Control Plane. |
| **Стратегии обновления** | Автоматизированный `RollingUpdate` (`maxUnavailable`, `maxSurge`). | Ручное изменение файлов манифестов на каждом хосте. |
| **Типовые сценарии** | CNI, Node Exporter, Fluent Bit, Falco, CSI-агенты. | Компоненты ядра k8s: `etcd`, `kube-apiserver`, `kube-controller-manager`, `kube-scheduler`. |

### См. также

*   **[Обслуживание узлов (Cordon/Drain)](../Operations/node_maintenance.md)** — регламент вывода серверов из эксплуатации и специфика работы флага `--ignore-daemonsets`.
*   **[Taints и Tolerations](../Scheduling/taints_and_tolerations.md)** — механизмы изоляции узлов и правила работы стандартных системных taints.
*   **[Affinity и Anti-Affinity](../Scheduling/affinity.md)** — правила селекции узлов через `nodeAffinity` и топологическое распределение.
*   **[QoS: Requests и Limits](../Scheduling/qos_limit_and_requests.md)** — классы качества обслуживания и защита системных процессов от OOM-killer.
*   **[RBAC: роли и права доступа](../Security/rbac/roles.md)** — настройка безопасных ролей для системных демонов.
*   **[Security Context пода](../Security/pod_security_context.md)** — параметры хостовых пространств имен (`hostNetwork`, `hostPID`) и привилегий.
*   **[Архитектура мониторинга и логирования](../MonitoringLogging/kubernetes-monitoring-logging-architecture.md)** — комплексный стек наблюдаемости на базе Prometheus и логов.
*   **[Диагностика зависания Pod Terminating](../Troubleshooting/Common_Errors/PodTerminating/daemonset_termination.md)** — решение проблем с финализаторами и зависшими подами DaemonSet.
*   **[Диагностика Pod Pending](../Troubleshooting/Common_Errors/pod_pending/diagnostics.md)** — устранение ошибок планирования и дефицита ресурсов на узлах.
*   **[Жизненный цикл Pod](./Pod/pod_lifecycle_and_state.md)** — стадии состояний контейнеров и хуки завершения.
*   **[Управление Deployment](./Deployment/index.md)** — базовый контроллер реплицированных нагрузок.
