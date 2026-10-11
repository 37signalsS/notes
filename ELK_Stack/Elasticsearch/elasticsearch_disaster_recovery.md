# Elasticsearch: Disaster Recovery (паттерны аварийного восстановления)

**Актуально для:** Elasticsearch 8.x / 9.x

> Паттерны аварийного восстановления для Elastic Stack: RPO/RTO, snapshot-стратегии, CCR failover/failback и multi-site. Механика CCR (настройка remote-кластеров, follow/auto-follow) — в [Cross-Cluster Replication](./elasticsearch_ccr_ccs.md); автоматизация SLM в сценарии туториала — в [ILM и политики хранения](./elasticsearch_ilm_and_retention.md); sizing ресурсов под DR — в [Capacity Planning](./elasticsearch_capacity_planning.md).
>
> **Важно:** Elasticsearch не выполняет автоматический failover. Переключение на резервный кластер всегда делает внешняя система (DNS, VIP/keepalived, proxy) — сам кластер только реплицирует данные.

## Определения

* **RPO (Recovery Point Objective)** — максимально допустимая потеря данных, измеряется временем (например, «не более 4 часов»).
* **RTO (Recovery Time Objective)** — максимально допустимое время восстановления сервиса после сбоя.
* **Disaster Recovery (DR)** — процедуры восстановления после катастрофического сбоя площадки или кластера.
* **Failover** — переключение нагрузки на резервный кластер/площадку.
* **Failback** — возврат на основной кластер после его восстановления.
* **Snapshot** — инкрементальный бэкап состояния кластера/индексов в репозиторий (после первого полного снапшота копируются только новые сегменты).
* **Repository** — хранилище снапшотов (общая файловая система, `url`, S3-совместимое object storage).
* **SLM (Snapshot Lifecycle Management)** — автоматизация снапшотов по расписанию с retention.
* **Searchable Snapshot** — индекс, смонтированный из снапшота и доступный для поиска без полного восстановления; read-only.
* **Allocation Awareness** — размещение реплик на узлах с разными атрибутами (например, площадка/зона) — механика в [Tutorials/cluster_setup.md](../Tutorials/cluster_setup.md).

## Основные концепции

### Что снапшот бэкапит, а что — нет

Снапшот содержит: данные открытых (open) индексов и data streams, cluster state (persistent settings, composable и legacy index templates, ingest pipelines, ILM-политики) при `include_global_state: true`, feature states (системные индексы: Watches, task records и др.) при `include_global_state: true` или явном `feature_states`.

Снапшот **не** содержит: transient cluster settings, зарегистрированные репозитории, конфигурационные файлы узлов (`elasticsearch.yml`), файлы безопасности (keystore, users/roles). Вывод для DR: runbook должен включать повторную регистрацию репозиториев и восстановление конфигурации узлов из CMDB/Ansible — снапшот этого не вернёт.

### Совместимость версий

Восстановить снапшот в кластер более ранней версии нельзя (нельзя восстановить снапшот 7.6.0 в кластер 7.5.0). Индекс, созданный в несовместимой версии, при restore упадёт с ошибкой; обходной путь — восстановить его в промежуточный кластер совместимой версии и пересоздать через `_reindex` from remote (требует включённого `_source`). Планируйте порядок upgrade до/после DR-учений.

### Стратегии DR

#### 1. Active-Passive (Cold Standby)

```
Active Cluster (Site A)          Passive Cluster (Site B)
├── Принимает весь трафик        ├── Простаивает (или минимальная нагрузка)
├── Пишет в локальное хранилище  ├── Получает снапшоты по SLM
└── Здоров                       └── В ожидании

RPO: до интервала SLM (часы)
RTO: часы (ручной restore + переключение)
```

#### 2. Active-Passive (Warm Standby, CCR)

```
Active Cluster (Site A)          Passive Cluster (Site B)
├── Принимает весь трафик        ├── Follower-индексы (read-only)
├── Пишет в локальное хранилище  ├── CCR-репликация в near-real-time
└── Здоров                       └── DNS/VIP-переключение при сбое

RPO: секунды-минуты (CCR lag)
RTO: минуты (ручной promote + переключение)
```

#### 3. Active-Active (Multi-Site)

