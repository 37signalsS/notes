# Apache: Аутентификация и авторизация (LDAP/AD, Digest, клиентские сертификаты)

---

## Определения

**mod_authnz_ldap** — модуль Apache, реализующий аутентификацию (проверку учётных данных — `AuthBasicProvider ldap`) и авторизацию (проверку членства — `Require ldap-*`) через LDAP-каталог: OpenLDAP, Active Directory, FreeIPA.

**mod_ldap** — бэкенд-модуль пула LDAP-соединений и кэширования, используется совместно с `mod_authnz_ldap` (`LDAP*` директивы).

**mod_auth_digest** — аутентификация по протоколу HTTP Digest (RFC 7616): пароль не передаётся открыто, используется хэш `HA1`, nonce и счетчик.

**Аутентификация по клиентскому сертификату (mTLS)** — проверка TLS-сертификата клиента (`SSLVerifyClient require`) с сопоставлением субъекта с учётной записью.

**mod_authn_dbd** — аутентификационный провайдер на базе SQL-базы (через `mod_dbd` и APR DBD): пароли проверяются SQL-запросом `AuthDBDUserPWQuery`. Хранит до двух видов паролей: plaintext и хэши `{SHA}`.

**mod_authz_dbm** — авторизация по группам пользователей из DBM-файла (`Require group`, `Require dbm-group`) — аналог `mod_authz_groupfile`, но с бинарным DBM-файлом `/etc/httpd/.htgroup_prefix` (хорошо для больших списков).

**mod_session** — сессионный модуль: хранит состояние пользователя между запросами (cookie `Session` или `mod_session_dbd`/-`crypto`). Часто связывается с приложением для передачи identity.

**AuthN vs AuthZ** — аутентификация является «кем ты», авторизация — «что тебе можно». В Apache разделяются на модули подсистемы `mod_authn_*` (источники учетных записей) и `mod_authz_*` (правила доступа).

---

## Основные концепции

### Слои аутентификации Apache 2.4

| Подсистема | Модуль | Задача |
|---|---|---|
| Провайдер учётных данных | `mod_authn_file` (htpasswd), `mod_authn_dbd`, `mod_authnz_ldap` | Решить, верные ли логин/пароль |
| Авторизация | `mod_authz_core` (`Require`), `mod_authz_user`, `mod_authz_groupfile`, `mod_authz_dbm`, `mod_authz_ldap` | Решить, разрешён ли доступ |
| Форматы | `mod_auth_basic`, `mod_auth_digest` | Как передаются учётные данные |

**Порядок аутентификации:** пароль согласуется провайдером (например LDAP), затем применяется `Require`-правило из `mod_authz_core`. При первом совпадении `Require` принятие (all granted) — доступ открывается.

**Ключевые совместимости:**
- `AuthBasicProvider ldap` — использовать LDAP как источник учётных записей.
- Фоллбэк на локальный файл: `AuthBasicProvider ldap file` — обе источники по порядку (`AuthLDAPAuthoritative off` для перехода к следующему при failure).

### LDAP URL (AuthLDAPURL)

```
ldap[s]://host[:port]/base_dn?attribute?scope?filter
```

| Часть | Значение |
|---|---|
| `attribute` | Атрибут поиска логина. Для AD — `sAMAccountName`, для OpenLDAP — `uid` |
| `scope` | `sub`/`base`/`one` — глубина поиска в поддереве |
| `filter` | Доп. фильтр, например `(&(objectClass=person))` |

### Способы проверки в LDAP

1.  **Search+bind (рекомендуется):** сервер ищет запись по атрибуту, затем выполняет ldap-bind с указанным DN. Нужен `AuthLDAPBindDN`/`AuthLDAPBindPassword`, если каталог запрещает анонимный поиск.
2.  **Direct bind:** DN пользователя формируется шаблоном — редко для Apache (нет `AuthLDAPURL`-шаблонов с привязкой), чаще Search.

### Digest: особенности

*   Пароль хранится в файле в виде хэша (не plaintext) — создаётся утилитой `htdigest`.
*   **Realm обязателен**: значение `AuthName` должно совпадать с realm при генерации пользователя (`htdigest -c file "realm" user`).
*   Не защищает содержимое (защита — TLS), но не раскрывает пароль в чистом виде.
*   Ограничение: не работает через прокси без корректной маршрутизации; сложнее дебажить, чем Basic.

---

## Практические сценарии

### 1. Базовая аутентификация против LDAP (OpenLDAP)

```apacheconf
LoadModule ldap_module modules/mod_ldap.so
LoadModule authnz_ldap_module modules/mod_authnz_ldap.so

LDAPTrustedGlobalCert CA_BASE64 /etc/ssl/certs/ldap-ca.pem
LDAPReferral off

<Directory "/var/www/internal">
    AuthType Basic
    AuthName "Corporate access"
    AuthBasicProvider ldap
    AuthLDAPURL "ldap://ldap.example.com:389/ou=People,dc=example,dc=com?uid?sub"
    Require valid-user
</Directory>
```

