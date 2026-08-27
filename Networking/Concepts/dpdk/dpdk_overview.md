# Обзор DPDK (Data Plane Development Kit)

### Определения

- **DPDK (Data Plane Development Kit)**: Набор библиотек и драйверов пространства пользователя (userspace), предназначенный для высокопроизводительной обработки сетевых пакетов. Основная цель — обеспечить обход сетевого стека ядра (Kernel Bypass) для минимизации задержек и максимизации пропускной способности. Разрабатывается под эгидой Linux Foundation (FD.io); лицензия BSD.
- **Kernel Bypass (Обход ядра)**: Архитектурный подход, при котором сетевой трафик передается напрямую из сетевого адаптера (NIC) в приложение в userspace, минуя обработку в ядре ОС. DPDK реализует kernel bypass через UIO (Userspace I/O) или VFIO — драйверы ядра, которые передают управление PCI-устройством приложению в пространстве пользователя.
- **Poll Mode Driver (PMD)**: Драйвер, работающий в режиме опроса (polling) вместо прерываний. Ядро CPU постоянно проверяет регистры NIC на наличие новых данных, что исключает накладные расходы на переключение контекста и обработку аппаратных прерываний. PMD实现了бесперебойную (busy-polling) модель, требующую выделения полного ядра CPU под обработку пакетов.
- **EAL (Environment Abstraction Layer)**: Слой абстракции окружения, который инициализирует низкоуровневые ресурсы (память, ядра CPU, PCI-устройства) и предоставляет единый интерфейс для приложения, скрывая детали конкретной ОС (Linux, FreeBSD, Windows). EAL скрывает разницу между платформами и позволяет DPDK-приложениям быть портируемыми.
- **UIO (Userspace I/O)**: Механизм ядра Linux, позволяющий приложениям в пространстве пользователя напрямую обращаться к аппаратным ресурсам (регистрами PCI-устройств) через маппинг памяти (mmap). DPDK исторически использовал UIO, но в 2026 году стандартом является VFIO.
- **VFIO (Virtual Function I/O)**: Современный драйвер ядра, обеспечивающий прямой доступ к PCI-устройствам из userspace с аппаратной изоляцией через IOMMU. В отличие от UIO, VFIO поддерживает IOMMU-изоляцию, что критично для безопасности в виртуализированных средах и многопользовательских системах.
- **rte_mbuf**: Основная структура данных DPDK для хранения пакетов. Содержит заголовок с метаданными (разгрузки, порты, хеши) и указатели на данные. Каждый mbuf выравнивается по границе кэш-линии (64/128 байт) для предотвращения false sharing.
- **rte_ring**: Высокопроизводительная бесблокировочная очередь (Ring Buffer), реализованная как кольцевой буфер с атомарными операциями. Обеспечивает эффективный обмен данными между lcores без использования мьютексов. Поддерживает SP/SC (Single Producer/Consumer) и MP/MC (Multi Producer/Consumer) режимы.
- **lcore (Logical Core)**: Поток исполнения DPDK, жёстко привязанный (affinity) к конкретному аппаратному ядру CPU через `taskset` или планировщик ядра. Каждый lcore обрабатывает пакеты независимо от других, что исключает конкуренцию за ресурсы.

---

### Краткая история

| Год | Событие |
| :--- | :--- |
| 2010 | Выпуск DPDK 1.0 разработчиками Intel. Первые PMD для Intel NIC. |
| 2013 | Проект перенесён в Linux Foundation (FD.io). Начало мультивендорной поддержки. |
| 2017 | DPDK 17.08 — добавлен generic Flow API (`rte_flow`), унифицированный интерфейс для фильтрации пакетов в железе. |
| 2019 | DPDK 19.02 — поддержка Windows (экспериментальная), автономные библиотеки (EAL вынесен из общей сборки). |
| 2021 | DPDK 21.11 LTS — стабильнаяLong-Term Support версия. Модульная архитектура библиотек. |
| 2023 | DPDK 23.11 — добавлен net/memif для IPC (Inter-Process Communication) между DPDK-приложениями, поддержка Rust-биндингов. |
| 2025 | DPDK 25.11 LTS — текущий стандарт. Поддержка PCIe Gen6, AMX (Advanced Matrix Extensions) для AI-инференса,泉5.0 NIC. |