```
Site A                           Site B
├── Принимает трафик (US)        ├── Принимает трафик (EU)
├── Пишет в локальное хранилище  ├── Пишет в локальное хранилище
└── CCR → Site B                 └── CCR → Site A

RPO: секунды (async replication)
RTO: минуты — автоматическое переключение возможно
       только через внешнюю оркстрацию (DNS/VIP/proxy)
```

Двунаправленная CCR требует разрешения конфликтов на уровне приложения (кто пишет в какой индекс/регион) — Elasticsearch не разрешает write-конфликты сам.

### RPO/RTO по стратегиям

| Стратегия | RPO | RTO | Стоимость | Сложность |
|-----------|-----|-----|-----------|-----------|
| Daily SLM snapshot | До 24h | Часы | Low | Low |
| 4-hour SLM snapshot | До 4h | Часы | Low-Medium | Low |
| CCR (async) | Секунды-минуты (lag) | Минуты (ручной promote) | High | Medium |
| Active-Active (bidirectional CCR) | Секунды | Минуты (только внешняя автоматизация) | Very High | High |
| Snapshot + CCR | Секунды (CCR) + точка снапшота | Минуты | High | High |

## Предварительные требования

* Кластер 8.x/9.x с elected master node; restore возможен только на работающем кластере с elected master.
* Репозиторий: общая файловая система (NFS) или S3-совместимое object storage (например, MinIO), доступное со **всех master и data узлов**.
* Для `fs`-репозитория: статическая настройка `path.repo` в `elasticsearch.yml` на каждом узле (путь репозитория должен разрешаться внутри `path.repo`):

  ```yaml
  # elasticsearch.yml (на каждом узле, static — требует рестарта)
  path.repo: ["/mnt/backup"]
  ```

* Привилегии: `manage` cluster privilege (или `cluster:admin/snapshot/*`) для snapshot/restore API.
* Для CCR: сеть между площадками, настроенные remote-кластеры (механика — в [CCR/CCS](./elasticsearch_ccr_ccs.md)).
* Для searchable snapshots в frozen tier: узлы с ролью `data_frozen`, Enterprise-подписка для фаз Cold/Frozen ILM.
* Внешняя система переключения: keepalived/VRRP VIP или DNS с низким TTL.

## Практические сценарии

### Сценарий 1: Автоматический бэкап по SLM

Регистрация репозитория и политики с retention:

```bash
# 1. Регистрация fs-репозитория
PUT _snapshot/my-repo
{
  "type": "fs",
  "settings": {
    "location": "/mnt/backup",
    "compress": true,
    "max_snapshot_bytes_per_sec": "40mb",
    "readonly": false
  }
}
# → {"acknowledged": true}

# 2. Проверка доступности репозитория со всех узлов
POST _snapshot/my-repo/_verify
# → {"nodes": {"<node_id>": {}}}

# 3. SLM-политика: ежедневно в 1:30, retention 30 дней
PUT _slm/policy/daily-snapshots
{
  "schedule": "0 30 1 * * ?",
  "name": "<daily-snap-{now/d}>",
  "repository": "my-repo",
  "config": {
    "indices": ["logs-*", "metrics-*"],
    "ignore_unavailable": true,
    "include_global_state": true
  },
  "retention": {
    "expire_after": "30d",
    "min_count": 5,
    "max_count": 50
  }
}
# → {"acknowledged": true}

# 4. Немедленный запуск (не ждать расписания)
PUT _slm/policy/daily-snapshots/_execute
# → {"snapshot_name": "daily-snap-2026.08.23"}
```

Параметры политики: `schedule` — cron (6 полей); `name` — имя снапшота с date math; `config.indices` — индексы/data streams (multi-target syntax); `config.ignore_unavailable` (default **false**) — не падать при отсутствии индекса; `config.include_global_state` (default **true**) — включать cluster state (templates, ILM-политики, pipelines, feature states); `retention` — `expire_after` (возраст), `min_count` (минимум копий, даже если истекли), `max_count` (максимум копий).

Retention-задача запускается отдельно от расписания снапшотов: кластерная настройка `slm.retention_schedule` (default `0 30 1 * * ?` — ежедневно 1:30 UTC), лимит времени удаления — `slm.retention_duration` (default `1h`). Ручной запуск: `POST _slm/_execute_retention`.

### Сценарий 2: Восстановление из снапшота

