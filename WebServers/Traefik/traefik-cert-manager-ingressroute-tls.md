# Автоматический TLS с cert-manager, Let's Encrypt и Traefik IngressRoute

**Актуально для:** cert-manager 1.21.x / Traefik 3.7.x

## Определения

**ClusterIssuer** — общекластерный ресурс cert-manager, описывающий метод взаимодействия с центром сертификации (CA). В отличие от `Issuer`, доступен во всех пространствах имен.

**Certificate** — ресурс cert-manager, определяющий желаемые параметры TLS-сертификата (DNS-имена, алгоритм ключа, срок действия, политика продления). На его основе cert-manager инициирует процесс выпуска через цепочку `CertificateRequest → Order → Challenge → Secret`.

**IngressRoute** — CRD Traefik (`traefik.io/v1alpha1`), заменяющий стандартный Kubernetes Ingress. Описывает роутер, middleware и сервис в одном объекте.

**Middleware** — CRD Traefik для переиспользуемых трансформаций запросов (перенаправления, префиксы, аутентификация, rate limiting).

**HTTP-01 challenge** — метод ACME-проверки владения доменом: сервер проверяет доступность токена по адресу `http://<domain>/.well-known/acme-challenge/<token>` на порту 80.

**Subject Alternative Name (SAN)** — расширение X.509, позволяющее защитить несколько доменных имен одним сертификатом.

**ACME Order / Challenge** — внутренние ресурсы cert-manager: `Order` представляет процесс заказа сертификата у ACME-сервера, `Challenge` — конкретную задачу проверки владения доменом.

---

## Основные концепции

### Архитектура автоматического TLS

Каждый поддомен на сервере получает действующий TLS-сертификат автоматически. Никаких ручных продлений, никаких cronjob с certbot, никаких wildcard-сертификатов. Полный цикл — от ClusterIssuer до замочка в браузере:

```text
ClusterIssuer (ACME) → Certificate (SAN) → Secret (TLS) → IngressRoute (TLS) → Traefik (Data Plane)
```

### Два issuer: staging и production

Staging-issuer не расходует лимиты Let's Encrypt (50 сертификатов на домен в неделю). Всегда использовать staging при настройке нового домена — если HTTP-01 challenge провалится (неправильный DNS, заблокирован порт 80), лимиты production не сгорят.

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
      name: letsencrypt-staging
    solvers:
      - http01:
          ingress:
            ingressClassName: traefik
---
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
      - http01:
          ingress:
            ingressClassName: traefik
```

> **Примечание:** `ingressClassName` — современный синтаксис (cert-manager v1.x), использующий Kubernetes IngressClass. Существующие файлы базы знаний используют устаревшее поле `class` (например, `class: nginx` в [cert-manager/ingress/scenarios.md](../../Kubernetes/ToolsUtilities/cert_manager/ingress/scenarios.md)). Оба варианта работают; `ingressClassName` предпочтительнее.

### Механика HTTP-01 challenge

Solver `http01` доказывает владение доменом, отдавая токен по адресу:

```
http://<domain>/.well-known/acme-challenge/<token>
```

cert-manager временно создаёт объект Ingress для этого пути. Traefik подхватывает его и маршрутизирует запрос ACME-сервера к поду cert-manager.

**Обязательные условия:**

- A-запись домена должна указывать на публичный IP сервера до запроса сертификата.
- Порт 80 должен быть открыт. Traefik слушает на 80 с `hostNetwork: true` и перенаправляет на 443 — но ACME challenge обслуживается на 80 до срабатывания редиректа.

---

## Практические сценарии

### Сценарий 1: Полный цикл — от ClusterIssuer до IngressRoute

#### Шаг 1. Создание ClusterIssuer (staging → production)

```yaml
# Сначала протестируйте через staging
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging
spec:
  acme:
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-staging
    solvers:
      - http01:
          ingress:
            ingressClassName: traefik
```

```bash
# Проверка, что ClusterIssuer готов
kubectl get clusterissuer letsencrypt-staging
# → NAME                   READY   REASON
# → letsencrypt-staging    True    ResourceIsAlwaysReconciled
```

#### Шаг 2. Объект Certificate с SAN

Все поддомены используют общий сертификат с несколькими SAN. cert-manager:

- Запрашивает единый сертификат для всех имён
- Сохраняет ключ и цепочку сертификатов в Secret `site-tls`
- Автоматически продлевает за ~30 дней до истечения
- Запускает ротацию при добавлении новых записей в `dnsNames`

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: site-tls
  namespace: default
spec:
  secretName: site-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - example.com
    - www.example.com
    - blog.example.com
    - cv.example.com
    - proxy.example.com
  renewBefore: 720h  # за 30 дней до истечения
```