---

### Архитектура и ключевые компоненты

В 2026 году DPDK 25.11 LTS является фундаментом для всех высокопроизводительных сетевых решений. Его архитектура строится на нескольких базовых библиотеках (`librte_*`):

#### Инфраструктурные библиотеки

- **librte_eal**: Сердце DPDK. Управляет выделением огромных страниц памяти (HugePages), привязкой к ядрам (CPU pinning) и доступом к шине PCI. EAL предоставляет API для:
  - Инициализации HugePages (`rte_eal_init`)
  - Маппинга PCI-устройств (`rte_pci_device`)
  - Управления lcore (`rte_lcore_id`, `rte_get_master_lcore`)
  - Параметры запуска: `-l` (lcores), `--socket-mem` (память по NUMA-узлам), `--file-prefix` (изоляция нескольких DPDK-приложений)

- **librte_mempool**: Высокопроизводительный аллокатор объектов (пакетов). Использует локальные кэши на каждом ядре для исключения блокировок (lockless). Архитектура:
  - Пер-ядре кэш (`per-lcore cache`) — маленький пул объектов, к которому ядро обращается без блокировок
  - Глобальный пул — используется только при опустошении локального кэша
  - Выравнивание по линиям кэша (64/128 байт) для предотвращения false sharing

- **librte_mbuf**: Описание структуры пакета. Поддерживает метаданные для аппаратной разгрузки (offloading). Каждый mbuf содержит:
  - Заголовок с метаданными: порт назначения, VLAN-тег, RSS-хэш, тип разгрузки
  - Указатели на сегменты данных (multi-segment mbuf для jumbo frames)
  - Счётчики ссылок (reference counting) для эффективного клонирования

#### Коммуникационные библиотеки

- **librte_ring**: Реализация бесблокировочных очередей «один-ко-многим» или «многие-ко-многим», обеспечивающая сверхбыструю передачу данных между потоками. Поддерживает два режима:
  - **SP/SC (Single Producer / Single Consumer)**: Максимальная скорость для передачи между двумя ядрами
  - **MP/MC (Multi Producer / Multi Consumer)**: Использование атомарных инструкций (CAS) для безопасного обмена в сложных топологиях

- **librte_ethdev**: Унифицированный интерфейс для взаимодействия с различными физическими и виртуальными сетевыми картами. Предоставляет единый API для:
  - Настройки очередей TX/RX
  - Конфигурации RSS и фильтрации
  - Сбора статистики
  - Аппаратных разгрузок (offloading)

#### Дополнительные библиотеки

- **librte_net**: Базовые функции для работы с заголовками сетевых протоколов (Ethernet, IP, TCP, UDP)
- **librte_ip_frag**: Фрагментация и дефрагментация IP-пакетов в userspace
- **librte_hash**: Высокопроизводительные хэш-таблицы для классификации потоков (flow classification)
- **librte_kni**: Kernel NIC Interface — позволяет передавать часть трафика через ядро (для управления, ARP, ICMP) при работе DPDK-приложения
- **librte_vhost**: Библиотека для взаимодействия с виртуальными машинами через vhost-user протокол (used by OVS-DPDK, QEMU)
- **librte_security**: API для аппаратного IPsec/TLS offloading на совместимых NIC
- **librte_compressdev**: API для аппаратного сжатия (compression offload)
- **librte_regexdev**: API для аппаратной регулярной выражений (regex offload, используется в IDS/IPS)

#### Аппаратная разгрузка (Hardware Offloading)

DPDK активно использует возможности современных NIC (ConnectX-8, Intel E810) для снижения нагрузки на CPU:

- **RSS (Receive Side Scaling)**: Аппаратное распределение входящего трафика по разным очередям (и ядрам CPU) на основе хэша заголовков (L3/L4). Управление через `rte_eth_rss_conf`:
  ```c
  struct rte_eth_rss_conf rss_conf = {
    .rss_key = NULL,  // Использовать ключ по умолчанию
    .rss_hf = RTE_ETH_RSS_IP | RTE_ETH_RSS_TCP | RTE_ETH_RSS_UDP,
  };
  rte_eth_dev_configure(port, nb_queues, nb_queues, &port_conf);
  ```

- **Flow Director / Generic Flow API (`rte_flow`)**: Программирование правил фильтрации и классификации пакетов непосредственно в железе NIC. Пример правила для направления трафика VLAN 100 на очередь 3:
  ```c
  struct rte_flow_attr attr = { .ingress = 1 };
  struct rte_flow_item_vlan vlan = { .tci = 100 };
  struct rte_flow_action_queue queue = { .index = 3 };
  rte_flow_create(port, &attr, pattern, actions, &error);
  ```

- **Checksum Offload**: Вычисление контрольных сумм IP/TCP/UDP силами сетевого адаптера. Снижает нагрузку на CPU на 5-10% при высоких скоростях.

- **TSO (TCP Segmentation Offload)**: Аппаратная сегментация больших TCP-сегментов (jumbo frames) на стандартные MTU-пакеты. Позволяет приложению отправлять большие блоки данных, а NIC разбивает их.

---

### Основные концепции обработки данных

#### Проблема стандартного стека Linux

Стандартный путь пакета через ядро (`net_dev → softirq → tcp/ip stack → socket`) не позволяет достичь скоростей 100G+ из-за:

1. **Копирования данных**: Минимум два копирования между буферами NIC, ядра и пользователя. При 100Gbps это ~148 миллионов пакетов в секунду (для 64-байтовых фреймов), каждый из которых копируется минимум 2 раза.
2. **Переключений контекста**: Системные вызовы и прерывания «съедают» циклы процессора. Каждое прерывание NIC требует ~5-10 мкс на обработку.
3. **Блокировок**: Глобальные блокировки в сетевом стеке ограничивают масштабируемость на многопроцессорных системах. При 100Gbps+ блокировки становятся узким местом.
4. **Прерывания (IRQ)**: Каждый пакет генерирует прерывание, что приводит к context switch между ядром и пользовательским пространством.

#### Решение через DPDK (Polling + Zero-copy)

DPDK устраняет эти проблемы:

1. **Polling (Опрос)**: Вместо ожидания прерывания, CPU «владеет» очередью NIC и забирает пакеты максимально быстро. Busy-polling исключает задержки обработки прерываний и context switches.
2. **Zero-copy (Нулевое копирование)**: Благодаря HugePages и DMA, сетевая карта пишет пакеты напрямую в память, к которой у приложения есть прямой доступ. Отсутствие копирования снижает нагрузку на CPU и пропускную способность шины памяти.
3. **Lockless design**: Весь путь пакета внутри DPDK-приложения спроектирован без использования мьютексов и семафоров. Используются атомарные операции (CAS, fetch-and-add) и lock-free очереди.

#### Пакетный путь (Packet Path) в DPDK

```
Физический порт → NIC (RX Parser → RSS Hash → Classifier)
  → DMA Engine → Descriptor Ring (VFIO/UIO маппинг)
    → rte_mempool (alloc mbuf) → PMD (опрос дескрипторов)
      → Приложение ( обработка L2/L3/L4 )
        → PMD (заполнение TX дескрипторов)
          → DMA Engine → TX Queue → MAC → Физический порт
```

Весь этот путь выполняется без участия ядра ОС и без копирования данных между пользователями.

#### Типичные конфигурации запуска

