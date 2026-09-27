# Samba: Устранение неполадок

## Определения

**testparm** — диагностическая утилита для проверки синтаксиса `smb.conf`. Выполняет проверку всех параметров и выводит итоговую конфигурацию (Dump), которая будет фактически применена демоном.

**smbstatus** — инструмент мониторинга текущего состояния сервера в реальном времени. Показывает активные сессии, идентификаторы процессов (PID), открытые файлы и типы используемого шифрования/подписывания.

**tdbtool / ldbsearch** — низкоуровневые инструменты для работы с базами данных Samba (TDB и LDB), где хранятся маппинги, секреты и метаданные Active Directory.

**Packet Capture (SMB)** — процесс захвата и анализа сетевых пакетов (порты 445/TCP) для выявления ошибок согласования диалектов (Negotiate) или отказов в аутентификации на уровне протокола.

**smbcontrol** — утилита для отправки динамических команд работающим демонам Samba. Позволяет изменять уровень логирования, сбрасывать кеш или завершать сессии без перезапуска сервиса.

**smbd_direct** — подсистема ядра Linux для поддержки SMB Direct (RDMA). При наличии ошибок в драйвере или прошивке NIC появляются сообщения `smbd_direct_negotiate` в логах.

**smbpasswd** — утилита для управления паролями локальных пользователей Samba в базе `secrets.tdb`. В AD-средах используется только для локальных учетных записей, не доменных.

**pdbedit** — утилита для управления базой данных пользователей Samba (`passdb.tdb`). Позволяет просматривать, создавать, изменять и удалять учетные записи.

**NT_STATUS** — семейство кодов возврата протокола SMB, информирующих клиента о результате операции. Каждый код соответствует конкретному состоянию ошибки (аутентификация, права доступа, сеть).

**SMB Negotiation** — процесс согласования параметров соединения между клиентом и сервером. Включает обмен диалектами протокола, выбор параметров шифрования и аутентификации.

**SMB Signing** — механизм целостности пакетов, добавляющий HMAC-SHA256 к каждому SMB2 пакету. В SMBv3.1.1 подпись является обязательной для всех соединений.

**SMB Lease** — механизм кэширования на стороне клиента (opportunistic leasing), позволяющий хранить открытые файлы в локальном кэше без повторных запросов к серверу.

**restrict anonymous** — параметр глобальной секции, ограничивающий доступ анонимных пользователей к информации о сервере и шарах. Уровень `2` полностью запрещает перечисление шар без аутентификации.

**NTLM auth levels** — градация поддержки устаревшего протокола NTLM:
- `ntlm auth = disabled` — полный запрет NTLM.
- `ntlm auth = ntlmv2-only` — только NTLMv2, без LM/NTLMv1.
- `ntlm auth = mschapv2-and-ntlmv2` — допускает MS-CHAPv2 и NTLMv2.

**secrets.tdb** — база данных Trusted Domain Base, хранящая секреты Samba: пароли компьютера, ключи Kerberos, пароли trusted-доменов. Доступ к ней должен быть ограничен пользователем `root` и группой `root`.

**idmap** — механизм маппинга SID ↔ UID/GID. Отдельные домены требуют уникальных диапазонов для предотвращения коллизий идентификаторов.

**xattr (extended attributes)** — расширенные атрибуты файловой системы Linux, используемые Samba для хранения дескрипторов безопасности Windows (NTFS ACL) и потоков данных macOS (ADS). Коррупция xattr приводит к потере прав доступа.

**VFS-цепочка (VFS chain)** — последовательность модулей VFS, вызываемых справа налево. Порядок определяет, какой модуль обрабатывает операцию первым.

## Базовые концепции

### Архитектура диагностики Samba

Samba состоит из трех основных демонов, каждый из которых отвечает за отдельный аспект работы:

| Демон | Назначение | Лог-файл | Диагностические порты |
| :--- | :--- | :--- | :--- |
| **`smbd`** | Файловые ресурсы, аутентификация, блокировки | `/var/log/samba/log.smbd` | 445/TCP |
| **`nmbd`** | Разрешение имен NetBIOS (legacy) | `/var/log/samba/log.nmbd` | 137/UDP, 138/UDP, 139/TCP |
| **`winbindd`** | Интеграция с AD, маппинг SID ↔ UID/GID | `/var/log/samba/log.winbindd` | RPC (135, 49152+) |

