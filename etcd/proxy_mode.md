# Прокси-режим и масштабирование etcd

**Актуально для:** etcd 3.6.x / 3.7.x

> **Статус legacy:** встроенный прокси-режим (`--proxy=readonly|on`) существовал только в etcd ≤ 3.5, поддерживал **только v2 API** и удалён в 3.6 вместе с v2store. Описан в разделе «Legacy: v2 proxy mode (etcd ≤ 3.5)».

**etcd gRPC proxy** — stateless reverse proxy на уровне gRPC (L7). Снижает суммарную нагрузку на кластер: коалесцирует (объединяет) watch- и lease-запросы множества клиентов и кэширует range-ответы. Прокси не является членом кластера: не участвует в Raft-консенсусе, не хранит данных, не поднимает алармы NOSPACE/CORRUPT.

## Определения

| Термин | Описание |
| :--- | :--- |
| **gRPC proxy** | Stateless L7 reverse proxy для etcd v3 API. Запускается отдельным процессом: `etcd grpc-proxy start`. |
| **Watch coalescing** | N клиентских watchers (`c-watchers`) на один ключ/диапазон объединяются в один watcher к etcd (`s-watcher`); события транслируются всем `c-watchers`. Нагрузка на кластер снижается с N до 1. |
| **Lease coalescing** | N клиентских lease-streams объединяются в один keepalive-stream к etcd. Нагрузка со stream'ов снижается с N до 1. |
| **Range cache** | Кэш ответов на range-запросы, когда это не нарушает требований консистентности. Защищает кластер от abusive-клиентов в tight loops. |
| **Namespace** | `--namespace=<prefix>/` — прозрачное секционирование keyspace: запросы клиентов добавляют префикс, ответы его снимают. Клиент видит «полный» keyspace. |
| **Endpoint registration** | Регистрация прокси в кластере (ключ с TTL-сессией), чтобы клиенты могли обнаружить прокси через `member list`. |
| **Legacy v2 proxy** | Встроенный прокси-режим `--proxy=off\|readonly\|on` (etcd ≤ 3.5, только v2 API, удалён в 3.6). |

---

## Основные концепции

### Как работает gRPC proxy

- Прокси получает список endpoint'ов кластера через `--endpoints`. При старте случайно выбирает один endpoint и обслуживает все запросы через него.
- При обнаружении отказа endpoint'а прокси переключается на другой доступный endpoint, скрывая отказ от клиентов. Это **failover, а не load balancing**: weighted round-robin пока не реализован.
- Watch и lease запросы коалесцируются (см. определения), range-ответы кэшируются.
- Прокси stateless: горизонтально масштабируется, не требует data-dir с данными.

### Что прокси НЕ делает

