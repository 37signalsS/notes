# Samba: Кластеризация и высокая доступность

## Определения

**CTDB (Cluster Trivial Database)** — кластерный сервис Samba, обеспечивающий совместное управление базами данных (TDB) между узлами кластера. Позволяет создавать отказоустойчивые файловые кластеры с единым пространством имен (virtual IP) и автоматическим переключением при сбое (failover).

**Witness Protocol** — протокол, позволяющий клиентам Windows/macOS получать уведомления о��态 кластера и мгновенно переключаться на резервный узел при падении основного. Реализован в CTDB и поддерживается начиная с Windows Vista/Server 2008.

**Virtual IP (VIP)** — IP-адрес, принадлежащий кластеру в целом, а не отдельному узлу. Перемещается между узлами при failover. Клиенты подключаются к VIP, что делает переключение прозрачным.

**Reclock (Recovery Lock)** — механизм предотвращения split-brain в CTDB. Использует общую файловую систему для атомарной блокировки, гарантируя, что только один узел является styling CTDB-лидером в любой момент времени.

**Public IP** — IP-адрес, привязанный к конкретному сервису (шаре) на кластере. CTDB может переключать Public IP между узлами для балансировки нагрузки или failover.

**Clustered Samba (Active/Active)** — режим работы, при котором несколько узлов кластера одновременно обслуживают клиентов, используя общую распределенную файловую систему (GFS2, GlusterFS, CephFS).

**Node Status Script** — пользовательский скрипт (обычно `/etc/ctdb/events.d/` или `/usr/lib/ctdb/events.d/`), определяющий, здоров ли узел и способен ли он обслуживать VIP. CTDB вызывает его при принятии решений о failover.

**Banned Node** — узел CTDB, временно исключенный из кластера из-за проблем (потеря связи, неработоспособная ФС). CTDB автоматически восстанавливает узел после устранения проблемы.

## Базовые концепции

### Архитектура CTDB

```
┌─────────────────────────────────────────────────────────┐
│                     Клиенты (Windows/macOS/Linux)       │
│                            │                             │
│                     Virtual IP (VIP)                     │
│                            │                             │
│  ┌─────────────────────────┼─────────────────────────┐   │
│  │         CTDB Cluster (Active/Active)              │   │
│  │                                                   │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────┐ │   │
│  │  │   Node 1     │  │   Node 2     │  │  Node 3 │ │   │
│  │  │  (smbd +     │  │  (smbd +     │  │ (smbd + │ │   │
│  │  │   ctdbd)     │  │   ctdbd)     │  │  ctdbd) │ │   │
│  │  └──────┬───────┘  └──────┬───────┘  └────┬────┘ │   │
│  │         │                  │               │      │   │
│  └─────────┼──────────────────┼───────────────┼──────┘   │
│            │                  │               │          │
│  ┌─────────▼──────────────────▼───────────────▼──────┐   │
│  │         Общая распределенная ФС                   │   │
│  │    (GFS2 on CLVM / GlusterFS / CephFS)           │   │
│  └───────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### Требования к инфраструктуре

| Компонент | Минимум | Рекомендация |
| :--- | :--- | :--- |
| **Узлы кластера** | 2 | 3+ (четное число для quorum) |
| **Сеть кластера** | 1x 1GbE | 2x 10GbE (bonded) |
| **Общая ФС** | GFS2 + CLVM | GlusterFS или CephFS |
| **Синхронизация времени** | chrony | chrony + PTP |
| **VIP** | 1 | 1 на сервис + 1 management |
| **Ядро Linux** | >= 3.17 | >= 5.10 (лучшая поддержка кластеров) |

### Режимы работы Samba-кластера

| Режим | Описание | Применение |
| :--- | :--- | :--- |
| **Active/Passive** | Один узел обслуживает клиентов, второй standby | Простые среды, DR-сценарии |
| **Active/Active** | Все узлы обслуживают клиентов параллельно | Высоконагруженные хранилища |
| **Scale-Out** | Узлы добавляются для увеличения пропускной способности | Растущие инфраструктуры |

### CTDB и распределенные ФС

CTDB не работает с локальными ФС — требуется общее хранилище:

| ФС | Преимущества | Недостатки |
| :--- | :--- | :--- |
| **GFS2 + CLVM** | Полная совместимость с CTDB, POSIX ACL | Требует dlm/corosync, сложность |
| **GlusterFS** | Масштабируемость, нет единой точки отказа | Выше latency, сложная отладка |
| **CephFS** | Автоматическая балансировка, receipt-based | Требует отдельного кластера Ceph |
| **NFS (exotic)** | Простота | Нет параллельного доступа к файлам |

## Практические сценарии

### 1. Установка и базовая настройка CTDB

```bash
# Debian / Ubuntu
sudo apt install -y ctdb