```bash
# Проверка, что сертификат выпущен
kubectl get certificate site-tls -n default
# → NAME      READY   SECRET     AGE
# → site-tls  True    site-tls   2m
```

#### Шаг 3. Привязка в IngressRoute

Traefik использует собственный CRD (`IngressRoute`) вместо стандартного Ingress. Секция `tls` ссылается на тот же Secret:

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: site-main
  namespace: default
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`example.com`)
      kind: Rule
      services:
        - name: site-backend
          port: 8000
    - match: Host(`www.example.com`)
      kind: Rule
      middlewares:
        - name: www-redirect
      services:
        - name: site-backend
          port: 8000
  tls:
    secretName: site-tls
```

> **Важно:** При использовании `ingressClassName: traefik` в ClusterIssuer, cert-manager создаёт временный **стандартный Ingress** (не IngressRoute) для HTTP-01 challenge. Traefik обрабатывает его через встроенный Ingress-провайдер. Для основного роутинга используется IngressRoute — это два разных механизма, оба поддерживаются Traefik.

### Сценарий 2: Middleware — поддомен → path prefix

FastAPI-приложение обслуживает всё через один роутер. Поддомены переписываются в path-префиксы через Traefik Middleware:

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: blog-prefix
  namespace: default
spec:
  addPrefix:
    prefix: /weblog
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: www-redirect
  namespace: default
spec:
  redirectRegex:
    regex: "^https://www\\.(.+)"
    replacement: "https://${1}"
    permanent: true
```

`blog.example.com/` → приложение видит `/weblog/`. Один под, один Service, один Deployment обрабатывает все поддомены.

Полный IngressRoute с middleware:

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: site-routing
  namespace: default
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`example.com`)
      kind: Rule
      services:
        - name: site-backend
          port: 8000
    - match: Host(`blog.example.com`)
      kind: Rule
      middlewares:
        - name: blog-prefix
      services:
        - name: site-backend
          port: 8000
    - match: Host(`www.example.com`)
      kind: Rule
      middlewares:
        - name: www-redirect
      services:
        - name: site-backend
          port: 8000
  tls:
    secretName: site-tls
```

---

## Проверка статуса сертификата

```bash
# Список всех сертификатов
kubectl get certificate -A

# Детали конкретного сертификата
kubectl describe certificate site-tls

# ACME order (если сертификат ожидает выпуска)
kubectl get orders -A
kubectl describe order <order-name>

# Challenge (если order ожидает)
kubectl get challenges -A
kubectl describe challenge <challenge-name>
```

Условие `Ready: True` — сертификат выпущен и сохранён. Если статус застрял в `False`, отследить цепочку `order → challenge`.

```bash
# Быстрая проверка через cmctl
cmctl status certificate site-tls -n default
# → Certificate: Ready=True, Secret: site-tls, Not After: 2026-11-15T00:00:00Z
```

---

## Отладка HTTP-01 challenge вручную

```bash
# Проверить, что solver-под cert-manager запущен
kubectl get pods -n cert-manager

# Проверить, что Traefik подхватил временный Ingress
kubectl get ingress -A | grep acme

# Проверить доступность порта 80
curl -v http://example.com/.well-known/acme-challenge/test
# → HTTP/1.1 404 (Traefik обрабатывает запрос, но токен не существует)
# → Если 502/503 или таймаут — порт 80 недоступен или NetworkPolicy блокирует
```

---

## Принудительное обновление сертификата

cert-manager продлевает автоматически. Для принудительного обновления:

```bash
kubectl delete secret site-tls
```

cert-manager обнаруживает отсутствие Secret, повторно запускает ACME-процесс и создаёт новый сертификат. Traefik короткое время отдаёт старый сертификат из памяти (обычно менее 60 секунд).

```bash
# Проверка после принудительного обновления
kubectl get order -n default -w
# → Цикл: ENNEDED → new order created

