# etcd: альтернативы и безопасность

**Актуально для:** Kubernetes 1.30+ / etcd 3.5+ / Kine 0.11+ / Dqlite 1.16+

## Определения

**Kine** (Kine Is Not etcd) — легковесный трансляционный прокси (shim), реализующий серверную часть протокола gRPC etcd v3 поверх реляционных СУБД (PostgreSQL, MySQL, SQLite). Это позволяет использовать существующие корпоративные RDBMS или встраиваемые базы в качестве хранилища состояния кластера Kubernetes без модификации кода `kube-apiserver`.

**Dqlite** (Distributed SQLite) — встраиваемая библиотека распределенной базы данных на базе SQLite, использующая алгоритм консенсуса Raft (реализация `c-raft` на языке C). Применяется в дистрибутиве MicroK8s для создания компактных и автономных High Availability (HA) кластеров на bare-metal и edge-инфраструктуре.

**KubeBrain** — высокопроизводительный движок хранения метаданных Kubernetes, разработанный для гипермасштабируемых кластеров (10 000+ узлов). Предоставляет etcd v3-совместимый gRPC API, транслируя операции в распределенные транзакционные KV-хранилища (преимущественно FoundationDB), что снимает лимит etcd в 8 ГБ на размер базы данных и узкое горло одиночного Raft-кворума на запись.

**Encryption at Rest (EaR)** — механизм криптографической защиты данных на диске, реализуемый на уровне `kube-apiserver`. Данные шифруются перед отправкой в хранилище (etcd или Kine) и расшифровываются при чтении в соответствии с конфигурацией `EncryptionConfiguration`.

**KMS v2 (Key Management Service)** — стандартизированный gRPC-протокол Kubernetes для интеграции с внешними провайдерами ключей (в on-prem инфраструктуре: HashiCorp Vault Transit Secret Engine, аппаратные HSM-модули). С версии Kubernetes 1.29 переведен в статус General Availability (GA) и является рекомендуемым стандартом конвертного шифрования.

**Envelope Encryption (Конвертное шифрование)** — двухуровневая криптографическая схема защиты: полезная нагрузка ресурса шифруется локальным ключом шифрования данных (DEK — Data Encryption Key), а сам DEK шифруется мастер-ключом (KEK — Key Encryption Key), хранящимся в защищенном внешнем хранилище (KMS/Vault/HSM).

**mTLS (Mutual TLS)** — двусторонняя криптографическая аутентификация и шифрование сетевого трафика. В архитектуре хранилища Kubernetes mTLS обязателен как для клиентского взаимодействия (`kube-apiserver` <-> etcd/Kine), так и для межсерверной репликации между узлами (etcd peer communication).

---

## Архитектура и основные концепции

### Архитектура Kine и трансляция протокола etcd v3

В стандартной архитектуре Kubernetes `kube-apiserver` взаимодействует с хранилищем исключительно по протоколу gRPC etcd v3. Kine перехватывает эти вызовы и транслирует их в эквивалентные SQL-запросы к реляционной СУБД.

```text
+---------------------------------------------------------------------------------+
|                                 kube-apiserver                                  |
|         (--etcd-servers=http://127.0.0.1:2379, --storage-backend=etcd3)         |
+---------------------------------------------------------------------------------+
                                         |
                                         | gRPC (etcd v3 API: Get, Put, Range, Watch)
                                         v
+---------------------------------------------------------------------------------+
|                                  Kine Daemon                                    |
|   - gRPC Server (:2379 или unix:///run/kine.sock)                              |
|   - MVCC Translation Engine (генерация ревизий, трансляция Range в SQL)         |
|   - Watch Engine (PostgreSQL LISTEN/NOTIFY или Polling Loop)                    |
|   - Background Compactor (очистка устаревших строк таблицы kine)               |
+---------------------------------------------------------------------------------+
                                         |
                                         | SQL Protocol (TCP/Unix Socket)
                                         v
+---------------------------------------------------------------------------------+
|                      Реляционная СУБД (PostgreSQL / MySQL / SQLite)             |
|   Таблица "kine": (id, name, created, deleted, create_revision, value, ...)     |
+---------------------------------------------------------------------------------+
```

#### Внутренняя схема данных таблицы `kine`

Kine создает в целевой базе данных единую таблицу со следующей структурой:

| Колонка | Тип данных (Postgres/SQLite) | Назначение |
| :--- | :--- | :--- |
| `id` | `BIGSERIAL` / `INTEGER PRIMARY KEY` | Глобальный монотонный идентификатор; выполняет роль `etcd Revision` |
| `name` | `TEXT` / `VARCHAR` | Ключ объекта Kubernetes (например, `/registry/pods/default/nginx`) |
| `created` | `INTEGER` | Флаг первичного создания (1) или обновления (0) |
| `deleted` | `INTEGER` | Маркер логического удаления (tombstone): 0 — активен, 1 — удален |
| `create_revision` | `BIGINT` / `INTEGER` | Значение `id`, при котором объект был первоначально создан |
| `prev_revision` | `BIGINT` / `INTEGER` | Значение `id` предыдущей версии объекта |
| `lease` | `BIGINT` / `INTEGER` | Идентификатор аренды (lease ID), используемый для TTL |
| `value` | `BYTEA` / `BLOB` | Бинарное тело объекта (Protobuf с префиксом `k8s\x00` или шифротекст) |
| `old_value` | `BYTEA` / `BLOB` | Предыдущее значение объекта (для проверки условий CAS) |

#### Эмуляция MVCC и механизма Watch

1. **Запись и версионирование:** При создании (`Put`) или удалении (`Delete`) объекта Kine не выполняет SQL `UPDATE` существующей строки. Вместо этого вставляется **новая строка** с инкрементированным `id`. Текущим актуальным состоянием ключа считается строка с максимальным `id` для данного `name`, у которой `deleted = 0`.
2. **Механизм Watch:**
   - **PostgreSQL:** Kine задействует нативную систему публикации событий `LISTEN / NOTIFY`. При вставке записи триггер отправляет уведомление в канал, и Kine немедленно доставляет обновление информерам API-сервера. Это обеспечивает околонулевую задержку реакции контроллеров без паразитной нагрузки на базу.
   - **SQLite и MySQL:** Поддержка асинхронных уведомлений отсутствует, поэтому Watch реализуется через цикл периодического опроса (polling loop) запросом вида `SELECT * FROM kine WHERE id > ?`. При большом числе подписок (> 1000) polling создает заметную нагрузку на CPU и диск.
3. **Компакция (Compaction):** Фоновый процесс Kine периодически выполняет удаление физических строк, у которых `id` меньше минимально удерживаемой ревизии (`compact_rev`), предотвращая неограниченное разрастание реляционной таблицы.

---

### Сравнительный анализ альтернатив etcd

Выбор хранилища определяется масштабом кластера, аппаратными ограничениями и существующей инфраструктурой эксплуатации.

| Параметр | etcd v3 | Kine + PostgreSQL | Kine + SQLite | Dqlite (MicroK8s) | KubeBrain + FoundationDB |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Механизм консенсуса** | Встроенный Raft (кворум 3/5 узлов) | Делегирован СУБД (Patroni / Galera) | Отсутствует (один узел) | Встроенный Raft (`c-raft` C-lib) | Multi-Paxos (внутри FoundationDB) |
| **Предельный размер БД** | 2–8 ГБ (лимит BoltDB) | Сотни ГБ — терабайты | 1–2 ГБ | 2–4 ГБ | Десятки терабайт |
| **Реализация Watch** | Нативный streaming gRPC | `LISTEN / NOTIFY` | Эмуляция polling | Raft streaming | gRPC streaming |
| **Накладные расходы** | Минимальные (zero abstraction) | +10–25% (парсинг SQL, сетевой стек) | Минимальные | Низкие | Средние (распределенный транзакционный слой) |
| **Сложность эксплуатации** | Высокая (бэкапы, дефрагментация, quorum loss) | Стандартная для DBA (pg_dump, WAL-G, pg_stat) | Минимальная (файл на диске) | Автоматическая в рамках MicroK8s | Высокая (эксплуатация кластера FDB) |
| **Целевой сценарий** | Стандартные Production K8s (kubeadm, bare-metal) | vCluster, мультиарендность, большие объемы CRD | Edge-узлы, IoT, k3s, локальная разработка | Автономные Edge/Branch HA-кластеры | Hyperscale кластеры (10k+ узлов, 1M+ подов) |

---

### Модель безопасности хранилища (Defense-in-Depth)

Защита состояния кластера строится на 5 эшелонах безопасности:

```text
+------------------------------------------------------------------------------------+
| 1. Физический и ОС-уровень: dm-crypt/LUKS, права доступа 0700/0600                 |
+------------------------------------------------------------------------------------+
       |
+------------------------------------------------------------------------------------+
| 2. Сетевая изоляция: порт 2379/2380 закрыт nftables; bind к localhost/VLAN        |
+------------------------------------------------------------------------------------+
       |
+------------------------------------------------------------------------------------+
| 3. Транспортная безопасность: mTLS, раздельные CA (peer CA != client CA)          |
+------------------------------------------------------------------------------------+
       |
+------------------------------------------------------------------------------------+
| 4. Прикладное шифрование: EncryptionConfiguration, KMS v2 (HashiCorp Vault)        |
+------------------------------------------------------------------------------------+
       |
+------------------------------------------------------------------------------------+
| 5. Авторизация доступа: etcd RBAC / минимальные привилегии роли базы данных Kine   |
+------------------------------------------------------------------------------------+
```

#### Риск обхода API-сервера при использовании Kine

В классическом кластере с etcd доступ к базе жестко ограничен сертификатами mTLS и бинарным форматом Protobuf. В случае использования Kine с PostgreSQL/MySQL возникает специфический вектор атаки: **прямой SQL-доступ в обход Control Plane**.

1. **Суть угрозы:** Субъект с правами на чтение/запись в таблицу `kine` (скомпрометированный пароль БД, уязвимость в веб-интерфейсе администрирования СУБД, недобросовестный DBA) может напрямую модифицировать или извлекать объекты кластера.
2. **Последствия прямого изменения SQL:**
   - **Обход Admission Controllers:** Прямая вставка привилегированного пода или модификация роли RBAC минует валидирующие и мутирующие вебхуки (например, Kyverno или OPA Gatekeeper).
   - **Отсутствие в Audit Logs:** Запросы не фиксируются в журнале аудита Kubernetes (`kube-apiserver audit log`).
   - **Кража секретов:** Если секреты не защищены через `EncryptionConfiguration`, они читаются простым SQL-запросом `SELECT name, value FROM kine`.
3. **Меры нейтрализации:**
   - Выделение отдельного пользователя БД `kine_app` с правами исключительно на таблицу `kine` (без прав `SUPERUSER` и `CREATE DATABASE`).
   - Принудительное включение TLS для подключения к СУБД (`sslmode=verify-full`).
   - Изоляция сети СУБД в отдельном VLAN/сетевом пространстве имен, недоступном для рабочих нод кластера.
   - Обязательное шифрование секретов на уровне `kube-apiserver` через KMS v2.

---

## Практические сценарии

### Сценарий 1: Развертывание Kine с PostgreSQL и интеграция с kube-apiserver

В данном сценарии Kine запускается как локальный системный сервис, транслирующий вызовы `kube-apiserver` в выделенный кластер PostgreSQL.

#### Шаг 1: Подготовка базы данных PostgreSQL

Выполняется на сервере PostgreSQL (версия >= 14):

```bash
# Создание выделенного пользователя и базы данных
sudo -u postgres psql -c "CREATE USER kine_app WITH PASSWORD 'KineStrongPassword2026!';"
# → CREATE ROLE

sudo -u postgres psql -c "CREATE DATABASE kine_db OWNER kine_app ENCODING 'UTF8';"
# → CREATE DATABASE

# Ограничение прав пользователя только целевой базой
sudo -u postgres psql -c "REVOKE ALL ON DATABASE kine_db FROM PUBLIC;"
# → REVOKE

sudo -u postgres psql -c "GRANT CONNECT, TEMPORARY ON DATABASE kine_db TO kine_app;"
# → GRANT

# Включение расширения для мониторинга медленных запросов
sudo -u postgres -d kine_db -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;"
# → CREATE EXTENSION
```

#### Шаг 2: Установка и запуск Kine через systemd

Бинарный файл Kine загружается в `/usr/local/bin/kine`. Создается unit-файл `/etc/systemd/system/kine.service`:

```ini
[Unit]
Description=Kine (Kine Is Not etcd) Translation Service
Documentation=https://github.com/k3s-io/kine
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/kine \
  --endpoint="postgres://kine_app:KineStrongPassword2026!@127.0.0.1:5432/kine_db?sslmode=disable" \
  --listen-address="127.0.0.1:2379" \
  --metrics-bind-address="127.0.0.1:8080" \
  --datastore-max-idle-connections=20 \
  --datastore-max-open-connections=50 \
  --datastore-connection-max-lifetime=30m
Restart=always
RestartSec=5s
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

Запуск и проверка сервиса:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now kine.service
sudo systemctl status kine.service
# → Active: active (running)

# Проверка доступности порта gRPC
ss -tlpn | grep 2379
# → LISTEN 0 128 127.0.0.1:2379 users:(("kine",pid=14230,fd=3))

# Проверка метрик Kine
curl -s http://127.0.0.1:8080/metrics | grep kine_api_call_total | head -n 5
# → # HELP kine_api_call_total Total number of API calls made to Kine
```

#### Шаг 3: Настройка kube-apiserver

`kube-apiserver` взаимодействует с Kine по стандартному протоколу etcd v3. В манифесте `/etc/kubernetes/manifests/kube-apiserver.yaml` настраиваются стандартные параметры:

```yaml
spec:
  containers:
  - name: kube-apiserver
    command:
    - kube-apiserver
    - --storage-backend=etcd3
    - --etcd-servers=http://127.0.0.1:2379
    # Если Kine настроен с mTLS:
    # - --etcd-cafile=/etc/kubernetes/pki/kine/ca.crt
    # - --etcd-certfile=/etc/kubernetes/pki/kine/apiserver-client.crt
    # - --etcd-keyfile=/etc/kubernetes/pki/kine/apiserver-client.key
```

> **Важно:** В `kube-apiserver` **не существует** флагов `--storage-backend=kine` или `--kine-endpoint`. API-сервер воспринимает Kine как стандартный сервер etcd3. Попытка передачи несуществующих флагов приведет к сбою запуска контейнера Control Plane.

Проверка доступности состояния кластера:

```bash
kubectl get nodes
# → NAME           STATUS   ROLES           AGE   VERSION
# → master-node-1   Ready    control-plane   12m   v1.30.2

kubectl get pods -A
# → kube-system   coredns-7db6d8ff4d-2q6wb   1/1   Running   0   11m
```

---

### Сценарий 2: Анализ и аудит состояния кластера через SQL (Kine)

Хранение состояния в реляционной СУБД позволяет выполнять оперативный анализ емкости и поиск аномалий стандартными SQL-запросами к таблице `kine`.

```sql
-- 1. Подсчет активных объектов по типам ресурсов Kubernetes
SELECT 
  SPLIT_PART(name, '/', 3) AS resource_type,
  COUNT(*) AS active_count
FROM kine 
WHERE id IN (SELECT MAX(id) FROM kine GROUP BY name)
  AND deleted = 0 
GROUP BY resource_type 
ORDER BY active_count DESC;

-- 2. Поиск 10 крупнейших объектов (по размеру бинарного Protobuf payload)
SELECT 
  name, 
  pg_size_pretty(LENGTH(value)) AS raw_size,
  created,
  id AS revision
FROM kine 
WHERE id IN (SELECT MAX(id) FROM kine GROUP BY name)
  AND deleted = 0 
ORDER BY LENGTH(value) DESC 
LIMIT 10;

-- 3. Выявление "мусорных" ревизий: соотношение активных записей и исторических версий
SELECT 
  COUNT(*) AS total_rows,
  COUNT(*) FILTER (WHERE deleted = 0) AS live_rows,
  COUNT(*) FILTER (WHERE deleted = 1) AS tombstone_rows,
  pg_size_pretty(pg_total_relation_size('kine')) AS physical_table_size
FROM kine;

-- 4. Проверка объектов с активными Lease (блокировки лидеров и heartbeats узлов)
SELECT 
  name, 
  lease, 
  id AS last_modified_rev
FROM kine 
WHERE lease > 0 
  AND deleted = 0
ORDER BY lease DESC;
```

---

### Сценарий 3: Построение отказоустойчивого бэкенда для Kine на базе PostgreSQL HA (Patroni)

Для обеспечения высокой доступности (HA) Kine в production-окружении база данных развертывается в виде кластера Patroni с репликацией на базе физического потокового WAL и автоматическим failover.

```text
+-----------------------+     +-----------------------+
|  kube-apiserver 1     |     |  kube-apiserver 2     |
|  (kine -> 127.0.0.1)  |     |  (kine -> 127.0.0.1)  |
+-----------------------+     +-----------------------+
            \                             /
             \                           /
    +---------------------------------------------+
    | HAProxy / Keepalived (VIP: 10.10.10.50:5000)|
    +---------------------------------------------+
                           |
            +--------------+--------------+
            | (Read/Write к Master)       |
            v                             v
+-----------------------+     +-----------------------+
|  PostgreSQL Primary   |===> |  PostgreSQL Standby   |
|  (Patroni Leader)     | WAL |  (Patroni Replica)    |
+-----------------------+     +-----------------------+
```

