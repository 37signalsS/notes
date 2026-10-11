# Cross-Cluster Search и Replication (OpenSearch)

**Актуально для:** OpenSearch 2.x / 3.x. CCR-плагин — с 1.1; CCS встроен в ядро (плагин не требуется). Возможности, появившиеся в 3.8+ (force-resume) и 3.9+ (`plugins.security.ccs.ignore_source_security_roles`), помечены в тексте.

> Поиск по нескольким кластерам (CCS) и репликация индексов между кластерами (CCR): настройка соединений, API, безопасность, мониторинг лага. Общая теория CCR/CCS — в [Elasticsearch CCR/CCS](../Elasticsearch/elasticsearch_ccr_ccs.md).

## Определения

* **CCS (Cross-Cluster Search)** — выполнение запроса одновременно к локальному и удалённым кластерам с координацией на одной ноде; результаты смешиваются. Встроен в ядро OpenSearch.
* **CCR (Cross-Cluster Replication)** — плагин `cross-cluster-replication`: непрерывная репликация индексов с leader-кластера на follower; follower-индекс доступен только для чтения.
* **Remote cluster connection** — алиас удалённого кластера, настраиваемый `cluster.remote.<alias>.seeds` (адреса transport-порта 9300).
* **Leader / Follower** — источники и приёмник CCR соответственно; все CCR-операции вызываются **на follower**.
* **Auto-follow** — правило CCR: автоматически создавать и реплицировать индексы leader, совпадающие с wildcard-паттерном.
* **`use_roles`** — при security plugin: имена ролей leader/follower, под которыми выполняются фоновые задачи репликации.
* **`remote_cluster_client`** — роль узла, участвующего в кросс-кластерных операциях. Настройка `node.remote_cluster_client` по умолчанию `true`, поэтому роль есть у любого узла; исключение её из распределения запрещает узлу подключаться к remote-кластерам.

## Cross-Cluster Search

### Настройка удалённого кластера (на coordinator-ноде)

```yaml
# opensearch.yml
cluster.remote.leader-prod.seeds:
  - "opensearch-leader.example.com:9300"
# достаточно одного адреса — нода сама разберётся с discovery остальных
```

* Порт — **transport (9300)**, не HTTP.
* Seeds перечисляют **transport-адреса удалённого кластера**. При включённом security соединение проверяется общим CA и списком `nodes_dn`; DN удалённых нод регистрируются через nodesdn API (см. CCR ниже). Обратные seeds не нужны — соединение всегда инициирует координатор.
* Режим соединения задаётся `cluster.remote.<alias>.mode`: `sniff` (default) — по seeds обнаруживаются все узлы удалённого кластера; `proxy` — соединение через фиксированный адрес `cluster.remote.<alias>.proxy_address`. Лимиты соединений: `cluster.remote.connections_per_cluster` (static, default `3`) и `cluster.remote.<alias>.node_connections` (sniff, default `3`).
* `cluster.remote.<alias>.skip_unavailable` (dynamic, default `false`) — если `true`, недоступный кластер пропускается, а не валит запрос.
* Для доступа по роли coordinator входит в распределение `remote_cluster_client` (настройка `node.remote_cluster_client`, default `true`).

### Запрос

```bash
# Имена индексов — с префиксом алиаса: <alias>:<index|wildcard>
GET leader-prod:logs-*/_search,logs-*/_search
{
  "query": { "range": { "@timestamp": { "gte": "now-1h" } } },
  "sort": [{ "@timestamp": "desc" }],
  "aggs": { "by_cluster": { "terms": { "field": "_index", "size": 20 } } }
}
```

* Каждый hit содержит поле `_index` вида `leader-prod:logs-2026.10.07` — по нему различают источник.
* `?ignore_unavailable=true` — не падать, если какой-то индекс недоступен; `skip_unavailable` для алиаса управляет поведением всего кластера по умолчанию.
* Ответ содержит блок `_clusters`: число кластеров, по которым выполнялся запрос, и результат по каждому. При `skip_unavailable: false` недоступность кластера приводит к ошибке, при `true` — кластер отмечается как пропущенный.
* Права на удалённом кластере — обычные `READ`/`SEARCH`. Параметр запроса `ccs_minimize_roundtrips` (boolean, default `true`) объединяет обращения к удалённому кластеру в один round-trip; при `ccs_minimize_roundtrips=false` удалённой стороне дополнительно требуется право `indices:admin/shards/search_shards` (иначе части плана, выполняемые удалённо, отклоняются).
* Авторизация на удалённом кластере — та же система security: пользователь/роль должен существовать и там (или действовать совместно используемые backend-роли). С 3.9 доступна настройка `plugins.security.ccs.ignore_source_security_roles` (default `false`).
* `GET _remote/info` показывает состояние соединений: `connected`, `mode`, `skip_unavailable`, число подключённых узлов (sniff) или proxy-сокетов (proxy).

