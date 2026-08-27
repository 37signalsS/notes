# io_uring / AF_XDP vs DPDK — Сравнение

### Определения

- **io_uring**: Механизм асинхронного I/O в Linux kernel (появился в kernel 5.1, 2019). Предоставляет efficient ring buffer для обмена I/O запросами между userspace и kernel. Поддерживает async read/write, networking (send/recv), файловые операции.
- **AF_XDP (Address Family XDP)**: Семейство сокетов в Linux, позволяющее userspace-приложениям получать и отправлять пакеты напрямую через XDP (eBPF), без прохождения через kernel network stack. Поддерживает zero-copy mode.
- **Zero-copy AF_XDP**: Режим AF_XDP, при котором NIC DMA-копирует данные напрямую в UMEM (userspace memory), пропуская kernel. Доступен на некоторых NIC (Intel, Mellanox).
- **XDP (eXpress Data Path)**: Программируемый data path в Linux kernel, работающий на уровне driver (before kernel stack). Позволяет обрабатывать пакеты на уровне 10-100 Mpps.
- **UMEM**: Область памяти в userspace, используемая AF_XDP для хранения пакетов. Похожа на mempool в DPDK, но управляется kernel.
- **Completion Queue (CQ)**: В io_uring — очередь завершённых операций. Kernel записывает результаты операций в CQ, userspace читает их.
- **Submission Queue (SQ)**: В io_uring — очередь запросов на выполнение. Userspace записывает I/O запросы в SQ, kernel забирает их и выполняет.
- **SQPOLL**: Режим io_uring, при котором kernel thread постоянно опрашивает SQ (без syscall). Снижает latency, но увеличивает CPU usage.
- **Network offload**: Аппаратная разгрузка NIC (checksum, RSS, TSO). Поддерживается в io_uring (через kernel driver) и DPDK (через PMD).

---

### Теория

#### 1. Архитектура: DPDK vs io_uring vs AF_XDP

```
DPDK (полный kernel bypass):
┌────────────────────────────────────────────────┐
│ Application                                     │
│ ├── rte_eth_rx_burst()   (busy-polling)        │
│ ├── rte_eth_tx_burst()                            │
│ └── PMD (Userspace driver)                     │
│     └── NIC硬件 (DMA → HugePages)               │
└────────────────────────────────────────────────┘
Прямой доступ к NIC, 0 kernel involvement

io_uring (async I/O, kernel-based):
┌────────────────────────────────────────────────┐
│ Application                                     │
│ ├── io_uring_prep_send() (async)               │
│ ├── io_uring_submit()   (syscall или SQPOLL)  │
│ └── kernel                                   │
│     ├── NIC driver                            │
│     └── kernel network stack                  │
│         └── TCP/IP processing                 │
└────────────────────────────────────────────────┘
Kernel управляет NIC, async I/O через ring buffers

AF_XDP (zero-copy XDP, kernel-bypass):
┌────────────────────────────────────────────────┐
│ Application                                     │
│ ├── xsk_ringprod__submit() (отправка)         │
│ ├── xsk_ringcons__peek()   (получение)        │
│ └── UMEM (userspace memory)                   │
│     └── NIC driver (XDP, zero-copy)           │
└────────────────────────────────────────────────┘
Zero-copy через XDP, minimal kernel involvement
```

#### 2. Сравнение производительности

| Метрика | DPDK | io_uring | AF_XDP |
| :--- | :--- | :--- | :--- |
| **Latency (P50)** | ~1-2 мкс | ~5-10 мкс | ~3-5 мкс |
| **Latency (P99)** | ~2-5 мкс | ~10-30 мкс | ~5-15 мкс |
| **Throughput (100G)** | Line-rate (148 Mpps) | ~50-80 Mpps | ~80-120 Mpps |
| **Throughput (10G)** | ~14.8 Mpps | ~5-8 Mpps | ~10-12 Mpps |
| **CPU usage** | 100% (busy-poll) | 10-30% (async) | 50-80% (busy-poll) |
| **Kernel involvement** | 0% (bypass) | 100% (kernel driver) | ~10% (XDP only) |
| **Memory model** | HugePages (mlock) | kernel buffers | UMEM (zero-copy) |
| **RSS support** | Hardware RSS | Kernel RSS | XDP RSS |
| **Offload support** | Full (PMD) | Full (kernel) | Limited (XDP) |

#### 3. Когда что использовать

| Сценарий | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| **HFT (sub-microsecond)** | DPDK | Минимальная latency, полный контроль |
| **5G UPF (100G+)** | DPDK | Wire-speed, hardware offload |
| **NFV (high throughput)** | DPDK | Контроль pipeline, mempool |
| **Cloud networking** | AF_XDP | Простота, kernel integration |
| **Microservices (L7)** | io_uring | Async I/O, kernel TCP/IP |
| **Storage + Network** | io_uring | Unified async I/O model |
| **Development/testing** | AF_XDP | Проще чем DPDK, kernel stack |
| **Mixed workload** | DPDK + io_uring | Best of both worlds |

#### 4. Ключевые различия

**DPDK vs io_uring:**
- DPDK: busy-polling, 100% CPU, минимальная latency
- io_uring: async I/O, ~10-30% CPU, kernel TCP/IP, более высокая latency
- io_uring проще в разработке (стандартный socket API через async)
- DPDK сложнее, но даёт полный контроль над data path

**DPDK vs AF_XDP:**
- AF_XDP: проще чем DPDK (стандартный socket API), kernel RSS
- DPDK: больше offload, больше control, выше throughput на 100G+
- AF_XDP: zero-copy через XDP driver, не требует vfio-pci
- DPDK: требует vfio-pci binding, HugePages, EAL init

