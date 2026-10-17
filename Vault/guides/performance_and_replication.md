# Производительность и репликация Vault

> **Статус:** Performance Standby, Performance Replication и DR Replication — функции HashiCorp Vault Enterprise (требуется лицензия Enterprise или HCP Vault Dedicated). В OSS-сборках эти функции недоступны.

**Актуально для:** Vault 2.x (latest 2.1.2)

## Предварительные требования

- **Vault Enterprise** (2.x) — Performance Standby, Performance Replication и DR Replication требуют Enterprise-лицензии. OSS-сборка не поддерживает репликацию и Performance Standby.
- **Хранилище с транзакционной поддержкой:** Integrated Storage (Raft) или Consul. Репликация не работает с файловым (`file`) или другими транзакционно-неподдерживаемыми бэкендами.
- **TLS:** все соединения между кластерами шифруются с использованием взаимной TLS-аутентификации. Сертификаты выпускаются Vault автоматически, но load balancer для cluster-порта (8201) не может终ировать TLS.
- **Сеть:** latency между узлами кластера < 50ms для Raft; latency между дата-центрами — для DR/Performance Replication не критична (репликация асинхронна).
- **CLI:** Vault CLI 2.x, `jq` для разбора JSON-ответов.
- **Kubernetes (для Сценария 1):** `kubectl` для выполнения команд `vault operator unseal` на узлах StatefulSet.
- **Согласованность версий:** secondary-кластер может работать на новой версии primary, но рекомендуется держать версии синхронными во время эксплуатации.

## Определения

**Performance Standby** — режим работы standby-узлов в HA-кластере Vault Enterprise, при котором они обслуживают read-only запросы локально, не перенаправляя их лидеру. Обеспечивает горизонтальное масштабирование операций чтения (KV, Transit).

**Stale Read** — режим чтения данных, при котором запрос обслуживается локально standby-узлом без перенаправления на лидера. Данные могут устаревать до 100 м с. Для read-after-write consistency используют заголовки `X-Vault-Forward: active-node` или `X-Vault-Inconsistent: forward-active-node` + `X-Vault-Index`.

**Read Consistency (Strong vs Stale)** — уровень согласованности данных при чтении. Strong consistency гарантирует актуальность данных (запрос перенаправляется на лидера). Stale consistency снижает задержку, но позволяет получить устаревшие данные.

**Performance Replication** — режим репликации между кластерами Vault Enterprise, распределяющий чтение и запись по нескольким кластерам в разных географических регионах. Кластеры-реплики имеют собственные лидеры и политики.

**DR Replication (Disaster Recovery Replication)** — режим репликации Vault Enterprise для аварийного восстановления. DR Secondary кластер находится в отдельном region/datacenter и получает асинхронную репликацию данных от основного (Performance) кластера. При отказе основного кластера DR Secondary может быть повышен до активного.

**Multi-DC (Multi-Datacenter)** — архитектура с несколькими кластерами Vault в разных дата-центрах, связанных репликацией. Обеспечивает отказоустойчивость и географическое распределение нагрузки.

**WAL (Write-Ahead Log)** — журнал предзаписи, используемый Raft для репликации. WAL гарантирует, что записи не потеряются при сбое.

**Commit Index** — индекс последнего зафиксированного (committed) записи в Raft-логе. Используется для определения, насколько синхронизирован follower с лидером.

## Основные концепции

### Архитектура HA-кластера

Vault является master-slave системой:

- **Active Node:** Единственный узел, обслуживающий записи (write) и чтения (read при strong consistency).
- **Standby Node:** Резервный узел, синхронизирующий данные через Raft. При сбое лидера автоматически становится active.
- **Performance Standby (Enterprise):** Standby-узел, обслуживающий read-only запросы локально.

### Режимы репликации (Enterprise)

| Режим | Назначение | Согласованность | Failover |
| :--- | :--- | :--- | :--- |
| **DR Replication** | Аварийное восстановление — полная репликация данных, включая токены и leases | Асинхронная (best-effort) | Ручной (через promote + `dr_operation_token`) |
| **Performance Replication** | Горизонтальное масштабирование read-only нагрузки (KV, Transit). Secondary обслуживает чтения, write — пересылает на primary | Асинхронная (near real-time) | Ручной (через promote); read failover автоматический через LB |

