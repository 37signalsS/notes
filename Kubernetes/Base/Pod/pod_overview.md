# Pod в Kubernetes: Обзор и архитектура

**Актуально для:** Kubernetes 1.30–1.32+

---

## Определения

**Pod (Под)** — атомарная и наименьшая развертываемая единица вычислительной нагрузки в Kubernetes. Представляет собой логическую абстракцию над группой из одного или нескольких тесно связанных контейнеров, гарантированно разделяющих сетевой стек, межпроцессное взаимодействие (IPC), пространства имен ядра Linux, тома хранения и планируемых на один и тот же рабочий узел (Node).

**Pod Sandbox (Песочница пода)** — низкоуровневое изолированное окружение на уровне операционной системы хоста, создаваемое контейнерным рантаймом (CRI: containerd, CRI-O) по запросу `kubelet` через вызов `RunPodSandbox`. Включает набор выделенных Linux-пространств имен (Network, IPC, UTS, Mount, опционально PID и User) и корневую cgroup пода.

**Pause Container (Инфраструктурный контейнер)** — специализированный минимальный системный контейнер (образ `registry.k8s.io/pause`), запускаемый рантаймом первым при создании Pod Sandbox. Он инициирует и удерживает открытыми разделяемые Linux namespaces и выступает в качестве процесса-сборщика зомби (PID 1 reaper) для осиротевших дочерних процессов внутри пода.

**Эфемерность Pod (Pod Ephemerality)** — архитектурное свойство Pod, означающее отсутствие встроенных механизмов самовосстановления. Объект Pod создается, получает уникальный идентификатор (UID), привязывается к узлу и существует до момента завершения процесса, удаления или гибели узла. При падении или эвикции Pod уничтожается безвозвратно; контроллеры оркестрации создают взамен новый экземпляр Pod с новым UID и новым IP-адресом.

**Static Pod (Статический под)** — Pod, управляемый напрямую демоном `kubelet` на конкретном узле без участия планировщика (`kube-scheduler`) и контроллеров API-сервера. Манифесты статических подов считываются локально из директории на хосте (по умолчанию `/etc/kubernetes/manifests`).

**Mirror Pod (Зеркальный под)** — объект Pod в Kube-API-Server, создаваемый `kubelet` для отражения статуса локального Static Pod. Позволяет операторам отслеживать состояние статических подов через `kubectl`, но не допускает управления ими через API (попытка удаления Mirror Pod через API не останавливает реальный процесс на узле).

**Pod Template (Шаблон пода)** — декларативная спецификация объекта Pod (`spec.template`), встраиваемая в манифесты высокоуровневых контроллеров (Deployment, StatefulSet, DaemonSet, Job) для автоматизированного тиражирования и обновления реплик.

**shareProcessNamespace** — директива спецификации Pod (`spec.shareProcessNamespace: true`), объединяющая контейнеры пода в общее пространство имен процессов (PID Namespace). Открывает видимость процессов между контейнерами через `/proc` и делегирует роль PID 1 контейнеру `pause`.

**Pod Overhead (Накладные расходы пода)** — фиксированный объем процессорного времени и оперативной памяти (`spec.overhead`), резервируемый планировщиком и cgroup-деревом для функционирования самой среды исполнения (RuntimeClass, например, микро-ВМ Kata Containers или gVisor) сверх лимитов пользовательских контейнеров.

---

## Архитектура и базовые концепции

### 1. Концептуальная модель Pod (Концепция «Логического хоста»)

В традиционной архитектуре Linux сервер (физический или виртуальный) выступает границей изоляции, внутри которой исполняется группа взаимодействующих процессов. Kubernetes переносит эту парадигму на контейнеры:

```
┌─────────────────────────────────── Pod (Логический хост) ───────────────────────────────────┐
│                                                                                             │
│  IP: 10.244.1.42        Hostname: web-app-pod        Shared IPC / Unix Domain Sockets        │
│                                                                                             │
│   ┌────────────────────────┐    Localhost Loopback    ┌────────────────────────┐            │
│   │ App Container          │ ◄──────────────────────► │ Sidecar Container      │            │
│   │ (Nginx / API Service)  │    (tcp://127.0.0.1)     │ (Log Shipper / Envoy)  │            │
│   └───────────┬────────────┘                          └───────────┬────────────┘            │
│               │                                                   │                         │
│               └───────────────────┬───────────────────────────────┘                         │
│                                   ▼                                                         │
│                      Shared Volumes (emptyDir / PVC)                                        │
│                      /var/log / /shared-data                                                │
│                                                                                             │
└───────────────────────────────────────┬─────────────────────────────────────────────────────┘
                                        ▼
                        Worker Node OS (Kernel, Cgroup, CNI)
```

**Ключевые свойства модели:**
* **Совместное планирование (Co-scheduling):** Все контейнеры, входящие в Pod, всегда атомарно назначаются и запускаются на одном физическом или виртуальном узле. Разделение контейнеров одного Pod между разными узлами невозможно.
* **Сетевая когерентность:** Все контейнеры Pod используют единый сетевой стек, один сетевой адрес (Pod IP) и единое пространство портов. Контейнеры связываются между собой через `localhost` с околонулевыми задержками (IPC / Loopback).
* **Связанное хранилище:** Тома данных декларируются на уровне спецификации Pod и монтируются в файловые системы нужных контейнеров в произвольные точки монтирования.

---

### 2. Анатомия Pod Sandbox и Pause Container

Развертывание Pod на узле выполняется `kubelet` через Container Runtime Interface (CRI). `kubelet` не запускает контейнеры приложения напрямую; сначала инициируется низкоуровневая инфраструктурная среда — **Pod Sandbox**.

