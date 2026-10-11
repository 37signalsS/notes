# Grafana: Высокая доступность

**Актуально для:** Grafana 13.x

## Определения

**Высокая доступность (High Availability, HA)** в Grafana — архитектурное решение, обеспечивающее непрерывную работу системы визуализации и алертинга при отказе одного или нескольких узлов.

**Ключевые принципы реализации:**
- **Stateless-узлы:** Все запущенные экземпляры Grafana идентичны и не хранят уникальное состояние локально. Любой узел может обслужить любой запрос.
- **Разделяемое состояние (Shared State):** Конфигурации, пользователи, сессии и состояние алертов вынесены во внешнюю БД; распределённые подсистемы (алертинг, Grafana Live) используют общий бэкенд для обмена сообщениями.
- **Дедупликация алертов:** Межсерверная коммуникация (Gossip) для предотвращения отправки повторяющихся уведомлений.

### Основные термины высокой доступности

| Термин | Определение |
| :--- | :--- |
| **MTTR** | Mean Time To Repair — среднее время восстановления после сбоя. Ключевая метрика HA: чем быстрее система восстанавливается, тем выше итоговая доступность. |
| **RTO** | Recovery Time Objective — бизнес-требование к максимальному времени простоя. Определяет, допустим ли ручной или требуется автоматический Failover. |
| **RPO** | Recovery Point Objective — максимально допустимая потеря данных. Диктует выбор метода репликации (синхронная vs асинхронная). |
| **Доступность «девятки»** | 99% = 3,65 дней простоя/год; 99.9% = 8,77 часов; 99.99% = 52,56 минут; 99.999% = 5,26 минут. Каждое следующее «девять» экспоненциально увеличивает стоимость. |
| **Split-Brain** | Ситуация, при которой части кластера теряют связь и каждая считает себя активной (Primary). Приводит к порче данных. Устраняется кворумом и нечётным числом узлов. |
| **Кворум (Quorum)** | Механизм консенсуса: действие разрешается только той части кластера, которая видит большинство узлов (`n/2 + 1`). |
| **Gossip-протокол** | Механизм децентрализованного обмена состоянием между узлами. В alerting-кластере Grafana реализован на базе библиотеки **Memberlist** и использует порт `9094` (TCP и UDP) для обнаружения узлов и синхронизации silences/уведомлений. |
| **Memberlist** | Встроенная в Grafana библиотека gossip, на которой строится HA-кластер системы оповещений. Основной (preferred) транспорт HA; поставляется в составе бинарника и не требует внешних сервисов. |
| **SNE** | Single-Node Evaluation — режим, при котором только один узел кластера (Primary, позиция `0`) выполняет вычисления правил, а остальные получают результаты через канал broadcast. Режим **включается явно** (`ha_single_node_evaluation = true`) и находится в статусе public preview. Снижает нагрузку на источники данных с N до 1. |
| **Active-Active** | Все узлы одновременно обслуживают пользовательский трафик. Grafana — stateless-приложение, поэтому балансировщик распределяет запросы по любому узлу. Обеспечивает масштабируемость и отказоустойчивость. |
| **Remote cache** | Внешний кэш (`[remote_cache]`), в котором хранятся токены аутентификации и другие временные данные. Может быть реализован на Redis, Memcached или основной БД. **Не хранит пользовательские сессии.** |
| **Connection Pool** | Набор соединений с БД, переиспользуемых между запросами. В HA-режиме каждый узел имеет собственный пул; суммарный размер пулов должен учитывать лимиты СУБД. |

## Базовые концепции

### Как Grafana выносит состояние наружу

Ключевой признак stateless-приложения: ни один узел не должен быть носителем уникального состояния. В Grafana это достигается раскладкой данных по нескольким независимым подсистемам.

