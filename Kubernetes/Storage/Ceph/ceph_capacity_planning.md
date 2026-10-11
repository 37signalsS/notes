# Capacity Planning для Ceph

Руководство по планированию емкости кластера Ceph: расчет usable capacity, выбор конфигурации, прогноз роста и стратегии расширения. Документ актуален для версий **Squid (19.x)**, **Tentacle (20.x)** и **Umbrella (21.x)**.

> **Границы документа:** аппаратный подбор — в [Тюнинге и выборе оборудования OSD](./ceph_osd_tuning.md); бенчмаркинг — в [Бенчмаркинге Ceph](./ceph_benchmarks.md); управление пулами — в [Операциях Ceph](./Administration/operations.md).

## Определения

**Raw Capacity** — полная физическая емкость всех дисков кластера (сумма всех OSD).

**Usable Capacity** — полезная емкость после учета replication factor или EC overhead.

**Replication Overhead** — коэффициент избыточности для replicated пулов. При size=3 полезная емкость = Raw / 3.

**EC Overhead** — коэффициент избыточности для erasure coding. При k=4, m=2 overhead = (k+m)/k = 1.5x.

**N+1 Resilience** — кластер должен выдерживать отказ одного failure domain (стойки, узла) без потери данных и с сохранением SLA.

**Nearfull Ratio** — порог заполнения OSD (по умолчанию 0.85), при котором начинается алерт и планирование расширения.

**Full Ratio** — критический порог заполнения (по умолчанию 0.95), при котором запись блокируется.

## Базовые концепции

### Формулы емкости

#### Replicated пулы

```
Usable = Raw_Capacity / Replication_Factor
```

Пример:
- 12 дисков × 16 TB = 192 TB raw
- Replication factor = 3
- Usable = 192 / 3 = 64 TB

#### EC пулы

```
Usable = Raw_Capacity × k / (k + m)
Overhead = (k + m) / k
```

Пример:
- 12 дисков × 16 TB = 192 TB raw
- k=4, m=2 (EC 4+2)
- Usable = 192 × 4 / 6 = 128 TB
- Overhead = 6 / 4 = 1.5x

#### Смешанные пулы

```
Total_Usable = Σ(Usable_replicated_pools) + Σ(Usable_ec_pools)
```

### Факторы, влияющие на usable capacity

| Фактор | Влияние | Рекомендация |
|--------|---------|--------------|
| **Replication factor** | 3x для production | size=3, min_size=2 |
| **EC overhead** | 1.2x–2.0x | k=4,m=2 для hot data; k=8,m=3 для cold |
| **Reserved for recovery** | 10-20% | Не заполняйте >80% |
| **OSD metadata** | ~0.1% | BlueStore RocksDB |
| **Snapshots** | Зависит от churn | 10-30% дополнительно |

## Практические сценарии

### 1. Расчет емкости для нового кластера

#### 1.1 Определение требований

```yaml
Требования:
  - Usable capacity: 100 TB
  - Workload: mixed (VMs + databases + archives)
  - SLA: 99.99% availability
  - Growth: 20% per year

Расчет:
  # Replicated пул для VMs (size=3)
  Raw_needed = 100 TB × 3 = 300 TB
  
  # EC пул для архивов (k=4, m=2, overhead 1.5x)
  Raw_needed_ec = 50 TB × 1.5 = 75 TB
  
  # Итого raw
  Total_raw = 300 + 75 = 375 TB
  
  # С запасом на growth (3 года)
  Total_raw_with_growth = 375 × 1.5 = 562 TB
  
  # Конфигурация:
  # 36 дисков × 16 TB = 576 TB raw
  # 3 узла × 12 дисков = 36 OSD
```

#### 1.2 Выбор конфигурации

| Параметр | Значение | Обоснование |
|----------|----------|-------------|
| Диски | 12 × 16 TB HDD | Емкость, стоимость |
| OSD на узел | 12 | 1 OSD на диск |
| MON | 3 узла | HA, кворум |
| MGR | 2 узла | Active/standby |
| Сеть | 2 × 25 GbE | Public + cluster |
| RAM | 64 GB на узел | 8 GB на OSD + 16 GB на MON/MGR |

### 2. Мониторинг и алертинг

```bash
# Текущее использование
ceph df
# → TOTAL    AVAIL   USED   RAW  %USED
# → 192 TB   45 TB   147 TB 192 TB  76%

# Детализация по OSD
ceph osd df tree
# → ID  CLASS  WEIGHT   USED   AVAIL  %USED
# → 0   hdd    1.82     1.5 TB 1.5 TB  50%

# Проверка nearfull
ceph config get mon mon_osd_nearfull_ratio
# → 0.85

# Порог для алерта
ceph osd dump | grep nearfull
```

**Рекомендуемые алерты:**
- `nearfull_ratio > 0.80` — Planning capacity expansion
- `nearfull_ratio > 0.90` — Emergency capacity expansion
- `full_ratio > 0.95` — Critical, write blocked

