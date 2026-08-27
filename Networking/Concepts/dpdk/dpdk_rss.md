# RSS (Receive Side Scaling) в DPDK

### Определения

- **RSS (Receive Side Scaling)**: Аппаратный механизм NIC для распределения входящего трафика по нескольким RX-очередям (и ядрам CPU) на основе хэша заголовков пакета. Позволяет масштабировать обработку на несколько ядер без locks.
- **Toeplitz hash**: Стандартная хэш-функция, используемая в RSS (RFC 3550 для RTP, адаптирована для NIC). Работает как свёртка (convolution) по Toeplitz-матрице. Используется Intel, NVIDIA, Broadcom.
- **Symmetric RSS**: Режим, при котором RX- и TX-трафик для одного потока (5-tuple) попадают на одно и то же ядро. Критично для stateful processing (NAT, firewall, load balancer).
- **RSS reta (Redirection Table)**: Таблица размером 128/512/1024 entries,映射 hash → queue. Позволяет динамически переназначать потоки между ядрами без перезапуска NIC.
- **RSS hash key**: Конфигурируемый ключ (40/52 байта) для Toeplitz-функции. Разные ключи = разное распределение трафика.
- **RSSHF (RSS Hash Function)**: Маска битов, определяющая какие поля пакета участвуют в хэшировании (L2/L3/L4, IPv4/IPv6, TCP/UDP).
- **Flow Director (FDir)**: Аппаратный механизм для точного сопоставления пакетов (exact match) с действиями (queue/mark/flag). Дополняет RSS: RSS = coarse-grained (hash-based), FDir = fine-grained (exact-match).
- **ethtool -X / -n / -u**: Linux-утилиты для настройки RSS (hash key, reta, flow rules) на NIC.
- **ethtool -S**: Аппаратные счётчики NIC (RX queues drops, RSS errors, FDir matches).
- **rte_eth_rss_conf**: Структура DPDK API для конфигурации RSS при инициализации порта.

---

### Теория

#### 1. Как работает RSS в NIC

```
Входящий пакет
  │
  ▼
┌─────────────────────────────────────────────┐
│ NIC Parser                                  │
│ 1. Извлечение полей из заголовков:          │
│    - src_ip, dst_ip (L3)                   │
│    - src_port, dst_port (L4)               │
│    - protocol (TCP/UDP/other)              │
│ 2. Вычисление Toeplitz hash:                │
│    hash = toeplitz(key, fields)             │
│ 3. Применение маски rss_hf:                │
│    masked_fields = fields & rss_hf          │
│ 4. Выбор queue по reta:                     │
│    queue = reta[hash % reta_size]           │
│ 5. Пометка mbuf: pkt_hash = hash            │
│    (DPDK читает через rte_mbuf->hash)       │
└─────────────────────────────────────────────┘
  │
  ▼
Queue 0 → lcore 0  ──┐
Queue 1 → lcore 1  ──┤
Queue 2 → lcore 2  ──┤  Каждый lcore обрабатывает
Queue 3 → lcore 3  ──┘  свою порцию трафика
```

**Ключевые правила:**
- Один и тот же поток (5-tuple: src_ip, dst_ip, src_port, dst_port, proto) всегда попадает в одну очередь → обработка на одном ядре → нет contention
- Каждый NIC имеет RSS-модуль; он работает в hardware, без участия CPU
- RSS hash записывается в `mbuf->hash.rss` → приложение может использовать его для further processing

#### 2. Hash-функции и ключ

**Toeplitz hash (основной алгоритм):**
```
Для пакета с полями [F1, F2, F3, F4] (например, src_ip=10.0.0.1, dst_ip=10.0.0.2, src_port=1234, dst_port=80):

1. Конкатенация полей в битовый вектор:
   bits = F1 || F2 || F3 || F4  ( может быть 104+ бит для IPv6)

2. Toeplitz-свёртка с ключом K (40/52 байта):
   hash = 0
   for i in 0..bits_len-1:
       if bits[i] == 1:
           hash ^= (K[i..i+31])  // XOR с 32-битным окном ключа

3. Результат: 32-битный hash
```

**Типичные ключи:**
```bash
# Стандартный ключ Intel (RFC 3550)
0x6d5a56da2557856e  # Первые 8 байт
0x2557856e2557856e  # Повторяющийся паттерн
0x6d5a56da2557856e

# Симметричный ключ (отличается от стандартного)
# Гарантирует: hash(A→B) == hash(B→A)
0x0000000000000000  # Нулевой ключ = fallback
```

