# Let's Encrypt: Диагностика и решение проблем

## Определения

**ACME-ошибки Let's Encrypt** — коды и сообщения об ошибках (RFC 8555), возвращаемые API-сервером Let's Encrypt при взаимодействии с контроллером cert-manager. Каждый код указывает на конкретную проблему: от некорректного формата запроса до превышения лимитов.

**Иерархия ресурсов (Resource Archaeology)** — метод последовательного анализа состояния цепочки объектов Kubernetes (Certificate → CertificateRequest → Order → Challenge), позволяющий точно локализовать сбой. Ошибка всегда транслируется снизу вверх: проблема на уровне Challenge отражается в статусе Order, затем CertificateRequest и Certificate.

**cmctl** (Cert-manager Control) — специализированная CLI-утилита (ранее `kubectl cert-manager`) для проверки состояния контроллера, ресурсов и диагностики API. Версия 1.20+ поддерживает `diagnose` для автоматического анализа конфигурации. Версия 2.0+ полностью поддерживает ARI и Gateway API.

**CAA (Certificate Authority Authorization)** — запись в DNS, указывающая, каким центрам сертификации разрешено выпускать сертификаты для данного домена. Если для домена настроены CAA, Let's Encrypt проверяет их перед выдачей. Отсутствие CAA-записи разрешает выпуск любым CA.

**Self-Check** — внутренняя проверка cert-manager, при которой контроллер сам обращается к созданному эндпоинту для подтверждения доступности токена HTTP-01 перед отправкой подтверждения в ACME API.

**Certificate Chain** — цепочка доверия, состоящая из конечного сертификата (leaf), промежуточного сертификата (intermediate) и корневого сертификата (root). Неполная или некорректная цепочка приводит к ошибкам TLS на стороне клиента.

---

## Основные концепции

### Иерархия диагностики (The "Archaeology" Flow)

Если объект `Certificate` не переходит в статус `Ready: True`, необходимо спускаться вниз по цепочке ресурсов. Ошибка всегда транслируется снизу вверх.

```
Certificate (Ready: False)
    │  причина: "Waiting for CertificateRequest"
    ▼
CertificateRequest (Pending/Failed)
    │  причина: "Order in status Invalid"
    ▼
Order (Invalid)
    │  причина: "Challenge failed"
    ▼
Challenge (Failed)          ← КОНТЕКСТ ОШИБКИ
    │  причина: "Self check failed"
    ▼
Pod cm-acme-http-solver    ← НИЖНИЙ УРОВЕНЬ
```

**Команда для быстрого поиска проблемных ресурсов:**
```bash
# Все ресурсы cert-manager в кластере, не в статусе Ready
kubectl get certificate,certificaterequest,order,challenge -A -o wide | grep -v -E "True|Complete|Valid|Succeeded"
```

### Инструментарий cmctl (2025–2026)

Для быстрой диагностики рекомендуется использовать утилиту `cmctl`:

```bash
# Проверка доступности вебхука и API
cmctl check api

# Детальный статус сертификата и всей цепочки ресурсов
cmctl status certificate <name> -n <namespace>

# Инспекция секрета (проверка срока, SAN, эмитента)
cmctl inspect secret <secret-name> -n <namespace>

# Принудительное продление (при зависании или ошибке ARI)
cmctl renew <name> -n <namespace>

# Массовое продление всех сертификатов
cmctl renew --all -A

# Автоматический анализ конфигурации (v1.20+)
cmctl diagnose certificate <name> -n <namespace>

# Диагностика всех сертификатов в namespace
cmctl diagnose certificate --namespace <namespace> --all
```

### Расширенная таблица ACME-кодов ошибок

| Код | Тип ошибки | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- | :--- |
| `400` | `malformed` | Некорректный формат запроса, невалидный CSR или JWS | `kubectl describe order <name>` | Удалите `Order` и `Challenge`, cert-manager пересоздаст |
| `401` | `unauthorized` | Невалидный аккаунт или ключ | Проверьте `privateKeySecretRef` в Issuer | Удалите секрет аккаунта, cert-manager зарегистрирует заново |
| `403` | `unauthorized` | Ошибка авторизации домена | Проверьте DNS-записи или HTTP-доступ по порту 80 | Убедитесь, что домен доступен из кластера и из интернета |
| `404` | `malformed` | Ресурс не найден (устаревший Order) | Проверьте версию ACME API | Обновите `server` на `https://acme-v02.api.letsencrypt.org/directory` |
| `429` | `rateLimited` | Превышены лимиты Let's Encrypt | Проверьте количество Order: `kubectl get order -A \| wc -l` | Используйте **Staging** окружение, ожидайте сброса лимитов |
| `500` | `serverInternal` | Временный сбой на стороне CA | Мониторьте статус: `kubectl describe order <name>` | Ожидание (обычно до 1 часа). При持久ном сбое — обратитесь в поддержку LE |
| `400` | `badNonce` | Повторное использование nonce | `kubectl logs -n cert-manager -l app=cert-manager \| grep badNonce` | Перезапустите контроллер, nonce автоматически обновится |
| `400` | `badCSREncoding` | Некорректный CSR | `openssl req -in csr.der -inform DER -noout -text` | Проверьте, что CSR содержит корректные SAN и CN |
| `403` | `unauthorized` | Несовпадение `externalAccountBinding` | Проверьте `externalAccountBinding` в Issuer | Убедитесь, что KID и HMAC-key соответствуют регистрации в EAB |
| `409` | `alreadyRevoked` | Сертификат уже отозван | `openssl s_client -connect domain:443 2>/dev/null \| openssl x509 -noout -text \| grep "CRL"` | Используйте новый домен или обратитесь в поддержку LE |

