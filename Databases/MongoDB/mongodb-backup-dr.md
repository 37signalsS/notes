# Бэкап и Disaster Recovery

**Актуально для:** MongoDB 8.0.x / 8.3.x, Percona Backup for MongoDB (PBM) 2.16.x

> **Совет по версии:** последний стабильный релиз MongoDB — 8.3 (май 2026), линия 8.0 активно патчится (8.0.29, август 2026). PBM 2.16.0 (сентябрь 2026) поддерживает MongoDB Community 7.0+ и Percona Server for MongoDB. нижеследующее описание корректно для этих линий.

---

## Определения

*   **RPO (Recovery Point Objective)** — максимально допустимая потеря данных во времени (например, «не более 5 минут»). Определяет частоту бэкапов и retention oplog.
*   **RTO (Recovery Time Objective)** — максимально допустимое время простоя до восстановления сервиса.
*   **PITR (Point-in-Time Recovery)** — восстановление на произвольный момент времени: полный бэкап + oplog (аналог WAL/Binlog в PostgreSQL/MySQL). Общая теория: **[Бэкапы](../../Databases/Concepts/backups.md)**.
*   **PBM (Percona Backup for MongoDB)** — open-source решение для физических бэкапов MongoDB: full + incremental, PITR через oplog, хранение в S3/файловой системе, сжатие, шифрование.
*   **Oplog (operations log)** — capped collection `local.oplog.rs`, хранящая все операции репликации. Основа PITR в MongoDB (аналог binlog в MySQL).
*   **Oplog Window** — временной диапазон, покрываемый oplog (размер oplog / скорость записи). Должен быть > RPO + время простоя.
*   **Snapshot (физический бэкап)** — копия файлов данных на уровне диска (LVM, EBS, CSI). Crash-consistent; требует `fsync`/`db.fsyncLock()` для application-consistent.
*   **Logical backup** — `mongodump` (BSON) / `mongoexport` (JSON/CSV). Медленнее физического, но гибче (выбор коллекций, кросс-версия).
*   **Quiesce** — приостановка записи (`db.fsyncLock()`) для согласованного снапшота.
*   **DR (Disaster Recovery) runbook** — пошаговая процедура восстановления после катастрофы (полная потеря кластера).

Правило **3-2-1-1-0** и уровни консистентности: **[Бэкапы (общая теория)](../../Databases/Concepts/backups.md)**.

---

## Базовые концепции

### Стратегии бэкапа MongoDB

| Стратегия | Инструмент | RPO | RTO | Когда |
| :--- | :--- | :--- | :--- | :--- |
| **Logical (mongodump)** | `mongodump` | Минуты | Долго (восстановление медленное) | Малые БД (< 100 GB), миграции |
| **Physical snapshot** | LVM/EBS/CSI | Минуты | Быстро | Большие БД, поддержка снапшотов |
| **PBM (full + incr + oplog)** | PBM | Секунды–минуты | Средне | Production, PITR |
| **Cloud Manager / Ops Manager** | MongoDB | Секунды | Быстро | Enterprise |

### Почему репликация — не бэкап

Репликация мгновенно тиражирует логические ошибки (`dropDatabase`, `delete` без фильтра) на все узлы. Бэкап — единственный способ откатиться к состоянию «до ошибки». См. **[Бэкапы (теория)](../../Databases/Concepts/backups.md)**.

### Oplog Window и PITR

```
Oplog Window = размер oplog / скорость записи (bytes/sec)
```

*   Для PITR oplog должен покрывать период от последнего бэкапа до текущего момента + запас.
*   Минимальный Oplog Window: `RPO + ожидаемое время обнаружения инцидента`.
*   Проверка: `rs.printReplicationInfo()` → `configured oplog size`, `log length start to end`.

### PBM архитектура

```
pbm-agent (на каждом mongod)
   │
   ├─► Full backup (logical или physical)
   ├─► Incremental backup (только physical, PSMDB)
   ├─► Selective backup (отдельные БД/коллекции)
   └─► Oplog backup (непрерывный, для PITR)
        │
        ▼
     S3 / MinIO / GCS / Azure / OCI / filesystem / NFS
```

