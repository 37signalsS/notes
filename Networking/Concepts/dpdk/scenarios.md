# Практические сценарии DPDK и SR-IOV

### Определения

- **NFV (Network Function Virtualization)**: Концепция виртуализации сетевых служб (брандмауэры, VPN, балансировщики), которые традиционно выполнялись на специализированном оборудовании. В контексте DPDK NFV-приложения работают в userspace, получая прямой доступ к NIC через Poll Mode Driver, что обеспечивает производительность уровня железа.
- **CNF (Cloud-Native Network Function)**: Сетевая функция, разработанная для работы в контейнерах (Kubernetes), использующая DPDK или SR-IOV для достижения производительности уровня bare-metal. Ключевое отличие от传统 NFV: microservices-архитектура, оркестрация через Kubernetes, stateless-принцип.
- **UPF (User Plane Function)**: Ключевой компонент ядра сети 5G, отвечающий за обработку и маршрутизацию пользовательского трафика. Требует экстремально высокой пропускной способности (терабиты) и минимальных задержек (sub-100 мкс). Реализуется поверх DPDK для обхода ядра.
- **HFT (High-Frequency Trading)**: Алгоритмическая торговля на финансовых рынках, где критическим фактором является «tick-to-trade» задержка, измеряемая в микро- и наносекундах. DPDK обеспечивает предсказуемую обработку пакетов без джиттера от ядра.
- **AI Fabric**: Сетевая топология (часто на базе InfiniBand или RoCEv2), оптимизированная для обмена данными между узлами обучения ИИ на скоростях 400G/800G. Использует GPUDirect RDMA через SR-IOV VF для прямого DMA-доступа между GPU и NIC.
- **IDS/IPS (Intrusion Detection/Prevention System)**: Системы обнаружения и предотвращения вторжений. При интеграции с DPDK получают прямой доступ к пакетам без копирования, что позволяет анализировать трафик на скоростях 100G+ без потерь.
- **vSwitch (Виртуальный коммутатор)**: Программный или аппаратный коммутатор, работающий на уровне L2, обеспечивающий коммутацию пакетов между виртуальными машинами, контейнерами и физическими сетями. OVS-DPDK — наиболее производительная программная реализация.

---

### Основные концепции

В 2026 году связка DPDK и SR-IOV является стандартом де-факто для высокопроизводительных вычислений и телекоммуникаций. Основная цель — исключить участие ядра ОС в обработке данных («kernel bypass»).

**Ключевые преимущества в сценариях:**
- **Предсказуемость**: Отсутствие случайных задержек, вызванных планировщиком задач ядра или обработкой прерываний. Джиттер снижается с микросекунд до наносекунд.
- **Масштабируемость**: Возможность обработки терабитных потоков на стандартных x86 серверах за счёт использования всех ядер CPU и аппаратной разгрузки NIC.
- **Эффективность**: Высвобождение ресурсов CPU для прикладной логики за счет аппаратной разгрузки (offloading). Один x86-сервер способен заменить десятки специализированных аппаратных устройств.

**Выбор технологии в зависимости от сценария:**

| Технология | Когда использовать | Компромисс |
| :--- | :--- | :--- |
| **DPDK** | Полная программируемость (NFV, HFT, custom protocol) | Высокая загрузка CPU (polling), сложность разработки |
| **SR-IOV** | Прямой проброс NIC в ВМ/контейнер (AI, DB) | Ограничена гибкостью NIC, нет live-миграции |
| **XDP/eBPF** | Фильтрация/маршрутизация в ядре (DDoS, load balance) | Ограничена логика eBPF, нет полного userspace-доступа |
| **OVS-DPDK** | Виртуальные сети в облаке (OpenStack, K8s) | Сложность настройки, требования к HugePages |
| **VPP** | Программная маршрутизация/коммутация (edge, telco) | Высокий порог входа, специфичный CLI |

---

### Предварительные требования

#### Общие (для всех сценариев DPDK)

**Аппаратное обеспечение:**
- x86_64 сервер с поддержкой VT-d (Intel) или AMD-Vi (AMD)
- Сетевой адаптер с поддержкой DPDK PMD: Intel E810/X710, NVIDIA ConnectX-6/7/8
- Достаточный объём RAM для HugePages (минимум 2 ГБ на сценарий)

**Программное обеспечение:**
- Linux kernel 5.15+ (рекомендуется 6.1+ LTS)
- DPDK 21.11+ (рекомендуется 24.11 или 25.11 LTS)
- Собранные и установленные библиотеки DPDK (`meson build && ninja -C build && sudo ninja -C build install`)

**BIOS/UEFI:**
- Включены **VT-d** (Intel) или **IOMMU** (AMD)
- Включена поддержка **SR-IOV Global Enable** (если используется SR-IOV)
- Отключены C-States (опционально, для HFT): `intel_cstate=0`

**Параметры ядра (GRUB):**
```bash
# /etc/default/grub — базовый набор для DPDK
GRUB_CMDLINE_LINUX_DEFAULT="default_hugepagesz=1G hugepagesz=1G hugepages=8 \
  intel_iommu=on iommu=pt"
# Для HFT добавить: isolcpus=2-15 nohz_full=2-15 rcu_nocbs=2-15 intel_pstate=disable
```

**Настройка HugePages:**
```bash
# Проверка доступных HugePages
grep -i huge /proc/meminfo
# → HugePages_Total:    0
# → HugePages_Free:     0
# → Hugepagesize:       1048576 kB

# Выделение 1 ГБ страниц (персистентно через GRUB или временно)
echo 8 > /sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages
# Проверка
cat /sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages
# → 8
```

