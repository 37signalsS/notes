# Сравнение Deployment, StatefulSet и DaemonSet

**Актуально для:** Kubernetes 1.35–1.37 (Bare-Metal / On-Premise)

## Определения

*   **Deployment** — декларативный контроллер рабочей нагрузки уровня API `apps/v1`, предназначенный для приложений без сохранения состояния (stateless). Управляет нижележащими объектами `ReplicaSet`. Рассматривает поды как взаимозаменяемые, эфемерные сущности («cattle» / скот) без персональной идентичности, стабильного сетевого имени или постоянной привязки к конкретному диску.
*   **StatefulSet** — специализированный контроллер рабочей нагрузки уровня API `apps/v1` для приложений с сохранением состояния (stateful). Гарантирует уникальность, строго детерминированный порядок развертывания/масштабирования/удаления и стабильную идентичность («pets» / питомцы): предсказуемый сетевой FQDN через Headless Service, неизменный порядковый номер (индекс) и постоянную привязку индивидуального тома хранилища (PVC).
*   **DaemonSet** — контроллер уровня API `apps/v1`, обеспечивающий запуск ровно одного экземпляра пода на каждом доступном физическом/виртуальном узле кластера (или на строго определенной выборке узлов). Не имеет параметра `spec.replicas`, масштабируется синхронно с топологией вычислительных узлов кластера. Служит для развертывания низкоуровневых инфраструктурных демонов (сбор логов, экспорт метрик узла, CNI-агенты, CSI-плагины, прокси).

Теоретические основы типов нагрузок см. в разделе **[Stateful vs Stateless](../../../Concepts/stateful_vs_stateless.md)**.

## Предварительные требования

Для практического применения и выбора между контроллерами требуется:

1.  **Базовые знания примитивов Kubernetes:** понимание жизненного цикла [Pod](../Pod/pod_overview.md), работы абстракций Service (ClusterIP, Headless Service), а также подсистемы хранения [PersistentVolume и PersistentVolumeClaim (PV/PVC)](../../Storage/pv_and_pvc.md).
2.  **Понимание предметных областей каждого контроллера:** [Deployment](../Deployment/index.md), [StatefulSet](./statefulset_overview.md), [DaemonSet](../daemonset.md).
3.  **Окружение кластера v1.35–v1.37:** часть описываемых механизмов (`persistentVolumeClaimRetentionPolicy` GA v1.32, `apps.kubernetes.io/pod-index` GA v1.32, `maxUnavailable` для StatefulSet Beta v1.35/v1.37, стратегия `Recreate` для StatefulSet Alpha v1.37, Non-Graceful Node Shutdown GA v1.28) актуальна для современных версий платформы.
4.  **Проверка версии кластера:**
    ```bash
    kubectl version
    # → Client Version: v1.35.0
    # → Kustomize Version: v5.4.3
    # → Server Version: v1.35.2
    ```

---

## Основные концепции

### Сравнительная таблица характеристик (Kubernetes v1.35–v1.37)

| Характеристика | Deployment | StatefulSet | DaemonSet |
| :--- | :--- | :--- | :--- |
| **Архитектурная модель** | Взаимозаменяемые реплики (Stateless) | Персональная идентичность (Stateful) | Инфраструктурный агент на узел (Node Daemon) |
| **Контроллер нижнего уровня** | Управляет `ReplicaSet` | Управляет подами напрямую | Управляет подами напрямую |
| **Именование подов** | Случайные суффиксы (`web-6c7d9b5d6-abc12`) | Детерминированный индекс (`db-0`, `db-1`, `db-2`) | Случайный хеш-суффикс (`node-exporter-4x2k9`) |
| **Сетевой доступ** | Балансировка через Service (ClusterIP / NodePort) | Прямой адрес через Headless Service (`clusterIP: None`) | `hostNetwork`, `hostPort`, либо Service с `internalTrafficPolicy: Local` |
| **DNS-идентификация** | Общий пул адресов сервиса (Endpoints / EndpointSlice) | Стабильный FQDN: `$(pod).$(service).$(ns).svc.cluster.local` | Имя узла (`spec.nodeName`) или `status.hostIP` |
| **Тип дискового хранилища** | Общее сетевое (RWX) или временное (`emptyDir`) | Индивидуальный том на реплику (RWO/RWOP) | Локальные пути узла (`hostPath`), сокеты, `emptyDir` |
| **Управление PVC** | Ручное создание одного общего PVC на весь контроллер | Автоматизация через `volumeClaimTemplates` и `retentionPolicy` | PVC обычно не применяются (работа с дисками хоста) |
| **Порядок жизненного цикла** | Параллельный, не детерминирован | Строго последовательный (0..N-1 старт, N-1..0 стоп) | Независимый на каждом узле кластера |
| **Стратегии обновления** | `RollingUpdate` (`maxSurge`, `maxUnavailable`), `Recreate` | `RollingUpdate` (`partition`, `maxUnavailable`), `OnDelete`, `Recreate` | `RollingUpdate` (`maxUnavailable`, `maxSurge`), `OnDelete` |
| **Механизм maxSurge** | Поддерживается (создает поды сверх `replicas`) | **Не поддерживается** (том RWO заблокирован репликой) | Поддерживается (GA v1.25, временный второй под на узле) |
| **Масштабирование** | Параллельное, мгновенное, поддержка HPA/KEDA | Последовательное (по умолчанию), поддержка HPA | Автоматическое (по числу узлов), HPA не применим |
| **Отказ узла (Node NotReady)** | Авто-эвикция (~5 мин) и пересоздание на другом узле | Под зависает в `Terminating`, том заблокирован (Split-brain lock) | Под не переносится, ожидает возврата узла в строй |
| **Реакция на `kubectl drain`** | Поды выселяются с учетом PDB | Поды выселяются с учетом PDB (кворум кластера) | Игнорирует выселение (требует `--ignore-daemonsets`) |
| **История ревизий и откат** | Объекты `ReplicaSet` (`rollout undo`) | Объекты `ControllerRevision` (`rollout undo`) | Объекты `ControllerRevision` (`rollout undo`) |
| **Пауза rollout (pause/resume)** | Поддерживается (`kubectl rollout pause`) | Не поддерживается | Не поддерживается |
| **PodDisruptionBudget (PDB)** | Обеспечивает SLA доступности пула подов | Защищает кворум распределенных СУБД (Raft/Paxos) | Не применим (на узле всего один под) |