### openssl-диагностика выпущенных сертификатов

Для проверки сертификата, выданного Let's Encrypt, используйте команды:

```bash
# Извлечение сертификата из Kubernetes Secret
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | base64 -d > /tmp/tls.crt

# Просмотр деталей сертификата
openssl x509 -in /tmp/tls.crt -noout -text

# Проверка issuer (должен содержать "Let's Encrypt" или "ISRG")
openssl x509 -in /tmp/tls.crt -noout -issuer -subject

# Проверка срока действия
openssl x509 -in /tmp/tls.crt -noout -dates

# Проверка SAN (Subject Alternative Names)
openssl x509 -in /tmp/tls.crt -noout -ext subjectAltName

# Проверка цепочки доверия
openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt /tmp/tls.crt

# Проверка цепочки с промежуточным сертификатом
cat /tmp/tls.crt | grep -A 20 "BEGIN CERTIFICATE" > /tmp/leaf.pem
openssl x509 -in /tmp/tls.crt -noout -text | grep -A 5 "Authority Info Access" # OCSP responder
```

### Проверка цепочки доверия

Неполная цепочка — распространённая проблема. Сертификат может быть валидным, но клиент не доверяет промежуточному CA.

```bash
# Проверка полноты цепочки
openssl s_client -connect example.com:443 -showcerts 2>/dev/null | openssl x509 -noout -text | grep -E "Certificate Chain|issuer|subject"

# Проверка через在线-инструмент
# ssl-checker.sh или curl https://example.com | openssl x509 -noout -text

# Валидация цепочки Let's Encrypt
openssl verify -untrusted /tmp/tls.crt /tmp/tls.crt
```

**Признаки неполной цепочки:**
- `verify error:num=20:unable to get local issuer certificate`
- Браузер показывает "Your connection is not private"
- Мобильные устройства не загружают страницу, а десктопные — загружают

---

## Практические сценарии

### Глубокая диагностика через kubectl

Если `cmctl` недоступен, используйте стандартные команды:

```bash
# 1. Поиск проблемных ресурсов
kubectl get certificate,certificaterequest,order,challenge -A | grep -v "True"

# 2. Осмотр Challenge (самый информативный уровень)
kubectl describe challenge <name>

# 3. Чтение логов контроллера по домену
kubectl logs -n cert-manager -l app.kubernetes.io/instance=cert-manager | grep "example.com"

# 4. Проверка состояния подов cert-manager
kubectl get pods -n cert-manager -o wide

# 5. Проверка событий (Events) — быстрый способ увидеть ошибки
kubectl get events -n cert-manager --field-selector reason=Issuing --sort-by='.lastTimestamp' | tail -20

# 6. Просмотр статуса всех Order
kubectl get order -A -o custom-columns=NAME:.metadata.name,NAMESPACE:.metadata.namespace,STATUS:.status.state,CREATED:.metadata.creationTimestamp

# 7. Просмотр Secret с сертификатом (срок, issuer)
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -dates -issuer -subject
```

### Проблемы HTTP-01 проверки

**Симптом:** `Waiting for HTTP-01 challenge propagation: failed to perform self check`

| Причина | Диагностика | Решение |
| :--- | :--- | :--- |
| **Network Policies** | `kubectl get networkpolicy -n cert-manager` | Разрешите трафик на порт 8089 из namespace Ingress-контроллера в namespace cert-manager |
| **Split-horizon DNS** | `dig +short example.com` vs `dig +short @8.8.8.8 example.com` | Настройте `--dns01-recursive-nameservers=8.8.8.8:53` в аргументах контроллера |
| **NAT Loopback** | Кластер за NAT не может достучаться до своего внешнего IP | Используйте **DNS-01** или настройте `hairpin` / `externalTrafficPolicy: Local` |
| **Force HTTPS** | Редирект 80→443 блокирует проверку | Исключите `/.well-known/acme-challenge/*` из редиректов в Ingress |
| **Firewall** | Внешний firewall блокирует порт 80 | Откройте порт 80 для ACME-проверки на время создания сертификата |
| **Ingress Class** | Временный Ingress создан с неверным классом | Укажите `acme.cert-manager.io/http01-ingress-class: nginx` в Issuer |
| **DNS-кэш** | Внутренний DNS кэширует старый IP | Настройте TTL DNS-записи на минимальное значение (300 сек) перед проверкой |

