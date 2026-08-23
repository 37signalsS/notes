# etcdctl и etcdutl: шпаргалка по командам

Данный справочник содержит исчерпывающий набор команд для управления кластером etcd v3.7.1 и выше.

## Определения

| Инструмент / Понятие | Описание |
| :--- | :--- |
| **etcdctl** | Основной клиент командной строки для онлайн-взаимодействия с работающим кластером через gRPC. Используется для CRUD-операций, управления участниками, мониторинга, RBAC и создания снапшотов. |
| **etcdutl** | (начиная с v3.6) Утилита для офлайн-операций, требующих прямого доступа к файлам данных на диске: восстановление из снапшота, дефрагментация файла БД, проверка статуса и целостности снапшотов, анализ WAL, работа с форматом базы данных. |
| **ETCDCTL_API** | Переменная окружения для выбора версии протокола. В v3.7+ стандарт — **v3**. Допустимые значения: `2`, `3`. |
| **Raft Consensus** | Алгоритм консенсуса, лежащий в основе etcd. Обеспечивает репликацию журнала записей (log replication) между участниками кластера и выбор лидера. |
| **WAL (Write-Ahead Log)** | Журнал предзаписи в формате protobuf. Каждая запись проходит через WAL перед фиксацией в BoltDB. Гарантирует durability: после `fsync` в WAL операция не потеряется даже при падении процесса. |
| **BoltDB** | Встроенная БД на основе B+ дерева. Хранит все ключ-значения и метаданные MVCC (версии, модификации). Файл базы данных фрагментируется при компакции; для возврата места в ОС требуется дефрагментация. |
| **Lease (Аренда)** | Механизм привязки ключей к временному контракту (TTL). Если TTL истекает без keep-alive, ключ автоматически удаляется. Lease ID — 64-битное число, выбранное лидером. |
| **Watch** | Механизм long-polling для отслеживания изменений ключей в реальном времени. Поддерживает исторический диапазон (`--rev`) и прогрессивные уведомления. |
| **Revision** | Глобально монотонно возрастающий номер версии состояния кластера. Каждая `put`, `del` или `txn` увеличивает revision. |
| **Compact (Компакция)** | Удаление старых ревизий BoltDB. Блокирует чтение по старым ревизиям, но не уменьшает размер файла на диске. |
| **Defrag (Дефрагментация)** | Онлайн-операция (v3.0+) или офлайн-операция (`etcdutl`), которая перестраивает файл BoltDB и возвращает свободное место операционной системе. Блокирует запись и чтение на узле на время выполнения. |
| **Alarm (Аларм)** | Сигнал нештатного состояния узла. Типы: `NOSPACE` (превышена квота диска) и `CORRUPT` (поврежден файл данных). Алармы не распространяются автоматически между участниками. |
| **Learner** | Участник кластера без права голоса. Получает репликацию от лидера, но не участвует в кворуме и не может стать лидером. |
| **MVCC (Multi-Version Concurrency Control)** | Архитектура хранения, при которой каждое изменение ключа создает новую версию, а не перезаписывает старое значение. Обеспечивает согласованность reads без блокировок. |

---

## Базовые концепции

### Настройка окружения и аутентификация

Для постоянной работы рекомендуется настроить переменные окружения, чтобы не передавать флаги TLS и адреса в каждой команде.

```bash
# Базовая настройка (API v3)
export ETCDCTL_API=3
export ETCDCTL_ENDPOINTS="https://127.0.0.1:2379"

# Настройка TLS (для Kubernetes и защищенных кластеров)
export ETCDCTL_CACERT="/etc/etcd/ca.crt"
export ETCDCTL_CERT="/etc/etcd/server.crt"
export ETCDCTL_KEY="/etc/etcd/server.key"

# Настройка аутентификации (если включен RBAC)
export ETCDCTL_USER="admin:password"
```

**Валидация:**
```bash
# Проверка успешного подключения
etcdctl --version
# → etcdctl version: 3.7.1

# Проверка endpoints
etcdctl endpoint status --cluster -w table
# Должен отображать HEALTH=true для всех узлов
```

### Форматы вывода

Флаг `-w` (или `--write-out`) изменяет формат ответа:
- `simple` — текстовый (по умолчанию).
- `table` — табличный (удобно для чтения).
- `json` — для автоматизации и скриптов.

### gRPC path и параметры подключения

