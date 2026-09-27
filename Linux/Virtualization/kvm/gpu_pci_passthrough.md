# Проброс GPU и PCI-устройств в ВМ (VFIO)

В данном файле описывается настройка прямого проброса GPU и других PCI-устройств в виртуальные машины KVM/QEMU через VFIO (Virtual Function I/O). SR-IOV для сетевых карт описан в [Продвинутая сеть KVM](./kvm_networking_advanced.md), а базовый NVMe passthrough — в [Основных концепциях образов](../vm_images/basic_concepts.md).

## Определения

**VFIO (Virtual Function I/O)** — современный драйвер ядра Linux для прямого доступа к PCI-устройствам из пространства пользователя. Обеспечивает изоляцию через IOMMU и заменяет устаревший `pciv` и `uio_pci_generic`.

**IOMMU (Input-Output Memory Management Unit)** — аппаратный блок процессора, обеспечивающий трансляцию адресов DMA и изоляцию PCI-устройств. Intel VT-d и AMD-Vi — реализации IOMMU.

**IOMMU Group** — группа PCI-устройств, изолированных как единое целое. Все устройства в группе должны быть проброшены вместе или не пробрасываться вообще.

**GPU Passthrough** — прямой доступ ВМ к физическому GPU, минуя эмуляцию. Позволяет использовать GPU-ускорение (CUDA, OpenCL, 3D-рендеринг) внутри ВМ с производительностью ~95-99% от bare-metal.

**VF (Virtual Function)** — облегченное PCI-устройство, созданное на базе физического устройства (PF) через SR-IOV. VF может быть проброшен в ВМ для прямого DMA-доступа.

**AMD VIOMMU / Intel VT-d** — технологии аппаратной виртуализации I/O, обеспечивающие изоляцию DMA-транзакций и прерываний для каждого PCI-устройства.

**GPU Reset Bug** — проблема, при которой GPU не может быть корректно сброшен после использования ВМ, что делает невозможным повторный запуск ВМ с тем же GPU. Типична для Consumer GPU (NVIDIA GeForce).

**vGPU (Virtual GPU)** — виртуализация GPU на уровне аппарата (NVIDIA vGPU, Intel GVT-g), позволяющая распределять один физический GPU между несколькими ВМ. Отличается от passthrough.

## Базовые концепции

### Архитектура VFIO

