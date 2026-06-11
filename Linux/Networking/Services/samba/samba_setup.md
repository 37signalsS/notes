# Samba: Настройка сервера

## Определения

**smb.conf** — главный конфигурационный файл Samba (`/etc/samba/smb.conf`). Состоит из секции `[global]` и отдельных секций шар (`[share_name]`).

**Шара (share)** — общий ресурс Samba, доступный клиентам по сети. Определяется секцией в `smb.conf` с параметрами доступа, пути и прав.

**Гостевой доступ** — доступ к сетевому ресурсу без необходимости ввода пароля. Управляется параметрами `map to guest` и `guest ok`.

## Базовые концепции

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

> **Важно:** Параметр `encrypt passwords` является устаревшим (deprecated) с версии Samba 4.11 и удалён в 4.24. Шифрование паролей теперь всегда включено по умолчанию.

### Переменные подстановки

| Переменная | Описание |
| :--- | :--- |
| `%u` | Имя пользователя |
| `%g` | Группа пользователя |
| `%I` | IP-адрес клиента |
| `%m` | NetBIOS-имя клиента |
| `%S` | Имя текущей шары |
| `%H` | Домашняя директория пользователя |

### Установка пакетов

```bash
# Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y samba

# RHEL/CentOS
sudo yum install -y samba samba-common samba-client
```

Проверка конфигурации:

```bash
testparm -s
# → Load smb config files from /etc/samba/smb.conf
# → Loaded services file OK.
```

## Практические сценарии

### Гостевой (анонимный) доступ

```bash
# Создание директории и установка прав
sudo mkdir -p /srv/samba/public
sudo chown -R nobody:nogroup /srv/samba/public/
sudo chmod -R 0775 /srv/samba/public/
```

Конфигурация в `smb.conf`:

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
# Создание системного пользователя без возможности входа в shell
sudo useradd --no-create-home --shell /usr/sbin/nologin smbuser

# Установка пароля Samba (отдельная база данных пользователей)
sudo smbpasswd -a smbuser
# → New SMB password:
# → Retype new SMB password:
# → Added user smbuser.

# Создание директории с ограничением прав
sudo mkdir -p /srv/samba/private
sudo chown -R smbuser:smbuser /srv/samba/private/
sudo chmod -R 0770 /srv/samba/private/
```

Конфигурация в `smb.conf`:

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
# Создание группы и добавление пользователя
sudo groupadd sambashare
sudo usermod -aG sambashare username

# Подготовка директории с битом setgid
sudo mkdir -p /srv/samba/share
sudo chown -R root:sambashare /srv/samba/share
sudo chmod 2770 /srv/samba/share  # setgid для наследования группы новыми файлами
```

Конфигурация в `smb.conf`:

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
# Активация и запуск служб (Debian/Ubuntu)
sudo systemctl enable --now smb nmb
# → Created symlink ...

# Перезапуск после изменения конфигурации
sudo systemctl restart smb nmb
```

## Дополнительная информация

- [Обзор Samba](./index.md) — архитектура, версии и общие сведения
- [Безопасность и VFS](./samba_security.md) — защита сервера и модули расширения
- [Интеграция с AD](./samba_ad.md) — работа в домене Active Directory
- [Устранение неполадок](./samba_troubleshooting.md) — логирование и диагностика ошибок

## Смотрите также

- [Монтирование через fstab](../../../FileSystems/mounting/fstab.md)
- [Systemd mount](../../../FileSystems/mounting/scenarios/systemd_mount.md)
