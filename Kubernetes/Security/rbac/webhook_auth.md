# Webhook Token Authentication

## Определения

**Webhook Token Authentication** — метод аутентификации в Kubernetes, при котором API-сервер делегирует проверку токенов внешнему HTTP-сервису. При получении запроса с токеном API-сервер отправляет POST-запрос с объектом `TokenReview` на настроенный URL вебхука. Вебхук проверяет токен и возвращает статус аутентификации.

**TokenReview** — стандартный ресурс Kubernetes API (`authentication.k8s.io/v1`), используемый для обмена данными между API-сервером и внешним валидатором. Содержит токен, который необходимо проверить.

**Применение:** Интеграция с корпоративными системами аутентификации (LDAP, Active Directory, кастомные базы данных), которые не поддерживают стандартные протоколы (OIDC, SAML).

---

## Основные концепции

### Механизм работы

```text
КЛИЕНТ → запрос с Bearer-токеном → KUBE-APISERVER
                                        ↓
                              Отправка TokenReview на WEBHOOK_URL
                                        ↓
                              WEBHOOK проверяет токен
                                        ↓
                              Ответ: {status: {authenticated: true, user: {...}}}
                                        ↓
                              KUBE-APISERVER → RBAC проверяет права → Ответ клиенту
```

**Флаги API-сервера:**

| Флаг | Назначение |
|------|-----------|
| `--authentication-token-webhook-config-file` | Путь к kubeconfig-файлу с конфигурацией вебхука |
| `--authentication-token-webhook-cache-ttl` | Время кэширования результатов (по умолчанию 2 минуты) |

### Формат запроса TokenReview

API-сервер отправляет POST-запрос:

```json
{
  "apiVersion": "authentication.k8s.io/v1",
  "kind": "TokenReview",
  "spec": {
    "token": "eyJhbGciOiJSUzI1NiIs..."
  }
}
```

### Формат ответа вебхука

Вебхук должен вернуть HTTP 200 с телом:

```json
{
  "apiVersion": "authentication.k8s.io/v1",
  "kind": "TokenReview",
  "status": {
    "authenticated": true,
    "user": {
      "username": "alice@example.com",
      "uid": "12345678-1234-1234-1234-123456789abc",
      "groups": ["developers", "platform"],
      "extra": {
        "email": ["alice@example.com"],
        "tenant": ["team-a"]
      }
    },
    "audiences": ["https://kubernetes.default.svc"]
  }
}
```

Если токен недействителен:

```json
{
  "apiVersion": "authentication.k8s.io/v1",
  "kind": "TokenReview",
  "status": {
    "authenticated": false
  }
}
```

### Конфигурация kubeconfig для вебхука

Файл конфигурации (отличается от стандартного kubeconfig):

```yaml
# webhook-token-auth-config.yaml
apiVersion: v1
kind: Config
clusters:
- name: webhook-auth
  cluster:
    certificate-authority: /etc/kubernetes/pki/ca.crt  # CA для проверки сертификата вебхука
    server: https://auth-webhook.example.com/authenticate  # URL вебхука
users:
- name: webhook-auth
  user:
    client-certificate: /etc/kubernetes/pki/webhook-client.crt  # Сертификат для mTLS
    client-key: /etc/kubernetes/pki/webhook-client.key
current-context: webhook-auth
contexts:
- context:
    cluster: webhook-auth
    user: webhook-auth
  name: webhook-auth
```

**Важно:** Вебхук общается с API-сервером по HTTPS. API-сервер предъявляет клиентский сертификат (mTLS), а вебхук предъявляет серверный сертификат.

### Кэширование результатов

API-сервер кэширует результаты проверки токенов (флаг `--authentication-token-webhook-cache-ttl`, по умолчанию 2 минуты). Это важно учитывать:

- **Ранний отзыв:** если токен был отозван, API-сервер продолжит считать его валидным до истечения TTL кэша.
- **Смена прав:** если права пользователя изменились в внешней системе, кэш вернёт старый результат.

