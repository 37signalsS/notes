# Cross-Cluster Replication и Cross-Cluster Search

**Актуально для:** Elasticsearch 9.5.x / 8.19 LTS

> Руководство по межкластерной репликации данных (CCR) и поиску через кластеры (CCS). Рассматриваются use cases, настройка, API и паттерны для DR и geo-distributed search.
>
> Связанные темы: capacity planning — [Capacity Planning](./elasticsearch_capacity_planning.md); безопасность — [Security Advanced](./elasticsearch_security_advanced.md); сеть — [Network и Firewall](../elasticsearch_network_requirements.md).

## Определения

* **Cross-Cluster Replication (CCR)** — асинхронная репликация индексов из leader-кластера в follower-кластер (active-passive). Обеспечивает DR, centralized reporting и размещение данных ближе к пользователям. Платная функция: требуется лицензия Platinum+ на обоих кластерах.
* **Cross-Cluster Search (CCS)** — выполнение поисковых запросов через несколько кластеров прозрачно для клиента. Доступна на уровне Basic (ES|QL через CCS требует Enterprise на всех участвующих кластерах).
* **Leader Cluster** — кластер-источник данных для CCR. Индекс может иметь только одного leader; follower-индексы pull-ят изменения с leader.
* **Follower Cluster** — кластер-приемник реплицируемых данных. Follower-индекс read-only во всех конфигурациях.
* **Remote Cluster** — конфигурация подключения к удалённому кластеру (на уровне кластера). Общая основа для CCS и CCR.
* **Sniff mode** — режим подключения по умолчанию: координирующий узел обнаруживает узлы remote-кластера через seed-адреса (transport-порт 9300).
* **Proxy mode** — подключение через L4-прокси (`proxy_address`); используется в Kubernetes и за балансировщиками, когда узлы remote-кластера не имеют доступных publish-адресов.
* **Cross-cluster API key** — API-ключ, созданный администратором на remote-кластере и хранимый в keystore локального кластера (`cluster.remote.<alias>.credentials`). Рекомендуемая модель безопасности с 8.14: все cross-cluster запросы ограничены привилегиями этого ключа, независимо от локальных пользователей.
* **Retention lease** — аренда удержания на leader-индексе: гарантирует, что шард leader сохранит историю операций, необходимую follower-шарду.
* **Remote recovery** — начальная загрузка follower-индекса: копирование Lucene-сегментов с primary-шарда leader (по умолчанию 5 параллельных фрагментов по 1 МБ).
* **Global checkpoint** — номер последней операции, применённой всеми активными копиями шарда. Разница `leader_global_checkpoint - follower_global_checkpoint` — отставание follower.

## Архитектура CCR

### Модель Leader-Follower

```
┌─────────────────┐         ┌─────────────────┐
│  Leader Cluster │  CCR    │ Follower Cluster│
│  (us-east)      │────────▶│ (eu-west)       │
│                 │  async  │                 │
│  index: logs-*  │         │ index: logs-*   │
│  read-write     │         │ read-only       │
└─────────────────┘         └─────────────────┘
```

CCR использует active-passive модель: запись идёт только в leader-индекс, follower-индексы pull-ят изменения. Репликация выполняется на уровне шардов: follower-индекс имеет столько же шардов, сколько leader, и каждый follower-шард тянет изменения со своего corresponding-шарда leader. Поддерживаются uni-directional (один кластер — только leader, другой — только follower) и bi-directional (каждый кластер содержит и leader-, и follower-индексы) конфигурации.

### Поток данных

```
Leader Cluster                         Follower Cluster
┌──────────┐    Auto-follow Pattern    ┌──────────┐
│ Index A  │ ────────────────────────▶ │ Index A  │
│ Index B  │ ────────────────────────▶ │ Index B  │
│ Index C  │ ────────────────────────▶ │ Index C  │
└──────────┘                           └──────────┘
        │
        ▼
   New Index D  ──auto followed──▶      Index D
```

При создании follower-индекса выполняется remote recovery: follower запрашивает recovery-сессию на primary-шарде leader и параллельно запрашивает фрагменты файлов. Далее follower непрерывно читает историю операций из translog leader (для этого на leader должны быть включены soft deletes — по умолчанию для индексов, созданных с 7.0).

