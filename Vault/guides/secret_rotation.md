# Ротация секретов в Vault

> **Актуально для:** Vault Enterprise/PKI 2.x (latest 2.1.2; ветка 1.21.x поддерживается)

## Определения

**Rotation (Ротация)** — процесс периодического обновления секретов (паролей, ключей, токенов) без остановки сервиса. Ротация минимизирует риск компрометации, ограничивая время жизни секрета.

**TTL (Time To Live)** — время жизни секрета или токена. По истечении TTL секрет автоматически становится невалидным.

**Max TTL** — максимальное время жизни секрета. Даже при продлении (renew) секрет не может прожить дольше `max_ttl`.

**Rotation Policy (Политика ротации)** — набор правил, определяющих частоту и способ ротации секретов. Политика учитывает критичность секрета, время ротации и механизм доставки.

**Graceful Rotation (Graceful переключение)** — процесс ротации без простоя сервиса. Приложение поддерживает несколько версий секрета одновременно во время ротации.

**Zero-Downtime Rotation** — ротация без остановки сервиса. Достигается через overlapping период, когда оба секрета (старый и новый) валидны.

**Secret Versioning** — механизм хранения нескольких версий секрета (KV v2). Позволяет откатиться на предыдущую версию при проблемах с новой.

**Static Role** — роль в Database Secrets Engine, которая сопоставляет Vault role с существующим пользователем в БД. Пароль пользователя ротируется автоматически через `rotation_period` или `rotation_schedule`.

**Dynamic Secret** — временный секрет (например, DB credentials), который автоматически создаётся и отзывается через lease TTL.

**Root Credential Rotation** — процесс ротации учётных данных Database Secrets Engine root-пользователя через `/database/rotate-root/:name`.

**Automated Rotation** — система централизованной ротации Vault Enterprise, которая использует rotation policies для управления retry-поведением и exponential backoff.

**Orphaned Rotation Entry** — запись ротации, помеченная как orphaned при превышении лимита retries. Требует ручного вмешательства.

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
| **На основе события** | Ротация при компрометации, увольнении | Минимальный радиус поражения | Требует [процесса реагирования](./incident-response.md) |
| **Гибридная** | Комбинация времени и событий | Баланс безопасности и удобства | Сложность настройки |

### Механизмы ротации в Vault

1. **Dynamic Secrets:** Автоматическая ротация через TTL и lease. Секрет отзывается по истечении TTL.
2. **Static Roles:** Vault автоматически ротирует пароль существующего пользователя через `rotation_period` или `rotation_schedule`. Минимальный `rotation_period` — 5 секунд.
3. **KV v2:** Встроенная версионность секретов. Ротация через обновление версии (подробнее — [KV v2](./kv-v2.md)).
4. **Transit Engine:** Ротация ключей через `/rotate` endpoint. Можно настроить `auto_rotate_period` для автоматической ротации (минимум 1 час).
5. **Database Root Credentials:** Vault Enterprise поддерживает `rotation_schedule`/`rotation_window` для root credentials и `rotation_period`/`rotation_schedule` для static roles (взаимно исключающие).
6. **Vault Agent:** Автоматическое обновление секретов в файлах без перезапуска приложения.
7. **Automated Rotation (Enterprise):** Централизованная система ротации с rotation policies, exponential backoff и orphan management.

### Мониторинг ротации (SRE)

Vault Enterprise автоматически ротацию логирует в стандартный `vault.log`:

```
[INFO]  rotation-job-manager: successfully rotated job: rotationID=database/config/my-database
[ERROR] rotation-job-manager: rotation failed, attempting to re-queue: rotationID=database/config/my-database error="connection refused"
[ERROR] rotation-job-manager: orphaning item, please re-register after resolving the error: rotationID=database/config/my-database
```

Для проверки статуса ротации читаются поля:

| Поле | Описание |
| :--- | :--- |
| `last_vault_rotation` | Timestamp последней успешной ротации |
| `next_vault_rotation` | Timestamp следующей запланированной ротации |
| `ttl` | Секунд до начала следующей ротации |

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

#### Root credential rotation

Для root credentials Database Secrets Engine используйте:

```bash
# Ротация root credentials (Vault Enterprise)
vault write -force database/rotate-root/my-postgresql
# → Это безопасно — пароль больше не доступен через Vault
```

### Сценарий 2: Ротация static role паролей

Static role позволяет Vault управлять паролем существующего пользователя:

```bash
# Создание static role с rotation_period 24h (минимум 5s)
vault write database/static-roles/myapp-static \
    db_name=my-postgresql \
    username="myapp_user" \
    rotation_period="24h" \
    rotation_statements="ALTER USER \"{{name}}\" WITH PASSWORD '{{password}}';"

# Просмотр текущего пароля и статуса ротации
vault read database/static-creds/myapp-static
# → Key                   Value
# → username              myapp_user
# → password              XyZ7kLL9pQ2
# → last_vault_rotation   2026-09-24T10:00:00Z
# → rotation_period       24h
# → ttl                   3600

# Ручной запуск ротации (переименование: rotate-role)
vault write -force database/rotate-role/myapp-static
```

#### Schedule-based rotation (Vault Enterprise)

Для более тонкой настройки используйте cron-расписание:

```bash
# rotation_period и rotation_schedule взаимно исключающие
vault write database/static-roles/myapp-static \
    db_name=my-postgresql \
    username="myapp_user" \
    rotation_schedule="0 2 * * SAT" \
    rotation_window="1h" \
    rotation_statements="ALTER USER \"{{name}}\" WITH PASSWORD '{{password}}';"
```

Если ротация не успевает завершиться в `rotation_window`, она повторяется на следующей неделе.

#### Skip initial rotation

Для onboarding без немедленной ротации:

```bash
vault write database/static-roles/myapp-static \
    db_name=my-postgresql \
    username="myapp_user" \
    skip_import_rotation=true \
    password="initial_password_from_legacy_system"
```

### Сценарий 3: Ротация KV v2 секретов

KV v2 поддерживает версионность. Ротация через обновление версии:

```bash
# Обновление секрета (создаётся новая версия)
vault kv put secret/myapp/config password="new_password" api_key="new_api_key"
# → Key              Value
# → secret/           metadata
# →     current_version  3
# →     oldest_version   1
# →     max_versions     10

# Просмотр истории версий
vault kv metadata get secret/myapp/config
# → Key                Value
# → ---                -----
# → cas_required       false
# → current_version    3
# → oldest_version     1
# → max_versions       0
# → custom_metadata    <nil>

# Отмена последней записи (мягкое удаление)
vault kv delete secret/myapp/config -versions=3
# → Success! Data deleted (if it existed) at: secret/myapp/config

# Восстановление удалённой версии (не undo!)
vault kv undelete secret/myapp/config -versions=3

# Откат на предыдущую версию: читаем версию 2, пишем как новую
vault kv get -version=2 secret/myapp/config
# используйте полученные значения в:
vault kv put secret/myapp/config password="previous_password" api_key="previous_api_key"
```

**Важно:** `vault kv undo` — это несуществующая команда. Для отката используйте `vault kv get -version=N` + `vault kv put`.

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
# Создание ключа с автоматической ротацией (минимум 1 час)
vault write -f transit/keys/app-encryption \
    type=aes256-gcm96 \
    exportable=false \
    auto_rotate_period="24h"

# Ротация ключа (создаётся новая версия)
vault write transit/keys/app-encryption/rotate

# Проверка версий
vault read transit/keys/app-encryption
# → Key                  Value
# → ---                  -----
# → type                 aes256-gcm96
# → deletion_allowed     false
# → derived              false
# → exportable           false
# → keys                 map[1:1433269787 2:1433289787]
# → min_decryption_version  1
# → min_encryption_version  0
# → name                 app-encryption

# Настройка min_encryption_version для принудительного перехода
vault write transit/keys/app-encryption/config \
    min_encryption_version=2 \
    min_decryption_version=2

# Очистка старых версий (необратимо!)
# min_available_version (singular) — параметр для /trim endpoint
vault write transit/keys/app-encryption/trim min_available_version=2
```

#### Crypto agility rotation (Vault Enterprise)

Смена алгоритма ключа:

```bash
# Создание ключа RSA 2048
vault write transit/keys/my-key type=rsa-2048