**Команда для проверки доступности эндпоинта HTTP-01:**
```bash
# Проверка, что токен доступен изнутри кластера
kubectl run curl-test --image=curlimages/curl --rm -it --restart=Never -- curl -s http://<domain>/.well-known/acme-challenge/<token>

# Проверка извне
curl -v http://<domain>/.well-known/acme-challenge/<token>
```

### Проблемы DNS-01 и CAA

**Симптом:** `CAA prevents issuance` или `DNS problem: networking error looking up CAA`

1.  **Проверка CAA**: Если в DNS есть записи CAA, они должны явно разрешать Let's Encrypt:
    ```text
    example.com. IN CAA 0 issue "letsencrypt.org"
    example.com. IN CAA 0 issuewild "letsencrypt.org"  # для wildcard
    ```
2.  **DNS Propagation**: Используйте флаг `--dns01-recursive-nameservers` (например, `8.8.8.8:53`), чтобы cert-manager проверял записи в обход внутреннего DNS кластера.
3.  **Permissions**: Секрет с API-токеном (Cloudflare/Yandex) должен находиться в том же namespace, что и `Issuer` (для `ClusterIssuer` — в namespace cert-manager).
4.  **TTL**: Уменьшите TTL DNS-записи до 300 сек перед началом работы, чтобы избежать проблем с кэшированием.

**Проверка TXT-записи _acme-challenge:**
```bash
# Проверка наличия TXT-записи через публичный DNS
dig +short TXT _acme-challenge.example.com @8.8.8.8

# Проверка через Cloudflare API (если используется)
curl -X GET "https://api.cloudflare.com/client/v4/zones/<zone_id>/dns_records?type=TXT&name=_acme-challenge.example.com" \
  -H "Authorization: Bearer <api_token>" | jq '.result[].content'
```

**Специфичные проблемы DNS-01 провайдеров:**

| Провайдер | Частая проблема | Решение |
| :--- | :--- | :--- |
| **Cloudflare** | Proxy mode (orange cloud) блокирует TXT-записи | Отключите proxy для `_acme-challenge` TXT-записи |
| **Route53** | IAM-роль не имеет права `route53:ChangeResourceRecordSets` | Добавьте политику `AmazonRoute53FullAccess` (или минималистичную) |
| **Yandex Cloud** | Неверный формат Service Account Key | Используйте JSON-формат, не PEM |
| **RFC 2136** | TSIG-ключ не совпадает | Проверьте корректность ключа и имя зоны |
| **Google Cloud DNS** | Service Account без роли `roles/dns.admin` | Назначьте роль через IAM |

### Диагностика ARI (ACME Renewal Information)

cert-manager 1.15+ использует ARI для динамического определения окна продления.

*   **Проверка**: Если сертификат обновляется задолго до `renewBefore`, это работа ARI.
*   **Диагностика**: `kubectl logs ... | grep "ARI"` покажет `suggestedWindow`. Это штатное поведение при обнаружении уязвимостей или техработах на стороне CA.
*   **Принудительное продление**: Если ARI заблокировал заказ (например, из-заIncorrectRevocation), используйте `cmctl renew <name> --force`.

**Проверка ARI-статуса:**
```bash
# Проверка наличия ARI-информации в статусе Certificate
kubectl get certificate <name> -o jsonpath='{.status.conditions}' | jq '.[] | select(.type=="Ready")'

# Логи ARI
kubectl logs -n cert-manager -l app=cert-manager | grep -i "ari\|renewal-info\|suggestedWindow"
```

### Диагностика Rate Limits

Если вы столкнулись с ошибкой `rateLimited`, определите причину:

```bash
# Подсчёт активных Order в кластере
kubectl get order -A -o json | jq '.items | length'

# Подсчёт Order по статусам
kubectl get order -A -o json | jq '.items | group_by(.status.state) | map({state: .[0].status.state, count: length})'

# Проверка последних ошибок rate limit в логах
kubectl logs -n cert-manager -l app=cert-manager | grep -i "rate\|limit\|429"

# Проверка количества сертификатов на домен (через API LE)
curl -s https://acme-v02.api.letsencrypt.org/directory | jq '.meta'
```

**Стратегия восстановления:**
1. Переключитесь на Staging-окружение для тестирования
2. Уменьшите частоту создания/обновления сертификатов
3. Используйте ARI для автоматического управления окном продления
4. Ожидайте сброса лимитов (от 1 часа до 7 дней в зависимости от типа)

