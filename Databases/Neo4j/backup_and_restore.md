# Neo4j: Бэкап и восстановление

**Актуально для:** Neo4j 2026.09.x / 5.26.x LTS

> **Редакции.** Онлайн-бэкап и восстановление (`neo4j-admin database backup` / `restore`) —
> возможности Enterprise Edition. Офлайн-бэкап через `neo4j-admin database dump`, проверка
> консистентности `neo4j-admin database check` и миграция формата хранилища доступны в обеих
> редакциях.

Общая теория резервного копирования — RPO, RTO, правило 3-2-1-1-0, уровни консистентности —
разобрана в [общих концепциях](../Concepts/backups.md). Здесь только процедуры Neo4j. Эксплуатация
сервера в целом — в [обслуживании](./operations.md), кластерные сценарии — в
[кластеризации](./clustering.md).

## Определения

- **Полный бэкап (Full backup)** — автономный артефакт `.backup`, содержащий все store-файлы базы на момент создания. Не зависит от других бэкапов.
- **Дифференциальный бэкап (Differential backup)** — артефакт, хранящий только дельту транзакционных журналов с момента последнего полного бэкапа. Несамостоятелен: требует родительский полный бэкап в той же директории.
- **Транзакционный журнал (Transaction log / WAL)** — последовательность записей всех закоммиченных транзакций. Основа для point-in-time recovery и дифференциальных бэкапов.
- **TX ID (Transaction ID)** — монотонно возрастающий идентификатор транзакции. Используется для адресации точек восстановления (`--restore-until`).
- **Метаданные (Metadata)** — пользователи, роли, привилегии и правила аутентификации из базы `system`. Включаются в бэкап через `--include-metadata`.
- **Pagecache** — кэш страниц Neo4j, используемый при чтении store-файлов во время бэкапа. Размер задаётся через `--pagecache`.
- **Консистентность (Consistency)** — свойство бэкапа, при котором восстановленная база проходит `neo4j-admin database check` без ошибок. Онлайн-бэкап даёт согласованный срез без остановки БД.

## Архитектура бэкапа

### Как работает онлайн-бэкап

Онлайн-бэкап в Neo4j Enterprise использует механизм **копирования store-файлов с одновременным отслеживанием транзакционных журналов**:

1. **Фаза копирования** — `neo4j-admin` читает store-файлы (`neostore.*`, индексы, схемы) через pagecache, не блокируя запись. Параллельно запоминает позицию в транзакционном журнале (LSN/TX ID) на момент старта.
2. **Фаза дожима (catch-up)** — после копирования файлов инструмент дочитывает все транзакции, закоммиченные пока шло копирование, из транзакционных журналов. Это гарантирует, что артефакт представляет согласованное состояние на момент **завершения** бэкапа, а не его начала.
3. **Запись артефакта** — собранные файлы пишутся в `--to-path` (сжатые по умолчанию). Если указано `--temp-path`, сборка происходит там, затем атомарно перемещается в целевую директорию.

> **Важно:** Бэкап согласован по построению — это не crash-consistent снапшот, а application-consistent срез. Neo4j не требует `fsync`/`quiesce` перед стартом, так как механизм дожима журналов закрывает разницу.

### Дифференциальная цепочка

- Первый бэкап в пустой директории — всегда **полный** (`FULL=true` в `--inspect-path`).
- Последующие запуски без `--type=full` создают **дифференциальные** артефакты (`FULL=false`).
- Каждый дифференциальный хранит диапазон `LOWEST TX` – `HIGHEST TX` и ссылается на родительский полный.
- Восстановление требует **всю цепочку в одной директории** — разнос полных и дифференциальных по разным папкам ломает восстановление.

### Удалённый бэкап (Remote backup)

При включённом `server.backup.listen_address` (порт 6362) клиент `neo4j-admin` подключается к кластеру и стримит store-файлы + журналы **на сторону клиента**. На сервере-источнике временные копии не создаются — нагрузка на диск минимальна, сеть становится узким местом. Поддерживается перебор адресов `--from=host1:6362,host2:6362` для отказоустойчивости.

## Выбор режима

