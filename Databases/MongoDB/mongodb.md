# Обзор MongoDB

**Актуально для:** MongoDB 8.0.x

## Определения

**MongoDB** — ведущая NoSQL СУБД, использующая документо-ориентированную модель данных. В отличие от реляционных БД, MongoDB хранит данные в гибких структурах, подобных JSON, что позволяет изменять схему без простоя (Schema-less подход).

*   **Тип:** Document Store (Документное хранилище).
*   **Теорема CAP:** Классифицируется как **CP** (Consistency/Partition Tolerance). Обеспечивает строгую согласованность, но при разделении сети (Partition) может пожертвовать доступностью (Availability) для записи. При использовании `readPreference: secondary` может работать в режиме **AP**, обеспечивая Eventual Consistency.
*   **Версия 8.0+ (2026):** Актуальная ветка, ориентированная на производительность. Основные инновации 8.0: Block Processing для временных рядов (агрегации работают до 40 раз быстрее), ускоренный Live Resharding (до 50x), Queryable Encryption с поддержкой range-запросов, оптимизированный Oplog Buffer на Secondary. Полное удаление устаревшей оболочки `mongo` в пользу `mongosh`.

### Ключевые термины

*   **BSON (Binary JSON):** Бинарный протокол сериализации. В отличие от JSON, поддерживает расширенные типы данных (Date, Decimal128, ObjectId, BinData) и оптимизирован для быстрого поиска полей без полной десериализации документа.
*   **Документ:** Основная единица данных (аналог строки в SQL). Максимальный размер — **16 МБ**.
*   **Коллекция:** Группа документов (аналог таблицы). Коллекции не требуют предварительного описания всех полей.
*   **GridFS:** Спецификация для хранения и извлечения файлов, размер которых превышает 16 МБ (разделяет файл на чанки).

---

## Базовые концепции

### Архитектура и хранение

MongoDB использует движок **WiredTiger**, который обеспечивает:
*   **Document-level Concurrency:** Блокировки на уровне документов, а не коллекций.
*   **Snapshot Isolation:** Читатели видят согласованный снимок данных, не блокируя писателей (MVCC).
*   **Журналирование (Journaling):** Гарантирует устойчивость данных при сбоях системы.
*   **Сжатие:** По умолчанию используется **Snappy** для коллекций и **columnar compression** для time-series коллекций (начиная с 5.2). Columnar compression кодирует значения полей отдельно (delta, RLE, simple-8b), что дает экономию до 90% на временных рядах.

### Жизненный цикл записи (Write Path)
1.  Клиент отправляет запрос с определенным `writeConcern`.
2.  Данные записываются в **WiredTiger Cache**.
3.  Операция фиксируется в **Journal** на диске (для долговечности).
4.  Операция заносится в **Oplog** (для репликации).
5.  Раз в 60 секунд (чекпоинт) данные сбрасываются из кэша в основные файлы данных (`.wt`).

### Жизненный цикл чтения (Read Path)
1.  Запрос поступает на `mongos` (в шардированном кластере) или напрямую на `mongod`.
2.  СУБД проверяет **Working Set** — находятся ли нужные данные и индексы в WiredTiger Cache.
3.  При отсутствии в кэше происходит чтение с диска (page fault).
4.  Для реплицированных данных драйвер применяет `readPreference` и `readConcern`.

---

## Подготовка окружения (Prerequisites)

Для промышленной эксплуатации MongoDB 8.0+ на Linux (Ubuntu/RHEL) критически важны следующие настройки:

1.  **Файловая система:** Строго **XFS**. Использование ext4 допустимо, но XFS лучше справляется с фрагментацией при работе WiredTiger.
2.  **Transparent Huge Pages (THP):** Должны быть **отключены**. THP вызывает непредсказуемые задержки (latency) и повышенное потребление CPU.
    ```bash
    echo never > /sys/kernel/mm/transparent_hugepage/enabled
    echo never > /sys/kernel/mm/transparent_hugepage/defrag
    ```
3.  **Лимиты системы (ulimits):**
    *   `fsize` (размер файла): unlimited
    *   `nofile` (открытые дескрипторы): 64,000+
    *   `nproc` (количество процессов): 64,000+
