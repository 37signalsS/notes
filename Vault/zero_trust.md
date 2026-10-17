# Подход Zero Trust к управлению секретами

**Актуально для:** Vault 2.x (latest 2.2.0; ветка 1.21.x поддерживается)

## Определения

**Подход Zero Trust («нулевого доверия»)** в управлении секретами — это стратегия безопасности, основанная на принципе «никогда не доверяй, всегда проверяй». В этой парадигме отсутствует понятие доверенного периметра: каждый запрос к данным должен быть аутентифицирован и авторизован на основе проверяемой идентиности и контекста, независимо от местоположения источника.

**Брокер секретов (Secret Broker)** — центральный компонент архитектуры Zero Trust (например, HashiCorp Vault), который выступает посредником между потребителями и ресурсами, выдавая краткоживущие, динамические и минимально привилегированные учетные данные.

**Security Lifecycle Management (SLM)** — современная надстройка над Zero Trust, обеспечивающая контроль секретов на всех этапах: от обнаружения утечек в исходном коде до безопасной ротации и синхронизации между системами.

## Основные концепции

### Фундаментальные принципы Zero Trust

*   **Сильная идентичность (Strong Identity):** Каждая рабочая нагрузка (приложение, сервис, контейнер, пользователь) имеет криптографически подтвержденное удостоверение. Идентичность проверяется на каждом запросе, а не только при входе в сеть.
    *   **OIDC/JWT-федерация:** Федерация идентичности, позволяющая Vault обмениваться доверием с внешними системами через OIDC-токены без использования статических "Secret Zero".
    *   **SPIFFE/SPIRE:** Использование стандарта SVID (SPIFFE Verifiable Identity Document). Начиная с Vault 1.21 (в т.ч. Vault 2.x, Enterprise), поддерживается **SPIFFE auth method**: проверка JWT- и X.509-версий SVID по доверенному trust bundle и сопоставление workload ID с политиками Vault. При наличии SPIRE Vault может забирать trust bundle напрямую через SPIRE Federation API. Vault также умеет выпускать сертификаты с SPIFFE URI в SAN (SPIFFE-aware PKI).
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
# Определение роли в Vault для Kubernetes (audience обязательно с Vault 1.21+)
vault write auth/kubernetes/role/payment-app \
    bound_service_account_names=payment-sa \
    bound_service_account_namespaces=production \
    token_policies=payment-policy \
    audience="vault" \
    ttl=1h
# → Success! Data written to: auth/kubernetes/role/payment-app
```

**Валидация:**

```bash
# Проверка ролей Kubernetes auth
vault list auth/kubernetes/role
# → Keys: payment-app

# Проверка конфигурации
vault read auth/kubernetes/config
# → Key             Value
# → kubernetes_host  https://10.96.0.1:443
```

**Очистка:**

```bash
vault delete auth/kubernetes/role/payment-app
vault auth disable kubernetes
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

**Валидация:**

```bash
# Проверка активных аренд (leases) для роли
vault list sys/leases/lookup/database/creds/payment-app
# → Keys: abc123-def456-...

# Проверка статуса роли
vault read database/roles/payment-app
# → Key          Value
# → db_name      my-postgresql
# → default_ttl  1h
# → max_ttl      24h
```

**Очистка:**

```bash
vault delete database/roles/payment-app
vault delete database/config/my-postgresql
vault secrets disable database
```

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

**Валидация:**

```bash
# Проверка статуса SSH secrets engine
vault secrets list | grep ssh
# → ssh/  SSH

# Проверка роли
vault read ssh/roles/one-time-role
# → Key        Value
# → key_type   otp
# → default_user  ubuntu
```

**Очистка:**

```bash
vault delete ssh/roles/one-time-role
vault secrets disable ssh
```

### Шифрование данных приложения (Transit Engine)

Transit Engine позволяет шифровать и дешифровать данные на стороне Vault, не выгружая ключи. Приложения передают данные в Vault, получают шифротекст и работают с ним без доступа к plaintext.

```bash
# Включение Transit Engine
vault secrets enable transit

# Создание ключа шифрования (AES-256-GCM)
vault write -f transit/keys/app-encryption-key \
    type=aes256-gcm96 \
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

Подробные сценарии политик доступа, типы ключей, ротация и тroubleshooting описаны в **[Политики Transit Engine](./guides/transit-encryption-policies.md)**.

**Валидация:**

```bash
# Проверка ключа и его типа
vault read transit/keys/app-encryption-key
# → Key              Value
# → type             aes256-gcm96
# → exportable       false
# → allow_plaintext_backup  false

# Проверка политики доступа
vault read sys/policy/app-transit-policy
```

**Очистка:**

```bash
vault policy delete app-transit-policy
vault delete transit/keys/app-encryption-key
vault secrets disable transit
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

