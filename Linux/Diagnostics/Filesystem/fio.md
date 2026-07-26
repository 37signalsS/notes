# `fio` (Flexible I/O Tester)

## Определения

- **`fio` (Flexible I/O Tester):** Мощная кроссплатформенная утилита для бенчмаркинга и стресс-тестирования подсистем ввода-вывода. Позволяет эмулировать практически любой тип нагрузки и измерять производительность с высокой точностью.
- **BW (Bandwidth):** Пропускная способность или полоса пропускания (МБ/с, ГБ/с).
- **IOPS (Input/Output Operations Per Second):** Количество операций ввода-вывода в секунду.
- **Latency (Задержка):** Время выполнения одной операции. Различают `slat` (submission), `clat` (completion) и `lat` (общее время).
- **Паттерны нагрузки:** Схемы доступа к данным (`read`, `write`, `randread`, `randwrite`, `rw`, `randrw`).
- **Механизмы I/O (`ioengine`):** Библиотеки и интерфейсы для взаимодействия с ядром (`sync`, `libaio`, `io_uring`, `mmap`, `posixaio`).

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

### Механизмы ввода-вывода (ioengine)

Выбор движка критически влияет на результаты, особенно для быстрых накопителей:

1.  **`sync` / `psync`:** Базовые синхронные вызовы. Поток блокируется до завершения операции. Не подходит для тестирования высокой глубины очереди.
2.  **`libaio`:** Традиционный асинхронный I/O в Linux. Требует `direct=1`. Долгое время был стандартом для тестирования NVMe.
3.  **`io_uring`:** Самый современный и производительный интерфейс (Linux 5.1+). Минимизирует переключения контекста, поддерживает Zero-copy и Polling (`hipri`). **Рекомендуется для всех современных тестов на Linux.**
4.  **`rbd` / `rados`:** Прямое тестирование хранилищ Ceph без промежуточного монтирования.

### Глубина очереди и потоки

- **`iodepth`:** Количество запросов, отправленных драйверу одновременно (только для асинхронных движков). Позволяет "насытить" контроллер SSD/NVMe.
- **`numjobs`:** Количество параллельных процессов или потоков `fio`. Полезно для проверки масштабируемости контроллера или RAID-массива.

## Практические сценарии

### Установка

```bash
# Ubuntu / Debian
sudo apt update && sudo apt install -y fio

# RHEL / CentOS / Rocky Linux
sudo dnf install -y fio
```

### Базовые замеры (Сырые устройства и файлы)

**Важно:** Тестирование сырого устройства (`/dev/sdX`) точнее, но **уничтожает данные**.

```bash
# 1. Последовательная запись (проверка линейной скорости)
fio --name=seq_write --rw=write --bs=1M --size=10G --filename=/dev/sdb \
    --ioengine=io_uring --direct=1 --group_reporting

# 2. Случайное чтение 4K (оценка IOPS для БД)
# Используем io_uring и глубину очереди 32
fio --name=rand_read --rw=randread --bs=4k --size=4G --filename=./testfile \
    --ioengine=io_uring --direct=1 --iodepth=32 --runtime=60 --time_based
```

### Тестирование для облачных дисков (AWS/GCP/Yandex)

В облаках производительность часто лимитирована (IOPS/BW limits). Для достижения лимитов важна глубина очереди.

```bash
# Проверка латентности на малой нагрузке
fio --name=cloud_lat --rw=randread --bs=4k --size=1G --direct=1 \
    --ioengine=io_uring --iodepth=1 --numjobs=1 --filename=./testfile

# Попытка достичь максимальных IOPS (например, 50k)
fio --name=cloud_max_iops --rw=randread --bs=4k --size=10G --direct=1 \
    --ioengine=io_uring --iodepth=128 --numjobs=4 --group_reporting --filename=./testfile
```

### Тестирование для etcd (fdatasync)

