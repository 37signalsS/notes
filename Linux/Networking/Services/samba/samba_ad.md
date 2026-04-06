# Samba: Интеграция с Active Directory

## Definitions

**Samba AD Member** — режим работы Samba как члена домена Active Directory с использованием Kerberos для аутентификации и winbind для маппинга пользователей.

**winbind** — сервис, обеспечивающий интеграцию между Linux и Windows-доменами: маппинг UID/GID ↔ SID, получение списков пользователей/групп из AD.

**idmap** — подсистема Samba для маппинга идентификаторов безопасности Windows (SID) на Unix-идентификаторы (UID/GID). Централизованное управление UID/GID критично для корректной работы в домене.

## Basic Concepts

### Требования

- Настроенный домен Active Directory
- Синхронизация времени (Kerberos требует точного времени, расхождение ≤5 минут)
- Пакет `winbind`

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

## Practical Scenarios

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

# Проверка подключения
net ads testjoin

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

# Список пользователей домена
wbinfo -u
getent passwd

# Список групп домена
wbinfo -g
getent group

# Проверка маппинга UID/GID
wbinfo --uid-to-sid 10000
wbinfo --sid-to-uid S-1-5-21-...

# Проверка билета Kerberos
klist
```

## Additional Information

- [Обзор Samba (SSoT)](./index.md) — архитектура, версии SMB, режимы работы
- [Настройка Samba](./samba_setup.md) — конфигурация шар и доступов
- [Kerberos: централизованная аутентификация](../../../../Security/Concepts/kerberos.md) — протокол аутентификации AD
- [Управление пользователями](../../../SystemAdministration/users_management.md) — NSS/PAM конфигурация
