# Vault Namespaces — изоляция сред

> **Актуально для:** Vault Enterprise 2.x (latest 2.1.2; ветка 1.12.x+ также поддерживается)

## Определения

**Namespace (Пространство имён)** — логический изолятор внутри одного физического кластера Vault Enterprise, позволяющий разделять среды (dev/staging/prod), команды или проекты. Namespace изолирует политики, секреты, токены и auth-методы.

**Enterprise Namespaces** — функция Vault Enterprise (Secure Multi-Tenancy), доступная с первых версий. В Open Source (OSS) версии namespaces недоступны.

**Root Namespace** — корневое пространство имён (`/`), существующее по умолчанию. Все ресурсы создаются в root namespace, если не указан иной. Только токены в root namespace могут выполнять root-only операции (`sys/init`, `sys/leader`, `sys/license`).

**Child Namespace** — дочернее пространство имён, создаваемое внутри root или другого namespace. Имеет путь-префикс (например, `prod/`, `team-a/`).

**Namespace Isolation** — принцип, при котором ресурсы в одном namespace не видны из другого. Политики, секреты и токены изолированы между namespace.

**Cross-Namespace Access** — доступ к ресурсам из другого namespace. В Vault Enterprise выполняется через заголовок `X-Vault-Namespace` или флаг `-namespace`, либо через fully-qualified пути в политиках.

**Namespace Admin** — роль с правами на управление ресурсами внутри namespace (secret engines, auth methods, policies). Имеет права только внутри своего namespace, если не делегированы права на дочерние namespace.

**Chroot Listener** — listener в конфигурации Vault с параметром `chroot_namespace`, определяющий альтернативный top-level namespace для входящих запросов. Доступен с Vault Enterprise 1.15+. Упрощает работу клиентов: запросы без `X-Vault-Namespace` автоматически маршрутизируются в указанный namespace.

**Namespace API Path** — путь к API endpoint с префиксом namespace. Например, `prod/sys/namespaces/` — управление дочерними namespace изнутри `prod`.

## Основные концепции

### Архитектура Namespaces

Vault Enterprise поддерживает иерархию namespaces:

```
/ (root)
├── prod/
│   ├── team-a/
│   └── team-b/
├── staging/
│   ├── team-a/
│   └── team-b/
└── dev/
```

Namespace функционируют как «Vault внутри Vault»: каждый имеет собственные login-пути, secret engines, auth methods, policies (ACL, EGP, RGP), password policies, identities (entities, groups), токены.

### Изоляция ресурсов

| Ресурс | Изоляция между namespace | Примечание |
| :--- | :--- | :--- |
| **Секреты (KV и другие)** | Да | Каждый namespace имеет собственное KV-хранилище и монтированные secret engines |
| **Политики (ACL/EGP/RGP)** | Да | Политики изолированы; дочерние namespace могут использовать политики родительских |
| **Auth методы** | Да | Каждый namespace имеет собственные auth-методы и конфигурации |
| **Токены** | Да | Токены висят только в своём namespace |
| **Identities (Entities, Groups)** | Да | Изолированы, но дочерние namespace могут ссылаться на entities родителей |
| **Password Policies** | Да | Изолированы |
| **Audit logs** | Нет | Audit логи глобальные, но содержат поле `namespace` в записи |
| **Raft storage** | Нет | Физическое хранилище общее для всех namespace |
| **Root-only API paths** | Нет | Некоторые endpoint доступны только из root namespace (`sys/init`, `sys/leader`, `sys/license`, `sys/health`, `sys/metrics`, `sys/storage`, `sys/storage/raft`, `sys/key-status`, `sys/host-info`) |

### Root-only API paths

Следующие endpoint доступны только из root namespace (не наследуются дочерними namespace):

```
sys/init
sys/license
sys/leader
sys/health
sys/metrics
sys/config/state
sys/host-info
sys/key-status
sys/storage
sys/storage/raft
sys/quotas
sys/config/group-policy-application (добавлен в 1.13+)
```

### Работа с путями

При работе с namespace путь к ресурсу может быть указан двумя способами:

1. **Fully-qualified path** — вставить namespace prefix в путь: `prod/secret/data/myapp/config`
2. **Relative path + X-Vault-Namespace header** — использовать относительный путь с указанием namespace через заголовок или флаг `-namespace`:

```bash
# Способ 1: fully-qualified path
curl -H "X-Vault-Token: $VAULT_TOKEN" https://vault:8200/v1/prod/secret/data/myapp/config

# Способ 2: relative path + header
curl -H "X-Vault-Token: $VAULT_TOKEN" -H "X-Vault-Namespace: prod" https://vault:8200/v1/secret/data/myapp/config

# Способ 3: CLI с -namespace флагом
VAULT_NAMESPACE=prod vault kv get secret/data/myapp/config
```

Эти три запроса эквивалентны.

### Важное правило для политик

Когда **политика создаётся внутри namespace** (через `-namespace=prod`), пути в политике **относительны к этому namespace** — префикс namespace не указывается:

```hcl
# Политика СОЗДАЁТСЯ в namespace prod (vault policy write -namespace=prod ...)
# Поэтому путь начинается с secret/, а не prod/secret/!
path "secret/data/myapp/*" {
  capabilities = ["read", "list"]
}
```

Когда **политика создаётся в root namespace** для управления ресурсами в дочернем namespace, путь включает префикс:

```hcl
# Политика создаётся в root namespace для управления prod/team-a
path "prod/team-a/secret/data/*" {
  capabilities = ["read", "list"]
}
```

## Практические сценарии

### Сценарий 1: Создание namespace с custom metadata

#### Создание корневого namespace

```bash
# Создание namespace "prod" с метаданными
vault namespace create prod/ \
  -custom-metadata=env=production \
  -custom-metadata=team=platform

# → id              a1b2c3d4-e12d-34f5-6789-9876543210ab
# → path            prod/
# → custom_metadata map[env:production team:platform]
```

#### Создание дочернего namespace

```bash
# Создание namespace "team-a" внутри "prod"
vault namespace create prod/team-a/ \
  -custom-metadata=team=team-a

# → id              b2c3d4e5-f23e-45a6-7890-0987654321bc
# → path            prod/team-a/
```

#### Просмотр namespace

```bash
# Список всех namespace с деталями
vault namespace list -detailed
# → Namespace                          ID          Custom Metadata
# → prod/                              a1b2c3d4... map[env:production team:platform]
# → prod/team-a/                       b2c3d4e5... map[team:team-a]

# Информация о конкретном namespace
vault namespace lookup prod/
# → id                  a1b2c3d4-e12d-34f5-6789-9876543210ab
# → path                prod/
# → custom_metadata     map[env:production team:platform]
```

### Сценарий 2: Настройка изолированной среды (production)

```bash
# 1. В root namespace: создать namespace prod
VAULT_NAMESPACE="" vault namespace create prod/
# → path  prod/

# 2. В prod namespace: включить KV v2
vault secrets enable -namespace=prod kv-v2

# 3. В prod namespace: создать политику (относительные пути!)
cat > prod-policy.hcl <<EOF
path "secret/data/myapp/*" {
  capabilities = ["read", "list"]
}
EOF
vault policy write -namespace=prod prod-policy prod-policy.hcl

# 4. В prod namespace: создать AppRole
vault auth enable -namespace=prod approle
vault write -namespace=prod auth/approle/role/myapp-role \
    token_policies="prod-policy" \
    token_ttl="1h" \
    token_max_ttl="24h"
```

### Сценарий 3: Изоляция команд (multitenancy)

```bash
# 1. Создать namespace prod/team-a в root
vault namespace create prod/team-a/

# 2. В prod/team-a: включить KV v2 и создать политику
vault secrets enable -namespace=prod/team-a kv-v2

cat > team-a-policy.hcl <<EOF
path "secret/data/*" {
  capabilities = ["read", "list", "create", "update", "delete"]
}
EOF
vault policy write -namespace=prod/team-a team-a-policy team-a-policy.hcl

# 3. В prod/team-a: включить Kubernetes auth
vault auth enable -namespace=prod/team-a kubernetes
```

### Сценарий 4: Cross-Namespace Access (Enterprise)

Доступ к ресурсам из другого namespace выполняется через заголовок `X-Vault-Namespace` или fully-qualified пути.

