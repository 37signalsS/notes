# Вложенная виртуализация — Дополнительная информация

В данном файле собраны углубленные сведения об архитектурных оптимизациях, производительности, безопасности и альтернативных решениях для вложенной виртуализации по состоянию на 2026 год.

## Определения

**Конфиденциальные вычисления (Confidential Computing)** — технологии аппаратной изоляции (Intel TDX, AMD SEV-SNP), позволяющие защитить данные ВМ от компрометации на уровне гипервизора или хоста.

**Shadow Page Tables (Теневые таблицы страниц)** — программный метод эмуляции управления памятью гостя, имеющий высокие накладные расходы. В современных системах заменен на **Virtual EPT/NPT**.

**guest_memfd** — специализированный механизм ядра Linux для управления памятью гостя через файловые дескрипторы, исключающий отображение защищенной памяти в пространство пользователя хоста.

**vCPU ASIDs (Address Space Identifiers)** — аппаратные идентификаторы, позволяющие гипервизору L0 сохранять кэши TLB для разных L1/L2 гостевых пространств без полной сброски (flush) при переключении контекста. Критичны для производительности вложенных сред.

**virtio-forwarding** — механизм перенаправления прерываний и устройств VirtIO из L1 в L2 без участия L0. Снижает количество VM-Exits в L0 при работе L2 с устройствами.

**Overcommit (Превышение гарантий)** — выделение виртуальных ресурсов (CPU, RAM) ВМ в объеме, превышающем физические ресурсы хоста. Во вложенных средах overcommit на L0 напрямую ограничивает максимальный overcommit на L1.

## Основные концепции

### Архитектурные оптимизации и производительность (2026)

В 2026 году налог на вложенность (nested tax) значительно снизился благодаря зрелости аппаратных расширений и оптимизациям в ядре Linux (6.15+).

| Метрика | Оверхед L1 (vs Bare Metal) | Оверхед L2 (Nested vs L1) | Технология оптимизации |
| :--- | :--- | :--- | :--- |
| **CPU (Вычисления)** | 1–2% | 5–8% | VMCS Shadowing, FEAT_NV2 |
| **Память (Latency)** | 3–5% | 10–12% | Virtual EPT, guest_memfd |
| **Сетевой ввод-вывод** | 5–7% | 12–18% | Posted Interrupts, vCPU ASIDs |

**Ключевые факторы ускорения:**
- **VMCS Shadowing (Intel) / SVM Optimization (AMD):** Позволяет гостевому гипервизору (L1) изменять структуры управления вложенным гостем (L2) без обязательного перехвата управления основным гипервизором (L0).
- **Virtual EPT (Nested EPT):** Основной гипервизор (L0) напрямую обрабатывает промахи страниц L2, сокращая количество «цепочек выходов» (VM-Exit chains).
- **guest_memfd:** Радикально ускоряет обработку Page Faults в защищенных вложенных средах (TDX/SNP), снижая задержки на 20–30%.

### Безопасность и Confidential Computing

Вложенная виртуализация традиционно расширяла поверхность атаки, но внедрение технологий Confidential Computing в 2025–2026 годах изменило парадигму:

1.  **Intel TDX Partitioning:** Позволяет разделять доверенный домен (Trust Domain) L1 на изолированные партиции для запуска L2-гостей с аппаратной защитой целостности и шифрованием памяти.
2.  **AMD SEV-SNP RMP:** Reverse Map Table обеспечивает защиту от атак на подмену страниц памяти (Remapping) даже в многоуровневых средах.
  3.  **Изоляция процессов:** На хосте (L0) каждый процесс QEMU/KVM, исполняющий L1, должен быть ограничен через **SELinux/AppArmor** (sVirt), чтобы минимизировать риски при успешном «побеге» (VM Escape) из L2 в L1.

### NUMA и топология CPU во вложенных средах

Вложенная виртуализация усложняет управление топологией, так как каждый уровень добавляет свой слой виртуализации ресурсов:

