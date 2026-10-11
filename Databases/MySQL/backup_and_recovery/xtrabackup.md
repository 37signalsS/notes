# Percona XtraBackup — физические бэкапы MySQL

**Актуально для:** MySQL 5.7 / 8.0 / 8.4 LTS, XtraBackup 8.0.35-36, XtraBackup 8.4 LTS

## Определения

**Percona XtraBackup** — промышленный стандарт создания «горячих» физических бэкапов InnoDB. Копирует страницы данных без остановки сервера и без блокировок записи на уровне транзакций. Финальный релиз ветки 8.0 — **8.0.35-36** (июнь 2026). Ветка 8.4 LTS — **8.4.0-6** (июнь 2026).

**Физический бэкап (Physical Backup)** — копирование файлов данных InnoDB на уровне страниц. Обеспечивает максимальную скорость создания и восстановления (минимальный RTO), но гранулярность ограничена уровнем таблиц.

**xbstream** — формат потока Percona для архивации файлов бэкапа. Поддерживает сжатие, шифрование и многопоточную запись.

**Throttle** — ограничение скорости копирования страниц InnoDB для снижения влияния на Production-нагрузку.

**Инкрементальный бэкап (Incremental Backup)** — копирование только страниц, изменённых между LSN (Log Sequence Number) двух точек снимка.

**Восстановление таблицы (Table Restore)** — извлечение отдельной таблицы из полного физического бэкапа через `--export` + `IMPORT TABLESPACE`.

**RTO (Recovery Time Objective)** — максимально допустимое время простоя. XtraBackup даёт минимальный RTO за счёт физического копирования файлов.

**RPO (Recovery Point Objective)** — максимально допустимая потеря данных. Определяется частотой бэкапов и сроком хранения бинарных логов.

## Основные концепции

### Как работает XtraBackup

XtraBackup использует комбинацию трёх механизмов InnoDB:

1. **Копирование redo log** — потоковое чтение активныхredo-записей в файл `xtrabackup_logfile`.
2. **Копирование данных** — чтение страниц InnoDB на момент начала снимка.
3. **Применение redo log** — фаза `--prepare` накладывает накопленныеredo-записи на скопированные страницы, приводя данные к консистентному состоянию.

На старте XtraBackup записывает начальный LSN. Если между началом и концом копирования данные изменятся, XtraBackup обнаружит несоответствие LSN на этапе `--prepare` и вернёт ошибку.

### Жизненный цикл бэкапа

1. **Pre-flight проверки:** свободное место, валидность учетных данных, binlog включён.
2. **Создание бэкапа:** физическое копирование страниц InnoDB.
3. **Верификация:** проверка LSN и integrity-check.
4. **Сжатие/шифрование:** уменьшение объёма и защита данных.
5. **Трансфер:** отправка на удалённое хранилище.
6. **Ротация:** удаление устаревших копий.
7. **Уведомление:** отправка статуса в мониторинг.

### Версионная совместимость

| Сборка XtraBackup | MySQL сервер | Примечания |
| :--- | :--- | :--- |
| 8.0.35-36 | 8.0.x | Финальный релиз ветки 8.0 |
| 8.4.0-6 | 8.4.x | Актуальная LTS-ветка |
| 2.4.x | 5.7.x | Legacy-ветка, EOL |

**Правило:** major.minor версии инструмента и сервера должны совпадать. Patch-версии могут отличаться.

### Ограничения XtraBackup

- **InnoDB only:** MyISAM таблицы копируются, но не защищены от изменений во время бэкапа. Используйте `FLUSH TABLES WITH READ LOCK` для их консистентности.
- **Совместимость major.minor:** XtraBackup 8.0 не работает с MySQL 8.4.
- **INSTANT ADD/DROP COLUMN:** В MySQL 8.0.12–8.0.28 может привести к ошибкам XtraBackup. Обновите MySQL до 8.0.29+ или используйте XtraBackup 8.0.35-xx.
- **Табличные пространства:** Экспорт/импорт требует одинакового keyring-бэкенда на источнике и цели.
- **MyISAM:** Требует явной блокировки `FLUSH TABLES WITH READ LOCK` или `--lock-all-tables`.

### MariaDB: mariadb-backup

`mariadb-backup` — форк XtraBackup, оптимизированный под MariaDB. Поддерживает MyRocks, Aria и атомарные бинарные логи. Используйте его для MariaDB вместо XtraBackup.

