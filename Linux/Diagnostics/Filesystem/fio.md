# `fio` (Flexible I/O Tester)

## Определения

- **`fio` (Flexible I/O Tester):** Утилита для бенчмаркинга и стресс-тестирования систем хранения данных. Эмулирует различные типы дисковой нагрузки и измеряет ключевые метрики производительности.
- **BW (Bandwidth):** Пропускная способность (МБ/с).
- **IOPS (Input/Output Operations Per Second):** Количество операций ввода-вывода в секунду.
- **Latency (lat):** Задержка выполнения операций (мкс, мс).
- **Паттерны нагрузки:** Типы доступа к данным (последовательный/случайный, чтение/запись/смешанный).
- **Механизмы I/O (`ioengine`):** Интерфейсы взаимодействия с подсистемой I/O (`sync`, `libaio`, `io_uring`, `mmap`).

## Основные концепции

`fio` позволяет точно имитировать реальные сценарии:

| Сценарий | Паттерн | Размер блока | Пример |
| :--- | :--- | :--- | :--- |
| **База данных (OLTP — Online Transaction Processing)** | `randread`, `randwrite` | 4K–8K | PostgreSQL, MySQL |
| **Файловый сервер** | `read`, `write` | 64K–1M | NFS, Samba |
| **Веб-сервер** | `randread` | 4K–16K | Статический контент |
| **Логирование** | `write` (seq) | 16K–128K | Журналы, аудит |
| **Бэкапы** | `read`, `write` (seq) | 256K–1M | Архивирование |
| **Виртуализация** | `randrw` | 4K–64K | ВМ с mixed workload |

**Ключевые параметры:**

- `--rw`: Режим операции (`read`, `write`, `randread`, `randwrite`, `randrw`, `rw`)
- `--bs`: Размер блока (4k, 16k, 128k, 1M)
- `--size` / `--runtime`: Объем данных или время теста
- `--numjobs`: Количество потоков
- `--iodepth`: Глубина очереди (для асинхронных `ioengine`)
- `--ioengine`: Механизм I/O (`libaio`, `sync`, `io_uring`, `psync`)
- `--direct`: Прямой I/O (0 = буферизированный, 1 = прямой)

**Интерпретация результатов:**

- **IOPS** важны для транзакционных нагрузок (БД)
- **Пропускная способность** — для последовательных операций (бэкапы, видео)
- **Latency** — критична для интерактивных приложений (p95, p99 важнее средней)

## Практические сценарии

### Базовые тесты

```bash
# Последовательная запись 1GB блоками по 1MB
fio --name=seq_write --rw=write --bs=1M --size=1G --filename=./testfile \
    --ioengine=libaio --direct=1 --fsync=32

# Последовательное чтение
fio --name=seq_read --rw=read --bs=1M --size=1G --filename=./testfile \
    --ioengine=libaio --direct=1

# Случайное чтение 4K (типично для БД)
fio --name=rand_read --rw=randread --bs=4k --size=1G --filename=./testfile \
    --ioengine=libaio --direct=1 --iodepth=32

# Случайная запись 4K
fio --name=rand_write --rw=randwrite --bs=4k --size=1G --filename=./testfile \
    --ioengine=libaio --direct=1 --iodepth=32
```

### Смешанная нагрузка (mixed workload)

```bash
# 70% чтение / 30% запись, 4 потока, глубина очереди 32
fio --name=mixed_rw --rw=randrw --rwmixread=70 --bs=4k --size=1G \
    --numjobs=4 --iodepth=32 --ioengine=libaio --direct=1 \
    --filename=./testfile --group_reporting

# 50/50 чтение/запись для виртуализации
fio --name=vm_workload --rw=randrw --rwmixread=50 --bs=8k --size=2G \
    --numjobs=8 --iodepth=64 --ioengine=libaio --direct=1 \
    --group_reporting --runtime=60 --time_based
```

### Тестирование для etcd

Перед запуском кластера etcd необходимо проверить задержку `fdatasync`:

```bash
fio --rw=write --ioengine=sync --fdatasync=1 --directory=./etcd-data \
    --size=22m --bs=2300 --name=etcd-test
# → fdatasync задержка должна быть < 10ms (лучше < 2ms)
```

### Бенчмаркинг RBD (RADOS Block Device) в Ceph

```bash
# Тест последовательной записи на RBD-устройство
fio --name=write --ioengine=libaio --rw=write --bs=4k \
    --direct=1 --numjobs=1 --size=1G --runtime=60 \
    --filename=/dev/rbd0
```

### Использование job-файлов

Создайте файл `benchmark.fio`:

```ini
[global]
ioengine=libaio
direct=1
size=1G
runtime=60
time_based
group_reporting

[seq_write]
rw=write
bs=1M
numjobs=4
iodepth=32

[rand_read_4k]
rw=randread
bs=4k
numjobs=8
iodepth=64
```

Запуск:

```bash
fio benchmark.fio
```

## Дополнительная информация

### Вывод результатов

**Форматы вывода:**

```bash
# Нормальный вывод (человекочитаемый)
fio --name=test --rw=randread --bs=4k --size=1G

# JSON для парсинга
fio --name=test --rw=randread --bs=4k --size=1G --output-format=json
```

**Ключевые поля вывода:**

- `bw`: Пропускная способность (КБ/с)
- `iops`: Операций в секунду
- `lat (usec)` / `lat (msec)`: Задержки (среднее, стандартное отклонение, перцентили)
- `clat (usec)`: Задержки завершения (completion latency)

### Рекомендации по тестированию

1. **Тест на пустом диске:** Результаты на заполненном диске могут быть нерепрезентативными.
2. **Прогрев:** SSD (Solid State Drive) могут показывать разные результаты до и после заполнения SLC-кэша (Single Level Cell).
3. **Несколько прогонов:** Запускайте тест 3–5 раз для стабильных результатов.
4. **Мониторинг:** Используйте `iostat -x 1` параллельно для контроля утилизации.
5. **Прямой I/O:** `--direct=1` отключает кэширование ядра для честных результатов.

### Типичные значения производительности

| Тип накопителя | Seq Read (MB/s) | Seq Write (MB/s) | Rand Read 4K (IOPS) |
| :--- | :--- | :--- | :--- |
| **HDD (Hard Disk Drive) 7200 RPM** | 100–200 | 80–150 | 100–200 |
| **SATA SSD** | 500–550 | 450–500 | 50K–100K |
| **NVMe PCIe 3.0** | 2000–3500 | 1500–3000 | 300K–600K |
| **NVMe PCIe 4.0** | 5000–7500 | 4000–6500 | 600K–1M+ |

### Ограничения и предостережения

- **Деструктивный тест:** Тест на блочном устройстве (`/dev/sdX`) уничтожает данные!
- **Тепловой троттлинг:** NVMe (Non-Volatile Memory Express) могут снижать производительность при перегреве.
- **RAID (Redundant Array of Independent Disks):** Результаты зависят от уровня RAID и контроллера.

### Дополнительные ссылки

- [Официальный manual fio](https://fio.readthedocs.io/)
- [io_uring — асинхронный ввод-вывод](../../Core/kernel/io_uring.md)
- [Статистика I/O (iostat)](./iostat.md)
