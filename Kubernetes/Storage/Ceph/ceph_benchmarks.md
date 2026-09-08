# Бенчмаркинг и тестирование производительности Ceph

Документ охватывает инструменты и методики тестирования производительности кластера Ceph: бенчмарки для RBD, CephFS и RADOS, анализ результатов и capacity planning. Актуально для версий **Squid (19.x)**, **Tentacle (20.x)** и **Umbrella (21.x)**.

---

## Определения

**IOPS (Input/Output Operations Per Second)** — количество операций ввода-вывода в секунду. Основная метрика для случайных нагрузок (СУБД, виртуальные машины).

**Throughput (Пропускная способность)** — объём данных, обрабатываемых в секунду (МБ/с или Гбит/с). Основная метрика для последовательных нагрузок (медиа, бэкапы).

**Latency (Задержка)** — время выполнения одной операции ввода-вывода (мс или мкс). Критична для OLTP и latency-sensitive приложений.

**Bandwidth (Ширина канала)** — максимальная пропускная способность сети или дисковой подсистемы.

**Рандомное чтение/запись** — операции I/O к случайным блокам данных. Тестирует производительность для workload с низким кэшированием.

**Последовательное чтение/запись** — операции I/O к последовательным блокам данных. Тестирует максимальную пропускную способность.

---

## Базовые концепции

### Что измерять

| Метрика | Инструмент | Сценарий |
|---------|-----------|----------|
| **IOPS (randread/randwrite)** | `rbd bench`, `fio` | СУБД, OLTP |
| **Throughput (seqread/seqwrite)** | `rbd bench`, `dd`, `fio` | Медиа, бэкапы |
| **Latency (avg/p99/p999)** | `fio`, `rados bench` | Latency-sensitive |
| **Network throughput** | `iperf3` | Проверка сети |
| **OSD performance** | `ceph osd bench` | Диагностика OSD |

### Подготовка к тестированию

**Обязательные условия:**
- Кластер в состоянии `HEALTH_OK`
- Нет активного recovery/backfill
- Нет scrubbing (отключите: `ceph osd set noscrub`)
- Нет других нагрузок на кластер
- NTP синхронизирован

```bash
# Подготовка
ceph osd set noscrub
ceph osd set nodeep-scrub
ceph -w  # → убедитесь, что нет active recovery

# После тестов ОБЯЗАТЕЛЬНО снять флаги!
ceph osd unset noscrub
ceph osd unset nodeep-scrub
```

---

## Практические сценарии

### 1. rbd bench — быстрый бенчмарк RBD

```bash
# Sequential read (128K блоки, 4 потока, 60 сек)
rbd bench --io-type read --io-size 128K --io-threads 4 \
  --io-total 1G --io-pattern seq kube/test-image

# Sequential write
rbd bench --io-type write --io-size 128K --io-threads 4 \
  --io-total 1G --io-pattern seq kube/test-image

# Random read (4K блоки — типичный для СУБД)
rbd bench --io-type read --io-size 4K --io-threads 8 \
  --io-total 1G --io-pattern rand kube/test-image

# Random write
rbd bench --io-type write --io-size 4K --io-threads 8 \
  --io-total 1G --io-pattern rand kube/test-image
```

**Интерпретация результатов:**

| Метрика | Хорошо | Плохо |
|---------|--------|-------|
| Sequential read | > 500 МБ/с | < 100 МБ/с |
| Sequential write | > 200 МБ/с | < 50 МБ/с |
| Random read IOPS | > 10K | < 1K |
| Random write IOPS | > 5K | < 500 |
| Latency (avg) | < 5 мс | > 20 мс |

### 2. fio — детальный бенчмарк

#### 2.1 Установка fio

```bash
# Ubuntu/Debian
apt-get install -y fio

# RHEL/Rocky
dnf install -y fio
```

#### 2.2 Конфигурационные файлы fio

**Random read (OLTP-стиль):**