```bash
# Список снапшотов и их состояние
GET _cat/snapshots/my-repo?v&h=id,state,indices,successful_shards,failed_shards

# Детали конкретного снапшота
GET _snapshot/my-repo/daily-snap-2026.08.23
# → {"snapshots": [{"snapshot": "daily-snap-2026.08.23", "state": "SUCCESS", ...}]}

# Восстановление ВСЕХ индексов с переименованием (безопасно для боевого кластера)
POST _snapshot/my-repo/daily-snap-2026.08.23/_restore?wait_for_completion=true
{
  "indices": "*",
  "include_global_state": false,
  "rename_pattern": "(.+)",
  "rename_replacement": "$1-restored"
}

# Восстановление конкретного индекса с переопределением настроек
POST _snapshot/my-repo/daily-snap-2026.08.23/_restore
{
  "indices": "logs-2026.08",
  "include_global_state": false,
  "include_aliases": true,
  "index_settings": {
    "index.number_of_replicas": 1
  },
  "ignore_index_settings": ["index.refresh_interval"]
}
```

Параметры restore: `indices` — что восстанавливать; `include_global_state` (default **false**) — восстанавливать cluster state (при restore в тот же кластер обычно `false`, иначе templates сливаются с существующими); `include_aliases` (default **true**); `partial` (default **false**) — разрешить restore при недоступных шардах (восстановятся только успешные); `rename_pattern`/`rename_replacement` — regex-переименование; `index_settings`/`ignore_index_settings` — переопределение/игнорирование настроек индекса; `wait_for_completion=true` — синхронный вызов.

Restore игнорирует index blocks, но требует writable global metadata (нет cluster blocks на запись). Для data stream нужен matching index template с `data_stream` enabled.

### Сценарий 3: DR на базе CCR (warm standby)

Нормальная работа: leader-кластер (Site A) принимает запись, follower-кластер (Site B) реплицирует индексы через auto-follow (настройка — в [CCR/CCS](./elasticsearch_ccr_ccs.md)):

```bash
# Auto-follow: все критичные индексы leader-кластера
PUT _ccr/auto_follow/dr-follower
{
  "remote_cluster": "dr-cluster",
  "leader_index_patterns": ["critical-*"],
  "follow_index_pattern": "{{leader_index}}"
}
# → {"acknowledged": true}
```

**Failover (promote follower)** — процедура необратима, follower конвертируется в обычный read-write индекс:

```bash
# 1. Остановить репликацию
POST critical-index/_ccr/pause_follow
# → {"acknowledged": true}

# 2. Закрыть индекс (обязательное условие для unfollow)
POST critical-index/_close
# → {"acknowledged": true, "shards_acknowledged": true}

# 3. Конвертировать follower в обычный индекс
POST critical-index/_ccr/unfollow
# → {"acknowledged": true}

# 4. Открыть и принимать запись
POST critical-index/_open
# → {"acknowledged": true, "shards_acknowledged": true}
```

После promote индекс — обычный: запись идёт на DR-кластер, CCR-метаданные удалены. Вернуть индекс обратно в режим follower нельзя (нельзя конвертировать обычный индекс в follower) — failback строится заново: восстанавливается leader-кластер, затем создаётся новый auto-follow в обратном направлении (или restore из снапшота + повторная репликация).

Мониторинг lag (алерт на расхождение):

```bash
GET _ccr/stats
# → follower_stats: operations_read, operations_written,
#   leader_max_seq_no, follower_global_checkpoint, ...
```

Lag в операциях = `leader_max_seq_no` − `follower_global_checkpoint` (по шарду; Kibana CCR-мониторинг показывает «Sync Lag (ops)» и «Last fetch time»). Информация о follower-индексах (active/paused): `GET _ccr/follow_info`; статистика по конкретным индексам: `GET _ccr/follow_stats/<index>`.

### Сценарий 4: Multi-site с allocation awareness

Для распределения реплик между площадками используйте shard allocation awareness (полная механика — в [Tutorials/cluster_setup.md](../Tutorials/cluster_setup.md)):

```yaml
# elasticsearch.yml на всех узлах
cluster.routing.allocation.awareness.attributes: site
node.attr.site: site-a   # или site-b
```

