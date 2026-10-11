# Redis против Memcached: архитектурное сравнение

**Актуально для:** Redis 8.6–8.10 (latest stable 8.10.2, 2026-09-17) / Memcached 1.6.x (latest 1.6.45); Valkey 9.1.x

## Определения

**Redis (Remote Dictionary Server)** и **Memcached** — ведущие in-memory хранилища «ключ-значение». Оба снижают нагрузку на основные БД, но различаются по ширине возможностей: Redis — мультимодальная платформа (хэши, списки, множества, sorted sets, Streams, JSON, Time Series, поиск), Memcached — специализированный кэш простых пар «ключ-значение».

**Лицензии и форки:**

| Проект | Лицензия | Примечание |
| :--- | :--- | :--- |
| Redis 7.2 и ранее | BSD-3-Clause | исторические релизы |
| Redis 7.4–7.8 | RSALv2 / SSPLv1 | с марта 2024 |
| Redis 8.0+ | RSALv2 / SSPLv1 / AGPLv3 | тройная лицензия; AGPLv3 — OSI-approved |
| Valkey 9.1.x | BSD-3-Clause | форк Redis 7.2.4 (Linux Foundation, 2024); drop-in замена, текущая 9.1.2 |
| Redict | LGPL-3.0-only | форк Redis 7.2.4 (независимый проект) |
| Memcached | BSD-3-Clause | полностью открыт, отсутствие лицензионных рисков |

Коммерческий self-hosted продукт — **Redis Software** (бывший Redis Enterprise): on-prem, аудит команд, FIPS 140-3, LDAP, Active-Active. Управляемые облачные сервисы в этой статье не рассматриваются.

## Основные концепции

### Сравнение технических характеристик

| Аспект | Redis 8.x | Memcached 1.6+ |
| :--- | :--- | :--- |
| **Архитектура потоков** | Reactor: команды последовательно в основном потоке + Threaded I/O (с 6.0) | **Полная многопоточность** (SMP), worker threads |
| **Модель данных** | Структуры: строки, хэши, списки, множества, sorted sets, Streams, JSON, Time Series | Простые пары «ключ-значение» (blob) |
| **Протокол** | RESP2 (default) / RESP3 (`HELLO 3`), pipelining | Text и **Meta-протокол** (binary deprecated) |
| **Управление памятью** | Аллокатор `jemalloc`, аппроксимированный LRU/LFU | **Slab allocator**. Segmented LRU (SLRU) |
| **Персистентность** | RDB, **multi-part AOF** (7.0+), `BACKUP` (8.10) | Отсутствует (Extstore — SSD-расширение кэша, не persistence) |
| **HA / failover** | Sentinel (автоматический), Cluster (шардирование + failover) | Нет встроенного; client-side consistent hashing или прокси **mcp** |
| **Масштабирование** | Cluster: 16384 hash slots, online resharding | Горизонтальное: добавление узлов + ketama; mcp (Lua, 1.6.23+) |
| **Размер значения** | До 512 МБ | До 1 МБ (настраивается `-I` до 1 ГБ) |
| **TTL** | На ключ, ms-точность (`PEXPIRE`), без ограничения сверху | Секунды, макс. 30 дней (2592000); **> 30 дней = Unix-timestamp** |
| **Безопасность** | **ACL v2** (пользователи, ключи, команды), TLS 1.2/1.3 | TLS (с 1.5.13), SASL (`-S`, compile-time) |

### Глубокий анализ архитектурных различий

#### Модель выполнения: Reactor vs SMP
- **Redis (Reactor Pattern):** все команды выполняются последовательно в основном потоке. Это гарантирует атомарность без мьютоксов, что критично для сложных структур. Многопоточность (с 6.0) — сетевой I/O и фоновая очистка (lazy free: `UNLINK`, `FLUSHDB ASYNC`). Следствие: тяжёлая команда O(N) блокирует всех клиентов инстанса.
- **Memcached (SMP):** полностью многопоточное приложение. Каждый worker thread обрабатывает свои соединения, конкурируя за доступ к хеш-таблице через гранулярные блокировки. Линейный масштаб с ростом числа ядер; `-t` ≈ числу ядер (64+ не рекомендуются).