```ini
# fio-randread.ini
[global]
ioengine=libaio
direct=1
bs=4k
size=10G
runtime=300
time_based
group_reporting
filename=/dev/rbd0

[randread]
iodepth=32
rw=randread
numjobs=4
```

**Random write:**

```ini
# fio-randwrite.ini
[global]
ioengine=libaio
direct=1
bs=4k
size=10G
runtime=300
time_based
group_reporting
filename=/dev/rbd0

[randwrite]
iodepth=32
rw=randwrite
numjobs=4
```

**Sequential throughput:**

```ini
# fio-seqread.ini
[global]
ioengine=libaio
direct=1
bs=128k
size=10G
runtime=300
time_based
group_reporting
filename=/dev/rbd0

[seqread]
iodepth=16
rw=read
numjobs=4
```

**Mixed workload (70/30 read/write):**

```ini
# fio-mixed.ini
[global]
ioengine=libaio
direct=1
bs=8k
size=10G
runtime=300
time_based
group_reporting
filename=/dev/rbd0

[mixed]
iodepth=32
rw=randrw
rwmixread=70
numjobs=4
```

#### 2.3 Запуск тестов

```bash
# Запуск и вывод в JSON для анализа
fio fio-randread.ini --output-format=json --output=fio-results.json

# Запуск с терминальным выводом
fio fio-randread.ini

# Запуск всех тестов последовательно
for test in fio-randread.ini fio-randwrite.ini fio-seqread.ini fio-mixed.ini; do
  echo "=== Running $test ==="
  fio "$test" --output="results-${test%.ini}.json" --output-format=json
done
```

#### 2.4 Анализ результатов

```bash
# Извлечение ключевых метрик из JSON
python3 -c "
import json, sys
with open('fio-results.json') as f:
    data = json.load(f)
for job in data['jobs']:
    name = job['jobname']
    read_iops = job.get('read', {}).get('iops', 0)
    write_iops = job.get('write', {}).get('iops', 0)
    read_lat = job.get('read', {}).get('lat_ns', {}).get('mean', 0) / 1e6
    write_lat = job.get('write', {}).get('lat_ns', {}).get('mean', 0) / 1e6
    print(f'{name}: read_iops={read_iops:.0f} write_iops={write_iops:.0f} read_lat={read_lat:.2f}ms write_lat={write_lat:.2f}ms')
"
```

### 3. rados bench — бенчмарк RADOS (нижний уровень)

```bash
# Sequential write (128K, 4 потока, 60 сек)
rados bench -p rbd 60 write -t 4 -b 128K

# Sequential read
rados bench -p rbd 60 seq -t 4

# Random read
rados bench -p rbd 60 rand -t 4

# Clean up test data
rados -p rbd cleanup
```

**Интерпретация:**

| Метрика | Назначение |
|---------|-----------|
| `Total bandwidth` | Максимальная пропускная способность |
| `Avg latency` | Средняя задержка |
| `Max latency` | Максимальная задержка (хвост распределения) |
| `95th percentile latency` | Latency для 95% операций |

### 4. ceph osd bench — бенчмарк одного OSD

```bash
# Тест одного OSD (sequential write, 4K)
ceph osd bench --profile-type seq --osd-id 0 --bdev-id 0 \
  --block-size 4096 --count 10000

# Проверка IOPS каждого OSD
ceph osd perf
# → osd  commit  apply
# → 0    1.23    2.34   (мс)
# → 1    0.89    1.56
```

### 5. iperf3 — тестирование сети

```bash
# На сервере (OSD-хост):
iperf3 -s

# На клиенте (другой OSD-хост):
iperf3 -c 10.0.1.11 -P 8 -t 30
# → Bandwidth: XX Gbits/sec

# Тест с разными размерами пакетов
iperf3 -c 10.0.1.11 -l 128K -P 4 -t 30
iperf3 -c 10.0.1.11 -l 1M -P 4 -t 30
```

### 6. cosbench — распределённый бенчмарк

