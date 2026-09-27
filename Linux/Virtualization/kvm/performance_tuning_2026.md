# Оптимизация производительности KVM (2025–2026)

В данном файле собраны современные методы и архитектурные решения для максимизации производительности гипервизора KVM, актуальные для высоконагруженных систем 2025–2026 годов.

## Определения

**guest_memfd (Guest Memory File Descriptor)** — механизм ядра Linux 6.x+, позволяющий гипервизору управлять памятью гостя через файловые дескрипторы. Это критически важно для **Confidential Computing** (защищенных вычислений), так как позволяет изолировать память гостя от прямого доступа хоста и снизить накладные расходы на управление таблицами страниц.

**Multi-Queue VirtIO (MQ)** — технология параллельной обработки очередей ввода-вывода. Позволяет распределять обработку сетевых пакетов и дисковых запросов между несколькими vCPU, устраняя узкие места на многоядерных системах.

**io_uring** — высокопроизводительный интерфейс асинхронного ввода-вывода в Linux. В KVM используется QEMU для обработки дисковых операций с минимальными задержками и низким потреблением CPU.

**vDPA (VirtIO Data Path Acceleration)** — технология, позволяющая пробрасывать аппаратное ускорение VirtIO (из сетевых карт или контроллеров) напрямую в гостевую ОС, сохраняя стандартный программный интерфейс VirtIO.

**CPU Pinning (Привязка ядер)** — жесткое закрепление виртуальных ядер (vCPU) за физическими ядрами хоста (pCPU) для исключения переключений контекста и повышения предсказуемости задержек.

**vhost-net** — механизм переноса обработки сетевых пакетов VirtIO из userspace (QEMU) напрямую в ядро Linux. Исключает лишние переключения контекста между ядром и пользователем, снижая задержки и нагрузку на CPU.

**vhost-user** — интерфейс взаимодействия QEMU с высокопроизводительными сетевыми стеками в userspace (например, DPDK, OVS-DPDK) через Unix Domain Sockets. Используется для низкозадержочных сетевых workloads.

**KSM (Kernel Samepage Merging)** — механизм ядра Linux, объединяющий одинаковые страницы памяти у нескольких ВМ в одну физическую страницу. Позволяет повысить степень consolidation на перегруженных хостах, но добавляет накладные расходы на сканирование и дедупликацию.

**Transparent Hugepages (THP)** — механизм ядра Linux, автоматически объединяющий стандартные страницы 4KB в Hugepages 2MB в фоновом режиме. Включен по умолчанию, но может вызывать latency spikes при дефрагментации, что недопустимо для баз данных и latency-sensitive workloads.

**IOThreads** — выделенные потоки QEMU для обработки дискового и сетевого ввода-вывода. Позволяют распараллелить обработку запросов, снижая нагрузку на основной поток и уменьшая задержки.

**cgroup blkio** — подсистема cgroup для контроля и ограничения дискового I/O ВМ. Позволяет задавать вес (weight) и абсолютные лимиты (BPS, IOPS) для предотвращения влияния одной ВМ на другие (Noisy Neighbor).

**CPU Quotas/Shares** — механизмы cgroups v2 для управления доступом к CPU. `shares` задает относительный вес при конкуренции, а `quota`/`period` задают абсолютное ограничение в микросекундах.

**Ballooning (Virtio-balloon)** — драйвер, позволяющий гипервизору динамически запрашивать возврат неиспользуемой памяти гостевой ОС для перераспределения между ВМ.

**Memory Hotplug** — возможность увеличивать объем RAM работающей ВМ без перезагрузки. Требует наличия `qemu-guest-agent` и поддержки hotplug в гостевом ядре.

**TCG (Tiny Code Generator)** — режим программной эмуляции QEMU, используемый когда аппаратная виртуализация KVM недоступна. Работает значительно медленнее native execution из-за интерпретации инструкций.

**kvm_stat** — утилита мониторинга событий KVM в реальном времени. Показывает количество выходов (exits), прерываний, MMIO-доступов и других событий, указывая на причины деградации производительности.

**Steal Time** — время, в течение которого виртуальный процессор ожидал физический CPU, пока гипервизор обслуживал другие процессы. Признак перегрузки хоста или агрессивного overcommit.

**Noisy Neighbor** — эффект, при котором одна ВМ на хосте потребляет непропорционально много ресурсов (CPU, дисковый I/O, сеть), ухудшая производительность соседних ВМ.

**cachetune** — механизм управления кэшем L3 для ВМ через libvirt. Позволяет выделить определенный объем кэша конкретной ВМ, снижая interference от других workloads.

**memlock** — ограничение на объем заблокированной в RAM памяти (mlock). Важно для производительных ВМ, так как предотвращает свопинг страниц процесса QEMU.

**QMP (QEMU Machine Protocol)** — JSON-based интерфейс управления QEMU на Unix-сокете или TCP. Используется libvirt и инструментами автоматизации для сбора метрик и изменения конфигурации «на лету».

