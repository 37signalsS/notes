# iSCSI: Настройка Target (Сервер)

Руководство по развертыванию, конфигурации и эксплуатации серверного компонента iSCSI в ОС Linux.

## Зачем нужен iSCSI Target

iSCSI Target позволяет превратить Linux-сервер в сетевое хранилище, экспортирующее блочные устройства по протоколу iSCSI. Клиенты (инициаторы) подключаются к target и видят удалённые диски как локальные — это открывает широкие возможности:

- **Centralized Storage** — единое хранилище для кластеров, виртуализации (KVM, Proxmox), контейнеров
- **High Availability** — в связке с Multipath I/O обеспечивается отказоустойчивость при сбоях сети или серверов
- **Гибкость управления** — LUN можно создавать, расширять, мигрировать без остановки клиентов
- **Цена решения** — Linux + commodity-жёсткие диски дешевле коммерческих SAN-решений (NetApp, EMC)
- **Интеграция** — LIO (Linux-IO) — ядерный модуль, не требует дополнительного ПО для базовых сценариев

**Типичные сценарии использования:**
- Хранилище для виртуальных машин (KVM/QEMU, Proxmox VE)
- Общие диски для кластеров (Pacemaker/Corosync)
- Резервное копирование (borg, restic,bacula → iSCSI LUN)
- Тестирование и разработка (быстрое создание виртуальных дисков)
- Миграция данных между серверами (live migration через iSCSI)

## Определения и сокращения

| Термин | Описание |
| :--- | :--- |
| **Target (Таргет)** | Серверный компонент, экспортирующий дисковые ресурсы по сети. |
| **Backstore** | Метод реализации хранилища в ядре (block, fileio, pscsi, ramdisk). Определяет, откуда берутся данные. |
| **TPG (Target Portal Group)** | Группа порталов, LUN и ACL, объединенных общей политикой доступа. Каждый target может содержать несколько TPG. |
| **LUN (Logical Unit Number)** | Логическая единица хранения, сопоставленная с конкретным Backstore. Нумерация начинается с 0. |
| **IQN (iSCSI Qualified Name)** | Уникальный идентификатор узла (инициатора или таргета). Формат: `iqn.YYYY-MM.com.example:name`. |
| **Portal** | IP-адрес и порт (по умолчанию 3260/tcp), на которых таргет ожидает подключения. |
| **ACL (Access Control List)** | Список IQN инициаторов, которым разрешен вход в конкретную TPG. |
| **targetcli** | Основной инструмент администрирования стека LIO (интерактивная оболочка). |
| **configfs** | Псевдофайловая система ядра, через которую LIO предоставляет интерфейс управления. Монтируется в `/sys/kernel/config/`. |
| **LIO (Linux-IO)** | Стандартная ядерная реализация iSCSI target в Linux. Включена в основное дерево ядра с версии 2.6.38. |
| **SCSI-3 PR (Persistent Reservations)** | Механизм блокировки доступа к LUN на уровне SCSI. Критичен для кластеров с общим хранением. |
| **Write Cache** | Кэш записи на стороне target. Write-back (быстрый, небезопасный) vs Write-through (медленный, безопасный). |

## Основные концепции

### Архитектура LIO (linux-iscsi.org)

