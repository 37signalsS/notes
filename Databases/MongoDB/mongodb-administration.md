# MongoDB: Администрирование и обслуживание

**Актуально для:** MongoDB 8.0.x

---

## Определения

**Администрирование MongoDB** — комплекс мер по обеспечению высокой доступности, производительности и сохранности данных кластера, включая развертывание, мониторинг, бэкапы, обновление и обслуживание без простоев.

*   **FCV (Feature Compatibility Version):** Флаг, определяющий набор доступных функций версии. Даже после обновления бинарных файлов до v8.0, новые функции не будут активны, пока FCV не переключен.
*   **PITR (Point-in-Time Recovery):** Возможность восстановления состояния БД на любой конкретный момент времени (секунду) в прошлом. Требует непрерывного захвата Oplog.
*   **Working Set (Рабочий набор):** Объем данных и индексов, к которым приложение обращается наиболее часто. В идеале должен целиком помещаться в WiredTiger Cache.
*   **Oplog Window:** Временной интервал, за который хранятся операции в Oplog. Определяет, как долго Secondary может находиться в офлайне без необходимости полной пересинхронизации.
*   **Hot Backup:** Физическое резервное копирование работающего инстанса `mongod` без остановки сервиса. Требует блокировки записи через `db.fsyncLock()` или использования файловых снимков (LVM/ZFS/Btrfs).
*   **Cold Backup:** Бэкап остановленного инстанса `mongod`. Простой, но требует простоя.
*   **Logical Backup:** Резервное копирование через `mongodump`/`mongorestore`. Не зависит от движка хранения, медленнее на больших объемах (ТБ), но позволяет восстанавливать отдельные коллекции.
*   **Physical Backup:** Резервное копирование на уровне файлов данных. Мгновенное создание (snapshot), быстрое восстановление, но привязано к конкретному движку и версии MongoDB.
*   **Maintenance Window:** Плановый период простоя или снижения производительности для проведения обновлений, замены оборудования или миграций. Должен быть согласован с SLA и stakeholders.
*   **Rolling Upgrade:** Последовательное обновление узлов кластера без остановки сервиса. Стандартная процедура для MongoDB Replica Set и Sharded Cluster.
*   **Repair:** Восстановление данных после сбоя или повреждения через `mongod --repair` или `db.repairDatabase()`. Может привести к потере последних изменений, не записанных в Journal.
*   **Compact:** Перестроение файлов данных на диске для устранения фрагментации. В WiredTiger работает на уровне коллекции и может вызывать всплески I/O.
*   **Validate:** Проверка целостности данных через `db.validate()` и `db.collection.validate()`. Полезно после сбоев или при подозрении на повреждение.
*   **Journal:** Журнал предзаписей (Write-Ahead Log), обеспечивающий устойчивость данных (Durability) между чекпоинтами. Сброс на диск происходит каждые 100 мс.
*   **Resync:** Принудительная повторная синхронизация Secondary с Primary через удаление локальных данных и повторный initial sync.
*   **Systemd Unit:** Файл конфигурации службы `mongod` для systemd. Содержит параметры запуска, лимиты ресурсов (`LimitNOFILE`, `LimitNPROC`) и зависимости.

---

## Базовые концепции

### Архитектура администрирования

Администрирование MongoDB построено вокруг нескольких ключевых процессов жизненного цикла:

1.  **Развертывание:** Установка, конфигурация, инициализация Replica Set или Sharded Cluster.
2.  **Мониторинг:** Сбор метрик, алертинг, диагностика производительности и доступности.
3.  **Резервное копирование:** Регулярное создание бэкапов, тестирование восстановления, управление retention.
4.  **Обновление:** Rolling upgrade, FCV management, валидация после обновления.
5.  **Обслуживание:** Плановые работы, compact, repair, resync, изменение конфигурации.
6.  **Инцидент-респонс:** Восстановление после сбоев, анализ корневых причин, postmortem.

### Жизненный цикл данных

```
Запись → Journal (каждые 100мс) → WiredTiger Cache → Чекпоинт (каждые 60с) → Файлы данных
                                                    ↓
                                                Oplog → Репликация на Secondary
```

**Ключевые точки восстановления:**
*   **Чекпоинт:** Каждые 60 секунд. Точка, с которой начинается восстановление после сбоя.
*   **Journal:** Обеспечивает восстановление данных между чекпоинтами. При сбое MongoDB восстанавливается из последнего чекпоинта + данных из Journal.
*   **Oplog:** Позволяет откатить или повторить операции до конкретного момента времени (PITR).

### Модель обслуживания

MongoDB поддерживает два режима обслуживания:

1.  **Planned Maintenance:** Плановые работы с предупреждением. Используется `rs.stepDown()`, `rs.freeze()`, `replSetMaintenance`.
2.  **Unplanned Recovery:** Восстановление после сбоев. Используется `mongod --repair`, `db.repairDatabase()`, resync.

---

## Практические сценарии

### 1. Первичная конфигурация `mongod.conf`

Файл конфигурации в формате YAML. Основные блоки:

```yaml
# /etc/mongod.conf
storage:
  dbPath: /var/lib/mongodb
  journal:
    enabled: true
  wiredTiger:
    engineConfig:
      cacheSizeGB: 8  # 50% от RAM, но не более 64GB
      directoryForIndexes: false  # true для разделения данных и индексов
    collectionConfig:
      blockCompressor: zstd  # Snappy/zstd для compression

net:
  port: 27017
  bindIp: 127.0.0.1,10.0.5.42  # Только внутренние интерфейсы
  tls:
    mode: disabled  # requireTLS для production

replication:
  replSetName: rs0

systemLog:
  destination: file
  path: /var/log/mongodb/mongod.log
  logAppend: true
  logRotate: rename
  timeStampFormat: iso8601-utc

processManagement:
  fork: false  # false для systemd, true для ручного запуска
  pidFilePath: /var/run/mongodb/mongod.pid
```

