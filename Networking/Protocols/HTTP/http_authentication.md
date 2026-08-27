# HTTP-аутентификация: Протоколы и механизмы

## Определения

**HTTP-аутентификация** — механизм протокола **HTTP**, позволяющий серверу запрашивать у клиента учетные данные (логин и пароль, токен, сертификат, криптографический вызов) для проверки личности перед предоставлением доступа к защищённым ресурсам.

**Основные заголовки:**

- **`WWW-Authenticate`** — заголовок ответа сервера, указывающий поддерживаемый метод аутентификации и область доступа (**`realm`**).
- **`Authorization`** — заголовок запроса клиента, содержащий учетные данные.
- **`Proxy-Authenticate` / `Proxy-Authorization`** — аналогичные заголовки для аутентификации на промежуточном прокси-сервере.
- **`DPoP`** — современный заголовок для передачи доказательства владения ключом (Proof-of-Possession).

## Основные концепции

### Базовая аутентификация (Basic Authentication)

Простейший метод, встроенный непосредственно в протокол HTTP (RFC 7617).

**Принцип работы:**

1. Клиент отправляет запрос к защищённому ресурсу.
2. Сервер отвечает кодом **`401 Unauthorized`** с заголовком `WWW-Authenticate: Basic realm="Restricted Area"`.
3. Браузер отображает системное окно ввода логина и пароля.
4. Клиент повторно отправляет запрос с заголовком `Authorization: Basic <логин:пароль_в_Base64>`.

**Безопасность:** Данные не шифруются, а только кодируются. Метод допустим **исключительно** при использовании **HTTPS**. В 2026 году считается устаревшим для пользовательских интерфейсов, но широко применяется для технического доступа к API и в контейнерных средах.

### Токен Bearer (Bearer Token)

Метод передачи токена доступа («на предъявителя»), обычно полученного через **OAuth 2.1** или **OIDC**.

**Особенности:**

- Клиент передает токен в заголовке `Authorization: Bearer <token>`.
- В 2026 году стандартом является **OAuth 2.1**, который делает обязательным использование **PKCE** для всех типов клиентов и запрещает небезопасные потоки (Implicit, ROPC).
- Основной формат — **JWT (JSON Web Token)**. Для подписи рекомендуется использовать алгоритм **EdDSA (Ed25519)**, обеспечивающий высокую безопасность при минимальном размере заголовка.
- **Риск:** Если Bearer-токен перехвачен, атакующий может использовать его до истечения срока жизни (TTL). Для защиты применяются **Sender-Constrained Tokens**.

### OAuth 2.0 / 2.1 и OpenID Connect

**OAuth 2.0** (RFC 6749) — открытый фреймворк авторизации, позволяющий приложениям получать ограниченный доступ к ресурсам пользователя без передачи его пароля. **OAuth 2.1** объединяет лучшие практики, опубликованные после 2012 года, в единый стандарт:
- **Обязательный PKCE** (Proof Key for Code Exchange, RFC 7636) для всех клиентов.
- **Запрет** на потоки Implicit Grant и Resource Owner Password Credentials (ROPC).
- Строгая валидация `redirect_uri` (exact match, без wildcard).
- Рекомендация Refresh Token Rotation (RFC 6749 §10.4).

**Основные потоки (flows):**

1. **Authorization Code + PKCE:** Стандарт для веб-приложений, SPA и мобильных клиентов. Клиент создаёт криптографический `code_verifier` и его хэш `code_challenge`. После успешного входа пользователя получает `authorization_code`, который обменивается на токены при условии предъявления `code_verifier`. Защищает от перехвата кода.
2. **Client Credentials:** Для Machine-to-Machine (M2M) взаимодействия. Клиент аутентифицируется своим `client_id` и `client_secret` (или mTLS) и получает Access Token, не связанный с пользователем.
3. **Device Authorization (RFC 8628):** Для устройств с ограниченным вводом (Smart TV, принтеры). Устройство получает `device_code` и `user_code`, пользователь вводит код на отдельном устройстве с браузером.
4. **Refresh Token Rotation:** При каждом обновлении Access Token старый Refresh Token аннулируется и выдаётся новая пара. При попытке повторного использования старого Refresh Token сервер аннулирует всю цепочку сессий.

