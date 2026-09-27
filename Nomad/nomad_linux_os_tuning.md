# Nomad — Linux OS Tuning

## Определения

**OS Tuning для Nomad** — настройка параметров ядра Linux, подсистем ресурсов и системных сервисов для оптимальной работы Nomad-серверов и клиентов.

**cgroups v2** — механизм изоляции ресурсов ядра Linux, используемый драйверами Nomad (exec, exec2) для ограничения CPU, memory и I/O задач.

**ulimit** — параметрыlimits для процессов, определяющие максимальное количество файловых дескрипторов, процессов и другие ресурсы.

**systemd** — система инициализации и менеджер сервисов, используемая для управления Nomad-агентами как системными сервисами.

## Основные концепции

### Требования к узлам Nomad

| Параметр | Сервер | Клиент |
| :--- | :--- | :--- |
| **CPU** | 4+ cores | 2+ cores |
| **RAM** | 16+ GB | 8+ GB |
| **Disk** | 50+ GB (SSD/NVMe) | 50+ GB |
| **Network** | 1 Gbps+ | 1 Gbps+ |
| **OS** | Linux 5.10+ | Linux 5.10+ |

### Важные kernel-параметры

```bash
# /etc/sysctl.d/99-nomad.conf

# Networking
net.ipv4.ip_forward = 1
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1

# File system
fs.file-max = 2097152
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 8192

# Memory
vm.max_map_count = 262144
vm.swappiness = 10
vm.overcommit_memory = 1
vm.panic_on_oom = 0

# TCP/IP
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.ip_local_port_range = 1024 65535
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15

# Conntrack (для bridge-сети)
net.netfilter.nf_conntrack_max = 1048576
```

## Практические сценарии

### Сценарий 1: Установка Nomad через systemd

**nomad.service:**
```ini
[Unit]
Description=HashiCorp Nomad
Documentation=https://nomadproject.io/docs/
Wants=network-online.target
After=network-online.target

[Service]
Type=notify
User=nomad
Group=nomad
ExecStart=/usr/local/bin/nomad agent -config=/etc/nomad.d/
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5
LimitNOFILE=65536
LimitNPROC=infinity
LimitCORE=infinity
LimitMEMLOCK=infinity

# Безопасность
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadOnlyPaths=/etc/nomad.d
ReadWritePaths=/opt/nomad/data
ReadWritePaths=/var/log/nomad

[Install]
WantedBy=multi-user.target
```

**Установка:**
```bash
# Создание пользователя
useradd --system --home /etc/nomad.d --shell /bin/false nomad

# Установка бинарника
unzip nomad_*.zip -d /usr/local/bin/

# Создание директорий
mkdir -p /etc/nomad.d /opt/nomad/data /var/log/nomad
chown -R nomad:nomad /etc/nomad.d /opt/nomad/data /var/log/nomad

# Включение и запуск
systemctl daemon-reload
systemctl enable nomad
systemctl start nomad
```

### Сценарий 2: Настройка ulimit

** /etc/security/limits.d/nomad.conf:**
```
nomad  soft  nofile  65536
nomad  hard  nofile  65536
nomad  soft  nproc   65536
nomad  hard  nproc   65536
nomad  soft  memlock unlimited
nomad  hard  memlock unlimited
```

**Проверка:**
```bash
# От имени nomad
su - nomad -c "ulimit -n"
# → 65536

su - nomad -c "ulimit -l"
# → unlimited
```

### Сценарий 3: Настройка cgroups v2 для Exec2

**Проверка поддержки cgroups v2:**
```bash
stat -fc %T /sys/fs/cgroup
# → cgroup2fs (v2) или tmpfs (v1)
```

**Включение cgroups v2 (если v1):**
```bash
# В параметрах ядра
GRUB_CMDLINE_LINUX="systemd.unified_cgroup_hierarchy=1"
update-grub
reboot
```

**Конфигурация Exec2 с cgroups (client.hcl):**
```hcl
plugin "exec2" {
  config {
    cgroup_root = "/sys/fs/cgroup/nomad"
    oom_score_adj = -1000
  }
}
```

### Сценарий 4: Оптимизация дисковой подсистемы

**Для серверов Nomad (Raft):**
```bash
# Выбор I/O планировщика для NVMe
echo none > /sys/block/nvme0n1/queue/scheduler

# Оптимизация depth очереди
echo 1024 > /sys/block/nvme0n1/queue/nr_requests
```

**Для клиентов (allocations):**
```bash
# Монтирование с оптимальными опциями
mount -o noatime,nodiratime,discard /dev/sda1 /opt/nomad/data

# /etc/fstab
/dev/sda1 /opt/nomad/data ext4 noatime,nodiratime,discard 0 2
```

### Сценарий 5: Настройка сети для Nomad

**Bridge-сеть и NAT:**
```bash
# Включение IP forwarding
sysctl -w net.ipv4.ip_forward=1

# Правила iptables для Nomad bridge
iptables -t nat -A POSTROUTING -s 172.26.64.0/20 ! -o docker0 -j MASQUERADE
iptables -A FORWARD -i nomad0 -o eth0 -j ACCEPT
iptables -A FORWARD -i eth0 -o nomad0 -m state --state RELATED,ESTABLISHED -j ACCEPT
```

**Reserved ports (client.hcl):**
```hcl
client {
  reserved {
    reserved_ports = "22,80,443,8500,8200"
  }
}
```

### Сценарий 6: Мониторинг ресурсов узла

```bash
# Проверка CPU
mpstat -P ALL 1

# Проверка памяти
free -h
cat /proc/meminfo | grep -E "MemTotal|MemFree|Buffers|Cached"

# Проверка диска
iostat -xz 1
df -h /opt/nomad/data

# Проверка сети
sar -n DEV 1
ss -s
```

## Чеклист настройки узла

| Параметр | Сервер | Клиент | Команда проверки |
| :--- | :--- | :--- | :--- |
| kernel >= 5.10 | Да | Да | `uname -r` |
| cgroups v2 | Рекомендуется | Рекомендуется | `stat -fc %T /sys/fs/cgroup` |
| ip_forward=1 | Да | Да | `sysctl net.ipv4.ip_forward` |
| file-max >= 65536 | Да | Да | `sysctl fs.file-max` |
| vm.max_map_count >= 262144 | Да | Да | `sysctl vm.max_map_count` |
| ulimit nofile >= 65536 | Да | Да | `ulimit -n` |
| nomad user создан | Да | Да | `id nomad` |
| SSD/NVMe для данных | Да | Да | `lsblk -d -o name,rota` |

## Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `too many open files` | Недостаточный ulimit | Увеличьте nofile в limits.d |
| `cannot allocate memory` | Недостаточно RAM или swap | Добавьте RAM или уменьшите oversubscription |
| `cgroup mount failed` | cgroups v1/v2 conflict | Убедитесь в unified hierarchy |
| `disk I/O timeout` | Неверный scheduler | Переключите на none/mq-deadline |

## Дополнительная информация

- [Linux: cgroups](../Linux/Core/cgroups.md) — полная теория cgroups.
- [Linux: namespaces](../Linux/Core/namespaces.md) — изоляция процессов.
- [Linux: systemd](../Linux/Core/systemd/) — управление сервисами.
- [Nomad — определения и базовые концепции](./definitions_and_concepts.md) — архитектура Nomad.
