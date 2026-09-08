# DPDK: Технические детали

### Определения

- **EAL (Environment Abstraction Layer)**: Слой абстракции окружения, который инициализирует ресурсы (память, ядра CPU, PCI-устройства) и предоставляет единый интерфейс для приложения, скрывая детали конкретной ОС.
- **Hugepages (Большие страницы)**: Механизм управления памятью, использующий страницы размером 2 МБ или 1 ГБ. Позволяет значительно увеличить покрытие TLB (Translation Lookaside Buffer) и снизить количество дорогостоящих промахов (TLB misses).
- **PMD (Poll Mode Driver)**: Драйвер, работающий в режиме постоянного опроса регистров сетевого адаптера. Полностью исключает прерывания и переключения контекста, обеспечивая детерминированную производительность.
- **lcore (Logical Core)**: Поток исполнения DPDK, жестко привязанный к конкретному аппаратному ядру CPU (affinity).
- **rte_mbuf**: Основная структура данных DPDK для хранения пакетов. Содержит заголовок с метаданными (разгрузки, порты, хеши) и указатели на данные.
- **rte_ring**: Высокопроизводительная бесблокировочная очередь (Ring Buffer), обеспечивающая эффективный обмен данными между lcores.
- **SP/SC (Single Producer / Single Consumer)**: Режим работы rte_ring с максимальной скоростью — один producer и один consumer, атомарные операции не требуются для head/tail.
- **MP/MC (Multi Producer / Multi Consumer)**: Режим rte_ring для нескольких producer/consumer с использованием CAS (Compare-And-Swap) атомарных инструкций.
- **Cache-line (Линия кэша)**: Базовая единица передачи данных между CPU и кэшем/памятью (64 байта на x86, 128 байт на Apple M1/M2/M3/M4). Все структуры DPDK выравниваются по этой границе для предотвращения false sharing.

---

### Глубокая оптимизация памяти

В 2026 году для систем 400G/800G стандартом является использование **Hugepages размером 1 ГБ**.

#### 1. Механика HugeTLB и покрытие TLB

**Проблема со стандартными страницами (4 КБ):**
```
TLB (64-128 записей) покрывает 64 × 4 КБ = 256 КБ памяти.
При обработке пакетов на NIC 100Gbps это ~148M пакетов/сек,
каждый пакет обращается к нескольким страницам → TLB miss →
 hardware walk → 5-10 циклов промаха → деградация производительности.
```

**Решение с HugePages:**

| Размер страницы | TLB entries | Покрытие памяти | Типичное использование |
| :--- | :--- | :--- | :--- |
| 4 КБ (стандартная) | 64 | 256 КБ | Обычные приложения |
| 2 МБ (HugePage) | 32 | 64 МБ | Средние нагрузки (до 25G) |
| 1 ГБ (Gigantic HugePage) | 16 | 16 ГБ | Высокие нагрузки (100G-800G) |

**Формула покрытия:** `Покрытие = Размер_страницы × Количество_записей_TLB`

TLB на современных CPU (x86-64): 64 L1 entries + 1536 L2 entries = 1600 entries. С 1 ГБ страницами: 1600 × 1 ГБ = **1.6 ТБ покрытия**. Этого достаточно для всех буферов DPDK (mbuf, mempool, ring) без единого TLB miss.

**Механизм выделения HugePages:**
```
Обычная страница (4KB):
  Виртуальный адрес → Page Table Walk (4 уровня) → Физический адрес

HugePage (2MB):
  Виртуальный адрес → Page Table Walk (3 уровня, PGD→PMD→PTE) → Физический адрес
  Экономия: 1 уровень меньше → 1 промах TLB меньше на каждый доступ

HugePage (1GB):
  Виртуальный адрес → Page Table Walk (2 уровня, PGD→PTE) → Физический адрес
  Экономия: 2 уровня меньше → 2 промаха TLB меньше на каждый доступ
```

**Статическое выделение HugePages (рекомендуется для DPDK):**
```bash
# Просмотр текущих HugePages
cat /proc/meminfo | grep -i huge
# → HugePages_Total:    0
# → HugePages_Free:     0
# → Hugepagesize:       2048 kB

# Выделение 1024 страниц по 2 МБ (2 ГБ)
echo 1024 | sudo tee /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages
# → Проверка: cat /proc/meminfo | grep -i huge
# → HugePages_Total:    1024
# → HugePages_Free:     1024

# Выделение 8 страниц по 1 ГБ (8 ГБ)
echo 8 | sudo tee /sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages

# Выделение HugePages на конкретном NUMA-узле
echo 4 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages
echo 4 > /sys/devices/system/node/node1/hugepages/hugepages-1048576kB/nr_hugepoints
```

**Динамическое выделение HugePages:**
```bash
# Через API ядра (внутри приложения)
#include <sys/mman.h>

// Выделение 2 МБ HugePages через mmap
void *ptr = mmap(NULL, 2 * 1024 * 1024, PROT_READ | PROT_WRITE,
                 MAP_PRIVATE | MAP_ANONYMOUS | MAP_HUGETLB, -1, 0);
if (ptr == MAP_FAILED) {
    // Ошибка: HugePages не выделены или недостаточно
    perror("mmap");
}

// Освобождение
munmap(ptr, 2 * 1024 * 1024);
```

**Точки монтирования HugePages (Файловая система):**
```bash
# Монтирование HugePages filesystem (обычно уже примонтировано)
mount -t hugetlbfs -o pagesize=1G none /dev/hugepages

# Просмотр примонтированных HugePages
mount | grep huge
# → nodev on /dev/hugepages type hugetlbfs (rw,relatime,pagesize=2M)
# → nodev on /dev/hugepages-1G type hugetlbfs (rw,relatime,pagesize=1G)

# DPDK автоматически монтирует HugePages при запуске
# Ручное монтирование не требуется если HugePages выделены через sysfs
```

