# Сравнение Stateful и Stateless архитектур

## Определения

**Stateful (с состоянием)** — архитектурный подход, при котором приложение или сервис сохраняет контекст взаимодействия (состояние, сессии, транзакционные данные) между последовательными запросами. Система «помнит» историю взаимодействий, и результат текущего запроса может зависеть от предыдущих.
*   **Где хранится состояние:** оперативная память (RAM), локальная файловая система, специализированные кэши или базы данных с привязкой к узлу.

**Stateless (без состояния)** — подход, при котором сервис не хранит никакой информации о предыдущих взаимодействиях. Каждый запрос обрабатывается как независимая транзакция, содержащая абсолютно весь необходимый контекст для выполнения операции (например, токен авторизации и ID объекта). Сервер является «чистой функцией» от входных данных.

## Предварительные требования

Для глубокого понимания темы рекомендуется ознакомиться с:
*   **[Протоколом HTTP](../Networking/Protocols/HTTP/http_basics.md)** (классический пример stateless-протокола).
*   **Основами контейнеризации и Docker** (эфемерность файловых систем).
*   **Базовыми сетевыми концепциями** (TCP-сессии, балансировка нагрузки).

## Базовые концепции

### Проблема сессий и способы ее решения
В кластерной среде классический подход Stateful (хранение сессии в памяти сервера) приводит к проблемам: если балансировщик направит второй запрос пользователя на другой сервер, сессия будет потеряна.

**Методы решения:**

1.  **Stateless + Внешнее хранилище (External State):**
    *   **Принцип:** Серверы приложений остаются stateless. Данные сессий выносятся в быстрое распределенное хранилище (Redis, Memcached).
    *   **Плюс:** Полная взаимозаменяемость узлов.
    *   **Минус:** Дополнительная сетевая задержка (RTT) при каждом запросе к Redis.

2.  **Client-Side State (JWT/Cookies):**
    *   **Принцип:** Состояние хранится на стороне клиента (браузера) в зашифрованном виде. Сервер только проверяет подпись.
    *   **Подробнее:** **[JWT (JSON Web Token)](../Security/Concepts/jwt_overview.md)**.

3.  **Sticky Sessions (Липкие сессии):**
    *   **Принцип:** Балансировщик на основе Cookie или IP-адреса «привязывает» клиента к конкретному бэкенду.
    *   **Минус:** При выходе сервера из строя сессия теряется. Сложность с равномерным распределением нагрузки (Hotspots).

### Ключевые различия

| Критерий | Stateless | Stateful |
| :--- | :--- | :--- |
| **Хранение данных** | Во внешних системах (БД, кэш) | Локально (RAM, диск) или репликация |
| **Масштабирование** | Горизонтальное (мгновенно, Auto-scaling) | Сложное (требует координации, шардирования) |
| **Отказоустойчивость** | Высокая (узлы эфемерны) | Требует механизмов Failover, WAL и репликации |
| **Идентификация узлов** | Случайные имена/IP (Web-1, Web-2) | Стабильные ID и DNS-имена (DB-0, DB-1) |
| **Задержки (Latency)** | Выше (из-за сетевого доступа к БД) | Ниже (данные в локальной памяти/диске) |

### Модели согласованности данных

Выбор модели согласованности определяет компромисс между **производительностью**, **доступностью** и **корректностью** данных. Stateless-сервисы перекладывают эту проблему на внешние хранилища, но понимание моделей критично для проектирования stateful-систем.

| Модель | Гарантия | Пример использования | Цена |
| :--- | :--- | :--- | :--- |
| **Strong Consistency** | Любой читатель видит последнюю запись | Банковские транзакции, блокировки строк | Высокая латентность (кворум) |
| **Eventual Consistency** | Данные синхронизируются «в конце концов» | Кэш, CDN, DNS | Низкая латентность, временная несогласованность |
| **Causal Consistency** | Сохраняется因果 порядок операций | Чат-приложения,/wiki, Ordering | Средняя латентность |
| **Read-your-writes** | Читатель видит свои собственные записи | Социальные сети (пост → видит себя), корзина | Кэш привязки к записи |
| **Monotonic Reads** | Чтение не может вернуться к старым данным | Финансовые графики, audit log | Средняя латентность |
| **Consistent Prefix** | Чтение не покажет данных в неправильном порядке | Репликация логов, ordered event streams | Буферизация |

