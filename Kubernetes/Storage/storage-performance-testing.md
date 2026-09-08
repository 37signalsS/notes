# Тестирование производительности хранилища в Kubernetes

## Определения

**Storage Performance Testing** — процесс измерения ключевых характеристик хранилища (IOPS, latency, throughput) в контейнеризированной среде для валидации соответствия SLA и выбора оптимального StorageClass.

**IOPS (Input/Output Operations Per Second)** — количество операций ввода-вывода в секунду. Зависит от размера блока: 4K random write даёт максимальные IOPS, 1M sequential read — максимальную throughput.

**Latency (Задержка)** — время от отправки I/O-запроса до получения ответа. Для OLTP-нагрузок критична p99 latency (< 10ms для NVMe).

**Throughput (Пропускная способность)** — объём данных в секунду (MB/s или GB/s). Определяется размером блока и пропускной способностью диска/сети.

**fio (Flexible I/O Tester)** — стандартный инструмент для тестирования производительности блочных устройств и файловых систем. Поддерживает синтетические и реалистичные паттерны нагрузки.

**Связанные темы:**
- [StorageClass](./storageclass.md) — параметры хранилища.
- [Storage Decision Matrix](./storage-decision-matrix.md) — выбор хранилища.
- [Ceph — бенчмарки](./Ceph/ceph_benchmarks.md) — бенчмарки Ceph.
- [etcd — бенчмаркинг](../../etcd/benchmarking.md) — fio для etcd.

---

## Теоретический блок

### Ключевые метрики и пороги

| Метрика | NVMe SSD | SATA SSD | HDD | NFS (10GbE) |
|:---|:---|:---|:---|:---|
| **Random 4K read IOPS** | 500K–3M | 50K–100K | 100–200 | 5K–20K |
| **Random 4K write IOPS** | 200K–1M | 30K–80K | 100–200 | 5K–15K |
| **Sequential 1M read (MB/s)** | 3000–7000 | 500–550 | 150–250 | 800–1200 |
| **Sequential 1M write (MB/s)** | 2000–5000 | 400–500 | 150–250 | 600–1000 |
| **p99 latency (random 4K)** | < 0.1 ms | 0.1–0.5 ms | 3–10 ms | 1–5 ms |

### Паттерны нагрузки

| Паттерн | Описание | Когда использовать |
|:---|:---|:---|
| **Random 4K read** | Случайное чтение мелкими блоками | OLTP (PostgreSQL, MySQL) |
| **Random 4K write** | Случайная запись мелкими блоками | WAL-файлы, транзакции |
| **Sequential 1M read** | Последовательное чтение крупными блоками | Логи, архивы, аналитика |
| **Sequential 1M write** | Последовательная запись крупными блоками | Бэкапы, стриминг |
| **Mixed (70/30)** | 70% чтение, 30% запись | Реалистичная нагрузка приложений |
| **Write-only (fsync)** | Запись с принудительным fsync | БД, требующие durability |

---

## Практический блок

### 1. Запуск fio в Kubernetes

#### 1.1 Базовый тест (Pod)

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: fio-test
  namespace: default
spec:
  containers:
  - name: fio
    image: linuxtools/fio:latest
    command: ["fio"]
    args:
    - "--name=randread"
    - "--ioengine=libaio"
    - "--direct=1"
    - "--rw=randread"
    - "--bs=4k"
    - "--size=1G"
    - "--numjobs=1"
    - "--iodepth=32"
    - "--runtime=60"
    - "--time_based"
    - "--group_reporting"
    - "--directory=/data"
    volumeMounts:
    - name: test-volume
      mountPath: /data
  volumes:
  - name: test-volume
    persistentVolumeClaim:
      claimName: fio-test-pvc
  restartPolicy: Never
```

#### 1.2 Полный набор тестов (Job)

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: fio-benchmark
spec:
  template:
    spec:
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
      restartPolicy: Never
```

#### 1.3 One-liner для быстрого теста

