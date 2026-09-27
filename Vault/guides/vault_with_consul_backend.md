# Consul как бэкенд для Vault

## Определения

**Consul бэкенд для Vault** — конфигурация, при которой HashiCorp Vault использует внешний распределенный кластер **[Consul](../../Consul/consul_overview.md)** в качестве персистентного хранилища данных и механизма координации высокой доступности (HA).

**Статус:** Данный метод считается **устаревшим (Legacy)** для новых инсталляций, хотя официально поддерживается HashiCorp. Рекомендуемым стандартом (основной вариант) является использование встроенного хранилища **[Raft (Integrated Storage)](./vault_installation.md)**. Использование Consul оправдано только в сложных распределенных топологиях или при наличии зрелой инфраструктуры Consul, требующей глубокой интеграции (например, когда Consul уже эксплуатируется как корпоративное KV-хранилище и сервисная сетка).

## Предварительные требования

### Версии компонентов

| Компонент | Минимальная версия | Рекомендуемая |
| :--- | :--- | :--- |
| **Vault** | 1.13+ | Стабильная patch-версия текущей мажорной линейки |
| **Consul** | 1.14+ | 1.16+ (Dataplane по умолчанию — несовместим, требуется Agent-based) |
| **Операционная система** | Linux 4.9+ (kernel) | RHEL/CentOS 8+, Ubuntu 20.04+, Debian 11+ |

> **Важно:** Начиная с Consul 1.14, режим **Dataplane** включен по умолчанию. Vault не поддерживает Dataplane; требуется классическая модель client-agent (см. ограничение в разделе «Основные концепции»).

### Требования к Consul-кластеру

*   **Кворум:** Для HA-кластера Vault необходимо минимум 3 серверных узла Consul (нечётное число). Consul-клиенты (agents) должны присутствовать на каждом хосте, где запускается Vault.
*   **Сеть:** Низколатентное соединение между Vault-узлами и Consul-серверами (рекомендуется 1–5 ms). Избегайте cross-AZ трафика без оптимизации.
*   **ACL:** Система ACL должна быть включена (`acl.enabled = true`) с политикой `default_policy = "deny"`.
*   **TLS:** Рекомендуется включить TLS на стороне Consul (`verify_incoming = true`, `verify_outgoing = true`).

### Подготовка хоста Vault

Минимальные требования к хосту, на котором будет запускаться Vault, аналогичны стандартной установке (см. **[Руководство по установке Vault](./vault_installation.md)**). Дополнительно:
*   Наличие монтирования `/vault/data` (для Raft не требуется, но для Consul требуется достаточно места для кэширования сессий).
*   Пакет `curl`, `jq` для диагностики.
*   Отключение swap (`swapoff -a`) для защиты секретов в оперативной памяти.

## Основные концепции

### Роль Consul в архитектуре Vault

При использовании данного бэкенда Consul выполняет две функции:
1.  **K/V Storage:** Хранение зашифрованных данных Vault. Vault шифрует все данные перед записью, поэтому Consul не имеет доступа к открытому тексту секретов.
2.  **High Availability (HA):** Consul предоставляет механизм распределенных блокировок (Sessions) для выбора активного узла (Active Node) и перенаправления запросов с резервных узлов (Standby Nodes).

### Шифрование данных и жизненный цикл

Vault никогда не передает в Consul открытый текст секретов. Перед записью в K/V-хранилище данные проходят через **Barrier Seal** (AES-GCM с ключом, распределенным по Shamir Secret Sharing). Consul хранит лишь зашифрованные байты и метаданные (индексы, пути). При компрометации Consul-кластера атакующий получает только шифротекст.

Для данных, которые Vault хранит в Consul, характерны следующие состояния:
*   **Sealed:** Vault не имеет доступа к ключам шифрования. В Consul данные остаются на месте, но являются нечитаемыми для Vault.
*   **Unsealed:** Vault расшифровывает Barrier и выполняет операции.
*   **Миграция:** При миграции на Raft данные перекопируются в зашифрованном виде и сохраняют структуру, что позволяет избежать повторного шифрования.

### Интеграция и Service Discovery

Vault автоматически регистрирует себя в каталоге сервисов Consul с default health check (HTTP-проверка на `/v1/sys/health`). В зависимости от состояния узла используются разные DNS-имена каталога `consul`:

*   `active.vault.service.consul` — активный (Active) узел, обслуживающий запросы;
*   `standby.vault.service.consul` — резервные (Standby) узлы, не выполняющие `vault.status` ответы;
*   `vault.service.consul` — все unsealed-узлы (и active, и standby);

Запечатанные (Sealed) узлы помечают себя как unhealthy и автоматически исключаются из результата Service Discovery, что позволяет строить балансировку через DNS или API Consul без лишних простоев.

> **Примечание:** Если у Vault настроено несколько `listener`, необходимо явно указать, какой адрес Consul должен публиковать как адрес активного узла, через параметры `api_addr` / `cluster_addr`.

> **Ограничение (актуально для Consul 1.14+):** Vault не поддерживает **Consul Dataplane**. Для кластеров, развернутых в Kubernetes, использование Consul 1.14+ с режимом Dataplane по умолчанию потребует выключения Dataplane и перехода обратно на классические client-agent (см. [upgrade guide Consul](https://developer.hashicorp.com/consul/docs/k8s/upgrade)). При использовании обычных client agents (VM, bare-metal) ограничение не распространяется.

Consul-бэкенд использует механизм **Consul Sessions** для выбора активного лидера. Активный узел создаёт сессию, привязывает её к K/V-ключу и удерживает через TTL (`session_ttl`, по умолчанию `15s`), периодически обновляя (renew). Остальные узлы находятся в режиме Standby и возвращают клиенту адрес активного узла (redirect).

В случае отказа активного узла сессия истекает (не возобновляется), блокировка освобождается, и один из Standby-узлов захватывает её через `lock_wait_time` (время ожидания перед очередной попыткой захвата). Выбор лидера координируется на стороне Consul, поэтому Vault не требует собственного алгоритма консенсуса, в отличие от Raft (Integrated Storage).

### Механизм лидерства и разделение ролей

*   **Active Node:** Выполняет все операции записи (write) и чтение (read). Хранит запечатывающий ключ в оперативной памяти.
*   **Standby Node:** Остается в фоне, синхронизирует данные через Consul K/V, готов к перехвату лидерства. При обращении клиента возвращает HTTP 307 redirect на активный узел.
*   **Sealed Node:** Не обслуживает запросы. Не участвует в выборах лидера до повторного распечатывания.

Переход лидера (failover) происходит автоматически при:
*   Превышении TTL сессии (активный узел завис или потерял связь с Consul).
*   Остановке сервиса Vault (`systemctl stop vault`).
*   Сбое ОС на активном узле.

### Требования к безопасности (ACL)

Если в Consul включена система управления доступом (ACL), Vault требует токен с правами на:
*   Чтение/запись/удаление в префиксе K/V (по умолчанию `vault/`).
*   Создание и управление сессиями (`session`) для работы механизмов HA.
*   Чтение информации агента (`agent`) для корректной работы health check и Service Discovery.
*   Регистрацию сервиса (если включен параметр `service_registration` или `service` в `storage`).

**Пример политики ACL (синтаксис Consul 1.4+, который рекомендуется использовать с современными версиями Vault):**
```hcl
key_prefix "vault/" {
  policy = "write"
}
session_prefix "" {
  policy = "write"
}
service "vault" {
  policy = "write"
}
agent_prefix "" {
  policy = "read"
}
```

> **Примечание:** ACL-токен для Vault должен иметь тип `client`. Management-токен (`management` тип) не рекомендуется использовать в production из-за избыточных привилегий.

## Практические сценарии

### Конфигурация хранилища (vault.hcl)

Пример настройки в файле `/etc/vault.d/vault.hcl`:

```hcl
storage "consul" {
  # Рекомендуется обращаться к локальному Consul Agent (127.0.0.1:8500),
  # а не напрямую к серверу — это упрощает ACL и Health Check.
  address = "127.0.0.1:8500"
  path    = "vault/"
  
  # Использование токена ACL (не Vault токен!)
  token   = "YOUR_CONSUL_ACL_TOKEN"
  
  # Настройка TLS для подключения к Consul. Даже во внутренней сети
  # не рекомендуется использовать "http" для связи по сети.
  scheme  = "https"
  tls_ca_file   = "/etc/vault.d/consul-ca.crt"
  tls_cert_file = "/etc/vault.d/vault-consul-client.crt"
  tls_key_file  = "/etc/vault.d/vault-consul-client.key"

  # HA: TTL сессии, используемой для захвата лидерства (не меньше 10s на стороне Consul)
  session_ttl = "15s"
  # Максимальный параллелизм запросов к Consul (согласуется с http_max_conns_per_client в Consul)
  max_parallel = "128"

  # Регистрация сервиса в Consul
  service = "vault"
  service_tags = "production,security"
}

# Адреса для координации кластера
api_addr     = "https://vault-node-1.example.com:8200"
cluster_addr = "https://10.0.0.1:8201"
```

### Настройка Service Registration отдельно от Storage

Начиная с версии 1.4, регистрация сервиса может быть вынесена в отдельный блок, что позволяет использовать Raft для хранения, но продолжать использовать Consul для обнаружения сервиса:

```hcl
service_registration "consul" {
  address = "127.0.0.1:8500"
  service = "vault"
}
```

### Сценарий 1: Базовое развертывание (3 узла, systemd)

#### Шаг 1: Подготовка Consul-кластера

Убедитесь, что на каждом хосте запущен Consul Server в режиме Agent-based (не Dataplane):

```hcl
# /etc/consul.d/server.hcl
server {
  enabled = true
  bootstrap_expect = 3
}

acl {
  enabled = true
  default_policy = "deny"
  enable_token_persistence = true
}

verify_incoming = true
verify_outgoing = true
```

```bash
# Инициализация ACL (выполнить один раз на любом сервере)
consul acl bootstrap
# Сохраните SecretID — это Management Token для создания политик
```

Создайте политику для Vault (подробнее о синтаксисе — в **[Consul ACL](../../Consul/consul_acl.md)**):

```bash
# Создание политики
cat > vault-policy.hcl <<'EOF'
key_prefix "vault/" {
  policy = "write"
}
session_prefix "" {
  policy = "write"
}
service "vault" {
  policy = "write"
}
agent_prefix "" {
  policy = "read"
}
EOF

consul acl policy create -name "vault-backend" -rules @vault-policy.hcl

# Создание токена, привязанного к политике
consul acl token create -description "Vault backend token" -policy-name "vault-backend"
# Сохраните returned SecretID — он потребуется в vault.hcl
```

#### Шаг 2: Подготовка хоста Vault

```bash
# Создание пользователя и директорий
sudo useradd --system --home /etc/vault.d --shell /bin/false vault

sudo mkdir -p /etc/vault.d /var/log/vault /opt/vault/data
sudo chown -R vault:vault /etc/vault.d /var/log/vault /opt/vault/data
sudo chmod 750 /etc/vault.d

# Отключение swap
sudo swapoff -a
sudo sed -i '/ swap / s/^/#/' /etc/fstab
```

#### Шаг 3: Конфигурация хранилища (vault.hcl)

Пример настройки в файле `/etc/vault.d/vault.hcl`:

```hcl
storage "consul" {
  # Рекомендуется обращаться к локальному Consul Agent (127.0.0.1:8500),
  # а не напрямую к серверу — это упрощает ACL и Health Check.
  address = "127.0.0.1:8500"
  path    = "vault/"
  
  # Использование токена ACL (не Vault токен!)
  token   = "YOUR_CONSUL_ACL_TOKEN"
  
  # Настройка TLS для подключения к Consul. Даже во внутренней сети
  # не рекомендуется использовать "http" для связи по сети.
  scheme  = "https"
  tls_ca_file   = "/etc/vault.d/consul-ca.crt"
  tls_cert_file = "/etc/vault.d/vault-consul-client.crt"
  tls_key_file  = "/etc/vault.d/vault-consul-client.key"

  # HA: TTL сессии, используемой для захвата лидерства (не меньше 10s на стороне Consul)
  session_ttl = "15s"
  # Максимальный параллелизм запросов к Consul (согласуется с http_max_conns_per_client в Consul)
  max_parallel = "128"

  # Регистрация сервиса в Consul
  service = "vault"
  service_tags = "production,security"
}

# Адреса для координации кластера
api_addr     = "https://vault-node-1.example.com:8200"
cluster_addr = "https://10.0.0.1:8201"
```

#### Шаг 4: Systemd unit

```ini
# /etc/systemd/system/vault.service
[Unit]
Description=HashiCorp Vault - Consul Backend
Documentation=https://developer.hashicorp.com/vault/docs
After=network-online.target consul.service
Wants=consul.service
ConditionFileNotEmpty=/etc/vault.d/vault.hcl

[Service]
User=vault
Group=vault
ProtectSystem=full
ProtectHome=read-only
PrivateTmp=true
PrivateDevices=true
NoNewPrivileges=true
ExecStart=/usr/bin/vault server -config=/etc/vault.d/vault.hcl
ExecReload=/bin/kill -HUP $MAINPID
KillMode=process
KillSignal=SIGINT
Restart=on-failure
RestartSec=5
StartLimitInterval=0
LimitMEMLOCK=infinity

[Install]
WantedBy=multi-user.target
```

#### Шаг 5: Инициализация и распечатывание

```bash
# Включение автозагрузки
sudo systemctl daemon-reload
sudo systemctl enable vault

# Запуск
sudo systemctl start vault

# Проверка статуса (должен быть sealed)
sudo systemctl status vault
vault status
# → Seal Type: shamir
# → Initialized: false
# → Sealed: true

# Инициализация (выполняется один раз на первом узле)
vault operator init -key-shares=5 -key-threshold=3
# → Сохраните 5 unseal keys и root token в защищенном хранилище (HashiCorp Boundary, 1Password, paper backup)

# Распечатывание (выполнить на всех узлах)
vault operator unseal <key_1>
vault operator unseal <key_2>
vault operator unseal <key_3>

# Вход под root (для начальной настройки)
vault login <root_token>
```

#### Шаг 6: Проверка HA и лидерства

```bash
# На любом узле
vault status
# → Sealed: false
# → HA Enabled: true
# → Cluster Name: vault-cluster-xxxxxx

# Просмотр Service Discovery
dig @127.0.0.1 -p 8600 active.vault.service.consul
# → Должен возвращать IP активного узла

# Проверка health endpoint
curl http://127.0.0.1:8500/v1/health/service/vault
# → active узел имеет статус "passing", standby — "critical" (если настроен accordingly)
```

### Сценарий 2: Разделение Service Registration и Storage (Raft + Consul)

Начиная с версии 1.4, регистрация сервиса может быть вынесена в отдельный блок, что позволяет использовать Raft для хранения, но продолжать использовать Consul для обнаружения сервиса:

```hcl
storage "raft" {
  path = "/vault/raft/"
  node_id = "node_1"
}

service_registration "consul" {
  address = "127.0.0.1:8500"
  service = "vault"
  # token = "YOUR_CONSUL_ACL_TOKEN"
}
```

> **Примечание:** При таком подходе Vault больше не требует Consul для хранения, но все еще зависит от Consul для Service Discovery и балансировки. Это промежуточный вариант при миграции с Consul на Raft.

### Сценарий 3: Динамические секреты и Consul в качестве Service Discovery

В распределенных топологиях (например, Nomad + Consul + Vault) Vault часто развертывается с Consul-бэкендом для обеспечения единой системы Service Discovery. Пример динамического получения учетных данных БД с использованием Consul DNS:

```bash
# Через CLI (любой узел кластера)
vault write database/config/my-postgres-db \
  plugin_name=postgresql-database-plugin \
  allowed_roles="readonly" \
  connection_url="postgresql://{{username}}:{{password}}@db.service.consul:5432/mydb" \
  username="vault_admin" \
  password="dynamic_password"

# Запрос динамических учетных данных
vault read database/creds/readonly
# → lease_id, lease_duration, username, password

# Автоматическое продление (если используется Vault Agent)
# Без Agent: повторный запрос по истечении lease или использование -mode=client
```

### Сценарий 4: Восстановление после сбоя (Disaster Recovery)

#### Остановка активного узла

```bash
# На узле, который нужно остановить
sudo systemctl stop vault

# На standby-узле проверьте статус через несколько секунд
vault status
# → HA Enabled: true
# → Cluster ID совпадает с предыдущим
```

#### Замена отказавшего узла

```bash
# На новом хосте повторите Шаги 2–5 из Сценария 1
# Если используется Raft-совместимый Consul, данные автоматически реплицируются.
# При использовании только Consul-бэкенда: запустите Vault с тем же конфигурацией.
# Новый узел подхватит данные из Consul K/V.

# Распечатывание
vault operator unseal <key_1> ...
# Проверка
vault status
# → Active Node должен переключиться на standby узел
```

#### Создание снапшота Consul

```bash
# Создание снапшота кластера Consul (выполнить на любом сервере Consul)
consul snapshot save /opt/consul/backups/backup-$(date +%Y%m%d).snap

# Восстановление из снапшота (при необходимости)
# Остановите все серверы Consul
consul snapshot restore /opt/consul/backups/backup-20230920.snap
# Запустите серверы
```

## Дополнительная информация

### Сравнение Consul и Raft

| Параметр | Consul (Legacy) | Raft (Standard) |
| :--- | :--- | :--- |
| **Зависимости** | Требует отдельный кластер Consul | Без внешних зависимостей |
| **Сложность** | Высокая (два кластера для поддержки) | Низкая (один бинарный файл) |
| **Производительность** | Ограничена сетевыми задержками до Consul | Максимальная (локальный диск + сеть Raft) |
| **Диагностика** | Разделена между логами Vault и Consul | Единый лог Vault |

### Миграция с Consul на Raft

Миграция позволяет перевести уже эксплуатируемый кластер с Consul-бэкенда на встроенное хранилище Raft (Integrated Storage) без потери данных. Команда используется: `vault operator migrate`. Миграция выполняется на одном из узлов, который станет лидером Raft-кластера, и требует временной остановки кластера (Vault должен быть офлайн).

> Перед миграцией обязательно создайте снапшот Consul: `consul snapshot save backup.snap` — это резервная копия на случай сбоя процесса.

**Конфигурация миграции (`migrate.hcl`):**
```hcl
storage_source "consul" {
  address = "127.0.0.1:8500"
  path    = "vault/"
}

storage_destination "raft" {
  path    = "/vault/raft/"
  node_id = "node_1"
}

cluster_addr = "https://10.0.0.1:8201"
```

> `storage_source` — текущий бэкенд (Consul), `storage_destination` — целевой (Raft). Значения `path` и `node_id` должны совпадать с конфигурацией серверного файла. Директория `/vault/raft/` должна существовать на хосте — команда не создает её автоматически.

**Команда миграции:**
```bash
vault operator migrate -config=migrate.hcl
# → перекопирует зашифрованные данные из Consul в Raft, не затрагивая секреты (зашифрованная структура сохраняется)
```

После миграции:

1. Запустите новый сервер Vault с конфигурацией на `storage "raft"` и выполните распечатывание (`vault operator unseal`, при необходимости `-migrate` для конверсии seal-структуры).
2. Один узел в Raft-кластере станет лидером — проверьте: `vault operator raft list-peers`.
3. Остальные узлы добавляются через `vault operator raft join <api_addr>`, либо автоматически при использовании `retry_join` в конфигурации Raft.

> В Vault Enterprise с multi-datacenter репликацией (Performance Replication / DR Secondary) рекомендован развёрнутый workflow: создать новый кластер на Raft, подключить его как DR Secondary к существующему основному (Consul), дождаться синхронизации, а затем перевести трафик и остановить старый кластер.

### Настройка TLS между Vault и Consul

Для защиты канала связи Vault → Consul используйте взаимный TLS (mTLS):

```hcl
# Consul: /etc/consul.d/tls.hcl
verify_incoming = true
verify_outgoing = true
ca_file = "/etc/consul.d/consul-agent-ca.pem"
cert_file = "/etc/consul.d/consul-agent.pem"
key_file = "/etc/consul.d/consul-agent-key.pem"
```

```hcl
# Vault: /etc/vault.d/vault.hcl (фрагмент storage "consul")
tls_ca_file   = "/etc/vault.d/consul-ca.crt"
tls_cert_file = "/etc/vault.d/vault-consul-client.crt"
tls_key_file  = "/etc/vault.d/vault-consul-client.key"
```

Генерация сертификатов (при использовании Consul CA):
```bash
consul tls ca create
consul tls cert create -server -dc=dc1
consul tls cert create -client -dc=dc1 -name "vault-client"
```

### Мониторинг и наблюдаемость

Для интеграции с Prometheus/Grafana отслеживайте метрики Consul на порту `8500` и метрики Vault на `8200`.

| Метрика | Источник | Назначение |
| :--- | :--- | :--- |
| `vault_core_unseal_progress` | Vault metrics | Прогресс распечатывания |
| `vault_runtime_lease_count` | Vault metrics | Количество активных аренд |
| `consul_raft_leader_lastContact` | Consul metrics | Задержка между лидером и фолловерами |
| `consul_serf_lan_member_flap` | Consul metrics | Частота переключений статусов узлов |

Для централизованного сбора логов используйте stdout-редирект Vault в journald или файл, и пересылайте их в ELK/Loki через Vector или Filebeat.

### Устранение неполадок (Troubleshooting)

| Проблема | Причина и решение |
| :--- | :--- |
| **Ошибка лидерства (session TTL)** | TTL сессии Consul слишком мал или сеть имеет высокую задержку. Увеличьте `session_ttl` в Vault до `30s`, убедитесь, что `lock_delay` в Consul не конфликтует. |
| **Dataplane mode конфликт** | Consul 1.14+ запущен с Dataplane. Vault требует agent-based. Отключите Dataplane: `connectInjector.enabled = false` в конфигурации Consul Helm, или используйте standalone agents. |
| **TLS handshake error** | Сертификаты просрочены или CN/SAN не соответствуют адресу. Проверьте: `openssl s_client -connect consul.service.consul:8500`. |
| **Consul ACL: permission denied** | Токен Vault недостаточно привилегирован. Проверьте политику: `consul acl token read -id <token_accessor_id>`. |
| **Sealed после рестарта** | Отсутствуют unseal keys или не настроен auto-unseal. Проверьте: `vault status`. |
| **Ошибка `storage is locked`** | Другой узел удерживает сессию. Проверьте: `consul members` и `consul monitor`. Убедитесь, что на всех узлах Vault одинаковое время (NTP). |
| **Потеря данных при сбое Consul** | Consul был остановлен дольше TTL сессий. После перезапуска сессия истечет, но данные K/V не удаляются. Vault возобновит работу после распечатывания. |
| **Высокая латентность запросов** | `max_parallel` слишком низкий или сеть перегружена. Увеличьте до `256` (согласуйте с `http_max_conns_per_client` в Consul). |

### Рекомендации по безопасности

1.  **ACL по умолчанию:** В Consul всегда включайте ACL с `default_policy = "deny"`. Белый список только для префикса `vault/`.
2.  **Тип токена:** Используйте токены типа `client` для Vault. Токены типа `management` оставляйте только для операторов.
3.  **TLS:** Никогда не используйте `scheme = "http"` в production. В Dev-средах допустимо, но не рекомендуется.
4.  **Локальный Agent:** Обращайтесь к Consul через `127.0.0.1:8500` (локальный agent), а не напрямую к серверу. Это упрощает ACL и изоляцию.
5.  **Сетевые правила:** Ограничьте доступ к порту 8500 только узлами Vault и серверами Consul (firewall / security groups).
6.  **Снапшоты:** Планируйте регулярное создание снапшотов Consul (`consul snapshot save`) по крону.
7.  **Ротация токенов ACL:** Периодически перевыпускайте токен, используемый Vault для доступа к Consul.

### Валидация и проверка корректности

1.  **Проверка статуса:** `vault status` → `Sealed: false`, `HA Enabled: true`.
2.  **Проверка лидера:** `consul kv get vault/leader` — проверка ключа лидерства в Consul K/V.
3.  **Health Check Consul:** `curl http://127.0.0.1:8500/v1/health/service/vault`.
4.  **Service Discovery:** `dig @127.0.0.1 -p 8600 active.vault.service.consul`.
5.  **Логи Vault:** `journalctl -u vault -f` — при старте должен появиться `storage "consul" registered successfully`.
6.  **ACL:** `consul acl token read -id <token_id>` — проверка срока действия и привилегий.

### Очистка и откат

```bash
# Остановка кластера Vault
sudo systemctl stop vault

# Остановка Consul (при необходимости)
sudo systemctl stop consul

# Удаление данных Vault из Consul (ОСТОРОЖНО: необратимо)
consul kv delete -recurse vault/

# Удаление сервиса из каталога Consul
consul services deregister vault

# Восстановление из снапшота Consul (если нужно откатить изменения)
consul snapshot restore /opt/consul/backups/backup-20230920.snap
```

### См. также

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и SLM.
*   **[Обзор Consul](../../Consul/consul_overview.md)** — возможности сервисной сетки, K/V и ACL.
*   **[Руководство по установке](./vault_installation.md)** — настройка Raft (Integrated Storage) и миграция.
