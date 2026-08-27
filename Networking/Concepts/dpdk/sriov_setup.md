# Настройка и использование SR-IOV

### Определения

- **SR-IOV (Single Root I/O Virtualization)**: Спецификация PCI SIG, позволяющая одному физическому устройству (NIC, GPU) представить себя как несколько независимых виртуальных PCI-устройств. Каждое виртуальное устройство имеет собственный адрес в пространстве PCI (BDF), уникальные очереди TX/RX и DMA-каналы, что обеспечивает аппаратную изоляцию без участия ядра ОС.
- **PF (Physical Function)**: Полнофункциональное PCI-устройство, управляемое драйвером ядра (ice, mlx5_core, i40e). PF отвечает за создание и управление VF, настройку параметров которых выполняет хост-ОС через sysfs или `ip link`.
- **VF (Virtual Function)**: Облегчённое PCI-устройство, созданное на базе PF, предназначенное исключительно для передачи данных. VF не может управлять PF или создавать другие VF. VF может быть проброшен в ВМ или контейнер через vfio-pci для прямого DMA-доступа к сетевой карте.
- **IOMMU (Input-Output Memory Management Unit)**: Аппаратный блок (Intel VT-d, AMD-Vi), транслирующий адреса ввода-вывода устройств (IOVA) в физические адреса памяти (HPA). Необходим для изоляции VF и предотвращения несанкционированного DMA-доступа между VM. Также выполняет защиту памяти и translation fault handling.
- **vfio-pci**: Современный драйвер ядра Linux для прямого доступа к PCI-устройствам из пространства пользователя. В отличие от устаревшего `uio_pci_generic`, поддерживает IOMMU и обеспечивает надёжную изоляцию VF. Является стандартом для DPDK и KVM-passthrough.
- **devbind**: Вспомогательная утилита DPDK (`dpdk-devbind.py`), используемая для управления привязкой драйверов к PCI-устройствам. Позволяет переключать NIC между стандартным драйвером ядра (ice, mlx5_core) и vfio-pci.
- **NUMA (Non-Uniform Memory Access)**: Архитектура многосокетных серверов, где каждый физический CPU-сокет образует отдельный NUMA-узел со своей локальной памятью и линиями PCI-шины. VF, подключённый к PCIe-шине NUMA-узла 0, обрабатывается быстрее при запуске на ядрах того же NUMA-узла.

---

### Предварительные требования

#### Аппаратное обеспечение

| Компонент | Требование | Минимум для SR-IOV |
| :--- | :--- | :--- |
| CPU | Поддержка VT-d (Intel) или AMD-Vi (AMD) | Skylake+ (Intel), Zen 3+ (AMD) |
| Chipset | Поддержка PCIe ACS (Access Control Services) | Q470+/C621+ (Intel), X570+/WRX80+ (AMD) |
| NIC | Поддержка SR-IOV спецификации | Intel X710/E810, NVIDIA ConnectX-5+, Broadcom BCM57800+ |
| RAM | Для HugePages (DPDK) | Минимум 2 ГБ HugePages на VF |
| BIOS | Поддержка VT-d/IOMMU и SR-IOV | Обязательно |

#### Программное обеспечение

- Linux kernel 5.15+ (рекомендуется 6.1+ LTS)
- `iproute2` 5.10+ (управление VF через `ip link`)
- `ethtool` 5.15+ (проверка состояния NIC)
- DPDK 21.11+ (если используется vfio-pci для DPDK-приложений)
- `kmod` 28+ (управление модулями ядра)

#### BIOS/UEFI

Включите поддержку виртуализации ввода-вывода в настройках BIOS/UEFI:

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| **Intel VT-d** | Enabled | Виртуализация ввода-вывода для Intel |
| **AMD IOMMU** / **AMD-Vi** | Enabled | Виртуализация ввода-вывода для AMD |
| **SR-IOV Global Enable** | Enabled | Аппаратная поддержка создания VF (если есть) |
| **PCIe ACS** | Enabled | Access Control Services для изоляции IOMMU-групп |
| **Resizable BAR** | Enabled (опционально) | Увеличение BAR для VF с большими объёмами памяти |

---

### Пошаговая настройка

#### Шаг 1: Параметры ядра Linux

Отредактируйте `/etc/default/grub`, добавив параметры IOMMU и HugePages:

```bash
# /etc/default/grub — полный набор для SR-IOV + DPDK
GRUB_CMDLINE_LINUX_DEFAULT="default_hugepagesz=1G hugepagesz=1G hugepages=8 \
  intel_iommu=on iommu=pt"
# Для AMD:
# GRUB_CMDLINE_LINUX_DEFAULT="default_hugepagesz=1G hugepagesz=1G hugepages=8 \
#   amd_iommu=on iommu=pt"
```

Параметры:
- `intel_iommu=on` / `amd_iommu=on`: Включает IOMMU (обязательно для SR-IOV)
- `iommu=pt`: Pass-Through mode — IOMMU не транслирует адреса для хостовых устройств, только для VF (снижает накладные расходы)
- `default_hugepagesz=1G hugepagesz=1G hugepages=8`: Выделяет 8 ГБ HugePages (1 ГБ страницы) для DPDK-приложений

Применение:
```bash
sudo update-grub
sudo reboot
```

#### Шаг 2: Проверка активации IOMMU

После перезагрузки убедитесь, что IOMMU успешно инициализирован:

```bash
dmesg | grep -e DMAR -e IOMMU
# → "DMAR: IOMMU enabled"
# → "DMAR: Registering all firmware regions"
```

Если вывод пуст — IOMMU не включён. Проверьте:
1. BIOS/UEFI: VT-d / AMD-Vi включены
2. Параметры ядра: `intel_iommu=on` добавлены в GRUB
3. Совместимость чипсета (некоторые потребительские чипсеты Intel не поддерживают VT-d)

#### Шаг 3: Проверка поддержки SR-IOV в ядре

```bash
# Загрузка модуля vfio-pci
sudo modprobe vfio-pci

# Проверка загруженных модулей
lsmod | grep vfio
# → vfio_pci vfio vfio_iommu_type1
# Три модуля обязательны: vfio (базовый), vfio_pci (PCI-драйвер), vfio_iommu_type1 (IOMMU-интеграция)
```

#### Шаг 4: Определение максимального количества VF

Количество VF, которое может создать NIC, зависит от модели и объёма ресурсов PCIe (BAR-пространство, TCAM):

```bash
# Определяем имя физического интерфейса
ip link show
# → 1: enp1s0f0: <BROADCAST,MULTICAST,SLAVE,UP> ...
# → 3: enp1s0f1: <BROADCAST,MULTICAST,SLAVE,UP> ...

# Проверка максимального количества VF
cat /sys/class/net/enp1s0f0/device/sriov_totalvfs
# → 64 (максимум поддерживаемых VF данным NIC)
```

Типичные ограничения по моделям NIC:
- **Intel X710 (i40e)**: до 128 VF
- **Intel E810 (ice)**: до 256 VF
- **NVIDIA ConnectX-6 Dx**: до 1024 VF
- **NVIDIA ConnectX-7**: до 1024 VF

> **Важно**: Реальное количество VF может быть меньше из-за нехватки PCIe BAR-ресурсов. Если `sriov_numvfs` возвращает ошибку, проверьте `dmesg` — возможно, нужно уменьшить количество VF или включить `pci=realloc`.

#### Шаг 5: Создание виртуальных функций

```bash
# Создание 8 виртуальных функций на интерфейсе enp1s0f0
echo 8 | sudo tee /sys/class/net/enp1s0f0/device/sriov_numvfs
# → 8

# Проверка
cat /sys/class/net/enp1s0f0/device/sriov_numvfs
# → 8

# Просмотр созданного VF
ip link show enp1s0f0
# → 1: enp1s0f0: <BROADCAST,MULTICAST,SLAVE,UP> ...
# →     vf 0 MAC 00:00:00:00:00:00, spoofchk on, trust off, rate unlimited
# →     vf 1 MAC 00:00:00:00:00:00, spoofchk on, trust off, rate unlimited
# →     ...

# Просмотр PCI-адресов VF
lspci | grep -i "Virtual Function"
# → 0000:01:00.2 Ethernet controller: Intel Corporation ...
# → 0000:01:00.3 Ethernet controller: Intel Corporation ...
# → 0000:01:00.4 Ethernet controller: Intel Corporation ...
# → ...
```

Проверка создаётся ли VF через `ip link`:
```bash
# Все VF PF-интерфейса
ls /sys/class/net/enp1s0f0/device/virtfn*
# → /sys/class/net/enp1s0f0/device/virtfn0
# → /sys/class/net/enp1s0f0/device/virtfn1
# → ...
```

#### Шаг 6: Обеспечение персистентности

В 2026 году для сохранения настроек VF после перезагрузки рекомендуется использовать стандартные средства сетевого управления.

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

