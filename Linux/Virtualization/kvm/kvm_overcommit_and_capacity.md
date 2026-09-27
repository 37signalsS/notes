# Overcommit и планирование ресурсов KVM

В данном файле описывается практика безопасного overcommit CPU и RAM в среде KVM, расчёт безопасных соотношений, влияние на производительность и методы мониторинга. Методы тюнинга производительности описаны в [Оптимизация KVM (2025–2026)](./performance_tuning_2026.md), а типовые проблемы — в [Решение проблем (Troubleshooting)](./troubleshooting.md).

## Определения

**Overcommit** — ситуация, когда суммарные ресурсы (CPU, RAM), выделенные всем ВМ, превышают физические ресурсы хоста. Виртуализация позволяет это благодаря time-sharing (CPU) и баллонным/swap механизмам (RAM).

**CPU Overcommit Ratio** — отношение суммарных vCPU всех ВМ к количеству физических ядер хоста. Например, 48 vCPU на 16 ядрах = ratio 3:1.

**RAM Overcommit Ratio** — отношение суммарного RAM всех ВМ к физическому RAM хоста. Например, 128 GB выделено при 64 GB на хосте = ratio 2:1.

**CPU Steal Time** — время, в течение которого vCPU ВМ ожидал физический CPU из-за перегрузки хоста или конкуренции за ресурсы. Высокий steal time (>5%) указывает на чрезмерный overcommit.

**Noisy Neighbor** — эффект, при котором одна ВМ потребляет непропорционально много ресурсов, ухудшая производительность соседних ВМ.

**Balloon Driver (virtio-balloon)** — драйвер, позволяющий гипервизору «забирать» неиспользуемую память у гостя и перераспределять её между ВМ.

**Overcommit Memory (vm.overcommit_memory)** — sysctl-параметр ядра Linux, определяющий политику выделения памяти: 0 (эвристика), 1 (всегда разрешать), 2 (строгий контроль).

**Overcommit Ratio (vm.overcommit_ratio)** — процент физической памяти, доступный для выделения при `vm.overcommit_memory=2`. Формула: `CommitLimit = Swap + RAM × overcommit_ratio / 100`.

## Базовые концепции

### Влияние CPU overcommit на производительность

CPU overcommit безопасен для batch- и idle-loads, но критичен для latency-sensitive workloads.

**Безопасные соотношения:**

| Тип нагрузки | Безопасный ratio | Комментарий |
| :--- | :--- | :--- |
| **Web-серверы ( Stateless)** | 4:1 – 8:1 | ВМ редко используют 100% CPU |
| **Базы данных** | 1:1 – 2:1 | Требуют стабильных задержек |
| **Контейнеры (K8s worker)** | 3:1 – 5:1 | Зависит от scheduler |
| **Real-time / HFT** | 1:1 | Полная изоляция |
| **Development / Test** | 8:1 – 16:1 | Допустимы задержки |

**Формула расчёта:**
```
CPU Overcommit Ratio = Σ(vCPU всех ВМ) / Кол-во физических ядер

Пример:
- 10 ВМ × 4 vCPU = 40 vCPU
- Хост: 16 ядер (32 потока с HT)
- Ratio = 40 / 32 = 1.25:1 → безопасно
```

**Мониторинг CPU overcommit:**
```bash
# Steal Time в % (через top на госте)
top -bn1 | grep "Cpu(s)" | awk '{print $8}'
# → %st

# Или через virsh
virsh domstats --cpu-total web-server-01 | grep cpu.time

# Через Prometheus
100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
# Если > 80% на хосте — overcommit слишком агрессивный
```

### Влияние RAM overcommit на производительность

RAM overcommit более опасен, чем CPU, так как приводит к OOM-kill или свопу.

**Три уровня RAM overcommit:**

| Уровень | Описание | Риск |
| :--- | :--- | :--- |
| **Balloon** | Гипервизор запрашивает неиспользуемую память у гостя | Минимальный — если гость согласен |
| **KSM** | Дедупликация одинаковых страниц между ВМ | Средний — добавляет CPU overhead |
| **Swap** | Выгрузка страниц ВМ на диск хоста | Высокий — катастрофический рост latency |

**Безопасные соотношения:**