---

### Глубокие различия в сетевой идентичности и маршрутизации

#### Deployment: Абстракция пула взаимозаменяемых адресов
Deployment опирается на стандартный виртуальный IP-адрес сервиса (`ClusterIP`). Сетевые пакеты проксируются через `kube-proxy` (iptables, IPVS) или eBPF-маршрутизацию CNI (Cilium) случайным образом или по алгоритму round-robin между всеми подами, прошедшими Readiness-проверку. 
Если под падает или пересоздается, он получает новый динамический IP-адрес из пула PodCIDR узла. Клиенты не знают и не должны знать IP-адреса конкретных подов; обращение всегда идет по единому DNS-имени сервиса (`api.prod.svc.cluster.local`).

#### StatefulSet: Стабильный FQDN и идентификация реплик
StatefulSet требует обязательной связки с **Headless Service** (`clusterIP: None`). В этом режиме CoreDNS не назначает виртуальный IP, а возвращает SRV- и A/AAAA-записи, указывающие напрямую на IP-адреса конкретных подов.
Каждый под получает постоянное доменное имя следующего формата:
```text
$(pod-name).$(service-name).$(namespace).svc.cluster.local
```
Например: `kafka-0.kafka-headless.messaging.svc.cluster.local`.

**Значение для SRE и распределенных систем:**
1.  **Топология кластера без координатора:** Узлы баз данных (ClickHouse, Cassandra, Kafka KRaft, MongoDB ReplicaSet) прописывают имена соседей в конфигурационных файлах до первого запуска. При перезапуске пода на другом физическом узле его IP-адрес изменится, но FQDN останется прежним, позволяя кластеру восстановить топологию без ручного переконфигурирования.
2.  **Pod Index Label (GA v1.32):** Каждый под StatefulSet автоматически помечается системной меткой `apps.kubernetes.io/pod-index: "0"`, `"1"`, `"2"`. Это позволяет настраивать таргетированные Service для чтения/записи (например, направлять write-трафик строго на под с индексом `0` через селектор `apps.kubernetes.io/pod-index: "0"`).

#### DaemonSet: Прямая привязка к сети и портам узла
Поды DaemonSet чаще всего работают в сетевом пространстве имен самого хоста (`hostNetwork: true`) или используют `hostPort`. IP-адрес пода в этом случае совпадает с IP-адресом физического сервера.
Если DaemonSet публикуется через стандартный Kubernetes Service, применяется директива `spec.internalTrafficPolicy: Local`. В этом случае `kube-proxy` направляет трафик, инициированный с текущего узла, строго в локальный под DaemonSet на этом же сервере, исключая лишние сетевые переходы (hops) через сеть кластера.

---

### Архитектура хранения и проблема Multi-Attach

Ключевой водораздел между Deployment и StatefulSet лежит в способе работы с блочными томами `ReadWriteOnce` (RWO) при эксплуатации в On-Premise инфраструктуре (Ceph RBD, iSCSI, Fibre Channel, SAN, LVM):

```
Проблема Multi-Attach в Deployment при RollingUpdate:
┌─────────────────┐             ┌─────────────────┐
│  Worker Node 1  │             │  Worker Node 2  │
│ ┌─────────────┐ │             │ ┌─────────────┐ │
│ │  Old Pod    │ │             │ │  New Pod    │ │
│ │ (Terminating│ │             │ │ (Container  │ │
│ └──────┬──────┘ │             │ │  Creating)  │ │
└────────┼────────┘             └────────┼────────┘
         │                               │
         ▼                               ▼
    [Узел 1 держит том]        [CSI Attach блокирован!]
         │                               │
         └──────────► [ RWO PV ] ◄───────┘
            VolumeAttachment conflict!
```

#### Механизм Multi-Attach Error в Deployment
1.  При стандартном обновлении Deployment со стратегией `RollingUpdate` контроллер создает новый под на свободном узле (Node 2) до того, как удалит старый под на Node 1 (`maxSurge > 0`).
2.  Новый под пытается смонтировать тот же PersistentVolumeClaim.
3.  CSI-контроллер (`attachdetach-controller` в `kube-controller-manager`) проверяет объект `VolumeAttachment` и фиксирует, что RWO-том уже эксклюзивно присоединен к Node 1.
4.  Новый под зависает в статусе `ContainerCreating` с ошибкой:
    ```text
    Multi-Attach error for volume "pvc-xxx" Volume is already exclusively attached to one node and cannot be attached to another
    ```
5.  **Вывод для системного администратора:** Deployment категорически не предназначен для работы с RWO-дисками в сочетании со стратегией `RollingUpdate`. Единственный способ запустить RWO-диск в Deployment — использовать стратегию `strategy.type: Recreate` (старый под гарантированно удаляется и отсоединяет том перед стартом нового), что неизбежно ведет к даунтайму.

