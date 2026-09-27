# Direct I/O vs Buffered I/O: влияние на дисковый ввод-вывод

## Определения

- **Buffered I/O (Буферизованный ввод-вывод):** Стандартный режим работы с файлами в Linux. Данные проходят через Page Cache (кэш страниц ядра) перед записью на диск. При чтении данные сначала попадают в RAM, а на диск — только при нехватке кэша или синхронном вызове. По умолчанию для всех `read()`/`write()`.
- **Direct I/O (Прямой ввод-вывод):** Режим обхода Page Cache через флаг `O_DIRECT`. Данные записываются/читаются напрямую между буфером приложения и блочным устройством. Используется СУБД для самостоятельного управления буферами.
- **Page Cache (Кэш страниц):** Основной кэш ядра для данных файлов. Использует свободную RAM для кэширования чтений с диска. При записи процесс получает подтверждение сразу (данные в RAM), а физический сброс откладывается (writeback).
- **O_SYNC / O_DSYNC:** Флаги, гарантирующие синхронную запись. `O_SYNC` блокирует вызов до физического сброса данных и метаданных. `O_DSYNC` — только метаданных. Оба значительно снижают производительность.
- **fsync / fdatasync:** Системные вызовы принудительного сброса. `fsync(fd)` сбрасывает данные и метаданные файла. `fdatasync(fd)` — только данные (без обновленияmtime/atime). Критичны для WAL и журналирования.
- **Double Buffering (Двойное кэширование):** Ситуация, когда данные дублируются в двух уровнях кэширования: Page Cache ОС и внутренний буфер приложения (например, `shared_buffers` в PostgreSQL). Уменьшает эффективный объем кэша.
- **io_uring:** Современный интерфейс асинхронного I/O (ядро 5.1+). Работает через shared ring buffer, минимизируя системные вызовы. Поддерживает `O_DIRECT` и buffered I/O.

## Основные концепции

### Сравнение режимов

| Параметр | Buffered I/O | Direct I/O |
| :--- | :--- | :--- |
| **Кэширование** | Через Page Cache ядра | Прямой доступ к устройству |
| **Запись (latency)** | Низкая (подтверждение сразу) | Высокая (ожидание физической записи) |
| **Чтение (latency)** | Низкое (данные в кэше) | Высокое (чтение с диска) |
| **Throughput** | Зависит от размера RAM | Зависит от скорости диска |
| **Потеря данных** | Возможна при сбое (данные в RAM) | Минимальна (данные на диске) |
| **Потребление RAM** | Высокое (Page Cache) | Минимальное |
| **Использование** | Файловые серверы, веб, логи | СУБД, WAL, BATCH-записи |

### Когда СУБД используют Direct I/O

#### PostgreSQL

```
shared_buffers (8GB) → Page Cache ОС (дополнительно) → Disk
     ↑                        ↑
  Внутренний кэш          Системный кэш
  (управляет PostgreSQL)   (управляет ядро)

Проблема: Double Buffering — одни и те же данные в двух кэшах
Решение: Оставить shared_buffers=25% RAM, остальное — Page Cache
         НЕ использовать O_DIRECT (PostgreSQL сам оптимизирует через shared_buffers)
```

**Рекомендация:** PostgreSQL **не использует** O_DIRECT для основных данных. Он полагается на `shared_buffers` + Page Cache. Однако `O_DIRECT` используется для:
- `wal_sync_method = open_datasync` (WAL)
- Бэкапы (`pg_basebackup`)

#### MySQL/InnoDB

```
InnoDB Buffer Pool (8GB) → Disk
     ↑
  Внутренний кэш
  (управляет InnoDB)

Проблема: Double Buffering — InnoDB кэширует данные, которые также в Page Cache
Решение: innodb_flush_method = O_DIRECT → обход Page Cache
```

**Рекомендация:** `innodb_flush_method = O_DIRECT` — стандартная настройка для InnoDB. Исключение: когда `innodb_buffer_pool_size` мал и данные часто читаются из Page Cache.

#### MongoDB

```
WiredTiger Cache (50% RAM) → Disk
     ↑
  Внутренний кэш

Рекомендация: storage.wiredTiger.engineConfig.cacheSizeGB = 50% RAM
              wiredTiger.diagnosticDataFilePathEnabled = true
```

### Влияние на Page Cache и vm.dirty_*

**Buffered I/O:**
- `write()` → данные попадают в Page Cache → страница помечается как dirty
- Ядро сбрасывает dirty pages через writeback (`vm.dirty_*` параметры)
- При `fsync()` → принудительный сброс на диск

**Direct I/O:**
- `write()` → данные идут напрямую на диск → Page Cache не используется
- `vm.dirty_*` параметры НЕ влияют на Direct I/O
- При `O_DIRECT | O_SYNC` → данные пишутся на диск синхронно