**Проверка выделения HugePages:**
```bash
# Проверка что HugePages выделены корректно
ls /dev/hugepages/
# → hugepages-1048576kB-0  (если 1GB страницы)
# → hugepages-2048kB-0     (если 2MB страницы)

# Просмотр используемых HugePages (для запущенного DPDK-приложения)
ls -la /dev/hugepages/
# → -rw-r--r-- 1 root root 1073741824 Aug 25 10:00 rte_mempool_dpdk
# → ^^^ mempool занимает HugePages файл
```

#### 2. Управление пулами (Mempool)

DPDK использует `rte_mempool` для управления буферами пакетов.

**Архитектура mempool:**
```
  lcore 0          lcore 1          lcore 2          lcore 3
    │                │                │                │
    ▼                ▼                ▼                ▼
┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
│ Local   │    │ Local   │    │ Local   │    │ Local   │
│ Cache   │    │ Cache   │    │ Cache   │    │ Cache   │
│ (32 obj)│    │ (32 obj)│    │ (32 obj)│    │ (32 obj)│
└────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘
     │              │              │              │
     └──────────────┴──────┬───────┴──────────────┘
                           │
                  ┌────────▼────────┐
                  │   Global Pool   │
                  │  (объекты mbuf) │
                  └────────┬────────┘
                           │
                  ┌────────▼────────┐
                  │  HugePages RAM  │
                  │  (физическая)   │
                  └─────────────────┘
```

**Ключевые параметры mempool:**

| Параметр | Формула / Значение | Описание |
| :--- | :--- | :--- |
| `nb_objs` | `nb_ports × nb_queues × queue_size × multiplier` | Общее количество объектов (рекомендуется ×4 от необходимого) |
| `obj_size` | `sizeof(struct rte_mempool_objhdr) + sizeof(struct rte_mbuf) + 64` | Размер объекта + выравнивание по cache-line |
| `cache_size` | `MIN(512, nb_objs / (nb_lcores × 8))` | Размер локального кэша на ядро (рекомендуется 32-512) |
| `socket_id` | `rte_socket_id()` или NUMA node NIC | NUMA-узел для локального выделения |
| `flags` | `MEMPOOL_F_SP_PUT \| MEMPOOL_F_SC_GET` | Single-Producer/Single-Consumer для максимальной скорости |

**Пример вычисления количества объектов:**
```bash
# Сценарий: 2 порта, 4 очереди на порт, 1024 дескриптора на очередь
# nb_objs = 2 × 4 × 1024 × 4 = 32768 объектов
# cache_size = MIN(512, 32768 / (4 лкоры × 8)) = 1024

# Для 100Gbps NIC с 64-байтовыми фреймами:
# nb_objs = 148Mpps × 2 (headroom) × 2 (backlog) = 592M объектов
# cache_size = MIN(512, 592M / (8 лкоры × 8)) = 512
```

**Создание mempool через API:**
```c
#include <rte_mempool.h>
#include <rte_mbuf.h>

// Создание mempool для mbuf
struct rte_mempool *mp = rte_mempool_create(
    "mbuf_pool",                    // Имя пула
    NB_MBUFS,                       // Количество объектов (32768)
    MBUF_SIZE,                      // Размер объекта (2176 байт с заголовком)
    CACHE_SIZE,                     // Размер локального кэша (256)
    sizeof(struct rte_pktmbuf_pool_private), // Размер приватных данных
    NULL,                           // mp_init callback
    NULL,                           // mp_init arg
    NULL,                           // obj_init callback
    NULL,                           // obj_init arg
    rte_socket_id(),                // NUMA socket (текущий)
    0                               // Флаги (0 = MP/MC)
);

// Проверка создания
if (mp == NULL)
    rte_exit(EXIT_FAILURE, "Cannot create mempool\n");
```

**Получение и освобождение объектов:**
```c
// Основные API для работы с mempool
struct rte_mbuf *pkts_burst[32];

// Получение пакетов из mempool (bulk)
unsigned ret = rte_mempool_get_bulk(mp, (void **)pkts_burst, 32);
if (ret == 0) {
    // Успешно получено 32 пакета
    for (int i = 0; i < 32; i++) {
        // Обработка pkts_burst[i]
    }
    // Освобождение обратно в mempool
    rte_mempool_put_bulk(mp, (void **)pkts_burst, 32);
}

// Получение одного пакета (single)
struct rte_mbuf *m;
if (rte_mempool_get(mp, (void **)&m) == 0) {
    // Пакет получен
    rte_mempool_put(mp, m);
}
```

**Оптимизация mempool:**
- **Размер кэши**: увеличивайте `cache_size` до 512 для снижения обращений к глобальному пулу. При `cache_size=512` и 8 ядрах, глобальный пул опрашивается только каждые 512 × 8 = 4096 операций.
- **Bulk-операции**: используйте `rte_mempool_get_bulk` вместо `rte_mempool_get` для группового выделения (снижает overhead).
- **Спавнинг**: для очень больших пулов (>1M объектов) используйте `rte_mempool_create_empty` + `rte_mempool_populate_obj` для поэтапного заполнения.
- **Проверка**: `rte_mempool_avail_count(mp)` показывает количество доступных объектов.

#### 3. Бесблокировочные очереди (rte_ring)

Библиотека `rte_ring` реализует эффективные алгоритмы для различных сценариев:

**Внутренняя структура rte_ring:**
```c
struct rte_ring {
    char name[RTE_RING_NAMESIZE];   // Имя очереди
    int flags;                       // Флаги (SP/SC/MP/MC)
    uint32_t size;                   // Размер кольца (степень двойки)
    uint32_t mask;                   // size - 1 (для битовой маски)
    uint32_t capacity;               // Максимальная ёмкость

    char pad0 __rte_cache_aligned;   // Выравнивание по cache-line

    // Голова и хвост (producer/consumer pointers)
    volatile uint32_t head __rte_cache_aligned; // Producer head
    volatile uint32_t tail __rte_cache_aligned; // Consumer tail

    char pad1 __rte_cache_aligned;

    // Элементы кольца
    void *ring[0] __rte_cache_aligned; // Гибкий массив указателей
};
```

