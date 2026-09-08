# Настройка параметров ядра (sysctl) — тюнинг и оптимизация

## Определения

**`sysctl`** — утилита и механизм ядра Linux, предназначенные для чтения и изменения параметров ядра в режиме реального времени (runtime) без необходимости перезагрузки системы.

**`/proc/sys/`** — виртуальная файловая система, через которую ядро экспортирует свои внутренние переменные в пространство пользователя. Утилита `sysctl` служит высокоуровневым интерфейсом к этой ФС, позволяя работать с параметрами в формате иерархических имен (например, `net.ipv4.ip_forward` вместо прямого обращения к пути `/proc/sys/net/ipv4/ip_forward`).

Тюнинг параметров ядра критически важен для адаптации ОС под специфические нагрузки: высокопроизводительные базы данных, узлы Kubernetes, сетевые шлюзы и системы с повышенными требованиями к безопасности (hardened).

## Внутренняя архитектура

### Механизм работы sysctl

Ядро экспонирует параметры через две виртуальные файловые системы:
- **`/proc/sys/`** — классический интерфейс sysctl. Параметры организованы в дерево каталогов, соответствующее их иерархии.
- **`/sys/` (sysfs)** — современный интерфейс для представления объектов ядра (устройств, драйверов, атрибутов). Некоторые параметры дублируются в sysfs для обратной совместимости.

Внутри ядра каждый параметр представлен структурой `ctl_table`, содержащей:
- Имя параметра
- Тип данных (int, string, bitmap)
- Максимальный/минимальный размер
- Указатель на обработчик (read/write callback)
- Атрибуты доступа (0644, 0600 и т.д.)

При записи в `/proc/sys/` ядро выполняет:
1. Проверку прав доступа (`capable(CAP_SYS_ADMIN)` или `ptrace_scope`)
2. Вызов обработчика write для изменения внутреннего состояния
3. Валидацию диапазона значений
4. Логирование в audit subsystem при включенном аудите

### Разница между sysctl и sysfs

| Характеристика | sysctl (`/proc/sys/`) | sysfs (`/sys/`) |
| :--- | :--- | :--- |
| Назначение | Глобальные параметры ядра | Объекты ядра и драйверов |
| Структура | Иерархия имен | Дерево kobject |
| Типы данных | int, long, string, ip_addr | Любые (через bin-файлы) |
| Современность | Устаревает | Активно развивается |
| Пример | `net.ipv4.ip_forward` | `/sys/class/net/eth0/speed` |

### Загрузка параметров при старте системы

Порядок загрузки sysctl-параметров при загрузке:
1. Параметры загрузчика GRUB (`/etc/default/grub` → `GRUB_CMDLINE_LINUX_DEFAULT`)
2. Ранний userspace (`/etc/sysctl.conf` через `systemd-sysctl.service`)
3. Модульные файлы из `/etc/sysctl.d/*.conf` (в лексикографическом порядке)
4. `/run/sysctl.d/*.conf` (временные, для live-патчей)
5. `/usr/lib/sysctl.d/*.conf` (пакетные, от дистрибутива)

## Основные концепции

### Иерархия параметров

Параметры сгруппированы по функциональным разделам, что отражается в их именовании:

- **`net.*`** — Сетевой стек. Управление TCP/IP, ARP, маршрутизацией, фильтрацией пакетов и дисциплинами очередей (qdisc).
- **`net.ipv4.*`** — Параметры IPv4.
- **`net.ipv6.*`** — Параметры IPv6.
- **`net.netfilter.*`** — Подсистема Netfilter (conntrack, NAT).
- **`net.bridge.*`** — Параметры мостов (br_netfilter).
- **`vm.*`** — Виртуальная память. Настройка агрессивности Swap, лимитов на маппинг памяти (`max_map_count`) и алгоритмов очистки кэша.
- **`kernel.*`** — Общие свойства ядра. Лимиты на PID, безопасность eBPF, параметры планировщика и поведение при сбоях (Panic).
- **`fs.*`** — Файловые системы. Лимиты на количество открытых дескрипторов (`file-max`), квоты и подписки `inotify`.
- **`sunrpc.*`** — Параметры NFS/RPC.
- **`user.*`** — Лимиты ресурсов для пространств имён пользователей (user namespaces).
- **`dev.*`** — Параметры устройств (RAID, USB).
- **`kernel.sched.*`** — Параметры планировщика CFS.
- **`kernel.panic*`** — Поведение при панике ядра.
- **`kernel.apparmor.*`** — Параметры AppArmor.