# Ротация с сменой алгоритма на RSA 4096
# Используйте /rotate с алгоритмом (Vault 1.11+)
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

# Добавление второго CA-ключа в sshd_config (overlapping period)
# TrustedUserCAKeys /etc/ssh/trusted-user-ca-keys.pub /etc/ssh/trusted-user-ca-keys-v2.pub

# Перезапуск SSH
ansible all -m systemd -a "name=sshd state=restarted"

# После истечения TTL старых сертификатов — удаление старой роли
vault delete ssh/roles/user-role
```

### Сценарий 7: Мониторинг и аудит ротации (SRE)

```bash
# Проверка статуса ротации static role (поле: last_vault_rotation, а не last_rotation)
vault read database/static-roles/myapp-static
# → Key              Value
# → ---              -----
# → last_vault_rotation  2026-09-24T10:00:00Z
# → rotation_period    24h
# → rotation_schedule  <empty>

# Проверка версий KV v2
vault kv metadata get secret/myapp/config

# Автоматическая ротация хранилища шифрования (backend encryption key)
vault write -force sys/rotate
# → Key       Value
# → ---       -----
# → hash      ...
# → time      2026-09-25T10:00:00Z

# Проверка конфигурации авто-ротации
vault read sys/rotate/config
# → Key              Value
# → ---              -----
# → enabled          true
# → interval         4320h
# → max_operations   2000000000

# Мониторинг через audit log (фильтр по операциям ротации)
# Dynamic secrets: запросы к database/* (создание credentials)
jq 'select(.request.path | startswith("database/creds/") or .request.path | startswith("database/rotate"))' /var/log/vault/audit.log

# Transit rotation: запросы к /*/rotate
jq 'select(.request.path | endswith("/rotate") and (.request.path | startswith("transit/")))' /var/log/vault/audit.log

# Обнаружение orphaned rotation entries (Vault Enterprise)
vault read sys/rotation/orphans
# → Key     Value
# → ---     -----
# → orphans [ldap/static-role/mary, ldap/static-role/alice]

# Проверка lease expiration для dynamic secrets
vault list sys/leases/lookup/database/creds
```

### Сценарий 8: Автоматизированная ротация (Vault Enterprise)

Настройка rotation policy для управления retry-поведением:

```bash
# Создание rotation policy с retry settings
vault write sys/policies/rotation/critical-db \
    max_retries_per_cycle=5 \
    max_retry_cycles=3

# Применение policy к конфигурации database connection
vault write database/config/my-postgresql \
    plugin_name=postgresql-database-plugin \
    connection_url="postgresql://{{username}}:{{password}}@10.0.0.1:5432/myapp" \
    username="vault_admin" \
    password="vault_password" \
    rotation_period="24h" \
    rotation_policy_name="critical-db"
```

### Сценарий 9: ACL-политики для ротации (devops)

```hcl
# Политика оператора ротации (администратор)
# Доступ к всем операциям ротации
path "database/roles/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "database/static-roles/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "database/static-creds/*" {
  capabilities = ["read"]
}

# Root credential rotation
path "database/rotate-root/*" {
  capabilities = ["update"]
}

# Static role rotation
path "database/rotate-role/*" {
  capabilities = ["update"]
}

# Transit key management
path "transit/keys/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "transit/keys/*/rotate" {
  capabilities = ["update"]
}

path "transit/keys/*/config" {
  capabilities = ["update"]
}

path "transit/keys/*/trim" {
  capabilities = ["update"]
}

# KV v2 management
path "secret/metadata/*" {
  capabilities = ["read", "update", "delete"]
}

path "secret/data/*" {
  capabilities = ["create", "read", "update", "delete"]
}

# System rotation (backend encryption key)
path "sys/rotate" {
  capabilities = ["update", "sudo"]
}

path "sys/rotate/config" {
  capabilities = ["read", "update", "sudo"]
}

# Orphaned rotation management (Enterprise)
path "sys/rotation/orphans" {
  capabilities = ["read"]
}