В современном Linux стандартом является **LIO** — реализация таргета на уровне ядра. Она взаимодействует с пользователем через псевдофайловую систему `configfs` (обычно монтируется в `/sys/kernel/config/target/`). Утилита `targetcli` предоставляет иерархическую оболочку для управления этой структурой.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Пользовательское пространство                │
│                                                                     │
│  ┌─────────────┐     ┌──────────────┐     ┌──────────────────────┐  │
│  │  targetcli   │────▶│  rtslib-fb   │────▶│  /sys/kernel/config/ │  │
│  │  (CLI)       │     │  (библиотека)│     │  target/ (configfs)  │  │
│  └─────────────┘     └──────────────┘     └──────────┬───────────┘  │
│                                                       │              │
├───────────────────────────────────────────────────────┼──────────────┤
│                        Ядро Linux                     │              │
│                                                       ▼              │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                     LIO Core (target_core_mod)                  │ │
│  │                                                                 │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │ │
│  │  │  block    │  │  fileio  │  │  pscsi   │  │  ramdisk     │   │ │
│  │  │  backstore│  │  backstore│  │  backstore│  │  backstore   │   │ │
│  │  └─────┬────┘  └─────┬────┘  └─────┬────┘  └──────┬───────┘   │ │
│  │        │              │              │               │           │ │
│  │        └──────────────┴──────────────┴───────────────┘           │ │
│  │                              │                                   │ │
│  │                    ┌─────────▼─────────┐                        │ │
│  │                    │   SCSI Target     │                        │ │
│  │                    │   Core (SBC/SPC)  │                        │ │
│  │                    └─────────┬─────────┘                        │ │
│  │                              │                                   │ │
│  │                    ┌─────────▼─────────┐                        │ │
│  │                    │  iSCSI Target     │                        │ │
│  │                    │  (iscsi_target_mod)│                       │ │
│  │                    └─────────┬─────────┘                        │ │
│  └──────────────────────────────┼──────────────────────────────────┘ │
│                                 │                                    │
│                    ┌────────────▼────────────┐                      │
│                    │    TCP/IP Stack         │                      │
│                    │    (порт 3260/tcp)      │                      │
│                    └─────────────────────────┘                      │
└─────────────────────────────────────────────────────────────────────┘
```

**Иерархия configfs:**

```
/sys/kernel/config/target/
├── iscsi/
│   └── iqn.2026-07.com.example:target01/
│       └── tpg1/
│           ├── acls/
│           │   └── iqn.2026-07.com.example:initiator01/
│           │       └── lun_0 -> ../../luns/lun_0
│           ├── luns/
│           │   └── lun_0/
│           │       └── _backstore -> ../../../.../storage01
│           └── portals/
│               └── 0.0.0.0:3260/
└── alua/
```

### Типы хранилищ (Backstores)

| Тип | Описание | Производительность | Use Case |
| :--- | :--- | :--- | :--- |
| **block** | Блочные устройства напрямую (диски, LVM, Zvol) | Максимальная | Продакшн, базы данных, ВМ |
| **fileio** | Файл как виртуальный диск (image) | Средняя (overhead ФС) | Тесты, development, temporary storage |
| **pscsi** | Прямой проброс SCSI-команд (pass-through) | Зависит от устройства | Физические tape-устройства, RAID-контроллеры |
| **ramdisk** | Хранилище в ОЗУ | Очень высокая | Тестирование, временные данные (при ребуте теряются) |

**Рекомендации по выбору:**
- **block** — используйте по умолчанию для любых продакшн-сценариев. LVM позволяет гибко расширять LUN без остановки services.
- **fileio** — удобно для быстрого создания тестовых LUN. Файл-образ можно easily скопировать/переместить. Double-buffering: пользовательский буфер → ядро → ФС → диск.
- **pscsi** — редко используется; подходит для проброса tape-библиотек или hardware RAID в виртуализированные среды.
- **ramdisk** — только для тестов производительности или временных данных.

## Практические сценарии

### Сценарий 1: Настройка LIO (Стандарт)

#### 1. Установка
```bash
sudo apt update && sudo apt install targetcli-fb -y
# Для RHEL/Rocky: sudo dnf install targetcli -y
```

#### 2. Конфигурация через targetcli
Запустите интерактивную оболочку: `sudo targetcli`.

```bash
# 1. Создание хранилища на базе LVM или раздела
/backstores/block create name=storage01 dev=/dev/vg_data/lv_iscsi

# 2. Создание таргета
/iscsi create iqn.2026-07.com.example:target01

# 3. Привязка портала (по умолчанию 0.0.0.0:3260)
/iscsi/iqn.2026-07.com.example:target01/tpg1/portals create 0.0.0.0

# 4. Сопоставление LUN с хранилищем
/iscsi/iqn.2026-07.com.example:target01/tpg1/luns create /backstores/block/storage01

