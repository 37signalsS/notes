# Масштабирование StatefulSet: HPA, KEDA и архитектурные паттерны

**Актуально для:** Kubernetes 1.30+ / KEDA 2.14+

## Определения

**StatefulSet** — контроллер рабочей нагрузки Kubernetes (`apps/v1`), управляющий развертыванием группы подов с предоставлением уникальных неизменяемых сетевых идентификаторов, детерминированных порядковых номеров (ordinals) и выделенных постоянных томов (PersistentVolumeClaims). Применяется для stateful-систем: баз данных, брокеров сообщений, распределенных хранилищ и шардированных сервисов с локальным состоянием.

**Подресурс `/scale`** — стандартная конечная точка Kubernetes API, предоставляющая унифицированный интерфейс для чтения и модификации числа реплик (`spec.replicas`) ресурса без необходимости прямого изменения всего манифеста. Контроллер StatefulSet реализует интерфейс `/scale`, что делает его совместимым с внешними автоскейлерами.

**Horizontal Pod Autoscaler (HPA)** — встроенный контроллер Kubernetes (`autoscaling/v2`), который опрашивает метрики утилизации ресурсов (`metrics.k8s.io`) или кастомные метрики (`custom.metrics.k8s.io`) и автоматически изменяет количество реплик в подресурсе `/scale`.

**KEDA (Kubernetes Event-driven Autoscaling)** — расширение Kubernetes для событийного автомасштабирования. Опрашивает внешние источники событий (очереди RabbitMQ, топики Kafka, базы данных, метрики Prometheus) и управляет масштабированием нагрузки, транслируя правила в нативные объекты HPA или напрямую через `/scale`.

**`podManagementPolicy`** — спецификация StatefulSet (`OrderedReady` по умолчанию или `Parallel`), определяющая последовательность создания, проверки готовности и завершения работы подов при изменении количества реплик.

**`persistentVolumeClaimRetentionPolicy`** — директива спецификации StatefulSet (GA в Kubernetes 1.32), определяющая жизненный цикл автоматически созданных томов PVC (`Retain` или `Delete`) при масштабировании вниз (`whenScaled`) и при удалении контроллера (`whenDeleted`).

**PodDisruptionBudget (PDB)** — объект Kubernetes API (`policy/v1`), ограничивающий количество одновременно недоступных подов при добровольных прерываниях (плановые выселения, дренаж узлов `kubectl drain`).

**Graceful Scale-Down** — управляемый процесс остановки реплики stateful-нагрузки, включающий вывод пода из балансировки, завершение активных операций, синхронизацию или сброс локального состояния на диск/в кластер через хук `preStop` до истечения `terminationGracePeriodSeconds`.

---

## Базовые концепции и архитектура

### Архитектурные вызовы автомасштабирования StatefulSet

Автоматическое масштабирование StatefulSet кардинально сложнее масштабирования stateless-нагрузок (Deployment) из-за фундаментальных ограничений контроллера и природы сохраняемого состояния:

| Характеристика | Deployment | StatefulSet | Влияние на автомасштабирование |
|---|---|---|---|
| **Именование подов** | Случайный хэш (`web-67df9-xyz`) | Детерминированный индекс (`db-0`, `db-1`, `db-N`) | Поды не взаимозаменяемы; идентификатор несет смысловую нагрузку в кластере |
| **Связка с хранилищем** | Общие тома (`ReadWriteMany`) или эфемерные (`emptyDir`) | Индивидуальный PVC на каждый под (`volumeClaimTemplates`) | При скейле создаются новые PV/PVC; при дескейле тома остаются или требуют очистки |
| **Порядок завершения (Scale-Down)** | Произвольный выбор подов (с учетом доступности нод) | Строгий LIFO: от наибольшего индекса к наименьшему (`N-1` → `0`) | Нельзя удалить произвольный «простаивающий» под; удаляется строго последний порядковый номер |
| **Инициализация (Scale-Up)** | Параллельный запуск всех запрошенных реплик | По умолчанию строгая последовательность (`pod-N` ждет Ready `pod-N-1`) | Реакция на всплеск нагрузки замедлена временем прогрева каждого пода |
| **Сетевые адреса** | Случайные IP через виртуальный сервис `ClusterIP` | Стабильные DNS-записи Headless Service (`pod-0.svc.ns`) | Пиры в кластере адресуют конкретный под напрямую по DNS-имени |

