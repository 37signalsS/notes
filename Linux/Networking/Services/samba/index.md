# Samba: Обзор

## Определения

**Samba** — программный комплекс с открытым исходным кодом, реализующий протокол **SMB/CIFS** (Server Message Block / Common Internet File System). Позволяет Unix-подобным системам предоставлять общий доступ к файлам и принтерам для клиентов Windows, функционировать как член домена Active Directory, а также выступать в роли контроллера домена.

**SMB (Server Message Block)** — сетевой протокол для совместного использования файлов, принтеров и других ресурсов. Актуальная версия — SMBv3.1.1 с поддержкой шифрования AES-256.

**NetBIOS** — legacy-протокол для обнаружения и разрешения имен в локальных сетях. В современных реализациях заменен на DNS.

## Базовые концепции

### Архитектура Samba

| Демон | Назначение |
| :--- | :--- |
| **`smbd`** | Файловые ресурсы, аутентификация, авторизация, блокировки |
| **`nmbd`** | Разрешение имён NetBIOS (legacy) |
| **`winbindd`** | Интеграция с Active Directory, маппинг UID/GID |

### Режимы работы

| Режим | Параметр `security` | Описание |
| :--- | :--- | :--- |
| Standalone | `user` | Локальная аутентификация, без домена |
| Domain Member | `ads` | Член домена Active Directory с Kerberos |
| Domain Controller | `ads` + `server role = active directory domain controller` | Samba AD DC |

### Версии SMB

| Версия | Статус | Ключевые особенности |
| :--- | :--- | :--- |
| SMBv1 (CIFS) | **Запрещён** | Уязвимости (EternalBlue, WannaCry) |
| SMBv2.x | Устарела | Улучшенная производительность |
| SMBv3.0+ | **Рекомендуется** | Шифрование AES-256, Secure Dialect Negotiation |

> **Важно:** Всегда отключайте SMBv1. Минимальная версия: `server min protocol = SMB3`.

## Практические сценарии

- Предоставление сетевых шар для Windows/Linux клиентов
- Интеграция Linux-сервера в Active Directory
- Настройка гостевого и authenticated доступа
- Настройка ACL, аудита и корзины через VFS модули
- Миграция файловых серверов Windows → Linux

## Дополнительные сведения

### Основные конфигурационные файлы

| Файл | Описание |
| :--- | :--- |
| `/etc/samba/smb.conf` | Главный конфигурационный файл |
| `/var/lib/samba/private/smbpasswd` | База паролей Samba |
| `/etc/krb5.conf` | Конфигурация Kerberos (для AD) |

### Порты

| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| 445 | TCP | SMB over TCP (основной) |
| 137-139 | TCP/UDP | NetBIOS (legacy) |

### Ключевые утилиты

- `testparm` — проверка конфигурации
- `smbclient` — CLI-клиент для SMB
- `smbstatus` — просмотр активных сессий
- `pdbedit` / `smbpasswd` — управление пользователями
- `net ads` — управление членством в домене

### Документация по теме

- [Настройка сервера](./samba_setup.md)
- [Безопасность и VFS](./samba_security.md)
- [Интеграция с AD](./samba_ad.md)
- [Устранение неполадок](./samba_troubleshooting.md)

## Смотрите также

- [NFS](../nfs/index.md)
- [Kerberos](../../../../Security/Concepts/kerberos.md)
- [Монтирование CIFS](../../../FileSystems/mounting/fstab.md)
