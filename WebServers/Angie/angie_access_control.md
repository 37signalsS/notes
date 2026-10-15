# Контроль доступа в Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

**Контроль доступа (Access Control)** — совокупность механизмов и политик веб-сервера для идентификации, аутентификации и авторизации клиентов при обращении к защищаемым ресурсам. Angie реализует контроль доступа на основе сетевых атрибутов (L3/L4 адресация), учетных записей (HTTP Basic Auth, каталоги LDAP/Active Directory, системные службы PAM), криптографических токенов (JWT, OIDC) и внешних служб авторизации (подзапросы `auth_request`).

**Ключевые модули Angie для контроля доступа:**
*   **ngx_http_access_module:** встроенный модуль фильтрации запросов по IP-адресам и CIDR-подсетям (`allow`, `deny`).
*   **ngx_http_auth_basic_module:** встроенный модуль базовой HTTP-аутентификации с проверкой имени и пароля по файлу учетных данных (RFC 7617).
*   **ngx_http_auth_request_module:** встроенный модуль авторизации на основе результата внутреннего HTTP-подзапроса к внешнему сервису или njs-скрипту.
*   **ngx_http_realip_module:** встроенный модуль подмены адреса клиента на реальный IP, полученный из заголовков доверенных промежуточных прокси и балансировщиков.
*   **ngx_http_auth_jwt_module:** динамический внешний модуль (пакет `angie-module-auth-jwt` / `angie-pro-module-auth-jwt`) для валидации токенов JSON Web Token (JWS/JWT) по локальным ключам или JWKS-эндпоинтам с проверкой claims.
*   **ngx_http_auth_ldap_module:** динамический внешний модуль (пакет `angie-module-auth-ldap` / `angie-pro-module-auth-ldap`) для корпоративной аутентификации через серверы OpenLDAP и Microsoft Active Directory.
*   **ngx_http_auth_pam_module:** динамический внешний модуль (пакет `angie-module-auth-pam` / `angie-pro-module-auth-pam`) для аутентификации через системные интерфейсы Linux Pluggable Authentication Modules.

## Базовые концепции

### Фазы обработки и иерархия контекстов
Контроль доступа в архитектуре Angie выполняется на фазе `NGX_HTTP_ACCESS_PHASE` — после определения конфигурации виртуального хоста (`server`), сопоставления пути (`location`) и перезаписи URI (`rewrite`), но строго до передачи запроса генераторам контента или проксирования в upstream (`NGX_HTTP_CONTENT_PHASE`).

Директивы контроля доступа объявляются на уровнях `http`, `server`, `location` и `limit_except`.
> **Важное правило наследования:** задание любой директивы модуля контроля доступа (например, `allow` или `auth_basic`) в дочернем контексте **полностью переопределяет**, а не дополняет правила этого же модуля, заданные в родительском блоке.

### Порядок обработки правил (Allow / Deny)
Директивы модуля `ngx_http_access_module` проверяются строго сверху вниз до первого совпадения:
1. Если IP-адрес клиента подпадает под директиву `allow`, проверка модуля завершается успехом, доступ разрешается.
2. Если IP-адрес подпадает под директиву `deny`, проверка немедленно прекращается, клиенту возвращается статус `403 Forbidden`.
3. Если совпадений не обнаружено, наследуются правила родительского блока. При отсутствии правил на всех уровнях доступ разрешен по умолчанию.

Для исключения случайного открытия периметра списки правил IP-фильтрации всегда закрываются терминальной директивой `deny all;`.

### Комбинирование проверок (директива satisfy)
Директива `satisfy` задает логику объединения результатов различных модулей контроля доступа (например, `access`, `auth_basic`, `auth_request`, `auth_jwt`):
*   `satisfy all;` *(поведение по умолчанию)* — доступ предоставляется только в случае, если проверки **каждого** активного модуля завершились успешно. Клиент должен удовлетворять сетевому фильтру IP **и** предоставить валидные учетные данные.
*   `satisfy any;` — доступ предоставляется, если проверка завершилась успешно **хотя бы в одном** из модулей. Типичный сценарий: клиенты из доверенной офисной сети или VPN проходят без пароля (по IP), а внешние пользователи обязаны пройти аутентификацию по логину и паролю.

