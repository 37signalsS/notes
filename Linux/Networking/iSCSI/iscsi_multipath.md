# iSCSI: Настройка Multipath I/O

**Multipath I/O (Многопутевой ввод-вывод)** — технология, позволяющая операционной системе использовать несколько независимых физических или логических путей для доступа к одному и тому же блочному устройству (LUN) на системе хранения данных (СХД). В контексте iSCSI это критически важно для обеспечения высокой доступности (High Availability) и агрегации пропускной способности.

## Определения и сокращения

| Термин | Описание |
| :--- | :--- |
| **Multipathd** | Демон в Linux, осуществляющий мониторинг путей, управление группами приоритетов и переключение при сбоях. |
| **WWID (World Wide Identifier)** | Глобально уникальный идентификатор устройства (LUN), по которому ОС понимает, что разные пути ведут к одному диску. |
| **ALUA (Asymmetric Logical Unit Access)** | Протокол, позволяющий СХД сообщать инициатору статус портов контроллера (Active/Optimized, Active/Non-Optimized, Standby). |
| **MPIO** | Multipath I/O (Многопутевой ввод-вывод) — общий термин для технологии. |
| **Failover** | Режим автоматического переключения ввода-вывода на резервный путь при отказе основного. |
| **Path Grouping Policy** | Алгоритм, определяющий, как доступные пути объединяются в группы (например, multibus, failover). |
| **DM (Device Mapper)** | Подсистема ядра Linux, предоставляющая механизм виртуальных блочных устройств. Multipath работает как target DM. |
| **fast_io_fail_tmo** | Таймаут (сек), через который I/O-операции на отказавшем пути прерываются с ошибкой (вместо зависания). |
| **dev_loss_tmo** | Таймаут (сек), через который устройство полностью удаляется из системы после потери всех путей. |
| **Path Checker** | Метод проверки доступности пути (TUR, readsector0, directio и др.). |

## Основные концепции

### Механизм объединения путей

Без использования Multipath, если инициатор подключен к таргету через два сетевых интерфейса, ОС увидит два отдельных блочных устройства (например, `/dev/sdb` и `/dev/sdc`), которые на самом деле являются одним и тем же диском. Прямая запись на оба устройства приведет к немедленному повреждению файловой системы.

`multipathd` идентифицирует такие устройства по их **WWID**, "скрывает" базовые пути и создает виртуальное составное устройство в `/dev/mapper/mpathX`. Все операции ввода-вывода приложения должны направлять только на это виртуальное устройство.

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                          Приложение / ФС                                │
├─────────────────────────────────────────────────────────────────────────┤
│                     /dev/mapper/mpatha  (виртуальное устройство)         │
├───────────────────────┬─────────────────────┬───────────────────────────┤
│   Путь A (eth1)      │   Путь B (eth2)     │   Путь C (eth3)          │
│   VLAN 100            │   VLAN 200           │   VLAN 300               │
│   192.168.100.x       │   192.168.200.x      │   192.168.300.x          │
├───────────────────────┴─────────────────────┴───────────────────────────┤
│                           iSCSI Network (SAN)                           │
├───────────────────────┬─────────────────────┬───────────────────────────┤
│   Target Portal A    │   Target Portal B   │   Target Portal C        │
│   192.168.100.20     │   192.168.200.20    │   192.168.300.20         │
└───────────────────────┴─────────────────────┴───────────────────────────┘
```

### Политики группировки путей (Path Grouping Policies)

Политики определяют стратегию выбора пути:

| Политика | Описание | Применение |
| :--- | :--- | :--- |
| **failover** | Только один активный путь. Остальные в режиме ожидания. | Простые среды, не требующие балансировки |
| **multibus** | Все пути объединяются в одну группу, нагрузка распределяется равномерно. | Балансировка нагрузки без приоритетов |
| **group_by_prio** | Пути группируются на основе приоритета (обычно ALUA). | Рекомендуется для СХД с ALUA-поддержкой |
| **group_by_node_name** | Группировка по имени узла (таргета). | Специфичные конфигурации |

### ALUA: Как это работает

ALUA (Asymmetric Logical Unit Access) — протокол, позволяющий СХД сообщать инициатору, какой из портов является оптимальным для I/O. Это критически важно для production-сред с несколькими контроллерами.

**Состояния портов LIO:**

| Состояние | Описание | Приоритет (по умолчанию) |
| :--- | :--- | :--- |
| Active/Optimized (A/O) | Основной путь, максимальная производительность | 50 |
| Active/Non-Optimized (A/N) | Резервный путь, работает но медленнее | 10 |
| Standby | Путь не используется для I/O | 0 |

```bash
# Проверка ALUA-состояния на стороне LIO (target):
cat /sys/kernel/config/target/iscsi/*/tpg1/luns/*/alua_tg_pt_state
# → AO (Active/Optimized) или AN (Active/Non-optimized)

