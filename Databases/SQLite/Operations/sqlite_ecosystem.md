# Экосистема SQLite: Litestream, rqlite, инструменты

**Актуально для:** Litestream (LTX-формат), rqlite 8.x

## Определения

*   **Litestream** — инструмент непрерывной репликации SQLite: отдельный процесс, потоково копирующий WAL-страницы в реплику с возможностью восстановления на точку во времени (PITR).
*   **LTX (Litestream Transaction Log)** — формат файлов реплики Litestream: пакет WAL-страниц с монотонным TXID и контрольными суммами.
*   **rqlite** — распределённая СУБД на SQLite: single binary, репликация через консенсус Raft, доступ через HTTP API.
*   **dqlite** — встраиваемая распределённая SQLite (C-библиотека, Raft); используется в MicroK8s — см. [etcd-альтернативы](../../../Kubernetes/Concepts/etcd_alternatives_and_security.md).
*   **DB Browser for SQLite** — кроссплатформенный GUI для просмотра, редактирования и миграции БД (sqlitebrowser.org).

## Базовые концепции

### Как работает Litestream

Litestream перехватывает процесс чекпоинтинга: держит длительную read-транзакцию, которая не даёт другим процессам сбросить WAL, читает новые WAL-страницы и пакует их в LTX-файлы с монотонно возрастающим TXID и контрольными суммами.

*   **Компактификация**: L0 (файлы на каждый sync), L1/L2/L3 (мерж каждые ~30 сек / 5 мин / 1 час), snapshot (полная копия, по умолчанию 24 ч).
*   **Retention**: по умолчанию 24 ч; всегда хранится хотя бы один snapshot.
*   **Restore**: последний snapshot + replay LTX в порядке TXID. Целостность цепочки проверяется: разрыв в TXID → восстановление невозможно (ошибка `no matching backup files available`).
*   **Таргеты restore**: `-txid N` (inclusive) и `-timestamp T` (exclusive).
*   **RPO**: интервал синка (по умолчанию ~1 сек); репликация асинхронная.
*   **Требования**: WAL-режим (Litestream ставит его сам); рекомендуется `synchronous=NORMAL` и `PRAGMA wal_autocheckpoint=0` в приложении (чекпоинты делает Litestream).
*   **litestream-vfs** — экспериментальное расширение для read-реплик: читает страницы прямо из реплики.

### Как работает rqlite

rqlite — это SQLite за HTTP API с репликацией через Raft:

*   **HTTP API**: `/db/execute` (запись), `/db/query` (чтение), `/db/request` (unified endpoint).
*   **Параметризованные запросы** — защита от SQL-инъекций (SQL + значения в JSON-массиве).
*   **Read consistency**: уровни от `none` (локальная нода, быстро) до `strong` (через Raft log, линейлизуемо).
*   **Queued Writes** — режим, жертвующий durability ради пропускной способности записи.
*   **Read replicas** — ноды, не участвующие в кворуме, для масштабирования чтения.
*   **CDC** — стриминг изменений во внешнюю систему.
*   **Бэкапы**: hot backup, автоматические в S3/MinIO/GCS.
*   **Безопасность**: TLS, аутентификация, RBAC.
*   **CP-система**: при сетевом разделении работает только мажоритарная часть кластера.
*   Запись всегда идёт через Leader (клиент может писать на любую ноду — forwarding прозрачный); rqlite **не** масштабирует запись — Raft сериализует все записи.

### Когда что выбирать

| Задача | Решение |
| :--- | :--- |
| Непрерывный бэкап + PITR одной ноды | Litestream |
| HA-кластер SQLite с failover (2–3+ ноды) | rqlite |
| HA-хранилище внутри MicroK8s | dqlite (встроен) |
| Высококонкурентная запись (десятки писателей) | Клиент-серверная СУБД (PostgreSQL/MySQL) |
| Разовый просмотр/правка БД | DB Browser for SQLite |

## Практические сценарии

### 1. Litestream: локальная реплика (file://)

```bash
# Запуск репликации в локальный каталог
litestream replicate /var/lib/app/data.db file:///mnt/backup/litestream/app

# Восстановление (последнее состояние)
litestream restore -o /var/lib/app/data_restored.db file:///mnt/backup/litestream/app

# Восстановление на точку во времени
litestream restore -o restored.db -timestamp '2026-10-03T10:00:00Z' file:///mnt/backup/litestream/app

# Инспекция LTX-файлов реплики
litestream ltx file:///mnt/backup/litestream/app

# Сброс локального состояния трекинга (при невалидных метаданных)
litestream reset /var/lib/app/data.db
```

