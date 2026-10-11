# Тюнинг и выбор оборудования для OSD

Руководство по подбору оборудования и оптимизации параметров OSD в кластере Ceph для различных рабочих нагрузок. Документ актуален для версий **Squid (19.x)**, **Tentacle (20.x)** и **Umbrella (21.x)**.

> **Границы документа:** общее управление OSD описано в [Операциях Ceph](./Administration/operations.md); производительность кластера в целом — в [Бенчмаркинге](./ceph_benchmarks.md); планирование емкости — в [Обзоре Ceph](./ceph_overview.md).

## Определения

**IOPS** (Input/Output Operations Per Second) — количество операций ввода-вывода в секунду. Критично для баз данных и low-latency хранилищ.

**Throughput** — пропускная способность, МБ/с. Важна для больших файлов, видео, бэкапов.

**Latency** — задержка ответа на операцию, мс. Измеряется через `ceph osd perf` (commit + apply).

**mclock** — планировщик Quality-of-Service для OSD, доступный начиная с Ceph v17+. Автоматически приоритизирует клиентский I/O относительно recovery-операций.

**Small files** — объекты < 64KB. Создают высокую нагрузку на метаданные и метаданный кэш OSD.

**Big data** — объекты > 1MB. Нагрузка primarily на дисковую подсистему и сеть.

## Базовые концепции

### Выбор дискового типа

| Тип диска | IOPS | Throughput | Latency | Стоимость | Сценарий |
|-----------|------|------------|---------|-----------|----------|
| **SATA HDD** (7200) | 100-150 | 100-200 MB/s | 10-20 ms | Низкая | Кластеры с большим объемом, холодные данные |
| **SAS HDD** (10K) | 150-200 | 150-250 MB/s | 8-15 ms | Средняя | Базы данных, средние нагрузки |
| **SAS HDD** (15K) | 200-300 | 200-300 MB/s | 5-10 ms | Средняя+ | Высоконагруженные базы данных |
| **SATA SSD** | 10K-50K | 500 MB/s | 0.1-0.5 ms | Средняя+ | Кэши, метаданные, hot data |
| **NVMe SSD** | 100K-1M | 3-7 GB/s | 0.02-0.1 ms | Высокая | Критичная производительность, базы данных |
| **ZNS SSD** | 50K-500K | 3-5 GB/s | 0.05-0.2 ms | Высокая | Объектные хранилища, write-intensive |

### Память OSD

| Параметр | Рекомендация | Комментарий |
|----------|--------------|-------------|
| **Минимум на OSD** | 4 GB | Ниже — деградация производительности |
| **Рекомендуется** | 8 GB | Оптимально для большинства нагрузок |
| **Высоконагруженные кластеры** | 16+ GB | Big data, high IOPS, EC-пулы |
| **Crimson OSD** | 4-8 GB | Меньше потребление за счет SeaStar |

Память используется под:
- Кэш метаданных BlueStore (RocksDB block cache)
- Буферы I/O
- Внутренние структуры OSD (PG,PG history)
- Journal/WAL (если on SSD)

**Формула оценки:**
```
Память на OSD = (количество объектов на OSD × 150 байт) + 2 GB
```
Пример: 10 млн объектов × 150 байт = 1.5 GB + 2 GB = 3.5 GB → минимум 4 GB.

### Сеть

| Сценарий | Рекомендация |
|----------|--------------|
| **Минимальная** | 10 Гбит/с (1 GbE неприемлем для production) |
| **Средняя** | 25 Гбит/с |
| **Высоконагруженная** | 40/100 Гбит/с |
| **MTU** | 9000 (Jumbo Frames) — обязательно для 10G+ |
| **Отдельная сеть** | Cluster network отдельно от public (client) |

## Практические сценарии

### 1. Конфигурация OSD под различные нагрузки

#### 1.1 Хранилище для баз данных (PostgreSQL/MySQL)

**Требования:** низкая latency, высокая IOPS, надежность.

