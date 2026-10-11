# Redis: высокая доступность (Sentinel и Cluster)

**Актуально для:** Redis 7.4–8.2, Valkey 8.1.x

## Определения

**Высокая доступность (HA)** — свойство системы обеспечивать непрерывную работу при отказе отдельных компонентов. В контексте Redis HA достигается за счет репликации и автоматического failover.

**Sentinel** — отдельный процесс мониторинга, который отслеживает состояние мастер-реplica пар, выполняет автоматический failover и предоставляет клиентам актуальный адрес мастера.

**Redis Cluster** — встроенное решение для шардирования на стороне сервера и HA, которое распределяет данные по множеству мастер-нод с автоматической репликацией.

**Replica** — асинхронная копия мастера, которая получает изменения через репликационный поток. Может обслуживать read-запросы.

**Failover** — процесс переключения клиентов с недоступного мастера на реплику вручную или автоматически.

**Split-brain** — состояние, при котором две ноды считают себя мастером из-за сетевого разделения. Может привести к потере данных.

**Quorum** — большинство голосов Sentinel-нод, необходимое для принятия решения о failover. Гарантирует, что решение принимается только при реальном отказе мастера.

## Предварительные требования

### Аппаратные и программные требования

- **Redis 7.4+ / Valkey 8.1+:** механизм репликации и Sentinel стабилен в этих версиях. Redis 7.4 (июль 2024, security support до декабря 2029), Redis 8.2 (август 2025, security support до сентября 2030), Valkey 8.1.10 (август 2026).
- **ОС:** Linux 4.x+ с systemd для управления сервисами.
- **Память:** минимум 2 GB RAM для dev; для production рассчитывайте по формуле: `RAM = (средний размер ключа × количество ключей) × 1.5` (с overhead).
- **Сеть:** задержка между нодами < 1 мс внутри дата-центра. При междатацентровом доступе (>5 мс) репликация становится узким местом.
- **NTP:** синхронизация времени обязательна для предотвращения clock drift при проверке сроков репликации.
- **Диски:** используйте отдельные диски для RDB/AOF файлов и данных, чтобы избежать IO contention.

### Топология развертывания

| Режим | Минимальная конфигурация | Use case |
| :--- | :--- | :--- |
| **Sentinel** | 1 мастер + 1 реплика + 3 Sentinel | HA для одного инстанса |
| **Cluster** | 3 мастера + 3 реплики | Шардирование + HA |
| **Standalone с репликой** | 1 мастер + 1 реплика | Read scaling без HA |

### Требования к клиентам

- Используйте клиенты с поддержкой Sentinel или Cluster: `redis-py` 3.0+, `go-redis` 9.0+, `ioredis` 5.0+.
- Настройте `tcp-keepalive 300` и `socket-timeout` для предотвращения зависших соединений.
- Реализуйте reconnect с экспоненциальным backoff.
- Для Cluster: используйте smart clients с кэшированием slot mapping.

## Основные концепции

### Redis Sentinel

Sentinel — это отдельный режим работы Redis, который выполняет три функции:
1. Мониторинг — постоянно проверяет доступность мастер-ноды
2. Автоматический failover — переключает реплику в режим мастера при отказе
3. Конфигурация — предоставляет клиентам актуальный адрес мастера

#### Архитектура

Sentinel работает как cluster из 3 или 5 процессов. Рекомендуется использовать нечетное количество для избежания deadlock при голосовании.

**Минимальная конфигурация:** 3 Sentinel-ноды (2 могут упасть — quorum=2 все равно работает)
**Production-конфигурация:** 5 Sentinel-нод (quorum=3)

#### Алгоритм failover

1. Sentinel обнаруживает, что мастер недоступен (`subjectively down`)
2. Достигается quorum голосов (`objectively down`)
3. Sentinel выбирает лучшую реплику по приоритету и репликационному offset
4. Новая реплика повышается до мастера
5. Остальные реплики переключаются на нового мастера
6. Клиенты получают обновленную конфигурацию

### Redis Cluster

Redis Cluster — это полностью децентрализованная архитектура без единой точки отказа.

#### Характеристики

- **Master-Replica:** каждый мастер имеет 1+ реплик
- **Автоматический failover:** при отказе мастера одна из реплик повышается автоматически
- **Шардирование на стороне сервера:** данные распределяются по 16384 слотам
- **Без прокси:** клиенты подключаются напрямую к нодам
- **Gossip protocol:** ноды обмениваются метаинформацией через PING/PONG/SEND/ASK

