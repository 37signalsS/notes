# OS тюнинг для Apache Kafka

**Актуально для:** Linux Kernel 5.15+ / 6.x, Apache Kafka 3.8.x / 3.9.x / 4.0.x (KRaft / ZooKeeper)

**OS тюнинг** — это комплексная низкоуровневая оптимизация параметров ядра Linux, подсистем виртуальной памяти, дискового ввода-вывода, очередей сетевого стека и ограничений процессов для обеспечения стабильной пропускной способности (throughput) и сверхнизких задержек (latency) брокеров Apache Kafka. Архитектура Kafka спроектирована с расчетом на прямое делегирование управления дисковым кэшированием ядру операционной системы. Некорректные параметры операционной системы приводят к длительным задержкам на сброс грязных страниц (dirty page flush storms), деградации репликации между брокерами, исчерпанию файловых дескрипторов и аварийным остановкам службы.

---

## Определения

- **Page Cache (Кэш страниц):** Подсистема виртуальной файловой системы ядра Linux, использующая невыделенную память оперативной памяти (RAM) для прозрачного кэширования дисковых страниц. Kafka удерживает сегменты логов в Page Cache, исключая накладные расходы на сборку мусора внутри JVM.
- **Zero-Copy (`sendfile`):** Механизм передачи данных напрямую из дискового Page Cache в сетевой сокет через системный вызов ядра Linux (`sendfile(2)`), минуя контекстные переключения и промежуточное копирование данных в пространство пользователя JVM.
- **Dirty Pages (Грязные страницы):** Страницы оперативной памяти в составе Page Cache, содержимое которых было изменено операциями записи приложения (`write`), но еще не синхронизировано с физическим накопителем.
- **Swappiness (`vm.swappiness`):** Параметр ядра Linux (0–100 или 0–200 в современных ядрах), определяющий агрессивность ядра при выгрузке анонимной памяти процессов в раздел подкачки (swap) в пользу удержания файлового Page Cache.
- **THP (Transparent Huge Pages):** Механизм автоматического объединения стандартных страниц памяти (4 КБ) в большие страницы (2 МБ). В высоконагруженных системах вызывает микропаузы (latency spikes) из-за фоновой дефрагментации памяти ядром (`khugepaged`).
- **`vm.max_map_count`:** Системное ограничение на максимальное число областей отображения памяти (Virtual Memory Areas, VMA), которые процесс может создать через системный вызов `mmap(2)`.
- **I/O Scheduler (Планировщик ввода-вывода):** Алгоритм ядра Linux, управляющий очередями дисковых операций и порядком отправки команд на физический контроллер блочного устройства.
- **`noatime` / `nodiratime`:** Опции монтирования файловой системы, отключающие запись времени последнего чтения (`atime`) для файлов и директорий при каждом обращении, предотвращая паразитные дисковые операции записи.
- **JBOD (Just a Bunch of Disks):** Дисковая архитектура прямого подключения накопителей без аппаратного или программного объединения в RAID. Kafka распределяет партиции по нескольким точкам монтирования через параметр `log.dirs`, изолируя сбои отдельных дисков.
- **NUMA (Non-Uniform Memory Access):** Аппаратная архитектура многопроцессорных серверов, где время доступа процессора к локальным банкам памяти существенно меньше, чем к банкам памяти соседних процессорных сокетов.
- **TCP Slow Start After Idle (`net.ipv4.tcp_slow_start_after_idle`):** Механизм сброса размера окна перегрузки (congestion window, `cwnd`) к начальному значению после периода простоя соединения.
- **Ulimit / Resource Limits:** Ограничения на потребление ресурсов (файловые дескрипторы, потоки, блокировка памяти), накладываемые ядром на уровне пользовательских сессий PAM или служб systemd.

---

## Архитектура и принципы взаимодействия Kafka с ядром Linux

### Модель работы с памятью: JVM Heap против Page Cache

Брокеры Apache Kafka принципиально отличаются от традиционных баз данных: они намеренно минимизируют использование кучи Java (JVM Heap обычно выделяется в пределах 6–10 ГБ) и делегируют 65–75% физической оперативной памяти хоста **Page Cache ядра Linux**.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Физическая память сервера (RAM)                       │
├───────────────────────────────┬─────────────────────────────────────────────┤
│         Процесс JVM           │             Ядро Linux и Page Cache         │
├───────────────┬───────────────┼──────────────────────────────┬──────────────┤
│   JVM Heap    │   Off-Heap /  │     Page Cache ядра Linux    │   Ядро ОС    │
│   (6–10 ГБ)   │  Direct Mem   │   (65–75% оперативной памяти)│   и службы   │
│               │   (2–4 ГБ)    │                              │              │
│ • Метаданные  │ • Сетевые     │ • Горячие сегменты (.log)    │ • Буферы сокетов
│ • Purgatory   │   буферы NIO  │ • Индексы (.index/.timeindex)│ • Драйверы   │
│ • Запросы     │ • Дескрипторы │ • Zero-Copy чтение (DMA)     │ • Таблицы сост.
└───────────────┴───────────────┴──────────────────────────────┴──────────────┘
```

Преимущества использования Page Cache вместо хранения данных в JVM Heap:
1. **Отсутствие накладных расходов на объекты Java:** Сегменты сообщений хранятся в памяти байт-в-байт в компактном бинарном виде без служебных заголовков объектов JVM (16–24 байта на объект).
2. **Исключение пауз Garbage Collection (GC):** Очистка и ротация десятков гигабайт кэша сообщений не создает нагрузки на сборщик мусора JVM.
3. **Сохранность кэша при перезапуске брокера:** При перезапуске процесса Kafka данные остаются в системном Page Cache. «Прогрев» кэша с физических дисков после штатного рестарта службы не требуется.
4. **Реализация Zero-Copy через `sendfile`:** Для отдачи данных консьюмерам брокер использует метод Java NIO `FileChannel.transferTo()`, который на уровне ядра транслируется в системный вызов `sendfile(2)`.

```
Традиционная передача (4 копирования, 4 переключения контекста):
[Диск] ──DMA──> [Page Cache] ──CPU──> [JVM Буфер] ──CPU──> [Буфер сокета] ──DMA──> [Сетевая карта]

