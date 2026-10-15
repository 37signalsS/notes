# Apache: Аутентификация и авторизация (LDAP/AD, Digest, клиентские сертификаты)

**Актуально для:** Apache HTTP Server 2.4.x

---

## Определения

**mod_authn_core / mod_authz_core** — базовые модули ядра Apache 2.4, реализующие разделение проверки подлинности (AuthN) и контроля доступа (AuthZ). Предоставляют директивы `AuthType`, `AuthName`, логические контейнеры `<RequireAll>`, `<RequireAny>`, `<RequireNone>` и механизм наследования прав `AuthMerging`.

**mod_auth_basic** — модуль базовой аутентификации HTTP (RFC 7617): учётные данные передаются клиентом в заголовке `Authorization: Basic <base64(login:password)>`. Без шифрования TLS данные уязвимы для перехвата.

**mod_auth_digest** — модуль аутентификации HTTP Digest (RFC 7616 / RFC 2617): учётные данные передаются в виде криптографического хэша (MD5 или SHA-256) с использованием realm, серверного nonce и счётчика запросов nc. Не требует передачи открытого пароля, но уступает связке HTTPS + Basic / mTLS / OIDC по гибкости и поддержке современными клиентами.

**mod_authnz_ldap** — модуль Apache, реализующий интерфейс аутентификации (`AuthBasicProvider ldap`) и авторизации (`Require ldap-*`) через каталоги LDAP (OpenLDAP, Active Directory, FreeIPA).

**mod_ldap** — низкоуровневый модуль управления пулом постоянных LDAP-соединений, разделяемой памятью и кэшированием результатов поиска/сравнения для `mod_authnz_ldap`.

**mTLS (Mutual TLS, клиентские сертификаты)** — механизм взаимной аутентификации на транспортном уровне (`mod_ssl`, директива `SSLVerifyClient require`): клиент подтверждает подлинность закрытым ключом и сертификатом X.509, проверенным доверенным CA сервера.

**mod_authn_file** — провайдер аутентификации по плоскому файлу учетных записей `htpasswd` с хэшированными паролями (bcrypt, APR1-MD5, SHA-512).

**mod_authn_dbd** — аутентификационный провайдер через SQL-базу данных (PostgreSQL, MySQL, SQLite, Oracle) с использованием пула соединений APR DBD (`mod_dbd`). Пароли проверяются через SQL-запрос `AuthDBDUserPWQuery`.

**mod_authz_dbm / mod_authz_groupfile** — модули авторизации по группам пользователей: плоский текстовый файл (`mod_authz_groupfile`) или высокопроизводительная бинарная DBM-база (`mod_authz_dbm`, утилита `htdbm`).

**mod_session / mod_session_crypto** — модули ведения сессий на стороне сервера или в криптографически подписанных/зашифрованных cookie `Session`, устраняющие необходимость повторного вызова внешних бэкендов аутентификации на каждый HTTP-запрос.

**AuthN vs AuthZ** — разделение ответственности:
- **Authentication (AuthN)**: «Кто ты?» — проверка подлинности переданных учётных данных (модули `mod_authn_*`).
- **Authorization (AuthZ)**: «Что тебе разрешено?» — проверка прав подтверждённого пользователя на доступ к ресурсу (модули `mod_authz_*`).

---

## Архитектура и основные концепции

### Модульная матрица Apache 2.4

В Apache 2.4 процесс аутентификации и авторизации декомпозирован на независимые слои:

```
[ HTTP-запрос ]
       │
       ▼
 ┌───────────────┐
 │   AuthType    │  (Basic, Digest)
 └───────┬───────┘
         │
         ▼
 ┌──────────────────────┐
 │  Auth*Provider       │  (ldap, file, dbd) — проверка логина/пароля
 └───────┬──────────────┘
         │  (AuthN: OK -> REMOTE_USER)
         ▼
 ┌──────────────────────┐
 │  mod_authz_core      │  (<RequireAll>, <RequireAny>, <RequireNone>)
 │  Провайдеры Require  │  (ldap-group, user, ip, ssl-verify-client, expr)
 └───────┬──────────────┘
         │
         ▼
[ Доступ разрешён (200) / отклонён (401 / 403) ]
```

