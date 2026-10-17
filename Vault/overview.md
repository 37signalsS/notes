# Обзор HashiCorp Vault

**Актуально для:** Vault 2.x (latest 2.1.2; ветка 1.21.x поддерживается)

## Предварительные требования

Перед развёртыванием и эксплуатацией кластера Vault необходимо подготовить инфраструктуру на уровне ОС и сети. Подробные пошаговые инструкции — в [Руководстве по установке](./guides/vault_installation.md).

* **Vault:** бинарник версии 2.x (или 1.16+ для SLM-фич). Минимальная версия для базовых функций — 1.13+. CLI должен соответствовать версии сервера (разница в minor-версии допустима, major — нет).
* **TLS:** Production-развёртывание требует TLS для всех соединений — API (8200), UI, межузловая коммуникация Raft (8201). Используйте `tls_cert_file`/`tls_key_file` и `tls_client_ca_file` для mTLS.
* **Audit logging:** включённый audit device (File или Syslog) обязателен для compliance и troubleshooting. Минимум два устройства на кластер для отказоустойчивости. Подробности — в [Анализ audit логов](./guides/audit_log_analysis.md).
* **Filesystem:** отдельный volume для данных Raft (`/opt/vault/data`; права `700`, владелец `vault:vault`), выделенный том для audit-логов (`/var/log/vault/`; права `0640`).
* **System limits:** `ulimit -n` ≥ 65536, `vm.max_map_count` ≥ 65536, `swapoff` (swap запрещает попадание секретов на диск).
* **CAP_IPC_LOCK:** `setcap cap_ipc_lock=+eip` на бинарнике и `LimitMEMLOCK=infinity` в systemd для `mlock` (предотвращает выгрузку ключей в swap). В контейнерах Vault 2.0.2+ не требует `CAP_IPC_LOCK` — используйте `disable_mlock = true`.
* **Минимальные ресурсы:** single-node — 2 vCPU, 4 ГБ RAM, 10 ГБ SSD; HA-кластер — 4+ vCPU, 8+ ГБ RAM, 100+ ГБ SSD на узел. Дисковый объём зависит от audit volume и KV-версий.
* **Сеть:** порт 8200/TCP (API/UI) и 8201/TCP (Raft internal); доступ к Kubernetes API (для K8s auth) или OIDC-провайдеру (для JWT auth).

## Определения

**HashiCorp Vault** — это централизованная система для безопасного управления жизненным циклом секретов (Security Lifecycle Management, SLM). Она предназначена для защиты чувствительных данных, таких как пароли, API-ключи, токены, сертификаты и ключи шифрования. Vault предоставляет единую точку управления для всей инфраструктуры, обеспечивая строгую идентификацию, гранулярную авторизацию и детальный аудит всех операций.

**Security Lifecycle Management (SLM)** — современный подход Vault (версии 1.16+, 2.0+), выходящий за рамки простого храниения секретов. SLM включает в себя обнаружение утечек в коде (Vault Radar), централизованное хранение, автоматическую ротацию и синхронизацию секретов с внешними корпоративными системами управления ключами. Vault выступает центральным хранилищем (system of record) для чувствительных данных: паролей, сертификатов, ключей и токенов, а также идентификаций машин и людей, работающих с ними.

## Проблема: Secret Sprawl (Расползание секретов)

Основная задача Vault — решение проблемы **Secret Sprawl** (неконтролируемое распространение секретов), когда чувствительные данные оказываются рассредоточены по всей инфраструктуре:
*   **Локальные машины инженеров:** SSH-ключи, файлы конфигурации Kubernetes (`kubeconfig`), учётные данные внешних сервисов.
*   **Системы документации:** Plain-text пароли на страницах Confluence или в общих файлах (Keepass).
*   **CI/CD переменные:** Учетные данные Docker Registry и SSH-ключи в настройках GitLab CI или Jenkins.
*   **Исходный код и Git:** API-ключи и учётные данные БД, жестко прописанные (hardcoded) в коде или конфигурационных файлах, попадающие в историю коммитов.

### Последствия Secret Sprawl