**emulatorpin** — параметр XML, закрепляющий потоки эмуляции QEMU (таймеры, ACPI, не-VirtIO устройства) за конкретными физическими ядрами хоста. Рекомендуется изолировать их на отдельные ядра от vCPU.

## Основные концепции

### 1. Оптимизация памяти через guest_memfd

Технология `guest_memfd` решает проблему безопасности и производительности в современных средах (Confidential VMs).
- **Эффект:** Снижение накладных расходов на создание и управление `mmap`-областями.
- **Применение:** Автоматически используется в современных дистрибутивах при включении AMD SEV-SNP или Intel TDX.
- **Ограничение:** Требует ядро Linux 6.x+ и поддержки гостевой ОС.

### 2. Масштабирование I/O с Multi-Queue VirtIO

В 2026 году поддержка MQ является стандартом. Для эффективной работы количество очередей должно соответствовать количеству vCPU в гостевой ОС.
- **Сеть:** Позволяет обрабатывать трафик 100GbE+ без перегрузки одного ядра.
- **Диск:** Улучшает IOPS на NVMe-хранилищах за счет параллелизма.
- **Конфигурация:** В XML указывается `queues='N'` в секции `<driver>` диска или интерфейса.

### 3. Динамическая привязка и топология (Dynamic CPU Pinning)

Современные процессоры (AMD EPYC Turin, Intel Granite Rapids) имеют сложную иерархию кэшей и NUMA-узлов.
- **CCD/CCX Awareness:** Привязка vCPU должна учитывать границы Core Complex Die (CCD) на процессорах AMD для минимизации задержек L3-кэша.
- **Scheduler Affinity:** Использование `isolcpus` и `nohz_full` на уровне ядра хоста для полной изоляции ядер, выделенных под ВМ.
- **emulatorpin:** Служебные потоки QEMU следует изолировать на отдельные ядра, не пересекаясь с vCPU.

### 4. Использование Hugepages (1ГБ)

Для ВМ с объемом памяти более 64 ГБ использование Hugepages размером 1 ГБ стало обязательным.
- **Преимущество:** Снижение количества промахов TLB (Translation Lookaside Buffer) на 10–15% в нагруженных базах данных.
- **Важно:** Страницы должны быть зарезервированы при загрузке системы через параметры GRUB.
- **THP vs Hugepages:** Transparent Hugepages (THP) включаются по умолчанию, но их фоновая дефрагментация вызывает latency spikes. Для production баз данных отключайте THP через `transparent_hugepage=never` и используйте явное выделение Hugepages.

### 5. Частотная политика CPU и энергоэффективность

На хостах с высокой нагрузкой виртуализации выбор политики частот напрямую влияет на задержки.
- **`intel_pstate=disable` + `acpi-cpufreq`:** Позволяет ручное управление частотами через `cpufreq`. Требуется для режима `performance` на Intel.
- **`performance`:** Фиксированная максимальная частота. Минимальные задержки, максимальное энергопотребление.
- **`schedutil` / `ondemand`:** Динамическое масштабирование. Предпочтительно для гетерогенных нагрузок, но добавляет джиттер.
- **AMD:** Используйте встроенный `amd-pstate` (active/passive) без отключения.

### 6. Управление памятью: Ballooning и Memory Hotplug

**Virtio-balloon** позволяет динамически перераспределять память между ВМ.
- **Принцип:** Гипервизор «надувает» balloon, заставляя гостевую ОС освободить неиспользуемые страницы.
- **Горячее подключение:** `virsh setmem <domain> <size> --live` увеличивает RAM без перезагрузки (требуется guest-agent).
- **Валидация:** `virsh dommemstat <domain>` показывает `actual`, `rss`, `swap_in`.

### 7. IOThreads и привязка дискового I/O

IOThreads — выделенные потоки QEMU для обработки дисков и сети.
- **Количество потоков:** Рекомендуется 1 поток на 2–4 диска/интерфейса.
- **Привязка:** Через `<iothread>` в XML и `<cputune>` с `<vcpupin>` для привязки потоков к физическим ядрам.
- **Эффект:** Снижение задержек дискового I/O на 20–30% при высокой нагрузке.

### 8. Сетевые режимы кэширования и offloading

Выбор режима кэширования диска влияет на скорость и безопасность.
- **`none` (O_DIRECT):** Прямой ввод-вывод, минуя кэш страниц ядра хоста. Рекомендуется для баз данных.
- **`writeback`:** Данные записываются в кэш хоста и подтверждаются сразу. Высокая скорость, риск потери данных при сбое питания.
- **`writethrough`:** Подтверждение только после физической записи. Максимальная безопасность, низкая скорость.
- **`directsync`:** Компромисс. Использует кэш QEMU, но не кэш страниц ядра.
- **Сетевые offloading:** Включение TSO (TCP Segmentation Offload), GSO (Generic Segmentation Offload) и checksum offloading на virtio-net снижает нагрузку на CPU хоста при передаче пакетов 10/25/100GbE.

### 9. vhost-user и DPDK