В современных доменных средах (SMBv2/v3) `nmbd` часто отключается, а разрешение имен осуществляется через WSD/mDNS/DNS.

### Диагностический инструментарий

| Утилита | Назначение | Ключевой флаг |
| :--- | :--- | :--- |
| **`testparm`** | Проверка синтаксиса и ролей. | `-v` (все параметры, включая default) |
| **`smbstatus`** | Мониторинг подключений. | `-v` (детали шифрования и подписи) |
| **`smbclient`** | Тестирование доступа с клиента. | `-L` (список шар), `-U` (пользователь) |
| **`net ads`** | Управление и тест домена. | `testjoin` (проверка билета компьютера) |
| **`wbinfo`** | Проверка Winbind. | `-t` (проверка Trust Secret) |
| **`tdbtool`** | Анализ баз данных .tdb. | `check` (проверка целостности БД) |
| **`smbcontrol`** | Динамическое управление демонами. | `winbindd debug 10` (уровень логирования) |
| **`ldbsearch`** | Поиск в LDB базах (idmap.ldb). | `-H /var/lib/samba/private/idmap.ldb` |
| **`getfacl` / `setfacl`** | Управление POSIX ACL. | `-n` (цифровой вывод) |
| **`getfattr` / `setfattr`** | Управление расширенными атрибутами. | `-d` (чтение), `-n` (имя атрибута) |

### Логирование и уровни детализации

**Архитектура логов Samba:**
- **smbd**: `/var/log/samba/log.smbd` — операции файлового доступа, аутентификация, ошибки VFS.
- **winbindd**: `/var/log/samba/log.winbindd` — маппинг SID ↔ UID/GID, Kerberos, RPC.
- **nmbd**: `/var/log/samba/log.nmbd` — NetBIOS-запросы (обычно отключен).
- **rpc**: `/var/log/samba/log.rpcd` — вызовы DCE/RPC.

**Ротация логов:**
Samba использует собственную ротацию на основе `max log size`. При превышении размера лог переименовывается и создается новый. Для интеграции с `logrotate` используйте параметр `max log size = 10000` (10MB).

**Уровни логирования в `smb.conf`:**
- `log level = 1` — стандартный, только критические ошибки.
- `log level = 3` — средняя детализация, ошибки протокола и аутентификации.
- `log level = 10` — максимальная отладка, включает дампы пакетов SMB (**опасно** для производительности в production).
- `log level = 10 auth:5 vfs:3` — точечная детализация: только аутентификация на уровне 10, VFS на уровне 3.

**Динамическое изменение уровня логирования:**
```bash
# Увеличение уровня логирования winbind без перезагрузки
sudo smbcontrol winbindd debug 10

# Проверка лога
tail -f /var/log/samba/log.winbindd

# Сброс уровня обратно
sudo smbcontrol winbindd debug 1
```

### Источники журналов (Logs)

В современных системах (2026) диагностика начинается с системного журнала:

```bash
# Просмотр критических ошибок всех компонентов Samba
journalctl -t smbd -t nmbd -t winbindd -p err..emerg

# Отслеживание входа пользователей
journalctl -u smbd -f | grep "session setup"

# Анализ AVC-отказов SELinux для smbd
sudo ausearch -m avc -ts recent | grep smbd

# Анализ отказов AppArmor
sudo journalctl -u smbd | grep -i apparmor
```

### Таксономия ошибок SMB (NT_STATUS)

Коды `NT_STATUS_*` возвращаются протоколом SMB и делятся на категории:

| Категория | Примеры | Причина | Действие |
| :--- | :--- | :--- | :--- |
| **Аутентификация** | `NT_STATUS_LOGON_FAILURE`, `NT_STATUS_WRONG_PASSWORD` | Неверный пароль, заблокированная учетная запись, NTLMv1 | Проверьте пароль, настройте Kerberos, отключите NTLMv1 |
| **Права доступа** | `NT_STATUS_ACCESS_DENIED`, `NT_STATUS_BAD_NETWORK_NAME` | Недостаточно прав, шара не опубликована | Проверьте `valid users`, `path`, ACL |
| **Протокол** | `NT_STATUS_INVALID_PARAMETER`, `NT_STATUS_NOT_SUPPORTED` | Несоответствие версий SMB, устаревший клиент | Проверьте `server min protocol` |
| **Сеть** | `NT_STATUS_NETWORK_UNREACHABLE`, `NT_STATUS_CONNECTION_REFUSED` | Фаервол, маршрутизация, недоступный хост | Проверьте порты 445/139, маршруты |
| **Ресурсы** | `NT_STATUS_NO_MEMORY`, `NT_STATUS_DISK_FULL` | Недостаток памяти или места на диске | Проверьте `free -h`, `df -h` |
| **Блокировки** | `NT_STATUS_SHARING_VIOLATION`, `NT_STATUS_LOCK_NOT_GRANTED` | Файл открыт другим клиентом | `smbstatus` → завершите сессию |

### Жизненный цикл кеша Winbind

Winbind кэширует данные о пользователях, группах и SID для снижения задержек при обращении к DC. Кеш хранится в базах данных TDB (`/var/lib/samba/*.tdb`).

- **Время жизни кеша:** по умолчанию данные о пользователях кэшируются на 15 минут. Для динамических сред можно снизить до 5 минут.
- **Сброс кеша:** требуется после изменения `idmap` или проблем с маппингом. Полный сброс — удаление файлов `*.tdb` и перезапуск `winbindd`.
- **Влияние на производительность:** отключение `winbind enum users/groups = no` предотвращает полное перечисление каталога при запуске и критически важно для доменов с >10 000 пользователей.

**Диагностика кеша:**
```bash
# Просмотр текущих записей в кеше
wbinfo -c
# → EXAMPLE\username

# Проверка преобразования SID -> UID
wbinfo -n "EXAMPLE\username"
# → S-1-5-21-...-500 SID_USER (1)
wbinfo -S "S-1-5-21-...-500"
# → 10000

# Принудительная очистка кеша
sudo systemctl stop winbind
sudo rm -f /var/lib/samba/*.tdb /var/cache/samba/*.tdb
sudo systemctl start winbind
```

### Проектирование idmap-диапазонов и коллизии

Настройка `idmap` всегда состоит из двух частей:
1. **Default (`*`)**: для локальных пользователей и доменов, не описанных явно. Должен использовать бэкенд `tdb`.
2. **Domain Specific**: для каждого домена AD, с которым работает сервер.

**Проектирование диапазонов (Range Design):**
Каждый домен должен иметь непересекающийся диапазон UID/GID. При интеграции с существующими Linux-серверами используйте бэкенд `ad` с явным указанием `uidNumber`/`gidNumber`, чтобы избежать конфликтов с локальными пользователями.

**Пример диапазонов:**
- `*` (default): 3000–7999 (локальные пользователи)
- `EXAMPLE.COM`: 10000–999999 (доменные пользователи)
- `TRUSTED.COM`: 1000000–1999999 (доверенный домен)

**Диагностика коллизий:**
```bash
# Проверка диапазонов на пересечения
grep "idmap config" /etc/samba/smb.conf

# Проверка конкретного пользователя
getent passwd "EXAMPLE\username"
# → должен возвращать UID из правильного диапазона

# Если UID совпадает с локальным пользователем — это коллизия
```

### xattr, ACL и коррупция метаданных

Samba хранит полнофункциональные дескрипторы безопасности Windows в расширенных атрибутах файловой системы Linux (`system.posix_acl_access` и `user.SAMBA_PAI`). Это обеспечивает совместимость с Windows ACL, но требует поддержки xattr со стороны ФС.

**Требования к файловой системе:**
- **ext4:** `user_xattr` (по умолчанию), максимальный размер xattr 4KB.
- **XFS:** `attr2` формат (по умолчанию в современных ядрах), размер xattr до 64KB.
- **Btrfs:** полная поддержка xattr, размер до 64KB.
- **NFSv3:** ограничение xattr до 4KB, может не поддерживать `system.posix_acl_access`.
- **NFSv4:** нативная поддержка ACL, рекомендуется для доменных сред.

