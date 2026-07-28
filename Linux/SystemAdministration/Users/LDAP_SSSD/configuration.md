# Установка и настройка LDAP и SSSD

## Определения

- **SSSD** (System Security Services Daemon) — системная служба, обеспечивающая доступ к удаленным базам данных пользователей (LDAP, Active Directory) с поддержкой кэширования для работы в автономном режиме.
- **LDAP** (Lightweight Directory Access Protocol) — сетевой протокол для доступа к распределенным службам каталогов.
- **NSS** (Name Service Switch) — механизм в Unix-подобных операционных системах, определяющий источники данных для системных баз (пользователи, группы, хосты). Настраивается в `/etc/nsswitch.conf`.
- **PAM** (Pluggable Authentication Modules) — набор разделяемых библиотек, позволяющих интегрировать различные методы аутентификации в приложения без их перекомпиляции.
- **TLS/SSL** (Transport Layer Security / Secure Sockets Layer) — криптографические протоколы, обеспечивающие защищенную передачу данных между клиентом и сервером каталогов.
- **AD** (Active Directory) — служба каталогов от Microsoft, использующая протокол LDAP для предоставления информации об объектах сети.
- **POSIX** (Portable Operating System Interface) — набор стандартов, определяющих интерфейсы взаимодействия операционной системы и приложений, включая формат записей пользователей и групп.

---

## Базовые понятия

### Архитектура конфигурации

Процесс настройки интеграции включает три уровня:

1. **Уровень службы (SSSD):** создание файла конфигурации `sssd.conf`, где описываются параметры подключения к серверу, базы поиска (Search DN) и настройки безопасности.
2. **Уровень системных баз (NSS):** указание системе, что информацию о пользователях и группах следует искать не только в локальных файлах (`/etc/passwd`), но и запрашивать у службы SSSD.
3. **Уровень приложений (PAM):** подключение модуля `pam_sss.so`, который перенаправляет запросы на проверку пароля в SSSD.

### Ключевые параметры sssd.conf

| Параметр | Описание | Значение |
| :--- | :--- | :--- |
| **id_provider** | Провайдер идентификации | `ldap`, `ad`, `ipa` |
| **auth_provider** | Провайдер аутентификации | Обычно совпадает с `id_provider` |
| **ldap_schema** | Схема данных | `rfc2307` (стандарт POSIX), `ad` |
| **cache_credentials** | Кэширование данных | `true` — разрешает вход без связи с сервером |
| **ldap_tls_reqcert** | Проверка сертификата | `demand` — обязательная проверка CA (Certificate Authority) |

---

## Практические сценарии

### Установка компонентов

В зависимости от дистрибутива установите необходимые пакеты:

**RHEL (Red Hat Enterprise Linux) и производные (Rocky, AlmaLinux):**

```bash
dnf install sssd sssd-ldap oddjob-mkhomedir
```

**Debian и Ubuntu:**

```bash
apt update && apt install sssd sssd-ldap libnss-sssd libpam-sssd
```

---

### Обеспечение безопасности соединений (TLS/SSL)

Для безопасной передачи учетных данных необходимо доверять сертификату сервера каталогов:

1. **Копирование сертификата CA:** поместите файл `ldap-ca.crt` в системное хранилище.
2. **Обновление хранилища:**
    - **Debian/Ubuntu:** `update-ca-certificates`
    - **RHEL:** `update-ca-trust`

---

### Конфигурация /etc/sssd/sssd.conf

Создайте файл с правами доступа `600`:

```ini
[sssd]
services = nss, pam
config_file_version = 2
domains = ldap_domain

[nss]
filter_groups = root
filter_users = root

[pam]
offline_credentials_expiration = 7

[domain/ldap_domain]
id_provider = ldap
auth_provider = ldap
access_provider = ldap

# Параметры LDAP-сервера
ldap_uri = ldaps://ldap.example.com:636
ldap_search_base = dc=example,dc=com

# Учётная запись для привязки (Bind DN)
ldap_default_bind_dn = cn=readonly,dc=example,dc=com
ldap_default_authtok = secret_password

# Схема и поиск пользователей
ldap_schema = rfc2307
ldap_user_search_base = ou=users,dc=example,dc=com
ldap_user_object_class = posixAccount

# Кэширование
cache_credentials = true
entry_cache_timeout = 600

# Настройка TLS
ldap_tls_cacert = /etc/ssl/certs/ca-certificates.crt
ldap_tls_reqcert = demand
```

---

### Интеграция с Active Directory (AD)

Для работы в доменах Windows используется оптимизированный провайдер `ad`. Подробное руководство по подключению через `realmd` и специфическим настройкам AD см. в отдельной статье: **[Интеграция SSSD с Active Directory](./ad_integration.md)**.

---

### Настройка системных интерфейсов (NSS и PAM)

Отредактируйте файлы конфигурации для активации SSSD:

**1. /etc/nsswitch.conf:**

```bash
passwd:     files sss
group:      files sss
shadow:     files sss
```

**2. PAM (через pam-auth-update в Debian или вручную):**
В файлах `/etc/pam.d/common-auth` (и аналогичных) должен присутствовать модуль `pam_sss.so`.

---

### Автоматическое создание домашних директорий

Для автоматического создания папок пользователей при первом входе:

- **RHEL:** `systemctl enable --now oddjobd`
- **Debian/Ubuntu:** убедитесь, что в `/etc/pam.d/common-session` добавлена строка:
    `session required pam_mkhomedir.so skel=/etc/skel umask=0077`

---

### Запуск и верификация

```bash
# Активация службы
systemctl enable --now sssd

# Проверка получения данных о пользователе
id username

# Проверка через системные базы
getent passwd username
```

---

## Дополнительная информация

**Связанные темы:**

- [Централизованное управление (LDAP, SSSD)](./index.md) — обзор архитектуры и общих принципов.
- [Эксплуатация и отладка](./operations.md) — решение проблем, мониторинг и очистка кэша.
- [PAM (Pluggable Authentication Modules)](../../../Security/pam_overview.md) — подробное описание работы модулей аутентификации.
