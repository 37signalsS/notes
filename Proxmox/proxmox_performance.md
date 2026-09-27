# Оптимизация производительности KVM/LXC в Proxmox

## Определения

**NUMA (Non-Uniform Memory Access)** -- архитектура, при которой время доступа к памяти зависит от процессора, к которому она физически подключена. При неправильной настройке гости испытывают задержки из-за удаленного доступа к памяти.

**CPU Pinning** -- привязка виртуальных процессоров VM к конкретным физическим ядрам хоста. Убирает конкуренцию за CPU и снижает context switching.

**Huge Pages** -- страницы памяти увеличенного размера (2 МБ или 1 ГБ вместо 4 КБ). Снижают TLB misses и накладные расходы на управление памятью.

**I/O Scheduler** -- алгоритм планирования дисковых операций. Для SSD/NVMe -- `none` или `mq-deadline`, для HDD -- `bfq`.

**VirtIO** -- семейство паравиртуализированных драйверов, обеспечивающих near-native производительность дисков и сети в KVM VM.

**Balloon Driver** -- VirtIO-модуль для динамического выделения и освобождения памяти внутри гостевой ОС. Позволяет переиспользовать неиспользуемую память VM.

**IOMMU (VT-d/AMD-Vi)** -- аппаратная технология виртуализации ввода-вывода. Позволяет прямой доступ VM к физическим устройствам (GPU, NIC, HBA) с изоляцией.

## Теоретический блок

### Влияние типа хранилища на производительность

| Хранилище | Формат | IOPS | Throughput | Latency |
|-----------|--------|------|-----------|---------|
| NVMe + ZFS | zvol | 100K-500K | 3-7 ГБ/с | <100 мкс |
| NVMe + LVM-Thin | raw | 100K-500K | 3-7 ГБ/с | <100 мкс |
| SATA SSD + ZFS | zvol | 50K-80K | 500 МБ/с | ~200 мкс |
| HDD + ZFS | zvol | 100-200 | 150 МБ/с | ~5 мс |
| NFS (1GbE) | qcow2 | 5K-10K | 110 МБ/с | ~1 мс |
| Ceph RBD | raw | 10K-50K | 1-10 ГБ/с | ~2 мс |

### Типы CPU

| Тип CPU | Описание | Когда использовать |
|---------|----------|-------------------|
| host | Все флаги физического CPU | Production |
| kvm64 | Базовый набор (Pentium 4) | Совместимость |
| qemu64 | Расширенный набор | Старые гости |
| max | Все доступные флаги | Бенчмарки |

## Практические сценарии

### 1. CPU Pinning

```bash
# Определение NUMA топологии
numactl --hardware
lscpu -e

# Настройка VM с CPU pinning
qm set 101 --cpu host,hidden=on --cores 4 --numa 1 --affinity 0-3

# В конфиге VM (/etc/pve/qemu-server/101.conf)
# cpu: host,hidden=on
# cores: 4
# numa: 1
# affinity: 0-3
```

### 2. Huge Pages

```bash
# Проверка текущих Huge Pages
grep -i huge /proc/meminfo

# Выделение 16384 Huge Pages (32 ГБ)
echo 16384 > /proc/sys/vm/nr_hugepages

# Постоянная настройка
echo "vm.nr_hugepages = 16384" >> /etc/sysctl.d/99-hugepages.conf
sysctl -p /etc/sysctl.d/99-hugepages.conf

# В конфиге VM
# memory: 32768
# hugepages: 2048
```

### 3. I/O Scheduler

```bash
# Проверка текущего scheduler
cat /sys/block/nvme0n1/queue/scheduler

# Установка для разных типов дисков
echo none > /sys/block/nvme0n1/queue/scheduler     # NVMe
echo mq-deadline > /sys/block/sda/queue/scheduler   # SSD
echo bfq > /sys/block/sda/queue/scheduler           # HDD

# Постоянная настройка через udev
cat > /etc/udev/rules.d/60-io-scheduler.rules << 'EOF'
ACTION=="add|change", KERNEL=="nvme[0-9]*n[0-9]*", ATTR{queue/scheduler}="none"
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="mq-deadline"
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="1", ATTR{queue/scheduler}="bfq"
EOF
```