#### Шардирование данных

Каждый ключ принадлежит одному из 16384 слотов. Слоты распределяются по мастер-нодам. Клиент вычисляет slot для ключа через `CRC16(key) mod 16384`.

#### Репликация

Каждая реплика асинхронно получает изменения от своего мастера. При failover новая реплика повышается до мастера и берет на себя его слоты.

#### Гарантии согласованности

Redis Cluster обеспечивает **согласованность в конечном счете**. В момент failover часть write-запросов может быть потеряна из-за асинхронной репликации. Для защиты от потерь можно использовать команду `WAIT`.

### Сравнение Sentinel и Cluster

| Аспект | Sentinel | Cluster |
| :--- | :--- | :--- |
| **Шардирование** | Нет | Да (16384 slots) |
| **Масштабирование** | Вертикальное | Горизонтальное |
| **Количество мастеров** | 1 | 3+ |
| **Сложность** | Средняя | Высокая |
| **Клиентская библиотека** | Нужна поддержка Sentinel | Нужна поддержка Cluster |
| **Failover** | Автоматический | Автоматический |
| **Окно потери данных** | ~1-2 секунды | ~1-2 секунды |
| **Рекомендуемое применение** | HA для одного инстанса | Масштабирование и HA |

### Политики репликации

**Синхронная репликация:** запись считается завершенной только после подтверждения от реплики. Гарантирует zero data loss, но снижает производительность.

**Асинхронная репликация:** запись подтверждается немедленно, реплика получает изменения позже. Минимальная латентность, но возможна потеря данных при отказе мастера до фиксации на реплике.

**Команда WAIT:** позволяет приложению ждать подтверждения от N реплик перед завершением write-операции. Компромисс между производительностью и надежностью.

## Пошаговая настройка окружения

### Шаг 1: Подготовка инфраструктуры

Создайте 6 серверов (3 мастера + 3 реплики) или 3 сервера (1 мастер + 2 реплики) + 3 Sentinel.

**Требования к сети:**
- Dedicated NIC для replication трафика при >100K операций/сек
- Firewall: открытые порты 6379, 6380, 6381 (данные) и 26379 (Sentinel)
- NTP синхронизация на всех нодах

**Валидация:**
```bash
# Проверка сетевой связности
ping -c 3 10.0.0.10
# → 0% packet loss

# Проверка открытых портов
nc -zv 10.0.0.10 6379
# → Connection succeeded

# Проверка NTP
chronyc tracking
# → System time: ...
```

### Шаг 2: Настройка репликации

На каждой ноде создайте конфигурацию с уникальным `port` и общим `cluster-config-file`:

```conf
port 6379
cluster-enabled yes
cluster-config-file nodes.conf
cluster-node-timeout 5000
appendonly yes
```

**Валидация:**
```bash
# Запуск ноды
redis-server /etc/redis/6379.conf

# Проверка статуса
redis-cli -p 6379 INFO cluster
# → cluster_enabled:1

# Проверка узла
redis-cli -p 6379 CLUSTER NODES
# → Список нод (пока только себя)
```

### Шаг 3: Создание кластера

Инициализируйте кластер с 3 мастерами и 1 репликой на каждого:

```bash
redis-cli --cluster create \
  10.0.0.10:6379 \
  10.0.0.10:6380 \
  10.0.0.10:6381 \
  10.0.0.20:6379 \
  10.0.0.20:6380 \
  10.0.0.20:6381 \
  --cluster-replicas 1
```

**Валидация:**
```bash
redis-cli -p 6379 CLUSTER INFO
# → cluster_state:ok

redis-cli -p 6379 CLUSTER NODES
# → 6 нод, 3 мастера, 3 реплики
```

### Шаг 4: Настройка Sentinel (опционально)

Для HA одного инстанса или мониторинга кластера:

```conf
# /etc/redis/sentinel.conf
port 26379
sentinel monitor mymaster 10.0.0.10 6379 2
sentinel auth-pass mymaster <sentinel_password>
sentinel down-after-milliseconds mymaster 5000
sentinel failover-timeout mymaster 60000
sentinel parallel-syncs mymaster 1
logfile /var/log/redis/sentinel.log
```

