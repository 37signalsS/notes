# Cubbyhole и Response Wrapping

**Актуально для:** Vault 2.x (latest 2.1.2)

## Определения

**Cubbyhole** — внутренний бэкенд Vault, привязанный к конкретному токену. Каждый токен получает изолированное пространство имен `cubbyhole/`, секреты в котором недоступны для других токенов, даже обладающих `sudo`-правами. Используется для временного хранения данных в контексте конкретного запроса.

**Response Wrapping (Обертывание ответов)** — механизм безопасной доставки секретов между сервисами. Vault возвращает временный одноразовый токен (wrapping token), содержащий итоговый секрет. Получатель разворачивает (unwrap) токен один раз и получает секрет.

**Wrapping Token** — временный токен доступа к wrapped секрету. Имеет ограниченный TTL и может быть использован только один раз.

**Unwrap (Распаковка)** — операция получения секрета из wrapping token. После успешного unwrap wrapping token становится невалидным.

**SecretID Wrapping** — применение Response Wrapping для передачи SecretID между сервисами без раскрытия его в открытом виде.

**wrap_info** — поле в ответе Vault API (JSON), содержащее метаданные wrapping token: `token`, `ttl`, `creation_time`, `creation_path` и `wrapped_accessor` (если обёрнутый ответ содержит токен аутентификации). Позволяет проверить подлинность wrapping token до распаковки.

## Предварительные требования

- **Vault 2.x** с включённым audit device (file или syslog) — Response Wrapping требует аудита для отслеживания unwrap-операций.
- **CLI Vault 2.x** или API-клиент с поддержкой заголовка `X-Vault-Wrap-TTL`.
- **TLS** между клиентом и Vault — wrapping token передаётся по сети и должен быть зашифрован.
- **TTL wrapping token ≤ `max_lease_ttl_seconds`** на сервере (по умолчанию 12h, но обычно снижается до 1h или меньше).
- **Секрет Zero** — для аутентификации клиента к Vault (токен, AppRole role_id или OIDC-токен), но не для передачи wrap-секрета.

## Основные концепции

### Жизненный цикл Response Wrapping

1. **Запрос:** Сервис-отправитель запрашивает секрет с флагом `-wrap-ttl`.
2. **Wrapping:** Vault создаёт wrapping token с ограниченным TTL и возвращает его вместо секрета. Секрет физически сохраняется в `cubbyhole/response` одноразового токена.
3. **Валидация (опционально):** Получатель может проверить `creation_path` и `ttl` через `sys/wrapping/lookup` до распаковки — это не потребляет токен.
4. **Передача:** Отправитель передаёт wrapping_token получателю через защищённый канал.
5. **Unwrap:** Получатель выполняет `vault unwrap` и получает реальный секрет. После unwrap токен становится невалидным.
6. **Аннулирование:** Wrapping token автоматически неактивен после unwrap или истечения TTL.

### Преимущества Response Wrapping

| Преимущество | Описание |
| :--- | :--- |
| **Отсутствие Secret Zero** | Не требуется передавать статические секреты между сервисами |
| **Одноразовость** | Wrapping token можно использовать только один раз |
| **TTL** | Автоматическое истечение по TTL |
| **Аудит** | Все операции логируются в audit device |
| **Отзыв** | Wrapping token можно отозвать до использования |

### Сравнение методов передачи секретов

| Метод | Безопасность | Аудит | Отзыв |
| :--- | :--- | :--- | :--- |
| **Plaintext (ENV)** | Нет | Нет | Нет |
| **Response Wrapping** | Высокая | Да | Да |
| **Vault Agent** | Высокая | Да | Да |
| **Secrets Sync** | Высокая | Да | Да |

## Практические сценарии

### Сценарий 1: Передача SecretID через Response Wrapping

#### Отправитель (оркестратор)

```bash
# Запрос SecretID с wrapping
vault write -wrap-ttl=3600 auth/approle/role/myapp-role/secret-id
# → Key                       Value
# → wrapping_token            hvs.CAESI...
# → wrapping_token_accessor   ydP3qR5s...
# → wrapping_token_ttl        3600

# Передача wrapping_token приложению (через ENV, файл, API)
echo "hvs.CAESI..." > /tmp/wrapping_token
```

#### Получатель (приложение)