**Привязка NIC к DPDK-драйверу (vfio-pci):**
```bash
# Загрузка модуля
sudo modprobe vfio-pci

# Проверка текущего драйвера
ethtool -i enp1s0
# → driver: ice

# Привязка к vfio-pci
sudo dpdk-devbind.py --bind=vfio-pci 0000:01:00.0

# Проверка результата
sudo dpdk-devbind.py --status
# → 0000:01:00.0 'Device 1592' if= enp1s0 drv=vfio-pci unused=ice
```

#### Дополнительные требования для SR-IOV

- SR-IOV включён в BIOS и ядре (см. [Настройка SR-IOV](sriov_setup.md))
- Загружен модуль `vfio-pci`
- Созданы VF (см. [Настройка SR-IOV](sriov_setup.md))

#### Дополнительные требования для Kubernetes

- Кластер Kubernetes 1.25+
- Установлен **Multus CNI** (для нескольких сетевых интерфейсов)
- Установлен **SR-IOV Network Device Plugin** (`k8s-for-nmstate` или `k8s-sriov-network-operator`)
- На узлах настроены HugePages и привязка NIC к vfio-pci

---

### Практические сценарии

#### Сценарий 1: Kubernetes — Сеть для ИИ-инференса через SR-IOV

**Цель**: Обеспечение прямого доступа контейнера к сетевому адаптеру для работы с GPUDirect RDMA. Критично для распределённого обучения ИИ, где GPU разных узлов обмениваются данными напрямую через NIC, минуя CPU.

**Пререквизиты:**
- Kubernetes 1.25+ с Multus CNI
- NVIDIA SR-IOV Network Device Plugin
- NIC с поддержкой SR-IOV (NVIDIA ConnectX-6 Dx или новее)
- NVIDIA GPU с поддержкой GPUDirect RDMA

**Шаг 1: Создание NetworkAttachmentDefinition (Multus CNI)**

```yaml
apiVersion: "k8s.cni.cncf.io/v1"
kind: NetworkAttachmentDefinition
metadata:
  name: sriov-rdma-network
  annotations:
    k8s.v1.cni.cncf.io/resourceName: nvidia.com/sriov_rdma
spec:
  config: '{
      "cniVersion": "0.3.1",
      "type": "sriov",
      "vlan": 100,
      "link_state": "enable",
      "ipam": {
        "type": "whereabouts",
        "range": "10.100.0.0/24"
      }
    }'
```

Применение:
```bash
kubectl apply -f sriov-nad.yaml
# Проверка
kubectl get network-attachment-definitions
# → NAME                  AGE
# → sriov-rdma-network    5s
```

**Шаг 2: Запуск Pod с выделенной VF**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: ai-worker
  annotations:
    k8s.v1.cni.cncf.io/networks: sriov-rdma-network
spec:
  nodeSelector:
    kubernetes.io/hostname: gpu-node-01
  containers:
  - name: llama-3-engine
    image: nvidia/cuda:12.6.0-base-ubuntu24.04
    command: ["sleep", "infinity"]
    resources:
      limits:
        nvidia.com/gpu: '1'
        nvidia.com/sriov_rdma: '1'
      requests:
        nvidia.com/gpu: '1'
        nvidia.com/sriov_rdma: '1'
    volumeMounts:
    - name: hugepages
      mountPath: /dev/hugepages
  volumes:
  - name: hugepages
    emptyDir:
      medium: HugePages-1Gi
      sizeLimit: 2Gi
```

**Шаг 3: Валидация внутри Pod**

```bash
# Проверка назначения VF
kubectl exec ai-worker -- ip link show
# → 3: net1: <BROADCAST,MULTICAST,UP,LOWER_UP> ...
# →     link/ether 52:54:00:00:01:01 brd ff:ff:ff:ff:ff:ff

# Проверка IP-адреса (из IPAM)
kubectl exec ai-worker -- ip addr show net1
# → 3: net1: <BROADCAST,MULTICAST,UP,LOWER_UP> ...
# →     inet 10.100.0.15/24 ...

# Проверка RDMA-доступности
kubectl exec ai-worker -- ibstat
# → CA 'mlx5_0'
# →     Port 1:
# →         State: Active
# →         Physical state: LinkUp
# →         Rate: 200 Gb/sec (4X HDR)

# Проверка GPUDirect RDMA
kubectl exec ai-worker -- nvidia-smi topo -m
# →        GPU0  NIC0
# → GPU0   X     NV12
# → NIC0  NV12    X
# → (NV12 = NVLink + PCIe, NIC0 = SR-IOV VF)
```

**Шаг 4: Тест производительности (RDMA между узлами)**

```bash
# На каждом узле запустить Perftest
kubectl exec ai-worker -- bash -c "ib_write_bw -d mlx5_0 -s 1048576 -n 10000"
# → #bytes     #iterations    BW peak(Gb/s)    BW average(Gb/s)
# → 1048576    10000          238.45           237.12
```

**Типичные ошибки и решения:**

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| VF не назначается Pod | `FailedCreatePodSandBox` в events | Проверьте resourceName в NAD и скап resources в Pod; убедитесь что SR-IOV device plugin запущен |
| RDMA не работает | `ibstat` показывает `State: Down` | Проверьте физическое подключение; убедитесь что `link_state: enable` в NAD |
| GPUDirect недоступен | `nvidia-smi topo` показывает `SYS/PCI` вместо `NV` | Установите NVIDIA GPUDirect Storage/RDMA драйвер; проверьте IOMMU-группу GPU и NIC |

**Очистка:**
```bash
kubectl delete pod ai-worker
kubectl delete network-attachment-definitions sriov-rdma-network
```

---

#### Сценарий 2: Open vSwitch (OVS) в режиме DPDK

**Цель**: Использование OVS-DPDK как основы для облачных платформ (OpenStack, CloudStack) при работе с 100G+ каналами. Программная коммутация в userspace обеспечивает пропускную способность до 100Mpps на одном сервере.

**Пререквизиты:**
- OVS 3.0+ (с поддержкой DPDK)
- DPDK 21.11+ установлен и настроен
- HugePages выделены (минимум 2 ГБ)
- NIC привязан к vfio-pci

**Шаг 1: Выделение HugePages**

```bash
# 1 ГБ HugePages (рекомендуется для OVS-DPDK)
echo 4 > /sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages

# Проверка
grep -i huge /proc/meminfo
# → HugePages_Total:    4
# → HugePages_Free:     4
# → Hugepagesize:       1048576 kB
```

**Шаг 2: Инициализация OVS с DPDK**

```bash
# Остановка OVS (если запущен в kernel-режиме)
sudo systemctl stop openvswitch-switch

# Настройка OVS для работы в Userspace
sudo ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-init=true
sudo ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-lcore-mask=0x3
sudo ovs-vsctl --no-wait set Open_vSwitch . other_config:pmd-cpu-mask=0xc
sudo ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-socket-mem="2048,2048"

# Запуск OVS
sudo systemctl start openvswitch-switch
```

Параметры:
- `dpdk-lcore-mask=0x3`: Ядра 0 и 1 для DPDK EAL (управление, mempool)
- `pmd-cpu-mask=0xc`: Ядра 2 и 3 для PMD-потоков (опрос NIC)
- `dpdk-socket-mem="2048,2048"`: 2 ГБ HugePages на каждый NUMA-узел

**Шаг 3: Создание моста и добавление портов**

```bash
# Создание моста с DPDK-datapath
sudo ovs-vsctl add-br br-dpdk -- set bridge br-dpdk datapath_type=netdev

# Добавление физического порта (PCI-адрес NIC)
sudo ovs-vsctl add-port br-dpdk dpdk0 \
  -- set Interface dpdk0 type=dpdk options:dpdk-devargs=0000:01:00.0

# Добавление второго порта (если есть второй NIC)
sudo ovs-vsctl add-port br-dpdk dpdk1 \
  -- set Interface dpdk1 type=dpdk options:dpdk-devargs=0000:01:00.1

# Проверка конфигурации
sudo ovs-vsctl show
# → Bridge br-dpdk
# →     Port dpdk0
# →         Interface dpdk0
# →             type: dpdk
# →             options: {dpdk-devargs="0000:01:00.0"}
# →     Port dpdk1
# →         Interface dpdk1
# →             type: dpdk
# →             options: {dpdk-devargs="0000:01:00.1"}
```

**Шаг 4: Настройка PMD и проверка производительности**

```bash
# Динамическая перенастройка PMD-потоков
sudo ovs-vsctl set Open_vSwitch . other_config:pmd-cpu-mask=0xf

# Просмотр статистики PMD
sudo ovs-appctl dpif-netdev/pmd-rxq-show
# → pmd thread numa_id 0 core_id 2:
# →   isolated : false
# →   port: dpdk0        queue-id: 0    pmd usage: 0 %
# →     rx packets: 12345678
# →     tx packets: 9876543

# Просмотр кэша datapath
sudo ovs-appctl dpif/show
# → system@ovs-system: hit:12345678 miss:9876543

# Тест производительности (iperf3 через OVS)
# На клиенте: iperf3 -c <server_ip> -t 30 -P 4
# Ожидаемый результат: ~95 Gbps на 100G-канале
```

**Шаг 5: Добавление VLAN и туннелей**

```bash
# VLAN access-порт (VLAN 100)
sudo ovs-vsctl add-port br-dpdk vhost0 \
  -- set Interface vhost0 type=dpdkvhostuser
sudo ovs-vsctl set port vhost0 tag=100

# VXLAN-туннель к удалённому хосту
sudo ovs-vsctl add-port br-dpdk vxlan0 \
  -- set Interface vxlan0 type=vxlan options:remote_ip=172.16.1.5

# Geneve-туннель (для OVN/SDN)
sudo ovs-vsctl add-port br-dpdk geneve0 \
  -- set Interface geneve0 type=geneve options:remote_ip=172.16.1.6
```

**Типичные ошибки и решения:**

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| OVS не стартует с DPDK | `ovs-vswitchd: dpdk_init failed` | Проверьте HugePages (`/proc/meminfo`); убедитесь что NIC привязан к `vfio-pci` |
| Низкий throughput | < 50 Gbps на 100G-канале | Увеличьте количество PMD-потоков; проверьте NUMA-локальность NIC и HugePages |
| PMD не видит порт | `dpdk-devargs` не распознаётся | Проверьте PCI-адрес через `lspci`; убедитесь что драйвер — `vfio-pci` |

**Очистка:**
```bash
sudo ovs-vsctl del-br br-dpdk
# Вернуть NIC к стандартному драйверу
sudo dpdk-devbind.py --bind=ice 0000:01:00.0
```

---

#### Сценарий 3: VPP (Vector Packet Processing) для Edge-маршрутизации

**Цель**: Применение VPP как высокопроизводительного программного роутера на границе сети. VPP обрабатывает пакеты группами (векторами), что обеспечивает пропускную способность до 1 Тбит/с на современных CPU.

**Пререквизиты:**
- VPP 24.02+ (с DPDK PMD)
- NIC привязан к vfio-pci
- HugePages выделены (минимум 1 ГБ)
- Включён IP forwarding в ядре (для маршрутизации)

**Шаг 1: Установка и первичная настройка VPP**

```bash
# Установка VPP (Ubuntu/Debian)
sudo apt install vpp vpp-plugin-core vpp-plugin-dpdk

