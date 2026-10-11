# Собеседование: вопросы по репликации MariaDB

**Актуально для:** MariaDB 11.4 LTS / 12.3 LTS

## Определения

*   **GTID (Global Transaction ID)** — уникальный идентентификатор транзакции в топологии репликации. Формат MariaDB: `domain-id-server-id:sequence`.
*   **RPO (Recovery Point Objective)** — максимально допустимая потеря данных.
*   **RTO (Recovery Time Objective)** — максимально допустимое время восстановления.
*   **Crash-safe replication** — восстановление реплики после сбоя без потери консистентности.

## Базовые концепции

### Тематические группы вопросов

1.  **Архитектура**: потоки репликации, binlog, relay log, GTID.
2.  **Настройка**: GTID, параллельная репликация, полусинхронная, crash-safe.
3.  **Мониторинг**: лаг, `Seconds_Behind_Source`, Prometheus.
4.  **Troubleshooting**: ошибки 1236/2003/1045/1062/1032, GTID skip.
5.  **Failover**: ручной/автоматический, split-brain, fencing.
6.  **Топологии**: каскадная, кольцевая, multi-source, delayed.

## Практические сценарии

### Группа 1: Архитектура

**Q: Какие потоки участвуют в репликации?**
> A: На источнике — Binlog Dump Thread (отправляет binlog). На реплике — I/O Thread (записывает в relay log) и SQL Thread (применяет из relay log). При параллельной репликации — Coordinator + Worker threads.

**Q: Что такое relay log?**
> A: Локальный журнал реплики, куда I/O-поток записывает события от источника перед применением SQL-потоком. Обеспечивает crash-safe recovery (при `relay_log_recovery = ON`).

**Q: В чём разница SBR, RBR, Mixed?**
> A: SBR — записывает SQL-запросы (экономия места, но нестабилен при `NOW()`, `RAND()`). RBR — записывает изменения строк (надёжен, но больше объём). Mixed — автоматический выбор. Рекомендация: `binlog_format = ROW`.

**Q: Что такое GTID?**
> A: Global Transaction ID — уникальный идентификатор транзакции в топологии. Формат MariaDB: `domain-id-server-id:sequence`. Упрощает failover и восстановление позиции (не нужно отслеживать file:pos).

### Группа 2: Настройка

**Q: Как включить GTID-репликацию?**
> A: На источнике: `server_id`, `log_bin`, `binlog_format=ROW`, `gtid_domain_id`, `gtid_strict_mode=ON`. На реплике: `server_id`, `relay_log`, `read_only=1`, `relay_log_recovery=ON`, `relay_log_info_repository=TABLE`. Подключение: `CHANGE REPLICATION SOURCE TO ... SOURCE_USE_GTID=slave_pos`.

**Q: Что такое crash-safe replication?**
> A: Механизм восстановления реплики после сбоя: `relay_log_recovery = ON` (повторная закачка relay log), `relay_log_info_repository = TABLE` (позиция в таблице, а не файле), `sync_relay_log = 1` (синхронизация на диск).

**Q: Режимы параллельной репликации?**
> A: `optimistic` (параллельно, откат при конфликте — рекомендуется с 10.5), `conservative` (только для group commit), `aggressive` (максимальный параллелизм, рискованен), `minimal` (только commit параллельно). Параметр: `slave_parallel_mode`.

**Q: Полусинхронная репликация: AFTER_SYNC vs AFTER_COMMIT?**
> A: `AFTER_SYNC` (рекомендуется): источник записывает в движок и binlog, ждёт ACK реплики, только затем транзакция видна клиентам — нет phantom reads. `AFTER_COMMIT`: транзакция фиксируется до ACK — клиенты могут увидеть данные, ещё не ушедшие на реплику.

### Группа 3: Мониторинг

**Q: Как измерить лаг репликации?**
> A: `Seconds_Behind_Source` (ненадёжен при длительных транзакциях и параллельной репликации). Надёжнее: сравнение GTID-позиций (`gtid_binlog_pos` vs `gtid_slave_pos`), `pt-heartbeat`, `performance_schema.replication_applier_status_by_worker`.

**Q: Почему Seconds_Behind_Source может быть неточным?**
> A: (1) Длительная транзакция: показывает 0, пока применяется, затем прыгает. (2) Параллельная репликация: транзакции применяются не в порядке записи. (3) I/O-поток остановлен: значение NULL/0, что не означает отсутствие лага.

**Q: Какие метрики алертить в Prometheus?**
> A: `mysql_slave_status_seconds_behind_master > 30` (warning), `> 60` (critical); `mysql_slave_status_slave_io_running == 0` или `mysql_slave_status_slave_sql_running == 0` (critical). Алерты с `for: >= 2m` для защиты от flapping.

### Группа 4: Troubleshooting

**Q: Error 1236 — что делать?**
> A: Источник удалил binlog, нужный реплике. Решение: увеличить `binlog_expire_logs_seconds` (больше максимального лага), пересоздать реплику (re-seeding) с текущего дампа.

**Q: Error 1062 (Duplicate entry)?**
> A: Попытка записать существующие данные (ручная запись на реплику или дублирование GTID). Решение: удалить строку на реплике или пропустить транзакцию через GTID skip.

