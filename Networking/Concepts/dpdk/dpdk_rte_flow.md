# rte_flow API — Программирование фильтрации в железе

### Определения

- **rte_flow**: Унифицированный DPDK API для программирования аппаратных правил фильтрации и классификации пакетов в NIC (Flow Director, Switchdev, и др.). Заменил неунифицированный FDir API начиная с DPDK 17.08.
- **Pattern (Паттерн)**: Описание набора полей пакета для сопоставления (match). Каждый элемент — это тип заголовка (eth, ipv4, tcp, udp, vxlan) + маска/значение.
- **Action (Действие)**: Операция, выполняемая NIC над пакетом при совпадении паттерна: queue (направить в очередь), drop (отбросить), mark (пометить), passthru (передать дальше), count (подсчитать), mirror (зеркалировать).
- **Rule (Правило)**: Полная конструкция: `pattern[] → actions[]`. Один pattern может содержать несколько элементов (eth + ipv4 + tcp). Одно действие может быть составным (queue + mark + count).
- **Group (Группа)**: Приоритетная группа правил. Правила в group 0 обрабатываются первыми (highest priority), group 1 — вторыми, и т.д. Правила в одной группе обрабатываются в порядке добавления.
- **RTE_FLOW_ITEM_TYPE_ETH**: Элемент паттерна для Ethernet-заголовка (src/dst MAC, ethertype).
- **RTE_FLOW_ITEM_TYPE_IPV4**: Элемент паттерна для IPv4 (src/dst IP, proto, TTL, DSCP).
- **RTE_FLOW_ITEM_TYPE_TCP**: Элемент паттерна для TCP (src/dst port, flags, seq/ack).
- **RTE_FLOW_ACTION_TYPE_QUEUE**: Действие — направить пакет в указанную RX-очередь.
- **RTE_FLOW_ACTION_TYPE_DROP**: Действие — отбросить пакет аппаратно (без участия CPU).
- **RTE_FLOW_ACTION_TYPE_MARK**: Действие — пометить пакет (set mark ID), приложение может прочитать через `RTE_ETH_RX_FLAG_MBUF_metadata`.
- **RTE_FLOW_ACTION_TYPE_PASSTHRU**: Действие — передать пакет дальше по pipeline (не останавливать на этом правиле).
- **RTE_FLOW_ACTION_TYPE_COUNT**: Действие — подсчитать количество совпавших пакетов (аппаратный счётчик).
- **rte_flow_error**: Структура для возврата ошибок API (message, type, cause).
- **rte_flow_flush**: Удаление всех правил для данного порта.
- **rte_flow_isolate**: Режим изоляции — NIC обрабатывает только rte_flow правила, игнорируя RSS/встроенные фильтры.

---

### Теория

#### 1. Архитектура rte_flow

```
Приложение (DPDK)
    │
    ▼
┌──────────────────────────────────────────┐
│ rte_flow API                             │
│ rte_flow_create() / rte_flow_destroy()   │
│ rte_flow_flush() / rte_flow_query()      │
└──────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────┐
│ PMD (	dpdk_ixgbe / dpdk_i40e / dpdk_ice)│
│ Преобразование в аппаратные правила NIC  │
│ (FDir rules / Switchdev rules / TC rules)│
└──────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────┐
│ NIC Hardware                             │
│ TCAM / Exact-match tables                │
│ Обработка пакетов в wire-speed           │
└──────────────────────────────────────────┘
```

**Ключевые преимущества:**
- Аппаратная фильтрация: 0 циклов CPU на каждый пакет
- Программирование: runtime (без перезапуска NIC)
- Унифицированный API: один код работает на Intel, NVIDIA, Broadcom NIC

#### 2. Структура правила

