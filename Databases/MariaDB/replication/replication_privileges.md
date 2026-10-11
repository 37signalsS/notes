# Привилегии для репликации MariaDB

**Актуально для:** MariaDB 10.5+ / 11.0+ / 11.4 LTS / 12.3 LTS

## Определения

*   **`REPLICATION SLAVE`** — привилегия для учётной записи, используемой репликой на источнике. Необходима для получения обновлений. Алиас: `REPLICATION REPLICA` (MariaDB 10.5+).
*   **`REPLICATION CLIENT`** — привилегия для мониторинга репликации (`SHOW REPLICA STATUS`). До MariaDB 10.5 включала `SHOW SLAVE STATUS`.
*   **`REPLICA MONITOR`** — привилегия (MariaDB 10.5.9+), автоматически выдаваемая пользователям с `REPLICATION CLIENT` или `REPLICATION SLAVE` при апгрейде. Позволяет мониторить репликацию.
*   **`REPLICATION SLAVE ADMIN`** — привилегия (MariaDB 11.0+, MDEV-21743) для администрирования репликации: `CHANGE REPLICATION SOURCE TO`, `START REPLICA`, `STOP REPLICA`, `RESET REPLICA`. До 11.0 эти операции требовали `SUPER`.
*   **`READ_ONLY ADMIN`** — привилегия (MariaDB 11.0+) для управления `read_only`/`super_read_only`. До 11.0 требовала `SUPER`.
*   **`BINLOG ADMIN` / `BINLOG MONITOR`** — привилегии (MariaDB 11.0+) для администрирования/мониторинга бинарного лога.
*   **`CONNECTION ADMIN`** — привилегия (MariaDB 11.0+) для управления соединениями (убийство сессий, обход `read_only`).

## Базовые концепции

### Разделение привилегий (MariaDB 11.0+)

Начиная с MariaDB 11.0, `SUPER` разделён на гранулярные привилегии (MDEV-21743). Операции репликации больше не требуют `SUPER`:

| Операция | Привилегия (11.0+) | До 11.0 |
| :--- | :--- | :--- |
| Репликация (реплика → источник) | `REPLICATION SLAVE` | `REPLICATION SLAVE` |
| `SHOW REPLICA STATUS` | `REPLICATION CLIENT` / `REPLICA MONITOR` | `REPLICATION CLIENT` |
| `CHANGE REPLICATION SOURCE TO` | `REPLICATION SLAVE ADMIN` | `SUPER` |
| `START REPLICA` / `STOP REPLICA` | `REPLICATION SLAVE ADMIN` | `SUPER` |
| `RESET REPLICA` | `REPLICATION SLAVE ADMIN` | `SUPER` |
| `SET GLOBAL read_only` | `READ_ONLY ADMIN` | `SUPER` |
| Убийство сессий | `CONNECTION ADMIN` | `SUPER` |
| `PURGE BINARY LOGS` | `BINLOG ADMIN` | `SUPER` |

### Минимальные наборы привилегий

**Пользователь репликации (`repl_user`)** — на источнике:
```sql
GRANT REPLICATION SLAVE ON *.* TO 'repl_user'@'192.168.1.%';
```

**Пользователь мониторинга (`monitor`)** — на всех узлах:
```sql
GRANT REPLICATION CLIENT, PROCESS, SHOW DATABASES, SHOW VIEW ON *.* TO 'monitor'@'localhost';
GRANT SELECT ON performance_schema.* TO 'monitor'@'localhost';
```

**Пользователь для failover (`mariadbmon` / Orchestrator)** — на всех узлах (MariaDB 11.0+):
```sql
GRANT REPLICATION SLAVE ADMIN, READ_ONLY ADMIN, BINLOG ADMIN,
      CONNECTION ADMIN, PROCESS, RELOAD, SET USER ON *.* TO 'mariadbmon'@'maxscale-host';
```

До MariaDB 11.0:
```sql
GRANT REPLICATION SLAVE, REPLICATION CLIENT, PROCESS, RELOAD, SUPER ON *.* TO 'mariadbmon'@'maxscale-host';
```

### REPLICA MONITOR: автоматический апгрейд

При апгрейде с MariaDB < 10.5.9 на 10.5.9+ пользователи с `REPLICATION CLIENT` или `REPLICATION SLAVE` автоматически получают `REPLICA MONITOR` при старте сервера (не при `mariadb-upgrade`).

### Привилегии для pt-утилит

*   **`pt-table-checksum`**: `SELECT`, `PROCESS`, `REPLICATION CLIENT` (для `SHOW SLAVE STATUS`).
*   **`pt-table-sync`**: `SELECT`, `INSERT`, `UPDATE`, `DELETE` на синхронизируемых таблицах.
*   **`pt-heartbeat`**: `INSERT`, `UPDATE`, `SELECT` на heartbeat-таблице, `REPLICATION CLIENT`.
*   **`mariadb-binlog --read-from-remote-server`**: `REPLICATION SLAVE` или `REPLICATION CLIENT`.

## Практические сценарии

### Сценарий 1: Создание пользователя репликации

