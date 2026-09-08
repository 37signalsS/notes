# Политики вытеснения в кэше

## Определения

**Политика вытеснения (Eviction Policy)** — это алгоритм, определяющий правила удаления записей из кэша для освобождения места под новые данные при достижении лимита памяти. Правильный выбор политики критичен для поддержания высокого **Hit Rate** (коэффициента попаданий) и минимизации нагрузки на основные хранилища данных.

С точки зрения SRE, выбор политики вытеснения является инструментом защиты системы от **вымывания кэша (Cache Pollution)** при сканирующих нагрузках и обеспечения стабильности Latency. Политика также определяет поведение системы при **Memory Pressure** (давлении памяти): при нехватке ресурсов кэш должен вытеснять наименее ценные данные, а не падать с ошибкой `OOM` или `OUT OF MEMORY`.

Для понимания общего контекста работы кэша см. [обзор кэширования](./caching_overview.md).

## Основные концепции

### Базовые алгоритмы

#### FIFO (First-In, First-Out)

Удаляются самые старые записи по времени их добавления. Реализуется через простую очередь.
*   **Плюсы:** Минимальные накладные расходы на CPU. Детерминированное поведение — легко предсказать, какие ключи будут вытеснены.
*   **Минусы:** Малоэффективен, так как не учитывает частоту или новизну обращений. Может удалять «горячие» данные просто потому, что они были добавлены давно.
*   **Применение:** Редко используется в рантайме кэшей. Актуален как базовый алгоритм для очередей задач и встраиваемых систем.

#### Clock (Second Chance / Второй шанс)

Улучшенная версия FIFO, аппроксимирующая LRU без использования тяжелых связных списков.
*   **Механизм:** Элементы организованы по кругу. Каждому элементу присваивается «бит доступа». При обращении бит ставится в 1. При нехватке памяти стрелка «часов» обходит круг: если бит 1, он сбрасывается в 0, а элементу дается второй шанс. Если бит уже 0 — элемент вытесняется.
*   **Применение:** Используется в **ядре Linux** для Page Cache и в **PostgreSQL** (алгоритм Clock Sweep для Shared Buffers).
*   **Преимущества перед LRU:** Отсутствие необходимости в связных списках, минимальные накладные расходы на CPU при обновлении метаданных.

#### LRU (Least Recently Used)

Вытесняется элемент, к которому не обращались дольше всего. Основан на гипотезе временной локальности.
*   **Аппроксимированный LRU:** В системах типа Redis LRU реализуется через сэмплирование (случайный выбор N ключей и удаление «худшего» среди них) для экономии памяти на хранение указателей.
*   **Ограничение сэмплирования:** Качество аппроксимации зависит от параметра `maxmemory-samples`. При `samples=5` Redis проверяет 5 случайных ключей и вытесняет наименее используемый. Увеличение до 10 улучшает точность, но растет CPU-нагрузка на каждый eviction.

#### LFU (Least Frequently Used)

Вытесняется элемент с наименьшим совокупным количеством обращений.
*   **Проблема:** Старые популярные ключи («зомби») могут долго занимать место, даже если они больше не используются.
*   **Оптимизация:** Использование **Count-Min Sketch** для компактного хранения частоты запросов.
*   **Decay (затухание):** Счетчик частоты уменьшается со временем (параметр `lfu-decay-time` в Redis). Это предотвращает «зомбификацию» — старые горячие ключи постепенно теряют приоритет.

### Продвинутые алгоритмы

#### 2Q (Two Queues)

Алгоритм, эффективно защищающий от однократных «сканирующих» обращений.
*   **Механизм:** Используются две очереди — FIFO (для новых данных) и LRU (для часто используемых). Если данные запрашиваются повторно, пока они находятся в FIFO, они перемещаются в LRU.
*   **Преимущества:** Лучше, чем LRU, справляется с нагрузками, где много «мусорных» однократных чтений.
*   **Применение:** Реализован в PostgreSQL для буферов WAL (Write-Ahead Log).

