# Интеграция cert-manager с Gateway API: Практические сценарии

## Определения

**Терминация TLS (TLS Termination)** — режим работы шлюза, при котором зашифрованный трафик расшифровывается на уровне Gateway и передается бэкенд-сервисам в открытом или перешифрованном виде. Основной метод интеграции с cert-manager.

**Сквозное шифрование (TLS Passthrough)** — режим, при котором TLS-трафик передается напрямую бэкенду без расшифровки на шлюзе (требуется `TLSRoute`). cert-manager в этом процессе на уровне шлюза не участвует.

**gateway-shim** — механизм в cert-manager, автоматически выпускающий сертификаты на основе аннотаций в ресурсах `Gateway`, `HTTPRoute` или `ListenerSet` (аналог Ingress-аннотаций).

**Wildcard-сертификат** — сертификат, выпускаемый для основного домена и всех его поддоменов первого уровня (например, `*.example.com`). В 2026 году для его получения обязателен метод DNS-01.

**ReferenceGrant** — ресурс безопасности Gateway API, разрешающий перекрестные ссылки между пространствами имен (например, когда Gateway в `infra` namespace использует Secret из `app` namespace).

---

## Основные концепции

### Подготовительные шаги (2025–2026)

Для реализации сценариев в современном окружении необходимо выполнить:

1.  **Установка Gateway API CRD (v1.1.0+):**
    ```bash
    kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.1.0/standard-install.yaml
    ```
2.  **Установка cert-manager (v1.20+):**
    Контроллер должен быть запущен с поддержкой Gateway API:
    ```bash
    # Helm параметр
    installCRDs: true
    extraArgs:
      - --enable-gateway-api=true
    ```
