# Neo4j: APOC — библиотека расширений

**APOC (Awesome Procedures on Cypher)** — стандартная библиотека расширений Neo4j, содержащая 450+ процедур и функций для импорта/экспорта данных, графовых алгоритмов, рефакторинга и интеграций. В Neo4j 2026.x APOC Core поставляется по умолчанию.

## Установка APOC

```bash
# В Docker (встроенный плагин, для разработки)
docker run -d \
  --name neo4j-apoc \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password123 \
  -e NEO4J_PLUGINS='["apoc"]' \
  neo4j:2026.07.0-community

# Для production: ручная установка JAR-файла
cd $NEO4J_HOME/plugins
wget https://github.com/neo4j/apoc/releases/download/2026.07.0/apoc-2026.07.0-core.jar
sudo systemctl restart neo4j
```

**Конфигурация APOC (`neo4j.conf`):**
```conf
dbms.security.procedures.unrestricted=apoc.*
dbms.security.procedures.allowlist=apoc.*
apoc.import.file.enabled=true
apoc.export.file.enabled=true
apoc.trigger.enabled=true
```

## Типичные сценарии APOC

```cypher
// Загрузка JSON из URL
WITH 'https://api.example.com/users' AS url
CALL apoc.load.json(url) YIELD value AS user
MERGE (p:Person {name: user.name})
SET p.email = user.email, p.age = user.age;

// Пакетная обработка (periodic iteration)
CALL apoc.periodic.iterate(
  "MATCH (p:Person) WHERE p.processed IS NULL RETURN p",
  "SET p.processed = true, p.processedAt = datetime()",
  {batchSize: 5000, parallel: true}
)
YIELD batches, total, errorMessages
RETURN batches, total, errorMessages;

// Экспорт графа в Cypher-скрипт
CALL apoc.export.cypher.all('/var/lib/neo4j/export/graph.cypher', {
  format: 'cypher-shell',
  useOptimizations: {type: 'UNWIND_BATCH', unwindBatchSize: 100}
});

// Нахождение кратчайшего пути с весами (Dijkstra)
MATCH (start:Station {name: 'A'}), (end:Station {name: 'Z'})
CALL apoc.algo.dijkstra(start, end, 'CONNECTED_TO', 'distance')
YIELD path, weight
RETURN path, weight;

// Проверка версии APOC
RETURN apoc.version();
```

## Категории APOC

| Категория | Примеры | Назначение |
| :--- | :--- | :--- |
| **Import** | `apoc.load.csv`, `apoc.load.json` | Массовая загрузка данных |
| **Export** | `apoc.export.cypher`, `apoc.export.csv` | Бэкапы, снапшоты |
| **Refactor** | `apoc.refactor.mergeNodes` | Миграция схемы |
| **Periodic** | `apoc.periodic.iterate` | Пакетная обработка |
| **Graph Algorithms** | `apoc.algo.dijkstra`, `apoc.algo.pageRank` | Графовые алгоритмы |
| **Spatial** | `apoc.spatial.geocode` | Геопространственные запросы |
| **Text** | `apoc.text.capitalize`, `apoc.text.urlEncode` | Манипуляции со строками |
| **Temporal** | `apoc.temporal.format`, `apoc.temporal.parseDate` | Работа с датами/временем |

## Частые ошибки

- Забыли добавить `apoc.*` в allowlist в конфиге (процедуры возвращают ошибку безопасности).
- Не включили `apoc.import.file.enabled=true` для чтения CSV/JSON с диска.
- Смешивание версий APOC в кластере (версии должны совпадать на всех узлах).
- Вызов процедур внутри функций, где допустимы только функции.

## См. также
- **[Документация APOC](https://neo4j.com/docs/apoc/current/)** — полный справочник процедур.
- **[Установка и настройка](./installation_and_setup.md)** — развёртывание Neo4j и включение плагинов.
- **[Cypher: полное руководство](./cypher_guide.md)** — CRUD, обход графа, агрегации.
