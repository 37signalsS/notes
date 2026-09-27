# NFS: Высокая доступность (HA)

---

## Определения

**High Availability (HA) NFS** — архитектура построения отказоустойчивого NFS-сервера, при которой при падении активного узла пассивный узел автоматически перехватывает обслуживание клиентов с минимальным временем простоя (RTO) и без потери данных (RPO).

**Active/Passive (Hot Standby)** — режим HA, при котором один узел активно обслуживает NFS-запросы, а второй находится в резерве и синхронизирует данные. При сбое активного узла происходит автоматический failover.

**Active/Active** — режим HA, при котором несколько узлов одновременно обслуживают NFS-запросы. Требует кластерную файловую систему (GFS2, OCFS2) или распределённое хранилище (Ceph, GlusterFS).

**Virtual IP (VIP)** — логический IP-адрес, который маршрутизируется на активный узел кластера. Клиенты NFS монтируют ресурсы по VIP, а не по физическим IP узлов.

**Split-Brain** — опасная ситуация, при которой два узла кластера одновременно считают себя активными и пишут в одно хранилище, что приводит к безвозвратной порче данных.

**STONITH (Shoot The Other Node In The Head)** — механизм принудительной изоляции (fencing) сбойного узла для предотвращения split-brain.

**DRBD (Distributed Replicated Block Device)** — программное решение для синхронной репликации блочных устройств по сети («сетевое RAID 1»).

---

## Теоретический блок

### Архитектурные модели HA для NFS

| Модель | Сложность | RPO | RTO | Хранилище | Применение |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Active/Passive + DRBD** | Средняя | 0 (синхронная) | 30–120 сек | Локальные диски | Критичные среды, 2 узла |
| **Active/Passive + SAN** | Низкая | 0 | 30–60 сек | Общий диск (iSCSI/FC) | Среды с SAN |
| **Active/Active + GFS2** | Высокая | 0 | 0 (нет failover) | SAN/DRBD | Высоконагруженные среды |
| **Active/Active + Ceph** | Очень высокая | 0 | Автоматически | Ceph集群 | Крупные инфраструктуры |
| **NFS + Keepalived** | Низкая | Зависит от бэкенда | 5–30 сек | Shared storage | Простые среды |

### Компоненты стека HA

| Компонент | Назначение | Порты |
| :--- | :--- | :--- |
| **Pacemaker** | Менеджер ресурсов кластера | — |
| **Corosync** | Инфраструктура обнаружения сбоев | UDP 5404–5405 |
| **pcs** | CLI/Web для управления кластером | TCP 2224 |
| **DRBD** | Репликация блочных устройств | TCP 7788–7799 |
| **Keepalived** | Управление VIP через VRRP | UDP 5801 (VRRP) |
| **STONITH/Fencing** | Изоляция сбойных узлов | Зависит от реализации |

### DRBD: протоколы репликации

| Протокол | Подтверждение записи | RPO | Задержка | Применение |
| :--- | :--- | :--- | :--- | :--- |
| **A (асинхронный)** | После попадания в сетевой буфер | До потери данных | Минимальная | Гео-удалённые площадки |
| **B (полусинхронный)** | После попадания в RAM удалённого узла | 0 при сбое питания | Средняя | Локальные сети |
| **C (синхронный)** | После записи на диск обоих узлов | 0 | Максимальная | **Рекомендуется для NFS HA** |

### Keepalived vs Pacemaker для VIP

| Характеристика | Keepalived | Pacemaker |
| :--- | :--- | :--- |
| **Сложность** | Низкая | Высокая |
| **VRRP** | Нативная поддержка | Через агент `ocf:heartbeat:IPaddr2` |
| **Healthcheck** | Встроенные скрипты | Resource Agents (OCF) |
| **Fencing** | Отсутствует | STONITH (обязателен) |
| **Split-brain защита** | Приоритет + VRRP | Кворум + STONITH |
| **Рекомендация** | Простые 2-узловые кластеры | Критичные среды |

---

## Практический блок

### Сценарий 1: NFS HA с DRBD + Pacemaker (2 узла)

