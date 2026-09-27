# Samba: Безопасность и VFS-модули

## Определения

**VFS (Virtual File System) modules** — расширяемые модули Samba, подключаемые к сетевым ресурсам (шарам) для добавления функциональности: аудит, корзина, снапшоты, антивирусная проверка. Указываются в директиве `vfs objects`.

**SMB Encryption** — шифрование трафика на уровне протокола SMB (AES-256-GCM в SMBv3.1.1). Защищает данные от перехвата и модификации (MitM).

**POSIX ACL vs NTFS ACL** — взаимодействие прав доступа Linux и Windows. Samba использует расширенные атрибуты (`xattr`) для хранения полнофункциональных дескрипторов безопасности Windows поверх файловой системы Linux.

**Zero Trust SMB** — архитектурный подход, требующий обязательного шифрования (`smb encrypt = required`), сильной аутентификации (Kerberos) и строгой изоляции сервиса.

**SMB Signing** — механизм целостности пакетов, добавляющий HMAC-SHA256 к каждому SMB2 пакету. В SMBv3.1.1 подпись является обязательной для всех соединений, что исключает возможность downgrade-атак.

**SMB Lease** — механизм кэширования на стороне клиента (opportunistic leasing), позволяющий хранить открытые файлы в локальном кэше без повторных запросов к серверу. Управляется параметрами `kernel oplocks` и `level2 oplocks`.

**restrict anonymous** — параметр глобальной секции, ограничивающий доступ анонимных пользователей к информации о сервере и шарам. Уровень `2` полностью запрещает перечисление шар без аутентификации.

**NTLM auth levels** — градация поддержки устаревшего протокола NTLM:
- `ntlm auth = disabled` — полный запрет NTLM.
- `ntlm auth = ntlmv2-only` — только NTLMv2, без LM/NTLMv1.
- `ntlm auth = mschapv2-and-ntlmv2` — допускает MS-CHAPv2 и NTLMv2.

**secrets.tdb** — база данных Trusted Domain Base, хранящая секреты Samba: пароли компьютера, ключи Kerberos, пароли trusted-доменов. Доступ к ней должен быть ограничен пользователем `root` и группой `root`.

**idmap** — механизм маппинга SID ↔ UID/GID. Отдельные домены требуют уникальных диапазонов для предотвращения коллизий идентификаторов.

## Базовые концепции

### Безопасность протокола (Стандарты 2026)

| Параметр | Назначение | Рекомендация 2026 |
| :--- | :--- | :--- |
| **`server min protocol`** | Минимальная версия SMB | **`SMB3_11`** |
| **`smb encrypt`** | Шифрование трафика | **`required`** (обязательно для всех) |
| **`ntlm auth`** | Тип NTLM-аутентификации | **`disabled`** (в пользу Kerberos) |
| **`restrict anonymous`** | Ограничение анонимного доступа | **`2`** (полный запрет) |
| **`lanman auth`** | Устаревшая аутентификация | **`no`** |
| **`client signing`** | Подпись клиентских запросов | **`auto`** (проверка, если сервер требует) |
| **`server signing`** | Подпись серверных ответов | **`auto`** (подпись при запросе клиента) |

### SMB Signing и целостность данных

SMB signing обеспечивает защиту от MitM-атак путем добавления HMAC-SHA256 к каждому пакету. В SMBv3.1.1 подпись является обязательной для всех соединений, что исключает возможность downgrade-атак.

**Верификация подписи:**
```bash
# Проверка статуса подписи текущих сессий
smbstatus -v
# → Signing: Active (SMB 3.1.1)
```

**Принудительная подпись для совместимости:**
```ini
[global]
   server signing = mandatory
   client signing = mandatory
```

### SMB Lease и Oplock семантика

**Kernel Oplocks** позволяют клиенту локально кэшировать файлы. При включении `kernel oplocks = yes` ядро управляет кэшем, что снижает количество сетевых операций на 30–50% для рабочих нагрузок с повторным чтением.