Для экстремально низких задержек в сетевом I/O используется vhost-user в связке с DPDK.
- **Принцип:** Обучающий процесс (DPDK) работает в userspace, обмениваясь данными с QEMU через Unix Domain Sockets.
- **Требования:** NIC, поддерживающая DPDK, и выделенные ядра (isolcpus) для DPDK потоков.
- **Сценарии:** High-frequency trading, telecom (5G UPF), high-performance load balancers.

### 10. Живая миграция: оптимизация пропускной способности

Миграция ВМ ограничена пропускной способностью сети между хостами.
- **Auto-converge:** Если guest пишет в память быстрее, чем она передается, гипервизор замедляет vCPU для снижения скорости изменения памяти.
- **Post-copy:** Минимальное downtime, но требует надежной низко задержочной сети.
- **Ограничение полосы:** `virsh migrate --bandwidth <Mbps>` предотвращает насыщение сети.
- **Сжатие:** Начиная с QEMU 6.0, поддерживается сжатие страниц памяти во время миграции (xz/zstd).

### 11. Политики cgroup и предотвращение Noisy Neighbor

- **CPU shares:** Относительный вес (`<shares>`) определяет приоритет ВМ при конкуренции за CPU.
- **CPU quota/period:** Абсолютное ограничение. Например, `quota='50000' period='100000'` = 50% одного ядра.
- **cgroup blkio weight:** Относительный вес для дискового I/O. Значения: 10–1000, по умолчанию 500.
- **blkio BPS/IOPS лимиты:** Абсолютные ограничения через `<iotune>` в XML.

### 12. Политика NUMA и многопроцессорных систем

На чиплетных процессорах (AMD EPYC Turin, Intel Granite Rapids) топология критична.
- **NUMA-узел:** Память должна быть привязана к тому же NUMA-узлу, где находятся vCPU. Используйте `<numatune>`.
- **CCD/CCX:** На AMD привязывайте vCPU к ядрам внутри одного CCD для минимизации задержек L3.
- **lscpu -e:** Определяет топологию физических ядер и дистанции NUMA.
- **numastat -p <PID>:** Проверяет локальность памяти процесса QEMU.

### 13. Мониторинг производительности: kvm_stat и turbostat

**kvm_stat** показывает события KVM в реальном времени:
- **`exits` > 100 000/сек на ядро:** Гость делает слишком много тяжелых системных вызовов. Перейдите на VirtIO или увеличьте количество очередей MQ.
- **`halt_exits`:** Высокое значение говорит о нехватке CPU на хосте. Проверьте overcommit и steal time.
- **`mmio_exits`:** Интенсивный I/O через эмулируемые устройства. Используйте VirtIO вместо эмуляции.

**turbostat** (пакет `linux-tools`):
- Мониторинг частот CPU, состояний C-states и P-states на всех ядрах хоста.
- Выявление нестабильных частот (turbo boost) под нагрузкой.

### 14. Cache Allocation Technology (CAT) и cachetune

Intel RDT (Resource Director Technology) позволяет выделять portions LLC (Last Level Cache) для конкретных ВМ.
- **cachetune:** В libvirt задается через `<cachetune>` с указанием `vcpus`, `cache` и `size` в KB.
- **Эффект:** Снижение cache interference на 15–25% при смешанных workloads на одном хосте.
- **Ограничение:** Требует процессоры Intel Broadwell+ или AMD Zen 3+ с поддержкой RDT.

### 15. Заблокированная память (memlock) и предотвращение свопа

Для latency-sensitive ВМ важно предотвратить свопинг страниц процесса QEMU.
- **Настройка:** `ulimit -l unlimited` для пользователя, запускающего libvirtd, или `LimitMEMLOCK=infinity` в systemd-юните.
- **Проверка:** `cat /proc/<PID>/status | grep VmLocked` показывает объем заблокированной памяти.
- **Эффект:** Исключение задержек при доступе к страницам, выгруженным в swap.

## Практические сценарии

### Сценарий 1: Оптимизация ВМ для высоконагруженной БД (PostgreSQL/Oracle)

Для достижения минимальных задержек (Tail Latency) при работе с памятью и диском:

**1. Настройка Hugepages (хост):**
```bash
# Добавьте в GRUB_CMDLINE_LINUX:
# default_hugepagesz=1G hugepagesz=1G hugepages=128
```

**2. Отключение THP:**
```bash
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
# Постоянно через GRUB:
# transparent_hugepage=never
```

