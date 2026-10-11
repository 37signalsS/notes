# Планирование ресурсов (Capacity Planning)

**Актуально для:** Capacity Planning — обзор 2026 года

## Определения

**Планирование ресурсов (Capacity Planning)** — проактивный процесс определения объема вычислительных ресурсов (CPU, RAM, Storage, Network), необходимых для обеспечения текущих и будущих требований бизнеса с соблюдением установленных SLO. В SRE это дисциплина, позволяющая найти баланс между надежностью (избыточность) и эффективностью (затраты).

**Насыщение (Saturation)** — степень заполнения ресурса, при которой дальнейшее увеличение нагрузки приводит к росту очередей и задержек, даже если утилизация не достигла 100%.

**Запас мощности (Headroom)** — разница между текущей утилизацией ресурсов и максимально допустимой мощностью системы до наступления деградации производительности.

**Утилизация (Utilization)** — доля времени или объема ресурса, которая занята полезной работой.

**Прогнозирование (Forecasting)** — расчет будущих потребностей в ресурсах на основе исторических трендов, планов маркетинга и сезонных колебаний.

**Срок подготовки (Lead Time / Time-to-Provision)** — время, необходимое для выделения и настройки новых ресурсов (от заказа сервера до его ввода в эксплуатацию).

## Архитектура процесса Capacity Planning

Capacity Planning — это не одноразовый расчет, а непрерывный процесс с feedback loop.

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Observe   │────▶│   Analyze   │────▶│   Model     │
│ (Сбор метрик)│     │(Корреляция) │     │(Нагрузочное │
└─────────────┘     └─────────────┘     │  тестирование)│
       ▲                               └──────┬──────┘
       │                                      │
       │         ┌─────────────┐     ┌────────▼────────┐
       └─────────│   Predict   │◀────│      Act       │
                 │(Прогноз даты│     │(Масштабирование│
                 │исчерпания)  │     │оптимизация)    │
                 └──────┬──────┘     └────────┬────────┘
                        │                     │
                        └──────────┬──────────┘
                                   │
                             ┌─────▼─────┐
                             │  Verify   │
                             │(Верификация│
                             │изменений)  │
                             └───────────┘
