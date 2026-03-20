# Сценарии диагностики дискового I/O

## Определения

- **I/O Wait (`wa`)**: Процент времени, в течение которого процессор простаивал, ожидая завершения операций ввода-вывода.
- **Uninterruptible Sleep (D-state)**: Состояние процесса, ожидающего завершения I/O операции.
- **Dirty Pages (Грязные страницы)**: Страницы в оперативной памяти (page cache), которые были изменены, но ещё не записаны на диск.
- **Direct I/O**: Операции чтения/записи, минуя page cache ядра.

## Практические сценарии

### Сценарий 1: Высокий I/O wait, `iotop` пуст

**Симптомы:** `top` показывает `wa > 50%`, `iotop -o` не показывает активных процессов.

**Диагностика:**

```bash
# Проверить dirty pages
cat /proc/meminfo | grep -E "Dirty|Writeback"

# Запустить fatrace для поиска писателей
sudo fatrace | grep -E "WRITE|OPEN"

# Проверить kworker потоки
ps aux | grep kworker
```

**Решение:**

```bash
# Временно уменьшить пороги dirty pages (меньше залпы, но чаще)
sudo sysctl -w vm.dirty_ratio=10
sudo sysctl -w vm.dirty_background_ratio=5
sudo sysctl -w vm.dirty_writeback_centisecs=300

# Постоянно: добавить в /etc/sysctl.conf
cat >> /etc/sysctl.conf << EOF
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5
vm.dirty_expire_centisecs = 3000
vm.dirty_writeback_centisecs = 300
EOF
```

### Сценарий 2: Поиск процесса с кумулятивным I/O

**Проблема:** `iotop` и `pidstat` не показывают процесс, но диск загружен.

**Решение:** Использовать `/proc/<pid>/io` — кумулятивная статистика с момента старта процесса.

```bash
# Просмотр кумулятивной статистики для процесса
cat /proc/<pid>/io

# Поиск процессов с наибольшим кумулятивным I/O
for pid in /proc/[0-9]*; do
    if [ -r "$pid/io" ]; then
        echo "=== $pid ==="
        grep -E "read_bytes|write_bytes" "$pid/io" 2>/dev/null
    fi
done | sort -t: -k2 -rn | head -20
```

### Сценарий 3: Детальная трассировка I/O запросов

**Инструмент:** `biosnoop` (требует `bcc-tools`).

```bash
# Установить bcc-tools
sudo apt install bpfcc-tools    # Debian/Ubuntu
sudo yum install bcc-tools      # RHEL/CentOS

# Запустить biosnoop
sudo biosnoop
```

**Вывод:**
```
TIME(s)        COMM           PID    DISK    T  SECTOR    BYTES   LAT(ms)
12345.678901   postgres       1234   sda     W  123456    4096    12.34
12345.679012   kworker/u8:0   56     sda     W  123457    8192    8.21
```

**Преимущества перед `iotop`:**

- Показывает **каждый** I/O запрос, а не сэмпл
- Отображает задержку (latency) каждой операции
- Видны ядерные потоки flush

### Сценарий 4: Альтернатива — `blktrace`

**Когда использовать:** `biosnoop` недоступен, нужна низкоуровневая трассировка.

```bash
# Записать трассировку на 30 секунд
sudo blktrace -d /dev/sda -o trace -w 30

# Воспроизвести и проанализировать
sudo blkparse trace | head -100

# Или в реальном времени
sudo blktrace -d /dev/sda | blkparse -i -
```

**Типы событий:**

- `D` — Discard (TRIM)
- `F` — Flush
- `M` — Metadata
- `Q` — Request queued
- `C` — Request completed
- `R` — Read
- `W` — Write
- `S` — Sync
- `U` — Unplug

### Сценарий 5: Мониторинг файловых операций с `fatrace`

**Когда использовать:** Нужно узнать, какие файлы читаются/пишутся.

```bash
# Установить
sudo apt install fatrace     # Debian/Ubuntu
sudo yum install fatrace     # RHEL/CentOS

# Запустить
sudo fatrace

# Фильтровать по типу операции
sudo fatrace | grep -E "WRITE|OPEN"

# Только для конкретной директории
sudo fatrace | grep "/var/log"
```

**Вывод:**
```
chrome:1234   [U] /home/user/Downloads/file.zip:WRITE
rsync:5678    [O] /var/log/syslog:OPEN
postgres:9012 [W] /var/lib/postgresql/data/base/12345/67890:WRITE
```

### Сценарий 6: Проверка на ошибки диска

**Команды:**

```bash
# Последние сообщения ядера об ошибках
dmesg | grep -iE "error|timeout|reset|blocked"

# Журнал ядра за последнее время
journalctl -k --since "1 hour ago" | grep -iE "i/o|block|sda"

# SMART-статус диска
sudo smartctl -H /dev/sda

# Полная SMART-информация
sudo smartctl -a /dev/sda
```

**Критичные сообщения:**

- `"I/O error"` — аппаратная ошибка
- `"task blocked for more than 120s"` — процесс ждёт I/O слишком долго
- `"sector read error"` — плохие сектора
- `"reset"` — контроллер диска перезагружается

### Сценарий 7: Диагностика cgroup I/O лимитов

**Когда использовать:** Docker/Kubernetes, systemd unit с ограничениями.

```bash
# Для systemd
systemctl show <unit> | grep -i io

# Просмотр статистики cgroup v2
cat /sys/fs/cgroup/system.slice/<unit>.service/io.stat

# Ограничения
cat /sys/fs/cgroup/system.slice/<unit>.service/io.max
cat /sys/fs/cgroup/system.slice/<unit>.service/io.bfq.weight
```

## Дополнительная информация

### См. также

- [Диагностический чеклист I/O](./diagnostic_checklist.md)
- [Роль kworker/u*:flush-*](./kworker_flush.md)
- [Настройка writeback](./writeback_tuning.md)
- [`biosnoop` и eBPF инструменты](../../../Tools/bcc_bpf_tools.md)
- [SMART: проверка здоровья диска](../Hardware/smartctl/disk_health_check.md)
