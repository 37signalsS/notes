**Актуально для:** Consul 1.20.x / 1.19.x

# Система управления доступом (ACL)

## Определения

**Consul ACL (Access Control List)** — это система разграничения прав доступа, основанная на возможностях (capability-based), которая обеспечивает аутентификацию и авторизацию для всех компонентов кластера. Система работает по принципу **Default Deny** (по умолчанию запрещено всё), требуя явного разрешения для любой операции.

В архитектуре Consul ACL является критически важным компонентом безопасности, обеспечивающим:
- **Аутентификация:** Проверку личности субъекта (человека, сервиса или узла) через токены или внешние методы (Kubernetes, OIDC).
- **Авторизация:** Проверку прав субъекта на выполнение конкретных действий над ресурсами (KV, сервисы, узлы, политики).
- **Изоляцию:** Разделение доступа в рамках [Namespaces и Admin Partitions](./consul_architecture.md).

## Основные концепции

### ACL Токены (Tokens)

Токен — это секретная строка (UUID), которая идентифицирует субъект в системе.
- **Management Token:** Токен с неограниченными правами (аналог `root`), создается при инициализации (bootstrap). Встроенная политика `global-management` имеет зарезервированный ID `00000000-0000-0000-0000-000000000001`.
- **Client Token:** Токен с ограниченным набором прав, привязанный к политикам или ролям.
- **Service Token:** Специализированный токен для конкретного сервиса, часто генерируемый автоматически в Service Mesh.
- **Anonymous Token:** Токен, используемый для запросов без явной аутентификации. Права анонимного токена определяются встроенной политикой `builtin/global-read-only` с ID `00000000-0000-0000-0000-000000000002`. По умолчанию предоставляет только права на чтение.
- **Agent Recovery Token:** Специальный токен (`acl.tokens.agent_recovery`), используемый для доступа к `agent/` HTTP API при недоступности серверов Consul. Политика привязана локально на агенте и не требует репликации на серверы.
- **Replication Token:** Токен (`acl.tokens.replication`), авторизующий вторичные датацентры на репликацию данных из первичного.

#### Жизненный цикл токена

- **ExpirationTime:** Токены могут иметь время истечения (от 1 минуты до 24 часов). По умолчанию токен не истекает.
- **Local:** Токен может быть локальным для датацентра (`Local: true`), не реплицируясь в другие датацентры.
- **Persistence:** При `enable_token_persistence = true` токены сохраняются на диск и перезагружаются при перезапуске агента.

### Политики (Policies)

Политики определяют набор правил доступа к ресурсам. Описываются на языке **HCL**.
Ресурсы включают: `key` (KV), `service`, `node`, `agent`, `event`, `query`, `operator`, `acl`, `session`, `namespace`.

Доступные политики (dispositions):
- `read` — чтение без модификации
- `write` — чтение и модификация
- `deny` — явный запрет
- `list` — рекурсивный перебор ключей в `key_prefix` (требует `acl.enable_key_list_policy = true`)

Правила могут определяться в режиме `allowlist` (при `default_policy = "deny"`) или `denylist` (при `default_policy = "allow"`).

**Пример политики:**
```hcl
# Разрешение на чтение сервиса и запись в KV по префиксу
service "web" {
  policy = "read"
}

key_prefix "config/web/" {
  policy = "write"
}

node_prefix "" {
  policy = "read"
}
```

### Роли (Roles)

Роли позволяют группировать несколько политик в одну сущность, упрощая управление правами для больших групп субъектов. Токен может быть привязан к одной или нескольким ролям. Роли поддерживают шаблонизированные политики (templated policies, Consul 1.20+), что избавляет от необходимости создавать идентичные политики для каждого сервиса.

## Методы аутентификации (Auth Methods)

Методы аутентификации позволяют внешним системам (Kubernetes, OIDC провайдеры) подтверждать личность субъекта и автоматически получать Consul токен.

### Kubernetes Auth Method

Позволяет подам в Kubernetes аутентифицироваться в Consul, используя свой **Service Account JWT**.

- **Механизм:** Consul проверяет предоставленный JWT через Kubernetes API сервер.
- **Binding Rules:** Правила привязки определяют, какие атрибуты Service Account (имя, неймсейс) маппятся на какие роли в Consul.
- **Selector:** Фильтрация по атрибутам, например: `serviceaccount.namespace == "prod"`.