### 2. Подключение к Active Directory

Для AD характерно: base DN корня домена, поиск по `sAMAccountName` (без `@domain`), часто требуется bind-аккаунт.

```apacheconf
AuthType Basic
AuthBasicProvider ldap
AuthLDAPURL "ldap://ad.corp.example.com:389/DC=corp,DC=example,DC=com?sAMAccountName?sub"
AuthLDAPBindDN "CN=svc-web,CN=Users,DC=corp,DC=example,DC=com"
AuthLDAPBindPassword "svc-pass-phrase"     # или "file:/etc/httpd/ldap-bind.secret"
AuthLDAPBindAuthoritative on                # не использовать другие провайдеры
Require valid-user
```

**LDAPS/TLS к AD:**
```apacheconf
LDAPTrustedGlobalCert CA_BASE64 /etc/ssl/certs/ad-ca.pem
AuthLDAPURL "ldaps://ad.corp.example.com:636/DC=corp,DC=example,DC=com?sAMAccountName?sub"
```

### 3. Авторизация по группам LDAP/AD

```apacheconf
Require ldap-group cn=devops,ou=Groups,dc=example,dc=com
Require ldap-user john jane          # отдельные пользователи
Require ldap-dn cn=CI-Host,ou=ServiceAccounts,dc=example,dc=com
```

Для групп по атрибуту членства в AD (группы вложенные) поиск может требовать `subtree` с `memberOf`-фильтром — проверять через `ldapsearch`.

### 4. Digest аутентификация

```bash
# Создать файл с хэшами (realm должен совпадать с AuthName)
sudo htdigest -c /etc/httpd/.digest "Restricted Area" admin
sudo htdigest /etc/httpd/.digest "Restricted Area" operator
```

```apacheconf
AuthType Digest
AuthName "Restricted Area"                 # realm — совпадает с htdigest
AuthDigestDomain /secure/ https://example.com/secure/
AuthDigestProvider file
AuthUserFile /etc/httpd/.digest
Require valid-user
```

### 5. Аутентификация клиентскими TLS-сертификатами (mTLS)

```apacheconf
<VirtualHost *:443>
    SSLEngine on
    SSLCertificateFile /etc/pki/tls/certs/server.crt
    SSLCertificateKeyFile /etc/pki/tls/private/server.key

    SSLCACertificateFile /etc/pki/tls/certs/client-ca.crt
    SSLVerifyClient require                   # обязательный сертификат клиента
    SSLVerifyDepth 3

    <Location "/api/clients">
        Require ssl-verify-client            # сертификат подписан доверенным CA и проверен
        # или авторизация по субъекту:
        # Require expr "%{SSL_CLIENT_S_DN_CN} == 'service-account'"
    </Location>

    # Передача субъекта приложению-бэкенду
    RequestHeader set X-Client-DN "%{SSL_CLIENT_S_DN}s"
    RequestHeader set X-Client-Cert-Serial "%{SSL_CLIENT_M_SERIAL}s"
</VirtualHost>
```

**Сопоставление сертификата с учётной записью:** не путать сертификат с логином — для маппинга на приложение использовать `%{SSL_CLIENT_S_DN}` (субъект) и `%{SSL_CLIENT_S_CN}` (CN) в переменных окружения или заголовках. Angie/Nginx mTLS-примеры см. в «См. также».

### 6. Комбинирование методов (LDAP + локальная запись)

```apacheconf
AuthBasicProvider ldap file
AuthLDAPURL "ldap://ldap.example.com/ou=People,dc=example,dc=com?uid?sub"
AuthLDAPAuthoritative off          # если LDAP не нашёл — перейти к file
AuthUserFile /etc/httpd/.local     # аварийный доступ (automation)
Require valid-user
```

### 7. Аутентификация через SQL (mod_authn_dbd) + сессии (mod_session)

Пароли и группы в БД (PostgreSQL/MySQL) — удобно для «портал с тысячью пользователей», когда источник — корпоративная БД.

```apacheconf
LoadModule dbd_module modules/mod_dbd.so
LoadModule authn_dbd_module modules/mod_authn_dbd.so
LoadModule session_module modules/mod_session.so
LoadModule session_crypto_module modules/mod_session_crypto.so

# DBD-пул
DBDriver pgsql
DBDParams "host=db.example.com user=apache pass=secret dbname=users connect_timeout=5"
DBDMin 1
DBDMax 20

<VirtualHost *:443>
    SSLEngine on
    ...

    # Запрос поиска пользователя (вернёт колонку с паролем)
    AuthDBDUserPWQuery "SELECT password FROM users WHERE login = %s"
    AuthBasicProvider dbd
    Require valid-user

    # Сессии на базе крипто-подписанной cookie
    Session On
    SessionCryptoPassphrase top-secret
    SessionCookieName session path=/; HttpOnly; Secure
    Header always set X-User "%{REMOTE_USER}s"
</VirtualHost>
```