---

## Практические сценарии

### Пример простого вебхука на Go

```go
package main

import (
    "encoding/json"
    "fmt"
    "log"
    "net/http"
    "strings"
    "sync"
)

type TokenReview struct {
    APIVersion string      `json:"apiVersion"`
    Kind       string      `json:"kind"`
    Spec       ReviewSpec  `json:"spec"`
    Status     ReviewStatus `json:"status,omitempty"`
}

type ReviewSpec struct {
    Token string `json:"token"`
}

type ReviewStatus struct {
    Authenticated bool       `json:"authenticated"`
    User          *UserInfo  `json:"user,omitempty"`
    Audiences     []string   `json:"audiences,omitempty"`
}

type UserInfo struct {
    Username string            `json:"username"`
    UID      string            `json:"uid"`
    Groups   []string          `json:"groups,omitempty"`
    Extra    map[string][]string `json:"extra,omitempty"`
}

// Простая in-memory база токенов (в production используйте Redis/БД)
var (
    tokenStore = map[string]UserInfo{
        "my-secret-token-123": {
            Username: "alice@example.com",
            UID:      "alice-uid-001",
            Groups:   []string{"developers", "platform"},
        },
        "ci-deploy-token-456": {
            Username: "ci-deployer",
            UID:      "ci-uid-002",
            Groups:   []string{"system:serviceaccounts:ci"},
        },
    }
    mu sync.RWMutex
)

func authenticateHandler(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodPost {
        http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
        return
    }

    var review TokenReview
    if err := json.NewDecoder(r.Body).Decode(&review); err != nil {
        http.Error(w, "Invalid request body", http.StatusBadRequest)
        return
    }

    mu.RLock()
    userInfo, exists := tokenStore[review.Spec.Token]
    mu.RUnlock()

    review.Status = ReviewStatus{
        Authenticated: exists,
    }
    if exists {
        review.Status.User = &userInfo
    }

    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(review)
}

func main() {
    http.HandleFunc("/authenticate", authenticateHandler)
    log.Println("Webhook auth server listening on :8443")
    log.Fatal(http.ListenAndServeTLS(":8443",
        "/etc/kubernetes/pki/webhook-server.crt",
        "/etc/kubernetes/pki/webhook-server.key",
        nil))
}
```

### Тестирование вебхука

```bash
# 1. Запуск вебхука (в отдельном поде или на хосте)
# Предполагается, что вебхук слушает на :8443

# 2. Ручная проверка через TokenReview
kubectl create --raw /apis/authentication.k8s.io/v1/tokenreviews \
  -f - <<EOF
apiVersion: authentication.k8s.io/v1
kind: TokenReview
spec:
  token: "my-secret-token-123"
EOF
# → {"apiVersion":"authentication.k8s.io/v1","kind":"TokenReview","status":{"authenticated":true,"user":{"username":"alice@example.com","uid":"alice-uid-001","groups":["developers","platform"]}}}

# 3. Проверка невалидного токена
kubectl create --raw /apis/authentication.k8s.io/v1/tokenreviews \
  -f - <<EOF
apiVersion: authentication.k8s.io/v1
kind: TokenReview
spec:
  token: "invalid-token"
EOF
# → {"apiVersion":"authentication.k8s.io/v1","kind":"TokenReview","status":{"authenticated":false}}
```

### Интеграция с Pinniped

[Pinniped](../pinniped.md) — CNCF-проект, предоставляющий единый слой аутентификации для Kubernetes кластеров. Поддерживает LDAP/AD через Webhook Token Authentication:

```bash
# Установка Pinniped (упрощённый пример)
helm repo add pinniped https://charts.pinniped.dev
helm install pinniped pinniped/pinniped \
  --namespace pinniped \
  --create-namespace \
  --set apiService.tls.certificateAuthorityData=$(cat /etc/kubernetes/pki/ca.crt | base64 -w0)

# Конфигурация Concierge (webhook authenticator)
kubectl apply -f - <<EOF
apiVersion: config.supervisor.pinniped.dev/v1alpha1
kind: WebhookIdentityProvider
metadata:
  name: corporate-ldap
  namespace: pinniped
spec:
  webhook:
    url: https://ldap-webhook.internal.corp/authenticate
    caBundle: $(cat /path/to/webhook-ca.crt | base64 -w0)
    header:
      x-token-header: "{{.token}}"
EOF
```

