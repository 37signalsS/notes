# Samba: Настройка сервера

## Определения

**smb.conf** — центральный конфигурационный файл Samba (`/etc/samba/smb.conf`). Управляет глобальными настройками демона и параметрами отдельных сетевых ресурсов (шар).

**Шара (share)** — логический ресурс (директория или принтер), экспортируемый сервером для сетевого доступа. Каждая шара настраивается индивидуально в контексте прав доступа и производительности.

**Asynchronous I/O (AIO)** — механизм асинхронной обработки запросов ввода-вывода. Позволяет Samba не блокировать основной поток выполнения при ожидании ответа от дисковой подсистемы, что критично для высоконагруженных систем на базе NVMe.

**SMB Multichannel** — технология, позволяющая использовать несколько сетевых соединений в рамках одной SMB-сессии для агрегации пропускной способности и обеспечения отказоустойчивости.

## Базовые концепции

### Структура конфигурации

| Секция | Назначение |
| :--- | :--- |
| `[global]` | Основные настройки: роль сервера, безопасность, сетевые параметры, логирование. |
| `[homes]` | Динамическое создание персональных шар на основе домашних директорий пользователей Linux. |
| `[printers]` | Настройка общего доступа к очередям печати (CUPS). |
| `[имя_шары]` | Пользовательская конфигурация конкретного ресурса. |

### Ключевые параметры 2026

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `server min protocol` | Минимальная версия протокола. | `SMB3_11` (защита от атак) |
| `server smb encrypt` | Обязательное шифрование трафика. | `required` |
| `aio read size` | Порог асинхронного чтения. | `1` (всегда асинхронно для SSD) |
| `aio write size` | Порог асинхронной записи. | `1` (всегда асинхронно для SSD) |
| `server multi channel` | Включение Multichannel. | `yes` |
| `map to guest` | Обработка неизвестных пользователей. | `Never` (безопасность) |

## Установка и базовая настройка

### Инсталляция компонентов

```bash
# Debian / Ubuntu / Mint
sudo apt update && sudo apt install -y samba samba-common-bin smbclient

# RHEL / Rocky / AlmaLinux / Fedora
sudo dnf install -y samba samba-common samba-client
```

### Верификация конфигурации

Перед каждым перезапуском сервиса необходимо проверять синтаксис файла:

```bash
testparm -s
# → Load smb config files from /etc/samba/smb.conf
# → Loaded services file OK.
```

## Практические сценарии

### 1. Высокопроизводительное хранилище (High-Perf)

Настройка для максимальной пропускной способности в 10GbE+ сетях с использованием SSD.

```ini
[global]
   workgroup = WORKGROUP
   security = user
   server min protocol = SMB3_11
   server smb encrypt = required
   
   # Тюнинг производительности 2026
   aio read size = 1
   aio write size = 1
   server multi channel = yes
   use sendfile = yes
   min receivefile size = 16384
   
   # Оптимизация сетевого стека
   socket options = TCP_NODELAY IPTOS_LOWDELAY SO_RCVBUF=131072 SO_SNDBUF=131072

[FastData]
   path = /data/production
   comment = NVMe Optimized Storage
   valid users = @sysadmins
   writable = yes
   browsable = yes
   # Использование расширенных атрибутов для метаданных
   vfs objects = streams_xattr
```

### 2. Изолированная шара с гостевым доступом

Применяется для публичных архивов внутри доверенного периметра.

```ini
[global]
   map to guest = bad user

[PublicArchive]
   path = /srv/samba/public
   guest ok = yes
   read only = yes
   browsable = yes
   public = yes
```

### 3. Резервное копирование Time Machine (Apple)

Использование Samba в качестве цели для бэкапов macOS.

```ini
[TimeMachine]
   path = /backups/timemachine
   valid users = macuser
   writable = yes
   vfs objects = fruit streams_xattr
   # Атрибуты совместимости с Apple AAPL
   fruit:time machine = yes
   fruit:aapl = yes
   fruit:metadata = stream
   fruit:model = MacSamba
```

## Управление доступом (Linux vs SMB)

Для корректной работы необходимо соблюдение двух уровней разрешений:

1.  **Права ФС (Linux):** У пользователя/группы должны быть права на уровне ядра (`chmod`, `chown`).
2.  **Права Samba:** Ограничения в `smb.conf` (`valid users`, `read only`).

**Пример создания пользователя:**
```bash
# Создание системного пользователя без оболочки
sudo useradd -M -s /usr/sbin/nologin smbuser
# Добавление пользователя в базу Samba
sudo smbpasswd -a smbuser
```

## Управление службами

Samba состоит из двух основных демонов, но в современных сетях (SMBv2/v3) `smbd` является самодостаточным.

```bash
# Основной демон (SMB/CIFS)
sudo systemctl enable --now smbd

# Демон имен (NetBIOS) - отключать, если не нужны старые Windows XP/7
sudo systemctl disable --now nmbd

# Проверка активных подключений
smbstatus
```

## Дополнительная информация

### Диагностика подключения

Проверка доступности шар с локальной или удаленной машины:
```bash
smbclient -L //127.0.0.1 -U smbuser
# → Sharename       Type      Comment
# → ---------       ----      -------
# → FastData        Disk      NVMe Optimized Storage
```

### См. также
- [Обзор Samba](./index.md) — архитектура и стандарты 2026.
- [Безопасность и VFS](./samba_security.md) — продвинутые модули и аудит.
- [Интеграция с AD](./samba_ad.md) — членство в домене Active Directory.
- [Оптимизация ФС](../../../FileSystems/performance_tuning.md) — настройка ядра и дисков.
- [Монтирование SMB в Linux](../../../FileSystems/mounting/index.md) — работа со стороны клиента.