## Практические сценарии

### Сценарий 1: Установка и верификация

#### Debian/Ubuntu

```bash
# Добавление репозитория Percona
sudo apt-get install percona-release
sudo percona-release enable pxb-84-lts

# Установка XtraBackup 8.4 LTS
sudo apt-get install percona-xtrabackup-84

# Проверка версии
xtrabackup --version
# → xtrabackup version 8.4.0-1 based on MySQL server 8.4.0
```

#### RHEL/CentOS/Rocky

```bash
# Добавление репозитория
sudo yum install https://repo.percona.com/yum/percona-release-latest.noarch.rpm
sudo percona-release enable pxb-84-lts

# Установка
sudo yum install percona-xtrabackup-84

# Проверка версии
xtrabackup --version
```

### Сценарий 2: Базовый полный бэкап

```bash
xtrabackup --backup \
  --target-dir=/backups/full_$(date +%F_%H%M) \
  --user=backup_user \
  --password='StrongPassword!2024'
# → ... completed OK!
```

**Проверка:** Файл `xtrabackup_checkpoints` содержит начальный и конечный LSN. Если они совпадают — бэкап полный.

### Сценарий 3: Бэкап с ограничением нагрузки

```bash
# Ограничение I/O: 100 страниц/сек (16 КБ каждый ≈ 1.6 МБ/с)
xtrabackup --backup \
  --target-dir=/backups/full_$(date +%F) \
  --user=backup_user --password='StrongPassword!2024' \
  --throttle=100
```

**Для Production:** комбинируйте с `ionice -c2 -n7` и `nice +10` для минимизации влияния на CPU и I/O.

```bash
ionice -c2 -n7 nice +10 xtrabackup --backup ...
```

### Сценарий 4: Стриминг через SSH (без промежуточного файла)

```bash
xtrabackup --backup --stream=xbstream \
  --user=backup_user --password='StrongPassword!2024' | \
ssh user@remote_host "mkdir -p /data/backups/full_$(date +%F_%H%M) && \
  xbstream -x -C /data/backups/full_$(date +%F_%H%M)"
```

**Преимущество:** Данные не записываются на локальный диск сервера бэкапа. Идеально при нехватке места.

### Сценарий 5: Бэкап со сжатием (Zstd)

```bash
xtrabackup --backup \
  --compress --compress-threads=4 --compress-zstd-level=3 \
  --target-dir=/backups/full_zstd_$(date +%F_%H%M) \
  --user=backup_user --password='StrongPassword!2024'

# Восстановление сжатого бэкапа: распаковка перед --prepare
xtrabackup --decompress --target-dir=/backups/full_zstd_$(date +%F_%H%M)
xtrabackup --prepare --target-dir=/backups/full_zstd_$(date +%F_%H%M)
```

**Параметры сжатия:**
- `--compress-threads` — количество потоков сжатия. Оптимально: `(CPU ядра / 2)`.
- `--compress-zstd-level` — уровень сжатия Zstd (0–19). Уровень 3 — баланс скорость/размер. Уровень 15+ — максимальное сжатие, но медленно.
- `--compress` без указания алгоритма использует `quicklz` (устаревший). Всегда указывайте `--compress-zstd-level` для Zstd.

### Сценарий 6: Шифрование на лету

```bash
# Генерация ключа (256 бит)
openssl rand -base64 32 > /etc/mysql/xtrabackup_key.key
chmod 600 /etc/mysql/xtrabackup_key.key

# Бэкап с шифрованием AES256
xtrabackup --backup \
  --target-dir=/backups/full_enc_$(date +%F_%H%M) \
  --user=backup_user --password='StrongPassword!2024' \
  --encrypt=AES256 --encrypt-key-file=/etc/mysql/xtrabackup_key.key

# Дешифрование перед --prepare
xtrabackup --decrypt --target-dir=/backups/full_enc_$(date +%F_%H%M) \
  --encrypt-key-file=/etc/mysql/xtrabackup_key.key
xtrabackup --prepare --target-dir=/backups/full_enc_$(date +%F_%H%M)
```

**Важно:** Ключ шифрования не храните вместе с бэкапом. Храните его в отдельном контуре (HashiCorp Vault, sealed-secrets, внешний носитель).

### Сценарий 7: Инкрементальный бэкап