## Cross-Cluster Replication

### Предусловия

1. Плагин установлен на **оба** кластера: `bin/opensearch-plugin install opensearch-cross-cluster-replication` (входит в стандартный дистрибутив сборок с плагинами).
2. Transport-соединение между кластерами настроено (тот же механизм `cluster.remote.<alias>.seeds`, что и для CCS).
3. Security: динамический список DN включён, нода follower зарегистрирована на leader:

   ```yaml
   # opensearch.yml leader (и follower — для взаимности)
   plugins.security.nodes_dn_dynamic_config_enabled: true
   ```

   ```bash
   # На leader: разрешить транспортный доступ от follower
   PUT _plugins/_security/api/nodesdn/follower
   { "nodes_dn": ["CN=follower-node1,...", "CN=follower-node2,..."] }
   ```

   * `plugins.security.nodes_dn_dynamic_config_enabled` — статическая настройка, по умолчанию `false`. Включать её нужно до регистрации DN; она требует, чтобы `plugins.security.cert.intercluster_request_evaluator_class` не был задан.
   * Список управляется эндпоинтами `GET|PUT|PATCH|DELETE _plugins/_security/api/nodesdn[/{cluster_name}]`; доступ требует admin-сертификата или права `restapi:admin/nodesdn`.

4. Права пользователя/роли, вызывающего CCR API. Официальный набор — per-index права на follower плюс чтение changes на leader:

   Права на follower-кластере:

   ```text
   indices:admin/plugins/replication/index/setup/validate
   indices:admin/plugins/replication/index/start
   indices:admin/plugins/replication/index/pause
   indices:admin/plugins/replication/index/resume
   indices:admin/plugins/replication/index/stop
   indices:admin/plugins/replication/index/update
   indices:admin/plugins/replication/index/status_check
   indices:data/write/plugins/replication/changes
   cluster:admin/plugins/replication/autofollow/update
   ```

   Права на leader-кластере:

   ```text
   indices:admin/plugins/replication/index/setup/validate
   indices:data/read/plugins/replication/file_chunk
   indices:data/read/plugins/replication/changes
   ```

   Эти права покрыты готовыми ролями `cross_cluster_replication_follower_full_access` и `cross_cluster_replication_leader_full_access` (см. `use_roles` ниже).

### Запуск репликации

```bash
# На follower
PUT _plugins/_replication/follower-01/_start
{
  "leader_alias": "leader-prod",
  "leader_index": "leader-01",
  "use_roles": {
    "leader_cluster_role": "cross_cluster_replication_leader_full_access",
    "follower_cluster_role": "cross_cluster_replication_follower_full_access"
  }
}
# → { "acknowledged": true }
```

* Follower-индекс создаётся read-only; операции над документами leader (index/update/delete) транслируются на follower. Удаление самого индекса на leader по умолчанию **не** удаляет follower (`plugins.replication.replicate.delete_index: false`).
* `use_roles` обязателен при включённом security plugin — роли предоставляет сам плагин (готовые `cross_cluster_replication_leader_full_access` / `cross_cluster_replication_follower_full_access`).

### Управление

```bash
# Статус: SYNCING | BOOTSTRAPING | PAUSED | REPLICATION NOT IN PROGRESS
GET _plugins/_replication/follower-01/_status
# → { "status": "SYNCING", "syncing_details": { "leader_checkpoint": 19, "follower_checkpoint": 19, ... } }

POST _plugins/_replication/follower-01/_pause     # пауза
POST _plugins/_replication/follower-01/_resume    # возобновление
POST _plugins/_replication/follower-01/_stop      # остановка: follower становится обычным (writeable) индексом
GET  _plugins/_replication/leader_stats            # агрегированная статистика репликации на leader
GET  _plugins/_replication/follower_stats          # агрегированная статистика на follower
GET  _plugins/_replication/autofollow_stats        # статистика auto-follow
```

