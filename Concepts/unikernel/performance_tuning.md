# Производительность и тюнинг Unikernel

**Актуально для:** Unikraft v0.21.0, KraftKit v0.12.15, Nanos (актуальная ветка), MirageOS v4.11.x, OSv v0.57.0; примеры for on-premise развёртываний

## Определения

**Производительность и тюнинг юникернелов** — это методы оптимизации задержки, пропускной способности и плотности инстансов в среде KVM/QEMU. Включает CPU pinning, NUMA-aware размещение, HugePages, IOThreads, vhost-net, тюнинг сетевого стека и методику benchmarks.

Базовая информация — в [Обзоре Unikernel](./unikernel_overview.md).

## Основные концепции

### Архитектура производительности

```
Хост (Linux)
├── KVM (ядро виртуализации)
│   ├── VCPU (pinning → NUMA node)
│   ├── RAM (HugePages, THP=never)
│   └── virtio-net (vhost-net, multi-queue)
├── QEMU (userspace VMM)
│   ├── IOThreads (дисковые операции)
│   └── Серийный порт (console)
└── Юникернел (ELF-бинарник)
    ├── Приложение (0-copy, io_uring)
    └── Library OS (TCP/IP стек)
```

### Факторы производительности

| Фактор | Влияние | Метод оптимизации |
| :--- | :--- | :--- |
| **CPU context switches** | +10-50 мкс latency | Pinning, host-passthrough |
| **NUMA miss** | +70-130 нс на доступ | NUMA-aware placement |
| **TLB misses** | +50-100 нс | HugePages (2MB/1GB) |
| **Virtio-net interrupts** | +10-50 мкс | vhost-net, multi-queue |
| **Дисковые I/O** | +100-500 мкс | IOThreads, cache=writeback |

## Практические сценарии

### 1. CPU Pinning

#### Virsh XML

```xml
<cpu mode='host-passthrough' check='none'>
  <topology sockets='1' cores='2' threads='1'/>
  <numa>
    <cell id='0' cpus='0-1' memory='268435456' unit='bytes'/>
  </numa>
  <cputune>
    <vcpupin vcpu='0' cpuset='0'/>
    <vcpupin vcpu='1' cpuset='1'/>
    <emulatorpin cpuset='0-1'/>
    <iothreadpin iothread='1' cpuset='0-1'/>
  </cputune>
</cpu>
```

#### QEMU CLI

```bash
qemu-system-x86_64 \
  -cpu host \
  -smp 2,sockets=1,cores=2,threads=1 \
  -numa node,memdev=mem0 \
  -numa cpu,node-id=0,socket-id=0,core-id=0 \
  -numa cpu,node-id=0,socket-id=0,core-id=1 \
  -object memory-backend-ram,id=mem0,size=256M,policy=bind,host-nodes=0 \
  -m 256 -nographic
```

### 2. NUMA-aware размещение

```bash
# Проверка топологии NUMA
lscpu | grep -E 'NUMA|CPU'
# → NUMA node(s): 2
# → NUMA node0 CPU(s): 0-3
# → NUMA node1 CPU(s): 4-7

# Привязка памяти к NUMA node 0
numactl --cpunodebind=0 --membind=0 qemu-system-x86_64 ...

# Проверка размещения
numastat -p qemu-system-x86_64
```

### 3. HugePages

```bash
# Резервирование HugePages (2MB)
echo 1024 | sudo tee /proc/sys/vm/nr_hugepages

# Проверка
cat /proc/meminfo | grep HugePages
# → HugePages_Total:    1024
# → HugePages_Free:     1024

# Постоянное резервирование
echo "vm.nr_hugepages = 1024" | sudo tee -a /etc/sysctl.d/99-hugepages.conf
sudo sysctl -p /etc/sysctl.d/99-hugepages.conf

# Использование в QEMU
qemu-system-x86_64 \
  -memory-backend file=/dev/hugepages,size=256M,prealloc=on \
  -m 256 \
  ...
```

### 4. IOThreads

```xml
<!-- В XML дефиниции -->
<devices>
  <disk type='file' device='disk'>
    <driver name='qemu' type='qcow2' cache='writeback' io='threads' iothread='1'/>
    <source file='/var/lib/libvirt/images/unikernels/data.qcow2'/>
    <target dev='vda' bus='virtio'/>
  </disk>
  <iothreadids>
    <iothread id='1'/>
  </iothreadids>
</devices>
```

```bash
# Или через QEMU CLI
qemu-system-x86_64 \
  -object iothread,id=iothread1 \
  -drive file=data.qcow2,if=virtio,aio=threads,queues=2 \
  -device virtio-blk-pci,drive=drive0,iothread=iothread1 \
  ...
```

### 5. vhost-net

```bash
# Проверка поддержки vhost-net
lsmod | grep vhost
# → vhost_net              28672  0

# Запуск с vhost-net
qemu-system-x86_64 \
  -netdev type=vhost,chardev=charnet0,id=hostnet0 \
  -device virtio-net-pci,netdev=hostnet0,queues=2 \
  ...
```