**Валидация:**
```bash
mongosh --eval "db.getCmdLineOpts()"
# → Проверка, что параметры совпадают с ожидаемыми
```

### 2. Тюнинг systemd unit и лимитов ОС

Для production-кластеров необходимо настроить лимиты файловых дескрипторов и памяти:

```ini
# /etc/systemd/system/mongod.service
[Service]
User=mongod
Group=mongod
ExecStart=/usr/bin/mongod --config /etc/mongod.conf
PIDFile=/var/run/mongodb/mongod.pid
LimitNOFILE=64000
LimitNPROC=64000
TimeoutStopSec=300
Restart=on-failure

# После изменения:
systemctl daemon-reload
systemctl restart mongod
ulimit -n 64000  # Проверка в рамках сессии
```

**Проверка лимитов:**
```bash
cat /proc/$(pgrep mongod)/limits | grep "open files"
# → Максимальное количество открытых файлов
```

### 3. Настройка NTP и синхронизации времени

NTP-дрейф > 100 мс критичен для репликации и TLS:

```bash
# Проверка текущего дрейфа
chronyc tracking
# → Root delay, Root dispersion

# Проверка синхронизации
timedatectl status
# → NTP synchronized: yes

# Установка chrony (RHEL/CentOS)
dnf install chrony
systemctl enable --now chronyd
```

**Валидация в mongosh:**
```javascript
db.serverStatus().startTime
# → Проверка, что время запуска корректное

rs.printSecondaryReplicationInfo()
# → secondaryLagSec должен быть < 1с при нормальной синхронизации
```

### 4. Мониторинг: базовые команды

```javascript
// Общая нагрузка и память
db.serverStatus()
// → mem.resident, mem.virtual, wiredTiger.cache

// Активные операции
db.currentOp({ "active": true, "secs_running": { "$gt": 5 } })
// → Зависшие или долгие операции

// Статус Replica Set
rs.status()
// → Состояние узлов, health, optime

// Информация об Oplog
db.getReplicationInfo()
// → logSizeMB, usedMB, timeDiff (секунды)

// Задержка репликации
rs.printSecondaryReplicationInfo()
// → secondaryLagSec по каждому Secondary
```

### 5. Мониторинг: `mongostat` и `mongotop`

```bash
# Реальное время (аналог top для MongoDB)
mongostat --host rs0/mongo-1:27017,mongo-2:27017 --rowcount 60

# Ключевые поля SRE:
#   insert  query  update  delete  — операции в секунду
#   flushes  — количество чекпоинтов
#   vsize   resident  — использование памяти
#   mapped   — отображение данных
#   % locked — процент времени под блокировками
#   qr|qw   — очереди на чтение/запись

# Анализ I/O по коллекциям
mongotop --host rs0/mongo-1:27017 --rowcount 60
# → Время чтения/записи по каждой коллекции
```

**SRE алерты по `mongostat`:**
*   `qr` > 100: очередь на чтение, возможный shortage индексов
*   `qw` > 100: очередь на запись, возможный shortage ресурсов
*   `flushes` > 0: активные чекпоинты, ожидайте всплесков I/O
*   `% locked` > 5%: высокая конкуренция, проверьте долгие транзакции

### 6. Логирование и ротация логов

```yaml
# В mongod.conf
systemLog:
  destination: file
  path: /var/log/mongodb/mongod.log
  logAppend: true
  logRotate: rename  # или reopen (для systemd)
```

```bash
# Ротация вручную
mongod --logRotate reopen
# Или через db admin command
mongosh --eval "db.adminCommand({ logRotate: 1 })"
```

**Ротация через logrotate:**
```bash
# /etc/logrotate.d/mongod
/var/log/mongodb/*.log {
  daily
  rotate 14
  compress
  delaycompress
  missingok
  notifempty
  create 640 mongod mongod
  postrotate
    /bin/systemctl kill -s HUP mongod.service
  endscript
}
```

### 7. Резервное копирование: стратегии

#### Логический бэкап (`mongodump` / `mongorestore`)

```bash
# Бэкап с захватом Oplog (обязательно для консистентности)
mongodump \
  --uri="mongodb://mongo-1:27017,mongo-2:27017/?replicaSet=rs0" \
  --oplog \
  --out=/backup/mongodb-$(date +%F) \
  --gzip

# Восстановление
mongorestore \
  --uri="mongodb://mongo-1:27017/?replicaSet=rs0" \
  --dir=/backup/mongodb-2024-01-15 \
  --gzip \
  --oplogReplay
```

**Плюсы:** Компактность, возможность восстановления отдельных коллекций, не зависит от storage engine.
**Минусы:** Медленно на больших объемах (ТБ), не подходит для frequent backups.

#### Физический бэкап (файловые снимки)

```bash
# LVM snapshot (требуется LVM на дисках данных)
lvcreate --snapshot --size 20G --name mongo-snap /dev/vg0/mongodb
mount /dev/vg0/mongo-snap /mnt/snap

# Бэкап snapshot'а
tar -czf /backup/mongo-physical-$(date +%F).tar.gz -C /mnt/snap .
umount /mnt/snap
lvremove -f /dev/vg0/mongo-snap
```

```bash
# ZFS snapshot
zfs snapshot tank/mongodb@backup-$(date +%F)
zfs send tank/mongodb@backup-$(date +%F) | gzip > /backup/mongo-zfs-$(date +%F).gz
```

**Важно:** Перед созданием snapshot'а выполните `db.fsyncLock()` для гарантии консистентности данных на диске.

#### Hot Backup без остановки (через fsyncLock)

```javascript
// Блокировка записи для консистентного snapshot'а
db.fsyncLock()
// → "lock count": 1

// Создайте snapshot на уровне storage/файловой системы здесь

// Снятие блокировки
db.fsyncUnlock()
// → "lock count": 0
```

**Предупреждение:** `db.fsyncLock()` блокирует все write-операции. Для больших snapshot'ов используйте Storage Snapshot (LVM/ZFS) с `fsyncLock`, а не `mongodump`.

### 8. Резервное копирование: PITR (Point-in-Time Recovery)

