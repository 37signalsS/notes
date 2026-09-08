# Topology Manager — NUMA-осознанное планирование ресурсов

## Определения

**Topology Manager** — компонент Kubelet, который координирует работу CPU Manager, Memory Manager и Device Manager для выдачи ресурсов с учётом физической топологии материнской платы (NUMA-архитектура). Его задача — гарантировать, что CPU, память и устройства (GPU, SR-IOV NIC) выделяются из одного NUMA-узла, минимизируя задержки межsocket-пересылки данных.

**NUMA (Non-Uniform Memory Access)** — архитектура многопроцессорных систем, где каждый CPU-сокет имеет собственную локальную память. Доступ к «чужой» памяти другого сокета происходит через интерконект (QPI/UPI/CXL), что увеличивает задержку в 1.5-3 раза. В современных серверах 2-4 NUMA-узла, в высокопроизводительных системах — до 8.

**NUMA Node (NUMA-узел)** — логическая группа ресурсов: CPU-ядра + локальная память + PCI-устройства (GPU, NIC, NVMe), привязанные к одному физическому сокету.

**Предикат 적ывания (Admission Predicate)** — механизм Topology Manager, который проверяет, может ли kubelet выделить все запрошенные подом ресурсы (CPU, память, устройства) из одного NUMA-узла до разрешения запуска контейнера.

**Topology Affinity Error** — ошибка, возникающая при политике `restricted` или `single-numa-node`, если невозможно обеспечить все ресурсы из одного NUMA-узла. Под не запускается и получает статус `Terminated` с кодом ошибки.

---

## Предварительные требования

### Требования к кластеру

* **Kubernetes:** 1.18+ (Topology Manager GA), 1.22+ (поддержка Policy Replica), 1.28+ (расширенные политики)
* **Kubelet:** сконфигурирован с `topologyManagerPolicy` и `topologyManagerScope`
* **Container Runtime:** containerd 1.6+ или CRI-O 1.20+
* **Ядро ОС:** 5.4+ (для корректной работы NUMA-информации через sysfs)

### Требования к узлам

* **NUMA-архитектура:** узел должен иметь 2+ NUMA-узла (проверка: `lscpu | grep NUMA`)
* **CPU Manager:** политика `static` (для целочисленных CPU)
* **Device Manager:** установленные device plugins (NVIDIA, SR-IOV)
* **Memory Manager:** опционально, но рекомендуется для полной NUMA-изоляции

### Проверка NUMA-топологии узла

```bash
# Количество NUMA-узлов
lscpu | grep "NUMA node(s)"
# → NUMA node(s):        2

# Какие ядра к какому NUMA-узлу
lscpu | grep -A 10 "NUMA"
# NUMA node0 CPU(s):     0-15
# NUMA node1 CPU(s):     16-31

# Список NUMA-узлов с их памятью
numactl --hardware
# available: 2 nodes (0-1)
# node 0 cpus: 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15
# node 0 size: 65536 MB
# node 1 cpus: 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31
# node 1 size: 65536 MB

# Дистанция между NUMA-узлами (1 = локально, 2 = через интерконект)
numactl --hardware
# node distances:
# node   0   1
#   0:  10  21
#   1:  21  10

# Какие устройства привязаны к какому NUMA-узлу
cat /sys/bus/pci/devices/0000:3b:00.0/numa_node
# → 1 (устройство привязано к NUMA node 1)
```

### Начальное состояние

* Кластер запущен и доступен через `kubectl`
* На целевом узле включён CPU Manager с политикой `static`
* На узле установлены device plugins (если требуются устройства)

---

## Основные концепции

### Зачем нужен Topology Manager?

Без Topology Manager kubelet распределяет ресурсы **независимо** между менеджерами:
1. CPU Manager выделяет ядра из NUMA Node 0
2. Memory Manager выделяет память из NUMA Node 1
3. Device Manager выделяет GPU из NUMA Node 1

Результат: под работает с CPU из одного сокета, а память и GPU — из другого. Пересылка данных через QPI/UPI шину вызывает **серьёзную деградацию производительности**:
* Задержка доступа к памяти увеличивается в 1.5-3 раза
* Пропускная способность падает на 30-50%
* Для HPC/ML/real-time нагрузок это критично

Topology Manager решает эту проблему, координируя все менеджеры и выдавая ресурсы **только из одного NUMA-узла**.

### Политики Topology Manager