```bash
# Распаковка wrapping_token (чтение токена из файла)
WRAPPING_TOKEN=$(cat /tmp/wrapping_token)

# Проверка подлинности wrapping token ДО распаковки (не потребляет токен)
vault write sys/wrapping/lookup token="$WRAPPING_TOKEN"
# → Key            Value
# → ttl            3600
# → creation_path  auth/approle/role/myapp-role/secret-id

# Распаковка — извлекаем SecretID
SECRET_ID=$(vault unwrap -field=secret_id "$WRAPPING_TOKEN")

# Аутентификация через AppRole
vault login -method=approle \
    role_id="6b2a5c4a-..." \
    secret_id="$SECRET_ID"
# → Success! Logged in with wrapped secret_id.
```

### Сценарий 2: Передача динамических секретов

```bash
# Запрос динамических учетных данных БД с wrapping
vault write -wrap-ttl=600 database/creds/app-role
# → wrapping_token  hvs.CAESI...

# Получатель распаковывает
vault unwrap hvs.CAESI...
# → {"lease_id":"database/creds/app-role/abc123","data":{"username":"v-token-app-role-...","password":"XyZ7kL9pQ2"},...}
```

### Сценарий 3: Использование в CI/CD пайплайне

```yaml
# .gitlab-ci.yml
stages:
  - deploy

deploy:
  stage: deploy
  script:
    - |
      # Запрос SecretID с wrapping
      WRAPPING_TOKEN=$(vault write -field=wrapping_token -wrap-ttl=3600 auth/approle/role/ci-runner/secret-id)
      
      # Передача wrapping_token в deploy-скрипт
      export WRAPPING_TOKEN
      ./deploy.sh
```

```bash
# deploy.sh
#!/bin/bash
set -euo pipefail

# Распаковка SecretID (извлекаем поле secret_id из wrapped ответа)
SECRET_ID=$(vault unwrap -field=secret_id "$WRAPPING_TOKEN")

# Аутентификация
VAULT_TOKEN=$(vault write -field=token auth/approle/login \
    role_id="$VAULT_ROLE_ID" \
    secret_id="$SECRET_ID")

# Получение секретов
vault kv get secret/myapp/config
```

### Сценарий 4: Автоматическая ротация SecretID

```bash
# Скрипт для ротации SecretID
#!/bin/bash
# rotate-secret-id.sh

# 1. Запрос нового SecretID с wrapping
WRAPPING_TOKEN=$(vault write -field=wrapping_token -wrap-ttl=60 auth/approle/role/myapp-role/secret-id)

# 2. Передача в приложение через API
curl -X POST https://myapp.example.com/api/v1/rotate-secret-id \
     -H "Content-Type: application/json" \
     -d "{\"wrapping_token\":\"$WRAPPING_TOKEN\"}"

# 3. Приложение распаковывает и обновляет SecretID
```

### Сценарий 5: Использование Cubbyhole для временных данных

```bash
# Запись в cubbyhole (доступно только текущему токену)
vault write cubbyhole/temp-data key=value

# Чтение из cubbyhole
vault read cubbyhole/temp-data
# → Key             Value
# → key             value

# После отзыва токена cubbyhole становится недоступен
vault token revoke <token>
```

### Сценарий 6: Валидация wrapping токена

```bash
# Проверка информации о wrapping токене (lookup НЕ потребляет токен)
VAULT_TOKEN=hvs.CAESI... vault write sys/wrapping/lookup
# → Key            Value
# → ttl            3600
# → creation_time  2026-09-24T12:00:00Z
# → creation_path  auth/approle/role/myapp-role/secret-id

# Попытка повторного unwrap (должна завершиться ошибкой)
vault unwrap hvs.CAESI...
# → Error unwrapping token: token already unwrapped
```

### Сценарий 7: Cubbyhole и API-клиенты

```bash
# Запись данных в cubbyhole через HTTP API (например, для передачи сессионного токена)
curl -s -X POST -H "X-Vault-Token: $VAULT_TOKEN" \
  -d '{"session_token":"abc123","expires_at":"2026-12-31T23:59:59Z"}' \
  https://vault.example.com:8200/v1/cubbyhole/session-data \
  | jq -r '.data'

# Чтение через API
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
  https://vault.example.com:8200/v1/cubbyhole/session-data

# Удаление (явное)
curl -s -X DELETE -H "X-Vault-Token: $VAULT_TOKEN" \
  https://vault.example.com:8200/v1/cubbyhole/session-data

# Чтение из snapshot (Vault 2.x): предварительно загрузите snapshot через
# `vault snapshot load <snapshot_file>`, затем укажите read_snapshot_id
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
  "https://vault.example.com:8200/v1/cubbyhole/session-data?read_snapshot_id=2403d301-94f2-46a1-a39d-02be83e2831a"
```

