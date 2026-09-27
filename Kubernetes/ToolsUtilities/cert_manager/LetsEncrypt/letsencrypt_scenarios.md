# Let's Encrypt: Практические сценарии в Kubernetes

## Определения

**ClusterIssuer** — общекластерный ресурс cert-manager, описывающий метод взаимодействия с центром сертификации (CA). В отличие от обычного `Issuer`, он доступен для всех пространств имен в кластере.

**Issuer** — ресурс cert-manager, привязанный к одному namespace. Используется, если CA-сертификат или ключ должны оставаться в пределах одного пространства имен (из соображений безопасности).

**Certificate** — ресурс, определяющий желаемые параметры TLS-сертификата (DNS-имена, алгоритм ключа, срок действия). На его основе cert-manager инициирует процесс выпуска через цепочку CertificateRequest → Order → Challenge.

**ECDSA (Elliptic Curve Digital Signature Algorithm)** — современный алгоритм цифровой подписи, обеспечивающий более высокую безопасность и производительность при меньшем размере ключа по сравнению с RSA. В 2026 году ECDSA P-256 является предпочтительным выбором для Let's Encrypt.

**preferredChain** — параметр, позволяющий выбрать конкретную цепочку доверия (например, ISRG Root X1), если CA предлагает несколько альтернативных путей. Влияет на то, какой промежуточный сертификат будет включён в Secret.

**ACME Account** — учётная запись в ACME API, привязанная к паре асимметричных ключей (ECDSA P-256 или RSA 3072+). Все API-запросы подписываются приватным ключом аккаунта. Адрес аккаунта (`Account URL`) используется в JWS заголовке `kid`.

**Replay-Nonce** — одноразовый токен, выдаваемый ACME API и встраиваемый в каждый JWS-запрос. Защищает от повторных атак (replay attacks). Nonce обновляется автоматически перед каждым запросом через заголовок `Replay-Nonce`.

**ACME Order** — ресурс, представляющий процесс заказа сертификата. Содержит список доменов, статус (`pending` → `ready` → `processing` → `valid`), ссылки на authority chains и идентификаторы Challenge. В cert-manager Order — это CRD.

**ACME Challenge** — задача проверки владения доменом (HTTP-01, DNS-01, TLS-ALPN-01), создаваемая в рамках Order. Статус Challenge: `pending` → `processing` → `valid` (успех) или `invalid` (сбой).

**Authorization Object** — ACME-ресурс, описывающий права на управление конкретным доменом. Содержит статус (`valid`, `invalid`, `deactivated`, `expired`, `revoked`) и список доступных Challenge-типов. cert-manager запрашивает Authorization перед созданием Order.

**Self-Check** — внутренняя проверка cert-manager перед отправкой подтверждения в ACME API. Контроллер сам обращается к созданному эндпоинту (HTTP-01) или проверяет TXT-запись (DNS-01), чтобы убедиться в доступности токена. Если Self-Check не проходит, Challenge остаётся в статусе `pending`.

**Certificate Chain** — цепочка доверия, состоящая из leaf-сертификата, промежуточного (intermediate) и корневого (root). Let's Encrypt выдаёт через промежуточные CA (R10–R14 для RSA, E5–E9 для ECDSA), кросс-подписанные ISRG Root X1. Неполная цепочка приводит к ошибкам TLS на клиенте.

**ACME Directory** — JSON-документ по адресу `/directory`, содержащий URLs всех доступных ACME-эндпоинтов (`newNonce`, `newAccount`, `newOrder`, `revokeCert`, `keyChange`). cert-manager запрашивает Directory при первом обращении к CA.

---

## Основные концепции

### Жизненный цикл заказа (Order Flow)

Для успешного применения сценариев важно понимать последовательность действий контроллера:

1. **Certificate**: Пользователь определяет параметры (DNS-имена, алгоритм ключа, Issuer).
2. **CertificateRequest**: Контроллер генерирует CSR и создаёт CertificateRequest.
3. **Order**: cert-manager отправляет `newOrder` в ACME API с указанием доменов.
4. **Authorization**: Для каждого домена ACME создаёт Authorization с доступными Challenge-типами.
5. **Challenge**: cert-manager выбирает доступный тип (HTTP-01 или DNS-01) и создаёт ресурс Challenge.
6. **Self-Check**: Контроллер проверяет доступность токена перед подтверждением ACME.
7. **Validation**: ACME-сервер проверяет владение доменом.
8. **Finalize**: cert-manager отправляет CSR через `finalize`.
9. **Certificate Download**: Полученный сертификат сохраняется в Kubernetes Secret.