```

**Ключевые принципы:**
- **Data-driven:** Все решения принимаются на основе метрик, а не интуиции.
- **Proactive:** Расширение планируется до исчерпания headroom, а не после.
- **Feedback:** Каждое действие (Act) верифицируется (Verify) и обновляет базу для следующего цикла.
- **Cross-team:** Capacity Planning involves SRE, Infra, App Teams, и Business.

## Теоретические основы

### Закон Литтла (Little's Law)

Фундаментальный закон теории очередей, позволяющий рассчитать необходимую емкость системы для обработки заданного потока запросов.

> `Concurrency = Throughput × Latency`

*   **Concurrency (Параллелизм):** Количество запросов, одновременно находящихся в обработке (или количество необходимых воркеров/потоков).
*   **Throughput (Пропускная способность):** Входящий поток (RPS).
*   **Latency (Задержка):** Среднее время обработки одного запроса.

**Практический вывод:** Если вы планируете обрабатывать 1000 RPS со средним временем ответа 200мс, вам необходимо иметь возможность обрабатывать минимум 200 одновременных запросов (`1000 * 0.2`). Это определяет минимальный размер Thread Pool или количество реплик пода.

> **Подробнее:** См. [Закон Литтла в Законах масштабируемости](./High_Availability/scalability_laws.md#закон-литтла-littles-law).

### Эффект Кингмана (Закон очереди)

Объясняет, почему планирование ресурсов на 100% утилизации невозможно для систем, чувствительных к задержкам.

> `Wait Time ≈ (V) × (U / (1 - U)) × (t)`

При приближении утилизации (`U`) к 1.0 (100%), время ожидания в очереди растет экспоненциально.
*   **80% утилизации:** Время ожидания в 4 раза больше, чем при 0%.
*   **90% утилизации:** В 9 раз больше.
*   **99% утилизации:** В 99 раз больше.

**Вывод для Capacity Planning:** Для систем с высокими требованиями к Tail Latency (p99) планируемая утилизация обычно не должна превышать **60–80%**. Оставшиеся 20–40% составляют «безопасный запас».

### Методология USE (Utilization, Saturation, Errors)

Метод диагностики ресурсов, предложенный Брендоном Греггом:
1.  **Utilization:** Процент времени, когда ресурс был занят.
2.  **Saturation:** Наличие очереди к ресурсу (например, CPU Run Queue, Disk Wait).
3.  **Errors:** Ошибки ресурса (например, ECC errors на памяти, сетевые дропы).

## Методы прогнозирования трендов

Прогнозирование позволяет избежать аврального расширения ресурсов («Firefighting»).

### 1. Линейная регрессия (Trend Analysis)
Анализ роста нагрузки за длительный период (месяцы/кварталы). Позволяет предсказать, когда текущая емкость будет исчерпана при сохранении текущих темпов роста.
*   *Сценарий:* Органический рост пользовательской базы.

### 2. Сезонность (Seasonality)
Учет циклических колебаний:
*   **Суточная:** Пики вечером, спад ночью.
*   **Недельная:** Разница между буднями и выходными.
*   **Календарная:** Черная пятница, Новый год, отчетные периоды.

### 3. Прогнозирование на основе событий (Event-based)
Расчет нагрузки от планируемых изменений:
*   Запуск рекламных кампаний.
*   Релизы новых фич.
*   Миграция новых клиентов на платформу.

## Цикл планирования ресурсов

Процесс планирования в SRE должен быть непрерывным:

1.  **Сбор данных (Observe):** Сбор метрик ресурсов и бизнес-показателей (Orders, DAU).
2.  **Анализ (Analyze):** Корреляция роста нагрузки с изменениями в продукте.
3.  **Моделирование (Model):** Нагрузочное тестирование для поиска Breaking Point.
4.  **Прогноз (Predict):** Определение даты исчерпания емкости (Capacity Burn Rate).
5.  **Действие (Act):** Масштабирование, оптимизация или пересмотр квот.
6.  **Верификация (Verify):** Проверка эффективности внесенных изменений.

## Управление запасом (Headroom Management)

### Типы запаса

*   **Статический запас (Safety Buffer):** Фиксированный процент (например, 30%). Просто, но может быть неэффективно.
*   **Динамический запас (Dynamic Headroom):** Рассчитывается на основе вариативности (стандартного отклонения) нагрузки: `Capacity = Mean_Load + k * StdDev`.
*   **Failover Headroom:** Резерв для выдерживания сбоя N+1 (потеря узла) или N+2 (потеря зоны доступности).
*   **Burst Capacity:** Возможность кратковременно потреблять ресурсы сверх лимитов (например, Burstable CPU в Kubernetes).
*   **Overcommit:** Стратегия, когда сумма Requests превышает физическую емкость (допустимо только для некритичных окружений).

## Практические сценарии

### Планирование в Kubernetes

1.  **Right-sizing:** Анализ `container_memory_working_set_bytes` и `container_cpu_usage_seconds_total` для установки адекватных `requests` (гарантии) и `limits` (защита узла). Инструмент **Goldilocks** (VPA Recommender) автоматически рекомендует значения на основе истории потребления.
2.  **Взаимодействие автоскейлеров:**
    - **HPA:** Масштабирует поды на основе метрик (CPU, RAM, custom). Требует наличия Failover Headroom в кластере — иначе новые поды не поместятся на существующих узлах.
    - **VPA:** Автоматизирует подбор `requests`/`limits`. Полезно для сервисов с постепенным ростом потребления памяти. Режим `recommendationOnly` безопасен для production.
    - **Karpenter / Cluster Autoscaler:** Динамически добавляют узлы. Важно учитывать **Lead Time** (время provisionинга узла), чтобы запас ресурсов на узлах не исчерпался до появления нового узла.
3.  **Bin Packing vs Spread:** Плотная упаковка (Bin Packing) экономит ресурсы, но распределение (Spread) повышает надежность при сбоях узлов.
4.  **Pod Disruption Budgets (PDB):** При планировании capacity необходимо учитывать, что обновления и maintenance могут потребовать остановки подов. PDB гарантирует минимальную доступность.

**Практический расчет Minimal Headroom для кластера:**
```bash
# Расчет доступной емкости кластера с учетом failover
TOTAL_CPU=$(kubectl get nodes -o json | jq '[.items[].status.allocatable.cpu | gsub("m";"") | tonumber] | add')
TOTAL_RAM=$(kubectl get nodes -o json | jq '[.items[].status.allocatable.memory | gsub("Ki";"") | tonumber] | add')
USED_CPU=$(kubectl get pods --all-namespaces -o json | jq '[.items[].spec.containers[].resources.requests.cpu // "0" | gsub("m";"") | tonumber] | add')
USED_RAM=$(kubectl get pods --all-namespaces -o json | jq '[.items[].spec.containers[].resources.requests.memory // "0" | gsub("Ki";"") | tonumber] | add')

CPU_HEADROOM=$(( (TOTAL_CPU - USED_CPU) * 100 / TOTAL_CPU ))
RAM_HEADROOM=$(( (TOTAL_RAM - USED_RAM) * 100 / TOTAL_RAM ))

