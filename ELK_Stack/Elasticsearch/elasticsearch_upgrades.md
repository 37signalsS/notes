# Upgrades и миграция Elastic Stack

**Актуально для:** Elasticsearch 9.5.x / 8.19 LTS

> Руководство по обновлению версий и миграции данных в Elastic Stack: rolling upgrade, full cluster restart, Blue-Green deployment, правила совместимости версий и откат.
>
> Связанные темы: установка кластера — [Cluster Setup](../Tutorials/cluster_setup.md); бэкапы — [ILM и политики хранения](./elasticsearch_ilm_and_retention.md); CCR — [Cross-Cluster](./elasticsearch_ccr_ccs.md); восстановление после сбоев — [Disaster Recovery](./elasticsearch_disaster_recovery.md).

## Определения

* **Rolling Upgrade** — последовательное обновление узлов кластера по одному без downtime. Применим только внутри одной major-версии (minor/patch-обновления).
* **Full Cluster Restart** — обновление с downtime: все узлы останавливаются, обновляются и запускаются согласованно. Требуется для перехода на новую major-версию (альтернатива — reindex/CCR в новый кластер).
* **Blue-Green Deployment** — создание параллельного кластера новой версии и переключение трафика после проверки.
* **Version Compatibility** — правила совместимости между версиями компонентов стека.
* **Upgrade Assistant** — инструмент Kibana (Stack Management > Upgrade Assistant) для проверки готовности к обновлению и миграции deprecated-функций.
* **Deprecated Features** — функции, которые будут удалены в следующей major-версии; остаются полностью рабочими в текущей.
* **Archived Settings** — deprecated-настройки кластера/индексов, не используемые в целевой версии, архивируются при апгрейде и должны быть удалены после него.
* **Upgrade Mode (ML)** — режим API `_ml/set_upgrade_mode`: ML-задачи приостанавливаются, а model state сохраняется автоматически; после апгрейда задачи возобновляются с последнего сохранённого состояния.

## Правила совместимости версий

### Elasticsearch и Kibana

Major-версии должны совпадать. Kibana не может быть новее Elasticsearch на уровне minor: Kibana с более новым minor не запустится (fatal error), а Elasticsearch с более новым minor работает с Kibana старого minor с предупреждением в логах — это временная конфигурация для апгрейда Elasticsearch первым.

| Соотношение версий | Результат |
|--------------------|-----------|
| Одинаковые (ES 8.15.0 ↔ Kibana 8.15.0) | OK |
| ES новее на patch (ES 8.15.1, Kibana 8.15.0) | Работает, warning в логах Kibana |
| ES новее на minor (ES 8.16.0, Kibana 8.15.0) | Работает, warning — только временно, пока Kibana не обновлён |
| Kibana новее на minor (ES 8.15.0, Kibana 8.16.0) | Fatal error — Kibana не запустится |
| Разные major (ES 8.x, Kibana 9.x) | Fatal error |

```text
[OK]   ES 8.15 + Kibana 8.15
[OK]   ES 8.16 + Kibana 8.15 (warning — ES обновлён первым, временно)
[FAIL] ES 8.15 + Kibana 8.16 (Kibana новее на minor)
[FAIL] ES 8.15 + Kibana 9.x (разные major)
```

### Beats и Logstash

Beats и Logstash отправляют данные в Elasticsearch: их major-версия должна совпадать с ES, а minor не может быть новее ES — Beats не может отправлять данные в более старую версию Elasticsearch.

| Компонент | Правило |
|-----------|---------|
| Beats | major совпадает с ES; minor ≤ ES minor |
| Logstash | major совпадает с ES; обновляется после Elasticsearch |

```text
[OK]   ES 8.15 + Beats 8.15
[OK]   ES 8.15 + Beats 8.14 (Beats старее)
[FAIL] ES 8.15 + Beats 8.16 (Beats новее ES)
[FAIL] ES 8.15 + Beats 9.0 (разные major)
```

Апгрейд между несмежными major-версиями (например, 7.x → 9.x) не поддерживается. Рекомендуемый порядок по стеку: сначала Elasticsearch и Kibana, затем Logstash и Beats.

### Путь апгрейда