```
  [ Kubelet ]
       │
       │ 1. RunPodSandbox(PodSandboxConfig) via CRI gRPC
       ▼
  [ Container Runtime (containerd / CRI-O) ]
       │
       ├─► 2. Создание Linux cgroup (/sys/fs/cgroup/kubepods.slice/...)
       ├─► 3. Создание пространств имен (net, ipc, uts)
       ├─► 4. Запуск Pause Container (registry.k8s.io/pause:3.10)
       ├─► 5. Вызов CNI плагина (cmdADD) -> настройка veth-пары и выделение IP
       │
       │ Sandbox готов (Ready)
       ▼
  [ Запуск пользовательских контейнеров ]
       ├─► 6. CreateContainer & StartContainer (Init Containers)
       ├─► 7. CreateContainer & StartContainer (Native Sidecars: restartPolicy: Always)
       └─► 8. CreateContainer & StartContainer (App Containers)
           (Все контейнеры присоединяются через setns() к пространствам имен Pause)
```

#### Роли Pause Container

1. **Создание и удержание Namespaces:** Создает пространства имен ядра Linux при старте Pod. Поскольку контейнеры приложения могут падать, завершаться и перезапускаться по `restartPolicy`, пространства имен должны оставаться активными. Пока жив Pause Container, сетевой адрес пода, открытые сокеты и IPC-очереди не разрушаются.
2. **Reaper процессов (PID 1):** В Unix-подобных ОС процесс с PID 1 обязан собирать статус завершения дочерних процессов (`waitpid()`). Если процесс-родитель внутри контейнера завершается раньше своих дочерних потоков, эти потоки становятся «сиротами» (orphan processes) и усыновляются процессом PID 1. При активированном `shareProcessNamespace: true` контейнер `pause` становится PID 1 для всего Pod, корректно перехватывает сигналы `SIGCHLD` и предотвращает утечку таблиц дескрипторов (предотвращает появление zombie-процессов).
3. **Обработка системных сигналов:** Pause-контейнер перехватывает `SIGTERM` и `SIGINT`, управляя последовательным каскадным завершением процессов внутри пространства имен.

#### Технические характеристики Pause Container

| Параметр | Значение / Детализация |
| :--- | :--- |
| **Образ** | `registry.k8s.io/pause:3.10` (стандарт для Kubernetes 1.30–1.32+). |
| **Бинарный файл** | Минимальный C-код (~300–700 КБ), выполняющий системный вызов `pause()` в бесконечном цикле после установки обработчиков `sigchld_handler`. |
| **Потребление ресурсов** | Memory: ~300–500 КБ RSS, CPU: 0% в режиме ожидания. Не тарифицируется в пользовательских квотах Pod. |
| **Жизненный цикл** | Запускается первым при создании пода, останавливается последним при `StopPodSandbox` после остановки всех контейнеров. |

---

### 3. Пространства имен ядра Linux (Namespaces) в Pod

Изоляция и совместное использование ресурсов между контейнерами внутри одного Pod конфигурируется через флаги системного вызова `clone()` и подключение через `setns()`:

| Namespace Linux | Поведение в Pod по умолчанию | Поведение при явной конфигурации | Системный эффект |
| :--- | :--- | :--- | :--- |
| **Network (net)** | **Разделяемый** (Shared) | `hostNetwork: true` | Общий стек TCP/IP, veth-пара, IP-адрес CNI, loopback `127.0.0.1`, общая таблица маршрутизации. При `hostNetwork` используется сетевой стек хоста. |
| **IPC (ipc)** | **Разделяемый** (Shared) | `hostIPC: true` | Общая память POSIX/System V shared memory (`/dev/shm`), очереди сообщений и семафоры между контейнерами пода. |
| **UTS (uts)** | **Разделяемый** (Shared) | `hostPID: true` | Единое системное имя узла (hostname) и доменное имя для всех контейнеров пода. |
| **PID (pid)** | **Изолированный** (Isolated) | `shareProcessNamespace: true` | По умолчанию каждый контейнер имеет собственный PID 1 (свой процесс приложения). При включении `shareProcessNamespace` все процессы видны во всех контейнерах через `/proc`. |
| **Mount (mnt)** | **Изолированный** (Isolated) | Монтирование общих Volumes | Файловая система каждого контейнера изолирована (собственный rootfs). Обмен файлами происходит только через явно смонтированные точки монтирования томов. |
| **User (user)** | **Изолированный** от хоста (K8s 1.30+ GA/Beta) | `spec.hostUsers: false` | Отображение (UID/GID mapping) непривилегированного пользователя внутри контейнера на отдельный пул UID хоста, предотвращающее root-эскалацию на узел. |

---

### 4. Иерархия Cgroups (v1 и v2) на уровне узла

Kubernetes изолирует ресурсы пода не через абстракции CRI, а через контрольные группы ядра Linux (**cgroups**). На современных дистрибутивах Linux с поддержкой **cgroups v2** (systemd cgroup driver) иерархия строится следующим образом:

```
/sys/fs/cgroup/
  └── kubepods.slice/
        ├── kubepods-burstable.slice/
        │     └── kubepods-burstable-pod<Pod-UID>.slice/
        │           ├── cgroup.procs (Pause Container)
        │           ├── cri-containerd-<Container1-ID>.scope/ (App Container)
        │           │     ├── cpu.max
        │           │     ├── cpu.weight
        │           │     └── memory.max
        │           └── cri-containerd-<Container2-ID>.scope/ (Sidecar Container)
        │                 ├── cpu.max
        │                 └── memory.max
        └── kubepods-besteffort.slice/
```