### Поведение `podManagementPolicy`: OrderedReady против Parallel

Поведение контроллера StatefulSet при изменении `spec.replicas` определяется полем `.spec.podManagementPolicy`:

```
OrderedReady (по умолчанию):
Scale-Up:   [pod-0 Ready] ──► [pod-1 Ready] ──► [pod-2 Ready] (медленный старт)
Scale-Down: [pod-2 Terminated] ──► [pod-1 Terminated] ──► [pod-0] (последовательный стоп)

Parallel:
Scale-Up:   [pod-0], [pod-1], [pod-2] запускаются ОДНОВРЕМЕННО
Scale-Down: [pod-2], [pod-1] останавливаются ОДНОВРЕМЕННО (быстрый скейл)
```

1. **`OrderedReady`**:
   - Применяется, когда запуск нового участника требует гарантии стабильности предыдущих (например, пошаговая инициализация кластера).
   - **Проблема для HPA:** Если прогрев и синхронизация данных пода занимают несколько минут, HPA не сможет оперативно компенсировать пиковую нагрузку.
2. **`Parallel`**:
   - Контроллер запускает или останавливает все недостающие/лишние поды параллельно, не дожидаясь перехода соседей в состояние `Ready`.
   - **Рекомендация для автомасштабируемых пулов:** Если поды представляют собой независимые читающие реплики или независимые обработчики очередей, установка `podManagementPolicy: Parallel` критически необходима для предсказуемого отклика автоскейлера.

### Жизненный цикл томов при Scale-Down: `persistentVolumeClaimRetentionPolicy`

До появления механизма `persistentVolumeClaimRetentionPolicy` (GA с Kubernetes 1.32) уменьшение количества реплик StatefulSet гарантированно приводило к появлению «осиротевших» (orphaned) PVC:

- Если `replicas` уменьшалось с 5 до 2, поды `db-4`, `db-3`, `db-2` удалялись, но диски `data-db-4`, `data-db-3`, `data-db-2` оставались подключенными к storage-пулу (Ceph, SAN, Local PV).
- При последующем росте нагрузки (`replicas=5`) поды `db-2`, `db-3`, `db-4` переподключались к своим старым томам со старыми данными.

Настройка `.spec.persistentVolumeClaimRetentionPolicy` позволяет централизованно управлять этим поведением:

```yaml
spec:
  persistentVolumeClaimRetentionPolicy:
    whenDeleted: Retain # Судьба PVC при полном удалении StatefulSet
    whenScaled: Delete  # Судьба PVC при уменьшении числа реплик (HPA scale-down)
```

- **`whenScaled: Retain` (безопасный режим, значение по умолчанию):** Тома сохраняются. Защищает от потери данных, если дескейл произошел по ошибке или временно. Минус: риск исчерпания дискового пространства в SAN/Ceph из-за накапливающихся неиспользуемых PVC.
- **`whenScaled: Delete` (режим пула кэшей/воркеров):** Контроллер автоматически удаляет ассоциированный PVC после завершения работы пода. Применимо только тогда, когда данные на диске являются эфемерным кэшем или подтягиваются из центрального хранилища при старте.

### Ограничения консенсусных и кворумных систем (Антипаттерн)

> [!CAUTION]
> Категорически запрещено подключать HPA или KEDA напрямую к StatefulSet, реализующим кворумные алгоритмы распределенного консенсуса (etcd, Raft, ZooKeeper, ClickHouse Keeper, RabbitMQ Quorum Queues, Elasticsearch Master Nodes).