### Жизненный цикл запроса

1. **Клиент отправляет запрос** на Vault.
2. **Load Balancer** направляет запрос на любой узел кластера.
3. **Если strong consistency:** запрос перенаправляется на active-лидер.
4. **Если stale read:** запрос обслуживается локально на standby-узле.
5. **Если Performance Standby:** read-only запрос обслуживается локально, write — перенаправляется на лидер.
6. **Raft:** запись реплицируется на большинство узлов (quorum) перед подтверждением.

### Согласованность данных

| Тип | Описание | Задержка | Use case |
| :--- | :--- | :--- | :--- |
| **Strong** | Актуальные данные, запрос к лидеру | ~10–50ms | Критичные операции, запись |
| **Stale** | Данные могут уставать до 100ms | ~1–5ms | Фоновые задачи, мониторинг, кэширование |

## Практические сценарии

### Сценарий 1: Настройка HA-кластера на Raft

#### Шаг 1: Конфигурация первого узла (vault-0)

```hcl
# /etc/vault.d/vault.hcl
ui = true

listener "tcp" {
  address       = "0.0.0.0:8200"
  cluster_address = "0.0.0.0:8201"
  tls_cert_file = "/etc/vault.d/tls/vault.crt"
  tls_key_file  = "/etc/vault.d/tls/vault.key"
}

storage "raft" {
  path    = "/opt/vault/data"
  node_id = "vault-0"
}

api_addr     = "https://vault-0.example.com:8200"
cluster_addr = "https://vault-0.example.com:8201"
```

#### Шаг 2: Конфигурация второго и третьего узлов

```hcl
# /etc/vault.d/vault.hcl (vault-1, vault-2)
storage "raft" {
  path    = "/opt/vault/data"
  node_id = "vault-1"  # или "vault-2"
  retry_join {
    leader_api_addr = "https://vault-0.example.com:8200"
  }
}

api_addr     = "https://vault-1.example.com:8200"
cluster_addr = "https://vault-1.example.com:8201"
```

#### Шаг 3: Инициализация кластера

```bash
# Инициализация (только на первом узле)
vault operator init -key-shares=5 -key-threshold=3 -format=json > cluster-keys.json

# Распечатывание на всех узлах
for i in 0 1 2; do
  kubectl exec -n vault vault-$i -- vault operator unseal $(jq -r ".unseal_keys_b64[0]" cluster-keys.json)
  kubectl exec -n vault vault-$i -- vault operator unseal $(jq -r ".unseal_keys_b64[1]" cluster-keys.json)
  kubectl exec -n vault vault-$i -- vault operator unseal $(jq -r ".unseal_keys_b64[2]" cluster-keys.json)
done
```

#### Шаг 4: Проверка кластера

```bash
# Проверка лидера
vault operator raft list-peers
# → Node       Address                        State       Voter
# → vault-0    10.0.0.1:8201                  leader      true
# → vault-1    10.0.0.2:8201                  follower    true
# → vault-2    10.0.0.3:8201                  follower    true

# Проверка статуса
vault status
# → Sealed        false
# → HA Cluster    active (self)
# → Cluster Name   vault-cluster-xxxxxx
```

### Сценарий 2: Stale Reads

#### Настройка на стороне Vault

```hcl
# server.hcl
api_addr     = "https://vault.example.com:8200"
cluster_addr = "https://vault-0.example.com:8201"
```

#### Использование через CLI

```bash
# Strong consistency (по умолчанию — запрос перенаправляется на active-лидер):
vault kv get secret/data/myapp/config

# Stale read — запрос к standby-узлу (данные могут устаревать до 100ms)
# Заголовок X-Vault-Stale-Read НЕ существует в API Vault.
# Stale reads достигаются простым запросом к standby-узлу:
vault kv get -address=https://vault-standby.example.com:8200 \
    secret/data/myapp/config
```

#### Использование через API

