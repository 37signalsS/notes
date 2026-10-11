# MariaDB MaxScale: Connection Pooling и Connection Sharing

**Актуально для:** MaxScale 25.10.x / 26.10.x

## Определения

*   **Persistent connection pool** — пул неиспользуемых соединений к бэкенду, которые MaxScale сохраняет после закрытия клиентской сессии и переиспользует для новых сессий. Управляется серверными параметрами `persistpoolmax` и `persistmaxtime`. Пул существует отдельно в каждом routing thread (с 6.3.0 MaxScale округляет `persistpoolmax` вверх, чтобы каждый поток получил равный пул).
*   **Connection sharing** — режим, при котором idle клиентская сессия отдаёт своё бэкенд-соединение в общий пул (`idle_session_pool_time`), и несколько сессий делят ограниченное число бэкенд-соединений. Введён в MaxScale 6.4.0.
*   **max_routing_connections** — лимит одновременных маршрутных (бэкендных) соединений к одному серверу. Соединения в пуле учитываются в лимите; соединения монитора и user account manager — нет. `0` (default) — без лимита; MaxScale Trial — максимум 15.
*   **multiplex_timeout** — время ожидания освобождения бэкенд-соединения при включённом connection sharing (default 60s).
*   **connection_keepalive** — keepalive-пинги бэкендам, даже когда клиент idle (сервисный параметр, default 300s, auto-tunable).
*   **force_connection_keepalive** — безусловные keepalive-пинги (6.4.9+), эмуляция поведения до 2.5.21.
*   **auth_all_servers** — агрегация auth-данных со всех серверов (default `false`; schemarouter включает автоматически с 24.02).
*   **auto_tune** — глобальный параметр (`[maxscale]`), автоматически подгоняющий `connection_keepalive` (80% от минимального значения на серверах сервиса) и `wait_timeout` (минимальное значение на серверах сервиса) по данным мониторов.
*   **max_sescmd_history** — лимит истории сессионных команд (default 50); сессия, превысившая лимит, исключается из пулинга (см. «Что нельзя использовать с connection sharing»).

## Теоретический блок

### Чем пулинг MaxScale отличается от ProxySQL

ProxySQL делает **multiplexing**: одно бэкенд-соединение обслуживает множество клиентских сессий одновременно (с ограничениями — транзакции, блокировки, `@var`, временные таблицы отключают мультиплексирование).

MaxScale исторически **не мультиплексирует** в этом смысле: каждая клиентская сессия держит свои собственные соединения к бэкендам. Что есть в MaxScale:

1.  **Persistent pool** (`persistpoolmax`/`persistmaxtime`) — соединения не закрываются при закрытии сессии, а лежат в пуле. Новая сессия берёт соединение из пула вместо установления нового TCP+auth. Экономит на handshake и аутентификации при churn-сессиях, но не уменьшает пиковое число соединений.
2.  **Connection sharing** (`idle_session_pool_time`) — idle сессия отдаёт бэкенд-соединение в пул; при приходе запроса сессия забирает соединение обратно. Это ближе к мультиплексированию, но работает только для idle-сессий.

Формула масштабирования в MaxScale с connection sharing:

```
бэкенд-соединения ≈ max_routing_connections (лимит на сервер)
клиентские сессии  ≫ бэкенд-соединений (за счёт idle-пулинга)
```

### Как работает persistent pool

*   Пул существует **per routing thread** (MaxScale 6.3+ округляет `persistpoolmax` так, чтобы каждый поток получил равный пул — эффективный лимит на сервер может быть выше настроенного значения).
*   Соединение из пула при использовании в readwritesplit восстанавливается до состояния сессии; другие роутеры этого не делают.
*   `persistpoolmax=0` (default) — пул отключён. Если пул заполнен, лишние соединения закрываются, а не помещаются в пул.
*   `persistmaxtime` — максимальный возраст соединения в пуле: соединение, простоявшее в пуле дольше указанного времени, закрывается. **Default `0s` не означает «вечно»**: каждый routing thread проверяет пул раз в секунду и закрывает соединения с возрастом `> persistmaxtime`, т.е. при `0s` соединение живёт в пуле ~1 секунду. Для удержания соединений задавайте значение явно (например, `persistmaxtime=5m`). Гранулярность параметра — секунды: значение в миллисекундах отклоняется; значение без единицы трактуется как секунды в 2.4/2.5 и в новых версиях может быть отклонено.
*   Соединения в пуле учитываются в `max_routing_connections`.
*   Условия помещения соединения в пул (реализация MaxScale): `persistpoolmax > 0`; соединение в состоянии polling, установлено и не «повешено»; сессия разрешает пулинг (`can_pool_backends`); сервер в состоянии running; в пуле есть место.
*   Обслуживание пула (раз в секунду, per routing thread): сервер down → весь пул к этому серверу очищается; иначе закрываются устаревшие (`persistmaxtime`) и сверхлимитные соединения (если `persistpoolmax` уменьшен в runtime).