**Level2 Oplocks** — упрощенная версия oplocks, передающая эксклюзивный доступ клиенту, но сохраняющая возможность параллельных чтений другими клиентами.

```ini
[global]
   kernel oplocks = yes
   level2 oplocks = yes
   oplock break wait time = 100
```

### POSIX ACL vs NTFS ACL: архитектура хранения

Samba хранит полнофункциональные дескрипторы безопасности Windows в расширенных атрибутах файловой системы Linux (`system.posix_acl_access` и `user.SAMBA_PAI`). Это обеспечивает совместимость с Windows ACL, но требует поддержки xattr со стороны ФС.

**Требования к файловой системе:**
- **ext4:** `user_xattr` (по умолчанию), максимальный размер xattr 4KB.
- **XFS:** `attr2` формат (по умолчанию в современных ядрах), размер xattr до 64KB.
- **Btrfs:** полная поддержка xattr, размер до 64KB.
- **NFSv3:** ограничение xattr до 4KB, может не поддерживать `system.posix_acl_access`.
- **NFSv4:** нативная поддержка ACL, рекомендуется для доменных сред.

**Проверка поддержки xattr:**
```bash
# Проверка поддержки на корневой ФС
getfattr -d -m "." /
# → Получение списка атрибутов

# Проверка размера доступного пространства для xattr
df -h /srv/samba/data
# → Размер ФС должен быть достаточным для ACL (рекомендуется >10GB)
```

### Механизмы повышения производительности

**sendfile():**
Передача данных напрямую из файлового кэша ядра в сетевой стек. Критично для высоконагруженных хранилищ с большими файлами (видео, бэкапы). Не поддерживает шифрование SMB — при `server smb encrypt = required` автоматически отключается.

**Socket Options:**
- `TCP_NODELAY` — отключает алгоритм Нагла, снижая латентность для небольших пакетов.
- `IPTOS_LOWDELAY` — устанавливает поле TOS для приоритизации задержки над пропускной способностью.
- `SO_RCVBUF`/`SO_SNDBUF` — размеры буферов приема/передачи. Значения 131072 (128KB) оптимальны для 10GbE.

### Виртуальная файловая система (VFS)

Использование нескольких модулей требует соблюдения порядка (справа налево в цепочке вызовов).

| Модуль | Описание | Применение |
| :--- | :--- | :--- |
| **`acl_xattr`** | Хранение ACL в атрибутах | Обеспечивает полноценную работу прав Windows. |
| **`fruit`** | Оптимизация для macOS | Обязателен для предотвращения утечек метаданных Apple. |
| **`shadow_copy2`** | Снапшоты | Реализация «Предыдущих версий» Windows. |
| **`virusfilter`** | Антивирус | Онлайн-сканирование через ClamAV/Sophos. |
| **`full_audit`** | Аудит | Логирование операций (соответствие ФЗ/GDPR). |
| **`recycle`** | Корзина | Восстановление удаленных файлов конечными пользователями. |
| **`prealloc`** | Предварительное выделение | Уменьшение фрагментации для больших файлов. |
| **`streams_xattr`** | Потоки данных | Хранение альтернативных потоков данных (ADS). |
| **`quota`** | Квоты | Ограничение места на диске для пользователей/групп. |
| **`perfile`** | Фильтрация по типу | Блокировка исполняемых файлов на шаре. |

### Порядок выполнения VFS-цепочки

При обращении к файлу Samba вызывает VFS-модули справа налево. Например, для `vfs objects = full_audit acl_xattr fruit`:
1. `fruit` обрабатывает запрос первым (macOS-специфичные атрибуты).
2. `acl_xattr` считывает/записывает NTFS ACL.
3. `full_audit` логирует операцию после выполнения.

Для безопасности критично размещать `full_audit` последним в цепочке, чтобы логгировались уже обработанные операции.

### Изоляция сервиса (AppArmor и SELinux)