```c
// Шаблон: pattern[] → actions[]
struct rte_flow_attr attr;      // Группа, направление (ingress/egress)
struct rte_flow_item pattern[]; // Элементы паттерна (eth + ipv4 + tcp + END)
struct rte_flow_action actions[]; // Действия (queue + END)
struct rte_flow_error error;    // Ошибка

// Пример: направить TCP трафик на порт 80 в queue 3
struct rte_flow_attr attr = {
    .group = 0,
    .ingress = 1,   // Входящий трафик
    .egress = 0,
};

struct rte_flow_item pattern[] = {
    { .type = RTE_FLOW_ITEM_TYPE_ETH },      // Ethernet
    { .type = RTE_FLOW_ITEM_TYPE_IPV4 },      // IPv4
    { .type = RTE_FLOW_ITEM_TYPE_TCP,         // TCP
      .spec = &(struct rte_flow_item_tcp){
          .hdr.dst_port = rte_cpu_to_be_16(80),
      },
      .mask = &(struct rte_flow_item_tcp){
          .hdr.dst_port = RTE_BE16(0xFFFF),  // Точное совпадение
      },
    },
    { .type = RTE_FLOW_ITEM_TYPE_END },       // Конец паттерна
};

struct rte_flow_action actions[] = {
    { .type = RTE_FLOW_ACTION_TYPE_QUEUE,
      .conf = &(struct rte_flow_action_queue){ .index = 3 } },
    { .type = RTE_FLOW_ACTION_TYPE_END },
};

// Создание правила
struct rte_flow *flow = rte_flow_create(port_id, &attr, pattern, actions, &error);
if (!flow) {
    printf("Error creating flow: %s\n", error.message);
}
```

#### 3. Типы элементов паттерна (Pattern Items)

**Ethernet:**
```c
{ .type = RTE_FLOW_ITEM_TYPE_ETH }
// Без spec/mask = match any Ethernet frame

// С фильтрацией по MAC
{ .type = RTE_FLOW_ITEM_TYPE_ETH,
  .spec = &(struct rte_flow_item_eth){
      .hdr.dst_addr.addr_bytes = {0x00, 0x11, 0x22, 0x33, 0x44, 0x55},
  },
  .mask = &(struct rte_flow_item_eth){
      .hdr.dst_addr.addr_bytes = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF},
  },
}
```

**IPv4:**
```c
{ .type = RTE_FLOW_ITEM_TYPE_IPV4 }
// Без фильтрации = match any IPv4

// С фильтрацией по src/dst IP
{ .type = RTE_FLOW_ITEM_TYPE_IPV4,
  .spec = &(struct rte_flow_item_ipv4){
      .hdr.src_addr = RTE_BE32(0x0A000001),  // 10.0.0.1
      .hdr.dst_addr = RTE_BE32(0x0A000002),  // 10.0.0.2
      .hdr.proto = IPPROTO_TCP,
  },
  .mask = &(struct rte_flow_item_ipv4){
      .hdr.src_addr = RTE_BE32(0xFFFFFFFF),  // Точный match
      .hdr.dst_addr = RTE_BE32(0xFFFFFFFF),
      .hdr.proto = 0xFF,
  },
}
```

**TCP:**
```c
{ .type = RTE_FLOW_ITEM_TYPE_TCP,
  .spec = &(struct rte_flow_item_tcp){
      .hdr.src_port = rte_cpu_to_be_16(1234),
      .hdr.dst_port = rte_cpu_to_be_16(80),
  },
  .mask = &(struct rte_flow_item_tcp){
      .hdr.src_port = RTE_BE16(0xFFFF),
      .hdr.dst_port = RTE_BE16(0xFFFF),
  },
}
```

**VXLAN:**
```c
{ .type = RTE_FLOW_ITEM_TYPE_VXLAN,
  .spec = &(struct rte_flow_item_vxlan){
      .hdr.vx_vni = rte_cpu_to_be_32(100 << 8),  // VNI = 100
  },
  .mask = &(struct rte_flow_item_vxlan){
      .hdr.vx_vni = RTE_BE32(0xFFFFFF00),  // VNI only (24 bits)
  },
}
```

**Geneve:**
```c
{ .type = RTE_FLOW_ITEM_TYPE_GENEVE,
  .spec = &(struct rte_flow_item_geneve){
      .hdr.vni = rte_cpu_to_be_32(200 << 8),
  },
  .mask = &(struct rte_flow_item_geneve){
      .hdr.vni = RTE_BE32(0xFFFFFF00),
  },
}
```

#### 4. Типы действий (Actions)

**QUEUE** — направить в RX-очередь:
```c
{ .type = RTE_FLOW_ACTION_TYPE_QUEUE,
  .conf = &(struct rte_flow_action_queue){ .index = 3 } }
```

**DROP** — отбросить аппаратно:
```c
{ .type = RTE_FLOW_ACTION_TYPE_DROP }
```