#### Управление памятью: динамика vs слабы
- **Redis (jemalloc):** выделение по требованию — гибкость для объектов разного размера, но возможна внешняя фрагментация (`activedefrag yes`, требует jemalloc). Накладные расходы на ключ: ~50–100+ байт (redisObject + dictEntry + SDS) — мелкие ключи неэффективны. Redis 8.10 добавил **compact hashes** — до 50% экономии памяти для хэшей с общей схемой полей (`HIMPORT` для bulk-загрузки).
- **Memcached (Slab Allocation):** память делится на страницы (1 МБ) и чанки фиксированных размеров (`-f` 1.25, `-n` 48). Внешняя фрагментация исключена, но возможна внутренняя (объект меньше чанка «округляется» вверх). Накладные расходы: 48 байт минимум.

#### Алгоритмы вытеснения
- **Redis:** аппроксимированный LRU/LFU на основе сэмплирования (`maxmemory-samples`, default 5). Политики `maxmemory-policy`: `noeviction`, `allkeys-lru`, `volatile-lru`, `allkeys-lfu`, `volatile-lfu`, `allkeys-random`, `volatile-random`, `volatile-ttl`.
- **Memcached (SLRU, default с 1.5.0):** HOT/WARM (каждый кап 32% памяти slab) / COLD / TEMP (TTL ≤ 61 с, не вытесняется). Защищает «горячие» данные от вытеснения при массовых разовых обращениях.

#### Персистентность и высокая доступность
- **Redis:** RDB (снапшоты, fork + copy-on-write), AOF (fsync: `always`/`everysec`/`no`), multi-part AOF (7.0+: base + инкрементальные файлы), `BACKUP` (8.10, node-side на базе MP-AOF). Sentinel — автоматический failover (обнаружение — десятки секунд); Cluster — 16384 слотов, failover на уровне шардов, online resharding (`CLUSTER SETSLOT`).
- **Memcached:** персистентности нет — кэш по дизайну volatile. Extstore выносит тела объектов на SSD, но это расширение кэша, а не durable storage. Отказ узла = потеря его доли кэша: при consistent hashing пересчитывается только часть ключей; прокси mcp обеспечивает маршрутизацию и fallback между пулами.

## Практические сценарии

### Когда выбирать Memcached
- **Экстремальные нагрузки на чтение:** системы с миллионами RPS на простых ключах-значениях.
- **Огромные объёмы кэша (ТБ+):** Extstore хранит тела объектов на SSD/NVMe, используя RAM только для метаданных — радикально дешевле чистой RAM.
- **Сверхнизкие задержки:** минимальная обработка на сервере без накладных расходов на парсинг сложных структур.
- **Проксирование трафика:** сложная балансировка и маршрутизация кэша через **mcp (Lua)**.

### Когда выбирать Redis
- **Сложная бизнес-логика:** атомарные манипуляции с частями объекта (инкремент поля хэша, `ZADD`/`ZRANGE`, `SETNX`).
- **Очереди и стриминг:** Streams с группами потребителей — надёжная шина сообщений.
- **Pub/Sub** (в т.ч. sharded, 7.0+), rate limiting, лидерборды (sorted sets), распределённые блокировки.
- **Состояние сессий:** где важны персистентность (RDB/AOF) и высокая доступность (Sentinel/Cluster).
- **Документы JSON и Time Series** нативно (в 8.x модули консолидированы в ядро).

### Матрица выбора решения