Все команды `etcdctl` маршрутизируются через gRPC endpoint (по умолчанию `/etcdserverpb.Maintenance/Defragment` и аналогичные). Важно:
- Подключение инициализируется при каждой команде (нет глобального keep-alive).
- Тайм-ауты настраиваются через `ETCDCTL_TIMEOUT` (по умолчанию зависит от версии клиента, обычно 5–10 секунд).
- В Kubernetes стандартные пути к сертификатам: `/etc/kubernetes/pki/etcd/ca.crt`, `/etc/kubernetes/pki/etcd/server.crt`, `/etc/kubernetes/pki/etcd/server.key`.

### Теория leases и watches

**Lease TTL:**
- TTL указывается в секундах при создании (`lease grant 60`).
- Минимальный TTL: 1 секунда. Максимальный: зависит от `--experimental-lease-ttl` (по умолчанию 9e18 секунд на сервере).
- Keep-alive выполняется через отдельный gRPC stream. Если клиент теряет соединение, lease истекает через TTL + небольшой grace period (обычно 1–2 секунды на grace period сервера).

**Watch:**
- Watch привязан к конкретной revision. При запуске `etcdctl watch /key` без `--rev` подписка начинается с текущей revision.
- При использовании `--rev=X` клиент получит все события, произошедшие после ревизии X, и последующие события.
- Watch buffer имеет ограниченный размер. Если клиент слишком медленно обрабатывает события, сервер закрывает стрим с ошибкой `etcdserver: mvcc: watch store is out of space`. Клиент должен переподключиться с последней известной revision.

### Теория дефрагментации и компакции

**Компакция:**
- Помечает старые версии ключей как удаленные в BoltDB, но не уменьшает физический размер файла.
- Блокирует чтение по ревизиям, старше compacted. Read через `get --rev=1000` после `compaction 5000` вернет ошибку `mvcc: required revision has been compacted`.
- Kubernetes автоматически запускает компакцию каждые 5 минут через `--auto-compaction-retention=5m`.

**Дефрагментация:**
- Онлайн-операция `etcdctl defrag` блокирует запись и чтение на конкретном узле на время выполнения (от миллисекунд до секунд в зависимости от размера БД).
- Офлайн-дефрагментация через `etcdutl defrag --data-dir` блокирует запуск etcd до завершения.
- Параллельная дефрагментация нескольких узлов недопустима: follower'ы не могут синхронизировать логи с заблокированным лидером, что может вызвать потерю кворума.

---

## Практические сценарии

### CRUD и работа с ключами

#### Запись и чтение ключа

```bash
etcdctl put /config/app "value1"
# → OK

etcdctl get /config/app
# → /config/app
# → value1
```

**Валидация:**
```bash
# Проверить существование ключа (exit code 0 = существует)
etcdctl get /config/app --exit-code
echo $?
# → 0

# Проверить отсутствие ключа
etcdctl get /config/nonexistent --exit-code
echo $?
# → 1
```

#### Работа с префиксами

```bash
# Чтение всех ключей в директории
etcdctl get /config/ --prefix

# Только названия ключей (без значений)
etcdctl get /config/ --prefix --keys-only

# С ограничением количества результатов
etcdctl get /config/ --prefix --limit=10

# С сортировкой по ключу (полезно для инспекции)
etcdctl get /config/ --prefix --sort
```

**Troubleshooting:**
- Если `get --prefix` возвращает слишком много ключей, добавьте `--limit=N`.
- Для больших директорий используйте `--keys-only` + `--sort` для быстрого перечисления.

#### Чтение по конкретной ревизии

```bash
# Прочитать значение ключа на ревизии 5000
etcdctl get /config/app --rev=5000

# Получить метаданные (модификация, версия)
etcdctl get /config/app -w json
# → {"header":{"cluster_id":...,"member_id":...,"revision":...,"raft_term":...},"kvs":[{"key":"...","create_revision":...,"mod_revision":...,"version":...,"value":"..."}]}
```

**Edge Cases:**
- Чтение по compacted revision возвращает ошибку: `mvcc: required revision has been compacted`.
- Чтение по ревизии за пределами истории (слишком старой) возвращает ошибку: `mvcc: required revision is beyond the range`.

#### Удаление

```bash
# Удаление одного ключа
etcdctl del /config/old_key
# → 1

# Удаление всех ключей по префиксу
etcdctl del /config/ --prefix

# Удаление с ограничением
etcdctl del /config/ --prefix --limit=10
```

