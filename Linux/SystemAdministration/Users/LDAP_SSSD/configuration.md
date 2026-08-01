# Установка и настройка LDAP и SSSD

## Определения

- **SSSD (System Security Services Daemon)** — системная служба, обеспечивающая интеграцию локальной ОС с удаленными провайдерами идентификации (LDAP, Active Directory, FreeIPA). Инкапсулирует логику кэширования и переключения между онлайн/офлайн режимами.
- **NSS (Name Service Switch)** — механизм системной библиотеки C (glibc), определяющий источники данных для системных баз (пользователи, группы). Конфигурируется в файле `/etc/nsswitch.conf`.
- **PAM (Pluggable Authentication Modules)** — модульная инфраструктура для проверки подлинности пользователей. Использует библиотеку `pam_sss.so` для передачи запросов на аутентификацию в SSSD.
- **RFC 2307 / RFC 2307bis** — стандарты схем LDAP для хранения POSIX-атрибутов (UID, GID, домашние папки). Различаются способом хранения членства в группах (атрибут `memberUid` vs `member`).
- **StartTLS** — расширение протокола LDAP, позволяющее установить защищенное соединение поверх стандартного порта 389.

## Базовые концепции

### Трехуровневая модель конфигурации

Для корректной работы централизованной аутентификации необходимо настроить три уровня:

1.  **Демон (SSSD)**: Файл `/etc/sssd/sssd.conf` описывает, *куда* подключаться (LDAP URI) и *как* искать данные (Search Base).
2.  **Диспетчер (NSS)**: Настройка определяет, что SSSD является доверенным источником имен пользователей.
3.  **Аутентификатор (PAM)**: Настройка определяет, что SSSD может проверять пароли.

### Выбор схемы данных (ldap_schema)

- **`rfc2307`**: Классическая схема. Группы содержат список имен пользователей в атрибуте `memberUid`. Эффективна, но не поддерживает вложенные группы.
- **`rfc2307bis`**: Современная схема. Группы содержат Distinguished Names (DN) участников в атрибуте `member`. Поддерживает иерархические структуры.

## Практические сценарии

### 1. Установка пакетов

```bash
# RHEL 8/9, Rocky Linux, AlmaLinux
sudo dnf install sssd sssd-ldap oddjob-mkhomedir

# Debian 12, Ubuntu 22.04/24.04
sudo apt update && sudo apt install sssd sssd-ldap libnss-sssd libpam-sssd
```

### 2. Подготовка TLS-сертификатов

Безопасное соединение обязательно для передачи хэшей паролей.

```bash
# Поместите сертификат CA вашего LDAP-сервера в /etc/ssl/certs/ldap-ca.crt
# Для RHEL систем обновите доверенное хранилище:
sudo cp ldap-ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust
```

### 3. Создание /etc/sssd/sssd.conf

Файл **обязательно** должен иметь права доступа `600` (`-rw-------`).

```ini
[sssd]
services = nss, pam
config_file_version = 2
domains = internal_ldap

[nss]
# Фильтрация системных аккаунтов (ускоряет работу)
filter_users = root,daemon,bin,sys,sync
filter_groups = root,daemon,bin,sys,sync

[pam]
# Срок жизни офлайн-пароля (в днях)
offline_credentials_expiration = 7

[domain/internal_ldap]
id_provider = ldap
auth_provider = ldap
access_provider = ldap

# Параметры подключения
ldap_uri = ldaps://ldap.example.com:636
ldap_search_base = dc=example,dc=com

# Учетная запись для чтения каталога (Bind DN)
ldap_default_bind_dn = cn=sssd_user,ou=services,dc=example,dc=com
ldap_default_authtok = YourSecurePassword

# Настройки поиска и схемы
ldap_schema = rfc2307bis
ldap_user_search_base = ou=users,dc=example,dc=com
ldap_group_search_base = ou=groups,dc=example,dc=com

# Кэширование
cache_credentials = true
enumerate = false

# TLS Безопасность
ldap_tls_cacert = /etc/ssl/certs/ca-certificates.crt
ldap_tls_reqcert = demand
```

### 4. Активация интерфейсов (NSS и PAM)

Использование автоматизированных утилит является предпочтительным и исключает риск повреждения файлов конфигурации.

#### Для систем RHEL/CentOS (authselect)
```bash
# Просмотр доступных профилей
authselect list

# Активация SSSD с автоматическим созданием домашних директорий
sudo authselect select sssd with-mkhomedir --force
```

#### Для систем Debian/Ubuntu (pam-auth-update)
```bash
# Запустите интерактивную утилиту и выберите "SSS Authentication"
sudo pam-auth-update

# Для автоматического создания папок добавьте в /etc/pam.d/common-session:
# session required pam_mkhomedir.so skel=/etc/skel umask=0077
```

### 5. Автоматическое создание домашних папок (oddjobd)

В RHEL-системах за создание папок отвечает сервис `oddjobd`.

```bash
sudo systemctl enable --now oddjobd
```

### 6. Запуск и верификация

```bash
# Запуск демона
sudo systemctl enable --now sssd

# Проверка получения данных (UID/GID должны соответствовать LDAP)
id username

# Проверка входа без пароля (для уже вошедших в кэш пользователей)
# Отключите сетевой интерфейс и попробуйте войти
```

## Дополнительная информация

### Тонкая настройка безопасности

1.  **StartTLS**: Если LDAP работает на порту 389, используйте `ldap_id_use_start_tls = true` в `sssd.conf`.
2.  **Защита пароля Bind DN**: Вместо хранения пароля в `sssd.conf`, рассмотрите использование провайдеров `ad` или `ipa`, которые используют системный Keytab.
3.  **Диапазоны UID/GID**: Убедитесь, что `UID_MIN` в `/etc/login.defs` на локальной системе меньше, чем минимальный UID в LDAP (обычно 1000 или 2000), чтобы избежать пересечений.

### Смежные темы

- [Централизованное управление (Index)](./index.md) — общая архитектура.
- [Эксплуатация и диагностика](./operations.md) — работа с `sssctl` и очистка кэша.
- [Интеграция с Active Directory](./ad_integration.md) — специфика провайдера `ad`.
- [Настройка PAM](../../../Security/pam_overview.md) — детальный разбор работы PAM-стека.
