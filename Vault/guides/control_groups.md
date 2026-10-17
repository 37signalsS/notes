# Control Groups в Vault

> **Актуально для:** Vault Enterprise 2.x (latest 2.1.2; ветка 1.12.x+ также поддерживается)

## Определения

**Control Groups** — механизм Vault Enterprise Plus для многостороннего одобрения (multi-approval) критических операций. Реализует принцип "четырёх глаз" (four-eyes principle), требующий подтверждения от нескольких доверенных лиц перед выполнением операции.

**Four-Eyes Principle (Принцип четырёх глаз)** — принцип безопасности, требующий одобрения операции как минимум двумя независимыми людьми. Цель — снижение риска ошибки или злоупотребления.

**Wrapping Token (в контексте Control Groups)** — временный токен, выданный Vault при попытке выполнения операции, требующей одобрения. Token имеет ограниченный TTL. Авторизаторы используют его accessor для одобрения операции через API `/sys/control-group/authorize`.

**Approval (Одобрение)** — подтверждение операции членом группы-одобрителя (factor). После накопления требуемого числа одобрений (`approvals`) для всех factor операция выполняется, и инициатор может извлечь результат через `vault unwrap`.

**Factor (Фактор одобрения)** — группа одобрителей в Control Groups. Каждый factor определяет identity group, в которую должен входить одобритель, и минимальное число одобрений (`approvals`). При наличии нескольких factor все они должны быть удовлетворены (логика AND).

**Controlled Capabilities** — параметр `controlled_capabilities` внутри блока `factor`, определяющий, для каких capability срабатывает Control Group. Если `controlled_capabilities` не указан, factor проверяется для всех операций к указанному пути.

**Control Group TTL** — параметр `ttl` в блоке `control_group`, ограничивающий время жизни wrapping token для конкретной политики. Глобальный лимит задаётся через API `/sys/config/control-group` параметром `max_ttl`.

**Authorizer (Авторизатор)** — участник identity group, одобряющий операцию через `vault write sys/control-group/authorize`.

## Основные концепции

### Архитектура Control Groups

Control Groups состоит из трёх компонентов:

1. **Политика с `control_group` блоком** — определяет, для каких операций требуется одобрение и кто может одобрить.
2. **Identity Groups (Factors)** — через Identity Store определяют, кто может одобрить операцию.
3. **Wrapping Token + /sys/control-group API** — механизм выдачи временного токена и проверки одобрений.

### Жизненный цикл операции с Control Groups

1. **Попытка операции:** Пользователь выполняет операцию, требующую одобрения.
2. **Валидация:** Vault проверяет политику и определяет, что требуется Control Group.
3. **Выдача wrapping token:** Vault возвращает wrapping token с accessor и ограниченным TTL. Оригинальные данные не возвращаются.
4. **Одобрение:** Каждый одобритель выполняет `vault write sys/control-group/authorize` с accessor wrapping token.
5. **Проверка статуса:** Используется `POST /sys/control-group/request` для проверки количества полученных одобрений.
6. **Выполнение:** После накопления требуемого числа одобрений для всех factor операция помечается как одобренная.
7. **Unwrap:** Инициатор выполняет `vault unwrap <accessor>` и получает результат операции.

### Логика множественных factor

При наличии нескольких factor требуется их **все** удовлетворить (логика AND, а не OR):

```
factor "tech_leads" { approvals = 2 }   # требуется 2 одобрения
factor "super_users" { approvals = 1 }  # требуется 1 одобрение

=> Всего требуется: 2 одобрения из tech_leads И 1 одобрение из super_users
```

Если один одобритель является членом обеих групп (tech_leads и super_users), одно одобрение удовлетворяет оба factor.

### Сравнение Control Groups и Sentinel

| Характеристика | Control Groups | Sentinel |
| :--- | :--- | :--- |
| **Тип одобрения** | Многостороннее (несколько человек) | Policy as Code (логические правила) |
| **Сложность** | Средняя | Высокая |
| **Use case** | Критические операции (экспорт ключей, изменение политик) | Compliance, контекстные ограничения |
| **Интеграция** | Встроено в ACL-политики | Отдельный язык политик |
| **Enterprise** | Да (Plus) | Да (Plus) |

