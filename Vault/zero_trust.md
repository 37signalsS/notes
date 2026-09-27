# Подход Zero Trust к управлению секретами

## Определения

**Подход Zero Trust («нулевого доверия»)** в управлении секретами — это стратегия безопасности, основанная на принципе «никогда не доверяй, всегда проверяй». В этой парадигме отсутствует понятие доверенного периметра: каждый запрос к данным должен быть аутентифицирован и авторизован на основе проверяемой идентиности и контекста, независимо от местоположения источника.

**Брокер секретов (Secret Broker)** — центральный компонент архитектуры Zero Trust (например, HashiCorp Vault), который выступает посредником между потребителями и ресурсами, выдавая краткоживущие, динамические и минимально привилегированные учетные данные.

**Security Lifecycle Management (SLM)** — современная надстройка над Zero Trust, обеспечивающая контроль секретов на всех этапах: от обнаружения утечек в исходном коде до безопасной ротации и синхронизации между системами.

## Основные концепции

### Фундаментальные принципы Zero Trust

*   **Сильная идентичность (Strong Identity):** Каждая рабочая нагрузка (приложение, сервис, контейнер, пользователь) имеет криптографически подтвержденное удостоверение. Идентичность проверяется на каждом запросе, а не только при входе в сеть.
    *   **OIDC/JWT-федерация:** Федерация идентичности, позволяющая Vault обмениваться доверием с внешними системами через OIDC-токены без использования статических "Secret Zero".
    *   **SPIFFE/SPIRE:** Использование стандарта SVID (SPIFFE Verifiable Identity Document). Начиная с Vault 1.21, Vault (Enterprise) поддерживает **SPIFFE auth method**: проверку JWT- и X.509-версий SVID по доверенному trust bundle и сопоставление workload ID с политиками Vault. При наличии SPIRE Vault может забирать trust bundle напрямую через SPIRE Federation API. Vault также умеет выпускать сертификаты с SPIFFE URI в SAN (SPIFFE-aware PKI).
*   **Динамическая выдача (Just-in-Time):** Секреты не существуют до момента запроса. Vault генерирует уникальные учетные данные для баз данных или систем "на лету" с ограниченным сроком жизни.
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
| **Secret Zero** | Отсутствует проблема (сетевой периметр) | Исключается через федерацию идентичности |
| **Хранение** | Локальные файлы, переменные окружения | Централизованный брокер с шифрованием |

## Предварительные требования

Перед внедрением Zero Trust с Vault необходимо:

1. **Инфраструктура:** Работающий кластер Vault (single-node для dev/test, Raft/Consul для production) с инициализированным и распечатанным состоянием.
2. **Метод аутентификации:** Выбрать и настроить хотя бы один метод аутентификации для машин (AppRole, Kubernetes, JWT/OIDC) согласно окружению.
3. **Политики:** Написать ACL-политики в HCL с принципом наименьших привилегий. Каждая политика должна ограничивать доступ только к конкретным путям API и методам (`read`, `write`, `list`, `sudo`).
4. **Секреты-движки:** Включить и настроить необходимые движки: `kv-v2` для статических конфигураций, `database` для динамических учетных данных, `pki` для сертификатов, `transit` для шифрования данных, `ssh` для одноразовых паролей.
5. **Аудит:** Включить минимум одно устройство аудита (`file`, `syslog`, `socket`) для фиксации всех операций.
6. **Сеть:** Открыть порт 8200/TCP для API Vault и порт 8201/TCP для внутренней коммуникации реплик (Raft). Запретить публичный доступ к кластеру production без VPN или bastion-хоста.

## Практические сценарии

### Интеграция с Kubernetes через ServiceAccount

Наиболее распространенный сценарий реализации Zero Trust. Pod доказывает свою идентичность через Kubernetes JWT, который Vault проверяет в API Kubernetes.

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

### Динамические учетные данные базы данных

Vault создает уникальный логин и пароль для каждого запроса, которые автоматически отзываются по истечении TTL. Это исключает использование статических паролей в конфигурациях приложений.

**Настройка подключения к базе данных:**

```bash
# Включение движка database
vault secrets enable database

# Настройка соединения с PostgreSQL
vault write database/config/my-postgresql \
    plugin_name=postgresql-database-plugin \
    allowed_roles="payment-app" \
    connection_url="postgresql://{{username}}:{{password}}@db.example.com:5432/app" \
    username="vault_admin" \
    password="vault_admin_password"
# → Success! Data written to: database/config/my-postgresql
```

**Создание конфигурации роли:**

```bash
# Роль генерирует учетные данные с SQL-запросом создания пользователя
vault write database/roles/payment-app \
    db_name=my-postgresql \
    creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}';" \
    revocation_statements="DROP ROLE IF EXISTS \"{{name}}\";" \
    default_ttl="1h" \
    max_ttl="24h"
# → Success! Data written to: database/roles/payment-app
```