**Статусы Order:**

| Статус | Описание |
| :--- | :--- |
| `pending` | Order создан, ожидает прохождения Challenge |
| `ready` | Все Challenge пройдены, ожидает `finalize` |
| `processing` | CSR отправлен, ожидается ответ от CA |
| `valid` | Сертификат выпущен и сохранён в Secret |
| `invalid` | Ошибка в одном или нескольких Challenge |

**Статусы Challenge:**

| Статус | Описание |
| :--- | :--- |
| `pending` | Challenge создан, Self-Check не пройден |
| `processing` | Self-Check пройден, ожидается проверка от ACME |
| `valid` | Проверка пройдена успешно |
| `invalid` | Проверка не пройдена (ошибка DNS, Firewall, таймаут) |

### Подготовка к 45-дневным сертификатам (2025–2026)

В связи с планируемым переходом Let's Encrypt на 45-дневные сертификаты, рекомендуется использовать следующие параметры в ресурсах `Certificate` для автоматизации через ARI:

| Параметр | Рекомендация | Комментарий |
| :--- | :--- | :--- |
| `duration` | `1080h` (45 дней) | Соответствует будущему стандарту |
| `renewBefore` | — | **Рекомендуется не указывать**, чтобы cert-manager использовал ARI |
| `privateKey.algorithm` | `ECDSA` | Предпочтительно для новых инсталляций |

### ACME Directory и Авторизация

При первом обращении к ACME API cert-manager загружает Directory — JSON с URLs всех эндпоинтов:

```bash
# Просмотр доступных ACME-эндпоинтов
curl -s https://acme-v02.api.letsencrypt.org/directory | jq .
# → {
#   "newNonce": "https://acme-v02.api.letsencrypt.org/new-nonce",
#   "newAccount": "https://acme-v02.api.letsencrypt.org/new-acct",
#   "newOrder": "https://acme-v02.api.letsencrypt.org/new-order",
#   "revokeCert": "https://acme-v02.api.letsencrypt.org/revoke-cert",
#   "keyChange": "https://acme-v02.api.letsencrypt.org/key-change"
# }
```

**Authorization** создаётся для каждого домена в Order. Authorization содержит:
- `identifier`: домен (`{"type": "dns", "value": "api.example.com"}`)
- `status`: `valid` (уже подтверждён) или `pending` (требует Challenge)
- `challenges`: список доступных Challenge-типов (`http-01`, `dns-01`, `tls-alpn-01`)

---

## Практические сценарии

### Сценарий 1: Публичный Ingress с HTTP-01 (RSA)

Классический сценарий для большинства веб-приложений. Не требует доступа к DNS API. Подходит для Ingress-контроллеров с проксированием (nginx, traefik).

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-http01
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-http01-account-key
    solvers:
    - http01:
        ingress:
          ingressClassName: nginx
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: web-app-tls
  namespace: prod
spec:
  secretName: web-app-tls-secret
  issuerRef:
    name: letsencrypt-http01
    kind: ClusterIssuer
  commonName: app.example.com
  dnsNames:
    - app.example.com
  privateKey:
    algorithm: RSA
    size: 2048
```

**Требования:**
- Ingress-контроллер должен проксировать `/.well-known/acme-challenge/` на порт 80
- Порт 80 должен быть доступен извне (для проверки ACME-сервером)
- При балансировке HTTP-трафика через Load Balancer убедитесь, что ACME-запросы не перенаправляются на HTTPS

### Сценарий 2: Wildcard сертификат через DNS-01 (Cloudflare ECDSA)

Использование API Cloudflare для выпуска сертификата на все поддомены с использованием эллиптических кривых.

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-dns01-ecdsa
spec:
  acme:
    email: admin@example.com
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-dns01-account-key
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token
            key: api-token
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: wildcard-ecdsa-tls
  namespace: prod
spec:
  secretName: wildcard-ecdsa-tls-secret
  issuerRef:
    name: letsencrypt-dns01-ecdsa
    kind: ClusterIssuer
  commonName: "*.example.com"
  dnsNames:
    - "*.example.com"
    - "example.com"
  privateKey:
    algorithm: ECDSA
    size: 256
```