```bash
# Установка cosbench
wget https://github.com/intel-cloud/cosbench/releases/download/v0.8.2/cosbench-0.8.2.zip
unzip cosbench-0.8.2.zip
cd cosbench-0.8.2

# Запуск controller
./start-controller.sh

# Запуск workers на OSD-хостах
./start-worker.sh <controller-ip>

# Пример конфигурации теста (XML)
cat > cosbench-test.xml <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<workload name="s3-test" rampup="30" runtime="300" rampdown="30">
  <storage type="s3" config="endpoint=http://rgw:7480;accesskey=...;secretkey=..." />
  <workflow>
    <works>
      <work name="put" type="put" ratio="50" config="containers=c(1,16,2);objects=c(1000,10);sizes=c(4,1,KB)" />
      <work name="get" type="get" ratio="50" config="containers=c(1,16,2);objects=c(1000,10);sizes=c(4,1,KB)" />
    </works>
  </workflow>
</workload>
EOF

# Запуск теста
./cosbench.sh cosbench-test.xml
```

---

## Анализ результатов и Capacity Planning

### Формулы расчёта

```
Нужное количество OSD = (Целевой IOPS) / (IOPS на 1 OSD)
Нужный сетевой канал = (Целевой throughput × replication_factor) / скорость_сети
Нужный объём RAM = (количество PG × 1 МБ) + (количество OSD × 1 ГБ)
```

### Пример расчёта

```
Требование: 50K random read IOPS, latency < 5ms

1 OSD (NVMe): ~5000 IOPS (randread, 4K)
Нужно OSD: 50000 / 5000 = 10 OSD (для данных)
+ 2 OSD запас = 12 OSD минимум

Сеть: 50K IOPS × 4K = 200 МБ/с × 3 (replication) = 600 МБ/с
Нужная сеть: 600 МБ/с → 10 Гбит/с достаточно
```

### Типичные значения

| Тип OSD | Random Read IOPS | Random Write IOPS | Sequential Throughput |
|---------|-----------------|-------------------|----------------------|
| HDD 7200 | 100-200 | 100-150 | 150-200 МБ/с |
| SATA SSD | 5K-10K | 3K-8K | 500-600 МБ/с |
| NVMe SSD | 20K-100K | 15K-50K | 2-7 ГБ/с |
| Intel Optane | 100K-500K | 50K-200K | 2-3 ГБ/с |

---

## Диагностика производительности

| Проблема | Вероятная причина | Диагностика | Решение |
|----------|-------------------|-------------|---------|
| Низкий IOPS | Мало OSD, медленные диски | `ceph osd perf`, `iostat -x` | Добавить NVMe OSD |
| Высокая latency | Сеть, scrubbing, recovery | `ceph osd perf`, `ceph -w` | Проверить сеть, отключить scrub |
| Throughput ниже ожидаемого | MTU mismatch, сеть | `iperf3`, `ethtool -S` | Проверить MTU, bond |
| Неравномерная нагрузка | Плохой баланс PG | `ceph osd df tree` | `ceph balancer execute` |
| Read latency растёт со временем | Кэш переполнен | `ceph daemon osd.0 dump_mempool` | Увеличить кэш, проверить RAM |

---

## Лучшие практики

- **Тестируйте в окне обслуживания** — бенчмарки нагружают кластер
- **Отключайте scrubbing** перед тестами (`ceph osd set noscrub`)
- **Используйте `direct=1` в fio** — для исключения влияния кэша ОС
- **Тестируйте разные blockSize** — 4K (IOPS), 128K (throughput)
- **Тестируйте разные depths** — iodepth=1 (latency), 32+ (throughput)
- **Сравнивайте с baseline** — фиксируйте результаты после каждого изменения
- **Тестируйте сеть отдельно** — `iperf3` между OSD-хостами
- **Документируйте результаты** — для сравнения при апгрейде или расширении

### См. также

- [Обзор Ceph](./ceph_overview.md) — архитектура компонентов
- [Расчет PG](./ceph_placement_groups.md) — влияние PG на производительность
- [Сетевая архитектура](./ceph_networking.md) — настройка сети
- [Мониторинг Ceph](./Administration/monitoring.md) — метрики производительности
