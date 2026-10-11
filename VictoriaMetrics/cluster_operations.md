# Операции с кластером VictoriaMetrics (vmcluster)

## Определения

**VictoriaMetrics Cluster** — распределённая сборка VictoriaMetrics из независимых компонентов: `vminsert` (приём и шардирование), `vmstorage` (хранение, Shared-Nothing), `vmselect` (запросы и агрегация). Порты по умолчанию: `vminsert` — `8480`, `vmselect` — `8481`, `vmstorage` — `8482` (HTTP), `8400`/`8401` (TCP с vminsert/vmselect).

**Tenant (accountID:projectID)** — логическая изоляция данных внутри одного кластера; адресуется в URL (`/insert/<accountID>/<projectID>/...`, `/select/<accountID>/<projectID>/...`). Мульти-тенантность — базовая функция Community-версии.

**Replication Factor (RF)** — сколько узлов `vmstorage` получают копию каждой серии. Задаётся `-replicationFactor` на `vminsert` (запись) и на `vmselect` (чтение).

**Storage node groups** — Enterprise-функция: группы `vmstorage`, изолирующие данные определённых тенантов на выделенных узлах хранения.

**Консистентный хеш** — механизм выбора storage-узла для серии на `vminsert`: одна серия всегда попадает на один и тот же node, что упрощает дедупликацию и запросы.

## Базовые концепции

### Роли компонентов

```
vmagent / remote_write / OTLP /
InfluxDB / Graphite ...                 dashboards / vmalert / API
        │                                        │
        ▼                                        ▼
   ┌────────┐   TCP 8400        ┌────────┐  TCP 8401 / HTTP 8481
   │vminsert│──consist.hash──▶│vmstorage│◀──consist.hash──vmselect
   └────────┘   записи          └────────┘        запросы
     HTTP 8480                   HTTP 8482       (кеш, мульти-тенант)
```

- **vminsert** — единственная точка приёма: принимает данные, хеширует каждую серию на выбранный узел (с учётом RF и rerouting по готовности), отдаёт сразу `204` (асинхронная запись).
- **vmstorage** — хранит и отдаёт данные; не имеет общего состояния. При переполнении диска переходит в read-only; при отказе — vminsert рерутит на здоровые узлы (данные в этом случае могут теряться для не-RF сценариев).
- **vmselect** — выполняет MetricsQL/PromQL, собирая данные со всех storage-узлов, дедуплицирует (если `-dedup.minScrapeInterval`), кеширует промежуточные результаты.

### Шардирование и репликация

- Серия (`{__name__, labels}`) отображается на storage-узел: `hash(__name__ + labels)` → node. Менять число `vmstorage` допускается, но это вызывает перераспределение серий и рост нагрузки на IOPS — планируйте заранее.
- RF>1: копии пишутся на `-replicationFactor` узлов сразу (не «в цикле»); при отказе одного узла запросы кластера продолжают работать, читая с другой копии.
- Дедупликация в кластере выполняется на **vmselect при чтении** (`-dedup.minScrapeInterval`), а не на записи.

### Многоуровневый кластер (multi-level)

`vmselect`-узлы могут выступать источником для других `vmselect`-узлов, если запущены с `-clusternativeListenAddr=:8401` — тогда верхний уровень указывает на них в `-storageNode` и «цепочка» строится по TCP так же, как с обычным `vmstorage`. Это позволяет, например, топ-уровень в одной AZ опрашивать второй уровень в других AZ, а те — локальные `vmstorage`:

```
top-level vmselect  ── TCP 8401 (-storageNode) ──▶ second-level vmselect (-clusternativeListenAddr=:8401)
                                                └──▶ vmstorage (локальная AZ)
```

Аналогично `vminsert` с `-clusternativeListenAddr=:8400` может принимать данные от другого `vminsert` (репликация между AZ на верхнем уровне). Недостатки цепочки на vminsert: скорость ограничена самым медленным звеном, а при недоступности одной AZ данные на ней гэпают — поэтому для кросс-AZ используйте [vmagent](./vmagent_overview.md) с `-remoteWrite.shardByURL`/буферизацией впереди кластера.

## Практические сценарии

### 1. Полный конфиг минимального HA-кластера (3 vmstorage, RF=2)