### Взаимодействие с балансировщиками и Real-IP
В производственной инфраструктуре DevOps/SRE сервер Angie обычно расположен за пограничными балансировщиками (HAProxy, Keepalived LVS) или внешними прокси. В этом случае переменная `$remote_addr` содержит IP-адрес самого балансировщика, а не конечного пользователя.

Модуль `ngx_http_realip_module` заменяет адрес клиента на значение из заголовка `X-Forwarded-For` или `X-Real-IP`, переданного балансировщиком. Проверка `allow`/`deny` выполняется над реальным адресом **только тогда**, когда запрос поступил из доверенной сети, указанной в `set_real_ip_from`.

### Механизм подзапросов auth_request
Модуль `ngx_http_auth_request_module` приостанавливает обработку клиентского запроса и инициирует внутренний синхронный HTTP-подзапрос (subrequest) к выделенному сервису авторизации или внутреннему location:
*   Код ответа `2xx` — подзапрос успешен, Angie возобновляет обработку оригинального запроса и отправляет его в целевой upstream.
*   Код ответа `401 Unauthorized` — доступ отклонен, Angie возвращает клиенту код `401` и пробрасывает заголовок `WWW-Authenticate`, полученный от авторизатора.
*   Код ответа `403 Forbidden` — доступ отклонен, клиенту возвращается код `403`.
*   Любой другой код (включая `5xx` или таймаут) — Angie возвращает клиенту статус `500 Internal Server Error`.
*   Директива `auth_request_set` извлекает данные из заголовков ответа авторизатора (переменные `$upstream_http_*`) и сохраняет их в переменные запроса для проброса в бэкенд приложения.

## Практические сценарии

### Сценарий 1: Ограничение доступа по IP с поддержкой Real-IP за балансировщиком

Сценарий защищает панель управления или закрытый API, учитывая реальный IP-адрес клиента при работе за HAProxy или пограничным Nginx/Angie.

```nginx
http {
    # Доверенные адреса внутренних балансировщиков
    set_real_ip_from 10.100.0.0/24;
    set_real_ip_from 192.168.10.15;
    
    # Заголовок с клиентским IP и рекурсивный поиск доверенного источника
    real_ip_header X-Forwarded-For;
    real_ip_recursive on;

    server {
        listen 80;
        server_name internal.example.com;

        location /admin/ {
            # Разрешаем доступ административным подсетям и localhost
            allow 192.168.1.0/24;
            allow 10.20.30.0/24;
            allow 127.0.0.1;
            allow ::1;

            # Запрещаем доступ всем остальным источникам
            deny all;

            proxy_pass http://backend_admin;
        }
    }
}
```

**Верификация:**
```bash
# Проверка конфигурации на корректность синтаксиса
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Запрос с разрешенного IP (эмуляция через доверенный балансировщик 192.168.10.15)
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Forwarded-For: 192.168.1.50" http://internal.example.com/admin/
# → 200

# Запрос с запрещенного публичного IP
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Forwarded-For: 203.0.113.10" http://internal.example.com/admin/
# → 403
```

### Сценарий 2: Разграничение доступа по HTTP-методам (limit_except)

Для публичных REST API часто требуется разрешить чтение (`GET`, `HEAD`) всем клиентам без ограничений, а методы модификации данных (`POST`, `PUT`, `DELETE`, `PATCH`) защитить паролем или ограничить доверенной сетью разработки.

```nginx
location /api/v1/resources/ {
    # Для всех методов, кроме GET и HEAD, требуются права администратора
    limit_except GET HEAD {
        allow 192.168.1.0/24;
        deny all;

        auth_basic "API Write Access";
        auth_basic_user_file /etc/angie/.htpasswd_writers;
    }

    proxy_pass http://api_backend;
}
```

**Верификация:**
```bash
# Чтение ресурса без авторизации разрешено всем
curl -s -o /dev/null -w "%{http_code}\n" -X GET http://localhost/api/v1/resources/
# → 200

# Попытка создания ресурса без аутентификации отклоняется
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost/api/v1/resources/
# → 401

# Запрос с валидными учетными данными из разрешенной подсети
curl -s -o /dev/null -w "%{http_code}\n" -u "writer:SecretPass2026" -X POST http://localhost/api/v1/resources/
# → 201
```

### Сценарий 3: Базовая HTTP-аутентификация (auth_basic) с безопасным хешированием

