# Практические сценарии использования DPDK и SR-IOV

Этот документ содержит конкретные примеры конфигураций для интеграции DPDK и SR-IOV с популярными платформами, такими как Kubernetes, Open vSwitch и VPP.

---

### Основные концепции: Области применения

DPDK и SR-IOV являются ключевыми технологиями для создания быстрых, программно-определяемых сетевых решений. Основные области их применения включают:

-   **NFV (Network Function Virtualization)**: Запуск сетевых сервисов (маршрутизаторов, файрволов, балансировщиков) на стандартном серверном оборудовании.
-   **Cloud-Native Network Functions (CNFs)**: Контейнеризованные сетевые функции, требующие высокой производительности.
-   **Виртуальные коммутаторы**: Ускорение обработки трафика в OVS или VPP.
-   **Мобильные сети (4G/5G)**: Обработка трафика в компонентах пакетного ядра (Packet Core).
-   **Системы кибербезопасности**: Высокопроизводительные IDS/IPS, способные анализировать трафик на скоростях 40/100 Гбит/с.
-   **Финансовые технологии (HFT)**: Системы для высокочастотной торговли, где важна минимальная задержка.

---

### Практические сценарии

#### Сценарий 1: Kubernetes — прямой доступ к сети для подов с SR-IOV

Для предоставления поду прямого доступа к сетевой карте используется SR-IOV Device Plugin.

1.  **На хосте**: Настраивается SR-IOV и создаются виртуальные функции (VF). (См. [Настройка SR-IOV](sriov_setup.md)).
2.  **В кластере**: Устанавливается SR-IOV Network Device Plugin, который обнаруживает VF на узлах и сообщает о них Kubernetes.
3.  **В поде**: Под запрашивает VF как ресурс.

**Пример манифеста пода:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: high-performance-pod
  annotations:
    # Запрос сети, предоставляемой плагином Multus CNI
    k8s.v1.cni.cncf.io/networks: sriov-net-a
spec:
  containers:
  - name: my-app
    image: my-nfv-app:latest
    resources:
      limits:
        # Запрос одного VF из пула ресурсов 'intel.com/sriov'
        intel.com/sriov: '1'
```
Внутри пода `my-nfv-app` может работать DPDK-приложение, которое будет использовать проброшенный VF для сверхбыстрой обработки пакетов.

#### Сценарий 2: Open vSwitch (OVS) с DPDK

Замена стандартного kernel-based датапаса в OVS на DPDK-версию значительно ускоряет обработку трафика.

```bash
# 1. Установить OVS с поддержкой DPDK и выделить Hugepages
ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-init=true
ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-socket-mem="1024,1024"

# 2. Создать бридж
ovs-vsctl add-br br-dpdk -- set bridge br-dpdk datapath_type=netdev

# 3. Добавить физический порт (NIC) в OVS как DPDK-порт
# PCI-адрес 0000:04:00.0 должен быть предварительно отвязан от драйвера ядра
ovs-vsctl add-port br-dpdk dpdk0 -- set Interface dpdk0 type=dpdk \
    options:dpdk-devargs=0000:04:00.0

# 4. Проверить конфигурацию
ovs-vsctl show
```

#### Сценарий 3: VPP (Vector Packet Processing)

VPP — это высокопроизводительный программный маршрутизатор от FD.io, который изначально построен на базе DPDK.

**Пример конфигурации VPP (`/etc/vpp/startup.conf`):**
```
# Секция для DPDK
dpdk {
  # Указать PCI-адрес устройства для захвата
  dev 0000:04:00.0 {
    name eth0
  }
  
  # Количество mbufs (буферов пакетов)
  num-mbufs 131072
}
```

**Работа с VPP через CLI:**
```bash
# Запустить VPP
sudo systemctl start vpp

# Подключиться к консоли VPP
vppctl

# Показать интерфейсы (захваченный DPDK-интерфейс будет виден здесь)
vppctl> show interfaces

# Показать информацию об оборудовании
vppctl> show hardware
```

---

### Дополнительная информация

-   Концептуальные основы: **[Обзор DPDK](dpdk_overview.md)** и **[Обзор SR-IOV](sriov.md)**.
-   [Официальная документация DPDK](https://doc.dpdk.org/guides/)
-   [Документация OVS-DPDK](https://docs.openvswitch.org/en/latest/intro/install/dpdk/)
-   [Документация VPP](https://fd.io/docs/vpp/)