# vault unwrap не имеет флага -token-only; используйте -field для извлечения значения
SECRET_ID=$(vault unwrap -field=secret_id "$WRAPPING_TOKEN")

# Вход в Vault с полученным secret_id
vault login -method=approle \
    role_id=3a5b7c9d-1234-5678-90ab-cdef12345678 \
    secret_id="$SECRET_ID"
# → Success! Logged in with wrapped secret_id.

# Получение секрета
vault kv get kv-v2/ci/database-url
# → ====== Data ======
# → Key             Value
# → password        XyZ7kL9pQ2
# → username        v-token-ci-runner-abc123
# → url             postgresql://v-token-ci-runner-abc123:XyZ7kL9pQ2@db.example.com:5432/ci_db
```

**Валидация:**

```bash
# Проверка созданной политики
vault policy read ci-pipeline
# → path "kv-v2/data/ci/*" { capabilities = ["read"] }

# Проверка роли AppRole
vault read auth/approle/role/ci-runner
# → Key            Value
# → token_ttl      1h
# → token_max_ttl  2h
# → secret_id_num_uses  1
```

**Очистка:**

```bash
vault delete auth/approle/role/ci-runner
vault policy delete ci-pipeline
vault auth disable approle
```

**Рекомендация для SRE/DevOps:** используйте `token_type=batch` в AppRole для CI/CD-пайплайнов — batch-токены не сохраняются в индексе Vault, что снижает нагрузку на хранилище и уменьшает поверхность аудита. Добавьте `secret_id_bound_cidrs` для ограничения диапазонов IP, с которых runner может аутентифицироваться.

### SPIFFE SVID для микросервисов

Vault выступает **потребителем** SVID (а не эмитентом): SPIFFE-контроллер (SPIRE или сервисная сеть) генерирует SVID для рабочей нагрузки, а Vault проверяет его по доверенному trust bundle. Это позволяет использовать единую identity-инфраструктуру для bare metal, VM и мульти-облачных кластеров без привязки к платформе.

Для JWT-SVID дополнительно требуется передать `Authorization: Bearer <svid-jwt>` в заголовке запроса — при включении метода необходимо добавить `-passthrough-request-headers="Authorization"`:

```bash
# Включение SPIFFE auth method (Enterprise, Vault 2.x)
vault auth enable -passthrough-request-headers="Authorization" spiffe
# → Success! Enabled spiffe auth method at: spiffe/

# Настройка trust bundle и trust domain
vault write auth/spiffe/config \
    trust_domain="example.org" \
    profile="https_spiffe_bundle" \
    endpoint_url="https://spire-server.example.org:8443" \
    endpoint_spiffe_id="spiffe://example.org/spire-federation" \
    audience="vault.example.org"
# → Success! Data written to: auth/spiffe/config

# Создание роли: сопоставление workload ID с политиками Vault
vault write auth/spiffe/role/payment-app \
    workload_id_patterns="ns/prod/sa/payment-service" \
    token_policies="payment-policy" \
    token_ttl="1h"
# → Success! Data written to: auth/spiffe/role/payment-app
```

**Обновление trust bundle:** Vault кэширует trust bundle и обновляет его периодически (интервал по умолчанию — 1 час, либо из refresh hint в bundle). Активный узел кластера выполняет загрузку и обновление от имени всех узлов. Для принудительного обновления:

```bash
vault write auth/spiffe/config
# → Success! Data written to: auth/spiffe/config
```

**Валидация:**

```bash
# Проверка конфигурации и статуса trust bundle
vault read auth/spiffe/config
# → Key              Value
# → trust_domain     example.org
# → profile          https_spiffe_bundle
# → last_refreshed   2026-10-15T12:00:00Z

# Проверка ролей
vault list auth/spiffe/role
# → Keys: payment-app

# Проверка политик, назначенных ролю
vault read auth/spiffe/role/payment-app
# → token_policies  [payment-policy]
```

**Очистка (cleanup):**

```bash
# Удаление ролей и конфигурации
vault delete auth/spiffe/role/payment-app
vault delete auth/spiffe/config

# Отключение метода аутентификации
vault auth disable spiffe
```

Для X.509-SVID (mTLS) Vault выпускает сертификаты с SPIFFE URI в SAN через PKI:

```bash
# Выпуск сертификата с SPIFFE URI SAN (SPIFFE-aware PKI)
vault write pki/issue/payment-role \
    common_name="payment-service.example.org" \
    uri_sans="spiffe://example.org/ns/prod/sa/payment-service"
# → Key          Value
# → serial_number  12:34:56:78:90:AB:CD:EF:00:12:34:56:78:90:AB:CD:EF:00
# → certificate    -----BEGIN CERTIFICATE-----
# → ...

