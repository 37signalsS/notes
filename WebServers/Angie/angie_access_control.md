# Контроль доступа в Angie

## Определения

**Контроль доступа (Access Control)** — комплекс механизмов и политик для управления правами доступа пользователей и автоматизированных систем к ресурсам веб-сервера. Angie предоставляет гибкие инструменты для идентификации клиентов на основе сетевых атрибутов (IP), учетных данных (пароли, LDAP, PAM) или криптографических доказательств (JWT, mTLS).

**Ключевые модули Angie для контроля доступа:**
*   **ngx_http_access_module:** базовая фильтрация по IP-адресам и подсетям.
*   **ngx_http_auth_basic_module:** аутентификация через заголовок `Authorization: Basic` (RFC 7617).
*   **ngx_http_auth_request_module:** авторизация через внешние HTTP-подзапросы (Auth Sidecar/Gateway).
*   **ngx_http_auth_jwt_module:** проверка подлинности через JSON Web Tokens (JWT) с поддержкой верификации подписей и Claims.
*   **ngx_http_auth_ldap_module:** интеграция с корпоративными каталогами (Active Directory, OpenLDAP).
*   **ngx_http_auth_pam_module:** использование системной аутентификации Linux через Pluggable Authentication Modules.

## Базовые концепции

### Иерархия и наследование
Правила контроля доступа могут быть определены на уровнях `http`, `server` или `location`. Важно учитывать, что указание любой директивы модуля контроля доступа в дочернем контексте полностью заменяет (не дополняет) набор правил родительского контекста для этого модуля.

### Порядок обработки правил (Allow/Deny)
Директивы модуля `access` проверяются в порядке их появления в конфигурации до первого совпадения:
1.  Если IP совпадает с `allow`, доступ разрешается.
2.  Если IP совпадает с `deny`, возвращается ошибка `403 Forbidden`.
3.  Если совпадений нет, применяется поведение родительского контекста или разрешается доступ по умолчанию.
**Рекомендация:** Всегда завершайте списки директивой `deny all;`.

### Механизм auth_request
Модуль выполняет внутренний подзапрос (subrequest) перед обработкой основного запроса.
*   **2xx:** доступ разрешен.
*   **401:** доступ запрещен (`Unauthorized`), клиенту передается заголовок `WWW-Authenticate` от авторизатора.
*   **403:** доступ запрещен (`Forbidden`).
*   **Передача данных:** директива `auth_request_set` позволяет копировать переменные из ответа авторизатора (например, `$upstream_http_...`) в переменные основного запроса для последующей передачи в бэкенд.

### Комбинирование методов (директива satisfy)
Директива `satisfy` определяет логику взаимодействия между модулями (например, IP-фильтр и пароль):
*   `satisfy all` (дефолт): клиент должен успешно пройти проверки всех модулей.
*   `satisfy any`: доступ разрешается, если выполнено условие хотя бы одного модуля.

## Практические сценарии

### Сценарий 1: Ограничение доступа по IP

Используется для защиты административных интерфейсов и внутренних API.

```nginx
location /admin/ {
    # Разрешаем конкретные хосты и подсети
    allow 192.168.1.0/24;
    allow 203.0.113.5;
    allow 127.0.0.1;
    
    # Запрещаем всем остальным
    deny all;
}
```

### Сценарий 2: Базовая аутентификация (auth_basic)

Классическая защита паролем. **Важно:** Данные передаются в кодировке Base64, поэтому использование **[TLS/HTTPS](./angie_tls_setup.md)** является обязательным.

**1. Генерация файла паролей:**
```bash
sudo htpasswd -c /etc/angie/.htpasswd admin
# Добавление без перезаписи файла:
sudo htpasswd /etc/angie/.htpasswd developer
```

**2. Настройка в Angie:**
```nginx
location /protected/ {
    auth_basic "Restricted Area";
    auth_basic_user_file /etc/angie/.htpasswd;
}
```