**AppArmor (Профиль для Debian/Ubuntu):**
Профиль `/etc/apparmor.d/usr.sbin.smbd` должен ограничивать доступ только к путям шар:
```text
/srv/samba/shares/** rwk,
/var/lib/samba/** rwk,
/var/log/samba/** rwk,
/var/cache/samba/** rwk,
/run/samba/** rwk,
network inet stream,
network inet dgram,
```

Для проверки статуса:
```bash
sudo aa-status | grep smbd
# → /usr/sbin/smbd (enforced)
```

**SELinux (Контексты для RHEL/Alma):**
```bash
# Разрешение записи для Samba
sudo setsebool -P samba_export_all_rw on
sudo setsebool -P samba_share_all_rw on

# Установка контекста на директорию
sudo semanage fcontext -a -t samba_share_t "/srv/samba/shares(/.*)?"
sudo restorecon -Rv /srv/samba/shares
```

Детальный справочник булевых значений и модулей политики приведен в **[SELinux](../../../Security/Mechanisms/SELinux.md)**.

### Номера портов и exposure surface

Samba использует порты 445/TCP (SMB) и 139/TCP (NetBIOS Session Service). Рекомендуется закрыть 139/TCP и ограничить 445/TCP доверенными подсетями.

Дополнительные порты:
- **137/UDP** — NetBIOS Name Service (legacy).
- **138/UDP** — NetBIOS Datagram Service (legacy).
- **5357/TCP** — WSD Discovery (Windows 10/11).
- **5358/TCP** — WSD Hosting (не требуется для Samba).

## Практические сценарии

### 1. Полный харденинг сервера (Production Checklist)

Перед выводом сервера в production выполните:

```ini
[global]
   # Протокол и шифрование
   server min protocol = SMB3_11
   server smb encrypt = required
   client signing = mandatory
   server signing = mandatory

   # Отключение устаревших протоколов
   smb ports = 445
   map to guest = Never
   restrict anonymous = 2
   lanman auth = no
   ntlm auth = disabled

   # Ограничение exposure
   bind interfaces only = yes
   interfaces = 192.168.1.0/24
   hosts allow = 192.168.1.0/24 127.0.0.1
   hosts deny = 0.0.0.0/0

   # Сессии
   deadtime = 15
   max protocol = SMB3_11
   socket options = TCP_NODELAY IPTOS_LOWDELAY SO_RCVBUF=131072 SO_SNDBUF=131072
```

### 2. Настройка антивирусной проверки (ClamAV)

Требует установленного и запущенного демона `clamd`.

```ini
[secure_share]
   path = /srv/samba/secure
   vfs objects = virusfilter
   virusfilter:scanner = clamd
   virusfilter:socket = /var/run/clamav/clamd.ctl
   virusfilter:on_access = yes
   virusfilter:infected_file_action = quarantine
   virusfilter:quarantine_directory = /srv/samba/quarantine
   virusfilter:max file size = 104857600
   virusfilter:scan on open = yes
   virusfilter:scan on close = yes
```

**Валидация:**
```bash
# Проверка работы clamd
nc -z /var/run/clamav/clamd.ctl
# → Соединение установлено

# Проверка VFS-цепочки
testparm -s | grep -A 5 "\[secure_share\]"
# → vfs objects = virusfilter
```

### 3. Реализация снапшотов («Предыдущие версии»)

Пример для файловой системы Btrfs/ZFS, где снапшоты находятся в директории `.snapshots`.

```ini
[data]
   path = /srv/samba/data
   vfs objects = shadow_copy2
   shadow_copy2:mountpoint = /srv/samba/data
   shadow_copy2:snapshotsdir = .snapshots
   shadow_copy2:format = GMT-%Y.%m.%d-%H.%M.%S
   shadow_copy2:sort = desc
   shadow_copy2:snapdir = .snapshots
```