Базовая аутентификация передает логин и пароль в заголовке `Authorization: Basic <base64>`, поэтому ее применение допустимо исключительно поверх защищенного соединения ([TLS/HTTPS](./angie_tls_setup.md)).

**1. Генерация файла паролей с использованием стойкого алгоритма bcrypt:**
```bash
# Создание нового файла паролей с пользователем 'sreadmin'
sudo htpasswd -B -C 10 -c /etc/angie/.htpasswd sreadmin
# → New password: 
# → Re-type new password: 
# → Adding password for user sreadmin

# Добавление дополнительного пользователя без перезаписи файла
sudo htpasswd -B -C 10 /etc/angie/.htpasswd devops
# → Adding password for user devops

# Установка безопасных прав (чтение только для владельца и группы angie)
sudo chown root:angie /etc/angie/.htpasswd
sudo chmod 0640 /etc/angie/.htpasswd
ls -la /etc/angie/.htpasswd
# → -rw-r----- 1 root angie 128 Oct 14 13:00 /etc/angie/.htpasswd
```

**2. Конфигурация виртуального хоста в Angie:**
```nginx
server {
    listen 443 ssl;
    server_name monitor.example.com;

    ssl_certificate /etc/ssl/certs/monitor.crt;
    ssl_certificate_key /etc/ssl/private/monitor.key;

    location / {
        auth_basic "Restricted Monitoring Area";
        auth_basic_user_file /etc/angie/.htpasswd;

        proxy_pass http://prometheus_ui;
    }
}
```

### Сценарий 4: Комбинированный доступ через satisfy any (Офис без пароля, удаленно — по паролю)

Распространенный корпоративный шаблон: сотрудники в локальной сети компании или через корпоративный VPN заходят во внутренние дашборды напрямую, а при доступе из внешнего интернета требуется ввод пароля.

```nginx
location /internal-dashboards/ {
    satisfy any;

    # Белый список офисных подсетей и VPN
    allow 10.0.0.0/8;
    allow 172.16.0.0/12;
    allow 192.168.0.0/16;
    deny all;

    # Внешние клиенты аутентифицируются по логину и паролю
    auth_basic "Corporate Access";
    auth_basic_user_file /etc/angie/.htpasswd_corp;

    proxy_pass http://dashboards_backend;
}
```

### Сценарий 5: Авторизация через подзапрос (auth_request)

#### Вариант А: Интеграция с микросервисом авторизации (Auth Sidecar / Gateway)
Angie отправляет подзапрос в auth-сервис, передавая оригинальные заголовки и извлекая идентификатор пользователя для передачи в бэкенд.

```nginx
location /private/ {
    auth_request /_auth_verify;

    # Извлечение заголовка ответа авторизатора в переменную Angie
    auth_request_set $user_id $upstream_http_x_authenticated_user;
    auth_request_set $user_roles $upstream_http_x_authenticated_roles;

    # Передача контекста пользователя в основной бэкенд
    proxy_set_header X-User-Id $user_id;
    proxy_set_header X-User-Roles $user_roles;

    proxy_pass http://app_backend;
}

location = /_auth_verify {
    internal;
    proxy_pass http://127.0.0.1:9080/auth/verify;

    # Отключение передачи тела оригинального запроса в auth-сервис
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";

    # Проброс исходного пути и параметров
    proxy_set_header X-Original-URI $request_uri;
    proxy_set_header X-Original-Method $request_method;
    proxy_set_header X-Real-IP $remote_addr;
}
```

#### Вариант Б: Легковесная авторизация через JavaScript (njs)
Без развертывания отдельного сетевого сервиса: проверка API-токена прямо в контексте воркера Angie. Подробнее о возможностях языка — в руководстве по [Скриптованию на njs в Angie](./angie-njs.md).

```javascript
// /etc/angie/scripts/auth_validator.js
function authorizeApiKey(r) {
    var apiKey = r.headersIn['X-API-Key'];
    
    // Проверка наличия и структуры ключа
    if (!apiKey) {
        r.return(401, "API Key required\n");
        return;
    }

    if (apiKey === "env-prod-secret-key-9921") {
        r.headersOut['X-Client-Tier'] = "premium";
        r.return(204);
    } else {
        r.return(403, "Access Denied: Invalid Key\n");
    }
}

export default { authorizeApiKey };
```

