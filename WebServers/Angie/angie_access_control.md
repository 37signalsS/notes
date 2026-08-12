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

## Дополнительная информация

### Мониторинг и аудит
Для отслеживания попыток доступа используйте расширенные переменные в `log_format`:
*   `$remote_user` — имя пользователя, прошедшего аутентификацию (Basic, LDAP, PAM).
*   `$jwt_header_alg` / `$jwt_payload_sub` — данные из JWT токена.
*   `$auth_request_status` — результат работы `auth_request`.

### Рекомендации по безопасности
1.  **Satisfy Any для офиса:** Часто используется паттерн, разрешающий доступ без пароля из офисной сети (`allow office_ip`), но требующий `auth_basic` для всех остальных.
2.  **Защита от перебора (Brute-force):** Рекомендуется комбинировать методы аутентификации с модулем `ngx_http_limit_req_module` для ограничения частоты запросов к эндпоинтам входа.
3.  **Безопасность JWT:** При использовании `auth_jwt` всегда проверяйте алгоритм подписи (`alg`) и срок действия (`exp`).

## См. также

*   **[Логирование в Angie](./angie_logging.md)** — аудит событий доступа.
*   **[Взаимная аутентификация (mTLS) в Angie](./angie_client_cert_auth.md)** — альтернативный метод на основе сертификатов.
*   **[Настройка TLS в Angie](./angie_tls_setup.md)** — обязательная база для защищенной аутентификации.
*   **[Руководство по безопасности Nginx](../Nginx/Security/nginx_security_guide.md)** — общие принципы.