*   **Logical backup** — `pbm backup` (умолчание). Использует `mongodump`-логику: выгружает BSON-снапшот данных через `$backupCursor`/`collStats`. Медленнее, но работает на Community Edition.
*   **Physical backup** — `pbm backup --type physical`. Копирует файлы WiredTiger через `$backupCursor`. Быстрее, требует Percona Server for MongoDB (для Community — только начиная с 7.0 и при определённых условиях).
*   **Incremental backup** — `pbm backup --type incremental --base <backup-name>`. Сохраняет только изменения после базового бэкапа. **Требует Percona Server for MongoDB** (из-за `$backupCursor`). Цепочка инкрементов привязана к узлу, на котором был сделан базовый бэкап.
*   **Oplog backup (PITR)** — включается через `pbm config --set pitr.enabled = true`. PBM резжет oplog на слои (span, по умолчанию 10 мин) и сохраняет их в хранилище. Позволяет восстановиться до любой секунды в пределах oplog window.
*   **Сжатие:** логические бэкапы — `gzip`, `snappy`, `lz4`, `s2`, `pgzip`, `zstd` (конфигурация `backup.compression`). Oplog-слои сжимаются отдельно (`pitr.compression`, по умолчанию `s2`).

### Бэкап шардированного кластера

Шардированный кластер требует согласованного бэкапа всех компонентов:

```
Config servers (RS)  →  бэкап (PBM или mongodump)
Shard 1 (RS)         →  бэкап
Shard 2 (RS)         →  бэкап
...
mongos               →  конфигурация (не данные)
```

**Варианты:**
1.  **PBM** — поддерживает шардированные кластеры (согласованный снапшот через `pbm`).
2.  **mongodump --oplog** на каждом шарде + config servers (менее согласованный).
3.  **Файловые снапшоты** — `db.fsyncLock()` на каждом шарде (остановка записи).

> **Важно:** для согласованного бэкапа шардированного кластера используйте PBM или остановите balancer + `fsyncLock` на всех шардах.

---

## Подготовка окружения (Prerequisites)

1.  **PBM:** установить `percona-backup-mongodb` на каждом узле.
    ```bash
    # Ubuntu/Debian
    sudo apt-get install percona-backup-mongodb
    ```
2.  **Хранилище:** S3-совместимое (MinIO, AWS S3) или NFS для PBM.
3.  **Пользователь:** роль `backup` и `restore` для PBM.
    ```javascript
    use admin
    db.createUser({ user: "pbm", pwd: passwordPrompt(),
                    roles: [ { role: "backup", db: "admin" },
                             { role: "restore", db: "admin" } ] })
    ```
4.  **Oplog:** размер oplog ≥ Oplog Window (см. выше).

---

## Практические сценарии

### 1. mongodump / mongorestore (логический)

```bash
# Полный бэкап с oplog (для PITR)
mongodump --host rs0/mongo-1:27017 \
  --username backup --password pass --authenticationDatabase admin \
  --oplog --gzip --archive=/backup/mongo_$(date +%F).gz

# Восстановление
mongorestore --host rs0/mongo-1:27017 \
  --username admin --password pass --authenticationDatabase admin \
  --gzip --archive=/backup/mongo_2026-10-04.gz \
  --oplogReplay
```

**Валидация:**
```bash
# Проверить содержимое архива
mongorestore --archive=/backup/mongo_2026-10-04.gz --dryRun

# Сравнить количество документов
mongosh --host rs0/mongo-1:27017 --eval "db.users.countDocuments()"
```

### 2. PBM: настройка

PBM конфигурируется через `pbm config` (сохраняет настройки в PBM control collection) или через YAML-файл, загружаемый командой `pbm config --file`.

```bash
# Через env variables (для быстрой настройки)
export PBM_MONGODB_URI="mongodb://pbm:pass@mongo-1:27017,mongo-2:27017,mongo-3:27017/?replicaSet=rs0&authSource=admin"
export PBM_S3_BUCKET="mongo-backups"
export PBM_S3_ENDPOINT="s3.example.com"
export PBM_S3_ACCESS_KEY_ID="..."
export PBM_S3_SECRET_ACCESS_KEY="..."

# Или через pbm config (пишется в control collection)
pbm config --set storage.s3.bucket=mongo-backups
pbm config --set storage.s3.endpoint=s3.example.com

# Включить PITR (oplog slicing)
pbm config --set pitr.enabled=true
# Продолжительность одного oplog-слоя (минут), по умолчанию 10
pbm config --set pitr.oplogSpanMin=10
# Сжатие oplog-слоев (s2 / gzip / snappy / lz4 / zstd)
pbm config --set pitr.compression=s2

# Проверить всю конфигурацию (секреты обрезаются)
pbm config --list
```