```sql
-- На источнике
CREATE USER 'repl_user'@'192.168.1.%' IDENTIFIED BY 'StrongPassword123';
GRANT REPLICATION SLAVE ON *.* TO 'repl_user'@'192.168.1.%';
FLUSH PRIVILEGES;

-- Проверка
SHOW GRANTS FOR 'repl_user'@'192.168.1.%';
-- → GRANT REPLICATION SLAVE ON *.* TO `repl_user`@`192.168.1.%`
```

### Сценарий 2: Пользователь мониторинга (mysqld_exporter)

```sql
CREATE USER 'monitor'@'localhost' IDENTIFIED BY 'YOUR_SECURE_PASSWORD'
    WITH MAX_USER_CONNECTIONS 3;
GRANT REPLICATION CLIENT, PROCESS, SHOW DATABASES, SHOW VIEW ON *.* TO 'monitor'@'localhost';
GRANT SELECT ON performance_schema.* TO 'monitor'@'localhost';
FLUSH PRIVILEGES;
```

### Сценарий 3: Пользователь для MaxScale mariadbmon (MariaDB 11.0+)

```sql
-- На каждом узле кластера
CREATE USER 'mariadbmon'@'maxscale-host' IDENTIFIED BY 'СЛОЖНЫЙ_ПАРОЛЬ';

-- Базовый мониторинг
GRANT REPLICA MONITOR ON *.* TO 'mariadbmon'@'maxscale-host';
GRANT CONNECTION ADMIN ON *.* TO 'mariadbmon'@'maxscale-host';

-- MariaDB 11.0+: операции failover/switchover
GRANT READ_ONLY ADMIN, REPLICATION SLAVE ADMIN ON *.* TO 'mariadbmon'@'maxscale-host';
GRANT BINLOG ADMIN, CONNECTION ADMIN, PROCESS, RELOAD, SET USER ON *.* TO 'mariadbmon'@'maxscale-host';

-- До MariaDB 11.0 вместо READ_ONLY ADMIN/REPLICATION SLAVE ADMIN:
-- GRANT REPLICATION SLAVE, REPLICATION CLIENT, PROCESS, RELOAD, SUPER ON *.* TO 'mariadbmon'@'maxscale-host';
```

### Сценарий 4: Проверка привилегий

```sql
-- Текущие привилегии пользователя
SHOW GRANTS FOR 'repl_user'@'192.168.1.%';

-- Проверка, что REPLICATION SLAVE ADMIN доступен (11.0+)
SELECT * FROM mysql.global_priv WHERE User='mariadbmon';

-- Проверка через попытку операции
STOP REPLICA;
-- → ERROR 1227 (42000): Access denied; you need (at least one of) the REPLICATION SLAVE ADMIN privilege(s)
```

### Сценарий 5: Миграция с SUPER на гранулярные привилегии (10.x → 11.0+)

```sql
-- Шаг 1: выдайте гранулярные привилегии
GRANT REPLICATION SLAVE ADMIN, READ_ONLY ADMIN, BINLOG ADMIN,
      CONNECTION ADMIN, PROCESS, RELOAD, SET USER ON *.* TO 'mariadbmon'@'maxscale-host';

-- Шаг 2: проверьте, что всё работает
-- (failover, switchover, read_only)

-- Шаг 3: отзовите SUPER (опционально, после проверки)
REVOKE SUPER ON *.* FROM 'mariadbmon'@'maxscale-host';
```

## Типовые ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Access denied` при `CHANGE REPLICATION SOURCE TO` | Нет `REPLICATION SLAVE ADMIN` (11.0+) или `SUPER` (< 11.0) | Выдайте соответствующую привилегию |
| `SHOW REPLICA STATUS` пустой | Нет `REPLICATION CLIENT` / `REPLICA MONITOR` | Выдайте `REPLICATION CLIENT` |
| `read_only` не переключается | Нет `READ_ONLY ADMIN` (11.0+) или `SUPER` | Выдайте `READ_ONLY ADMIN` |
| `REPLICA MONITOR` не выдан автоматически | Апгрейд без перезапуска сервера | Перезапустите MariaDB (привилегия выдаётся при старте) |
| `pt-table-checksum` не работает | Нет `REPLICATION CLIENT` | Выдайте `REPLICATION CLIENT` |

## Best Practices

1.  **Минимальные привилегии** — `repl_user` только `REPLICATION SLAVE`; `monitor` только `REPLICATION CLIENT` + `SELECT` на `performance_schema`.
2.  **Не давайте `SUPER`** сервисным пользователям на MariaDB 11.0+ — используйте гранулярные привилегии.
3.  **Ограничьте хост** — `repl_user@'192.168.1.%'`, не `'%'`.
4.  **`MAX_USER_CONNECTIONS`** для `monitor` — ограничьте число соединений.
5.  **Проверяйте `SHOW GRANTS`** после выдачи привилегий.
6.  **SSL/TLS** для `repl_user` — `REQUIRE SSL` при шифровании репликационного трафика.

## Дополнительная информация

### См. также
- **[Обзор репликации](./overview.md)** — безопасность при настройке.
- **[Failover и Switchover (mariadbmon)](../MaxScale/maxscale_failover.md)** — гранты для mariadbmon.
- **[RBAC](../security/rbac.md)** — сервисные учётные записи.
- **[Документация MariaDB: GRANT](https://mariadb.com/docs/server/reference/sql-statements/account-management-sql-statements/grant)** — полный список привилегий.