**3. Конфигурация ВМ (XML):**
```xml
<domain type='kvm'>
  <memory unit='GiB'>128</memory>
  <memoryBacking>
    <hugepages/>
    <lock/>
    <source type='memfd'/> <!-- guest_memfd для TDX/SNP -->
  </memoryBacking>
  <vcpu placement='static'>16</vcpu>
  <cputune>
    <vcpupin vcpu='0' cpuset='2'/>
    <vcpupin vcpu='1' cpuset='3'/>
    <!-- ... и так далее для всех vCPU -->
    <emulatorpin cpuset='0-1'/> <!-- Служебные потоки на отдельные ядра -->
  </cputune>
  <cpu mode='host-passthrough'>
    <topology sockets='1' dies='1' clusters='1' cores='8' threads='2'/>
  </cpu>
  <numatune>
    <memory mode='strict' nodeset='0'/>
    <cpus cpuset='2-17' nodeset='0'/>
  </numatune>
  <devices>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' io='io_uring' queues='16' cache='none'/>
      <target dev='vda' bus='virtio'/>
    </disk>
  </devices>
</domain>
```

### Сценарий 2: Настройка сетевой производительности 100GbE

Если ВМ должна обрабатывать огромный поток трафика:

**1. Включение Multi-Queue и vhost (XML):**
```xml
<interface type='bridge'>
  <source bridge='br0'/>
  <model type='virtio'/>
  <driver name='vhost' queues='8'/> <!-- queues = vCPU -->
  <offload>
    <tx offload='tso'/>
    <tx offload='gso'/>
  </offload>
</interface>
```

**2. Настройка внутри гостя (Linux):**
```bash
# Проверка и активация очередей
ethtool -L eth0 combined 8

# Проверка offloading
ethtool -k eth0 | grep -E 'tso|gso|gro'
# → tcp-segmentation-offload: on
# → generic-segmentation-offload: on
```

**3. Для экстремальных задержек — vhost-user с DPDK:**
```bash
# На хосте: запуск OVS-DPDK или VPP с выделенными ядрами
# В XML: <model type='virtio' driver='vhostuser'/>
```

### Сценарий 3: Тюнинг под архитектуру AMD EPYC (NUMA)

Для предотвращения деградации производительности из-за межпроцессорного взаимодействия:

**1. Определение топологии:**
```bash
lscpu -e
# → Выводит: CPU, Core, Socket, Node, L1d, L1i, L2, L3
```

**2. Определение NUMA-дистанций:**
```bash
numactl --hardware
# → node 0 cpus: 0 1 2 3 8 9 10 11
# → node 1 cpus: 4 5 6 7 12 13 14 15
```

**3. Привязка ВМ к одному CCD (XML):**
```xml
<numatune>
  <memory mode='strict' nodeset='0'/>
  <cpus cpuset='0-7' nodeset='0'/>
</numatune>
<cputune>
  <vcpupin vcpu='0' cpuset='0'/>
  <vcpupin vcpu='1' cpuset='1'/>
  <!-- Ядра внутри одного CCD -->
  <emulatorpin cpuset='8-9'/>
</cputune>
```

### Сценарий 4: Настройка IOThreads для дискового I/O

Выделение отдельных потоков для обработки дисковых запросов:

```xml
<domain type='kvm'>
  <iothreads>4</iothreads>
  <cputune>
    <iothreadpin iothread='1' cpuset='4'/>
    <iothreadpin iothread='2' cpuset='5'/>
    <iothreadpin iothread='3' cpuset='6'/>
    <iothreadpin iothread='4' cpuset='7'/>
  </cputune>
  <devices>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' io='io_uring' queues='4' iothread='1'/>
      <target dev='vda' bus='virtio'/>
    </disk>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' io='io_uring' queues='4' iothread='2'/>
      <target dev='vdb' bus='virtio'/>
    </disk>
  </devices>
</domain>
```

**Валидация:**
```bash
# Проверка привязки IOThreads
virsh iothreadinfo web-server-01
# → iothread 1 affinity: 4
# → iothread 2 affinity: 5
```

### Сценарий 5: KSM (Kernel Samepage Merging) для consolidation

При высокой степени consolidation (много одинаковых ВМ) KSM позволяет сэкономить память.

**1. Проверка текущего состояния:**
```bash
cat /sys/kernel/mm/ksm/run
# → 0 (выключен), 1 (включен), 2 (включен + агрессивный режим)
```

**2. Включение и настройка:**
```bash
# Включение KSM
echo 1 | sudo tee /sys/kernel/mm/ksm/run

# Настройка периода сканирования (мс)
echo 100 | sudo tee /sys/kernel/mm/ksm/sleep_millisecs

# Ограничение памяти, занимаемой KSM (страницы)
echo 50000 | sudo tee /sys/kernel/mm/ksm/pages_to_scan
```

**3. Постоянная настройка через systemd:**
```bash
# /etc/systemd/system/ksm.service
[Unit]
Description=Kernel Samepage Merging

[Service]
Type=oneshot
ExecStart=/usr/bin/echo 1 > /sys/kernel/mm/ksm/run
ExecStop=/usr/bin/echo 0 > /sys/kernel/mm/ksm/run

[Install]
WantedBy=multi-user.target
```

**4. Мониторинг экономии:**
```bash
grep -E 'ksm|shared' /proc/meminfo
# → KsmPages: 12345
# → ShmemHugePages: 67890
```

**Важно:** KSM добавляет CPU overhead на сканирование и дедупликацию. Не включайте на хостах с уже высокой нагрузкой.

