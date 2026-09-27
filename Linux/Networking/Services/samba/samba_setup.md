# Samba: Настройка сервера

## Определения

**smb.conf** — центральный конфигурационный файл Samba (`/etc/samba/smb.conf`). Управляет глобальными настройками демона и параметрами отдельных сетевых ресурсов (шар).

**Шара (share)** — логический ресурс (директория или принтер), экспортируемый сервером для сетевого доступа. Каждая шара настраивается индивидуально в контексте прав доступа и производительности.

**Asynchronous I/O (AIO)** — механизм асинхронной обработки запросов ввода-вывода. Позволяет Samba не блокировать основной поток выполнения при ожидании ответа от дисковой подсистемы, что критично для высоконагруженных систем на базе NVMe.

**SMB Multichannel** — технология, позволяющая использовать несколько сетевых соединений в рамках одной SMB-сессии для агрегации пропускной способности и обеспечения отказоустойчивости.

**SMB Negotiation** — процесс согласования параметров соединения между клиентом и сервером. Включает обмен диалектами протокола, выбор параметров шифрования и аутентификации.

**SMB Signing** — механизм целостности пакетов, добавляющий HMAC-SHA256 к каждому SMB2 пакету. В SMBv3.1.1 подпись является обязательной для всех соединений.

**Kernel Oplocks** — механизм кэширования файлов на стороне клиента. Позволяет клиенту локально кэшировать чтения и отложенные записи, снижая сетевой трафик.

**sendfile()** — системный вызов Linux, передающий данные напрямую из файлового кэша ядра в сетевой стек, минуя пользовательское пространство. Уменьшает количество копирований данных с 4 до 1.

**VFS-цепочка (VFS chain)** — последовательность модулей VFS, вызываемых справа налево. Порядок определяет, какой модуль обрабатывает операцию первым.

**pdbedit** — утилита для управления базой данных пользователей Samba (passdb.tdb). Позволяет просматривать, создавать, изменять и удалять учетные записи.

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
| `use sendfile` | Использование sendfile() для передачи. | `yes` (требует `aio write size = 0` для совместимости) |
| `kernel oplocks` | Включение oplocks на уровне ядра. | `yes` (кэширование на клиенте) |
| `socket options` | Оптимизация TCP-сокетов. | `TCP_NODELAY IPTOS_LOWDELAY SO_RCVBUF=131072 SO_SNDBUF=131072` |
| `log level` | Уровень детализации логов. | `1` (стандарт), `3` (отладка), `10` (пакетные дампы) |
| `max protocol` | Максимальная версия протокола. | `SMB3_11` (ограничение Negotiate) |

### Процесс согласования SMB (Negotiation)

При установке соединения клиент и сервер выполняют Negotiate Protocol:
1. **SMB2_NEGOTIATE** — клиент отправляет список поддерживаемых диалектов.
2. **SMB2_NEGOTIATE Response** — сервер выбирает максимальный общий диалект.
3. **SMB2_SESSION_SETUP** — аутентификация (Kerberos или NTLM).
4. **SMB2_TREE_CONNECT** — подключение к конкретной шаре.

В SMBv3.1.1 добавлен параметр `EncryptionCapabilities`, принудительно требующий совпадение алгоритмов шифрования.

### Механизмы повышения производительности

**sendfile():**
Передача данных напрямую из файлового кэша ядра в сетевой стек. Критично для высоконагруженных хранилищ с большими файлами (видео, бэкапы). Не поддерживает шифрование SMB — при `server smb encrypt = required` автоматически отключается.

**Kernel Oplocks:**
Оплаки ( opportunistic locks ) позволяют клиенту локально кэшировать файлы. При включении `kernel oplocks = yes` ядро управляет кэшем, что снижает количество сетевых операций на 30-50% для рабочих нагрузок с повторным чтением.

**Socket Options:**
- `TCP_NODELAY` — отключает алгоритм Нагла, снижая латентность для небольших пакетов.
- `IPTOS_LOWDELAY` — устанавливает поле TOS для приоритизации задержки над пропускной способностью.
- `SO_RCVBUF`/`SO_SNDBUF` — размеры буферов приема/передачи. Значения 131072 (128KB) оптимальны для 10GbE.

## Установка и базовая настройка