| Уровень | Модули | Назначение |
|---|---|---|
| Схема протокола | `mod_auth_basic`, `mod_auth_digest` | Разбор заголовков `Authorization`, генерация вызова `WWW-Authenticate` |
| Источник AuthN | `mod_authn_file`, `mod_authnz_ldap`, `mod_authn_dbd`, `mod_authn_anon` | Валидация пары логин/пароль по базе данных или каталогу |
| Ядро AuthZ | `mod_authz_core` | Логика объединения проверок (`Require`), контекстные контейнеры |
| Правила AuthZ | `mod_authz_user`, `mod_authz_groupfile`, `mod_authz_ldap`, `mod_authz_host`, `mod_authz_dbm` | Конкретные проверки: членство в группе, совпадение логина, IP-адрес |
| Транспортная безопасность | `mod_ssl` | Аутентификация по клиентским сертификатам (mTLS), экспорт TLS-переменных |

### Цепочка провайдеров и поведение Fallback

Директива `AuthBasicProvider` принимает упорядоченный список провайдеров:
```apacheconf
AuthBasicProvider ldap file
```
1. Apache вызывает первый провайдер (`ldap`). Если пользователь найден и пароль верен — доступ переходит к проверке `Require`.
2. Если пользователь в LDAP **не найден** (`AUTH_USER_NOT_FOUND`), управление автоматически передаётся следующему провайдеру (`file`).
3. Если пользователь найден в LDAP, но **введён неверный пароль**:
   - По умолчанию (`AuthLDAPBindAuthoritative on`) процесс аутентификации немедленно прерывается с ошибкой `401 Unauthorized`.
   - Если задано `AuthLDAPBindAuthoritative off`, ошибка пароля в LDAP не является терминальной: Apache переходит к проверке пользователя во вторичном провайдере (`file`). Это позволяет создавать резервные локальные учётные записи на случай рассинхронизации или аварийных работ.

> [!IMPORTANT]
> В Apache 2.4 директивы `AuthLDAPAuthoritative` и `AuthzLDAPAuthoritative` (из Apache 2.2) полностью **удалены**. За переход между источниками аутентификации отвечает список в `AuthBasicProvider` и директива `AuthLDAPBindAuthoritative`. Контроль авторизации полностью передан директивам `Require`.

### Логические контейнеры авторизации

В Apache 2.4 директивы `Require` группируются с помощью логических блоков `mod_authz_core`:

- `<RequireAll>` — логическое **И**: доступ разрешается, если все вложенные директивы завершились успехом и ни одна не вернула отказ.
- `<RequireAny>` — логическое **ИЛИ**: доступ разрешается при первом успешном правиле (по умолчанию несколько директив `Require` на одном уровне неявно работают как `<RequireAny>`).
- `<RequireNone>` — логическое **НЕ**: инвертирует результат. Если хотя бы одно вложенное правило совпало, доступ безусловно запрещается.

### Наследование прав: директива AuthMerging

При наложении конфигураций (`<Directory>`, `<Location>`, `.htaccess`) директива `AuthMerging` определяет, как объединяются секции авторизации:
- `AuthMerging Off` (по умолчанию) — директивы `Require` дочернего контекста полностью заменяют родительские правила.
- `AuthMerging And` — дочерние директивы объединяются с родительскими через виртуальный `<RequireAll>` (требуется соблюдение и старых, и новых условий).
- `AuthMerging Or` — дочерние директивы объединяются с родительскими через виртуальный `<RequireAny>` (достаточно выполнения родительских или дочерних правил).

### Архитектура пула и кэша mod_ldap

