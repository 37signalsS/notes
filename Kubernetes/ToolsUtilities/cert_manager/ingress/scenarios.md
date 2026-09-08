# Cert-manager: Сценарии интеграции с Ingress

## Определения

**Сценарии интеграции** — набор практических паттернов конфигурации ресурсов Ingress для автоматизированного управления TLS-сертификатами. Сценарии охватывают различные методы валидации (HTTP-01, DNS-01), топологии доменов (SAN, Wildcard), интеграцию с инструментами автоматизации (external-dns, GitOps) и специфические требования среды (internal CA, gRPC, multi-cluster).

**Subject Alternative Name (SAN)** — расширение X.509, позволяющее защитить несколько доменных имен одним сертификатом. В контексте Ingress это реализуется через перечисление нескольких хостов в одной секции `tls`. Один Ingress может содержать несколько секций `tls`, каждая из которых ссылается на отдельный Secret и набор хостов.

**ACME Solver** — механизм подтверждения владения доменом. При интеграции с Ingress выбор солвера происходит автоматически на основе конфигурации `Issuer`/`ClusterIssuer`, но может уточняться через аннотации (`acme.cert-manager.io/http01-edit-in-place`, `acme.cert-manager.io/dns01-*`).

**Staging-first подход** — методология тестирования конфигурации cert-manager через staging-окружение Let's Encrypt (`acme-staging-v02.api.letsencrypt.org/directory`) перед применением в production. Позволяет выявить ошибки конфигурации без риска попасть в rate limit production-окружения.

**Pre-existing TLS Secret** — Kubernetes Secret типа `kubernetes.io/tls`, созданный до или независимо от cert-manager. Может содержать сертификаты, выпущенные внешним CA, импортированные из Vault или других источников. Ingress может ссылаться на такой Secret без участия cert-manager.

**cert-manager CSI Driver** — дополнительный компонент экосистемы cert-manager, позволяющий монтировать TLS-сертификаты напрямую в файловую систему пода через CSI-плагин без создания Kubernetes Secrets. Полезен для приложений, которые не поддерживают чтение секретов из Kubernetes API.

> **См. также:** [Обзор интеграции](./overview.md) — концепции, аннотации и механизм работы ingress-shim.

---

## Основные концепции

Эффективное использование сценариев в 2026 году базируется на следующих принципах:

1.  **Приоритет безопасности:** Использование современных алгоритмов (**Ed25519**, **ECDSA**) и обязательная ротация приватных ключей (`rotationPolicy: Always`).
2.  **Автоматизация продления:** Использование протокола **ARI** (ACME Renewal Information) для минимизации рисков истечения срока действия (настройка на стороне контроллера, прозрачно для Ingress).
3.  **Изоляция доменов:** Решение о том, использовать ли один SAN-сертификат для всех сервисов или отдельные сертификаты для каждого Ingress, должно основываться на требованиях к безопасности и лимитах CA.
4.  **Staging-first:** Тестирование любой новой конфигурации через staging-окружение Let's Encrypt перед продакшеном. Rate limit production: 50 сертификатов на домен в неделю.
5.  **Соответствие GitOps:** При использовании ArgoCD/Flux необходимо учитывать конфликты Server-Side Apply и настраивать `managedFieldsManagers` для игнорирования изменений cert-manager.
6.  **Интеграция с DNS-автоматизацией:** Совместное использование cert-manager и external-dns обеспечивает полный цикл: DNS-запись -> TLS-сертификат -> Ingress.

---

## Практические сценарии

### Сценарий 1: Публичный сервис с HTTP-01 (NGINX/Traefik)

Наиболее распространенный сценарий для стандартных Ingress-контроллеров.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web-app-ingress
  annotations:
    # Использование общекластерного выпускающего органа
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    # Стандарт 2026: Ротация ключа при каждом обновлении (защита от компрометации)
    cert-manager.io/private-key-rotation-policy: "Always"
    # Опционально: использование ECDSA вместо RSA
    cert-manager.io/private-key-algorithm: "ECDSA"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - app.example.com
    secretName: app-example-tls
  rules:
  - host: app.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: app-service
            port:
              number: 80