**Валидация:**
```bash
# Создание снапшота (Btrfs)
sudo btrfs subvolume snapshot -r /srv/samba/data /srv/samba/data/.snapshots/GMT-2026.09.12-10.00.00

# Проверка видимости в Windows
smbclient //server/data -U user
# → В контекстном меню "Предыдущие версии" появятся снапшоты
```

### 4. Глубокий аудит операций (Compliance)

Настройка для отслеживания удаления и изменения прав доступа. Подходит для соответствия ФЗ-152 и GDPR.

```ini
[audit_share]
   vfs objects = full_audit
   full_audit:prefix = %u|%I|%m|%S|%t
   full_audit:success = unlink chmod chown rename open close write
   full_audit:failure = connect disconnect
   full_audit:facility = LOCAL7
   full_audit:priority = NOTICE
   full_audit:log loglevel = 1
```

**Настройка rsyslog для分离 audit логов:**
```bash
# /etc/rsyslog.d/30-samba-audit.conf
if $programname == 'smbd_audit' then /var/log/samba/audit.log
& stop
```

**Валидация:**
```bash
# Проверка появления записей в аудит-логе
sudo tail -f /var/log/samba/audit.log
# → smbuser|192.168.1.10|SERVER|audit_share|2026/09/12 10:00:00|unlink|OK
```

### 5. Сетевая корзина (Recycle Bin)

Включает восстановление удаленных файлов конечными пользователями без доступа к root.

```ini
[RecycleBin]
   path = /srv/samba/secure
   vfs objects = recycle
   recycle:repository = .recycle/%U
   recycle:keeptree = yes
   recycle:versions = yes
   recycle:touch = yes
   recycle:directory_mode = 0700
   recycle:subdir_mode = 0700
```

### 6. Ограничение типов файлов

Блокировка исполняемых файлов и потенциально опасных форматов на шаре.

```ini
[PublicShare]
   path = /srv/samba/public
   vfs objects = full_audit perfile
   perfile:exclude = *.exe *.dll *.bat *.cmd *.ps1 *.vbs *.js *.scr *.pif
   perfile:exclude_dir = .snapshots .recycle
```

### 7. Настройка сетевого экрана (nftables)

Ограничение доступа к портам Samba только из доверенной подсети.

```bash
# /etc/nftables.d/samba.nft
table inet filter {
   chain input {
      type filter hook input priority filter; policy accept;
      tcp dport 445 ip saddr 192.168.1.0/24 accept
      tcp dport 445 ip saddr 10.0.0.0/8 accept
      tcp dport 139 ip saddr 192.168.1.0/24 accept
      tcp dport 445 drop
      tcp dport 139 drop
   }
}
```

**Для RHEL-based (firewalld):**
```bash
# Открытие порта только для доверенной зоны
sudo firewall-cmd --zone=trusted --add-service=samba --permanent
sudo firewall-cmd --zone=trusted --add-port=445/tcp --permanent
sudo firewall-cmd --reload
```

### 8. Защита от брутфорса (fail2ban)

Samba не имеет встроенной защиты от брутфорса. Используйте fail2ban:

```bash
# /etc/fail2ban/filter.d/samba.conf
[Definition]
failregex = (?i)^.*Failed login attempt.*from\s+<HOST>\s*$
            ^.*NT_STATUS_LOGON_FAILURE.*from\s+<HOST>\s*$
            ^.*NT_STATUS_WRONG_PASSWORD.*from\s+<HOST>\s*$

ignoreregex =
```

```bash
# /etc/fail2ban/jail.d/samba.conf
[samba]
enabled = true
port = 445,139
protocol = tcp
filter = samba
logpath = /var/log/samba/log.smbd
maxretry = 5
bantime = 3600
findtime = 600
```

**Валидация:**
```bash
# Проверка статуса jail
sudo fail2ban-client status samba
# → Status for the jail: samba
# → Filter list: samba
# → Currently banned: 1
```

### 9. Защита баз данных TDB

Базы данных Samba (TDB/LDB) содержат критичные данные: пароли компьютера, маппинги SID, секреты домена.