**MARK** — пометить пакет (для обработки в приложении):
```c
{ .type = RTE_FLOW_ACTION_TYPE_MARK,
  .conf = &(struct rte_flow_action_mark){ .id = 42 } }
// В приложении:
// if (ol_flags & PKT_RX_FDIR) { mark = m->hash.fdir.hi; }
```

**PASSTHRU** — передать дальше:
```c
{ .type = RTE_FLOW_ACTION_TYPE_PASSTHRU }
```

**COUNT** — аппаратный подсчёт:
```c
// 1. Создать счётчик
struct rte_flow_action_count count = { .shared = 0, .id = 0 };

// 2. Использовать в action
{ .type = RTE_FLOW_ACTION_TYPE_COUNT,
  .conf = &count }

// 3. Запросить счётчик
struct rte_flow_query_data query;
rte_flow_query(port_id, flow, RTE_FLOW_ACTION_TYPE_COUNT, &count, &query);
printf("Matched packets: %lu\n", query.counter_set.packets);
```

**MIRROR** — зеркалирование трафика (Intel E810):
```c
// Создать зеркало
struct rte_flow_action_mirror mirror = { .port_id = 1 };  // Зеркалировать на порт 1

// Использовать
{ .type = RTE_FLOW_ACTION_TYPE_MIRROR,
  .conf = &mirror }
```

#### 5. Управление правилами

```c
// Создание
struct rte_flow *flow = rte_flow_create(port_id, &attr, pattern, actions, &error);

// Удаление одного правила
rte_flow_destroy(port_id, flow, &error);

// Удаление всех правил
rte_flow_flush(port_id, &error);

// Включение режима изоляции (только rte_flow правила, без RSS)
rte_flow_isolate(port_id, 1, &error);

// Выключение режима изоляции (вернуть RSS)
rte_flow_isolate(port_id, 0, &error);

// Запрос счётчиков
rte_flow_query(port_id, flow, RTE_FLOW_ACTION_TYPE_COUNT, &count, &query);
```

#### 6. Типичные паттерны для продакшена

**1. Направить трафик VLAN X на core Y:**
```c
struct rte_flow_item pattern[] = {
    { .type = RTE_FLOW_ITEM_TYPE_ETH },
    { .type = RTE_FLOW_ITEM_TYPE_VLAN,
      .spec = &(struct rte_flow_item_vlan){ .tci = rte_cpu_to_be_16(100) },
      .mask = &(struct rte_flow_item_vlan){ .tci = RTE_BE16(0x0FFF) },
    },
    { .type = RTE_FLOW_ITEM_TYPE_END },
};

struct rte_flow_action actions[] = {
    { .type = RTE_FLOW_ACTION_TYPE_QUEUE,
      .conf = &(struct rte_flow_action_queue){ .index = 2 } },
    { .type = RTE_FLOW_ACTION_TYPE_END },
};
```

**2. Drop трафика с определённого IP (DDoS protection):**
```c
struct rte_flow_item pattern[] = {
    { .type = RTE_FLOW_ITEM_TYPE_ETH },
    { .type = RTE_FLOW_ITEM_TYPE_IPV4,
      .spec = &(struct rte_flow_item_ipv4){
          .hdr.src_addr = RTE_BE32(0xC0A80064),  // 192.168.0.100
      },
      .mask = &(struct rte_flow_item_ipv4){
          .hdr.src_addr = RTE_BE32(0xFFFFFFFF),
      },
    },
    { .type = RTE_FLOW_ITEM_TYPE_END },
};

struct rte_flow_action actions[] = {
    { .type = RTE_FLOW_ACTION_TYPE_DROP },
    { .type = RTE_FLOW_ACTION_TYPE_END },
};
```