```bash
sudo netplan apply
```

**Вариант Б: systemd-networkd**

```ini
# /etc/systemd/network/10-sriov.link
[Match]
OriginalName=enp1s0f0

[Link]
VirtualFunctionCount=8
```

```bash
sudo systemctl restart systemd-networkd
```

**Вариант В: udev rule (универсальный)**

```bash
# /etc/udev/rules.d/99-sriov.rules
ACTION=="add", SUBSYSTEM=="net", NAME=="enp1s0f0", \
  RUN+="/bin/sh -c 'echo 8 > /sys/class/net/enp1s0f0/device/sriov_numvfs'"
```

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

#### Шаг 7: Настройка параметров VF (QoS и безопасность)

После создания VF настройте их параметры через `ip link`:

- **Назначение MAC-адреса и VLAN**:
  ```bash
  sudo ip link set enp1s0f0 vf 0 mac 52:54:00:00:01:01 vlan 100
  ```

- **Trust Mode**: Разрешает гостевой ОС изменять параметры VF (например, включать Promiscuous mode), что необходимо для NFV-решений и OVS-DPDK:
  ```bash
  sudo ip link set enp1s0f0 vf 0 trust on
  ```

- **Spoof Checking**: Защита от подмены MAC-адресов VF (включена по умолчанию):
  ```bash
  sudo ip link set enp1s0f0 vf 0 spoofchk on
  ```

- **Ограничение полосы (QoS)**: Ограничение пропускной способности VF (в Мбит/с):
  ```bash
  sudo ip link set enp1s0f0 vf 0 rate 10000  # 10 Гбит/с
  sudo ip link set enp1s0f0 vf 0 max_tx_rate 5000  # 5 Гбит/с (альтернативный синтаксис)
  ```

- **Управление VLAN-тегами**: Разрешение VF управлять собственными VLAN:
  ```bash
  sudo ip link set enp1s0f0 vf 0 vlan 100 spoofchk on
  ```

- **Просмотр текущих параметров всех VF**:
  ```bash
  ip -d link show enp1s0f0
  # → vf 0 MAC 52:54:00:00:01:01, vlan 100, spoofchk on, trust on, rate 10000
  # → vf 1 MAC 00:00:00:00:00:00, vlan 0, spoofchk on, trust off, rate unlimited
  ```

#### Шаг 8: Привязка VF к драйверу vfio-pci

Для использования VF в DPDK-приложениях или проброса в KVM/QEMU необходимо освободить VF от стандартного драйвера ядра и привязать к vfio-pci:

```bash
# Загрузка модуля vfio-pci (если ещё не загружен)
sudo modprobe vfio-pci

# Поиск PCI-адреса созданной VF
lspci | grep -i "Virtual Function"
# → 0000:01:00.2 Ethernet controller: Intel Corporation ...

# Отвязка от стандартного драйвера ядра
sudo dpdk-devbind.py --unbind 0000:01:00.2

# Привязка к vfio-pci
sudo dpdk-devbind.py --bind=vfio-pci 0000:01:00.2

# Проверка результата
sudo dpdk-devbind.py --status
# → Network devices using DPDK-compatible driver
# → ============================================
# → 0000:01:00.2 'Device 1592' if=  drv=vfio-pci unused=i40e
```

**Или без использования DPDK-утилит (через sysfs)**:

```bash
# Отвязка от текущего драйвера
echo "0000:01:00.2" | sudo tee /sys/bus/pci/devices/0000:01:00.2/driver/unbind

# Привязка к vfio-pci
echo "vfio-pci" | sudo tee /sys/bus/pci/devices/0000:01:00.2/driver_override
echo "0000:01:00.2" | sudo tee /sys/bus/pci/drivers/vfio-pci/bind
```

**Персистентная привязка через udev rule**:

```bash
# /etc/udev/rules.d/99-vfio-pci.rules
ACTION=="add", SUBSYSTEM=="pci", ATTR{address}=="0000:01:00.2", \
  RUN+="/bin/sh -c 'echo vfio-pci > /sys/bus/pci/devices/0000:01:00.2/driver_override'"
```

#### Шаг 9: Проверка и валидация