### 6. Тюнинг хоста

```bash
# tuned profile
sudo tuned-adm profile virtual-host

# sysctl параметры
cat <<EOF | sudo tee /etc/sysctl.d/99-kvm.conf
# KVM
net.core.netdev_max_backlog = 250000
net.core.rmem_default = 134217728
net.core.rmem_max = 134217728
net.core.wmem_default = 134217728
net.core.wmem_max = 134217728
net.ipv4.tcp_rmem = 4096 87380 134217728
net.ipv4.tcp_wmem = 4096 65536 134217728
net.ipv4.tcp_low_latency = 1
net.ipv4.tcp_syncookies = 0
fs.nr_open = 1048576
vm.overcommit_memory = 0
EOF

sudo sysctl -p /etc/sysctl.d/99-kvm.conf
```

### 7. Benchmarks

#### HTTP-нагрузка (wrk)

```bash
# Установка
wrk -t12 -c400 -d30s --latency http://10.0.0.2:8080/
# → Running 30s test @ http://10.0.0.2:8080/
# → 12 threads and 400 connections
# → Latency: p50=0.3ms p99=0.8ms
```

#### Сеть (iperf3)

```bash
# На хосте
iperf3 -s

# На юникернеле (внутри)
iperf3 -c 10.0.0.1 -t 30 -P 4
# → [SUM] 0.00-30.00 sec 9.88 GBytes 2.89 Gbits/sec
```

#### Диск (fio)

```bash
# На хосте
fio --name=randread_4k \
  --filename=/dev/vdb \
  --bs=4k \
  --iodepth=32 \
  --rw=randread \
  --numjobs=4 \
  --runtime=30 \
  --group_reporting

# → READ: IOPS=12500, BW=50.0MiB/s
```

### 8. Capacity Planning

#### Формула плотности

```bash
# Общие ресурсы хоста
TOTAL_RAM_GB=32
TOTAL_CORES=16

# Нагрузка системы
SYSTEM_RAM_GB=2
SYSTEM_CORES=2

# На один юникернел
UNIKERNEL_RAM_MB=64
UNIKERNEL_CORES=1
OVERHEAD_RAM_MB=8

# Доступно
AVAILABLE_RAM_MB=$(( (TOTAL_RAM_GB - SYSTEM_RAM_GB) * 1024 ))
AVAILABLE_CORES=$(( TOTAL_CORES - SYSTEM_CORES ))

# Максимальная плотность
MAX_INSTANCES_RAM=$(( AVAILABLE_RAM_MB / (UNIKERNEL_RAM_MB + OVERHEAD_RAM_MB) ))
MAX_INSTANCES_CORES=$(( AVAILABLE_CORES / UNIKERNEL_CORES ))

# Фактическая (с запасом 20%)
SAFETY_FACTOR=0.8
MAX_INSTANCES=$(( MAX_INSTANCES_RAM < MAX_INSTANCES_CORES ? MAX_INSTANCES_RAM : MAX_INSTANCES_CORES ))
RECOMMENDED_INSTANCES=$(echo "$MAX_INSTANCES * $SAFETY_FACTOR" | bc | cut -d. -f1)

echo "Рекомендуемое количество инстансов: $RECOMMENDED_INSTANCES"
```

## Валидация и проверка работоспособности

- **CPU Pinning:** `virsh vcpupin my-service` — VCPU привязаны.
- **NUMA:** `numastat -p qemu-system-x86_64` — память локальна.
- **HugePages:** `cat /proc/meminfo | grep HugePages` — используются.
- **IOThreads:** `virsh iothreadinfo my-service` — потоки активны.
- **vhost-net:** `ethtool -S tap0 | grep vhost` — активен.
- **Benchmarks:** wrk, iperf3, fio — метрики в пределах SLO.

## Устранение неполадок

