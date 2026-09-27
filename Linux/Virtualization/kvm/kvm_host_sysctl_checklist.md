# Sysctl чек-лист для KVM-хостов

В данном файле приведен полный checklist параметров sysctl и ядра, критичных для стабильной и производительной работы KVM-хостов в продакшене. Методы тюнинга производительности ВМ описаны в [Оптимизация KVM (2025–2026)](./performance_tuning_2026.md), а overcommit — в [Overcommit и планирование ресурсов](./kvm_overcommit_and_capacity.md).

## Определения

**sysctl** — интерфейс ядра Linux для чтения и изменения параметров времени выполнения. Параметры хранятся в `/proc/sys/` и настраиваются через `/etc/sysctl.d/*.conf`.

**Transparent Hugepages (THP)** — механизм ядра, автоматически объединяющий страницы 4KB в 2MB в фоновом режиме. Может вызывать latency spikes при дефрагментации.

**KSM (Kernel Samepage Merging)** — механизм дедупликации одинаковых страниц памяти между процессами. В контексте KVM объединяет идентичные страницы разных ВМ.

**Overcommit Memory** — политика ядра выделения памяти. Определяет, разрешает ли ядро выделять больше памяти, чем физически доступно.

**Dirty Ratio** — процент RAM, при заполнении которого ядро блокирует процессы записи до синхронизации данных на диск.

**conntrack** — подсистема ядра для отслеживания состояний сетевых соединений. Основной bottleneck при высоких нагрузках.

## Базовые концепции

### Структура файла конфигурации

Параметры sysctl группируются по категориям. Рекомендуется создавать отдельные файлы для каждой группы:

```
/etc/sysctl.d/
├── 01-memory.conf         # Память, swap, overcommit
├── 02-network.conf        # Сеть, conntrack, TCP
├── 03-kvm.conf            # KVM-специфичные параметры
├── 04-security.conf       # Защита от side-channel атак
└── 99-custom.conf         # Собственные настройки
```

### Применение конфигурации

```bash
# Проверка текущих значений
sysctl vm.swappiness

# Применение одного параметра
sudo sysctl -w vm.swappiness=10

# Применение всех файлов из директории
sudo sysctl --system

# Проверка что параметр применился
sysctl -a | grep vm.swappiness
```

## Практические сценарии

### 1. Память и Swap

Эти параметры критичны для предотвращения OOM и контроля свопинга ВМ.

```bash
# /etc/sysctl.d/01-memory.conf

# === ПОЛИТИКА SWAP ===
# Склонность ядра к свопанию (0-100). Для KVM-хостов рекомендуется 10.
# Значение 0: свопать только при нехватке RAM (рекомендуется для БД-хостов)
# Значение 10: умеренная свопка (хороший баланс для общих хостов)
# Значение 60: дефолт Linux (слишком агрессивен для KVM)
vm.swappiness = 10

# === OVERCOMMIT MEMORY ===
# 0 = эвристика (дефолт Linux, допускает умеренный overcommit)
# 1 = всегда разрешать (опасно, но используется для某些 workloads)
# 2 = строгий контроль: CommitLimit = Swap + RAM * overcommit_ratio / 100
vm.overcommit_memory = 0

# Процент физической памяти, доступный для выделения при overcommit_memory=2
# Формула: CommitLimit = Swap + RAM * overcommit_ratio / 100
# Рекомендуется 80-90 для KVM-хостов
vm.overcommit_ratio = 80

# === MIN FREE KBYTES ===
# Минимальное количество KB свободной памяти, которое ядро пытается поддерживать
# Для KVM-хостов с 64GB RAM рекомендуется 262144 (256MB)
vm.min_free_kbytes = 262144

# === SWAPPINESS ===
# Альтернативный swappiness через cgroup (для systemd.slice)
#vm.swappiness = 10
```

**Проверка после применения:**
```bash
# Проверка политики overcommit
cat /proc/sys/vm/overcommit_memory
# → 0 (эвристика)

# Проверка CommitLimit
grep -i commitlimit /proc/meminfo
# → CommitLimit:  64997376 kB

# Проверка swappiness
cat /proc/sys/vm/swappiness
# → 10
```

### 2. Dirty Pages (Контроль записи на диск)

Параметры управления «грязными» страницами влияют на производительность записи и безопасность данных.

