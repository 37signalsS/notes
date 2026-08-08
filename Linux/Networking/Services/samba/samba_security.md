# Samba: Безопасность и VFS-модули

## Определения

**VFS (Virtual File System) modules** — расширяемые модули Samba, подключаемые к сетевым ресурсам (шарам) для добавления функциональности: аудит, корзина, снапшоты, антивирусная проверка. Указываются в директиве `vfs objects`.

**SMB Encryption** — шифрование трафика на уровне протокола SMB (AES-256-GCM в SMBv3.1.1). Защищает данные от перехвата и модификации (MitM).

**POSIX ACL vs NTFS ACL** — взаимодействие прав доступа Linux и Windows. Samba использует расширенные атрибуты (`xattr`) для хранения полнофункциональных дескрипторов безопасности Windows поверх файловой системы Linux.

**Zero Trust SMB** — архитектурный подход, требующий обязательного шифрования (`smb encrypt = required`), сильной аутентификации (Kerberos) и строгой изоляции сервиса.

## Базовые концепции

### Безопасность протокола (Стандарты 2026)

| Параметр | Назначение | Рекомендация 2026 |
| :--- | :--- | :--- |
| **`server min protocol`** | Минимальная версия SMB | **`SMB3_11`** |
| **`smb encrypt`** | Шифрование трафика | **`required`** (обязательно для всех) |
| **`ntlm auth`** | Тип NTLM-аутентификации | **`disabled`** (в пользу Kerberos) |
| **`restrict anonymous`** | Ограничение анонимного доступа | **`2`** (полный запрет) |
| **`lanman auth`** | Устаревшая аутентификация | **`no`** |

### Виртуальная файловая система (VFS)

Использование нескольких модулей требует соблюдения порядка (справа налево в цепочке вызовов).

| Модуль | Описание | Применение |
| :--- | :--- | :--- |
| **`acl_xattr`** | Хранение ACL в атрибутах | Обеспечивает полноценную работу прав Windows. |
| **`fruit`** | Оптимизация для macOS | Обязателен для предотвращения утечек метаданных Apple. |
| **`shadow_copy2`** | Снапшоты | Реализация «Предыдущих версий» Windows. |
| **`virusfilter`** | Антивирус | Онлайн-сканирование через ClamAV/Sophos. |
| **`full_audit`** | Аудит | Логирование операций (соответствие ФЗ/GDPR). |

### Изоляция сервиса (AppArmor и SELinux)

**AppArmor (Профиль для Debian/Ubuntu):**
Профиль `/etc/apparmor.d/usr.sbin.smbd` должен ограничивать доступ только к путям шар:
```text
/srv/samba/shares/** rwk,
/var/lib/samba/** rwk,
```

**SELinux (Контексты для RHEL/Alma):**
```bash
# Разрешение записи для Samba
sudo setsebool -P samba_export_all_rw on
# Установка контекста на директорию
sudo chcon -t samba_share_t /srv/samba/data
```

## Практические сценарии

### 1. Настройка антивирусной проверки (ClamAV)

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
```

### 2. Реализация снапшотов («Предыдущие версии»)

Пример для файловой системы Btrfs/ZFS, где снапшоты находятся в директории `.snapshots`.

```ini
[data]
   path = /srv/samba/data
   vfs objects = shadow_copy2
   shadow_copy2:mountpoint = /srv/samba/data
   shadow_copy2:snapshotsdir = .snapshots
   shadow_copy2:format = GMT-%Y.%m.%d-%H.%M.%S
   shadow_copy2:sort = desc
```

### 3. Глубокий аудит операций

Настройка для отслеживания удаления и изменения прав доступа.

```ini
[audit_share]
   vfs objects = full_audit
   full_audit:prefix = %u|%I|%m|%S
   full_audit:success = unlink chmod chown rename
   full_audit:failure = connect
   full_audit:facility = LOCAL7
   full_audit:priority = NOTICE
```

### 4. Настройка сетевого экрана (nftables)

Ограничение доступа к портам Samba только из доверенной подсети.

```text
table inet filter {
    chain input {
        tcp dport 445 ip saddr 192.168.1.0/24 accept
        tcp dport 445 drop
    }
}
```

## Мониторинг безопасности

### Проверка активного шифрования

```bash
# Просмотр статуса шифрования текущих сессий
smbstatus -v
# → Encryption: AES-256-GCM (Active)
```

### Анализ расширенных атрибутов (ACL)

Проверка того, как Samba хранит права Windows в Linux:
```bash
getfattr -d -m "user.SAMBA_PAI" /srv/samba/data/file.txt
```

## Дополнительная информация

- [Samba: Обзор](./index.md) — архитектура и стандарты.
- [Samba: Настройка сервера](./samba_setup.md) — базовые параметры.
- [Samba: Интеграция с AD](./samba_ad.md) — управление пользователями.
- [Устранение неполадок](./samba_troubleshooting.md) — анализ ошибок доступа.

## См. также

- [Механизмы SELinux](../../../Security/Mechanisms/SELinux.md)
- [AppArmor: профилирование](../../../Security/Mechanisms/AppArmor.md)
- [Протокол Kerberos](../../../../Security/Concepts/kerberos.md)
- [Безопасность сетевого уровня (nftables)](../../Settings/tools/nftables/architecture_and_concepts.md)