```bash
# 1. Проверка что VF созданы
cat /sys/class/net/enp1s0f0/device/sriov_numvfs
# → 8

# 2. Проверка PCI-устройств
lspci | grep -i "Virtual Function"
# → 0000:01:00.2 Ethernet controller: ...

# 3. Проверка привязки драйвера
sudo dpdk-devbind.py --status
# → 0000:01:00.2 'Device 1592' drv=vfio-pci

# 4. Проверка IOMMU-группы VF
find /sys/kernel/iommu_groups/ -type l | grep "01:00.2"
# → /sys/kernel/iommu_groups/5/devices/0000:01:00.2

# 5. Проверка загруженных модулей
lsmod | grep vfio
# → vfio_pci vfio vfio_iommu_type1

# 6. Проверка логов ядра на ошибки
dmesg | grep -iE "sriov|vfio|iommu" | tail -5
```

---

### Спецификации оборудования

#### NVIDIA/Mellanox (ConnectX-5/6/7)

NVIDIA-карты требуют предварительной настройки прошивки через `mstconfig` для включения SR-IOV:

```bash
# Установка MST (Mellanox Software Tools)
sudo apt install mstflint

# Включение SR-IOV в прошивке NIC
sudo mstconfig -d 0000:01:00.0 set SRIOV_EN=1 NUM_OF_VFS=16

# Проверка текущих настроек
sudo mstconfig -d 0000:01:00.0 query | grep -i sr
# → SRIOV_EN 1
# → NUM_OF_VFS 16
```

**Особенности NVIDIA:**
- Поддерживает до 1024 VF (ConnectX-6 Dx, ConnectX-7)
- Требует `mlx5_core` драйвер (version 24.01+ для полноценной поддержки)
- Поддерживает GPUDirect RDMA через VF (для AI-сценариев)
- VF использует аппаратный RSS для распределения трафика

#### Intel (i40e/ice)

Intel-карты поддерживают расширенные функции управления VF через `iproute2`:

```bash
# Проверка версии драйвера
ethtool -i enp1s0f0
# → driver: ice
# → version: 1.12.6

# Проверка capabilities
ethtool -k enp1s0f0 | grep -i sriov
# → sr-iov: on
```

**Особенности Intel:**
- Поддерживает до 256 VF (E810)
- Требует актуальных версий драйверов ice (5.x+) для PCIe Gen5/Gen6
- VF поддерживают ADQ (Application Device Queues) — аппаратное распределение трафика по приложениям
- Поддерживает VF LGPL (Low Latency Guest Loopback) для HFT-сценариев

#### Broadcom (BCM57800/NetXtreme-E)

```bash
# Включение SR-IOV через инструмент厂商
sudo bnxtnvm -d 0000:01:00.0 set-sriov 8

# Или через sysfs (после загрузки драйвера bnx2x)
echo 8 | sudo tee /sys/class/net/enp1s0f0/device/sriov_numvfs
```

**Особенности Broadcom:**
- Поддерживает до 64 VF (BCM57800)
- Драйвер `bnx2x` (старый) или `bnxt_en` (новый) — для SR-IOV рекомендуется `bnxt_en`
- VF поддерживаютrove VLAN offloading (аппаратная инкапсуляция VLAN)

---

### Интеграция с KVM/QEMU

SR-IOV VF может быть напрямую передан виртуальной машине KVM для достижения производительности уровня bare-metal.

#### Проброс VF в ВМ через virsh

```bash
# Проброс VF на лету (hot-plug)
sudo virsh attach-interface <vm_name> hostdev 0000:01:00.2 \
  --mac 52:54:00:00:01:01 --managed --live --config

# Параметры:
# --managed  — автоматическое управление生命周期 (создание/удаление VF)
# --live     — применить к запущенной ВМ
# --config   — сохранить для автозапуска
```

#### Конфигурация через XML

```xml
<!-- /etc/libvirt/qemu/<vm_name>.xml -->
<hostdev mode='subsystem' type='pci' managed='yes'>
  <source>
    <address domain='0x0000' bus='0x01' slot='0x00' function='0x2'/>
  </source>
  <address type='pci' domain='0x0000' bus='0x00' slot='0x05' function='0x0'/>
</hostdev>
```

**Важно**: Убедитесь что IOMMU-группа VF не содержит других устройств, которые вы не хотите пробрасывать в эту ВМ:

```bash
# Проверка IOMMU-группы VF
find /sys/kernel/iommu_groups/ -type l | grep "01:00.2"
# → /sys/kernel/iommu_groups/5/devices/0000:01:00.2

# Проверка всех устройств в группе
for d in /sys/kernel/iommu_groups/5/devices/*; do
  echo $(basename $d)
done
# → 0000:01:00.2 (VF)
# → Если в группе есть другие устройства — их тоже нужно пробросить
```

#### Удаление VF из ВМ