Причины:
1. **Нарушение кворума:** Кворум требует строгого правила $Q = \lfloor N/2 \rfloor + 1$. Четное количество узлов снижает отказоустойчивость кластера.
2. **Риск Split-Brain и потери кворума при Scale-Down:** Если HPA инициирует scale-down в момент сетевой нестабильности или перегрузки, удаление подов с конца может уничтожить кворумное большинство, переведя кластер в состояние Read-Only или вызвав аварийную остановку.
3. **Требование явной переконфигурации membership:** Добавление или удаление узла Raft/etcd требует регистрации узла на уровне протокола приложения (`member add`, `member remove`), о чем Kubernetes `/scale` ничего не знает.

### Допустимые архитектурные паттерны масштабирования

Для надежного масштабирования stateful-систем в SRE-практике применяются три паттерна:

```
[Клиентский трафик на запись] ──► [Primary (StatefulSet, replicas: 1 или фиксированный кворум)]
                                            │
                                  (Стриминг репликации WAL)
                                            ▼
[Клиентский трафик на чтение] ──► [Read-Only Pool (StatefulSet, HPA / KEDA)]
                                  ├── replica-0 (PVC-0)
                                  ├── replica-1 (PVC-1)
                                  └── replica-N (PVC-N) [Автомасштабирование]
```

#### Паттерн 1: Split StatefulSet (Разделение на Master и Read-Only Replicas)
- **Primary / Master:** Отдельный `StatefulSet` с фиксированным количеством реплик (`replicas: 1` или отказоустойчивая пара), управляемый оператором (например, Patroni, CloudNativePG) **без HPA**.
- **Read Replicas:** Отдельный `StatefulSet` с `podManagementPolicy: Parallel`, подключенный к HPA/KEDA по метрикам CPU, памяти или RPS на чтение.

#### Паттерн 2: Partitioned State / Stream Workers
- Воркеры обработки потоков (Kafka, RabbitMQ, Celery), которым требуется выделенный локальный SSD-кэш (например, локальная база RocksDB, кэш ML-моделей или сегментов медиафайлов) и уникальный `pod-index` для партиционирования.
- Масштабируются через KEDA по метрике лага очередей.

#### Паттерн 3: Вертикальное масштабирование (VPA) для монолитных БД
- Если архитектура базы данных не поддерживает горизонтальное добавление узлов на лету, применяется [Vertical Pod Autoscaler (VPA)](vpa_detailed.md) в связке с [In-Place Pod Resize](in_place_pod_resize.md), изменяющий `requests/limits` CPU и Memory без пересоздания подов и томов.

---

## Практические сценарии и конфигурация

### Требования к инфраструктуре

| Компонент | Минимальная версия | Назначение |
|---|---|---|
| **Kubernetes** | 1.30+ (1.32+ для стабильного `whenScaled`) | Среда исполнения контейнеров и оркестрация |
| **CSI Driver** | CSI 1.5+ с поддержкой Dynamic Provisioning | Выделение томов (Ceph RBD, OpenEBS, Local Storage Operator) |
| **Metrics Server** | 0.7.0+ | Поставка базовых системных метрик для HPA (`metrics.k8s.io`) |
| **Prometheus Adapter / KEDA** | Prometheus 2.50+ / KEDA 2.14+ | Поставка кастомных и внешних метрик |

### Сценарий 1: HPA для пула Read-Only реплик с защитой от флаппинга

Конфигурация StatefulSet для пула читающих реплик базы данных и HPA с консервативной политикой `scaleDown`, предотвращающей частое пересоздание тяжелых подов.

#### Манифест StatefulSet (`read-replicas-sts.yaml`)

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres-read-pool
  namespace: database
  labels:
    app.kubernetes.io/name: postgres-read-pool