## Архитектура CCS

### Прозрачный поиск через кластеры

```
                     ┌─────────────────┐
                     │   Application   │
                     └────────┬────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │ Local Cluster   │  (координирующий)
                     │ (us-east)       │
                     └────────┬────────┘
                              │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
      ┌────────────┐  ┌────────────┐  ┌────────────┐
      │ us-east    │  │ eu-west    │  │ ap-south   │
      │ (local)    │  │ (remote)   │  │ (remote)   │
      └────────────┘  └────────────┘  └────────────┘
```

Координирующий узел локального кластера рассылает запрос remote-кластерам, собирает результаты и выполняет reduce-фазу. Индексы remote-кластеров адресуются как `<remote_cluster_name>:<index>`. Документы из remote-индексов возвращаются с префиксом кластера в поле `_index` (например, `cluster_one:my-index-000001`).

## Настройка remote cluster

Remote cluster — обязательное условие для CCS и CCR. Настраивается на локальном (принимающем) кластере.

### Через elasticsearch.yml (статическая)

```yaml
# На каждом узле кластера; настройка действует только на узлах, где указана
cluster:
  remote:
    us-east:
      seeds:
        - us-east-es-node1:9300
        - us-east-es-node2:9300
        - us-east-es-node3:9300
      skip_unavailable: false
```

### Через API (динамическая, рекомендуется)

```bash
# На принимающем кластере (eu-west)
PUT _cluster/settings
{
  "persistent": {
    "cluster": {
      "remote": {
        "us-east": {
          "seeds": [
            "us-east-es-node1:9300",
            "us-east-es-node2:9300",
            "us-east-es-node3:9300"
          ],
          "skip_unavailable": false
        }
      }
    }
  }
}
```

Динамические настройки действуют на весь кластер. При изменении `transport.compress` или `transport.ping_schedule` существующие соединения закрываются и переоткрываются — in-flight запросы могут завершиться ошибкой.

### API key модель (рекомендуется, 8.14+)

1. На remote-кластере включите remote cluster server (отдельный порт, по умолчанию 9443):

   ```yaml
   xpack.security.remote_cluster_server.ssl.keystore.path: cross-cluster.p12
   ```

2. На remote-кластере создайте cross-cluster API key (операция Create Cross-Cluster API key — `POST /_security/api_key`, либо Kibana → Management → Remote Clusters), включив доступ к нужным индексам. Скопируйте encoded key из ответа.
3. На локальном кластере добавьте ключ в keystore:

   ```bash
   ./bin/elasticsearch-keystore add cluster.remote.us-east.credentials
   # → вставить encoded cross-cluster API key
   ```

4. Настройте `cluster.remote.us-east.seeds` на remote cluster server port (9443) вместо transport-порта.
5. Примените без перезапуска: `POST _nodes/reload-secure-settings`.

Локальные пользователи получают доступ через роли с `remote_indices`-привилегиями (см. раздел про привилегии). Эффективный доступ пользователя — пересечение привилегий его роли и привилегий cross-cluster API key.

### TLS certificate модель (deprecated с 9.0)

Альтернативная модель: роли с одинаковыми именами на обоих кластерах, авторизация пересылается на remote-кластер. Deprecated с 9.0 — используйте API key модель. Миграция описана в документации Elastic (remote clusters migrate).

### Настройки remote cluster

