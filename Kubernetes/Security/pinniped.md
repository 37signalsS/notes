# Pinniped: Сервис аутентификации для Kubernetes

## Определения

**Pinniped** — это сервис аутентификации с открытым исходным кодом для Kubernetes, позволяющий подключать кластеры к внешним провайдерам идентификации (Identity Providers, IdP) без сложной ручной настройки API-сервера.

* **Supervisor:** Центральный компонент Pinniped, выступающий агрегатором IdP. Он аутентифицирует пользователей через внешние системы (OIDC, LDAP, AD, GitHub) и выдает краткосрочные JWT-токены. Один Supervisor может обслуживать множество кластеров, обеспечивая единую точку входа (SSO).
* **Concierge:** Легковесный агент, устанавливаемый в каждый рабочий кластер. Он проверяет токены, выпущенные Supervisor (или другими доверенными эмитентами), и интегрируется с механизмом Aggregated API Kubernetes для передачи информации о пользователе и его группах в API-сервер.
* **Federation Domain:** Ресурс в Supervisor, определяющий логический домен аутентификации, его URL эмитента (Issuer URL) и правила сопоставления с вышестоящими IdP.
* **Pinniped CLI (плагин kubectl):** Клиентская утилита, которая расширяет возможности `kubectl`. Она автоматически инициирует процесс логина (например, через браузер для OIDC или GitHub) и обновляет токены в локальном `kubeconfig`.

**Важно:** Pinniped позволяет избежать перезагрузки API-сервера при изменении параметров аутентификации, так как конфигурация хранится в Custom Resources (CRD), а не в статических флагах процесса.

## Основные концепции

### Архитектура и детальное взаимодействие

Pinniped реализует многоуровневую схему федеративной аутентификации:

1. **Инициация:** Пользователь запускает команду `kubectl`. Плагин Pinniped проверяет наличие и валидность токена в `kubeconfig`.
2. **Запрос к Supervisor:** Если токен отсутствует или просрочен, плагин обращается к **Supervisor** кластера.
3. **Взаимодействие с IdP:** Supervisor перенаправляет запрос к внешнему провайдеру (LDAP, OIDC, GitHub, Active Directory). Пользователь вводит учетные данные в системе IdP.
4. **Выдача токена Supervisor:** После успешной проверки Supervisor выдает пользователю JWT (JSON Web Token), подписанный его ключом.
5. **Обмен токена (Token Exchange):** Плагин передает полученный JWT в API-сервер целевого кластера, где его перехватывает **Concierge**.
6. **Валидация в Concierge:** Concierge подтверждает подлинность токена (проверяет подпись Supervisor) и возвращает API-серверу структурированную информацию об Identity (имя пользователя, UID, группы).
7. **Авторизация:** Kubernetes использует стандартный механизм [RBAC (Role-Based Access Control)](./rbac/rbac_overview.md) для финальной проверки прав доступа на основе групп, переданных Pinniped.

### Поддерживаемые провайдеры (IdP)

* **OIDC (OpenID Connect):** Полная поддержка Okta, Dex, Google, Azure AD, GitLab. С версии v0.43.0 добавлена улучшенная поддержка ADFS.
* **GitHub (Native):** С версии v0.31.0 поддерживается нативно как первый класс IdP. Позволяет использовать организации и команды GitHub как группы Kubernetes.
* **LDAP/Active Directory:** Прямая интеграция с OpenLDAP, 389 Directory Server и Microsoft AD без промежуточных прокси.
* **SAML:** Поддержка для корпоративных систем с протоколом SAML 2.0.

### Трансформации идентичности (CEL)

Pinniped поддерживает **Identity Transformations** на языке CEL (Common Expression Language). Это позволяет динамически изменять данные пользователя при переходе от Supervisor к Concierge:
* **Предотвращение коллизий:** Добавление префиксов (например, `ldap:` или `github:`) к именам пользователей, если используется несколько IdP.
* **Маппинг групп:** Переименование групп IdP в формат, принятый в кластере.
* **Фильтрация:** Запрет аутентификации на основе атрибутов (например, разрешить вход только пользователям с определенным доменом почты).

