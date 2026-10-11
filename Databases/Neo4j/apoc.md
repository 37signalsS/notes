# Neo4j: APOC — библиотека расширений

**Актуально для:** APOC 2026.09.x (Neo4j 2026.09.x) / APOC 5.26.x (Neo4j 5.26 LTS)

**APOC (Awesome Procedures on Cypher)** — библиотека процедур и функций, официально поддерживаемая Neo4j. Это не сторонний плагин: APOC поставляется в составе дистрибутива Neo4j (в каталоге `$NEO4J_HOME/labs`), разрабатывается той же командой и привязана к внутренним API ядра. Именно поэтому версия APOC жёстко привязана к версии Neo4j — это главный эксплуатационный нюанс библиотеки.

Историческое название расшифровывается как «Awesome Procedures on Cypher»; в документации Neo4j 2025.01+ имя произносится просто как «APOC».

APOC покрывает задачи, для которых в языке Cypher нет выразительности: файловый и сетевой импорт/экспорт данных, пакетная обработка больших объёмов, фоновые задачи, триггеры, часть графовых алгоритмов, работа с датами, строками и геоданными.

## Совместимость версий

### Правило соответствия APOC и Neo4j

APOC использует **внутренние API** Neo4j, поэтому бинарная совместимость между произвольными версиями не гарантирована. Правило, установленное документацией:

> **Год и месяц** версии APOC должны совпадать с годом и месяцем версии Neo4j.
> Номера patch-уровня совпадать не обязаны.

Пример: APOC 2025.06.2 совместим с Neo4j 2025.06.0.

Схема нумерации APOC — `<версия-neo4j>.<счётчик-релизов-apoc>`. Финальная часть инкрементально растёт с каждым релизом APOC внутри одного месяца.

Если на старте обнаружен несовместимый JAR, в журнале появляется предупреждение уровня `WARN`:

```text
# → neo4j.log: предупреждение о несовместимой версии APOC
```

Это самая частая причина «APOC установлен, но процедуры не находятся» после ручного обновления Neo4j.

### Матрица соответствия

| Версия APOC | Версия Neo4j | Ветка |
| :--- | :--- | :--- |
| 2026.09.0 | 2026.09.0 (2026.09.x) | Текущая |
| 2026.08.1 | 2026.08.1 (2026.08.x) | Предыдущая |
| 2026.07.1 | 2026.07.1 (2026.07.x) | Предыдущая |
| 5.26.31 | 5.26.31 (5.26.x) | LTS |

Начиная с 2025.01 Neo4j перешёл на календарную схему версий `YYYY.MM.Patch`. Год в номере **не** является признаком мажорной версии — все релизы образуют один непрерывный поток, и год нельзя читать как границу обратной совместимости.