```json
PUT _cluster/settings
{
  "persistent": {
    "cluster.routing.allocation.awareness.force.site.values": ["site-a", "site-b"]
  }
}
```

 Forced awareness гарантирует, что primary и replica не «скучуются» в одной площадке: если site-b недоступна, первичные шарды в site-a не получают реплик (сохраняется ёмкость диска, но снижается отказоустойчивость записи до возвращения площадки). Без `force` при потере площадки реплики могут разместиться в выжившей площадке рядом с primary.

Переключение трафика — внешнее: VIP (keepalived/VRRP) или DNS с низким TTL:

```bash
# keepalived: VRRP VIP на активной площадке (иллюстративный пример)
vrrp_instance VI_ES {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 100
    advert_int 1
    virtual_ipaddress { 10.0.0.100/24 }
    track_script { chk_es }
}

vrrp_script chk_es {
    script "curl -sk -o /dev/null -w '%{http_code}' -u elastic:$ES_PASS https://localhost:9200/_cluster/health"
    interval 5
}
```

### Сценарий 5: Searchable snapshots для архива и DR

Searchable snapshot — read-only индекс, данные которого остаются в репозитории; поиск обслуживается из локального кэша/диска, недостающее скачивается по запросу. Два режима монтирования:

* `full_copy` — полная копия шардов на локальный диск (cold tier; данные сохраняются между рестартами; ILM-префикс `restored-`);
* `shared_cache` — только недавно запрашиваемые блоки в локальном кэше фиксированного размера (frozen tier; ILM-префикс `partial-`).

```bash
# Монтирование индекса из снапшота как searchable snapshot (read-only)
POST _snapshot/my-repo/daily-snap-2026.08.23/_mount?storage=shared_cache&wait_for_completion=true
{
  "index": "logs-2026.01",
  "renamed_index": "frozen-logs-2026.01",
  "index_settings": {
    "index.number_of_replicas": 0
  },
  "ignore_index_settings": ["index.refresh_interval"]
}
# → {"acknowledged": true}

# Проверка: индекс смонтирован из репозитория
GET frozen-logs-2026.01/_settings?filter_path=**.store.type
# → {"frozen-logs-2026.01": {"settings": {"index": {"store": {"type": "remote_snapshot"}}}}}
```

Настройки shared cache (только на узлах с ролью `data_frozen`, один data path на узел):

```yaml
# elasticsearch.yml
# Диск под shared cache: default — 90% диска на dedicated frozen-узлах, иначе 0b
xpack.searchable.snapshot.shared_cache.size: 20%
# Запас незанятого пространства при процентной настройке (default 100GB)
xpack.searchable.snapshot.shared_cache.size.max_headroom: 100gb
```

Ограничения: mounted-индекс read-only (для записи — `_reindex` в обычный индекс); удаление снапшота, на который ссылается mounted-индекс, делает данные недоступными; не монтируйте вручную снапшоты, управляемые ILM (нарушает работу политики); скорость восстановления ограничена `max_restore_bytes_per_sec` репозитория и `indices.recovery.max_bytes_per_sec` кластера. При restore снапшота, содержащего searchable snapshot индекс, сначала зарегистрируйте репозиторий-источник.

### Сценарий 6: DR drill (учение)

```
1. Выбрать стратегию для теста (snapshot / CCR / multi-site)
2. Сымитировать сбой площадки (остановить трафик на активный кластер)
3. Выполнить процедуру failover по runbook
4. Проверить целостность данных (doc counts, spot-check документов)
5. Проверить подключение приложений
6. Замерить фактический RTO
7. Выполнить failback на основной кластер
8. Задокументировать результаты и обновить runbook
```

Тестирование restore без риска для боевого кластера — restore с `rename_pattern` на стенде, сверка `_count`, удаление восстановленных индексов. Для snapshot-based DR можно использовать thin clone (не копирует данные, разделяет файлы с исходным снапшотом):

```bash
# Клон снапшота для тестов (в том же репозитории)
PUT _snapshot/my-repo/daily-snap-2026.08.23/_clone/drill-2026.08.23
{
  "indices": "logs-*"
}
# → {"accepted": true}
```

Автоматизированный health-check с триггером runbook (иллюстративный пример):