#### Segmented LRU (SLRU)

Кэш делится на несколько сегментов (обычно WARM и COLD):
*   Новые данные попадают в COLD. При повторном обращении перемещаются в WARM. Вытеснение из WARM перемещает данные обратно в COLD.
*   Широко применяется в **Memcached** (четыре сегмента: TEMP, HOT, WARM, COLD).
*   **Защита от сканирования:** Однократные обращения никогда не попадают в WARM, поэтому фоновые задачи не вымывают «горячие» данные.

#### LIRS (Low Inter-reference Recency Set)

Алгоритм, классифицирующий данные по интервалу между обращениями (IRR).
*   **Механизм:** Разделяет кэш на «горячие» (LIR) и «холодные» (HIR) блоки. HIR блоки вытесняются чаще.
*   **Преимущества:** Устойчив к последовательному сканированию данных и превосходит LRU в большинстве сценариев СУБД (например, в **MySQL InnoDB**).
*   **Сложность:** Высокие накладные расходы на управление структурой данных.

#### S3-FIFO (Simple Scalable Static-like FIFO)

Современный алгоритм (2023+), использующий три очереди (Small, Main, Ghost).
*   **Ghost Queue:** Хранит идентификаторы недавно удаленных объектов. Если объект из Ghost запрашивается снова, он считается «горячим» и попадает в Main.
*   Часто превосходит LRU по эффективности при меньших накладных расходах на CPU.
*   **Применение:** Активно исследуется для замены LRU в Linux Page Cache и Redis.

#### W-TinyLFU (Window TinyLFU)

Алгоритм, используемый в библиотеке **Caffeine** (Java) и **Ristretto** (Go).
*   **Механизм:** Использует небольшое «окно» (Admission Window) для новых данных и основной кэш. TinyLFU выступает в роли «фильтра на входе», сравнивая частоту обращений нового элемента и кандидата на вытеснение из основного кэша.
*   Использует вероятностные структуры данных (Bloom Filter, Count-Min Sketch) для оценки частоты без больших затрат памяти.
*   **Преимущества:** Баланс между точностью LFU и минимальными затратами памяти.

### Сравнение политик

| Алгоритм | Учет времени (Recency) | Учет частоты (Frequency) | Сложность | Устойчивость к сканам | Память на элемент |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **FIFO** | Да (запись) | Нет | Минимальная | Нет | Минимальная |
| **Clock** | Да | Нет | Низкая | Средняя | Низкая |
| **LRU** | Да (чтение) | Нет | Низкая | Средняя | Средняя (16-24 байта) |
| **LFU** | Нет | Да | Средняя | Высокая | Высокая (счетчик + скетч) |
| **SLRU** | Да | Частично | Средняя | Высокая | Средняя |
| **2Q** | Да | Частично | Средняя | Высокая | Средняя |
| **LIRS** | Да | Да | Высокая | Максимальная | Высокая |
| **W-TinyLFU** | Да | Да | Средняя | Максимальная | Низкая (скетч) |
| **S3-FIFO** | Да | Да | Средняя | Максимальная | Средняя (Ghost Queue) |

### Влияние выбора политики на производительность

Выбор политики напрямую влияет на **Hit Rate**, что определяет нагрузку на БД и общую задержку (Latency) системы:

*   **Разница в Hit Rate на 1%** для системы с 100K RPS и средней стоимостью запроса к БД 2 мс означает **1000 лишних запросов к БД** и **2 секунды дополнительной задержки** суммарно.
*   **Cache Pollution** (вымывание) при неправильной политике может снизить Hit Rate на 10–30%, что эквивалентно удвоению или утроению нагрузки на БД.

## Практические сценарии

### Конфигурация в Redis

Redis использует сэмплирование для аппроксимации LRU/LFU. Полный набор параметров:

```bash
# Основные настройки памяти
CONFIG SET maxmemory 2gb
CONFIG SET maxmemory-policy allkeys-lfu

# Тюнинг сэмплирования (для LRU и LFU)
# maxmemory-samples: количество ключей для проверки при вытеснении
# Больше = точнее, но дороже по CPU
CONFIG SET maxmemory-samples 5    # по умолчанию (LRU)
CONFIG SET maxmemory-samples 10   # рекомендуется для LFU

# Тюнинг LFU:
# lfu-log-factor (по умолчанию 10): чем выше, тем медленнее растет счетчик.
# lfu-decay-time (по умолчанию 1 мин): время, через которое счетчик уменьшается.
CONFIG SET lfu-log-factor 10
CONFIG SET lfu-decay-time 1
```

**Режимы вытеснения в Redis:**

| Политика | Поведение | Когда использовать |
| :--- | :--- | :--- |
| `noeviction` | Возврат ошибки при нехватке памяти | Критические данные, которые нельзя терять |
| `allkeys-lru` | LRU среди всех ключей | Общие нагрузки, рекомендуется по умолчанию |
| `allkeys-lfu` | LFU среди всех ключей | Стабильно популярные данные, длинный хвост |
| `volatile-lru` | LRU только среди ключей с TTL | Смешанные нагрузки (кэш +永久 хранилище) |
| `volatile-lfu` | LFU только среди ключей с TTL | Смешанные нагрузки с предсказуемой частотой |
| `volatile-ttl` | Удаление ключей с наименьшим TTL | Агрессивное старение данных |
| `volatile-random` | Случайное удаление среди ключей с TTL | Быстрое освобождение памяти при критической нехватке |
| `allkeys-random` | Случайное удаление среди всех ключей | Когда частота обращений не важна |

**Пример: Разные политики для разных Use Cases:**

```bash
# Use Case 1: Сессии пользователей (данные с TTL, важна свежесть)
# → volatile-lfu: вытесняем редко используемые сессии
CONFIG SET maxmemory 4gb
CONFIG SET maxmemory-policy volatile-lfu
CONFIG SET lfu-decay-time 10  # Медленное затухание для сессий

# Use Case 2: Кэш API-ответов (все ключи с TTL)
# → allkeys-lru: простая и эффективная стратегия
CONFIG SET maxmemory 8gb
CONFIG SET maxmemory-policy allkeys-lru

# Use Case 3: Rate Limiter (счетчики без TTL)
# → volatile-lru: не вытесняем счетчики, только кэш
CONFIG SET maxmemory 2gb
CONFIG SET maxmemory-policy volatile-lru
```

**Валидация конфигурации:**
```bash
# Проверка текущих настроек
redis-cli CONFIG GET maxmemory-policy
# → "allkeys-lfu"

redis-cli CONFIG GET maxmemory-samples
# → "10"

# Мониторинг вытеснений в реальном времени
redis-cli INFO stats | grep -E "evicted_keys|keyspace_misses|keyspace_hits"
# → evicted_keys:0
# → keyspace_misses:1234
# → keyspace_hits:98765
# → Hit rate: 98.77%
```

### Конфигурация в Memcached (Segmented LRU)

Memcached разделяет Slab Class на сегменты (TEMP, HOT, WARM, COLD) для защиты «горячих» данных от вымывания.

```bash
# Запуск Memcached с фоновой очисткой и поддержкой Segmented LRU
memcached -m 1024 \
  -o lru_maintainer,lru_crawler,slab_automove,ext_item_size=512

# Параметры:
# -m 1024: 1024 МБ памяти
# lru_maintainer: фоновый поток для перемещения элементов между сегментами
# lru_crawler: механизм для сканирования и удаления просроченных элементов
# slab_automove: автоматическая балансировка памяти между slab-классами
```