### Connection sharing: механизм

Обычно MaxScale помещает в пул только соединения закрытых сессий. При `idle_session_pool_time >= 0` MaxScale дополнительно забирает соединения у **работающих** idle-сессий и переподключает их сессии, когда та выполняет запрос — эффективно несколько сессий делят одни бэкенд-соединения.

*   MaxScale забирает соединение только когда другая сессия в нём нуждается: `idle_session_pool_time` ограничивает частоту перемещения соединений между сессиями. `idle_session_pool_time=0ms` — перемещение при первой возможности (в 24.02–24.02.4 при `0s` соединения распределялись между сессиями несправедливо, MXS-5492, исправлено в 24.02.5).
*   Используйте sharing только когда ограничение числа бэкенд-соединений важнее задержки запросов и throughput.
*   Требуются серверные параметры: `max_routing_connections`, `persistpoolmax`, `persistmaxtime`.
*   Внутренний механизм перезапуска сессий сервиса (`Session::restart`) отказывается работать при включённом `idle_session_pool_time` — в логе ошибка «Cannot restart session if 'idle_session_pool_time' is in use».
*   Без sharing превышение `max_routing_connections` — ошибка подключения к бэкенду (клиент подключён к MaxScale, но запросы падают). С sharing — сессии ставятся на hold и «виснут» до `multiplex_timeout`, затем MaxScale возвращает клиенту ошибку, обычно завершая сессию («Timed out when waiting for a connection»).

### Что нельзя использовать с connection sharing

При помещении соединения в пул и повторном использовании состояние теряется. Сессионные переменные и prepared statements восстанавливаются replay'ем сессионных команд, но часть состояния не переносится:

*   **Открытая транзакция** — sharing отключается для сессии до завершения транзакции.
*   `LOCK TABLES`, `GET_LOCK` и любые другие операторы, вводящие состояние в соединение.
*   Временные таблицы и «проблемные» сессионные переменные, например `LAST_INSERT_ID()` (используйте значение, возвращённое коннектором, вместо переменной).
*   Хранимые процедуры с сессионными побочными эффектами.
*   Другие ситуации могут не детектироваться — ответственность за отсутствие такого состояния лежит на пользователе.
*   Сессия, превысившая `max_sescmd_history` (default 50), исключается из пулинга; если таких сессий много и задан `max_routing_connections`, остальные сессии застопорятся — найти бэкенд-соединение нечем. Избежать помогает `prune_sescmd_history` (default `true`), но обрезанные команды не replay'ятся при reuse: если обрезаны важные команды (например, подготовки statement'ов), сессия может упасть позже.

### Фрагментация пулов и монополизация потоков

Каждый routing thread имеет свой пул. Поток может монополизировать сервер: если пул потока 1 содержит 100 соединений к ServerA при `max_routing_connections=100`, другие потоки к серверу не подключатся. Помогает снижение `persistmaxtime` этого сервера (ненужные соединения закрываются быстрее, слоты освобождаются для других потоков) или снижение числа routing threads (`threads`) — уменьшает фрагментацию, но может снизить общий throughput. При connection sharing соединения в пуле находятся мгновенно, поэтому `persistmaxtime` можно ставить низким, например `10s`.

### Масштабирование

Если активных клиентов больше, чем `max_routing_connections`, throughput страдает — клиенты ходят по очереди. В этом случае число бэкенд-соединений на сессию нужно минимизировать. Для ReadWriteSplit:

```ini
max_slave_connections=1
lazy_connect=1
transaction_replay=true
```

Тогда MaxScale обрабатывает примерно (`число реплик` × `max_routing_connections`) read-запросов одновременно; write-запросы всё равно по очереди (один Primary).

