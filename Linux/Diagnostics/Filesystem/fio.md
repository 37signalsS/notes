# fio (Flexible I/O Tester)

## Определения

- **fio (Flexible I/O Tester):** Отраслевой стандарт для бенчмаркинга и стресс-тестирования подсистем ввода-вывода. Позволяет эмулировать практически любой тип нагрузки (от простых последовательных операций до сложных смешанных паттернов СУБД) и измерять производительность с высокой точностью.
- **BW (Bandwidth):** Пропускная способность или полоса пропускания. Измеряется в МБ/с или ГБ/с. Показывает объем данных, передаваемый в единицу времени.
- **IOPS (Input/Output Operations Per Second):** Количество операций ввода-вывода в секунду. Критический показатель для транзакционных нагрузок (БД, почтовые серверы).
- **Latency (Задержка):** Время выполнения операции. В `fio` разделяется на:
    - `slat` (submission latency): время от создания запроса до его отправки в ядро.
    - `clat` (completion latency): время от отправки в ядро до подтверждения завершения. Основной показатель задержки диска.
    - `lat` (total latency): общее время выполнения операции.
- **Движок ввода-вывода (ioengine):** Метод, через который `fio` взаимодействует с ОС (например, `sync`, `libaio`, `io_uring`, `rbd`).
- **Глубина очереди (iodepth):** Количество запросов, отправленных "в полет" одновременно, не дожидаясь завершения предыдущих.
- **fdatasync:** Системный вызов, который сбрасывает на диск только данные файла (без метаданных). В `fio` активируется параметром `fdatasync=1`. Критичен для WAL и журналирования.
- **fsync:** Системный вызов, который сбрасывает на диск и данные, и метаданные файла. В `fio` активируется параметром `fsync=1`. Более агрессивный, чем `fdatasync`, используется для тестирования с полным гарантированным сбросом.
- **Планировщик I/O:** Подсистема ядра, управляющая порядком и приоритетом обработки блочных запросов. Для NVMe рекомендуется `none`, для SATA SSD — `mq-deadline` или `kyber`, для HDD — `bfq`.
- **io_uring:** Современный интерфейс асинхронного ввода-вывода в Linux (ядро 5.1+), минимизирующий переключения контекста и накладные расходы. В `fio` используется через `ioengine=io_uring`.
- **hipri:** Режим Polling (опрос) в `io_uring`, исключающий прерывания для снижения задержки. В `fio` активируется параметром `hipri=1`. Повышает стабильность латентности, но нагружает CPU.
- **SQPOLL (Submission Queue Poll):** Режим `io_uring`, при котором поток опроса очереди submission работает в userspace, снижая количество системных вызовов. В `fio` настраивается через `sqthread_poll` и `sq_thread_idle`.
- **stonewall:** Директива в job-файле, гарантирующая, что следующая секция начнется только после полного завершения предыдущей. Используется для последовательного выполнения тестов с очисткой состояния.
- **cgroups v2 I/O controller:** Механизм ядра для ограничения и приоритизации дисковых операций процессов через `io.weight`, `io.max`, `io.latency`.

## Основные концепции

`fio` позволяет гибко настраивать параметры нагрузки для имитации работы реальных приложений:

| Сценарий | Паттерн | Размер блока (bs) | Пример применения |
| :--- | :--- | :--- | :--- |
| **OLTP СУБД** | `randrw` (70/30) | 4K–16K | PostgreSQL, MySQL, Oracle |
| **Big Data / OLAP** | `read` (seq) | 128K–1M | ClickHouse, Hadoop, Spark |
| **Файловый сервер** | `rw` (mixed) | 64K–1M | SMB/CIFS, NFS |
| **Виртуализация** | `randrw` | 8K–64K | KVM/QEMU, VMWare |
| **Журналирование** | `write` (seq) | 4K–64K | WAL, Syslog, Kafka |
| **Объектное хранилище**| `read` / `write` | 1M+ | S3, Swift, MinIO |
| **Ceph RBD** | `randread` / `randwrite` | 4K–128K | RBD-томы в Kubernetes/OpenStack |
| **iSCSI / NVMe-oF** | `randrw` / `seq` | 4K–128K | Сетевые блочные устройства |
| **Прокси-кеши (PWL)** | `randwrite` | 4K | Ceph Persistent Write Log Cache |

