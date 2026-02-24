# iSCSI (Internet Small Computer System Interface)

**iSCSI (Internet Small Computer System Interface)** — протокол блочного доступа, инкапсулирующий команды SCSI в TCP/IP.

Позволяет подключать удалённые блочные устройства по IP-сети так, будто это локальный диск.

## Архитектурная модель iSCSI

- **Target** — сервер, предоставляющий блочные устройства (LUN).
- **Initiator** — клиент, подключающийся к таргету и получающий доступ к этим устройствам.

## Установка и настройка iSCSI Target

### Установка (Debian/Ubuntu)

```bash
sudo apt install tgt
```

Конфигурация — файл `/etc/tgt/conf.d/debian.conf`. Пример создания LUN:

```ini
# /etc/tgt/conf.d/iscsi-target.conf
<target iqn.2026-02.example:storage.lun1>
    backing-store /dev/sdb           # или путь к файлу-образу
    initiator-address 192.168.1.0/24 # разрешённые инициаторы
</target>
```

После изменения конфигурации перезапустите службу:

```bash
sudo systemctl restart tgt
```

## Установка и основные команды для iSCSI Initiator

### Установка (Debian/Ubuntu)

```bash
sudo apt install open-iscsi
```

### Основные команды

- **Обнаружение таргетов:**

  ```bash
  sudo iscsiadm -m discovery -t sendtargets -p <IP_таргета>
  ```

- **Подключение к таргету:**

  ```bash
  sudo iscsiadm -m node -T <IQN> -p <IP> --login
  ```

- **Просмотр активных сессий:**

  ```bash
  sudo iscsiadm -m session
  ```

- **Отключение:**

  ```bash
  sudo iscsiadm -m node -T <IQN> -p <IP> --logout
  ```

## Использование iSCSI-устройства (разметка, форматирование, монтирование, постоянство)

После успешного подключения (`--login`) iSCSI-таска он становится доступным как блочное устройство.

1. **Определение нового устройства:**
    Используйте `lsblk` или `fdisk -l` для обнаружения нового диска. Оно может появиться как `/dev/sdX` (например, `/dev/sdb`).

    ```bash
    lsblk
    ```

2. **Создание раздела (опционально, если не нужен весь диск):**

    ```bash
    sudo fdisk /dev/sdb
    # N (новый раздел), P (основной), 1 (номер раздела), Enter (начальный сектор), Enter (конечный сектор), W (записать изменения)
    ```

3. **Форматирование раздела:**

    ```bash
    sudo mkfs.ext4 /dev/sdb1 # или /dev/sdb, если без разделов
    ```

4. **Создание точки монтирования и монтирование:**

    ```bash
    sudo mkdir /mnt/iscsi_data
    sudo mount /dev/sdb1 /mnt/iscsi_iscsi_data
    ```

5. **Проверка монтирования:**

    ```bash
    df -h /mnt/iscsi_data
    ```

6. **Настройка постоянного монтирования (fstab):**
    Получите UUID устройства для надежного монтирования:

    ```bash
    sudo blkid /dev/sdb1
    ```

    Добавьте строку в `/etc/fstab`. Важно использовать опцию `_netdev`, чтобы система монтировала раздел только после поднятия сети.

    ```ini
    UUID=<ваш_UUID> /mnt/iscsi_data ext4 _netdev,defaults 0 0
    ```

    Проверьте конфигурацию `/etc/fstab`:

    ```bash
    sudo mount -a
    ```

### CHAP (Challenge-Handshake Authentication Protocol)

CHAP — протокол аутентификации, используемый для безопасного подключения iSCSI-инициаторов к таргетам. Обеспечивает взаимную аутентификацию (target-initiator и initiator-target) с использованием общего секрета.

#### Настройка на iSCSI Target (tgt)

Добавьте параметры `incominguser` и `outgoinguser` в секцию `<target>` файла `/etc/tgt/conf.d/iscsi-target.conf`:

```ini
<target iqn.2026-02.example:storage.lun1>
    backing-store /dev/sdb
    initiator-address 192.168.1.0/24
    # Аутентификация инициатора на таргете
    incominguser myuser mysecretpassword
    # Аутентификация таргета на инициаторе (взаимная CHAP)
    outgoinguser targetuser targetsecretpassword
</target>
```

Перезапустите службу `tgt` после изменений.

#### Настройка на iSCSI Initiator (open-iscsi)

Отредактируйте файл `/etc/iscsi/iscsid.conf`. Установите `node.session.auth.authmethod = CHAP` и укажите данные для `CHAP` аутентификации.

**Пример для односторонней аутентификации (инициатор -> таргет):**

```ini
node.session.auth.authmethod = CHAP
node.session.auth.username = myuser
node.session.auth.password = mysecretpassword
```

**Пример для взаимной аутентификации (инициатор -> таргет И таргет -> инициатор):**

```ini
node.session.auth.authmethod = CHAP
node.session.auth.username = myuser
node.session.auth.password = mysecretpassword
node.session.auth.username_in = targetuser
node.session.auth.password_in = targetsecretpassword
```

После изменений необходимо обновить базу данных `open-iscsi` для конкретного таргета и переподключиться.

```bash
sudo iscsiadm -m node -T <IQN> -p <IP_таргета> -o update -n node.session.auth.authmethod -v CHAP
sudo iscsiadm -m node -T <IQN> -p <IP_таргета> -o update -n node.session.auth.username -v myuser
sudo iscsiadm -m node -T <IQN> -p <IP_таргета> -o update -n node.session.auth.password -v mysecretpassword
# Для взаимной CHAP:
sudo iscsiadm -m node -T <IQN> -p <IP_таргета> -o update -n node.session.auth.username_in -v targetuser
sudo iscsiadm -m node -T <IQN> -p <IP_таргета> -o update -n node.session.auth.password_in -v targetsecretpassword

sudo iscsiadm -m node -T <IQN> -p <IP_таргета> --login
```

## Заключение

iSCSI превращает IP-сеть в гибкое хранилище уровня SAN — бесплатная альтернатива Fibre Channel для виртуализации, кластеров и бэкапов. Основные реализации: `open-iscsi` (инициатор) и `tgt` или `LIO` (таргет).
