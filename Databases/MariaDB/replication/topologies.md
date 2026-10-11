# Топологии репликации MariaDB: каскадная, кольцевая, multi-master

**Актуально для:** MariaDB 11.4 LTS / 12.3 LTS

## Определения

*   **Каскадная репликация (Cascading Replication)** — топология, в которой реплика сама является источником для другой реплики (replica → replica). Промежуточная реплика называется **промежуточным узлом (intermediate source)**.
*   **`log_slave_updates`** — системная переменная (MariaDB 10.x+), включающая запись полученных от источника событий в собственный бинарный лог реплики. Обязательна для каскадной репликации: без неё промежуточная реплика не передаёт события дальше.
*   **Кольцевая репликация (Ring Replication)** — топология, в которой узлы образуют кольцо: каждый узел реплицирует следующему, последний — первому. Поддерживает multi-master запись (с осторожностью).
*   **Multi-master (classic)** — классическая асинхронная репликация с записью на нескольких узлах (в отличие от Galera — без синхронной сертификации и автоматического разрешения конфликтов).
*   **`auto_increment_increment` / `auto_increment_offset`** — системные переменные для генерации уникальных AUTO_INCREMENT-значений на разных мастерах в multi-master/ring топологиях.

## Базовые концепции

### Каскадная репликация (Chain / Tree)

Топология: `Source → Replica1 → Replica2 → Replica3`.

**Зачем:**
*   **Снижение нагрузки на источник**: источник отдаёт binlog только одному промежуточному узлу, а не всем репликам. Полезно при большом числе реплик (десятки).
*   **Географическое распределение**: промежуточный узел в другом ЦОД, реплики за ним — локально.
*   **Изоляция**: реплики для аналитики не нагружают сеть источника.

**Требования:**
*   На промежуточной реплике обязательно `log_slave_updates = ON` (по умолчанию ON в MariaDB 10.x+).
*   Промежуточная реплика должна иметь включённый `log_bin`.
*   GTID-репликация упрощает каскад: позиции отслеживаются автоматически.

**Ограничения:**
*   **Суммарный лаг** складывается из лагов всех звеньев. Replica2 отстаёт от Source на (лаг Replica1 + собственный лаг).
*   **Точка отказа**: если Replica1 падает, Replica2 и Replica3 перестают получать обновления.
*   **Failover сложнее**: при промоушене Replica1 нужно перенастроить всю цепочку ниже.

### Кольцевая репликация (Ring)

Топология: `A → B → C → A` (каждый узел — источник для следующего).

**Особенности:**
*   Поддерживает запись на всех узлах (multi-master), но **без автоматического разрешения конфликтов** (до MariaDB Enterprise Server 12.3 с CDR-триггерами).
*   Требует `auto_increment_increment` / `auto_increment_offset` для уникальности AUTO_INCREMENT.
*   **Опасна**: циклическая репликация может привести к бесконечному распространению событий при неправильной настройке фильтров.
*   MariaDB документирует ring replication как поддерживаемую топологию, но для production multi-master рекомендуется Galera.

### Multi-master (classic, не Galera)

Два и более узла, на которые разрешена запись, связанные асинхронной репликацией.

**Отличия от Galera:**
*   Нет синхронной сертификации — конфликты не обнаруживаются автоматически.
*   RPO > 0 (асинхронность).
*   Требует ручной стратегии разрешения конфликтов или строгого разделения записи по узлам (sharding на уровне приложения).

**Когда оправдан:**
*   Географически распределённая запись с разделением по регионам (каждый регион пишет в свой мастер).
*   Миграция между версиями/движками.
*   **Не оправдан** для типичного HA — используйте Galera или Source-Replica + Orchestrator/MaxScale.

### AUTO_INCREMENT в multi-master

Для уникальности значений на разных мастерах:

```ini
# Узел A
auto_increment_increment = 2
auto_increment_offset = 1   # генерирует 1, 3, 5, 7, ...

# Узел B
auto_increment_increment = 2
auto_increment_offset = 2   # генерирует 2, 4, 6, 8, ...
```

**Правила:**
*   `auto_increment_increment` — интервал между значениями (1..65535).
*   `auto_increment_offset` — стартовая точка (1..65535).
*   Если `auto_increment_offset > auto_increment_increment`, offset игнорируется и сбрасывается в 1.
*   При изменении требуется перезапуск сервера или принудительное закрытие всех соединений.
*   В Galera эти параметры управляются автоматически (`wsrep_auto_increment_control`).

## Практические сценарии

### Сценарий 1: Каскадная репликация (Source → Replica1 → Replica2)

**На Replica1 (промежуточный узел):**
```ini
[mariadb]
server_id = 2
log_bin = /var/log/mysql/mariadb-bin
log_slave_updates = ON   # обязательно: записывает полученные события в свой binlog
read_only = 1
```