4.  **Swap:** Рекомендуется минимальный swap (`vm.swappiness = 1`), чтобы избежать вытеснения WiredTiger Cache на диск.
5.  **Инструкции CPU:** Требуется поддержка **AVX** (Advanced Vector Extensions).
6.  **Сеть:** Порты 27017 (mongod/mongos) и 27019 (configsvr) должны быть доступны только из доверенного сегмента. Рекомендуется использование VLAN/VPC с firewall.

---

## Практические сценарии

### 1. Установка и настройка (Ubuntu/RHEL)

**Шаг 1: Добавление репозитория MongoDB**
```bash
# Ubuntu
wget -qO - https://www.mongodb.org/static/pgp/server-8.0.asc | sudo apt-key add -
echo "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu $(lsb_release -cs)/mongodb-org/8.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
sudo apt update && sudo apt install -y mongodb-org
```

**Шаг 2: Создание директорий и запуск**
```bash
sudo mkdir -p /var/lib/mongodb /var/log/mongodb
sudo chown -R mongodb:mongodb /var/lib/mongodb /var/log/mongodb
sudo systemctl enable --now mongod
```

**Шаг 3: Валидация установки**
```bash
mongosh --eval "db.serverStatus().version" # # → "8.0.x"
mongosh --eval "db.hello()" # # → проверка роли узла (в standalone: { isWritablePrimary: true })
```

### 2. Работа с mongosh (Базовые операции)
Подключение и проверка статуса:
```javascript
// Подключение к локальному экземпляру
// mongosh

// Проверка версии и статуса БД
db.serverStatus().version // # → "8.0.x"
db.hello() // # → проверка роли узла в Replica Set
```

### 3. CRUD операции
Создание и поиск данных:
```javascript
// Вставка документа
db.users.insertOne({
  name: "Ivan",
  role: "DevOps",
  tags: ["linux", "mongodb"],
  createdAt: new Date()
})

// Поиск с фильтрацией
db.users.find({ tags: "linux" }).pretty()

// Обновление (добавление поля)
db.users.updateOne(
  { name: "Ivan" },
  { $set: { status: "active" } }
)
```

### 4. Базовая агрегация
Подсчет пользователей по ролям:
```javascript
db.users.aggregate([
  { $match: { status: "active" } },
  { $group: { _id: "$role", count: { $sum: 1 } } }
])
```

### 5. Валидация результатов

После выполнения операций используйте стандартные команды для проверки:
```bash
# Проверка статуса кластера (Replica Set)
mongosh --eval "rs.status()"

# Проверка состояния хранилища
mongosh --eval "db.serverStatus().wiredTiger.cache"
# # → проверка hit ratio, usage bytes

# Проверка индексов
mongosh --eval "db.users.getIndexes()"
```

---

## Ограничения и особенности

*   **Размер документа (16MB):** Если данные растут бесконтрольно (например, массив логов внутри документа), необходимо переходить на модель ссылок или использовать GridFS.
*   **Глубина вложенности:** Максимум 100 уровней для BSON-документов.
*   **Индексы:** Максимум 64 индекса на одну коллекцию.
*   **Шардирование:** В версии 8.0+ шардирование по времени (`timeField`) для Time-series коллекций не рекомендуется (создает "горячие" шарды). Рекомендуется шардирование по `metaField`.
*   **Working Set:** Данные, к которым приложение обращается чаще всего, должны помещаться в WiredTiger Cache (50% RAM по умолчанию). Иначе происходит Cache Eviction и рост latency.

---

## Лучшие практики (SRE)

1.  **Фиксируйте версии пакетов:** Используйте `apt-mark hold mongodb-org` (Ubuntu) или `yum versionlock mongodb-org` (RHEL), чтобы избежать случайных обновлений.
2.  **Динамический Oplog:** Начиная с v4.4, изменяйте размер Oplog без перезагрузки:
    ```javascript
    db.adminCommand({ replSetResizeOplog: 1, size: 50000 }) // Размер в МБ
    ```
3.  **Мониторинг Oplog Window:** Держите окно не менее 48 часов. Если оно падает до 1-2 часов — это критический риск потери данных.
4.  **Разделение прав:** Используйте `keyFile` только для внутренней связи, а для администрирования — выделенных пользователей с RBAC.
5.  **Версионность FCV:** После Rolling Upgrade установите Feature Compatibility Version:
    ```javascript
    db.adminCommand({ setFeatureCompatibilityVersion: "8.0" })
    ```