```

**Особенности:**
- cert-manager автоматически создаст временный Ingress и Pod для прохождения HTTP-01 проверки.
- Требуется открытый порт 80 для входящего трафика от Let's Encrypt.

---

### Сценарий 2: Облачные Ingress (AWS ALB / Google GCE)

В облачных средах Ingress-контроллер часто сам управляет внешним Load Balancer. Создание дополнительных ресурсов cert-manager может нарушить работу балансировщика.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: cloud-app-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    # ВАЖНО: Модифицировать существующий Ingress вместо создания нового
    acme.cert-manager.io/http01-edit-in-place: "true"
    # Для AWS ALB требуется указывать группу
    alb.ingress.kubernetes.io/group.name: my-app-group
spec:
  ingressClassName: alb
  tls:
  - hosts:
    - cloud.example.com
    secretName: cloud-example-tls
  rules:
  - host: cloud.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: cloud-service
            port:
              number: 80
```

**Почему это важно:**
Без `edit-in-place` cert-manager создаст новый ресурс Ingress, что приведет к созданию нового AWS ALB или GCE Load Balancer, который не будет иметь нужных DNS-записей.

---

### Сценарий 3: Wildcard-домены через DNS-01

HTTP-01 проверка не поддерживает wildcard-сертификаты (`*.example.com`). Для них обязателен DNS-01.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: wildcard-ingress
  annotations:
    # ClusterIssuer должен быть предварительно настроен на работу с Cloud DNS / Route53 / Cloudflare
    cert-manager.io/cluster-issuer: "letsencrypt-dns-prod"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - "*.example.com"
    - "example.com" # SAN включает корень и wildcard
    secretName: wildcard-example-tls
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: api-service
            port:
              number: 80
```

---

### Сценарий 4: Multi-Domain (SAN) в одном Ingress

Один сертификат для нескольких независимых хостов.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: multi-site-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - site1.com
    - site2.com
    - site3.com
    secretName: multi-site-tls
  rules:
  - host: site1.com
    http:
      paths:
      - path: /
        backend:
          service:
            name: svc1
            port:
              number: 80
  # ... остальные правила
```

**Предупреждение:** Если один из доменов перестанет указывать на IP кластера, перевыпуск сертификата SAN **провалится для всех доменов** в этом списке.

---

### Сценарий 5: Использование Issuer в разных Namespaces

Если вам нужно использовать локальный (не кластерный) Issuer, он должен находиться в том же Namespace, что и Ingress.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: local-app-ingress
  namespace: team-alpha
  annotations:
    # Ссылается на ресурс Issuer в namespace team-alpha
    cert-manager.io/issuer: "team-ca-issuer"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - internal.alpha.local
    secretName: alpha-tls
  rules:
  - host: internal.alpha.local
    http:
      paths:
      - path: /
        backend:
          service:
            name: alpha-service
            port:
              number: 80
```

---

### Сценарий 6: Staging-first подход (тестирование перед продакшеном)

Критически важный паттерн для production-сред. Использование staging-окружения Let's Encrypt позволяет выявить ошибки конфигурации без риска попасть в rate limit (50 сертификатов/неделю на домен).

**Алгоритм безопасного тестирования:**

1. **Этап 1 — Валидация конфигурации через staging:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: test-staging-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-staging"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - test.example.com
    secretName: test-staging-tls
  rules:
  - host: test.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: test-service
            port:
              number: 80
```

**ClusterIssuer для staging:**

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging
spec:
  acme:
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-staging-key
    solvers:
    - http01:
        ingress:
          class: nginx
```

2. **Этап 2 — Проверка выпуска сертификата:**

```bash
# Проверка состояния Certificate
kubectl get certificate test-staging-tls -n default
# → READY должен быть True

# Проверка деталей
kubectl describe certificate test-staging-tls -n default

