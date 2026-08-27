# DPDK Hotplug — динамическое добавление/удаление NIC

### Определения

- **Hotplug**: Динамическое добавление или удаление PCI/PCIe устройства в рантайме без перезагрузки системы или DPDK-приложения.
- **PCI hot-remove**: Процесс безопасного отключения PCI устройства от шины. Включает отмену DMA, отключение прерываний, освобождение ресурсов (MMIO regions).
- **PCI hot-add**: Процесс обнаружения и инициализации нового PCI устройства. Включает сканирование PCI bus, настройку BAR, выделение ресурсов.
- **Device hotplug callback**: Механизм DPDK для уведомления приложения о событиях hotplug ( device added / device removed). Регистрируется через `rte_dev_hotplug_cb_register`.
- **rte_dev_hotplug_add**: API DPDK для динамического добавления устройства по PCI address.
- **rte_dev_hotplug_remove**: API DPDK для динамического удаления устройства по PCI address.
- **Graceful shutdown**: Безостановочное завершение работы NIC перед удалением: stop RX/TX, drain queues, free mbufs, unbind driver.
- **Failover**: Автоматическое переключение на резервный NIC при отказе основного. Реализуется через bonding (active-backup) или hotplug с replacement NIC.

---

### Теория

#### 1. Зачем нужен hotplug

| Сценарий | Описание | Зачем hotplug |
| :--- | :--- | :--- |
| **NIC failure** | Основной NIC вышел из строя | Замена на резервный NIC без downtime |
| **Capacity upgrade** | Добавление NIC для увеличения throughput | Масштабирование без перезапуска |
| **Maintenance** | Замена NIC на обновлённый | Обновление hardware без downtime |
| **Development** | Тестирование нового NIC в dev среде | Быстрое подключение/отключение |
| **NFV scaling** | Добавление NIC для new network function | Динамическое масштабирование NFV |

#### 2. Архитектура hotplug в DPDK

```
Приложение
    │
    ├── rte_dev_hotplug_cb_register(callback)
    │       │
    │       ▼
    │   ┌─────────────────────────────────────────┐
    │   │ Event Handler                            │
    │   │ При hotplug event:                       │
    │   │ 1. Вызвать callback                     │
    │   │ 2. Приложение quyết định                │
    │   │    - Добавить/удалить device            │
    │   │    - Переключиться на backup NIC        │
    │   └─────────────────────────────────────────┘
    │
    ├── rte_dev_hotplug_add("0000:01:00.1")
    │       │
    │       ▼
    │   ┌─────────────────────────────────────────┐
    │   │ PCI Bus Scan                             │
    │   │ 1. Сканирование PCI bus                 │
    │   │ 2. Привязка driver (vfio-pci)           │
    │   │ 3. Инициализация PMD                    │
    │   │ 4. rte_eth_dev_configure + start        │
    │   └─────────────────────────────────────────┘
    │
    └── rte_dev_hotplug_remove("0000:01:00.0")
            │
            ▼
        ┌─────────────────────────────────────────┐
        │ Graceful Shutdown                        │
        │ 1. rte_eth_dev_stop()                   │
        │ 2. Очистка TX queues (drain)            │
        │ 3. Освобождение mbufs                   │
        │ 4. rte_eth_dev_close()                  │
        │ 5. Unbind driver                        │
        └─────────────────────────────────────────┘
```

#### 3. События hotplug

| Событие | Описание | Действие приложения |
| :--- | :--- | :--- |
| `RTE_DEV_EVENT_ADD` | Новое устройство обнаружено | Добавить device, настроить, начать обработку |
| `RTE_DEV_EVENT_REMOVE` | Устройство удалено | Остановить обработку, переключиться на backup |
| `RTE_DEV_EVENT_INTR_LSC` | Link status changed | Обновить link status, перенастроить bonding |

---

### Практическое руководство

#### 1. Регистрация hotplug callback

```c
#include <rte_dev.h>
#include <rte_ethdev.h>

// Callback для hotplug events
static int hotplug_handler(const char *dev_name, enum rte_dev_event_type type,
                           void *arg) {
    switch (type) {
    case RTE_DEV_EVENT_ADD:
        printf("Device added: %s\n", dev_name);
        // Настройка нового устройства
        setup_new_device(dev_name);
        break;
    case RTE_DEV_EVENT_REMOVE:
        printf("Device removed: %s\n", dev_name);
        // Graceful shutdown и failover
        handle_device_removal(dev_name);
        break;
    default:
        break;
    }
    return 0;
}

// Регистрация callback
rte_dev_hotplug_cb_register(hotplug_handler, NULL);

// Или через event API
rte_dev_event_callback_register(RTE_DEV_EVENT_ADD, hotplug_handler, NULL);
rte_dev_event_callback_register(RTE_DEV_EVENT_REMOVE, hotplug_handler, NULL);

// Запуск event monitoring thread
rte_dev_event_monitor_start();
```