**Поддерживаемые типы хранилища (storage profiles):**
- AWS S3 (сигнатура SigV4)
- S3-совместимые: MinIO, Alibaba Cloud OSS, Ceph, self-hosted MinIO
- Google Cloud Storage (только через JSON-ключ; HMAC-аутентификация устарела и удалена)
- Oracle Cloud Infrastructure Object Storage (PBM 2.15.0+, включая Workload Identity)
- Azure Blob Storage
- Локальная filesystem / NFS

**Настройка retention (PBM 2.10.0+):**
PBM поддерживает модель **GFS (Grandfather-Father-Son)** через `lifecycle`:

```yaml
lifecycle:
  enabled: true
  strategy: rolling   # или calendar
  minKeep: 1          # минимум точек восстановления
  purgeFailed: false
  dailyRetention: 7
  weeklyRetention: 4
  monthlyRetention: 12
```

Конфигурация retention хранится в main config или в storage profile (для отдельных типов бэкапов).

### 3. PBM: полный бэкап

```bash
# Запуск full backup
pbm backup

# Список бэкапов
pbm list
# → 2026-10-04T10:00:00Z  full  rs0  15GB

# Статус
pbm status
```

### 4. PBM: PITR (Point-in-Time Recovery)

```bash
# Восстановление на момент времени (ISO8601)
pbm restore --time 2026-10-04T09:30:00Z

# Восстановление до конкретного oplog timestamp
pbm restore --oplog-timestamp 1759575000:1

# Начиная с PBM 2.14.0 restore требует подтверждения (-y/--yes)
pbm restore --time 2026-10-04T09:30:00Z --yes

# Восстановление конкретной коллекции/БД (selective restore, PBM 2.8.0+)
pbm restore --time 2026-10-04T09:30:00Z --ns mydb.users

# Восстановление с включением пользователей и ролей (PBM 2.13.0+)
pbm restore --ns "mydb.*" --with-users-and-roles <backup-name>

# Восстановление с откатом при ошибке (PBM 2.14.0+)
pbm restore --time 2026-10-04T09:30:00Z --fallback-enabled=true --allow-partly-done=true
```

**Процесс PITR:**
1.  PBM находит последний full backup перед указанным временем.
2.  Восстанавливает full.
3.  Применяет incremental backups.
4.  Применяет oplog до указанного момента.

**PBM backup types:**
- `pbm backup` — по умолчанию **logical** backup (mongodump-аналог)
- `pbm backup --type physical` — физический снапшот WiredTiger
- `pbm backup --type incremental --base <backup-name>` — инкрементальный (требует PSMDB, привязан к узлу)
- `pbm backup --type external` — внешний снапшот (через `pbm backup-finish`)

**PBM lifecycle-команды:**
- `pbm list` — список бэкапов и oplog-слоев (с валидными диапазонами для PITR)
- `pbm describe-backup <name> --with-collections` — детали бэкапа, включая коллекции
- `pbm cleanup` — удаление устаревших бэкапов согласно lifecycle-политике
- `pbm config --force-resync` — синхронизация метаданных с хранилищем (требуется после физического восстановления)

### 5. Физический снапшот (LVM/EBS)

```bash
# 1. Заблокировать запись (application-consistent)
mongosh --host rs0/mongo-1:27017 --eval "db.fsyncLock()"

# 2. Создать снапшот диска
lvcreate --size 10G --snapshot --name mongo_snap /dev/vg0/mongodb
# Или EBS: aws ec2 create-snapshot ...

# 3. Разблокировать запись
mongosh --host rs0/mongo-1:27017 --eval "db.fsyncUnlock()"
```

> **Важно:** `db.fsyncLock()` останавливает запись. Используйте на hidden secondary (см. **[Репликация](./mongodb-replication.md)**), чтобы не влиять на production.

### 6. Бэкап шардированного кластера (PBM)

```bash
# PBM автоматически согласует бэкап всех шардов и config servers
pbm backup

# Проверить, что все компоненты в бэкапе
pbm list
# → 2026-10-04T10:00:00Z  full  sharded  (configsvr, shard1, shard2)
```

