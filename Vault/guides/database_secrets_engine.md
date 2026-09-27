# Database Secrets Engine в Vault

## Определения

**Database Secrets Engine** — движок секретов HashiCorp Vault, который генерирует динамические учетные данные для баз данных (PostgreSQL, MySQL, MongoDB, Oracle, Cassandra и др.). Вместо хранения статических паролей Vault создаёт уникальные логины/пароли на лету с ограниченным сроком жизни (TTL) и автоматически отзывает их по истечении аренды (lease).

**Static Roles (Статические роли)** — роль, привязанная к конкретному существующему пользователю БД. Vault не создаёт нового пользователя, а возвращает пароль для уже существующего. Подходит для legacy-систем, где нельзя создавать новых пользователей.

**Dynamic Roles (Динамические роли)** — роль, при которой Vault создаёт нового пользователя в БД при каждом запросе учетных данных. Пользователь автоматически удаляется по истечении TTL. Подходит для современных приложений с высокой степенью изоляции.

**Connection URL** — строка подключения к БД, которую Vault использует для управления учетными данными. Содержит шаблоны `{{username}}` и `{{password}}`, которые заменяются на сгенерированные значения.

**Creation Statements** — SQL-запрос (или набор команд), который Vault выполняет в БД для создания нового пользователя при использовании dynamic role. Запрос должен создавать пользователя с ограниченным сроком жизни.

**Revocation Statements** — SQL-запрос для удаления пользователя при отзыве lease или истечении TTL.

**Rotation** — процесс автоматического обновления пароля статического пользователя без изменения имени пользователя. Vault периодически генерирует новый пароль и обновляет его в БД.

## Основные концепции

### Типы ролей

| Тип роли | Создание пользователя | Use case |
| :--- | :--- | :--- |
| **Dynamic** | Vault создаёт нового пользователя на каждую выдачу | Современные приложения, микросервисы, высокий уровень изоляции |
| **Static** | Vault управляет паролем существующего пользователя | Legacy-системы, приложения с жёстко заданными именами пользователей |

### Жизненный цикл динамических учетных данных

1. **Запрос:** Приложение запрашивает учетные данные: `vault read database/creds/my-role`
2. **Создание:** Vault создаёт нового пользователя в БД через `creation_statements`
3. **Выдача:** Vault возвращает `username`, `password`, `lease_id`, `lease_duration`
4. **Использование:** Приложение подключается к БД с полученными учетными данными
5. **Продление:** Приложение может продлить lease (если настроено)
6. **Отзыв:** По истечении TTL Vault автоматически удаляет пользователя через `revocation_statements`
7. **Каскадный отзыв:** При отзыве parent-токена отзываются все дочерние lease

### Поддерживаемые СУБД

| СУБД | Плагин | Особенности |
| :--- | :--- | :--- |
| **PostgreSQL** | `postgresql-database-plugin` | Наиболее распространённый, поддерживает dynamic/static roles |
| **MySQL** | `mysql-database-plugin` | Поддерживает dynamic/static roles, connection pooling |
| **MongoDB** | `mongodb-database-plugin` | Динамические учетные данные для аутентификации MongoDB |
| **Oracle** | `oracle-database-plugin` | Enterprise-функции, плагин доступен в Enterprise версии |
| **Cassandra** | `cassandra-database-plugin` | Динамические учетные данные для Cassandra |
| **Redis** | `redis-database-plugin` | Поддерживается через плагин сообщества |
| **RabbitMQ** | `rabbitmq-database-plugin` | Встроенный плагин для RabbitMQ |
| **Elasticsearch** | `elasticsearch-database-plugin` | Динамические учетные данные для ES |

### Требования к БД

Для работы dynamic roles Vault должен иметь учетную запись с правами на:
- Создание пользователей (`CREATE USER`)
- Удаление пользователей (`DROP USER`)
- Выдача прав (`GRANT`)

Пример для PostgreSQL:

```sql
-- Создание учетной записи Vault
CREATE USER vault_admin WITH PASSWORD 'vault_password';
GRANT CREATE, DROP ON SCHEMA public TO vault_admin;
```

## Практические сценарии

### Сценарий 1: Настройка PostgreSQL (dynamic role)

#### Шаг 1: Включение Database Secrets Engine

```bash
vault secrets enable database
```

#### Шаг 2: Настройка подключения к PostgreSQL

```bash
vault write database/config/my-postgresql \
    plugin_name=postgresql-database-plugin \
    allowed_roles="app-role,readonly-role" \
    connection_url="postgresql://{{username}}:{{password}}@10.0.0.1:5432/myapp?sslmode=require" \
    username="vault_admin" \
    password="vault_admin_password"
```

Параметры:
- `plugin_name` — плагин для СУБД
- `allowed_roles` — роли, которые могут использовать это подключение
- `connection_url` — шаблон подключения с `{{username}}` и `{{password}}`
- `username` / `password` — учетные данные Vault для подключения к БД

#### Шаг 3: Создание dynamic role

