# Maintenance API etcd

**Актуально для:** etcd 3.7.x (patch v3.7.2)

## Определения

| Термин | Описание |
| :--- | :--- |
| **Maintenance Service** | gRPC-сервис `etcdserverpb.Maintenance` на клиентском порту etcd (2379): операции обслуживания узлов без остановки кластера. |
| **Status** | RPC статуса узла: версии, размеры БД, лидер, raft-позиции, learner-статус, информация о downgrade. |
| **HashKV** | RPC хеша MVCC-состояния на заданном revision; удерживает MVCC-блокировки, безопасен при живых транзакциях. |
| **Hash** | Устаревший RPC хеша без блокировок — только для тестов, не для production. |
| **Defragment** | RPC онлайн-дефрагментации BoltDB на одном узле. |
| **Snapshot** | Streaming RPC потоковой выгрузки снапшота БД. |
| **MoveLeader** | RPC передачи лидерства указанному follower (voter). |
| **Alarm** | RPC управления алармами: один метод с action GET/ACTIVATE/DEACTIVATE. |
| **Downgrade** | RPC подготовки отката версии кластера: validate/enable/cancel. |
| **etcd-dump-logs** | Утилита офлайн-чтения WAL и снапшотов (`tools/etcd-dump-logs` в etcd-repo). |

## Предварительные требования

- Кластер etcd 3.7.x; мажорная версия etcdctl совпадает с версией сервера (иначе возможны ошибки `method not found`).
- `grpcurl` для прямых gRPC-вызовов.
- TLS-материалы (`ca.crt`, `server.crt`, `server.key`) или `--insecure` в тестовом контуре.
- Для etcd-dump-logs: Go-тулчейн для сборки из исходников etcd.

## Основные концепции

### Endpoint и доступ

Maintenance API доступен на том же клиентском порту (2379), что и KV API — отдельного порта нет. Два транспорта:

- gRPC: `etcdserverpb.Maintenance/<Method>`
- REST через grpc-gateway: `POST /v3/maintenance/{status,defragment,hash,hashkv,snapshot,move-leader,downgrade,alarm}`

При включённом auth токен передаётся в заголовке; etcd снимает префикс `Bearer ` (`server/auth/store.go`), поэтому форма `authorization: Bearer <token>` корректна.

```bash
# gRPC-вызов через grpcurl
grpcurl -d '{"revision": 0}' \
  -H "authorization: Bearer $(cat /var/lib/etcd/token)" \
  --cacert /etc/etcd/ca.crt \
  --cert /etc/etcd/server.crt \
  --key /etc/etcd/server.key \
  10.0.1.10:2379 \
  etcdserverpb.Maintenance/HashKV

# Тот же вызов через REST-gateway
curl -s --cacert /etc/etcd/ca.crt --cert /etc/etcd/server.crt --key /etc/etcd/server.key \
  -X POST -d '{"revision": 0}' \
  https://10.0.1.10:2379/v3/maintenance/hashkv
```

### Полный список RPC (etcd 3.7.2, etcdserverpb/rpc.proto)

| RPC | Запрос | Ответ | Назначение |
| :--- | :--- | :--- | :--- |
| `Status` | `{}` | version, dbSize, leader, raftIndex, raftTerm, raftAppliedIndex, errors, dbSizeInUse, isLearner, storageVersion, dbSizeQuota, downgradeInfo | Статус узла |
| `Defragment` | `{}` | `{}` | Дефрагментация BoltDB на узле |
| `Hash` | `{}` | hash, revision | Хеш без блокировок (**deprecated**, только тесты) |
| `HashKV` | `{revision}` | hash, compact_revision, hash_revision | Хеш MVCC-состояния на revision |
| `Snapshot` | `{}` | stream: header, remaining_bytes, blob, version | Потоковая выгрузка снапшота |
| `MoveLeader` | `{targetID}` | `{}` | Передача лидерства follower |
| `Downgrade` | `{action, version}` | `{}` | validate/enable/cancel downgrade |
| `Alarm` | `{action, memberID, alarm}` | header, alarms | GET/ACTIVATE/DEACTIVATE алармов |

