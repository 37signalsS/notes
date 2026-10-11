# Neo4j: Graph Data Science (GDS)

**Актуально для:** Neo4j 2026.09.x / 5.26.x LTS. GDS 2026.09.x.

> **Редакции.** Graph Data Science — функция **Enterprise Edition**. В Community Edition плагин
> отсутствует; графовые алгоритмы там покрываются только через `apoc.algo.*` (см.
> [APOC](./apoc.md#графовые-алгоритмы)).

## Определения

| Термин | Значение |
| :--- | :--- |
| **GDS (Graph Data Science)** | Плагин Enterprise Edition для графовой аналитики и ML-пайплайнов на данных Neo4j. |
| **Projection** | ВизUAL-представление подграфа в памяти, на котором выполняются алгоритмы. |
| **Native projection** | Проекция, построенная напрямую из store-файлов без Cypher; минимальные накладные. |
| **Cypher projection** | Проекция, построенная Cypher-запросом; позволяет фильтровать узлы и связи. |
| **Graph catalog** | Реестр проекций внутри сессии GDS; проекции живут в heap и удаляются в конце сессии. |
| **Node property** | Скалярное значение на узле, доступное алгоритмам как признак или вес. |
| **Relationship property** | Вес или тип связи, используемый взвешенными алгоритмами. |
| **Centrality** | Мера важности узла в графе (PageRank, Betweenness, Degree). |
| **Community detection** | Поиск плотных подграфов (Louvain, Label Propagation, WCC). |
| **Node embedding** | Векторное представление узла для ML-задач (FastRP, Node2Vec). |
| **Link prediction** | Предсказание появления новых связей между парами узлов. |

## Базовые понятия: проекции и память

GDS работает с **проекциями графа в памяти**. Алгоритмы не читают store-файлы напрямую:
сначала подграф копируется в оперативную память, затем запускается вычисление.

**Почему это важно для эксплуатации.** Проекция занимает heap (и частично off-heap) поверх
рабочего набора store-файлов, который сам лежит в page cache. Итого: для GDS-задания нужно
покрыть page cache для store + heap для проекции + запас ОС. Формула из [обслуживания](./operations.md):

```
server.memory.pagecache.size ≥ 1.2 × (объём data + native indexes)
```

Heap для проекции выделяется из той же кучи, что и Cypher-запросы. Если проекция не помещается
в оставшееся место, задание падает с `OutOfMemoryError` — не с ошибкой GDS, а с ошибкой JVM.

### Типы проекций

| Тип | Как строится | Когда использовать |
| :--- | :--- | :--- |
| **Native** | Непосредственно из store-файлов по меткам и типам связей | Большие графы, фильтрация по меткам/свойствам |
| **Cypher** | Результат произвольного Cypher-запроса (`CALL gds.graph.project(...)`) | Сложная фильтрация, подграфы с условиями |
| **Graph projection** | Указание существующего графа как источника | Переиспользование уже построенной проекции |

### Жизненный цикл проекции

1. **Создание:** `gds.graph.project(...)` или `gds.graph.project.cypher(...)`.
2. **Использование:** алгоритмы получают имя проекции и работают с данными в памяти.
3. **Удаление:** `gds.graph.drop(...)` или `gds.graph.dropVertexLabels(...)`. Если проекция не
   удалена явно, она живёт до конца сессии и освобождает память только при закрытии соединения.

Неудалённые проекции — частая причина роста heap под нагрузкой: каждый запуск алгоритма
создаёт новую проекцию, старая остаётся в памяти до таймаута сессии.

## Алгоритмы GDS

| Категория | Алгоритмы | Применение в инфраструктуре |
| :--- | :--- | :--- |
| **Centrality** | PageRank, Betweenness, Degree, Eigenvector | Выявление критических узлов: сервисов, коммутаторов, точек отказа |
| **Community Detection** | Louvain, Label Propagation, Weakly Connected Components | Кластеризация: группы взаимосвязанных сервисов, сегменты сети |
| **Pathfinding** | Shortest Path, Dijkstra, A*, All Pairs Shortest Paths | Анализ маршрутов, blast radius, поиск путей обхода |
| **Similarity** | Node Similarity, Cosine Similarity, Pearson | Дедупликация конфигурации, поиск похожих инцидентов |
| **Node Embeddings** | FastRP, Node2Vec | ML-представления для предиктивной аналитики |
| **Link Prediction** | Common Neighbors, Adamic Adar, Resource Allocation | Прогноз зависимостей, планированиеcapacity |

### Примеры алгоритмов

```cypher
// PageRank: выявление наиболее влиятельных узлов
CALL gds.pageRank.stream('myGraph')
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).name AS name, score
ORDER BY score DESC LIMIT 10;
```

```cypher
// Community Detection (Louvain)
CALL gds.louvain.stream('myGraph')
YIELD nodeId, communityId
RETURN communityId, collect(gds.util.asNode(nodeId).name) AS members
ORDER BY size(members) DESC;
```

```cypher
// Кратчайший путь по весу
MATCH (start:Station {name: 'A'}), (end:Station {name: 'Z'})
CALL gds.shortestPath.dijkstra.stream('myGraph', {
  sourceNode: start,
  targetNode: end
})
YIELD index, sourceNode, targetNode, totalCost, nodeIds, costs, path
RETURN path, totalCost;
```

## Установка GDS

GDS поставляется как плагин JAR. Версия плагина должна совпадать с версией Neo4j по году и месяцу.

### Docker

```bash
docker run -d \
  --name neo4j-gds \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password123 \
  -e NEO4J_PLUGINS='["apoc","graph-data-science"]' \
  neo4j:2026.09.0-enterprise
```

### Ручная установка (production)

```bash
cd $NEO4J_HOME/plugins
wget https://github.com/neo4j/graph-data-science/releases/download/2026.09.0/neo4j-graph-data-science-2026.09.0.jar
sudo systemctl restart neo4j
```

### Проверка установки

```cypher
SHOW PROCEDURES YIELD name
WHERE name STARTS WITH 'gds.'
RETURN count(*) AS gdsProcedures;
```

## Конфигурация

### Параметры конфигурации

| Параметр | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `dbms.security.procedures.allowlist` | все процедуры | Whitelist процедур; рекомендуется сузить до используемого набора |
| `dbms.security.procedures.unrestricted` | пусто | Процедуры GDS на внутренних API; требуют явного разрешения |

### Размещение плагина

Плагины лежат в `/var/lib/neo4j/plugins`. Права на каталог и JAR-файл должны принадлежать
пользователю `neo4j`:

```bash
ls -ld /var/lib/neo4j/plugins
# → drwxr-x---  neo4j neo4j
```

## Управление памятью

GDS выделяет память для проекций из heap JVM. При больших графах это становится узким местом.

### Правила планирования

1. **Page cache покрывает store-файлы** — формула `1.2 × (data + native indexes)` из
   [operations.md](./operations.md#расчёт-памяти-memory-recommendation).
2. **Heap GDS — это часть оставшейся RAM.** Если Cypher-запросы потребляют 4 ГБ heap, а всего
   heap задан 8 ГБ, GDS остаётся работать с 4 ГБ.
3. **Оставьте запас под ОС** — минимум 1–2 ГБ на выделенном сервере.

### Мониторинг потребления

```cypher
// Активные проекции в текущей сессии
CALL gds.graph.list() YIELD graphName, nodeCount, relationshipCount, memoryUsage
RETURN graphName, nodeCount, relationshipCount, memoryUsage
ORDER BY memoryUsage DESC;
```

```cypher
// Очистка неиспользуемых проекций
CALL gds.graph.drop('myGraph');
```

### Квотирование

GDS не имеет встроенного лимита heap. Ограничение задаётся глобально через
`dbms.memory.transaction.total.max` — при превышении прерывается только текущая транзакция,
база остаётся здоровой.

```conf
dbms.memory.transaction.total.max=2G
```

## Эксплуатация в кластере

> **Ограничение:** библиотека GDS не поддерживает отказоустойчивость. GDS следует разворачивать
> только на серверах, настроенных под аналитику. В варианте с одним writer'ом остальные серверы
> умеют только читать, а записывать результаты GDS обратно может лишь writer-сервер.

### Практические правила

- **GDS на выделенных analytics-серверах.** Не запускайте GDS на тех же узлах, что несут
  транзакционную нагрузку: проекции конкурируют за heap и page cache с обычными Cypher-запросами.
- **Чтение через secondary.** Запускайте GDS-задания на secondary-репликах, чтобы не добавлять
  нагрузку на leader.
- **Нет failover для GDS.** Отказ сервера, на котором выполняется алгоритм, прерывает задание;
> его нужно перезапускать вручную или внешним планировщиком.
- **Запись результатов — через writer.** Если алгоритм должен сохранить результат (например,
  PageRank в свойство), выполняйте запись на leader'е базы.

## Пакетная обработка и интеграция с Cypher 25

GDS Stream-процедуры возвращают результаты построчно; для записи их в свойства узлов
используйте `CALL { } IN TRANSACTIONS`:

```cypher
MATCH (n:Person)
CALL gds.pageRank.stream('myGraph', {nodeLabels:['Person']})
YIELD nodeId, score
WITH gds.util.asNode(nodeId) AS node, score
CALL {
  WITH node, score
  SET node.pagerank = score
} IN TRANSACTIONS OF 1000 ROWS
RETURN count(*) AS updated;
```

> **Замечание:** `apoc.periodic.iterate` объявлен устаревшим в Neo4j 2026.04 в пользу
> `CALL { } IN TRANSACTIONS`. Для GDS-заданий это стандартный подход.

## Устранение неполадок

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **OOM при запуске алгоритма** | `OutOfMemoryError` в логе | Проекция не помещается в heap | Увеличить heap или уменьшить проекцию (фильтры, типы узлов) |
| **Проекция не удаляется** | Потребление heap растёт между запусками | `gds.graph.drop()` не вызван | Удалять проекцию явно; мониторить через `gds.graph.list()` |
| **GDS не установлен** | `ProcedureNotFound` | JAR отсутствует или несовместимая версия | Проверить версию плагина, логи запуска |
| **Медленный запуск алгоритма** | Высокое время построения проекции | Native projection с большим графом | Использовать Cypher projection с фильтрацией; проверить page cache |
| **Запись результатов не видена** | PageRank рассчитан, но свойства нет | Запись на secondary или без коммита | Выполнять запись на writer; проверять `writer` в `SHOW DATABASES` |
| **Checkpoint не успевает** | Директория `data/transactions` растёт | GDS-задание генерирует много изменений | Увеличить `db.checkpoint.iops.limit`; см. [operations.md](./operations.md) |

## Лучшие практики

- **Устанавливайте версию GDS, совпадающую с версией Neo4j** по году и месяцу. Patch-версии
  могут отличаться, но мажорный минорный должен совпадать.
- **Создавайте проекции с фильтрацией.** Загружать в память весь граф, если нужен только
  подграф — wasteful и риск OOM.
- **Удаляйте проекции явно.** `gds.graph.drop(...)` после завершения работы; не полагайтесь на
  автоматическую очистку при закрытии сессии.
- **Выделяйте серверы под аналитику.** GDS конкурирует за heap и page cache с транзакционной
  нагрузкой. Разделение на analytics- и transactional-слой — стандартный подход.
- **Запускайте на secondary.** Задания чтения на secondary не влияют на latency leader'а.
- **Мониторьте heap через `dbms.listPools()`.** Рост `currentQueryAllocatedBytes` под GDS — сигнал
  увеличить heap или уменьшить проекцию.
- **Не используйте GDS для `apoc.algo.*`-задач.** Для простых алгоритмов (Dijkstra, PageRank)
  на небольших графах APOC-процедуры работают без предварительного построения проекции.
- **Фиксируйте версию GDS в конфигурации управления.** Как и версию Neo4j, версию плагина
  следует хранить в репозитории.

## См. также

- **[Обзор Neo4j](./overview.md)** — редакции и лицензии, версии и поддержка, модель данных.
- **[Архитектура и хранение](./architecture.md)** — Index-free adjacency, store files, page cache.
- **[Установка и настройка](./installation_and_setup.md)** — Ubuntu APT, Docker, начальная конфигурация.
- **[Обслуживание и эксплуатация](./operations.md)** — память, checkpoint, WAL, диагностика, метрики.
- **[APOC: библиотека расширений](./apoc.md)** — `apoc.algo.*`, пакетная обработка, экспорт.
- **[Оптимизация запросов](./query_optimization.md)** — EXPLAIN/PROFILE, индексы.
- **[Кластеризация и HA](./clustering.md)** — primary/secondary, топология, маршрутизация.
- **[Безопасность](./security.md)** — RBAC, allowlist/unrestricted для процедур.
- **[Драйверы](./drivers.md)** — выполнение GDS-заданий из приложений.
- **[Нагрузочное тестирование](./performance_testing.md)** — влияние проекций на heap и page cache под нагрузкой.
- **[Обновление версии и миграция](./upgrade_and_migration.md)** — совместимость версий плагина при обновлении сервера.