### Сценарий 3: Авторизация через подзапрос (njs и API)

#### Вариант А: Проверка API-ключа в конфигурации
```nginx
location /api/ {
    auth_request /_validate_key;
    proxy_pass http://backend;
}

location = /_validate_key {
    internal;
    if ($http_x_api_key != "secret-token-2026") {
        return 403;
    }
    return 204;
}
```

#### Вариант Б: Использование JavaScript (njs)
Позволяет реализовать сложную логику проверки (например, проверка срока действия или обращение к Redis).
```javascript
// auth.js
function check_access(r) {
    if (r.headersIn['Authorization'] === 'Bearer security-token') {
        r.return(204);
    } else {
        r.return(401);
    }
}
export default { check_access };
```
**Настройка:**
```nginx
js_import /etc/angie/scripts/auth.js;

location /secure/ {
    auth_request /_js_auth;
    proxy_pass http://backend;
}

location = /_js_auth {
    internal;
    js_content auth.check_access;
}
```

### Сценарий 4: Валидация JWT (JSON Web Token)

Позволяет проверять подлинность токенов и права пользователя (Claims) без обращения к внешним сервисам.

```nginx
# В angie.conf: load_module modules/ngx_http_auth_jwt_module.so;

http {
    # Путь к набору публичных ключей (JWKS)
    auth_jwt_key_file /etc/angie/keys/idp_public.jwk;

    server {
        location /v2/api/ {
            auth_jwt "API Access";
            auth_jwt_key_file /etc/angie/keys/idp_public.jwk;
            
            # Проверка конкретного поля в payload (например, роль)
            auth_jwt_require $jwt_payload_role "admin" "editor";

            proxy_pass http://api_backend;
        }
    }
}
```

### Сценарий 5: Интеграция с LDAP / Active Directory

Используется для обеспечения Single Sign-On (SSO) в корпоративной среде.

```nginx
# В angie.conf: load_module modules/ngx_http_auth_ldap_module.so;

http {
    ldap_server ad_srv {
        url ldap://ad.example.com:389/dc=example,dc=com?sAMAccountName?sub?(objectClass=person);
        binddn "cn=svc_angie,ou=services,dc=example,dc=com";
        binddn_passwd "StrongPassword123";
        
        # Кэширование для снижения нагрузки на контроллер домена
        cache max=1000 inactive=10m;
        
        require valid_user;
    }

    server {
        location /internal/ {
            auth_ldap "Domain Auth Required";
            auth_ldap_servers ad_srv;
            proxy_pass http://internal_app;
        }
    }
}
```

### Сценарий 6: Системная аутентификация (PAM)

Интеграция с локальными пользователями ОС через `/etc/shadow`.

**1. Настройка сервиса PAM (`/etc/pam.d/angie`):**
```text
auth    required    pam_unix.so
account required    pam_unix.so
```

**2. Настройка в Angie:**
```nginx
location /system-admin/ {
    auth_pam "System Login";
    auth_pam_service_name "angie";
}
```

### Сценарий 7: Гео-блокировка через GeoIP2 и map

Ограничение доступа по стране клиента на основе базы MaxMind GeoLite2 и модуля `ngx_http_geoip2_module`.

```nginx
http {
    geoip2 /etc/angie/geo/Country.mmdb {
        $geoip2_country_code default=RU country iso_code;
    }

    # Решение о доступе принимает map (а не if) — чистая композиция с другими правилами
    map $geoip2_country_code $allow_geo {
        default  0;
        RU       1;
        KZ       1;
        BY       1;
    }

    server {
        listen 80;
        server_name admin.example.com;

        # Комбинируем гео-фильтр с IP-фильтром через satisfy any
        satisfy any;
        allow 10.0.0.0/8;      # доступ из внутренней сети всегда
        deny all;

        location / {
            # Дополнительная гео-проверка для остальных
            if ($allow_geo = 0) {
                return 403;
            }
            proxy_pass http://backend;
        }
    }
}
```

