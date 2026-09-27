# Проброс PCI-устройств и GPU в Proxmox VE

## Определения

**VFIO (Virtual Function I/O)** -- современный драйвер ядра Linux для прямого доступа к PCI-устройствам из пространства пользователя. Обеспечивает изоляцию через IOMMU и заменяет устаревший `pciv` и `uio_pci_generic`.

**IOMMU (Input-Output Memory Management Unit)** -- аппаратный блок процессора (Intel VT-d / AMD-Vi), обеспечивающий трансляцию адресов DMA и изоляцию PCI-устройств. Позволяет каждой VM безопасно работать с физическими устройствами без влияния на другие VM или хост.

**IOMMU Group** -- группа PCI-устройств, изолированных как единое целое. Все устройства в группе должны быть проброшены вместе или не пробрасываться вообще. Проверяется через `find /sys/kernel/iommu_groups/`.

**GPU Passthrough** -- прямой доступ VM к физическому GPU, минуя эмуляцию. Позволяет использовать GPU-ускорение (CUDA, OpenCL, 3D-рендеринг) внутри VM с производительностью ~95-99% от bare-metal.

**SR-IOV (Single Root I/O Virtualization)** -- спецификация PCI SIG, позволяющая одному физическому устройству (NIC, GPU) представить себя как несколько независимых виртуальных PCI-устройств (VF). Каждое VF имеет собственный адрес BDF, очереди TX/RX и DMA-каналы.

**VF (Virtual Function)** -- облегченное PCI-устройство, созданное на базе физического устройства (PF) через SR-IOV. VF пробрасывается в VM для прямого DMA-доступа.

**GPU Reset Bug** -- проблема, при которой GPU не может быть корректно сброшен после использования VM, что делает невозможным повторный запуск VM с тем же GPU. Типична для Consumer GPU (NVIDIA GeForce).

**vGPU (Virtual GPU)** -- виртуализация GPU на уровне аппарата (NVIDIA vGPU, Intel GVT-g), позволяющая распределять один физический GPU между несколькими VM. Отличается от passthrough тем, что устройство разделяется, а не передаётся целиком.

## Теоретический блок

### Архитектура VFIO в Proxmox

```
┌─────────────────────────────────────────────────┐
│  Гостевая ОС (VM)                               │
│  ├── GPU driver (nvidia/nouveau, amdgpu)        │
│  └── Приложение (CUDA, Blender, games)          │
├─────────────────────────────────────────────────┤
│  QEMU (userspace)                               │
│  └── VFIO-PCI device passthrough                │
│       ├── BAR space mapping                     │
│       ├── Interrupt remapping                    │
│       └── DMA isolation (IOMMU)                 │
├─────────────────────────────────────────────────┤
│  Ядро хоста                                     │
│  ├── vfio-pci (драйвер)                         │
│  ├── IOMMU (Intel VT-d / AMD-Vi)               │
│  └── /dev/vfio/<group_id>                       │
├─────────────────────────────────────────────────┤
│  Физическое устройство                          │
│  └── GPU (NVIDIA RTX / AMD Radeon)              │
└─────────────────────────────────────────────────┘
```

### Требования к оборудованию

| Компонент | Минимальное | Рекомендуемое |
| :--- | :--- | :--- |
| **CPU** | С поддержкой VT-d/AMD-Vi | Intel Xeon / AMD EPYC |
| **BIOS** | VT-d/AMD-Vi enabled | + ACS, SR-IOV support |
| **GPU (primary)** | Любая с поддержкой UEFI | NVIDIA Quadro / AMD Radeon Pro |
| **GPU (secondary)** | Consumer GPU с reset bug workaround | GPU без reset bug (NVIDIA Tesla) |
| **RAM** | 16 GB | 32+ GB (GPU VRAM не учитывается) |

### IOMMU группы

IOMMU группы определяют, какие устройства изолированы вместе. Все устройства в одной группе должны быть проброшены в одну VM.

```bash
# Просмотр всех IOMMU групп
for d in /sys/kernel/iommu_groups/*/devices/*; do
  n=${d#*/iommu_groups/}; n=${n%%/*}
  printf 'IOMMU Group %s: ' "$n"
  lspci -nns "${d##*/}"
done

# Упрощенный вариант
#!/bin/bash
for g in $(find /sys/kernel/iommu_groups/* -maxdepth 0 -type d | sort -V); do
  echo "IOMMU Group ${g##*/}:"
  for d in $g/devices/*; do
    echo -e "\t$(lspci -nns ${d##*/})"
  done
done
```