### Механизмы ввода-вывода (ioengine)

Выбор движка критически влияет на результаты, особенно на быстрых NVMe-накопителях:

1.  **`sync` / `psync`:** Базовые синхронные вызовы (`read`/`write`). Поток блокируется до завершения операции. Не подходит для тестирования высокой глубины очереди. Используется для `fdatasync` и `fsync` тестов.
2.  **`libaio`:** Асинхронный I/O в Linux. Традиционный стандарт для тестирования SSD. Требует `direct=1`. Поддерживает `O_DIRECT` и дает стабильные результаты на большинстве железа.
3.  **`io_uring`:** Самый современный интерфейс (ядро 5.1+). Минимизирует переключения контекста и накладные расходы.
    - `hipri=1`: включает режим Polling (опрос), исключая прерывания. Снижает задержку, но нагружает CPU.
    - `sqthread_poll=1`: включает SQPOLL, перенося опрос очереди в userspace.
    - `sq_thread_idle`: время бездействия SQPOLL-потока в микросекундах (дефолт 125000).
4.  **`rbd`:** Прямое тестирование хранилищ Ceph через `librbd`, минуя уровень ядра и ФС. Использует параметры `--pool=`, `--rbdname=`.
5.  **`rados`:** Низкоуровневое тестирование RADOS-пулов (объектное хранилище, минуя RBD).
6.  **`rbd` + `krbd`/`rbd-nbd`:** Для тестирования через модуль ядра используйте `ioengine=libaio` с устройством `/dev/rbd0` (krbd) или `/dev/nbd0` (rbd-nbd).

### Глубина очереди и потоки

- **`iodepth`:** Используется только с асинхронными движками (`libaio`, `io_uring`). Позволяет нагрузить контроллер SSD/NVMe для достижения пиковых IOPS. Для NVMe Gen4/Gen5 рекомендуется 64–256.
- **`numjobs`:** Количество параллельных процессов или потоков. Каждый поток работает со своей копией `iodepth`.
    - Общее количество запросов в работе = `iodepth` * `numjobs`.
- **`cpus_allowed`:** Привязка (pinning) потоков `fio` к конкретным ядрам CPU. Предотвращает переключение контекста и повышает стабильность результатов.
- **`fsync` / `fdatasync`:** Параметры сброса данных на диск. `fsync=1` сбрасывает данные + метаданные, `fdatasync=1` — только данные. Используются для тестирования durability-сценариев (WAL, БД).

## Практические сценарии

### Установка

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y fio

# RHEL / CentOS / Rocky Linux
sudo dnf install -y fio

# Alpine (для контейнеров)
apk add --no-cache fio
```

### Базовые замеры производительности

**Важно:** Тестирование сырого устройства (`/dev/sdX`) точнее, но **уничтожает все данные на нем**.

```bash
# 1. Линейная запись (максимальная пропускная способность)
fio --name=seq_write --rw=write --bs=1M --size=10G --filename=/dev/sdb \
    --ioengine=io_uring --direct=1 --group_reporting
# → Результат: BW=4500MiB/s (4718MB/s)

# 2. Случайное чтение 4K (максимальный IOPS)
fio --name=rand_read --rw=randread --bs=4k --size=4G --filename=./testfile \
    --ioengine=io_uring --direct=1 --iodepth=64 --numjobs=4 --runtime=60 --time_based