# Проверка challenge (если есть проблемы)
kubectl get challenge -n default
kubectl describe challenge <name> -n default
```

> **Важно:** Staging-сертификаты НЕ доверяются браузерами. Они используются ТОЛЬКО для валидации процесса выпуска.

3. **Этап 3 — Миграция на production:**

```bash
# Удаление staging-сертификата
kubectl delete secret test-staging-tls

# Применение production-конфигурации
kubectl apply -f ingress-prod.yaml
```

**Production ClusterIssuer:**

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-key
    solvers:
    - http01:
        ingress:
          class: nginx
```

**Почему staging-first критичен:**

- Let's Encrypt имеет строгие rate limits: 50 сертификатов/неделю на домен, 300 Order/час
- Ошибки конфигурации (например, неверный `ingressClassName`) в staging не тратят лимиты production
- Staging-окружение идентично production по логике валидации, отличается только CA-цепочка

---

### Сценарий 7: Ingress с несколькими TLS-секциями (разные сертификаты)

Когда различные хосты требуют различных сертификатов (разные CA, разные параметры безопасности), используют несколько секций `tls` с различными `secretName`.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: multi-tls-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - api.example.com
    secretName: api-tls-secret
  - hosts:
    - admin.example.com
    secretName: admin-tls-secret
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: api-service
            port:
              number: 80
  - host: admin.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: admin-service
            port:
              number: 80
```

**Особенности:**

- cert-manager создаст отдельные ресурсы `Certificate` для каждого `secretName`
- Каждый сертификат будет выпущен независимо, что позволяет использовать разные параметры (алгоритмы ключей, сроки действия)
- Если один сертификат не выпущен, это не влияет на другие

**Комбинирование SAN и отдельных сертификатов:**

```yaml
tls:
- hosts:
  - site1.example.com
  - site2.example.com
  secretName: shared-tls-secret          # SAN-сертификат для site1 и site2
- hosts:
  - secure.example.com
  secretName: dedicated-tls-secret        # Отдельный сертификат для secure
```

---

### Сценарий 8: Pre-existing TLS Secret (импортированные сертификаты)

Для Ingress, которые используют сертификаты, выпущенные внешним CA или импортированные из Vault, cert-manager не требуется — Ingress ссылается на предсуществующий Secret напрямую.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: imported-cert-ingress
  # Без аннотаций cert-manager — сертификат уже существует
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - legacy.example.com
    secretName: imported-tls-secret       # Предсуществующий Secret
  rules:
  - host: legacy.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: legacy-service
            port:
              number: 80
```

**Создание Secret из существующих файлов:**

```bash
# Импорт сертификата и ключа в Kubernetes Secret
kubectl create secret tls imported-tls-secret \
  --cert=path/to/tls.crt \
  --key=path/to/tls.key \
  -n default

# Или из OpenSSL-генерации
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout tls.key -out tls.crt \
  -subj "/CN=legacy.example.com"

kubectl create secret tls imported-tls-secret \
  --cert=tls.crt --key=tls.key
```

**Важно:** При добавлении аннотаций cert-manager к Ingress, который ссылается на предсуществующий Secret, cert-manager НЕ будет пытаться выпустить сертификат, если Secret уже содержит валидный TLS-сертификат. Однако это поведение нежелательно — лучше явно указывать источник сертификата.

---

### Сценарий 9: cert-manager + external-dns (полная автоматизация DNS + TLS)

Связка cert-manager и external-dns обеспечивает полный цикл: автоматическое создание DNS-записей и выпуск TLS-сертификатов. Критически важна для динамических сред (review apps, ephemeral environments).

**Предварительные требования:**

- Установленный external-dns (см. [Kubernetes/Networking/Ingress/overview.md](../../../Networking/Ingress/overview.md))
- Настроенный ClusterIssuer для DNS-01 (требуется для wildcard и автоматизации)

**Конфигурация Ingress с dual-автоматизацией:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: auto-dns-tls-ingress
  annotations:
    # cert-manager: автоматический выпуск TLS
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    # external-dns: автоматическое создание DNS-записи
    external-dns.alpha.kubernetes.io/hostname: app.example.com
    external-dns.alpha.kubernetes.io/ttl: "300"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - app.example.com
    secretName: app-auto-tls
  rules:
  - host: app.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: app-service
            port:
              number: 80