### Сценарий 6: Настройка частотного governora CPU

Для production-хостов с latency-sensitive ВМ:

**1. Проверка текущего governor:**
```bash
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
# → performance / schedutil / ondemand
```

**2. Установка performance (все ядра):**
```bash
for cpu in /sys/devices/system/cpu/cpu[0-9]*; do
  echo performance | sudo tee "$cpu/cpufreq/scaling_governor"
done
```

**3. Постоянная настройка через tuned:**
```bash
# Установка профиля virtual-host (RHEL/Rocky/Fedora)
sudo tuned-adm profile virtual-host

# Или кастомный профиль
sudo tuned-adm profile custom-virtual
```

**4. Проверка текущих частот:**
```bash
turbostat --show CPU,Avg_MHz
# → Выводит текущую и среднюю частоту каждого ядра
```

### Сценарий 7: cgroup blkio и предотвращение Noisy Neighbor

Ограничение дискового I/O для предотвращения влияния одной ВМ на другие:

**1. Через XML (persistent):**
```xml
<disk type='file' device='disk'>
  <driver name='qemu' type='qcow2' io='io_uring' queues='4'/>
  <source file='/var/lib/libvirt/images/web-server-01.qcow2'/>
  <target dev='vda' bus='virtio'/>
  <iotune>
    <read_bytes_sec>10485760</read_bytes_sec>      <!-- 10 MB/s -->
    <write_bytes_sec>5242880</write_bytes_sec>     <!-- 5 MB/s -->
    <read_iops_sec>1000</read_iops_sec>
    <write_iops_sec>500</write_iops_sec>
  </iotune>
</disk>
```

**2. Через virsh (runtime):**
```bash
# Установка веса (relative weight 10-1000, default 500)
virsh blkiotune web-server-01 --weight 800

# Установка абсолютных лимитов
virsh blkiotune web-server-01 --read_bytes_sec 10485760 --write_bytes_sec 5242880
```

**3. Проверка текущих лимитов:**
```bash
virsh blkiotune web-server-01
# → read_bytes_sec: 10485760
# → write_bytes_sec: 5242880
```

### Сценарий 8: vhost-user с DPDK для низкозадержочной сети

Настройка высокопроизводительного сетевого стека в userspace:

**1. Установка DPDK и выделение огромных страниц:**
```bash
# Резервирование 1GB hugepages
echo 4 | sudo tee /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages

# Загрузка модуля vfio-pci
sudo modprobe vfio-pci
```

**2. Конфигурация OVS-DPDK (на хосте):**
```bash
ovs-vsctl -- add-br ovs-br0 -- set bridge ovs-br0 datapath_type=netdev
ovs-vsctl add-port ovs-br0 dpdk0 -- set Interface dpdk0 type=dpdk
```

**3. XML-конфигурация ВМ:**
```xml
<interface type='vhostuser'>
  <mac address='52:54:00:xx:xx:xx'/>
  <source type='unix' path='/var/run/openvswitch/vhost-user-0' mode='client'/>
  <model type='virtio'/>
  <driver name='vhostuser' queues='4'/>
</interface>
```

**4. Внутри гостя:**
```bash
# Установка DPDK и запуск testpmd
dpdk-testpmd -l 0-3 -n 4 -- --port-topology=chained --forward-mode=io
```

### Сценарий 9: Оптимизация живой миграции (Live Migration)

Для минимизации downtime и потерь производительности при миграции:

**1. Базовая миграция с auto-converge:**
```bash
virsh migrate --live --auto-converge --bandwidth 1000 \
  web-server-01 qemu+ssh://dest-host/system
```

**2. Post-copy для активных ВМ (высокий memory write rate):**
```bash
virsh migrate --live --postcopy --verbose \
  web-server-01 qemu+ssh://dest-host/system
```

**3. Включение сжатия (QEMU 6.0+):**
```xml
<domain type='kvm'>
  <migration>
    <postcopy enable='yes'/>
    <compress xbzrle='yes' zstd='yes'/>
  </migration>
</domain>
```

**4. Мониторинг прогресса миграции:**
```bash
# На целевом хосте
virsh domjobinfo web-server-01
# → Time remaining: 12.3 seconds
# → Memory processed: 8.5 GiB / 16.0 GiB
```

### Сценарий 10: Анализ производительности через kvm_stat

Выявление причин деградации производительности без доступа к гостю:

**1. Сбор статистики в реальном времени:**
```bash
sudo kvm_stat -1 5
# → Снимок каждые 5 секунд
```

**2. Ключевые метрики:**
```
exits          1234567   # Всего выходов из гостевого режима
halt_exits     543210    # Выходы из idle — ожидание
mmio_exits     12345     # Доступ к MMIO — эмулируемые устройства
ept_mis        98765     # Промахи EPT/NPT — TLB miss
```