# Конфигурация-startup.conf
cat > /etc/vpp/startup.conf << 'EOF'
unix {
  nodaemon
  log /var/log/vpp/vpp.log
  full-coredump
  cli-listen /run/vpp/cli.sock
  gid vpp
}

api-trace {
  on
}

cpu {
  main-core 1
  workers 2-3
}

memory {
  main-heap-size 2G
  numa-main 0
  numa-worker 0
}

plugins {
  plugin dpdk_plugin.so { enable }
  plugin default { disable }
  plugin dpdk_plugin.so { enable }
}

dpdk {
  dev 0000:01:00.0
  dev 0000:01:00.1
}
EOF

# Запуск VPP
sudo systemctl start vpp
```

**Шаг 2: Настройка интерфейсов**

```bash
# Создание интерфейса на базе DPDK
vppctl create interface dpdk dev 0000:01:00.0 name GigabitEthernet0/0/0

# Настройка IP и включение
vppctl set interface state GigabitEthernet0/0/0 up
vppctl set interface ip address GigabitEthernet0/0/0 10.0.0.1/24

# Второй интерфейс (uplink)
vppctl create interface dpdk dev 0000:01:00.1 name GigabitEthernet0/0/1
vppctl set interface state GigabitEthernet0/0/1 up
vppctl set interface ip address GigabitEthernet0/0/1 192.168.1.1/24
```

**Шаг 3: Настройка маршрутизации**

```bash
# Включение IP forwarding
vppctl set ip forwarding GigabitEthernet0/0/0 on
vppctl set ip forwarding GigabitEthernet0/0/1 on

# Статический маршрут к корпоративной сети
vppctl ip route add 172.16.0.0/16 via 192.168.1.254

# Проверка таблицы маршрутизации
vppctl show ip fib
# → IPv4 FIB:
# →   10.0.0.0/24
# →     -> GigabitEthernet0/0/0 (connected)
# →   172.16.0.0/16
# →     -> 192.168.1.254 via GigabitEthernet0/0/1
```

**Шаг 4: ACL и фильтрация**

```bash
# Создание ACL для фильтрации трафика
vppctl acl-plugin add acl \
  match in ip4 src 10.0.0.0/8 \
  permit

# Привязка ACL к интерфейсу
vppctl set interface acl GigabitEthernet0/0/0 input acl 0

# Просмотр статистики ACL
vppctl acl-plugin show
```

**Шаг 5: Валидация и мониторинг**

```bash
# Просмотр всех интерфейсов
vppctl show interface
# → GigabitEthernet0/0/0
# →   up
# →   GigabitEthernet0/0/1
# →   up

# Просмотр статистики (пакеты, байты, ошибки)
vppctl show interface GigabitEthernet0/0/0
# → ...
# →   RX:  12345678 packets  9876543210 bytes
# →   TX:  11223344 packets  8765432100 bytes

# Проверка ARP-таблицы
vppctl show ip arp
# → IP address      MAC address       Self  Age  Static  Interface
# → 10.0.0.2        52:54:00:11:22:33  no   5s   no      GigabitEthernet0/0/0

# Бенчмарк
vppctl packet-tracer enable
```

**Типичные ошибки и решения:**

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| VPP не видит NIC | `show interface` пуст | Проверьте PCI-адрес в `startup.conf`; убедитесь что NIC привязан к `vfio-pci` |
| Низкий throughput | < 100 Gbps на 100G-канале | Увеличьте количество workers; проверьте NUMA-локальность; используйте HugePages 1 ГБ |
| ARP не резолвится | `show ip arp` пуст | Проверьте физическое подключение; убедитесь что IP назначён правильно |

**Очистка:**
```bash
vppctl delete interface dpdk GigabitEthernet0/0/0
vppctl delete interface dpdk GigabitEthernet0/0/1
sudo systemctl stop vpp
sudo dpdk-devbind.py --bind=ice 0000:01:00.0
```

---

#### Сценарий 4: 5G UPF (User Plane Function)

**Цель**: Реализация ядра 5G сети на базе DPDK для обработки миллионов сессий одновременно. UPF отвечает за инкапсуляцию/декапсуляцию GTP-U трафика и маршрутизацию пользовательских данных.

**Пререквизиты:**
- DPDK-совместимое приложение UPF (Open5GS, free5GC, или коммерческое)
- NIC с поддержкой 100G+ (NVIDIA ConnectX-7, Intel E810)
- Минимум 16 ядер CPU, 32 ГБ RAM, 8 ГБ HugePages
- Знание архитектуры 5G Core (N3/N4/N6 интерфейсы)

**Особенности реализации:**
- **N3 Termination**: Приём GTP-U трафика от gNB (radio access network). Каждый пакет содержит GTP-заголовок с TEID (Tunnel Endpoint Identifier), идентифицирующий сессию абонента.
- **N6 Termination**: Выход в интернет. DPDK выполняет NAT/masquerading и инкапсуляцию/декапсуляцию GTP-U.
- **Zero-Copy**: Пакеты передаются между сетевой картой и UPF приложением без копирования в памяти. Достигается за счёт использования HugePages и DMA-движка NIC.
- **NUMA-awareness**: Запуск потоков UPF строго на тех ядрах CPU, которые физически подключены к PCIe-шине сетевой карты. Несоответствие NUMA добавляет 30-100 нс задержки на каждый пакет.

**Шаг 1: Конфигурация окружения**

```bash
# GRUB: изоляция ядер под UPF
# /etc/default/grub
GRUB_CMDLINE_LINUX_DEFAULT="default_hugepagesz=1G hugepagesz=1G hugepages=16 \
  intel_iommu=on iommu=pt isolcpus=4-19 nohz_full=4-19 rcu_nocbs=4-19"

