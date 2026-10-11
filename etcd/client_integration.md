# Клиентская интеграция и библиотеки etcd

**Актуально для:** etcd 3.6.x / 3.7.x (Go clientv3; неблокирующее создание клиента — 3.7+, retry-параметры в `Config` — с 3.5, серверная поддержка Unix-сокетов — 3.7)

Клиентская интеграция — это то, что связывает приложение с кластером etcd: транспорт (gRPC), выбор endpoint'ов, балансировка, повторы, обработка ошибок и поведение watch/lease при разрывах. Большинство production-инцидентов «etcd недоступен» на стороне приложения — это не проблема кластера, а неверная конфигурация клиента: слишком короткий `DialTimeout`, отсутствие повторов, игнорирование `WaitForReady` или необработанная компакция watch.

Внутреннее устройство watch и lease описано в [Watch и Lease: внутреннее устройство](./watch_lease_internals.md), лимиты размеров запросов — в [Лимиты и ограничения](./limits_and_constraints.md), серверные флаги — в [Конфигурация и развёртывание](./configuration_and_deployment.md).

**Prerequisites:** установленный Go (для примеров на clientv3), доступность client-эндпоинта etcd (`:2379`), базовое понимание gRPC и HTTP/2.

## Определения

| Термин | Описание |
| :--- | :--- |
| **clientv3** | Официальный Go-клиент v3 API etcd (`go.etcd.io/etcd/client/v3`). Базируется на gRPC и grpc-go. |
| **gRPC gateway** | HTTP/JSON-транслятор в gRPC, встроенный в etcd. Позволяет вызывать v3 API обычными HTTP-запросами (`--enable-grpc-gateway`, по умолчанию включён). |
| **gRPC proxy** | Отдельный процесс, проксирующий gRPC-запросы к кластеру и кеширующий watch-события. Детали — в [gRPC proxy](./proxy_mode.md). |
| **Resolver / Balancer** | Внутренние компоненты gRPC: resolver отдаёт список адресов, balancer выбирает соединение. clientv3 использует собственный resolver с политикой `round_robin`. |
| **WaitForReady** | gRPC-опция, при которой запрос ждёт готовности соединения вместо немедленного отказа. clientv3 включает её по умолчанию. |
| **WithRequireLeader** | Обёртка контекста, при которой запрос завершается успехом только если в кластере есть лидер. |
| **AutoSyncInterval** | Интервал, с которым клиент обновляет список endpoint'ов актуальным составом кластера. `0` — выключено. |
| **Embed** | Режим встраивания etcd как библиотеки в Go-приложение (пакет `go.etcd.io/etcd/server/v3/embed`). |

---

## Основы клиентского взаимодействия

### Транспорт: gRPC и HTTP/JSON gateway

Единственный нативный протокол v3 API — **gRPC** (HTTP/2 + Protobuf). Отдельного REST API v3 нет: HTTP/JSON-доступ обеспечивает встроенный **gRPC-gateway**, слушающий тот же client-эндпоинт `:2379`. Это значит:

- Любой клиентский трафик (SDK, `etcdctl`, gateway) идёт на один и тот же порт.
- HTTP/JSON удобен для отладки и простых интеграций, но заметно медленнее gRPC из-за сериализации. Стримовые RPC (watch, snapshot) через gateway идут по WebSocket — HTTP-mux обёрнут в `wsproxy.WebsocketProxy`; обычным HTTP-поллингом они недоступны.
- REST-вызовы через gateway описаны в [Maintenance API](./maintenance_api.md); флаг `--enable-grpc-gateway` — в [Конфигурации и развёртывании](./configuration_and_deployment.md).

### Формат endpoint'ов и схема

`Config.Endpoints` — список URL. Схема **первого** endpoint определяет схему для всех остальных:

```go
clientv3.New(clientv3.Config{
    Endpoints: []string{"https://etcd-0:2379", "https://etcd-1:2379", "https://etcd-2:2379"},
})
```

