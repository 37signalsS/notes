# Аутентификация в Kubernetes

## Определения

**Аутентификация (Authentication, AuthN)** в Kubernetes — это процесс проверки личности пользователя или компонента, отправляющего запрос к API-серверу. Каждому запросу, приходящему в кластер, должна быть сопоставлена учетная запись (человек-пользователь или `ServiceAccount`), либо он помечается как анонимный.

* **API-сервер как шлюз:** Аутентификация является первым этапом обработки запроса. Если личность не подтверждена, запрос отклоняется с кодом **401 Unauthorized** до этапа проверки прав (авторизации).
* **Пользователи (Users) vs Сервисные аккаунты (ServiceAccounts):**
    * **Пользователи:** Реальные люди или внешние системы. Kubernetes не хранит объекты «пользователь» в etcd, полагаясь на внешние механизмы (сертификаты, OIDC).
    * **ServiceAccounts:** Внутренние объекты кластера для процессов в подах.
* **Impersonation (Самозванство):** Возможность аутентифицированного пользователя выполнять действия от имени другого субъекта.

**Важно:** Подробное сравнение проверки личности и проверки прав доступно в материале [Authentication vs Authorization](../../Security/Concepts/authentication_vs_authorization.md).

## Основные концепции

### 1. Цепочка аутентификаторов (Authentication Chain)

API-сервер проверяет запрос списком настроенных методов.
* **Приоритет:** Проверка идет до первого успешного совпадения. Если метод не опознал запрос, он передает его следующему в цепочке.
* **Анонимный доступ:** Если ни один метод не сработал и включен флаг `--anonymous-auth=true`, запросу назначается пользователь `system:anonymous` и группа `system:unauthenticated`.

### 2. X.509 Клиентские сертификаты

Используются компонентами кластера (Kubelet, Scheduler) и администраторами.
* **Маппинг атрибутов:**
    * `Common Name (CN)` → Имя пользователя.
    * `Organization (O)` → Имя группы (несколько `O` = несколько групп).
* **Особенности:** Нет механизма отзыва (CRL/OCSP). Единственный способ аннулировать доступ — дождаться истечения срока действия или перевыпустить Root CA.
* **Ротация:** Kubelet поддерживает автоматическую ротацию своих сертификатов через флаг `--rotate-certificates`.

### 3. Привязанные токены (Bound Service Account Tokens)

Современный стандарт (GA с v1.22, улучшения в v1.31+).
* **TokenRequest API:** Динамическая генерация кратковременных токенов вместо статических Secret-объектов.
* **Projected Volumes:** Токены монтируются в поды и автоматически ротируются Kubelet до истечения TTL.
* **Механизмы привязки (Binding):**
    * **Time-bound:** Ограниченный TTL (по умолчанию 1 час).
    * **Audience-bound:** Предназначены для конкретного потребителя (например, Vault).
    * **Object-bound:** Привязаны к жизненному циклу пода (токен аннулируется при удалении пода).
    * **Node-bound (Beta v1.31):** Токен привязан к конкретному узлу. Если злоумышленник украдет токен с узла А, он не сможет использовать его на узле Б.

### 4. Структурированная конфигурация и OIDC (v1.30+)

Рекомендуется использовать флаг `--authentication-config` вместо старых флагов `--oidc-*`.
* **Multiple OIDC Providers:** Поддержка неограниченного количества OIDC-провайдеров одновременно (например, Okta + GitHub).
* **CEL Expressions:** Использование Common Expression Language для динамического маппинга данных из токена. Пример: `claims.email.split('@')[0]` для username.
* **Hot-Reload:** API-сервер подхватывает изменения в конфигурационном файле без перезагрузки процесса.

### 5. Вебхук-аутентификация и TokenReview API

API-сервер делегирует проверку токена внешнему сервису.
* **Механизм:** API-сервер отправляет POST-запрос с объектом `TokenReview` (содержащим токен) на URL вебхука.
* **TokenReview API:** Стандартный ресурс Kubernetes, который используется для обмена информацией между API-сервером и валидатором. В ответ вебхук возвращает статус (аутентифицирован или нет) и данные пользователя (UID, группы).
* **Применение:** Интеграция с прокси-системами аутентификации (например, [Pinniped](./pinniped.md)) для поддержки LDAP/AD.

### 6. Impersonation (Выполнение от имени)