# Выделение HugePages
echo 16 > /sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages

# Проверка NUMA-топологии NIC
cat /sys/class/net/enp1s0/device/numa_node
# → 0 (NIC подключён к NUMA-узлу 0)
```

**Шаг 2: Привязка NIC к DPDK**

```bash
# Привязка N3-интерфейса (вход от gNB)
sudo dpdk-devbind.py --bind=vfio-pci 0000:01:00.0

# Привязка N6-интерфейса (выход в интернет)
sudo dpdk-devbind.py --bind=vfio-pci 0000:01:00.1

# Проверка
sudo dpdk-devbind.py --status
# → 0000:01:00.0 'Device 1592' if= enp1s0 drv=vfio-pci
# → 0000:01:00.1 'Device 1592' if= enp1s1 drv=vfio-pci
```

**Шаг 3: Запуск UPF-приложения (пример: free5GC DPDK-UPF)**

```bash
# Конфигурация (upfcfg.yaml)
cat > /etc/free5gc/upfcfg.yaml << 'EOF'
version: 1.0.0
description: 5G UPF with DPDK

pfcp:
  addr: 10.0.0.1
  nodeID: 10.0.0.1

gtpu:
  forwarder: gtp5g  # или dpdk для DPDK-режима
  ifList:
    - addr: 10.0.0.1
      type: N3

dnnList:
  - dnn: internet
    cidr: 10.60.0.0/16
    enableNAT: true

# DPDK-specific
dpdk:
  cores: "4-19"
  mempool-size: 65536
  hugepages: "/dev/hugepages"
  rxQueues: 4
  txQueues: 4
EOF

# Запуск UPF с DPDK
sudo ./upf --config /etc/free5gc/upfcfg.yaml \
  --eal="--lcores=4-19 --socket-mem=8192,8192 --file-prefix=upf0"
```

**Шаг 4: Валидация**

```bash
# Проверка сессий (через PFCP)
# На SMF/CPF выполнить:
smf> pfcp session list
# → ID: 1, SEID: 1001, State: ACTIVE
# → ID: 2, SEID: 1002, State: ACTIVE

# Проверка GTP-U туннелей
tcpdump -i enp1s0 -nn "udp port 2152"
# → 10:00:01.123456 IP 10.0.0.2.2152 > 10.0.0.1.2152: GTP-U v1, TEID=1001, len=1400
# → 10:00:01.123789 IP 10.0.0.1.2152 > 10.0.0.2.2152: GTP-U v1, TEID=1002, len=1400

# Проверка таблицы NAT
iptables -t nat -L -v -n | head -20
# → pkts bytes target  prot  opt  in  out  source  destination
# → 123456 789012 MASQUERADE  all  --  *  *  0.0.0.0/0  0.0.0.0/0

# Тест пропускной способности (iperf3 через UPF)
# На абонентском устройстве:
iperf3 -c 8.8.8.8 -t 30 -P 8
# → [ ID] Interval       Transfer     Bitrate
# → [  5] 0.00-30.00  sec  35.0 GBytes  10.0 Gbits/sec
```

**Типичные ошибки и решения:**

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| UPF не стартует | `EAL: Not enough hugepages` | Увеличьте количество HugePages; проверьте что приложение использует те же HugePages-монтирования |
| GTP-U туннель не устанавливается | PFCP-сессия не создана | Проверьте связность между SMF и UPF по PFCP (порт 8805); убедитесь что gNB может достучаться до UPF |
| Низкий throughput на сессиях | < 10 Gbps | Проверьте NUMA-локальность; увеличьте количество PMD-потоков; используйте RSS для распределения по ядрам |

**Очистка:**
```bash
# Остановка UPF
sudo killall upf

# Освобождение HugePages
echo 0 > /sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages

# Возврат NIC к стандартному драйверу
sudo dpdk-devbind.py --bind=ice 0000:01:00.0
sudo dpdk-devbind.py --bind=ice 0000:01:00.1
```

---

#### Сценарий 5: HFT — Ультра-низкая задержка

**Цель**: Тюнинг системы для минимизации задержек при получении рыночных данных (Market Data). Критический показатель — «tick-to-trade» задержка: время от получения пакета с биржи до отправки ордера обратно. Целевое значение: < 1 мкс.

**Пререквизиты:**
- Сервер с Intel Xeon (Skylake+ или newer) или AMD EPYC (Zen 3+)
- NIC с аппаратным timestamping (NVIDIA ConnectX-6, Intel E810)
- Запуск приложения с root-привилегиями
- Отключение всех фоновых сервисов

**Шаг 1: Полная изоляция системы**

```bash
# /etc/default/grub — максимальная изоляция
GRUB_CMDLINE_LINUX_DEFAULT="default_hugepagesz=1G hugepagesz=1G hugepages=4 \
  intel_iommu=on iommu=pt \
  isolcpus=2-15 nohz_full=2-15 rcu_nocbs=2-15 \
  intel_pstate=disable \
  processor.max_cstate=0 intel_idle.max_cstate=0 \
  mitigations=off \
  tsc=reliable clocksource=tsc"

# После reboot: проверка изоляции
cat /sys/devices/system/cpu/isolated
# → 2-15
```

**Шаг 2: Тонкая настройка CPU**

```bash
# Отключение C-States и P-States
for cpu in /sys/devices/system/cpu/cpu{2..15}; do
  echo 1 > $cpu/cpuidle/state0/disable 2>/dev/null
  echo 1 > $cpu/cpuidle/state1/disable 2>/dev/null
  echo 1 > $cpu/cpuidle/state2/disable 2>/dev/null