* **Pod-level Cgroup:** `kubelet` создает родительскую cgroup для пода (`pod<UID>.slice`). Лимиты этой cgroup вычисляются как сумма ресурсов всех контейнеров пода плюс `spec.overhead`.
* **Container-level Cgroup:** Каждый контейнер пода запускается в дочерней scope-группе, где действуют индивидуальные `limits.cpu` (`cpu.max`) и `limits.memory` (`memory.max`).
* **Поведение OOM:** Если лимит памяти превышает отдельный контейнер, ядро Linux убивает процесс внутри этого контейнера (`OOMKilled`, Exit Code 137), а `pause` контейнер и соседние контейнеры продолжают работу. Если же суммарное потребление пода превышает лимит родительской cgroup пода (например, за счет оверхеда runtime или shared memory `/dev/shm`), ядро может ликвидировать процесс с наибольшим `oom_score_adj`.

---

### 5. Сетевая модель Pod

Kubernetes реализует модель «IP-per-Pod». Это накладывает строгие требования на взаимодействие:

```
[ Pod A (10.244.1.10) ]                   [ Pod B (10.244.2.20) ]
  ├── container-1 (port 8080)               ├── container-1 (port 8080)  <-- Порты не конфликтуют
  └── container-2 (port 9090)               └── container-2 (port 9091)      (разные Pod IP)
            │                                         │
       (veth0_podA)                              (veth0_podB)
            │                                         │
            ▼                                         ▼
   [ Host Bridge / CNI ]                     [ Host Bridge / CNI ]
   (Worker Node 1)                           (Worker Node 2)
            │                                         │
            └────────────── Physical Network ─────────┘
                       (No NAT / Flat Routing)
```

1. **Отсутствие NAT внутри кластера:** Все поды взаимодействуют друг с другом напрямую по IP-адресам без использования сетевой трансляции адресов (NAT), независимо от того, находятся они на одном узле или на разных.
2. **Конфликты портов внутри Pod:** Поскольку все контейнеры пода разделяют один сетевой интерфейс (`eth0`) и сетевой стек:
   * Контейнер А и Контейнер Б **не могут** одновременно открыть слушающий сокет на одном и том же порту (например, `0.0.0.0:8080`). Второй контейнер завершится аварийно с ошибкой `bind: address already in use`.
   * Контейнеры могут безопасно использовать одинаковые порты, только если они разнесены по разным Pod.
3. **hostPort vs hostNetwork:**
   * `hostPort`: Пробрасывает порт хоста на порт внутри Pod через iptables/nftables правила DNAT. Создает жесткую привязку: на одном узле может быть запущен только один под с данным `hostPort`.
   * `hostNetwork: true`: Полностью отключает изоляцию сетевого пространства имен. Pod использует сетевые интерфейсы самого хоста. Порты пода становятся напрямую портами хоста (применяется для CNI плагинов, Ingress Controller и node-exporter).

---

### 6. Классификация Pod: Static Pods vs Controller-Managed Pods

| Характеристика | Static Pod | Controller-managed Pod (Deployment / DaemonSet) | Bare Pod (`kubectl run`) |
| :--- | :--- | :--- | :--- |
| **Источник конфигурации** | Файл на диске узла (`/etc/kubernetes/manifests`) | Спецификация контроллера в etcd | Прямой манифест в etcd |
| **Управляющий компонент** | Демон `kubelet` конкретного узла | Controller Manager + Kube-Scheduler | Kube-Scheduler |
| **Роль Kube-Scheduler** | **Полностью игнорируется** (NodeName зашит) | Участвует в планировании и фильтрации узлов | Назначает узел по правилам фильтрации |
| **Отражение в API** | Создается Mirror Pod (Read-Only) | Полноценный объект Pod со связью `ownerReferences` | Одиночный объект Pod |
| **Реакция на `kubectl delete`** | Mirror Pod удаляется на секунду и пересоздается `kubelet` | Контроллер пересоздает Pod согласно desired state | Pod безвозвратно удаляется |
| **Реакция на сбой узла** | Ожидает перезапуска ОС узла | Контроллер эвакуирует/пересоздает Pod на другом узле | Остается в `Unknown` / `Terminating` |
| **Поведение при `kubectl drain`** | **Игнорируется** Eviction API (не выселяется) | Корректно завершается согласно PDB | Требует флага `--force` |
| **Типичные сценарии** | `etcd`, `kube-apiserver`, `kube-vip`, `keepalived` | Микросервисы, БД, агенты мониторинга | Однократные тесты сети |

---

### 7. Шаблоны Pod (Pod Template) и вычисление Hash

Высокоуровневые контроллеры управляют жизненным циклом подов не напрямую, а через генерацию дочерних объектов по шаблону `spec.template`.

```
[ Deployment: my-app ]
       │
       ▼ (вычисляет SHA-256 хеш от spec.template)
[ ReplicaSet: my-app-7d4b569584 ]  <-- Метка pod-template-hash=7d4b569584
       │
       ├─► Pod: my-app-7d4b569584-x8k92
       └─► Pod: my-app-7d4b569584-m4p11
```

* **Механизм `pod-template-hash`:** Контроллер Deployment берет содержимое `spec.template`, нормализует его, вычисляет 32-битный хеш FNV-1a (или 10-значный строковый хеш) и добавляет его в виде селектора и метки `pod-template-hash`.
* **Контроль версий:** Любое изменение спецификации шаблона (изменение образа, переменных окружения, лимитов) изменяет вычисленный хеш, приводя к созданию нового ReplicaSet и запуску процедуры плавного обновления (RollingUpdate).

---

### 8. Типы контейнеров внутри Pod

Современный Kubernetes (1.30–1.32+) поддерживает 4 типа контейнеров внутри единого Pod:

1. **App Containers (Основные контейнеры):** Исполняют основную бизнес-логику приложения. Запускаются параллельно после завершения этапа инициализации.
2. **Init Containers (`spec.initContainers`):** Исполняются **строго последовательно** до запуска основных контейнеров. Каждый init-контейнер обязан завершиться с кодом `0`. При ошибке весь Pod перезапускается в соответствии с `restartPolicy`.
3. **Native Sidecars (GA в K8s 1.32+, Beta в 1.29–1.31):** Контейнеры, описанные в блоке `spec.initContainers`, но содержащие директиву `restartPolicy: Always`. Они запускаются последовательно во время инициализации, дожидаются прохождения своих проб (`startupProbe` / `readinessProbe`), после чего управление передается следующим init- или app-контейнерам. Native Sidecar продолжает непрерывно работать параллельно с приложением и корректно останавливается **после** завершения app-контейнеров.
4. **Ephemeral Containers (`spec.ephemeralContainers`):** Временные контейнеры, добавляемые в работающий Pod через подресурс API `/ephemeralcontainers` (команда `kubectl debug`). Не имеют собственных портов, не могут перезапускаться и используются исключительно для траблшутинга и профилирования живых процессов.

---

### 9. Pod Overhead (Накладные расходы среды исполнения)

При использовании изолированных сред выполнения (RuntimeClass: Kata Containers, gVisor runsc) каждый Pod требует дополнительной памяти и CPU для работы ядра гостевой ОС или процесса-эмулятора.

```yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: kata-qemu
handler: kata-qemu
overhead:
  podFixed:
    cpu: "250m"
    memory: "350Mi"
```

Когда Pod запрашивает `runtimeClassName: kata-qemu`, планировщик `kube-scheduler` при поиске подходящего узла суммирует:
$$\text{Total Requests} = \sum \text{Container Requests} + \text{Pod Overhead}$$
Это гарантирует, что узел не уйдет в дефицит ресурсов из-за скрытого потребления самого гипервизора.

---

## Практические сценарии и конфигурации

### Сценарий 1: Production Multi-container Pod (App + Native Sidecar + Log Collector)

Комплексный пример промышленного Pod для Bare-Metal / On-Premises сред. Включает:
* Native Sidecar (локальный прокси Envoy) для шифрования/маршрутизации;
* Основное приложение с жестким профилем безопасности (`securityContext`);
* Sidecar для агрегации логов (Vector/Fluentbit) через общий том `emptyDir`;
* Проектируемые тома (Projected Volumes) с Downward API.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: production-service
  namespace: default
  labels:
    app.kubernetes.io/name: payment-gateway
    app.kubernetes.io/version: "1.32.0"
    app.kubernetes.io/component: backend
spec:
  restartPolicy: Always
  terminationGracePeriodSeconds: 60
  dnsPolicy: ClusterFirst
  volumes:
  - name: shared-logs
    emptyDir:
      sizeLimit: 1Gi
  - name: pod-metadata
    projected:
      sources:
      - downwardAPI:
          items:
          - path: "labels"
            fieldRef:
              fieldPath: metadata.labels
          - path: "ip"
            fieldRef:
              fieldPath: status.podIP
  # 1. Native Sidecar (инициализируется до основного приложения)
  initContainers:
  - name: local-mesh-proxy
    image: envoyproxy/envoy:v1.31.2
    restartPolicy: Always
    command: ["envoy", "-c", "/etc/envoy/envoy.yaml"]
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
      limits:
        cpu: 500m
        memory: 256Mi
    startupProbe:
      httpGet:
        path: /ready
        port: 9901
      failureThreshold: 30
      periodSeconds: 2
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      runAsNonRoot: true
      runAsUser: 10001
      capabilities:
        drop: ["ALL"]
  # 2. Основные контейнеры приложения
  containers:
  - name: api-server
    image: internal-registry.local/finance/api:1.32.0
    ports:
    - name: http
      containerPort: 8080
      protocol: TCP
    resources:
      requests:
        cpu: 500m
        memory: 512Mi
      limits:
        cpu: 1000m
        memory: 1Gi
    startupProbe:
      httpGet:
        path: /healthz
        port: 8080
      failureThreshold: 15
      periodSeconds: 2
    livenessProbe:
      httpGet:
        path: /healthz
        port: 8080
      periodSeconds: 10
      timeoutSeconds: 2
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      periodSeconds: 5
      timeoutSeconds: 2
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      runAsNonRoot: true
      runAsUser: 10002
      capabilities:
        drop: ["ALL"]
    volumeMounts:
    - name: shared-logs
      mountPath: /var/log/app
    - name: pod-metadata
      mountPath: /etc/podinfo
      readOnly: true
  # 3. Sidecar сбора логов
  - name: log-collector
    image: timberio/vector:0.39.0-alpine
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 200m
        memory: 128Mi
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      runAsNonRoot: true
      runAsUser: 10003
      capabilities:
        drop: ["ALL"]
    volumeMounts:
    - name: shared-logs
      mountPath: /var/log/app
      readOnly: true
```

#### Проверка состояния компонентов Pod

```bash
# 1. Проверка готовности контейнеров (все 3 контейнера в READY)
kubectl get pod production-service -o wide
# → NAME                 READY   STATUS    RESTARTS   AGE   IP            NODE     NOMINATED NODE   READINESS GATES
# → production-service   3/3     Running   0          45s   10.244.1.42   node-2   <none>           <none>