# → Результат: IOPS=850k
```

### Проверка целостности данных (Integrity Check)

Используется для выявления проблем с памятью или контроллером диска.

```bash
fio --name=integrity_test --rw=randrw --bs=4k --size=1G --filename=./testfile \
    --verify=md5 --do_verify=1 --ioengine=libaio --direct=1
```

### Тестирование для etcd (fdatasync / fsync latency)

Для `etcd` критична скорость сброса данных на диск. p99 задержки должен быть менее 10 мс (оптимально < 2 мс).

```bash
# Тест с fdatasync (только данные, без метаданных — соответствует WAL)
fio --rw=write --ioengine=sync --fdatasync=1 --directory=./etcd-data \
    --size=22m --bs=2300 --name=etcd-sync-test
# → Ищите результат "clat" (completion latency) в микросекундах.

# Более агрессивный тест с fsync (данные + метаданные)
fio --name=etcd-fsync-test --rw=write --ioengine=sync --fsync=1 \
    --size=1G --bs=4k --numjobs=4 --time_based --runtime=60
```

**Критические пороги для NVMe:**
- `lat_avg` < 1 мс.
- `lat_p99` < 5 мс.
- IOPS > 50 000 (4K random write с `fsync=1`).

### Бенчмаркинг SSD: Burst vs Steady State

SSD показывают завышенные результаты на пустом SLC-кэше. Для корректных измерений необходимо тестировать burst (первый прогон) и steady state (после истощения кэша).

```bash
# Шаг 1: Burst sequential write (первый прогон, SLC-кэш полон)
fio --name=burst_seq_write \
    --rw=write --bs=1M --size=10G --filename=/tmp/testfile \
    --ioengine=libaio --direct=1 --iodepth=32 --numjobs=1 \
    --group_reporting --time_based --runtime=30

# Шаг 2: Предварительное заполнение диска 2 раза для истощения SLC-кэша
dd if=/dev/zero of=/tmp/testfile bs=1M count=0 oflag=direct conv=fdatasync 2>/dev/null || true

# Шаг 3: Steady state sequential write (стабильная производительность)
fio --name=steady_seq_write \
    --rw=write --bs=1M --size=10G --filename=/tmp/testfile \
    --ioengine=libaio --direct=1 --iodepth=32 --numjobs=1 \
    --group_reporting --time_based --runtime=60

# Шаг 4: Случайная запись 4K с fsync=1 (имитация БД с durability)
fio --name=randwrite_4k \
    --rw=randwrite --bs=4k --size=4G --filename=/tmp/testfile \
    --ioengine=io_uring --direct=1 --iodepth=64 --numjobs=4 \
    --group_reporting --time_based --runtime=30 \
    --fsync=1
```

**Интерпретация:**
- Разница между `burst_seq_write` и `steady_seq_write` показывает размер SLC-кэша и точку перехода в steady state.
- `randwrite_4k` с `fsync=1` на consumer SSD покажет падение IOPS в 5–10 раз по сравнению с enterprise SSD с PLP (Power Loss Protection).

### Сценарии для RAID и ZFS

1.  **RAID:** Для тестирования эффективности страйпинга используйте `numjobs`, равный количеству дисков в массиве.
2.  **ZFS:** Всегда используйте `direct=0` (ZFS не поддерживает стандартный O_DIRECT так, как Ext4/XFS) и задавайте размер блока (`bs`), соответствующий `recordsize` пула.

```bash
# Тест ZFS с учетом recordsize=128k
fio --name=zfs_test --rw=randrw --bs=128k --size=10G --filename=/zfs_pool/testfile \
    --ioengine=libaio --direct=0 --runtime=60
```

### Тестирование Ceph RBD (ioengine=rbd)

Для тестирования Ceph-хранилищ используйте `ioengine=rbd` для прямого доступа через `librbd`, минуя уровень ядра и ФС:

```bash
# Случайное чтение 4K через RBD (OLTP-нагрузка)
fio --name=randread-rbd --ioengine=rbd --pool=kube --rbdname=my-image \
    --rw=randread --bs=4k --size=4G --iodepth=64 --numjobs=4 \
    --runtime=120 --time_based --group_reporting