echo "CPU Headroom: ${CPU_HEADROOM}% (рекомендуется >25%)"
echo "RAM Headroom: ${RAM_HEADROOM}% (рекомендуется >30%)"

# При Failover N+1: потеря одного узла не должна превышать available headroom
LARGEST_NODE_CPU=$(kubectl get nodes -o json | jq '[.items[].status.allocatable.cpu | gsub("m";"") | tonumber] | max')
echo "Max node CPU: ${LARGEST_NODE_CPU}m — Headroom должен превышать это значение"
```

### Физические серверы и on-premise инфраструктура

В отличие от контейнерных сред, где ресурсы масштабируются за минуты, планирование для физических серверов требует месяцев вперед из-за Lead Time на закупку и установку оборудования.

**Ключевые параметры физических серверов:**

| Параметр | Формула расчета | Пример |
| :--- | :--- | :--- |
| **CPU Capacity** | `Серверы × Ядра × Частота × Скорость IPC` | 10 серверов × 16 ядер × 3.0 GHz × IPC 2.0 = 960 GIPS |
| **RAM Capacity** | `Серверы × DIMM × Слоты на планку` | 10 × 8 × 16 ГБ = 1280 ГБ (с учётом NUMA) |
| **Network Bandwidth** | `Серверы × Порты × Скорость` | 10 × 2 × 25 Gbps = 500 Gbps aggregate |
| **Disk IOPS** | `Диски × IOPS_диска × RAID_коэффициент` | 20 × 3000 × 0.6 (RAID5) = 36,000 IOPS |

**Процесс закупки и ввода в эксплуатацию:**
1.  **Определение потребности (Capacity Gap):** Сравнение текущей утилизации с прогнозом. Lead Time от 2 недель (есть на складе) до 3-6 месяцев (special order).
2.  **Спецификация сервера:** Выбор CPU (Intel Xeon / AMD EPYC), количества RAM (с учетом DIMM slot availability), типа дисков (NVMe SSD для IOPS, SATA SSD для capacity).
3.  **Rack и Power:** Планирование U-мест в стойках, рассчет энергопотребления (Watts per server × количество серверов ≤ capacity of PDU).
4.  **Network:** Прокладка кабелей, настройка VLAN, LACP bond для redundancy и throughput.
5.  **OS Provisioning:** PXE boot + Kickstart/Preseed для автоматической установки.

**Пример: оценка энергопотребления стойки:**
```bash
# Сбор данных о потреблении через IPMI
ipmitool -I lanplus -H mgmt-server-01 -U admin -P secret power status
ipmitool -I lanplus -H mgmt-server-01 -U admin -P secret dcmi power reading

# Расчет охлаждения (BTU/hr)
# 1 Watt = 3.412 BTU/hr
SERVERS_IN_RACK=10
WATTS_PER_SERVER=450
TOTAL_WATTS=$((SERVERS_IN_RACK * WATTS_PER_SERVER))
BTU_HR=$(echo "scale=0; $TOTAL_WATTS * 3.412" | bc)
echo "Total heat: ${BTU_HR} BTU/hr — requires $(echo "scale=1; $BTU_HR / 12000" | bc) tons of cooling"
```

### Инфраструктура ЦОД: энергия, охлаждение и размещение

Для on-premise и colocation capacity planning не ограничивается серверами. Необходимо учитывать:
- **Питание:** Мощность PDU (Power Distribution Unit), линии электропередач, UPS (источники бесперебойного питания). Формула: `Watts per server × количество серверов × (1 + growth_factor) ≤ PDU_capacity × количество_PDU`.
- **Охлаждение:** BTU/hr рассчитывается по формуле выше. Важно учитывать CRAC/CRAH (Computer Room Air Conditioning) мощность и hot-aisle/cold-aisle layout.
- **Пространство в стойках (Rack U):** Каждый сервер занимает определенное количество U-мест. При планировании учитывайте также коммутаторы, KVM, панели распределения.
- **Пол (Floor loading):** Для тяжелых стоек с большим количеством дисков (например, Ceph nodes с 36 HDD) необходимо учитывать нагрузку на пол. Стандарт raised floor — 1000–2000 lbs per sq ft.
- **Сеть:** Порт density на коммутаторах (например, 48x10GbE + 6x100GbE per ToR switch). При规划新机架 учитывайте uplink capacity.

**Пример: расчет емкости стойки:**
```bash
# Максимальная мощность стойки
RACK_U=42
PDU_CAPACITY_W=24000  # 24kW per PDU x 2 PDUs per rack
AVERAGE_SERVER_W=450
MAX_SERVERS=$(( RACK_U / 2 ))  # ~21 server x 2U each
TOTAL_POSSIBLE_W=$(( MAX_SERVERS * AVERAGE_SERVER_W ))
echo "Max power: ${TOTAL_POSSIBLE_W}W — ${PDU_CAPACITY_W}W available"
echo "Utilization: $(( TOTAL_POSSIBLE_W * 100 / PDU_CAPACITY_W ))%"
```

### Планирование ресурсов для баз данных

Базы данных — наиболее ресурсоемкий компонент в большинстве инфраструктур. Ошибки capacity planning для БД приводят к наиболее серьезным последствиям.

**PostgreSQL:**

| Ресурс | Формула / Правило | Инструмент мониторинга |
| :--- | :--- | :--- |
| **Connections** | `max_connections` × ~10 МБ RAM на соединение | `pg_stat_activity`, `pgbouncer` |
| **Shared Buffers** | 25% от RAM сервера (до 32 ГБ) | `shared_buffers` в postgresql.conf |
| **Work Mem** | `RAM / max_connections / 4` | `EXPLAIN ANALYZE` покажет usage |
| **WAL Size** | `checkpoint_timeout` × throughput (МБ/с) | `pg_stat_bgwriter` |
| **Disk** | `table_size × growth_rate × retention + indexes` | `pg_database_size()` |

```bash
# Мониторинг соединений PostgreSQL
psql -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state;"
# → Если active connections приближаются к max_connections — планируйте PgBouncer или увеличение RAM