Для `etcd` критична скорость сброса данных на диск (`fdatasync`).

```bash
fio --rw=write --ioengine=sync --fdatasync=1 --directory=./etcd-data \
    --size=22m --bs=2300 --name=etcd-sync-test
# → Ищите результат "clat" или "lat". Для стабильной работы etcd p99 должен быть < 10ms.
```

### Сценарий для SSD TRIM (Unmap)

Проверка скорости очистки ячеек.

```bash
fio --name=trim_test --filename=/dev/nvme0n1 --rw=trim --bs=1M \
    --ioengine=libaio --direct=1 --runtime=60 --time_based
```

### Тестирование Ceph RBD

Для замера производительности блочных устройств Ceph можно использовать два подхода:

1.  **Через ядро (Kernel RBD):** Тестирование смонтированного устройства `/dev/rbd0`. Используются стандартные движки `io_uring` или `libaio`.
2.  **Напрямую через librbd (Userspace):** Движок `ioengine=rbd`. Позволяет тестировать RBD без маппинга в ОС.

```bash
# Пример для librbd (userspace)
fio --name=ceph_test --ioengine=rbd --clientname=admin --pool=rbd \
    --rbdname=image01 --rw=randwrite --bs=4k --direct=1 --iodepth=32
```

### Использование файлов конфигурации (Job-files)

Пример файла `db_workload.fio`:

```ini
[global]
ioengine=io_uring
direct=1
group_reporting
runtime=120
time_based
filename=/dev/nvme1n1

[oltp_read]
rw=randread
bs=8k
iodepth=64
numjobs=4

[oltp_write]
rw=randwrite
bs=8k
iodepth=32
numjobs=2
```

Запуск: `fio db_workload.fio`

## Дополнительная информация

### Вывод результатов и парсинг

`fio` может выводить данные в различных форматах для автоматизации:

```bash
# Вывод в JSON для скриптов или Grafana
fio job_file.fio --output-format=json > results.json

# Компактный формат (terse), разделенный точкой с запятой
fio job_file.fio --output-format=terse
```

### Рекомендации по чистоте эксперимента

1.  **Steady State (Установившееся состояние):** SSD показывают завышенные результаты "из коробки" (из-за пустого SLC-кэша). Перед финальным тестом SSD нужно "прогреть" — записать его полностью 1–2 раза.
2.  **Прямой ввод-вывод (`--direct=1`):** Всегда используйте этот параметр, чтобы исключить влияние Page Cache ядра Linux.
3.  **Охлаждение:** NVMe накопители могут снижать частоту (троттлинг) при перегреве во время долгих тестов. Мониторьте температуру через `smartctl`.
4.  **Файловая система vs Raw:** Тестирование поверх ФС (Ext4, XFS) добавляет накладные расходы на метаданные. Если нужно проверить чистое железо — используйте блочное устройство.

### Типичные показатели производительности (2025–2026)

| Тип устройства | Seq Read (МБ/с) | Seq Write (МБ/с) | Rand Read 4K (IOPS) |
| :--- | :--- | :--- | :--- |
| **HDD 7200 RPM** | 150–250 | 120–200 | 100–180 |
| **SATA SSD** | 540–560 | 500–530 | 70K–100K |
| **NVMe PCIe 3.0** | 3000–3500 | 2500–3200 | 400K–600K |
| **NVMe PCIe 4.0** | 7000–7500 | 5000–6500 | 800K–1.2M |
| **NVMe PCIe 5.0** | 10000–14500 | 9000–12000 | 1.5M–2M+ |

### Полезные ссылки

- [Официальная документация fio](https://fio.readthedocs.io/)
- [io_uring — современный асинхронный I/O](../../Core/kernel/io_uring.md)
- [Мониторинг дисковой статистики (iostat)](./iostat.md)
- [Диагностика узких мест БД](../../../Databases/db_disk_bottleneck_troubleshooting.md)