| | `neo4j-admin database dump` | `neo4j-admin database backup` |
| :--- | :--- | :--- |
| **Режим БД** | Офлайн (база остановлена) | Онлайн (база работает) |
| **Редакция** | Community и Enterprise | Только Enterprise |
| **Формат** | Один файл `.dump` | Артефакт `.backup` + цепочка дифференциальных |
| **Метаданные** | Нет | Пользователи и роли (RBAC) через `--include-metadata` |
| **Инспекция** | Нет | `--inspect-path` |
| **Потеря данных** | Всё, что не попало в дамп | Согласованный срез на момент бэкапа |
| **Проверка** | `neo4j-admin database check --from-path=...` | То же |

Офлайн-дамп — это остановленная база. Он консистентен по построению, но недоступен во время
создания. Онлайн-бэкап согласован и не требует остановки, поэтому он и является production-вариантом.

> Все команды `neo4j-admin` запускаются от пользователя `neo4j` — иначе нарушатся права на файлы,
> и последующая операция restore или start не сможет их прочитать.

## Онлайн-бэкап

Синтаксис (Enterprise Edition, база работает):

```bash
# Full or differential backup, type is auto-detected by default
neo4j-admin database backup --to-path=/backups/neo4j neo4j

# Force a full backup even if a newer differential exists
neo4j-admin database backup --type=full --to-path=/backups/neo4j neo4j
```

```bash
# Create the backup directory owned by the neo4j user first
sudo -u neo4j mkdir -p /backups/neo4j
```

Имя базы передаётся **позиционным аргументом** в конце. По умолчанию тип `AUTO`: если в целевой
папке уже есть бэкап, команда попытается построить дифференциальный, и только при
недоступности нужных журналов откатится в полный.

**Цепочка бэкапов.** Дифференциальные артефакты несамостоятельны: они хранят только дельту
транзакционных журналов и опираются на родительский артефакт. Восстановление идёт по цепочке
целиком, поэтому **полный бэкап должен существовать в той же папке**. Положив полный бэкап в
одну директорию, а дифференциальные — в другую, вы получите не восстановление, а ошибку
`not found`.

Инспекция артефактов перед восстановлением — обязательный шаг, а не опция:

```bash
neo4j-admin database backup --inspect-path=/backups/neo4j
```

```
|                                 FILE | DATABASE |                DATABASE ID |                TIME |  FULL | COMPRESSED | LOWEST TX | HIGHEST TX |
| file:///backups/neo4j/neo4j-2026-06-29T13-46-27.backup |    neo4j | c8368b24-55e2-474d-bb41-75657f5bfcde | 2026-06-29T13:46:27 |  true |       true |         1 |         11 |
| file:///backups/neo4j/neo4j-2026-06-29T13-50-45.backup |    neo4j | c8368b24-55e2-474d-bb41-75657f5bfcde | 2026-06-29T13:50:45 | false |       true |        12 |         14 |
| file:///backups/neo4j/neo4j-2026-06-29T13-51-33.backup |    neo4j | c8368b24-55e2-474d-bb41-75657f5bfcde | 2026-06-29T13:51:33 | false |       true |        15 |         18 |
```

Колонка `FULL` показывает, где начинается цепочка; `LOWEST TX` / `HIGHEST TX` — диапазон
идентификаторов транзакций. Восстановление с `--from-path`, указывающим на второй артефакт,
даст базу с последней транзакцией `14`, а не `18`.

Метаданные пользователей и ролей включаются в бэкап по умолчанию:

```bash
# Include users, roles and auth rules
neo4j-admin database backup --to-path=/backups/neo4j --include-metadata=all neo4j
```

С 2025.10 `--include-metadata` принимает фильтр: `--include-metadata=users=alice,bob` включит
только указанных пользователей, `roles` — только роли, `none` — ничего.

**Удалённый бэкап.** Если на сервере разрешён `server.backup.listen_address` (порт 6362), бэкап
снимается с другой машины по сети — на источнике не создаётся временных копий store-файлов:

```bash
# Try several servers in order until one responds
neo4j-admin database backup \
  --from=192.168.1.34:6362,192.168.1.35:6362 \
  --to-path=/mnt/backups/neo4j \
  --pagecache=4G \
  neo4j
```

**`--temp-path` — не опция, а необходимость при нехватке места.** Артефакт сначала
собирается во временной директории, и только затем пишется в целевую. Если временная папка
не указана, она создаётся в текущем рабочем каталоге `neo4j-admin` — то есть на системном
разделе, где места почти наверняка нет:

```bash
neo4j-admin database backup --to-path=/backups/neo4j --temp-path=/scratch neo4j
```

## Восстановление

