# Подготовка к высоким нагрузкам в Kubernetes

**Актуально для:** Kubernetes 1.30–1.35+ (Bare-Metal / On-Premise)

---

## Определения

*   **Высокая нагрузка (High Load)** в контексте Kubernetes — эксплуатационный режим, при котором интенсивность входящих сетевых запросов, транзакций или фоновых вычислений приближает потребление ресурсов узлов (CPU, RAM, Network Bandwidth, IOPS) или пропускную способность компонентов платформы (API Server, etcd, CoreDNS, CNI) к физическим или архитектурным лимитам.
*   **CFS Throttling (Completely Fair Scheduler Quota Throttling)** — принудительное ограничение выделенного времени CPU процессам контейнера со стороны планировщика ядра Linux при исчерпании квоты (`cpu.max` в cgroups v2 / `cpu.cfs_quota_us` в cgroups v1) за текущий расчетный период (обычно 100 мс). Проявляется в резком росте хвостовой задержки (P99/P99.9 latency) даже при суммарной загрузке процессора узла ниже 50%.
*   **Насыщение (Saturation)** — состояние подсистемы (очереди сокетов, CPU runqueue, IO queue, Conntrack table), при котором она перестает справляться с потоком задач без накопления очередей, вызывая деградацию времени отклика по закону Литтла (Little's Law).
*   **Conntrack Exhaustion** — переполнение таблицы состояний межсетевого экрана ядра Linux (`nf_conntrack`). Приводит к сбросу новых и транзитных TCP/UDP пакетов на уровне сетевого стека узла с ошибкой `table full, dropping packet`.
*   **UDP DNS Race Condition** — гонка за запись в таблице `nf_conntrack` при одновременных параллельных DNS-запросах (A и AAAA записи) от glibc/musl через общий UDP-сокет. Вызывает случайные задержки разрешения имен в 5 секунд.
*   **Каскадный сбой (Cascading Failure)** — лавинообразное распространение отказа от деградировавшего микросервиса к зависимым компонентам из-за исчерпания пулов соединений, тайм-аутов и повторных попыток (Retry Storm).
*   **Load Shedding (Сброс нагрузки)** — архитектурная стратегия управляемого превентивного отбрасывания низкоприоритетного или избыточного трафика (HTTP 429/503) для сохранения работоспособности ядра системы.
*   **PLEG (Pod Lifecycle Event Generator)** — внутренний модуль Kubelet, опрашивающий контейнерный рантайм (containerd/CRI-O) о состоянии контейнеров. При чрезмерной плотности подов или блокировках I/O переходит в состояние `PLEG is not healthy`, приводя узел в статус `NotReady`.

---

## Базовые концепции

### Анатомия узких мест на уровне платформы

При возникновении пиковых нагрузок деградация в On-Premise / Bare-Metal инфраструктуре развивается на четырех независимых уровнях:

```
[ L1: Сетевой стек ядра Linux узла ]  →  Conntrack, backlog сокетов, кольцевые буферы NIC (RX/TX)
                ↓
[ L2: Сервисная сеть и DNS ]          →  CoreDNS saturation, iptables lock contention, eBPF/IPVS
                ↓
[ L3: Плоскость управления (Control Plane) ] → etcd fsync latency, API Server serialization, Kubelet PLEG
                ↓
[ L4: Среда исполнения подов (CRI/cgroups) ]  → CFS Throttling, OOM Killer, IO contention, GC-паузы
```

1.  **Сетевой стек и ядро узла:** Дефолтные настройки дистрибутивов Linux рассчитаны на офисные серверы. Ограничения очередей сокетов (`somaxconn`), размер диапазона временных портов (`ip_local_port_range`) и лимит таблицы `nf_conntrack_max` приводят к отбрасыванию пакетов задолго до насыщения сетевого интерфейса.
2.  **Service Discovery и CoreDNS:** Базовый DNS-резолвинг на тысячах подов создает огромную нагрузку на CoreDNS. Наличие параметра `ndots: 5` по умолчанию в `/etc/resolv.conf` вынуждает резолвер совершать до 5 холостых запросов к кластерному домену на каждое обращение к внешнему ресурсу.
3.  **Маршрутизация трафика в кластере:** При тысячах сервисов и эндпоинтов режим `iptables` в `kube-proxy` страдает от последовательного обхода правил $O(N)$ и глобальных блокировок при обновлениях (`iptables-restore`). В high-load кластерах стандартном является использование `IPVS` или бессервисного `eBPF` (Cilium).
4.  **Планировщик и Control Plane:** Массовое создание подов при автоскейлинге или рестарте перегружает `etcd` операциями записи и вызывает сериализационные блокировки в `kube-apiserver`.
5.  **cgroups v2 и CFS:** Использование жестких лимитов CPU (`limits.cpu`) включает планировщик CFS. Если поток приложения выполняет кратковременный всплеск вычислений, он исчерпывает миллисекундную квоту и замораживается ядром до начала следующего периода.

### Механика CFS Throttling в cgroups v2

В cgroups v2 квота задается в файле `cpu.max` парой значений: `[quota] [period]`. 
По умолчанию `period` составляет `100000` мкс (100 мс). 
Лимит в `2000m` (2 CPU) соответствует квоте `200000 100000`.

*   Если многопоточное приложение запускает 8 воркеров на узле с 32 ядрами, суммарная квота в 200 мс будет израсходована всеми потоками всего за 25 мс реального времени ($8 \times 25\text{ мс} = 200\text{ мс}$).
*   Оставшиеся 75 мс текущего периода все 8 потоков будут принудительно заблокированы ядром, независимо от наличия свободных ядер на физическом сервере.
*   **cgroups v2 CPU Bursting:** Начиная с ядер Linux 5.14+ и Kubernetes 1.30+ поддерживается механизм накопления неизрасходованной квоты предыдущих периодов (`cpu.max.burst`), позволяющий сглаживать пики без троттлинга.

### Стратегии автомасштабирования на On-Premise

В отличие от публичных облаков, где доступна практически бесконечная эластичность узлов, в Bare-Metal инфраструктуре физический пул серверов жестко фиксирован:

*   **Горизонтальное автомасштабирование рабочих нагрузок (HPA v2):** Масштабирование числа реплик в рамках существующего пула емкости. Требует обязательной настройки профиля `behavior` для предотвращения качания (flapping).
*   **Событийное масштабирование (KEDA):** Реакция на внешние очереди (Kafka Lag, RabbitMQ queue depth, Redis stream depth) до того, как перегрузка вызовет рост HTTP-задержек.
*   **Вертикальное масштабирование на лету (In-Place Pod Resize):** Включение изменения ресурсов CPU/RAM пода без его перезапуска (`resizePolicy`), что критично для stateful-нагрузок и тяжелых приложений с длительным прогревом (JVM).
*   **Управление емкостью физических узлов:** Использование Cluster API с провайдером Metal3/vSphere или статическое разделение узлов на пулы через `Taints / Tolerations` и `NodeAffinity`.

---

## Практические сценарии

### Сценарий 1: Тюнинг ядра и сетевого стека узлов (Node-level sysctl & ulimits)

Для подготовки физических серверов (Worker Nodes) к нагрузкам свыше 50 000 RPS необходимо сконфигурировать системные лимиты ядра.

1. Создайте конфигурационный файл тюнинга ядра `/etc/sysctl.d/99-kubernetes-high-load.conf` на каждом воркер-узле:

```ini
# Максимальный размер очереди входящих соединений ядра (backlog)
net.core.somaxconn = 65535

# Максимальное число пакетов в очереди сетевого интерфейса перед передачей стеку
net.core.netdev_max_backlog = 16384

# Защита от переполнения очереди полуоткрытых соединений (SYN Backlog)
net.ipv4.tcp_max_syn_backlog = 65535

# Повторное использование сокетов в состоянии TIME_WAIT для исходящих подключений
net.ipv4.tcp_tw_reuse = 1

# Расширение диапазона эфемерных портов для балансировщиков и прокси
net.ipv4.ip_local_port_range = 10240 65535

# Емкость таблицы трансляции адресов (conntrack) для исключения потерь пакетов
net.netfilter.nf_conntrack_max = 2097152
net.netfilter.nf_conntrack_tcp_timeout_established = 3600
net.netfilter.nf_conntrack_tcp_timeout_close_wait = 60

# Размеры буферов сокетов (максимальные значения: до 16MB на сокет)
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# Алгоритм контроля перегрузки сети BBR (требует ядра Linux 4.9+)
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# Лимиты открытых файлов и файловых дескрипторов
fs.file-max = 2097152
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 8192

# Увеличение лимита областей виртуальной памяти (для баз данных, JVM, Elasticsearch)
vm.max_map_count = 1048576

# Минимизация сброса страниц в swap при наличии RAM
vm.swappiness = 1
```

2. Примените параметры ядра без перезагрузки:

```bash
sudo sysctl --system
# → Applying /etc/sysctl.d/99-kubernetes-high-load.conf ...
# → net.core.somaxconn = 65535
# → net.netfilter.nf_conntrack_max = 2097152
# → net.ipv4.tcp_congestion_control = bbr
```

3. Сконфигурируйте системные лимиты дескрипторов для `containerd` и `kubelet` в файле `/etc/systemd/system.conf.d/high-load-limits.conf`:

```ini
[Manager]
DefaultLimitNOFILE=1048576
DefaultLimitNPROC=524288
DefaultLimitMEMLOCK=infinity
```

Перезагрузите демон systemd:

```bash
sudo systemctl daemon-reexec
# → (процесс завершается без вывода ошибок)
```

---

### Сценарий 2: Использование namespaced sysctl в подах и настройка Kubelet

Большинство сетевых параметров `net.*` по умолчанию считаются в Kubernetes «небезопасными» (unsafe sysctls), так как изоляция пространства имен сети (Network Namespace) может влиять на другие контейнеры или ядро хоста.

1. Разрешите необходимые параметры в конфигурации `kubelet` (`/var/lib/kubelet/config.yaml`):

```yaml
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
allowedUnsafeSysctls:
  - "net.core.somaxconn"
  - "net.ipv4.tcp_tw_reuse"
  - "net.ipv4.ip_local_port_range"
```

Перезапустите сервис kubelet:

```bash
sudo systemctl restart kubelet
sudo systemctl status kubelet --no-pager | grep "Active:"
# → Active: active (running) since Sun 2026-10-18 12:00:00 MSK; 10s ago
```

2. Пример манифеста пода с изолированным тюнингом сетевого пространства:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: high-load-ingress-gateway
  namespace: networking
spec:
  replicas: 5
  selector:
    matchLabels:
      app: ingress-gateway
  template:
    metadata:
      labels:
        app: ingress-gateway
    spec:
      securityContext:
        sysctls:
        - name: net.core.somaxconn
          value: "65535"
        - name: net.ipv4.tcp_tw_reuse
          value: "1"
        - name: net.ipv4.ip_local_port_range
          value: "10240 65535"
      containers:
      - name: gateway
        image: angie:1.8.2
        resources:
          requests:
            cpu: "4000m"
            memory: "8Gi"
          limits:
            cpu: "8000m"
            memory: "16Gi"
```

---

### Сценарий 3: Аппаратная изоляция и CPU/Memory Manager (Guaranteed QoS и NUMA)

Для сервисов, критичных к задержкам (Trading engines, L7 балансировщики, RTB-системы), переключение контекста между ядрами и доступ к чужому NUMA-узлу создают неприемлемый джиттер.

1. Настройте Kubelet для жесткого закрепления ядер CPU и памяти в файле `/var/lib/kubelet/config.yaml`:

```yaml
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
# Политика закрепления изолированных процессорных ядер
cpuManagerPolicy: static
cpuManagerPolicyOptions:
  full-pcpus-only: "true"

# Резервирование ресурсов под системные демоны и kubelet (ядра 0-1)
reservedSystemCPUs: "0-1"

# Координация топологии NUMA
topologyManagerPolicy: single-numa-node
topologyManagerScope: container

# Менеджер распределения памяти с учетом NUMA
memoryManagerPolicy: Static
reservedMemory:
  - numaNode: 0
    limits:
      memory: "2Gi"
```

2. Для активации политики `static` под **обязан** находиться в классе качества обслуживания **Guaranteed**:
   *   Значения `requests.cpu` и `limits.cpu` должны быть строго равны.
   *   Значение `cpu` должно быть целым числом (например, `4`, а не `4000m` или `3500m`).
   *   Значения `requests.memory` и `limits.memory` должны быть строго равны.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: ultra-low-latency-service
spec:
  containers:
  - name: processor
    image: custom-engine:v3.2
    resources:
      limits:
        cpu: "4"
        memory: 8Gi
      requests:
        cpu: "4"
        memory: 8Gi
```

После старта пода Kubelet выделит ему 4 физических ядра монопольно. Никакие другие поды или процессы не смогут исполняться на этих ядрах.

---

### Сценарий 4: Оптимизация Service Discovery (NodeLocal DNSCache)

При нагрузке свыше 10 000 RPS стандартная схема обращения подов к удаленным подам CoreDNS через Service IP (kube-proxy) приводит к деградации из-за UDP conntrack race conditions.

Решение — обязательное развертывание **NodeLocal DNSCache**. Демон работает как `DaemonSet` на каждом узле, перехватывает DNS-запросы на виртуальном адресе `169.254.20.10` и пересылает их в вышестоящий CoreDNS по постоянному TCP-соединению.

1. Конфигурация пода для устранения избыточных суффиксных поисков (`ndots`):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: high-qps-client
spec:
  replicas: 10
  template:
    spec:
      dnsPolicy: "ClusterFirst"
      dnsConfig:
        options:
        - name: ndots
          value: "2"  # Снижает число холостых запросов с 5 до 2
        - name: single-request-reopen  # Предотвращает гонку сокетов A и AAAA в glibc
        - name: timeout
          value: "1"
        - name: attempts
          value: "3"
      containers:
      - name: client
        image: backend-app:v1.12
```

---

### Сценарий 5: Оптимизация Ingress и пулинг соединений

Нехватка Keep-Alive соединений между балансировщиком и бэкендами — основная причина исчерпания сетевых портов и роста задержек за счет постоянного TLS/TCP handshaking.

1. Настройка пула постоянных соединений в Ingress Controller (пример для Ingress Nginx / Angie):

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ingress-nginx-controller
  namespace: ingress-nginx
data:
  # Максимальное число активных Keep-Alive соединений с апстримами
  upstream-keepalive-connections: "512"
  upstream-keepalive-requests: "100000"
  upstream-keepalive-timeout: "60"
  
  # Оптимизация очередей и буферизации
  max-worker-connections: "65535"
  worker-processes: "auto"
  worker-cpu-affinity: "auto"
  reuse-port: "true"
  
  # Буферизация для защиты бэкендов от медленных клиентов (Slowloris)
  proxy-buffering: "on"
  proxy-buffer-size: "8k"
  proxy-buffers-number: "8"
```

2. Пулинг соединений к базам данных (PostgreSQL / MySQL):
   *   Прямое подключение тысяч реплик подов к PostgreSQL приводит к краху СУБД из-за выделения отдельного процесса на соединение.
   *   Архитектурный стандарт: развертывание пулера соединений (**PgBouncer**) в виде `Deployment` с Service или в виде локального `Sidecar` контейнера.

---

### Сценарий 6: Конфигурация автомасштабирования (HPA v2 с Behavior и KEDA)

Под нагрузкой стандартный HPA может запаздывать со скейлингом вверх или начинать преждевременно сбрасывать поды при кратковременном спаде.

1. Настройка HPA v2 с агрессивным ростом и плавным снижением (Stabilization Window):

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: orders-api-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: orders-api
  minReplicas: 10
  maxReplicas: 120
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 65
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 75
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0  # Мгновенная реакция на всплеск
      policies:
      - type: Percent
        value: 100                   # Удвоение емкости за 15 секунд
        periodSeconds: 15
      - type: Pods
        value: 20                    # Либо добавление фиксированных 20 подов
        periodSeconds: 15
      selectPolicy: Max
    scaleDown:
      stabilizationWindowSeconds: 300 # 5 минут удержания подов после спада нагрузки
      policies:
      - type: Percent
        value: 10                    # Снижение не более 10% емкости в минуту
        periodSeconds: 60
      selectPolicy: Min
```

2. KEDA ScaledObject для масштабирования консьюмеров по лагу Apache Kafka в On-Premise:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: kafka-consumer-scaler
  namespace: production
spec:
  scaleTargetRef:
    name: payments-worker
  pollingInterval: 10
  cooldownPeriod: 180
  minReplicaCount: 4
  maxReplicaCount: 80
  triggers:
  - type: kafka
    metadata:
      bootstrapServers: kafka-cluster-kafka-bootstrap.kafka.svc:9092
      consumerGroup: payments-processors
      topic: high-volume-transactions
      lagThreshold: "250"
      activationLagThreshold: "20"
      offsetResetPolicy: latest
```

---

### Сценарий 7: Защита доступности, изоляция и Graceful Shutdown

При пиковых нагрузках плановое обслуживание нод или падение отдельных инстансов не должно приводить к отказу сервиса.

1. Манифест Pod Disruption Budget (PDB):

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: orders-api-pdb
  namespace: production
spec:
  minAvailable: "80%"
  selector:
    matchLabels:
      app: orders-api
  unhealthyPodEvictionPolicy: Always  # Не блокировать вытеснение упавших подов
```

2. Классы приоритета для изоляции критических компонентов:

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: high-load-critical
value: 1000000
globalDefault: false
preemptionPolicy: PreemptLowerPriority
description: "Критичные компоненты, вытесняющие фоновые задачи при дефиците ресурсов"
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: background-batch-workload
value: 1000
globalDefault: false
preemptionPolicy: Never
description: "Фоновые аналитические задачи без права вытеснения"
```

3. Конфигурация распределения подов и Graceful Shutdown:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders-api
  namespace: production
spec:
  replicas: 12
  template:
    metadata:
      labels:
        app: orders-api
    spec:
      priorityClassName: high-load-critical
      # Равномерное распределение по физическим серверам
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: "kubernetes.io/hostname"
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app: orders-api
      terminationGracePeriodSeconds: 45
      containers:
      - name: app
        image: orders-service:v2.4
        lifecycle:
          preStop:
            exec:
              # Задержка 15 секунд для синхронизации iptables/IPVS на всех узлах кластера
              command: ["/bin/sh", "-c", "sleep 15"]
        ports:
        - containerPort: 8080
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 2
          failureThreshold: 2
```

---

## Операции и команды

Сводная таблица ключевых операционных команд для SRE и системных администраторов:

| Задача | Команда | Ожидаемый результат / Интерпретация |
| :--- | :--- | :--- |
| Анализ потребления CPU и RAM подами | `kubectl top pods -n production --sort-by=cpu` | Вывод списка подов; поиск подов, приближающихся к 100% лимита |
| Поиск подов с падениями по памяти | `kubectl get pods -A -o jsonpath='{range .items[?(@.status.containerStatuses[*].lastState.terminated.reason=="OOMKilled")]}{.metadata.namespace}{"/"}{.metadata.name}{"\n"}{end}'` | Список подов, аварийно завершенных ядром по причине `OOMKilled` |
| Проверка троттлинга контейнера (cgroups v2) | `kubectl exec -it <pod> -- cat /sys/fs/cgroup/cpu.stat` | Значения `nr_throttled` и `throttled_usec`; их рост говорит о CFS throttling |
| Проверка насыщения Conntrack на узле | `sudo conntrack -S` | `entries`: текущее число; `drop`: количество отброшенных пакетов (должно быть 0) |
| Проверка состояния очередей сокетов хоста | `ss -lnt '( sport = :80 or sport = :443 )'` | Столбец `Send-Q` (лимит очереди) и `Recv-Q` (текущая очередь; если > 0, сокет забит) |
| Анализ задержек API-сервера | `kubectl get --raw /metrics \| grep apiserver_request_duration_seconds_bucket` | Оценка P99 времени обработки API-запросов |
| Проверка вытеснений планировщиком (Evictions) | `kubectl get events -A --field-selector reason=Evicted` | Список событий принудительного выселения подов из-за NodePressure |

---

## Диагностика и устранение неисправностей

### Диагностика 1: Детекция CFS Throttling через cgroups v2 и Prometheus

**Симптом:** Пользователи жалуются на спайки P99/P99.9 латентности сервиса. При этом средняя утилизация CPU пода не превышает 40–50%.

**Диагностика:**

1. Проверьте метрику троттлинга в Prometheus:

```promql
sum(rate(container_cpu_cfs_throttled_periods_total{container="orders-api"}[5m])) by (pod)
/
sum(rate(container_cpu_cfs_periods_total{container="orders-api"}[5m])) by (pod) > 0.20
```

2. Выполните прямую проверку счетчиков cgroups v2 внутри контейнера:

```bash
kubectl exec -n production deploy/orders-api -- cat /sys/fs/cgroup/cpu.stat
# → usage_usec 421098231
# → user_usec 312019238
# → system_usec 109078993
# → nr_periods 12450
# → nr_throttled 3820          # ← 30.6% всех периодов были подвергнуты троттлингу!
# → throttled_usec 98210340
```

**Решение:**
*   Переведите критичный под в класс `Guaranteed QoS` (целые ядра, `requests.cpu == limits.cpu`).
*   Если приложение многопоточное (Java, Go runtime с большим `GOMAXPROCS`), увеличьте `limits.cpu` кратно количеству активных потоков.
*   Установите `GOMAXPROCS` в Go-сервисах равным значению `requests.cpu` (используя библиотеку `uber-go/automaxprocs`).

---

### Диагностика 2: Исчерпание conntrack и отбрасывание сетевых пакетов

**Симптом:** Межсервисные запросы падают по тайм-ауту. В логах ядра узлов (`dmesg`) фиксируются сбросы трафика.

**Диагностика:**

1. Проверьте логи ядра на Worker-узле:

```bash
sudo dmesg -T | grep -i "conntrack" | tail -n 5
# → [Sun Oct 18 12:15:30 2026] nf_conntrack: table full, dropping packet
# → [Sun Oct 18 12:15:31 2026] nf_conntrack: table full, dropping packet
```

2. Проверьте отношение текущего количества соединений к максимальному:

```bash
cat /proc/sys/net/netfilter/nf_conntrack_count
# → 1048560
cat /proc/sys/net/netfilter/nf_conntrack_max
# → 1048576
```

Таблица заполнена на 99.9%.

**Решение:**
1. Немедленно увеличьте лимит на узле:

```bash
sudo sysctl -w net.netfilter.nf_conntrack_max=2097152
# → net.netfilter.nf_conntrack_max = 2097152
```

2. Увеличьте размер хеш-таблицы (`hashsize`) для предотвращения деградации поиска по коллизиям:

```bash
echo 524288 | sudo tee /sys/module/nf_conntrack/parameters/hashsize
# → 524288
```

3. Сократите время хранения закрытых сессий:

```bash
sudo sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=3600
# → net.netfilter.nf_conntrack_tcp_timeout_established = 3600
```

---

### Диагностика 3: Случайные 5-секундные задержки в DNS (conntrack UDP race)

**Симптом:** При обращении к базам данных или внутренним сервисам периодически возникают задержки строго около 5000 мс.

**Диагностика:**

1. Запустите трассировку разрешения имени внутри проблемного пода:

```bash
kubectl exec -it <pod-name> -- time nslookup postgres.production.svc.cluster.local
# → Server:    10.96.0.10
# → Address:   10.96.0.10#53
# → Name:      postgres.production.svc.cluster.local
# → Address:   10.244.3.45
# → real       0m 5.008s
```

2. Проверьте метрику ошибок CoreDNS:

```promql
histogram_quantile(0.99, sum(rate(coredns_dns_request_duration_seconds_bucket[5m])) by (le)) > 2
```

**Причина:** glibc выполняет параллельные запросы A и AAAA через один UDP-порт. Ядро Linux в этот момент производит трансляцию NAT через conntrack; один из пакетов отбрасывается из-за гонки, и резолвер ждет стандартный тайм-аут 5 секунд перед повтором.

**Решение:**
*   Разверните **NodeLocal DNSCache** в кластере.
*   Добавьте в спецификацию пода опцию `single-request-reopen`:
    ```yaml
    dnsConfig:
      options:
      - name: single-request-reopen
    ```

---

### Диагностика 4: Ошибки 502 Bad Gateway / Connection Reset при автомасштабировании

**Симптом:** В моменты добавления или удаления подов балансировщик (Ingress) фиксирует всплески кодов 502/503.

**Причина:** Асинхронность Control Plane Kubernetes:
1. При удалении пода API Server одновременно отправляет команду Kubelet на остановку контейнера (SIGTERM) и обновляет ресурс `EndpointSlice`.
2. Балансировщик и узловые правила IPVS/iptables обновляются с задержкой в 2–5 секунд.
3. Контейнер, получив SIGTERM, сразу завершает процесс приложения, в то время как Ingress продолжает направлять в него активный входящий трафик.

**Решение:**
Добавьте хук `preStop` со сном в спецификацию контейнера и увеличьте время изящного завершения:

```yaml
lifecycle:
  preStop:
    exec:
      command: ["/bin/sh", "-c", "sleep 15"]
terminationGracePeriodSeconds: 60
```

---

### Сводная матрица типовых неисправностей

| Симптом | Вероятная причина | Диагностическая команда | Решение |
| :--- | :--- | :--- | :--- |
| **Высокий P99 Latency при низком среднем CPU** | CFS Quota Throttling в ядре Linux | `cat /sys/fs/cgroup/cpu.stat` | Перевести в Guaranteed QoS; убрать limits или включить CPU Bursting |
| **Поды падают со статусом OOMKilled** | Превышение лимита памяти под пиком соединений | `kubectl describe pod <name> \| grep -A 3 "Last State"` | Увеличить memory limit; настроить пулинг соединений; профилировать heap |
| **Поды зависают в состоянии Pending** | Исчерпание ресурсов на Worker-узлах | `kubectl describe pod <name> \| grep -A 5 "Events:"` | Настроить PriorityClass; добавить физические ноды; оптимизировать requests |
| **DNS-запросы зависают на 5 секунд** | Гонка UDP Conntrack при резолвинге A/AAAA | `time nslookup <service>` | Развернуть NodeLocal DNSCache; выставить `single-request-reopen` |
| **HPA не масштабирует поды** | Отсутствие метрик в Metrics Server / Prometheus | `kubectl get hpa <name>` (колонка TARGETS `<unknown>`) | Проверить доступность metrics-server; проверить scrape-конфигурацию адаптера |
| **Ошибки 502/Connection Refused при скейле** | Преждевременное завершение процесса до вывода из Endpoints | Логи Ingress Controller (`grep "502"`) | Добавить `preStop: sleep 15` и `terminationGracePeriodSeconds: 60` |
| **Узел переходит в статус NotReady** | Kubelet PLEG завис из-за перегрузки диска/CRI | `journalctl -u kubelet -e \| grep "PLEG"` | Разнести `/var/lib/containerd` на быстрый NVMe; ограничить число подов на ноду |

---

## Лучшие практики

1.  **Откажитесь от заниженных CPU Limits:** Для чувствительных к задержкам сервисов не устанавливайте `limits.cpu` произвольно. Используйте `requests == limits` (Guaranteed QoS) либо задавайте только `requests.cpu`, защищая ноды от перегрузки на уровне пространства имен через `ResourceQuota`.
2.  **Всегда настраивайте Node Allocatable:** Гарантируйте системным процессам ресурсы через `--system-reserved` и `--kube-reserved` в Kubelet, чтобы шторм пользовательской нагрузки не убивал Kubelet, containerd и sshd.
3.  **Используйте NodeLocal DNSCache:** В любых кластерах с суммарным трафиком выше 5000 QPS развертывание кэширующего DNS-агента на петлевом адресе узла обязательно.
4.  **Калибруйте HPA Behavior:** Избегайте мгновенного свертывания подов. Окно стабилизации `scaleDown` должно составлять не менее 300 секунд (5 минут), чтобы предотвратить циклический каскадный перегруз оставшихся реплик.
5.  **Внедряйте Circuit Breakers и Rate Limiting:** Защищайте внутренние сервисы от лавинообразных очередей на уровне Service Mesh (Envoy/Istio) или API Gateway.
6.  **Изолируйте критические сервисы:** Применяйте `PriorityClass` с правом вытеснения (`PreemptLowerPriority`) для критичных компонентов ядра и `topologySpreadConstraints` для исключения концентрации всех реплик на одном физическом сервере.
7.  **Контролируйте размер пулов соединений:** Клиентские пулы (Keep-Alive, HTTP/2 multiplexing, DB pools) должны быть строго ограничены, чтобы не переполнять очереди сокетов `somaxconn` целевых серверов.

---

## Дополнительная информация

*   **[QoS, Requests и Limits в Kubernetes](../Scheduling/qos_limit_and_requests.md)** — глубокий разбор классов качества обслуживания, расчета Node Allocatable и In-Place Pod Resize.
*   **[API Priority and Fairness (APF)](api_priority_and_fairness.md)** — защита API-сервера Kubernetes от перегрузки со стороны контроллеров и операторов.
*   **[Автомасштабирование в Kubernetes: Концепции и обзор](../Autoscaling/overview_concepts.md)** — архитектура HPA v2, VPA и Cluster Autoscaler.
*   **[Автомасштабирование на On-Premise инфраструктуре](../Autoscaling/on_premise_autoscaling.md)** — стратегии масштабирования в изолированных Bare-Metal кластерах (Cluster API, Metal3).
*   **[KEDA: Архитектура и концепции](../Autoscaling/keda/keda_concepts.md)** — событийное автомасштабирование по очередям и внешним источникам.
*   **[Высокая доступность в Kubernetes](../Base/high_availability.md)** — построение отказоустойчивых кластеров, кворум etcd и L4-балансировка.
*   **[Graceful Shutdown: Глубокое погружение](../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md)** — порядок остановки контейнеров, хуки `preStop` и жизненный цикл завершения подов.
*   **[DNS в Kubernetes: Глубокое погружение](../Networking/dns_deep_dive.md)** — устройство CoreDNS, EndpointSlice, NodeLocal DNSCache и оптимизация резолвинга.
*   **[Диагностика и устранение CPU Throttling](../Troubleshooting/Common_Errors/cpu_throttling.md)** — практическое руководство по профилированию планировщика ядра CFS и cgroups v2.
*   **[Тюнинг ядра Linux для узлов Kubernetes](../Troubleshooting/Common_Errors/NodeUnavailability/kernel_tuning.md)** — системные параметры `sysctl`, настройка conntrack и сокетов на уровне ОС хоста.