### Ключевые параметры для современных систем (2024-2026)

#### Сетевой стек

| Параметр | Описание | Рекомендуемое значение (High Load) |
| :--- | :--- | :--- |
| `net.ipv4.tcp_congestion_control` | Алгоритм управления перегрузкой. | `bbr` (BBRv3 в ядрах 6.x) |
| `net.core.default_qdisc` | Дисциплина очередей по умолчанию. | `fq` (необходимо для BBR) |
| `net.core.somaxconn` | Максимальный размер очереди сокетов. | `65535` |
| `net.ipv4.ip_forward` | Включение IP-forwarding (L3-маршрутизация). | `1` (для шлюзов/K8s) |
| `net.ipv4.tcp_tw_reuse` | Повторное использование TIME_WAIT сокетов. | `1` |
| `net.ipv4.tcp_fin_timeout` | Таймаут FIN-WAIT-2. | `15` |
| `net.ipv4.tcp_keepalive_time` | Время до отправки keepalive. | `600` |
| `net.ipv4.tcp_keepalive_intvl` | Интервал между keepalive. | `30` |
| `net.ipv4.tcp_keepalive_probes` | Количество попыток keepalive. | `3` |
| `net.ipv4.tcp_max_syn_backlog` | Очередь полуоткрытых соединений. | `16384` |
| `net.ipv4.ip_local_port_range` | Диапазон эфемерных портов. | `1024 65535` |
| `net.ipv4.tcp_syncookies` | Защита от SYN-флуда. | `1` (Enabled) |
| `net.ipv4.conf.all.rp_filter` | Обратная фильтрация пакетов. | `1` |
| `net.ipv4.conf.all.accept_redirects` | Приём ICMP redirect. | `0` |
| `net.ipv4.conf.all.arp_announce` | Ограничение ARP-ответов. | `2` |
| `net.ipv4.conf.all.arp_ignore` | Игнорирование ARP-запросов. | `1` |
| `net.netfilter.nf_conntrack_max` | Максимум записей conntrack. | `1048576` |
| `net.netfilter.nf_conntrack_tcp_timeout_established` | Таймаут установленных соединений. | `3600` |
| `net.netfilter.nf_conntrack_tcp_timeout_time_wait` | Таймаут TIME_WAIT в conntrack. | `30` |
| `net.core.netdev_max_backlog` | Очередь пакетов на интерфейсе. | `5000` |
| `net.core.busy_poll` | Активный опрос драйвера (мкс). | `50` |
| `net.core.busy_read` | Активный опрос при чтении (мкс). | `50` |

#### Виртуальная память

| Параметр | Описание | Рекомендуемое значение |
| :--- | :--- | :--- |
| `vm.swappiness` | Агрессивность использования Swap. | `10` (для SSD/NVMe) |
| `vm.vfs_cache_pressure` | Очистка dentry/inode cache. | `50` |
| `vm.max_map_count` | Лимит memory map areas. | `262144` (Elasticsearch, Redis) |
| `vm.dirty_ratio` | % RAM, при котором синхронизация блокирует writers. | `10` |
| `vm.dirty_background_ratio` | % RAM, при котором запускается фоновая запись. | `5` |
| `vm.overcommit_memory` | Политика overcommit памяти. | `0` (heuristic) или `1` (always) |
| `vm.overcommit_ratio` | % RAM + Swap при overcommit_memory=2. | `50` |
| `vm.nr_hugepages` | Количество заранее зарезервированных HugePages. | `1024` (для БД, VMs) |
| `vm.hugetlb_shm_group` | GID для разделения HugePages через shmget. | `0` (или группа) |
| `vm.transparent_hugepage.defrag` | Политика дефрагментации THP. | `never` (для БД) |
| `vm.transparent_hugepage.enabled` | Включение THP. | `never` (для latency-sensitive) |

#### Безопасность и ограничения

