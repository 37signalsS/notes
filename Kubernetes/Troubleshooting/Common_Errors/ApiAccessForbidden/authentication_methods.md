# Ошибки аутентификации: методы и код 401 Unauthorized

## Определения

**401 Unauthorized** — код состояния HTTP, означающий, что API-сервер Kubernetes не смог подтвердить личность (аутентифицировать) субъекта. Это первичный барьер безопасности: если личность не установлена, проверка прав (**RBAC**) не производится, и запрос отклоняется немедленно.

**Аутентификатор (Authenticator)** — модуль API-сервера, ответственный за проверку конкретного типа учетных данных (токены, сертификаты, пароли).

**TokenReview API** — механизм, позволяющий проверить валидность токена и получить информацию о субъекте (имя, группы) напрямую от API-сервера.

**Bound Service Account Token** — современный механизм (GA с v1.22), при котором JWT-токены ServiceAccount привязываются к конкретному поду, аудитории и временному интервалу. Токены автоматически ротируются Kubelet.

**Structured Authentication Configuration** — файл конфигурации (`--authentication-config`), поддерживающий несколько OIDC-провайдеров и CEL-выражения для маппинга claims (GA в v1.30).

> Различие 401 vs 403: [definitions.md](definitions.md)
> Полное описание механизмов: [../../../Security/authentication.md](../../../Security/authentication.md)
> Субъекты доступа и ServiceAccount: [../../../Security/rbac/subjects.md](../../../Security/rbac/subjects.md)

## Основные концепции

### Цепочка проверки запроса

Kubernetes использует список аутентификаторов, которые проверяются последовательно до первого успешного совпадения.

1.  **X509:** Клиентские сертификаты (админы, компоненты кластера).
2.  **ServiceAccount:** JWT токены (поды, автоматизация).
3.  **OIDC:** Внешние провайдеры (Okta, Keycloak, Google).
4.  **Webhook:** Кастомная проверка через внешний сервис.
5.  **Anonymous:** Если включено (`--anonymous-auth=true`), запросу назначается `system:anonymous`.

**Как работает последовательная проверка:**
```
Запрос → X509 проверка → (не совпало?) → SA токен → (не совпало?) → OIDC → (не совпало?) → Webhook → (не совпало?) → Anonymous
                │                              │                      │                        │
                ↓                              ↓                      ↓                        ↓
           Успех: OK                    Успех: OK              Успех: OK               Успех: OK
           (username из CN)             (system:serviceaccount:..)  (username из claims)   (username из webhook)
```

**Важно:** Порядок аутентификаторов определяется флагами API-сервера. Если несколько методов могут распознать один и тот же токен, срабатывает первый в цепочке.

### Новое в Kubernetes 1.30 и 1.31

-   **Legacy ServiceAccount Token Cleaner (v1.31 GA):** Контроллер автоматически удаляет неиспользуемые токены ServiceAccount, хранящиеся в Secrets (по умолчанию, если не использовались > 1 года).
-   **Structured Authentication Configuration (v1.30+):** Позволяет настраивать несколько OIDC-провайдеров через файл конфигурации и использовать CEL (Common Expression Language) для валидации заявок в токене.
-   **Node-binding (v1.31 Beta):** Токены могут быть жестко привязаны к конкретному узлу. Использование такого токена на другом узле приведет к 401.

### Частые причины отказа (401)

| Причина | Детали | Инструмент проверки |
| :--- | :--- | :--- |
| **Истекший токен** | JWT токен имеет ограниченный TTL (по умолчанию 1 час) | `kubectl create token` |
| **Token Cleaner** | Токен был удален из etcd как устаревший (v1.31+) | `kubectl get secret` |
| **Node Mismatch** | Токен привязан к другому узлу (Node-binding) | Логи API-сервера |
| **Clock Skew** | Разница во времени между клиентом и сервером > 300 сек | `ntpstat` / `timedatectl` |
| **Audience Mismatch** | Поле `aud` в токене не совпадает с настройками API | `jwt.io` / `step crypto jwt` |

## Практические сценарии

### Сценарий 1: Диагностика через TokenReview API