# Прогноз роста таблицы
psql -c "SELECT pg_size_pretty(pg_total_relation_size('big_table'));"
psql -c "SELECT pg_size_pretty(pg_indexes_size('big_table'));"
# Индексы могут занимать 1.5x–3x от размера данных
```

**MySQL/MariaDB:**

| Ресурс | Формула / Правило | Метрика |
| :--- | :--- | :--- |
| **InnoDB Buffer Pool** | 70–80% от RAM (dedicated server) | `Innodb_buffer_pool_size` |
| **Connections** | `max_connections` × 256 КБ (thread stack) | `Threads_connected` |
| **Table Cache** | `open_files_limit / 4` или `table_open_cache` | `Opened_tables` |
| **Disk IOPS** | SSD: 5,000–50,000 IOPS; HDD: 100–200 IOPS | `iostat -x 1` |

```bash
# Оценка использования Buffer Pool
mysql -e "SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool%';"
# Key metric: Innodb_buffer_pool_read_requests / Innodb_buffer_pool_reads = hit ratio (должен быть >99%)

# Мониторинг роста данных
mysql -e "SELECT table_schema, ROUND(SUM(data_length + index_length) / 1024 / 1024, 2) AS 'Size (MB)' FROM information_schema.tables GROUP BY table_schema ORDER BY 2 DESC;"
```

### Планирование ресурсов для очередей сообщений

**Apache Kafka:**

| Ресурс | Формула | Пример |
| :--- | :--- | :--- |
| **Disk** | `(daily_data_GB × replication_factor × retention_days × headroom) / brokers` | `(100 × 3 × 7 × 1.5) / 3 = 1050 ГБ на брокер` |
| **RAM** | `page_cache_size = retention_throughput × 24h × 1.5` | Для 100 МБ/с: 100 × 86400 × 1.5 ≈ 12.6 ГБ page cache |
| **Network** | `peak_throughput × replication_factor × 2` (producer + consumer) | 500 МБ/с × 3 × 2 = 3 Гбит/с на интерфейс |
| **Partitions** | `peak_RPS / target_RPS_per_partition` | 100,000 / 10,000 = 10 партиций на топик |

**RabbitMQ:**

| Ресурс | Правило | Мониторинг |
| :--- | :--- | :--- |
| **RAM** | 1 ГБ на 10,000 queued messages (зависит от size) | `rabbitmqctl status` → `mem_used` |
| **Disk** | Включить `disk_free_limit` (по умолчанию 1 ГБ) | `rabbitmqctl status` → `disk_free` |
| **Connections** | Каждое соединение = ~1 МБ | `rabbitmqctl list_connections` |
| **Queues** | Не более 1000 queues на ноду (зависит от RAM) | `rabbitmqctl list_queues name messages` |

### Планирование ресурсов для хранилищ данных

**Ceph:**

| Компонент | Рекомендация | Формула |
| :--- | :--- | :--- |
| **OSD** | 1 OSD на диск (HDD или SSD) | Минимум 3 OSD для replication |
| **MON** | 3 или 5 (нечетное число для quorum) | Размещать на разных физических серверах |
| **MGR** | 2 (primary + standby) | Может работать на MON серверах |
| **PG (Placement Groups)** | ` OSD_count × 100 / replication_factor` | 6 OSD × 100 / 3 = 200 PG |

```bash
# Мониторинг кластера Ceph
ceph -s
# → Проверяйте: health, osd down, pg degraded, recovery I/O

