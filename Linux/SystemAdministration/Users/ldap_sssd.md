# Централизованное управление пользователями (LDAP, SSSD)

## Определения

- **LDAP** (Lightweight Directory Access Protocol) — протокол доступа к распределённой иерархической базе данных (каталогу)
- **SSSD** (System Security Services Daemon) — демон для подключения к службам каталогов с кэшированием учётных данных
- **NSS** (Name Service Switch) — механизм получения информации о пользователях/группах из различных источников
- **PAM** (Pluggable Authentication Modules) — гибкая система аутентификации

## Базовые концепции

### Архитектура

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Приложение │ →  │     PAM     │ →  │    SSSD     │
│  (sshd, su) │    │  (аутентиф.)│    │ (кэш/LDAP)  │
└─────────────┘    └─────────────┘    └──────┬──────┘
                                             ↓
                                      ┌─────────────┐
                                      │  LDAP Server│
                                      │ (AD/OpenLDAP)│
                                      └─────────────┘
```

### Компоненты

| Компонент | Назначение |
| :--- | :--- |
| **LDAP** | Централизованное хранение учётных записей |
| **NSS** | Получение информации о пользователях (UID, GID, группы) |
| **PAM** | Аутентификация пользователей |
| **SSSD** | Кэширование учётных данных, офлайн-аутентификация |

### Преимущества SSSD перед nss-pam-ldapd

- **Кэширование учётных данных** — вход при недоступности LDAP
- **Производительность** — меньше запросов к серверу
- **Гибкость** — поддержка множественных доменов
- **Безопасность** — безопасное хранение учётных данных

## Практические сценарии

### Установка пакетов

```bash
# Rocky Linux / RHEL / CentOS / AlmaLinux
dnf install sssd sssd-ldap oddjob-mkhomedir

# Debian / Ubuntu
apt install sssd sssd-ldap libnss-sssd libpam-sssd
```

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

### Автоматическое создание домашних директорий

```bash
# RHEL/CentOS - включение oddjobd
systemctl enable --now oddjobd

# Debian/Ubuntu - pam_mkhomedir в PAM
# Добавить в /etc/pam.d/common-session:
# session required pam_mkhomedir.so skel=/etc/skel umask=0077
```

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

### Отладка и мониторинг

```bash
# Просмотр логов SSSD
journalctl -u sssd -f

# Уровень логирования (изменить в sssd.conf)
# [sssd]
# debug_level = 9

# Перезапуск с новым уровнем логирования
systemctl restart sssd

# Очистка кэша SSSD
systemctl stop sssd
rm -rf /var/lib/sss/db/*
rm -rf /var/lib/sss/mc/passwd
rm -rf /var/lib/sss/mc/group
systemctl start sssd

# Проверка кэшированных пользователей
sss_cache -E  # Показать всё
sss_cache -u username  # Показать пользователя
```

## Лучшие практики

### Безопасность

1. **Всегда используйте LDAPS (порт 636)** — никогда не передавайте учётные данные в открытом виде
2. **Ограничьте доступ к sssd.conf** — файл содержит пароли:

   ```bash
   chmod 600 /etc/sssd/sssd.conf
   chown root:root /etc/sssd/sssd.conf
   ```

3. **Используйте SASL/GSSAPI** для аутентификации вместо простых паролей
4. **Настройте firewall** — разрешите только порт 636 (LDAPS)
5. **Регулярно обновляйте CA-сертификаты**

### Производительность

1. **Настройте кэширование** — уменьшите нагрузку на LDAP:

   ```ini
   entry_cache_timeout = 60
   entry_cache_user_timeout = 30
   entry_cache_group_timeout = 30
   ```

2. **Используйте поддомены** — для крупных инфраструктур:

   ```ini
   [sssd]
   domains = example.com, sub.example.com
   ```

3. **Фильтруйте пользователей** — не кэшируйте системные учётные записи:

   ```ini
   [nss]
   filter_users = root,daemon,bin
   filter_groups = root,daemon,bin
   ```

### Типовые проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Пользователь не находится | Неверный search_base | Проверьте ldap_user_search_base |
| Аутентификация не работает | Неверный bind_dn/пароль | Проверьте учётные данные |
| Кэш не обновляется | Старые записи в кэше | Очистите кэш: `sss_cache -E` |
| Нет домашних директорий | Не настроен oddjob/pam_mkhomedir | Включите сервис |
| TLS ошибка | Неправильный CA-сертификат | Проверьте путь и формат |

### Конфигурация для Active Directory

```ini
[domain/AD]
id_provider = ad
auth_provider = ad
access_provider = ad

ldap_schema = ad
ldap_id_mapping = True
fallback_homedir = /home/%u@%d
default_shell = /bin/bash

# Кэширование
cache_credentials = True
entry_cache_timeout = 60
```

## Дополнительная информация

### Связанные темы

- [PAM](../../Security/pam_overview.md) — модули аутентификации
- [389DS](../../../LDAP/389ds/overview.md) — развёртывание LDAP-сервера
- [OpenLDAP в Kubernetes](../../../LDAP/openldap_kubernetes.md) — контейнеризация
- [Kerberos](../../Security/Concepts/kerberos.md) — аутентификация в AD

### Полезные команды

```bash
# Проверка подключения к LDAP
ldapsearch -x -H ldaps://ldap.example.com -b dc=example,dc=com "(objectClass=*)"

# Тест аутентификации
ldapwhoami -x -H ldaps://ldap.example.com -D "cn=admin,dc=example,dc=com" -W

# Проверка SSSD
sssctl domain-status ldap
sssctl user-check username
```

### Ресурсы

- [Официальная документация SSSD](https://sssd.io/)
- [Red Hat SSSD Guide](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/configuring_authentication_and_authorization_in_rhel/configuring-identity-management-with-sssd_system-configuring-identity-management-with-sssd)
- [LDAP Schema RFC2307](https://www.rfc-editor.org/rfc/rfc2307)
