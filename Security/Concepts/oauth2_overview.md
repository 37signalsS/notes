# OAuth 2.0 и OpenID Connect

## Определение

**OAuth 2.0 (Open Authorization)** — открытый протокол авторизации ([RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749)), позволяющий приложениям получать ограниченный доступ к ресурсам пользователя без передачи его учетных данных (пароля). Протокол основан на делегировании прав через выдачу токенов.

**OpenID Connect (OIDC)** — слой идентификации (Identity), построенный поверх OAuth 2.0. Добавляет стандартизированный формат **ID Token** и эндпоинт `UserInfo` для получения данных профиля пользователя.

**OAuth 2.1** — актуальная консолидированная спецификация (стандарт 2025-2026 гг.), которая исключает небезопасные механизмы (Implicit Grant, Password Grant) и делает **PKCE** обязательным для всех типов клиентов.

## Основные концепции

### Роли в архитектуре

| Роль | Технический термин | Описание |
| :--- | :--- | :--- |
| **Владелец ресурса** | Resource Owner | Сущность (обычно пользователь), предоставляющая доступ к своим данным. |
| **Клиент** | Client | Приложение, запрашивающее доступ к ресурсам (веб, мобильное, сервис). |
| **Сервер авторизации** | Authorization Server | Сервер, проверяющий личность владельца и выдающий токены доступа. |
| **Сервер ресурсов** | Resource Server | API или сервис, хранящий защищенные данные и валидирующий токены. |

### Типы клиентов

1.  **Confidential Clients (Конфиденциальные):** могут безопасно хранить секрет приложения (например, серверные веб-приложения). Используют `client_secret`.
2.  **Public Clients (Публичные):** не могут гарантировать безопасность секрета (SPA в браузере, нативные мобильные приложения). Для них обязателен механизм **PKCE**.

### Типы токенов

-   **Access Token (Токен доступа):** Краткосрочный объект (обычно в формате [JWT](./jwt_overview.md)), используемый для доступа к защищенным ресурсам. Содержит **Scopes** (области доступа).
-   **Refresh Token (Токен обновления):** Долгосрочный токен для получения новой пары токенов без повторного ввода пароля пользователем.
-   **ID Token (Токен идентификации):** (только в OIDC) JWT, содержащий утверждения (claims) о пользователе: `sub`, `email`, `name`.

Access token и ID token решают разные задачи и не взаимозаменяемы:

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
3.  При обмене кода на токены клиент передает исходный `code_verifier`.
4.  **Сервер** хеширует полученный верификатор и сравнивает с ранее полученным челленджем.

### Ротация токенов (Refresh Token Rotation)

Метод повышения безопасности для публичных клиентов: при каждом использовании Refresh токена сервер выдает новую пару (Access + Refresh), а старый Refresh токен аннулируется. Это позволяет обнаружить кражу токенов (при попытке повторного использования старого токена сервером аннулируется вся цепочка сессии).

## Дополнительная информация

### Продвинутые механизмы безопасности

-   **DPoP (Demonstrating Proof-of-Possession):** Метод привязки токена к ключу клиента (через HTTP-заголовок с подписью). Защищает от использования токена, если он был украден.
-   **FAPI (Financial-grade API):** Профиль безопасности поверх OAuth/OIDC с жесткими требованиями к шифрованию и подписанию запросов (используется в финтехе и критических системах).
-   **PAR (Pushed Authorization Requests):** Клиент передает параметры авторизации напрямую на сервер через POST-запрос, получая ссылку, что скрывает данные от URL браузера.

### Инструменты и реализации

-   **Keycloak:** Промышленный стандарт IdP (Identity Provider). Поддерживает OIDC, SAML, User Federation.
-   **Dex:** Легковесный OIDC-коннектор для Kubernetes, проксирующий запросы к LDAP/GitHub/GitLab.
- **Zitadel:** Современная альтернатива Keycloak с акцентом на multi-tenancy и модульность, написана на Go.
-   **Ory Stack (Kratos, Hydra):** Модульные компоненты для построения собственной IAM-системы.

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

## Практическое развёртывание и эксплуатация (on-prem / self-hosted)

### Выбор Identity Provider для внутренней инфраструктуры

Для корпоративных сред без облачных зависимостей используются self-hosted IdP:

| Решение | Язык / Runtime | Лучшее применение |
| :--- | :--- | :--- |
| **Keycloak** | Java (Quarkus) | Полнофункциональный IAM, SSO, LDAP federation, fine-grained authz |
| **Authentik** | Python | Лёгкий self-hosted IdP, простота развёртывания |
| **Zitadel** | Go | Multi-tenancy, cloud-native архитектура, API-first |
| **Dex** | Go | Федеретивный прокси (OIDC) для Kubernetes, тонкий слой поверх LDAP/GitHub/GitLab |
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
import jwt  # PyJWT
import requests

# Получение JWKS из Authorization Server
jwks_url = "https://auth.internal.example.com/realms/internal/protocol/openid-connect/certs"
jwks = requests.get(jwks_url).json()

public_keys = {}
for jwk in jwks["keys"]:
    kid = jwk["kid"]
    public_keys[kid] = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)

