# Бэкап и репликация (XtraBackup + интеграция)

**Актуально для:** MySQL 5.7 / 8.0 / 8.4 LTS, Percona XtraBackup 8.0.35-36 / 8.4.0-6 (ветка 8.0 — EOL с июня 2026; для MySQL 5.7 — legacy-ветка XtraBackup 2.4)

Сценарий: физический бэкап с реплики и подключение восстановленного узла в репликацию. Общие приёмы XtraBackup (сжатие, шифрование, инкременты, частичные бэкапы, история) — в **[Percona XtraBackup — физические бэкапы MySQL](../backup_and_recovery/xtrabackup.md)**; логический дамп с реплики — в **[mysqldump](../backup_and_recovery/mysqldump.md)**.

## Определения

**Hot Backup** — бэкап без остановки сервера (online backup). XtraBackup позволяет делать hot-бэкап InnoDB; MyISAM и другие non-InnoDB таблицы копируются под кратковременным локом в финальной фазе бэкапа.

**--slave-info** — опция XtraBackup для бэкапа с реплики: печатает бинарную позицию source'а и записывает координаты в файл `xtrabackup_slave_info` как команду `CHANGE REPLICATION SOURCE TO`. Позволяет быстро подключить восстановленный узел в топологию.

**--safe-slave-backup** — опция, останавливающая SQL-поток реплики незадолго до копирования InnoDB-файлов (с XtraBackup 8.0.22-15.0 — до начала копирования InnoDB) и дожидающаяся обнуления `Replica_open_temp_tables` в `SHOW STATUS` (таймаут `--safe-slave-backup-timeout`, по умолчанию 300 с). SQL-поток перезапускается по завершении бэкапа. Не требуется при row-based репликации.

**Prepare** (`--prepare`) — этап подготовки бэкапа к восстановлению: применение redo-логов (InnoDB crash-recovery) к скопированным страницам для приведения данных к консистентному состоянию на момент завершения бэкапа.

**Backup locks** — облегчённые блокировки бэкапа MySQL 8.0+: `LOCK INSTANCE FOR BACKUP` (instance-level), `LOCK TABLES FOR BACKUP`, `LOCK BINLOG FOR BACKUP`. XtraBackup применяет их автоматически вместо `FLUSH TABLES WITH READ LOCK`, где это поддерживается сервером.

## Теоретический блок

### Почему бэкап со слейва предпочтителен в репликационной топологии

- **Меньше нагрузки на мастере**: бэкап снимается с реплики, не влияет на продуктивную запись.
- **Меньше риска блокировок/замедления**: особенно при больших объёмах.
- **Удобство для клонирования реплик**: восстановленный с бэкапа слейв можно сразу подключить к мастеру.
- **RPO определяется лагом реплики**: точка согласованности бэкапа — это позиция, до которой реплика применила транзакции source'а, а не текущая позиция source'а. Перед бэкапом проверяйте `Seconds_Behind_Source` — см. **[Мониторинг лага репликации](lag_monitoring.md)**.

### Как фиксируется репликационная позиция

Координаты source'а (`Exec_Source_Log_Pos` / `Exec_Gtid_Set` из `SHOW REPLICA STATUS`) собираются в финальной фазе бэкапа под `LOCK BINLOG FOR BACKUP`, который блокирует операции, способные изменить бинарную позицию или позицию SQL-потока реплики. Так координаты в `xtrabackup_slave_info` соответствуют состоянию применённых транзакций на момент снимка.

Важные нюансы:

- На **MySQL 8.0/8.4** при запуске с `--slave-info` XtraBackup всё ещё использует `FLUSH TABLES WITH READ LOCK` для получения координат (backup locks не дают relay-координат).
- На **Percona Server for MySQL 8.x** таблица `performance_schema.log_status` расширена relay-координатами — лока не требуется даже с `--slave-info`.
- Файл `xtrabackup_slave_info` создаётся на этапе **`--backup`** (в конце, при снятии координат), а не на этапе `--prepare`.

### Интеграция с репликацией: --slave-info

При снятии бэкапа **на реплике** XtraBackup фиксирует позицию, на которой находился слейв относительно мастера. Содержимое `xtrabackup_slave_info`:

File:Pos-вариант (реплика без GTID):
```sql
CHANGE REPLICATION SOURCE TO SOURCE_LOG_FILE='binlog.000123', SOURCE_LOG_POS=456789;
```