```bash
# /etc/sysctl.d/01-memory.conf (продолжение)

# === DIRTY PAGES ===
# Максимум % RAM для грязных страниц перед блокировкой записи
# Для KVM-хостов: 10-20 (ниже = меньше потеря при сбое, выше = лучше производительность)
vm.dirty_ratio = 15

# % RAM для грязных страниц, при которых запускается фоновая запись
# Должно быть меньше dirty_ratio. Рекомендуется 3-5.
vm.dirty_background_ratio = 5

# Максимальный % одной.dirty-записи, разрешенный за раз
#vm.dirty_bytes = 0

# Интервал (в сотых долях секунды) между принудительными flush
# По умолчанию 500 (5 сек). Для KVM: 100-300.
vm.dirty_expire_centisecs = 300

# Интервал between_background_ и _foreground_ writeback
vm.dirty_writeback_centisecs = 100
```

**Влияние на production:**
```text
Сценарий: KVM-хост с 128GB RAM, БД- workload

Если dirty_ratio = 40 (дефолт):
  → До 51GB могут быть в памяти перед flush
  → При сбое: потеря данных за ~30 секунд
  → Производительность: максимальная

Если dirty_ratio = 15 (рекомендуется):
  → До 19GB в памяти перед flush
  → При сбое: потеря данных за ~5 секунд
  → Производительность: 95% от максимальной
```

### 3. Сеть и Conntrack

Эти параметры критичны для хостов с высокой сетевой нагрузкой.

```bash
# /etc/sysctl.d/02-network.conf

# === CONNTRACK ===
# Максимальное количество отслеживаемых соединений
# Для KVM-хостов с hundreds of VMs: 524288-1048576
net.netfilter.nf_conntrack_max = 524288

# Размер хэш-таблицы conntrack (рекомендуется = max / 4)
net.netfilter.nf_conntrack_buckets = 131072

# Таймауты conntrack (в секундах)
net.netfilter.nf_conntrack_tcp_timeout_established = 432000
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
net.netfilter.nf_conntrack_udp_timeout = 30
net.netfilter.nf_conntrack_udp_timeout_stream = 60

# === TCP ===
# Максимальный размер listen backlog
net.core.somaxconn = 65535

# Максимальное количество пакетов в очереди на входе в ядро
net.core.netdev_max_backlog = 65536

# Максимальное количество syn_recv (SYN cookies включены)
net.ipv4.tcp_max_syn_backlog = 65535

# Включение SYN cookies (защита от SYN flood)
net.ipv4.tcp_syncookies = 1

# Переиспользование TIME_WAIT socket
net.ipv4.tcp_tw_reuse = 1

# Максимальное количество孤儿енных соединений (без владельца)
net.ipv4.tcp_max_orphans = 65536

# Максимальный размер кэша socket (в байтах)
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216

# TCP buffer sizes: min, default, max (в байтах)
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# === БУФЕРЫ ===
# Максимальный размер ARP-кэша
net.ipv4.neigh.default.gc_thresh1 = 4096
net.ipv4.neigh.default.gc_thresh2 = 8192
net.ipv4.neigh.default.gc_thresh3 = 16384
```

**Проверка conntrack:**
```bash
# Текущее использование conntrack
cat /proc/sys/net/netfilter/nf_conntrack_count
# → 128456

cat /proc/sys/net/netfilter/nf_conntrack_max
# → 524288

# Процент использования (должен быть < 80%)
echo "scale=2; $(cat /proc/sys/net/netfilter/nf_conntrack_count) * 100 / $(cat /proc/sys/net/netfilter/nf_conntrack_max)" | bc
# → 24.59%
```

### 4. KVM-специфичные параметры

Параметры, напрямую влияющие на работу гипервизора.

```bash
# /etc/sysctl.d/03-kvm.conf

# === VIRTUAL MEMORY ===
# Включить access (read/write) к виртуальной памяти
# Требуется для работы некоторых ВМ с hugepages
vm.vm_memory_access_allowed = 1

# === HUGE PAGES ===
# Количество зарезервированных hugepages 2MB при загрузке
# Для ВМ с 8GB RAM: 4096 pages = 8GB
#vm.nr_hugepages = 4096

# Allow user to allocate hugepages
vm.hugetlb_shm_group = 0

# === KSM ===
# Включение KSM (обычно отключено по умолчанию)
# Включайте только на хостах с однотипными ВМ (development, VDI)
#vm.ksm.run = 0

# Количество страниц для сканирования за раз
#vm.ksm.pages_to_scan = 100

# Интервал сканирования (мс)
#vm.ksm.sleep_millisecs = 20

# === OVERCOMMIT VIRTUAL MEMORY ===
#vm.overcommit_kbytes = 0
```