#### Шаг 1: Подготовка узлов

```bash
# На обоих узлах (Ubuntu/Debian)
sudo apt update && sudo apt install -y pacemaker pcs corosync drbd-utils resource-agents

# Включение и запуск pcsd
sudo systemctl enable --now pcsd

# Установка пароля для пользователя hacluster
sudo passwd hacluster
```

#### Шаг 2: Настройка кластера

```bash
# На одном узле (node1):
sudo pcs host auth node1 node2 -u hacluster -p <password>
sudo pcs cluster setup nfs_cluster node1 node2 --transport knet
sudo pcs cluster start --all
sudo pcs cluster enable --all
```

#### Шаг 3: Настройка DRBD

Создайте `/etc/drbd.d/nfs.res` на обоих узлах:

```text
resource nfs_data {
    options {
        quorum majority;
        on-no-quorum io-error;
    }
    net {
        protocol C;
        after-sb-0pri discard-zero-changes;
        after-sb-1pri discard-secondary;
    }
    disk {
        on-io-error detach;
    }
    on node1 {
        address 10.0.0.1:7788;
        volume 0 {
            device /dev/drbd0;
            disk /dev/sdb;
            meta-disk internal;
        }
    }
    on node2 {
        address 10.0.0.2:7788;
        volume 0 {
            device /dev/drbd0;
            disk /dev/sdb;
            meta-disk internal;
        }
    }
}
```

```bash
# На обоих узлах:
sudo drbdadm create-md nfs_data
sudo drbdadm up nfs_data

# Только на node1 (для начала синхронизации):
sudo drbdadm primary --force nfs_data

# Проверка статуса:
cat /proc/drbd
# или
sudo drbdadm status
```

#### Шаг 4: Форматирование и монтирование

```bash
# Только на активном узле (node1):
sudo mkfs.xfs /dev/drbd0
sudo mkdir -p /srv/nfs/data
sudo mount /dev/drbd0 /srv/nfs/data

# Настройка NFS-экспорта:
echo "/srv/nfs/data 10.0.0.0/24(rw,sync,no_subtree_check,no_root_squash)" | sudo tee -a /etc/exports
sudo exportfs -ra
```

#### Шаг 5: Ресурсы Pacemaker

```bash
# Включение STONITH (если есть IPMI/iLO):
sudo pcs stonith create ipmi_stonith fence_ipmilan pcmk_host_list="node1 node2" ipaddr=10.0.0.100 login=admin passwd=admin

# Ресурс DRBD:
sudo pcs resource create nfs_drbd ocf:linbit:drbd drbd_resource=nfs_data op monitor interval=10s role=Started

# Ресурс файловой системы (clone для обоих узлов):
sudo pcs resource promotable nfs_drbd_clone node-max=1 clone-max=2

# Ресурсэкспорта NFS (только на активном DRBD-узле):
sudo pcs resource create nfs_export ocf:heartbeat:exportfs \
    clientspec="10.0.0.0/24" \
    directory="/srv/nfs/data" \
    fsid=0 \
    options="rw,sync,no_subtree_check,no_root_squash" \
    op monitor interval=30s

# Ресурс NFS-сервера:
sudo pcs resource create nfs_server systemd:nfs-server op monitor interval=30s

# Связывание ресурсов (порядок запуска):
sudo pcs constraint order promote nfs_drbd_clone then start nfs_server
sudo pcs constraint order start nfs_server then start nfs_export
sudo pcs constraint colocation add nfs_export with nfs_server

# VIP для клиентов:
sudo pcs resource create nfs_vip ocf:heartbeat:IPaddr2 \
    ip=10.0.0.50 \
    cidr_netmask=24 \
    op monitor interval=10s

# Привязка VIP к активному узлу:
sudo pcs constraint colocation add nfs_vip with nfs_server
```

#### Шаг 6: Тестирование failover

```bash
# На активном узле:
sudo pcs cluster stop node1
# → node2 должен стать активным, VIP переключится

# Проверка на node2:
sudo pcs status
sudo drbdadm status
sudo mount | grep drbd
showmount -e 10.0.0.50

# Восстановление:
sudo pcs cluster start node1
# → node1 станет ведомым, данные синхронизируются
```