**3. Forward VXLAN трафик с VNI=100 на core 3 + mark:**
```c
struct rte_flow_item pattern[] = {
    { .type = RTE_FLOW_ITEM_TYPE_ETH },
    { .type = RTE_FLOW_ITEM_TYPE_IPV4 },
    { .type = RTE_FLOW_ITEM_TYPE_UDP,
      .spec = &(struct rte_flow_item_udp){
          .hdr.dst_port = rte_cpu_to_be_16(4789),
      },
      .mask = &(struct rte_flow_item_udp){
          .hdr.dst_port = RTE_BE16(0xFFFF),
      },
    },
    { .type = RTE_FLOW_ITEM_TYPE_VXLAN,
      .spec = &(struct rte_flow_item_vxlan){
          .hdr.vx_vni = rte_cpu_to_be_32(100 << 8),
      },
      .mask = &(struct rte_flow_item_vxlan){
          .hdr.vx_vni = RTE_BE32(0xFFFFFF00),
      },
    },
    { .type = RTE_FLOW_ITEM_TYPE_END },
};

struct rte_flow_action actions[] = {
    { .type = RTE_FLOW_ACTION_TYPE_QUEUE,
      .conf = &(struct rte_flow_action_queue){ .index = 3 } },
    { .type = RTE_FLOW_ACTION_TYPE_MARK,
      .conf = &(struct rte_flow_action_mark){ .id = 100 } },
    { .type = RTE_FLOW_ACTION_TYPE_END },
};
```

**4. ACL: разрешить только TCP/80 и TCP/443, остальное drop:**
```c
// Правило 1: разрешить TCP/80
struct rte_flow_item pattern1[] = {
    { .type = RTE_FLOW_ITEM_TYPE_ETH },
    { .type = RTE_FLOW_ITEM_TYPE_IPV4 },
    { .type = RTE_FLOW_ITEM_TYPE_TCP,
      .spec = &(struct rte_flow_item_tcp){
          .hdr.dst_port = rte_cpu_to_be_16(80),
      },
      .mask = &(struct rte_flow_item_tcp){
          .hdr.dst_port = RTE_BE16(0xFFFF),
      },
    },
    { .type = RTE_FLOW_ITEM_TYPE_END },
};

struct rte_flow_action actions1[] = {
    { .type = RTE_FLOW_ACTION_TYPE_PASSTHRU },
    { .type = RTE_FLOW_ACTION_TYPE_END },
};

// Правило 2: разрешить TCP/443
struct rte_flow_item pattern2[] = {
    { .type = RTE_FLOW_ITEM_TYPE_ETH },
    { .type = RTE_FLOW_ITEM_TYPE_IPV4 },
    { .type = RTE_FLOW_ITEM_TYPE_TCP,
      .spec = &(struct rte_flow_item_tcp){
          .hdr.dst_port = rte_cpu_to_be_16(443),
      },
      .mask = &(struct rte_flow_item_tcp){
          .hdr.dst_port = RTE_BE16(0xFFFF),
      },
    },
    { .type = RTE_FLOW_ITEM_TYPE_END },
};

struct rte_flow_action actions2[] = {
    { .type = RTE_FLOW_ACTION_TYPE_PASSTHRU },
    { .type = RTE_FLOW_ACTION_TYPE_END },
};

// Правило 3 (group 1, lower priority): drop всё остальное
struct rte_flow_attr attr_drop = {
    .group = 1,   // Ниже чем group 0
    .ingress = 1,
};

struct rte_flow_item pattern3[] = {
    { .type = RTE_FLOW_ITEM_TYPE_END },
};

struct rte_flow_action actions3[] = {
    { .type = RTE_FLOW_ACTION_TYPE_DROP },
    { .type = RTE_FLOW_ACTION_TYPE_END },
};

// Создание всех трёх правил
rte_flow_create(port_id, &attr_group0, pattern1, actions1, &error);
rte_flow_create(port_id, &attr_group0, pattern2, actions2, &error);
rte_flow_create(port_id, &attr_drop, pattern3, actions3, &error);
```

#### 7. rte_flow vs Software Matching (kernel OVS)

| Критерий | rte_flow (NIC hardware) | Software matching (kernel OVS / eBPF) |
| :--- | :--- | :--- |
| **Где выполняется** | В silicon NIC (TCAM, hash tables) | В CPU (kernel или userspace) |
| **Скорость** | Wire-speed (100G/400G) | ~10-50 Mpps (зависит от CPU) |
| **Задержка** | ~100 нс (hardware pipeline) | ~500-1000 нс (context switch) |
| **Гибкость** | Ограничена возможностями NIC | Неограниченная (любые правила) |
| **Память** | 8K-128K rules (TCAM NIC) | Миллионы rules (kernel hash) |
| **Обновление** | ~1 мкс на rule | ~10-50 мкс на rule |
| **Когда использовать** | Простые правила (queue/drop/mark), stateless | Complex stateful rules, deep packet inspection |

