# Контроль доступа в Angie

## Определения

**Контроль доступа (Access Control)** — механизмы управления правами доступа пользователей и систем к ресурсам веб-сервера (сайтам, каталогам, API-эндпоинтам).

**ngx_http_access_module** — модуль для ограничения доступа на основе IP-адресов или подсетей клиента.

**ngx_http_auth_basic_module** — модуль, реализующий базовую HTTP-аутентификацию (Basic Access Authentication) с проверкой логина и пароля.

**ngx_http_auth_request_module** — модуль для авторизации запросов на основе ответа внешнего подзапроса. Позволяет реализовать сложную логику аутентификации (например, через OAuth2 или кастомные сервисы).

**ngx_http_auth_pam_module** — сторонний (или встроенный в Angie Pro) модуль для интеграции с системными механизмами аутентификации Linux через **PAM (Pluggable Authentication Modules)**.

**JWT (JSON Web Token)** — компактный формат токенов для безопасной передачи информации между сторонами, часто используемый для аутентификации в API.

## Основные концепции

### Иерархия и наследование правил

Правила контроля доступа могут быть определены на уровнях `http`, `server` или `location`. Правила, определенные на более глубоком уровне, переопределяют или дополняют правила родительских контекстов в зависимости от конкретного модуля.

### Порядок обработки allow и deny

Директивы модуля `ngx_http_access_module` проверяются последовательно до первого совпадения. Если совпадение найдено, поиск прекращается, и доступ либо разрешается (`allow`), либо запрещается (`deny`).

### Принцип работы auth_request

Модуль отправляет внутренний подзапрос (subrequest) на указанный URI.

- Если подзапрос возвращает код `2xx`, доступ разрешен.
- Если `401` или `403`, доступ запрещен с соответствующим кодом.
- Другие коды интерпретируются как ошибка сервера.

### Комбинирование методов (директива satisfy)

Директива `satisfy` определяет логику взаимодействия между модулями контроля доступа (например, IP-фильтр и пароль):

- `satisfy all` (по умолчанию) — должны быть выполнены все условия.
- `satisfy any` — достаточно выполнения любого одного условия.

## Практические сценарии

### 1. Ограничение доступа по IP-адресу

Позволяет разрешить доступ только доверенным сетям (например, офисным IP или VPN).

```nginx
location /admin/ {
    # Разрешаем доступ из локальной сети
    allow 192.168.1.0/24;
    # Разрешаем конкретный IP
    allow 203.0.113.5;
    # Запрещаем всем остальным (обязательно в конце)
    deny all;
}
```

### 2. Базовая аутентификация (auth_basic)

Классическая защита паролем. Обязательно используйте совместно с **[TLS/HTTPS](./angie_tls_setup.md)**, так как учетные данные передаются в открытом виде (Base64).

**Шаг 1: Создание файла паролей**
Используйте утилиту `htpasswd` (пакет `apache2-utils`):

```bash
# Создать файл и добавить первого пользователя
sudo htpasswd -c /etc/angie/htpasswd admin
# Добавить пользователя в существующий файл
sudo htpasswd /etc/angie/htpasswd guest
```

**Шаг 2: Настройка Angie**

```nginx
location /protected/ {
    auth_basic "Restricted Area";
    auth_basic_user_file /etc/angie/htpasswd;
}
```

### 3. Комбинирование IP-фильтра и пароля (satisfy any)

Сценарий: сотрудники в офисе заходят без пароля, остальные — по паролю.

```nginx
location /internal/ {
    satisfy any;

    allow 10.0.0.0/8;
    deny all;

    auth_basic "Internal Portal";
    auth_basic_user_file /etc/angie/htpasswd;
}
```

### 4. Авторизация через подзапрос (auth_request)

#### Вариант А: Простая проверка API-ключа

Реализация логики проверки внутри конфигурации.

```nginx
location /api/ {
    auth_request /_validate_key;
    proxy_pass http://backend;
}

location = /_validate_key {
    internal;
    if ($http_x_api_key != "top-secret-token") {
        return 403;
    }
    return 204;
}
```

#### Вариант Б: Сложная логика на JavaScript (njs)

Позволяет проверять токены, время или делать запросы к внешним БД.

```nginx
# В блоке http: js_import /etc/angie/scripts/auth.js;

location /secure/ {
    auth_request /_js_auth;
    proxy_pass http://backend;
}

location = /_js_auth {
    internal;
    js_content auth.check_access;
}
```

Пример `auth.js`:

```javascript
function check_access(r) {
    if (r.headersIn['Authorization'] === 'Bearer valid-token') {
        r.return(204);
    } else {
        r.return(401);
    }
}
export default { check_access };
```

### 5. Аутентификация через системных пользователей (PAM)

Интеграция с пользователями ОС Linux. Требует модуль `ngx_http_auth_pam_module`.

**Шаг 1: Настройка PAM-сервиса**
Создайте файл `/etc/pam.d/angie`:

```text
auth    required    pam_unix.so
account required    pam_unix.so
```

**Шаг 2: Настройка Angie**

```nginx
location /system-admin/ {
    auth_pam "System Authentication";
    auth_pam_service_name "angie";
}
```

## Дополнительная информация

### Продвинутые модули

- **JWT**: Валидация токенов через `auth_jwt`. Подробнее о концепциях: **[Аутентификация vs Авторизация](../../Security/Concepts/authentication_vs_authorization.md)**.
- **LDAP**: Интеграция с корпоративными каталогами. См. **[LDAP и SSSD](../../Linux/SystemAdministration/Users/LDAP_SSSD/operations.md)**.
- **mTLS**: Аутентификация клиентов по TLS-сертификатам. См. **[mTLS в Angie](./angie_client_cert_auth.md)**.

### См. также

- **[Общий обзор безопасности Nginx](../Nginx/Security/nginx_security_guide.md)**
- **[Логирование в Angie](./angie_logging.md)** — для аудита попыток доступа.
