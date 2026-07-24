# Cert-manager: Сценарии интеграции с Ingress

## Определения

**Сценарии интеграции** — практические примеры использования cert-manager с Ingress для автоматического получения и продления TLS-сертификатов. Каждый сценарий демонстрирует конкретный паттерн конфигурации в зависимости от требований к безопасности и доменам.

**ingress-shim** — встроенный контроллер cert-manager, который отслеживает объекты Ingress и автоматически создаёт ресурсы `Certificate` на основе аннотаций.

> **См. также:** [Обзор интеграции](./overview.md) — концепции, аннотации, поток работы, диагностика.

---

## Основные концепции

Все сценарии базируются на автоматизации жизненного цикла:

1. **Обнаружение:** Ingress с аннотацией `cert-manager.io/cluster-issuer` или `cert-manager.io/issuer`.
2. **Генерация:** Автоматическое создание ресурса `Certificate`.
3. **Валидация:** Выполнение ACME-проверки (HTTP-01 или DNS-01).
4. **Применение:** Сохранение сертификата в Secret, который используется Ingress-контроллером.

**Стандарты 2026 года:**
*   **Срок действия:** Let's Encrypt перешел на 45-дневные сертификаты (`duration: 1080h`).
*   **ARI (ACME Renewal Information):** cert-manager 1.15+ поддерживает ARI, позволяя CA рекомендовать точное время продления.
*   **Безопасность:** Рекомендуется политика ротации ключей `Always`.

---

## Практические сценарии

### Сценарий 1: Базовый Ingress с HTTP-01

**Цель:** Автоматическое получение сертификата для одного домена через стандартную проверку.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app-ingress
  namespace: default
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    # Стандарт безопасности 2026 года
    cert-manager.io/private-key-rotation-policy: "Always"
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

**Особенности:**
- cert-manager автоматически создаст `Certificate` с `duration: 1080h` (45 дней) для Let's Encrypt.
- HTTP-01 проверка требует доступности порта 80 из интернета.

---

### Сценарий 2: Несколько доменов в одном Ingress (SAN)

**Цель:** Использование одного сертификата (Subject Alternative Name) для группы доменов.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: multi-domain-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    # Явное указание CN (необязательно, но полезно для логов)
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

### Сценарий 3: Временный сертификат до ACME-проверки

**Цель:** Обеспечить работу TLS немедленно (через самоподписанный сертификат), пока идет процесс проверки ACME.

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

---

### Сценарий 4: DNS-01 для Wildcard-доменов

**Цель:** Получение wildcard-сертификата `*.example.com`, когда HTTP-проверка невозможна или неудобна.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: wildcard-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    # Тип проверки через аннотацию поддерживается не всеми версиями,
    # чаще настраивается в самом Issuer.
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
```

> **Важно:** HTTP-01 проверка **не поддерживает** wildcard-сертификаты. Требуется настроенный DNS-01 solver в ClusterIssuer.

---

### Сценарий 5: Прямое создание Certificate (Полный контроль)

**Цель:** Тонкая настройка параметров (алгоритмы, сроки), недоступных через аннотации Ingress.

```yaml
# 1. Ресурс Certificate
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: my-domain-cert
  namespace: default
spec:
  secretName: my-domain-tls
  duration: 1080h       # 45 дней (стандарт 2026)
  renewBefore: 168h     # 7 дней
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - my-domain.com
    - www.my-domain.com
  privateKey:
    algorithm: ECDSA
    size: 256
    rotationPolicy: Always
    encoding: PKCS8
---
# 2. Ingress ссылается на уже существующий Secret
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-domain-ingress
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - my-domain.com
    secretName: my-domain-tls
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

---

## Дополнительная информация

### Диагностика

Диагностика cert-manager подробно описана в [Обзоре интеграции](./overview.md#диагностика-через-cmctl).

Краткие команды для проверки объектов выпуска:

```bash
# Проверка статуса сертификата
kubectl get certificate -n <namespace>

# Проверка процесса ACME-вызова (Challenge)
kubectl get challenge -n <namespace>

# Просмотр статуса заказа (Order)
kubectl get order -n <namespace>
```

### Смотрите также

- **[Обзор интеграции](./overview.md)** — концепции, аннотации, диагностика, частые ошибки
- **[Cert-manager: Определения](../definitions.md)** — CRD, Issuer, ACME Solvers
- **[Let's Encrypt](../LetsEncrypt/index.md)** — публичные сертификаты через ACME
- **[Gateway API: Сценарии](../gateway_api/practical_scenarios.md)** — современный подход к TLS в Kubernetes