# 2. Проверка порядка старта контейнеров через Events
kubectl get events --field-selector involvedObject.name=production-service --sort-by='.metadata.creationTimestamp'
# → 0s    Normal   Scheduled   pod/production-service   Successfully assigned default/production-service to node-2
# → 0s    Normal   Pulled      pod/production-service   Container image "envoyproxy/envoy:v1.31.2" already present on node
# → 0s    Normal   Created     pod/production-service   Created container local-mesh-proxy
# → 1s    Normal   Started     pod/production-service   Started container local-mesh-proxy
# → 3s    Normal   Pulled      pod/production-service   Container image "internal-registry.local/finance/api:1.32.0" already present
# → 3s    Normal   Created     pod/production-service   Created container api-server
# → 4s    Normal   Started     pod/production-service   Started container api-server
# → 4s    Normal   Started     pod/production-service   Started container log-collector

# 3. Проверка передачи логов между контейнерами через общий том
kubectl exec production-service -c log-collector -- ls -lh /var/log/app
# → -rw-r--r-- 1 10002 10002 24.5K Oct 17 14:30 app.log
```

---

### Сценарий 2: Совместное использование PID Namespace (`shareProcessNamespace`)

Сценарий необходим, когда вспомогательному контейнеру требуется мониторить процесс основного приложения, отправлять сигналы (`SIGHUP` для перезагрузки конфигурации без рестарта контейнера) или инспектировать память.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: pid-sharing-demo
  namespace: default
spec:
  shareProcessNamespace: true
  containers:
  - name: nginx-server
    image: nginx:1.27-alpine
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 200m
        memory: 128Mi
  - name: config-reloader
    image: busybox:1.36
    command: ["sh", "-c", "sleep 3600"]
    resources:
      requests:
        cpu: 10m
        memory: 32Mi
      limits:
        cpu: 50m
        memory: 64Mi
```

#### Проверка и валидация пространства PID

```bash
# 1. Просмотр дерева процессов из контейнера config-reloader
kubectl exec pid-sharing-demo -c config-reloader -- ps aux
# → PID   USER     TIME  COMMAND
# →   1   root     0:00  /pause
# →   7   root     0:00  nginx: master process nginx -g daemon off;
# →  14   101      0:00  nginx: worker process
# →  20   root     0:00  sleep 3600
# →  26   root     0:00  ps aux

# 2. Отправка сигнала перезагрузки Nginx из соседнего контейнера
kubectl exec pid-sharing-demo -c config-reloader -- kill -HUP 7
# → (Процесс master Nginx перечитывает конфигурацию без сброса соединений)

# 3. Проверка логов Nginx на предмет получения сигнала
kubectl logs pid-sharing-demo -c nginx-server | tail -n 2
# → 2026/10/17 14:35:10 [notice] 7#7: signal 1 (SIGHUP) received, reconfiguring
# → 2026/10/17 14:35:10 [notice] 7#7: reconfiguring done
```

---

### Сценарий 3: Развертывание и эксплуатация Static Pod (Bare-Metal / On-Premises)

Статические поды применяются системными инженерами для запуска критических сервисов локального узла: локальных DNS-кэшеров, VIP-менеджеров (`kube-vip`), вспомогательных балансировщиков (`haproxy`).

```yaml
# Файл на целевом worker-узле: /etc/kubernetes/manifests/node-watchdog.yaml
apiVersion: v1
kind: Pod
metadata:
  name: node-watchdog
  namespace: kube-system
  labels:
    tier: node-management
spec:
  hostNetwork: true
  priorityClassName: system-node-critical
  containers:
  - name: agent
    image: internal-registry.local/sysops/node-watchdog:1.2.0
    resources:
      requests:
        cpu: 50m
        memory: 48Mi
      limits:
        cpu: 100m
        memory: 96Mi
    volumeMounts:
    - name: host-root
      mountPath: /host
      readOnly: true
  volumes:
  - name: host-root
    hostPath:
      path: /
      type: Directory
```

#### Проверка и управление жизненным циклом Static Pod

```bash
# 1. Размещение манифеста на узле (выполняется администратором узла)
sudo cp node-watchdog.yaml /etc/kubernetes/manifests/

# 2. Проверка реакции kubelet через системный журнал узла
journalctl -u kubelet -n 20 --no-pager | grep "node-watchdog"
# → Oct 17 14:40:02 node-1 kubelet[1245]: I1017 14:40:02.102 "Watching for new static pod manifests" path="/etc/kubernetes/manifests"
# → Oct 17 14:40:02 node-1 kubelet[1245]: I1017 14:40:02.105 "Creating static pod" pod="kube-system/node-watchdog-node-1"

# 3. Проверка появления Mirror Pod в API-сервере
kubectl get pods -n kube-system -l tier=node-management -o wide
# → NAME                         READY   STATUS    RESTARTS   AGE   IP            NODE     NOMINATED NODE   READINESS GATES
# → node-watchdog-node-1         1/1     Running   0          30s   192.168.1.11  node-1   <none>           <none>

# 4. Демонстрация невозможности удаления через Kube-API-Server
kubectl delete pod node-watchdog-node-1 -n kube-system
# → pod "node-watchdog-node-1" deleted
kubectl get pod node-watchdog-node-1 -n kube-system
# → NAME                     READY   STATUS    RESTARTS   AGE
# → node-watchdog-node-1     1/1     Running   0          2s   # Mirror Pod мгновенно пересоздан Kubelet!

# 5. Корректное удаление Static Pod (удалением локального файла)
sudo rm -f /etc/kubernetes/manifests/node-watchdog.yaml
# → Kubelet обнаруживает удаление inotify-событием, останавливает контейнеры и очищает Mirror Pod.
```

---

### Сценарий 4: Низкоуровневая диагностика сетевого стека через Diagnostic Pod

Специализированный Pod для отладки сетевой связности внутри пространства CNI и разрешения DNS в bare-metal кластерах без загрязнения рабочих образов утилитами отладки.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: net-diagnostics
  namespace: default
