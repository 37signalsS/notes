# Disaster Recovery (DR) для MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

*   **Disaster Recovery (DR)** — план и процедуры восстановления сервиса после катастрофы (потеря дата-центра, corruption, человеческая ошибка). Цель — достижение RTO и RPO.
*   **RTO (Recovery Time Objective)** — максимально допустимое время простоя. Цель DR: восстановить сервис за RTO.
*   **RPO (Recovery Point Objective)** — максимально допустимая потеря данных (во времени). Цель DR: потерять не более RPO данных.
*   **DR Runbook** — пошаговая процедура восстановления после катастрофы.
*   **PITR (Point-in-Time Recovery)** — восстановление до конкретного момента времени через бэкап + binlog. Подробнее: **[Резервное копирование](backup_and_recovery.md)**.
*   **Air-gapped backup** — бэкап, изолированный от production (оффлайн, другой дата-центр). Защита от ransomware и corruption.
*   **Immutable backup** — бэкап, который нельзя изменить или удалить (WORM-хранилище).

## Базовые концепции

### Стратегия 3-2-1-1-0

Стандартная стратегия резервного копирования для DR:

*   **3** копии данных (1 production + 2 бэкапа).
*   **2** разных носителя (диск + лента/объектное хранилище).
*   **1** копия вне площадки (другой дата-центр).
*   **1** immutable/air-gapped бэкап.
*   **0** ошибок при проверке восстановления.

### RPO/RPO по топологии

| Топология | RPO | RTO | Механизм |
| :--- | :--- | :--- | :--- |
| **Galera Cluster** | 0 | секунды | Синхронная репликация, auto-failover |
| **Source-Replica + semi-sync** | ~0 | минуты | Полусинхронная репликация + Orchestrator/MaxScale |
| **Source-Replica async** | секунды-минуты | минуты | Асинхронная репликация + failover |
| **Бэкап + PITR** | до 24 ч (зависит от частоты) | часы | mariadb-backup + binlog |

### Компоненты DR-плана

1.  **Бэкапы:** физические (mariadb-backup) + логические (mariadb-dump) + binlog.
2.  **Репликация:** hot standby (replica или Galera).
3.  **Документация:** runbook с контактами, шагами, проверкой.
4.  **Тестирование:** регулярные учения (fire drill) восстановления.

## Практические сценарии

### 1. DR Runbook: полная потеря primary

**Симптом:** primary недоступен, данные повреждены или дата-центр потерян.

**Шаги:**

```bash
# 1. Оценить ситуацию
# - Есть ли реплика с актуальными данными?
# - Каков RPO (какие данные потеряны)?

# 2. Если есть реплика (Source-Replica):
#    a. Остановить репликацию на реплике
mariadb -u root -p -e "STOP REPLICA;"

#    b. Проверить GTID-позицию реплики
mariadb -u root -p -e "SELECT @@gtid_slave_pos;"

#    c. Промотировать реплику в source
mariadb -u root -p -e "
  RESET REPLICA ALL;
  SET GLOBAL read_only = 0;
  SET GLOBAL read_only = 0;"

#    d. Перенаправить приложение на новый source (VIP/ProxySQL/MaxScale)

# 3. Если реплик нет — восстановление из бэкапа + PITR:
#    a. Восстановить последний физический бэкап
mariadb-backup --copy-back --target-dir=/backup/latest

#    b. Применить binlog до момента катастрофы (PITR)
mariadb-binlog --start-position=... /var/log/mysql/mariadb-bin.000001 | mariadb -u root -p

# 4. Валидация
mariadb -u root -p -e "CHECK TABLE shop.orders;"
```

### 2. DR Runbook: corruption таблицы

**Симптом:** `ERROR 1032`, `InnoDB: Database page corruption`, `CHECK TABLE` — ошибка.

**Шаги:**

```sql
-- 1. Диагностика
CHECK TABLE shop.orders;
SHOW ENGINE INNODB STATUS\G

-- 2. Если corruption в одной таблице — восстановить из бэкапа
--    a. Экспортировать неповреждённые данные (если возможно)
mariadb-dump shop other_tables > other_tables.sql

--    b. Восстановить повреждённую таблицу из бэкапа
--    c. Импортировать остальные данные
```

```bash
# 3. Если corruption критична — восстановить весь datadir из бэкапа
systemctl stop mariadb
mv /var/lib/mysql /var/lib/mysql.corrupt
mariadb-backup --copy-back --target-dir=/backup/latest
chown -R mysql:mysql /var/lib/mysql
systemctl start mariadb
```

### 3. DR Runbook: случайный DROP DATABASE

**Симптом:** `DROP DATABASE` выполнен по ошибке.

**Шаги (если binlog включён и RBR):**

