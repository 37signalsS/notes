# MongoDB: Connection String, URI и конфигурация драйвера

**Актуально для:** MongoDB 8.0.x / 8.3.x, драйверы 4.x+ (pymongo 4.9+, mongodb Node.js 6.x, Java sync 5.x)

> **Совет по версии:** последний стабильный релиз MongoDB — 8.3 (май 2026); линия 8.0 активно патчится (8.0.29, август 2026). Параметры connection string описанные ниже не изменились в 8.x: `maxPoolSize`, `maxConnecting`, `waitQueueTimeoutMS`, `connectTimeoutMS`, `socketTimeoutMS`, `serverSelectionTimeoutMS`, `heartbeatFrequencyMS`, `localThresholdMS`, `retryWrites`, `retryReads`, `directConnection`, `srvServiceName`, `srvMaxHosts`, `loadBalanced`, `serverMonitoringMode`, `maxStalenessSeconds`. Новые в 8.x — `timeoutMS` (единый таймаут операции, депрекирует `socketTimeoutMS`/`waitQueueTimeoutMS`/`wTimeoutMS`/`maxTimeMS`/`maxCommitTimeMS`) и `maxAdaptiveRetries`/`enableOverloadRetargeting` (client backpressure).

---

## Определения

**Connection String (URI)** — строка подключения, описывающая топологию кластера, параметры аутентификации и поведение драйвера. Единственный способ сконфигурировать пул соединений, таймауты и retry-логику на стороне клиента.

*   **SRV Record (`mongodb+srv://`):** DNS-запись, автоматически разрешающая все узлы Replica Set (или mongos) из одного hostname. Имплицитно включает TLS. Требует `dnspython` (pymongo) >= 2.6.1.
*   **SDAM (Server Discovery and Monitoring):** механизм драйвера, отслеживающий топологию через heartbeats (`heartbeatFrequencyMS`, по умолчанию 10с). Именно SDAM обнаруживает failover и переключает записи на новый Primary.
*   **Connection Pool:** кэш TCP-соединений к `mongod`/`mongos`. Размер регулируется `maxPoolSize` (по умолчанию 100). Общая теория пулов — **[Connection Pooling](../../Concepts/Caching/caching_connection_pooling.md)**.
*   **Connection Storm:** ситуация, когда после failover или перезапуска все клиенты одновременно начинают устанавливать новые соединения, перегружая `mongod` (accept queue, CPU на TLS handshake). Классическая причина «лавины» после кратковременного сбоя.
*   **Retryable Writes:** драйвер повторяет однократно операцию записи при сетевой ошибке или смене Primary (тот же `lsid` + `txnNumber`). Включены по умолчанию в драйверах 4.0+. Не работают с `w: 0`.
*   **Retryable Reads:** драйвер повторяет чтение при сетевой ошибке. Включены по умолчанию.
*   **directConnection:** флаг, отключающий автообнаружение топологии. `true` — подключаться строго к указанному хосту (полезно для mongos или standalone), `false` (по умолчанию) — драйвер разворачивает полный список узлов Replica Set.
*   **Load Balancer Mode (`loadBalanced=true`):** режим драйвера для работы через балансировщик (например, Envoy, HAProxy, MongoDB Atlas proxy). Требует ровно один host:port в URI, `directConnection=false`, отсутствие `replicaSet` и `srvMaxHosts`. Каждый pooled connection отправляет `hello: { loadBalanced: true }`. По умолчанию `false`.
*   **Server Monitoring Mode (`serverMonitoringMode`):** как драйвер опрашивает серверы. `auto` (по умолчанию) — streaming (awaitable hello) на обычных хостах, polling на FaaS (AWS Lambda). `stream` — принудительно streaming, `poll` — принудительно polling. FaaS-окружение автоматически переключается на polling.
*   **SRV Polling:** после initial seedlist discovery драйвер периодически опрашивает SRV/TXT-записи (heartbeat-интервал) и добавляет/удаляет узлы без перезапуска приложения. `srvMaxHosts` (по умолчанию 0 = без ограничений) ограничивает сколько узлов можно добавить.
*   **timeoutMS (MongoDB 4.4+):** единый таймаут операции в мс, охватывающий server selection + connection checkout + server-side execution. Депрекирует `socketTimeoutMS`, `waitQueueTimeoutMS`, `wTimeoutMS`, `maxTimeMS`, `maxCommitTimeMS`. Без значения — поведение по отдельным таймаутам.
*   **Client Backpressure (`maxAdaptiveRetries`, `enableOverloadRetargeting`):** при перегрузке сервера драйвер сокращает retry-повторы (`maxAdaptiveRetries`, по умолчанию 2) и перенаправляет операции на менее загруженные серверы (`enableOverloadRetargeting`, по умолчанию `false`).