1. **Основная база данных** — `[database]`. Единый источник истины для дашбордов, пользователей, организаций, провиженинга, **состояния и истории алертов, а также пользовательских сессий**. Допускаются **PostgreSQL** (рекомендуется) или **MySQL**. SQLite в режиме HA не поддерживается из-за ограничений на одновременную запись. Обратите внимание: `type = sqlite3` работает только для одиночного инстанса.
2. **Remote cache** — `[remote_cache]`. Кэширует токены аутентификации и другие временные авторизационные данные, снижая нагрузку на основную БД в кластере. Варианты: `redis`, `memcached`, `database` (по умолчанию — основная БД). Это **не** хранилище сессий: согласно документации Grafana, пользовательские сессии всегда хранятся в основной БД независимо от настроек `[remote_cache]`.
3. **Бэкенд alerting HA** — `[unified_alerting]`. Обеспечивает обмен состоянием между Alertmanager-компонентами: либо **Memberlist** (по умолчанию, предпочтительно), либо **Redis** (pub/sub). Подробнее — ниже.
4. **Бэкенд Grafana Live HA** — `[live]`. Если используется Grafana Live (WebSocket: стриминг данных, live-обновления), для работы через несколько инстансов требуется внешний HA-движок — Redis (`ha_engine = redis`).
5. **Внешнее хранилище изображений** — `[external_image_storage]` (опционально). Скриншоты панелей, прикрепляемые к уведомлениям, можно складывать в S3/GCS/Azure Blob/WebDAV вместо локального диска (`upload_external_image_storage = true` в `[unified_alerting.screenshots]`). Это устраняет локальную зависимость и позволяет любому узлу отдать изображение.

### Бэкенд HA системы оповещений: Memberlist и Redis

Grafana Alerting разделяет **генерацию** алертов и **доставку** уведомлений (модель Prometheus). Генератор — это Scheduler, получатель — встроенный Alertmanager. По умолчанию **все** инстансы Grafana вычисляют **все** правила: это гарантирует оценку даже при отказе части узлов ценой умножения нагрузки на источники данных (N раз).

Встроенные Alertmanager-ы связываются по **gossip-протоколу**, чтобы обмениваться активными алертами и silences и избегать дублирующих уведомлений. Alertmanager выбирает **доступность вместо согласованности**: редкие дубли или уведомления не по порядку считаются меньшим злом, чем пропуск уведомления.

Существует два взаимозаменяемых транспорта кластера:

| Транспорт | Как настраивается | Когда применять |
| :--- | :--- | :--- |
| **Memberlist** (preferred) | `ha_listen_address`, `ha_advertise_address`, `ha_peers` | По умолчанию. Узлы должны иметь прямой сетевой доступ друг к другу на порт `9094` (TCP и UDP). |
| **Redis** | `ha_redis_address` + `ha_redis_*` | Когда прямой обмен между узлами невозможен: TCP/UDP-порты заблокированы, узлы за NAT/proxy. Поддерживаются режимы Redis standalone, Cluster и Sentinel. |

Порт `9094` используется одновременно по **TCP** (доставка сообщений) и **UDP** (gossip-обнаружение), поэтому в firewall/NetworkPolicy нужно открывать **оба** протокола между всеми узлами кластера.

Ключевые параметры транспорта Memberlist (`[unified_alerting]`):

| Параметр | Назначение | Значение по умолчанию |
| :--- | :--- | :--- |
| `ha_listen_address` | Адрес и порт, на котором узел принимает HA-сообщения | `0.0.0.0:9094` |
| `ha_advertise_address` | Явный адрес, который узел сообщает другим (нужен за NAT/Kubernetes, где внутренний и внешний адреса различаются) | пусто |
| `ha_peers` | Список начальных узлов кластера `<HOST>:<PORT>`; **само наличие значения включает HA-режим** | пусто |
| `ha_peer_timeout` | Время ожидания отправки уведомления; умножается на позицию узла (replication lag) | `15s` |
| `ha_gossip_interval` | Интервал gossip-сообщений | `200ms` |
| `ha_push_pull_interval` | Интервал полной синхронизации состояния | `60s` |
| `ha_reconnect_timeout` | Время попыток переподключения к потерянному пиру | `6h` (в Kubernetes рекомендуется < `15m`) |
| `ha_label` | Метка кластера: разделяет gossip-трафик нескольких независимых кластеров в одной сети | пусто |

### Single-Node Evaluation (SNE)

Режим SNE меняет модель по умолчанию «все узлы вычисляют всё» на «вычисляет только один узел».