### Сценарий 2: NFS HA с Keepalived (упрощённый)

Для сред, где не требуется fencing и кластерная ФС:

```bash
# Установка Keepalived на обоих узлах:
sudo apt install -y keepalived
```

`/etc/keepalived/keepalived.conf` на node1 (приоритет 101):

```text
vrrp_script check_nfs {
    script "/usr/bin/systemctl is-active nfs-server"
    interval 2
    weight -20
}

vrrp_instance NFS_VIP {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 101
    advert_int 1
    authentication {
        auth_type PASS
        auth_pass secret123
    }
    virtual_ipaddress {
        10.0.0.50/24
    }
    track_script {
        check_nfs
    }
}
```

`/etc/keepalived/keepalived.conf` на node2 (приоритет 100):

```text
vrrp_script check_nfs {
    script "/usr/bin/systemctl is-active nfs-server"
    interval 2
    weight -20
}

vrrp_instance NFS_VIP {
    state BACKUP
    interface eth0
    virtual_router_id 51
    priority 100
    advert_int 1
    authentication {
        auth_type PASS
        auth_pass secret123
    }
    virtual_ipaddress {
        10.0.0.50/24
    }
    track_script {
        check_nfs
    }
}
```

```bash
sudo systemctl enable --now keepalived

# Тестирование:
sudo systemctl stop nfs-server
# → VIP должен переключиться на node2
```

### Сценарий 3: Репликация данных между узлами

#### rsync (для ручной/периодической синхронизации)

```bash
# На активном узле (cron job каждые 5 минут):
*/5 * * * * rsync -avz --delete /srv/nfs/data/ node2:/srv/nfs/data/

# Или через lsyncd (real-time репликация):
sudo apt install -y lsyncd
```

Конфигурация `/etc/lsyncd.conf`:

```lua
settings {
    logfile = "/var/log/lsyncd/lsyncd.log",
    statusFile = "/var/log/lsyncd/lsyncd.status",
    nodaemon = false,
}

sync {
    default.rsync,
    source = "/srv/nfs/data/",
    target = "node2:/srv/nfs/data/",
    delay = 5,
    rsync = {
        archive = true,
        compress = true,
        acls = true,
        xattrs = true,
    },
}
```

---

## Дополнительная информация

### Мониторинг кластера

```bash
# Статус кластера:
sudo pcs status

# Статус DRBD:
sudo drbdadm status
cat /proc/drbd

# Проверка VIP:
ip addr show | grep 10.0.0.50

# Логи Pacemaker:
sudo journalctl -u pacemaker -f

# Логи Corosync:
sudo journalctl -u corosync -f
```

### Чеклист перед запуском NFS HA

- [ ] Настроена синхронная репликация DRBD (протокол C)
- [ ] Настроен STONITH/Fencing (обязательно для split-brain защиты)
- [ ] VIP работает и переключается при остановке active-узла
- [ ] NFS-экспорты автоматически активируются при failover
- [ ] Клиенты монтируют NFS по VIP, а не по физическим IP
- [ ] Клиенты используют `hard` монтирование для устойчивости к transient failures
- [ ] Настроено мониторинг состояния кластера и DRBD
- [ ] Протестирован сценарий полного падения активного узла
- [ ] Время failover не превышает SLA (обычно 30–120 сек)

### Связанные темы

- **[NFS: Основные концепции](./index.md)** — архитектура и версии NFS.
- **[NFS: Настройка сервера и клиента](./nfs_setup.md)** — базовая конфигурация.
- **[NFS: Диагностика](./nfs_troubleshooting.md)** — устранение неполадок.
- **[Pacemaker + DRBD](../../../../Concepts/High_Availability/linux_ha_stack_pacemaker_drbd.md)** — общий стек HA.
- **[Keepalived](../../../../Concepts/High_Availability/ha_failover_mechanisms.md)** — механизмы failover.
- **[NFS в Kubernetes](../../../../Kubernetes/Storage/CSI/csi_nfs_production.md)** — NFS HA в контейнерах.
