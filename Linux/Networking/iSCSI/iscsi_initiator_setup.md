# iSCSI: Настройка инициатора (Клиент)

Руководство по установке, идентификации и подключению клиентской части iSCSI (инициатора) в ОС Linux.

## Зачем нужен iSCSI Initiator

iSCSI Initiator — это программный компонент, который позволяет Linux-хосту подключаться к удалённым блочным устройствам (LUN) по протоколу iSCSI. После подключения LUN отображаются как локальные блочные устройства (`/dev/sdb`, `/dev/sdc` и т.д.), с которыми можно работать как с обычными дисками.

**Типичные сценарии использования:**
- **Centralized Storage** — подключение к общему хранилищу (NAS/SAN) для виртуализации, баз данных, файловых серверов
- **Кластерные конфигурации** — shared storage для Pacemaker/Corosinx, GFS2/OCFS2
- **Виртуализация** — KVM/QEMU, Proxmox VE, oVirt используют iSCSI для хранения образов ВМ
- **Резервное копирование** — подключение LUN для borg, restic, bacula
- **Миграция данных** — live-миграция между серверами через общее хранилище
- **Boot from iSCSI** — загрузка ОС с сетевого диска (для diskless-серверов)

**Преимущества программного инициатора (open-iscsi):**
- Не требует специализированного оборудования (iSCSI HBA)
- Работает на любом Linux-хосте с Ethernet-картой
- Поддерживает Multipath I/O для отказоустойчивости
- Интегрирован в ядро Linux (модуль `iscsi_tcp`)

## Определения и сокращения

| Термин | Описание |
| :--- | :--- |
| **Initiator (Инициатор)** | Клиентское ПО или аппаратный адаптер, инициирующий SCSI-команды к удаленным хранилищам. |
| **iscsid** | Фоновый демон, управляющий сессиями, восстановлением соединений и обработкой событий протокола. |
| **iscsiadm** | Утилита командной строки для управления базами данных (discovery, node) и активными сессиями. |
| **Node (Узел)** | Запись в локальной БД инициатора, содержащая параметры подключения к конкретному таргету. |
| **iface (Interface)** | Объект в базе данных iSCSI, позволяющий привязать сессию к конкретной сетевой карте (NIC) или IP-адресу инициатора. |
| **Discovery** | Процесс опроса портала таргета для получения списка доступных IQN. |
| **Session (Сессия)** | Логическое соединение между инициатором и таргетом. Составляется из одного или нескольких TCP-соединений. |
| **Connection (Соединение)** | Одно TCP-соединение внутри сессии. Одна сессия может содержать до `MaxConnections` соединений. |
| **PDU (Protocol Data Unit)** | Единица обмена данными в iSCSI, содержащая заголовок и полезную нагрузку. |
| **ERL (Error Recovery Level)** | Уровень восстановления ошибок: 0 (базовый), 1 (сессиальный), 2 (connection-level). |
| **CHAP** | Протокол аутентификации по логину/паролю. Поддерживает односторонний и взаимный режимы. |
| **MPIO (Multipath I/O)** | Технология объединения нескольких физических путей к одному LUN для отказоустойчивости. |
| **iSER (iSCSI Extensions for RDMA)** | Расширение протокола, использующее RDMA для минимизации задержек и нагрузки на CPU. |
| **Backstore (Хранилище)** | Физическое или логическое устройство на сервере-таргете, из которого экспортируются LUN. |

## Основные концепции

### Стек open-iscsi