**Управление LRU через внешние команды:**
```bash
# Принудительное удаление всех элементов ( hazır整顿)
echo "flush_all" | nc localhost 11211
# → OK

# Удаление элемента по ключу
echo "delete user:12345" | nc localhost 11211
# → DELETED

# Просмотр slab-статистики
memcached-tool localhost:11211 display
# → Столбцы: slab_id, used_chunks, total_chunks, evicted_keys
```

**Валидация:**
```bash
# Проверка количества вытеснений
echo "stats" | nc localhost 11211 | grep -E "evictions|curr_items|bytes"
# → STAT evictions 0
# → STAT curr_items 125432
# → STAT bytes 536870912
```

### Вытеснение в Nginx (Proxy Cache)

Nginx не реализует сложный LRU/LFU в рантайме для каждого запроса. Вытеснение происходит по времени неактивности (`inactive`) и по достижении лимита `max_size` (через специальный процесс `cache manager`, который удаляет старые файлы).

```nginx
proxy_cache_path /var/lib/nginx/cache levels=1:2 keys_zone=my_cache:10m 
                 max_size=10g 
                 inactive=60m   # Удаление данных, к которым не обращались 60 мин
                 loader_files=200  # Максимум файлов для загрузки за один цикл
                 loader_threshold=200  # Максимум времени (мс) на один цикл загрузки
                 use_temp_path=off;  # Пишем напрямую в кэш-директорию

server {
    listen 80;
    location /api/ {
        proxy_cache my_cache;
        proxy_cache_valid 200 5m;
        proxy_cache_valid 404 10s;
        proxy_cache_key "$scheme$request_method$host$request_uri";
        proxy_cache_use_stale error timeout updating http_500 http_502 http_503;

        # Активная очистка кэша
        proxy_cache_purge on;  # Требует модуль ngx_cache_purge

        add_header X-Cache-Status $upstream_cache_status;
        proxy_pass http://backend;
    }
}
```

**Очистка кэша вручную (без модуля purge):**
```bash
# Поиск и удаление файлов кэша по URL
CACHE_DIR="/var/lib/nginx/cache"
CACHE_KEY=$(echo -n "GEThttp://example.com/api/v1/users/1" | md5sum | cut -d' ' -f1)
LEVEL1="${CACHE_KEY:0:1}"
LEVEL2="${CACHE_KEY:1:2}"

rm -f "${CACHE_DIR}/${LEVEL1}/${LEVEL2}/${CACHE_KEY}"
```

### Управление Page Cache в Linux

Page Cache — это кэш файловых операций на уровне ядра Linux. Управление им критично для производительности БД и приложений.

```bash
# Просмотр текущего использования Page Cache
free -h
# → total    used    free   shared  buff/cache  available
# → 31Gi    12Gi    5Gi    512Mi     14Gi       18Gi

# Просмотр статистики Page Cache
grep -E "nr_free_pages|nr_file_pages|nr_dirty" /proc/meminfo
# → nr_free_pages: 1310720
# → nr_file_pages: 14680064
# → nr_dirty: 65536

# Принудительный сброс Page Cache (безопасно для производственных систем)
sync && echo 1 > /proc/sys/vm/drop_caches  # Очистка Page Cache
sync && echo 2 > /proc/sys/vm/drop_caches  # Очистка dentries и inodes
sync && echo 3 > /proc/sys/vm/drop_caches  # Очистка всех (Page Cache + dentries + inodes)

# Тюнинг sysctl для оптимизации вытеснения
sysctl -w vm.swappiness=10                    # Минимизация swap
sysctl -w vm.dirty_ratio=15                   # %dirty_memory перед принудительной записью
sysctl -w vm.dirty_background_ratio=5         # %dirty_memory для фоновой записи
sysctl -w vm.vfs_cache_pressure=50            # Давление на кэши dentries/inodes
sysctl -w vm.min_free_kbytes=65536            # Минимум свободной памяти
```

