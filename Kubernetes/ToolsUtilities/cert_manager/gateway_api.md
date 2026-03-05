# Интеграция Cert-manager с Gateway API

## Определения

**Gateway API** — эволюция Kubernetes Ingress API, предоставляющая более выразительную модель для маршрутизации трафика (L7 и L4).

**Интеграция с cert-manager:** cert-manager может автоматически выпускать сертификаты для Gateway-ресурсов через аннотации или прямые `Certificate` ресурсы.

---

## Основные концепции

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| **cert-manager** | 1.13+ | Флаг `--enable-gateway-api` |
| **Gateway API CRD** | v1.0+ | Устанавливаются отдельно |
| **Kubernetes** | 1.21+ | Для Gateway API v1 |

### Поток работы

```
1. Установка CRD Gateway API
         ↓
2. Установка cert-manager с --enable-gateway-api
         ↓
3. Создание Gateway с certificateRefs
         ↓
4. cert-manager создаёт Certificate
         ↓
5. Secret создаётся и используется Gateway
```

### Отличия от Ingress

| Аспект | Ingress | Gateway API |
| :--- | :--- | :--- |
| **Аннотации** | `cert-manager.io/cluster-issuer` | Прямая ссылка на Secret |
| **Certificate** | Автоматически через аннотацию | Требуется вручную или через Gateway-аннотации |
| **Несколько слушателей** | Ограничено | Полная поддержка |
| **TLS-режимы** | Зависит от контроллера | `Terminate`, `Passthrough`, `Redirect` |

---

## Практические сценарии

### Сценарий 1: Базовый Gateway с TLS Termination

**Цель:** Настроить Gateway с TLS-сертификатом.

#### Шаг 1: Установка Gateway API CRD

```bash
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.0.0/standard-install.yaml
```

#### Шаг 2: Установка cert-manager с поддержкой Gateway API

```bash
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set installCRDs=true \
  --set "extraArgs={--enable-gateway-api=true}"
```

#### Шаг 3: Создание Certificate

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

#### Шаг 4: Создание Gateway

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

**Цель:** Один Gateway с несколькими доменами и сертификатами.

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

**Сертификаты:**

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

> **Важно:** Требуется DNS-01 solver в ClusterIssuer для wildcard.

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

**HTTPRoute для passthrough:**

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

### Особенности работы с hostname

**Проблема:** При указании `hostname` в Gateway cert-manager может некорректно определять домены для сертификата.

**Решения:**
1. Создать `Certificate` вручную перед Gateway
2. Дождаться создания Secret
3. Применить Gateway с ссылкой на Secret

### Диагностика

```bash
# Статус Gateway
kubectl get gateway -n default

# Детали Gateway
kubectl describe gateway example-gateway -n default

# Статус Certificate
kubectl get certificate -n default

# Логи cert-manager
kubectl logs -n cert-manager -l app=cert-manager | grep -i gateway
```

### Частые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Gateway API not enabled` | Флаг не указан | Пересоздать с `--enable-gateway-api=true` |
| `CertificateRef not found` | Secret не создан | Проверить статус Certificate |
| `hostname конфликт` | cert-manager не определяет домен | Создать Certificate вручную |
| `CRD missing` | Gateway API CRD не установлены | Установить CRD до cert-manager |

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| Gateway API интеграция | **9** | Подтверждено в cert-manager 1.13+ |
| Несколько слушателей | **9** | Работает в Traefik, Envoy Gateway |
| TLS Passthrough | **8** | Зависит от реализации Gateway Controller |
| Wildcard сертификаты | **10** | Стандартный ACME DNS-01 |

---

*SSoT для интеграции с Gateway API. Последняя проверка актуальности: март 2026.*
