# Ядерные параметры и тюнинг ОС для etcd

**etcd** чрезвычайно чувствителен к задержкам диска, сети и планировщику процессов. Правильная настройка ОС (sysctl, CPU governor, ionice) — это prerequisite для production. Данный документ описывает конкретные параметры и их обоснование.

## Определения

| Термин | Описание |
| :--- | :--- |
| **sysctl** | Утилита для настройки параметров ядра Linux во время выполнения. |
| **ionice** | Утилита для установки приоритета I/O-операций процесса. |
| **nice** | Утилита для изменения приоритета CPU-планировщика. |
| **CPU Governor** | Политика управления частотой CPU. `performance` — фиксированная высокая частота. |
| **isolcpus** | Параметр ядра для выделения CPU-ядер под конкретные процессы. |
| **vm.swappiness** | Склонность ядра перемещать страницы в swap. Для etcd должна быть 0. |
| **net.core.somaxconn** | Максимальная длина очереди ожидающих TCP-соединений. |
| **LimitNOFILE** | Максимальное количество файловых дескрипторов для процесса (systemd). |

---

## Основные концепции

### sysctl параметры

```bash
# /etc/sysctl.d/99-etcd.conf
# Защита от swap (etcd не должен попадать в swap)
vm.swappiness = 0

# Длинные очереди для listen() (Watch-соединения)
net.core.somaxconn = 4096

# Увеличение буферов TCP для высоконагруженных кластеров
net.ipv4.tcp_rmem = 4096 87380 6291456
net.ipv4.tcp_wmem = 4096 87380 6291456

# Отключение TCP SACK (уменьшает задержку в некоторых сценариях)
net.ipv4.tcp_sack = 0

# Увеличение backlog для passive sockets
net.core.netdev_max_backlog = 5000

# Время удержания TCP-соединений в TIME_WAIT
net.ipv4.tcp_fin_timeout = 15
```

**Применение:**
```bash
sysctl --system
```

### Приоритеты процессов (ionice + nice)

```bash
# Запуск etcd с максимальным приоритетом I/O и CPU
ionice -c2 -n0 nice -n -10 etcd --config-file /etc/etcd/etcd.conf.yml
```

**В systemd-юните:**
```ini
[Service]
ExecStart=
ExecStart=/usr/bin/etcd --config-file /etc/etcd/etcd.conf.yml
Nice=-10
IOSchedulingClass=realtime
IOSchedulingPriority=0
```

**Обоснование:**
- `nice=-10` — высокий приоритет CPU (etcd обрабатывает Protobuf и Raft).
- `ionice -c2 -n0` — real-time I/O priority (WAL fsync не прерывается другими процессами).

### CPU Governor

```bash
# Установить performance governor (минимизация переключений частоты)
cpupower frequency-set -g performance

# Или через cpufreq
echo performance > /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
```

**Обоснование:** Transition между частотами CPU добавляет джиттер к обработке heartbeats. В production используется фиксированная высокая частота.

### CPU Isolation (isolcpus)

Для критически важных ядер:

```bash
# /etc/default/grub
GRUB_CMDLINE_LINUX="... isolcpus=2,3 systemd.cpu_affinity=0,1"

# После изменения
update-grub && reboot
```

**Обоснование:** Ядра 2,3 выделяются для etcd. Никакой другой процесс не может их занимать, что гарантирует мгновенную обработку heartbeat-сообщений.

### Лимиты файловых дескрипторов

```ini
# /etc/systemd/system/etcd.service.d/limits.conf
[Service]
LimitNOFILE=65536
```

```bash
# Проверить действующий лимит
cat /proc/$(pgrep etcd)/limits | grep "open files"
# → Max open files            65536                65536                files
```

**Обоснование:** Каждый Watch-соединение, клиентское подключение и файл WAL потребляют дескриптор. При > 40 000 соединений лимит 1024 (по умолчанию) приведёт к отказу новых подключений.

### Выделенный диск для WAL

