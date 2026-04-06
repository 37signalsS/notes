# Samba: Security and VFS Modules

## Definitions

**VFS (Virtual File System) modules** — расширяемые модули Samba, подключаемые к шарам для добавления функциональности: аудит, корзина, снапшоты, антивирусная проверка. Указываются в директиве `vfs objects` без префикса `vfs_`.

**SMB encryption** — шифрование трафика на уровне SMB-протокола (AES-256 в SMBv3+). Не зависит от TLS/IPsec, согласуется между клиентом и сервером.

## Basic Concepts

### Безопасность протокола

| Параметр | Назначение | Рекомендация |
| :--- | :--- | :--- |
| `server min protocol` | Минимальная версия SMB | `SMB3` |
| `server max protocol` | Максимальная версия SMB | `SMB3_11` |
| `smb encrypt` | Шифрование трафика | `required` (обязательное) или `auto` (по выбору клиента) |
| `ntlm auth` | Тип NTLM-аутентификации | `ntlmv2-only` |
| `map to guest` | Гостевой доступ | `Never` (по умолчанию), `bad user` — только для публичных шар |
| `restrict anonymous` | Анонимные запросы | `2` |

> **Важно:** Параметры `read raw`, `write raw`, `max xmit`, `getwd cache`, `strict allocate`, `strict sync` удалены в Samba 4.x — они относились к SMB1 и не применяются к SMB2/SMB3.

### VFS-модули

| Модуль | Описание |
| :--- | :--- |
| `audit` | Базовый аудит операций (устаревший, заменён на `full_audit`) |
| `full_audit` | Расширенный аудит с логированием success/failure |
| `recycle` | Корзина — перемещение удалённых файлов вместо удаления |
| `shadow_copy2` | Интеграция со снапшотами ФС (Volume Shadow Copy для Windows-клиентов) |
| `virusfilter` | Проверка файлов антивирусом при записи |
| `acl_xattr` | Хранение Windows ACL в extended attributes |
| `zfsacl` | Поддержка ACL на ZFS |

### SELinux контексты

Для RHEL/CentOS/Fedora требуется контекст `samba_share_t` на директориях шар. Булевы `samba_enable_home_dirs` — доступ к домашним каталогам.

## Practical Scenarios

### Минимальная безопасная конфигурация

```ini
[global]
   server min protocol = SMB3
   server max protocol = SMB3_11
   ntlm auth = ntlmv2-only
   smb encrypt = required
   map to guest = Never
   restrict anonymous = 2
```

### Шара с аудитом и корзиной

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

### Шара со снапшотами (shadow_copy2)

```ini
[snapshots]
   path = /srv/data
   vfs objects = shadow_copy2
   shadow:snapdir = /srv/data/.snapshots
   shadow:format = auto-%Y-%m-%d_%H:%M:%S
   shadow:sort = desc
   shadow:localtime = yes
```

### SELinux — настройка контекстов

```bash
# Временная установка
sudo chcon -t samba_share_t /srv/samba/public/

# Постоянное (через semanage)
sudo semanage fcontext -a -t samba_share_t '/srv/samba/public(/.*)?'
sudo restorecon -Rv /srv/samba/public/

# Доступ к домашним директориям
sudo setsebool -P samba_enable_home_dirs on
```

### Расширенное логирование

```ini
[global]
   log level = 2
   log file = /var/log/samba/%m.log
   max log size = 10000
```

Аудит на уровне шары:

```ini
[audited_share]
   path = /srv/samba/audited
   vfs objects = full_audit
   full_audit:success = open mkdir rename unlink chmod chown
   full_audit:failure = open mkdir
   full_audit:prefix = %u|%I|%m|%S
```

### Диагностика подключений

```bash
smbstatus              # Активные подключения
smbstatus -S           # Статистика по шарам
smbstatus -v           # Подробный вывод с блокировками
```

## Additional Information

Связанные документы: [обзор Samba](./index.md), [настройка сервера](./samba_setup.md), [AD-интеграция](./samba_ad.md), [устранение неполадок](./samba_troubleshooting.md). SELinux: [механизмы SELinux](../../../Security/Mechanisms/SELinux.md). Файрволы: [firewalld](../../../Settings/tools/firewalld.md), [nftables](../../../Settings/tools/nftables/practical_scenarios.md).