spec:
  serviceName: postgres-read-service
  podManagementPolicy: Parallel
  replicas: 2
  persistentVolumeClaimRetentionPolicy:
    whenDeleted: Retain
    whenScaled: Retain
  selector:
    matchLabels:
      app.kubernetes.io/name: postgres-read-pool
  template:
    metadata:
      labels:
        app.kubernetes.io/name: postgres-read-pool
    spec:
      terminationGracePeriodSeconds: 180
      containers:
        - name: postgresql
          image: postgres:16.4-alpine
          resources:
            requests:
              cpu: 1000m
              memory: 2Gi
            limits:
              cpu: 2000m
              memory: 4Gi
          ports:
            - containerPort: 5432
              name: postgresql
          lifecycle:
            preStop:
              exec:
                command:
                  - /bin/sh
                  - -c
                  - |
                    # Вывод пода из балансировки и ожидание завершения читающих транзакций
                    touch /tmp/draining
                    sleep 30
                    pg_ctl -D /var/lib/postgresql/data stop -m fast
          readinessProbe:
            exec:
              command:
                - /bin/sh
                - -c
                - test ! -f /tmp/draining && pg_isready -h 127.0.0.1 -p 5432
            initialDelaySeconds: 15
            periodSeconds: 5
            failureThreshold: 2
          volumeMounts:
            - name: pgdata
              mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
    - metadata:
        name: pgdata
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: fast-rbd
        resources:
          requests:
            storage: 50Gi
```

#### Манифест HPA с расширенной политикой `behavior` (`read-replicas-hpa.yaml`)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: postgres-read-pool-hpa
  namespace: database
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: postgres-read-pool
  minReplicas: 2
  maxReplicas: 8
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100
          periodSeconds: 60
        - type: Pods
          value: 2
          periodSeconds: 60
      selectPolicy: Max
    scaleDown:
      stabilizationWindowSeconds: 600
      policies:
        - type: Pods
          value: 1
          periodSeconds: 180
      selectPolicy: Min
```

> **Пояснение параметров behavior:**
> - `scaleDown.stabilizationWindowSeconds: 600` — удерживает масштаб на максимальном зафиксированном уровне в течение 10 минут, исключая флаппинг при кратковременных спадах нагрузки.
> - `scaleDown.policies` (`value: 1, periodSeconds: 180`) — разрешает удалять не более 1 пода за 3 минуты. Это дает возможность соседним подам плавно принять трафик и снижает нагрузку на дисковую подсистему при десинхронизации.

### Сценарий 2: KEDA ScaledObject для воркеров обработки потоков с локальным кэшем

Масштабирование воркеров-обработчиков очереди RabbitMQ, сохраняющих локальное состояние транскодинга или кэш на диске.

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: stream-worker-scaler
  namespace: processing
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: stream-worker
  pollingInterval: 15
  cooldownPeriod: 300
  minReplicaCount: 2
  maxReplicaCount: 15
  advanced:
    restoreToOriginalReplicaCount: false
    horizontalPodAutoscalerConfig:
      behavior:
        scaleDown:
          stabilizationWindowSeconds: 420
          policies:
            - type: Pods
              value: 1
              periodSeconds: 120
  triggers:
    - type: rabbitmq
      metadata:
        protocol: amqp
        queueName: high-load-tasks
        mode: QueueLength
        value: "50"
      authenticationRef:
        name: keda-rabbitmq-auth
```

> **Особенность `minReplicaCount` для StatefulSet:**
> В отличие от stateless Deployment, для StatefulSet настоятельно не рекомендуется использовать `minReplicaCount: 0` (scale-to-zero). Полная остановка всех подов приводит к потере активных дисковых кэшей и задержкам холодного старта при появлении новых сообщений.

### Сценарий 3: Защита доступности через PodDisruptionBudget (PDB)

При плановом обслуживании узлов (`kubectl drain`) или автоматическом обновлении кластера автоскейлер и диспетчер выселения должны соблюдать гарантии доступности сервиса:

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: postgres-read-pool-pdb
  namespace: database
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: postgres-read-pool
```

> [!IMPORTANT]
> Значение `minAvailable` в PDB должно быть **строго меньше или равно** `minReplicas` в HPA. Если задать `minAvailable: 3` при `minReplicas: 2`, то в период минимальной нагрузки HPA сожмет пул до 2 подов, после чего любой `kubectl drain` узла с репликой будет заблокирован ошибкой `Cannot evict pod: PodDisruptionBudget is violated`.

---

## Операции и команды

### Мониторинг состояния HPA и StatefulSet

Проверка текущего статуса автомасштабирования, утилизации метрик и числа запущенных реплик:

```bash
kubectl get hpa postgres-read-pool-hpa -n database
# → NAME                     REFERENCE                          TARGETS           MINPODS   MAXPODS   REPLICAS   AGE
# → postgres-read-pool-hpa   StatefulSet/postgres-read-pool     68%/70%, 72%/80%   2         8         4          3d
```

Инспекция детального состояния HPA, включая события регулятора масштабирования (`ScalingActive`, `AbleToScale`):

```bash
kubectl describe hpa postgres-read-pool-hpa -n database
# → Reference:                                             StatefulSet/postgres-read-pool
# → Metrics:                                               ( current / target )
# →   resource cpu on pods  (as a percentage of request):  68% (680m) / 70%
# → Min replicas:                                          2
# → Max replicas:                                          8
# → StatefulSet pods:                                      4 current / 4 desired
# → Conditions:
# →   Type            Status  Reason               Message
# →   ----            ------  ------               -------
# →   AbleToScale     True    ScaleDownStabilized  recent recommendations were higher than current one, waiting for stabilization
# →   ScalingActive   True    ValidMetricFound     the HPA was able to successfully calculate a replica count
# → Events:
# →   Type    Reason             Age    From                       Message
# →   ----    ------             ----   ----                       -------
# →   Normal  SuccessfulRescale  14m    horizontal-pod-autoscaler  New size: 4; reason: cpu resource utilization above target
```

### Проверка статуса KEDA ScaledObject

Контроль за состоянием триггеров KEDA и связанного HPA:

```bash
kubectl get scaledobject stream-worker-scaler -n processing
# → NAME                   SCALETARGETKIND   SCALETARGETNAME   MIN   MAX   TRIGGERS   AUTHENTICATION       READY   ACTIVE   AGE
# → stream-worker-scaler   StatefulSet       stream-worker     2     15    rabbitmq   keda-rabbitmq-auth   True    True     24h
```

### Аудит порядка подов и привязки PVC

Проверка порядка создания подов StatefulSet и привязанных к ним томов:

```bash
kubectl get pods -n database -l app.kubernetes.io/name=postgres-read-pool -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,IP:.status.podIP,NODE:.spec.nodeName
# → NAME                   STATUS    IP              NODE
# → postgres-read-pool-0   Running   10.244.2.45     worker-node-01
# → postgres-read-pool-1   Running   10.244.5.12     worker-node-02
# → postgres-read-pool-2   Running   10.244.3.89     worker-node-03
# → postgres-read-pool-3   Running   10.244.1.67     worker-node-04
```

Проверка политики удержания PVC в действующем StatefulSet:

```bash
kubectl get statefulset postgres-read-pool -n database -o jsonpath='{.spec.persistentVolumeClaimRetentionPolicy}'
# → {"whenDeleted":"Retain","whenScaled":"Retain"}
```

### Аудит и очистка неиспользуемых (orphaned) PVC после Scale-Down

Если в StatefulSet используется политика `whenScaled: Retain`, при масштабировании вниз остаются диски. Команда для обнаружения томов, чей порядковый номер превышает текущее число реплик:

```bash
# Получение текущего количества реплик
CURRENT_REPLICAS=$(kubectl get statefulset postgres-read-pool -n database -o jsonpath='{.spec.replicas}')
echo "Current replicas: $CURRENT_REPLICAS"
# → Current replicas: 2

# Поиск PVC с индексами >= CURRENT_REPLICAS
kubectl get pvc -n database -l app.kubernetes.io/name=postgres-read-pool | awk -v limit="$CURRENT_REPLICAS" '
NR>1 {
  split($1, parts, "-");
  idx = parts[length(parts)];
  if (idx >= limit) print "Orphaned PVC:", $1, "(Status: " $2 ")"
}'
# → Orphaned PVC: pgdata-postgres-read-pool-2 (Status: Bound)
# → Orphaned PVC: pgdata-postgres-read-pool-3 (Status: Bound)
```

---

## Устранение неполадок

### 1. Переполнение хранилища из-за накопления неиспользуемых PVC