Zero-Copy через sendfile(2) (0 копирований CPU, 2 переключения контекста):
[Диск] ──DMA──> [Page Cache] ────────────────DMA (дескрипторы)───────────────> [Сетевая карта]
```

---

### Подсистема виртуальной памяти и сброс грязных страниц (Dirty Pages)

При интенсивной записи сообщений продьюсерами ядро накапливает измененные страницы в Page Cache. Управление сбросом данных на физический диск осуществляется демонами ядра `kswapd` и `flush-threads` (`bdi-writeback`).

#### Настройка `vm.dirty_background_ratio` и `vm.dirty_ratio`
- **Фоновый сброс (`vm.dirty_background_ratio` / `vm.dirty_background_bytes`):** Порог, при достижении которого ядро начинает фоновую асинхронную запись страниц на диск через потоки `wb_work`. Процесс записи Kafka при этом не блокируется.
- **Синхронный блокирующий сброс (`vm.dirty_ratio` / `vm.dirty_bytes`):** Жесткий порог, при достижении которого процессы, выполняющие системный вызов `write(2)`, принудительно переводятся в режим синхронной записи до тех пор, пока объем грязных страниц не опустится ниже границы. Для Kafka попадание в этот режим означает остановку потоков обработки сетевых запросов и скачок задержек с миллисекунд до секунд.

#### Проблема больших объемов RAM («Dirty Page Flush Storm»)
На современных серверах с 128–512 ГБ оперативной памяти стандартные процентные значения по умолчанию (`dirty_ratio = 20`, `dirty_background_ratio = 10`) приводят к катастрофическим последствиям:
- При 256 ГБ RAM 10% фонового порога составляют ~25 ГБ грязных страниц.
- Сброс 25–50 ГБ данных на диск за один цикл перегружает дисковые очереди контроллеров, вызывая лавинообразные всплески `iowait` и зависание ввода-вывода.
- **Решение:** На серверах с оперативной памятью более 64 ГБ рекомендуется использовать абсолютные байтовые ограничения (`vm.dirty_background_bytes` и `vm.dirty_bytes`). В ядре Linux одновременное указание `dirty_bytes` автоматически обнуляет `dirty_ratio`, и наоборот.

#### Поведение `vm.swappiness`
- По умолчанию в Linux параметр `vm.swappiness` равен `60`, что заставляет ядро агрессивно выгружать анонимные страницы процессов в swap ради удержания Page Cache. Если в swap попадают страницы JVM Heap, брокер останавливается на время считывания страниц из свопа, что приводит к разрыву сессий и выпадению узла из кворума контроллеров KRaft или ISR.
- Установка `vm.swappiness = 1` предписывает ядру избегать выгрузки памяти в swap при любых обстоятельствах, разрешая сброс в swap только в случае реальной угрозы Out-Of-Memory (OOM). Значение `0` в современных ядрах (>= 3.5) может вызвать преждевременную активацию OOM Killer, поэтому стандартом SRE является значение `1`.

#### Лимит дескрипторов отображения памяти (`vm.max_map_count`)
Каждая партиция Kafka состоит из сегментов журналов. Для каждого активного и закрытого сегмента брокер удерживает в памяти индекс смещений (`.index`) и временной индекс (`.timeindex`), отображаемые в адресное пространство процесса через `mmap(2)`. На брокере с 3000 партиций и ротацией сегментов количество VMA быстро превышает стандартный лимит ядра `65530`, приводя к ошибке `java.io.IOException: Map failed` и аварийному падению брокера. Рекомендуемое значение: `1048576` (минимум `262144`).

---

### Деградация производительности при использовании THP (Transparent Huge Pages)

Transparent Huge Pages (THP) призваны снизить нагрузку на буфер ассоциативной трансляции (TLB) процессора за счет объединения страниц 4 КБ в 2 МБ. Для брокеров Kafka THP представляет критическую угрозу:
1. **Паузы дефрагментации памяти:** Когда ядро не находит свободных непрерывных физических блоков размером 2 МБ, запускается процесс компактификации памяти (`khugepaged`), блокирующий аллокацию памяти для других потоков.
2. **Фрагментация памяти под индексы:** Индексы Kafka имеют переменный размер и разметку, плохо совместимую со страницами 2 МБ, что ведет к перерасходу оперативной памяти.
3. **Хвосты задержек (Tail Latency):** Задержки записи сообщений в P99.9 подскакивают с единиц миллисекунд до сотен миллисекунд и секунд.

**Требование SRE/DevOps:** THP должен быть принудительно отключен на уровне ядра и загрузчика ОС.

---

### Архитектура дисковой подсистемы: Файловые системы, планировщики I/O и JBOD

#### Выбор файловой системы: XFS
XFS является безальтернативным отраслевым стандартом для серверов Apache Kafka:
- Поддержка высокой параллельности за счет групп распределения (Allocation Groups, AG).
- Эффективное выделение непрерывных экстентов для файлов сегментов журналов (`.log`).
- Стабильная производительность при динамическом создании тысяч индексных файлов.

#### Опции монтирования XFS
- `noatime,nodiratime`: Устраняют дисковую запись метаданных времени доступа при чтении сегментов консьюмерами.
- `logbufs=8,logbsize=256k`: Увеличивают буферы журнала метаданных XFS в оперативной памяти, сглаживая пики при интенсивном создании новых файлов сегментов.
- `allocsize=64M`: Задает размер предварительного выделения блоков при записи в конец файла, кардинально снижая фрагментацию сегментов журналов на диске.
- **Статус `nobarrier`:** Опция `nobarrier` признана устаревшей и **удалена в современных ядрах Linux (>= 4.19)**. Ее использование небезопасно: отключение барьеров на дисках без энергонезависимого кэша (BBU/NVRAM) при внезапном сбое электропитания ведет к повреждению структуры файловой системы XFS.

#### Выбор дискового планировщика (I/O Scheduler)
В подсистеме Multi-Queue Block Layer (`blk-mq`) выбор планировщика определяется физической природой накопителей:

| Тип накопителя | Рекомендуемый scheduler | Обоснование |
|----------------|------------------------|-------------|
| **NVMe SSD** | `none` | Аппаратный контроллер NVMe имеет десятки тысяч независимых аппаратных очередей. Программное планирование ядра создает паразитные задержки CPU. |
| **SATA / SAS SSD** | `none` или `mq-deadline` | Отсутствие механических задержек позиционирования головки. `none` минимизирует задержки CPU; `mq-deadline` гарантирует лимит задержки на операцию при перегрузке шины. |
| **HDD (Mechanical)** | `mq-deadline` | Обеспечивает слияние смежных запросов (request merging) для последовательного ввода-вывода и предотвращает голодание очередей записи. |

#### Упреждающее чтение (Readahead)
Kafka последовательно считывает сегменты логов при отдаче консьюмерам. Значение readahead по умолчанию (обычно 128–256 секторов, т.е. 64–128 КБ) является приемлемым. Чрезмерное увеличение readahead (более 512 КБ–1 МБ) на дисках со случайным доступом к историческим данным может вызывать вытеснение полезных страниц из Page Cache («cache thrashing»). Рекомендуется держать readahead в диапазоне `256–1024` секторов (128–512 КБ).

#### JBOD против Hardware RAID 10
В On-Premise инфраструктурах предпочтительной архитектурой является **JBOD**:
- Каждый физический накопитель форматируется в XFS и монтируется в отдельную точку (например, `/data/kafka-disk1`, `/data/kafka-disk2`).
- В `server.properties` брокера указывается список путей: `log.dirs=/data/kafka-disk1,/data/kafka-disk2`.
- Kafka автоматически распределяет новые партиции по дискам с наименьшим числом реплик.
- При физическом выходе из строя одного накопителя отключаются только партиции поврежденного диска. Брокер продолжает функционировать на остальных дисках, а реплики поврежденного диска восстанавливаются репликацией с других брокеров кластера. В случае RAID 10 отказ массива ведет к падению всего брокера.

---

### Особенности работы на многопроцессорных NUMA-узлах

На двухсокетных и четырехсокетных серверах память разделена между процессорами. Если брокер Kafka работает без учета топологии NUMA:
1. Выделение памяти под Page Cache может сосредоточиться на одном сокете, вызвав локальное исчерпание памяти.
2. При исчерпании локального банка узел может активировать локальную очистку страниц (`zone reclaim`), вызывая блокировку потоков Kafka, даже если на соседнем сокете свободно 100+ ГБ RAM.

**Правила настройки NUMA для Kafka:**
- `vm.zone_reclaim_mode = 0`: Обязательно отключено. При нехватке локальной памяти ядро должно немедленно выделять память из удаленных узлов NUMA, а не инициировать синхронный сброс локальных страниц.
- Запуск процесса Kafka с чередованием памяти: `numactl --interleave=all`. Политика чередования равномерно распределяет аллокации памяти JVM и структур Page Cache по всем NUMA-нодам, предотвращая дисбаланс шин межпроцессорного взаимодействия (UPI/QPI).

---

### Сетевой стек ядра Linux и буферизация TCP

Брокер Kafka передает гигабайты сетевого трафика между клиентами и узлами репликации. Узкие места сетевого стека приводят к отбрасыванию пакетов (packet drops), разрывам TCP-соединений и повторным передачам (retransmits).

#### Буферы сокетов и TCP окон
- Параметры `net.core.rmem_max` и `net.core.wmem_max` задают верхний предел размера буферов приема и передачи для всех сокетов ОС. Для 10GbE / 25GbE сетей минимальный порог составляет 16 МБ (`16777216`), а для высокопроизводительных кластеров и репликации между удаленными ЦОД — 32 МБ (`33554432`).
- Векторы `net.ipv4.tcp_rmem` и `net.ipv4.tcp_wmem` управляют автоматической подстройкой буферов TCP (минимальный, по умолчанию, максимальный размер):
  - По умолчанию в ядре среднее значение часто равно 87 КБ / 65 КБ, что недостаточно для высокоскоростной передачи с большими задержками (Bandwidth-Delay Product, BDP).

#### Очереди соединений (Backlog Queues)
- `net.core.somaxconn`: Максимальный размер очереди полностью установленных соединений (listen backlog). При массовом переподключении тысяч продьюсеров или консьюмеров стандартное значение `128` или `4096` приводит к ошибкам `Connection reset by peer`. Рекомендуется: `32768`–`65535`.
- `net.ipv4.tcp_max_syn_backlog`: Очередь полуоткрытых соединений (SYN_RECV). Рекомендуется: `16384`–`32768`.
- `net.core.netdev_max_backlog`: Очередь пакетов на входе сетевой карты перед передачей сетевому стеку ядра. Рекомендуется: `30000`–`250000`.

#### Параметры поведения TCP
- `net.ipv4.tcp_slow_start_after_idle = 0`: По умолчанию TCP после периода отсутствия передачи данных сбрасывает размер окна перегрузки в начальное состояние (Slow Start). Отключение этого параметра предотвращает просадку пропускной способности на постоянных keepalive-соединениях консьюмеров и брокеров.
- `net.ipv4.tcp_tw_reuse = 1`: Разрешает безопасное повторное использование сокетов в состоянии `TIME_WAIT` для новых исходящих соединений (требует включенных временных меток `tcp_timestamps = 1`).
- **Устаревший параметр `tcp_tw_recycle`:** Данный параметр ломал работу клиентов за корпоративными NAT/маршрутизаторами и был **полностью удален из ядра Linux (>= 4.12)**. Его конфигурирование не допускается.

---

## Практические сценарии и конфигурация

### Сценарий 1: Комплексная конфигурация sysctl

Создайте конфигурационный файл для параметров ядра `/etc/sysctl.d/99-kafka.conf`. Выберите блок управления памятью в зависимости от объема физической памяти хоста.

#### Вариант А: Серверы с RAM до 64 ГБ (Процентные пороги)

```ini
# /etc/sysctl.d/99-kafka.conf