```
┌─────────────────────────────────────────────────┐
│  Гостевая ОС (ВМ)                               │
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

```bash
# Просмотр всех IOMMU групп
for g in $(find /sys/kernel/iommu_groups/* -maxdepth 1 -type d | sort -V); do
  echo "=== IOMMU Group $(basename $g) ==="
  for d in $g/devices/*; do
    echo "  $(lspci -nns $(basename $d))"
  done
done

# Пример вывода:
# === IOMMU Group 1 ===
#   01:00.0 VGA compatible controller [0300]: NVIDIA Corporation GA102 [10de:2204] (rev a1)
#   01:00.1 Audio device [0403]: NVIDIA Corporation GA102 HDMI Audio [10de:1aef] (rev a1)
```

**Важно:** GPU и его HD Audio controller находятся в одной IOMMU группе. Оба устройства должны быть проброшены вместе.

## Практические сценарии

### Сценарий 1: Включение IOMMU

```bash
# 1. Проверка поддержки IOMMU в CPU
grep -E "(vmx|svm)" /proc/cpuinfo | head -1
# → flags: ... vmx ... (Intel) или ... svm ... (AMD)

# 2. Проверка в BIOS/UEFI
# Intel: VT-d → Enabled
# AMD: AMD-Vi → Enabled
# Дополнительно: ACS (Access Control Services) → Enabled (если есть)

# 3. Добавление параметров ядра в GRUB
# Для Intel:
sudo sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="/GRUB_CMDLINE_LINUX_DEFAULT="intel_iommu=on iommu=pt /' /etc/default/grub

# Для AMD:
sudo sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT="/GRUB_CMDLINE_LINUX_DEFAULT="amd_iommu=on iommu=pt /' /etc/default/grub

# 4. Обновление GRUB и перезагрузка
sudo update-grub && sudo reboot

# 5. Проверка после перезагрузки
dmesg | grep -i iommu
# → DMAR: IOMMU enabled
# → AMD-Vi: IOMMU performance counters supported

# Проверка что IOMMU active:
cat /sys/kernel/iommu_groups/*/type 2>/dev/null | head -5
# → DMAR
```

### Сценарий 2: Проброс NVIDIA GPU

```bash
# 1. Определение PCI-адреса GPU
lspci -nn | grep -i nvidia
# → 01:00.0 VGA compatible controller [0300]: NVIDIA Corporation GA102 [10de:2204] (rev a1)
# → 01:00.1 Audio device [0403]: NVIDIA Corporation GA102 HDMI Audio [10de:1aef] (rev a1)

# 2. Отвязка GPU от драйвера хоста
# Временная (до перезагрузки):
sudo modprobe -r nouveau
sudo modprobe -r nvidia
sudo modprobe -r nvidia_drm
sudo modprobe -r nvidia_modeset

# Постоянная (через blacklist):
cat > /etc/modprobe.d/blacklist-gpu.conf << 'EOF'
blacklist nouveau
blacklist nvidia
blacklist nvidia_drm
blacklist nvidia_modeset
blacklist nvidia_uvm
EOF

sudo update-initramfs -u

# 3. Привязка к vfio-pci
# Загрузка модуля:
sudo modprobe vfio-pci

# Привязка (временно):
echo "0000:01:00.0" | sudo tee /sys/bus/pci/devices/0000:01:00.0/driver_override
echo "0000:01:00.1" | sudo tee /sys/bus/pci/devices/0000:01:00.1/driver_override
echo "0000:01:00.0" | sudo tee /sys/bus/pci/drivers/vfio-pci/bind
echo "0000:01:00.1" | sudo tee /sys/bus/pci/drivers/vfio-pci/bind

# Постоянная (udev rule):
cat > /etc/udev/rules.d/99-gpu-vfio-pci.rules << 'EOF'
# NVIDIA GPU + Audio
ACTION=="add", SUBSYSTEM=="pci", ATTR{vendor}=="0x10de", ATTR{class}=="0x030000", RUN+="/bin/sh -c 'echo vfio-pci > /sys/bus/pci/devices/%k/driver_override'"
ACTION=="add", SUBSYSTEM=="pci", ATTR{vendor}=="0x10de", ATTR{class}=="0x040300", RUN+="/bin/sh -c 'echo vfio-pci > /sys/bus/pci/devices/%k/driver_override'"
EOF

sudo udevadm control --reload && sudo udevadm trigger

# 4. Проверка привязки
lspci -k -s 01:00
# → Kernel driver in use: vfio-pci

# 5. Проверка IOMMU группы
find /sys/kernel/iommu_groups/ -type l | grep "01:00"
# → /sys/kernel/iommu_groups/1/devices/0000:01:00.0
# → /sys/kernel/iommu_groups/1/devices/0000:01:00.1
```

### Сценарий 3: Конфигурация ВМ с GPU

```xml
<!-- /etc/libvirt/qemu/gpu-vm.xml -->
<domain type='kvm'>
  <name>gpu-vm</name>
  <memory unit='GiB'>16</memory>
  <vcpu placement='static'>4</vcpu>
  
  <cputune>
    <!-- Изоляция vCPU от эмулятора -->
    <vcpupin vcpu='0' cpuset='2'/>
    <vcpupin vcpu='1' cpuset='3'/>
    <vcpupin vcpu='2' cpuset='4'/>
    <vcpupin vcpu='3' cpuset='5'/>
    <emulatorpin cpuset='0-1'/>
  </cputune>

  <os>
    <type arch='x86_64' machine='pc-q35-8.2'>hvm</type>
    <loader readonly='yes' type='pflash'>/usr/share/OVMF/OVMF_CODE.fd</loader>
    <nvram>/var/lib/libvirt/qemu/nvram/gpu-vm_VARS.fd</nvram>
    <boot dev='hd'/>
  </os>

  <devices>
    <!-- Основной диск -->
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' cache='none' io='io_uring'/>
      <source file='/var/lib/libvirt/images/gpu-vm.qcow2'/>
      <target dev='vda' bus='virtio'/>
    </disk>

    <!-- GPU (Primary) -->
    <hostdev mode='subsystem' type='pci' managed='yes'>
      <source>
        <address domain='0x0000' bus='0x01' slot='0x00' function='0x0'/>
      </source>
      <address type='pci' domain='0x0000' bus='0x06' slot='0x00' function='0x0'/>
    </hostdev>

    <!-- GPU Audio -->
    <hostdev mode='subsystem' type='pci' managed='yes'>
      <source>
        <address domain='0x0000' bus='0x01' slot='0x00' function='0x1'/>
      </source>
      <address type='pci' domain='0x0000' bus='0x06' slot='0x00' function='0x1'/>
    </hostdev>

    <!-- Сеть -->
    <interface type='bridge'>
      <source bridge='br0'/>
      <model type='virtio'/>
      <driver name='vhost' queues='4'/>
    </interface>
  </devices>

  <!-- Hugepages для производительности -->
  <memoryBacking>
    <hugepages>
      <page size='2' unit='MiB'/>
    </hugepages>
    <locked/>
  </memoryBacking>

  <!-- CPU mode для максимальной совместимости -->
  <cpu mode='host-passthrough' check='none' migratable='off'>
    <topology sockets='1' dies='1' cores='4' threads='1'/>
    <cache mode='passthrough'/>
  </cpu>
</domain>
```

**Применение конфигурации:**
```bash
# Определениеvfio-pci IDs
GPU_IDS="10de:2204,10de:1aef"

# Добавление в модуль vfio-pci
echo "options vfio-pci ids=$GPU_IDS" | sudo tee /etc/modprobe.d/vfio.conf

# Обновление initramfs
sudo update-initramfs -u

# Define и запуск ВМ
virsh define /etc/libvirt/qemu/gpu-vm.xml
virsh start gpu-vm
```

### Сценарий 4: Решение GPU Reset Bug

**Проблема:** После остановки ВМ GPU не сбрасывается и не может быть повторно использован.

```bash
# 1. Диагностика
dmesg | grep -i "vfio\|reset"
# → vfio-pci 0000:01:00.0: Failed to reset PCI device

# 2. Решение: vendor-reset модуль (для AMD GPU)
git clone https://github.com/gnif/vendor-reset.git
cd vendor-reset
make
sudo insmod vendor-reset.ko

# Проверка:
sudo dmesg | grep vendor-reset
# → vendor-reset: loaded

# 3. Решение:-specific для NVIDIA (scripts)
# NVIDIA не требует vendor-reset, но может требовать:

# a) Остановка VM перед выгрузкой vfio-pci:
virsh shutdown gpu-vm
sleep 5

# b) Выгрузка vfio-pci и перезагрузка GPU:
echo 0000:01:00.0 > /sys/bus/pci/drivers/vfio-pci/unbind
echo 1 > /sys/bus/pci/rescan

# c) Проверка:
lspci -k -s 01:00
# → Kernel driver in use: nvidia (если вернулся)

# 4. Решение: evitar el problema с start scripts
cat > /usr/local/sbin/vm-gpu-reset.sh << 'SCRIPT'
#!/bin/bash
VM_NAME="$1"
GPU_ADDR="0000:01:00.0"

# Остановка ВМ
virsh shutdown "$VM_NAME"
sleep 5

# Отвязка от vfio-pci
echo "$GPU_ADDR" > /sys/bus/pci/drivers/vfio-pci/unbind 2>/dev/null || true

# Рескан PCI
echo 1 > /sys/bus/pci/rescan

# Ожидание восстановления
sleep 2
DRIVER=$(lspci -k -s "${GPU_ADDR:0:7}" | grep "Kernel driver" | awk '{print $NF}')
echo "GPU driver after reset: $DRIVER"
SCRIPT
chmod +x /usr/local/sbin/vm-gpu-reset.sh
```

### Сценарий 5: Проброс NVMe через VFIO

```bash
# 1. Определение NVMe
lspci -nn | grep -i nvme
# → 03:00.0 Non-Volatile memory controller [0108]: Samsung Electronics [144d:a808]

# 2. Привязка к vfio-pci
NVME_ADDR="0000:03:00.0"

# Проверка что NVMe не занят:
lsblk | grep nvme
# → (пусто если не смонтирован)

# Отвязка от nvme модуля:
sudo modprobe -r nvme

# Привязка к vfio-pci:
echo "$NVME_ADDR" | sudo tee /sys/bus/pci/devices/$NVME_ADDR/driver_override
echo "$NVME_ADDR" | sudo tee /sys/bus/pci/drivers/vfio-pci/bind

# 3. Конфигурация ВМ (дополнение к основному XML)
# <hostdev mode='subsystem' type='pci' managed='yes'>
#   <source>
#     <address domain='0x0000' bus='0x03' slot='0x00' function='0x0'/>
#   </source>
# </hostdev>

# 4. Проверка в ВМ
ssh root@<vm-ip> "lsblk"
# → NAME   SIZE TYPE
# → nvme0n1 954G disk  ← прямой доступ к NVMe
```

### Сценарий 6: Мониторинг GPU в ВМ

```bash
# 1. Установка NVIDIA drivers в ВМ (Windows)
# Скачать с nvidia.com, установить, перезагрузить

# 2. Установка NVIDIA drivers в ВМ (Linux)
sudo apt install -y nvidia-driver-535 nvidia-utils-535
sudo reboot

# 3. Проверка в ВМ
nvidia-smi
# → +-----------------------------------------------------------------------------+
# → | NVIDIA-SMI 535.129.03   Driver Version: 535.129.03   CUDA Version: 12.2     |
# → |-------------------------------+----------------------+----------------------+
# → | GPU  Name        Persistence-M| Bus-Id        Disp.A | Volatile Uncorr. ECC |
# → | Fan  Temp  Perf  Pwr:Usage/Cap|         Memory-Usage | GPU-Util  Compute M. |
# → |===============================+======================+======================|
# → |   0  NVIDIA RTX 3090      Off | 00000000:06:00.0 Off |                  N/A |
# → |  0%   35C    P8    22W / 350W |      0MiB / 24576MiB |      0%      Default |
# → +-------------------------------+----------------------+----------------------+

# 4. Мониторинг через Prometheus (nvidia exporter)
# На хосте:
docker run -d --restart=always \
  --privileged \
  --pid=host \
  -p 9400:9400 \
  nvidia/dcgm-exporter

# В prometheus.yml:
# - job_name: 'nvidia-gpu'
#   static_configs:
#     - targets: ['kvm-host:9400']
```

## Диагностика

```bash
#!/bin/bash
# gpu-passthrough-diagnose.sh — диагностика VFIO
set -euo pipefail

echo "=== VFIO/GPU Passthrough Diagnostics ==="

# 1. IOMMU включен?
echo "--- IOMMU Status ---"
dmesg | grep -i "iommu.*enabled" | head -1
[ $? -eq 0 ] && echo "IOMMU: OK" || echo "IOMMU: NOT ENABLED (check BIOS/GRUB)"

# 2. VFIO модуль загружен?
echo "--- VFIO Module ---"
lsmod | grep vfio
[ $? -eq 0 ] && echo "vfio-pci: loaded" || echo "vfio-pci: NOT LOADED"

# 3. Устройства привязаны к vfio-pci?
echo "--- VFIO Devices ---"
lspci -nnk | grep -B3 "vfio-pci"

# 4. IOMMU группы
echo "--- IOMMU Groups ---"
for g in $(find /sys/kernel/iommu_groups/* -maxdepth 1 -type d | sort -V); do
  DEVICES=$(ls $g/devices/ 2>/dev/null | wc -l)
  if [ "$DEVICES" -gt 0 ]; then
    echo "Group $(basename $g): $DEVICES device(s)"
    for d in $g/devices/*; do
      echo "  $(lspci -nns $(basename $d))"
    done
  fi
done

# 5. Проверка ACS (если GPU в отдельной группе)
echo "--- ACS Status ---"
dmesg | grep -i "acs" | head -3

# 6. Проверка Reset capability
echo "--- GPU Reset ---"
for gpu in $(lspci -nn | grep -i "vga\|3d" | awk '{print $1}'); do
  DRIVER=$(lspci -k -s $gpu | grep "Kernel driver" | awk '{print $NF}')
  echo "GPU $gpu: driver=$DRIVER"
done
```

## Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **"No IOMMU detected"** | IOMMU не включен в BIOS или GRUB | Включить VT-d/AMD-Vi в BIOS, добавить `intel_iommu=on` в GRUB |
| **"Device is in IOMMU group with other devices"** | IOMMU group включает другие устройства | Использовать ACS override (risks!) или пробросить все устройства в группе |
| **"Failed to reset PCI device"** | GPU reset bug (типично для GeForce) | Использовать vendor-reset модуль или Tesla/Quadro GPU |
| **"vfio-pci: probe failed"** | Устройство занято другим драйвером | Выгрузить драйвер (`modprobe -r nvidia`) перед привязкой |
| **GPU работает медленно** | Нет PCIe Gen4/Gen5 x16 | Проверить `lspci -v` — должен быть x16, не x4 |
| **Нет video output** | VBIOS не загружается | Добавить VBIOS ROM file в XML: `<rom bar='off' file='/path/to/vbios.rom'/>` |
| **VM зависает при запуске GPU** | IRQ conflict или IOMMU fault | Проверить `dmesg \| grep -i "irq\|iommu"`, попробовать другой PCI slot |

## Дополнительная информация

- [Продвинутая сеть KVM](./kvm_networking_advanced.md) — SR-IOV, DPDK, OVS.
- [Оптимизация KVM (2025–2026)](./performance_tuning_2026.md) — CPU pinning, HugePages, NUMA.
- [Диагностика и решение проблем](./troubleshooting.md) — VFIO, macvtap, общий troubleshooting.
- [Sysctl чек-лист для KVM-хостов](./kvm_host_sysctl_checklist.md) — IOMMU-related sysctl.