**Практические рекомендации:**
*   **Stateless API + Redis/Memcached:** Eventual Consistency (допустимо для сессий, кэша, rate limiting).
*   **Stateful БД (PostgreSQL, MySQL):** Strong Consistency по умолчанию (ACID). Реплики могут работать в режиме eventual (async replication).
*   **Distributed KV (etcd, Consul):** Strong Consistency через Raft-консенсус. Используется для service discovery, leader election, конфигураций.
*   **Распределенные очереди (Kafka):** Partition-level ordering (consistent within partition, eventual across partitions).

Подробнее: **[CAP Theorem и выбор БД](./Storage/data_storage_overview.md)**.

### Принципы Stateless-архитектуры

Методология **12-Factor App** (фактор VI) является фундаментом для облачных приложений:
*   **Взаимозаменяемость:** любой экземпляр может обработать любой запрос.
*   **Идемпотентность:** повторный запрос при сбое не должен дублировать действия (например, двойное списание средств). Подробнее: **[Идемпотентность](./idempotency.md)**.
*   **Быстрый старт и завершение:** процессы должны запускаться и завершаться мгновенно, не заботясь о сохранении локальных данных.

### Принципы Stateful-архитектуры

Необходима для систем, где данные являются критическим ресурсом или требуется минимальная задержка обработки.
*   **Алгоритмы консенсуса:** Использование протоколов **Raft** или **Paxos** для обеспечения консистентности данных в кластере (см. **[Архитектура etcd](../etcd/architecture-and-concepts.md)**).
*   **Write-Ahead Log (WAL):** Все изменения сначала записываются в журнал (Append-only), а затем применяются к состоянию. Это гарантирует восстановление после краха.
*   **Data Locality:** Приближение кода к данным (например, в Big Data системах или In-memory DB).

## Практические сценарии

### Kubernetes: Deployment vs StatefulSet

Kubernetes предоставляет разные контроллеры для управления типами нагрузок:

**Stateless (Deployment):**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: nginx
        image: nginx:latest
# Поды web-app-xxxxx получают случайные имена и не привязаны к конкретным дискам.
```

**Stateful (StatefulSet):**
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: database
spec:
  serviceName: "db-internal"
  replicas: 3
  template:
    spec:
      containers:
      - name: postgres
        image: postgres:15
  volumeClaimTemplates: # Диск следует за подом при перезапуске на другой узел
  - metadata:
      name: data
    spec:
      accessModes: [ "ReadWriteOnce" ]
      resources:
        requests:
          storage: 10Gi
```
*Подробное сравнение:* **[StatefulSet vs Deployment](../Kubernetes/Base/StatefulSet/statefulset_vs_deployment.md)**.

### Балансировка нагрузки и Nginx

Для приложений, которые не могут быть полностью stateless, Nginx предлагает механизмы сохранения сессий:

**Пример `ip_hash` (простая привязка по IP):**
```nginx
upstream backend {
    ip_hash;
    server backend1.example.com;
    server backend2.example.com;
}
```

**Пример `sticky cookie` (требует Nginx Plus или модули):**
```nginx
upstream backend {
    server backend1.example.com;
    server backend2.example.com;
    sticky cookie srv_id expires=1h domain=.example.com path=/;
}
```

### Внешнее хранилище сессий (Flask + Redis)

Пример на Python, реализующий перенос состояния из памяти приложения во внешнее хранилище:

```python
from flask import Flask, session
from flask_session import Session
import redis

app = Flask(__name__)
app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_REDIS'] = redis.from_url('redis://redis-server:6379')

Session(app)

@app.route('/')
def index():
    # Состояние сессии хранится в Redis, а не в памяти процесса Python
    session['counter'] = session.get('counter', 0) + 1
    return f"Вы посетили страницу {session['counter']} раз"
```

### Управление инфраструктурой (IaC)

*   **Ansible (Stateless):** Инструмент "толкающего" типа (push-based). При каждом запуске он собирает факты об узлах заново. Если ресурс был удален вручную, Ansible просто создаст его снова, если это описано в плейбуке.
*   **Terraform (Stateful):** Хранит состояние инфраструктуры в файле `terraform.tfstate`. Это позволяет Terraform понимать, какие ресурсы он создал ранее, и корректно удалять их, если они исчезли из кода. Подробнее: **[Обзор IaC](./iac_overview.md)**.

### Stateless-контейнеры с локальным состоянием (eni Temporary State)