```

**ClusterIssuer с DNS-01 solver (Cloudflare как пример):**

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-dns-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-dns-prod-key
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token
            key: api-token
```

**Порядок операций:**

1. external-dns создаёт DNS-запись (A/CNAME) для хоста из Ingress
2. cert-manager инициирует ACME Challenge (HTTP-01 или DNS-01)
3. Let's Encrypt валидирует владение доменом через созданную DNS-запись
4. TLS-сертификат сохраняется в Secret, указанный в `tls.secretName`
5. Ingress-контроллер обновляет конфигурацию с новым сертификатом

**Диагностика dual-автоматизации:**

```bash
# Проверка DNS-записи (должна существовать ДО валидации cert-manager)
dig app.example.com +short

# Проверка состояния certificate
kubectl get certificate app-auto-tls -n default

# Проверка логов external-dns
kubectl logs -n kube-system -l app=external-dns --tail=50

# Проверка логов cert-manager
kubectl logs -n cert-manager -l app=cert-manager --tail=50
```

---

### Сценарий 10: cert-manager для gRPC-сервисов

gRPC использует HTTP/2 и требует особого внимания к TLS-конфигурации. Основные отличия от HTTP/1.1: ALPN (Application-Layer Protocol Negotiation), requirement на HTTP/2, и специфика маршрутизации (`Exact` вместо `Prefix`).

**Ключевые требования:**

- TLS-сертификат должен поддерживать ALPN h2 (HTTP/2)
- Ingress-контроллер должен быть настроен на проксирование HTTP/2
- Для NGINX Ingress: аннотация `nginx.ingress.kubernetes.io/backend-protocol: "GRPC"`

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: grpc-service-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    # NGINX: backend-protocol GRPC для HTTP/2
    nginx.ingress.kubernetes.io/backend-protocol: "GRPC"
    # Опционально: SSL-редирект
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    # Опционально: проксирование gRPC-таймаутов
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - grpc.example.com
    secretName: grpc-tls
  rules:
  - host: grpc.example.com
    http:
      paths:
      - path: /
        pathType: Exact              # gRPC требует точного совпадения
        backend:
          service:
            name: grpc-service
            port:
              number: 50051
```

**Проверка ALPN (важно для gRPC-клиентов):**

```bash
# Проверка ALPN через openssl
openssl s_client -connect grpc.example.com:443 -alpn h2 2>/dev/null | grep "ALPN"
# → Protocol  : h2

# Проверка HTTP/2 через curl
curl -v --http2 https://grpc.example.com 2>&1 | grep "HTTP/2"
# → * Using HTTP/2
```

**Особенности gRPC + TLS:**

- cert-manager автоматически добавляет ALPN h2 в выпущенные сертификаты (ECDSA/RSA)
- Для internal gRPC (без TLS termination на Ingress) используется mTLS через cert-manager и private CA
- При использовании Envoy/Istio: сертификаты монтируются через sidecar, Ingress не требуется

---

### Сценарий 11: cert-manager + WAF/Rate Limiting (комбинированная безопасность)

Интеграция cert-manager с средствами защиты (WAF, rate limiting) обеспечивает многоуровневую безопасность: TLS на уровне Ingress + application-level protection.

**Ingress с cert-manager + NGINX Rate Limiting:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: protected-app-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    # NGINX: Rate Limiting
    nginx.ingress.kubernetes.io/limit-rps: "10"
    nginx.ingress.kubernetes.io/limit-burst-multiplier: "5"
    nginx.ingress.kubernetes.io/limit-connections: "5"
    # NGINX: Реализация rate limit через ключ (IP или заголовок)
    nginx.ingress.kubernetes.io/limit-req-status: "429"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - api.example.com
    secretName: api-protected-tls
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: api-service
            port:
              number: 80
```

