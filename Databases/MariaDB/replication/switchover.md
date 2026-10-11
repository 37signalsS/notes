# Ручной Switchover в MariaDB (плановое переключение)

**Актуально для:** MariaDB 11.4 LTS / 12.3 LTS

## Определения

*   **Switchover (плановое переключение)** — контролируемое переключение роли источника на реплику с минимальным простоем. Выполняется при обслуживании (обновление, миграция, обслуживание оборудования) с предварительной синхронизацией.
*   **Failover (аварийное переключение)** — переключение на реплику при недоступности текущего источника. Цель — восстановить запись как можно быстрее, ценой возможной потери данных (RPO > 0 при асинхронной репликации).
*   **Promotion (промоушен)** — повышение реплики до источника (снятие `read_only`, остановка репликации).
*   **Demotion (демоушен)** — понижение источника до реплики (включение `read_only`, перенастройка на новый источник).

## Базовые концепции

### Switchover vs Failover

| Характеристика | Switchover | Failover |
| :--- | :--- | :--- |
| **Триггер** | Плановое обслуживание | Авария источника |
| **Потеря данных** | 0 (ожидаем синхронизацию) | Возможна (асинхронность) |
| **Простой** | Секунды (контролируемый) | Минимизируется (аварийный) |
| **Подготовка** | Полная (синхронизация, проверка) | Минимальная |
| **Кто выполняет** | Оператор / автоматизация | Orchestrator / MaxScale / оператор |

### Когда нужен ручной switchover

*   Обновление MariaDB (rolling upgrade).
*   Обслуживание оборудования / ОС.
*   Миграция на другой хост.
*   Балансировка нагрузки (перенос записи на другой узел).
*   **Автоматический switchover** (через MaxScale `mariadbmon` или Orchestrator) предпочтительнее — см. **[Failover и Switchover (mariadbmon)](../MaxScale/maxscale_failover.md)** и **[Orchestrator](../../MySQL/orchestrator.md)**.

### Предварительные требования

*   GTID-репликация (упрощает переключение позиций).
*   Реплика-кандидат с минимальным лагом (`Seconds_Behind_Source = 0` или совпадение GTID-позиций).
*   `read_only = ON` на всех репликах.
*   Приложение готово к переподключению (или прокси — MaxScale/HAProxy).
*   Полусинхронная репликация (опционально) — снижает риск потери данных.

## Практические сценарии

### Сценарий 1: Полный ручной switchover (GTID)

**Шаг 0: Выбор кандидата**
```sql
-- На всех репликах: проверьте лаг
SHOW REPLICA STATUS\G
-- Seconds_Behind_Source: 0
-- Replica_IO_Running: Yes
-- Replica_SQL_Running: Yes

-- Сравните GTID-позиции
SELECT @@gtid_binlog_pos;   -- на источнике
SELECT @@gtid_slave_pos;    -- на реплике-кандидате
-- Должны совпадать (или реплика догоняет)
```

**Шаг 1: Остановка записи на старом источнике**
```sql
-- На старом источнике: заблокировать запись (fencing)
SET GLOBAL super_read_only = ON;
-- Проверка: запись запрещена даже для SUPER

-- Дождитесь, пока реплика-кандидат догонит
-- На кандидате:
SELECT @@gtid_slave_pos;
-- Должно совпасть с @@gtid_binlog_pos старого источника
```

**Шаг 2: Промоушен реплики-кандидата**
```sql
-- На новом источнике (бывшая реплика)
STOP REPLICA;
RESET REPLICA ALL;
SET GLOBAL read_only = OFF;
SET GLOBAL super_read_only = OFF;

-- Проверка
SHOW VARIABLES LIKE 'read_only';
-- → OFF
```

**Шаг 3: Перенастройка остальных реплик**
```sql
-- На каждой другой реплике
STOP REPLICA;
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='new_source_ip',
    SOURCE_USER='repl_user',
    SOURCE_PASSWORD='password',
    SOURCE_USE_GTID=slave_pos;
START REPLICA;

-- Проверка
SHOW REPLICA STATUS\G
-- Source_Host: new_source_ip
-- Replica_IO_Running: Yes
-- Replica_SQL_Running: Yes
```

**Шаг 4: Переключение приложения**
*   Обновите connection string / DNS / VIP на новый источник.
*   Или перезапустите прокси (MaxScale/HAProxy) с новой конфигурацией.

**Шаг 5: Старый источник — в реплики (опционально)**
```sql
-- На старом источнике (теперь реплика)
STOP REPLICA;
RESET REPLICA ALL;
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='new_source_ip',
    SOURCE_USER='repl_user',
    SOURCE_PASSWORD='password',
    SOURCE_USE_GTID=slave_pos;
START REPLICA;
SET GLOBAL read_only = ON;
```