Для минимальной задержки `fdatasync` размещайте WAL на отдельном физическом диске:

```bash
# Структура дисков
/dev/nvme0n1 → ОС + docker/containerd
/dev/nvme1n1 → /var/lib/etcd/wal (только WAL)
/dev/nvme2n1 → /var/lib/etcd/member (данные + снапшоты)
```

Или через символические ссылки:
```bash
mv /var/lib/etcd/member/wal /var/lib/etcd/wal
ln -s /var/lib/etcd/wal /var/lib/etcd/member/wal
```

---

## Практические сценарии

### Полная настройка нового узла etcd

```bash
# 1. sysctl
cat <<EOF > /etc/sysctl.d/99-etcd.conf
vm.swappiness = 0
net.core.somaxconn = 4096
net.core.netdev_max_backlog = 5000
net.ipv4.tcp_fin_timeout = 15
EOF
sysctl --system

# 2. CPU governor
cpupower frequency-set -g performance

# 3. systemd limits
mkdir -p /etc/systemd/system/etcd.service.d
cat <<EOF > /etc/systemd/system/etcd.service.d/limits.conf
[Service]
LimitNOFILE=65536
Nice=-10
IOSchedulingClass=realtime
IOSchedulingPriority=0
EOF
systemctl daemon-reload

# 4. Проверка
systemctl show etcd | grep -E "Nice|IOScheduling|LimitNOFILE"
```

### Мониторинг эффективности тюнинга

```bash
# Задержка fdatasync (должна быть < 1 ms p99)
curl -s http://localhost:2379/metrics | grep etcd_disk_wal_fsync_duration_seconds

# Использование CPU
mpstat -P ALL 1 5

# Ожидание I/O
iostat -x 1 5

# Context switches
pidstat -w -p $(pgrep etcd) 1
```

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `fdatasync` > 10 ms | Диск не NVMe, governor наdemand, или high iowait | Перейти на NVMe; установить `performance` governor; проверить `iostat` |
| Высокий `%iowait` | Другие процессы конкурируют за диск | `ionice` для etcd; выделить отдельный диск |
| Лидер flapping | Сетевой джиттер + CPU throttling | Увеличить `election-timeout`; выделить CPU via `isolcpus` |
| `Too many open files` | `LimitNOFILE` слишком мал | Увеличить до 65536; проверить `ulimit -n` |
| Высокий `cs` (context switches) | Много процессов на узле | Выделить отдельные ядра для etcd через `isolcpus` |

---

## Best Practices

- **Все параметры в etcd.conf.yml + systemd:** Не передавайте флаги через command line в Static Pod.
- **`LimitNOFILE=65536`:** Обязательно для production.
- **Отдельный диск для WAL:** Минимизирует задержку `fdatasync`.
- **`vm.swappiness = 0`:** Никогда не используйте swap для etcd.
- **Performance governor:** Фиксированная частота CPU исключает джиттер.
- **ionice + nice:** Гарантируют приоритет etcd при общей нагрузке на узел.

---

## Edge Cases

- **Container runtime:** Если etcd запущен в контейнере, убедитесь, что контейнер имеет права `SYS_NICE` и `IPC_LOCK` (для mlock).
- **Virtualization:** В виртуализированных средах (ESXi, KVM) убедитесь, что CPU Governor настроен на host level, а не только внутри VM.
- **Throttling на уровне облака:** В AWS/GCP/Azure проверьте лимиты CPU burst (credits). etcd требует стабильной производительности, а не burst.
- **NUMA:** Для multi-socket серверов размещайте etcd (и особенно WAL) на NUMA-ноде, соответствующей CPU-ядрам.

---

## См. также

* **[Конфигурация и развертывание](./configuration_and_deployment.md)** — systemd и Static Pod.
* **[Архитектура и основные концепции](./architecture-and-concepts.md)** — аппаратные требования.
* **[Raft консенсус](./raft_consensus.md)** — влияние задержек на выборы лидера.