### OIDC Auth Method (Enterprise)

Используется для интерактивного входа пользователей через внешних провайдеров (Okta, GitLab, Google, Keycloak).

- **UI & CLI:** Поддерживает аутентификацию как в веб-интерфейсе, так и через командную строку.
- **Claims Mapping:** Поля из ID-токена провайдера (email, groups) могут использоваться для назначения прав.

### JWT Auth Method

Универсальный метод для headless-аутентификации с использованием любых подписанных JWT-токенов. Часто используется для интеграции с CI/CD или внешними KMS.

## Практические примеры политик

Политики в Consul должны следовать принципу наименьших привилегий. Ниже приведены примеры для типовых ролей в инфраструктуре.

### 1. Роль: Администратор платформы (Full Access)
Вместо использования `bootstrap`-токена для повседневных задач, рекомендуется создать политику администратора.

```hcl
# Полный доступ ко всем ресурсам
acl = "write"
operator = "write"
agent_prefix "" {
  policy = "write"
}
node_prefix "" {
  policy = "write"
}
service_prefix "" {
  policy = "write"
}
key_prefix "" {
  policy = "write"
}
query_prefix "" {
  policy = "write"
}
```

### 2. Роль: Разработчик (Team/Service level)
Ограничивает доступ только к ресурсам конкретной команды или сервиса.

```hcl
# Чтение всех узлов кластера (нужно для Service Discovery)
node_prefix "" {
  policy = "read"
}

# Управление своим сервисом
service "order-api" {
  policy = "write"
}

# Чтение конфигурации и запись флагов в своем префиксе KV
key_prefix "config/orders/" {
  policy = "read"
}
key "config/orders/maintenance-mode" {
  policy = "write"
}

# Запрет на просмотр секретов других команд
key_prefix "config/billing/" {
  policy = "deny"
}
```

### 3. Роль: CI/CD Pipeline (Headless)
Используется для автоматизированной регистрации сервисов или обновления конфигурации.

```hcl
# Разрешение на регистрацию экземпляров сервиса
service "order-api" {
  policy = "write"
}

# Разрешение агенту выполнять проверки здоровья от имени сервиса
agent "node-01" {
  policy = "write"
}

# Обновление метаданных деплоя в KV
key "deploy/orders/last-version" {
  policy = "write"
}
```

### 4. Роль: Vault (Backend storage)
Необходима, если Vault использует Consul как бэкенд для хранения данных.

```hcl
# Vault требует полный доступ к своему префиксу
key_prefix "vault/" {
  policy = "write"
}

# Создание сессий для механизмов High Availability (HA)
session_prefix "" {
  policy = "write"
}

# Чтение информации об агенте для Health Checks
agent_prefix "" {
  policy = "read"
}

# Для работы Service Discovery (регистрация сервиса 'vault')
service "vault" {
  policy = "write"
}
```

### 5. Роль: Мониторинг (Prometheus)
Минимальные права для сбора метрик и обнаружения целей.

```hcl
# Разрешение на чтение всех сервисов и узлов для Discovery
service_prefix "" {
  policy = "read"
}
node_prefix "" {
  policy = "read"
}

# Разрешение на чтение системных метрик агента
agent_prefix "" {
  policy = "read"
}
```

## Правила привязки (Binding Rules) и Шаблонизация

**Binding Rules** связывают личность из метода аутентификации с ролями или сервисными идентичностями в Consul.

### Шаблонизированные политики (v1.20+)
Consul позволяет создавать политики с переменными, которые заполняются данными из JWT-токена или OIDC-клаймов. Это избавляет от необходимости создавать тысячи идентичных политик для каждого сервиса.

**Пример шаблона:**
```hcl
# Доступ к KV только для своего неймсейса Kubernetes
key_prefix "config/${value.serviceaccount.namespace}/" {
  policy = "write"
}
```
*Переменная `${value.field}` берется из проверенных данных метода аутентификации.*

## Инициализация и настройка

### Предварительные требования

- Running Consul cluster (серверы и клиенты)
- Доступ к конфигурации агентов (`/etc/consul.d/`)
- Права на перезапуск служб Consul
- Для Enterprise-функций (Namespaces, Admin Partitions, Sentinel) — действующая лицензия