| Тип нагрузки | Безопасный ratio | Комментарий |
| :--- | :--- | :--- |
| **Базы данных** | 1:1 | Не допускать任何形式 of overcommit |
| **Web-серверы** | 1.2:1 – 1.5:1 | С balloon driver |
| **Development** | 2:1 – 3:1 | С swap и KSM |
| **Контейнеры** | 1.5:1 – 2:1 | Зависит от QoS class |

**Формула расчёта:**
```
RAM Overcommit Ratio = Σ(maxmemory всех ВМ) / Физический RAM хоста

Пример:
- 10 ВМ × 8 GB maxmemory = 80 GB
- Хост: 64 GB RAM
- Ratio = 80 / 64 = 1.25:1 → безопасно с balloon

БЕЗ balloon:
- 10 ВМ × 4 GB currentMemory = 40 GB
- Хост: 64 GB RAM
- Ratio = 40 / 64 = 0.625:1 → безопасно
```

### Настройка vm.overcommit_memory

Параметр ядра определяет политику выделения памяти на уровне хоста.

| Значение | Политика | Рекомендация |
| :--- | :--- | :--- |
| **0** | Эвристика (по умолчанию). Ядро пытается выделить, но может отказать при нехватке. | Для development |
| **1** | Всегда разрешать. Не проверять CommitLimit. Риск OOM. | Только для Redis (fork) |
| **2** | Строгий контроль. `CommitLimit = Swap + RAM × ratio / 100`. | Production KVM-хосты |

**Настройка для production:**
```bash
# /etc/sysctl.d/99-kvm-overcommit.conf
vm.overcommit_memory = 2
vm.overcommit_ratio = 80  # 80% физической RAM доступно для выделения

# Применение
sudo sysctl -p /etc/sysctl.d/99-kvm-overcommit.conf

# Проверка
cat /proc/sys/vm/overcommit_memory
# → 2
grep CommitLimit /proc/meminfo
# → CommitLimit:  54975581388 kB (Swap + RAM * 80%)
```

**Расчёт CommitLimit:**
```
CommitLimit = Swap + (RAM × overcommit_ratio / 100)

Пример:
- RAM: 64 GB, Swap: 8 GB, ratio: 80
- CommitLimit = 8 + (64 × 80 / 100) = 8 + 51.2 = 59.2 GB
- Если ΣcurrentMemory всех ВМ > 59.2 GB → OOM-killer
```

### Влияние NUMA на overcommit

В NUMA-системах overcommit должен учитывать распределение памяти по узлам.

**Проблема:** ВМ с памятью из разных NUMA-узлов получает задержки 1.5-3x.

**Решение:** Привязка ВМ к одному NUMA-узлу через `numatune`.

```xml
<!-- ВМ привязана к NUMA-узлу 0 -->
<numatune>
  <memory mode='strict' nodeset='0'/>
  <cpus cpuset='0-7' nodeset='0'/>
</numatune>
```

**Проверка NUMA-баланса:**
```bash
# Просмотр NUMA-топологии
numactl --hardware
# → node 0 cpus: 0 1 2 3 8 9 10 11
# → node 0 size: 32768 MB
# → node 1 cpus: 4 5 6 7 12 13 14 15
# → node 1 size: 32768 MB

# Проверка распределения памяти процесса QEMU
numastat -p $(pgrep -f qemu-system)
# → Per-node process memory usage (in MBs)
# → Node 0  Node 1
# → 16384     0      ← хорошо: вся память на одном узле
```

### Влияние Balloon Driver на overcommit

Balloon — единственный безопасный механизм RAM overcommit в KVM.

**Принцип работы:**
1. Хост запрашивает у гостя освободить страницы (inflate balloon).
2. Гостевая ОС возвращает страницы ядру (через balloon driver).
3. Хост перераспределяет страницы между ВМ.

**Настройка balloon в XML:**
```xml
<memballoon model='virtio'/>
```

**Проверка состояния balloon:**
```bash
# Просмотр метрик balloon
virsh dommemstat web-server-01
# → actual 4194304      (текущий объём RAM ВМ)
# → swap_in 0
# → rss 2097152         (фактически используемая RAM)
# → major_fault 0
# → minor_fault 12345

# Целевой размер balloon
virsh domstats web-server-01 | grep balloon
# → balloon.current=0        (текущий размер balloon)
# → balloon.target=0         (целевой размер)
# → balloon.maximum=8388608  (максимальный размер)
```