Инициатор в Linux (стек **open-iscsi**) представляет удаленные ресурсы (LUN) как стандартные локальные блочные устройства (например, `/dev/sdb`). Управление осуществляется через базы данных, хранящиеся в `/etc/iscsi/nodes/` и `/etc/iscsi/send_targets/`.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Пользовательское пространство                │
│                                                                     │
│  ┌─────────────┐     ┌──────────────┐     ┌──────────────────────┐  │
│  │   iscsiadm   │────▶│    iscsid    │────▶│  /etc/iscsi/         │  │
│  │   (CLI)      │     │   (демон)    │     │  ├── nodes/          │  │
│  └─────────────┘     └──────────────┘     │  ├── send_targets/   │  │
│                                            │  └── initiatorname   │  │
├────────────────────────────────────────────┤  .iscsi              │  │
│                        Ядро Linux          └──────────────────────┘  │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                     SCSI Subsystem                              │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐                     │ │
│  │  │ /dev/sda │  │ /dev/sdb │  │ /dev/sdc │  ← iSCSI LUN       │ │
│  │  └──────────┘  └──────────┘  └──────────┘                     │ │
│  └───────────────────────────┬─────────────────────────────────────┘ │
│                              │                                       │
│  ┌───────────────────────────▼─────────────────────────────────────┐ │
│  │              iSCSI Layer (модуль iscsi_tcp)                     │ │
│  │                                                                 │ │
│  │  ┌──────────────────────────────────────────────────────────┐   │ │
│  │  │  iscsi_tcp: ядерный драйвер, реализующий iSCSI протокол  │   │ │
│  │  │  • Инкапсуляция SCSI-команд в iSCSI PDU                  │   │ │
│  │  │  • Управление сессиями и соединениями                     │   │ │
│  │  │  • Восстановление ошибок (ERL 0/1/2)                     │   │ │
│  │  │  • CHAP аутентификация                                    │   │ │
│  │  └──────────────────────────────────────────────────────────┘   │ │
│  └───────────────────────────┬─────────────────────────────────────┘ │
│                              │                                       │
│  ┌───────────────────────────▼─────────────────────────────────────┐ │
│  │                     TCP/IP Stack                                │ │
│  │  • TCP: reliable delivery, congestion control                   │ │
│  │  • Порт: 3260/tcp (по умолчанию)                               │ │
│  │  • Поддержка: Jumbo Frames, RSS, TCP Offload                   │ │
│  └───────────────────────────┬─────────────────────────────────────┘ │
│                              │                                       │
│  ┌───────────────────────────▼─────────────────────────────────────┐ │
│  │                    Ethernet (1/10/25/100 GbE)                   │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

### Архитектура iface

Для сред с несколькими сетевыми интерфейсами (Multipath) недостаточно просто выполнить Discovery. Чтобы заставить iSCSI использовать конкретные физические пути, необходимо создать объекты `iface`, которые связывают драйвер iSCSI с конкретным сетевым интерфейсом хоста. Это предотвращает ситуацию, когда все сессии устанавливаются через один и тот же интерфейс по умолчанию.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Инициатор (хост)                             │
│                                                                     │
│  ┌──────────────┐     ┌──────────────┐                              │
│  │  iface eth0  │────▶│  eth0 (SAN)  │────┐                        │
│  └──────────────┘     └──────────────┘    │    ┌─────────────────┐  │
│                                           ├───▶│  Target Portal  │  │
│  ┌──────────────┐     ┌──────────────┐    │    │  10.10.1.20:3260│  │
│  │  iface eth1  │────▶│  eth1 (SAN)  │────┤    └─────────────────┘  │
│  └──────────────┘     └──────────────┘    │                        │
│                                           │    ┌─────────────────┐  │
│  ┌──────────────┐     ┌──────────────┐    ├───▶│  Target Portal  │  │
│  │  iface eth2  │────▶│  eth2 (SAN)  │────┘    │  10.10.2.20:3260│  │
│  └──────────────┘     └──────────────┘         └─────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## Практические сценарии

### 1. Установка и базовая идентификация

#### Установка пакетов
```bash
sudo apt update && sudo apt install open-iscsi -y
# Для RHEL/CentOS/Rocky: sudo dnf install iscsi-initiator-utils -y
```

#### Идентификация (IQN инициатора)
Отредактируйте `/etc/iscsi/initiatorname.iscsi`, указав уникальное имя:
```bash
InitiatorName=iqn.2026-07.com.example:client.node01
```
После изменения перезапустите демоны:
```bash
sudo systemctl restart iscsid open-iscsi
```

### 2. Настройка сетевых интерфейсов (iface)

