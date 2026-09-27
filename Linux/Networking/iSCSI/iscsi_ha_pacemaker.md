# iSCSI: Высокая доступность с Pacemaker/Corosync

Руководство по построению отказоустойчивых кластеров с общим iSCSI-хранилищем, управляемых Pacemaker и Corosync.

## Определения

| Термин | Описание |
| :--- | :--- |
| **Pacemaker** | Менеджер кластерных ресурсов (CRM). Управляет запуском/остановкой сервисов, мониторингом состояния и автоматическим failover между узлами. |
| **Corosync** | Кластерный коммуникационный движок. Обеспечивает reliable messaging (heartbeats) между узлами кластера. Corosync = транспорт, Pacemaker = логика. |
| **Кворум** | Минимальное количество узлов для работы кластера. Без кворума кластер может "разделиться" (split-brain). |
| **STONITH (Shoot The Other Node In The Head)** | Механизм принудительного отключения "подозрительного" узла через IPMI/iLO/Redfish. Обязателен для production. |
| **Resource Agent (RA)** | Скрипт-обёртка над сервисом, который управляет Pacemaker. Примеры: `ocf:heartbeat:IPaddr2`, `ocf:heartbeat:Filesystem`, `ocf:heartbeat:oracle` |
| **Clone-ресурс** | Ресурс, запущенный на нескольких узлах одновременно (например, DLM, vigil). |
| **Colocation** | Ограничение: два ресурса ДОЛЖНЫ работать на одном узле. |
| **Order** | Ограничение: один ресурс ДОЛЖЕН запуститься ПЕРЕД другим. |
| **Location** | Ограничение: ресурс предпочитает определённый узел (prefer/move). |
| ** promotable resource** | Ресурс с концепцией "Master/Slave" (например, DRBD). Один узел — Master, остальные — Slave. |
| ** pcs** | Утилита командной строки для управления Pacemaker/Corosync (replacement для cibadmin). |

## Архитектура кластера

```text
┌──────────────────────────────────────────────────────────────┐
│                      PACEMAKER CRM                          │
│  (менеджер ресурсов, принимает решения о failover)           │
└───────────────┬──────────────────────────┬───────────────────┘
                │                          │
    ┌───────────▼───────────┐  ┌──────────▼──────────────┐
    │   Corosync (Node 01)  │  │  Corosync (Node 02)     │
    │   - Heartbeat         │  │  - Heartbeat             │
    │   - Quorum vote       │  │  - Quorum vote           │
    │   - Messaging         │  │  - Messaging              │
    └───────────┬───────────┘  └──────────┬──────────────┘
                │                          │
    ┌───────────▼───────────┐  ┌──────────▼──────────────┐
    │    Pacemaker Agent    │  │   Pacemaker Agent        │
    │    (node01)           │  │   (node02)               │
    │    - IPaddr2          │  │   - IPaddr2              │
    │    - Filesystem       │  │   - Filesystem           │
    │    - dlm              │  │   - dlm                  │
    │    - oracle           │  │   - oracle               │
    └───────────┬───────────┘  └──────────┬──────────────┘
                │                          │
                └──────────────┬───────────┘
                               │
                    ┌──────────▼──────────┐
                    │    iSCSI LUN        │
                    │    (общий)          │
                    └─────────────────────┘
```

## Требования

1. **2+ узла** (рекомендуется нечётное количество для кворума)
2. **Синхронизация времени** (`chrony`, разница < 500 мс)
3. **Отдельная сеть для Corosync** (рекомендуется)
4. **STONITH** (IPMI/iLO/Redfish) для production
5. **Общее блочное устройство** (iSCSI LUN с multipath)
6. **SCSI-3 Persistent Reservations** для защиты данных

## Практические сценарии

### Сценарий 1: Базовая установка кластера (2 узла)

#### Шаг 1: Установка пакетов (оба узла)

```bash
# RHEL/Rocky/Alma
sudo dnf install -y pacemaker corosync pcs resource-agents fence-agents-all

# Debian/Ubuntu
sudo apt install -y pacemaker corosync pcs resource-agents fence-agents

# Включение и запуск pcsd
sudo systemctl enable --now pcsd
```

#### Шаг 2: Настройка паролей (оба узла)

```bash
# Установка пароля для пользователя 'hacluster'
sudo passwd hacluster
# Ввести одинаковый пароль на обоих узлах
```

#### Шаг 3: Авторизация узлов (с любого узла)

```bash
# Авторизация узлов друг с другом
sudo pcs host auth node1 node2 -u hacluster -p <PASSWORD>

# Проверка
sudo pcs host auth node1 node2 -u hacluster
# → node1: Authorized
# → node2: Authorized
```

#### Шаг 4: Создание кластера (с любого узла)

```bash
# Создание кластера
sudo pcs cluster setup my_cluster node1 node2

# Запуск кластера на всех узлах
sudo pcs cluster start --all

# Включение автозапуска
sudo pcs cluster enable --all

# Проверка статуса
sudo pcs status
# → Cluster name: my_cluster
# → STONITH (fence_heuristics_implied):      Disabled
# → Last updated: Mon Sep 14 2026
# → Last change: Mon Sep 14 2026
# → Stack: corosync
# → Current DC: node1 (version 2.1.0) - partition with quorum
# → 2 nodes configured
# → 0 resource instances configured
```