#### Решение StatefulSet: Изолированные PVC через шаблоны
StatefulSet исключает конфликт Multi-Attach за счет декларации `volumeClaimTemplates`:
*   Для каждого пода `app-0`, `app-1` создается свой собственный независимый PVC: `data-app-0`, `data-app-1`.
*   При обновлении или перезапуске пода `app-0` контроллер StatefulSet ожидает полной остановки контейнера и завершения процесса отсоединения диска от старого узла, после чего запускает под с тем же именем `app-0`, монтирующий строго диск `data-app-0`.

#### Политика сохранения томов (PVC Retention Policy)
В Kubernetes v1.32+ (GA) поведение дисков при изменении размера StatefulSet регулируется секцией `spec.persistentVolumeClaimRetentionPolicy`:
*   `whenScaled: Retain` (по умолчанию) — при масштабировании вниз (с 5 до 3 реплик) диски `data-app-4` и `data-app-3` не удаляются, предотвращая потерю данных.
*   `whenDeleted: Retain` — при удалении самого объекта StatefulSet все диски остаются в статусе `Bound` в хранилище.

---

### Стратегии обновления и версионирование

#### 1. Deployment: Максимальная доступность через ReplicaSet
*   **Двухуровневое версионирование:** Каждое изменение шаблона пода (`spec.template`) генерирует новый дочерний объект `ReplicaSet`. История ревизий хранится в etcd в виде законсервированных ReplicaSet с числом реплик `0`. Количество ревизий ограничивается `spec.revisionHistoryLimit` (рекомендуется `3–5`).
*   **Параметры `maxSurge` и `maxUnavailable`:**
    *   `maxSurge` (по умолчанию `25%`): допустимое превышение целевого числа реплик во время выкатки. Позволяет поднять новые поды параллельно со старыми (требует резерва CPU/RAM в кластере).
    *   `maxUnavailable` (по умолчанию `25%`): допустимая просадка мощности сервиса. Значение `maxUnavailable: 0` гарантирует нулевой даунтайм при наличии свободных ресурсов.
*   **Механизм Rollover:** Если во время выполнения rollout версии v2 администратор накатывает версию v3, Deployment не ждет завершения v2, а немедленно начинает сворачивать поды v2 и v1, поднимая v3.
*   **Управление процессом:** Поддерживаются команды `kubectl rollout pause` и `kubectl rollout resume` для отладки промежуточных состояний.