# ==============================================================================
# 1. Управление виртуальной памятью (RAM < 64 ГБ)
# ==============================================================================
vm.swappiness = 1
vm.dirty_background_ratio = 5
vm.dirty_ratio = 10
vm.dirty_writeback_centisecs = 500
vm.dirty_expire_centisecs = 3000
vm.max_map_count = 1048576
vm.zone_reclaim_mode = 0

# ==============================================================================
# 2. Сетевой стек: Буферы сокетов и TCP
# ==============================================================================
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 262144
net.core.wmem_default = 262144
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.ipv4.tcp_window_scaling = 1
net.ipv4.tcp_timestamps = 1
net.ipv4.tcp_sack = 1

# ==============================================================================
# 3. Сетевой стек: Очереди соединений и защита от перегрузок
# ==============================================================================
net.core.somaxconn = 32768
net.ipv4.tcp_max_syn_backlog = 16384
net.core.netdev_max_backlog = 30000
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15

# ==============================================================================
# 4. TCP Keepalive (обнаружение сетевых сбоев)
# ==============================================================================
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 60
net.ipv4.tcp_keepalive_probes = 3

# ==============================================================================
# 5. Лимиты файловой системы ядра
# ==============================================================================
fs.file-max = 2097152
```

#### Вариант Б: Серверы с RAM 64 ГБ и выше (Байтовые пороги против I/O Storm)

Для серверов с большим объемом оперативной памяти (128–512 ГБ) замените блок `vm.dirty_*_ratio` на фиксированные байты:

```ini
# /etc/sysctl.d/99-kafka.conf

