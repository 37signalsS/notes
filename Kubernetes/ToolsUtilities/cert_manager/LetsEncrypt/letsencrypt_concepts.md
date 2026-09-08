# Let's Encrypt: Углублённые концепции ACME

## Определения

**ACME (Automated Certificate Management Environment)** — протокол (RFC 8555), обеспечивающий полностью автоматизированное взаимодействие между клиентом (cert-manager) и центром сертификации (Let's Encrypt) для управления жизненным циклом TLS-сертификатов. Протокол определяет четыре базовые операции: регистрация аккаунта (`newAccount`), создание заказа (`newOrder`), прохождение проверки владения доменом (`challenge`) и получение сертификата (`certificate`). Каждое сообщение подписывается JWS и защищено от повторных атак через机制 Replay-Nonce.

**JWS (JSON Web Signature)** — стандарт (RFC 7515), используемый в ACME для обеспечения аутентификации, целостности и защиты от повторов (anti-replay) всех сообщений между клиентом и сервером. ACME требует использования **JSON Serialization** (RFC 7515, Section 3.2), а не компактной записи (Base64url-цепочка через точки). Каждый запрос содержит `protected` заголовок (с nonce, URL и ключом) и `payload`.

**External Account Binding (EAB)** — механизм привязки ACME-аккаунта к уже существующему учётной записи в CA через внешний ключ (KID + HMAC). Используется коммерческими CA для авторизации клиентов. Let's Encrypt **не требует** EAB для стандартных пользователей — он нужен только для интеграций через посредников или при включении `externalAccountBinding` в Issuer.

**ACME Order** — ресурс, представляющий процесс заказа сертификата у ACME-сервера. Order содержит список доменов (`identifiers`), статус (`pending`, `ready`, `processing`, `valid`, `invalid`), ссылки на authority chains и идентификаторы Challenge. В Kubernetes Order — это CRD, создаваемый cert-manager при инициировании выпуска сертификата. Lifecycle Order: `pending` → `ready` → `processing` → `valid`.

**ACME Challenge** — конкретная задача по проверке владения доменом (HTTP-01, DNS-01, TLS-ALPN-01), создаваемая в рамках Order. Для каждого домена в Order создаётся отдельный Challenge. Статус Challenge: `pending` → `processing` → `valid` (успех) или `invalid` (сбой). cert-manager отслеживает состояние Challenge через polling `/acme/chall/{authz}`.

**Self-Check** — внутренняя проверка cert-manager перед отправкой подтверждения в ACME API. Контроллер сам обращается к созданному эндпоинту (HTTP-01) или проверяет TXT-запись (DNS-01), чтобы убедиться в доступности токена. Если Self-Check не проходит, Challenge остаётся в статусе `pending` до восстановления доступности.

**Certificate Chain** — цепочка доверия, состоящая из конечного сертификата (leaf/intermediate), промежуточного сертификата (intermediate) и корневого сертификата (root). Let's Encrypt выдаёт сертификаты через промежуточные CA (R10–R14 для RSA, E5–E9 для ECDSA), кросс-подписанные ISRG Root X1 для обратной совместимости. Неполная или некорректная цепочка приводит к ошибкам TLS на стороне клиента.

**ECDSA (Elliptic Curve Digital Signature Algorithm)** — алгоритм асимметричной криптографии, используемый Let's Encrypt для выпуска сертификатов с ключами на эллиптических кривых (P-256). ECDSA-сертификаты меньше по размеру и быстрее обрабатываются, чем RSA, но всё ещё кросс-подписаны RSA-корнем ISRG Root X1 для совместимости со старыми клиентами. В 2026 году ECDSA P-256 является предпочтительным выбором.

**Certificate Transparency (CT)** — открытый стандарт мониторинга цифровых сертификатов. С 15 июня 2026 года пре-сертификаты должны быть залогированы *до* выдачи финального сертификата (Pre-issuance CT). Без SCT (Signed Certificate Timestamp) браузеры Chrome/Safari блокируют доступ без возможности обхода. CT-логи позволяют обнаружить несанкционированный выпуск сертификатов.

**ARI (ACME Renewal Information)** — расширение протокола (RFC 9773), позволяющее CA динамически управлять окном продления сертификатов на стороне клиента. Вместо статичного `renewBefore` cert-manager опрашивает эндпоинт `/acme/renewal-info` и получает `suggestedWindow` с оптимальным временем продления. ARI критически важно для предотвращения перегрузки API, соблюдения лимитов и оперативной обработки массовых отзывов сертификатов.

---

## Основные концепции

### Регистрация аккаунта и External Account Binding (EAB)

При первом взаимодействии с ACME API cert-manager регистрирует аккаунт, создавая пару ключей (ECDSA P-256 или RSA 3072+). Адрес регистрации: `https://acme-v02.api.letsencrypt.org/new-account`.

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `email` | Email для уведомлений Let's Encrypt | Обязательно |
| `server` | ACME API endpoint | `https://acme-v02.api.letsencrypt.org/directory` |
| `privateKeySecretRef` | Secret с приватным ключом аккаунта | `cert-manager-issuer-account-<issuer-name>` |
| `externalAccountBinding` | Привязка к внешнему аккаунту (KID + HMAC) | Не используется (только для коммерческих CA) |

**EAB-сценарий** (для интеграций через посредников):
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: commercial-ca
spec:
  acme:
    email: admin@example.com
    server: https://acme.commercial-ca.com/directory
    privateKeySecretRef:
      name: commercial-ca-account
    externalAccountBinding:
      keyID: "0123456789abcdef"
      keySecretRef:
        name: commercial-ca-eab-key
        key: hmac-key
        namespace: cert-manager
```

**Важно:** Let's Encrypt **не поддерживает** EAB для стандартных пользователей. Если `externalAccountBinding` указан для Let's Encrypt, cert-manager вернёт ошибку `unauthorized`.

### Жизненный цикл ACME-Order (45-дневный цикл)

```
┌─────────────────────────────────────────────────────────────────┐
│  Certificate (Kubernetes CRD)                                  │
│  spec.renewBefore: 2160h (90 дней)                             │
│  spec.issuerRef: letsencrypt-prod                              │
└──────────────────────────┬──────────────────────────────────────┘
                           │ cert-manager polling
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Order (Kubernetes CRD)                                        │
│  identifiers: [api.example.com]                                │
│  state: pending → ready → processing → valid                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │ ACME API: newOrder
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Challenge (Kubernetes CRD)                                    │
│  type: HTTP-01 / DNS-01                                        │
│  state: pending → processing → valid                           │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Validation
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Secret (tls.crt + tls.key)                                    │
│  expiry: 90 дней (45 дней в 2026)                              │
└─────────────────────────────────────────────────────────────────┘
```

**Таймлайн ACME-взаимодействия (HTTP-01):**

| Этап | Описание | Время |
| :--- | :--- | :--- |
| 1. `newOrder` | Создание заказа в ACME API | 1–5 сек |
| 2. `newNonce` | Получение свежего nonce | 0.1–0.5 сек |
| 3. Challenge | Проверка доступности токена | 5–30 сек (зависит от TTL DNS) |
| 4. `finalize` | Отправка CSR | 2–10 сек |
| 5. Download | Получение сертификата | 1–3 сек |
| **Итого** | | **10–50 сек** |

**Таймлайн ACME-взаимодействия (DNS-01 через Cloudflare):**

| Этап | Описание | Время |
| :--- | :--- | :--- |
| 1. `newOrder` | Создание заказа в ACME API | 1–5 сек |
| 2. TXT-запись | Создание `_acme-challenge` записи | 1–5 сек |
| 3. Propagation | Ожидание распространения DNS | 30–120 сек |
| 4. Validation | ACME-сервер проверяет TXT | 5–10 сек |
| 5. Cleanup | Удаление TXT-записи | 1–3 сек |
| **Итого** | | **40–140 сек** |

### Механизмы безопасности ACME и JWS

ACME использует асимметричное шифрование и JWS для каждой операции. Каждое сообщение подписывается приватным ключом аккаунта.

| Компонент | Техническая роль | Специфика ACME |
| :--- | :--- | :--- |
| **Account Key** | Идентификация клиента | ECDSA P-256 или RSA 3072+. Подписывает все API-запросы. |
| **Replay-Nonce** | Защита от повторных атак | Передаётся в HTTP-заголовке `Replay-Nonce` и встраивается в `protected` заголовок JWS. |
| **Account URL** | Уникальный ID аккаунта | Формат: `https://acme-v02.api.letsencrypt.org/acme/acct/...`. Используется вместо передачи публичного ключа в каждом запросе. |
| **JWS Protected Header** | Метаданные подписи | Содержит `alg` (ES256/RS256), `nonce`, `url`, `kid` (ссылка на аккаунт). |
| **JWS Payload** | Тело запроса | Неструктурированный JSON (для `newAccount`) или пустая строка (для `newNonce`). |

**Типичная структура JWS-запроса (POST):**
```http
POST /acme/new-order HTTP/1.1
Host: acme-v02.api.letsencrypt.org
Content-Type: application/jose+json

{
  "protected": base64url({
    "alg": "ES256",
    "kid": "https://acme-v02.api.letsencrypt.org/acme/acct/12345",
    "nonce": "0102AbCdEfGhIjKl",
    "url": "https://acme-v02.api.letsencrypt.org/acme/new-order"
  }),
  "payload": base64url({
    "identifiers": [
      {"type": "dns", "value": "api.example.com"}
    ]
  }),
  "signature": "base64url(ECDSA-P256-signature)"
}
```

### Иерархия и цепочки доверия (Preferred Chain)

В 2025–2026 годах Let's Encrypt использует иерархию **Generation X** (Intermediates R10–R14 для RSA и E5–E9 для ECDSA), подписанную **ISRG Root X1**. Ранее используемый **DST Root CA X3** (для совместимости со старыми Android) истёк в сентябре 2021.

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `preferredChain: "ISRG Root X1"` | Выбор RSA-корня для максимальной совместимости | **Рекомендуется** для большинства сценариев |
| `preferredChain: "ISRG Root X2"` | Выбор ECDSA-корня для перехода на эллиптические кривые | Только для кластеров с полной поддержкой ECDSA |
| `preferredChain: "DST Root CA X3"` | Устаревший корень (срок истёк 30.09.2021) | **Не использовать** |

**Как cert-manager определяет цепочку:**
1. При создании Order cert-manager указывает `preferredChain` в запросе
2. ACME API возвращает URLs authority chains для каждой доступной цепочки
3. cert-manager скачивает промежуточный сертификат из предложенной цепочки
4. Сертификат сохраняется в Secret `tls.crt` в порядке: leaf → intermediate → root

### ECDSA-архитектура ISRG Root X2

Let's Encrypt активно продвигает переход на ECDSA (E5–E9), так как эти сертификаты меньше по размеру и быстрее обрабатываются на мобильных устройствах. Однако они все ещё кросс-подписаны RSA-корнем ISRG Root X1 для совместимости.

| Параметр | RSA (R10–R14) | ECDSA (E5–E9) |
| :--- | :--- | :--- |
| **Размер ключа** | 2048–4096 бит | 256 бит (P-256) |
| **Размер сертификата** | ~2–3 KB | ~0.5–1 KB |
| **Производительность подписи** | Медленнее | Быстрее |
| **Совместимость** | Все клиенты | Клиенты с поддержкой P-256 (99%+) |
| **Cross-sign** | ISRG Root X1 | ISRG Root X1 |

**Переход на ECDSA в Kubernetes:**
```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: api-tls-ecdsa
spec:
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  secretName: api-tls-ecdsa
  dnsNames:
    - api.example.com
  privateKey:
    algorithm: ECDSA
    size: 256
```

### Мандаты 2026: CT, EKU Split и OCSP Must-Staple

Экосистема WebPKI в 2026 году претерпевает фундаментальные изменения:

**1. Обязательный Pre-issuance CT (с 15 июня 2026):**
- Пре-сертификаты должны быть залогированы *до* выдачи финального сертификата
- Без SCT (Signed Certificate Timestamp) браузеры Chrome/Safari блокируют доступ
- cert-manager автоматически добавляет SCT в CSR через расширение `x509 SCT`
- Проверка SCT: `openssl x509 -in cert.pem -text | grep -A 5 "CT Precertificate SCTs"`

**2. Разделение EKU (Extended Key Usage):**
- Публичные сертификаты больше не могут быть одновременно `serverAuth` и `clientAuth`
- Для mTLS необходимо использовать внутренние PKI (Vault, Step-CA) или специальные CA
- Let's Encrypt выпускает только `serverAuth` (TLS Server Authentication)

**3. OCSP Must-Staple (рекомендация):**
- Сертификаты могут содержать расширение `OCSP Must-Staple`, требующее от сервера提供 OCSP-ответа при каждом TLS-handshake
- Сокращает время отзыва сертификата с часов до минут
- В cert-manager включается через `ocspMustStaple: true` в `Certificate.spec.privateKey`

**4. Shorter Lifetimes (45 дней):**
- Переход на 45-дневный цикл ротации становится стандартом
- Let's Encrypt ARI является основным механизмом для реализации этой частоты
- cert-manager автоматически управляет окном продления через ARI

---

## Практические сценарии

### Настройка Preferred Chain в Kubernetes

Если ваш стек требует специфический корень (например, для легаси-клиентов), укажите это в `Certificate`:

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: api-tls
spec:
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  commonName: api.example.com
  issuerOptions:
    preferredChain: "ISRG Root X1"
```

### Проверка Nonce и JWS-сообщений

Для глубокой отладки взаимодействия (например, ошибки `badNonce`) можно использовать `curl` для получения свежего nonce:

```bash
# Получение нового nonce от API Let's Encrypt
curl -I https://acme-v02.api.letsencrypt.org/new-nonce | grep -i "Replay-Nonce"
# → Replay-Nonce: 0102AbCd...

# Просмотр.Directory (информация о доступных ресурсах)
curl -s https://acme-v02.api.letsencrypt.org/directory | jq .
```

**Ручная отправка JWS-запроса (для отладки):**
```bash
# Получение Account URL
curl -s -X POST https://acme-v02.api.letsencrypt.org/new-account \
  -H "Content-Type: application/jose+json" \
  -d '{
    "protected": base64url({"alg":"ES256","jwk":{"kty":"EC","crv":"P-256","x":"...","y":"..."},"nonce":"...","url":"https://acme-v02.api.letsencrypt.org/new-account"}),
    "payload": base64url({"termsOfServiceAgreed":true}),
    "signature": "..."
  }'