---

## Базовые концепции

### Синтаксис URI

```
mongodb://[username:password@]host1[:port1][,...hostN[:portN]][/[defaultauthdb][?options]]
mongodb+srv://[username:password@]host[/[defaultauthdb][?options]]
```

*   `host1,...hostN` — список узлов Replica Set или mongos. Для Replica Set указывайте 2–3 узла; драйвер автообнаружит остальные.
*   `defaultauthdb` — БД по умолчанию для аутентификации (обычно `admin`).
*   `options` — `key=value` через `&`.

### Группы параметров

| Группа | Ключевые опции | Назначение |
| :--- | :--- | :--- |
| **Топология** | `replicaSet`, `directConnection`, `srvServiceName`, `srvMaxHosts`, `srvAllowedHostsSuffix` | Обнаружение Replica Set / mongos / шардирование |
| **Load Balancer** | `loadBalanced`, `serverMonitoringMode` | Работа через балансировщик (Envoy, HAProxy, Atlas LB) |
| **Аутентификация** | `authSource`, `authMechanism`, `authMechanismProperties` | SCRAM-SHA-256, x.509, OIDC, Kerberos |
| **Пул соединений** | `maxPoolSize`, `minPoolSize`, `maxIdleTimeMS`, `maxConnecting`, `waitQueueTimeoutMS` | Sizing пула, защита от storm |
| **Таймауты** | `connectTimeoutMS`, `socketTimeoutMS`, `serverSelectionTimeoutMS`, `timeoutMS`, `heartbeatFrequencyMS`, `localThresholdMS` | Управление latency и failover |
| **Read/Write** | `w`, `wtimeout`, `j`, `readPreference`, `readPreferenceTags`, `maxStalenessSeconds` | Гарантии записи и чтения |
| **Retry** | `retryWrites`, `retryReads`, `maxAdaptiveRetries`, `enableOverloadRetargeting` | Автоповтор при сетевых сбоях и client backpressure |
| **TLS** | `tls`, `tlsCAFile`, `tlsCertificateKeyFile`, `tlsAllowInvalidCertificates`, `tlsInsecure` | Шифрование трафика |
| **Сжатие** | `compressors`, `zstdCompressionLevel`, `zlibCompressionLevel` | Сжатие wire-протокола |

### Пул соединений: как работает

```
Приложение → [maxPoolSize=100] → mongod (net.maxIncomingConnections)
                     ↑
            waitQueueTimeoutMS — сколько ждать свободного соединения
            maxConnecting=2    — сколько соединений устанавливается параллельно
```

*   `maxPoolSize` (по умолчанию **100**) — максимум соединений на один `mongod`/`mongos` в пуле. При множестве подов/инстансов приложения общее число соединений = `maxPoolSize × N_инстансов`. Это главный рычаг против исчерпания `net.maxIncomingConnections`.
*   `minPoolSize` (по умолчанию **0**) — минимум держимых соединений. Полезно для «прогрева» пула и снижения latency после простоя.
*   `maxIdleTimeMS` (по умолчанию **0** = без лимита) — время жизни простаивающего соединения. Уменьшайте при autoscaling, чтобы не держать сотни idle-соединений.
*   `maxConnecting` (по умолчанию **2**) — лимит одновременно устанавливаемых соединений. Защита от connection storm: драйвер не будет открывать 100 соединений разом.
*   `waitQueueTimeoutMS` (по умолчанию **0** = без лимита ожидания) — сколько мс запрос ждёт свободного соединения. **Рекомендуется задавать явно** (например, 2000–5000), иначе при исчерпании пула запросы встают в бесконечную очередь.