### 3. Стратегия расширения

#### 3.1 Добавление OSD (in-place)

```bash
# 1. Добавление нового хоста
ceph orch host add new-host --labels=osd_hdd

# 2. Развертывание OSD
ceph orch apply osd --all-available-devices

# 3. Мониторинг rebalancing
ceph status
ceph osd tree
```

**Влияние на производительность:**
- Recovery/backfill конкурирует за I/O с клиентами.
- Используйте `osd_max_backfills` и `osd_recovery_max_active` для ограничения.
- Включите `noscrub`/`nodeep-scrub` на время expansion.

#### 3.2 Добавление racks/datacenters

```bash
# 1. Добавление новых хостов в новый rack
ceph orch host add rack-c-host-1 --labels=osd_hdd
ceph orch host add rack-c-host-2 --labels=osd_hdd

# 2. Перемещение хостов в новый bucket
ceph osd crush move rack-c-host-1 rack=rack-c
ceph osd crush move rack-c-host-2 rack=rack-c

# 3. Обновление CRUSH правила (если нужно)
ceph osd crush rule create-replicated hdd_rack_c default host hdd

# 4. Проверка
ceph osd tree
```

### 4. Pool Sizing Strategies

#### 4.1 PG count per pool

```bash
# Формула
PG = (OSD_count × 100) / replication_factor
# Округлить до ближайшей степени двойки: 128, 256, 512, 1024

# Пример: 100 OSD, replication=3
PG = (100 × 100) / 3 = 3333 → 4096

# Пример: 50 OSD, EC 4+2
PG = (50 × 100) / 4 = 1250 → 1024
```

#### 4.2 Рекомендации по PG

| OSD Count | Replicated Pools | EC Pools |
|-----------|------------------|----------|
| < 10 | 64–128 | 32–64 |
| 10–50 | 128–256 | 64–128 |
| 50–200 | 256–512 | 128–256 |
| > 200 | 512–1024 | 256–512 |

### 5. Прогноз роста

```python
# Пример расчета роста на 3 года
current_raw = 192  # TB
growth_rate = 0.20  # 20% per year
years = 3

for year in range(1, years + 1):
    needed = current_raw * ((1 + growth_rate) ** year)
    print(f"Year {year}: {needed:.1f} TB raw needed")

# Year 1: 230.4 TB
# Year 2: 276.5 TB
# Year 3: 331.8 TB
```

### 6. N+1 Resilience Planning

```bash
# Проверка: может ли кластер выдержать отказ одного failure domain?
ceph osd tree
# → rack-a: 24 OSD (192 TB raw, 64 TB usable)
# → rack-b: 24 OSD (192 TB raw, 64 TB usable)

# При отказе rack-a:
# → Оставшаяся capacity: 192 TB raw, 64 TB usable (при size=3)
# → Достаточно ли для текущей нагрузки? Да.

# При отказе rack-a + ремонте rack-b:
# → Риск: если rack-b тоже отказывается — потеря данных
# → Решение: минимум 3 racks для production
```

## Лучшие практики

### Планирование

1. **Начинайте с запасом 20-30%** на growth и recovery.
2. **Не превышайте 80% заполнения** — после 80% recovery замедляется.
3. **Планируйте по failure domains** — кластер должен выдерживать отказ целой стойки/узла.
4. **Учитывайте overhead** — replication 3x, EC 1.2-2.0x, snapshots 10-30%.

### Мониторинг

1. **Еженедельно:** `ceph df`, `ceph osd df tree`, алерты на nearfull.
2. **Ежемесячно:** capacity planning review, прогноз роста.
3. **Ежеквартально:** оценка конфигурации, планы на expansion.

### Эксплуатация

1. **Не добавляйте OSD разных размеров** в один пул без корректировки весов.
2. **Используйте device classes** для отделения HDD/SSD/NVMe.
3. **Включайте PG autoscaler** — он автоматически подбирает количество PG.
4. **Тестируйте expansion** на staging перед production.

## Дополнительная информация

### См. также

- [Тюнинг и выбор оборудования OSD](./ceph_osd_tuning.md) — hardware selection
- [Бенчмаркинг Ceph](./ceph_benchmarks.md) — тестирование производительности
- [Операции Ceph](./Administration/operations.md) — добавление хостов и OSD
- [CRUSH Advanced Topics](./ceph_crush_advanced.md) — failure domain design
- [Резервное копирование и DR](./ceph_backup_and_dr.md) — репликация и EC overhead

### Официальные ресурсы

- [Ceph Capacity Planning](https://docs.ceph.com/en/latest/rados/operations/capacity-planning/) — официальное руководство
- [Ceph Hardware Recommendations](https://docs.ceph.com/en/latest/rados/hardware-requirements/) — аппаратные требования