```bash
# Strong consistency — запрос к active-лидеру или через forwarding:
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
     -H "X-Vault-Forward: active-node" \
     https://vault-standby.example.com:8200/v1/secret/data/myapp/config

# Stale read — запрос к standby-узлу без специальных заголовков
# (данные обслуживаются из локального состояния standby)
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
     https://vault-standby.example.com:8200/v1/secret/data/myapp/config
```

#### Использование через SDK (Python/hvac)

```python
import hvac

client = hvac.Client(url='https://vault-standby.example.com:8200', token=token)

# Stale read — запрос к standby без специальных заголовков
# (X-Vault-Stale-Read НЕ существует в Vault API)
response = client.secrets.kv.v2.read_secret_version(
    path='myapp/config',
    mount='secret'
)
```

### Сценарий 3: Performance Replication (Enterprise)

#### Настройка Performance кластера (основной)

```bash
# Включение Performance replication на primary
vault write -f sys/replication/performance/primary/enable
```

#### Генерация secondary activation token (на primary)

```bash
# secondary activation token — response-wrapped, требует аутентификации как root
# Token следует переносить на secondary машину и использовать один раз
SEC_BOOTSTRAP=$(vault write sys/replication/performance/primary/secondary-token id=secondary \
    -format=json | jq -r '.wrap_info.token')
echo "$SEC_BOOTSTRAP" > /secure/path/sec-bootstrap.token
```

#### Настройка Performance Secondary кластера

```bash
# Активация secondary на базе bootstrap token
# token — обязательный параметр; primary_api_addr — опциональный override
vault write -f sys/replication/performance/secondary/enable \
    token="$(cat /secure/path/sec-bootstrap.token)" \
    primary_api_addr="https://vault-primary.example.com:8200"
```

#### Проверка статуса репликации

```bash
# На primary кластере
vault read sys/replication/performance/status
# → state                    | active
# → mode                     | primary
# → cluster_id               | xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# → known_secondaries        | [cd0463e0-a37f-7421-345e-aad53007479f]

# На secondary кластере
vault read sys/replication/performance/status
# → state                    | stream-wals
# → mode                     | secondary
# → primary_cluster_addr     | https://vault-primary.example.com:8200
```

#### Failover для Performance Replication

```bash
# На secondary кластере
vault write -f sys/replication/performance/secondary/promote
# → Success! Data written to: sys/replication/performance/secondary/promote

# После promote: secondary становится primary
vault read sys/replication/performance/status
# → state | active
# → mode  | primary
```

### Сценарий 4: DR Replication (Enterprise)

#### Настройка DR Primary

```bash
# На primary кластере
vault write -f sys/replication/dr/primary/enable
```

#### Генерация secondary activation token (на DR Primary)

```bash
# secondary activation token для DR — response-wrapped JWT
# Token следует переносить на DR Secondary и использовать один раз
DR_BOOTSTRAP=$(vault write sys/replication/dr/primary/secondary-token id=dr-secondary \
    -format=json | jq -r '.wrap_info.token')
echo "$DR_BOOTSTRAP" > /secure/path/dr-bootstrap.token
```

#### Настройка DR Secondary

```bash
# На DR Secondary кластере
# token — обязательный параметр
vault write -f sys/replication/dr/secondary/enable \
    token="$(cat /secure/path/dr-bootstrap.token)" \
    primary_api_addr="https://vault-primary.example.com:8200"
```

#### Проверка статуса DR

```bash
# На primary
vault read sys/replication/dr/status
# → state                    | active
# → mode                     | primary
# → cluster_id               | xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# → known_secondaries        | [dr-secondary-cluster-id]

# На DR Secondary
vault read sys/replication/dr/status
# → state                    | running
# → mode                     | secondary
# → primary_cluster_addr     | https://vault-primary.example.com:8200
```

#### Аварийное восстановление через DR Secondary

```bash
# DR promote требует dr_operation_token (Vault 2.0.0+)
# Сгенерировать DR operation token на primary:
# vault write sys/replication/dr/secondary/generate-operation-token/attempt
# (требует порог unseal/recovery ключей)

# На DR Secondary кластере
vault write sys/replication/dr/secondary/promote \
    dr_operation_token=<DR_OPERATION_TOKEN>

# После promote: DR Secondary становится активным кластером
vault read sys/replication/dr/status
# → state | active
# → mode  | primary
```