Если вы получили 401, проверьте, как API-сервер видит ваш токен. Это исключит проблемы на стороне клиента.

```bash
# Создание запроса на проверку токена
cat <<EOF | kubectl create -f -
apiVersion: authentication.k8s.io/v1
kind: TokenReview
spec:
  token: <ВАШ_ТОКЕН>
EOF

# Ожидаемый ответ при успехе:
# status:
#   authenticated: true
#   user:
#     username: system:serviceaccount:default:my-sa
```

**Ожидаемый результат при ошибке:**
```text
# Токен невалиден:
status:
  authenticated: false
  error: "token is expired"

# Токен отозван:
status:
  authenticated: false
  error: "token has been revoked"
```

### Сценарий 2: Проблемы с токенами в подах (K8s 1.24+)

В современных кластерах токены монтируются как проецируемые тома (Projected Volumes) и автоматически ротируются `kubelet`.

**Симптомы:** Приложение получает 401.
**Причины:**
1.  `kubelet` не может обновить токен (проблемы с API-сервером или диском).
2.  Токен привязан к конкретному поду (Object-binding), и вы пытаетесь использовать его вне этого пода.

**Решение:**
```bash
# Проверка монтирования токена
kubectl get pod <pod-name> -o jsonpath='{.spec.volumes[?(@.projected)].projected.sources}'

# Ручная генерация для теста (с заданным TTL и Audience)
kubectl create token <sa-name> --duration=1h --audience=my-api

# Проверка, что токен действительно смонтирован
kubectl exec <pod-name> -- ls -la /var/run/secrets/kubernetes.io/serviceaccount/

# Чтение токена из пода
kubectl exec <pod-name> -- cat /var/run/secrets/kubernetes.io/serviceaccount/token | head -c 50

# Проверка audience в токене
kubectl exec <pod-name> -- cat /var/run/secrets/kubernetes.io/serviceaccount/token | cut -d. -f2 | base64 -d 2>/dev/null | jq .aud
```

**Ожидаемый результат:**
```text
# Токен смонтирован:
total 0
drwxrwxrwt 3 root root  100 Jan  1 00:00 .
drwxr-xr-x 1 root root 4096 Jan  1 00:00 ..
-rw-r--r-- 1 root root  695 Jan  1 00:00 token

# Token трейлер:
eyJhbGciOiJSUzI1NiIsImtpZCI6Ij...

# Audience (должен совпадать с API-сервером):
["https://kubernetes.default.svc.cluster.local"]
```

### Сценарий 3: Ошибки Structured Authentication и CEL (v1.30+)

Если используется `--authentication-config`, ошибки могут быть вызваны CEL-фильтрами.

**Пример конфигурации с ошибкой:**
```yaml
# Если email не совпадает с доменом, API-сервер вернет 401
claimMappings:
  username: { expression: "claims.email.split('@')[0]" }
  validationRules:
    - expression: "claims.email.endsWith('@company.com')"
      message: "Only company emails allowed"
```

**Диагностика:** Ищите в логах API-сервера записи с уровнем `-v=4` или выше:
`"Authentication failed" err="validation failed: Only company emails allowed"`

**Команды диагностики:**
```bash
# Просмотр текущей конфигурации аутентификации
kubectl get --raw /metrics | grep apiserver_authentication

# Проверка_OIDC discovery
kubectl get --raw /.well-known/openid-configuration | jq '.issuer_supported, .claims_supported'

# Просмотр ошибок аутентификации
kubectl get --raw /metrics | grep apiserver_authentication_failed_count
```

**Ожидаемый результат:**
```text
# Метрики аутентификации:
apiserver_authentication_failed_count{issuer="https://accounts.google.com"} 5.0

# OIDC discovery:
true
["email","groups","sub"]
```

### Сценарий 4: Истечение X509 сертификатов

**Симптомы:** Ошибка `x509: certificate has expired` или `x509: certificate signed by unknown authority`.