spec:
  restartPolicy: Never
  containers:
  - name: netshoot
    image: nicolaka/netshoot:v0.13
    command: ["sleep", "1800"]
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 250m
        memory: 128Mi
    securityContext:
      capabilities:
        add: ["NET_ADMIN", "NET_RAW"]
```

#### Диагностические тесты

```bash
# 1. Проверка разрешения внутренних DNS-имен сервисов через CoreDNS
kubectl exec net-diagnostics -- dig +short kubernetes.default.svc.cluster.local
# → 10.96.0.1

# 2. Проверка задержки и MTU сетевого пути до целевого узла/пода (детектирование MTU blackhole)
kubectl exec net-diagnostics -- ping -M do -s 1420 -c 3 10.244.2.15
# → 1428 bytes from 10.244.2.15: icmp_seq=1 ttl=63 time=0.412 ms
# → 3 packets transmitted, 3 received, 0% packet loss

# 3. Проверка доступности портов TCP и согласования сокетов
kubectl exec net-diagnostics -- nc -zvw 2 internal-service 5432
# → Connection to internal-service (10.96.14.88) 5432 port [tcp/postgresql] succeeded!
```

---

## Операции и команды диагностики

### 1. Низкоуровневые операции на узле (`crictl` и Linux CLI)

При отказах API-сервера, зависании Kubelet или проблемах с CNI инженер SRE проводит диагностику напрямую на узле хоста через интерфейс `crictl`:

```bash
# Найти Pod Sandbox по имени или UID
crictl pods --name production-service
# → POD ID         CREATED         STATE    NAME                 NAMESPACE   ATTEMPT
# → 4e9d1a8c3f2b   5 minutes ago   Ready    production-service   default     0

# Инспекция параметров Pod Sandbox (пространства имен, IP CNI, DNS)
crictl inspectp 4e9d1a8c3f2b | jq '.info.linux.namespaces'
# → {
# →   "options": {
# →     "network": "/proc/12890/ns/net",
# →     "ipc": "/proc/12890/ns/ipc",
# →     "uts": "/proc/12890/ns/uts"
# →   }
# → }

# Найти pause-контейнер и связанные контейнеры внутри sandbox
crictl ps --pod 4e9d1a8c3f2b -a
# → CONTAINER       IMAGE                               CREATED         STATE     NAME               ATTEMPT
# → a81b9c2d3e4f    internal-registry.local/api:1.32.0   4 minutes ago   Running   api-server         0
# → f9e8d7c6b5a4    timberio/vector:0.39.0-alpine       4 minutes ago   Running   log-collector      0
# → 112233445566    envoyproxy/envoy:v1.31.2            5 minutes ago   Running   local-mesh-proxy   0

# Просмотр сетевых сокетов, открытых в network namespace пода
PID=$(crictl inspectp 4e9d1a8c3f2b | jq '.info.pid')
sudo nsenter -t $PID -n ss -tulpn
# → Netid State  Recv-Q Send-Q Local Address:Port  Peer Address:Port Process
# → tcp   LISTEN 0      128          0.0.0.0:8080       0.0.0.0:*     users:(("api-server",pid=13245,fd=6))
# → tcp   LISTEN 0      128        127.0.0.1:9901       0.0.0.0:*     users:(("envoy",pid=12950,fd=12))

# Проверка лимитов cgroups v2 пода на хосте
cat /sys/fs/cgroup/kubepods.slice/kubepods-burstable.slice/kubepods-burstable-pod$(crictl inspectp 4e9d1a8c3f2b | jq -r .info.config.metadata.uid | tr '-' '_').slice/memory.current
# → 268435456 # (Текущее потребление памяти всеми контейнерами пода: 256 MiB)
```

---

### 2. Высокоуровневые операции кластера (`kubectl`)

```bash
# Получение расширенной информации о размещении подов и IP
kubectl get pods -o wide -n default --show-labels
# → NAME                 READY   STATUS    RESTARTS   AGE   IP            NODE     LABELS
# → production-service   3/3     Running   0          10m   10.244.1.42   node-2   app.kubernetes.io/name=payment-gateway...

# Просмотр детального графа статусов (Conditions, ContainerStatuses, LastState)
kubectl get pod production-service -o jsonpath='{range .status.conditions[*]}{.type}{"\t"}{.status}{"\t"}{.message}{"\n"}{end}'
# → PodReadyToStartContainers   True
# → Initialized                 True
# → Ready                       True
# → ContainersReady             True
# → PodScheduled                True

# Вывод причин завершения контейнера (полезно при расследовании падений)
kubectl get pod production-service -o jsonpath='{.status.containerStatuses[*].lastState.terminated}' | jq .
# → {
# →   "exitCode": 137,
# →   "reason": "OOMKilled",
# →   "startedAt": "2026-10-17T14:20:00Z",
# →   "finishedAt": "2026-10-17T14:25:00Z"
# → }

# Стриминг логов сразу всех контейнеров мультиконтейнерного пода
kubectl logs production-service --all-containers=true --tail=50 --prefix=true -f
# → [pod/production-service/api-server] 14:45:01 Processing HTTP GET /healthz
# → [pod/production-service/local-mesh-proxy] [14:45:01] "GET /healthz HTTP/1.1" 200
```

---

## Диагностика и устранение неисправностей

### 1. Pod завис в статусе `ContainerCreating`

**Симптомы:**
Pod долго находится в статусе `ContainerCreating`, фаза не переходит в `Running`, в `kubectl describe pod` фиксируются таймауты.

```
Events:
  Warning  FailedCreatePodSandBox  45s  kubelet  Failed to create pod sandbox: rpc error: code = Unknown desc = failed to set up sandbox container: networkPlugin cni failed: no IP addresses available in range set