# Защита от сброса анонимной памяти в swap
vm.swappiness = 1

# Фоновый сброс при накоплении 256 МБ грязных страниц
vm.dirty_background_bytes = 268435456

# Блокировка записи процесса только при накоплении 1024 МБ грязных страниц
vm.dirty_bytes = 1073741824

# Таймеры сброса
vm.dirty_writeback_centisecs = 500
vm.dirty_expire_centisecs = 3000

# Индексные файлы mmap и NUMA
vm.max_map_count = 1048576
vm.zone_reclaim_mode = 0

# Сетевые буферы (32 МБ для высокоскоростных интерфейсов 10/25/40GbE)
net.core.rmem_max = 33554432
net.core.wmem_max = 33554432
net.core.rmem_default = 262144
net.core.wmem_default = 262144
net.ipv4.tcp_rmem = 4096 87380 33554432
net.ipv4.tcp_wmem = 4096 65536 33554432
net.ipv4.tcp_window_scaling = 1
net.ipv4.tcp_timestamps = 1
net.ipv4.tcp_sack = 1

# Сетевые очереди
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 32768
net.core.netdev_max_backlog = 250000
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15

# Keepalive и файловые дескрипторы
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 3
fs.file-max = 2097152
```

Применение параметров ядра:
```bash
sudo sysctl --system
# → * Applying /etc/sysctl.d/99-kafka.conf ...
# → vm.swappiness = 1
# → vm.dirty_background_ratio = 5
# → vm.dirty_ratio = 10
# → vm.max_map_count = 1048576
# → net.core.somaxconn = 32768
# → net.core.rmem_max = 16777216
# → net.core.wmem_max = 16777216
# → ...
```

---

### Сценарий 2: Гарантированное отключение Transparent Huge Pages (THP)

Для полного отключения THP требуется комбинированный подход: системный сервис `systemd` на этапе ранней инициализации ОС и передача параметров ядру в загрузчике GRUB.

#### Шаг 1: Создание раннего systemd-юнита
Создайте файл `/etc/systemd/system/disable-thp.service`:

```ini
[Unit]
Description=Disable Transparent Huge Pages (THP) for Apache Kafka
DefaultDependencies=no
After=sysinit.target local-fs.target
Before=basic.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo never > /sys/kernel/mm/transparent_hugepage/enabled && echo never > /sys/kernel/mm/transparent_hugepage/defrag'
RemainAfterExit=yes

[Install]
WantedBy=basic.target
```

Активация и запуск сервиса:
```bash
sudo systemctl daemon-reload
# → (успешно перечитаны юниты systemd)

sudo systemctl enable --now disable-thp.service
# → Created symlink /etc/systemd/system/basic.target.wants/disable-thp.service → /etc/systemd/system/disable-thp.service.

sudo systemctl status disable-thp.service
# → ● disable-thp.service - Disable Transparent Huge Pages (THP) for Apache Kafka
# →      Loaded: loaded (/etc/systemd/system/disable-thp.service; enabled; preset: enabled)
# →      Active: active (exited) since Mon 2026-10-12 14:00:00 UTC; 10s ago
```

#### Шаг 2: Фиксация в загрузчике GRUB (персистентность при старте ядра)
Отредактируйте строку `GRUB_CMDLINE_LINUX` в файле `/etc/default/grub`:
```text
GRUB_CMDLINE_LINUX="... transparent_hugepage=never"
```

Обновление конфигурации загрузчика:
```bash
# Для систем семейства Debian / Ubuntu:
sudo update-grub
# → Sourcing file `/etc/default/grub'
# → Generating grub configuration file ...
# → done