```bash
#!/bin/bash
# Health check активного кластера; при недоступности — запуск runbook failover
CLUSTER_HEALTH=$(curl -sk -o /dev/null -w "%{http_code}" \
  -u "elastic:$ES_PASS" https://active-cluster:9200/_cluster/health)

if [ "$CLUSTER_HEALTH" != "200" ]; then
  # 1. Pause follow на DR-кластере
  curl -sk -u "elastic:$DR_PASS" -X POST "https://dr-cluster:9200/critical-*/_ccr/pause_follow"
  # 2. Promote: close -> unfollow -> open (см. сценарий 3)
  # 3. Переключение VIP/DNS на DR-кластер (keepalived/ansible)
  ansible-playbook failover-vip.yml --extra-vars "target=dr-cluster"
fi
```

### Сценарий 7: Tiered DR по критичности данных

```
Tier 1 (Critical):
  - CCR (async) + ежедневные снапшоты
  - RPO: секунды-минуты
  - RTO: минуты

Tier 2 (Important):
  - SLM каждые 4 часа
  - RPO: до 4h
  - RTO: часы

Tier 3 (Archive):
  - SLM ежедневно + searchable snapshots для поиска по архиву
  - RPO: до 24h
  - RTO: часы-дни
```

## Настройки, влияющие на DR

### Репозиторий (`fs`)

| Настройка | Default | Назначение |
|-----------|---------|------------|
| `location` | (обязательно) | Путь внутри `path.repo` на каждом master/data узле |
| `compress` | `true` | Сжимать метаданные снапшота (данные сегментов не сжимаются) |
| `chunk_size` | `null` (без лимита) | Дробить файлы снапшота на чанки указанного размера |
| `max_snapshot_bytes_per_sec` | `40mb` на узел | Троттлинг создания снапшота |
| `max_restore_bytes_per_sec` | unlimited | Троттлинг restore (дополнительно throttled через recovery-настройки) |
| `readonly` | `false` | `true` — кластер может restore, но не может писать в репозиторий (DR/restore-кластер) |
| `max_number_of_snapshots` | `Integer.MAX_VALUE` | Лимит числа снапшотов в репозитории |

### Репозиторий (`s3`)

Объектное хранилище — основной выбор off-site резервных копий: S3 (AWS), MinIO и любой S3-совместимый storage. Поддержка S3/GCS/Azure **встроена в дистрибутив Elasticsearch** — отдельная установка `repository-s3`-плагина не требуется (для 8.0 и новее).

Регистрация:

```bash
PUT _snapshot/s3_backup
{
  "type": "s3",
  "settings": {
    "bucket": "my-snapshots",
    "base_path": "es-prod",
    "region": "eu-central-1",
    "compress": true
  }
}
POST _snapshot/s3_backup/_verify   # → {"nodes": {...}} — проверка доступности
```

| Настройка | Default | Назначение |
|-----------|---------|------------|
| `bucket` | (обязательно) | Имя существующего бакета; создавать бакет заранее (права не должны включать `CreateBucket`) |
| `client` | `default` | Имя S3-клиента (настройки клиента — в keystore с префиксом `s3.client.<имя>.*`) |
| `base_path` | `""` (корень бакета) | Путь данных репозитория внутри бакета; не начинать и не заканчивать на `/` |
| `compress` | `true` | Сжатие метаданных снапшота (как у `fs`) |
| `chunk_size` | `5tb` (макс. объект S3) | Размер объекта, в которые дробятся файлы снапшота; больше — multipart-лимиты S3 |
| `max_snapshot_bytes_per_sec` | `40mb` на узел | Троттлинг создания снапшота |
| `max_restore_bytes_per_sec` | unlimited | Троттлинг restore (дополнительно throttled recovery-настройками) |
| `server_side_encryption` | `false` | Шифрование объектов на стороне S3 (AES-256, SSE-S3) |
| `storage_class` | `standard` | S3 storage class объектов; с 9.5 вместо него рекомендуются `data_storage_class` и `metadata_storage_class` (отдельно для данных и метаданных) |
| `readonly` | `false` | Как у `fs`: `true` — только restore (реплика-кластер для DR) |
| `endpoint` | — | Клиентская настройка (не репозитория): URL S3-совместимого сервиса (MinIO, Ceph RGW) |

**Аутентификация.** Предпочтительны IAM-механизмы без секретов в конфигах: instance profile / IAM-роль нод, IRSA (EKS), Pod Identity. Статические ключи — только в keystore (никогда в `elasticsearch.yml` и запросе):

