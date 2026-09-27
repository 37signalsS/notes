# Политики безопасности Istio

## Определения

**Безопасность Istio** — комплекс механизмов для реализации модели **Zero Trust** в микросервисных архитектурах. Она базируется на трех фундаментальных принципах:
1.  **Идентичность (Identity):** Каждая рабочая нагрузка (Workload) имеет уникальный криптографический идентификатор на основе стандарта [SPIFFE](https://spiffe.io/).
2.  **Аутентификация (Authentication):** Проверка подлинности отправителя (mTLS) и конечного пользователя (JWT/OIDC).
3.  **Авторизация (Authorization):** Управление доступом на основе политик (L4–L7), определяющих, «кто», «куда» и «как» может обращаться.

В 2026 году (версии 1.32+) основным интерфейсом управления безопасностью стал **Gateway API** (GAMMA), а механизмы mTLS инкапсулированы в протокол **HBONE** для поддержки Ambient Mesh.

---

## Идентичность и SPIFFE

Istio использует идентификаторы **SPIFFE ID** для представления сервисов. Формат: `spiffe://<trust-domain>/ns/<namespace>/sa/<service-account>`.

- **Trust Domain:** Логическая группа доверия (по умолчанию `cluster.local`). В мультикластерных конфигурациях каждый кластер может иметь свою trust domain, объединенную через federation.
- **SVID (SPIFFE Verifiable Identity Document):** X.509 сертификат, выпускаемый Istiod (или внешним CA, например Vault/SPIRE), содержащий SPIFFE ID в поле SAN (Subject Alternative Name).
- **Ротация:** Сертификаты короткоживущие (обычно 24 часа) и ротируются автоматически без участия приложения. Ротация происходит задолго до истечения срока; прокси поддерживают оба сертификата (старое и новое) в течение grace period, не прерывая соединения.
- **Trust Bundle:** корневые CA distributing через ConfigMap или секрет. При росте мультикластерной инфраструктуры trust bundle необходимо экспортировать из Primary и импортировать в Remote кластеры.

---

## Аутентификация (Authentication)

### 1. Peer Authentication (mTLS)

Ресурс `PeerAuthentication` определяет, как прокси принимают входящие соединения. В 2026 году mTLS между узлами в Ambient Mesh выполняется компонентом **Ztunnel**.

**Режимы работы (`mode`):**
- **`STRICT` (Стандарт 2026):** Разрешен ТОЛЬКО mTLS-трафик. Любые запросы в открытом тексте блокируются.
- **`PERMISSIVE`:** Принимает mTLS и Plain Text. Используется исключительно для временной миграции (не рекомендуется для продакшена).
- **`DISABLE`:** mTLS отключен.

**Область действия (scope):**
- **Namespace-level:** если ресурс `PeerAuthentication` применен к неймспейсу, он действует на все Workloads в этом неймспейсе.
- **Workload-level:** если указан `selector`, политика действует только на поды с соответствующими метками.
- **Port-level:** можно переопределить режим для конкретного порта через `portLevelMtls`.

**Пример: Глобальный Strict mTLS (istio-system)**

```yaml
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: istio-system
spec:
  mtls:
    mode: STRICT
```

**Пример: PERMISSIVE для конкретного порта (миграция)**

```yaml
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: legacy-migration
  namespace: prod
spec:
  selector:
    matchLabels:
      app: legacy-service
  mtls:
    mode: PERMISSIVE
  portLevelMtls:
    8080:
      mode: STRICT
```

**Миграция с PERMISSIVE на STRICT:**
1. Убедитесь, что все отправители в mesh имеют sidecar/ztunnel.
2. Примените `PeerAuthentication: PERMISSIVE` и включите логирование отказов.
3. Используйте `istioctl proxy-config secret` и логи Ztunnel для поиска plaintext-трафика.
4. После устранения всех источников plaintext переключите в `STRICT`.

### 2. Request Authentication (JWT)

Проверяет токены конечных пользователей (JWT) от внешних провайдеров (Auth0, Keycloak, Okta). Ресурс работает только для L7-трафика, проходящего через Envoy (sidecar или waypoint); в Ambient Mesh L4-трафик через Ztunnel не проверяет JWT.

```yaml
apiVersion: security.istio.io/v1beta1
kind: RequestAuthentication
metadata:
  name: jwt-auth
  namespace: prod
spec:
  selector:
    matchLabels:
      app: api-server
  jwtRules:
  - issuer: "https://keycloak.example.com/auth/realms/master"
    jwksUri: "https://keycloak.example.com/auth/realms/master/protocol/openid-connect/certs"
    audiences: ["my-api"]
    forwardOriginalToken: true
```

**Параметры:**
- `issuer`: идентификатор провайдера токенов.
- `jwksUri`: URL с открытыми ключами для проверки подписи.
- `audiences`: список допустимых значений claims `aud`. Если не указан, проверка отключена.
- `forwardOriginalToken`: передавать исходный JWT в заголовке `Authorization` бэкенду (по умолчанию `true`).

**CORS:** Istio не предоставляет отдельного ресурса CORS. Настройка CORS-headers осуществляется через `EnvoyFilter` или `TrafficExtension` (Lua) на уровне Waypoint/Sidecar.

---

## Авторизация (Authorization)

Политики авторизации (`AuthorizationPolicy`) реализуют принцип наименьших привилегий.

### Иерархия и приоритеты

1.  **DENY:** Если запрос подпадает под правило `DENY`, он блокируется немедленно.
2.  **ALLOW:** Если есть правила `ALLOW`, запрос разрешается только при совпадении с одним из них.
3.  **Default-Deny:** Если определена хотя бы одна политика `ALLOW`, весь остальной трафик к ворклоаду запрещен.

**Важно:** политики действуют только на трафик, проходящий через прокси. Если `PeerAuthentication: DISABLE` или трафик идет в обход mesh, `AuthorizationPolicy` не применяется.

### Синтаксис правил

**L4 (транспортный уровень):**
```yaml
rules:
- from:
  - source:
      principals: ["spiffe://cluster.local/ns/prod/sa/billing-sa"]
      ipBlocks: ["10.0.0.0/8"]
      remoteIpBlocks: ["192.168.0.0/16"]
  to:
  - operation:
      ports: ["5432", "3306"]
```

**L7 (прикладной уровень):**
```yaml
rules:
- to:
  - operation:
      methods: ["GET", "HEAD"]
      paths: ["/public/*"]
      host: ["api.example.com"]
  when:
  - key: request.auth.claims[role]
    values: ["admin", "editor"]
  - key: request.headers[x-api-version]
    values: ["v2"]
```

**Ключи `when`:**
- `request.auth.claims[<claim-name>]` — JWT claims.
- `request.headers[<header-name>]` — HTTP-заголовки.
- `destination.port` — порт назначения.
- `request.host` — хост заголовка.
- `request.path` — путь запроса.
- `request.method` — HTTP-метод.
- `request.scheme` — схема (`http`/`https`).

### Правила DENY

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: deny-sensitive-paths
  namespace: prod
spec:
  selector:
    matchLabels:
      app: inventory
  action: DENY
  rules:
  - to:
    - operation:
        paths: ["/admin/*", "/internal/*"]
```

### Безопасность в Ambient Mesh
- **L4 Политики (IP, Principals):** Исполняются на уровне **Ztunnel** (максимальная производительность).
- **L7 Политики (Path, Methods, Headers):** Исполняются на уровне **Waypoint Proxy**. Для их работы необходимо развернуть Waypoint для неймспейса или сервиса.

### Namespace-scoped политики

Политики без `selector` действуют на весь неймспейс. Это полезно для default-deny на уровне окружения:

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: default-deny-all
  namespace: prod
spec:
  {} # Пустая политика ALLOW запрещает всё, что не разрешено явно
```

**Пример: Default-Deny (Блокировать всё по умолчанию)**

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: allow-nothing
  namespace: prod
spec:
  {} # Пустая политика ALLOW запрещает всё, что не разрешено явно
```

**Пример: Доступ по SPIFFE ID (L4)**

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: allow-billing-to-inventory
  namespace: prod
spec:
  selector:
    matchLabels:
      app: inventory
  action: ALLOW
  rules:
  - from:
    - source:
        principals: ["spiffe://cluster.local/ns/prod/sa/billing-sa"]
```

**Пример: Проверка JWT Claims (L7)**

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: require-admin-role
  namespace: prod
spec:
  action: ALLOW
  rules:
  - when:
    - key: request.auth.claims[role]
      values: ["admin"]
```

---

## BackendTLSPolicy (Gateway API)

С 2026 года mTLS между Gateway и бэкендом настраивается через `BackendTLSPolicy` (Gateway API). Это отделяет конфигурацию TLS от специфики mesh и работает с любым совместимым шлюзом.

```yaml
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: BackendTLSPolicy
metadata:
  name: backend-mtls
  namespace: prod
spec:
  targetRefs:
  - group: ""
    kind: Service
    name: my-api
    port: 443
  tls:
    mode: Mutual
    caCertificates:
    - name: mesh-ca
      group: ""
      kind: ConfigMap
```

---

## Внешняя авторизация (ExtAuthz)

Для делегирования авторизации на внешний сервис (OPA, Envoy External Authorization, кастомный API) используйте `TrafficExtension` с Lua или Wasm-расширением, либо `EnvoyFilter`.

**Вариант 1: TrafficExtension (Lua) для Waypoint/Sidecar:**

```yaml
apiVersion: extensions.istio.io/v1alpha1
kind: TrafficExtension
metadata:
  name: ext-authz-check
  namespace: prod
spec:
  selector:
    matchLabels:
      app: api-server
  phase: AUTHZ
  priority: 100
  lua:
    inlineCode: |
      function envoy_on_request(req)
        local authz_header = req:headers():get("x-ext-authz")
        if authz_header == "allow" then
          return
        end
        req:headers():add(":status", "403")
        req:headers():add("content-type", "application/json")
        req:body():setBytes('{"error":"forbidden"}')
      end
```

**Вариант 2: EnvoyFilter (кластерный):**

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: EnvoyFilter
metadata:
  name: ext-authz
  namespace: istio-system
spec:
  workloadSelector:
    labels:
      app: istio-ingressgateway
  configPatches:
  - applyTo: HTTP_FILTER
    match:
      context: GATEWAY
      listener:
        filterChain:
          filter:
            name: "envoy.filters.network.http_connection_manager"
    patch:
      operation: INSERT_BEFORE
      value:
        name: envoy.filters.http.ext_authz
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthz
          http_service:
            server_uri:
              uri: ext-authz.prod.svc.cluster.local
              cluster: ext-authz
              timeout: 2s
            authorization_request:
              headers_to_add:
              - key: x-request-id
                value: "%REQ(x-request-id)%"
```

---

## Управление сертификатами и доверием

### Корневые trust anchors

Trust anchors — это корневые CA-сертификаты, на которых основано доверие всего меша. Они хранятся в ConfigMap `istio-ca-root-cert` в `istio-system`.

**Проверка trust anchors:**
```bash
kubectl get configmap istio-ca-root-cert -n istio-system -o jsonpath='{.data["root-cert.pem"]}' | openssl x509 -noout -subject -issuer -dates
```

### Ротация trust anchors

Ротация промежуточных CA (certificate signing) происходит автоматически. Ротация корневых trust anchors требует ручного вмешательства:

1. Создайте новый корневой CA через `istioctl x create-credential`.
2. Обновите ConfigMap `istio-ca-root-cert` в каждом кластере (primary и remote).
3. Istiod автоматически перевыпустит все сертификаты на новый корень.
4. Старые сертификаты остаются валидными до истечения срока; Graceful rotation исклюжает простой.

**Пример ротации:**
```bash
# 1. Создание новых учетных данных
istioctl x create-credential --name=istiod --type=SelfSigned --namespace=istio-system

# 2. Проверка распространения
kubectl get configmap istio-ca-root-cert -n istio-system -o yaml

# 3. Проверка, что сертификаты подов обновились
istioctl proxy-config secret <pod> -n <ns> -o json | jq '.dynamicActiveSecrets[0].secret.tlsCertificate.certificateChain'
```

### Внешний CA (Vault / SPIRE / cert-manager)

Если используется внешний CA, настройте `MeshConfig` или `Citadel` для подключения к нему:

```yaml
apiVersion: install.istio.io/v1alpha1
kind: IstioOperator
spec:
  values:
    meshConfig:
      defaultConfig:
        tlsCerts:
          cert: /etc/istio/ca-certs/cert.pem
          key: /etc/istio/ca-certs/key.pem
      caCertificates:
      - pem: |
          -----BEGIN CERTIFICATE-----
          ...
          -----END CERTIFICATE-----
```

- **Vault / SPIRE**: интеграция через pluggable CA и trust anchors (см. [Zero Trust с HashiCorp Vault](../Vault/zero_trust.md)).
- **cert-manager как external CA для mTLS меша**: оформление и ротация mesh-CA выполняется через `Issuer`/`ClusterIssuer` (например, Let's Encrypt или внутренний CA), а полученные сертификаты подкладываются istiod. Практическое руководство — [Service Mesh Integration (cert-manager)](../Kubernetes/ToolsUtilities/cert_manager/Private_CA/service_mesh_integration.md).
- Межкластерное доверие при внешнем CA — см. [Мультикластерная архитектура Istio](./istio-multicluster.md).

---

## Практические сценарии

### Сценарий 1: Защита Gateway API

С 2026 года для mTLS между шлюзом (Gateway) и бэкендом используется `BackendTLSPolicy`.

```bash
# Примените BackendTLSPolicy для сервиса
cat <<EOF | kubectl apply -f -
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: BackendTLSPolicy
metadata:
  name: gateway-backend-tls
  namespace: prod
spec:
  targetRefs:
  - group: ""
    kind: Service
    name: my-api
    port: 443
  tls:
    mode: Mutual
    caCertificates:
    - name: mesh-ca
      group: ""
      kind: ConfigMap
EOF

# Проверка
kubectl get backendtlspolicy -n prod
```

### Сценарий 2: Мультикластерная федерация

При использовании нескольких кластеров сертификаты должны иметь общие корни доверия. Istio поддерживает федерацию через `MeshConfig` или внешние системы управления идентификацией (SPIRE Federation).

```bash
# Экспорт trust anchors из Primary кластера
kubectl get configmap istio-ca-root-cert -n istio-system -o jsonpath='{.data["root-cert.pem"]}' > root-cert.pem

# Импорт в Remote кластер
kubectl create configmap istio-ca-root-cert -n istio-system --from-file=root-cert.pem=root-cert.pem --dry-run=client -o yaml | kubectl apply -f -

# Проверка синхронизации
istioctl proxy-config secret <pod> -n <ns> | grep "validity"
```

### Сценарий 3: Изоляция системных компонентов

Защита `istiod` и других компонентов `istio-system` с помощью жестких политик `AuthorizationPolicy`, разрешающих доступ только из доверенных систем мониторинга (Prometheus, Kiali).

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: allow-prometheus-kiali
  namespace: istio-system
spec:
  selector:
    matchLabels:
      app: istiod
  action: ALLOW
  rules:
  - from:
    - source:
        namespaces: ["istio-system", "monitoring"]
    - source:
        principals: ["spiffe://cluster.local/ns/istio-system/sa/istiod"]
  - to:
    - operation:
        methods: ["GET"]
        paths: ["/metrics", "/debug/*"]
```

### Сценарий 4: Миграция с PERMISSIVE на STRICT mTLS

Поэтапное ужесточение политики без прерывания обслуживания:

```bash
# 1. Включите PERMISSIVE и сбор логов
kubectl apply -f - <<EOF
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: migrate-to-strict
  namespace: prod
spec:
  selector:
    matchLabels:
      app: my-app
  mtls:
    mode: PERMISSIVE
EOF

# 2. Проанализируйте трафик (временно включите access-логи)
kubectl logs -l app=my-app -c istio-proxy -n prod | grep -v "mTLS"

# 3. После устранения всех plaintext-источников переключите в STRICT
kubectl patch peerauthentication migrate-to-strict -n prod -p '{"spec":{"mtls":{"mode":"STRICT"}}}' --type=merge

# 4. Проверка
istioctl proxy-config secret deploy/my-app -n prod -o json | jq '.dynamicActiveSecrets[0].secret.tlsCertificate.certificateChain'
```

### Сценарий 5: JWT-защищенный API с ролями

Настройте проверку JWT и авторизацию на основе claims:

```bash
# 1. RequestAuthentication
cat <<EOF | kubectl apply -f -
apiVersion: security.istio.io/v1beta1
kind: RequestAuthentication
metadata:
  name: api-jwt
  namespace: prod
spec:
  selector:
    matchLabels:
      app: api-server
  jwtRules:
  - issuer: "https://keycloak.example.com/auth/realms/master"
    jwksUri: "https://keycloak.example.com/auth/realms/master/protocol/openid-connect/certs"
    audiences: ["my-api"]
EOF

# 2. AuthorizationPolicy с ролями
cat <<EOF | kubectl apply -f -
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: api-roles
  namespace: prod
spec:
  selector:
    matchLabels:
      app: api-server
  action: ALLOW
  rules:
  - to:
    - operation:
        methods: ["GET"]
        paths: ["/public/*"]
  - when:
    - key: request.auth.claims[role]
      values: ["admin", "editor"]
      to:
      - operation:
          methods: ["POST", "PUT", "DELETE"]
          paths: ["/api/*"]
EOF

# 3. Проверка с curl
TOKEN=$(curl -s -X POST "https://keycloak.example.com/auth/realms/master/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" -d "client_id=my-api" -d "client_secret=secret" | jq -r .access_token)
curl -H "Authorization: Bearer $TOKEN" https://api.example.com/api/resource
```

### Сценарий 6: Path-based доступ (L7 в Ambient)

Настройте доступ к конкретным путям через Waypoint:

```bash
# 1. Создайте Waypoint для неймспейса
istioctl waypoint apply -n prod --enroll-namespace

# 2. Примените L7-политику
cat <<EOF | kubectl apply -f -
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: path-restricted
  namespace: prod
spec:
  selector:
    matchLabels:
      app: inventory
  action: ALLOW
  rules:
  - to:
    - operation:
        paths: ["/api/v1/*", "/health"]
        methods: ["GET", "POST"]
  - from:
    - source:
        principals: ["spiffe://cluster.local/ns/prod/sa/billing-sa"]
        to:
        - operation:
            paths: ["/internal/*"]
EOF

# 3. Проверка
kubectl exec -n prod deploy/billing -- curl -s -o /dev/null -w "%{http_code}" http://inventory.prod/api/v1/items
# → 200
kubectl exec -n prod deploy/billing -- curl -s -o /dev/null -w "%{http_code}" http://inventory.prod/internal/secret
# → 403
```

### Сценарий 7: Отказ всех внешних вызовов (Default-Deny + явные разрешения)

```bash
# 1. Default-deny для всего неймспейса
cat <<EOF | kubectl apply -f -
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: default-deny
  namespace: prod
spec:
  {}
EOF

# 2. Разрешение только из того же неймспейса и из billing
cat <<EOF | kubectl apply -f -
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: allow-internal
  namespace: prod
spec:
  selector:
    matchLabels:
      app: inventory
  action: ALLOW
  rules:
  - from:
    - source:
        namespaces: ["prod"]
    - source:
        principals: ["spiffe://cluster.local/ns/prod/sa/billing-sa"]
EOF

# 3. Проверка
istioctl proxy-config cluster deploy/inventory -n prod | grep -E "outbound|9090"
```

### Сценарий 8: Внешняя авторизация через OPA/OPA Gatekeeper

Интеграция с внешним PDP через EnvoyFilter:

```bash
# Примените EnvoyFilter для ext-authz
cat <<EOF | kubectl apply -f -
apiVersion: networking.istio.io/v1alpha3
kind: EnvoyFilter
metadata:
  name: opa-ext-authz
  namespace: prod
spec:
  workloadSelector:
    labels:
      app: api-server
  configPatches:
  - applyTo: HTTP_FILTER
    match:
      context: SIDECAR_INBOUND
      listener:
        filterChain:
          filter:
            name: "envoy.filters.network.http_connection_manager"
    patch:
      operation: INSERT_BEFORE
      value:
        name: envoy.filters.http.ext_authz
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthz
          http_service:
            server_uri:
              uri: opa.prod.svc.cluster.local:8181
              cluster: opa
              timeout: 1s
            authorization_request:
              headers_to_add:
              - key: x-ext-authz
                value: "opa"
EOF

# Проверка: запрос без разрешения должен получить 403
curl -v http://api-server.prod/api/restricted
# → HTTP/1.1 403 Forbidden
```

### Сценарий 9: Ротация trust anchors без простоя

```bash
# 1. Создайте новые учетные данные
istioctl x create-credential --name=istiod --type=SelfSigned --namespace=istio-system

# 2. Проверьте, что ConfigMap обновился
kubectl get configmap istio-ca-root-cert -n istio-system -o jsonpath='{.data["root-cert.pem"]}' | openssl x509 -noout -serial -subject -dates

# 3. Проверьте, что поды получили новые сертификаты
istioctl proxy-config secret deploy/my-app -n prod -o json | jq '.dynamicActiveSecrets[0].secret.tlsCertificate.certificateChain.inlineBytes' | base64 -d | openssl x509 -noout -subject -issuer -dates

# 4. Убедитесь, что старое и новое сертификаты действуют одновременно (grace period)
istioctl proxy-config secret deploy/my-app -n prod -o json | jq '.dynamicActiveSecrets'
```

### Сценарий 10: Включение observability для нового сервиса

Настройте сбор метрик и трассировки для сервиса, только что добавленного в mesh:

```bash
# 1. Включите access-логи через Telemetry API
cat <<EOF | kubectl apply -f -
apiVersion: telemetry.istio.io/v1alpha1
kind: Telemetry
metadata:
  name: enable-access-logging
  namespace: my-app
spec:
  accessLogging:
  - providers:
    - name: envoy
  metrics:
  - providers:
    - name: prometheus
  tracing:
  - providers:
    - name: otel
EOF

# 2. Настройте PodMonitor для Prometheus
cat <<EOF | kubectl apply -f -
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: istio-proxy-metrics
  namespace: my-app
spec:
  selector:
    matchLabels:
      istio-injection: enabled
  podMetricsEndpoints:
  - port: 15090
    path: /stats/prometheus
EOF

# 3. Проверьте, что метрики появляются
kubectl exec -n my-app deploy/my-app -- curl -s localhost:15090/stats/prometheus | head -20
```

---

## Диагностика и отладка

### Команды проверки

| Команда | Назначение |
| :--- | :--- |
| **`istioctl analyze -A`** | Автоматический поиск конфликтов в политиках по всем неймспейсам. |
| **`istioctl proxy-config secret <pod>`** | Просмотр текущих mTLS сертификатов и их срока действия. |
| **`istioctl proxy-status`** | Проверка синхронизации политик с прокси-серверами (SYNCED / NOT SYNCED). |
| **`istioctl proxy-config all deploy/<name> -n <ns>`** | Полный дамп конфигурации прокси (listeners, routes, clusters, endpoints, secrets). |
| **`istioctl proxy-config cluster deploy/<name> -n <ns>`** | Проверка upstream-кластеров и outlier detection. |
| **`istioctl proxy-config route deploy/<name> -n <ns>`** | Проверка активных маршрутов, таймаутов и ретраев. |
| **`istioctl waypoint list -n <ns>`** | Список Waypoint прокси в неймспейсе. |
| **`istioctl experimental ambient describe pod <pod> -n <ns>`** | Описание сетевого пути пода в Ambient (Ztunnel, Waypoint, политики). |

### Логи

- **Ztunnel/Waypoint:** Анализ отказов по кодам `403 Forbidden` (AuthZ) или `Connection Reset` (AuthN).
- **istiod:** `kubectl logs -n istio-system -l app=istiod --tail=100`
- **CNI:** `kubectl logs -n istio-system -l app=istio-cni-node --tail=100`

---

## Аудит и compliance

### Аудит изменений Security-ресурсов (Kubernetes Audit)

Istio-ресурсы (`AuthorizationPolicy`, `PeerAuthentication`, `RequestAuthentication`, `Sidecar`) ходят через Kubernetes API-сервер, поэтому их можно отслеживать audit-логом.

```bash
# 1. AuditPolicy API-сервера: логировать все изменения istio-ресурсов
#    (пример фрагмента audit-policy.yaml)
cat <<EOF > audit-policy.yaml
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
- level: RequestResponse
  verbs: ["create", "update", "patch", "delete"]
  resources:
  - group: "security.istio.io"
    resources: ["authorizationpolicies", "peerauthentications", "requestauthentications"]
  - group: "networking.istio.io"
    resources: ["sidecars", "serviceentries", "virtualservices", "destinationrules"]
EOF

# 2. Проверка, что файл подхвачен API-сервером (kube-apiserver)
kubectl get pods -n kube-system -o wide | grep kube-apiserver

# 3. Выборка событий из audit-backend (Loki/EFK): запросы к security.istio.io
#    Пример запроса: {resource="authorizationpolicies"} HTTP PATCH → кто и когда изменил
```

### Инвентаризация политик по кластеру

```bash
# Все AuthorizationPolicy с пользователем-создателем (kube 1.31+ можно через field manager)
kubectl get authorizationpolicies -A -o json \
  | jq -r '.items[] | "\(.metadata.namespace)/\(.metadata.name) managedFields=\(.metadata.managedFields[0].manager) action=\(.spec.action)"'

# PeerAuthentication: проверка, что premissive/STRICT заданы явно
kubectl get peerauthentications -A -o json | jq -r '.items[].metadata.namespace + "/" + .metadata.name'

# Sidecar-скопинг (что видит каждый namespace)
kubectl get sidecars -A
```

### Проверка соответствия требованиям

`istioctl analyze -A` выявляет конфликты политик и небезопасные сочетания (например, PERMISSIVE поверх STRICT, отсутствующие selectors). Для compliance-отчётов готовьте доказательную базу:

| Контроль (пример) | Как доказывается | Источник |
| :--- | :--- | :--- |
| mTLS STRICT | `PeerAuthentication` + % mTLS-запросов = 100 | Prometheus `istio_requests_total{security_policy}` |
| Default-deny | Есть `AuthorizationPolicy` (пустой) в каждом ns | `kubectl get authorizationpolicies -A` |
| Краткосрочные сертификаты | Средний `certificate_validity` сертификатов | `istioctl proxy-config secret` |
| Traceability изменений | Audit-лог API-сервера по `security.istio.io` | audit-backend |
| Сегментация по namespace | NetworkPolicy + `Sidecar` egress scoping | CRD + Envoy config dump |

---

## Типичные ошибки и устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **mTLS handshake failure** | `PeerAuthentication: STRICT` на сервере, а клиент не имеет сайдкара | Проверьте инъекцию на namespace отправителя; временно переведите в `PERMISSIVE` для диагностики |
| **Pods не получают IP из меша** | CNI не перехватывает трафик | Проверьте метку `istio.io/dataplane-mode=ambient`; проверьте логи `istio-cni-node` |
| **Waypoint не создаётся** | Нет Gateway API CRD или недостаточно прав | Установите CRD: `kubectl get crd gateways.gateway.networking.k8s.io`; проверьте RBAC istiod |
| **Высокий CPU на ноде от Ztunnel** | Конфликт правил iptables/nftables | Переключите на `nftables` (`values.global.nativeNftables=true`); проверьте количество правил: `iptables -L -t nat -v | wc -l` |
| **Сервис не обнаруживается (No Healthy Upstream)** | Эндпоинт не Ready или отсутствует в `egress.hosts` ресурса `Sidecar` | Проверьте readiness probe; добавьте namespace в `Sidecar.egress.hosts` |
| **Сертификат истёк / mTLS не работает** | CA недоступен или trust bundle устарел | Проверьте `istioctl proxy-config secret`; перевыпустите trust anchors через `istioctl x create-credential` |
| **xDS не синхронизируется (NOT SYNCED)** | istiod перегружен или сетевой разрыв | Проверьте ресурсы istiod; убедитесь в отсутствии NetworkPolicy между istiod и подами |
| **Зависание Pod при удалении (Terminating)** | Sidecar не завершается вовремя | Увеличьте `terminationGracePeriodSeconds` до 60s; проверьте `preStop` хук |
| **Access-логи не пишутся** | Telemetry API не настроен или уровень логирования выключен | Примените ресурс `Telemetry` с `accessLogging`; проверьте `kubectl logs -c istio-proxy` |
| **JWT не проверяется (401 без логов)** | `RequestAuthentication` не совпадает с селектором пода | Проверьте метки пода; убедитесь, что `jwksUri` доступен из кластера |
| **L7-политика не применяется в Ambient** | Waypoint не создан или неймспейс не подписан на него | `istioctl waypoint list -n <ns>`; проверьте метку `istio.io/use-waypoint` |
| **AuthorizationPolicy позволяет больше, чем нужно** | Правило `ALLOW` слишком широкое (например, пустой `selector`) | Уточните `selector`, `from` и `to`; проверьте через `istioctl proxy-config all` |

---

## Лучшие практики эксплуатации

1.  **Ресурсные квоты:** всегда устанавливайте `requests` и `limits` для сайдкаров. В 2026 году Envoy требует ~0.5 vCPU и 50MB RAM на 1,000 RPS. Для Ztunnel (Ambient) используйте `requests.cpu: 50m` и `requests.memory: 64Mi` как минимум.
2.  **Стандартизация на Gateway API (GAMMA):** в новых проектах используйте `HTTPRoute` вместо `VirtualService`/`ServiceProfile` для обеспечения переносимости между мешами. Учитывайте поведение «reject by default» при привязке роута к `Service`.
3.  **Scoping конфигурации:** используйте ресурс `Sidecar` (Istio) или `ServiceProfile` (Linkerd) для ограничения списка сервисов, о которых знает прокси. Это критично для снижения потребления RAM в больших кластерах.
4.  **Градуальное внедрение:** начинайте с Ambient L4 (mTLS) для всего кластера, затем добавляйте Waypoint Proxy только для сервисов, требующих L7. При переходе с Sidecar оставляйте оба режима параллельно 2–4 недели.
5.  **Мониторинг Ztunnel:** настраивайте алерты на использование ресурсов Ztunnel, так как он обслуживает все поды на ноде. Норма: CPU < 200m, Memory < 256Mi на узел.
6.  **eBPF-акселерация:** включайте SOCKMAP (Istio CNI / Cilium) для обхода TCP-стека ядра. Снижает задержки на 15–20%. Приоритетен для новых инсталляций `nftables` над `iptables`.
7.  **Сертификаты:** настройте автоматическую ротацию trust anchors перед истечением срока (рекомендуемый срок — 90 дней для промежуточных CA). Используйте `istioctl proxy-config secret` для проверки.
8.  **Валидация после изменений:** после изменения ресурсов выполняйте `istioctl analyze` и `istioctl proxy-status` для подтверждения распространения конфигурации.
9.  **Бэкап конфигурации:** регулярно экспортируйте ресурсы меша и ConfigMap `istio` в `istio-system`. Храните бэкапы вне кластера.
10. **Изоляция сред:** разделяйте кластеры по окружениям (dev/staging/prod) разными неймспейсами или отдельными кластерами. Istio не предоставляет встроенной изоляции между окружениями внутри одного кластера на уровне Control Plane.
11. **Namespace-scoped политики:** применяйте `AuthorizationPolicy` на уровне неймспейса для default-deny, а на уровне workload — для исключений. Это снижает количество ресурсов и упрощает аудит.
12. **Проверка селекторов:** перед применением `AuthorizationPolicy` проверяйте метки пода (`kubectl get pod <pod> --show-labels`), чтобы политика не была применена к unintended workload.

---

## Дополнительная информация

### Операционные аспекты (2026)

1.  **Sidecar Tax (Налог на сайдкар):** даже с оптимизациями добавление прокси увеличивает задержку. В 2026 году это решается через переход на **Ambient Mesh** (Ztunnel + Waypoint) или использование **eBPF-акселерации** (SOCKMAP-обход TCP/IP-стека ядра, снижение задержек на 15–20%).
2.  **Ресурсное планирование:** прокси потребляют память и CPU. В Sidecar-модели это может составлять до 10–15% ресурсов кластера. Ambient Mesh снижает этот показатель до 1–3%.
3.  **Управление сертификатами:** ротация сертификатов mTLS происходит автоматически (обычно раз в 24 часа), что исключает риски простоя из-за истечения срока действия.
4.  **Планирование емкости провайдеров (Capacity Planning):** в мультикластерных конфигурациях важно учитывать overhead Control Plane (например, Istiod) и резервировать ресурсы для распределенной трассировки.
5.  **Совместимость с существующими сервисами:** при интеграции mesh с устаревшими системами (VM, внешние базы данных) настройте исключения из mTLS/проксирования через `ServiceEntry` (Istio) или явные политики, чтобы не потерять связность.

### Актуальность

Основной тренд 2026 года — **унификация**. Использование Gateway API (GAMMA) позволяет переключаться между Istio, Linkerd и Cilium без полной переработки манифестов управления трафиком. Наблюдаемые тренды: переход от Sidecar к Ambient/eBPF-моделям, конвергенция с CNI через eBPF. SMI (Service Mesh Interface, ресурсы `TrafficSplit`) считается устаревшим — функция перехвачена Gateway API/GAMMA.

### См. также

- [Архитектура Istio и режим Ambient](./istio_architecture.md)
- [Наблюдаемость в Istio](./istio_observability_and_tools.md)
- [Zero Trust с HashiCorp Vault](../Vault/zero_trust.md)
- [SPIFFE.io](https://spiffe.io/) — официальная спецификация идентификации.
- [Интеграция виртуальных машин (VM Workloads) в Istio](./istio_vm_workloads.md)
- [Мультикластерная архитектура Istio](./istio-multicluster.md)
- [cert-manager как external CA для mTLS](../Kubernetes/ToolsUtilities/cert_manager/Private_CA/service_mesh_integration.md)

Документация: [Istio Security Overview](https://istio.io/latest/docs/concepts/security/).