Подробное описание Sentinel-механиков (порядок оценки запросов, enforcement levels, override, примеры правил) — [Sentinel-политики (RGP/EGP)](./sentinel-policies.md).

## Практические сценарии

### Сценарий 1: Базовый Control Group для доступа к секрету

#### Создание группы одобрителей

```bash
# 1. Создать identity group "ops" (если ещё не создана)
vault group create -name="ops" -description="Operations team approvers"
# → id  b32dd389-99a0-4f63-ab88-ce4a61f33b9c

# 2. Добавить участников в группу
vault group member add -group-id=b32dd389-99a0-4f63-ab88-ce4a61f33b9c \
  -member-id=44e88a7c-74b8-4f87-91a4-63cc41d64a2c
# (member-id — entity ID одобрителя)
```

#### Создание политики с Control Group

```hcl
path "secret/data/access/export-keys" {
  capabilities = ["read"]
  control_group = {
    factor "ops_manager" {
      identity {
        group_names = ["ops"]
        approvals = 2
      }
    }
  }
}
```

```bash
# Применить политику
vault policy write export-keys-control-group export-keys-control-group.hcl
```

#### Попытка выполнения операции

```bash
# Пользователь пытается прочитать секрет
vault kv get secret/data/access/export-keys
# → Error: 1 error occurred:
# → * control group approval required
# → Request identity token accessor: 0ad21b78-e9bb-64fa-88b8-1e38db217bde
```

#### Одобрение операции

```bash
# Одобритель 1: авторизует запрос по accessor
vault write sys/control-group/authorize \
    token="0ad21b78-e9bb-64fa-88b8-1e38db217bde" \
    approval="Approved by ops-manager-1: verified request context"

# → Key        Value
# → ---        -----
# → approved   false

# Одобритель 2: второй одобритель
vault write sys/control-group/authorize \
    token="0ad21b78-e9bb-64fa-88b8-1e38db217bde" \
    approval="Approved by ops-manager-2: reviewed"

# → Key        Value
# → ---        -----
# → approved   true
```

#### Проверка статуса и извлечение результата

```bash
# Проверить статус одобрения
vault write sys/control-group/request \
    token="0ad21b78-e9bb-64fa-88b8-1e38db217bde"

# → Key              Value
# → ---              -----
# → approved         true
# → request_path     secret/data/access/export-keys
# → request_entity   map[name:alice id:entity-uuid-123]
# → authorizations   [
# →   map[entity_id:44e88a7c-... entity_name:alice],
# →   map[entity_id:7e90f634-... entity_name:bob]
# → ]

# Извлечь результат (выполняет инициатор операции)
vault unwrap 0ad21b78-e9bb-64fa-88b8-1e38db217bde
# → ====== Metadata ======
# → Key              Value
# → ---              -----
# → api_version      ...
# → ...
```

### Сценарий 2: Множественные factor (AND-логика)

```hcl
path "secret/data/access/export-keys" {
  capabilities = ["read"]
  control_group = {
    ttl = "8h"
    factor "tech_leads" {
      identity {
        group_names = ["managers", "leads"]
        approvals = 2
      }
    }
    factor "super_users" {
      identity {
        group_names = ["superusers"]
        approvals = 1
      }
    }
  }
}
```

В этом сценарии требуется **все** factor удовлетворить:
- 2 одобрения от группы `managers` ИЛИ `leads` (членство в любой из групп достаточно, но нужно 2 разных одобрителя)
- 1 одобрение от группы `superusers`

### Сценарий 3: Controlled Capabilities (разделение доступа по capability)

```hcl
path "secret/data/myapp/*" {
  capabilities = ["read", "list"]
  control_group = {
    factor "admin" {
      identity {
        group_names = ["admins"]
        approvals = 1
      }
      controlled_capabilities = ["list"]
    }
  }
}
```