```bash
bin/elasticsearch-keystore add s3.client.default.access_key
bin/elasticsearch-keystore add s3.client.default.secret_key
# s3.client.default.session_token — опционально, для временных credentials
```

С AWS SDK v2 (начиная с 8.19) регион обязан быть задан явно в настройках/клиенте либо определяться автоматически из окружения — без этого подписанные запросы падают.

**Ограничения и особенности:**

- Репликация бакета S3 (cross-region/внутрирегиональная) **несовместима** с снапшотами Elasticsearch: объекты снапшота ссылаются друг на друга, рассинхрон реплики ломает restore. Для off-site — отдельный бакет и либо SLM-копии, либо CRR самого Elasticsearch (cross-cluster replication).
- Мини-стек для лабораторий: MinIO официально поддерживается (включён в набор проверок Elastic); S3-совместимые прочие системы — «могут работать, но не покрыты тестами Elastic».
- Для Elastic Cloud Enterprise `base_path` задавать нельзя — он генерируется автоматически для каждого deployment.
- Стоимость: без lifecycle-политик бакета снапшоты копятся вечно; параллельно настройте retention через SLM (см. ниже).

### SLM (кластерные настройки)

| Настройка | Default | Назначение |
|-----------|---------|------------|
| `slm.retention_schedule` | `0 30 1 * * ?` (1:30 UTC) | Расписание retention-задачи |
| `slm.retention_duration` | `1h` | Лимит времени удаления старых снапшотов |
| `slm.history_index_enabled` | `true` | Писать историю действий SLM в `slm-history-*` |

### Snapshot/restore API (справочно)

| Операция | Метод | Endpoint |
|----------|-------|----------|
| Регистрация репозитория | PUT | `_snapshot/<repo>` |
| Проверка репозитория | POST | `_snapshot/<repo>/_verify` |
| Создание снапшота | PUT | `_snapshot/<repo>/<snapshot>?wait_for_completion=true` |
| Информация о снапшоте | GET | `_snapshot/<repo>/<snapshot>` |
| Список снапшотов | GET | `_cat/snapshots/<repo>?v` |
| Удаление снапшота | DELETE | `_snapshot/<repo>/<snapshot>` |
| Clone снапшота | PUT | `_snapshot/<repo>/<src>/_clone/<target>` |
| Cleanup репозитория | POST | `_snapshot/<repo>/_cleanup` |
| Анализ репозитория | POST | `_snapshot/<repo>/_analyze` |
| Restore | POST | `_snapshot/<repo>/<snapshot>/_restore` |
| SLM: создать политику | PUT | `_slm/policy/<id>` |
| SLM: выполнить сейчас | PUT | `_slm/policy/<id>/_execute` |
| SLM: retention вручную | POST | `_slm/_execute_retention` |
| SLM: статус/статистика | GET | `_slm/status`, `_slm/stats` |
| SLM: стоп/старт | POST | `_slm/stop`, `_slm/start` |

Состояния снапшота: `SUCCESS`, `PARTIAL`, `FAILED`, `IN_PROGRESS`, `INCOMPATIBLE`.

## Валидация расчёта и конфигурации

* **Снапшот создан**: `GET _snapshot/<repo>/<snap>` → `state: SUCCESS`; `GET _cat/snapshots/<repo>?v` — `successful_shards` = `total_shards`, `failed_shards` = 0.
* **SLM работает**: `GET _slm/status` → `{"mode": "RUNNING"}`; `GET _slm/stats` → `policy_stats[].snapshots_taken` растёт, `snapshots_failed` = 0; история — `GET slm-history-*/_search`.
* **Restore корректен**: после restore — `GET <index>/_count` совпадает с ожидаемым; `GET _cluster/health` → `green`/`yellow`.
* **CCR lag в норме**: `GET _ccr/stats` → `leader_max_seq_no` − `follower_global_checkpoint` ≈ 0; `read_exceptions` пуст.
* **Репозиторий доступен**: `POST _snapshot/<repo>/_verify` → список узлов; `GET _cat/repositories?v` — репозиторий зарегистрирован.
* **Searchable snapshot смонтирован**: `GET <index>/_settings?filter_path=**.store.type` → `remote_snapshot`.

## Troubleshooting