# Проверка приоритета пути в multipath:
multipathd show paths format "%d %t %T %p %s"
# → Столбец "prio" показывает текущий приоритет для каждого пути

# Пример вывода:
# sdb 1:0:0:1  AO  50 sdb
# sdc 2:0:0:1  AN  10 sdc
```

**Важно:** ALUA работает только с `path_grouping_policy "group_by_prio"` и `prio "alua"` в конфигурации multipath.

### Методы проверки путей (Path Checkers)

| Метод | Описание | Применение |
| :--- | :--- | :--- |
| `tur` | Test Unit Ready — стандартная SCSI-команда | Рекомендуется для большинства СХД |
| `readsector0` | Чтение первого сектора устройства | Для устройств без поддержки TUR |
| `directio` | Прямое чтение через O_DIRECT | Альтернатива tur для некоторых массивов |
| `hp_sw` | HP-specific sequence (Start/Stop) | Только для Legacy HP arrays |
| `cciss_tur` | TUR через CCISS интерфейс | Только для HP Smart Array |

```bash
# Проверка как работает path_checker:
multipathd show paths format "%d %t %T %p %s %z"
# → Столбец "chkr" показывает текущий статус проверки
```

## Сетевая топология для Multipath

Для отказоустойчивости каждый путь multipath должен проходить через независимую сетевую инфраструктуру.

### Рекомендуемая топология

```text
Initiator                    Target
┌──────────┐                ┌──────────┐
│  eth1    │── VLAN 100 ──▶│  eth1    │  ← Путь A (192.168.100.x)
│  (IP-A)  │   (Core SW1)  │  (IP-A)  │
│          │                │          │
│  eth2    │── VLAN 200 ──▶│  eth2    │  ← Путь B (192.168.200.x)
│  (IP-B)  │   (Core SW2)  │  (IP-B)  │
└──────────┘                └──────────┘
```

**Ключевые правила:**

| Правило | Описание | Приоритет |
| :--- | :--- | :--- |
| **Отдельные VLAN** | Каждый путь через отдельный VLAN | Обязательно |
| **Отдельные коммутаторы** | Физическая изоляция путей | Рекомендуется |
| **Отдельные подсети** | Каждый путь в своей подсети (192.168.100.0/24, 192.168.200.0/24) | Обязательно |
| **Отдельные NIC** | Не совмещать iSCSI с пользовательским LAN | Рекомендуется |
| **MTU 9000** | Jumbo Frames согласованы на всех звеньях | Рекомендуется |
| **Без LACP/bonding** | Multipath сам балансирует; NIC bonding не нужен | Обязательно |

### Проверка MTU

```bash
# Проверка MTU между инициатором и таргетом для каждого пути
ping -M do -s 8972 -c 3 192.168.100.20  # Путь A
ping -M do -s 8972 -c 3 192.168.200.20  # Путь B
```

## Практические сценарии

### Отличия между дистрибутивами

| Компонент | Debian/Ubuntu | RHEL/Rocky/AlmaLinux |
| :--- | :--- | :--- |
| Пакет | `multipath-tools` | `device-mapper-multipath` |
| Сервис | `multipathd` | `multipathd` |
| Конфигурация | `/etc/multipath.conf` | `/etc/multipath.conf` |
| initramfs | `update-initramfs -u` | `dracut --force` |
| Логи | `/var/log/syslog` | `/var/log/messages` |
| Проверка модуля | `lsmod \| grep dm_multipath` | `lsmod \| grep dm_multipath` |

### 1. Установка и базовая инициализация

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install multipath-tools -y

# RHEL/Rocky
sudo dnf install device-mapper-multipath -y

# Запуск и включение автозагрузки демона
sudo systemctl enable --now multipathd
```