Для предотвращения деградации производительности LDAP-каталога при тысячах запросов `mod_ldap` реализует разделяемый кэш в общей памяти (SHM):
- **Search Cache**: сохраняет соответствие поискового запроса (`AuthLDAPURL` + username) полученному DN пользователя.
- **Compare/Operation Cache**: сохраняет результаты проверки членства в группах (`Require ldap-group`).
- **Пул постоянных соединений**: дескрипторы соединений к LDAP-серверу повторно используются между рабочими потоками MPM (worker/event), минимизируя задержки на установление TCP/TLS-сессий.

Параметры кэширования:
```apacheconf
LDAPSharedCacheSize 500000        # размер разделяемой памяти кэша в байтах
LDAPCacheEntries 1024             # максимум записей поиска
LDAPCacheTTL 600                  # время жизни кэша поиска в секундах (10 мин)
LDAPOpCacheEntries 1024           # максимум записей проверки групп/атрибутов
LDAPOpCacheTTL 600                # время жизни кэша операций в секундах
LDAPConnectionTimeout 5           # таймаут TCP-соединения к LDAP (сек)
LDAPTimeout 10                    # таймаут выполнения поискового запроса (сек)
```

---

## Практические сценарии и конфигурация

### 1. Интеграция с каталогом OpenLDAP / FreeIPA

Типовой сценарий проверки логина и пароля по атрибуту `uid` с использованием защищенного канала StartTLS/LDAPS.

```apacheconf
# Глобальные параметры LDAP (httpd.conf)
LoadModule ldap_module modules/mod_ldap.so
LoadModule authnz_ldap_module modules/mod_authnz_ldap.so

LDAPSharedCacheSize 500000
LDAPCacheEntries 2048
LDAPCacheTTL 300
LDAPOpCacheEntries 2048
LDAPOpCacheTTL 300
LDAPTrustedGlobalCert CA_BASE64 /etc/ssl/certs/ldap-ca.pem

<Directory "/var/www/internal">
    AuthType Basic
    AuthName "Корпоративный доступ (LDAP)"
    AuthBasicProvider ldap
    
    # URL: ldap[s]://host[:port]/base_dn?attribute?scope?filter
    AuthLDAPURL "ldaps://ldap.example.com:636/ou=People,dc=example,dc=com?uid?sub?(objectClass=inetOrgPerson)"
    
    # Сервисная учетная запись для первичного поиска DN
    AuthLDAPBindDN "cn=svc-apache,ou=Services,dc=example,dc=com"
    AuthLDAPBindPassword "exec:/bin/cat /etc/httpd/secrets/ldap-bind.secret"
    
    # Требовать успешной аутентификации любого валидного пользователя
    Require valid-user
</Directory>
```

### 2. Интеграция с Microsoft Active Directory

Особенности AD:
- Базовый атрибут пользователя: `sAMAccountName` (логин без доменного суффикса) или `userPrincipalName` (UPN вида `user@corp.example.com`).
- Отключение переходов по рефералам (`LDAPReferrals Off`): предотвращает зависание Apache при попытке связаться с контроллерами других доменов леса через порт 389/636. При необходимости работы со всем лесом подключайтесь к Global Catalog (порты 3268 LDAP / 3269 LDAPS).
- Проверка членства во вложенных группах через `AuthLDAPMaxSubGroupDepth`.

```apacheconf
<Location "/ad-secure">
    AuthType Basic
    AuthName "Active Directory Domain Access"
    AuthBasicProvider ldap
    
    # Поиск по sAMAccountName в корне домена
    AuthLDAPURL "ldaps://dc1.corp.example.com:636/DC=corp,DC=example,DC=com?sAMAccountName?sub?(&(objectCategory=person)(objectClass=user))"
    
    # Учетная запись службы (Managed Service Account или стандартный service user)
    AuthLDAPBindDN "CN=svc-httpd,OU=ServiceAccounts,DC=corp,DC=example,DC=com"
    AuthLDAPBindPassword "file:/etc/httpd/secrets/ad-bind.secret"
    
    # Отключение рефералов для предотвращения таймаутов
    LDAPReferrals Off
    
    # Настройки проверки групп
    AuthLDAPGroupAttribute member
    AuthLDAPGroupAttributeIsDN On
    AuthLDAPMaxSubGroupDepth 2
    
    # Авторизация членов доменной группы
    Require ldap-group CN=SRE-Team,OU=SecurityGroups,DC=corp,DC=example,DC=com
</Location>
```