**3. Интерпретация:**
- **`exits` > 100 000/сек на ядро:** Гость выполняет слишком много тяжелых системных вызовов. Используйте VirtIO или увеличьте MQ очереди.
- **`halt_exits` > 50 000/сек:** Планировщик хоста не дает ВМ достаточно CPU. Проверьте overcommit и steal time.
- **`mmio_exits` > 10 000/сек:** Интенсивный I/O через эмулируемые устройства. Перейдите на VirtIO.

**4. Дифференциальный анализ:**
```bash
# Снимок до и после нагрузки, сравнение
sudo kvm_stat -c 10 > before.txt
# ... нагружаем ВМ ...
sudo kvm_stat -c 10 > after.txt
diff before.txt after.txt
```

### Сценарий 11: Настройка CPU Quotas и Shares для fair scheduling

Контроль распределения CPU между ВМ:

**1. XML-конфигурация:**
```xml
<domain type='kvm'>
  <vcpu placement='static'>8</vcpu>
  <cputune>
    <shares>2048</shares> <!-- Относительный вес (default 1024) -->
    <quota>50000</quota>   <!-- 50% одного ядра за период -->
    <period>100000</period> <!-- 100ms период -->
    <vcpupin vcpu='0' cpuset='2'/>
    <!-- ... -->
  </cputune>
</domain>
```

**2. Runtime-настройка через virsh:**
```bash
# Изменение shares (без перезагрузки ВМ)
virsh schedinfo web-server-01 --set vcpu_shares=2048

# Изменение quota/period
virsh schedinfo web-server-01 --set vcpu_quota=50000 --set vcpu_period=100000
```

**3. Проверка:**
```bash
virsh schedinfo web-server-01
# → vcpu_shares: 2048
# → vcpu_quota: 50000
# → vcpu_period: 100000
```

### Сценарий 12: Включение memlock для предотвращения свопа

Для latency-sensitive ВМ важно предотвратить свопинг страниц процесса QEMU:

**1. Проверка текущего лимита:**
```bash
cat /proc/$(pgrep -f qemu-system)/limits | grep "Max locked memory"
# → Max locked memory: unlimited unlimited
```

**2. Настройка через systemd (RHEL/Fedora):**
```bash
# /etc/systemd/system/libvirtd.service.d/override.conf
[Service]
LimitMEMLOCK=infinity
```

**3. Настройка через systemd (Ubuntu/Debian):**
```bash
# /etc/systemd/system/libvirtd.service.d/override.conf
[Service]
LimitMEMLOCK=infinity
```

**4. Применение:**
```bash
sudo systemctl daemon-reload
sudo systemctl restart libvirtd
```

**5. Проверка:**
```bash
cat /proc/$(pgrep -f qemu-system)/status | grep VmLocked
# → VmLocked: 134217728  (заблокировано 128 MB)
```

### Сценарий 13: Мониторинг через QMP (QEMU Machine Protocol)

Сбор метрик напрямую из QEMU без libvirt:

**1. Подключение к сокету:**
```bash
SOCK="/var/run/libvirt/qemu/web-server-01.sock"
echo '{"execute": "qmp_capabilities"}' | sudo socat - "$SOCK"
echo '{"execute": "query-status"}' | sudo socat - "$SOCK"
```

**2. Сбор метрик:**
```bash
# CPU usage
echo '{"execute": "query-cpus-fast"}' | sudo socat - "$SOCK"

# Block devices
echo '{"execute": "query-block"}' | sudo socat - "$SOCK"

# Block stats (IOPS, bytes)
echo '{"execute": "query-blockstats"}' | sudo socat - "$SOCK"
```

**3. Изменение конфигурации «на лету»:**
```bash
# Включение throttling без перезагрузки ВМ
echo '{"execute": "block-set-io-throttle", "arguments": {"node-name": "drive-virtio-disk0", "bps": 10485760, "iops": 1000}}' | sudo socat - "$SOCK"
```

### Сценарий 14: cachetune для AMD Zen 3+ / Intel RDT

Выделение кэша L3 для критичных ВМ:

**1. Проверка поддержки RDT:**
```bash
cat /sys/fs/resctrl/cpuset/cpus
# → Если директория существует, RDT поддерживается
```

**2. XML-конфигурация (Intel RDT / AMD Zen 3+):**
```xml
<domain type='kvm'>
  <cputune>
    <vcpupin vcpu='0' cpuset='0'/>
    <!-- ... -->
  </cputune>
  <cachetune>
    <cache cpus='0-3' type='l3' size='4' unit='MiB'/>
  </cachetune>
</domain>
```

**3. Проверка:**
```bash
# Просмотр текущего распределения кэша
cat /sys/fs/resctrl/Intel_RDTL3_Cache/mon_l3_00/mon
```

### Сценарий 15: Проверка и отключение Transparent Hugepages

Для баз данных и приложений с требованием к минимальным задержкам THP должен быть отключен.

**1. Текущий режим THP:**
```bash
cat /sys/kernel/mm/transparent_hugepage/enabled
# → [always] madvise never
```

**2. Отключение THP (до перезагрузки):**
```bash
echo madvise | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
```

