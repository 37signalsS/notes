# Диагностика виртуализации через dmesg

## Определения

**Виртуализационные сообщения в dmesg** — выводы ядра, отражающие работу гипервизора и гостевых ОС: загрузку виртуальных драйверов (virtio, vmxnet3, hv_netvsc), ошибки VMM (Virtual Machine Monitor), проблемы с balloon-драйверами, steal time, nested virtualization и PCI passthrough. Эти сообщения критичны для диагностики производительности и стабильности виртуальных машин.

---

## Базовые концепции

### Типы виртуальных драйверов

| Драйвер | Гипервизор | Тип | Описание |
|:---|:---|:---|:---|
| `virtio_net`, `virtio_blk` | KVM/QEMU | Para-virt | Высокопроизводительные паравиртуализированные драйверы |
| `kvm`, `kvm_intel`, `kvm_amd` | KVM | Модуль хоста | Модули ядра для аппаратной виртуализации |
| `vmxnet3` | VMware | Para-virt | Сетевой драйвер VMware |
| `vmw_balloon` | VMware | Balloon | Драйвер управления памятью |
| `hv_vmbus`, `hv_netvsc`, `hv_storvsc` | Hyper-V | Synth | Синтетические драйверы Hyper-V |
| `xen-netfront`, `xen-blkfront` | Xen | Frontend | Фронтенд-драйверы Xen |

---

## Практические сценарии

### Поиск виртуализационных событий в dmesg

```bash
# Все виртуализационные сообщения
dmesg -T | grep -iE "kvm|qemu|virtio|vmxnet|vmw_|hv_|xen|vhost|balloon|steal|hypervisor"

# Только ошибки
dmesg -T | grep -iE "kvm.*error|virtio.*error|hv_.*error|balloon.*error|vhost.*error"

# Модули виртуализации
dmesg -T | grep -iE "kvm_intel|kvm_amd|kvm.*loaded|module.*kvm"
```

### Диагностика KVM на хосте

```bash
# Загрузка модулей KVM
dmesg | grep -iE "kvm_intel|kvm_amd|kvm.*enabled|kvm.*nested"

# Ключевые паттерны:
# -> kvm_intel: VMX enabled (by BIOS)
# -> kvm_intel: Nested Virtualization enabled
# -> kvm: EPT capable (если Intel VT-d)

# Проверка nested virtualization
cat /sys/module/kvm_intel/parameters/nested 2>/dev/null
# -> Y -- включено, N -- выключено

# Динамическое включение nested virt (без перезагрузки)
sudo modprobe -r kvm_intel
sudo modprobe kvm_intel nested=1
```

### Диагностика virtio-драйверов в госте

```bash
# Проверка загрузки virtio-модулей
dmesg | grep -iE "virtio.*loaded|virtio.*registered|virtio.*features"

# Ключевые паттерны:
# -> virtio_net: going to register ring - size 4096
# -> virtio_blk: going to register ring - size 256

# Ошибки virtio
dmesg | grep -iE "virtio.*error|virtio.*fail|vring|vhost"

# Ключевые паттерны:
# -> virtio_net: ratelimit: X messages suppressed
# -> vring: vring_alloc_queue: failed
# -> vhost: VHOST_GET_BACKEND_FEATURES failed
```

### Диагностика balloon-драйвера

```bash
# VMware balloon
dmesg | grep -iE "vmw_balloon|vmmemctl|balloon"

# Ключевые паттерны:
# -> vmw_balloon: Balloon driver loaded
# -> vmw_balloon: inflating/deflating
# -> vmw_balloon: Guest reports low memory

# Virtio-balloon (KVM)
dmesg | grep -iE "virtio_balloon|vballoon"

# Диагностика проблемы: balloon забирает слишком много памяти
# 1. Проверить Usage в госте
cat /proc/meminfo | grep -i balloon

# 2. Ограничить balloon через libvirt XML
# <memballoon model='virtio'>
#   <memballoon model='none'/>  -- отключить balloon
# </memballoon>
```

