# Cheatsheet: etcdctl — полный справочник команд

**Актуально для:** etcd 3.7.x (основные команды неизменны с 3.5; `etcdutl` и колонки `STORAGE VERSION`/`DB SIZE IN USE` в `endpoint status` — с 3.6)

Справочник по CLI-утилите `etcdctl` для управления кластером etcd. Содержит основные команды с флагами, примерами и ожидаемым выводом. Команды сгруппированы по областям: KV-операции, watch, lease, concurrency, cluster, maintenance, RBAC, backup/restore. Полный список команд и флагов — в `etcdctl --help` и `etcdctl options`.

## Определения

| Термин | Определение |
|--------|-------------|
| **etcdctl** | CLI-утилита для управления etcd: чтение/запись данных, управление кластером, мониторинг, бэкап |
| **ETCDCTL_API** | Версия API etcdctl: `2` или `3`. С etcd 3.4 по умолчанию `3`. API v2 удалена из сервера etcd в 3.6 (флаг `--enable-v2` удалён) — для etcd 3.6+ работает только v3 |
| **KV** | Key-Value операции (get, put, del, txn) — основной API etcd |
| **Watch** | Механизм подписки на изменения ключей. Реализован как gRPC-стрим (bidirectional streaming), не long-polling |
| **Lease** | Аренда с TTL — механизм автоматического удаления ключей по истечении времени |
| **Compact** | Удаление старых ревизий из истории MVCC. Команда: `etcdctl compaction <revision>` (`compact` работает как префикс благодаря prefix matching в cobra) |
| **Defrag** | Дефрагментация BoltDB — возврат места в ОС. Онлайн-операция, блокирует чтение/запись на узле |
| **Alarm** | Сигнал о проблеме с кластером. Типы: `NOSPACE` и `CORRUPT`. Алармы не распространяются автоматически между участниками — каждый узел хранит свои |
| **MVCC** | Multi-Version Concurrency Control — модель версионирования etcd. Каждая запись имеет уникальную ревизию |
| **BoltDB** | Встроенная key-value БД (bbolt), хранилище etcd. Файл `member/snap/db`. Фрагментируется при обновлениях и удалениях ключей (свободные страницы остаются в freelist); для возврата места в ОС требуется дефрагментация |
| **Lease ID** | 64-битное число, генерируемое сервером (лидером) при `lease grant`, если клиент не указало ID явно |

## Основные концепции

### Переменные окружения

```bash
export ETCDCTL_API=3                          # версия API (v3 — по умолчанию с 3.4)
export ETCDCTL_ENDPOINTS="https://10.0.0.11:2379,https://10.0.0.12:2379,https://10.0.0.13:2379"
export ETCDCTL_USER="admin:password"          # формат username[:password]
export ETCDCTL_PASSWORD="password"            # пароль отдельно от пользователя
export ETCDCTL_CACERT="/etc/kubernetes/pki/etcd/ca.crt"
export ETCDCTL_CERT="/etc/kubernetes/pki/etcd/server.crt"
export ETCDCTL_KEY="/etc/kubernetes/pki/etcd/server.key"
export ETCDCTL_DIAL_TIMEOUT=5                 # тайм-аут подключения, сек (по умолчанию 2)
export ETCDCTL_COMMAND_TIMEOUT=5              # тайм-аут выполнения команды, сек (по умолчанию 5)
export ETCDCTL_KEEPALIVE_TIME=2               # gRPC keepalive, сек (по умолчанию 2)
export ETCDCTL_KEEPALIVE_TIMEOUT=6            # тайм-аут keepalive, сек (по умолчанию 6)
export ETCDCTL_MAX_REQUEST_BYTES=2097152      # макс. размер запроса, байт (по умолчанию 2 MiB)
export ETCDCTL_MAX_RECV_BYTES=2147483647      # макс. размер ответа, байт (по умолчанию MaxInt32)
export ETCDCTL_AUTH_JWT_TOKEN="token"         # JWT-токен (при --auth-token=jwt)
export ETCDCTL_DISCOVERY_SRV="example.com"    # DNS SRV-обнаружение кластера
```

**Правила именования:** любой глобальный флаг `--foo-bar` доступен как переменная `ETCDCTL_FOO_BAR` (префикс `ETCDCTL_`, буквы в верхнем регистре, дефисы заменены подчёркиваниями). Переменные с префиксом `ETCDCTL_` работают **только** для глобальных флагов. `ETCDCTL_API` — специальная переменная для внутреннего использования etcdctl.

### Форматы вывода

```bash
etcdctl --write-out=simple ...   # по умолчанию, человекочитаемый
etcdctl --write-out=json ...     # JSON (ключи и значения кодируются в base64)
etcdctl --write-out=protobuf ... # бинарный protobuf
etcdctl --write-out=fields ...   # поля через табуляцию
etcdctl --write-out=table ...    # таблица (для endpoint, member, snapshot status)
```

### Глобальные флаги

```bash
etcdctl --endpoints=... --dial-timeout=2 --command-timeout=5 \
  --keepalive-time=2 --keepalive-timeout=6 \
  --max-request-bytes=2097152 --max-recv-bytes=2147483647 \
  --insecure-transport --insecure-skip-tls-verify \
  --cert=... --key=... --cacert=... --user=... --password=... ...
```

Полный список: `etcdctl options` (появилась в 3.6+).

### gRPC и маршрутизация команд

Все команды etcdctl выполняются через gRPC. Разные группы команд используют разные сервисы: KV-операции (get/put/del/txn/compaction) — `/etcdserverpb.KV/*`, watch — `/etcdserverpb.Watch/*`, lease — `/etcdserverpb.Lease/*`, cluster (member/move-leader) — `/etcdserverpb.Cluster/*`, maintenance (endpoint/defrag/snapshot/alarm) — `/etcdserverpb.Maintenance/*`, auth/user/role — `/etcdserverpb.Auth/*`. Подключение инициализируется при каждой команде (нет глобального keep-alive между вызовами etcdctl).

### Теория: Lease (аренда)