```bash
# vmstorage × 3
vmstorage -storageDataPath=/var/lib/vmstorage -httpListenAddr=:8482 -vminsertAddr=:8400 -vmselectAddr=:8401

# vminsert × 2 (с RF=2)
vminsert -httpListenAddr=:8480 -storageNode=vmstorage-0:8400,vmstorage-1:8400,vmstorage-2:8400 -replicationFactor=2 -maxConcurrentInserts=128

# vmselect × 2 (дедуп при чтении)
vmselect -httpListenAddr=:8481 -storageNode=vmstorage-0:8401,vmstorage-1:8401,vmstorage-2:8401 -dedup.minScrapeInterval=15s
```

> `-storageNode` указывает список storage-узлов (можно повторить флаг), DNS-имя может содержать несколько адресов. Для HA в Kubernetes — минимум 2 реплики на каждый сервис и PDB.

### 2. Мульти-тенантность

```bash
# Тенант 0 (default): /insert/0/prometheus/api/v1/write и /select/0/prometheus/api/v1/query
curl -s http://vminsert:8480/insert/0/prometheus/api/v1/write --data-binary @samples

# Тенант 1: /insert/1/prometheus/...
curl -s 'http://vmselect:8481/select/1/prometheus/api/v1/query?query=up'
```

Тенанты изолированы на чтение и запись; для управления доступом ставьте [vmauth](./vmauth_overview.md) (маршрут по `accountID`).

### 3. Балансировка и фейловер write

```bash
# vmagent пишет на оба vminsert через vmauth / load balancer
vmagent -remoteWrite.url=http://vmauth:8427/insert/0/prometheus/api/v1/write
```

`vminsert` сам рерутит серии при недоступном storage-узле (availability/slowness-based rerouting) — доп. инстансов vminsert для фейловера достаточно держать 2+.

### 4. Изменение состава vmstorage-узлов (runbook)

Консистентный хеш меняет владельца серий при каждом изменении состава — это фоновая перебалансировка (серии мигрируют на новые узлы, по диску идут merge). Проводите только в окно с запасом по IOPS/диску.

> **Принцип:** состав `-storageNode` должен быть **одинаков** на всех `vminsert`/`vmselect`. Меняйте его одновременно на всех, иначе часть запросов пойдёт на «неизвестные» узлы.

**Добавление ноды:**

1. Развернуть новый `vmstorage` (запуск с пустым `-storageDataPath`); убедиться `/health` отвечает.
2. Добавить адрес в `-storageNode` всех `vminsert` и `vmselect` (rolling-restart).
3. Наблюдать перебалансировку: растут `vm_merges_*`, IOPS на новых узлах; серии появляются через некоторое время (не мгновенно).
4. Дождаться стабилизации (`vm_dropped_rows_total` без роста, `merges` снизились).
5. Если добавляли к RF=2 кластеру — новые узлы подтянут реплики с других нод.

**Удаление ноды (graceful):**

1. Убедиться, что с ноды сняты данные, либо RF>1 позволяет уйти без потерь (при RF=1 потеряется её часть — сначала снять бэкап [vmbackup](./vmbackup_restore.md)).
2. Убрать адрес из `-storageNode` на всех `vminsert`/`vmselect` (rolling-restart) — серии перераспределятся до **останова** ноды.
3. Остановить `vmstorage` (процесс корректно закрывает партиции).
4. Сверка: `vmselect` отвечает без `"isPartial": true`, `vm_dropped_rows_total` стабилен.

> Никогда не удаляйте `vmstorage` с живыми данными «убристо» (kill -9) — риск коррупции партиций.

### 5. Мульти-тенантность: проверка изоляции и лимиты

Тенанты изолированы на **чтение и запись** в Community-версии; фильтрации/hash на уровне серий нет — данные тенантов разделены на сборке (см. `accountID/projectID`). Проверяется «честная» изоляция:

```bash
# Записать в тенант 1
curl -s http://vminsert:8480/insert/1/prometheus/api/v1/write --data-binary @samples

# В тенанте 0 данные из тенанта 1 НЕ видны
curl -s 'http://vmselect:8481/select/0/prometheus/api/v1/query?query=up' | jq '.data.result'
# В тенанте 1 — видны
curl -s 'http://vmselect:8481/select/1/prometheus/api/v1/query?query=up' | jq '.data.result'
```