### 3. Отказоустойчивый Fallback: LDAP + аварийный локальный файл

Сценарий обеспечивает доступ дежурному инженеру или CI/CD по локальному файлу `htpasswd`, если LDAP-сервер недоступен или учетная запись является локальной сервисной.

```apacheconf
<Directory "/var/www/critical-app">
    AuthType Basic
    AuthName "Operations Control Panel"
    
    # Список провайдеров в порядке приоритета
    AuthBasicProvider ldap file
    
    # Первичный источник: корпоративный LDAP
    AuthLDAPURL "ldaps://ldap.example.com/ou=Users,dc=example,dc=com?uid?sub"
    AuthLDAPBindDN "cn=httpd-reader,ou=Services,dc=example,dc=com"
    AuthLDAPBindPassword "file:/etc/httpd/secrets/ldap.secret"
    
    # Если пароль не подошел в LDAP — передать проверку следующему провайдеру (file)
    AuthLDAPBindAuthoritative Off
    
    # Вторичный источник: локальный аварийный файл паролей
    AuthUserFile /etc/httpd/conf/breakglass.htpasswd
    
    Require valid-user
</Directory>
```

### 4. Комплексная авторизация: IP-фильтрация + учетные данные

Реализация двух типовых политик безопасности через логические контейнеры:

#### Вариант А: Доступ из офиса без пароля, извне — обязательный LDAP-пароль (Логическое ИЛИ)
```apacheconf
<Location "/monitoring">
    AuthType Basic
    AuthName "Internal Monitoring"
    AuthBasicProvider ldap
    AuthLDAPURL "ldaps://ldap.example.com/ou=People,dc=example,dc=com?uid?sub"
    AuthLDAPBindDN "cn=svc,dc=example,dc=com"
    AuthLDAPBindPassword "file:/etc/httpd/secrets/ldap.secret"

    <RequireAny>
        # Доверенная офисная подсеть или локалхост
        Require ip 10.100.0.0/16
        Require ip 127.0.0.1 ::1
        
        # Для всех остальных — валидный сотрудник
        Require valid-user
    </RequireAny>
</Location>
```

#### Вариант Б: Строгий барьер 2-FA (Доверенный VPN-IP И членство в группе SRE)
```apacheconf
<Location "/admin/production">
    AuthType Basic
    AuthName "Production Cluster Admin"
    AuthBasicProvider ldap
    AuthLDAPURL "ldaps://ldap.example.com/ou=People,dc=example,dc=com?uid?sub"
    AuthLDAPBindDN "cn=svc,dc=example,dc=com"
    AuthLDAPBindPassword "file:/etc/httpd/secrets/ldap.secret"

    <RequireAll>
        # Требование 1: Запрос строго через VPN-шлюз
        Require ip 192.168.50.0/24
        
        # Требование 2: Пользователь обязан быть в группе devops-admins
        Require ldap-group cn=devops-admins,ou=Groups,dc=example,dc=com
        
        # Требование 3: Запрет доступа заблокированным подсетям
        <RequireNone>
            Require ip 192.168.50.250
        </RequireNone>
    </RequireAll>
</Location>
```

### 5. Аутентификация по клиентским TLS-сертификатам (mTLS)

mTLS гарантирует аутентификацию клиента на уровне криптографии TLS. Подходит для межсервисного взаимодействия (M2M) и доступа к защищенным API.