| Симптом | Причина | Решение |
|---------|---------|---------|
| `repository_missing_exception` при restore | Репозиторий не зарегистрирован на целевом кластере | Зарегистрировать `PUT _snapshot/<repo>` (снапшоты не содержат репозитории) |
| Restore падает с ошибкой записи cluster state | Global metadata заблокирован (cluster blocks) | Снять блоки (`PUT _cluster/settings`), restore игнорирует index blocks, но не cluster blocks |
| Restore data stream падает | Нет matching index template с `data_stream` | Создать template до restore |
| Снапшот `PARTIAL`/`FAILED` | Недоступные шарды, диск, сеть | `GET _snapshot/<repo>/<snap>` → `failures`; `partial: true` в конфиге для снапшота при нестабильных шардах |
| `snapshot_in_progress_exception` | Достигнут лимит concurrent snapshots (`1000`) или идёт снапшот того же индекса | Дождаться завершения (`GET _snapshot/<repo>/_status`) |
| SLM-политика не выполняется | SLM остановлен (`GET _slm/status` → `STOPPED`) | `POST _slm/start`; проверить `slm-history-*` на ошибки |
| Retention не удаляет снапшоты | Нет `retention` в политике или retention-задача не запускалась | Добавить `retention`; `POST _slm/_execute_retention`; проверить `slm.retention_schedule` |
| `unfollow` завершается ошибкой | Follower не paused или не closed | `POST /<index>/_ccr/pause_follow`, `POST /<index>/_close`, затем `unfollow` |
| CCR `read_exceptions` растёт | Leader-кластер/сеть недоступен | Проверить remote-кластер (`GET _remote/info`), сеть; при длительном простое — `skip_unavailable: true` |
| Restore в более раннюю версию | Несовместимость версий | Восстановить в промежуточный кластер совместимой версии, затем `_reindex` from remote (требуется `_source`) |
| `_verify` не проходит для части узлов | `path.repo` не настроен или путь не смонтирован на узле | Проверить `path.repo` и монтирование NFS на каждом master/data узле |
| Searchable snapshot не аллоцируется | Нет узла с `data_frozen` и shared cache | Настроить `data_frozen`-узел и `xpack.searchable.snapshot.shared_cache.size` |

## Граничные случаи

* **Снапшоты только открытых индексов** — closed индексы не попадают в снапшот (`ignore_unavailable: true` подавит ошибку, но данные closed-индекса не забэкапятся).
* **Удаление снапшота, на который ссылается searchable snapshot**, делает данные mounted-индекса недоступными.
* **Restore в тот же кластер** с `include_global_state: true` мержит templates/pipelines с существующими — может вызвать конфликты; для боевого кластера используйте `false` + `rename_pattern`.
* **Forced allocation awareness**: при потере одной площадки запись продолжается только в выжившей, но реплики не создаются до её возвращения — компромисс между ёмкостью и отказоустойчивостью.
* **Split brain** в 7.x+ предотвращается voting configuration (кворум master-eligible узлов); при сбое с двумя кластерами — ручное разрешение: остановить «меньшинственный» кластер, восстановить данные из снапшота при расхождении.
* **CCR**: follower имеет столько же шардов, сколько leader; обычный индекс нельзя конвертировать в follower; `unfollow` необратим; при недоступности leader после `unfollow` retention leases удаляются через `forget_follower`.
* **Snapshot во время интенсивной индексации** — инкрементальный, но высокая ротация сегментов увеличивает размер репозитория; удаление старых снапшотов освобождает только неразделяемые данные.
* **Троттлинг restore** действует двояко: `max_restore_bytes_per_sec` репозитория и `indices.recovery.max_bytes_per_sec` кластера (default 40mb/узел).
* **`max_number_of_snapshots`** — при достижении лимита новые снапшоты отклоняются; актуально для репозиториев с большим retention.

## Best Practices

### Snapshots

