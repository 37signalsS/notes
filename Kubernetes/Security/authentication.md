# Аутентификация в Kubernetes

## Определения

**Аутентификация (Authentication, AuthN)** в Kubernetes — это процесс проверки личности пользователя или компонента, отправляющего запрос к API-серверу. Каждому запросу, приходящему в кластер, должна быть сопоставлена учетная запись (человек-пользователь или `ServiceAccount`), либо он помечается как анонимный.

* **API-сервер как шлюз:** Аутентификация является первым этапом обработки запроса. Если личность не подтверждена, запрос отклоняется с кодом **401 Unauthorized** до этапа проверки прав (авторизации).
* **Пользователи (Users) vs Сервисные аккаунты (ServiceAccounts):**
    * **Пользователи:** Реальные люди или внешние системы. Kubernetes не хранит объекты «пользователь» в своей базе данных (etcd), полагаясь на внешние механизмы (сертификаты, OIDC).
    * **ServiceAccounts:** Внутренние объекты кластера, предназначенные для аутентификации процессов, запущенных в подах.

**Важно:** Подробное сравнение проверки личности и проверки прав доступно в материале [Authentication vs Authorization](../../Security/Concepts/authentication_vs_authorization.md).

## Основные концепции

### 1. X.509 Клиентские сертификаты

Один из наиболее надежных методов, используемый компонентами кластера (Kubelet, Scheduler) и администраторами.

* **Принцип работы:** Клиент предоставляет сертификат, подписанный доверенным Root CA кластера.
* **Маппинг атрибутов:**
    * `Common Name (CN)` → Имя пользователя (User).
    * `Organization (O)` → Имя группы (Group). Можно указать несколько полей `O` для членства в нескольких группах.
* **Особенности:** В Kubernetes нет встроенного механизма отзыва сертификатов (CRL/OCSP). Единственный способ аннулировать доступ — дождаться истечения срока действия или перевыпустить CA кластера (крайне сложная операция).

Подробнее о PKI: [PKI Overview](../../Security/Concepts/pki_overview.md), [TLS и mTLS в Kubernetes](./tls_and_mtls_in_kubernetes.md).

### 2. Привязанные токены (Bound Service Account Tokens)

Современный стандарт аутентификации для приложений (GA с v1.22, улучшения в v1.30+).

* **TokenRequest API:** Вместо создания вечных токенов-секретов, Kubernetes использует динамическую генерацию кратковременных токенов через `TokenRequest`.
* **Projected Volumes:** Токены монтируются в поды через [Projected Volume](../Base/Pod/volume_types/projected_volumes.md). Они автоматически ротируются Kubelet до истечения срока.
* **Механизмы привязки (Binding):**
    * **Time-bound:** Имеют ограниченный TTL (по умолчанию 1 час).
    * **Audience-bound:** Преддназначены для конкретного получателя (например, `vault`).
    * **Object-bound:** Привязаны к жизненному циклу конкретного Pod (токен недействителен после удаления пода).
    * **Node-bound (Beta v1.31):** Токен привязан к конкретному узлу.

### 3. Структурированная конфигурация и OIDC (v1.30+)

Начиная с Kubernetes 1.30, рекомендуется использовать флаг `--authentication-config` вместо старых флагов `--oidc-*`.

* **Multiple OIDC Providers:** Новая конфигурация `AuthenticationConfiguration` позволяет подключать неограниченное количество независимых OIDC-провайдеров (например, одновременно Okta, Google и GitHub).
* **CEL Expressions:** Использование Common Expression Language для динамического маппинга данных из токена в атрибуты пользователя. Например: `claims.email.split('@')[0]` для извлечения имени пользователя.
* **Hot-Reload:** API-сервер подхватывает изменения в конфигурационном файле без перезагрузки.
* **Pinniped:** Популярный инструмент для упрощения сложной федерации IdP. Подробнее: [Pinniped](./pinniped.md).

### 4. Вебхук-аутентификация (Webhook Token Authentication)

API-сервер отправляет полученный токен на внешний HTTP-сервис для проверки.

* **Сценарий:** Интеграция с корпоративными системами управления доступом, которые не поддерживают стандартный OIDC.
* **Результат:** Вебхук возвращает статус аутентификации и список групп пользователя в формате JSON.

### 5. Bootstrap Tokens и Статические токены

* **Bootstrap Tokens:** Используются `kubeadm` для временной аутентификации новых узлов во время присоединения к кластеру. Хранятся как `Secrets` в `kube-system`.
* **Static Token File:** Список токенов в CSV-файле на мастере. **Не рекомендуется** для использования из-за отсутствия безопасности и сложности ротации.

## Практические сценарии

### 1. Подготовка сертификата администратора (CSR)

Создание запроса на подпись сертификата через API Kubernetes:

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

### 2. Кастомизация ServiceAccount токена в поде

Использование `projected volume` для получения токена с кастомной аудиторией:

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

Конфигурация для поддержки двух провайдеров (Google и Azure):

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

## Дополнительная информация

### Рекомендации по безопасности

* **Отключение анонимного доступа:** Используйте `--anonymous-auth=false` или ограничьте анонимный доступ через `AuthenticationConfiguration` только для `/healthz`.
* **Отказ от Secret-based токенов:** Проверьте кластер на наличие старых `Secrets` с типом `kubernetes.io/service-account-token` и замените их на `TokenRequest`.
* **Ротация CA:** Настройте автоматическую ротацию сертификатов Kubelet через флаг `--rotate-certificates`.

### Сравнение методов аутентификации

| Метод | Субъект | Безопасность | Основная особенность |
|:------|:--------|:-------------|:---------------------|
| **X.509** | Компоненты, Админы | Высокая | Нельзя отозвать без смены CA |
| **Bound Tokens** | Приложения (SA) | Высокая | Авто-ротация, привязка к Pod/Node |
| **OIDC (v1.30+)** | Пользователи (SSO) | Высокая | Поддержка многих IdP, CEL-маппинг |
| **Webhook** | Кастомные системы | Средняя | Требует внешний сервис-валидатор |
| **Bootstrap** | Новые узлы | Средняя | Только для инициализации (`kubeadm`) |
| **Static Tokens** | Тестирование | Низкая | **Deprecated**, небезопасно |

**Ссылки:**

* [TLS и mTLS в Kubernetes](./tls_and_mtls_in_kubernetes.md) — детали шифрования трафика.
* [Pinniped: Интеграция с IdP](./pinniped.md) — продвинутая федерация идентичностей.
* [RBAC в Kubernetes](./rbac/rbac_overview.md) — следующий этап: проверка прав доступа.
* [Управление kubeconfig](../Operations/kubeconfig_and_connection.md) — настройка клиентского доступа.