- **Не масштабирует записи:** все writes идут в кластер (к лидеру). Для writes-heavy нагрузки прокси только добавляет latency — подключайтесь напрямую.
- **Не ускоряет линейные чтения:** linearizable read требует ReadIndex через лидера; прокси не устраняет эту задержку.
- **Не имеет read-only режима для v3 API** (etcd issue #8622) — в отличие от legacy v2 readonly-прокси.
- **Не балансирует нагрузку между endpoint'ами** — только failover при отказе.
- **Не заменяет LB:** клиенты должны знать адреса прокси или использовать endpoint registration.

### Когда использовать

| Сценарий | Что даёт прокси |
| :--- | :--- |
| Много watchers на одни ключи/диапазоны (informer'ы K8s) | Watch coalescing: N watchers → 1 s-watcher |
| Много клиентов с активными leases | Lease coalescing: N streams → 1 keepalive-stream |
| Abusive-клиенты (tight loops на чтение) | Range cache защищает кластер |
| Общий кластер, изоляция приложений | `--namespace` (multi-tenancy) |
| TLS termination | Прокси принимает plaintext локально, к кластеру подключается по TLS |
| Автообнаружение прокси клиентами | Endpoint registration (`--resolver-prefix`) |

### Legacy: v2 proxy mode (etcd ≤ 3.5)

В etcd ≤ 3.5 флаг `--proxy` включал встроенный прокси-режим. **Поддерживал только v2 API.**

| Режим | Поведение |
| :--- | :--- |
| `--proxy=on` (readwrite, по умолчанию в fallback) | Пересылает read и write запросы в кластер |
| `--proxy=readonly` | Пересылает только read-запросы; на все write-запросы возвращает **HTTP 501** |

Сопутствующие флаги (все удалены в 3.6): `--proxy-failure-wait` (5000 мс), `--proxy-refresh-interval` (30000 мс), `--proxy-dial-timeout` (1000 мс), `--proxy-write-timeout` (5000 мс), `--proxy-read-timeout` (0 — без таймаута).

**Особенности legacy-режима:**
- Прокси слушал `listen-client-urls` и обнаруживал кластер из `initial-cluster` или discovery URL.
- При bootstrap через discovery service лишние процессы (свыше `size=`) по умолчанию становились readwrite-прокси. В 3.6 дефолт `--discovery-fallback` изменён с `'proxy'` на `'exit'`.
- **Удалён в 3.6** (PR #18999) вместе с v2store, на которой он работал.
- **Ловушка апгрейда:** `etcd.conf.yml` парсится нестрогим `yaml.Unmarshal` — удалённые ключи **молча игнорируются**. Конфиг со старыми `proxy:` настройками запустится без ошибки, но прокси работать не будет. Удалите `--proxy*` флаги **до** апгрейда на 3.6.
- **Миграция:** замените встроенный прокси на `etcd grpc-proxy start` (см. сценарии ниже).

---

## Практические сценарии

### Запуск gRPC proxy

```bash
# На прокси-узле (stateless, data-dir не требуется)
etcd grpc-proxy start \
  --endpoints=infra0.example.com:2379,infra1.example.com:2379,infra2.example.com:2379 \
  --listen-addr=10.0.2.10:2379
```

**Валидация:**
```bash
# Запрос через прокси
ETCDCTL_API=3 etcdctl --endpoints=10.0.2.10:2379 put foo bar
# → OK
ETCDCTL_API=3 etcdctl --endpoints=10.0.2.10:2379 get foo
# → foo
# → bar

# Прокси не является членом кластера — в member list его нет
ETCDCTL_API=3 etcdctl --endpoints=10.0.1.10:2379 member list
```

### Namespacing (multi-tenancy)

```bash
etcd grpc-proxy start --endpoints=localhost:2379 \
  --listen-addr=127.0.0.1:23790 \
  --namespace=my-prefix/

# Клиент работает с «полным» keyspace без префикса:
ETCDCTL_API=3 etcdctl --endpoints=127.0.0.1:23790 put my-key abc
# → OK
# В кластере ключ записан как my-prefix/my-key:
ETCDCTL_API=3 etcdctl --endpoints=localhost:2379 get my-prefix/my-key
# → my-prefix/my-key
# → abc
```

### TLS termination

Прокси принимает plaintext-соединения локально, а к кластеру подключается с клиентскими сертификатами:

```bash
etcd grpc-proxy start --endpoints=https://localhost:2379 \
  --listen-addr=localhost:12379 \
  --cert client.crt --key client.key --cacert=ca.crt \
  --insecure-skip-tls-verify

# Проверка: запись по plaintext через прокси
ETCDCTL_API=3 etcdctl --endpoints=http://localhost:12379 put abc def
# → OK
```

Для приёма TLS на стороне прокси (вместо plaintext) используйте `--cert-file`/`--key-file` (серверный сертификат прокси) и `--trusted-ca-file`.

### Endpoint registration и автообнаружение

```bash
etcd grpc-proxy start --endpoints=localhost:2379 \
  --listen-addr=127.0.0.1:23790 \
  --advertise-client-url=127.0.0.1:23790 \
  --resolver-prefix="___grpc_proxy_endpoint" \
  --resolver-ttl=60
```

- Прокси регистрирует себя в кластере ключом с TTL-сессией; при падении прокси запись исчезает.
- `member list` через прокси возвращает его собственный `advertise-client-url`.
- На стороне клиента (Go): `cli.Sync(ctx)` получает список зарегистрированных прокси.

### Metrics и health

Прокси экспонирует `/health` и Prometheus `/metrics` для endpoint'ов из `--endpoints`. Альтернатива — отдельный интерфейс через `--metrics-addr`.

**Known issue:** основной интерфейс прокси обслуживает и HTTP/2, и HTTP/1.1. При TLS на основном интерфейсе cURL для `/metrics` и `/health` требует явного `--http1.1`; с `--metrics-addr` это ограничение не проявляется:

```bash
curl --cacert proxy-ca.pem --key proxy-client.key --cert proxy-client.crt \
  https://127.0.0.1:23790/metrics --http1.1
```

### Паттерн масштабирования: пул прокси

```
[ API Server ] → [ External LB ] → [ gRPC proxy pool ] → [ etcd Cluster (3-5 узлов, NVMe) ]
```

- Прокси stateless: добавляйте экземпляры горизонтально при росте числа watchers/leases.
- Размещайте прокси в той же AZ, что и клиенты, чтобы минимизировать RTT.
- Метрики здоровья кластера (`etcd_server_compact_index_gap`, `etcd_mvcc_db_total_size_in_bytes`, `etcd_server_has_leader`) снимайте **с членов кластера**, а не с прокси — прокси этих данных не хранит.
- **Capacity planning** (размер БД, treeIndex, RAM, квота) — в **[Лимиты и ограничения](./limits_and_constraints.md)** (SSoT). Прокси снижает нагрузку от клиентов, но не меняет требования к размеру кластера: кворум и объём данных определяются числом ключей, а не числом клиентов.

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Прокси не подключается к кластеру | Неверные `--endpoints` или TLS (сертификаты, CA) | Проверить `--endpoints`, `--cacert`, `--cert`, `--key`; доступность 2379 |
| Клиент не получает события с начала | Watch без явной revision может начаться с более старой ревизии (напр., 990 вместо 1000) — coalesced `s-watcher` может отставать | При resume указывать revision явно (`etcdctl watch --rev=N`) |
| Записи через прокси не проходят | Прокси недоступен или endpoint'ы в `--endpoints` недостижимы | Проверить failover: `etcdctl endpoint health` на каждом endpoint'е |
| cURL не возвращает `/metrics` | Основной интерфейс обслуживает HTTP/2 + HTTP/1.1 | Добавить `curl --http1.1` или вынести метрики на `--metrics-addr` |
| Прокси отсутствует в `member list` | Ожидаемо: прокси не член кластера | Проверять доступность через `endpoint status` на адресе прокси |
| Цикл пересылки, утечка FD (legacy) | `advertise-client-urls` члена указывает на прокси, прокси пересылает запрос самому себе | В `advertise-client-urls` указывать прямые URL членов кластера |

---

## Best Practices

- **Не используйте прокси для writes-heavy нагрузки:** прокси добавляет latency; подключайтесь к кластеру напрямую.
- **Не размещайте прокси на узлах-членах etcd:** изолируйте ресурсы (CPU, network).
- **Бэкапы — только на голосующих узлах:** прокси не хранит данных, снапшоты с него невозможны.
- **Не полагайтесь на прокси для масштабирования линейных чтений:** linearizable reads всё равно идут через лидера.
- **Апгрейд 3.5 → 3.6:** удалите `--proxy*` флаги из конфига до апгрейда — иначе они будут молча проигнорированы.
- **Мониторьте кластер, а не прокси:** алермы на `etcd_server_has_leader`, NOSPACE и размер БД ставьте на членов кластера.

---

## Edge Cases

- **Failover, а не LB:** прокси держит один endpoint и переключается только при отказе. Для равномерного распределения используйте несколько прокси + LB перед ними.
- **Watch revision caveat:** при неуказанной revision начало watch через прокси не гарантируется с последней ревизии хранилища.
- **Namespace:** префикс указывается с завершающим слэшем (`--namespace=my-prefix/`); клиенты «видят» keyspace без префикса, но RBAC etcd применяется к реальным (с префиксом) ключам.
- **CN-auth несовместим с прокси:** gRPC proxy терминирует TLS, и сервер видит CN прокси вместо CN клиента (см. [Безопасность etcd](./security.md)).
- **Geo-распределённый кластер:** etcd не предназначен для высоких задержек между ДЦ (Peer RTT < 50 мс); прокси не устраняет задержку линейных чтений, так как ReadIndex идёт к лидеру.
- **Legacy readonly:** write-запросы к v2 readonly-прокси возвращали HTTP 501; для v3 API read-only режима не существует.

---

## См. также

* **[Архитектура и основные концепции](./architecture-and-concepts.md)** — пути записи и чтения, Raft.
* **[Лимиты и ограничения](./limits_and_constraints.md)** — SSoT по capacity planning (quota-backend-bytes, treeIndex, RAM).
* **[Безопасность etcd](./security.md)** — TLS termination, CN-auth и несовместимость с прокси.
* **[Конфигурация и развертывание](./configuration_and_deployment.md)** — флаги etcd.conf.yml.
* **[Мониторинг etcd](./etcd_monitoring.md)** — метрики кластера.
* **[Аварийное восстановление](./emergency_recovery.md)** — `--force-new-cluster` и DR.