* Нельзя пропускать major-версии: 7.x → 9.x напрямую не поддерживается, нужен путь 7.x → 8.x → 9.x.
* 7.x → 8.x: сначала обновиться до 7.17 (даже при full cluster restart) — это даёт Upgrade Assistant для проверки и reindex индексов, созданных до 7.0.
* 8.x → 9.x: сначала перейти на последнюю доступную 8.x.
* Апгрейд с release-кандидатов (например, `9.0.0-rc1`) не поддерживается — pre-release только для тестовых сред.
* Elastic поддерживает несколько minor-версий одновременно (out-of-order releases); перед апгрейдом читайте release notes целевой версии.

## Rolling Upgrade Elasticsearch

### Когда применим

Rolling upgrade — для обновлений внутри одной major-версии (например, 8.14 → 8.15, 9.4 → 9.5). Для перехода на новую major (8.x → 9.x) используйте full cluster restart или Blue-Green с reindex/CCR.

### Предварительные проверки

```bash
# Статус кластера (должен быть green)
GET /_cluster/health

# Deprecated features: level=critical — блокер для апгрейда
GET /_migration/deprecations

# Плагины и их версии на всех узлах
GET /_cat/plugins?v
```

### Порядок обновления узлов

Обновляйте по одному узлу в порядке групп ролей (узел с несколькими ролями относится к первой подходящей группе):

1. **Data-узлы первыми, по tier'ам:** `data_frozen` → `data_cold` → `data_warm` → `data_hot` → остальные data-узлы (например, `data_content`).
2. **Остальные узлы, не являющиеся master-eligible и data** (порядок внутри группы произвольный): `ml`, `ingest`, dedicated coordinating, `transform`, `remote_cluster_client`.
3. **Master-eligible и `voting_only` — последними.**

Почему такой порядок: обновлённый узел может присоединиться к кластеру со старым master, но узел старой версии не всегда может присоединиться к кластеру с обновлённым master. Порядок также гарантирует, что встроенные плагины (ILM, transforms) продолжают обработку данных без ошибок.

Определить узлы нужной роли:

```bash
GET /_cat/nodes?v&h=name,version,node.role,master
# → es-frozen-1  9.5.5  df  -
# → es-master-1  9.5.5  m   *
```

Если узел обновлён раньше своей группы — ошибки (например, ошибки аллокации шардов) будут наблюдаться до завершения апгрейда всех узлов группы.

### Процедура

Подготовка (выполняется один раз):

```bash
# 1. (Опционально) Отключить перемещение реплик, чтобы не гонять шарды
#    с узла, который скоро перезапустится
PUT /_cluster/settings
{
  "persistent": {
    "cluster.routing.allocation.enable": "primaries"
  }
}

# 2. (Опционально) Остановить несущественную индексацию и сделать flush
#    (обычный flush; synced flush удалён в 8.0)
POST /_flush

# 3. (Опционально) ML: приостановить задачи с сохранением model state
POST /_ml/set_upgrade_mode
{
  "enabled": true
}
```

На каждый узел:

```bash
# 4. Остановить узел
sudo systemctl stop elasticsearch.service

# 5. Обновить версию узла
#    deb/rpm: конфигурационные файлы не перезаписываются
sudo apt update && sudo apt install elasticsearch
#    zip/tarball: распаковать в НОВУЮ директорию, задать ES_PATH_CONF,
#    path.data и path.logs в elasticsearch.yml; не перезаписывать config/ и data/

# 6. Обновить плагины на этом узле (все плагины должны быть обновлены)
sudo /usr/share/elasticsearch/bin/elasticsearch-plugin install <plugin-name>

# 7. Смержить изменения конфигурации:
#    - cluster.initial_master_nodes НЕ задавать при rolling upgrade (узел
#      присоединяется к существующему кластеру); discovery.seed_hosts обязателен
#    - перенести overrides из jvm.options.d/ и log4j2.properties в новую версию
sudo vim /etc/elasticsearch/elasticsearch.yml

# 8. Запустить узел
sudo systemctl start elasticsearch.service

# 9. Проверить присоединение к кластеру
GET /_cat/nodes?v&h=name,version,node.role,master

# 10. Включить shard allocation обратно
PUT /_cluster/settings
{
  "persistent": {
    "cluster.routing.allocation.enable": null
  }
}

# 11. Дождаться green перед переходом к следующему узлу
GET /_cluster/health?wait_for_status=green&timeout=300s
# Прогресс recovery отдельных шардов:
GET /_cat/recovery?v
```