## Практические сценарии

### 1. Установка компонентов

Для актуальных версий (v0.43.0+) используются официальные манифесты.

**Установка Supervisor:**
```bash
kubectl apply -f https://get.pinniped.dev/v0.43.0/install-pinniped-supervisor.yaml
```
*Примечание:* Для доступа извне требуется сервис типа `LoadBalancer` и TLS-сертификат, который рекомендуется выпускать через `cert-manager`.

**Установка Concierge:**
```bash
kubectl apply -f https://get.pinniped.dev/v0.43.0/install-pinniped-concierge-crds.yaml
kubectl apply -f https://get.pinniped.dev/v0.43.0/install-pinniped-concierge-resources.yaml
```

### 2. Настройка LDAP Identity Provider

Детальный пример интеграции с LDAP-сервером:

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
    secretName: ldap-bind-account # Секрет с dn и password для поиска
  userSearch:
    base: "ou=People,dc=example,dc=local"
    filter: "(uid={})" # {} заменяется на введенный логин
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

### 3. Настройка GitHub Identity Provider (v0.31.0+)

Интеграция с организациями GitHub:

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
      allowedOrganizations: ["my-core-team-org"]
  client:
    secretName: github-client-credentials # ClientID и ClientSecret из GitHub App
  claims:
    username: login
    groups: teams # Маппинг команд GitHub в группы K8s
```

### 4. Настройка домена федерации и трансформаций

Ресурс связывает Supervisor с внешним URL и настраивает логику обработки имен:

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
      expression: 'user.username + "@" + idp.name' # Результат: user@github-auth
```

### 5. Настройка доверия в кластере (JWTAuthenticator)

```yaml
apiVersion: authentication.concierge.pinniped.dev/v1alpha1
kind: JWTAuthenticator
metadata:
  name: supervisor-authenticator
spec:
  issuer: "https://pinniped.example.com"
  audience: "cluster-production-01"
  tls:
    certificateAuthorityDataSource:
      kind: Secret
      name: supervisor-ca-cert
      key: ca.crt
```

## Дополнительная информация

### Сравнение с альтернативами

* **Dex:** Pinniped предоставляет более глубокую нативную интеграцию с `kubectl` и поддерживает динамическую конфигурацию без перезагрузки компонентов. В отличие от Dex, Pinniped не требует внешних прокси для работы с LDAP в режиме CLI.
* **Rancher:** Rancher имеет мощную встроенную систему аутентификации, но она жестко связана с экосистемой Rancher. Pinniped — модульное решение для любых дистрибутивов Kubernetes (EKS, GKE, bare-metal).
* **Static OIDC:** Статическая настройка API-сервера (`--oidc-issuer-url`) ограничена одним провайдером. Pinniped позволяет федеративно объединять множество IdP в одном кластере.

### Безопасность и эксплуатация

* **Автоматизация групп:** Pinniped передает членство в группах напрямую в токены, что позволяет управлять доступом через стандартные `RoleBinding` и `ClusterRoleBinding`.
* **Отказоустойчивость:** Supervisor и Concierge являются критическими компонентами. При их недоступности новые сессии не могут быть созданы. Рекомендуется:
    * Дублировать реплики подов.
    * Сохранять административный доступ (break-glass) через локальные X.509 сертификаты кластера.
* **Отзыв прав:** Блокировка пользователя во внешнем IdP (LDAP/AD/GitHub) мгновенно прекращает возможность получения новых токенов. Существующие сессии ограничиваются временем жизни JWT (обычно 1-5 минут).
* **FIPS:** Для государственных и банковских систем доступны сборки Pinniped, совместимые с FIPS 140-2.

**Связанные темы:**

* [Аутентификация в Kubernetes](./authentication.md)
* [RBAC в Kubernetes](./rbac/rbac_overview.md)
* [OpenLDAP в Kubernetes](../../LDAP/openldap_kubernetes.md)
* [Управление секретами в приложении](./application_secrets_management.md)