1.  **Отсутствие видимости:** Невозможно узнать, у кого есть доступ к конкретным учетным данным и где они используются.
2.  **Отсутствие аудита:** Нет возможности отследить, кто и когда использовал секрет. При компрометации невозможно определить источник утечки.
3.  **Радиус поражения (Blast Radius):** Компрометация одного секрета даёт злоумышленнику доступ ко всем системам, где этот секрет используется.
4.  **Сложность ротации:** Замена скомпрометированного ключа превращается в катастрофу, так как нужно вручную обновить его во всех разрозненных системах.

## Архитектура и основные концепции

### Архитектура Vault

Vault имеет **плагинную архитектуру (Pluggable Architecture)**, состоящую из ядра и подключаемых плагинов:

1.  **Vault Core (Ядро):** Управляет логикой работы, безопасностью и связью между компонентами. Ядро включает механизм **Barrier** (криптографический слой шифрования/дешифрования данных), обработку API-запросов и координацию плагинов. Доступ к данным возможен **только** через Core — прямой доступ к бэкенду обходит Vault невозможен.
2.  **Vault API:** Весь доступ к Vault (через CLI, UI или SDK) осуществляется исключительно через HTTP API на порту 8200.
3.  **Плагины (Plugins):**
    *   **Secret Engines:** Реализуют логику хранения или динамической генерации секретов.
    *   **Auth Methods:** Отвечают за идентификацию пользователей и машин, выступая **посредником доверия (Trust Broker)** между Vault и внешними поставщиками идентичности (K8s, LDAP, OIDC).
    *   **Audit Devices:** Ведут подробные журналы всех операций (запросов и ответов).
    *   **Storage Backends:** Физически сохраняют зашифрованные данные.