def validate_token(token: str) -> dict:
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header["kid"]
    key = public_keys.get(kid)
    if not key:
        raise ValueError("Unknown key ID")
    payload = jwt.decode(
        token,
        key=key,
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
# Установка kubelogin (Pinniped)
curl -L https://github.com/int128/kubelogin/releases/latest/download/kubelogin-linux-amd64.zip | jar xv
sudo mv kubelogin /usr/local/bin/

# Получение kubeconfig с OIDC-аутентификацией
kubectl oidc-login setup \
  --oidc-issuer-url=https://auth.internal.example.com/realms/internal \
  --oidc-client-id=kubernetes \
  --oidc-client-secret=client-secret \
  --oidc-extra-scopes=email,groups
```

Альтернатива — **Pinniped Supervisor**, который выступает OIDC-провайдером для API-сервера Kubernetes и обменивает внешний токен на短оживущий ServiceAccount token.

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
  image: docker:29.8
  services:
    - docker:29.8-dind
  id_tokens:
    REGISTRY_TOKEN:
      aud: registry.example.com
  script:
    - docker login registry.example.com -u oidc --password-stdin
      <<< "$REGISTRY_TOKEN"
```

**Требования:** GitLab 17.0+, включённый `instance_oidc_token` или `workload_oidc_token` в настройках CI/CD.

### GitHub Actions — OIDC для внутренних сервисов

Для доступа к self-hosted реестрам или внутренним API:

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
          curl -X POST https://registry.internal.example.com/oauth2/token \
            -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange" \
            -d "subject_token=$ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
            -d "subject_token_type=urn:ietf:params:oauth:token-type:id_token" \
            -d "audience=registry.internal.example.com"
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
  cookie-secret: "$(openssl rand -base64 32)"
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
          image: quay.io/oauth2-proxy/oauth2-proxy:v0.15.0
          args:
            - --provider=oidc
            - --oidc-issuer-url=https://auth.internal.example.com/realms/internal
            - --client-id=/etc/oauth2-proxy/client-id
            - --client-secret=/etc/oauth2-proxy/client-secret
            - --cookie-secret=/etc/oauth2-proxy/cookie-secret
            - --email-domain=*
            - --upstream=http://prometheus-server.monitoring.svc.cluster.local:9090
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

## Мониторинг и аудит OAuth2-потоков

### Аудит событий аутентификации

```bash
# Логи Keycloak (если используется)
journalctl -u keycloak -f | grep -E "AUTH|LOGIN|TOKEN"

# Мониторинг эндпоинта /oauth/token в Nginx/Angie
tail -f /var/log/nginx/access.log | grep "/oauth2/token"

# Поиск ошибок валидации токенов в приложении
grep -i "jwt\|token.*invalid\|signature" /var/log/app/error.log | tail -20
```

### Prometheus метрики для Keycloak

Keycloak экспортирует метрики на `/metrics`:

```yaml
# Prometheus scrape config
- job_name: 'keycloak'
  static_configs:
    - targets: ['keycloak.internal.example.com:8080']
  metrics_path: '/metrics'
```

## Резервное копирование и аварийное восстановление

### Keycloak

Бэкап и восстановление Keycloak см. в [Keycloak — обзор](../Tools/keycloak_overview.md).

### Бэкап Dex

Dex хранит конфигурацию в ConfigMap и динамические данные в Kubernetes secrets (если используется):

```bash
kubectl get configmap argocd-dex-server -n argocd -o yaml > dex-configmap.yaml
kubectl get secret argocd-dex-server-token -n argocd -o yaml > dex-secret.yaml
```

### Бэкап OAuth2 Proxy secrets

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

## Безопасность и рекомендации

1. **HTTPS повсеместно:** Все эндпоинты OAuth2 (authorization, token, introspection, userinfo) должны быть доступны только по HTTPS. Внутренние сети не являются исключением.
2. **Короткий TTL Access Token:** 5–15 минут для Access Token. Для длительных операций используйте Refresh Token с Rotation.
3. **Sender-Constrained Tokens:** В high-risk средах используйте DPoP или mTLS certificate binding для привязки токена к клиенту.
4. **Rate limiting на /oauth/token:** Защита от credential stuffing и атак на PKCE verifier exhaustion.
5. **Валидация всех claims:** На Resource Server проверяйте `iss`, `aud`, `exp`, `nbf`, `scope`. Не полагайтесь только на формат токена.
6. **Логирование без секретов:** Логируйте `jti`, `sub`, `client_id`, но никогда не пишите `access_token`, `refresh_token`, `client_secret` или `code_verifier` в логи.
7. **Ротация client secrets:** Ротируйте `client_secret` раз в 90 дней. Используйте автоматическую ротацию, если IdP поддерживает.

- **Специфичные для Keycloak практики:** изоляция Realm, MFA для админов, сетевые ограничения — см. [Keycloak — обзор](../Tools/keycloak_overview.md).

## Дополнительная информация

### Основные RFC

| RFC | Название / Тема | Статус в 2026 |
| :--- | :--- | :--- |
| **RFC 6749** | OAuth 2.0 Framework | Основа авторизации |
| **RFC 9700** | OAuth 2.0 Security BCP | Безопасные практики (обязательно) |
| **RFC 6819** | OAuth 2.0 Threat Model | Угрозы и контрмеры |
| **RFC 7636** | PKCE | Proof Key for Code Exchange |
| **RFC 8252** | OAuth 2.0 for Native Apps | PKCE и кастомные схемы URI |
| **RFC 8628** | Device Authorization Grant | TV, IoT, CLI без браузера |
| **RFC 8705** | OAuth 2.0 Mutual TLS | Привязка токена к сертификату |
| **RFC 9449** | OAuth 2.0 DPoP | Доказательство владения ключом |
| **RFC 7519** | JSON Web Token (JWT) | Стандарт токенов |
| **RFC 7515** | JSON Web Signature (JWS) | Подпись JWT |

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