### Сценарий 2: Настройка кворума (2 узла)

```bash
# Для 2-узлового кластера: two_node режим
sudo pcs property set no-quorum-policy=ignore
sudo pcs property set two_node=1

# Проверка
sudo pcs property config
# → Cluster Properties:
# →   cluster-recheck-interval: 90s
# →   default-action-timeout: 20s
# →   no-quorum-policy: ignore
# →   two_node: 1
```

### Сценарий 3: Настройка STONITH (fencing)

```bash
# Пример для IPMI fence (оба узла должны иметь IPMI-интерфейс)

# Настройка fence-агента для node1
sudo pcs stonith create fence_node1 fence_ipmp \
  pcmk_host_map="node1:node1_ipmi" \
  ipaddr="192.168.1.101" \
  login="admin" \
  passwd="ipmi_password" \
  lanplus=1 \
  pcmk_host_check="static-list"

# Настройка fence-агента для node2
sudo pcs stonith create fence_node2 fence_ipmp \
  pcmk_host_map="node2:node2_ipmi" \
  ipaddr="192.168.1.102" \
  login="admin" \
  passwd="ipmi_password" \
  lanplus=1 \
  pcmk_host_check="static-list"

# Привязка fence к узлам
sudo pcs constraint location fence_node1 avoids node1=INFINITY
sudo pcs constraint location fence_node2 avoids node2=INFINITY

# Проверка
sudo pcs stonith config
# → Resource: fence_node1 (class=stonith type=fence_ipmp)
# →   Attributes: pcmk_host_map="node1:node1_ipmi" ipaddr="192.168.1.101" ...
# → Resource: fence_node2 (class=stonith type=fence_ipmp)
# →   Attributes: pcmk_host_map="node2:node2_ipmi" ipaddr="192.168.1.102" ...
```

**Примечание:** Если IPMI недоступен, используйте `fence_heuristics_implied` как временный вариант (⚠️ не рекомендуется для production).

### Сценарий 4: Кластер с общим iSCSI LUN

#### Шаг 1: DLM (оба узла)

```bash
# Создание DLM как clone-ресурса (запускается на всех узлах)
sudo pcs resource create dlm ocf:pacemaker:controld \
  op monitor interval="30s" timeout="20s" \
  op start timeout="90s" \
  op stop timeout="90s"

sudo pcs resource clone dlm clone-max=2 clone-node-max=1 notify=true

# Привязка DLM к узлам
sudo pcs constraint location dlm-clone avoids node1=INFINITY
sudo pcs constraint location dlm-clone avoids node2=INFINITY
```

#### Шаг 2: Clustered LVM (оба узла)

```bash
# Создание clvm как clone-ресурса
sudo pcs resource create clvmd ocf:heartbeat:clvm \
  op monitor interval="30s" timeout="20s"

sudo pcs resource clone clvmd clone-max=2 clone-node-max=1 notify=true

# Порядок запуска: DLM → clvm
sudo pcs constraint order dlm-clone then clvmd-clone
```

#### Шаг 3: VIP (Virtual IP) (с любого узла)

```bash
# Виртуальный IP для доступа к сервису
sudo pcs resource create VIP ocf:heartbeat:IPaddr2 \
  ip="192.168.1.100" \
  cidr_netmask="24" \
  op monitor interval="10s"

# Привязка VIP к ресурсам
sudo pcs constraint colocation add VIP with dlm-clone INFINITY
```

#### Шаг 4: Файловая система (с любого узла)

```bash
# Создание ресурса Filesystem
sudo pcs resource create GFS2_FS ocf:heartbeat:Filesystem \
  device="/dev/vg_cluster/lv_shared" \
  directory="/mnt/gfs2" \
  fstype="gfs2" \
  options="noatime" \
  op monitor interval="20s" timeout="40s" \
  op start timeout="60s" \
  op stop timeout="60s"

# Colocation: VIP + Filesystem на одном узле
sudo pcs constraint colocation add GFS2_FS with VIP INFINITY

# Order: VIP → Filesystem
sudo pcs constraint order VIP then GFS2_FS
```

#### Шаг 5: Мониторинг

```bash
# Создание资源状态检查а
sudo pcs resource status
# → dlm-clone (ocf:pacemaker:controld):
# →   Master/Slave Set: dlm-clone [dlm]
# →     Masters: [ node1 ]
# →     Slaves: [ node2 ]
# → VIP (ocf:heartbeat:IPaddr2):
# →   Stopped: [ node1 ] (or node2)
# → GFS2_FS (ocf:heartbeat:Filesystem):
# →   Stopped: [ node1 ] (or node2)
```

### Сценарий 5: Тестирование failover