**Мониторинг balloon effectiveness:**
```promql
# Prometheus: balloon забирает память
libvirt_domain_info_balloon_target > 0 and libvirt_domain_info_balloon_current == 0
# → Алерт: balloon установлен, но не работает

# Фактическое потребление RAM ВМ
libvirt_domain_info_memory_stats_rss / libvirt_domain_info_memory_stats_actual * 100
# → Если < 70% — ВМ использует мало памяти, можно надувать balloon
```

### Практический расчёт для кластера

**Сценарий: 3 хоста по 64 GB RAM, 16 ядер, Web-серверы (4 vCPU, 4 GB RAM)**

```bash
# Расчёт CPU:
# ВМ на хост: ceil(16 ядер × 3 ratio) / 4 vCPU = 12 ВМ
# Всего: 12 × 3 = 36 ВМ

# Расчёт RAM (с balloon):
# Безопасный ratio: 1.5:1
# RAM на хост: 64 GB × 1.5 = 96 GB доступно
# ВМ на хост: 96 / 4 = 24 ВМ

# Расчёт RAM (без balloon):
# RAM на хост: 64 GB × 0.9 = 57.6 GB (с запасом 10%)
# ВМ на хост: 57.6 / 4 = 14 ВМ

# Итого (с balloon): min(36, 24) = 24 ВМ на хост
# Всего: 24 × 3 = 72 ВМ

# Проверка steal time:
# При 24 ВМ × 4 vCPU = 96 vCPU на 16 ядер
# Ratio = 96 / 16 = 6:1 → для web-серверов допустимо
# Но нужен мониторинг steal time
```

## Практические сценарии

### Сценарий 1: Определение безопасного overcommit для хоста

```bash
#!/bin/bash
# kvm-calculate-overcommit.sh — расчёт безопасного overcommit

CORES=$(nproc)
RAM_GB=$(free -g | awk '/^Mem:/{print $2}')
SWAP_GB=$(free -g | awk '/^Swap:/{print $2}')

# Безопасные ratio для разных типов нагрузки
echo "=== KVM Overcommit Calculator ==="
echo "Host: ${CORES} cores, ${RAM_GB} GB RAM, ${SWAP_GB} GB Swap"
echo ""

# Тип: Web-серверы
WEB_VM_VCPU=4
WEB_VM_RAM=4
WEB_RATIO_CPU=4
WEB_RATIO_RAM=1.5

MAX_VMS_BY_CPU=$((CORES * WEB_RATIO_CPU / WEB_VM_VCPU))
MAX_VMS_BY_RAM=$(echo "$RAM_GB * $WEB_RATIO_RAM / $WEB_VM_RAM" | bc)

echo "Web servers (${WEB_VM_VCPU} vCPU, ${WEB_VM_RAM} GB RAM):"
echo "  CPU limit: ${MAX_VMS_BY_CPU} VMs"
echo "  RAM limit: ${MAX_VMS_BY_RAM} VMs"
echo "  Safe: $(min $MAX_VMS_BY_CPU $MAX_VMS_BY_RAM) VMs per host"
echo ""

# Тип: Базы данных
DB_VM_VCPU=8
DB_VM_RAM=32
DB_RATIO_CPU=1.5
DB_RATIO_RAM=1

MAX_VMS_BY_CPU=$((CORES * DB_RATIO_CPU / DB_VM_VCPU))
MAX_VMS_BY_RAM=$(echo "$RAM_GB * $DB_RATIO_RAM / $DB_VM_RAM" | bc)

echo "Databases (${DB_VM_VCPU} vCPU, ${DB_VM_RAM} GB RAM):"
echo "  CPU limit: ${MAX_VMS_BY_CPU} VMs"
echo "  RAM limit: ${MAX_VMS_BY_RAM} VMs"
echo "  Safe: $(min $MAX_VMS_BY_CPU $MAX_VMS_BY_RAM) VMs per host"
```

### Сценарий 2: Мониторинг overcommit в реальном времени