**Валидация:**
```bash
# Запуск Sentinel
redis-server /etc/redis/sentinel.conf --sentinel

# Проверка quorum
redis-cli -p 26379 SENTINEL ckquorum mymaster
# → OK 3 usable Sentinels
```

### Шаг 5: Настройка клиентов

Настройте клиентские приложения для работы с Sentinel или Cluster:

**Python (Sentinel):**
```python
from redis.sentinel import Sentinel

sentinel = Sentinel([
    ('10.0.0.10', 26379),
    ('10.0.0.20', 26379),
    ('10.0.0.30', 26379)
], socket_timeout=0.5)

master = sentinel.master_for('mymaster', socket_timeout=0.5)
master.set('key', 'value')
```

**Валидация:**
```bash
# Тест записи
python3 -c "from redis.sentinel import Sentinel; s = Sentinel([('10.0.0.10', 26379)], socket_timeout=0.5); print(s.master_for('mymaster').set('test', 'ok'))"
# → True

# Тест чтения с реплики
python3 -c "from redis.sentinel import Sentinel; s = Sentinel([('10.0.0.10', 26379)], socket_timeout=0.5); print(s.slave_for('mymaster').get('test'))"
# → b'ok'
```

## Практические сценарии

### Конфигурация Redis Sentinel

**sentinel.conf:**
```conf
# Мониторинг мастера
sentinel monitor mymaster 10.0.0.10 6379 2
sentinel auth-pass mymaster <sentinel_password>

# Таймауты
sentinel down-after-milliseconds mymaster 5000
sentinel failover-timeout mymaster 60000
sentinel parallel-syncs mymaster 1

# Порт
port 26379

# Логирование
logfile /var/log/redis/sentinel.log
```

**Запуск:**
```bash
# Запуск 3 Sentinel-нод
redis-server /etc/redis/sentinel.conf --sentinel
```

**Проверка статуса:**
```bash
redis-cli -p 26379 SENTINEL masters
# → mymaster 10.0.0.10 6379 [...]

redis-cli -p 26379 SENTINEL get-master-addr-by-name mymaster
# → 10.0.0.10 6379

redis-cli -p 26379 SENTINEL replicas mymaster
# → Показывает все реплики
```

**Валидация:**
```bash
# Проверка quorum
redis-cli -p 26379 SENTINEL ckquorum mymaster
# → OK 3 usable Sentinels

# Проверка конфигурации
redis-cli -p 26379 SENTINEL get-master-addr-by-name mymaster
# → Актуальный адрес мастера

# Проверка реплик
redis-cli -p 26379 SENTINEL replicas mymaster
# → Список всех реплик с состоянием
```

### Конфигурация Redis Cluster (6 нод: 3 мастера + 3 реплики)

**redis.conf (мастер-нода 1):**
```conf
port 6379
cluster-enabled yes
cluster-config-file nodes-6379.conf
cluster-node-timeout 5000
appendonly yes
```

**Запуск кластера:**
```bash
# Запуск 6 нод
for port in 6379 6380 6381 6382 6383 6384; do
  redis-server /etc/redis/${port}.conf
done

# Создание кластера
redis-cli --cluster create \
  10.0.0.10:6379 \
  10.0.0.10:6380 \
  10.0.0.10:6381 \
  10.0.0.20:6379 \
  10.0.0.20:6380 \
  10.0.0.20:6381 \
  --cluster-replicas 1
```

**Проверка статуса:**
```bash
redis-cli -p 6379 CLUSTER INFO
# → cluster_state:ok

redis-cli -p 6379 CLUSTER NODES
# → Показывает все ноды и их роли

redis-cli -p 6379 CLUSTER FAILOVER
# → Ручной failover (требует подтверждения)
```

**Валидация:**
```bash
# Проверка состояния кластера
redis-cli -p 6379 CLUSTER INFO
# → cluster_state:ok
# → cluster_known_nodes:6
# → cluster_size:3

# Проверка распределения slots
redis-cli --cluster check 10.0.0.10:6379
# → [OK] All nodes agree about slots configuration

# Проверка репликации
redis-cli -p 6379 INFO replication
# → role:master
# → connected_slaves:1
```

### Failover testing

