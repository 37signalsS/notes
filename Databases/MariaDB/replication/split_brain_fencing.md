# Split-brain и fencing при классической репликации MariaDB

**Актуально для:** MariaDB 11.4 LTS / 12.3 LTS

## Определения

*   **Split-brain (расщепление мозга)** — состояние, при котором два узла одновременно считают себя источником и принимают запись. В классической асинхронной репликации возникает при сетевом разделении или ошибке failover.
*   **Fencing (изоляция)** — принудительная блокировка записи на «старом» источнике при промоушене реплики. Гарантирует, что только один узел принимает запись.
*   **`read_only`** — системная переменная, запрещающая запись всем клиентам, кроме тех, у кого есть `SUPER` / `CONNECTION ADMIN` / `READ_ONLY ADMIN`.
*   **`super_read_only`** — системная переменная (MariaDB 10.5.1+), запрещающая запись даже клиентам с `SUPER`. Требует предварительного `read_only = ON`.
*   **`enforce_read_only_servers`** — опция MaxScale `mariadbmon`: монитор сам включает `read_only` на узлах, не являющихся Primary.

## Базовые концепции

### Почему split-brain опасен для классической репликации

В Galera split-brain предотвращается кворумом и сертификацией транзакций. В классической асинхронной репликации **нет встроенной защиты**: если сеть разделит источник и реплику, и реплику промоутят вручную или автоматически, оба узла могут принимать запись. Последствия:

*   **Дивергенция данных**: одинаковые строки изменены по-разному на двух узлах.
*   **Ошибки репликации** при восстановлении связи: `Duplicate entry`, `Can't find record`.
*   **Потеря данных**: при повторном подключении «старого» источника как реплики его транзакции перезаписываются или конфликтуют.

### Стратегии предотвращения split-brain

1.  **`read_only = ON` на всех репликах** — базовая защита от случайной записи. Не защищает от промоушена с записью.
2.  **`super_read_only = ON`** — защита от записи даже для `SUPER`-аккаунтов. Включается при промоушене/демоушене.
3.  **Fencing через прокси (MaxScale)** — `mariadbmon` автоматически управляет `read_only` на узлах; запись маршрутизируется только на текущий Primary.
4.  **Fencing через Orchestrator** — при failover Orchestrator переводит старый мастер в `read_only` и перенастраивает топологию.
5.  **Внешний fencing (STONITH)** — на уровне виртуализации/физической инфраструктуры: выключение «старого» мастера при потере кворума. Характерен для Pacemaker-кластеров.

### Механика read_only и super_read_only

*   `read_only = ON`: блокирует запись для обычных клиентов. Клиенты с `SUPER` (до 11.0) или `CONNECTION ADMIN` / `READ_ONLY ADMIN` (11.0+) могут писать.
*   `super_read_only = ON`: блокирует запись для всех, включая `SUPER`. Требует `read_only = ON` (иначе игнорируется).
*   Репликационный SQL-поток **игнорирует** `read_only` — применяет события от источника даже при `read_only = ON`.

**Важно:** `super_read_only` не может быть включён, если `read_only = OFF`. MariaDB игнорирует `super_read_only` при отсутствии базового `read_only`.

### Fencing при ручном failover

При ручном промоушене реплики (без Orchestrator/MaxScale) fencing выполняется оператором:

1.  На старом источнике: `SET GLOBAL super_read_only = ON;` (или остановка сервера).
2.  На новом источнике: `SET GLOBAL read_only = OFF; SET GLOBAL super_read_only = OFF;`
3.  Перенастройка остальных реплик на новый источник.

**Критично:** если старый источник «оживёт» после сетевого разделения и не был зafenced, он продолжит принимать запись → split-brain.

## Практические сценарии

### Сценарий 1: Базовая защита реплик (read_only + super_read_only)

```ini
# На всех репликах (/etc/mysql/mariadb.conf.d/50-server.cnf)
[mariadb]
read_only = ON
# super_read_only включается только при обслуживании,
# когда даже админ не должен случайно записать данные
# super_read_only = ON
```

```sql
-- Проверка
SHOW VARIABLES LIKE 'read_only';
SHOW VARIABLES LIKE 'super_read_only';
-- → read_only = ON, super_read_only = OFF (или ON при обслуживании)

-- Включение super_read_only (требует read_only = ON)
SET GLOBAL read_only = ON;
SET GLOBAL super_read_only = ON;

-- Выключение (обратный порядок)
SET GLOBAL super_read_only = OFF;
SET GLOBAL read_only = OFF;
```

### Сценарий 2: Fencing при ручном failover

