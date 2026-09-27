# Диагностика и устранение неисправностей cert-manager

## Определения

**Troubleshooting cert-manager** — комплексный процесс выявления и устранения сбоев в жизненном цикле сертификатов, работе Admission Webhooks и интеграции с внешними API центров сертификации (CA).

**cmctl** — основная CLI-утилита для диагностики, заменяющая устаревшие методы ручного осмотра ресурсов. С версии v2.0 полностью поддерживает ARI и Gateway API.

**Resource Archaeology (Археология ресурсов)** — методология отладки путем последовательного анализа иерархии объектов от высокоуровневого `Certificate` до низкоуровневых `Challenge`.

**ARI (ACME Renewal Information)** — механизм, позволяющий CA рекомендовать конкретное время для продления. Ошибки в работе ARI могут приводить к преждевременному или неудачному обновлению.

---

## Основные концепции

### Иерархия диагностики ресурсов

Для эффективного поиска ошибок необходимо двигаться "вниз" по цепочке ресурсов. Ошибка почти всегда транслируется снизу вверх:

1.  **Certificate:** Отражает общее состояние готовности (`Ready`).
2.  **CertificateRequest:** Содержит статус формирования CSR и взаимодействия с Issuer.
3.  **Order (для ACME):** Отражает состояние заказа в API центра сертификации.
4.  **Challenge (для ACME):** Содержит детальную причину сбоя проверки владения доменом (DNS-01/HTTP-01).

### Ключевые компоненты и их индикаторы сбоев

| Компонент | Роль | Признак сбоя |
| :--- | :--- | :--- |
| **cert-manager** | Основная логика | Статус ресурсов не обновляется, ошибки в логах ACME. |
| **webhook** | Валидация API | Ошибки `Internal error occurred: failed calling webhook` при `kubectl apply`. |
| **cainjector** | Доверие в кластере | CRD или Webhook конфигурации не имеют валидных CA-сертификатов. |
| **trust-manager** | Дистрибуция CA | Ресурсы `Bundle` не синхронизируются в ConfigMap целевых namespace. |

---

## Практические сценарии

### Шаг 1: Экспресс-диагностика через cmctl

В 2026 году использование `cmctl` является обязательным стандартом для SRE.

```bash
# 1. Проверка работоспособности API и вебхуков
cmctl check api --wait=2m

# 2. Визуализация всей цепочки ресурсов для проблемного сертификата
cmctl status certificate <name> -n <namespace>

# 3. Инспекция состава секрета (SAN, сроки, алгоритм)
cmctl inspect secret <secret-name> -n <namespace>
```

### Шаг 2: Глубокий анализ ACME и ARI

Если сертификат застрял в процессе обновления или выдает ошибки 400 Malformed:

1.  **Проверка статуса ARI:**
    ```bash
    kubectl get certificate <name> -o jsonpath='{.status.acme.ari}'
    ```
2.  **Принудительное продление (если ARI заблокировал заказ):**
    ```bash
    cmctl renew <name> --force
    ```
3.  **Отладка HTTP-01:** Убедитесь, что временный под `cm-acme-http-solver` доступен извне.
    ```bash
    kubectl get pods -l acme.cert-manager.io/http-domain -A
    ```

### Диагностика ACME-проверок

#### Проблемы HTTP-01

**Симптом:** Challenge висит в `pending` или завершается ошибкой `self-check failed`.

| Причина | Диагностика | Решение |
| :--- | :--- | :--- |
| **NetworkPolicy** | `kubectl get networkpolicy -n cert-manager` | Разрешите трафик на порт 8089 из namespace Ingress-контроллера |
| **Split-horizon DNS** | `dig +short example.com` vs `dig +short @8.8.8.8 example.com` | Настройте `--dns01-recursive-nameservers=8.8.8.8:53` в аргументах контроллера |
| **NAT Loopback** | Кластер за NAT не может достучаться до своего внешнего IP | Используйте DNS-01 или настройте hairpin / `externalTrafficPolicy: Local` |
| **Force HTTPS** | Редирект 80→443 блокирует проверку | Исключите `/.well-known/acme-challenge/*` из редиректов |
| **Firewall** | Внешний firewall блокирует порт 80 | Откройте порт 80 для ACME-проверки на время создания сертификата |
| **Ingress Class** | Временный Ingress создан с неверным классом | Укажите `acme.cert-manager.io/http01-ingress-class: nginx` в Issuer |
| **DNS-кэш** | Внутренний DNS кэширует старый IP | Настройте TTL DNS-записи на минимальное значение (300 сек) |

