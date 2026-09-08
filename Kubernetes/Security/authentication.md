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

**Архитектура обработки запроса:**

```
kubectl apply -f deploy.yaml
        │
        ▼
   API Server (HTTPS :6443)
        │
        ├── 1. Аутентификация (кто ты?)
        │   ├── X.509 Client Certificates
        │   ├── Bearer Token (ServiceAccount / Static)
        │   ├── OIDC (Structured Config v1.30+)
        │   ├── Webhook (TokenReview)
        │   ├── Authenticating Proxy (X-Remote-User)
        │   └── Anonymous (system:anonymous)
        │
        ├── 2. Авторизация (что тебе можно?)
        │   └── RBAC / ABAC / Webhook
        │
        ├── 3. Admission Control
        │   └── Mutating → Validating
        │
        └── 4. Сохранение в etcd
```

**Важно:** После успешной аутентификации API-сервер извлекает из учетных данных:
* Имя пользователя (`username`)
* UID
* Группы (`groups`)
* Дополнительные поля (`extra`)

Эти данные используются на этапе авторизации (RBAC) и аудита.

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

### 4. OIDC и структурированная конфигурация (v1.30+)

Рекомендуется использовать флаг `--authentication-config` вместо старых флагов `--oidc-*`.
* **Multiple OIDC Providers:** Поддержка неограниченного количества OIDC-провайдеров одновременно (например, Okta + GitHub).
* **CEL Expressions:** Использование Common Expression Language для динамического маппинга данных из токена. Пример: `claims.email.split('@')[0]` для username.
* **Hot-Reload:** API-сервер подхватывает изменения в конфигурационном файле без перезагрузки процесса.

### 5. Вебхук-аутентификация и TokenReview API

API-сервер делегирует проверку токена внешнему сервису.
* **Механизм:** API-сервер отправляет POST-запрос с объектом `TokenReview` (содержащим токен) на URL вебхука.
* **TokenReview API:** Стандартный ресурс Kubernetes, который используется для обмена информацией между API-сервером и валидатором. В ответ вебхук возвращает статус (аутентифицирован или нет) и данные пользователя (UID, группы).
* **Применение:** Интеграция с прокси-системами аутентификации (например, [Pinniped](./pinniped.md)) для поддержки LDAP/AD.

### 6. Аутентифицирующий прокси (Authenticating Proxy)

В корпоративных средах аутентификация часто делегируется обратному прокси (OAuth2 Proxy, Authelia, Envoy), который проверяет учетные данные пользователя и передает результат в API-сервер через заголовки.

* **Механизм:** Прокси устанавливает заголовки `X-Remote-User` и `X-Remote-Group`. API-сервер доверяет источнику (прокси) и назначает пользователю имя и группы.
* **Trusted Origins:** Администратор явно указывает доверенные CIDR или сертификаты прокси. Если злоумышленник из ненадежной сети отправит запрос с поддельными заголовками, они будут проигнорированы.
* **Применение:** Интеграция с корпоративными SSO без изменения конфигурации API-сервера.

Для деталей маппинга групп и субъектов см. [Субъекты RBAC](./rbac/subjects.md). Подробное руководство по настройке клиентских сертификатов см. в [Аутентификация через TLS-сертификаты](./rbac/certificate_auth.md). Конфигурация вебхука — в [Webhook Token Authentication](./rbac/webhook_auth.md).

### 7. Front-proxy аутентификация

Kubernetes поддерживает агрегированный API-сервер (Aggregated API), который позволяет расширять функциональность API через собственные эндпоинты. Для аутентификации запросов к агрегированному API используется отдельный CA (`front-proxy-ca`).

* **Механизм:** API-сервер проверяет клиентский сертификат, подписанный `front-proxy-ca`, и передает запрос агрегированному API.
* **Применение:** Встроенные расширения API (metrics, API groups от аддонов) используют этот механизм.

### 8. Basic Auth (устаревший)

Kubernetes поддерживает устаревший метод Basic Authentication (пара `username` + `password`), хранящийся в CSV-файле, указанном флагом `--basic-auth-file`.

* **Статус:** Deprecated. Отключен по умолчанию во многих современных дистрибутивах.
* **Ограничения:** Пароли передаются в открытом виде (Base64). Нет механизма отзыва. Требует перезагрузки API-сервера для изменений.
* **Рекомендация:** Используйте OIDC или сертификаты X.509.