```bash
neo4j-admin database restore [-h] [--expand-commands] [--verbose]
                             [--overwrite-destination[=true|false]]
                             [--source-database[=source-database-name]]
                             --from-path=<path>[,<path>...]
                             [--restore-until=<recovery-criteria>]
                             [--temp-path=<path>]
                             [--to-path-data=<path>] [--to-path-txn=<path>]
                             [<database>]
```

Восстановление в **новую** базу — безопасный путь по умолчанию:

```bash
# 1. Restore into a new database name
neo4j-admin database restore \
  --from-path=/backups/neo4j/neo4j-2026-06-29T13-51-33.backup \
  mydatabase

# 2. Create it in the system database
```

```cypher
CREATE DATABASE mydatabase
```

Без этой команды база восстановлена на диск, но не существует для клиентов: `neo4j-admin
database restore` только раскладывает файлы, а регистрирует базу Cypher-команда.

Замена существующей базы требует остановки и явного флага:

```bash
sudo systemctl stop neo4j
neo4j-admin database restore \
  --from-path=/backups/neo4j/neo4j-2026-06-29T13-51-33.backup \
  --overwrite-destination=true neo4j
sudo systemctl start neo4j
```

> `--overwrite-destination=true` **небезопасен в кластере**: у базы есть дополнительное
> состояние репликации, которое не приедет вместе с восстановленными store-файлами и станет
> несогласованным. В кластере восстанавливайте в новую базу.

**Point-in-time recovery.** `--restore-until` применяет журналы из цепочки до точки отката.
Поддерживаются предикаты по идентификатору транзакции и по метке UTC:

```bash
# Recover only transactions committed before this UTC timestamp
neo4j-admin database restore \
  --from-path=/backups/neo4j/neo4j-2026-06-29T13-50-45.backup \
  --restore-until="2026-06-29 13:50:45" \
  mydatabase

# Same, by transaction ID; recovers up to but NOT including tx 123
neo4j-admin database restore \
  --from-path=/backups/neo4j/neo4j-2026-06-29T13-51-33.backup \
  --restore-until=123 \
  mydatabase
```

Обратите внимание на «до, но не включая» в случае с ID: восстановление остановится перед
транзакцией 123, а не на ней.

**Восстановление метаданных.** Пользователи и роли восстанавливаются отдельно — команда
создаёт Cypher-скрипт, который нужно выполнить вручную:

```bash
cat /var/lib/neo4j/data/scripts/mydatabase/restore_metadata.cypher | \
  cypher-shell -u neo4j -p <password> -a localhost -d system \
    --param "database => 'mydatabase'"
```

Потеря этого шага означает потерю пользователей и ролей при полностью целых данных — типичный
случай «восстановился, но войти не могу».

## Проверка консистентности

`neo4j-admin database check` проверяет базу, дамп или полный бэкап. Работающая база не
проверяется — её нужно остановить.

```bash
# Check a restored database
neo4j-admin database check neo4j

# Check a backup or dump without restoring it first
neo4j-admin database check --from-path=/backups/neo4j/neo4j-2026-06-29T13-51-33.backup neo4j

# Report directory, verbose output, more threads
neo4j-admin database check --report-path=/var/log/neo4j-check --threads=8 --verbose neo4j
```

С 2025.09 `--from-path` принимает и файл, и директорию; для директории выбирается самая свежая
цепочка по идентификаторам транзакций.

Ошибок не найдено — чистый выход с кодом `0`, отчёт не создаётся. Найдены — ненулевой код и файл
`inconsistencies-YYYY-MM-DD.HH24.MI.SS.report` в рабочем каталоге либо в `--report-path`.

Дополнительные проверки включаются по необходимости:

| Параметр | По умолчанию | Что проверяет |
| :--- | :--- | :--- |
| `--check-graph` | `true` | Согласованность узлов, связей, свойств, типов и токенов |
| `--check-indexes` | `true` | Содержимое индексов против store |
| `--check-counts` | — | Счётчики; требует `--check-graph` |
| `--check-property-owners` | `false` | Владение свойствами; очень дорого по времени и памяти |
| `--force` | — | Проверка несмотря на ресурсы, более тщательный обход |

> Дифференциальные бэкапы и неразвёрнутые полные бэкапы проверке **не** поддаются. Перед
> `check` цепочку нужно агрегировать в полный восстановленный артефакт.

## Офлайн-бэкап

Доступно в обеих редакциях.