### Наблюдение (Watch)

#### Базовый Watch

```bash
# Ожидание изменений конкретного ключа
etcdctl watch /config/app
# → PUT
# → /config/app
# → new_value

# Watch всех изменений в префиксе
etcdctl watch /config/ --prefix

# Watch с прогрессивными уведомлениями
etcdctl watch /config/ --prefix --progress-notify
```

#### Watch с историей

```bash
# Получить все события, произошедшие после ревизии 5000
etcdctl watch /config/app --rev=5000

# Игнорировать исторические события, начать с текущей ревизии
etcdctl watch /config/app --ignore-watch
```

#### Watch с предыдущим значением

```bash
# Получить старое значение при изменении
etcdctl watch /config/app --prev-kv
# → PUT
# → /config/app
# → new_value
# → PREV_KEY: /config/app
# → PREV_VALUE: value1
```

**Troubleshooting:**
- `etcdserver: mvcc: watch store is out of space` — клиент не успевает обрабатывать события. Решение: уменьшить буфер обработки на стороне клиента, переподключиться с `--rev`, или настроить `--auto-compaction-retention`.
- `context canceled` — клиент отключился раньше времени. Увеличьте тайм-ауты или исправьте сетевые проблемы.

### Аренда (Lease)

#### Создание и привязка

```bash
# Создать аренду на 60 секунд
etcdctl lease grant 60
# → lease 694d5765fc71500b granted with TTL(60s)

# Привязать ключ к аренде
etcdctl put /tmp/key "val" --lease=694d5765fc71500b

# Продлить аренду (keep-alive)
etcdctl lease keep-alive 694d5765fc71500b
# → lease 694d5765fc71500b keepalive with TTL(60s)
```

#### Просмотр и отзыв аренды

```bash
# Просмотр информации об аренде
etcdctl lease timetolive 694d5765fc71500b
# → lease 694d5765fc71500b granted with TTL(60s), remaining(45s)

# Принудительный отзыв аренды
etcdctl lease revoke 694d5765fc71500b
# → lease 694d5765fc71500b revoked
```

**Валидация:**
```bash
# После отзыва попытка чтения ключа вернет пустой результат
etcdctl get /tmp/key
# → (пусто)
```

**Edge Cases:**
- TTL 0 или отрицательный — аренда не создается, возвращается ошибка.
- Отзыв несуществующей аренды возвращает ошибку `etcdserver: lease not found`.
- В Kubernetes контроллеры используют leases для лидерских выборов (leader election) и keep-alive. Прерывание keep-alive приведет к потери лидерства.

### Распределенные блокировки (Lock)

```bash
# Создать блокировку (команда блокируется пока удерживается)
etcdctl lock mutex_name
# → mutex_name/694d5765fc71500b (блокировка удерживается, пока команда запущена)

# Освобождение происходит при закрытии процесса (Ctrl+C)
```

**Важно:** `etcdctl lock` создает ключ под `/locks/mutex_name/<lease_id>` с TTL аренды. Если процесс упадет, блокировка автоматически освободится через TTL.

**Fencing Token:** В распределенных системах важно проверять fencing token (revision lock-ключа) для предотвращения split-brain.

### Транзакции (Txn)

```bash
etcdctl txn --interactive
# Пример логики:
# cmp: mod("/config/app") = "123"
# success: put "/config/app" "new_val"
# failure: get "/config/app"
```

**Пакетный режим (неинтерактивный):**

```bash
etcdctl txn <<'EOF'
cmp
mod_revision("/config/app") = "152"
success
put "/config/app" "new_val"
failure
get "/config/app"
EOF
```

**Валидация:**
- `cmp` поддерживает: `=`, `<`, `>`, `!=`, `mod`, `ver`, `create`, `mod_revision`, `prev_kv`.
- `success` выполняется только если ВСЕ условия `cmp` истинны.
- `failure` выполняется только если хотя бы одно условие ложно.

### Состояние и здоровье кластера

#### Проверка здоровья

```bash
etcdctl endpoint health --cluster -w table
# → +----------------+--------+-------+-------+
# → |    ENDPOINT    | HEALTH |  TOOK | ERROR |
# → +----------------+--------+-------+-------+
# → | 127.0.0.1:2379 |   true | 1.5ms |       |
# → +----------------+--------+-------+-------+
```

**Валидация:**
```bash
# Exit code 0 при здоровом кластере
etcdctl endpoint health --cluster
echo $?
# → 0
```