```bash
# Проверка текущего состояния

# 1. Сколько vCPU выделено vs сколько ядер
TOTAL_VCPU=$(virsh list --name --all | xargs -I{} virsh dominfo {} 2>/dev/null | grep "CPU(s):" | awk '{sum+=$2} END{print sum}')
PHYSICAL_CORES=$(nproc)
echo "vCPU: ${TOTAL_VCPU} / Cores: ${PHYSICAL_CORES} = Ratio: $(echo "scale=1; $TOTAL_VCPU / $PHYSICAL_CORES" | bc)"

# 2. Сколько RAM выделено vs сколько доступно
TOTAL_RAM=$(virsh list --name --all | xargs -I{} virsh dominfo {} 2>/dev/null | grep "Max memory:" | awk '{sum+=$3} END{print sum}')
PHYSICAL_RAM=$(free -k | awk '/^Mem:/{print $2}')
echo "RAM allocated: $((TOTAL_RAM / 1024 / 1024)) GB / Physical: $((PHYSICAL_RAM / 1024 / 1024)) GB = Ratio: $(echo "scale=1; $TOTAL_RAM / $PHYSICAL_RAM" | bc)"

# 3. Steal time (самый важный индикатор)
echo "Steal time (last 5 min):"
mpstat 1 5 | tail -1 | awk '{print $NF"%"}'
```

### Сценарий 3: Настройка tuning profile для KVM-хоста

```bash
# RHEL/Rocky/Fedora: tuning через tuned
sudo dnf install tuned
sudo tuned-adm profile virtual-host

# Проверка профиля
sudo tuned-adm active
# → Current active profile: virtual-host

# Профиль virtual-host включает:
# - vm.swappiness = 10
# - vm.dirty_ratio = 40
# - vm.dirty_background_ratio = 10
# - kernel.sched_migration_cost_ns = 5000000
# - transparent_hugepage = always (для general workloads)

# Для latency-sensitive ВМ:
sudo tuned-adm profile virtual-guest
# Или кастомный профиль
```

### Сценарий 4: Алертинг на overcommit

```yaml
# kvm_overcommit_alerts.yml для Prometheus
groups:
  - name: kvm_overcommit
    rules:
      # High Steal Time
      - alert: HighStealTime
        expr: |
          100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 15
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High steal time on {{ $labels.instance }}"
          description: "CPU steal time > 15% indicates aggressive overcommit"

      # Memory overcommit
      - alert: MemoryOvercommit
        expr: |
          sum(libvirt_domain_info_memory_stats_actual) by (instance) >
          node_memory_MemTotal_bytes * 0.9
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Memory overcommit critical on {{ $labels.instance }}"
          description: "VM memory allocation > 90% of physical RAM"

      # Balloon not working
      - alert: BalloonIneffective
        expr: |
          libvirt_domain_info_balloon_target > 0 and
          libvirt_domain_info_balloon_current == 0
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Balloon not working in {{ $labels.domain }}"
```

## Дополнительная информация

- [Оптимизация KVM (2025–2026)](./performance_tuning_2026.md) — CPU pinning, HugePages, NUMA, cgroups.
- [Решение проблем (Troubleshooting)](./troubleshooting.md) — steal time, OOM, noisy neighbor.
- [Мониторинг KVM](./kvm_monitoring.md) — Prometheus метрики, алерты.
- [KVM — Обзор и архитектура](./overview.md) — balloon, NUMA, memory management.
- [Sysctl чек-лист для KVM-хостов](./kvm_host_sysctl_checklist.md) — полный список параметров sysctl.
- [vm.overcommit_memory](../../Linux/Core/processes/oom_killer_management.md) — полное руководство по overcommit memory.
- [OOM Killer](../../Linux/Core/processes/oom_killer_management.md) — диагностика и настройка.
- [Системный tuning](../../Linux/SystemAdministration/performance_baseline.md) — tuning profiles, sysctl.
- [NUMA](../../Linux/Core/cpu_selection.md) — NUMA-планирование, CCD/CCX.
- [cgroups](../../Linux/Core/cgroups.md) — CPU/Disk quotas для ВМ.
- [Kubernetes QoS](../../Kubernetes/Scheduling/qos_limit_and_requests.md) — overcommit в контексте K8s.