После обновления всех узлов:

```bash
# 12. ML: вернуть задачи в активное состояние
POST /_ml/set_upgrade_mode
{
  "enabled": false
}

# 13. Удалить archived settings (deprecated-настройки, архивированные при апгрейде)

# 14. Возобновить индексацию (если останавливали)
```

Пояснения к процедуре:

* Отключение shard allocation опционально: при остановке data-узла аллокация ждёт `index.unassigned.node_left.delayed_timeout` (по умолчанию одну минуту) перед репликацией шардов на другие узлы — отключение позволяет не гонять этот I/O.
* Если узлы обновляются быстро подряд, индексацию и ML-задачи можно держать приостановленными весь апгрейд; shard allocation всё равно включается после каждого узла.
* При использовании monitoring повторно используйте data-директорию: узлы идентифицируются по persistent UUID, хранящемуся в data-директории.

### Ограничения mixed-version кластера

* Mixed-version кластер валиден только во время апгрейда; одновременно поддерживаются не более двух версий.
* После того как хотя бы один узел работает на целевой версии, кластер может выполнять изменения, которые нельзя откатить: доведите апгрейд до последнего узла. Если пришлось остановиться — нельзя вернуть существующий кластер на старую версию; вариант — развернуть пустой кластер старой версии и восстановить snapshot.
* Шарды нельзя реплицировать с обновлённого узла на узел старой версии.

## Full Cluster Restart

### Когда применим

* Переход на новую major-версию (8.x → 9.x).
* Сценарии, где допустим downtime и все узлы обновляются согласованно.

### Процесс

```text
1. Создать snapshot всего кластера
2. Остановить все узлы
3. Обновить все узлы (пакеты/архивы, конфигурация, плагины)
4. Запустить все узлы согласованно
5. Проверить cluster health и функциональность
```

Без high availability во время downtime возможна потеря данных при недостаточно управляемом процессе.

## Blue-Green Deployment

### Когда использовать

- Major version upgrade (8.x → 9.x)
- Большие изменения в конфигурации
- Нельзя допустить downtime
- Требуется rollback

### Архитектура

```text
Blue Cluster (current)          Green Cluster (new)
├── ES 8.x                      ├── ES 9.x
├── Active                      ├── Standby
├── Receives traffic            ├── Receiving replicated data
└── Old Kibana                  └── New Kibana
```

### Процесс

```text
1. Deploy Green Cluster (new version)
2. Setup CCR с Blue на Green (опционально; требует Platinum-лицензии)
   или reindex из Blue в Green
3. Verify data integrity
4. Switch traffic to Green
5. Keep Blue for rollback (24-48h)
6. Decommission Blue
```

Детали CCR — в [Cross-Cluster](./elasticsearch_ccr_ccs.md).

### Reindex при миграции

```bash
# Reindex в новый кластер
POST _reindex?wait_for_completion=false
{
  "source": {
    "remote": {
      "host": "https://blue-cluster:9200",
      "username": "reindex",
      "password": "${REINDEX_PASSWORD}"
    },
    "index": "logs-*"
  },
  "dest": {
    "index": "logs-new",
    "op_type": "create"
  }
}
```

## Обновление Kibana

### Кластер Kibana (несколько инстансов)

**Rolling upgrade не поддерживается** («Rolling upgrades are unsupported in Kibana»): до запуска инстансов новой версии должны быть остановлены **все** инстансы старой — работа смешанных версий против одних и тех же системных индексов приводит к ошибкам миграции Saved Objects.

```bash
# 1. Остановить ВСЕ инстансы Kibana
sudo systemctl stop kibana

# 2. Обновить пакет на каждом инстансе
sudo apt update && sudo apt install kibana

# 3. Запустить инстансы (миграция Saved Objects идёт при старте,
#    до плагинов и HTTP-сервера)
sudo systemctl start kibana
```

Перед апгрейдом — снапшот с feature state kibana (откат невозможен без него); чек-лист и порядок проверки — в [Kibana: Эксплуатация](../Kibana/kibana_production_operations.md).

### Standalone Kibana

```bash
# Остановить
sudo systemctl stop kibana

# Обновить
sudo apt update && sudo apt install kibana

# Перезапустить
sudo systemctl start kibana
```