```sql
-- Replica1 подключается к Source
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='source_ip',
    SOURCE_USER='repl_user',
    SOURCE_PASSWORD='password',
    SOURCE_USE_GTID=slave_pos;
START REPLICA;
```

**На Replica2:**
```sql
-- Replica2 подключается к Replica1 (не к Source!)
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='replica1_ip',
    SOURCE_USER='repl_user',
    SOURCE_PASSWORD='password',
    SOURCE_USE_GTID=slave_pos;
START REPLICA;
```

**Проверка:**
```sql
-- На Replica1: убедитесь, что log_slave_updates включён
SHOW VARIABLES LIKE 'log_slave_updates';
-- → ON

-- На Replica2: проверьте, что источник — Replica1
SHOW REPLICA STATUS\G
-- Source_Host: replica1_ip
-- Source_Server_Id: 2
```

### Сценарий 2: Кольцевая репликация (2 узла)

```sql
-- На узле A: реплицируемся с B
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='node_b_ip',
    SOURCE_USER='repl_user',
    SOURCE_PASSWORD='password',
    SOURCE_USE_GTID=slave_pos;
START REPLICA;

-- На узле B: реплицируемся с A
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='node_a_ip',
    SOURCE_USER='repl_user',
    SOURCE_PASSWORD='password',
    SOURCE_USE_GTID=slave_pos;
START REPLICA;
```

**Обязательно:** `auto_increment_increment = 2` на обоих узлах с разными `auto_increment_offset`.

**Предупреждение:** кольцевая репликация с записью на обоих узлах — риск конфликтов. Для production multi-master используйте Galera.

### Сценарий 3: Добавление узла в multi-master (без полного перезапуска)

При `auto_increment_increment = 2` (два мастера) добавить третий мастер без перезапуска всех:

```sql
-- На узле A: переключаемся на increment=4 (освобождаём нечётные позиции 3, 7, 11...)
SET GLOBAL auto_increment_increment = 4;
-- A теперь генерирует 1, 5, 9, 13, ...

-- На новом узле C:
SET GLOBAL auto_increment_increment = 4;
SET GLOBAL auto_increment_offset = 3;
-- C генерирует 3, 7, 11, 15, ...
```

> **Примечание:** изменение `auto_increment_increment` требует перезапуска или закрытия всех соединений, чтобы существующие сессии подхватили новое значение.

### Сценарий 4: Диагностика каскадной цепочки

```sql
-- На каждом узле проверьте позицию GTID
SELECT @@gtid_binlog_pos;   -- что узел записал в свой binlog
SELECT @@gtid_slave_pos;    -- что узел применил от источника

-- На Replica2: Source_Server_Id должен указывать на Replica1, а не на Source
SHOW REPLICA STATUS\G
```

## Типовые ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Replica2 не получает данные | `log_slave_updates = OFF` на Replica1 | Включите `log_slave_updates = ON` на промежуточном узле, перезапустите репликацию |
| Дублирование AUTO_INCREMENT в ring | Не настроены `auto_increment_increment`/`offset` | Настройте на каждом мастере: `increment = N`, уникальный `offset` |
| Бесконечный цикл событий в ring | Событие реплицируется по кольцу повторно | Используйте фильтры (`replicate-ignore-db`) или GTID для отсечения уже применённых событий |
| Суммарный лаг в каскаде растёт | Лаг каждого звена складывается | Мониторьте лаг на каждом звене отдельно; включите параллельную репликацию |
| `auto_increment_offset` игнорируется | `offset > increment` | Убедитесь, что `auto_increment_offset <= auto_increment_increment` |

## Best Practices

1.  **Каскад вместо fan-out** при числе реплик > 5–10: снижает нагрузку на сеть источника.
2.  **GTID обязателен** для каскадной и кольцевой топологий — упрощает отслеживание позиций.
3.  **Не используйте кольцевую multi-master запись** в production без CDR-триггеров (MariaDB Enterprise 12.3+) или строгого разделения записи.
4.  **Мониторьте лаг на каждом звене** каскада, а не только на последней реплике.
5.  **`log_slave_updates = ON`** — проверяйте на всех промежуточных узлах; это самая частая ошибка каскадной топологии.

## Дополнительная информация

### См. также
- **[Обзор репликации](./overview.md)** — базовые топологии Source-Replica.
- **[Фильтрация](./filtering.md)** — фильтры для кольцевой топологии.
- **[Отказоустойчивость MariaDB](../high_availability.md)** — Galera, Orchestrator, MaxScale.
- **[Документация MariaDB: Replication Overview](https://mariadb.com/docs/server/ha-and-performance/standard-replication/replication-overview)** — ring replication, multi-master.