```

**Причины:**
1. Ошибка CNI-плагина: исчерпан пул IP-адресов подсети узла (IPAM exhaustion);
2. Локальный реестр образов недоступен, либо узел не может скачать инфраструктурный образ `registry.k8s.io/pause:3.10`;
3. Проблемы монтирования томов хранения: CSI-драйвер не завершил процедуру `AttachVolume` / `MountDevice`.

**Диагностика и решение:**

```bash
# 1. Изоляция причины через фильтрацию системных событий
kubectl describe pod <pod-name> | grep -A 10 "Events:"

# 2. Если ошибка "no IP addresses available":
# Проверить аллокацию IPAM на узле (пример для Calico/Cilium)
kubectl get blockaffinities -l kubernetes.io/hostname=<node-name>
# Решение: очистить зависшие интерфейсы или расширить Pod CIDR узла.

# 3. Если ошибка связана с pause container:
# Проверить наличие образа pause в локальном кэше рантайма узла
crictl images | grep pause
# Решение: вручную загрузить pause образ на узел:
crictl pull registry.k8s.io/pause:3.10
```

---

### 2. Конфликт сетевых портов (`bind: address already in use`)

**Симптомы:**
Один из контейнеров в мультиконтейнерном Pod циклически падает со статусом `CrashLoopBackOff`, второй работает штатно.

```bash
kubectl logs <pod-name> -c failed-container
# → 2026/10/17 14:50:00 [emerg] 1#1: bind() to 0.0.0.0:8080 failed (98: Address already in use)
```

**Причины:**
Два контейнера внутри одного Pod пытаются слушать одинаковый TCP или UDP порт. Поскольку они разделяют единый сетевой namespace `pause`-контейнера, коллизия сокетов блокирует запуск второго процесса.

**Решение:**
1. Развести порты прослушивания сервисов по разным номерам через конфигурационные файлы или переменные окружения;
2. Если контейнеры функционально независимы и не требуют общего localhost — разделить их на два отдельных Pod.

---

### 3. Утечка PID и зомби-процессы (Zombie / Orphan Processes)

**Симптомы:**
На узле нарастает общее количество процессов (`kernel: cgroups: fork rejected by pids.max`), контейнеры не могут порождать новые потоки (`fork: Cannot allocate memory`), хотя памяти достаточно.

**Причины:**
* Включена опция `shareProcessNamespace: true`, но приложение запускает дочерние подпроцессы через shell-скрипты без вызова `wait()`.
* Либо используется устаревший базовый образ pause/контейнера, где PID 1 не перехватывает `SIGCHLD`.

**Диагностика:**

```bash
# Проверка наличия зомби-процессов (состояние 'Z') внутри Pod
kubectl exec <pod-name> -c <container-name> -- ps aux | grep -w "Z"
# → 1450 app 0:00 [worker.sh] <defunct>
# → 1451 app 0:00 [worker.sh] <defunct>

# Проверка лимита pids cgroup на узле
cat /sys/fs/cgroup/kubepods.slice/.../pids.current
cat /sys/fs/cgroup/kubepods.slice/.../pids.max
```

**Решение:**
1. Использовать специализированные инициализаторы (например, утилиту `tini` в качестве entrypoint контейнера: `ENTRYPOINT ["/sbin/tini", "--", "/entrypoint.sh"]`);
2. Обрабатывать сигналы завершения дочерних процессов в коде сервиса;
3. Настроить лимиты `podPidsLimit` в конфигурации Kubelet.

---

### 4. Сбои и рассинхронизация Static Pods и Mirror Pods

**Симптомы:**
Файл манифеста обновлен в `/etc/kubernetes/manifests/`, но `kubectl get pod` показывает старую конфигурацию, либо под исчез из вывода.

**Причины:**
1. Ошибка синтаксиса YAML в манифесте на диске узла (Kubelet молча отбрасывает некорректный файл);
2. Kube-API-Server недоступен, из-за чего Kubelet не может обновить состояние Mirror Pod;
3. Рассинхронизация токенов аутентификации узла (Kubelet Node TLS).

**Диагностика и решение:**

```bash
# 1. Валидация синтаксиса манифеста локально на узле
kubectl apply --dry-run=client -f /etc/kubernetes/manifests/kube-apiserver.yaml
# → Error: error parsing /etc/kubernetes/manifests/kube-apiserver.yaml: yaml: line 14: mapping values are not allowed in this context

# 2. Поиск ошибок парсинга в журнале Kubelet
journalctl -u kubelet --no-pager | grep -iE "failed to parse|static pod"
# → kubelet[1245]: E1017 14:55:00.123 "Failed to create static pod from manifest" path="/etc/kubernetes/manifests/kube-apiserver.yaml" err="..."

# 3. При зависании старого Mirror Pod в etcd:
kubectl delete pod <mirror-pod-name> -n kube-system --force --grace-period=0
# → Kubelet автоматически пересоздаст актуальный Mirror Pod.
```

---

### 5. OOMKilled на уровне cgroup Pod vs cgroup контейнера

**Симптомы:**
Контейнер внезапно завершает работу с кодом выхода 137 (`OOMKilled`), но `limits.memory` контейнера не был превышен.

**Причины:**
* Превышена общая квота памяти на уровне Pod cgroup (например, разрастание разделяемой памяти `/dev/shm` в томах `emptyDir.medium: Memory` или утечка в pause-контейнере/sidecar).
* Сработал OOM Killer на уровне операционной системы хоста из-за общего дефицита памяти узла.

**Диагностика:**

```bash
# 1. Анализ системных событий ядра Linux на узле
sudo dmesg -T | grep -iE "oom[-_]killer|killed process"
# → [Sat Oct 17 14:58:12 2026] Memory cgroup out of memory: Killed process 13456 (api-server) total-vm:2104500kB, anon-rss:1048576kB, file-rss:1240kB, shmem-rss:0kB oom_score_adj:998