**Аварийный мониторинг запросов к DBD:**
```bash
sudo pg_stat_statements=on  # на сервере PostgreSQL — план запроса
# или посмотреть connection pool:
sudo httpd -M | grep dbd
```

### 8. Группы из DBM (mod_authz_dbm)

```apacheconf
# Создать DBM-файл групп (формат: группа: пользователь)
htdbm -c /etc/httpd/.htgroups members
htdbm -c /etc/httpd/.htgroups admins

LoadModule authz_dbm_module modules/mod_authz_dbm.so
# Путь: префикс + имя группы
Require dbm-group admins
```

---

## Операции и команды

| Команда | Назначение | Пример вывода |
|---|---|---|
| `apache2ctl -M \| grep -E "ldap\|authn\|authz"` | Проверка модулей | `authnz_ldap_module (shared)` |
| `ldapsearch -x -H ldap://ldap.example.com -b "ou=People,dc=example,dc=com" "(uid=admin)"` | Проверка поиска и атрибутов | `dn: uid=admin,...` |
| `ldapsearch -x -H ldap://ad/ -b "DC=corp,DC=..." "(sAMAccountName=login)" sAMAccountName` | Проверка членства AD | `memberOf: CN=devops,...` |
| `htdigest /etc/httpd/.digest "Restricted" user` | Добавить/обновить digest-пользователя при unchanged realm | `Updating user ...` |
| `openssl verify -CAfile client-ca.crt client.crt` | Проверка цепочки клиентских сертификатов | `OK` |
| `curl -u admin -I https://example.com/secure/` | Проверка Basic/Digest из CLI | `HTTP/1.1 401`/`200` |

**Проверка LDAP из командной строки до правки конфига:**
```bash
ldapsearch -x -H ldap://ad.corp.example.com \
  -D "CN=svc-web,CN=Users,DC=corp,DC=example,DC=com" -w 'secret' \
  -b "DC=corp,DC=example,DC=com" "(sAMAccountName=testuser)" memberOf
```

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
|---|---|---|
| `401` в цикле для всех пользователей | `AuthLDAPURL` с пустым `attribute`/неверным base; bind-аккаунт не имеет прав поиска | Проверить `ldapsearch` вручную; исправить base/attribute |
| `AH01618: user not found` при валидном в AD | Атрибут поиска `uid` вместо `sAMAccountName`; ссылки на кандидатов в другом OU | Исправить атрибут/scope |
| Редирект/fallback не работает | `AuthLDAPAuthoritative on` запрещает переход к следующему провайдеру | Установить `off` для фоллбэка |
| `AH02032/ldap_bind` таймауты | LDAP-сервер не отвечает; превышен `LDAPConnectionTimeout` | Проверить сеть/DNS; увеличить `LDAPConnectionTimeout` |
| Digest: повторный запрос пароля | Realm в `AuthName` не совпадает с realm при `htdigest` | Пересоздать пользователя с правильным realm |
| mTLS: `400 No required SSL certificate` | `SSLVerifyClient require` + отсутствие сертификата | Проверить цепочку, `SSLVerifyDepth`, пути CA |
| mTLS: сертификат валиден, но 403 | `Require expr`/маппинг не совпадает с субъектом | Вывести `%{SSL_CLIENT_S_DN}` в лог; сверить с правилом |

---

## Лучшие практики

1.  Безопасность учётных данных: `AuthLDAPBindPassword` хранить в файле (`file:`), а не plaintext в конфиге.
2.  Перед изменением конфига проверять связность: `ldapsearch` той же командой, что и `AuthLDAPURL`.
3.  TLS к LDAP обязателен для паролей (`ldaps://` или `...?uid?sub` + `TLS`). Отключать `LDAPReferral off` при проблемах с кросс-доменным поиском.
4.  Не использовать Digest для новых систем, если нет жёсткого требования — Basic+HTTPS проще и поддерживается шире.
5.  Маппинг сертификата и пользователя (mTLS) согласовывать с приложением заранее; логировать `SSL_CLIENT_S_DN`.
6.  Тестировать на отдельном vhost (staging) с `LogLevel debug`.

---

## Дополнительная информация

### См. также

*   [HTTP-аутентификация: протоколы и механизмы](../../Networking/Protocols/HTTP/http_authentication.md) — Basic/Digest/Bearer/OAuth на уровне протокола.
*   [Настройка mTLS в Nginx](../Nginx/Security/TLS_SSL/nginx_mtls_configuration.md) — аналог клиентских сертификатов для Nginx/Angie.
*   [SSO через OIDC (mod_auth_openidc)](./apache-oidc-sso.md) — замена/дополнение к Basic при интеграции с Keycloak/Okta.
*   [Определение реального IP (mod_remoteip)](./apache_overview.md) — учёт доверенных прокси в `Require ip` и логах.
*   [Обзор Apache](./apache_overview.md) — базовая аутентификация htpasswd, SSL/TLS, модули.