В этом сценарии:
- `read` на `secret/data/myapp/*` разрешён без одобрения (anyone with the policy)
- `list` на `secret/data/myapp/*` требует одобрения 1 администратора (т.к. `controlled_capabilities = ["list"]` внутри `factor`)

### Сценарий 4: Ограничение TTL и глобальная конфигурация

```hcl
# Политика с ttl для wrapping token
path "secret/data/access/export-keys" {
  capabilities = ["read"]
  control_group = {
    ttl = "4h"
    factor "ops_manager" {
      identity {
        group_names = ["ops"]
        approvals = 2
      }
    }
  }
}
```

Глобальная конфигурация Control Groups (max TTL для всех wrapping token):

```bash
# Просмотр текущей конфигурации
curl -H "X-Vault-Token: $VAULT_TOKEN" \
  https://vault:8200/v1/sys/config/control-group
# → {"data": {"max_ttl": "24h"}}

# Установить максимальный TTL (например, 24 часа)
curl -H "X-Vault-Token: $VAULT_TOKEN" \
  -X POST \
  -d '{"max_ttl": "24h"}' \
  https://vault:8200/v1/sys/config/control-group

# Сбросить конфигурацию
curl -H "X-Vault-Token: $VAULT_TOKEN" \
  -X DELETE https://vault:8200/v1/sys/config/control-group
```

### Сценарий 5: Автоматизация уведомлений и одобрений (devops)

```bash
#!/bin/bash
# Скрипт для автоматизированного workflow Control Groups
set -euo pipefail

WRAPPING_ACCESSOR="$1"
APPROVAL_MESSAGE="${2:-"Approved by automation"}"
VAULT_ADDR="${VAULT_ADDR:-https://vault:8200}"

# 1. Проверить статус запроса
STATUS=$(curl -sf -H "X-Vault-Token: $VAULT_TOKEN" \
  -X POST \
  -d "{\"token\": \"$WRAPPING_ACCESSOR\"}" \
  "$VAULT_ADDR/v1/sys/control-group/request" | jq -r '.data.approved')

if [[ "$STATUS" == "true" ]]; then
  echo "Operation already approved"
  exit 0
fi

# 2. Выполнить одобрение
RESPONSE=$(curl -sf -H "X-Vault-Token: $VAULT_TOKEN" \
  -X POST \
  -d "{\"token\": \"$WRAPPING_ACCESSOR\", \"approval\": \"$APPROVAL_MESSAGE\"}" \
  "$VAULT_ADDR/v1/sys/control-group/authorize" | jq -r '.data.approved')

if [[ "$RESPONSE" == "true" ]]; then
  echo "Operation fully approved"
else
  echo "Approval recorded, waiting for additional approvals"
fi
```

### Сценарий 6: Аудит и мониторинг Control Groups (SRE)

#### Аудит через audit logs

```bash
# Просмотр операций, требующих Control Group approval
jq 'select(.type=="request") | select(.request.operation=="read") | select(.request.path=="secret/data/access/export-keys")' \
  /var/log/vault/audit.log

# Просмотр одобрений
jq 'select(.request.path == "sys/control-group/authorize")' \
  /var/log/vault/audit.log

# Просмотр запросов с истекшим wrapping token (неодобренные)
jq 'select(.type=="response") | select(.error != null) | select(.error | contains("expired"))' \
  /var/log/vault/audit.log
```

#### Метрики для Prometheus/Grafana

```bash
# Vault telemetry предоставляет метрики о Control Groups
# Включить unauthenticated metrics access в конфиге:
# telemetry {
#   unauthenticated_metrics_access = true
# }

# Метрики, связанные с Control Groups:
# - vault.core.control_group.approval.count — число одобрений
# - vault.core.control_group.expired.count — число просроченных запросов

curl -s "http://localhost:9100/metrics" | \
  grep "vault_core_control_group"
```

#### Мониторинг через CLI

```bash
# Просмотр всех неприменённых (не oneобренныхых) Control Group запросов
# (требует root или policy с sudo на sys/control-group)
vault list sys/control-group/request
```

## Операции и команды

### CLI команды