# Последовательная запись 1M через RBD (потоковая нагрузка)
fio --name=seqwrite-rbd --ioengine=rbd --pool=kube --rbdname=my-image \
    --rw=write --bs=1m --size=10G --iodepth=16 --numjobs=1 \
    --runtime=120 --time_based --group_reporting

# Смешанная нагрузка 70/30 (типичный паттерн СУБД)
fio --name=mixed-rbd --ioengine=rbd --pool=kube --rbdname=my-image \
    --rw=randrw --rwmixread=70 --bs=8k --size=4G --iodepth=32 --numjobs=4 \
    --runtime=120 --time_based --group_reporting
```

**Сравнение krbd vs rbd-nbd:**

```bash
# Тест через krbd (модуль ядра)
sudo rbd map kube/perf-test
fio --name=krbd-test --filename=/dev/rbd0 --ioengine=libaio --direct=1 \
    --rw=randread --bs=4k --iodepth=64 --size=4G --runtime=60
sudo rbd unmap kube/perf-test

# Тест через rbd-nbd
sudo rbd device map -t nbd kube/perf-test
fio --name=nbd-test --filename=/dev/nbd0 --ioengine=libaio --direct=1 \
    --rw=randread --bs=4k --iodepth=64 --size=4G --runtime=60
sudo rbd device unmap -t nbd kube/perf-test
```

### Тестирование iSCSI-хранилищ

```bash
# Sequential Read (throughput)
fio --name=seqread --ioengine=libaio --direct=1 --bs=128k --iodepth=32 \
    --rw=read --size=10G --runtime=60 --filename=/mnt/iscsi/testfile

# Random Read (IOPS + Latency)
fio --name=randread --ioengine=libaio --direct=1 --bs=4k --iodepth=64 \
    --rw=randread --size=10G --runtime=60 --filename=/mnt/iscsi/testfile

# Mixed Random R/W (70% read / 30% write)
fio --name=mixed --ioengine=libaio --direct=1 --bs=4k --iodepth=64 \
    --rw=randrw --rwmixread=70 --size=10G --runtime=60 \
    --filename=/mnt/iscsi/testfile
```

### Тестирование образов виртуальных машин (qcow2)

```bash
# Типичный workload ВМ: смешанный чтение/запись 4K, 16 очередей
fio --name=vm-workload \
  --rw=randrw \
  --bs=4k \
  --iodepth=16 \
  --size=1G \
  --filename=/var/lib/libvirt/images/test.qcow2 \
  --output-format=json \
  --runtime=60 \
  --time_based

# Оценка latency (p99, p999)
fio --name=latency-test \
  --rw=randread \
  --bs=4k \
  --iodepth=1 \
  --size=1G \
  --filename=/var/lib/libvirt/images/test.qcow2 \
  --output-format=json | \
  jq '.jobs[0].latency'

# Сравнение cache modes
fio --name=cache-none --rw=randrw --bs=4k --iodepth=16 \
  --filename=/var/lib/libvirt/images/test-cache-none.qcow2
```

### Тестирование в контейнере Docker

```bash
# Запуск fio внутри Alpine-контейнера
docker run --rm -v /tmp/fio-test:/data alpine sh -c "
  apk add --no-cache fio && \
  fio --name=seq-read --directory=/data --rw=read --bs=1M --size=512M \
      --numjobs=1 --runtime=30 --group_reporting
"

# Random write (БД workload) через docker run
docker run --rm -v /tmp/fio-test:/data alpine sh -c "
  apk add --no-cache fio && \
  fio --name=rand-write --directory=/data --rw=randwrite --bs=4k --size=256M \
      --numjobs=4 --runtime=60 --group_reporting --fsync=1
"