**3. Постоянное отключение через GRUB:**
```bash
echo 'transparent_hugepage=never' | sudo tee -a /etc/default/grub.d/99-thp.cfg
sudo update-grub  # Ubuntu/Debian
# sudo grub2-mkconfig -o /boot/grub2/grub.cfg  # RHEL/Rocky
```

### Сценарий 16: Идемпотентный скрипт проверки здоровья (DevOps/SRE)

Скрипт для автоматизированных систем мониторинга (Prometheus node_exporter, Ansible, SaltStack). Возвращает 0, если все проверки пройдены.

```bash
#!/bin/bash
# kvm-healthcheck.sh — проверка здоровья KVM-хоста
set -euo pipefail

ERRORS=0

check() {
  local name="$1"
  local cmd="$2"
  local expected="$3"
  if eval "$cmd" | grep -qE "$expected"; then
    echo "[OK]   $name"
  else
    echo "[FAIL] $name"
    ERRORS=$((ERRORS + 1))
  fi
}

check "KVM module loaded" "lsmod | grep -E 'kvm_(intel|amd)'" "kvm_(intel|amd)"
check "/dev/kvm exists" "ls -la /dev/kvm" "crw-rw----"
check "libvirtd active" "systemctl is-active libvirtd" "active"
check "virtlogd active" "systemctl is-active virtlogd" "active"
check "virtlockd active" "systemctl is-active virtlockd" "active"
check "libvirt URI" "virsh uri" "qemu:///system"
check "default pool active" "virsh pool-list --all" "default.*active"
check "default network active" "virsh net-list --all" "default.*active"
check "User in kvm/libvirt groups" "groups" "(kvm|libvirt)"

# Проверка OOM за последний час
if dmesg | grep -qi "out of memory"; then
  echo "[WARN] OOM events detected in dmesg"
  ERRORS=$((ERRORS + 1))
fi

# Проверка места на пуле хранилища
POOL_USAGE=$(df -h /var/lib/libvirt/images | awk 'NR==2 {print $5}' | tr -d '%')
if [ "$POOL_USAGE" -gt 90 ]; then
  echo "[WARN] Storage pool usage critical: ${POOL_USAGE}%"
  ERRORS=$((ERRORS + 1))
fi

# Проверка THP (должен быть отключен для production)
THP=$(cat /sys/kernel/mm/transparent_hugepage/enabled)
if [[ "$THP" == *"[always]"* ]]; then
  echo "[WARN] Transparent Hugepages enabled"
  ERRORS=$((ERRORS + 1))
fi

# Проверка steal time (Noisy Neighbor)
STEAL=$(virsh domstats --cpu-total --block-total --net-total 2>/dev/null | grep cpu.time | awk '{print $2}' || echo "0")
if [ -n "$STEAL" ] && [ "$STEAL" -gt 1000000 ]; then
  echo "[WARN] High steal time detected: $STEAL"
  ERRORS=$((ERRORS + 1))
fi

if [ "$ERRORS" -gt 0 ]; then
  echo "Health check FAILED: $ERRORS issues found"
  exit 1
else
  echo "Health check PASSED"
  exit 0
fi
```

### Сценарий 17: Бенчмарк производительности ВМ (fio, sysbench, iperf3)

Измерение реальной производительности ВМ перед запуском production-нагрузки.

**1. Дисковый бенчмарк (fio):**
```bash
# Sequential read (симуляция загрузки образа ВМ)
fio --name=seq-read --directory=/var/lib/libvirt/images \
  --rw=read --bs=1M --size=1G --numjobs=4 --runtime=30 \
  --group_reporting --output-format=json

# Random write (симуляция работы БД)
fio --name=rand-write --directory=/var/lib/libvirt/images \
  --rw=randwrite --bs=4k --size=256M --numjobs=8 \
  --runtime=60 --group_reporting --iodepth=32 \
  --output-format=json

# Mixed random read/write (типичная нагрузка ВМ)
fio --name=mixed --directory=/var/lib/libvirt/images \
  --rw=randrw --bs=4k --size=256M --numjobs=4 \
  --runtime=60 --group_reporting --iodepth=16 \
  --rwmixread=70 --output-format=json
```

**2. CPU бенчмарк (sysbench):**
```bash
# Single-thread CPU test
sysbench cpu --threads=1 --time=30 run

# Multi-thread CPU test (все vCPU)
sysbench cpu --threads=$(nproc) --time=30 run

# Memory test
sysbench memory --memory-block-size=1M --memory-total-size=10G run
```

**3. Сетевой бенчмарк (iperf3):**
```bash
# На хосте (сервер)
iperf3 -s

# Внутри ВМ (клиент)
iperf3 -c 192.168.122.1 -t 30 -P 4  # 4 parallel streams

# UDP test (для latency-sensitive)
iperf3 -c 192.168.122.1 -u -b 1G -t 30
```