**Коррупция xattr:**
```bash
# Проверка поддержки на корневой ФС
getfattr -d -m "." /
# → Получение списка атрибутов

# Проверка конкретного файла
getfattr -d -m "user.SAMBA_PAI" /srv/samba/data/file.txt
# → должен возвращать дескриптор безопасности

# Если атрибут отсутствует — ACL Windows не применяется
# Причины: ФС без xattr, повреждение inode, недостаток места
```

### Kernel oplock/lease: причины конфликтов

Oplocks (opportunistic locks) позволяют клиенту локально кэшировать файлы. При включении `kernel oplocks = yes` ядро управляет кэшем, что снижает количество сетевых операций на 30–50% для рабочих нагрузок с повторным чтением.

**Типичные проблемы:**
- **Два клиента, один файл:** При попытке одновременного редактирования один клиент получает ` oplock break`, что может приводить к задержкам.
- **Ошибка `NT_STATUS_SHARING_VIOLATION`:** Файл заблокирован другим клиентом. Используйте `smbstatus` для поиска блокировки.
- **macOS и oplocks:** macOS иногда некорректно обрабатывает `level2 oplocks`. Если возникают артефакты кэширования, отключите `level2 oplocks = no`.

**Диагностика:**
```bash
# Проверка статуса oplock
smbstatus -v
# → Oplock: Granted (Level II)

# Принудительный break oplock
sudo smbcontrol smbd break oplock <pid> <tid> <fid>
```

### VFS-цепочка: порядок выполнения и побочные эффекты

При обращении к файлу Samba вызывает VFS-модули справа налево. Например, для `vfs objects = full_audit acl_xattr fruit`:
1. `fruit` обрабатывает запрос первым (macOS-специфичные атрибуты).
2. `acl_xattr` считывает/записывает NTFS ACL.
3. `full_audit` логирует операцию после выполнения.

Для безопасности критично размещать `full_audit` последним в цепочке, чтобы логгировались уже обработанные операции.

**Типичные ошибки конфигурации VFS:**
```ini
# НЕПРАВИЛЬНО: full_audit перед acl_xattr — audit не увидит итоговые права
vfs objects = full_audit acl_xattr

# ПРАВИЛЬНО: full_audit последним
vfs objects = acl_xattr full_audit
```

### SMB over TLS: сертификаты и отладка

Для доменных сред требуется корректная работа с сертификатами:

```ini
[global]
   # Для AD DC
   tls enabled = yes
   tls keyfile = /etc/samba/tls/key.pem
   tls certfile = /etc/samba/tls/cert.pem
   tls cafile = /etc/samba/tls/ca.pem
   tls priority = NORMAL:-VERS-SSL3.0:-VERS-TLS1.0:-VERS-TLS1.1
   tls verify peer = ca_and_serial
```

**Диагностика TLS:**
```bash
# Проверка сертификата
openssl x509 -in /etc/samba/tls/cert.pem -noout -dates -subject

# Проверка цепочки
openssl verify -CAfile /etc/samba/tls/ca.pem /etc/samba/tls/cert.pem

# Проверка статуса TLS в сессиях
smbstatus -v
# → TLS: Active (TLS_AES_256_GCM_SHA384)
```

### SMB Negotiation: типичные сбои согласования

При установке соединения клиент и сервер выполняют Negotiate Protocol:
1. **SMB2_NEGOTIATE** — клиент отправляет список поддерживаемых диалектов.
2. **SMB2_NEGOTIATE Response** — сервер выбирает максимальный общий диалект.
3. **SMB2_SESSION_SETUP** — аутентификация (Kerberos или NTLM).
4. **SMB2_TREE_CONNECT** — подключение к конкретной шаре.

**Типичные причины сбоя Negotiate:**
- Клиент не поддерживает `SMB3_11` (старые Windows 7 без обновлений, встроенные устройства).
- Несоответствие шифровых наборов (cipher suites).
- Сетевой экран блокирует пакеты Negotiate.
- Антивирус на клиенте инжектирует пакеты и нарушает Negotiate.

## Практические сценарии

### 1. Проблемы аутентификации и Kerberos

Если сервер не может авторизовать пользователей домена:

1. **Проверка времени:** `chronyc tracking` (разница с DC должна быть < 5 мин).
2. **Проверка билета компьютера:** `klist -k /etc/krb5.keytab`. Если ключей нет или они устарели, переприсоединитесь к домену.
3. **Тест RPC-канала:** `wbinfo -t`. Если ошибка `NT_STATUS_ACCESS_DENIED`, сбросьте пароль компьютера через `net ads changetrustpw`.
4. **Анализ KVNO:** Сравните Key Version Number в AD и локальном keytab:
    ```bash
    kvno host/samba-srv.example.com@EXAMPLE.COM
    ```

**Дополнительные проверки:**
```bash
# Проверка видимости пользователя через ОС
getent passwd "EXAMPLE\username"
# → EXAMPLE\username:x:10000:10000:User:/home/username:/bin/bash

# Если пользователь не виден — проверьте NSS
cat /etc/nsswitch.conf | grep -E "passwd|group"
# → passwd:         files winbind
# → group:          files winbind
```

### 2. Ошибки доступа (Access Denied)

Если права кажутся верными, но доступа нет:

- **Проверка эффективных прав Linux:** `sudo -u nobody ls -l /path/to/share` (проверьте, может ли системный пользователь войти в директорию).
- **Проверка ACL:** `getfacl /path/to/file`. Samba отдает приоритет наиболее строгим правам (Linux vs SMB).
- **Проверка xattr:** `getfattr -d /path/to/file`. Убедитесь, что присутствуют атрибуты SAMBA.
- **Сброс кеша Winbind:** Если маппинг SID ↔ UID сломался:
    ```bash
    sudo systemctl stop winbind
    sudo rm -f /var/lib/samba/*.tdb /var/cache/samba/*.tdb
    sudo systemctl start winbind
    ```

### 3. Проблемы производительности (Latency/Throughput)

- **SMB Multichannel:** Если скорость не растет при наличии нескольких линков, проверьте `smbstatus -S` — клиент должен использовать несколько соединений.
- **RDMA (SMB Direct):** Проверьте поддержку в ядре и драйверах NIC. В логах не должно быть ошибок `smbd_direct_negotiate`.
- **AIO:** Убедитесь, что `aio read size = 1` включен. Используйте `iostat`, чтобы увидеть глубину очереди (Queue Depth).
- **sendfile():** При `server smb encrypt = required` автоматически отключается. Если производительность падает при включении шифрования — это ожидаемо.

**Глубокий анализ производительности:**
```bash
# Мониторинг очереди диска
iostat -x 1
# → await: время ожидания в мс (норма < 10ms для SSD)
# → aqu-sz: глубина очереди (норма < 2 для SSD)

# Мониторинг сетевых ошибок
ip -s link show eth0
# → проверьте drops, overruns, errors

# Проверка TCP-сокетов Samba
ss -tnp | grep smbd
# → должно быть много established соединений
```

### 4. Анализ сетевого трафика (Packet Capture)

Для отладки сложных проблем согласования (например, почему не включается шифрование):

```bash
# Захват SMB трафика без полезной нагрузки (только заголовки)
sudo tcpdump -i eth0 port 445 -s 128 -w smb_debug.pcap

# Анализ в реальном времени
sudo tcpdump -i eth0 port 445 -s 128 -X | grep -i "negotiate\|session setup"
```

Анализируйте файл в Wireshark, используя фильтр `smb2`. Ищите пакеты `Negotiate Protocol` и `Session Setup`.

**Типичные проблемы, видимые в Wireshark:**
- Отсутствие `EncryptionCapabilities` в Negotiate — клиент не поддерживает SMBv3.1.1.
- `Session Setup` с `NTLMSSP` — Kerberos не работает.
- `Tree Connect` с `STATUS_BAD_NETWORK_NAME` — шара не опубликована.

### 5. Повреждение баз данных (TDB/LDB)

Если Samba ведет себя нестабильно или не запускается:

```bash
# Проверка целостности базы secrets
sudo tdbtool /var/lib/samba/private/secrets.tdb check

# Проверка LDB баз
sudo ldbsearch -H /var/lib/samba/private/idmap.ldb

# Если база повреждена, потребуется восстановление из бэкапа или переприсоединение к AD.
```

**Резервное копирование:**
```bash
sudo tar -czf /backup/samba-tdb-$(date +%F).tar.gz /var/lib/samba/private/
```

### 6. Клиентские проблемы Windows

