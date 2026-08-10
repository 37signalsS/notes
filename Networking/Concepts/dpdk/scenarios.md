# Практические сценарии DPDK и SR-IOV

### Определения

- **NFV (Network Function Virtualization)**: Концепция виртуализации сетевых служб (брандмауэры, VPN, балансировщики), которые традиционно выполнялись на специализированном оборудовании.
- **CNF (Cloud-Native Network Function)**: Сетевая функция, разработанная для работы в контейнерах (Kubernetes), использующая DPDK или SR-IOV для достижения производительности уровня bare-metal.
- **UPF (User Plane Function)**: Ключевой компонент ядра сети 5G, отвечающий за обработку и маршрутизацию пользовательского трафика. Требует экстремально высокой пропускной способности.
- **HFT (High-Frequency Trading)**: Алгоритмическая торговля на финансовых рынках, где критическим фактором является «tick-to-trade» задержка, измеряемая в микро- и наносекундах.
- **AI Fabric**: Сетевая топология (часто на базе InfiniBand или RoCEv2), оптимизированная для обмена данными между узлами обучения ИИ на скоростях 400G/800G.

---

### Основные концепции

В 2026 году связка DPDK и SR-IOV является стандартом де-факто для высокопроизводительных вычислений и телекоммуникаций. Основная цель — исключить участие ядра ОС в обработке данных («kernel bypass»).

**Ключевые преимущества в сценариях:**
- **Предсказуемость**: Отсутствие случайных задержек, вызванных планировщиком задач ядра или обработкой прерываний.
- **Масштабируемость**: Возможность обработки терабитных потоков на стандартных x86 серверах.
- **Эффективность**: Высвобождение ресурсов CPU для прикладной логики за счет аппаратной разгрузки (offloading).

---

### Практические сценарии

#### Сценарий 1: Kubernetes — Сеть для ИИ-инференса через SR-IOV
Обеспечение прямого доступа контейнера к сетевому адаптеру для работы с GPUDirect RDMA.

1.  **Инфраструктура**: Использование **SR-IOV Network Device Plugin**.
2.  **Конфигурация**: Создание `NetworkAttachmentDefinition` (Multus CNI).
3.  **Использование**: Запрос ресурса в манифесте пода.

```yaml
apiVersion: "k8s.cni.cncf.io/v1"
kind: NetworkAttachmentDefinition
metadata:
  name: sriov-rdma-network
spec:
  config: '{
      "cniVersion": "0.3.1",
      "type": "sriov",
      "vlan": 100,
      "link_state": "enable"
    }'
---
apiVersion: v1
kind: Pod
metadata:
  name: ai-worker
  annotations:
    k8s.v1.cni.cncf.io/networks: sriov-rdma-network
spec:
  containers:
  - name: llama-3-engine
    image: nvidia/cuda:12.x-base
    resources:
      limits:
        nvidia.com/sriov: '1' # Выделение аппаратной VF
```

#### Сценарий 2: Open vSwitch (OVS) в режиме DPDK
Использование OVS-DPDK как основы для облачных платформ (OpenStack, CloudStack) при работе с 100G+ каналами.

```bash
# Выделение HugePages (1 ГБ страницы)
echo 4 > /sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages

# Настройка OVS для работы в Userspace
ovs-vsctl set Open_vSwitch . other_config:dpdk-init=true
ovs-vsctl set Open_vSwitch . other_config:dpdk-lcore-mask=0x3 # Привязка к ядрам 0 и 1
ovs-vsctl set Open_vSwitch . other_config:pmd-cpu-mask=0xc    # Ядра для обработки пакетов (2,3)

# Создание моста и добавление порта
ovs-vsctl add-br br-dpdk -- set bridge br-dpdk datapath_type=netdev
ovs-vsctl add-port br-dpdk dpdk0 -- set Interface dpdk0 type=dpdk options:dpdk-devargs=0000:01:00.0
```

#### Сценарий 3: VPP (Vector Packet Processing) для Edge-маршрутизации
Применение VPP как высокопроизводительного программного роутера на границе сети.

Пример настройки интерфейса в `vppctl`:
```bash
# Создание интерфейса на базе VFIO
vppctl create interface dbdk dev 0000:01:00.0 name eth0

# Настройка IP и включение
vppctl set interface state eth0 up
vppctl set interface ip address eth0 10.0.0.1/24

# Включение векторной обработки (по умолчанию) обеспечивает
# пропускную способность до 1 Тбит/с на современных CPU.
```

#### Сценарий 4: 5G UPF (User Plane Function)
Реализация ядра 5G сети на базе DPDK для обработки миллионов сессий одновременно.

**Особенности реализации:**
- **N6 Termination**: Использование DPDK для инкапсуляции/декапсуляции GTP-U трафика.
- **Zero-Copy**: Пакеты передаются между сетевой картой и UPF приложением без копирования в памяти.
- **NUMA-awareness**: Запуск потоков UPF строго на тех ядрах CPU, которые физически подключены к PCIe-шине сетевой карты.

#### Сценарий 5: HFT — Ультра-низкая задержка
Тюнинг системы для минимизации задержек при получении рыночных данных (Market Data).

**Ключевые настройки:**
- **Isolate CPUs**: Выделение ядер только под DPDK-приложение (параметр ядра `isolcpus`).
- **No Interrupts**: Отключение прерываний на ядрах обработки (Polling mode).
- **Direct I/O**: Использование DPDK PMD (Poll Mode Driver) для прямого опроса регистров NIC.
- **Hardware Timestamping**: Фиксация времени прибытия пакета на уровне аппаратного обеспечения сетевой карты.

---

### Дополнительная информация

- **[Обзор DPDK](dpdk_overview.md)** — архитектура обхода ядра и работа PMD.
- **[Обзор SR-IOV](sriov.md)** — аппаратная виртуализация PCI-устройств.
- **[Настройка SR-IOV](sriov_setup.md)** — подготовка BIOS, IOMMU и создание VF.
- **[Технические детали DPDK](dpdk_technical.md)** — глубокий разбор HugePages, TLB и выравнивания памяти.
- **[Open vSwitch (OVS)](../../ServicesAndTools/open_vswitch.md)** — детальное руководство по настройке программных коммутаторов.