**4. Сравнение производительности до/после оптимизации:**
```bash
# Baseline (до оптимизации)
fio --name=baseline --directory=/var/lib/libvirt/images \
  --rw=randread --bs=4k --size=256M --numjobs=4 --runtime=30 \
  --group_reporting --output=baseline.json

# После оптимизации (io_uring, MQ, pinning)
fio --name=optimized --directory=/var/lib/libvirt/images \
  --rw=randread --bs=4k --size=256M --numjobs=4 --runtime=30 \
  --group_reporting --output=optimized.json

# Сравнение
fio_verify_baseline baseline.json optimized.json
```

### Сценарий 18: Swap для KVM-хостов

Настройка swap для предотвращения OOM killer при временных всплесках нагрузки.

**1. Создание swap-файла:**
```bash
# Создание 8 GB swap
sudo fallocate -l 8G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Постоянное включение
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

**2. Настройка swappiness:**
```bash
# Проверка текущего значения
cat /proc/sys/vm/swappiness
# → 60

# Для KVM-хостов рекомендуется 1-10
sudo sysctl vm.swappiness=1

# Постоянно
echo 'vm.swappiness = 1' | sudo tee -a /etc/sysctl.d/99-kvm.conf
```

**3. Zswap (компрессия swap):**
```bash
# Включение zswap
sudo modprobe zswap
echo 1 | sudo tee /sys/module/zswap/parameters/enabled

# Выбор алгоритма сжатия
echo lz4hc | sudo tee /sys/module/zswap/parameters/compressor
```

**4. Swap для конкретных ВМ (XML):**
```xml
<domain type='kvm'>
  <memory unit='GiB'>16</memory>
  <memoryBacking>
    <swap>
      <file path='/var/lib/libvirt/images/swap-${VM_NAME}.swap' size='4'/>
    </swap>
  </memoryBacking>
</domain>
```

**Правила для KVM:**
- swappiness=1 для production хостов (minimize swap)
- swappiness=10 для development хостов
- Отключите swap для latency-sensitive ВМ (БД, cache)
- Включите zswap для компрессии (экономия 30-50% swap)
- Мониторьте `vmstat 1` — колонка `si/so` (swap in/out) должна быть 0

### Сценарий 19: Восстановление после сбоев (Rollback)

**Откат обновления libvirt/QEMU:**
```bash
# Если после обновления ВМ не стартуют, откатите пакеты:
# Debian/Ubuntu
apt install --reinstall -y qemu-system-x86=1:7.2.* libvirt-daemon-system=8.0.*

# RHEL/Rocky
dnf downgrade qemu-kvm libvirt

# После отката проверьте ВМ
virsh list --all
```

**Восстановление из резервной копии:**
```bash
# 1. Остановите проблемную ВМ
virsh destroy web-server-01

# 2. Восстановите диск из бэкапа
virsh vol-delete web-server-01.qcow2 --pool default
virsh vol-create-from default web-server-01.qcow2 /backup/vms/web-server-01.qcow2 --pool default

# 3. Переопределите ВМ (если потеряна конфигурация)
virsh define /backup/vms/web-server-01.xml

# 4. Запустите
virsh start web-server-01
```

**Очистка зависших lock-файлов после сбоя:**
```bash
# Только если Вы уверены, что ВМ не работает на других хостах!
find /var/run/libvirt/lock/ -name "*.lock" -mtime +1 -exec rm -v {} \;
```

## Дополнительная информация

- [KVM — Обзор и архитектура](./overview.md) — базовые принципы и компоненты.
- [KVM — Управление через virsh](./management.md) — жизненный цикл ВМ и автоматизация.
- [KVM — Решение проблем (Troubleshooting)](./troubleshooting.md) — диагностика производительности и ошибок.
- [KVM — Установка и настройка](./installation.md) — параметры ядра хоста, sVirt, firewall.
- [Вложенная виртуализация (Nested)](../nested_virtualization/practical_scenarios.md) — накладные расходы и оптимизация вложенных сред.
- [Образы ВМ — Форматы и утилиты](../vm_images/definitions.md) — qcow2, CoW, QGA и конвертация.
- [Образы ВМ — Основные концепции](../vm_images/basic_concepts.md) — стратегии хранения, кэширование и TRIM.
- [Виртуализация: Обзор](../virtualization_overview.md) — типы гипервизоров, привилегированные кольца.
- [Безопасность: SELinux](../../Security/Mechanisms/SELinux.md) — подробнее о метках и sVirt.
- [Linux Bridge: Концепции](../../Networking/Concepts/linux_bridge.md) — архитектура L2-сетей.
- [Выбор конфигурации CPU: NUMA и топология](../../../Linux/Core/cpu_selection.md) — NUMA, CCD, CXL и рекомендации для систем 2025–2026.
- [Мониторинг производительности: Tail Latency](../../../Testing/performance_testing_methodology.md) — методология тестирования и SLI.
- [Overcommit и планирование ресурсов](./kvm_overcommit_and_capacity.md) — CPU/RAM overcommit, расчёт ratio.
- [Сетевые основы KVM](./kvm_networking_fundamentals.md) — dnsmasq, nwfilter, port forwarding.
