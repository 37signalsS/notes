# OAuth 2.0 и OpenID Connect

**Актуально для:** OAuth 2.1 (draft-ietf-oauth-v2-1-16), OpenID Connect Core 1.0, oauth2-proxy 7.15.x

## Определения

**OAuth 2.0 (Open Authorization)** — открытый протокол делегированной авторизации ([RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749)), позволяющий приложениям получать ограниченный доступ к ресурсам пользователя без передачи его учетных данных (пароля). Протокол основан на делегировании прав через выдачу токенов.

**OpenID Connect (OIDC)** — слой идентификации, построенный поверх OAuth 2.0 ([OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)). Добавляет стандартизированный формат **ID Token** (JWT) и эндпоинт `UserInfo` для получения данных профиля пользователя.

**OAuth 2.1** — консолидированная спецификация ([draft-ietf-oauth-v2-1](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-v2-1-16)), объединяющая и упрощающая OAuth 2.0. Исключает небезопасные механизмы (Implicit Grant, Resource Owner Password Credentials) и делает **PKCE** обязательным для всех типов клиентов. В 2026 году находится на стадии Internet-Draft (-16), заменяет RFC 6749 и RFC 6750. Руководство по безопасности — [RFC 9700](https://datatracker.ietf.org/doc/html/rfc9700).

## Основные концепции

### Роли в архитектуре

| Роль | Технический термин | Описание |
| :--- | :--- | :--- |
| **Владелец ресурса** | Resource Owner | Сущность (обычно пользователь), предоставляющая доступ к своим данным. |
| **Клиент** | Client | Приложение, запрашивающее доступ к ресурсам (веб, мобильное, сервис). |
| **Сервер авторизации** | Authorization Server | Сервер, проверяющий личность владельца и выдающий токены доступа. |
| **Сервер ресурсов** | Resource Server | API или сервис, хранящий защищённые данные и валидирующий токены. |

### Типы клиентов

1.  **Confidential Clients (Конфиденциальные):** могут безопасно хранить секрет приложения (например, серверные веб-приложения). Используют `client_secret`.
2.  **Public Clients (Публичные):** не могут гарантировать безопасность секрета (SPA в браузере, нативные мобильные приложения). Для них обязателен механизм **PKCE**.

### Типы токенов

-   **Access Token (Токен доступа):** Краткосрочный объект (обычно в формате [JWT](./jwt_overview.md)), используемый для доступа к защищенным ресурсам. Содержит **Scopes** (области доступа).
-   **Refresh Token (Токен обновления):** Долгосрочный токен для получения новой пары токенов без повторного ввода пароля пользователем.
-   **ID Token (Токен идентификации):** (только в OIDC) JWT, содержащий утверждения (claims) о пользователе: `sub`, `email`, `name`.

Access token и ID token решают разные задачи и не взаимозаменяимы:

| Token | Для чего нужен |
| :--- | :--- |
| Access token | Доступ к API / resource server. |
| ID token | Информация о том, кто пользователь. |

**Валидация ID token обязательна.** Backend не должен просто декодировать ID token и доверять содержимому: проверяются подпись, `iss`, `aud`, `exp` и другие условия (подробнее о claims и их валидации — [JWT](./jwt_overview.md)).

### OAuth2 — авторизация, а не логин

OAuth2 отвечает на вопрос «к каким ресурсам это приложение может получить доступ от имени пользователя?», а не «кто этот пользователь?». Ключевые свойства:

- Это фреймворк **delegated authorization**: пользователь не отдаёт пароль стороннему приложению, а выдаёт разрешение.
- Приложение получает access token, который доказывает не «кто пользователь», а «какой доступ выдан клиенту».

Поэтому формулировка «у нас логин через OAuth2» неточна; корректно — «OAuth2 используется для получения access token». Если речь именно про вход пользователя (аутентификацию), нужен OpenID Connect с его ID token.

### Области действия (Scopes)

Определяют права доступа. Стандартные scopes OIDC:

- `openid`: Обязателен для OIDC-запросов.
- `profile`: Доступ к ФИО, полу, дате рождения.
- `email`: Доступ к адресу электронной почты.
- `offline_access`: Запрос Refresh токена.

### Продвинутые механизмы безопасности

-   **DPoP (Demonstrating Proof-of-Possession)** ([RFC 9449](https://datatracker.ietf.org/doc/html/rfc9449)): Метод привязки токена к ключу клиента через HTTP-заголовок `DPoP` с подписью JWT. Защищает от использования токена, если он был украден.
-   **FAPI (Financial-grade API):** Профиль безопасности поверх OAuth/OIDC с жёсткими требованиями к шифрованию и подписанию запросов (используется в финтехе и критических системах).
-   **PAR (Pushed Authorization Requests):** Клиент передаёт параметры авторизации напрямую на сервер через POST-запрос, получая ссылку, что скрывает данные от URL браузера.
-   **OAuth 2.0 Token Exchange** ([RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693)): Протокол обмена токенами между сервисами (STS), позволяющий преобразовать один тип токена в другой (например, OIDC ID token → access token для реестра).
-   **OAuth 2.0 Token Introspection** ([RFC 7662](https://datatracker.ietf.org/doc/html/rfc7662)): Эндпоинт `/introspect`, позволяющий resource server проверить валидность токена (особенно opaque-токенов) на сервере авторизации в реальном времени.
-   **OAuth 2.0 Token Revocation** ([RFC 7009](https://datatracker.ietf.org/doc/html/rfc7009)): Эндпоинт `/revoke` для немедленного аннулирования токена.
-   **OIDC Discovery** ([RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414) / [OpenID Connect Discovery](https://openid.net/specs/openid-connect-discovery-1_0.html)): Автоматическое обнаружение эндпоинтов и публичных ключей через `/.well-known/openid-configuration`.

## Практические сценарии

### Основные типы авторизации (Grant Types)

| Метод | Использование | Статус (2026) |
| :--- | :--- | :--- |
| **Authorization Code + PKCE** | Все современные приложения | **Рекомендовано** |
| **Client Credentials** | Межсерверное взаимодействие (M2M) | Рекомендовано |
| **Device Code** | Устройства без браузера (CLI, Smart TV) | Рекомендовано |
| **Implicit Grant** | Старые SPA | **Запрещено (OAuth 2.1)** |
| **Resource Owner Password (ROPC)** | Старые нативные приложения | **Запрещено (OAuth 2.1)** |

### Механизм PKCE (Proof Key for Code Exchange)

Предотвращает перехват кода авторизации (Authorization Code Injection):

1.  **Клиент** генерирует секретную строку `code_verifier` и вычисляет её хеш `code_challenge`.
2.  Запрос на авторизацию отправляется с `code_challenge`.
3.  При обмене кода на токены клиент передаёт исходный `code_verifier`.
4.  **Сервер** хеширует полученный верификатор и сравнивает с ранее полученным челленджем.

### Ротация токенов (Refresh Token Rotation)

Метод повышения безопасности для публичных клиентов: при каждом использовании Refresh токена сервер выдаёт новую пару (Access + Refresh), а старый Refresh токен аннулируется. Это позволяет обнаружить кражу токенов (при попытке повторного использования старого токена сервер аннулирует всю цепочку сессии).

### Инструменты и реализации

-   **Keycloak:** Промышленный стандарт IdP (Identity Provider). Поддерживает OIDC, SAML, User Federation.
-   **Dex:** Лёгковесный OIDC-коннектор для Kubernetes, проксирующий запросы к LDAP/GitHub/GitLab.
-   **Zitadel:** Современная альтернатива Keycloak с акцентом на multi-tenancy и модульность, написана на Go.
-   **Ory Stack (Kratos, Hydra):** Модульные компоненты для построения собственной IAM-системы.
-   **Authentik:** Лёгкий self-hosted IdP с простотой развёртывания.
-   **Authelia:** Портальная аутентификация для Nginx/Traefik, 2FA, session management.

## Практическое развёртывание и эксплуатация (on-prem / self-hosted)

### Выбор Identity Provider для внутренней инфраструктуры

Для корпоративных сред без облачных зависимостей используются self-hosted IdP:

| Решение | Язык / Runtime | Лучшее применение |
| :--- | :--- | :--- |
| **Keycloak** | Java (Quarkus) | Полнофункциональный IAM, SSO, LDAP federation, fine-grained authz |
| **Authentik** | Python | Лёгкий self-hosted IdP, простота развёртывания |
| **Zitadel** | Go | Multi-tenancy, cloud-native архитектура, API-first |
| **Dex** | Go | Федеративный прокси (OIDC) для Kubernetes, тонкий слой поверх LDAP/GitHub/GitLab |
| **Authelia** | Go | Портальная аутентификация для Nginx/Traefik, 2FA, session |

**Рекомендации:**

- Для enterprise-сред с LDAP/AD — Keycloak или Zitadel.
- Для Kubernetes-only — Dex + внешний LDAP/GitLab.
- Для минимализма — Authelia в связке с Nginx/Traefik.

### Keycloak

Практическое развёртывание, эксплуатация и конфигурация Keycloak описаны в обзоре инструмента:

- [Keycloak — обзор](../Tools/keycloak_overview.md) — развёртывание, backup, безопасность и эксплуатация.

### Валидация токенов на Resource Server (Python)

```python
import jwt  # PyJWT >= 2.0
import requests

# PyJWKClient автоматически загружает и кэширует JWKS,
# обрабатывая ротацию ключей и поддерживая RSA, EC и EdDSA
jwks_url = "https://auth.internal.example.com/realms/internal/protocol/openid-connect/certs"
jwks_client = jwt.PyJWKClient(jwks_url)

def validate_token(token: str) -> dict:
    # Получение подписывающего ключа по kid из JWT-заголовка
    signing_key = jwks_client.get_signing_key_from_jwt(token)
    payload = jwt.decode(
        token,
        key=signing_key.key,
        algorithms=["RS256", "EdDSA"],
        audience="prometheus",
        issuer="https://auth.internal.example.com/realms/internal",
    )
    return payload
```

**Валидация:**

```bash
python3 validate_token.py
# → {"sub": "user-123", "email": "alice@example.com", "scope": "read:metrics"}
```

## Интеграция с Kubernetes

### kubectl через OIDC (kubelogin / Pinniped)

Для входа в кластер через корпоративный IdP без статических токенов:

```bash
# Установка kubelogin (int128/kubelogin)
curl -L https://github.com/int128/kubelogin/releases/latest/download/kubelogin-linux-amd64.tar.gz | tar xz
sudo mv kubelogin /usr/local/bin/

# Получение kubeconfig с OIDC-аутентификацией
kubectl oidc-login setup \
  --oidc-issuer-url=https://auth.internal.example.com/realms/internal \
  --oidc-client-id=kubernetes \
  --oidc-client-secret=client-secret \
  --oidc-extra-scope=email \
  --oidc-extra-scope=groups
```

Альтернатива — **Pinniped Supervisor**, который выступает OIDC-провайдером для API-сервера Kubernetes и обменивает внешний токен на краткоживущий ServiceAccount token.

### Валидация токенов в Ingress (Nginx/Angie через auth_request)

```nginx
location / {
    auth_request /auth;
    auth_request_set $auth_user $upstream_http_x_auth_user;

    proxy_pass http://backend;
    proxy_set_header X-User $auth_user;
    proxy_set_header X-Email $upstream_http_x_auth_email;
}

location = /auth {
    internal;
    proxy_pass http://auth-service:8080/verify;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header X-Original-URI $request_uri;
    proxy_set_header Authorization $http_authorization;
}
```

## Интеграция с CI/CD

### GitLab CI — беспарольная аутентификация через OIDC

GitLab CI/CD поддерживает `id_tokens` для получения временных OIDC-токенов без статических секретов:

```yaml
build_image:
  stage: build
  image: docker:29.9.1
  services:
    - docker:29.9.1-dind
  id_tokens:
    REGISTRY_TOKEN:
      aud: registry.example.com
  script:
    - docker login registry.example.com -u oidc --password-stdin
      <<< "$REGISTRY_TOKEN"
```

**Требования:** GitLab 17.0+, включённый `instance_oidc_token` или `workload_oidc_token` в настройках CI/CD.

### GitHub Actions — OIDC для внутренних сервисов

Для доступа к self-hosted реестрам или внутренним API. Требуется `permissions: id-token: write`.

```yaml
jobs:
  deploy:
    runs-on: self-hosted
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@v4
      - name: Login to internal registry
        run: |
          # 1. Запрос OIDC ID token от GitHub Actions
          ID_TOKEN=$(curl -sSL \
            -H "Authorization: Bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
            "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=registry.internal.example.com" \
            | jq -r '.value')

          # 2. Обмен ID token на registry access token (RFC 8693 Token Exchange)
          ACCESS_TOKEN=$(curl -sSL -X POST \
            https://registry.internal.example.com/oauth2/token \
            -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
            -d "subject_token=$ID_TOKEN" \
            -d "subject_token_type=urn:ietf:params:oauth:token-type:id_token" \
            -d "audience=registry.internal.example.com" \
            | jq -r '.access_token')
```

## OAuth2 Proxy для внутренних сервисов

OAuth2 Proxy защищает веб-приложения, не имеющие нативной OIDC-поддержки (Prometheus UI, Alertmanager, Grafana до нативной интеграции).

### Минимальный деплой (standalone)

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: oauth2-proxy-secret
  namespace: monitoring
type: Opaque
stringData:
  client-id: "prometheus-oauth"
  client-secret: "secret"
  cookie-secret: "16_bytes_random_value_here"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: oauth2-proxy
  namespace: monitoring
spec:
  replicas: 2
  selector:
    matchLabels:
      app: oauth2-proxy
  template:
    metadata:
      labels:
        app: oauth2-proxy
    spec:
      containers:
        - name: oauth2-proxy
          image: quay.io/oauth2-proxy/oauth2-proxy:v7.15.1
          args:
            - --provider=oidc
            - --oidc-issuer-url=https://auth.internal.example.com/realms/internal
            - --email-domain=*
            - --upstream=http://prometheus-server.monitoring.svc.cluster.local:9090
          env:
            - name: OAUTH2_PROXY_CLIENT_ID
              valueFrom:
                secretKeyRef:
                  name: oauth2-proxy-secret
                  key: client-id
            - name: OAUTH2_PROXY_CLIENT_SECRET
              valueFrom:
                secretKeyRef:
                  name: oauth2-proxy-secret
                  key: client-secret
            - name: OAUTH2_PROXY_COOKIE_SECRET
              valueFrom:
                secretKeyRef:
                  name: oauth2-proxy-secret
                  key: cookie-secret
          ports:
            - containerPort: 4180
          volumeMounts:
            - name: oauth2-proxy-secret
              mountPath: /etc/oauth2-proxy
              readOnly: true
          volumes:
            - name: oauth2-proxy-secret
              secret:
                secretName: oauth2-proxy-secret
```

**Валидация:**

```bash
kubectl get pods -n monitoring -l app=oauth2-proxy
# → NAME                        READY   STATUS
# → oauth2-proxy-xxx            1/1     Running

kubectl logs -l app=oauth2-proxy -n monitoring | grep -i "error\|unauthorized"
# → (пусто при корректной работе)
```

## Операции и команды

### Мониторинг и аудит OAuth2-потоков

#### Аудит событий аутентификации

```bash
# Логи Keycloak (если используется)
journalctl -u keycloak -f | grep -E "AUTH|LOGIN|TOKEN"

# Мониторинг эндпоинта /oauth/token в Nginx/Angie
tail -f /var/log/nginx/access.log | grep "/oauth2/token"

# Поиск ошибок валидации токенов в приложении
grep -i "jwt\|token.*invalid\|signature" /var/log/app/error.log | tail -20
```

#### Prometheus метрики для Keycloak

Keycloak экспортирует метрики на `/metrics`:

```yaml
# Prometheus scrape config
- job_name: 'keycloak'
  static_configs:
    - targets: ['keycloak.internal.example.com:8080']
  metrics_path: '/metrics'
```

### Резервное копирование и аварийное восстановление

#### Keycloak

Бэкап и восстановление Keycloak см. в [Keycloak — обзор](../Tools/keycloak_overview.md).

#### Бэкап Dex

Dex хранит конфигурацию в ConfigMap и динамические данные в Kubernetes secrets (если используется):

```bash
kubectl get configmap argocd-dex-server -n argocd -o yaml > dex-configmap.yaml
kubectl get secret argocd-dex-server-token -n argocd -o yaml > dex-secret.yaml
```

#### Бэкап OAuth2 Proxy secrets

```bash
kubectl get secret oauth2-proxy-secret -n monitoring -o yaml > oauth2-proxy-backup.yaml
```

## Типичные проблемы и диагностика

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Цикл редиректов (login loop)** | Браузер перенаправляет на IdP и обратно | Проверить `redirect_uri` в клиенте и в URL браузера | Убедиться, что `redirect_uri` в клиенте точно совпадает с URL в запросе |
| **401 Unauthorized** | Запрос отклонён despite валидный токен | `curl -v -H "Authorization: Bearer $TOKEN"` | Проверить `aud`, `iss`, `exp` в токене; убедиться что токен предназначен для этого ресурса |
| **403 Forbidden** | Токен валиден, но недостаточно прав | Декодировать JWT: `jwt decode $TOKEN --no-verify` | Проверить `scope` / `scp` claims; добавить недостающие scope в запрос |
| **PKCE mismatch** | Ошибка обмена кода на токен | Логи сервера авторизации: `code_verifier mismatch` | Проверить что `code_verifier` на клиенте соответствует `code_challenge` из запроса |
| **Токен не обновляется** | Refresh Token истёк или отозван | Проверить `exp` Refresh Token в introspection | Включить Refresh Token Rotation; проверить `refresh_token_lifespan` в IdP |
| **Dex CrashLoopBackOff** | Pod Dex не стартует | `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-dex-server` | Проверить конфигурацию connector, доступность внешнего IdP, валидность CA-сертификатов |
| **OAuth2 Proxy 502** | Прокси не может достичь IdP | `kubectl logs -l app=oauth2-proxy -n monitoring` | Разрешить egress к доменам IdP через NetworkPolicy; проверить `oidc-issuer-url` |
| **Сессия не сохраняется** | Пользователь разлогинивается после рестарта пода | Проверить `cookie-secret` и `session-store-type` | Для стабильности используйте внешний Redis для сессий; фиксируйте `cookie-secret` |
| **Ошибка JWKS** | Token validation fails: key not found | `curl -sS $JWKS_URL | jq '.keys[].kid'` | Убедиться что JWKS URL доступен; проверить ротацию ключей; добавить кэш stale-ключей |

## Безопасность и рекомендации

1. **HTTPS повсеместно:** Все эндпоинты OAuth2 (authorization, token, introspection, userinfo) должны быть доступны только по HTTPS. Внутренние сети не являются исключением.
2. **Короткий TTL Access Token:** 5–15 минут для Access Token. Для длительных операций используйте Refresh Token с Rotation.
3. **Sender-Constrained Tokens:** В high-risk средах используйте DPoP или mTLS certificate binding для привязки токена к клиенту.
4. **Rate limiting на /oauth/token:** Защита от credential stuffing и атак на PKCE verifier exhaustion.
5. **Валидация всех claims:** На Resource Server проверяйте `iss`, `aud`, `exp`, `nbf`, `scope`. Не полагайтесь только на формат токена.
6. **Логирование без секретов:** Логируйте `jti`, `sub`, `client_id`, но никогда не пишите `access_token`, `refresh_token`, `client_secret` или `code_verifier` в логи.
7. **Ротация client secrets:** Ротируйте `client_secret` раз в 90 дней. Используйте автоматическую ротацию, если IdP поддерживает.
8. **Token revocation on logout:** При выходе пользователя вызывайте `/revoke` (RFC 7009) для Access Token и Refresh Token.
9. **OIDC Discovery:** Используйте `/.well-known/openid-configuration` для автоматической настройки, а не ручное указание endpoint-ов.

- **Специфичные для Keycloak практики:** изоляция Realm, MFA для админов, сетевые ограничения — см. [Keycloak — обзор](../Tools/keycloak_overview.md).

## Дополнительная информация

### Основные RFC

| RFC | Название / Тема | Статус в 2026 |
| :--- | :--- | :--- |
| **RFC 6749** | OAuth 2.0 Framework | Основа авторизации (заменяется OAuth 2.1) |
| **RFC 6750** | OAuth 2.0 Bearer Token Usage | Использование bearer-токенов (заменяется OAuth 2.1) |
| **RFC 9700** | OAuth 2.0 Security BCP | Безопасные практики (обязательно) |
| **RFC 6819** | OAuth 2.0 Threat Model | Угрозы и контрмеры |
| **RFC 7009** | OAuth 2.0 Token Revocation | Аннулирование токенов |
| **RFC 7662** | OAuth 2.0 Token Introspection | Проверка токенов на сервере |
| **RFC 7636** | PKCE | Proof Key for Code Exchange |
| **RFC 8252** | OAuth 2.0 for Native Apps | PKCE и кастомные схемы URI |
| **RFC 8414** | OAuth 2.0 Authorization Server Metadata | Авто-обнаружение конфигурации |
| **RFC 8628** | OAuth 2.0 Device Authorization Grant | TV, IoT, CLI без браузера |
| **RFC 8693** | OAuth 2.0 Token Exchange | Обмен токенами между сервисами |
| **RFC 8705** | OAuth 2.0 Mutual TLS | Привязка токена к сертификату |
| **RFC 9449** | OAuth 2.0 DPoP | Доказательство владения ключом |
| **RFC 7519** | JSON Web Token (JWT) | Стандарт токенов |
| **RFC 7515** | JSON Web Signature (JWS) | Подпись JWT |
| **RFC 7517** | JSON Web Key (JWK) | Формат ключей |

- **draft-ietf-oauth-v2-1** — OAuth 2.1 Authorization Framework (текущий интернет-черновик, заменяет RFC 6749 и RFC 6750).

### Сравнение IdP для on-prem

| Критерий | Keycloak | Authentik | Dex | Zitadel |
| :--- | :--- | :--- | :--- | :--- |
| **Сложность развёртывания** | Средняя | Низкая | Низкая | Средняя |
| **LDAP/AD federation** | Да | Да | Через коннектор | Да |
| **Fine-grained AuthZ** | Да (RBAC/ABAC) | Да | Нет | Да |
| **Kubernetes-native** | Средняя | Средняя | Высокая | Высокая |
| **Производительность** | Средняя | Высокая | Высокая | Высокая |
| **Поддержка SAML** | Да | Да | Нет | Да |
| **Multi-tenancy** | Нет (по realm) | Да | Нет | Да |

### Связанные концепции

- [Аутентификация vs Авторизация](./authentication_vs_authorization.md) — базовые определения и отличия.
- [JWT (JSON Web Token)](./jwt_overview.md) — формат токенов, используемый в OAuth.
- [Keycloak — обзор](../Tools/keycloak_overview.md) — практическая работа с IdP.
- [Keycloak — интеграция с LDAP/AD](../Tools/keycloak_ldap_federation.md) — федерация пользователей.
- [HTTP-аутентификация](../../Networking/Protocols/HTTP/http_authentication.md) — OAuth 2.1, PKCE, DPoP, валидация JWT.
- [ArgoCD SSO через GitLab](../../GitOps/ArgoCD/argocd_sso_gitlab.md) — практическая настройка OIDC в GitOps.
- [Веб-аутентификация для Prometheus/Grafana](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/web_authentication.md) — OAuth2-proxy и нативная OIDC-интеграция.
- [Kubeconfig и OIDC](../../Kubernetes/Operations/kubeconfig_and_connection.md) — вход в Kubernetes через OIDC.
- [Pinniped: OIDC для Kubernetes](../../Kubernetes/Security/pinniped.md) — сервис аутентификации для кластеров.
- [Vault: аутентификация через OIDC SSO](../../Vault/guides/vault-auth-oidc-sso.md) — OIDC-аутентификация людей через Vault.
- [OIDC аутентификация в Traefik](../../WebServers/Traefik/traefik-oidc-auth.md) — ForwardAuth и OAuth2 Proxy.