```nginx
# В основном контексте main:
# load_module modules/ngx_http_js_module.so;

http {
    js_import /etc/angie/scripts/auth_validator.js;

    server {
        listen 80;

        location /api/v2/ {
            auth_request /_js_verify;
            auth_request_set $client_tier $upstream_http_x_client_tier;

            proxy_set_header X-Client-Tier $client_tier;
            proxy_pass http://api_backend;
        }

        location = /_js_verify {
            internal;
            js_content auth_validator.authorizeApiKey;
        }
    }
}
```

### Сценарий 6: Валидация JWT (JSON Web Token) со статическими ключами и JWKS

Модуль `ngx_http_auth_jwt_module` валидирует подпись токена без сетевых обращений на каждый запрос, проверяет срок жизни (`exp`) и извлекает Claims.

**1. Установка пакета модуля:**
```bash
# Для Angie OSS в Debian/Ubuntu
sudo apt install -y angie-module-auth-jwt
# → Setting up angie-module-auth-jwt ...

# Для Angie PRO
# sudo apt install -y angie-pro-module-auth-jwt
```

**2. Конфигурация в Angie:**
```nginx
# В /etc/angie/angie.conf на верхнем уровне main:
load_module modules/ngx_http_auth_jwt_module.so;

http {
    server {
        listen 443 ssl;
        server_name api.example.com;

        location /secure-api/ {
            # Задание realm и пути к публичным ключам (JWKS или PEM)
            auth_jwt "Secured API Realm";
            auth_jwt_key_file /etc/angie/keys/idp_jwks.json;
            
            # Допустимое расхождение системных часов (clock skew)
            auth_jwt_leeway 30s;

            # Проверка конкретного значения claim (например, scope или aud)
            auth_jwt_require $jwt_payload_iss "https://auth.example.com";
            auth_jwt_require $jwt_payload_role "admin" "operator";

            # Проброс имени пользователя из JWT sub в бэкенд
            proxy_set_header X-Auth-Subject $jwt_payload_sub;
            proxy_pass http://backend_cluster;
        }
    }
}
```

Полный протокольный OIDC-поток с аутентификацией пользователей через браузер документирован в [Аутентификация через OpenID Connect в Angie](./angie-oidc.md).

### Сценарий 7: Интеграция с корпоративным каталогом LDAP / Active Directory

Модуль `ngx_http_auth_ldap_module` обеспечивает проверку учетных записей сотрудников с поддержкой нескольких контроллеров домена и кэширования в памяти воркера.

**1. Установка пакета:**
```bash
sudo apt install -y angie-module-auth-ldap
# → Setting up angie-module-auth-ldap ...
```

**2. Конфигурация:**
```nginx
load_module modules/ngx_http_auth_ldap_module.so;

http {
    # Определение пула контроллеров домена Active Directory
    ldap_server ad_primary {
        url ldap://dc1.corp.example.com:389/dc=corp,dc=example,dc=com?sAMAccountName?sub?(objectClass=person);
        binddn "cn=svc_angie,ou=ServiceAccounts,dc=corp,dc=example,dc=com";
        binddn_passwd "StrongSvcSecret2026";
        
        # Разрешать вход только членам определенной группы безопасности
        group_attribute member;
        group_attribute_is_dn on;
        require group "cn=SRE-Engineers,ou=Groups,dc=corp,dc=example,dc=com";

        # Кэширование успешных проверок в памяти воркера для разгрузки DC
        cache max=5000 inactive=15m;
        connect_timeout 5s;
        bind_timeout 5s;
        request_timeout 5s;
    }

    ldap_server ad_secondary {
        url ldap://dc2.corp.example.com:389/dc=corp,dc=example,dc=com?sAMAccountName?sub?(objectClass=person);
        binddn "cn=svc_angie,ou=ServiceAccounts,dc=corp,dc=example,dc=com";
        binddn_passwd "StrongSvcSecret2026";
        group_attribute member;
        group_attribute_is_dn on;
        require group "cn=SRE-Engineers,ou=Groups,dc=corp,dc=example,dc=com";
        cache max=5000 inactive=15m;
        connect_timeout 5s;
        bind_timeout 5s;
    }

    server {
        listen 443 ssl;
        server_name kbn.corp.example.com;

        location / {
            auth_ldap "Corporate AD Authentication";
            # Отказоустойчивый опрос серверов каталога
            auth_ldap_servers ad_primary;
            auth_ldap_servers ad_secondary;

            proxy_pass http://kibana_upstream;
        }
    }
}
```