```

### Мониторинг CT-логов (2026)

Убедитесь, что ваши сертификаты содержат необходимые SCT:

```bash
# Проверка расширения SCT в сертификате
openssl x509 -in cert.pem -text -noout | grep -A 5 "CT Precertificate SCTs"

# Проверка SCT через online-инструмент
curl -s "https://crt.sh/?q=example.com" | grep -i "ct"

# Просмотр CT-логов через JSON API
curl -s "https://crt.sh/?q=example.com&output=json" | jq '.[] | {id: .id, name: .name_value, timestamp: .entry_timestamp}'
```

### Регистрация аккаунта с EAB

Если ваш CA требует EAB (например, коммерческие CA), создайте Secret с HMAC-ключом и укажите `externalAccountBinding` в Issuer:

```bash
# 1. Создайте Secret с HMAC-ключом
kubectl create secret generic commercial-ca-eab-key \
  --from-literal=hmac-key=<HMAC-KEY-FROM-CA> \
  -n cert-manager

# 2. Примените ClusterIssuer с EAB
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: commercial-ca
spec:
  acme:
    email: admin@example.com
    server: https://acme.commercial-ca.com/directory
    privateKeySecretRef:
      name: commercial-ca-account
    externalAccountBinding:
      keyID: "0123456789abcdef"
      keySecretRef:
        name: commercial-ca-eab-key
        key: hmac-key
        namespace: cert-manager