**Механика работы SP/SC (Single Producer / Single Consumer):**
```
SP (Producer):
  1. Читает producer_head (volatile)
  2. Вычисляет новый head = (head + n) & mask
  3. Записывает элементы в ring[head .. head+n-1]
  4. Атомарно обновляет producer_head = new_head
  (Атомарность НЕ нужна — только один producer)

SC (Consumer):
  1. Читает consumer_tail (volatile)
  2. Вычисляет новый tail = (tail + n) & mask
  3. Читает элементы из ring[tail .. tail+n-1]
  4. Атомарно обновляет consumer_tail = new_tail
  (Атомарность НЕ нужна — только один consumer)

Скорость: ~20-30 ns на enqueue/dequeue (0 атомарных инструкций)
```

**Механика MP/MC (Multi Producer / Multi Consumer):**
```
MP (Producer):
  1. Читает producer_head (volatile)
  2. CAS(head, old_head, new_head) — атомарная установка
  3. Если CAS не удался — повторить (spin-loop)
  4. Записывает элементы в ring[old_head .. new_head-1]

MC (Consumer):
  1. Читает consumer_tail (volatile)
  2. CAS(tail, old_tail, new_tail) — атомарная установка
  3. Если CAS не удался — повторить (spin-loop)
  4. Читает элементы из ring[old_tail .. new_tail-1]

Скорость: ~50-80 ns на enqueue/dequeue (1 CAS + retry loop)
```

**Режимы работы:**

| Режим | Флаг | Функции | Сценарий использования |
| :--- | :--- | :--- | :--- |
| **SP/SC** | `RING_F_SP_ENQ \| RING_F_SC_DEQ` | `rte_ring_sp_enqueue`, `rte_ring_sc_dequeue` | Один producer, один consumer (максимальная скорость) |
| **MP/MC** | 0 (по умолчанию) | `rte_ring_enqueue`, `rte_ring_dequeue` | Несколько producer/consumer (кассета) |
| **MP/SC** | `RING_F_SC_DEQ` | `rte_ring_enqueue`, `rte_ring_sc_dequeue` | Несколько producer, один consumer |
| **SP/MC** | `RING_F_SP_ENQ` | `rte_ring_sp_enqueue`, `rte_ring_dequeue` | Один producer, несколько consumer |

**Примеры API:**
```c
#include <rte_ring.h>

// Создание кольца (размер должен быть степенью двойки)
struct rte_ring *ring = rte_ring_create(
    "my_ring",          // Имя
    1024,               // Размер (степень двойки)
    rte_socket_id(),    // NUMA socket
    RING_F_SP_ENQ | RING_F_SC_DEQ  // Флаги (SP/SC)
);

// Enqueue (вставка элементов)
void *objs[4] = {buf1, buf2, buf3, buf4};

// Bulk enqueue (все 4 или ни одного)
unsigned enqueued = rte_ring_enqueue_burst(ring, objs, 4, NULL);
// enqueued = количество успешно вставленных элементов (0-4)

// Single enqueue (один элемент)
int ret = rte_ring_sp_enqueue(ring, buf1);
if (ret == -ENOSPC) {
    // Кольцо заполнено
}

// Dequeue (извлечение элементов)
void *out[4];
unsigned dequeued = rte_ring_sc_dequeue_burst(ring, out, 4, NULL);
// dequeued = количество извлечённых элементов (0-4)

// Проверка состояния
unsigned count = rte_ring_count(ring);   // Количество элементов
unsigned free_cnt = rte_ring_free_count(ring); // Свободное место
int full = rte_ring_full(ring);          // 1 если заполнено
int empty = rte_ring_empty(ring);        // 1 если пусто
```

**Оптимизация rte_ring:**
- **Bulk-операции**: `rte_ring_enqueue_burst` и `rte_ring_dequeue_burst` намного эффективнее одиночных операций (амортизация overhead).
- **Размер кольца**: степень двойки (1024, 2048, 4096). Для 100Gbps с burst=32: `1024 × 32 = 32768` элементов минимальный размер.
- **Кэширование**: `rte_ring_enqueue_burst` с `n` элементов обрабатывает их пачками, минимизируя обращения к памяти.
- **Проверка полноты/пустоты**: `rte_ring_full` и `rte_ring_empty` используют memory barriers, что может быть дороже простого сравнения `count`.

#### 4. NUMA-выравнивание

Критически важно, чтобы память (Hugepages) и сетевой адаптер (NIC) находились на одном NUMA-узле. Обращение к памяти через шину UPI/QPI между сокетами увеличивает задержку (Latency) на 30–50%.

**Влияние NUMA на производительность DPDK:**

| Параметр | Локальный NUMA | Удалённый NUMA | Деградация |
| :--- | :--- | :--- | :--- |
| Задержка доступа к памяти | 80-100 нс | 130-150 нс | +30-50% |
| Пропускная способность памяти | 200-300 ГБ/с | 100-150 ГБ/с | -50% |
| Время обработки пакета | 1.0x | 1.3-1.5x | +30-50% |

**Определение NUMA-топологии NIC:**
```bash
# Определение NUMA-узла NIC
cat /sys/class/net/enp1s0/device/numa_node
# → 0  (NIC подключена к NUMA-узлу 0)

# Просмотр всей NUMA-топологии
numactl --hardware
# → available: 2 nodes (0-1)
# → node 0 cpus: 0 1 2 3 4 5 6 7
# → node 0 size: 65536 MB
# → node 1 cpus: 8 9 10 11 12 13 14 15
# → node 1 size: 65536 MB
# → node distances:
# → node   0   1
# →   0:  10  21   ← расстояние 21 = UPI interconnect
# →   1:  21  10

# Проверка расстояний NUMA
numactl --hardware | grep "node distances"
# → 10 = локальный доступ
# → 21 = удалённый доступ через UPI/QPI
```