Необходимо для Multipath. Если Multipath не используется, этот шаг можно пропустить.

```bash
# Создание объектов iface
sudo iscsiadm -m iface -I eth1_iface --op=new
sudo iscsiadm -m iface -I eth2_iface --op=new

# Привязка к физическим именам NIC
sudo iscsiadm -m iface -I eth1_iface --op=update -n iface.net_ifacename -v eth1
sudo iscsiadm -m iface -I eth2_iface --op=update -n iface.net_ifacename -v eth2
```

### 3. Подключение к хранилищу

#### Обнаружение таргетов (Discovery)
```bash
# Обычное обнаружение
sudo iscsiadm -m discovery -t sendtargets -p <TARGET_IP>

# Обнаружение через конкретные интерфейсы (для Multipath)
sudo iscsiadm -m discovery -t sendtargets -p <TARGET_IP> -I eth1_iface -I eth2_iface
```

#### Вход в систему (Login)
```bash
# Подключение к конкретному таргету через все настроенные пути
sudo iscsiadm -m node -T <TARGET_IQN> -p <TARGET_IP> --login

# Подключение ко всем известным узлам
sudo iscsiadm -m node --loginall=all
```

### 4. Настройка безопасности (CHAP)

#### Односторонний CHAP (таргет проверяет инициатора)

Если таргет требует авторизацию, обновите параметры узла **до** выполнения входа (Login).

```bash
sudo iscsiadm -m node -T <IQN> -p <IP> -o update -n node.session.auth.authmethod -v CHAP
sudo iscsiadm -m node -T <IQN> -p <IP> -o update -n node.session.auth.username -v <USER>
sudo iscsiadm -m node -T <IQN> -p <IP> -o update -n node.session.auth.password -v <PASS>
```

#### Взаимный CHAP (Mutual CHAP)

Инициатор также проверяет таргет, что защищает от подмены сервера хранения. На инициаторе используются параметры `username_in` и `password_in` для credentials таргета.

```bash
# Credentials инициатора (односторонний CHAP)
sudo iscsiadm -m node -T <TARGET_IQN> -p <IP> -o update \
  -n node.session.auth.authmethod -v CHAP
sudo iscsiadm -m node -T <TARGET_IQN> -p <IP> -o update \
  -n node.session.auth.username -v <USER>
sudo iscsiadm -m node -T <TARGET_IQN> -p <IP> -o update \
  -n node.session.auth.password -v '<PASS>'

# Credentials таргета (для mutual CHAP)
sudo iscsiadm -m node -T <TARGET_IQN> -p <IP> -o update \
  -n node.session.auth.username_in -v <TARGET_USER>
sudo iscsiadm -m node -T <TARGET_IQN> -p <IP> -o update \
  -n node.session.auth.password_in -v '<TARGET_PASS>'
```

#### Проверка конфигурации CHAP

```bash
# Просмотр параметров аутентификации
sudo iscsiadm -m node -T <TARGET_IQN> -p <IP> | grep auth
# → node.session.auth.authmethod = CHAP
# → node.session.auth.username = iscsi_user
# → node.session.auth.username_in = target_user
```

Для полного описания настройки CHAP, ACL и других мер безопасности см. [Безопасность iSCSI](./iscsi_security.md).

### 5. Подключение к нескольким таргетам

В реальных средах один инициатор часто подключается к нескольким таргетам (например, system + data + backup).

