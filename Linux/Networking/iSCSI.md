# iSCSI (Internet Small Computer System Interface)

**iSCSI (Internet Small Computer System Interface)** — протокол блочного доступа, инкапсулирующий команды SCSI в TCP/IP.

Позволяет подключать удалённые блочные устройства по IP-сети так, будто это локальный диск.

## Определения

* **Target** — сервер, предоставляющий блочные устройства (LUN).
* **Initiator** — клиент, подключающийся к таргету и получающий доступ к этим устройствам.
* **LUN (Logical Unit Number)** — логический том, предоставляемый Target.
* **IQN (iSCSI Qualified Name)** — уникальное имя таргета/инициатора в формате `iqn.YYYY-MM.com.example:storage`.
* **CHAP (Challenge-Handshake Authentication Protocol)** — протокол аутентификации для безопасного подключения.

## Архитектурная модель iSCSI

```
┌─────────────────┐      IP-сеть      ┌─────────────────┐
│   Initiator     │◄─────────────────►│     Target      │
│   (Клиент)      │    TCP/IP:3260    │   (Сервер)      │
│  open-iscsi     │                   │  tgt / LIO      │
└─────────────────┘                   └─────────────────┘
        │                                     │
        ▼                                     ▼
  /dev/sdb                              /dev/sdb (физический)
  (виртуальный диск)                    (или файл-образ)
```

### Реализации

| Компонент | Реализация | Статус | Примечание |
| :--- | :--- | :--- | :--- |
| **Target** | `tgt` | Стабильно | Простая настройка, рекомендуется для большинства случаев |
| **Target** | `LIO` (targetcli) | Стабильно | Встроен в ядро, сложнее в настройке |
| **Initiator** | `open-iscsi` | Стандарт | Используется во всех дистрибутивах |
| **Initiator** | Встроенный в ядро | Альтернатива | Для специфичных сценариев |

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

**Важно:** iSCSI использует TCP-порт **3260**. Убедитесь, что он открыт в firewall:

```bash
sudo ufw allow 3260/tcp
# или для iptables
sudo iptables -A INPUT -p tcp --dport 3260 -j ACCEPT
```

После изменения конфигурации перезапустите службу:

```bash
sudo systemctl restart tgt
sudo systemctl enable tgt  # для автозагрузки при старте
```

**Проверка статуса Target:**

```bash
# Показать все таргеты
sudo tgtadm --lld iscsi --mode target --op show

# Проверить статус службы
systemctl status tgt
```

### Альтернатива: LIO (targetcli)

`LIO` — встроенная в ядро Linux реализация iSCSI Target. Настройка через `targetcli`:

```bash
sudo apt install targetcli-fb
sudo targetcli
```
```

## Установка и основные команды для iSCSI Initiator

### Установка (Debian/Ubuntu)

```bash
sudo apt install open-iscsi
sudo systemctl enable open-iscsi
sudo systemctl start open-iscsi
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

- **Удаление записи о таргете (после logout):**

  ```bash
  sudo iscsiadm -m node -T <IQN> -p <IP> -o delete
  ```

- **Автоматический вход при загрузке:**

  ```bash
  # После успешного login установите автоматический вход
  sudo iscsiadm -m node -T <IQN> -p <IP> -o update -n node.startup -v automatic
  ```

## Использование iSCSI-устройства (разметка, форматирование, монтирование, постоянство)

После успешного подключения (`--login`) iSCSI-таска он становится доступным как блочное устройство.

### 1. Определение нового устройства

Используйте `lsblk` или `fdisk -l` для обнаружения нового диска. Оно может появиться как `/dev/sdX` (например, `/dev/sdb`).

```bash
lsblk
# или
sudo fdisk -l
```

**Проверка сессий iSCSI:**

```bash
# Показать активные сессии с деталями
sudo iscsiadm -m session -P 3
```

### 2. Создание раздела (опционально, если не нужен весь диск)

```bash
sudo fdisk /dev/sdb
# N (новый раздел), P (основной), 1 (номер раздела), Enter (начальный сектор), Enter (конечный сектор), W (записать изменения)
```