Минимизирует объём данных, копируя только изменённые страницы InnoDB между LSN.

```bash
# 1. Базовый полный бэкап (Base)
xtrabackup --backup --target-dir=/backups/base \
  --user=backup_user --password='StrongPassword!2024'

# 2. Инкремент 1 (на основе Base)
xtrabackup --backup --target-dir=/backups/inc1 \
  --incremental-basedir=/backups/base \
  --user=backup_user --password='StrongPassword!2024'

# 3. Инкремент 2 (на основе Inc1 — цепочка)
xtrabackup --backup --target-dir=/backups/inc2 \
  --incremental-basedir=/backups/inc1 \
  --user=backup_user --password='StrongPassword!2024'
```

**Принцип:** Каждый инкрементальный бэкап содержит только страницы, изменённые с момента предыдущего. `--incremental-basedir` указывает на ПОСЛЕДНИЙ успешный бэкап (полный или инкрементальный).

### Сценарий 8: Частичный бэкап (partial backup)

Копирует только указанные таблицы или базы. Применяется, когда полный физический бэкап не нужен или не помещается в окно, а целевые таблицы нужно восстановить физически быстро.

**Обязательное условие:** `innodb_file_per_table=ON`. Частичный бэкап работает только с отдельными файлами-таблицами `.ibd`; при выделенных таблицах в общем `ibdata1` выбрать таблицы невозможно.

```sql
SELECT @@innodb_file_per_table;
-- → 1
```

```bash
# По одной таблице
xtrabackup --backup \
  --target-dir=/backups/partial_orders \
  --tables="mydb.orders" \
  --user=backup_user --password='StrongPassword!2024'
# → MySQL binlog position: filename 'binlog.000042', position '1540'
```

```bash
# Список таблиц из файла
printf "mydb.orders\nmydb.order_items\nmydb.customers\n" \
  > /tmp/partial_tables.txt

xtrabackup --backup \
  --target-dir=/backups/partial_set \
  --tables-file=/tmp/partial_tables.txt \
  --user=backup_user --password='StrongPassword!2024'
# → Completed backup!
```

```bash
# Несколько баз целиком
xtrabackup --backup \
  --target-dir=/backups/partial_dbs \
  --databases="mydb mydb_analytics" \
  --user=backup_user --password='StrongPassword!2024'

# То же через файл
printf "mydb\nmydb_analytics\n" > /tmp/partial_dbs.txt
xtrabackup --backup \
  --target-dir=/backups/partial_dbs \
  --databases-file=/tmp/partial_dbs.txt \
  --user=backup_user --password='StrongPassword!2024'
```

Восстановление частичного бэкапа принципиально отличается от полного:

```bash
# 1. Подготовка
xtrabackup --prepare --target-dir=/backups/partial_orders
# → Completed preparing!

# 2. Частичный бэкап НЕЛЬЗЯ скопировать напрямую поверх работающего datadir.
#    Его таблицы переносятся вручную через EXPORT/IMPORT:
#    1) копировать .ibd и экспортировать определения таблиц
cp /backups/partial_orders/mydb/orders.ibd /var/lib/mysql/mydb/orders.ibd
cp /backups/partial_orders/mydb/orders.cfg /var/lib/mysql/mydb/orders.cfg 2>/dev/null

# 3. На целевом сервере — остановленный, без этой таблицы
mysql -e "ALTER TABLE mydb.orders DISCARD TABLESPACE;"

# 4. Импорт с корректным владельцем
chown mysql:mysql /var/lib/mysql/mydb/orders.ibd
mysql -e "ALTER TABLE mydb.orders IMPORT TABLESPACE;"
# → (без вывода при успехе)

# 5. Проверка
mysql -e "CHECK TABLE mydb.orders EXTENDED;"
# → mydb.orders  check  status  OK
```

**Ограничения частичного бэкапа:**

| Ограничение | Следствие |
| :--- | :--- |
| Нельзя использовать `--copy-back` | Частичная копия не является полной копией datadir; `cp -a` поверх работающей базы разрушит её |
| Нужны `DISCARD/IMPORT TABLESPACE` | Ручная процедура, не автоматизируется в одну команду |
| Требуется `innodb_file_per_table=ON` | При `OFF` выбрать таблицы нельзя |
| Таблицы-разделители, федеративные движки | Не копируются — нет отдельного `.ibd` |
| Внешние таблицы | Не копируются |