**Не видна шара в сетевом окружении:**
```powershell
# Очистка кеша обнаружения на клиенте
ipconfig /flushdns
nbtstat -R

# Проверка поддержки SMBv3
Get-SmbConnection
# → должна отображаться версия SMB

# Принудительное использование SMBv3.1.1
New-SmbMapping -RemotePath \\server\share -UserName domain\user -SmbVersion 3.1.1
```

**Offline Files и кэширование:**
- Отключите Offline Files в Windows, если возникают артефакты кэширования.
- Убедитесь, что на шарах установлен `oplocks = yes` и `level2 oplocks = yes`.

**Ошибка `The specified network name is no longer available`:**
- Причина: сервер перезапустился, соединение разорвано.
- Решение: переподключите шар. Для предотвращения используйте `deadtime = 15` на сервере.

### 7. Клиентские проблемы macOS

**Ошибка `fruit:metadata`:**
```bash
# Убедитесь, что VFS-модули включены
testparm -s | grep -A 5 "\[TimeMachine\]"
# → vfs objects = fruit streams_xattr
```

**Time Machine не видит шар:**
```bash
# Проверка атрибутов AAPL
smbclient //server/TimeMachine -U macuser -m SMB3
# → должен отображаться атрибут AAPL

# Перезагрузка демонов на macOS
sudo launchctl unload /System/Library/LaunchDaemons/com.apple.smb.server.plist
sudo launchctl load /System/Library/LaunchDaemons/com.apple.smb.server.plist
```

### 8. Клиентские проблемы Linux (mount.cifs)

**Монтирование не работает:**
```bash
# Проверка версии SMB
sudo mount.cifs //server/share /mnt -o vers=3.1.1,sec=krb5

# Для гостевого доступа
sudo mount.cifs //server/share /mnt -o guest,vers=3.0

# Для пользовательской аутентификации
sudo mount.cifs //server/share /mnt -o username=user,password=pass,vers=3.1.1
```

**Типичные ошибки mount.cifs:**
- `mount error(13): Permission denied` — проверьте `sec=` (krb5/ntlmv2) и `vers=`.
- `mount error(112): Host is down` — проверьте сетевую доступность и порт 445.
- `CIFS VFS: No writable address found` — сервер не поддерживает указанную версию SMB.

### 9. Проблемы разрешения имен и browsing

**Шара не видна в сетевом окружении:**
```bash
# Проверка WSD Discovery
sudo ss -ulnp | grep 5357

# Проверка mDNS/Bonjour
sudo avahi-browse -a | grep smb

# Проверка NetBIOS (legacy)
sudo nmblookup -A 192.168.1.10
```

**Для Windows-клиентов:**
```powershell
# Очистка NetBIOS-кеша
nbtstat -RR

# Перезапуск Function Discovery
net stop fdrespub
net start fdrespub
```

### 10. Проблемы с подписью и шифрованием SMB

**Шифрование неактивно:**
```bash
# Проверка статуса шифрования
smbstatus -v
# → Encryption: AES-256-GCM (Active)

# Если шифрование неактивно:
# 1. Проверьте server min protocol = SMB3_11
# 2. Проверьте client min protocol = SMB3_11
# 3. Проверьте, что клиент поддерживает SMBv3.1.1
# 4. Проверьте server smb encrypt = required
```

**Подпись неактивна:**
```bash
# Проверка статуса подписи
smbstatus -v
# → Signing: Active (SMB 3.1.1)

# Принудительная подпись
smbcontrol smbd signing mandatory
```

### 11. Диагностика и восстановление TDB/LDB баз

**Полная проверка всех баз:**
```bash
# Проверка secrets.tdb
sudo tdbtool /var/lib/samba/private/secrets.tdb check

# Проверка passdb.tdb
sudo tdbtool /var/lib/samba/private/passdb.tdb check

# Проверка idmap.ldb
sudo ldbsearch -H /var/lib/samba/private/idmap.ldb

# Проверка account_policy.tdb
sudo tdbtool /var/lib/samba/private/account_policy.tdb check
```

**Восстановление из бэкапа:**
```bash
# Остановка сервисов
sudo systemctl stop smbd winbind

# Восстановление из бэкапа
sudo tar -xzf /backup/samba-tdb-2026-09-12.tar.gz -C /var/lib/samba/

# Исправление прав
sudo chown -R root:root /var/lib/samba/private
sudo chmod 600 /var/lib/samba/private/secrets.tdb
sudo chmod 600 /var/lib/samba/private/idmap.ldb

# Запуск
sudo systemctl start smbd winbind
```