| Политика | Поведение | Когда под запускается | Типичное применение |
|:---|:---|:---|:---|
| `none` (по умолчанию) | Kubelet не проверяет NUMA-совместимость | Всегда | Обычные рабочие нагрузки без требований к производительности |
| `best-effort` | Kubelet пытается выровнять ресурсы по NUMA | Всегда (даже при невозможности выравнивания) | Приложения, которым желательна, но не критична NUMA-локальность |
| `restricted` | Kubelet требует выравнивания, допуская частичное совпадение | Только если выравнивание возможно | Требовательные к производительности приложения (БД, очереди сообщений) |
| `single-numa-node` | Все ресурсы строго из одного NUMA-узла | Только при полном выравнивании | HPC, real-time, latency-critical приложения |

### Как работает Topology Manager

Процесс координации:

1. **Admission Phase (Prefilter):** При создании пода Topology Manager запрашивает у каждого менеджера (CPU, Memory, Device) список доступных ресурсов по NUMA-узлам.
2. **Calculation:** На основе политики Topology Manager определяет, можно ли удовлетворить все запросы пода из одного NUMA-узла.
3. **Admission Decision:**
   * `none`: под допускается без проверок
   * `best-effort`: под допускается всегда, NUMA-выравнивание — лучшая попытка
   * `restricted`/`single-numa-node`: под допускается только при成功的NUMA-выравнивании, иначе — `TopologyAffinityError`
4. **Allocation:** После допуска каждый менеджер выделяет ресурсы из выбранного NUMA-узла.

### Взаимодействие с другими менеджерами

* **CPU Manager** (`cpuManagerPolicy: static`): Выделяет целые ядра CPU из конкретного NUMA-узла. Требуется для Topology Manager.
* **Memory Manager** (`memoryManagerPolicy: Static`): Выделяет память из конкретного NUMA-узла. Устанавливает `memory.min` в cgroups v2 для гарантированного выделения.
* **Device Manager**: Управляет device plugins (NVIDIA GPU, SR-IOV, RDMA). Каждый device plugin сообщает NUMA-привязку устройства.

### Требования к подам

Для корректной работы Topology Manager под должен:

1. **Принадлежать к классу `Guaranteed`:** `requests` == `limits` для CPU и памяти
2. **Запрашивать ресурсы целыми числами:** CPU — целое количество ядер (не `500m`), устройства — целое количество
3. **Иметь device requests** (опционально): `nvidia.com/gpu: 1`, `intel.com/sriov_net`

### Topology Manager Scope

Два режима видимости (scope):

* **`container`** (по умолчанию): NUMA-выравнивание проверяется для каждого контейнера отдельно. Контейнеры в одном поде могут быть на разных NUMA-узлах.
* **`pod`**: NUMA-выравнивание проверяется для всего пода целиком. Все контейнеры пода гарантированно попадают на один NUMA-узел.

```bash
# Проверка текущего scope
cat /var/lib/kubelet/config.yaml | grep topologyManagerScope
# → topologyManagerScope: pod
```

---

## Практические сценарии

### Сценарий 1: Настройка Topology Manager для production-сервера

**Задача:** Включить NUMA-осознанное планирование на сервере с 2 NUMA-узлами для БД PostgreSQL и очереди Kafka.

**Конфигурация Kubelet:**
```yaml
# /var/lib/kubelet/config.yaml
apiVersion: kubelet.config.k8s.io/v1
kind: KubeletConfiguration
topologyManagerPolicy: restricted
topologyManagerScope: pod
cpuManagerPolicy: static
cpuManagerReconcilePeriod: 10s
memoryManagerPolicy: Static
reservedSystemCPUs: "0-1"  # Резерв для системных процессов
kubeReserved:
  cpu: "500m"
  memory: "1Gi"
systemReserved:
  cpu: "500m"
  memory: "1Gi"
```

**Применение:**
```bash
# Перезапуск kubelet для применения конфигурации
sudo systemctl daemon-reload
sudo systemctl restart kubelet

# Проверка, что политика применена
cat /var/lib/kubelet/config.yaml | grep -E "topologyManager|cpuManager|memoryManager"
# → topologyManagerPolicy: restricted
# → topologyManagerScope: pod
# → cpuManagerPolicy: static
# → memoryManagerPolicy: Static

# Проверка состояния Topology Manager (через метрики)
curl -sk https://localhost:10250/metrics | grep topology_manager
```

### Сценарий 2: Развертывание NUMA-изолированной БД PostgreSQL

**Манифест Deployment:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
  namespace: database
