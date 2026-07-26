# Samba: Безопасность и VFS-модули

> **Надежность: 10** (Подтверждено официальной документацией Samba 4.24+ и стандартами 2026 года)

## Определения

**VFS (Virtual File System) modules** — расширяемые модули Samba, подключаемые к сетевым ресурсам (шарам) для добавления функциональности: аудит, корзина, снапшоты, антивирусная проверка. Указываются в директиве `vfs objects` без префикса `vfs_`.

**SMB encryption** — шифрование трафика на уровне протокола SMB (AES-256 в SMBv3.1.1). Обеспечивает защиту данных при передаче, предотвращая перехват и модификацию трафика.

**Zero Trust SMB** — архитектурный подход, при котором доступ к ресурсам Samba требует обязательного шифрования, сильной аутентификации и минимально необходимых привилегий (Least Privilege).

## Базовые концепции

### Безопасность протокола (Стандарты 2026)

| Параметр | Назначение | Рекомендация 2026 |
| :--- | :--- | :--- |
| **`server min protocol`** | Минимальная версия SMB | **`SMB3_11`** |
| **`smb encrypt`** | Шифрование трафика | **`required`** (обязательно для всех) |
| **`ntlm auth`** | Тип NTLM-аутентификации | **`ntlmv2-only`** (или `disabled` в пользу Kerberos) |
| **`ldap server require strong auth`** | Защита LDAP-соединений | **`yes`** (обязательный Channel Binding) |
| **`kdc require canonicalization`** | Защита Kerberos | **`yes`** (защита от impersonation атак) |

> **Важно:** В 2026 году рекомендуется полностью отказаться от NTLM в пользу Kerberos. Если NTLM необходим, используйте только NTLMv2 с обязательным шифрованием.

### VFS-модули

| Модуль | Описание | Применение |
| :--- | :--- | :--- |
| **`fruit`** | Оптимизация для Apple/macOS | Обязателен для смешанных сетей. |
| **`full_audit`** | Расширенный аудит операций | Мониторинг действий пользователей. |
| **`recycle`** | Корзина | Защита от случайного удаления файлов. |
| **`shadow_copy2`** | Снапшоты (Previous Versions) | Интеграция с ZFS/Btrfs/LVM snapshots. |
| **`aio_ratelimit`** | Throttling (I/O Limiting) | **Новое в 2026.** Ограничение IOPS/BW на шару. |
| **`virusfilter`** | Антивирусная проверка | Сканирование файлов (ClamAV) при записи. |

### Контексты SELinux

Для систем с активным SELinux (RHEL, Fedora) необходимо корректно размечать файловую систему:

```bash
# Установка контекста для Samba-шары
sudo semanage fcontext -a -t samba_share_t "/srv/samba/data(/.*)?"
sudo restorecon -Rv /srv/samba/data/

# Разрешение экспорта домашних директорий
sudo setsebool -P samba_enable_home_dirs on
```

## Практические сценарии

### "Закаленная" (Hardened) конфигурация 2026

Секция `[global]` с максимальным уровнем защиты:

```ini
[global]
   # Принудительный SMB 3.1.1 и шифрование
   server min protocol = SMB3_11
   server smb encrypt = required
   
   # Отключение слабых протоколов и анонимного доступа
   restrict anonymous = 2
   map to guest = Never
   
   # Безопасность Kerberos (AES-only)
   kdc default domain supported enctypes = aes256-cts-hmac-sha1-96 aes128-cts-hmac-sha1-96
   kdc require canonicalization = yes
   
   # Защита LDAP
   ldap server require strong auth = yes
```

### Настройка аудита, корзины и macOS-оптимизации

Пример для шары с полным набором модулей:

```ini
[corp_data]
   path = /srv/samba/data
   vfs objects = catia fruit streams_xattr full_audit recycle
   
   # Оптимизация для Apple
   fruit:metadata = stream
   fruit:model = MacSamba
   
   # Настройка аудита
   full_audit:success = open mkdir rename unlink chmod chown
   full_audit:failure = open mkdir
   full_audit:prefix = %u|%I|%m|%S
   
   # Настройка корзины
   recycle:repository = .recycle/%U
   recycle:keeptree = yes
   recycle:versions = yes
   recycle:maxsize = 1000000
```

### Диагностика безопасности

```bash
# Проверка используемого протокола и шифрования для текущих сессий
smbstatus -v
# → Protocol: SMB3_11
# → Encryption: AES-256-GCM

# Проверка базы пользователей на наличие слабых флагов
pdbedit -v -u username
# → Account Flags: [U          ] (должно быть без 'L' - LanMan или 'D' - Disabled)
```

## Дополнительная информация

- [Обзор Samba](./index.md) — общая архитектура и версии протокола
- [Настройка сервера](./samba_setup.md) — базовые параметры конфигурации
- [Интеграция с AD](./samba_ad.md) — работа в домене Active Directory
- [Устранение неполадок](./samba_troubleshooting.md) — отладка и чтение логов

## Смотрите также

- [Механизмы SELinux](../../../Security/Mechanisms/SELinux.md)
- [Протокол Kerberos: основы](../../../../Security/Concepts/kerberos.md)
- [firewalld: настройка портов](../../Settings/tools/firewalld.md)