PITR позволяет восстановить данные на любой момент времени в пределах Oplog Window:

```bash
# Шаг 1: Логический бэкап с Oplog
mongodump --uri="mongodb://..." --oplog --out=/backup/base

# Шаг 2: Непрерывный захват Oplog (через cron или external tool)
# Пример: Percona Backup for MongoDB (PBM) или кастомный скрипт
mongodump --uri="mongodb://..." --oplog --out=/backup/oplog-$(date +%F)

# Шаг 3: Восстановление на конкретный момент времени
mongorestore \
  --uri="mongodb://..." \
  --dir=/backup/base \
  --oplogReplay \
  --oplogLimit="2024-01-15T14:30:00Z"
```

**Требования для PITR:**
*   Oplog Window должен покрывать период с момента последнего бэкапа.
*   Рекомендуется Oplog Window ≥ 24 часа для production.
*   Для шардированных кластеров — бэкап и восстановление через mongos.

### 9. Валидация и тестирование восстановления

```bash
# Проверка целостности бэкапа
mongorestore --dir=/backup/mongodb-2024-01-15 --dryRun
# → Список коллекций, которые будут восстановлены

# Тестовое восстановление в отдельный инстанс
mongod --dbpath /tmp/mongo-restore-test --port 27018 --fork --logpath /tmp/restore.log
mongorestore --uri="mongodb://localhost:27018" --dir=/backup/mongodb-2024-01-15
mongosh --port 27018 --eval "db.getCollectionNames()"
# → Проверка, что все ожидаемые коллекции присутствуют

# Очистка тестового инстанса
kill $(pgrep -f "mongod.*27018")
rm -rf /tmp/mongo-restore-test
```

**SRE практика:** Тестируйте восстановление минимум раз в квартал. Документируйте RTO (Recovery Time Objective) и RPO (Recovery Point Objective).

### 10. Обновление версий: Rolling Upgrade (8.0+)

```bash
# Шаг 1: Обновление Secondary
systemctl stop mongod
yum update mongodb-org  # или apt-get install mongodb-org
systemctl start mongod

# Проверка статуса
mongosh --eval "rs.status().members.find(m => m.host.includes('secondary')).stateStr"
# → SECONDARY

# Шаг 2: Ротация Primary
mongosh --eval "rs.stepDown(60)"
# → Текущий Primary становится Secondary

# Шаг 3: Обновление старого Primary
systemctl stop mongod
yum update mongodb-org
systemctl start mongod

# Шаг 4: Финализация FCV (после проверки стабильности)
mongosh --eval "db.adminCommand({ setFeatureCompatibilityVersion: '8.0' })"
```

**Предварительные проверки перед upgrade:**
```bash
# Проверка FCV
mongosh --eval "db.adminCommand({ getParameter: 1, featureCompatibilityVersion: 1 })"
# → Должен быть 7.0 перед upgrade до 8.0

# Проверка наличия активных транзакций
mongosh --eval "db.serverStatus().transactions.totalLive"
# → Должен быть 0 перед upgrade

# Проверка версии пакетов
mongod --version
# → Сравнение с целевой версией
```

### 11. Downgrade: ограничения и процедура

```bash
# Проверка FCV перед downgrade
mongosh --eval "db.adminCommand({ getParameter: 1, featureCompatibilityVersion: 1 })"
# → Должен быть 7.0 для downgrade до 7.0

# Если FCV = 8.0 — сначала верните на 7.0
mongosh --eval "db.adminCommand({ setFeatureCompatibilityVersion: '7.0' })"
# → Ожидайте, пока все узлы перейдут на 7.0 перед downgrade
```

**Ограничения downgrade:**
*   Time-series коллекции необходимо удалить перед downgrade ниже 6.0.
*   Коллекции с функционалом, появившимся в 8.0, нельзя использовать после downgrade FCV.
*   Журнал Oplog может содержать операции, непонятные старой версии.

### 12. Плановое обслуживание: maintenance mode и stepDown

```javascript
// Перевод Secondary в RECOVERING для обслуживания
db.adminCommand({ replSetMaintenance: 1 })
// → Узел переходит в RECOVERING, не участвует в выборах

// Проверка статуса
rs.status().members.find(m => m.host.includes('maintenance')).stateStr
// → RECOVERING

// Возврат в SECONDARY
db.adminCommand({ replSetMaintenance: 0 })
// → SECONDARY
```

```javascript
// Плановый отвод Primary (например, для замены диска)
rs.stepDown(300)  // Secondary на 5 минут
// → Автоматически выбирается новый Primary

// Заморозка узла без отвода Primary
rs.freeze(600)  // Не участвует в выборах 10 минут
```

### 13. Очистка файлов отката (Rollback)

После failover Primary может откатить изменения. Файлы отката сохраняются в `data/rollback/`:

```bash
# Проверка наличия файлов отката
ls -la /var/lib/mongodb/rollback/

# Анализ откатанных операций
mongorestore --dir /var/lib/mongodb/rollback/ --dryRun
# → Список операций, которые были откачены

# Если данные нужны — примените их вручную
mongorestore --dir /var/lib/mongodb/rollback/ --nsFrom="admin.system.users" --nsTo="admin.system.users_restore"
```

### 14. Восстановление после сбоя: `mongod --repair`

```bash
# Остановка mongod
systemctl stop mongod

# Проверка диска
df -h /var/lib/mongodb
# → Достаточно свободного места (минимум 2x от размера данных)

# Запуск repair
mongod --dbpath /var/lib/mongodb --repair
# → Восстановление данных из Journal и файлов

# Запуск mongod
systemctl start mongod

# Валидация
mongosh --eval "db.serverStatus().wiredTiger.cache"
# → Нормальное использование кэша
```

**Предупреждение:** `mongod --repair` может привести к потере последних изменений, не записанных в Journal. Используйте только как последний resort.

### 15. `compact`: перестроение файлов данных