### 9. Impersonation (Выполнение от имени)

Позволяет пользователю (например, администратору) проверять поведение RBAC от лица другого пользователя.
* Реализуется через HTTP-заголовки `Impersonate-User`, `Impersonate-Group`, `Impersonate-Extra-`.
* Требует специальных прав RBAC (`verb: impersonate` на ресурсы `users`, `groups`, `serviceaccounts`).

### 10. Bootstrap Tokens и Статические токены

* **Bootstrap Tokens:** Используются `kubeadm` для временной аутентификации новых узлов. Хранятся как `Secrets` в `kube-system`. Начиная с v1.31, Legacy ServiceAccount Token Cleaner автоматически удаляет неиспользуемые токены, хранящиеся в Secrets (если не использовались более 1 года).
* **Static Token File:** Список токенов в CSV-файле. **Не рекомендуется** (небезопасно, требует перезагрузки для изменений).

### 11. Аутентификация в client-go и встроенных клиентах

Клиентские библиотеки Kubernetes (`client-go`, `python-kubernetes`, `java`) поддерживают несколько встроенных провайдеров аутентификации:

* **In-Cluster:** Автоматическое обнаружение ServiceAccount токена в пути `/var/run/secrets/kubernetes.io/serviceaccount/`.
* **Exec Provider:** Вызов внешней команды (например, `kubelogin`, корпоративные скрипты) для получения токена.
* **Сторонние провайдеры:** Некоторые клиентские библиотеки имеют нативные провайдеры для специфических сред (не рекомендуются для новых развертываний без прямой интеграции).
* **OIDC:** Явное указание параметров OIDC в конфигурации.

**Пример на Go (client-go):**
```go
import (
    "context"
    "fmt"
    "k8s.io/client-go/tools/clientcmd"
)

func main() {
    config, err := clientcmd.BuildConfigFromFlags("", "")
    if err != nil {
        panic(err)
    }
    fmt.Printf("API Server: %s\n", config.Host)
}
```

**Пример на Python:**
```python
from kubernetes import client, config

config.load_kube_config()
v1 = client.CoreV1Api()
ret = v1.list_pod_for_all_namespaces(watch=False)
for pod in ret.items:
    print(f"{pod.metadata.namespace} / {pod.metadata.name}")
```

### 12. Безопасность аутентификации

* **Отключение анонимного доступа:** Используйте `--anonymous-auth=false` в production.
* **Отказ от Secret-based токенов:** Заменяйте старые токены на `TokenRequest`.
* **Аудит токенов:** Проверяйте использование Node-bound токенов для минимизации радиуса поражения при компрометации узла.
* **Ограничение impersonation:** Право `impersonate` на `system:masters` эквивалентно правам кластерного администратора.
* **Защита kubeconfig:** Файл `~/.kube/config` должен иметь права `600`. Для OIDC-плагинов используйте кэширование в системном keyring.
* **Ротация сертификатов:** Настройте автоматическую ротацию для всех клиентских сертификатов.
* **Верификация прокси:** Если используется аутентифицирующий прокси, убедитесь, что запросы могут поступать только из доверенных подсетей.

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
    url: https://login.example.com/tenant-id/v2.0
    audiences: ["k8s-client-id-example"]
  claimMappings:
    username: { expression: 'claims.preferred_username' }
    groups: { expression: 'claims.groups' }
```

### 4. Использование Impersonation в CLI

```bash
# Проверка: может ли пользователь 'dev-user' получить список подов в неймспейсе 'test'
kubectl get pods -n test --as=dev-user --as-group=developers
```

### 5. Настройка вебхук-аутентификации

Вебхук-аутентификация позволяет делегировать проверку токена внешнему сервису (например, корпоративному IdP).

```yaml
# 1. Конфигурация API-сервера (фрагмент)
apiVersion: apiserver.config.k8s.io/v1
kind: AuthenticationConfiguration
webhook:
  cacheTTL: 2m
  flushInterval: 5s
  kubeConfigFile: /etc/kubernetes/webhook-authn.yaml
```

```yaml
# 2. webhook-authn.yaml (kubeconfig-подобный формат)
apiVersion: v1
kind: Config
clusters:
- name: authn-webhook
  cluster:
    server: https://authn.internal.example.com/authenticate
    certificate-authority: /etc/kubernetes/pki/ca.crt