Даже в Stateless-архитектуре контейнеры могут нуждаться во временном хранилище:
*   **EmptyDir:** Эфемерный том, который удаляется при остановке пода. Используется для кэша, временных файлов, IPC.
*   **hostPath:** Монтирует директорию хоста в контейнер. Опасно в multi-tenant средах (безопасность, изоляция).
*   **local PV:** Привязан к конкретному узлу, но управляется Kubernetes. Подходит для stateful workload, требующих locality (кэш, буфер).

**Правило:** Stateless-приложения могут использовать EmptyDir для временного кэша, но **никогда** для данных, которые должны пережить рестарт контейнера.

## Стратегии миграции состояния

### Expand-Contract (Parallell Change)
Расширение схемы, миграция данных, сжатие схемы — три этапа без даунтайма:

```
Phase 1 (Expand):   ALTER TABLE users ADD COLUMN email_v2 VARCHAR(255);
Phase 2 (Migrate):  UPDATE users SET email_v2 = email;
Phase 3 (Contract): ALTER TABLE DROP COLUMN email; ALTER TABLE RENAME COLUMN email_v2 TO email;
```

Подробнее: **[Expand-Contract](../Databases/Concepts/migrations/expand_contract.md)**.

### CDC (Change Data Capture) для синхронизации
Когда два сервиса хранят копии одних данных, CDC обеспечивает синхронизацию:

```
PostgreSQL (Primary) → Debezium → Kafka → Consumer (микросервис)
```

*   **Debezium** отслеживает WAL (Write-Ahead Log) PostgreSQL и публикует события `INSERT/UPDATE/DELETE`.
*   **Потребитель** применяет изменения к своей модели данных (денормализация, read model).
*   **Преимущество:** Реалтайм-синхронизация, нет нагрузки на БД через polling.

Подробнее: **[CDC в Event-Driven архитектуре](./event-driven-architecture.md)**.

### Dual Write и проверка
Параллельная запись в две системы (legacy + новая) с проверкой консистентности:

1. Запись в обе системы одновременно.
2. Периодическое сравнение данных (CRC32 checksum, hash comparison).
3. При обнаружении расхождений — автоматическое исправление или алерт.
4. После стабилизации — отключение записи в legacy.

**Риск:** Race conditions между записями. Решение:ackbar-based approach с транзакционным outbox.

### Blue-Green миграция базы данных
1. Настройка реплики (Green) с синхронизацией из Primary (Blue).
2. Ожидание sync lag < порога (обычно < 1 сек).
3. Переключение приложений на Green (connection string update).
4. Проверка данных и performance.
5. Удаление Blue после стабилизации.

## Паттерны распределенного состояния

### Event Sourcing
Вместо хранения текущего состояния — хранение последовательности событий, которые привели к этому состоянию.

```
Event Store:
  [UserCreated{id:1, name:"Ivan"}, EmailChanged{id:1, email:"ivan@test.com"}, BalanceCredited{id:1, amount:100}]

Текущее состояние = replay всех событий:
  User{id:1, name:"Ivan", email:"ivan@test.com", balance:100}
```

**Плюсы:** Полная история изменений, возможность восстановить состояние на любой момент, аудит.
**Минусы:** Сложность запросов (нужны проекции), размер хранилища, latency при replay.
**Использование:** Финансовые системы, ERP, гейминг, IoT.

Подробнее: **[Event Sourcing в EDA](./event-driven-architecture.md)**.

### CQRS (Command Query Responsibility Segregation)
Разделение модели записи (Command) и модели чтения (Query):

```
Write Model (Normalization):     Read Model (Denormalization):
┌─────────────────┐              ┌──────────────────────┐
│ users (id,name) │──events──→  │ user_orders_view     │
│ orders (id,uid) │              │ (id, name, order_id) │
│ items (id,oid)  │              │ denormalized for fast │
└─────────────────┘              │ reads                │
                                 └──────────────────────┘
```

**Когда использовать:** Высокая нагрузка на чтение, сложные запросы, необходимость denormalized view.
**Минусы:** Сложность, eventual consistency между write/read моделями.

### Saga Pattern (оркестрация vs хореография)
Управление распределенными транзакциями без 2PC:

| Подход | Описание | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Orchestration** | Центральный оркестратор управляет шагами | Ясная логика, easy debugging | Single point of failure, сложность |
| **Choreography** | Каждый сервис реагирует на события предыдущего | Decoupling, простота | Сложно отслеживать, циклические зависимости |

