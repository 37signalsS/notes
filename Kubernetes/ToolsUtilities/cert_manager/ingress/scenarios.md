# Сценарии интеграции Cert-manager с Ingress

## Сценарий 1: Базовый Ingress с HTTP-01

**Цель:** Автоматически получить сертификат для домена.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app-ingress
  namespace: default
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - myapp.example.com
    secretName: myapp-tls
  rules:
  - host: myapp.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: my-app
            port:
              number: 80
```

**Процесс:**

1. cert-manager создаёт `Certificate` с именем `myapp-tls`
2. Выполняется HTTP-01 проверка через Ingress
3. Secret `myapp-tls` создаётся с сертификатом
4. Ingress использует Secret для TLS

---

## Сценарий 2: Несколько доменов в одном Ingress

**Цель:** Один сертификат для нескольких доменов (SAN).

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: multi-domain-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    cert-manager.io/common-name: "example.com"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - example.com
    - www.example.com
    - shop.example.com
    secretName: example-com-multi-tls
  rules:
  - host: example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: main-service
            port:
              number: 80
  - host: www.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: main-service
            port:
              number: 80
  - host: shop.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: shop-service
            port:
              number: 80
```

---

## Сценарий 3: Временный сертификат до ACME-проверки

**Цель:** Избежать ошибок TLS во время ACME-проверки.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: temp-cert-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    cert-manager.io/issue-temporary-certificate: "true"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - myapp.example.com
    secretName: myapp-tls
  rules:
  - host: myapp.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: my-app
            port:
              number: 80
```

**Поведение:**

- cert-manager создаёт self-signed сертификат немедленно
- После прохождения ACME-проверки заменяется на настоящий

---

## Сценарий 4: DNS-01 для wildcard-доменов

**Цель:** Wildcard-сертификат `*.example.com`.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: wildcard-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    cert-manager.io/acme-challenge-type: "dns01"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - example.com
    - "*.example.com"
    secretName: example-wildcard-tls
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

> **Важно:** Требуется настроенный DNS-01 solver в ClusterIssuer.

---

## Сценарий 5: Прямое создание Certificate (без аннотаций)

**Цель:** Больший контроль над параметрами сертификата.

```yaml
# 1. Certificate ресурс
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: my-domain-cert
  namespace: default
spec:
  secretName: my-domain-tls
  duration: 2160h  # 90 дней
  renewBefore: 360h  # 15 дней
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - my-domain.com
    - www.my-domain.com
  privateKey:
    algorithm: ECDSA
    size: 256
    encoding: PKCS8
---
# 2. Ingress без аннотаций cert-manager
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-domain-ingress
  namespace: default
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - my-domain.com
    - www.my-domain.com
    secretName: my-domain-tls  # Ссылка на Secret из Certificate
  rules:
  - host: my-domain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: my-service
            port:
              number: 80
```

**Преимущества:**

- Полный контроль над `duration`, `renewBefore`, `privateKey`
- Можно использовать для не-Ingress сценариев (mTLS, Secret для приложений)

---

## Дополнительная информация

### Частые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Waiting for HTTP-01 challenge` | Ingress недоступен извне | Проверить LoadBalancer, firewall |
| `Secret not found` | Certificate ещё не создан | Подождать 1-2 минуты, проверить логи |
| `Issuer not found` | Неправильный namespace/имя | Проверить `issuerRef` или аннотацию |
| `Rate limit exceeded` | Лимит Let's Encrypt | Использовать staging, подождать |

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| Ingress аннотации | **10** | Официальная документация cert-manager.io |
| Временные сертификаты | **9** | Подтверждено в релизах 1.10+ |
| Wildcard через DNS-01 | **10** | Стандартный паттерн ACME |