### Сценарий 8: Системная аутентификация Linux (PAM)

Позволяет локальным системным администраторам входить в аварийные консоли управления по учетным записям ОС Linux.

**1. Установка пакета модуля:**
```bash
sudo apt install -y angie-module-auth-pam
# → Setting up angie-module-auth-pam ...
```

**2. Настройка политики PAM (`/etc/pam.d/angie`):**
```text
# /etc/pam.d/angie
auth    required    pam_unix.so
account required    pam_unix.so
```

**3. Настройка разрешений ОС для рабочего процесса:**
Рабочие процессы Angie работают от пользователя `angie` (или `nginx`). Чтобы процесс мог проверять пароли локальных пользователей против базы хэшей `/etc/shadow`, пользователь `angie` добавляется в системную группу `shadow`:
```bash
sudo usermod -aG shadow angie
id angie
# → uid=998(angie) gid=998(angie) groups=998(angie),42(shadow)
```

**4. Конфигурация виртуального хоста:**
```nginx
load_module modules/ngx_http_auth_pam_module.so;

http {
    server {
        listen 443 ssl;
        server_name emergency.local;

        location /recovery-console/ {
            auth_pam "Host Admin Authentication";
            auth_pam_service_name "angie";

            proxy_pass http://127.0.0.1:9090;
        }
    }
}
```

### Сценарий 9: Гео-фильтрация через MaxMind GeoIP2 и директиву map

Блокировка трафика из нежелательных регионов на основе актуальной бинарной базы данных `Country.mmdb`.

```nginx
# В блоке main:
# load_module modules/ngx_http_geoip2_module.so;

http {
    geoip2 /etc/angie/geo/Country.mmdb {
        $geoip2_country_code default=XX country iso_code;
    }

    # Безопасное сопоставление через map без использования директивы if
    map $geoip2_country_code $access_allowed {
        default  0;
        RU       1;
        BY       1;
        KZ       1;
    }

    server {
        listen 80;
        server_name app.example.com;

        # Разрешаем доступ из локальной сети в обход гео-фильтра
        satisfy any;
        allow 192.168.0.0/16;
        allow 10.0.0.0/8;
        deny all;

        location / {
            if ($access_allowed = 0) {
                return 403;
            }
            proxy_pass http://app_cluster;
        }
    }
}
```

## Операции и команды

### Верификация синтаксиса и перезагрузка конфигурации
```bash
# Тестирование синтаксиса перед применением
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Бесшовная перезагрузка конфигурации без обрыва соединений
sudo systemctl reload angie
# → 

# Проверка статуса сервиса
sudo systemctl status angie --no-pager
# → ● angie.service - Angie - high performance web server
# →    Loaded: loaded (/lib/systemd/system/angie.service; enabled; vendor preset: enabled)
# →    Active: active (running)
```

### Управление базой учетных данных htpasswd
```bash
# Создание нового файла паролей (алгоритм bcrypt, 10 раундов)
sudo htpasswd -B -C 10 -c /etc/angie/.htpasswd techlead
# → Adding password for user techlead

# Добавление инженера без перезаписи существующего файла
sudo htpasswd -B -C 10 /etc/angie/.htpasswd oncall
# → Adding password for user oncall

# Удаление учетной записи
sudo htpasswd -D /etc/angie/.htpasswd oncall
# → Deleting password for user oncall

# Проверка корректности введенного пароля
sudo htpasswd -bv /etc/angie/.htpasswd techlead "MasterSecretPass"
# → Password for user techlead correct.
```

### Анализ инцидентов контроля доступа по логам
```bash
# Просмотр последних 10 попыток с отказом в аутентификации (401)
awk '$9 == 401 {print $1, $4, $7, $9}' /var/log/angie/access.log | tail -n 10
# → 192.0.2.14 [14/Oct/2026:13:01:10 "GET /admin/ HTTP/1.1" 401
# → 192.0.2.14 [14/Oct/2026:13:01:15 "GET /admin/ HTTP/1.1" 401

# Топ-5 IP-адресов, получивших отказ в доступе (403 Forbidden)
awk '$9 == 403 {print $1}' /var/log/angie/access.log | sort | uniq -c | sort -rn | head -n 5
# →    142 203.0.113.88
# →     64 198.51.100.4
# →     12 192.168.1.99

# Поиск ошибок PAM и LDAP в журнале ошибок Angie
grep -E "PAM|ldap" /var/log/angie/error.log | tail -n 5
# → 2026/10/14 13:02:11 [error] 14201#14201: *105 http_auth_ldap: ldap_simple_bind_s() failed (49: Invalid credentials)
```