**Получение динамических учетных данных:**

```bash
# Запрос учетных данных
vault read database/creds/payment-app
# → Key             Value
# → lease_id        database/creds/payment-app/abc123...
# → lease_duration  3600
# → lease_renewable true
# → password        XyZ7kL9pQ2
# → username        v-token-payment-app-8f3a2c
```

Приложение использует эти учетные данные для подключения. По истечении TTL Vault автоматически удаляет пользователя в базе данных. Для автоматического продления используется [Vault Agent](./guides/vault_agent/basics.md) с авто-аутентификацией.

### Одноразовые пароли SSH

Vault может выдать временные SSH-credentials (пароль или сертификат) для доступа к серверам без статических ключей.

```bash
# Включение движка SSH
vault secrets enable ssh

# Настройка OTP-метода для временных паролей
vault write ssh/roles/one-time-role \
    key_type=otp \
    default_user=ubuntu \
    cidr_list=10.0.0.0/16
# → Success! Data written to: ssh/roles/one-time-role

# Получение OTP-пароля для подключения к целевому хосту
vault write ssh/creds/one-time-role ip=10.0.1.50
# → Key             Value
# → lease_id        ssh/creds/one-time-role/def456...
# → lease_duration  600
# → password        7d92b1c4e6
# → username        ubuntu
```

Сервер-цель должен быть настроен на использование Vault в качестве источника аутентификации (PAM-модуль `vault-ssh-helper`).

### Шифрование данных приложения (Transit Engine)

Transit Engine позволяет шифровать и дешифровать данные на стороне Vault, не выгружая ключи. Приложения передают данные в Vault, получают шифротекст и работают с ним без доступа к plaintext.

```bash
# Включение Transit Engine
vault secrets enable transit

# Создание ключа шифрования (AES-256-GCM)
vault write -f transit/keys/app-encryption-key \
    type=aes256-gcm \
    exportable=false
# → Success! Data written to: transit/keys/app-encryption-key

# Настройка политики для приложения
vault policy write app-transit-policy - <<EOF
path "transit/encrypt/app-encryption-key" {
  capabilities = ["update"]
}
path "transit/decrypt/app-encryption-key" {
  capabilities = ["update"]
}
EOF

# Шифрование данных
vault write transit/encrypt/app-encryption-key \
    plaintext=base64:$(echo -n "sensitive_data_here" | base64)
# → Key             Value
# → ciphertext     vault:v1:abc123...
# → key_version    1

# Дешифрование данных
vault write transit/decrypt/app-encryption-key \
    ciphertext=vault:v1:abc123...
# → Key             Value
# → plaintext      base64:c2Vuc2l0aXZldl9kYXRhX2hlcmU=
```

### Vault Agent Auto-Auth для CI/CD пайплайнов

Использование AppRole с Response Wrapping для безопасной аутентификации CI/CD раннеров без статических SecretID.

**Настройка AppRole в Vault:**

```bash
# Включение AppRole метода аутентификации
vault auth enable approle

# Создание политики для CI/CD
vault policy write ci-pipeline - <<EOF
path "kv-v2/data/ci/*" {
  capabilities = ["read"]
}
path "database/creds/ci-role" {
  capabilities = ["read"]
}
EOF

# Создание AppRole
vault write auth/approle/role/ci-runner \
    token_policies="ci-pipeline" \
    token_ttl=3600 \
    token_max_ttl=7200 \
    secret_id_num_uses=1 \
    secret_id_ttl=86400
# → Success! Data written to: auth/approle/role/ci-runner

# Получение RoleID
vault read auth/approle/role/ci-runner/role-id
# → Key        Value
# → role_id    3a5b7c9d-1234-5678-90ab-cdef12345678

# Запрос SecretID с Response Wrapping
vault write -wrap-ttl=3600 auth/approle/role/ci-runner/secret-id
# → Key             Value
# → wrapping_token  eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
# → wrapping_token_ttl  3600
```

**Использование в CI/CD пайплайне:**

```bash
# Распаковка wrapping_token и вход в Vault
export WRAPPING_TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
vault unwrap -token-only $WRAPPING_TOKEN | vault login -method=approle \
    role_id=3a5b7c9d-1234-5678-90ab-cdef12345678 \
    secret_id=-
# → Success! Logged in with wrapped secret_id.

# Получение секрета
vault kv get kv-v2/ci/database-url
# → ====== Data ======
# → Key             Value
# → password        XyZ7kL9pQ2
# → username        v-token-ci-runner-abc123
# → url             postgresql://v-token-ci-runner-abc123:XyZ7kL9pQ2@db.example.com:5432/ci_db
```

### SPIFFE SVID для микросервисов

Использование Vault в качестве центра сертификации для Mesh-сетей. Vault выпускает SVID, которые используются для взаимной аутентификации (mTLS) между сервисами без участия статических паролей.

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

