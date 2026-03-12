# Kiali и Dex: Визуализация и Аутентификация в Istio

## Определения

**Kiali** — веб-интерфейс для Service Mesh Istio, предоставляющий возможности для визуализации топологии сервисов, мониторинга трафика и частичного управления конфигурациями Istio. Установка Kiali не является обязательной, но крайне полезна для наглядного представления работы mesh-сети.

**Dex** — легковесный провайдер Identity и OpenID Connect (OIDC), который используется для федерации аутентификации из различных источников (LDAP, SAML, GitHub и др.) и предоставления OIDC-совместимого интерфейса для приложений. В контексте Istio, Dex часто применяется для организации безопасного, аутентифицированного доступа к Kiali, вместо небезопасного анонимного режима.

---

## Основные концепты

### Зависимости Kiali

Для полноценной работы Kiali требуются следующие компоненты в кластере:

| Компонент | Обязательность | Назначение |
| :--- | :--- | :--- |
| **Prometheus** (или VictoriaMetrics) | **Обязателен** | Сбор и хранение метрик для графиков и состояния сервисов. |
| **Grafana** | Рекомендуется | Расширенные дашборды и глубокий анализ метрик. |
| **Трейсинг-система** (Jaeger, Tempo) | Опциональна | Визуализация трейсов запросов. |
| **Istio** | **Обязателен** | Kiali работает только с Istio Service Mesh. |

### Возможности визуализации

Kiali предоставляет наглядную карту (`traffic graph`) взаимодействия сервисов, используя ряд визуальных индикаторов:

| Индикатор | Описание | Пример |
| :--- | :--- | :--- |
| **Тип трафика** | Соединения отображаются разными цветами. | В Ambient-режиме: синие стрелки — L4-трафик (`Ztunnel`), зеленые — L7-трафик (`Waypoint Proxy`). |
| **Безопасность (mTLS)** | Зашифрованные с помощью mTLS соединения помечаются иконкой замка. | Позволяет быстро оценить, какой трафик защищен. |
| **Идентификаторы (Principals)** | При выборе соединения Kiali показывает `principal` (ServiceAccount источника и назначения). | Критично для отладки `AuthorizationPolicy`. |
| **Ошибки и задержки** | Проблемные соединения подсвечиваются красным или оранжевым цветом. | Высокий процент ошибок или увеличение задержек. |
| **Gateway API** | Визуализация `HTTPRoute`, `Gateway`, `BackendRef`. | Отображение правил маршрутизации. |

### Модели доступа к Kiali

| Стратегия | Описание | Рекомендация |
| :--- | :--- | :--- |
| **`anonymous`** | Анонимный доступ по умолчанию. | ❌ **Крайне не рекомендуется** для production и test. |
| **`openid`** | Интеграция с OIDC-провайдером (Dex, Keycloak). | ✅ **Рекомендуется** для безопасного доступа. |
| **`header`** | Аутентификация через внешний прокси (oauth2-proxy). | Для сложных сценариев с SSO. |
| **`token`** | Доступ через Kubernetes ServiceAccount tokens. | Для администраторов. |

---

## Практический Сценарий: Установка Kiali с аутентификацией через Dex

Данный сценарий описывает развертывание полного стека observability для Istio с использованием Gateway API и безопасным доступом к Kiali.

### Шаг 1: Подготовка (Сертификаты и Gateway)

Предполагается, что в кластере уже установлен `cert-manager` (см. [Интеграция с Ingress](../../Kubernetes/ToolsUtilities/cert_manager/ingress/overview.md) или [Gateway API](../../Kubernetes/ToolsUtilities/cert_manager/gateway_api/definitions.md)).

1. **Создание TLS-сертификата:** Для защиты всех веб-интерфейсов (Kiali, Grafana, Prometheus, Dex) создается единый сертификат, который будет обслуживать несколько доменных имен.

    ```yaml
    # Фрагмент Certificate для ClusterIssuer
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

2. **Создание выделенного Gateway:** Для инструментов мониторинга создается отдельный `Gateway`, который будет слушать только HTTPS-трафик (порт 443) и использовать созданный сертификат.

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

### Шаг 2: Установка зависимостей (Prometheus и Grafana)

1. **Prometheus:** Устанавливается через Helm. Важно убедиться, что его конфигурация скрайпинга (`scrape_configs`) охватывает все необходимые компоненты Istio (istiod, envoy, ztunnel, waypoint). Доступ к веб-интерфейсу Prometheus организуется через `HTTPRoute`.

    ```yaml
    # Пример HTTPRoute для Prometheus
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

2. **Grafana:** Устанавливается через Helm. Современные чарты Grafana поддерживают создание `HTTPRoute` "из коробки". Также в `values.yaml` можно сразу определить `dataSource` для подключения к Prometheus.

### Шаг 3: Установка и настройка Dex

Dex разворачивается как отдельное приложение в кластере.