| Настройка | Default | Описание |
|-----------|---------|----------|
| `cluster.remote.<alias>.seeds` | — | Список seed-адресов `host:port` (transport 9300 или remote server 9443 в API key модели) |
| `cluster.remote.<alias>.mode` | `sniff` | `sniff` или `proxy` |
| `cluster.remote.<alias>.proxy_address` | — | Адрес L4-прокси (proxy mode) |
| `cluster.remote.<alias>.proxy_socket_connections` | `18` | Число сокетных соединений к прокси |
| `cluster.remote.<alias>.server_name` | — | SNI-имя (proxy mode) |
| `cluster.remote.<alias>.skip_unavailable` | `true` (с 8.15; ранее `false`) | `true` — кластер опционален: пропускается при недоступности; `false` — кластер обязателен, его недоступность падает запрос |
| `cluster.remote.<alias>.transport.ping_schedule` | `-1` | Интервал application-level ping. Предпочтительны TCP keepalives (включены по умолчанию на remote-соединениях) |
| `cluster.remote.<alias>.transport.compress` | глобальный `transport.compress` | Сжатие запросов к remote-кластеру: `true` / `indexing_data` / `false` |
| `cluster.remote.initial_connect_timeout` | `30s` | Таймаут установления remote-соединений при старте узла |
| `cluster.remote.<alias>.credentials` | — | Cross-cluster API key в keystore (API key модель, secure + reloadable) |

Удалить remote-кластер — обнулить seeds:

```bash
PUT _cluster/settings
{
  "persistent": {
    "cluster": {
      "remote": {
        "us-east": {
          "seeds": null
        }
      }
    }
  }
}
```

### Проверка соединения

```bash
GET _remote/info
```

```json
{
  "us-east": {
    "connected": true,
    "mode": "sniff",
    "seeds": ["us-east-es-node1:9300"],
    "num_nodes_connected": 3,
    "max_connections_per_cluster": 3,
    "initial_connect_timeout": "30s",
    "skip_unavailable": false
  }
}
```

В API key модели ответ дополнительно содержит `cluster_credentials`.

### Роли узлов

По умолчанию любой узел может выступать cross-cluster client (`remote_cluster_client` входит в `node.roles`). Исключите `remote_cluster_client` из `node.roles`, чтобы запретить узлу подключаться к remote-кластерам. Требования:

* CCS: запросы к remote-кластерам должны приходить на узел с ролью `remote_cluster_client` (координирующий узел).
* CCR: все master-узлы локального кластера должны также иметь роль `remote_cluster_client`; минимум один узел с data-ролью и `remote_cluster_client`.
* ML data feeds и transforms также требуют `remote_cluster_client`.

## Cross-Cluster Search (CCS)

### Синтаксис запроса

```bash
# Поиск в remote-кластере
GET us-east:logs-*/_search
{
  "query": {
    "match": { "message": "error" }
  }
}

# Поиск по локальному и remote-кластерам одновременно
GET logs-*,us-east:logs-*/_search
{
  "query": { "match_all": {} }
}

# Wildcard в имени кластера поддерживается
GET cluster_*:logs-*/_search
{
  "query": { "match_all": {} }
}

# Агрегация через кластеры
GET logs-*/_search
{
  "size": 0,
  "aggs": {
    "by_cluster": {
      "terms": {
        "field": "_index",
        "size": 10
      }
    }
  }
}
```

### Опции запроса

| Опция | Default | Описание |
|-------|---------|----------|
| `ccs_minimize_roundtrips` | `true` (для sync; `false` для async search) | Минимизировать число network roundtrips: один запрос на кластер вместо can-match + запрос на шард. Лучше для большого числа шардов и высокой latency. Не применяется к scroll и inner hits |
| `allow_partial_search_results` | `true` | `true` — возвращать частичные результаты при таймаутах/сбоях шардов; `false` — ошибка без частичных результатов. Кластерная настройка `search.default_allow_partial_results` |
| `max_concurrent_shard_requests` | `5` | Число параллельных shard-запросов на узел; ограничивает влияние поиска на кластер |

`preference` управляет выбором шардов на локальном узле (`_local` — по возможности шарды локального узла, `_only_local` — только шарды локального узла). Отдельного значения «предпочитать локальный кластер» нет: для снижения latency адресуйте локальные индексы явно или полагайтесь на adaptive replica selection.

### Секция `_clusters` в ответе

При поиске по remote-кластерам ответ содержит секцию `_clusters` со статусом каждого кластера:

```json
"_clusters": {
  "total": 3,
  "successful": 2,
  "skipped": 0,
  "running": 0,
  "partial": 1,
  "failed": 0,
  "details": {
    "(local)": { "status": "successful", "indices": "logs-*", "took": 21, "_shards": { "total": 10, "successful": 10, "failed": 0 } },
    "us-east": { "status": "successful", "indices": "logs-*", "took": 48, "_shards": { "total": 12, "successful": 12, "failed": 0 } },
    "eu-west": { "status": "partial", "indices": "logs-*", "took": 2039, "_shards": { "total": 6, "successful": 5, "failed": 1 }, "failures": [ ... ] }
  }
}
```

Статусы: `successful`, `skipped` (кластер с `skip_unavailable: true` недоступен), `running` (async search), `partial` (часть шардов не выполнилась), `failed` (все шарды не выполнились или кластер с `skip_unavailable: false` недоступен). Наличие `failed`-кластера приводит к HTTP 500 и top-level `error`.

### Исключение кластеров и индексов (9.5+)

При использовании wildcards можно исключить кластер или индекс префиксом `-`:

* `-mycluster:*` — исключить весь кластер (в позиции индекса обязателен `*`)
* `mycluster:-myindex` — исключить конкретный remote-индекс
* `-mycluster:myindex` — эквивалентно `mycluster:-myindex` (с 9.5)
* Комбинация `-mycluster:-myindex` недопустима

### Поддерживаемые API

Search, Async search (`ccs_minimize_roundtrips` по умолчанию `false`), Multi search, Search template, Multi search template, Field capabilities, Painless execute, Resolve Index, Vector tile search (всегда минимизирует roundtrips), ES|QL (GA с 9.1; требует Enterprise на всех кластерах), EQL и SQL (preview). Approximate kNN не поддерживает минимизацию roundtrips и принудительно устанавливает `ccs_minimize_roundtrips=false`.

### Совместимость версий

Локальный кластер может искать в remote-кластере, работающем на: предыдущей minor-версии, той же версии, более новой minor-версии в том же major. Локальный 8.19 (последняя minor 8.x) может искать любой 9.x; локальный 9.0 не может искать 8.17 или 7.17. Самый надёжный вариант — держать все кластеры на одной версии. Во время rolling upgrade локального кластера поиск по remote-кластеру допустим, если «upgrade from»/«upgrade to» версии координирующего узла совместимы с gateway-узлом remote-кластера.

### Привилегии (API key модель)

На локальном кластере создайте роль с `remote_indices`-привилегиями и назначьте её пользователю:

```bash
POST /_security/role/remote-search
{
  "remote_indices": [
    {
      "clusters": ["us-east"],
      "names": ["logs-*"],
      "privileges": ["read", "read_cross_cluster", "view_index_metadata"]
    }
  ]
}
```

Пользователь по умолчанию не имеет remote-привилегий — их нужно выдавать явно. Ключевые индекс-привилегии: `read_cross_cluster` (чтение через remote-запрос), `view_index_metadata` (метаданные индекса).

## Cross-Cluster Replication (CCR)

### Требования

* Лицензия, поддерживающая CCR (Platinum+), одинакового типа на обоих кластерах.
* `manage` cluster-привилегия для подключения remote-кластеров.
* Все master-узлы локального кластера с ролью `remote_cluster_client`; минимум один узел с data-ролью и `remote_cluster_client`.
* Soft deletes на leader-индексе (включены по умолчанию для индексов с 7.0; CCR нельзя использовать на индексах 7.0 и старше с отключёнными soft deletes).
* Follower-кластер той же или более новой версии, чем leader (при более новой — совместимость по матрице версий).
* Follower-индекс создаётся с числом шардов, равным leader-индексу.

### Привилегии

**Leader (remote) кластер** — роль с `read_ccr` и чтением leader-индекса:

```bash
POST /_security/role/remote-replication
{
  "cluster": ["read_ccr"],
  "indices": [
    {
      "names": ["logs-*"],
      "privileges": ["monitor", "read"]
    }
  ]
}
```

**Follower (local) кластер** — роль с `manage_ccr` и управлением follower-индексом:

```bash
POST /_security/role/remote-replication
{
  "cluster": ["manage_ccr"],
  "indices": [
    {
      "names": ["logs-*"],
      "privileges": ["monitor", "read", "write", "manage_follow_index"]
    }
  ]
}
```

**API key модель** — на локальном кластере роль с `remote_indices`-привилегией `cross_cluster_replication`:

```bash
POST /_security/role/remote-replication
{
  "cluster": ["manage_ccr"],
  "remote_indices": [
    {
      "clusters": ["us-east"],
      "names": ["logs-*"],
      "privileges": ["cross_cluster_replication"]
    }
  ]
}
```

Если запросы выполняются от имени других пользователей, аутентифицирующий пользователь должен иметь `run_as` на remote-кластере.

### Создание follower index

```bash
PUT logs-2026.08-copy/_ccr/follow?wait_for_active_shards=1
{
  "remote_cluster": "us-east",
  "leader_index": "logs-2026.08"
}
```

Когда API возвращает управление, follower-индекс существует и репликация запущена. До завершения remote recovery индекс недоступен для использования. Параметры тюнинга (значения по умолчанию):

| Параметр | Default | Описание |
|----------|---------|----------|
| `max_read_request_operation_count` | `5120` | Макс. операций за одно чтение с leader |
| `max_read_request_size` | `32mb` | Макс. размер пакета операций за одно чтение |
| `max_outstanding_read_requests` | `12` | Макс. одновременных чтений с leader |
| `max_write_request_operation_count` | `5120` | Макс. операций в одной bulk-записи на follower |
| `max_write_request_size` | unlimited | Макс. размер bulk-записи на follower |
| `max_outstanding_write_requests` | `9` | Макс. одновременных записей на follower |
| `max_write_buffer_count` | `2147483647` | Макс. операций в очереди записи |
| `max_write_buffer_size` | `512mb` | Макс. размер очереди записи |
| `max_retry_delay` | `500ms` | Макс. задержка повтора неудачной операции (exponential backoff) |
| `read_poll_timeout` | `1m` | Таймаут ожидания новых операций, когда follower синхронизирован с leader |

Те же параметры принимают `resume_follow` и auto-follow pattern.

### Auto-follow patterns

```bash
# Автоматическая репликация новых индексов, соответствующих паттерну
PUT _ccr/auto_follow/logs-pattern
{
  "remote_cluster": "us-east",
  "leader_index_patterns": ["logs-*"],
  "follow_index_pattern": "{{leader_index}}",
  "settings": {
    "index.number_of_replicas": 1
  }
}
```

Auto-follow предназначен для time series-индексов, периодически создаваемых на leader (например, ежедневные Beats-индексы). Особенности:

* Работает только для новых индексов, созданных после настройки паттерна; существующие индексы не подхватываются ретроспективно.
* Follower-индексы, созданные автоматически до обновления паттерна, остаются неизменными, даже если не соответствуют новым паттернам.
* `settings` позволяют переопределить часть настроек follower-индекса (например, `number_of_replicas`); число шардов переопределить нельзя.

### Управление репликацией

```bash
# Приостановить репликацию follower-индекса
POST logs-2026.08-copy/_ccr/pause_follow

# Возобновить (с возможностью изменения параметров тюнинга)
POST logs-2026.08-copy/_ccr/resume_follow
{
  "max_outstanding_read_requests": 16
}

# Информация о follower-индексах (статус active/paused, параметры)
GET logs-2026.08-copy/_ccr/follow_info

# Конвертировать follower-индекс в обычный (необратимо; индекс должен быть paused и closed)
POST logs-2026.08-copy/_ccr/unfollow

# Удалить retention leases с leader-индекса (если unfollow не смог, например при недоступности leader)
POST logs-2026.08/_ccr/forget_follower
{
  "follower_cluster": "eu-west",
  "follower_index": "logs-2026.08-copy"
}
```

Retention leases со временем истекают сами, но пока они существуют, leader-индекс хранит больше истории, чем нужно, и ILM может не выполнять часть операций. `forget_follower` не останавливает репликацию: если применить его к активно следующему индексу, follower просто добавит аренды заново.

### Мониторинг CCR

```bash
# Общая статистика: follower + auto-follow
GET _ccr/stats

# Шард-уровневая статистика конкретных follower-индексов
GET logs-2026.08-copy/_ccr/follow_stats
```

Ключевые метрики `follow_stats`:

| Метрика | Описание |
|---------|----------|
| `follower_global_checkpoint` | Последний применённый чекпоинт на follower |
| `leader_global_checkpoint` | Текущий чекпоинт leader; разница с `follower_global_checkpoint` — отставание |
| `leader_max_seq_no` / `follower_max_seq_no` | Максимальные номера последовательности |
| `operations_read` / `operations_written` | Прочитанные/записанные операции |
| `outstanding_write_requests` | Число активных bulk-записей на follower |
| `read_exceptions` | Массив неудачных чтений с leader |
| `follower_mapping_version` / `follower_aliases_version` | Версии маппинга/алиасов, до которых синхронизирован follower |

В Kibana (Operations → CCR) для каждого follower-индекса доступны «Operations behind» (разница приращений `leader_max_seq_no` и `follower_global_checkpoint` по шардам) и «Last fetch time» (время с последнего успешного чтения с leader).

## Use Cases

### 1. Disaster Recovery (DR)

```
Leader (active)          Follower (DR site)
     │                        │
     │  Continuous sync       │
     └───────────────────────▶│
                               │
     Site down!               │
                               │
     X                        ▼
                         Promote to read-write
```

**RPO:** Секунды-минуты (зависит от задержки сети и объема данных)
**RTO:** Минуты (ручное или автоматическое переключение)

Promote: `pause_follow` → `_close` → `_ccr/unfollow` → `_open` (необратимо, follower становится обычным read-write индексом). Подробный сценарий failover/failback — в [Disaster Recovery](./elasticsearch_disaster_recovery.md).

### 2. Geo-distributed Search

```
User in EU ──▶ eu-west cluster ──▶ Local data (fast)
                     │
                     └──▶ CCS to us-east, ap-south for global view
```

Снижает latency для региональных пользователей при сохранении возможности глобального поиска.

### 3. Data Locality (GDPR)

```
EU Data ──▶ eu-west cluster (stays in EU)
US Data ──▶ us-east cluster (stays in US)
```

Данные не покидают юрисдикцию, но возможен ограниченный глобальный поиск.

### 4. Hub-and-Spoke Architecture

```
                     ┌────────────┐
                     │ Hub Cluster│ (аналитика)
                     └─────┬──────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │ Spoke 1  │    │ Spoke 2  │    │ Spoke 3  │
    │ (prod)   │    │ (staging)│    │ (dev)    │
    └──────────┘    └──────────┘    └──────────┘
```

### 5. Centralized Reporting

```
Spoke clusters (prod DCs) ──CCR──▶ Hub cluster (reporting)
                                         ↓
                                  Локальный поиск и отчёты
```

Поисковая нагрузка не влияет на индексацию в прод-кластерах (search volume не снижает indexing throughput); отчёты выполняются локально на hub-кластере.

## Операции и команды (API)

### CCR API

| API | Method | Path | Описание |
|-----|--------|------|----------|
| Create follower | PUT | `/<follower_index>/_ccr/follow` | Создать follower-индекс и начать репликацию |
| Get follower info | GET | `/<follower_index>/_ccr/follow_info` | Статус (active/paused) и параметры follower-индексов |
| Get follower stats | GET | `/<follower_index>/_ccr/follow_stats` | Шард-уровневая статистика following-задач |
| Pause follower | POST | `/<follower_index>/_ccr/pause_follow` | Приостановить репликацию |
| Resume follower | POST | `/<follower_index>/_ccr/resume_follow` | Возобновить репликацию |
| Unfollow | POST | `/<follower_index>/_ccr/unfollow` | Конвертировать follower в обычный индекс (необратимо) |
| Forget follower | POST | `/<leader_index>/_ccr/forget_follower` | Удалить retention leases с leader-индекса |
| Create/update auto-follow | PUT | `_ccr/auto_follow/<name>` | Создать или обновить паттерн |
| Get auto-follow | GET | `_ccr/auto_follow/<name>` | Получить паттерн (все, если имя не указано) |
| Delete auto-follow | DELETE | `_ccr/auto_follow/<name>` | Удалить паттерн |
| Pause auto-follow | POST | `_ccr/auto_follow/<name>/_pause` | Приостановить паттерн |
| Resume auto-follow | POST | `_ccr/auto_follow/<name>/_resume` | Возобновить паттерн |
| Get CCR stats | GET | `_ccr/stats` | Общая статистика: follower + auto-follow |