### 4. TRIM/DISCARD для SSD

```bash
# Включить TRIM для диска VM
qm set 101 --scsi0 local-lvm:32,discard=on,ssd=1

# На уровне хоста
systemctl enable fstrim.timer
fstrim -av
```

### 5. Оптимизация сети для VM

```bash
# Multi-queue для VirtIO NIC
qm set 101 --net0 virtio,bridge=vmbr0,queues=4

# Внутри гостя
ethtool -l eth0
ethtool -G eth0 rx 4096 tx 4096
ethtool -K eth0 tso on gro on gso on
```

### 6. IOMMU и Device Passthrough

```bash
# Включение IOMMU в GRUB (/etc/default/grub)
# Intel: GRUB_CMDLINE_LINUX_DEFAULT="quiet intel_iommu=on iommu=pt"
# AMD:   GRUB_CMDLINE_LINUX_DEFAULT="quiet amd_iommu=on iommu=pt"

update-grub

# Проверка
dmesg | grep -i iommu

# Проброс GPU в VM
qm set 101 --hostpci0 01:00.0,pcie=1,x-vga=1

# SR-IOV
qm set 101 --hostpci1 03:10.0,sriov=1
```

### 7. Оптимизация Ceph для VM

```bash
# CRUSH rule для NVMe OSD
ceph osd crush rule create-replicated nvme-rule default host nvme

# Пул с NVMe правилами
ceph osd pool create vm-nvme 128 128 replicated
ceph osd pool set vm-nvme crush_rule nvme-rule
ceph osd pool set vm-nvme size 3

# PG Autoscaler
ceph mgr module enable pg_autoscaler
ceph osd pool set vm-nvme pg_autoscale_mode warn
```

### 8. Мониторинг производительности

```bash
# IO delay
iostat -xmt 1

# NUMA статистика
numastat -p $(pgrep qemu)

# CPU по ядрам
mpstat -P ALL 1

# Виртуальные машины
qm status 101 --verbose
```

## Диагностика и устранение неполадок

### Высокий IO Delay

```bash
iotop -oP
iostat -xmt 1
lvs                    # LVM-Thin pool
ceph osd df tree       # Ceph
zpool iostat -v 1      # ZFS
```

### Memory ballooning проблемы

```bash
# Проверка в госте
free -h
cat /proc/meminfo | grep -E "MemTotal|MemFree"

# Если balloon driver не установлен -- память не возвращается
# Установите qemu-guest-agent
```

## Управление памятью

### Balloon Driver

Balloon -- единственный безопасный механизм RAM overcommit в Proxmox:

```bash
# Включение balloon в конфиге VM (/etc/pve/qemu-server/101.conf)
balloon: 1           # Включить balloon
balloon: 0           # Отключить balloon (для latency-чувствительных VM)

# Динамическое управление памятью
qm set 101 --balloon 2048  # Установить целевой размер balloon в MB

# Мониторинг balloon
qm status 101 --verbose | grep balloon
# → balloon: 1024
```

**Принцип работы:**
1. Хост запрашивает у гостя освободить страницы (inflate balloon).
2. Гостевая ОС возвращает страницы ядру (через balloon driver).
3. Хост перераспределяет страницы между VM.

**Важно:** Без QEMU Guest Agent balloon не работает -- память не освобождается.

### KSM (Kernel Same-page Merging)

KSM -- механизм дедупликации страниц памяти с одинаковым содержимым:

```bash
# Включение KSM
echo 1 > /sys/kernel/mm/ksm/run

# Параметры
echo 1000 > /sys/kernel/mm/ksm/pages_to_scan    # сколько страниц сканировать за раз
echo 20 > /sys/kernel/mm/ksm/sleep_millisecs    # задержка между сканированиями

# Статистика
cat /sys/kernel/mm/ksm/pages_shared     # количество уникальных страниц
cat /sys/kernel/mm/ksm/pages_sharing    # количество страниц, ссылающихся на shared
cat /sys/kernel/mm/ksm/pages_unshared   # неиспользуемые страницы
```

**Применение:** KSM наиболее эффективен для VM с похожим содержимым (одинаковые ОС, одинаковые библиотеки).

### OOM Killer и memballoon