**Выделение HugePages на NUMA-узле NIC:**
```bash
# NIC на NUMA-узле 0 → HugePages на узле 0
echo 8 > /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages

# Проверка
cat /sys/devices/system/node/node0/hugepages/hugepages-1048576kB/nr_hugepages
# → 8

# Проверка использования HugePages по узлам
cat /sys/devices/system/node/node0/meminfo | grep Huge
# → Node 0 HugePages_Total:     8
# → Node 0 HugePages_Free:      8
```

---

### Архитектура обработки и CPU

#### 1. Цикл Run-to-Completion

В DPDK пакет обрабатывается одним ядром от момента получения до отправки. Это позволяет держать все данные в L1/L2 кэшах текущего ядра.

**Сравнение моделей обработки:**

| Модель | Описание | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Run-to-Completion** | Один lcore обрабатывает пакет от RX до TX | Максимальная скорость, кэш-локальность | Сложная логика на одном ядре |
| **Pipeline (Потоковая)** | Разделение на этапы (RX → Processing → TX) на разных lcore | Простая логика, параллелизм | Межъядерная коммуникация через ring |
| **Смешанная** | Гибрид двух подходов | Баланс скорости и сложности | Дополнительная сложность конфигурации |

**Run-to-Completion в DPDK (типичный паттерн):**
```c
// Поток для одного lcore
void lcore_main(void) {
    struct rte_mbuf *pkts_burst[MAX_PKT_BURST];

    while (1) {
        // 1. Получение пакетов из NIC
        unsigned nb_rx = rte_eth_rx_burst(port_id, queue_id,
                                          pkts_burst, MAX_PKT_BURST);

        // 2. Обработка каждого пакета
        for (unsigned i = 0; i < nb_rx; i++) {
            struct rte_mbuf *m = pkts_burst[i];

            // Парсинг заголовков
            struct rte_ether_hdr *eth = rte_pktmbuf_mtod(m, struct rte_ether_hdr *);

            // Логика обработки (L2/L3/L4)
            process_packet(m);

            // 3. Отправка
            rte_eth_tx_burst(port_id, queue_id, &m, 1);
        }
    }
}
```

**Pipeline модель через rte_ring:**
```c
// RX lcore: получает пакеты и передаёт в ring
void rx_lcore(void) {
    struct rte_mbuf *pkts_burst[MAX_PKT_BURST];

    while (1) {
        unsigned nb_rx = rte_eth_rx_burst(port_id, 0,
                                          pkts_burst, MAX_PKT_BURST);

        // Передача в ring для обработки
        rte_ring_enqueue_burst(rx_to_worker_ring,
                               (void **)pkts_burst, nb_rx, NULL);
    }
}

// Worker lcore: обрабатывает пакеты из ring
void worker_lcore(void) {
    struct rte_mbuf *pkts_burst[MAX_PKT_BURST];

    while (1) {
        unsigned nb = rte_ring_dequeue_burst(rx_to_worker_ring,
                                             (void **)pkts_burst,
                                             MAX_PKT_BURST, NULL);

        for (unsigned i = 0; i < nb; i++) {
            process_packet(pkts_burst[i]);
            rte_eth_tx_burst(port_id, 0, &pkts_burst[i], 1);
        }
    }
}
```

#### 2. Оптимизация кэша (Prefetching)

Программный предварительный выбор данных (`rte_prefetch0/1/2`) позволяет заранее загрузить заголовки пакетов из RAM в кэш CPU, пока выполняется логика обработки предыдущего пакета.

**Уровни предзагрузки:**
```c
struct rte_mbuf *pkts_burst[32];

// Prefetch levels
for (unsigned i = 0; i < nb_rx; i++) {
    // Prefetch Level 0: загрузка в L1/L2 ( ~3-5 циклов)
    rte_prefetch0(rte_pktmbuf_mtod(pkts_burst[i], void *));

    // Prefetch Level 1: загрузка в L2 ( ~10-15 циклов)
    rte_prefetch1(rte_pktmbuf_mtod(pkts_burst[i], void *));

    // Prefetch Level 2: загрузка в L3 ( ~20-30 циклов)
    rte_prefetch2(rte_pktmbuf_mtod(pkts_burst[i], void *));
}
```

**Эффект prefetching:**

| Сценарий | Время доступа к mbuf | Пояснение |
| :--- | :--- | :--- |
| Без prefetch | 200-300 нс (RAM access) | Каждое обращение к mbuf = промах кэша |
| С prefetch (L2) | 10-15 нс (L2 hit) | Данные уже в кэше при обращении |
| С prefetch (L3) | 4-6 нс (L3 hit) | Данные в общем кэше |

**Паттерн "Prefetch Pipeline":**
```c
// Оптимальный паттерн: prefetch следующего пакета при обработке текущего
for (unsigned i = 0; i < nb_rx; i++) {
    // Prefetch данных следующего пакета (если есть)
    if (i + 1 < nb_rx)
        rte_prefetch0(rte_pktmbuf_mtod(pkts_burst[i + 1], void *));

    // Обработка текущего пакета
    process_packet(pkts_burst[i]);
}
```

#### 3. Векторные инструкции (SIMD)

Современные PMD-драйверы (для Intel E810, ConnectX-8) используют **AVX-512** и **AMX** для пакетной обработки. Это позволяет обрабатывать 4, 8 или 16 дескрипторов за одну инструкцию, что критично для скоростей 100+ Mpps.

**Пример векторной обработки:**
```c
// x86 AVX-512: обработка 16 дескрипторов за одну инструкцию
#include <immintrin.h>

// Загрузка 16 указателей на дескрипторы
__m512i desc_ptrs = _mm512_loadu_si512(desc_array);

// Параллельная проверка статусов 16 дескрипторов
__m512i statuses = _mm512_maskz_loadu_epi64(valid_mask, desc_array);

// Сравнение с нулём (проверка на ошибки)
__mmask16 error_mask = _mm512_cmp_epi64_mask(statuses, zero_vec, _MM_CMPINT_EQ);

// Пакетная обработка: 16 пакетов за ~5-10 нс
```

