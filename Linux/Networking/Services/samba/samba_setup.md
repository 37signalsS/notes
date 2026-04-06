# Samba: Server Configuration

## Definitions

**smb.conf** — главный конфигурационный файл Samba (`/etc/samba/smb.conf`). Состоит из секции `[global]` и отдельных секций шар (`[share_name]`).

**Шара (share)** — общий ресурс Samba, доступный клиентам по сети. Определяется секцией в `smb.conf` с параметрами доступа, пути и прав.

**Гостевой доступ** — доступ к шаре без аутентификации. Управляется параметром `map to guest` и `guest ok`.

## Basic Concepts

### Структура smb.conf

| Секция | Назначение |
| :--- | :--- |
| `[global]` | Глобальные параметры сервера, значения по умолчанию |
| `[homes]` | Автоматические шары домашних директорий пользователей |
| `[printers]` | Доступ к принтерам |
| `[имя]` | Именованная шара с произвольными параметрами |

### Ключевые параметры

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `workgroup` | Имя рабочей группы / домена | `WORKGROUP` |
| `server string` | Описание сервера (отображается клиентам) | `%h server` |
| `security` | Режим аутентификации | `user` |
| `map to guest` | Маппинг неудачных логинов | `Never` |
| `server min protocol` | Минимальная версия SMB | `SMB2_10` |
| `load printers` | Загрузка списка принтеров | `yes` |
| `disable spoolss` | Отключение подсистемы печати | `no` |

> **Важно:** Параметр `encrypt passwords` deprecated с Samba 4.11, удалён в 4.24. Шифрование паролей всегда включено по умолчанию.

### Переменные подстановки

| Переменная | Описание |
| :--- | :--- |
| `%u` | Имя пользователя |
| `%g` | Группа пользователя |
| `%I` | IP-адрес клиента |
| `%m` | NetBIOS-имя клиента |
| `%S` | Имя теку шары |
| `%H` | Домашняя директория пользователя |

### Установка пакетов

```bash
# Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y samba

# RHEL/CentOS
sudo yum install -y samba samba-common samba-client
```

Проверка конфигурации: `testparm -s`

## Practical Scenarios

### Гостевой (анонимный) доступ

```bash
sudo mkdir -p /srv/samba/public
sudo chown -R nobody:nogroup /srv/samba/public/
sudo chmod -R 0775 /srv/samba/public/
```

```ini
[global]
   workgroup = WORKGROUP
   server string = Samba Server
   security = user
   map to guest = bad user
   server min protocol = SMB3
   load printers = no
   disable spoolss = yes

[Public]
   comment = Public Share
   path = /srv/samba/public
   browsable = yes
   writable = yes
   guest ok = yes
   read only = no
```

### Доступ по паролю

```bash
# Создание системного пользователя без shell
sudo useradd --no-create-home --shell /usr/sbin/nologin smbuser

# Установка пароля Samba (отдельная база)
sudo smbpasswd -a smbuser

# Создание директории
sudo mkdir -p /srv/samba/private
sudo chown -R smbuser:smbuser /srv/samba/private/
sudo chmod -R 0770 /srv/samba/private/
```

```ini
[Private]
   comment = Private Share
   path = /srv/samba/private
   valid users = smbuser
   guest ok = no
   writable = yes
   browsable = yes
```

### Шара для группы

```bash
sudo groupadd sambashare
sudo usermod -aG sambashare username
sudo mkdir -p /srv/samba/share
sudo chown -R root:sambashare /srv/samba/share
sudo chmod 2770 /srv/samba/share  # setgid для наследования группы
sudo smbpasswd -a username
```

```ini
[share]
   path = /srv/samba/share
   browsable = yes
   read only = no
   valid users = @sambashare
   create mask = 0660
   directory mask = 0770
   force group = sambashare
```

### Управление службами

```bash
sudo systemctl enable --now smb nmb    # Debian/Ubuntu
sudo systemctl restart smb nmb          # Перезапуск
testparm -s                             # Проверка конфигурации
```

## Additional Information

Связанные документы: [обзор Samba](./index.md), [безопасность и VFS](./samba_security.md), [AD-интеграция](./samba_ad.md), [устранение неполадок](./samba_troubleshooting.md). Клиентское монтирование: [fstab](../../../FileSystems/mounting/fstab.md), [systemd mount](../../../FileSystems/mounting/scenarios/systemd_mount.md).