1. **Конфигурация Dex (`ConfigMap`):**
    * **Storage:** В качестве бэкенда для хранения данных используется сам Kubernetes (CRD).
    * **Static Users:** Для тестового сценария пользователи определяются статически прямо в конфигурации. **Внимание:** Пароль хранится в виде bcrypt-хэша.
    * **Static Clients:** Определяется клиент `kiali` с его `redirectURIs` и секретом.

    ```yaml
    # Фрагмент ConfigMap для Dex
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
          hash: "$2a$10$..." # Bcrypt hash of the password
          username: "artur"
          userID: "08a8684b-db2e-4246-a3b1-1d44a839a89c"
        staticClients:
        - id: kiali
          redirectURIs:
          - 'https://kiali.local/api/auth/login/oidc/callback'
          name: 'Kiali'
          secret: "$CLIENT_SECRET_FROM_K8S_SECRET"
    ```

2. **Публикация Dex:** Доступ к Dex организуется через `HTTPRoute`, привязанный к ранее созданному `kiali-support-gateway`.

### Шаг 4: Установка и настройка Kiali

1. **Создание секрета для OIDC клиента:** Kiali ожидает секрет с паролем клиента, который был определен в конфигурации Dex.

    ```bash
    kubectl create secret generic kiali-oidc-secret \
      --from-literal=client_secret='your-client-secret' \
      -n istio-system
    ```

2. **Конфигурация Kiali (`values.yaml` для Helm):**
    * **Аутентификация:** Устанавливается стратегия `openid`.
    * **Конфигурация OpenID:** Указываются `client_id`, `issuer_uri` (адрес Dex). Важно установить `insecure_skip_verify_tls: true` при использовании самоподписанных сертификатов для Dex.
    * **Внешние сервисы:** Прописываются внутренние URL для доступа Kiali к Prometheus и Grafana.
    * **Доступ к кластеру:** Поскольку кластер Kubernetes не был изначально настроен на работу с OIDC, необходимо отключить RBAC на основе токенов Dex с помощью флага `disable_rbac: true`.

    ```yaml
    # Фрагмент values.yaml для Kiali
    auth:
      strategy: openid
      openid:
        client_id: kiali
        # Секрет клиента будет взят из kiali-oidc-secret
        issuer_uri: https://dex.local
        insecure_skip_verify_tls: true
        disable_rbac: true
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

3. **Публикация Kiali:** Как и другие компоненты, Kiali публикуется наружу с помощью `HTTPRoute`.

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

После применения всех конфигураций доступ к `https://kiali.local` будет перенаправлять на страницу логина Dex. После успешной аутентификации пользователь будет возвращен в Kiali.

---

## Дополнительная информация

### Kiali v2.x: Новые возможности

* **Ambient Mesh Visualization:** Полная поддержка Ztunnel и Waypoint Proxy, разделение L4/L7 трафика.
* **Gateway API Support:** Визуализация `HTTPRoute`, `Gateway`, `BackendRef`.
* **External Kiali:** Централизованное управление observability для мультикластерных развертываний.
* **Улучшенная производительность:** Оптимизация запросов к Prometheus, кэширование.
* **Расширенная валидация:** Автоматическое обнаружение ошибок в конфигурациях Istio.

### Сложность настройки

Интеграция всех компонентов (Cert-Manager [ingress.md](../../Kubernetes/ToolsUtilities/cert_manager/ingress/overview.md), Gateway API [gateway_api.md](../../Kubernetes/ToolsUtilities/cert_manager/gateway_api/definitions.md), Prometheus, Grafana, Dex, Kiali) является нетривиальной задачей и требует хорошего понимания каждого из них.

**Рекомендации:**

1. Используйте Helm-чарты для автоматизации установки.
2. Тестируйте на non-production окружении перед production.
3. Документируйте все кастомные конфигурации.
4. Мониторьте сам Kiali и его зависимости (Prometheus, Dex).

### Альтернативы Dex

| Провайдер | Преимущества | Недостатки |
| :--- | :--- | :--- |
| **Keycloak** | Полноценный IAM, поддержка SAML/OIDC, богатый UI. | Высокое потребление ресурсов, сложность. |
| **oauth2-proxy** | Простая интеграция с GitHub/Google, легковесный. | Меньше функций, чем у Dex. |
| **Authelia** | Легковесный, поддержка 2FA, простой UI. | Меньше интеграций, чем у Dex. |

### Источники и документация

* **[Официальная документация Kiali](https://kiali.io/docs/)** — полное руководство по установке и настройке.
* **[External Kiali](https://kiali.io/docs/configuration/multi-cluster/external/)** — централизованное observability для мультикластера.
* **[Istio Observability with Kiali](https://oneuptime.com/blog/post/2026-02-09-istio-kiali-observability/view)** — практическое руководство.

### Связанные документы

* **Базовые концепции:** [Service Mesh Concepts](./service_mesh_concepts.md)
* **Архитектура:** [Istio Architecture](./istio_architecture.md)
* **Трафик:** [Traffic Management](./traffic_management.md)
* **Grafana:** [Grafana Dashboards](../Grafana/dashboards/definitions_and_concepts.md), [Grafana Helm Installation](../Grafana/Installation/grafana_helm_installation.md)
* **Prometheus:** [Prometheus Service Discovery](../Prometheus/service_discovery_and_relabeling.md)