done

# Фиксация частоты CPU (performance governor)
for cpu in /sys/devices/system/cpu/cpu{2..15}; do
  echo performance > $cpu/cpufreq/scaling_governor
done

# Отключение turbo boost
echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo

# Проверка
cat /sys/devices/system/cpu/cpu2/cpufreq/scaling_governor
# → performance
cat /sys/devices/system/cpu/intel_pstate/no_turbo
# → 1
```

**Шаг 3: HugePages и память**

```bash
# Выделение HugePages на NUMA-узле NIC
cat /sys/class/net/enp1s0/device/numa_node
# → 0
echo 4 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages

# Отключение NUMA balancing
echo 0 > /proc/sys/kernel/numa_balancing

# Отключение swap
swapoff -a
echo 0 > /proc/sys/vm/swappiness
```

**Шаг 4: IRQ Affinity и прерывания**

```bash
# Привязка прерываний NIC к изолированным ядрам
# Найти IRQ для NIC
grep enp1s0 /proc/interrupts | awk '{print $1}' | tr -d ':'
# → 48

# Привязать все прерывания NIC к ядру 2 (остальные ядра — чистые)
echo 4 > /proc/irq/48/smp_affinity  # 4 = ядро 2

# Проверка
cat /proc/irq/48/smp_affinity
# → 04
```

**Шаг 5: Запуск DPDK-приложения с оптимизацией**

```bash
# Привязка NIC к vfio-pci
sudo dpdk-devbind.py --bind=vfio-pci 0000:01:00.0

# Запуск приложения с параметрами DPDK
./hft_application \
  -l 2,4,6 \
  --socket-mem 2048,2048 \
  --file-prefix=hft0 \
  --vdev=net_tap0 \
  --log-level=pmd,5 \
  --no-pci

# Или с физическим NIC:
./hft_application \
  -l 2,4,6 \
  --socket-mem 2048,2048 \
  --file-prefix=hft0 \
  --log-level=pmd,5
```

Параметры:
- `-l 2,4,6`: Ядра для lcore 0 (ядро 2), lcore 1 (ядро 4), lcore 2 (ядро 6). Ядро 2 — основной поток, 4 и 6 — worker-потоки.
- `--socket-mem`: HugePages на NUMA-узле 0 (первое значение) и 1 (второе)
- `--file-prefix`: Уникальный префикс для раздельных mempool-ов

**Шаг 6: Валидация задержек**

```bash
# Тест задержки через DPDK testpmd
testpmd -l 2,4 --socket-mem 1024,0 --file-prefix=test \
  -- --forward-mode=mac \
  --stats-period=1 \
  --port-topology=chained

# Результат (в статистике testpmd):
# → TX-packets: 12345678
# → TX-bytes: 18518517000
# → TX Drops: 0

# Измерение задержки через аппаратный timestamping
# В приложении: rte_eth_dev_info_get() → check .tx_offload_capa
# для RTE_ETH_TX_OFFLOAD_TIMESTAMP

# Ожидаемые результаты:
# → Min latency: 0.8 мкс
# → Avg latency: 1.2 мкс
# → Max latency: 3.5 мкс (при редких прерываниях)
# → P99 latency: 2.1 мкс
```

**Типичные ошибки и решения:**

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| Задержки нестабильные (jitter) | P99 > 10 мкс | Проверьте что `isolcpus` работает; отключите `numa_balancing`; убедитесь что фоновые сервисы не используют изолированные ядра |
| NIC не видит DPDK | Приложение не находит порт | Проверьте что NIC привязан к `vfio-pci`; проверьте IOMMU; попробуйте `--vdev=net_tap0` для тестирования |
| Высокий CPU в idle | PMD-потоки загружают 100% ядра | Это нормально для polling mode; убедитесь что прикладная логика работает на отдельных ядрах |

**Очистка:**
```bash
# Восстановление C-States
for cpu in /sys/devices/system/cpu/cpu{2..15}; do
  echo 0 > $cpu/cpuidle/state0/disable 2>/dev/null
  echo 0 > $cpu/cpuidle/state1/disable 2>/dev/null
done

# Восстановление governor
for cpu in /sys/devices/system/cpu/cpu{2..15}; do
  echo powersave > $cpu/cpufreq/scaling_governor
done

# Включение turbo boost
echo 0 > /sys/devices/system/cpu/intel_pstate/no_turbo

# Включение swap
swapon -a
```

---

#### Сценарий 6: NFV — Виртуальный файрвол и балансировщик нагрузки

**Цель**: Реализация NFV-функций (файрвол, балансировщик нагрузки, NAT) поверх DPDK для обработки 100G+ трафика в облачных средах. Замена аппаратных устройств (hardware appliances) программными решениями.

**Пререквизиты:**
- DPDK-совместимое NFV-приложение (FD.io VPP, DPVS, или custom)
- NIC с поддержкой RSS и flow director (Intel E810, NVIDIA ConnectX-7)
- Минимум 8 ядер CPU, 16 ГБ RAM, 4 ГБ HugePages

**Шаг 1: Архитектура решения**

```
                    ┌─────────────────────────┐
                    │      Internet           │
                    └────────────┬────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │   NIC (DPDK PMD)        │
                    │   RSS → ядра 2,4,6,8    │
                    └────────────┬────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
    ┌─────────┴─────────┐ ┌─────┴─────┐ ┌─────────┴─────────┐
    │  L4 LB (ядро 2)  │ │ FW (ядро 4)│ │  NAT (ядро 6)    │
    │  DPVS/lvs        │ │ ACL rules  │ │  DNAT/SNAT       │
    └─────────┬─────────┘ └─────┬─────┘ └─────────┬─────────┘
              │                  │                  │
              └──────────────────┼──────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │   Backend servers        │
                    └─────────────────────────┘
