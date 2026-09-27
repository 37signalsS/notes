# iSCSI: Шпаргалка по командам

Быстрая справка по основным командам iSCSI: target, initiator, multipath и диагностика.

## Target (серверная часть — LIO)

### Управление через targetcli

```bash
# Запуск targetcli
sudo targetcli

# Просмотр всей конфигурации
ls

# Навигация
cd /iscsi
cd /iscsi/iqn.2026-07.com.example:storage.target01/tpg1
cd /backstores

# Создание backstore (block)
/backstores/block create /dev/vg_storage/lv_data1 data1

# Создание backstore (fileio)
/backstores/fileio create /var/lib/iscsi/disk1.img 50G true

# Создание LUN
/luns create /backstores/block/data1

# Удаление LUN
/luns delete lun0

# Создание ACL
/acl create iqn.2026-07.com.example:node01
/acl create iqn.2026-07.com.example:node02

# Удаление ACL
/acl delete iqn.2026-07.com.example:node01

# Настройка TPG attributes
/iscsi/iqn.*/tpg1 set attribute demo_mode_write_protect=0
/iscsi/iqn.*/tpg1 set attribute cache_dynamic_acls=1

# Настройка authentication (CHAP)
/acl set attribute authentication=1
/acl set chap userid=user1 password=pass123

# Сохранение и выход
saveconfig
exit
```

### Управление через targetctl

```bash
# Загрузка конфигурации
sudo targetctl restoreconfig

# Сохранение конфигурации
sudo targetctl saveconfig

# Проверка статуса
sudo targetctl status
```

### Управление через sysfs

```bash
# Просмотр всех iSCSI таргетов
ls /sys/kernel/config/target/iscsi/

# Просмотр LUN конкретного таргета
ls /sys/kernel/config/target/iscsi/*/tpg*/luns/

# Просмотр ACL
ls /sys/kernel/config/target/iscsi/*/tpg*/acls/

# Просмотр размера LUN (в секторах)
cat /sys/kernel/config/target/iscsi/*/tpg*/luns/lun0/size

# Просмотр PR (Persistent Reservations)
cat /sys/kernel/config/target/iscsi/*/tpg*/luns/lun0/pr/res_aptpl_metadata
```

## Initiator (клиентская часть — open-iscsi)

### Обнаружение и подключение

```bash
# Discovery всех доступных таргетов
sudo iscsiadm -m discovery -t sendtargets -p 192.168.1.200:3260

# Discovery через SendTargets
sudo iscsiadm -m discovery -t sendtargets -p 192.168.1.200

# Discovery через iSNS
sudo iscsiadm -m discovery -t isns -p 192.168.1.201

# Login к конкретному таргету
sudo iscsiadm -m node -T iqn.2026-07.com.example:storage.target01 \
  -p 192.168.1.200 --login

# Login ко всем доступным таргетам
sudo iscsiadm -m node --loginall=all

# Logout от конкретного таргета
sudo iscsiadm -m node -T iqn.2026-07.com.example:storage.target01 \
  -p 192.168.1.200 --logout

# Logout от всех
sudo iscsiadm -m node --logoutall=all

# Просмотр активных сессий
sudo iscsiadm -m session

# Просмотр с детализацией (3 уровня)
sudo iscsiadm -m session -P 3

# Просмотр конкретной сессии
sudo iscsiadm -m session -P 1 -r <session_id>
```

### Управление настройками

```bash
# Просмотр параметров узла
sudo iscsiadm -m node -T <IQN> -p <IP>

# Обновление параметра
sudo iscsiadm -m node -T <IQN> -p <IP> \
  -o update -n node.startup -v automatic

# Настройка CHAP
sudo iscsiadm -m node -T <IQN> -p <IP> \
  -o update -n node.session.auth.authmethod -v CHAP
sudo iscsiadm -m node -T <IQN> -p <IP> \
  -o update -n node.session.auth.username -v user1
sudo iscsiadm -m node -T <IQN> -p <IP> \
  -o update -n node.session.auth.password -v pass123

# Удаление записи об узле
sudo iscsiadm -m node -T <IQN> -p <IP> -o delete

# Удаление всех записей
sudo iscsiadm -m node -o delete

# Удаление записи об обнаружении
sudo iscsiadm -m discoverydb -t st -p <IP> -o delete
```

### Rescan и обнаружение изменений

```bash
# Rescan всех iSCSI-сессий
sudo iscsiadm -m session --rescan

# Rescan SCSI-шин
sudo rescan-scsi-bus.sh

# Просмотр SCSI-устройств
ls /sys/class/scsi_device/

# Rescan конкретного устройства
echo 1 | sudo tee /sys/class/scsi_device/*/device/rescan

# Просмотр нового размера LUN
sudo blockdev --getsize64 /dev/sda
lsblk
```

## Multipath

### Управление multipathd