- **Проблема:** при классическом HA нагрузка на источники данных (Prometheus, Loki, ClickHouse) умножается на число узлов Grafana.
- **Решение:** кластер автоматически выбирает **Primary**-узел (позиция `0`), который вычисляет все правила и рассылает сработавшие алерты остальным узлам через канал broadcast. Остальные узлы вычисление пропускают, но применяют полученные алерты к своему встроенному Alertmanager.
- **Включение:** `ha_single_node_evaluation = true` в `[unified_alerting]`. По умолчанию режим **отключён** (`false`) и находится в статусе public preview. Настройка требует, чтобы HA-кластеризация уже была сконфигурирована (Memberlist или Redis).
- **Отказоустойчивость:** при потере Primary кластер перераспределяет позиции и назначает нового Primary. В момент переключения возникает короткий разрыв в вычислениях, но состояния алертов сохраняются в БД.
- **Размер очереди broadcast:** Primary складывает алерты в очередь перед рассылкой. По умолчанию она вмещает `200` сообщений (`ha_single_evaluation_alert_broadcast_queue_size`). При большом числе правил очередь может переполняться, и сообщения теряются — это видно по метрикам dropped (см. раздел мониторинга).

### Пользовательские сессии

В HA-кластере сессии хранятся в **основной базе данных** (не в Redis и не в локальной памяти узла). Благодаря этому:

- Балансировщик распределяет запросы по любому узлу без «липких сессий» (Sticky Sessions).
- При отказе узла пользователь продолжает работу на другом узле без повторной аутентификации.

Управление жизненным циклом сессии выполняется в секции `[auth]`:

| Параметр | Назначение | Значение по умолчанию |
| :--- | :--- | :--- |
| `login_cookie_name` | Имя cookie с токеном аутентификации | `grafana_session` |
| `login_maximum_inactive_lifetime_duration` | Максимальное время неактивности до повторного входа. Сбрасывается при каждой ротации токена | `7d` |
| `login_maximum_lifetime_duration` | Максимальное время жизни сессии с момента входа | `30d` |
| `token_rotation_interval_minutes` | Частота ротации токена активного пользователя | `10` |

`[remote_cache]` (Redis/Memcached) ускоряет проверку токенов аутентификации в кластере, но **не** заменяет хранилище сессий.

### Синхронизация `secret_key`

Параметр `secret_key` в секции `[security]` используется для шифрования (AES-256 в режиме CFB) и подписи чувствительных данных: секретов и паролей источников данных, сохранённых через Grafana.

**Требование:** значение должно быть **идентичным** на всех узлах кластера. Несоответствие приведёт к невозможности расшифровать секреты источника данных, сохранённые другим узлом. `secret_key` нельзя менять без последующего перекодирования сохранённых настроек источников данных.

В Grafana Enterprise управление ключами расширено механизмом envelope encryption: `encryption_provider` задаёт активный провайдер (по умолчанию — `secretKey.v1` на базе `secret_key`), а KMS-провайдеры вроде `awskms.v1` перечисляются в `available_encryption_providers`.

### Пулы соединений с базой данных

Каждый узел Grafana создаёт собственный пул соединений с СУБД. При конфигурации учитывайте:

- `max_open_conn` — максимум открытых соединений (по умолчанию `0` — без явного лимита, ограничение задаёт СУБД).
- `max_idle_conn` — максимум соединений в idle-пуле (по умолчанию `2`).
- `conn_max_lifetime` — максимальное время переиспользования соединения, в секундах (по умолчанию `14400`, то есть 4 часа).
- **Формула:** `(пул_на_узел × количество_узлов) < max_connections` СУБД + запас под системные процессы.

### Жизненный цикл запроса в HA-кластере

Приходящий запрос проходит следующий путь:

1. **Load Balancer** проверяет доступность узла через `/api/health`.
2. **Балансировщик** направляет запрос на любой доступный узел (Round Robin).
3. **Grafana Node** валидирует токен сессии, обратившись к основной БД (и при необходимости — к remote cache).
4. **Чтение конфигурации:** дашборд, папки и пользователи загружаются из основной БД (PostgreSQL/MySQL).
5. **Запрос к источнику данных:** если требуется метрика/лог, узел обращается к Prometheus/Loki и т.д.
6. **Рендеринг:** результат форматируется и возвращается пользователю.
7. **Алертинг (если настроен):** в режиме SNE только Primary (позиция `0`) выполняет оценку правил; результат рассылается остальным узлам.

### Ключевые компоненты кластера