**Сетевой стенд (одно приложение):**
```bash
# Запуск testpmd с 4 ядрами (2-5), 2GB HugePages на NUMA-узле 0
./build/app/testpmd -l 2-5 -n 4 --socket-mem 2048,0 \
  --vdev=net_ice_b0000:01:00.0 -a no-high-precision-timer
# → EAL: Requested 2048 pages of size 1048576K from socket 0
# → Port 0: MAC=XX:XX:XX:XX:XX:XX; PCI=0000:01:00.0
# → Checking link statuses...
# → Port 0: link UP, 100 Gbps, Full Duplex
```

**Мульти-приложение (изоляция через file-prefix):**
```bash
# Приложение A (orks-frontend)
./app_a -l 2-3 --socket-mem 1024,0 --file-prefix=app_a

# Приложение B (orks-backend)
./app_b -l 4-5 --socket-mem 1024,0 --file-prefix=app_b
```

---

### Сравнение DPDK и альтернативных технологий (2026)

| Характеристика | DPDK (25.11 LTS) | XDP (Express Data Path) | AF_XDP | Standard Sockets |
| :--- | :--- | :--- | :--- | :--- |
| **Место выполнения** | Пространство пользователя | Драйвер ядра (eBPF) | Пространство пользователя (через XDP) | Пространство пользователя |
| **Управление NIC** | Монопольное (Kernel bypass) | Совместное с ОС | Совместное с ОС | Совместное с ОС |
| **Производительность** | Экстремальная (400G/800G, >100Mpps) | Очень высокая (100G/200G) | Высокая (10G/25G) | Низкая-средняя (1G/10G) |
| **Загрузка CPU** | 100% (Polling mode, одно ядро на NIC) | Адаптивная (по прерываниям) | Адаптивная | По прерываниям |
| **Сложность разработки** | Высокая (C, API DPDK) | Средняя (eBPF, C) | Средняя (C, libbpf) | Низкая (POSIX sockets) |
| **Изоляция** | Полная (HugePages, CPU pinning) | Частичная | Частичная | Минимальная |
| **Рекомендуется для** | NFV, 5G UPF, HFT, vSwitch | DDoS mitigation, load balancing | Приложения средней производительности | Общего назначения |

**Когда выбирать DPDK:**
- Требуется экстремальная производительность (400G+, терабиты)
- Необходим полный контроль над пакетами (L2-L7 обработка)
- Нужна аппаратная разгрузка (RSS, Flow Director, IPsec offload)
- Важна предсказуемость задержек (HFT, телеком)

**Когда выбирать XDP:**
- Достаточна производительность 100G/200G
- Нужна совместимость с остальной ОС (не монопольный доступ)
- Важна простота интеграции с существующим стеком
- Требуется DDoS-защита или маршрутизация на уровне ядра

---

### Платформы и поддержка

#### Поддерживаемые операционные системы

| ОС | Уровень поддержки | Примечания |
| :--- | :--- | :--- |
| **Linux** | Полная | Основная платформа. Все PMD, все библиотеки. Ядро 5.15+ (рекомендуется 6.1+ LTS). |
| **FreeBSD** | Полная | Ядро 13+. Ограниченный набор PMD (Intel, Mellanox). |
| **Windows** | Экспериментальная | DPDK 21.11+. Поддержка Microsoft VPP. Ограниченный набор PMD. |
| **macOS** | Не поддерживается | Нет нативной поддержки (нет VFIO/UIO). |

#### Поддерживаемые NIC (PMD)

| Вендор | Модели | Драйвер | Макс. производительность |
| :--- | :--- | :--- | :--- |
| **Intel** | E810, X710, X520, XL710 | ice, i40e, ixgbe | 100Gbps (E810) |
| **NVIDIA/Mellanox** | ConnectX-5/6/7/8 | mlx5 | 400Gbps (ConnectX-8) |
| **Broadcom** | BCM57800, NetXtreme-E | bnxt, net_tap (альтернативный) | 100Gbps |
| **Marvell** | OCTEON TX2 | octeontx2 | 100Gbps (ARM) |
| **Базовые (тестирование)** | net_tap, net/null, net/ring | -- | Тестирование и отладка |