**Альтернатива (mongodump):**
```bash
# Остановить balancer
mongosh --host mongos:27017 --eval "sh.stopBalancer()"

# Бэкап каждого шарда + config servers
# ВАЖНО: mongodump --oplog запускать на каждом шарде отдельно,
# подключаясь к Primary каждого Replica Set (не к mongos!)
for shard in shard1 shard2 configsvr; do
  mongodump --host ${shard}/mongo-1:27017 --oplog --gzip \
    --archive=/backup/${shard}_$(date +%F).gz
done

# Возобновить balancer
mongosh --host mongos:27017 --eval "sh.startBalancer()"
```

> **Ограничение `mongodump --oplog`:** флаг `--oplog` работает только при подключении к Replica Set ( mongod). При подключении к `mongos` (шардированный кластер) он **игнорируется** — дамп будет неконсистентным. Для бэкапа шардированного кластера либо подключайтесь к каждому шарду напрямую, либо используйте PBM.

### 7. DR Runbook: полная потеря кластера

**Сценарий:** потеряны все узлы Replica Set (или шардированного кластера).

```
Фаза 1: Оценка (0–15 мин)
├─ Подтвердить потерю (мониторинг, логи)
├─ Определить RPO/RTO
└─ Оповестить stakeholders

Фаза 2: Подготовка (15–30 мин)
├─ Поднять инфраструктуру (ВМ/диски/сеть)
├─ Установить MongoDB той же версии
└─ Подготовить хранилище бэкапов

Фаза 3: Восстановление (30–120 мин)
├─ PBM: pbm restore --time <последний_рабочий_момент>
├─ Или: mongorestore --oplogReplay из последнего dump
└─ Для шардированного: восстановить config servers, затем шарды

Фаза 4: Валидация (15–30 мин)
├─ Проверить countDocuments() на ключевых коллекциях
├─ Проверить rs.status() — есть Primary
├─ Прогнать smoke-тесты приложения
└─ Сверить контрольные суммы

Фаза 5: Переключение (5–15 мин)
├─ Обновить DNS / connection string
├─ Переключить приложение
└─ Мониторить 30+ минут

Фаза 6: Постмортем
├─ Timeline инцидента
├─ Root cause
└─ Action items (предотвращение)
```

**DR-тестирование:**
*   Тестируйте восстановление **минимум раз в квартал**.
*   Тестируйте в изолированной среде (не production).
*   Замеряйте фактический RTO — он часто больше ожидаемого.

### 8. Восстановление одной коллекции (PBM)

```bash
# PBM поддерживает восстановление на уровне namespace
pbm restore --time 2026-10-04T09:30:00Z --ns mydb.users
```

---

## Операции и команды (Reference)

| Операция | Команда |
| :--- | :--- |
| Logical backup | `mongodump --oplog --gzip --archive=<file>` |
| Logical restore | `mongorestore --oplogReplay --gzip --archive=<file>` |
| PBM full | `pbm backup` |
| PBM list | `pbm list` |
| PBM PITR | `pbm restore --time <ISO8601>` |
| PBM oplog-ts | `pbm restore --oplog-timestamp <ts:inc>` |
| Oplog Window | `rs.printReplicationInfo()` |
| Replication lag | `rs.printSecondaryReplicationInfo()` |
| Fsync lock | `db.fsyncLock()` / `db.fsyncUnlock()` |
| Balancer stop | `sh.stopBalancer()` / `sh.startBalancer()` |

---

## Устранение неполадок

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Oplog Window < RPO** | Малый oplog / высокая write-нагрузка | `rs.printReplicationInfo()` | Увеличить oplog (`rs.resizeOplog()`) |
| **PBM backup fails** | Нет прав / нет места в S3 | `pbm status`, логи agent | Роль `backup`, проверить S3 |
| **mongodump медленный** | Индексы, сеть | `mongostat` | `--gzip`, читать с hidden secondary |
| **Restore не консистентен** | Нет `--oplog` | Сравнение counts | Переснять с `--oplog` |
| **PITR не достигает момента** | Oplog не покрывает период | `rs.printReplicationInfo()` | Увеличить oplog, чаще full backup |
| **Шардированный restore не согласован** | Balancer работал | `sh.status()` | Остановить balancer перед бэкапом |

---

## Лучшие практики (SRE)

