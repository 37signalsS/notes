# Pinniped: Сервис аутентификации для Kubernetes

## Определения

**Pinniped** — это сервис аутентификации с открытым исходным кодом для Kubernetes, позволяющий подключать кластеры к внешним провайдерам идентификации (Identity Providers, IdP) без сложной ручной настройки API-сервера. Проект переехал в организацию `vmware` (ghcr.io/vmware/pinniped).

* **Supervisor:** Центральный компонент Pinniped, выступающий агрегатором IdP. Он аутентифицирует пользователей через внешние системы (OIDC, LDAP, AD, GitHub, SAML) и выдает краткосрочные JWT-токены. Один Supervisor может обслуживать множество кластеров, обеспечивая единую точку входа (SSO).
* **Concierge:** Легковесный агент, устанавливаемый в каждый рабочий кластер. Он проверяет токены, выпущенные Supervisor (или другими доверенными эмитентами), и интегрируется с механизмом Aggregated API Kubernetes для передачи информации о пользователе и его группах в API-сервер.
* **Federation Domain:** Ресурс в Supervisor, определяющий логический домен аутентификации, его URL эмитента (Issuer URL) и правила сопоставления с вышестоящими IdP.
* **Pinniped CLI (плагин kubectl):** Клиентская утилита, которая расширяет возможности `kubectl`. Она автоматически инициирует процесс логина (через браузер или интерактивно) и обновляет токены в локальном `kubeconfig`.

**Важно:** Pinniped позволяет избежать перезагрузки API-сервера при изменении параметров аутентификации, так как конфигурация хранится в Custom Resources (CRD), а не в статических флагах процесса.

## Основные концепции

### Архитектура и детальное взаимодействие

Pinniped реализует многоуровневую схему федеративной аутентификации:

1. **Инициация:** Пользователь запускает команду `kubectl`. Плагин Pinniped проверяет наличие и валидность токена в `kubeconfig`.
2. **Запрос к Supervisor:** Если токен отсутствует или просрочен, плагин обращается к **Supervisor** кластера.
3. **Взаимодействие с IdP:** Supervisor перенаправляет запрос к внешнему провайдеру. Пользователь вводит учетные данные в системе IdP.
4. **Выдача токена Supervisor:** После успешной проверки Supervisor выдает пользователю JWT (JSON Web Token), подписанный его ключом.
5. **Обмен токена (Token Exchange):** Плагин передает полученный JWT в API-сервер целевого кластера, где его перехватывает **Concierge**.
6. **Валидация в Concierge:** Concierge подтверждает подлинность токена (проверяет подпись Supervisor) и возвращает API-серверу структурированную информацию об Identity (имя пользователя, UID, группы).
7. **Авторизация:** Kubernetes использует стандартный механизм [RBAC (Role-Based Access Control)](./rbac/rbac_overview.md) для финальной проверки прав доступа.

### Поддерживаемые провайдеры (IdP)

* **OIDC (OpenID Connect):** Поддержка Okta, Keycloak, Google, Azure AD, GitLab.
* **GitHub (Native):** Позволяет использовать организации и команды GitHub как группы Kubernetes.
* **LDAP:** Прямая интеграция с OpenLDAP, 389 Directory Server.
* **Active Directory:** Специализированный провайдер с поддержкой специфических атрибутов AD (objectGUID, sAMAccountName) и вложенных групп.
* **SAML:** Поддержка для корпоративных систем (SAML 2.0).

### Трансформации идентичности (CEL)

Pinniped поддерживает **Identity Transformations** на языке CEL (Common Expression Language). Это позволяет динамически изменять данные пользователя при переходе от Supervisor к Concierge:
* **Предотвращение коллизий:** Добавление префиксов (например, `ldap:` или `github:`) к именам пользователей.
* **Маппинг групп:** Переименование групп IdP в формат, принятый в кластере.
* **Фильтрация:** Ограничение доступа на основе атрибутов (например, разрешить вход только пользователям с `email_verified: true`).

### Сравнение с AuthenticationConfiguration (K8s 1.30+)

Начиная с Kubernetes 1.30, API-сервер поддерживает нативную федерацию через [структурированную конфигурацию](./authentication.md).
* **Pinniped** остается актуальным для:
    * Версий K8s < 1.30.
    * Использования LDAP/AD напрямую (K8s нативно поддерживает только OIDC).
    * Сложных трансформаций CEL, которые в Pinniped более гибки.
    * Удобного CLI-плагина, который автоматизирует получение токенов.

## Практические сценарии

### 1. Установка компонентов (v0.47.0)

Используются официальные манифесты из нового репозитория.

**Установка Supervisor:**
```bash
kubectl apply -f https://get.pinniped.dev/v0.47.0/install-pinniped-supervisor.yaml
```

**Установка Concierge:**
```bash
kubectl apply -f https://get.pinniped.dev/v0.47.0/install-pinniped-concierge-crds.yaml
kubectl apply -f https://get.pinniped.dev/v0.47.0/install-pinniped-concierge-resources.yaml
```

### 2. Настройка LDAP Identity Provider