### Включение ACL (Bootstrap)

**Шаг 1:** Включите ACL в конфигурации серверов:
```hcl
acl {
  enabled = true
  default_policy = "deny"
  enable_token_persistence = true
}
```
# → ACL включены, все запросы по умолчанию запрещены

**Шаг 2:** Выполните bootstrap на одном из серверов:
```bash
consul acl bootstrap
# → SecretID: <токен>, AccessorID: <идентификатор>
```
Сохраните `SecretID` — это ваш первый Management Token.

**Шаг 3:** Настройте токены для агентов:
```bash
# Создание политики для агента
consul acl policy create -name "agent-policy" -rules @agent-policy.hcl -token "<MANAGEMENT_TOKEN>"
# → ID: <auto-generated>

# Создание токена для агента
consul acl token create -description "Agent token" -policy-name "agent-policy" -token "<MANAGEMENT_TOKEN>"
# → SecretID: <токен>, AccessorID: <идентификатор>
```

**Шаг 4:** Примените конфигурацию на всех серверах и клиентах с помощью rolling restart.

### Управление через CLI

```bash
# Создание политики
consul acl policy create -name "web-reader" -description "Read access for web" -rules @web-policy.hcl -token "<MANAGEMENT_TOKEN>"
# → ID: <auto-generated>, Name: web-reader

# Создание роли с привязкой политики
consul acl role create -name "web-role" -policy-name "web-reader" -token "<MANAGEMENT_TOKEN>"
# → ID: <auto-generated>

# Создание токена, привязанного к роли
consul acl token create -description "Token for web service" -role-name "web-role" -token "<MANAGEMENT_TOKEN>"
# → SecretID: <токен>, AccessorID: <идентификатор>

# Чтение токена для проверки прав
consul acl token read -id <token_accessor_id> -token "<MANAGEMENT_TOKEN>"
# → Policies: [...], Roles: [...], ExpirationTime: ...

# Ротация токена (создание нового с заменой старого)
consul acl token create -description "Rotated token" -policy-name "web-reader" -token "<MANAGEMENT_TOKEN>"
# → Новый SecretID; старый должен быть удалён:
consul acl token delete -id <old_accessor_id> -token "<MANAGEMENT_TOKEN>"
```

### Настройка Kubernetes Auth Method (Helm)

В файле `values.yaml` для Consul Helm chart:
```yaml
global:
  acls:
    manageSystemACLs: true
server:
  extraConfig: |
    {
      "acl": {
        "enabled": true,
        "default_policy": "deny"
      }
    }
```

## Интеграция с Vault

Vault может выступать в роли **ACL Secret Engine** для Consul, динамически генерируя токены с заданным TTL и политиками. Это устраняет необходимость хранения долгоживущих токенов в конфигурациях. Подробнее: **[Vault с Consul бэкендом](../Vault/guides/vault_with_consul_backend.md)**.

## Устранение неполадок (Troubleshooting)

### Ошибка: Permission Denied (403)
- **Проверка токена:** Убедитесь, что токен передается в заголовке `X-Consul-Token` или через флаг `-token`.
- **Инспекция прав:** Проверьте содержимое политик, привязанных к токену:
  ```bash
  consul acl token read -id <token_accessor_id> -token "<MANAGEMENT_TOKEN>"
  ```
- **Анонимный доступ:** Если запрос выполняется без токена, проверьте права политики для анонимного пользователя.

### Проблемы Auth Methods
- **Kubernetes:** Проверьте доступность API-сервера Kubernetes с серверов Consul и валидность CA-сертификата.
- **OIDC:** Проверьте `Allowed Redirect URIs` в настройках провайдера (должны включать `/oidc/callback`).
- **Логи:** Серверы Consul логируют ошибки аутентификации с деталями (`invalid signature`, `issuer mismatch`). Используйте `-log-level=debug`.

### Агент не может синхронизировать каталог
- **Симптом:** В логах агента ошибки `ACL not found` или `Permission denied` при регистрации сервиса.
- **Причина:** У агента нет токена с правами на запись своего узла (`node "<hostname>" { policy = "write" }`) или на чтение сервисов (`service_prefix "" { policy = "read" }`).
- **Решение:** Проверьте `acl.tokens.agent` и политики, привязанные к нему.

