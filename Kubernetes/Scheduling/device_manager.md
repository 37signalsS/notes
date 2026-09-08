# Device Manager — управление специализированным оборудованием

## Определения

**Device Manager** — компонент Kubelet, который управляет доступом подов к специализированному оборудованию (GPU, FPGA, RDMA, SR-IOV NIC) через механизм **Device Plugins**. Он отвечает за обнаружение, регистрацию и выделение устройств, а также за координацию с Topology Manager для NUMA-осознанного выделения.

**Device Plugin** — плагин, реализующий gRPC-интерфейс `k8s.io/device-plugin`. Каждый плагин отвечает за конкретный тип устройства (NVIDIA GPU, Intel SR-IOV, AMD GPU). Device Plugin работает как DaemonSet на узлах и сообщает kubelet о доступных устройствах.

**Extended Resources (Расширенные ресурсы)** — ресурсы, не встроенные в ядро Kubernetes (например, `nvidia.com/gpu`, `intel.com/sriov_net`). Запрашиваются целыми числами, `requests` должны быть равны `limits`.

**Device Plugin Registry Directory** (`/var/lib/kubelet/device-plugins/`) — директория, в которой Device Plugins регистрируют свои gRPC-сокеты. Kubelet отслеживает эту директорию для обнаружения новых плагинов.

**Dynamic Resource Allocation (DRA)** — механизм (Beta с K8s 1.30+), приходящий на смену Device Plugins. Позволяет описывать сложные требования к ресурсам через `ResourceClaim` и `ResourceClass`, обеспечивая более глубокую интеграцию со специфическим железом.

---

## Предварительные требования

### Требования к кластеру

* **Kubernetes:** 1.26+ (Device Plugins GA), 1.30+ (DRA Beta)
* **Kubelet:** доступ к директории `/var/lib/kubelet/device-plugins/`
* **Container Runtime:** containerd 1.6+ или CRI-O 1.20+

### Требования к узлам

* **Драйверы устройства:** установленные драйверы (NVIDIA Driver, Intel SR-IOV, etc.)
* **Device Plugin:** запущенный DaemonSet с соответствующим плагином
* **NUMA-информация:** для NUMA-осознанного выделения (опционально, но рекомендуется)

### Проверка доступных устройств

```bash
# Проверка GPU (NVIDIA)
nvidia-smi -L
# → GPU 0: NVIDIA A100-SXM4-40GB (UUID: GPU-xxx)
# → GPU 1: NVIDIA A100-SXM4-40GB (UUID: GPU-yyy)

# Проверка NUMA-привязки GPU
nvidia-smi topo -m
#        GPU0  GPU1  CPU Affinity
# GPU0     X   NV12  16-31
# GPU1    NV12   X   0-15

# Проверка SR-IOV NIC
ip link show
# → eno1: <BROADCAST,MULTICAST,UP> ... (основной NIC)
# → eno1v0: <BROADCAST,MULTICAST,UP> ... (VF)

# Проверка FPGA (Intel)
fpgainfo fme
# → Функция FME: драйверы установлены

# Проверка, что kubelet видит устройства
kubectl get nodes -o json | jq '.items[].status.capacity'
# → "nvidia.com/gpu": "2"
# → "intel.com/sriov_net": "4"
```

---

## Основные концепции

### Архитектура Device Plugin

```
┌─────────────────────────────────────────────────┐
│                    Kubelet                        │
│  ┌─────────────────────────────────────────────┐ │
│  │           Device Manager                    │ │
│  │  • Обнаружение плагинов                     │ │
│  │  • Регистрация устройств                    │ │
│  │  • Выделение устройств подам                │ │
│  │  • Координация с Topology Manager           │ │
│  └─────────────────────────────────────────────┘ │
│         │                                        │
│         ▼                                        │
│  /var/lib/kubelet/device-plugins/                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ NVIDIA   │  │ SR-IOV   │  │ FPGA     │      │
│  │ sock     │  │ sock     │  │ sock     │      │
│  └──────────┘  └──────────┘  └──────────┘      │
│       │              │              │            │
│       ▼              ▼              ▼            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ NVIDIA   │  │ SR-IOV   │  │ FPGA     │      │
│  │ Device   │  │ Device   │  │ Device   │      │
│  │ Plugin   │  │ Plugin   │  │ Plugin   │      │
│  └──────────┘  └──────────┘  └──────────┘      │
└─────────────────────────────────────────────────┘
```

### Жизненный цикл Device Plugin