# Проверка использования пулов
ceph df
ceph osd df tree
# → Если usage > 75% — планируйте добавление OSD

# Прогноз заполнения
ceph osd df tree | awk 'NR>3 {used+=$9; avail+=$10} END {printf "Used: %.1f%%\n", used/(used+avail)*100}'
```

**LVM (Local Volume Manager):**

```bash
# Проверка использования LVM
lvs -o +devices,percent
vgs -o vg_name,vg_free,vg_size

# Мониторинг inode usage (критично для Many Small Files)
df -i | awk '$5 > 80 {print "WARNING: " $6 " inode usage " $5}'

# Планирование роста: если LV растет >5% в месяц — планируйте расширение VG
```

### Планирование ресурсов для CI/CD

CI/CD Runner'ы и пайплайны требуют отдельного capacity planning, особенно при масштабировании команды.

**GitLab Runner:**
```bash
# Расчет необходимого количества Runner'ов
# Формула: runners_needed = (average_jobs × average_duration) / desired_queue_time

AVERAGE_JOBS_PER_HOUR=50
AVERAGE_JOB_DURATION_MIN=10
DESIRED_QUEUE_TIME_MIN=2

RUNNERS_NEEDED=$(echo "scale=0; ($AVERAGE_JOBS_PER_HOUR * $AVERAGE_JOB_DURATION_MIN) / ($DESIRED_QUEUE_TIME_MIN * 60)" | bc)
echo "Need approximately ${RUNNERS_NEEDED} active runners"

# Мониторинг utilization Runner'ов
# GitLab API: GET /api/v4/runners/:id/jobs?status=running
# Метрика: runner_utilization = running_jobs / total_slots
```

**Jenkins:**
```bash
# Оценка потребления ресурсов Jenkins Master
# Каждый подключенный агент = ~50 МБ RAM на Master
# Каждый запущенный build = ~100-500 МБ RAM (зависит от артефактов)

# Планирование disk для артефактов
ARTIFACT_SIZE_MB=100
BUILDS_PER_DAY=200
RETENTION_DAYS=30
TOTAL_DISK_GB=$(echo "scale=0; $ARTIFACT_SIZE_MB * $BUILDS_PER_DAY * $RETENTION_DAYS / 1024" | bc)
echo "Need ${TOTAL_DISK_GB} ГБ for build artifacts"
```

### Планирование ресурсов для DNS и сетевых сервисов

**DNS (BIND/Unbound/CoreDNS):**
```bash
# Планирование DNS: QPS и cache hit ratio
# Формула: cache_size = (unique_domains × avg_record_size) × 1.5

UNIQUE_DOMAINS=100000
AVG_RECORD_SIZE_BYTES=256
CACHE_SIZE_MB=$(echo "scale=0; $UNIQUE_DOMAINS * $AVG_RECORD_SIZE_BYTES * 1.5 / 1024 / 1024" | bc)
echo "DNS cache size: ${CACHE_SIZE_MB} МБ"

# Мониторинг DNS
# BIND: rndc stats → /var/named/data/named_stats.txt
# Unbound: unbound-control stats_noreset
# CoreDNS: plugin.prometheus → metrics
```

**Load Balancer (HAProxy/Nginx):**
```bash
# HAProxy: оценка максимальных соединений
# Каждое соединение = ~32 КБ RAM (TCP) или ~64 КБ (HTTP)
MAX_CONNECTIONS=100000
RAM_PER_CONN_KB=64
TOTAL_RAM_MB=$(echo "scale=0; $MAX_CONNECTIONS * $RAM_PER_CONN_KB / 1024" | bc)
echo "HAProxy needs ~${TOTAL_RAM_MB} МБ RAM for ${MAX_CONNECTIONS} connections"

# Мониторинг: haproxy stats socket
echo "show stat" | socat unix-connect:/var/run/haproxy/admin.sock stdio | \
    awk -F',' '$1 == "frontend" {print $1 ": " $2 " sessions=" $4 " bytes=" $8}'