### Таймауты и failover

*   `connectTimeoutMS` (по умолчанию **30000** мс) — таймаут TCP-подключения.
*   `socketTimeoutMS` (по умолчанию **0** = без таймаута) — таймаут чтения/записи на уже установленном сокете. **Осторожно:** при `0` долгий запрос может висеть вечно. Задавайте под SLA (например, 30000).
*   `serverSelectionTimeoutMS` (по умолчанию **30000** мс) — сколько ждать подходящего сервера (например, Secondary для `readPreference=secondary`). При failover именно этот таймаут определяет, как быстро приложение получит ошибку вместо зависания.
*   `heartbeatFrequencyMS` (по умолчанию **10000** мс) — частота SDAM-проверок. Уменьшать не рекомендуется (нагрузка на кластер).
*   `localThresholdMS` (по умолчанию **15** мс) — окно latency для `readPreference=nearest`.

### Retry-логика

*   `retryWrites=true` (по умолчанию) — драйвер повторит запись **один раз** при сетевой ошибке или `NotPrimary`/`PrimarySteppedDown`. Гарантирует идемпотентность через `lsid`+`txnNumber`. **Не применяется** к `w:0` и к некоторым операциям (например, `db.collection.insert()` без write concern).
*   `retryReads=true` (по умолчанию) — повтор чтения при сетевой ошибке.
*   Retryable Writes **не покрывают** логические ошибки (дубликат ключа, валидация) — только транспортные сбои.
*   **`timeoutMS` (MongoDB 4.4+, SRE-рекомендация):** единый таймаут операции. Заменяет `socketTimeoutMS`, `waitQueueTimeoutMS`, `wTimeoutMS`, `maxTimeMS`, `maxCommitTimeMS`. Если задан — драйвер игнорирует перечисленные. Позволяет задать один SLA-таймаут для всей операции (server selection + pool checkout + выполнение). Поддержка по драйверам — проверять в документации конкретного драйвера.

### Load Balancer Mode и SRV-подробности

*   **`loadBalanced=true`** — режим работы через балансировщик (Envoy, HAProxy, MongoDB Atlas load balancer). URI: ровно один `host:port`, `directConnection=false`, нет `replicaSet`, нет `srvMaxHosts`. Драйвер отправляет `hello: { loadBalanced: true }` и не отслеживает топологию самостоятельно — балансировщик отвечает за discoverability.
*   **`srvServiceName`** (по умолчанию `mongodb`) — кастомное имя SRV-service при multicell-кластерах. Используйте при конфликте с другими SRV-записями на том же домене.
*   **`srvMaxHosts`** (по умолчанию 0 = без ограничений) — максимум узлов, добавляемых к seed list из SRV-records. Полезно при шардировании, где нужно ограничить число узлов для подключения. Не совместимо с `replicaSet`, `loadBalanced=true`, или `directConnection=true`.
*   **`srvAllowedHostsSuffix`** — ограничить, какие хосты разрешены из SRV (безопасность против DNS-спуфинга).
*   **TXT-запись:** сопровождает SRV-запись, задаёт опции по умолчанию (например, `authSource=admin`, `replicaSet=rs0`). Драйвер merge-ит TXT с query-string опциями, query-string имеет приоритет.
*   **SRV polling:** драйвер обновляет seed list без переподключения, если администратор добавил/удалил узел в DNS.

---

## Подготовка окружения (Prerequisites)

