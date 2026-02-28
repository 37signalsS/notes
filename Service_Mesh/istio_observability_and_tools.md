# Kiali и Dex: Визуализация и Аутентификация в Istio

## 1. Определения

**Kiali** — это веб-интерфейс (веб-морда) для Service Mesh Istio, предоставляющий возможности для визуализации топологии сервисов, мониторинга трафика и частичного управления конфигурациями Istio. Установка Kiali не является обязательной, но крайне полезна для наглядного представления работы mesh-сети.

**Dex** — это легковесный провайдер Identity и OpenID Connect (OIDC), который используется для федерации аутентификации из различных источников (LDAP, SAML, GitHub и др.) и предоставления OIDC-совместимого интерфейса для приложений. В контексте Istio, Dex часто применяется для организации безопасного, аутентифицированного доступа к Kiali, вместо небезопасного анонимного режима.

## 2. Базовые Концепты

### Зависимости Kiali

Для полноценной работы Kiali требуются следующие компоненты в кластере:

- **Prometheus (или совместимый аналог, например, VictoriaMetrics):** Обязателен для сбора и хранения метрик, на основе которых Kiali строит графики и отображает состояние сервисов.
- **Grafana:** Опциональна, но рекомендуется для создания расширенных дашбордов и глубокого анализа метрик.
- **Трейсинг-система (Jaeger, Tempo):** Опциональна, для визуализации трейсов запросов.

### Возможности визуализации

Kiali предоставляет наглядную карту (`traffic graph`) взаимодействия сервисов, используя ряд визуальных индикаторов:

- **Тип трафика:** Соединения отображаются разными цветами. Например, в Ambient-режиме синие стрелки могут обозначать L4-трафик, обрабатываемый `Ztunnel`, а зеленые — L7-трафик, проходящий через `Waypoint Proxy`.
- **Безопасность (mTLS):** Зашифрованные с помощью mTLS соединения помечаются иконкой замка. Это позволяет быстро оценить, какой трафик в сетке защищен, а какой — нет.
- **Идентификаторы (Principals):** При выборе соединения Kiali показывает, от какого `principal` (ServiceAccount источника) и к какому `principal` (ServiceAccount назначения) идет трафик, что критически важно для отладки политик `AuthorizationPolicy`.
- **Ошибки и задержки:** Kiali подсвечивает проблемные соединения красным или оранжевым цветом, указывая на высокий процент ошибок или увеличение задержек.

### Модели доступа к Kiali

1.  **`anonymous` (Анонимный доступ):** Стратегия по умолчанию во многих примерах. **Крайне не рекомендуется** для производственных или даже тестовых сред, так как предоставляет неконтролируемый доступ к панели управления Service Mesh.
2.  **`openid` (OpenID Connect):** Рекомендуемая стратегия для безопасного доступа. Kiali интегрируется с OIDC-провайдером (например, Dex, Keycloak), который отвечает за аутентификацию пользователей.
3.  **`header` (Аутентификация через заголовки):** Используется, когда перед Kiali стоит внешний прокси (например, `oauth2-proxy`), который выполняет аутентификацию и передает информацию о пользователе в HTTP-заголовках.

## 3. Практический Сценарий: Установка Kiali с аутентификацией через Dex

Данный сценарий описывает развертывание полного стека observability для Istio с использованием Gateway API и безопасным доступом к Kiali.

### Шаг 1: Подготовка (Сертификаты и Gateway)

Предполагается, что в кластере уже установлен `cert-manager`.

1.  **Создание TLS-сертификата:** Для защиты всех веб-интерфейсов (Kiali, Grafana, Prometheus, Dex) создается единый сертификат, который будет обслуживать несколько доменных имен.

    ```yaml
    # Фрагмент ClusterIssuer или Issuer
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

2.  **Создание выделенного Gateway:** Для инструментов мониторинга создается отдельный `Gateway`, который будет слушать только HTTPS-трафик (порт 443) и использовать созданный сертификат.

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

1.  **Prometheus:** Устанавливается через Helm. Важно убедиться, что его конфигурация скрайпинга (`scrape_configs`) охватывает все необходимые компоненты Istio. Доступ к веб-интерфейсу Prometheus организуется через `HTTPRoute`.

    ```yaml
    # Пример HTTPRoute для Prometheus
    apiVersion: gateway.networking.k8s.io/v1
    kind: HTTPRoute
    metadata:
      name: prometheus-route
      namespace: monitoring # Namespace, где установлен Prometheus
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

2.  **Grafana:** Устанавливается через Helm. Современные чарты Grafana поддерживают создание `HTTPRoute` "из коробки". Также в `values.yaml` можно сразу определить `dataSource` для подключения к Prometheus.

### Шаг 3: Установка и настройка Dex

Dex разворачивается как отдельное приложение в кластере.

1.  **Конфигурация Dex (`ConfigMap`):**
    *   **Storage:** В качестве бэкенда для хранения данных используется сам Kubernetes (CRD).
    *   **Static Users:** Для тестового сценария пользователи определяются статически прямо в конфигурации. **Внимание:** Пароль хранится в виде bcrypt-хэша.
    *   **Static Clients:** Определяется клиент `kiali` с его `redirectURIs` и секретом.

    ```yaml
    # Фрагмент ConfigMap для Dex
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

2.  **Публикация Dex:** Доступ к Dex организуется через `HTTPRoute`, привязанный к ранее созданному `kiali-support-gateway`.

### Шаг 4: Установка и настройка Kiali

1.  **Создание секрета для OIDC клиента:** Kiali ожидает секрет с паролем клиента, который был определен в конфигурации Dex.

    ```bash
    kubectl create secret generic kiali-oidc-secret 
      --from-literal=client_secret='your-client-secret' 
      -n istio-system
    ```

2.  **Конфигурация Kiali (`values.yaml` для Helm):**
    *   **Аутентификация:** Устанавливается стратегия `openid`.
    *   **Конфигурация OpenID:** Указываются `client_id`, `issuer_uri` (адрес Dex). Важно установить `insecure_skip_verify_tls: true` при использовании самоподписанных сертификатов для Dex.
    *   **Внешние сервисы:** Прописываются внутренние URL для доступа Kiali к Prometheus и Grafana.
    *   **Доступ к кластеру:** Поскольку кластер Kubernetes не был изначально настроен на работу с OIDC, необходимо отключить RBAC на основе токенов Dex с помощью флага `disable_rbac: true`.

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
    
    # ... и другие настройки
    ```

3.  **Публикация Kiali:** Как и другие компоненты, Kiali публикуется наружу с помощью `HTTPRoute`.

После применения всех конфигураций доступ к `https://kiali.local` будет перенаправлять на страницу логина Dex. После успешной аутентификации пользователь будет возвращен в Kiali.

## 4. Дополнительная информация

- **Сложность настройки:** Интеграция всех компонентов (Cert-Manager, Gateway API, Prometheus, Grafana, Dex, Kiali) является нетривиальной задачей и требует хорошего понимания каждого из них.
- **Документация:** Документация по Kiali и Dex может быть не всегда исчерпывающей, что требует дополнительного исследования ("режим шахтера") для решения специфических проблем интеграции.
