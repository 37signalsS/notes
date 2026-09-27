# Control Groups в Vault

## Определения

**Control Groups** — механизм Vault Enterprise для многостороннего одобрения (multi-approval) критических операций. Реализует принцип "четырех глаз" (four-eyes principle), требующий подтверждения от нескольких доверенных лиц перед выполнением операции.

**Four-Eyes Principle (Принцип четырёх глаз)** — принцип безопасности, требующий одобрения операции как минимум двумя независимыми людьми. Цель — снижение риска ошибки или злоупотребления.

**Wrapping Token (в контексте Control Groups)** — временный токен, выданный Vault при попытке выполнения операции, требующей одобрения. Токен передаётся членам группы-одобрителя для утверждения.

**Approval (Одобрение)** — подтверждение операции членом группы-одобрителя. После накопления требуемого числа одобрений операция выполняется.

**Controlled Capabilities** — capability, при выполнении которых срабатывает Control Group. Например, `sudo` на пути `sys/audit`.

**Factor** — группа одобрителей в Control Groups. Может содержать несколько members с разными требованиями к одобрению.

## Основные концепции

### Архитектура Control Groups

Control Groups состоит из трёх компонентов:

1. **Политика с `control_group` блоком:** Определяет, для каких операций требуется одобрение.
2. **Группы одобрителей (Factors):** Определяют, кто может одобрить операцию.
3. **Wrapping Token:** Временный токен, выдаваемый при попытке выполнения операции.

### Жизненный цикл операции с Control Groups

1. **Попытка операции:** Пользователь выполняет операцию, требующую одобрения.
2. **Валидация:** Vault проверяет политику и определяет, что требуется Control Group.
3. **Выдача wrapping token:** Vault возвращает wrapping token с ограниченным TTL.
4. **Уведомление одобрителей:** Члены группы-одобрителя получают уведомление.
5. **Одобрение:** Каждый одобритель выполняет `vault write sys/control-group/authorize` с wrapping token.
6. **Выполнение:** После накопления требуемого числа одобрений операция выполняется.
7. **Unwrap:** Инициатор выполняет `vault unwrap` и получает результат.

### Сравнение Control Groups и Sentinel

| Характеристика | Control Groups | Sentinel |
| :--- | :--- | :--- |
| **Тип одобрения** | Многостороннее (несколько человек) | Policy as Code (логические правила) |
| **Сложность** | Средняя | Высокая |
| **Use case** | Критические операции (экспорт ключей) | Compliance, контекстные ограничения |
| **Интеграция** | Встроено в ACL-политики | Отдельный язык политик |
| **Enterprise** | Да | Да |

## Практические сценарии

### Сценарий 1: Базовый Control Group

#### Создание политики с Control Group

```hcl
path "secret/access/export-keys" {
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

#### Применение политики

```bash
vault policy write export-keys-policy export-keys-policy.hcl
```

#### Попытка выполнения операции

```bash
# Пользователь пытается прочитать секрет
vault read secret/access/export-keys
# → Error: control group approval required
# → wrapping_token: hvs.CAESI...
```

#### Одобрение операции

```bash
# Член группы "ops" одобряет операцию
vault write sys/control-group/authorize \
    token="hvs.CAESI..." \
    approval="Approved by ops-manager"

# После двух одобрений операция выполняется
vault unwrap hvs.CAESI...
# → {"data":{"keys":["key1","key2"]}}
```

### Сценарий 2: Множественные факторы

```hcl
path "secret/access/export-keys" {
  capabilities = ["read"]
  control_group = {
    factor "ops_manager" {
      identity {
        group_names = ["ops"]
        approvals = 2
      }
    }
    
    factor "security_team" {
      identity {
        group_names = ["security"]
        approvals = 1
      }
    }
  }
}
```

В этом сценарии требуется:
- 2 одобрения от группы "ops" ИЛИ
- 1 одобрение от группы "security"

### Сценарий 3: Controlled Capabilities

```hcl
path "sys/audit" {
  capabilities = ["sudo", "read"]
  control_group = {
    factor "admin" {
      identity {
        group_names = ["admins"]
        approvals = 2
      }
    }
  }
  controlled_capabilities = ["sudo"]
}
```

В этом сценарии:
- `read` на `sys/audit` разрешён без одобрения
- `sudo` на `sys/audit` требует одобрения 2 администраторов

### Сценарий 4: Временные ограничения

```hcl
path "secret/access/export-keys" {
  capabilities = ["read"]
  control_group = {
    factor "ops_manager" {
      identity {
        group_names = ["ops"]
        approvals = 2
      }
    }
  }
  
  # Ограничения на wrapping token
  allowed_parameters = {
    "wrap_ttl" = ["3600"]
  }
  min_wrapping_ttl = "300s"
  max_wrapping_ttl = "3600s"
}
```

### Сценарий 5: Интеграция с Slack/Teams

```bash
# Скрипт для уведомления одобрителей
#!/bin/bash
WRAPPING_TOKEN="$1"
APPROVER_GROUP="ops"

# Получение информации о запросе
vault unwrap -meta "$WRAPPING_TOKEN"

# Отправка уведомления в Slack
curl -X POST https://hooks.slack.com/services/... \
     -H 'Content-Type: application/json' \
     -d "{\"text\":\"Требуется одобрение операции export-keys. Wrapping token: $WRAPPING_TOKEN\"}"
```

### Сценарий 6: Аудит Control Groups

```bash
# Просмотр операций, требующих одобрения
jq 'select(.request.path == "secret/access/export-keys")' /var/log/vault/audit.log

# Просмотр одобрений
jq 'select(.request.path == "sys/control-group/authorize")' /var/log/vault/audit.log
```

## Лучшие практики

1. **Критичные операции:** Используйте Control Groups только для критичных операций (экспорт ключей, изменение политик).
2. **Минимальное число одобрителей:** 2–3 человека достаточно для большинства случаев.
3. **Разделение обязанностей:** Одобрители должны быть независимы от инициатора операции.
4. **TTL:** Устанавливайте разумный TTL для wrapping token (1–24 часа).
5. **Уведомления:** Интегрируйте со Slack/Teams для уведомления одобрителей.
6. **Аудит:** Включите audit device для отслеживания всех операций одобрения.

## Ограничения и известные проблемы

- **Enterprise только:** Control Groups доступны только в Vault Enterprise.
- **Синхронность:** Все одобрители должны одобрить операцию в течение TTL wrapping token.
- **Сложность:** Настройка и поддержка Control Groups требует дополнительных усилий.
- **User Lockout:** Если одобритель заблокирован, операция не может быть выполнена.

## Дополнительная информация

*   **[Авторизация в Vault](../authorization.md)** — ACL-политики и capabilities.
*   **[Sentinel — продвинутая авторизация](../authorization.md#3-sentinel-и-продвинутая-авторизация-enterprise)** — альтернативный подход.
*   **[Zero Trust](../zero_trust.md)** — принцип наименьших привилегий.
*   [Официальная документация Control Groups](https://developer.hashicorp.com/vault/docs/enterprise/control-groups)