### 3. Форматирование раздела

```bash
sudo mkfs.ext4 /dev/sdb1 # или /dev/sdb, если без разделов
```

### 4. Создание точки монтирования и монтирование

```bash
sudo mkdir /mnt/iscsi_data
sudo mount /dev/sdb1 /mnt/iscsi_data
```

### 5. Проверка монтирования

```bash
df -h /mnt/iscsi_data
```

### 6. Настройка постоянного монтирования (fstab)

Получите UUID устройства для надежного монтирования:

```bash
sudo blkid /dev/sdb1
```

Добавьте строку в `/etc/fstab`. **Важно использовать опцию `_netdev`**, чтобы система монтировала раздел только после поднятия сети.

```ini
UUID=<ваш_UUID> /mnt/iscsi_data ext4 _netdev,defaults 0 0
```

Проверьте конфигурацию `/etc/fstab`:

```bash
sudo mount -a
```

**Опции монтирования для iSCSI:**

| Опция | Описание |
| :--- | :--- |
| `_netdev` | Устройство требует сети (обязательно для iSCSI) |
| `nofail` | Не прерывать загрузку, если устройство недоступно |
| `defaults` | Стандартные опции (rw, suid, dev, exec, auto, nouser, async) |
| `noatime` | Не обновлять время доступа (для производительности) |

**Пример полной строки fstab:**

```ini
UUID=abc123 /mnt/iscsi_data ext4 _netdev,nofail,noatime 0 2
```

### Диагностика проблем Initiator

```bash
# Проверить статус службы open-iscsi
systemctl status open-iscsi

# Просмотреть логи
journalctl -u open-iscsi -f

# Принудительное переподключение
sudo iscsiadm -m node --logoutall=ALL
sudo iscsiadm -m node --loginall=ALL
```

### CHAP (Challenge-Handshake Authentication Protocol)

CHAP — протокол аутентификации, используемый для безопасного подключения iSCSI-инициаторов к таргетам. Обеспечивает взаимную аутентификацию (target-initiator и initiator-target) с использованием общего секрета.

**Важно:** CHAP защищает от несанкционированного доступа, но не шифрует трафик. Для шифрования используйте IPsec или выделенную сеть. Для изоляции iSCSI-трафика в отдельной сети рассмотрите **[Policy-Based Routing](./linux_policy_based_routing.md)**.

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

**Рекомендации по безопасности CHAP:**

| Требование | Описание |
| :--- | :--- |
| **Длина пароля** | Минимум 12 символов |
| **Сложность** | Буквы, цифры, специальные символы |
| **Уникальность** | Разные пароли для разных таргетов |
| **Хранение** | Файл `/etc/iscsi/iscsid.conf` должен быть доступен только root (`chmod 600`) |

## Заключение

iSCSI превращает IP-сеть в гибкое хранилище уровня SAN — бесплатная альтернатива Fibre Channel для виртуализации, кластеров и бэкапов. Основные реализации: `open-iscsi` (инициатор) и `tgt` или `LIO` (таргет).

## Типичные проблемы и решения

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Connection refused:3260** | Target не запущен или firewall блокирует | `systemctl status tgt`, проверить порт 3260 |
| **Authentication failed** | Неверный CHAP пароль | Проверить `iscsid.conf` на обоих концах |
| **No portals found** | Неправильный IP таргета | Проверить `iscsiadm -m discovery` |
| **Device not appearing** | Драйверы или проблема с ядром | `dmesg \| grep -i iscsi`, `lsblk` |
| **Mount fails after reboot** | Нет опции `_netdev` в fstab | Добавить `_netdev,nofail` в fstab |
| **Session timeout** | Проблемы с сетью | Проверить стабильность сети, MTU |

## Связанные заметки

* **[LVM](../Storage/lvm.md)** — управление логическими томами
* **[Mount](../SystemAdministration/filesystems/mount.md)** — монтирование файловых систем
* **[Network Diagnostics](./network_diagnostics_tools.md)** — диагностика сети
* **[Firewall](../Settings/linux_firewall_management.md)** — настройка firewall