**Альтернативные DNS-провайдеры (DNS-01):**

| Провайдер | Конфигурация solver | Примечание |
| :--- | :--- | :--- |
| **Cloudflare** | `cloudflare.apiTokenSecretRef` | Рекомендуется API Token (не Global API Key) |
| **Route53** | `route53.accessKeyID` + `secretAccessKeySecretRef` | Требуется IAM-пользователь с `Route53:ChangeResourceRecordSets` |
| **RFC 2136** | `rfc2136.nameserver` + `tsigSecretSecretRef` | Для BIND9/PowerDNS с TSIG-аутентификацией |
| **Google Cloud DNS** | `cloudDNS.serviceAccountSecretRef` | JSON-ключ сервисного аккаунта |
| **Yandex Cloud DNS** | `yandexclouddns.serviceAccountKeyJSON` | JSON-ключ сервисного аккаунта |

### Сценарий 3: Управление цепочкой доверия (preferredChain)

Сценарий необходим, если клиенты (например, старые устройства) требуют специфического корневого сертификата.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: legacy-compat-tls
spec:
  secretName: legacy-compat-tls-secret
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  commonName: legacy.example.com
  issuerOptions:
    # Явный выбор цепочки ISRG Root X1 (RSA)
    preferredChain: "ISRG Root X1"
```

**Доступные цепочки Let's Encrypt (2025–2026):**

| Цепочка | Тип ключа | Рекомендация |
| :--- | :--- | :--- |
| `ISRG Root X1` | RSA (R10–R14) | **Рекомендуется** — максимальная совместимость |
| `ISRG Root X2` | ECDSA (E5–E9) | Только для кластеров с полной поддержкой ECDSA |
| `DST Root CA X3` | RSA | **Устаревший** (срок истёк 30.09.2021) — не использовать |

### Сценарий 4: Интеграция с Gateway API и HTTPRoute

Современный метод настройки TLS через аннотации Gateway API.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: main-gateway
  namespace: istio-system
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  gatewayClassName: istio
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    hostname: "*.example.com"
    tls:
      mode: Terminated
      certificateRefs:
      - name: gateway-wildcard-tls
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-route
  namespace: backend
spec:
  parentRefs:
  - name: main-gateway
    namespace: istio-system
  hostnames:
  - "api.example.com"
  rules:
  - backendRefs:
    - name: api-service
      port: 8080
```

### Сценарий 5: Миграция с Staging на Production

Алгоритм безопасного тестирования конфигурации без риска блокировок. Включает полные YAML-манифесты для Staging и Production.

**Шаг 1: Создание Staging Issuer и тестового Certificate:**

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging
spec:
  acme:
    # Staging API — не тратит лимиты Production
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-staging-account-key
    solvers:
    - http01:
        ingress:
          ingressClassName: nginx
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: test-app-tls
  namespace: staging
spec:
  secretName: test-app-tls-secret
  issuerRef:
    name: letsencrypt-staging
    kind: ClusterIssuer
  commonName: app.example.com
  dnsNames:
    - app.example.com
```

**Шаг 2: Проверка прохождения Challenge:**

```bash
# Проверка статуса Certificate
kubectl get certificate test-app-tls -n staging

# Просмотр Order и Challenge
kubectl get order -n staging
kubectl get challenge -n staging

# Детальная диагностика
cmctl status certificate test-app-tls -n staging
```

**Шаг 3: Переключение на Production Issuer:**

```yaml
# Обновлённый Certificate с Production Issuer
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: test-app-tls
  namespace: staging
spec:
  secretName: test-app-tls-secret
  issuerRef:
    # Замена на Production Issuer
    name: letsencrypt-prod
    kind: ClusterIssuer
  commonName: app.example.com
  dnsNames:
    - app.example.com
```

**Шаг 4: Верификация Production-сертификата:**

```bash
# Проверка, что сертификат выпущен Production CA
kubectl get secret test-app-tls-secret -n staging -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -issuer
# → issuer: ... / C=US / O=Let's Encrypt / CN=R11