# 5. Настройка доступа (ACL) для инициатора
/iscsi/iqn.2026-07.com.example:target01/tpg1/acls create iqn.2026-07.com.example:initiator01
```

### Сценарий 2: Настройка безопасности (CHAP)

LIO поддерживает одностороннюю и взаимную (Mutual) аутентификацию.

#### Односторонний CHAP (Таргет проверяет инициатора)
В `targetcli`:
```bash
cd /iscsi/iqn.2026-07.com.example:target01/tpg1/acls/iqn.2026-07.com.example:initiator01
set auth userid=user1
set auth password=secret_pass_123
```

#### Взаимный CHAP (Инициатор также проверяет таргет)
```bash
set auth mutual_userid=target_user
set auth mutual_password=target_pass_456
```

## Эксплуатация и обслуживание

### Резервное копирование конфигурации

Конфигурация LIO хранится в JSON-формате.

- **Путь по умолчанию:** `/etc/rtslib-fb-target/saveconfig.json`.
- **Ручное сохранение:** В `targetcli` выполнить `saveconfig`.
- **Создание бэкапа:**
  ```bash
  sudo targetcli saveconfig /root/iscsi_backup_$(date +%F).json
  ```
- **Восстановление:**
  ```bash
  sudo targetcli restoreconfig /root/iscsi_backup.json
  ```

### Персистентность
Убедитесь, что конфигурация автоматически загружается при старте системы:
```bash
sudo systemctl enable --now target
```
*Примечание:* В некоторых дистрибутивах сервис называется `targetcli.service`.

### Диагностика на стороне сервера

1.  **Проверка активных сессий:**
    ```bash
    ls /iscsi/iqn.2026-07.com.example:target01/tpg1/acls/iqn.2026-07.com.example:initiator01/
    # → Если папка 'info' содержит данные, сессия активна.
    ```
2.  **Просмотр структуры через sysfs:**
    ```bash
    ls -R /sys/kernel/config/target/
    ```
3.  **Логи ошибок:**
    ```bash
    sudo dmesg | grep -i target
    ```

### Сценарий 3: Настройка backstore type=fileio

Для тестовых сред или случаев, когда выделенный диск недоступен:

```bash
# Создание файлового backstore (10GB файл-образ)
truncate -s 10G /var/lib/iscsi/disk01.img

sudo targetcli
/backstores/fileio create name=fileio01 file=/var/lib/iscsi/disk01.img size=10G

# Дальнейшая настройка аналогична block-backstore
/iscsi create iqn.2026-07.com.example:target_fileio
/iscsi/iqn.2026-07.com.example:target_fileio/tpg1/luns create /backstores/fileio/fileio01
```

*Примечание:* fileio backstore имеет значительные накладные расходы из-за double-buffering (пользовательский буфер → ядро → ФС → диск). Используйте только для тестов или development-сред.

### Сценарий 4: Экспорт нескольких LUN

На практике один таргет часто предоставляет несколько LUN (например, system + data + backup):

```bash
sudo targetcli

# Создание двух backstores
/backstores/block create name=lv_system dev=/dev/vg_iscsi/lv_system
/backstores/block create name=lv_data dev=/dev/vg_iscsi/lv_data

# Создание таргета
/iscsi create iqn.2026-07.com.example:storage.target01

# Добавление LUN 0 (system)
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1/luns create /backstores/block/lv_system

# Добавление LUN 1 (data)
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1/luns create /backstores/block/lv_data

# ACL для инициатора
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1/acls create iqn.2026-07.com.example:initiator01

# Просмотр результата
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1/luns ls
# → LUN 0  /backstores/block/lv_system
#   LUN 1  /backstores/block/lv_data
```

На стороне инициатора после Discovery и Login будут видны два блочных устройства (`/dev/sdb`, `/dev/sdc`).

### Управление активными сессиями (отключение инициаторов)

Если необходимо отключить конкретного инициатора без перезапуска сервиса:

```bash
# На сервере: принудительное закрытие сессии
echo 1 > /sys/kernel/config/target/iscsi/iqn.2026-07.com.example:storage.target01/tpg1/acls/iqn.2026-07.com.example:initiator01/enable
# → 0 = отключить, 1 = включить

