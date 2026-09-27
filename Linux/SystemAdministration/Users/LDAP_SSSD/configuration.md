# Установка и настройка LDAP и SSSD

## Определения

Основные понятия (LDAP, SSSD, NSS, PAM) подробно описаны в **[обзорном разделе](./index.md)**.

- **RFC 2307 / RFC 2307bis** — стандарты схем LDAP для хранения POSIX-атрибутов (UID, GID, домашние папки). В `rfc2307` членство в группах хранится в атрибуте `memberUid` (значение — UID пользователя), что затрудняет работу с вложенными группами. В `rfc2307bis` используется атрибут `member` (значение — DN записи пользователя), что позволяет реализовать вложенность и упрощает управление.
- **StartTLS** — расширение протокола LDAP, позволяющее установить защищенное соединение поверх стандартного порта 389.
- **MFA (Multi-Factor Authentication)** — многофакторная аутентификация. SSSD поддерживает нативную проверку TOTP (Time-based One-Time Password) при интеграции с LDAP/IPA.
- **Bind DN** — учетная запись («технический пользователь»), используемая SSSD для подключения и поиска в дереве каталогов LDAP.
- **ldap_id_mapping** — параметр, определяющий способ получения POSIX-идентификаторов из AD: алгоритмический (на основе SID) или явный (из атрибутов `uidNumber`/`gidNumber`). Актуален только для провайдера `ad`.
- **access_provider** — модуль, отвечающий за принятие решения о разрешении входа. Варианты: `simple` (разрешить/запретить по статическому списку), `ldap` (запрос атрибута `authorizedService` или `loginShell`), `ad` (через GPO в Active Directory).
- **ad_site** — принудительное указание сайта AD для клиента, если механизм CLDAP автоопределения не работает. Упрощает отладку и используется в филиалах с нестандартной топологией.

## Базовые концепции

### Четырехуровневая модель интеграции

Для полноценной работы централизованной среды необходимо настроить следующие уровни:

1.  **Демон (SSSD)**: Основной сервис (`sssd.conf`), отвечающий за протоколы, кэширование и логику доменов.
2.  **Диспетчер имен (NSS)**: Механизм `glibc`, перенаправляющий запросы `getpwnam()` и `getgrnam()` в SSSD через `/etc/nsswitch.conf`.
3.  **Аутентификатор (PAM)**: Стек модулей, управляющий проверкой паролей, MFA и политиками сессий (`pam_sss.so`).
4.  **Управление привилегиями (Sudo)**: Интеграция SSSD с `sudo` для получения правил доступа напрямую из LDAP без редактирования локального `/etc/sudoers`.

### Схемы каталогов: RFC 2307 vs RFC 2307bis

Выбор схемы влияет на структуру атрибутов и способ хранения членства в группах:

| Характеристика | RFC 2307 | RFC 2307bis |
| :--- | :--- | :--- |
| **Членство в группе** | `memberUid` (значение — UID) | `member` (значение — DN пользователя) |
| **Вложенные группы** | Не поддерживаются | Поддерживаются (через `member`/`uniqueMember`) |
| **Совместимость** | Устаревшая, есть в старых OpenLDAP | Рекомендуется для новых развертываний |
| **Пример атрибута** | `memberUid: jdoe` | `member: uid=jdoe,ou=users,dc=example,dc=com` |

Параметр `ldap_schema` в `sssd.conf` должен соответствовать реальной схеме каталога. Несоответствие приводит к тому, что пользователи найдутся, но группы останутся пустыми.

### Кэширование и безопасность

При `cache_credentials = true` SSSD сохраняет хэши паролей в локальной базе LDB (`/var/lib/sss/db/`). Это позволяет аутентифицироваться при недоступности LDAP, но требует:
- Права `600` на каталог `/var/lib/sss/db/` и файлы `.ldb`.
- SELinux-контекстов `sssd_var_lib_t` (RHEL-подобные).
- Отключения `cache_credentials` на общедоступных рабочих станциях без шифрования диска.

### Многодоменная архитектура

SSSD поддерживает несколько доменов в одной конфигурации. Каждый домен определяется как отдельный блок `[domain/<name>]`. Домены могут использовать разные провайдеры (например, `ldap` и `ad`) и разные базовые DN. Общий блок `[sssd]` содержит список доменов через параметр `domains`.

### Взаимодействие с Kerberos