```apacheconf
<VirtualHost *:443>
    ServerName api.example.com
    
    SSLEngine on
    SSLCertificateFile /etc/pki/tls/certs/api-server.crt
    SSLCertificateKeyFile /etc/pki/tls/private/api-server.key
    
    # Доверенный удостоверяющий центр для клиентских сертификатов
    SSLCACertificateFile /etc/pki/tls/certs/internal-ca-chain.crt
    
    # Проверка списка отзыва сертификатов (CRL)
    SSLCARevocationFile /etc/pki/tls/crl/internal-ca.crl
    SSLCARevocationCheck chain
    
    # Обязательная проверка клиентского сертификата
    SSLVerifyClient require
    SSLVerifyDepth 2
    
    <Location "/v1/control">
        # Проверка факта валидности сертификата
        Require ssl-verify-client
        
        # Дополнительная авторизация по атрибутам субъекта через выражения
        Require expr "%{SSL_CLIENT_S_DN_CN} in {'deploy-daemon', 'ci-runner-01'} && %{SSL_CLIENT_I_DN_O} == 'DevOps Core CA'"
    </Location>
    
    # Безопасная передача идентификатора клиента бэкенду (Gunicorn, Node, Tomcat)
    RequestHeader set X-SSL-Client-Verify "%{SSL_CLIENT_VERIFY}s"
    RequestHeader set X-SSL-Client-DN "%{SSL_CLIENT_S_DN}s"
    RequestHeader set X-SSL-Client-CN "%{SSL_CLIENT_S_DN_CN}s"
    RequestHeader set X-SSL-Client-Serial "%{SSL_CLIENT_M_SERIAL}s"
</VirtualHost>
```

### 6. Аутентификация через SQL-базу данных (`mod_authn_dbd`) и сессии

Используется для централизованной аутентификации пользователей через существующие СУБД (PostgreSQL / MySQL) с кэшированием сессий в криптографически защищенных cookie.

```apacheconf
# 1. Загрузка модулей
LoadModule dbd_module modules/mod_dbd.so
LoadModule authn_dbd_module modules/mod_authn_dbd.so
LoadModule session_module modules/mod_session.so
LoadModule session_cookie_module modules/mod_session_cookie.so
LoadModule session_crypto_module modules/mod_session_crypto.so

# 2. Пул соединений к СУБД (PostgreSQL)
DBDriver pgsql
DBDParams "host=pg-auth.internal port=5432 dbname=auth_db user=httpd_app password=db_secret_pass connect_timeout=4"
DBDMin 2
DBDKeep 4
DBDMax 15
DBDExptime 300

<VirtualHost *:443>
    ServerName portal.example.com
    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/portal.crt
    SSLCertificateKeyFile /etc/ssl/private/portal.key

    <Location "/portal">
        AuthType Basic
        AuthName "Portal DB Login"
        AuthBasicProvider dbd
        
        # SQL-запрос для проверки пароля (%s заменяется на имя пользователя)
        # Пароль в БД должен храниться в формате хэшей crypt/apr1/sha256/bcrypt
        AuthDBDUserPWQuery "SELECT password FROM accounts WHERE username = %s AND is_active = true"
        
        Require valid-user
        
        # Включение управления сессиями
        Session On
        SessionCookieName apache_auth_session path=/portal; HttpOnly; Secure; SameSite=Strict
        SessionCryptoPassphrase "file:/etc/httpd/secrets/session-crypto.key"
        SessionMaxAge 3600
        
        # Проброс имени пользователя в заголовок для приложения
        Header always set X-Authenticated-User "%{REMOTE_USER}s"
    </Location>
</VirtualHost>
```

### 7. Аутентификация HTTP Digest (`mod_auth_digest`)

Применяется в изолированных сетях или для устаревших систем, где невозможно использовать TLS, но требуется защита от перехвата пароля в открытом виде.

```bash
# Генерация файла digest-паролей (realm обязан совпадать с AuthName)
sudo htdigest -c /etc/httpd/.htdigest "Engineering Portal" lead_sre
# → Adding password for lead_sre in realm Engineering Portal.
# → New password: ****
# → Re-type new password: ****
```

```apacheconf
<Location "/legacy-api">
    AuthType Digest
    AuthName "Engineering Portal"
    AuthDigestDomain /legacy-api/
    AuthDigestProvider file
    AuthUserFile /etc/httpd/.htdigest
    
    # Время жизни одноразового серверного nonce (секунды)
    AuthDigestNonceLifetime 120
    
    Require valid-user
</Location>
```