### Remote cluster и CCS API

| API | Method | Path | Описание |
|-----|--------|------|----------|
| Update cluster settings | PUT | `_cluster/settings` | Динамическая настройка `cluster.remote.*` |
| Get remote cluster info | GET | `_remote/info` | Состояние remote-кластеров (connected, mode, seeds) |
| Search | GET/POST | `/<remote>:<index>/_search` | CCS-запрос |
| Async search | POST | `/_async_search` | Асинхронный CCS (`ccs_minimize_roundtrips` default `false`) |
| Multi search | POST | `/_msearch` | Пакетный CCS |
| Field capabilities | GET | `/<remote>:<index>/_field_caps` | Field capabilities через кластеры |
| Resolve index | POST | `/_resolve/index` | Разрешение индексов/дата-стримов через кластеры |

### Keystore (API key модель)

```bash
# Добавить cross-cluster API key на локальном кластере
./bin/elasticsearch-keystore add cluster.remote.us-east.credentials

# Применить без перезапуска
POST _nodes/reload-secure-settings

# Удалить credential
./bin/elasticsearch-keystore remove cluster.remote.us-east.credentials
```

### Проверка работоспособности

```bash
# 1. Соединение с remote-кластером
GET _remote/info
# → "us-east": { "connected": true, "num_nodes_connected": 3, ... }

# 2. CCS: поиск по remote-кластеру
GET us-east:logs-*/_search
{ "size": 0 }
# → "_clusters": { "total": 2, "successful": 2, "skipped": 0, "failed": 0 }

# 3. CCR: статус follower-индекса
GET logs-2026.08-copy/_ccr/follow_info
# → "follower_indices": [{ "follower_index": "logs-2026.08-copy", "leader_index": "logs-2026.08", "status": "active" }]

# 4. CCR: отставание
GET logs-2026.08-copy/_ccr/follow_stats
# → follower_global_checkpoint ≈ leader_global_checkpoint
```

## Troubleshooting

| Симптом | Причина | Решение |
|---------|---------|---------|
| `_remote/info` показывает `connected: false` | Неверные seeds, firewall, TLS | Проверить seeds (transport 9300 / remote server 9443 в API key модели), сеть, `xpack.security.transport.ssl.*`; `cluster.remote.initial_connect_timeout` |
| CCS завершается HTTP 500 с `node_disconnected_exception` | Кластер с `skip_unavailable: false` недоступен | Восстановить кластер или установить `skip_unavailable: true` |
| Кластер со статусом `skipped` в `_clusters` | `skip_unavailable: true` (default с 8.15) | Для обязательного кластера явно установить `skip_unavailable: false` |
| Follower отстаёт: растёт `leader_global_checkpoint - follower_global_checkpoint` | Сеть, latency, нагрузка | Проверить `read_exceptions`, latency (<100ms рекомендуется), увеличить `max_outstanding_read_requests` / `max_read_request_operation_count` |
| `read_exceptions` в follow stats | Ошибки чтения с leader | Проверить сеть, TLS, привилегии cross-cluster API key |
| Auto-follow не создаёт follower-индексы | Паттерн не совпадает с именем индекса; индекс создан до настройки паттерна | Проверить `leader_index_patterns`; auto-follow работает только для новых индексов |
| `unfollow` завершается ошибкой | Follower не paused или не closed | `POST /<index>/_ccr/pause_follow`, закрыть индекс, затем `unfollow` |
| Leader-кластер недоступен, retention leases не удаляются | `unfollow` не смог удалить аренды | После восстановления leader выполнить `forget_follower` |
| Ошибка лицензии при настройке CCR | Лицензия не поддерживает CCR или различается на кластерах | Platinum+ на обоих кластерах, одинаковый тип лицензии |
| CCR не реплицирует индекс, созданный до 7.0 | Soft deletes отключены | CCR требует soft deletes; используйте snapshot/restore для таких индексов |

