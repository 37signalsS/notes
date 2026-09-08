# Memory Manager — NUMA-осознанное управление памятью

## Определения

**Memory Manager** — компонент Kubelet, который обеспечивает NUMA-осознанное выделение памяти подам. Он координирует работу с Topology Manager и CPU Manager для гарантии, что память пода выделяется из того же NUMA-узла, что и CPU и устройства.

**NUMA-осознанное выделение памяти (NUMA-aware allocation)** — механизм, при котором память пода выделяется физически из локальной памяти того NUMA-узла, на котором размещены ядра CPU пода. Это исключает межsocket-пересылку данных и минимизирует задержку доступа к памяти.

**Guaranteed Memory Reservation** — гарантия Kubelet, что определённый объём памяти на конкретном NUMA-узле будет зарезервирован для пода и не будет доступен другим подам. Реализуется через `memory.min` в cgroups v2.

**Memory Manager State File** (`/var/lib/kubelet/memory_manager_state`) — JSON-файл, в котором Kubelet хранит текущее состояние выделения памяти по NUMA-узлам. Используется для согласования состояний между перезапусками kubelet.

---

## Предварительные требования

### Требования к кластеру

* **Kubernetes:** 1.22+ (Memory Manager Beta), 1.28+ (GA для Static политики)
* **Kubelet:** `memoryManagerPolicy: Static` в `KubeletConfiguration`
* **Container Runtime:** containerd 1.7+ или CRI-O 1.26+ (для поддержки cgroups v2)
* **Ядро ОС:** 5.4+ (для корректной работы NUMA-информации)

### Требования к узлам

* **NUMA-архитектура:** 2+ NUMA-узла (проверка: `lscpu | grep NUMA`)
* **CPU Manager:** политика `static` (обязательна для работы Memory Manager)
* **Topology Manager:** политика `restricted` или `single-numa-node` (рекомендуется)

### Проверка NUMA-памяти

```bash
# Общий объём памяти по NUMA-узлам
numactl --hardware
# available: 2 nodes (0-1)
# node 0 cpus: 0 1 2 3 4 5 6 7
# node 0 size: 65536 MB
# node 0 free: 50000 MB
# node 1 cpus: 8 9 10 11 12 13 14 15
# node 1 size: 65536 MB
# node 1 free: 48000 MB

# Текущее использование памяти по NUMA-узлам
numastat -m
# node 0
# ​​​​​anonymous                     12345678
# file                            23456789
# ...
# node 1
# anonymous                       11234567
# file                            22345678

# Проверка, что Kubelet видит NUMA-топологию
cat /sys/devices/system/node/node0/meminfo | head -5
# Node 0 MemTotal:       67108864 kB
```

---

## Основные концепции

### Зачем нужен Memory Manager?

Без Memory Manager Kubelet выделяет память подам из «общего пула» без учёта NUMA-топологии. Результат:
* CPU пода на NUMA Node 0, память — на NUMA Node 1
* Задержка доступа к памяти увеличивается в 1.5-3 раза
* Для latency-critical приложений (БД, real-time) это критично

Memory Manager решает эту проблему:
* При старте kubelet сканирует NUMA-топологию и распределяет память по NUMA-узлам
* При создании Guaranteed-пода Memory Manager выделяет память из выбранного NUMA-узла
* Каждому поду гарантируется `memory.min` — минимальный объём памяти, который ОС никогда не заберёт

### Политики Memory Manager

| Политика | Поведение | Требования |
|:---|:---|:---|
| `None` (по умолчанию) | Memory Manager не активен, память выделяется без NUMA-учёта | Нет специальных требований |
| `Static` | NUMA-осознанное выделение памяти для Guaranteed-подов | Требуется `cpuManagerPolicy: static` и NUMA-топология |

### Как работает Memory Manager

1. **Инициализация:** При старте kubelet Memory Manager сканирует NUMA-топологию и создаёт файл состояния (`memory_manager_state`).
2. **Admission:** При создании Guaranteed-пода Memory Manager проверяет, может ли выделить запрошенный объём памяти из одного NUMA-узла (в координации с Topology Manager).
3. **Allocation:** После допуска Memory Manager выделяет память из выбранного NUMA-узла и устанавливает `memory.min` в cgroups v2 для гарантированного выделения.
4. **Сохранение состояния:** Memory Manager периодически записывает состояние в файл `memory_manager_state` для согласования между перезапусками kubelet.

### Взаимодействие с cgroups v2

Memory Manager использует возможности cgroups v2 для гарантии выделения памяти:

* **`memory.min`:** Минимальный объём памяти, который ОС никогда не заберёт у контейнера. Соответствует `requests.memory` в Kubernetes.
* **`memory.high`:** Мягкий лимит. При достижении ядро начинает throttle процесс, давая шанс освободить память.

