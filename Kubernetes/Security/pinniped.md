# Pinniped — сервис аутентификации для Kubernetes

## Определения

**Pinniped** — это сервис аутентификации с открытым исходным кодом для Kubernetes, который позволяет администраторам подключать кластеры к внешним провайдерам идентификации (Identity Providers, IdP) без необходимости сложной настройки API-сервера.

**Supervisor** — центральный компонент Pinniped, который выступает в роли агрегатора IdP. Он аутентифицирует пользователей через внешние системы (OIDC, LDAP, AD) и выдает токены, понятные для Concierge. Один Supervisor может обслуживать множество кластеров.

**Concierge** — легковесный агент, устанавливаемый в каждый кластер Kubernetes. Он проверяет токены, выпущенные Supervisor (или другими OIDC-провайдерами), и интегрируется с механизмом Aggregated API Kubernetes для идентификации пользователей.

**Pinniped CLI / kubectl plugin** — клиентская утилита, которая расширяет возможности `kubectl`. Она автоматически инициирует процесс логина (например, открывает браузер или запрашивает учетные данные в терминале) и обновляет токены в `kubeconfig`.

## Основные концепции

### Архитектура и взаимодействие

Pinniped реализует многоуровневую схему аутентификации:

1. **Клиентская сторона:** Пользователь запускает команду `kubectl`. Плагин Pinniped проверяет наличие валидного токена.
2. **Аутентификация:** Если токен отсутствует или просрочен, плагин обращается к **Supervisor**.
3. **Внешний IdP:** Supervisor перенаправляет запрос к внешнему провайдеру (LDAP, OIDC). Пользователь вводит свои учетные данные.
4. **Выдача токена:** После успешной проверки IdP, Supervisor выдает пользователю свой JWT-токен.
5. **Доступ к кластеру:** Плагин передает этот токен в API-сервер кластера.
6. **Валидация:** API-сервер перенаправляет токен в **Concierge**, который подтверждает его подлинность у Supervisor и возвращает информацию о пользователе и его группах.
7. **Авторизация:** Далее Kubernetes использует стандартный [RBAC](./rbac/rbac_overview.md) для проверки прав пользователя.

### Поддерживаемые провайдеры

- **OIDC:** Okta, Dex, Google, Azure AD и др.
- **LDAP:** OpenLDAP, 389 Directory Server (389 DS).
- **Active Directory:** Полная интеграция с пользователями и группами AD.

## Практические сценарии

### 1. Установка Supervisor

Supervisor обычно устанавливается в выделенный кластер (или в тот же, где и приложения). Для установки используются официальные манифесты (или Helm-чарты, если доступны):

```bash
# Установка компонентов Supervisor (версия 0.43.0 для примера)
kubectl apply -f https://get.pinniped.dev/v0.43.0/install-pinniped-supervisor.yaml
```

Для доступа извне потребуется сервис типа `LoadBalancer` и валидный TLS-сертификат (можно выпустить через [cert-manager](../ToolsUtilities/cert_manager/definitions.md)).

### 2. Настройка LDAP IdP (на примере 389 DS)

Создание ресурса `LDAPIdentityProvider` для связи с LDAP-сервером.

```yaml
apiVersion: idp.supervisor.pinniped.dev/v1alpha1
kind: LDAPIdentityProvider
metadata:
  name: 389ds-provider
  namespace: pinniped-supervisor
spec:
  host: "389ds-service.ds.svc.cluster.local:3636"
  tls:
    certificateAuthorityDataSource:
      kind: Secret
      name: ldap-ca-cert
      key: ca.crt
  bind:
    secretName: ldap-bind-account
  userSearch:
    base: "ou=People,dc=test,dc=local"
    filter: "(uid={}) engine=identity"
    attributes:
      username: uid
      uid: uidNumber
  groupSearch:
    base: "ou=Groups,dc=test,dc=local"
    filter: "(uniqueMember={})"
    userAttributeForFilter: "dn"
    attributes:
      groupName: cn
```

*Важно: При использовании LDAPS обязательно наличие CA-сертификата в секрете.*

### 3. Настройка Federation Domain

Federation Domain связывает Supervisor с конкретным URL и IdP.

```yaml
apiVersion: config.supervisor.pinniped.dev/v1alpha1
kind: FederationDomain
metadata:
  name: my-federation-domain
  namespace: pinniped-supervisor
spec:
  issuer: "https://pinniped.example.com"
  tls:
    secretName: pinniped-tls-cert
```

### 4. Установка Concierge в кластер

Concierge устанавливается в каждый кластер, к которому нужен доступ.

```bash
kubectl apply -f https://get.pinniped.dev/v0.43.0/install-pinniped-concierge.yaml
```

Для настройки связи с Supervisor создается `JWTAuthenticator`:

```yaml
apiVersion: authentication.concierge.pinniped.dev/v1alpha1
kind: JWTAuthenticator
metadata:
  name: supervisor-authenticator
spec:
  issuer: "https://pinniped.example.com"
  audience: "my-cluster-unique-id"
  tls:
    certificateAuthorityDataSource:
      kind: Secret
      name: supervisor-ca-cert
      key: ca.crt
```

### 5. Настройка клиентского доступа

Администратор генерирует шаблон `kubeconfig` с помощью команды:

```bash
pinniped get kubeconfig --static > user-kubeconfig.yaml
```

Этот файл передается пользователю. При первом использовании `kubectl` плагин Pinniped предложит ввести логин/пароль.

## Дополнительная информация

### Сравнение с альтернативами

- **Rancher:** Предоставляет собственный механизм управления пользователями, но требует полной установки Rancher. Pinniped более легковесен.
- **ArgoCD:** Позволяет управлять правами внутри своего интерфейса, но не решает вопрос аутентификации напрямую в `kubectl` для всего кластера.
- **Dex:** Часто используется как бэкенд, Pinniped может работать поверх Dex или заменять его, предоставляя более глубокую интеграцию с `kubectl`.

### Безопасность и отказоустойчивость

- **Группы из LDAP:** Pinniped автоматически пробрасывает группы пользователя из LDAP/AD. Это позволяет настраивать доступ через стандартные `RoleBinding` для групп.
- **Отказ Pinniped:** В случае недоступности Supervisor или Concierge пользователи не смогут войти. Администраторы всегда должны иметь "аварийный" доступ через статический X.509 сертификат администратора.
- **Отзыв доступа:** При удалении или блокировке пользователя во внешнем IdP (LDAP/AD), доступ к Kubernetes прекращается автоматически при следующей проверке токена.

Связанные темы:

- [Аутентификация в Kubernetes](./authentication.md)
- [RBAC в Kubernetes](./rbac/rbac_overview.md)
- [LDAP в Kubernetes](../../LDAP/openldap_kubernetes.md)