```bash
# Запуск multipathd
sudo systemctl start multipathd

# Просмотр multipath-устройств
sudo multipath -ll
# → mpatha (3600605b00a1b2c3d) dm-0 LIO,LAGER1
# → size=100G features='0' hwhandler='0' wp=rw
# │
# ├─ sdg 8:48  0 100G  0  session  [active]
# ├─ sdh 8:64  0 100G  0  session  [active]
# └─ sdi 8:80  0 100G  0  session  [active]

# Принудительное обновление карты
sudo multipath -r

# Просмотр multipath.conf
sudo multipathd show config

# Перечитывание конфигурации
sudo multipathd reconfigure

# Привязка к NUMA-узлу
sudo multipathd show topology
```

### Настройка multipath.conf

```bash
# Основные секции
defaults {
    polling_interval    30
    path_grouping_policy  multibus
    uid_attribute       ID_SERIAL
    path_selector       "round-robin 0"
    failback            immediate
    no_path_retry       5
    user_friendly_names yes
}

# Пример для iSCSI
devices {
    device {
        vendor          "LIO-TCM"
        product         "LAGER1"
        path_grouping_policy  multibus
        path_selector       "round-robin 0"
        no_path_retry       5
    }
}

# Пример для hardware-массива
devices {
    device {
        vendor          "NETAPP"
        product         "LUN"
        path_grouping_policy  group_by_prio
        path_selector       "round-robin 0"
        path_checker        tur
        failback            immediate
    }
}
```

## Диагностика

### Проверка статуса

```bash
# Статус iSCSI сессий
sudo iscsiadm -m session -P 3

# Статус SCSI-устройств
ls /sys/class/scsi_device/

# Статус multipath
sudo multipath -ll

# Просмотр логов iSCSI
sudo journalctl -u iscsid -f
sudo journalctl -u open-iscsi -f

# Просмотр dmesg
sudo dmesg | grep -iE "iscsi|scsi|mpath"
```

### Анализ сети

```bash
# Проверка доступности target
nc -zv 192.168.1.200 3260
# → Connection to 192.168.1.200 3260 port [tcp/*] succeeded!

# Ping через iSCSI-интерфейс
ping -c 5 -I eth1 192.168.1.200

# Анализ TCP-соединений
ss -tnp | grep 3260

# Захват трафика (10 секунд)
sudo tcpdump -i eth1 -w /tmp/iscsi.pcap -c 1000 port 3260

# Анализ pcap
tshark -r /tmp/iscsi.pcap -Y "iscsi" -T fields -e iscsi.opcode
```

### Анализ производительности

```bash
# Метрики блочных устройств
iostat -xmt 5 10 /dev/sda

# Просмотр I/O латентности
iostat -xmt 1 30 /dev/sda | awk '/sd[a-z]/{print $0}'

# Просмотр queue depth
cat /sys/class/scsi_disk/*/queue/nr_requests

# Просмотр размеров буферов
cat /sys/class/block/sda/queue/nr_requests
cat /sys/class/block/sda/queue/read_ahead_kb

# Аналитика через blktrace
sudo blktrace -d /dev/sda -o - | blkparse -i - | head -100
```

### SCSI Persistent Reservations

```bash
# Просмотр PR
sudo sg_persist -r /dev/sda

# Регистрация
sudo sg_persist -s -I 0x<KEY> /dev/sda

# Резервирование
sudo sg_persist -W -T 5 -K 0x<KEY> /dev/sda

# Preempt (failover)
sudo sg_persist --preempt --abort -T 5 \
  -K 0x<NEW_KEY> -I 0x<OLD_KEY> /dev/sda

# Очистка всех PR
sudo sg_persist -C /dev/sda
```

## Быстрые ссылки

| Задача | Команда |
| :--- | :--- |
| Discovery таргетов | `sudo iscsiadm -m discovery -t sendtargets -p <IP>` |
| Login | `sudo iscsiadm -m node -T <IQN> -p <IP> --login` |
| Login ко всем | `sudo iscsiadm -m node --loginall=all` |
| Logout | `sudo iscsiadm -m node -T <IQN> -p <IP> --logout` |
| Статус сессий | `sudo iscsiadm -m session` |
| Детальный статус | `sudo iscsiadm -m session -P 3` |
| Rescan | `sudo iscsiadm -m session --rescan` |
| Автозапуск | `sudo iscsiadm -m node -T <IQN> -o update -n node.startup -v automatic` |
| CHAP настройка | `sudo iscsiadm -m node -T <IQN> -o update -n node.session.auth.authmethod -v CHAP` |
| Multipath статус | `sudo multipath -ll` |
| Multipath обновление | `sudo multipath -r` |
| iSCSI логи | `sudo journalctl -u iscsid -f` |
| PR просмотр | `sudo sg_persist -r /dev/sdX` |

## См. также

- **[Основные концепции iSCSI](./iscsi_concepts.md)** — теория протокола
- **[Настройка iSCSI Target](./iscsi_target_setup.md)** — серверная часть
- **[Настройка iSCSI Initiator](./iscsi_initiator_setup.md)** — клиентская часть
- **[Настройка Multipath I/O](./iscsi_multipath.md)** — отказоустойчивость путей
- **[Диагностика iSCSI](./iscsi_diagnostics.md)** — разбор проблем