**SIMD-инструкции в DPDK PMD:**

| Инструкция | Размер | Пакетов за инструкцию | Использование |
| :--- | :--- | :--- | :--- |
| SSE4.2 | 128 бит | 2 × 64-битных указателя | Начальные PMD |
| AVX2 | 256 бит | 4 × 64-битных указателя | Основной SIMD в DPDK |
| AVX-512 | 512 бит | 8 × 64-битных указателя | Высокопроизводительные PMD |
| AMX | 1024 бит | 16 × 64-битных указателя | AI/ML ускорение в NIC |

---

### Структура rte_mbuf

`rte_mbuf` — основная структура данных для хранения пакетов. Понимание её внутренней организации критично для эффективной обработки.

**Внутренняя структура rte_mbuf:**
```c
struct rte_mbuf {
    // Приватные данные mempool
    void *buf_addr;           // Адрес начала буфера (учитывая data_off)
    uint16_t buf_len;         // Длина буфера (включая headroom)
    uint16_t data_off;        // Смещение от buf_addr до начала данных

    // Кэш-линия 1 (64 байта): метаданные пакета
    struct rte_mempool *pool;  // Пул, из которого выделен mbuf
    void *buf_addr;           // Виртуальный адрес начала буфера

    // Кэш-линия 2: управление
    uint16_t refcnt;          // Счётчик ссылок (для клонирования)
    uint16_t nb_segs;         // Количество сегментов (для jumbo frames)
    uint32_t packet_type;     // Тип пакета (L2/L3/L4)

    // Кэш-линия 3: аппаратные разгрузки
    uint32_t ol_flags;        // Флаги offloading (PKT_RX_IP_CKSUM good и т.д.)

    // Кэш-линия 4: размеры и VLAN
    uint16_t data_len;        // Фактическая длина данных в первом сегменте
    uint32_t pkt_len;         // Общая длина пакета (все сегменты)
    uint16_t vlan_tci;        // VLAN TCI для аппаратного вставки

    // Кэш-линия 5: RSS/Hash
    uint32_t hash;            // RSS hash или пользовательский hash
    uint16_t seqn;            // Последовательный номер
};
```

**Хранение данных в mbuf:**
```
  buf_addr (начало буфера)
    │
    ├─── Headroom (128 байт, резерв) ← rte_pktmbuf_headroom()
    │
    ├─── data_off ← смещение до начала данных
    │
    ├─── Data (данные пакета) ← rte_pktmbuf_mtod(m, ...)
    │    ├── Ethernet header (14 байт)
    │    ├── IP header (20-60 байт)
    │    ├── TCP/UDP header (8-20 байт)
    │    └── Payload
    │
    └─── End of buffer
```

**Операции с mbuf:**
```c
#include <rte_mbuf.h>

// Добавление заголовка (выделение пространства перед данными)
struct rte_ether_hdr *eth = rte_pktmbuf_append(m, sizeof(*eth));
eth->ether_type = rte_be_to_cpu_16(RTE_ETHER_TYPE_IPV4);

// Удаление заголовка (смещение данных)
rte_pktmbuf_adj(m, sizeof(struct rte_ether_hdr));

// Получение указателя на данные
void *data = rte_pktmbuf_mtod(m, void *);

// Клонирование (разделяет данные, увеличивает refcnt)
struct rte_mbuf *clone = rte_pktmbuf_clone(m, m->pool);

// Проверка ссылок
if (rte_mbuf_refcnt_read(m) > 1) {
    // mbuf используется несколькими потоками — нужно клонировать
}
```

---

### Пакетный путь (Packet Path) в DPDK

```
Физический порт → NIC (RX Parser → RSS Hash → Classifier)
  │
  ▼
DMA Engine → Descriptor Ring (VFIO/UIO маппинг)
  │
  ▼
┌─────────────────────────────────────────────────┐
│ PMD (Poll Mode Driver)                          │
│ rte_eth_rx_burst()                              │
│   1. Чтение дескрипторов из RX descriptor ring  │
│   2. Проверка DD (Done Descriptor) bit          │
│   3. Получение mbuf из mempool                  │
│   4. Копирование/DMA данных в mbuf              │
│   5. Обновление метаданных (RSS hash, flags)    │
│   6. Возврат массива mbuf в приложение           │
└─────────────────────────────────────────────────┘
  │
  ▼
Приложение (L2/L3/L4 обработка)
  │
  ▼
┌─────────────────────────────────────────────────┐
│ PMD (TX path)                                   │
│ rte_eth_tx_burst()                              │
│   1. Помещение mbuf в TX descriptor ring        │
│   2. Настройка DMA (размер, offloading)          │
│   3. Запуск передачи (doorbell)                  │
│   4. NIC отправляет данные через MAC              │
│   5. Освобождение mbuf обратно в mempool         │
└─────────────────────────────────────────────────┘
  │
  ▼
MAC → Физический порт
```

**Типичные размеры burst:**

| Пакетный размер | Burst size | Пакетов/сек | Ожидаемый throughput |
| :--- | :--- | :--- | :--- |
| 64 байта | 32 | ~148M | ~100 Gbps (line rate) |
| 128 байта | 32 | ~88M | ~90 Gbps |
| 512 байта | 32 | ~28M | ~115 Gbps |
| 1518 байт | 32 | ~12M | ~146 Gbps (Jumbo) |
| 9000 байт | 32 | ~2M | ~144 Gbps (Jumbo) |

---

### Технологии аппаратного ускорения (2026)

- **Intel DSA (Data Streaming Accelerator)**: Разгрузка CPU от задач копирования памяти. Позволяет перемещать данные между буферами `mbuf` без использования ресурсов ядер.
- **Flow Director (rte_flow)**: Программирование правил классификации пакетов в железе. Например, NIC может аппаратно направлять трафик конкретного VLAN или VXLAN-туннеля на выделенную очередь и ядро.
- **Inline IPsec/TLS**: Шифрование трафика непосредственно в NIC. DPDK через `cryptodev` управляет ключами, а данные шифруются в процессе передачи через PCIe.