Конфигурация как сервис (файл-реплика на отдельном диске):

```yaml
dbs:
  - path: /var/lib/app/data.db
    replica:
      path: /mnt/backup/litestream/app
```

Управление демоном: `litestream replicate` запускает демон; `litestream start DB` / `litestream stop DB` — пауза/возобновление репликации для запущенного демона (требуется IPC-сокет в конфиге).

### 2. rqlite: кластер из трёх нод

```bash
# Нода 1 (Leader)
rqlited -node-id 1 -http-addr localhost:4001 -raft-addr localhost:4002 data1/

# Ноды 2 и 3 (присоединение к кластеру)
rqlited -node-id 2 -http-addr localhost:4003 -raft-addr localhost:4004 -join localhost:4002 data2/
rqlited -node-id 3 -http-addr localhost:4005 -raft-addr localhost:4006 -join localhost:4002 data3/

# Запись (любая нода прозрачно форвардит на Leader)
curl 'localhost:4001/db/execute' -H "Content-Type: text/plain" \
  -d 'CREATE TABLE foo (name TEXT, age INTEGER)'
curl 'localhost:4001/db/execute' -H "Content-Type: text/plain" \
  -d 'INSERT INTO foo(name, age) VALUES("fiona", 20)'

# Чтение
curl 'localhost:4001/db/query' -H "Content-Type: text/plain" \
  -d 'SELECT * FROM foo'

# Параметризованный запрос (защита от SQL injection)
curl 'localhost:4001/db/query' -H "Content-Type: application/json" \
  -d '[["SELECT * FROM foo WHERE name = ?", ["fiona"]]]'
```

### 3. Проверка восстановленной БД

```bash
# Восстановление из реплики Litestream
litestream restore -o /tmp/check.db file:///mnt/backup/litestream/app

# Обязательная проверка перед возвратом в продакшен
sqlite3 /tmp/check.db "PRAGMA integrity_check;"
# → ok
```

## Операции и команды

| Задача | Litestream | rqlite |
| :--- | :--- | :--- |
| Запуск | `litestream replicate DB [URL]` | `rqlited -node-id N -http-addr A -raft-addr B [-join ...] DIR` |
| Восстановление | `litestream restore -o FILE URL` | — |
| PITR | `litestream restore -timestamp T` / `-txid N` | — |
| Инспекция реплики | `litestream ltx URL` | — |
| Сброс состояния | `litestream reset DB` | — |
| Запись | — | `POST /db/execute` |
| Чтение | — | `POST /db/query` |
| Unified | — | `POST /db/request` |

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Litestream: конфликты чекпоинтов | Приложение делает свой checkpoint | `PRAGMA wal_autocheckpoint=0` в приложении |
| Litestream: `no matching backup files available` | Retention удалил L0 под snapshot | Увеличить `l0-retention` (например, `8760h`) |
| Litestream: невалидное локальное состояние | Метаданные трекинга повреждены | `litestream reset DB` (свежий snapshot на следующем sync) |
| Litestream: проблемы после удаления БД | Остался WAL-файл | Удалять `.db` и `.db-wal` вместе |
| rqlite: `no leader` | Нет кворума (меньше половины нод) | Поднять большинство нод; проверить сеть |
| rqlite: запись медленная | Raft round-trip на каждую запись | Queued Writes (если допустима потеря durability) |
| rqlite: разделение сети | CP-система | Работает только мажоритарная часть; heal автоматически |

## Рекомендации SRE

*   Litestream — стандартный выбор для DR одиночной SQLite-БД: реплицируйте на **отдельный физический диск** или хост.
*   С Litestream отключайте авточекпоинт приложения (`wal_autocheckpoint=0`) — чекпоинты делает Litestream.
*   Регулярно тестируйте восстановление (`litestream restore` + `integrity_check`) — бэкап без проверенного restore не является бэкапом.
*   rqlite — когда нужна HA без операционной сложности клиент-серверной СУБД; не для write-scaling.
*   Не запускайте два приложения в один и тот же replica-path Litestream.

## Дополнительная информация

### См. также

*   [WAL, конкурентность и эксплуатация](./sqlite_sre_operations.md) — чекпоинты и WAL
*   [Восстановление и диагностика](./sqlite_recovery_diagnostics.md) — проверка восстановленных БД
*   [etcd-альтернативы и dqlite](../../../Kubernetes/Concepts/etcd_alternatives_and_security.md) — dqlite в MicroK8s
*   [Официальная документация: Litestream](https://litestream.io/)
*   [Официальная документация: rqlite](https://rqlite.io/docs/)