EOF

# 3. Проверьте статус Issuer
kubectl describe clusterissuer commercial-ca
```

### openssl-проверка цепочки доверия

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
```

**Диагностика неполной цепочки:**
```bash
# Проверка, что промежуточный сертификат включён
openssl x509 -in /tmp/tls.crt -noout -text | grep -A 3 "Authority Info Access"

# Если AIA содержит OCSP responder — цепочка полная
# Если AIA пуст — промежуточный сертификат не включён в Secret
```

### Отладка ACME-взаимодействия через kubectl

```bash
# Просмотр всех Order
kubectl get order -A -o custom-columns=\
  NAME:.metadata.name,\
  NAMESPACE:.metadata.namespace,\
  STATUS:.status.state,\
  DOMAINS:.spec.identifiers[*].value,\
  CREATED:.metadata.creationTimestamp

# Просмотр Challenge с детализацией
kubectl describe challenge <name> -n <namespace>

# Логи контроллера по конкретному домену
kubectl logs -n cert-manager -l app=cert-manager | grep "api.example.com"

# Проверка событий (быстрый способ увидеть ошибки)
kubectl get events -n cert-manager --field-selector reason=Issuing | tail -20

# Проверка статуса всех Certificate
kubectl get certificate -A -o custom-columns=\
  NAME:.metadata.name,\
  NAMESPACE:.metadata.namespace,\
  READY:.status.conditions[?(@.type=="Ready")].status,\
  EXPIRY:.status.notAfter
```