```bash
vault write database/roles/app-role \
    db_name=my-postgresql \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO \"{{name}}\"; GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO \"{{name}}\";" \
    default_ttl="1h" \
    max_ttl="24h" \
    revocation_statements="DROP ROLE IF EXISTS \"{{name}}\";"
```

Параметры:
- `db_name` — имя конфигурации подключения
- `creation_statements` — SQL для создания пользователя
- `default_ttl` — срок жизни по умолчанию
- `max_ttl` — максимальный срок жизни
- `revocation_statements` — SQL для удаления пользователя

#### Шаг 4: Получение учетных данных

```bash
vault read database/creds/app-role
# → Key             Value
# → lease_id        database/creds/app-role/abc123...
# → lease_duration  3600
# → password        XyZ7kL9pQ2
# → username        v-token-app-role-8f3a2c
```

#### Шаг 5: Автоматическое продление (Vault Agent)

```hcl
# agent-config.hcl
template {
  destination = "/app/secrets/db-config.yaml"
  contents    = <<-EOH
    {{- with secret "database/creds/app-role" -}}
    DB_HOST=10.0.0.1
    DB_PORT=5432
    DB_USER={{ .Data.data.username }}
    DB_PASSWORD={{ .Data.data.password }}
    LEASE_DURATION={{ .LeaseData.lease_duration }}
    {{- end -}}
  EOH
  command = ["sh", "-c", "kill -HUP $(pgrep -f my-app)"]
  wait {
    min = "2s"
    max = "10s"
  }
}
```

### Сценарий 2: Static role (управление паролем существующего пользователя)

Для систем, где нельзя создавать новых пользователей:

```bash
# Создание static role
vault write database/static-roles/myapp-static \
    db_name=my-postgresql \
    username="myapp_user" \
    rotation_period="24h"
```

Vault будет автоматически ротировать пароль пользователя `myapp_user` каждые 24 часа. Приложение получает текущий пароль через:

```bash
vault read database/static-creds/myapp-static
# → username        myapp_user
# → password        XyZ7kLL9pQ2
# → last_rotation   2026-09-20T12:00:00Z
```

### Сценарий 3: Настройка MySQL

```bash
vault write database/config/my-mysql \
    plugin_name=mysql-database-plugin \
    allowed_roles="app-role" \
    connection_url="mysql://{{username}}:{{password}}@10.0.0.2:3306/myapp" \
    username="vault_admin" \
    password="vault_password"

vault write database/roles/app-role \
    db_name=my-mysql \
    creation_statements="CREATE USER '{{name}}'@'%' IDENTIFIED BY '{{password}}'; GRANT SELECT, INSERT, UPDATE, DELETE ON myapp.* TO '{{name}}'@'%';" \
    default_ttl="1h" \
    max_ttl="24h" \
    revocation_statements="DROP USER '{{name}}'@'%';"
```

### Сценарий 4: Настройка MongoDB

```bash
vault write database/config/my-mongodb \
    plugin_name=mongodb-database-plugin \
    allowed_roles="app-role" \
    connection_url="mongodb://{{username}}:{{password}}@10.0.0.3:27017/myapp" \
    username="vault_admin" \
    password="vault_password"

vault write database/roles/app-role \
    db_name=my-mongodb \
    creation_statements="{ \"db\": \"admin\", \"roles\": [{ \"role\": \"readWrite\", \"db\": \"myapp\" }] }" \
    default_ttl="1h" \
    max_ttl="24h" \
    revocation_statements="{ \"db\": \"admin\", \"roles\": [{ \"role\": \"readWrite\", \"db\": \"myapp\" }] }"
```

### Сценарий 5: Connection Pooling с PgBouncer

Для production-сред с высоким числом подключений используйте PgBouncer как посредник:

```bash
# Настройка роли с ограничениями
vault write database/roles/app-role \
    db_name=my-postgresql \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO \"{{name}}\";" \
    default_ttl="15m" \
    max_ttl="1h"
```

PgBouncer конфигурация:

```
[databases]
myapp = host=10.0.0.1 port=5432 dbname=myapp pool_mode=transaction

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = md5
auth_file = /etc/pgbouncer/userlist.txt
pool_mode = transaction
max_client_conn = 10000
default_pool_size = 20
reserve_pool_size = 5
```

Приложение получает учетные данные из Vault и подключается через PgBouncer:

```hcl
template {
  destination = "/app/secrets/db-config.yaml"
  contents    = <<-EOH
    {{- with secret "database/creds/app-role" -}}
    DB_HOST=127.0.0.1
    DB_PORT=6432
    DB_POOL_SIZE=20
    DB_USER={{ .Data.data.username }}
    DB_PASSWORD={{ .Data.data.password }}
    LEASE_DURATION={{ .LeaseData.lease_duration }}
    {{- end -}}
  EOH
}
```

### Сценарий 6: Множество баз данных (multi-DB)