### Потеря кворума при включении ACL
- **Симптом:** После включения `acl.enabled = true` серверы не образуют кворум.
- **Причина:** Агенты пытаются выполнить операции без токенов. При включении ACL на работающем кластере используйте `default_policy = "allow"` для первоначальной настройки, затем переключите на `deny` после распределения токенов.
- **Решение:** Rolling restart с правильными токенами.

## Лучшие практики (Best Practices)

- **Default Deny:** Всегда включайте ACL с `default_policy = "deny"`. Белый список только для необходимых префиксов.
- **Least Privilege:** Выдавайте токены только с теми правами, которые необходимы для конкретной задачи. Используйте `deny` для явного запрета доступа к чувствительным префиксам.
- **Token Rotation:** Периодически перевыпускайте токены, особенно для сервисов и CI/CD. Используйте `ExpirationTime` при создании токенов.
- **Separation of Duties:** Используйте отдельные токены для операций (bootstrap, agent, replication, default). Никогда не используйте management-токен в приложениях.
- **Audit Logging:** Включите аудит доступа к ACL API. Операции изменения ACL требуют `acl = "write"` и должны логироваться.
- **Replication Token:** Для мульти-датацентровых кластеров настройте `acl.tokens.replication` на secondary датацентры.
- **Vault Integration:** Предпочитайте динамическую генерацию токенов через Vault вместо хранения долгоживущих токенов в конфигурациях.
- **Enterprise Sentinel:** Для сложной логики доступа (время суток, геолокация, состояние кластера) используйте Sentinel-политики (Consul Enterprise).
- **Local Tokens:** Для мульти-датацентровых сред используйте локальные токены (`Local: true`) для операций, которые не должны реплицироваться.

## Граничные случаи (Edge Cases)

- **Anonymous Token:** По умолчанию анонимный токен имеет права только на чтение. Если ACL включены без явной настройки анонимного токена, все неаутентифицированные запросы будут отклонены.
- **Namespaces и Partitions:** В Enterprise-версии политики изолируются в рамках Namespaces и Admin Partitions. Политика из одного namespace не влияет на другой. Каждый namespace автоматически получает политику `namespace-management` для управления ACL внутри него.
- **Токены без истечения:** Токены без `ExpirationTime` действуют бессрочно. Это удобно для сервисных учетных данных, но повышает риск утечки.
- **Agent Recovery Token:** Используется только при недоступности серверов Consul. Не требуется для штатной работы.
- **Multi-Datacenter:** Токены реплицируются между датацентрами, если не указан флаг `Local: true`. Реплика-датацентр требует `acl.tokens.replication`.
- **Service Mesh Intentions:** Intentions являются частью ACL и требуют соответствующих токенов для управления. При `default_policy = "deny"` настройте `default_intention_policy = "deny"` (Consul 1.20.1+), чтобы обеспечить безопасность по умолчанию.
- **Snapshot и ACL:** Создание snapshot требует `acl = "write"`, так как snapshot содержит все секретные ID токенов. Восстановление из snapshot должно выполняться с помощью management-токена.

## Дополнительная информация

- **[Архитектура Consul](./consul_architecture.md)** — общие принципы работы Control Plane.
- **[Namespaces и Partitions](./consul_architecture.md#многопользовательская-изоляция-enterprise)** — логическое разделение политик.
- **[Consul Service Mesh](./consul_service_mesh.md)** — использование ACL для Intentions.
- **[Consul KV Store](./consul_kv_store.md)** — управление доступом на уровне ключей.
- **[Consul Audit Logging](./consul_audit_logging.md)** — аудит операций ACL для compliance.
- **[Consul Config Entries Lifecycle](./consul_config_entries_lifecycle.md)** — управление конфигурацией как кодом.
- **[Vault с Consul бэкендом](../Vault/guides/vault_with_consul_backend.md)** — динамическая генерация токенов.
- **[Consul Deployment](./consul-deployment.md)** — порядок развертывания с включением ACL.
- **[Официальная документация: ACL](https://developer.hashicorp.com/consul/docs/security/acl)**.
- **[Официальная документация: ACL Best Practices](https://developer.hashicorp.com/consul/docs/secure/acl/best-practice)**.
- **[Официальная документация: ACL Policy Reference](https://developer.hashicorp.com/consul/docs/reference/acl/policy)**.