**Ingress с cert-manager + ModSecurity WAF:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: waf-protected-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    # NGINX: Включение ModSecurity
    nginx.ingress.kubernetes.io/enable-modsecurity: "true"
    nginx.ingress.kubernetes.io/modsecurity-snippet: |
      SecRuleEngine On
      SecRule REQUEST_URI "@rx /admin" "id:1001,phase:1,deny,status:403"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - secure.example.com
    secretName: secure-tls
  rules:
  - host: secure.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: secure-service
            port:
              number: 80
```

**Важные замечания:**

- Rate limiting и WAF применяются ПОСЛЕ TLS termination ( plaintext HTTP)
- При атаке на TLS (handshake flooding) rate limiting не поможет — рекомендуется Cloudflare/CDN
- Для gRPC rate limiting: NGINX Ingress не поддерживает gRPC rate limiting, используйте Envoy/Istio

---

### Сценарий 12: cert-manager CSI Driver (монтирование без Secrets)

cert-manager CSI Driver позволяет монтировать TLS-сертификаты напрямую в файловую систему пода через CSI-плагин без создания Kubernetes Secrets. Полезен для приложений, которые не поддерживают чтение секретов из Kubernetes API (legacy applications, database clients).

**Установка cert-manager CSI Driver:**

```bash
helm install cert-manager-csi jetstack/cert-manager-csi \
  --namespace cert-manager \
  --create-namespace
```

**Ingress с CSI-монтированием (для бэкенд-сервиса):**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: csi-app-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - app.example.com
    secretName: app-csi-tls
  rules:
  - host: app.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: csi-app-service
            port:
              number: 443
---
# Deployment с CSI-монтированием TLS-сертификата
apiVersion: apps/v1
kind: Deployment
metadata:
  name: csi-app
spec:
  replicas: 2
  selector:
    matchLabels:
      app: csi-app
  template:
    metadata:
      labels:
        app: csi-app
    spec:
      containers:
      - name: app
        image: nginx:1.27-alpine
        volumeMounts:
        - name: tls-cert
          mountPath: /etc/tls
          readOnly: true
        command: ["nginx", "-g", "daemon off;"]
        args:
        - "-c"
        - |
          server {
            listen 443 ssl;
            ssl_certificate /etc/tls/tls.crt;
            ssl_certificate_key /etc/tls/tls.key;
            server_name app.example.com;
          }
      volumes:
      - name: tls-cert
        csi:
          driver: cert-manager.csi
          readOnly: true
          volumeAttributes:
            csi.cert-manager.io/issuer-name: letsencrypt-prod
            csi.cert-manager.io/issuer-kind: ClusterIssuer
            csi.cert-manager.io/dns-names: app.example.com
            csi.cert-manager.io/duration: 2160h
            csi.cert-manager.io/renew-before: 360h
```

**Отличия CSI от Secrets:**

| Аспект | Secrets | CSI Driver |
| :--- | :--- | :--- |
| **Хранение** | Kubernetes Secret (etcd) | Файл в Volume |
| **Обновление** | Pod restart или Reloader | Автоматическое (in-place) |
| **Безопасность** | Доступ через RBAC | Файловые права (0644) |
| **Совместимость** | Все приложения | Только POSIX-совместимые |

---

## Дополнительная информация

### Диагностика типовых сбоев

При применении сценариев наиболее часто возникают проблемы на этапе валидации (Challenge).

#### Проверка состояния Challenge
Если Secret не появляется, первым делом проверьте объекты `Challenge`:
```bash
kubectl get challenge -n <namespace>
# Если статус не 'valid', смотрим детали:
kubectl describe challenge <name> -n <namespace>
```

> **Совет для тестирования:** Если у вас есть публичный IP, но нет настроенной DNS-записи для проверки Let's Encrypt, используйте сервисы типа `nip.io` или `sslip.io`. Например: `1.2.3.4.nip.io` будет разрешаться в IP `1.2.3.4`. Это позволит успешно пройти HTTP-01 проверку.

#### Ошибки в сценарии SAN (Сценарий 4)
Если вы видите ошибку `Waiting for HTTP-01 challenge propagation`, убедитесь, что **все** домены из списка `hosts` разрешаются в IP вашего Ingress-контроллера. Let's Encrypt будет проверять каждый из них. Если хотя бы один домен недоступен, сертификат не будет выпущен.

