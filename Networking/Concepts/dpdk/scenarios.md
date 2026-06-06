# Практические сценарии DPDK и SR-IOV

Этот документ содержит конкретные примеры конфигураций для интеграции DPDK и SR-IOV с Kubernetes, Open vSwitch и VPP. Концептуальные основы: [Обзор DPDK](dpdk_overview.md), [Обзор SR-IOV](sriov.md), [Технические детали DPDK](dpdk_technical.md).

## Определения

- **NFV (Network Function Virtualization)**: Запуск сетевых сервисов (маршрутизаторы, файрволы, балансировщики) на стандартном серверном оборудовании.
- **CNF (Cloud-Native Network Function)**: Контейнеризованная сетевая функция, требующая высокой производительности.
- **HFT (High-Frequency Trading)**: Высокочастотная торговля, критичная к минимальной задержке.

## Основные концепции

DPDK и SR-IOV совместно обеспечивают производительность, близкую к «bare metal», в виртуализированных и контейнеризованных средах. Архитектура и механизм работы описаны в [Обзор DPDK](dpdk_overview.md) и [Обзор SR-IOV](sriov.md).

**Типичные области применения:**

- **NFV/CNF**: Виртуализация сетевых функций в Kubernetes и на стандартном оборудовании.
- **Виртуальные коммутаторы**: Ускорение датапаса OVS или VPP через bypass ядра.
- **Мобильные сети (4G/5G)**: Обработка трафика Packet Core.
- **Кибербезопасность**: IDS/IPS для анализа на скоростях 40/100 Гбит/с.
- **HFT**: Системы с детерминированной минимальной задержкой.

Подробное сравнение технологий — в [SR-IOV: Сравнение с DPDK](sriov.md#сравнение-dpdk-и-sr-iov).

## Практические сценарии

**Сценарий 1: Kubernetes — прямой доступ к сети для подов с SR-IOV**

Для предоставления поду прямого доступа к сетевой карте используется SR-IOV Device Plugin.

1. **На хосте**: Настраивается SR-IOV, создаются виртуальные функции (VF). См. [Настройка SR-IOV](sriov_setup.md).
2. **В кластере**: Устанавливается SR-IOV Network Device Plugin, обнаруживающий VF и сообщающий о них Kubernetes.
3. **В поде**: Под запрашивает VF как ресурс.

Пример манифеста пода:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: high-performance-pod
  annotations:
    k8s.v1.cni.cncf.io/networks: sriov-net-a
spec:
  containers:
  - name: my-app
    image: my-nfv-app:latest
    resources:
      limits:
        intel.com/sriov: '1'
```

Внутри пода `my-nfv-app` работает DPDK-приложение, использующее проброшенный VF для сверхбыстрой обработки пакетов.

**Сценарий 2: Open vSwitch (OVS) с DPDK**

Замена стандартного kernel-based датапаса в OVS на DPDK-версию ускоряет обработку трафика.

```bash
# 1. Инициализировать OVS с DPDK и выделить Hugepages
ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-init=true
ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-socket-mem="1024,1024"

# 2. Создать бридж
ovs-vsctl add-br br-dpdk -- set bridge br-dpdk datapath_type=netdev

# 3. Добавить физический порт (NIC) как DPDK-порт
# PCI-адрес 0000:04:00.0 предварительно отвязан от драйвера ядра
ovs-vsctl add-port br-dpdk dpdk0 -- set Interface dpdk0 type=dpdk \
    options:dpdk-devargs=0000:04:00.0

# 4. Проверить конфигурацию
ovs-vsctl show
```

**Сценарий 3: VPP (Vector Packet Processing)**

VPP — высокопроизводительный программный маршрутизатор от FD.io, построенный на базе DPDK.

Пример конфигурации VPP (`/etc/vpp/startup.conf`):

```
dpdk {
  dev 0000:04:00.0 {
    name eth0
  }
  num-mbufs 131072
}
```

Работа с VPP через CLI:

```bash
sudo systemctl start vpp
vppctl
vppctl> show interfaces
vppctl> show hardware
```

### Дополнительная информация

Пошаговые инструкции по активации SR-IOV см. в [Настройка SR-IOV](sriov_setup.md). Конфигурация OVS-DPDK описана в [официальной документации OVS](https://docs.openvswitch.org/en/latest/intro/install/dpdk/) и в обзоре **[Open vSwitch](../../ServicesAndTools/open_vswitch.md)**. Настройка VPP документирована на [fd.io](https://fd.io/docs/vpp/). Общие сведения о DPDK и его архитектуре — в [Обзор DPDK](dpdk_overview.md), технические детали — в [Технические детали DPDK](dpdk_technical.md).