# Для систем семейства RHEL / Rocky Linux / AlmaLinux:
sudo grub2-mkconfig -o /boot/grub2/grub.cfg
# → Generating grub configuration file ...
# → done
```

Проверка применения:
```bash
cat /sys/kernel/mm/transparent_hugepage/enabled
# → always madvise [never]

cat /sys/kernel/mm/transparent_hugepage/defrag
# → always defer defer+madvise madvise [never]
```

---

### Сценарий 3: Подготовка блочных устройств и монтирование файловой системы XFS

#### Шаг 1: Форматирование раздела диска
При форматировании дисков под хранение данных Kafka (`log.dirs`) задайте размер блока метаданных:

```bash
sudo mkfs.xfs -f -i size=512 -d agcount=16 /dev/sdb1
# → meta-data=/dev/sdb1              isize=512    agcount=16, agsize=30517568 blks
# → data     =                       bsize=4096   blocks=488281088, imaxpct=25
# → naming   =version 2              bsize=4096   ascii-ci=0, ftype=1
# → log      =internal log           bsize=4096   blocks=238418, version=2
# → realtime =none                   extsz=4096   blocks=0, rtextents=0
```

#### Шаг 2: Конфигурация постоянного монтирования в `/etc/fstab`
Определите UUID устройства с помощью `blkid`:
```bash
sudo blkid /dev/sdb1
# → /dev/sdb1: UUID="7b1e8f2a-5d6c-4b8a-9e2f-3d1c4b5a6e7f" BLOCK_SIZE="4096" TYPE="xfs" PARTUUID="..."
```

Добавьте запись в `/etc/fstab` с оптимальными опциями для Kafka:
```text
# Точка монтирования данных Kafka JBOD Disk 1
UUID=7b1e8f2a-5d6c-4b8a-9e2f-3d1c4b5a6e7f /var/lib/kafka/data-1 xfs defaults,noatime,nodiratime,logbufs=8,logbsize=256k,allocsize=64M,largeio,inode64 0 2
```

Применение монтирования и валидация:
```bash
sudo mkdir -p /var/lib/kafka/data-1
sudo mount -a

findmnt /var/lib/kafka/data-1
# → TARGET                 SOURCE    FSTYPE OPTIONS
# → /var/lib/kafka/data-1  /dev/sdb1 xfs    rw,noatime,nodiratime,attr2,inode64,logbufs=8,logbsize=256k,allocsize=64M,largeio,noquota
```

---

### Сценарий 4: Автоматизация планировщиков I/O и readahead через udev

Чтобы настройки планировщика блочных устройств и упреждающего чтения сохранялись после перезагрузки сервера и подключения накопителей, создайте правило udev `/etc/udev/rules.d/99-kafka-disk.rules`:

```ini
# /etc/udev/rules.d/99-kafka-disk.rules

# NVMe накопители: scheduler none, readahead 512 секторов (256 КБ)
ACTION=="add|change", KERNEL=="nvme[0-9]*n[0-9]*", ATTR{queue/scheduler}="none", ATTR{queue/read_ahead_kb}="256"

# SATA/SAS SSD накопители (non-rotational): scheduler none или mq-deadline, readahead 256 КБ
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="none", ATTR{queue/read_ahead_kb}="256"

# Механические диски HDD (rotational): scheduler mq-deadline, readahead 512 КБ
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="1", ATTR{queue/scheduler}="mq-deadline", ATTR{queue/read_ahead_kb}="512"
```

Применение правил udev без перезагрузки:
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger --type=devices --subsystem-match=block

# Проверка текущего планировщика для диска:
cat /sys/block/sdb/queue/scheduler
# → [none] mq-deadline kyber bfq

cat /sys/block/sdb/queue/read_ahead_kb
# → 256
```

---

### Сценарий 5: Настройка системных лимитов ресурсов (systemd и PAM limits)

Службы, управляемые `systemd`, **игнорируют** ограничения файла `/etc/security/limits.conf` (PAM). Для брокера Kafka лимиты должны быть настроены непосредственно в unit-файле systemd.

#### Шаг 1: Конфигурация systemd drop-in override
Создайте директорию и файл переопределения `/etc/systemd/system/kafka.service.d/override.conf`:

```ini
# /etc/systemd/system/kafka.service.d/override.conf
[Service]
# Лимит открытых файловых дескрипторов (1 000 000)
LimitNOFILE=1000000

# Лимит количества потоков и процессов
LimitNPROC=512000

# Блокировка памяти (предотвращение свопирования кучи JVM)
LimitMEMLOCK=infinity

# Размер core dump файлов при авариях
LimitCORE=infinity
```

Применение изменений в systemd:
```bash
sudo systemctl daemon-reload
sudo systemctl restart kafka.service
```

#### Шаг 2: Конфигурация PAM limits (для сессий пользователей и CLI инструментов)
Для утилит командной строки и пользователя `kafka` настройте `/etc/security/limits.d/99-kafka.conf`:

```text
# /etc/security/limits.d/99-kafka.conf
kafka   soft   nofile   1000000
kafka   hard   nofile   1000000
kafka   soft   nproc    512000
kafka   hard   nproc    512000
kafka   soft   memlock  unlimited
kafka   hard   memlock  unlimited
```

Проверка действующих ограничений работающего процесса Kafka:
```bash
KAFKA_PID=$(pgrep -f "kafka.Kafka")
cat /proc/${KAFKA_PID}/limits | grep -E "Max open files|Max processes|Max locked memory"
# → Max open files            1000000              1000000              files
# → Max processes             512000               512000               processes
# → Max locked memory         unlimited            unlimited            bytes
```

---

### Сценарий 6: Оптимизация очередей сетевой карты (Ring Buffers и Offloading)

На серверах с сетевыми интерфейсами 10GbE / 25GbE / 40GbE стандартный размер аппаратного кольцевого буфера сетевой карты (Ring Buffer) часто ограничен 256–512 дескрипторами. При кратковременных всплесках сетевого трафика буфер переполняется до того, как ядро успеет обработать пакеты через SoftIRQ, что вызывает потерю пакетов (`rx_dropped`).

