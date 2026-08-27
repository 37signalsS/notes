# Grafana: Высокая доступность

## Определения

**Высокая доступность (High Availability, HA)** в Grafana — архитектурное решение, обеспечивающее непрерывную работу системы визуализации и алертинга при отказе одного или нескольких узлов.

**Ключевые принципы реализации:**
- **Stateless-узлы:** Все запущенные экземпляры Grafana идентичны и не хранят уникальное состояние локально.
- **Разделяемое состояние (Shared State):** Использование внешних отказоустойчивых систем для хранения конфигураций, сессий и кэша.
- **Дедупликация алертов:** Межсерверная коммуникация для предотвращения отправки повторяющихся уведомлений.

**Текущая версия (август 2026):** Grafana 13.1.x.

### Основные термины высокой доступности

| Термин | Определение |
| :--- | :--- |
| **MTTR** | Mean Time To Repair — среднее время восстановления после сбоя. Ключевая метрика HA: чем быстрее система восстанавливается, тем выше итоговая доступность. |
| **RTO** | Recovery Time Objective — бизнес-требование к максимальному времени простоя. Определяет, допустим ли ручной или требуется автоматический Failover. |
| **RPO** | Recovery Point Objective — максимально допустимая потеря данных. Диктует выбор метода репликации (синхронная vs асинхронная). |
| **Доступность «девятки»** | 99% = 3,65 дней простоя/год; 99.9% = 8,77 часов; 99.99% = 52,56 минут; 99.999% = 5,26 минут. Каждое следующее «девять» экспоненциально увеличивает стоимость. |
| **Split-Brain** | Ситуация, при которой части кластера теряют связь и каждая считает себя активной (Primary). Приводит к порче данных. Устраняется кворумом и нечетным числом узлов. |
| **Кворум (Quorum)** | Механизм консенсуса: действие разрешается только той части кластера, которая видит большинство узлов (`n/2 + 1`). |
| **Gossip-протокол** | Механизм децентрализованного обмена состоянием между узлами. В Grafana используется Memberlist на порту `9094` для обнаружения узлов и согласования лидера. |
| **SNE** | Single-Node Evaluation — режим оценки алертов, при котором только один узел (Primary/P0) выполняет вычисления, остальные получают результаты через Gossip. Снижает нагрузку на источники данных. |
| **Active-Passive** | Основной узел обрабатывает нагрузку, резервный ожидает. При отказе происходит переключение. |
| **Active-Active** | Все узлы одновременно обрабатывают нагрузку. Обеспечивает масштабируемость и отказоустойчивость. |
| **Session Affinity** | Механизм привязки сессии пользователя к конкретному узлу. В HA-кластере Grafana используется Redis для централизованного хранения сессий, чтобы избежать «липких сессий». |
| **Connection Pool** | Набор соединений с базой данных, переиспользуемых между запросами. В HA-режиме каждый узел имеет собственный пул; размер пула должен учитывать лимиты PostgreSQL. |

## Базовые концепции

### Архитектура "Три столпа"

Надежный HA-кластер Grafana опирается на три независимых слоя хранения данных:

1.  **База данных конфигураций (Configuration Storage):** Хранит дашборды, пользователей и настройки алертов. Допускается только **PostgreSQL** (рекомендуется v15+) или **MySQL**. SQLite в режиме HA не поддерживается из-за ограничений на одновременную запись.
2.  **Удаленный кэш и сессии (Remote Cache):** **Redis Cluster** или **Sentinel** используются для хранения пользовательских сессий. Это позволяет балансировщику распределять запросы в режиме Round Robin без использования "липких сессий" (Sticky Sessions).
3.  **Хранилище артефактов (Object Storage):** Для хранения скриншотов панелей, прикрепляемых к алертам, используются облачные хранилища (**S3**, **GCS**, **Azure Blob**) или общая файловая система (NFS/CephFS).

### Single-Node Evaluation (SNE)

Начиная с версии 13.0, Grafana поддерживает режим **Single-Node Evaluation** для системы оповещений. 
- **Проблема:** В классическом HA каждый узел выполняет все алерты, что создает избыточную нагрузку на источники данных (Prometheus, ClickHouse).
- **Решение:** В режиме SNE кластер выбирает "Primary"-узел (Position 0), который выполняет вычисления, а остальные узлы работают в режиме ожидания или распределенной обработки, получая результаты через Gossip-протокол.

### Жизненный цикл запроса в HA-кластере

Приходящий запрос проходит следующий путь:

1.  **Load Balancer** проверяет доступность узла через `/api/health` (или `/api/live/health`).
2.  **Балансировщик** направляет запрос на любой доступный узел (Round Robin).
3.  **Grafana Node** проверяет сессию в Redis. При наличии валидной сессии обрабатывает запрос.
4.  **Чтение конфигурации:** Дашборд, папки и пользователи загружаются из **PostgreSQL**.
5.  **Запрос к источнику данных:** Если требуется метрика/лог, узел обращается к Prometheus/Loki/etc.
6.  **Рендеринг:** Результат форматируется в HTML/JSON и возвращается пользователю.
7.  **Алертинг (если настроен):** В режиме SNE только Primary (P0) выполняет оценку правил; результат рассылается через Gossip.

### Управление сессиями

В HA-режиме сессии пользователей хранятся в **Redis** (не в локальной памяти). Это позволяет:
- Балансировщику использовать **Round Robin** без Sticky Sessions.
- При отказе узла пользователь автоматически продолжает работу на другом узле без повторной аутентификации.
- Настроить `session.cookie_lifetime` и `session.gc_max_lifetime` для управления временем жизни сессий.

### Синхронизация `secret_key`

Параметр `secret_key` в секции `[security]` используется для:
- Подписи и валидации cookies/JWT.
- Шифрования данных в базе (например, сохраненных паролей источников данных).

**Требование:** Значение должно быть **идентичным и длинным** (рекомендуется 32+ случайных байта) на всех узлах кластера. Несоответствие приводит к невозможности валидации сессий и расшифровки конфигурций.

### Connection Pooling базы данных

Каждый узел Grafana создает собственный пул соединений с PostgreSQL. При конфигурации учитывайте:
- `GF_DATABASE_MAX_OPEN_CONN` (по умолчанию `0` — без лимита, но PostgreSQL накладывает свои ограничения).
- `GF_DATABASE_MAX_IDLE_CONN` (по умолчанию `0` — без ограничения, Grafana управляет автоматически).
- **Формула:** `(пул_на_узел × количество_узлов) < max_connections` PostgreSQL + запас под системные процессы.

### Ключевые компоненты кластера

| Компонент | Роль в системе | Требование к отказоустойчивости |
| :--- | :--- | :--- |
| **Load Balancer** | Точка входа для пользователей и API | L7 (Nginx/HAProxy) с проверкой `/api/health` |
| **Grafana Nodes** | Выполнение логики и рендеринг | Минимум 2 узла (рекомендуется 3 для кворума) |
| **PostgreSQL** | Персистентность настроек | Кластер на базе Patroni или Managed Service |
| **Redis** | Кэширование и сессии | Redis Sentinel или Cluster |
| **Memberlist** | Gossip-протокол (порт 9094) | Открытые порты TCP/UDP между всеми узлами |

## Практические сценарии

### Конфигурация кластера (grafana.ini)

Для сборки HA-кластера необходимо синхронизировать `secret_key` и настроить внешние бэкенды.

```ini
[database]
type = postgres
host = postgres-ha-lb:5432
name = grafana
user = grafana_user
password = grafana_password
# Включает механизмы распределенных блокировок
high_availability = true
# Опционально: ограничение пула соединений на узел
# max_open_conn = 10
# max_idle_conn = 5

[remote_cache]
type = redis
connstr = addr=redis-cluster:6379,pool_size=100,db=0

[session]
provider = redis
provider_config = addr=redis-cluster:6379,pool_size=100,prefix=grafana_sess

[security]
# Должен быть идентичен на всех узлах для валидации Cookie/JWT
secret_key = <long_random_string_from_vault>

[unified_alerting]
enabled = true
# Включение режима Single-Node Evaluation (v13+)
ha_single_node_evaluation = true
# Настройка Gossip-протокола
ha_listen_address = 0.0.0.0:9094
# В K8s используется DNS headless-сервиса
ha_peers = grafana-headless.monitoring.svc.cluster.local:9094
```

### Развертывание в Kubernetes (Helm)

Для production-кластера в Kubernetes требуется минимально 3 реплики с анти-аффинностью и проверками готовности:

```yaml
# grafana-values.yaml
replicas: 3

# Распределение по разным узлам и AZ
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

# Проверки готовности
livenessProbe:
  httpGet:
    path: /api/health
    port: 3000
  initialDelaySeconds: 30
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /api/health
    port: 3000
  initialDelaySeconds: 5
  periodSeconds: 5

# Внешняя PostgreSQL и Redis
database:
  type: postgres
  host: postgres-service.db-namespace:5432
  name: grafana
  existingSecret: grafana-db-secret

grafana.ini:
  remote_cache:
    type: redis
    connstr: addr=redis-service:6379,pool_size=100
  session:
    provider: redis
    provider_config: addr=redis-service:6379,pool_size=100,prefix=grafana_sess
  security:
    secret_key: "${GF_SECURITY_SECRET_KEY}"
  unified_alerting:
    ha_single_node_evaluation: true
    ha_listen_address: 0.0.0.0:9094
    ha_peers: grafana-headless.monitoring:9094
```

### Валидация состояния HA-кластера

После развертывания выполните проверки:

```bash
# 1. Проверка реплик Deployment
kubectl get deployment grafana -n monitoring
# → NAME      READY   UP-TO-DATE   AVAILABLE   AGE
# → grafana   3/3     3            3           2m

# 2. Проверка распределения по зонам (при topologySpreadConstraints)
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana -o wide
# →grafana-xxx-xxxxx   3/3     Running   0          2m   10.0.0.1   node-1   zone-a
# →grafana-xxx-xxxxx   3/3     Running   0          2m   10.0.1.2   node-2   zone-b
# →grafana-xxx-xxxxx   3/3     Running   0          2m   10.0.2.3   node-3   zone-c

# 3. Проверка endpoint /api/health с каждого пода
kubectl exec -n monitoring grafana-xxx-xxxxx -- curl -s http://localhost:3000/api/health
# → {"database":"ok","memory":"ok"}

# 4. Проверка метрик SNE (кто является Primary)
kubectl port-forward svc/grafana -n monitoring 3000:80 &
curl -s http://localhost:3000/metrics | grep grafana_alerting_ha_single_node_evaluation_position
# → grafana_alerting_ha_single_node_evaluation_position{...} 0   # 0 = Primary
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
2. Kubernetes создает новый Pod, ждет готовности (`readinessProbe`).
2.  Старый Pod завершается gracefully.
3. Если проверка `readinessProbe` не проходит на новом поде, обновление останавливается (при `--atomic` выполняется откат).

**Важно:** Не отключайте `readinessProbe` и `livenessProbe` — без них Kubernetes не узнает, что Grafana готова к трафику, и отправит на нее запросы до инициализации.

### Обработка отказа Redis

При падении Redis:
- **Существующие сессии:** пользователи продолжают работать до истечения TTL сессии.
- **Новые сессии:** не создаются, пользователи перенаправляются на аутентификацию.
- **Алертинг:** работает (использует PostgreSQL), но SNE-Gossip может испытывать задержки при большом объеме broadcast.

**Рекомендация:** Используйте Redis Sentinel или Cluster для HA-развертывания кэша.

### Мониторинг и алертинг состояния кластера

Для proactive мониторинга HA-кластера настройте Prometheus-запросы и алерты на основе внутренних метрик Grafana:

**Ключевые метрики (`/metrics`):**

| Метрика | Описание | Алерт |
| :--- | :--- | :--- |
| `grafana_alertmanager_cluster_members` | Количество активных узлов в Gossip-сети | `< 3` при ожидаемых 3 узлах |
| `grafana_alerting_ha_single_node_evaluation_position` | Роль узла (0=Primary, >0=Replica) | Два узла с `position=0` → Split-Brain |
| `grafana_alerting_ha_single_node_evaluation_broadcast_dropped_total` | Отброшено broadcast-сообщений | Рост → увеличить `ha_single_evaluation_alert_broadcast_queue_size` |
| `grafana_http_request_total` | HTTP-запросы по статусам | Рост 5xx → проблема с БД или перегрузка |
| `grafana_db_data_source_usage_total` | Использование источников данных | Аномалии → проблемы с пулом соединений |

**Пример PromQL-запроса для проверки SNE:**

```promql
# Проверка: только один узел должен быть Primary (position=0)
count(grafana_alerting_ha_single_node_evaluation_position == 0) == 1
```

### Устранение неполадок (Troubleshooting)

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Алерты дублируются в HA** | SNE отключен или не настроен `ha_peers` | Включите `ha_single_node_evaluation = true`; проверьте доступность порта 9094/UDP |
| **Split-Brain (два Primary)** | Нечетное число узлов или сетевой partition | Увеличьте количество узлов до 3+; проверьте `ha_peers` и сетевые политики |
| **Сессии сбрасываются** | Redis недоступен или `secret_key` различается | Проверьте `remote_cache` и `security.secret_key` на всех узлах |
| **Ошибка подключения к БД** | Исчерпан пул соединений PostgreSQL | Увеличьте `max_connections` в PostgreSQL; настройте `max_open_conn` в Grafana |
| **`/api/health` возвращает 500** | БД недоступна или миграции не применены | Проверьте доступность PostgreSQL; смотрите логи `logger=database` |
| **Grafana не стартует в K8s** | CrashLoopBackOff | Проверьте readinessProbe, права на PVC, SecurityContext, наличие секрета |
| **Метрики SNE отсутствуют** | Gossip-порт закрыт брандмауэром | Откройте TCP/9094 и UDP/9094 между подами/узлами |
| **Дребезг алертов при обновлении** | Разница времени > 500 мс между узлами | Настройте NTP/Chrony; проверьте `timedatectl status` |

### Рекомендации (Best Practices)

1.  **Количество узлов:** Используйте нечетное число (3 или 5) для кворума. Два узла не дают отказоустойчивости при Split-Brain.
2.  **Секреты:** Храните `secret_key` во внешнем vault (HashiCorp Vault, AWS Secrets Manager). Для HA он должен быть идентичен на всех узлах.
3.  **Пул соединений:** Настройте `max_open_conn` и `max_idle_conn` на стороне Grafana с учетом `max_connections` PostgreSQL. Правило: `(replicas × max_open_conn) < 0.8 × max_connections`.
4.  **Мониторинг:** Настройте алерты на метрики SNE и `cluster_members`. Отсутствие Primary — критичный инцидент.
5.  **Сеть:** Открывайте порт **9094/TCP** (Gossip messages) и **9094/UDP** (discovery) между всеми узлами. В K8s используйте Headless Service.
6.  **Обновления:** Используйте Rolling Update с `readinessProbe`. Никогда не обновляйте все узлы одновременно.
7.  **NTP:** Обязательна синхронизация времени через Chrony/NTPd. Разница > 500 мс приводит к нестабильному алертингу.
8.  **Бэкапы:** Регулярно бэкапируйте PostgreSQL и конфигурации Grafana ( provisioning ). HA защищает от аппаратных сбоев, но не от логических ошибок.

### Граничные случаи (Edge Cases)

*   **SQLite в HA:** Полностью не поддерживается. При попытке запуска нескольких инстансов с SQLite произойдет Corruption базы данных.
*   **Redis Sentinel vs Cluster:** Sentinel подходит для failover мастера; Cluster — для шардирования и больших объемов сессий. Для HA сессий достаточно Sentinel.
*   **Конфигурация 1 МБ в ConfigMap:** В Kubernetes размер ConfigMap ограничен 1 МБ. Для больших дашбордов включите GZIP (`sidecar.dashboards.GZIP: true`) или используйте внешнее хранилище.
*   **Давление кворума (Quorum Loss):** При потере большинства узлов (например, 2 из 3) оставшийся узел перестает выполнять SNE. Восстановление возможно только после возвращения кворума.
*   **Временная drift:** Даже при настроенном NTP возможна дрогнация до нескольких секунд. Для критичных алертов используйте `evaluate_interval` не менее 1 минуты.
*   **Обновление PostgreSQL:** При миграции PostgreSQL major version (например, 15 → 16) остановите все узлы Grafana, обновите БД, затем запускайте узлы последовательно.

**Связанные темы:**
- [Резервное копирование и восстановление](./grafana_backup_restore.md) — бэкап БД и конфигурации Grafana
- [Обновление и миграция](./grafana_upgrade_migration.md) — обновление версий и смена СУБД

## Дополнительная информация

### Рекомендации по эксплуатации

- **Синхронизация времени:** Разница во времени между узлами более 500 мс гарантированно приводит к "дребезгу" алертов и дублированию уведомлений. Использование NTP/Chrony обязательно.
- **Split-Brain:** Для предотвращения ситуации, когда два узла считают себя Primary, всегда используйте нечетное количество узлов (3 и более) и надежное DNS-имя для `ha_peers`.
- **База данных:** PostgreSQL является единственным источником истины. Убедитесь, что лимит соединений (`max_connections`) на стороне СУБД достаточен для всех узлов Grafana с учетом их пулов соединений.
- **Сетевая доступность:** Порт **9094** должен быть доступен по **TCP** (для надежной передачи) и **UDP** (для gossip-трафика).

**См. также:**
- [Grafana: Обзор](./grafana_overview.md)
- [Обзор High Availability](../Concepts/High_Availability/ha_overview.md)
- [PostgreSQL HA: Обзор](../Databases/PostgreSQL/Concepts/high_availability.md)