**Утилита vmtouch (управление Page Cache для конкретных файлов):**
```bash
# Установка (macOS)
brew install vmtouch

# Просмотр Page Cache для файла
vmtouch -v /var/lib/mysql/ibdata1
# → /var/lib/mysql/ibdata1
# → 25600/25600 pages (100%) [mr]

# Предзагрузка файла в Page Cache
vmtouch -t /var/lib/mysql/ibdata1
# → 25600/25600 pages (100%) loaded

# Очистка файла из Page Cache
vmtouch -e /var/lib/mysql/ibdata1
```

## Критерии выбора политики

Для эффективной эксплуатации SRE-инженеру следует выбирать политику исходя из паттерна нагрузки:

1.  **Общие нагрузки (Default):** `allkeys-lru` (Redis) или SLRU (Memcached). Это сбалансированный выбор для большинства веб-приложений.
2.  **Длинный хвост (Long Tail):** Если данных очень много и они запрашиваются редко, используйте `LFU` или `LIRS`, чтобы защитить «голову» популярных данных.
3.  **Защита от сканирования (Scan Resistance):** Если в системе часто проходят фоновые задачи (аналитика, бэкапы), выбирайте `SLRU`, `2Q` или `S3-FIFO`, чтобы сканирование не «вымыло» пользовательский кэш.
4.  **Ограниченные ресурсы CPU:** `FIFO` или `Clock` (актуально для встраиваемых систем или сверхвысоких RPS, где накладные расходы на LRU-списки критичны).
5.  **Смешанные нагрузки (кэш +永久 хранилище):** `volatile-lru` или `volatile-lfu` — вытесняются только ключи с TTL,永久 ключи (счетчики, сессии) остаются.

**Decision Matrix:**

| Тип данных | Паттерн нагрузки | Рекомендуемая политика | альтернатива |
| :--- | :--- | :--- | :--- |
| API-кэш (все ключи с TTL) | Стабильный | `allkeys-lru` | `allkeys-lfu` |
| Сессии (ключ с TTL) | Стабильный | `volatile-lfu` | `volatile-lru` |
| Rate Limiter (без TTL) | Высокочастотный | `volatile-lru` | `volatile-random` |
| Кэш БД (долгоживущий) | Длинный хвост | `allkeys-lfu` | `allkeys-lru` |
| Стриминг/логи | Высокая запись | `noeviction` + отдельный storage | `volatile-random` |

## Мониторинг и эксплуатация

### Критические метрики для алертинга

| Метрика | Описание | Источник | Алерт |
| :--- | :--- | :--- | :--- |
| `evicted_keys_total` | Резкий рост означает нехватку памяти (Memory Pressure) | `redis-cli INFO stats` | Рост > 100/мин |
| `cache_hit_ratio` | Падение hit rate при росте evictions — сигнал о смене паттерна доступа | `rate(hits) / rate(hits + misses)` | < 80% |
| `used_memory_bytes` | Текущее использование памяти | `redis-cli INFO memory` | > 80% maxmemory |
| `mem_fragmentation_ratio` | Фрагментация памяти | `redis-cli INFO memory` | > 1.5 |
| `evictions_per_second` | Скорость вытеснений в секунду | Prometheus + Grafana | > 50 |
| `cache_size_bytes` | Текущий размер кэша (для Nginx) | `ls -la /var/lib/nginx/cache/` | > max_size |

### Команды диагностики

