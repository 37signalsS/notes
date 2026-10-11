# Мониторинг репликации MariaDB: Prometheus, алерты, SLO

**Актуально для:** MariaDB 11.4 LTS / 12.3 LTS, mysqld_exporter 0.20.0+

## Определения

*   **SLO (Service Level Objective)** — целевое значение метрики (например, лаг репликации < 5 секунд в 99% времени).
*   **`mysqld_exporter`** — экспортер метрик MariaDB/MySQL в формате Prometheus. Коллектор `slave_status` / `replication` экспортирует поля `SHOW REPLICA STATUS` как метрики.
*   **`mysql_slave_status_seconds_behind_master`** — метрика Prometheus: лаг репликации в секундах (из `Seconds_Behind_Source`).
*   **`mysql_slave_status_slave_io_running` / `mysql_slave_status_slave_sql_running`** — метрики статуса потоков (1 = работает, 0 = остановлен).
*   **Recording rules** — предвычисленные PromQL-выражения в Prometheus, снижающие нагрузку и ускоряющие алерты.

## Базовые концепции

### Метрики репликации в Prometheus

Через `mysqld_exporter` доступны (имена зависят от версии экспортера):

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `mysql_slave_status_seconds_behind_master` | Лаг репликации (сек) | > 30 (warning), > 60 (critical) |
| `mysql_slave_status_slave_io_running` | I/O-поток (1/0) | == 0 |
| `mysql_slave_status_slave_sql_running` | SQL-поток (1/0) | == 0 |
| `mysql_slave_status_slave_retried_transactions` | Повторные попытки | рост > 0 |
| `mysql_slave_status_master_server_id` | ID источника | изменение после failover |

> **Примечание:** имена метрик зависят от версии `mysqld_exporter`. В новых версиях коллектор `replication` может использовать префикс `mysql_replication_`. Проверьте фактические имена через `curl http://exporter:9104/metrics`.

### Почему Seconds_Behind_Source ненадёжен

Метрика `Seconds_Behind_Source` (и соответствующая Prometheus-метрика) может быть неточной:
*   Длительная транзакция: показывает 0, пока транзакция применяется, затем резко прыгает.
*   Параллельная репликация: транзакции применяются не в порядке записи.
*   I/O-поток остановлен: значение `NULL` или 0, что не означает отсутствие лага.

**Альтернативы:**
*   **GTID-позиция**: сравнение `gtid_binlog_pos` (источник) и `gtid_slave_pos` (реплика) — точный объём не применённых данных.
*   **`pt-heartbeat`** — истинный лаг на уровне приложения.
*   **Performance Schema**: `performance_schema.replication_applier_status_by_worker`.

### SLO на репликацию

Типичные SLO для production:

| Метрика | SLO | Алерт |
| :--- | :--- | :--- |
| Лаг репликации | < 5 секунд (p99) | warning > 30s, critical > 60s |
| Доступность репликации | 99.9% (IO+SQL running) | critical при == 0 |
| Консистентность | 0 расхождений (pt-table-checksum) | critical при DIFFS > 0 |

## Практические сценарии

### Сценарий 1: Настройка mysqld_exporter для репликации

```bash
# Пользователь для мониторинга (на каждом узле)
mysql -u root -p
```

```sql
CREATE USER 'monitor'@'localhost' IDENTIFIED BY 'YOUR_SECURE_PASSWORD'
    WITH MAX_USER_CONNECTIONS 3;
GRANT REPLICATION CLIENT, PROCESS, SHOW DATABASES, SHOW VIEW ON *.* TO 'monitor'@'localhost';
GRANT SELECT ON performance_schema.* TO 'monitor'@'localhost';
FLUSH PRIVILEGES;
```

```bash
# /etc/mysqld_exporter/.my.cnf
[client]
user=monitor
password=YOUR_SECURE_PASSWORD

# Запуск
mysqld_exporter \
    --config.my-cnf=/etc/mysqld_exporter/.my.cnf \
    --web.listen-address=:9104
```

> **Примечание:** для MariaDB 10.11+ `REPLICATION CLIENT` покрывает мониторинг репликации. Подробнее: **[Привилегии](./replication_privileges.md)**.

### Сценарий 2: Prometheus-алерты на репликацию

