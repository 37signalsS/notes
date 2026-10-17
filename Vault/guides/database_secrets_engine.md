# Database Secrets Engine в Vault

**Актуально для:** Vault 2.x (Database Secrets Engine: поддержка со 0.4; dynamic и static роли — со 1.6; настройка `username_template` — с 1.7+).

## Определения

**Database Secrets Engine** — движок секретов HashiCorp Vault, который генерирует динамические учетные данные для баз данных (PostgreSQL, MySQL, MongoDB, Oracle, Cassandra и др.). Вместо хранения статических паролей Vault создаёт уникальные логины/паролы на лету с ограниченным сроком жизни (TTL) и автоматически отзывает их по истечении аренды (lease).

**Dynamic Roles (Динамические роли)** — роль, при которой Vault создаёт нового пользователя в БД при каждом запросе учетных данных. Пользователь автоматически удаляется по истечении TTL. Подходит для современных приложений с высокой степенью изоляции.

**Static Roles (Статические роли)** — роль, привязанная к конкретному существующему пользователю БД. Vault не создаёт нового пользователя, а периодически ротирует пароль для уже существующего. Подходит для legacy-систем, где нельзя создавать новых пользователей. Как и для dynamic, пароль хранится в виде lease и отзывается по истечении TTL.

**Connection URL** — строка подключения к БД, которую Vault использует для управления учетными данными. Содержит шаблоны `{{username}}` и `{{password}}`, которые заменяются на сгенерированные значения.

**Creation Statements** — SQL-запрос (или набор команд), который Vault выполняет в БД для создания нового пользователя при использовании dynamic role.

**Revocation Statements** — SQL-запрос для удаления пользователя при отзыве lease или истечении TTL. Не все плагины требуют явного `revocation_statements` — многие удаляют пользователя автоматически.

**Rotation** — процесс автоматического обновления пароля статического или root-пользователя. Для static ролей — через `rotation_period`/`rotation_schedule`; для root-учётных данных конфигурации — через `database/rotate-root/:name`.

**Username Template** — шаблон (`username_template`), управляющий именем создаваемого Vault пользователем (например, префикс `v-`). Доступно, начиная с 1.7+ для большинства плагинов.

**Root Credential Rotation** — ротация учётных данных конфигурации (root-пользователя), которыми Vault подключается к БД для управления пользователями. Выполняется командой `vault write -f database/rotate-root/<config-name>`.

## Основные концепции

### Требования

Операторские требования:

- Vault 1.6+ (рекомендуется 2.x); database secrets engine включён: `vault secrets enable database`.
- Токен с правами на `database/config/*`, `database/roles/*`, `database/static-roles/*`, `database/creds/*`, `database/static-creds/*`, `database/rotate-root/*`, `database/rotate-role/*` и `sys/leases/*`.
- **Рекомендуется** включить audit device для трассировки выдачи и отзыва учётных данных (см. `audit_log_analysis.md`).

Для работы dynamic roles Vault должен иметь учётную запись с правами на:

- Создание пользователей (`CREATE USER`)
- Удаление пользователей (`DROP USER`)
- Выдачу прав (`GRANT`)

Пример для PostgreSQL:

```sql
-- Создание учетной записи Vault
CREATE USER vault_admin WITH PASSWORD 'vault_password';
GRANT CREATE, DROP ON SCHEMA public TO vault_admin;
```

> **Важно:** используйте выделенного пользователя для Vault — никогда не привязывайте static role к root-учётным данным конфигурации. После настройки обязательно выполните ротацию root-пароля (см. сценарий 1, шаг 3).

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
5. **Продление:** Приложение может продлить lease (если `lease_renewable = true`)
6. **Отзыв:** По истечении TTL Vault автоматически удаляет пользователя через `revocation_statements` (или автоматически, если плагин удаляет пользователей)
7. **Каскадный отзыв:** При отзыве parent-токена отзываются все дочерние lease

### Поддерживаемые СУБД