### Тестирование аутентификации через curl
```bash
# Проверка требования аутентификации (ожидается 401 с WWW-Authenticate)
curl -s -I http://localhost/admin/ | grep -E "HTTP/|WWW-Authenticate"
# → HTTP/1.1 401 Unauthorized
# → WWW-Authenticate: Basic realm="Restricted Monitoring Area"

# Успешная передача учетных данных
curl -s -o /dev/null -w "%{http_code}\n" -u "techlead:MasterSecretPass" http://localhost/admin/
# → 200

# Тестирование доступа с передачей JWT в заголовке Authorization
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..." https://api.example.com/secure-api/
# → 200
```

### Диагностика сетевой доступности LDAP / Active Directory
```bash
# Проверка сетевой связности по порту LDAP/LDAPS
nc -zvw3 dc1.corp.example.com 389
# → Connection to dc1.corp.example.com 389 port [tcp/ldap] succeeded!

# Тестирование сервисной учетной записи binddn
ldapwhoami -x -H ldap://dc1.corp.example.com:389 -D "cn=svc_angie,ou=ServiceAccounts,dc=corp,dc=example,dc=com" -w "StrongSvcSecret2026"
# → u:CORP\svc_angie

# Поиск пользователя в каталоге
ldapsearch -x -H ldap://dc1.corp.example.com:389 -D "cn=svc_angie,ou=ServiceAccounts,dc=corp,dc=example,dc=com" -w "StrongSvcSecret2026" -b "dc=corp,dc=example,dc=com" "(sAMAccountName=jdoe)" mail
# → # jdoe, Users, corp.example.com
# → dn: cn=John Doe,ou=Users,dc=corp,dc=example,dc=com
# → mail: jdoe@example.com
```

### Тестирование сервиса PAM
```bash
# Проверка синтаксиса и аутентификации через утилиту pamtester
pamtester angie sreadmin authenticate
# → Password: 
# → pamtester: successfully authenticated
```

## Диагностика и устранение неисправностей

### 403 Forbidden при корректном клиентском IP-адресе
*   **Симптом:** Клиент с легитимным адресом получает ошибку `403 Forbidden`, хотя адрес присутствует в директивах `allow`.
*   **Причина:** 
    1. Между клиентом и Angie установлен балансировщик (L4/L7), и проверка выполняется над адресом балансировщика, а не клиента.
    2. Родительский блок `server` содержит правила `allow`/`deny`, которые были непреднамеренно переопределены правилом в блоке `location`.
*   **Диагностика:**
    ```bash
    # Проверка реального IP, с которого Angie видит запрос
    grep "403" /var/log/angie/access.log | tail -n 1
    # → 10.100.0.1 - - [14/Oct/2026:13:05:00 +0300] "GET /admin/ HTTP/1.1" 403 153 "-" "curl/7.88.1"
    ```
*   **Решение:** Настройте модуль `ngx_http_realip_module`: добавьте `set_real_ip_from <IP_балансировщика>; real_ip_header X-Forwarded-For; real_ip_recursive on;`.

### 401 Unauthorized при Basic Auth
*   **Симптом:** При передаче заведомо верного логина и пароля сервер возвращает `401 Unauthorized`.
*   **Причина:** 
    1. Недостаточные права доступа рабочего процесса `angie` на чтение файла `.htpasswd`.
    2. Использование несовместимого алгоритма хеширования (например, MD5 или SHA1 при отключенной поддержке в ОС) или повреждение файла.
*   **Диагностика:**
    ```bash
    # Проверка журнала ошибок Angie
    grep -E "auth_basic|htpasswd" /var/log/angie/error.log | tail -n 3
    # → 2026/10/14 13:06:22 [error] 14201#14201: *112 open() "/etc/angie/.htpasswd" failed (13: Permission denied)
    ```