# Сравнение XFS noatime
fio --name=xfs-noatime --directory=/var/lib/docker/test \
    --rw=randwrite --bs=4k --size=100M --numjobs=4 --runtime=30
```

### Тестирование в Kubernetes (Job / Pod)

```yaml
# fio-test-pod.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: fio-test
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: fio
        image: linuxtools/fio:latest
        command: ["/bin/sh", "-c"]
        args:
        - |
          echo "=== Random 4K Read (IOPS) ===" &&
          fio --name=randread --ioengine=libaio --direct=1 --rw=randread \
              --bs=4k --size=1G --numjobs=1 --iodepth=32 --runtime=60 \
              --time_based --group_reporting --directory=/data --output-format=json &&
          echo "=== Random 4K Write (IOPS) ===" &&
          fio --name=randwrite --ioengine=libaio --direct=1 --rw=randwrite \
              --bs=4k --size=1G --numjobs=1 --iodepth=16 --runtime=60 \
              --time_based --group_reporting --directory=/data --output-format=json &&
          echo "=== Sequential 1M Read (Throughput) ===" &&
          fio --name=seqread --ioengine=libaio --direct=1 --rw=read \
              --bs=1m --size=4G --numjobs=1 --iodepth=1 --runtime=30 \
              --time_based --group_reporting --directory=/data --output-format=json &&
          echo "=== Random 4K Mixed (70/30) ===" &&
          fio --name=mixed --ioengine=libaio --direct=1 --rw=randrw \
              --rwmixread=70 --bs=4k --size=1G --numjobs=1 --iodepth=16 \
              --runtime=60 --time_based --group_reporting --directory=/data \
              --output-format=json
        volumeMounts:
        - name: test-volume
          mountPath: /data
      volumes:
      - name: test-volume
        persistentVolumeClaim:
          claimName: fio-test-pvc
```

```bash
# One-liner для быстрого теста
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: fio-test-pvc
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: fast-ssd
  resources:
    requests:
      storage: 5Gi
EOF

kubectl run fio --rm -it --image=linuxtools/fio --overrides='{"spec":{"containers":[{"name":"fio","image":"linuxtools/fio","command":["fio","--name=test","--ioengine=libaio","--direct=1","--rw=randread","--bs=4k","--size=256M","--numjobs=1","--iodepth=32","--runtime=30","--time_based","--directory=/data"],"volumeMounts":[{"name":"vol","mountPath":"/data"}]}],"volumes":[{"name":"vol","persistentVolumeClaim":{"claimName":"fio-test-pvc"}}]}}'
```

### Использование файлов конфигурации (Job-files)

Файлы конфигурации позволяют описывать сложные многошаговые тесты.

```ini
[global]
ioengine=io_uring
direct=1
group_reporting
runtime=60
time_based

[db_reads]
filename=/dev/nvme1n1
rw=randread
bs=8k
iodepth=64

[db_writes]
filename=/dev/nvme1n1
rw=randwrite
bs=8k
iodepth=32
# stonewall гарантирует, что эта секция начнется только после завершения предыдущей
stonewall
```

## Анализ результатов

### Пример вывода (Summary)

```text
read: IOPS=150k, BW=586MiB/s (614MB/s)(34.3GiB/60001ms)
  slat (nsec): min=901, max=158810, avg=1120.41, stdev=340.21
  clat (usec): min=4, max=1502, avg=420.12, stdev=80.45
  lat (usec): min=5, max=1504, avg=421.24, stdev=80.46
  clat percentiles (usec):
    |  1.00th=[  310],  5.00th=[  340], 10.00th=[  360], 20.00th=[  380],
    | 50.00th=[  410], 90.00th=[  450], 95.00th=[  480], 99.00th=[  550],
    | 99.90th=[ 1200], 99.99th=[ 1450]