## Best Practices

1. **API key rotation** — регулярно обновляйте cross-cluster API keys, используйте короткий expiration; ключ хранится только в keystore локального кластера.
2. **Network latency** — CCR асинхронна (pull-модель); рекомендуется <100 ms между DC, >200 ms не рекомендуется (см. [Network и Firewall](../elasticsearch_network_requirements.md)). CCS по умолчанию минимизирует roundtrips — это лучше для высокой latency.
3. **Bandwidth** — оцените объём данных в секунду; remote recovery можно rate-limit'ить динамическими настройками, чтобы не перегрузить сеть при начальной загрузке.
4. **Security** — TLS для межкластерного трафика; API key модель (с 8.14) вместо TLS certificate (deprecated с 9.0); привилегии по принципу наименьших привилегий.
5. **Monitoring** — алерты на отставание CCR (рост `leader_global_checkpoint - follower_global_checkpoint`), `read_exceptions`, «Last fetch time» в Kibana.
6. **Leader limit** — follower-индекс следует только за одним leader-индексом.
7. **Index settings** — follower наследует mappings и settings от leader; число шардов изменить нельзя; `number_of_replicas` можно задать в auto-follow `settings`. Менять маппинг/алиасы — только на leader.
8. **skip_unavailable** — осознанно: с 8.15 default `true` (кластер опционален). Для обязательных кластеров явно устанавливайте `false`, иначе CCS тихо пропустит кластер.
9. **Version policy** — держите кластеры на одной версии; для CCR follower должен быть same or newer; security-конфигурация не реплицируется — настраивайте её на каждом кластере и бэкапьте snapshots.
10. **Откат и очистка** — остановка репликации: `pause_follow` → close индекс → `unfollow`; удаление паттерна: `DELETE _ccr/auto_follow/<name>`; удаление remote-кластера: `seeds: null` + `elasticsearch-keystore remove cluster.remote.<alias>.credentials`.

## Ограничения

* **CCR:** follower-индекс read-only во всех конфигурациях; нельзя вручную менять mappings и aliases follower-индекса; write-индексы (алиасы) игнорируются.
* **CCR:** follower-индекс имеет столько же шардов, сколько leader; нельзя конвертировать обычный индекс в follower; `unfollow` необратим.
* **CCR:** реплицируются только пользовательские индексы — не реплицируются system indices (`.security`, `.kibana`), index templates, ILM-политики, Watcher-алерты и searchable snapshot indices (их данные хранятся в snapshot-репозитории; для cold/frozen tiers настраивайте репозиторий и ILM на remote-кластере).
* **CCR:** security-конфигурация (пользователи, роли, токены) не реплицируется.
* **CCR:** auto-follow работает только для новых индексов.
* **CCR:** требуется лицензия Platinum+ одинакового типа на обоих кластерах.
* **CCS:** при `allow_partial_search_results=true` (default) при сбоях результаты могут быть неполными — агрегации будут неполными, а не неточными.
* **CCS:** wildcards в именах кластеров и индексов поддерживаются (`cluster_*:logs-*`).
* **CCS:** kNN, scroll и inner hits не поддерживают минимизацию roundtrips.
* **Версии:** CCS — local ищет previous minor / same / newer minor в том же major; 8.19 → любой 9.x; 9.0+ не ищет 8.17/7.17. CCR — follower same or newer (совместимость по матрице), local same or newer включая patch-версию.

## См. также

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура кластера, шардинг.
* **[Capacity Planning](./elasticsearch_capacity_planning.md)** — планирование ресурсов для multi-cluster.
* **[Security Advanced](./elasticsearch_security_advanced.md)** — API Keys для CCR/CCS.
* **[Disaster Recovery](./elasticsearch_disaster_recovery.md)** — паттерны DR с использованием CCR.
* **[Network и Firewall](../elasticsearch_network_requirements.md)** — порты и latency для межкластерного взаимодействия.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — управление жизненным циклом.
* **[Upgrades](./elasticsearch_upgrades.md)** — CCR в blue/green-стратегии обновления.
* **[Cluster Setup](../Tutorials/cluster_setup.md)** — базовая настройка кластера.