#### Проблемы с правами в Облаках (Сценарий 2)
Для AWS/GCP часто требуется дополнительная настройка IAM-ролей для подов cert-manager, чтобы они могли изменять записи в DNS (для DNS-01) или аннотировать Ingress (для HTTP-01 `edit-in-place`).

#### Ошибки gRPC Ingress (Сценарий 10)
| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `Connection refused` | Неверный backend-protocol | Добавить `nginx.ingress.kubernetes.io/backend-protocol: "GRPC"` |
| `HTTP/1.1 200` вместо `HTTP/2` | ALPN не включён | Проверить сертификат: `openssl s_client -alpn h2` |
| `context deadline exceeded` | Таймаут соединения | Увеличить `proxy-read-timeout` и `proxy-send-timeout` |

#### Ошибки CSI Driver (Сценарий 12)
| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Volume не монтируется | CSI Driver не установлен | `helm install cert-manager-csi jetstack/cert-manager-csi` |
| Файл сертификата пуст | Issuer недоступен | `kubectl describe certificate <name>` |
| `permission denied` | Неверные права доступа | Проверить `securityContext.fsGroup` в Pod |

#### Диагностика Rate Limit Let's Encrypt
Если cert-manager сообщает об ошибке rate limit:

```bash
# Проверка количества выпущенных сертификатов (через CT-логи)
curl -s "https://crt.sh/?q=example.com&output=json" | jq '.[] | .not_after' | sort | uniq -c

# Проверка лимитов Let's Encrypt
# Production: 50 сертификатов/неделю на Registered Domain
# Staging: 30000 сертификатов/неделю

# Сброс rate limit: смена email в ClusterIssuer или использование staging
```

### Best Practices

1. **Staging-first:** Всегда тестируйте новую конфигурацию через staging перед продакшеном.
2. **Разделение Issuer:** Используйте отдельные Issuer для публичных (Let's Encrypt) и внутренних (Vault/Self-signed) нужд.
3. **Rotation Policy:** Включите `rotationPolicy: Always` для всех Production-сертификатов.
4. **Мониторинг:** Настройте алерты на `certmanager_certificate_ready_status` и `certmanager_certificate_expiration_timestamp_seconds` (см. [Administration/operations.md](../Administration/operations.md)).
5. **GitOps:** При использовании ArgoCD/Flux настраивайте `managedFieldsManagers` для игнорирования изменений cert-manager (см. [GitOps/ArgoCD/synchronization/ignore_differences.md](../../../GitOps/ArgoCD/synchronization/ignore_differences.md)).
6. **Cleanup:** Удаляйте test-staging Secret перед миграцией на production.

### Edge Cases и ограничения

- **Rate Limits:** Let's Encrypt: 50 сертификатов/неделю на домен, 300 Order/час, 5 duplicate certificates/неделю
- **Wildcard:** HTTP-01 не поддерживает wildcard (`*.example.com`), обязателен DNS-01
- **SAN Limit:** Максимум 100 хостов в одном сертификате (рекомендуется <10 для production)
- **Key Size:** ECDSA: P-256/P-384; RSA: минимум 2048 бит (рекомендуется 4096)
- **Namespace Isolation:** ClusterIssuer доступен из всех namespace, Issuer — только из своего
- **IngressClassName:** При смене класса Ingress потребуется ручное удаление старого Certificate

### Смотрите также

- **[Обзор интеграции](./overview.md)** — концепции, аннотации, диагностика
- **[Cert-manager: Определения](../definitions.md)** — база знаний по CRD
- **[Let's Encrypt: Сценарии](../LetsEncrypt/letsencrypt_scenarios.md)** — настройка Issuer и ClusterIssuer
- **[Gateway API: Сценарии](../gateway_api/practical_scenarios.md)** — использование cert-manager с новым стандартом Gateway API
- **[Troubleshooting](../Administration/troubleshooting.md)** — глубокая диагностика контроллера
