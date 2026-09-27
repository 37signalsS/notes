# Производительность и репликация Vault

## Определения

**Performance Standby** — режим работы standby-узлов в HA-кластере Vault Enterprise, при котором они обслуживают read-only запросы локально, не перенаправляя их лидеру. Обеспечивает горизонтальное масштабирование операций чтения (KV, Transit).

**Stale Read** — режим чтения данных, при котором запрос обслуживается локально standby-узлом без перенаправления на лидера. Данные могут уставать до 100 мс. Настраивается через заголовок `X-Vault-Stale-Read: true`.

**Read Consistency (Strong vs Stale)** — уровень согласованности данных при чтении. Strong consistency гарантирует актуальность данных (запрос перенаправляется на лидера). Stale consistency снижает задержку, но позволяет получить устаревшие данные.

**Performance Replication** — режим репликации между кластерами Vault Enterprise, распределяющий чтение и запись по нескольким кластерам в разных географических регионах. Кластеры-реплики имеют собственные лидеры и политики.

**DR Replication (Disaster Recovery Replication)** — режим репликации Vault Enterprise для аварийного восстановления. DR Secondary клаuster находится в отдельном region/datacenter и получает асинхронную репликацию данных от основного (Performance) кластера. При отказе основного кластера DR Secondary может быть повышен до активного.

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
| **DR Replication** | Аварийное восстановление | Асинхронная | Ручной (через Promote)
| **Performance Replication** | Распределение нагрузки | Синхронная (в рамках cluster) | Автоматический |

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
# Strong consistency (по умолчанию)
vault kv get secret/data/myapp/config

# Stale read (заголовок X-Vault-Stale-Read: true)
vault kv get -ns=secret -address=https://vault-standby.example.com:8200 \
    -header="X-Vault-Stale-Read: true" secret/data/myapp/config
```

#### Использование через API

```bash
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
     -H "X-Vault-Stale-Read: true" \
     https://vault-standby.example.com:8200/v1/secret/data/myapp/config
```

#### Использование через SDK (Python/hvac)

```python
import hvac

client = hvac.Client(url='https://vault-standby.example.com:8200', token=token)

# Stale read
response = client.adapter.get(
    '/v1/secret/data/myapp/config',
    headers={'X-Vault-Stale-Read': 'true'}
)
```

### Сценарий 3: Performance Replication (Enterprise)

#### Настройка Performance кластера (основной)

```bash
# Включение Performance replication
vault write -f sys/replication/performance/primary/enable
```

#### Настройка Performance Secondary кластера

```bash
# Инициализация DR/Performance Secondary
vault write -f sys/replication/performance/secondary/enable \
    primary_api_addr="https://vault-primary.example.com:8200"
```

#### Проверка статуса репликации

```bash
# На primary кластере
vault read sys/replication/performance/status
# → state                    | active
# → cluster_id               | xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# → known_secondary_clusters | [secondary-cluster-id]

# На secondary кластере
vault read sys/replication/performance/status
# → state                    | running
# → primary_cluster_addr     | https://vault-primary.example.com:8200
# → last_reindex_op          | 2026-09-24T10:00:00Z
```

#### Failover для Performance Replication

```bash
# На secondary кластере
vault write -f sys/replication/performance/secondary/promote
# → Success! Data written to: sys/replication/performance/secondary/promote

# После promote: secondary становится primary
vault read sys/replication/performance/status
# → state | active
```

### Сценарий 4: DR Replication (Enterprise)

#### Настройка DR Primary

```bash
# На primary кластере
vault write -f sys/replication/dr/primary/enable
```

#### Настройка DR Secondary

```bash
# На DR Secondary кластере
vault write -f sys/replication/dr/secondary/enable \
    primary_api_addr="https://vault-primary.example.com:8200"
```

#### Проверка статуса DR

```bash
# На primary
vault read sys/replication/dr/status
# → state                    | active
# → dr_secondary_clusters    | [dr-secondary-cluster-id]

