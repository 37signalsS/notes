# JWT (JSON Web Token) — открытый стандарт токенов

**Актуально для:** RFC 7519, RFC 8725 (Best Current Practices), RFC 9449 (DPoP), OAuth 2.1

## Определения

**JWT (JSON Web Token)** — открытый стандарт ([RFC 7519](https://datatracker.ietf.org/doc/html/rfc7519)) для компактной и безопасной передачи информации между сторонами в виде объекта JSON. Благодаря цифровой подписи данные в JWT являются доверенными и защищенными от подделки.

**JWT является частью стека JOSE (JSON Object Signing and Encryption):**
*   **JWS (JSON Web Signature):** Структура данных с подписью (наиболее частый вид JWT).
*   **JWE (JSON Web Encryption):** Зашифрованный контент (используется, когда данные в Payload нельзя показывать клиенту).
*   **JWA (JSON Web Algorithms):** Спецификация используемых криптографических алгоритмов.
*   **JWK (JSON Web Key):** Формат представления криптографических ключей в виде JSON.

## Основные концепции

### JWT и Bearer: разные уровни

В конструкции `Authorization: Bearer <token>` смешаны два независимых уровня:

| Часть | Что это |
| :--- | :--- |
| `Authorization` | HTTP-заголовок. |
| `Bearer` | Схема передачи токена («доступ получает тот, кто предъявил токен»). |
| `<token>` | Сам токен. |
| JWT | Возможный формат этого токена (`header.payload.signature`). |

Следствия:

- Bearer-токен может быть JWT, но не обязан — это может быть **opaque token** (непрозрачная случайная строка без встроенных claims, проверяемая только через introspection на сервере, который её выдал).
- Фраза «JWT-авторизация» неточна: JWT не определяет способ передачи токена, не определяет, кто и по какому flow его выдал, и не является протоколом авторизации. Авторизация может использовать claims из JWT, но сам JWT — формат.
- Корректные формулировки: «Bearer authentication с JWT access token», «API принимает access token в формате JWT через `Authorization: Bearer`».

### Структура токена (JWS)

JWT состоит из трёх частей, разделённых точкой (`.`):
1.  **Header (Заголовок):** Содержит метаданные — тип токена (`typ`) и алгоритм подписи (`alg`).
2.  **Payload (Полезная нагрузка):** Содержит утверждения (**Claims**).
3.  **Signature (Подпись):** Результат хеширования заголовка и полезной нагрузки с использованием секретного ключа.

### Утверждения (Claims) и их валидация

*   **Зарегистрированные (Registered):** Стандартные поля, обязательные для проверки:
    *   `iss` (Issuer): Кто выпустил токен.
    *   `sub` (Subject): Идентификатор пользователя.
    *   `aud` (Audience): Для какого сервиса предназначен токен.
    *   `exp` (Expiration): Время истечения. Обязательно для верификации (RFC 8725 §2); токен не должен приниматься после `exp`.
    *   `nbf` (Not Before): Токен не валиден до этого времени.
    *   `iat` (Issued At): Время выпуска.
    *   `jti` (JWT ID): Уникальный ID токена для защиты от атак повтора (Replay attacks).
*   **Приватные (Private):** Пользовательские данные (например, `roles`, `email`, `org_id`).

### Алгоритмы подписи (JWA)

| Алгоритм | Тип | Статус (2026) | Описание |
| :--- | :--- | :--- | :--- |
| **EdDSA** (Ed25519) | Асимметричный | **Рекомендовано** | Современный стандарт. Высокая скорость, малый размер ключа и высокая безопасность. |
| **ES256** (ECDSA + SHA256) | Асимметричный | **Рекомендовано** | Хорошая производительность, компактная подпись (64 байта для P-256). Требует корректного выбора curves. |
| **RS256** (RSA + SHA256) | Асимметричный | Стандарт | Классический выбор для OIDC. Требует больших ключей (от 2048 бит). |
| **HS256** (HMAC + SHA256) | Симметричный | Ограничено | Один секрет. Подходит только для внутренней микросервисной связи. |
| **none** | Нет | **Запрещено** | Токен без подписи. Использование ведет к критическим уязвимостям. |

### JWKS (JSON Web Key Set)

**JWKS** ([RFC 7517](https://datatracker.ietf.org/doc/html/rfc7517)) — это HTTP-эндпоинт (обычно `/.well-known/jwks.json`), публикующий набор открытых ключей сервера авторизации.
*   **Преимущество:** Сервисы-потребители могут автоматически обновлять ключи при их ротации на сервере без перезапуска.
*   **Безопасность:** Позволяет легко переходить на новые ключи в случае компрометации старых.

#### JWKS URI и кэширование

Помимо статического файла, JWKS может поставляться через HTTP-эндпоинт:
- **jwks_uri** в OpenID Connect Discovery (`/.well-known/openid-configuration`) — стандартный способ discovery в OIDC.
- **Кэширование:** Сервисы-потребители должны кэшировать JWKS с TTL (обычно 5–10 минут) и обновлять асинхронно, чтобы избежать thundering herd при массовой ротации ключей.

#### Grace Period при ротации

При компрометации ключа или плановой ротации:
1. Новый ключ добавляется в JWKS вместе с старым.
2. Старые токены, выданные на старый ключ, продолжают валидироваться до истечения `exp`.
3. После grace period старый ключ удаляется из JWKS.

## Практические сценарии

### Паттерн Access и Refresh токенов

Используется для минимизации рисков при stateless-аутентификации:
1.  **Access Token:** Короткоживущий (5–15 мин). Передается в заголовке `Authorization: Bearer`.
2.  **Refresh Token:** Долгоживущий (дни/недели). Используется только для получения нового Access Token.
3.  **Ротация:** При каждом использовании Refresh токена выдается новая пара. Старый Refresh токен аннулируется. Это позволяет обнаружить кражу токена (если кто-то пытается использовать старый Refresh токен дважды).

### Привязка токена (DPoP — RFC 9449)

**DPoP (Demonstrating Proof-of-Possession)** — механизм привязки JWT к конкретному клиенту.
*   **Проблема:** Обычный Bearer-токен может быть использован любым, кто его перехватил.
*   **Решение:** Клиент подписывает каждый HTTP-запрос временным ключом. Сервер проверяет, что токен был выдан именно для этого ключа. Это делает украденные JWT бесполезными без доступа к приватному ключу клиента.

### Валидация JWT на Python (EdDSA / PyJWT)

```python
import jwt
import requests

# 1. Получение публичного ключа из JWKS (упрощенно)
jwks_url = "https://auth.example.com/.well-known/jwks.json"
public_key = requests.get(jwks_url).json()["keys"][0] 

token = "eyJhbG..."

try:
    # 2. Декодирование с обязательной проверкой алгоритма и Claims
    decoded = jwt.decode(
        token, 
        public_key, 
        algorithms=["EdDSA"], 
        audience="my-api-service",
        options={"require": ["exp", "iss", "sub"]}
    )
    print("User ID:", decoded["sub"])
except jwt.ExpiredSignatureError:
    print("Срок действия токена истек")
except jwt.InvalidTokenError as e:
    print("Ошибка валидации:", e)
```

### Валидация JWT на Edge (Reverse Proxy / Load Balancer)

В высоконагруженных инфраструктурах JWT валидируется на L7 перед проксированием запроса к бэкенду. Это позволяет:
- Снимать нагрузку по валидации с приложения
- Централизованно применять политики доступа
- Блокировать невалидные запросы на раннем этапе

**Angie/Nginx:** модуль `ngx_http_auth_jwt_module` проверяет подпись по JWKS-файлу и позволяет фильтровать по Claims (роли, группы). Детали конфигурации — в [Контроль доступа в Angie](../../WebServers/Angie/angie_access_control.md).

**HAProxy:** встроенная поддержка JWT-валидации (начиная с версии 2.4) через `lua` скрипты или внешние сервисы. Детали — в [Обзор HAProxy](../../WebServers/haproxy_overview.md).

**Envoy:** используется в Service Mesh (Istio) для RequestAuthentication на уровне шлюза или sidecar. Детали — в [Политики безопасности Istio](../../Service_Mesh/istio-security-policies.md).

### JWT в мониторинге и Observability

**Grafana:** поддерживает аутентификацию по JWT-токену в заголовке (например, `X-JWT-Assertion`). Grafana проверяет подпись по JWKS IdP, кэширует ключи и сопоставляет claims с ролями. Подходит для machine-to-machine доступа и reverse-proxy сценариев. Детали — в [Enterprise SSO — SAML, JWT и расширенный LDAP](../../Grafana/grafana_sso_saml_jwt.md).

**Prometheus Blackbox Exporter:** может опрашивать эндпоинты с передачей JWT в заголовке `Authorization: Bearer`. Позволяет проверять доступность внутренних сервисов, защищённых JWT-аутентификацией.

#### Метрики JWT для observability

Приложения и прокси должны экспортировать стандартные метрики аутентификации для построения SRE-дашбордов и алертинга:

| Метрика | Описание | Критические метки |
| :--- | :--- | :--- |
| `auth_jwt_valid_total` | Количество успешно валидированных JWT | `audience`, `issuer` |
| `auth_jwt_invalid_total` | Количество отклонённых JWT | `reason` (expired, bad_signature, invalid_claims, alg_none) |
| `auth_jwt_validation_duration_seconds` | Latency валидации подписи JWT | `method` (local, jwks, introspection) |
| `auth_jwt_jwks_fetch_total` | Количество запросов к JWKS-эндпоинту | `status` (2xx, 4xx, 5xx) |
| `auth_jwt_jwks_cache_hit_ratio` | Доля запросов обслуженных из кэша JWKS | — |

**Важно:** Не используйте `sub` или `jti` в метках метрик — высокая кардинальность приводит к problems с Prometheus. Используйте `issuer`/`audience` для агрегации по сервису.

#### AlertManager правила для JWT

```yaml
# rules/jwt_rules.yml
groups:
- name: jwt_alerts
  rules:
  - alert: JWTInvalidTokensRate
    expr: rate(auth_jwt_invalid_total{reason!="expired"}[5m]) > 10
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "Высокая частота невалидных JWT (не из-за истечения)"
      description: "{{ $value }} невалидных токенов/сек. Возможна атака или проблемы с JWKS."

  - alert: JWTJwksEndpointDown
    expr: up{job="auth-server"} == 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "JWKS эндпоинт недоступен"
      description: "Сервис авторизации недоступен. JWT-валидация перестанет работать для новых ключей."

  - alert: JWTJwksFetchFailures
    expr: rate(auth_jwt_jwks_fetch_total{status=~"4..|5.."}[5m]) > 0
    for: 3m
    labels:
      severity: critical
    annotations:
      summary: "Ошибки получения JWKS"
      description: "{{ $value }} ошибок/сек при получении JWKS."

  - alert: JWTStaleCache
    expr: auth_jwt_jwks_cache_hit_ratio < 0.5
    for: 1m
    labels:
      severity: warning
    annotations:
      summary: "Снижение эффективности кэша JWKS"
      description: "Hit ratio < 50%. Увеличьте TTL кэша или проверьте доступность JWKS."
```

#### Аудит и беспрепятственное восстановление (SRE runbook)

**Инцидент: JWKS эндпоинт недоступен (HTTP 5xx/таймаут)**

1. Проверить доступность через `curl -sS -o /dev/null -w "%{http_code}" https://auth.example.com/.well-known/jwks.json`
2. Проверить health check сервиса авторизации (`/healthz`, `/ready`)
3. Если проблема в инфраструктуре — включить fallback: разослать JWKS напрямую через CDN/статический файл
4. Если таймаут — проверить DNS, TLS-сертификаты, upstream
5. Документировать в change log и выполнить post-mortem

**Инцидент: Массовые JWT validation failures (401 для валидных токенов)**

1. Проверить логи приложения: `grep "JWT validation error" /var/log/app.log`
2. Проверить наличие в кэше старого `kid`: `redis-cli GET "jwks:cache:v1"`
3. Проверить время сервера: `date -d @$(echo "eyJ..." | cut -d. -f2 | base64 -d | jq .iat)`
4. Если проблема в ротации ключей — выполнить forced JWKS refresh: `curl -X POST http://app:8080/internal/reload-jwks`
5. Если clock skew — синхронизировать NTP на всех узлах

**Процедура ротации ключей (SRE playbook)**

```bash
#!/bin/bash
# rotate-jwk.sh — ротация RSA/ECDSA ключа для подписи JWT
# Использование: ./rotate-jwk.sh <key_id> <new_key_file>

set -euo pipefail

KEY_ID="$1"
NEW_KEY_FILE="$2"
JWKS_URL="https://auth.example.com/.well-known/jwks.json"
JWKS_ADMIN_API="https://auth.example.com/admin/jwks"

# 1. Сгенерировать новый ключ
openssl ecparam -name prime256v1 -genkey -noout -out "$NEW_KEY_FILE"

# 2. Добавить в JWKS (grace period — старый ключ остаётся)
curl -X POST "$JWKS_ADMIN_API" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"kid\": \"$KEY_ID\", \"key_file\": \"$NEW_KEY_FILE\"}"

# 3. Подождать, пока все активные токены с старым ключом истекнут
sleep $((15 * 60))

# 4. Удалить старый ключ
curl -X DELETE "$JWKS_ADMIN_API/$KEY_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo "Ротация завершена. Проверьте логи на ошибки валидации."
```

**Процедура экстренного отзова (break-glass)**

Для немедленного отзова скомпрометированного токена или ключа:
1. Добавить `jti` в Redis blacklist с TTL = `exp`:
   ```bash
   redis-cli SETEX "jwt:blacklist:${jti}" $(( exp - $(date +%s) )) "revoked"
   ```
2. Добавить проверку в валидацию:
   ```python
   if redis.exists(f"jwt:blacklist:{payload.get('jti')}"):
       raise jwt.InvalidTokenError("Token revoked")
   ```
3. При компрометации ключа — удалить `kid` из JWKS и выполнить ротацию (см. playbook выше)

#### Защита от brute-force атак на JWT

**fail2ban:** Настройка фильтра для обнаружения массовых неудачных JWT-валидаций:

```ini
# /etc/fail2ban/filter.d/jwt-bruteforce.conf
[Definition]
failregex = ^.*jwt validation error.*Invalid token.*<HOST>.*$
            ^.*HTTP/1\.1" 401.*Authorization: Bearer.*<HOST>.*$
ignoreregex =

# /etc/fail2ban/jail.local
[jwt-bruteforce]
enabled = true
filter = jwt-bruteforce
logpath = /var/log/app/auth.log
maxretry = 20
findtime = 60
bantime = 3600
action = iptables[name=JWT, port=http, protocol=tcp]
```

Валидация: `fail2ban-client status jwt-bruteforce`

### JWT в GitOps и CI/CD пайплайнах

**Argo CD:** поддерживает SSO через OIDC/JWT. Провайдер (Keycloak, Dex) выдает ID Token, который Argo CD валидирует по JWKS. Это позволяет использовать корпоративные учётные записи для доступа к GitOps-интерфейсу вместо статических admin-токенов. Детали — в [SSO с GitLab (JWT/OIDC)](../../GitOps/ArgoCD/argocd_sso_gitlab.md).

**Vault:** метод `jwt` аутентификации позволяет раннерам CI/CD (GitLab CI, GitHub Actions) аутентифицироваться в Vault по JWT-токену, выданному платформой, без статических `ROLE_ID`/`SECRET_ID`. Детали — в [Ansible Vault: интеграция с CI/CD](../../Ansible/Vault/passwords.md).

### JWT в Kubernetes

**ServiceAccount JWT:** Каждый ServiceAccount в Kubernetes имеет связанный JWT-токен (хранится в `/var/run/secrets/kubernetes.io/serviceaccount/token`). Под может использовать его для аутентификации в:
- Kubernetes API Server (через `Authorization: Bearer`)
- Vault (метод `kubernetes` auth)
- Внешние сервисы, доверяющие Kubernetes-подписи

**kubeconfig с OIDC:** Для пользователей статические токены заменяются на OIDC-флоу с плагином `kubelogin`. Kubeconfig не содержит секретов — токен короткоживущий и автоматически ротируется. Детали — в [Kubeconfig и подключение](../../Kubernetes/Operations/kubeconfig_and_connection.md).

### Диагностика и отладка JWT

Sysadmin-инструменты для быстрой проверки токена без развёртывания полноценного приложения:

```bash
# 1. Декодирование Header и Payload (только для диагностики, не заменяет валидацию подписи)
echo "eyJhbG..." | awk -F. '{print $1"."$2}' | base64 -d 2>/dev/null | jq .

# 2. Проверка срока действия (exp) — сравнение с текущим Unix timestamp
echo "eyJhbG..." | cut -d. -f2 | base64 -d 2>/dev/null | jq '.exp'
echo "Текущее время: $(date +%s)"

# 3. Проверка доступности JWKS-эндпоинта
curl -sS https://auth.example.com/.well-known/jwks.json | jq '.keys[0] | {kty, kid, alg}'

# 4. Проверка подписи через OpenSSL (для HMAC-алгоритмов, только для тестов)
echo "eyJhbG..." | cut -d. -f1-2 | openssl dgst -sha256 -hmac "secret" -binary | base64url
```

**Типичные ошибки и причины:**

| Симптом | Вероятная причина |
| :--- | :--- |
| `401 Unauthorized` при валидном токене | Неправильный `aud` или `iss`; истек `exp`; токен подписан другим ключом |
| `alg: none` в заголовке | Попытка атаки; отклоняйте такие токены unconditionally |
| Дублирование `Authorization` заголовка | Прокси (HAProxy/Angie) может обрезать или дублировать заголовок при редиректах |
| Токен перехвачен и передан повторно | Отсутствие DPoP/Sender-Constrained Tokens; недостаточный TTL access token |

## Дополнительная информация

### Рекомендации по безопасности (RFC 8725)

1.  **Проверка алгоритма:** Всегда жестко ограничивайте список разрешенных алгоритмов в коде (`algorithms=["EdDSA"]`).
2.  **Explicit Typ:** Используйте заголовок `typ: "at+jwt"` для Access-токенов, чтобы предотвратить подмену типов токенов (Token Type Confusion).
3.  **Хранение:** 
    *   **В вебе:** Никогда не храните JWT в `localStorage` (уязвимо к XSS). Используйте `HttpOnly`, `Secure`, `SameSite=Strict` Cookies.
    *   **В мобильных приложениях:** Используйте защищенные хранилища (Keychain/Keystore).
4.  **Отзыв (Revocation):** Для немедленного отзыва stateless токенов используйте **Blacklisting** в Redis (хранение `jti` отозванных токенов до их истечения по `exp`).

### Ротация ключей JWKS и управление секретами

При компрометации приватного ключа или плановой ротации:

1. **Grace Period:** Новый ключ добавляется в JWKS вместе с старым. Старые токены продолжают работать до истечения `exp`.
2. **Аннулирование:** Для немедленного отзыва используйте Redis-блокировку (`jti` отозванных токенов) до истечения `exp`.
3. **Автоматизация:** Инструменты вроде `cert-manager` или `Vault` могут автоматически ротировать ключи и публиковать обновлённый JWKS.
4. **Мониторинг:** Следите за временем истечения `exp` у активных токенов и временем удаления старых ключей из JWKS.

### Производительность и масштабирование JWT

- **Размер токена:** JWT в 3–5 раз больше opaque-токена из-за claims. При большом объёме claims (роли, permissions) токен может превышать 4 KB, что влияет на размер HTTP-заголовков. Решение: использовать короткие имена claims, хранить полные данные в introspection endpoint.
- **JWKS кэширование:** JWKS должен кэшироваться на стороне потребителя (TTL 5–10 мин). При ротации ключей stale-кэш приводит к отказу валидных токенов.
- **Локальная валидация vs Introspection:** Статическая JWT-валидация быстрее (нет сетевого запроса), но не позволяет мгновенно отозвать токен. Opaque token + introspection даёт мгновенный отзов, но добавляет latency и SPOF.
- **Лимиты HTTP-серверов:** Nginx/Angie по умолчанию имеют `large_client_header_buffers` 8KB или 16KB. JWT > 4KB в заголовке `Authorization` потребует увеличения буферов.

### Альтернатива: PASETO

**PASETO (Platform-Agnostic SEcurity TOkens)** — современная альтернатива JWT, созданная для исправления его архитектурных недостатков. В отличие от JWT, где разработчик может выбрать небезопасный алгоритм, PASETO предлагает фиксированные «версии» с гарантированно стойкой криптографией.

### Связанные темы

- **[OAuth 2.0 / 2.1](./oauth2_overview.md)** — протоколы делегирования доступа, потоки, PKCE.
- **[HTTP-аутентификация](../../Networking/Protocols/HTTP/http_authentication.md)** — способы передачи токенов, Bearer, OIDC Discovery.
- **[Аутентификация vs Авторизация](./authentication_vs_authorization.md)** — различие понятий, типичные смешения.
- **[Контроль доступа в Angie](../../WebServers/Angie/angie_access_control.md)** — валидация JWT на reverse proxy.
- **[Обзор HAProxy](../../WebServers/haproxy_overview.md)** — JWT-валидация на балансировщике.
- **[Политики безопасности Istio](../../Service_Mesh/istio-security-policies.md)** — RequestAuthentication (JWT) на уровне sidecar/шлюза.
- **[Kubeconfig и OIDC](../../Kubernetes/Operations/kubeconfig_and_connection.md)** — JWT-токены в Kubernetes (ServiceAccount, kubelogin).
- **[Grafana: SAML, JWT и LDAP](../../Grafana/grafana_sso_saml_jwt.md)** — практическая конфигурация JWT-аутентификации.
- **[Vault: интеграция с Kubernetes](../../Vault/guides/vault_kubernetes_integration.md)** — аутентификация по ServiceAccount JWT.
- **[Redis для кэширования и отзыва токенов](../../Databases/redis_overview.md)** — реализация списков отзыва (blacklist) и кэширования JWKS.

- **[Fail2ban — защита от brute-force](../../Linux/Security/Tools/fail2ban.md)** — фильтры для обнаружения массовых неудачных JWT-валидаций.