| Компонент | Роль в системе | Требование к отказоустойчивости |
| :--- | :--- | :--- |
| **Load Balancer** | Точка входа для пользователей и API | L7 (Nginx/HAProxy) с проверкой `/api/health` |
| **Grafana Nodes** | Выполнение логики и рендеринг | Минимум 2 узла (рекомендуется 3+) |
| **PostgreSQL / MySQL** | Персистентность настроек, сессий и состояния алертов | Кластер (например, Patroni для PostgreSQL) |
| **Redis** (опционально) | Remote cache; HA-бэкенд alerting и Grafana Live | Redis Sentinel или Cluster |
| **Memberlist** | Gossip-протокол alerting (порт 9094) | Открытые порты TCP/UDP 9094 между всеми узлами |

## Практические сценарии

### Конфигурация кластера (grafana.ini)

Для сборки HA-кластера необходимо синхронизировать `secret_key`, настроить внешнюю БД и включить распределённые подсистемы.

```ini
[database]
type = postgres
host = postgres-ha-lb:5432
name = grafana
user = grafana_user
password = grafana_password
# HA-режим: часть внутренних механизмов опирается на БД вместо процесса.
# По умолчанию true; отключать (false) только для одиночного инстанса.
high_availability = true
# Ограничение пула соединений на узел
max_open_conn = 10
max_idle_conn = 5

[remote_cache]
# Кэш токенов аутентификации (не хранилище сессий)
type = redis
connstr = addr=redis-cache:6379,pool_size=100,db=0,prefix=grafana_cache

[security]
# Должен быть идентичен на всех узлах для расшифровки секретов источников данных
secret_key = <long_random_string_from_vault>

[auth]
login_cookie_name = grafana_session
login_maximum_inactive_lifetime_duration = 7d
login_maximum_lifetime_duration = 30d
token_rotation_interval_minutes = 10

[unified_alerting]
enabled = true
# Транспорт Memberlist
ha_listen_address = 0.0.0.0:9094
ha_advertise_address = 10.0.0.5:9094
ha_peers = 10.0.0.5:9094,10.0.0.6:9094,10.0.0.7:9094
ha_peer_timeout = 15s
ha_gossip_interval = 200ms
ha_push_pull_interval = 60s
ha_reconnect_timeout = 6h
ha_label = grafana-prod
# Single-Node Evaluation (public preview)
ha_single_node_evaluation = true
ha_single_evaluation_alert_broadcast_queue_size = 200

[live]
# HA-движок Grafana Live (нужен при использовании Live на нескольких узлах)
ha_engine = redis
ha_engine_address = redis-cache:6379
ha_prefix = grafana-live
```

### Alerting HA через Redis

Если прямой обмен между узлами невозможен (закрыты порты `9094`/TCP-UDP, узлы за NAT или proxy), используйте Redis в качестве транспорта alerting-кластера.

```ini
[unified_alerting]
enabled = true
# Режим Redis вместо Memberlist
ha_redis_address = redis-ha-1:6379,redis-ha-2:6379,redis-ha-3:6379
ha_redis_sentinel_mode_enabled = true
ha_redis_sentinel_master_name = mymaster
ha_redis_password = redis_password
ha_redis_prefix = grafana-alerting
ha_single_node_evaluation = true
```

Для Redis Cluster вместо Sentinel задайте `ha_redis_cluster_mode_enabled = true` (параметры Sentinel и Cluster взаимно исключающий). При использовании TLS включите `ha_redis_tls_enabled = true` и при необходимости настройте `ha_redis_tls_*`-поля. Memberlist остаётся предпочтительным транспортом; Redis применяйте только там, где прямой обмен невозможен.

### Развёртывание в Kubernetes (Helm)

Используется community-чарт `grafana-community/grafana` (в начале 2026 года чарт переехал из `grafana/helm-charts` в репозиторий `grafana-community/helm-charts`). Для production-кластера требуется минимум 3 реплики с анти-аффинностью и проверками готовности.

Важные для HA значения чарта:
- `headlessService: true` — создаёт headless-сервис, отдающий Pod IP на порту gossip `9094` (нужен для `ha_peers`).
- `gossipPortName`/`podPortName` — имена портов; gossip-порты `9094` (TCP/UDP) публикуются в контейнере автоматически, а переменная `POD_IP` подставляется чартом.
- Внешняя БД настраивается через секцию `[database]` внутри `grafana.ini` или через переменные `GF_DATABASE_*`; отдельного блока `database:` в `values.yaml` нет.