| Команда | Описание | Пример |
| :--- | :--- | :--- |
| `vault write sys/control-group/authorize` | Одобрить запрос | `vault write sys/control-group/authorize token=<accessor>` |
| `vault write sys/control-group/request` | Проверить статус | `vault write sys/control-group/request token=<accessor>` |
| `vault unwrap` | Извлечь результат | `vault unwrap <accessor>` |
| `vault policy write` | Применить политику с CG | `vault policy write my-policy policy.hcl` |

**Параметры `vault write sys/control-group/authorize`:**

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `token` | Accessor wrapping token | `token=0ad21b78-...` |
| `approval` | Сообщение одобрителя | `approval="Reviewed and approved"` |

### API эндпоинты

| Метод | Путь | Описание | Параметры |
| :--- | :--- | :--- | :--- |
| `POST` | `/sys/control-group/authorize` | Одобрить операцию | `accessor` (string, required), `approval` (string) |
| `POST` | `/sys/control-group/request` | Проверить статус | `accessor` (string, required) |
| `GET`  | `/sys/config/control-group` | Просмотр глобальной конфигурации | — |
| `POST` | `/sys/config/control-group` | Установить max_ttl | `max_ttl` (string) |
| `DELETE` | `/sys/config/control-group` | Сбросить конфигурацию | — |

#### Примеры API

```bash
# Одобрить запрос (accessor получен после попытки операции)
curl -H "X-Vault-Token: $VAULT_TOKEN" \
  -X POST \
  -d '{"token": "0ad21b78-e9bb-64fa-88b8-1e38db217bde", "approval": "Approved by ops-manager"}' \
  https://vault:8200/v1/sys/control-group/authorize

# → {"data": {"approved": false}}

# Проверить статус
curl -H "X-Vault-Token: $VAULT_TOKEN" \
  -X POST \
  -d '{"token": "0ad21b78-e9bb-64fa-88b8-1e38db217bde"}' \
  https://vault:8200/v1/sys/control-group/request

# → {"data": {"approved": true, "request_path": "secret/data/foo", "authorizations": [...]}}

# Только root namespace может выполнять конфигурацию Control Groups
curl -H "X-Vault-Token: $VAULT_TOKEN" \
  https://vault:8200/v1/sys/config/control-group
# → {"data": {"max_ttl": "24h"}}
```

### Автоматизация

```bash
# Проверить статус Control Group в CI/CD pipeline
STATUS=$(curl -sf -H "X-Vault-Token: $VAULT_TOKEN" \
  -X POST \
  -d '{"token": "$WRAPPING_ACCESSOR"}' \
  "$VAULT_ADDR/v1/sys/control-group/request" | jq -r '.data.approved')

if [[ "$STATUS" == "true" ]]; then
  echo "Control group approved, proceeding..."
else
  echo "Control group not yet approved"
  exit 1
fi
```

## Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `control group approval required` | Запрос требует одобрения; accesssor wrapping token выдан | Передайте accessor одобрителям; один из них вызывает `vault write sys/control-group/authorize` |
| `wrapping token not found` | Accessor неверен или истёк | Проверьте accessor; убедитесь что TTL не истёк (проверьте `max_ttl` через `/sys/config/control-group`) |
| `permission denied` на `/sys/control-group/authorize` | Токен не входит в approval group | Проверьте членство сущности в identity group, указанной в `group_names` политики |
| `controlled_capabilities must be subset of capabilities` | `controlled_capabilities` содержит capability, отсутствующую в политике | Исправьте `controlled_capabilities` — значения должны быть подмножеством `capabilities` блока |
| `ttl cannot exceed max_ttl` | `ttl` в политике превышает глобальный `max_ttl` | Уменьшите `ttl` в политике или увеличьте `max_ttl` через `/sys/config/control-group` |
| `control_group` block requires Enterprise | Используется OSS версия Vault | Контролируйте использование Control Groups только в Enterprise + HCP Vault Dedicated/Standard |
| `request_entity` пустой в `/sys/control-group/request` | Сущность одобрителя не связана с запросом | Проверьте что одобритель аутентифицирован через auth method и его entity привязан к identity group |
| Автоматическое одобрение не работает | `approval` параметр отсутствует или пустой | Добавьте параметр `approval` в запросе: `vault write sys/control-group/authorize token=X approval="Approved"` |
| Запрос не одобрен после всех одобрений | Один из factor неудовлетворён (AND-логика) | Проверьте что все factor получили минимальное число одобрений: `vault write sys/control-group/request token=X` |
| `sys/config/control-group` возвращает 404 | Vault версии < 1.14 или не Enterprise | `max_ttl` конфигурация доступна с Vault Enterprise 1.14+. На более ранних версиях используйте `ttl` в политике. |