#### Переключение трафика

```bash
# 1. Обновление DNS/load balancer на новый активный кластер
# 2. Проверка работоспособности
curl https://vault-dr-secondary.example.com:8200/v1/sys/health
# → {"initialized":true,"sealed":false,...}

# 3. При необходимости: перенастройка клиентов на новый cluster_addr
```

### Сценарий 5: Мониторинг производительности

#### Ключевые метрики

```bash
# Проверка метрик Prometheus
curl -s https://vault.example.com:8200/v1/sys/metrics | grep vault_
```

| Метрика | Описание | Норма | Алерт |
| :--- | :--- | :--- | :--- |
| `vault.raft.commitTime` | Время коммита записи в Raft (ms) | < 50ms | > 100ms |
| `vault.raft.apply` | Время применения записи | < 10ms | > 50ms |
| `vault.core.unsealed` | Состояние распечатанности | 1 | 0 |
| `vault.cache.hit` / `vault.cache.miss` | Эффективность кэша | > 80% hit | Рост miss |
| `vault.token.count.by_policy` | Количество токенов | Мониторинг роста | Всплеск без объяснения |
| `vault.runtime.lease.count` | Количество активных lease | Мониторинг | Рост без границ |

#### Настройка Prometheus exporter

```hcl
# server.hcl
telemetry {
  prometheus_enabled = true
  prometheus_retention_time = "30s"
}
```

#### Дашборд Grafana (основные панели)

1. **Raft Commit Time:** `vault_raft_commit_time` — время репликации между узлами
2. **Leader Status:** `vault_core_leader` — какой узел является лидером
3. **Token Count:** `vault_token_count_by_policy` — количество токенов по политикам
4. **Cache Hit Ratio:** `vault_cache_hit / (vault_cache_hit + vault_cache_miss)` — эффективность кэша
5. **Lease Count:** `vault_runtime_lease_count` — количество активных аренд
6. **Request Rate:** `vault_request_count` — общее число запросов

### Сценарий 6: Настройка Load Balancer

```nginx
# upstream-vault.conf
upstream vault_cluster {
    least_conn;
    server vault-0.example.com:8200 max_fails=3 fail_timeout=10s;
    server vault-1.example.com:8200 max_fails=3 fail_timeout=10s;
    server vault-2.example.com:8200 max_fails=3 fail_timeout=10s;
}

server {
    listen 8200;
    server_name vault.example.com;

    location / {
        proxy_pass https://vault_cluster;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Vault-Request true;

        # TLS
        proxy_ssl_verify on;
        proxy_ssl_verify_depth 2;
        proxy_ssl_trusted_certificate /etc/nginx/ca.crt;
    }
}
```

### Сценарий 7: Graceful Degradation при потере кворума