# Или через targetcli:
cd /iscsi/iqn.2026-07.com.example:storage.target01/tpg1/acls/iqn.2026-07.com.example:initiator01
set attribute sam_bit=0
```

### Сценарий 5: Настройка backstore type=pscsi (Pass-through)

Прямой проброс физического SCSI-устройства инициатору. Используется для tape-библиотек, hardware RAID-контроллеров или USB-дисков.

```bash
sudo targetcli

# Определение SCSI-устройства (например, /dev/sr0 — CD-ROM, /dev/sda — диск)
lsblk -o NAME,SIZE,TYPE,SERIAL
# → NAME   SIZE TYPE SERIAL
#   sda    500G disk  ABC123

# Создание pscsi backstore
/backstores/pscsi create name=pscsi_disk0 dev=/dev/sda

# Дальнейшая настройка аналогична block-backstore
/iscsi create iqn.2026-07.com.example:target_pscsi
/iscsi/iqn.2026-07.com.example:target_pscsi/tpg1/luns create /backstores/pscsi/pscsi_disk0
/iscsi/iqn.2026-07.com.example:target_pscsi/tpg1/acls create iqn.2026-07.com.example:initiator01
/iscsi/iqn.2026-07.com.example:target_pscsi/tpg1/portals create 0.0.0.0
```

*Примечание:* pscsi backstore передаёт SCSI-команды напрямую физическому устройству. Это означает, что инициатор получает полный контроль над оборудованием — убедитесь, что ACL настроены корректно.

### Сценарий 6: Настройка backstore type=ramdisk

Временное хранилище в оперативной памяти. Данные полностью теряются при перезагрузке или отключении питания.

```bash
sudo targetcli

# Создание ramdisk backstore (1GB)
/backstores/ramdisk create name=ramdisk01 size=1G

# Настройка таргета
/iscsi create iqn.2026-07.com.example:target_ramdisk
/iscsi/iqn.2026-07.com.example:target_ramdisk/tpg1/luns create /backstores/ramdisk/ramdisk01
/iscsi/iqn.2026-07.com.example:target_ramdisk/tpg1/acls create iqn.2026-07.com.example:initiator01
/iscsi/iqn.2026-07.com.example:target_ramdisk/tpg1/portals create 0.0.0.0
```

**Use cases:**
- Тестирование производительности iSCSI (без влияния дисковой подсистемы)
- Временные данные для вычислений (HPC, scientific computing)
- Кэширование frequently accessed данных (как RAM-disk cache)

### Сценарий 7: Привязка к конкретному IP-адресу (Portal)

По умолчанию target слушает на всех интерфейсах (`0.0.0.0:3260`). Для безопасности лучше привязать к конкретному IP:

```bash
sudo targetcli

# Удаление стандартного портала
/iscsi/iqn.2026-07.com.example:target01/tpg1/portals delete 0.0.0.0:3260

# Создание портала на конкретном IP (только SAN-интерфейс)
/iscsi/iqn.2026-07.com.example:target01/tpg1/portals create 10.10.1.100

# Проверка
/iscsi/iqn.2026-07.com.example:target01/tpg1/portals ls
# → o- portals
#   o- 10.10.1.100:3260
```

*Примечание:* Если target-сервер имеет несколько сетевых карт (SAN + Management), привязка к SAN-интерфейсу исключает утечку iSCSI-трафика через management-сеть.

## Оптимизация сети на стороне Target

iSCSI-трафик требует оптимизации сетевого стека на target-сервере для достижения максимальной производительности.

### Sysctl для Target

```bash
# /etc/sysctl.d/99-iscsi-target.conf

# === TCP Buffers (для больших объёмов данных) ===
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728
net.ipv4.tcp_rmem = 4096 87380 134217728
net.ipv4.tcp_wmem = 4096 65536 134217728

# === Backlog (много одновременных подключений) ===
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535

# === Congestion Control ===
net.ipv4.tcp_congestion_control = cubic
net.core.default_qdisc = fq

# === Keepalive (обнаружение мёртвых пиров) ===
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 15
net.ipv4.tcp_keepalive_probes = 5

# Применение
sudo sysctl --system
```

### Jumbo Frames на Target

```bash
# Установка MTU 9000 на SAN-интерфейсе
sudo ip link set dev eth1 mtu 9000

# Проверка
ip link show eth1 | grep mtu
# → mtu 9000

