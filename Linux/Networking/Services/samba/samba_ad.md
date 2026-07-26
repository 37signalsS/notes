# Samba: Интеграция с Active Directory

## Определения

**Samba AD Member** — режим работы Samba как члена домена Active Directory с использованием Kerberos для аутентификации и winbind для маппинга пользователей.

**winbind** — сервис, обеспечивающий интеграцию между Linux и Windows-доменами: маппинг UID/GID ↔ SID, получение списков пользователей/групп из AD.

**idmap** — подсистема Samba для маппинга идентификаторов безопасности Windows (SID) на Unix-идентификаторы (UID/GID). Централизованное управление UID/GID критично для корректной работы в домене.

**SSPR (Self-Service Password Reset)** — (Новое в 2026) возможность сброса паролей пользователями через веб-интерфейс (Keycloak/Entra ID), который интегрируется с политиками паролей Samba.

## Базовые концепции

### Требования

- Настроенный домен Active Directory (Windows Server 2016+ или Samba AD DC).
- Синхронизация времени через **Chrony** или **NTP** (расхождение Kerberos ≤5 минут).
- Пакеты `winbind` и `libnss-winbind`.

### Уровни безопасности и Hardening (Стандарты 2026)

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `security = ads` | Член домена Active Directory | Обязательно для AD. |
| **`kerberos method`** | Метод проверки билетов | `secrets and keytab` |
| **`kdc require canonicalization`** | Защита от impersonation | `yes` |
| **`client signing`** | Подпись SMB-трафика клиентом | `required` |

### Бэкенды idmap

| Бэкенд | Описание | Применение |
| :--- | :--- | :--- |
| `tdb` | Локальная база данных | Для локальных SID (`*`). |
| `rid` | Алгоритмический маппинг | Рекомендуется для одиночных доменов. |
| `ad` | Чтение атрибутов из AD | RFC2307 (uidNumber/gidNumber). |
| `autorid` | Автоматическое выделение | Для лесов с множеством доменов. |

## Практические сценарии

### Установка пакетов (Modern)

```bash
# Debian/Ubuntu 24.04+
sudo apt-get install -y samba winbind libnss-winbind libpam-winbind krb5-user

# RHEL/AlmaLinux 9+
sudo dnf install -y samba-winbind samba-winbind-clients krb5-workstation
```

### Конфигурация члена домена (`/etc/samba/smb.conf`)

Пример с использованием бэкенда `rid` и усиленной безопасностью.

```ini
[global]
   workgroup = EXAMPLE
   realm = EXAMPLE.COM
   security = ADS
   
   # Безопасность Kerberos 2026
   kerberos method = secrets and keytab
   kdc require canonicalization = yes
   client signing = required
   
   # ID mapping
   idmap config * : backend = tdb
   idmap config * : range = 3000-7999
   idmap config EXAMPLE : backend = rid
   idmap config EXAMPLE : range = 10000-999999

   winbind use default domain = yes
   winbind offline logon = yes
   winbind refresh tickets = yes
```

### Присоединение к домену

```bash
# Инициализация Kerberos тикета администратора
kinit Administrator@EXAMPLE.COM

# Присоединение (создание учетной записи компьютера и keytab)
sudo net ads join -U Administrator
# → Joined 'SAMBA-SRV' to dns domain 'example.com'

# Проверка статуса
net ads testjoin
# → Join is OK
```

### Настройка NSS и PAM

**`/etc/nsswitch.conf`** (добавление winbind):

```yaml
passwd:         compat winbind
group:          compat winbind
```

**PAM (автоматическое создание домашних директорий при входе):**

```bash
# Для Debian/Ubuntu
sudo pam-auth-update --enable mkhomedir
```

### Диагностика AD интеграции

```bash
# Проверка связи с DC и параметров домена
net ads info

# Проверка работы winbind (список пользователей домена)
wbinfo -u

# Проверка разрешения имен пользователей через ОС
getent passwd "EXAMPLE\user1"
# → user1:*:10001:10000:User One:/home/EXAMPLE/user1:/bin/bash

# Просмотр билетов Kerberos в кеше
klist
```

## Дополнительная информация

- [Обзор Samba](./index.md) — архитектура и версии протокола
- [Настройка сервера](./samba_setup.md) — базовые шаги конфигурации
- [Интеграция через SSSD](../../../SystemAdministration/Users/LDAP_SSSD/index.md) — современная альтернатива Winbind
- [Протокол Kerberos](../../../../Security/Concepts/kerberos.md) — основы сетевой аутентификации
- [Управление пользователями](../../../SystemAdministration/users_management.md) — общие принципы Linux
