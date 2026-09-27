# Базовый чеклист настройки производительности сервера

## Определения

- **Performance Baseline (Базовая линия производительности):** Набор параметров системы, установленных при развёртывании сервера для обеспечения предсказуемого поведения при нагрузке. Включает параметры ядра (sysctl), лимиты процессов (limits.conf), настройки планировщика и параметры файловой системы.
- **sysctl:** Механизм настройки параметров ядра Linux в runtime через `/proc/sys/` или утилиту `sysctl`. Параметры делятся на: network, vm, kernel, fs. Применяются без перезагрузки.
- **limits.conf:** Файл `/etc/security/limits.conf` и директория `/etc/security/limits.d/` для установки ресурсных лимитов пользователей и процессов (open files, max processes, memory size).
- **ulimit:** Команда для просмотра и изменения ресурсных лимитов текущего процесса и его дочерних. Является обёрткой над `setrlimit`/`getrlimit` системными вызовами.

---

## Базовые концепции

### Иерархия приоритетов настроек

Параметры применяются в следующем порядке (последний перекрывает предыдущий):

```
/etc/sysctl.d/00-default.conf     — дефолты ядра (не трогать)
/etc/sysctl.d/50-*.conf           — стандартные настройки дистрибутива
/etc/sysctl.d/90-*.conf           — наши настройки (ПЕРЕОПРЕДЕЛЯЮТ 50-*)
/etc/sysctl.d/99-*.conf           — кастомные настройки (ПЕРЕОПРЕДЕЛЯЮТ 90-*)
/etc/sysctl.conf                  — legacy (устаревает)

/etc/security/limits.conf         — глобальные лимиты
/etc/security/limits.d/*.conf     — переопределения (последний файл побеждает)
```

### Применение sysctl

```bash
# Временное (до перезагрузки)
sudo sysctl -w net.core.somaxconn=65535

# Постоянное
echo "net.core.somaxconn = 65535" | sudo tee /etc/sysctl.d/90-network.conf
sudo sysctl --system

# Проверка
cat /proc/sys/net/core/somaxconn
sysctl net.core.somaxconn
```

---

## Практические сценарии

### 1. Сетевые параметры (высоконагруженные серверы)

```bash
cat <<'EOF' | sudo tee /etc/sysctl.d/90-network-performance.conf
# --- TCP backlog ---
# Максимальная очередь входящих соединений (SYNC_RECV)
net.core.somaxconn = 65535

# Максимальная очередь пакетов, ожидающих обработки ядром
net.core.netdev_max_backlog = 65535

# --- TCP buffer sizing ---
# min/max/default接收缓冲区 (в байтах)
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576

# min/pressure/max发送缓冲区 (в байтах, TCP автоматически масштабирует)
net.ipv4.tcp_rmem = 4096 1048576 16777216
net.ipv4.tcp_wmem = 4096 1048576 16777216

# --- TCP connection handling ---
# Включить TCP window scaling (RFC 1323)
net.ipv4.tcp_window_scaling = 1

# Включить TCP timestamps
net.ipv4.tcp_timestamps = 1

# Включить Selective Acknowledgments (SACK)
net.ipv4.tcp_sack = 1

# Максимальное количество FIN_WAIT2 соединений
net.ipv4.tcp_max_tw_buckets = 2000000

# Ускорить.recycle TIME_WAIT (осторожно: может ломать за NAT)
net.ipv4.tcp_tw_reuse = 1

# Увеличить ephemeral port range
net.ipv4.ip_local_port_range = 1024 65535

# --- SYN flood protection ---
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_synack_retries = 2

# --- Keepalive (обнаружение мертвых соединений) ---
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 5
EOF

sudo sysctl --system
```

### 2. Параметры памяти

```bash
cat <<'EOF' | sudo tee /etc/sysctl.d/90-memory.conf
# --- Overcommit ---
# 0: heuristic (по умолчанию), 1: всегда разрешать, 2: строгий контроль
vm.overcommit_memory = 0

# Порог для heuristics (в процентах от RAM)
vm.overcommit_ratio = 50

# --- Swap ---
# Склонность к свопированию (0-100, чем меньше, тем меньше свопа)
vm.swappiness = 10

# --- Dirty pages ---
# Максимум dirty pages (% от RAM) перед началом写了
vm.dirty_ratio = 15

# Порог начала фоновой записи (% от RAM)
vm.dirty_background_ratio = 5

# Таймаут для dirty pages (в сотых долях секунды)
vm.dirty_writeback_centisecs = 500
vm.dirty_expire_centisecs = 3000

# --- Huge Pages ---
# Отключить transparent huge pages для БД (MongoDB, PostgreSQL)
# echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
# echo never | sudo tee /sys/kernel/mm/transparent_hugepage/defrag

# Количество огромных страниц (0 = отключить)
vm.nr_hugepages = 0
EOF

sudo sysctl --system
```