### 2. Конфигурация (/etc/multipath.conf)

#### Базовая конфигурация для LIO с ALUA

```ini
defaults {
    # Использовать понятные имена вместо WWID (например, mpatha)
    user_friendly_names yes
    # Автоматически добавлять устройства с несколькими путями
    find_multipaths smart
    # Период опроса путей (секунды)
    polling_interval 5
    # Максимальный интервал при проблемах
    max_polling_interval 20
    # Интервал запуска checker (сек)
    checker_interval 5
    # I/O перед переключением пути (round-robin)
    rr_min_io 100
    # Вес при round-robin
    rr_weight priorities
    # Очищать буфер при удалении последнего пути
    flush_on_last_del no
    # Очередь I/O без multipathd
    queue_without_daemon no
}

blacklist {
    # Исключение системных и локальных дисков
    devnode "^(ram|raw|loop|fd|md|dm-|sr|scd|st)[0-9]*"
    devnode "^sda"
}

devices {
    device {
        vendor "LIO-ORG"
        product ".*"
        # Использование ALUA для приоритизации путей
        prio "alua"
        path_grouping_policy "group_by_prio"
        # Алгоритм балансировки внутри группы
        path_selector "service-time 0"
        # Метод проверки исправности пути
        path_checker tur
        # Возврат на оптимальный путь при его восстановлении
        failback immediate
        # Количество повторных попыток при отказе всех путей
        no_path_retry 10
        # Таймаут до пометки пути как failed (сек)
        fast_io_fail_tmo 10
        # Максимальное время до удаления устройства (сек)
        dev_loss_tmo 60
    }
}
```

#### Справочник ключевых параметров multipath.conf

| Параметр | Значение по умолч. | Описание | Рекомендация |
| :--- | :--- | :--- | :--- |
| `polling_interval` | 5 | Интервал проверки путей (сек) | 5 для SSD, 10 для HDD |
| `max_polling_interval` | 20 | Макс. интервал при проблемах | 20-30 |
| `checker_interval` | 5 | Интервал запуска checker (сек) | Совпадает с polling_interval |
| `rr_min_io` | 1000 | I/O перед переключением пути (round-robin) | 100 для SSD, 1000 для HDD |
| `rr_weight` | priorities | Вес при round-robin | priorities для ALUA |
| `pg_timeout` | none | Таймаут path group (сек) | none (автоматически) |
| `flush_on_last_del` | no | Очищать буфер при удалении последнего пути | no |
| `queue_without_daemon` | no | Очередь I/O без multipathd | no |
| `no_path_retry` | fail | Поведение при потере всех путей | fail для DB, число для batch |
| `failback` | immediate | Возврат на основной путь | immediate для ALUA |
| `fast_io_fail_tmo` | off | Таймаут до ошибки I/O на failed пути | 5-15 сек для production |
| `dev_loss_tmo` | 60 | Макс. время до удаления устройства | 60-300 сек (или off) |

**Значения `no_path_retry`:**
- `fail` — вернуть ошибку I/O немедленно (для баз данных)
- `queue` — поставить I/O в очередь (для batch-задач)
- Число — количество повторных попыток перед fail

#### Таймауты отказов (dev_loss_tmo / fast_io_fail_tmo)

Эти параметры критически важны для resilience iSCSI-подключений:

| Параметр | Описание | Когда срабатывает | Рекомендация |
| :--- | :--- | :--- | :--- |
| `fast_io_fail_tmo` | Время (сек) до пометки пути как failed | Потеря связи с путём | 5-15 сек для production |
| `dev_loss_tmo` | Максимальное время (сек) до удаления устройства | Все пути потеряны | 60-300 сек (или `off`) |

**Взаимодействие с iSCSI:**
- `fast_io_fail_tmo` в multipath должен быть **меньше** `node.session.timeo.replacement_timeout` в `iscsid.conf` (по умолчанию 120 сек)
- Если `fast_io_fail_tmo` > `replacement_timeout`, ядро iSCSI может пометить устройство как failed раньше multipath

**Рекомендации по сценариям:**

| Сценарий | fast_io_fail_tmo | dev_loss_tmo | no_path_retry |
| :--- | :--- | :--- | :--- |
| **Базы данных (OLTP)** | 5 сек | 60 сек | fail |
| **Файловые серверы** | 10 сек | 120 сек | fail |
| **Batch-задачи** | 15 сек | 300 сек | queue |
| **Нестабильная сеть** | 30 сек | 300 сек | queue |

### 3. Конфигурация для популярных СХД

#### Dell EMC Unity / PowerStore

```ini
devices {
    device {
        vendor "DELL"
        product "Unity"
        path_grouping_policy "group_by_prio"
        path_selector "round-robin 0"
        path_checker tur
        prio alua
        failback immediate
        no_path_retry fail
        fast_io_fail_tmo 15
        dev_loss_tmo 60
    }
}
```

#### NetApp ONTAP

```ini
devices {
    device {
        vendor "NETAPP"
        product "LUN"
        path_grouping_policy "group_by_prio"
        path_selector "service-time 0"
        path_checker tur
        prio alua
        failback immediate
        no_path_retry 12
        fast_io_fail_tmo 10
        dev_loss_tmo 60
    }
}
```

#### Pure Storage

```ini
devices {
    device {
        vendor "PURE"
        product "FlashArray"
        path_grouping_policy "group_by_prio"
        path_checker tur
        fast_io_fail_tmo 10
        dev_loss_tmo 60
    }
}
```

### 4. Интеграция с LVM

Чтобы LVM не пытался использовать базовые SCSI-устройства, создавая дубликаты PV, необходимо настроить фильтр в `/etc/lvm/lvm.conf`:

```ini
devices {
    # Разрешаем только multipath-устройства, игнорируем базовые sdX
    filter = [ "a|/dev/mapper/mpath.*|", "r|/dev/sd.*|", "r|/dev/dm-.*|" ]
}
```

После изменения обновите initramfs: `sudo update-initramfs -u`.

#### Расширение multipath-устройства и VG/LV

```bash
# 1. Увеличить LUN на стороне СХД
# 2. Обновить multipath:
sudo multipath -r

# 3. Обновить размер в ядре (для каждого базового устройства):
echo 1 | sudo tee /sys/class/block/sdb/device/rescan
echo 1 | sudo tee /sys/class/block/sdc/device/rescan

# 4. Расширить PV и LV:
sudo pvresize /dev/mapper/mpatha
sudo lvextend -l +100%FREE /dev/vg_data/lv_data

# 5. Расширить ФС:
sudo resize2fs /dev/vg_data/lv_data       # ext4
sudo xfs_growfs /mnt/data                  # XFS
```

#### Влияние multipath на LVM-снапшоты

Снапшоты создаются на уровне LV и не зависят от multipath. Однако при восстановлении снапшота multipath должен быть здоров. Рекомендация: создавать снапшоты только при всех путях активных.

### 5. Конфигурация initramfs для Multipath

Для корневого устройства или критических томов multipath должен быть доступен уже в initramfs.

```bash
# Debian/Ubuntu — добавить multipath в initramfs:
echo 'BOOT=local' | sudo tee /etc/initramfs-tools/conf.d/multipath
sudo update-initramfs -u

# RHEL/Rocky — dracut:
sudo dracut --force --add multipath

# Или permanent:
echo 'hostonly+="multipath "' | sudo tee /etc/dracut.conf.d/multipath.conf
sudo dracut --force

# Проверка наличия multipath в initramfs:
lsinitramfs /boot/initrd.img-$(uname -r) | grep multipath   # Debian/Ubuntu
lsinitrd /boot/initramfs-$(uname -r) | grep multipath       # RHEL
```

