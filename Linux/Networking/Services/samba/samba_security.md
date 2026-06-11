# Samba: Безопасность и VFS-модули

> **Надежность: 10** (Подтверждено официальной документацией Samba и практическими сценариями)

## Определения

**VFS (Virtual File System) modules** — расширяемые модули Samba, подключаемые к сетевым ресурсам (шарам) для добавления функциональности: аудит, корзина, снапшоты, антивирусная проверка. Указываются в директиве `vfs objects` без префикса `vfs_`.

**SMB encryption** — шифрование трафика на уровне протокола SMB (AES-256 в SMBv3+). Обеспечивает защиту данных при передаче, не зависит от TLS/IPsec.

## Базовые концепции

### Безопасность протокола

| Параметр | Назначение | Рекомендация |
| :--- | :--- | :--- |
| `server min protocol` | Минимальная версия SMB | `SMB3` |
| `server max protocol` | Максимальная версия SMB | `SMB3_11` |
| `smb encrypt` | Шифрование трафика | `required` (обязательное) или `auto` (по выбору клиента) |
| `ntlm auth` | Тип NTLM-аутентификации | `ntlmv2-only` |
| `map to guest` | Гостевой доступ | `Never` (по умолчанию), `bad user` — только для публичных шар |
| `restrict anonymous` | Анонимные запросы | `2` |

> **Важно:** Параметры `read raw`, `write raw`, `max xmit`, `getwd cache`, `strict allocate`, `strict sync` удалены в Samba 4.x — они относились к SMB1 и не применяются к современным версиям протокола.

### VFS-модули

| Модуль | Описание |
| :--- | :--- |
| `audit` | Базовый аудит операций (устаревший, заменён на `full_audit`) |
| `full_audit` | Расширенный аудит с логированием успешных и неудачных операций |
| `recycle` | Корзина — перемещение удалённых файлов в специальную директорию |
| `shadow_copy2` | Интеграция со снапшотами файловой системы (VSS для Windows-клиентов) |
| `virusfilter` | Проверка файлов антивирусом при записи на сервер |
| `acl_xattr` | Хранение Windows ACL в расширенных атрибутах файлов (xattr) |
| `zfsacl` | Нативная поддержка ACL для файловой системы ZFS |

### Контексты SELinux

Для дистрибутивов семейства RHEL (Red Hat Enterprise Linux) требуется установка контекста `samba_share_t` на директории сетевых ресурсов. Параметр `samba_enable_home_dirs` управляет доступом к домашним каталогам пользователей.

## Практические сценарии

### Минимальная безопасная конфигурация

Пример настройки в секции `[global]` файла `/etc/samba/smb.conf`:

```ini
[global]
   server min protocol = SMB3
   server max protocol = SMB3_11
   ntlm auth = ntlmv2-only
   smb encrypt = required
   map to guest = Never
   restrict anonymous = 2
```

### Настройка аудита и корзины для шары

```ini
[secure_share]
   path = /srv/samba/secure
   vfs objects = full_audit recycle
   full_audit:success = open mkdir rename unlink
   full_audit:failure = open mkdir
   full_audit:prefix = %u|%I|%m|%S
   recycle:repository = /srv/samba/.recycle/%U
   recycle:keeptree = yes
   recycle:versions = yes
```

### Настройка контекстов SELinux

```bash
# Временная установка контекста
sudo chcon -t samba_share_t /srv/samba/public/

# Постоянная установка через semanage
sudo semanage fcontext -a -t samba_share_t '/srv/samba/public(/.*)?'
sudo restorecon -Rv /srv/samba/public/
# → restorecon reset /srv/samba/public context ...

# Разрешение доступа к домашним директориям
sudo setsebool -P samba_enable_home_dirs on
```

### Расширенное логирование и аудит

Глобальные настройки логирования:

```ini
[global]
   log level = 2
   log file = /var/log/samba/%m.log
   max log size = 10000
```

Аудит операций записи и прав доступа:

```ini
[audited_share]
   path = /srv/samba/audited
   vfs objects = full_audit
   full_audit:success = open mkdir rename unlink chmod chown
   full_audit:failure = open mkdir
   full_audit:prefix = %u|%I|%m|%S
```

### Диагностика активных подключений

```bash
# Список текущих сессий
smbstatus
# → Samba version 4.15.13-Ubuntu
# → PID     Username     Group        Machine
# → 1234    user1        users        192.168.1.50 (ipv4:192.168.1.50:5678)

# Статистика по сетевым ресурсам
smbstatus -S

# Подробный вывод с информацией о блокировках файлов
smbstatus -v
```

## Дополнительная информация

- [Обзор Samba](./index.md) — общая архитектура и версии протокола
- [Настройка сервера](./samba_setup.md) — базовые параметры конфигурации
- [Интеграция с AD](./samba_ad.md) — работа в домене Active Directory
- [Устранение неполадок](./samba_troubleshooting.md) — отладка и чтение логов

## Смотрите также

- [Механизмы SELinux](../../../Security/Mechanisms/SELinux.md)
- [firewalld](../../Settings/tools/firewalld.md)
- [nftables](../../Settings/tools/nftables/practical_scenarios.md)