**OpenID Connect (OIDC)** — слой идентификации поверх OAuth 2.0. Добавляет:
- **ID Token** (JWT) с утверждениями о пользователе (`sub`, `iss`, `aud`, `exp`, `name`, `email`).
- **UserInfo Endpoint** — защищённый эндпоинт для получения дополнительных claims.
- **Discovery** — механизм автоматического обнаружения конфигурации провайдера через `/.well-known/openid-configuration`.
- **Scopes:** `openid` (обязательный), `profile`, `email`, `phone`, `address`.

**Рекомендации 2026 года:**
- Для публичных клиентов (SPA, mobile) — только Authorization Code + PKCE.
- Для M2M — Client Credentials + mTLS привязка токена (RFC 8705).
- Для высокорисковых сред — DPoP или Sender-Constrained Tokens.
- Для пользовательского входа — Passkeys / WebAuthn вместо пароля.

### Форматы токенов и их валидация

**JWT (JSON Web Token, RFC 7519)** — компактный, URL-безопасный токен, состоящий из трёх Base64URL-закодированных частей, разделённых точками: `header.payload.signature`.

- **Header:** `{"alg":"EdDSA","typ":"JWT","kid":"key-id"}` — алгоритм подписи и идентификатор ключа.
- **Payload (claims):** `{"sub":"user-123","iss":"https://idp.example.com","aud":"api.example.com","exp":1700000000,"iat":1699996400,"scope":"read:profile write:orders"}`.
- **Signature:** Защищает от подделки. Валидация выполняется публичным ключом издателя (через JWKS endpoint).

**Opaque Token:** Случайная строка без внутренней структуры. Для проверки клиент должен обратиться к Authorization Server introspection endpoint (RFC 7662). Преимущество — возможность мгновенной отзыва без проверки списка блокировок.

**Чек-лист валидации JWT:**
1. Проверка подписи алгоритмом, указанным в `alg` (отклоняйте `alg: none`).
2. Проверка `iss` (issuer) против доверенного списка.
3. Проверка `aud` (audience) — токен должен быть предназначен именно для этого ресурса.
4. Проверка `exp` (expiration) — отклоняйте просроченные токены.
5. Проверка `nbf` (not before) — токен ещё не действителен.
6. Проверка `scope` / `scp` — достаточные ли права для запрошенной операции.
7. Проверка `jti` (JWT ID) на уникальность для защиты от replay.

### HTTP-подпись (HTTP Signatures, RFC 9421)

Альтернативный механизм аутентификации, при котором клиент подписывает сам HTTP-запрос приватным ключом, а не передаёт секретный токен.

**Заголовки подписи:**
- **`Signature-Input`** — перечисляет компоненты подписи (список заголовков, `keyId`, `created`, `expires`, `nonce`).
- **`Signature`** —Base64URL-подпись строки, составленной из указанных заголовков.

**Принцип:**
```http
Signature-Input: sig1=(
  "@method" "@target-uri" "@authority"
  "date" "digest"
);keyId="https://idp.example.com/key/1";created=1700000000;expires=1700003600
Signature: sig1=<base64url-signature>
```

**Преимущества перед Bearer:**
- Подпись привязана к конкретному запросу (метод, URI, дата, тело).
- Защита от replay (поля `created`/`expires`).
- Защита от пересылки украденного токена (так как подпись уникальна для каждого запроса).
- Не требует HTTPS для защиты подписи (хотя HTTPS всё равно рекомендуется).

**Типичное применение:** финансовые API, WebSub (PubSubHubbub), микросервисные взаимодействия внутри DMZ.

### Корпоративный SSO: SAML 2.0

**SAML 2.0** (Security Assertion Markup Language) — XML-стандарт для реализации федеративной идентичности и Single Sign-On (SSO) в корпоративных средах.

