# Установка и настройка LDAP и SSSD

## Определения

Основные понятия (LDAP, SSSD, NSS, PAM) подробно описаны в **[обзорном разделе](./index.md)**.

- **RFC 2307 / RFC 2307bis** — стандарты схем LDAP для хранения POSIX-атрибутов (UID, GID, домашние папки). Различаются способом хранения членства в группах (атрибут `memberUid` vs `member`).
- **StartTLS** — расширение протокола LDAP, позволяющее установить защищенное соединение поверх стандартного порта 389.
- **MFA (Multi-Factor Authentication)** — многофакторная аутентификация. SSSD поддерживает нативную проверку TOTP (Time-based One-Time Password) при интеграции с LDAP/IPA.
- **Bind DN** — учетная запись («технический пользователь»), используемая SSSD для подключения и поиска в дереве каталогов LDAP.

## Базовые концепции

### Четырехуровневая модель интеграции

Для полноценной работы централизованной среды необходимо настроить следующие уровни:

1.  **Демон (SSSD)**: Основной сервис (`sssd.conf`), отвечающий за протоколы, кэширование и логику доменов.
2.  **Диспетчер имен (NSS)**: Механизм `glibc`, перенаправляющий запросы `getpwnam()` и `getgrnam()` в SSSD через `/etc/nsswitch.conf`.
3.  **Аутентификатор (PAM)**: Стек модулей, управляющий проверкой паролей, MFA и политиками сессий (`pam_sss.so`).
4.  **Управление привилегиями (Sudo)**: Интеграция SSSD с `sudo` для получения правил доступа напрямую из LDAP без редактирования локального `/etc/sudoers`.

## Практические сценарии

### 1. Установка пакетов

```bash
# RHEL 8/9, Rocky Linux, AlmaLinux
sudo dnf install sssd sssd-ldap sssd-tools oddjob-mkhomedir

# Debian 12, Ubuntu 22.04/24.04
sudo apt update && sudo apt install sssd sssd-ldap sssd-tools libnss-sssd libpam-sssd
```

### 2. Подготовка TLS-сертификатов (Обязательно)

Передача паролей по незащищенному каналу запрещена.

```bash
# Размещение сертификата CA в доверенном хранилище
# RHEL:
sudo cp ldap-ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust

# Debian/Ubuntu:
sudo cp ldap-ca.crt /usr/local/share/ca-certificates/ldap-ca.crt
sudo update-ca-certificates
```

### 3. Расширенная конфигурация /etc/sssd/sssd.conf

Файл должен иметь владельца `root:root` и права `600`.

```ini
[sssd]
# Добавьте 'sudo', если планируете хранить правила в LDAP
services = nss, pam, sudo
config_file_version = 2
domains = internal_ldap

[nss]
filter_users = root,daemon,bin,sys,sync
filter_groups = root,daemon,bin,sys,sync
# Таймаут кэширования негативных ответов (пользователь не найден)
negative_timeout = 60

[pam]
# Разрешить вход, если сервер LDAP недоступен (по кэшу)
offline_credentials_expiration = 7

[sudo]
# Настройки для извлечения правил sudo из LDAP

[domain/internal_ldap]
id_provider = ldap
auth_provider = ldap
access_provider = ldap
sudo_provider = ldap

# Параметры подключения
ldap_uri = ldaps://ldap.example.com:636
ldap_search_base = dc=example,dc=com

# Bind DN (учетная запись для поиска)
ldap_default_bind_dn = cn=sssd_user,ou=services,dc=example,dc=com
ldap_default_authtok = SecurePass123

# Настройки схемы
ldap_schema = rfc2307bis
ldap_user_search_base = ou=users,dc=example,dc=com
ldap_group_search_base = ou=groups,dc=example,dc=com
ldap_sudo_search_base = ou=sudoers,dc=example,dc=com

# Безопасность и TLS
ldap_tls_cacert = /etc/ssl/certs/ca-certificates.crt
ldap_tls_reqcert = demand

# Кэширование и производительность
cache_credentials = true
# КРИТИЧНО: enumerate = false для больших каталогов (>500 объектов)
enumerate = false
```

### 4. Нативная поддержка MFA (TOTP)

Если LDAP поддерживает атрибут `ipaTokenOTP` (или аналогичный), SSSD может запрашивать второй фактор.

1.  Включите поддержку в `sssd.conf`:
    ```ini
    [domain/internal_ldap]
    ...
    # Активация двухфакторной аутентификации
    ldap_authentication_token_timeout = 60
    ```
2.  При входе SSSD запросит `First Factor + OTP` (обычно вводится слитно или последовательно, в зависимости от настроек PAM).

### 5. Интеграция с Sudo

Для получения правил из LDAP без локальных правок:

1.  Добавьте `sss` в `/etc/nsswitch.conf`:
    ```text
    sudoers: files sss
    ```
2.  Убедитесь, что в LDAP создана ветка `ou=sudoers` с объектами класса `sudoRole`.

### 6. Активация профиля через authselect (RHEL)

```bash
# Активация SSSD с автоматическим созданием домашних директорий
sudo authselect select sssd with-mkhomedir --force
sudo systemctl enable --now oddjobd
```

## Дополнительная информация

### Конфликты UID/GID

При интеграции с LDAP всегда существует риск пересечения ID с локальными пользователями.
- **Рекомендация:** Начинайте диапазон UID в LDAP с `2000` или выше.
- **Проверка:** Используйте `ldap_idmap_range_min` и `max` в `sssd.conf` для жесткого ограничения.

### Управление кэшем

Если данные в LDAP изменились, но не отображаются локально:
```bash
# Очистка кэша для конкретного пользователя
sudo sss_cache -u username

# Полный сброс кэша (инвалидация всех записей)
sudo sss_cache -E
```

### Смежные темы

- [Обзор LDAP и SSSD (Index)](./index.md) — архитектурные принципы.
- [Эксплуатация и диагностика](./operations.md) — решение проблем и `sssctl`.
- [Интеграция с Active Directory](./ad_integration.md) — особенности провайдера `ad`.
- [PAM (Pluggable Authentication Modules)](../../../Security/pam_overview.md) — детальный разбор стека аутентификации.