Лимиты и квоты между тенантами:

- **vmauth** — ограничение доступа по маршрутам (`url_map`), аутентификация и per-user rate/concurrency-лимиты (параметр известен как `rate_limit` на пользователя — сверяйтесь с официальной документацией vmauth);
- **Enterprise**: storage node groups — выделенные «изолированные» группы `vmstorage` для конкретных тенантов (данные физически не смешиваются на накопителях);
- Глобальные лимиты кластера (`-maxLabelsPerTimeseries`, `-maxConcurrentInserts` и т.п.) — общие на всех тенантов.

## Валидация установки

```bash
# Все компоненты живы
curl -s http://vminsert:8480/health
curl -s http://vmselect:8481/health
curl -s http://vmstorage-0:8482/health

# Запись тенанта 0 и чтение
curl -s 'http://vmselect:8481/select/0/prometheus/api/v1/query?query=up' | jq .

# Метрики репликации/отказов
curl -s http://vmstorage-0:8482/metrics | grep -E '^vm_(rows|parts|merges|isReadOnly)'
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `vm_dropped_rows_total` растёт | vminsert перегружен / storage недоступен | Проверить health storage, `-maxConcurrentInserts`, корректность `-storageNode` |
| Запросы медленные асимметрично | Одна нода storage читает большинство серий (неравномерное распределение хеша) | Перепроверить состав `-storageNode` и DNS-имена; добавить storage-узлы и переждать перераспределение |
| vmstorage read-only | Диск заполнен / ФС | `df -h`, расширить диск; временно поднять `-retentionPeriod` не поможет — чистить партиции |
| Данные дублируются | Нет дедупликации на чтении | Добавить `-dedup.minScrapeInterval` на vmselect |
| Потеря данных при падении storage | RF=1 | Поднять `-replicationFactor` (запись) — история всё равно не наверстается: восстанавливать из бэкапа (vmbackup) |
| Ошибки сети между vmselect и storage | Несовпадение `-storageNode` / портов | Проверить TCP 8400/8401, firewall; `vmselect` должен видеть все storage |

## Рекомендации по эксплуатации

- Минимум **3 `vmstorage`** для отказоустойчивости; RF≥2 для данных, которые нужно пережить падение целой ноды.
- Используйте `vmauth` как единую точку входа и для мульти-тенантности — не давайте прямого доступа к vminsert/vmselect извне.
- Следите за кардинальностью (`vmestimator`), чтобы не превысить память на indexdb storage-узлов.
- Производите добавление/удаление storage-узлов в «окно» с запасом по IOPS — перераспределение серий усиливает merge (слияние партиций) и нагрузку на диск.
- Перед удалением инстанса останавливайте все `vmstorage` — иначе возможна коррупция партиций.

## Ограничения и особые случаи

- Запись асинхронная: `vminsert` вернёт `204` сразу после распределения; отказ storage между распределением и записью может потерять пачку без RF (защита — persistent queue в [vmagent](./vmagent_overview.md)).
- Кластер в первую очередь жертвует консистентностью ради доступности: при недоступности части `vmstorage` `vmselect` возвращает частичный ответ (`"isPartial": true`); для консистентных ответов включайте `-search.denyPartialResponse` (или параметр `deny_partial_response=1`).
- `-replicationFactor` на `vmselect` означает, что ответ считается полным, пока недоступно меньше RF узлов — подберите его под фактическую схему репликации записи, иначе получите ложную полноту ответов.
- Число `vmstorage`-узлов можно менять, но это приводит к перераспределению серий (консистентный хеш меняет владельца) — выполняйте в окно с запасом диска/деска, либо планируйте состав заранее.
- Многоуровневый кластер (multi-level) требует аккуратной настройки `-clusternativeListenAddr`/`-storageNode` перед включением — см. официальную документацию.

## Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md) — компоненты, порты, capacity-планирование;
- [vmauth: прокси и маршрутизация](./vmauth_overview.md) — тенанты и доступ;
- [vmbackup/vmrestore](./vmbackup_restore.md) — бэкап vmstorage;
- [DR: аварийное восстановление](./disaster_recovery.md) — сценарии потери нод/кластера;
- [Enterprise: storage node groups](./enterprise_features.md) — изоляция тенантов на группах vmstorage.
# force reindex test