# Сохранение (systemd-networkd)
cat << 'EOF' | sudo tee /etc/systemd/network/70-iscsi-target.network
[Match]
Name=eth1

[Link]
MTUBytes=9000
EOF
```

### RSS (Receive Side Scaling) и IRQ Affinity

Для Multi-queue NIC распределите прерывания по ядрам CPU:

```bash
# Проверка NUMA-узла NIC
cat /sys/class/net/eth1/device/numa_node
# → 0

# Привязка IRQ к ядрам NUMA-узла 0
for irq in $(grep eth1 /proc/interrupts | awk '{print $1}' | tr -d ':'); do
    echo 1 > /proc/irq/$irq/smp_affinity
done
```

Для полного описания оптимизации см. [Оптимизация производительности iSCSI](./iscsi_performance.md).

## Производительность Target

### I/O Scheduler

Для iSCSI-устройств (block backstore) рекомендуется `none` или `mq-deadline`:

```bash
# Просмотр текущего планировщика
cat /sys/block/sda/queue/scheduler
# → [none] mq-deadline kyber bfq

# Установка (временно)
echo none | sudo tee /sys/block/sda/queue/scheduler

# Постоянная настройка (udev rule)
cat << 'EOF' | sudo tee /etc/udev/rules.d/60-iscsi-scheduler.rules
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/scheduler}="none"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### Write Cache

```bash
# Проверка текущего режима
sudo targetcli /backstores/block/storage01 get attribute
# → emulated=0 (write-through)

# Включение write-back (ускорение записи, но риск потери данных при аварии)
sudo targetcli /backstores/block/storage01 set attribute emulated=1

# Отключение write-back (безопасный режим)
sudo targetcli /backstores/block/storage01 set attribute emulated=0
```

**Важно:** Write-back кэш безопасен только при наличии:
- RAID-контроллера с батарейной защитой (BBU/BPS)
- ИБП (UPS) на target-сервере
- Поддержки flush/force_unit_access на инициаторе

### Queue Depth

```bash
# Просмотр текущего queue depth
cat /sys/block/sda/queue/nr_requests
# → 128

# Увеличение для NVMe-дисков
echo 256 | sudo tee /sys/block/sda/queue/nr_requests
```

## Безопасность: чек-лист

| Мера | Описание | Как проверить |
| :--- | :--- | :--- |
| **CHAP аутентификация** | Односторонний или взаимный CHAP | `targetcli .../acls/... get auth` |
| **ACL (IQN-фильтрация)** | Разрешённые только конкретные IQN | `targetcli .../acls ls` |
| **Portal привязка** | Таргет слушает только на SAN-интерфейсе | `targetcli .../portals ls` |
| **Firewall** | Порт 3260/tcp открыт только для SAN-подсети | `sudo firewall-cmd --list-all` |
| **Network isolation** | SAN-трафик выделен в отдельную VLAN/subnet | Проверка на коммутаторе |
| **saveconfig protection** | Файл конфигурации защищён от чтения | `ls -la /etc/rtslib-fb-target/saveconfig.json` |

Для полного описания мер безопасности см. [Безопасность iSCSI](./iscsi_security.md).

## Типичные ошибки и решение

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `iscsiadm: No active sessions` | Инициатор не подключён | Проверить ACL, CHAP, firewall |
| `Connection refused` | Target не слушает порт 3260 | `ss -tlnp | grep 3260`, `systemctl status target` |
| `CHAP authentication failure` | Неверный userid/password | Проверить credentials на обеих сторонах |
| `LUN not found` | LUN не сопоставлен с backstore | `targetcli .../luns ls`, проверить path backstore |
| `Access denied for initiator` | IQN инициатора не в ACL | `targetcli .../acls create <IQN>` |
| `target.service: Failed` | Ошибка загрузки конфигурации | `journalctl -u target`, проверить `saveconfig.json` |
| `Device is busy` | Backstore используется другим процессом | `lsof /dev/sda`, `fuser -m /dev/sda` |

Для подробной диагностики см. [Диагностика iSCSI](./iscsi_diagnostics.md).

## Скрипт автоматизации: проверка здоровья Target