**Troubleshooting:**
- `etcdserver: request timed out` — проверьте firewall, TLS сертификаты, и доступность endpoints.
- `etcdserver: no leader` — потеря кворума. Проверьте `etcdctl member list` и логи.

#### Детальный статус

```bash
etcdctl endpoint status --cluster -w table
# → +----------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+
# → |    ENDPOINT    |        ID        | VERSION | DB SIZE | IS LEADER | IS LEARNER | RAFT TERM | RAFT INDEX | RAFT APPLIED INDEX |
# → +----------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+
# → | 127.0.0.1:2379 | 8e9e05f521f74f0d | 3.7.1   | 1.2 GB  |      true |     false  |        12 |    1543200 |           1543200 |
# → +----------------+------------------+---------+---------+-----------+------------+-----------+------------+--------------------+
```

**Интерпретация:**
- `RAFT INDEX` и `RAFT APPLIED INDEX` на follower'ах не должны отставать от лидера более чем на 1000.
- `DB SIZE` — физический размер файла BoltDB (не используется место).
- `IS LEARNER` — узел без права голоса.

#### Проверка хеш-значения данных (Data Integrity)

```bash
# Проверка хеш-значения ключевых данных на всех узлах
etcdctl endpoint hashkv --cluster -w table
# → +----------------+------------------+----------+---------+
# → |    ENDPOINT    |        ID        |   HASH   | ROLE    |
# → +----------------+------------------+----------+---------+
# → | 127.0.0.1:2379 | 8e9e05f521f74f0d | 12345678 | Leader  |
# → | 10.0.0.11:2379 | 9f1a06g632g85g1e | 12345678 | Follower|
# → +----------------+------------------+----------+---------+
```

**Валидация:** Все узлы в HA-кластере должны иметь одинаковый `HASH`. Различия указывают на рассинхронизацию данных.

#### Управление участниками

```bash
# Список участников
etcdctl member list -w table
# → +------------------+--------+------------------------+------------------------+
# → |       ID         | STATUS |        NAME            |       PEER URLS        |
# → +------------------+--------+------------------------+------------------------+
# → | 8e9e05f521f74f0d | started| node1                  | https://10.0.1.10:2380 |
# → | 9f1a06g632g85g1e | started| node2                  | https://10.0.1.11:2380 |
# → +------------------+--------+------------------------+------------------------+

# Добавить узел как learner (без права голоса)
etcdctl member add node3 --peer-urls=https://10.0.1.12:2380 --learner

# Повысить learner до голосующего участника
etcdctl member promote <MEMBER_ID>

# Удалить узел
etcdctl member remove 8e9e05f521f74f0d
```

**Best Practices:**
- Всегда добавляйте большие узлы через `--learner` и дождитесь синхронизации RAFT INDEX (разница < 1000) перед промоушеном.
- Удаление участника требует кворума: минимум 2 из 3 узлов должны быть доступны.

#### Передача лидерства

```bash
# Проверить текущего лидера
etcdctl endpoint status --cluster -w table | grep true

# Передать лидерство целевому узлу
etcdctl move-leader <target-node-id>
```

**Важно:** `move-leader` отправляет узлу `TimeoutNow` для немедленных выборов. Текущий лидер перестает принимать запросы. Используйте для планового техобслуживания.

### Управление алармами (Alarms)

```bash
# Список активных алармов
etcdctl alarm list
# → member 8e9e05f521f74f0d: NOSPACE

# Сброс конкретного аларма
etcdctl alarm disarm --member 8e9e05f521f74f0d

# Сброс всех алармов
etcdctl alarm disarm
```

**Типы алармов:**
- `NOSPACE` — quota exceeded (по умолчанию 2GB или 8GB). Возникает при `database space exceeded`.
- `CORRUPT` — поврежден файл данных. Возникает при аппаратных сбоях или некорректном завершении.

**Troubleshooting:**
- При `NOSPACE` выполните `compaction` + `defrag`, затем увеличьте `quota-backend-bytes` или освободите место в ОС.
- При `CORRUPT` требуется восстановление из снапшота (offline restore).

### Обслуживание и производительность

#### Компакция (Сжатие истории)

```bash
# Удалить все ревизии до 5000
etcdctl compaction 5000
# → compacted revision 5000

# Автоматическая компакция (Kubernetes)
# В манифесте kube-apiserver:
# --auto-compaction-retention=5m
```