**io_uring vs AF_XDP:**
- io_uring: async I/O для всех типов (network, file, timer)
- AF_XDP: только L2/L3 пакеты (без kernel TCP/IP)
- io_uring: полный kernel TCP/IP стек
- AF_XDP: без TCP/IP (нужен userspace stack)

---

### Практическое руководство

#### 1. Пример AF_XDP

```c
#include <linux/if_xdp.h>
#include <bpf/xsk.h>

// Создание UMEM
struct xsk_umem_config umem_cfg = {
    .fill_size = XSK_RING_PROD__DEFAULT_NUM_DESCS,
    .comp_size = XSK_RING_CONS__DEFAULT_NUM_DESCS,
    .frame_size = XSK_UMEM__DEFAULT_FRAME_SIZE,
    .frame_headroom = XSK_UMEM__DEFAULT_FRAME_HEADROOM,
};

void *umem_area = malloc(UMEM_SIZE);
struct xsk_umem *umem;
xsk_umem_create(&umem, umem_area, UMEM_SIZE, &fill, &comp, &umem_cfg);

// Создание socket
struct xsk_socket_config sk_cfg = {
    .rx_size = XSK_RING_CONS__DEFAULT_NUM_DESCS,
    .tx_size = XSK_RING_PROD__DEFAULT_NUM_DESCS,
    .bind_flags = XDP_ZEROCOPY,  // Zero-copy mode
};

struct xsk_socket *xsk;
struct xsk_ring_cons rx;
struct xsk_ring_prod tx;
xsk_socket_create(&xsk, "eth0", queue_id, umem, &rx, &tx, &sk_cfg);

// Получение пакетов
unsigned int idx;
while (1) {
    // Проверка наличия пакетов
    unsigned int rcvd = xsk_ring_cons__peek(&rx, 32, &idx);
    if (rcvd > 0) {
        for (unsigned int i = 0; i < rcvd; i++) {
            const struct xdp_desc *desc = xsk_ring_cons__rx_desc(&rx, idx++);
            void *pkt = xsk_umem__get_data(umem, desc->addr);
            // Обработка пакета
            process_packet(pkt, desc->len);
        }
        // Возврат обработанных UMEM frames
        xsk_ring_prod__submit(&fill, rcvd);
    }
}

// Отправка пакетов
unsigned int tx_idx;
xsk_ring_prod__reserve(&tx, 1, &tx_idx);
struct xdp_desc *tx_desc = xsk_ring_prod__tx_desc(&tx, tx_idx);
tx_desc->addr = xsk_umem__add_to_fill_ring(&fill, pkt_data);
tx_desc->len = pkt_len;
xsk_ring_prod__submit(&tx, 1);
```

#### 2. Пример io_uring networking

```c
#include <liburing.h>

struct io_uring ring;
io_uring_queue_init(256, &ring, 0);

// Подготовка send operation
struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
io_uring_prep_send(sqe, sockfd, data, len, 0);
io_uring_sqe_set_data(sqe, context);

// Отправка запроса
io_uring_submit(&ring);

// Ожидание завершения
struct io_uring_cqe *cqe;
io_uring_wait_cqe(&ring, &cqe);

// Проверка результата
int result = cqe->res;
if (result > 0) {
    printf("Sent %d bytes\n", result);
}

io_uring_cqe_seen(&ring, cqe);
```

#### 3. Сравнение: DPDK vs AF_XDP throughput test

```bash
# DPDK: testpmd loopback
./build/app/testpmd -l 2-3 -n 4 -w 0000:01:00.0 --socket-mem 1024,0 -- \
  --forward-mode=io --stats-period=1
# → 14.8 Mpps (10G line-rate)

# AF_XDP: скрипт (Python + bcc)
# Использование xdp-tools или xsk_fwd
./xsk_fwd --interface eth0 --queue 0
# → ~10-12 Mpps

# io_uring: пример из liburing
./io_uring_net_bench --port 8080
# → ~5-8 Mpps (async I/O)
```

---

### Типичные ошибки

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| AF_XDP zero-copy не работает | ~5 Mpps вместо 10 | NIC не поддерживает XDP zero-copy | Проверьте `ethtool -i eth0`; используйте Intel/Mellanox NIC |
| io_uring SQPOLL high CPU | 100% CPU | SQPOLL thread потребляет CPU | Отключите SQPOLL или уменьшите queue size |
| DPDK vs AF_XDP: AF_XDP latency high | P99 > 20 мкс | Kernel involved в XDP path | Используйте zero-copy mode; NUMA-local UMEM |
| io_uring not async | Блокируется на send | Используется sync socket | Используйте `io_uring_prep_send` вместо `send()` |

---

### Дополнительная информация

- **[DPDK: Архитектура](dpdk_overview.md)** — полный обзор DPDK для сравнения.
- **[DPDK: Тестирование](dpdk_testing.md)** — benchmarking DPDK vs alternatives.
- **[DPDK: Технические детали](dpdk_technical.md)** — HugePages, mempool vs UMEM.
- **[io_uring paper](https://kernel.dk/io_uring.pdf)** — оригинальная статья по io_uring.
- **[AF_XDP documentation](https://www.kernel.org/doc/Documentation/networking/af_xdp.rst)** — документация AF_XDP.
- **[XDP tutorial](https://github.com/xdp-project/xdp-tutorial)** — практический туториал по XDP.
- **[DPDK vs AF_XDP benchmark](https://www.intel.com/content/www/us/en/developer/articles/technical/dpdk-and-af-xdp-performance-comparison.html)** — сравнение производительности от Intel.