1.  **Драйвер:** используйте версию, совместимую с MongoDB 8.x (pymongo 4.9+, Node.js 6.x, Java sync 5.x). См. **[Совместимость версий и драйверов](./mongodb-administration.md#18-совместимость-версий-и-драйверов)**.
2.  **SRV-записи:** для `mongodb+srv://` настройте DNS `_mongodb._tcp.<domain>` SRV-записи и сопровождающую TXT-запись (опции по умолчанию, например `authSource=admin`). Установите `dnspython` >= 2.6.1 для pymongo.
3.  **DNS-проверка:** `dig +short SRV _mongodb._tcp.<domain>` и `dig +short TXT <domain>` — должны возвращать ожидаемые записи перед production-развёртыванием.
4.  **TLS:** для `mongodb+srv://` TLS включён по умолчанию. Для `mongodb://` укажите `tls=true` и `tlsCAFile`.
5.  **Лимиты:** рассчитайте суммарный пул: `maxPoolSize × количество подов/инстансов` должен быть < `net.maxIncomingConnections` (см. **[Администрирование](./mongodb-administration.md)**).
6.  **FaaS (AWS Lambda и аналоги):** если приложение запускается в FaaS, установите `serverMonitoringMode=poll` — streaming-протокол не работает в stateless-окружении (одно соединение на invoke).
7.  **Load Balancer:** если MongoDB стоит за балансировщиком, используйте `loadBalanced=true` с одним `host:port` в URI. Не комбинируйте с `replicaSet`, `directConnection=true`, `srvMaxHosts`.

---

## Практические сценарии

### 1. Подключение к Replica Set с пулом и таймаутами

```python
# Python (pymongo)
from pymongo import MongoClient

client = MongoClient(
    "mongodb://mongo-1:27017,mongo-2:27017,mongo-3:27017/?replicaSet=rs0"
    "&authSource=admin&authMechanism=SCRAM-SHA-256"
    "&retryWrites=true&retryReads=true"
    "&maxPoolSize=50&minPoolSize=5&maxIdleTimeMS=300000"
    "&waitQueueTimeoutMS=5000&maxConnecting=2"
    "&connectTimeoutMS=10000&socketTimeoutMS=30000&serverSelectionTimeoutMS=15000"
    "&w=majority&wtimeout=5000"
    "&readPreference=primaryPreferred"
)
```

**Валидация:**
```javascript
// Проверить текущий пул и топологию
db.serverStatus().connections
// → { current, available, totalCreated, active }

// В mongosh: какая readPreference применена
db.getMongo().getReadPrefMode()
```

### 2. SRV-подключение (автообнаружение)

```javascript
// Node.js
const { MongoClient } = require("mongodb");
const uri = "mongodb+srv://app_user:password@cluster.example.com/production?authSource=admin&retryWrites=true&w=majority";
const client = new MongoClient(uri, {
  maxPoolSize: 100,
  waitQueueTimeoutMS: 3000,
  serverSelectionTimeoutMS: 10000,
});
```

**Валидация SRV:**
```bash
# Проверить SRV-запись
dig +short SRV _mongodb._tcp.cluster.example.com
# → 0 0 27017 mongo-1.cluster.example.com. ...

# Проверить, что драйвер видит все узлы
mongosh "mongodb+srv://cluster.example.com" --eval "db.hello().hosts"
```

### 3. directConnection для mongos и standalone

```python
# Подключение строго к одному mongos (без автообнаружения)
client = MongoClient(
    "mongodb://mongos-1:27017/?directConnection=true&authSource=admin"
)
```

> **Когда `directConnection=true`:** подключение к одному mongos, к standalone, или когда DNS/балансировщик скрывает топологию. **Когда `false` (по умолчанию):** Replica Set — драйвер должен развернуть полный список узлов для failover.

### 4. Защита от connection storm

```python
# Рекомендуемый набор для production:
client = MongoClient(
    uri,
    maxPoolSize=50,          # ограничить пул на инстанс
    minPoolSize=5,           # держать 5 «тёплых» соединений
    maxConnecting=2,         # не более 2 одновременных подключений
    waitQueueTimeoutMS=3000, # не ждать соединение дольше 3с
    retryWrites=True,        # автоповтор при failover
    serverSelectionTimeoutMS=10000,
)
```

**Диагностика storm:**
```javascript
// На mongod: резкий рост totalCreated и current
db.serverStatus().connections
// → { current: 9800, available: 200, totalCreated: 500000 }

// Признак storm: totalCreated растёт лавинообразно, current ≈ maxIncomingConnections
```

### 5. TLS в URI

```python
client = MongoClient(
    "mongodb://mongo-1:27017/?tls=true"
    "&tlsCAFile=/etc/ssl/ca.pem"
    "&tlsCertificateKeyFile=/etc/ssl/client.pem"
    "&tlsCertificateKeyFilePassword=secret"
    "&authMechanism=MONGODB-X509&authSource=$external"
)
```

> **Не используйте** `tlsAllowInvalidCertificates=true` в production — отключает проверку сертификата. Для тестов только.

### 6. Load Balancer Mode (Envoy / HAProxy / Atlas LB)

```python
# Подключение через балансировщик: один host:port, loadBalanced=true
client = MongoClient(
    "mongodb://lb.example.com:27017/?loadBalanced=true"
    "&authSource=admin&retryWrites=true"
    "&maxPoolSize=50&waitQueueTimeoutMS=3000"
)
```

**Валидация:**
```javascript
// mongosh должен увидеть loadBalanced=true в handshake
db.getMongo().hello()
// → { loadBalanced: true, ... }
```

> **Когда использовать:** балансировщик скрывает топологию Replica Set/mongos (например, TCP LB, Docker swarm, Atlas LB). Не используйте `loadBalanced=true` без балансировщика — драйвер не будет отслеживать failover.

### 7. timeoutMS — единый таймаут операции (SRE-рекомендация)

```python
# Единый SLA-таймаут: server selection + pool checkout + выполнение
client = MongoClient(
    "mongodb://mongo-1:27017/?retryWrites=true"
    "&timeoutMS=5000"          # 5с на всю операцию
    "&serverSelectionTimeoutMS=15000"
)
```

*   `timeoutMS` покрывает **всё**: server selection, ожидание соединения из пула, выполнение на сервере.
*   При `timeoutMS=5000` и загруженном пуле запрос упадёт через 5с — без бесконечного ожидания.
*   Если `timeoutMS` задан — `socketTimeoutMS`, `waitQueueTimeoutMS`, `wTimeoutMS`, `maxTimeMS`, `maxCommitTimeMS` **игнорируются**.
*   Поддержка по драйверам: проверьте в документации (pymongo 4.x, Node.js 6.x, Java 5.x — поддерживают).

### 8. maxStalenessSeconds и readPreferenceTags

```python
# Читать с Secondary, но не старше 120с; только из dc:eu
client = MongoClient(
    "mongodb://mongo-1:27017,mongo-2:27017,mongo-3:27017/?replicaSet=rs0"
    "&readPreference=secondary"
    "&maxStalenessSeconds=120"
    "&readPreferenceTags=dc:eu"
)
```

*   `maxStalenessSeconds` минимум 90с; `0`–89с вызывают ошибку. `-1` (по умолчанию) — без лимита.
*   При `readPreference=primary` и `maxStalenessSeconds` задан — URI считается некорректным.
*   `readPreferenceTags` — comma-separated `key:value` пары; драйвер сначала ищет узлы с тегами, потом без тегов (если `hedge` не задан).
*   Валидация: `db.getMongo().getReadPrefMode()` и `db.hello().lastWrite` для оценки лага Secondary.

### 9. FaaS (AWS Lambda): serverMonitoringMode=poll

```python
# Streaming-протокол не работает в stateless-окружении — принудительно polling
client = MongoClient(
    "mongodb+srv://cluster.example.com/?serverMonitoringMode=poll"
    "&maxPoolSize=1"
)
```

*   В `auto` драйвер сам переключается на `poll` в FaaS (по правилам handshake metadata).
*   `maxPoolSize=1` — одно соединение на invoke (stateless).
*   `serverSelectionTimeoutMS` должен быть больше, чем время жизни invoke.

---

## Операции и команды (Reference)

| Опция | По умолчанию | SRE-рекомендация |
| :--- | :--- | :--- |
| `maxPoolSize` | 100 | Рассчитать: `maxPoolSize × N_подов < net.maxIncomingConnections` |
| `minPoolSize` | 0 | 5–10 для «прогрева» пула |
| `maxIdleTimeMS` | 0 (∞) | 300000 (5м) при autoscaling |
| `maxConnecting` | 2 | Не увеличивать без необходимости |
| `waitQueueTimeoutMS` | 0 (∞) | **Задавать явно** 2000–5000 (или `timeoutMS`) |
| `connectTimeoutMS` | 30000 | 10000 для fast-fail |
| `socketTimeoutMS` | 0 (∞) | 30000–60000 под SLA (или `timeoutMS`) |
| `serverSelectionTimeoutMS` | 30000 | 10000–15000 |
| `timeoutMS` | unset | Единый таймаут операции; предпочтительнее `socketTimeoutMS`/`waitQueueTimeoutMS` (MongoDB 4.4+) |
| `heartbeatFrequencyMS` | 10000 | Не менять |
| `localThresholdMS` | 15 | Не менять |
| `retryWrites` | true | Оставить true |
| `retryReads` | true | Оставить true |
| `directConnection` | false | true для mongos/standalone |
| `srvMaxHosts` | 0 (∞) | Ограничить при шардировании (например, 6) |
| `srvServiceName` | `mongodb` | Менять только при multicell-конфликте |
| `srvAllowedHostsSuffix` | unset | Добавить для защиты от DNS-спуфинга |
| `loadBalanced` | false | true только за балансировщиком |
| `serverMonitoringMode` | `auto` | `poll` в FaaS (AWS Lambda) |
| `maxStalenessSeconds` | -1 (без лимита) | Минимум 90; задать при `readPreference=secondary/nearest` |
| `compressors` | — | `zstd` для снижения трафика |
| `maxAdaptiveRetries` | 2 | Оставить; снижает retry при перегрузке |
| `enableOverloadRetargeting` | false | true при высокой нагрузке (client backpressure) |

---

## Устранение неполадок

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`MongoServerSelectionError`** | Нет доступного Primary/Secondary в `serverSelectionTimeoutMS` | Логи приложения, `db.hello()` | Проверить replicaSet, сеть, `readPreference` |
| **Connection storm после failover** | Все клиенты переподключаются одновременно | `db.serverStatus().connections.totalCreated` резко растёт | Уменьшить `maxPoolSize`, включить `maxConnecting=2`, `retryWrites` |
| **`MongoTimeoutError` (pool)** | Пул исчерпан, `waitQueueTimeoutMS` истёк | Метрики пула драйвера, `connections.current` ≈ `maxIncomingConnections` | Увеличить `maxPoolSize` или уменьшить число инстансов; проверить долгие операции; задать `timeoutMS` |
| **Зависшие запросы** | `socketTimeoutMS=0` (∞) | `db.currentOp({secs_running:{$gt:30}})` | Задать `socketTimeoutMS` под SLA или `timeoutMS` |
| **`NotPrimary` на записи** | Failover, драйвер ещё не переключился | `db.hello()`, логи | `retryWrites=true` покрывает; иначе retry в приложении |
| **SRV не резолвится** | Нет `dnspython` или DNS SRV | `dig SRV _mongodb._tcp.<domain>` | Установить `dnspython` >= 2.6.1 |
| **TLS handshake failure** | Неверный CA, дрейф NTP, истёк сертификат | `openssl s_client -connect host:27017` | Обновить сертификаты, синхронизировать NTP |
| **`srvMaxHosts` игнорируется** | Указан `replicaSet` или `loadBalanced=true` | URI-валидация драйвера | Убрать конфликтующую опцию; `srvMaxHosts` совместим только с `directConnection=false` и без RS/LB |
| **FaaS: constant reconnects** | Streaming-протокол не работает в stateless-окружении | Логи драйвера, частые reconnect | Установить `serverMonitoringMode=poll` |
| **Балансировщик: `NotPrimary`** | `loadBalanced=false` за LB, драйвер пытается управлять топологией | `db.hello()` — нет `loadBalanced: true` | Включить `loadBalanced=true`, один host:port, убрать `replicaSet`/`directConnection` |
| **`timeoutMS` не влияет на операцию** | Драйвер не поддерживает `timeoutMS` | Документация драйвера | Использовать `socketTimeoutMS`/`waitQueueTimeoutMS` в качестве альтернативы |

---

## Лучшие практики (SRE)

1.  **Считайте суммарный пул:** `maxPoolSize × N_инстансов` должен оставлять запас под `net.maxIncomingConnections` (обычно 65536). При 50 подах и `maxPoolSize=100` → 5000 соединений.
2.  **Всегда задавайте `waitQueueTimeoutMS` или `timeoutMS`:** без него исчерпание пула превращается в бесконечную очередь и каскадный таймаут.
3.  **`retryWrites=true`:** оставьте по умолчанию — покрывает большинство кратковременных сбоев и failover.
4.  **`socketTimeoutMS`/`timeoutMS` под SLA:** `0` (∞) опасен — долгий запрос блокирует соединение из пула.
5.  **SRV для Replica Set:** `mongodb+srv://` упрощает топологию и автоматически включает TLS.
6.  **`directConnection` осознанно:** для Replica Set оставляйте `false`, иначе драйвер не переключится на новый Primary при failover.
7.  **Сжатие трафика:** `compressors=zstd` снижает network I/O на 60–80% для больших документов (ценой CPU).
8.  **Мониторьте `connections`:** алерт на `connections.current / maxIncomingConnections > 0.8`.
9.  **`srvMaxHosts` при шардировании:** ограничить число узлов для подключения (например, 6), чтобы драйвер не пытался соединяться со всеми шардами напрямую.
10. **FaaS → `serverMonitoringMode=poll`:** streaming-протокол не работает в stateless-окружении.
11. **`timeoutMS` вместо набора таймаутов:** один SLA-таймаут проще поддерживать и покрывает pool checkout + execution.
12. **Load Balancer → `loadBalanced=true`:** только с одним host:port, без `replicaSet`, без `directConnection=true`, без `srvMaxHosts`.
13. **`maxStalenessSeconds` при `secondary`/`nearest`:** минимум 90с; без него драйвер может читать с устаревшего Secondary без предупреждения.
14. **`srvAllowedHostsSuffix` для защиты:** предотвращает DNS-спуфинг при публичном SRV-хостинге.

---

## Дополнительная информация

*   **[Обзор MongoDB](./mongodb.md)** — архитектура и write path.
*   **[Репликация](./mongodb-replication.md)** — Write Concern, Read Preference, failover.
*   **[Администрирование](./mongodb-administration.md)** — `net.maxIncomingConnections`, лимиты, совместимость драйверов.
*   **[Capacity Planning](./mongodb-capacity-planning.md)** — sizing пула соединений, `maxIncomingConnections`, RAM.
*   **[Connection Pooling (общая теория)](../../../Concepts/Caching/caching_connection_pooling.md)** — принципы пулов соединений.
*   **[Benchmarking (общая теория)](../../../Databases/Concepts/benchmarking.md)** — sizing пула и capacity planning.
*   [MongoDB Connection String URI](https://www.mongodb.com/docs/manual/reference/connection-string/)
*   [MongoDB Connection String Options](https://www.mongodb.com/docs/manual/reference/connection-string-options/)
*   [MongoDB Driver Connection Pool](https://www.mongodb.com/docs/manual/administration/analyzing-mongodb-performance/#connection-pool)
*   [Client Side Operations Timeout (`timeoutMS`)](https://www.mongodb.com/docs/manual/reference/client-side-operations-timeout/)
*   [Load Balancer Mode](https://www.mongodb.com/docs/manual/core/load-balancers/)