**Q: Как пропустить битую транзакцию в GTID-репликации?**
> A: `STOP REPLICA;` → `SET GTID_NEXT='domain-server:seq'; BEGIN; COMMIT; SET GTID_NEXT='AUTOMATIC';` → `START REPLICA;`. Записывает пустую транзакцию с тем же GTID. Предупреждение: приводит к расхождению данных — только после анализа причины.

**Q: Error 1032 (Can't find record)?**
> A: На источнике удалили/обновили строку, которой нет на реплике. Решение: восстановить строку на реплике или `slave_skip_errors = 1032` (рискованно). Частая причина — фильтрация (`replicate-ignore-db`).

**Q: Replica_SQL_Running: No — первые шаги?**
> A: `SHOW REPLICA STATUS\G` → `Last_SQL_Error`. Классификация: I/O (связь) или SQL (применение). Проверка: сеть, диск, permissions, конфликты данных. Восстановление: пропуск, re-seeding, переключение источника.

### Группа 5: Failover

**Q: Ручной failover: шаги?**
> A: (1) Выбрать реплику с минимальным лагом. (2) Остановить запись на старом источнике (`super_read_only = ON` — fencing). (3) Дождаться применения всех транзакций на новом источнике. (4) На новом источнике: `STOP REPLICA; RESET REPLICA ALL; read_only = OFF;`. (5) Перенастроить остальные реплики: `CHANGE REPLICATION SOURCE TO ... SOURCE_USE_GTID=slave_pos`. (6) Обновить конфигурацию приложения.

**Q: Что такое split-brain и как его предотвратить?**
> A: Два узла одновременно принимают запись. Предотвращение: `read_only = ON` на репликах, `super_read_only = ON` (fencing), автоматический failover через Orchestrator/MaxScale, STONITH в Pacemaker-кластерах.

**Q: Switchover vs Failover?**
> A: Switchover — плановое переключение (обслуживание), с ожиданием синхронизации, RPO = 0. Failover — аварийное, без ожидания, RPO > 0 при асинхронной репликации.

### Группа 6: Топологии

**Q: Каскадная репликация: зачем и как?**
> A: `Source → Replica1 → Replica2`. Снижает нагрузку на источник (одно соединение вместо N). Требует `log_slave_updates = ON` на промежуточном узле. Лаг суммируется по звеньям.

**Q: Multi-source репликация: зачем?**
> A: Одна реплика подключается к нескольким источникам (каналы). Используется для агрегации данных из разных шардов/филиалов в одно хранилище. Все источники должны иметь уникальные `server_id`.

**Q: Delayed replication: зачем?**
> A: `SOURCE_DELAY = N` — реплика применяет транзакции с задержкой. Защита от логических ошибок (`DROP TABLE`, ошибочный `UPDATE`): если ошибка обнаружена в течение окна задержки, реплика ещё не применила её. Не заменяет бэкапы; при failover теряет данные за время задержки.

**Q: Galera vs Source-Replica?**
> A: Galera — синхронная multi-master, RPO = 0, автоматический failover, но сложнее и ограничена по масштабированию записи. Source-Replica — асинхронная/полусинхронная, RPO > 0, один источник, проще, масштабирует чтение.

## Типовые ошибки

| Вопрос | Частая ошибка в ответе | Правильный ответ |
| :--- | :--- | :--- |
| Лаг репликации | «Только `Seconds_Behind_Source`» | `Seconds_Behind_Source` ненадёжен; GTID-позиции, `pt-heartbeat` |
| GTID skip | «`sql_slave_skip_counter`» | Deprecated, не работает с GTID; используйте `SET GTID_NEXT` |
| Failover | «Промоутить реплику» | Сначала fencing старого источника (`super_read_only = ON`) |
| Crash-safe | «`sync_relay_log = 1` достаточно» | Нужно `relay_log_recovery = ON` + `relay_log_info_repository = TABLE` |
| Полусинхронность | «`AFTER_COMMIT` лучше» | `AFTER_SYNC` рекомендуется (нет phantom reads) |

## Best Practices

1.  **GTID** — всегда включайте; упрощает failover и диагностику.
2.  **`binlog_format = ROW`** — для надёжности и совместимости с фильтрацией.
3.  **`read_only = ON`** на репликах — всегда.
4.  **Crash-safe** — `relay_log_recovery = ON`, `relay_log_info_repository = TABLE`.
5.  **Мониторинг** — алерты на IO/SQL Running и лаг; не только `Seconds_Behind_Source`.
6.  **Fencing** — `super_read_only = ON` перед промоушеном.
7.  **Тестирование** — отрабатывайте failover в staging.

## Дополнительная информация

### См. также
- **[Обзор репликации](./overview.md)** — архитектура и потоки.
- **[Диагностика и Troubleshooting](./troubleshooting.md)** — ошибки и решения.
- **[Split-brain и fencing](./split_brain_fencing.md)** — защита от двойной записи.
- **[Отложенная репликация](./delayed_replication.md)** — SOURCE_DELAY.
- **[Топологии](./topologies.md)** — каскадная, кольцевая, multi-master.