#### Расширенные capabilities разгрузки

DPDK предоставляет API для запроса аппаратных возможностей NIC:

```c
#include <rte_ethdev.h>

struct rte_eth_dev_info dev_info;
rte_eth_dev_info_get(port_id, &dev_info);

// Запрос поддерживаемых offload'ов
printf("RX offload caps: 0x%lx\n", dev_info.rx_offload_capa);
// → RX offload caps: 0x3fffff (все offload'ы поддерживается)
// → Биты: RTE_ETH_RX_OFFLOAD_IP_CKSUM, _TCP_CKSUM, _UDP_CKSUM, ...

// Настройка offload'ов при конфигурации порта
struct rte_eth_conf port_conf = {
    .rxmode = {
        .offloads = RTE_ETH_RX_OFFLOAD_CHECKSUM |
                    RTE_ETH_RX_OFFLOAD_SCATTER |
                    RTE_ETH_RX_OFFLOAD_RSS_HASH,
        .mq_mode = RTE_ETH_MQ_RX_RSS,
    },
    .txmode = {
        .offloads = RTE_ETH_TX_OFFLOAD_IP_CKSUM |
                    RTE_ETH_TX_OFFLOAD_TCP_CKSUM |
                    RTE_ETH_TX_OFFLOAD_TCP_TSO,
    },
};
rte_eth_dev_configure(port_id, nb_rx_queues, nb_tx_queues, &port_conf);
```

**Таблица поддерживаемых offload'ов:**

| Offload | Флаг | Описание | Влияние на производительность |
| :--- | :--- | :--- | :--- |
| **IP Checksum** | `RTE_ETH_RX_OFFLOAD_IP_CKSUM` | Аппаратная проверка IP checksum | -5-10% нагрузки на CPU |
| **TCP/UDP Checksum** | `RTE_ETH_RX_OFFLOAD_TCP_CKSUM` | Аппаратная проверка TCP/UDP checksum | -5-10% нагрузки на CPU |
| **RSS** | `RTE_ETH_RX_OFFLOAD_RSS_HASH` | Аппаратный RSS hash для распределения по очередям | -10-15% задержки |
| **TSO** | `RTE_ETH_TX_OFFLOAD_TCP_TSO` | Аппаратная сегментация TCP | -20-30% нагрузки на CPU |
| **Scatter** | `RTE_ETH_RX_OFFLOAD_SCATTER` | Поддержка jumbo frames (multi-segment) | Нет (необходимо для >4KB) |
| **Timestamp** | `RTE_ETH_RX_OFFLOAD_TIMESTAMP` | Аппаратная метка времени | Нет (для HFT) |

---

### Конфигурация памяти и каналов

#### Каналы памяти (Memory Channels)

Параметр `-n` при запуске DPDK-приложения указывает количество каналов памяти. Неправильное значение приводит к снижению производительности на 30-50%.

**Определение количества каналов:**
```bash
# Определение количества каналов памяти
dmidecode -t memory | grep -i "Number of Devices"
# → Number Of Devices: 4  (4 DIMM-слота = 4 канала на односокетной системе)

# Или через lspci
lspci -v | grep -i memory
# → Region 0: Memory at f8000000 (32-bit, non-prefetchable) [size=16M]

# Или через dmidecode
sudo dmidecode -t memory | grep "Locator"
# → Locator: DIMM_A1
# → Locator: DIMM_A2
# → Locator: DIMM_B1
# → Locator: DIMM_B2

# Или через BIOS/UEFI (самый точный способ)
#通常 4 DIMM = 4 channels (DDR4/DDR5)

# Проверка через memcg (если доступно)
cat /sys/devices/system/memory/block_size_bytes
```

**Настройка `-n` при запуске:**
```bash
# Правильно: указать реальное количество каналов
./app -l 2-5 -n 4 --socket-mem 2048,2048
#                             ^^^
#                             4 канала (Intel Xeon 4-канальный, AMD EPYC 8-канальный)

# Неправильно: если channels=4, а -n=2
./app -l 2-5 -n 2 --socket-mem 2048,2048
# → EAL: WARNING: memory channels mismatch (2 vs 4)
# → Производительность снижается на 30-50%

# Автоопределение (рекомендуется)
./app -l 2-5 -n 0 --socket-mem 2048,2048
# → EAL: Auto-detected 4 memory channels
```

**Влияние каналов памяти на производительность:**

| Каналы | Пропускная способность | Relative Performance |
| :--- | :--- | :--- |
| 1 канал DDR4-3200 | 25.6 ГБ/с | 1.0x |
| 2 канала DDR4-3200 | 51.2 ГБ/с | 2.0x |
| 4 канала DDR4-3200 | 102.4 ГБ/с | 4.0x |
| 8 каналов DDR5-4800 | 307.2 ГБ/с | 12.0x |

---

### Практические сценарии настройки

#### 1. Тюнинг параметров загрузки (GRUB)

Для максимальной изоляции ядер и стабильности Hugepages используйте параметры `isolcpus`, `nohz_full` и `rcu_nocbs`. Полный обзор параметров, их назначение и caveats приведены в **[Ядерная изоляция](../../../Linux/Core/kernel/cpu_isolation.md)**.

#### 2. Проверка NUMA-топологии
```bash
# Проверка, к какому узлу подключена карта
cat /sys/class/net/enp1s0/device/numa_node
# Проверка доступной памяти на узле
numastat -m
```

#### 3. Настройка параметров EAL
При запуске приложения важно правильно распределить ресурсы:
```bash
./dpdk_app -l 2,4,6 --socket-mem 2048,2048 --file-prefix=node0 --vdev=net_tap0
```
- `-l`: Список lcores для работы.
- `--socket-mem`: Распределение памяти между сокетами (в МБ).