```

**На что смотреть:**
- **IOPS/BW:** соответствие заявленным характеристикам железа.
- **clat percentiles:** стабильность задержки. Если `99.90th` сильно отличается от `50.00th`, у системы есть проблемы с "хвостами" задержек (jitter).
- **slat:** если `slat` значительно выше `clat`, проблема в планировщике или переключении контекста.

### Интерпретация результатов в Kubernetes

| Поле | Описание | Целевое значение |
|:---|:---|:---|
| **IOPS** | Операций в секунду | Для OLTP > 10K (4K random) |
| **BW (Bandwidth)** | Пропускная способность | Для sequential > 500 MB/s |
| **slat** | Submission latency (время в очереди) | < 100 usec |
| **clat** | Completion latency (время завершения) | < 1ms для NVMe, < 10ms для SSD |
| **lat** | Total latency (общая задержка) | p99 < 10ms для OLTP |
| **p99** | 99-й процентиль задержки | Ключевая метрика для SLA |

### Вывод в JSON и парсинг

Для автоматизации используйте `--output-format=json`.

```bash
fio job.fio --output-format=json > results.json

# Извлечение IOPS чтения с помощью jq
cat results.json | jq '.jobs[0].read.iops'
```

**Автоматический анализ на Python:**

```python
import json, sys

with open('fio-results.json') as f:
    data = json.load(f)

for job in data['jobs']:
    name = job['jobname']
    read_iops = job.get('read', {}).get('iops', 0)
    write_iops = job.get('write', {}).get('iops', 0)
    read_lat = job.get('read', {}).get('lat_ns', {}).get('mean', 0) / 1e6
    write_lat = job.get('write', {}).get('lat_ns', {}).get('mean', 0) / 1e6
    print(f'{name}: read_iops={read_iops:.0f} write_iops={write_iops:.0f} '
          f'read_lat={read_lat:.2f}ms write_lat={write_lat:.2f}ms')
```

## Изоляция и приоритизация I/O (cgroups v2)

Для production-средств используйте cgroups v2 для контроля дисковых операций:

```bash
# Установка веса I/O для группы сервиса (относительный приоритет)
echo "100" | sudo tee /sys/fs/cgroup/system.slice/database.service/io.weight

# Жесткое ограничение скорости записи (MB/s)
echo "wbps=10485760" | sudo tee /sys/fs/cgroup/system.slice/backup.service/io.max

# Ограничение по задержке (микросекунды)
echo "rt=125000" | sudo tee /sys/fs/cgroup/system.slice/database.service/io.latency