```bash
sudo systemctl stop neo4j

# Dump to a single file
neo4j-admin database dump --to-path=/backups/dumps neo4j

sudo systemctl start neo4j
```

```bash
# Load the dump back, replacing the existing database
sudo systemctl stop neo4j
neo4j-admin database load --from-path=/backups/dumps/neo4j.dump \
  --overwrite-destination=true neo4j
sudo systemctl start neo4j
```

Офлайн-копирование каталога базы — тоже корректный приём при остановленном сервере, но
`dump` предпочтительнее: он самозавершён, переносим между версиями и проверяем
`neo4j-admin database check`.

## Автоматизация

Задача cron от пользователя `neo4j` — полный путь, вывод в отдельный лог, явное кодирование `%`
в crontab:

```bash
# /etc/cron.d/neo4j-backup
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# Run as the neo4j user; the % in date must be escaped as \%
0 2 * * * neo4j /usr/bin/neo4j-admin database backup --to-path=/backups/neo4j --temp-path=/scratch neo4j >> /var/log/neo4j-backup.log 2>&1
```

Что должно быть в cron-задаче помимо самой команды:

- **права `neo4j`** — иначе артефакты будут принадлежать `root` и следующий запуск упадёт;
- **`--temp-path`** на диске с запасом по размеру базы;
- **ротация**: старые артефакты удаляются, потому что полная цепочка со временем съедает диск;
- **проверка кода возврата** — `neo4j-admin` при ошибке пишет в лог, но cron о нём не узнает.

### Рекомендуемая структура автоматизации (SRE-уровень)

На production вместо голого cron используйте обёртку, которая реализует полный цикл:

```bash
#!/usr/bin/env bash
# /usr/local/bin/neo4j-backup-wrapper.sh
set -euo pipefail

BACKUP_DIR="/backups/neo4j"
TEMP_DIR="/scratch"
LOG_FILE="/var/log/neo4j-backup.log"
RETENTION_DAYS=30
MIN_FREE_GB=50

# 1. Pre-backup checks
FREE_GB=$(df -BG "$BACKUP_DIR" | awk 'NR==2 {print $4}' | sed 's/G//')
if [ "$FREE_GB" -lt "$MIN_FREE_GB" ]; then
  echo "$(date) CRITICAL: Only ${FREE_GB}GB free on $BACKUP_DIR, need ${MIN_FREE_GB}GB" | tee -a "$LOG_FILE"
  exit 1
fi

# 2. Run backup
echo "$(date) Starting backup..." | tee -a "$LOG_FILE"
if ! /usr/bin/neo4j-admin database backup \
     --to-path="$BACKUP_DIR" \
     --temp-path="$TEMP_DIR" \
     --pagecache=4G \
     neo4j >> "$LOG_FILE" 2>&1; then
  echo "$(date) BACKUP FAILED" | tee -a "$LOG_FILE"
  exit 1
fi

# 3. Verify backup integrity
echo "$(date) Verifying backup..." | tee -a "$LOG_FILE"
if ! /usr/bin/neo4j-admin database check --from-path="$BACKUP_DIR" neo4j >> "$LOG_FILE" 2>&1; then
  echo "$(date) BACKUP CHECK FAILED" | tee -a "$LOG_FILE"
  exit 1
fi

# 4. Inspect chain (ensure FULL + differentials present)
/usr/bin/neo4j-admin database backup --inspect-path="$BACKUP_DIR" >> "$LOG_FILE" 2>&1

# 5. Retention: remove chains older than RETENTION_DAYS
# Find full backups older than retention, remove them and their differentials
find "$BACKUP_DIR" -name "*.backup" -type f -mtime +"$RETENTION_DAYS" | while read -r full_backup; do
  # Extract DB ID and timestamp to find related differentials
  db_id=$(basename "$full_backup" | cut -d'-' -f2- | cut -d'.' -f1)
  # Remove all backups with same DB ID and older/equal timestamp
  find "$BACKUP_DIR" -name "*${db_id}*.backup" -type f -mtime +"$RETENTION_DAYS" -delete
done

# 6. Push metrics (example for Prometheus Pushgateway)
# curl -X POST --data "neo4j_backup_last_success_timestamp_seconds $(date +%s)" http://pushgateway:9091/metrics/job/neo4j-backup

echo "$(date) Backup completed successfully" | tee -a "$LOG_FILE"
```