# Проверка SAN
kubectl get secret test-app-tls-secret -n staging -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -ext subjectAltName
```

**Полезные команды для диагностики миграции:**

```bash
# Просмотр всех Certificate в namespace
kubectl get certificate -n staging -o custom-columns=\
  NAME:.metadata.name,\
  READY:.status.conditions[?(@.type=="Ready")].status,\
  SECRET:.spec.secretName,\
  ISSUER:.spec.issuerRef.name

# Просмотр Order с фильтрацией по статусу
kubectl get order -n staging -o json | jq -r '.items[] | "\(.metadata.name) \(.status.state)"'

# Удаление зависшего Order (для перезапуска)
kubectl delete order <order-name> -n staging
```

### Сценарий 6: TLS-ALPN-01 через cert-manager

Проверка владения доменом через TLS-рукопожатие на порту 443 с использованием специального ALPN-протокола. Не требует HTTP-доступа, работает на уровне L4.

**Преимущества TLS-ALPN-01:**
- Не требует проксирования HTTP (в отличие от HTTP-01)
- Работает за NAT/Firewall без проброса порта 80
- Подходит для gRPC-сервисов и TCP-приложений

**Ограничения:**
- Требует прямого доступа к порту 443 (без L7-прокси перед подом)
- Не поддерживает wildcards (`*.example.com`)
- Не все Ingress-контроллеры поддерживают ALPN-протокол

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-tls-alpn
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-tls-alpn-account-key
    solvers:
    - tlsALPN01: {}
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: grpc-service-tls
  namespace: backend
spec:
  secretName: grpc-service-tls-secret
  issuerRef:
    name: letsencrypt-tls-alpn
    kind: ClusterIssuer
  commonName: grpc.example.com
  dnsNames:
    - grpc.example.com
```

**Диагностика TLS-ALPN-01:**

```bash
# Проверка ALPN-поддержки на Ingress-контроллере
openssl s_client -connect grpc.example.com:443 -alpn h2 2>/dev/null | grep "ALPN"

# Проверка ACME TLS-ALPN-01 через curl
curl -k --tls-max 1.3 --alpn acme-tls/1 https://grpc.example.com:443

# Просмотр Challenge (должен быть tls-alpn-01)
kubectl get challenge -n backend -o json | jq -r '.items[] | "\(.metadata.name) \(.spec.type)"'
```

### Сценарий 7: Принудительное продление сертификата (Force Renewal)

Сценарий для экстренных ситуаций: сертификат истёк, заблокирован ACME или требует немедленного перевыпуска.

**Причины принудительного продления:**
- Сертификат истёк (ACME-сервер может отклонить заказ)
- Смена алгоритма ключа (RSA → ECDSA)
- Массовая ротация ключей (Security Policy)
- Ошибка ARI (сбой API, неверное suggestedWindow)
- Отзыв сертификата (Compromise)

```bash
# 1. Принудительное продление через cmctl
cmctl renew <cert-name> -n <namespace>

# 2. Принудительное продление всех сертификатов в namespace
cmctl renew --all -n <namespace>

# 3. Принудительное продление всех сертификатов во всех namespace
cmctl renew --all -A

# 4. Если cmctl недоступен — удаление Order для перезапуска
kubectl delete order <order-name> -n <namespace>

# 5. Если Challenge завис — удаление Challenge
kubectl delete challenge <challenge-name> -n <namespace>

# 6. Полная перезапуск выпуска (удаление Certificate + Secret)
kubectl delete secret <secret-name> -n <namespace>
kubectl delete certificate <cert-name> -n <namespace>
# cert-manager автоматически создаст новый Order
```

**Проверка после принудительного продления:**

```bash
# Мониторинг нового Order
kubectl get order -n <namespace> -w

# Проверка, что сертификат выпущен
cmctl status certificate <cert-name> -n <namespace>

# Верификация нового сертификата
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -dates
```

### Сценарий 8: openssl-проверка цепочки доверия

Для подтверждения корректности выпущенного сертификата и его цепочки доверия.