# Валидация сертификата
openssl x509 -in /tmp/payment.crt -text -noout | grep -A2 "Subject Alternative Name"
# → URI:spiffe://example.org/ns/prod/sa/payment-service
```

**Важно:** если reverse proxy или load balancer завершает TLS перед Vault, для X.509-SVID необходимо настроить `x_forwarded_for_client_cert_header` на listener-уровне и обеспечить mTLS между прокси и Vault (см. [документацию](https://developer.hashicorp.com/vault/docs/auth/spiffe/spiffe#load-balancer-and-proxy-considerations)).

## Операции и команды

Справочная таблица ключевых команд для эксплуатации Zero Trust с Vault:

| Действие | Команда | Описание |
| :--- | :--- | :--- |
| Проверка статуса | `vault status` | Проверка Seal/Unseal статуса и версии |
| Просмотр аренд (leases) | `vault list sys/leases/lookup/<path>` | Список активных аренд для конкретного пути |
| Принудительный revoke | `vault lease revoke -f <lease_id>` | Немедленный отзыв конкретной аренды |
| Проверка политики | `vault policy read <name>` | Чтение ACL-политики HCL |
| Проверка capabilities | `vault capabilities <path>` | Проверка доступа токена к пути |
| Список включенных auth | `vault auth list` | Список включенных методов аутентификации |
| Список включенных secrets | `vault secrets list` | Список включенных движков секретов |
| Отзыв токена | `vault token revoke -f <token>` | Немедленный отзыв токена пользователя |
| Просмотр audit-устройств | `vault audit list` | Список включенных устройств аудита |
| Force-повторное сканирование | `vault write sys/raw/...` | Прямой доступ к raw-хранилищу (root только) |

**SRE/DevOps:** для автоматизации используйте Terraform-провайдер Vault (`vault` provider) — все роли, политики и конфигурации аутентификации могут быть описаны как код. Примеры: [Vault AppRole Terraform](https://registry.terraform.io/providers/hashicorp/vault/latest/docs/resources/approle_auth_backend_role), [Vault Kubernetes Auth](https://registry.terraform.io/providers/hashicorp/vault/latest/docs/resources/kubernetes_auth_backend_role); общий обзор и предупреждения по state — во [внутреннем руководстве](./guides/terraform-integration.md).

## Лучшие практики

1. **Отказ от Secret Zero:** Используйте федерацию идентичности (OIDC, Kubernetes, AppRole) вместо стационных токенов аутентификации.
2. **Минимальные TTL:** Настраивайте максимально возможные ограничения по времени жизни секретов. Для баз данных рекомендуется TTL < 1 часа.
3. **Автоматическая ротация:** Настройте автоматическое продление (`renew`) и перевыпуск токенов через Vault Agent. Ручная ротация — источник человеческой ошибки.
4. **Политики версии 2:** Всегда используйте `kv-v2` вместо устаревшего `kv-v1`. `kv-v1` не поддерживает версионирование и ротацию. Подробно — [KV v2](./guides/kv-v2.md).
5. **Response Wrapping:** Для передачи чувствительных данных (SecretID, корневой токен) используйте Response Wrapping вместо передачи в переменных окружения.
6. **Мультипликативность аудита:** Настройте минимум два устройства аудита (например, `file` + `syslog`) для предотвращения потери журналов.
7. **Изоляция Namespaces:** Используйте Vault Namespaces для разделения сред (dev/staging/prod) и команд.
8. **Хранение ключей:** Мастер-ключ (Unseal Key) храните в Shamir-схеме (минимум 3 из 5 шардов) или используйте Auto-unseal с Transit seal.

**Контекст SRE / sysadmin:**

9.  **Мониторинг и алертинг:** Настройте метрики Vault через [Prometheus endpoint](./guides/monitoring_and_alerting.md) (`vault.sys.`) с алертами на: рост количества активных токенов (> порог), время отклика audit device (> 1 сек), частота отзыва токенов (anomaly detection), количество неудачных логинов (brute-force detection).
10. **Аудит нарушений Zero Trust:** Регулярно сканируйте audit-логи на наличие запросов с `token_ttl > 24h` (нарушение минимальных TTL) и доступ к `sys/raw/` (обход политик). Используйте [Vault Radar](./guides/slm_radar_secrets_sync.md) для поиска hardcoded-секретов в Git/артефактах CI.
11. **Disaster Recovery:** Для production-кластеров используйте Integrated Storage (Raft) с минимум 3 узлами + 1 Performance Standby. Настройте автоматические снапшоты хранилища с RPO ≤ 1h. Резервные копии unseal key храните в разных зонах доступности.
12. **Hardening ОС:** Vault server запускается с `user=vault` (не root), `LimitMEMLOCK=infinity`, `disable_mlock=true` в контейнерах. Отключите swap на ноде. Используйте `chroot`/контейнерные security context (`runAsNonRoot`, `readOnlyRootFilesystem`, `allowPrivilegeEscalation=false`).
13. **Rate limiting:** Настройте `default_lease_ttl` и `max_lease_ttl` на уровне системы, а также используйте [Control Groups](./guides/control_groups.md) для критических операций (sudo, root-политики) — требует approval от второго оператора.

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Ошибка 403 Forbidden при получении секрета** | Политика denies доступ к запрошенному пути | Проверить политики с `vault policy read <name>` и `vault capabilities <path> <token>`. Убедиться, что политика содержит нужный путь и метод. |
| **Краткоживущий токен истекает во время операции** | TTL токена меньше времени выполнения задачи | Увеличить `token_ttl` в AppRole/Kubernetes роли или настроить автоматическое продление через Vault Agent (`renew_token`). |
| **"permission denied" при чтении audit log** | Отсутствует capability `sudo` или `root`-токен для чтения audit | Использовать root-токен или токен с политикой, имеющей `capabilities = ["sudo", "read"]` на пути audit. |
| **База данных не создает пользователя** | Неверный `creation_statements` или нет прав у Vault DB-пользователя | Проверить логи audit device, убедиться что `vault_admin` имеет право CREATE ROLE в целевой БД. |
| **SPIFFE auth: trust bundle mismatch** | Trust bundle в Vault не совпадает с корневыми сертификатами SPIRE, либо `profile` не поддерживает выбранный тип SVID | Обновить `auth/spiffe/config` с актуальным trust bundle через SPIRE Federation API; для JWT-SVID используйте `profile="https_spiffe_bundle"` или `profile="static"` с JWKS. |
| **SPIFFE JWT-SVID: 403 на login** | Отсутствует `Authorization` в `passthrough-request-headers` | Перенастроить метод: `vault auth tune -passthrough-request-headers="Authorization" spiffe`. |
| **Kubernetes auth: audience mismatch** | Роль не содержит `audience` (обязательно с Vault 1.21+) или SA токен имеет другую аудиторию | Добавить `audience="vault"` в роль и/или собрать токен с `audience: vault` через TokenRequest API. |
| **Vault 2.x: invalid path (400)** | Запрос содержит `/../`, `/./`, `//` — Vault 2.0+ требует canonicalized пути | Использовать очищенный путь без относительных ссылок. |
| **AppRole: secret_id_ttl истек** | SecretID использован после истечения срока действия | Запросить новый SecretID через `vault write auth/approle/role/<role>/secret-id` или использовать Response Wrapping с достаточным TTL. |
| **Lease не продлевается автоматически** | Vault Agent не настроен на автоматическое продление | Проверить конфигурацию Agent: блок `auto_auth` с `method` и `token` в `cache`/`templated_config`. |