spec:
  replicas: 2
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      # Требования к Guaranteed QoS
      containers:
      - name: postgres
        image: postgres:16
        resources:
          requests:
            cpu: "4"           # Целое число ядер
            memory: "8Gi"      # requests == limits → Guaranteed
          limits:
            cpu: "4"
            memory: "8Gi"
        env:
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-secret
              key: password
        volumeMounts:
        - name: postgres-data
          mountPath: /var/lib/postgresql/data
      volumes:
      - name: postgres-data
        persistentVolumeClaim:
          claimName: postgres-data-pvc
```

**Валидация:**
```bash
# Применение манифеста
kubectl apply -f postgres-deployment.yaml

# Проверка, что под запущен и имеет Guaranteed QoS
kubectl get pod -l app=postgres -n database -o jsonpath='{.items[0].status.qosClass}'
# → Guaranteed

# Проверка NUMA-распределения ресурсов (на узле)
# Подключиться к узлу и выполнить:
cat /var/lib/kubelet/cpu_manager_state | python3 -c "
import json, sys
data = json.load(sys.stdin)
for pod in data.get('pods', []):
    if 'postgres' in pod.get('podUID', ''):
        print(f'Pod: {pod[\"podUID\"]}')
        for cpu in pod.get('cpus', []):
            print(f'  CPU {cpu} → NUMA node {data[\"clockTickMapping\"].get(cpu, \"?\")}')
"
# → Все ядра пода назначены из одного NUMA-узла

# Проверка распределения памяти по NUMA (на узле)
numastat -p $(pgrep -f postgres)
# → Процесс PostgreSQL использует память только из одного NUMA-узла
```

**Cleanup:**
```bash
kubectl delete deployment postgres -n database
```

**Граничные случаи:**
* Если NUMA-узел не может выделить все 4 ядра и 8Gi памяти — под получит `TopologyAffinityError` и будет перезапущен.
* При `topologyManagerScope: container` каждый контейнер выравнивается отдельно — для multi-container подов используйте `pod`.
* Для StatefulSet убедитесь, что все поды получают одинаковые ресурсы (requests == limits).

### Сценарий 3: NUMA-изолированный ML-инференс с GPU

**Манифест Pod:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: ml-inference
  namespace: ml
spec:
  containers:
  - name: inference-server
    image: nvcr.io/nvidia/tritonserver:24.01-py3
    resources:
      requests:
        cpu: "4"
        memory: "16Gi"
        nvidia.com/gpu: 1
      limits:
        cpu: "4"
        memory: "16Gi"
        nvidia.com/gpu: 1
    env:
    - name: CUDA_VISIBLE_DEVICES
      value: "0"
```

**Валидация:**
```bash
# Применение
kubectl apply -f ml-inference.yaml

# Проверка, что под запущен
kubectl get pod ml-inference -n ml
# NAME            READY   STATUS    RESTARTS   AGE
# ml-inference    1/1     Running   0          30s

# Проверка, что GPU и CPU из одного NUMA (на узле)
nvidia-smi topo -m
#        GPU0  CPU Affinity
# GPU0     X   16-31       ← GPU привязан к NUMA 1
# CPU: 16-31 — все из NUMA 1

# Проверка памяти
numastat -p $(pgrep -f tritonserver)
# → Вся память из NUMA node 1
```

**Граничные случаи:**
* Если GPU привязан к NUMA 0, а CPU выделены из NUMA 1 — `single-numa-node` политика отклонит под.
* Используйте `nvidia-smi topo -m` для определения NUMA-привязки GPU перед созданием пода.
* Для MIG (Multi-Instance GPU) каждая MIG-инстанса может иметь свою NUMA-привязку.

### Сценарий 4: Диагностика TopologyAffinityError

**Симптом:**
```
kubectl get pod my-pod
# NAME      READY   STATUS                 RESTARTS   AGE
# my-pod    0/1     TopologyAffinityError  0          10s
```

