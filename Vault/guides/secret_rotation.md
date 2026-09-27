# Ротация секретов в Vault

## Определения

**Rotation (Ротация)** — процесс периодического обновления секретов (паролей, ключей, токенов) без остановки сервиса. Ротация минимизирует риск компрометации, ограничивая время жизни секрета.

**TTL (Time To Live)** — время жизни секрета или токена. По истечении TTL секрет автоматически становится невалидным.

**Max TTL** — максимальное время жизни секрета. Даже при продлении (renew) секрет не может прожить дольше `max_ttl`.

**Rotation Policy (Политика ротации)** — набор правил, определяющих частоту и способ ротации секретов. Политика учитывает критичность секрета, время ротации и механизм доставки.

**Graceful Rotation (Graceful переключение)** — процесс ротации без простоя сервиса. Приложение поддерживает несколько версий секрета одновременно во время ротации.

**Zero-Downtime Rotation** — ротация без остановки сервиса. Достигается через overlapping период, когда оба секрета (старый и новый) валидны.

**Secret Versioning** — механизм хранения нескольких версий секрета (KV v2). Позволяет откатиться на предыдущую версию при проблемах с новой.

## Основные концепции

### Типы ротации

| Тип | Описание | Use case |
| :--- | :--- | :--- |
| **Автоматическая** | Vault или инструмент автоматически обновляет секрет | Production, high-security среды |
| **Полуавтоматическая** | Vault генерирует новый секрет, но требуется подтверждение | Критичные секреты, compliance |
| **Ручная** | Администратор вручную обновляет секрет | Legacy-системы, редкие случаи |

### Стратегии ротации

| Стратегия | Описание | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **На основе времени** | Ротация через фиксированный интервал (1h, 24h) | Простота, предсказуемость | Может ротировать неиспользуемые секреты |
| **На основе использования** | Ротация после N использований | Эффективно для дорогих операций | Сложнее в реализации |
| **На основе события** | Ротация при компрометации, увольнении | Минимальный радиус поражения | Требует процесса реагирования |
| **Гибридная** | Комбинация времени и событий | Баланс безопасности и удобства | Сложность настройки |

### Механизмы ротации в Vault

1. **Dynamic Secrets:** Автоматическая ротация через TTL и lease. Секрет отзывается по истечении TTL.
2. **Static Roles:** Vault автоматически ротирует пароль существующего пользователя через `rotation_period`.
3. **KV v2:** Встроенная версионность секретов. Ротация через обновление версии.
4. **Transit Engine:** Ротация ключей через `/rotate` endpoint.
5. **Vault Agent:** Автоматическое обновление секретов в файлах без перезапуска приложения.

## Практические сценарии

### Сценарий 1: Автоматическая ротация через Dynamic Secrets

Dynamic secrets автоматически отзываются по истечении TTL:

```bash
# Создание dynamic role с TTL 1 час
vault write database/roles/app-role \
    db_name=my-postgresql \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}';" \
    default_ttl="1h" \
    max_ttl="24h" \
    revocation_statements="DROP ROLE IF EXISTS \"{{name}}\";"
```

Приложение получает новые учетные данные каждые 15 минут (рекомендуется):

```hcl
template {
  destination = "/app/secrets/db-config.yaml"
  contents    = <<-EOH
    {{- with secret "database/creds/app-role" -}}
    DB_USER={{ .Data.data.username }}
    DB_PASSWORD={{ .Data.data.password }}
    LEASE_DURATION={{ .LeaseData.lease_duration }}
    {{- end -}}
  EOH
  command = ["sh", "-c", "kill -HUP $(pgrep -f myapp)"]
  wait {
    min = "2s"
    max = "10s"
  }
}
```

### Сценарий 2: Ротация static role паролей

Static role позволяет Vault управлять паролем существующего пользователя:

```bash
# Создание static role
vault write database/static-roles/myapp-static \
    db_name=my-postgresql \
    username="myapp_user" \
    rotation_period="24h"

# Просмотр текущего пароля
vault read database/static-creds/myapp-static
# → username        myapp_user
# → password        XyZ7kLL9pQ2
# → last_rotation   2026-09-24T10:00:00Z
# → rotation_period 24h
```

Vault автоматически ротирует пароль каждые 24 часа. Приложение получает актуальный пароль через:

```bash
vault read database/static-creds/myapp-static
```

### Сценарий 3: Ротация KV v2 секретов

KV v2 поддерживает версионность. Ротация через обновление версии:

```bash
# Обновление секрета (создаётся новая версия)
vault kv put secret/myapp/config password="new_password" api_key="new_api_key"

# Просмотр истории версий
vault kv metadata get secret/myapp/config
# → versions
# →   1 (деле)
# →   2 (текущая)

# Откат на предыдущую версию
vault kv undo secret/myapp/config -versions=1
```

### Сценарий 4: Graceful Rotation для приложений

Приложение должно поддерживать graceful reload при смене пароля:

```python
import signal
import os

def reload_config(signum, frame):
    """Перечитывание конфигурации без остановки сервиса"""
    global db_password
    # Получение нового пароля из файла
    with open('/app/secrets/db_password.txt') as f:
        db_password = f.read().strip()
    # Переподключение к БД
    reconnect_database()
    print("Configuration reloaded")

signal.signal(signal.SIGHUP, reload_config)
```

### Сценарий 5: Ротация Transit Engine ключей

```bash
# Создание ключа
vault write -f transit/keys/app-encryption \
    type=aes256-gcm \
    exportable=false

# Ротация ключа (создаётся новая версия)
vault write transit/keys/app-encryption/rotate

# Проверка версий
vault read transit/keys/app-encryption
# → versions
# →   1 (старая)
# →   2 (текущая)

# Настройка min_encryption_version для принудительного перехода
vault write transit/keys/app-encryption/config \
    min_encryption_version=2

# Удаление старых версий (необратимо!)
vault write transit/keys/app-encryption/trim min_available_versions=2
```

### Сценарий 6: Ротация SSH CA ключей

```bash
# Создание новой CA-роли с новым ключом
vault write ssh/roles/user-role-v2 \
    key_type=ca \
    default_user=ubuntu \
    allowed_users="ubuntu,admin" \
    ttl=8h \
    max_ttl=24h

# Получение нового CA-ключа
vault read -field=public_key ssh/roles/user-role-v2 > /etc/ssh/trusted-user-ca-keys-v2.pub

# Распространение нового CA-ключа
ansible all -m copy -a "src=/etc/ssh/trusted-user-ca-keys-v2.pub dest=/etc/ssh/trusted-user-ca-keys-v2.pub mode=0644"

# Добавление второго CA-ключа в sshd_config
# TrustedUserCAKeys /etc/ssh/trusted-user-ca-keys.pub /etc/ssh/trusted-user-ca-keys-v2.pub

# Перезапуск SSH
ansible all -m systemd -a "name=sshd state=restarted"

# После исхода TTL старых сертификатов — удаление старой роли
vault delete ssh/roles/user-role
```

### Сценарий 7: Мониторинг и аудит ротации

```bash
# Проверка последней ротации static role
vault read database/static-roles/myapp-static
# → last_rotation   2026-09-24T10:00:00Z

# Проверка версий KV v2
vault kv metadata get secret/myapp/config

# Мониторинг через audit log
jq 'select(.request.path | startswith("transit/keys") and .request.path | endswith("/rotate"))' /var/log/vault/audit.log
```

## Лучшие практики

1. **Автоматизация:** Используйте dynamic secrets или static roles вместо ручной ротации.
2. **TTL:** Настраивайте TTL минимально необходимым (15–60 минут для БД, 1–24 часа для приложений).
3. **Graceful reload:** Приложение должно поддерживать graceful reload при смене пароля.
4. **Overlapping период:** При ротации CA-ключей используйте overlapping период, когда оба CA валидны.
5. **Мониторинг:** Отслеживайте время последней ротации и upcoming событий.
6. **Audit:** Включите audit device для отслеживания всех операций ротации.
7. **Документация:** Документируйте политику ротации для каждого типа секретов.

## Ограничения и известные проблемы

- **Static roles:** Требуют, чтобы Vault имел права на обновление пароля в БД.
- **Dynamic secrets:** Создают много пользователей в БД. Убедитесь, что БД выдерживает нагрузку.
- **Graceful reload:** Не все приложения поддерживают graceful reload. Для legacy-систем используйте sidecar-паттерн.
- **Транзакции:** При истечении TTL во время активной транзакции пользователь может быть удалён. Настройте `max_ttl` с запасом.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и движки секретов.
*   **[Database Secrets Engine](./database_secrets_engine.md)** — автоматическая ротация учетных данных БД.
*   **[Transit Engine — Политики](./transit-encryption-policies.md)** — ротация криптографических ключей.
*   **[SSH Secrets Engine](./ssh_secrets_engine.md)** — ротация SSH-ключей.
*   **[Zero Trust](../zero_trust.md)** — роль ротации в архитектуре нулевого доверия.
