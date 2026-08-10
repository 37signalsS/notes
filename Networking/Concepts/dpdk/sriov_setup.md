# Настройка и использование SR-IOV

### Определения

- **IOMMU (Input-Output Memory Management Unit)**: Аппаратный блок, транслирующий адреса ввода-вывода устройств в физические адреса памяти. Необходим для изоляции и безопасного проброса PCI-устройств (Virtual Functions) в виртуальные машины или контейнеры.
- **vfio-pci**: Современный драйвер ядра Linux для прямого доступа к PCI-устройствам из пространства пользователя. В отличие от устаревшего `uio_pci_generic`, поддерживает IOMMU и обеспечивает надежную изоляцию.
- **devbind**: Вспомогательная утилита DPDK (`dpdk-devbind.py`), используемая для управления привязкой драйверов к PCI-устройствам.
- **Virtual Function (VF)**: Облегченное PCI-устройство, созданное на базе физической функции (PF), предназначенное для прямой передачи данных.

---

### Подготовка системы

Перед активацией SR-IOV необходимо выполнить предварительную настройку на уровне BIOS и ядра ОС.

#### 1. BIOS/UEFI
Включите поддержку виртуализации ввода-вывода в настройках процессора:
- **Intel**: `VT-d` (Virtualization Technology for Directed I/O).
- **AMD**: `IOMMU` или `AMD-Vi`.
- Убедитесь, что включена поддержка **SR-IOV Global Enable** (если есть такой пункт).

#### 2. Параметры ядра Linux
Отредактируйте `/etc/default/grub`, добавив поддержку IOMMU:
```bash
# Для Intel
GRUB_CMDLINE_LINUX_DEFAULT="... intel_iommu=on iommu=pt"
# Для AMD
GRUB_CMDLINE_LINUX_DEFAULT="... amd_iommu=on iommu=pt"
```
После изменения выполните `update-grub` и перезагрузите хост.

#### 3. Проверка активации
Убедитесь, что IOMMU успешно инициализирован:
```bash
dmesg | grep -e DMAR -e IOMMU
# → "DMAR: IOMMU enabled"
```

---

### Практическая настройка

#### Шаг 1: Создание виртуальных функций
Количество доступных VF зависит от модели сетевой карты (NIC).

```bash
# Определяем имя физического интерфейса
ip link show

# Создаем 8 виртуальных функций на интерфейсе enp1s0f0
echo 8 | sudo tee /sys/class/net/enp1s0f0/device/sriov_numvfs
```

#### Шаг 2: Обеспечение персистентности
В 2026 году для сохранения настроек после перезагрузки рекомендуется использовать стандартные средства сетевого управления.

**Вариант А: Netplan (Ubuntu/Debian)**
```yaml
# /etc/netplan/01-netcfg.yaml
network:
  version: 2
  ethernets:
    enp1s0f0:
      virtual-functions:
        - count: 8
```

**Вариант Б: systemd-networkd**
```ini
# /etc/systemd/network/10-sriov.link
[Match]
OriginalName=enp1s0f0

[Link]
VirtualFunctionCount=8
```

#### Шаг 3: Настройка параметров безопасности и QoS
Настройка выполняется с хоста через `ip link`.

- **Trust Mode**: Разрешает гостевой ОС изменять параметры VF (например, включать Promiscuous mode), что необходимо для некоторых NFV-решений.
  ```bash
  sudo ip link set enp1s0f0 vf 0 trust on
  ```
- **Spoof Checking**: Защита от подмены MAC-адресов.
  ```bash
  sudo ip link set enp1s0f0 vf 0 spoofchk on
  ```
- **Ограничение полосы (QoS)**:
  ```bash
  sudo ip link set enp1s0f0 vf 0 rate 10000 # Ограничение до 10 Гбит/с
  ```

#### Шаг 4: Привязка VF к драйверу vfio-pci
Для использования VF в DPDK или проброса в KVM необходимо освободить устройство от стандартного драйвера ядра.

```bash
# Загрузка модуля vfio-pci
sudo modprobe vfio-pci

# Поиск PCI-адреса созданной VF
lspci | grep -i "Virtual Function"
# → 0000:01:00.2 Ethernet controller: ...

# Привязка через скрипт DPDK
sudo dpdk-devbind.py --bind=vfio-pci 0000:01:00.2
```

---

### Нюансы оборудования

- **NVIDIA/Mellanox (ConnectX)**: Требуют предварительной настройки прошивки через `mstconfig` для включения SR-IOV:
  ```bash
  mstconfig -d <pci_addr> set SRIOV_EN=1 NUM_OF_VFS=16
  ```
- **Intel (i40e/ice)**: Поддерживают расширенные функции управления VF через утилиту `iproute2`, но требуют актуальных версий драйверов и прошивок для работы с PCIe Gen5/Gen6.

---

### Диагностика и отладка

- **Проверка IOMMU групп**: Все устройства в одной группе должны пробрасываться вместе.
  ```bash
  find /sys/kernel/iommu_groups/ -type l
  ```
- **Логи ядра**: Ошибки при создании VF или привязке драйвера.
  ```bash
  journalctl -k | grep -iE "sriov|vfio|iommu"
  ```
- **Статус драйверов**:
  ```bash
  dpdk-devbind.py --status
  ```

---

### Дополнительная информация

- **[Обзор SR-IOV](sriov.md)** — теоретические основы и архитектура аппаратного разделения.
- **[Практические сценарии DPDK и SR-IOV](scenarios.md)** — примеры интеграции с Kubernetes и AI Fabric.
- **[Обзор DPDK](dpdk_overview.md)** — принципы работы Userspace сетевого стека.
- **[Технические детали DPDK](dpdk_technical.md)** — оптимизация производительности на уровне памяти и процессора.
