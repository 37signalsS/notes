# Samba: Настройка сервера

## Определения

**smb.conf** — главный конфигурационный файл Samba (`/etc/samba/smb.conf`). Состоит из секции `[global]` и отдельных секций шар (`[share_name]`).

**Шара (share)** — общий ресурс Samba, доступный клиентам по сети. Определяется секцией в `smb.conf` с параметрами доступа, пути и прав.

**Asynchronous I/O (AIO)** — механизм ввода-вывода, позволяющий Samba обрабатывать запросы без блокировки основного процесса, что критично для производительности на современных SSD.

## Базовые концепции

### Структура smb.conf

| Секция | Назначение |
| :--- | :--- |
| `[global]` | Глобальные параметры сервера, значения по умолчанию. |
| `[homes]` | Автоматические шары домашних директорий пользователей. |
| `[имя]` | Именованная шара с произвольными параметрами. |

### Ключевые параметры (Стандарты 2026)

| Параметр | Описание | Значение 2026 |
| :--- | :--- | :--- |
| `server min protocol` | Минимальная версия SMB | `SMB3_11` |
| `security` | Режим аутентификации | `user` |
| `map to guest` | Маппинг неудачных логинов | `Never` |
| **`aio read size`** | Порог для асинхронного чтения | `1` (всегда асинхронно) |
| **`aio write size`** | Порог для асинхронной записи | `1` (всегда асинхронно) |
| **`use sendfile`** | Использование системного вызова sendfile | `yes` |

> **Важно:** Параметр `encrypt passwords` удалён в Samba 4.24. Шифрование паролей теперь является обязательным и неотключаемым.

### Установка пакетов

```bash
# Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y samba samba-common-bin

# RHEL/CentOS/Fedora
sudo dnf install -y samba samba-common samba-client
```

Проверка конфигурации:

```bash
# Проверка синтаксиса и вывод итоговых параметров
testparm -s
```

## Практические сценарии

### Производительное хранилище с доступом по паролю

Пример настройки современной шары для работы с большими файлами и SSD.

```bash
# Создание пользователя и установка пароля
sudo useradd -M -s /usr/sbin/nologin smbworker
sudo smbpasswd -a smbworker

# Подготовка директории
sudo mkdir -p /srv/samba/fast_storage
sudo chown smbworker:smbworker /srv/samba/fast_storage
sudo chmod 0700 /srv/samba/fast_storage
```

Конфигурация в `smb.conf`:

```ini
[global]
   workgroup = WORKGROUP
   server string = High-Perf Samba
   security = user
   
   # Безопасность
   server min protocol = SMB3_11
   server smb encrypt = required
   
   # Производительность (Тюнинг 2026)
   aio read size = 1
   aio write size = 1
   use sendfile = yes
   min receivefile size = 16384
   socket options = TCP_NODELAY

[FastStorage]
   comment = SSD Optimized Share
   path = /srv/samba/fast_storage
   valid users = smbworker
   writable = yes
   browsable = yes
   vfs objects = streams_xattr
```

### Публичная шара (Только чтение, Гостевой доступ)

Используется для дистрибутивов ПО или публичных архивов.

```ini
[global]
   map to guest = bad user

[PublicArchive]
   path = /srv/samba/archive
   guest ok = yes
   read only = yes
   browsable = yes
   comment = Read-only Public Archive
```

### Оптимизация для macOS (Time Machine)

Samba позволяет выступать в роли сервера для бэкапов Apple.

```ini
[TimeMachine]
   path = /srv/samba/timemachine
   valid users = macuser
   writable = yes
   vfs objects = fruit streams_xattr
   fruit:time machine = yes
   fruit:aapl = yes
```

### Управление службами

В современных дистрибутивах используется демон `smbd`. Демон `nmbd` (NetBIOS) рекомендуется отключать, если не требуется поддержка старых клиентов Windows XP/7.

```bash
# Запуск и автозагрузка
sudo systemctl enable --now smbd

# Если требуется NetBIOS (не рекомендуется в 2026)
# sudo systemctl enable --now nmbd

# Проверка статуса
systemctl status smbd
```

## Дополнительная информация

- [Обзор Samba](./index.md) — архитектура, версии и общие сведения
- [Безопасность и VFS](./samba_security.md) — защита сервера и модули расширения
- [Интеграция с AD](./samba_ad.md) — работа в домене Active Directory
- [Устранение неполадок](./samba_troubleshooting.md) — логирование и диагностика ошибок

## Смотрите также

- [Монтирование через fstab](../../../FileSystems/mounting/fstab.md)
- [Systemd mount сценарии](../../../FileSystems/mounting/scenarios/systemd_mount.md)
- [Настройка ZFS для Samba](../../../FileSystems/filesystem_types_comparison.md)