| Требование | Redis 8.x | Memcached 1.6+ |
| :--- | :--- | :--- |
| Простое кеширование строк | Да | **Предпочтительно (SLRU, SMP)** |
| Масштабирование на терабайты (SSD) | Сложно | **Да (Extstore)** |
| Документы JSON / Time Series | **Да (нативно)** | Нет |
| Очереди задач / Streams / Pub-Sub | **Да** | Нет |
| Сохранение на диск (persistence) | **Да (RDB/AOF/MP-AOF)** | Нет (Extstore — не persistence) |
| Автоматический failover | **Да (Sentinel/Cluster)** | Нет (client-side) |
| Многопоточная утилизация CPU | Высокая (I/O threads) | **Экстремальная (SMP)** |
| Лицензия без рисков | AGPLv3 (8.0+) или Valkey (BSD) | **BSD-3-Clause** |

## Операции и команды (мониторинг)

```bash
# Redis: ключевые секции INFO
redis-cli INFO stats | egrep "keyspace_hits|keyspace_misses|evicted_keys|instantaneous_ops_per_sec"
redis-cli INFO memory | egrep "used_memory_human|used_memory_rss_human|mem_fragmentation_ratio"
redis-cli INFO clients | egrep "connected_clients|blocked_clients"
redis-cli SLOWLOG GET 10        # медленные команды
redis-cli CLUSTER INFO          # состояние кластера

# Memcached
echo "stats" | nc 127.0.0.1 11211 | egrep "get_hits|cmd_get|evictions|listen_disabled_num"
memcached-tool 127.0.0.1:11211 display   # slab-классы
memcached-tool 127.0.0.1:11211 stats
```

| Метрика | Redis | Memcached |
| :--- | :--- | :--- |
| Hit rate | `keyspace_hits / (keyspace_hits + keyspace_misses)` | `get_hits / cmd_get` |
| Вытеснения | `evicted_keys` (INFO stats) | `evictions` (stats) |
| Фрагментация | `mem_fragmentation_ratio` (INFO memory) | не применимо (slab) |
| Перегрузка | `blocked_clients`, `instantaneous_ops_per_sec` | `listen_disabled_num` (исчерпание `-c`) |
| Экспортёр Prometheus | redis_exporter | memcached_exporter |

## Безопасность

- **Redis:** ACL v2 (пользователи, шаблоны ключей, категории команд), `AUTH`, TLS 1.2/1.3 (`tls-port`, сертификаты; в 8.10 — mutual TLS между серверами). Redis Software добавляет LDAP, аудит команд, FIPS 140-3. По умолчанию Redis слушает все интерфейсы — обязательно `bind` внутренний IP / `protected-mode yes` и пароль или ACL.
- **Memcached:** ориентирован на доверенную внутреннюю сеть; TLS (с 1.5.13, `--enable-tls`), SASL (`-S`, требует сборки с `--enable-sasl`). UDP выключен по умолчанию с 1.5.6 (CVE-2018-1000115, amplification-атаки) — держать `-U 0`. Флаги `-F` (запрет `flush_all`), `-X` (запрет дампов), `-A` (включить `shutdown`).

## Валидация конфигурации

| Что проверить | Redis | Memcached |
| :--- | :--- | :--- |
| Версия | `redis-cli INFO server \| grep redis_version` → `redis_version:8.10.2` | `echo version \| nc ...` → `VERSION 1.6.45` |
| Лимит памяти | `INFO memory` → `maxmemory` | `stats settings` → `limit_maxbytes` |
| HA | `SENTINEL master <name>` / `CLUSTER INFO` → `cluster_state:ok` | не применимо |
| Вытеснения | `INFO stats` → `evicted_keys:0` | `stats` → `evictions:0` |

## Диагностика и устранение неисправностей