```bash
# Извлечение сертификата из Kubernetes Secret
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | base64 -d > /tmp/tls.crt

# Просмотр issuer и subject
openssl x509 -in /tmp/tls.crt -noout -issuer -subject

# Проверка SAN (Subject Alternative Names)
openssl x509 -in /tmp/tls.crt -noout -ext subjectAltName

# Проверка цепочки доверия
openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt /tmp/tls.crt

# Проверка количества сертификатов в цепочке
grep -c "BEGIN CERTIFICATE" /tmp/tls.crt

# Просмотр цепочки (каждый сертификат)
openssl crl2pkcs7 -nocrl -certfile /tmp/tls.crt | openssl pkcs7 -print_certs -noout

# Проверка CT-логов (Pre-issuance SCT)
openssl x509 -in /tmp/tls.crt -text -noout | grep -A 5 "CT Precertificate SCTs"

# Проверка расширений (EKU, Key Usage)
openssl x509 -in /tmp/tls.crt -noout -text | grep -A 3 "Extended Key Usage"
```

**Диагностика неполной цепочки:**

```bash
# Проверка AIA (Authority Information Access)
openssl x509 -in /tmp/tls.crt -noout -text | grep -A 3 "Authority Info Access"

# Если AIA содержит OCSP responder — цепочка полная
# Если AIA пуст — промежуточный сертификат не включён в Secret

# Проверка полной цепочки (leaf + intermediate)
openssl s_client -connect api.example.com:443 -showcerts 2>/dev/null | grep -E "Certificate chain|subject|issuer"
```

### Сценарий 9: Мониторинг состояния через cmctl

Использование `cmctl` для операционного мониторинга сертификатов в кластере.

```bash
# Быстрая проверка API-сервера cert-manager
cmctl check api

# Проверка статуса конкретного сертификата
cmctl status certificate <cert-name> -n <namespace>

# Инспекция Secret (содержимое сертификата)
cmctl inspect secret <secret-name> -n <namespace>

# Автоматическая диагностика (cert-manager v1.20+)
cmctl diagnose certificate <cert-name> -n <namespace>

# Диагностика всех сертификатов в namespace
cmctl diagnose certificate --namespace <namespace> --all

# Просмотр всех Certificate с кастомными колонками
kubectl get certificate -A -o custom-columns=\
  NAME:.metadata.name,\
  NAMESPACE:.metadata.namespace,\
  READY:.status.conditions[?(@.type=="Ready")].status,\
  EXPIRY:.status.notAfter,\
  ISSUER:.spec.issuerRef.name

# Просмотр всех Order с фильтрацией
kubectl get order -A -o json | jq -r '.items[] | "\(.metadata.namespace)/\(.metadata.name) \(.status.state)"' | sort

# Мониторинг Challenge в реальном времени
kubectl get challenge -A -w
```

**Пример вывода `cmctl status certificate`:**

```
Name: api-tls
Namespace: prod
Conditions:
  Ready: True, Reason: Issuing, Message: Certificate issued successfully
  Issuing: False, Reason: Issued, Message: Certificate has been issued
Secret: api-tls-secret
Not Before: 2025-01-15T00:00:00Z
Not After: 2025-04-15T00:00:00Z
DNS Names: api.example.com
Issuer: letsencrypt-prod (ClusterIssuer)
```

### Сценарий 10: Диагностика ошибок ACME

Пошаговая диагностика при сбое выпуска сертификата.

```bash
# Шаг 1: Проверка статуса Certificate
kubectl get certificate -n <namespace>
# → READY: False, Reason: Issuing

# Шаг 2: Просмотр Order
kubectl get order -n <namespace>
# → STATE: invalid

# Шаг 3: Просмотр Challenge
kubectl get challenge -n <namespace>
# → STATE: invalid, REASON: Challenge failed

# Шаг 4: Детали Challenge
kubectl describe challenge <challenge-name> -n <namespace>
# → Events: Self-check failed, reason: HTTP-01 self-check failed

# Шаг 5: Проверка доступности токена (HTTP-01)
TOKEN="<token из Challenge spec.token>"
curl -v http://app.example.com/.well-known/acme-challenge/$TOKEN
# → Должен вернуть содержимое токена

# Шаг 6: Проверка DNS-записи (DNS-01)
DOMAIN="app.example.com"
dig TXT _acme-challenge.$DOMAIN
# → Должен содержать TXT-запись с токеном

# Шаг 7: Проверка Firewall (для HTTP-01)
kubectl logs -n cert-manager -l app=cert-manager | grep "Connection refused"
# → Если ошибка подключения — проверьте NetworkPolicy и Ingress

# Шаг 8: Логи контроллера
kubectl logs -n cert-manager -l app=cert-manager --tail=50 | grep $DOMAIN
```