```bash
# Проверка cgroup v2 для контейнера (на узле)
# Найти cgroup пода
cat /sys/fs/cgroup/kubepods/pod<pod-id>/memory.min
# → 8589934592 (8Gi в байтах)

cat /sys/fs/cgroup/kubepods/pod<pod-id>/memory.high
# → 9663676416 (9Gi в байтах, ~110% от requests)
```

### Memory Manager State File

Файл `/var/lib/kubelet/memory_manager_state` хранит информацию о выделении памяти:

```json
{
  "policy": "Static",
  "memoryCalculations": {
    "numaFree": [50000000000, 48000000000],
    "numaCapacity": [67108864000, 67108864000]
  },
  "entries": {
    "pod-uid-1": {
      "containerName": "app",
      "numaNode": 0,
      "memoryType": "guaranteed",
      "allocation": 8589934592
    }
  },
  "timestamp": "2024-08-30T12:00:00Z"
}
```

**Важно:** При повреждении этого файла Kubelet пересоздаёт его при следующем запуске. Некорректный файл может вызвать потерю NUMA-привязки подов.

---

## Практические сценарии

### Сценарий 1: Настройка Memory Manager для БД PostgreSQL

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
reservedSystemCPUs: "0-1"
kubeReserved:
  cpu: "500m"
  memory: "1Gi"
systemReserved:
  cpu: "500m"
  memory: "1Gi"
```

**Применение:**
```bash
# Перезапуск kubelet
sudo systemctl daemon-reload
sudo systemctl restart kubelet

# Проверка, что Memory Manager активен
cat /var/lib/kubelet/config.yaml | grep memoryManagerPolicy
# → memoryManagerPolicy: Static

# Проверка файла состояния
cat /var/lib/kubelet/memory_manager_state | python3 -m json.tool
# → Файл создан и содержит NUMA-информацию
```

**Манифест PostgreSQL:**
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
      containers:
      - name: postgres
        image: postgres:16
        resources:
          requests:
            cpu: "4"
            memory: "8Gi"
          limits:
            cpu: "4"
            memory: "8Gi"
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
# Проверка QoS класса
kubectl get pod -l app=postgres -n database -o jsonpath='{.items[0].status.qosClass}'
# → Guaranteed

# Проверка memory.min на узле
# Найти cgroup пода
CONTAINER_ID=$(docker inspect --format '{{.Id}}' $(kubectl get pod -l app=postgres -n database -o jsonpath='{.items[0].metadata.name}') 2>/dev/null || crictl inspect $(crictl pods --name $(kubectl get pod -l app=postgres -n database -o jsonpath='{.items[0].metadata.name}') -q | head -1) | jq -r '.info.pid')
# Проверить memory.min
cat /sys/fs/cgroup/kubepods/pod$(kubectl get pod -l app=postgres -n database -o jsonpath='{.items[0].metadata.uid}' | tr -d '-')/memory.min
# → 8589934592 (8Gi)

# Проверка NUMA-привязки памяти (на узле)
numastat -p $(pgrep -f postgres)
# → Вся память из одного NUMA-узла
```

**Cleanup:**
```bash
kubectl delete deployment postgres -n database
```

### Сценарий 2: Диагностика повреждённого memory_manager_state

**Симптом:**
```
kubectl get pods -A --field-selector spec.nodeName=worker-1 | grep -v Running
# NAME                          READY   STATUS              RESTARTS   AGE
# postgres-6b7d8f9c4-xxxxx     0/1     Terminating         5          10m
```

**Диагностика:**
```bash
# Шаг 1: Проверка логов kubelet
journalctl -u kubelet | grep -i "memory_manager"
# → E0830 12:00:00.123456 12345 memory_manager.go:200] "Failed to restore state" err="failed to unmarshal state file"

# Шаг 2: Проверка файла состояния
cat /var/lib/kubelet/memory_manager_state | python3 -m json.tool
# → Ошибка парсинга или повреждённый JSON

# Шаг 3: Проверка прав доступа
ls -la /var/lib/kubelet/memory_manager_state
# → -rw-r--r-- 1 root root 1234 Aug 30 12:00 memory_manager_state
```

**Решение:**
```bash
# 1. Остановка kubelet
sudo systemctl stop kubelet

# 2. Удаление повреждённого файла
sudo rm -f /var/lib/kubelet/memory_manager_state

# 3. Запуск kubelet (пересоздаст файл)
sudo systemctl start kubelet

# 4. Проверка, что файл пересоздан
cat /var/lib/kubelet/memory_manager_state | python3 -m json.tool
# → Валидный JSON с NUMA-информацией

# 5. Проверка, что поды восстановились
kubectl get pods -A --field-selector spec.nodeName=worker-1
# → Все поды в статусе Running
```

### Сценарий 3: Проверка выделения памяти по NUMA-узлам