## Практические сценарии

### Prerequisites

*   MaxScale 6.4.0+ для connection sharing (`idle_session_pool_time`).
*   Понимание, что пулинг не заменяет пулинг на стороне приложения — он уменьшает cost handshake, а не число клиентских соединений.
*   Монитор на серверах — для `auto_tune` (значения собираются мониторами; без монитора авто-подстройка не работает).

### Шаг 1: Persistent pool для churn-нагрузки

```ini
# /etc/maxscale.cnf

[db-node-1]
type=server
address=192.168.1.11
port=3306

# Пул из 50 соединений к этому серверу.
# С 6.3.0 значение округляется вверх до равного числа
# на каждый routing thread — эффективный лимит выше.
persistpoolmax=50

# Соединение старше 5 минут выбрасывается из пула.
# ВАЖНО: default 0s — соединения закрываются на ближайшей
# секундной проверке (~1s жизни), т.е. пул фактически не работает
persistmaxtime=5m

# Лимит маршрутных соединений (пул учитывается в лимите;
# монитор и user account manager — не учитываются)
max_routing_connections=200
```

Серверные параметры:

| Параметр | Тип | Default | Dynamic | Смысл |
| :--- | :--- | :--- | :--- | :--- |
| `persistpoolmax` | number | `0` (выключен) | Yes | Размер пула на сервер; при переполнении соединения закрываются |
| `persistmaxtime` | duration | `0s` | Yes | Макс. возраст соединения в пуле; старше — закрывается; значения в ms отклоняются |
| `max_routing_connections` | number | `0` (без лимита); Trial: `15` | Yes | Лимит маршрутных соединений; пульные учитываются |

### Шаг 2: Connection sharing для высокой конкурентности

Конфигурация по официальной документации (ReadWriteSplit):

```ini
[server1]
type=server
# Должно соответствовать capacity MariaDB Server
max_routing_connections=1000
# То же значение — разумная стартовая точка для persistpoolmax
persistpoolmax=1000
# При sharing соединения в пуле мгновенно — можно низкое значение
persistmaxtime=10

[RW-Split-Service]
type=service
router=readwritesplit
servers=server1,server2,server3
user=maxscale_user
password=СЛОЖНЫЙ_ПАРОЛЬ

# Сессия idle > 500ms отдаёт бэкенд-соединение в пул
idle_session_pool_time=500ms

# Ожидание освобождения соединения при исчерпании лимита
multiplex_timeout=60s

# Минимизация бэкенд-соединений на сессию (см. «Масштабирование»)
max_slave_connections=1
lazy_connect=1
transaction_replay=true

# Keepalive к бэкендам (default 300s)
connection_keepalive=300s
```

Сервисные параметры:

| Параметр | Тип | Default | Dynamic | Смысл |
| :--- | :--- | :--- | :--- | :--- |
| `idle_session_pool_time` | duration | `-1s` (выключен) | Yes | `>= 0` включает sharing; секунды или ms; `0ms` — перемещение сразу |
| `multiplex_timeout` | duration | `60s` | Yes | Таймаут ожидания соединения; увеличить при ошибках «Timed out when waiting for a connection», уменьшить — если предпочтительнее быстрый отказ |
| `connection_keepalive` | duration | `300s` | Yes | Keepalive-пинги; auto-tunable; `0s` — отключить |
| `force_connection_keepalive` | boolean | `false` | Yes | 6.4.9+: безусловные пинги (эмуляция поведения до 2.5.21) |
| `auth_all_servers` | boolean | `false` | Yes | Auth-данные со всех серверов; schemarouter включает автоматически (24.02+) |
| `max_sescmd_history` | number | `50` | Yes | Лимит истории сессионных команд; превышение — сессия вне пулинга |
| `prune_sescmd_history` | boolean | `true` | Yes | Обрезка истории при превышении лимита |
| `disable_sescmd_history` | boolean | `false` | Yes | Отключает историю (замена упавшей реплики не работает) |

Поведение `connection_keepalive` (детали):