**Полная диагностика:**
```bash
# Проверка срока действия сертификата в kubeconfig
kubectl config view --raw -o jsonpath='{.users[0].user.client-certificate-data}' | base64 -d | openssl x509 -noout -dates

# Просмотр SAN (Subject Alternative Name) сертификата
kubectl config view --raw -o jsonpath='{.users[0].user.client-certificate-data}' | base64 -d | openssl x509 -noout -text | grep -A1 "Subject Alternative Name"

# Проверка сертификата API-сервера
kubectl get --raw /version | jq .serverClient

# Проверка CA-сертификата
kubectl config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d | openssl x509 -noout -dates

# Проверка цепочки доверия
kubectl config view --raw -o jsonpath='{.users[0].user.client-certificate-data}' | base64 -d | openssl x509 -noout -issuer -subject
```

**Решение для администратора:**
```bash
# Проверка всех сертификатов (kubeadm)
kubeadm certs check-expiration

# Обновление и перезагрузка компонентов
kubeadm certs renew all
systemctl restart kubelet

# Проверка нового сертификата
kubectl get --raw /healthz
```

**Ожидаемый результат:**
```text
# Сертификат валиден:
notBefore: Jan  1 00:00:00 2024 GMT
notAfter : Jan  1 00:00:00 2025 GMT

# SAN сертификата:
X509v3 Subject Alternative Name:
    DNS:kubernetes
    DNS:kubernetes.default
    DNS:kubernetes.default.svc
    IP Address:10.96.0.1
```

### Сценарий 5: Диагностика ServiceAccount токенов

ServiceAccount — наиболее частый источник ошибок 401 в автоматизации и CI/CD.

```bash
# Проверка automountServiceAccountToken
kubectl get sa <sa-name> -n <ns> -o jsonpath='{.automountServiceAccountToken}'

# Просмотр секретов SA (legacy)
kubectl get sa <sa-name> -n <ns> -o jsonpath='{.secrets[*].name}'

# Проверка, используется ли SA в подах
kubectl get pods -n <ns> -o json | jq '.items[] | select(.spec.serviceAccountName == "<sa-name>") | .metadata.name'

# Просмотр всех SA с включенным automount
kubectl get sa -n <ns> -o json | jq '.items[] | select(.automountServiceAccountToken != false) | .metadata.name'

# Проверка прав SA через имперсонацию
kubectl auth can-i --list --as=system:serviceaccount:<ns>:<sa-name> -n <ns>

# Создание токена для теста
kubectl create token <sa-name> -n <ns> --duration=5m
```

**Ожидаемый результат:**
```text
# SA с automount=true (опасно):
default
build-robot

# SA с automount=false (безопасно):
app-sa
monitoring-sa

# Права SA:
Resources   Non-Resource URLs   Verbs
secrets     []                  [get list]
pods        []                  [get list watch]
```

### Сценарий 6: ДиагностикаOIDC аутентификации

```bash
# Просмотр OIDC discovery endpoint
kubectl get --raw /.well-known/openid-configuration | jq '{issuer, authorization_endpoint, token_endpoint, jwks_uri}'

# Просмотр JWKS (JSON Web Key Set)
kubectl get --raw /openid/v1/jwks | jq '.keys[0] | {kty, kid, alg}'

# Просмотр текущего пользователя в kubeconfig
kubectl config view --minify -o jsonpath='{.users[*].user}'

# Проверка OIDC токена
kubectl config view --minify -o jsonpath='{.users[*].user.auth-provider.config.id-token}' | cut -d. -f2 | base64 -d 2>/dev/null | jq .

# ПросмотрOIDC groups
kubectl auth can-i --list --as=<oidc-user> --as-group=<oidc-group>
```

**Ожидаемый результат:**
```text
# OIDC discovery:
{
  "issuer": "https://accounts.google.com",
  "authorization_endpoint": "https://accounts.google.com/o/oauth2/auth",
  "token_endpoint": "https://oauth2.googleapis.com/token",
  "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs"
}

# JWKS:
{
  "kty": "RSA",
  "kid": "abc123...",
  "alg": "RS256"
}
```

### Сценарий 7: ДиагностикаWebhook аутентификации