**Диагностика:**
```bash
# Шаг 1: Проверка событий пода
kubectl describe pod my-pod | grep -A 10 "Events:"
# Warning  TopologyAffinityError  0/2 nodes are available:
# 2 pod's requested cpu/gpu resources are not available in any single NUMA node

# Шаг 2: Проверка NUMA-топологии узла
lscpu | grep "NUMA node(s)"
# → NUMA node(s):        2

# Шаг 3: Проверка распределения CPU по NUMA
numactl --hardware | grep "node 0 cpus\|node 1 cpus"
# node 0 cpus: 0 1 2 3 4 5 6 7
# node 1 cpus: 8 9 10 11 12 13 14 15

# Шаг 4: Проверка распределения GPU по NUMA (на узле)
nvidia-smi topo -m
# GPU0    CPU Affinity: 8-15  → NUMA 1
# GPU1    CPU Affinity: 0-7   → NUMA 0

# Шаг 5: Проверка текущего потребления NUMA-ресурсов
cat /var/lib/kubelet/cpu_manager_state | python3 -c "
import json, sys
data = json.load(sys.stdin)
print('NUMA 0 CPUs:', [e for e in data.get('entries', {}) if e.get('NUMANode', 0) == 0])
print('NUMA 1 CPUs:', [e for e in data.get('entries', {}) if e.get('NUMANode', 0) == 1])
"
```

**Решения:**
1. **Уменьшите запросы:** Если под запрашивает 8 CPU + 2 GPU, а на каждом NUMA-узле только 8 CPU и 1 GPU — уменьшите количество GPU до 1.
2. **Используйте `best-effort`:** Если NUMA-локальность желательна, но не обязательна.
3. **Проверьте `reservedSystemCPUs`:** Если системные процессы заняли ядра на нужном NUMA-узле.
4. **Используйте `topologyManagerScope: container`:** Если multi-container под не может получить все ресурсы из одного NUMA.

### Сценарий 5: Переключение политики Topology Manager

**Задача:** Переключить Topology Manager с `none` на `restricted` без простоя кластера.

```bash
# 1. Проверка текущей политики
cat /var/lib/kubelet/config.yaml | grep topologyManagerPolicy
# → topologyManagerPolicy: none

# 2. Редактирование конфигурации
sudo sed -i 's/topologyManagerPolicy: none/topologyManagerPolicy: restricted/' /var/lib/kubelet/config.yaml

# 3. Перезапуск kubelet (на одном узле за раз для minimization impact)
sudo systemctl daemon-reload
sudo systemctl restart kubelet

# 4. Проверка, что kubelet запустился
sudo systemctl status kubelet
# → Active: active (running)

# 5. Проверка новой политики
cat /var/lib/kubelet/config.yaml | grep topologyManagerPolicy
# → topologyManagerPolicy: restricted

# 6. Проверка, что существующие поды не пострадали
kubectl get pods -A --field-selector spec.nodeName=<node-name> | grep -v Running
# → Не должно быть подов в ошибке
```

**Важно:** При переключении с `restricted`/`single-numa-node` на `none` существующие поды не пересоздаются — NUMA-привязка сохраняется до следующего перезапуска пода.

---

## Дополнительная информация

### Диагностика и мониторинг

```bash
# Проверка политики Topology Manager
cat /var/lib/kubelet/config.yaml | grep topologyManagerPolicy
# → topologyManagerPolicy: restricted

# Проверка scope
cat /var/lib/kubelet/config.yaml | grep topologyManagerScope
# → topologyManagerScope: pod

# Проверка состояния CPU Manager (файл состояния)
cat /var/lib/kubelet/cpu_manager_state | python3 -m json.tool

# Проверка состояния Memory Manager (файл состояния)
cat /var/lib/kubelet/memory_manager_state | python3 -m json.tool

# Проверка NUMA-топологии узла
lscpu | grep "NUMA"
numactl --hardware

# Проверка NUMA-привязки устройств
cat /sys/bus/pci/devices/0000:3b:00.0/numa_node

# Метрики Topology Manager (через Prometheus)
# topology_manager_admission_requests_total{result="admitted|rejected"}
# topology_manager_admission_duration_seconds{policy="restricted|single-numa-node"}
```

### Troubleshooting

#### Проблема: Под в состоянии TopologyAffinityError

**Симптом:** Под перезапускается с ошибкой `TopologyAffinityError`.

**Диагностика:**
```bash
# Проверка событий пода
kubectl describe pod <pod-name> | grep -A 5 "Events"

# Проверка, что под имеет Guaranteed QoS
kubectl get pod <pod-name> -o jsonpath='{.status.qosClass}'
# → Должно быть: Guaranteed

# Проверка requests == limits
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[].resources}'
# → requests и limits должны совпадать

# Проверка NUMA-ресурсов на узле
numactl --hardware | grep "node.*cpus"
```

**Решения:**
1. Убедитесь, что requests == limits (Guaranteed QoS).
2. Уменьшите количество запрашиваемых ресурсов (CPU, GPU).
3. Используйте `best-effort` вместо `restricted` или `single-numa-node`.
4. Проверьте `reservedSystemCPUs` — возможно, системные процессы заняли слишком много ядер.

