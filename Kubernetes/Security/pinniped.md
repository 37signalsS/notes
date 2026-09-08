# Pinniped: Сервис аутентификации для Kubernetes

## Определения

**Pinniped** — это сервис аутентификации с открытым исходным кодом для Kubernetes, позволяющий подключать кластеры к внешним провайдерам идентичности (Identity Providers, IdP) без сложной ручной настройки API-сервера. Проект переехал в организацию `vmware` (ghcr.io/vmware/pinniped).

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

### OAuth 2.0 Token Exchange (RFC 8693)

Механизм обмена токена между Supervisor и Concierge основан на протоколе **OAuth 2.0 Token Exchange** (RFC 8693). Это отличает Pinniped от простого проброса JWT и обеспечивает дополнительные гарантии безопасности:

* **Subject Token:** Исходный токен, выданный внешним IdP, передается как `subject_token` в запросе обмена.
* **Actor Token:** В некоторых конфигурациях Concierge может выступать как актор (actor), подтверждающий права на обмен.
* **Token Type:** По умолчанию используется `urn:ietf:params:oauth:token-type:refresh_token` или `urn:ietf:params:oauth:token-type:access_token`.
* **Audience Restriction:** Supervisor проверяет, что запрос обмена предназначен для доверенного потребителя (Concierge), что предотвращает использование украденного токена в других сервисах.

Преимущество RFC 8693 заключается в том, что внешний IdP не нужно интегрировать напрямую с каждым кластером. Supervisor выступает как доверенный посредник, а Concierge валидирует только подпись Supervisor, а не подпись внешнего IdP.

### PKI и TLS-архитектура Pinniped

Pinniped требует защищенного канала связи между компонентами:

* **Supervisor TLS:** Должен быть доступен по HTTPS с валидным сертификатом. Рекомендуется использовать сертификаты, подписанные доверенным CA (например, cert-manager с Let's Encrypt или внутренним CA).
* **Concierge TLS:** Concierge регистрируется в API-сервере как Aggregated API Server. Его сертификат также должен быть доверенным для API-сервера.
* **mTLS между Supervisor и Concierge:** В production-средах рекомендуется включить взаимную TLS-аутентификацию. Concierge проверяет подпись Supervisor через JWTAuthenticator, но дополнительный слой mTLS снижает риск атак при компрометации CA.
* **CA Bundle:** Корневые сертификаты CA Supervisor хранятся в Kubernetes Secret и монтируются в Concierge через `cert-manager` или вручную.

### JWT-токены: структура и claims

Токены, выдаваемые Supervisor, являются стандартными JWT (RFC 7519):

* **iss (Issuer):** URL Federation Domain (например, `https://pinniped.example.com`).
* **sub (Subject):** Уникальный идентификатор пользователя, обычно с префиксом IdP (например, `github:octocat` или `ldap:jdoe`).
* **aud (Audience):** Идентификатор доверенного потребителя (audience из JWTAuthenticator). Должен совпадать с `spec.audience` в Concierge.
* **exp (Expiration Time):** Кратковременность токена — по умолчанию 5 минут, максимально 1 час.
* **groups:** Массив групп пользователя, полученный из IdP и пропущенный через CEL-трансформации.
* **email, name:** Дополнительные claims, если включены в конфигурации Identity Provider.

**Проверка токена:** Concierge проверяет:
1. Подпись через открытый ключ Supervisor (JWKS endpoint).
2. Срок действия (`exp`).
3. Audience (`aud`).
4. Issuer (`iss`).
5. Дополнительные ограничения, заданные в JWTAuthenticator.

### CRD API Groups и версионирование

Pinniped использует следующие API Groups:

* `idp.supervisor.pinniped.dev/v1alpha1` — конфигурация Identity Providers.
* `config.supervisor.pinniped.dev/v1alpha1` — Federation Domain и трансформации.
* `authentication.concierge.pinniped.dev/v1alpha1` — JWTAuthenticator и доверительные отношения.
* `login.concierge.pinniped.dev/v1alpha1` — ресурсы сессий логина (внутреннее использование).

**Важно:** API Groups имеют статус `v1alpha1`, что означает возможность breaking changes при мажорных обновлениях. Перед обновлением Pinniped проверяйте release notes на предмет изменений в CRD-схемах. Всегда делайте бэкап CRD-объектов (`kubectl get <crd> -A -o yaml > backup.yaml`).

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

### 9. CI/CD интеграция

Pinniped может использоваться в пайплайнах для безопасного доступа к кластерам:

```yaml
# GitLab CI example
deploy:
  image: bitnami/kubectl:latest
  script:
    - pinniped login kubeconfig \
        --supervisor https://pinniped.example.com \
        --credential-file /credentials/supervisor-token.json \
        --kubeconfig /tmp/kubeconfig
    - kubectl apply -f deployment.yaml
  only:
    - main
```

**GitHub Actions:**
```yaml
- name: Configure Pinniped Kubeconfig
  run: |
    pinniped login kubeconfig \
      --supervisor https://pinniped.example.com \
      --credential-file ${{ secrets.SUPERVISOR_CREDENTIALS }} \
      --kubeconfig ./kubeconfig
- name: Deploy
  run: kubectl apply -f manifests/
```

### 10. Апгрейд версий

Перед обновлением Pinniped:

```bash
# 1. Бэкап текущих CRD и конфигураций
kubectl get crd | grep pinniped > pinniped-crds.txt
kubectl get all -n pinniped-supervisor -o yaml > supervisor-backup.yaml
kubectl get all -n pinniped-concierge -o yaml > concierge-backup.yaml

# 2. Проверка совместимости CRD
kubectl get crd idp.supervisor.pinniped.dev -o jsonpath='{.spec.versions[*].name}'

# 3. Обновление через Helm (рекомендуется для production)
helm repo update pinniped
helm upgrade pinniped-supervisor pinniped/supervisor \
  --namespace pinniped-supervisor \
  --version <новая_версия>

# 4. Проверка статуса
kubectl get pods -n pinniped-supervisor
kubectl get pods -n pinniped-concierge
kubectl get jwtauthenticator -A
```

## Production-развертывание

### Высоконагруженный Supervisor (HA)

Supervisor должен разворачиваться в production с несколькими репликами:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pinniped-supervisor
  namespace: pinniped-supervisor
spec:
  replicas: 3
  selector:
    matchLabels:
      app: pinniped-supervisor
  template:
    metadata:
      labels:
        app: pinniped-supervisor
    spec:
      serviceAccountName: pinniped-supervisor
      containers:
      - name: supervisor
        image: ghcr.io/vmware/pinniped/supervisor:v0.47.0
        ports:
        - containerPort: 5443
          name: https
        resources:
          requests:
            cpu: 250m
            memory: 256Mi
          limits:
            cpu: "1"
            memory: 512Mi
        livenessProbe:
          httpGet:
            path: /healthz
            port: 5443
            scheme: HTTPS
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /readyz
            port: 5443
            scheme: HTTPS
          initialDelaySeconds: 5
          periodSeconds: 10
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: pinniped-supervisor-pdb
  namespace: pinniped-supervisor
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: pinniped-supervisor
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: pinniped-supervisor-hpa
  namespace: pinniped-supervisor
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: pinniped-supervisor
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

**Почему так:**
* `replicas: 3` — минимальное количество для quorum при использовании etcd встроенного в Supervisor (если не используется внешнее хранилище).
* `PodDisruptionBudget` с `minAvailable: 2` — предотвращает одновременный drain всех реплик при.node maintenance.
* `HorizontalPodAutoscaler` — автоматическое масштабирование при всплесках логинов (утро, начало рабочего дня).
* `livenessProbe` / `readinessProbe` по HTTPS — Supervisor отвечает на `/healthz` и `/readyz`.

### RBAC для ServiceAccount Pinniped

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: pinniped-supervisor
  namespace: pinniped-supervisor
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: pinniped-supervisor
rules:
- apiGroups: ["config.supervisor.pinniped.dev"]
  resources: ["federationdomains"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["idp.supervisor.pinniped.dev"]
  resources: ["ldapidentityproviders", "active directoryidentityproviders", "oidcidentityproviders", "samlidentityproviders", "githubidentityproviders"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"]
  resourceNames: ["ldap-bind-account", "oidc-client-credentials", "pinniped-tls-cert"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: pinniped-supervisor
subjects:
- kind: ServiceAccount
  name: pinniped-supervisor
  namespace: pinniped-supervisor
roleRef:
  kind: ClusterRole
  name: pinniped-supervisor
  apiGroup: rbac.authorization.k8s.io
```

### NetworkPolicy для компонентов Pinniped

Ограничение сетевого доступа снижает поверхность атаки:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-supervisor-ingress
  namespace: pinniped-supervisor
spec:
  podSelector:
    matchLabels:
      app: pinniped-supervisor
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: pinniped-concierge
    ports:
    - protocol: TCP
      port: 5443
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-concierge-ingress
  namespace: pinniped-concierge
spec:
  podSelector:
    matchLabels:
      app: pinniped-concierge
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector: {}
    ports:
    - protocol: TCP
      port: 8443
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all-egress
  namespace: pinniped-supervisor
spec:
  podSelector:
    matchLabels:
      app: pinniped-supervisor
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - protocol: TCP
      port: 636  # LDAPS
    - protocol: TCP
      port: 443  # HTTPS (OIDC, SAML)
    - protocol: TCP
      port: 389  # LDAP
```

### TLS-сертификаты с cert-manager

Автоматизация выдачи и ротации сертификатов для Supervisor:

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: pinniped-supervisor-tls
  namespace: pinniped-supervisor
spec:
  secretName: pinniped-tls-cert
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
  - "pinniped.example.com"
  duration: 2160h  # 90 дней
  renewBefore: 720h  # 30 дней до истечения
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: pinniped-concierge-tls
  namespace: pinniped-concierge
spec:
  secretName: pinniped-concierge-tls
  issuerRef:
    name: internal-ca-issuer
    kind: ClusterIssuer
  dnsNames:
  - "pinniped-concierge.pinniped-concierge.svc"
  duration: 2160h
  renewBefore: 720h
```

## Мониторинг и наблюдаемость

### Метрики Prometheus

Supervisor и Concierge экспортируют метрики Prometheus на порту `8080` (по умолчанию):

```yaml
# ServiceMonitor для Prometheus Operator
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: pinniped-supervisor
  namespace: pinniped-supervisor
spec:
  selector:
    matchLabels:
      app: pinniped-supervisor
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
---
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: pinniped-concierge
  namespace: pinniped-concierge
spec:
  selector:
    matchLabels:
      app: pinniped-concierge
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
```

**Ключевые метрики:**
* `pinniped_supervisor_login_success_total` — успешные логины.
* `pinniped_supervisor_login_failure_total` — неудачные логины (полезно для детектирования brute-force).
* `pinniped_supervisor_token_exchange_duration_seconds` — задержка обмена токена.
* `pinniped_concierge_token_validation_total` — валидации токенов в Concierge.

### Структурированное логирование

Настройка логгера в deployment:

```yaml
      containers:
      - name: supervisor
        image: ghcr.io/vmware/pinniped/supervisor:v0.47.0
        env:
        - name: LOG_LEVEL
          value: "info"  # debug, info, warn, error
        - name: LOG_FORMAT
          value: "json"  # json или console
        volumeMounts:
        - name: logs
          mountPath: /var/log/pinniped
```

Рекомендуется собирать логи через Fluentd/Fluent Bit или Promtail в Loki.

## Мультикластерность и федерация

### Сценарий: Hub-and-Spoke Federation

Один центральный Supervisor обслуживает несколько рабочих кластеров:

* **Supervisor:** Развертывается в dedicated cluster (hub) с высокой доступностью.
* **Concierge:** Устанавливается в каждом spoke-кластере.
* **Federation Domain:** Один Federation Domain на Supervisor, но для каждого кластера создается отдельный `JWTAuthenticator` с уникальным `audience`.
* **Identity Transformations:** Централизованно управляются в Supervisor, что упрощает аудит.

### Сценарий: Multi-Supervisor (Резервирование IdP)

Если у вас есть несколько IdP (например, AD и Okta), можно настроить несколько Identity Provider в одном Federation Domain. Supervisor последовательно пробует провайдеры или использует правила маршрутизации:

```yaml
apiVersion: config.supervisor.pinniped.dev/v1alpha1
kind: FederationDomain
metadata:
  name: multi-idp-federation
  namespace: pinniped-supervisor
spec:
  issuer: "https://pinniped.example.com"
  tls:
    secretName: pinniped-tls-cert
  identityProviders:
  - name: okta-primary
    type: OIDC
    # ... конфигурация Okta
  - name: ad-fallback
    type: ActiveDirectory
    # ... конфигурация AD
```

## Ограничения и известные проблемы

### Ограничения статического анализа

* **Отсутствие семантического анализа:** Pinniped не проверяет политики RBAC или NetworkPolicy. Он только аутентифицирует (AuthN), но не авторизует (AuthZ).
* **Зависимость от внешних IdP:** Доступность Pinniped напрямую зависит от доступности внешнего IdP. При offline-режиме идентификация невозможна (break-glass доступ через static credentials остается единственным вариантом).
* **v1alpha1 API:** CRD-схемы могут меняться между версиями. Не используйте Pinniped в production без прохождения полного цикла тестирования при каждом мажорном обновлении.
* **Только Kubernetes:** Pinniped не работает с другими оркестраторами (Nomad, Docker Swarm).
* **Ограничения CEL:** Хотя CEL мощный, сложные выражения могут снижать производительность трансформации. Избегайте циклов и рекурсии.

### Известные проблемы

* **Token Cache Race Condition:** В редких случаях при параллельных запросах `kubectl` плагин Pinniped может попытаться обновить токен одновременно, что приводит к 401. Решение: обновление Pinniped CLI до v0.47.0+, где добавлен файловый lock.
* **LDAP Group Nesting:** Вложенные группы в AD/LDAP могут не разрешаться корректно без явного указания `nestedGroups: true` в конфигурации провайдера (доступно начиная с v0.45.0).
* **Memory Leak в Supervisor:** При очень высоком RPS (более 1000 запросов/сек) зафиксированы утечки памяти в Supervisor. Рекомендуется горизонтальное масштабирование и мониторинг RSS.

## Соответствие стандартам

Pinniped покрывает требования следующих стандартов:

| Стандарт | Раздел | Соответствие |
| :--- | :--- | :--- |
| **CIS Kubernetes Benchmark** | 1.2.1, 1.2.2 | Централизованная аутентификация, отказ от статических пользователей. |
| **PCI DSS** | 2.2, 8.3 | SSO, MFA через внешний IdP, кратковременные токены. |
| **ISO 27001** | A.9.2.1, A.9.4.2 | Управление доступом, уникальная идентификация пользователей. |
| **SOC 2** | CC6.1, CC6.3 | Логическое разделение, ограничение срока действия сессий. |

Общие принципы комплаенса подробно описаны в разделе [Аудит и комплаенс: Обзор](../../Security/audit_and_compliance_overview.md).

## Сравнение с альтернативами

* **Dex:** Pinniped обеспечивает более глубокую нативную интеграцию с `kubectl` и поддерживает динамическую конфигурацию через CRD без перезагрузки.
* **Rancher:** Rancher — это комбайн; Pinniped — легковесное решение для федерации аутентификации в любом K8s.
* **Static OIDC:** Ограничен одним провайдером и требует доступа к флагам API-сервера.
* **kubelogin (Azure):** Аналогичная функциональность (OIDC login plugin), но только для Azure AD. Pinniped поддерживает широкий спектр IdP.
* **Keycloak Gatekeeper / oauth2-proxy:** Решения на уровне L7 (Ingress), которые не заменяют аутентификацию на уровне API-сервера. Pinniped интегрируется на уровне AuthN chain.

## Безопасность и эксплуатация

* **FIPS:** Начиная с v0.47.0, используется нативная поддержка `GOFIPS140` в Go. Режим "boringcrypto" считается устаревшим.
* **Отказоустойчивость:** Supervisor и Concierge должны иметь несколько реплик.
* **Break-glass:** Всегда сохраняйте доступ через статические сертификаты (admin.conf) на случай недоступности IdP или Pinniped.
* **Отзыв прав:** Блокировка в IdP мгновенно запрещает получение новых токенов. Сессии JWT обычно живут 1-5 минут.
* **Сегрегация Namespace:** Supervisor и Concierge разворачиваются в отдельных namespace. Никогда не смешивайте их с рабочими нагрузками.
* **Минимизация прав ServiceAccount:** Supervisor должен иметь доступ только к своим CRD и Secrets с credentials IdP. Concierge требует прав на регистрацию Aggregated API.

## Связанные темы

* [Аутентификация в Kubernetes](./authentication.md)
* [RBAC в Kubernetes](./rbac/rbac_overview.md)
* [OpenLDAP в Kubernetes](../../LDAP/openldap_kubernetes.md)
* [Управление секретами в приложении](./application_secrets_management.md)
* [Сетевые политики (NetworkPolicy)](../Networking/Network/network_policy.md) — изоляция трафика между компонентами Pinniped.
* [cert-manager: Установка](../ToolsUtilities/cert_manager/installation.md) — автоматизация TLS-сертификатов для Supervisor.
* [Аудит событий в Kubernetes](./audit.md) — логирование API-вызовов для аудита доступа.

**Ссылки:**
* [Официальный репозиторий проекта](https://github.com/vmware-tanzu/pinniped)
* [Документация](https://pinniped.dev)