1. **Балансировка:** Запросы на запись от всех инстансов Kine направляются строго на текущий Leader через локальный HAProxy или PgBouncer, проверяющий статус HTTP-эндпоинта Patroni (`http://node:8008/primary`).
2. **Строка подключения Kine к пулу:**
   ```bash
   --endpoint="postgres://kine_app:KineStrongPassword2026!@10.10.10.50:5000/kine_db?sslmode=verify-full&sslrootcert=/etc/kine/pki/db-ca.crt"
   ```
3. **Параметры пулинга:**
   - `--datastore-max-idle-connections=20`: удерживание прогретых соединений для исключения оверхеда на повторные TCP/TLS handshakes.
   - `--datastore-max-open-connections=100`: предел открытых сессий к СУБД с учетом общего пула соединений PostgreSQL (`max_connections`).

---

### Сценарий 4: Харденинг etcd: mTLS, разделение CA и сетевая изоляция

При эксплуатации стандартного etcd изоляция и сегментация доступа являются ключевыми требованиями CIS Kubernetes Benchmark.

#### Шаг 1: Разделение CA для клиентского и межсерверного трафика

Использование одного CA для peer и client трафика создает уязвимость: клиентский сертификат скомпрометированного рабочего компонента может быть использован для присоединения вредоносного узла в Raft-кворум.

Необходима генерация двух независимых цепочек:
- `etcd-ca-peer.crt` / `etcd-ca-peer.key` — подписывает только взаимные сертификаты узлов etcd (порт 2380).
- `etcd-ca-client.crt` / `etcd-ca-client.key` — подписывает серверные сертификаты etcd (порт 2379) и клиентские сертификаты `kube-apiserver`.

Конфигурация параметров демона etcd:

```bash
# Конфигурация межсерверного трафика (Peer)
--peer-client-cert-auth=true \
--peer-trusted-ca-file=/etc/etcd/pki/etcd-ca-peer.crt \
--peer-cert-file=/etc/etcd/pki/peer.crt \
--peer-key-file=/etc/etcd/pki/peer.key \
--peer-cert-allowed-cn=etcd-node-1,etcd-node-2,etcd-node-3 \

# Конфигурация клиентского трафика (Client)
--client-cert-auth=true \
--trusted-ca-file=/etc/etcd/pki/etcd-ca-client.crt \
--cert-file=/etc/etcd/pki/server.crt \
--key-file=/etc/etcd/pki/server.key
```

Параметр `--peer-cert-allowed-cn` гарантирует, что даже при наличии валидного сертификата от peer CA узел не будет допущен к выборам и репликации Raft, если его Common Name отсутствует в белом списке.

#### Шаг 2: Сетевая изоляция через nftables

Порт 2379 должен быть доступен исключительно локальным процессам Control Plane и доверенным адресам API-серверов. Порт 2380 — строго между узлами etcd.

Правила `/etc/nftables.conf`:

```text
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        # Разрешить loopback и установленные соединения
        iif "lo" accept
        ct state established,related accept

        # etcd peer traffic (порт 2380) только между master-узлами
        ip saddr { 10.10.10.11, 10.10.10.12, 10.10.10.13 } tcp dport 2380 accept

        # etcd client traffic (порт 2379) только для kube-apiserver
        ip saddr { 10.10.10.11, 10.10.10.12, 10.10.10.13 } tcp dport 2379 accept

        # Запрет всех остальных обращений к портам etcd
        tcp dport { 2379, 2380 } counter drop
    }
}
```

Проверка применения правил:

```bash
sudo nft -s list ruleset | grep 2379
# → ip saddr { 10.10.10.11, 10.10.10.12, 10.10.10.13 } tcp dport 2379 accept
```

---

### Сценарий 5: Резервное копирование и Disaster Recovery (etcd vs Kine)

Сравнение процедур снятия согласованных снимков и восстановления состояния.

#### etcd: Снимок через etcdctl и валидация через etcdutl

