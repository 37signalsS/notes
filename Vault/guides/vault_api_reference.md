# Vault API — comprehensive reference

## Определения

**Vault API** — RESTful HTTP API, предоставляемый Vault для всех операций. Все взаимодействия с Vault (CLI, UI, SDK) осуществляются через API.

**Endpoint** — конкретный URL в API Vault, например `/v1/secret/data/myapp/config`.

**Request ID** — уникальный идентификатор запроса, возвращается в заголовке `X-Vault-Request-Id`. Используется для трассировки и расследования инцидентов.

**Namespace Header** — заголовок `X-Vault-Namespace`, используемый для указания namespace в запросе (Enterprise).

**Wrapping Token** — временный токен, возвращаемый Vault при использовании флага `-wrap-ttl`. Используется для безопасной передачи секретов между сервисами.

**Batch Request** — запрос, содержащий несколько операций в одном HTTP-вызове. Поддерживается для некоторых движков (Transit, Database).

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
LIST   /v1/secret/metadata/myapp - Список ключей
```

### Заголовки запросов

| Заголовок | Описание | Обязательный |
| :--- | :--- | :--- |
| `X-Vault-Token` | Токен аутентификации | Да (для большинства запросов) |
| `X-Vault-Namespace` | Namespace (Enterprise) | Нет |
| `X-Vault-Request` | Подтверждение, что запрос от Vault | Нет |
| `Content-Type` | Тип содержимого | Да (обычно `application/json`) |
| `Accept` | Формат ответа | Нет |

### Форматы ответов

| Формат | Описание | Использование |
| :--- | :--- | :--- |
| `JSON` (по умолчанию) | Структурированный JSON | Большинство случаев |
| `text/plain` | Текстовый формат | Простые значения |
| `application/octet-stream` | Бинарные данные | Сертификаты, ключи |

## Практические сценарии

### Сценарий 1: Базовые операции с секретами

#### Чтение секрета (KV v2)

```bash
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/secret/data/myapp/config
# → {"request_id":"...","data":{"data":{"password":"...","username":"..."},"metadata":{...}}}
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
curl -s -X DELETE -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/secret/data/myapp/config
```

#### Список секретов

```bash
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/secret/metadata/myapp/
# → {"keys": ["config", "db", "api-key"]}
```

### Сценарий 2: Аутентификация через API

#### AppRole

```bash
# Аутентификация
curl -s -X POST -H "Content-Type: application/json" \
     -d '{"role_id":"6b2a5c4a-...","secret_id":"98e4f7b3-..."}' \
     https://vault.example.com:8200/v1/auth/approle/login
# → {"auth":{"client_token":"hvs.CAESI...","policies":["default","app-policy"],...}}
```

#### Kubernetes

```bash
# Чтение ServiceAccount токена
SA_TOKEN=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)

# Аутентификация
curl -s -X POST -H "Content-Type: application/json" \
     -d "{\"jwt\":\"$SA_TOKEN\",\"role\":\"myapp-role\"}" \
     https://vault.example.com:8200/v1/auth/kubernetes/login
```

#### JWT/OIDC

```bash
curl -s -X POST -H "Content-Type: application/json" \
     -d '{"jwt":"eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...","role":"ci-runner"}' \
     https://vault.example.com:8200/v1/auth/jwt/login
```

### Сценарий 3: Dynamic Secrets

#### Database credentials

```bash
# Получение динамических учетных данных
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/database/creds/app-role
# → {"lease_id":"database/creds/app-role/abc123","data":{"username":"v-token-app-role-...","password":"XyZ7kL9pQ2"},...}
```

#### Продление lease

```bash
curl -s -X PUT -H "X-Vault-Token: $VAULT_TOKEN" \
     -d '{"lease_id":"database/creds/app-role/abc123","increment":3600}' \
     https://vault.example.com:8200/v1/sys/leases/lookup
```

#### Отзыв lease

```bash
curl -s -X DELETE -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/database/creds/app-role/abc123
```

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
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"input":"dGVzdA=="}' \
     https://vault.example.com:8200/v1/transit/sign/app-signing/sha2-256
```

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

#### Отзыв сертификата

```bash
curl -s -X DELETE -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/pki_int/revoke/1a2b3c4d
```

### Сценарий 6: Response Wrapping

#### Создание wrapped токена

```bash
# Запрос SecretID с wrapping
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
     -d '{"wrap_ttl":"3600"}' \
     https://vault.example.com:8200/v1/auth/approle/role/myapp-role/secret-id
# → {"wrapping_token":"hvs.CAESI...","wrapping_token_ttl":3600}
```

#### Распаковка wrapped токена

```bash
curl -s -X POST -H "Content-Type: application/json" \
     -d '{"token":"hvs.CAESI..."}' \
     https://vault.example.com:8200/v1/sys/wrapping/unwrap
# → {"data":{"secret_id":"98e4f7b3-..."}}
```

### Сценарий 7: Системные операции

#### Проверка здоровья

```bash
curl -s https://vault.example.com:8200/v1/sys/health
# → {"initialized":true,"sealed":false,"standby":false,...}
```

#### Проверка статуса

```bash
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/sys/status
```

#### Проверка смонтированных движков

```bash
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault.example.com:8200/v1/sys/mounts
```

### Сценарий 8: Обработка ошибок

#### Стандартные HTTP-коды

| Код | Описание | Действие |
| :--- | :--- | :--- |
| 200 | Успех | Обработать ответ |
| 204 | Успех (нет содержимого) | Успешное удаление |
| 400 | Неверный запрос | Проверить параметры запроса |
| 403 | Запрещено | Проверить политику доступа |
| 404 | Не найдено | Проверить путь |
| 429 | Слишком много запросов | Увеличить задержку (retry) |
| 500 | Внутренняя ошибка | Проверить логи Vault |
| 503 | Vault запечатан | Выполнить unseal |

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
            # Rate limit - retry with backoff
            time.sleep(2 ** attempt)
            continue
        elif response.status_code == 503:
            # Vault sealed - wait and retry
            time.sleep(5)
            continue
        elif response.status_code == 200:
            return response.json()
        else:
            response.raise_for_status()
    
    raise Exception("Max retries exceeded")
```

## Лучшие практики

1. **Используйте SDK:** Предпочитайте официальные SDK (hvac, vault-ruby) вместо прямых HTTP-запросов.
2. **Обработка ошибок:** Реализуйте retry с exponential backoff для 429/503 ошибок.
3. **TLS:** Всегда используйте HTTPS в production. Отключение `tls_disable` только для dev.
4. **Токены:** Никогда не передавайте токены в URL. Используйте заголовок `X-Vault-Token`.
5. **Batch requests:** Используйте batch запросы для снижения количества round-trip.
6. **Monitoring:** Отслеживайте HTTP-коды ответов для диагностики проблем.

## Ограничения и известные проблемы

- **Rate limiting:** Vault не имеет встроенного rate limiting, но LB может ограничивать запросы.
- **Request size:** Максимальный размер запроса — 32 MB (`max_request_size`).
- **Timeout:** По умолчанию timeout = 90s. Настройте `read_timeout`/`write_timeout` в listener.
- **API versioning:** API V1 является стабильным. Breaking changes документируются в Release Notes.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура API.
*   **[Установка Vault](../guides/vault_installation.md)** — настройка listener и TLS.
*   **[Аутентификация через AppRole](../vault_auth_approle.md)** — примеры API запросов.
*   [Официальная документация API](https://developer.hashicorp.com/vault/api-docs)