```

### Мониторинг и алертинг для Capacity Planning

Наблюдаемость — это фундамент capacity planning. Без данных о текущей утилизации и трендах невозможно принимать обоснованные решения о расширении.

**Ключевые метрики для capacity planning:**

| Метрика | Описание | Пример PromQL | Порог алерта |
| :--- | :--- | :--- | :--- |
| **CPU Headroom** | Доступный запас CPU (%) | `1 - (sum(rate(node_cpu_seconds_total{mode="idle"}[5m])) by (instance) / count(node_cpu_seconds_total{mode="idle"}) by (instance))` | < 20% warning, < 10% critical |
| **RAM Headroom** | Доступный запас RAM (%) | `1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)` | < 25% warning, < 15% critical |
| **Disk Headroom** | Доступный запас диска (%) | `1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})` | > 80% warning, > 90% critical |
| **Inode Usage** | Использование inodes (%) | `1 - (node_filesystem_files_free / node_filesystem_files)` | > 80% warning |
| **Network Utilization** | Утилизация сетевого интерфейса (%) | `rate(node_network_receive_bytes_total[5m]) * 8 / node_network_speed_bytes` | > 70% warning, > 85% critical |

**Prometheus recording rules для capacity planning:**
```yaml
# /etc/prometheus/rules/capacity_planning.yml
groups:
  - name: capacity_planning
    interval: 5m
    rules:
      # CPU Headroom по узлам
      - record: node:cpu_headroom:ratio
        expr: |
          1 - (
            sum by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))
            /
            count by (instance) (node_cpu_seconds_total{mode="idle"})
          )

      # RAM Headroom по узлам
      - record: node:memory_headroom:ratio
        expr: |
          1 - (
            node_memory_MemAvailable_bytes
            /
            node_memory_MemTotal_bytes
          )

      # Disk Headroom по узлам
      - record: node:disk_headroom:ratio
        expr: |
          1 - (
            node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"}
            /
            node_filesystem_size_bytes{fstype!~"tmpfs|overlay"}
          )

      # Days until disk full (linear projection)
      - record: node:disk_days_until_full:days
        expr: |
          (node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"}
          /
          (rate(node_filesystem_read_bytes_total[7d]) + rate(node_filesystem_written_bytes[7d])))
          / 86400

      # Capacity burn rate: скорость исчерпания ресурса (% в час)
      - record: node:capacity_burn_rate:percent_per_hour
        expr: |
          (1 - node:memory_headroom:ratio offset 24h)
          - (1 - node:memory_headroom:ratio)
```

**Алерты для proactive capacity management:**
```yaml
# /etc/prometheus/rules/capacity_alerts.yml
groups:
  - name: capacity_planning_alerts
    rules:
      - alert: LowDiskHeadroom
        expr: node:disk_headroom:ratio < 0.15
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "Disk headroom < 15% on {{ $labels.instance }}"
          description: "Доступно {{ $value | humanizePercentage }} дискового пространства. Планируйте расширение."

      - alert: DiskWillFillInWeek
        expr: node:disk_days_until_full:days < 7
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Disk on {{ $labels.instance }} will be full in {{ $value | humanize }} days"

      - alert: CriticalRAMHeadroom
        expr: node:memory_headroom:ratio < 0.1
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "RAM headroom < 10% on {{ $labels.instance }}"
          description: "Риск OOM Kill. Требуется немедленное масштабирование."

      - alert: HighCPUUtilization
        expr: node:cpu_headroom:ratio < 0.1
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "CPU headroom < 10% on {{ $labels.instance }}"
          description: "Система работает на пределе. Рассмотрите оптимизацию или масштабирование."

      - alert: CapacityReviewNeeded
        expr: |
          (
            node:disk_headroom:ratio < 0.2
            or
            node:memory_headroom:ratio < 0.2
            or
            node:cpu_headroom:ratio < 0.2
          )
        for: 7d
        labels:
          severity: info
        annotations:
          summary: "Capacity review needed for {{ $labels.instance }}"
          description: "Один из ресурсов стабильно ниже 20% headroom на протяжении недели."
```

**Практический скрипт еженедельного отчета по capacity:**
```bash
#!/bin/bash
# /opt/scripts/capacity_report.sh — еженедельный отчет по capacity

PROM_URL="http://prometheus:9090"
REPORT_DATE=$(date +%Y-%m-%d)
REPORT_FILE="/var/reports/capacity_${REPORT_DATE}.md"

echo "# Capacity Planning Report — ${REPORT_DATE}" > "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# CPU Headroom
echo "## CPU Headroom" >> "$REPORT_FILE"
curl -s "${PROM_URL}/api/v1/query?query=1-(sum by (instance)(rate(node_cpu_seconds_total{mode='idle'}[5m]))/count by (instance)(node_cpu_seconds_total{mode='idle'}))*100" | \
    jq -r '.data.result[] | "| \(.metric.instance) | \(.value[1] | tonumber | . * 100 | floor)%"' | \
    column -t -s'|' >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# RAM Headroom
echo "## RAM Headroom" >> "$REPORT_FILE"
curl -s "${PROM_URL}/api/v1/query?query=(1-(node_memory_MemAvailable_bytes/node_memory_MemTotal_bytes))*100" | \
    jq -r '.data.result[] | "| \(.metric.instance) | \(.value[1] | tonumber | . * 100 | floor)%"' | \
    column -t -s'|' >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# Disk days until full
