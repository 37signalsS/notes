# Система управления доступом (ACL)

# Определения

**Consul ACL (Access Control List)** — это система разграничения прав доступа, основанная на возможностях (capability-based), которая обеспечивает аутентификацию и авторизацию для всех компонентов кластера. Система работает по принципу **Default Deny** (по умолчанию запрещено всё), требуя явного разрешения для любой операции.

В архитектуре Consul ACL является критически важным компонентом безопасности, обеспечивающим:
- **Аутентификацию:** Проверку личности субъекта (человека, сервиса или узла) через токены или внешние методы (Kubernetes, OIDC).
- **Авторизацию:** Проверку прав субъекта на выполнение конкретных действий над ресурсами (KV, сервисы, узлы, политики).
- **Изоляцию:** Разделение доступа в рамках [Namespaces и Admin Partitions](./consul_architecture.md).

# Основные концепции

## ACL Токены (Tokens)

Токен — это секретная строка (UUID), которая идентифицирует субъекта в системе.
- **Management Token:** Токен с неограниченными правами (аналог `root`), создается при инициализации (bootstrap).
- **Client Token:** Токен с ограниченным набором прав, привязанный к политикам или ролям.
- **Service Token:** Специализированный токен для конкретного сервиса, часто генерируемый автоматически в Service Mesh.
- **Anonymous Token:** Токен, используемый для запросов без явной аутентификации. Если ACL включены, права анонимного токена определяются политикой с ID `00000000-0000-0000-0000-000000000002`.

## Политики (Policies)

Политики определяют набор правил доступа к ресурсам. Описываются на языке **HCL**.
Ресурсы включают: `key` (KV), `service`, `node`, `agent`, `event`, `query`, `operator`.

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

## Роли (Roles)

Роли позволяют группировать несколько политик в одну сущность, упрощая управление правами для больших групп субъектов. Токен может быть привязан к одной или нескольким ролям.

# Методы аутентификации (Auth Methods)

Методы аутентификации позволяют внешним системам (Kubernetes, OIDC провайдеры) подтверждать личность субъекта и автоматически получать Consul токен.

## Kubernetes Auth Method

Позволяет подам в Kubernetes аутентифицироваться в Consul, используя свой **Service Account JWT**.

- **Механизм:** Consul проверяет предоставленный JWT через Kubernetes API сервер.
- **Binding Rules:** Правила привязки определяют, какие атрибуты Service Account (имя, неймсейс) маппятся на какие роли в Consul.
- **Selector:** Фильтрация по атрибутам, например: `serviceaccount.namespace == "prod"`.

## OIDC Auth Method (Enterprise)

Используется для интерактивного входа пользователей через внешних провайдеров (Okta, GitLab, Google, Keycloak).

- **UI & CLI:** Поддерживает аутентификацию как в веб-интерфейсе, так и через командную строку.
- **Claims Mapping:** Поля из ID-токена провайдера (email, groups) могут использоваться для назначения прав.

## JWT Auth Method

Универсальный метод дляheadless-аутентификации с использованием любых подписанных JWT-токенов. Часто используется для интеграции с CI/CD или внешними KMS.

# Практические примеры политик

Политики в Consul должны следовать принципу наименьших привилегий. Ниже приведены примеры для типовых ролей в инфраструктуре.

## 1. Роль: Администратор платформы (Full Access)
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

## 2. Роль: Разработчик (Team/Service level)
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

## 3. Роль: CI/CD Pipeline (Headless)
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

## 4. Роль: Vault (Backend storage)
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

## 5. Роль: Мониторинг (Prometheus)
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

# Правила привязки (Binding Rules) и Шаблонизация

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

# Жизненный цикл и инициализация

## Включение ACL (Bootstrap)

1. **Конфигурация серверов:**
```hcl
acl {
  enabled = true
  default_policy = "deny"
  enable_token_persistence = true
}
```
2. **Инициализация:**
```bash
consul acl bootstrap
# Сохраните SecretID — это ваш первый Management Token
```

## Управление через CLI

```bash
# Создание политики
consul acl policy create -name "web-reader" -rules @web-policy.hcl

# Создание роли с привязкой политики
consul acl role create -name "web-role" -policy-name "web-reader"

# Создание токена, привязанного к роли
consul acl token create -description "Token for web" -role-name "web-role"
```

# Практические сценарии

## Настройка Kubernetes Auth Method (Helm)

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

# Устранение неполадок (Troubleshooting)

## Ошибка: Permission Denied (403)
- **Проверка токена:** Убедитесь, что токен передается в заголовке `X-Consul-Token` или через флаг `-token`.
- **Инспекция прав:** Проверьте содержимое политик, привязанных к токену:
  ```bash
  consul acl token read -id <token_accessor_id>
  ```
- **Анонимный доступ:** Если запрос выполняется без токена, проверьте права политики для анонимного пользователя.

## Проблемы Auth Methods
- **Kubernetes:** Проверьте доступность API-сервера Kubernetes с серверов Consul и валидность CA-сертификата.
- **OIDC:** Проверьте `Allowed Redirect URIs` в настройках провайдера (должны включать `/oidc/callback`).
- **Логи:** Серверы Consul логируют ошибки аутентификации с деталями (`invalid signature`, `issuer mismatch`). Используйте `-log-level=debug`.

# Дополнительная информация

- **[Архитектура Consul](./consul_architecture.md)** — общие принципы работы Control Plane.
- **[Namespaces и Partitions](./consul_architecture.md#многопользовательская-изоляция-enterprise)** — логическое разделение политик.
- **[Consul Service Mesh](./consul_service_mesh.md)** — использование ACL для Intentions.
- **[Официальная документация: ACL](https://developer.hashicorp.com/consul/docs/security/acl)**.