### Сценарий 2: Switchover с полусинхронной репликацией

При полусинхронной репликации (`rpl_semi_sync`) switchover безопаснее:

```sql
-- На старом источнике: убедитесь, что полусинхронность активна
SHOW STATUS LIKE 'Rpl_semi_sync_master_status';
-- → Active: ON

-- После промоушена на новом источнике: включите полусинхронность
INSTALL SONAME 'semisync_master';
SET GLOBAL rpl_semi_sync_master_enabled = ON;
SET GLOBAL rpl_semi_sync_master_wait_point = 'AFTER_SYNC';

-- На репликах: включите semisync slave
INSTALL SONAME 'semisync_slave';
SET GLOBAL rpl_semi_sync_slave_enabled = ON;
STOP REPLICA IO_THREAD;
START REPLICA IO_THREAD;
```

### Сценарий 3: Автоматический switchover через MaxScale

```bash
# MaxScale 25.10+: имя монитора вместо имени модуля
maxctrl call command MariaDB-Monitor switchover

# С указанием нового Primary и старого
maxctrl call command MariaDB-Monitor switchover server2 server1

# Расширенный синтаксис (MaxScale 24.08+)
maxctrl call command mariadbmon switchover \
    monitor=MariaDB-Monitor \
    new_primary=server2 \
    old_primary_maint=1
```

Подробнее: **[Failover и Switchover (mariadbmon)](../MaxScale/maxscale_failover.md)**.

### Сценарий 4: Проверка после switchover

```sql
-- На новом источнике
SHOW VARIABLES LIKE 'read_only';
-- → OFF

-- Запись работает
CREATE TABLE switchover_test (id INT PRIMARY KEY);
INSERT INTO switchover_test VALUES (1);
DROP TABLE switchover_test;

-- На репликах: данные появились?
SHOW REPLICA STATUS\G
-- Replica_IO_Running: Yes
-- Replica_SQL_Running: Yes
-- Seconds_Behind_Source: 0

-- На старом источнике (теперь реплика): read_only = ON
SHOW VARIABLES LIKE 'read_only';
-- → ON
```

### Сценарий 5: Откат switchover (rollback)

Если после switchover обнаружена проблема:

```sql
-- На новом источнике: заблокировать запись
SET GLOBAL super_read_only = ON;

-- На старом источнике: вернуть роль
SET GLOBAL read_only = OFF;
SET GLOBAL super_read_only = OFF;

-- Перенастроить реплики обратно на старый источник
-- (повторите Шаг 3 Сценария 1 с SOURCE_HOST='old_source_ip')
```

## Типовые ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Потеря данных после switchover | Реплика не догнала перед промоушеном | Дождитесь `Seconds_Behind_Source = 0` / совпадения GTID перед Шагом 2 |
| Split-brain после switchover | Старый источник не зafenced | `SET GLOBAL super_read_only = ON;` перед промоушеном |
| Реплики не переключились | `CHANGE REPLICATION SOURCE TO` не выполнен | Выполните Шаг 3 на всех репликах |
| Приложение пишет на старый источник | Connection string не обновлён | Обновите DNS/VIP/прокси; проверьте `read_only` на старом источнике |
| `read_only` не снимается на новом источнике | `super_read_only = ON` | Сначала `SET GLOBAL super_read_only = OFF;`, затем `read_only = OFF` |

## Best Practices

1.  **Всегда fencing** — `super_read_only = ON` на старом источнике перед промоушеном.
2.  **Дождитесь синхронизации** — `Seconds_Behind_Source = 0` или совпадение GTID перед промоушеном.
3.  **GTID обязателен** — упрощает переключение позиций и восстановление.
4.  **Автоматизируйте** — используйте MaxScale `mariadbmon` или Orchestrator вместо ручного switchover.
5.  **Тестируйте в staging** — отработайте процедуру switchover регулярно.
6.  **Полусинхронная репликация** — снижает риск потери данных при switchover.
7.  **Плановый switchover, а не остановка** — перед обслуживанием источника всегда делайте switchover, а не просто останавливайте сервер (остановка не ждёт репликации на реплики).

## Дополнительная информация

### См. также
- **[Обзор репликации](./overview.md)** — ручной failover.
- **[Split-brain и fencing](./split_brain_fencing.md)** — защита от двойной записи.
- **[Failover и Switchover (mariadbmon)](../MaxScale/maxscale_failover.md)** — автоматический switchover через MaxScale.
- **[Orchestrator](../../MySQL/orchestrator.md)** — автоматический failover для классической репликации.
- **[Failover и Switchover MySQL](../../MySQL/replication/failover_switchover.md)** — аналогичная тема для MySQL.