## Лучшие практики

1. **Отказ от Secret Zero:** Используйте федерацию идентичности (OIDC, Kubernetes, AppRole) вместо стационных токенов аутентификации.
2. **Минимальные TTL:** Настраивайте максимально возможные ограничения по времени жизни секретов. Для баз данных рекомендуется TTL < 1 часа.
3. **Автоматическая ротация:** Настройте автоматическое продление (`renew`) и перевыпуск токенов через Vault Agent. Ручная ротация — источник человеческой ошибки.
4. **Политики версии 2:** Всегда используйте `kv-v2` вместо устаревшего `kv-v1`. `kv-v1` не поддерживает версионирование и ротацию.
5. **Response Wrapping:** Для передачи чувствительных данных (SecretID, корневой токен) используйте Response Wrapping вместо передачи в переменных окружения.
6. **Мультипликативность аудита:** Настройте минимум два устройства аудита (например, `file` + `syslog`) для предотвращения потери журналов.
7. **Изоляция Namespaces:** Используйте Vault Namespaces для разделения сред (dev/staging/prod) и команд.
8. **Хранение ключей:** Мастер-ключ (Unseal Key) храните в Shamir-схеме (минимум 3 из 5 шардов) или используйте Auto-unseal с Transit seal.

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Ошибка 403 Forbidden при получении секрета** | Политика denies доступ к запрошенному пути | Проверить политики с `vault policy read <name>` и `vault capabilities <path> <token>`. Убедиться, что политика содержит нужный путь и метод. |
| **Краткоживущий токен истекает во время операции** | TTL токена меньше времени выполнения задачи | Увеличить `token_ttl` в AppRole/Kubernetes роли или настроить автоматическое продление через Vault Agent (`renew_token`). |
| **"permission denied" при чтении audit log** | Отсутствует capability `sudo` или `root`-токен для чтения audit | Использовать root-токен или токен с политикой, имеющей `capabilities = ["sudo", "read"]` на пути audit. |
| **База данных не создает пользователя** | Неверный `creation_statements` или нет прав у Vault DB-пользователя | Проверить логи audit device, убедиться что `vault_admin` имеет право CREATE ROLE в целевой БД. |
| **SPIFFE auth: trust bundle mismatch** | Trust bundle в Vault не совпадает с корневыми сертификатами SPIRE | Обновить `auth/spiffe/config` с актуальным trust bundle через SPIRE Federation API. |
| **AppRole: secret_id_ttl истек** | SecretID использован после истечения срока действия | Запросить новый SecretID через `vault write auth/approle/role/<role>/secret-id` или использовать Response Wrapping с достаточным TTL. |
| **Lease не продлевается автоматически** | Vault Agent не настроен на автоматическое продление | Проверить конфигурацию Agent: блок `auto_auth` с `method` и `token` в `cache`/`templated_config`. |

## См. также

*   **[Обзор HashiCorp Vault](./overview.md)** — архитектура SLM и движки секретов.
*   **[Антипаттерны управления секретами](./common_antipatterns.md)** — как избежать нарушения принципов Zero Trust.
*   **[Control Groups](./control_groups.md)** — multi-approval для критических операций (Enterprise).
*   **[SSH Secrets Engine](./guides/ssh_secrets_engine.md)** — динамические SSH-ключи и сертификаты.
*   **[Database Secrets Engine](./guides/database_secrets_engine.md)** — динамические учетные данные баз данных.
*   **[PKI/CA продвинутые сценарии](./guides/pki_ca_advanced.md)** — Intermediate CA, ACME, CRL/OCSP.
*   **[Производительность и репликация](./performance_and_replication.md)** — Performance Standby, DR Replication.
*   **[Мониторинг и алертинг](./monitoring_and_alerting.md)** — Prometheus, Grafana, SLO/SLI.
*   **[Анализ audit логов](./audit_log_analysis.md)** — SIEM, forensic, compliance.
*   **[Ротация секретов](./secret_rotation.md)** — стратегии ротации.
*   **[Namespaces](./namespaces.md)** — изоляция сред (Enterprise).
*   **[SLM, Vault Radar, Secrets Sync](./slm_radar_secrets_sync.md)** — Security Lifecycle Management.
*   **[Производительность и тюнинг](./performance_tuning.md)** — оптимизация для high-load.
*   **[Vault API Reference](./vault_api_reference.md)** — REST API и endpoints.
*   **[Cubbyhole и Response Wrapping](./cubbyhole_response_wrapping.md)** — безопасная доставка секретов.
*   **[Стратегии бэкапов и восстановления](./backup_restore_strategies.md)** — RPO/RTO, disaster recovery.
*   [SPIFFE.io](https://spiffe.io/) — стандарт идентификации рабочих нагрузок.