**Проверка доступности эндпоинта:**
```bash
# Проверка изнутри кластера
kubectl run curl-test --image=curlimages/curl --rm -it --restart=Never -- curl -s http://<domain>/.well-known/acme-challenge/<token>

# Проверка извне
curl -v http://<domain>/.well-known/acme-challenge/<token>
```

#### Проблемы DNS-01 и CAA

**Симптом:** `CAA prevents issuance` или `DNS problem: networking error looking up CAA`.

1.  **Проверка CAA:** Если в DNS есть записи CAA, они должны явно разрешать Let's Encrypt:
    ```text
    example.com. IN CAA 0 issue "letsencrypt.org"
    example.com. IN CAA 0 issuewild "letsencrypt.org"  # для wildcard
    ```
2.  **DNS Propagation:** Используйте флаг `--dns01-recursive-nameservers` (например, `8.8.8.8:53`), чтобы cert-manager проверял записи в обход внутреннего DNS кластера.
3.  **Permissions:** Секрет с API-токеном (Cloudflare/Yandex) должен находиться в том же namespace, что и `Issuer` (для `ClusterIssuer` — в namespace cert-manager).
4.  **TTL:** Уменьшите TTL DNS-записи до 300 сек перед началом работы.

**Проверка TXT-записи _acme-challenge:**
```bash
# Проверка через публичный DNS
dig +short TXT _acme-challenge.example.com @8.8.8.8

# Проверка через Cloudflare API (если используется)
curl -X GET "https://api.cloudflare.com/client/v4/zones/<zone_id>/dns_records?type=TXT&name=_acme-challenge.example.com" \
  -H "Authorization: Bearer <api_token>" | jq '.result[].content'
```

#### Диагностика Wildcard-сертификатов

Wildcard-сертификаты (`*.example.com`) обязуют использовать DNS-01.

```bash
# Проверка, что wildcard-сертификат создан
kubectl get certificate -A -o json | jq '.items[] | select(.spec.dnsNames[] | startswith("*")) | {name: .metadata.name, dnsNames: .spec.dnsNames}'

# Проверка TXT-записи для wildcard
dig +short TXT _acme-challenge.example.com @8.8.8.8

# Проверка, что DNS-01 solver настроен
kubectl get clusterissuer letsencrypt-prod -o jsonpath='{.spec.acme.solvers}'
```

**Типичные проблемы:**
- DNS-01 solver не создан для wildcard → cert-manager не может проверить владение `*.example.com`
- TXT-запись не удаляется после проверки → возможно, API-токен не имеет прав на удаление
- Wildcard + SAN: указывайте оба домена в `dnsNames` (`*.example.com` и `example.com`)

### Шаг 3: Частые проблемы и методы их решения (2025–2026)

#### Сценарий: Ошибки Gateway API (ReferenceGrant)

**Симптом:** Gateway не видит сертификат, или cert-manager не создает Certificate для Gateway.
1.  **Проверка ReferenceGrant:** Если Secret в другом namespace, создайте `ReferenceGrant` в namespace секрета.
2.  **ParentRef Fallback:** Если используется только 443 порт, убедитесь в наличии аннотации `acme.cert-manager.io/http01-parentreffallback: "true"`.

#### Сценарий: Ошибки RBAC в версии 1.21+

**Симптом:** Ошибки `permission denied` при работе с Route53 или Vault.
*   **Причина:** Удаление прав на создание ServiceAccount токенов из стандартного чарта.
*   **Решение:** Вручную добавьте права `serviceaccounts/token: create` в ClusterRole контроллера или используйте IRSA (для AWS).

#### Сценарий: Webhook Timeout

**Симптом:** Блокировка любых операций с ресурсами cert-manager.
1.  **Сеть:** Проверьте доступность порта 10250 на подах webhook.
2.  **NetworkPolicy:** Разрешите трафик из namespace `kube-system` (API-сервер) в namespace `cert-manager`.
3.  **Перезагрузка:** `kubectl rollout restart deployment cert-manager-webhook -n cert-manager`.