- **Роли:** **IdP** (Identity Provider) — аутентифицирует пользователя; **SP** (Service Provider) — доверяет IdP и предоставляет доступ.
- **Протокол:** Обмен XML-документами (AuthnRequest, Assertion, Response) через перенаправления браузера или SOAP.
- **Сравнение с OIDC:** SAML более тяжёлый (XML, перенаправления), но глубоко внедрён в корпоративные каталоги (AD FS, ADFS, Shibboleth). OIDC использует JSON и HTTP, легче для современных приложений.

### Современная беспарольная аутентификация (WebAuthn / Passkeys)

Стандарт **FIDO2**, интегрированный в браузеры через **Web Authentication API**.

- **Принцип:** Вместо пароля используется асимметричная криптография. Устройство пользователя (телефон, YubiKey, TPM) подписывает криптографический «вызов» (challenge) от сервера.
- **Passkeys (Пасс-ключи):** Реализация, позволяющая синхронизировать ключи между устройствами пользователя (Apple Keychain, Google Password Manager).
- **Преимущество:** Полная защита от фишинга, так как подпись привязана к домену сайта (Origin).
- **Структура ответа (AuthenticatorAssertionResponse):** `clientDataJSON` (challenge, origin, type), `authenticatorData` (rpIdHash, flags, counter), `signature` (подпись приватным ключом), `userHandle` (опциональный).

### Куки и сессии (Cookies and Sessions)

Механизм эмуляции состояния в stateless-протоколе HTTP.

**Атрибуты безопасности (обязательны в 2026):**

- **`Domain`** — ограничивает отправку куки конкретным доменом и его поддоменами.
- **`Path`** — ограничивает отправку конкретным путями URI (например, `/api`).
- **`Max-Age` / `Expires`** — время жизни куки в секундах или абсолютная дата. `Max-Age` приоритетнее.
- **`HttpOnly`** — блокирует доступ к куки из JavaScript (**XSS**-защита).
- **`Secure`** — разрешает передачу только по HTTPS.
- **`SameSite=Lax/Strict/None`** — защита от **CSRF**. В современных браузерах `Lax` является значением по умолчанию; `SameSite=None` требует обязательного флага `Secure`.
- **`Partitioned` (CHIPS):** Позволяет использовать куки в сторонних контекстах, изолируя их по топ-левел домену (ответ на отмену 3rd-party cookies).
- **`Priority`** — `High` (стандартные куки) или `Low` (сторонние). Влияет на порядок отправки при приближении к лимиту размера.
- **Префиксы:** `__Secure-` (обязывает `Secure`), `__Host-` (обязывает `Secure`, `Domain` не должен быть указан, `Path=/`).

**Ограничения:**
- Максимальный размер одной куки — ~4 КБ.
- Максимальное количество куки на домен — 50–180 (зависит от браузера).
- При каждом запросе куки передаются автоматически браузером — влияет на bandwidth.

### Аутентификация по сессиям

Подход, при котором после логина сервер создаёт сессию и хранит состояние входа у себя, а клиент оперирует только идентификатором.

**Flow:**

1. Пользователь вводит username/password.
2. Сервер проверяет credentials и создаёт `session id`.
3. Сессия сохраняется в session storage: `sessionId → userId, loginTime, expiresAt, roles/flags`.
4. Сервер отправляет `session id` клиенту в cookie:
    ```http
    HTTP/1.1 200 OK
    Set-Cookie: sessionId=abc123; HttpOnly; Secure; SameSite=Lax
    ```
5. Браузер автоматически прикладывает cookie к следующим запросам:
    ```http
    GET /profile HTTP/1.1
    Host: example.com
    Cookie: sessionId=abc123
    ```
6. Сервер по `session id` находит сессию в хранилище.

В cookie хранится **только идентификатор сессии** — не пароль, не данные пользователя и не «вся сессия».

**Хранилище сессий:**
- **In-memory:** максимальная скорость, но теряется при перезапуске.
- **Redis / Memcached:** распределённое хранение, быстрый доступ, TTL на уровне ключа.
- **Database (SQL/NoSQL):** персистентность, но выше латентность.
- **Signed cookie:** сериализованная и подписанная сессия в самом cookie (Stateless Session, например `ss:signature(payload)`).

