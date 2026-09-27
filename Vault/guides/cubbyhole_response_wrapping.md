# Cubbyhole и Response Wrapping

## Определения

**Cubbyhole** — внутренний бэкенд Vault, привязанный к конкретному токену. Каждый токен получает изолированное пространство имен `cubbyhole/`, секреты в котором недоступны для других токенов, даже обладающих `sudo`-правами. Используется для временного хранения данных в контексте конкретного запроса.

**Response Wrapping (Обертывание ответов)** — механизм безопасной доставки секретов между сервисами. Vault возвращает временный одноразовый токен (wrapping token), содержащий итоговый секрет. Получатель разворачивает (unwrap) токен один раз и получает секрет.

**Wrapping Token** — временный токен доступа к wrapped секрету. Имеет ограниченный TTL и может быть использован только один раз.

**Unwrap (Распаковка)** — операция получения секрета из wrapping token. После успешного unwrap wrapping token становится невалидным.

**SecretID Wrapping** — применение Response Wrapping для передачи SecretID между сервисами без раскрытия его в открытом виде.

## Основные концепции

### Жизненный цикл Response Wrapping

1. **Запрос:** Сервис-отправитель запрашивает секрет с флагом `-wrap-ttl`.
2. **Wrapping:** Vault создаёт wrapping token с ограниченным TTL и возвращает его вместо секрета.
3. **Передача:** Отправитель передаёт wrapping_token получателю через защищённый канал.
4. **Unwrap:** Получатель выполняет `vault unwrap` и получает реальный секрет.
5. **Аннулирование:** Wrapping token становится невалидным после первого использования.

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
# → Key             Value
# → wrapping_token  hvs.CAESI...
# → wrapping_token_ttl  3600

# Передача wrapping_token приложению (через ENV, файл, API)
echo "hvs.CAESI..." > /tmp/wrapping_token
```

#### Получатель (приложение)

```bash
# Распаковка wrapping_token
VAULT_TOKEN=$(vault unwrap -token-only /tmp/wrapping_token)

# Аутентификация через AppRole
vault login -method=approle \
    role_id="6b2a5c4a-..." \
    secret_id="-"
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

# Распаковка SecretID
SECRET_ID=$(vault unwrap -token-only "$WRAPPING_TOKEN")

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
# Проверка информации о wrapping токене
vault unwrap -meta hvs.CAESI...
# → wrapping_token_ttl  3600
# → wrapping_token_creation_time  2026-09-24T12:00:00Z
# → wrapping_token_creation_path  auth/approle/role/myapp-role/secret-id

# Попытка повторного unwrap (должна завершиться ошибкой)
vault unwrap hvs.CAESI...
# → Error unwrapping token: token already unwrapped
```

## Лучшие практики

1. **Минимальный TTL:** Устанавливайте минимально возможный TTL для wrapping токена (60–3600 секунд).
2. **Одноразовость:** Никогда не используйте wrapping token повторно. После unwrap он становится невалидным.
3. **Защищённый канал:** Передавайте wrapping_token через защищённый канал (mTLS, VPN).
4. **Отзыв:** Если wrapping_token скомпрометирован — отзовите его через `vault token revoke`.
5. **Audit:** Включите audit device для отслеживания операций wrapping/unwrap.
6. **Error handling:** Обрабатывайте ошибку `already unwrapped` как сигнал возможной компрометации.

## Ограничения и известные проблемы

- **Одноразовость:** Wrapping token можно использовать только один раз. Повторный unwrap завершается ошибкой.
- **TTL:** TTL wrapping токена ограничен `max_lease_ttl_seconds` на сервере.
- **Cubbyhole:** Размер cubbyhole ограничен 1 MB. Не подходит для больших данных.
- **Токен:** Cubbyhole привязан к токену. При отзыве токена cubbyhole становится недоступен.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и безопасность.
*   **[Аутентификация через AppRole](../vault_auth_approle.md)** — примеры Response Wrapping.
*   **[Zero Trust](../zero_trust.md)** — роль Response Wrapping в архитектуре нулевого доверия.
*   **[Антипаттерны управления секретами](../common_antipatterns.md)** — почему Secret Zero опасен.
*   [Официальная документация Response Wrapping](https://developer.hashicorp.com/vault/docs/commands/wrap)