### Предварительные проверки

Перед установкой убедитесь, что среда соответствует требованиям:

```bash
# Проверка дискового пространства (минимум 2GB для системы + место под шары)
df -h /

# Проверка доступности репозиториев
sudo apt update   # Debian/Ubuntu
sudo dnf check-update  # RHEL-based

# Проверка сетевых интерфейсов
ip -br link
ip -br addr

# Проверка версии ядра (SMBv3.1.1 требует >= 3.17)
uname -r
```

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

### Инициализация директорий

```bash
# Создание корневой директории для шар
sudo mkdir -p /srv/samba/shares
sudo chown root:root /srv/samba/shares
sudo chmod 755 /srv/samba/shares

# Создание тестовой шара
sudo mkdir -p /srv/samba/shares/fastdata
sudo chown nobody:nogroup /srv/samba/shares/fastdata
sudo chmod 2770 /srv/samba/shares/fastdata
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
   kernel oplocks = yes
   
   # Оптимизация сетевого стека
   socket options = TCP_NODELAY IPTOS_LOWDELAY SO_RCVBUF=131072 SO_SNDBUF=131072

[FastData]
   path = /srv/samba/shares/fastdata
   comment = NVMe Optimized Storage
   valid users = @sysadmins
   writable = yes
   browsable = yes
   # Использование расширенных атрибутов для метаданных
   vfs objects = streams_xattr
```

**Валидация:**
```bash
# Проверка Multichannel (требует активных клиентов)
smbstatus -S
# → Client: 192.168.1.10, Channels: 2 (10GbE x2)

# Проверка производительности диска
iostat -x 1
# → await: время ожидания в мс (норма < 10ms для SSD)
# → aqu-sz: глубина очереди (норма < 2 для SSD)
```

### 2. Изолированная шара с гостевым доступом

Применяется для публичных архивов внутри доверенного периметра.

```ini
[global]
   map to guest = bad user

[PublicArchive]
   path = /srv/samba/shares/public
   guest ok = yes
   read only = yes
   browsable = yes
   public = yes
```

**Валидация:**
```bash
# Подключение без пароля
smbclient //server/PublicArchive -N
# → Domain=[WORKGROUP] OS=[Windows 6.1] Server=[Samba 4.x]
```

### 3. Резервное копирование Time Machine (Apple)

Использование Samba в качестве цели для бэкапов macOS.

```ini
[TimeMachine]
   path = /srv/samba/shares/timemachine
   valid users = macuser
   writable = yes
   vfs objects = fruit streams_xattr
   # Атрибуты совместимости с Apple AAPL
   fruit:time machine = yes
   fruit:aapl = yes
   fruit:metadata = stream
   fruit:model = MacSamba
```

**Валидация:**
```bash
# Проверка VFS-модулей
testparm -s | grep -A 5 "\[TimeMachine\]"
# → vfs objects = fruit streams_xattr
```

### 4. Персональная домашняя шара ([homes])

Автоматическое создание шар на основе домашних директорий:

```ini
[homes]
   comment = Home Directories
   browseable = no
   writable = yes
   valid users = %S
   create mask = 0700
   directory mask = 0700
```

### 5. Общий доступ к принтерам ([printers])

Интеграция с CUPS:

```ini
[printers]
   comment = All Printers
   browseable = no
   path = /var/spool/samba
   printable = yes
   guest ok = no
   read only = yes
   create mask = 0700

[print$]
   comment = Printer Drivers
   path = /etc/samba/drivers
   browseable = yes
   read only = yes
   guest ok = no
```

## Управление доступом (Linux vs SMB)

Для корректной работы необходимо соблюдение двух уровней разрешений:

1. **Права ФС (Linux):** У пользователя/группы должны быть права на уровне ядра (`chmod`, `chown`).
2. **Права Samba:** Ограничения в `smb.conf` (`valid users`, `read only`).

### Создание пользователя Samba

```bash
# Создание системного пользователя без оболочки
sudo useradd -M -s /usr/sbin/nologin smbuser
# Добавление пользователя в базу Samba
sudo smbpasswd -a smbuser
# Проверка
pdbedit -L
# → smbuser:1001:

# Удаление пользователя
sudo smbpasswd -x smbuser
```

### Управление пользователями через pdbedit

