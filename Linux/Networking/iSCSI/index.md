# iSCSI (Internet Small Computer System Interface)

Индекс документов по архитектуре, настройке и эксплуатации протокола iSCSI в ОС Linux.

## Определение

**iSCSI (Internet Small Computer System Interface)** — сетевой протокол блочного доступа, позволяющий передавать команды SCSI через стандартные IP-сети (TCP/IP). Технология позволяет объединять удаленные дисковые ресурсы в распределенную сеть хранения данных (SAN), где удалённые накопители (LUN) подключаются к хостам и функционируют как локальные блочные устройства. iSCSI является экономичной альтернативой Fibre Channel, так как не требует специализированного оборудования (HBA-карт, коммутаторов FC) и работает на стандартной инфраструктуре Ethernet.

**Ключевые характеристики протокола:**
- **Транспорт:** TCP/IP, порт 3260 (по умолчанию)
- **Контрольная сумма:** CRC32C на уровне PDU (в дополнение к TCP/ETH checksums)
- **Аутентификация:** CHAP (односторонний/взаимный), ACL по IQN
- **Реализации в Linux:** Target — LIO (ядерный) / tgt (legacy); Initiator — open-iscsi

## Быстрая справка

### Часто используемые команды

| Задача | Команда |
| :--- | :--- |
| **Discovery (обнаружение таргетов)** | `sudo iscsiadm -m discovery -t sendtargets -p <TARGET_IP>` |
| **Login (подключение)** | `sudo iscsiadm -m node -T <TARGET_IQN> -p <IP> --login` |
| **Login ко всем** | `sudo iscsiadm -m node --loginall=all` |
| **Logout (отключение)** | `sudo iscsiadm -m node -T <TARGET_IQN> -p <IP> --logout` |
| **Статус сессий** | `sudo iscsiadm -m session` |
| **Детальный статус** | `sudo iscsiadm -m session -P 3` |
| **Rescan (обнаружение новых LUN)** | `sudo iscsiadm -m session --rescan` |
| **Персистентность сессии** | `sudo iscsiadm -m node -T <IQN> -o update -n node.startup -v automatic` |
| **Настройка CHAP** | `sudo iscsiadm -m node -T <IQN> -p <IP> -o update -n node.session.auth.authmethod -v CHAP` |
| **Просмотр в dmesg** | `sudo dmesg \| grep -iE "iscsi\|scsi"` |

### Порты и протоколы

| Компонент | Протокол | Порт | Назначение |
| :--- | :--- | :--- | :--- |
| iSCSI Target | TCP | 3260 | Основной порт входящих подключений |
| iSCSI Discovery | TCP | 3260 | Запрос SendTargets |
| Multipath | — | — | Управление путями на уровне ядра |
| LIO configfs | — | `/sys/kernel/config/target/` | Конфигурация ядерного таргета |

### Структура IQN (iSCSI Qualified Name)

```
iqn.YYYY-MM.domain.reversed:optional_identifier
```

Примеры:
- Таргет: `iqn.2026-07.com.example:storage.target01`
- Инициатор: `iqn.2026-07.com.example:client.node01`

Допустимые альтернативы: `eui.` (EUI-64), `naa.` (NAA, для FC-стиля).

## Основные концепции

Теоретический фундамент и терминология протокола:

- **[Основные концепции iSCSI](./iscsi_concepts.md)** — архитектура Target/Initiator, структура PDU, фазы сессии (Discovery → Login → Full Feature Phase), уровни восстановления ошибок (ERL 0/1/2), сравнение реализаций (LIO vs tgt).
- **Терминология**: Понимание порталов (Portals), групп порталов (TPG), сессий и backing stores.
- **Сравнение с альтернативами**: Позиционирование iSCSI относительно NVMe-oF, Fibre Channel и NFS. iSCSI — баланс между производительностью и простотой развёртывания; NVMe-oF — для экстремальных нагрузок на Flash; FC — максимальная стабильность, но дорогостоящая инфраструктура.

## Практические сценарии развертывания

Пошаговые руководства по настройке компонентов стека:

- **[Настройка iSCSI Target (Сервер)](./iscsi_target_setup.md)** — развертывание серверной части с использованием стека **LIO** (`targetcli`): создание backstores (block, fileio), LUN, TPG, ACL. Legacy-решение `tgt` (scsi-target-utils) для старых систем.
- **[Настройка iSCSI Initiator (Клиент)](./iscsi_initiator_setup.md)** — использование `open-iscsi` (`iscsiadm`): установка, настройка IQN, Discovery, Login, привязка к NIC через `iface`, автоматическое подключение при загрузке.
- **[Настройка Multipath I/O](./iscsi_multipath.md)** — обеспечение высокой доступности (HA) и агрегации пропускной способности через несколько сетевых путей (MPIO): `multipathd`, ALUA, `find_multipaths`, интеграция с LVM.

## Безопасность и аутентификация

Защита iSCSI-трафика и контроль доступа к ресурсам:

- **[Безопасность iSCSI](./iscsi_security.md)** — аутентификация CHAP (односторонняя и взаимная), списки контроля доступа (ACL) по IQN, сетевая изоляция (VLAN, firewall), шифрование трафика (IPsec), харденинг.

**Краткое описание:**
- **CHAP**: Таргет проверяет инициатор по логину/паролю. Рекомендуется взаимный CHAP (双向), чтобы инициатор также проверял таргет.
- **ACL**: Разрешение доступа только по whitelist IQN на уровне TPG.
- **Сетевая изоляция**: Выделенный VLAN для iSCSI-трафика, firewall rules (порт 3260/tcp), отключение сервисов на целевых хостах.
- **Шифрование**: IPsec (tunnel или transport mode) для защиты данных в транзите. Требует вычислительных ресурсов на обоих концах.

## Оптимизация производительности

Методы повышения пропускной способности и снижения задержек:

- **[Оптимизация производительности iSCSI](./iscsi_performance.md)** — настройка Jumbo Frames (MTU 9000), аппаратных разгрузок (TSO/GRO, отключение LRO), параметров TCP (буферы, BDP), планировщиков I/O (`none` для SSD, `mq-deadline` для HDD), привязка IRQ к NUMA-узлам.
- **[iSER (iSCSI Extensions for RDMA)](./iscsi_performance.md#iser-iscsi-extensions-for-rdma)** — использование RDMA для минимизации задержек (в 3-5 раз) и нагрузки на CPU. Требует RDMA-адаптеров (RoCE/iWARP).

## Мониторинг и диагностика

Обслуживание и решение типовых проблем:

- **[Диагностика iSCSI](./iscsi_diagnostics.md)** — анализ логов `iscsid`, проверка статуса сессий (`iscsiadm -m session -P 3`), анализ TCP-ретрансмиссий (`nstat`), захват трафика (`tcpdump`), решение ошибок авторизации, таймаутов и зависаний.
- **[Мониторинг iSCSI](./iscsi_monitoring.md)** — метрики производительности (IOPS, throughput, latency), настройка Prometheus с `iscsiadm`-экспортерами, алертинг (alerting) на потери путей и ретрансмиссии, анализ `iostat` и `dstat`.

## Резервное копирование и снапшоты

Стратегии обеспечения целостности данных:

- **[Резервное копирование iSCSI](./iscsi_backup.md)** — создание снапшотов на стороне таргета (LVM snapshots, VSS для Windows), консистентность данных (application-consistent vs crash-consistent), интеграция с LVM (`/etc/lvm/lvm.conf` filter), стратегии бэкапа для СУБД поверх iSCSI.

## Эксплуатация и типичные проблемы

- **[Диагностика iSCSI](./iscsi_diagnostics.md)** — разбор ошибок: `login failed due to authorization failure`, `session recovery timed out`, `can not connect to iSCSI portal`, переход ФС в read-only, зависание при shutdown.
- **[Шпаргалка по командам](./iscsi_cheatsheet.md)** — быстрая справка: targetcli, iscsiadm, multipath, диагностика.
- **[Жизненный цикл LUN](./iscsi_lun_lifecycle.md)** — создание, расширение "на лету", миграция, удаление LUN.
- **Edge cases:**
  - **Одновременный доступ нескольких инициаторов к LUN**: Возможен только через [SCSI-3 Persistent Reservations](./iscsi_persistent_reservations.md). Без них — риск повреждения данных.
  - **Rescan после изменения размера LUN**: `iscsiadm -m session --rescan` + `echo 1 > /sys/class/block/sdX/device/rescan` + `resize2fs`/`xfs_growfs`.
  - **Перезагрузка target-сервера**: Инициаторы должны автоматически переподключиться (при `node.startup = automatic`). Проверьте `replacement_timeout`.
  - **Boot from iSCSI**: Загрузка ОС с сетевого LUN (diskless-серверы). Подробности см. в [Настройка Initiator](./iscsi_initiator_setup.md#7-iscsi-boot).

## Интеграция и смежные технологии

Использование iSCSI в различных инфраструктурных слоях:

- **[Управление томами LVM](../../FileSystems/LVM/operations/lvm_disk_replacement.md)** — создание VG и LV поверх сетевых блочных устройств. **Важно**: настроить фильтр `filter = [ "a|/dev/mapper/mpath.*|", "r|/dev/sd.*|" ]` в `/etc/lvm/lvm.conf` для исключения базовых путей.
- **Виртуализация**: Подключение iSCSI в [Proxmox VE](./iscsi_proxmox.md) (плагины `iscsi`, `iscsidirect`, `zfs over iSCSI`, `LVM over iSCSI`) и VMware ESXi. В PVE для многопользовательского доступа поверх iSCSI требуется LVM.
- **[Высокая доступность (HA)](./iscsi_ha_pacemaker.md)** — построение отказоустойчивых кластеров с общим iSCSI-хранилищем: Pacemaker, Corosync, STONITH, DLM.
- **[Кластерные файловые системы](./iscsi_cluster_fs.md)** — GFS2 и OCFS2 для одновременного доступа к iSCSI LUN с нескольких узлов.
- **Kubernetes**: Использование iSCSI для [Persistent Volumes (PV)](../../../Kubernetes/Storage/pv_and_pvc.md) через CSI-драйверы. Тип.accessMode: `ReadWriteOnce` (RWO). При drain-узла detach RWO-томов может занимать 2-5 минут.
- **Сетевая инфраструктура**:
    - **[Policy-Based Routing](../Policy_Based_Routing/index.md)** — изоляция трафика хранения в отдельный VLAN.
    - **[Настройка Firewall](../Settings/tools/firewalld.md)** — открытие порта 3260/tcp и ограничение доступа по IP.
    - **[Диагностика сети](../network_diagnostics_tools.md)** — утилиты для анализа транспортного уровня (ping, traceroute, mtr, tcpdump).

## Сравнение iSCSI с альтернативными протоколами

| Критерий | iSCSI | Fibre Channel | NVMe-oF (TCP) | NFS v4 |
| :--- | :--- | :--- | :--- | :--- |
| **Транспорт** | Ethernet (TCP/IP) | Fibre Channel (proprietary) | Ethernet (TCP/RDMA) | Ethernet (NFS) |
| **Порт по умолч.** | 3260 | 3260 (PP) | 4420 (TCP), RoCE:自发 | 2049 |
| **Блочный/файловый** | Блочный | Блочный | Блочный | Файловый |
| **Задержка** | Средняя (100-500 мкс) | Низкая (1-10 мкс) | Экстремальная (1-50 мкс) | Высокая |
| **Оборудование** | Стандартный Ethernet | HBA + FC-коммутаторы | RDMA-адаптеры (RoCE) | Стандартный Ethernet |
| **Стоимость** | Низкая | Высокая | Средняя-высокая | Низкая |
| **Применение** | SAN для SMB/SME, виртуализация | Enterprise SAN, массивы | Высокопроизводительные БД | Файловые серверы,shares |
| **Безопасность** | CHAP, IPsec | FC-Ports, zoning | IPsec, поддержка TLS | Kerberos, RPCSEC_G |

## См. также

- **[Основные концепции iSCSI](./iscsi_concepts.md)** — теория протокола
- **[Настройка iSCSI Target](./iscsi_target_setup.md)** — серверная часть
- **[Настройка iSCSI Initiator](./iscsi_initiator_setup.md)** — клиентская часть
- **[Настройка Multipath I/O](./iscsi_multipath.md)** — отказоустойчивость
- **[Безопасность iSCSI](./iscsi_security.md)** — защита и аутентификация
- **[Шпаргалка по командам](./iscsi_cheatsheet.md)** — быстрая справка по командам
- **[Жизненный цикл LUN](./iscsi_lun_lifecycle.md)** — управление LUN
- **[SCSI-3 Persistent Reservations](./iscsi_persistent_reservations.md)** — блокировки для кластеров
- **[Кластерные ФС (GFS2/OCFS2)](./iscsi_cluster_fs.md)** — кластерные файловые системы
- **[iSCSI + Pacemaker HA](./iscsi_ha_pacemaker.md)** — высокая доступность
- **[iSCSI + Proxmox VE](./iscsi_proxmox.md)** — интеграция с виртуализацией