1. **Registration:** Device Plugin регистрируется в kubelet через gRPC-сокет в `/var/lib/kubelet/device-plugins/`.
2. **Discovery:** Kubelet запускает `ListAndWatch` RPC для получения списка доступных устройств.
3. **Allocation:** При создании пода с `resources.limits` для устройства kubelet вызывает `Allocate` RPC для выделения устройства.
4. **Monitoring:** Device Plugin отслеживает здоровье устройств и сообщает о проблемах через `ListAndWatch`.

### Интерфейс Device Plugin

Каждый Device Plugin реализует gRPC-интерфейс:

```protobuf
service DevicePlugin {
    // ListAndWatch возвращает список доступных устройств
    rpc ListAndWatch(Empty) returns (stream ListAndWatchResponse);
    
    // Allocate выделяет устройства поду
    rpc Allocate(AllocateRequest) returns (AllocateResponse);
    
    // GetDevicePluginOptions возвращает опции плагина
    rpc GetDevicePluginOptions(Empty) returns (DevicePluginOptions);
    
    // PreStartOptional вызывается перед запуском контейнера
    rpc PreStartOptional(PreStartRequest) returns (PreStartResponse);
}
```

### Extended Resources в Kubernetes

Device Plugins регистрируют **расширенные ресурсы** в kubelet. Эти ресурсы:

* **Запрашиваются целыми числами:** `nvidia.com/gpu: 1`, `intel.com/sriov_net: 2`
* **Требуют requests == limits:** Дробное выделение невозможно (кроме DRA)
* **Учитываются планировщиком:** Kube-scheduler проверяет наличие устройства на узле перед планированием
* **Отслеживаются kubelet:** Kubelet мониторит использование устройств подами

### Доступные Device Plugins

| Плагин | Ресурс | Описание |
|:---|:---|:---|
| **NVIDIA Device Plugin** | `nvidia.com/gpu` | Управление GPU (CUDA, MIG, Time-slicing) |
| **Intel SR-IOV Network Device Plugin** | `intel.com/sriov_net`, `intel.com/sriov_netd` | Виртуальные функции сетевых адаптеров |
| **Intel FPGA Device Plugin** | `intel.com/fpga_fec`, `intel.com/fpga_mgmt` | Программируемые логические матрицы |
| **AMD GPU Device Plugin** | `amd.com/gpu` | GPU AMD (ROCm) |
| **RDMA Device Plugin** | `rdma/rdma_shared_device_a` | RDMA-устройства (InfiniBand, RoCE) |
| **QAT Device Plugin** | `intel.com/qat` | Устройства аппаратного ускорения |

### NUMA-осознанное выделение

Device Manager координирует с Topology Manager для выделения устройств из правильного NUMA-узла:

```bash
# Проверка NUMA-привязки GPU
nvidia-smi topo -m
# GPU0: CPU Affinity 16-31 → NUMA 1
# GPU1: CPU Affinity 0-15  → NUMA 0

# Проверка NUMA-привязки SR-IOV NIC
cat /sys/bus/pci/devices/0000:3b:00.0/numa_node
# → 1 (устройство привязано к NUMA node 1)
```

Если Topology Manager настроен как `single-numa-node`, под может получить GPU только из NUMA-узла, где уже выделены CPU и память.

---

## Практические сценарии

### Сценарий 1: Развертывание NVIDIA Device Plugin

**Установка через Helm:**
```bash
# Добавление репозитория
helm repo add nvdp https://nvidia.github.io/k8s-device-plugin
helm repo update

# Установка Device Plugin
helm install nvdp nvdp/nvidia-device-plugin \
  --namespace kube-system \
  --set config.map.default="{
    \"version\": \"v1\",
    \"flags\": {
      \"migStrategy\": \"none\"
    }
  }"
```

**Проверка установки:**
```bash
# Проверка DaemonSet
kubectl get daemonset -n kube-system nvidia-device-plugin-daemonset
# NAME                        DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE
# nvidia-device-plugin        3         3         3       3            3

# Проверка доступных GPU
kubectl get nodes -o json | jq '.items[].status.capacity | select(."nvidia.com/gpu")'
# {
#   "nvidia.com/gpu": "2"
# }

# Проверка логов Device Plugin
kubectl logs -n kube-system -l app=nvidia-device-plugin-daemonset --tail=50
# → I0830 12:00:00.123456 12345 main.go:200] "Starting plugin" device=nvidia
# → I0830 12:00:00.124567 12345 main.go:300] "Registered device" device=nvidia count=2
```

**Манифест Pod с GPU:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: gpu-workload
  namespace: ml
spec:
  containers:
  - name: cuda-container
    image: nvidia/cuda:12.0-base
    resources:
      requests:
        cpu: "2"
        memory: "4Gi"
        nvidia.com/gpu: 1
      limits:
        cpu: "2"
        memory: "4Gi"
        nvidia.com/gpu: 1
    command: ["nvidia-smi"]