#### 2. StatefulSet: Консервативный детерминизм через ControllerRevision
*   **Версионирование через ControllerRevision:** StatefulSet не создает ReplicaSet. Снапшоты шаблонов подов сохраняются в компактных системных объектах `ControllerRevision`.
*   **Последовательный Rollout (N-1 → 0):** По умолчанию обновление начинается со старшего индекса. Под `app-2` останавливается, отсоединяет диск, создается заново с новым образом, проходит проверку `readinessProbe` и выдерживает паузу `minReadySeconds`. Только после этого контроллер переходит к `app-1`.
*   **Канареечные выкатки через `partition`:** Параметр `spec.updateStrategy.rollingUpdate.partition: 2` указывает контроллеру обновлять только поды с индексом `>= 2`. Поды с индексами `0` и `1` остаются на старой версии, позволяя протестировать релиз на одной реплике под реальной нагрузкой.
*   **Параметр `maxUnavailable` (Beta v1.35, v1.37):**
    *   Позволяет обновлять несколько реплик одновременно (число или процент).
    *   *Оговорка о стабильности:* В версиях v1.35.0–v1.35.3 фичагейт `MaxUnavailableStatefulSet` был включен по умолчанию, но из-за бага deadlock при `podManagementPolicy: Parallel` ([kubernetes/kubernetes#137409](https://github.com/kubernetes/kubernetes/issues/137409)) был отключен по умолчанию в v1.35.4+ и v1.36. В v1.37 ошибка устранена (PR [#137666](https://github.com/kubernetes/kubernetes/pull/137666)), и гейт снова активен по умолчанию.
    *   *SRE-ограничение:* Для кворумных систем из 3 реплик значение `maxUnavailable` выше `1` недопустимо, так как одновременная потеря двух реплик разрушает кворум ($N/2 + 1$).
*   **Стратегия `Recreate` (Alpha v1.37, feature gate `StatefulSetRecreateStrategy`):** Полностью гасит все поды с N-1 до 0, затем поднимает новые с 0 до N-1. Применяется, когда формат данных на диске не допускает одновременной работы старой и новой версий бинарного протокола.

#### 3. DaemonSet: Поузловое обновление инфраструктуры
*   **Стратегии:** `RollingUpdate` (по умолчанию) и `OnDelete` (под обновляется только при принудительном ручном удалении пода администратором — стандарт де-факто для критичных сетевых компонентов CNI, чтобы исключить потерю связности кластера).
*   **Параметры:**
    *   `maxUnavailable` (по умолчанию `1`): лимит узлов, временно остающихся без агента.
    *   `maxSurge` (GA v1.25): контроллер запускает новый под на узле рядом со старым. Позволяет избежать слепых зон при сборе метрик/логов. Требует отсутствия конфликтов по фиксированным `hostPort`.

---

### Поведение при авариях узлов и регламентных работах (SRE)

Поведение контроллеров при переходе физического сервера в статус `NotReady` (сбой гипервизора, зависание ядра, потеря линка питания/сети) принципиально различается:

```
Реакция контроллеров на падение физического узла:
┌────────────────────────────────────────────────────────┐
│ Worker Node (NotReady, taints: unreachable:NoExecute)  │
│                                                        │
│  [ Deployment Pod ]  ──► Evicted через 300 сек         │
│                          Автоматически поднят на Node 2│
│                                                        │
│  [ StatefulSet Pod]  ──► ЗАБЛОКИРОВАН в Terminating    │
│                          Новый под НЕ СОЗДАЕТСЯ!       │
│                          Защита от Split-brain         │
│                                                        │
│  [ DaemonSet Pod  ]  ──► Остается на мертвом узле      │
│                          Не эвакуируется на Node 2     │
└────────────────────────────────────────────────────────┘
```

#### Защита StatefulSet от Split-Brain
Если узел завис, `kubelet` перестает отправлять heartbeat в API-сервер. По истечении таймаута (`node-monitor-grace-period: 40s` и `tolerationSeconds: 300`) контроллер накладывает таинт `node.kubernetes.io/unreachable:NoExecute`.
*   **Deployment:** Помещает старый под в `Terminating` и **немедленно создает замену** на другом работающем узле. Для stateless-приложений это безопасно.
*   **StatefulSet:** Переводит под в `Terminating`, но **не создает замену на другом узле**. 
    *Причина:* Контроллер не может знать наверняка, умер ли сервер физически или произошла сетевая изоляция (network partition). Если запустить `db-0` на исправном узле в то время как старый `db-0` еще жив и пишет на диск SAN/iSCSI, возникнет катастрофическая порча данных (Split-brain).
*   **SRE-протокол восстановления (Non-Graceful Node Shutdown, GA v1.28+):**
    Администратор обязан физически изолировать/выключить упавший сервер (через IPMI, iLO, PDU или STONITH), после чего явно подтвердить отключение в Kubernetes:
    ```bash
    kubectl taint node worker-node-03 node.kubernetes.io/out-of-service=nodeshutdown:NoExecute
    # → node/worker-node-03 tainted
    ```
    Только после наложения этого таинта `AttachDetachController` принудительно удаляет `VolumeAttachment`, отсоединяет RWO-том и разрешает запуск пода StatefulSet на новом узле.

#### Поведение при `kubectl drain`
*   **Deployment:** Поды выселяются с соблюдением требований `PodDisruptionBudget` и пересоздаются планировщиком на других узлах.
*   **StatefulSet:** Поды выселяются последовательно с соблюдением PDB. Если PDB запрещает отключение реплики из-за потери кворума, операция `kubectl drain` блокируется до восстановления здоровья кластера.
*   **DaemonSet:** Механизм `eviction API` **не выселяет** поды DaemonSet. Команда `kubectl drain` завершится ошибкой, если явно не указан флаг `--ignore-daemonsets`.

---

## Практические сценарии

### Сценарий 1: Отказоустойчивый Stateless API (Deployment)

Конфигурация для высоконагруженного API-сервиса: автоматическое масштабирование, нулевой даунтайм при обновлении, распределение по физическим серверам.

```yaml
# web-api-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-api
  namespace: production
  labels:
    app.kubernetes.io/name: web-api
spec:
  replicas: 4
  revisionHistoryLimit: 5
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 25%
      maxUnavailable: 0
  selector:
    matchLabels:
      app.kubernetes.io/name: web-api
  template:
    metadata:
      labels:
        app.kubernetes.io/name: web-api
    spec:
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: app.kubernetes.io/name
                  operator: In
                  values: ["web-api"]
              topologyKey: kubernetes.io/hostname
      containers:
      - name: api
        image: nginx:1.27.4-alpine
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: 200m
            memory: 256Mi
          limits:
            cpu: 500m
            memory: 512Mi
        readinessProbe:
          httpGet:
            path: /healthz
            port: 80
          initialDelaySeconds: 5
          periodSeconds: 5
```

Проверка состояния и хода развертывания:
```bash
kubectl apply -f web-api-deployment.yaml
# → deployment.apps/web-api created

kubectl rollout status deployment/web-api -n production
# → Waiting for deployment "web-api" rollout to finish: 0 of 4 updated replicas are available...
# → deployment "web-api" successfully rolled out

kubectl get rs -n production -l app.kubernetes.io/name=web-api
# → NAME                 DESIRED   CURRENT   READY   AGE
# → web-api-78d469766b   4         4         4       45s
```

---

### Сценарий 2: Распределенная кластерная СУБД с кворумом (StatefulSet)

Манифест для 3-узлового кластера с индивидуальными блочными томами, Headless Service и канареечным обновлением через `partition`.

```yaml
# db-cluster-statefulset.yaml
apiVersion: v1
kind: Service
metadata:
  name: db-nodes
  namespace: database
  labels:
    app.kubernetes.io/name: db-cluster
spec:
  clusterIP: None
  selector:
    app.kubernetes.io/name: db-cluster
  ports:
  - port: 5432
    name: postgresql
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: db
  namespace: database
spec:
  serviceName: "db-nodes"
  replicas: 3
  podManagementPolicy: OrderedReady
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      partition: 0
  persistentVolumeClaimRetentionPolicy:
    whenDeleted: Retain
    whenScaled: Retain
  selector:
    matchLabels:
      app.kubernetes.io/name: db-cluster
  template:
    metadata:
      labels:
        app.kubernetes.io/name: db-cluster
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
              - key: app.kubernetes.io/name
                operator: In
                values: ["db-cluster"]
            topologyKey: kubernetes.io/hostname
      containers:
      - name: postgresql
        image: postgres:16.8-alpine
        ports:
        - containerPort: 5432
          name: postgresql
        env:
        - name: POSTGRES_PASSWORD
          value: "SecretAuthPass123"
        volumeMounts:
        - name: pgdata
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: pgdata
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: "local-ssd"
      resources:
        requests:
          storage: 50Gi
```

Проверка формирования сетевой идентичности и дисков:
```bash
kubectl apply -f db-cluster-statefulset.yaml
# → service/db-nodes created
# → statefulset.apps/db created

kubectl get pods -n database -l app.kubernetes.io/name=db-cluster -o wide
# → NAME   READY   STATUS    RESTARTS   AGE   IP            NODE
# → db-0   1/1     Running   0          60s   10.244.1.45   worker-01
# → db-1   1/1     Running   0          42s   10.244.2.89   worker-02
# → db-2   1/1     Running   0          25s   10.244.3.12   worker-03

kubectl get pvc -n database
# → NAME          STATUS   VOLUME         CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# → pgdata-db-0   Bound    pvc-local-01   50Gi       RWO            local-ssd      75s
# → pgdata-db-1   Bound    pvc-local-02   50Gi       RWO            local-ssd      57s
# → pgdata-db-2   Bound    pvc-local-03   50Gi       RWO            local-ssd      40s
```

Проверка внутренней DNS-записи реплики из вспомогательного пода:
```bash
kubectl run dns-test --rm -it --restart=Never --image=busybox:1.36 -- nslookup db-0.db-nodes.database.svc.cluster.local
# → Server:    10.96.0.10
# → Address:   10.96.0.10:53
# → Name:      db-0.db-nodes.database.svc.cluster.local
# → Address:   10.244.1.45
# → pod "dns-test" deleted
```

---

### Сценарий 3: Инфраструктурный агент мониторинга узлов (DaemonSet)

Развертывание Node Exporter на всех узлах кластера (включая Control Plane) с доступом к сети хоста.

```yaml
# node-exporter-daemonset.yaml
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
  template:
    metadata:
      labels:
        app.kubernetes.io/name: node-exporter
    spec:
      hostNetwork: true
      hostPID: true
      tolerations:
      - operator: Exists
        effect: NoSchedule
      - operator: Exists
        effect: NoExecute
      containers:
      - name: node-exporter
        image: prom/node-exporter:v1.8.2
        args:
        - "--path.procfs=/host/proc"
        - "--path.sysfs=/host/sys"
        - "--path.rootfs=/host/root"
        ports:
        - containerPort: 9100
          hostPort: 9100
          name: metrics
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

Проверка охвата узлов кластера:
```bash
kubectl apply -f node-exporter-daemonset.yaml
# → daemonset.apps/node-exporter created

kubectl get daemonset node-exporter -n monitoring
# → NAME            DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR   AGE
# → node-exporter   5         5         5       5            5           <none>          30s
```

---

### Сценарий 4: Одиночный сервис с RWO-диском (Deployment Recreate vs StatefulSet)

Частая задача: сервис с 1 репликой (Jenkins, локальный биллинг-воркер, Single-Node Redis), которому нужен персистентный диск RWO.

| Параметр | Deployment (`strategy.type: Recreate`) | StatefulSet (`replicas: 1`) |
| :--- | :--- | :--- |
| **Создание PVC** | Ручное (один статический PVC) | Автоматическое (`volumeClaimTemplates`) |
| **Поведение при RollingUpdate** | Остановка пода → Detach диска → Старт пода | Остановка пода → Detach диска → Старт пода |
| **Сетевое имя** | Случайный суффикс (`jenkins-59b87dfb6-xk82l`) | Детерминированное (`jenkins-0`) |
| **Headless Service** | Не требуется | Обязателен для корректной работы |
| **Удобство отката** | Простое (`kubectl rollout undo`) | Требует контроля ControllerRevision |
| **Рекомендация SRE** | **Предпочтительно**, если сервису не нужны стабильные DNS-имена и он работает в единственном числе. | **Обязательно**, если в будущем планируется переход в кластерный режим. |

Фрагмент стратегии `Recreate` для Deployment:
```yaml
spec:
  replicas: 1
  strategy:
    type: Recreate
```

---

### Пошаговый SRE-ранбук: Миграция Deployment → StatefulSet без потери данных

Задача: Перевести сервис, работавший в `Deployment` с общим томом или локальным каталогом, на архитектуру `StatefulSet` с per-подовыми PVC без даунтайма для клиентов.

#### Шаг 1: Создание Headless Service
Создается Headless Service с тем же селектором меток, что и у существующего сервиса:
```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: app-headless
  namespace: default
spec:
  clusterIP: None
  selector:
    app: my-service
  ports:
  - port: 8080
    name: http
EOF
# → service/app-headless created
```

#### Шаг 2: Создание StatefulSet параллельно с Deployment
Развертывается манифест StatefulSet с `replicas: 3` и селектором `app: my-service`. Поды StatefulSet будут получать трафик через существующий общий Service наряду с подами Deployment:
```bash
kubectl apply -f app-statefulset.yaml
# → statefulset.apps/app-sts created

kubectl rollout status statefulset/app-sts
# → Waiting for 3 pods to be ready...
# → statefulset rolling update complete 3 pods at revision app-sts-5d8f6b8b8...
```

#### Шаг 3: Синхронизация данных в индивидуальные PVC
Если в Deployment использовался общий том, выполняется копирование исходных данных в новые PVC (`data-app-sts-0`, `data-app-sts-1`, `data-app-sts-2`) через вспомогательный Job или утилиту `rsync`.

#### Шаг 4: Плавное выключение старого Deployment
После проверки прогрева кэша и готовности баз данных реплики Deployment плавно масштабируются в 0:
```bash
kubectl scale deployment app-deploy --replicas=0
# → deployment.apps/app-deploy scaled

kubectl get pods -l app=my-service
# → NAME          READY   STATUS    RESTARTS   AGE
# → app-sts-0     1/1     Running   0          5m
# → app-sts-1     1/1     Running   0          4m
# → app-sts-2     1/1     Running   0          3m
```

#### Шаг 5: План отката (Rollback Plan)
Если в работе StatefulSet обнаружены сбои или деградация производительности I/O, выполняется мгновенный возврат:
```bash
kubectl scale deployment app-deploy --replicas=3
kubectl rollout status deployment/app-deploy
# → deployment "app-deploy" successfully rolled out

kubectl scale statefulset app-sts --replicas=0
# → statefulset.apps/app-sts scaled
```

#### Шаг 6: Финализация и удаление Deployment
После 24 часов стабильной работы старый Deployment удаляется из кластера:
```bash
kubectl delete deployment app-deploy
# → deployment.apps "app-deploy" deleted
```

---

### Инспекция и аудит управляющих контроллеров

Команды системного администратора для быстрой идентификации типа контроллера, управляющего подом:

```bash
# 1. Определение прямого владельца пода через metadata.ownerReferences
kubectl get pod web-api-78d469766b-4k2x9 -o jsonpath='{.metadata.ownerReferences[0].kind}: {.metadata.ownerReferences[0].name}{"\n"}'
# → ReplicaSet: web-api-78d469766b

kubectl get pod db-0 -n database -o jsonpath='{.metadata.ownerReferences[0].kind}: {.metadata.ownerReferences[0].name}{"\n"}'
# → StatefulSet: db

kubectl get pod node-exporter-9x7pl -n monitoring -o jsonpath='{.metadata.ownerReferences[0].kind}: {.metadata.ownerReferences[0].name}{"\n"}'
# → DaemonSet: node-exporter

# 2. Просмотр истории ревизий контроллеров
kubectl rollout history deployment/web-api -n production
# → deployment.apps/web-api 
# → REVISION  CHANGE-CAUSE
# → 1         <none>
# → 2         kubectl set image deployment/web-api api=nginx:1.27.4-alpine

kubectl rollout history statefulset/db -n database
# → statefulset.apps/db 
# → REVISION  CHANGE-CAUSE
# → 1         <none>

# 3. Аудит объектов ControllerRevision в пространстве имен
kubectl get controllerrevisions -n database
# → NAME            CONTROLLER             REVISION   AGE
# → db-78c69d846b   statefulset.apps/db    1          12m
```

---

## Диагностика и устранение неполадок

### 1. Multi-Attach error: под Deployment завис в ContainerCreating при RollingUpdate
*   **Симптомы:** После обновления образа или манифеста Deployment новый под бесконечно находится в статусе `ContainerCreating`. Старый под находится в `Terminating` или `Running`.
*   **Диагностика:**
    ```bash
    kubectl describe pod app-deploy-689bfb7bd-abc12
    # → Events:
    # → Warning  FailedAttachVolume  2m   attachdetach-controller  Multi-Attach error for volume "pvc-91823" Volume is already exclusively attached to one node (worker-01) and cannot be attached to another (worker-02)
    ```
*   **Причина:** К поду примонтирован PersistentVolume с режимом доступа `ReadWriteOnce`. При стратегии `RollingUpdate` планировщик назначил новый под на `worker-02`, в то время как старый под еще не отпустил диск на `worker-01`.
*   **Решение:**
    1.  Для приложений с 1 репликой переключить стратегию Deployment на `Recreate`:
        ```bash
        kubectl patch deployment app-deploy -p '{"spec":{"strategy":{"type":"Recreate","rollingUpdate":null}}}'
        # → deployment.apps/app-deploy patched
        ```
    2.  Для реплицированных сервисов выполнить миграцию на `StatefulSet` с `volumeClaimTemplates`.

---

### 2. Под StatefulSet завис в Terminating при падении физического узла
*   **Симптомы:** Сервер `worker-03` отключился по питанию. Под `db-2` перешел в статус `Terminating`. Новый под на других узлах не создается, кластер БД находится в состоянии `Degraded`.
*   **Диагностика:**
    ```bash
    kubectl get nodes
    # → NAME        STATUS     ROLES    AGE   VERSION
    # → worker-01   Ready      <none>   45d   v1.35.2
    # → worker-02   Ready      <none>   45d   v1.35.2
    # → worker-03   NotReady   <none>   45d   v1.35.2

    kubectl get pods -n database -o wide
    # → NAME   READY   STATUS        RESTARTS   AGE   NODE
    # → db-0   1/1     Running       0          2d    worker-01
    # → db-1   1/1     Running       0          2d    worker-02
    # → db-2   1/1     Terminating   0          2d    worker-03
    ```
*   **Причина:** Kubernetes защищает данные от Split-Brain. Пока узел `worker-03` не признан окончательно выведенным из строя, том RWO не может быть смонтирован на другой хост.
*   **Опасное действие (Анти-паттерн):** Выполнение `kubectl delete pod db-2 --force --grace-period=0` **категорически запрещено**, если сервер физически доступен по питанию или сети. Если старый процесс БД продолжит запись, произойдет разрушение ФС.
*   **Правильное SRE-решение (Non-Graceful Node Shutdown):**
    1.  Убедиться через IPMI/iLO/PDU, что сервер `worker-03` полностью выключен:
        ```bash
        ipmitool -H 192.168.10.103 -U admin -P secret power status
        # → Chassis Power is off
        ```
    2.  Наложить таинт аварийного отключения:
        ```bash
        kubectl taint node worker-03 node.kubernetes.io/out-of-service=nodeshutdown:NoExecute
        # → node/worker-03 tainted
        ```
    3.  Контроллер автоматически снимет `VolumeAttachment`, завершит удаление старого пода и создаст `db-2` на работающем узле `worker-01` или `worker-02`.

---

### 3. Под DaemonSet в CrashLoopBackOff из-за конфликта hostPort
*   **Симптомы:** На новом добавленном узле кластера под DaemonSet не может запуститься: `CrashLoopBackOff` или `Error`.
*   **Диагностика:**
    ```bash
    kubectl logs -n monitoring -l app.kubernetes.io/name=node-exporter --tail=20
    # → level=error msg="Couldn't create listener: listen tcp :9100: bind: address already in use"
    ```
*   **Причина:** На физическом хосте вне контейнера уже работает системный сервис, слушающий порт 9100 (например, установленный через `apt`/`systemd` локальный Node Exporter), что блокирует запуск пода с `hostPort: 9100` или `hostNetwork: true`.
*   **Решение:**
    1.  Найти и отключить конфликтующий сервис на хосте:
        ```bash
        ssh root@worker-04 "ss -tulpn | grep 9100"
        # → tcp LISTEN 0 128 *:9100 users:(("node_exporter",pid=1240,fd=3))
        ssh root@worker-04 "systemctl stop node_exporter && systemctl disable node_exporter"
        ```
    2.  Либо изменить порт в манифесте DaemonSet, избегая пересечений с портами ОС.

---

### 4. Deadlock обновления StatefulSet (зависание реплики N-1)
*   **Симптомы:** Выполнен `kubectl apply` с новым образом для StatefulSet. Под `db-2` перезапустился, но обновление `db-1` и `db-0` не начинается.
*   **Диагностика:**
    ```bash
    kubectl rollout status statefulset/db -n database
    # → Waiting for partitioned roll out to finish: 1 out of 3 new pods have been updated...

    kubectl get pods -n database
    # → NAME   READY   STATUS    RESTARTS   AGE
    # → db-0   1/1     Running   0          4h
    # → db-1   1/1     Running   0          4h
    # → db-2   0/1     Running   0          3m
    ```
*   **Причина:** Реплика `db-2` не проходит `readinessProbe` (например, ошибка инициализации, неверный пароль в Secret или несовместимость миграций схемы БД). Контроллер StatefulSet блокирует дальнейшее обновление, ожидая состояния `Ready` от текущей реплики.
*   **Решение:**
    1.  Изучить логи и события проблемного пода:
        ```bash
        kubectl describe pod db-2 -n database
        # → Warning  Unhealthy  10s (x8 over 80s)  kubelet  Readiness probe failed: HTTP probe failed with statuscode: 500
        ```
    2.  Если ошибка критична, выполнить немедленный откат:
        ```bash
        kubectl rollout undo statefulset/db -n database
        # → statefulset.apps/db rolled back
        ```

---

### 5. Ошибка `kubectl drain`: блокировка вывода узла из эксплуатации
*   **Симптомы:** Администратор пытается перевести узел в обслуживание, но команда `kubectl drain` падает с ошибкой.
*   **Диагностика:**
    ```bash
    kubectl drain worker-02 --delete-emptydir-data
    # → error: cannot delete DaemonSet-managed Pods (use --ignore-daemonsets to ignore): monitoring/node-exporter-4k2x9
    ```
*   **Причина:** По умолчанию `kubectl drain` защищает системные демоны. Так как поды DaemonSet привязаны к узлу, их выселение не имеет смысла — контроллер DaemonSet попытается создать их тут же снова.
*   **Решение:**
    Использовать флаг игнорирования DaemonSet:
    ```bash
    kubectl drain worker-02 --delete-emptydir-data --ignore-daemonsets
    # → node/worker-02 cordoned
    # → WARNING: ignoring DaemonSet-managed Pods: monitoring/node-exporter-4k2x9
    # → evicting pod production/web-api-78d469766b-4k2x9
    # → pod/web-api-78d469766b-4k2x9 evicted
    # → node/worker-02 drained
    ```

---

## Лучшие практики

### 1. Архитектурный чек-лист выбора контроллера

```
                    ┌─────────────────────────────────────────┐
                    │ Нужен запуск на каждом узле кластера?   │
                    └────────────────────┬────────────────────┘
                                         │
                         ДА              │              НЕТ
             ┌───────────────────────────┴───────────────────────────┐
             ▼                                                       ▼
      [ DaemonSet ]                                ┌───────────────────────────────────┐
      (Логи, метрики, CNI, CSI)                    │ Требуется постоянный RWO-диск     │
                                                   │ или уникальное имя/DNS реплики?   │
                                                   └─────────────────┬─────────────────┘
                                                                     │
                                                     ДА              │              НЕТ
                                         ┌───────────────────────────┴───────────────────────────┐
                                         ▼                                                       ▼
                                ┌─────────────────┐                                       [ Deployment ]
                                │ Число реплик    │                                       (Stateless веб,
                                │ строго равно 1? │                                       микросервисы,
                                └────────┬────────┘                                       очереди, RWX)
                                         │
                         ДА              │              НЕТ
             ┌───────────────────────────┴───────────────────────────┐
             ▼                                                       ▼
    ┌───────────────────────────┐                              [ StatefulSet ]
    │ Deployment с Recreate     │                              (БД, Kafka, ZooKeeper,
    │ либо StatefulSet          │                              etcd, RabbitMQ кворум)
    └───────────────────────────┘
```

---

### 2. Конфигурирование PodDisruptionBudget (PDB) под кворумные нагрузки

Для предотвращения потери кворума распределенных сервисов во время обновления кластера или вывода узлов администратор обязан настраивать PDB:

```yaml
# db-pdb.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: db-pdb
  namespace: database
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: db-cluster
```
*   Для кластера из 3 узлов (etcd, Patroni, ClickHouse) `minAvailable: 2` разрешает одновременное отключение строго **одного** узла.
*   Для stateless Deployment чаще используется `maxUnavailable: 20%` или `maxUnavailable: 1`, чтобы защитить общую пропускную способность сервиса.

Подробнее о политиках прерываний см. в документе **[PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md)**.

---

### 3. Ресурсные квоты и изоляция DaemonSet

Поскольку поды DaemonSet запускаются на каждом узле кластера (включая критичные узлы Control Plane), неверно заданные ресурсы могут вызвать исчерпание памяти (OOMKilled) рабочих приложений или самого `kubelet`:
1.  **Всегда задавать `resources.requests` и `resources.limits`:** Запрещено запускать DaemonSet без лимитов памяти.
2.  **Использовать `PriorityClass: system-node-critical`:** Для сетевых плагинов (Cilium, Calico) устанавливается наивысший приоритет, чтобы планировщик не вытеснял сетевые поды при нехватке ресурсов.
3.  **Ограничение размещения через `nodeSelector`:** Если агент предназначен только для узлов с определенным типом дисков или GPU, явно ограничивайте выборку:
    ```yaml
    spec:
      template:
        spec:
          nodeSelector:
            storage.role: ceph-osd
    ```

---

### 4. Анти-паттерны эксплуатации контроллеров

*   **Анти-паттерн 1: Запуск реплицированной СУБД внутри Deployment с несколькими репликами и одним PVC.** Приводит к моментальному повреждению файлов БД либо к зависанию подов в `Multi-Attach error`.
*   **Анти-паттерн 2: Принудительное удаление пода StatefulSet (`--force --grace-period=0`) при зависании узла.** На блочных СХД (SAN, iSCSI, Ceph) это прямой путь к двойному монтированию тома и необратимой порче файловой системы.
*   **Анти-паттерн 3: Использование `latest` тегов и стратегии `OnDelete` без четкого плана регламентных работ.** В `OnDelete` обновление откладывается до перезагрузки ноды; через полгода перезапуск узла приведет к запуску совершенно другого образа, разрушив совместимость протоколов.
*   **Анти-паттерн 4: Запуск stateless микросервисов в StatefulSet «на всякий случай».** Замедляет масштабирование, увеличивает время выкатки (последовательное ожидание Readiness каждого пода), блокирует `maxSurge` и создает ненужные объекты `ControllerRevision`.

---

## Дополнительная информация

### Архитектурный разбор сложных вопросов

> **Почему StatefulSet принципиально не поддерживает `maxSurge`?**
> 
> `Deployment` при `maxSurge: 1` создает Pod N+1, монтирует временную файловую систему или общий том RWX, ждет его готовности и только потом гасит старый Pod 1. Для `StatefulSet` это физически невозможно: под `db-0` жестко привязан к конкретному блочному тому `data-db-0`. Создать второй под с тем же томом нельзя, пока старый под не завершит все I/O-операции и не отмонтирует диск.

> **Как безопасно ускорить rollout StatefulSet?**
> 
> 1. Включить `maxUnavailable: 2` (Beta с v1.35, v1.37 по умолчанию), если размер кластера велик ($N \ge 7$) и потеря двух реплик гарантированно не разрушает кворум.
> 2. Для систем, не требующих строгого порядка старта/останова, переключить `podManagementPolicy: Parallel`. Это заставит поды подниматься параллельно, сохраняя индивидуальные PVC и FQDN.
> 3. Использовать `partition` для выкатки обновления на 1 реплику (Canary), а после успешного тестирования сбросить `partition: 0`.

> **Почему DaemonSet не использует `spec.replicas`?**
> 
> Целевое состояние DaemonSet определяется топологией вычислительных ресурсов кластера. За масштабирование отвечает `kube-scheduler` и `daemonset-controller`, отслеживающие добавление и удаление объектов `Node` через API-сервер.

---

### См. также

*   **[Ключевые концепции StatefulSet](./statefulset_core_concepts.md)** — архитектура Headless Service, порядковые индексы и алгоритмы инициализации.
*   **[Практическое руководство по StatefulSet](./statefulset_practical_guide.md)** — сценарии развертывания реальных кластеров БД и отладки.
*   **[Обзор StatefulSet](./statefulset_overview.md)** — фундаментальные механизмы контроллера.
*   **[Local PV vs CSI для StatefulSet](./statefulset_local_pv_vs_csi.md)** — выбор между локальными NVMe и сетевым хранилищем.
*   **[Kubernetes Deployment: Полное руководство](../Deployment/index.md)** — детальная настройка stateless-нагрузок.
*   **[DaemonSet: Архитектура и администрирование](../daemonset.md)** — системные агенты и управление узловыми демонами.
*   **[Бюджет прерывания подов (PDB)](../../Autoscaling/pod_disruption_budget.md)** — защита кворумов при регламентных работах.