# Политика приложения (только чтение и ротация через Vault Agent)
path "database/creds/app-role" {
  capabilities = ["update"]
}
```

```bash
# Применение политики
vault policy write rotation-operator rotation-operator.hcl

# Назначение политики на AppRole
vault write auth/approle/role/app \
    token_policies="app-policy" \
    secret_id_ttl="0" \
    secret_id_num_uses="0"
```

## Операции и команды

### CLI команды ротации

| Команда | Описание | Пример |
| :--- | :--- | :--- |
| `vault write -f database/rotate-root/<name>` | Ротация root credentials | `vault write -f database/rotate-root/my-postgresql` |
| `vault write -f database/rotate-role/<name>` | Ротация static role | `vault write -force database/rotate-role/myapp-static` |
| `vault read database/static-creds/<name>` | Просмотр static credentials | `vault read database/static-creds/myapp-static` |
| `vault write -f sys/rotate` | Ротация backend encryption key | `vault write -force sys/rotate` |
| `vault write transit/keys/<name>/rotate` | Ротация Transit ключа | `vault write -f transit/keys/app-encryption/rotate` |
| `vault write transit/keys/<name>/config` | Настройка auto_rotate_period | `vault write transit/keys/app-encryption/config auto_rotate_period="24h"` |
| `vault write transit/keys/<name>/trim` | Очистка старых версий | `vault write transit/keys/app-encryption/trim min_available_version=2` |
| `vault kv put secret/<path>` | Ротация KV v2 (новая версия) | `vault kv put secret/myapp/config api_key="new_key"` |
| `vault kv get -version=N secret/<path>` | Чтение конкретной версии | `vault kv get -version=2 secret/myapp/config` |
| `vault kv delete secret/<path> -versions=N` | Мягкое удаление версии | `vault kv delete secret/myapp/config -versions=3` |
| `vault kv undelete secret/<path> -versions=N` | Восстановление удалённой версии | `vault kv undelete secret/myapp/config -versions=3` |
| `vault kv destroy secret/<path> -versions=N` | Постоянное удаление версии | `vault kv destroy secret/myapp/config -versions=3` |
| `vault read sys/rotate/config` | Просмотр конфига auto-ротации | `vault read sys/rotate/config` |
| `vault read sys/rotation/orphans` | Просмотр orphaned entries | `vault read sys/rotation/orphans` |

### API эндпоинты ротации

| Метод | Путь | Описание | Требования |
| :--- | :--- | :--- | :--- |
| `POST` | `/sys/rotate` | Ротация backend encryption key | `sudo` |
| `GET/POST` | `/sys/rotate/config` | Конфиг авто-ротации | `sudo` |
| `GET` | `/sys/rotation/orphans` | Список orphaned entries | Enterprise |
| `POST` | `/sys/policies/rotation/:name` | Rotation policy | Enterprise |
| `GET` | `/sys/policies/rotation/:name` | Чтение policy | Enterprise |
| `DELETE` | `/sys/policies/rotation/:name` | Удаление policy | Enterprise |
| `POST` | `/database/rotate-root/:name` | Ротация root credentials | `-f` |
| `POST` | `/database/rotate-role/:name` | Ротация static role | `-f` |
| `GET` | `/database/static-creds/:name` | Static credentials | — |
| `POST` | `/transit/keys/:name/rotate` | Ротация ключа | — |
| `POST` | `/transit/keys/:name/config` | Конфиг ключа | `auto_rotate_period` |
| `POST` | `/transit/keys/:name/trim` | Очистка версий | `min_available_version` |
| `POST` | `/:mount/data/:path` | KV v2 запись (новая версия) | CAS опционален |
| `POST` | `/:mount/delete/:path` | KV v2 soft delete | `versions` |
| `POST` | `/:mount/undelete/:path` | KV v2 undelete | `versions` |
| `PUT` | `/:mount/destroy/:path` | KV v2 destroy | `versions` |

### Параметры конфигурации ротации

| Параметр | Движок | Тип | Минимум | Описание |
| :--- | :--- | :--- | :--- | :--- |
| `rotation_period` | Database (static/config) | duration | 5s (static role) | Интервал ротации для static roles и config |
| `rotation_schedule` | Database (Enterprise) | cron | — | Cron-расписание (UTC с 1.20.5+) |
| `rotation_window` | Database (Enterprise) | duration | 1h | Окно для завершения ротации |
| `rotation_statements` | Database (static) | list | — | SQL-заявления для ротации пароля |
| `auto_rotate_period` | Transit | duration | 1h | Авто-ротация ключа (0 = выключить) |
| `max_operations` | sys/rotate/config | int | 1,000,000 | Лимит encryptions перед ротацией backend key |
| `interval` | sys/rotate/config | duration | 24h | Временной интервал для ротации backend key |
| `max_retries_per_cycle` | sys/policies/rotation | int | — | Максимум retries per cycle (Enterprise) |
| `max_retry_cycles` | sys/policies/rotation | int | — | Максимум retry cycles (Enterprise) |
| `skip_import_rotation` | Database (static role) | bool | — | Skip rotation on creation (Enterprise) |
| `max_versions` | KV v2 config | int | 0 (keep 10) | Максимум версий на ключ |

## Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `vault kv undo: command not found` | Команда `kv undo` не существует в Vault CLI | Использовать `vault kv get -version=N` + `vault kv put` для отката; `vault kv undelete` для восстановления удалённой версии |
| `min_available_versions` — параметр не применяется к `/trim` | Параметр называется `min_available_version` (без `s`) | `vault write transit/keys/<name>/trim min_available_version=2` |
| `last_rotation` не возвращается в ответе | Поле называется `last_vault_rotation`, а не `last_rotation` | `vault read database/static-creds/<name>` — смотрите `last_vault_rotation` |
| `error rotating root credentials: permission denied` | Root rotation требует специальных прав | Проверить ACL: `path "database/rotate-root/*"` с `update` capability; также может потребоваться `sudo` для некоторых БД |
| `rotation_period must be at least 5 seconds` | `rotation_period` меньше минимума | Установить минимум 5s или использовать `rotation_schedule` |
| `rotation_period and rotation_schedule are mutually exclusive` | Оба параметра заданы одновременно | Использовать только один: либо `rotation_period`, либо `rotation_schedule` |
| `rotation_window only valid with rotation_schedule` | `rotation_window` используется с `rotation_period` | `rotation_window` работает только с `rotation_schedule` |
| `transit key rotation: key type does not support rotation` | Импортированный ключ без `allow_rotation=true` | При импорте указывать `allow_rotation=true` |
| `orphaned rotation entry detected` | Ротация превысила лимит retries | 1) Check `sys/rotation/orphans`; 2) Resolve underlying error (network/BД); 3) Re-register rotation manually или через API |
| `kv: soft deleted version cannot be read` | Версия удалена через `kv delete` | Использовать `vault kv undelete -versions=N` для восстановления |
| `transit/trim: min_available_version >= min_decryption_version` | `trim` пытается удалить используемые версии | Снизить `min_available_version` или повысить `min_decryption_version` |
| `static role rotation failed: user already exists` | Конфликт имени пользователя в БД | Использовать `skip_import_rotation=true` при создании роли |
| `database plugin: connection refused during rotation` | БД недоступна во время ротации | Проверить `connection_url`, сеть, credentials; увеличить `rotation_window` |
| `lease not renewable` при dynamic secret rotation | Lease просрочен или не поддерживает renewal | Увеличить `max_ttl`; проверить политику lease в БД |
| `error: invalid rotation schedule` | Cron-выражение некорректно | Использовать стандартный cron формат: `minute hour day month dayofweek` (UTC) |

## Лучшие практики

1. **Динамические секреты предпочтительнее статических:** Настраивайте dynamic roles с коротким TTL (1–4 часа) вместо static roles с частой ротацией.
2. **Короткий TTL:** Настраивайте TTL минимально необходимым (15–60 минут для БД, 1–24 часа для приложений).
3. **Graceful reload:** Приложение должно поддерживать graceful reload при смене пароля.
4. **Root credential rotation:** Всегда ротируйте root credentials после настройки Database Secrets Engine: `vault write -force database/rotate-root/<name>`.
5. **Schedule-based rotation:** Используйте `rotation_schedule` вместо `rotation_period` для предсказуемых окон ротации (например, `0 2 * * SAT`).
6. **Rotation policies (Enterprise):** Настраивайте `max_retries_per_cycle` и `max_retry_cycles` для production сред, чтобы избежать циклов ротации.
7. **Monitoring:** Отслеживайте `last_vault_rotation`, `next_vault_rotation` и `orphaned rotation entries` через audit logs и `sys/rotation/orphans`.
8. **Audit:** Включите audit device для отслеживания всех операций ротации.
9. **Transit auto-rotation:** Используйте `auto_rotate_period` для Transit ключей вместо ручной ротации (минимум 1 час).
10. **KV v2 cleanup:** Настраивайте `max_versions` для ограничения роста хранилища: `vault write secret/config max_versions=20`.
11. **Backend encryption key:** Периодически ротируйте `sys/rotate` (рекомендуемо каждые 6–12 месяцев).
12. **ACL policies:** Ограничьте доступ к `database/rotate-role/*`, `transit/keys/*/rotate`, `sys/rotate` через ACL-политики.
13. **Documentation:** Документируйте политику ротации для каждого типа секретов.

## Ограничения и известные проблемы

- **Static roles:** Требуют, чтобы Vault имел права на обновление пароля в БД.
- **Dynamic secrets:** Создают много пользователей в БД. Убедитесь, что БД выдерживает нагрузку.
- **Graceful reload:** Не все приложения поддерживают graceful reload. Для legacy-систем используйте sidecar-паттерн.
- **Транзакции:** При истечении TTL во время активной транзакции пользователь может быть удалён. Настройте `max_ttl` с запасом.
- **Skip import rotation:** Доступен только в Enterprise и только для некоторых типов БД (Postgres, Oracle).
- **Rotation schedule timezone:** До Vault 1.20.5 расписание интерпретировалось в локальном timezone. Начиная с 1.20.5 — в UTC.
- **Rootless password rotation:** Только для select DB engines (Postgres, Oracle). Требует Enterprise.
- **Audit log volume:** Интенсивная ротация может увеличить объём audit logs. Настройте retention и rotation (см. `audit_log_analysis.md`).
- **KV v2 storage:** При длительном хранении множества версий используйте `max_versions` для ограничения роста.
- **Transit trim:** После `trim` данные, зашифрованные удалёнными версиями, расшифровать невозможно. Делайте backup перед trim.
- **Rotation window:** Минимальное окно — 1 час. Для недоступных БД увеличьте окно или используйте `rotation_period`.
- **Database plugin retry:** Vault не применяет exponential backoff для database plugin rotation. Используйте rotation policies (Enterprise) для управления retry.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и движки секретов.
*   **[Database Secrets Engine](./database_secrets_engine.md)** — автоматическая ротация учетных данных БД.
*   **[Transit Engine — Политики](./transit-encryption-policies.md)** — ротация криптографических ключей.
*   **[SSH Secrets Engine](./ssh_secrets_engine.md)** — ротация SSH-ключей.
*   **[PKI и CA — продвинутые сценарии](./pki_ca_advanced.md)** — ротация сертификатов и CA.
*   **[Zero Trust](../zero_trust.md)** — роль ротации в архитектуре нулевого доверия.
*   **[Антипаттерны управления секретами](../common_antipatterns.md)** — почему статические секреты — антипаттерн.
*   **[Анализ audit логов](./audit_log_analysis.md)** — ротация и retention audit logs.
*   [Automated credential rotation (Vault Enterprise)](https://developer.hashicorp.com/vault/docs/enterprise/automated-credential-rotation/overview)
*   [Rotation policies API](https://developer.hashicorp.com/vault/api-docs/system/policies-rotation)
*   [Database secrets engine API](https://developer.hashicorp.com/vault/api-docs/secret/databases)
*   [Transit secrets engine API](https://developer.hashicorp.com/vault/api-docs/secret/transit)
*   [KV v2 API](https://developer.hashicorp.com/vault/api-docs/secret/kv/kv-v2)