```bash
# Список всех пользователей
sudo pdbedit -L
# → smbuser:1001:

# Информация о конкретном пользователе
sudo pdbedit -v -u smbuser

# Блокировка учетной записи
sudo pdbedit -L --user=smbuser
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

### Маскировка служб

```bash
# Полное отключение nmbd (не запустится даже если другой сервис зависит от него)
sudo systemctl mask nmbd
sudo systemctl unmask nmbd  # для возврата
```

### Перезапуск после изменений конфигурации

```bash
# Проверка конфигурации
testparm -s

# Перезагрузка без разрыва существующих сессий
sudo systemctl reload smbd

# Полный перезапуск (разрывает сессии)
sudo systemctl restart smbd
```

## Настройка логирования

```ini
[global]
   log level = 2
   max log size = 10240
   log file = /var/log/samba/log.%m
```

```bash
# Просмотр логов конкретного сервера
journalctl -t smbd -t nmbd -t winbindd -p err..emerg

# Отслеживание входа пользователей
journalctl -u smbd -f | grep "session setup"
```

## Изоляция и безопасность

Минимальные правила для настройки сервера:

```bash
# AppArmor (Debian/Ubuntu) — проверка профиля
sudo aa-status | grep smbd
# → /usr/sbin/smbd (enforced)

# SELinux (RHEL/Alma) — установка контекста
sudo chcon -t samba_share_t /srv/samba/shares/fastdata
```

Подробную конфигурацию AppArmor/SELinux, VFS-модулей и сетевого экрана см. в [Samba: Безопасность и VFS](./samba_security.md).

## Мониторинг и производительность

### Диагностика подключения

```bash
smbclient -L //127.0.0.1 -U smbuser
# → Sharename       Type      Comment
# → ---------       ----      -------
# → FastData        Disk      NVMe Optimized Storage
```

### Мониторинг сессий и шифрования

```bash
# Просмотр статуса шифрования текущих сессий
smbstatus -v
# → Encryption: AES-256-GCM (Active)
```

### Мониторинг производительности диска

```bash
# Мониторинг Queue Depth и latency
iostat -x 1
# → await: время ожидания в мс (норма < 10ms для SSD)
# → aqu-sz: глубина очереди (норма < 2 для SSD)

# Мониторинг сетевого стека
sar -n EDEV 1
```

### Мониторинг SMB Multichannel

```bash
# Проверка использования нескольких соединений
smbstatus -S
# → Client: 192.168.1.10, Channels: 2 (10GbE x2)
```

## Типовые ошибки настройки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `NT_STATUS_ACCESS_DENIED` | Пользователь не в `valid users` | Добавьте пользователя в параметр `valid users` или группу. |
| `NT_STATUS_BAD_NETWORK_NAME` | Шара не опубликована | Проверьте `browsable = yes` и `path` на существование. |
| `NT_STATUS_INVALID_PARAMETER` | Несоответствие SMB3.1.1 | Проверьте `server min protocol = SMB3_11` на клиенте и сервере. |
| `fruit:metadata` ошибка | macOS клиенты | Убедитесь, что `vfs objects = fruit streams_xattr` включен. |
| Нет доступа к файлам | Права ФС | `sudo -u nobody ls -l /path/to/share` — проверьте права ядра. |

## Дополнительная информация

### Проверка целостности баз данных

```bash
# Проверка базы secrets
sudo tdbtool /var/lib/samba/private/secrets.tdb check
```

### См. также

- [Обзор Samba](./index.md) — архитектура и стандарты 2026.
- [Безопасность и VFS](./samba_security.md) — продвинутые модули и аудит.
- [Интеграция с AD](./samba_ad.md) — членство в домене Active Directory.
- [Устранение неполадок](./samba_troubleshooting.md) — анализ ошибок доступа.
- [Кластеризация (CTDB)](./samba_cluster.md) — высокая доступность.
- [Автоматизация (Ansible)](./samba_automation.md) — IaC для Samba.
- [Резервное копирование](./samba_backup.md) — rsync, borgbackup.
- [Оптимизация ФС](../../../FileSystems/performance_tuning.md) — настройка ядра и дисков.
- [Монтирование SMB в Linux](../../../FileSystems/mounting/index.md) — работа со стороны клиента.