### 12. Управление сервисами systemd

**Сервис не запускается:**
```bash
# Проверка статуса
systemctl status smbd
# → Active: failed (Result: exit-code)

# Просмотр логов
journalctl -u smbd -n 50
# → ищите ошибки конфигурации или прав доступа

# Проверка конфигурации
testparm -s
# → Loaded services file OK.

# Принудительный перезапуск
sudo systemctl daemon-reload
sudo systemctl restart smbd
```

**Маскировка и размаскировка:**
```bash
# Полное отключение nmbd (не запустится даже если другой сервис зависит от него)
sudo systemctl mask nmbd
sudo systemctl unmask nmbd  # для возврата
```

**Перезагрузка без разрыва сессий:**
```bash
# Проверка конфигурации
testparm -s

# Перезагрузка без разрыва сессий
sudo systemctl reload smbd

# Полный перезапуск (разрывает сессии)
sudo systemctl restart smbd
```

### 13. Анализ производительности: CPU, память, диск

```bash
# Мониторинг потребления CPU/памяти smbd
top -p $(pgrep smbd)
# → отслеживайте %CPU, %MEM, VSZ, RSS

# Поиск утечек памяти
ps -eo pid,pmem,pcpu,cmd --sort=-pmem | head -20
# → smbd должен потреблять <100MB на процесс

# Анализ дисковой подсистемы
iostat -x 1
# → await: время ожидания в мс (норма < 10ms для SSD)
# → aqu-sz: глубина очереди (норма < 2 для SSD)

# Проверка inodes
df -i /srv/samba
# → Inodes не должны быть exhausted

# Проверка количества открытых файлов
cat /proc/sys/fs/file-nr
# → должно быть меньше /proc/sys/fs/file-max
```

### 14. Восстановление после сбоев и миграция

**Миграция TDB баз между версиями:**
```bash
# Samba 4.x использует TDB версии 2
# При обновлении с 4.18 на 4.20 TDB автоматически конвертируется
# Принудительная конвертация:
sudo tdbbackup /var/lib/samba/private/secrets.tdb
sudo tdbtool /var/lib/samba/private/secrets.tdb upgrade
```

**Сброс всего состояния Samba:**
```bash
# Опасная операция! Используйте только при полной переустановке.
sudo systemctl stop smbd winbind nmbd
sudo rm -rf /var/lib/samba/* /var/cache/samba/* /var/run/samba/*
sudo systemctl start smbd winbind
```

### 15. Расширенный анализ логов

**Паттерны для grep:**
```bash
# Ошибки аутентификации
grep -i "NT_STATUS_LOGON_FAILURE\|NT_STATUS_WRONG_PASSWORD" /var/log/samba/log.smbd

# Ошибки доступа
grep -i "NT_STATUS_ACCESS_DENIED\|NT_STATUS_BAD_NETWORK_NAME" /var/log/samba/log.smbd

# Ошибки блокировок
grep -i "NT_STATUS_SHARING_VIOLATION\|NT_STATUS_LOCK_NOT_GRANTED" /var/log/samba/log.smbd

# Сетевые ошибки
grep -i "NT_STATUS_NETWORK_UNREACHABLE\|NT_STATUS_CONNECTION_REFUSED" /var/log/samba/log.smbd
```

**Анализ логов Winbind:**
```bash
# Ошибки маппинга
grep -i "could not convert name\|nt_status_unsuccessful" /var/log/samba/log.winbindd

# Проблемы с Kerberos
grep -i "kinit\|kerberos\|preauth" /var/log/samba/log.winbindd
```