RPC для работы с WAL (`WALCheckpoint`, `WALRepair`, `WALList`) **не существуют** — WAL не обслуживается через Maintenance API (см. раздел про WAL).

### Status: статус узла

```bash
etcdctl endpoint status --cluster -w table
# Колонки: endpoint, ID, version, storage version, db size, in use,
# percentage not in use, quota, is leader, is learner, raft term,
# raft index, raft applied index, errors, downgrade target version,
# downgrade enabled

etcdctl endpoint status --cluster -w json
# → [{"endpoint":"https://10.0.1.10:2379","status":{"header":{"member_id":"8e9e05f54f240d12",...},
#     "version":"3.7.2","dbSize":"20971520","leader":"8e9e05f54f240d12","raftIndex":"1234",
#     "raftTerm":"5","raftAppliedIndex":"1234","errors":null,"dbSizeInUse":"18874368",
#     "isLearner":false,"storageVersion":"3.7","dbSizeQuota":"8589934592",
#     "downgradeInfo":{"target_version":"","enabled":false}}}]
```

**`percentage not in use`** — доля свободного места в файле БД, которую вернёт дефрагментация (`100 - dbSizeInUse*100/dbSize`). Большое значение — сигнал выполнить defrag.

### HashKV: проверка целостности данных

```bash
# Хеш на всех узлах (по умолчанию — на последнем compacted revision)
etcdctl endpoint hashkv --cluster -w table
# → +----------------+------------+---------------+
# → |   ENDPOINT     |    HASH    | HASH_REVISION |
# → +----------------+------------+---------------+
# → | 10.0.1.10:2379 | 1234567890 |         12345 |
# → | 10.0.1.11:2379 | 1234567890 |         12345 |
# → +----------------+------------+---------------+

# Хеш на конкретном revision
etcdctl endpoint hashkv --cluster --rev 12345
```

**Валидация:** совпадение HASH при совпадении HASH_REVISION означает идентичность MVCC-состояния узлов. Если hash_revision различается (отставание follower), хеши тоже будут различаться — это нормально. Различие хешей при одинаковом hash_revision указывает на рассинхронизацию или коррупцию.

### Defragment: дефрагментация

- Выполняется на ОДНОМ узле и не реплицируется — каждый узел дефрагментируется отдельно.
- Блокирует чтение и запись на узле на время выполнения.
- Внутри: создаётся новый BoltDB-файл, копируются только живые страницы, старый файл заменяется новым.

```bash
# Один узел
etcdctl defrag --endpoints=https://10.0.1.10:2379
# → Finished defragmenting etcd member[10.0.1.10:2379]. took = 1.2s

# Весь кластер (поочерёдно, последовательно)
etcdctl defrag --cluster
```

### Snapshot: потоковый снапшот

Единственный способ получить снапшот без доступа к файловой системе узла. `etcdctl snapshot save` использует именно этот RPC:

```bash
etcdctl snapshot save /backup/etcd-snapshot.db
# → Snapshot saved at /backup/etcd-snapshot.db
# → Server version 3.7.2
```

Прямой gRPC-вызов возвращает поток JSON-сообщений с полем `blob` (base64); для сборки бинарного файла нужно декодировать и склеить blobs — `etcdctl snapshot save` делает это автоматически:

```bash
grpcurl -d '{}' \
  --cacert /etc/etcd/ca.crt --cert /etc/etcd/server.crt --key /etc/etcd/server.key \
  10.0.1.10:2379 \
  etcdserverpb.Maintenance/Snapshot
```

### MoveLeader: передача лидерства

```bash
# ID цели — из `etcdctl member list -w table` (follower, voter)
etcdctl move-leader 9f1a06e632f85c1e
# → Leadership transferred from 8e9e05f54f240d12 to 9f1a06e632f85c1e
```