```bash
# Рекомендуемая конфигурация
# - NVMe SSD для данных
# - Отдельный NVMe для DB/WAL (или тот же, если достаточной производительности)
# - 8 GB RAM на OSD
# - 25/100 GbE сеть

# Параметры tuning
ceph config set osd osd_mclock_profile high_client_ops
ceph config set osd osd_recovery_max_active 1
ceph config set osd osd_max_backfills 1
```

#### 1.2 Хранилище для больших файлов (видео, бэкапы)

**Требования:** высокая пропускная способность, емкость.

```bash
# Рекомендуемая конфигурация
# - SATA HDD 7200 RPM
# - SATA SSD для DB/WAL (200-500 GB на OSD)
# - 8 GB RAM на OSD
# - 10/25 GbE сеть

# Параметры tuning
ceph config set osd bluestore_min_alloc_size_hdd 65536
ceph config set osd bluestore_compression_mode passive
```

#### 1.3 Хранилище для small files (объекты < 64KB)

**Требования:** высокая IOPS, большой кэш метаданных.

```bash
# Рекомендуемая конфигурация
# - NVMe SSD
# - Отдельный NVMe для DB/WAL
# - 16 GB RAM на OSD
# - 25/100 GbE сеть

# Параметры tuning
ceph config set osd bluestore_min_alloc_size 4096
ceph config set osd osd_mclock_profile high_client_ops
```

### 2. Параметры конфигурации OSD

#### 2.1 Память

```bash
# Глобально
ceph config set global osd_memory_target 8G

# Для конкретного OSD (например, на узле с 64 GB RAM)
ceph config set osd.host-a osd_memory_target 16G

# Проверка
ceph config get osd osd_memory_target
```

#### 2.2 Параллельность recovery

```bash
# Глобально
ceph config set osd osd_max_backfills 2
ceph config set osd osd_recovery_max_active 4

# Для конкретного OSD
ceph config set osd.5 osd_max_backfills 1

# Сброс к умолчанию
ceph config rm osd osd_max_backfills
```

#### 2.3 mclock профили

| Профиль | Использование |
|---------|--------------|
| `balanced` | По умолчанию. Баланс между клиентским I/O и recovery. |
| `high_client_ops` | Минимизировать влияние recovery на клиентов. Для production СУБД. |
| `high_recovery_ops` | Ускорить recovery/backfill. Для maintenance-окон. |

```bash
# Применить профиль
ceph config set osd osd_mclock_profile high_client_ops
```

#### 2.4 Сжатие

```bash
# Алгоритмы
# - lz4: быстро, низкое сжатие (~2:1), для hot data
# - zstd: баланс скорости и сжатия (~3:1)
# - snappy: быстро, очень низкое сжатие (~1.5:1)
# - zlib: медленно, высокое сжатие (~4:1), для cold data

# Глобально
ceph config set global bluestore_compression_algorithm zstd
ceph config set global bluestore_compression_mode passive

# Для конкретного пула
ceph osd pool set <pool-name> compression_algorithm zstd
ceph osd pool set <pool-name> compression_mode aggressive
```

### 3. Размер Placement Groups

| Количество OSD | Рекомендуемое PG на пул |
|----------------|------------------------|
| < 10 | 64-128 |
| 10-50 | 128-256 |
| 50-200 | 256-512 |
| > 200 | 512-1024 |

**Формула:**
```
PG = (OSD_count × 100) / replication_factor
```
Округлите до ближайшей степени двойки.

### 4. Аппаратные требования

#### 4.1 Минимальная конфигурация

| Компонент | Минимум | Рекомендация |
|-----------|---------|--------------|
| **CPU** | 2 ядра на OSD + 2 ядра на MON/MGR | 8+ ядер на узел с 4 OSD |
| **RAM** | 4 GB на OSD + 4 GB на MON/MGR | 16+ GB на узел |
| **Сеть** | 1 GbE (тестовая) | 10+ GbE (production) |
| **Диски** | SATA HDD | NVMe SSD для production |
| **MON** | 3 узла | 3 или 5 узлов |