1.  **PBM для production:** full + incremental + oplog = PITR с RPO в секундах.
2.  **Oplog Window > RPO + время обнаружения** — иначе PITR невозможен.
3.  **3-2-1-1-0:** 3 копии, 2 носителя, 1 offsite, 1 immutable, 0 ошибок при тесте.
4.  **Тестируйте восстановление** раз в квартал (бэкап без теста — не бэкап).
5.  **Бэкап с hidden secondary** — не нагружайте Primary.
6.  **Шардированный кластер:** PBM или `stopBalancer` + `fsyncLock` на всех шардах.
7.  **Шифрование бэкапов** at rest и in transit (см. **[Безопасность бэкапов](../../Databases/Concepts/backup_security.md)**).
8.  **DR runbook** — документируйте и репетируйте; замеряйте фактический RTO.
9.  **Retention policy** — храните бэкапы по политике (например, 7 дней daily, 4 недели weekly, 12 месяцев monthly).
10. **PBM lifecycle (GFS):** настройте `dailyRetention` / `weeklyRetention` / `monthlyRetention` и `minKeep`. Запускайте `pbm cleanup` по расписанию.
11. **Мониторинг бэкапов:** настройте алерты на "отсутствие свежего успешного бэкапа", а не на "ошибку бэкапа". Используйте `pbm status` и метрики `mongodb_oplog_window_seconds`.

---

## Проверка целостности бэкапов (Validation)

Бэкап не считается существующим, пока его восстановление не протестировано. Подробная методика — **[Проверка целостности бэкапов](../../Databases/Concepts/backup_validation.md)**.

### Проверка PBM-бэкапа

```bash
# 1. Проверка статуса бэкапа
pbm describe-backup <backup-name>
# status: done — бэкап завершён успешно

# 2. Проверка, что бэкап не "partially done"
pbm status
# отсутствие активных операций и ошибок в control collections

# 3. Проверка PITR-готовности: oplog-слои должны обновляться
pbm list
# в разделе pitr — валидный диапазон времени для восстановления

# 4. Проверка целостности через control collections
# PBM автоматически проверяет согласованность при описании бэкапа;
# при обнаружении повреждённых чанков — команда завершается с ошибкой
```

### Тестовое восстановление (SRE-чеклист)

1.  **Раз в квартал** — полное восстановление в изолированной среде (отдельный сервер/namespace, без доступа к production).
2.  **Замеряйте реальный RTO** — время от начала восстановления до готовности приложения принимать соединения.
3.  **Проверяйте PITR** — восстановление на произвольную точку времени в пределах oplog window.
4.  **Проверяйте selective restore** — восстановление одной коллекции/БД без затрагивания остальных данных.
5.  **Smoke-тесты приложения:** `countDocuments()` на ключевых коллекциях, проверка ссылочной целостности, выполнение бизнес-запросов.
6.  **Маскирование данных:** при восстановлении в Dev/Staging удаляйте PII перед предоставлением доступа разработчикам.
7.  **Dead Man's Switch:** настройте алерт на "отсутствие успешной проверки бэкапа более N дней".

### Контрольные суммы и шифрование

*   Проверяйте, что бэкапы шифруются (на стороне PBM — через `backup.compression` + опционально KMS/Vault) и что ключи доступны.
*   Для локальных filesystem-бэкапов вычисляйте `sha256sum` до и после выгрузки, сравнивайте.
*   Используйте иммутабельное хранилище (S3 Object Lock) или ZFS snapshot `readonly` для защиты от Ransomware.

---

## Дополнительная информация

*   **[Репликация](./mongodb-replication.md)** — oplog, hidden secondary.
*   **[Высокая доступность](./high_availability.md)** — failover, Oplog Window.
*   **[Шардирование](./mongodb-sharding.md)** — balancer, согласованность бэкапа.
*   **[Импорт/экспорт](./mongodb-import-export.md)** — `mongodump`/`mongorestore`.
*   **[Бэкапы (общая теория)](../../Databases/Concepts/backups.md)** — RPO/RTO, PITR, 3-2-1-1-0.
*   **[Безопасность бэкапов](../../Databases/Concepts/backup_security.md)** — шифрование, KMS.
*   **[Проверка целостности бэкапов](../../Databases/Concepts/backup_validation.md)** — валидация.
*   **[Velero (Kubernetes)](../../Kubernetes/ToolsUtilities/velero-overview.md)** — бэкап K8s-RESOURCEов.
*   [Percona Backup for MongoDB](https://docs.percona.com/percona-backup-mongodb/)
*   [MongoDB Backup Methods](https://www.mongodb.com/docs/manual/core/backups/)
*   [PBM Release Notes](https://docs.percona.com/percona-backup-mongodb/release-notes/)