GTID-вариант (при `gtid_mode=ON` на снимаемой реплике):
```sql
CHANGE REPLICATION SOURCE TO SOURCE_AUTO_POSITION=1;
```

> **Предупреждение (документация Percona):** не рекомендуется смешивать варианты MySQL (Percona Server / MySQL) в одной репликационной топологии — это может привести к некорректному `xtrabackup_slave_info` при добавлении новой реплики.

> **Предупреждение:** перед использованием реплики как источника бэкапа убедитесь, что она является точной копией source'а. Инструмент проверки — `pt-table-checksum`, см. **[Проверка консистентности реплик](consistency_checks.md)**.

### GTID-особенности

При `gtid_mode=ON`:

- `xtrabackup_binlog_info` содержит бинарные координаты **и GTID последней транзакции** (в XtraBackup 8.4 GTID записывается автоматически при включённом GTID-режиме):
  ```text
  mysql-bin.000002    1232        c777888a-b6df-11e2-a604-080027635ef5:1-4
  ```
  Тот же вывод печатается в stderr: `xtrabackup: MySQL binlog position: filename 'mysql-bin.000002', position 1232, GTID of the last change 'c777888a-b6df-11e2-a604-080027635ef5:1-4'`.
- Для развёртывания новой GTID-реплики: восстановить бэкап, выставить `gtid_purged` по GTID из `xtrabackup_binlog_info`, подключиться с `SOURCE_AUTO_POSITION=1` — см. **[GTID: практические сценарии](gtid_practical.md)** и [How to create a new (or repair a broken) GTID-based replica](https://docs.percona.com/percona-xtrabackup/8.4/create-gtid-replica.html).
- При встраивании в существующую топологию учитывайте `gtid_purged`/`gtid_executed` восстановленного узла — см. **[GTID-репликация](gtid.md)**.

### Prepare — обязательно

Сырые файлы данных после `xtrabackup --backup` неконсистентны для InnoDB. Обязательный шаг: `xtrabackup --prepare --target-dir=...`. Prepare выполняет crash-recovery: применяет собранные в `xtrabackup_logfile` redo-записи к страницам и откатывает незавершённые транзакции. Prepare можно запускать на любой машине — не обязательно на сервере-источнике или сервере восстановления.

- Ожидаемый вывод: `InnoDB: Shutdown completed; log sequence number <N>` и `xtrabackup: completed OK!`.
- После успешного prepare файл `xtrabackup_logfile` **больше не нужен** (redo применён к страницам) — в подготовленном каталоге его нет.
- Prepare идемпотентен: повторный запуск на подготовленном каталоге выдаст `xtrabackup: This target seems to be already prepared.` и `xtrabackup: notice: xtrabackup_logfile was already used to '--prepare'.`
- Не прерывайте prepare: при прерывании файлы данных могут быть повреждены, валидность бэкапа не гарантируется.
- `--use-memory` ускоряет только prepare (в других фазах параметр лишь резервирует память, не влияя на страницы).

## Практический блок

### 0. Предусловия

**Привилегии пользователя бэкапа** (создайте отдельного пользователя, не `root`):

| Привилегия | MySQL 8.0+ | MySQL 5.7 / XtraBackup 2.4 | Зачем |
| :--- | :--- | :--- | :--- |
| `BACKUP_ADMIN` | требуется | нет такой привилегии | `LOCK INSTANCE FOR BACKUP` и доступ к `performance_schema.log_status` (нужен также `SELECT` на эту таблицу) |
| `RELOAD` | требуется | требуется | `FLUSH TABLES WITH READ LOCK` |
| `LOCK TABLES` | требуется | требуется | копирование MyISAM/non-InnoDB при отсутствии backup locks |
| `PROCESS` | требуется | требуется | обработка DDL с `ALGORITHM=INPLACE` |
| `REPLICATION CLIENT` | требуется для `--slave-info` | требуется для `--slave-info` | чтение позиции репликации (`SHOW REPLICA STATUS`) |

```sql
GRANT BACKUP_ADMIN, RELOAD, PROCESS, REPLICATION CLIENT, LOCK TABLES ON *.* TO 'backup_user'@'backup_host';
```

Проверить наличие привилегий можно опцией `--check-privileges`: при отсутствии обязательной привилегии бэкап завершится ошибкой `xtrabackup: Error: missing required privilege LOCK TABLES on *.*`, при отсутствии необязательной — предупреждением `xtrabackup: Warning: missing required privilege REPLICATION CLIENT on *.*`.

**Совместимость версий:** major.minor версии XtraBackup и сервера должны совпадать. XtraBackup 8.0.35-36 работает с сервером 8.0.34 и новее; XtraBackup 8.4 требует БД, созданных в серии 8.4+. Если версия сервера новее версии XtraBackup, бэкап прерывается проверкой — отключить её можно `--no-server-version-check`, но совместимость при этом не гарантируется.

**Ресурсы:** свободное место под бэкап ≈ размер datadir (плюс место для prepare), место на целевом узле для восстановления, сетевой канал для переноса бэкапа.

### 1. Снятие бэкапа со слейва с учётом репликационной позиции

На реплике (рекомендуется):
```bash
# Проверьте лаг перед бэкапом (на MySQL 5.7 — SHOW SLAVE STATUS)
mysql -e "SHOW REPLICA STATUS\G" | grep Seconds_Behind_Source
# → Seconds_Behind_Source: 0

# Снимаем бэкап в директорию /backups/full_$(date +%F_%H%M)
ionice -c2 -n7 nice +10 xtrabackup --user=backup_user --password='<pass>' \
  --backup \
  --slave-info \
  --safe-slave-backup \
  --throttle=100 \
  --target-dir=/backups/full_$(date +%F_%H%M)
# → xtrabackup: completed OK!
# → MySQL binlog position: filename 'binlog.000123', position 456789
```

Пояснения:

- `--slave-info` — фиксирует позицию репликации и записывает `xtrabackup_slave_info` (файл появится сразу после `--backup`, до prepare).
- `--safe-slave-backup` — рекомендуется всегда при бэкапе с реплики (рекомендация документации Percona): кратковременно останавливает SQL-поток перед копированием InnoDB-файлов, пока открыты временные таблицы. При row-based репликации опция не нужна.
- `--throttle=100` — ограничение копирования 100 страниц/сек (16 КБ каждая ≈ 1.6 МБ/с); `ionice`/`nice` снижают приоритет процесса.
- Бэкап снимается без остановки репликации (hot-backup).

### 2. Подготовка бэкапа к восстановлению

На том же хосте или на бэкап-сервере:
```bash
xtrabackup --prepare --use-memory=4G --target-dir=/backups/full_2026-10-03_120000
# → InnoDB: Shutdown completed; log sequence number 15188961605
# → 170223 13:39:31 completed OK!
```

Проверка содержимого подготовленного каталога:
```bash
ls -la /backups/full_2026-10-03_120000/
# Должны присутствовать: backup-my.cnf, xtrabackup_checkpoints,
# xtrabackup_info, xtrabackup_binlog_info, xtrabackup_slave_info (если --slave-info)
# xtrabackup_logfile в подготовленном каталоге отсутствует — redo применён к страницам
```

Состояние бэкапа в `xtrabackup_checkpoints`:
```text
backup_type = full-backuped
from_lsn = 0
to_lsn = 15188961605
last_lsn = 15188961605
```

Содержимое `xtrabackup_slave_info` (пример File:Pos):
```text
CHANGE REPLICATION SOURCE TO SOURCE_LOG_FILE='binlog.000123', SOURCE_LOG_POS=456789;
```

Содержимое `xtrabackup_binlog_info` (координаты; при `gtid_mode=ON` — с GTID последней транзакции):
```text
binlog.000123	456789
```

### 3. Восстановление бэкапа на новом сервере

Остановить MySQL на целевом узле:
```bash
systemctl stop mysql
```

Освободить datadir безопасным способом (не `rm -rf`): перенести старый datadir, создать пустой:
```bash
mv /var/lib/mysql /var/lib/mysql.old_$(date +%F_%H%M)
mkdir -p /var/lib/mysql
chown mysql:mysql /var/lib/mysql
```

Восстановить файлы. `--copy-back` требует пустого целевого каталога и не перезаписывает существующие файлы — при конфликте имён операция завершится ошибкой. Опция `--force-non-empty-directories` позволяет копировать в непустой каталог, но существующие файлы всё равно не перезаписываются:
```bash
xtrabackup --copy-back --target-dir=/backups/full_2026-10-03_120000 --datadir=/var/lib/mysql
# → xtrabackup: completed OK!
```

Альтернатива — `--move-back` (перемещает файлы вместо копирования, удаляя бэкап; используйте с осторожностью). Если конфигурационный файл MySQL в нестандартном месте, укажите его через `--defaults-file` — XtraBackup читает из него расположение datadir.

Установить корректные права:
```bash
chown -R mysql:mysql /var/lib/mysql
```

Если восстанавливаемый узел станет репликой — запретите автозапуск репликации до настройки подключения: в `my.cnf` укажите `skip-replica-start` (MySQL 8.0.26+; ранее — deprecated `skip-slave-start`), затем запустить MySQL:
```bash
systemctl start mysql
```

> Если `ibdata`/`ib_logfile` расположены вне datadir — после применения логов их нужно положить в соответствующие каталоги.

### 4. Подключение восстановленного узла в репликацию (из бэкапа со слейва)

После старта MySQL берём команду из `xtrabackup_slave_info` и дополняем параметрами подключения:

File:Pos-вариант:
```sql
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST='master_host',
  SOURCE_PORT=3306,
  SOURCE_USER='repl_user',
  SOURCE_PASSWORD='repl_pass',
  SOURCE_LOG_FILE='binlog.000123',
  SOURCE_LOG_POS=456789;
START REPLICA;
SHOW REPLICA STATUS\G
```

GTID-вариант (восстановленный узел в GTID-режиме):
```sql
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST='master_host',
  SOURCE_PORT=3306,
  SOURCE_USER='repl_user',
  SOURCE_PASSWORD='repl_pass',
  SOURCE_AUTO_POSITION=1;
START REPLICA;
SHOW REPLICA STATUS\G
```

Пояснения:

- `SOURCE_LOG_FILE`/`SOURCE_LOG_POS` — канонические имена опций в `CHANGE REPLICATION SOURCE TO` (MySQL 8.0.23+); `MASTER_LOG_FILE`/`MASTER_LOG_POS` принимаются как deprecated-синонимы.
- `START REPLICA` требует привилегии `REPLICATION_SLAVE_ADMIN` (или deprecated `SUPER`).
- При GTID: если в `xtrabackup_slave_info` записан `SOURCE_AUTO_POSITION=1` — используйте его; GTID-координаты для контроля также есть в `xtrabackup_binlog_info`. При разрывах в GTID (source удалил нужные бинлоги) подключение с `AUTO_POSITION` невозможно — потребуется более свежий бэкап.

### 5. Валидация

- [ ] `xtrabackup --prepare` завершился без ошибок (`completed OK!`)
- [ ] После старта MySQL поднялся без ошибок в error.log
- [ ] `SHOW REPLICA STATUS` (на MySQL 5.7 — `SHOW SLAVE STATUS`) — `Replica_IO_Running=Yes`, `Replica_SQL_Running=Yes`
- [ ] `Seconds_Behind_Source` небольшое/0 (зависит от времени между бэкапом и подключением)
- [ ] Нет `Last_IO_Error`/`Last_SQL_Error`
- [ ] При GTID — `Retrieved_Gtid_Set`/`Executed_Gtid_Set` корректны, `Executed_Gtid_Set` догоняет source'а
- [ ] Данные проверены: `CHECK TABLE` на критичных таблицах или `xtrabackup --check-tables` (введена в XtraBackup 8.4.0-6)

## Диагностика и устранение неисправностей

| Ошибка / симптом | Причина | Решение |
| :--- | :--- | :--- |
| `xtrabackup: Error: missing required privilege LOCK TABLES on *.*` | Нет прав у backup_user | Выдать `BACKUP_ADMIN`/`LOCK TABLES`; проверить опцией `--check-privileges` |
| `xtrabackup: Warning: missing required privilege REPLICATION CLIENT on *.*` | Нет прав — `--slave-info` не сможет прочитать позицию | Выдать `REPLICATION CLIENT` |
| Бэкап прерван проверкой версии | Сервер новее, чем версия XtraBackup | Обновить XtraBackup; `--no-server-version-check` — только как исключение |
| `Log sequence number (LSN) mismatch` / `last checkpoint LSN is greater` на prepare | Повреждён redo-лог или базовый бэкап; prepare прерван вручную | Сделать новый полный бэкап |
| `--copy-back` завершается ошибкой, файлы не скопированы | datadir не пустой, есть конфликтующие файлы | Очистить/перенести datadir; `--force-non-empty-directories` не перезаписывает существующие файлы |
| `ERROR 1236` при `START REPLICA` (binlog purged) | Source удалил бинлоги, содержащие нужные транзакции | Взять более свежий бэкап; увеличить срок хранения binlog (`binlog_expire_logs_seconds`) — см. **[Управление бинарным логом](binlog_management.md)** |
| GTID conflict (`ERROR 1782`) при подключении | `gtid_executed` восстановленного узла расходится с source'ом | Проверить `gtid_executed` на узле и source'е; восстановить из корректного бэкапа |
| `SOURCE_AUTO_POSITION=1` не подключается | Разрывы в GTID: нужные транзакции purged на source'е | Более свежий бэкап; затем `AUTO_POSITION=1` |
| `--safe-slave-backup` таймаут | `Replica_open_temp_tables` не обнуляется 300 с (длинная транзакция с временными таблицами) | Увеличить `--safe-slave-backup-timeout`; дождаться завершения транзакции |
| Backup fails with Error 24: 'Too many open files' | Мало `ulimit -n` при большом числе файлов | Поднять лимит открытых файлов для пользователя, под которым работает xtrabackup |
| MyISAM-блокировка на время бэкапа | Финальная фаза копирует non-InnoDB под FTWRL/backup lock | Нормальное поведение; сократить долю MyISAM или использовать ROW + backup locks |

## Лучшие практики

1. **Всегда используйте `--safe-slave-backup`** при бэкапе с реплики (рекомендация документации Percona); при row-based репликации опция не обязательна.
2. **Проверяйте лаг и консистентность реплики** перед бэкапом: `Seconds_Behind_Source` и `pt-table-checksum` — бэкап с отстающей или рассинхронизированной реплики расширяет RPO.
3. **Храните метаданные бэкапа вместе с копией**: `xtrabackup_slave_info`, `xtrabackup_binlog_info`, `xtrabackup_checkpoints` — без них подключение в репликацию невозможно.
4. **Ротация и хранение** — см. **[Автоматизацию и верификацию](../backup_and_recovery/automation.md)** (политика хранения, `flock`-идемпотентность) и правило 3-2-1-1-0 в **[Стратегиях резервного копирования](../../Concepts/backups.md)**.
5. **Тестируйте восстановление** на изолированном стенде не реже раза в квартал; бэкап не считается существующим, пока восстановление не проверено — **[Проверка целостности бэкапов](../../Concepts/backup_validation.md)**.
6. **Мониторинг:** алерт не на «ошибку бэкапа», а на «отсутствие успешного бэкапа за N часов».
7. **Снижайте нагрузку**: `--throttle`, `ionice -c2 -n7 nice +10`.
8. **Не смешивайте варианты MySQL** (Percona Server / MySQL) в одной репликационной топологии при развёртывании реплик из бэкапов.
9. **SSL:** если репликация идёт по SSL, сохраните клиентские SSL-настройки (CA/сертификаты) и укажите их в `CHANGE REPLICATION SOURCE TO` (`SOURCE_SSL_CA` и др.).
10. **Защита бэкапов:** шифрование на лету (`--encrypt=AES256`) и хранение ключей отдельно — **[Безопасность бэкапов](../../Concepts/backup_security.md)**.

## Дополнительная информация

- **Связанные файлы:** `gtid.md`, `gtid_practical.md`, `setup.md`, `setup_guide.md`, `lag_monitoring.md`, `failover_switchover.md`, `consistency_checks.md`, `../backup_and_recovery/xtrabackup.md`, `../backup_and_recovery/automation.md`, `../backup_and_recovery/pitr.md`, `binlog_management.md`
- **Инструменты:** Percona XtraBackup (официальная документация). В файле описаны практические рабочие сценарии без cloud-деталей.
- **Рекомендация:** для production тестировать процедуру восстановления на стенде минимум раз в квартал.

### Внешние ресурсы

- [How to set up a replica for replication in 6 simple steps with Percona XtraBackup](https://docs.percona.com/percona-xtrabackup/8.4/set-up-replication.html)
- [How to create a new (or repair a broken) GTID-based replica](https://docs.percona.com/percona-xtrabackup/8.4/create-gtid-replica.html)
- [Index of files created by Percona XtraBackup](https://docs.percona.com/percona-xtrabackup/8.4/xtrabackup-files.html)
- [The xtrabackup command-line options](https://docs.percona.com/percona-xtrabackup/8.4/xtrabackup-option-reference.html)
- [CHANGE REPLICATION SOURCE TO Statement (MySQL 8.4)](https://dev.mysql.com/doc/refman/8.4/en/change-replication-source-to.html)