# 2. Проверка использования памяти shm/tmpfs томов
kubectl exec <pod-name> -- df -h /dev/shm
# → Filesystem      Size  Used Avail Use% Mounted on
# → shm             512M  512M     0 100% /dev/shm   # Исчерпание памяти shm!
```

**Решение:**
1. Ограничить размер `emptyDir` через директиву `sizeLimit`;
2. Сбалансировать `requests.memory` и `limits.memory` всех контейнеров пода;
3. Для критических сервисов использовать QoS класс **Guaranteed** (`requests` == `limits` по CPU и Memory для всех контейнеров), что гарантирует присвоение `oom_score_adj = -997` и защищает от первоочередного уничтожения ядром.

---

## Лучшие практики для DevOps, SRE и системных администраторов

### 1. Архитектурное проектирование Multi-container Pods

* **Соблюдение Single Concern Principle:** Не упаковывайте независимые микросервисы в один Pod только ради совместного размещения. Несколько контейнеров в одном Pod оправданы исключительно тогда, когда их жизненный цикл неразрывно связан (соотношение 1:1, общий доступ к локальным файлам или разделяемой памяти).
* **Применение Native Sidecars:** Для служебных задач (прокси Envoy, mTLS-агенты, Vault-агенты) переводите манифесты на нативные сайдкары (`initContainers` с `restartPolicy: Always`). Это устраняет гонки запуска (когда основное приложение стартовало раньше, чем поднялся локальный сетевой прокси).

### 2. Защита и изоляция на Bare-Metal / On-Premises узлах

* **Ограничение привилегий (`securityContext`):**
  * Всегда объявляйте `runAsNonRoot: true` и назначайте фиксированный `runAsUser` с UID $\ge 10000$.
  * Включайте `readOnlyRootFilesystem: true`. Для записи временных файлов подключайте локальный том `emptyDir`.
  * Блокируйте эскалацию прав: `allowPrivilegeEscalation: false`.
  * Сбрасывайте привилегии ядра: `capabilities: { drop: ["ALL"] }`.
* **Запрет `hostNetwork`, `hostPID`, `hostIPC`:** Использование пространств имен хоста допустимо только для инфраструктурных системных компонентов (CNI, kube-proxy). Случайное использование `hostNetwork` открывает доступ к локальным сокетам хоста (включая loopback kubelet `10250` и etcd `2379`).

### 3. Ресурсное планирование и предотвращение сбоев узла

* **Фиксация QoS Guaranteed для mission-critical нагрузок:** Устанавливайте одинаковые значения `requests` и `limits` по CPU и памяти. Это предотвратит вытеснение пода демоном `kubelet` при исчерпании ресурсов хоста (`NodeMemoryPressure`).
* **Квотирование эфемерного диска:** Всегда определяйте `resources.limits.ephemeral-storage`. Без этого агрессивное логирование приложения в `/var/log` способно переполнить корневой раздел хоста, переведя узел в статус `DiskPressure` с последующей эвикцией всех соседних подов.

### 4. Управление корректным завершением (Graceful Shutdown)

* **Корректный PID 1 и обработка `SIGTERM`:** Приложение внутри контейнера обязано быть процессом PID 1 (использование синтаксиса JSON в Dockerfile: `ENTRYPOINT ["./app"]`, а не `ENTRYPOINT ./app`). Контейнер должен перехватывать сигнал `SIGTERM`, завершать активные транзакции и закрывать сетевые соединения.
* **Синхронизация `terminationGracePeriodSeconds`:** Время льготного завершения пода должно с запасом превышать таймаут закрытия соединений внутри приложения (например, если приложение завершает запросы до 30 секунд, установите `terminationGracePeriodSeconds: 45–60`).

---

## Дополнительная информация

**Связанные документы в базе знаний:**

* [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md) — детальный анализ фаз, условий (`PodConditions`), зондов доступности и механики Graceful Termination.
* [Паттерны Sidecar в Kubernetes](./pod_sidecar_patterns.md) — архитектурные шаблоны Ambassador, Adapter и Native Sidecars с примерами конфигураций.
* [Инициализирующие контейнеры (Init Containers)](./pod_init_containers.md) — специфика последовательного запуска и подготовки сетевого окружения.
* [Эфемерные контейнеры](./ephemeral_containers.md) — оперативная отладка живых подов через `kubectl debug`.
* [Лучшие практики написания манифестов Pod](./pod_best_practices.md) — углубленный аудит безопасности манифестов и оптимизация ресурсов ядра.
* [Перезапуск и устойчивость Pod](./pod_restarts.md) — разбор политик `restartPolicy`, циклов экспоненциального бэкоффа и состояний `CrashLoopBackOff`.
* [Продвинутые темы Pod](./pod_advanced_topics.md) — управление `RuntimeClass`, `Pod Overhead`, динамическое изменение ресурсов (In-Place Pod Resize) и Scheduling Gates.
* [Пользовательские пространства имен (User Namespaces)](./user_namespaces.md) — настройка безопасности `hostUsers: false` для изоляции UID/GID на уровне ядра.
* [Архитектура и управление Kubelet](../../Concepts/kubelet.md) — внутренние механизмы взаимодействия Kubelet, CRI и CNI на узле.
* [Классы качества обслуживания (QoS) и управление ресурсами](../../Scheduling/qos_limit_and_requests.md) — влияние `requests`/`limits` на алгоритм эвикции и OOM score.
* [Компоненты Control Plane и Kubeadm](../../Installation/kubeadm/index.md) — развертывание базовой инфраструктуры кластера на базе Static Pods.