```bash
# Порог OOM killer (в процентах от total RAM)
echo 80 > /proc/sys/vm/overcommit_memory  # 0= heuristic, 1=always, 2=never
echo 80 > /proc/sys/vm/overcommit_ratio

# Мониторинг OOM events
dmesg | grep -i "oom\|out of memory"
journalctl -k | grep -i "oom"

# Настройка OOM score для VM
echo -1000 > /proc/$(pgrep qemu)/oom_score_adj  # Защита от OOM
```

### zram (compressed RAM swap)

```bash
# Настройка zram для Proxmox
modprobe zram
echo lz4 > /sys/block/zram0/comp_algorithm
echo 8G > /sys/block/zram0/disksize
mkswap /dev/zram0
swapon -p 100 /dev/zram0  # приоритет выше regular swap

# Проверка
cat /proc/swaps
free -h
```

## Управление CPU

### Типы CPU в Proxmox

| Тип CPU | Описание | Когда использовать |
| :--- | :--- | :--- |
| **host** | Все флаги физического CPU | Production (рекомендуется) |
| **kvm64** | Базовый набор (Pentium 4) | Совместимость со старыми ОС |
| **qemu64** | Расширенный набор | Старые гости |
| **max** | Все доступные флаги | Бенчмарки |
| **host,hidden=on** | Все флаги + скрытие KVM | GPU passthrough (NVIDIA) |

### CPU Shares и Limits

```bash
# Относительный вес (shares)
qm set 101 --shares 2048  # Высокий приоритет (default: 100)
qm set 102 --shares 512   # Низкий приоритет

# Абсолютный лимит (limit)
qm set 101 --cpu-limit 2.5  # Максимум 2.5 ядра

# Проверка
qm config 101 | grep -E "cpu|shares|limit"
# → cpu: host
# → shares: 2048
```

### Nested Virtualization

```bash
# Включение nested virtualization
# Intel:
echo "options kvm_intel nested=1" > /etc/modprobe.d/kvm-nested.conf
modprobe -r kvm_intel && modprobe kvm_intel

# AMD:
echo "options kvm_amd nested=1" > /etc/modprobe.d/kvm-nested.conf
modprobe -r kvm_amd && modprobe kvm_amd

# Проверка
cat /sys/module/kvm_intel/parameters/nested
# → Y (enabled)
```

## Лучшие практики

1. **CPU**: Используйте `cpu: host` для production. Не превышайте overcommit > 2:1.
2. **RAM**: Не используйте balloon для latency-чувствительных VM (БД, кэши). Включайте balloon для general-purpose VM.
3. **Huge Pages**: Включайте для VM с > 4 ГБ RAM.
4. **NUMA**: На двухпроцессорных серверах -- NUMA + pinning для VM > 4 ядер.
5. **Disk**: `virtio-scsi-pci` вместо IDE/SATA. `discard=on` для SSD.
6. **Network**: VirtIO с `queues=4` для высоконагруженных VM.
7. **I/O Scheduler**: NVMe -- none, SSD -- mq-deadline, HDD -- bfq.
8. **TRIM**: `fstrim.timer` на хосте + `discard=on` на дисках VM.
9. **Agent**: Всегда устанавливайте QEMU Guest Agent.
10. **Baselines**: Создавайте baseline производительности и мониторьте регрессии.
11. **KSM**: Включайте для однотипных VM (VDI, dev/test).
12. **zram**: Используйте для замены swap на SSD (экономит I/O).

## Граничные случаи

- **Huge Pages и OOM**: При нехватке Huge Pages система использует обычные страницы. Проверяйте `HugePages_Free`.
- **CPU pinning и миграция**: Live migration с CPU pinning возможна только между узлами с идентичными CPU.
- **Balloon и OOM killer**: Без QEMU Guest Agent balloon не работает, память не освобождается.
- **IOMMU и ядро**: При обновлении ядра проверяйте доступность IOMMU модуля.

## Дополнительная информация

### Связанные темы

- [Обзор Proxmox VE](./proxmox_overview.md)
- [Хранилища и Ceph](./proxmox_storage.md)
- [Сетевые технологии](./proxmox_networking.md)
- [KVM Security Hardening](../Linux/Virtualization/kvm/kvm_security_hardening.md)