```bash
# Создать PVC и запустить fio
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

### 2. Интерпретация результатов

#### Ключевые поля вывода fio

```
read:   IOPS=50.0k, BW=195MiB/s (205MB/s)
        slat (usec): min=1, max=500, avg=10.00, stdev=5.00
        clat (usec): min=10, max=5000, avg=600.00, stdev=200.00
         lat (usec): min=12, max=5200, avg=610.00, stdev=205.00
        clat percentiles (usec):
         |  1.00th=[  100],  5.00th=[  150], 50.00th=[  500],
         | 95.00th=[ 1000], 99.00th=[ 2000], 99.99th=[ 4000]
```

| Поле | Описание | Целевое значение |
|:---|:---|:---|
| **IOPS** | Операций в секунду | Для OLTP > 10K (4K random) |
| **BW (Bandwidth)** | Пропускная способность | Для sequential > 500 MB/s |
| **slat** | Submission latency (время в очереди) | < 100 usec |
| **clat** | Completion latency (время завершения) | < 1ms для NVMe, < 10ms для SSD |
| **lat** | Total latency (общая задержка) | p99 < 10ms для OLTP |
| **p99** | 99-й процентиль задержки | Ключевая метрика для SLA |

### 3. Тестирование разных StorageClass

Сравнительный тест для принятия решения:

```bash
#!/bin/bash
# Скрипт сравнения StorageClass

SC_LIST=("fast-ssd" "standard-hdd" "longhorn" "ceph-rbd")
PVC_SIZE="5Gi"

for SC in "${SC_LIST[@]}"; do
  echo "=== Тест StorageClass: $SC ==="

  # Создать PVC
  cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: fio-${SC}
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: ${SC}
  resources:
    requests:
      storage: ${PVC_SIZE}
EOF

  # Ждать Bound
  kubectl wait --for=jsonpath='{.status.phase}'=Bound pvc/fio-${SC} --timeout=120s

  # Запустить fio
  kubectl run fio-${SC} --rm -it --image=linuxtools/fio --overrides="{...}" -- \
    fio --name=test --directory=/data --rw=randread --bs=4k \
    --size=1G --numjobs=1 --iodepth=32 --runtime=30 --time_based

  # Удалить PVC
  kubectl delete pvc fio-${SC}
done
```

### 4. Мониторинг производительности в реальном времени

```bash
# Метрики kubelet по томам (в Prometheus)
# kubelet_volume_stats_used_bytes
# kubelet_volume_stats_capacity_bytes

# На узле: мониторинг диска
iostat -x 1 5
# %util → 100% = диск перегружен
# await → средняя задержка I/O
# r_await / w_await → задержки чтения/записи

# Для NFS: мониторинг клиента
nfsiostat 1
```

### 5. Частые ошибки тестирования

| Ошибка | Проблема | Решение |
|:---|:---|:---|
| Тест на пустом диске | Результаты завышены (кэш) | Заполнить диск на 50% перед тестом |
| Тест без `direct=1` | Данные идут через page cache | Всегда использовать `--direct=1` |
| Слишком короткий runtime | Статистика не стабилизируется | Минимум 60 секунд |
| Маленький size | Не покрывает весь диск | size >= 2x RAM для исключения кэша |
| Один поток | Не раскрывает параллелизм диска | Использовать numjobs >= 4 для SSD |
| Тест через NFS (FUSE) | Замеряется производительность FUSE, а не диска | Тестировать на блочном уровне |

---

## Дополнительная информация

### Рекомендации по IOPS для приложений

| Приложение | Минимальные IOPS (4K random) | Минимальная latency (p99) |
|:---|:---|:---|
| PostgreSQL OLTP | 10,000+ | < 5 ms |
| MySQL OLTP | 10,000+ | < 5 ms |
| MongoDB | 5,000+ | < 10 ms |
| Redis (per shard) | 50,000+ | < 1 ms |
| Elasticsearch (per data node) | 5,000+ | < 10 ms |
| Kafka (per broker) | 5,000+ | < 10 ms |
| Prometheus (local) | 1,000+ | < 50 ms |

### См. также

- [Ceph — бенчмарки](./Ceph/ceph_benchmarks.md) — бенчмарки Ceph-кластера.
- [etcd — бенчмаркинг](../../etcd/benchmarking.md) — fio для etcd.
- [Storage Capacity Planning](./storage-capacity-planning.md) — расчёт объёмов.
- [Storage Decision Matrix](./storage-decision-matrix.md) — выбор хранилища.