**Проверка поддержки NIC:**
```bash
# Проверка поддержки NIC в DPDK
./usertools/dpdk-devbind.py --status
# → Network devices using DPDK-compatible driver
# → ============================================
# → 0000:01:00.0 'Device 1592' if=  drv=ice unused=vfio-pci

# Если NIC не отображается — проверьте поддержку PMD
grep -r "PCI_DEVICE_ID" drivers/net/ice/
# → drivers/net/ice/ice_ethdev.c: ICE_DEV_ID_E810C 0x1592
```

---

### Сборка и установка

#### Предварительные требования

**Аппаратное обеспечение:**
- x86_64 или ARM64 процессор с поддержкой SSE4.2 (x86) или NEON (ARM)
- Сетевой адаптер с поддержкой DPDK PMD (см. таблицу выше)
- Минимум 2 ГБ HugePages (2 МБ страницы) или 1 ГБ HugePages (1 ГБ страницы)

**Программное обеспечение:**
- Linux kernel 5.15+ (рекомендуется 6.1+ LTS)
- GCC 9+ или Clang 12+
- Meson 0.53+ и Ninja
- Python 3.6+ (для скриптов сборки)
- `libnuma-dev` (NUMA-aware выделение памяти)
- `pkg-config` (поиск зависимостей)