```yaml
# grafana-values.yaml
replicas: 3
headlessService: true

# Распределение по разным узлам и зонам
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: DoNotSchedule
    labelSelector:
      matchLabels:
        app.kubernetes.io/name: grafana

# Анти-аффинность: не размещать два пода на одном узле
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchLabels:
            app.kubernetes.io/name: grafana
        topologyKey: kubernetes.io/hostname

readinessProbe:
  httpGet:
    path: /api/health
    port: grafana

livenessProbe:
  httpGet:
    path: /api/health
    port: grafana
  initialDelaySeconds: 60
  timeoutSeconds: 30
  failureThreshold: 10

# Секреты — через переменные окружения, а не в открытом grafana.ini
env:
  GF_SECURITY_SECRET_KEY:
    valueFrom:
      secretKeyRef:
        name: grafana-secrets
        key: secret-key
  GF_DATABASE_PASSWORD:
    valueFrom:
      secretKeyRef:
        name: grafana-db-secret
        key: password

grafana.ini:
  database:
    type: postgres
    host: postgres-service.db-namespace:5432
    name: grafana
    user: grafana_user
    high_availability: true
    max_open_conn: 10
    max_idle_conn: 5
  remote_cache:
    type: redis
    connstr: addr=redis-service:6379,pool_size=100,db=0
  unified_alerting:
    ha_listen_address: "${POD_IP}:9094"
    ha_advertise_address: "${POD_IP}:9094"
    ha_peers: "grafana-headless.monitoring:9094"
    ha_peer_timeout: 15s
    ha_reconnect_timeout: 2m
    ha_single_node_evaluation: true
  live:
    ha_engine: redis
    ha_engine_address: redis-service:6379
```

### Валидация состояния HA-кластера

После развёртывания выполните проверки:

```bash
# 1. Проверка реплик Deployment
kubectl get deployment grafana -n monitoring
# → NAME      READY   UP-TO-DATE   AVAILABLE   AGE
# → grafana   3/3     3            3           2m

# 2. Проверка распределения по зонам (при topologySpreadConstraints)
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana -o wide
# → grafana-xxx-xxxxx   3/3     Running   0          2m   10.0.0.1   node-1   zone-a
# → grafana-xxx-xxxxx   3/3     Running   0          2m   10.0.1.2   node-2   zone-b
# → grafana-xxx-xxxxx   3/3     Running   0          2m   10.0.2.3   node-3   zone-c

# 3. Проверка endpoint /api/health с каждого пода
kubectl exec -n monitoring grafana-xxx-xxxxx -- curl -s http://localhost:3000/api/health
# → {"commit":"...","database":"ok","version":"13.2.0"}

# 4. Проверка размера gossip-кластера (должно быть равно числу узлов)
kubectl port-forward svc/grafana -n monitoring 3000:80 &
curl -s http://localhost:3000/metrics | grep grafana_alertmanager_cluster_members

# 5. Проверка позиций узлов (в SNE ровно один узел имеет position=0)
curl -s http://localhost:3000/metrics | grep grafana_alertmanager_peer_position
```

### Rolling Update (обновление без простоя)

При обновлении Grafana в HA-кластере используйте Rolling Update:

```bash
helm upgrade --install grafana grafana-community/grafana \
  -f grafana-values.yaml \
  --namespace monitoring \
  --atomic \
  --wait --timeout 10m
```

**Механизм:**
1. Helm обновляет Deployment с `strategy: RollingUpdate` (по умолчанию).
2. Kubernetes создаёт новый Pod и ждёт прохождения `readinessProbe`.
3. После готовности нового Pod трафик переключается на него, старый Pod завершается gracefully.
4. Если `readinessProbe` на новом поде не проходит, обновление останавливается (при `--atomic` выполняется откат).

**Важно:** Не отключайте `readinessProbe` и `livenessProbe` — без них Kubernetes не узнает, что Grafana готова к трафику, и отправит на неё запросы до инициализации.

### Обработка отказа Redis

Последствия зависят от того, какие подсистемы используют Redis:

- **Сессии:** не затрагиваются — они хранятся в основной БД.
- **Remote cache:** Grafana переключается на основную БД для проверки токенов аутентификации, что повышает нагрузку на неё.
- **Grafana Live:** при `ha_engine = redis` live-соединения теряют общий транспорт; работа Live может нарушиться до восстановления Redis.
- **Alerting (если выбран Redis-транспорт):** нарушается обмен состоянием между узлами; при большой нагрузке возможны дубли уведомлений.