- **TTL**: время жизни аренды в секундах. Минимальный TTL = `ceil(1.5 × election-timeout)` (при дефолтном `election-timeout=1s` — **2 секунды**); запрошенный TTL ниже минимума продлевается до минимума. Максимальный TTL = `9 000 000 000` секунд (~285 лет, константа `MaxLeaseTTL` в `server/lease/lessor.go`); превышение возвращает ошибку `etcdserver: too large lease TTL`
- **Экспири**: лидер проверяет истёкшие аренды каждые **500 мс** (цикл `runLoop` lessor'а); revoked-аренды удаляются в течение ~500 мс (при ошибке revoke — повтор через 3 с)
- **Keep-alive**: клиент отправляет продление каждые `TTL/3` секунд; продления не проходят через raft — они форвардятся на лидера напрямую
- **Checkpoint**: оставшийся TTL сохраняется в consensus-log каждые 5 минут, но только при включённом LeaseCheckpoint (выключен по умолчанию: 3.5 — `--experimental-enable-lease-checkpoint=true`, 3.6/3.7 — `--feature-gates=LeaseCheckpoint=true`); persist remainingTTL в backend автоматический при cluster version ≥ 3.6
- **Скорость revoke**: не более 1000 аренд в секунду (`leaseRevokeRate`)
- **В Kubernetes** контроллеры используют leases для лидерских выборов (объекты `coordination.k8s.io/v1/Lease`)

### Теория: Watch

- **Стрим**: gRPC bidirectional stream; watch требует наличия лидера (клиент использует `WithRequireLeader`)
- **Буфер**: у каждого watcher ограниченный буфер событий. Если клиент не успевает читать события (например, отстал от компакции), сервер помечает watcher как «victim» и отменяет его пакетно; клиент получает ответ с установленным `CompactRevision`, а clientv3 возвращает ошибку `mvcc: required revision has been compacted`. Ошибки «watch store is out of space» в etcd нет
- **Метрики**: `etcd_debugging_mvcc_slow_watcher_total`, `etcd_debugging_mvcc_watcher_total`, `etcd_debugging_mvcc_watch_stream_total`
- **Progress notify**: с `--progress-notify` сервер периодически присылает `progress notify: <revision>` — подтверждение, что стрим жив и клиент на текущей ревизии

### Теория: Compact и Defrag

- **Compact** — удаление старых ревизий из истории MVCC. Блокирует чтение по старым ревизиям, но **не уменьшает** размер файла на диске
- **Defrag** — онлайн-операция, блокирует чтение и запись на узле пока rebuild'ит состояние. Запрос **не реплицируется** по кластеру — применяется только к локальному узлу; укажите все участники через `--endpoints` или `--cluster`
- **Параллельная дефрагментация нескольких узлов недопустима**: дефрагментация блокирует чтение/запись на узле, одновременная дефрагментация всех участников делает кластер недоступным — выполняйте поочередно, узел за узлом
- **Офлайн-дефрагментация** через `etcdutl defrag --data-dir` блокирует запуск etcd до завершения (data-dir занят утилитой)

### Авто-компакция на сервере etcd

```bash
# Флаги сервера etcd (не etcdctl!)
etcd --auto-compaction-mode=periodic --auto-compaction-retention=1h
```

- `--auto-compaction-mode`: `periodic` (по умолчанию) или `revision`
- `--auto-compaction-retention`: окно сохраняемой истории. Дефолт `0` — авто-компакция **отключена**
- **periodic**: значение — сколько истории хранить. Если окно > 1 часа — компакция выполняется каждый час, сохраняя полное окно; если окно ≤ 1 часа — компакция выполняется с интервалом, равным окну. Без единицы времени — часы: `5` = 5 часов
- **revision**: компакция, когда `текущая revision - retention` достигает цели; запускается каждые 5 минут при достаточном прогрессе
- **В Kubernetes**: kube-apiserver запускает **собственный** компактор каждые **5 минут** по умолчанию (`DefaultCompactInterval` в `staging/src/k8s.io/apiserver/pkg/storage/storagebackend/config.go`), сохраняя ~5 минут истории; он обращается к etcd с Compaction RPC, а не через флаг `--auto-compaction-retention` etcd-сервера

## Практические сценарии

### Базовые операции (CRUD)

#### Проверка версии и endpoints

```bash
# Версия etcdctl (две строки: версия утилиты и версия API)
etcdctl version
# etcdctl version: 3.7.2
# API version: 3.7

# Проверка endpoints (здоровье: линейизуемое чтение + коммит тестовой записи)
etcdctl endpoint health --cluster
# 10.0.0.11:2379 is healthy: successfully committed proposal: took = 2.095242ms
# 10.0.0.12:2379 is healthy: successfully committed proposal: took = 1.876543ms
# 10.0.0.13:2379 is healthy: successfully committed proposal: took = 2.112456ms

# Статус endpoints (версия, размер БД, лидер, raft-индексы)
etcdctl endpoint status --cluster -w table
```

**Валидация:** `endpoint health` должен показать `is healthy` для каждого узла; `endpoint status` — одинаковые `VERSION` на всех узлах и ровно один `IS LEADER=true`.

#### Запись данных (put)

```bash
# Простая запись
etcdctl put /config/app/key1 "value1"
# OK

# Запись с арендой (TTL 60 секунд)
etcdctl put /config/app/key2 "value2" --lease=123456

# Запись с возвратом предыдущего значения
etcdctl put /config/app/key1 "new_value" --prev-kv

# Запись только значения (без ключа) — для обновления значения существующего ключа
etcdctl put /config/app/key1 --ignore-value
# (значение читается из stdin)

# Запись только аренды (без изменения значения)
etcdctl put /config/app/key1 --ignore-lease --lease=123456

# Значение из stdin (если значение не указано, читается из stdin)
echo "multi
line
value" | etcdctl put /config/app/key3
# (многострочные значения требуют двойных кавычек при передаче аргументом)

# Значение, начинающееся с дефиса — используйте "--" разделитель
etcdctl put /config/app/key4 -- "-value-starting-with-dash"
```

**Флаги put:** `--lease=<id>`, `--prev-kv`, `--ignore-value`, `--ignore-lease`.

#### Чтение данных (get)

```bash
# Простое чтение
etcdctl get /config/app/key1
# /config/app/key1
# value1

# Чтение по префиксу
etcdctl get /config/app/ --prefix

# Чтение с лимитом
etcdctl get /config/ --prefix --limit=10

# Чтение с сортировкой (по ключу, имени, ревизии создания/модификации или значению)
etcdctl get /config/ --prefix --sort-by=KEY --order=ASCEND
# --sort-by: CREATE | KEY | MODIFY | VALUE | VERSION
# --order: ASCEND | DESCEND

# Чтение только ключей (без значений)
etcdctl get /config/ --prefix --keys-only

# Чтение только значений (без ключей)
etcdctl get /config/app/key1 --print-value-only

# Чтение с определённой ревизии (историческое чтение)
etcdctl get /config/app/key1 --rev=1000

# Чтение всех ключей (пустой prefix + от начала)
etcdctl get "" --from-key --prefix

# Чтение в hex-формате (для бинарных ключей)
etcdctl get /config/app/key1 --hex

# Чтение с фильтрами по ревизиям
etcdctl get /config/ --prefix --min-create-revision=100 --max-create-revision=200
etcdctl get /config/ --prefix --min-mod-revision=100 --max-mod-revision=200

# Чтение с уровнем согласованности: l (linearizable, по умолчанию) или s (serializable)
etcdctl get /config/app/key1 --consistency=s

# Чтение в JSON (ключи и значения в base64)
etcdctl get /config/app/key1 -w json
# {"header":{"cluster_id":...,"member_id":...,"revision":123,"raft_term":5},"kvs":[{"key":"L2NvbmZpZy9hcHAva2V5MQ==","value":"dmFsdWUx","create_revision":"1","mod_revision":"1","version":"1"}],"count":"1"}
```

**Флаги get:** `--hex`, `--limit`, `--prefix`, `--order`, `--sort-by`, `--rev`, `--print-value-only`, `--consistency`, `--from-key`, `--keys-only`, `--min-create-revision`, `--max-create-revision`, `--min-mod-revision`, `--max-mod-revision`.

**Типичные ошибки и решения (get):**

| Ошибка | Причина | Решение |
|---------------------------|---------|---------|
| Пустой вывод при `--prefix` | Префикс не совпадает ни с одним ключом | Проверьте префикс: `etcdctl get "" --from-key --prefix --keys-only` |
| `mvcc: required revision has been compacted` | Запрошена ревизия старше compacted revision | Используйте текущую ревизию или более свежую |
| `mvcc: required revision is a future revision` | Запрошена ревизия новее текущей | Проверьте текущую ревизию: `etcdctl endpoint status -w json` (поле `header.revision`) |

#### Удаление данных (del)

```bash
# Удаление одного ключа
etcdctl del /config/app/key1
# 1

# Удаление по префиксу
etcdctl del /config/app/ --prefix
# 3

# Удаление с возвратом удалённых значений
etcdctl del /config/app/key1 --prev-kv

# Удаление всех ключей, начиная с указанного
etcdctl del /config/app/ --from-key
```

**Флаги del:** `--prefix`, `--prev-kv`, `--from-key`. Возвращает число удалённых ключей.

### Watch (подписка на изменения)

```bash
# Подписка на изменения ключа (с текущей ревизии)
etcdctl watch /config/app/key1
# PUT
# /config/app/key1
# new_value

# Подписка с определённой ревизии (все события после revision X)
etcdctl watch /config/app/ --rev=1000

# Подписка по префиксу
etcdctl watch /config/app/ --prefix

# Подписка с возвратом предыдущих значений
etcdctl watch /config/app/ --prefix --prev-kv

# Подписка с progress-notify (периодическое подтверждение живости стрима)
etcdctl watch /config/app/ --progress-notify
# progress notify: 12345

# Интерактивный режим (команды watch/put/del в одной сессии)
etcdctl watch /config/app/ --interactive

# Выполнение команды при каждом событии (после "--")
etcdctl watch /config/app/ -- echo "watch event received"
# (переменные окружения для команды: ETCD_WATCH_REVISION, ETCD_WATCH_EVENT_TYPE,
#  ETCD_WATCH_KEY, ETCD_WATCH_VALUE)

# Watch через переменные окружения (ключ и/или конец диапазона)
export ETCDCTL_WATCH_KEY="/config/app/"
export ETCDCTL_WATCH_RANGE_END="/config/app0"
etcdctl watch
```

**Флаги watch:** `--hex`, `--interactive`/`-i`, `--prefix`, `--rev`, `--prev-kv`, `--progress-notify`.

**Типичные ошибки и решения (watch):**

| Ошибка | Причина | Решение |
|---------------------------|---------|---------|
| `watch was canceled (...)` | Watcher отменён сервером (клиент отстал от компакции) | Переподключитесь с последней известной ревизии (`--rev=<revision>`) |
| `etcdserver: no leader` | Нет лидера — watch требует лидера | Проверьте здоровье кластера: `etcdctl endpoint health --cluster` |
| `context canceled` | Клиент отключился раньше времени | Нормальное завершение при Ctrl+C |

### Lease (аренда)

```bash
# Создание аренды с TTL 60 секунд
etcdctl lease grant 60
# lease 1234567890 granted with TTL(60s)

# Привязка ключа к аренде
etcdctl put /config/app/key1 "value1" --lease=1234567890

# Однократное продление аренды (с немедленным выходом)
etcdctl lease keep-alive 1234567890 --once
# lease 1234567890 renewed with TTL(60)

# Постоянное продление (стрим, пока не прервано Ctrl+C)
etcdctl lease keep-alive 1234567890
# lease 1234567890 renewed with TTL(60)
# (при экспириции аренды стрим завершается: lease ... expired or revoked.)

# Проверка оставшегося TTL
etcdctl lease timetolive 1234567890
# lease 1234567890 granted with TTL(60), remaining(45)

# То же с выводом привязанных ключей
etcdctl lease timetolive 1234567890 --keys

# Список всех активных аренд
etcdctl lease list
# 1234567890
# 1234567891

# Отзыв аренды (немедленное удаление всех привязанных ключей)
etcdctl lease revoke 1234567890
# lease 1234567890 revoked
```

**Типичные ошибки и решения (lease):**

| Ошибка | Причина | Решение |
|---------------------------|---------|---------|
| `etcdserver: too large lease TTL` | TTL превышает максимум (9e9 с) | Укажите TTL ≤ 9 000 000 000 |
| `etcdserver: requested lease not found` | Аренда с таким ID не существует | Создайте аренду: `etcdctl lease grant 60` |
| TTL в выводе grant больше запрошенного | Запрошенный TTL ниже минимума `ceil(1.5 × election-timeout)` (дефолт 2 с) — сервер продлевает до минимума | Укажите TTL ≥ 2 (или увеличьте `--election-ticks`/`--heartbeat-interval` сервера для меньшего минимума) |

**Примечания:**
- Запрошенный TTL ниже минимального **не является ошибкой** — аренда создаётся с TTL, продлённым до `minLeaseTTL` (дефолт 2 с). Ошибка только при TTL > 9e9
- Lease ID — hex-строка: etcdctl парсит аргумент `<leaseID>` в base 16 (`bad lease ID arg, expecting ID in Hex` при не-hex символах)
- Keep-alive отправляется каждые `TTL/3` секунд; при потере связи с лидером продление форвардится на лидера вручную
- Аренда переживает смену лидера благодаря checkpoint'ам (каждые 5 мин; checkpointing выключен по умолчанию — feature gate LeaseCheckpoint, см. garbage_collection.md)

### Lock и Elect (concurrency)

```bash
# Создание распределённой блокировки (команда блокируется, пока удерживается)
etcdctl lock mutex_name
# mutex_name/694d5765fc71500b

# Блокировка с TTL сессии (по умолчанию 60 с)
etcdctl lock mutex_name --ttl=30

# Блокировка с выполнением команды (создаёт ключ <lockname>/<lease-id>,
# выполняет команду с ETCD_LOCK_KEY и ETCD_LOCK_REV, отпускает при выходе)
etcdctl lock mutex_name -- echo "critical section"

# Участие в выборах лидера (candidate с proposal)
etcdctl elect election_name "candidate-1"

# Наблюдение за выборами (вывод изменений лидера)
etcdctl elect election_name --listen
```

**Типичные ошибки и решения (lock/elect):**

| Ошибка | Причина | Решение |
|---------------------------|---------|---------|
| Команда `lock` зависает | Другой участник удерживает блокировку | Дождитесь освобождения или увеличьте `--ttl` |
| Блокировка не отпускается после падения | etcdctl упал, не отпустив блокировку | Блокировка удерживается до экспири аренды (дефолт 60 с) |

**Примечания:**
- Ключ блокировки создаётся по пути `<lockname>/<lease-id>` (без префикса `/locks/`), например `mutex_name/694d5765fc71500b`
- **Fencing Token**: для корректного fencing при split-brain проверяйте revision lock-ключа (`etcdctl get <lockname> --rev=<rev>`) — только holder с максимальным revision может писать в разделяемый ресурс
- `lock` возвращает нулевой код выхода только при завершении по сигналу

### Транзакции (txn)

```bash
# Транзакция с условием (интерактивный режим)
etcdctl txn --interactive

# cmp
mod("/config/app") = "123"

# success
put "/config/app" "new_value"

# failure
get "/config/app"
```

**Синтаксис сравнений (cmp)** — цели и операторы:

| Цель | Сокращение | Сравнивает |
|------|-----------|------------|
| `create(<key>)` | `c(<key>)` | revision создания ключа |
| `mod(<key>)` | `m(<key>)` | revision последней модификации |
| `value(<key>)` | `val(<key>)` | значение ключа |
| `version(<key>)` | `ver(<key>)` | версию ключа (число обновлений) |
| `lease(<key>)` | — | ID аренды ключа |

Операторы: `<`, `=`, `>` (оператора `!=` нет). Сравнение с ревизией: `mod("/config/app") = "152"`.

**Правила:**
- `success` выполняется только если **все** условия истинны; `failure` — если хотя бы одно ложно
- Один ключ нельзя модифицировать дважды в одной транзакции (ошибка `etcdserver: duplicate key given in txn request`)
- Макс. число операций в транзакции — 128 (серверный флаг `--max-txn-ops`, дефолт 128; ошибка `etcdserver: too many operations in txn request`)
- Многострочные значения в интерактивном режиме записываются как `\n`
- Вывод: `SUCCESS` или `FAILURE`, затем результаты операций

```bash
# Нестерактивный режим (условие + success/failure блоки через stdin)
printf 'value("/config/app") = "old"\n\nput "/config/app" "new"\n\nget "/config/app"\n' | etcdctl txn
```

### Проверка здоровья и статуса кластера

#### endpoint health

```bash
# Проверка здоровья всех endpoints
etcdctl endpoint health --cluster
# 10.0.0.11:2379 is healthy: successfully committed proposal: took = 2.095242ms

# Табличный формат
etcdctl endpoint health --cluster -w table
# +---------------+---------+---------+-------+
# |   ENDPOINT    | HEALTH  |  TOOK   | ERROR |
# +---------------+---------+---------+-------+
# | 10.0.0.11:2379 |  true   | 2.09ms  |       |
# +---------------+---------+---------+-------+
```

**Типичные ошибки и решения (endpoint health):**

| Ошибка | Причина | Решение |
|---------------------------|---------|---------|
| `context deadline exceeded` | Узел недоступен или перегружен | Проверьте сеть, firewall, TLS-сертификаты; увеличьте `--command-timeout` |
| `etcdserver: request timed out` | Узел не отвечает в тайм-аут | Проверьте нагрузку на узел, диск (iowait), сеть |
| `etcdserver: request timed out, possibly due to previous leader failure` | Недавняя смена лидера | Дождитесь стабилизации, повторите |
| `etcdserver: unhealthy cluster` | Кворум недоступен | Проверьте `endpoint status --cluster`, логи etcd |

#### endpoint status

```bash
# Статус всех endpoints (таблица, etcd 3.6+)
etcdctl endpoint status --cluster -w table
# +---------------+------------------+---------+------------------+----------+--------------+-----------+------------+-----------+----------+---------------------+--------+
# |   ENDPOINT    |       ID         | VERSION | STORAGE VERSION  | DB SIZE  | DB SIZE IN USE | IS LEADER | IS LEARNER | RAFT TERM | RAFT INDEX | RAFT APPLIED INDEX | ERRORS |
# +---------------+------------------+---------+------------------+----------+--------------+-----------+------------+-----------+----------+---------------------+--------+
# | 10.0.0.11:2379 | 8e9e05f521f74f0d |  3.7.2  |       3.7        |  25 MB   |    18 MB     |  false    |   false    |     5     |  1234567   |      1234560       |        |
# +---------------+------------------+---------+------------------+----------+--------------+-----------+------------+-----------+----------+---------------------+--------+

# JSON-формат (содержит header.revision — текущую ревизию MVCC)
etcdctl endpoint status --cluster -w json
```

**Валидация:**
- `VERSION` одинакова на всех узлах (кроме rolling upgrade)
- Ровно один узел с `IS LEADER=true`
- `RAFT INDEX` и `RAFT APPLIED INDEX` на follower'ах не должны сильно отставать от лидера; для promote learner'а он должен догнать лидера (порог готовности — Match learner'а ≥ 90% от Match лидера, хардкод `readyPercentThreshold = 0.9`)
- Текущую ревизию MVCC получаете из JSON: `etcdctl endpoint status -w json` → поле `header.revision` (в табличном формате ревизия не выводится)

**Типичные ошибки и решения (endpoint status):**

| Ошибка | Причина | Решение |
|---------------------------|---------|---------|
| `etcdserver: no leader` | Потеря кворума | Проверьте доступность большинства узлов |
| `etcdserver: leader changed` | Смена лидера во время запроса | Повторите команду |
| Разница `DB SIZE` на узлах | Разная степень фрагментации | Выполните defrag на узле с большим размером |

#### endpoint hashkv

```bash
# Хеш ключей для проверки консистентности между узлами
etcdctl endpoint hashkv --cluster -w table
# +---------------+----------+---------------+
# |   ENDPOINT    |   HASH   | HASH REVISION |
# +---------------+----------+---------------+
# | 10.0.0.11:2379 | 2064120424 |     1234567   |
# +---------------+----------+---------------+

# Простой формат: endpoint, hash, hash_revision
etcdctl endpoint hashkv --cluster
# 10.0.0.11:2379, 2064120424, 1234567
```

**Валидация:** все узлы в HA-кластере должны иметь одинаковый `HASH` при одинаковом `HASH REVISION`. Разный hash при одинаковой ревизии — рассинхронизация данных.

### Управление участниками кластера (member)

```bash
# Список участников
etcdctl member list
# 8e9e05f521f74f0d, started, node1, https://10.0.0.11:2380, https://10.0.0.11:2379, false
# 9f1a06e632a85b1e, started, node2, https://10.0.0.12:2380, https://10.0.0.12:2379, false
# 7c8d9e0f1a2b3c4d, unstarted, node3, https://10.0.0.13:2380, , false
# (простой формат: ID, Status, Name, Peer Addrs, Client Addrs, Is Learner)

# Табличный формат
etcdctl member list -w table
# +------------------+---------+--------+------------------------+------------------------+
# |        ID        | STATUS  |  NAME  |       PEER ADDRS       |      CLIENT ADDRS      |
# +------------------+---------+--------+------------------------+------------------------+
# | 8e9e05f521f74f0d | started | node1  | https://10.0.0.11:2380 | https://10.0.0.11:2379 |
# +------------------+---------+--------+------------------------+------------------------+

# С консистентностью через лидера (не локальный кеш)
etcdctl member list --consistency=l

# Добавление нового участника
etcdctl member add node3 --peer-urls=https://10.0.0.13:2380
# Member 7c8d9e0f1a2b3c4d added to cluster 8e9e05f521f74f0d
#
# ETCD_NAME: "node3"
# ETCD_INITIAL_CLUSTER: "node1=https://10.0.0.11:2380,node2=https://10.0.0.12:2380,node3=https://10.0.0.13:2380"
# ETCD_INITIAL_ADVERTISE_PEER_URLS: "https://10.0.0.13:2380"
# ETCD_INITIAL_CLUSTER_STATE: "existing"

# Добавление learner'а (не голосующего участника)
etcdctl member add node4 --peer-urls=https://10.0.0.14:2380 --learner

# Обновление peer URLs участника
etcdctl member update 8e9e05f521f74f0d --peer-urls=https://10.0.0.11:2380

# Повышение learner'а до полноценного участника
etcdctl member promote 7c8d9e0f1a2b3c4d
# Member 7c8d9e0f1a2b3c4d promoted in cluster 8e9e05f521f74f0d

# Удаление участника
etcdctl member remove 7c8d9e0f1a2b3c4d
# Member 7c8d9e0f1a2b3c4d removed from cluster 8e9e05f521f74f0d
```

**Типичные ошибки и решения (member):**

| Ошибка | Причина | Решение |
|---------------------------|---------|---------|
| `etcdserver: member ID already exist` | Участник с таким ID уже есть | Проверьте `member list` |
| `etcdserver: member not found` | Неверный member ID | Скопируйте ID из `member list` (ID — hex-строка) |
| `etcdserver: re-configuration failed due to not enough started members` | Нет кворума для изменения состава | Проверьте здоровье большинства узлов |
| `etcdserver: given member URLs are invalid` | Некорректный формат peer URLs | Проверьте URL: `https://host:2380` |
| `etcdserver: Peer URLs already exists` | Peer URL занят другим участником | Используйте уникальный URL |
| Promote learner'а не удаётся | Learner отстал от лидера | Дождитесь синхронизации (Match learner'а ≥ 90% от Match лидера) перед промоушеном |

**Примечания:**
- Member ID — hex-строка (16 hex-символов); при ручном вводе используйте только символы `0-9a-f`
- Удаление участника требует кворума: минимум 2 из 3 узлов должны быть доступны
- `member add` выводит переменные окружения для конфигурации нового узла (`ETCD_INITIAL_CLUSTER_STATE: "existing"`)

### Перенос лидерства (move-leader)

```bash
# Перенос лидерства на указанный участник (ID в hex)
etcdctl move-leader 9f1a06e632a85b1e
# Leadership transferred from 8e9e05f521f74f0d to 9f1a06e632a85b1e
```

**Примечания:**
- `move-leader` отправляет целевому узлу `TimeoutNow` для немедленных выборов
- Используется при обслуживании текущего лидера (upgrade, замена диска)
- Целевой узел должен быть здоров и иметь актуальные данные

### Управление алармами (alarm)

```bash
# Список активных алармов
etcdctl alarm list
# memberID:8e9e05f521f74f0d alarm:NOSPACE
# (пустой вывод — алармов нет)

# Сброс ВСЕХ алармов (disarm не принимает аргументов — выборочного сброса нет)
etcdctl alarm disarm
```

**Типы алармов:**
- **NOSPACE** — превышен quota backend (дефолт **2 GiB**; 8 GiB — рекомендуемый максимум, при превышении которого сервер только предупреждает в логах)
- **CORRUPT** — повреждён файл данных

**Типичные ошибки и решения (alarm):**

| Ошибка | Причина | Решение |
|---------------------------|---------|---------|
| `alarm:NOSPACE` | Квота backend превышена | Выполните compaction → defrag, затем `etcdctl alarm disarm`; при необходимости увеличьте `--quota-backend-bytes` или освободите место в ОС |
| `alarm:CORRUPT` | Повреждён файл данных | Восстановление из снапшота (offline restore) |

**Примечания:**
- Порядок восстановления при NOSPACE: **compaction → defrag → `alarm disarm`** — без disarm аларм сохраняется даже после освобождения места
- Квота проверяется на двух уровнях: API-слой (ранний reject запросов) и Apply-слой (поднимает NOSPACE alarm без блокировки транзакции) — поэтому Put может вернуть `ErrGRPCNoSpace` и при этом успешно записать данные
- Алармы хранятся per-member и не распространяются автоматически — проверяйте `alarm list` на каждом узле

### Компакция (compaction)

```bash
# Удаление истории до указанной ревизии
etcdctl compaction 5000
# compacted mvcc keys with revision 5000

# Физическая компакция (с ожиданием завершения удаления ключей)
etcdctl compaction 5000 --physical
```

**Примечания:**
- Каноническое имя команды — `compaction`; `compact` работает как сокращение благодаря prefix matching в cobra
- Компакция **не уменьшает** размер файла БД — для возврата места в ОС требуется defrag
- После компакции чтение по ревизиям < compacted revision возвращает `mvcc: required revision has been compacted`
- Текущую ревизию можно получить из JSON-вывода: `etcdctl endpoint status -w json` → `header.revision`

**Типичные ошибки и решения (compaction):**

| Ошибка | Причина | Решение |
|---------------------------|---------|---------|
| `mvcc: required revision has been compacted` | Watcher или чтение отстали от компакции | Перечитайте с текущей ревизии, переподключите watch |
| `etcdserver: request timed out` | Длительная компакция на большой БД | Увеличьте `--command-timeout`, проверьте нагрузку на диск |

### Дефрагментация (defrag)

```bash
# Дефрагментация всех узлов кластера (поочерёдно, не параллельно)
etcdctl defrag --cluster

# Дефрагментация конкретного узла
etcdctl defrag --endpoints=https://10.0.0.11:2379
# Finished defragmenting etcd member[https://10.0.0.11:2379]

# Дефрагментация с тайм-аутом для большой БД
etcdctl defrag --endpoints=https://10.0.0.11:2379 --command-timeout=300
```

**Типичные ошибки и решения (defrag):**

| Ошибка | Причина | Решение |
|---------------------------|---------|---------|
| `context deadline exceeded` | Дефрагментация не уложилась в `--command-timeout` | Увеличьте тайм-аут (дефрагментация большой БД может занять минуты) |
| `etcdserver: leader changed` | Смена лидера во время операции | Повторите команду |

**Best Practices:**
- Дефрагментируйте **поочередно**, узел за узлом — одновременная дефрагментация всех участников делает кластер недоступным
- Мониторьте фрагментацию через метрики `etcd_mvcc_db_total_size_in_bytes` (размер файла) и `etcd_mvcc_db_total_size_in_use_in_bytes` (используемое место); фрагментация = `(total - in_use) / total`
- `defrag` возвращает нулевой код выхода только при успешной дефрагментации **всех** указанных endpoints
- Офлайн-дефрагментация (etcd 3.6+): `etcdutl defrag --data-dir /var/lib/etcd`

### Проверка производительности (check perf)

```bash
# Проверка производительности кластера (нагрузка "s" — small, по умолчанию)
etcdctl check perf --load="s"
# Start load test for 60 seconds with 50 clients, rate limit 150 writes/s
# ...
# PASS: throughput is 150 writes/s, slowest request took 12ms, stddev 3ms

# Доступные нагрузки: s (small), m (medium), l (large), xl (x-large)
etcdctl check perf --load="m"   # 200 clients, rate limit 1000 writes/s
etcdctl check perf --load="l"   # 500 clients, rate limit 8000 writes/s
etcdctl check perf --load="xl"  # 1000 clients, rate limit 15000 writes/s

# С авто-компакцией и дефрагментацией во время теста
etcdctl check perf --load="s" --auto-compact --auto-defrag

# С префиксом для изоляции тестовых данных
etcdctl check perf --load="s" --prefix=/etcdctl-check-perf/
```

**Параметры нагрузок (исходник `etcdctl/ctlv3/command/check.go`):**

| Load | Clients | Rate limit (writes/s) | PASS: throughput | PASS: slowest | PASS: stddev |
|------|---------|----------------------|------------------|---------------|--------------|
| s | 50 | 150 | ≥ 135 (90%) | ≤ 500 ms | ≤ 100 ms |
| m | 200 | 1000 | ≥ 900 | ≤ 500 ms | ≤ 100 ms |
| l | 500 | 8000 | ≥ 7200 | ≤ 500 ms | ≤ 100 ms |
| xl | 1000 | 15000 | ≥ 13500 | ≤ 500 ms | ≤ 100 ms |

**Примечания:**
- Тест длится **60 секунд**; данные пишутся в префикс `/etcdctl-check-perf/` (перезаписывается при каждом запуске)
- Разные нагрузки могут независимо PASS/FAIL (issue etcd-io/etcd#13455) — проверяйте все четыре уровня
- FAIL на s или m указывает на проблемы с диском (HDD вместо SSD, высокий iowait) или сетью
- Подробнее о бенчмаркинге: [benchmarking.md](./benchmarking.md)

### Проверка масштаба данных (check datascale)

```bash
# Проверка использования памяти при заданной нагрузке
etcdctl check datascale
# Start data scale check for work load [10000 key-value pairs, 1024 bytes per key-value, 50 concurrent clients]
# ...
# PASS: Approximate system memory used : 64.30 MB

# С префиксом и авто-компакцией
etcdctl check datascale --prefix=/datascale/ --auto-compact
```

**Примечания:** `check datascale` оценивает потребление памяти (heap) при заданном объёме данных — полезно для планирования capacity перед загрузкой больших объёмов ключей.

### RBAC (управление доступом)

#### Bootstrap (минимальная последовательность)

```bash
# 1. Создание root-пользователя (пароль запрашивается интерактивно)
etcdctl user add root
# User root created

# 2. Назначение root-пользователю root-роли
# (для root-роли проверка существования роли пропускается — grant работает без role add)
etcdctl user grant-role root root
# Role root is granted to user root

# 3. Включение аутентификации
etcdctl auth enable
# Authentication Enabled

# Проверка
etcdctl --user=root:password endpoint status
```

**Валидация:** `auth enable` требует существования root-пользователя **с** root-ролью (иначе — ошибки `etcdserver: root user does not exist` / `etcdserver: root user does not have root role`). Попытка `role grant-permission root readwrite /` **до** создания роли `root` (`role add root`) завершится ошибкой `etcdserver: role not found` — grant-permission требует существующей роли.

#### Пользователи

```bash
# Создание пользователя (пароль запрашивается интерактивно)
etcdctl user add myuser
# User myuser created

# Создание с паролем из stdin (без интерактивного запроса)
etcdctl user add myuser --interactive=false
# или
etcdctl user add myuser --new-user-password=secret

# Пользователь без пароля (аутентификация только по TLS Common Name)
etcdctl user add myuser --no-password

# Список пользователей
etcdctl user list
# root
# myuser

# Информация о пользователе (роли)
etcdctl user get myuser
# User: myuser
# Roles: myrole

# То же с деталями по правам ролей
etcdctl user get myuser --detail

# Смена пароля
etcdctl user passwd myuser

# Удаление пользователя
etcdctl user delete myuser
# User myuser deleted

# Назначение/отзыв роли пользователю
etcdctl user grant-role myuser myrole
etcdctl user revoke-role myuser myrole
```

#### Роли

```bash
# Создание роли
etcdctl role add myrole
# Role myrole created

# Выдача прав (readwrite, read, write)
etcdctl role grant-permission myrole readwrite /a
# Role myrole granted permissions on /a

# Выдача прав на префикс (диапазон [/a/, /a0))
etcdctl role grant-permission myrole --prefix=true readwrite /a/

# Выдача прав на диапазон [key1, key5)
etcdctl role grant-permission myrole readwrite key1 key5

# Просмотр прав роли (показывает KV Read: и KV Write:)
etcdctl role get myrole
# Role myrole
# KV Read:
#  /a
# KV Write:
#  /a

# Список ролей
etcdctl role list
# myrole
# root

# Отзыв прав на ключ/диапазон
etcdctl role revoke-permission myrole /a

# Удаление роли
etcdctl role delete myrole
# Role myrole deleted
```

**Типичные ошибки и решения (RBAC):**

| Ошибка | Причина | Решение |
|---------------------------|---------|---------|
| `etcdserver: permission denied` | Нет прав на операцию | Проверьте роли пользователя: `etcdctl user get <user> --detail` |
| `etcdserver: authentication failed, invalid user ID or password` | Неверный логин/пароль | Проверьте учётные данные |
| `etcdserver: authentication is not enabled` | Аутентификация отключена | Включите: `etcdctl auth enable` |
| `etcdserver: user not found` | Пользователь не существует | Создайте: `etcdctl user add` |
| `etcdserver: role not found` | Роль не существует | Создайте: `etcdctl role add` |
| `etcdserver: role is not granted to the user` | Роль не назначена пользователю | Назначьте: `etcdctl user grant-role` |
| `etcdserver: permission is not granted to the role` | Нет прав на ключ | Выдайте: `etcdctl role grant-permission` |

**Примечания:**
- Аутентификация защищает **только V3 gRPC API** (get, put, watch, txn и т.д.). Endpoints `/metrics` и `/health` работают на отдельном handler и **не защищены** RBAC — для их защиты используйте mTLS (`--client-cert-auth`), привязку `--listen-metrics-urls` к приватному интерфейсу или сетевые политики
- Аутентификация по TLS Common Name: при `--client-cert-auth=true` CN клиентского сертификата используется как имя пользователя (v3.2+); username/password имеет приоритет, если предоставлены оба
- etcd не проверяет стойкость паролей — требования к длине/сложности должен задавать администратор
- Пустой пароль не поддерживается через `--user username:` (пользователь с пустым паролем не может аутентифицироваться по username/password)
- RBAC проверяется на сервере на каждом gRPC-запросе; клиент кэширует только auth-токен (simple или JWT, `--auth-token`)
- После `auth disable` все права сохраняются в метаданных и восстанавливаются при повторном `auth enable`

### Зеркалирование ключей (make-mirror)

```bash
# Зеркалирование ключей из текущего кластера в целевой кластер
etcdctl make-mirror http://localhost:2379
# ...
# Approximate total number of keys transferred: 12345
# (прогресс обновляется каждые 30 секунд)

# С префиксом источника и/или назначения
etcdctl make-mirror http://dest:2379 --prefix=/config/ --dest-prefix=/mirror/config/

# Без префикса назначения (ключи пишутся в корень целевого кластера)
etcdctl make-mirror http://dest:2379 --prefix=/config/ --no-dest-prefix

# TLS к целевому кластеру
etcdctl make-mirror https://dest:2379 \
  --dest-cacert=/etc/etcd/ca.crt \
  --dest-cert=/etc/etcd/client.crt \
  --dest-key=/etc/etcd/client.key

# Без TLS-проверки целевого кластера
etcdctl make-mirror http://dest:2379 --dest-insecure-transport
```

**Флаги make-mirror:** `--prefix`, `--dest-prefix`, `--no-dest-prefix`, `--dest-cacert`, `--dest-cert`, `--dest-key`, `--dest-insecure-transport`, `--max-txn-ops`.

**Примечания:** `make-mirror` копирует диапазон ключей из текущего кластера в целевой через Txn-пакеты — механизм логической репликации/миграции keyspace между кластерами (не snapshot-restore). Полезно для cross-DC репликации read-only копии и миграции на новый кластер без простоя.

### Backup и Restore

```bash
# Создание снапшота (не влияет на производительность участника)
etcdctl snapshot save backup.db
# Snapshot saved at 1234567890
# ...

# Проверка целостности снапшота (etcd 3.6+ — через etcdutl)
etcdutl snapshot status backup.db -w table
# +----------+----------+------------------+-------------+---------+
# |   HASH   | REVISION | TOTAL KEY COUNT  | TOTAL SIZE  | VERSION |
# +----------+----------+------------------+-------------+---------+
# | 1a2b3c4d |   512340 |          1254300 |    256 MB   |   3.7   |
# +----------+----------+------------------+-------------+---------+

# Восстановление из снапшота в новую директорию (etcd 3.6+ — через etcdutl)
etcdutl snapshot restore backup.db \
  --name node1 \
  --initial-cluster "node1=https://10.0.0.11:2380,node2=https://10.0.0.12:2380,node3=https://10.0.0.13:2380" \
  --initial-advertise-peer-urls https://10.0.0.11:2380 \
  --data-dir /var/lib/etcd-new
# ...

# Восстановление с дополнительными опциями (etcd 3.6+)
etcdutl snapshot restore backup.db --data-dir /var/lib/etcd-new \
  --skip-hash-check \      # пропустить проверку целостности (для копий из data-dir/member/snap/db)
  --bump-revision=1000 \   # увеличить ревизию после restore
  --mark-compacted=5000    # пометить ревизии до 5000 как скомпактированные
```

**Примечания:**
- Восстановление требует остановки etcd на всех узлах и создания новой директории данных
- Восстановленный член получает **новые** member ID и cluster ID — это новый логический кластер; все члены восстанавливают из **одного и того же** снапшота
- В Kubernetes после restore необходимо обновить статичные манифесты в `/etc/kubernetes/manifests/etcd.yaml` (или ConfigMap) и перезапустить поды
- Проверка после restore: `etcdutl snapshot status` на восстановленном `db` — revision должен совпадать с revision в снапшоте
- Полная процедура DR (quorum loss, force-new-cluster, fencing) — в [emergency_recovery.md](./emergency_recovery.md)

### Офлайн-утилиты (etcdutl, etcd-dump-logs)

```bash
# Офлайн-дефрагментация (etcd 3.6+)
etcdutl defrag --data-dir /var/lib/etcd

# Чтение WAL (журнала raft) — утилита etcd-dump-logs
# Установка:
go install go.etcd.io/etcd/v3/tools/etcd-dump-logs@latest
# или из исходников etcd:
go install -v ./tools/etcd-dump-logs

# Дамп записей WAL с фильтром по типу и диапазону raft-индексов
etcd-dump-logs --wal-dir /var/lib/etcd/member/wal --entry-type IRRPut --start-index 100 --end-index 200 /var/lib/etcd
```

**Флаги etcd-dump-logs:** `-wal-dir` (директория WAL), `-entry-type` (`ConfigChange`, `Normal`, `Request`, `InternalRaftRequest`, `IRRRange`, `IRRPut`, `IRRDeleteRange`, `IRRTxn`, `IRRCompaction`, `IRRLeaseGrant`, `IRRLeaseRevoke`, `IRRLeaseCheckpoint`), `-start-index` (включительно; по умолчанию — от индекса последнего снапшота), `-end-index` (исключительно), `-start-snap`, `-stream-decoder`, `-raw`.

**Примечания:**
- `etcdutl` не имеет wal-команды; для чтения WAL используется только `etcd-dump-logs`
- Утилита выводит метаданные WAL (nodeID, clusterID, term, commitIndex, vote), информацию о снапшотах и записи; **ограничения**: показывает только Entries (не записи Snapshots/HardStates), применяет overrides (для перезаписанных ключей печатает финальное значение), печатает незакоммиченные «хвостовые» записи без информации о commitIndex
- Best Practices: регулярно проверяйте целостность бэкапов (`etcdutl snapshot status`); храните снапшоты отдельно от data-dir; для etcd 3.5 и ниже используйте `etcdctl snapshot save`/`status`/`restore` (в 3.6+ они удалены из etcdctl)

### Downgrade (экспериментально, etcd 3.6+)

```bash
# Проверка возможности даунгрейда до целевой версии
etcdctl downgrade validate 3.5
# ...

# Включение режима даунгрейда
etcdctl downgrade enable 3.5

# Отмена даунгрейда
etcdctl downgrade cancel
```

**Примечания:** команда `downgrade` помечена experimental в 3.6; используется при даунгрейде кластера (например, 3.7 → 3.6). Подробнее: [version_compatibility.md](./version_compatibility.md).

### Shell completion

```bash
# Генерация completion для bash/zsh/fish/powershell (etcd 3.6+)
etcdctl completion bash
etcdctl completion zsh
```

## См. также

- [architecture-and-concepts.md](./architecture-and-concepts.md) — архитектура etcd
- [clustering_and_recovery.md](./clustering_and_recovery.md) — управление кластером и восстановление
- [watch_lease_internals.md](./watch_lease_internals.md) — внутренности watch и lease
- [version_compatibility.md](./version_compatibility.md) — совместимость версий
- [backup_strategies.md](./backup_strategies.md) — стратегии бэкапа
- [security.md](./security.md) — безопасность (TLS, RBAC)
- [garbage_collection.md](./garbage_collection.md) — сборка мусора
- [proposal_pipeline.md](./proposal_pipeline.md) — pipeline записи
- [maintenance_api.md](./maintenance_api.md) — Maintenance API
- [emergency_recovery.md](./emergency_recovery.md) — аварийное восстановление
- [limits_and_constraints.md](./limits_and_constraints.md) — лимиты и ограничения
- [kubernetes_integration.md](./kubernetes_integration.md) — интеграция с Kubernetes
- [kernel_tuning.md](./kernel_tuning.md) — настройка ядра
- [mvcc_versioning_and_compaction.md](./mvcc_versioning_and_compaction.md) — MVCC и компакция
- [etcd_monitoring.md](./etcd_monitoring.md) — мониторинг
- [benchmarking.md](./benchmarking.md) — бенчмаркинг
- [troubleshooting.md](./troubleshooting.md) — troubleshooting playbook
- [raft_consensus.md](./raft_consensus.md) — консенсус Raft и кворум
