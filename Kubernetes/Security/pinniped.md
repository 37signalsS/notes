# Pinniped: Сервис аутентификации для Kubernetes

## Определения

**Pinniped** — это сервис аутентификации с открытым исходным кодом для Kubernetes, позволяющий подключать кластеры к внешним провайдерам идентификации (Identity Providers, IdP) без сложной ручной настройки API-сервера.

**Supervisor** — центральный компонент Pinniped, выступающий агрегатором IdP. Он аутентифицирует пользователей через внешние системы (OIDC, LDAP, AD) и выдает токены, понятные для Concierge. Один Supervisor может обслуживать множество кластеров.

**Concierge** — легковесный агент, устанавливаемый в каждый кластер Kubernetes. Он проверяет токены, выпущенные Supervisor (или другими провайдерами OpenID Connect, OIDC), и интегрируется с механизмом Aggregated API Kubernetes для идентификации пользователей.

**Pinniped CLI (Command Line Interface)** — клиентская утилита (плагин для `kubectl`), которая расширяет возможности стандартного интерфейса командной строки. Она автоматически инициирует процесс логина (например, через браузер) и обновляет токены в `kubeconfig`.

## Основные концепции

### Архитектура и взаимодействие

Pinniped реализует многоуровневую схему аутентификации:

1. **Клиентская сторона:** Пользователь запускает команду `kubectl`. Плагин Pinniped проверяет наличие валидного токена.
2. **Аутентификация:** Если токен отсутствует, плагин обращается к **Supervisor**.
3. **Внешний IdP:** Supervisor перенаправляет запрос к внешнему провайдеру (LDAP, OIDC, Active Directory). Пользователь вводит учетные данные.
4. **Выдача токена:** После успешной проверки Supervisor выдает пользователю JWT (JSON Web Token).
5. **Доступ к кластеру:** Плагин передает этот токен в API-сервер кластера.
6. **Валидация:** API-сервер перенаправляет токен в **Concierge**, который подтверждает его подлинность и возвращает информацию о пользователе и группах.
7. **Авторизация:** Kubernetes использует стандартный [RBAC (Role-Based Access Control)](./rbac/rbac_overview.md) для проверки прав.

### Поддерживаемые провайдеры

- **OIDC (OpenID Connect):** Okta, Dex, Google, Azure AD.
- **LDAP (Lightweight Directory Access Protocol):** OpenLDAP, 389 Directory Server.
- **Active Directory (AD):** Полная интеграция с пользователями и группами Windows-доменов.

## Практические сценарии

### 1. Установка Supervisor

Для установки используются официальные манифесты (версия v0.46.0):

```bash
# Установка компонентов Supervisor
kubectl apply -f https://get.pinniped.dev/v0.46.0/install-pinniped-supervisor.yaml
```

Для доступа извне требуется сервис типа `LoadBalancer` и TLS-сертификат (Transport Layer Security), который можно выпустить через [cert-manager](../ToolsUtilities/cert_manager/definitions.md).

### 2. Настройка LDAP IdP

Пример ресурса `LDAPIdentityProvider` для интеграции с LDAP-сервером:

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

### 3. Настройка Federation Domain

Federation Domain связывает Supervisor с конкретным URL и провайдером.

```yaml
apiVersion: config.supervisor.pinniped.dev/v1alpha1
kind: FederationDomain
metadata:
  name: main-federation-domain
  namespace: pinniped-supervisor
spec:
  issuer: "https://pinniped.example.com"
  tls:
    secretName: pinniped-tls-cert
```

### 4. Установка Concierge

Concierge устанавливается в целевой кластер:

```bash
kubectl apply -f https://get.pinniped.dev/v0.46.0/install-pinniped-concierge-crds.yaml
kubectl apply -f https://get.pinniped.dev/v0.46.0/install-pinniped-concierge-resources.yaml
```

Настройка связи через `JWTAuthenticator`:

```yaml
apiVersion: authentication.concierge.pinniped.dev/v1alpha1
kind: JWTAuthenticator
metadata:
  name: supervisor-authenticator
spec:
  issuer: "https://pinniped.example.com"
  audience: "cluster-alpha"
  tls:
    certificateAuthorityDataSource:
      kind: Secret
      name: supervisor-ca-cert
      key: ca.crt
```

## Дополнительная информация

### Сравнение с альтернативами

- **Dex:** Pinniped предоставляет более глубокую интеграцию с `kubectl` и нативную поддержку LDAP/AD без необходимости использования Dex как прослойки, хотя может работать поверх него.
- **Rancher:** Rancher имеет встроенную аутентификацию, но Pinniped более модульный и подходит для "чистых" кластеров Kubernetes.
- **Static OIDC:** Pinniped избавляет от необходимости перезапускать API-сервер при изменении настроек IdP.

### Безопасность

- **Автоматизация групп:** Pinniped передает группы напрямую в Kubernetes, что позволяет использовать стандартные `RoleBinding`.
- **Отказоустойчивость:** При недоступности Pinniped вход новых пользователей невозможен. Рекомендуется сохранять административный доступ через X.509 сертификаты (CA кластера).
- **Отзыв прав:** Блокировка пользователя в LDAP/AD приводит к автоматическому прекращению доступа в Kubernetes при следующей проверке токена.

**Связанные темы:**

- [Аутентификация в Kubernetes](./authentication.md)
- [RBAC в Kubernetes](./rbac/rbac_overview.md)
- [OpenLDAP в Kubernetes](../../LDAP/openldap_kubernetes.md)
- [PKI Overview](../../Security/Concepts/pki_overview.md) (Public Key Infrastructure)