6.  **Снижайте `writeConcern` только при необходимости:** В MongoDB 8.0 значение по умолчанию — `majority`. Снижение до `w:1` увеличивает риск потери данных при отказе Primary до фиксации в Journal.
7.  **Мониторинг Cache Eviction:** Следите за метрикой `wiredTiger.cache.evictions` в `db.serverStatus()`. Рост этого значения при отсутствии пиковых нагрузок указывает на недостаток RAM.

---

## Устранение неполадок

| Проблема | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **mongod не запускается** | Наличие `mongod.lock` после аварии | `journal` в логах | Проверить права на `/var/lib/mongodb` или удалить lock-файл после подтверждения корректности данных. |
| **Высокий CPU Usage** | Отсутствие индексов (COLLSCAN) | `db.collection.explain("executionStats").find(...)` | Создать недостающий индекс. |
| **Connection Timeout** | THP включен или лимит `nofile` | `ulimit -n`, `cat /sys/kernel/mm/transparent_hugepage/enabled` | Отключить THP и установить `ulimit -n 64000`. |
| **WiredTiger Cache Eviction** | RAM < Working Set | `db.serverStatus().wiredTiger.cache` | Увеличить объем RAM или ограничить `cacheSizeGB` в `mongod.conf`. |
| **Replica Lag** | Медленная сеть или диск на Secondary | `rs.printSecondaryReplicationInfo()` | Проверить пропускную способность, увеличить `oplogSize`. |
| **Stale Config** | Ошибка метаданных в шардированном кластере | Логи `mongos` | Обычно исправляется автоматическим retry. |

---

## Навигация по разделам

Для углубленного изучения выберите соответствующую тему:

*   **[Движок WiredTiger](./mongodb-storage-engine.md)** — кэширование, сжатие, чекпоинты.
*   **[Моделирование данных](./mongodb-modeling.md)** — Embedding vs Referencing, валидация схем.
*   **[Индексы](./mongodb-indexes.md)** — ESR правило, типы индексов, профилирование.
*   **[Репликация](./mongodb-replication.md)** — Replica Set, кворум, отказоустойчивость.
*   **[Шардирование](./mongodb-sharding.md)** — масштабирование, распределение данных.
*   **[Решардинг (Live Resharding)](./mongodb-resharding.md)** — изменение ключа без простоя.
*   **[Агрегация](./mongodb-aggregation.md)** — конвейеры обработки данных.
*   **[Time-series коллекции](./mongodb-time-series.md)** — работа с временными рядами в 8.0.
*   **[Change Streams](./mongodb-change-streams.md)** — отслеживание изменений данных в реальном времени.
*   **[Транзакции и согласованность](./mongodb-transactions.md)** — ACID в NoSQL.
*   **[Безопасность](./mongodb-security.md)** — RBAC, TLS, аутентификация.
*   **[Администрирование и обслуживание](./mongodb-administration.md)** — бэкапы, обновление, мониторинг, логи, скриптинг.
*   **[Высокая доступность](./high_availability.md)** — архитектуры HA, диагностика отказов.
*   **[Connection String и URI](./mongodb-connection-strings.md)** — URI, драйвер, пул соединений, connection storm.
*   **[Мониторинг и наблюдаемость](./mongodb-monitoring.md)** — exporter, Prometheus, Grafana, SLO/SLI.
*   **[Capacity Planning](./mongodb-capacity-planning.md)** — working set, IOPS, бенчмаркинг.
*   **[GridFS](./mongodb-gridfs.md)** — хранение файлов > 16 MB.
*   **[Импорт/экспорт и bulk-операции](./mongodb-import-export.md)** — mongoimport/export, bulk writes.
*   **[Troubleshooting](./mongodb-troubleshooting.md)** — decision tree, incident response.
*   **[Бэкап и Disaster Recovery](./mongodb-backup-dr.md)** — PBM, шардированный бэкап, DR runbook.

---

## Дополнительные ресурсы

*   **[Установка MongoDB на Ubuntu](./installation_ubuntu.md)**
*   **[Развертывание через Ansible](../../Ansible/examples/mongodb_setup.md)**
