# iSCSI: Настройка инициатора (Клиент)

Руководство по установке, идентификации и подключению клиентской части iSCSI (инициатора) в ОС Linux.

## Определения и сокращения

| Термин | Описание |
| :--- | :--- |
| **Initiator (Инициатор)** | Клиентское ПО или аппаратный адаптер, инициирующий SCSI-команды к удаленным хранилищам. |
| **iscsid** | Фоновый демон, управляющий сессиями, восстановлением соединений и обработкой событий протокола. |
| **iscsiadm** | Утилита командной строки для управления базами данных (discovery, node) и активными сессиями. |
| **Node (Узел)** | Запись в локальной БД инициатора, содержащая параметры подключения к конкретному таргету. |
| **iface (Interface)** | Объект в базе данных iSCSI, позволяющий привязать сессию к конкретной сетевой карте (NIC) или IP-адресу инициатора. |
| **Discovery** | Процесс опроса портала таргета для получения списка доступных IQN. |

## Основные концепции

### Стек open-iscsi

Инициатор в Linux (стек **open-iscsi**) представляет удаленные ресурсы (LUN) как стандартные локальные блочные устройства (например, `/dev/sdb`). Управление осуществляется через базы данных, хранящиеся в `/etc/iscsi/nodes/` и `/etc/iscsi/send_targets/`.

### Архитектура iface

Для сред с несколькими сетевыми интерфейсами (Multipath) недостаточно просто выполнить Discovery. Чтобы заставить iSCSI использовать конкретные физические пути, необходимо создать объекты `iface`, которые связывают драйвер iSCSI с конкретным сетевым интерфейсом хоста. Это предотвращает ситуацию, когда все сессии устанавливаются через один и тот же интерфейс по умолчанию.

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

Если таргет требует авторизацию, обновите параметры узла **до** выполнения входа (Login).

```bash
# Односторонний CHAP
sudo iscsiadm -m node -T <IQN> -p <IP> -o update -n node.session.auth.authmethod -v CHAP
sudo iscsiadm -m node -T <IQN> -p <IP> -o update -n node.session.auth.username -v <USER>
sudo iscsiadm -m node -T <IQN> -p <IP> -o update -n node.session.auth.password -v <PASS>
```

## Эксплуатация и персистентность

### Тюнинг параметров сессии (`iscsid.conf`)

Для повышения стабильности в нестабильных сетях отредактируйте `/etc/iscsi/iscsid.conf`:

- **node.session.timeo.replacement_timeout**: Время (в сек.), которое ядро ждет перед тем, как признать устройство "мертвым" и перевести ФС в RO. Рекомендуется 120.
- **node.conn[0].timeo.noop_out_interval**: Интервал проверки активности соединения (Keepalive).
- **node.conn[0].timeo.noop_out_timeout**: Таймаут ответа на проверку.

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

## Дополнительная информация

### Взаимодействие с LVM
Во избежание конфликтов и дублирования PV, настройте фильтры в `lvm.conf`. Подробнее см. в документе **[Настройка Multipath I/O](./iscsi_multipath.md#интеграция-с-lvm)**.

### Управление базой данных узлов

| Задача | Команда |
| :--- | :--- |
| Список активных сессий | `iscsiadm -m session -P 3` |
| Просмотр параметров узла | `iscsiadm -m node -T <IQN> -p <IP>` |
| Удаление узла из базы | `iscsiadm -m node -T <IQN> -p <IP> -o delete` |
| Сканирование новых LUN | `iscsiadm -m session --rescan` |

### См. также

- **[Диагностика iSCSI](./iscsi_diagnostics.md)** — разбор ошибок и мониторинг.
- **[Основные концепции iSCSI](./iscsi_concepts.md)** — теория протокола.
- **[Настройка iSCSI Target](./iscsi_target_setup.md)** — конфигурация сервера.
- **[Оптимизация производительности iSCSI](./iscsi_performance.md)** — тюнинг параметров.