### 6. Правила udev для multipath-устройств

```bash
# /etc/udev/rules.d/99-multipath-permissions.rules

# Установка прав доступа и группы для multipath-устройств
ACTION=="add|change", KERNEL=="mapper/mpath*", MODE="0660", GROUP="disk"

# Создание стабильных симлинков по WWID
ACTION=="add|change", ENV{DM_NAME}=="mpath*", SYMLINK+="iscsi/mpath-%E{DM_NAME}"

# Отключение I/O планировщика для dm-устройств (performance)
ACTION=="add|change", KERNEL=="dm-*", ATTR{queue/scheduler}="none"
```

```bash
# Применение правил udev
sudo udevadm control --reload-rules
sudo udevadm trigger
```

## Эксплуатация и диагностика

### Проверка топологии устройств

```bash
sudo multipath -ll
```

**Пример вывода (ALUA):**
```text
mpatha (36001405...) dm-0 LIO-ORG,disk1
size=50G features='1 queue_if_no_path' hwhandler='1 alua' wp=rw
|-+- policy='service-time 0' prio=50 status=active [Оптимальная группа]
| `- 1:0:0:1 sdb 8:16 active ready running
`-+- policy='service-time 0' prio=10 status=enabled [Резервная группа]
  `- 2:0:0:1 sdc 8:32 active ready running
```

### Базовые команды управления

| Задача | Команда |
| :--- | :--- |
| Обновить конфигурацию без перезагрузки | `sudo multipath -r` |
| Просмотр всех WWID в системе | `sudo multipath -v3 \| grep WWID` |
| Очистка неиспользуемых mpath-устройств | `sudo multipath -F` |
| Мониторинг логов в реальном времени | `sudo journalctl -u multipathd -f` |

### Расширенные команды multipathd

| Задача | Команда |
| :--- | :--- |
| Интерактивная консоль | `sudo multipathd` |
| Просмотр всех путей с форматированием | `multipathd show paths format "%d %t %T %p %s %z"` |
| Просмотр всех мапов | `multipathd show maps` |
| Просмотр конкретного мапа | `multipathd show map mpatha` |
| Принудительный failover | `multipathd failover mpatha` |
| Переключение path group | `multipathd pathGroupSwitching mpatha 0` |
| Включение пути | `multipathd enable path sdb` |
| Отключение пути | `multipathd disable path sdb` |
| Принудительное обновление | `multipathd reconfigure` |
| Верbose-логирование | `multipathd -vvv` |
| Просмотр состояния device-mapper | `dmsetup status`, `dmsetup table`, `dmsetup info` |

**Пример интерактивной сессии:**
```bash
$ sudo multipathd
multipathd> show paths format "%d %t %p %s"
# dev target prios device
# sdb 1:0:0:1   50 sdb
# sdc 2:0:0:1   10 sdc

multipathd> failover mpatha
multipathd> show map mpatha
```

## Тюнинг

### Queue Depth

Queue Depth (глубина очереди) определяет максимальное количество одновременных I/O-запросов к устройству. Влияет на производительность и стабильность:

```bash
# Просмотр текущей глубины очереди
cat /sys/block/mapper/mpatha/queue/nr_requests
# → 128 (по умолчанию)

# Увеличение для SSD/NVMe (рекомендуется 256)
echo 256 | sudo tee /sys/block/mapper/mpatha/queue/nr_requests