```bash
# 1. Снятие консистентного снапшота
ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  snapshot save /backup/etcd-snapshot-$(date +%F).db
# → Snapshot saved at /backup/etcd-snapshot-2026-10-18.db

# 2. Обязательная валидация целостности bbolt файла (offline-утилита etcdutl)
etcdutl snapshot status /backup/etcd-snapshot-$(date +%F).db -w table
# → +----------+----------+------------+------------+
# → |   HASH   | REVISION | TOTAL KEYS | TOTAL SIZE |
# → +----------+----------+------------+------------+
# → | a4f9e1b2 |  1942045 |      14201 |      45 MB |
# → +----------+----------+------------+------------+
```

#### Kine: Резервное копирование PostgreSQL через WAL-G / pg_dump

```bash
# Создание транзакционно-согласованного логического дампа
PGPASSWORD='KineStrongPassword2026!' pg_dump \
  -h 127.0.0.1 -p 5432 -U kine_app -d kine_db \
  -F c -b -v -f /backup/kine-db-$(date +%F).dump
# → pg_dump: dumping contents of table "public.kine"
# → pg_dump: finished item 210 ...

# Восстановление базы данных при аварии
sudo -u postgres dropdb kine_db
sudo -u postgres createdb -O kine_app kine_db
sudo -u postgres pg_restore -d kine_db -v /backup/kine-db-2026-10-18.dump
# → pg_restore: connecting to database for restore
# → pg_restore: processing data for table "public.kine"
```

---

## Диагностика и устранение неисправностей

| Симптом / Ошибка | Первопричина | Пошаговое решение |
| :--- | :--- | :--- |
| **`context deadline exceeded` при старте kube-apiserver** | 1. Kine не запущен или упал.<br>2. Закрыт сетевой порт 2379.<br>3. Несоответствие TLS-параметров. | 1. Проверить статус демона: `systemctl status kine`.<br>2. Проверить сокет: `ss -tlpn \| grep 2379`.<br>3. Изучить логи: `journalctl -u kine -n 50 --no-pager`. |
| **Деградация Watch и 100% CPU на SQLite (Kine)** | SQLite эмулирует Watch через постоянный polling базы. При > 1000 подов/информеров база упирается в I/O. | 1. Перевести кластер на PostgreSQL для активации нативного `LISTEN/NOTIFY`.<br>2. Временно перенести файл `.db` на tmpfs/NVMe.<br>3. Выполнить `sqlite3 state.db "PRAGMA optimize; PRAGMA wal_checkpoint(TRUNCATE);"`. |
| **`FATAL: remaining connection slots are reserved` (PostgreSQL)** | Kine исчерпал лимит `max_connections` СУБД из-за множества одновременных API-запросов. | 1. В `postgresql.conf` увеличить `max_connections` (например, с 100 до 300).<br>2. В `kine.service` ограничить пул: `--datastore-max-open-connections=50`.<br>3. Внедрить PgBouncer в режиме session pooling. |
| **`x509: certificate signed by unknown authority`** | 1. Перепутаны peer CA и client CA.<br>2. Не указан `--cacert` при вызове `etcdctl`.<br>3. Истек срок действия сертификата. | 1. Проверить сертификат: `openssl x509 -in /etc/etcd/pki/server.crt -text -noout`.<br>2. Сверить Subject Key Identifier с CA Authority Key Identifier.<br>3. Продлить сертификаты (`kubeadm certs renew etcd-server`). |
| **`mvcc: database space exceeded` (etcd Alarm NOSPACE)** | Размер базы BoltDB достиг квоты `--quota-backend-bytes` (по умолчанию 2 ГБ). etcd перешел в Read-Only. | 1. Запустить компакцию: `etcdctl compact $(etcdctl endpoint status -w json \| jq '.[0].Status.header.revision')`.<br>2. Дефрагментировать: `etcdctl defrag`.<br>3. Снять блокировку: `etcdctl alarm disarm`. |
| **Объекты создаются, но контроллеры не реагируют** | Нарушена доставка событий Watch (разрыв длинного gRPC-стрима или падение соединения Kine с БД). | 1. Проверить метрику `kine_compact_revision`.<br>2. Перезапустить Kine daemon для сброса пула соединений.<br>3. Проверить задержки репликации в PostgreSQL: `SELECT client_addr, state, replay_lag FROM pg_stat_replication;`. |

---

## Рекомендации по эксплуатации (Best Practices)

### Критерии выбора хранилища состояния