**Ключевые элементы SRE-автоматизации:**
- **Dead Man's Switch** — алерт на отсутствие успешного бэкапа > 24h (не на ошибку, а на отсутствие успеха).
- **Метрики** — `backup_last_success_timestamp`, `backup_duration_seconds`, `backup_size_bytes`, `backup_chain_length`.
- **Валидация в том же цикле** — бэкап не считается успешным, пока не пройден `check`.
- **Ротация по цепочкам** — удаляем полный бэкап вместе со всеми его дифференциальными, а не по отдельным файлам.
- **Проверка места заранее** — предотвращает падение на этапе сборки артефакта.

Проверка результата (быстрый чек без полного скрипта):

```bash
# Inspect the directory; FULL and HIGHEST TX must advance between runs
neo4j-admin database backup --inspect-path=/backups/neo4j

# Fail the job if the backup is inconsistent
neo4j-admin database check --from-path=/backups/neo4j neo4j
```

## Docker: бэкап через volume

Остановленный контейнер гарантирует согласованный снимок. Работающий — нет, даже при
`tar` по volume.

```bash
# Consistent: stop, archive, start
docker stop neo4j
docker run --rm -v neo4j_data:/data:ro -v "$(pwd)":/backup \
  ubuntu tar czf /backup/neo4j-$(date +%F).tar.gz -C /data .
docker start neo4j
```

```bash
# Restore
docker run --rm -v neo4j_data:/data -v "$(pwd)":/backup \
  ubuntu sh -c 'rm -rf /data/* && tar xzf /backup/neo4j-2026-09-30.tar.gz -C /data'
```

Копирование только подкаталога `data/databases/neo4j` **без** `data/transactions` даёт
неконсистентную базу: незавершённые транзакции из журналов не будут отменены, а часть данных
может остаться в WAL. В `tar` включайте весь `/data`.

### Rootless-контейнеры (Podman / Docker rootless)

При использовании rootless-контейнеров файлы volume принадлежат пользователю внутри контейнера (обычно UID 7474 для официального образа). Для бэкапа от хоста:

```bash
# Consistent: stop, archive, start
podman stop neo4j
podman run --rm -v neo4j_data:/data:ro -v "$(pwd)":/backup \
  ubuntu tar czf /backup/neo4j-$(date +%F).tar.gz -C /data .
podman start neo4j
```

Владелец файлов в архиве будет UID 7474. При restore на том же хосте/пользователе права сохранятся. При миграции на другой хост — используйте `tar --numeric-owner` или `chown` после распаковки.

## Проверка восстановления

Бэкап, который не восстанавливали, — это гипотеза. Регулярное восстановление в изолированное
окружение — единственный способ узнать, что он рабочий, до того, как он понадобится:

1. Поднять отдельный сервер на изолированном хосте или в отдельной сети.
2. Восстановить бэкап по процедуре выше.
3. Прогнать `neo4j-admin database check` на восстановленной базе.
4. Сверить контрольные суммы или количество узлов/связей с исходной базой.
5. Проверить, что метаданные восстановлены и вход работает.
6. Уничтожить окружение.

Периодичность — не реже, чем максимальный интервал бэкапов: если последний бэкап никогда не
проверялся, весь предшествующий период прошёл без рубежа.

## Устранение неисправностей (Troubleshooting)

### Бэкап завершается ошибкой "No space left on device"

**Симптомы:** `neo4j-admin database backup` падает с ошибкой нехватки места, хотя в `--to-path` свободно много гигабайт.

**Причина:** По умолчанию временная директория создаётся в текущем рабочем каталоге процесса (обычно `/var/lib/neo4j` или домашняя директория пользователя), а не в `--to-path`. Системный раздел заполняется до сбора артефакта.

**Решение:** Всегда задавайте `--temp-path` на диске с запасом ≥ размера базы:
```bash
neo4j-admin database backup --to-path=/backups/neo4j --temp-path=/scratch neo4j
```

### Ошибка "not found" при восстановлении дифференциального бэкапа

**Симптомы:** `neo4j-admin database restore --from-path=/backups/neo4j/diff.backup ...` выдает `not found` или `missing parent backup`.

**Причина:** Полный бэкап и дифференциальные лежат в разных директориях, либо полный бэкап был удален retention-политикой.

**Решение:**
1. Проверьте `--inspect-path` — колонка `FULL` должна показывать `true` для первого файла цепочки.
2. Держите полную цепочку в одной директории.
3. При ротации удаляйте цепочки целиком (полный + все его дифференциальные), а не отдельные файлы.