SSSD использует Kerberos (TGT — Ticket Granting Ticket) для Kerberos-аутентификации. Файл `/etc/krb5.conf` должен быть настроен даже при использовании провайдера `ldap`, если требуется Kerberos-авторизация (SSH, CIFS). Провайдер `ad` автоматически генерирует `krb5.conf` через `realmd`, но для `ldap` требуется ручная настройка.

### Авторизация по SSH-ключам из LDAP

SSSD может передавать атрибуты пользователя (включая публичные SSH-ключи) приложениям через респондер `ifp` (InfoPipe). Это позволяет использовать `sss_authorizedkeys` или `AuthorizedKeysCommand` в `sshd` для централизованного управления ключами без NFS.

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
# Добавьте 'sudo' и 'ifp', если требуются соответствующие функции
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
# Для отказоустойчивости перечислите несколько серверов
ldap_uri = ldaps://ldap01.example.com:636, ldaps://ldap02.example.com:636
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

#### Несколько доменов в одной конфигурации

```ini
[sssd]
domains = corp_ldap, ext_ipa
config_file_version = 2
services = nss, pam

[domain/corp_ldap]
id_provider = ldap
auth_provider = ldap
ldap_uri = ldaps://ldap01.corp.example.com:636
ldap_search_base = dc=corp,dc=example,dc=com
ldap_schema = rfc2307bis

[domain/ext_ipa]
id_provider = ipa
auth_provider = ipa
ipa_server = ipa01.ext.example.com
ipa_domain = ext.example.com
```

### 4. Настройка Kerberos (/etc/krb5.conf)

SSSD использует Kerberos для получения Ticket Granting Ticket (TGT). Минимальная конфигурация для LDAP-среды:

```ini
[libdefaults]
default_realm = EXAMPLE.COM
dns_lookup_realm = false
dns_lookup_kdc = true
ticket_lifetime = 24h
renew_lifetime = 7d
forwardable = true
rdns = false

[realms]
EXAMPLE.COM = {
    kdc = kdc01.example.com
    kdc = kdc02.example.com
    admin_server = kdc01.example.com
}

[domain_realm]
.example.com = EXAMPLE.COM
example.com = EXAMPLE.COM
```

Для AD-среды `realmd` создает `krb5.conf` автоматически. Проверьте актуальность realm и KDC после ввода хоста в домен.

### 5. Настройка отказоустойчивости (Failover)

SSSD автоматически переключается на резервный сервер, если указано несколько значений в `ldap_uri` или `ad_server`. Порядок важен: первый сервер в списке — предпочтительный.

```ini
ldap_uri = ldaps://ldap01.example.com:636, ldaps://ldap02.example.com:636
```

Для AD также используйте `ad_server` и `ad_backup_server`:

```ini
ad_server = rodc01.example.com
ad_backup_server = rwdc01.example.com
```

### 6. Атрибуты пользователей и SSH-ключи из LDAP

Централизованное хранение SSH-ключей в LDAP исключает необходимость распространять `authorized_keys` через NFS или Ansible на каждый сервер. SSSD выступает прослойкой: ключи хранятся в каталоге, а `sshd` запрашивает их через `AuthorizedKeysCommand`.

#### Схема хранения ключей

Для хранения публичных SSH-ключей в LDAP используется объектный класс `ldapPublicKey` (схема `rfc2713`) или расширение `openssh-lpk`:

```ldif
# Добавление схемы в OpenLDAP (если не существует)
dn: cn=schema,cn=config
changetype: modify
add: olcSchemaFiles
olcSchemaFiles: file:///etc/ldap/schema/openssh-lpk.ldif

# Пример LDIF для объектного класса openssh-lpk
# objectClass: openssh-lpk
# Атрибут: sshPublicKey (syntax:Octet String)
```

В AD используется атрибут `sshPublicKey` из расширения `ldapPublicKey` или `msDS-KeyCredentialLink` для FIDO2/Passkey.

#### Настройка SSSD для передачи ключей

Ключи передаются через респондер `ifp` (InfoPipe) или напрямую через NSS:

```ini
[domain/internal_ldap]
# Атрибут в LDAP, содержащий публичный ключ
ldap_user_extra_attrs = sshPublicKey

[sssd]
services = nss, pam, ifp

[ifp]
allowed_uids = root, sshd
# Какие атрибуты передавать через D-Bus
user_attributes = sshPublicKey
```