---

## Операции и команды

Все диагностические и эксплуатационные команды с ожидаемыми результатами вывода:

### 1. Проверка загруженных модулей и синтаксиса конфигурации

```bash
# Проверка наличия модулей аутентификации и авторизации в runtime
apachectl -M | grep -E "auth[nz]?_|ldap|ssl|session|dbd"
# → authn_core_module (static)
# → authz_core_module (static)
# → authn_file_module (shared)
# → authnz_ldap_module (shared)
# → authz_user_module (shared)
# → authz_groupfile_module (shared)
# → ldap_module (shared)
# → ssl_module (shared)

# Валидация синтаксиса конфигурационных файлов
apachectl configtest
# → Syntax OK
```

### 2. Тестирование подключения к LDAP/AD до настройки Apache

Диагностика доступности атрибутов, корректности base DN и прав сервисного аккаунта через `ldapsearch`:

```bash
# Проверка учетной записи в Active Directory (LDAPS порт 636)
ldapsearch -x -H ldaps://ad.corp.example.com:636 \
  -D "CN=svc-httpd,OU=ServiceAccounts,DC=corp,DC=example,DC=com" \
  -w "SecretPass123" \
  -b "DC=corp,DC=example,DC=com" \
  -s sub "(&(objectClass=user)(sAMAccountName=alex))" dn memberOf
# → # extended LDIF
# → dn: CN=Alex SRE,OU=Engineers,DC=corp,DC=example,DC=com
# → memberOf: CN=SRE-Team,OU=SecurityGroups,DC=corp,DC=example,DC=com
```

### 3. Проверка цепочки mTLS и TLS-рукопожатия через OpenSSL

```bash
# Тест mTLS-соединения с передачей клиентского сертификата и ключа
openssl s_client -connect api.example.com:443 \
  -cert /etc/pki/tls/certs/client.crt \
  -key /etc/pki/tls/private/client.key \
  -CAfile /etc/pki/tls/certs/internal-ca-chain.crt \
  -quiet
# → depth=2 C = US, O = Root CA
# → depth=1 C = US, O = Internal Issuing CA
# → depth=0 CN = api.example.com
# → verify return:1
```

### 4. Тестирование HTTP-аутентификации через curl

```bash
# 1. Запрос без авторизации (проверка получения 401 и заголовка realm)
curl -s -i https://internal.example.com/monitoring | head -n 8
# → HTTP/1.1 401 Unauthorized
# → Date: Mon, 14 Oct 2026 11:20:00 GMT
# → Server: Apache/2.4.62 (Unix)
# → WWW-Authenticate: Basic realm="Internal Monitoring"
# → Content-Type: text/html; charset=iso-8859-1

# 2. Успешный запрос с Basic-аутентификацией
curl -s -o /dev/null -w "%{http_code}\n" -u "alex:SecurePass" https://internal.example.com/monitoring
# → 200

# 3. Запрос с клиентским mTLS-сертификатом
curl -s -o /dev/null -w "%{http_code}\n" \
  --cert /etc/pki/tls/certs/client.crt \
  --key /etc/pki/tls/private/client.key \
  --cacert /etc/pki/tls/certs/internal-ca-chain.crt \
  https://api.example.com/v1/control
# → 200
```

### 5. Инспекция состояния кэша LDAP (mod_status / ldap-status)

Для анализа эффективности кэша поиска и операций настраивается обработчик `ldap-status`:

```apacheconf
<Location "/ldap-status">
    SetHandler ldap-status
    Require ip 127.0.0.1 ::1
</Location>
```

```bash
curl -s http://127.0.0.1/ldap-status | grep -A 5 "Cache"
# → LDAP Shared Cache Info:
# → Total entries: 142
# → Cache hits: 18490
# → Cache misses: 145
# → Cache hit ratio: 99.2%
```

---

## Типичные ошибки и диагностика

### Коды ошибок Apache (AH) и решения

