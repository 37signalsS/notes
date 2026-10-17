# Vault API — справочник

> **Актуально для:** Vault 2.x (latest 2.1.2; ветка 1.21.x поддерживается)

## Определения

**Vault API** — RESTful HTTP API, предоставляемый Vault для всех операций. Все взаимодействия с Vault (CLI, UI, SDK) осуществляются через API.

**Endpoint** — конкретный URL в API Vault, например `/v1/secret/data/myapp/config`.

**Request ID** — уникальный идентификатор запроса, возвращается в заголовке `X-Vault-Request-Id` и в поле `request_id` JSON-ответа. Используется для трассировки и расследования инцидентов.

**Namespace Header** — заголовок `X-Vault-Namespace`, используемый для указания namespace в запросе (Enterprise).

**Wrapping Token** — временный токен, возвращаемый Vault при запросе с заголовком `X-Vault-Wrap-Ttl`. Содержит wrapped ответ в cubbyhole и может быть использован один раз для его распаковки.

**Batch request** — запрос, содержащий несколько операций в одном HTTP-вызове через параметр `batch_input`. Поддерживается движком Transit (encrypt/decrypt/sign/hmac/rewrap); поддержка остальных движков зависит от реализации конкретного движка.

**Cubbyhole** — внутренний бэкенд Vault, привязанный к конкретному токену. Секреты в cubbyhole видны только держателю токена.

## Основные концепции

### Структура API

Все API endpoints имеют префикс `/v1/`:

```
GET    /v1/sys/health          - Проверка работоспособности
POST   /v1/auth/approle/login  - Аутентификация
GET    /v1/secret/data/myapp   - Чтение секрета
POST   /v1/secret/data/myapp   - Запись секрета
DELETE /v1/secret/data/myapp   - Удаление секрета
LIST    /v1/secret/metadata/myapp - Список ключей
```

Vault считает PUT и POST синонимами, поэтому для записи можно использовать любой из глаголов. Для списков используется глагол `LIST`; эквивалентом является `GET` с параметром `?list=true`.

### Заголовки запросов

| Заголовок | Описание | Обязательный |
| :--- | :--- | :--- |
| `X-Vault-Token` | Токен аутентификации | Да (для большинства запросов) |
| `X-Vault-Namespace` | Namespace (Enterprise) | Нет |
| `X-Vault-Wrap-Ttl` | TTL wrapping token (Response Wrapping) | Нет |
| `X-Vault-Request` | Защита от SSRF: подтверждает, что запрос идёт через доверенный канал (`require_request_header`) | Нет |
| `Content-Type` | Тип содержимого | Да (обычно `application/json`) |
| `Accept` | Формат ответа | Нет |

### Форматы ответов

| Формат | Описание | Использование |
| :--- | :--- | :--- |
| `JSON` (по умолчанию) | Структурированный JSON | Большинство случаев |
| `text/plain` | Текстовый формат | Простые значения |
| `application/octet-stream` | Бинарные данные | Сертификаты, ключи |

Ошибки возвращаются структурой `{"errors": ["message", ...]}` для любого статуса ≥ 400.

## Практические сценарии

### Сценарий 1: Базовые операции с секретами (KV v2)

#### Чтение секрета

```bash
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/secret/data/myapp/config
# → {"request_id":"...","data":{"data":{"password":"...","username":"..."},"metadata":{"version":1,"created_time":"...","destruction_time":"",...}}}
```

#### Запись секрета

```bash
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"data": {"password": "new_password", "api_key": "new_key"}}' \
     https://vault.example.com:8200/v1/secret/data/myapp/config
```

#### Удаление секрета

```bash
# Soft delete (удаление данных последней версии; восстановимо через undelete)
curl -s -X DELETE -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/secret/data/myapp/config

# Полное удаление конкретных версий (irreversible — destroy)
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"versions":[1,2]}' \
     https://vault.example.com:8200/v1/secret/destroy/myapp/config
```