**Принцип Barrier:** независимо от выбранного бэкенда (Raft, Consul, Filesystem), Vault всегда шифрует данные перед записью. Данные сериализуются, хэшируются (HMAC) для контроля целостности, шифруются AES-256-GCM с использованием Master Key и записываются в бэкенд. Даже при получении прямого доступа к хранилищу (например, к файлам Raft или снапшоту), злоумышленник увидит только шифротекст без доступа к Master Key в памяти. Подробнее — в [Основных концепциях](./concepts.md#барьер-и-шифрование-данных-encryption-at-rest).

Архитектура Vault построена на принципах безопасности "Zero Trust" (нулевого доверия) и включает следующие фундаментальные механизмы:

*   **Брокер секретов (Secret Broker):** Vault выступает доверенным посредником между клиентами (людьми, сервисами) и целевыми системами (БД, внешние сервисы), выдавая временные права доступа.
*   **[Процесс Seal/Unseal (Запечатывание)](./concepts.md#процесс-запечатывания-seal-и-распечатывания-unseal):** Механизм защиты главного ключа шифрования. В продуктивных средах рекомендуется использовать **Auto-unseal** через HSM или Transit Engine.
*   **[Интегрированное хранилище (Raft)](./concepts.md#бэкенды-хранения-storage-backends):** Современный стандарт хранения данных Vault, обеспечивающий высокую доступность (HA) без внешних зависимостей.
*   **[Система идентификации (Identity Store)](./concepts.md#система-идентификации-identity-store):** Механизм Entities и Groups, позволяющий связывать различные методы аутентификации с одной личностью.
*   **[Авторизация и политики (Policies)](./authorization.md):** Управление доступом на основе путей API с использованием декларативного языка HCL.
*   **[Движки секретов (Secret Engines)](./concepts.md#движки-секретов-secret-engines):** Компоненты, реализующие логику работы с данными: от статического KV до динамической генерации учетных данных баз данных и внешних систем.
*   **[Жизненный цикл (Lease & Revoke)](./concepts.md#жизненный-цикл-токены-lease-и-revoke):** Система аренды секретов с ограниченным временем жизни (TTL), обеспечивающая автоматический отзыв доступа.
*   **[Аудит и события (Audit Devices)](./guides/audit_log_analysis.md):** Неизменяемые логи всех запросов и ответов. Audit device гарантирует запись в хотя бы одно включённое устройство — если все недоступны, запрос отклоняется.

### Ключевые преимущества

1.  **Централизация (Централизованное хранилище):** Исключение разрозненного хранения секретов в коде, конфигурациях и переменных окружения. Vault решает проблему **Secret Sprawl**, собирая все ключи и пароли в единую защищенную точку.
2.  **Многослойная защита (Layered Security):** Реализация принципа «луковицы», где безопасность обеспечивается не одной стеной, а множеством слоев: шифрование при хранении (at rest), шифрование при передаче (in transit), гранулярный доступ (ACL) и динамические токены.
3.  **Динамическая безопасность:** Генерация краткоживущих секретов "на лету" минимизирует ущерб при их компрометации и окно атаки (hacking window). Если секрет попадет в логи, он будет недействителен к моменту обнаружения злоумышленником.
4.  **Автоматизация ротации:** Встроенные механизмы обновления паролей и ключей без участия человека.
5.  **Синхронизация секретов (Secrets Sync):** Возможность управлять секретами в Vault и автоматически реплицировать их во внешние корпоративные системы управления секретами и оркестраторы. Изменение секрета в Vault распространяется на целевые платформы в реальном времени. Доступно в Vault Enterprise.

### Ключевые возможности

| Категория | Возможности |
| :--- | :--- |
| **Управление секретами** | Статическое хранение (KV v1/v2), динамические учетные данные (DB, внешние системы). |
| **Криптография** | Шифрование как сервис (Transit Engine), маскирование данных, управление ключами (KMIP). |
| **Идентификация** | Поддержка OIDC, Workload Identity Federation (WIF), интеграция с LDAP/Okta/Active Directory ([LDAP](./guides/vault-auth-ldap.md), [OIDC/SSO](./guides/vault-auth-oidc-sso.md), [MFA](./guides/vault-mfa.md)). |
| **Синхронизация и Обнаружение** | Secrets Sync (Hub-and-spoke модель), Vault Radar (поиск секретов в коде и корпоративных системах). |
| **PKI и Сертификаты** | Полноценный центр сертификации (CA), поддержка ACME, выдача TLS и SSH сертификатов. |
| **Аудит и Compliance** | Неизменяемые логи, хэширование чувствительных данных в журналах (HMAC-SHA256), поддержка FIPS 140-2. |
| **Высокая доступность** | Raft HA, Performance Standby (Enterprise), DR Replication (Enterprise), Namespaces (Enterprise). |

## Сценарии развертывания

| Сценарий | Хранилище | Способ | Руководство |
| :--- | :--- | :--- | :--- |
| Быстрый старт / dev | `inmem` | Dev Mode | см. ниже |
| Одиночный сервер / продакшн | Raft (Integrated Storage) | Open Source / Enterprise | [Установка Vault](./guides/vault_installation.md) |
| Bare metal / VM | Raft | systemd | [Установка Vault](./guides/vault_installation.md) |
| Контейнерная среда | Raft | Docker / Docker Compose | [Vault в Docker](./guides/vault_docker_integration.md) |
| HA-кластер в Kubernetes | Raft | Helm / VSO / Agent Injector | [Интеграция с Kubernetes](./guides/vault_kubernetes_integration.md) |
| Legacy HA | Consul / PostgreSQL | External Storage | [Vault с Consul backend](./guides/vault_with_consul_backend.md) |

Для HA-кластеров на Raft в Enterprise доступно **Snapshot Agent** (автоматическое резервное копирование снапшотом в объектные хранилища) и **Secret Recovery** (восстановление отдельных секретов без полного restore, начиная с 1.20+). Для legacy-инсталляций — External Storage (Consul/PostgreSQL) как альтернативный backend. Подробные стратегии резервного копирования — в [Стратегии бэкапов и восстановления](./guides/backup_restore_strategies.md).

## Практические сценарии

### Запуск в режиме разработки (Dev Mode)

Для быстрого ознакомления и тестирования Vault можно запустить в dev-режиме, не требующем настройки хранилища и распечатывания. Сервер стартует автоматически инициализированным и распечатанным: хранилище — `inmem` (в оперативной памяти), unseal-ключ и корневой токен выводятся в stdout при старте и теряются при остановке сервера. Такой режим **только для разработки и тестирования** — не используйте в production.

```bash
# Запуск сервера в dev-режиме с известным корневым токеном (иначе генерируется случайный)
vault server -dev -dev-root-token-id='root'
# → WARNING! dev mode is enabled!
#   ... (вывод настройки прошивки сервера)
#   Root Token: root
#   Unseal Key: <unseal-ключ для dev-режима>

# Настройка CLI для работы с локальным сервером (выполняется в новом терминале)
export VAULT_ADDR='http://127.0.0.1:8200'
export VAULT_TOKEN='root' # Корневой токен из вывода предыдущей команды

# Проверка статуса
vault status
# → Key             Value
#   Seal Type       shamir
#   Initialized     true
#   Sealed          false
#   Storage Type    inmem
#   HA Enabled      false
```

### Динамические учетные данные базы данных

Vault может генерировать временные учётные данные для PostgreSQL, MySQL, MongoDB и других СУБД:

```bash
# Настройка подключения к БД (выполняется один раз)
vault write database/config/my-postgresql \
  plugin_name=postgresql-database-plugin \
  allowed_roles="app-role" \
  connection_url="postgresql://{{username}}:{{password}}@10.0.0.1:5432/postgres" \
  username="vault-admin" \
  password="vault-password"

# Создание роли с TTL 1 час
vault write database/roles/app-role \
  db_name=my-postgresql \
  creation_statements="CREATE ROLE \"{{name}}\" WITH LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}';" \
  default_ttl="1h" \
  max_ttl="24h"

# Получение динамических учётных данных
vault read database/creds/app-role
# → lease_id: database/creds/app-role/xxxx
# → lease_duration: 1h
# → username: v-root-app-role-xxxx
# → password: xxxx-xxxx-xxxx-xxxx

# Продление аренды (при необходимости)
vault lease renew database/creds/app-role/xxxx

# Принудительный отзыв (удаляет пользователя в БД)
vault lease revoke database/creds/app-role/xxxx
```

Подробнее о сценариях работы с БД — в [Database Secrets Engine](./guides/database_secrets_engine.md).

### Примеры использования в инфраструктуре

*   **CI/CD интеграция:** Динамическая выдача временных токенов для пайплайнов GitLab/GitHub, исключающая хранение статических паролей в настройках CI. Аутентификация через AppRole или JWT/OIDC. Подробности — в [Аутентификация через AppRole](./guides/vault_auth_approle.md) и [Zero Trust](./zero_trust.md).
*   **Kubernetes Sidecar:** Автоматическое внедрение секретов в поды через Vault Agent Sidecar или Secrets Store CSI Driver. Подробности — в [Интеграция с Kubernetes](./guides/vault_kubernetes_integration.md).
*   **Database Credentials:** Генерация уникальных логинов для каждого экземпляра микросервиса с автоматическим удалением пользователя в БД после истечения TTL.
*   **Zero Trust Networking:** Выдача краткоживущих TLS-сертификатов для взаимодействия между сервисами. Подробности — в [PKI/CA продвинутые сценарии](./guides/pki_ca_advanced.md) и [Zero Trust](./zero_trust.md).
*   **SSH доступ:** Динамические SSH-ключи и OTP-пароли для администрирования серверов без статических `.pem` файлов. Подробности — в [SSH Secrets Engine](./guides/ssh_secrets_engine.md).

## Ежедневные операции и обслуживание

### Основные команды

```bash
# Проверка статуса
vault status

# Список смонтированных движков секретов и auth-методов
vault secrets list
vault auth list

# Чтение и запись секретов (KV v2)
vault kv get -mount=secret myapp/config
vault kv put -mount=secret myapp/config username=admin password=s3cret

# Проверка лидера и пиров (только для Raft)
vault operator raft list-peers
```

Полный список операционных команд — в [Основные концепции](./concepts.md#операционные-команды-и-управление-кластером).

### Проверка работоспособности (Health Checks)

Для SRE-практик важно автоматизированно проверять состояние кластера. Endpoint `/v1/sys/health` доступен без аутентификации и возвращает HTTP-коды в зависимости от состояния:

```bash
# Health check (доступен без аутентификации)
curl -sk https://vault.example.com:8200/v1/sys/health
# → {"initialized":true,"sealed":false,"standby":false,...}

# Проверка лидера (только для Raft)
vault read sys/leader
# → {"ha_enabled":true,"is_self":true,...}

# Проверка смонтированных движков и audit devices
vault secrets list -detailed
vault audit list
```

| HTTP-код | Состояние | Описание |
| :--- | :--- | :--- |
| 200 | Initialized, unsealed, active | Лидер; обслуживает запросы |
| 429 | Unsealed, standby | Follower |
| 472 | DR secondary | Вторичный узел DR |
| 501 | Not initialized | Кластер не инициализирован |
| 503 | Sealed | Запечатан (требует unseal) |

Подробнее о настройке health checks для Kubernetes и Prometheus — в [Мониторинг и алертинг](./guides/monitoring_and_alerting.md).

### Системное администрирование (systemd, логи, лимиты)

Для bare metal / VM Vault управляется через systemd-сервис с жёстким харденингом:

```ini
# /etc/systemd/system/vault.service
[Unit]
Description=HashiCorp Vault
Documentation=https://developer.hashicorp.com/vault/docs
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=vault
Group=vault
ExecStart=/usr/local/bin/vault server -config=/etc/vault.d/vault.hcl
ExecReload=/bin/kill -HUP $MAINPID
CapabilityBoundingSet=CAP_IPC_LOCK
NoNewPrivileges=yes
ProtectSystem=full
PrivateTmp=true
ProtectKernelModules=true
RestrictSUIDSGID=true
LimitNOFILE=65536
LimitMEMLOCK=infinity
TasksMax=infinity

[Install]
WantedBy=multi-user.target
```

**Ротация audit-логов (logrotate):**

```bash
# /etc/logrotate.d/vault
/var/log/vault/audit.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    postrotate
        systemctl kill -s HUP vault.service
    endscript
}
```

**Включение audit device:**

```bash
# Минимум два устройства для отказоустойчивости
vault audit enable file file_path=/var/log/vault/audit.log
vault audit enable syslog tag="vault-audit" facility="AUTH"
```

Подробнее о systemd, TLS, ротации сертификатов и настройке ОС — в [Руководстве по установке](./guides/vault_installation.md).

### Резервное копирование

```bash
# Создание снапшота Raft-хранилища
vault operator raft snapshot save /vault/backup/vault-$(date +%Y%m%d).snap

# Проверка целостности снапшота
vault operator raft snapshot inspect /vault/backup/vault-$(date +%Y%m%d).snap
```

Регулярное тестирование restore на отдельном стенде обязательно. Подробные стратегии RPO/RTO, DR Replication и восстановление после потери кворума — в [Стратегии бэкапов и восстановления](./guides/backup_restore_strategies.md).

### Обновление кластера

1.  Последовательный обновление узлов: Standby → Active → Standby.
2.  После обновления каждого узла убедитесь, что он rejoins кластер (`vault operator raft list-peers`).
3.  Проверьте работоспособность после обновления всего кластера (`vault status`, `vault secrets list`).
4.  При major upgrade проверяйте [Release Notes](https://developer.hashicorp.com/vault/docs/upgrade) на breaking changes (изменения формата снапшотов, параметры конфигурации).

Подробности по Seal Migration (Shamir → Auto-unseal) — в [Руководстве по установке](./guides/vault_installation.md).

## Устранение неисправностей

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **Sealed despite Auto-unseal** | HSM/KMS недоступен или изменён ключ. | Проверьте `vault status` (поле `Seal Type`) и логи внешнего сервиса. |
| **Raft Quorum Lost** | Потеря >50% узлов кластера. | Восстановление из снапшота или ручная правка `peers.json`. |
| **High commit latency** | Рост `vault.raft.commitTime`. | Проверьте диск (IOPS), сеть между узлами и размер Raft-лога. |
| **Audit log not writing** | Audit device misconfiguration или недостаточно прав. | Проверьте `vault audit list`, права на файл/сокет, формат логов. |
| **Pod в CrashLoopBackOff (K8s)** | Несовместимость версии Vault с данными Raft. | Откатитесь через `helm rollback vault -n vault`. |
| **Token count high** | Приложения не отзывают токены после завершения работы. | Настройте токены с небольшим `ttl`, используйте `batch`-токены для M2M. |
| **Vault Agent не получает секреты** | Неверный ServiceAccount или политика. | Проверьте `allowed_parameters` и `vault token capabilities`. |

Подробное руководство по устранению неисправностей — в [Основные концепции](./concepts.md#типичные-ошибки-и-способы-восстановления-troubleshooting) и [Мониторинг и алертинг](./guides/monitoring_and_alerting.md).

## Лучшие практики

### Управление ключами и инициализация

*   **Shamir quorum:** Используйте `key-shares=5, key-threshold=3` (или аналогичный quorum) и распределяйте Unseal Keys между разными ролями (Security Officer, Platform Admin, On-Call Engineer). Ни один человек не должен иметь все ключи.
*   **Auto-unseal для production:** В production используйте Auto-unseal через KMS/HSM (или Transit Engine) — устраняет необходимость ручного вмешательства при перезапуске.
*   **Root token — одноразово:** Root token используется только для первоначальной настройки. После инициализации сразу создайте персональный токен с ограниченными политиками через `vault token create -role=<role>` и отзовите root-токен.
*   **Не используйте root-токен для ежедневной работы:** Генерируйте ограниченные токены для всех операций.

### Безопасность и аудит

*   **Deny-by-default политики:** Все политики должны явно разрешать только необходимые пути. Никогда не используйте `path "secret/*" { capabilities = ["read"] }` для приложений. Подробнее — в [Авторизация в Vault](./authorization.md).
*   **Минимум два audit device:** Включите `file` + `syslog` (или `socket`) на каждом кластере. Vault гарантирует запись в хотя бы одно — если одно выходит из строя, второе продолжит писать.
*   **Хэширование секретов в логах:** По умолчанию Vault хэширует все строковые значения в audit логах (HMAC-SHA256). Не включайте `log_raw=true` в production.
*   **KV v2 для всех новых хранилищ:** Используйте KV v2, который поддерживает версионирование, мягкое удаление и атрибуты изменений. KV v1 не рекомендуется.

### Токены

*   **batch-токены для M2M:** Используйте `token_type=batch` для машинных сервисов — меньше следов в индексе и в аудите, нечувствительны к перезапуску Active node.
*   **service + orphan + periodic для долгоживущих сервисов:** Автоматическое продление через Vault Agent.
*   **Ограничьте TTL:** Устанавливайте `max_ttl` жёстче, чем `ttl` для токенов приложений — это предотвращает бессрочное продление.
*   **token_bound_cidrs:** Ограничьте токены конкретными подсетями (например, pod CIDR в Kubernetes).

### Хранилище и резервные копии

*   **Raft (Integrated Storage):** Стандарт для новых инсталляций — не требует внешних зависимостей, поддерживает `vault operator raft snapshot save` в OSS.
*   **Автоматизированный snapshot:** cron (OSS) или Snapshot Agent (Enterprise): `vault operator raft snapshot save /backup/vault-$(date +%F).snap` каждые 6–12 часов.
*   **3-2-1 правило:** 3 копии, на 2 разных носителя, 1 off-site (удалённый хост по SSH/rsync, не облако). Шифруйте snapshot при хранении.
*   **Тестирование DR:** регулярно тестируйте restore на отдельном сервере не реже одного раза в квартал.

### Мониторинг (SRE)

*   **Метрики с самого начала:** Включите Prometheus exporter (`prometheus_retention_time = "24h"`) на этапе установки.
*   **Ключевые алерты:** `vault.core.unsealed` (availability), `vault.request.count` с `status=~"5.."` (error rate), `vault.raft.commitTime` (latency).
*   **Health checks:** Используйте `/v1/sys/health` для liveness (sealed=false) и readiness (standby_ok=true) probes в orchestrator.
*   **SLO 99.9%:** слежите за `vault_core_unsealed` и долей ошибок `5xx` в `vault_request_count`.

Подробнее о мониторинге, дашбордах Grafana и SLO — в [Мониторинг и алертинг](./guides/monitoring_and_alerting.md).

## Дополнительная информация

### Vault внутри Kubernetes

Развертывание Vault в Kubernetes — распространенный паттерн для обеспечения безопасности кластера:

**Архитектура:**
- **Vault Server** разворачивается как StatefulSet в выделенном неймспейсе (например, `vault`).
- Хранилище — **Raft** (Integrated Storage) для HA без внешних зависимостей.
- Для production обязательен **Auto-unseal** через HSM, Transit Engine или KMS.

**Способы доставки секретов в поды:**
1.  **Vault Agent Sidecar:** Контейнер-сайдкар, который аутентифицируется в Vault, получает секреты и записывает их в общий `emptyDir` volume. Поддерживает бесшовную ротацию через `SIGHUP`.
2.  **Vault Secrets Operator (VSO):** Оператор, синхронизирующий секреты из Vault в нативные Kubernetes Secret ресурсы (CRD `VaultStaticSecret`/`VaultDynamicSecret`/`VaultPKISecret`).
3.  **Secrets Store CSI Driver:** CSI-драйвер, монтирующий секреты из Vault как volume в `tmpfs` пода (секреты не попадают в etcd).

**Аутентификация подов:**
- **Kubernetes Auth Method:** Под аутентифицируется через свой ServiceAccount JWT-токен. Начиная с Vault 1.21+, параметр `audience` обязателен для роли.
- **JWT/OIDC:** Для внешних систем (CI/CD) используется подписанный JWT-токен.

Подробности — в [Интеграция с Kubernetes](./guides/vault_kubernetes_integration.md).

### См. также

*   **[Архитектура и основные концепции](./concepts.md):** Глубокое погружение в механизмы работы Vault (Barrier, Seal/Unseal, Storage Backends, HA, Identity Store, Token Types, Secret Engines, Lease & Revoke, Response Wrapping, Audit).
*   **[Авторизация в Vault](./authorization.md):** Политики доступа и принцип наименьших привилегий.
*   **[Подход Zero Trust](./zero_trust.md):** Архитектурные основы Vault в модели нулевого доверия.
*   **[Антипаттерны управления секретами](./common_antipatterns.md):** Типичные ошибки при работе с Vault и способы их устранения.
*   **[Vault Agent](./guides/vault_agent/basics.md):** Автоматизация аутентификации, рендеринга секретов и управление токенами на стороне клиента.
*   **[Аутентификация через AppRole](./guides/vault_auth_approle.md):** Настройка M2M-аутентификации для CI/CD и приложений.
*   **[Database Secrets Engine](./guides/database_secrets_engine.md):** Динамические учетные данные баз данных.
*   **[SSH Secrets Engine](./guides/ssh_secrets_engine.md):** Динамические SSH-ключи и сертификаты.
*   **[PKI/CA продвинутые сценарии](./guides/pki_ca_advanced.md):** Intermediate CA, ACME, CRL/OCSP, cross-signing.
*   **[Transit Engine — Политики](./guides/transit-encryption-policies.md):** Шифрование данных без выгрузки ключей.
*   **[Cubbyhole и Response Wrapping](./guides/cubbyhole_response_wrapping.md):** Безопасная доставка секретов.
*   **[Control Groups](./guides/control_groups.md):** Multi-approval для критических операций (Enterprise).
*   **[Namespaces](./guides/namespaces.md):** Изоляция сред (Enterprise).
*   **[SLM, Vault Radar, Secrets Sync](./guides/slm_radar_secrets_sync.md):** Security Lifecycle Management.
*   **[Производительность и репликация](./guides/performance_and_replication.md):** Performance Standby, DR Replication, stale reads.
*   **[Производительность и тюнинг](./guides/performance_tuning.md):** Оптимизация для high-load сред.
*   **[Мониторинг и алертинг](./guides/monitoring_and_alerting.md):** Prometheus, Grafana, SLO/SLI.
*   **[Анализ audit логов](./guides/audit_log_analysis.md):** SIEM, forensic, compliance.
*   **[Ротация секретов](./guides/secret_rotation.md):** Стратегии ротации, graceful rotation.
*   **[Стратегии бэкапов и востановления](./guides/backup_restore_strategies.md):** RPO/RTO, snapshot, disaster recovery.
*   **[Руководство по установке Vault](./guides/vault_installation.md):** Развёртывание, харденинг systemd, Seal Migration.
*   **[Vault API Reference](./guides/vault_api_reference.md):** REST API, endpoints, примеры.
*   **[Официальная документация HashiCorp Vault](https://developer.hashicorp.com/vault/docs):** Технический справочник по актуальным версиям.