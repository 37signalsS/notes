# Kiali и Dex: визуализация и аутентификация в Istio

## Определения

**Kiali** — веб-интерфейс для [Service Mesh](./service_mesh_concepts.md) Istio, предоставляющий визуализацию топологии сервисов, мониторинг трафика и частичное управление конфигурациями Istio. Установка не обязательна, но полезна для наглядного представления работы mesh-сети.

**Dex** — легковесный провайдер Identity и OpenID Connect (OIDC) для федерации аутентификации из различных источников (LDAP, SAML, GitHub и др.) и предоставления OIDC-совместимого интерфейса. В контексте Istio Dex применяется для организации безопасного доступа к Kiali вместо анонимного режима. Альтернативы — [Keycloak](../Security/Tools/keycloak_overview.md), oauth2-proxy, Authelia.

---

## Основные концепции

### Зависимости Kiali

| Компонент | Обязательность | Назначение |
| :--- | :--- | :--- |
| **Prometheus** (или VictoriaMetrics) | **Обязателен** | Сбор и хранение метрик для графиков и состояния сервисов. Подробнее: [Prometheus Service Discovery](../Prometheus/service_discovery_and_relabeling.md). |
| **Grafana** | Рекомендуется | Расширенные дашборды ([концепции дашбордов](../Grafana/dashboards/definitions_and_concepts.md), [установка через Helm](../Grafana/Installation/grafana_helm_installation.md)). |
| **Трейсинг-система** (Jaeger, Tempo) | Опциональна | Визуализация трейсов запросов. |
| **Istio** | **Обязателен** | Kiali работает только с Istio Service Mesh. |

### Возможности визуализации

Kiali предоставляет карту (`traffic graph`) взаимодействия сервисов с визуальными индикаторами:

| Индикатор | Описание | Пример |
| :--- | :--- | :--- |
| **Тип трафика** | Соединения отображаются разными цветами. | В Ambient-режиме: синие стрелки — L4-трафик (Ztunnel), зелёные — L7-трафик (Waypoint Proxy). |
| **Безопасность (mTLS)** | Зашифрованные mTLS-соединения помечаются иконкой замка. | Быстрая оценка защищённого трафика. |
| **Идентификаторы (Principals)** | При выборе соединения Kiali показывает `principal` (ServiceAccount источника и назначения). | Отладка [AuthorizationPolicy](./istio_architecture.md). |
| **Ошибки и задержки** | Проблемные соединения подсвечиваются красным или оранжевым. | Высокий процент ошибок или увеличение задержек. |
| **Gateway API** | Визуализация `HTTPRoute`, `Gateway`, `BackendRef`. | Отображение правил маршрутизации ([управление трафиком](./traffic_management.md)). |

### Модели доступа к Kiali

| Стратегия | Описание | Рекомендация |
| :--- | :--- | :--- |
| **`anonymous`** | Анонимный доступ по умолчанию. | ❌ Не рекомендуется для production и test. |
| **`openid`** | Интеграция с OIDC-провайдером (Dex, Keycloak). | ✅ Рекомендуется для безопасного доступа. |
| **`header`** | Аутентификация через внешний прокси (oauth2-proxy). | Для сложных сценариев SSO. |
| **`token`** | Доступ через Kubernetes ServiceAccount tokens. | Для администраторов. |

---

## Практические сценарии

### Установка Kiali с аутентификацией через Dex

Развёртывание полного стека observability для Istio с использованием [Gateway API](../Kubernetes/Networking/gateway_api/practical_basic.md) и безопасным доступом к Kiali.

#### Шаг 1: подготовка (сертификаты и Gateway)

Предполагается установленный `cert-manager` (см. [Ingress overview](../Kubernetes/Networking/Ingress/overview.md)).

1. **TLS-сертификат** для всех веб-интерфейсов (Kiali, Grafana, Prometheus, Dex):

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: kiali-gateway-tls
  namespace: istio-system
spec:
  secretName: kiali-gateway-tls
  dnsNames:
  - kiali.local
  - prometheus.local
  - grafana.local
  - dex.local
  issuerRef:
    name: your-cluster-issuer
    kind: ClusterIssuer
```

1. **Gateway** для инструментов мониторинга (HTTPS, порт 443):

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: kiali-support-gateway
  namespace: istio-system
spec:
  gatewayClassName: istio
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: kiali-gateway-tls
    allowedRoutes:
      namespaces:
        from: All
```