```bash
# Просмотр конфигурации webhook
kubectl get --raw /metrics | grep apiserver_webhook

# Проверка доступности webhook сервиса
kubectl get endpoints -n <webhook-ns> <webhook-svc>

# Просмотр ошибок webhook
kubectl get --raw /metrics | grep apiserver_webhook_failures

# Тестирование webhook напрямую
curl -X POST https://<webhook-svc>:<port>/authenticate \
  -H "Content-Type: application/json" \
  -d '{"apiVersion":"authentication.k8s.io/v1","kind":"TokenReview","spec":{"token":"<test-token>"}}'
```

**Ожидаемый результат:**
```text
# Webhook доступен:
NAME         ENDPOINTS                     AGE
auth-webhook 10.0.1.10:443                 5d

# Ошибки webhook отсутствуют:
apiserver_webhook_failures{webhook="auth-webhook"} 0.0
```

### Сценарий 8: Проверка Clock Skew

Разница во времени между клиентом и API-сервером > 300 секунд вызывает 401 для JWT-токенов.

```bash
# Проверка времени на клиенте
date -u
timedatectl

# Проверка времени API-сервера (через kubectl)
kubectl get --raw /version | jq .gitVersion

# Сравнение времени
echo "Клиент: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Сервер: $(kubectl get --raw /version | jq -r .gitCommit)"

# Проверка NTP синхронизации
ntpstat
chronyc tracking

# Просмотр времени на узлах
kubectl get nodes -o custom-columns=NAME:.metadata.name,TIME:.status.conditions[-1].lastTransitionTime
```

**Ожидаемый результат:**
```text
# Время синхронизировано:
synchronised to NTP server (169.254.169.123) at stratum 3

# Clock skew в пределах нормы:
Разница: 2.3 секунды (норма < 300 секунд)
```

## Дополнительная информация

### Имитация (Impersonation) для отладки

Имитация помогает понять, является ли проблема ошибкой **аутентификации** (личность не установлена) или **авторизации** (нет прав). Если имитация через админа работает, а прямой запрос — нет, значит проблема в учетных данных.

```bash
# Проверка от имени пользователя и группы
kubectl get pods --as=user@example.com --as-group=developers

# Проверка от имени ServiceAccount
kubectl get pods --as=system:serviceaccount:default:my-sa

# Просмотр всех разрешений имитируемого субъекта
kubectl auth can-i --list --as=user@example.com --as-group=developers

# Проверка имперсонации
kubectl auth can-i impersonate users --as=system:masters
```

### Анонимные запросы: 401 vs 403

-   Если `--anonymous-auth=false` → любой запрос без учетных данных получает **401 Unauthorized**.
-   Если `--anonymous-auth=true` (по умолчанию) → запрос получает личность `system:anonymous`. Если у этой группы нет прав (а их обычно нет), вернется **403 Forbidden**.

**Диагностика анонимного доступа:**
```bash
# Проверка настроек анонимного доступа
kubectl get --raw /metrics | grep apiserver_anonymous_auth

# Просмотр анонимных запросов в метриках
kubectl get --raw /metrics | grep 'username="system:anonymous"'

# Отключение анонимного доступа (API-сервер)
# --anonymous-auth=false
```

### Команды быстрой диагностики

```bash
# Просмотр текущего пользователя
kubectl config view --minify -o jsonpath='{.users[*].name}'

# Просмотр текущего контекста
kubectl config view --minify -o jsonpath='{.current-context}'

# Проверка подключения к API
kubectl cluster-info

# Просмотр версии API
kubectl version --short

# Проверка всех аутентификаторов
kubectl get --raw /metrics | grep apiserver_authentication

# Просмотр ошибок аутентификации
kubectl get --raw /metrics | grep apiserver_authentication_failed
```

### Распространенные ошибки аутентификации

| Ошибка | Симптомы | Причина | Решение |
|--------|----------|---------|---------|
| `x509: certificate has expired` | Все запросы возвращают 401 | Просроченный клиентский сертификат | `kubeadm certs renew all` |
| `x509: certificate signed by unknown authority` | Запросы отклоняются | Неверный CA-сертификат в kubeconfig | Обновить `certificate-authority-data` |
| `token is expired` | Приложение получает 401 | Истек TTL JWT-токена | Перезапустить под или `kubectl create token` |
| `audience mismatch` | Токен отклонен API-сервером | Неверный audience в токене | Проверить `--api-audience` флаг |
| `clock skew` | Периодические 401 | Разница во времени > 300 сек | Настроить NTP: `ntpdate time.google.com` |
| `webhook connection refused` | 401 при использовании webhook | Webhook сервис недоступен | Проверить Endpoints webhook сервиса |
| `impersonate denied` | 403 при имперсонации | Нет прав RBAC на impersonate | Добавить ClusterRole с verb=impersonate |