| Симптом / AH-код | Возможная причина | Диагностика | Решение |
|---|---|---|---|
| `401 Unauthorized`<br>`AH01618: user not found: /path` | Неверный базовый DN или атрибут поиска логина (`uid` вместо `sAMAccountName`) | Выполнить `ldapsearch` с фильтром из `AuthLDAPURL` | Сверить атрибут пользователя в каталоге; для AD использовать `sAMAccountName` |
| `401 Unauthorized`<br>`AH01617: user ...: authentication failure for "/path": Password Mismatch` | Неверный пароль пользователя или bind-пользователь не имеет прав чтения атрибута | Проверить ручной `ldapsearch` bind от имени самого пользователя | Проверить пароль; убедиться в отсутствии спецсимволов, ломающих конфиг; проверить статус блокировки в AD |
| `500 Internal Server Error`<br>`AH02032: Ldap cache operation failed` / таймаут | Недоступен LDAP-хост, блокировка фаерволом или исчерпан `LDAPConnectionTimeout` | Проверить TCP связность: `nc -zv ldap.example.com 636` | Увеличить `LDAPConnectionTimeout 10`; проверить DNS и маршрутизацию к контроллерам |
| Зависание запросов на 30–60 сек<br>`AH01695: auth_ldap authenticate: ... [LDAP: referral]` | Попытка перехода по рефералам в многодоменном лесу Active Directory | `LogLevel authnz_ldap:debug` показывает обращения к недоступным контроллерам | Указать директиву `LDAPReferrals Off` или использовать порт Global Catalog (`3268`/`3269`) |
| `403 Forbidden`<br>`AH01631: user ...: authorization failure to path "/path":` | Пользователь успешно аутентифицирован, но не проходит условие `Require` (членство в группе/IP) | Проверить вывод `memberOf` пользователя и формат имени группы | Для `Require ldap-group` указывать полный DN группы; проверить `AuthLDAPGroupAttributeIsDN On` |
| mTLS: `400 Bad Request`<br>`No required SSL certificate was sent` | Клиент не передал сертификат, либо сертификат выпущен CA, отсутствующим в `SSLCACertificateFile` | Проверить список CA, запрашиваемых сервером: `openssl s_client -showcerts` | Добавить корневой и промежуточный сертификаты выпускающего CA в файл `SSLCACertificateFile` |
| mTLS: `403 Forbidden`<br>`AH02224: Certificate Verification: Error (23): certificate revoked` | Клиентский сертификат отозван и включена проверка `SSLCARevocationCheck` | Проверить серийный номер сертификата в CRL: `openssl crl -in ca.crl -text -noout` | Выпустить новый сертификат; обновить CRL-файл на сервере |
| Fallback не срабатывает<br>`AH01617` блокирует локального пользователя | Директива `AuthLDAPBindAuthoritative on` запрещает переход к `AuthBasicProvider ... file` | Проверить директивы авторизации в блоке `<Directory>` | Установить `AuthLDAPBindAuthoritative Off` для передачи управления локальному файлу |

### Таргетированная отладка через LogLevel

Включение глобального `LogLevel trace8` заливает журнал терабайтами системного шума. Рекомендуется точечное профилирование затронутых модулей:

```apacheconf
# Точечный дебаг аутентификации, LDAP и SSL в контексте VirtualHost
<VirtualHost *:443>
    ServerName secure.example.com
    
    # Базовый уровень для всех модулей — предупреждения
    LogLevel warn
    
    # Детальная трассировка подсистем доступа
    LogLevel authn_core:trace6 authz_core:trace6 authnz_ldap:trace6 ldap:trace6 ssl:trace4
    
    ErrorLog /var/log/httpd/secure_error.log
    CustomLog /var/log/httpd/secure_access.log combined
</VirtualHost>
```

Анализ журнала:
```bash
tail -f /var/log/httpd/secure_error.log | grep -E "authnz_ldap|authz_core|ssl"
```

---

## Рекомендации и Best Practices

### 1. Безопасность сервисных учетных записей (Bind Credentials)