## Типовые ошибки и решения 2026

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `NT_STATUS_ACCESS_DENIED` на клиенте | Устаревший NTLM | Отключите NTLMv1, используйте Kerberos или NTLMv2. |
| `NT_STATUS_INVALID_PARAMETER` | Несоответствие SMB3.1.1 | Проверьте `server min protocol`. |
| Ошибка `fruit:metadata` | macOS клиенты | Убедитесь, что `vfs objects = fruit streams_xattr` включен. |
| Дубликаты UID/GID | Ошибка в `idmap config` | Проверьте диапазоны (ranges) в `smb.conf` на отсутствие пересечений. |
| `NT_STATUS_LOGON_FAILURE` | Неверный пароль или учетная запись заблокирована | Проверьте пароль, статус учетной записи в AD. |
| `NT_STATUS_WRONG_PASSWORD` | Устаревший NTLM или неверный пароль | Переключитесь на Kerberos, сбросьте пароль. |
| `NT_STATUS_BAD_NETWORK_NAME` | Шара не опубликована или `path` не существует | Проверьте `browsable = yes` и существование директории. |
| `NT_STATUS_SHARING_VIOLATION` | Файл открыт другим клиентом | `smbstatus` → завершите сессию или подождите. |
| `NT_STATUS_NETWORK_UNREACHABLE` | Фаервол или маршрутизация | Откройте порт 445/TCP, проверьте маршруты. |
| `NT_STATUS_CONNECTION_REFUSED` | smbd не слушает порт | `systemctl status smbd`, проверьте `smb ports = 445`. |
| `NT_STATUS_NO_MEMORY` | Недостаток оперативной памяти | Проверьте `free -h`, увеличьте swap или RAM. |
| `NT_STATUS_DISK_FULL` | Диск заполнен | `df -h /srv/samba`, очистите место или расширьте раздел. |
| `NT_STATUS_NOT_SUPPORTED` | Устаревший клиент или протокол | Проверьте `max protocol` на сервере и клиенте. |
| `NT_STATUS_OBJECT_NAME_NOT_FOUND` | Путь не существует | Проверьте `path` в конфигурации шара. |
| `NT_STATUS_TOO_MANY_OPEN_FILES` | Лимит открытых файлов | `ulimit -n` для smbd, увеличьте `max open files` в systemd. |
| `NT_STATUS_IO_DEVICE_ERROR` | Ошибка диска или RAID | Проверьте `smartctl`, `cat /proc/mdstat`. |
| `NT_STATUS_CANT_WAIT` | Таймаут операции | Увеличьте `deadtime` или проверьте сеть. |
| Шифрование неактивно | Клиент не поддерживает SMBv3 | Проверьте `server min protocol = SMB3_11` и версию Windows/macOS. |
| Подпись неактивна | Клиент не запросил подпись | Проверьте `client signing = auto` на клиенте. |
| `smbd_direct_negotiate` ошибка | Проблемы с RDMA/NIC | Проверьте драйверы NIC, отключите `server multi channel = yes` для теста. |
| `NT_STATUS_UNEXPECTED_IO_ERROR` | Коррупция TDB или xattr | Проверьте `tdbtool check`, `getfattr` на проблемных файлах. |

## Дополнительная информация

- [Samba: Обзор](./index.md) — архитектура и протоколы.
- [Samba: Настройка сервера](./samba_setup.md) — базовые параметры.
- [Samba: Интеграция с AD](./samba_ad.md) — детальная отладка Winbind и idmap.
- [Samba: Безопасность и VFS](./samba_security.md) — аудит и права доступа.
- [Синхронизация времени (Chrony)](../chrony_ntp.md) — база для Kerberos.

## См. также

- [Wireshark: практические сценарии](../../../../Networking/ServicesAndTools/Wireshark/practical_scenarios.md) — анализ SMB-трафика.
- [Протокол Kerberos: диагностика](../../../../Security/Concepts/kerberos.md) — глубокая отладка тикетов.
- [Диагностика производительности дисков](../../../Diagnostics/Performance/DiskIO/invisible_io.md) — анализ задержек и очередей.
- [Кластеризация (CTDB)](./samba_cluster.md) — диагностика кластеров.
- [Мониторинг](./samba_monitoring.md) — Prometheus, Grafana.
- [Резервное копирование](./samba_backup.md) — восстановление данных.
- [Механизмы SELinux](../../../Security/Mechanisms/SELinux.md) — булевы значения и политики для Samba.
- [AppArmor: профилирование](../../../Security/Mechanisms/AppArmor.md) — управление профилями MAC.
- [Безопасность сетевого уровня (nftables)](../../Settings/tools/nftables/architecture_and_concepts.md) — фильтрация трафика.