**Sentinel:**
```bash
# Остановка мастера
redis-cli -p 6379 SHUTDOWN NOSAVE

# Проверка нового мастера
sleep 10
redis-cli -p 26379 SENTINEL get-master-addr-by-name mymaster
# → Новый адрес мастера
```

**Валидация:**
```bash
# Проверка нового мастера
redis-cli -p 26379 SENTINEL get-master-addr-by-name mymaster
# → Адрес, отличный от упавшего мастера

# Проверка роли
redis-cli -p <new_master_port> INFO replication
# → role:master

# Проверка переподключения клиентов
redis-cli -p <new_master_port> PING
# → PONG
```

**Cluster:**
```bash
# Просмотр slot distribution
redis-cli -p 6379 CLUSTER SLOTS

# Имитация отказа мастера
redis-cli -p 6380 CLUSTER FAILOVER

# Проверка нового мастера
redis-cli -p 6379 CLUSTER NODES | grep master
```

**Валидация:**
```bash
# Проверка состояния кластера
redis-cli -p 6379 CLUSTER INFO
# → cluster_state:ok

# Проверка новых мастеров
redis-cli -p 6379 CLUSTER NODES | grep master
# → Список мастер-нод, включая повышенную реплику

# Проверка целостности данных
redis-cli -p 6379 CLUSTER CHECK
# → [OK] All nodes agree about slots configuration
```

### Реbalancing кластера

```bash
# Перенос slot с одной ноды на другую
redis-cli --cluster reshard 10.0.0.10:6379

# Или автоматическое распределение
redis-cli --cluster rebalance 10.0.0.10:6379
```

### Использование в приложении

**Python (Sentinel):**
```python
from redis.sentinel import Sentinel

sentinel = Sentinel([
    ('10.0.0.10', 26379),
    ('10.0.0.20', 26379),
    ('10.0.0.30', 26379)
], socket_timeout=0.5)

# Получение мастера
master = sentinel.master_for('mymaster', socket_timeout=0.5)
master.set('key', 'value')

# Получение реплики
replica = sentinel.slave_for('mymaster', socket_timeout=0.5)
replica.get('key')
```

**Python (Cluster):**
```python
from rediscluster import RedisCluster

startup_nodes = [
    {'host': '10.0.0.10', 'port': 6379},
    {'host': '10.0.0.10', 'port': 6380},
]

cluster = RedisCluster(startup_nodes=startup_nodes, decode_responses=True)
cluster.set('key', 'value')
cluster.get('key')
```

## Ограничения и крайние случаи

### Сетевые разрывы (network partition)

При разделении сети группа нод может потерять связь с большинством. Поведение:
- **Sentinel:** ноды без quorum не могут выполнить failover, старый мастер продолжает принимать writes (если еще доступен), что приводит к split-brain.
- **Cluster:** ноды без большинства голосов переходят в `fail` state и отклоняют writes, предотвращая split-brain.

**Решение:** используйте `cluster-require-full-coverage no` для минимизации impact, но понимайте риск расхождений.

### Частичный отказ кластера

При отказе 1-2 мастеров в кластере из 3+ нод:
- Слоты отказавших мастеров становятся недоступными
- Клиенты получают `MOVED` или `ASK` ошибки
- Данные на этих слотах недоступны до failover

**Решение:** увеличьте количество мастеров до 5+ для повышения отказоустойчивости.

### Потеря данных при failover

Асинхронная репликация имеет окно потери данных ~1-2 секунды. При отказе мастера:
- Write, не реплицированный на реплику, теряется
- Клиент может получить `MOVED` после записи на старом мастере

**Решение:** используйте `WAIT` команду для критичных writes.

### Смешанные версии в кластере

Запуск нод разных версий Redis/Valkey в одном кластере не поддерживается. При обновлении:
- Используйте rolling upgrade с остановкой по одной ноде
- Проверяйте совместимость протокола между версиями

### Высокая нагрузка на Gossip-протокол

При >100K операций/сек gossip-трафик может создавать нагрузку на сеть:
- Ноды обмениваются PING/PONG/SEND/ASK каждые несколько секунд
- Большие кластеры (>100 нод) увеличивают overhead

**Решение:** используйте Cluster с меньшим количеством мастеров или разделите на несколько кластеров.

### Sentinels и Cluster в одной среде

Не смешивайте Sentinel и Cluster мониторинг для одних и тех же данных. Используйте либо Sentinel для standalone/single-master, либо Cluster для multi-master.