#### Шаг 1: Проверка и увеличение Ring Buffer
```bash
# Просмотр текущих и максимальных лимитов:
sudo ethtool -g eth0
# → Ring parameters for eth0:
# → Pre-set maximums:
# → RX:        4096
# → TX:        4096
# → Current hardware settings:
# → RX:        512
# → TX:        512

# Установка максимальных буферов приема и передачи:
sudo ethtool -G eth0 rx 4096 tx 4096
# → (параметры успешно применены)
```

#### Шаг 2: Проверка аппаратного ускорения (Offload)
Убедитесь, что включены механизмы Large Receive Offload (LRO) / Generic Receive Offload (GRO) и TCP Segmentation Offload (TSO):
```bash
sudo ethtool -k eth0 | grep -E "tcp-segmentation-offload|generic-receive-offload"
# → tcp-segmentation-offload: on
# → generic-receive-offload: on
```

#### Шаг 3: Сохранение настроек сетевой карты при перезагрузке
Для персистентности создайте systemd-юнит `/etc/systemd/system/nic-tuning.service`:

```ini
[Unit]
Description=Set Network Interface Ring Buffers for Kafka
After=network.target

[Service]
Type=oneshot
ExecStart=/sbin/ethtool -G eth0 rx 4096 tx 4096
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now nic-tuning.service
# → Created symlink /etc/systemd/system/multi-user.target.wants/nic-tuning.service → /etc/systemd/system/nic-tuning.service.
```

---

### Сценарий 7: Запуск брокера с учетом топологии NUMA

На многопроцессорных серверах с двумя и более сокетами привязка процесса Kafka к политике чередования памяти исключает асимметрию и локальные задержки межпроцессорной шины.

#### Шаг 1: Анализ топологии NUMA
```bash
numactl --hardware
# → available: 2 nodes (0-1)
# → node 0 cpus: 0 1 2 3 4 5 6 7 16 17 18 19 20 21 22 23
# → node 0 size: 128820 MB
# → node 0 free: 42150 MB
# → node 1 cpus: 8 9 10 11 12 13 14 15 24 25 26 27 28 29 30 31
# → node 1 size: 128990 MB
# → node 1 free: 45600 MB
# → node distances:
# → node   0   1
# →   0:  10  21
# →   1:  21  10
```

#### Шаг 2: Интеграция `numactl` в systemd-юнит брокера
Отредактируйте `/etc/systemd/system/kafka.service.d/override.conf`:

```ini
[Service]
# Запуск брокера с чередованием страниц по всем NUMA узлам
ExecStart=
ExecStart=/usr/bin/numactl --interleave=all /opt/kafka/bin/kafka-server-start.sh /etc/kafka/server.properties
```

Применение:
```bash
sudo systemctl daemon-reload
sudo systemctl restart kafka.service

# Проверка политики памяти активного процесса:
grep -i interleave /proc/$(pgrep -f "kafka.Kafka")/numa_maps | head -n 3
# → 7f3b80000000 interleave:0-1 anon=...
# → 7f3bc0000000 interleave:0-1 anon=...
# → 7f3c00000000 interleave:0-1 anon=...
```

---

## Операции и команды валидации

В таблице ниже приведены обязательные команды проверки состояния подсистем ОС узла Kafka.

| Подсистема | Команда проверки | Ожидаемый результат / Целевое значение |
|---|---|---|
| **Swappiness** | `sysctl vm.swappiness` | `# → vm.swappiness = 1` |
| **Dirty Pages (фон)** | `sysctl vm.dirty_background_ratio` | `# → vm.dirty_background_ratio = 5` |
| **Dirty Pages (блок)** | `sysctl vm.dirty_ratio` | `# → vm.dirty_ratio = 10` |
| **Лимит mmap** | `sysctl vm.max_map_count` | `# → vm.max_map_count = 1048576` |
| **Zone Reclaim** | `sysctl vm.zone_reclaim_mode` | `# → vm.zone_reclaim_mode = 0` |
| **TCP Somaxconn** | `sysctl net.core.somaxconn` | `# → net.core.somaxconn = 32768` (или `65535`) |
| **TCP SYN Backlog** | `sysctl net.ipv4.tcp_max_syn_backlog`| `# → net.ipv4.tcp_max_syn_backlog = 16384` |
| **TCP Buffers** | `sysctl net.core.rmem_max net.core.wmem_max` | `# → net.core.rmem_max = 16777216`<br>`# → net.core.wmem_max = 16777216` |
| **Slow Start Idle** | `sysctl net.ipv4.tcp_slow_start_after_idle` | `# → net.ipv4.tcp_slow_start_after_idle = 0` |
| **THP Enabled** | `cat /sys/kernel/mm/transparent_hugepage/enabled` | `# → always madvise [never]` |
| **THP Defrag** | `cat /sys/kernel/mm/transparent_hugepage/defrag` | `# → always defer defer+madvise madvise [never]` |
| **Limit NOFILE** | `cat /proc/$(pgrep -f kafka.Kafka)/limits \| grep "open files"` | `# → Max open files 1000000 1000000 files` |
| **I/O Scheduler** | `cat /sys/block/sdb/queue/scheduler` | `# → [none] mq-deadline ...` (для NVMe/SSD) |
| **ФС XFS Опции** | `findmnt -no OPTIONS /var/lib/kafka/data-1` | `# → rw,noatime,nodiratime,...,logbufs=8,logbsize=256k,allocsize=64M` |

Комплексный однострочный скрипт экспресс-аудита:
```bash
echo "=== 1. Virtual Memory ==="
sysctl vm.swappiness vm.dirty_background_ratio vm.dirty_ratio vm.max_map_count vm.zone_reclaim_mode

echo "=== 2. Network Core ==="
sysctl net.core.somaxconn net.ipv4.tcp_max_syn_backlog net.core.rmem_max net.core.wmem_max net.ipv4.tcp_slow_start_after_idle

echo "=== 3. Transparent Huge Pages ==="
cat /sys/kernel/mm/transparent_hugepage/enabled

echo "=== 4. Process Limits ==="
cat /proc/$(pgrep -f "kafka.Kafka" | head -n 1)/limits | grep "open files"
```