```sql
-- Шаг 1: На СТАРОМ источнике — заблокировать запись (fencing)
SET GLOBAL super_read_only = ON;
-- Проверка: запись должна быть запрещена даже для root

-- Шаг 2: На НОВОМ источнике (бывшая реплика) — разрешить запись
SET GLOBAL super_read_only = OFF;
SET GLOBAL read_only = OFF;

-- Шаг 3: Остановить репликацию на новом источнике
STOP REPLICA;
RESET REPLICA ALL;

-- Шаг 4: Перенастроить остальные реплики на новый источник
-- (на каждой реплике)
STOP REPLICA;
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='new_source_ip',
    SOURCE_USER='repl_user',
    SOURCE_PASSWORD='password',
    SOURCE_USE_GTID=slave_pos;
START REPLICA;
```

### Сценарий 3: Автоматический fencing через MaxScale

```ini
# В конфигурации MaxScale (maxscale.cnf)
[MariaDB-Monitor]
type=monitor
module=mariadbmon
servers=server1,server2,server3
user=mariadbmon
password=***
auto_failover=true
enforce_read_only_servers=true   # монитор сам включает read_only на не-Primary
```

При failover `mariadbmon`:
1.  Включает `read_only` на старом Primary (fencing).
2.  Выключает `read_only` на новом Primary.
3.  Перенастраивает реплики через `CHANGE MASTER TO`.

Подробнее: **[Failover и Switchover (mariadbmon)](../MaxScale/maxscale_failover.md)**.

### Сценарий 4: Обнаружение split-brain после восстановления сети

```sql
-- На обоих узлах: проверьте, были ли записи во время разделения
-- Сравните GTID-позиции
SELECT @@gtid_binlog_pos;

-- На «старом» источнике: есть ли транзакции, которых нет на новом?
-- Если да — данные дивергировали. Требуется ручное разрешение конфликтов
-- или пересинхронизация (re-seeding) с «победившего» узла.

-- Проверка через pt-table-checksum
pt-table-checksum --replicate=percona.checksums h=source_ip,u=monitor_user,p=***
```

### Сценарий 5: Fencing на уровне Pacemaker (STONITH)

Для кластеров под управлением Pacemaker fencing реализуется через STONITH-агенты (выключение узла на гипервизоре/IPMI). Все узлы должны быть одной платформы — fencing-агенты платформозависимы.

```bash
# Пример: настройка STONITH для IPMI (Pacemaker)
sudo pcs stonith create ipmi-fence fence_ipmilan \
    ip=192.168.1.100 username=admin password=*** \
    pcmk_host_list=node1
```

> **Примечание:** STONITH обязателен в production-кластерах Pacemaker. Примеры без fencing — только для тестов.

## Типовые ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Запись на реплику несмотря на `read_only` | Клиент имеет `SUPER` / `CONNECTION ADMIN` | Включите `super_read_only = ON` |
| `super_read_only` не применяется | `read_only = OFF` | Сначала `SET GLOBAL read_only = ON;`, затем `super_read_only = ON` |
| Split-brain после сетевого разделения | Старый мастер не был зafenced | Fencing перед промоушеном; используйте Orchestrator/MaxScale |
| Репликация не применяет события при `read_only` | Ожидаемое поведение | SQL-поток игнорирует `read_only`; проверяйте `Replica_SQL_Running` |
| Дублирование данных после восстановления | Оба узла принимали запись | Разрешение конфликтов вручную или re-seeding с одного узла |

## Best Practices

1.  **`read_only = ON` на всех репликах** — всегда, даже в тестовых средах.
2.  **`super_read_only = ON`** при обслуживании и перед плановым отключением источника.
3.  **Fencing перед промоушеном** — никогда не промоутите реплику, не заблокировав запись на старом источнике.
4.  **Автоматизируйте failover** через Orchestrator или MaxScale — ручной fencing ненадёжен при аварии.
5.  **Мониторьте `read_only`/`super_read_only`** как метрику: неожиданное `OFF` на реплике — сигнал инцидента.
6.  **Тестируйте failover** в staging: проверяйте, что fencing срабатывает и запись блокируется на старом мастере.

## Дополнительная информация

### См. также
- **[Обзор репликации](./overview.md)** — топологии и failover.
- **[Дополнительные параметры безопасности](../security/additional-parameters.md)** — `super_read_only`, детальное описание.
- **[Failover и Switchover (mariadbmon)](../MaxScale/maxscale_failover.md)** — автоматический fencing через MaxScale.
- **[Orchestrator](../../MySQL/orchestrator.md)** — автоматический failover для классической репликации.
- **[Отказоустойчивость MariaDB](../high_availability.md)** — Galera, Orchestrator, MaxScale.
