# Интеграция Cert-manager с Gateway API: Практические сценарии

## Определения

**TLS Termination** — режим Gateway, при котором TLS-трафик расшифровывается на шлюзе и передаётся бэкенду в открытом виде.

**TLS Passthrough** — режим, при котором TLS-трафик передаётся напрямую бэкенду без расшифровки на шлюзе (требуется `TLSRoute`, статус: `v1alpha2`).

**Wildcard-сертификат** — единый сертификат для всех поддоменов (например, `*.example.com`). Требует DNS-01 solver.

## Базовые концепции

### Подготовительные шаги

Перед созданием сценариев необходимо:

1. Установить CRD Gateway API
2. Установить cert-manager с флагом `--enable-gateway-api`
3. Создать ClusterIssuer (ACME Let's Encrypt)

Подробные инструкции: [Установка cert-manager](../../installation.md), [Определения cert-manager](../../definitions.md#интеграция-с-gateway-api).

### Архитектура интеграции

```
Certificate (cert-manager)
    ↓ создаёт
Secret (tls secret)
    ↓ используется
Gateway.certificateRefs
    ↓ обрабатывает
Gateway Controller (Traefik, Envoy Gateway, Cilium)
```

### Типы сценариев

| Сценарий | Режим TLS | Solver | Примечание |
| :--- | :--- | :--- | :--- |
| Базовый Gateway | Terminate | HTTP-01 / DNS-01 | Один домен, один сертификат |
| Несколько слушателей | Terminate | HTTP-01 / DNS-01 | Несколько доменов, отдельные сертификаты |
| Wildcard | Terminate | DNS-01 | Один сертификат на все поддомены |
| TLS Passthrough | Passthrough | Не требуется | Бэкенд управляет TLS самостоятельно |
| HTTP-to-HTTPS Redirect | Terminate + HTTP | — | Редирект через HTTPRoute filter |

---

## Практические сценарии

### Сценарий 1: Базовый Gateway с TLS Termination

**Цель:** Настроить Gateway с TLS-сертификатом для одного домена.

**Certificate:**

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: gateway-tls
  namespace: default
spec:
  secretName: gateway-tls-secret
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - api.example.com
  duration: 2160h
  renewBefore: 360h
```

**Gateway:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: example-gateway
  namespace: default
spec:
  gatewayClassName: traefik
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: gateway-tls-secret
        namespace: default
  allowedRoutes:
    namespaces:
      from: Same
```

---

### Сценарий 2: Несколько HTTPS-слушателей

**Цель:** Один Gateway с несколькими доменами и отдельными сертификатами.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: multi-tls-gateway
  namespace: default
spec:
  gatewayClassName: traefik
  listeners:
  - name: https-main
    hostname: main.example.com
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: main-tls-secret
  - name: https-api
    hostname: api.example.com
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: api-tls-secret
  - name: https-admin
    hostname: admin.example.com
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: admin-tls-secret
  allowedRoutes:
    namespaces:
      from: Same
```

**Сертификаты** (по одному на домен):

```yaml
# main.example.com
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: main-tls
  namespace: default
spec:
  secretName: main-tls-secret
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - main.example.com
---
# api.example.com
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: api-tls
  namespace: default
spec:
  secretName: api-tls-secret
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - api.example.com
---
# admin.example.com
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: admin-tls
  namespace: default
spec:
  secretName: admin-tls-secret
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - admin.example.com
```

---

### Сценарий 3: Wildcard-сертификат для Gateway

**Цель:** Один wildcard-сертификат для всех поддоменов.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: wildcard-gateway-tls
  namespace: default
spec:
  secretName: wildcard-gateway-secret
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - example.com
    - "*.example.com"
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: wildcard-gateway
  namespace: default
spec:
  gatewayClassName: traefik
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: wildcard-gateway-secret
  allowedRoutes:
    namespaces:
      from: All
```

> **Важно:** Требуется DNS-01 solver в ClusterIssuer. Подробности: [ACME Solvers](../../definitions.md#acme-solvers-проверки-владения).

---

### Сценарий 4: TLS Passthrough

**Цель:** Передать TLS-трафик напрямую бэкенду (mTLS).

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: passthrough-gateway
  namespace: default
spec:
  gatewayClassName: traefik
  listeners:
  - name: tls-passthrough
    protocol: TLS
    port: 443
    tls:
      mode: Passthrough
  allowedRoutes:
    namespaces:
      from: Same
```

**TLSRoute для passthrough:**

```yaml
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: TLSRoute
metadata:
  name: mtls-backend
  namespace: default
spec:
  parentRefs:
  - name: passthrough-gateway
  rules:
  - backendRefs:
    - name: mtls-backend-service
      port: 8443
```

> **Примечание:** cert-manager не участвует в терминации — бэкенд самостоятельно управляет сертификатами. Подробности: [Дополнительные темы](./advanced_topics.md#особенности-tls-passthrough).

---

### Сценарий 5: HTTP-to-HTTPS Redirect

**Цель:** Автоматический редирект с HTTP на HTTPS.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: redirect-gateway
  namespace: default
spec:
  gatewayClassName: traefik
  listeners:
  - name: http
    protocol: HTTP
    port: 80
    allowedRoutes:
      namespaces:
        from: Same
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: gateway-tls-secret
    allowedRoutes:
      namespaces:
        from: Same
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: redirect-route
  namespace: default
spec:
  parentRefs:
  - name: redirect-gateway
    sectionName: http
  rules:
  - filters:
    - type: RequestRedirect
      requestRedirect:
        scheme: https
        statusCode: 301
```

---

## Дополнительная информация

### Диагностика

Проверка статусов ресурсов и логи cert-manager: [Дополнительные темы](./advanced_topics.md#диагностика-интеграции).

### Troubleshooting

Частые ошибки и решения: [Дополнительные темы](./advanced_topics.md#частые-ошибки).

### Определения и концепции

Базовые понятия и отличия от Ingress: [Определения и концепции](./definitions_and_concepts.md).