```bash
# Discovery всех таргетов на сервере
sudo iscsiadm -m discovery -t sendtargets -p 10.10.1.20
# → 10.10.1.20:3260,1 iqn.2026-07.com.example:storage.system
# → 10.10.1.20:3260,1 iqn.2026-07.com.example:storage.data
# → 10.10.1.20:3260,1 iqn.2026-07.com.example:storage.backup

# Просмотр всех обнаруженных узлов
sudo iscsiadm -m node
# → iqn.2026-07.com.example:storage.system,10.10.1.20,3260,1 default
# → iqn.2026-07.com.example:storage.data,10.10.1.20,3260,1 default
# → iqn.2026-07.com.example:storage.backup,10.10.1.20,3260,1 default

# Login ко всем узлам
sudo iscsiadm -m node --loginall=all

# Проверка результатов
lsblk
# → NAME   MAJ:MIN RM  SIZE RO TYPE MOUNTPOINT
# → sda      8:0    0   50G  0 disk
# ├─sda1   8:1    0   20G  0 part /
# ├─sda2   8:2    0   10G  0 part /boot
# └─sda3   8:3    0   20G  0 part /home
# → sdb      8:16   0  100G  0 disk            ← system LUN
# → sdc      8:32   0  500G  0 disk            ← data LUN
# → sdd      8:48   0  200G  0 disk            ← backup LUN
```

### 6. Автоматическое подключение при загрузке (per-target)

Для каждого таргета можно настроить автоматический Login при старте системы:

```bash
# Включение автоматического Login для конкретного узла
sudo iscsiadm -m node -T iqn.2026-07.com.example:storage.system \
  -p 10.10.1.20 -o update -n node.startup -v automatic

# Включение автоматического Login для всех узлов
sudo iscsiadm -m node --op=update -n node.startup -v automatic

# Проверка
sudo iscsiadm -m node | grep -E "automatic|manual"
# → iqn.2026-07.com.example:storage.system,10.10.1.20,3260,1 automatic
# → iqn.2026-07.com.example:storage.data,10.10.1.20,3260,1 automatic
```

**Важно:** Убедитесь, что сервис `open-iscsi` включён в автозагрузку:
```bash
sudo systemctl enable open-iscsi
```

### 7. Boot from iSCSI

Загрузка ОС с сетевого диска (iSCSI LUN) позволяет создавать diskless-серверы, что удобно для кластеров и масштабируемых сред.

**Требования:**
- NIC с поддержкой iSCSI Boot (PXE/UEFI) или программный iSCSI Boot
- Target, экспортирующий LUN с установленной ОС
- initramfs с модулем `iscsi_tcp`

#### Настройка на Target (экспорт boot-LUN)

```bash
# На сервере: создание LUN с установленной ОС
sudo targetcli
/backstores/block create name=boot_lun dev=/dev/vg_data/lv_boot
/iscsi create iqn.2026-07.com.example:storage.boot
/iscsi/iqn.2026-07.com.example:storage.boot/tpg1/luns create /backstores/block/boot_lun
/iscsi/iqn.2026-07.com.example:storage.boot/tpg1/acls create iqn.2026-07.com.example:diskless01
```

#### Настройка на Initiator (diskless-хост)

```bash
# Установка пакетов для iSCSI Boot
sudo apt install open-iscsi iscsi-dos2unix syslinux initramfs-tools -y

# Конфигурация InitiatorName
echo "InitiatorName=iqn.2026-07.com.example:diskless01" | sudo tee /etc/iscsi/initiatorname.iscsi

# Добавление iSCSI в initramfs
echo 'iscsi_target_name=iqn.2026-07.com.example:storage.boot' | sudo tee /etc/iscsi/iscsi.initramfs
echo 'iscsi_target_ip=10.10.1.20' | sudo tee -a /etc/iscsi/iscsi.initramfs
echo 'iscsi_target_port=3260' | sudo tee -a /etc/iscsi/iscsi.initramfs
echo 'iscsi_target_group=1' | sudo tee -a /etc/iscsi/iscsi.initramfs

# Пересборка initramfs
sudo update-initramfs -u

# Настройка загрузчика (GRUB)
# В /etc/default/grub установите root=UUID=<UUID boot LUN>
# или root=/dev/sda1 (после iSCSI Login)
```

#### Программный iSCSI Boot (BIOS/UEFI)

Для NIC без аппаратной поддержки iSCSI Boot используйте iPXE:

```bash
# Скачивание iPXE
git clone https://github.com/ipxe/ipxe.git
cd ipxe/src

# Создание boot-скрипта
cat > boot.ipxe << 'EOF'
#!ipxe
dhcp net0
set initiator-iqn iqn.2026-07.com.example:diskless01
set keep-san 1
sanboot iscsi:192.168.1.200::3260:1:iqn.2026-07.com.example:storage.boot
boot || reboot
EOF

# Сборка ROM для NIC
make bin/10ec8168.rom   # RTL8168
make bin/15e8.rom       # Intel
```

#### Настройка GRUB для iSCSI root

```bash
# В /etc/default/grub добавить:
GRUB_CMDLINE_LINUX="root=/dev/sda rootdelay=30"

# Пересборка GRUB
sudo update-grub
```

#### Добавление iSCSI в dracut (RHEL/Rocky)

```bash
# Добавление iSCSI модулей в initramfs
echo 'add_dracutmodules+=" iscsi iscsiroot "' | sudo tee -a /etc/dracut.conf.d/iscsi.conf

# Пересборка initramfs
sudo dracut --force

# Настройка параметров загрузки
echo 'iscsi_target_name=iqn.2026-07.com.example:storage.boot' | sudo tee /etc/iscsi/iscsi.initramfs
echo 'iscsi_target_ip=192.168.1.20' | sudo tee -a /etc/iscsi/iscsi.initramfs
```

#### Проверка конфигурации Boot from iSCSI

```bash
# Проверка доступности target перед reboot
sudo iscsiadm -m discovery -t sendtargets -p 192.168.1.200
sudo iscsiadm -m node -T iqn.2026-07.com.example:storage.boot --login

# Проверка что root FS примонтирован
mount | grep " / "
# → /dev/sda1 on / type ext4 (rw,relatime)

# Проверка fstab
cat /etc/fstab | grep "^/dev/sda"
# → UUID=<uuid>  /  ext4  defaults,_netdev  0 1
```

#### Частые проблемы Boot from iSCSI

| Проблема | Решение |
| :--- | :--- |
| `root device not found` | Добавить `rootdelay=30` в GRUB, проверить что initramfs содержит `iscsi_tcp` |
| `iscsiadm: No active sessions` | Проверить что `open-iscsi` включён в автозагрузку |
| `waiting for root device` | Увеличить `rootdelay=60`, проверить network cable |
| After reboot, iSCSI login fails | Использовать `node.startup=automatic` для автоматического login |
| Multiple paths cause issues | Настроить multipath, `multipath.conf` с `find_multipaths yes` |

**Примечание:** Для production-сред рекомендуется использовать hardware iSCSI HBA с PXE-поддержкой вместо программного boot-клиента.

## Эксплуатация и персистентность

### Тюнинг параметров сессии (`iscsid.conf`)

Для повышения стабильности в нестабильных сетях отредактируйте `/etc/iscsi/iscsid.conf`:

- **node.session.timeo.replacement_timeout**: Время (в сек.), которое ядро ждет перед тем, как признать устройство "мертвым" и перевести ФС в RO. Рекомендуется 120.
- **node.conn[0].timeo.noop_out_interval**: Интервал проверки активности соединения (Keepalive).
- **node.conn[0].timeo.noop_out_timeout**: Таймаут ответа на проверку.

```bash
# Примеры рекомендуемых значений для нестабильных сетей
sudo sed -i 's/node.session.timeo.replacement_timeout.*/node.session.timeo.replacement_timeout = 120/' /etc/iscsi/iscsid.conf
sudo sed -i 's/node.conn[0].timeo.noop_out_interval.*/node.conn[0].timeo.noop_out_interval = 15/' /etc/iscsi/iscsid.conf
sudo sed -i 's/node.conn[0].timeo.noop_out_timeout.*/node.conn[0].timeo.noop_out_timeout = 30/' /etc/iscsi/iscsid.conf

# Перезапуск демона после изменений
sudo systemctl restart iscsid
```

### Автоматическое подключение и монтирование

1.  **Автозагрузка сессий:**
    ```bash
    sudo iscsiadm -m node -T <TARGET_IQN> -o update -n node.startup -v automatic
    ```