**Верификация:**
```bash
# Проверка, что модуль загружен
angie -M | grep geoip2
# → ngx_http_geoip2_module

# Проверка базы
ls -la /etc/angie/geo/Country.mmdb

# Тест принудительно "чужим" IP (если позволено в тестовой среде)
curl -s -H "X-Forwarded-For: 8.8.8.8" http://admin.example.com/ -o /dev/null -w "%{http_code}\n"
# → 403
```

Подробнее о `geo`/`map` и их комбинировании — в [Переменных и map в Angie](./angie_variables.md). Полный сценарий гео-блокировки с rate limiting — в [Защите от DoS-атак в Angie](./High_Load/dos_protection.md).

## Операции и команды

### Верификация конфигурации контроля доступа
```bash
# Проверка синтаксиса конфигурации
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful
```

### Управление учетными данными Basic Auth
```bash
# Создание нового файла паролей
sudo htpasswd -c /etc/angie/.htpasswd admin

# Добавление пользователя без перезаписи файла
sudo htpasswd /etc/angie/.htpasswd developer

# Удаление пользователя
sudo htpasswd -D /etc/angie/.htpasswd admin

# Проверка содержимого файла
sudo htpasswd -v /etc/angie/.htpasswd admin
# → admin
```

### Инспекция логов аутентификации
```bash
# Поиск попыток аутентификации Basic Auth (статус 401)
grep "401" /var/log/angie/access.log | tail -n 20

# Поиск IP с наибольшим количеством неудачных попыток
awk '$9 == 401 {print $1}' /var/log/angie/access.log | sort | uniq -c | sort -rn | head -n 10

# Поиск заблокированных запросов (статус 403)
awk '$9 == 403' /var/log/angie/access.log | tail -n 20
```

### Проверка JWT переменных
```bash
# Декодирование JWT payload (только для отладки, в production используйте соответствующую библиотеку)
echo "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ" | cut -d. -f2 | base64 -d 2>/dev/null || echo "Invalid token"
```

### Тестирование LDAP-подключения
```bash
# Проверка доступности LDAP-сервера
ldapsearch -x -H ldap://ad.example.com:389 -b "dc=example,dc=com" -s base "(objectclass=*)"

# Проверка аутентификации пользователя
ldapwhoami -x -H ldap://ad.example.com:389 -D "cn=svc_angie,ou=services,dc=example,dc=com" -w "StrongPassword123"
```

### Управление PAM-сервисом
```bash
# Проверка существования конфигурации PAM для Angie
ls -la /etc/pam.d/angie

# Тестирование PAM-аутентификации вручную
pamtester angie username authenticate
```

## Устранение неисправностей

### 401 Unauthorized при Basic Auth
**Причина:** Неверные учетные данные или отсутствует заголовок `Authorization`.
**Диагностика:**
```bash
# Проверка, передает ли клиент заголовок Authorization
curl -I http://protected-endpoint/
# Должен вернуть 401 с заголовком WWW-Authenticate

# Проверка файла паролей
sudo htpasswd -v /etc/angie/.htpasswd username
```
**Решение:** Убедитесь, что клиент отправляет корректные креды и файл паролей доступен для чтения процессом Angie.

### 403 Forbidden при IP-фильтрации
**Причина:** IP-адрес клиента не попадает ни в один `allow` блок.
**Диагностика:**
```bash
# Проверка IP-адреса, под которым работает Angie при проксировании
curl -s http://whatismyip.akamai.com/
```
**Решение:** Проверьте порядок директив `allow`/`deny`. Добавьте недостающую подсеть в `allow`. Убедитесь, что используется правильный ключ (например, `$remote_addr` vs `$http_x_forwarded_for`).