```

**Валидация:**
```bash
# Применение
kubectl apply -f gpu-pod.yaml

# Проверка, что под запущен
kubectl get pod gpu-workload -n ml
# NAME            READY   STATUS    RESTARTS   AGE
# gpu-workload    1/1     Running   0          30s

# Проверка, что GPU выделена
kubectl exec gpu-workload -n ml -- nvidia-smi -L
# → GPU 0: NVIDIA A100-SXM4-40GB (UUID: GPU-xxx)

# Проверка использования GPU
kubectl exec gpu-workload -n ml -- nvidia-smi
# → Нагрузка на GPU 0
```

**Cleanup:**
```bash
kubectl delete pod gpu-workload -n ml
helm uninstall nvdp -n kube-system
```

### Сценарий 2: Развертывание SR-IOV Network Device Plugin

**Установка:**
```bash
# Клонирование репозитория
git clone https://github.com/k8snetworkplumbingwg/sriov-network-device-plugin.git
cd sriov-network-device-plugin

# Установка через Helm
helm install sriov-device-plugin ./deployments/sriov-network-device-plugin \
  --namespace kube-system \
  --set resourcePrefix=intel.com
```

**Конфигурация SR-IOV:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: sriov-device-plugin-config
  namespace: kube-system
data:
  config.json: |
    {
      "resourceList": [
        {
          "resourceName": "sriov_net",
          "selectors": {
            "drivers": ["iavf"],
            "devices": ["8086:154c"],
            "pfNames": ["enp1s0f0"]
          }
        }
      ]
    }
```

**Манифест Pod с SR-IOV:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: sriov-pod
  namespace: networking
spec:
  containers:
  - name: app
    image: fedora:38
    command: ["sleep", "infinity"]
    resources:
      requests:
        intel.com/sriov_net: 1
      limits:
        intel.com/sriov_net: 1
```

**Валидация:**
```bash
# Проверка доступных SR-IOV ресурсов
kubectl get nodes -o json | jq '.items[].status.capacity | select(."intel.com/sriov_net")'
# {
#   "intel.com/sriov_net": "4"
# }

# Применение
kubectl apply -f sriov-pod.yaml

# Проверка, что VF выделена
kubectl exec sriov-pod -n networking -- ip link show
# → net1: <BROADCAST,MULTICAST,UP> ... (VF выделена)

# Проверка производительности
kubectl exec sriov-pod -n networking -- iperf3 -c <server-ip>
# → Высокая пропускная способность без виртуализации
```

### Сценарий 3: Мониторинг использования GPU

```bash
# Проверка использования GPU по подам
kubectl exec -n kube-system $(kubectl get pod -n kube-system -l app=nvidia-device-plugin-daemonset -o name | head -1) -- nvidia-smi
# → Таблица использования GPU

# Проверка через Prometheus (если установлен DCGM Exporter)
kubectl get pods -n monitoring -l app=dcgm-exporter
# → Prometheus собирает метрики GPU

# Ключевые метрики:
# DCGM_FI_DEV_GPU_UTIL — загрузка GPU (%)
# DCGM_FI_DEV_FB_USED — использованная память GPU (MiB)
# DCGM_FI_DEV_GPU_TEMP — температура GPU (°C)
```

---

## Дополнительная информация

### Диагностика и мониторинг

```bash
# Проверка Device Plugin DaemonSet
kubectl get daemonset -n kube-system -l app=nvidia-device-plugin

# Проверка логов Device Plugin
kubectl logs -n kube-system -l app=nvidia-device-plugin-daemonset --tail=50

# Проверка доступных расширенных ресурсов
kubectl get nodes -o json | jq '.items[].status.capacity | select(."nvidia.com/gpu")'

# Проверка использования устройств подами
kubectl describe nodes | grep -A 20 "Allocated resources"

# Проверка NUMA-привязки устройств (на узле)
nvidia-smi topo -m
cat /sys/bus/pci/devices/0000:3b:00.0/numa_node

# Проверка сокетов Device Plugin
ls -la /var/lib/kubelet/device-plugins/
# → NVIDIA.sock, intel_sriov_net.sock, etc.
```

### Troubleshooting

#### Проблема: GPU не отображается в `kubectl get nodes`

**Симптом:**
```bash
kubectl get nodes -o json | jq '.items[].status.capacity | select(."nvidia.com/gpu")'
# → null
```

**Диагностика:**
```bash
# Проверка, что Device Plugin запущен
kubectl get pods -n kube-system -l app=nvidia-device-plugin-daemonset
# → Должны быть Running на всех узлах с GPU