**Рекомендация:** разворачивайте Redis в режиме Sentinel или Cluster, если он критичен (Live или Redis-транспорт alerting).

### Мониторинг и алертинг состояния кластера

Метрики HA доступны на `/metrics` (порт `3000`) и автоматически не собираются — нужен scrape-конфиг Prometheus:

```yaml
- job_name: grafana
  honor_timestamps: true
  scrape_interval: 15s
  scrape_timeout: 10s
  metrics_path: /metrics
  scheme: http
  static_configs:
    - targets:
        - grafana:3000
```

> **Важно:** начиная с Grafana v12.4 метрики Alertmanager получили префикс `grafana_` (например, `grafana_alertmanager_cluster_members`). При обновлении с более старых версий скорректируйте дашборды и правила.

**Ключевые метрики:**

| Метрика | Описание | Алерт |
| :--- | :--- | :--- |
| `grafana_alertmanager_cluster_members` | Текущее число узлов в gossip-кластере | `< N` при ожидаемых N узлах |
| `grafana_alertmanager_peer_position` | Позиция узла в кластере; узел на позиции `0` — Primary | В SNE: больше одного узла с `position=0` |
| `grafana_alerting_alerts_received_total` | Число принятых алертов на узел; не-Primary узлы получают их через broadcast | Резкое падение у не-Primary → проблемы broadcast |
| `grafana_alerting_alertmanager_alerts{state="active"}` | Активные алерты на узле | Значение должно совпадать на всех узлах |
| `grafana_alertmanager_oversized_gossip_message_dropped_total{key="alerts:broadcast"}` | (Memberlist) Отброшено broadcast-сообщений из-за переполнения очереди | Рост → увеличить `ha_single_evaluation_alert_broadcast_queue_size` |
| `grafana_alertmanager_cluster_messages_publish_failures_total` | (Redis) Ошибки публикации сообщений состояния | Рост → проверить Redis |

**Пример PromQL-запроса для проверки SNE:**

```promql
# Проверка: только один узел должен быть Primary (position=0)
count(grafana_alertmanager_peer_position == 0) == 1
```

### Устранение неполадок (Troubleshooting)

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Алерты дублируются в HA** | Не настроены `ha_peers` / транспорт, либо используется классический HA при желании снизить нагрузку | Проверьте, что `ha_peers` заполнены и порт `9094` (TCP+UDP) доступен между узлами; при необходимости включите `ha_single_node_evaluation = true` |
| **Split-Brain (два Primary в SNE)** | Нечётное число узлов, сетевой partition, нестабильный gossip | Проверьте `ha_peers`, сетевые политики и метрики позиций; убедитесь в стабильной сети между узлами |
| **Gossip-кластер не образуется** | Порт `9094` закрыт по TCP или UDP | Откройте **оба** протокола на `9094` между подами/узлами; проверьте NetworkPolicy |
| **`/api/health` возвращает 500** | Основная БД недоступна или миграции не применены | Проверьте доступность СУБД; смотрите логи с `logger=database` |
| **Ошибка подключения к БД** | Исчерпан пул соединений СУБД | Увеличьте `max_connections` СУБД; скорректируйте `max_open_conn` в Grafana |
| **Секреты источников данных не расшифровываются** | Разные `secret_key` на узлах | Приведите `secret_key` к одному значению на всех узлах |
| **Grafana не стартует в K8s** | CrashLoopBackOff | Проверьте `readinessProbe`, права на PVC, SecurityContext, наличие секрета |
| **Метрики SNE отсутствуют** | Gossip-порт закрыт брандмауэром | Откройте TCP `9094` и UDP `9094` между подами/узлами |
| **Live не работает через несколько узлов** | Не настроен HA-движок Grafana Live | Включите `[live] ha_engine = redis` и укажите `ha_engine_address` |
| **Дребезг алертов при обновлении** | Расхождение часов между узлами | Настройте NTP/Chrony; проверьте `timedatectl status` |

### Рекомендации (Best Practices)