# Для HDD рекомендуется 64-128
```

**Рекомендации:**
- **SSD/NVMe:** 128-256 (высокий параллелизм)
- **HDD:** 32-64 (ограниченный параллелизм из-за механики)
- **Эффект увеличения:** Более высокий throughput при стабильной сети, но рост latency при переполнении очереди

### Настройка Failback

Failback — процесс возврата на основной путь после его восстановления:

```ini
# /etc/multipath.conf — устройство LIO
devices {
    device {
        vendor "LIO-ORG"
        product ".*"
        # Немедленный возврат на основной путь (рекомендуется для ALUA)
        failback immediate
        # Или плавный возврат (в секундах)
        # failback 30
    }
}
```

**Поведение failback:**
- `immediate`: Немедленный switch на основной путь (путь с наивысшим приоритетом). Рекомендуется для ALUA.
- Число (секунды): Плавное переключение через указанное время.
- `manual`: Только по команде `multipathd pathGroupSwitching <wwid> <groupnum>`.

## Диагностика проблем

### Типичные проблемы Multipath

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `multipathd: map in kernel ... does not have a multipath handler` | Модуль `dm_multipath` не загружен | `sudo modprobe dm_multipath` + `sudo update-initramfs -u` |
| `WWID different on paths` | Разные Serial/WWN на таргете | Проверить `targetcli` → LUN → напрямую |
| `path priority callout failed` | Нет приоритетного планировщика (ALUA) | Установить `prio "alua"` в конфигурации |
| Все пути в `faulty` | Сетевая проблема или target down | Проверить `ping`, `nc -zv <IP> 3260`, логи `dmesg` |
| `queue_if_no_path` сработал | Все пути временно недоступны | Ожидание восстановления (timeout настраивается) |
| `fast_io_fail_tmo` сработал | Путь нестабильный,requent переключения | Увеличить `fast_io_fail_tmo` или проверить сеть |
| Устройство исчезло после перезагрузки | multipath не в initramfs | Настроить initramfs (раздел 5) |
| `permission denied` при `multipath -ll` | Нет прав root | Использовать `sudo` |
| PV/LVM конфликт | LVM видит базовые sdX устройства | Проверить `filter` в `lvm.conf` |

### Проблема несоответствия WWID

Если `multipathd` видит пути как разные устройства, хотя это один диск, проверьте:

1.  **ID устройства на таргете**: Убедитесь, что LUN экспортирован с одинаковым Serial/WWN на всех порталах.
2.  **Записи в blacklist**: Проверьте, не попал ли WWID в список исключений.
3.  **Ручное задание WWID**: Если hardware-идентификатор не считываются корректно:

```bash
# В /etc/multipath.conf
devices {
    device {
        vendor "LIO-ORG"
        product ".*"
        # Ручное задание WWID (если auto-detect не работает)
        uid "36001405deadbeef0000000000000001"
    }
}
```

### Отладка Multipath (Debug)

```bash
# Запуск multipathd с максимальной детализацией:
sudo multipathd -vvv

# Включение отладки через syslog:
# /etc/rsyslog.d/multipath.conf
# local0.debug    /var/log/multipathd-debug.log

# Просмотр debug-вывода multipath:
sudo multipath -ll -v3
# → Показывает: WWID, path grouping, priorities, checker status

# Анализ логов multipathd:
sudo journalctl -u multipathd --since "1 hour ago" | grep -iE "path|fail|retry|switch|group"

# Проверка состояния device-mapper:
sudo dmsetup status
sudo dmsetup table
sudo dmsetup info
```

### Проверка монтирования

При записи в `/etc/fstab` обязательно указывайте опцию `_netdev`, чтобы предотвратить зависание системы при загрузке, если сетевое хранилище недоступно.

```text
/dev/mapper/mpatha1  /mnt/data  ext4  defaults,_netdev,nofail  0  2
```

### Диагностика через sysfs

```bash
# Просмотр всех путей устройства
ls -la /sys/block/mapper/mpatha/slaves/
# → sdb  sdc  (два физических пути)

# Состояние каждого пути
cat /sys/block/mapper/mpatha/slaves/sdb/stat
# → Кол-во операций, времени и т.д.

# Информация о multipath-группе
cat /sys/block/mapper/mpatha/dm/name
# → mpatha
```

### Скрипт проверки состояния Multipath

```bash
#!/bin/bash
# /usr/local/bin/check_multipath.sh
# Рекомендуется запускать через cron каждые 5 минут