| Параметр | Описание | Рекомендуемое значение |
| :--- | :--- | :--- |
| `kernel.randomize_va_space` | Рандомизация адресного пространства (ASLR). | `2` (Full ASLR) |
| `kernel.kptr_restrict` | Скрытие адресов ядра в `/proc/kallsyms`. | `2` |
| `kernel.dmesg_restrict` | Запрет чтения dmesg обычными пользователями. | `1` |
| `kernel.perf_event_paranoid` | Ограничение perf для непривилегированных. | `3` |
| `kernel.yama.ptrace_scope` | Ограничение ptrace. | `2` |
| `kernel.unprivileged_bpf_disabled` | Отключение eBPF для непривилегированных. | `1` |
| `kernel.modules_disabled` | Запрет загрузки модулей после старта. | `0` (runtime) или `1` (post-init) |
| `kernel.pid_max` | Максимальный PID в системе. | `4194304` (для плотных K8s узлов) |
| `kernel.sched_rt_period_us` | Период для SCHED_FIFO/RR. | `1000000` |
| `kernel.sched_rt_runtime_us` | Доступное время для реального времени. | `950000` |
| `fs.protected_fifos` | Защита FIFO от открытия из world-writable каталогов. | `2` |
| `fs.protected_regular` | Защита обычных файлов. | `2` |
| `fs.protected_symlinks` | Защита от symlink-атак. | `1` |
| `fs.protected_hardlinks` | Защита от hardlink-атак. | `1` |
| `kernel.apparmor_restrict_unprivileged_userns` | Ограничение userns в AppArmor. | `0` (если нужны rootless-контейнеры) |

## Практические сценарии

### Основные команды управления

```bash
# Вывести все текущие параметры системы
sysctl -a

# Получить значение конкретного параметра
sysctl net.ipv4.ip_forward

# Временное изменение параметра (до перезагрузки)
sudo sysctl -w net.ipv4.ip_forward=1

# Чтение напрямую из /proc/sys/
cat /proc/sys/net/ipv4/ip_forward
```

### Постоянное сохранение настроек

Для обеспечения персистентности настроек используются файлы конфигурации.

- **`/etc/sysctl.conf`** — классический файл (устаревает, не рекомендуется для новых настроек).
- **`/etc/sysctl.d/*.conf`** — современный модульный стандарт. Файлы загружаются в лексикографическом порядке (например, `99-performance.conf` перекроет `10-defaults.conf`).

**Правила именования файлов:**
- Используйте префикс из двух цифр для контроля порядка загрузки.
- Именуйте файлы по назначению: `99-networking.conf`, `90-security.conf`, `80-vm.conf`.

**Эталонная конфигурация `/etc/sysctl.d/99-performance.conf`:**
```conf
# --- Сетевая производительность ---
# Включение BBRv3 (требует ядро 6.x и fq)
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# Оптимизация буферов для 10Gbps+ сетей
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728
net.ipv4.tcp_rmem = 4096 87380 134217728
net.ipv4.tcp_wmem = 4096 65536 134217728

# Масштабируемость соединений
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 16384
net.ipv4.tcp_tw_reuse = 1
net.ipv4.ip_local_port_range = 1024 65535

# --- Conntrack ---
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_tcp_timeout_established = 3600
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30

# --- Виртуальная память и MGLRU ---
vm.swappiness = 10
vm.vfs_cache_pressure = 50
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5
vm.max_map_count = 262144

# --- Безопасность (Hardening) ---
# Для комплексного харденинга см. SSoT: [Харденинг ядра Linux](../../Security/Mechanisms/Kernel/hardening.md)
# Защита от SYN атак и спуфинга
net.ipv4.tcp_syncookies = 1
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
# Отключение редиректов (защита от MITM)
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
# Ограничение доступа к dmesg и JIT
kernel.dmesg_restrict = 1
net.core.bpf_jit_harden = 2
kernel.randomize_va_space = 2
```

### Применение конфигурации

```bash
# Применить изменения из всех файлов (/etc/sysctl.d/, /run/sysctl.d/ и т.д.)
sudo sysctl --system

# Применить изменения из конкретного файла вручную
sudo sysctl -p /etc/sysctl.d/99-performance.conf

# Проверить, что параметр изменился
sysctl net.ipv4.ip_forward
# → net.ipv4.ip_forward = 1
```