```bash
# На узле: проверка памяти по NUMA-узлам для конкретного пода
POD_UID=$(kubectl get pod my-pod -o jsonpath='{.metadata.uid}')

# Проверка cgroup memory.min (гарантированная память)
cat /sys/fs/cgroup/kubepods/pod${POD_UID}/memory.min
# → 4294967296 (4Gi)

# Проверка распределения памяти
numastat -p $(pgrep -f "container_name")
# → Процесс использует память только из одного NUMA-узла

# Проверка общей статистики NUMA
numastat -m | head -20
# node 0
# ​​​​​anonymous                     12345678
# file                            23456789
# ...
```

---

## Дополнительная информация

### Диагностика и мониторинг

```bash
# Проверка политики Memory Manager
cat /var/lib/kubelet/config.yaml | grep memoryManagerPolicy
# → memoryManagerPolicy: Static

# Проверка файла состояния
cat /var/lib/kubelet/memory_manager_state | python3 -m json.tool

# Проверка NUMA-памяти
numactl --hardware
numastat -m

# Проверка cgroup v2 для контейнера
cat /sys/fs/cgroup/kubepods/pod<pod-uid>/memory.min
cat /sys/fs/cgroup/kubepods/pod<pod-uid>/memory.high

# Проверка, что под имеет Guaranteed QoS
kubectl get pod <pod-name> -o jsonpath='{.status.qosClass}'
# → Guaranteed
```

### Troubleshooting

#### Проблема: Memory Manager не активен

**Симптом:** Поды запускаются без NUMA-привязки памяти.

**Диагностика:**
```bash
# Проверка политики
cat /var/lib/kubelet/config.yaml | grep memoryManagerPolicy
# → memoryManagerPolicy: None

# Проверка CPU Manager
cat /var/lib/kubelet/config.yaml | grep cpuManagerPolicy
# → cpuManagerPolicy: none
```

**Решение:**
1. Установите `memoryManagerPolicy: Static`.
2. Убедитесь, что `cpuManagerPolicy: static` (обязательно).
3. Перезапустите kubelet: `sudo systemctl restart kubelet`.

#### Проблема: Под в состоянии Terminating с ошибкой Memory Manager

**Симптом:** Под не может запуститься из-за нехватки памяти на NUMA-узле.

**Диагностика:**
```bash
# Проверка событий пода
kubectl describe pod <pod-name> | grep -A 5 "Events"
# → Warning  MemoryManagerAllocation  insufficient memory on NUMA node

# Проверка доступной памяти
numactl --hardware | grep "node.*free"
# → node 0 free: 1000 MB (недостаточно)
```

**Решение:**
1. Уменьшите `requests.memory` пода.
2. Освободите память на NUMA-узле (удалите другие поды).
3. Используйте `memoryManagerPolicy: None` если NUMA-изоляция не критична.

### Рекомендации (Best Practices)

* **Всегда используйте `memoryManagerPolicy: Static`:** Для production-серверов с NUMA-топологией.
* **Комбинируйте с Topology Manager:** Установите `topologyManagerPolicy: restricted` или `single-numa-node` для полной NUMA-изоляции.
* **Резервируйте память:** Используйте `kubeReserved` и `systemReserved` для системных процессов.
* **Мониторьте memory.min:** Проверяйте, что `memory.min` установлен корректно для Guaranteed-подов.
* **Берегите memory_manager_state:** Не редактируйте файл вручную. При повреждении Kubelet пересоздаёт его, но NUMA-привязка подов может потеряться.

### Вопросы на собеседовании

#### Зачем нужен Memory Manager в Kubernetes?
Memory Manager обеспечивает NUMA-осознанное выделение памяти, гарантируя, что память пода выделяется из того же NUMA-узла, что и CPU и устройства. Это минимизирует задержки доступа к памяти и критично для latency-critical приложений.

#### Как Memory Manager связан с cgroups v2?
Memory Manager устанавливает `memory.min` в cgroups v2 для Guaranteed-подов, гарантируя, что ОС никогда не заберёт этот объём памяти. Это реализует механизм Guaranteed Memory Reservation.

#### Какие требования к подам для работы Memory Manager?
Под должен быть `Guaranteed` QoS (requests == limits), CPU запрашиваться целыми числами. Memory Manager работает только с `cpuManagerPolicy: static` и `memoryManagerPolicy: Static`.

#### Что такое memory_manager_state и зачем он нужен?
Это JSON-файл, в котором Kubelet хранит состояние выделения памяти по NUMA-узлам. Он используется для согласования между перезапусками kubelet. При повреждении Kubelet пересоздаёт его, но NUMA-привязка подов может потеряться.

### См. также

* [Topology Manager](./topology_manager.md) — координация CPU, Memory и Device Manager
* [QoS, Requests и Limits](./qos_limit_and_requests.md) — классы QoS и управление ресурсами
* [Device Manager](./device_manager.md) — управление GPU и специализированным оборудованием
* [Affinity и Anti-Affinity](./affinity.md) — управление размещением подов