## Лучшие практики

### Архитектура и проектирование
- Используйте 3 или 5 Sentinel-нод для HA одного инстанса
- Для шардирования используйте Redis Cluster с минимум 3 мастерами
- Размещайте мастер и его реплики на разных зонах доступности
- Используйте `cluster-require-full-coverage no` для минимизации impact при частичном отказе

### Надежность
- Настройте `replica-serve-stale-data no` для предотвращения обслуживания устаревших данных
- Используйте `min-replicas-to-write 1` для защиты от потерь данных
- Настройте `replica-priority` для контроля порядка failover
- Используйте `client-reconnect-delay` в клиентах для автоматического переподключения

### Производительность
- Размещайте реплики на тех же хостах, что и мастеры, для снижения латентности
- Используйте read-реплики для разгрузки read-запросов
- Настройте `cluster-announce-ip` и `cluster-announce-port` для корректной работы за NAT
- Используйте пул соединений в клиентах для минимизации overhead

### Безопасность
- Настройте ACL для Sentinel и Cluster нод
- Используйте TLS для шифрования репликационного трафика
- Ограничьте доступ к Sentinel-порту (26379) firewall
- Используйте `requirepass` и `masterauth` в репликах

### Эксплуатация
- Настройте мониторинг: `redis_up`, `redis_connected_clients`, `redis_repl_offset_diff`
- Тестируйте failover регулярно: `redis-cli -p 26379 SENTINEL FAILOVER mymaster`
- Используйте `redis-cli --cluster check` для проверки целостности кластера
- Настройте алерты на `RedisReplicationLag` и `RedisDown`

## Устранение неисправностей

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Split-brain | Две ноды считают себя мастером | `redis-cli CLUSTER NODES` | Настройте `cluster-require-full-coverage no` |
| Высокая задержка репликации | Сетевая задержка или перегрузка мастера | `redis-cli INFO replication` | Увеличите `repl-backlog-size`, оптимизируйте сеть |
| Failover не происходит | Недостаточно Sentinel-голосов | `redis-cli -p 26379 SENTINEL ckquorum` | Увеличьте количество Sentinel-нод |
| Cluster red | Один или несколько slots не покрыты | `redis-cli CLUSTER INFO` | Переназначьте slots на доступные мастера |
| Миграция слотов зависает | Большие ключи или сетевые проблемы | `redis-cli --cluster check` | Разбейте большие ключи, проверьте сеть |
| Client получает MOVED/ASK | Клиент не поддерживает Cluster | Логи клиента | Обновите клиентскую библиотеку |
| Повторяющийся failover | Нестабильная сеть или перегрузка мастера | `redis-cli INFO replication` | Увеличьте `down-after-milliseconds`, оптимизируйте сеть |
| Реплика не подключается | Аутентификация или ACL отключены | `redis-cli INFO replication` | Настройте `requirepass` и `masterauth` |
| Cluster stuck in loading | Перезагрузка ноды или большая репликация | `redis-cli CLUSTER NODES` | Дождитесь завершения загрузки или перезапустите ноду |
| Ошибка BUSY при resharding | Ключи изменяются во время миграции | `redis-cli --cluster check` | Повторите resharding с `--cluster-yes` |

## Очистка и восстановление

### Остановка и отключение Sentinel

```bash
# Остановка Sentinel-сервиса
systemctl stop redis-sentinel
systemctl disable redis-sentinel

# Удаление конфигурации
rm /etc/redis/sentinel.conf
rm -rf /var/lib/redis/sentinel/
```

### Остановка и отключение Cluster

```bash
# Остановка всех нод
for port in 6379 6380 6381 6382 6383 6384; do
  redis-cli -p $port SHUTDOWN NOSAVE
done

# Удаление конфигурации
rm /etc/redis/*.conf
rm -rf /var/lib/redis/
```

### Восстановление после сбоя

Если мастер упал и не восстанавливается:

```bash
# 1. Принудительный failover Sentinel
redis-cli -p 26379 SENTINEL FAILOVER mymaster

# 2. Проверка нового мастера
redis-cli -p 26379 SENTINEL get-master-addr-by-name mymaster
# → Новый адрес мастера

# 3. Если Sentinel не работает, ручное повышение реплики
redis-cli -p 6380 SLAVEOF NO ONE
redis-cli -p 6380 CLUSTER FAILOVER
```