### Диагностика проблем

```bash
# 1. Проверка конфигурации вебхука в API-сервере
kubectl describe pod -n kube-system -l component=kube-apiserver | \
  grep authentication-token-webhook
# → --authentication-token-webhook-config-file=/etc/kubernetes/webhook-token-auth.yaml

# 2. Проверка логов API-сервера на ошибки вебхука
kubectl logs -n kube-system -l component=kube-apiserver | \
  grep -i "webhook.*auth\|token.*review"

# 3. Проверка доступности вебхука из API-сервера
kubectl exec -n kube-system kube-apiserver-<node> -c kube-apiserver -- \
  curl -sk https://auth-webhook.example.com/authenticate

# 4. Тестирование конкретного токена
kubectl create --raw /apis/authentication.k8s.io/v1/tokenreviews \
  -f - <<EOF
apiVersion: authentication.k8s.io/v1
kind: TokenReview
spec:
  token: "$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)"
EOF

# 5. Проверка, какой метод аутентификации использовался
kubectl get --raw /api/v1/namespaces/default | jq '.metadata'
# Или через аудит:
kubectl get --raw /apis/audit.k8s.io/v1/events | \
  jq '.items[] | select(.stage == "ResponseComplete") | {
    user: .user.username,
    verb: .verb,
    annotations: .annotations
  }'
```

### Типовые ошибки

| Симптом | Причина | Решение |
|---------|---------|---------|
| `unable to authenticate the request` | Вебхук недоступен | Проверьте URL, сеть, сертификаты |
| `token review failed` | Вебхук вернул не 200 | Проверьте логи вебхука, формат ответа |
| `certificate signed by unknown authority` | CA вебхука не доверяется API-серверу | Укажите `certificate-authority` в кластере |
| Токен «не работает» сразу после отзыва | Кэш (`cache-ttl`) | Подождите истечения TTL или уменьшите кэш |
| `no endpoints available for service` | Вебхук не имеет подов | Проверьте Service и readiness probe |

---

## Дополнительная информация

### Безопасность

- **mTLS обязателен:** Используйте клиентский сертификат для аутентификации API-сервера перед вебхуком. Это предотвращает MITM-атаки.
- **Защита токенов:** Bearer-токены передаются в открытом виде. Используйте HTTPS для всех соединений.
- **Кэш:** Уменьшайте `--authentication-token-webhook-cache-ttl` для критичных систем (например, 30 секунд вместо 2 минут).
- **Rate Limiting:** Вебхук должен иметь защиту от DoS (rate limiting, circuit breaker).

### Сравнение с другими методами

| Критерий | Webhook | OIDC | TLS Certs | SA Token |
|----------|---------|------|-----------|----------|
| **Гибкость** | Максимальная (кастомная логика) | Высокая (стандартный протокол) | Ограниченная | Низкая |
| **Производительность** | Зависит от вебхука | Зависит от провайдера | Высокая | Высокая |
| **Точка отказа** | Вебхук | OIDC-провайдер | Нет | Нет |
| **Сложность** | Высокая | Средняя | Средняя | Низкая |
| **LDAP/AD** | Да (кастомный маппинг) | Да (через Dex) | Нет | Нет |

### Связанные темы

- **[Аутентификация в Kubernetes](../authentication.md)** — обзор всех методов аутентификации
- **[Pinniped](../pinniped.md)** — готовое решение для Webhook + LDAP/AD
- **[Субъекты доступа](./subjects.md)** — как webhook-пользователи становятся субъектами RBAC
- **[Обзор RBAC](./rbac_overview.md)** — проверка прав после аутентификации