**Отличие от JWT-based flow:**

| | Session-based auth | JWT-based token flow |
| :--- | :--- | :--- |
| Хранение состояния | Сервер хранит сессию. | Токен самодостаточен. |
| Проверка | По `sessionId` нужен lookup в storage. | Подпись JWT проверяется локально. |
| Logout/revoke | Проще: удалить сессию. | Сложнее: blacklist / версия токена / короткий TTL. |
| Типичное применение | Классические web apps. | API, SPA, mobile, microservices. |

### API-ключи (API Keys)

Передача статического секрета в кастомном заголовке (например, `X-API-Key`). Используется для идентификации приложений, а не пользователей. Требует обязательной ротации и ограничения прав (Least Privilege).

Возможные способы передачи: отдельный header (`X-API-Key`), заголовок `Authorization`, query parameter или cookie.

API key не является заменой пользовательской аутентификации:

| API Key | Пользовательский логин |
| :--- | :--- |
| Выдаётся приложению, интеграции, проекту или техническому клиенту. | Принадлежит человеку. |
| Создаётся заранее. | Вводится при интерактивном входе. |
| Может жить долго. | Обычно часть интерактивной сессии входа. |
| Сам по себе обычно не содержит claims. | Логин указывает на identity пользователя. |

Если ключ украден, злоумышленник получает доступ к API, пока ключ не отозван, не ограничен по правам или не истёк его срок.

**Лучшие практики для API-ключей:**
- Храните ключи в секрет-менеджерах (Vault, AWS Secrets Manager, Kubernetes Secrets).
- Используйте разные ключи для разных сред (dev/staging/prod).
- Устанавливайте IP-allowlist, если инфраструктура статична.
- Внедряйте ключи с привязкой к конкретным ресурсам/действиям (scoped keys).
- Ротируйте ключи раз в 90 дней автоматически.

### Дайджест-аутентификация (Digest Authentication)

Передает хэш пароля вместо самого пароля (RFC 7616).

**Статус:** Считается устаревшим (Legacy). Использование TLS делает Basic-аутентификацию проще и надежнее, а механизмы Digest (особенно на базе MD5) уязвимы к современным атакам. В 2026 году не рекомендуется для новых проектов.

### Ограничение отправителя (Sender-Constrained Tokens: DPoP и mTLS)

Механизмы привязки токена к конкретному клиенту, предотвращающие использование украденных токенов.

1.  **DPoP (Demonstrating Proof-of-Possession, RFC 9449):**
    - Клиент генерирует временную пару ключей.
    - Каждый запрос подписывается приватным ключом (заголовок `DPoP`).
    - Сервер проверяет подпись и соответствие токена публичному ключу клиента.
    - Защищает от replay через поле `jti` в JWT.
2.  **mTLS Certificate Binding (RFC 8705):**
    - Токен привязывается к отпечатку TLS-сертификата клиента.
    - Требует установления взаимного TLS-соединения.
    - Применяется в высокорисковых API и Service Mesh.

### Взаимная TLS-аутентификация (mTLS)

Аутентификация на уровне транспортного протокола.