#### 4.2 Пример конфигурации узла

```
Сценарий: Production, 100 TB usable, replication factor 3

Устройство: Supermicro 2028TP-HC1R
- CPU: 2× Intel Xeon Silver 4210 (20 cores total)
- RAM: 128 GB DDR4
- Диски: 12× 16 TB SATA HDD (9.6 TB usable × 4 nodes = 38.4 TB × 3 = 115 TB raw → ~38 TB usable)
- Сеть: 2× 25 GbE (public + cluster)
- MON: 3 отдельных узла или collocated
- OSD: 12 на узел × 4 узла = 48 OSD
```

### 5. Производительность: Benchmarks

```bash
# Тест OSD (rados bench)
rados -p <pool-name> bench 60 write --no-cleanup
rados -p <pool-name> bench 60 seq

# Тест через RBD
rbd bench --io-pattern=rand --io-total=1024 test-image write
rbd bench --io-pattern=rand --io-total=1024 test-image read

# Мониторинг latency
ceph osd perf
# → commit: 5ms, apply: 3ms (good)
# → commit: 80ms, apply: 20ms (disk degradation)
```

### 6. Оптимизация для конкретных сценариев

#### 6.1 High IOPS (базы данных)

```yaml
# spec.yaml
service_type: osd
service_id: db_osds
placement:
  label: osd_nvme
data_devices:
  rotational: false
db_devices:
  rotational: false
wal_devices:
  rotational: false
```

```bash
# Параметры
ceph config set osd osd_mclock_profile high_client_ops
ceph config set osd osd_max_backfills 1
ceph config set osd osd_recovery_max_active 1
```

#### 6.2 High Capacity (архивы)

```yaml
service_type: osd
service_id: archive_osds
placement:
  label: osd_hdd
data_devices:
  rotational: 1
db_devices:
  rotational: 0
  size: "200G:"
wal_devices:
  rotational: 0
  size: "50G:"
```

```bash
# Параметры
ceph config set osd bluestore_min_alloc_size_hdd 65536
ceph config set osd bluestore_compression_algorithm zstd
ceph config set osd osd_mclock_profile balanced
```

## Лучшие практики

### Развертывание

1. **Стартуйте с запасом 20%:** не заполняйте диски более чем на 80%. Recovery и growth требуют места.
2. **Одинаковые диски в одном кластере:** смешивание разных типов дисков усложняет capacity planning.
3. **DB/WAL на NVMe:** для HDD-кластеров это обязательно, а не рекомендуется.
4. **Сеть:** 10 GbE минимум; для NVMe-кластеров 25/100 GbE.

### Эксплуатация

1. **Мониторинг SMART:** настройте `smartd` для оповещения о предстоящих отказах.
2. **Регулярный capacity planning:** `ceph df` и `ceph osd df tree` еженедельно.
3. **Scrubbing:** настройте окно scrubbing на часы минимальной нагрузки.
4. **Апгрейд:** один мажорный релиз за раз; тестируйте на staging.

## Дополнительная информация

### См. также

- [Операции Ceph](./Administration/operations.md) — управление OSD, конфигурация
- [Бенчмаркинг](./ceph_benchmarks.md) — тестирование производительности
- [Обзор Ceph](./ceph_overview.md) — архитектура и выбор интерфейса
- [BlueStore Maintenance](./ceph_bluestore_maintenance.md) — обслуживание BlueStore
- [BlueStore Maintenance](./ceph_bluestore_maintenance.md) — обслуживание BlueStore

### Официальные ресурсы

- [Ceph Hardware Recommendations](https://docs.ceph.com/en/latest/rados/hardware-requirements/) — аппаратные требования
- [Ceph OSD Configuration](https://docs.ceph.com/en/latest/rados/configuration/osd-config-ref/) — параметры конфигурации
- [Ceph BlueStore Configuration](https://docs.ceph.com/en/latest/rados/configuration/bluestore-config-ref/) — BlueStore-параметры