*   Пинг отправляется, если соединение простаивает дольше интервала. Начиная с 2.5.21/6.4.0 пинги **не** отправляются, если клиент idle дольше `connection_keepalive` (в старых версиях — независимо от состояния клиента).
*   Действует только в top-level сервисах (куда указывает listener); для сервисов, подключённых через `targets`, не применяется.
*   Изменение в runtime действует немедленно. Для `readconnroute` — небольшая просадка производительности (нужно отслеживать запросы); для `readwritesplit`/`schemarouter` — без разницы (они и так отслеживают результаты).

### Шаг 3: Мониторинг пула

Метрики OpenTelemetry (**добавлены в MaxScale 26.10**, см. [Мониторинг](./maxscale_monitoring.md)):

| Метрика | Тип | Смысл |
| :--- | :--- | :--- |
| `maxscale.server.pool_size` | Gauge | Текущий размер пула соединений |
| `maxscale.server.pool_found` | Gauge (running total) | Сколько раз соединение взято из пула (hit) |
| `maxscale.server.pool_empty` | Gauge (running total) | Сколько раз пул был пуст (miss) |

В Prometheus (через OTel Collector) точки заменяются подчёркиваниями: `maxscale_server_pool_empty`.

На MaxScale 25.10 (метрик пула нет) используйте pull-диагностику:

```bash
# Число соединений к серверам (поле Connections)
maxctrl list servers

# Детально по сервису: Current/Total/Max Connections, Router Diagnostics
maxctrl show service RW-Split-Service

# Idle-время сессий — прямая оценка для idle_session_pool_time
# (поле Idle: сколько секунд сессия простаивает)
maxctrl list sessions

# REST API: соединения и состояние серверов
curl -sS -u admin:СЛОЖНЫЙ_ПАРОЛЬ http://127.0.0.1:8989/v1/servers
```

Оценка эффективности (26.10+): `pool_found / (pool_found + pool_empty)` — доля попаданий в пул. Низкая доля при высоком `pool_empty` — пул слишком мал или `persistmaxtime` слишком короткий.

### Шаг 4: Автонастройка keepalive

```ini
# /etc/maxscale.cnf — глобальная секция
[maxscale]
# Автоподгонка connection_keepalive (80% от минимального значения
# на серверах сервиса) и wait_timeout (минимальное значение на серверах).
# Значения собираются мониторами: без монитора авто-подстройка не работает.
# Явно заданные значения перезаписываются на следующем цикле авто-подстройки
# (только если серверы сервиса мониторятся).
auto_tune=all
```

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Запросы «виснут», сессии неотзывчивы при sharing | Исчерпан `max_routing_connections` | Увеличьте `max_routing_connections` или уменьшите `idle_session_pool_time`; проверьте `multiplex_timeout`. Ошибка «Timed out when waiting for a connection» — таймаут ожидания, сессия обычно завершается |
| Пул не работает | `persistpoolmax=0` (default) | Задайте `persistpoolmax` на серверах |
| Соединения не задерживаются в пуле | `persistmaxtime=0s` (default): эвикция на ближайшей секундной проверке | Задайте явное значение (`persistmaxtime=5m` и т. п.) |
| Ошибки аутентификации при reuse | Состояние сессии не восстановлено (роутер ≠ readwritesplit) | Для не-readwritesplit роутеров reuse не восстанавливает сессионное состояние — проверяйте приложение |
| Рост `maxscale.server.pool_empty` (26.10+) | Пул мал относительно churn; `persistmaxtime` слишком короткий | Поднимите `persistpoolmax` (помните про per-thread округление) и `persistmaxtime` |
| Сессии застопорились, пулинг отключён для отдельных сессий | Сессия превысила `max_sescmd_history` (50) | Поднимите `max_sescmd_history` (правило: ожидаемое число сессионных команд × 2) или включите `prune_sescmd_history` — но обрезанные команды не replay'ятся |
| Один routing thread монополизирует сервер | Per-thread пулы: поток держит все слоты (`persistpoolmax` ≈ `max_routing_connections`) | Уменьшите `persistmaxtime` этого сервера или число `threads` (меньше фрагментации, но возможна просадка throughput) |
| Не работает перезапуск сессий сервиса | Включён `idle_session_pool_time` | Отключите sharing для сервиса, где нужен restart (в логе: «Cannot restart session if 'idle_session_pool_time' is in use») |
| Соединения рвутся по `wait_timeout`, хотя keepalive включён | 2.5.21+: пинги не шлются, если клиент idle дольше `connection_keepalive` | `force_connection_keepalive=true` (6.4.9+) — но тогда `wait_timeout` перестаёт действовать (пинги маскируют idle) |
| NAT/файрвол рвёт idle-соединения | `connection_keepalive=0s` | Оставьте default 300s или используйте `auto_tune` |