Поддерживаются `http://`, `https://`, форма без схемы (`etcd-0:2379` — трактуется как `http`) и Unix-сокет (`unix:///path/to/etcd.sock`): клиент разбирает схемы `unix:`/`unixs:`, а поддержка на стороне сервера — приём `unix://` в `--listen-client-urls` — появилась в 3.7 (changelog 3.7, PR #19760; в 3.6 и раньше валидация URL отклоняла unix-схему). Для TLS достаточно одного `https://` первого endpoint — сертификат проверяется по имени хоста endpoint'а.

### Жизненный цикл клиента

**Клиент следует создавать один раз и переиспользовать.** `Client` хранит внутреннее состояние (наборы watcher'ов и lease) и безопасен для конкурентного использования из нескольких горутин. Создание клиента на каждый запрос приводит к утечке горутин и потоков.

```go
cli, err := clientv3.New(clientv3.Config{
    Endpoints:   []string{"localhost:2379", "localhost:22379", "localhost:32379"},
    DialTimeout: 5 * time.Second,
})
if err != nil {
    // handle error
}
defer cli.Close() // закрывать обязательно — иначе утекут горутины
```

Таймаут отдельного запроса задаётся не через `Config`, а через контекст:

```go
ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
defer cancel()
resp, err := cli.Put(ctx, "sample_key", "sample_value")
```

### Неблокирующее создание клиента (3.7+)

До 3.7 `DialTimeout` ограничивал и установку соединения: `clientv3.New` мог вернуть ошибку по таймауту, если ни один endpoint не отвечал. Начиная с 3.7 клиент создаётся **неблокирующе** (grpc-go `NewClient`): `clientv3.New` возвращает объект до установления соединения, а `DialTimeout` теперь применяется только к отдельным операциям — получению auth-токена и проверке версии кластера при `RejectOldCluster=true`. Опция `grpc.WithBlock` в 3.7+ не учитывается (changelog 3.7, PR #21942). Отсюда практическое следствие: в 3.7 отсутствие коннекта к кластеру проявляется не ошибкой `New`, а ошибкой первого запроса или предупреждением в логе.

### Большие выборки: GetStream и RangeStream (3.7+)

Обычный `Get` буферизует весь ответ целиком — и на сервере, и в клиенте; на диапазонах в сотни тысяч ключей это пик потребления памяти и риск OOM. Начиная с etcd 3.7 сервер отдаёт такие ответы потоком через RPC `RangeStream` (устройство серверной части — в [Архитектура и основные концепции](./architecture-and-concepts.md)), клиентский API:

```go
ch, err := cli.GetStream(ctx, "/registry/pods/", clientv3.WithPrefix())
if err != nil {
    // ошибка до начала потока: нет соединения или сервер без RangeStream (< 3.7)
}
for chunk := range ch {
    if err := chunk.Err(); err != nil {
        // ошибка в середине потока: компакция, неверные опции и т.п.
        break
    }
    for _, kv := range chunk.Kvs { // чанки не пересекаются
        _ = kv
    }
}
```

- `GetStream(ctx, key, opts...)` принимает те же опции, что и `Get` (`WithPrefix`, `WithRange`, `WithFromKey`, `WithRev`, `WithLimit`).
- Каждый элемент канала — чанк `RangeStreamResponse`: `Header`, `More` и `Count` заполняются только в последнем чанке. При ошибке в середине потока последний элемент — терминальный чанк с `Err() != nil` (его нельзя разыменовывать — `RangeResponse` в нём `nil`), после чего канал закрывается; нормальное завершение (EOF) — просто закрытие канала без ошибки.
- `clientv3.GetStreamToGetResponse(ch)` сворачивает поток в обычный `*GetResponse`, если нужен привычный формат; при ошибке потока возвращает её.
- В `etcdctl` — флаг `--stream`: `etcdctl get --stream --prefix /registry/`.
- Ограничения серверной стороны (нестандартная сортировка, фильтры по revision) — в [Архитектура и основные концепции](./architecture-and-concepts.md). На серверах без 3.7 `GetStream` вернёт `Unimplemented` — используйте пагинацию через `WithRange`/`WithLimit` (см. [Лимиты и ограничения](./limits_and_constraints.md)).

### Вспомогательные пакеты clientv3

Помимо базового API, в составе `go.etcd.io/etcd/client/v3` есть готовые обёртки:

| Пакет | Назначение |
| :--- | :--- |
| `concurrency` | Распределённые блокировки (`Mutex`, `NewLocker`), выборы лидера (`Election`) и STM-транзакции — см. [Паттерны использования](./usage_patterns.md). |
| `namespace` | Обёртка, дописывающая всем ключам фиксированный префикс. |
| `ordering` | Обёртка, обнаруживающая нарушения порядка (stale-ответы) и позволяющая задать политику реакции на них. |
| `mirror` | Зеркалирование префикса: `Syncer` отдаёт базовое состояние (`SyncBase`) и далее поток изменений (`SyncUpdates`). |
| `leasing` | Линейизуемые чтения из локального кэша через клиентский протокол аренды ключей. |
| `snapshot` | Утилиты вокруг снапшотов etcd (создание и чтение файла бэкапа). |
| `naming` | Хранение адресов gRPC-сервисов в etcd и etcd-backed resolver для gRPC-клиентов/серверов. |

---

## Конфигурация clientv3

Ключевые поля `clientv3.Config` и их значения по умолчанию (проверено по `client/v3/config.go`, `client/v3/options.go` и `client/v3/client.go` для 3.7.2):

| Поле | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `Endpoints` | — (минимум один) | Список адресов кластера. Пустой список — ошибка `at least one Endpoint is required`. |
| `DialTimeout` | `0` | Таймаут операций установки связи: получение auth-токена, проверка версии (`RejectOldCluster`). От него же зависит первоначальный дедлайн первого keep-alive lease: `DialTimeout + 1 s`, при `0` — 5 s. В 3.6 и раньше также ограничивал установку соединения. |
| `AutoSyncInterval` | `0` (выключено) | Периодически обновлять endpoints актуальным составом кластера. |
| `DialKeepAliveTime` | `0` (keepalive не настраивается) | Интервал gRPC keepalive-ping'ов. При `>0` передаётся в `keepalive.ClientParameters`. |
| `DialKeepAliveTimeout` | `0` | Ожидание ответа на keepalive-ping до разрыва соединения. |
| `MaxCallSendMsgSize` | `2 MiB` (2 097 152) | Лимит отправляемого сообщения. При превышении клиент не отправит запрос. |
| `MaxCallRecvMsgSize` | `math.MaxInt32` | Лимит принимаемого ответа. clientv3 переопределяет gRPC-дефолт (4 MB) на максимум `int32`. |
| `Username` / `Password` | — | Включают аутентификацию; токен обновляется автоматически. |
| `Token` | — | Готовый auth-токен вместо username/password. Взаимоисключимо с `Username`/`Password`. |
| `TLS` | `nil` | `*tls.Config` для клиентских соединений. |
| `RejectOldCluster` | `false` | Отказываться создавать клиент к кластеру старше версии клиента. |
| `MaxUnaryRetries` | `100` | Максимум повторов unary-запросов. Значение `>0` в `Config` переопределяет дефолт. |
| `BackoffWaitBetween` | `25 ms` | Пауза между повторами. |
| `BackoffJitterFraction` | `0.10` | Джиттер паузы между повторами. |
| `PermitWithoutStream` | `false` | Разрешить keepalive-пинги без активных RPC. |
| `DialOptions` | — | Дополнительные `grpc.DialOption` (интерсепторы и т.п.). |
| `Context` | — | Корневой контекст клиента. |

**Важно про `RejectOldCluster`:** при его включении `DialTimeout` используется для запроса версии кластера, поэтому нулевой `DialTimeout` в этом режиме приведёт к ожиданию без таймаута — задавайте ненулевое значение.

### Проверка лимитов

clientv3 по умолчанию принимает ответы практически без ограничения (`MaxCallRecvMsgSize = math.MaxInt32`), а **отправляет** не более 2 MiB. При повышении серверного `--max-request-bytes` выше 2 MiB увеличивать `MaxCallRecvMsgSize` почти всегда не нужно — важно поднять `MaxCallSendMsgSize`:

```go
cli, _ := clientv3.New(clientv3.Config{
    Endpoints:          []string{"localhost:2379"},
    MaxCallSendMsgSize: 10 * 1024 * 1024, // 10 MiB, >= server --max-request-bytes
})
```

Если задан только один из лимитов и `MaxCallSendMsgSize > MaxCallRecvMsgSize`, клиент вернёт ошибку вида `gRPC message recv limit (N bytes) must be greater than send limit (M bytes)`.

---

## Отказоустойчивость, балансировка и повторы

### Балансировка между endpoint'ами

clientv3 использует собственный resolver (`client/v3/internal/resolver`) с service config `{"loadBalancingPolicy": "round_robin"}`. Практические следствия:

- Запросы **равномерно распределяются** по всем живым endpoint'ам, а не идут всегда в первый.
- Resolver получает список адресов из `Config.Endpoints`, а в режиме `AutoSyncInterval` — и из фактического состава кластера (через member list). Это избавляет от ручного перечисления всех узлов.
- `SetEndpoints(...)` меняет список на лету; `Sync(ctx)` разово подтягивает актуальный состав; `AutoSyncInterval` делает это периодически.

### WaitForReady и повторы

clientv3 по умолчанию включает `grpc.WaitForReady(true)`: запрос не падает сразу при отсутствии готового соединения, а ждёт его — это уменьшает количество ложных ошибок при кратковременных сбоях. Поверх этого работает retry-интерсептор:

- **Unary-запросы:** до 100 повторов по умолчанию (`MaxUnaryRetries`), пауза между ними `BackoffWaitBetween` (25 ms) с джиттером `BackoffJitterFraction` (10%).
- **Повторяемые RPC** (читающие и статусные: `Range`, `Status`, `Hash`, `MemberList`, `LeaseTimeToLive` и им подобные — полный набор задан в `client/v3/retry.go`) повторяются только на gRPC `Unavailable` — то есть когда сервер не обработал запрос.
- **Мутабельные RPC** (`Put`, `Delete`, `Txn` и т.п.) повторяются только когда соединение ещё не установлено (ошибки `there is no address available` / `there is no connection available`): запрос гарантированно не дошёл до сервера, поэтому семантика write-at-most-once сохраняется. Полагаться на повторы как на механизм резервирования не нужно — для инкрементов и условных обновлений используйте транзакции (`Txn` с `Cmp`, см. [Паттерны использования](./usage_patterns.md)).
- **Стримы:** повторы по умолчанию отключены; безопасные для повтора стримы включаются индивидуально (например, watch имеет собственную логику переподключения).
- **Свой `ctx` главнее повторов:** при истёкшем или отменённом `ctx` интерсептор сразу возвращает ошибку, не расходуя бюджет повторов. При ошибке auth-токена клиент сначала обновляет токен и продолжает попытку.

### Обработка ошибок

clientv3 возвращает два класса ошибок:

1. **Контекстные** — `context.Canceled`, `context.DeadlineExceeded` (истёк `ctx` запроса).
2. **gRPC/серверные** — из пакета `go.etcd.io/etcd/api/v3/v3rpc/rpctypes`, сравниваются через `errors.Is` или прямой switch.

```go
resp, err := cli.Put(ctx, "", "")
if err != nil {
    switch {
    case errors.Is(err, context.Canceled):
        // ctx отменён другой горутиной
    case errors.Is(err, context.DeadlineExceeded):
        // истёк дедлайн ctx
    case errors.Is(err, rpctypes.ErrEmptyKey):
        // клиентская ошибка: ключ не задан
    case errors.Is(err, rpctypes.ErrRequestTooLarge):
        // запрос больше серверного лимита
    default:
        // недоступные endpoint'ы или иная серверная ошибка
    }
}
```

Проверенные строки ошибок rpctypes:

| Ошибка | Текст gRPC | Код |
| :--- | :--- | :--- |
| `ErrEmptyKey` | `etcdserver: key is not provided` | `InvalidArgument` |
| `ErrRequestTooLarge` | `etcdserver: request is too large` | `InvalidArgument` |
| `ErrCompacted` | `etcdserver: mvcc: required revision has been compacted` | `OutOfRange` |
| `ErrNoLeader` | `etcdserver: no leader` | `Unavailable` |
| `ErrLeaseNotFound` | `etcdserver: requested lease not found` | `NotFound` |

**Различение «своего» и «серверного» таймаута (clock skew):** если истёк серверный контекст раньше клиентского из-за расхождения часов, ответ приходит как gRPC-ошибка с кодом `DeadlineExceeded`, а не как `context.DeadlineExceeded`. Проверяйте оба варианта:

```go
if ev, ok := status.FromError(err); ok && ev.Code() == codes.DeadlineExceeded {
    // серверный таймаут — вероятен clock skew
}
```

После `cli.Close()` запросы, находящиеся «в полёте», возвращают ошибку; для 3.4+ её распознаёт `clientv3.IsConnCanceled(err)`.

---

## Watch на клиенте

`Watcher` автоматически переподключается при **восстановимых** ошибках (потеря соединения, смена лидера) и продолжает watch с последней полученной ревизии. Невосстановимые ошибки, прежде всего компакция, закрывают канал с ошибкой.

```go
watchCh := cli.Watch(ctx, "/config/", clientv3.WithPrefix())
for resp := range watchCh {
    if err := resp.Err(); err != nil {
        if errors.Is(err, rpctypes.ErrCompacted) {
            // нужна полная пересинхронизация: GET + новый Watch с актуальной ревизии
        }
        continue
    }
    for _, ev := range resp.Events {
        // ev.Type — PUT/DELETE, ev.Kv.Key, ev.Kv.Value
    }
}
```

Ключевое правило: **на компакцию клиент обязан отреагировать полным list'ом и новым watch с ревизии из заголовка ответа** — подробности и пример в [Watch и Lease](./watch_lease_internals.md).

- `clientv3.WithRequireLeader(ctx)` — watch завершится ошибкой `ErrNoLeader`, если кластер потерял лидера, вместо бесконечного ожидания. Полезно для контроллеров, которые не должны принимать решения без лидера.
- `clientv3.WithProgressNotify()` — периодические уведомления о прогрессе (пустые события с актуальной ревизией) помогают обнаружить молчаливую остановку watch.
- `WithRev(rev)` — старт с конкретной ревизии; `WithPrefix()`, `WithPrevKV()`, `WithFilterPut/Delete()` — фильтрация.

---

## Lease на клиенте

Аренда продлевается **клиентом**: `KeepAlive` держит long-lived gRPC-стрим и отправляет продления с интервалом `TTL/3`. Пока стрим жив, ключи не истекают.

```go
lease, err := cli.Grant(ctx, 10) // TTL = 10s
if err != nil {
    // handle error
}
_, err = cli.Put(ctx, "lock/leader", "node-1", clientv3.WithLease(lease.ID))

kaCh, err := cli.KeepAlive(ctx, lease.ID)
go func() {
    for range kaCh {
        // каждый ответ — продление; канал закроется при истечении или отзыве аренды
    }
}()
```

- `KeepAlive(ctx, id)` возвращает канал ответов; он закрывается при истечении/отзыве аренды. Если авто-продление сломалось, клиент возвращает `ErrKeepAliveHalted`, но `KeepAliveOnce` продолжает работать.
- `KeepAliveOnce(ctx, id)` — однократное продление для редких операций.
- Минимальный TTL ограничен формулой `MinLeaseTTL = ceil(1.5 × election-timeout)` (при дефолтах — 2 секунды); слишком короткий TTL продлевается до минимума. Детали и внутренние константы — в [Watch и Lease](./watch_lease_internals.md).

---

## Аутентификация и TLS

- **Пользователь/пароль:** заполните `Config.Username` и `Config.Password`. Клиент сам получает токен и обновляет его; `Config.Token` задаёт токен напрямую. Одновременное использование `Username`/`Password` и `Token` недопустимо (`ErrMutuallyExclusiveCfg`).
- **CN как имя пользователя:** при `--client-cert-auth=true` CN клиентского сертификата используется как имя пользователя. Механизм несовместим с gRPC-proxy и gRPC-gateway (см. [Безопасность](./security.md)).
- **TLS:** передайте настроенный `*tls.Config` в `Config.TLS`; при `https://` в первом endpoint без явного TLS применяется имя хоста endpoint'а как `ServerName`. Полная модель TLS — в [Безопасность](./security.md).

```go
cfg := clientv3.Config{
    Endpoints: []string{"https://etcd-0:2379"},
    Username:  "root",
    Password:  "secret",
    TLS:       tlsConfig, // *tls.Config с CA, cert и key
}
```

---

## Альтернативные способы доступа

| Способ | Назначение | Когда применять |
| :--- | :--- | :--- |
| **clientv3 (Go)** | Полноценный нативный доступ | Сервисы на Go; наиболее полный API, стримы, watch. |
| **HTTP/JSON gRPC gateway** | REST-подобный доступ | Отладка, простые скрипты, языки без gRPC-клиента. Стримы (watch, snapshot) — только по WebSocket. |
| **gRPC proxy** | Проксирование и кеширование watch | Много клиентов, читающих одни и те же ключи; снижение нагрузки на кластер. Подробнее — [gRPC proxy](./proxy_mode.md). |
| **Клиенты других языков** | Java, Python, C#, .NET и др. | Официальный список, версии и статус поддержки — в разделе «Libraries and tools» документации etcd. |
| **Embedding (`server/v3/embed`)** | etcd как библиотека внутри процесса | Встраивание в собственное приложение; не заменяет внешний HA-кластер — не рекомендуется для продакшена, где нужна отказоустойчивость. См. официальный гайд «Embedding etcd in a Go Application». |

---

## Практические сценарии

### Корректное завершение и graceful shutdown

```go
ctx, cancel := context.WithCancel(context.Background())
defer cancel()

cli, _ := clientv3.New(clientv3.Config{Endpoints: eps, DialTimeout: 5 * time.Second})
defer cli.Close() // закрывает соединения и фоновые горутины
```

Порядок важен: сначала отменяйте контексты запросов/watcher'ов (`cancel()`), затем `cli.Close()`. Запросы, попавшие в момент закрытия, вернут `IsConnCanceled(err)`.

### Read-only реплика через gRPC proxy

Если множество приложений читают один и тот же набор ключей, gRPC proxy кеширует watch-события и отдаёт линейизуемые чтения без обращения к лидеру на каждый запрос. Клиент подключается к прокси как к обычному endpoint — изменения в конфигурации clientv3 не требуются.

### Устойчивость к rolling update кластера

При последовательном перезапуске членов клиент с `AutoSyncInterval` и включённым `WaitForReady` переживает обновление без ручного вмешательства: resolver обновляет адреса, round-robin исключает недоступные, повторы переживают кратковременные обрывы.

---

## Валидация

После настройки клиента проверьте на реальном кластере базовый сценарий «запись → чтение → health»:

```bash
etcdctl --endpoints=localhost:2379 put probe/key ok
# → OK
etcdctl --endpoints=localhost:2379 get probe/key
# → probe/key
# ok
etcdctl --endpoints=localhost:2379 endpoint health
# → localhost:2379 is healthy: successfully committed proposal: took = 1.2ms
```

Тот же roundtrip на стороне Go — `cli.Put` → `cli.Get` с проверкой `err != nil` и один цикл `cli.Watch` (см. «Watch на клиенте»); в 3.7 дополнительно — `cli.GetStream` на большом префиксе. Дальше — health всех узлов, задержки и метрики кластера: [Мониторинг и диагностика](./etcd_monitoring.md).

---

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `etcdserver: request is too large` | Запрос больше `--max-request-bytes` сервера | Уменьшить значение или поднять серверный лимит и `MaxCallSendMsgSize` клиента |
| `gRPC message recv limit ... must be greater than send limit` | `MaxCallSendMsgSize > MaxCallRecvMsgSize` | Задать `MaxCallRecvMsgSize ≥ MaxCallSendMsgSize` |
| `context deadline exceeded` на каждом запросе | Истёк клиентский `ctx`; коннект медленный | Увеличить таймаут запроса, проверить сеть и `DialTimeout` |
| gRPC `DeadlineExceeded`, но клиентский `ctx` не истёк | Расхождение часов сервер/клиент | Синхронизировать NTP/chrony на всех узлах |
| `etcdserver: no leader` | Кластер потерял лидер (или включён `WithRequireLeader`) | Проверить кворум и сеть; см. [Network partitions](./network_partitions.md) |
| `mvcc: required revision has been compacted` | Начата ревизия, уже удалённая компакцией | Полный `GET` + новый watch с актуальной ревизии |
| `client: etcd cluster is unavailable or misconfigured` | Неверные endpoint'ы/схема, TLS-ошибка | Проверить первый endpoint и его схему, сертификаты |
| Утечка горутин, рост памяти в приложении | Клиент создаётся на каждый запрос и не закрывается | Переиспользовать один `Client`, всегда вызывать `Close()` |
| `ErrKeepAliveHalted` | Авто-продление аренды сломалось | Проверить сеть и TTL; при необходимости пересоздать lease |
| Пропали повторы или не вызываются интерсепторы метрик | `WithUnaryInterceptor` в `Config.DialOptions` перезаписывает retry-интерсептор clientv3 | Добавлять интерсепторы через `grpc.WithChainUnaryInterceptor` / `WithChainStreamInterceptor` |
| В логе приложения `Auto sync endpoints failed.` | Кратковременный сбой запроса member list при `AutoSyncInterval` (часто во время rolling update) | Если ошибки единичны — норма; постоянные — проверить `etcdctl endpoint health` и сеть (см. [Мониторинг и диагностика](./etcd_monitoring.md)) |

---

## Best Practices

- **Один клиент на процесс.** `Client` потокобезопасен; повторное создание — источник утечек.
- **Ненулевой `DialTimeout`** (например, 5 s) и явные таймауты на каждый запрос через контекст.
- **Не отключайте повторы и `WaitForReady` без причины** — они гасят большинство кратковременных сбоев.
- **`AutoSyncInterval`** (например, 30 s) вместо ручного перечисления всех узлов.
- **Для watch всегда обрабатывайте `resp.Err()`**, особенно `ErrCompacted`, и делайте пересинхронизацию.
- **Для lock/leader election** используйте идемпотентные операции и lease, а не самописные схемы; готовые примеры — `concurrency` package clientv3.
- **Лимиты:** держите клиентский `MaxCallSendMsgSize` ≥ серверного `--max-request-bytes`; `MaxCallRecvMsgSize` трогайте только при явном занижении.
- **Большие выборки (3.7+):** для префиксов в сотни тысяч ключей используйте `GetStream`, чтобы не буферизовать ответ целиком (раздел «Большие выборки»).
- **gRPC keepalive:** если соединения держит посредник (LB, NAT, firewall) с таймаутом простоя, задайте `DialKeepAliveTime`/`DialKeepAliveTimeout` (например, 30 s / 10 s). Интервал ping'ов не должен быть меньше серверного `--grpc-keepalive-min-time` (5 s по умолчанию) — иначе сервер сочтёт пинги избыточными и завершит соединение; подробнее — [Лимиты и ограничения](./limits_and_constraints.md).
- **Мониторинг:** клиентские RPC-метрики (`grpc_client_started_total`, `grpc_client_handled_total`, `grpc_client_msg_received_total`, `grpc_client_msg_sent_total`) даёт `github.com/grpc-ecosystem/go-grpc-middleware/providers/prometheus` — пакет go-grpc-prometheus deprecated и архивирован, сам etcd перешёл на него в 3.7 (`client/v3/go.mod`); альтернатива — otelgrpc. Интерсепторы подключайте через `grpc.WithChainUnaryInterceptor`/`WithChainStreamInterceptor`: `WithUnaryInterceptor` в `DialOptions` перезаписывает retry-интерсептор clientv3 и молча отключает повторы. Следите за долями ошибок по кодам gRPC и latency в `grpc_client_handled_total`.

---

## Дополнительная информация

- [Watch и Lease: внутреннее устройство](./watch_lease_internals.md) — переподключение watch, компакция, продление lease.
- [Лимиты и ограничения](./limits_and_constraints.md) — серверные и клиентские лимиты размера.
- [gRPC proxy](./proxy_mode.md) — проксирование и кеширование.
- [Maintenance API](./maintenance_api.md) — REST-вызовы через gRPC gateway.
- [Безопасность](./security.md) — TLS, RBAC, CN-аутентификация.
- [Конфигурация и развёртывание](./configuration_and_deployment.md) — серверные флаги, включая `--enable-grpc-gateway`.
- [Proposal Pipeline](./proposal_pipeline.md) — путь записи и почему крупные запросы повышают latency.