```yaml
# /etc/prometheus/alerts/mariadb-replication.yml
groups:
- name: mariadb-replication
  rules:
  - alert: MariaDBReplicationLag
    expr: mysql_slave_status_seconds_behind_master > 30
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "MariaDB: лаг репликации > 30s на {{ $labels.instance }}"
      description: "Seconds_Behind_Source = {{ $value }}s. Проверьте SQL-поток и нагрузку на реплике."

  - alert: MariaDBReplicationLagCritical
    expr: mysql_slave_status_seconds_behind_master > 60
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "MariaDB: критический лаг репликации > 60s на {{ $labels.instance }}"

  - alert: MariaDBReplicationStopped
    expr: mysql_slave_status_slave_io_running == 0 or mysql_slave_status_slave_sql_running == 0
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "MariaDB: репликация остановлена на {{ $labels.instance }}"
      description: "IO_Running или SQL_Running = 0. Проверьте SHOW REPLICA STATUS."

  - alert: MariaDBReplicationRetriedTransactions
    expr: increase(mysql_slave_status_slave_retried_transactions[10m]) > 0
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "MariaDB: повторные транзакции на {{ $labels.instance }}"
```

> **Важно:** после failover метрика `mysql_slave_status_seconds_behind_master` может показывать `NULL` или отрицательные значения в течение нескольких секунд. Настройте алерт с `for: >= 5m` и дополнительную проверку `Slave_IO_Running` / `Slave_SQL_Running`.

### Сценарий 3: Recording rules (снижение нагрузки)

```yaml
# /etc/prometheus/rules/mariadb-replication-recording.yml
groups:
- name: mariadb-replication-recording
  rules:
  - record: job:mariadb_replication_lag:max
    expr: max by (job) (mysql_slave_status_seconds_behind_master)
  - record: job:mariadb_replication_running:min
    expr: min by (job) (mysql_slave_status_slave_io_running * mysql_slave_status_slave_sql_running)
```

### Сценарий 4: GTID-лаг через кастомный экспортер

Для точного измерения лага (вместо `Seconds_Behind_Source`):

```bash
# Скрипт сравнения GTID-позиций (упрощённый)
# На источнике: SELECT @@gtid_binlog_pos;
# На реплике: SELECT @@gtid_slave_pos;
# Разница = объём не применённых транзакций
```

Или через `pt-heartbeat` (истинный лаг):

```bash
# На источнике
pt-heartbeat --update --database heartbeat --create-table --daemonize \
    --user=monitor --password=***

# Мониторинг
pt-heartbeat --monitor --database heartbeat --master-server-id=1 \
    --user=monitor --password=***
```

### Сценарий 5: Grafana-дашборд

Панели для репликации (методология USE/RED):
*   **Utilization**: `mysql_slave_status_seconds_behind_master` (time series).
*   **Saturation**: `Relay_Log_Space` (если экспортируется).
*   **Errors**: `mysql_slave_status_slave_retried_transactions`.
*   **Status**: `mysql_slave_status_slave_io_running`, `mysql_slave_status_slave_sql_running` (stat panels).

Подробнее о дашбордах: **[Мониторинг MariaDB](../monitoring.md)**.

## Валидация

```bash
# Проверка метрик экспортера
curl -s http://exporter:9104/metrics | grep slave_status
# → mysql_slave_status_seconds_behind_master{...} 0
# → mysql_slave_status_slave_io_running{...} 1
# → mysql_slave_status_slave_sql_running{...} 1

# Проверка алертов в Prometheus
curl -s http://prometheus:9090/api/v1/alerts | jq '.data.alerts[] | .labels.alertname'
```

## Типовые ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Метрики репликации отсутствуют | Нет прав `REPLICATION CLIENT` у `monitor` | Дайте `GRANT REPLICATION CLIENT` |
| `seconds_behind_master` = NaN | Репликация остановлена или `NULL` | Проверьте `Replica_IO_Running`; алерт на `== 0` |
| Ложные алерты после failover | Метрика `NULL`/отрицательная в первые секунды | `for: >= 5m` + проверка IO/SQL Running |
| Имена метрик не совпадают | Другая версия `mysqld_exporter` | Проверьте `/metrics` и адаптируйте PromQL |
| Алерт не срабатывает | Экспортер не опрашивает реплику | Проверьте `up{job="mariadb"} == 1` |

## Best Practices

1.  **Алерты на IO/SQL Running** — критический сигнал остановки репликации.
2.  **`for: >= 2m`** — защита от flapping при кратковременных скачках.
3.  **Не полагайтесь только на `Seconds_Behind_Source`** — используйте GTID-позиции или `pt-heartbeat`.
4.  **Recording rules** — выносите сложные PromQL для снижения нагрузки на Prometheus.
5.  **Мониторьте место на диске** — заполнение диска на реплике останавливает SQL-поток.
6.  **Алерт на изменение `master_server_id`** — сигнал незапланированного failover.

## Дополнительная информация

### См. также
- **[Мониторинг MariaDB](../monitoring.md)** — полный набор метрик, mysqld_exporter, Grafana.
- **[Диагностика и Troubleshooting](./troubleshooting.md)** — измерение лага, pt-heartbeat.
- **[Мониторинг MySQL](../../MySQL/monitoring.md)** — аналогичная тема для MySQL.
- **[Документация mysqld_exporter](https://github.com/prometheus/mysqld_exporter)**