**Полный список параметров EAL:**

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `-l <cores>` | Список lcores (ядра CPU) | `-l 2-5,8-11` |
| `-n <channels>` | Количество каналов памяти | `-n 4` |
| `--socket-mem <MB,MB>` | HugePages по NUMA-узлам | `--socket-mem 2048,2048` |
| `--file-prefix <name>` | Префикс файлов (изоляция) | `--file-prefix=app1` |
| `--vdev <name>` | Виртуальное устройство | `--vdev=net_tap0` |
| `-w <pci>` | Привязка PCI-устройства | `-w 0000:01:00.0` |
| `--log-level <type>,<level>` | Уровень логирования | `--log-level=pmd,5` |
| `--no-pci` | Отключить PCI (для vdev) | `--no-pci` |
| `-m <MB>` | Общий объём HugePages (legacy) | `-m 4096` |
| `--huge-dir <path>` | Директория HugePages | `--huge-dir=/dev/hugepages-1G` |
| `--proc-type <type>` | Тип процесса (primary/secondary) | `--proc-type=secondary` |

#### 4. Конфигурация PMD (Poll Mode Driver)

**Настройка burst size:**
```bash
# Типичная конфигурация для 100Gbps NIC
./app -l 2-5 -n 4 --socket-mem 2048,2048 -- \
  --rxq=1024 --txq=1024 \
  --rxd=1024 --txd=1024 \
  --burst=32

# Параметры:
# --rxq/--txq: Количество RX/TX очередей
# --rxd/--txd: Размер RX/TX дескрипторных колец
# --burst: Количество пакетов за один вызов rx_burst/tx_burst
```

**PMD thread architecture:**
```
┌─────────────────────────────────────────────┐
│ PMD Thread (привязан к lcore)              │
│                                             │
│ while (1) {                                │
│     // RX: опрос NIC                        │
│     nb_rx = rte_eth_rx_burst(port, qid,    │
│                               pkts, burst); │
│                                             │
│     // Processing: обработка пакетов         │
│     for (i = 0; i < nb_rx; i++) {          │
│         process(pkts[i]);                   │
│     }                                      │
│                                             │
│     // TX: передача в NIC                    │
│     rte_eth_tx_burst(port, qid,            │
│                       pkts, nb_rx);         │
│ }                                          │
│                                             │
│ При nb_rx == 0: цикл продолжается          │
│ (busy-polling, 100% CPU)                   │
└─────────────────────────────────────────────┘
```

**Adaptive polling (адаптивный опрос):**
```bash
# Включение адаптивного опроса (снижение CPU при отсутствии трафика)
./app -l 2-5 -n 4 --socket-mem 2048,2048 -- \
  --adaptive-polling

# Включение через rte_eth_dev_callback
rte_eth_dev_callback_register(port_id,
                              RTE_ETH_EVENT_INTR_LSC,
                              link_status_change_handler,
                              NULL);
```

---

### Диагностика производительности

| Инструмент | Что проверять | Пример использования |
| :--- | :--- | :--- |
| **`dpdk-proc-info`** | Просмотр статистики очередей, ошибок и оффлоудов в реальном времени. | `./build/app/dpdk-proc-info --file-prefix=app1 --stats` |
| **`pcm-memory`** | Мониторинг пропускной способности шины памяти и задержек QPI/UPI. | `pcm-memory 1` (обновление каждую секунду) |
| **`perf top`** | Выявление «горячих» функций (например, если Polling тратит 100% времени впустую). | `perf top -g -p $(pgrep testpmd)` |
| **`ethtool -S`** | Аппаратные счетчики NIC (отброшенные пакеты, переполнения FIFO). | `ethtool -S enp1s0 | grep -i error` |
| **`rte_metrics`** | Пользовательские метрики DPDK ( создание пользовательских счётчиков). | `rte_metrics_reg_name("my_counter"); rte_metrics_update_value(...)` |
| **`dpdk-test-compress-perf`** | Тестирование производительности аппаратного сжатия (compression offload). | `./build/app/dpdk-test-compress-perf -l 2-3 -n 4` |
| **`tshark` / `tcpdump`** | Анализ трафика (с ограничениями — DPDK не использует的标准网络 стек). | См. ниже «Перехват трафика DPDK» |
| **`numastat -p <pid>`** | Потребление HugePages по NUMA-узлам для конкретного процесса. | `numastat -p $(pgrep testpmd)` |

**Перехват трафика DPDK (нет стандартного tcpdump):**
```bash
# Вариант 1: Использование KNI (Kernel NIC Interface)
# DPDK-приложение перенаправляет часть трафика через ядро
./app -l 2-3 -n 4 --vdev=net_kni0
# → В другом терминале:
tcpdump -i kni0 -w dump.pcap

# Вариант 2: Использование testpmd в режиме capture
./build/app/testpmd -l 2-3 -n 4 -w 0000:01:00.0 \
  -- --forward-mode=mac --capture
# → В testpmd: > set fwd mac
# → В testpmd: > start
# → Пакеты логируются в файлы pcap

# Вариант 3: Использование DPDK pdump
./build/app/dpdk-pdump --file-prefix=app1 -- \
  --pdump='port=0,queue=*,rx-dev=/tmp/rx.pcap,tx-dev=/tmp/tx.pcap'
```

---