> **Практический вывод:** частичный бэкап — инструмент для разовых операций (миграция одной большой таблицы, восстановление после инцидента), а не схема регулярного резервного копирования. Для регулярного бэкапа используйте полный `XtraBackup` или `mysqldump` с `--databases`.

### Сценарий 9: История бэкапов (`--history`)

XtraBackup ведёт собственную историю бэкапов в таблице `xtrabackup_history` базы `PERCONA_SCHEMA`. Это позволяет со временем отказаться от ручного хранения имён каталогов инкрементов — утилита сама находит предыдущий.

**Обязательные условия:**

1. Таблица `PERCONA_SCHEMA.XTRABACKUP_HISTORY` должна существовать и быть доступна пользователю бэкапа (создаётся автоматически при первой записи, либо создаётся вручную).
2. Все бэкапы в цепочке выполняются **с одним и тем же** UUID — он задаётся через `--uuid`.

```sql
-- Проверка наличия таблицы истории
SELECT * FROM PERCONA_SCHEMA.XTRABACKUP_HISTORY LIMIT 5\G
-- → stmtexec_time: 2026-10-03 03:00:12
-- → stmtexec_time: 2026-10-03 03:00:13
-- → name: xtrabackup_checkpoints
-- → name: xtrabackup_binlog_info
```

```bash
# 1. Генерируем UUID один раз для всей цепочки и сохраняем
UUID=$(uuidgen)
echo "$UUID" > /etc/mysql/xtrabackup_chain_uuid
# → 6ba7b810-9dad-11d1-80b4-00c04fd430c8
```

```bash
# 2. Полный бэкап с UUID и историей
xtrabackup --backup \
  --target-dir=/backups/chain \
  --uuid="$UUID" --history
# → Completed backup!
```

```bash
# 3. Инкремент — history и uuid те же, incremental-basedir указывает на историю
xtrabackup --backup \
  --target-dir=/backups/chain_inc \
  --uuid="$UUID" --history \
  --incremental-basedir=BACKUP_HISTORY
# → Completed backup!
```

**Значение `BACKUP_HISTORY`:** специальная строка вместо пути — XtraBackup читает последний успешный бэкап из `PERCONA_SCHEMA.XTRABACKUP_HISTORY` и использует его как основу. Путь указывать вручную больше не нужно.

```bash
# Смотрим, что записалось в историю
mysql -N -B -e "SELECT name, uuid, tool_version FROM PERCONA_SCHEMA.XTRABACKUP_HISTORY\G"
# → name: full
# → uuid: 6ba7b810-9dad-11d1-80b4-00c04fd430c8
# → name: inc1
-- → uuid: 6ba7b810-9dad-11d1-80b4-00c04fd430c8
```

**Ограничения `--history`:**

| Ограничение | Пояснение |
| :--- | :--- |
| Не работает с `--stream` | Потоковый режим не даёт каталога, куда можно записать метаданные |
| Требует `--uuid` | Без явного UUID история не свяжет инкременты с полным бэкапом |
| Таблица истории должна пережить восстановление | При восстановлении на «чистый» инстанс история теряется, если её не перенести |
| `--incremental-history-name` — только для `--history` | Не комбинируется с `--history` в одном запуске иначе, чем через UUID |

```bash
# Указать конкретный бэкап из истории по имени
xtrabackup --backup \
  --target-dir=/backups/chain_inc2 \
  --uuid="$UUID" --history \
  --incremental-history-name=inc1 \
  --incremental-basedir=BACKUP_HISTORY
# → Completed backup!
```

**Восстановление с использованием истории:**

```bash
# --apply-log-only — быстрая подготовка без полной проверки
xtrabackup --prepare --target-dir=/backups/chain --apply-log-only
xtrabackup --prepare --target-dir=/backups/chain_inc --apply-log-only

# Итоговое объединение
xtrabackup --prepare \
  --target-dir=/backups/chain \
  --apply-log-only \
  --incremental-basedir=/backups/chain_inc
# → Completed preparing!
```

> **Важно:** при восстановлении **обязательно** переносите таблицу `PERCONA_SCHEMA.XTRABACKUP_HISTORY` на новый инстанс, иначе следующий инкремент не найдёт основу и цепочка разорвётся. Идентификатор `uuid` из истории должен совпадать с `--uuid` будущих бэкапов.