```bash
# Отключение VF от ВМ
sudo virsh detach-interface <vm_name> hostdev 0000:01:00.2
```

#### Настройка net_failover (live-migration)

Для поддержки live-migration VF/VFIO с SR-IOV используется механизм `net_failover`:

```bash
# Включить failover-пару (virtio + VF)
virsh attach-interface <vm_name> network default \
  --model virtio --mac 52:54:00:00:01:00 --live --config

# Внутри ВМ: VF автоматически становится primary, virtio — backup
# При миграции VF отключается, трафик переключается на virtio
```

---

### Диагностика и отладка

#### Проверка IOMMU-групп

Все устройства в одной IOMMU-группе должны пробрасываться вместе. Если VF находится в группе с другими устройствами (например, корневой мост), это может вызвать проблемы с изоляцией:

```bash
# Все IOMMU-группы и их устройства
for g in $(find /sys/kernel/iommu_groups/* -maxdepth 1 -type d | sort -V); do
  echo "IOMMU Group $(basename $g):"
  for d in $g/devices/*; do
    echo "  $(lspci -nns $(basename $d))"
  done
done
```

#### NUMA-локальность NIC

```bash
# NUMA-узел NIC
cat /sys/class/net/enp1s0f0/device/numa_node
# → 0

# Проверка NUMA-топологии системы
lscpu | grep -i numa
# → NUMA node(s):        2
# → NUMA node0 CPU(s):   0-31
# → NUMA node1 CPU(s):   32-63

# Все PCI-устройства NUMA-узла 0
find /sys/bus/pci/devices/*/numa_node -exec grep -l "0" {} \;
```

#### Привязка IRQ для VF (IRQ Affinity)

Для оптимальной производительности VF привязывайте прерывания к ядрам локального NUMA-узла:

```bash
# Просмотр прерываний VF
grep 01:00.2 /proc/interrupts
# → 48:  ... PCI-MSI-edge  enp1s0f0-TxRx-0
# → 49:  ... PCI-MSI-edge  enp1s0f0-TxRx-1

# Привязка IRQ 48 к ядрам NUMA-узла 0 (битовая маска для ядер 0-7: ff)
echo ff > /proc/irq/48/smp_affinity

# Или через список ядер (удобнее)
echo 0-7 > /proc/irq/48/smp_affinity_list

# Проверка
cat /proc/irq/48/smp_affinity
# → ff
```

#### Мониторинг статистики VF

```bash
# Статистика VF через ethtool
ethtool -S enp1s0f0 | grep -i vf
# → vf.rx_packets: 12345678
# → vf.tx_packets: 9876543

# Статистика через sysfs
cat /sys/class/net/enp1s0f0/statistics/rx_packets
# → 12345678

# Мониторинг в реальном времени
watch -n1 "ethtool -S enp1s0f0 | grep -E 'rx_|tx_|vf_'"
```

#### Просмотр логов ядра

```bash
# Ошибки при создании VF или привязке драйвера
journalctl -k | grep -iE "sriov|vfio|iommu"
# → kernel: vfio-pci: probe of 0000:01:00.2 failed
# → kernel: iommu_group: Adding device 0000:01:00.2 to group 5

# Последние 20 строк с SR-IOV
dmesg | grep -iE "sriov|vfio|iommu" | tail -20
```

#### Проверка драйверов

```bash
# Текущий драйвер каждого PCI-устройства
sudo dpdk-devbind.py --status
# → Network devices using DPDK-compatible driver
# → ============================================
# → 0000:01:00.2 'Device 1592' if=  drv=vfio-pci unused=i40e
#
# → Network devices using kernel driver
# → ====================================
# → 0000:01:00.0 'Device 1592' if= enp1s0f0 drv=ice unused=vfio-pci

# Текущий драйвер конкретного NIC
ethtool -i enp1s0f0
# → driver: ice
# → version: 1.12.6
# → firmware-version: 4.10 1.3349.0
```

---