#### 2. Динамическое добавление NIC

```c
// Добавление нового NIC
int ret = rte_dev_hotplug_add("0000:01:00.1");
if (ret < 0) {
    printf("Failed to hotplug device: %s\n", rte_strerror(-ret));
    return -1;
}

// Найти добавленный порт
uint16_t new_port_id;
RTE_ETH_FOREACH_DEV(new_port_id) {
    struct rte_eth_dev_info dev_info;
    rte_eth_dev_info_get(new_port_id, &dev_info);
    if (strcmp(dev_info.pci_dev->name, "0000:01:00.1") == 0) {
        printf("Found new port: %u\n", new_port_id);
        break;
    }
}

// Конфигурация нового порта
struct rte_eth_conf conf = {
    .rxmode = { .mq_mode = RTE_ETH_MQ_RX_RSS },
    .rx_adv_conf = {
        .rss_conf = { .rss_hf = RTE_ETH_RSS_IP | RTE_ETH_RSS_TCP },
    },
};
rte_eth_dev_configure(new_port_id, 4, 4, &conf);
rte_eth_dev_start(new_port_id);
```

#### 3. Graceful removal

```c
// Безостановочное удаление NIC
int graceful_remove(uint16_t port_id) {
    // 1. Остановка RX
    rte_eth_dev_stop(port_id);

    // 2. Очистка TX queues (дождаться отправки всех пакетов)
    struct rte_eth_stats stats;
    rte_eth_stats_get(port_id, &stats);
    printf("TX before drain: %lu packets\n", stats.opackets);

    // 3. Освобождение всех mbuf в mempool
    rte_eth_dev_flush_tx_queues(port_id);

    // 4. Закрытие порта
    rte_eth_dev_close(port_id);

    // 5. Удаление устройства
    int ret = rte_dev_hotplug_remove(pci_addr);
    if (ret < 0) {
        printf("Failed to remove device: %s\n", rte_strerror(-ret));
    }

    return ret;
}
```

#### 4. Failover с hotplug

```c
// Типичный паттерн: primary NIC + backup NIC
uint16_t primary_port = 0;
uint16_t backup_port = 1;

// Callback при removal primary
void handle_device_removal(const char *dev_name) {
    if (is_primary_device(dev_name)) {
        printf("Primary NIC failed! Switching to backup...\n");

        // Graceful shutdown primary
        graceful_remove(primary_port);

        // Настройка backup
        rte_eth_dev_configure(backup_port, 4, 4, &conf);
        rte_eth_dev_start(backup_port);

        // Переключение обработки на backup
        primary_port = backup_port;

        // Попытка найти замену
        rte_dev_hotplug_add(new_pci_addr);
    }
}
```

#### 5. Тестирование hotplug

```bash
# 1. Запустить DPDK-приложение с одним NIC
./my_app -l 2-3 -n 4 -w 0000:01:00.0 --socket-mem 1024,0

# 2. В другом терминале: добавить второй NIC
sudo ./usertools/dpdk-devbind.py --bind=vfio-pci 0000:01:00.1

# 3. DPDK-приложение получит RTE_DEV_EVENT_ADD callback
# → Добавит новый порт автоматически

# 4. Эмулировать removal (unplug кабель или unbind)
sudo ./usertools/dpdk-devbind.py -u 0000:01:00.0

# 5. DPDK-приложение получит RTE_DEV_EVENT_REMOVE callback
# → Переключится на backup NIC
```

---

### Типичные ошибки

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| hotplug callback не вызывается | Событие не обработан | Callback не зарегистрирован | `rte_dev_hotplug_cb_register()` |
| "Device not found" при hotplug | Добавление fails | PCI address неправильный | `lspci` для проверки address |
| NIC не отвечает после hot-remove | Зависание | DMA не остановлен | Graceful shutdown перед removal |
| Race condition в hotplug | Crash при concurrent add/remove | Lock не используется | Мutex для hotplug operations |

---

### Дополнительная информация

- **[DPDK: Bonding](dpdk_bonding.md)** — bonding для failover (alternative to hotplug).
- **[DPDK: Multi-process](dpdk_multiprocess.md)** — hotplug в multi-process.
- **[DPDK: PMD Architecture](dpdk_overview.md)** — как PMD инициализирует device.
- **[Linux PCI Hotplug](https://www.kernel.org/doc/Documentation/PCI/pci-hotplug.txt)** — kernel PCI hotplug.
- **[DPDK Hotplug Guide](https://doc.dpdk.org/guides/prog_guide/hotplug.html)** — официальный гайд.