### Тюнинг MGLRU (Multi-Gen LRU)

В новых ядрах (6.1+) механизм MGLRU значительно повышает производительность при нехватке памяти. Его настройка производится через `/sys/kernel/mm/lru_gen/`, но часто дублируется в скриптах тюнинга.

```bash
# Включение всех компонентов MGLRU (Aging, Eviction, Tiering)
echo 7 > /sys/kernel/mm/lru_gen/enabled

# Проверка статистики
cat /sys/kernel/mm/lru_gen/faults
```

## Тюнинг для конкретных рабочих нагрузок

### Базы данных (PostgreSQL, MySQL, Redis)

```bash
# /etc/sysctl.d/99-database.conf

# Виртуальная память
vm.swappiness = 10
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5
vm.max_map_count = 262144
vm.nr_hugepages = 1024

# Отключение THP для PostgreSQL/MySQL
echo never > /sys/kernel/mm/transparent_hugepage/enabled
echo never > /sys/kernel/mm/transparent_hugepage/defrag

# Сеть
net.core.somaxconn = 65535
net.ipv4.tcp_tw_reuse = 1
```

### Виртуализация (KVM/QEMU)

```bash
# /etc/sysctl.d/99-virt.conf

# Разрешение forwarding для мостов
net.ipv4.ip_forward = 1
net.ipv4.conf.all.forwarding = 1

# MACVLAN
net.ipv4.conf.all.proxy_arp = 0

# HugeTLB
vm.nr_hugepages = 2048
```

### Высоконагруженные веб-серверы (Nginx/Angie)

```bash
# /etc/sysctl.d/99-web.conf

net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 16384
net.ipv4.ip_local_port_range = 1024 65535
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
net.core.netdev_max_backlog = 5000
```

## Тюнинг в Kubernetes

В Kubernetes параметры `sysctl` делятся на:
- **Безопасные (Safe):** Можно настраивать в `PodSpec` через `securityContext.sysctls` (например, `net.ipv4.tcp_keepalive_time`).
- **Небезопасные (Unsafe):** Требуют явного разрешения в конфиге `kubelet` узла (параметр `--allowed-unsafe-sysctls`).

**Пример манифеста Pod:**
```yaml
securityContext:
  sysctls:
  - name: net.core.somaxconn
    value: "16384"
  - name: net.ipv4.tcp_keepalive_time
    value: "600"
```

**Для небезопасных sysctl:**
```bash
# Запуск kubelet с разрешением
kubelet --allowed-unsafe-sysctls=net.ipv4.tcp_rmem,net.ipv4.tcp_wmem
```

## Диагностика и устранение неполадок

### Проверка текущих значений

```bash
# Все параметры TCP
sysctl -a | grep net.ipv4.tcp

# Критичные параметры
sysctl net.ipv4.tcp_rmem net.ipv4.tcp_wmem \
  net.ipv4.tcp_congestion_control net.core.somaxconn \
  net.ipv4.tcp_syncookies vm.swappiness

# Проверка через ss для конкретного соединения
ss -tin dst 10.0.0.1 | grep -E "rcv_space|snd_space|cwnd|rtt"

# Глобальные счетчики TCP
nstat -az | grep -E "TcpRetrans|ListenOverflows|ListenDrops|TcpExtTCPTimeouts"
```

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `sysctl: setting key "net.ipv4.ip_forward": Invalid argument` | Параметр закомпилирован как модуль или отсутствует | Проверить `grep CONFIG_IP_ADVANCED /boot/config-$(uname -r)` |
| `sysctl: permission denied` | Недостаточно прав или `kernel.unprivileged_userns_clone=0` | `sudo sysctl ...` или проверить AppArmor/SELinux |
| `Operation not permitted` при записи в `/proc/sys/` | Аудит или seccomp-фильтр блокирует запись | Проверить `dmesg | grep -i audit` |
| Параметр не применяется после `sysctl --system` | Конфликт с более поздним файлом в `/usr/lib/sysctl.d/` | Использовать `sysctl --system --verbose` для отладки порядка загрузки |
| `nf_conntrack: table full, dropping packet` | Переполнение conntrack table | `sysctl -w net.netfilter.nf_conntrack_max=2097152` |
| `kernel: TCP: request_sock_TCP: Possible SYN flooding` | SYN-флуд, `tcp_max_syn_backlog` исчерпан | Увеличить `tcp_max_syn_backlog` и `somaxconn` |