При потере более половины узлов кластер теряет лидера и перестаёт обслужвать запросы (см. детали в [Сценарии 3: Восстановление после потери кворума](./backup_restore_strategies.md#сценарий-3-восстановление-после-потери-кворума)).

### Сценарий 8: Миграция с Consul на Raft

Подробная инструкция по миграции с Consul backend на Raft — в **[Vault с Consul бэкендом](./vault_with_consul_backend.md#миграция-с-consul-на-raft)**. Кратко: создайте снапшот Consul (`consul snapshot save`), выполните `vault operator migrate -config=migrate.hcl` с остановленным Vault, затем запустите с конфигурацией `storage "raft"` и распечатайте узлы.

#### Валидация и проверка

```bash
# Проверка состояния HA-кластера после всех настроек:
vault status
# → Sealed: false, HA Cluster: active (self), performance_standby: true

# Проверка репликации:
vault read sys/replication/performance/status | jq -r '.data.mode, .data.state'
vault read sys/replication/dr/status | jq -r '.data.mode, .data.state'
```

## Операции и команды

### CLI: управление репликацией

| Команда | Описание | Требования |
| :--- | :--- | :--- |
| `vault write -f sys/replication/performance/primary/enable` | Включить Performance Replication на primary | Enterprise, root |
| `vault write sys/replication/performance/primary/secondary-token id=<id>` | Сгенерировать bootstrap token для secondary | Enterprise, root, response-wrapped |
| `vault write -f sys/replication/performance/secondary/enable token=<token>` | Активировать secondary | Token от primary |
| `vault write -f sys/replication/performance/secondary/promote` | Повысить secondary до primary | Enterprise, root |
| `vault write -f sys/replication/performance/primary/disable` | Отключить Performance Replication на primary | Enterprise, root |
| `vault write -f sys/replication/dr/primary/enable` | Включить DR Replication на primary | Enterprise, root |
| `vault write sys/replication/dr/primary/secondary-token id=<id>` | Сгенерировать bootstrap token для DR secondary | Enterprise, root, response-wrapped |
| `vault write -f sys/replication/dr/secondary/enable token=<token>` | Активировать DR secondary | Token от primary |
| `vault write sys/replication/dr/secondary/promote dr_operation_token=<token>` | Повысить DR secondary до primary | Enterprise, root, dr_operation_token |
| `vault write -f sys/replication/dr/secondary/reindex` | Переиндексировать DR secondary | Enterprise |

### API endpoints репликации

| Метод | Путь | Описание |
| :--- | :--- | :--- |
| `POST` | `/sys/replication/performance/primary/enable` | Включить Performance primary |
| `POST` | `/sys/replication/performance/primary/secondary-token` | Сгенерировать bootstrap token |
| `POST` | `/sys/replication/performance/secondary/enable` | Активировать Performance secondary |
| `POST` | `/sys/replication/performance/secondary/promote` | Повысить Performance secondary |
| `GET` | `/sys/replication/performance/status` | Статус Performance репликации |
| `POST` | `/sys/replication/dr/primary/enable` | Включить DR primary |
| `POST` | `/sys/replication/dr/primary/secondary-token` | Сгенерировать DR bootstrap token |
| `POST` | `/sys/replication/dr/secondary/enable` | Активировать DR secondary |
| `POST` | `/sys/replication/dr/secondary/promote` | Повысить DR secondary (требует `dr_operation_token`) |
| `GET` | `/sys/replication/dr/status` | Статус DR репликации |
| `GET` | `/sys/replication/status` | Общий статус репликации |
| `POST` | `/sys/replication/recover` | Попытка восстановления при сбое репликации |
| `POST` | `/sys/replication/reindex` | Переиндексация данных (требует sudo) |
| `POST` | `/sys/replication/merkle-check` | Проверка целостности Merkle tree |

## Лучшие практики

1. **Нечётное число узлов:** Используйте 3, 5 или 7 узлов для HA-кластера. Чётное число усложняет достижение кворума.
2. **Raft Integrated Storage:** Используйте Raft как стандарт для новых инсталляций. Consul — только для миграций.
3. **Performance Standby:** Для production сред с высокой читающей нагрузкой используйте Performance Standby ноды (Enterprise).
4. **Stale reads:** Используйте stale reads только для не критичных операций (мониторинг, фоновые задачи).
5. **Load Balancer:** Настройка LB с health checks (`/v1/sys/health`) и `max_fails` для автоматического исключения неработающих узлов.
6. **Мониторинг Raft:** Следите за `vault.raft.commitTime` и `vault.raft.apply`. Рост этих метрик указывает на проблемы с сетью или диском.
7. **Репликация:** Для географически распределённых сред используйте Performance Replication. Для DR — DR Replication.
8. **Graceful failover:** Планируйте процедуры failover и тестируйте их регулярно.

#### Валидация и проверка

```bash
# Проверка что репликация синхронизирована:
vault read sys/replication/dr/status | jq -r '.data.secondaries[0].connection_status'
# → connected

# Проверка что Performance secondary обслуживает запросы:
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
    https://vault-secondary.example.com:8200/v1/secret/data/myapp/config
# → {"data": {"data": {...}}}
```

#### Очистка и откат

```bash
# Отключение DR Replication (на DR Primary):
vault write -f sys/replication/dr/primary/disable

# Отключение Performance Replication (на Performance Primary):
vault write -f sys/replication/performance/primary/disable

# Отключение Performance Secondary (на бывшем secondary):
vault write -f sys/replication/performance/secondary/disable

# Удаление bootstrap token (одноразовое использование):
shred -u /secure/path/sec-bootstrap.token /secure/path/dr-bootstrap.token

# Ротация secondary activation token (security best practice):
vault write sys/replication/performance/primary/secondary-token id=secondary-new \
    -format=json | jq -r '.wrap_info.token'

## Устранение неполадок

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `replication is already enabled` | Репликация уже включена на этом кластере | Выполнить `promote` вместо `enable`, либо `disable` и повторить |
| `replication is not enabled` при `promote` | Кластер не настроен как secondary | Включить `secondary/enable` с корректным `token` |
| `invalid secondary token` | Bootstrap token истёк или используется неверный token | Сгенерировать новый token на primary, убедиться что он не использован |
| `dr_operation_token required` на promote | DR promote требует DR operation token | Сгенерировать через `sys/replication/dr/secondary/generate-operation-token/attempt` |
| `merkle tree corruption` | Повреждение Merkle tree на secondary | Выполнить `vault write -f sys/replication/reindex` |
| `connection refused` / `timeout` на secondary | Сетевые проблемы между кластерами | Проверить connectivity на cluster port (8201), firewall rules, TLS сертификаты |
| `clock skew detected` | Расхождение времени между узлами | Синхронизировать время через NTP (chrony/systemd-timesyncd) |
| `seal configuration mismatch` | Secondary использует другой seal | После включения replication seal конфигурация secondary заменяется на primary; при необходимости обновить recovery keys/unseal keys |

### Диагностика

#### 1. Проверка статуса репликации

```bash
# Полный статус (включает DR и Performance):
vault read sys/replication/status -format=json | jq
# → state, mode, connection_state, known_secondaries, primaries
```

#### 2. Проверка сети между кластерами

```bash
# Проверка cluster port (8201):
nc -zv vault-primary.example.com 8201
# → Connection to vault-primary.example.com port 8201 [TCP/*] succeeded!

# Проверка TLS на cluster порту:
openssl s_client -connect vault-primary.example.com:8201 -servername vault-primary.example.com
```

#### 3. Проверка Merkle tree перед reindex

```bash
# Рекомендуется перед perindex:
vault write sys/replication/merkle-check
# → merkle_corruption_report: { corrupted_root: false, ... }
```

#### 4. Аудит логов

```bash
# Поиск ошибок репликации в audit логах:
vault audit list -format=json | jq -r '.[] | select(.request.path | contains("replication"))'

# Journalctl (systemd):
journalctl -u vault -n 100 --no-pager | grep -i replication
```

### Ограничения

- **Raft и сетевая задержка:** Высокая латентность между узлами (>50ms) увеличивает время коммита и снижает производительность.
- **Performance Standby (Enterprise):** Доступен только в Enterprise версии. В OSS standby-узлы не обслуживают read-запросы.
- **Stale reads:** Данные могут устаревать до 100ms. Не подходит для операций, требующих актуальных данных.
- **Потеря кворума:** При потере >50% узлов кластер переходит в Sealed. Восстановление возможно только из снапшота.
- **Миграция Consul → Raft:** Требуется остановка кластера. Планируйте миграцию во время окна обслуживания.
- **Version compatibility:** Secondary может работать на новой версии Vault, но работа на разных версиях дольше 1 недели не рекомендуется.
- **Seal replacement:** При включении replication на secondary, его seal конфигурация заменяется конфигурацией primary.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и HA.
*   **[Основные концепции Vault](../concepts.md)** — Raft, Seal/Unseal, Identity.
*   **[Установка Vault](../guides/vault_installation.md)** — развёртывание HA-кластера.
*   **[Vault с Consul бэкендом](./vault_with_consul_backend.md)** — альтернативный бэкенд.
*   [Официальная документация по репликации](https://developer.hashicorp.com/vault/docs/enterprise/replication)
