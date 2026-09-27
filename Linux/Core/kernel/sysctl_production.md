# sysctl для production-окружения: kernel tunables

## Определения

**Production sysctl** — набор параметров ядра, рекомендуемых для серверов в продакшне, влияющих на стабильность, производительность и диагностику. Эти параметры настраиваются через `/etc/sysctl.d/` и применяются без перезагрузки, обеспечивая оптимальное поведение ядра при высоких нагрузках, аварийных ситуациях и проблемах с оборудованием.

---

## Базовые концепции

### Применение sysctl

```bash
# Временное применение (до перезагрузки)
sudo sysctl -w kernel.panic=10

# Постоянное применение
echo "kernel.panic = 10" | sudo tee /etc/sysctl.d/99-kernel.conf
sudo sysctl --system

# Проверка текущего значения
cat /proc/sys/kernel/panic
```

### Приоритеты sysctl-файлов

```
/etc/sysctl.d/00-default.conf     — дефолты (не трогать)
/etc/sysctl.d/50-*.conf           — стандартные настройки дистрибутива
/etc/sysctl.d/90-*.conf           — наши настройки (ПЕРЕОПРЕДЕЛЯЮТ 50-*)
/etc/sysctl.d/99-*.conf           — кастомные настройки (ПЕРЕОПРЕДЕЛЯЮТ 90-*)
/etc/sysctl.conf                  — legacy (устаревает)
```

---

## Практические сценарии

### Параметры аварийного восстановления

```bash
cat <<'EOF' | sudo tee /etc/sysctl.d/90-kernel-emergency.conf
# Автоматическая перезагрузка через 10 сек после kernel panic
kernel.panic = 10

# Panic при Oops (не возвращаться в работу)
kernel.panic_on_oops = 1

# Panic при WARN (раскомментировать для строгого контроля)
# kernel.panic_on_warn = 1

# Panic при RCU stall
kernel.panic_on_rcu_stall = 1

# Soft lockup: panic через 4 сек
kernel.softlockup_panic = 1

# Hung task: panic через 120 сек (по умолчанию)
# kernel.hung_task_panic = 1

# Watchdog
kernel.watchdog = 1
EOF
```

### Параметры printk и dmesg

```bash
cat <<'EOF' | sudo tee /etc/sysctl.d/90-printk.conf
# Уровень вывода на консоль: 4 = KERN_WARNING
# Показывает warning и выше, исключая info/debug
kernel.printk = 4 4 1 7

# Ограничение доступа к dmesg (только root)
kernel.dmesg_restrict = 1

# Включить SysRq (для аварийного восстановления через SSH)
kernel.sysrq = 1
EOF
```

### Параметры сети

```bash
cat <<'EOF' | sudo tee /etc/sysctl.d/90-network.conf
# SYN cookies (защита от SYN flood)
net.ipv4.tcp_syncookies = 1

# SYN backlog
net.ipv4.tcp_max_syn_backlog = 65535
net.core.somaxconn = 65535

# SYN ack retries (по умолчанию 5, уменьшить для быстрого failover)
net.ipv4.tcp_synack_retries = 2

# TCP retries (по умолчанию 15 = ~13-30 мин)
net.ipv4.tcp_retries2 = 8

# Conntrack
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_buckets = 262144
net.netfilter.nf_conntrack_tcp_timeout_established = 3600
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30

# ARP table
net.ipv4.neigh.default.gc_thresh1 = 4096
net.ipv4.neigh.default.gc_thresh2 = 8192
net.ipv4.neigh.default.gc_thresh3 = 16384

# Network buffers
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# TCP keepalive
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 3
EOF
```

### Параметры памяти

```bash
cat <<'EOF' | sudo tee /etc/sysctl.d/90-memory.conf
# Overcommit: 0 = запретить, 1 = всегда разрешать, 2 = строгий
vm.overcommit_memory = 2
vm.overcommit_ratio = 80

# Swap: рекомендуется 10 для серверов
vm.swappiness = 10

# Dirty pages: % от RAM для отложенной записи
vm.dirty_ratio = 15
vm.dirty_background_ratio = 5

# Min free memory (MB):保証 minimum free RAM
vm.min_free_kbytes = 65536

# VFS cache: % от RAM для inode/dentry cache
vm.vfs_cache_pressure = 50

# Huge pages (если используются)
# vm.nr_hugepages = 1024
EOF
```