```javascript
// Compact коллекции с высокой фрагментацией
db.runCommand({ compact: 'large_collection' })
// → Процесс может занять часы для больших коллекций

// Проверка статуса
db.currentOp({ "command.compact": { $exists: true } })
// → Активные операции compact
```

**Влияние на I/O:** Compact создает значительную нагрузку на диск. Выполняйте в maintenance window.

### 16. Анализ логов (Log Analysis)

Логи `mongod`/`mongos` — первичный источник для диагностики инцидентов и аудита. Формат — JSON (начиная с 4.4) или текстовый.

**Структура JSON-лога:**
```json
{
  "t": { "$date": "2026-10-04T10:15:30.123Z" },
  "s": "I",
  "c": "NETWORK",
  "id": 22943,
  "ctx": "listener",
  "msg": "Connection accepted",
  "attr": { "remote": "10.0.5.10:52341", "connectionId": 42, "connectionCount": 128 }
}
```

**Ключевые поля:**
*   `s` — severity: `F` (Fatal), `E` (Error), `W` (Warning), `I` (Information), `D1-D5` (Debug).
*   `c` — component: `NETWORK`, `STORAGE`, `REPL`, `COMMAND`, `QUERY`, `INDEX`, `AUTH`, `CONTROL`.
*   `id` — код события (стабильный идентификатор для фильтрации).
*   `attr` — контекст события.

**Анализ типичных проблем:**
```bash
# Ошибки и фатальные события
grep -E '"s":"E"|"s":"F"' /var/log/mongodb/mongod.log

# Failover и выборы Primary
grep -E '"id":(4607|4610|4612|4615)' /var/log/mongodb/mongod.log
# → 4607: "Starting an election", 4610: "Election succeeded"

# Медленные операции (если profiling включен)
grep '"c":"COMMAND"' /var/log/mongodb/mongod.log | jq 'select(.attr.docsExamined > 10000)'

# Аутентификация: неудачные попытки
grep '"c":"AUTH"' /var/log/mongodb/mongod.log | grep -i "failed"

# Репликация: лаг, ошибки initial sync
grep '"c":"REPL"' /var/log/mongodb/mongod.log | grep -iE "error|lag|initial sync"

# Подсчет событий по компонентам
jq -r '.c' /var/log/mongodb/mongod.log | sort | uniq -c | sort -rn

# Подсчет по severity
jq -r '.s' /var/log/mongodb/mongod.log | sort | uniq -c | sort -rn
```

**Конфигурация verbosity:**
```javascript
// Установить уровень логирования для компонента
db.adminCommand({ setParameter: 1, logComponentVerbosity: {
  storage: { journal: 2 },
  replication: 1,
  network: 0
}})

// Текущий уровень
db.adminCommand({ getParameter: 1, logComponentVerbosity: 1 })
```

**Ротация и архивация:** см. раздел 6 (Логирование и ротация логов). Для централизованного сбора используйте Filebeat/Fluentd → ELK/Loki.

### 17. Скриптинг mongosh и автоматизация

`mongosh` поддерживает выполнение JavaScript-файлов, что позволяет автоматизировать рутинные операции и интегрировать MongoDB в CI/CD и системы управления конфигурацией.

**Выполнение скрипта:**
```bash
# Выполнить JS-файл
mongosh --host rs0/mongo-1:27017 --file /opt/scripts/healthcheck.js

# Или через stdin
mongosh --host rs0/mongo-1:27017 < /opt/scripts/healthcheck.js

# С аутентификацией
mongosh "mongodb://user:pass@mongo-1:27017/admin?authSource=admin" --file script.js

# Eval (однострочный)
mongosh --host rs0/mongo-1:27017 --eval "db.serverStatus().version"
```

**Пример: healthcheck-скрипт:**
```javascript
// /opt/scripts/healthcheck.js
const status = rs.status();
const primary = status.members.find(m => m.stateStr === "PRIMARY");
if (!primary) {
  print("ERROR: No PRIMARY in Replica Set");
  quit(1);
}
const lag = db.adminCommand({ replSetGetStatus: 1 }).members
  .filter(m => m.stateStr === "SECONDARY")
  .map(m => m.optimeDate);
print(`OK: PRIMARY=${primary.name}, members=${status.members.length}`);
quit(0);
```

**Пример: массовая операция через скрипт:**
```javascript
// /opt/scripts/cleanup_old_sessions.js
const cutoff = new Date(Date.now() - 30 * 24 * 3600 * 1000); // 30 дней
const result = db.sessions.deleteMany({ createdAt: { $lt: cutoff } });
print(`Deleted ${result.deletedCount} old sessions`);
```

**Автоматизация через Ansible:** см. **[Ansible: MongoDB Setup](../../Ansible/examples/mongodb_setup.md)** — примеры `mongosh --eval`, pymongo, настройки Replica Set.

**Ключевые возможности mongosh:**
*   `quit(code)` — выход с кодом (для CI/CD).
*   `print()` / `printjson()` — вывод.
*   `db.getSiblingDB("name")` — переключение БД.
*   `load("/path/to/file.js")` — загрузка другого скрипта.
*   Поддержка async/await (Node.js runtime).

### 18. Совместимость версий и драйверов

**Правила совместимости MongoDB:**
*   **Драйверы:** драйвер версии N поддерживает MongoDB N и N-1 (например, драйвер 8.x поддерживает MongoDB 8.0 и 7.x).
*   **FCV:** Feature Compatibility Version должен совпадать с минорной версией.
*   **Rolling upgrade:** только между соседними мажорными версиями (7.0 → 8.0, не 6.0 → 8.0 напрямую).

**Матрица совместимости драйверов (упрощённо):**

| Драйвер | MongoDB 8.0 | MongoDB 7.0 | MongoDB 6.0 |
| :--- | :--- | :--- | :--- |
| pymongo 4.9+ | Да | Да | Да |
| Node.js 6.x | Да | Да | Да |
| Java sync 5.x | Да | Да | Да |
| Go 1.17+ | Да | Да | Да |
| C# 3.x | Да | Да | Да |