- **Никогда не хранить пароли открытым текстом в основном конфигурационном файле.** Используйте конструкцию `AuthLDAPBindPassword "file:/etc/httpd/secrets/ldap.secret"` или `exec:/usr/local/bin/get-secret.sh`.
- Файл с секретом должен принадлежать пользователю `root` с правами доступа `0400` или `0600`:
  ```bash
  sudo chown root:root /etc/httpd/secrets/ldap.secret
  sudo chmod 0400 /etc/httpd/secrets/ldap.secret
  ```
- Сервисная учетная запись LDAP (`svc-apache`) должна обладать минимальными привилегиями: строго права на чтение (`Read`) пользовательских учетных записей и членства в группах без прав изменения каталога.

### 2. Защита от перехвата и Brute-Force

- **Запрет базовой аутентификации без TLS**: передача `Authorization: Basic` по незашифрованному HTTP (порт 80) раскрывает пароли пользователей в открытом виде (Base64 декодируется мгновенно). Все эндпоинты с аутентификацией обязаны быть защищены постоянным редиректом на HTTPS:
  ```apacheconf
  <VirtualHost *:80>
      ServerName app.example.com
      Redirect permanent / https://app.example.com/
  </VirtualHost>
  ```
- **Интеграция с fail2ban**: частые 401 ошибки в журнале `CustomLog` должны приводить к временной блокировке IP-адреса на уровне фаервола (`nftables` / `iptables`), снижая нагрузку на контроллеры домена LDAP.

### 3. Оптимизация производительности mod_ldap под высокую нагрузку

- **Связка с MPM event/worker**: убедитесь, что `LDAPSharedCacheSize` достаточен для удержания активных пользователей. Для пула в 5000 сотрудников выделите 1–2 МБ (`LDAPSharedCacheSize 2000000`).
- **Таймауты сети**: значения по умолчанию для `LDAPConnectionTimeout` могут приводить к зависанию рабочих процессов при сетевых сбоях. Всегда явно задавайте:
  ```apacheconf
  LDAPConnectionTimeout 5
  LDAPTimeout 10
  ```
- **Использование LDAPS vs StartTLS**: прямое соединение LDAPS (порт 636) быстрее и надежнее в контексте пула постоянных соединений Apache, чем согласование StartTLS поверх открытого порта 389.

### 4. Контроль наследования прав

- При работе со сложными структурами каталогов явно указывайте директиву `AuthMerging`, чтобы дочерний файл `.htaccess` или поддиректория не сняли требования обязательной авторизации.
- По умолчанию проверяйте, что директива `AllowOverride None` отключена для критических локаций, исключая несанкционированное изменение правил доступа через пользовательские файлы `.htaccess`.

---

## Дополнительная информация

### См. также

* [Обзор Apache HTTP Server](./apache_overview.md) — базовая архитектура, MPM-модели, виртуальные хосты и конфигурация `htpasswd`.
* [Порядок слияния конфигурации Apache](./apache-config-merge-order.md) — приоритеты и правила наследования секций `<Directory>`, `<Location>` и директивы `AuthMerging`.
* [Харденинг Apache](./apache_hardening.md) — защищенная конфигурация TLS, заголовки безопасности, минимизация раскрытия информации.
* [SSO через OpenID Connect (mod_auth_openidc)](./apache-oidc-sso.md) — современная федеративная аутентификация через Keycloak, Okta, GitLab.
* [Продвинутый Reverse Proxy в Apache](./apache-reverse-proxy-advanced.md) — безопасная передача заголовков аутентификации (`X-Forwarded-User`, mTLS) бэкендам.
* [HTTP-аутентификация: протоколы и механизмы](../../Networking/Protocols/HTTP/http_authentication.md) — теоретические основы RFC для Basic, Digest, Bearer токенов.
* [Настройка Mutual TLS (mTLS) в Nginx](../Nginx/Security/TLS_SSL/nginx_mtls_configuration.md) — сопоставление подходов к реализации mTLS в других веб-серверах.