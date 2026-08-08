# Подход Zero Trust к управлению секретами

## Определения

**Подход Zero Trust («нулевого доверия»)** в управлении секретами — это стратегия безопасности, основанная на принципе «никогда не доверяй, всегда проверяй». В этой парадигме отсутствует понятие доверенного периметра: каждый запрос к данным должен быть аутентифицирован и авторизован на основе проверяемой идентичности и контекста, независимо от местоположения источника.

**Брокер секретов (Secret Broker)** — центральный компонент архитектуры Zero Trust (например, HashiCorp Vault), который выступает посредником между потребителями и ресурсами, выдавая краткоживущие, динамические и минимально привилегированные учетные данные.

**Security Lifecycle Management (SLM)** — современная надстройка над Zero Trust, обеспечивающая контроль секретов на всех этапах: от обнаружения утечек в исходном коде до безопасной ротации и синхронизации между облаками.

## Основные концепции

### Фундаментальные принципы Zero Trust

*   **Сильная идентичность (Strong Identity):** Каждая рабочая нагрузка (приложение, сервис, ИИ-агент) имеет криптографически подтвержденное удостоверение.
    *   **WIF (Workload Identity Federation):** Федерация идентичности, позволяющая Vault обмениваться доверием с облачными провайдерами (AWS, GCP, Azure) через OIDC-токены без использования статических "Secret Zero".
    *   **SPIFFE/SPIRE:** Использование стандарта SVID (SPIFFE Verifiable Identity Document). Начиная с Vault 1.21, Vault (Enterprise) поддерживает **SPIFFE auth method**: проверку JWT- и X.509-версий SVID по доверенному trust bundle и сопоставление workload ID с политиками Vault. При наличии SPIRE Vault может забирать trust bundle напрямую через SPIRE Federation API. Vault также умеет выпускать сертификаты с SPIFFE URI в SAN (SPIFFE-aware PKI).
*   **Динамическая выдача (Just-in-Time):** Секреты не существуют до момента запроса. Vault генерирует уникальные учетные данные для баз данных или облаков "на лету" с ограниченным сроком жизни.
*   **Минимальные привилегии (Least Privilege):** Доступ предоставляется только к тем путям API, которые необходимы для выполнения конкретной задачи, через гранулярные [ACL-политики](./authorization.md).
*   **Контекстная проверка (Contextual Awareness):** Решение о доступе принимается с учетом метаданных запроса: IP-адрес, принадлежность к Kubernetes Namespace, время запроса, использование MFA.
*   **Краткоживущие секреты (Short-lived Secrets):** Все токены и секреты имеют TTL (Time To Live). По истечении срока аренды ([Lease](./concepts.md#жизненный-цикл-токены-lease-и-revoke)) доступ отзывается автоматически.
*   **Непрерывный аудит и контроль:** Каждое действие записывается в [устройства аудита](./concepts.md#аудит-и-события-vault-events). Использование **Vault Radar** позволяет проактивно находить секреты, попавшие в открытый доступ (Git, Slack), нарушающие принципы Zero Trust.

### Сравнение архитектурных подходов

| Характеристика | Традиционная модель | Модель Zero Trust (с Vault) |
| :--- | :--- | :--- |
| **Доверие** | Неявное (внутри сети/периметра) | Явное (проверка каждого запроса) |
| **Идентификация** | По IP-адресу или сетевому сегменту | По криптографической идентичности (Identity Store) |
| **Секреты** | Статические, долгоживущие (.env, Git) | Динамические, эфемерные (JIT) |
| **Ротация** | Редкая, часто ручная | Автоматическая, программная |
| **Аудит** | Фрагментарный (логи приложения) | Централизованный, неизменяемый (Audit Logs) |
| **Управление** | Децентрализованное (каждый сервис сам по себе) | Централизованное SLM (Hub-and-spoke) |

## Практические сценарии

### Интеграция с Kubernetes через ServiceAccount

Наиболее распространенный сценарий реализации Zero Trust в облачных средах. Pod доказывает свою идентичность через Kubernetes JWT, который Vault проверяет в API Kubernetes.

```bash
# Определение роли в Vault для Kubernetes
vault write auth/kubernetes/role/payment-app \
    bound_service_account_names=payment-sa \
    bound_service_account_namespaces=production \
    token_policies=payment-policy \
    ttl=1h
# → Success! Data written to: auth/kubernetes/role/payment-app
```

Приложение использует sidecar-контейнер (Vault Agent) для автоматического получения секрета, который монтируется в `tmpfs` (память), не попадая на диск. Подробные сценарии внедрения агента описаны в [Vault Agent Sidecar](./guides/vault_agent/sidecar_pattern.md) и [Vault Agent Injector](./guides/vault_agent/injector.md).

### Федерация идентичности (WIF) для облачных нагрузок

Исключение необходимости хранения долгоживущих AWS Access Keys в Vault. Vault использует OIDC-токен своей сущности для получения временных прав в облаке через соответствующую роль метода аутентификации (AWS, Azure, GCP).

1.  Vault запрашивает временные credentials у AWS через STS (Security Token Service) или OIDC.
2.  Облако проверяет доверие к Vault через OIDC Discovery (настроенный IAM Identity Provider).
3.  Vault выдает приложению динамический секрет, токен которого привязан к WIF-роли.

```bash
# Настройка WIF для AWS: роль привязывает Vault OIDC-сущность к IAM-роли
vault write auth/aws/role/rds-admin \
    auth_type=iam \
    bound_iam_principal_arn="arn:aws:iam::123456789012:role/app-role" \
    token_policies=rds-admin-policy \
    ttl=1h
# → Success! Data written to: auth/aws/role/rds-admin
```

### SPIFFE SVID для микросервисов

Использование Vault в качестве центра сертификации для Mesh-сетей. Vault выпускает SVID, которые используются для взаимной аутентификации (mTLS) между сервисами без участия статических паролей. Для этого используются два пути: выпуск сертификатов с SPIFFE URI в SAN через PKI secrets engine и прием SVID от SPIRE через SPIFFE auth method.

```bash
# Включение SPIFFE auth method (Enterprise, Vault 1.21+)
vault auth enable spiffe
# → Success! Enabled spiffe auth method at: spiffe/

# Настройка доверенного trust bundle (SPIRE Federation API или статический bundle)
vault write auth/spiffe/config url=https://spire-server.example:8081/bundle

# Создание роли: сопоставление workload ID с политиками Vault
vault write auth/spiffe/role/payment-app \
    workload_id_patterns="payment/*" \
    token_policies=payment-policy
# → Success! Data written to: auth/spiffe/role/payment-app
```

SPIFFE-aware PKI для взаимного mTLS между сервисами:
```bash
# Выпуск сертификата с SPIFFE URI SAN (SPIFFE-aware PKI)
vault write pki/issue/payment-role \
    common_name="spiffe://cluster.local/ns/prod/sa/app1" \
    uri_sans="spiffe://cluster.local/ns/prod/sa/app1"
```

## Дополнительная информация

*   **[Обзор HashiCorp Vault](./overview.md)** — архитектура SLM.
*   **[Антипаттерны управления секретами](./common_antipatterns.md)** — как избежать нарушения принципов Zero Trust.
*   **[SPIFFE.io](https://spiffe.io/)** — стандарт идентификации рабочих нагрузок.