Позволяет пользователю (например, администратору) проверять поведение RBAC от лица другого пользователя.
* Реализуется через HTTP-заголовки `Impersonate-User`, `Impersonate-Group`, `Impersonate-Extra-`.
* Требует специальных прав RBAC (`verb: impersonate` на ресурсы `users`, `groups`, `serviceaccounts`).

### 7. Bootstrap Tokens и Статические токены

* **Bootstrap Tokens:** Используются `kubeadm` для временной аутентификации новых узлов. Хранятся как `Secrets` в `kube-system`.
* **Static Token File:** Список токенов в CSV-файле. **Не рекомендуется** (небезопасно, требует перезагрузки для изменений).

## Практические сценарии

### 1. Подготовка сертификата администратора (CSR)

```bash
# 1. Генерация ключа и запроса
openssl genrsa -out developer.key 2048
openssl req -new -key developer.key -out developer.csr -subj "/CN=developer/O=dev-group"

# 2. Создание объекта CertificateSigningRequest в K8s
cat <<EOF | kubectl apply -f -
apiVersion: certificates.k8s.io/v1
kind: CertificateSigningRequest
metadata:
  name: developer-access
spec:
  request: $(cat developer.csr | base64 | tr -d '\n')
  signerName: kubernetes.io/kube-apiserver-client
  usages:
  - client auth
EOF

# 3. Одобрение и получение сертификата
kubectl certificate approve developer-access
kubectl get csr developer-access -o jsonpath='{.status.certificate}' | base64 -d > developer.crt
```

### 2. Кастомизация ServiceAccount токена в поде (Projected Volume)

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: security-app
spec:
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - mountPath: /var/run/secrets/tokens
      name: vault-token
  volumes:
  - name: vault-token
    projected:
      sources:
      - serviceAccountToken:
          path: vault-token
          expirationSeconds: 7200
          audience: vault-service
```

### 3. Пример структурированной конфигурации (AuthenticationConfiguration)

```yaml
apiVersion: apiserver.config.k8s.io/v1beta1
kind: AuthenticationConfiguration
jwt:
- issuer:
    url: https://accounts.google.com
    audiences: ["k8s-client-id-google"]
  claimMappings:
    username: { expression: 'claims.email' }
    groups: { expression: 'claims.groups' }
- issuer:
    url: https://login.microsoftonline.com/tenant-id/v2.0
    audiences: ["k8s-client-id-azure"]
  claimMappings:
    username: { expression: 'claims.preferred_username' }
```

### 4. Использование Impersonation в CLI

```bash
# Проверка: может ли пользователь 'dev-user' получить список подов в неймспейсе 'test'
kubectl get pods -n test --as=dev-user --as-group=developers
```

## Дополнительная информация

### Сравнение методов аутентификации

| Метод | Субъект | Безопасность | Основная особенность |
|:------|:--------|:-------------|:---------------------|
| **X.509** | Компоненты, Админы | Высокая | Нет отзыва без смены CA |
| **Bound Tokens** | Приложения (SA) | Высокая | Авто-ротация, Node-binding (v1.31+) |
| **OIDC (v1.30+)** | Пользователи (SSO) | Высокая | Поддержка многих IdP, Hot-Reload |
| **Webhook** | Кастомные системы | Средняя | Работает через `TokenReview API` |
| **Bootstrap** | Новые узлы | Средняя | Только для `kubeadm join` |
| **Static Tokens** | Тестирование | Низкая | **Deprecated**, небезопасно |

### Рекомендации по безопасности

* **Отключение анонимного доступа:** Используйте `--anonymous-auth=false` в production.
* **Отказ от Secret-based токенов:** Заменяйте старые токены на `TokenRequest`.
* **Аудит токенов:** Проверяйте использование Node-bound токенов для минимизации радиуса поражения при компрометации узла.

**Связанные темы:**

* [TLS и mTLS в Kubernetes](./tls_and_mtls_in_kubernetes.md) — детали шифрования.
* [Pinniped: Интеграция с IdP](./pinniped.md) — федерация OIDC/LDAP.
* [RBAC в Kubernetes](./rbac/rbac_overview.md) — контроль прав доступа.
* [Диагностика 401 Unauthorized](../Troubleshooting/Common_Errors/ApiAccessForbidden/authentication_methods.md) — поиск причин отказа.