### 5. Безопасность (Side-Channel Защита)

Параметры для защиты от атак типа Spectre/Meltdown и других side-channel атак.

```bash
# /etc/sysctl.d/04-security.conf

# === MELTDOWN/SPECTRE MITIGATIONS ===
# Автоматические митигации (рекомендуется включено)
# 0 = отключены, 1 = включены, 2 = включены для vulnerable процессов
kernel.mitigate_spectre_ring1 = 1

# === ASLR (Address Space Layout Randomization) ===
# Уровень randomization: 0=отключен, 1=обычный, 2=полный
kernel.randomize_va_space = 2

# === DUMPABLE ===
# Запрет dump suid-процессов
fs.suid_dumpable = 0

# === KEXEC ===
# Разрешить kexec (для быстрой перезагрузки ядра)
kernel.kexec_load_disabled = 0

# === YAMA ===
# Ограничение ptrace (защита от injection)
kernel.yama.ptrace_scope = 1
```

### 6. Disk I/O и Storage

```bash
# /etc/sysctl.d/01-memory.conf (дополнение)

# === I/O SCHEDULER ===
# Для NVMe: none (прямой доступ)
# Для SATA/SAS: mq-deadline (баланс latency/throughput)
# Настройка через /sys/block/<device>/queue/scheduler, не через sysctl

# === WRITEBACK ===
# Максимальное количество страниц для writeback за раз
vm.dirty_background_bytes = 0
vm.dirty_bytes = 0

# === INOTIFY ===
# Лимиты inotify (важно для KVM с множеством watch)
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 8192
```

## Полный пример конфигурации

```bash
# /etc/sysctl.d/99-kvm-host.conf
# Полный чек-лист для KVM-хоста в продакшене

# --- Память ---
vm.swappiness = 10
vm.overcommit_memory = 0
vm.overcommit_ratio = 80
vm.min_free_kbytes = 262144
vm.dirty_ratio = 15
vm.dirty_background_ratio = 5
vm.dirty_expire_centisecs = 300
vm.dirty_writeback_centisecs = 100

# --- Сеть ---
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 65536
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_max_orphans = 65536
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.netfilter.nf_conntrack_max = 524288
net.netfilter.nf_conntrack_buckets = 131072
net.netfilter.nf_conntrack_tcp_timeout_established = 432000
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30

# --- Безопасность ---
kernel.randomize_va_space = 2
fs.suid_dumpable = 0
kernel.yama.ptrace_scope = 1

# --- Файловая система ---
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 8192
fs.file-max = 2097152

# --- ARP ---
net.ipv4.neigh.default.gc_thresh1 = 4096
net.ipv4.neigh.default.gc_thresh2 = 8192
net.ipv4.neigh.default.gc_thresh3 = 16384
```

## Диагностика и мониторинг

### Проверка текущих значений

```bash
# Вывод всех параметров с фильтрацией
sysctl -a | grep -E "vm\.|net\."

# Проверка конкретных критичных параметров
echo "=== Память ==="
echo "swappiness: $(sysctl -n vm.swappiness)"
echo "overcommit_memory: $(sysctl -n vm.overcommit_memory)"
echo "dirty_ratio: $(sysctl -n vm.dirty_ratio)"
echo "dirty_background_ratio: $(sysctl -n vm.dirty_background_ratio)"

echo "=== Сеть ==="
echo "somaxconn: $(sysctl -n net.core.somaxconn)"
echo "conntrack_max: $(sysctl -n net.netfilter.nf_conntrack_max)"
echo "conntrack_count: $(cat /proc/sys/net/netfilter/nf_conntrack_count)"
```

### Аудит конфигурации