Таблица основана на вероятностях, опубликованных в [официальной документации](https://developer.hashicorp.com/vault/docs/secrets/databases). Ряд плагинов помечен `ENT` — требует лицензии Vault Enterprise или отдельной установки (custom plugin). Управляемые (cloud) сервисы БД (Redshift, Snowflake, Redis ElastiCache, MongoDB Atlas) здесь не рассматриваются.

| СУБД | Плагин | Root rotation | Dynamic | Static | Username templating | Особенности |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **PostgreSQL** | `postgresql-database-plugin` | Да | Да | Да | Да (1.7+) | Наиболее распространённый; поддержка x509-аутентификации; `gcp_iam` |
| **MySQL / MariaDB** | `mysql-database-plugin` | Да | Да | Да | Да (1.7+) | connection pooling; `disable_escaping` для спецсимволов |
| **MongoDB** | `mongodb-database-plugin` | Да | Да | Да | Да (1.7+) | `creation_statements` — JSON ACL; revocation выполняется плагином автоматически |
| **Cassandra** | `cassandra-database-plugin` | Да | Да | Да (1.6+) | Да (1.7+) | Требует `GRANT CREATE/ALTER/DROP/AUTHORIZE ON ALL ROLES`; deprecated SHA-1 X.509 с 1.12 |
| **MSSQL** | `mssql-database-plugin` | Да | Да | Да | Да (1.7+) | ADO-формат `connection_url`; `disable_escaping` для `#` и `%` |
| **Oracle** | `vault-plugin-database-oracle` | Да | Да | Да | Да (1.7+) | **ENT** — отдельный плагин (не в core OSS), требует Oracle Instant Client; поддержка `rootless DB connection` |
| **Elasticsearch** | `elasticsearch-database-plugin` | Да (1.6+) | Да | Да | Да (1.8+) | Через native X-Pack Security |
| **Redis** | `redis-database-plugin` | Да | Да | Да | Нет | `creation_statements` — JSON ACL (`["+@admin"]` или `["~*", "+@read"]`); подстановки в `allowed_roles` (например `my-*-role`) |

> **RabbitMQ:** отдельный secrets engine `rabbitmq` (`vault secrets enable rabbitmq`), **не** database plugin.

#### Требования к отдельным СУБД

**Cassandra** — учётной записи Vault назначаются права:

```sql
GRANT CREATE ON ALL ROLES to '<YOUR USER>';
GRANT ALTER ON ALL ROLES to '<YOUR USER>';
GRANT DROP ON ALL ROLES to '<YOUR USER>';
GRANT AUTHORIZE ON ALL ROLES to '<YOUR USER>';
```

**Redis** — роль по умолчанию (без `creation_statements`) создаёт read-only пользователя с ACL `["~*", "+@read"]`.

#### Дополнительные возможности конфигурации

Эти параметры доступны большинству плагинов (см. [API](https://developer.hashicorp.com/vault/api-docs/secret/databases)):

- **Root Credential Rotation:** после настройки конфигурации всегда ротируйте root-пароль — `vault write -f database/rotate-root/<name>`. Большинство плагинов поддерживают плановую ротацию через `rotation_schedule` (cron) + `rotation_window`. Доступна и ручная ротация через API.
- **Password Policies:** пароли генерируются через [политики паролей Vault](https://developer.hashicorp.com/vault/docs/concepts/password-policies). По умолчанию — 20 символов (1 upper, 1 lower, 1 digit, 1 dash). Политику можно задавать на уровне конфигурации (`password_policy`) или роли.
- **`disable_escaping` (Vault 1.10+):** отключает экранирование `#`/`%` в `connection_url`/`username`/`password` — необходимо для ADO-строк MSSQL и паролей с URL-символами.
- **Пул соединений:** `max_open_connections` (по умолчанию 4), `max_idle_connections` (0), `max_connection_lifetime` — ограничивают нагрузку на СУБД.
- **Static role onboarding:** по умолчанию при создании static role Vault сразу ротирует пароль. Отключить можно: `skip_import_rotation=true` (на роль) или `skip_static_role_import_rotation=true` (на конфигурацию). `rotation_period` и `rotation_schedule` взаимно исключаются — задайте один.

## Практические сценарии

### Сценарий 1: Настройка PostgreSQL (dynamic role)

#### Шаг 1: Включение Database Secrets Engine

```bash
vault secrets enable database
# → Success! Enabled the database secrets engine at: database/
```

#### Шаг 2: Настройка подключения к PostgreSQL

```bash
vault write database/config/my-postgresql \
    plugin_name=postgresql-database-plugin \
    allowed_roles="app-role,readonly-role" \
    connection_url="postgresql://{{username}}:{{password}}@10.0.0.1:5432/myapp?sslmode=require" \
    username="vault_admin" \
    password="vault_admin_password"
# → Success! Data written to: database/config/my-postgresql
```

Параметры:

- `plugin_name` — плагин для СУБД
- `allowed_roles` — роли, которые могут использовать это подключение
- `connection_url` — шаблон подключения с `{{username}}` и `{{password}}`
- `username` / `password` — учетные данные Vault для подключения к БД

#### Шаг 3: Ротация root-учётных данных конфигурации

```bash
vault write -f database/rotate-root/my-postgresql
# → Success! Data written to: database/rotate-root/my-postgresql
```

После этой команды исходный `vault_admin_password` больше недоступен — только Vault знает текущий пароль.

#### Шаг 4: Создание dynamic role

```bash
vault write database/roles/app-role \
    db_name=my-postgresql \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO \"{{name}}\"; GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO \"{{name}}\";" \
    default_ttl="1h" \
    max_ttl="24h" \
    revocation_statements="DROP ROLE IF EXISTS \"{{name}}\";"
# → Success! Data written to: database/roles/app-role
```

Параметры:

- `db_name` — имя конфигурации подключения
- `creation_statements` — SQL для создания пользователя
- `default_ttl` — срок жизни по умолчанию
- `max_ttl` — максимальный срок жизни
- `revocation_statements` — SQL для удаления пользователя

#### Шаг 5: Получение учетных credentials

```bash
vault read database/creds/app-role
# → Key             Value
# → lease_id        database/creds/app-role/abc123...
# → lease_duration  3600
# → lease_renewable true
# → password        XyZ7kL9pQ2
# → username        v-token-app-role-8f3a2c
```

#### Шаг 6: Автоматическое продление (Vault Agent)

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
vault write database/static-roles/myapp-static \
    db_name=my-postgresql \
    username="myapp_user" \
    rotation_period="24h"
```

Vault будет автоматически ротировать пароль пользователя `myapp_user` каждые 24 часа. Плановая ротация по расписанию задаётся через `rotation_schedule` (cron) вместо `rotation_period` — параметры взаимно исключаются:

```bash
vault write database/static-roles/myapp-static \
    db_name=my-postgresql \
    username="myapp_user" \
    rotation_schedule="0 2 * * *" \
    rotation_window="1h"
```

Приложение получает текущий пароль через:

```bash
vault read database/static-creds/myapp-static
# → Key                    Value
# → last_vault_rotation    2026-09-20T12:00:00Z
# → lease_duration         86400
# → lease_renewable         true
# → password                XyZ7kLL9pQ2
# → username                myapp_user
```

### Сценарий 3: Настройка MySQL

```bash
vault write database/config/my-mysql \
    plugin_name=mysql-database-plugin \
    allowed_roles="app-role" \
    connection_url="mysql://{{username}}:{{password}}@10.0.0.2:3306/myapp" \
    username="vault_admin" \
    password="vault_password"
# → Success! Data written to: database/config/my-mysql

vault write database/roles/app-role \
    db_name=my-mysql \
    creation_statements="CREATE USER '{{name}}'@'%' IDENTIFIED BY '{{password}}'; GRANT SELECT, INSERT, UPDATE, DELETE ON myapp.* TO '{{name}}'@'%';" \
    default_ttl="1h" \
    max_ttl="24h" \
    revocation_statements="DROP USER '{{name}}'@'%';"
# → Success! Data written to: database/roles/app-role
```

### Сценарий 4: Настройка MongoDB

```bash
vault write database/config/my-mongodb \
    plugin_name=mongodb-database-plugin \
    allowed_roles="app-role" \
    connection_url="mongodb://{{username}}:{{password}}@10.0.0.3:27017/myapp" \
    username="vault_admin" \
    password="vault_password"
# → Success! Data written to: database/config/my-mongodb

vault write database/roles/app-role \
    db_name=my-mongodb \
    creation_statements='{ "db": "admin", "roles": [{ "role": "readWrite", "db": "myapp" }] }' \
    default_ttl="1h" \
    max_ttl="24h"
# → Success! Data written to: database/roles/app-role
```

> **Примечание:** `creation_statements` для MongoDB — это JSON-объект с `db` и массивом `roles` (ключи `role`/`db`). Отзыв пользователя (`revocation`) выполняется плагином автоматически — явный `revocation_statements` обычно не нужен.

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
    connection_url="postgresql://{{username}}:{{password}}@prod-db.example.com:5432/prod?sslmode=require" \
    username="vault_admin" \
    password="prod_vault_password"
# → Success! Data written to: database/config/prod-postgres

# Конфигурация для стейджинга
vault write database/config/staging-postgres \
    plugin_name=postgresql-database-plugin \
    allowed_roles="staging-app-role" \
    connection_url="postgresql://{{username}}:{{password}}@staging-db.example.com:5432/staging?sslmode=require" \
    username="vault_admin" \
    password="staging_vault_password"
# → Success! Data written to: database/config/staging-postgres

# Ротация root-паролей после настройки
vault write -f database/rotate-root/prod-postgres
vault write -f database/rotate-root/staging-postgres

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

### Сценарий 7: Отзыв и ротация учетных credentials

#### Просмотр и принудительный отзыв lease

```bash
# Просмотр активных lease (список lease_id по префиксу database/)
vault list sys/leases/lookup/database
# → Keys
# → database/creds/app-role/abc123...

# Отзыв конкретного lease
vault lease revoke database/creds/app-role/abc123...
# → Revoke successful (or queued)

# Отзыв всех lease роли по префиксу
vault lease revoke -prefix database/creds/app-role
```

> `vault list database/creds/<role>` **не** выводит список lease — он генерирует новые credentials. Для управления lease используйте `sys/leases`.

#### Ротация static role

```bash
# Просмотр параметров static role
vault read database/static-roles/myapp-static

# Принудительная ротация пароля
vault write -f database/rotate-role/myapp-static
# → Success! Data written to: database/rotate-role/myapp-static

# Проверка нового пароля
vault read database/static-creds/myapp-static
# → username        myapp_user
#   password        <будет изменён>
#   last_vault_rotation  <новое время>
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
# → Success! Data written to: auth/kubernetes/role/myapp-role

# Политика
cat > app-policy.hcl <<EOF
path "database/creds/app-role" {
  capabilities = ["read"]
}
EOF
vault policy write app-policy app-policy.hcl
# → Policy "app-policy" written to Vault.
```

Vault Agent Sidecar для динамических учетных credentials:

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

> **Примечание:** пример использует устаревший тип Secret `kubernetes.io/service-account-token`. Для новых кластеров (Kubernetes 1.24+) отдавайте предпочтение token-проекции через [Vault Kubernetes integration](./vault_kubernetes_integration.md).

## Операции и команды

| Операция | CLI | API | Назначение |
| :--- | :--- | :--- | :--- |
| Включить движок | `vault secrets enable database` | `POST /sys/mounts` | Включить database secrets engine |
| Конфигурация подключения | `vault write database/config/<name>` | `POST /database/config/:name` | Настройка подключения к СУБД |
| Dynamic role | `vault write database/roles/<role>` | `POST /database/roles/:name` | Шаблон создания/удаления пользователя |
| Static role | `vault write database/static-roles/<role>` | `POST /database/static-roles/:name` | Управление паролем существующего пользователя |
| Выдача dynamic creds | `vault read database/creds/<role>` | `GET /database/creds/:name` | Сгенерировать временные учётные данные |
| Выдача static creds | `vault read database/static-creds/<role>` | `GET /database/static-creds/:name` | Текущий пароль static-пользователя |
| Ротация root | `vault write -f database/rotate-root/<name>` | `POST /database/rotate-root/:name` | Сменить root-пароль конфигурации |
| Ротация static role | `vault write -f database/rotate-role/<role>` | `POST /database/rotate-role/:name` | Принудительная ротация пароля static-роли |
| Просмотр конфигурации | `vault read database/config/<name>` | `GET /database/config/:name` | Прочитать конфиг (пароль маскируется) |
| Управление lease | `vault lease revoke [-prefix] <path>` | `POST /sys/leases/revoke/:prefix` | Отзыв lease'ей |

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `role "…" not found` при `vault read database/creds/<role>` | Роль не создана или `allowed_roles` конфигурации не включает роль | `vault read database/config/<db> \| grep allowed_roles`; добавьте роль в `allowed_roles` |
| `permission denied` / `CREATE ROLE` failed | Учётная запись Vault (`/database/config/<name>` username) не имеет прав CREATE/ALTER/DROP USER | Предоставьте DDL-права DB-администратору; проверьте `audit`-логи |
| credentials сгенерированы, но приложение не подключается | `connection_url` с `disable_escaping` (спецсимволы `#`/`%`), неверный `sslmode`/хост, файрвол | `vault read database/config/<name>` (пароль скрыт); проверьте сеть и TLS |
| Lease просрочен, но пользователь остался в БД | `revocation_statements` пуст/неверен, либо плагин не отозвал | `vault lease revoke -prefix database/creds/<role>`; добавьте явный `revocation_statements` |
| Static role не ротируется | `rotation_period`/`rotation_schedule` не заданы, или `disable_automated_rotation=true` | `vault read database/static-roles/<role>`; задайте `rotation_period` или `rotation_schedule`; сбросьте `disable_automated_rotation` |
| Root-пароль "потерян" после `rotate-root` | Это ожидаемо — `rotate-root` сменяет пароль и больше не возвращает его | Только Vault знает текущий root-пароль; для смены конфигурации используйте новый токен DB |
| Пользователь удаляется во время активной транзакции | `max_ttl` слишком короток | Установите `max_ttl` с запасом; приложение должно продлять lease (`lease_renewable=true`) и graceful-reload |

Диагностические команды:

```bash
vault read database/config/<name>           # конфиг подключения (пароль маскируется)
vault read database/roles/<role>            # dynamic role
vault read database/static-roles/<role>     # static role
vault list sys/leases/lookup/database       # все активные lease
vault write -f database/rotate-root/<name>  # ручная ротация root
vault write -f database/rotate-role/<role>  # ручная ротация static role
vault lease renew <lease_id>                # продление lease
vault lease revoke -prefix database/creds/<role>   # массовый отзыв
```

## Лучшие практики

1. **Динамические роли по умолчанию:** Используйте dynamic roles вместо static, если БД поддерживает создание пользователей.
2. **TTL:** Настраивайте TTL минимально необходимым (15–60 минут для приложений, 1–24 часа для CI/CD).
3. **Права пользователя:** Ограничивайте права создаваемых пользователей только необходимыми операциями (`GRANT SELECT, INSERT` вместо `GRANT ALL`).
4. **Connection Pooling:** Используйте PgBouncer или аналоги для управления пулом подключений, так как динамические пользователи создаются и удаляются часто.
5. **Graceful reload:** Приложение должно корректно переподключаться к БД при смене пароля (graceful reload, SIGHUP).
6. **Static roles для legacy:** Если система не поддерживает dynamic users, используйте static roles с коротким `rotation_period` или `rotation_schedule`.
7. **Root rotation:** После настройки конфигурации всегда выполняйте `vault write -f database/rotate-root/<name>`, чтобы исходный root-пароль стал недоступным. Никогда не привязывайте static role к root-учётным данным.
8. **Password policy:** Задавайте собственную политику паролей (`password_policy` на конфигурации/роли), чтобы соответствовать требованиям DB к сложности.
9. **Audit:** Включите audit device для отслеживания всех операций выдачи и отзыва учётных credentials.
10. **TLS:** Используйте `sslmode=require`/`verify-full` (PostgreSQL) или `tls=true` (MongoDB/Redis) в `connection_url` и `disable_escaping=true` при наличии URL-спецсимволов в пароле.
11. **Префиксы ролей:** Ограничивайте `allowed_roles` наименьшим необходимым набором и используйте wildcard-префиксы (например `app-*-role`) вместо `*`.

## Ограничения

- **Создание пользователя:** Dynamic roles требуют, чтобы Vault имел права на создание/удаление пользователей в БД. Некоторые управляемые или ограниченно-привилегированные СУБД ограничивают DDL-права (`CREATE`/`ALTER`/`DROP USER`) — убедитесь, что учётная запись имеет необходимые привилегии.
- **Количество пользователей:** При высокой нагрузке может создаться большое количество пользователей. Убедитесь, что БД выдерживает это количество; используйте `max_open_connections` для ограничения пула и PgBouncer.
- **Graceful reload:** Приложение должно уметь переподключаться к БД при смене пароля. Без этого возможны короткие простои.
- **Transaction safety:** При истечении TTL во время активной транзакции пользователь может быть удалён. Настройте `max_ttl` с запасом.
- **Oracle:** отдельный плагин (не входит в core OSS), требует лицензии Vault Enterprise и Oracle Instant Client; несовместим с Alpine Linux (требует glibc).
- **RabbitMQ:** управляется отдельным secrets engine `rabbitmq`, а не database plugin.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и движки секретов.
*   **[Основные концепции Vault](../concepts.md)** — lease, токены, жизненный цикл.
*   **[Аутентификация через AppRole](../vault_auth_approle.md)** — для машинной аутентификации.
*   **[Vault Agent — основы](../guides/vault_agent/basics.md)** — автоматическая аутентификация.
*   **[Ротация секретов в Vault](./secret_rotation.md)** — root- и static-ротация.
*   **[Аудит и анализ логов](./audit_log_analysis.md)** — аудит выдачи учётных credentials.
*   **[Zero trust](../zero_trust.md)** — роль динамических секретов в архитектуре нулевого доверия.
*   [Официальная документация Database Secrets Engine](https://developer.hashicorp.com/vault/docs/secrets/databases)
*   [Database Secrets Engine HTTP API](https://developer.hashicorp.com/vault/api-docs/secret/databases)
*   [Manage dynamic credential leases (tutorial)](https://developer.hashicorp.com/vault/tutorials/db-credentials/manage-dynamic-leases)
*   [Password Policies](https://developer.hashicorp.com/vault/docs/concepts/password-policies)