**Валидация:**
```bash
# Проверить текущий revision кластера
etcdctl endpoint status --cluster -w table | grep -oE '[0-9]+$'
# Убедиться, что current revision > compacted revision
```

**Troubleshooting:**
- `mvcc: required revision has been compacted` — watcher отстал. Исправьте: увеличить `--auto-compaction-retention` или оптимизировать контроллеры, чтобы они не отставали.

#### Дефрагментация (Освобождение места)

```bash
# Онлайн дефрагментация всего кластера (поочередно, не параллельно)
etcdctl defrag --cluster
# → Finished defragmenting etcd member[https://127.0.0.1:2379]

# Онлайн дефрагментация конкретного узла
etcdctl defrag --endpoints=https://10.0.0.11:2379
```

**Валидация:**
```bash
# Вычислить фрагментацию через метрики
curl -s http://localhost:2379/metrics | grep etcd_mvcc_db_total_size
# etcd_mvcc_db_total_size_in_bytes{...} 3221225472
# etcd_mvcc_db_total_size_in_use_in_bytes{...} 1610612736

# Формула: fragmentation = (total - in_use) / total
# В примере: (3221225472 - 1610612736) / 3221225472 = 0.5 (50%)
```

**Best Practices:**
- Выполняйте `etcdctl defrag` по очереди на узлах (не одновременно) в часы минимальной нагрузки.
- Это возвращает свободное место в ОС и ускоряет чтение (меньший файл = меньше дисковых операций).

#### Проверка производительности (Perf Check)

```bash
etcdctl check perf --load="s"  # s (small), m (medium), l (large), xl (x-large)
# → PASS: Throughput is 150 writes/s
```

**Интерпретация порогов (ориентировочно для NVMe):**
- **Small (s):** PASS при > 100 writes/s.
- **Medium (m):** PASS при > 50 writes/s.
- **Large (l):** PASS при > 20 writes/s.
- **X-Large (xl):** PASS при > 5 writes/s.

**Troubleshooting:**
- FAIL на `s` или `m` указывает на проблемы с диском (HDD вместо SSD, высокий iowait) или сетью между участниками.
- При высокой вариативности запускайте тест 3–5 раз и считайте медиану.

### Управление доступом (RBAC)

#### Работа с пользователями

```bash
etcdctl user add my_user           # Создать пользователя (интерактивно запрашивает пароль)
etcdctl user delete my_user        # Удалить пользователя
etcdctl user list                  # Список всех пользователей
etcdctl user get root              # Информация о пользователе и его ролях
```

#### Работа с ролями

```bash
# Создать роль
etcdctl role add my_role

# Дать права на конкретный ключ
etcdctl role grant-permission my_role readwrite /a

# Дать права на префикс
etcdctl role grant-permission my_role read /b --prefix

# Просмотр прав роли
etcdctl role get-permission my_role

# Привязать роль к пользователю
etcdctl user grant-role my_user my_role

# Отвязать роль от пользователя
etcdctl user revoke-role my_user my_role
```

#### Включение аутентификации

```bash
# Включить (требует наличия пользователя root)
etcdctl auth enable

# Выключить
etcdctl auth disable
```

**Bootstrap sequence (правильный порядок):**
1. `etcdctl user add root`
2. `etcdctl role grant-permission root readwrite /`
3. `etcdctl auth enable`
4. Проверить: `etcdctl --user=root:password endpoint status`

**Edge Cases:**
- Попытка `auth enable` без пользователя `root` завершится ошибкой.
- После `auth disable` все права сохраняются в метаданных. При повторном `auth enable` они восстанавливаются.
- RBAC проверяется на каждом gRPC-запросе. Нет кэширования прав на стороне клиента.

### Резервное копирование и восстановление

#### Создание снапшота (Online)

```bash
# Базовая команда
etcdctl snapshot save backup.db

# Полная команда с TLS и эндпоинтами (рекомендуется для HA кластеров)
ETCDCTL_API=3 etcdctl snapshot save /path/to/backup.db \
  --endpoints=https://etcd1.example.com:2379,https://etcd2.example.com:2379,https://etcd3.example.com:2379 \
  --cacert=/etc/etcd/pki/ca.pem \
  --cert=/etc/etcd/pki/etcd.pem \
  --key=/etc/etcd/pki/etcd-key.pem
```