1.  **L0 → L1:** Планировщик хоста должен учитывать NUMA-узел, на котором размещена ВМ L1. Если L1 размещена на узле 0, а её vCPU привязаны к ядрам узла 1, происходит межъузловой трафик (через UPI/QPI), добавляющий задержки 30–50 нс на каждый доступ к памяти.
2.  **L1 → L2:** Гипервизор L1 может не иметь полной информации о топологии L0. Поэтому привязка vCPU L2 должна выполняться с учетом физических ядер, назначенных L1 на хосте.
3.  **CCD/CCX Awareness:** На процессорах AMD EPYC (Zen 3/4/5) и Intel Granite Rapids привязка vCPU должна учитывать границы Core Complex Die. Для L1 это означает размещение всех её vCPU внутри одного CCD; для L2 — размещение внутри одного физического ядра L1.

**Практические рекомендации:**
- Используйте `<numatune>` в XML L1 для привязки памяти и vCPU к одному NUMA-узлу L0.
- В L1 используйте `<cputune>` с `<vcpupin>` для явного закрепления vCPU L2 за физическими ядрами, выделенными L1.
- Для гетерогенных хостов (mixed CCD sizes) используйте `lscpu -e` и `numactl --hardware` для построения карты топологии.

### Управление памятью в многоуровневых средах

Память во вложенных средах имеет каскадный эффект: ограничения и настройки L0 напрямую влияют на L1, которые в свою очередь влияют на L2:

1.  **Ballooning в L1:** Драйвер `virtio-balloon` в L1 запрашивает возврат неиспользуемой памяти у L0. Это уменьшает объем RAM, доступного для L2. Для production-сред с L2 рекомендуется отключить ballooning в L1 или установить минимальный порог.
2.  **KSM (Kernel Samepage Merging):** На уровне L0 KSM может объединять одинаковые страницы у разных ВМ L1. Однако KSM не работает между L2-гостями, запущенными в разных L1. Для consolidation на уровне L2 используйте гостевые механизмы (например, `virtio-balloon` сdeflation).
3.  **Hugepages:** Резервирование Hugepages на L0 для L1 должно учитывать не только потребности L1, но и ожидаемое количество/размер L2. При использовании 1GB Hugepages для L2, L1 должна иметь достаточный запас.
4.  **Overcommit:** Overcommit памяти на L0 (через `virsh setmem --live`) снижает объем памяти, доступной L1, что может привести к OOM-kill L2. Рекомендуется мониторить `steal_time` и `actual` через `virsh domstats`.

**Валидация:**
```bash
# Проверка фактического использования памяти L1
virsh domstats l1-vm --cpu-total --memory
# → balloon.actual: 8388608
# → balloon.current: 10737418240

# Проверка KSM на L0
cat /sys/kernel/mm/ksm/run
# → 1 (включен)
```

### Хранение и бэкенды для L2

Выбор бэкенда хранения на каждом уровне влияет на производительность L2:

1.  **L0 → L1:** Для дисков L1 рекомендуется использовать **raw** или **qcow2 с предварительным выделением** (`preallocation=metadata` или `falloc`), чтобы избежать фрагментации. Кэширование на L0 должно быть установлено в `none` (O_DIRECT) для дисков L1, если L1 использует собственный кэш.
2.  **L1 → L2:** Внутри L1 диски L2 должны использовать **io_uring** и **Multi-Queue VirtIO**. Кэш на уровне L1 для дисков L2 должен быть `none` или `directsync`, чтобы избежать двойного кэширования.
3.  **Формат диска L2:** `qcow2` удобен для snapshots, но добавляет накладные расходы на decompression. Для production L2 с высокой нагрузкой используйте **raw** или **qcow2 с `preallocation=full`**.
4.  **Throttling:** На L0 можно ограничить дисковый I/O L1 через `<iotune>`. Это предотвращает Noisy Neighbor эффект, который влияет на все L2 внутри L1.

**XML-пример (диск L2 внутри L1):**
```xml
<disk type='file' device='disk'>
  <driver name='qemu' type='qcow2' io='io_uring' queues='4' cache='none'/>
  <source file='/var/lib/libvirt/images/l2-disk.qcow2'/>
  <target dev='vda' bus='virtio'/>
</disk>
```