2.  **Монтирование в /etc/fstab:**
    Используйте опцию `_netdev`, чтобы предотвратить зависание загрузки системы.
    ```text
    UUID=xxxx-xxxx  /mnt/data  ext4  defaults,_netdev,nofail  0  2
    ```

### Отключение от таргета (Logout)

```bash
# Отключение от конкретного таргета
sudo iscsiadm -m node -T <TARGET_IQN> -p <IP> --logout

# Отключение от всех таргетов
sudo iscsiadm -m node --logoutall=all

# Полное удаление записи о таргете из базы
sudo iscsiadm -m node -T <TARGET_IQN> -p <IP> -o delete
```

**Важно:** перед `logout` убедитесь, что все ФС смонтированы в read/write или отмонтированы. Принудительный logout при активных операциях I/O приведет к зависанию или повреждению данных.

### Rescan (обнаружение новых LUN)

Если на таргете были добавлены новые LUN или изменен размер существующего:

```bash
# Сканирование новых LUN
sudo iscsiadm -m session --rescan

# Принудительное обновление информации об устройстве
echo 1 | sudo tee /sys/class/block/sdX/device/rescan

# Обновление Multipath (если используется)
sudo multipath -r

# Проверка
lsblk
sudo multipath -ll
```

### Взаимодействие с LVM