#### Через флаг -namespace

```bash
# Доступ к секрету в prod/team-a из root namespace
vault kv get -namespace=prod/team-a secret/data/myapp/config

# Доступ к секрету в prod из prod/team-a (через родительский путь)
vault kv get -namespace=prod secret/data/shared-config
```

#### Через API (curl)

```bash
# Способ 1: fully-qualified path (без заголовка)
curl -H "X-Vault-Token: $VAULT_TOKEN" \
  https://vault:8200/v1/prod/secret/data/myapp/config

# Способ 2: relative path + X-Vault-Namespace header
curl -H "X-Vault-Token: $VAULT_TOKEN" \
  -H "X-Vault-Namespace: prod/team-a" \
  https://vault:8200/v1/secret/data/myapp/config
```

#### Namespace Admin Policy (из root namespace)

Политика в root namespace, предоставляющая администратору права на управление child namespace:

```bash
# Создаём политику в root для управления namespace prod и prod/team-a/*
cat > prod-admin.hcl <<EOF
# Управление namespace в prod
path "prod/sys/namespaces/*" {
  capabilities = ["create", "read", "update", "delete", "list", "sudo"]
}

# Управление политиками в prod
path "prod/sys/policies/acl/*" {
  capabilities = ["create", "read", "update", "delete", "list", "sudo"]
}

# Управление secret engines в prod
path "prod/sys/mounts/*" {
  capabilities = ["create", "read", "update", "delete", "list", "sudo"]
}

# Управление auth методами в prod
path "prod/sys/auth/*" {
  capabilities = ["create", "read", "update", "delete", "list", "sudo"]
}
EOF

# Назначить политику токену (корневому администратору)
vault policy write prod-admin prod-admin.hcl

# Создать токен с этой политикой
vault token create -policy=prod-admin -ttl=720h -display-name="prod-admin"
```

### Сценарий 5: Chroot Listener (Vault Enterprise 1.15+)

Chroot listener позволяет определить альтернативный top-level namespace для listener. Запросы без `X-Vault-Namespace` автоматически маршрутизируются в указанный namespace.

```hcl
# config.hcl — listener с chroot
listener "tcp" {
  address          = "0.0.0.0:8200"
  cluster_address  = ":8203"
  tls_cert_file    = "/path/to/full-chain.pem"
  tls_key_file     = "/path/to/private-key.pem"
  chroot_namespace = "usa-hq"
  role             = "default"
}

telemetry {
  unauthenticated_metrics_access = true
}
```

После перезапуска Vault с этим listener запросы к `https://127.0.0.1:8200/v1/team-1/secret/data/foo` работают с namespace `usa-hq/team-1`, даже без заголовка `X-Vault-Namespace`.

### Сценарий 6: Обновление и удаление namespace

#### Обновление custom metadata

```bash
# Патч: добавить ключ и удалить ключ
vault namespace patch prod/ \
  -custom-metadata=status=active \
  -remove-custom-metadata=team

# → id              a1b2c3d4-...
# → path            prod/
# → custom_metadata  map[env:production status:active]
```

#### Блокировка namespace (API Lock)

```bash
# Заблокировать API для namespace prod
vault namespace lock prod/
# → unlock_key  abcd1234-...

# Разблокировать
vault namespace unlock prod/ -unlock-key=abcd1234-...
```

#### Удаление namespace (необратимо!)

```bash
# ВНИМАНИЕ: удаление namespace удаляет ВСЕ ресурсы внутри него
vault namespace delete prod/team-a/

# Проверить, что удалён
vault namespace lookup prod/team-a/
# → Error: No value found in namespace path
```

### Сценарий 7: Мониторинг и аудит namespace

#### Проверка токенов в namespace

```bash
# Информация о токене в конкретном namespace
vault token lookup -namespace=prod <token>

# Список политик в namespace
vault policy list -namespace=prod
# → default
# → prod-policy

# Список auth методов в namespace
vault auth list -namespace=prod
# → approle/
# → kubernetes/
```

#### Фильтрация audit логов по namespace

Audit логи — глобальные, но каждая запись содержит поле `namespace`. Для фильтрации:

```bash
# Просмотр audit логов только для prod namespace
# Если используется JSON audit format
cat /var/log/vault_audit.log | jq 'select(.type=="request") | select(.request.namespace.path=="prod/") | .request.path'

# Если используется syslog:
journalctl -u vault | grep '"namespace"'
```

## Операции и команды

### CLI команды

| Команда | Описание | Пример |
| :--- | :--- | :--- |
| `vault namespace create` | Создать namespace | `vault namespace create prod/` |
| `vault namespace delete` | Удалить namespace | `vault namespace delete prod/team-a/` |
| `vault namespace list` | Список namespace | `vault namespace list` |
| `vault namespace list -detailed` | Список с деталями | `vault namespace list -detailed` |
| `vault namespace lookup` | Инфо о namespace | `vault namespace lookup prod/` |
| `vault namespace patch` | Обновить metadata | `vault namespace patch prod/ -custom-metadata=env=prod` |
| `vault namespace lock` | Блокировать API | `vault namespace lock prod/` |
| `vault namespace unlock` | Разблокировать API | `vault namespace unlock prod/ -unlock-key=KEY` |

**Флаги для работы с namespace:**

| Флаг | Описание | Пример |
| :--- | :--- | :--- |
| `-namespace=<path>` | Операция в указанном namespace | `vault kv get -namespace=prod secret/data/myapp` |
| `-custom-metadata=k=v` | Добавить метаданные (create/patch) | `vault namespace create prod/ -custom-metadata=env=prod` |
| `-remove-custom-metadata=k` | Удалить ключ метаданных (patch) | `vault namespace patch prod/ -remove-custom-metadata=team` |
| `-detailed` | Расширенный вывод (list) | `vault namespace list -detailed` |
| `-format=json` | JSON для автоматизации | `vault namespace list -format=json` |

### API эндпоинты

Базовый путь: `POST/GET/DELETE /v1/sys/namespaces/:path`

| Метод | Путь | Описание | Параметры |
| :--- | :--- | :--- | :--- |
| `LIST` | `/sys/namespaces` | Список namespace | `-` |
| `POST` | `/sys/namespaces/:path` | Создать namespace | `custom_metadata` (map, Vault 1.12+) |
| `GET` | `/sys/namespaces/:path` | Инфо о namespace | `-` |
| `PATCH` | `/sys/namespaces/:path` | Обновить metadata | `custom_metadata` (map) |
| `DELETE` | `/sys/namespaces/:path` | Удалить namespace | `-` |
| `POST` | `/sys/namespaces/api-lock/lock/:path` | Блокировать API | `-unlock-key` (для unlock) |
| `POST` | `/sys/namespaces/api-lock/unlock/:path` | Разблокировать API | `unlock_key` |

#### Примеры API

```bash
# Список namespace
curl -H "X-Vault-Token: $VAULT_TOKEN" -X LIST https://vault:8200/v1/sys/namespaces
# → ["prod/", "staging/", "dev/"]

# Создание namespace с metadata
curl -H "X-Vault-Token: $VAULT_TOKEN" \
  -X POST \
  -d '{"custom_metadata": {"env": "production", "team": "platform"}}' \
  https://vault:8200/v1/sys/namespaces/prod

# Инфо о namespace
curl -H "X-Vault-Token: $VAULT_TOKEN" \
  https://vault:8200/v1/sys/namespaces/prod
# → {"id": "a1b2c3d4-...", "path": "prod/", "custom_metadata": {"env": "production", "team": "platform"}}

# Операция в конкретном namespace через API
curl -H "X-Vault-Token: $VAULT_TOKEN" \
  -H "X-Vault-Namespace: prod/team-a" \
  https://vault:8200/v1/secret/data/myapp/config
```

### Автоматизация с -format=json

```bash
# Получить ID namespace для использования в скриптах
NS_ID=$(vault namespace lookup prod/ -format=json | jq -r '.id')

# Проверить существование namespace
if vault namespace lookup prod/ -format=json > /dev/null 2>&1; then
  echo "Namespace prod существует"
else
  echo "Ошибка: namespace prod не найден"
fi

# Список всех namespace в JSON для обработки
vault namespace list -detailed -format=json > namespaces.json
```

## Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `no value found in namespace` | Namespace не существует | `vault namespace list` для проверки; создайте namespace `vault namespace create <path>/` |
| `permission denied` | Политика не покрывает путь | Проверьте, что путь в политике **относительен** к namespace, в котором политика создана. Не добавляйте namespace-префикс. |
| `permission denied` при cross-namespace доступе | Нет прав доступа в целевом namespace | Используйте политику из root с fully-qualified путями (`prod/team-a/...`), либо создайте токен в целевом namespace. |
| `path would traverse outside namespace boundary` | Попытка доступа к родительскому namespace | Используйте `X-Vault-Namespace` header или `-namespace` флаг для явного указания target namespace. |
| Токен валиден, но секрет не возвращается | Токен в другом namespace | Проверьте `VAULT_NAMESPACE` env var или `-namespace` флаг. |
| `sudo path required` | Операция требует root-токена | Namespace admin не может выполнять root-only операции (`sys/init`, `sys/leader`, `sys/license`). |
| Audit логи не содержат namespace | Audit device не настроен на JSON | Включите `log_raw` и JSON формат: `vault audit enable file file_path=/var/log/vault_audit.log log_raw=true`. |
| `chroot_namespace` не работает | Vault < 1.15 или не Enterprise | Chroot listener доступен только в Vault Enterprise 1.15+. |

## Лучшие практики

1. **Изоляция сред:** Используйте отдельные namespace для prod, staging, dev.
2. **Изоляция команд:** Для мультитенантных сред создавайте namespace для каждой команды.
3. **Root namespace:** Ограничьте доступ к root namespace. Используйте его только для административных операций.
4. **Политики:** Создавайте отдельные политики для каждого namespace. Избегайте глобальных wildcard-политик. Пути в политиках, созданных внутри namespace, **всегда относительны** к этому namespace.
5. **Метаданные:** Используйте `-custom-metadata` для отслеживания owner, cost-center, environment в больших организациях.
6. **Chroot Listener:** Для больших организаций используйте chroot listener (1.15+) для упрощения доступа к namespace.
7. **Аудит:** Включите audit device для отслеживания операций в namespace. Используйте поле `namespace` в audit логах для фильтрации.
8. **Бэкап:** Регулярно бэкапируйте raft-хранилище. Namespace не защищают от потери данных.
9. **API Lock:** Используйте `vault namespace lock` для временного блокирования namespace при обслуживании или инцидентах.
10. **Cleanup:** Периодически удаляйте неиспользуемые namespace. Удаление namespace удаляет все ресурсы внутри него (secrets, policies, tokens) — это необратимо.
11. **Ограничения:** Большое количество namespace (>100) может снизить производительность.
12. **Миграция:** Перенос ресурсов между namespace не поддерживается автоматически. Требуется ручное копирование секретов и политик с помощью CLI или Terraform.

## Ограничения и известные проблемы

- **Enterprise только:** Namespaces доступны только в Vault Enterprise.
- **Количество namespace:** Ограничено лицензией Enterprise. В HCP Vault Dedicated — определённое количество.
- **Производительность:** Большое количество namespace (>100) может снизить производительность.
- **Миграция:** Перенос ресурсов между namespace не поддерживается. Требуется ручное копирование.
- **Audit logs:** Audit логи глобальные, но содержат поле `namespace` в записи. Используйте его для фильтрации.
- **Root-only paths:** Некоторые системные endpoint доступны только из root namespace и не наследуются дочерними namespace.
- **Миграция путей политик при upgrade:** При переходе с 1.x на 2.x политики с namespace-префиксами, созданные внутри namespace, могут требовать исправления путей (убрать префикс).

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и лицензирование.
*   **[Авторизация в Vault](../authorization.md)** — политики доступа и policy path matching.
*   **[Zero Trust](../zero_trust.md)** — изоляция в архитектуре нулевого доверия.
*   [Официальная документация по namespaces](https://developer.hashicorp.com/vault/docs/enterprise/namespaces)
*   [Namespace Structure и Best Practices](https://developer.hashicorp.com/vault/docs/enterprise/namespaces/namespace-structure)
*   [Best practices for namespaces and mount paths](https://developer.hashicorp.com/vault/docs/v1.19.x/enterprise/namespaces/namespace-structure)