## Практические сценарии

### Сценарий 1: Мониторинг и профилирование вложенных сред

Для глубокого анализа производительности вложенных систем используйте инструменты трассировки на хосте (L0).

**Анализ VM-Exits:**
```bash
# Просмотр статистики выходов в реальном времени
sudo kvm_stat

# Трассировка конкретных типов выходов (напр. из-за ввода-вывода)
sudo perf kvm stat live --component vmexits
```

**Профилирование задержек:**
Используйте `ebpf` скрипты для замера времени, проводимого в контексте L1 и L2:
```bash
# Пример использования инструмента из bcc-tools (если установлен)
sudo kvmexit.py -p <L1_PID>
```

### Сценарий 2: Валидация работоспособности на всех уровнях (L0 → L1 → L2)

Перед использованием вложенной виртуализации в production выполните проверку на каждом уровне:

**Шаг 1: L0 (Физический хост)**
```bash
# Проверка аппаратной поддержки
egrep -c '(vmx|svm)' /proc/cpuinfo
# → > 0

# Проверка включенности вложенности
cat /sys/module/kvm_intel/parameters/nested
# → Y

# Проверка IOMMU
dmesg | grep -iE 'DMAR|IOMMU'
# → DMAR: IOMMU enabled
```

**Шаг 2: L1 (Гипервизор внутри ВМ)**
```bash
# Внутри ВМ L1
egrep -c '(vmx|svm)' /proc/cpuinfo
# → > 0 (флаги проброшены из L0)

# Проверка загрузки модуля KVM
lsmod | grep kvm
# → kvm_intel (или kvm_amd)

# Проверка режима CPU
virsh cpu-baseline l1-vm 2>/dev/null || echo "host-passthrough confirmed via cpu-baseline"
```

**Шаг 3: L2 (Вложенный гость)**
```bash
# Внутри ВМ L2
egrep -c '(vmx|svm)' /proc/cpuinfo || grep -c 'virt' /proc/cpuinfo
# → > 0

# Проверка работы KVM
sudo dmesg | grep -i kvm
# → kvm: Nested Virtualization enabled

# Запуск тестовой ВМ L3 (опционально)
sudo virt-install --name l3-test --memory 512 --vcpus 1 \
  --disk size=5 --os-variant ubuntu22.04 \
  --network network=default --nographics
```

### Сценарий 3: Диагностика и решение проблем вложенных сред

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| L2 не запускается, L1 имеет флаги VT | CPU mode L1 не `host-passthrough` | Измените `<cpu mode='host-passthrough'>` в XML L1. |
| Производительность L2 в 2–3 раза ниже L1 | Отсутствует VMCS Shadowing или Virtual EPT | Проверьте поддержку в ядре L0 (6.12+), обновите прошивку L0. |
| Сеть L2 недоступна, L1 работает | Блокировка MAC на уровне L1 или L0 | Включите `promiscuous mode` на бридже L1 и убедитесь, что L0 разрешает MAC spoofing. |
| L2 видит меньше vCPU, чем выделено | L1 не имеет достаточного количества pCPU | Увеличьте vCPU L1 или улучшите пиннинг на L0. |
| OOM-kill L2 при наличии свободной памяти | Ballooning в L1 уменьшил доступную память | Отключите ballooning в L1 или увеличьте maxmem. |
| `kvm: Nested Virtualization disabled` | Вложенность выключена в BIOS/UEFI L0 | Включите VT-x/AMD-V в прошивке. |
| Высокий `halt_exits` на L0 | L1 активно потребляет CPU, starving L2 | Проверьте `virsh domstats` L1, уменьшите overcommit. |
| `VMX disabled by BIOS` в логах L1 | BIOS L0 блокирует VT-x | Включите virtualization extensions в BIOS. |

### Сценарий 4: Конфигурация хранилища для L2

Для минимальных задержек при работе с дисками L2 используйте следующие параметры:

**XML-конфигурация L1 (оптимизировано для L2):**
```xml
<domain type='kvm'>
  <name>l1-hypervisor</name>
  <memory unit='GiB'>16</memory>
  <vcpu placement='static'>8</vcpu>
  <cputune>
    <vcpupin vcpu='0' cpuset='2'/>
    <vcpupin vcpu='1' cpuset='3'/>
    <emulatorpin cpuset='0-1'/>
  </cputune>
  <numatune>
    <memory mode='strict' nodeset='0'/>
    <cpus cpuset='2-9' nodeset='0'/>
  </numatune>
  <devices>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' io='io_uring' queues='4' cache='none'/>
      <source file='/var/lib/libvirt/images/l1-root.qcow2'/>
      <target dev='vda' bus='virtio'/>
    </disk>
  </devices>
</domain>
```

**XML-конфигурация L2 внутри L1:**
```xml
<domain type='kvm'>
  <name>l2-guest</name>
  <memory unit='GiB'>4</memory>
  <vcpu placement='static'>2</vcpu>
  <cputune>
    <vcpupin vcpu='0' cpuset='4'/>
    <vcpupin vcpu='1' cpuset='5'/>
  </cputune>
  <devices>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2' io='io_uring' queues='2' cache='none'/>
      <source file='/var/lib/libvirt/images/l2-disk.qcow2'/>
      <target dev='vda' bus='virtio'/>
    </disk>
    <interface type='bridge'>
      <source bridge='br-l1'/>
      <model type='virtio'/>
      <driver name='vhost' queues='2'/>
    </interface>
  </devices>
</domain>
```

**Валидация:**
```bash
# Проверка режима кэширования диска L1
virsh dumpxml l1-hypervisor | grep -A2 "<driver name='qemu'"
# → io='io_uring' queues='4' cache='none'

# Проверка очередей внутри L1
cat /sys/block/vda/queue/nr_requests
# → 128 (оптимально для SSD)
```

### Сценарий 5: Ограничение ресурсов L1 и L2 через cgroups

На уровне L0 используйте cgroups для предотвращения влияния L1 на другие ВМ:

**1. Ограничение CPU для L1:**
```bash
# Установка shares (относительный вес)
virsh schedinfo l1-hypervisor --set vcpu_shares=2048

# Установка quota (абсолютный лимит)
virsh schedinfo l1-hypervisor --set vcpu_quota=80000 --set vcpu_period=100000
# → 80% одного ядра за период 100ms
```

**2. Ограничение дискового I/O для L1:**
```bash
virsh blkiotune l1-hypervisor --weight 800
virsh blkiotune l1-hypervisor --read_bytes_sec 10485760 --write_bytes_sec 5242880
```

**3. Внутри L1:** Настройте аналогичные лимиты для L2, чтобы предотвратить влияние L2 на L1 и другие гостевые ВМ.

**Валидация:**
```bash
virsh schedinfo l1-hypervisor
# → vcpu_shares: 2048
# → vcpu_quota: 80000

virsh blkiotune l1-hypervisor
# → weight: 800
# → read_bytes_sec: 10485760
```

### Сценарий 6: Жесткая изоляция и безопасность L1

Каждый процесс QEMU, исполняющий L1, должен быть изолирован на L0 для минимизации рисков при VM Escape:

**1. Проверка sVirt (SELinux) на L0:**
```bash
# Проверка статуса SELinux
getenforce
# → Enforcing

# Проверка меток процессов L1
ps -eZ | grep qemu
# → system_u:system_r:svirt_t:s0:c123,c456 (уникальная метка на ВМ)
```

**2. Проверка AppArmor на L0 (Ubuntu/Debian):**
```bash
# Проверка загруженных профилей
sudo aa-status | grep qemu
# → /usr/bin/qemu-system-x86_64 (enforced)

# Проверка логов AppArmor
sudo dmesg | grep -i apparmor | grep DENIED
```

**3. Рекомендации по конфигурации:**
- Убедитесь, что SELinux/AppArmor активен на L0 в режиме `Enforcing`/`enforced`.
- Не отключайте sVirt для production-сред. Для debugging используйте `permissive` временно.
- На уровне L1 аналогично изолируйте процессы L2 через sVirt/AppArmor.
- Включите **IOMMU** (`intel_iommu=on iommu=pt` или `amd_iommu=on iommu=pt`) для защиты от DMA-атак через проброшенные устройства.