### Диагностика Hyper-V драйверов

```bash
# Проверка загрузки Hyper-V модулей
dmesg | grep -iE "hv_|hyper-v|hyperv"

# Ключевые паттерны:
# -> hv_vmbus: Hyper-V Guest Bus Driver initialized
# -> hv_netvsc: channel bond successful
# -> hv_storvsc: cmd 0x28 aborted - resetting

# Ошибки Hyper-V
dmesg | grep -iE "hv_.*error|hv_.*fail|vmbus.*error"

# Ключевые паттерны:
# -> hv_netvsc: no channel available
# -> hv_storvsc: device reset
```

### Диагностика VMware guest tools

```bash
# Проверка VMware-драйверов
dmesg | grep -iE "vmxnet3|vmw_|vmware|open-vm"

# Ключевые паттерны:
# -> vmxnet3 0000:03:00.0: eth0: NIC Link is Up 10000 Mbps
# -> vmxnet3 0000:03:00.0: eth0: ring ring0 is full

# Проверка open-vm-tools
systemctl status vmtoolsd
vmware-toolbox-cmd stat raw 2>/dev/null
```

### Диагностика steal time

```bash
# Проверка steal time
dmesg | grep -iE "steal|kvm.*time|vcpu.*preempt"

# Steal time -- время, когда гипервизор удерживал vCPU
# Высокий steal time (>5%) указывает на Noisy Neighbor или overselling

# Мониторинг steal time
mpstat -P ALL 1 | awk '{print $NF}' | head -1
# -> %usr %sys %iowait %irq %soft %steal %idle

# В dmesg steal time может проявляться как:
# -> kvm: tsc unmstable (встречается при проблемах с clocksource)
# -> kvm: vmclock: detected TSC offset
```

### Диагностика PCI passthrough (VFIO)

```bash
# Проверка загрузки vfio-pci
dmesg | grep -iE "vfio|iommu|passthrough"

# Ключевые паттерны:
# -> vfio-pci 0000:03:00.0: enabling device (0000 -> 0002)
# -> vfio: Ignoring failed probe for 0000:03:00.0

# Ошибки IOMMU
dmesg | grep -iE "iommu.*error|viommu|AMD-Vi|Intel.*IOMMU"

# Ключевые паттерны:
# -> AMD-Vi: Interrupt remapping enabled
# -> Intel-IOMMU: enabled
# -> vfio: No IOMMU group for device -- проблема с IOMMU группировкой
```

### Диагностика nested virtualization

```bash
# Проверка nested virt в dmesg хоста
dmesg | grep -iE "nested|vmentry|vmexit|VMCS"

# Ключевые паттерны:
# -> kvm_intel: Nested Virtualization enabled
# -> kvm: vmentry for nested VM -- L2 VM запущен

# Проблемы с nested virt
dmesg | grep -iE "nested.*error|vmcs.*error|vmx.*abort"

# Ключевые паттерны:
# -> kvm: VMCS READ: nested_vmx_exit_reason = 0x... -- VM-Exit из L2
# -> kvm: VMCS WRITE: failed -- проблема с VMCS
```

---

## Дополнительная информация

### Связанные темы

*   [**KVM Overview**](../../../Virtualization/kvm/overview.md) — архитектура KVM/QEMU.
*   [**KVM Performance Tuning**](../../../Virtualization/kvm/performance_tuning_2026.md) — тюнинг виртуальных машин.
*   [**KVM Troubleshooting**](../../../Virtualization/kvm/troubleshooting.md) — диагностика KVM проблем.
*   [**Nested Virtualization**](../../../Virtualization/nested_virtualization/definitions_and_concepts.md) — теория nested virt.
*   [**Обзор dmesg**](./index.md) — общая архитектура kmsg.
*   [**Поиск и устранение неисправностей**](./troubleshooting.md) — Call Trace, Oops, Panic.