## Ограничения

*   Connection sharing работает только для idle-сессий; открытая транзакция отключает sharing для сессии до её завершения.
*   Часть состояния не переносится при reuse (см. список выше); недетектируемые случаи — ответственность приложения.
*   Перезапуск сессий сервиса невозможен при включённом `idle_session_pool_time`.
*   Пулы per-thread: фрагментация и монополизация (см. выше).
*   `persistmaxtime`: гранулярность — секунды, значения в ms отклоняются.
*   `connection_keepalive` действует только в top-level сервисах.
*   MaxScale Trial: максимум 15 маршрутных соединений на сервер.
*   Метрики пула (`maxscale.server.pool_*`) доступны только в MaxScale 26.10+.

## Best Practices

1.  **Сначала — пул на стороне приложения.** MaxScale-пулинг экономит handshake, но не заменяет клиентский пулинг.
2.  **`persistpoolmax`** — для нагрузки с большим числом коротких сессий (частые connect/disconnect); учитывайте per-thread округление (6.3.0+).
3.  **Всегда задавайте `persistmaxtime` явно** — default `0s` держит соединение в пуле ~1 секунду.
4.  **Connection sharing** — когда клиентских сессий на порядок больше, чем допустимых бэкенд-соединений, и сессии часто idle; только если лимит бэкенд-соединений важнее задержки и throughput.
5.  **Считайте лимит:** `max_routing_connections` должен покрывать и активные, и пульные соединения; `persistpoolmax` не должен превышать `max_routing_connections` (разумная стартовая точка — то же значение).
6.  **При sharing:** `persistmaxtime` можно низким (`10s`), `idle_session_pool_time` — в ms (`500ms`); для ReadWriteSplit — `max_slave_connections=1`, `lazy_connect=1`, `transaction_replay=true`.
7.  **Не используйте с sharing** `LOCK TABLES`, `GET_LOCK`, временные таблицы, `LAST_INSERT_ID()` и хранимые процедуры с сессионными побочными эффектами.
8.  **`connection_keepalive=300s`** (default) — не отключайте без причины: предотвращает разрыв idle-соединений NAT/файрволом; для автоматической подстройки — `auto_tune`.
9.  **`auth_all_servers`** — не задавайте вручную для schemarouter: роутер включает его автоматически (24.02+).
10. **Мониторьте пул:** `pool_empty`/`pool_found` (26.10+), `maxctrl list servers` / `list sessions` и REST API `/v1/servers` (25.10).

## Дополнительная информация

### См. также

*   **[ProxySQL: Connection Pool и Multiplexing](../../MySQL/ProxySQL/proxysql_connection_pool.md)** — мультиплексирование в ProxySQL: когда отключается, диагностика pinning.
*   **[Read/Write Split](./maxscale_readwritesplit.md)** — поведение сессий и транзакций.
*   **[Обзор MaxScale](./maxscale_overview.md)** — общая архитектура и `lazy_connect`.
*   **[Мониторинг MaxScale](./maxscale_monitoring.md)** — метрики пула (26.10+) и OTel-экспорт.
*   **[Connection Pooling](../../../Networking/Concepts/connection_pooling.md)** — общая теория пулинга.
*   [MaxScale Servers](https://mariadb.com/docs/maxscale/reference/maxscale-servers.md) — серверные параметры (`persistpoolmax`, `persistmaxtime`, `max_routing_connections`).
*   [MaxScale Configuration Guide](https://mariadb.com/docs/maxscale/maxscale-management/deployment/installation-and-configuration/maxscale-configuration-guide.md) — сервисные параметры (`idle_session_pool_time`, `multiplex_timeout`, `connection_keepalive`, `auto_tune`).
*   [MaxScale Telemetry](https://mariadb.com/docs/maxscale/reference/maxscale-telemetry.md) — эталонный список экспортируемых метрик.
*   [MaxCtrl](https://mariadb.com/docs/maxscale/reference/maxscale-maxctrl.md) — `list servers`, `list sessions`, `show service`.
