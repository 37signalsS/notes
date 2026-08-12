# Cert-manager: Сценарии интеграции с Ingress

## Определения

**Сценарии интеграции** — набор практических паттернов конфигурации ресурсов Ingress для автоматизированного управления TLS-сертификатами. Сценарии охватывают различные методы валидации (HTTP-01, DNS-01), топологии доменов (SAN, Wildcard) и специфические требования облачных провайдеров.

**Subject Alternative Name (SAN)** — расширение X.509, позволяющее защитить несколько доменных имен одним сертификатом. В контексте Ingress это реализуется через перечисление нескольких хостов в одной секции `tls`.

**ACME Solver** — механизм подтверждения владения доменом. При интеграции с Ingress выбор солвера чаще всего происходит автоматически на основе конфигурации `Issuer`/`ClusterIssuer`, но может уточняться через аннотации.

> **См. также:** [Обзор интеграции](./overview.md) — концепции, аннотации и механизм работы ingress-shim.

---

## Основные концепции

Эффективное использование сценариев в 2026 году базируется на следующих принципах:

1.  **Приоритет безопасности:** Использование современных алгоритмов (**Ed25519**, **ECDSA**) и обязательная ротация приватных ключей (`rotationPolicy: Always`).
2.  **Автоматизация продления:** Использование протокола **ARI** для минимизации рисков истечения срока действия (настройка на стороне контроллера, прозрачно для Ingress).
3.  **Изоляция доменов:** Решение о том, использовать ли один SAN-сертификат для всех сервисов или отдельные сертификаты для каждого Ingress, должно основываться на требованиях к безопасности и лимитах CA.

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

### Смотрите также

- **[Обзор интеграции](./overview.md)** — концепции, аннотации, диагностика
- **[Cert-manager: Определения](../definitions.md)** — база знаний по CRD
- **[Gateway API: Сценарии](../gateway_api/practical_scenarios.md)** — использование cert-manager с новым стандартом Gateway API
- **[Troubleshooting](../Administration/troubleshooting.md)** — глубокая диагностика контроллера
