# Grafana: Высокая доступность

## Определения

**Высокая доступность (High Availability, HA)** в Grafana — архитектурное решение, обеспечивающее непрерывную работу системы визуализации и алертинга при отказе одного или нескольких узлов. 

**Ключевые принципы реализации:**
- **Stateless-узлы:** Все запущенные экземпляры Grafana идентичны и не хранят уникальное состояние локально.
- **Разделяемое состояние (Shared State):** Использование внешних отказоустойчивых систем для хранения конфигураций, сессий и кэша.
- **Дедупликация алертов:** Межсерверная коммуникация для предотвращения отправки повторяющихся уведомлений.

**Текущая версия (август 2026):** Grafana 13.1.x.

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

### Мониторинг здоровья HA-кластера

Для отладки и мониторинга состояния кластера используются внутренние метрики Grafana (экспортируются на `/metrics`):

- `grafana_alertmanager_cluster_members` — количество активных узлов в Gossip-сети.
- `grafana_alerting_ha_single_node_evaluation_position` — роль узла (0 — Primary, выполняющий алерты).
- `grafana_alerting_ha_single_node_evaluation_broadcast_dropped_total` — индикатор перегрузки очереди широковещательных сообщений (сигнал к увеличению `ha_single_evaluation_alert_broadcast_queue_size`).

### Развертывание в Docker Compose

Пример минимального HA-стека для тестирования:

```yaml
services:
  grafana-node-1: &grafana_template
    image: grafana/grafana:13.1.x
    environment:
      - GF_DATABASE_TYPE=postgres
      - GF_DATABASE_HOST=db:5432
      - GF_SECURITY_SECRET_KEY=supersecret
      - GF_REMOTE_CACHE_TYPE=redis
      - GF_REMOTE_CACHE_CONNSTR=addr=redis:6379
      - GF_UNIFIED_ALERTING_HA_PEERS=grafana-node-2:9094
    ports: [ "3001:3000" ]

  grafana-node-2:
    <<: *grafana_template
    environment:
      - GF_UNIFIED_ALERTING_HA_PEERS=grafana-node-1:9094
    ports: [ "3002:3000" ]

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: grafana

  redis:
    image: redis:7-alpine
```

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