users:
- name: api-server
  user:
    client-certificate: /etc/kubernetes/pki/apiserver-client.crt
    client-key: /etc/kubernetes/pki/apiserver-client.key
current-context: authn-webhook
contexts:
- context:
    cluster: authn-webhook
    user: api-server
  name: authn-webhook
```

**Валидация:**
```bash
# Проверка, что webhook работает
kubectl auth can-i list pods --as=user-from-webhook
```

### 6. Создание и использование Bootstrap Tokens

Bootstrap Tokens используются для временной аутентификации новых узлов при операции `kubeadm join`.

```bash
# 1. Создание bootstrap token (v1.31+)
kubeadm token create --print-join-command

# 2. Токен хранится как Secret в kube-system
kubectl get secret -n kube-system | grep bootstrap

# 3. Проверка TTL
kubectl describe secret <bootstrap-token-name> -n kube-system
```

**Удаление токена после использования:**
```bash
kubectl delete secret <bootstrap-token-name> -n kube-system
```

### 7. Генерация kubeconfig для ServiceAccount (CI/CD)

Для программированного доступа к кластеру используйте ServiceAccount с ограниченными правами.

```bash
# 1. Создание SA
kubectl create serviceaccount ci-deployer -n production

# 2. Создание токена (bound token)
kubectl create token ci-deployer -n production --duration=720h

# 3. Получение CA и URL
SERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
CA=$(kubectl get secret -n production -o jsonpath='{.data.ca\.crt}')

# 4. Формирование kubeconfig
cat <<EOF > ci-kubeconfig.yaml
apiVersion: v1
kind: Config
clusters:
- name: default-cluster
  cluster:
    certificate-authority-data: ${CA}
    server: ${SERVER}
contexts:
- name: default-context
  context:
    cluster: default-cluster
    namespace: production
    user: default-user
current-context: default-context
users:
- name: default-user
  user:
    token: <TOKEN>
EOF
```

Подробнее о создании постоянных токенов и RBAC: [ServiceAccounts и безопасность](../Base/secrets/security.md).

### 8. Настройка exec-плагина (kubelogin) для OIDC

Для аутентификации пользователей через корпоративный IdP используйте exec-плагин в kubeconfig.

```yaml
# ~/.kube/config (фрагмент)
users:
- name: oidc-user
  user:
    exec:
      apiVersion: client.authentication.k8s.io/v1
      command: kubectl
      args:
      - oidc-login
      - get-token
      - --oidc-issuer-url=https://idp.internal.example.com/
      - --oidc-client-id=kubernetes-cli
      - --oidc-extra-scope=profile,email,groups
      - --token-cache-storage=keyring
      interactiveMode: IfAvailable
```

Полное руководство по настройке kubeconfig и exec-плагинов: [Kubeconfig: Подключение к кластеру](../Operations/kubeconfig_and_connection.md).

### 9. Мониторинг и аудит событий аутентификации

Аудит событий аутентификации критичен для обнаружения аномалий.

```yaml
# /etc/kubernetes/audit-policy.yaml (фрагмент)
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
- level: Metadata
  resources:
  - group: ""
    resources: ["serviceaccounts", "secrets"]
  omitStages:
  - "RequestReceived"
```

```bash
# Поиск неудачных аутентификаций в логах
kubectl logs -n kube-system -l component=kube-apiserver | \
  jq 'select(.user.username == "system:anonymous" or .responseStatus.code == 401)'