---

### Практическое руководство

#### 1. Проверка поддержки rte_flow

```bash
# Проверка что NIC поддерживает rte_flow
./usertools/dpdk-devbind.py -s | grep -A2 "DPDK-compatible"
# → NIC должна быть привязана к vfio-pci

# Через testpmd:
# show port flow operations 0
# → Supported flow operations: count drop queue mark passthru
# → Maximum number of rules: 16384
# → Maximum number of groups: 64

# Проверка через ethtool
ethtool -n enp1s0
# → Supports n-tuple filters: yes
# → Supports RSS: yes
# → Supports flow director: yes
```

#### 2. Тестирование rte_flow на testpmd

```bash
# Запуск testpmd с поддержкой flow
./build/app/testpmd -l 2-3 -n 4 -w 0000:01:00.0 --socket-mem 1024,0 -- \
  --forward-mode=io --rxq=4 --txq=4

# Добавление правила через testpmd CLI (если поддерживается)
# testpmd> flow create 0 ingress pattern eth / ipv4 / tcp dst-port is 80 / end actions queue index 3 / end
# → Flow rule #0 created

# Просмотр правил
# testpmd> flow list 0
# → ID   Group   Prio   Attr      Rule
# → 0    0       0      i--       eth/ipv4/tcp dst-port=80 => queue index 3

# Удаление правила
# testpmd> flow destroy 0 0
# → Flow rule #0 destroyed

# Удаление всех правил
# testpmd> flow flush 0
# → All flow rules flushed
```

#### 3. Отладка ошибок rte_flow

```c
struct rte_flow_error error;

struct rte_flow *flow = rte_flow_create(port_id, &attr, pattern, actions, &error);
if (!flow) {
    printf("rte_flow_create failed:\n");
    printf("  Message: %s\n", error.message);
    printf("  Type: %d\n", error.type);
    // Типы ошибок:
    // RTE_FLOW_ERROR_TYPE_NONE: нет ошибки
    // RTE_FLOW_ERROR_TYPE_ATTR: ошибка в атрибутах (group, ingress)
    // RTE_FLOW_ERROR_TYPE_ITEM: ошибка в паттерне (unsupported item type)
    // RTE_FLOW_ERROR_TYPE_ACTION: ошибка в действии (unsupported action)
    // RTE_FLOW_ERROR_TYPE_HANDLE: ошибка в правиле (duplicate rule)
}
```

---

### Типичные ошибки

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| `rte_flow_create` returns NULL | Правило не создано | NIC не поддерживает данный pattern/action | Проверьте `show port flow operations`; упростите rule |
| `ENOSPC` при создании правила | Правило не создано | Достигнут лимит rules на NIC | `rte_flow_flush` или увеличьте лимит (если возможно) |
| Правило не действует | Пакеты не фильтруются | Неправильный mask (маска не совпадает) | Проверьте mask: `0xFFFF` = точный match, `0x0000` = wildcard |
| `ENOTSUP` | Ошибка в error.message | NIC PMD не поддерживает данную комбинацию | Упростите паттерн или используйте другую NIC |
| FDir перехватывает трафик | Пакеты идут не в ту queue | Конфликт FDir rules с rss_hf | Проверьте `ethtool -u`; удалите конфликтующие FDir rules |

---

### Дополнительная информация

- **[DPDK: RSS](dpdk_rss.md)** — аппаратное распределение трафика (дополняет rte_flow).
- **[DPDK: Тестирование и бенчмаркинг](dpdk_testing.md)** — как протестировать flow rules на практике.
- **[DPDK: Архитектура PMD](dpdk_overview.md)** — как PMD программирует NIC rules.
- **[DPDK: Типичные ошибки](dpdk_technical.md)** — troubleshooting rte_flow ошибок.
- **[Intel Flow Director API](https://www.intel.com/content/www/us/en/docs/dpk/dev-guide/21.11/flow-director-api.html)** — официальный гайд по FDir/rte_flow в DPDK.
- **[OVS-DPDK: hw-offload](https://docs.openvswitch.org/en/latest/topics/dpdk/hw-offload/)** — аппаратное ускорение в OVS через rte_flow.