### 500 Internal Server Error при auth_request
**Причина:** Внешний авторизатор вернул ошибку или недоступен.
**Диагностика:**
```bash
# Проверка доступности авторизатора напрямую
curl -s -o /dev/null -w "%{http_code}" http://auth-service:8080/validate

# Проверка логов авторизатора
journalctl -u auth-service -n 50
```
**Решение:** Проверьте здоровье авторизатора, таймауты в `auth_request` (по умолчанию 60s), и корректность URL подзапроса.

### Ошибки валидации JWT
**Причина:** Просроченный токен (`exp`), неверная подпись (`alg`), или отсутствующий ключ.
**Диагностика:**
```bash
# Проверка срока действия токена (декодирование без проверки подписи)
echo "$JWT_TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | python3 -m json.tool

# Проверка наличия и формата ключа
file /etc/angie/keys/idp_public.jwk
```
**Решение:** Обновите ключи (`auth_jwt_key_file`), проверьте часы синхронизации (NTP) на серверах, убедитесь что `alg` в токене соответствует ожидаемому.

### Сбои LDAP-аутентификации
**Причина:** Недоступность контроллера домена, неверные учетные данные для bind, или истечение кэша.
**Диагностика:**
```bash
# Проверка TCP-доступности порта LDAP
nc -zv ad.example.com 389

# Проверка резолвинга
nslookup ad.example.com

# Проверка кэша LDAP
curl -s http://localhost/api/v1/http/ldap_servers/ad_srv | jq .
```
**Решение:** Проверьте сетевую доступность, корректность `binddn`/`binddn_passwd`, и настройки файрвола. Увеличьте TTL кэша при высокой нагрузке.

### PAM: отказ в аутентификации
**Причина:** Пользователь не существует в `/etc/passwd` или `/etc/shadow`, или модуль PAM заблокирован.
**Диагностика:**
```bash
# Проверка пользователя в системе
id username

# Проверка содержимого /etc/pam.d/angie
cat /etc/pam.d/angie

# Проверка логов PAM
grep pam_unix /var/log/auth.log
```
**Решение:** Убедитесь, что пользователь существует, модуль `pam_unix.so` доступен, и Angie запущен с достаточными правами (обычно `root`).

## Лучшие практики

### Принцип наименьших привилегий
Используйте `satisfy any` только когда это оправдано (например, офисный доступ без VPN). В публичных API всегда применяйте `satisfy all` с комбинацией IP-фильтрации и строгой аутентификации.

### Безопасность заголовков аутентификации
1. **Заголовок `WWW-Authenticate`:** При возврате `401` не раскрывайте избыточную информацию о типе аутентификации, если это не требуется спецификацией.
2. **Защита от перебора:** Для эндпоинтов аутентификации (login, API key validation) всегда применяйте `limit_req` с `burst` и `nodelay` или перенаправляйте их через WAF.
3. **Логирование:** Никогда не логируйте содержимое заголовков `Authorization` или `Cookie` в открытом виде. Используйте маскирование через `map`.

### JWT-безопасность
1. **Проверка алгоритма:** Всегда явно указывайте `auth_jwt_type` и проверяйте, что `alg` в заголовке соответствует ожидаемому (обычно `RS256` для асимметричных ключей).
2. **Валидация Claims:** Проверяйте `exp` (expiration), `nbf` (not before), `iss` (issuer), и `aud` (audience) через `auth_jwt_require` или кастомный `auth_request`.
3. **Ротация ключей:** Используйте `auth_jwt_key_file` с регулярной ротацией. Для бесшовного обновления поддерживайте оба ключа (старый и новый) в JWKS и настройте `auth_jwt_key_request` для динамической загрузки.

### LDAP/PAM hardening
1. **Кэширование:** Настройте `cache max=1000 inactive=10m` для снижения нагрузки на контроллер домена.
2. **Сервисные учетные данные:** Используйте отдельную учетную запись с минимальными правами (read-only) для `binddn`.
3. **Защита пароля:** В `binddn_passwd` храните пароль в зашифрованном виде или используйте файл переменных, исключенный из репозитория.