```bash
# Конфигурация для продакшен
vault write database/config/prod-postgres \
    plugin_name=postgresql-database-plugin \
    allowed_roles="prod-app-role" \
    connection_url="postgresql://{{username}}:{{password}}@prod-db.example.com:5432/prod" \
    username="vault_admin" \
    password="prod_vault_password"

# Конфигурация для стейджинга
vault write database/config/staging-postgres \
    plugin_name=postgresql-database-plugin \
    allowed_roles="staging-app-role" \
    connection_url="postgresql://{{username}}:{{password}}@staging-db.example.com:5432/staging" \
    username="vault_admin" \
    password="staging_vault_password"

# Роли для разных сред
vault write database/roles/prod-app-role \
    db_name=prod-postgres \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO \"{{name}}\";" \
    default_ttl="1h" \
    max_ttl="24h"

vault write database/roles/staging-app-role \
    db_name=staging-postgres \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; GRANT ALL PRIVILEGES ON SCHEMA public TO \"{{name}}\";" \
    default_ttl="24h" \
    max_ttl="168h"
```

### Сценарий 7: Отзыв и ротация учетных данных

#### Принудительный отзыв lease

```bash
# Просмотр активных lease
vault list database/creds/app-role

# Отзыв конкретного lease
vault lease revoke database/creds/app-role/abc123...

# Каскадный отзыв всех дочерних lease
vault token revoke -mode=orphan <parent_token_accessor>
```

#### Ротация static role

```bash
# Просмотр параметров static role
vault read database/static-roles/myapp-static

# Принудительная ротация пароля
vault write -f database/rotate-role/myapp-static

# Проверка нового пароля
vault read database/static-creds/myapp-static
```

### Сценарий 8: Настройка для Kubernetes

```yaml
# VaultRole для Kubernetes Auth Method
apiVersion: v1
kind: ServiceAccount
metadata:
  name: myapp-sa
  namespace: prod
---
apiVersion: v1
kind: Secret
metadata:
  name: myapp-vault-token
  namespace: prod
  annotations:
    kubernetes.io/service-account.name: myapp-sa
type: kubernetes.io/service-account-token
```

```bash
# Создание роли в Vault
vault write auth/kubernetes/role/myapp-role \
    bound_service_account_names=myapp-sa \
    bound_service_account_namespaces=prod \
    policies=app-policy \
    ttl=1h \
    audience=vault

# Политика
cat > app-policy.hcl <<EOF
path "database/creds/app-role" {
  capabilities = ["read"]
}
EOF
vault policy write app-policy app-policy.hcl
```

Vault Agent Sidecar для динамических учетных данных:

```hcl
template {
  destination = "/vault/secrets/db-config.yaml"
  contents    = <<-EOH
    {{- with secret "database/creds/app-role" -}}
    DB_HOST=prod-db.example.com
    DB_PORT=5432
    DB_USER={{ .Data.data.username }}
    DB_PASSWORD={{ .Data.data.password }}
    LEASE_DURATION={{ .LeaseData.lease_duration }}
    {{- end -}}
  EOH
  command = ["sh", "-c", "kill -HUP $(pgrep -f myapp)"]
}
```

## Лучшие практики

1. **Динамические роли по умолчанию:** Используйте dynamic roles вместо static, если БД поддерживает создание пользователей.
2. **TTL:** Настраивайте TTL минимально необходимым (15–60 минут для приложений, 1–24 часа для CI/CD).
3. **Права пользователя:** Ограничивайте права создаваемых пользователей только необходимыми операциями (`GRANT SELECT, INSERT` вместо `GRANT ALL`).
4. **Connection Pooling:** Используйте PgBouncer или аналоги для управления пулом подключений, так как динамические пользователи создаются и удаляются часто.
5. **Graceful reload:** Приложение должно корректно переподключаться к БД при смене пароля (graceful reload, SIGHUP).
6. **Static roles для legacy:** Если система не поддерживает dynamic users, используйте static roles с коротким `rotation_period`.
7. **Audit:** Включите audit device для отслеживания всех операций выдачи учетных данных.
8. **TLS:** Используйте `sslmode=require` или `sslmode=verify-full` в `connection_url` для шифрования трафика.

## Ограничения и известные проблемы

- **Создание пользователя:** Dynamic roles требуют, чтобы Vault имел права на создание/удаление пользователей в БД. Некоторые managed БД (RDS, Cloud SQL) ограничивают эти права.
- **Количество пользователей:** При высокой нагрузке может создаться большое количество пользователей. Убедитесь, что БД выдерживает это количество.
- **Graceful reload:** Приложение должно уметь переподключаться к БД при смене пароля. Без этого возможны короткие простои.
- **Transaction safety:** При истечении TTL во время активной транзакции пользователь может быть удалён. Настройте `max_ttl` с запасом.
- **Plugin compatibility:** Убедитесь, что используете совместимую версию плагина Database Secrets Engine для вашей СУБД.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и движки секретов.
*   **[Основные концепции Vault](../concepts.md)** — lease, токены, жизненный цикл.
*   **[Аутентификация через AppRole](../vault_auth_approle.md)** — для машинной аутентификации.
*   **[Vault Agent — основы](../guides/vault_agent/basics.md)** — автоматическая аутентификация.
*   **[Zero Trust](../zero_trust.md)** — роль динамических секретов в архитектуре нулевого доверия.
*   [Официальная документация Database Secrets Engine](https://developer.hashicorp.com/vault/docs/secrets/databases)