**Проблемаlarge IOMMU Groups:** Многие Consumer GPU находятся в группе с другими устройствами (USB-контроллер, аудио). Без ACS override patch все устройства в группе должны быть проброшены. Решения:

1. **ACS Override Patch** -- патч ядра, разбивающий IOMMU группы на более мелкие (небезопасно для production).
2. **Использование серверного оборудования** -- серверные чипсеты (Intel C620+, AMD EPYC) имеют корректные IOMMU группы.
3. **Ручной обход** -- проброс всех устройств из группы в одну VM.

### GPU Reset Bug и решения

| GPU | Reset Bug | Решение |
| :--- | :--- | :--- |
| NVIDIA GeForce (consumer) | Да | vendor-reset kernel module |
| NVIDIA Quadro / Tesla | Нет | Нативная поддержка |
| AMD Radeon (pre RDNA2) | Да | vendor-reset / amdgpu.ppfeaturemask |
| AMD Radeon Pro | Редко | Проверка перед покупкой |

```bash
# vendor-reset -- решение для NVIDIA/AMD consumer GPU
git clone https://github.com/andrewwhitehead/vendor-reset.git
cd vendor-reset
make -C /lib/modules/$(uname -r)/build M=$(pwd) modules
sudo insmod vendor-reset.ko
```

## Практические сценарии

### 1. Включение IOMMU в Proxmox

```bash
# Проверка поддержки IOMMU
dmesg | grep -i "iommu\|intel-iommu\|amd-iommu"

# Включение в GRUB
# Intel:
编辑 /etc/default/grub
GRUB_CMDLINE_LINUX_DEFAULT="quiet intel_iommu=on iommu=pt"

# AMD:
GRUB_CMDLINE_LINUX_DEFAULT="quiet amd_iommu=on iommu=pt"

update-grub
reboot

# Проверка после перезагрузки
dmesg | grep -i "DMAR\|IOMMU\|AMD-Vi"
# → DMAR: IOMMU enabled
# → AMD-Vi: Interrupt remapping enabled
```

### 2. Настройка VFIO для GPU

```bash
# Определение BDF (Bus Device Function) GPU
lspci -nn | grep -i vga
# → 01:00.0 VGA compatible controller [0300]: NVIDIA Corporation GA102 [10de:2204] (rev a1)

# Определениеvfio-pci для устройства
echo "10de 2204" | sudo tee /sys/bus/pci/drivers/vfio-pci/new_id

# Блокировка стандартного драйвера NVIDIA
echo "blacklist nouveau" | sudo tee /etc/modprobe.d/blacklist-nouveau.conf
echo "options nouveau modeset=0" | sudo tee -a /etc/modprobe.d/blacklist-nouveau.conf
echo "blacklist nvidia" | sudo tee /etc/modprobe.d/blacklist-nvidia.conf

# Настройкаvfio-pci для автозагрузки
echo "options vfio-pci ids=10de:2204" | sudo tee /etc/modprobe.d/vfio.conf
echo "softdep nouveau pre: vfio-pci" | sudo tee -a /etc/modprobe.d/vfio.conf
echo "softdep nvidia pre: vfio-pci" | sudo tee -a /etc/modprobe.d/vfio.conf

# Обновление initramfs
update-initramfs -u -k all
reboot

# Проверка
lspci -k -s 01:00.0
# → Kernel driver in use: vfio-pci
```

### 3. Проброс GPU в VM через CLI

```bash
# Проброс GPU (PCIe) в VM
qm set 101 --hostpci0 01:00.0,pcie=1,x-vga=1

# Конфигурация в /etc/pve/qemu-server/101.conf
# hostpci0: 01:00.0,pcie=1,x-vga=1
# cpu: host,hidden=on
# args: -cpu host,kvm=off,hv_vendor_id=1234567890ab

# Для NVIDIA: скрытие виртуальной среды
# args: -cpu host,kvm=off,hv_vendor_id=randomid
```

### 4. SR-IOV для сетевых адаптеров