**Установка зависимостей (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install -y build-essential meson ninja-build python3-pyelftools \
  libnuma-dev pkg-config libssl-dev linux-headers-$(uname -r)
```

**Установка зависимостей (RHEL/CentOS 9):**
```bash
sudo dnf groupinstall -y "Development Tools"
sudo dnf install -y meson ninja-build python3-pyelftools numactl-devel \
  openssl-devel kernel-devel-$(uname -r)
```

#### Клонирование и сборка

```bash
# Клонирование репозитория DPDK
git clone https://github.com/DPDK/dpdk.git
cd dpdk

# Переключение на стабильную LTS-ветку (рекомендуется)
git checkout v25.11

# Конфигуция сборки
meson setup build
# → Определяет доступные библиотеки и PMD
# → Вывод: " meson.build:1:0: ERROR: ..." если не хватает зависимостей

# Сборка (ускорение через -j$(nproc))
ninja -C build -j$(nproc)
# → Время сборки: ~2-5 минут на 8-ядерном CPU

# Установка (устанавливает библиотеки и утилиты)
sudo ninja -C build install

# Обновление кэша динамических библиотек
sudo ldconfig

# Проверка установки
pkg-config --modversion libdpdk
# → 25.11.0.2511.0
```

**Конфигурация через `meson configure`:**
```bash
# Посмотреть доступные опции
meson configure build | grep -E "^  [a-z]"

# Включить только нужные библиотеки (минимальная сборка)
meson setup build -Ddisable_drivers='net/af_packet' \
  -Dexamples='' -Dtests=false -Dkernel_dir=''

# Или включить всё
meson setup build --wipe -Dexamples=all -Dtests=true
```

#### Проверка сборки

```bash
# Проверка установленных библиотек
ls /usr/local/lib/x86_64-linux-gnu/librte_*
# → /usr/local/lib/x86_64-linux-gnu/librte_eal.so.25.11
# → /usr/local/lib/x86_64-linux-gnu/librte_mempool.so.25.11
# → ...

# Проверка тестовых приложений
ls build/app/testpmd build/app/test
# → build/app/testpmd
# → build/app/test
```

---

### Тестовые приложения DPDK

DPDK поставляется с набором тестовых приложений, которые демонстрируют базовые функции и используются для валидации работоспособности среды.

#### testpmd — основной инструмент тестирования

`testpmd` — универсальное приложение для тестирования производительности NIC, проверки корректности PMD и измерения throughput/latency.

**Запуск в режиме forwarding:**
```bash
# Инициализация EAL, 4 ядра (2-5), привязка к NIC через vdev
./build/app/testpmd -l 2-5 -n 4 --socket-mem 2048,0 \
  --vdev=net_ice_b0000:01:00.0 -- --forward-mode=io \
  --txd=1024 --rxd=1024 --stats-period=1

# Параметры EAL:
# -l 2-5        — Использовать lcore 2, 3, 4, 5
# -n 4          — 4 канала памяти
# --socket-mem  — Выделить 2048 МБ HugePages на NUMA-узле 0

# Параметры testpmd:
# --forward-mode=io  — Режим I/O forwarding (IOR模式, самый быстрый)
# --txd/--rxd        — Размер TX/RX очередей
# --stats-period=1   — Вывод статистики каждую секунду
```

**Просмотр статистики:**
```
---
  Stats:  Port 0: TX-pps: 148000000  RX-pps: 148000000
  Stats:  Port 0: TX-bps: 75776000000  RX-bps: 75776000000
  Stats:  Port 0: TX-errors: 0  RX-errors: 0
  Stats:  Port 0: RX-good-bad: 0  TX-good-bad: 0
---
```

**Запуск с реальным трафиком (廉на):**
```bash
# Запуск с физической NIC (найти PCI-адрес через dpdk-devbind)
./build/app/testpmd -l 2-5 -n 4 -w 0000:01:00.0 --socket-mem 2048,0 \
  -- --forward-mode=io --port-topology=chained --stats-period=1
```

#### l2fwd — маршрутизация L2

Простое L2-коммутатор-приложение, Forwarding пакетов между портами без изменения заголовков.

```bash
# Запуск l2fwd между двумя портами
./build/examples/l2fwd -l 2-3 -n 4 -w 0000:01:00.0 -w 0000:01:00.1 \
  --socket-mem 1024,0 -- -p 0x3 -q 2 -T 0
# → L2FWD: Enterapped by lcore 2
# → L2FWD: lcore 2 forwarding packets
# → L2FWD: Port 0: rx=1234567 tx=1234567
```

#### l3fwd — маршрутизация L3

Приложение маршрутизации на основе LPM (Longest Prefix Match) или em (_exact match).

```bash
# Запуск l3fwd с 4 ядрами и 8 очередями на порт
./build/examples/l3fwd -l 2-5 -n 4 -w 0000:01:00.0 \
  --socket-mem 2048,0 -- --parse-ptype --config="(0,2,4),(1,2,4)" \
  --eth-dest=0,XX:XX:XX:XX:XX:XX
# → L3FWD: Port 0: 148 Mpps
```

#### ipsec-secgw — IPsec шифрование

Пример IPsec-шлюза с аппаратным ускорением шифрования.

```bash
# Запуск с аппаратным IPsec offload (если NIC поддерживает)
./build/examples/ipsec-secgw -l 2-3 -n 4 -w 0000:01:00.0 \
  --socket-mem 2048,0 -- \
  --disable-flows --crypto 0000:00:04.0 --ethdev 0000:01:00.0 \
  --rule "ESP algorithms AES_GCM_128"
```

#### Продвинутые команды testpmd

**Полный список ключевых команд:**

| Команда | Описание | Пример |
| :--- | :--- | :--- |
| `show port info <port>` | Информация о порте (link, RSS, offloads) | `show port info 0` |
| `show port stats <port>` | Статистика RX/TX (packets, bytes, errors) | `show port stats 0` |
| `show port xstats <port>` | Расширенная статистика NIC | `show port xstats 0` |
| `show config fwd` | Текущая конфигурация forwarding | `show config fwd` |
| `set fwd <mode>` | Установка режима forwarding | `set fwd io` / `set fwd mac` / `set fwd rxonly` |
| `start` | Запуск forwarding | `start` |
| `stop` | Остановка forwarding | `stop` |
| `clear port stats all` | Очистка статистики | `clear port stats 0` |
| `show port summary` | Сводка по всем портам | `show port summary` |
| `show port rss hash <port>` | Текущая конфигурация RSS | `show port rss hash 0` |
| `show port flow operations <port>` | Поддерживаемые flow операции | `show port flow operations 0` |
| `flow create <port> ...` | Добавление flow rule | `flow create 0 ingress pattern eth / ipv4 / end actions queue index 2 / end` |
| `flow list <port>` | Просмотр flow rules | `flow list 0` |
| `flow destroy <port> <id>` | Удаление flow rule | `flow destroy 0 0` |
| `flow flush <port>` | Удаление всех flow rules | `flow flush 0` |
| `set mac forward on` | Включение MAC forwarding | `set mac forward on` |
| `set burst <N>` | Установка burst size | `set burst 32` |
| `set txpkts <len>` | Установка размера TX пакета | `set txpkts 64` |

**Примеры типичных workflow:**
```bash
# 1. Просмотр информации о NIC
show port info 0
# → Link: UP, 100 Gbps
# → RSS: Toeplitz, 4 queues
# → Offloads: CHECKSUM RSS_HASH

# 2. Настройка и запуск теста
set fwd io
set burst 32
start

# 3. Мониторинг throughput
show port stats 0
# → TX-pps: 14880952  RX-pps: 14880952  (line-rate при 64B)

# 4. Проверка ошибок
show port xstats 0 | grep -i error

# 5. Остановка и анализ
stop
clear port stats 0
```

---

### Утилиты

| Утилита | Назначение | Пример |
| :--- | :--- | :--- |
| `dpdk-devbind.py` | Управление привязкой PCI-устройств к драйверам (vfio-pci, uio_pci_generic) | `./usertools/dpdk-devbind.py -b vfio-pci 0000:01:00.0` |
| `dpdk-hugeinfo` | Просмотр информации о выделенных HugePages | `./usertools/dpdk-hugeinfo.py` |
| `dpdk-pmdinfo` | Просмотр информации о PMD-драйверах NIC | `./usertools/dpdk-pmdinfo.py` |
| `dpdk-setup.sh` | Интерактивный скрипт начальной настройки (HugePages, привязка NIC) | `./tools/dpdk-setup.sh` |
| `dpdk-proc-info` | Просмотр статистики всех портов DPDK (для запущенных приложений) | `./build/app/dpdk-proc-info --file-prefix=app_a` |
| `dpdk-pmdstats` | Мониторинг аппаратной статистики NIC | `./build/app/dpdk-pmdstats -w 0000:01:00.0` |

**Пример использования `dpdk-devbind.py`:**
```bash
# Просмотр текущего состояния всех PCI-устройств
./usertools/dpdk-devbind.py --status
# → Network devices using kernel driver
# → ====================================
# → 0000:01:00.0 'Device 1592' if= enp1s0f0 drv=ice unused=vfio-pci

# Привязка NIC к vfio-pci для DPDK
./usertools/dpdk-devbind.py -b vfio-pci 0000:01:00.0

# Проверка
./usertools/dpdk-devbind.py --status
# → Network devices using DPDK-compatible driver
# → ============================================
# → 0000:01:00.0 'Device 1592' if= drv=vfio-pci unused=ice
```

---

### Валидация и проверка работоспособности

#### Проверка HugePages

```bash
# Проверка выделенных HugePages
cat /proc/meminfo | grep -i huge
# → HugePages_Total:    4096
# → HugePages_Free:     4096
# → HugePages_Rsvd:        0
# → HugePages_Surp:        0
# → Hugepagesize:       1048576 kB

# Если HugePages_Total = 0 — HugePages не выделены
# Решение: добавить в GRUB hugepagesz=1G hugepages=N
```

#### Проверка IOMMU

```bash
# Проверка что IOMMU включён
dmesg | grep -e DMAR -e IOMMU
# → "DMAR: IOMMU enabled"

# Если вывод пуст — IOMMU не активен
# Решение: добавить intel_iommu=on в GRUB
```

#### Проверка привязки NIC к vfio-pci

```bash
# Проверка что NIC привязана к vfio-pci (не к kernel driver)
./usertools/dpdk-devbind.py --status | grep -A2 "DPDK-compatible"
# → 0000:01:00.0 'Device 1592' if= drv=vfio-pci unused=ice

# Если NIC仍在使用 kernel driver — привязать к vfio-pci
sudo ./usertools/dpdk-devbind.py -b vfio-pci 0000:01:00.0
```

#### Запуск testpmd для проверки

```bash
# Минимальный запуск для проверки что NIC работает через DPDK
./build/app/testpmd -l 2-3 -n 4 -w 0000:01:00.0 --socket-mem 1024,0 \
  -- --forward-mode=io --stats-period=1 --interactive

# В интерактивном режиме:
# > show port stats all
# → Port 0:  RX-packets: 0  TX-packets: 0
# → Если RX/tx растут при подключённом трафике — NIC работает корректно
```

#### Измерение производительности (PMD)

```bash
# Тест throughput в testpmd (IOR模式, loopback через cable/switch)
./build/app/testpmd -l 2-5 -n 4 -w 0000:01:00.0 --socket-mem 2048,0 \
  -- --forward-mode=io --txd=1024 --rxd=1024 --stats-period=1 \
  --burst=32 --txpkts=64

# Ожидаемый результат для 100Gbps NIC (64-байтовые фреймы):
# → TX-pps: 148000000 (148 Mpps = 100Gbps line rate)
# → RX-pps: 148000000
# → TX-errors: 0
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

**Диагностические команды:**
```bash
# Проверка логов ядра на ошибки DPDK/VFIO
dmesg | grep -iE "vfio|iommu|uio" | tail -20

# Проверка статуса PCI-устройств
lspci -v -s 0000:01:00.0

# Проверка使用的 HugePages
cat /proc/meminfo | grep -i huge

# Мониторинг CPU (busy-polling использует 100% ядра)
top -p $(pgrep testpmd)
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

### Практические сценарии

- **Телеком (5G Core / UPF)**: Обработка абонентского трафика на скоростях терабитного уровня. UPF (User Plane Function) реализуется поверх DPDK для инкапсуляции/декапсуляции GTP-U и маршрутизации пользовательских данных.
- **Облачные виртуальные сети**: Ускорение [Open vSwitch (OVS-DPDK)](../../ServicesAndTools/open_vswitch.md). OVS-DPDK обеспечивает коммутацию пакетов между VM на скоростях 100G+ в облаках (OpenStack, CloudStack).
- **Высокочастотный трейдинг (HFT)**: Минимизация задержек до уровня единиц микросекунд. DPDK обеспечивает предсказуемую обработку пакетов без джиттера от ядра, что критично для "tick-to-trade" задержек.
- **Кибербезопасность**: Сверхбыстрые IDS/IPS и файрволы, анализирующие трафик «на лету» без потерь. Suricata с DPDK позволяет анализировать трафик на скоростях 100G+.
- **NFV (Network Function Virtualization)**: Замена аппаратных сетевых устройств программными решениями (DPVS для балансировки, VPP для маршрутизации). Подробные примеры в [Практические сценарии](scenarios.md).
- **AI Fabric**: Сетевые топологии для обмена данными между узлами обучения ИИ на скоростях 400G/800G. Использует GPUDirect RDMA через SR-IOV VF.

---

### Дополнительная информация

- **[Технические детали DPDK](dpdk_technical.md)** — глубокий разбор HugePages, PMD и оптимизации TLB.
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
- **[Практические сценарии DPDK и SR-IOV](scenarios.md)** — примеры интеграции с Kubernetes и AI Fabric.
- **[RSS, RPS, RFS в Linux](../../Linux/Networking/Concepts/rss_rps_rfs.md)** — сравнение аппаратного и программного масштабирования.