# Проверка работы TokenReview API
kubectl create token default --duration=60s
```

Подробнее об аудите: [Аудит в Kubernetes](./audit.md).

### 10. Миграция со статических токенов на Bound Tokens

Начиная с Kubernetes 1.24, автоматическая генерация долгоживущих токенов в Secrets отключена.

**Шаги миграции:**
1. Обновите приложения для использования projected volume tokens.
2. Убедитесь, что `automountServiceAccountToken` установлен корректно.
3. Удалите старые Secret-токены (`kubectl delete secret <old-token>`).
4. Настройте TTL и audience в projected volume согласно требованиям приложения.

## Дополнительная информация

### Сравнение методов аутентификации

| Метод | Субъект | Безопасность | Основная особенность |
|:------|:--------|:-------------|:---------------------|
| **X.509** | Компоненты, Админы | Высокая | Нет отзыва без смены CA |
| **Bound Tokens** | Приложения (SA) | Высокая | Авто-ротация, Node-binding (v1.31+) |
| **OIDC (v1.30+)** | Пользователи (SSO) | Высокая | Поддержка многих IdP, Hot-Reload |
| **Webhook** | Кастомные системы | Средняя | Работает через `TokenReview API` |
| **Authenticating Proxy** | Корпоративные пользователи | Средняя/Высокая | Зависит от доверия к прокси |
| **Front-proxy** | Aggregated API | Высокая | Отдельный CA для расширений API |
| **Bootstrap** | Новые узлы | Средняя | Только для `kubeadm join` |
| **Basic Auth** | Тестирование | Низкая | **Deprecated**, Base64 без шифрования |
| **Static Tokens** | Тестирование | Низкая | **Deprecated**, небезопасно |

### Compliance-соответствие

Аутентификация в Kubernetes является ключевым контролем для удовлетворения требований регуляторов:
* **PCI DSS v4.0.1:** Требование 8.3 — уникальная идентификация пользователей, многофакторная аутентификация для администраторов. Требование 10.2 — логирование всех доступов к данным карт.
* **ISO/IEC 27001:2022:** Контроль A.9.2.1 — уникальная идентификация пользователей; A.9.4.2 — безопасный процесс управления доступом.
* **SOC 2:** Критерий CC6.1 — логическая доступность и безопасность; CC6.3 — ограничение доступа через ролевую модель.
* **DISA STIG:** STIG ID `Kubernetes V-242421` — отключение анонимного доступа; `V-242422` — использование сертификатов X.509 для компонентов.

Общие принципы комплаенса подробно описаны в разделе [Аудит и комплаенс: Обзор](../../Security/audit_and_compliance_overview.md).

### Рекомендации по безопасности

* **Отключение анонимного доступа:** Используйте `--anonymous-auth=false` в production.
* **Отказ от Secret-based токенов:** Заменяйте старые токены на `TokenRequest`.
* **Аудит токенов:** Проверяйте использование Node-bound токенов для минимизации радиуса поражения при компрометации узла.
* **Ограничение impersonation:** Право `impersonate` на `system:masters` эквивалентно правам кластерного администратора.
* **Защита kubeconfig:** Файл `~/.kube/config` должен иметь права `600`. Для OIDC-плагинов используйте кэширование в системном keyring.
* **Ротация сертификатов:** Настройте автоматическую ротацию для всех клиентских сертификатов.
* **Верификация прокси:** Если используется аутентифицирующий прокси, убедитесь, что запросы могут поступать только из доверенных подсетей.

### Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **401 Unauthorized** | Просроченный токен, неверный сертификат, несовпадение audience | Проверить срок действия: `kubectl create token` / `openssl x509 -noout -dates` |
| **x509: certificate has expired** | Истек сертификат в kubeconfig или на компоненте | Обновить через `kubeadm certs renew` или перевыпустить CSR |
| **TokenReview failure** | Вебхук недоступен или неверный сертификат | Проверить доступность вебхука: `curl -k https://webhook/authenticate` |
| **Impersonation forbidden** | Нет права RBAC `impersonate` на целевого субъекта | Проверить: `kubectl auth can-i impersonate users --as=admin` |
| **Clock skew** | Расхождение времени > 5 минут | Настроить NTP/chrony на всех узлах |
| **Anonymous requests** | `--anonymous-auth=true` и нет прав у `system:unauthenticated` | Отключить анонимный доступ или назначить минимальные права |

### Связанные темы

* [TLS и mTLS в Kubernetes](./tls_and_mtls_in_kubernetes.md) — детали шифрования.
* [Pinniped: Интеграция с IdP](./pinniped.md) — федерация OIDC/LDAP.
* [RBAC в Kubernetes](./rbac/rbac_overview.md) — контроль прав доступа.
* [Kubeconfig и подключение](../Operations/kubeconfig_and_connection.md) — структура конфигурационных файлов.
* [Управление сертификатами через kubeadm](../Operations/certificate_management.md) — ротация и продление.
* [Диагностика 401 Unauthorized](../Troubleshooting/Common_Errors/ApiAccessForbidden/authentication_methods.md) — поиск причин отказа.
* [Субъекты RBAC](./rbac/subjects.md) — маппинг пользователей, групп и ServiceAccounts.