* `leader_checkpoint` vs `follower_checkpoint` в `_status` — измеримый replication lag; разница растёт при сетевых проблемах или перегрузке leader.
* Follower-индекс становится **read-only** (`index.blocks.write: true`); запись в него завершается ошибкой, пока репликация не остановлена.
* Пауза ограничена retention lease лидер-индекса `index.soft_deletes.retention_lease.period` (default `12h`). Если пауза превысила лимит, обычный `_resume` не сработает. С OpenSearch **3.8** доступен принудительный ресинк: `POST _plugins/_replication/<follower-index>/_resume` с телом `{"force_resume": true}` (статус меняется `RESTORING` → `SYNCING`). В 2.x и в 3.x до 3.8 остаётся только `_stop`, удалить follower-индекс и `_start` заново (полный bootstrap).
* `_stop` открывает follower для записи — типичный сценарий failover: остановить репликацию и писать в бывший follower.

### Auto-follow

```bash
POST _plugins/_replication/_autofollow
{
  "leader_alias": "leader-prod",
  "name": "logs-autofollow",
  "pattern": "logs-*",
  "follower_index_pattern": "{{leader_index}}-rep",
  "use_roles": {
    "leader_cluster_role": "cross_cluster_replication_leader_full_access",
    "follower_cluster_role": "cross_cluster_replication_follower_full_access"
  }
}

DELETE _plugins/_replication/_autofollow
{ "leader_alias": "leader-prod", "name": "logs-autofollow" }
```

* Новый leader-индекс под паттерн → автоматически создаётся follower и стартует репликация.
* `follower_index_pattern` — необязательное переименование на follower через placeholder `{{leader_index}}` (избегает коллизии одноимённых индексов).
* `GET _plugins/_replication/autofollow_stats` — выполняются ли правила, есть ли ошибки.

## Настройки репликации

Кластерные настройки (динамические, если не указано иное):

| Настройка | Default | Назначение |
|---|---|---|
| `plugins.replication.follower.concurrent_readers_per_shard` | `2` | Число параллельных читателей транзакционного лога на шард follower |
| `plugins.replication.autofollow.fetch_poll_interval` | `30s` | Периодичность опроса leader на новые индексы под auto-follow |
| `plugins.replication.follower.metadata_sync_interval` | `60s` | Периодичность сверки метаданных leader/follower |
| `plugins.replication.translog.retention_lease.pruning.enabled` | `true` | Прунинг (очистка) retention lease транзакционного лога |
| `plugins.replication.translog.retention_size` | `512 MB` | Лимит размера retention lease транзакционного лога |
| `plugins.replication.replicate.delete_index` | `false` | Удаление индекса на leader не удаляет follower (если `true` — каскадное удаление) |
| `plugins.replication.follower.index.ops_batch_size` | `50000` | Размер батча операций при репликации |

Индексная настройка:

| Настройка | Default | Назначение |
|---|---|---|
| `index.plugins.replication.follower.ops_batch_size` | `50000` | Переопределение размера батча на конкретном follower-индексе |

Bulk replication (массовая репликация нескольких индексов, Bulk Replication API):

| Настройка | Default | Диапазон |
|---|---|---|
| `plugins.replication.follower.bulk_batch_size` | `10` | `1`–`100` |
| `plugins.replication.follower.bulk_poll_timeout` | `15` | `1`–`30` (минуты) |

## Мониторинг

```bash
# Статус и лаг по конкретному follower
GET _plugins/_replication/follower-01/_status?verbose=true

# Агрегированная статистика по всем индексам
GET _plugins/_replication/leader_stats
GET _plugins/_replication/follower_stats

# Незавершённые/сбойные задачи репликации — через task API
GET _tasks?actions=*replication*&detailed

# CCS-соединения
GET _remote/info
```

Алертинг на лаг: мониторы Alerting работают по индексам, а не по REST-эндпоинту `_status`, поэтому значения `leader_checkpoint`/`follower_checkpoint` нужно периодически выгружать в индекс (скриптом/экспортёром) и строить по нему query-level монитор (см. [Alerting](./opensearch-alerting.md)).

## Troubleshooting

### _start: connection не найден / нет соединения