### Сценарий 10: Восстановление из полного + инкрементальных бэкапов

```bash
# 1. Подготовка базового бэкапа (apply log only — без отката redo)
xtrabackup --prepare --apply-log-only --target-dir=/backups/base

# 2. Применение первого инкремента
xtrabackup --prepare --apply-log-only --target-dir=/backups/base \
  --incremental-dir=/backups/inc1

# 3. Применение второго инкремента (последний — БЕЗ --apply-log-only)
xtrabackup --prepare --target-dir=/backups/base \
  --incremental-dir=/backups/inc2

# 4. Копирование данных в каталог MySQL
systemctl stop mysql
rm -rf /var/lib/mysql/*
xtrabackup --copy-back --target-dir=/backups/base \
  --datadir=/var/lib/mysql
chown -R mysql:mysql /var/lib/mysql
systemctl start mysql
```

**Важно:** Последний шаг `--prepare` выполняется **без** флага `--apply-log-only`. Это позволяет InnoDB выполнить финальный откат незавершённых транзакций (Rollback), обеспечивая консистентность.

**Восстановление инкрементов:** Инкременты применяются строго последовательно: Base → Inc1 → Inc2. Пропуск шага приведёт к ошибке LSN mismatch.

### Сценарий 11: Восстановление конкретной таблицы из физического бэкапа

Позволяет избежать полного восстановления терабайтной БД ради одной таблицы.

```bash
# 1. Подготовка бэкапа с экспортом метаданных
xtrabackup --prepare --export --target-dir=/backups/base

# 2. На целевом сервере (может быть другим инстансом):
# Удалите данные таблицы и отсоедините tablespace
mysql> ALTER TABLE mydb.mytable DISCARD TABLESPACE;

# 3. Скопируйте файлы из бэкапа в каталог данных MySQL
cp /backups/base/mydb/mytable.ibd /var/lib/mysql/mydb/mytable.ibd
cp /backups/base/mydb/mytable.cfg /var/lib/mysql/mydb/mytable.cfg
chown mysql:mysql /var/lib/mysql/mydb/mytable.*

# 4. Подключите tablespace
mysql> ALTER TABLE mydb.mytable IMPORT TABLESPACE;
```

**Ограничения:**
- Таблица должна принадлежать движку InnoDB.
- Для MyISAM потребуется полное восстановление или логический дамп с фильтрацией.
- Целевой сервер должен иметь ту же major-версию MySQL, что и источник.
- При использовании `INSTANT ADD/DROP COLUMN` (MySQL 8.0.12+) файл `.cfg` может не содержать актуальную схему — обновите MySQL до 8.0.29+.

### Сценарий 12: Параллельное копирование при восстановлении

```bash
# Копирование файлов данных параллельно (ускоряет --copy-back)
xtrabackup --copy-back \
  --target-dir=/backups/base \
  --datadir=/var/lib/mysql \
  --parallel=4
```

**Примечание:** `--parallel` работает только для пользовательских табличных пространств. Системные табличные пространства (redo log, system tablespace) копируются в основном потоке.

### Сценарий 13: Верификация бэкапа (check-tables)

В XtraBackup 8.4.0-6+ доступна встроенная проверка B-Tree индексов InnoDB:

```bash
# Проверка таблиц на предмет повреждений B-Tree
xtrabackup --check-tables \
  --target-dir=/backups/full_latest \
  --user=backup_user --password='StrongPassword!2024'
```

**Важно:** Проверка выполняется в read-only режиме и не модифицирует данные бэкапа. Возвращает ненулевой exit-code при обнаружении повреждений.

## Управление ресурсами и надёжность

### Приоритеты процесса

```bash
# Понижение приоритета CPU и I/O
ionice -c2 -n7 nice +10 xtrabackup --backup ...

# Ограничение дискового I/O через --throttle
xtrabackup --backup ... --throttle=100
```

### Использование памяти при prepare

```bash
# Увеличение буфера для ускорения --prepare
xtrabackup --prepare \
  --use-memory=4G \
  --target-dir=/backups/base
```

**Рекомендация:** `--use-memory` ≈ размеру `innodb_buffer_pool_size` на сервере бэкапа. Достаточно 25–50% от общего объёма данных.

### Хранение метаданных

Файлы метаданных XtraBackup должны храниться вместе с бэкапом:

- `xtrabackup_binlog_info` — позиция binlog на момент создания бэкапа.
- `xtrabackup_checkpoints` — начальный и конечный LSN.
- `xtrabackup_logfile` — накопленные redo-записи для prepare.

## Диагностика и устранение неисправностей

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **`Error: redo log size mismatch`** | Несовместимость версий xtrabackup и mysqld | Версии должны совпадать по major.minor |
| **`Log sequence number (LSN) mismatch`** | Базовый бэкап повреждён | Удалите инкремент и сделайте новый базовый бэкап |
| **`last checkpoint LSN is greater`** | Повреждение redo-лога | Проверьте целостность диска, сделайте новый полный бэкап |
| **`Found tables with row versions due to INSTANT ADD/DROP`** | MySQL 8.0.12–8.0.28 | Обновите MySQL или используйте XtraBackup 8.0.35-xx |
| **`code=1` при `--copy-back`** | Неверные права или нехватка места | Проверьте `chown` и `df -h` |
| **`No space left on device`** | Нехватка места | Используйте стриминг (`--stream=xbstream`) или сжатие |
| **`xtrabackup: [ERROR] unknown variable`** | Конфликт опций конфигурации | Добавьте `--no-defaults` к команде |
| **`ERROR 3185 (Can't find master key from keyring)`** | Keyring недоступен при импорте tablespace | Убедитесь в доступности keyring-бэкенда на целевом сервере |

## Бест-практисы

1. **Идемпотентность:** Скрипты бэкапа должны безопасно выполняться повторно. Используйте `flock` или файловые маркеры. Подробнее — в **[Идемпотентность](../../../Concepts/idempotency.md)**.
2. **Минимальные права:** Создайте отдельного пользователя `backup_user` с минимально необходимыми привилегиями. Не используйте `root`.
3. **Верификация:** Минимум раз в квартал проводите полное восстановление в изолированную среду. Документируйте RTO и RPO.
4. **Шифрование:** Шифруйте бэкапы на лету (`xtrabackup --encrypt=AES256`) и в покое. Ключи храните в отдельном контуре.
5. **Мониторинг:** Настраивайте алерты не на «ошибку бэкапа», а на «отсутствие успешного бэкапа за N часов».
6. **Хранение offsite:** Копия бэкапа должна находиться на удалённой площадке. Следуйте правилу 3-2-1-1-0. Подробнее — в **[Стратегии резервного копирования](../../Concepts/backups.md)**.
7. **Ротация логов:** Мониторьте место под binlog. Настройте алерт при заполнении диска более чем на 80%.
8. **Тестируйте PITR регулярно:** Проводите drills восстановления на изолированном инстансе не реже раза в квартал.
9. **Храните метаданные:** Файлы `xtrabackup_binlog_info`, метаданные дампа MySQL Shell и скрипты восстановления должны храниться вместе с бэкапом.
10. **Используйте отложенную репликацию (`SOURCE_DELAY`):** Для защиты от логических ошибок (DROP TABLE, ошибочный UPDATE) можно настроить реплику с задержкой 30–60 минут.

## Дополнительная информация

### См. также

- **[Обзор инструментов бэкапа](./overview.md)** — версии, сравнение методов, бест-практисы.
- **[Point-in-Time Recovery](./pitr.md)** — комбинация физического бэкапа + бинарные логи.
- **[Автоматизация](./automation.md)** — cron-скрипты, ротация, smoke-тестирование.
- **[Проверка целостности бэкапов](../../Concepts/backup_validation.md)** — методы валидации.
- **[Безопасность бэкапов](../../Concepts/backup_security.md)** — шифрование, контроль доступа, хранение ключей.
- **[Управление бинарным логом](../replication/binlog_management.md)** — ротация, архивация, продвинутая PITR.
- **[Идемпотентность](../../../Concepts/idempotency.md)** — защита от дублирующих запусков, паттерны `flock`.

### Внешние ресурсы

- **[Percona XtraBackup Documentation](https://docs.percona.com/percona-xtrabackup/8.0/index.html)**
- **[Percona XtraBackup 8.4 Documentation](https://docs.percona.com/percona-xtrabackup/8.4/index.html)**
- **[MySQL Shell Dump & Load Guide](https://dev.mysql.com/doc/mysql-shell/8.4/en/mysql-shell-utilities-dump-instance-schema.html)**
