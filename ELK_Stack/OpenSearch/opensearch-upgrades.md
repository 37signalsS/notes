# Апгрейды OpenSearch

**Актуально для:** OpenSearch 1.x → 2.x → 3.x. Rolling upgrade поддерживается только между **смежными** мажорными версиями. Для 3.x требуется **JDK 21** (входит в дистрибутив; с 3.4 — JDK 25 в официальных сборках).

> Правила и процедура обновления кластера: допустимые пути, подготовка, пошаговый rolling upgrade, особенности 2.x/3.x. Сравнение с апгрейдами Elasticsearch — в [Elasticsearch Upgrades](../Elasticsearch/elasticsearch_upgrades.md).

## Определения

* **Rolling upgrade** — поочерёдная остановка и обновление нод на работающем кластере, практически без даунтайма.
* **Restart upgrade** — полная остановка кластера и обновление всех нод (применяется там, где rolling невозможен).
* **Смежные мажорные версии** — обновляться можно только на один мажорный шаг: 1.x → 2.x, 2.x → 3.x; **1.x → 3.x напрямую запрещено**.
* **Cluster manager** — переименование роли `master` в 2.x и далее; при чтении `_cat/nodes` в 1.x колонка называется `master`.

## Как это работает

OpenSearch поддерживает **mixed-version cluster** во время rolling upgrade: ноды старой и новой версии совместно работают в одном кластере, пока обновление не завершится. Это работает благдаря трём принципам:

1. **Совместимость только на один мажорный шаг вперёд.** Нода новой версии может присоединиться к кластеру со старыми manager-нодами (backward compatibility), но не наоборот — старая нода не может присоединиться к кластеру, где все manager-ноды уже на новой версии. Именно поэтому **cluster manager-ноды обновляются последними** (правило 4).
2. **Плагины привязаны к версии ядра.** Плагин, собранный для другой версии ядра, не загружается — кластер не стартует. Плагины обновляются синхронно с бинарником ноды.
3. **Breaking changes только между мажорными релизами.** Minor и patch-обновления не ломают API, поэтому rolling upgrade внутри мажорной версии (например, 2.18 → 2.19) тривиален.

Для перехода между мажорными версиями допускаются два режима:
- **Rolling upgrade** — для смежных мажорных (1.x → 2.x, 2.x → 3.x), когда выполнено минимум версий (2.19.0+ для 3.x).
- **Restart upgrade (Full Cluster Restart)** — для случаев, когда rolling невозможен (breaking changes в cluster state format) или при переходе через неподдерживаемую комбинацию версий.

## Правила обновления

1. **Только смежные мажорные версии.** Путь 1.x → 3.x невозможен: сначала поднять последний 2.x, затем 3.x.
2. **Минимальная версия для 3.x — 2.19.0.** Кластер на более старом 2.x сначала обновляется до 2.19.x.
3. **Даунгрейд невозможен.** OpenSearch не поддерживает откат версии; для отката — новая установка нужной версии + восстановление из снапшота. Поэтому снапшот в **удалённое хранилище обязателен перед апгрейдом**.
4. **Порядок нод:** data-ноды первыми → ingest/ML/coordinating → **cluster manager-ноды последними**. Причина: нода может присоединиться к кластеру, где manager-ноды *старой* версии, но не может — где все manager-ноды уже *новой*.
5. **Плагины обновляются синхронно** с версией ядра: несовместимая версия плагина не загрузится, а security/alerting/CCR при несовпадении ломают работу кластера.
6. **Breaking changes — только между мажорными релизами** (поэтому патч/minor-апдейты идут обычным rolling).

### Совместимость индексов

* Маппинг-типы (`_type`) удалены в 2.0 — индексы и запросы, их использующие, требуют миграции при 1.x → 2.x.
* Индексы, созданные до 2.x (включая системные), на 3.x не поддерживаются — их нужно **reindex** в новые индексы до (или после) перехода на 3.x.
* Для 3.0 минимум JDK 21 (входит в дистрибутив; с 3.4 — JDK 25 в официальных сборках).

### Breaking changes при переходе на 3.x