**Разбор флагов:**
- `ETCDCTL_API=3`: Принудительное использование API v3.
- `snapshot save`: Создает снимок и сохраняет его по указанному пути.
- `--endpoints`: Список URL-адресов всех серверов etcd в кластере.
- `--cacert`, `--cert`, `--key`: Пути к сертификатам и ключам для безопасной аутентификации.

**Валидация:**
```bash
# Проверить размер снапшота
ls -lh backup.db
# → 1.2G backup.db

# Проверить валидность снапшота
etcdutl snapshot status backup.db -w table
# → Hash: 1a2b3c4d, Revision: 512340, Total key count: 1254300
```

#### Восстановление (Offline)

```bash
# Для etcd 3.6+ обязательно использование etcdutl
etcdutl snapshot restore backup.db \
  --name node1 \
  --initial-cluster node1=https://10.0.1.10:2380,node2=https://10.0.1.11:2380,node3=https://10.0.1.12:2380 \
  --data-dir /var/lib/etcd-new
```

**Важно:**
- Восстановление требует **остановки** etcd на всех узлах и создания **новой** директории данных.
- В Kubernetes после restore необходимо обновить статичные манифесты в `/etc/kubernetes/manifests/etcd.yaml` с новым `--initial-cluster` и `--name`, затем перезапустить control plane.

**Валидация:**
```bash
# Проверить восстановленный кластер
ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint status -w table

# Проверить revision
etcdctl endpoint status -w table | grep -oE '[0-9]+$'
# Должен совпадать с revision в снапшоте
```

### Утилита etcdutl: расширенные операции

#### Проверка статуса снапшота

```bash
etcdutl snapshot status backup.db -w table
# → Hash: 1a2b3c4d, Revision: 512340, Total key count: 1254300
```

#### Анализ WAL

```bash
# Статистика WAL (количество записей, размер файлов)
etcdutl wal show /var/lib/etcd/wal/
# → WAL records: 15420, file size: 1.2GB

# Проверка целостности WAL
etcdutl wal verify /var/lib/etcd/wal/
# → WAL verify passed, records: 15420
```

#### Офлайн дефрагментация

```bash
# Требует остановки etcd
etcdutl defrag --data-dir /var/lib/etcd
# → Finished defragmenting
```

#### Офлайн работа с базой данных

```bash
# Экспорт ключей в формате JSON
etcdutl db --data-dir /var/lib/etcd get /config/ -w json

# Проверка здоровья базы данных (offline)
etcdutl health --data-dir /var/lib/etcd
# → health check passed
```

**Best Practices:**
- Используйте `etcdutl` только когда процесс etcd остановлен или на уровне файлов данных.
- Не смешивайте онлайн (`etcdctl`) и офлайн (`etcdutl`) операции на одном узле одновременно.

---

## Дополнительная информация

*   **[Архитектура и основные концепции](./architecture-and-concepts.md)** — глубокое понимание WAL, Raft и Revision.
*   **[Кластеризация и восстановление](./clustering_and_recovery.md)** — процедуры замены узлов и аварийное восстановление.
*   **[Watch и Lease: внутреннее устройство](./watch_lease_internals.md)** — буфер, прогресс, compacted revision, lease GC.
*   **[Совместимость версий и обновление](./version_compatibility.md)** — rolling upgrade и downgrade.
*   **[Стратегии резервного копирования](./backup_strategies.md)** — snapshot vs logical backup, trade-offs.
*   **[Безопасность](./security.md)** — TLS, RBAC, encryption at rest.
*   **[Garbage Collection](./garbage_collection.md)** — key GC и revision cleanup.
*   **[Proposal Pipeline](./proposal_pipeline.md)** — детальный write path.
*   **[Maintenance API](./maintenance_api.md)** — gRPC maintenance endpoint.
*   **[Аварийное восстановление](./emergency_recovery.md)** — `--force-new-cluster` и DR.
*   **[Лимиты и ограничения](./limits_and_constraints.md)** — size limits и capacity planning.
*   **[etcd в Kubernetes](./kubernetes_integration.md)** — интеграция с K8s.
*   **[Ядерные параметры и тюнинг ОС](./kernel_tuning.md)** — sysctl, ionice, CPU governor.
*   **[MVCC и компакция](./mvcc_versioning_and_compaction.md)** — как избежать разрастания БД.
*   **[Мониторинг etcd](./etcd_monitoring.md)** — метрики здоровья, алертинг и WAL fsync.