```bash
# Redis: полная статистика кэша
redis-cli INFO stats | grep -E "keyspace_hits|keyspace_misses|evicted_keys"
# → keyspace_hits:1234567
# → keyspace_misses:12345
# → evicted_keys:0

# Redis: детализация по памяти
redis-cli INFO memory | grep -E "used_memory_human|maxmemory_human|mem_fragmentation_ratio"
# → used_memory_human:1.92G
# → maxmemory_human:2.00G
# → mem_fragmentation_ratio:1.05

# Redis: поиск ключей с наименьшим LFU-счетчиком (кандидаты на вытеснение)
redis-cli --bigkeys --no-auth-warning

# Memcached: детализация по slab-классам
memcached-tool localhost:11211 display
# → Столбцы: slab_id, used_chunks, total_chunks, evicted_keys

# Memcached: быстрая проверка статуса
echo "stats" | nc localhost 11211 | grep -E "evictions|curr_items|bytes|cmd_get|cmd_set"
# → STAT evictions 0
# → STAT curr_items 125432
# → STAT bytes 536870912
```

### Диагностика и устранение проблем

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Hit rate < 80% | Недостаточный объем кэша или неэффективная политика | `redis-cli INFO stats` | Увеличить `maxmemory` или сменить политику |
| Hit rate < 80% (Nginx) | Слишком короткий `inactive` или `proxy_cache_valid` | Проверить `X-Cache-Status: MISS` | Увеличить TTL кэша |
| `OOM command not allowed` | Исчерпан лимит `maxmemory` | `redis-cli INFO memory` | Увеличить `maxmemory` или сменить политику |
| `evictions > 0` | Памяти недостаточно, вытесняются старые данные | `memcached-tool stats` | Увеличить `-m` или оптимизировать размеры объектов |
| Memory pressure в контейнере | Лимит `memory.limit_in_bytes` (cgroup v1) или `memory.max` (cgroup v2) слишком низок | `cat /sys/fs/cgroup/memory/memory.limit_in_bytes` | Увеличить `memory` limits контейнера |
| Рост latency операций | Фрагментация памяти или блокировки при вытеснении | `redis-cli INFO memory`, `redis-cli SLOWLOG GET` | Включить `activedefrag yes`, увеличить `maxmemory-samples` |
| `CACHE_FULL` в Nginx | `max_size` достигнут, `cache manager` не успевает удалять | Проверить логи Nginx, `ls /var/lib/nginx/cache/` | Увеличить `max_size` или уменьшить `inactive` |
| Странное поведение после рестарта | Кэш пуст (холодный старт) | Проверить `curr_items` после рестарта | Прогреть кэш (Cache Warmup) |

## Сетевые соображения

*   **Влияние сетевой задержки:** Каждый `Cache Miss` в распределенном кэше (Redis/Memcached) добавляет одну сетевую операцию (0.1–0.5 мс в дата-центре). При высоком miss rate суммарная задержка может превышать прямой доступ к БД.
*   **Проверка задержки до кэша:**
    ```bash
    # Redis
    redis-cli --latency -h <host> -p 6379
    # → min: 0, max: 1, avg: 0.12 (milliseconds)

    # Memcached
    memcslap --servers=<host>:11211 --connect-timeout=1 --execute-number=100
    ```
*   **TCP Keepalive:** Настройте `tcp-keepalive 300` (Redis) или `-o tcp_keepalive` (Memcached) для предотвращения разрыва неактивных соединений.

## Ограничения и Edge Cases

*   **Race Condition при `volatile-*` политике:** Если ключ с TTL вытесняется в момент обновления, следующий запрос может прочитать устаршие данные из БД. Решение — использовать `allkeys-*` или `noeviction`.
*   **Split-brain при Redis Cluster:** При сетевом partitions возможна ситуация, когда две ноды считают себя master. Настройте `cluster-require-full-coverage no` для минимизации impact.
*   **Анти-паттерн: Большой ключ в Redis:** Один ключ размером 100 МБ может заблокировать eviction для всех ключей. Решение — `redis-cli --bigkeys` для поиска и разбиения на части.
*   **Неравномерное вытеснение в Memcached:** При `slab_automove=1` Memcached может перераспределять память между slab-классами, что приводит к неравномерным eviction. Решение — `slab_automove=0` для стабильного поведения.
*   **Decay-time и паттерны нагрузки:** Слишком короткий `lfu-decay-time` (1 мин) может «забывать» горячие ключи при временных всплесках. Решение — увеличить до 10–30 минут для стабильных данных.
*   **Гонка данных при `noeviction`:** Если `noeviction` включен, но приложение не обрабатывает ошибку `OOM command not allowed`, данные могут быть потеряны. Решение — всегда обрабатывать ошибки Redis в коде приложения.

