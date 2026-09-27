# Чек-лист диагностики дискового ввода-вывода (I/O)

Данный документ представляет собой пошаговый алгоритм выявления причин деградации производительности дисковой подсистемы — от экспресс-анализа до глубокой трассировки на уровне блочного уровня.

## Определения

- **I/O Wait (`%wa`)**: Процент времени CPU, проведенного в ожидании завершения операций I/O при отсутствии другой полезной нагрузки. Может вводить в заблуждение на многоядерных системах и NVMe-устройствах.
- **Pressure Stall Information (PSI)**: Механизм ядра Linux (v4.20+) для измерения реальной задержки процессов из-за нехватки ресурсов. В отличие от `%iowait`, отражает фактическое влияние на приложения.
- **Latency (Await)**: Среднее время выполнения запроса, включая очередь планировщика и время обслуживания диском.
- **IOPS (Input/Output Operations Per Second)**: Количество операций ввода-вывода в секунду.
- **Throughput (Пропускная способность)**: Объем данных, передаваемых в единицу времени (МБ/с).
- **Uninterruptible Sleep (D-state)**: Состояние процесса, заблокированного в системном вызове (обычно I/O). Увеличивает `Load Average`.
- **avgqu-sz (Average Queue Size)**: Средняя длина очереди запросов к устройству. Рассчитывается из Weighted I/O time (поле 14 `/proc/diskstats`).
- **Writeback**: Фоновый процесс сброса «грязных» страниц из Page Cache на физический носитель потоками `kworker`.

## Основные концепции

### Иерархия диагностики (Сверху вниз)

Эффективный поиск проблем I/O должен следовать логике от влияния на систему к конкретному аппаратному сектору:

1.  **Общая оценка (System-wide)**: Влияет ли I/O на отзывчивость системы? (PSI, Load Average).
2.  **Уровень устройств (Block Device)**: Какой именно диск или раздел перегружен? (`iostat`, `diskstats`).
3.  **Уровень процессов (Process-specific)**: Кто именно генерирует нагрузку? (`iotop`, `pidstat`, `/proc/<pid>/io`).
4.  **Уровень ФС и файлов (Filesystem)**: К каким файлам идут обращения? (`fatrace`, `lsof`, `opensnoop`).
5.  **Уровень ядра и прерываний (Kernel/IRQ)**: Как ядро обрабатывает запросы? (`wchan`, `perf`, `interrupts`).
6.  **Блочная трассировка (Block Tracing)**: Детальный анализ очередей и задержек (`blktrace`, eBPF).
7.  **Аппаратный уровень (Hardware)**: Есть ли физические ошибки? (`smartctl`, `dmesg`, `nvme smart-log`).

### Почему `%iowait` не отражает реальность

На многоядерных системах и NVMe `%iowait` может быть близок к нулю, хотя приложения испытывают серьезные задержки. Причины:
- **Multi-core masking**: Задержка распределяется по нескольким ядрам, усредняя `%iowait` на уровне CPU.
- **PSI advantage**: Метрика `some avg10` в `/proc/pressure/io` показывает фактическое время простоя процессов, а не CPU.
- **Queue depth**: Высокий `await` при низком `%util` указывает на переполнение очереди планировщика или внешний троттлинг (hypervisor, SAN).

### cgroups и изоляция I/O

В системах с cgroups v2 доступен `io.pressure` для измерения давления внутри контрольных групп. В cgroups v1 PSI недоступен, используйте `blkio.io_service_bytes` для косвенной оценки. Лимиты `io.max` могут создавать искусственный троттлинг, который выглядит как деградация диска.

## Предварительные требования

### Проверка конфигурации ядра

```bash
# Статистика задержек задач (нужна для iotop, pidstat)
grep TASK_DELAY_ACCT /boot/config-$(uname -r)
# → CONFIG_TASK_DELAY_ACCT=y

# Pressure Stall Information (нужна для PSI)
grep PSI /boot/config-$(uname -r)
# → CONFIG_PSI=y

# eBPF (нужна для biolatency, biosnoop, bpftrace)
grep BPF /boot/config-$(uname -r)
# → CONFIG_BPF=y, CONFIG_BPF_SYSCALL=y
```

### Установка инструментов

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install -y sysstat iotop bpfcc-tools bpftrace fatrace smartmontools nvme-cli procps

# RHEL/CentOS/Fedora
sudo dnf install -y sysstat iotop bcc-tools bpftrace fatrace smartmontools nvme-cli procps-ng