```bash
# 1. Проверка текущего состояния
sudo pcs status
# → Masters: [ node1 ]
# → VIP running on: node1

# 2. Отключение node1 (имитация сбоя)
sudo pcs cluster stop node1
# или
sudo pcs node fence node1

# 3. Проверка на node2 (через 30-60 секунд)
sudo pcs status
# → Masters: [ node2 ]  (DLM перезапущен)
# → VIP running on: node2  (VIP мигрировал)
# → GFS2_FS running on: node2  (ФС примонтирована)

# 4. Включение node1 обратно
sudo pcs cluster start node1

# 5. Возврат на исходный узел (если нужно)
sudo pcs resource move VIP node1
```

### Сценарий 6: Полный стек (DLM + clvm + VIP + FS + DB)

```bash
# Полный набор ресурсов для базы данных на iSCSI

# 1. DLM (clone)
sudo pcs resource create dlm ocf:pacemaker:controld \
  op monitor interval="30s" timeout="20s"
sudo pcs resource clone dlm clone-max=2 clone-node-max=1 notify=true

# 2. clvm (clone)
sudo pcs resource create clvmd ocf:heartbeat:clvm \
  op monitor interval="30s" timeout="20s"
sudo pcs resource clone clvmd clone-max=2 clone-node-max=1 notify=true

# 3. VIP
sudo pcs resource create VIP ocf:heartbeat:IPaddr2 \
  ip="192.168.1.100" cidr_netmask="24" \
  op monitor interval="10s"

# 4. Filesystem
sudo pcs resource create GFS2_FS ocf:heartbeat:Filesystem \
  device="/dev/vg_cluster/lv_data" \
  directory="/var/lib/pgsql" \
  fstype="gfs2" \
  options="noatime" \
  op monitor interval="20s" timeout="40s"

# 5. PostgreSQL
sudo pcs resource create pgsql ocf:heartbeat:pgsql \
  pgctl="/usr/bin/pg_ctl" \
  psql="/usr/bin/psql" \
  pgdata="/var/lib/pgsql/data" \
  op monitor interval="30s" timeout="60s"

# 6. Ограничения
sudo pcs constraint order dlm-clone then clvmd-clone
sudo pcs constraint order clvmd-clone then VIP
sudo pcs constraint order VIP then GFS2_FS
sudo pcs constraint order GFS2_FS then pgsql

sudo pcs constraint colocation add VIP with dlm-clone INFINITY
sudo pcs constraint colocation add GFS2_FS with VIP INFINITY
sudo pcs constraint colocation add pgsql with GFS2_FS INFINITY

# 7. Проверка
sudo pcs constraint show --full
```

## Диагностика проблем

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `No quorum` | Узлы не могут связаться | Проверить сеть Corosync (порт 5405/UDP), `corosync-cfgtool -s` |
| `Resource start timeout` | Ресурс не запустился за отведённое время | Увеличить timeout, проверить логи `journalctl -u resource` |
| `Resource monitor failed` | Проверка состояния вернула ошибку | Проверить права доступа, зависимости |
| `STONITH fencing failed` | Fence-агент не может отключить узел | Проверить IPMI/iLO доступность, credentials |
| `Split-brain` | Кластер разделился из-за отсутствия STONITH | Настроить STONITH, увеличить timeouts |
| `DLM lock space not found` | DLM не инициализирован на узле | `sudo systemctl start dlm`, проверить pacemaker |
| `clvm: volume group not found` | clvm не может найти VG | Убедиться что clvmd запущен и VG создан с `--shared` |

### Полезные команды мониторинга

```bash
# Статус кластера
sudo pcs status

# Детальный статус
sudo pcs status xml | xmllint --format -

# Свойства кластера
sudo pcs property config

# Все ресурсы
sudo pcs resource config

# Все ограничения
sudo pcs constraint show --full

# Логи Pacemaker
sudo journalctl -u pacemaker -f

# Логи Corosync
sudo journalctl -u corosync -f

# Тест connectivity
sudo corosync-cfgtool -s

# Просмотр cmap (key-value store)
sudo corosync-cmapctl | grep nodes
```

## Рекомендации для production

1. **STONITH обязателен:** Без него кластер не может безопасно обрабатывать split-brain
2. **Нечётное количество узлов:** Для кворума без extra-quorum-policy (3, 5, 7 узлов)
3. **Отдельная сеть Corosync:** Не используйте сеть данных для heartbeats
4. **Мониторинг:** Настройте алерты на `pcs status` и логи Pacemaker
5. **Регулярное тестирование failover:** Минимум раз в месяц
6. **Документация:** Записывайте все constraint'ы и их назначение
7. **Бэкап конфигурации:** `sudo pcs config backup cluster_backup`

## См. также

- **[SCSI-3 Persistent Reservations](./iscsi_persistent_reservations.md)** — блокировки для защиты данных
- **[Кластерные ФС (GFS2/OCFS2)](./iscsi_cluster_fs.md)** — файловые системы для кластера
- **[Настройка Multipath I/O](./iscsi_multipath.md)** — отказоустойчивость путей
- **[Настройка iSCSI Target](./iscsi_target_setup.md)** — серверная часть