Ожидаемый вывод проверки:
```text
=== 1. Virtual Memory ===
vm.swappiness = 1
vm.dirty_background_ratio = 5
vm.dirty_ratio = 10
vm.max_map_count = 1048576
vm.zone_reclaim_mode = 0
=== 2. Network Core ===
net.core.somaxconn = 32768
net.ipv4.tcp_max_syn_backlog = 16384
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_slow_start_after_idle = 0
=== 3. Transparent Huge Pages ===
always madvise [never]
=== 4. Process Limits ===
Max open files            1000000              1000000              files
```

---

## Диагностика и устранение неисправностей (Troubleshooting)

### Сводная таблица типовых сбоев подсистем ОС

| Симптом / Ошибка | Вероятная причина | Инструмент диагностики | Метод устранения |
|---|---|---|---|
| Резкие скачки latency в P99.9, зависания записи | Фоновый лавинообразный сброс Dirty Pages | `iostat -xz 1`, `vmstat 1`, `/proc/meminfo` | Перевести `vm.dirty_*` с процентных значений на фиксированные байты |
| Микрозадержки потоков JVM на 100–500 мс | Дефрагментация THP демоном `khugepaged` | `grep compact /proc/vmstat` | Отключить THP: `transparent_hugepage=never` |
| `java.io.IOException: Map failed` | Превышение лимита областей памяти `vm.max_map_count` | `wc -l /proc/<pid>/maps` | Увеличить `vm.max_map_count = 1048576` |
| `java.io.IOException: Too many open files` | Исчерпание файловых дескрипторов процесса | `ls -1 /proc/<pid>/fd \| wc -l` | Прописать `LimitNOFILE=1000000` в override-файле службы systemd |
| Разрывы соединений, рост метрики `Connection reset` | Переполнение очереди `listen` (`somaxconn`) | `nstat -az TcpExtListenOverflows` | Увеличить `net.core.somaxconn` и `net.ipv4.tcp_max_syn_backlog` |
| Потеря пакетов на сетевом интерфейсе | Переполнение буфера сетевой карты Ring Buffer | `ethtool -S eth0 \| grep -E "drop\|miss"` | Увеличить Ring Buffer: `ethtool -G eth0 rx 4096 tx 4096` |
| Выпадение брокера из ISR, свопирование кучи | Высокий `vm.swappiness` или нехватка RAM | `vmstat 1` (колонки `si`/`so`), `free -m` | Выставить `vm.swappiness=1`, проверить объем свободной памяти под Page Cache |
| Падение процесса Kafka от Linux OOM Killer | Чрезмерный размер Heap + нехватка памяти под Direct Buffer | `dmesg -T \| grep -i oom`, `/var/log/messages` | Ограничить JVM Heap (до 8–10 ГБ), оставить 70% RAM под Page Cache |

---

### Диагностические сценарии SRE

#### 1. Диагностика лавинообразного сброса грязных страниц (Dirty Page Flush Storm)
**Признаки:** Всплеск метрики `%iowait` по данным утилиты `top`, резкое падение скорости обработки сообщений брокером.

Диагностика объема накопленных грязных страниц:
```bash
grep -E "Dirty|Writeback" /proc/meminfo
# → Dirty:           14582912 kB
# → Writeback:        4194304 kB
```
Если объем `Dirty` превышает несколько гигабайт, а значение `Writeback` держится на максимуме, подсистема I/O перегружена синхронным сбросом страниц.

Мониторинг задержек дисковых очередей:
```bash
iostat -xz 1 5
# → Device    r/s   w/s    rkB/s     wkB/s  rrqm/s  wrqm/s  %rrqm  %wrqm  r_await  w_await  aqu-sz  %util
# → sdb      0.00 4500.00   0.00 580000.00    0.00 1200.00   0.00  21.05     0.00   184.20   42.50  99.80
```
*Интерпретация:* Значение `w_await > 50–100 ms` и `aqu-sz > 10` при утилизации `%util ~ 100%` свидетельствуют об образовании пробки ввода-вывода.  
*Решение:* Переключите параметры ядра на `vm.dirty_background_bytes = 268435456` и `vm.dirty_bytes = 1073741824`, чтобы сброс страниц выполнялся непрерывно малыми порциями.

---

#### 2. Диагностика пауз из-за Transparent Huge Pages (THP Compaction)
**Признаки:** JVM GC логи показывают нормальные времена сборок, но задержки запросов клиентов подскакивают.

Диагностика счетчиков дефрагментации страниц ядра:
```bash
grep -E "compact_stall|compact_fail|compact_success" /proc/vmstat
# → compact_stall 14280
# → compact_fail 8120
# → compact_success 6160
```
Если счетчик `compact_stall` непрерывно увеличивается в реальном времени (`watch -n 1 'grep compact_stall /proc/vmstat'`), потоки процессора блокируются ядром в попытке выделить непрерывные страницы 2 МБ.  
*Решение:* Примените Сценарий 2 для принудительного отключения THP в `/sys/kernel/mm/transparent_hugepage/enabled`.

---

#### 3. Диагностика исчерпания сетевых очередей сокетов (Listen Drops)
**Признаки:** Клиенты Kafka регистрируют таймауты подключения `ConnectTimeoutException`, в логах брокера фиксируются обрывы соединений.