### Восстановление конфигурации после перезагрузки

```bash
# Проверка автозапуска сервисов
systemctl is-enabled redis-server
systemctl is-enabled redis-sentinel

# Проверка статуса
redis-cli -p 26379 PING
# → PONG

redis-cli -p 6379 CLUSTER INFO
# → cluster_state:ok
```

### Очистка устаревших конфигураций

```bash
# Проверка старых конфигураций
find /etc/redis -name "*.conf" -mtime +30

# Проверка устаревших PID-файлов
find /var/run/redis -name "*.pid"

# Очистка старых логов
find /var/log/redis -name "*.log" -mtime +7 -delete
```

## Дополнительная информация

### Взаимодействие с операционной системой

- **NUMA:** на multi-socket серверах размещайте мастер и его реплики на одном NUMA-узле
- **THP:** отключайте Transparent Huge Pages для Redis: `echo never > /sys/kernel/mm/transparent_hugepage/enabled`
- **TCP:** настройте `net.core.somaxconn=65535` и `net.ipv4.tcp_keepalive_time=300`
- **OOM:** используйте `vm.overcommit_memory=1` (официальная рекомендация Redis) для предотвращения ошибок fork при снапшотах и AOF-rewrite

### Мониторинг и алертинг

**Ключевые метрики (Prometheus/Grafana):**

| Метрика | Источник | Описание | Алерт |
| :--- | :--- | :--- | :--- |
| `redis_up` | `PING` | Доступность Redis | = 0 |
| `redis_connected_clients` | `INFO clients` | Количество активных соединений | > 1000 |
| `redis_repl_offset_diff` | `INFO replication` | Задержка репликации | > 10000 |
| `redis_evicted_keys_total` | `INFO stats` | Вытеснение ключей | Рост > 100/мин |
| `redis_keyspace_hit_ratio` | `INFO stats` | Эффективность кэширования | < 80% |
| `redis_blocked_clients` | `INFO clients` | Заблокированные клиенты | > 10 |
| `redis_instantaneous_ops_per_sec` | `INFO stats` | Операций в секунду | Резкий рост/падение |
| `redis_mem_used_bytes` | `INFO memory` | Потребление памяти | Рост без очистки |
| `sentinel_master_down_since_seconds` | `SENTINEL masters` | Время недоступности мастера | > 5 сек |
| `sentinel_known_slaves` | `SENTINEL replicas` | Количество известных реплик | < 1 |

**Команды для ручной проверки:**
```bash
# Статус Sentinel
redis-cli -p 26379 SENTINEL masters
redis-cli -p 26379 SENTINEL ckquorum mymaster

# Статус Cluster
redis-cli -p 6379 CLUSTER INFO
redis-cli -p 6379 CLUSTER NODES

# Проверка репликации
redis-cli -p 6379 INFO replication
# → role:master
# → connected_slaves:1

# Проверка задержки репликации
redis-cli -p 6379 INFO replication | grep offset
# → master_repl_offset:12345
# → slave_repl_offset:12340
# → diff: 5 (норма: < 10)
```

**Пример алертов (Prometheus Alertmanager):**
```yaml
groups:
  - name: redis_ha_alerts
    rules:
      - alert: RedisReplicationLag
        expr: redis_repl_offset_diff > 10000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Задержка репликации Redis"
          description: "Разница offset: {{ $value }}."

      - alert: RedisDown
        expr: redis_up == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Redis {{ $labels.instance }} недоступен"

      - alert: RedisHighEvictions
        expr: rate(redis_evicted_keys_total[5m]) > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокое вытеснение ключей"
          description: "{{ $value }} ключей/сек."

      - alert: RedisClusterRed
        expr: redis_cluster_known_nodes - redis_cluster_masters < 3
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Cluster red"
          description: "Доступно мастер-нод: {{ $value }}."
```

### Связанные темы

- [Обзор Redis](../../Databases/redis_overview.md) — архитектура и возможности
- [Redis vs Memcached](../../Databases/redis_vs_memcached.md) — сравнение систем кэширования
- [Обзор кэширования](./caching_overview.md) — уровни и метрики
- [Паттерны кэширования](./caching_patterns.md) — стратегии взаимодействия
- [Redis Exporter](../../Prometheus/Exporters/redis_exporter.md) — мониторинг