```
Влияние на vm.dirty_ratio:

Buffered I/O:
  vm.dirty_ratio=20 → при 20% RAM в dirty pages → throttle (balance_dirty_pages)
  → Процесс замедляется, участвуя в writeback

Direct I/O:
  vm.dirty_ratio=20 → НЕ влияет (данные не в Page Cache)
  → Write происходит напрямую на диск
```

### Влияние на Disk I/O метрики

| Метрика | Buffered I/O | Direct I/O |
| :--- | :--- | :--- |
| **`await`** | Зависит от writeback | Всегда отражает реальную задержку диска |
| **`%util`** | Может быть низким (данные в кэше) | Отражает реальную загрузку |
| **`w_await`** | Зависит от `vm.dirty_*` | Всегда = задержка устройства |
| **`r_await`** | Низкое (данные в кэше) | Высокое (чтение с диска) |
| **Dirty pages** | Растут при записи | Не растут (не используют Page Cache) |

## Предварительные требования

```bash
# Базовые инструменты
sudo apt install sysstat fio    # Debian/Ubuntu
sudo dnf install sysstat fio    # RHEL/CentOS
```

## Практические сценарии

### Шаг 1: Определение режима I/O приложения

```bash
# Проверка открытых файлов с O_DIRECT
ls -la /proc/$(pgrep mysqld)/fd/ | grep -c anon_inode
# → количество файлов с O_DIRECT (для InnoDB)

# Проверка через strace (медленно, только для диагностики)
sudo strace -e trace=openat -p $(pgrep mysqld) 2>&1 | grep O_DIRECT
# → openat(AT_FDCWD, "/var/lib/mysql/ibdata1", O_RDWR|O_DIRECT) = 5

# Проверка fdatasync через strace
sudo strace -e trace=fdatasync -p $(pgrep mysqld) 2>&1 | head -5
# → fdatasync(5) = 0
```

### Шаг 2: Бенчмарк: Buffered vs Direct I/O

```bash
# Buffered I/O (по умолчанию)
sudo fio --name=buffered --directory=/tmp --rw=write --bs=4k \
  --size=1G --numjobs=1 --runtime=30 --group_reporting
# → write: IOPS=50000, BW=195MiB/s, lat=0.020ms (в кэше!)

# Direct I/O (обход кэша)
sudo fio --name=direct --directory=/tmp --rw=write --bs=4k \
  --direct=1 --size=1G --numjobs=1 --runtime=30 --group_reporting
# → write: IOPS=8000, BW=31MiB/s, lat=0.125ms (реальная скорость диска)

# Чтение: Buffered vs Direct
sudo fio --name=read_buffered --directory=/tmp --rw=read --bs=4k \
  --size=1G --numjobs=1 --runtime=30 --group_reporting
# → read: IOPS=200000, BW=781MiB/s (данные в Page Cache)

sudo fio --name=read_direct --directory=/tmp --rw=read --bs=4k \
  --direct=1 --size=1G --numjobs=1 --runtime=30 --group_reporting
# → read: IOPS=10000, BW=39MiB/s (чтение с диска)
```

### Шаг 3: Проверка влияния на Page Cache

```bash
# Buffered I/O: dirty pages растут
sudo fio --name=write_buf --directory=/tmp --rw=write --bs=4k \
  --size=2G --numjobs=1 --runtime=30 --group_reporting &
sleep 5
grep -E "Dirty|Writeback" /proc/meminfo
# → Dirty: 512 MB (данные в Page Cache, ждут writeback)
# → Writeback: 128 MB (сейчас сбрасываются на диск)

# Direct I/O: dirty pages не растут
sudo fio --name=write_dir --directory=/tmp --rw=write --bs=4k \
  --direct=1 --size=2G --numjobs=1 --runtime=30 --group_reporting &
sleep 5
grep -E "Dirty|Writeback" /proc/meminfo
# → Dirty: 0 kB (данные не в Page Cache)
# → Writeback: 0 kB
```

### Шаг 4: Настройка для PostgreSQL

```bash
# PostgreSQL: shared_buffers + wal_sync_method

# Проверка текущих настроек
sudo -u postgres psql -c "SHOW shared_buffers;"
# → 8GB

sudo -u postgres psql -c "SHOW wal_sync_method;"
# → fsync

# Оптимальные настройки
# shared_buffers = 25% RAM (НЕ больше, чтобы избежать double buffering)
# effective_cache_size = 75% RAM
# wal_sync_method = open_datasync (O_DIRECT для WAL)

# Настройка через postgresql.conf
sudo tee -a /etc/postgresql/16/main/postgresql.conf << 'EOF'
wal_sync_method = open_datasync
EOF
sudo systemctl restart postgresql
```

### Шаг 5: Настройка для MySQL/InnoDB