**Проверка совместимости:**
```bash
# Версия сервера
mongosh --eval "db.version()"

# Версия драйвера (Python)
python3 -c "import pymongo; print(pymongo.version)"

# FCV
mongosh --eval "db.adminCommand({ getParameter: 1, featureCompatibilityVersion: 1 })"
```

**Важные ограничения:**
*   **mongodump/mongorestore:** утилиты Database Tools версии N могут восстанавливать данные в MongoDB N и N-1. Не используйте утилиты 8.0 для восстановления в 6.0.
*   **Time-series:** коллекции, созданные в 6.0+, нельзя использовать после downgrade ниже 6.0.
*   **Queryable Encryption:** требует MongoDB 7.0+ и соответствующих драйверов.
*   **Hedged reads:** удалены в 8.0 (см. **[Высокая доступность](./high_availability.md)**).

**Рекомендация SRE:** всегда проверяйте [MongoDB Compatibility Matrix](https://www.mongodb.com/docs/manual/reference/mongodb-compatibility/) перед upgrade. Пиньте версии пакетов (`apt-mark hold mongodb-org`).

---

## Операции и команды

### Управление конфигурацией

| Команда / Файл | Описание |
| :--- | :--- |
| `/etc/mongod.conf` | Основной файл конфигурации (YAML) |
| `db.getCmdLineOpts()` | Получить текущие параметры запуска |
| `db.adminCommand({ getParameter: 1, featureCompatibilityVersion: 1 })` | Проверка FCV |
| `db.adminCommand({ setFeatureCompatibilityVersion: '8.0' })` | Установка FCV |
| `db.setProfilingLevel(1, { slowms: 100 })` | Включение профилирования |

### Управление жизненным циклом

| Команда / Действие | Описание |
| :--- | :--- |
| `systemctl start mongod` | Запуск сервиса |
| `systemctl stop mongod` | Остановка сервиса |
| `systemctl restart mongod` | Перезапуск |
| `systemctl status mongod` | Проверка статуса |
| `mongod --repair` | Восстановление после сбоя |
| `mongod --dbpath ... --fork` | Фоновый запуск (без systemd) |

### Резервное копирование и восстановление

| Команда / Метод | Описание |
| :--- | :--- |
| `mongodump --uri=... --oplog --out=...` | Логический бэкап с Oplog |
| `mongorestore --dir=... --oplogReplay` | Восстановление с Oplog |
| `mongodump --uri=... --oplog --archive=...` | Бэкап в архив |
| `mongorestore --archive=...` | Восстановление из архива |
| `db.fsyncLock()` | Блокировка записи для физического бэкапа |
| `db.fsyncUnlock()` | Снятие блокировки записи |
| `db.repairDatabase()` | Repair конкретной базы |
| `db.runCommand({ compact: 'coll' })` | Compact коллекции |
| `db.validate()` | Валидация всех баз |
| `db.collection.validate()` | Валидация коллекции |

### Мониторинг и диагностика

| Команда / Метод | Что показывает |
| :--- | :--- |
| `db.serverStatus()` | Общая статистика: память, соединения, кэш, операции |
| `db.currentOp()` | Активные операции в реальном времени |
| `db.killOp(opId)` | Завершение операции |
| `db.getReplicationInfo()` | Размер и временное покрытие Oplog |
| `rs.printSecondaryReplicationInfo()` | Задержка репликации по Secondary |
| `rs.printReplicationInfo()` | Информация об Oplog с точки зрения Primary |
| `mongostat` | Реальное время: ops, память, блокировки, очереди |
| `mongotop` | I/O по коллекциям |
| `db.serverStatus().wiredTiger.cache` | Использование кэша WiredTiger |
| `db.serverStatus().transactions` | Метрики транзакций |
| `db.serverStatus().oplog` | Состояние Oplog |
| `db.serverStatus().oplogMirroring` | Состояние mirrored reads |
| `db.serverStatus().flowControl` | Состояние Flow Control |
| `db.serverStatus().mirroredReads` | Метрики mirrored reads |

### Обслуживание и обновление

| Команда / Метод | Описание |
| :--- | :--- |
| `rs.stepDown(seconds)` | Отвод Primary (плановый или принудительный) |
| `rs.stepDown(seconds, { force: true })` | Принудительный stepDown |
| `rs.freeze(seconds)` | Заморозка узла для обслуживания |
| `db.adminCommand({ replSetMaintenance: 1 })` | Включение maintenance mode (RECOVERING) |
| `db.adminCommand({ replSetMaintenance: 0 })` | Выключение maintenance mode |
| `db.adminCommand({ replSetResizeOplog: 1, size: 50000 })` | Динамическое изменение размера Oplog (MB) |
| `db.adminCommand({ replSetAbortPrimaryCatchUp: 1 })` | Принудительное завершение catchup |
| `db.adminCommand({ logRotate: 1 })` | Ротация логов |
| `db.adminCommand({ setFeatureCompatibilityVersion: '8.0' })` | Установка FCV |

### Параметры конфигурации (SSD/High IOPS)

| Параметр | Значение по умолчанию | SRE рекомендация |
| :--- | :--- | :--- |
| `storage.wiredTiger.engineConfig.cacheSizeGB` | 50% RAM | Установите явно. Для 16GB RAM → 8GB. Для контейнеров — по лимиту RAM пода. |
| `storage.wiredTiger.engineConfig.directoryForIndexes` | false | true для разделения данных и индексов на разные диски |
| `storage.wiredTiger.collectionConfig.blockCompressor` | snappy | zstd для лучшего сжатия (больше CPU) |
| `storage.journal.enabled` | true | false только для не-critical данных с риском потери |
| `storage.journal.commitIntervalMs` | 100 | Уменьшить для меньшей потери при сбое (больше I/O) |
| `replication.oplogSizeMB` | 5% свободного места | Установите явно: минимум 24 часа изменений |
| `replication.enableFlowControl` | true | true для production, ограничивает writes при replication lag |
| `replication.flowControlTargetLagSeconds` | 0.5 | Уменьшить для более агрессивного ограничения |
| `replication.mirrorReads.samplingRate` | 0.01 | 1% reads зеркалируются на secondary для прогрева кэша |
| `replication.secondaryDelaySecs` | 0 | Установить >0 для delayed secondary (защита от human error) |
| `net.maxIncomingConnections` | 65536 | Установить лимит соединений (например, 10000) |
| `operationProfiling.slowOpThresholdMs` | 100 | Уменьшить до 50ms для детального мониторинга |
| `setParameter.transactionLifetimeLimitSeconds` | 60 | Увеличить до 120-300 для длинных транзакций |
| `setParameter.maxTransactionLockRequestTimeoutMillis` | 5 | Увеличить до 1000 для high contention |

### Systemd unit: рекомендуемые лимиты

```ini
[Service]
User=mongod
Group=mongod
ExecStart=/usr/bin/mongod --config /etc/mongod.conf
LimitNOFILE=64000
LimitNPROC=64000
LimitAS=infinity
TimeoutStopSec=300
Restart=on-failure
RestartSec=5
```

### Sysctl параметры для production

```bash
# /etc/sysctl.d/99-mongodb.conf
vm.swappiness = 1  # Минимизировать swap
vm.dirty_ratio = 10  # Максимальный процент грязных страниц
vm.dirty_background_ratio = 3  # Фоновая запись
fs.file-max = 1000000  # Максимальное количество открытых файлов
net.core.somaxconn = 4096  # Очередь соединений
net.ipv4.tcp_syncookies = 1  # Защита от SYN flood
```

```bash
sysctl -p /etc/sysctl.d/99-mongodb.conf
```

---

## Ограничения и особенности

### 1. Время жизни и масштабирование

*   **Oplog Window:** Secondary, отставший больше чем Oplog Window, требует полной пересинхронизации (initial sync). Для TB-баз это часы. Мониторьте `db.getReplicationInfo().timeDiff`.
*   **Working Set:** Должен помещаться в WiredTiger Cache. При превышении начинается Cache Eviction с ростом latency. Мониторьте `db.serverStatus().wiredTiger.cache.bytes currently in the cache`.
*   **Резервное копирование:** На объемах > 1TB `mongodump` становится неприменимым по времени. Используйте файловые snapshot'ы (LVM/ZFS) или Percona Backup for MongoDB.
*   **Индексы:** Максимум 64 индекса на коллекцию. Каждый индекс замедляет запись (Write Amplification). Мониторьте `db.collection.stats().indexDetails`.

### 2. Жесткие диски и фрагментация

*   **Чекпоинты:** Каждые 60 секунд создают всплески I/O. На HDD это критично — используйте только SSD/NVMe.
*   **Compact:** Выполняет полное перестроение файлов данных. На больших коллекциях (>100GB) может занимать часы и создавать высокую нагрузку на диск.
*   **Repair:** Может потребовать места, равного размеру данных + индексов. На HDD repair может занять дни для TB-баз.

### 3. FCV и обратная совместимость

*   **Upgrade:** FCV остается на старой версии после upgrade пакетов. Новые функции не активны пока FCV не переключен.
*   **Downgrade:** FCV должен быть опущен до целевой версии перед downgrade пакетов. Некоторые изменения (например, creation of new indexes with new options) необратимы.
*   **Feature checks:** Всегда проверяйте FCV перед и после операций с версиями.

### 4. Журналирование и устойчивость

*   **Journal commit interval:** По умолчанию 100 мс. При сбое питания MongoDB теряет данные за последние 100 мс (если `j: true` не использовался).
*   **Директория journal:** Хранится в `dbPath/journal/`. Должна быть на быстром диске (NVMe).
*   **`j: true`:** Гарантирует запись в Journal перед подтверждением. Добавляет задержку ~1ms, но критично для финансовых данных.

### 5. Резервное копирование и retention

*   **Retention:** Определяется SLA и RPO. Для production — минимум 2 полных бэкапа + 7 дней Oplog.
*   **Offsite storage:** Бэкапы должны храниться отдельно от production (другой сервер, облако, ленточный накопитель).
*   **Шифрование бэкапов:** Логические и физические бэкапы должны храниться в зашифрованном виде.
*   **Тестирование восстановления:** Бэкап без тестирования восстановления — не бэкап. Тестируйте минимум раз в квартал.

---

## Устранение неполадок

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **OOM Kill** | Кэш + соединения > RAM. | `dmesg`, `mongostat`, `db.serverStatus().mem` | Ограничить `cacheSizeGB` и `maxIncomingConnections`. Добавить RAM или масштабировать. |
| **Диск заполнен** | Логи, бэкапы или данные переполнили раздел. | `df -h`, `du -sh /var/lib/mongodb/*` | Увеличить диск, вынести бэкапы, настроить log rotation. |
| **Высокий I/O Wait** | Частые чекпоинты или медленные диски. | `iostat -x 1`, `mongotop` | Перейти на NVMe, разнести индексы и данные, увеличить RAM. |
| **Replica Lag** | Медленная сеть или диск на Secondary. | `rs.printSecondaryReplicationInfo()` | Проверить пропускную способность, увеличить `oplogSize`, оптимизировать сеть. |
| **`Connection reset`** | Лимит дескрипторов или файлов. | `ulimit -n`, `cat /proc/$(pgrep mongod)/limits` | Установить `ulimit -n 64000` в systemd юните. |
| **Stale Config** | Устаревший routing table на mongos. | Логи `mongos`: `StaleConfig error` | Обычно исправляется автоматически при повторе (Retry). При устойчивых ошибках — перезапуск mongos. |
| **Oplog переполнен** | Secondary долго не доступен. | `db.getReplicationInfo()` | Увеличить `oplogSize`, мониторить Oplog Window. |
| **FCV mismatch** | После upgrade FCV не переключен. | `db.adminCommand({ getParameter: 1, featureCompatibilityVersion: 1 })` | Переключить FCV на новую версию после проверки стабильности. |
| **Ошибка upgrade/downgrade** | Присутствие активных транзакций, TS-коллекций или неправильный FCV. | Версия FCV, `db.serverStatus().transactions.totalLive` | Завершить транзакции, удалить TS-коллекции перед downgrade, установить правильный FCV. |
| **`mongod --repair` падает** | Недостаточно места на диске или поврежден Journal. | Логи mongod, `df -h` | Убедиться, что свободного места > 2x от размера данных. Восстановить Journal вручную. |
| **`mongod` не запускается** | Неверные параметры в `mongod.conf` или поврежден WiredTiger метаданные. | Логи mongod, `mongod --dbpath ... --repair` | Проверить конфигурацию, выполнить repair. |
| **`db.fsyncLock()` зависает** | Активные long-running операции (транзакции, index builds). | `db.currentOp()` | Завершить долгие операции или дождаться их завершения. |
| **Высокий % locked в mongostat** | Высокая конкуренция на уровне документов или долгие транзакции. | `db.currentOp()`, `db.serverStatus().transactions` | Уменьшить размер транзакций, оптимизировать доступ к документам. |
| **Rollback после failover** | Primary упал до репликации данных. | `rs.printReplicationInfo()` | Использовать `w: "majority"`, мониторить Oplog. Файлы отката в `data/rollback/`. |
| **`NotMaster` / `NotPrimaryNoSecondaryOk`** | Failover во время операции. | Логи приложения | Приложение должно retry с новым Primary. |
| **`Journal` переполнен** | Слишком большие транзакции или медленный диск. | `db.serverStatus().wiredTiger.cache` | Увеличить скорость диска, уменьшить размер транзакций. |

---

## Лучшие практики (SRE)

### Резервное копирование

1.  **3-2-1 правило:** 3 копии данных, 2 разных носителя, 1 копия offsite.
2.  **Логический + физический:** Комбинируйте `mongodump` (для точечных восстановлений) и файловые snapshot'ы (для полных восстановлений).
3.  **Oplog для PITR:** Захватывайте Oplog в каждом бэкапе. Это позволяет восстановиться на любой момент времени.
4.  **Шифрование бэкапов:** Храните бэкапы в зашифрованном виде (LUKS, AES-256).
5.  **Тестирование восстановления:** Минимум раз в квартал выполняйте полное восстановление на тестовый инстанс.
6.  **Retention:** Определите retention по SLA. Для production — минимум 2 полных бэкапа + 7 дней Oplog.
7.  **Автоматизация:** Используйте скрипты или инструменты (PBM, mongodump cron) для автоматизации бэкапов.
8.  **Валидация:** После каждого бэкапа проверяйте `mongorestore --dryRun` и логи.

### Мониторинг и алертинг

9.  **Ключевые метрики:**
    *   `rs.status()` — здоровье Replica Set
    *   `rs.printSecondaryReplicationInfo()` — задержка репликации
    *   `db.getReplicationInfo()` — Oplog Window
    *   `db.serverStatus().wiredTiger.cache` — использование кэша
    *   `db.serverStatus().transactions.totalLive` — активные транзакции
    *   `mongostat` — ops/sec, блокировки, очереди
10. **Алерты:**
    *   Replica Set без PRIMARY — критично
    *   Replication lag > 10s — предупреждение
    *   Oplog Window < 1h — критично
    *   WiredTiger Cache > 90% — предупреждение
    *   Disk usage > 80% — критично
    *   `mongod` не запускается 30s — критично
11. **NTP:** Мониторьте дрейф времени. Дрейф > 100 мс нарушает репликацию и TLS.

### Обновления и изменения

12. **Change Management:** Все изменения (upgrade, конфигурация, schema) должны проходить через Change Management с approval.
13. **Rollback Plan:** Перед каждым изменением имейте план отката (backup, старый FCV, snapshot).
14. **Maintenance Window:** Выполняйте изменения в согласованное окно с уведомлением stakeholders.
15. **Canary deployments:** Обновляйте сначала один Secondary, проверяйте метрики, затем остальные.
16. **FCV management:** Переключайте FCV только после проверки стабильности всех узлов. Не оставляйте FCV на старой версии надолго.

### Производительность

17. **Working Set в RAM:** Оценивайте размер Working Set и убедитесь, что он помещается в WiredTiger Cache.
18. **Индексы:** Создавайте индексы до залива данных. Используйте `$indexStats` для аудита неиспользуемых индексов.
19. **Чекпоинты:** Мониторьте `wiredTiger.transaction.checkpoint amount written` и `iostat` во время чекпоинтов.
20. **Flow Control:** Включайте `enableFlowControl: true` для поддержания replication lag низким.

### Безопасность

21. **Авторизация:** Всегда включайте `security.authorization: enabled` в production.
22. **Сетевой доступ:** `bindIp` ограничен внутренними интерфейсами. Порты 27017/27018/27019 не открыты в интернет.
23. **Журналы:** Не храните пароли или ключи в `mongod.conf`. Используйте Vault или environment variables.
24. **Шифрование:** Включите TLS для внутреннего трафика и шифрование на диске (EaR или LUKS).

---

## Гранicные случаи

### 1. Долгий-running compact и фрагментация

Compact может занимать часы для больших коллекций (>100GB). На HDD это критично. Для SSD/NVMe compact выполняется быстрее, но все равно создает всплеск I/O.

**Решение:** Выполняйте compact в maintenance window. Мониторьте через `db.currentOp()`. На SSD/NVMe фрагментация менее критична — compact может не требоваться.

### 2. Repair и потеря данных

`mongod --repair` может удалить последние изменения, не записанные в Journal. На TB-базах repair может занять дни.

**Решение:** Используйте repair только как последний resort. Предпочитайте восстановление из бэкапа. Для Replica Set — resync Secondary вместо repair.

### 3. FCV mismatch после частичного upgrade

Если часть узлов обновлена до 8.0, а FCV остался на 7.0 — новые функции не работают. Если FCV переключен на 8.0, а часть узлов еще на 7.0 — кластер нестабилен.

**Решение:** Следуйте процедуре Rolling Upgrade строго: обновите все узлы → проверьте стабильность → переключите FCV.

### 4. Downgrade с Time-series коллекциями

Time-series коллекции являются backwards-incompatible. Перед downgrade ниже 6.0 или 5.3 необходимо удалить все TS-коллекции.

**Решение:** Удалите TS-коллекции или экспортируйте данные в обычные коллекции перед downgrade. После downgrade TS-коллекции можно recreate.

### 5. Oplog слишком мал для maintenance window

Если Secondary будет в офлайне дольше Oplog Window — потребуется полная пересинхронизация (initial sync). Для TB-баз это часы.

**Решение:** Увеличьте `oplogSizeMB` до покрытия минимум 24 часов изменений. Мониторьте `db.getReplicationInfo().timeDiff`.

### 6. `db.fsyncLock()` и long-running транзакции

`db.fsyncLock()` блокирует все write-операции. Если есть долгие транзакции (> 60 сек), lock может зависнуть.

**Решение:** Завершите долгие транзакции через `db.currentOp()` и `db.killOp()` перед `fsyncLock()`. Используйте Storage Snapshot (LVM/ZFS) с минимальным временем блокировки.

### 7. Журнал (Journal) на отдельном диске

Размещение Journal на быстром SSD снижает latency записи. На HDD journal commit (каждые 100 мс) создает дополнительную нагрузку.

**Решение:** Для production используйте NVMe для данных и Journal. На контейнерах (K8s/Docker) используйте fast local SSD для `dbPath`.

### 8. Systemd и `fork: true` конфликт

В `mongod.conf` параметр `processManagement.fork: true` конфликтует с systemd unit, который ожидает, что процесс не длякается. Это приводит к падению сервиса.

**Решение:** Установите `fork: false` в `mongod.conf` при использовании systemd. Убедитесь, что `PIDFile` указан правильно.

### 9. NTP дрейф и TLS handshake failures

Дрейф времени > 5 минут вызывает ошибки TLS handshake (`certificate has expired` или `not yet valid`). Дрейф > 100 мс нарушает репликацию.

**Решение:** Настройте chrony/ntpd на всех узлах. Мониторьте дрейф через `chronyc tracking`. Синхронизируйте время перед включением TLS.

### 10. Восстановление после потери > 50% узлов в Replica Set

При потере кворума (большинства узлов) Replica Set не может выбрать Primary. Данные остаются доступны для чтения, но запись невозможна.

**Решение:** Используйте force reconfig для восстановления кворума на оставшихся узлах. Добавьте новые узлы обратно. Восстановите данные с бэкапа если необходимо.

---

## Чистка и восстановление после инцидентов

### Очистка файлов отката (Rollback)

```bash
# Проверка наличия файлов отката
ls -la /var/lib/mongodb/rollback/

# Анализ откатанных операций
mongorestore --dir /var/lib/mongodb/rollback/ --dryRun
# → Список операций, которые были откачены

# При необходимости — примените вручную
mongorestore --dir /var/lib/mongodb/rollback/ --nsFrom="admin.system.users" --nsTo="admin.system.users_restore"
```

### Очистка после массового abort транзакций

После сбоя, приведшего к массовому abort'у транзакций, проверьте:
1.  **Активные транзакции:** `db.serverStatus().transactions.totalLive` — должно быть 0 или близко к 0.
2.  **WiredTiger Cache:** `db.serverStatus().wiredTiger.cache` — нормализовался ли процент использования.
3.  **Replication:** `rs.printSecondaryReplicationInfo()` — нет ли лага после восстановления.

### Восстановление после `mongod --repair`

После repair проверьте:
1.  **Целостность данных:** `db.runCommand({ validate: 'collection_name' })` — `valid: true`.
2.  **Replica Set статус:** `rs.status()` — все члены PRIMARY/SECONDARY.
3.  **Oplog:** `db.getReplicationInfo()` — размер и покрытие корректны.

### Очистка metadata в `config.transactions`

После завершения транзакции MongoDB автоматически очищает запись из `config.transactions`. При подозрении на "зависшие" записи:

```javascript
// Только для диагностики (read-only)
db.getSiblingDB("config").transactions.find({
  "startTimestamp": { $lt: new Date(Date.now() - 3600000) }
})
// Если записи старше transactionLifetimeLimitSeconds остались — проверьте логи mongod
```

### Очистка временных файлов после сбоя

```bash
# Проверка временных файлов
ls -la /var/lib/mongodb/tmp/
# → Временные файлы от сбоев

# Очистка (только если mongod остановлен)
rm -f /var/lib/mongodb/tmp/*
```

---

## Дополнительная информация

*   **[Общий обзор MongoDB](./mongodb.md)** — архитектура и WiredTiger.
*   **[Репликация в MongoDB](./mongodb-replication.md)** — механизмы кворума, Oplog, Read/Write Concern, Initial Sync.
*   **[Высокая доступность](./high_availability.md)** — Replica Set, отказоустойчивость, Read Preference, Prometheus алерты.
*   **[Шардирование](./mongodb-sharding.md)** — распределение данных, CWWC, Config Shard, Balancer.
*   **[Решардинг (Live Resharding)](./mongodb-resharding.md)** — изменение ключа без простоя, forceRedistribution, prerequisites.
*   **[Движок WiredTiger](./mongodb-storage-engine.md)** — кэширование, чекпоинты, `cacheSizeGB`, compression.
*   **[Безопасность](./mongodb-security.md)** — RBAC, TLS, шифрование, Audit Log.
*   **[Индексы](./mongodb-indexes.md)** — compound index, ESR правило, стратегии индексирования.
*   **[Транзакции](./mongodb-transactions.md)** — ACID, snapshot isolation, PITR.
*   **[Time-series коллекции](./mongodb-time-series.md)** — bucketing, TTL, columnar compression.
*   **[Установка на Ubuntu](./installation_ubuntu.md)** — пошаговый процесс деплоя.