## Операции и команды (API)

### API Cubbyhole secrets engine

| Метод | HTTP-путь | Описание | Пример |
| :--- | :--- | :--- | :--- |
| `GET` | `/cubbyhole/:path` | Read secret (`?read_snapshot_id=<id>` — чтение из snapshot, Vault 2.x) | `vault read cubbyhole/creds` |
| `POST` | `/cubbyhole/:path` | Create/Update secret | `vault write cubbyhole/temp k=v` |
| `LIST` | `/cubbyhole/:path` | List secret entries | `vault list cubbyhole/` |
| `DELETE` | `/cubbyhole/:path` | Delete secret | `vault delete cubbyhole/temp` |
| `RECOVER` | `/cubbyhole/:path` | Recover secret из snapshot (Vault 2.x) | `curl -X RECOVER` с `X-Vault-Recover-Snapshot-Id` |

**RECOVER** — метод Vault 2.x для восстановления cubbyhole-данных из предварительно загруженного snapshot. Требует два заголовка:
- `X-Vault-Recover-Snapshot-Id` — ID загруженного snapshot (обязательно)
- `X-Vault-Recover-Source-Path` — исходный путь в snapshot, если отличается от целевого (опционально)

Подробности — в [документации Vault: Recover a secret](https://developer.hashicorp.com/vault/docs/sysadmin/snapshots/recover-a-secret).

### API Response Wrapping (`sys/wrapping`)

| Метод | HTTP-путь | Описание | Пример |
| :--- | :--- | :--- | :--- |
| — | `X-Vault-Wrap-TTL` header | Trigger wrapping на любой API-запрос | `curl -H "X-Vault-Wrap-TTL: 3600" ...` |
| `POST` | `/sys/wrapping/lookup` | Lookup свойств wrapping токена (unauthenticated) | `vault write sys/wrapping/lookup token=...` |
| `POST` | `/sys/wrapping/unwrap` | Unwrap токен, получить оригинальный ответ | `vault unwrap hvs.CAESI...` |
| `POST` | `/sys/wrapping/wrap` | Helper: wrap произвольных данных | `vault write sys/wrapping/wrap data=@file` |

**Важно:** чтение `cubbyhole/response` напрямую устарело (deprecated) — всегда используйте `sys/wrapping/unwrap`, который выполняет дополнительные проверки и корректно аудит-логирует операцию.

## Устранение неполадок

### Ошибка: `wrapping token is not a token` / `invalid token`

| Признак | Причина | Решение |
| :--- | :--- | :--- |
| `Error unwrapping token: invalid token` | Токен истёк (TTL), отозван, или уже использован (consumed) | Проверить `sys/wrapping/lookup` — если `ttl=0` или ошибка 403, токен недействителен. Выпросить новый wrapping token у отправителя. |
| `Error looking up token: permission denied` | На lookup используется не wrapping token | Использовать wrapping token как `VAULT_TOKEN` или передать в `token=` параметре: `vault write sys/wrapping/lookup token=hvs.CAESI...` |
| `Error unwrapping token: token already unwrapped` | Токен был уже распакован (double unwrap) | Ошибка ожидаема — не пытайтесь unwrap дважды. Возможная компрометация: проверить аудит-лог. |
| `403 forbidden: error calling sys/wrapping/unwrap` | Токен используется как client token И в `token=` параметре одновременно | Не передавайте wrapping token в обоих местах — используйте либо как `VAULT_TOKEN`, либо в `token=`, но не оба. |

### Диагностика

```bash
# 1. Проверить, не использован ли токен (lookup НЕ потребляет токен)
vault write sys/wrapping/lookup token=hvs.CAESI...
# → ttl > 0 и creation_path совпадает с ожидаемым — токен валиден

# 2. Если lookup пишет "invalid token" — токен истёк или уже использован
# Проверить audit log на предмет unwrap-операции:
vault audit list -format=json
# Или поискать в audit-файле:
grep "hvs.CAESI..." /var/log/vault_audit.log | grep "unwrap"

# 3. Если unwrap возвращает неверные данные — проверить creation_path
# Подделанный wrapping token может содержать секрет с неожиданным путём
```

### Ограничения

- **Одноразовость:** Wrapping token можно использовать только один раз. Повторный unwrap завершается ошибкой `token already unwrapped`.
- **TTL:** TTL wrapping токена ограничен `max_lease_ttl_seconds` на сервере. Если запрошенный `-wrap-ttl` превышает `max_lease_ttl_seconds`, Vault использует серверный максимум.
- **Cubbyhole size:** Размер данных в cubbyhole ограничен 1 MB. Не подходит для больших payload-ов.
- **Токен-зависимость:** Cubbyhole привязан к токену. При отзыве токена (например, через `vault token revoke`) его cubbyhole становится недоступным, включая незавершённые wrapping операции.

## Лучшие практики

1. **Минимальный TTL:** Устанавливайте минимально возможный TTL для wrapping токена (60–3600 секунд).
2. **Одноразовость:** Никогда не используйте wrapping token повторно. После unwrap он становится невалидным.
3. **Защищённый канал:** Передавайте wrapping_token через защищённый канал (mTLS, VPN).
4. **Отзыв:** Если wrapping_token скомпрометирован — отзовите его через `vault token revoke`.
5. **Audit:** Включите audit device для отслеживания операций wrapping/unwrap.
6. **Error handling:** Обрабатывайте ошибку `already unwrapped` как сигнал возможной компрометации.
7. **Валидация пути:** Проверяйте `creation_path` через `sys/wrapping/lookup` перед unwrap — отклонение от ожидаемого пути может сигнализировать о MITM-атаке или подмене токена.

### Валидация и проверка

Перед использованием распакованного секрета обязательно проверьте:

1. **Тип секрета:** убедитесь, что `creation_path` соответствует ожидаемому (например, `auth/approle/role/myapp-role/secret-id`, а не `sys/wrapping/wrap`).
2. **Схожесть с истощимым токеном:** если `sys/wrapping/lookup` возвращает ошибку — не пытайтесь unwrap, а запрашивайте новый токен.
3. **Аудит:** после unwrap проверьте audit log на запись о successful unwrap с вашим client_token.

```bash
# Валидация перед unwrap
LOOK_INFO=$(vault write -format=json sys/wrapping/lookup token="$WRAPPING_TOKEN" | jq '.data')
TTL=$(echo "$LOOK_INFO" | jq -r '.ttl')
PATH_VAL=$(echo "$LOOK_INFO" | jq -r '.creation_path')

if [ "$TTL" -le 0 ] 2>/dev/null; then
  echo "ERROR: wrapping token expired or consumed"
  exit 1
fi

if [ "$PATH_VAL" != "auth/approle/role/myapp-role/secret-id" ]; then
  echo "ERROR: unexpected creation_path: $PATH_VAL"
  echo "Possible token substitution attack"
  exit 1
fi

# Только после валидации — unwrap
SECRET_ID=$(vault unwrap -field=secret_id "$WRAPPING_TOKEN")
```

### Очистка и откат

- **Явное удаление cubbyhole:** если wrapping token не используется или скомпрометирован, удалите данные из cubbyhole: `vault delete cubbyhole/response` (требует токена с правами на cubbyhole).
- **Отзыв токена:** `vault token revoke <wrapping_token>` немедленно делает токен недействительным и очищает associated cubbyhole.
- **Rotация:** регулярно ротацию SecretID/токенов, используйте `wrap-ttl` не более 10 минут для CI/CD.
- **Cleanup временных файлов:** удаляйте временные файлы с wrapping token (`/tmp/wrapping_token`) после использования: `shred -u /tmp/wrapping_token`.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и безопасность.
*   **[Аутентификация через AppRole](../vault_auth_approle.md)** — примеры Response Wrapping.
*   **[Zero Trust](../zero_trust.md)** — роль Response Wrapping в архитектуре нулевого доверия.
*   **[Антипаттерны управления секретами](../common_antipatterns.md)** — почему Secret Zero опасен.
*   [Официальная документация Response Wrapping](https://developer.hashicorp.com/vault/docs/concepts/response-wrapping)