3.  **Создание ClusterIssuer:** Настроенный ACME (Let's Encrypt) или внутренний (Vault/PKI) эмитент.

### Архитектура интеграции

```mermaid
graph TD
    A[Certificate Resource] -->|создаёт| B[TLS Secret]
    B -->|ссылка в certificateRefs| C[Gateway Listener]
    D[Gateway Controller] -->|читает| C
    D -->|настраивает| E[Data Plane / Envoy / Cilium]
```

---

## Практические сценарии

### Сценарий 1: Базовый шлюз с явным ресурсом Certificate

**Цель:** Максимальный контроль над параметрами сертификата (алгоритмы, ротация, ARI).

**Certificate:**
```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: api-tls
  namespace: infra-system
spec:
  secretName: api-tls-secret
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - api.example.com
  privateKey:
    algorithm: ECDSA # Рекомендация 2026 года
    size: 256
```

**Gateway:**
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: public-gateway
  namespace: infra-system
spec:
  gatewayClassName: cilium
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    hostname: api.example.com
    tls:
      mode: Terminate
      certificateRefs:
      - name: api-tls-secret
        namespace: infra-system
  allowedRoutes:
    namespaces:
      from: All
```

---

### Сценарий 2: Автоматический выпуск через аннотации (gateway-shim)

**Цель:** Простота настройки в стиле Ingress. cert-manager сам создаст ресурс `Certificate`.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: auto-tls-gateway
  namespace: default
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  gatewayClassName: envoy-gateway
  listeners:
  - name: https
    hostname: "app.example.com"
    port: 443
    protocol: HTTPS
    tls:
      mode: Terminate
      certificateRefs:
      - name: app-tls-secret # Secret будет создан автоматически
    allowedRoutes:
      namespaces:
        from: All
```

---

### Сценарий 3: Несколько слушателей с индивидуальными сертификатами

**Цель:** Разделение TLS-конфигураций для разных доменов на одном физическом шлюзе.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: multi-domain-gateway
  namespace: infra-system
spec:
  gatewayClassName: istio
  listeners:
  - name: https-main
    hostname: main.example.com
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs: [{name: main-tls-secret}]
  - name: https-api
    hostname: api.example.com
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs: [{name: api-tls-secret}]
```

---

### Сценарий 4: Wildcard-сертификат (DNS-01)

**Цель:** Обслуживание множества поддоменов одним сертификатом.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: wildcard-tls
  namespace: infra-system
spec:
  secretName: wildcard-tls-secret
  issuerRef: 
    name: cloudflare-dns-issuer
    kind: ClusterIssuer
  dnsNames: 
    - "example.com"
    - "*.example.com"
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: wildcard-gateway
  namespace: infra-system
spec:
  gatewayClassName: cilium
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs: [{name: wildcard-tls-secret}]
    allowedRoutes:
      namespaces: {from: All}
```

---

### Сценарий 5: Безопасный кросс-неймспейс доступ (ReferenceGrant)

**Цель:** Использование сертификата из защищенного хранилища в публичном шлюзе.

**ReferenceGrant (в namespace с сертификатом — `cert-storage`):**
```yaml
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-infra-gateway
  namespace: cert-storage
spec:
  from:
  - group: gateway.networking.k8s.io
    kind: Gateway
    namespace: infra-system
  to:
  - group: ""
    kind: Secret
    name: central-tls-secret
```

**Gateway (в namespace `infra-system`):**
```yaml
# ... фрагмент манифеста
    tls:
      mode: Terminate
      certificateRefs:
      - name: central-tls-secret
        namespace: cert-storage # Ссылка на другой namespace разрешена ReferenceGrant
```

---

### Сценарий 6: Self-Service TLS через ListenerSet (v1.21+ Stable)

**Цель:** Позволить разработчикам приложений управлять TLS самостоятельно, не имея прав на основной Gateway.

```yaml
apiVersion: gateway.networking.k8s.io/v1alpha1
kind: ListenerSet
metadata:
  name: app-team-listeners
  namespace: app-team
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    # Аннотация для прохождения HTTP-01 через 80 порт родительского Gateway
    acme.cert-manager.io/http01-parentreffallback: "true"
spec:
  parentRef:
    name: shared-gateway
    namespace: infra-system
  listeners:
  - name: https-app
    hostname: "app.team-a.example.com"
    port: 443
    protocol: HTTPS
    tls:
      mode: Terminate
      certificateRefs: [{name: team-a-tls-secret}]
```

---

### Сценарий 7: Сквозное шифрование (TLS Passthrough / mTLS)

**Цель:** Передача трафика до пода без расшифровки на шлюзе (для mTLS или строгой изоляции).

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: secure-gateway
spec:
  listeners:
  - name: tls-passthrough
    protocol: TLS
    port: 443
    tls: {mode: Passthrough}
---
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: TLSRoute
metadata:
  name: backend-mtls-route
spec:
  parentRefs: [{name: secure-gateway}]
  rules:
  - backendRefs: [{name: mtls-enabled-service, port: 8443}]
```

---

### Сценарий 8: Нативный HTTP-to-HTTPS редирект

**Цель:** Принудительное использование защищенного соединения без сторонних аннотаций.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: redirect-to-https
  namespace: infra-system
spec:
  parentRefs:
  - name: public-gateway
    sectionName: http-80 # Ссылка на слушатель порта 80 в Gateway
  rules:
  - filters:
    - type: RequestRedirect
      requestRedirect:
        scheme: https
        statusCode: 301
```

---

## Дополнительная информация

### Рекомендации по эксплуатации

1.  **ARI и автоматизация**: В cert-manager v1.21+ ARI включен по умолчанию. Рекомендуется удалять `renewBefore` из ресурсов `Certificate`, чтобы передать управление окном продления протоколу ACME.
2.  **Диагностика фидбека**: Состояние выпуска сертификата теперь транслируется в `status.conditions` ресурсов `Gateway` и `ListenerSet` (тип `ResolvedRefs`), что позволяет отлаживать TLS без прямого доступа к логам cert-manager.
3.  **Безопасность RBAC**: Ограничивайте права на создание `ListenerSet` и `ReferenceGrant`, так как они позволяют манипулировать точками входа в кластер.

### Смотрите также

- **[Определения и концепции Gateway API](./definitions_and_concepts.md)** — архитектура и ролевая модель.
- **[Gateway API: Дополнительные темы](./advanced_topics.md)** — глубокая диагностика и Hostname-конфликты.
- **[Cert-manager: Определения](../../definitions.md)** — базовые ресурсы контроллера.