CRITICAL=0
WARNING=0

# Проверка демона
if ! systemctl is-active --quiet multipathd; then
    echo "CRITICAL: multipathd is not running"
    exit 2
fi

# Проверка faulty путей
FAULTY=$(multipath -ll 2>/dev/null | grep -c "faulty")
if [ "$FAULTY" -gt 0 ]; then
    echo "CRITICAL: $FAULTY faulty path(s) detected"
    multipath -ll | grep faulty
    CRITICAL=1
fi

# Проверка путей в состоянии blocked
BLOCKED=$(multipath -ll 2>/dev/null | grep -c "blocked")
if [ "$BLOCKED" -gt 0 ]; then
    echo "WARNING: $BLOCKED blocked path(s)"
    WARNING=1
fi

# Проверка что все mpath-устройства имеют >0 путей
for map in $(multipath -ll 2>/dev/null | grep "^mpath" | awk '{print $1}'); do
    PATHS=$(multipath -ll "$map" 2>/dev/null | grep -c "active ready running")
    if [ "$PATHS" -eq 0 ]; then
        echo "CRITICAL: mpath device $map has NO active paths"
        CRITICAL=1
    elif [ "$PATHS" -eq 1 ]; then
        echo "WARNING: mpath device $map has only 1 active path (no redundancy)"
        WARNING=1
    fi
done

if [ "$CRITICAL" -eq 1 ]; then exit 2
elif [ "$WARNING" -eq 1 ]; then exit 1
else echo "OK: All multipath devices healthy"; exit 0
fi
```

### Экспорт метрик Multipath для Prometheus

```bash
#!/bin/bash
# /usr/local/bin/multipath_metrics.sh
# Экспорт метрик для node_exporter textfile collector

PROM_DIR="/var/lib/node_exporter/textfile_collector"
OUT="$PROM_DIR/multipath.prom"

# Количество multipath-устройств
MAPS=$(multipath -ll 2>/dev/null | grep -c "^mpath")
echo "multipath_maps_total ${MAPS:-0}" > "$OUT.tmp"

# Количество faulty путей
FAULTY=$(multipath -ll 2>/dev/null | grep -c "faulty")
echo "multipath_faulty_paths_total ${FAULTY:-0}" >> "$OUT.tmp"

# Количество активных путей на каждое устройство
while IFS= read -r line; do
    MAP=$(echo "$line" | awk '{print $1}')
    ACTIVE=$(multipath -ll "$MAP" 2>/dev/null | grep -c "active ready running")
    TOTAL=$(multipath -ll "$MAP" 2>/dev/null | grep -c "sd[a-z]")
    echo "multipath_active_paths{device=\"$MAP\"} $ACTIVE" >> "$OUT.tmp"
    echo "multipath_total_paths{device=\"$MAP\"} $TOTAL" >> "$OUT.tmp"
done < <(multipath -ll 2>/dev/null | grep "^mpath")

mv "$OUT.tmp" "$OUT"
```

**Пример алерта Prometheus:**
```yaml
- alert: MultipathDegraded
  expr: multipath_active_paths < multipath_total_paths
  for: 1m
  labels:
    severity: warning
  annotations:
    summary: "Multipath degraded on {{ $labels.instance }}"
    description: "{{ $labels.device }} has {{ $value }} active paths"
```

## См. также

- **[Настройка iSCSI Initiator](./iscsi_initiator_setup.md)** — подготовка сессий и iface.
- **[Диагностика iSCSI](./iscsi_diagnostics.md)** — общие инструменты отладки стека.
- **[Оптимизация производительности iSCSI](./iscsi_performance.md)** — тюнинг сетевых параметров.
- **[Безопасность iSCSI](./iscsi_security.md)** — изоляция SAN-сегмента и firewall.
- **[Мониторинг iSCSI](./iscsi_monitoring.md)** — мониторинг состояния путей.
- **[Управление томами LVM](../../FileSystems/LVM/operations/lvm_disk_replacement.md)** — работа с VG поверх MPIO.