```bash
# Включение SR-IOV в ядре
echo "options ixgbe max_vfs=8" | sudo tee /etc/modprobe.d/ixgbe.conf
# или для i40e:
echo "options i40e max_vfs=8" | sudo tee /etc/modprobe.d/i40e.conf

modprobe -r ixgbe && modprobe ixgbe

# Просмотр VFs
lspci | grep "Virtual Function"
ip link show enp1s0f0
# → VF 0, 1, 2...

# Проброс VF в VM
qm set 101 --hostpci1 03:10.0,sriov=1
```

### 5. Диагностика проблем

```bash
# Проверка IOMMU групп
find /sys/kernel/iommu_groups/ -type l | sort -V

# Проверка загрузкиvfio-pci
dmesg | grep -iE "vfio|iommu|passthrough"

# Типичные ошибки:
# →vfio: Ignoring failed probe for 0000:01:00.0
# Причина: IOMMU не включен или device already bound to another driver

# Проверка связки устройств
cat /sys/bus/pci/devices/0000:01:00.0/driver_override
# → vfio-pci

# Мониторинг DMA
cat /proc/interrupts | grep -i vfio
```

### 6. Proxmox API для управления passthrough

```bash
# Через pvesh
pvesh set /nodes/node1/hardware/pci/0000:01:00.0 -o iommugroup=1

# Через REST API
curl -k -X POST "https://pve1.example.com:8006/api2/json/nodes/node1/hardware/pci" \
  -H "Authorization: PVEAPIToken=USER@REALM!TOKENID=UUID" \
  -d '{"id":"0000:01:00.0","iommugroup":1}'
```

## Диагностика и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| IOMMU не включен | BIOS/GRUB | `intel_iommu=on iommu=pt` в GRUB |
| VFIO: device already bound | Другой драйвер захватил устройство | `echo "vfio-pci" > /sys/bus/pci/devices/.../driver_override` |
| GPU не сбрасывается (reset bug) | Consumer GPU | Установить `vendor-reset` module |
| VM не стартует с GPU | Нехватка MMIO пространства | Добавить `efifb=off video=efifb:off` в GRUB |
| Black screen в госте | NVIDIA Optimus | Используйте `x-vga=1` + UEFI BIOS |
| VFIO timeout | Медленная инициализация GPU | Увеличить timeout: `options vfio-pci disable_vga=1` |

## Лучшие практики

1. **Используйте серверное оборудование**: Серверные чипсеты имеют корректные IOMMU группы без ACS override.
2. **Для NVIDIA GPU**: Устанавливайте официальный драйвер в госте, но включайте `kvm=off` для скрытия виртуальной среды.
3. **Для production GPU workloads**: Используйте NVIDIA Quadro/Tesla без reset bug.
4. **SR-IOV предпочтительнее Passthrough**: Когда нужно разделить одно устройство между несколькими VM.
5. **Мониторинг**: Отслеживайте IOMMU faults через `dmesg` и `/sys/kernel/debug/iommu/`.
6. **Резервное копирование**: Перед обновлением ядра проверяйте совместимостьvfio-pci модуля.
7. **NUMA**: При multi-socket конфигурации убедитесь, что GPU подключен к тому же NUMA-узлу, что и vCPU VM.

## Граничные случаи

- **GPU passthrough + Live Migration**: Возможна только между узлами с идентичными GPU и IOMMU конфигурацией.
- **NVIDIA Code 43**: Ошибка в Windows, когда GPU обнаруживает виртуальную среду. Решение: `kvm=off` + `hv_vendor_id`.
- **AMD GPU +/vendor-reset**: Требуется загрузка модуля до старта VM; автоматизируйте через systemd.
- **Проброс NVMe**: Используйте `qm set 101 --hostpci0 0000:03:00.0` для прямого доступа к NVMe SSD.

## Дополнительная информация

### Связанные темы

- [Проброс GPU и PCI-устройств в ВМ (VFIO) -- SSoT](../Linux/Virtualization/kvm/gpu_pci_passthrough.md)
- [SR-IOV -- SSoT](../Networking/Concepts/dpdk/sriov_setup.md)
- [Диагностика виртуализации через dmesg](../Linux/Diagnostics/Kernel/dmesg/virtualization.md)
- [Оптимизация производительности KVM/LXC](./proxmox_performance.md)