```

**Шаг 2: Настройка DPVS (DPDK-based LVS)**

```bash
# Установка DPVS
git clone https://github.com/iqiyi/dpvs.git
cd dpvs && make -j$(nproc)
sudo make install

# Конфигурация
cat > /etc/dpvs/dpvs.conf << 'EOF'
EOF   # empty config — defaults

# Запуск DPVS
sudo dpvs -c /etc/dpvs/dpvs.conf \
  -l 2,4,6 \
  --socket-mem 4096,4096 \
  --file-prefix=dpvs0

# Добавление VIP (Virtual IP)
sudo dpvs ip-add -addr 10.0.0.100/24 -dev dpdk0

# Добавление реального сервера (real server)
sudo dpvs server-add -addr 192.168.1.10:80 -dev dpdk1 \
  -weight 1 -conn-flush
sudo dpvs server-add -addr 192.168.1.11:80 -dev dpdk1 \
  -weight 1 -conn-flush

# Настройка scheduling method
sudo dpvs sched -m rr  # Round-Robin
```

**Шаг 3: Настройка файрвола (ACL в VPP)**

```bash
# Создание ACL для фильтрации
vppctl acl-plugin add acl \
  match in ip4 proto tcp dst port 80 permit \
  match in ip4 proto tcp dst port 443 permit \
  match in ip4 proto icmp permit \
  match out ip4 deny

# Привязка к интерфейсу
vppctl set interface acl GigabitEthernet0/0/0 input acl 0
vppctl set interface acl GigabitEthernet0/0/0 output acl 0

# Проверка
vppctl acl-plugin show acl 0
```

**Шаг 4: Валидация**

```bash
# Тест балансировки (iperf3)
for i in {1..4}; do
  iperf3 -c 10.0.0.100 -t 5 -P 1 &
done
wait
# Проверка распределения по backend-серверам
dpvs -g
# → WEIGHT  FLOW   ACTIVE  INACT  SERVER
# → 1       12345  123     45     192.168.1.10:80
# → 1       12346  122     46     192.168.1.11:80

# Тест файрвола
curl -v http://10.0.0.100:80
# → 200 OK (разрешено)
curl -v http://10.0.0.100:8443
# → Connection refused (заблокировано)
```

**Типичные ошибки и решения:**

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| DPVS не стартует | `EAL: No PCI probed` | Проверьте что NIC привязан к `vfio-pci`; проверьте HugePages |
| Файрвол блокирует всё | Нет доступа к VIP | Проверьте ACL-правила; убедитесь что `permit` идут перед `deny` |
| Неравномерная нагрузка | Один backend получает больше трафика | Проверьте метод scheduling; используйте `wrr` (Weighted Round-Robin) |

**Очистка:**
```bash
sudo dpvs stop
sudo dpdk-devbind.py --bind=ice 0000:01:00.0
```

---

#### Сценарий 7: Кибербезопасность — IDS/IPS на базе DPDK (Suricata)

**Цель**: Развертывание высокопроизводительной IDS/IPS системы Suricata с DPDK для анализа сетевого трафика на скоростях 100G+ без потерь пакетов. Традиционный Suricata через pcap не способен обработать 100G+ из-за копирования пакетов через ядро.

**Пререквизиты:**
- Suricata 7.0+ (с поддержкой DPDK)
- DPDK 21.11+ установлен
- NIC привязан к vfio-pci
- Правила IDS/IPS ( Emerging Threats или кастомные)

**Шаг 1: Сборка Suricata с поддержкой DPDK**

```bash
# Установка зависимостей
sudo apt install -y build-essential autoconf automake libtool \
  pkg-config libpcre2-dev libyaml-dev libjansson-dev libpcap-dev \
  libnet-dev libcap-ng-dev libnss3-dev libnspr4-dev

# Установка DPDK
git clone https://github.com/DPDK/dpdk.git
cd dpdk && meson build && ninja -C build && sudo ninja -C build install

# Сборка Suricata
git clone https://github.com/OISF/suricata.git
cd suricata
./scripts/bundle.sh
./autogen.sh
./configure --enable-dpdk --enable-nfqueue --prefix=/opt/suricata
make -j$(nproc)
sudo make install
sudo ldconfig
```

**Шаг 2: Конфигурация Suricata для DPDK**

```yaml
# /opt/suricata/etc/suricata.yaml
af-packet:
  - interface: dpdk0
    threads: auto
    cluster-id: 99
    cluster-type: cluster_flow
    defrag: yes
    use-mmap: yes
    ring-size: 2048
    block-size: 32768

# DPDK-specific
dpdk:
  eal-args: >
    -l 2,4,6,8
    --socket-mem 4096,4096
    --file-prefix=suricata0
    --log-level=pmd,5
  ports:
    - pci-addr: "0000:01:00.0"
      name: dpdk0
      threads: 4
```

**Шаг 3: Запуск Suricata**

```bash
# Инициализация правил
/opt/suricata/bin/suricata-update

# Запуск в режиме IDS
/opt/suricata/bin/suricata -c /opt/suricata/etc/suricata.yaml \
  --dpdk -D

# Проверка запуска
/opt/suricata/bin/suricatasc -c "iface-stat dpdk0"
# → dpdk0:
# →   pkts: 12345678
# →   bytes: 18518517000
# →   drops: 0
# →   alerts: 42
```

**Шаг 4: Мониторинг и валидация**

```bash
# Просмотр алертов
tail -f /opt/suricata/log/eve.json | jq 'select(.event_type=="alert")'
# → {
# →   "src_ip": "10.0.0.5",
# →   "src_port": 45678,
# →   "dest_ip": "10.0.0.100",
# →   "dest_port": 22,
# →   "alert": {
# →     "signature_id": 2001219,
# →     "signature": "ET SCAN Potential SSH Scan",
# →     "category": "Attempted Information Leak"
# →   }
# → }