# Arch Linux
sudo pacman -S sysstat iotop bpftrace bcc-tools fatrace smartmontools nvme-cli procps

# openSUSE/SLES
sudo zypper install -y sysstat iotop bpftrace bcc-tools fatrace smartmontools nvme-cli procps
```

### Включение сбора данных

```bash
# sysstat (для sar, iostat с историей)
sudo systemctl enable --now sysstat

# Проверка task_delayacct
echo 1 | sudo tee /proc/sys/kernel/task_delayacct
```

## Практические сценарии

### Шаг 1: Экспресс-диагностика (PSI и vmstat)

Начните с оценки общего влияния I/O на систему.

```bash
# Проверка давления на I/O
cat /proc/pressure/io
# → result: some avg10=15.20 avg60=10.05 avg300=5.00 total=1234567
# some avg10 > 5-10% — приложения уже испытывают задержки из-за диска.
# full: все процессы были заблокированы на I/O (критическая ситуация).

# Анализ очередей и свопинга
vmstat 1 5
# → b: количество процессов в D-state (uninterruptible sleep).
# → wa: высокий iowait.
# → si/so: если > 0, диск перегружен операциями подкачки (Swap).
# → us/sy/id: распределение CPU для исключения CPU-узкого места.
```

**Ожидаемый результат:** `some avg10 < 5` = I/O не является причиной замедления. Переходите к анализу CPU/RAM.

### Шаг 2: Идентификация проблемного устройства (iostat)

```bash
# Расширенная статистика всех устройств (игнорировать первую строку)
iostat -xz 1
```

**На что смотреть:**
- **`await`**: Если > 20 мс (HDD) или > 1 мс (SSD/NVMe) — диск не справляется. Для NVMe порог часто составляет 0.5 мс.
- **`aqu-sz` / `avgqu-sz`**: Длина очереди. Постоянные значения > 1 (на поток) или > 2 (общие) — признак перегрузки.
- **`%util`**: На HDD > 80% указывает на насыщение. На SSD/NVMe 100% не означает проблему из-за параллельной обработки.
- **`r/s` + `w/s`**: IOPS. Определите характер нагрузки (Small Random vs Large Sequential).
- **`f_await`**: Задержка flush-операций. Высокое значение при низком общем `await` указывает на проблемы с кэшированием или отсутствие PLP (Power Loss Protection).

**Дополнительно:**
```bash
# Проверка cgroups v2 (если используются контейнеры)
cat /sys/fs/cgroup/*/io.stat 2>/dev/null || echo "cgroups v2 io.stat не найден"

# Проверка LVM-устройств
lsblk -o NAME,SERIAL,SIZE,ROTA,MOUNTPOINT
```

**Ожидаемый результат:** Выявлено конкретное устройство (`sda`, `nvme0n1`, `dm-1`) с аномальными метриками.

### Шаг 3: Поиск процесса-виновника (iotop и pidstat)

```bash
# Поиск "топовых" писателей/читателей
sudo iotop -Pa -o
# -P: показывать только процессы (не потоки).
# -a: кумулятивная статистика с момента запуска iotop.

# Детальная статистика по процессу
pidstat -d 1
# → iodelay: задержка процесса в тиках из-за I/O.
```

**Важные нюансы:**
- `iotop` может показывать `kworker` вместо реального процесса из-за writeback. Подробнее: [Роль kworker и процессов writeback](./kworker_flush.md).
- `pidstat -d` не учитывает `io_uring` и writeback ядра. Для полной картины используйте `perf record -e block:block_rq_issue -a sleep 5`.
- Для быстрого анализа без установки утилит: `cat /proc/<PID>/io`.

**Ожидаемый результат:** Идентифицирован PID процесса с наибольшим `DISK WRITE`/`DISK READ`.

### Шаг 4: Анализ точек блокировки (wchan)

Если процесс в `D-state`, узнайте, где именно в ядре он застрял:

```bash
ps -eo pid,state,wchan:30,comm | grep " D "
```

**Интерпретация wchan:**
- `io_schedule`: Обычное ожидание диска.
- `get_request`: Перегрузка очередей (диск не успевает принимать запросы).
- `jbd2_log_wait_commit`: Ожидание фиксации транзакции в журнале (проблема медленной записи метаданных).
- `wait_on_page_bit`: Ожидание страницы в кэше (часто при высокой конкуренции за память).
- `balance_dirty_pages`: Ядро принудительно замедляет процесс из-за переполнения кэша записи.
- `inode_lock` / `ext4_*` / `xfs_*`: Прямой индикатор конкуренции за блокировки файловой системы.
- `fuse_dev_read`: Блокировка в FUSE-файловой системе.

**Дополнительные инструменты:**
```bash
# Мониторинг открытия файлов (поиск тысяч openat на несуществующие файлы)
sudo opensnoop -x 2>/dev/null || echo "opensnoop не установлен (bcc-tools)"

# Трассировка обращений к файлам
sudo fatrace -t | head -n 20
```

**Ожидаемый результат:** Указана конкретная функция ядра (`io_schedule`, `ext4_inode_lock` и т.д.), указывающая на тип проблемы.

### Шаг 5: Диагностика конкуренции за блокировки

Если диск почти не загружен, но Load Average и задержки растут:

1.  **Мониторинг переключения контекста:**
    ```bash
    pidstat -w 1
    # cswch/s (voluntary) и nvcswch/s (involuntary). 
    # Рост при D-state указывает на ожидание блокировок.
    ```

2.  **Профилирование блокировок ядра:**
    ```bash
    sudo perf lock record sleep 30
    sudo perf lock report
    # Ищите функции с наибольшим временем удержания (Wait time).
    ```

3.  **Анализ VFS-блокировок:**
    ```bash
    ps -eo pid,state,wchan:30,comm | awk '$2=="D" && $3 ~ /lock|inode|ext4|xfs/'
    ```

**Ожидаемый результат:** Выявлены блокировки с высоким `Wait time` или процессы, ожидающие `inode_lock`.

### Шаг 6: Глубокая трассировка задержек (eBPF и blktrace)

Когда средние значения выглядят нормально, но есть "микро-фризы":

```bash
# Гистограмма задержек выполнения I/O (помогает найти Tail Latency)
sudo biolatency-bpfcc -D 1 10
# → Ищите значения в корзинах > 100ms (хвост распределения).

# Время вне CPU (offcputime)
sudo offcputime-bpfcc -K -m 5 2>/dev/null || echo "offcputime-bpfcc не найден"
# Показывает, в каких функциях ядра процесс проводит время, ожидая I/O.

# Трассировка каждого запроса блочного уровня (видит io_uring)
sudo biosnoop-bpfcc | awk '$NF > 100'
# → Запросы с задержкой > 100 мс: COMM, PID, LAT(ms).
```

Если eBPF недоступен, используйте `blktrace` для сбора полной истории событий на шине:

```bash
sudo blktrace -d /dev/sda -o - | blkparse -i -
```

**Ожидаемый результат:** Выявлены P95/P99 выбросы задержек (`biolatency`) или конкретные запросы > 100 мс (`biosnoop`).

### Шаг 7: Аппаратный уровень и физические ошибки

Если ни один слой ПО не объясняет задержку, проверьте физическое состояние:

```bash
# Логи ядра на наличие таймаутов и ошибок
dmesg -T | grep -iE "timeout|blocked|error|reset|nvme|scsi|ata"
# → nvme nvme0: I/O 123 QID 4 timeout, completion polled

# SMART-статистика (замените sda на нужное устройство)
sudo smartctl -a /dev/sda | grep -E 'SMART|Reallocated|Pending|Current_Pending_Sector|Temperature'

# NVMe — подробный лог (если доступен)
sudo nvme smart-log /dev/nvme0 2>/dev/null | grep -E 'critical_warning|temperature|percentage_used|available_spare'

# Проверка статуса RAID (если используется)
cat /proc/mdstat
# → [UUU_U] — символ "_" указывает на выпавший диск
```

**Ожидаемый результат:** Выявлены физические ошибки (bad sectors, failing controller, overheating) или проблемы с RAID.

## Валидация диагноза

Перед применением исправлений подтвердите причину деградации:

1. **Корреляция PSI и iostat**: Высокий `await` должен совпадать с ростом `some avg10` в `/proc/pressure/io`. Если PSI низкий, а `await` высокий — проверяйте внешний троттлинг (hypervisor, SAN) или инструментальные погрешности.
2. **Изоляция контейнера**: В cgroups v2 проверьте `io.stat` конкретного slice. В cgroups v1 проверьте `blkio.throttle.io_service_bytes`.
3. **Проверка оборудования**: Запустите `smartctl -H` (быстрая оценка здоровья) и `dmesg` перед заменой диска.
4. **Повторяемость**: Убедитесь, что задержка воспроизводится при повторной диагностике. Одиночные всплески могут быть вызваны фоновыми задачами ОС.

## Автоматизация и мониторинг

### Сбор данных для исторического анализа

```bash
# Сохранение данных iostat в JSON (sysstat >= 12)
iostat -dx -o JSON 2 300 > /var/log/iostat_$(date +%Y%m%d).json

# Запись расширенной статистики в текстовый файл
iostat -dx 2 60 > /var/log/iostat_$(date +%Y%m%d).txt

# Парсинг JSON через jq: извлечение await для устройства sda
cat /var/log/iostat_*.json | jq -r '.sysstat.hosts[].statistics[].disk[] | select(.device=="sda") | [.await] | @tsv'
```

### Prometheus alerts (node_exporter)

```yaml
# Высокое давление на I/O
- alert: HighIOStall
  expr: avg by(instance) (rate(node_pressure_io_waiting_seconds_total[5m])) > 0.1
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Высокое I/O давление на {{ $labels.instance }}"
    description: "Процессы ждут I/O {{ $value | humanizePercentage }} времени за 5 минут. Проверьте await и avgqu-sz в iostat."

# Высокая задержка диска
- alert: HighDiskLatency
  expr: node_disk_io_time_weighted_seconds_total{device!=""} > 0.05
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Высокая задержка диска {{ $labels.device }} на {{ $labels.instance }}"
```

### Python-парсинг iostat для автоматизации

```python
import json, subprocess

result = subprocess.run(['iostat', '-dxo', 'JSON', '1', '3'], capture_output=True, text=True)
data = json.loads(result.stdout)

for stat in data['sysstat']['hosts'][0]['statistics']:
    for disk in stat['disk']:
        if disk['await'] > 20:
            print(f"ALERT: {disk['device']} await={disk['await']}ms")
        if float(disk['%util']) > 90 and disk['aqu_sz'] < 2:
            print(f"WARNING: {disk['device']} высокий %util при низкой очереди — возможно, SSD/NVMe параллельная обработка")
```

## Ограничения и особые случаи

### Многоядерные системы

`%iowait` — системная метрика, распределенная по всем ядрам. На 32-ядерном сервере `%wa = 3%` может означать, что одно ядро простаивает 100% времени. Используйте PSI или `mpstat -P ALL 1` для точного анализа.

### Виртуализация (KVM, VMware, Xen)

- `%steal` в `iostat`/`mpstat` показывает время, «украденное» гипервизором. Постоянный `%steal > 5%` — признак overselling или noisy neighbor.
- Паравиртуализированные драйверы (`virtio-blk`, `vmw_pvscsi`) могут кэшировать запросы, скрывая реальную задержку от гостевой ОС.
- В гипервизорных средах throttling часто применяется на уровне хоста; гость видит только результат.

### cgroups v1 vs v2

- **cgroups v1**: `io.stat` существует только для blkio контроллера. Нет PSI (`io.pressure` отсутствует). Используйте `cat /sys/fs/cgroup/blkio/*/io.stat`.
- **cgroups v2**: `io.pressure` доступен, что позволяет измерять давление на I/O внутри контейнера.
- Внутри контейнера `iotop` видит только процессы этого контейнера.

### Сетевые ФС (NFS, FUSE, CIFS)

- NFS добавляет сетевую задержку, которая в `iotop` выглядит как обычный I/O wait. Используйте `nfsstat -m` и `nfsiostat`.
- FUSE-файловые системы (`sshfs`) блокируют процесс в пользовательском пространстве. Видно по `wchan` (`fuse_dev_read`).
- При зависании NFS-сервера поток writeback уходит в `D-state` на неопределённое время. Единственное решение — `umount -f` или перезагрузка.

### 32-битные системы

На архитектурах, отличных от x86_64, формат `/proc/<pid>/io` остается совместимым, но некоторые eBPF-утилиты могут требовать перекомпиляции.

### SSD и NVMe

- **Write Amplification**: Внутренний GC SSD может увеличивать физическую запись в 3–10 раз относительно логической. `await` может быть низким, но износ носителя ускоряется.
- **SLC-кэш**: Высокий `await` после заполнения SLC-кэша — нормальное поведение consumer SSD. Ориентируйтесь на P99 latency, а не на средние значения.
- **Flush-штормы**: Высокое `f_await` при низком общем `await` указывает на отсутствие PLP (Power Loss Protection).

### RAID и шифрование

- **Hardware RAID**: Контроллер скрывает отдельные диски. `iostat` показывает только виртуальное устройство. Для диагностики используйте утилиты вендора (`megacli`, `hpacucli`).
- **dm-crypt (LUKS)**: Шифрование добавляет overhead на CPU. При высокой нагрузке процесс `dm-crypt` может потреблять CPU, маскируя проблему как CPU-bound.

## Быстрая справка: симптом → инструмент

| Симптом | Инструмент | Файл |
| :--- | :--- | :--- |
| `await` > 20 мс (HDD) или > 1 мс (SSD) | `iostat -xz 1` | → `io_scheduler_selection.md` |
| `%util` > 80%, но нет D-state | `iostat -xz 1`, `vmstat 1` | → `direct_vs_buffered_io.md` |
| `si`/`so` > 0 в `vmstat` | `vmstat 1 5`, `free -h` | → `swap_io_impact.md` |
| `Dirty` > 10% RAM | `grep Dirty /proc/meminfo` | → `writeback_tuning.md` |
| Процесс в D-state | `ps -eo pid,state,wchan:30,comm` | → `kworker_flush.md` |
| `aqu-sz` > 2 (среднее) | `iostat -xz 1` | → `io_scheduler_selection.md` |
| `f_await` высокий | `iostat -xz 1`, `smartctl -a /dev/sdX` | → `smartctl_exporter.md` |
| Thin pool data_percent > 80% | `sudo lvs -o data_percent vg/pool` | → `lvm_io_performance.md` |
| RAID rebuild замедляет системы | `cat /proc/mdstat`, `iostat -xz 1` | → `raid_io_impact.md` |
| PostgreSQL в swap | `cat /proc/<pid>/status \| grep VmSwap` | → `swap_io_impact.md` |
| MySQL с O_DIRECT | `SHOW VARIABLES LIKE 'innodb_flush_method'` | → `direct_vs_buffered_io.md` |
| TRIM не освобождает thin pool | `fstrim -v /mountpoint`, `sudo lvs -o data_percent` | → `fstrim_ssd_maintenance.md` |
| NVMe: scheduler настроен неверно | `cat /sys/block/nvme*/queue/scheduler` | → `io_scheduler_selection.md` |
| Двойное кэширование (DB) | `SHOW shared_buffers` / `innodb_buffer_pool_size` | → `direct_vs_buffered_io.md` |
| Высокий I/O в контейнере | `cat /sys/fs/cgroup/*/io.stat`, `docker stats` | → `lvm_io_performance.md` |
| Деградация RAID 5/6 | `cat /proc/mdstat`, `smartctl -a /dev/sdX` | → `raid_io_impact.md` |
| HDD: низкий throughput | `iostat -xz 1`, `hdparm -t /dev/sdX` | → `io_scheduler_selection.md` |
| Высокая задержка при записи | `biolatency-bpfcc -D`, `iostat -xz 1` | → `direct_vs_buffered_io.md` |
| SMART предупреждает о здоровье | `sudo smartctl -H /dev/sdX`, `smartd` | → `disk_health_check.md` |

## См. также

- [Низкий iowait при высокой задержке](./iowait_and_latency.md) — разбор ложных показателей CPU.
- [Невидимый ввод-вывод](./invisible_io.md) — причины, по которым `iotop` может не показывать нагрузку (io_uring, writeback, lock contention).
- [Роль kworker и процессов writeback](./kworker_flush.md) — детализация фоновой записи.
- [I/O Scheduler: выбор и настройка](./io_scheduler_selection.md) — выбор планировщика для типов устройств и нагрузок.
- [RAID: write penalty и влияние на I/O](./raid_io_impact.md) — write penalty, stripe size, rebuild, мониторинг.
- [LVM: производительность I/O](./lvm_io_performance.md) — thin provisioning, COW, stripe vs linear, TRIM.
- [Swap и влияние на Disk I/O](./swap_io_impact.md) — swappiness, swap thrashing, THP, zswap/zram.
- [Direct I/O vs Buffered I/O](./direct_vs_buffered_io.md) — O_DIRECT, O_SYNC, double buffering, настройка для БД.
- [SAR: статистика производительности](../../../../Diagnostics/Performance/sar.md) — сбор исторических данных I/O.
- [SMART: мониторинг здоровья дисков](../../../../Diagnostics/Hardware/smartctl/smartctl_exporter.md) — автоматизация сбора SMART-метрик.
- [fstrim: обслуживание SSD](../../../../SystemAdministration/fstrim_ssd_maintenance.md) — TRIM для поддержания производительности.
