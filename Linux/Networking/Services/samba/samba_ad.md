# Samba: Интеграция с Active Directory

## Определения

**Samba AD Member** — режим работы Samba как члена домена Active Directory с использованием Kerberos для аутентификации и winbind для маппинга пользователей.

**winbind** — сервис, обеспечивающий интеграцию между Linux и Windows-доменами: маппинг UID/GID ↔ SID, получение списков пользователей/групп из AD.

**idmap** — подсистема Samba для маппинга идентификаторов безопасности Windows (SID) на Unix-идентификаторы (UID/GID). Централизованное управление UID/GID критично для корректной работы в домене.

## Базовые концепции

### Требования

- Настроенный домен Active Directory.
- Синхронизация времени (Kerberos требует точного времени, расхождение ≤5 минут).
- Пакет `winbind`.

### Уровни безопасности (`security`)

| Режим | Описание |
| :--- | :--- |
| `security = user` | Стандартный режим, локальная аутентификация |
| `security = ads` | Член домена Active Directory, Kerberos |
| `security = domain` | Устаревший режим для NT4-доменов |

### Бэкенды idmap

| Бэкенд | Описание | Использование |
| :--- | :--- | :--- |
| `tdb` | Локальная база (trivial database) | Для локальных пользователей (`*`) |
| `rid` | Маппинг на основе RID домена | Для доменных пользователей |
| `ad` | Маппинг из атрибутов AD (uidNumber/gidNumber) | Для сложных схем с RFC2307 |
| `autorid` | Автоматическое выделение диапазонов | Для нескольких доменов |

### Принципы маппинга UID/GID

Без централизованного управления UID/GID возможны конфликты прав доступа. Диапазоны должны быть непересекающимися:

- `*` (локальные пользователи): 3000–7999
- `EXAMPLE` (основной домен): 10000–999999
- `TRUSTED` (доверенные домены): 2000000–2999999

## Практические сценарии

### Установка пакетов

```bash
# Debian/Ubuntu
sudo apt-get install -y samba winbind libnss-winbind libpam-winbind

# RHEL/CentOS
sudo yum install -y samba-winbind samba-winbind-clients
```

### Конфигурация (`/etc/samba/smb.conf`)

```ini
[global]
   workgroup = EXAMPLE
   realm = EXAMPLE.COM
   security = ADS
   encrypt passwords = yes
   kerberos method = secrets and keytab

   # ID mapping (важно для корректного маппинга UID/GID)
   idmap config * : backend = tdb
   idmap config * : range = 3000-7999
   idmap config EXAMPLE : backend = rid
   idmap config EXAMPLE : range = 10000-999999

   winbind use default domain = yes
   winbind offline logon = yes
```

### Присоединение к домену

```bash
# Присоединение к домену
sudo net ads join -U Administrator
# → Joined 'SERVER' to dns domain 'example.com'

# Проверка подключения
net ads testjoin
# → Join is OK

# Запуск служб
sudo systemctl enable --now smb nmb winbind
```

### Настройка NSS и PAM

**`/etc/nsswitch.conf`:**

```yaml
passwd:         compat winbind
group:          compat winbind
shadow:         compat
```

**PAM (автоматическое создание домашних директорий):**

```bash
sudo pam-auth-update
```

### Проверка и диагностика

```bash
# Информация о домене
net ads info
# → LDAP server: 192.168.1.10 ...

# Список пользователей домена
wbinfo -u
# → administrator, user1, user2...

# Список групп домена
wbinfo -g
# → domain users, domain admins...

# Проверка маппинга UID/GID
getent passwd "EXAMPLE\user1"
# → user1:*:10001:10000:User One:/home/EXAMPLE/user1:/bin/bash

# Проверка билета Kerberos
klist
# → Default principal: user1@EXAMPLE.COM
```

## Дополнительная информация

- [Обзор Samba](./index.md) — архитектура и версии протокола
- [Настройка сервера](./samba_setup.md) — базовые шаги конфигурации
- [Интеграция через SSSD](../../../SystemAdministration/Users/LDAP_SSSD/index.md) — современная альтернатива Winbind
- [Протокол Kerberos](../../../../Security/Concepts/kerberos.md) — основы сетевой аутентификации
- [Управление пользователями](../../../SystemAdministration/users_management.md) — настройка NSS/PAM