echo "## Disk Projection" >> "$REPORT_FILE"
curl -s "${PROM_URL}/api/v1/query?query=(node_filesystem_avail_bytes/(rate(node_filesystem_read_bytes_total[7d])+rate(node_filesystem_written_bytes[7d])))/86400" | \
    jq -r '.data.result[] | "| \(.metric.instance) | \(.metric.mountpoint) | \(.value[1] | tonumber | floor) days"' | \
    column -t -s'|' >> "$REPORT_FILE"

echo "Report generated: ${REPORT_FILE}"
```

## Риски и устранение проблем

### Типичные ошибки

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **OOM Kill** | Исчерпание RAM, утечки памяти | `dmesg | grep -i oom`, `journalctl -k`, метрики памяти | Увеличение лимитов, профилирование памяти (`valgrind`, `heaptrack`), устранение утечек |
| **CPU Throttling** | Превышение limits, CPU-bound нагрузка | `container_cpu_cfs_throttled_seconds_total`, `top`, `perf top` | Увеличение Limits, оптимизация CPU-intensive кода, профилирование через `pprof` |
| **Cascading Failures** | Рост Latency → исчерпание воркеров → отказы | Рост Latency на всех звеньях цепи, `LOAD AVG` > CPU cores | Circuit Breakers, Backpressure (ограничение входящего потока), bulkheads |
| **Disk Space Exhaustion** | Рост данных, логов, артефактов | `df -h`, `du -sh /*`, мониторинг inodes | Ротация логов, compression, archival, увеличение емкости |
| **Inode Exhaustion** | Множество мелких файлов (container images, logs) | `df -i` | Очистка неиспользуемых образов, объединение мелких файлов |
| **Network Saturation** | Высокий throughput, DDoS | `iftop`, `nethogs`, `sar -n DEV` | Ограничение rate, добавление интерфейсов, балансировка |
| **Connection Pool Exhaustion** | Максимум соединений с БД/сервисом | `SHOW PROCESSLIST` (MySQL), `pg_stat_activity` (PG) | Увеличение pool size, PgBouncer/Pgpool, оптимизация long queries |
| **Lock Contention** | Высокая конкуренция за данные | `SHOW ENGINE INNODB STATUS`, `pg_locks` | Оптимизация индексов, разбиение горячих таблиц, sharding |

### Pressure Stall Information (PSI)

Механизм ядра Linux (Kernel 4.20+) для оценки реального насыщения. Показывает процент времени, когда процессы ждали CPU, RAM или I/O. В отличие от утилизации, PSI измеряет реальное влияние на производительность.

```bash
# Проверка PSI для CPU
cat /proc/pressure/cpu
# some avg10=0.50 avg60=0.20 avg300=0.10 total=12345678
# full avg10=0.00 avg60=0.00 avg300=0.00 total=0

# some: Доля времени, когда ХОТЯ БЫ ОДИН процесс был заблокирован
# full: Доля времени, когда ВСЕ процессы были заблокированы

# Проверка PSI для Memory
cat /proc/pressure/memory
# some avg10=2.10 avg60=1.50 avg300=0.80 total=98765432
# full avg10=0.80 avg60=0.30 avg300=0.10 total=45678901

# Проверка PSI для I/O
cat /proc/pressure/io
# some avg10=5.30 avg60=3.20 avg300=1.80 total=34567890
# full avg10=1.20 avg60=0.80 avg300=0.40 total=12345678

# Мониторинг PSI через Prometheus (node-exporter >= 1.8.0)
# Метрики: node_pressure_cpu_waiting_seconds_total, node_pressure_io_waiting_seconds_total
```

**PSI vs Uтилизация:**

| Метрика | Что измеряет | Когда полезна |
| :--- | :--- | :--- |
| **CPU Utilization** | % времени, когда CPU был занят | Общая загрузка, планирование |
| **CPU PSI (some)** | % времени, когда процессы ждали CPU | Обнаружение saturation при <100% utilization |
| **Memory Utilization** | % используемой RAM | Общая оценка потребления |
| **Memory PSI (full)** | % времени, когда все процессы ждали RAM | Ранний индикатор impending OOM |
| **Disk I/O Utilization** | % времени, когда диск был занят | Оценка пропускной способности |
| **Disk I/O PSI (some)** | % времени, когда процессы ждали I/O | Обнаружение bottleneck в storage |

**Пример: алерт на основе PSI:**
```yaml
# Алерт когда хотя бы один процесс ждал CPU >5% времени за 10 минут
- alert: HighCPUPressure
  expr: rate(node_pressure_cpu_waiting_seconds_total[5m]) > 0.05
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "CPU pressure on {{ $labels.instance }}"
    description: "Processes waiting for CPU {{ $value | humanizePercentage }} of time"
```

## Инструментарий

*   **Prometheus/Grafana:** Визуализация трендов, recording rules для capacity metrics, alerting.
*   **VictoriaMetrics:** Долгосрочное хранение данных для годового планирования.
*   **Goldilocks / VPA (Recommender):** Рекомендации по лимитам в K8s на основе истории потребления.
*   **Karpenter:** Эффективное управление емкостью узлов в K8s.
*   **k6 / Locust:** Нагрузочное тестирование для определения реального предела пропускной способности.
*   **node_exporter (>=1.8.0):** Сбор PSI-метрик для оценки реального насыщения.
*   **vmagent (VictoriaMetrics):** Легковесный сбор метрик для on-premise инфраструктуры.
*   **vmestimator (VictoriaMetrics):** Оценка кардинальности в реальном времени для проактивного планирования и предотвращения взрывов серий. Подробнее: [vmestimator](../../VictoriaMetrics/vmestimator.md).
*   **Netdata:** real-time мониторинг с автоматическим обнаружением аномалий.

## Лучшие практики

1.  **Proactive, не Reactive:** Планируйте расширение за 2–4 недели до исчерпания ресурсов. Используйте recording rules с прогнозированием (linear regression на 7/30 дней).
2.  **Бюджет ошибок для capacity:** Если headroom падает ниже 20% — начинайте планирование. Ниже 10% — экстренное расширение. Ниже 5% — risk of cascading failures.
3.  **Регулярные capacity review:** Еженедельный автоматизированный отчет + ежемесячный ручной review с командой.
4.  **Load testing перед расширением:** Не увеличивайте ресурсы, не проверив, что проблема в capacity, а не в коде. Один оптимизированный запрос может заменить добавление сервера.
5.  **Измеряйте Lead Time:** Время от решения о расширении до ввода в эксплуатацию должно быть известно. Для физических серверов — недели/месяцы. Для контейнеров — минуты.
6.  **Учитывайте сезонность:** Не планируйте по среднему значению. Планируйте по пиковому с запасом headroom.
7.  **Document decisions:** Фиксируйте, почему было принято решение о расширении/оптимизации. Через 6 месяцев контекст будет утерян.
8.  **Capacity per failure domain:** При планировании учитывайте сценарий потери AZ/стойки. Ресурсы должны быть распределены так, чтобы оставшиеся домены могли выдержать нагрузку.
9.  **Планируйте backup capacity:** Резервное копирование создает пиковую нагрузку (I/O, сеть, CPU). Убедитесь, что window бэкапара не конфликтует с пиками production.
10. **Не забывайте о «недостающих» ресурсах:** Часто упускают shared storage bandwidth, kernel file descriptors, и network connection tracking (conntrack). Эти ресурсы могут исчерпиться раньше CPU/RAM.

## Граничные случаи

- **Seasonal spikes:** Черная пятница, отчетные периоды, запуск рекламных кампаний. Планируйте по пиковому с запасом 30–50%.
- **Development vs Production:** Dev-среды могут иметь более высокий overcommit ratio, но не должны влиять на capacity planning production.
- **Database workloads:** Требуют выделенных ресурсов; избегайте overcommit CPU/RAM для БД. Планируйте рост индексов и WAL.
- **Batch processing:** Может безопасно использовать высокий CPU overcommit, но требует планирования disk I/O и network peak.
- **Legacy systems:** Устаревшее ПО может иметь неэффективные алгоритмы (O(n²)), которые показывают рост потребления ресурсов непропорционально нагрузке. Требуют отдельного планирования.
- **Noisy Neighbor:** В KVM/Proxmox один «шумный» VM может деградировать производительность остальных. Используйте CPU pinning, limits, и monitoring steal time.
- **Cold start / Scale from zero:** При пуске новых сервисов или после полного останова потребление ресурсов может расти нелинейно. Учитывайте warm-up period при планировании.
- **Backup windows:** Резервное копирование создает пиковую нагрузку на disk I/O и сеть. Планируйте capacity с учетом concurrent backup jobs.
- **Multi-tenancy:** Shared clusters требуют планирования не только по суммарной нагрузке, но и по изоляции (resource quotas, network policies).

## Дополнительная информация

*   **[Законы масштабируемости](./High_Availability/scalability_laws.md)** — теоретический фундамент (Little's Law, Universal Scalability Law).
*   **[Концепции SRE](./sre_concepts_main.md)** — управление надежностью и Error Budgets.
*   **[Наблюдаемость (Observability)](./Observability_and_Monitoring/observability_definitions.md)** — сбор данных для планирования.