# RHEL / Rocky / AlmaLinux
sudo dnf install -y ctdb
```

### 2. Конфигурация CTDB (`/etc/ctdb/ctdb.conf`)

```ini
[cluster]
    transport = tcp
    # Сеть для кластерного трафика (рекомендуется отдельная VLAN)
    node address = 10.0.1.1
    # Список узлов (или через.nodes file)
    nodes = 10.0.1.1 10.0.1.2 10.0.1.3

[database]
    # Тип recreate permitted для первого запуска
    # После инициализации переключить на locked
    recover timeout = 30

[legacy]
    # Путь к скрипту определения здоровья узла
    script = /usr/lib/ctdb/events.d/50.samba.options
```

### 3. Файл узлов (`/etc/ctdb/nodes`)

```text
10.0.1.1
10.0.1.2
10.0.1.3
```

### 4. Настройка общего хранилища (GFS2 + CLVM)

```bash
# На всех узлах
sudo apt install -y dlm4 gfs2-utils lvm2-cluster

# Настройка DLM (Distributed Lock Manager)
sudo systemctl enable --now dlm

# Создание кластерного LV (на одном узле)
sudo clvmd -S  # Запуск clvmd
sudo lvcreate -L 500G -n samba_data clvm_vg
sudo mkfs.gfs2 -p lock_dlm -t mycluster:samba_data /dev/clvm_vg/samba_data

# Монтирование на всех узлах
sudo mkdir -p /srv/samba/cluster
sudo mount -t gfs2 /dev/clvm_vg/samba_data /srv/samba/cluster

# Добавление в /etc/fstab
echo '/dev/clvm_vg/samba_data /srv/samba/cluster gfs2 defaults,noatime 0 0' | sudo tee -a /etc/fstab
```

### 5. Конфигурация Samba для кластера

```ini
# /etc/samba/smb.conf (одинаковый на всех узлах)
[global]
    workgroup = WORKGROUP
    security = user
    server min protocol = SMB3_11
    server smb encrypt = required

    # Кластерные настройки
    clustering = yes
    ctdbd socket = /var/run/ctdb/ctdbd.socket

    # Виртуальная IP
    bind interfaces only = yes
    interfaces = eth1
    smb ports = 445

[ClusterShare]
    path = /srv/samba/cluster
    valid users = @shareusers
    writable = yes
    browsable = yes
    vfs objects = acl_xattr
    map acl inherit = yes
```

### 6. Настройка VIP и Public IPs

```bash
# /etc/ctdb/public_addresses (на всех узлах)
# Формат: IP/маска интерфейс
192.168.1.100/24 eth1
192.168.1.101/24 eth1
```

```bash
# Запуск CTDB
sudo systemctl enable --now ctdb

# Проверка статуса кластера
sudo ctdb status
# → Number of nodes    : 3
# → pnn:0    10.0.1.1    OK (THIS NODE)
# → pnn:1    10.0.1.2    OK
# → pnn:2    10.0.1.3    OK
```

### 7. Witness Protocol (для клиентов Windows)

Witness Protocol работает через RPC и не требует отдельной настройки — CTDB реализует его нативно. Клиенты Windows автоматически используют Witness для отслеживания состояния кластера.

```bash
# Проверка работы Witness на клиенте Windows
Get-SmbConnection | Select-Object -Property UserName, ServerName, WitnessType
```

### 8. Скрипт определения здоровья узла

```bash
#!/bin/bash
# /usr/lib/ctdb/events.d/50.samba.options

# Проверка доступности общей ФС
if ! mountpoint -q /srv/samba/cluster; then
    echo "UNHEALTHY: Cluster FS not mounted"
    exit 1
fi