# На DR Secondary
vault read sys/replication/dr/status
# → state                    | running
# → primary_cluster_addr     | https://vault-primary.example.com:8200
```

#### Аварийное восстановление через DR Secondary

```bash
# На DR Secondary кластере
vault write -f sys/replication/dr/secondary/promote
# → Success! Data written to: sys/replication/dr/secondary/promote

# После promote: DR Secondary становится активным кластером
vault read sys/replication/dr/status
# → state | active
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
metrics {
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

При потере >50% узлов кластер переходит в состояние Sealed:

```bash
# Проверка статуса
vault status
# → Sealed: true
# → Error: cluster has lost quorum

# Вариант 1: восстановление из снапшота (если есть)
vault operator raft snapshot restore /opt/vault/backups/vault-latest.snap

# Вариант 2: ручная правка peers.json
# 1. Остановка Vault
sudo systemctl stop vault

# 2. Редактирование /opt/vault/data/raft/peers.json
# Удалить недоступные узлы, оставить только доступные

# 3. Запуск и распечатывание
sudo systemctl start vault
vault operator unseal <key_1>
vault operator unseal <key_2>
vault operator unseal <key_3>
```

### Сценарий 8: Миграция с Consul на Raft

```bash
# 1. Создание снапшота Consul (резервная копия)
consul snapshot save /opt/consul/backups/backup-$(date +%Y%m%d).snap

# 2. Конфигурация миграции
cat > migrate.hcl <<EOF
storage_source "consul" {
  address = "127.0.0.1:8500"
  path    = "vault/"
}

storage_destination "raft" {
  path    = "/opt/vault/raft/"
  node_id = "vault-0"
}

cluster_addr = "https://vault-0.example.com:8201"
EOF

# 3. Выполнение миграции (Vault должен быть остановлен)
vault operator migrate -config=migrate.hcl

# 4. Запуск с новой конфигурацией
sudo systemctl start vault
vault operator unseal <key_1>
vault operator unseal <key_2>
vault operator unseal <key_3>
```

## Лучшие практики

1. **Нечётное число узлов:** Используйте 3, 5 или 7 узлов для HA-кластера. Чётное число усложняет достижение кворума.
2. **Raft Integrated Storage:** Используйте Raft как стандарт для новых инсталляций. Consul — только для миграций.
3. **Performance Standby:** Для production сред с высокой читающей нагрузкой используйте Performance Standby ноды (Enterprise).
4. **Stale reads:** Используйте stale reads только для не критичных операций (мониторинг, фоновые задачи).
5. **Load Balancer:** Настройка LB с health checks (`/v1/sys/health`) и `max_fails` для автоматического исключения неработающих узлов.
6. **Мониторинг Raft:** Следите за `vault.raft.commitTime` и `vault.raft.apply`. Рост этих метрик указывает на проблемы с сетью или диском.
7. **Репликация:** Для географически распределённых сред используйте Performance Replication. Для DR — DR Replication.
8. **Graceful failover:** Планируйте процедуры failover и тестируйте их регулярно.

## Ограничения и известные проблемы

- **Raft и сетевая задержка:** Высокая латентность между узлами (>50ms) увеличивает время коммита и снижает производительность.
- **Performance Standby (Enterprise):** Доступен только в Enterprise версии. В OSS standby-узлы не обслуживают read-запросы.
- **Stale reads:** Данные могут уставать до 100ms. Не подходит для операций, требующих актуальных данных.
- **Потеря кворума:** При потере >50% узлов кластер переходит в Sealed. Восстановление возможно только из снапшота.
- **Миграция Consul → Raft:** Требуется остановка кластера. Планируйте миграцию во время окна обслуживания.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и HA.
*   **[Основные концепции Vault](../concepts.md)** — Raft, Seal/Unseal, Identity.
*   **[Установка Vault](../guides/vault_installation.md)** — развёртывание HA-кластера.
*   **[Vault с Consul бэкендом](./vault_with_consul_backend.md)** — альтернативный бэкенд.
*   [Официальная документация по репликации](https://developer.hashicorp.com/vault/docs/enterprise/replication)