### Устранение неисправностей

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| VF не создаются | `echo N > sriov_numvfs` возвращает ошибку | Нехватка BAR-ресурсов PCIe или IOMMU не включён | Проверьте `dmesg` на ошибки IOMMU; попробуйте параметр ядра `pci=realloc`; уменьшите количество VF |
| VF не видна в ВМ | `lspci` в ВМ не показывает устройство | Некорректный пропуск VF через vfio-pci или libvirt | Проверьте XML-конфигурацию ВМ; убедитесь в `managed=yes` для hostdev |
| Низкая производительность VF | p99 задержка выше ожиданий, низкий throughput | NUMA-несоответствие, IRQ не привязаны, IOTLB misses | Проверьте NUMA-локальность; привязьте IRQ; используйте HugePages |
| VF исчезает после перезагрузки | VF не создаются автоматически | Нет конфигурации персистентности | Настройте Netplan, systemd-networkd или udev-rule (см. Шаг 6) |
| Ошибки AER в dmesg | `pcieport ... AER ... Correctable/Uncorrectable error` | Проблемы с PCIe-шиной, нестабильная прошивка NIC | Обновите прошивку NIC; проверьте физическое подключение; попробуйте FLR через `remove`/`rescan` PCI-устройства |
| IOTLB miss rate высокий | Высокая CPU нагрузка в `iommu_fault_handler` | Фрагментированная память VF, отсутствие HugePages | Включите HugePages; закрепите память (mlock); используйте `iommu=pt` для хостовых устройств |
| `EAL: Cannot open /dev/vfio/X` | DPDK-приложение не стартует | VF не привязана к vfio-pci | `dpdk-devbind.py --bind=vfio-pci <pci_addr>` |
| `EAL: IOVA mapping failed` | DPDK-приложение не стартует | IOMMU не включён | Параметр ядра `intel_iommu=on iommu=pt` |
| NIC не видна в `dpdk-devbind` | `dpdk-devbind.py --status` не показывает NIC | Драйвер не загружен или NIC занята | Остановите NetworkManager; `modprobe vfio-pci`; `echo 1 > /sys/bus/pci/rescan` |

#### Принудительный сброс VF (FLR)

Если VF не работает корректно (нет трафика, ошибки в `dmesg`), выполните Function Level Reset:

```bash
# Через sysfs — удалить и восстановить VF
echo 0 > /sys/class/net/enp1s0f0/device/sriov_numvfs
echo 8 > /sys/class/net/enp1s0f0/device/sriov_numvfs

# Через PCI remove/rescan (для сброса устройства)
echo 1 > /sys/bus/pci/devices/0000:01:00.2/remove
echo 1 > /sys/bus/pci/rescan

# Проверка после сброса
dmesg | tail -5
# → vfio-pci: probe of 0000:01:00.2 succeeded
```

---

### Очистка

```bash
# 1. Отвязка VF от vfio-pci
sudo dpdk-devbind.py --bind=i40e 0000:01:00.2  # Вернуть к стандартному драйверу
# Или:
sudo dpdk-devbind.py --unbind 0000:01:00.2

# 2. Удаление VF
echo 0 | sudo tee /sys/class/net/enp1s0f0/device/sriov_numvfs

# 3. Проверка что VF удалены
cat /sys/class/net/enp1s0f0/device/sriov_numvfs
# → 0

# 4. Удаление udev-правил (если создавались)
sudo rm /etc/udev/rules.d/99-vfio-pci.rules
sudo udevadm control --reload-rules

# 5. Отключение HugePages (если больше не нужны)
echo 0 > /sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages
```

---

### Дополнительная информация

- **[Обзор SR-IOV](sriov.md)** — теоретические основы, архитектура аппаратного разделения, NUMA-зависимость и интеграция с KVM/QEMU.
- **[Практические сценарии DPDK и SR-IOV](scenarios.md)** — примеры интеграции с Kubernetes (SR-IOV Device Plugin), OVS-DPDK, VPP, 5G UPF и HFT.
- **[Обзор DPDK](dpdk_overview.md)** — принципы работы Userspace сетевого стека и Poll Mode Drivers.
- **[RSS в DPDK](dpdk_rss.md)** — аппаратное распределение трафика по ядрам CPU.
- **[DPDK Bonding](dpdk_bonding.md)** — LACP, failover, балансировка.
- **[Безопасность DPDK](dpdk_security.md)** — trust, spoof, MACsec.
- **[Hotplug](dpdk_hotplug.md)** — динамическое добавление/удаление NIC.
- **[Технические детали DPDK](dpdk_technical.md)** — оптимизация производительности на уровне памяти (HugePages, TLB) и процессора (CPU Pinning).
- **[Настройка сети в Ubuntu (Netplan)](../../Linux/Networking/Settings/Persistent_Network/ubuntu_netplan.md)** — персистентная конфигурация сетевых интерфейсов и SR-IOV.
- **[ip link — управление интерфейсами](../../Linux/Networking/Tools/iproute2/ip_link.md)** — команды настройки VF, VLAN, trust mode и rate limiting.