# Верификация нового сертификата
kubectl get secret site-tls -n default -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -dates
```

---

## Лимиты Let's Encrypt

| Лимит | Production | Staging |
| :--- | :--- | :--- |
| **Сертификаты на домен** | 50 / неделю | 30 000 / неделю |
| **Ошибки на hostname** | 5 / час | Нет (но браузеры staging-сертификатам не доверяют) |
| **Duplicate certificates** | 5 / неделю | — |

При превышении лимитов проверить все выпущенные сертификаты: https://crt.sh/?q=example.com.

---

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Certificate stuck в `Pending`** | DNS не указывает на IP, порт 80 закрыт | Проверить A-запись и `curl http://<domain>/.well-known/acme-challenge/test` |
| **Challenge в `pending`/`processing`** | Traefik не подхватил временный Ingress, NetworkPolicy блокирует порт 80 | `kubectl get ingress -A \| grep acme`, проверить NetworkPolicy для namespace `cert-manager` |
| **Challenge в `invalid`** | Лимиты Let's Encrypt production исчерпаны | Проверить https://crt.sh/?q=<domain>; использовать staging для тестов |
| **Traefik не подхватывает Secret** | IngressRoute и Certificate в разных namespace, нет TLS-опции | Убедиться, что `secretName` в IngressRoute совпадает с `spec.secretName` в Certificate; Secret должен быть в том же namespace |
| **Сертификат выдан, но браузер не доверяет** | Использован staging-issuer вместо production | Проверить `issuerRef.name` в Certificate — должен быть `letsencrypt-prod` |
| **`www.example.com` не редиректится** | Middleware `www-redirect` не применяется | Проверить порядок middleware в IngressRoute, убедиться что `match` включает `www.example.com` |
| **Сертификат не обновляется после `kubectl delete secret`** | cert-manager не пересоздаёт Secret | `kubectl get certificate -n <namespace>` — проверить статус; удалить и Order и Challenge при необходимости |

---

## Лучшие практики

1. **Staging-first:** Всегда тестируйте новую конфигурацию через `letsencrypt-staging` перед переходом на `letsencrypt-prod`. Rate limit production: 50 сертификатов/неделю на домен.
2. **SAN-сертификаты:** Используйте один сертификат с несколькими SAN для связанных поддоменов. Это экономит лимиты и упрощает ротацию.
3. **Ротация ключей:** Добавляйте `privateKey.rotationPolicy: Always` для production-сертификатов (см. [cert-manager definitions](../../Kubernetes/ToolsUtilities/cert_manager/definitions.md)).
4. **ECDSA:** Используйте `privateKey.algorithm: ECDSA` с `size: 256` для новых сертификатов (рекомендация 2026 года, см. [cert-manager definitions](../../Kubernetes/ToolsUtilities/cert_manager/definitions.md)).
5. **ARI:** В cert-manager v1.21+ ARI включен по умолчанию. Не указывайте `renewBefore`, если используете ARI — пусть CA управляет окном продления.
6. **NetworkPolicy:** Разрешите исходящий трафик от подов cert-manager к ACME API (443) и входящий на порт 80 для HTTP-01 challenge.
7. **Cleanup:** При удалении `Certificate` автоматически удаляются `Order`, `Challenge` и `Secret`. `ClusterIssuer` и его account key Secret удаляются вручную.

---

## Дополнительная информация

### Связанные документы

- **[Cert-manager: Интеграция с Ingress](../../Kubernetes/ToolsUtilities/cert_manager/ingress/overview.md)** — концепции ingress-shim, аннотации, диагностика для стандартного Ingress.
- **[Cert-manager: Сценарии интеграции с Ingress](../../Kubernetes/ToolsUtilities/cert_manager/ingress/scenarios.md)** — SAN-сертификаты, staging-first, edit-in-place для облачных Ingress.
- **[Cert-manager: Let's Encrypt сценарии](../../Kubernetes/ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md)** — ClusterIssuer, Certificate, DNS-01, ARI.
- **[Traefik в Kubernetes: CRD, RBAC, Helm](./traefik-kubernetes.md)** — IngressRoute CRD, Middleware, TLSOption, NetworkPolicy.
- **[Traefik: TLS Options и mTLS](./traefik-tls-options.md)** — политики шифрования, passthrough, mTLS.
- **[Traefik: Мониторинг сертификатов](./traefik-cert-monitoring.md)** — expiration monitoring, Prometheus alerts, внешний ACME handler.
- **[Traefik: Middleware для управления трафиком](./traefik-middlewares-traffic.md)** — RateLimit, CircuitBreaker, Retry, Compress.
- **[Traefik: Rules и приоритеты роутинга](./traefik-routers-and-rules.md)** — Host/Path матчеры, redirectRegex, порядок применения middleware.
- **[Gateway API: Traefik](../../Kubernetes/Networking/gateway_api/traefik.md)** — современная альтернатива IngressRoute через Gateway API.