### Восстановленная база не запускается / "Database not found"

**Симптомы:** После `neo4j-admin database restore` база не видна в `SHOW DATABASES`, клиенты не подключаются.

**Причина:** `restore` только раскладывает файлы на диск. Базу нужно зарегистрировать в `system` через Cypher:
```cypher
CREATE DATABASE mydatabase;
```

**Решение:** Всегда выполняйте `CREATE DATABASE` после restore в новую базу. Для перезаписи существующей — используйте `--overwrite-destination=true` (только в standalone, не в кластере).

### "Could not acquire lock" / права доступа к файлам

**Симптомы:** Ошибки прав доступа при старте Neo4j после restore или при следующем бэкапе.

**Причина:** Команды `neo4j-admin` запущены не от пользователя `neo4j` (например, из `root` cron). Файлы созданы с владельцем `root:root`, процесс Neo4j (user `neo4j`) не может их читать.

**Решение:** Всегда запускайте `neo4j-admin` от пользователя `neo4j`:
```bash
sudo -u neo4j neo4j-admin database backup ...
# или в cron:
0 2 * * * neo4j /usr/bin/neo4j-admin database backup ...
```

### Point-in-time recovery останавливается раньше ожидаемой точки

**Симптомы:** `--restore-until="2026-06-29 13:50:45"` восстанавливает базу до более ранней транзакции.