**Важно:** Kibana обновляется после Elasticsearch; Kibana не может быть новее ES ни на major, ни на minor (см. таблицу совместимости).

## Обновление Beats

```bash
# Остановить Beat
sudo systemctl stop metricbeat

# Обновить
sudo apt update && sudo apt install metricbeat

# Загрузить новые dashboards (если нужно)
metricbeat setup -e

# Перезапустить
sudo systemctl start metricbeat
```

Beats обновляется после Elasticsearch и Kibana. Версия Beats должна быть ≤ версии ES.

## Обновление Logstash

### Rolling Update (для кластера)

```bash
# Остановить один узел
sudo systemctl stop logstash

# Обновить
sudo apt update && sudo apt install logstash

# Перезапустить
sudo systemctl start logstash
```

### С PQ (Persistent Queue)

PQ сохраняет данные на диск, поэтому обновление безопасно — данные не теряются.

### Без PQ

1. Остановить input (Filebeat, Kafka)
2. Дождаться опустошения pipeline
3. Остановить Logstash
4. Обновить
5. Запустить
6. Включить input

Logstash обновляется после Elasticsearch.

Полная процедура для группы узлов (вывод из балансировки, ожидание опустошения очереди, rolling update по одному узлу) и контрольный чек-лист — в [Logstash: Rolling update без потери данных](../Logstash/logstash_production.md#rolling-update-без-потери-данных).

## Upgrade Assistant и Migration APIs

### Kibana Upgrade Assistant

1. **Stack Management > Upgrade Assistant**
2. Проверить readiness
3. Просмотреть deprecated features
4. Получить upgrade recommendations

### Deprecations API

```bash
GET /_migration/deprecations
# Для конкретного индекса/датастрима:
GET /logs-*/_migration/deprecations
```

API существует в 8.x и 9.x, предназначен для косвенного использования Upgrade Assistant (при включённой безопасности требуется привилегия `manage_cluster`). Сообщает о cluster-, node- и index-настройках, которые будут удалены или изменены в следующей major-версии:

```json
{
  "cluster_settings" : [
    {
      "level" : "critical",
      "message" : "Cluster name cannot contain ':'",
      "url" : "https://www.elastic.co/guide/en/elasticsearch/reference/7.0/breaking-changes-7.0.html",
      "details" : "This cluster is named [mycompany:logging], which contains the illegal character ':'."
    }
  ],
  "node_settings" : [ ],
  "index_settings" : {
    "logs:apache" : [
      {
        "level" : "warning",
        "message" : "Index name cannot contain ':'",
        "url" : "https://www.elastic.co/guide/en/elasticsearch/reference/7.0/breaking-changes-7.0.html",
        "details" : "This index is named [logs:apache], which contains the illegal character ':'."
      }
    ]
  },
  "ml_settings" : [ ]
}
```

Уровни: `warning` — апгрейд возможен, но функция уйдёт в будущей версии; `critical` — апгрейд невозможен без исправления. Внутри текущей major-версии действий не требуется: deprecated-функции продолжают работать.

### Статус миграции функций

```bash
# 9.x
GET /_migration/get_feature_upgrade_status
# 8.x
GET /_migration/system_features
```

Проверяет, какие функции требуют миграции данных в системных индексах, и статус выполняемых миграций.

## Breaking changes 9.0 (операционно значимые)

Перед апгрейдом на 9.x проверьте полный список breaking changes в release notes; ключевое:

* Удалено чтение frozen-индексов и REST-эндпоинт `unfreeze`.
* Удалены роли `data_frame_transforms_admin`/`data_frame_transforms_user` — заменены на `transform_admin`/`transform_user`.
* Удалена настройка `client.type`; удалены REST-эндпоинты совместимости с V7.
* Таймауты Elasticsearch теперь возвращают 429 вместо 5xx.
* Удалён deprecated-параметр `local` из API алиасов; более строгий парсинг `actions` в bulk API.
* EQL: `allow_partial_search_results=true` по умолчанию.
* Watcher: удалена поддержка поля `types` в search.
* Удалены deprecated-настройки `tracing.apm.*`; категория логирования `deprecation.elasticsearch` переименована в `elasticsearch.deprecation`.

## Чек-лист обновления

### Перед upgrade

- [ ] Проверить version compatibility (таблицы выше)
- [ ] Прочитать release notes и breaking changes целевой версии
- [ ] Проверить deprecated features (`GET /_migration/deprecations`; `critical` — блокер)
- [ ] Создать snapshot всего кластера
- [ ] Проверить cluster health (green) и плагины на совместимость
- [ ] Проверить кастомные скрипты (Painless)
- [ ] Для пути 7.x → 8.x: обновиться до 7.17, reindex индексов, созданных до 7.0 (Upgrade Assistant)
- [ ] ML-индексы, созданные до 8.x: reindex (инициируется из Upgrade Assistant в 8.19)
- [ ] Протестировать на staging
- [ ] Подготовить rollback plan (snapshot)
- [ ] Уведомить stakeholders

### После upgrade

- [ ] Проверить cluster health (green) и что все узлы на одной версии (`GET /_cat/nodes?v`)
- [ ] Проверить shard allocation (unassigned = 0)
- [ ] Удалить archived settings
- [ ] Проверить индексацию (indexing rate) и поиск (search latency)
- [ ] Проверить dashboards и alerts
- [ ] Мониторить 24-48 часов

## Rollback

### Официальная позиция

Elasticsearch не поддерживает downgrade на более раннюю версию. После того как первый узел работает на новой версии, кластер может выполнять изменения, которые нельзя откатить. Если апгрейд прерван:

```text
1. Развернуть пустой кластер предыдущей версии
2. Восстановить snapshot, снятый перед апгрейдом
```

### Blue-Green Rollback

```text
1. Switch traffic back to Blue
2. Удалить Green
3. Расследовать причину неудачи
```

## Устранение неполадок

### Ошибки аллокации шардов во время апгрейда

```text
Причина: узел обновлён раньше своей группы (реплика на узле старой версии
при primary на обновлённом)
Решение: продолжить апгрейд всех узлов группы; ошибка вида:
"cannot allocate replica shard to a node with version [x.x.x] since this is
older than the primary version [y.y.y]"
```

### Kibana не подключается к ES после upgrade

```text
Причина: Kibana новее ES на minor или разные major (fatal error)
Решение: привести версии к совместимым (Kibana ≤ ES на minor, major совпадает)
```

### Узел не запускается после обновления

```text
Причина: несовместимые настройки (удалённые в целевой версии) или
несовместимые индексы (созданные в 6.x и старше — требуют reindex до апгрейда на 8.x)
Решение: проверить логи узла и release notes breaking changes, удалить или
мигрировать устаревшие настройки
```

### Plugins не работают

```text
Причина: плагин не обновлён на узле или не совместим с новой версией
Решение: обновить плагин на каждом узле (elasticsearch-plugin) или удалить
```

### Slow queries после upgrade

```text
Причина: изменения в query engine
Решение: проверить fielddata и кэши, при необходимости перестроить индексы
```

## Best Practices

1. **Всегда тестируйте на staging** — перед production upgrade
2. **Создавайте snapshot** — перед каждым upgrade
3. **Rolling upgrade для minor/patch** — без downtime; только внутри одной major
4. **Blue-Green или full restart для major** — безопасный откат
5. **Обновляйте в порядке стека** — Elasticsearch → Kibana → Logstash/Beats
6. **Соблюдайте порядок ролей узлов** — data по tier'ам, master-eligible последними
7. **Мониторьте после upgrade** — 24-48 часов
8. **Документируйте изменения** — конфигурации, плагины
9. **Следите за EOL** — 8.19 LTS и 9.x current; EOL-версии не получают исправлений, не откладывайте upgrade

## См. также

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура и роли узлов.
* **[ECK: Elastic Cloud on Kubernetes](../elastic_cloud_on_k8s.md)** — upgrade в Kubernetes.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — snapshots для backup.
* **[Cross-Cluster (CCR/CCS)](./elasticsearch_ccr_ccs.md)** — CCR для Blue-Green миграции.
* **[Disaster Recovery](./elasticsearch_disaster_recovery.md)** — восстановление из snapshot.
* **[Stack Monitoring](./elasticsearch_stack_monitoring.md)** — мониторинг после upgrade.
* **[Network и Firewall](../elasticsearch_network_requirements.md)** — порты и протоколы.
* **[OpenSearch: Обзор](../OpenSearch/opensearch_overview.md)** — миграция на OpenSearch.