Во избежание конфликтов и дублирования PV, настройте фильтры в `lvm.conf`. Подробнее см. в документе **[Настройка Multipath I/O](./iscsi_multipath.md#интеграция-с-lvm)**.

### Управление базой данных узлов

| Задача | Команда |
| :--- | :--- |
| Список активных сессий | `iscsiadm -m session -P 3` |
| Просмотр параметров узла | `iscsiadm -m node -T <IQN> -p <IP>` |
| Удаление узла из базы | `iscsiadm -m node -T <IQN> -p <IP> -o delete` |
| Сканирование новых LUN | `iscsiadm -m session --rescan` |
| Отключение от всех таргетов | `iscsiadm -m node --logoutall=all` |
| Просмотр discovery-базы | `iscsiadm -m discoverydb` |
| Удаление discovery-записи | `iscsiadm -m discovery -p <IP> -o delete` |
| Перезапуск демона | `sudo systemctl restart iscsid` |

## Оптимизация сети на стороне Initiator

iSCSI-трафик чувствителен к задержкам и потерям пакетов. Оптимизация сетевого стека на стороне инициатора критична для производительности.

### Sysctl для Initiator

```bash
# /etc/sysctl.d/99-iscsi-initiator.conf

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

### Jumbo Frames на Initiator

```bash
# Установка MTU 9000 на SAN-интерфейсе
sudo ip link set dev eth1 mtu 9000

# Проверка
ip link show eth1 | grep mtu
# → mtu 9000

# Сохранение (systemd-networkd)
cat << 'EOF' | sudo tee /etc/systemd/network/70-iscsi-initiator.network
[Match]
Name=eth1

[Link]
MTUBytes=9000
EOF
```

Для полного описания оптимизации см. [Оптимизация производительности iSCSI](./iscsi_performance.md).

## Типичные ошибки и решение

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `iscsiadm: No records found` | Нет discovery-записей | `iscsiadm -m discovery -t sendtargets -p <IP>` |
| `iscsiadm: initiator reported error (24 - could not send PDU to target)` | Сетевая проблема или target недоступен | Проверить сеть: `ping <TARGET_IP>`, `nc -zv <IP> 3260` |
| `iscsiadm: login failed to authenticate` | Неверный CHAP credentials | Проверить userid/password на обеих сторонах |
| `iscsiadm: connection login retries exceeded` | Target не отвечает | Проверить `systemctl status target`, firewall, ACL |
| `iscsiadm: Could not login to [TARGET]` | Отказ в доступе | Проверить ACL на target: `targetcli .../acls ls` |
| `sd X:X:X:X: [sda] tag#XX aborted` | Таймаут операции I/O | Увеличить `node.session.timeo.replacement_timeout` |
| `iscsiadm: kernel reported error (121 - remote I/O error)` | Проблема с backstore на target | Проверить LUN, диски, RAID на target-сервере |
| `iscsiadm: session information is not available` | Сессия не активна | `iscsiadm -m session --login`, проверить `systemctl status open-iscsi` |
| `Mount failed: mount: /mnt/data: unknown filesystem type '_netdev'` | Нет поддержки iSCSI в initramfs | Установить `open-iscsi`, `update-initramfs -u` |
| `iscsiadm: discovery session to [IP] failed` | Target не слушает порт 3260 | Проверить `ss -tlnp | grep 3260` на target |

Для подробной диагностики см. [Диагностика iSCSI](./iscsi_diagnostics.md).

## Скрипт автоматизации: проверка здоровья Initiator

```bash
#!/bin/bash
# iscsi_initiator_health_check.sh — проверка состояния iSCSI initiator

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

warn() {
    local desc="$1"
    local result="$2"
    echo -e "${YELLOW}[WARN]${NC} $desc — $result"
}

echo "=== iSCSI Initiator Health Check ==="
echo ""

# 1. Проверка сервисов
if systemctl is-active --quiet open-iscsi; then
    check "Service open-iscsi" "OK"
else
    check "Service open-iscsi" "Сервис не запущен"
fi

if systemctl is-active --quiet iscsid; then
    check "Service iscsid" "OK"
else
    check "Service iscsid" "Демон iscsid не запущен"
fi

# 2. Проверка InitiatorName
IQN=$(grep "^InitiatorName=" /etc/iscsi/initiatorname.iscsi 2>/dev/null | cut -d= -f2)
if [ -n "$IQN" ]; then
    check "InitiatorName ($IQN)" "OK"
else
    check "InitiatorName" "Не задан в /etc/iscsi/initiatorname.iscsi"
fi

# 3. Проверка активных сессий
SESSIONS=$(sudo iscsiadm -m session 2>/dev/null | grep -c "^tcp:" || echo 0)
if [ "$SESSIONS" -gt 0 ]; then
    check "Active sessions ($SESSIONS)" "OK"
else
    check "Active sessions" "Нет активных сессий"
fi

# 4. Проверка доступности target (попытка discovery)
TARGET_IPS=$(sudo iscsiadm -m discoverydb 2>/dev/null | grep -oP '\d+\.\d+\.\d+\.\d+' | sort -u)
if [ -n "$TARGET_IPS" ]; then
    for ip in $TARGET_IPS; do
        if nc -zw3 "$ip" 3260 2>/dev/null; then
            check "Target $ip:3260" "OK"
        else
            check "Target $ip:3260" "Недоступен"
        fi
    done
else
    warn "Discovery" "Нет записей discovery в базе"
fi

# 5. Проверка available devices
LUN_COUNT=$(lsblk -dno NAME,TYPE 2>/dev/null | grep -c "disk" || echo 0)
if [ "$LUN_COUNT" -gt 0 ]; then
    check "Block devices ($LUN_COUNT disks)" "OK"
else
    check "Block devices" "Нет обнаруженных дисков"
fi

# 6. Проверка ошибок в логах
ERRORS_COUNT=$(dmesg | grep -i "iscsi\|iscsid" | grep -ci "error\|fail" || echo 0)
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

### См. также

- **[Диагностика iSCSI](./iscsi_diagnostics.md)** — разбор ошибок и мониторинг.
- **[Основные концепции iSCSI](./iscsi_concepts.md)** — теория протокола.
- **[Настройка iSCSI Target](./iscsi_target_setup.md)** — конфигурация сервера.
- **[Безопасность iSCSI](./iscsi_security.md)** — настройка CHAP, ACL и изоляции.
- **[Оптимизация производительности iSCSI](./iscsi_performance.md)** — тюнинг параметров.
- **[Multipath I/O](./iscsi_multipath.md)** — отказоустойчивость и балансировка.
- **[Мониторинг iSCSI](./iscsi_monitoring.md)** — сбор метрик и алертинг.
- **[Backup и DR](./iscsi_backup.md)** — резервное копирование и восстановление LUN.