Цель — follower-узел (voter); learner не может быть назначен лидером. Используется перед обслуживанием текущего лидера (дефрагментация, обновление, замена узла).

### Alarm: управление алармами

Один RPC с action. Типы алармов: `NONE`, `NOSPACE` (БД достигла квоты), `CORRUPT` (повреждение raft-лога).

```bash
# Список активных алармов
etcdctl alarm list
# → memberID:8e9e05f54f240d12 alarm:NOSPACE

# Сброс аларма — disarm принимает НОЛЬ аргументов и сбрасывает ВСЕ алармы
etcdctl alarm disarm
```

### Downgrade: подготовка отката версии

Механизм подготовки кластера к откату на младшую мажорную версию (например, 3.7 → 3.6). Поддерживается с etcd 3.5.

```bash
# Проверка возможности отката на 3.5
etcdctl downgrade validate 3.5
# → Downgrade validate success, cluster version 3.6.0

# Активация режима отката
etcdctl downgrade enable 3.5
# → Downgrade enable success, cluster version 3.6.0

# Отмена начатого downgrade
etcdctl downgrade cancel
# → Downgrade cancel success, cluster version 3.6.0
```

### Hash (deprecated): только для тестов

`Hash` вычисляет хеш без удержания MVCC-блокировок, поэтому при живых транзакциях результат нестабилен. В документации etcd: «This is designed for testing ONLY! Do not rely on this in production with ongoing transactions... Use HashKV API instead». Для проверок используйте `HashKV`.

### WAL: нет online RPC

WAL не обслуживается через Maintenance API — в сервисе нет RPC для checkpoint/repair/list сегментов. Целостность WAL проверяется автоматически при старте узла; повреждение фиксируется алармом `CORRUPT`.

- Расположение: `<data-dir>/member/wal/` (сегменты вида `0000000000000000-0000000000000000.wal`), снапшоты — `<data-dir>/member/snap/`.
- Старые сегменты WAL усекаются автоматически при создании снапшотов.
- `etcdutl` **не имеет** wal-команды (в v3.7.2 зарегистрированы только: defrag, snapshot, hashkv, version, completion, migrate).
- Для ручной диагностики — утилита `etcd-dump-logs` (см. сценарий ниже).

## Практические сценарии

### Плановое обслуживание без остановки

```bash
# 1. Передать лидерство на follower
etcdctl move-leader 9f1a06e632f85c1e
# → Leadership transferred from 8e9e05f54f240d12 to 9f1a06e632f85c1e

# 2. Дефрагментация бывшего лидера (теперь follower)
etcdctl defrag --endpoints=https://10.0.1.10:2379
# → Finished defragmenting etcd member[10.0.1.10:2379]. took = 1.2s

# 3. Проверка здоровья кластера
etcdctl endpoint health --cluster -w table
# → +----------------+---------+-------+-------+
# → |   ENDPOINT     | HEALTH  | TOOK  | ERROR |
# → +----------------+---------+-------+-------+
# → | 10.0.1.10:2379 |  true   | 12ms  |       |
# → +----------------+---------+-------+-------+
```

### Проверка согласованности данных после обновления

```bash
# Сравнить хеши на всех узлах
etcdctl endpoint hashkv --cluster -w table

# Если хеши разные — сравнить hash_revision и проверить логи
journalctl -u etcd -n 100 | grep -i "error\|corrupt\|inconsistent"
```

### Восстановление после аларма NOSPACE

Аларм `NOSPACE` возникает при достижении квоты БД (`dbSizeQuota`, по умолчанию 2 ГБ на узел). Порядок восстановления:

```bash
# 1. Текущий revision
rev=$(etcdctl endpoint status --write-out=json | egrep -o '"revision":[0-9]*' | egrep -o '[0-9].*')

# 2. Компактция до текущего revision
etcdctl compact $rev

# 3. Дефрагментация каждого узла по очереди
etcdctl defrag

# 4. Сброс аларма (disarm без аргументов сбрасывает все алармы)
etcdctl alarm disarm

# 5. Проверка записи
etcdctl put probe-key probe-value
```