*   **Решение:** Назначьте права на чтение группе веб-сервера: `sudo chown root:angie /etc/angie/.htpasswd && sudo chmod 0640 /etc/angie/.htpasswd`. Перегенерируйте пароль через `htpasswd -B`.

### 500 Internal Server Error при использовании auth_request
*   **Симптом:** Пользователь обращается к защищенному эндпоинту и получает `500 Internal Server Error` вместо `401` или `403`.
*   **Причина:** Сервис авторизации, указанный в `auth_request`, недоступен, возвращает код ошибки `5xx`, сбрасывает соединение или зависает по таймауту.
*   **Диагностика:**
    ```bash
    grep "auth request" /var/log/angie/error.log | tail -n 2
    # → 2026/10/14 13:07:40 [error] 14201#14201: *120 auth request unexpected status: 502 while sending to client
    ```
*   **Решение:** 
    1. Проверьте работоспособность сервиса авторизации: `curl -I http://127.0.0.1:9080/auth/verify`.
    2. В `location = /_auth_verify` убедитесь, что передача тела отключена: `proxy_pass_request_body off; proxy_set_header Content-Length "";`.
    3. При необходимости настройте перехват ошибок авторизатора через `error_page 500 502 503 = /auth_fallback;`.

### Ошибки валидации JWT (401 / 403)
*   **Симптом:** Клиент передает токен, но Angie отклоняет его с кодом `401` (`"API Access"`) или `403`.
*   **Причина:**
    1. Рассинхронизация времени между сервером выдачи токенов (IdP) и сервером Angie (нарушение валидации claim `exp` или `nbf`).
    2. Алгоритм в заголовке JWT (`alg`) отличается от поддерживаемого в файле ключей.
    3. Отсутствует или не совпадает claim, указанный в директиве `auth_jwt_require`.
*   **Диагностика:**
    ```bash
    # Проверка статуса службы синхронизации времени
    timedatectl status
    # → System clock synchronized: yes
    # → NTP service: active

    # Проверка соответствия ключа в JWKS
    cat /etc/angie/keys/idp_jwks.json | jq '.keys[] | {kid: .kid, alg: .alg, kty: .kty}'
    # → { "kid": "key-2026-01", "alg": "RS256", "kty": "RSA" }
    ```
*   **Решение:** Установите директиву `auth_jwt_leeway 30s;` для компенсации расхождения времени. Убедитесь, что IdP выпускает токены с корректным `kid` и алгоритмом, зарегистрированным в JWKS.

### Ошибки аутентификации PAM: Permission denied
*   **Симптом:** В логах Angie появляется сообщение `pam_authenticate() failed (7: Authentication failure)` или ошибка доступа к shadow-файлу.
*   **Причина:** Рабочий процесс `angie` не имеет привилегий на чтение хешей паролей из `/etc/shadow`.
*   **Диагностика:**
    ```bash
    ls -l /etc/shadow
    # → -rw-r----- 1 root shadow 1240 Oct 10 10:00 /etc/shadow
    groups angie
    # → angie : angie
    ```
*   **Решение:** Включите сервисного пользователя в группу `shadow`: `sudo usermod -aG shadow angie` и перезапустите Angie: `sudo systemctl restart angie`.

### Ошибка: unknown directive при запуске
*   **Симптом:** При `angie -t` возникает ошибка `unknown directive "auth_jwt"` или `unknown directive "auth_ldap"`.
*   **Причина:** Динамический модуль установлен, но директива `load_module` не добавлена в контекст `main` файла `/etc/angie/angie.conf`.
*   **Решение:** Добавьте в самое начало конфигурационного файла:
    ```nginx
    load_module modules/ngx_http_auth_jwt_module.so;
    load_module modules/ngx_http_auth_ldap_module.so;
    ```

## Лучшие практики

### Защита эндпоинтов аутентификации от перебора (Brute-Force)
Любые эндпоинты с Basic Auth или формами входа должны быть защищены ограничением частоты запросов через `ngx_http_limit_req_module`:
```nginx
http {
    # Зона ограничения запросов: 5 запросов в секунду на один IP-адрес
    limit_req_zone $binary_remote_addr zone=auth_limit:10m rate=5r/s;

    server {
        location /admin/ {
            limit_req zone=auth_limit burst=10 nodelay;
            limit_req_status 429;

            auth_basic "Protected Area";
            auth_basic_user_file /etc/angie/.htpasswd;

            proxy_pass http://backend;
        }
    }
}
```