- **Симптомы:** СХД (Ceph / SAN) сообщает о нехватке пространства. Новые поды переходят в состояние `Pending` с ошибкой `FailedScheduling: 0/12 nodes are available: volume node affinity conflict` или `ProvisioningFailed`.
- **Причина:** HPA активно масштабирует StatefulSet вверх и вниз. При политике `whenScaled: Retain` удаление подов не освобождает диски. Каждый всплеск нагрузки до `maxReplicas` аллоцирует новые тома, которые никогда не удаляются автоматически.
- **Диагностика:**
  ```bash
  kubectl get pvc -n database -l app.kubernetes.io/name=postgres-read-pool
  # Вывод показывает десятки Bound PVC для подов, которых нет в кластере
  ```
- **Решение:**
  1. Если тома содержат восстановимые данные (кэш): переключите политику на `whenScaled: Delete` через патч спецификации:
     ```bash
     kubectl patch statefulset postgres-read-pool -n database -p '{"spec":{"persistentVolumeClaimRetentionPolicy":{"whenScaled":"Delete"}}}'
     # → statefulset.apps/postgres-read-pool patched
     ```
  2. Если тома содержат персистентные данные реплик: настройте плановый регламент (CronJob) для очистки PVC, не используемых более заданного времени, либо ограничьте амплитуду масштабирования (`maxReplicas`).

### 2. Флаппинг HPA и деградация при долгой инициализации подов

- **Симптомы:** HPA фиксирует перегрузку и инициирует `scaleUp`. Новый под стартует, начинает загрузку дампа базы или прогрев кэша (10–15 минут), утилизирует CPU на 100%. HPA считает, что нагрузки стало еще больше, и запрашивает еще поды. После завершения инициализации нагрузка падает, HPA сбрасывает поды, затем цикл повторяется.
- **Причина:**
  1. По умолчанию метрики рассчитываются по всем подам, включая не готовые к приему трафика.
  2. Не настроена стабилизация `behavior.scaleDown.stabilizationWindowSeconds`.
  3. Используется `podManagementPolicy: OrderedReady`, блокирующий одновременную инициализацию.
- **Решение:**
  1. Настройте корректную `readinessProbe`, чтобы трафик и расчет метрик не перегружали холодный под.
  2. Увеличьте `stabilizationWindowSeconds` для `scaleDown` минимум до 600–900 секунд.
  3. Для независимых реплик включите `podManagementPolicy: Parallel`.

### 3. Обрыв клиентских соединений и повреждение данных при Scale-Down

- **Симптомы:** При уменьшении количества реплик клиенты получают ошибки `Connection reset by peer` или транзакции прерываются с `FATAL: terminating connection due to administrator command`.
- **Причина:** StatefulSet удаляет под сигналом `SIGTERM`. По умолчанию `terminationGracePeriodSeconds: 30`, и если приложение не успело сбросить буферы или корректно закрыть соединения, процесс завершается принудительно через `SIGKILL`.
- **Диагностика:**
  ```bash
  kubectl get events -n database --field-selector reason=Killing
  # → Killing pod postgres-read-pool-3: Stopping container postgresql
  ```
- **Решение:**
  1. Увеличьте `terminationGracePeriodSeconds` (например, до 180–300 секунд).
  2. Добавьте в контейнер `lifecycle.preStop` хук, который переводит под в режим дренажа (снятие с балансировки через Readiness Probe) и дает время активным клиентам завершить работу:
     ```yaml
     lifecycle:
       preStop:
         exec:
           command: ["/bin/sh", "-c", "touch /tmp/draining && sleep 20"]
     ```

### 4. Взаимная блокировка (Deadlock) HPA Scale-Down и PodDisruptionBudget

- **Симптомы:** HPA фиксирует необходимость уменьшения реплик, но количество подов не снижается. В логах контроллера или событиях отображается зависание масштабирования.
- **Причина:** Значение `minAvailable` в PDB жестко зафиксировано выше или равно текущему количеству подов, либо системные операции дренажа узлов вступили в конфликт с попыткой HPA удалить последний ordinal под.
- **Диагностика:**
  ```bash
  kubectl get pdb -n database
  # → NAME                      MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
  # → postgres-read-pool-pdb    3               N/A               0                     5d
  ```
  Если `ALLOWED DISRUPTIONS: 0`, выселение и удаление подов блокируется.