## Лучшие практики

1. **Критичные операции:** Используйте Control Groups только для действительно критичных операций (экспорт ключей, изменение root-политик, изменение audit конфигурации).
2. **Минимальное число одобрителей:** 2–3 человека достаточно для большинства случаев. Используйте отдельные factor для разных ролей (например, security + ops).
3. **Разделение обязанностей:** Одобрители должны быть независимы от инициатора операции. Используйте identity groups для чёткого назначения ролей.
4. **TTL:** Устанавливайте разумный TTL для wrapping token (1–8 часов) через параметр `ttl` в политике и через `/sys/config/control-group` для глобального `max_ttl`.
5. **Уведомления:** Интегрируйте с системами уведомлений (Slack, Teams, Email) для оповещения одобрителей. Используйте `POST /sys/control-group/request` для проверки статуса.
6. **Аудит:** Включите audit device для отслеживания всех операций одобрения. Используйте поле `request_path` в audit логах для фильтрации по Control Group операциям.
7. **Мониторинг:** Настраивайте алерты на истекшие wrapping tokens и операции с длительным временем одобрения. Используйте Vault telemetry метрики.
8. **Emergency bypass:** Документируйте процедуру экстренного доступа (emergency token) на случай недоступности одобрителей. Храните в over-provisioned safe.
9. **Регулярный обзор:** Периодически пересматривайте состав групп одобрителей и удаляйте неактивных участников.
10. **Документация:** Поддерживайте актуальную документацию по процедурам одобрения для каждой критической операции.

## Ограничения и известные проблемы

- **Enterprise + Plus только:** Control Groups требуют Vault Enterprise Plus или HCP Vault Dedicated/Standard. В OSS использовать нельзя.
- **Синхронность:** Все одобрители должны одобрить операцию в течение TTL wrapping token. Истёкший запрос нужно повторить с нуля.
- **Истечение TTL:** Если wrapping token истёкает, запрос автоматически отклоняется. Длинные операции требуют увеличения `ttl` или `max_ttl`.
- **User Lockout:** Если одобритель заблокирован или уволен, операция не может быть выполнена. Нужно изменить политику или добавить заменяющего в identity group.
- **AND-логика при множественных factor:** Все factor должны быть удовлетворены. Это может создавать узкое место, если один из factor сложен для выполнения.
- **Конфигурация max_ttl:** `/sys/config/control-group` доступен только с Vault Enterprise 1.14+. На ранних версиях используйте `ttl` в политике для ограничения срока.
- **Audit не фильтрует по умолчанию:** Audit записи содержат accessor и request_entity, но требуют ручного парсинга для построения отчётов.
- **Не работает с Token Namespaces (Enterprise):** Control Groups не поддерживает cross-namespace oneобрения. Одобритель должен быть в том же namespace, что и инициатор.

## Дополнительная информация

*   **[Авторизация в Vault](../authorization.md)** — ACL-политики, capabilities, controlled_capabilities.
*   **[Концепции Vault](../concepts.md)** — Identity Store, entities, groups.
*   **[Zero Trust](../zero_trust.md)** — принцип наименьших привилегий и multi-approval.
*   [Официальная документация Control Groups](https://developer.hashicorp.com/vault/docs/enterprise/control-groups)
*   [Control Groups API](https://developer.hashicorp.com/vault/api-docs/system/control-group)
*   [Control Group Configuration API](https://developer.hashicorp.com/vault/api-docs/system/config-control-group)