#### Настройка sshd

```text
# /etc/ssh/sshd_config
AuthorizedKeysCommand /usr/bin/sss_ssh_authorizedkeys
AuthorizedKeysCommandUser sssd
```

`sss_ssh_authorizedkeys` — встроенная утилита SSSD, которая:
1. Принимает имя пользователя как аргумент (`%u` в `AuthorizedKeysCommand`).
2. Запрашивает атрибут `sshPublicKey` через InfoPipe или NSS.
3. Возвращает найденные ключи по одному на строку.

#### Проверка работоспособности

```bash
# Ручной вызов утилиты
sudo sss_ssh_authorizedkeys ldap_user
# → ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA... ldap_user@example.com
# → ssh-rsa AAAAB3NzaC1yc2EAAAA... ldap_user@example.com

# Проверка через getent (если настроен NSS)
getent passwd ldap_user
# → ldap_user:x:10000:10000::/home/ldap_user:/bin/bash

# Проверка через D-Bus (InfoPipe)
sudo busctl call org.freedesktop.sssd.infopipe /org/freedesktop/sssd/infopipe \
  org.freedesktop.sssd.infopipe User "s" "ldap_user"
```

#### Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `sss_ssh_authorizedkeys` возвращает пустой результат | Атрибут `sshPublicKey` не добавлен в `ldap_user_extra_attrs` | Добавьте атрибут в `sssd.conf`, перезапустите SSSD |
| Ключи обновляются с задержкой | Кэш SSSD (`entry_cache_timeout`) | Уменьшите `entry_cache_timeout` или выполните `sss_cache -u username` |
| `AuthorizedKeysCommand` завершается с таймаутом | Большое количество ключей или慢速 LDAP | Увеличьте `sshd`-таймаут: `KeyRegenerationInterval` не применим, используйте кэширование на стороне SSSD |
| Ключи не отображаются после добавления в LDAP | Схема не содержит `openssh-lpk` или `ldapPublicKey` | Убедитесь, что схема загружена в LDAP-сервер |

#### Альтернативы: SSH-ключи из LDAP vs SSH CA

| Критерий | LDAP/SSSD + AuthorizedKeysCommand | SSH CA (Certificate Authority) |
| :--- | :--- | :--- |
| Сложность настройки | Низкая | Средняя (требует CA) |
| Централизация | Да | Да |
| Ротация ключей | Ручная (через LDAP) | Автоматическая (TTL сертификатов) |
| Безопасность | Средняя (ключи статические) | Высокая (short-lived сертификаты) |
| Масштаб | 100-1000 пользователей | 1000+ пользователей |

Для масштабных инфраструктур (1000+ серверов) рассмотрите SSH CA или Vault SSH — см. [Управление SSH-ключами в масштабных инфраструктурах](../../../../Linux/Security/ssh/server/ssh_key_management_at_scale.md).

### 7. Нативная поддержка MFA (TOTP)

Если LDAP поддерживает атрибут `ipaTokenOTP` (или аналогичный), SSSD может запрашивать второй фактор.

1.  Включите поддержку в `sssd.conf`:
    ```ini
    [domain/internal_ldap]
    ...
    # Активация двухфакторной аутентификации
    ldap_authentication_token_timeout = 60
    ```
2.  При входе SSSD запросит `First Factor + OTP` (обычно вводится слитно или последовательно, в зависимости от настроек PAM).

### 8. Централизованные правила Sudo через LDAP

Централизованное управление sudo-правилами в LDAP исключает необходимость редактирования `/etc/sudoers` или файлов в `/etc/sudoers.d/` на каждом сервере. Правила вступают в силу немедленно без перезапуска sudo.

#### Структура LDAP для хранения правил sudo

Правила хранятся в ветке `ou=sudoers` (или `ou=SUDOers`) объектами класса `sudoRole`:

```ldif
# Корневой контейнер
dn: ou=SUDOers,dc=example,dc=com
objectClass: organizationalUnit
ou: SUDOers

# Правило: все пользователи группы wheel могут выполнять всё от root
dn: cn=defaults,ou=SUDOers,dc=example,dc=com
objectClass: sudoRole
cn: defaults
sudoOption: !authenticate

# Правило: группа sysadmins — полный доступ на серверах приложений
dn: cn=sysadmins_all,ou=SUDOers,dc=example,dc=com
objectClass: sudoRole
cn: sysadmins_all
sudoUser: %sysadmins
sudoHost: ALL
sudoCommand: ALL
sudoRunAsUser: root
sudoRunAsGroup: root

# Правило: группа devops — только restart nginx и docker pull на prod-серверах
dn: cn=devops_deploy,ou=SUDOers,dc=example,dc=com
objectClass: sudoRole
cn: devops_deploy
sudoUser: %devops
sudoHost: prod-web01,prod-web02
sudoCommand: /usr/bin/systemctl restart nginx
sudoCommand: /usr/bin/docker pull *
sudoOption: !authenticate

# Правило: отдельный пользователь — только без пароля для特定 команд
dn: cn=deploy_user,ou=SUDOers,dc=example,dc=com
objectClass: sudoRole
cn: deploy_user
sudoUser: deploy
sudoHost: web*
sudoCommand: /usr/local/bin/deploy.sh
sudoCommand: /usr/bin/systemctl restart app-*
sudoOption: authenticate
```

#### Ключевые атрибуты sudoRole

| Атрибут | Описание | Пример |
| :--- | :--- | :--- |
| `sudoUser` | Имя пользователя или группы (с префиксом `%`) | `jdoe`, `%sysadmins` |
| `sudoHost` | Хост или группа хостов | `ALL`, `web01`, `%app_servers` |
| `sudoCommand` | Разрешенные команды (с путем или `ALL`) | `/usr/bin/systemctl`, `ALL` |
| `sudoOption` | Опции (`authenticate`, `!authenticate`, `setenv`) | `!authenticate` |
| `sudoRunAsUser` | От чьего имени выполнять (по умолчанию root) | `root`, `appuser` |
| `sudoRunAsGroup` | Группа для выполнения | `root`, `deploy` |
| `sudoNotBefore` / `sudoNotAfter` | Временные ограничения правила | `20260101000000Z` |

#### Настройка на клиенте

1. Добавьте `sss` в `/etc/nsswitch.conf`:
   ```text
   sudoers: files sss
   ```

2. В `sssd.conf` включите sudo-провайдер:
   ```ini
   [sssd]
   services = nss, pam, sudo

   [domain/internal_ldap]
   sudo_provider = ldap
   ldap_sudo_search_base = ou=SUDOers,dc=example,dc=com
   # Опционально: фильтр поиска для ускорения
   ldap_sudo_search_base = ou=SUDOers,dc=example,dc=com
   ```

3. Для FreeIPA sudo-политики настраиваются через `ipa sudorule` (не требуют ручного создания `ou=SUDOers`).

#### Порядок разрешения правил

SSSD загружает все `sudoRole` из LDAP и применяет правила в следующем порядке:
1. **Точное совпадение** (`sudoUser=jdoe`, `sudoHost=web01`) — самый высокий приоритет.
2. **Групповые правила** (`sudoUser=%sysadmins`) — проверяются после точных.
3. **Правила по умолчанию** (`cn=defaults`) — применяются, если ни одно конкретное правило не совпало.
4. **Файлы** (`/etc/sudoers`, `/etc/sudoers.d/*`) — проверяются первыми (благодаря `files sss` в nsswitch.conf).

#### Проверка работоспособности

```bash
# Проверка правил для конкретного пользователя
sudo -l -U sysadmin_user
# → User sysadmin_user may run the following commands on this host:
#     (root) /bin/systemctl restart *

# Проверка через SSSD
sudo -l -U devops_user
# → Matching Defaults entries for devops_user on this host:
#     !authenticate
# User devops_user may run the following commands on this host:
#     (root) /bin/systemctl restart nginx

# Принудительное обновление кэша sudo
sudo sss_cache -u username
```

#### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `sudo: no valid sudoers sources found` | В `nsswitch.conf` нет `sudoers: files sss` | Добавьте строку |
| `sudo: ldap_sudo_lookup: no matching rules` | `ldap_sudo_search_base` указан неверно | Проверьте `sssctl user-check username` |
| Sudo-правила не обновляются | Кэш SSSD (`entry_cache_timeout`) | `sss_cache -E` или уменьшите таймаут |
| `sudo: requires root` | Правило `sudoRunAsUser` не указано | Укажите `sudoRunAsUser: root` в `sudoRole` |

### 9. Активация профиля через authselect (RHEL)

