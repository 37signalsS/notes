# Neo4j: Установка и настройка

## Предварительные требования

- **ОС:** Ubuntu 22.04/24.04 LTS (Debian-based) или Docker 24+
- **Java:** OpenJDK 21 (включён в пакет Neo4j)
- **Память:** минимум 2 ГБ RAM, рекомендуется 8+ ГБ для production
- **Диск:** минимум 10 ГБ свободного места

## Вариант 1: Установка на Ubuntu (APT)

```bash
# Импорт GPG-ключа
curl -fsSL https://debian.neo4j.com/neotechnology.gpg.key | \
  sudo gpg --dearmor -o /usr/share/keyrings/neo4j-archive-keyring.gpg

# Добавление репозитория
echo "deb [signed-by=/usr/share/keyrings/neo4j-archive-keyring.gpg] \
  https://debian.neo4j.com stable latest" | \
  sudo tee /etc/apt/sources.list.d/neo4j.list

# Установка Community Edition
sudo apt update
sudo apt install neo4j -y

# Установка Enterprise Edition (требуется лицензия)
# sudo apt install neo4j-enterprise -y

# Запуск
sudo systemctl enable neo4j
sudo systemctl start neo4j
```

## Вариант 2: Docker (рекомендуется для разработки)

```bash
# Базовый запуск
docker run -d \
  --name neo4j \
  --restart unless-stopped \
  -p 7474:7474 \
  -p 7687:7687 \
  -v neo4j_data:/data \
  -v neo4j_logs:/logs \
  -e NEO4J_AUTH=neo4j/password123 \
  -e NEO4J_PLUGINS='["apoc"]' \
  neo4j:2026.07.0-community
```

**Порты:**
| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| 7474 | HTTP | Neo4j Browser (веб-интерфейс) |
| 7473 | HTTPS | Neo4j Browser (TLS) |
| 7687 | Bolt | Драйверы, cypher-shell |

## Вариант 3: Docker Compose (production-подобная конфигурация)

```yaml
version: '3.8'
services:
  neo4j:
    image: neo4j:2026.07.0-enterprise
    container_name: neo4j-prod
    ports:
      - "7474:7474"
      - "7687:7687"
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    environment:
      NEO4J_AUTH: neo4j/CHANGE_ME_STRONG_PASSWORD
      NEO4J_ACCEPT_LICENSE_AGREEMENT: "yes"
      # JVM heap: максимум 50% от RAM контейнера
      NEO4J_server_memory_heap_initial__size: "2G"
      NEO4J_server_memory_heap_max__size: "4G"
      # Page cache: остаток от RAM
      NEO4J_server_memory_pagecache_size: "4G"
      # Включение APOC
      NEO4J_PLUGINS: '["apoc"]'
      NEO4J_apoc_import_file_enabled: "true"
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 12G
volumes:
  neo4j_data:
  neo4j_logs:
```

## Начальная конфигурация

```bash
# Установка начального пароля (до первого запуска)
sudo neo4j-admin dbms set-initial-password YourStrongPassword2026

# Подключение через cypher-shell
cypher-shell -u neo4j -p YourStrongPassword2026

# Подключение через Bolt
cypher-shell -a bolt://localhost:7687 -u neo4j -p YourStrongPassword2026
```

## Проверка работоспособности

```bash
# Статус сервиса
sudo systemctl status neo4j

# Проверка через HTTP
curl http://localhost:7474
# → {"bolt_routing":"neo4j://localhost:7687","transaction":"http://localhost:7474/db/{databaseName}/tx",...}

# Проверка через cypher-shell
echo "RETURN 1 AS test;" | cypher-shell -u neo4j -p YourStrongPassword2026
# → +------+
#    | test |
#    +------+
#    | 1    |
#    +------+
```

## Управление APOC в Docker

### Установка APOC

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

### Типичные сценарии APOC

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

## См. также
- **[Обзор Neo4j](./overview.md)** — определения и место в экосистеме.
- **[Архитектура и хранение](./architecture.md)** — Index-free adjacency, store files, транзакционный движок.
- **[Cypher: полное руководство](./cypher_guide.md)** — CRUD, обход графа, агрегации.
- **[Драйверы](./drivers.md)** — Python, Java, JavaScript/TypeScript.
- **[Обслуживание и эксплуатация](./operations.md)** — Память, бэкап/восстановление, диагностика.