**4. Чеклист безопасности L1:**
```bash
# IOMMU активен
dmesg | grep -iE 'DMAR|IOMMU'
# → DMAR: IOMMU enabled

# VT-d/AMD-Vi работает
lspci -v | grep -i "Intel Corporation Device [01]38" || lspci -v | grep -i "AMD IOMMU"
```

## Дополнительная информация

### Сетевые оптимизации и MTU

Для минимизации задержек в L2 рекомендуется:
1.  **Multi-queue VirtIO:** Включите многопоточность для сетевых интерфейсов на всех уровнях (L1 и L2).
2.  **MTU Management:** При использовании оверлейных сетей (Geneve/VXLAN) в L1, установите MTU в L2 на уровне **1400–1450**, чтобы избежать фрагментации пакетов на физическом интерфейсе L0.
3.  **Posted Interrupts:** Убедитесь, что данная функция активна в параметрах KVM (требует аппаратной поддержки VT-d / IOMMU), что позволяет доставлять прерывания напрямую в L2 vCPU.

### Альтернативы вложенной виртуализации

Если производительность L2 критична, а изоляция гипервизора не требуется, рассмотрите:
- **Kata Containers:** Использует легковесные microVM, которые могут запускаться как L2-гости, но с минималистичным ядром и окружением.
- **gVisor (Sentry):** Перехватывает системные вызовы в userspace. Не требует аппаратной виртуализации, обеспечивая при этом высокую степень изоляции процессов.
- **Firecracker:** Оптимизирован для serverless-нагрузок. В вложенном режиме позволяет запускать сотни микро-ВМ с минимальным потреблением RAM.

### Граничные случаи и ограничения вложенности

1.  **Максимальная глубина вложенности:** На практике используется L2. L3 теоретически возможен, но накладные расходы экспоненциально растут из-за удлинения цепочек VM-Exit. Для L3 требуется ядро Linux 6.16+ и поддержка FEAT_NV2 на ARM64.
2.  **Ограничения памяти:** Каждый уровень добавляет накладные расходы на таблицы страниц (Nested EPT/NPT). Для L2 Reserve минимум 20% дополнительной памяти сверх потребностей гостевой ОС.
3.  **Ограничения vCPU:** Количество vCPU L2 не должно превышать количество pCPU, выделенных L1. Переalloc L1 vCPU для L2 приводит к contention и росту steal time.
4.  **Совместимость гостевых ОС:** Некоторые гостевые ОС (Windows 11) требуют специфических enlightenments (Hyper-V enlightenments) для работы в качестве L1. Проверяйте compatibility matrix перед deployment.
5.  **Время загрузки:** Каждый уровень добавляет 5–15 секунд к времени загрузки. Для автоматических сценариев (CI/CD, инфра-as-code) учитывайте это в timeout'ах.

## Бенчмаркинг и измерение производительности

### Базовые команды для бенчмаркинга

**CPU (sysbench):**
```bash
# Установка
sudo apt-get install -y sysbench

# Тест CPU на L0 (bare metal baseline)
sysbench cpu --threads=$(nproc) --time=30 run

# Тест CPU внутри L1
sysbench cpu --threads=$(nproc) --time=30 run

# Тест CPU внутри L2 (nested)
sysbench cpu --threads=$(nproc) --time=30 run

# Сравнение результатов
# → events per second: L0 ≈ 1000, L1 ≈ 980 (2% loss), L2 ≈ 920 (8% loss)
```

**Дисковый I/O (fio):**
```bash
# Установка
sudo apt-get install -y fio

# Sequential read/write
fio --name=seq_read --rw=read --bs=1M --size=1G --numjobs=4 --time_based --runtime=30
fio --name=seq_write --rw=write --bs=1M --size=1G --numjobs=4 --time_based --runtime=30

# Random IOPS
fio --name=rand_read --rw=randread --bs=4k --size=1G --numjobs=4 --time_based --runtime=30
fio --name=rand_write --rw=randwrite --bs=4k --size=1G --numjobs=4 --time_based --runtime=30

# Сравнение: ожидаемый оверхед L2 vs L1 = 10–15% для random I/O
```