1. **Количество узлов:** используйте нечётное число (3 или 5) для устойчивости gossip-кластера. Два узла не дают отказоустойчивости при сетевом разделении.
2. **Секреты:** храните `secret_key` во внешнем vault (HashiCorp Vault, KMS). Для HA он должен быть идентичен на всех узлах.
3. **База данных:** PostgreSQL или MySQL — обязательны для HA. Сессии и состояние алертов живут в БД, поэтому её отказоустойчивость критична.
4. **Remote cache:** используйте Redis/Memcached для кэша токенов аутентификации в нагруженных кластерах; не путайте его с хранилищем сессий.
5. **Пул соединений:** настройте `max_open_conn` и `max_idle_conn` с учётом `max_connections` СУБД. Правило: `(replicas × max_open_conn) < 0.8 × max_connections`.
6. **Транспорт alerting:** предпочитайте Memberlist. Переходите на Redis только при невозможности прямого сетевого обмена между узлами.
7. **Сеть:** открывайте порт `9094` по **TCP** (сообщения) и **UDP** (обнаружение) между всеми узлами. В K8s используйте Headless Service (`headlessService: true`).
8. **Мониторинг:** настройте алерты на метрики `cluster_members` и `peer_position`. Отсутствие Primary в SNE — критичный инцидент.
9. **Обновления:** используйте Rolling Update с `readinessProbe`. Никогда не обновляйте все узлы одновременно.
10. **NTP:** обязательна синхронизация времени через Chrony/NTPd — расхождение часов приводит к нестабильному алертингу.
11. **Бэкапы:** регулярно бэкапируйте основную БД и конфигурации провиженинга. HA защищает от аппаратных сбоев, но не от логических ошибок.

### Граничные случаи (Edge Cases)

- **SQLite в HA:** не поддерживается. При попытке запуска нескольких инстансов с общей SQLite произойдёт порча файла БД. Для HA — только PostgreSQL/MySQL.
- **Классический HA vs SNE:** SNE снижает нагрузку на источники данных (с N до 1), но на время переключения Primary возникает короткий разрыв в вычислениях. Классический HA (все узлы вычисляют всё) такого разрыва не даёт, но умножает нагрузку.
- **Переполнение очереди broadcast:** при большом числе правил очередь Primary (по умолчанию `200`) переполняется, сообщения теряются. Отслеживайте dropped-метрику своего транспорта и увеличивайте `ha_single_evaluation_alert_broadcast_queue_size`.
- **Redis Sentinel vs Cluster:** Sentinel подходит для failover мастера; Cluster — для шардирования и больших объёмов. Для alerting-транспорта и Live достаточно Sentinel.
- **Лимит ConfigMap в Kubernetes:** размер ConfigMap ограничен 1 МиБ. Для крупных наборов дашбордов используйте внешний провиженинг (dashboard providers, S3/Git) или отдельные ConfigMap на дашборд, а не один общий.
- **Потеря кворума (Quorum Loss):** при потере большинства узлов оставшийся узел не может полноценно поддерживать gossip-кластер. Восстановление — после возвращения кворума.
- **Временной drift:** даже при настроенном NTP возможна дрейф в несколько секунд. Для критичных алертов задавайте `evaluate_interval` не менее 1 минуты.
- **Обновление PostgreSQL:** при миграции major-версии (например, 15 → 16) остановите все узлы Grafana, обновите БД, затем запускайте узлы последовательно.

**Связанные темы:**
- [Резервное копирование и восстановление](./grafana_backup_restore.md) — бэкап БД и конфигурации Grafana
- [Обновление и миграция](./grafana_upgrade_migration.md) — обновление версий и смена СУБД

## Дополнительная информация

### Рекомендации по эксплуатации

- **Синхронизация времени:** расхождение часов между узлами приводит к «дребезгу» алертов и дублированию уведомлений. Использование NTP/Chrony обязательно.
- **Кворум:** для устойчивости gossip-кластера используйте нечётное количество узлов (3 и более) и стабильное DNS-имя для `ha_peers`.
- **База данных:** основная БД — единственный источник истины (настройки, пользователи, сессии, состояние алертов). Убедитесь, что лимит соединений (`max_connections`) достаточен для всех узлов с учётом их пулов.
- **Сетевая доступность:** порт `9094` должен быть доступен по **TCP** (передача сообщений) и **UDP** (gossip-обнаружение).

**См. также:**
- [Grafana: Обзор](./grafana_overview.md)
- [Обзор Grafana Alerting](./alerting/concepts.md)
- [Обзор High Availability](../Concepts/High_Availability/ha_overview.md)
- [PostgreSQL HA: Обзор](../Databases/PostgreSQL/Concepts/high_availability.md)