```bash
# 1. Найти момент DROP в binlog
mariadb-binlog --start-datetime="2026-10-04 10:00:00" \
  --stop-datetime="2026-10-04 12:00:00" \
  /var/log/mysql/mariadb-bin.000001 | grep -i "drop database"

# 2. Восстановить: бэкап + binlog до момента перед DROP
#    a. Восстановить бэкап
mariadb-backup --copy-back --target-dir=/backup/latest

#    b. Применить binlog до момента перед DROP (PITR)
mariadb-binlog --stop-position=<position_before_drop> \
  /var/log/mysql/mariadb-bin.000001 | mariadb -u root -p
```

**Профилактика:** `sql_mode` с `NO_AUTO_CREATE_USER`, отдельные привилегии для DROP, delayed replica (см. **[Отложенная репликация](replication/delayed_replication.md)**).

### 4. Тестирование DR (fire drill)

```bash
# Периодическое тестирование восстановления (регламент)
# 1. Создать изолированную среду (Docker или VM)
docker run -d --name mariadb-dr-test \
  -e MARIADB_ROOT_PASSWORD=test \
  -v /tmp/dr-test:/var/lib/mysql \
  mariadb:11.8

# 2. Восстановить бэкап в изолированную среду
mariadb-backup --copy-back --target-dir=/backup/latest \
  --datadir=/tmp/dr-test

# 3. Проверить целостность
mariadb -S /tmp/dr-test/mysql.sock -u root -ptest \
  -e "CHECK TABLE shop.orders; SELECT COUNT(*) FROM shop.orders;"

# 4. Задокументировать RTO (время восстановления)
```

### 5. Географический DR (multi-DC)

```sql
-- Репликация в другой дата-центр (WAN)
-- На replica в DC2:
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST='source-dc1.example.com',
  SOURCE_USER='repl',
  SOURCE_PASSWORD='...',
  SOURCE_USE_GTID=slave_pos;

-- Настроить сжатие для WAN
SET GLOBAL slave_compressed_protocol = ON;
```

**Рекомендации для WAN:**
*   `slave_compressed_protocol = ON` — сжатие трафика.
*   Увеличьте `slave_net_timeout` и `net_read_timeout`.
*   Мониторьте лаг репликации (WAN-лаг выше LAN).

## Устранение неполадок (Troubleshooting)

### Бэкап не восстанавливается

*   **Причина:** повреждённый бэкап, несовместимость версий, не выполнена prepare.
*   **Диагностика:** `mariadb-backup --prepare` — ошибки; проверка контрольных сумм.
*   **Решение:** пересоздайте бэкап; проверьте версию mariadb-backup; выполните `--prepare` перед `--copy-back`.

### PITR: binlog неполный

*   **Причина:** binlog удалён (`binlog_expire_logs_seconds`), повреждён.
*   **Решение:** восстановите последний полный бэкап; увеличьте `binlog_expire_logs_seconds`; храните binlog отдельно.

### RTO превышен

*   **Причина:** медленное восстановление (большой бэкап, медленный диск).
*   **Решение:** используйте физические бэкапы (mariadb-backup быстрее dump); репликация для hot standby; параллельное восстановление.

## Лучшие практики (Best Practices)

1.  **Стратегия 3-2-1-1-0** — минимум для DR.
2.  **Тестируйте восстановление** ежеквартально (fire drill) — бэкап без проверки восстановления не является бэкапом.
3.  **RPO/RTO согласуйте с бизнесом** — определите допустимую потерю и время простоя.
4.  **Galera для RPO=0**, Source-Replica для RPO~0, бэкап+PITR для RPO=часы.
5.  **Air-gapped/immutable бэкап** — защита от ransomware.
6.  **Delayed replica** (1 час) — защита от логических ошибок (DROP DATABASE).
7.  **Документируйте runbook** с контактами и эскалацией.

## Дополнительная информация

### См. также

*   **[Резервное копирование и PITR](backup_and_recovery.md)** — детальные процедуры.
*   **[Отказоустойчивость](high_availability.md)** — Galera, Orchestrator, MaxScale.
*   **[Общие концепции DR](../../Concepts/disaster_recovery.md)** — теория RTO/RPO.
*   **[Отложенная репликация](replication/delayed_replication.md)** — защита от логических ошибок.
*   **[Репликация: split-brain и fencing](replication/split_brain_fencing.md)** — защита от двойной записи.

### Внешние ресурсы

*   [MariaDB Backup and Restore](https://mariadb.com/kb/en/backup-and-restore/)
*   [MariaDB Disaster Recovery](https://mariadb.com/docs/server/server-usage/high-availability/)
*   [MariaDB mariadb-backup](https://mariadb.com/kb/en/mariabackup-overview/)
*   [MariaDB PITR](https://mariadb.com/kb/en/point-in-time-recovery/)