| Симптом | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Высокий latency (>1 мс)** | CPU contention, NUMA miss, TCG mode | `kvm_stat`, `numastat`, `dmesg \| grep -i kvm` | CPU pinning, NUMA-aware placement, проверка `/dev/kvm` |
| **Низкая пропускная способность** | vhost-net отключен, multi-queue не настроен | `ethtool -S tap0 \| grep vhost`, `lsmod \| grep vhost` | Включить `vhost-net`, `queues=N` |
| **Высокий steal time (>5%)** | overcommit CPU, noisy neighbor | `top` (col1=`st`), `virsh cpu-stats my-service` | Уменьшить плотность, мигрировать нагрузку |
| **NUMA miss (>50% remote)** | vCPU/RAM на разных NUMA нодах | `numastat -p qemu-system-x86_64` | Перезапустить с `numactl` или XML `<numa>` |
| **HugePages зарезервированы, но не используются** | THP=never не установлен, QEMU не получил hugepages | `cat /proc/meminfo \| grep -E 'HugePages|Transparent'`, `grep -i huge /proc/<qemu-pid>/smaps` | Установить `echo never > /sys/kernel/mm/transparent_hugepage/enabled`, проверить `-memory-backend` |
| **Дисковый I/O ниже ожидаемого** | cache=none/writeback не настроен, IOThreads неактивны | `iostat -x 1`, `virsh iothreadinfo my-service` | Переключить на `cache=writeback`, добавить IOThreads |
| **QEMU работает в TCG (эмуляции)** | Нет VT-x/AMD-V, KVM модуль не загружен | `kvm-ok`, `lsmod \| grep kvm`, `dmesg \| grep -i kvm` | Включить virtualization в BIOS, загрузить `kvm_intel`/`kvm_amd` |
| **Общая деградация под нагрузкой** | Hot CPU, неоптимальный tuned profile | `tuned-adm active`, `mpstat -P ALL 1`, `perf top` | Переключиться на `virtual-host`, проверить `vm.overcommit_memory=0` |

## Лучшие практики

### Подготовка хоста

- **Tuned profile:** Всегда используйте `virtual-host` для KVM-хостов. Profile `throughput-performance` подходит для batch-нагрузок без низкозадержочных требований.
- **Sysctl baseline:** Применяйте параметры из [KVM — host sysctl checklist](../../Linux/Virtualization/kvm/kvm_host_sysctl_checklist.md) как основу. Изменяйте инкрементально и тестируйте.
- **Пакетная установка зависимостей:** Перед установкой `bc` (используется в capacity planning) убедитесь что он присутствует: `apt install bc` / `yum install bc`.

### CPU и память

- **Capacity headroom:** Оставляйте 20–30% резерва CPU и RAM для пиковых нагрузок и миграций. Начинайте с 20–30 юникернелов на хост (16 cores, 32 GB RAM).
- **HugePages:** Используйте 2MB HugePages для ВМ > 4 GB RAM. Для 1GB HugePages требуется явный mlock и поддержка в гостевом ядре.
- **NUMA-first:** Привязывайте vCPU и память к одной NUMA-ноде. Миграция между нодами с разной топологией NUMA может давать латентность +70–130 нс.
- **CPU pinning:** Используйте `host-passthrough` режим. Изолируйте потоки эмуляции (`emulatorpin`) на отдельные ядра от vCPU.

### Сеть и диски

- **vhost-net:** Обязателен для production. Проверяйте `ethtool -S tap0 | grep vhost` после каждого обновления ядра.
- **VirtIO multi-queue:** Для >4 vCPU настройте `queues=N` в XML или QEMU CLI, чтобы распределить обработку прерываний.
- **Дисковый cache:** Используйте `cache=writeback` + `aio=threads`/`io_uring` для production. `cache=none` подходит только если есть внешний UPS и журналирование на хосте отключено.
- **IOThreads:** Для storage-heavy workloads назначайте отдельный IOThread на диск, избегайте shared IOThread для >2 дисков.

### Мониторинг и алертинг

- **Базовые метрики:** `qemu` CPU usage (не host total), `kvm_stat` exits/sec, `numastat` local vs remote, `ethtool -S` vhost packets, `iostat` await.
- **Пороги алертов:** steal time > 5%, NUMA remote > 30%, vhost-net off, HugePages free = 0, QEMU TCG mode.
- **Benchmarking cadence:** Запускайте wrk/iperf3/fio при изменении версии ядра, QEMU, образа юникернела, или после изменения NUMA/pinning конфигурации.

### Безопасность производительности

- **mlock/capabilities:** Убедитесь что QEMU процесс имеет `CAP_IPC_LOCK` и `CAP_SYS_NICE` для стабильной производительности.
- **cgroups blkio:** Ограничивайте I/O на уровне libvirt (`<iotune>`), чтобы предотвратить noisy neighbor.
- **Изменения в production:** Вносите изменения в CPU/memory pinning по одному параметру за раз. Запускайте baseline benchmark до и после, сравнивайте p50/p99 latency.

## Дополнительная информация

### См. также
- [Обзор Unikernel](./unikernel_overview.md)
- [Оркестрация и управление](./orchestration_and_management.md)
- [Мониторинг и алертинг](./monitoring_and_alerting.md)

### Ссылки
- [Оптимизация KVM (2025–2026)](../../Linux/Virtualization/kvm/performance_tuning_2026.md)
- [KVM — мониторинг](../../Linux/Virtualization/kvm/kvm_monitoring.md)
- [KVM — overcommit и capacity planning](../../Linux/Virtualization/kvm/kvm_overcommit_and_capacity.md)
- [KVM — host sysctl checklist](../../Linux/Virtualization/kvm/kvm_host_sysctl_checklist.md)
- [Тестирование производительности](../../Testing/performance_testing_methodology.md)
- [Методология нагрузочного тестирования](../../Testing/k6_load_testing.md)