Диагностика переполнения очередей ядра:
```bash
nstat -az TcpExtListenOverflows TcpExtListenDrops
# → #kernel
# → TcpExtListenOverflows           1420               0.0
# → TcpExtListenDrops               1420               0.0
```
Проверка текущего размера очереди слушающего сокета Kafka (порт 9092):
```bash
ss -lnt '( sport = :9092 )'
# → State    Recv-Q   Send-Q   Local Address:Port   Peer Address:Port
# → LISTEN   32769    32768    0.0.0.0:9092         0.0.0.0:*
```
*Интерпретация:* Если значение `Recv-Q` превышает `Send-Q`, сокет входящих соединений переполнен. Ядро отбрасывает новые запросы на установку соединений.  
*Решение:* Увеличьте `net.core.somaxconn` до `65535` и убедитесь, что параметр брокера `socket.max.connection.receive.buffer` и сетевые пулы потоков `num.network.threads` настроены оптимально.

---

#### 4. Диагностика утечек и исчерпания файловых дескрипторов
**Признаки:** В логе `server.log` появляется фатальная ошибка `java.io.IOException: Too many open files`.

Подсчет открытых дескрипторов работающего процесса:
```bash
KAFKA_PID=$(pgrep -f "kafka.Kafka")
ls -1 /proc/${KAFKA_PID}/fd | wc -l
# → 142850
```
Аудит распределения открытых дескрипторов по типам:
```bash
lsof -p ${KAFKA_PID} | awk '{print $5}' | sort | uniq -c | sort -nr
# → 98400 REG    (файлы сегментов журналов .log и индексов)
# → 43200 IPv4   (клиентские сокеты и репликация)
# →  1200 FIFO   (каналы межпроцессного взаимодействия)
# →    50 DIR    (директории разделов)
```
*Решение:* Если число открытых файлов приближается к лимиту процесса, увеличьте `LimitNOFILE` в файле `/etc/systemd/system/kafka.service.d/override.conf` до `1000000`.

---

## Лучшие практики и откат изменений (Rollback)

### Рекомендации по эксплуатации в On-Premise инфраструктуре

1. **Изоляция дисковых шпинделей:** Никогда не размещайте операционную систему, логи приложений Kafka (`/var/log/kafka`) и данные партиций (`log.dirs`) на одном физическом диске. Активная запись логов ОС в `/var/log` деградирует последовательный ввод-вывод данных топиков.
2. **Отказ от Cloud/AI надстроек на bare-metal:** При развертывании в корпоративном ЦОД избегайте виртуализации поверх виртуализации. Прямой доступ брокеров к физическим накопителям NVMe/SAS через JBOD обеспечивает наименьшие задержки.
3. **Идемпотентность и автоматизация:** Все настройки ядра (`sysctl`), правила udev и сервисы systemd должны распространяться централизованно через Ansible. Прямое ручное внесение изменений на продакшн-серверах запрещено.
4. **Резервирование оперативной памяти:** На сервере с 128 ГБ RAM выделяйте брокеру 8 ГБ под JVM Heap, оставляя ~115 ГБ под системный Page Cache. При превышении JVM Heap свыше 32 ГБ включается 64-битная адресация указателей (отключается Compressed Oops), что снижает эффективность использования кэшей процессора L1/L2/L3.

---

### Пошаговая процедура безопасного отката (Rollback & Cleanup)

Если после применения тюнинга операционной системы возникла нестабильность, выполните процедуру возврата к стандартным настройкам ОС.

#### Шаг 1: Восстановление стандартных параметров sysctl
Удалите или отключите файл пользовательских параметров ядра:
```bash
sudo rm -f /etc/sysctl.d/99-kafka.conf
sudo sysctl --system
# → Параметры ядра перезагружены из стандартных системных файлов дистрибутива
```

#### Шаг 2: Отключение сервиса disable-thp и возврат настроек THP
```bash
sudo systemctl stop disable-thp.service
sudo systemctl disable disable-thp.service
sudo rm -f /etc/systemd/system/disable-thp.service
sudo systemctl daemon-reload

# Возврат стандартного режима THP в ядре (madvise):
echo madvise | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
echo madvise | sudo tee /sys/kernel/mm/transparent_hugepage/defrag
# → madvise
```

#### Шаг 3: Удаление правил udev для планировщиков дисков
```bash
sudo rm -f /etc/udev/rules.d/99-kafka-disk.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --type=devices --subsystem-match=block
```

#### Шаг 4: Удаление переопределений лимитов systemd
```bash
sudo rm -rf /etc/systemd/system/kafka.service.d/
sudo systemctl daemon-reload
sudo systemctl restart kafka.service
```

---

## Дополнительная информация

### Связанные руководства в базе знаний

- **[JVM и GC тюнинг для Apache Kafka](./kafka_jvm_gc_tuning.md)** — распределение памяти между Heap и Page Cache, конфигурация сборщиков мусора G1GC и ZGC.
- **[Потоковая модель брокера Kafka](./kafka_broker_thread_model.md)** — конфигурация пулов `num.network.threads`, `num.io.threads` и их взаимодействие с сокетами ядра.
- **[Развертывание кластера Kafka через Ansible](./kafka_ansible_deployment.md)** — автоматизация развертывания конфигураций `sysctl`, `limits.conf` и systemd на bare-metal серверах.
- **[Гарантии доставки и надежность](./delivery_guarantees.md)** — влияние параметров сброса `dirty_ratio` и `fsync` на сохранность сообщений.
- **[Playbook по устранению неисправностей Kafka](./kafka_troubleshooting_playbook.md)** — пошаговое руководство по расследованию инцидентов при сбоях брокеров и деградации репликации.
- **[Мониторинг Kafka](./kafka_for_monitoring.md)** — ключевые метрики брокера, операционной системы и дашборды.
- **[Capacity Planning и Disaster Recovery](./kafka_capacity_dr.md)** — расчет дисковой емкости, сайзинг оборудования и стратегии отказоустойчивости в On-Premise инфраструктуре.
- **[Обзор архитектуры Apache Kafka](./kafka_overview.md)** — фундаментальные концепции брокера, репликации и хранения данных в журналах сообщений.