- **Применение:** Межсерверное взаимодействие (M2M), микросервисы в [Service Mesh](../../../Service_Mesh/service_mesh_concepts.md).
- **Подробности:** См. **[TLS-шифрование и сертификаты для HTTP](./http_tls_hardening.md#сценарий-4-взаимная-аутентификация-mtls)**.
- **Ограничения:** Требует управления сертификатами (выдача, ротация, отзыв). В контейнерных средах rotation выполняется автоматически (обычно раз в 24 часа) через Istio Citadel или SPIRE.

## Практические сценарии

### Использование curl с DPoP (2026)

Современные версии curl поддерживают генерацию DPoP-доказательств:

```bash
# Использование Bearer токена с DPoP-подписью
curl -H "Authorization: DPoP $TOKEN" \
     --dpop-key private_key.pem \
     https://api.example.com/secure-resource
```

**Валидация:**
```bash
# Проверка заголовков запроса
curl -v -H "Authorization: DPoP $TOKEN" \
     --dpop-key private_key.pem \
     https://api.example.com/secure-resource 2>&1 | grep -E "DPoP|Authorization"
# → В запросе присутствуют оба заголовка
```

### Настройка сессионной куки в Nginx/Angie

```http
# Пример заголовка с максимальной защитой
Set-Cookie: session_id=xyz789; HttpOnly; Secure; SameSite=Strict; Partitioned; Max-Age=3600
```

**Валидация:**
```bash
curl -s -I https://app.example.com/login \
  | grep -i "set-cookie"
# → Set-Cookie: session_id=xyz789; HttpOnly; Secure; SameSite=Strict; Partitioned; Max-Age=3600
```

### Проверка JWT с алгоритмом EdDSA (Python)

```python
import jwt # PyJWT

# Ed25519 — стандарт 2026 года для JWT
public_key = "..." 
token = "..."

try:
    decoded = jwt.decode(token, public_key, algorithms=["EdDSA"], audience="api.example.com")
    print("Доступ разрешен:", decoded["sub"])
except jwt.PyJWTError as e:
    print("Ошибка валидации:", e)
```

**Валидация:**
```bash
python3 validate_jwt.py
# → Доступ разрешен: user-42
```

### OAuth 2.1: поток Authorization Code + PKCE (Python)

Минимальный сервер авторизации для тестирования потока Authorization Code + PKCE с использованием `requests` и `cryptography`:

```python
import secrets, hashlib, base64
import requests

# Шаг 1: Генерация PKCE-параметров
code_verifier = secrets.token_urlsafe(64)
code_challenge = base64.urlsafe_b64encode(
    hashlib.sha256(code_verifier.encode()).digest()
).rstrip(b"=").decode()

# Шаг 2: Перенаправление пользователя (ручной шаг в браузере)
auth_url = (
    "https://idp.example.com/authorize?"
    "response_type=code&client_id=public-client"
    f"&code_challenge={code_challenge}&code_challenge_method=S256"
    "&redirect_uri=https://app.example.com/callback"
    "&scope=openid%20profile"
)
print("Откройте в браузере:", auth_url)

# Шаг 3: После callback получаем code и обмениваем на токены
authorization_code = input("Введите code из callback: ")
token_response = requests.post(
    "https://idp.example.com/oauth2/token",
    data={
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": "https://app.example.com/callback",
        "client_id": "public-client",
        "code_verifier": code_verifier,
    },
)
print("Access Token:", token_response.json()["access_token"])
```

**Валидация:**
```bash
python3 oauth_pkce.py
# → Откройте в браузере: https://idp.example.com/authorize?...
# → Access Token: eyJhbGciOiJFZERTQSJ9...
```

### mTLS-аутентификация между сервисами (curl)

Взаимная TLS-аутентификация для M2M-запроса с клиентским сертификатом:

```bash
# Запрос с клиентским сертификатом и ключом
curl --cacert ca.crt \
     --cert client.crt \
     --key client.key \
     https://service-a.internal:8443/api/v1/hello
```

**Валидация:**
```bash
curl -v --cacert ca.crt --cert client.crt --key client.key \
     https://service-a.internal:8443/api/v1/hello 2>&1 | grep "subject:"
# → subject: C=RU; ST=Moscow; L=Moscow; O=Service-A; CN=service-a.internal
# → HTTP/2 200
```

### Валидация JWT в Nginx/Angie через auth_request

Конфигурация Nginx/Angie для аутентификации запросов через внутренний эндпоинт валидации JWT:

```nginx
server {
    listen 80;
    server_name api.example.com;

    location / {
        auth_request /auth;
        auth_request_set $auth_user $upstream_http_x_auth_user;

        proxy_pass http://backend;
        proxy_set_header X-User $auth_user;
    }

    location = /auth {
        internal;
        proxy_pass http://auth-service:8080/verify;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Original-URI $request_uri;
        proxy_set_header Authorization $http_authorization;
    }
}
```

**Валидация:**
```bash
# Запрос с валидным токеном
curl -H "Authorization: Bearer $VALID_TOKEN" \
     https://api.example.com/protected
# → 200 OK (X-User: user-42)

# Запрос с просроченным токеном
curl -H "Authorization: Bearer $EXPIRED_TOKEN" \
     https://api.example.com/protected
# → 401 Unauthorized (ответ от auth-service)
```

### Конфигурация Basic Auth в Nginx/Angie

Защита локации с помощью файла паролей, созданного через `htpasswd`:

```bash
# Создание файла паролей (bcrypt)
htpasswd -c /etc/nginx/.htpasswd alice
# → Ввод пароля и подтверждение
```

```nginx
server {
    listen 80;
    server_name staging.example.com;

    location / {
        auth_basic "Staging Area";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://staging-backend;
    }
}
```

**Валидация:**
```bash
# Успешная аутентификация
curl -u alice:password https://staging.example.com/status
# → 200 OK

# Неверные учётные данные
curl -u alice:wrong https://staging.example.com/status
# → 401 Unauthorized
# → WWW-Authenticate: Basic realm="Staging Area"
```

## Типичные проблемы и диагностика

### 1. 401 при передаче Bearer токена

**Симптом:** Сервер возвращает `401 Unauthorized` даже при наличии заголовка `Authorization: Bearer ...`.

**Причина:**
- Лишние пробелы или переносы строк в токене.
- Токен просрочен (`exp` в прошлом).
- Неправильный формат (не JWT, не opaque, битые байты).
- Отсутствие `Authorization` заголовка из-за прозрачного прокси или CDN.

**Решение:**
```bash
# Декодирование JWT для проверки структуры
echo "$TOKEN" | cut -d. -f1 | base64 -d 2>/dev/null | python3 -m json.tool
echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | python3 -m json.tool
# → Проверка полей exp, iss, aud

# Проверка точного заголовка
curl -v -H "Authorization: Bearer $TOKEN" https://api.example.com/health 2>&1 | grep -i authorization
# → Заголовок не должен модифицироваться промежуточными прокси
```

### 2. 403 Forbidden при валидном токене

**Симптом:** Токен валиден, но сервер возвращает `403 Forbidden`.

**Причина:** Недостаточные права (`scope`, `role`, `group`). Access Token может быть валидным, но не содержать нужные claims для операции.

**Решение:**
```bash
# Проверка claims токена
jwt decode "$TOKEN" --no-verify
# → Проверка scope: ["read:profile"] — нет "write:orders"

# Логирование решений авторизации на бэкенде
# (не в production, только для отладки)
```

### 3. Cookie не прикрепляется к запросу

**Симптом:** Браузер не отправляет `Cookie` заголовок.

**Причина:**
- Несовпадение `Domain` или `Path`.
- Отсутствует флаг `Secure` при запросе по HTTPS.
- `SameSite=Strict` блокирует cookie при переходе с внешнего сайта.
- Cookie просрочен (`Max-Age` истёк).

**Решение:**
```bash
# Проверка заголовка Set-Cookie
curl -s -I https://app.example.com/login | grep -i set-cookie
# → Убедитесь в Domain, Path, Secure, SameSite

# Проверка отправки cookie
curl -v -b "sessionId=abc123" https://app.example.com/profile 2>&1 | grep Cookie
# → Cookie: sessionId=abc123
```

### 4. Истёкший JWT: алгоритм подписи не поддерживается

**Симптом:** Валидатор падает с ошибкой или принимает токен с `alg: none`.

**Причина:** Атака «отключения подписи» (algorithm none attack) или неправильная конфигурация библиотеки, принимающей `alg: none`.

**Решение:**
```python
# PyJWT: явное указание разрешённых алгоритмов
jwt.decode(token, key, algorithms=["EdDSA", "ES256"])
# → Библиотека отклонит alg: none
```

### 5. Сбой handshake mTLS

**Симптом:** Ошибка TLS handshake при использовании клиентских сертификатов.

**Причина:**
- Сертификат клиента истёк или ещё не действителен (`notBefore`).
- Клиентский сертификат подписан неизвестным CA.
- Несовпадение SNI (Server Name Indication) с `subjectAltName` сертификата сервера.
- Ошибка в цепочке сертификатов (промежуточный CA не передан).

**Решение:**
```bash
# Диагностика TLS handshake
openssl s_client -connect service.example.com:8443 \
  -cert client.crt -key client.key -CAfile ca.crt
# → Проверка Verify return code: 0 (ok)

# Проверка срока действия сертификата
openssl x509 -in client.crt -noout -dates
# → notBefore=Jan 1 00:00:00 2024 GMT
# → notAfter=Jan 1 00:00:00 2025 GMT
```

### 6. CSRF при использовании cookie-сессий

**Симптом:** Пользователь выполняет нежелательные действия после перехода по ссылке злоумышленника.

**Причина:** Отсутствие или слабая конфигурация `SameSite` для session cookie.

**Решение:**
```nginx
# Принудительная установка SameSite=Lax
proxy_cookie_flags session_id HttpOnly Secure SameSite=Lax;
```

### 7. Требуется сетевая аутентификация (511)

**Симптом:** Браузер перенаправляет на страницу входа Wi-Fi, но CLI-клиент получает `511`.

**Причина:** Клиент находится в сети с Captive Portal (отель, аэропорт, кафе). Сервер ожидает, что клиент перейдёт на страницу аутентификации сетевого оператора.

**Решение:**
```bash
# Обнаружение Captive Portal
curl -s http://example.com/generate_204
# → Ожидается 204 No Content; если получен 511 — требуется вход в сеть
```

## Лучшие практики

1. **HTTPS повсеместно:** Никогда не передавайте учетные данные по HTTP. Basic Auth, токены и cookie без HTTPS эквивалентны открытому тексту.
2. **Правильный алгоритм подписи:** Для JWT используйте EdDSA (Ed25519) или ES256. Отвергайте `alg: none` и устаревшие RS256 в высокорисковых средах.
3. **Обязательный PKCE:** Для всех OAuth 2.1 клиентов (SPA, mobile, desktop) используйте PKCE, даже если `client_secret` доступен.
4. **Короткий TTL Access Token:** Устанавливайте срок жизни Access Token 5–15 минут. Для длительных сессий используйте Refresh Token с Rotation.
5. **Sender-Constrained Tokens:** В публичных клиентах (SPA, mobile) используйте DPoP или mTLS binding, чтобы украденный токен нельзя было повторно использовать.
6. **HttpOnly + Secure + SameSite:** Все session cookie должны иметь эти флаги. Для максимальной защиты используйте `SameSite=Strict`; для приложений с внешними редиректами — `SameSite=Lax`.
7. **Валидация всех claims:** На ресурсном сервере проверяйте `iss`, `aud`, `exp`, `nbf`, `scope`. Не полагайтесь только на формат токена.
8. **Ротация секретов:** Регулярно ротируйте API-ключи, JWT signing keys и client secrets. Используйте автоматическую ротацию там, где это возможно.
9. **Логирование без секретов:** Логируйте все попытки аутентификации, но никогда не пишите токены, пароли или cookie в логи. Используйте `token_id` или `jti` для корреляции.
10. **Rate limiting на /oauth/token:** Защищайте endpoint выдачи токенов от брутфорса (credential stuffing) и атак на PKCE verifier exhaustion.

## Граничные случаи и ограничения

1. **Basic Auth и проксирование:** При передаче через промежуточный прокси заголовок `Authorization` может удаляться для защиты. Используйте `Proxy-Authorization` или настройте прокси на его сохранение (`proxy_set_header Authorization $http_authorization;`).
2. **JWT в query parameter:** Некоторые SDK передают токен в URL (`?access_token=...`). Это приводит к утечке в логах серверов, браузера и Referer заголовках. RFC 6750 строго не рекомендует такой способ.
3. **Размер cookie (~4 KB):** Не храните JWT в cookie без проверки размера. Стандартный JWT с множеством claims может превысить лимит, что приведёт к обрезанию cookie и невалидной аутентификации.
4. **Смещение часов (Clock Skew):** При валидации `exp` и `nbf` допускайте расхождение часов ±30–60 секунд между сервисами. Для строгой валидации используйте NTP/Chrony.
5. **Bearer токен в query string:** Запрещён RFC 6750 для sensitive tokens из-за утечки в логи и историю браузера.
6. **OAuth 2.0 без PKCE:** Поток Authorization Code без PKCE уязвим для перехвата кода (authorization code interception attack) в публичных клиентах.
7. **mTLS и connection pooling:** При использовании пула соединений убедитесь, что один клиентский сертификат не используется одновременно несколькими логическими пользователями — это нарушает привязку токена к клиенту.
8. **Stateless logout:** JWT не имеет встроенного механизма отзыва. Для немедленного отзыва используйте blacklist/CRL или сокращайте TTL и применяйте Refresh Token Rotation.
9. **Unicode и XSS:** При отображении данных из JWT (например, `name` claim) всегда экранируйте вывод. Токен сам не защищает от XSS в браузере.
10. **HTTP/2 и Connection Migration:** При миграции TCP-соединения в HTTP/3 (QUIC) IP-адрес меняется. Для mTLS это не критично, но для DPoP убедитесь, что привязка ключа к клиенту остаётся валидной после миграции.

## Дополнительная информация

### Основные RFC

| RFC | Название / Тема | Статус в 2026 |
| :--- | :--- | :--- |
| **RFC 9110** | HTTP Semantics (включая Auth) | Базовый стандарт |
| **RFC 7617** | Basic Authentication | Legacy, только для технического доступа |
| **RFC 6750** | Bearer Token Usage | Стандарт передачи токена |
| **RFC 7616** | Digest Authentication | Устаревший, не рекомендуется |
| **RFC 6749** | OAuth 2.0 Framework | Основа авторизации |
| **RFC 9700** | OAuth 2.0 Security BCP | Безопасные практики (обязательно) |
| **RFC 6819** | OAuth 2.0 Threat Model | Угрозы и контрмеры |
| **RFC 8252** | OAuth 2.0 for Native Apps | PKCE и кастомные схемы URI |
| **RFC 8628** | Device Authorization Grant | TV, IoT, CLI без браузера |
| **RFC 8705** | OAuth 2.0 Mutual TLS | Привязка токена к сертификату |
| **RFC 9449** | OAuth 2.0 DPoP | Доказательство владения ключом |
| **RFC 9421** | HTTP Signatures | Подпись запроса/ответа |
| **RFC 7519** | JSON Web Token (JWT) | Стандарт токенов |
| **RFC 7515** | JSON Web Signature (JWS) | Подпись JWT |
| **RFC 7636** | PKCE | Proof Key for Code Exchange |

### Сравнение методов аутентификации

| Метод | Уровень безопасности | Состояние | Сфера применения |
| :--- | :--- | :--- | :--- |
| **Passkeys / WebAuthn** | Максимальный | Stateless | Основной вход пользователей |
| **mTLS** | Максимальный | Stateless | M2M, критичные API |
| **DPoP + JWT** | Высокий | Stateless | Мобильные и SPA приложения |
| **HTTP Signatures** | Высокий | Stateless | Финансовые API, микросервисы |
| **Bearer (OAuth 2.1)** | Средний/Высокий | Stateless | Микросервисы, публичные API |
| **Куки/Сессии** | Высокий | Stateful | Монолитные веб-приложения |
| **Basic** | Низкий | Stateless | Технический доступ, локальная отладка |

### Смотрите также

- **[Различия аутентификации и авторизации](../../../Security/Concepts/authentication_vs_authorization.md)** — концептуальный обзор процессов.
- **[Обзор протокола OAuth 2.0 / 2.1](../../../Security/Concepts/oauth2_overview.md)** — детали работы с токенами доступа.
- **[Обзор JWT-токенов](../../../Security/Concepts/jwt_overview.md)** — структура, подпись, распространённые ошибки.
- **[Безопасность HTTP в продакшене](./http_security_hardening.md)** — WAF, request smuggling, brute-force protection.
- **[TLS-шифрование и сертификаты для HTTP](./http_tls_hardening.md)** — mTLS, cipher suites, OCSP stapling.