```bash
# Активация SSSD с автоматическим созданием домашних директорий
sudo authselect select sssd with-mkhomedir --force
sudo systemctl enable --now oddjobd
```

На Debian/Ubuntu используйте `pam-auth-update`:

```bash
sudo pam-auth-update --enable sssd
sudo systemctl enable --now oddjobd
```

### 10. Валидация конфигурации перед применением

```bash
# Проверка синтаксиса sssd.conf
sudo sssctl config-check

# Проверка доступности LDAP с параметрами из sssd.conf
sudo sssctl domain-status internal_ldap

# Ручная проверка bind (замена пароля на действительный)
ldapsearch -x -H ldaps://ldap01.example.com:636 \
  -D "cn=sssd_user,ou=services,dc=example,dc=com" \
  -W -b "dc=example,dc=com" "(uid=testuser)"
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

Для глубокой диагностики кэша используйте `sssctl` (см. **[Эксплуатация и диагностика](./operations.md)**).

### Производительность и тюнинг

Ключевые параметры для больших каталогов (>500 объектов):

| Параметр | Рекомендация | Пояснение |
| :--- | :--- | :--- |
| `enumerate` | `false` | Отключает выгрузку всего каталога в память. |
| `ldap_page_size` | `5000` | Размер страницы для пагинации. Уменьшает нагрузку на сервер. |
| `entry_cache_timeout` | `1800` (30 мин) | Время жизни записей в кэше. |
| `ldap_search_timeout` | `60` | Таймаут одного LDAP-запроса. |
| `negative_timeout` | `60` | Таймаут кэширования «не найден». |

Детальный разбор производительности и мониторинга приведен в **[Эксплуатация и диагностика](./operations.md)**.

### SELinux и права доступа

На RHEL-подобных системах проверяйте контексты:

```bash
# Файл конфигурации
ls -Z /etc/sssd/sssd.conf
# → system_u:object_r:etc_t:s0 /etc/sssd/sssd.conf

# База LDB
ls -Z /var/lib/sss/db/*
# → system_u:object_r:sssd_var_lib_t:s0 ...

# Логи
ls -Z /var/log/sssd/
# → system_u:object_r:sssd_log_t:s0 ...
```

Некорректные контексты маскируются под общие ошибки аутентификации.

### Типовые ошибки конфигурации

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Can't contact LDAP server` | Неверный `ldap_uri`, firewall, DNS | Проверьте порт 636/389, `dig`, `ldapsearch` |
| `TLS handshake failed` | Неверный CA, истекший сертификат | `openssl s_client -connect ldap:636`, проверьте CRL |
| `UserNotFoundError` | Неверный `ldap_search_base` или схема | Проверьте `sssctl user-check <user>` |
| `Groups empty` | `ldap_schema` не соответствует каталогу | Переключитесь на `rfc2307bis` или наоборот |
| `Sudo not working` | В `nsswitch.conf` нет `sudoers: files sss` | Добавьте строку, проверьте `sudo -l` |
| `Access denied for all` | Ошибка прав на `sssd.conf` | `chmod 600 /etc/sssd/sssd.conf`, `chown root:root` |
| `OOM after boot` | `enumerate = true` на большом каталоге | Отключите `enumerate`, увеличьте RAM или swap |
| `Kerberos auth fails` | Рассynchronзация времени или неверный realm | Проверьте `chronyc tracking`, `krb5.conf` |

### Аварийный доступ

Если SSSD полностью блокирует вход, используйте следующие шаги:
1. Загрузка в `single user mode` или использование консоли IPMI.
2. Временное удаление `sss` из `/etc/nsswitch.conf` (строки `passwd` и `group`).
3. Исправление конфигурации в `/etc/sssd/sssd.conf`.
4. Проверка прав доступа: `chown root:root /etc/sssd/sssd.conf && chmod 600 /etc/sssd/sssd.conf`.

Подробные шаги аварийного восстановления и миграции с `nscd`/`winbind` описаны в **[Эксплуатация и диагностика](./operations.md)**.

### Смежные темы

- [Обзор LDAP и SSSD (Index)](./index.md) — архитектурные принципы.
- [Эксплуатация и диагностика](./operations.md) — решение проблем и `sssctl`.
- [Интеграция с Active Directory](./ad_integration.md) — особенности провайдера `ad`.
- [PAM (Pluggable Authentication Modules)](../../../Security/pam_overview.md) — детальный разбор стека аутентификации.