### Проблемы с Webhook и контроллером

**Симптом:** Блокировка любых операций с ресурсами cert-manager

```bash
# Проверка доступности webhook
kubectl get endpoints -n cert-manager cert-manager-webhook

# Проверка логов webhook
kubectl logs -n cert-manager -l app=cert-manager-webhook --tail=50

# Проверка NetworkPolicy
kubectl get networkpolicy -n cert-manager -o yaml

# Перезапуск webhook при зависании
kubectl rollout restart deployment cert-manager-webhook -n cert-manager
```

**Типичные проблемы:**
- Webhook не отвечает → проверьте порт 10250, NetworkPolicy, ресурсы пода
- `Internal error occurred: failed calling webhook` → webhook-сервис недоступен, перезапустите
- TLS-ошибка webhook → проверьте сертификаты в Secret `cert-manager-webhook-ca`

### Диагностика Wildcard-сертификатов

Wildcard-сертификаты (`*.example.com`) обязуют использовать DNS-01. Типичные проблемы:

```bash
# Проверка, что wildcard-сертификат создан
kubectl get certificate -A -o json | jq '.items[] | select(.spec.dnsNames[] | startswith("*")) | {name: .metadata.name, dnsNames: .spec.dnsNames}'

# Проверка TXT-записи для wildcard
dig +short TXT _acme-challenge.example.com @8.8.8.8

# Проверка, что DNS-01 solver настроен для wildcard
kubectl get clusterissuer letsencrypt-prod -o jsonpath='{.spec.acme.solvers}'
```

**Wildcard-specific проблемы:**
- DNS-01 solver не создан для wildcard → cert-manager не может проверить владение `*.example.com`
- TXT-запись не удаляется после проверки → возможно, API-токен не имеет прав на удаление
- Wildcard + SAN: указывайте оба домена в `dnsNames` (`*.example.com` и `example.com`)

---

## Дополнительная информация

### Рекомендации по безопасности и стабильности

1.  **Gateway API**: В версиях 1.15+ поддержка Gateway API стабильна. Если сертификат не создается для `HTTPRoute`, проверьте наличие аннотации `cert-manager.io/issuer` на самом ресурсе `Gateway`.
2.  **Cleanup**: Если `Order` или `Challenge` зависли в статусе `invalid`, удалите их вручную. cert-manager автоматически инициирует новую попытку:
    ```bash
    kubectl delete order <order-name> -n <namespace>
    kubectl delete challenge <challenge-name> -n <namespace>
    ```
3.  **Staging-first**: Для любых тестов всегда используйте `server: https://acme-staging-v02.api.letsencrypt.org/directory`. Ошибки DNS-01 в Staging не тратят лимиты Production.
4.  **Resource Limits**: Недостаток памяти у пода `cert-manager` может приводить к перезагрузкам во время обработки больших списков `Challenge`. Рекомендуется минимум 256Mi для controller и 128Mi для webhook.
5.  **Версия контроллера**: Используйте cert-manager v1.15+. Это обязательное требование для поддержки ARI и корректной работы с 45-дневными сертификатами Let's Encrypt.
6.  **Логирование**: Повысьте уровень логирования для отладки ACME-взаимодействия:
    ```bash
    kubectl patch deployment cert-manager -n cert-manager --type='json' \
      -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--v=6"}]'
    ```
7.  **Мониторинг**: Настройте Prometheus-алерты на метрику `certmanager_certificate_expiration_timestamp_seconds` для заблаговременного обнаружения проблем с продлением.

### Смотрите также

- **[Let's Encrypt: Обзор](./index.md)** — лимиты, solvers и окружения
- **[Углублённые концепции ACME](./letsencrypt_concepts.md)** — подробности ARI, CT-логи и типы аккаунтов.
- **[Практические сценарии Let's Encrypt](./letsencrypt_scenarios.md)** — полные YAML-примеры конфигураций.
- **[Реагирование на инциденты (Incident Response)](./letsencrypt_incident_response.md)** — пошаговые процедуры при просроченных сертификатах и компрометации ключей.
- **[Disaster Recovery и Backup](./letsencrypt_disaster_recovery.md)** — восстановление после потери кластера и DNS API токенов.
- **[Сетевая безопасность (Network Security)](./letsencrypt_network_security.md)** — firewall, egress и NetworkPolicy для ACME проверок.
- **[Cert-manager: Определения](../definitions.md)** — базовая структура ресурсов контроллера.
- **[Cert-manager: Администрирование](../Administration/index.md)** — HA, ресурсы и ротация ключей.
- **[Cert-manager: Troubleshooting](../Administration/troubleshooting.md)** — общая диагностика контроллера (CPU, Memory, Webhook).