# Проверка статистики DPDK
/opt/suricata/bin/suricatasc -c "iface-stat dpdk0"
# → pkts: 12345678
# → bytes: 18518517000
# → drops: 0          <-- 0 drops означает что Suricata справляется с нагрузкой

# Тест производительности
# На клиенте: hping3 -S -p 22 --flood 10.0.0.100
# На Suricata: проверить что drops остаётся 0
```

**Типичные ошибки и решения:**

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| Suricata не стартует с DPDK | `DPDK EAL init failed` | Проверьте HugePages; убедитесь что NIC привязан к `vfio-pci` |
| Drops > 0 при высокой нагрузке | Пакеты теряются | Увеличьте количество потоков DPDK; добавьте ядра CPU; увеличьте ring-size |
| Мало алертов | `alerts: 0` при подозрительном трафике | Обновите правила (`suricata-update`); проверьте что DPDK PMD получает пакеты |

**Очистка:**
```bash
sudo killall suricata
sudo dpdk-devbind.py --bind=ice 0000:01:00.0
```

---

### Диагностика и общие инструменты

#### Проверка DPDK EAL

```bash
# Просмотр доступных портов
dpdk-devbind.py --status
# → Network devices using DPDK-compatible driver
# → ============================================
# → 0000:01:00.0 'Device 1592' if= enp1s0 drv=vfio-pci unused=ice

# Просмотр HugePages
grep -i huge /proc/meminfo
# → HugePages_Total:       8
# → HugePages_Free:        8
# → HugePages_Rsvd:        0
# → Hugepagesize:       1048576 kB

# Просмотр NUMA-топологии
lscpu | grep -i numa
# → NUMA node(s):        2
# → NUMA node0 CPU(s):   0-31
# → NUMA node1 CPU(s):   32-63
```

#### Мониторинг производительности

```bash
# Просмотр статистики NIC
ethtool -S enp1s0
# → rx_bytes: 18518517000
# → tx_bytes: 12345678000
# → rx_drops: 0
# → tx_drops: 0

# Просмотр DPDK-статистики (внутри приложения)
# Используйте rte_eth_stats_get() в коде приложения

# Просмотр CPU
mpstat -P ALL 1
# → CPU    %usr   %nice  %sys   %iowait  %irq   %soft  %idle
# → 2      100.0  0.0    0.0    0.0      0.0    0.0    0.0  <-- PMD-поток
# → 4      100.0  0.0    0.0    0.0      0.0    0.0    0.0  <-- PMD-поток
```

#### Типичные ошибки DPDK-приложений

| Ошибка DPDK | Причина | Решение |
| :--- | :--- | :--- |
| `EAL: No free hugepages` | Недостаточно HugePages | `echo N > /sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages` |
| `EAL: Cannot open /dev/vfio/X` | NIC не привязана к vfio-pci | `dpdk-devbind.py --bind=vfio-pci <pci_addr>` |
| `EAL: IOVA mapping failed` | IOMMU не включён | Параметр ядра `intel_iommu=on iommu=pt` |
| `EAL: Cannot set up memory` | NUMA-несоответствие | `--socket-mem` должен покрывать NUMA-узел NIC |
| `PMD: Failed to start port` | NIC занята другим процессом | Остановите другие DPDK-приложения или OVS |

---

### Дополнительная информация

- **[Обзор DPDK](dpdk_overview.md)** — архитектура обхода ядра и работа PMD.
- **[RSS в DPDK](dpdk_rss.md)** — аппаратное распределение трафика по ядрам CPU.
- **[rte_flow API](dpdk_rte_flow.md)** — программирование фильтрации пакетов в железе NIC.
- **[Тестирование и бенчмаркинг](dpdk_testing.md)** — RFC 2544, трафик-генераторы, метрики.
- **[DPDK Bonding](dpdk_bonding.md)** — LACP, failover, балансировка.
- **[QoS / Metering](dpdk_qos.md)** — rte_mtr, rte_sched, DCB/ETS.
- **[Multi-process DPDK](dpdk_multiprocess.md)** — primary/secondary модель.
- **[Отладка DPDK](dpdk_debugging.md)** — gdb, core dump, logging, valgrind.
- **[Cryptodev / IPsec](dpdk_cryptodev.md)** — inline vs lookaside crypto, QAT.
- **[Hotplug](dpdk_hotplug.md)** — динамическое добавление/удаление NIC.
- **[io_uring / AF_XDP vs DPDK](dpdk_io_uring_vs_afxdp.md)** — сравнение альтернатив.
- **[Service Function Chaining](dpdk_sfc.md)** — NSH, VxLAN-GPE, pipeline.
- **[KNI / Tap / vhost-user](dpdk_kni.md)** — взаимодействие с kernel network stack.
- **[Безопасность DPDK](dpdk_security.md)** — trust, spoof, MACsec.
- **[Обзор SR-IOV](sriov.md)** — аппаратная виртуализация PCI-устройств.
- **[Настройка SR-IOV](sriov_setup.md)** — подготовка BIOS, IOMMU и создание VF.
- **[Технические детали DPDK](dpdk_technical.md)** — глубокий разбор HugePages, TLB и выравнивания памяти.
- **[Open vSwitch (OVS)](../../ServicesAndTools/open_vswitch.md)** — детальное руководство по настройке программных коммутаторов.