```bash
#!/bin/bash
# iscsi_target_health_check.sh — проверка состояния iSCSI target

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0

check() {
    local desc="$1"
    local result="$2"
    if [ "$result" = "OK" ]; then
        echo -e "${GREEN}[OK]${NC}   $desc"
    else
        echo -e "${RED}[FAIL]${NC} $desc — $result"
        ((ERRORS++))
    fi
}

echo "=== iSCSI Target Health Check ==="
echo ""

# 1. Проверка сервиса target
if systemctl is-active --quiet target; then
    check "Service target" "OK"
else
    check "Service target" "Сервис не запущен"
fi

# 2. Проверка сессий
SESSIONS=$(targetcli /iscsi ls 2>/dev/null | grep -c "i>" || echo 0)
if [ "$SESSIONS" -gt 0 ]; then
    check "Active sessions ($SESSIONS)" "OK"
else
    check "Active sessions" "Нет активных сессий"
fi

# 3. Проверка портала
if ss -tlnp | grep -q ":3260"; then
    check "Portal 3260/tcp" "OK"
else
    check "Portal 3260/tcp" "Порт 3260 не слушается"
fi

# 4. Проверка ACL (пример для конкретного target)
TARGET_IQN="iqn.2026-07.com.example:target01"
if targetcli /iscsi/$TARGET_IQN/tpg1/acls ls &>/dev/null; then
    ACL_COUNT=$(targetcli /iscsi/$TARGET_IQN/tpg1/acls ls 2>/dev/null | grep -c "node_" || echo 0)
    check "ACL entries ($ACL_COUNT)" "OK"
else
    check "ACL entries" "Target $TARGET_IQN не найден"
fi

# 5. Проверка дискового пространства
DISK_USAGE=$(df -h /var/lib/iscsi 2>/dev/null | tail -1 | awk '{print $5}' | tr -d '%')
if [ "${DISK_USAGE:-0}" -lt 80 ]; then
    check "Disk usage ($DISK_USAGE%)" "OK"
else
    check "Disk usage ($DISK_USAGE%)" "Диск заполнен >80%"
fi

# 6. Проверка логов
ERRORS_COUNT=$(dmesg | grep -i "target\|iscsi" | grep -ci "error\|fail" || echo 0)
if [ "$ERRORS_COUNT" -eq 0 ]; then
    check "Kernel errors" "OK"
else
    check "Kernel errors ($ERRORS_COUNT)" "Есть ошибки в dmesg"
fi

echo ""
if [ "$ERRORS" -eq 0 ]; then
    echo -e "${GREEN}All checks passed${NC}"
    exit 0
else
    echo -e "${RED}$ERRORS check(s) failed${NC}"
    exit 1
fi
```

## Дополнительная информация

### Сравнение с tgt (Legacy)

`tgt` (scsi-target-utils) — user-space реализация. В 2026 году считается устаревшей и используется только для поддержки старых систем или специфических эмуляций. LIO превосходит `tgt` по производительности и нативной интеграции с ядром.

| Критерий | LIO | tgt |
| :--- | :--- | :--- |
| Пространство | Ядро (in-kernel) | User-space |
| Производительность | Выше (нет context switch) | Ниже |
| Backstores | block, fileio, pscsi, ramdisk | fileio, block |
| Управление | `targetcli` (configfs) | `tgtadm` |
| Multi-TPG | Да | Ограниченно |

### Интеграция и оптимизация

- **[Настройка iSCSI Initiator](./iscsi_initiator_setup.md)** — подключение клиента.
- **[Оптимизация производительности iSCSI](./iscsi_performance.md)** — тюнинг сетевого стека и параметров I/O.
- **[Безопасность iSCSI](./iscsi_security.md)** — настройка CHAP, ACL и сетевой изоляции.
- **[Мониторинг iSCSI](./iscsi_monitoring.md)** — сбор метрик и настройка алертинга.
- **[Диагностика iSCSI](./iscsi_diagnostics.md)** — решение проблем связности.
- **[Backup и DR](./iscsi_backup.md)** — резервное копирование и восстановление LUN.
- **[Настройка Firewall](../Settings/tools/firewalld.md)** — открытие порта 3260/tcp.