#### Шаг 2: установка зависимостей (Prometheus и Grafana)

1. **Prometheus**: установка через Helm с `scrape_configs` для компонентов Istio (istiod, envoy, ztunnel, waypoint). Доступ через `HTTPRoute`:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: prometheus-route
  namespace: monitoring
spec:
  parentRefs:
  - name: kiali-support-gateway
    namespace: istio-system
  hostnames: ["prometheus.local"]
  rules:
  - backendRefs:
    - name: prometheus-server-service
      port: 80
```

1. **Grafana**: установка через Helm, создание `HTTPRoute` «из коробки», определение `dataSource` в `values.yaml`.

#### Шаг 3: установка и настройка Dex

Dex разворачивается как отдельное приложение в кластере.

**Конфигурация Dex (`ConfigMap`):**

- **Storage**: Kubernetes (CRD) как бэкенд.
- **Static Users**: для тестового сценария — статические пользователи. Пароль хранится как bcrypt-хэш.
- **Static Clients**: клиент `kiali` с `redirectURIs` и секретом.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: dex
  namespace: auth
data:
  config.yaml: |
    issuer: https://dex.local
    storage:
      type: kubernetes
      config:
        inCluster: true
    web:
      http: 0.0.0.0:5556
    staticPasswords:
    - email: "user@example.com"
      hash: "$2a$10$..." # bcrypt-хэш пароля
      username: "artur"
      userID: "08a8684b-db2e-4246-a3b1-1d44a839a89c"
    staticClients:
    - id: kiali
      redirectURIs:
      - 'https://kiali.local/api/auth/login/oidc/callback'
      name: 'Kiali'
      secret: "$CLIENT_SECRET_FROM_K8S_SECRET"
```

Доступ к Dex публикуется через `HTTPRoute`, привязанный к `kiali-support-gateway`.

#### Шаг 4: установка и настройка Kiali

1. **Секрет для OIDC-клиента:**

```bash
kubectl create secret generic kiali-oidc-secret \
  --from-literal=client_secret='your-client-secret' \
  -n istio-system
```

1. **Конфигурация Kiali (`values.yaml` для Helm):**

```yaml
auth:
  strategy: openid
  openid:
    client_id: kiali
    issuer_uri: https://dex.local
    insecure_skip_verify_tls: true  # для самоподписанных сертификатов Dex
    disable_rbac: true              # отключение RBAC на основе токенов Dex
    username_claim: email

external_services:
  prometheus:
    url: "http://prometheus-server.monitoring.svc.cluster.local:80"
  grafana:
    enabled: true
    url: "http://grafana.monitoring.svc.cluster.local:3000"
    in_cluster_url: "http://grafana.monitoring.svc.cluster.local:3000"
  tracing:
    enabled: true
    url: "http://jaeger-query.istio-system.svc.cluster.local:16686"

kiali_feature_flags:
  clustering:
    enabled: true
  validation:
    enabled: true
```

1. **Публикация Kiali через `HTTPRoute`:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: kiali-route
  namespace: istio-system
spec:
  parentRefs:
  - name: kiali-support-gateway
  hostnames: ["kiali.local"]
  rules:
  - backendRefs:
    - name: kiali
      port: 20001
```

После применения конфигураций доступ к `https://kiali.local` перенаправляет на страницу логина Dex. После аутентификации пользователь возвращается в Kiali.

---

## Дополнительная информация

### Kiali v2.x: возможности

- **Ambient Mesh Visualization**: поддержка Ztunnel и Waypoint Proxy, разделение L4/L7 трафика.
- **Gateway API Support**: визуализация `HTTPRoute`, `Gateway`, `BackendRef`.
- **External Kiali**: централизованное управление observability для мультикластерных развёртываний.
- **Производительность**: pre-compute и кэширование health status (по умолчанию с v2.22).
- **Валидация**: автоматическое обнаружение ошибок в конфигурациях Istio.

### Рекомендации по эксплуатации

1. Helm-чарты для автоматизации установки.
2. Тестирование на non-production перед production.
3. Документирование всех кастомных конфигураций.
4. Мониторинг Kiali и его зависимостей (Prometheus, Dex).
5. Интеграция компонентов — нетривиальная задача; требуется понимание каждого: [cert-manager](../Kubernetes/Networking/Ingress/overview.md), [Gateway API](../Kubernetes/Networking/gateway_api/practical_basic.md), Prometheus, Grafana, Dex, Kiali.
