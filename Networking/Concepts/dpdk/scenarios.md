# Практические сценарии DPDK и SR-IOV

### Определения

- **NFV (Network Function Virtualization)**: Виртуализация сетевых функций (маршрутизаторы, межсетевые экраны) на стандартном серверном оборудовании.
- **CNF (Cloud-Native Network Function)**: Сетевая функция, реализованная в виде контейнера (обычно в Kubernetes), требующая сверхвысокой производительности.
- **HFT (High-Frequency Trading)**: Высокочастотный трейдинг, где задержки измеряются наносекундами.
- **AI Fabric**: Специализированная сетевая инфраструктура для обучения больших языковых моделей (LLM), требующая пропускной способности 400G/800G и RDMA.

---

### Основные концепции

DPDK и SR-IOV совместно обеспечивают производительность, сопоставимую с «голым железом» (Bare Metal), в виртуализированных средах.

**Типичные области применения (2026):**
- **ИИ-кластеры**: Передача данных между GPU через GPUDirect RDMA.
- **Облачные сети**: Ускорение виртуальных коммутаторов (OVS, VPP) для работы на скоростях 800 Гбит/с.
- **Телеком (5G/6G)**: Обработка трафика в ядре мобильной сети (UPF).
- **Кибербезопасность**: Анализ трафика в реальном времени на скоростях 400 Гбит/с (IDS/IPS).

---

### Практические сценарии

#### Сценарий 1: Kubernetes — прямой доступ к сети через SR-IOV
Используется для предоставления поду прямого доступа к аппаратной виртуальной функции (VF).

1.  **Хост**: Настройка SR-IOV и создание VF.
2.  **Кластер**: Установка **SR-IOV Network Device Plugin**.
3.  **Пользователь**: Определение ресурса в манифесте пода.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: ai-inference-pod
  annotations:
    k8s.v1.cni.cncf.io/networks: sriov-network-800g
spec:
  containers:
  - name: inference-engine
    image: ai-app:2026-latest
    resources:
      limits:
        nvidia.com/sriov: '1' # Запрос аппаратной VF
```

#### Сценарий 2: Open vSwitch (OVS) с поддержкой DPDK
Замена стандартного датапаса ядра на высокопроизводительный userspace-движок.

```bash
# Инициализация OVS с выделением HugePages (2 ГБ на сокет)
ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-init=true
ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-socket-mem="2048,2048"

# Создание моста с типом netdev (userspace)
ovs-vsctl add-br br-highspeed -- set bridge br-highspeed datapath_type=netdev

# Привязка физической NIC (PCI Gen6) как DPDK-порта
ovs-vsctl add-port br-highspeed dpdk0 -- set Interface dpdk0 type=dpdk \
    options:dpdk-devargs=0000:01:00.0
```

#### Сценарий 3: VPP (Vector Packet Processing)
Использование VPP как программного терабитного маршрутизатора.

Конфигурация драйвера в `/etc/vpp/startup.conf`:
```hcl
dpdk {
  dev 0000:01:00.0 {
    name port-800g
  }
  uio-driver vfio-pci
  num-mbufs 262144
}
```

---

### Дополнительная информация

- **[Обзор DPDK](dpdk_overview.md)** — архитектура обхода ядра.
- **[Обзор SR-IOV](sriov.md)** — аппаратная виртуализация I/O.
- **[Настройка SR-IOV](sriov_setup.md)** — пошаговое руководство по активации VF.
- **[Технические детали DPDK](dpdk_technical.md)** — оптимизация памяти и CPU.

**Reliability Score: 10 (Внутренняя база + Исследование 2026)**