```bash
# Проверка целостности базы secrets
sudo tdbtool /var/lib/samba/private/secrets.tdb check

# Проверка прав доступа
ls -la /var/lib/samba/private/
# → drwx------ 2 root root ... secrets.tdb

# Резервное копирование
sudo tar -czf /backup/samba-tdb-$(date +%F).tar.gz /var/lib/samba/private/
```

**Права на критичные файлы:**
```bash
sudo chown root:root /var/lib/samba/private/secrets.tdb
sudo chmod 600 /var/lib/samba/private/secrets.tdb
sudo chown root:root /var/lib/samba/private/idmap.ldb
sudo chmod 600 /var/lib/samba/private/idmap.ldb
```

### 10. AppArmor профиль для Samba

На Debian/Ubuntu создайте кастомный профиль для повышения изоляции:

```text
# /etc/apparmor.d/usr.sbin.smbd
#include <abstractions/base>
#include <abstractions/nameservice>

/usr/sbin/smbd {
   # Основные права
   /proc/** r,
   /sys/** r,
   /etc/samba/** r,
   /var/lib/samba/** rwk,
   /var/log/samba/** rwk,
   /var/cache/samba/** rwk,
   /var/run/samba/** rwk,
   /run/samba/** rwk,
   /srv/samba/** rwk,

   # Сеть
   network inet stream,
   network inet dgram,
   network inet6 stream,
   network inet6 dgram,

   # Исполняемые файлы
   /usr/sbin/smbd mr,
   /usr/bin/* mr,
   /{bin,usr/bin,usr/local/bin}/* mr,

   # Запрет неиспользуемого
   deny /tmp/** rwk,
   deny /var/tmp/** rwk,
}
```

**Валидация:**
```bash
sudo apparmor_parser -a /etc/apparmor.d/usr.sbin.smbd
# → Syntax OK

sudo systemctl reload apparmor
sudo aa-status | grep smbd
# → /usr/sbin/smbd (enforced)
```

### 11. Квоты на разделы

Ограничение места для пользователей и групп через VFS-модуль `quota`:

```ini
[QuotaShare]
   path = /srv/samba/quota
   vfs objects = quota
   quota:show_sys_paths = yes
   quota:show_hidden_sys_paths = yes
```

**Установка квот на уровне ФС:**
```bash
# Для XFS
sudo xfs_quota -x -c 'limit bsoft=5G bhard=6G user1' /srv/samba/quota

# Для ext4
sudo setquota -u user1 5242880 6291456 0 0 /srv/samba/quota
```

### 12. Таймауты сессий и idle disconnect

Ограничение времени простоя сессий для снижения риска несанкционированного доступа:

```ini
[global]
   deadtime = 15
   map to guest = Never
   smb ports = 445

[SecureShare]
   path = /srv/samba/secure
   read only = no
   valid users = @secure_users
   veto files = /*.exe/*.dll/*.bat/*.cmd/
```

**Валидация:**
```bash
# Проверка активных сессий
smbstatus -S
# → Поле Idle time покажет время простоя

# Принудительное завершение сессии
smbstatus -b
# → Список PIDs для завершения
```

### 13. Сертификатная аутентификация (SMB over TLS)

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

### 14. Изоляция мультитенантных шар

Для провайдеров, размещающих данные разных клиентов на одном сервере:

```ini
[tenant_a]
   path = /srv/samba/tenant_a
   force user = tenant_a
   force group = tenant_a
   vfs objects = full_audit
   full_audit:prefix = %u|%I|%m|%S|%t
   full_audit:success = all
   full_audit:failure = all

[tenant_b]
   path = /srv/samba/tenant_b
   force user = tenant_b
   force group = tenant_b
   vfs objects = full_audit
   full_audit:prefix = %u|%I|%m|%S|%t
   full_audit:success = all
   full_audit:failure = all
```

## Мониторинг безопасности

### Проверка активного шифрования