**Сеть (iperf3):**
```bash
# Сервер на L0
iperf3 -s

# Клиент на L1/L2
iperf3 -c <L0_IP> -t 30 -P 4

# Сравнение: L1 ≈ 95% от L0, L2 ≈ 82–88% от L0 (в зависимости от Posted Interrupts)
```

**Латентность (ping + netperf):**
```bash
# Базовая латентность между уровнями
ping -c 100 <L1_IP>
# → rtt min/avg/max: L0→L1 ≈ 0.1ms, L0→L2 ≈ 0.2ms
```

### Сценарий бенчмаркинга

**Полный цикл измерения оверхеда вложенности:**
```bash
#!/bin/bash
# nested-benchmark.sh — сравнение производительности L0/L1/L2

echo "=== CPU Benchmark ==="
for level in L0 L1 L2; do
  echo -n "$level: "
  sysbench cpu --threads=4 --time=10 run 2>&1 | grep "events per second"
done

echo ""
echo "=== Memory Bandwidth ==="
for level in L0 L1 L2; do
  echo -n "$level: "
  sysbench memory --threads=4 --time=10 run 2>&1 | grep "MiB/sec"
done

echo ""
echo "=== Disk I/O (4K random read) ==="
for level in L0 L1 L2; do
  echo -n "$level: "
  fio --name=test --rw=randread --bs=4k --size=256M --numjobs=2 --time_based --runtime=10 \
    --output-format=json 2>/dev/null | jq '.jobs[0].read.iops'
done
```

## Процедуры обновления

### Обновление ядра L0 с сохранением вложенности

**Риск:** Обновление яdra может сбросить параметры модулей KVM.

```bash
# 1. Перед обновлением: сохраните конфигурацию
cat /sys/module/kvm_intel/parameters/nested  # → Y
cp /etc/modprobe.d/kvm-nested.conf /backup/

# 2. Обновите ядро
sudo apt-get update && sudo apt-get upgrade linux-image-generic

# 3. После перезагрузки: проверьте вложенность
cat /sys/module/kvm_intel/parameters/nested
# → Если N: восстановите конфигурацию
sudo tee /etc/modprobe.d/kvm-nested.conf <<EOF
options kvm_intel nested=1
EOF
sudo modprobe -r kvm_intel && sudo modprobe kvm_intel

# 4. Проверьте L1 и L2
virsh start l1-hypervisor
# Внутри L1: egrep -c '(vmx|svm)' /proc/cpuinfo → > 0
```

### Обновление QEMU/libvirt

**Порядок обновления:**
1. Остановите все L1 и L2: `virsh shutdown <vm>`
2. Обновите QEMU/libvirt: `apt-get upgrade qemu-system-x86 libvirt-daemon-system`
3. Перезапустите libvirtd: `systemctl restart libvirtd`
4. Запустите L1 и проверьте L2

**Проверка совместимости:**
```bash
# Версия QEMU (минимум 8.0+ для live-migration L1 с L2)
qemu-system-x86_64 --version

# Версия libvirt (минимум 9.0+)
virsh --version

# Проверка поддержки nested в новом QEMU
qemu-system-x86_64 -cpu help | grep -i "host"
```

### Обновление guest OS (L1/L2)

**Рекомендации:**
- Обновляйте L1 и L2 поочередно, не одновременно.
- Перед обновлением создайте снапшот: `virsh snapshot-create-as <vm> <name>`
- После обновления проверьте флаги CPU: `egrep -c '(vmx|svm)' /proc/cpuinfo`

## Расширенные граничные случаи

### Проблема: Timer Synchronization

Вложенные среды могут иметь проблемы синхронизации времени из-за задержек VM-Exit.

**Симптомы:**
- Время в L2 отстаёт от L1 на 1–5 секунд/час
- NTP не может синхронизироваться