Диагностика заполнения: метрика `etcd_mvcc_db_total_size_in_use_in_bytes` — фактическое использование БД; `etcd_mvcc_db_total_size_in_bytes` — размер файла включая свободное место (до v3.4 называлась `etcd_debugging_mvcc_db_total_size_in_bytes`).

### Диагностика WAL через etcd-dump-logs

```bash
# Установка
go install go.etcd.io/etcd/v3/tools/etcd-dump-logs@latest

# Дамп WAL узла (data-dir содержит member/wal и member/snap)
etcd-dump-logs /var/lib/etcd

# Фильтр по типу записи и диапазону raft-индексов
etcd-dump-logs --wal-dir /var/lib/etcd/member/wal \
  --entry-type IRRPut --start-index 100 --end-index 200 /var/lib/etcd
```

Типы записей (`--entry-type`): `ConfigChange`, `Normal`, `Request`, `InternalRaftRequest`, `IRRRange`, `IRRPut`, `IRRDeleteRange`, `IRRTxn`, `IRRCompaction`, `IRRLeaseGrant`, `IRRLeaseRevoke`. Дополнительные флаги: `-start-snap`, `-stream-decoder`.

### Проверка возможности downgrade

```bash
# Перед откатом версии — валидация совместимости
etcdctl downgrade validate 3.5
# → Downgrade validate success, cluster version 3.6.0
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `defrag` блокирует узел надолго | БД > 20 ГБ или медленный диск | Часы минимальной нагрузки; поочерёдно на узлах |
| `hashkv` — разные хеши | Разный hash_revision (отставание follower) либо рассинхронизация/коррупция | Сравнить hash_revision; при совпадении — проверить логи, восстановить из снапшота |
| `maintenance: method not found` | Клиент новее сервера: метод отсутствует в серверной версии | Понизить etcdctl до версии сервера или обновить сервер |
| Snapshot через API медленный | Большая БД | Снапшот уровня хранилища (LVM/volume snapshot) или копия data-dir остановленного узла |
| `etcdutl wal ...: unknown command` | etcdutl не имеет wal-команды | Использовать etcd-dump-logs |
| `alarm disarm` не сбрасывает конкретный аларм | disarm принимает ноль аргументов и сбрасывает все алармы | Сначала `alarm list`, затем `alarm disarm` |
| `move-leader` отказывает | Цель — learner или недоступный узел | Передать лидерство voter-follower |

## Best Practices

- **HashKV вместо Hash:** для проверок целостности используйте только HashKV — Hash не удерживает MVCC-блокировки и годен только для тестов.
- **HashKV после изменений топологии:** сравнивайте хеши после rolling upgrade, замены узлов, restore.
- **Defrag по очереди:** никогда не дефрагментируйте все узлы одновременно — каждый узел блокируется на время выполнения.
- **MoveLeader перед обслуживанием:** снимайте нагрузку с лидера перед дефрагментацией или обновлением.
- **Большие БД:** для снапшотов используйте хранилищный уровень (LVM/volume snapshot), а не Snapshot API.
- **WAL не обслуживается через API:** целостность проверяется при старте узла; для ручной диагностики — etcd-dump-logs.

## Откат и очистка

- `etcdctl downgrade cancel` — отменить начатый downgrade.
- Удалить временные снапшоты: `rm /backup/etcd-snapshot.db`.
- После восстановления от NOSPACE: `etcdctl alarm list` должен возвращать пустой результат.

## См. также

* **[Шпаргалка etcdctl](./etcdctl_cheatsheet.md)** — команды maintenance.
* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — restore и DR.
* **[Внутреннее устройство хранения](./storage_internals.md)** — BoltDB и defrag internals.
* **[Устранение неисправностей](./troubleshooting.md)** — типовые проблемы etcd.
* **[Стратегии резервного копирования](./backup_strategies.md)** — снапшоты и backup.