Полный список релизов и матрица соответствия: [APOC → Installation](https://neo4j.com/docs/apoc/current/installation/).

## APOC и версии Cypher

Начиная с Neo4j 2025.06 язык разделён на две ветви: **Cypher 5** и **Cypher 25**. Разработка языка идёт в Cypher 25; Cypher 5 заморожен на стабильном состоянии.

Это напрямую влияет на APOC:

- **APOC 2025.06** — последний релиз с обновлениями для Cypher 5.
- **APOC 2025.07 и новее** — совместимы **только** с Cypher 25.
- Процедуры и функции APOC привязаны к конкретной версии Cypher. То, что было удалено в Cypher 25, в APOC 2025.06+ доступно только при `CYPHER 5`.
- Базы, созданные **после** выхода 2025.06, по умолчанию используют Cypher 5 — то есть поведение базы может отличаться от поведения новой базы того же релиза.

```cypher
// Принудительный запуск запроса на Cypher 5 (для APOC 2025.06+)
CYPHER 5
CALL apoc.create.uuids(10)
```

Версию языка по умолчанию можно задать на уровне базы. Базы, работающие на Cypher 5, получают только замороженный набор процедур APOC — это нужно учитывать при планировании обновлений: сначала миграция языка, потом обновление APOC.

Полный список удалений и замен: [APOC → Additions, deprecations, removals](https://neo4j.com/docs/apoc/current/deprecations-and-additions/).

## Установка

### Предварительные требования

- Установленный и работающий Neo4j (см. [Установка и настройка](./installation_and_setup.md)).
- Свободное место в `$NEO4J_HOME/plugins`.
- Права на запись в `$NEO4J_HOME/conf` для создания `apoc.conf`.
- Для production-контейнеров — доступ к `https://github.com/neo4j/apoc/releases` на этапе сборки образа.

### Docker: разработка и CI

Самый быстрый способ — переменная окружения `NEO4J_PLUGINS`. Образ скачивает JAR подходящей версии и настраивает его в рантайме.

```bash
docker run -d \
  --name neo4j-apoc \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password123 \
  -e NEO4J_PLUGINS='["apoc"]' \
  neo4j:2026.09.0-community
```

В выводе контейнера появляются две строки, подтверждающие установку:

```text
# → Fetching versions.json for Plugin 'apoc' from https://neo4j.github.io/apoc/versions.json
# → Installing Plugin 'apoc' from https://github.com/neo4j/apoc/releases/download/2026.09.0/apoc-2026.09.0-core.jar to /plugins/apoc.jar
```

> **Ограничение.** Механизм `NEO4J_PLUGINS` предназначен для сред разработки. В production документация его не рекомендует: на этапе старта контейнера выполняется сетевой запрос, и от его успеха зависит запуск БД.

### Docker: production

В production JAR скачивается заранее и монтируется в `/plugins` как том. Сетевых обращений при старте нет, версия зафиксирована в образе.

```bash
# 1. Скачать JAR в локальный каталог сборки
mkdir -p plugins && pushd plugins
wget https://github.com/neo4j/apoc/releases/download/2026.09.0/apoc-2026.09.0-core.jar
popd

# 2. Запуск с проброшенным каталогом плагинов
docker run -d \
  --name neo4j-prod \
  -p 7474:7474 -p 7687:7687 \
  -v neo4j_data:/data \
  -v "$(pwd)/plugins:/plugins" \
  -e NEO4J_AUTH=neo4j/CHANGE_ME_STRONG_PASSWORD \
  neo4j:2026.09.0-community
```

### Ручная установка на хост

APOC входит в поставку Neo4j — JAR лежит в каталоге `labs` рядом с `conf`, `bin` и `plugins`.

```bash
# Путь к каталогу с настройками задаётся переменной окружения
cd $NEO4J_HOME

# Перенести JAR из labs в plugins
sudo mv labs/apoc-*-core.jar plugins/

# Перезапуск
sudo systemctl restart neo4j
# → сообщение об успешном старте в journalctl
```

Альтернатива для Neo4j Desktop: после создания базы перейти на экран **Manage → Plugins**, нажать **Install** в карточке APOC и дождаться зелёной отметки.

### Проверка установки

```cypher
// Сколько процедур и функций APOC зарегистрировано
SHOW PROCEDURES YIELD name
WHERE name STARTS WITH 'apoc.'
RETURN count(*) AS apocProcedures;
```

```cypher
// Проверка конкретного пакета и признака админской процедуры
SHOW PROCEDURES YIELD name, admin
WHERE name STARTS WITH 'apoc.trigger.'
RETURN name, admin
ORDER BY name;
```

```cypher
// Полный листинг с сигнатурами и признаком устаревания
SHOW PROCEDURES YIELD name, signature, option
WHERE name STARTS WITH 'apoc.periodic.'
RETURN name, signature, option;
```

Пустой результат означает, что JAR не подхватился или версия несовместима — см. раздел «Диагностика».

## Конфигурация

### Где задаются настройки APOC

**Начиная с Neo4j 5 настройки `apoc.*` не поддерживаются в `neo4j.conf`.** Все параметры библиотеки перенесены в отдельный файл `apoc.conf` либо задаются переменными окружения.

| Способ | Расположение | Приоритет |
| :--- | :--- | :--- |
| Переменные окружения | `export key=val`, `--env` в Docker | Выше |
| `apoc.conf` | Тот же каталог, что и `neo4j.conf` (по умолчанию `neo4j/conf`) | Ниже |

Порядок в таблице соответствует приоритету: переменная окружения перекрывает значение из `apoc.conf`.

Файл `apoc.conf` **не создаётся автоматически** при установке плагина — его нужно создать вручную.

```properties
# apoc.conf — полный пример для production
# Чтение файлов из каталога импорта
apoc.import.file.enabled=true
# Запись файлов в каталог импорта
apoc.export.file.enabled=true
# Доступ к ФС за пределами server.directories.import — НЕ включать без необходимости
# apoc.import.file.use_neo4j_config=false
# Триггеры
apoc.trigger.enabled=true
apoc.trigger.refresh=60000
```

### Справочник настроек

| Параметр | Тип | По умолчанию | Назначение |
| :--- | :--- | :--- | :--- |
| `apoc.import.file.enabled` | boolean | `false` | Разрешить чтение локальных файлов |
| `apoc.export.file.enabled` | boolean | `false` | Разрешить запись локальных файлов |
| `apoc.import.file.use_neo4j_config` | boolean | `true` | Управлять доступом к ФС настройками Neo4j |
| `apoc.http.timeout.connect` | integer | `10000` | Таймаут установки исходящего HTTP-соединения, мс; `0` — бесконечно |
| `apoc.http.timeout.read` | integer | `60000` | Таймаут чтения данных HTTP, мс; `0` — бесконечно |
| `apoc.jobs.scheduled.num_threads` | integer | CPU / 4 | Размер пула потоков планировщика (`apoc.periodic.*`) |
| `apoc.jobs.pool.num_threads` | integer | CPU * 2 | Размер пула фоновых задач |
| `apoc.jobs.queue.size` | integer | `apoc.jobs.pool.num_threads` * 5 | Размер очереди пула |
| `apoc.spatial.geocode.provider` | string | `osm` | Провайдер геокодирования |
| `apoc.trigger.enabled` | boolean | `false` | Включить пакет `apoc.trigger` |
| `apoc.trigger.refresh` | integer | `60000` | Период проверки изменений триггеров по кластеру, мс |
| `apoc.max.decompression.ratio` | integer | `200` | Предельное отношение размера распакованного файла к сжатому; отрицательное значение снимает лимит |

`apoc.max.decompression.ratio` — защита от распаковки-бомб в процедурах загрузки. Значение по умолчанию оставлять как есть; отключать (`-1`) стоит только с явным пониманием риска.

### Алиасы настроек

Длинные URL можно вынести в `apoc.conf` под коротким именем. Ключ `apoc.json.<алиас>.url` определяет переменную, используемую в `apoc.load.json('<алиас>', …)`.

```properties
# apoc.conf
apoc.json.myJson.url=https://api.example.com/users
```

```cypher
// Вместо полного URL
CALL apoc.load.json('myJson') YIELD value
RETURN value;
```

Алиасы пригодятся и для выноса секретов из конфигурации, и для сокращения длинных строк в скриптах миграции.

### Подстановка значений из внешних файлов

APOC использует механизм command expansion Neo4j: значение вида `$(команда)` вычисляется при старте. Это позволяет не хранить пароли и ключи в `apoc.conf` открытым текстом.

```properties
# apoc.conf
apoc.some.key=$(cat /run/secrets/some_key)
```

**Требуется** флаг запуска `--expand-commands`, иначе такие записи трактуются как некорректные настройки:

```bash
bin/neo4j start --expand-commands
```

При управлении через systemd флаг нужно передать команде запуска в юните — в штатном `neo4j.service` из документации Neo4j он отсутствует, поэтому правится `ExecStart` вашего собственного юнита:

```bash
# Проверить, какой ExecStart используется сейчас
systemctl cat neo4j | grep ExecStart
# → ExecStart=/opt/neo4j/bin/neo4j console

# После правки юнита
sudo systemctl daemon-reload
sudo systemctl restart neo4j
```

Механизм command expansion включается только на старте процесса, поэтому изменение `apoc.conf` требует перезапуска Neo4j, а не применения динамической настройки.

### Настройки в Docker

Имена переменных окружения для настроек Neo4j/APOC в официальном образе имеют форму `NEO4J_<ключ>`, где точки и дефисы заменены на подчёркивания, а литеральные подчёркивания удваиваются.

```bash
docker run -d \
  -p 7474:7474 -p 7687:7687 \
  --name neo4j-apoc \
  -e NEO4J_apoc_import_file_enabled=true \
  -e NEO4J_apoc_export_file_enabled=true \
  -e NEO4J_apoc_import_file_use__neo4j__config=true \
  -e NEO4J_PLUGINS='["apoc"]' \
  neo4j:2026.09.0-community
```

Обратите внимание на `use__neo4j__config` — двойные подчёркивания соответствуют точкам и дефисам в имени параметра `apoc.import.file.use_neo4j_config`.

## Модель безопасности: allowlist и unrestricted

APOC разделяет процедуры на два класса, и для каждого действует отдельный параметр Neo4j.

### `dbms.security.procedures.allowlist` — какие процедуры загружены

**Значение по умолчанию — загружать все процедуры и функции.** Поэтому утверждение «забыли добавить `apoc.*` в allowlist» неверно: процедуры и так доступны. Документация прямо рекомендует **переопределить** настройку минимальным списком.

```conf
# neo4j.conf — пример: только реально используемое
dbms.security.procedures.allowlist=apoc.math.maxInt,apoc.rel.*,apoc.load.json,apoc.export.cypher.*
```

Если APOC приложению не нужен вовсе, рекомендация документации — удалить плагин, а не оставлять его загруженным «на всякий случай».

### `dbms.security.procedures.unrestricted` — процедуры на внутренних API

Часть процедур APOC использует внутренние API Neo4j и **по умолчанию отключена** — даже при пустом allowlist. Такие процедуры возвращают ошибку доступа, пока их не разблокируют.

```conf
# neo4j.conf
dbms.security.procedures.unrestricted=apoc.cypher.runFirstColumn,apoc.cypher.*,apoc.meta.stats
```

Конкретный пример — `apoc.meta.stats()`: процедура помечена как «restricted on on-premise instances» и требует явного разрешения.

```cypher
// Проверка, какие процедуры требуют прав администратора и какому пакету соответствуют
SHOW PROCEDURES YIELD name, admin, rolesExecution
WHERE name STARTS WITH 'apoc.'
RETURN name, admin, rolesExecution
ORDER BY name
LIMIT 20;
```

В Docker:

```bash
docker run -d \
  -p 7474:7474 -p 7687:7687 \
  --name neo4j-apoc \
  -e NEO4J_dbms_security_procedures_unrestricted="apoc.cypher.*" \
  -e NEO4J_PLUGINS='["apoc"]' \
  neo4j:2026.09.0-community
```

### Принцип наименьших привилегий

Оба параметра следует задавать **поимённо, по пакетам**, а не как `apoc.*`. Полное раскрытие библиотеки снимает ограничения, которые существуют не зря: процедуры файлового доступа, внешних вызовов и внутренних API расширяют поверхность атаки заметно сильнее, чем процедуры работы со строками.

Практическое правило: `allowlist` перечисляет используемое, `unrestricted` — только то, что действительно упирается во внутренние API. Всё остальное — выключено.

Подробнее: [Securing Extensions](https://neo4j.com/docs/operations-manual/current/security/securing-extensions/).

## Типичные сценарии

### Загрузка JSON

```cypher
// Из URL — поток объектов, если ответ это массив
WITH 'https://api.example.com/users' AS url
CALL apoc.load.json(url) YIELD value
MERGE (p:Person {name: value.name})
SET p.email = value.email, p.age = value.age;

// Из локального файла — путь относительно каталога server.directories.import
CALL apoc.load.json("file:///person.json") YIELD value
RETURN value;
```

Параметры конфигурации `apoc.load.json`:

| Параметр | Тип | По умолчанию | Назначение |
| :--- | :--- | :--- | :--- |
| `failOnError` | boolean | `true` | Прерывать выполнение при ошибке разбора JSON |
| `compression` | enum | `NONE` | `NONE`, `BYTES`, `GZIP`, `BZIP2`, `DEFLATE`, `BLOCK_LZ4`, `FRAMED_SNAPPY` — для бинарного входа |
| `pathOptions` | list of string | `[]` | Опции обхода JSONPath |

Второй позиционный аргумент — выражение JSONPath. Оно позволяет адресовать вложенные структуры без разворачивания верхних уровней:

```cypher
// $.items[?(@.answer_count>0)].answers[*] — только элементы с непустым массивом ответов
CALL apoc.load.json(url, '$.items[?(@.answer_count>0)].answers[*]') YIELD value
RETURN value;
```

Если JSON-документ — `LIST`, процедура импортирует поток значений; если `MAP` — одно значение.

> **SSRF.** `apoc.load.json` выполняет запросы по внешним URL и уязвим к Server-Side Request Forgery. В Enterprise Edition ограничение задаётся load-privileges с CIDR; для admin-пользователей дополнительно требуется `DENY EXECUTE BOOSTED PROCEDURE apoc.* ON DBMS TO PUBLIC`, иначе boosted-привилегии обойдут ограничение. В Community Edition используется `internal.dbms.cypher_ip_blocklist`. Если загрузка по URL не нужна — не давайте процедуре доступ в allowlist.

> `apoc.load.jsonParams` (заголовки и payload HTTP-запроса) **удалён в Cypher 25**. На APOC 2025.06+ доступен только под префиксом `CYPHER 5`. Планируйте замену до миграции языка.

### Массовая обработка: `apoc.periodic.iterate`

> **Статус:** процедура **устарела в Cypher 25** (начиная с APOC 2026.04 / Neo4j 2026.04). Прямая замена — `CALL {…} IN CONCURRENT TRANSACTIONS`.

```cypher
CALL apoc.periodic.iterate(
  "MATCH (p:Person) WHERE p.processed IS NULL RETURN p",
  "SET p.processed = true, p.processedAt = datetime()",
  {batchSize: 5000, parallel: true}
)
YIELD batches, total, errorMessages, wasTerminated
RETURN batches, total, errorMessages, wasTerminated;
```

| Параметр | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `batchSize` | `10000` | Число операций в одной транзакции |
| `parallel` | `false` | Параллельное выполнение батчей |
| `retries` | `0` | Повторы с паузой 100 мс при сбое операции |
| `batchMode` | `BATCH` | `BATCH`, `SINGLE`, `BATCH_SINGLE` |
| `params` | `{}` | Внешние параметры для операторного запроса |
| `concurrency` | Число CPU | Размер параллелизма при `parallel: true` |
| `failedParams` | `-1` | Сколько наборов параметров упавших батчей вернуть |
| `planner` | `DEFAULT` | `DEFAULT`, `COST`, `IDP`, `DP` |

Эксплуатационные предостережения:

- `parallel: false` не означает «свободные потоки». APOC намеренно переиспользует пул с максимальным размером 1, чтобы исключить параллелизм. Следствие: два одновременных `apoc.periodic.iterate` выполняются строго последовательно.
- `parallel: true` использует пул, размер которого задаётся `apoc.jobs.pool.num_threads` (по умолчанию CPU * 2).
- **Параллелизм действует на все базы, а не на текущую.** Итерация по `db1` повлияет на производительность `db2`.
- Для операций, изменяющих или удаляющих связи, либо не используйте `parallel: true`, либо разбивайте работу так, чтобы каждое поддерево обновлялось одной операцией, и включайте `retries`.

Современная замена на чистом Cypher 25:

```cypher
MATCH (p:Person) WHERE p.processed IS NULL
CALL (p) {
  SET p.processed = true, p.processedAt = datetime()
} IN CONCURRENT TRANSACTIONS
RETURN count(*) AS processed;
```

Обратите внимание на структуру: переменная `p` не переносится в подзапрос как связанный объект — передаётся через `CALL (p) { … }`. Массовая альтернатива, не требующая имён переменных:

```cypher
MATCH (p:Person) WHERE p.processed IS NULL
CALL {
  WITH p
  SET p.processed = true, p.processedAt = datetime()
} IN CONCURRENT TRANSACTIONS;
```

### Фоновые задачи: `apoc.periodic.repeat`

`apoc.periodic.repeat` выполняет запрос по расписанию и, в отличие от `apoc.periodic.iterate`, **не устарел**. Используйте его для регламентных задач: расчёта метрик, инкрементальной поддержки данных, ночных пересчётов.

Сигнатура: `apoc.periodic.repeat(name, statement, rate [, config])`, где `rate` — задержка в секундах между запусками. Первый аргумент — **имя задачи**, по нему же она останавливается.

```cypher
CALL apoc.periodic.repeat(
  "touch-nodes",                          // имя задачи — ключ для отмены
  "MATCH (n) SET n.touchedAt = datetime()",
  3600                                    // интервал в секундах
);
```

| Параметр конфигурации | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `params` | `{}` | Параметры для повторяемого запроса |
| `cancelOnError` | `true` | Отменять задачу при ошибке запроса (с 2025.08) |

Поведение по умолчанию важно для эксплуатации: **при первой же ошибке задача отменяется и больше не повторяется.** Для регламентных задач, где ошибка единична и повтор безопасен, ставьте `cancelOnError: false` — тогда ошибка игнорируется и выполнение продолжается по расписанию.

```cypher
CALL apoc.periodic.repeat(
  "tolerant-job",
  "MATCH (n) SET n.touchedAt = datetime()",
  3600,
  {cancelOnError: false}
);
```

Остановка:

```cypher
CALL apoc.periodic.cancel('touch-nodes');
```

> **Ограничение кластера.** `apoc.periodic.repeat` не рассчитана на кластерную среду и может вести себя непредсказуемо. Задача продолжает выполняться против той базы, в которой была запущена, то есть фактически только на лидере; при переключении лидера задача завершается с ошибкой. Планирование задач на несколько инстансов нужно вести внешним планировщиком (cron, systemd timer), а не полагаться на `apoc.periodic.repeat`.

Планировщик работает на отдельном пуле потоков, размер которого по умолчанию равен `CPU / 4`. При большом числе зарегистрированных задач пул становится узким местом — увеличивайте `apoc.jobs.scheduled.num_threads`.

### Триггеры

Триггеры регистрируют Cypher-запрос, вызываемый при изменении данных. Пакет `apoc.trigger` **выключен по умолчанию** и состоит из семи процедур (ещё пять — `add`, `remove`, `removeAll`, `pause`, `resume` — помечены как удалённые в Cypher 25 и оставлены для совместимости с Cypher 5).

```properties
# apoc.conf
apoc.trigger.enabled=true
apoc.trigger.refresh=60000
```

```cypher
// Установка выполняется в СИСТЕМНОЙ базе — в cypher-shell префикс :use system
:use system
CALL apoc.trigger.install(
  'neo4j',                                       // имя базы
  'setLastUpdate',                               // имя триггера
  'UNWIND keys($assignedNodeProperties) AS k
   UNWIND $assignedNodeProperties[k] AS map
   WITH map.node AS node, collect(map.key) AS propList
   SET node.time = date(), node.lasts = propList',
  {phase: 'afterAsync'}                          // фаза
);
```

Полный набор процедур:

| Процедура | Назначение |
| :--- | :--- |
| `apoc.trigger.install(databaseName, name, statement, selector, config)` | Зарегистрировать триггер |
| `apoc.trigger.show(databaseName)` | Показать триггеры базы |
| `apoc.trigger.list()` | Триггеры текущей сессионной базы (актуальное состояние) |
| `apoc.trigger.stop(databaseName, name)` | Приостановить |
| `apoc.trigger.start(databaseName, name)` | Возобновить |
| `apoc.trigger.drop(databaseName, name)` | Удалить |
| `apoc.trigger.dropAll(databaseName)` | Удалить все |

Три особенности, критичные для эксплуатации:

1. **Системная база.** `install`, `drop`, `dropAll`, `stop`, `start` выполняются только в сессии к базе `system` (`:use system` в cypher-shell и Browser, `USE system` в Fabric, отдельная сессия в драйверах). Процедуры — Admin Only.
2. **Слабая согласованность.** Установка, изменение и удаление триггера применяются не мгновенно, а с задержкой `apoc.trigger.refresh` (по умолчанию 60 с). `show` может вернуть ещё не применившиеся изменения; для достоверной картины используйте `apoc.trigger.list()` против сессионной базы.
3. **Сверка, а не консенсус.** Документация определяет `apoc.trigger.refresh` как интервал, по истечении которого запускается проверка репликации по всем узлам кластера. То есть триггеры расходятся между узлами периодически, а не через консенсус: после изменения одного узла остальные подхватывают его с задержкой.

Фазы срабатывания:

| Фаза | Когда | Рекомендация |
| :--- | :--- | :--- |
| `before` | До коммита | Значение по умолчанию |
| `rollback` | Сразу после отката | |
| `after` | После коммита | Может блокировать транзакции |
| `afterAsync` | После коммита, в отдельной транзакции и потоке | **Предпочтительная** для тяжёлых операций |

В Neo4j 5 невозможно изменить сущность, созданную в фазе `after` — транзакция получит исключение вида `can't acquire ExclusiveLock…`. В таких случаях выбирайте другую фазу или выполняйте только чтение.

Параметры, доступные в теле триггера:

| Параметр | Содержимое |
| :--- | :--- |
| `createdNodes`, `createdRelationships` | Созданные сущности |
| `deletedNodes`, `deletedRelationships` | Удалённые сущности |
| `assignedLabels`, `removedLabels` | Карта: метка → список узлов |
| `assignedNodeProperties`, `removedNodeProperties` | Карта: ключ → список `{key, old, new, node}` |
| `assignedRelationshipProperties`, `removedRelationshipProperties` | Аналогично для связей |
| `transactionId` | Идентификатор транзакции; работает только в фазах `after` и `afterAsync`, иначе `-1` |
| `commitTime` | Время коммита в миллисекундах |
| `metaData` | Метаданные транзакции, заданные клиентом |

Для удалённых сущностей свойства нельзя получить через `properties()` — они представлены виртуальными узлами. Используйте `apoc.any.properties(deletedNode)`.

Защита от рекурсии в триггере на `SET` обязательна: если триггер пишет в свойство, на которое сам же реагирует, запрос зациклится. Условие вида `AND NOT 'lasts' IN propList` в теле триггера — штатный способ этого избежать.

### Экспорт графа

```cypher
CALL apoc.export.cypher.all('graph.cypher', {
  format: 'cypher-shell',
  useOptimizations: {type: 'UNWIND_BATCH', unwindBatchSize: 100}
})
YIELD file, nodes, relationships, properties, time, batches
RETURN file, nodes, relationships, properties, time, batches;
```

| Параметр | По умолчанию | Значения |
| :--- | :--- | :--- |
| `format` | `cypher-shell` | `cypher-shell`, `neo4j-shell`, `plain` |
| `cypherFormat` | `create` | `create`, `updateAll`, `addStructure`, `updateStructure` |
| `useOptimizations.type` | `UNWIND_BATCH` | `NONE`, `UNWIND_BATCH`, `UNWIND_BATCH_PARAMS` |
| `useOptimizations.unwindBatchSize` | `20` | Размер батча `UNWIND` |
| `batchSize` | `20000` | Размер транзакции экспорта |
| `awaitForIndexes` | `300` | Таймаут `db.awaitIndexes`, с |
| `ifNotExists` | `false` | Добавлять `IF NOT EXISTS` к ограничениям и индексам |

Два эксплуатационных нюанса:

- `apoc.export.cypher.*` **не поддерживается parallel runtime** — процедура не считается безопасной для многопоточного выполнения.
- Путь к файлу разрешается **относительно каталога `server.directories.import`**, а не от произвольного абсолютного пути. Абсолютный путь завершится ошибкой `FileNotFoundException`.

Если файловая система недоступна, экспортируйте потоком — передайте `null` вместо имени файла и `stream: true`:

```cypher
CALL apoc.export.cypher.all(null, {stream: true, streamStatements: true, format: 'cypher-shell'})
YIELD nodes, relationships, cypherStatements
RETURN nodes, relationships, cypherStatements;
```

Для полного физического бэкапа используйте `neo4j-admin database backup` — процедуры экспорта не заменяют его и не включают состояние схемы в полном объёме (см. [Бэкап и восстановление](./backup_and_restore.md)).

### Графовые алгоритмы

```cypher
// Кратчайший путь по весу — синтаксис «тип+направление»
MATCH (start:Station {name: 'A'}), (end:Station {name: 'Z'})
CALL apoc.algo.dijkstra(start, end, 'CONNECTED_TO>', 'distance')
YIELD path, weight
RETURN [n IN nodes(path) | n.name] AS route, weight;
```

Третий аргумент использует синтаксис APOC «relationship type + направление»: `TRAIN>` — только исходящие связи, `<TRAIN` — только входящие, `TRAIN` — оба. Это важно: обход в обоих направлениях на двусторонних графах резко увеличивает число посещённых подграфов.

Дополнительные аргументы: `defaultWeight` (по умолчанию `NaN`) — вес для связей без заданного веса, `numberOfWantedPaths` (по умолчанию `1`).

Геокодирование через внешний сервис:

```cypher
CALL apoc.spatial.geocode('Union House, London')
YIELD latitude, longitude, description
RETURN latitude, longitude, description;
```

Провайдер задаётся через `apoc.spatial.geocode.provider` (`osm` по умолчанию). Обращения идут во внешнюю сеть — для изолированного контура вызывать нельзя, а таймауты берутся из `apoc.http.timeout.connect` и `apoc.http.timeout.read`.

Для серьёзной аналитики предпочтительнее GDS: встроенные `apoc.algo.*` — это отдельные реализации, не оптимизированные под проекции в памяти (см. [Graph Data Science](./graph_data_science.md)).

## Карта пакетов и статус процедур

| Категория | Примеры | Назначение |
| :--- | :--- | :--- |
| **Import** | `apoc.load.csv`, `apoc.load.json`, `apoc.import.json` | Массовая загрузка данных |
| **Export** | `apoc.export.cypher.*`, `apoc.export.json.*`, `apoc.export.csv.*` | Дампы, перенос между инстансами |
| **Refactor** | `apoc.refactor.mergeNodes`, `apoc.refactor.invert` | Миграция схемы |
| **Periodic** | `apoc.periodic.iterate`, `apoc.periodic.repeat` | Пакетная и регламентная обработка |
| **Trigger** | `apoc.trigger.install`, `apoc.trigger.dropAll` | Реакция на изменения данных |
| **Graph Algorithms** | `apoc.algo.dijkstra`, `apoc.algo.pageRank` | Графовые алгоритмы |
| **Path** | `apoc.path.expandConfig`, `apoc.path.subgraphAll` | Обход и подграфы |
| **Spatial** | `apoc.spatial.geocode` | Геопространственные запросы |
| **Meta** | `apoc.meta.stats`, `apoc.meta.data` | Метаданные схемы и статистика |
| **Util** | `apoc.util.validate`, `apoc.util.sleep` | Валидация и вспомогательные операции |
| **Create** | `apoc.create.virtualPath`, `apoc.create.vNode` | Виртуальные узлы и связи |

Процедуры и функции, удалённые или устаревшие в Cypher 25, на которые чаще всего натыкается мигрирующий код:

| Процедура / функция | Статус | Замена |
| :--- | :--- | :--- |
| `apoc.periodic.iterate` | Устарела (APOC 2026.04) | `CALL {…} IN CONCURRENT TRANSACTIONS` |
| `apoc.trigger.add` / `remove` / `removeAll` / `pause` / `resume` | Удалены | `apoc.trigger.install` / `drop` / `dropAll` / `stop` / `start` |
| `apoc.nodes.delete` | Устарела | `CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 100 ROWS` |
| `apoc.create.addLabels` / `setProperties` и весь `apoc.create.node/relationship` | Устарели | Динамические метки и свойства Cypher: `SET n:$(labels)`, `SET n[key] = value` |
| `apoc.refactor.rename.*` | Устарели | Динамические метки, типы и свойства |
| `apoc.do.when` / `apoc.do.case` / `apoc.when` | Устарели | Вложенные `WHEN … THEN` запросы Cypher 25 |
| `apoc.coll.*` (sort, sum, max, min, flatten, zip, partition) | Устарели | Функции `coll.*`, `reduce()`, list comprehension |
| `apoc.text.indexOf` / `join` / `replace` | Устарели | `string.indexOf()`, `string.join()`, `string.regexReplace()` |
| `apoc.temporal.format`, `apoc.date.*` | Устарели | Функция `format()`, конструкторы `datetime()`, `date()` |
| `apoc.create.uuids`, `apoc.create.uuid` | Удалены | `randomUUID()` |
| `apoc.convert.toTree` | Удалена | `apoc.paths.toJsonTree` |
| `apoc.load.jsonParams` | Удалена | Заголовки и payload — через параметры `apoc.load.json` либо в APOC Extended |
| `apoc.export.arrow.*`, `apoc.load.arrow.*` | Перенесены в APOC Extended | — |
| `apoc.warmup.run` | Удалена | Прогрев page cache средствами DBMS |

Массовая миграция на Cypher 25 должна начинаться с этого списка, а не с чтения кода: устаревшие вызовы дают предупреждение, удалённые — ошибку «процедура не найдена».

## Управление ресурсами

APOC выполняет фоновую работу в пулах потоков JVM. Их размеры вычисляются от числа CPU и потому ведут себя по-разному на разных хостах — это главный источник «работало на десктопе, не работает на сервере».

| Пул | Настройка | По умолчанию | Что обслуживает |
| :--- | :--- | :--- | :--- |
| Планировщик | `apoc.jobs.scheduled.num_threads` | CPU / 4 | `apoc.periodic.repeat` |
| Фоновые задачи | `apoc.jobs.pool.num_threads` | CPU * 2 | `apoc.periodic.iterate` с `parallel: true` |
| Очередь | `apoc.jobs.queue.size` | `apoc.jobs.pool.num_threads` * 5 | Буфер очереди пула |

Практические замечания:

- При `parallel: false` APOC намеренно использует пул размера 1 — это гарантия отсутствия параллелизма, а не признак недоработки.
- Пул фоновых задач общий для всех баз инстанса: нагрузка от `db1` влияет на `db2`.
- Размер пула задаётся относительно CPU, поэтому при одинаковом объёме работы контейнер с лимитом CPU ведёт себя иначе, чем хост с большим числом ядер. В контейнерах ограничивайте CPU явно, иначе расчёт по числу ядер хоста вводит в заблуждение.
- Загрузка файлов и сетевые вызовы (`apoc.http.timeout.*`) блокируют потоки пула — при недоступном внешнем сервисе пул исчерпывается быстрее, чем ожидается.

## Мониторинг и диагностика

### Проверка загрузки процедур

```cypher
// Сколько процедур APOC доступно
SHOW PROCEDURES YIELD name
WHERE name STARTS WITH 'apoc.'
RETURN count(*) AS apocProcedures;
// → apocProcedures: 0 означает, что JAR не загружен

// Есть ли среди них устаревшие — планирование миграции на Cypher 25
SHOW PROCEDURES YIELD name, option
WHERE name STARTS WITH 'apoc.' AND option IS NOT NULL
RETURN name, option
ORDER BY name;
```

### Состояние файлового доступа

```cypher
// Проверка фактически применённых настроек
CALL apoc.meta.stats();
```

Процедура возвращает `labelCount`, `relTypeCount`, `propertyKeyCount`, `nodeCount`, `relCount`, карты `labels`, `relTypes`, `relTypesCount` и сводную карту `stats`.

Два ограничения на неё накладывает документация:

- **restricted on on-premise instances** — работает только при наличии в `dbms.security.procedures.unrestricted`.
- **не поддерживает parallel runtime** — процедура не считается безопасной для многопоточного выполнения, поэтому вызов из `CALL … IN PARALLEL` недопустим.

### Журналы

| Что искать | Где |
| :--- | :--- |
| Предупреждение о несовместимой версии APOC | `neo4j.log` / `debug.log`, уровень `warn` |
| `Failed to load apoc.util.s3.S3URLConnection` | `debug.log` |
| Ошибки файлового доступа | `debug.log` |
| Разбор загрузок и экспортов | `query.log` (при `dbms.logs.query.enabled=true`) |

Предупреждение о незагруженных классах — норма для APOC Core: JAR дополнительных зависимостей не входит в поставку, поэтому в `debug.log` появляются строки вида `Failed to load apoc.util.s3.S3URLConnection`. Если соответствующая функциональность не используется, предупреждение игнорируется — на файловый импорт и экспорт из локального диска оно не влияет.

### Диагностика по симптомам

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Процедура не найдена | JAR не в `plugins` или несовместимая версия | `SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'apoc.'` → `0`; поиск `warn` в `neo4j.log` | Положить `apoc-<YYYY.MM>-core.jar` с совпадающим годом и месяцем, перезапустить |
| `Import from files not enabled` | Не задан `apoc.import.file.enabled` | `SHOW SETTINGS YIELD name, value WHERE name CONTAINS 'apoc.import'` | `apoc.import.file.enabled=true` в `apoc.conf` |
| `Export to files not enabled` | Не задан `apoc.export.file.enabled` | То же | `apoc.export.file.enabled=true` в `apoc.conf` |
| `FileNotFoundException` при экспорте/импорте | Абсолютный путь вместо относительного | Путь резолвится от `server.directories.import` | Использовать путь относительно каталога импорта либо осознанно выставить `apoc.import.file.use_neo4j_config=false` |
| Настройка в `neo4j.conf` игнорируется | С Neo4j 5 параметры `apoc.*` в `neo4j.conf` не поддерживаются | — | Перенести в `apoc.conf` или в переменные окружения |
| `not authorized` / ошибка доступа к процедуре на внутренних API | Процедура не разблокирована | `SHOW PROCEDURES YIELD name, admin WHERE name = 'apoc.meta.stats'` | Добавить в `dbms.security.procedures.unrestricted` |
| Триггер не срабатывает | Пакет выключен либо не та фаза | `SHOW SETTINGS YIELD name, value WHERE name CONTAINS 'apoc.trigger'`; `apoc.trigger.list()` | `apoc.trigger.enabled=true`; учесть задержку `apoc.trigger.refresh` |
| Триггер выполняется не в той базе | Процедуры триггеров работают только в `system` | — | Открыть сессию к `system` (`:use system`) |
| `apoc.trigger.install` возвращает успех, но эффекта нет | Слабая согласованность, применение не завершено | `apoc.trigger.list()` вместо `show` | Выждать `apoc.trigger.refresh` |
| Две итерации выполняются строго по очереди | `parallel: false` намеренно сериализует пул | — | Ожидаемое поведение; для параллелизма задать `parallel: true` |
| Долгая транзакция, contention | Триггер в фазе `after`/`before` блокирует коммит | Логи транзакций | Перевести триггер в фазу `afterAsync` |
| Не хватает потоков под фоновые задачи | Размер пула вычислен от CPU хоста | — | Поднять `apoc.jobs.pool.num_threads`, ограничить CPU контейнера |
| В `debug.log` ошибки `Failed to load apoc.util.s3...` | Не установлены дополнительные JAR зависимостей | `debug.log` | Игнорировать, если соответствующие источники не используются |

## Валидация в прикладном коде

Для проверок целостности данных и бизнес-правил внутри процедур используется `apoc.util.validate` — она выбрасывает осмысленное исключение с параметрами.

```cypher
WITH true AS predicate
CALL apoc.util.validate(predicate, 'message %d', [42])
RETURN count(*);
```

```text
# → Failed to invoke procedure `apoc.util.validate`: Caused by: java.lang.RuntimeException: message 42
```

При `false` предиката запрос выполняется без ошибок. Формат сообщения аналогичен `String.format`, что позволяет подставлять значения, не собирая строку конкатенацией.

## Обновление и откат

### План обновления

APOC обновляется **вместе** с Neo4j — раздельно эти два компонента обновлять нельзя, требование совпадения года и месяца жёсткое.

```bash
# 1. Зафиксировать текущие версии
sudo systemctl stop neo4j
ls -1 $NEO4J_HOME/plugins/apoc-*.jar
# → apoc-2026.07.1-core.jar

# 2. Обновить Neo4j до целевой версии
sudo apt update && sudo apt install neo4j -y

# 3. Положить JAR, совпадающий с новой версией Neo4j по году и месяцу
sudo mv $NEO4J_HOME/labs/apoc-*-core.jar $NEO4J_HOME/plugins/
sudo rm -f $NEO4J_HOME/plugins/apoc-2026.07.1-core.jar

# 4. Перезапуск и проверка — число процедур зависит от dbms.security.procedures.allowlist
sudo systemctl start neo4j
echo "SHOW PROCEDURES YIELD name WHERE name STARTS WITH 'apoc.' RETURN count(*) AS loaded;" \
  | cypher-shell -u neo4j -p YourStrongPassword2026
# → loaded: ненулевое число. Значение 0 означает, что JAR не загрузился
```

### Проверка перед переходом на новый Cypher

1. Найти устаревшие вызовы: `SHOW PROCEDURES ... WHERE option IS NOT NULL`.
2. Прогнать приложение на тестовой базе с включённым `dbms.logs.query.enabled` и собрать предупреждения из `query.log`.
3. Заменить процедуры по таблице устаревших вызовов.
4. Мигрировать базу на Cypher 25 и повторить прогон.

### Откат

Откат — это возврат **обоих** компонентов к предыдущей паре версий:

```bash
sudo systemctl stop neo4j
sudo cp /opt/backups/plugins/apoc-2026.07.1-core.jar $NEO4J_HOME/plugins/
# и вернуть конфигурацию/версию Neo4j к предыдущей
sudo systemctl start neo4j
```

> Несовместимая пара версий не приводит к отказу запуска: Neo4j поднимется и запишет предупреждение, но процедуры APOC работать не будут. Это самая опасная разновидность отката — ошибка обнаруживается только на рабочей нагрузке. Всегда проверяйте `SHOW PROCEDURES` после перезапуска.

## Удаление APOC

Если библиотека не используется, её следует удалить, а не держать загруженной «на всякий случай».

```bash
sudo systemctl stop neo4j
sudo rm -f $NEO4J_HOME/plugins/apoc-*.jar
# Убрать связанные настройки из apoc.conf
sudo systemctl start neo4j
```

Перед удалением проверьте, что нет зависимостей — вызовы APOC могут идти из прикладного кода, из скриптов миграции и из сохранённых запросов Neo4j Browser. Сохранённые запросы в `SHOW` не выводятся, их нужно проверить отдельно. Живой трафик виден так:

```cypher
// Активные запросы, вызывающие APOC — если такие идут, удалять нельзя
SHOW TRANSACTIONS YIELD currentQueryId, currentQuery
WHERE currentQuery CONTAINS 'apoc.'
RETURN currentQueryId, currentQuery;
```

Для прикладного кода надёжнее статический анализ репозитория:

```bash
# Поиск вызовов APOC в исходниках и скриптах
grep -rn "apoc\." --include="*.cypher" --include="*.java" --include="*.py" --include="*.js" .
```

## См. также
- **[Установка и настройка](./installation_and_setup.md)** — развёртывание Neo4j, порты, начальная конфигурация.
- **[Обслуживание и эксплуатация](./operations.md)** — память, бэкап/восстановение, метрики.
- **[Безопасность](./security.md)** — RBAC, TLS, принцип наименьших привилегий.
- **[Cypher: полное руководство](./cypher_guide.md)** — CRUD, обход графа, агрегации.
- **[Оптимизация запросов](./query_optimization.md)** — EXPLAIN/PROFILE, индексы.
- **[Graph Data Science](./graph_data_science.md)** — плагин GDS и его отличие от `apoc.algo.*`.
- **[Документация APOC](https://neo4j.com/docs/apoc/current/)** — полный справочник процедур.
- **[APOC и Cypher versions](https://neo4j.com/docs/apoc/current/cypher-versions/)** — правила совместимости языка.
- **[Additions, deprecations, removals](https://neo4j.com/docs/apoc/current/deprecations-and-additions/)** — журнал изменений по релизам.
- **[Безопасность](./security.md)** — защита запросов от инъекций при динамическом выполнении Cypher.