**Решение:**
```bash
# Включите KVM clock в L1 и L2
# XML L1: добавьте <clock offset='kvmclock'/>

# Внутри L2: установите kvm-clock
sudo apt-get install -y kvm-clock  # если доступен

# Проверка
timedatectl
# → NTP synchronized: yes
```

### Проблема: Balloon Conflict

Ballooning в L1 конфликтует с управлением памятью L2.

**Симптомы:**
- L2 получает OOM-kill при наличии свободной памяти на L0
- `balloon.actual` значительно меньше `balloon.current`

**Решение:**
```bash
# Вариант 1: Отключите ballooning в L1
# XML L1: <memballoon type='none'/>

# Вариант 2: Установите минимальный порог
# XML L1: <memballoon model='virtio' autodeflate='off' freePageReporting='off'/>
```

### Проблема: Nested EPT not available

Если L0 не поддерживает Virtual EPT (старые CPU), производительность L2 резко падает.

**Диагностика:**
```bash
# Проверка Virtual EPT
dmesg | grep -i "virtual ept"
# → Если нет: Shadow Page Tables активен (оверход до 30%)

# Проверка через perf
sudo perf kvm stat live --component vmexits
# → EPT Violation: > 50% от всех exit = проблема
```

**Решение:** Обновите оборудование на CPU с поддержкой Virtual EPT (Broadwell+ / Zen 2+).

### Проблема: vCPU starvation при overcommit

Если L0 перегружен ВМ, L2 может испытывать starvation.

**Диагностика:**
```bash
# На L0: проверка steal time
vmstat 1 5
# → st (steal) > 5% = проблема

# На L2: проверка steal time
top
# → %st > 5% = L2 не хватает CPU
```

**Решение:**
```bash
# На L0: уменьшите overcommit ratio
virsh schedinfo l1-hypervisor --set vcpu_quota=80000

# Или перераспределите ВМ по хостам
```

## Чеклист для production-развертывания

### Перед запуском

- [ ] Включена вложенность на L0 (`nested=1`)
- [ ] IOMMU активен (`iommu=pt`)
- [ ] L1 использует `host-passthrough`
- [ ] NUMA-привязка настроена (`<numatune>`)
- [ ] CPU pinning настроен (`<vcpupin>`)
- [ ] Shared storage настроен для миграции (NFS/Ceph)
- [ ] sVirt/AppArmor активен на L0
- [ ] Мониторинг настроен (Prometheus + node_exporter)
- [ ] Алерты настроены (steal time, VM-Exits, balloon)
- [ ] Бэкапы настроены (снапшоты + инкрементальный бэкап)
- [ ] Тест failover выполнен

### После запуска

- [ ] Steal time < 5% на L0
- [ ] VM-Exits < 100k/s на L0
- [ ] Balloon actual ≈ balloon current в L1
- [ ] Все L2 доступны по сети
- [ ] Время синхронизировано (NTP)
- [ ] Логи не содержат ошибок (`journalctl -u libvirtd`)

## Ссылки и ресурсы

### Связанные файлы

- [Вложенная виртуализация: Определения и концепции](./definitions_and_concepts.md) — уровни и архитектура.
- [Вложенная виртуализация: Практические сценарии](./practical_scenarios.md) — пошаговая настройка.
- [KVM — Обзор и архитектура](../kvm/overview.md) — фундаментальные принципы.
- [Оптимизация KVM (2026)](../kvm/performance_tuning_2026.md) — глубокий тюнинг памяти и CPU.
- [Мониторинг KVM](../kvm/kvm_monitoring.md) — Prometheus, Grafana, алерты.
- [Безопасность KVM](../kvm/kvm_security_hardening.md) — sVirt, SELinux, LUKS.
- [Резервное копирование ВМ](../kvm/vm_backup_dr.md) — стратегии бэкапа.
- [Высокая доступность KVM](../kvm/kvm_ha.md) — Pacemaker, DRBD.
- [Решение проблем KVM](../kvm/troubleshooting.md) — типичные ошибки.