## Тестирование и валидация

### Нагрузочное тестирование политик

```bash
# Сравнение LRU vs LFU через memtier_benchmark
# LRU
redis-cli CONFIG SET maxmemory-policy allkeys-lru
memtier_benchmark -s 127.0.0.1 -p 6379 -t 4 -c 50 -n 100000 --key-maximum=1000000 --ratio=1:1 --key-pattern=R:R

# LFU
redis-cli CONFIG SET maxmemory-policy allkeys-lfu
memtier_benchmark -s 127.0.0.1 -p 6379 -t 4 -c 50 -n 100000 --key-maximum=1000000 --ratio=1:1 --key-pattern=R:R
```

### Сценарий тестирования: Защита от сканирования

```bash
# 1. Заполнить кэш горячими данными
for i in $(seq 1 10000); do
    redis-cli SET "hot:$i" "value_$i" EX 3600
done

# 2. Запустить фоновое сканирование (имитация аналитики)
for i in $(seq 1 50000); do
    redis-cli GET "scan:$i"
done

# 3. Проверить hit rate для горячих ключей
redis-cli INFO stats | grep -E "keyspace_hits|keyspace_misses"
# При SLRU/S3-FIFO: hit rate сохраняется > 95%
# При LRU: hit rate может упасть до 60-70%
```

### Валидация корректности вытеснения

```bash
# Проверка, что вытесняются именно «холодные» ключи
redis-cli CONFIG SET maxmemory 100mb
redis-cli CONFIG SET maxmemory-policy allkeys-lru

# Заполнить кэш: 80% горячих, 20% холодных
for i in $(seq 1 8000); do redis-cli SET "hot:$i" "x"; done
for i in $(seq 1 2000); do redis-cli SET "cold:$i" "x"; done

# Обратиться к горячим ключам (обновить LRU-счетчик)
for i in $(seq 1 8000); do redis-cli GET "hot:$i"; done

# Добавить новые ключи, чтобы вызвать eviction
for i in $(seq 1 1000); do redis-cli SET "new:$i" "x"; done

# Проверить, что горячие ключи на месте
redis-cli EXISTS hot:1   # → 1
redis-cli EXISTS cold:1  # → 0 (вытеснен)
```

## Бэкап и восстановление

*   **Redis (при персистентности):** RDB-снапшоты: автоматические (`save 900 1`) или ручные (`BGSAVE`). AOF: `BGREWRITEAOF`. Политика вытеснения не влияет на персистентность — вытесненные ключи удаляются из памяти, но остаются в RDB/AOF до следующей записи.
*   **Redis (без персистентности):** Полная потеря данных — нормальное поведение для кэша. Recovery strategy: прогрев кэша после перезапуска.
*   **Memcached:** Полная потеря данных при перезапуске — это нормальное поведение для кэша. Recovery strategy: прогрев кэша (Cache Warmup).

**Пример: Ручной снапшот Redis перед сменой политики:**
```bash
# Перед изменением политики вытеснения
redis-cli BGSAVE
redis-cli LASTSAVE
# → 1234567890

# Изменить политику
redis-cli CONFIG SET maxmemory-policy allkeys-lfu

# Проверить, что данные на месте
redis-cli DBSIZE
# → (integer) 125432
```

## Связанные темы

*   [Обзор кэширования](./caching_overview.md) — уровни и метрики
*   [Паттерны кэширования](./caching_patterns.md) — стратегии взаимодействия с БД
*   [Обзор Redis](../../Databases/redis_overview.md) — детали реализации в Redis
