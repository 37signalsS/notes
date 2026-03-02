# Централизованное управление (LDAP, SSSD)

В крупных инфраструктурах локальное управление пользователями на каждой машине неэффективно. Вместо этого используется централизованная служба каталогов.

## LDAP (Lightweight Directory Access Protocol)

**Определение:** LDAP (Lightweight Directory Access Protocol) — это протокол доступа к распределённой иерархической базе данных. Он используется для организации централизованного хранения и доступа к информации о пользователях, группах, компьютерах и других сетевых ресурсах.

- **Принцип работы:** Linux-системы настраиваются так, чтобы запрашивать информацию о пользователях и выполнять аутентификацию через сеть у центрального сервера, такого как **OpenLDAP** или **Microsoft Active Directory**. Протокол использует TCP-порт 389.
- **Использование:** Применяется для аутентификации пользователей и авторизации доступа к различным сервисам и системам.

- **Ключевые технологии:**
- **NSS (Name Service Switch):** Механизм, позволяющий системе получать информацию о пользователях/группах не только из `/etc/passwd`, но и из других источников (например, из сети).
- **PAM (Pluggable Authentication Modules):** Гибкая система аутентификации, позволяющая подключать различные модули для проверки подлинности. Подробнее см. в [PAM (Pluggable Authentication Modules)](../Security/pam_overview.md).
- **SSSD (System Security Services Daemon):** Современный стандартный демон на Linux-клиентах, который подключается к службе каталогов, управляет аутентификацией и **кэширует учетные данные**, позволяя входить в систему даже при отсутствии сети.

## Настройка SSSD для LDAP

**Установка пакетов:**

```bash
# Rocky Linux / RHEL / CentOS
dnf install sssd oddjob-mkhomedir sssd-ldap openldap-clients

# Debian / Ubuntu
apt install sssd oddjob-mkhomedir sssd-ldap openldap-clients
```

**Добавление CA-сертификата в доверенные:**

```bash
# Скопировать CA-сертификат
cp ldap-ca.crt /usr/local/share/ca-certificates/

# Обновить хранилище сертификатов
update-ca-certificates
```

**Настройка `/etc/sssd/sssd.conf`:**

```ini
[sssd]
services = nss, pam
config_file_version = 2
domains = ldap

[nss]
filter_groups = root
filter_users = root

[pam]
offline_credentials_expiration = 7

[domain/ldap]
id_provider = ldap
auth_provider = ldap
chpass_provider = ldap

# DN для подключения к LDAP
binddn = cn=admin,dc=example,dc=com
bindpw = password

# URL LDAP-сервера (LDAPS)
ldap_uri = ldaps://ldap.example.com:636

# LDAP search base
ldap_search_base = dc=example,dc=com

# Схема LDAP
ldap_schema = rfc2307

# User/Group search bases
ldap_user_search_base = ou=users,dc=example,dc=com?one?objectClass=posixAccount
ldap_group_search_base = ou=groups,dc=example,dc=com?one?objectClass=posixGroup

# Атрибуты пользователя
ldap_user_uid_number = uidNumber
ldap_user_gid_number = gidNumber
ldap_user_home_directory = homeDirectory
ldap_user_shell = loginShell

# Фильтр пользователей
ldap_user_filter = (objectClass=posixAccount)

# Кэширование
cache_credentials = true
enumerate = false
```

**Настройка автоматического создания домашней директории:**

```bash
# Включить и запустить сервисы
systemctl enable --now oddjobd
systemctl enable --now sssd
```

**Проверка:**

```bash
# Посмотреть пользователей из LDAP
getent passwd

# Посмотреть группы из LDAP
getent group
```

**Важно:**
- При использовании SSL/TLS необходимо добавить CA-сертификат в систему
- Для смены пароля требуется настроенный `chpass_provider = ldap`
- Пароль binddn хранится в открытом виде в конфигурации

См. также:
* [PAM (Pluggable Authentication Modules)](../../Security/pam_overview.md)
* [Определения](./users_definitions.md)
* [389DS — LDAP сервер](../../../LDAP/389ds/overview.md) — развёртывание LDAP-сервера
* [OpenLDAP в Kubernetes](../../../LDAP/openldap_kubernetes.md) — альтернативная реализация LDAP