**rss_hf (RSS Hash Function) — маски полей:**
```c
// Типичные маски
RTE_ETH_RSS_IPV4     // IPv4 src/dst
RTE_ETH_RSS_IPV6     // IPv6 src/dst
RTE_ETH_RSS_IPV4_EXT // IPv4 с расширенными полями
RTE_ETH_RSS_IPV6_EXT // IPv6 с расширенными полями
RTE_ETH_RSS_TCP      // TCP src_port, dst_port
RTE_ETH_RSS_UDP      // UDP src_port, dst_port
RTE_ETH_RSS_SCTP     // SCTP
RTE_ETH_RSS_PORT     // Только порты (без IP)
RTE_ETH_RSS_IP       // = IPv4 | IPv6
RTE_ETH_RSS_L3       // = IP (v4+v6)
RTE_ETH_RSS_L4       // = TCP | UDP | SCTP
RTE_ETH_RSS_IP_TCP   // = IPv4 | IPv6 | TCP
RTE_ETH_RSS_IP_UDP   // = IPv4 | IPv6 | UDP

// Комбинации для типичных сценариев
RTE_ETH_RSS_IP | RTE_ETH_RSS_TCP | RTE_ETH_RSS_UDP  // Полный 5-tuple hash
```

#### 3. Symmetric RSS

**Проблема без symmetric RSS:**
```
Отправитель (A) → Получатель (B):
  hash(A→B) = 0x3A7F  → Queue 3 → lcore 3

Ответ (B→A):
  hash(B→A) = 0x1B2C  → Queue 1 → lcore 1

Результат: RX и TX обрабатываются на РАЗНЫХ ядрах.
Для stateful приложений (NAT, conntrack) это проблема:
  - lcore 3 не знает о state, созданном lcore 1
  - Нужна синхронизация через mempool/lock → потеря производительности
```

**Решение — Symmetric RSS:**
```
hash(A→B) == hash(B→A)  →  Queue 3  →  lcore 3
                                          ↑
                                    Один и тот же core
                                    обрабатывает оба направления
```

**Как достичь symmetric RSS:**

**Способ 1: Симметричный ключ**
```c
// Ключ, при котором hash(A,B) == hash(B,A)
// ДляToeplitz: достаточно использовать ключ, где K[i..i+31] = K[i+32..i+63]
// (зеркальный паттерн)
static const uint8_t symmetric_rss_key[40] = {
    0x6d, 0x5a, 0x56, 0xda, 0x25, 0x57, 0x85, 0x6e,
    0x25, 0x57, 0x85, 0x6e, 0x6d, 0x5a, 0x56, 0xda,
    0x25, 0x57, 0x85, 0x6e, 0x25, 0x57, 0x85, 0x6e,
    0x6d, 0x5a, 0x56, 0xda, 0x25, 0x57, 0x85, 0x6e,
    0x25, 0x57, 0x85, 0x6e, 0x6d, 0x5a, 0x56, 0xda
};

struct rte_eth_rss_conf rss_conf = {
    .rss_key = symmetric_rss_key,
    .rss_hf = RTE_ETH_RSS_IP | RTE_ETH_RSS_TCP | RTE_ETH_RSS_UDP,
};
rte_eth_dev_configure(port_id, nb_rx, nb_tx, &port_conf);
```

**Способ 2: Локальный XOR (программный, в приложении)**
```c
// После получения пакета через rte_eth_rx_burst:
uint32_t hash = m->hash.rss;
uint32_t symmetric_hash = hash ^ (hash >> 16);
uint32_t queue = symmetric_hash % nb_queues;
// Проблема: программная обработка добавляет latency
```

**Способ 3: NIC-specific (Intel E810)**
```bash
# Intel E810: symmetric RSS через ethtool
ethtool -X enp1s0 hkey 6d5a56da2557856e2557856e6d5a56da2557856e2557856e...
# NIC автоматически применяет зеркальный ключ
```

#### 4. RSS Reta (Redirection Table)

**Структура reta:**
```
reta_size = 128 / 512 / 1024  (зависит от NIC)

reta[0] → queue 0
reta[1] → queue 1
reta[2] → queue 2
...
reta[reta_size-1] → queue N

Адресация: queue = reta[hash % reta_size]
```

**Зачем менять reta в рантайме:**
- Перераспределение трафика при изменении нагрузки
- Изоляция потоков (hot flow → отдельное ядро)
- Балансировка при добавлении/удалении ядер