### Безопасное логирование без утечки учетных данных
1. **Маскирование чувствительных данных:** Никогда не добавляйте заголовок `$http_authorization` в формат стандартного журнала `access.log`.
2. **Использование безопасных переменных:** Для аудита авторизованных сессий используйте `$remote_user` (содержит имя прошедшего аутентификацию пользователя) и `$jwt_payload_sub` (subject из токена).
```nginx
log_format secure_combined '$remote_addr - $remote_user [$time_local] '
                           '"$request" $status $body_bytes_sent '
                           '"$http_referer" "$http_user_agent" '
                           'auth_status=$auth_request_status jwt_user="$jwt_payload_sub"';
```

### Принцип наименьших привилегий для служебных каталогов
1. **Сервисный аккаунт LDAP:** Учетная запись `binddn` для связи Angie с LDAP/AD должна иметь исключительно права на чтение (Read-Only) минимально необходимого дерева объектов (OU).
2. **Файлы секретов:** Файлы паролей `.htpasswd`, секретные ключи JWT и сертификаты должны принадлежать `root`, иметь права `0640` и группу `angie`. Хранение незашифрованных паролей в конфигурационных репозиториях Git недопустимо.

### Отказоустойчивость и кэширование проверок
При интеграции с внешними системами аутентификации (LDAP, HTTP Sidecar) сбой сетевого каталога не должен вызывать полный отказ веб-приложения:
1. Задавайте короткие таймауты подключения: `connect_timeout 3s; request_timeout 5s;`.
2. Включайте кэширование результатов: `cache max=10000 inactive=15m;` в директиве `ldap_server`.
3. Указывайте несколько резервных контроллеров каталога через повторные директивы `auth_ldap_servers`.

### Исключение небезопасных конструкций if
Не используйте директивы `if` внутри блоков `location` для проверки прав доступа (антипаттерн "If Is Evil"). Для сложной многофакторной фильтрации комбинируйте директивы `map`, модуль `satisfy any` или делегируйте проверку в `auth_request`.

## Дополнительная информация

### Внутренние ссылки
*   **[Взаимная аутентификация клиентов (mTLS) в Angie](./angie_client_cert_auth.md)** — бескомпромиссная двухсторонняя криптографическая проверка клиентов на основе TLS-сертификатов.
*   **[Настройка TLS в Angie](./angie_tls_setup.md)** — базовое шифрование соединений, необходимое для безопасной передачи Basic Auth и JWT.
*   **[Аутентификация через OpenID Connect (OIDC) в Angie](./angie-oidc.md)** — реализация полного потока Authorization Code + PKCE с интеграцией с IdP (Keycloak, Dex, Authentik).
*   **[Скриптование на njs в Angie](./angie-njs.md)** — программируемая авторизация и валидация заголовков на JavaScript.
*   **[Настройка Angie в роли обратного HTTP-прокси](./angie_reverse_proxy.md)** — настройка взаимодействия с upstream и директивы `ngx_http_realip_module`.
*   **[Защита от DoS-атак в Angie](./High_Load/dos_protection.md)** — противодействие перебору паролей и распределенным атакам через зоны `limit_req`.
*   **[Логирование в Angie](./angie_logging.md)** — аудит событий безопасности и настройка специализированных форматов логов доступа.

### Внешние источники и спецификации
*   Официальная документация Angie: [ngx_http_access_module](https://en.angie.software/angie/docs/configuration/modules/http/http_access/)
*   Официальная документация Angie: [ngx_http_auth_basic_module](https://en.angie.software/angie/docs/configuration/modules/http/http_auth_basic/)
*   Официальная документация Angie: [ngx_http_auth_request_module](https://en.angie.software/angie/docs/configuration/modules/http/http_auth_request/)
*   Официальная документация Angie: [Auth JWT Module](https://en.angie.software/angie/docs/configuration/modules/external-modules/auth-jwt/)
*   Официальная документация Angie: [Auth LDAP Module](https://en.angie.software/angie/docs/configuration/modules/external-modules/auth-ldap/)
*   Официальная документация Angie: [Auth PAM Module](https://en.angie.software/angie/docs/configuration/modules/external-modules/auth-pam/)
*   RFC 7617: The 'Basic' HTTP Authentication Scheme
*   RFC 7519: JSON Web Token (JWT)