```bash
# MySQL: innodb_flush_method = O_DIRECT

# Проверка текущей настройки
mysql -e "SHOW VARIABLES LIKE 'innodb_flush_method';"
# → fsync

# Установка O_DIRECT
mysql -e "SET GLOBAL innodb_flush_method = 'O_DIRECT';"

# Постоянная настройка
sudo tee -a /etc/mysql/mysql.conf.d/innodb.cnf << 'EOF'
[mysqld]
innodb_flush_method = O_DIRECT
innodb_buffer_pool_size = 12G
innodb_log_file_size = 2G
EOF
sudo systemctl restart mysql
```

### Шаг 6: Мониторинг влияния на disk I/O

```bash
# Buffered I/O: мониторинг dirty pages и await
watch -n2 "grep -E 'Dirty|Writeback' /proc/meminfo && iostat -xz 1 1 | grep -E 'Device|sda'"

# Direct I/O: мониторинг реального await
watch -n2 "iostat -xz 1 1 | grep -E 'Device|sda'"

# Сравнение:.Buffered I/O может показывать низкий %util при высоком await
# (данные в кэше, но writeback блокирует)
# Direct I/O показывает реальную утилизацию
```

## Автоматизация и мониторинг

### Prometheus alerts

```yaml
groups:
  - name: io_mode_alerts
    rules:
      - alert: HighDirtyPagesWithBufferedIO
        expr: node_memory_Dirty_bytes / node_memory_MemTotal_bytes > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий уровень dirty pages на {{ $labels.instance }}"
          description: "Dirty pages > 10% RAM. Возможно, приложение использует Buffered I/O с агрессивной записью. Проверьте vm.dirty_* параметры."

      - alert: DirectIOLatencyHigh
        expr: |
          avg by(device) (
            rate(node_disk_write_time_seconds_total[5m]) /
            rate(node_disk_writes_completed_total[5m])
          ) > 0.01
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокая задержка Direct I/O на {{ $labels.device }}"
          description: "w_await > 10ms. Проверьте здоровье диска (smartctl)."
```

## Типичные ошибки и устранение неполадок

| Симптом | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `await` низкий, но приложение «тормозит» | Buffered I/O: writeback блокирует | `grep Dirty /proc/meminfo`, `vmstat 1` | Настроить `vm.dirty_*`, перейти на Direct I/O |
| `%util` низкий, но `await` высокий | Buffered I/O: кэш маскирует реальную нагрузку | `cat /proc/meminfo \| grep Dirty` | Использовать `fio --direct=1` для реального теста |
| PostgreSQL потребляет >50% RAM | `shared_buffers` слишком велик | `SHOW shared_buffers` | Установить 25% RAM, `effective_cache_size = 75% RAM` |
| MySQL потребляет 100% RAM | `innodb_buffer_pool_size` + Page Cache | `SHOW VARIABLES LIKE 'innodb_buffer_pool_size'` | `innodb_flush_method = O_DIRECT`, уменьшить pool |
| Direct I/O замедляет запись | Ожидание физической записи | `iostat -xz 1` (смотрим `w_await`) | Это нормально; используйте асинхронный I/O (`io_uring`) |
| `fdatasync` вызывает задержки | Синхронный сброс WAL | `strace -e fdatasync -p PID` | Увеличить `wal_buffers`, использовать `open_datasync` |

## Ограничения и особые случаи

### NVMe и io_uring

- `io_uring` с `O_DIRECT` минимизирует системные вызовы и обеспечивает минимальную задержку.
- Для NVMe Gen4/Gen5 рекомендуется `io_uring` + `O_DIRECT` + `hipri=1` (polling mode).
- Buffered I/O на NVMe менее эффективен из-за того, что Page Cache добавляет overhead без значительного выигрыша.

### Контейнеры (Docker, Kubernetes)

- В контейнерах `O_DIRECT` требует `--privileged` или `--cap-add=SYS_ADMIN`.
- В Kubernetes `O_DIRECT` доступен через `hostPID: false` и volume mount options.
- Рекомендация: использовать Buffered I/O в контейнерах, Direct I/O — на хосте.

### NFS и сетевые ФС

- NFS не поддерживает `O_DIRECT` на клиентах (данные всегда через Page Cache).
- Для NFS: `sync` mount option = синхронная запись (аналог O_SYNC).
- FUSE не поддерживает `O_DIRECT`.

## Дополнительная информация

### См. также

- [Настройка writeback: vm.dirty_* параметры](./writeback_tuning.md) — влияние dirty pages на Buffered I/O.
- [fio — бенчмаркинг](../../../Diagnostics/Filesystem/fio.md) — тестирование `--direct=1`.
- [Performance Tuning: ФС](../../../../FileSystems/performance_tuning.md) — O_DIRECT, O_SYNC, mount options.
- [Database Performance Concepts](../../../../Databases/Concepts/database_performance_concepts.md) — настройка СУБД.