**DPDK API для reta:**
```c
#include <rte_ethdev.h>

// Получение reta
struct rte_eth_rss_reta_entry reta_conf[64];  // 64 entries за раз
reta_conf[0].mask = UINT64_MAX;  // Запросить все 64 entry

rte_eth_dev_rss_reta_query(port_id, reta_conf, 64);
for (int i = 0; i < 64; i++) {
    printf("reta[%d] → queue %d\n", i, reta_conf[i].queue);
}

// Установка reta (для 4 ядер)
struct rte_eth_rss_reta_entry new_reta[64];
for (int i = 0; i < 64; i++) {
    new_reta[i].queue = i % 4;  // Round-robin по 4 очередям
    new_reta[i].mask = UINT64_MAX;
}
rte_eth_dev_rss_reta_update(port_id, new_reta, 64);

// Тестирование: куда попадёт конкретный 5-tuple
uint32_t test_hash = rte_softrss((uint32_t[]){
    src_ip, dst_ip, src_port, dst_port, proto
}, 5, symmetric_rss_key);
uint32_t queue = test_hash % 64;
```

#### 5. RSS vs Flow Director vs rte_flow

| Критерий | RSS | Flow Director (FDir) | rte_flow |
| :--- | :--- | :--- | :--- |
| **Принцип** | Hash-based (coarse) | Exact-match (fine) | Unified API (flexible) |
| **Точность** | Один и тот же поток → одно ядро | Точно指定流 →指定 действие | Любые правила |
| **Действия** | Только queue selection | queue, mark, flag, drop | queue, drop, mark, mirror, passthru, count |
| **Количество rules** | 1 (hash key) | 8K-128K (зависит от NIC) | ~16K (зависит от NIC) |
| **Обновление** | Перезапуск NIC или runtime | Runtime | Runtime |
| **Когда использовать** | Всегда (default) | Stateful NAT, специфичные потоки | Complex filtering, SFC |
| **Задержка** | Hardware (0 циклов CPU) | Hardware (0 циклов CPU) | Hardware (0 циклов CPU) |

#### 6. Мониторинг RSS

```bash
# Текущая конфигурация RSS
ethtool -g enp1s0        # RX/TX ring sizes
ethtool -k enp1s0 | grep rss  # RSS включён?

# Просмотр hash key
ethtool -x enp1s0        # Текущий ключ и команда

# Просмотр reta (8 entry за раз, 0-7, 8-15, ...)
ethtool -n enp1s0        # Фильтры NIC (включая RSS)
ethtool -u enp1s0        # Активные фильтры

# Счётчики ошибок RSS (аппаратные)
ethtool -S enp1s0 | grep -i rss
# → rx_rss_hits: 123456789
# → rx_rss_miss: 0
# → rx_rss_err: 0

# Распределение пакетов по queue
ethtool -S enp1s0 | grep -i "rx.*queue"
# → rx-0.packets: 3456789
# → rx-1.packets: 3456789
# → rx-2.packets: 3456788
# → rx-3.packets: 3456789
```

**DPDK API мониторинг:**
```c
// Запрос распределения reta
struct rte_eth_rss_reta_entry reta[64];
for (int i = 0; i < reta_size; i += 64) {
    reta[0].mask = 0xFFFFFFFFFFFFFFFF;
    rte_eth_dev_rss_reta_query(port_id, reta, 64);
    // Вывод reta[i..i+63]
}

// Проверка hash конкретного пакета
uint32_t pkt_hash = m->hash.rss;
printf("Packet hash: 0x%08x → queue %d\n", pkt_hash, pkt_hash % nb_queues);
```

---

### Практическое руководство

#### 1. Конфигурация RSS при запуске DPDK-приложения

```c
// Типичная конфигурация RSS для 100Gbps NIC с 4 ядрами
struct rte_eth_conf port_conf = {
    .rxmode = {
        .mq_mode = RTE_ETH_MQ_RX_RSS,
        .offloads = RTE_ETH_RX_OFFLOAD_CHECKSUM |
                    RTE_ETH_RX_OFFLOAD_RSS_HASH,
    },
    .rx_adv_conf = {
        .rss_conf = {
            .rss_key = symmetric_rss_key,   // Симметричный ключ
            .rss_hf = RTE_ETH_RSS_IP |      // IPv4 + IPv6
                      RTE_ETH_RSS_TCP |     // TCP ports
                      RTE_ETH_RSS_UDP,      // UDP ports
        },
    },
};

rte_eth_dev_configure(port_id, nb_rx_queues, nb_tx_queues, &port_conf);
```

#### 2. Проверка RSS на testpmd

```bash
# Запуск testpmd с RSS
./build/app/testpmd -l 2-5 -n 4 -w 0000:01:00.0 --socket-mem 2048,0 -- \
  --forward-mode=io --rxq=4 --txq=4 --rxd=1024 --txd=1024 --stats-period=1

# В testpmd:
# show port info 0
# → RSS: on
# → RSS hash function: Toeplitz
# → RSS key: 6d5a56da2557856e...
# → RX queues: 4
# → RSS hfeld: IP TCP UDP

# Тест с trivia-трафиком (iperf3 в фоне)
# show port stats 0
# → rx-0.packets: XXX  ← распределение по queue
# → rx-1.packets: XXX
# → rx-2.packets: XXX
# → rx-3.packets: XXX
```

