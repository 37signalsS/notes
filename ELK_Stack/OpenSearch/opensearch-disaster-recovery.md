# Снапшоты и восстановление (OpenSearch)

**Актуально для:** OpenSearch 2.x / 3.x. Snapshot Management (SM) — с 2.1, требует плагинов Index Management и Job Scheduler; `creation` в SM-политике необязателен с 3.3; shallow copy snapshots — с 2.10 (v2 — с 2.17); Remote-Backed Storage production-ready с 2.15.

> Стратегия disaster recovery для OpenSearch: резервное копирование (snapshot/restore), автоматизация через Snapshot Management, роль CCR и ISM в плане восстановления, порядок действий при потере кластера. Общая теория DR (паттерны active-passive/warm standby, RPO/RTO, tiered-стратегии) — в [Elasticsearch Disaster Recovery](../Elasticsearch/elasticsearch_disaster_recovery.md); расчёт RPO/RTO под кластер — в [Capacity Planning](./opensearch_capacity_planning.md).

## Определения

* **Snapshot** — инкрементальный бэкап индексов и состояния кластера (настройки, маппинги, шаблоны, топология шардов). Сегменты хранятся в репозитории дедуплицированно, поэтому последующие снапшоты переносят только изменения.
* **Repository** — хранилище снапшотов (`fs` — общий каталог, `s3`/`hdfs`/`azure` — внешнее хранилище); регистрируется API `_snapshot`. Регистрация существует на уровне кластера и в сам снапшот не входит.
* **Restore** — восстановление индексов/кластерного состояния из снапшота в тот же или другой кластер.
* **Snapshot Management (SM) policy** — cron-политика автоматического создания и удаления снапшотов (`_plugins/_sm/policies`).
* **RPO / RTO** — допустимая потеря данных (между бэкапами) и время восстановления; RPO задаётся частотой SM-политики, RTO — размером кластера и планом восстановления.
* **`path.repo`** — статическая настройка узла в `opensearch.yml`, задающая каталоги, которые разрешено использовать как `fs`-репозиторий.
* **Shallow snapshot** — снапшот кластера с remote-backed storage, хранящий только метаданные и ссылки на сегменты в remote store, без полных копий сегментов (2.10+; `shallow_snapshot_v2` — 2.17+).
* **DR-элементы OpenSearch**: снапшоты (основной механизм), CCR (read-follower как горячий standby), ISM (ретеншн данных), GitOps-конфигурация (воссоздание кластера «с нуля»).

## Как это работает

Снапшот не является простой копией индексов. OpenSearch разбивает данные на сегменты, сохраняет в репозитории только те сегменты, которых там ещё нет, и пишет метаданные снапшота (список индексов, шардов и ссылок на сегменты). Отсюда следуют практические свойства:

* **Инкрементальность бесплатна на уровне хранилища.** Первый снапшот переносит все сегменты, каждый следующий — только новые. Удаление старого снапшота освобождает лишь те сегменты, на которые не ссылается ни один другой снапшот.
* **Снапшот фиксирует точку во времени** на момент запроса; записи, попавшие в кластер после, в него не входят.

**Что входит в снапшот:**

* данные индексов из списка `indices` (в том числе закрытых);
* при `include_global_state: true` — persistent cluster settings, composable и legacy index templates, ingest pipelines, ISM-политики.

**Что НЕ входит** (важно для runbook):

* конфигурационные файлы узлов (`opensearch.yml`), keystore, список установленных плагинов;
* регистрация репозиториев — её выполняют на целевом кластере заново;
* transient cluster settings.

**Security plugin и снапшоты.** Конфигурация безопасности хранится в системном индексе `.opendistro_security`. Снапшоты, содержащие глобальное состояние или этот индекс, **не восстанавливаются**, пока в запросе restore их не исключить (`include_global_state: false`, `indices: "-.opendistro_security"`). Восстановить `.opendistro_security` можно только с admin-сертификатом, и это не рекомендуется — меняет security-состояние всего кластера. Штатный способ бэкапа security-конфигурации — выгрузка YAML через `securityadmin.sh -backup` и хранение в Git (см. [Administration](./opensearch_administration.md)).

## Совместимость версий