1. **Используйте стандартный etcd**, если:
   - Разворачивается стандартный production-кластер на 3–5 узлах Control Plane (bare-metal или виртуальные машины).
   - Инфраструктура обеспечена быстрыми NVMe-накопителями с задержкой fsync < 10 мс.
   - Штат SRE имеет регламенты бэкапа и дефрагментации etcd.
2. **Используйте Kine + PostgreSQL**, если:
   - В компании развернут надежный корпоративный кластер PostgreSQL HA под управлением выделенной команды DBA.
   - Используются виртуальные кластеры (vCluster) или мультиарендные платформы с сотнями тысяч CRD, выходящими за пределы квоты etcd в 8 ГБ.
   - Требуется глубокий аналитический аудит и мониторинг метаданных методами стандартного SQL.
3. **Используйте Kine + SQLite или Dqlite**, если:
   - Проект создается для Edge/IoT или удаленных филиалов с ограниченными ресурсами RAM (< 1–2 ГБ на ноду).
   - Разворачивается дистрибутив k3s (одиночный узел на SQLite) или MicroK8s (автономный HA на Dqlite).

### Настройки производительности PostgreSQL для Kine

При использовании PostgreSQL в качестве бэкенда Kine критически важны параметры I/O и памяти:

```ini
# postgresql.conf: Оптимизация под OLTP нагрузку Kine
shared_buffers = 2GB                  # 25% от доступной RAM сервера БД
effective_cache_size = 6GB            # 75% от доступной RAM
work_mem = 32MB
maintenance_work_mem = 256MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
random_page_cost = 1.1                # Для NVMe SSD дисков
synchronous_commit = off              # Допустимо для dev/staging ради кратного роста RPS записи
```

> **Предупреждение SRE:** Установка `synchronous_commit = off` существенно увеличивает пропускную способность на запись при частых обновлениях подов, однако при аварийном отключении питания сервера БД существует риск потери последних транзакций за время `wal_writer_delay` (до 200 мс). Для production с высокими требованиями к RPO значение должно оставаться `on` или `remote_apply`.

### Метрики и алертинг в Prometheus

Для предотвращения деградации Control Plane настройте мониторинг следующих показателей:

| Метрика | Источник | Пороговое значение | Описание инцидента |
| :--- | :--- | :--- | :--- |
| `kine_api_call_latency_seconds{quantile="0.99"}` | Kine (:8080) | > 0.1s | Высокая задержка трансляции API-запросов к SQL |
| `kine_compact_revision` | Kine (:8080) | Не растет > 1 часа | Сбой механизма компакции, риск распухания таблицы `kine` |
| `etcd_disk_wal_fsync_duration_seconds{quantile="0.99"}` | etcd (:2379) | > 10ms | Медленный диск; риск потери кворума и перевыборов лидера |
| `etcd_server_has_leader` | etcd (:2379) | != 1 | Потеря лидера кластера etcd (Control Plane перешел в Read-Only) |
| `etcd_mvcc_db_total_size_in_bytes / etcd_server_quota_backend_bytes` | etcd (:2379) | > 0.85 | Заполнение квоты базы данных; приближение аларма `NOSPACE` |

---

## Дополнительная информация

*   **[Обзор etcd в Kubernetes](./etcd_overview.md)** — концептуальная роль etcd, префиксы реестра и параметры отказоустойчивости.
*   **[Сравнение etcd, Consul и ZooKeeper](../../etcd/alternatives_comparison.md)** — глубокий анализ распределенных KV-хранилищ и алгоритмов консенсуса.
*   **[Безопасность etcd: TLS, RBAC и шифрование](../../etcd/security.md)** — детальный разбор конфигурации TLS, списков отзыва CRL и внутреннего RBAC.
*   **[Хранение Secret в etcd](../Base/secrets/etcd_storage.md)** — Single Source of Truth (SSoT) по конвертному шифрованию, спецификации `EncryptionConfiguration` и устройству плагинов KMS v2.
*   **[Архитектура Control Plane](./control_plane_architecture.md)** — размещение etcd (Stacked vs External) и влияние на отказоустойчивость.
*   **[Архитектура K3s](../Installation/k3s_dev_environment/k3s_architecture.md)** — реализация Kine и SQLite в dev-окружении.
*   **[Обзор MicroK8s](../Installation/microk8s/microk8s_overview.md)** — развертывание и функционирование отказоустойчивого хранилища Dqlite.
