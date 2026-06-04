# Подход Zero Trust к управлению секретами

## Определения

**Подход Zero Trust ("нулевого доверия")** в управлении секретами — парадигма безопасности, исходящая из отсутствия "доверенных зон" (внутренних сетей, периметров). Каждый запрос к секрету проходит строгую проверку подлинности и авторизации на основе сильной идентичности и контекста.

Центральный элемент — **брокер доступа** (например, **[HashiCorp Vault](./overview.md)**), который выдает **краткоживущие, минимально привилегированные** учётные данные по запросу.

## Основные концепции

### Принципы Zero Trust для секретов

- **Сильная идентичность:** каждая рабочая нагрузка (приложение, сервис) имеет криптографически подтверждённое удостоверение. Реализуется через **OIDC (OpenID Connect)**, **JWT (JSON Web Token)** или стандарты **SPIFFE (Secure Production Identity Framework for Everyone)** / **SPIRE (SPIFFE Runtime Environment)** через **[методы аутентификации](./concepts.md#методы-аутентификации-и-токены)** Vault.
- **Контекстная проверка:** решение о предоставлении доступа принимается на основе контекста — `namespace` (пространство имен), метки `pod`, среда выполнения, IP-адрес источника.
- **Минимальные привилегии:** предоставление доступа только к необходимым путям и операциям через гранулярные **[политики доступа](./authorization.md)**.
- **Краткоживущие секреты:** секреты и **[токены](./concepts.md#жизненный-цикл-секрета-токены-lease-и-revoke)** имеют короткий TTL (Time to Live), требуют продления (`lease`) и могут быть мгновенно отозваны.
- **Защищённые каналы связи:** обязательное использование TLS (Transport Layer Security) для всех коммуникаций между клиентом и Vault.
- **Policies as Code (Политики как код):** правила доступа описываются декларативно, хранятся в системах контроля версий и применяются автоматически.
- **Непрерывный аудит:** протоколирование всех операций через **[устройства аудита](./concepts.md#аудит-audit-devices)** для обнаружения аномалий и расследования инцидентов.

### Сравнение подходов

| Аспект | Традиционный подход | Zero Trust с Vault |
| :--- | :--- | :--- |
| **Хранение** | `.env`-файлы, Git, долгоживущие ключи | Динамическая выдача через брокер секретов |
| **Срок жизни** | Недели, месяцы или бессрочно | Минуты или часы; автоматическое продление и отзыв |
| **Проверка доступа** | По принадлежности к "доверенной" сети | По идентичности и контексту каждого запроса |
| **Риск компрометации** | Долговременный неконтролируемый доступ | Ущерб ограничен коротким TTL и узкими привилегиями |
| **Ротация** | Ручная, выполняется редко | Автоматическая, выполняется часто |
| **Аудит** | Отсутствует или фрагментарный | Полный журнал операций с хэшированием чувствительных данных |

## Практические сценарии

### Интеграция с Kubernetes

`Pod` подтверждает свою личность через токен `ServiceAccount`, который верифицируется Vault. Подробности — в **[интеграции Vault с Kubernetes](./guides/vault_kubernetes_integration.md)**.

1. **Настройка аутентификации `kubernetes`:** Vault настраивается на доверие OIDC-провайдеру Kubernetes API.
2. **Роль Vault:** связывает конкретный `ServiceAccount` из определенного `namespace` с политиками доступа.

    ```hcl
    vault write auth/kubernetes/role/web \
      bound_service_account_names=web-sa \
      bound_service_account_namespaces=prod \
      policies=web-readonly \
      ttl=30m
    ```

3. **Доставка секрета:** Vault Agent (в режиме sidecar или через **[Vault Injector](./guides/vault_agent/injector.md)**) выполняет аутентификацию, получает динамические учётные данные и записывает их в `tmpfs`-том.

### Динамические секреты для баз данных

Vault генерирует временные учётные данные для баз данных с ограниченным сроком действия вместо использования статических паролей.

```bash
# Настройка плагина базы данных
vault write database/config/postgresql \
    plugin_name=postgresql-database-plugin \
    allowed_roles="readonly-role" \
    connection_url="postgresql://{{username}}:{{password}}@db.example.com:5432/appdb?sslmode=disable" \
    username="vault_admin" \
    password="admin_password"

# Создание роли с динамической генерацией пользователя
vault write database/roles/readonly-role \
    db_name=postgresql \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; \
        GRANT SELECT ON ALL TABLES IN SCHEMA public TO \"{{name}}\";" \
    default_ttl="1h" \
    max_ttl="24h"

# Запрос секрета
vault read database/creds/readonly-role
```

### Шифрование через Transit Engine (Encryption as a Service)

Приложение выполняет криптографические операции через API Vault без локального хранения ключей. Подробности — в **[политике для Transit Engine](./guides/transit-encryption-policies.md)**.

```bash
# Включение движка секретов
vault secrets enable transit
vault write -f transit/keys/payments

# Шифрование данных
vault write transit/encrypt/payments \
    plaintext=$(echo -n "sensitive_data" | base64)

# Дешифрование данных
vault write transit/decrypt/payments \
    ciphertext="vault:v1:..." \
    --format json | jq -r .data.plaintext | base64 -d
```

## Дополнительная информация

### См. также

- **[Обзор HashiCorp Vault](./overview.md)** — базовые возможности системы.
- **[Антипаттерны управления секретами](./common_antipatterns.md)** — типичные ошибки при работе с секретами.
- **[Vault Agent и шаблоны](./guides/vault_agent/basics.md)** — автоматизация доставки секретов.
- **[Sealed Secrets](../Kubernetes/Security/sealed_secrets_overview.md)** — подход к шифрованию секретов для GitOps.
- **[Zero Trust в сетях](../Networking/Concepts/zero_trust_overview.md)** — общие принципы архитектуры нулевого доверия.