**Причины:**
1. В цепочке бэкапов нет транзакций до указанной точки (журналы обрезаны retention'ом).
2. При использовании TX ID: `--restore-until=123` восстанавливает **до, но не включая** транзакцию 123.

**Решение:**
1. Проверьте `--inspect-path` — колонка `HIGHEST TX` последнего артефакта должна покрывать целевую точку.
2. Согласуйте `dbms.tx_log.rotation.retention_policy` с требуемым окном PITR.
3. Для timestamp-указывайте момент **после** последней нужной транзакции.

### Метаданные не восстановились — "Authentication failed"

**Симптомы:** База восстановлена, данные целы, но вход под любым пользователем выдает `Authentication failed`.

**Причина:** Пропущен шаг выполнения `restore_metadata.cypher`. Этот файл создается автоматически при restore, но **не применяется автоматически**.

**Решение:** Всегда выполняйте после restore:
```bash
cat /var/lib/neo4j/data/scripts/mydatabase/restore_metadata.cypher | \
  cypher-shell -u neo4j -p <password> -a localhost -d system \
    --param "database => 'mydatabase'"
```

### `neo4j-admin database check` выдает ошибки на восстановленной базе

**Симптомы:** Проверка после restore показывает `inconsistencies-*.report` с ошибками.

**Причины:**
1. Бэкап был создан с ошибкой (прерван, нехватка места, сбой сети при remote backup).
2. Цепочка дифференциальных бэкапов неполна (утерян полный или промежуточные).
3. Восстановление делалось не из последнего артефакта цепочки.

**Решение:**
1. Проверяйте бэкап сразу после создания: `neo4j-admin database check --from-path=/backups/neo4j neo4j`.
2. Инспектируйте цепочку перед restore: `--inspect-path` должна показывать непрерывную последовательность TX ID.
3. Всегда восстанавливайте из **последнего** артефакта цепочки (с максимальным `HIGHEST TX`).

### Удалённый бэкап зависает / таймаут

**Симптомы:** `neo4j-admin database backup --from=host:6362 ...` висит без прогресса.

**Причины:**
1. Порт 6362 заблокирован firewall'ом между клиентом и сервером.
2. `server.backup.listen_address` не настроен или слушает не тот интерфейс.
3. SSL-политика `backup` не настроена или сертификаты не совпадают.

**Решение:**
1. Проверьте доступность порта: `nc -zv host 6362`.
2. В `neo4j.conf` источника: `server.backup.listen_address=0.0.0.0:6362` (или конкретный IP).
3. Настройте SSL-политику `backup` (см. [безопасность](./security.md#внутрикластерная-коммуникация-и-бэкапы)): `dbms.ssl.policy.backup.enabled=true` + сертификаты. Для теста можно отключить: `dbms.ssl.policy.backup.enabled=false` (не для production).

## Миграция формата хранилища

Формат store помечается как `MAJOR.MINOR` независимо от календарной версии Neo4j. Обновление
до свежего `MINOR` выполняется автоматически при старте, а переход на новый `MAJOR` или смена
формата — ручная операция через `neo4j-admin database migrate`.

| Формат | Статус |
| :--- | :--- |
| `block` | По умолчанию в Enterprise с 5.22, для всех баз с 5.26. Рекомендуемый с 5.23 |
| `aligned` | По умолчанию в Community |
| `high_limit` | Deprecated с 5.23 (Enterprise) |
| `standard` | Deprecated с 5.23 (Community) |

```bash
# Migrate the store to the latest MAJOR.MINOR of its current format
neo4j-admin database migrate neo4j

# Migrate to a specific format
neo4j-admin database migrate --to-format=block neo4j
```

```
2025-01-22 18:03:23.804+0000 INFO  [c.n.c.d.EnterpriseMigrateStoreCommand] Database migration completed successfully
```

Особенности операции:

- **Офлайн и I/O-интенсивна.** 100 ГБ — от 10 минут до более часа. Планируйте окно, а не
  «запустим и посмотрим».
- **BTREE-индексы удаляются.** Они не поддерживаются начиная с Neo4j 5. Создайте эквиваленты
  RANGE, POINT или TEXT заранее, либо примените `--force-btree-indexes-to-range` — но учтите,
  что RANGE не всегда оптимальная замена, а наполнение новых индексов идёт в фоне при первом
  старте.
- **В кластере** требует отдельного сервера-сидера: восстановить базу на одном сервере и
  назначить его designated seeder. Подробности — в [кластеризации](./clustering.md).
- **Собственные файлы конфигурации.** Команда читает `neo4j-admin-database-migrate.conf` из
  той же директории, что и `neo4j.conf`.

`high_limit` и `standard` удаляются после релиза 2026 LTS. `block` имеет более высокие лимиты,
поэтому перед миграцией `block` → `aligned` убедитесь, что граф в них укладывается.

## Лучшие практики

- **Держите всю цепочку бэкапов в одной директории.** Это условие работоспособности
  дифференциального восстановления, а не рекомендация по организации каталогов.
- **Задавайте `--temp-path` явно.** Иначе временная папка создаётся в системном разделе, и
  бэкап падает на нехватке места там, где вы его не проверяли.
- **Инспектируйте артефакты перед каждым restore.** `--inspect-path` показывает, действительно ли
  цепочка полная и какой tx ID вы получите.
- **Восстанавливайте в новую базу, а не поверх существующей** — так проверка не зависит от
  боевого окружения, а исходная база остаётся доступной для сравнения.
- **Не забывайте `restore_metadata.cypher`.** Данные целы, а пользователей нет.
- **Проверяйте бэкап, а не только создавайте.** Главный индикатор здоровья бэкап-системы —
  не наличие файлов, а прошедшие успешно restore-тесты.
- **Согласуйте retention policy с требуемым RPO.** Размер окна хранения журналов ограничивает
  глубину point-in-time recovery.
- **Планируйте миграцию формата как операцию с окном простоя**, а не как фоновую задачу.
- **Шифруйте бэкапы и ограничивайте доступ к ним** — они содержат все данные базы, а часто и
  метаданные аутентификации.

## См. также

- **[Обслуживание и эксплуатация](./operations.md)** — память, checkpointing, диагностика.
- **[Кластеризация и высокая доступность](./clustering.md)** — сидеры, DR, восстановление в кластере.
- **[Мониторинг и логи](./monitoring.md)** — `query.log` как источник данных о нагрузке.
- **[Установка и настройка](./installation_and_setup.md)** — версии, редакции, образы.
- **[Стратегии резервного копирования баз данных](../Concepts/backups.md)** — общая теория: RPO, RTO, правило 3-2-1-1-0.
- **[Проверка резервных копий](../Concepts/backup_validation.md)** — методика регулярных restore-тестов.
- **[Безопасность резервных копий](../Concepts/backup_security.md)** — шифрование и доступ к бэкапам.
- **[WAL: теория](../Concepts/write_ahead_log.md)** — журналы упреждающей записи и их очистка.
- **[Массовый импорт и начальная загрузка](./bulk_import.md)** — создание базы из дампа и загрузка больших объёмов данных.
- **[CDC и интеграция с потоками](./cdc_integration.md)** — журналы транзакций как источник изменений, режимы CDC.
- **[Обновление версии и миграция](./upgrade_and_migration.md)** — порядок операций при обновлении, почему формат мигрируется отдельно.