# Проверка доступности VIP
if ! ip addr show eth1 | grep -q "192.168.1.100"; then
    echo "WARNING: VIP not on this node"
fi

# Проверка свободного места
DISK_USAGE=$(df /srv/samba/cluster | tail -1 | awk '{print $5}' | tr -d '%')
if [ "$DISK_USAGE" -gt 95 ]; then
    echo "UNHEALTHY: Disk usage ${DISK_USAGE}%"
    exit 1
fi

echo "OK"
exit 0
```

```bash
sudo chmod +x /usr/lib/ctdb/events.d/50.samba.options
```

### 9. Мониторинг кластера

```bash
# Статус узлов
sudo ctdb status

# IP-адреса на узлах
sudo ctdb ip

# Тест connectivity
sudo ctdb ping

# Логи CTDB
sudo journalctl -u ctdb -f

# Список забаненных узлов
sudo ctdb banned
```

### 10. Failover и отладка

```bash
# Принудительный failover VIP на другой узел
sudo ctdb ip reallocate

# Ручной ban узла (для обслуживания)
sudo ctdb ban 1 600  # Ban node 1 на 600 секунд

# Снятие ban
sudo ctdb unban 1

# принудительный recovery кластера
sudo ctdb recover

# Просмотр логов failover
sudo journalctl -u ctdb | grep -i "failover\|move\|public_ip"
```

### 11. Типовые ошибки кластера

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `UNHEALTHY` node | Общая ФС недоступна | Проверьте mount, DLM, сеть |
| VIP не перемещается | Reclock failed | Проверьте общую ФС для reclock |
| Split-brain | Потеря связи между узлами | Настройте 2+ кластерных линка |
| `ctdb recover` бесконечный | Блокировка в TDB | `ctdb stop` → `ctdb start` на проблемном узле |
| Клиент не подключается к VIP | Firewall / routing | Откройте 445/TCP на VIP |

### 12. Балансировка нагрузки (DNS round-robin)

Для распределения клиентов между узлами используйте DNS round-robin с VIP каждого узла:

```bind
; /etc/bind/db.example.com
samba-vip1  A  192.168.1.100
samba-vip2  A  192.168.1.101
samba-vip3  A  192.168.1.102

shares  A  192.168.1.100
shares  A  192.168.1.101
shares  A  192.168.1.102
```

## Мониторинг и диагностика

### Интеграция с Prometheus

```bash
# Экспорт метрик CTDB через textfile collector
cat <<'EOF' > /usr/local/bin/ctdb_metrics.sh
#!/bin/bash
METRICS_DIR="/var/lib/node_exporter/textfile_collector"
mkdir -p "$METRICS_DIR"

# Статус узла
STATUS=$(sudo ctdb status 2>/dev/null | grep "THIS NODE" | awk '{print $NF}')
echo "ctdb_node_status{node=\"$(hostname)\"} $([[ "$STATUS" == "OK" ]] && echo 1 || echo 0)" > "$METRICS_DIR/ctdb.prom.$$"

# Количество рекаверий
RECOVERIES=$(sudo ctdb status 2>/dev/null | grep "Recoveries" | awk '{print $NF}')
echo "ctdb_total_recoveries $RECOVERIES" >> "$METRICS_DIR/ctdb.prom.$$"

mv "$METRICS_DIR/ctdb.prom.$$" "$METRICS_DIR/ctdb.prom"
EOF
chmod +x /usr/local/bin/ctdb_metrics.sh
```

```bash
# Cron каждые 30 секунд
* * * * * /usr/local/bin/ctdb_metrics.sh
```

## Дополнительная информация

- [Обзор Samba](./index.md) — архитектура и демоны.
- [Настройка сервера](./samba_setup.md) — создание файловых ресурсов.
- [Безопасность и VFS](./samba_security.md) — hardening и модульное расширение.
- [Интеграция с AD](./samba_ad.md) — членство в домене Active Directory.

## См. также

- [GFS2 и кластерные ФС](../../../FileSystems/GFS2/overview.md) — настройкаобщей файловой системы.
- [Corosync и DLM](../../../Clustering/corosync/overview.md) — кластерная инфраструктура.
- [Оптимизация TCP в Linux](../../../Networking/Concepts/tcp_tuning/tcp_tuning_overview.md) — тюнинг для кластерного трафика.
