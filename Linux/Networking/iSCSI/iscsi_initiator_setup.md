# iSCSI: Настройка инициатора

Руководство по установке, подключению и эксплуатации iSCSI-инициатора (клиента) в Linux.

## Определение

**iSCSI Initiator (Инициатор)** — это клиентская часть протокола iSCSI, которая инициирует запросы к удаленным дискам (таргетам) и представляет их операционной системе как локальные блочные устройства. В Linux стандартной реализацией является пакет `open-iscsi`.

## Основные концепции

Базовые принципы работы инициатора, структура IQN и архитектура взаимодействия описаны в документе **[Основные концепции iSCSI](./iscsi_concepts.md)**. Ключевые моменты перед настройкой:

- Инициатор должен иметь уникальный **IQN**.
- Для подключения необходим IP-адрес **портала** (таргета) и доступ по порту **3260/tcp**.
- Подключение может требовать аутентификации **CHAP**.

## Практические сценарии

### 1. Установка и базовая настройка

#### Установка (Debian/Ubuntu)

```bash
sudo apt update && sudo apt install open-iscsi -y
sudo systemctl enable --now open-iscsi
```

#### Проверка имени инициатора

Имя хранится в файле `/etc/iscsi/initiatorname.iscsi`. Оно должно быть уникальным в сети.

```bash
cat /etc/iscsi/initiatorname.iscsi
# → InitiatorName=iqn.2026-06.com.example:client01
```

### 2. Подключение к таргету

#### Обнаружение (Discovery)

```bash
sudo iscsiadm -m discovery -t sendtargets -p <IP_таргета>
# → 192.168.1.10:3260,1 iqn.2026-06.com.example:storage.lun1
```

#### Вход в систему (Login)

```bash
sudo iscsiadm -m node -T <IQN_таргета> -p <IP_таргета> --login
```

#### Настройка автозагрузки

Чтобы устройство подключалось автоматически при старте системы:

```bash
sudo iscsiadm -m node -T <IQN_таргета> -p <IP_таргета> -o update -n node.startup -v automatic
```

### 3. Работа с блочным устройством

После логина новое устройство появится в системе (например, как `/dev/sdb`).

#### Идентификация диска

```bash
lsblk
# → sdb      8:16   0   10G  0 disk
```

#### Создание файловой системы и монтирование

```bash
sudo mkfs.ext4 /dev/sdb
sudo mkdir /mnt/iscsi_data
sudo mount /dev/sdb /mnt/iscsi_data
```

#### Постоянное монтирование (/etc/fstab)

**Критически важно** использовать опцию `_netdev`, чтобы система дождалась поднятия сети перед попыткой монтирования.

```ini
# /etc/fstab
UUID=<UUID_устройства> /mnt/iscsi_data ext4 _netdev,nofail 0 2
```

### 4. Настройка аутентификации CHAP

Если на таргете включена аутентификация, настройте её в `/etc/iscsi/iscsid.conf` или через `iscsiadm`.

#### Через конфигурационный файл

Отредактируйте `/etc/iscsi/iscsid.conf`:

```ini
node.session.auth.authmethod = CHAP
node.session.auth.username = myuser
node.session.auth.password = mysecretpassword
```

#### Обновление параметров для конкретной ноды

```bash
sudo iscsiadm -m node -T <IQN> -p <IP> -o update -n node.session.auth.authmethod -v CHAP
sudo iscsiadm -m node -T <IQN> -p <IP> -o update -n node.session.auth.username -v myuser
sudo iscsiadm -m node -T <IQN> -p <IP> -o update -n node.session.auth.password -v mysecretpassword
```

## Дополнительная информация

### Диагностика и отладка

| Команда | Описание |
| :--- | :--- |
| `iscsiadm -m session -P 3` | Подробная информация об активных сессиях и LUN. |
| `journalctl -u open-iscsi -f` | Просмотр логов службы в реальном времени. |
| `iscsiadm -m node --logoutall=ALL` | Принудительное отключение всех сессий. |

### Типичные ошибки

- **Connection refused**: Проверьте доступность порта 3260 на таргете и настройки Firewall.
- **Authentication failed**: Проверьте логины/пароли CHAP в `iscsid.conf` и на стороне таргета.
- **Device not appearing**: Проверьте `dmesg | grep -i iscsi`. Возможно, таргет не экспортировал LUN для данного IQN инициатора.
- **Зависание при загрузке**: Убедитесь, что в `/etc/fstab` указана опция `_netdev`.

### См. также

- **[Основные концепции iSCSI](./iscsi_concepts.md)** — теория и терминология.
- **[Настройка iSCSI Target](./iscsi_target_setup.md)** — конфигурация серверной части.
- **[Управление томами LVM](../../FileSystems/LVM/operations/lvm_disk_replacement.md)** — создание VG/LV поверх iSCSI дисков.
- **[Монтирование файловых систем](../../FileSystems/mounting/scenarios/udev_mount.md)** — подробнее об опциях монтирования и udev.
- **[Policy-Based Routing](../Policy_Based_Routing/index.md)** — изоляция трафика iSCSI.
