# Конфигурация LDAP и SSSD

## Определения

**Конфигурация LDAP/SSSD** — установка и настройка интеграции Linux с LDAP-серверами через SSSD.

> **Навигация:** [Главная LDAP_SSSD](./index.md) | [Операции](./operations.md)

---

## Practical Scenarios

### Установка пакетов

```bash
# Rocky Linux / RHEL / CentOS / AlmaLinux
dnf install sssd sssd-ldap oddjob-mkhomedir

# Debian / Ubuntu
apt install sssd sssd-ldap libnss-sssd libpam-sssd
```

---

### Настройка TLS/SSL

```bash
# Копирование CA-сертификата
sudo cp ldap-ca.crt /usr/local/share/ca-certificates/

# Обновление хранилища (Debian/Ubuntu)
sudo update-ca-certificates

# Обновление хранилища (RHEL/CentOS)
sudo cp ldap-ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust
```

---

### Конфигурация /etc/sssd/sssd.conf

```ini
[sssd]
services = nss, pam
config_file_version = 2
domains = ldap

[nss]
filter_groups = root
filter_users = root
reconnection_retries = 3

[pam]
offline_credentials_expiration = 7
offline_failed_login_attempts = 3
offline_failed_login_delay = 5

[domain/ldap]
id_provider = ldap
auth_provider = ldap
chpass_provider = ldap
access_provider = ldap

# LDAP сервер
ldap_uri = ldaps://ldap.example.com:636
ldap_search_base = dc=example,dc=com

# Учётная запись для привязки
ldap_default_bind_dn = cn=admin,dc=example,dc=com
ldap_default_authtok = password
ldap_default_authtok_type = password

# Схема
ldap_schema = rfc2307

# Поиск пользователей
ldap_user_search_base = ou=users,dc=example,dc=com
ldap_user_search_scope = sub
ldap_user_search_filter = (objectClass=posixAccount)

# Атрибуты пользователей
ldap_user_uid = uid
ldap_user_uid_number = uidNumber
ldap_user_gid_number = gidNumber
ldap_user_home_directory = homeDirectory
ldap_user_shell = loginShell
ldap_user_gecos = gecos
ldap_user_object_class = posixAccount

# Поиск групп
ldap_group_search_base = ou=groups,dc=example,dc=com
ldap_group_search_scope = sub
ldap_group_search_filter = (objectClass=posixGroup)
ldap_group_object_class = posixGroup
ldap_group_gid = cn
ldap_group_gid_number = gidNumber
ldap_group_member = memberUid

# Кэширование
cache_credentials = true
cache_credentials_minimal_first_factor_length = 2
entry_cache_timeout = 60
entry_cache_user_timeout = 30
entry_cache_group_timeout = 30

# Безопасность
ldap_tls_cacert = /etc/ssl/certs/ca-certificates.crt
ldap_tls_reqcert = demand
```

---

### Настройка NSS и PAM

```bash
# /etc/nsswitch.conf
passwd:     files sss
shadow:     files sss
group:      files sss

# /etc/pam.d/common-auth (Debian/Ubuntu)
auth    [success=1 default=ignore]    pam_sss.so use_first_pass
auth    requisite                        pam_deny.so
auth    required                        pam_permit.so

# /etc/pam.d/common-account (Debian/Ubuntu)
account [default=bad success=ok user_unknown=ignore] pam_sss.so
account required                        pam_permit.so

# /etc/pam.d/common-password (Debian/Ubuntu)
password sufficient                    pam_sss.so use_authtok
password required                        pam_unix.so sha512

# /etc/pam.d/common-session (Debian/Ubuntu)
session required                        pam_mkhomedir.so skel=/etc/skel umask=0077
session optional                        pam_sss.so
```

---

### Автоматическое создание домашних директорий

```bash
# RHEL/CentOS - включение oddjobd
systemctl enable --now oddjobd

# Debian/Ubuntu - pam_mkhomedir в PAM
# Добавить в /etc/pam.d/common-session:
# session required pam_mkhomedir.so skel=/etc/skel umask=0077
```

---

### Запуск и проверка

```bash
# Включение и запуск SSSD
systemctl enable sssd
systemctl start sssd

# Проверка статуса
systemctl status sssd

# Проверка пользователей из LDAP
getent passwd

# Поиск конкретного пользователя
getent passwd username

# Проверка групп из LDAP
getent group

# Проверка аутентификации
id username

# Тест аутентификации
sss_ssh_authorizedkeys username
```

---

## Additional Information

### Связанные темы

- **[PAM](../../../Security/pam_overview.md)** — модули аутентификации
- **[389DS](../../../LDAP/389ds/overview.md)** — развёртывание LDAP-сервера