Critical changes, подтверждённые в [официальной документации](https://docs.opensearch.org/latest/breaking-changes):

| Что | Breaking change | Действие перед апгрейдом |
|-----|-----------------|------------------------|
| JDK | Минимум JDK 21 (был JDK 11 в 2.x) | Проверить `java -version` на всех нодах; bundled JDK в дистрибутиве 3.x решает это автоматически |
| k-NN | NMSLIB deprecated; удалены настройки `index.knn.algo_param.ef_construction`, `index.knn.algo_param.m`, `index.knn.space_type`, `knn.plugin.enabled` | Удалить устаревшие настройки из индексов и шаблонов; переключить движок на Faiss/Lucene |
| Performance Analyzer | RCA-агент удалён (deprecated с 2.19, removed в 3.0) | Мигрировать на Telemetry Plugin (OpenTelemetry) |
| Remote Store | Searchable snapshots требуют роль `warm` (роль `search` больше не подходит) | Перенастроить роли нод перед апгрейдом |
| Thread pool | Удалены `thread_pool.test.max_queue_size`, `thread_pool.test.min_queue_size` | Удалить из `opensearch.yml` |
| Index store | Удалена `index.store.hybrid.mmap.extensions` | Удалить из конфигурации |
| Transport | Плагин transport-nio удалён (Netty — стандарт) | Убедиться, что Netty используется |
| Security | Blake2b hash теперь корректно использует salt — значения изменятся | Сбросить/пересоздать хеши паролей при необходимости |
| Archived settings | Deprecated-настройки архивируются с префиксом `archived.` и блокируют `PUT /_cluster/settings` | Удалить или явно заархивировать |

### Исторический путь миграции с Elasticsearch

OpenSearch 1.0 поддерживал апгрейд с Elasticsearch OSS 6.8.0–7.10.2 и Open Distro for Elasticsearch (ODFE) — как обычный междуверсионный апгрейд ядра (namespace `org.elasticsearch` → `org.opensearch` для плагинов). Актуально только для легаси-переездов.

## Процедура rolling upgrade

### Подготовка

```bash
# 1. Снапшот В удалённое хранилище — до начала, единственный способ «отката»
PUT _snapshot/upgrade_backup
{
  "type": "s3",
  "settings": { "bucket": "opensearch-backups", "base_path": "pre-upgrade" }
}
PUT _snapshot/upgrade_backup/snapshot-1?wait_for_completion=true

# 2. Здоровье кластера обязано быть green — устранить unassigned шарды ДО старта
GET _cluster/health?pretty
```

**Pre-flight checklist** перед началом rolling upgrade:

1. **Снапшот в удалённое хранилище** выполнен (см. выше) — это единственный «откат», т.к. даунгрейд невозможен.
2. **Здоровье кластера** — `GET _cluster/health?pretty` → `green` (все primaries и реплики распределены).
3. **Устранить unassigned shards**:
   ```bash
   GET _cat/shards?v&h=index,shard,prirep,state,unassigned.node,unassigned.reason
   # → найти и исправить (allocate, cancel, или удалить orphaned)
   ```
4. **JVM / JDK** — для перехода на 3.x проверить минимум JDK 21 на всех нодах (или убедиться, что bundled JDK в дистрибутиве 3.x будет использован):
   ```bash
   java -version 2>&1
   ```
5. **Плагины** — зафиксировать установленные плагины и их версии на каждой ноде (проверка несовместимости после апгрейда):
   ```bash
   bin/opensearch-plugin list
   ```
6. **Deprecated settings** — проверить конфиги на устаревшие настройки, которые будут заархивированы при апгрейде (блокируют `PUT _cluster/settings`):
   ```bash
   GET _cluster/settings?include_defaults=true&filter_path=**.cluster.routing.allocation.enable
   # → проверить отсутствие deprecated thread_pool.test.*, index.store.hybrid.mmap.extensions и др.
   ```
7. **Breaking changes** — изучить [release notes](https://docs.opensearch.org/latest/breaking-changes) целевой версии; для 3.x — k-NN, Performance Analyzer RCA, searchable snapshots node role.
8. **Security** — заархивировать текущую security-конфигурацию через `securityadmin.sh -backup /tmp/sec-backup` перед апгрейдом.

### Пошагово

```bash
# 3. Отключить перераспределение реплик — ноды будут уходить со своей очередью
PUT _cluster/settings
{
  "persistent": { "cluster.routing.allocation.enable": "primaries" }
}
# → останавливается движение Lucene-сегментов между нодами
```

4. Приостановить неэкстренную индексацию и завершающие операции (flush/merge-нагрузку) — indexing-потоки продолжат работать, но снижение нагрузки уменьшит квоты во время перезапуска.
5. Определить первую ноду (`GET _cat/nodes?v&h=name,version,node.role,cluster_manager`) и обновлять в порядке: **data → ingest/ML/coordinating → cluster manager**. Примечание: в 1.x колонка называется `master`, в 2.x+ — `cluster_manager` (алиас `master` deprecated, но работает для обратной совместимости во время mixed-version).
6. На каждой ноде:
   * остановить OpenSearch;
   * обновить бинарник/контейнер до новой версии;
   * обновить плагины: `bin/opensearch-plugin install <plugin>@<new-version>` (или менеджер пакетов/Ansible — см. [Ansible Deployment](./opensearch_ansible_deployment.md));
   * проверить конфиги на breaking changes (release notes);
   * запустить ноду.
7. Проверить возвращение ноды: `GET _cat/nodes?v&h=name,version,node.role,cluster_manager` — версия обновилась, роль на месте; `GET _cluster/health` — между нодами допустим yellow (реплики перераспределяются после включения allocation).
8. Повторять для всех нод.
9. После последней ноды включить перераспределение обратно:

```bash
PUT _cluster/settings
{
  "persistent": { "cluster.routing.allocation.enable": "all" }
}
```

10. Финальная проверка: `GET _cluster/health` → green; версии всех нод в `GET _cat/nodes?v&h=name,version,node.role,cluster_manager`; плагины `bin/opensearch-plugin list`; Security health `GET _plugins/_security/health`; ключевые API (alerting, ISM, CCS/CCR) отвечают.
11. Для 3.x: reindex индексов, созданных до 2.x; проверить запросы и шаблоны на breaking changes.
12. **Security plugin**: после апгрейда выполнить `securityadmin.sh -backup` → `securityadmin.sh -cd config/opensearch-security/` для применения конфигурации из YAML в новом формате.

### OpenSearch Dashboards

Обновляется после ядра (или до — отдельным сервисом); поддерживает **restart upgrade**. Версия Dashboards должна соответствовать версии OpenSearch кластера (same major, same minor).

**Подготовка к апгрейду Dashboards:**

```bash
# 1. Снапшот системных индексов .kibana* — ДО обновления
PUT _snapshot/upgrade_backup/snapshot-dashboards?wait_for_completion=true
{
  "indices": ".kibana*",
  "include_global_state": false
}

# 2. Проверить текущую версию через API
GET /api/status
# → {"version":{"number":"2.xx.x",...}}
```

**Порядок обновления стека:** снапшот `.kibana*` → обновление ядра OpenSearch → обновление Dashboards → проверка `/api/status` и перенос saved objects (auto-migrate при первом старте новой версии).

### Restart upgrade (Full Cluster Restart)

Применяется, когда rolling upgrade невозможен: breaking changes в cluster state format, переход на новую major с incompatible настройками, либо восстановление после сбоя. В отличие от rolling, кластер находится в downtime на время остановки всех нод.

**Подготовка** (см. также [Ansible Deployment](./opensearch_ansible_deployment.md), сценарий 8):

1. Снапшот в удалённое хранилище + бэкап `securityadmin.sh -backup` — обязательны (см. раздел Подготовка выше).
2. Здоровье кластера `green` — устранить unassigned shards.
3. Зафиксировать плагины (`bin/opensearch-plugin list`) и конфиги (`opensearch.yml`, `jvm.options.d/*.options`, `config/opensearch-security/`).
4. Для tarball-установок: заархивировать `data/`, `config/`, `plugins/`, TLS-сертификаты.

**Пошагово:**

1. Приостановить индексацию и flush всех индексов (`POST _flush/sync` для активных).
2. Остановить все ноды одной коллекцией: `systemctl stop opensearch` (опционально в порядке data → ingest → cluster manager).
3. На каждой ноде: обновить пакет/бинарник и плагины до новой версии; проверить breaking changes в конфигах.
4. Добавить настройки восстановления (Ansible deployment.md:560):

```yaml
# opensearch.yml — ускорить recovery после full restart
gateway.recover_after_nodes: 2      # ждать минимум N узлов перед recovery
gateway.expected_nodes: 5           # целевое число узлов
gateway.recover_after_time: 5m      # таймаут recovery
```

5. Запустить ноды в обратном порядке (cluster manager первыми) с шагом 30 секунд между нодами для elect-safe bootstrap.
6. После старта всех нод: `GET _cluster/health?pretty` → `green`; удалить настройки `gateway.*` из `opensearch.yml`.
7. Переинициализировать Security plugin (см. [Administration](./opensearch_administration.md)):

```bash
./plugins/opensearch-security/tools/securityadmin.sh \
  -cd config/opensearch-security/ -icl -nhnv
```

8. Для 3.x: выполнить reindex индексов, созданных до 2.x; проверить запросы и шаблоны.

## Troubleshooting

### Нода не присоединяется после обновления

1. Убедиться, что это не cluster manager-нод и что не все manager-ноды уже на новой версии (порядок: manager — последними).
2. Логи ноды: несовместимый плагин (удалить/обновить), несовместимая конфигурация.
3. Кластер ушёл в red из-за потери кворума manager-нод — не обновлять несколько manager-нод одновременно.

### Плагин не загрузился

1. Версия плагина ≠ версия ядра — обновить плагин до той же версии.
2. Сторонний плагин без сборки под новую версию — найти совместимую версию либо временно демонтировать (security/CCR — критичные, их отсутствие ломает функциональность).

### Ошибка несовместимости индексов на 3.x

1. Индекс создан до 2.x — выполнить reindex в новый индекс (`POST _reindex`), шаблоном задать актуальный mapping.
2. Использовать снапшот: откат невозможен, только restore на версию ≤ 2.19.

### `PUT _cluster/settings` отклоняется с ошибкой unknown setting

1. При апгрейде на 3.x deprecated-настройки архивируются с префиксом `archived.` и блокируют любые `PUT /_cluster/settings` (часто затрагивает ISM: `plugins.index_state_management.*`).
2. Решение: либо удалить устаревшие настройки из `opensearch.yml`, либо явно заархивировать их в API-запросе:

```bash
GET _cluster/settings?include_defaults=true&filter_path=persistent.**.archived.*
# → найти проблемные archived настройки, затем:
PUT _cluster/settings
{
  "persistent": { "cluster.routing.allocation.enable": "all" }
}
```

### Апгрейд застрял: allocation в primaries после сбоя

1. Проверить `GET _cluster/settings?include_defaults=true&filter_path=**.cluster.routing.allocation.enable` — если `primaries` остался persistent-настройкой после прерванного апгрейда, вернуть `all`.
2. Разобраться с unassigned-шардами до возобновления (см. [Troubleshooting](./opensearch_troubleshooting_indexing.md)).

## Best Practices

1. Снапшот в удалённое хранилище — обязательный пункт чек-листа, это единственный «откат».
2. Сначала поднять кластер до последней версии текущего мажора (например 2.19.x), потом планировать 3.x.
3. Порядок нод: cluster manager — строго последними; никогда не обновлять все manager-ноды вместе.
4. Обновлять по одному ноду, между нодами — `_cluster/health` и `_cat/nodes`.
5. Плагины версионировать в той же автоматизации, что и ядро (Ansible/пакеты) — исключить расхождение версий.
6. Читать release notes целевой версии: breaking changes появляются именно на мажорных шагах.
7. Тренировать процедуру на staging ( Rolling upgrade lab из документации) — порядок нод и плагинов отрабатываются заранее.
8. После апгрейда — плановый reindex по мере вытеснения старых индексов ISM-политикой, чтобы хранение соответствовало новой версии.
9. Performance Analyzer RCA deprecated с 2.19, удалён в 3.x — мигрировать на Telemetry Plugin до апгрейда.
10. Security plugin: перед апгрейдом — `securityadmin.sh -backup`; после — переинициализировать конфиг из YAML; Demo certs заменить на production PKI.

## Дополнительная информация

* [Elasticsearch Upgrades](../Elasticsearch/elasticsearch_upgrades.md) — сравнение подходов ES/OpenSearch.
* [OpenSearch: Обзор](./opensearch_overview.md) — версии и возможности.
* [OpenSearch Ansible Deployment](./opensearch_ansible_deployment.md) — автоматизация обновления нод и плагинов.
* [Снапшоты и DR](./opensearch-disaster-recovery.md) — подготовка снапшота перед апгрейдом.
* [OpenSearch Administration](./opensearch_administration.md) — кластерные настройки, SegRep/Remote Store (учитывать при остановке нод).
* [Безопасность: TLS и SSO](./opensearch-security-tls-sso.md) — security plugin конфигурация, securityadmin.sh.

### Перекрытие с существующими файлами (§0.10)

* `Elasticsearch/elasticsearch_upgrades.md` — SSoT по общим принципам (rolling, snapshot-first, plugin sync); настоящий файл — правила OpenSearch: смежные мажоры, минимум 2.19.0 для 3.x, порядок нод, запрет даунгрейда.
* `OpenSearch/opensearch_ansible_deployment.md` — как автоматизировать установку/обновление (пакеты, rolling restart, gateway settings); процедура здесь, инструменты — там.
* `OpenSearch/opensearch_overview.md` — версионная матрица, critical requirements для 3.x (JDK 21, k-NN, PGP keys), RBS migration; дополняет breaking changes здесь.
* `OpenSearch/opensearch-security-tls-sso.md` — securityadmin.sh, demo certs, TLS; security-specific upgrade steps (backup/re-init) здесь, конфигурация — там.
* `OpenSearch/opensearch-disaster-recovery.md` — снапшот как обязательный шаг перед апгрейдом; restore compatibility — один мажор вперёд.
* `OpenSearch/opensearch_helm_deployment.md` — Helm-специфичные апгрейды (updateStrategy, majorVersion); процедура здесь, Helm-детали — там.
* `OpenSearch/opensearch-ccs-ccr.md` — CCR follower-first правило при апгрейде (не в SSoT, но важно для multi-cluster).