> **Примечание:** подробнее о версии KV v2 — в [Vault API: KV](https://developer.hashicorp.com/vault/api-docs/secret/kv/kv-v2). Удаление (`delete`) помечает версию удалённой, но данные сохраняются и их можно восстановить через `undelete`; `destroy` удаляет данные необратимо.

#### Список секретов

```bash
curl -s -X LIST -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/secret/metadata/myapp/
# → {"data":{"keys": ["config", "db", "api-key"]}}
```

### Сценарий 2: Аутентификация через API

#### AppRole

```bash
# Аутентификация
curl -s -X POST -H "Content-Type: application/json" \
     -d '{"role_id":"6b2a5c4a-...","secret_id":"98e4f7b3-..."}' \
     https://vault.example.com:8200/v1/auth/approle/login
# → {"auth":{"client_token":"hvs.CAESI...","policies":["default","app-policy"],"lease_duration":...}}
```

#### LDAP

```bash
# Аутентификация через LDAP
curl -s -X POST -H "Content-Type: application/json" \
     -d '{"username":"john.doe","password":"P@ssw0rd"}' \
     https://vault.example.com:8200/v1/auth/ldap/login/john.doe
# → {"auth":{"client_token":"hvs.CAESI...","policies":["default","ldap-users"],...}}
```

> **Примечание:** методы аутентификации Kubernetes и JWT требуют внешние сервисы (кластер K8s или OIDC-провайдер). Для on-premise сред используйте LDAP, TLS Cert или AppRole. Подробнее — [AppRole](./vault_auth_approle.md).

### Сценарий 3: Dynamic Secrets (база данных)

#### Получение динамических учетных данных

```bash
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/database/creds/app-role
# → {"lease_id":"database/creds/app-role/abc123","lease_duration":3600,"data":{"username":"v-token-app-role-...","password":"XyZ7kL9pQ2"},...}
```

#### Продление lease

```bash
# /sys/leases/renew — запрашивает продление на increment секунд от текущего времени
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"lease_id":"database/creds/app-role/abc123","increment":3600}' \
     https://vault.example.com:8200/v1/sys/leases/renew
```

#### Отзыв lease

```bash
# /sys/leases/revoke — немедленный отзыв конкретного lease
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"lease_id":"database/creds/app-role/abc123"}' \
     https://vault.example.com:8200/v1/sys/leases/revoke
```

> **Примечание:** подробнее о динамических секретах БД — в [Database Secrets Engine](./database_secrets_engine.md). О lease, TTL и префиксном отзыве — в [Lease, Renew, and Revoke](https://developer.hashicorp.com/vault/docs/concepts/lease).

### Сценарий 4: Transit Engine

#### Шифрование

```bash
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"plaintext":"c2Vuc2l0aXZldF9kYXRhX2hlcmU=","context":"dGVzdA=="}' \
     https://vault.example.com:8200/v1/transit/encrypt/app-encryption
# → {"data":{"ciphertext":"vault:v1:abc123...","key_version":1}}
```

#### Расшифровка

```bash
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"ciphertext":"vault:v1:abc123...","context":"dGVzdA=="}' \
     https://vault.example.com:8200/v1/transit/decrypt/app-encryption
```

#### Подписание

```bash
# POST /transit/sign/:name(/:hash_algorithm) — sha2-256 задаёт алгоритм хеширования
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"input":"dGVzdA=="}' \
     https://vault.example.com:8200/v1/transit/sign/app-signing/sha2-256
# → {"data":{"signature":"vault:v1:abc123..."}}
```

> **Примечание:** подробнее о Transit — в [Transit Encryption и Policies](./transit-encryption-policies.md).

### Сценарий 5: PKI

#### Выдача сертификата

```bash
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"common_name":"app.example.com","ttl":"24h","ip_sans":["10.0.0.1"]}' \
     https://vault.example.com:8200/v1/pki_int/issue/webapp
```

#### Подпись CSR

```bash
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"csr":"-----BEGIN CERTIFICATE REQUEST-----\n...","ttl":"24h"}' \
     https://vault.example.com:8200/v1/pki_int/sign/webapp
```

#### Отзов сертификата

```bash
# POST /pki/revoke с serial_number в теле (отзов по серийному номеру)
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"serial_number":"1a:2b:3c:4d"}' \
     https://vault.example.com:8200/v1/pki_int/revoke
# → {"data":{"revocation_time":1729000000}}
```

> **Примечание:** подробнее о PKI — в [PKI CA Advanced](./pki_ca_advanced.md).

### Сценарий 6: Response Wrapping (обертывание ответов)

#### Создание wrapped токена

```bash
# Запрос SecretID с wrapping через заголовок X-Vault-Wrap-Ttl
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     -H "X-Vault-Wrap-Ttl: 3600" \
     https://vault.example.com:8200/v1/auth/approle/role/myapp-role/secret-id
# → {"wrap_info":{"token":"hvs.CAESI...","ttl":3600,"creation_time":"...","creation_path":"auth/approle/role/myapp-role/secret-id"},...}
```

#### Распаковка wrapped токена

```bash
# Самораспаковка: wrapping token передаётся как X-Vault-Token
curl -s -X POST -H "X-Vault-Token: hvs.CAESI..." \
     https://vault.example.com:8200/v1/sys/wrapping/unwrap
# → {"data":{"secret_id":"98e4f7b3-..."}}
```

> **Примечание:** Response Wrapping покрыт подробно в [Cubbyhole и Response Wrapping](./cubbyhole_response_wrapping.md) (жизненный цикл, TTL, одноразовость, CI/CD). Wrapping запускается клиентом через заголовок `X-Vault-Wrap-Ttl`; в CLI — флагом `-wrap-ttl`. После `unwrap` wrapping token становится недействительным.

### Сценарий 7: Системные операции

#### Проверка состояния и мониторинг

```bash
# Health check (доступен без аутентификации, root namespace)
curl -s https://vault.example.com:8200/v1/sys/health
# → {"initialized":true,"sealed":false,"standby":false,"performance_standby":false,...}

# Статус (seal-status)
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/sys/seal-status

# Смонтированные движки
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/sys/mounts
```

#### Управление секрет-движками

```bash
# Включение KV v2 на пути secret/
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"type":"kv","options":{"version":"2"}}' \
     https://vault.example.com:8200/v1/sys/mounts/secret

# Список смонтированных движков
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/sys/mounts
# → {"data":{"secret/":{"type":"kv",...},"auth/":{"type":"token",...}}}

# Отключение движка
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/sys/mounts/secret/disable
```

#### Управление токенами

```bash
# Создание токена с ограниченными политиками
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"policies":["app-policy"],"ttl":"24h","explicit_max_ttl":"720h"}' \
     https://vault.example.com:8200/v1/auth/token/create
# → {"auth":{"client_token":"hvs.CAESI...","policies":["app-policy"],"lease_duration":86400,"renewable":true}}

# Информация о токене (self-lookup)
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/auth/token/lookup-self
# → {"data":{"ttl":84321,"policies":["app-policy"],"path":"auth/token/create"}}

# Revoke токена (self-revoke)
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/auth/token/revoke-self
```

#### Управление политиками

```bash
# Создание политики через API (POST /sys/policies/acl/:name)
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"policy":"path \"secret/data/myapp/*\" { capabilities = [\"read\"] }"}' \
     https://vault.example.com:8200/v1/sys/policies/acl/myapp-read

# Листинг политик (LIST /sys/policies/acl)
curl -s -X LIST -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/sys/policies/acl
# → {"data":{"keys":["myapp-read","default"]}}
```

#### Аудит и логирование

```bash
# Листинг audit-устройств
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/sys/audit

# Включение file audit device
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"type":"file","options":{"file_path":"/var/log/vault/audit.log"}}' \
     https://vault.example.com:8200/v1/sys/audit
```

#### Health check для load balancer

Для интеграции с LB/BGP/keepalived (active node = 200, sealed = 503, standby = 429):

```bash
curl -s -o /dev/null -w "%{http_code}" https://vault.example.com:8200/v1/sys/health
# → 200 (healthy) или 429 (standby — LB перенаправит на другой)

# Детальная проверка по заголовкам ответа
curl -s -D - -o /dev/null https://vault.example.com:8200/v1/sys/health 2>&1 | grep -E "X-Vault"
# → X-Vault-Initialized: true
# → X-Vault-Sealed: false
# → X-Vault-Standby: false
```

## Ограничения и известные проблемы

- **Rate limiting:** Родные квоты есть и в Vault Community: rate limit quotas (token bucket, ответ 429 Too Many Requests при превышении; в Community только группировка bucket'а по IP) и lease count quotas (лимит числа lease, Enterprise). LB может дополнительно ограничивать запросы. Подробнее — [Rate limit и lease quotas](./quotas.md).
- **Request size:** Максимальный размер запроса — 32 MiB (`max_request_size`, значение по умолчанию 33554432). Для передачи больших payload используйте presigned URL или chunked transfer.
- **Timeout:** По умолчанию `default_max_request_duration = 90s`; переопределяется на listener через `max_request_duration`. Транспортные таймауты задаются `http_read_timeout`/`http_write_timeout`/`http_idle_timeout`.
- **API versioning:** API V1 стабилен, breaking changes документируются в Release Notes. Начиная с 2.0.0 Vault требует canonicalized пути и отклоняет запросы с относительными ссылками (`/../`, `/./`, `//`) — используйте очищенные пути. Начиная с 2.0.0 раннее неаутентифицированные endpoint-семейства (`sys/rekey`, `sys/generate-root`, `sys/replication/dr/secondary/generate-operation-token`) требуют токен; для обратной совместимости используйте `enable_unauthenticated_access`.

## Устранение неполадок

### Стандартные HTTP-коды

| Код | Описание | Действие |
| :--- | :--- | :--- |
| 200 | Успех | Обработать ответ |
| 204 | Успех (нет содержимого) | Успешное удаление |
| 400 | Неверный запрос | Проверить параметры запроса |
| 403 | Запрещено | Проверить политику доступа |
| 404 | Не найдено | Проверить путь |
| 429 | Слишком много запросов (rate limit / standby) | Увеличить задержку (retry) |
| 500 | Внутренняя ошибка | Проверить логи Vault |
| 503 | Vault запечатан (sealed) или перегружен | Выполнить unseal |

> **Коды `/sys/health` (по умолчанию):** 200 — активен; 429 — standby (или Too Many Requests при lease quota); 472 — DR secondary; 473 — performance standby; 474 — standby без соединения с active; 501 — не инициализирован; 503 — sealed; 530 — удалён из кластера. Для 429 в health и 429 в rate limiting контексты отличаются.

#### Пример обработки ошибки

```python
import requests
import time

def vault_request(method, path, **kwargs):
    url = f"https://vault.example.com:8200/v1{path}"
    headers = kwargs.get('headers', {})
    headers['X-Vault-Token'] = VAULT_TOKEN

    for attempt in range(3):
        response = requests.request(method, url, headers=headers, **kwargs)

        if response.status_code == 429:
            # Rate limit или standby — retry с экспоненциальной задержкой
            time.sleep(2 ** attempt)
            continue
        elif response.status_code == 503:
            # Vault sealed или в maintenance — ждать и retry
            time.sleep(5)
            continue
        elif response.status_code == 200:
            return response.json()
        else:
            response.raise_for_status()

    raise Exception("Max retries exceeded")
```

### Частые проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **403 Forbidden** | Токен не имеет прав для path | Проверить политику через `vault policy read <name>` или `/v1/sys/policies/acl/<name>` |
| **404 Not Found** | Неверный путь или движок не смонтирован | Проверить `/v1/sys/mounts` и структуру пути (KV v2: `/data/`) |
| **429 Too Many Requests** | Rate limiting на LB или lease quota | Добавить retry с exponential backoff; проверить квоты |
| **503 Service Unavailable** | Vault запечатан, в maintenance, или перегружен | Выполнить unseal; для перегрузки — добавить retry |
| **Invalid request 400** | Неверный JSON или параметры | Проверить `Content-Type: application/json` и структуру payload |
| **Connection refused** | Vault не запущен или TLS ошибка | Проверить `systemctl status vault`, сертификаты, `VAULT_ADDR` |
| **TLS certificate error** | self-signed сертификат | Добавить `-k` для dev, либо добавить CA в системное доверие |
| **invalid path (400)** | Запрос с относительными ссылками (`/../`, `//`) | Vault 2.0+ требует canonicalized пути — используйте очищенный путь |

### Диагностика через CLI и API

```bash
# Проверка статуса (комбинация health + sealed)
vault status -format=json
# Проверка монтированных движков
curl -s -H "X-Vault-Token: $VAULT_TOKEN" https://vault.example.com:8200/v1/sys/mounts
# Проверка токена
curl -s -H "X-Vault-Token: $VAULT_TOKEN" https://vault.example.com:8200/v1/auth/token/lookup-self
# Листинг audit-устройств
curl -s -H "X-Vault-Token: $VAULT_TOKEN" https://vault.example.com:8200/v1/sys/audit
```

## Лучшие практики

1. **Используйте SDK:** Предпочитайте официальные SDK (hvac, vault-ruby) вместо прямых HTTP-запросов. SDK обрабатывают аутентификацию, токен-обновление и retry автоматически.
2. **Обработка ошибок:** Реализуйте retry с exponential backoff для 429/503 ошибок. 429 — rate limiting или standby; 503 — Vault sealed или в maintenance.
3. **TLS:** Всегда используйте HTTPS в production. Отключение `tls_disable` только для dev. Используйте mTLS для аутентификации клиентов.
4. **Токены:** Никогда не передавайте токены в URL, логах, или HTTP-заголовках Referer. Используйте заголовок `X-Vault-Token` или cookie. Устанавливайте короткий TTL (`ttl: 24h` или меньше).
5. **Персональные токены:** Для каждого сервиса создавайте отдельный токен с минимальными правами. Используйте `display_name` и `policy` для идентификации в аудит-логах.
6. **Request size:** Максимальный размер запроса — 32 MB (`max_request_size`). Для передачи больших payload используйте presigned URL или chunked transfer.
7. **Monitoring:** Отслеживайте HTTP-коды ответов, `vault.core` и `vault.raft` метрики. Настройте алерты на 503 (sealed) и 500 (internal errors).
8. **Namespace isolation (Enterprise):** Используйте `X-Vault-Namespace` для логической изоляции между team/environment. Каждый namespace имеет изолированное хранилище.
9. **Audit logging:** Всегда включайте audit device перед production-нагрузкой. Используйте `file` для локального хранилища, `syslog` для централизованного.
10. **Secret versioning (KV v2):** Используйте KV v2 для отслеживания изменений и отката. `delete` помечает версию удалённой (восстановимо через `undelete`), `destroy` удаляет данные необратимо.
11. **Dynamic secrets:** Предпочитайте dynamic secrets (Database, LDAP passthrough) вместо статических. Это обеспечивает автоматическую ротацию и истечение.
12. **Response wrapping:** Используйте заголовок `X-Vault-Wrap-Ttl` для безопасной передачи секретов между непосредственно доверенными сервисами. Wrapped токен можно использовать только один раз.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и ключевые преимущества.
*   **[Установка Vault](./vault_installation.md)** — настройка listener и TLS.
*   **[Аутентификация через AppRole](./vault_auth_approle.md)** — примеры API запросов для AppRole.
*   **[Cubbyhole и Response Wrapping](./cubbyhole_response_wrapping.md)** — жизненный цикл и практики Response Wrapping.
*   **[Database Secrets Engine](./database_secrets_engine.md)** — динамические учетные данные БД.
*   **[Transit Encryption и Policies](./transit-encryption-policies.md)** — шифрование и подпись.
*   **[PKI CA Advanced](./pki_ca_advanced.md)** — управление сертификатами.
*   [Официальная документация API](https://developer.hashicorp.com/vault/api-docs)