**Таблица распространённых ошибок ACME:**

| Ошибка ACME | Причина | Решение |
| :--- | :--- | :--- |
| `urn:ietf:params:acme:error:unauthorized` | Невалидный Account Key | Пересоздайте Issuer (удалите Secret с аккаунтным ключом) |
| `urn:ietf:params:acme:error:rateLimited` | Превышен лимит запросов | Используйте Staging для тестов; дождитесь сброса лимитов |
| `urn:ietf:params:acme:error:badNonce` | Повторный Nonce | cert-manager обновит Nonce автоматически; перезапустите Order |
| `urn:ietf:params:acme:error:dns` | Ошибка DNS-резолва | Проверьте DNS-провайдер и TXT-запись |
| `urn:ietf:params:acme:error:connection` | Сервер недоступен | Проверьте Firewall, NetworkPolicy, Ingress |
| `urn:ietf:params:acme:error:externalAccountRequired` | Требуется EAB | Добавьте `externalAccountBinding` в Issuer |

---

## Дополнительная информация

### Рекомендации по эксплуатации (Best Practices)

1. **Разделение Issuer**: Рекомендуется иметь отдельные `ClusterIssuer` для HTTP-01 и DNS-01 проверок. Это упрощает диагностику и позволяет использовать разные CA-аккаунты.

2. **Использование ECDSA**: С 2025 года ECDSA P-256 является предпочтительным выбором для повышения производительности TLS-handshake. Указывайте `privateKey.algorithm: ECDSA` во всех новых Certificate.

3. **Контроль лимитов**: При массовом перевыпуске (миграция кластера, смена CA) следите за лимитом Duplicate Certificates (5 в неделю для Production). Используйте Staging для тестов.

4. **Staging-first**: Для любых тестов всегда используйте `server: https://acme-staging-v02.api.letsencrypt.org/directory`. Ошибки DNS-01 в Staging не тратят лимиты Production.

5. **Cleanup**: Удаляйте зависшие Order и Challenge. cert-manager автоматически инициирует новую попытку:
   ```bash
   kubectl delete order <order-name> -n <namespace>
   kubectl delete challenge <challenge-name> -n <namespace>
   ```

6. **Resource Limits**: Рекомендуется минимум 256Mi для пода `cert-manager` controller и 128Mi для webhook. Недостаток памяти приводит к перезагрузкам при обработке большого количества Challenge.

7. **NetworkPolicy**: Убедитесь, что NetworkPolicy разрешает исходящие подключения от пода cert-manager к ACME API (443 порт) и входящие для HTTP-01 (80 порт).

8. **Аккаунт Let's Encrypt**: Регистрация аккаунта происходит автоматически при первом применении Issuer. Приватный ключ хранится в Secret `cert-manager-issuer-account-<issuer-name>` в namespace `cert-manager`.

### Смотрите также

- **[Углублённые концепции ACME](./letsencrypt_concepts.md)** — архитектура ARI, CT-логи и безопасность.
- **[Диагностика и Troubleshooting](./letsencrypt_advanced.md)** — решение проблем с прохождением проверок.
- **[Реагирование на инциденты (Incident Response)](./letsencrypt_incident_response.md)** — процедуры при просроченных сертификатах и компрометации ключей.
- **[Terraform: Управление сертификатами](./letsencrypt_terraform.md)** — ACME provider для не-Kubernetes серверов.
- **[Сетевая безопасность (Network Security)](./letsencrypt_network_security.md)** — firewall, egress и NetworkPolicy для ACME проверок.
- **[Cert-manager: Определения](../../definitions.md)** — базовая структура ресурсов контроллера.
- **[Cert-manager: Администрирование](../Administration/index.md)** — HA, ресурсы и ротация ключей.

---