**Пример (Orchestration):**
1. Order Service → `OrderCreated` → Payment Service
2. Payment Service → `PaymentProcessed` → Inventory Service
3. Inventory Service → `StockReserved` → Shipping Service
4. При ошибке на любом шаге → компенсирующие транзакции (reverse steps).

Подробнее: **[Saga в Distributed Transactions](../Databases/Concepts/distributed_transactions.md)**.

## Операционные паттерны для Stateful сервисов

### Health Checks для Stateful
Stateful сервисы требуют более глубоких проверок, чем HTTP 200:

| Проверка | Что проверяет | Пример |
| :--- | :--- | :--- |
| **Liveness** | Процесс жив, БД доступна | `pg_isready -h localhost -p 5432` |
| **Readiness** | Готов принимать трафик, репликация в норме | `psql -c "SELECT pg_is_in_recovery()"` |
| **Startup** | Длительная инициализация (WAL replay) | `kubectl exec -- pg_isready` с задержкой |
| **Replication Lag** | Отставание реплики | `pg_last_wal_replay_lsn() - pg_last_wal_receive_lsn()` |

**Пример для PostgreSQL в K8s:**
```yaml
livenessProbe:
  exec:
    command: ["pg_isready", "-U", "postgres"]
  initialDelaySeconds: 30
  periodSeconds: 10
readinessProbe:
  exec:
    command:
    - /bin/sh
    - -c
    - |
      pg_isready -U postgres && \
      test $(psql -U postgres -t -c "SELECT pg_is_in_recovery()::text") = "f"
  initialDelaySeconds: 5
  periodSeconds: 5
startupProbe:
  exec:
    command: ["pg_isready", "-U", "postgres"]
  failureThreshold: 30
  periodSeconds: 10
```

### Backup и Recovery для Stateful
*   **Logical Backup:** `pg_dump` / `mysqldump` — полный дамп, медленное восстановление, версионирование.
*   **Physical Backup:** `pg_basebackup` + WAL archiving — инкрементальные, быстрое восстановление.
*   **Снапшоты дисков:** Снимок PV через CSI driver или storage backend (minio, Ceph).
*   **Регулярное тестирование:** Восстановление из бэкапа — это часть SRE-процесса. Тестировать раз в квартал.

### Runbook для типичных операций
*   **Добавление реплики:** `pg_basebackup` → настройка `recovery.conf` → START REPLICA.
*   **Promotion реплики:** `pg_ctl promote` → обновление DNS/service → проверка данных.
*   **Rolling restart:** Остановка пода → ожидание drain → запуск нового → проверка health.
*   **Data compaction:** Для LSM-деревьев (RocksDB, LevelDB) — регулярная компакция для предотвращения read amplification.

## Репликация и разрешение конфликтов

### Модели репликации

| Модель | Описание | Consistency | Availability |
| :--- | :--- | :--- | :--- |
| **Synchronous** | Лидер ждет подтверждения от реплик | Strong | Низкая (задержка на кворум) |
| **Asynchronous** | Лидер не ждет подтверждения | Eventual | Высокая |
| **Semi-synchronous** | Лидер ждет хотя бы одну реплику | Between | Средняя |

### Multi-Primary (Active-Active)
Два или более узла принимают записи одновременно. Проблема: **конфликты** при параллельной записи в одну строку.

**Стратегии разрешения конфликтов:**

| Стратегия | Описание | Пример |
| :--- | :--- | :--- |
| **Last-Write-Wins (LWW)** | Побеждает запись с более поздним timestamp | Cassandra (по умолчанию), CockroachDB |
| **Application-level** | Приложение разрешает конфликт бизнес-логикой | Merge.shoping.cart.items() |
| **CRDT** | Conflict-free Replicated Data Type — математически гарантирует слияние | Redis CRDT (active-active), Riak |
| **Vector Clocks** | Отслеживание causal ordering для определения конфликтов | DynamoDB, Riak |

**CRDT (Conflict-free Replicated Data Types):**
*   **G-Counter:** Глобальный счётчик. Каждый узел имеет свой slot. Сумма — агрегация всех slot'ов.
*   **PN-Counter:** Positive-Negative счётчик (для инкремента и декремента).
*   **LWW-Register:** Last-Write-Wins register для строк.
*   **OR-Set:** Observed-Remove Set (множество с добавлением/удалением без конфликтов).

