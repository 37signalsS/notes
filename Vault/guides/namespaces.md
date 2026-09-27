# Vault Namespaces — изоляция сред

## Определения

**Namespace (Пространство имён)** — логический изолятор внутри одного физического кластера Vault Enterprise, позволяющий разделять среды (dev/staging/prod), команды или проекты. Namespace изолирует политики, секреты, токены и auth-методы.

**Enterprise Namespaces** — функция Vault Enterprise, предоставляющая изоляцию на уровне кластера. В Open Source (OSS) версии namespaces недоступны.

**Root Namespace** — корневое пространство имён (`/`), существующее по умолчанию. Все ресурсы создаются в root namespace, если не указан иной.

**Child Namespace** — дочернее пространство имён, создаваемое внутри root или другого namespace. Имеет префикс в пути (например, `prod/`, `team-a/`).

**Namespace Isolation** — принцип, при котором ресурсы в одном namespace не видны из другого. Политики, секреты и токены изолированы между namespace.

**Cross-Namespace Access** — доступ к ресурсам из другого namespace. В Vault Enterprise возможен через явное указание namespace в пути или через алиасы.

**Namespace Admin** — роль администратора namespace с правами на управление ресурсами внутри namespace. Имеет права только внутри своего namespace.

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

### Изоляция ресурсов

| Ресурс | Изоляция между namespace |
| :--- | :--- |
| **Секреты (KV)** | Да, каждый namespace имеет собственное KV-хранилище |
| **Политики** | Да, политики изолированы между namespace |
| **Auth методы** | Да, auth-методы изолированы |
| **Токены** | Да, токены висят только в своём namespace |
| **Audit logs** | Нет, audit логи глобальные (но содержат namespace в записи) |
| **Рaft storage** | Нет, физическое хранилище общее |

### Префиксы путей

При работе с namespace путь к ресурсу включает префикс namespace:

```
# Root namespace
secret/data/myapp/config

# prod namespace
prod/secret/data/myapp/config

# team-a внутри prod
prod/team-a/secret/data/myapp/config
```

## Практические сценарии

### Сценарий 1: Создание namespace

#### Создание корневого namespace

```bash
# Создание namespace "prod"
vault namespace create prod
# → Key             Value
# → namespace_path  prod/
# → namespace_id    a1b2c3d4-...

# Создание namespace "staging"
vault namespace create staging
```

#### Создание дочернего namespace

```bash
# Создание namespace "team-a" внутри "prod"
vault namespace create -namespace=prod team-a
# → namespace_path  prod/team-a/
```

#### Просмотр namespace

```bash
# Список namespace
vault namespace list
# → Namespace
# → prod/
# → staging/
# → dev/

# Информация о namespace
vault namespace lookup prod
# → namespace_path  prod/
# → namespace_id    a1b2c3d4-...
# → created_time    2026-09-24T10:00:00Z
```

### Сценарий 2: Настройка изолированных сред

#### Создание namespace для production

```bash
# Создание namespace
vault namespace create prod

# Включение KV v2 в namespace
vault secrets enable -namespace=prod kv-v2

# Создание политики для production
cat > prod-policy.hcl <<EOF
path "prod/secret/data/myapp/*" {
  capabilities = ["read", "list"]
}
EOF
vault policy write -namespace=prod prod-policy prod-policy.hcl

# Создание AppRole для production
vault auth enable -namespace=prod approle
vault write -namespace=prod auth/approle/role/myapp-role \
    token_policies="prod-policy" \
    token_ttl="1h" \
    token_max_ttl="24h"
```

#### Создание namespace для staging

```bash
# Создание namespace
vault namespace create staging

# Включение KV v2 в namespace
vault secrets enable -namespace=staging kv-v2

# Создание политики для staging
cat > staging-policy.hcl <<EOF
path "staging/secret/data/myapp/*" {
  capabilities = ["read", "list", "create", "update", "delete"]
}
EOF
vault policy write -namespace=staging staging-policy staging-policy.hcl
```

### Сценарий 3: Изоляция команд

```bash
# Создание namespace для команды "team-a"
vault namespace create prod/team-a

# Включение KV в namespace команды
vault secrets enable -namespace=prod/team-a kv-v2

# Создание политики команды
cat > team-a-policy.hcl <<EOF
path "prod/team-a/secret/data/*" {
  capabilities = ["read", "list", "create", "update", "delete"]
}
EOF
vault policy write -namespace=prod/team-a team-a-policy team-a-policy.hcl

# Создание auth метода для команды
vault auth enable -namespace=prod/team-a kubernetes
```

### Сценарий 4: Cross-Namespace доступ (Enterprise)

В Vault Enterprise можно настроить доступ между namespace:

```bash
# Создание алиаса в root namespace, указывающего на prod namespace
vault write sys/namespaces/prod/alias root-alias

# Доступ к ресурсу в prod namespace из root
vault read prod/secret/data/myapp/config
```

### Сценарий 5: Ротация ключей namespace

```bash
# Просмотр информации о namespace
vault namespace lookup prod

# Обновление namespace
vault namespace update prod -ttl=720h

# Удаление namespace (необратимо!)
vault namespace delete prod
```

### Сценарий 6: Мониторинг namespace

```bash
# Проверка активных токенов в namespace
vault token lookup -namespace=prod <token>

# Просмотр политик в namespace
vault policy list -namespace=prod

# Просмотр auth методов в namespace
vault auth list -namespace=prod
```

## Лучшие практики

1. **Изоляция сред:** Используйте отдельные namespace для prod, staging, dev.
2. **Изоляция команд:** Для мультитенантных сред создавайте namespace для каждой команды.
3. **Root namespace:** Ограничьте доступ к root namespace. Используйте его только для административных операций.
4. **Политики:** Создавайте отдельные политики для каждого namespace. Избегайте глобальных wildcard-политик.
5. **Аудит:** Включите audit device для отслеживания операций в namespace.
6. **Backup:** Регулярно бэкапируйте raft-хранилище. Namespace не защищают от потери данных.

## Ограничения и известные проблемы

- **Enterprise только:** Namespaces доступны только в Vault Enterprise.
- **Количество namespace:** Ограничено лицензией Enterprise. В HCP Vault Dedicated — определённое количество.
- **Производительность:** Большое количество namespace (>100) может снизить производительность.
- **Миграция:** Перенос ресурсов между namespace не поддерживается. Требуется ручное копирование.
- **Audit logs:** Audit логи глобальные, но содержат поле `namespace`. Используйте его для фильтрации.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и лицензирование.
*   **[Авторизация в Vault](../authorization.md)** — политики доступа.
*   **[Zero Trust](../zero_trust.md)** — изоляция в архитектуре нулевого доверия.
*   [Официальная документация по namespaces](https://developer.hashicorp.com/vault/docs/enterprise/namespaces)