```yaml
apiVersion: idp.supervisor.pinniped.dev/v1alpha1
kind: LDAPIdentityProvider
metadata:
  name: openldap-provider
  namespace: pinniped-supervisor
spec:
  host: "openldap.ldap.svc.cluster.local:3636"
  tls:
    certificateAuthorityDataSource:
      kind: Secret
      name: ldap-ca-cert
      key: ca.crt
  bind:
    secretName: ldap-bind-account
  userSearch:
    base: "ou=People,dc=example,dc=local"
    filter: "(uid={})"
    attributes:
      username: uid
      uid: uidNumber
  groupSearch:
    base: "ou=Groups,dc=example,dc=local"
    filter: "(uniqueMember={})"
    userAttributeForFilter: "dn"
    attributes:
      groupName: cn
```

### 3. Настройка Active Directory Identity Provider

В отличие от LDAP, здесь оптимизированы фильтры и поиск групп для AD.

```yaml
apiVersion: idp.supervisor.pinniped.dev/v1alpha1
kind: ActiveDirectoryIdentityProvider
metadata:
  name: ad-provider
  namespace: pinniped-supervisor
spec:
  host: "ad.example.com:636"
  bind:
    secretName: ad-bind-account # DN и password
  userSearch:
    base: "CN=Users,DC=example,DC=com"
    attributes:
      username: sAMAccountName
      uid: objectGUID
  groupSearch:
    base: "CN=Groups,DC=example,DC=com"
```

### 4. Настройка OIDC Identity Provider

```yaml
apiVersion: idp.supervisor.pinniped.dev/v1alpha1
kind: OIDCIdentityProvider
metadata:
  name: keycloak-oidc
  namespace: pinniped-supervisor
spec:
  issuer: "https://keycloak.example.com/realms/master"
  client:
    secretName: oidc-client-credentials
  claims:
    username: preferred_username
    groups: roles
```

### 5. Настройка SAML Identity Provider

```yaml
apiVersion: idp.supervisor.pinniped.dev/v1alpha1
kind: SAMLIdentityProvider
metadata:
  name: okta-saml
  namespace: pinniped-supervisor
spec:
  issuer: "http://www.okta.com/exk123"
  metadata:
    secretName: okta-metadata-xml # XML метаданные от провайдера
  claims:
    username: "email"
    groups: "groups"
```

### 6. Настройка GitHub Identity Provider

```yaml
apiVersion: idp.supervisor.pinniped.dev/v1alpha1
kind: GitHubIdentityProvider
metadata:
  name: github-auth
  namespace: pinniped-supervisor
spec:
  allowAuthentication:
    organizations:
      policy: OnlyUsersFromSpecificOrganizations
      allowedOrganizations: ["my-org"]
  client:
    secretName: github-client-credentials
  claims:
    username: login
    groups: teams
```

### 7. Настройка домена федерации и трансформаций

```yaml
apiVersion: config.supervisor.pinniped.dev/v1alpha1
kind: FederationDomain
metadata:
  name: main-federation
  namespace: pinniped-supervisor
spec:
  issuer: "https://pinniped.example.com"
  tls:
    secretName: pinniped-tls-cert
  identityTransformations:
    - type: username
      expression: 'user.username + "@" + idp.name'
```

### 8. Настройка доверия в кластере (JWTAuthenticator)

Concierge в рабочем кластере должен доверять Supervisor.

```yaml
apiVersion: authentication.concierge.pinniped.dev/v1alpha1
kind: JWTAuthenticator
metadata:
  name: supervisor-authenticator
spec:
  issuer: "https://pinniped.example.com"
  audience: "cluster-prod-01"
  tls:
    certificateAuthorityDataSource:
      kind: Secret
      name: supervisor-ca-cert
      key: ca.crt
```

## Дополнительная информация

### Сравнение с альтернативами

* **Dex:** Pinniped обеспечивает более глубокую нативную интеграцию с `kubectl` и поддерживает динамическую конфигурацию через CRD без перезагрузки.
* **Rancher:** Rancher — это комбайн; Pinniped — легковесное решение для федерации аутентификации в любом K8s.
* **Static OIDC:** Ограничен одним провайдером и требует доступа к флагам API-сервера.

### Безопасность и эксплуатация

* **FIPS:** Начиная с v0.47.0, используется нативная поддержка `GOFIPS140` в Go. Режим "boringcrypto" считается устаревшим.
* **Отказоустойчивость:** Supervisor и Concierge должны иметь несколько реплик.
* **Break-glass:** Всегда сохраняйте доступ через статические сертификаты (admin.conf) на случай недоступности IdP или Pinniped.
* **Отзыв прав:** Блокировка в IdP мгновенно запрещает получение новых токенов. Сессии JWT обычно живут 1-5 минут.

**Связанные темы:**

* [Аутентификация в Kubernetes](./authentication.md)
* [RBAC в Kubernetes](./rbac/rbac_overview.md)
* [OpenLDAP в Kubernetes](../../LDAP/openldap_kubernetes.md)
* [Управление секретами в приложении](./application_secrets_management.md)