# Просмотр статистики
cat /sys/fs/cgroup/system.slice/database.service/io.stat
```

## Типичные ошибки и диагностика

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Низкий IOPS на NVMe | Планировщик `mq-deadline`/`bfq` или включен `libaio` fallback | Переключите планировщик на `none`; убедитесь, что `io_uring` действительно используется (strace) |
| Высокое `slat` относительно `clat` | Проблема в планировщике, NUMA, или переключении контекста | Проверьте `cpus_allowed`, `numactl --hardware`, планировщик устройства |
| Тест на пустом диске | Результаты завышены (SLC-кэш) | Заполнить диск на 50% перед тестом или выполнить preconditioning |
| Тест без `direct=1` | Данные идут через page cache | Всегда использовать `--direct=1` (кроме ZFS и тестирования самой ФС) |
| Слишком короткий runtime | Статистика не стабилизируется | Минимум 60 секунд для NVMe, 300 секунд для Ceph |
| Маленький size | Не покрывает весь диск, данные удерживаются в кэше | size >= 2x RAM для исключения кэша, или >= 50% диска |
| Один поток | Не раскрывает параллелизм диска | Использовать `numjobs >= 4` для SSD, `iodepth >= 64` для NVMe |
| `EINVAL` при использовании `io_uring` | Ядро собрано без `CONFIG_IO_URING` или версия < 5.1 | Обновите ядро; проверьте `grep CONFIG_IO_URING /boot/config-$(uname -r)` |
| Нулевая или низкая производительность | Используется `sync` движок или `direct=0` | Переключитесь на `libaio` или `io_uring` с `direct=1` |
| Высокое потребление CPU при `hipri=1` | Режим Polling исключает прерывания | Нормально для latency-тестов; уменьшите `numjobs` или отключите `hipri` |
| Потеря пакетов в сетевом multishot | Буферы недостаточного размера или нет `IOSQE_BUFFER_SELECT` | Увеличьте размер буферного пула; проверьте флаги SQE |

## Дополнительная информация

### Рекомендации по чистоте эксперимента

1.  **Прогрев SSD (Preconditioning):** SSD показывают завышенные результаты на пустом SLC-кэше. Перед тестом запишите диск полностью 1–2 раза.
2.  **Исключение кэширования:** Всегда используйте `direct=1`, чтобы данные шли мимо Page Cache ОС (кроме случаев тестирования самой ФС или ZFS).
3.  **Температурный троттлинг:** NVMe-диски снижают скорость при перегреве. Мониторьте температуру через `smartctl` во время теста.
4.  **Размер файла:** Размер тестового файла (`--size`) должен превышать объем оперативной памяти сервера, чтобы исключить влияние RAM-кэша.
5.  **NUMA locality:** Привязывайте `fio` к ядрам NUMA-ноды, к которой относится тестируемый диск. Используйте `numactl --cpunodebind=X --membind=X fio ...`.
6.  **Планировщик I/O:** Для NVMe используйте `none`, для SATA SSD — `mq-deadline` или `kyber`. Проверка: `cat /sys/block/nvme0n1/queue/scheduler`.

### Типичные показатели производительности (2025–2026)

| Тип устройства | Seq Read (МБ/с) | Rand Read 4K (IOPS) | Latency p99 (мкс) |
| :--- | :--- | :--- | :--- |
| **HDD 7200 RPM** | 150–250 | 100–180 | 15,000–30,000 |
| **SATA SSD** | 540–560 | 70K–100K | 150–500 |
| **NVMe Gen3** | 3,500–5,000 | 500K–800K | 15–30 |
| **NVMe Gen4** | 7,000–7,500 | 800K–1.2M | 50–100 |
| **NVMe Gen5** | 10,000–14,500 | 1.5M–2M+ | 20–50 |

### Рекомендации по IOPS для приложений

| Приложение | Минимальные IOPS (4K random) | Минимальная latency (p99) |
| :--- | :--- | :--- |
| PostgreSQL OLTP | 10,000+ | < 5 ms |
| MySQL OLTP | 10,000+ | < 5 ms |
| MongoDB | 5,000+ | < 10 ms |
| Redis (per shard) | 50,000+ | < 1 ms |
| Elasticsearch (per data node) | 5,000+ | < 10 ms |
| Kafka (per broker) | 5,000+ | < 10 ms |
| Prometheus (local) | 1,000+ | < 50 ms |
| etcd (3-node cluster) | 50,000+ | < 5 ms |

### Мониторинг во время тестирования

```bash
# В отдельном терминале
iostat -x 1 5          # Дисковая подсистема (%util, await, aqu-sz)
mpstat -P ALL 1 5      # Распределение нагрузки по ядрам CPU
nstat -az 1            # TCP-статистика (retransmits) для iSCSI/NVMe-oF
sar -n DEV 1           # Сетевая активность

# Для NVMe
sudo nvme smart-log /dev/nvme0 | grep -E 'Temperature|Percentage Used'
```

### См. также

- [Официальная документация fio](https://fio.readthedocs.io/)
- [io_uring — современный асинхронный I/O](../../Core/kernel/io_uring.md)
- [Мониторинг дисковой статистики (iostat)](./iostat.md)
- [Тестирование производительности Ceph](../../Kubernetes/Storage/Ceph/ceph_benchmarks.md)
- [Бенчмаркинг etcd](../../etcd/benchmarking.md)