```bash
#!/bin/bash
# kvm_sysctl_audit.sh — аудит sysctl для KVM-хоста
set -euo pipefail

ERRORS=0

check_sysctl() {
  local param="$1"
  local expected="$2"
  local desc="$3"
  local actual
  actual=$(sysctl -n "$param" 2>/dev/null || echo "NOT_FOUND")
  
  if [ "$actual" = "NOT_FOUND" ]; then
    echo "[WARN] $param: параметр не найден ($desc)"
  elif [ "$actual" != "$expected" ]; then
    echo "[FAIL] $param: $actual (ожидалось $expected) — $desc"
    ERRORS=$((ERRORS + 1))
  else
    echo "[OK]   $param: $actual — $desc"
  fi
}

echo "=== KVM Host Sysctl Audit ==="

# Память
check_sysctl "vm.swappiness" "10" "Swap policy"
check_sysctl "vm.dirty_ratio" "15" "Max dirty pages"
check_sysctl "vm.dirty_background_ratio" "5" "Background writeback threshold"

# Сеть
check_sysctl "net.core.somaxconn" "65535" "Listen backlog"
check_sysctl "net.ipv4.tcp_syncookies" "1" "SYN cookies"

echo ""
echo "=== Conntrack ==="
COUNT=$(cat /proc/sys/net/netfilter/nf_conntrack_count 2>/dev/null || echo "0")
MAX=$(cat /proc/sys/net/netfilter/nf_conntrack_max 2>/dev/null || echo "0")
if [ "$MAX" -gt 0 ]; then
  PCT=$((COUNT * 100 / MAX))
  echo "conntrack: $COUNT / $MAX ($PCT%)"
  [ "$PCT" -gt 80 ] && echo "[WARN] conntrack usage > 80%" && ERRORS=$((ERRORS + 1))
fi

echo ""
echo "=== Итого ошибок: $ERRORS ==="
exit $ERRORS
```

### Мониторинг через Prometheus

```yaml
# Записи для мониторинга sysctl-метрик
groups:
  - name: kvm_host_sysctl
    rules:
      - alert: HighSwapUsage
        expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Использование памяти > 80% на {{ $labels.instance }}"

      - alert: ConntrackNearFull
        expr: (node_netfilter_conntrack_entries / node_netfilter_conntrack_entries_limit) > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "conntrack > 80% на {{ $labels.instance }}"

      - alert: HighDirtyPages
        expr: (node_memory_Dirty_bytes / node_memory_MemTotal_bytes) > 0.1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Dirty pages > 10% RAM на {{ $labels.instance }}"
```

## Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **OOM Killer убивает QEMU** | `vm.swappiness` слишком высокий, ВМ агрессивно свопают | Снизить `vm.swappiness` до 10, увеличить RAM |
| **conntrack table full** | `nf_conntrack_max` слишком мал для числа ВМ | Увеличить `nf_conntrack_max` до 524288+ |
| **Высокий latency записи** | `dirty_ratio` слишком высокий, накапливается много грязных страниц | Снизить `dirty_ratio` до 15, `dirty_background_ratio` до 5 |
| **SYN flood vulnerability** | `tcp_syncookies` отключен | Включить `tcp_syncookies = 1` |
| **Высокий steal time** | `overcommit_ratio` слишком высокий | Снизить до 80, проверить баланс vCPU/pCPU |
| **KVM не видит hugepages** | `vm.nr_hugepages` не задан или недостаточно | Настроить в GRUB или через `sysctl` |

## Взаимодействие с другими компонентами

```
┌─────────────────────────────────────────────────────────┐
│  sysctl (ядро)                                          │
│  ├── vm.* → KVM/QEMU (память, swap, dirty pages)       │
│  ├── net.* → libvirt networks (conntrack, TCP)         │
│  └── fs.* → файловая система (inotify, file-max)       │
├─────────────────────────────────────────────────────────┤
│  systemd                                                 │
│  ├── sysctl.d/*.conf → автозагрузка параметров         │
│  └── tuned → профили оптимизации                        │
├─────────────────────────────────────────────────────────┤
│  tuned-adm profile virtual-host                         │
│  ├── Автоматически задает: swappiness=10,              │
│  │   transparent_hugepage=madvise,                     │
│  │   dirty_ratio=10, dirty_background_ratio=3          │
│  └── НЕ задает: conntrack, somaxconn, overcommit       │
└─────────────────────────────────────────────────────────┘
```

**Важно:** `tuned-adm profile virtual-host` задает базовые параметры, но НЕ покрывает network tuning (conntrack, somaxconn) и security (mitigations). Всегда комбинируйте tuned с ручной настройкой sysctl.

## Дополнительная информация

- [Оптимизация KVM (2025–2026)](./performance_tuning_2026.md) — CPU pinning, HugePages, NUMA, io_uring.
- [Overcommit и планирование ресурсов](./kvm_overcommit_and_capacity.md) — safe ratios, monitoring.
- [Диагностика и решение проблем](./troubleshooting.md) — kvm_stat, логи, диагностика.
- [Сетевые основы KVM](./kvm_networking_fundamentals.md) — libvirt networks, nwfilter.
- [Безопасность KVM-хостов](./kvm_security_hardening.md) — sVirt, CIS Benchmark.
