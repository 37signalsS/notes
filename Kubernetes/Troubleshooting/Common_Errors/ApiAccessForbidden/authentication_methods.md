# Ошибки аутентификации: методы и код 401 Unauthorized

## Определения

**401 Unauthorized** — код состояния HTTP, означающий, что API-сервер Kubernetes не смог подтвердить личность (аутентифицировать) субъекта. Это первичный барьер безопасности: если личность не установлена, проверка прав (**RBAC**) не производится, и запрос отклоняется немедленно.

**Аутентификатор (Authenticator)** — модуль API-сервера, ответственный за проверку конкретного типа учетных данных (токены, сертификаты, пароли).

**TokenReview API** — механизм, позволяющий проверить валидность токена и получить информацию о субъекте (имя, группы) напрямую от API-сервера.

> Различие 401 vs 403: [definitions.md](definitions.md)
> Полное описание механизмов: [../../../Security/authentication.md](../../../Security/authentication.md)

## Основные концепции

### Цепочка проверки запроса

Kubernetes использует список аутентификаторов, которые проверяются последовательно до первого успешного совпадения.

1.  **X509:** Клиентские сертификаты (админы, компоненты кластера).
2.  **ServiceAccount:** JWT токены (поды, автоматизация).
3.  **OIDC:** Внешние провайдеры (Okta, Keycloak, Google).
4.  **Webhook:** Кастомная проверка через внешний сервис.
5.  **Anonymous:** Если включено (`--anonymous-auth=true`), запросу назначается `system:anonymous`.

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

### Сценарий 4: Истечение X509 сертификатов

**Симптомы:** Ошибка `x509: certificate has expired`.

**Решение для администратора:**
```bash
# Проверка всех сертификатов (kubeadm)
kubeadm certs check-expiration

# Обновление и перезагрузка компонентов
kubeadm certs renew all
systemctl restart kubelet
```

## Дополнительная информация

### Имитация (Impersonation) для отладки

Имитация помогает понять, является ли проблема ошибкой **аутентификации** (личность не установлена) или **авторизации** (нет прав). Если имитация через админа работает, а прямой запрос — нет, значит проблема в учетных данных.

```bash
# Проверка от имени пользователя и группы
kubectl get pods --as=user@example.com --as-group=developers
```

### Анонимные запросы: 401 vs 403

-   Если `--anonymous-auth=false` → любой запрос без учетных данных получает **401 Unauthorized**.
-   Если `--anonymous-auth=true` (по умолчанию) → запрос получает личность `system:anonymous`. Если у этой группы нет прав (а их обычно нет), вернется **403 Forbidden**.

### Связанные ресурсы

- [Алгоритм пошаговой диагностики (401 и 403)](diagnostics.md)
- [Определения 401 vs 403](definitions.md)
- [Kubeconfig и управление подключениями](../../../Operations/kubeconfig_and_connection.md)
- [Официальная документация: Authenticating](https://kubernetes.io/docs/reference/access-authn/authentication/)