## См. также

*   **[Обзор HashiCorp Vault](./overview.md)** — архитектура SLM и движки секретов.
*   **[Антипаттерны управления секретами](./common_antipatterns.md)** — как избежать нарушения принципов Zero Trust.
*   **[Control Groups](./guides/control_groups.md)** — multi-approval для критических операций (Enterprise).
*   **[SSH Secrets Engine](./guides/ssh_secrets_engine.md)** — динамические SSH-ключи и сертификаты.
*   **[Database Secrets Engine](./guides/database_secrets_engine.md)** — динамические учетные данные баз данных.
*   **[PKI/CA продвинутые сценарии](./guides/pki_ca_advanced.md)** — Intermediate CA, ACME, CRL/OCSP.
*   **[Производительность и репликация](./guides/performance_and_replication.md)** — Performance Standby, DR Replication.
*   **[Мониторинг и алертинг](./guides/monitoring_and_alerting.md)** — Prometheus, Grafana, SLO/SLI.
*   **[Анализ audit логов](./guides/audit_log_analysis.md)** — SIEM, forensic, compliance.
*   **[Ротация секретов](./guides/secret_rotation.md)** — стратегии ротации.
*   **[Namespaces](./guides/namespaces.md)** — изоляция сред (Enterprise).
*   **[SLM, Vault Radar, Secrets Sync](./guides/slm_radar_secrets_sync.md)** — Security Lifecycle Management.
*   **[Производительность и тюнинг](./guides/performance_tuning.md)** — оптимизация для high-load.
*   **[Vault API Reference](./guides/vault_api_reference.md)** — REST API и endpoints.
*   **[Cubbyhole и Response Wrapping](./guides/cubbyhole_response_wrapping.md)** — безопасная доставка секретов.
*   **[Стратегии бэкапов и восстановления](./guides/backup_restore_strategies.md)** — RPO/RTO, disaster recovery.
*   [SPIFFE.io](https://spiffe.io/) — стандарт идентификации рабочих нагрузок.