### Валидация изменений

```bash
# 1. Применить конфигурацию
sudo sysctl --system

# 2. Проверить конкретные параметры
sysctl net.ipv4.tcp_congestion_control
sysctl net.core.somaxconn

# 3. Проверить через ss (сетевые очереди)
ss -s
ss -ltn | head -20

# 4. Проверить nstat (счётчики ядра)
nstat -az | grep -E "TcpExtListen|TcpRetrans|TcpExtTCP"

# 5. Проверить логи dmesg на ошибки
dmesg | tail -20
```

## Автоматизация через Ansible

Для массового применения конфигураций используйте модуль `ansible.posix.sysctl`:

```yaml
- name: Тюнинг виртуальной памяти через sysctl
  ansible.posix.sysctl:
    name: vm.swappiness
    value: '10'
    sysctl_set: true
    reload: true
    sysctl_file: /etc/sysctl.d/99-performance.conf
    state: present

- name: Настройка сети для high-load
  ansible.posix.sysctl:
    name: "{{ item.name }}"
    value: "{{ item.value }}"
    sysctl_set: true
    reload: true
  loop:
    - { name: 'net.core.somaxconn', value: '65535' }
    - { name: 'net.ipv4.tcp_congestion_control', value: 'bbr' }
    - { name: 'net.ipv4.tcp_tw_reuse', value: '1' }
```

## Взаимодействие с cgroup v2

В cgroup v2 параметры sysctl и cgroup-ограничения могут взаимодействовать:

- **Приоритет cgroup:** Параметры, заданные через cgroup (например, `cpu.max`), имеют приоритет над глобальными sysctl для процессов в этом cgroup.
- **Безопасные sysctl в PodSpec:** Только определённый набор параметров можно задавать напрямую через Kubernetes.
- **bpffs и cgroup:** eBPF-программы, прикреплённые к cgroup, могут видеть и изменять сетевые параметры через хелперы.

Пример:
```bash
# Создание cgroup с ограничениями
mkdir -p /sys/fs/cgroup/nginx
echo "50000 100000" > /sys/fs/cgroup/nginx/cpu.max
echo "2G" > /sys/fs/cgroup/nginx/memory.max

# Применение sysctl только для этого cgroup
sudo sysctl -w net.ipv4.tcp_syncookies=1
```

## Дополнительная информация

### Связанные темы

- **Интерфейсы ядра:** [Интерфейсы ядра Linux](./kernel_interfaces.md) — роль Syscalls и виртуальных ФС.
- **Харденинг:** [Харденинг ядра Linux](../../Security/Mechanisms/Kernel/hardening.md) — комплексная настройка безопасности.
- **Сетевая оптимизация:** [Оптимизация TCP в Linux](../../Networking/Concepts/tcp_tuning/tcp_tuning_overview.md) — подробнее о логике BBR, буферов и очередей.
- **TCP-диагностика:** [sysctl — сводка параметров TCP](../../../Networking/ServicesAndTools/Wireshark/sysctl_tcp_cheatsheet.md) — связь параметров с симптомами в Wireshark.
- **Тюнинг памяти:** [Performance Tuning](../memory/performance_tuning.md) — глубокая настройка подсистемы виртуальной памяти.
- **Диагностика:** [Анализ Kernel Panic](./kernel_panic.md) — использование `kernel.panic` для автоматической перезагрузки.
- **Контейнеры:** [Rootless Podman](../../../Podman/podman_rootless.md) — sysctl для непривилегированных контейнеров.

### Полезные ссылки

- [Документация ядра: sysctl/net](https://www.kernel.org/doc/Documentation/networking/ip-sysctl.txt)
- [Документация ядра: sysctl/vm](https://www.kernel.org/doc/Documentation/sysctl/vm.txt)
- [Kernel.org — sysctl(8)](https://www.kernel.org/doc/man-pages/online/pages/man8/sysctl.8.html)
- [CIS Benchmarks — Linux](https://www.cisecurity.org/cis-benchmarks/)