### Сценарий 9: Истечение SA токена и сбой ротации в production

**Контекст:** Приложение внутри пода использует ServiceAccount токен для обращения к API-серверу или внешнему сервису. В Kubernetes 1.24+ токены по умолчанию являются Bound Tokens (TTL 1 час) и автоматически ротируются kubelet.

**Симптомы:** Приложение периодически (примерно раз в час) получает 401 Unauthorized, после чего ошибки прекращаются. Или — ошибки не прекращаются (сбой ротации).

**Причины сбоя ротации:**
1. **Kubelet не может обновить токен** — проблемы с API-сервером, диском на ноде или нехваткой ресурсов
2. **Projected volume заполнен** — механизм проецированных томов не может записать новый токен
3. **Clock skew** — время на ноде рассинхронизировано, токен считается невалидным
4. **Token Cleaner (v1.31+)** — контроллер удалил legacy-токен, а новый не был создан

**Диагностика:**
```bash
# Шаг 1: Проверить, что токен смонтирован и валиден
kubectl exec <pod-name> -- cat /var/run/secrets/kubernetes.io/serviceaccount/token | cut -d. -f2 | base64 -d 2>/dev/null | jq '{exp: (.exp | todate), aud: .aud, sub: .sub}'

# Шаг 2: Проверить, обновляет ли kubelet токен (посмотреть年龄 файла)
kubectl exec <pod-name> -- ls -la /var/run/secrets/kubernetes.io/serviceaccount/token

# Шаг 3: Проверить, есть ли ошибки в projected volume
kubectl describe pod <pod-name> | grep -A5 "Conditions\|Events" | grep -i "error\|warn\|fail"

# Шаг 4: Проверить время на ноде (clock skew)
kubectl exec <pod-name> -- date -u +%Y-%m-%dT%H:%M:%SZ
kubectl get node <node-name> -o jsonpath='{.status.conditions[-1].lastTransitionTime}'

# Шаг 5: Для принудительной ротации — пересоздать под
kubectl delete pod <pod-name> -n <ns>
```

**Профилактика:**
```bash
# Включить автоматическую ротацию (по умолчанию в K8s 1.24+)
# В манифесте пода:
spec:
  automountServiceAccountToken: false  # Отключить стандартный токен
  serviceAccountName: app-sa
  containers:
  - name: app
    volumeMounts:
    - name: bound-token
      mountPath: /var/run/secrets/tokens
  volumes:
  - name: bound-token
    projected:
      sources:
      - serviceAccountToken:
          audience: api-server
          expirationSeconds: 3600  # 1 час
          path: bound-token

# Настроить алерт на приближение истечения токена
# Prometheus:(token_expires_in_seconds < 600)
```

> Подробнее о Bound Tokens и ротации: [../../../Security/authentication.md](../../../Security/authentication.md)
> Очистка legacy-токенов (v1.31+): [../../../Base/secrets/creating_secrets.md](../../../Base/secrets/creating_secrets.md)

### Связанные ресурсы

- [Алгоритм пошаговой диагностики (401 и 403)](diagnostics.md)
- [Определения 401 vs 403](definitions.md)
- [Субъекты доступа (ServiceAccount, Users, Groups)](../../../Security/rbac/subjects.md)
- [Kubeconfig и управление подключениями](../../../Operations/kubeconfig_and_connection.md) — ошибки контекста, KUBECONFIG, OIDC
- [Описание методов аутентификации](../../../Security/authentication.md)
- [Лучшие практики](best_practices.md) — Bound Tokens, ротация CA, мониторинг
- [Официальная документация: Authenticating](https://kubernetes.io/docs/reference/access-authn/authentication/)