### Типичные проблемы Redis
1. **Блокировка потока (latency spikes):** тяжёлые команды (`KEYS`, `SMEMBERS`/`HGETALL` на огромных ключах) выполняются в основном потоке. *Решение:* `SCAN`/`HSCAN`, разделение больших коллекций, анализ `SLOWLOG`.
2. **Фрагментация памяти:** `mem_fragmentation_ratio > 1.5`. *Решение:* `activedefrag yes` (требует jemalloc); при сильной фрагментации — плановый рестарт с переключением трафика.
3. **Задержки fork():** RDB-снапшоты и AOF-rewrite на больших датасетах (copy-on-write, пиковое потребление RAM до ~2×). *Решение:* тюнинг `save`/`auto-aof-rewrite-percentage`, мониторинг `latest_fork_usec`.
4. **Ошибки записи при `maxmemory` + `noeviction`:** ожидаемое поведение для критичных данных; для кэша используйте `allkeys-lru`/`allkeys-lfu`.

### Типичные проблемы Memcached
1. **Slab calcification:** дисбаланс страниц между slab-классами. *Решение:* `-o slab_automove`, `slabs reassign <src> <dst>`, рестарт для перераспределения.
2. **Низкий hit rate:** нехватка памяти или «вымывание» кэша. *Решение:* увеличение `-m`, настройка **Extstore**, проверка TTL и SLRU-распределения (`stats items`).
3. **Клиенты «зависают» на подключении:** исчерпан лимит `-c` (1024 по умолчанию). Признак: `listen_disabled_num > 0`. *Решение:* поднять `-c`, пулинг соединений в клиентах.

## Лучшие практики (Best Practices)

1. **Мониторинг:** ключевые метрики — hit rate, evictions, latency. В Redis дополнительно — `ops/sec`, `blocked_clients`, `latest_fork_usec`.
2. **Разделение инстансов:** не использовать один Redis для кэша (допустимо вытеснение) и для критической БД/очередей (`noeviction`).
3. **Сетевой тюнинг (Redis на Linux):** `net.core.somaxconn` до 65535, отключить Transparent Huge Pages (THP), `vm.overcommit_memory=1`.
4. **Высокая доступность:** для Redis — Sentinel или Cluster; для Memcached — client-side consistent hashing (ketama) + мониторинг узлов.
5. **Лицензия:** если AGPLv3 неприемлем — Valkey (BSD-3-Clause, drop-in совместимость) или Memcached (BSD).

### Миграция и откат
- **Redis → Memcached:** потеря структур (все значения сериализуются в blob), потеря persistence/HA; обратная миграция — повторное наполнение кэша.
- **Redis → Valkey:** drop-in (протокол RESP, форматы RDB/AOF совместимы); проверить совместимость используемых модулей.
- **Откат:** обе системы — конфиг + restart; кэш после рестарта холодный (Redis с AOF/RDB восстанавливает данные). План: вернуть конфиг → restart → проверить hit rate и `evicted_keys`/`evictions`.

## Дополнительная информация

### TCO
Memcached эффективнее по стоимости владения при гигантских объёмах кэша (Extstore, SMP, низкие накладные расходы на ключ). Redis экономит ресурсы приложения за счёт атомарных операций (нет циклов read-modify-write) и богатых структур, но требует больше RAM на метаданные; compact hashes (8.10) сокращают разрыв для хэш-интенсивных нагрузок.

### Смежные темы
- Подробный обзор возможностей Redis — **[Обзор Redis](./redis_overview.md)**
- Архитектура и настройка Memcached — **[Обзор Memcached](./memcached_overview.md)**
- Высокая доступность Redis (Sentinel/Cluster) — **[Redis HA](../Concepts/Caching/caching_redis_ha.md)**
- Распределённые блокировки — **[Distributed Locks](../Concepts/Caching/caching_distributed_locks.md)**
- Алгоритмы управления памятью — **[Политики вытеснения в кэше](../Concepts/Caching/caching_eviction_policies.md)**
- Стратегии работы с кешем — **[Паттерны кэширования](../Concepts/Caching/caching_patterns.md)**
- Мониторинг Redis — **[Redis Exporter](../Prometheus/Exporters/redis_exporter.md)**
