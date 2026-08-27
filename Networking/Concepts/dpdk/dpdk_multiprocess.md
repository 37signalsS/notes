# Multi-process DPDK — Primary/Secondary модель

### Определения

- **Primary process**: Основной DPDK-процесс, который управляет ресурсами (HugePages, mempool, rte_ring, порты NIC). Только один primary может работать на хосте одновременно.
- **Secondary process**: Вторичный DPDK-процесс, который подключается к shared memory primary. Secondary может читать mempool/ring, но НЕ может создавать их или управлять NIC.
- **Shared memory**: Область HugePages, разделяемая между primary и secondary через shared memory files (`/var/run/dpdk/<prefix>/`). Secondary процесс mmap-ит те же HugePages, что и primary.
- **--file-prefix**: Префикс для shared memory files. Позволяет запускать несколько изолированных DPDK кластеров на одном хосте (primary1 + primary2 с разными prefixes).
- **--proc-type**: Параметр EAL, указывающий тип процесса: `auto` (автоопределение), `primary`, `secondary`.
- **IPC (Inter-Process Communication)**: Межпроцессное взаимодействие в multi-process DPDK. Реализуется через shared mempool/ring и механизм file descriptor passing.
- **file descriptor passing**: Механизм передачи файловых дескрипторов между процессами через Unix socket. Позволяет secondary получить доступ к mempool/ring, созданным primary.
- **Memory hotplug**: Динамическое добавление/удаление HugePages в рантайме. Поддерживается в multi-process для расширения shared memory.
- **Сценарий control plane + data plane**: Типичное использование multi-process: primary = data plane (высокопроизводительная обработка пакетов), secondary = control plane (управление, статистика, конфигурация).

---

### Теория

#### 1. Архитектура Multi-process

```
┌─────────────────────────────────────────────────────┐
│ Хост (HugePages)                                    │
│                                                     │
│ ┌──────────────────────────────────────────────────┐│
│ │ Shared Memory (HugePages)                        ││
│ │ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐││
│ │ │ mempool │ │ mempool │ │ ring    │ │ ring    │││
│ │ │ (pool0) │ │ (pool1) │ │ (r0)    │ │ (r1)    │││
│ │ └─────────┘ └─────────┘ └─────────┘ └─────────┘││
│ └──────────────────────────────────────────────────┘│
│         ▲                       ▲                   │
│         │                       │                   │
│ ┌───────┴───────┐   ┌───────────┴─────────────────┐│
│ │ Primary      │   │ Secondary                     ││
│ │ Process      │   │ Process                       ││
│ │ - NIC mgmt   │   │ - Read stats                  ││
│ │ - Create pool│   │ - Forwarding rules            ││
│ │ - RX/TX      │   │ - Monitoring                  ││
│ │ - Lcore mgmt │   │ - Control plane               ││
│ └───────────────┘   └──────────────────────────────┘│
│         │                       │                   │
│         ▼                       ▼                   │
│ ┌──────────────────────────────────────────────────┐│
│ │ NIC (vfio-pci)                                   ││
│ │ Port 0, Port 1                                   ││
│ └──────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘
```

#### 2. Ключевые ограничения

| Операция | Primary | Secondary | Пояснение |
| :--- | :--- | :--- | :--- |
| Создание mempool | ✅ | ❌ | Secondary читает существующий mempool |
| Создание rte_ring | ✅ | ❌ | Secondary читает существующий ring |
| Управление NIC (configure/start/stop) | ✅ | ❌ | Только primary управляет NIC |
| RX/TX пакетов | ✅ | ❌ | Secondary не имеет прямого доступа к NIC |
| Чтение mempool (get/put) | ✅ | ✅ | Secondary может выделять/освобождать mbuf |
| Чтение rte_ring (enqueue/dequeue) | ✅ | ✅ | Secondary может обмениваться данными через ring |
| Запуск lcore thread | ✅ | ✅ | Secondary может запускать worker threads |
| Access to HugePages | ✅ | ✅ | Через shared memory (mmap) |
| Hotplug devices | ✅ | ❌ | Только primary |

#### 3. Как работает shared memory

```
1. Primary запускается:
   - Выделяет HugePages
   - Создаёт mempool в HugePages
   - Создаёт rte_ring в HugePages
   - Записывает файлы в /var/run/dpdk/<prefix>/

2. Secondary запускается:
   - Читает файлы из /var/run/dpdk/<prefix>/
   - mmap те же HugePages (read-only)
   - Находит mempool/ring по имени
   - Может использовать mempool/ring (чтение/запись)
```

**Файлы shared memory:**
```bash
# После запуска primary:
ls /var/run/dpdk/app1/
# → config  - конфигурация DPDK
# → mem - memory map (HugePages)
# → port - port configuration
# → ctrl - control IPC channel
```

---

### Практическое руководство

#### 1. Primary процесс

```c
#include <rte_eal.h>
#include <rte_mempool.h>
#include <rte_ring.h>

int main(int argc, char **argv) {
    // Инициализация EAL как primary
    int ret = rte_eal_init(argc, argv);
    if (ret < 0)
        rte_exit(EXIT_FAILURE, "Cannot init EAL\n");

    // Создание mempool
    struct rte_mempool *mp = rte_mempool_create(
        "mbuf_pool", 32768, 2176, 256,
        sizeof(struct rte_pktmbuf_pool_private),
        NULL, NULL, NULL, NULL,
        rte_socket_id(), 0
    );

    // Создание ring для IPC с secondary
    struct rte_ring *ring = rte_ring_create(
        "ipc_ring", 1024, rte_socket_id(), RING_F_SP_ENQ | RING_F_SC_DEQ
    );

    // Настройка NIC и запуск обработки
    // ...

    // Primary работает как data plane
    while (1) {
        unsigned nb_rx = rte_eth_rx_burst(port_id, queue_id, pkts_burst, 32);

        // Обработка пакетов
        for (unsigned i = 0; i < nb_rx; i++) {
            // L2/L3/L4 processing
        }

        // Отправка статистики в secondary через ring
        rte_ring_sp_enqueue(ring, stats_msg);
    }
}
```