### 3. Параметры файловой системы

```bash
cat <<'EOF' | sudo tee /etc/sysctl.d/90-filesystem.conf
# --- File handles ---
# Максимум файловых дескрипторов в системе
fs.file-max = 2097152

# Максимум inotify watches (для мониторинга файлов)
fs.inotify.max_user_watches = 524288

# Максимум inotify instances
fs.inotify.max_user_instances = 1024

# Максимум очереди AIO
fs.aio-max-nr = 1048576
EOF

sudo sysctl --system
```

### 4. Параметры ядра и безопасности

```bash
cat <<'EOF' | sudo tee /etc/sysctl.d/90-kernel.conf
# --- Kernel panic ---
# Автоматическая перезагрузка через 10 сек после kernel panic
kernel.panic = 10

# Panic при Oops
kernel.panic_on_oops = 1

# --- PID ---
# Максимальный PID (по умолчанию 32768, увеличить для контейнеров)
kernel.pid_max = 4194304

# --- Yama ptrace ---
# 0: unrestricted, 1: parent-only, 2: admin-only, 3: disabled
kernel.yama.ptrace_scope = 1

# --- Randomize VA space ---
# 0: off, 1: mmap randomization, 2: full randomization
kernel.randomize_va_space = 2
EOF

sudo sysctl --system
```

### 5. Лимиты процессов (limits.conf)

```bash
cat <<'EOF' | sudo tee /etc/security/limits.d/99-server.conf
# --- Open files ---
*    soft    nofile    1048576
*    hard    nofile    1048576
root soft    nofile    1048576
root hard    nofile    1048576

# --- Max processes/threads ---
*    soft    nproc     65535
*    hard    nproc     65535

# --- Core dumps ---
*    soft    core      0
*    hard    core      0

# --- Memory (MB) ---
*    soft    memlock   unlimited
*    hard    memlock   unlimited
EOF
```

> **Важно:** Для systemd-сервисов лимиты задаются в unit-файле через `LimitNOFILE=`, `LimitNPROC=`, `LimitCORE=`. Значения из `limits.conf` применяются только к процессам, запущенным через PAM-сессии (ssh, login, sudo).

### 6. Проверка текущего состояния

```bash
# sysctl
sysctl -a | grep -E "somaxconn|file-max|tcp_keepalive|swappiness|overcommit"

# Лимиты текущего процесса
ulimit -a

# Лимиты конкретного PID
cat /proc/<PID>/limits

# Количество открытых файловых дескрипторов
cat /proc/<PID>/fd | wc -l

# Системные лимиты
cat /proc/sys/fs/file-nr     # allocated / unused / max
cat /proc/sys/fs/file-max    # system-wide max
```

### 7. Диагностика типичных проблем

| Симптом | Причина | Проверка | Решение |
| :--- | :--- | :--- | :--- |
| `Too many open files` | Лимит nofile исчерпан | `cat /proc/PID/limits \| grep "open files"` | Увеличить `LimitNOFILE=` в unit-файле |
| `Cannot allocate memory` | overcommit отклонил | `dmesg \| grep -i oom` | Настроить `vm.overcommit_*` |
| TCP connection refused | somaxconn исчерпан | `ss -s \| grep -i listen` | Увеличить `net.core.somaxconn` |
| Высокий swap при нормальной RAM | swappiness слишком высокий | `free -h`, `swapon -s` | Снизить `vm.swappiness` |
| Slowloris-атака / SYN flood | syncookies отключены | `sysctl net.ipv4.tcp_syncookies` | Включить `tcp_syncookies = 1` |

---

## Дополнительная информация

### См. также

- **[sysctl для production-окружения](../Core/kernel/sysctl_production.md)** — полный справочник параметров ядра с категориями и описаниями.
- **[sysctl: Обзор](../Core/kernel/sysctl.md)** — архитектура `/proc/sys/`, `ctl_table`, безопасность записи.
- **[Параметры сети](../Networking/Settings/sysctl_network.md)** — сетевые sysctl-параметры с описанием каждого.
- **[Управление памятью](../Core/memory/performance_tuning.md)** — настройка кэширования, swap, huge pages.
- **[Файловые дескрипторы](../FileSystems/file_descriptors.md)** — архитектура FD, epoll, limts.
- **[Troubleshooting: Too many open files](../Diagnostics/Troubleshooting/troubleshooting_too_many_open_files.md)** — пошаговое устранение проблем с FD.
- **[OOM Killer](../Core/processes/oom_killer_mechanism.md)** — механизм работы и настройка OOM.
- **[cgroups](../Core/cgroups.md)** — изоляция ресурсов через контрольные группы.