---

## Дополнительная информация

### Рекомендации по работе с ACME в Kubernetes

1. **Версия контроллера**: Используйте cert-manager v1.15+. Это обязательное требование для поддержки ARI и корректной работы с 45-дневными сертификатами Let's Encrypt.
2. **Иерархия ресурсов**: При диагностике проблем всегда начинайте с `Certificate`, затем `CertificateRequest`, `Order` и `Challenge`. Ошибка транслируется снизу вверх.
3. **Staging-first**: Для любых тестов всегда используйте `server: https://acme-staging-v02.api.letsencrypt.org/directory`. Ошибки DNS-01 в Staging не тратят лимиты Production.
4. **Resource Limits**: Недостаток памяти у пода `cert-manager` может приводить к перезагрузкам во время обработки больших списков `Challenge`. Рекомендуется минимум 256Mi для controller и 128Mi для webhook.
5. **Cleanup**: Если `Order` или `Challenge` зависли в статусе `invalid`, удалите их вручную. cert-manager автоматически инициирует новую попытку:
   ```bash
   kubectl delete order <order-name> -n <namespace>
   kubectl delete challenge <challenge-name> -n <namespace>
   ```
6. **Аккаунт Let's Encrypt**: Регистрация аккаунта происходит автоматически при первом применении `Issuer`. Приватный ключ хранится в Secret `cert-manager-issuer-account-<issuer-name>` в namespace `cert-manager`.
7. **Проверка ARI**: Убедитесь, что cert-manager опрашивает ARI для управления окном продления. В cert-manager 1.15+ ARI включён по умолчанию.

### Смотрите также

- **[Let's Encrypt: Обзор](./index.md)** — лимиты, solvers и окружения
- **[Практические сценарии Let's Encrypt](./letsencrypt_scenarios.md)** — конфигурация HTTP-01 и DNS-01
- **[Cert-manager: Диагностика](./letsencrypt_advanced.md)** — решение проблем с ACME-заказами
- **[Cert-manager: Определения](../definitions.md)** — базовая структура ресурсов (Certificate, Issuer, Order, Challenge)
- **[Cert-manager: Администрирование](../Administration/index.md)** — HA, ресурсы и ротация ключей