#### 2. Secondary процесс

```c
#include <rte_eal.h>
#include <rte_mempool.h>
#include <rte_ring.h>

int main(int argc, char **argv) {
    // EAL автоматически определит secondary (--proc-type=secondary)
    setenv("RTE_SECONDARY", "1", 1);  // Или аргумент --proc-type=secondary

    int ret = rte_eal_init(argc, argv);
    if (ret < 0)
        rte_exit(EXIT_FAILURE, "Cannot init EAL (secondary)\n");

    // Найти существующий mempool по имени
    struct rte_mempool *mp = rte_mempool_lookup("mbuf_pool");
    if (!mp)
        rte_exit(EXIT_FAILURE, "Cannot find mempool\n");

    // Найти существующий ring по имени
    struct rte_ring *ring = rte_ring_lookup("ipc_ring");
    if (!ring)
        rte_exit(EXIT_FAILURE, "Cannot find ring\n");

    // Secondary работает как control plane
    while (1) {
        // Чтение статистики из ring
        void *msg;
        if (rte_ring_sc_dequeue(ring, &msg) == 0) {
            // Обработка статистики
            process_stats(msg);
        }

        // Чтение мемпулов (для анализа)
        uint32_t avail = rte_mempool_avail_count(mp);
        printf("Mempool available: %u\n", avail);

        // НЕЛЬЗЯ: rte_eth_rx_burst() — нет доступа к NIC
        // НЕЛЬЗЯ: rte_mempool_create() — только primary
    }
}
```

#### 3. Запуск multi-process

```bash
# Terminal 1: Primary process
./primary-app -l 2-3 -n 4 --socket-mem 2048,0 --file-prefix=app1

# Terminal 2: Secondary process
./secondary-app -l 4-5 -n 4 --socket-mem 1024,0 --file-prefix=app1 --proc-type=secondary

# Проверка shared memory:
ls /var/run/dpdk/app1/
# → config  mem  port  ctrl
```

#### 4. Типичный сценарий: Data Plane + Control Plane

```c
// === Primary: Data Plane ===
// Отправляет пакеты, считает статистику, передаёт в ring

struct stats_msg {
    uint64_t rx_packets;
    uint64_t tx_packets;
    uint64_t rx_bytes;
    uint64_t tx_bytes;
    uint64_t rx_errors;
    uint64_t tx_errors;
};

// В основном цикле primary:
struct stats_msg stats = {
    .rx_packets = port_stats.ipackets,
    .tx_packets = port_stats.opackets,
    // ...
};
rte_ring_sp_enqueue(stats_ring, &stats);
```

```c
// === Secondary: Control Plane ===
// Получает статистику, управляет правилами, логирует

while (1) {
    struct stats_msg *msg;
    if (rte_ring_sc_dequeue(stats_ring, (void **)&msg) == 0) {
        printf("RX: %lu pkts, TX: %lu pkts\n",
               msg->rx_packets, msg->tx_packets);

        // Логирование, алерты, SNMP, и т.д.
    }
}
```

#### 5. File descriptor passing (IPC)

```c
// Primary: передать mempool через fd
int fd = rte_mempool_external_get(mp, "/var/run/dpdk/app1/ctrl.sock");
// fd отправляется через unix socket secondary-процессу

// Secondary: принять mempool через fd
int fd = recv_fd(unix_socket);
struct rte_mempool *mp = rte_mempool_lookup_external(fd);
```

---

### Типичные ошибки

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| Secondary не находит mempool | `rte_mempool_lookup` returns NULL | file-prefix не совпадает | Убедитесь что primary и secondary используют одинаковый `--file-prefix` |
| Shared memory не найдена | `rte_eal_init` fails в secondary | Primary не запущен или завершился | Запустите primary первым; проверьте `/var/run/dpdk/<prefix>/` |
| Secondary управляет NIC | Ошибка или непредсказуемое поведение | Secondary пытается вызвать `rte_eth_*` | Secondary НЕ должен вызывать NIC API |
| HugePages exhaustion | Secondary не может получить mbuf | Mempool исчерпан primary | Увеличьте mempool size; добавьте HugePages |
| Race condition в ring | Потеря данных в ring | MP/MC без proper sync | Используйте SP/SC для single-producer/single-consumer |

---

### Дополнительная информация

- **[DPDK: Архитектура PMD](dpdk_overview.md)** — как primary управляет NIC.
- **[DPDK: Технические детали](dpdk_technical.md)** — mempool, rte_ring, HugePages.
- **[DPDK: Тестирование](dpdk_testing.md)** — тестирование multi-process конфигурации.
- **[DPDK: Низкая задержка (HFT)](scenarios.md#сценарий-5-hft)** — multi-process для control plane в HFT.
- **[DPDK Multi-process Guide](https://doc.dpdk.org/guides/prog_guide/multi_process.html)** — официальный гайд по multi-process.