# Проверка логов Device Plugin
kubectl logs -n kube-system -l app=nvidia-device-plugin-daemonset
# → Ищите ошибки регистрации

# Проверка драйверов NVIDIA на узле
nvidia-smi
# → Должен показывать список GPU
```

**Решение:**
1. Установите или обновите драйверы NVIDIA на узле.
2. Перезапустите Device Plugin: `kubectl rollout restart daemonset -n kube-system nvidia-device-plugin-daemonset`.
3. Проверьте, что `/var/lib/kubelet/device-plugins/` содержит `NVIDIA.sock`.

#### Проблема: Под в состоянии Pending с ошибкой `nvidia.com/gpu`

**Симптом:**
```
kubectl describe pod gpu-pod
# Warning  FailedScheduling  0/3 nodes are available:
# 3 Insufficient nvidia.com/gpu.
```

**Диагностика:**
```bash
# Проверка доступных GPU на узлах
kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, gpu: .status.capacity["nvidia.com/gpu"]}'
# → name: worker-1, gpu: "0"  ← Нет GPU!

# Проверка использования GPU
kubectl describe nodes | grep -A 5 "nvidia.com/gpu"
# → Allocated: 2/2 (все GPU заняты)
```

**Решение:**
1. Добавьте узлы с GPU в кластер.
2. Уменьшите количество запрашиваемых GPU.
3. Используйте Cluster Autoscaler для автоматического добавления GPU-узлов.

#### Проблема: Device Plugin не регистрируется

**Симптом:**
```bash
ls -la /var/lib/kubelet/device-plugins/
# → NVIDIA.sock отсутствует
```

**Диагностика:**
```bash
# Проверка логов Device Plugin
kubectl logs -n kube-system -l app=nvidia-device-plugin-daemonset
# → E0830 12:00:00.123456 12345 main.go:200] "Failed to register" err="connection refused"

# Проверка, что Device Plugin имеет доступ к `/var/lib/kubelet/device-plugins/`
kubectl describe pod -n kube-system -l app=nvidia-device-plugin-daemonset | grep -A 10 "Volumes"
```

**Решение:**
1. Проверьте, что Device Plugin имеет hostPath mount для `/var/lib/kubelet/device-plugins/`.
2. Перезапустите Device Plugin.
3. Проверьте, что kubelet запущен и доступен.

### Рекомендации (Best Practices)

* **Используйте DaemonSet:** Device Plugin должен работать на каждом узле с устройствами.
* **Мониторьте здоровье устройств:** Настройте алерты на падение Device Plugin или ошибки устройств.
* **Используйте NUMA-осознанное выделение:** Комбинируйте с Topology Manager для latency-critical нагрузок.
* **Документируйте устройства:** Ведите реестр GPU/FPGA/SR-IOV NIC по узлам и NUMA-узлам.
* **Тестируйте обновления:** При обновлении драйверов или Device Plugin проверяйте на staging-кластере.
* **Используйте MIG для GPU:** Для melodyworkloads используйте MIG (Multi-Instance GPU) для изоляции.

### Вопросы на собеседовании

#### Как работает Device Plugin в Kubernetes?
Device Plugin регистрируется в kubelet через gRPC-сокет в `/var/lib/kubelet/device-plugins/`. Kubelet вызывает `ListAndWatch` для получения списка устройств и `Allocate` для выделения устройства поду. Device Plugin сообщает о расширенных ресурсах (например, `nvidia.com/gpu`), которые учитываются планировщиком.

#### Чем DRA отличается от Device Plugin?
DRA (Dynamic Resource Allocation) — более гибкий механизм, позволяющий описывать сложные требования к ресурсам через `ResourceClaim` и `ResourceClass`. В отличие от Device Plugin, DRA поддерживает дробное выделение, группировку устройств и интеграцию с Topology Manager на более глубоком уровне.

#### Как Device Plugin связан с Topology Manager?
Device Manager сообщает Topology Manager о NUMA-привязке каждого устройства. Topology Manager учитывает эту информацию при координации CPU, Memory и Device Manager, гарантируя, что все ресурсы выделяются из одного NUMA-узла.

#### Как проверить, что GPU выделена поду?
```bash
kubectl exec <pod> -- nvidia-smi
# → Показывает используемые GPU
kubectl describe node <node> | grep -A 5 "nvidia.com/gpu"
# → Показывает выделенные GPU
```

### См. также

* [Topology Manager](./topology_manager.md) — координация CPU, Memory и Device Manager
* [Memory Manager](./memory_manager.md) — NUMA-осознанное выделение памяти
* [QoS, Requests и Limits](./qos_limit_and_requests.md) — расширенные ресурсы и QoS
* [Affinity и Anti-Affinity](./affinity.md) — управление размещением подов