#### Проблема: Topology Manager не активен

**Симптом:** Поды запускаются без NUMA-выравнивания, хотя политика установлена.

**Диагностика:**
```bash
# Проверка, что CPU Manager работает в режиме static
cat /var/lib/kubelet/config.yaml | grep cpuManagerPolicy
# → cpuManagerPolicy: static

# Проверка логов kubelet
journalctl -u kubelet | grep -i "topology"
# → Ищите сообщения о загрузке Topology Manager

# Проверка, что узел имеет NUMA-топологию
lscpu | grep "NUMA node(s)"
# → NUMA node(s):        1
# Если NUMA node(s): 1 — Topology Manager бесполезен
```

**Решения:**
1. Убедитесь, что `cpuManagerPolicy: static` и `topologyManagerPolicy` установлены.
2. Убедитесь, что узел имеет 2+ NUMA-узла.
3. Перезапустите kubelet: `sudo systemctl restart kubelet`.

#### Проблема: Деградация производительности после включения Topology Manager

**Симптом:** Приложение работает медленнее после включения NUMA-выравнивания.

**Диагностика:**
```bash
# Проверка, что все ресурсы из одного NUMA (на узле)
numastat -p $(pgrep -f <process-name>)

# Проверка переполнения NUMA-узла
numastat -m | grep -A 5 "node 0\|node 1"

# Проверка, не заблокированы ли ядра из-за reservedSystemCPUs
cat /var/lib/kubelet/config.yaml | grep reservedSystemCPUs
```

**Решения:**
1. Если NUMA-узел переполнен — распределите поды по разным NUMA-узлам через `nodeSelector` с метками `topology.kubernetes.io/numa-node`.
2. Увеличьте `reservedSystemCPUs` для освобождения ядер.
3. Используйте `topologyManagerScope: container` вместо `pod`.

### Рекомендации (Best Practices)

* **Начните с `best-effort`:** Перед включением `restricted` или `single-numa-node` протестируйте на staging-кластере.
* **Всегда используйте `topologyManagerScope: pod`:** Для multi-container подов это гарантирует NUMA-изоляцию всего пода.
* **Убедитесь в наличии 2+ NUMA-узлов:** На одноsocket серверах Topology Manager бесполезен.
* **Резервируйте ядра:** Используйте `reservedSystemCPUs` для системных процессов, чтобы они не конкурировали с пользовательскими подами за NUMA-ресурсы.
* **Мониторьте NUMA-использование:** Настройте алерты на переполнение NUMA-узлов через Prometheus.
* **Документируйте NUMA-топологию:** Ведите реестр NUMA-привязки GPU и NIC для упрощения планирования.

### Вопросы на собеседовании

#### Что такое NUMA и почему это важно для Kubernetes?
NUMA (Non-Uniform Memory Access) — архитектура, где каждый CPU-сокет имеет локальную память. Доступ к памяти другого сокета медленнее в 1.5-3 раза. В Kubernetes Topology Manager гарантирует, что CPU, память и GPU выделяются из одного NUMA-узла, минимизируя задержки.

#### Какие политики Topology Manager существуют и чем отличаются?
Четыре политики: `none` (нет проверок), `best-effort` (пытается выровнять, но допускает), `restricted` (требует выравнивания, допускает частичное), `single-numa-node` (все ресурсы строго из одного NUMA). Чем строже политика, тем выше производительность, но выше риск ошибок.

#### Какие требования к подам для работы Topology Manager?
Под должен быть `Guaranteed` QoS (requests == limits), CPU запрашиваться целыми числами, device requests — целыми количествами. Для `single-numa-node` все ресурсы должны быть доступны из одного NUMA-узла.

#### Чем Topology Manager отличается от CPU Manager?
CPU Manager выделяет целые ядра CPU из конкретного NUMA-узла. Topology Manager координирует CPU Manager, Memory Manager и Device Manager, гарантируя, что все ресурсы (CPU + память + GPU) выделяются из одного NUMA-узла.

### См. также

* [QoS, Requests и Limits](./qos_limit_and_requests.md) — классы QoS и управление ресурсами
* [Affinity и Anti-Affinity](./affinity.md) — управление размещением подов
* [Taints и Tolerations](./taints_and_tolerations.md) — изоляция узлов
* [Memory Manager](./memory_manager.md) — NUMA-осознанное выделение памяти
* [Device Manager](./device_manager.md) — управление GPU и специализированным оборудованием