1. `GET _remote/info` — есть ли алиас; `cluster.remote.<alias>.seeds` задан на ноде, принимающей запрос.
2. Порт 9300 открыт между кластерами, общий CA, `nodes_dn` содержит DN нод обеих сторон.
3. `plugins.security.nodes_dn_dynamic_config_enabled: true` и `PUT _plugins/_security/api/nodesdn/<follower>` на leader.

### Репликация не стартует: права

1. `use_roles` не передан при включённом security plugin — добавить с готовыми ролями CCR.
2. Сверить права пользователя, вызывающего API, с официальным набором (см. «Предусловия», п. 4: `indices:admin/plugins/replication/*`, `indices:data/write/plugins/replication/changes`) — на follower и на leader.

### Статус BOOTSTRAPING вечно

1. Начальная синхронизация больших индексов идёт долго — следить за прогрессом в `_status?verbose=true`.
2. Лидер перегружен или сеть узкая — смотреть throughput репликации, при необходимости пересоздать после освобождения ресурсов.

### PAUSED и _resume не работает

1. Пауза превысила retention lease leader-индекса (default `12h`): на 3.8+ попробовать `_resume` с `{"force_resume": true}`; иначе — `_stop`, удалить follower-индекс, запустить `_start` заново (полный bootstrap).
2. Проверить `plugins.replication.translog.retention_size` и `index.soft_deletes.retention_lease.period` — при интенсивной записи lease вытесняется быстрее.
3. Если индекс критичен — остановить писателей и убедиться, что данные leader актуальны.

### CCS: удалённый кластер в ошибке

1. `ignore_unavailable=true` или `skip_unavailable` для алиаса — если недоступность допустима.
2. Права пользователя на удалённой стороне; при `ccs_minimize_roundtrips: false` — `indices:admin/shards/search_shards`.
3. Разные версии security-конфигурации: пользователь существует только локально — создать/смаппить на удалённом.

## Best Practices

1. CCR и CCS использовать по прямому назначению: CCR — DR/Read-scaling, CCS — единая точка запроса, **не** как замена репликации.
2. Follower — read-only: заранее согласовать сценарий failover (`_stop` → запись) и кто его инициирует.
3. Auto-follow для динамических (ротируемых) индексов; ручной `_start` — для статичных.
4. Контролировать лаг (`_status`) и алертить на рост checkpoint-разницы.
5. Учитывать retention lease (`index.soft_deletes.retention_lease.period`, default `12h`): пауза дольше лимита требует `force_resume` (3.8+) либо полного пересоздания follower — планировать непрерывную репликацию или осознанный пересинк.
6. Безопасность: минимальные `nodes_dn`, отдельные роли CCR, не давать `full_access` шире необходимого.
7. Для поиска по мульти-кластеру — `skip_unavailable` осознанно: `false` (default) для критичных данных (лучше упасть, чем тихо получить неполную выборку), `true` для best-effort аналитики.
8. Держать версии leader и follower совместимыми: официальные правила совместимости CCR в документации OpenSearch не описаны явно, но на практике follower не должен быть старше leader — при апгрейде обновляйте follower первым (неофициальное правило, проверяйте под свою версию).
9. `plugins.replication.replicate.delete_index` по умолчанию `false`: удаление индекса на leader не удаляет follower. Учитывать это в жизненном цикле (например, в ISM), иначе на follower накопятся «осиротевшие» индексы.

## Дополнительная информация

* [Elasticsearch CCR/CCS](../Elasticsearch/elasticsearch_ccr_ccs.md) — общая теория, сравнение механизмов (учтите: лицензия, дефолт `skip_unavailable` и правила версий в Elasticsearch отличаются от OpenSearch).
* [OpenSearch: Обзор](./opensearch_overview.md) — архитектура кластера.
* [OpenSearch Administration](./opensearch_administration.md) — транспортный TLS, ноды, кластерные настройки.
* [Снапшоты и DR](./opensearch-disaster-recovery.md) — CCR как элемент стратегии восстановления.
* [Alerting](./opensearch-alerting.md) — мониторы для контроля лага.
* Документация OpenSearch: [Cross-cluster search](https://docs.opensearch.org/latest/search-plugins/cross-cluster-search/), [Cross-cluster replication](https://docs.opensearch.org/latest/tuning-your-cluster/replication-plugin/index/).