#### Сценарий: trust-manager Bundle не обновляется

1.  **Namespace Selector:** Убедитесь, что целевые namespace имеют метки, соответствующие `namespaceSelector` в ресурсе `Bundle`.
2.  **Метки по умолчанию:** В новых версиях пустой селектор **не** означает "все namespace".

### Верификация цепочки сертификатов

Неполная или поврежденная цепочка — распространённая проблема. Сертификат может быть валидным, но клиент не доверяет промежуточному CA.

```bash
# Извлечение сертификата из Kubernetes Secret
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | base64 -d > /tmp/tls.crt

# Просмотр деталей сертификата
openssl x509 -in /tmp/tls.crt -noout -text

# Проверка issuer
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

**Признаки неполной цепочки:**
- `verify error:num=20:unable to get local issuer certificate`
- Браузер показывает "Your connection is not private"
- Мобильные устройства не загружают страницу, а десктопные — загружают

### Производительность и ресурсы

#### OOMKilled и нехватка памяти

**Симптом:** Pod cert-manager перезапускается с `OOMKilled` или метрики `container_memory_working_set_bytes` близки к лимиту.

```bash
# Проверка статуса подов
kubectl get pods -n cert-manager -o wide
kubectl describe pod <pod-name> -n cert-manager | grep -A5 "Last State"

# Проверка лимитов памяти
kubectl get deployment cert-manager -n cert-manager -o jsonpath='{.spec.template.spec.containers[0].resources}'
```

**Решение:**
- Увеличьте лимиты памяти для контроллера при >500 сертификатах: `limits.memory: 1Gi`, `requests.memory: 256Mi`
- Для webhook установите `requests == limits` для QoS `Guaranteed`, чтобы защитить от OOM Kill

#### Высокая задержка Webhook

**Симптом:** `certmanager_webhook_request_duration_seconds` > 1s, создание ресурсов блокируется.

```bash
# Проверка метрик webhook
curl -s http://localhost:9402/metrics | grep certmanager_webhook_request_duration_seconds

# Проверка ресурсов пода webhook
kubectl top pods -n cert-manager -l app=cert-manager,app.kubernetes.io/component=webhook
```

**Решение:**
- Увеличьте `limits.cpu` для webhook
- Проверьте, нет ли сетевых задержек между API-сервером и webhook

#### Ошибки реконсиляции и переполнение очереди

**Симптом:** `controller_runtime_reconcile_errors_total` растет, `workqueue_depth` > 100.

```bash
# Проверка глубины очереди
curl -s http://localhost:9402/metrics | grep workqueue_depth

# Проверка ошибок реконсиляции
curl -s http://localhost:9402/metrics | grep controller_runtime_reconcile_errors_total
```

**Решение:**
- Увеличьте `replicaCount` контроллера для распределения нагрузки
- Проверьте, нет ли зависших ресурсов (например, Challenge в `pending`), блокирующих очередь

### Проблемы CSI-драйвера и инъекции секретов

cert-manager CSI-драйвер монтирует сертификаты в поды без сохранения приватных ключей в etcd.

**Симптом:** Pod не видит обновленный сертификат после продления, или CSI-volume не монтируется.

```bash
# Проверка, что CSI-драйвер установлен
kubectl get pods -n cert-manager -l app=cert-manager-csi-driver

# Проверка CSI-класса
kubectl get storageclass