```bash
# Просмотр статуса шифрования текущих сессий
smbstatus -v
# → Encryption: AES-256-GCM (Active)
# → Signing: Active (SMB 3.1.1)
```

### Анализ расширенных атрибутов (ACL)

Проверка того, как Samba хранит права Windows в Linux:
```bash
getfattr -d -m "user.SAMBA_PAI" /srv/samba/data/file.txt
```

### Мониторинг отказов SELinux/AppArmor

```bash
# SELinux: анализ AVC отказов
sudo ausearch -m avc -ts recent | grep smbd

# AppArmor: анализ отказов
sudo journalctl -u smbd | grep -i apparmor
```

### Интеграция с SIEM (rsyslog/syslog-ng)

Для централизованного сбора логов настройте экспорт в syslog:

```bash
# /etc/rsyslog.d/30-samba-security.conf
# Аудит операций
if $programname == 'smbd_audit' then /var/log/samba/audit.log
& stop

# Критические ошибки
if $programname == 'smbd' and $syslogseverity <= 3 then /var/log/samba/security.log
& stop

# Отправка на внешний SIEM (например, Graylog)
*.* @graylog.example.com:514
```

## Типовые ошибки безопасности

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `NT_STATUS_ACCESS_DENIED` | Пользователь не в `valid users` | Добавьте пользователя в параметр `valid users` или группу. |
| `NT_STATUS_BAD_NETWORK_NAME` | Шара не опубликована | Проверьте `browsable = yes` и `path` на существование. |
| `NT_STATUS_INVALID_PARAMETER` | Несоответствие SMB3.1.1 | Проверьте `server min protocol = SMB3_11` на клиенте и сервере. |
| `fruit:metadata` ошибка | macOS клиенты | Убедитесь, что `vfs objects = fruit streams_xattr` включен. |
| Нет доступа к файлам | Права ФС | `sudo -u nobody ls -l /path/to/share` — проверьте права ядра. |
| SELinux `Permission denied` | Неверный контекст | `restorecon -Rv /srv/samba/shares` или установка `samba_share_t`. |
| AppArmor `DENIED` | Недостаточно правил | Добавьте путь в профиль `/etc/apparmor.d/usr.sbin.smbd`. |
| AVC denied в audit.log | Политика SELinux | Сгенерируйте модуль через `audit2allow -M samba_fix && semodule -i samba_fix.pp`. |
| Шифрование неактивно | Клиент не поддерживает | Проверьте `server min protocol = SMB3_11` и версию Windows/macOS. |

## Дополнительная информация

### Проверка целостности баз данных

```bash
# Проверка базы secrets
sudo tdbtool /var/lib/samba/private/secrets.tdb check

# Проверка LDB баз
sudo ldbsearch -H /var/lib/samba/private/idmap.ldb
```

### См. также

- [Samba: Обзор](./index.md) — архитектура и стандарты 2026.
- [Samba: Настройка сервера](./samba_setup.md) — базовые параметры и производительность.
- [Samba: Интеграция с AD](./samba_ad.md) — управление пользователями и доменами.
- [Устранение неполадок](./samba_troubleshooting.md) — анализ ошибок доступа.
- [SIEM и комплаенс](./samba_siem.md) — аудит и безопасность.
- [Автоматизация (Ansible)](./samba_automation.md) — IaC для безопасной конфигурации.
- [Механизмы SELinux](../../../Security/Mechanisms/SELinux.md) — булевы значения и политики для Samba.
- [AppArmor: профилирование](../../../Security/Mechanisms/AppArmor.md) — управление профилями MAC.
- [Протокол Kerberos](../../../../Security/Concepts/kerberos.md) — аутентификация в доменах.
- [Безопасность сетевого уровня (nftables)](../../Settings/tools/nftables/architecture_and_concepts.md) — фильтрация трафика.
- [Ограничения хостинг-провайдеров на порты](../../../../Networking/Concepts/provider_port_restrictions.md) — блокировка портов SMB на VPS/дедиках и SMB over QUIC