#### 3. Настройка symmetric RSS на Intel E810

```bash
# 1. Включить symmetric RSS
ethtool -X enp1s0 hkey 6d5a56da2557856e2557856e6d5a56da2557856e2557856e...

# 2. Установить symmetric toeplitz
ethtool -X enp1s0 equal 4  # 4 queues, symmetric распределение

# 3. Проверка
ethtool -x enp1s0
# → RSS hash key: 6d5a56da...
# → RSS equals: 4
# → Текущий распределение: 0→0, 1→1, 2→2, 3→3

# 4. Тест: пинг между двумя хостами
ping -c 10 10.0.0.2
# На обоих хостах: rx-0.packets растёт (оба направления на одном ядре)
```

#### 4. Динамическое обновление reta

```c
// Пример: перераспределение трафика при изменении нагрузки
void redistribute_traffic(uint16_t port_id, uint16_t new_nb_queues) {
    struct rte_eth_rss_reta_entry reta[1024];
    int reta_size = 1024;

    for (int i = 0; i < reta_size; i++) {
        reta[i].queue = i % new_nb_queues;
        reta[i].mask = UINT64_MAX;
    }

    int ret = rte_eth_dev_rss_reta_update(port_id, reta, reta_size);
    if (ret < 0) {
        printf("Failed to update reta: %s\n", rte_strerror(-ret));
    }
}
```

#### 5. Тестирование hash-распределения

```bash
# Сравнение распределения с разными ключами
python3 -c "
import struct

def toeplitz_hash(key, fields):
    # Упрощённый Toeplitz hash
    result = 0
    for i, field in enumerate(fields):
        for bit in range(32):
            if field & (1 << (31 - bit)):
                result ^= (key[i // 8] << (24 - (i % 8) * 8)) >> bit
    return result & 0xFFFFFFFF

key = bytes.fromhex('6d5a56da2557856e2557856e6d5a56da2557856e')
fields = [0x0A000001, 0x0A000002, 0x04D2, 0x0050]  # 10.0.0.1→10.0.0.2:1234→80
hash_val = toeplitz_hash(key, fields)
print(f'hash(A→B): 0x{hash_val:08x} → queue {hash_val % 4}')
print(f'hash(B→A): 0x{toeplitz_hash(key, [0x0A000002, 0x0A000001, 0x0050, 0x04D2]):08x} → queue {toeplitz_hash(key, [0x0A000002, 0x0A000001, 0x0050, 0x04D2]) % 4}')
"
```

---

### Типичные ошибки

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| RSS не распределяет трафик | Все пакеты идут в одну queue | rss_hf = 0 или не задан | Проверьте `rss_hf` в `rte_eth_rss_conf` |
| Асимметричное распределение | TX и RX на разных ядрах | Обычный Toeplitz key (не symmetric) | Используйте symmetric key или `ethtool -X equal N` |
| reta не обновляется | `rte_eth_dev_rss_reta_update` возвращает -EINVAL | reta_size не поддерживается NIC | Проверьте `dev_info.reta_size` (128/512/1024) |
| RSS miss пакетов | `rx_rss_miss` > 0 в `ethtool -S` | NIC не может обработать все пакеты (overload) | Увеличьте количество queue, уменьшите burst size |
| FDir vs RSS конфликт | Пакеты не попадают в нужную queue | FDir rule перехватывает трафик | Проверьте FDir rules: `ethtool -u` |

---

### Дополнительная информация

- **[DPDK: RSS vs XDP vs AF_XDP](dpdk_overview.md)** — сравнение механизмов распределения.
- **[RSS в Linux (RPS/RFS)](../../Linux/Networking/Concepts/rss_rps_rfs.md)** — аппаратный и программный RSS в kernel.
- **[DPDK: rte_flow API](dpdk_rte_flow.md)** — программирование фильтрации в железе (дополняет RSS).
- **[DPDK: Тестирование и бенчмаркинг](dpdk_testing.md)** — как проверить распределение RSS на практике.
- **[DPDK: Низкая задержка (HFT)](scenarios.md#сценарий-5-hft--ультра-низкая-задержка)** — symmetric RSS для HFT.
- **[Intel E810 RSS Configuration Guide](https://www.intel.com/content/www/us/en/content-details/671501/intel-ethernet-controller-e810-rss-configuration-guide.html)** — официальный гайд по RSS на E810.