- **Решение:** Пересмотрите расчет PDB: используйте процентное соотношение (например, `maxUnavailable: 25%`) или убедитесь, что `minAvailable` строго меньше минимального порога `minReplicas` в HPA.

---

## Лучшие практики

1. **Разделяйте роли Master и Read-Only Replicas:**
   - Никогда не объединяйте ведущий узел записи (Primary) и масштабируемые читающие реплики в один StatefulSet под управлением HPA.
   - Primary должен быть статическим StatefulSet (`replicas: 1` или фиксированная пара), управляемым специализированным оператором.
   - Read-реплики выносите в отдельный StatefulSet со своей службой балансировки.

2. **Используйте `podManagementPolicy: Parallel` для читающих пулов:**
   - Если поды пула автономны и не зависят друг от друга, параллельный запуск и остановка снижают задержку масштабирования в разы по сравнению с последовательным `OrderedReady`.

3. **Защищайте кластер длинным окном стабилизации `scaleDown`:**
   - Задавайте `stabilizationWindowSeconds: 600` (10 минут) или более в блоке `behavior.scaleDown`. Для дисковых и stateful-нагрузок стоимость удаления и повторного создания пода неизмеримо выше, чем для stateless microservices.

4. **Осознанно выбирайте политику `whenScaled`:**
   - Для шардированных кэшей и воркеров очередей используйте `whenScaled: Delete`, чтобы исключить утечки дискового пространства на СХД.
   - Для read-реплик СУБД с предварительно синхронизированным состоянием используйте `whenScaled: Retain`, но обеспечьте регламентный мониторинг и очистку осиротевших PVC.

5. **Обязательно рассчитывайте `terminationGracePeriodSeconds` и настраивайте `preStop`:**
   - Время вывода из строя должно покрывать максимальную длину транзакции на чтение плюс время контролируемого завершения процесса СУБД.
   - Снятие пода с Readiness Probe перед отправкой `SIGTERM` предотвращает отправку новых запросов на завершающийся под.

6. **Контролируйте лаг репликации через Readiness Probe:**
   - Подключайте реплику к балансировщику (Service) только тогда, когда отставание репликации от мастера находится в пределах допустимого SLA (например, лаг репликации < 5 секунд).
   - Если реплика сильно отстала при старте, она не должна получать клиентский трафик до полной синхронизации.

7. **Не используйте Scale-to-Zero для StatefulSet:**
   - Минимальное число реплик (`minReplicas` в HPA, `minReplicaCount` в KEDA) всегда должно быть $\ge 1$ (рекомендуется $\ge 2$ для обеспечения отказоустойчивости сервиса).

---

## Дополнительная информация

### См. также

- [HPA: Общие концепции](HPA/index.md) — базовые принципы и архитектура Horizontal Pod Autoscaler
- [HPA: Продвинутые сценарии](HPA/hpa_advanced.md) — настройки `behavior`, кастомные метрики и политики масштабирования
- [HPA: Практические манифесты](HPA/hpa_scenarios.md) — примеры манифестов для очередей и микросервисов
- [KEDA: Концепции и архитектура](keda/keda_concepts.md) — основы событийного автомасштабирования
- [KEDA: Практические сценарии](keda/practical_scenarios.md) — детальные примеры работы с брокерами сообщений
- [Pod Disruption Budget (PDB)](pod_disruption_budget.md) — управление бюджетом прерываний при регламентных работах
- [Vertical Pod Autoscaler (VPA)](vpa_detailed.md) — вертикальное автомасштабирование ресурсов подов
- [In-Place Pod Resize](in_place_pod_resize.md) — изменение CPU и памяти пода без перезапуска
- [StatefulSet: Архитектура и основы](../Base/StatefulSet/statefulset_core_concepts.md) — глубокий разбор контроллера StatefulSet
- [StatefulSet: Лучшие практики](../Base/StatefulSet/statefulset_best_practices.md) — эксплуатационные правила и рекомендации для production
- [Управление томами PV и PVC](../Storage/pv_and_pvc_scenarios.md) — жизненный цикл томов и CSI-интеграция
