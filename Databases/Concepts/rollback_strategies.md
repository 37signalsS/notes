# Стратегии отката (Rollback Strategies) в Database

## Определения

**Точки отката (Rollback Points)** — это заранее подготовленные ориентиры, к которым можно безопасно вернуться при неудачных изменениях данных или схемы. Они необходимы как для быстрого возврата в рамках транзакций, так и для восстановлений на уровне базы данных и инфраструктуры. Критично понимать различия между локальным откатом (в пределах одной транзакции) и системным (PITR — восстановление до момента времени) и планировать их использование до начала релиза.

## Основные концепции

### Классы точек отката

| Механизм | Уровень | Что откатывает | Ограничения |
| :--- | :--- | :--- | :--- |
| SAVEPOINT | Транзакция | Подмножество операций до коммита | Не применим после COMMIT |
| ROLLBACK | Транзакция | Все изменения в незакоммиченной транзакции | Потеря всех промежуточных изменений |
| Restore Point (PITR) | База | Состояние на момент времени | Требует журналов (WAL/binlog) и бэкапа |
| Снимок хранилища (LVM/ZFS/облако) | Хранилище | Блоковый снимок данных | Когерентность зависит от паузы/фризов |
| Версия миграций | Схема | Структурные изменения | «Down»-миграции не всегда обратимы (особенно с потерей данных) |

### Транзакционный откат

Транзакционные точки отката используются для безопасных, изолированных изменений в рамках одной сессии. Подход уместен для корректировки батч-операций и сложных процедур. Подробнее о свойствах транзакций — [ACID: Свойства транзакций](./acid.md).

## Практические сценарии

### Сценарий 1: Транзакционный откат с SAVEPOINT

```sql
BEGIN;

UPDATE accounts SET balance = balance - 100 WHERE id = 1;
SAVEPOINT before_bulk;

UPDATE accounts SET balance = balance + 100 WHERE id IN (SELECT id FROM vip WHERE tier = 'gold');

-- Обнаружили аномалию
ROLLBACK TO SAVEPOINT before_bulk;

-- Продолжаем альтернативной стратегией
UPDATE accounts SET balance = balance + 100 WHERE id IN (SELECT id FROM vip WHERE verified);

COMMIT;
```

Этот механизм не заменяет восстановление уровня БД: после `COMMIT` откатить транзакцию невозможно без PITR.

### Сценарий 2: PITR в PostgreSQL (восстановление на точку во времени)

```bash
# Создание restore point перед миграцией
psql -c "SELECT pg_create_restore_point('pre_migration_2025_03_25');"

# Восстановление на точку во времени (через wal-g)
wal-g backup-fetch /var/lib/postgresql/data "2025-03-25T10:00:00"
```

Альтернатива через `recovery.conf` (PostgreSQL 12+):

```bash
restore_command = 'cp /wal_archive/%f %p'
recovery_target_time = '2025-03-25 10:00:00'
recovery_target_action = 'promote'
```

Подробнее о PITR в PostgreSQL — [PostgreSQL/Concepts/backup_and_recovery.md](../PostgreSQL/Concepts/backup_and_recovery.md).

### Сценарий 3: PITR в MySQL (восстановление через binlog)

```bash
# Создание бэкапа перед изменениями
mysqldump -u root -p --single-transaction --master-data=2 mydb > backup_$(date +%F).sql

# Восстановление до точки во времени через binlog
mysqlbinlog --stop-datetime="2025-03-25 10:00:00" /var/log/mysql/binlog.000123 | mysql -u root -p
```

### Сценарий 4: Снимок хранилища (LVM)

```bash
# Создание снапшота перед миграцией
lvcreate -L 10G -s -n pg_snapshot /dev/vg0/pgdata

# В случае проблем — откат
umount /var/lib/postgresql/data
lvconvert --merge /dev/vg0/pg_snapshot
reboot
```

### Сценарий 5: Откат миграций схемы

Для отката миграций используются down-миграции или специализированные инструменты (Flyway, Liquibase, Atlas). Подробнее — [migrations/rollback_strategies.md](./migrations/rollback_strategies.md).

## Дополнительная информация

- **WAL как основа PITR:** Журнал предзаписи (WAL) обеспечивает возможность восстановления на любую точку во времени — [write_ahead_log.md](./write_ahead_log.md).
- **Резервное копирование:** Общие стратегии бэкапов и восстановления — [backups.md](./backups.md).
- **Откат миграций:** Специфичные стратегии для миграций схемы — [migrations/rollback_strategies.md](./migrations/rollback_strategies.md).
- **Связанные концепции:** [acid.md](./acid.md) (атомарность транзакций), [backup_validation.md](./backup_validation.md) (проверка бэкапов).