### Типичные ошибки и устранение неисправностей

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| `EAL: Cannot open /dev/vfio/X` | DPDK-приложение не стартует | VF не привязана к vfio-pci | `dpdk-devbind.py --bind=vfio-pci <pci_addr>` |
| `EAL: IOVA mapping failed` | DPDK-приложение не стартует | IOMMU не включён | Параметр ядра `intel_iommu=on iommu=pt` |
| `EAL: No available hugepages` | DPDK-приложение не стартует | HugePages не выделены | `echo N > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages` |
| `EAL: Could not open UIO` | DPDK-приложение не стартует | Модуль uio_pci_generic не загружен | `sudo modprobe uio_pci_generic` или используйте vfio-pci |
| `PMD: Failed to start port` | NIC не инициализируется | NIC занята другим процессом | Остановите другие DPDK-приложения или OVS |
| `PMD: Failed to setup port` | NIC не инициализируется | NIC не поддерживается PMD | Проверьте поддержку NIC: `dpdk-pmdinfo.py` |
| 0 пакетов в testpmd | TX-pps = 0, RX-pps = 0 | NIC не подключена к источнику трафика | Проверьте физическое подключение; в testpmd: `start` |
| Высокий jitter (нестабильные задержки) | P99 задержка >> P50 | NUMA-несоответствие, IRQ конфликты | Проверьте NUMA-локальность; привязьте IRQ; используйте HugePages |
| `EAL: Invalid port` | Ошибка при вызове rte_eth_* | Порт не инициализирован | Проверьте `rte_eth_dev_configure()` вызов до `rte_eth_dev_start()` |
| Ошибки при `rte_mempool_create` | DPDK-приложение не стартует | Недостаточно HugePages | Увеличьте количество HugePages; уменьшите `--socket-mem` |
| `EAL: memory channels mismatch` | Предупреждение при запуске | Неправильный параметр `-n` | Укажите реальное количество каналов или используйте `-n 0` (авто) |
| `EAL: Cannot malloc` | DPDK-приложение не стартует | Мало HugePages для `--socket-mem` | Увеличьте HugePages; уменьшите `--socket-mem` |

**Диагностические команды:**
```bash
# Проверка логов ядра на ошибки DPDK/VFIO
dmesg | grep -iE "vfio|iommu|uio" | tail -20

# Проверка статуса PCI-устройств
lspci -v -s 0000:01:00.0

# Проверка используемых HugePages
cat /proc/meminfo | grep -i huge

# Мониторинг CPU (busy-polling использует 100% ядра)
top -p $(pgrep testpmd)

# Проверка NUMA-топологии
numactl --hardware

# Проверка расстояний NUMA (влияние на latency)
cat /sys/devices/system/node/node*/meminfo | grep -A5 "Huge"

# Проверка что NIC привязана к vfio-pci
./usertools/dpdk-devbind.py --status | grep -A2 "DPDK-compatible"

# Проверка размера кэши CPU (влияние на prefetching)
lscpu | grep "cache"
# → L1d cache:           48K
# → L1i cache:           32K
# → L2 cache:            2048K
# → L3 cache:            36864K
```

---

### Очистка

```bash
# 1. Остановка DPDK-приложения
# (В интерактивном режиме testpmd: > quit)
# Или через Ctrl+C

# 2. Отвязка NIC от vfio-pci (вернуть к kernel driver)
sudo ./usertools/dpdk-devbind.py -b ice 0000:01:00.0
# Или:
sudo ./usertools/dpdk-devbind.py -b i40e 0000:01:00.0

# 3. Проверка что NIC вернулась к kernel driver
./usertools/dpdk-devbind.py --status
# → Network devices using kernel driver
# → 0000:01:00.0 'Device 1592' if= enp1s0f0 drv=ice unused=vfio-pci

# 4. Освобождение HugePages (если больше не нужны)
echo 0 | sudo tee /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages
# Или для 1GB страниц:
echo 0 | sudo tee /sys/kernel/mm/hugepages/hugepages-1048576kB/nr_hugepages

# 5. Проверка
cat /proc/meminfo | grep -i huge
# → HugePages_Total:    0
# → HugePages_Free:     0

# 6. Удаление DPDK (если больше не нужен)
cd dpdk && sudo ninja -C build uninstall
cd .. && rm -rf dpdk
sudo ldconfig
```

---

### Дополнительная информация

- **[Обзор DPDK](dpdk_overview.md)** — архитектура обхода ядра и работа PMD.
- **[RSS в DPDK](dpdk_rss.md)** — аппаратное распределение трафика по ядрам CPU.
- **[rte_flow API](dpdk_rte_flow.md)** — программирование фильтрации пакетов в железе NIC.
- **[Тестирование и бенчмаркинг](dpdk_testing.md)** — RFC 2544, трафик-генераторы, метрики.
- **[DPDK Bonding](dpdk_bonding.md)** — LACP, failover, балансировка.
- **[QoS / Metering](dpdk_qos.md)** — rte_mtr, rte_sched, DCB/ETS.
- **[Multi-process DPDK](dpdk_multiprocess.md)** — primary/secondary модель.
- **[Отладка DPDK](dpdk_debugging.md)** — gdb, core dump, logging, valgrind.
- **[Cryptodev / IPsec](dpdk_cryptodev.md)** — inline vs lookaside crypto, QAT.
- **[Hotplug](dpdk_hotplug.md)** — динамическое добавление/удаление NIC.
- **[io_uring / AF_XDP vs DPDK](dpdk_io_uring_vs_afxdp.md)** — сравнение альтернатив.
- **[Service Function Chaining](dpdk_sfc.md)** — NSH, VxLAN-GPE, pipeline.
- **[KNI / Tap / vhost-user](dpdk_kni.md)** — взаимодействие с kernel network stack.
- **[Безопасность DPDK](dpdk_security.md)** — trust, spoof, MACsec.
- **[Обзор SR-IOV](sriov.md)** — аппаратная виртуализация, часто используемая совместно с DPDK.
- **[Настройка SR-IOV](sriov_setup.md)** — практическое руководство по подготовке среды.
- **[Практические сценарии DPDK и SR-IOV](scenarios.md)** — интеграция с Kubernetes и AI Fabric.
- **[Оптимизация сетевых задержек](../../Linux/Networking/Concepts/network_latency_optimization.md)** — тюнинг сетевого стека для Low Latency.
- **[CPU pinning](../../Linux/Core/cpu_pinning.md)** — привязка процессов к ядрам CPU.
- **[Ядерная изоляция](../../Linux/Core/kernel/cpu_isolation.md)** — isolcpus, nohz_full, rcu_nocbs.
- **[Оптимизация HugePages](../../Linux/Core/memory/performance_tuning.md)** — HugePages в контексте Linux.
- **[DPDK и SR-IOV: Сравнение](sriov.md#сравнение-dpdk-и-sr-ov)** — когда использовать DPDK, а когда SR-IOV.