1. **Automate with SLM** — не полагайтесь на ручные бэкапы; проверяйте `GET _slm/stats` в мониторинге.
2. **Test restores regularly** — бэкап бесполезен, если не восстанавливается; DR drill минимум раз в квартал.
3. **Off-site storage** — репозиторий в отдельном failure domain (отдельная площадка/серверная), а не на тех же узлах.
4. **Retention policy** — баланс между стоимостью и окном восстановления; `min_count` ≥ 2 для защиты от «плохого» снапшота.
5. **Include global state** — для DR-снапшотов `include_global_state: true` (templates, ILM, pipelines), но восстанавливайте его осознанно.
6. **Readonly-репозиторий на restore-кластере** — `"readonly": true` защищает DR-копию от случайной перезаписи.
7. **Восстанавливайте конфигурацию узлов из CMDB** — снапшот не содержит `elasticsearch.yml`, keystore, security-файлы.

### CCR для DR

1. **Monitor replication lag** — алерт на `leader_max_seq_no` − `follower_global_checkpoint` > порога (например, 1000 ops) или на рост `read_exceptions`.
2. **Auto-follow patterns** — автоматическая репликация новых индексов, иначе новый индекс не попадёт в DR.
3. **Promote procedure** — документируйте шаги failover (pause → close → unfollow → open) и проверяйте на учениях.
4. **Network bandwidth** — учитывайте latency и пропускную способность между площадками; CCR — async, lag растёт при перегрузе канала.

### General

1. **Document DR procedures** — runbook на каждый сценарий (node, site, corruption, split brain).
2. **Regular DR drills** — минимум раз в квартал с замером фактического RTO/RPO.
3. **Automate failover** — где возможно, через VIP/DNS-оркстрацию для снижения RTO.
4. **Cross-team coordination** — DBA, network, application teams; DR-зависимости приложений от Elasticsearch.
5. **Version compatibility** — планируйте upgrade до DR-учений; снапшот нельзя restore в более раннюю версию.

## Cleanup

```bash
# Удалить SLM-политику (снапшоты при этом НЕ удаляются)
DELETE _slm/policy/daily-snapshots

# Удалить конкретный снапшот (освобождает только неразделяемые данные)
DELETE _snapshot/my-repo/daily-snap-2026.08.23

# Удалить восстановленные тестовые индексы
DELETE logs-2026.08-restored

# Остановить репликацию и удалить auto-follow паттерн
POST critical-index/_ccr/pause_follow
POST critical-index/_close
POST critical-index/_ccr/unfollow
DELETE _ccr/auto_follow/dr-follower

# Удалить remote-кластер
PUT _cluster/settings
{
  "persistent": {
    "cluster.remote.dr-cluster.seeds": null
  }
}

# Очистить shared cache searchable snapshots
POST /_searchable_snapshots/cache/clear

# Отключить троттлинг, если меняли для DR-операций
PUT _cluster/settings
{
  "persistent": {
    "indices.recovery.max_bytes_per_sec": null
  }
}
```

## Дополнительная информация

**Чек-лист DR-готовности:**

- [ ] SLM-политика создана и выполняется (`GET _slm/stats` → `snapshots_failed: 0`)
- [ ] Репозиторий верифицирован со всех узлов (`POST _snapshot/<repo>/_verify`)
- [ ] Retention настроен и удаляет старые снапшоты
- [ ] Restore протестирован на стенде с `rename_pattern`
- [ ] Конфигурация узлов и security-файлы восстановимы из CMDB/Ansible
- [ ] CCR lag мониторится, алерт на расхождение настроен
- [ ] Runbook failover/failback написан и отрепетирован
- [ ] Внешнее переключение (VIP/DNS) протестировано
- [ ] Фактический RTO/RPO замерян на последнем учении

**См. также:**

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура кластера, роли узлов.
* **[Cross-Cluster Replication и Search](./elasticsearch_ccr_ccs.md)** — механика CCR, remote-кластеры, auto-follow.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — SLM-туториал, searchable snapshots в фазах Cold/Frozen.
* **[Capacity Planning](./elasticsearch_capacity_planning.md)** — sizing под DR, recovery-настройки.
* **[Stack Monitoring](./elasticsearch_stack_monitoring.md)** — мониторинг кластера и алерты.
* **[Search Tuning](./elasticsearch_search_tuning.md)** — поиск по восстановленным индексам.
* **[Upgrades и миграция](./elasticsearch_upgrades.md)** — совместимость версий при restore.
* **[Security Advanced](./elasticsearch_security_advanced.md)** — безопасность данных и keystore.
* **[Tutorials/cluster_setup.md](../Tutorials/cluster_setup.md)** — allocation awareness, multi-zone деплой.
