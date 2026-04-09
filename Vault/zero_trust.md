# Подход Zero Trust к управлению секретами

## Definitions

**Подход Zero Trust ("нулевого доверия")** в управлении секретами — парадигма безопасности, исходящая из отсутствия "доверенных зон" (внутренних сетей и т.п.). Каждый запрос к секрету проходит строгую проверку подлинности и авторизации на основе сильной идентичности и контекста.

Центральный элемент — **брокер доступа** (напр., **[HashiCorp Vault](./overview.md)**), выдающий **краткоживущие, минимально привилегированные** учётные данные по запросу.

## Basic Concepts

### Принципы Zero Trust для секретов

- **Сильная идентичность:** каждая рабочая нагрузка (приложение, сервис) имеет криптографически подтверждённое удостоверение (OIDC/JWT, SPIFFE/SPIRE), реализуемое через **[методы аутентификации](./concepts.md#методы-аутентификации-и-токены)** Vault.
- **Контекстная проверка:** доступ определяется контекстом — `namespace`, метки `pod`, среда выполнения, IP источника.
- **Минимальные привилегии:** доступ только к нужным путям и операциям через **[политики доступа](./concepts.md#политики-доступа-policies)**.
- **Краткоживущие секреты:** секреты и **[токены](./concepts.md#жизненный-цикл-секрета-токены-lease-и-revoke)** имеют короткий TTL, требуют продления (`lease`) и могут быть отозваны мгновенно.
- **Защищённые каналы:** коммуникация клиент—Vault через TLS.
- **Policies as Code:** правила доступа описываются декларативно, хранятся в VCS, применяются автоматически.
- **Непрерывный аудит:** все операции протоколируются **[устройствами аудита](./concepts.md#аудит-audit-devices)** для обнаружения аномалий.

### Сравнение подходов

| Аспект | Традиционный подход | Zero Trust с Vault |
| :--- | :--- | :--- |
| **Хранение** | `.env`, Git, долгоживущие ключи | Динамическая выдача через брокер секретов |
| **Срок жизни** | Недели/месяцы/бессрочно | Минуты/часы; авто-продление и отзыв |
| **Проверка доступа** | По принадлежности к "доверенной" сети | По идентичности и контексту каждого запроса |
| **Компрометация** | Долговременный неконтролируемый доступ | Ущерб ограничен TTL и узкими привилегиями |
| **Ротация** | Ручная, редкая | Автоматическая, частая |
| **Аудит** | Отсутствует/фрагментарный | Полный журнал операций с хэшированием чувствительных данных |

## Practical Scenarios

### Интеграция с Kubernetes

Pod подтверждает личность через токен `ServiceAccount`, верифицируемый Vault. Подробности — в **[интеграции Vault с Kubernetes](./guides/vault_kubernetes_integration.md)**.

1. **Настройка аутентификации `kubernetes`:** Vault доверяет OIDC-провайдеру Kubernetes API.
2. **Роль Vault:** связывает `ServiceAccount` из `namespace` с политиками.

    ```hcl
    vault write auth/kubernetes/role/web \
      bound_service_account_names=web-sa \
      bound_service_account_namespaces=prod \
      policies=web-readonly \
      ttl=30m
    ```

3. **Доставка секрета:** Vault Agent (sidecar или через **[Vault Injector](./guides/vault_agent/injector.md)**) аутентифицируется, получает динамические учётные данные для БД и записывает в `tmpfs`-том.

### Динамические секреты для баз данных

Vault генерирует временные учётные данные БД с ограниченным TTL вместо статических паролей.

```bash
vault write database/config/postgresql \
    plugin_name=postgresql-database-plugin \
    allowed_roles="readonly-role" \
    connection_url="postgresql://{{username}}:{{password}}@db.example.com:5432/appdb?sslmode=disable" \
    username="vault_admin" \
    password="admin_password"

vault write database/roles/readonly-role \
    db_name=postgresql \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; \
        GRANT SELECT ON ALL TABLES IN SCHEMA public TO \"{{name}}\";" \
    default_ttl="1h" \
    max_ttl="24h"

vault read database/creds/readonly-role
```

Преимущества: уникальные credentials на запрос, автоудаление по TTL, полный аудит.

### Шифрование через Transit Engine

Приложение шифрует данные через Vault без локального хранения ключей. Детали — в **[политике для Transit Engine](./guides/transit-encryption-policies.md)**.

```bash
vault secrets enable transit
vault write -f transit/keys/payments

vault write transit/encrypt/payments \
    plaintext=$(echo -n "sensitive_data" | base64)

vault write transit/decrypt/payments \
    ciphertext="vault:v1:..." \
    --format json | jq -r .data.plaintext | base64 -d
```

Приложение не имеет доступа к ключам — только к операциям шифрования/дешифрования через API.

## Additional Information

Принципы Zero Trust для секретов дополняются подходами **[Sealed Secrets](../Kubernetes/Security/sealed_secrets_overview.md)** (шифрование для конкретного кластера), разбором типовичных ошибок в **[антипаттернах](./common_antipatterns.md)** и автоматизацией доставки через **[Vault Agent и шаблоны](./guides/vault_agent/basics.md)**. Полный чеклист лучших практик — **[18-point secrets management checklist](https://www.hashicorp.com/en/blog/the-18-point-secrets-management-checklist)** от HashiCorp.