* Снапшот восстанавливается в кластер той же версии или **на один мажор новее** (forward compatible by one major version). Снапшот 2.x → кластер 3.x работает; 3.x → 2.x — нет.
* Внутри одной линии снапшот, снятый в раннем релизе, продолжает восстанавливаться в этой же линии после её обновления.
* Снапшот, отстоящий на несколько мажоров, переносят через промежуточный кластер: restore → `_reindex` → новый снапшот → следующий мажор. Часто проще проиндексировать данные в новом кластере заново.
* Снапшот, несовместимый с версией кластера, имеет состояние `INCOMPATIBLE`.

## Предусловия

* **`fs`-репозиторий:** общий каталог, смонтированный на **всех** узлах, и путь, добавленный в `path.repo` (static) на каждом узле:

  ```yaml
  # opensearch.yml на всех узлах (static — требуется рестарт)
  path.repo: ["/mnt/opensearch-backups"]
  ```

* **`s3`-репозиторий:** плагин `repository-s3`, установленный на всех узлах, и права на бакет (IAM-роль узла либо ключи в keystore). Аналогично `repository-hdfs` и `repository-azure`.
* **Права Security:** роль `manage_snapshots` для snapshot/restore; при тонкой настройке — `cluster:admin/snapshot/*`. Для restore — `cluster:admin/snapshot/restore`, `indices:admin/create`, `indices:data/write/index` на целевые индексы.
* **Restore в другой кластер:** репозиторий должен быть зарегистрирован на целевом кластере (регистрация в снапшот не входит).
* **Cross-cluster restore с remote-backed storage:** на целевом кластере регистрируют read-only репозитории-источники сегментов и транслогов; подробности — в разделе [Restore между кластерами с remote-backed storage](#restore-между-кластерами-с-remote-backed-storage).

## Snapshot: резервное копирование

### Репозиторий

```bash
# fs (shared filesystem): каталог должен лежать внутри path.repo на всех узлах
PUT _snapshot/backup-fs
{
  "type": "fs",
  "settings": {
    "location": "/mnt/opensearch-backups/backup-fs",
    "compress": true,
    "max_restore_bytes_per_sec": "40mb",
    "max_snapshot_bytes_per_sec": "40mb"
  }
}

# s3
PUT _snapshot/backup-s3
{
  "type": "s3",
  "settings": {
    "bucket": "opensearch-backups",
    "base_path": "prod-cluster",
    "region": "eu-central-1",
    "compress": true
  }
}

# Проверка (обязательный шаг) — возвращает узлы, имеющие доступ к репозиторию
POST _snapshot/backup-s3/_verify
# → { "nodes": { "<node-id>": { "name": "..." } } }

GET _snapshot/backup-s3     # описание репозитория
DELETE _snapshot/backup-s3  # удаляет только регистрацию, не данные
```

* Для `s3` нужны права на бакет и установленный на всех узлах плагин `repository-s3`. Секреты храните в keystore, не в настройках репозитория: `opensearch-keystore add s3.client.default.access_key` (и `...secret_key`), для временных credentials — `...session_token`, для IAM-роли — `s3.client.default.role_arn`. Если узлы работают на EC2 с IAM instance profile, ключи в keystore не нужны.
* `readonly: true` переводит репозиторий в режим «только чтение» — применяется на restore-кластере, чтобы защитить бэкап от случайной перезаписи.
* Репозиторий — общий ресурс: если несколько кластеров пишут в один бакет, разведите их по `base_path` и расписанию cron.

### Настройки репозитория

| Настройка | Default | Назначение |
|---|---|---|
| `location` (`fs`) | — (обязательна) | Путь внутри `path.repo`, доступный со всех узлов |
| `bucket` (`s3`) | — (обязательна) | Имя бакета; создаётся заранее |
| `base_path` (`s3`) | корень бакета | Префикс данных репозитория внутри бакета |
| `region` (`s3`) | — | Регион; иначе берётся из клиента (`s3.client.default.region`) |
| `compress` | `false` | Сжатие **метаданных** снапшота (данные-сегменты не сжимаются) |
| `chunk_size` | `fs`: не ограничен; `s3`: `1gb` | Дробление файлов снапшота на чанки |
| `max_snapshot_bytes_per_sec` | `40mb` | Троттлинг создания снапшота (на узел) |
| `max_restore_bytes_per_sec` | `0` (без лимита) | Троттлинг restore; дополнительно ограничен `indices.recovery.max_bytes_per_sec` (`40mb`) |
| `readonly` | `false` | `true` — репозиторий только для чтения (restore-кластер, миграция) |

### Создание и просмотр снапшота

```bash
# Полный снапшот всех индексов + кластерного состояния
PUT _snapshot/backup-s3/snapshot-2026-10-07?wait_for_completion=true
{
  "indices": "*",
  "include_global_state": true,
  "ignore_unavailable": true
}

# Только логи, без глобального состояния
PUT _snapshot/backup-s3/logs-nightly
{
  "indices": "logs-*",
  "include_global_state": false,
  "partial": false
}

# Статус / список
GET _snapshot/backup-s3/snapshot-2026-10-07
GET _snapshot/backup-s3/_all
GET _snapshot/backup-s3/_status
GET _snapshot/_status          # все снапшоты всех репозиториев
GET _cat/repositories?v
GET _cat/snapshots/backup-s3?v

# Клонирование снапшота в новый внутри того же репозитория (без копирования сегментов)
PUT _snapshot/backup-s3/snapshot-2026-10-07/_clone/snapshot-2026-10-07-copy
{
  "indices": "index_a,index_b"
}

# Очистка репозитория от сегментов, на которые не ссылается ни один снапшот
POST _snapshot/backup-s3/_cleanup
```

* Тело запроса и его defaults: `indices` (по умолчанию все), `ignore_unavailable` (`false`) — не падать при отсутствии индекса, `include_global_state` (`true`), `partial` (`false`) — при `false` снапшот падает, если хотя бы один шард не сохранился.
* `wait_for_completion=true` — синхронный снапшот; для больших кластеров лучше асинхронный (`false` по умолчанию) и контроль через `_status`.
* Удалять снапшоты **только API** (`DELETE _snapshot/<repo>/<snap>`), не руками в хранилище — инкрементальные сегменты общие для нескольких снапшотов.
* Клон (`_clone`) дешёв, поскольку сегменты в репозитории уже лежат общими блоками и копируются только метаданные; для него нужно право `cluster:admin/snapshot/clone`. `_cleanup` освобождает место, оставшееся после удаления снапшотов.
* Ротацию удобно делать через `deletion`-часть SM-политики.

### Состояния снапшота

| Состояние | Значение |
|---|---|
| `SUCCESS` | Все шарды сохранены |
| `IN_PROGRESS` | Снапшот выполняется |
| `PARTIAL` | Хотя бы один шард не сохранён; возможно только при `partial: true` |
| `FAILED` | Снапшот завершился ошибкой, данные не сохранены |
| `INCOMPATIBLE` | Снапшот несовместим с текущей версией кластера |

### Кластерные настройки снапшотов

| Настройка | Default | Назначение |
|---|---|---|
| `snapshot.max_concurrent_operations` | `1000` (dynamic) | Максимум одновременных операций со снапшотами |
| `snapshot.repository_data.cache.threshold` | `500kb` или `1%` heap (static) | Лимит кэша метаданных репозитория (ускоряет clone/restore/status) |

## Restore

```bash
# На целевом кластере: индекс должен быть закрыт, удалён или переименован
POST _snapshot/backup-s3/logs-nightly/_restore
{
  "indices": "logs-*",
  "include_global_state": false,
  "rename_pattern": "(.+)",
  "rename_replacement": "restored-$1",
  "index_settings": {
    "index.number_of_replicas": 0
  },
  "ignore_unavailable": true
}

# Проверка
GET _cluster/health
GET logs-*/_count
```

Тело запроса и его defaults: `ignore_unavailable` (`false`), `include_global_state` (`false`), `include_aliases` (`true`), `partial` (`false`), `rename_pattern`/`rename_replacement` (regex-переименование), `index_settings`/`ignore_index_settings` (переопределение/игнорирование настроек индекса), `wait_for_completion`.

Особенности:

* Restore **того же** индекса поверх: закрыть индекс (`POST /<index>/_close`) либо восстановить под другим именем через `rename_pattern`/`rename_replacement` (типичный сценарий вытаскивания данных).
* Изменённое кластерное состояние (шаблоны, настройки, pipeline, ISM) восстанавливается только при `include_global_state: true` в снапшоте; применяется осторожно — глобальное состояние перезаписывает текущее.
* Совместимость версий — см. [Совместимость версий](#совместимость-версий): снапшот несовместимой версии даст `INCOMPATIBLE`/ошибку restore.
* Для restore нужны роль `manage_snapshots` и права `cluster:admin/snapshot/restore`, `indices:admin/create`, `indices:data/write/index`.

### Security при restore

* Снапшоты, содержащие глобальное состояние или индекс `.opendistro_security`, **не восстанавливаются**. Исключайте их в запросе:

  ```bash
  POST _snapshot/backup-s3/snapshot-3/_restore
  {
    "indices": "-.opendistro_security",
    "include_global_state": false
  }
  ```

* Настройка `plugins.security.enable_snapshot_restore_privilege` (static, default `true`): при `false` обычные пользователи не могут восстанавливать снапшоты — разрешены только запросы с admin-сертификатом.
* Настройка `plugins.security.check_snapshot_restore_write_privileges` (static, default `true`) включает проверку write-прав на восстанавливаемые индексы.
* Восстановление `.opendistro_security` — только admin-сертификатом, и это не рекомендуется. Конфигурацию Security восстанавливайте из Git через `securityadmin.sh` (см. [Administration](./opensearch_administration.md)).

### Restore между кластерами с remote-backed storage

Если оба кластера используют remote-backed storage с **разными** remote store репозиториями, обычного restore недостаточно — сегменты и транслоги источника лежат в его remote store. Порядок:

1. Зарегистрировать на целевом кластере как `readonly: true` репозиторий снапшотов источника.
2. Зарегистрировать read-only репозиторий сегментов источника (`source-remote-store-repository`).
3. Зарегистрировать read-only репозиторий транслогов источника.
4. В запросе restore указать оба репозитория-источника:

   ```bash
   POST _snapshot/source-cluster-snapshots/snapshot-1/_restore
   {
     "indices": "my-index",
     "source_remote_store_repository": "source-remote-segment-repo",
     "source_remote_translog_repository": "source-remote-translog-repo"
   }
   ```

Восстановленные индексы начинают читать сегменты и транслоги из remote store источника. Оба параметра обязательны при разных remote store; без них cluster вернёт красные индексы вместо явной ошибки (см. [issue #19080](https://github.com/opensearch-project/opensearch/issues/19080)). Если remote store одинаков, параметры не нужны — используются репозитории, зарегистрированные при создании снапшота.

При restore в кластер с remote-backed storage доступен параметр `storage_type`: `local` (default — данные скачиваются в локальное хранилище) или `remote_snapshot` (метаданные локально, сегменты остаются в remote store и кэшируются по запросу; требует узла с ролью `search`).

### Shallow snapshots (remote-backed)

Для remote-backed индексов снапшот можно сделать «поверхностным»: в репозитории хранятся только метаданные, а сегменты остаются в remote store. Включается настройкой репозитория `remote_store_index_shallow_copy: true` (default `false`); все запросы Snapshot API после этого работают как обычно. Инкремент по объёму равен нулю. Требуется OpenSearch 2.10+ на всех узлах; searchable snapshots внутри shallow-снапшотов не поддерживаются. Отдельная версия `shallow_snapshot_v2: true` (2.17+) включается независимо. Настройку нельзя отключать после включения — это влияет на durability данных.


## Snapshot Management: автоматизация

```bash
# Ежедневный снапшот в 08:00 UTC, удаление старше 7 дней
POST _plugins/_sm/policies/daily-policy
{
  "description": "Daily snapshot policy",
  "creation": {
    "schedule": { "cron": { "expression": "0 8 * * *", "timezone": "UTC" } },
    "time_limit": "1h"
  },
  "deletion": {
    "schedule": { "cron": { "expression": "0 1 * * *", "timezone": "UTC" } },
    "condition": { "max_age": "7d", "min_count": 7, "max_count": 30 }
  },
  "snapshot_config": {
    "indices": "*",
    "include_global_state": true,
    "partial": false,
    "repository": "backup-s3"
  }
}
# → { "_id": "daily-policy-sm-policy", ... }

GET    _plugins/_sm/policies
GET    _plugins/_sm/policies/daily-policy
PUT    _plugins/_sm/policies/daily-policy?if_seq_no=<seq_no>&if_primary_term=<primary_term>
DELETE _plugins/_sm/policies/daily-policy
POST   _plugins/_sm/policies/daily-policy/_start    # включить
POST   _plugins/_sm/policies/daily-policy/_stop     # приостановить
GET    _plugins/_sm/policies/daily-policy/_explain  # состояние state machine и метаданные
```

* Имена снапшотов от политики: `<policy_name>-<date>-<random number>` — суффикс гарантирует уникальность внутри политики, а префикс — между политиками. Идентификатор самой политики — `<policy_name>-sm-policy`, поэтому имя политики должно быть уникальным и неизменяемым.
* Поля `snapshot_config` и defaults: `indices` (`*`), `ignore_unavailable` (`false`), `include_global_state` (`true` — значение по умолчанию из-за соображений Security plugin), `partial` (`false`), `repository` (обязателен), `date_format` (формат даты в имени снапшота, default `yyyy-MM-dd'T'HH:mm:ss`) и `timezone` (зона даты, default `UTC`).
* Условие удаления требует `max_age` или `max_count`; `min_count` (default `1`) — минимум сохраняемых снапшотов независимо от возраста.
* Обновление политики — только через `if_seq_no`/`if_primary_term` (optimistic concurrency). Права: `cluster:admin/opensearch/snapshot_management/policy/{write,explain,start,stop}`; готовые роли `snapshot_management_full_access` / `snapshot_management_read_access`.
* Зависимости: Index Management plugin (в нём живёт SM) + Job Scheduler plugin — расписание исполняется как job.
* Уведомления о событиях SM — через Notifications plugin (`notification`-блок политики), см. [Alerting](./opensearch-alerting.md).
* С OpenSearch 3.3 блок `creation` необязателен — можно создать политику только с `deletion`.
* UI: OpenSearch Dashboards → Management → Snapshot Management (Repositories / Snapshot Policies).

## Полный план восстановления

1. **Определить сценарий**: потеря отдельного индекса (restore), потеря кластера (restore + переустановка), региональная катастрофа (снапшоты в другом регионе + новый кластер).
2. **Воссоздать кластер**: Ansible/Helm/ручной конфиг (см. [Ansible](./opensearch_ansible_deployment.md)) — та же версия ядра и плагинов, тот же `opensearch.yml`, тот же набор плагинов, включая `repository-s3`.
3. **Применить `path.repo`** (для `fs`) и/или ключи S3 в keystore — без этого репозиторий не зарегистрируется.
4. **Восстановить security-конфигурацию** из Git: применить `config/opensearch-security/*.yml` через `securityadmin.sh` (см. [Administration](./opensearch_administration.md)) — security-индекс `.opendistro_security` воссоздаётся из YAML; пароли пользователей и сертификаты — из хранилища паролей/CA.
5. **Зарегистрировать репозиторий** на новом кластере (тот же бакет/каталог) и выполнить `_verify`.
6. **Restore** нужных индексов и, при необходимости, глобального состояния (`include_global_state: false` в запросе restore при активном Security plugin); при конфликте имён — через `rename_pattern`.
7. **Проверить данные**: `_cluster/health`, `_count`, выборочный поиск/агрегаты — сверить с источником.
8. **Вернуть писателей**: перенаправить потоки (логи, Kafka-consumers), восстановить `default_pipeline`, ISM-политики, алерты, SM-политики (артефакты конфигурации).
9. **Зафиксировать RPO/RTO фактическими числами** и скорректировать частоту SM-политики.

### CCR как горячий standby

Для сценариев с маленьким RPO (минуты вместо суток) — follower-кластер на CCR ([CCS/CCR](./opensearch-ccs-ccr.md)): данные реплицируются непрерывно, при отказе leader promote делается `_stop` на follower (индекс открывается для записи). CCR не заменяет снапшоты: он не покрывает потерю самого follower и не хранит историю.

## Troubleshooting

### Репозиторий не проходит _verify / снапшот падает

1. Для `fs` — путь добавлен в `path.repo` (static) и каталог смонтирован на **всех** узлах с правами на запись; для `s3` — плагин `repository-s3` установлен на всех узлах, права IAM/ключи в keystore.
2. `POST _snapshot/<repo>/_verify` покажет ноды, не имеющие доступа.
3. Для MinIO/custom endpoint — задайте `s3.client.default.endpoint` и при необходимости `AWS_EC2_METADATA_DISABLED=true`.
4. Лимиты скорости (`max_snapshot_bytes_per_sec`) — при узкой сети снапшот будет упираться в `time_limit` SM-политики.

### Restore: index already exists / naming conflict

1. Использовать `rename_pattern`/`rename_replacement` (для alias — `rename_alias_pattern`/`rename_alias_replacement`), либо закрыть/удалить целевой индекс, либо восстановить в отдельный кластер.

### Restore отклонён из-за global state или security-индекса

1. Добавить `"include_global_state": false` и исключить `.opendistro_security` (`"indices": "-.opendistro_security"` или явный список индексов).
2. Убедиться, что у пользователя есть `manage_snapshots` и права `cluster:admin/snapshot/restore`, `indices:admin/create`, `indices:data/write/index`.

### Снапшот восстанавливается не в ту версию (INCOMPATIBLE)

1. Совместимость — только вперёд на один мажор; снапшот из более новой версии в старую не восстанавливается.
2. Перенос через промежуточный кластер: restore → `_reindex` → новый снапшот. Откат на старую версию возможен только снапшотом, сделанным до апгрейда (см. [Upgrades](./opensearch-upgrades.md)).

### `snapshot_in_progress` / снапшот не стартует

1. Уже идёт снапшот того же индекса — дождаться завершения (`GET _snapshot/_status`).
2. Достигнут лимит `snapshot.max_concurrent_operations` (default `1000`).

### SM-политика не создаёт снапшоты

1. `GET _plugins/_sm/policies/<name>/_explain` — `enabled: true`, cron корректен.
2. Установлены Index Management и Job Scheduler plugins — без них SM не работает.
3. Репозиторий зарегистрирован и верифицирован; права `snapshot_management_full_access`.
4. Ошибки job — смотреть Job Scheduler API / логи; события SM — уведомления Notifications.

### Узкое место: снапшот тянется часами

1. Это нормально для первого (полного) — дальше инкрементально.
2. Увеличить лимиты скорости, сузить `indices` (не бэкапить воспроизводимое из источника), следить за unassigned-шардами.

## Best Practices

1. Снапшоты — в **удалённое** хранилище (другой узел/площадка/бакет): локальный `fs`-бэкап не спасает при потере хоста.
2. SM-политика как код: ежедневный инкремент, `max_age`/`min_count`/`max_count` — ротация без ручной чистки.
3. Обязательная проверка restore в staging **регулярно** — непроверенный бэкап не является бэкапом; фиксировать фактический RTO.
4. `include_global_state: true` для disaster-recovery-снапшотов (шаблоны + ISM/pipeline), точечные — без него. При активном Security plugin помнить, что restore идёт с `include_global_state: false`.
5. Не удалять снапшоты руками в хранилище — только `DELETE _snapshot`.
6. `readonly: true` на restore-кластере — защита бэкапа от перезаписи.
7. Конфигурацию кластера (opensearch.yml, security YAML, шаблоны, SM/ISM-политики) хранить в Git — снапшот покрывает данные, GitOps — управление.
8. Комбинировать уровни: снапшот (длительный RPO) + CCR (малый RPO для критичных) + ISM (ретеншн «горячих» данных).
9. Перед апгрейдом — обязательный снапшот в удалённое хранилище (единственный «откат», см. [Upgrades](./opensearch-upgrades.md)).

## Дополнительная информация

* [Elasticsearch Disaster Recovery](../Elasticsearch/elasticsearch_disaster_recovery.md) — общая теория DR и паттерны стратегий.
* [CCS/CCR (OpenSearch)](./opensearch-ccs-ccr.md) — горячий standby через репликацию.
* [ISM: жизненный цикл индексов](./opensearch_ism_lifecycle.md) — ретеншн, rollover, searchable snapshots.
* [OpenSearch Administration](./opensearch_administration.md) — восстановление security-конфигурации, Remote Store, cluster settings.
* [Апгрейды OpenSearch](./opensearch-upgrades.md) — снапшот как обязательный шаг перед обновлением.
* [Capacity Planning](./opensearch_capacity_planning.md) — расчёт RPO/RTO и recovery-настроек.
* Документация OpenSearch: [Snapshots](https://docs.opensearch.org/latest/tuning-your-cluster/availability-and-recovery/snapshots/index/), [Snapshot Management API](https://docs.opensearch.org/latest/tuning-your-cluster/availability-and-recovery/snapshots/sm-api/), [Availability and recovery settings](https://docs.opensearch.org/latest/install-and-configure/configuring-opensearch/availability-recovery/).