# Проверка монтирования в поде
kubectl describe pod <pod-name> -n <namespace> | grep -A10 "Volumes"
```

**Распространенные проблемы:**
- CSI-драйвер не установлен или не поддерживает `readOnly: false` для частого опроса
- `fsGroup` не настроен, поэтому приложение не имеет прав на чтение сертификата
- `fsVolumeRepollInterval` слишком большой (>60s), обновление сертификата не распространяется сразу

### Совместимость с Ingress-контроллерами

Некоторые Ingress-контроллеры не поддерживают динамическое обновление TLS-секретов без перезапуска.

| Контроллер | Минимальная версия | Особенности |
| :--- | :--- | :--- |
| **NGINX Ingress** | 1.10+ | До 1.10 требуется перезапуск для подхвата нового Secret |
| **Traefik** | 3.0+ | Поддерживает hot-reload TLS из Kubernetes Secret |
| **HAProxy Ingress** | 0.13+ | Требует `--configmap` с явным указанием Secret |
| **AWS ALB** | Любая | Требует аннотации `acme.cert-manager.io/http01-edit-in-place: "true"` |
| **GCE Ingress** | Любая | Требует аннотации `acme.cert-manager.io/http01-edit-in-place: "true"` |

**Диагностика:**
```bash
# Проверка версии Ingress-контроллера
kubectl describe deployment <ingress-controller> -n <namespace> | grep Image

# Проверка, что Ingress использует правильный Secret
kubectl describe ingress <ingress-name> -n <namespace> | grep Secret

# Проверка, что конфигурация обновилась (после продления сертификата)
kubectl exec -it <pod-name> -n <namespace> -- curl -v https://localhost 2>&1 | grep "SSL certificate"
```

### Каталог ACME-кодов ошибок

| Код | Тип ошибки | Причина | Решение |
| :--- | :--- | :--- | :--- |
| `400` | `malformed` | Некорректный CSR или JWS | Удалите `Order` и `Challenge`, cert-manager пересоздаст |
| `401` | `unauthorized` | Невалидный аккаунт или ключ | Удалите секрет аккаунта, cert-manager зарегистрирует заново |
| `403` | `unauthorized` | Ошибка авторизации домена | Убедитесь, что домен доступен из кластера и из интернета |
| `404` | `malformed` | Устаревший Order | Обновите `server` на `https://acme-v02.api.letsencrypt.org/directory` |
| `429` | `rateLimited` | Превышены лимиты Let's Encrypt | Используйте Staging, ожидайте сброса лимитов |
| `500` | `serverInternal` | Временный сбой на стороне CA | Ожидание до 1 часа; при стойком сбое — обратитесь в поддержку LE |
| `400` | `badNonce` | Повторное использование nonce | Перезапустите контроллер |
| `400` | `badCSREncoding` | Некорректный CSR | Проверьте, что CSR содержит корректные SAN и CN |
| `403` | `unauthorized` | Несовпадение `externalAccountBinding` | Убедитесь, что KID и HMAC-key соответствуют регистрации в EAB |
| `409` | `alreadyRevoked` | Сертификат уже отозван | Используйте новый домен или обратитесь в поддержку LE |

> **Примечание:** Подробный разбор каждого кода с примерами логов — в [Let's Encrypt: Диагностика](../LetsEncrypt/letsencrypt_advanced.md).

---

## Дополнительная информация

### Рекомендации по логированию

Для глубокой отладки ACME-взаимодействия повысьте уровень логирования контроллера:
```bash
# Установка уровня 6 для детального вывода JWS-сообщений
kubectl patch deployment cert-manager -n cert-manager --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--v=6"}]'
```

### Смотрите также

- **[Cert-manager: Администрирование](./index.md)** — HA, ресурсы и ротация ключей.
- **[Cert-manager: Операции](./operations.md)** — мониторинг, алертинг и резервное копирование.
- **[Обновление и миграция cert-manager](./upgrades_and_migration.md)** — пошаговый апгрейд, breaking changes, rollback.
- **[Масштабирование и производительность](./scaling_and_performance.md)** — tuning при 1000+ сертификатах, OOM, workqueue.
- **[RBAC-примеры](./rbac_examples.md)** — ошибки `Forbidden` и готовые Role/ClusterRole.
- **[Cert-manager: GitOps интеграция](./gitops_integration.md)** — настройка ArgoCD/Flux с cert-manager.
- **[Cert-manager: Тестирование в CI/CD](./cicd_testing.md)** — валидация манифестов перед деплоем.
- **[Cert-manager: Production Playbooks](./production_playbooks.md)** — пошаговые инструкции по типичным инцидентам.
- **[Cert-manager: Отзыв сертификатов](./certificate_revocation.md)** — CRL, OCSP, короткие TTL.
- **[Let's Encrypt: Диагностика](../LetsEncrypt/letsencrypt_advanced.md)** — решение специфичных проблем ACME.