### Параметры файловых систем

```bash
cat <<'EOF' | sudo tee /etc/sysctl.d/90-fs.conf
# Max open files (системный лимит)
fs.file-max = 2097152

# Max inotify watches (для_MONIT_oring, IDE)
fs.inotify.max_user_watches = 524288

# Max queued events
fs.inotify.max_queued_events = 32768

# AIO (async I/O)
fs.aio-max-nr = 1048576
EOF
```

### Параметры производительности

```bash
cat <<'EOF' | sudo tee /etc/sysctl.d/90-performance.conf
# Scheduler: wenigcores = 1 (standalone), по умолчанию 0
# kernel.sched_autogroup_enabled = 0

# NUMA balancing: 0 = off (для latency-sensitive)
# kernel.numa_balancing = 0

# Transparent Huge Pages: 0 = madvise, 1 = always, 2 = never
# Для БД рекомендуется madvise или never
# vm.transparent_hugepage = madvise

# Performance governor через TuneD (рекомендуется)
# См. tuned.conf или tuned-adm profile throughput-performance
EOF
```

### Параметры безопасности

```bash
cat <<'EOF' | sudo tee /etc/sysctl.d/90-security.conf
# ASLR: 2 = полный, 1 = частичный, 0 = отключен
kernel.randomize_va_space = 2

# IP spoofing
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1

# ICMP redirects
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0

# Source routing
net.ipv4.conf.all.accept_source_route = 0

# SYN cookies (уже настроены выше, но для полноты)
# net.ipv4.tcp_syncookies = 1
EOF
```

### Проверка и валидация

```bash
# Применить все sysctl.d файлы
sudo sysctl --system

# Проверить ключевые параметры
echo "=== Kernel Emergency ==="
sysctl kernel.panic kernel.panic_on_oops kernel.softlockup_panic

echo "=== Printk ==="
sysctl kernel.printk kernel.dmesg_restrict kernel.sysrq

echo "=== Network ==="
sysctl net.ipv4.tcp_syncookies net.core.somaxconn net.netfilter.nf_conntrack_max

echo "=== Memory ==="
sysctl vm.swappiness vm.overcommit_memory vm.min_free_kbytes

echo "=== FS ==="
sysctl fs.file-max fs.inotify.max_user_watches
```

### Мониторинг изменений sysctl

```bash
#!/bin/bash
# /usr/local/bin/sysctl_audit.sh
# Проверка критических sysctl на соответствие ожидаемым значениям

EXPECTED=(
    "kernel.panic=10"
    "kernel.panic_on_oops=1"
    "kernel.dmesg_restrict=1"
    "net.ipv4.tcp_syncookies=1"
    "vm.swappiness=10"
)

for item in "${EXPECTED[@]}"; do
    param="${item%%=*}"
    expected_val="${item##*=}"
    actual_val=$(sysctl -n "$param" 2>/dev/null)
    if [ "$actual_val" != "$expected_val" ]; then
        echo "MISMATCH: $param = $actual_val (expected $expected_val)"
    fi
done
```

---

## Дополнительная информация

### Связанные темы

*   [**sysctl**](./sysctl.md) — обзор sysctl как инструмента.
*   [**Обзор dmesg**](../../Diagnostics/Kernel/dmesg/index.md) — архитектура kmsg.
*   [**Мониторинг dmesg**](../../SystemAdministration/Logging/dmesg_monitoring.md) — экспорт и алертинг.
*   [**TuneD**](./tuned.md) — автоматическая настройка через профили.
*   [**Kernel Panic**](./kernel_panic.md) — аварийное восстановление.
*   [**SysRq**](../../Diagnostics/Troubleshooting/reboot_troubleshooting.md) — аварийный reboot через SysRq.
*   [**Диагностика CPU**](../../Diagnostics/Performance/cpu_performance_diagnostics.md) — sysctl для CPU performance (swappiness, sched_autogroup).
*   [**Диагностика памяти**](../../Diagnostics/Performance/memory_performance_diagnostics.md) — sysctl для памяти (overcommit, dirty_ratio, swappiness).
*   [**Диагностика сети**](../../Diagnostics/Performance/network_performance_diagnostics.md) — sysctl для сети (buffers, somaxconn, bbr).
*   [**Диагностика контейнеров**](../../Diagnostics/Performance/container_performance_diagnostics.md) — cgroup sysctl и лимиты.