### Конфигурация и порядок директив
1. **Завершайте списки `deny all;`:** Это защищает от случайного разрешения доступа при добавлении новых `allow` в родительских контекстах.
2. **Избегайте `if` в контексте `location`:** Модуль `ngx_http_rewrite_module` и его директива `if` имеют ограниченную семантику. Для сложной логики используйте `map` в блоке `http` или `auth_request`.

### Изоляция и сетевая безопасность
1. **Сегментация upstream:** Разделите внутренние и внешние бэкенды. Эндпоинты с `auth_basic` или `auth_jwt` должны обращаться к изолированным backend-сервисам.
2. **mTLS для критичных эндпоинтов:** Для административных интерфейсов используйте взаимную TLS ([Взаимная аутентификация клиентов (mTLS) в Angie](./angie_client_cert_auth.md)) вместо или в дополнение к парольной аутентификации.

## Дополнительная информация

### Мониторинг и аудит
Для отслеживания попыток доступа используйте расширенные переменные в `log_format`:
*   `$remote_user` — имя пользователя, прошедшего аутентификацию (Basic, LDAP, PAM).
*   `$jwt_header_alg` / `$jwt_payload_sub` — данные из JWT токена.
*   `$auth_request_status` — результат работы `auth_request`.

### Взаимодействие с rate limiting
Модули контроля доступа и модули ограничения частоты запросов (`ngx_http_limit_req_module`, `ngx_http_limit_conn_module`) работают независимо. Для защиты эндпоинтов аутентификации от brute-force атак комбинируйте их:
- `limit_req` на `/login` или `/_validate_key` для ограничения попыток входа.
- `limit_conn` для ограничения одновременных соединений с одного IP.

Подробнее о настройке лимитов см. в [angie_reverse_proxy.md](./angie_reverse_proxy.md) и [angie_variables.md](./angie_variables.md).

### Условный доступ через `map` и `geo`
Для сложных сценариев, где решение о доступе зависит от нескольких переменных (страна, User-Agent, время суток), используйте модуль `ngx_http_map_module` для создания переменных на основе логических выражений. Для геолокации используйте `ngx_http_geoip2_module` с базой MaxMind GeoLite2. Примеры см. в [angie_variables.md](./angie_variables.md) и [dos_protection.md](./High_Load/dos_protection.md).

### Версионные особенности Angie
*   **Angie OSS:** Поддерживает `ngx_http_access_module`, `ngx_http_auth_basic_module`, `ngx_http_auth_request_module`, `ngx_http_auth_jwt_module`.
*   **Angie PRO:** Добавляет `ngx_http_auth_ldap_module`, `ngx_http_auth_pam_module`, расширенные возможности синхронизации зон.

### Рекомендации по безопасности
1.  **Satisfy Any для офиса:** Часто используется паттерн, разрешающий доступ без пароля из офисной сети (`allow office_ip`), но требующий `auth_basic` для всех остальных.
2.  **Защита от перебора (Brute-force):** Рекомендуется комбинировать методы аутентификации с модулем `ngx_http_limit_req_module` для ограничения частоты запросов к эндпоинтам входа.
3.  **Безопасность JWT:** При использовании `auth_jwt` всегда проверяйте алгоритм подписи (`alg`) и срок действия (`exp`).

## См. также

*   **[Взаимная аутентификация клиентов (mTLS) в Angie](./angie_client_cert_auth.md)** — альтернативный метод на основе сертификатов.
*   **[Настройка TLS в Angie](./angie_tls_setup.md)** — обязательная база для защищенной аутентификации.
*   **[Логирование в Angie](./angie_logging.md)** — аудит событий доступа.
*   **[Аутентификация через OpenID Connect (OIDC) в Angie](./angie-oidc.md)** — полный OIDC-поток, JWKS, Authorization Code + PKCE.
*   **[Скриптование на njs в Angie](./angie-njs.md)** — сложная логика проверки на JavaScript.