**Использование в DevOps:** Распределённые лимиты (rate limiting), счётчики метрик в multi-datacenter, синхронизация конфигураций.

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Разлогин пользователей при деплое** | Сессии хранятся локально, поды в K8s эфемерны. | Использовать Redis для сессий или Sticky Sessions с плавным дренажем трафика. |
| **Переполнение таблицы conntrack** | Stateful Firewall отслеживает слишком много соединений. | Увеличить `net.netfilter.nf_conntrack_max` или оптимизировать таймауты. |
| **Data Drift в StatefulSet** | Рассинхронизация данных между репликами БД (Split-brain). | Использовать алгоритмы консенсуса (Raft/Paxos) и проверять статус кворума. |
| **Задержки (Tail Latency)** | Перегрузка внешнего хранилища сессий (Redis). | Шардирование Redis или использование Client-side сессий (JWT). |
| **Split-brain при multi-primary** | Сетевой partition: два узла считают себя leader. | Настройка fencing (STONITH), кворума, или LWW-стратегии разрешения конфликтов. |
| **Replication Lag растёт** | Перегрузка primary или медленная сеть. | Проверить `pg_stat_replication`, увеличить bandwidth, использовать sync replication для критичных данных. |
| **StatefulSet не запускается** | PersistentVolume не найден или Bound. | `kubectl get pv,pvc` — проверить status. Для local PV: узел должен быть в `Ready` trạng thái. |
| **WAL накапливается (PostgreSQL)** | Архивация не работает или wal_keep_size слишком высокий. | Проверить `archive_command`, увеличить `wal_keep_size` или настроить replication slot с feedback. |
| **Redis OOM при high write load** | maxmemory-policy отбирает ключи. | Увеличить `maxmemory`, выбрать политику `allkeys-lru` вместо `volatile-lru`. |

## Лучшие практики

1.  **Стремитесь к Stateless:** Делайте бизнес-логику stateless по умолчанию. Это упрощает масштабирование и CI/CD.
2.  **Изолируйте State:** Выносите состояние в специализированные слои (PostgreSQL, Redis, MinIO).
3.  **Не храните состояние в контейнерах:** Любые данные, записанные на локальный диск контейнера, будут потеряны при его перезапуске (если не используется Persistent Volume).
4.  **Graceful Shutdown:** Stateless-сервисы должны корректно завершать текущие запросы перед выходом, чтобы балансировщик успел переключить трафик.
5.  **Мониторинг Lag:** Для Stateful-систем критически важно отслеживать задержку репликации (Replication Lag). Алерт при lag > порога.
6.  **Backup = Runnable:** Бэкап бесполезен, если не проверено восстановление. Тестировать restore раз в квартал.
7.  **Consistency by Design:** Выбирайте модель согласованности осознанно. Не используйте eventual consistency там, где нужна strong (финансовые транзакции).
8. **CRDT для multi-datacenter:** При.getActive-active распределении используйте CRDT для данных, где конфликты неизбежны (счётчики, множества, лимиты).

## Современные тренды (2025–2026)

*   **Dapr (Distributed Application Runtime):** Sidecar-паттерн для state management. Dapr предоставляет единый API для state stores (Redis, PostgreSQL, etcd) с built-in support для concurrency control, state queries, transactions.
*   **Transactional Outbox:** Паттерн для guarantees доставки событий без dual-write проблем. События записываются в ту же транзакцию, что и бизнес-данные.
*   **Zero-copy State Transfer:** Использование RDMA и общей памяти для передачи состояния между контейнерами без накладных расходов на сеть. Актуально для HPC и high-frequency trading.
*   **WebAssembly (Wasm) для Stateful Processing:** Wasm-модули для stateful обработки данных в edge и streaming (WasmEdge, Spin). Поддержка persistent memory через WASI.

## Дополнительная информация

### См. также
*   **[Паттерны микросервисной архитектуры](./microservice_patterns.md)** — отказоустойчивость и масштабируемость.
*   **[Идемпотентность в API](./idempotency.md)** — как строить надежные stateless-системы.
*   **[Высокая доступность (High Availability)](./High_Availability/ha_overview.md)** — архитектурные паттерны отказоустойчивости.
*   **[Event-Driven Architecture](./event-driven-architecture.md)** — Event Sourcing, CDC, Saga и паттерны распределенного состояния.
