# io_uring — асинхронный ввод-вывод нового поколения

## Определения

**`io_uring`** — это высокопроизводительный асинхронный интерфейс ядра Linux, предназначенный для выполнения операций ввода-вывода (I/O) и системных вызовов с минимальными накладными расходами. Представленный в ядре 5.1, он радикально меняет модель взаимодействия приложений с ядром, заменяя синхронные блокирующие вызовы механизмом разделяемых кольцевых буферов. Для сравнения с традиционными интерфейсами I/O multiplexing (select, poll, epoll) см. раздел [**I/O Multiplexing: select, poll, epoll**](../processes/epoll_io_multiplexing.md).

В современных реализациях (2024–2026 гг.) `io_uring` перерос рамки дискового I/O и стал универсальной средой асинхронного исполнения, поддерживающей практически все системные вызовы: от сетевых операций до управления процессами и межпроцессного взаимодействия (IPC).

- **Submission Queue Entry (SQE)**: Структура данных, описывающая один запрос. Приложение заполняет поля опкода, файлового дескриптора, адресов буферов и флагов.
- **Completion Queue Event (CQE)**: Структура данных, возвращаемая ядром после выполнения операции. Содержит результат (`res`), опкод и флаги (например, `IORING_CQE_F_MORE` для multishot).
- **Ring buffer**: Разделяемая область памяти между userspace и kernel, использующая массив фиксированного размера с кольцевым указателем.
- **io_uring_enter()**: Системный вызов, который либо передает управление ядру для выполнения запросов, либо ожидает завершения операций в CQ.
- **IORING_SETUP_SQPOLL**: Флаг инициализации, при котором ядро создает отдельный поток для опроса Submission Queue.

## Жизненный цикл запроса

1. **Подготовка SQE**: Приложение получает указатель на свободный SQE через `io_uring_get_sqe()`. Структура SQE заполняется: опкод операции (`IORING_OP_READ`, `IORING_OP_WRITE`, `IORING_OP_ACCEPT` и т.д.), указатели на пользовательские буферы, файловый дескриптор и флаги.
2. **Дублирование буферов (для DMA)**: Если буферы не зарегистрированы заранее, ядро делает внутренний `pin` страниц памяти, чтобы DMA-контроллер мог безопасно к ним обращаться.
3. **Подача запроса**: Приложение вызывает `io_uring_submit()` (или `io_uring_enter()` с флагом `IORING_ENTER_GETEVENTS`). В режиме SQPOLL запрос просто попадает в разделяемую память, и ядерный поток подбирает его автоматически.
4. **Выполнение в ядре**: Ядро выполняет операцию (дисковую, сетевую или другую). Для сетевых операций задействуется полный стек TCP/IP; для дисковых — через `bio`-слой и планировщик I/O.
5. **Запись CQE**: После завершения ядро помещает CQE в Completion Queue. При последовательном выполнении запросов порядок CQE может отличаться от порядка SQE (особенно при использовании `IOSQE_IO_DRAIN` или multishot).
6. **Извлечение результата**: Приложение получает CQE через `io_uring_wait_cqe()` или `io_uring_peek_cqe()`. Поле `cqe->res` содержит результат (положительное — байты, отрицательное — errno). Если установлен флаг `IORING_CQE_F_MORE`, multishot-операция генерирует следующий CQE автоматически.

## Архитектура кольцевых буферов

`io_uring` использует два кольцевых буфера (rings), расположенных в разделяемой памяти (shared memory) между приложением и ядром. Это исключает необходимость копирования данных запроса при каждом системном вызове.

1.  **Submission Queue (SQ)**: Очередь запросов. Приложение помещает сюда записи **SQE (Submission Queue Entry)**, описывающие операцию (чтение, запись, `accept`, `send` и т.д.).
2.  **Completion Queue (CQ)**: Очередь завершений. Ядро помещает сюда результаты **CQE (Completion Queue Event)** после выполнения операции.

### Организация памяти и cache line

- SQ и CQ выравниваются по границе кэш-линии (обычно 64 байта), чтобы избежать false sharing между ядрами CPU.
- Размеры колец задаются при инициализации и влияют на потребление памяти: `entries * sizeof(struct io_uring_sqe)` для SQ и аналогично для CQ.
- Ядро использует memory barriers для синхронизации изменений указателей между CPU приложения и ядерным потоком. Приложение должно использовать `io_uring_smp_store_release()` и `io_uring_smp_load_acquire()` при ручном обновлении указателей (обычно это скрыто внутри `liburing`).

**Режимы работы:**
- **Стандартный**: Приложение заполняет SQ и вызывает `io_uring_enter()` для уведомления ядра.
- **SQPOLL (Submission Queue Polling)**: Ядро запускает отдельный поток в контексте ядра для опроса SQ. В этом режиме приложение может отправлять запросы вообще без выполнения системных вызовов, просто записывая данные в память.

## Ключевые возможности и инновации (2024–2026)

*   **Zero-Copy Networking (ZC)**:
    - **`SEND_ZC`**: Позволяет сетевой карте считывать данные напрямую из памяти приложения (через DMA), минуя буферы ядра.
    - **`RECV_ZC` (ZCRX)**: (С ядра 6.15/7.1) Прямая доставка полезной нагрузки из сети в буферы приложения. Требует поддержки со стороны NIC (Header/Data split).
*   **Multishot-режим**: Позволяет одной записи в SQ генерировать несколько событий в CQ.
    - `Multishot Accept`: Одна отправка `accept` возвращает CQE для каждого нового входящего соединения.
    - `Multishot Receive`: Позволяет сокету непрерывно принимать данные в пул буферов без переподачи запроса.
*   **Ring Resizing**: (С ядра 6.13) Возможность изменять размер колец SQ/CQ динамически, без необходимости полного пересоздания интерфейса.
*   **Registered Buffers & Files**: Предварительная регистрация ресурсов в ядре ускоряет выполнение за счет исключения постоянного маппинга страниц и поиска файловых дескрипторов в таблицах процесса.

## Сравнение механизмов I/O

| Характеристика | `read/write` (Sync) | `epoll` | `libaio` | `io_uring` |
| :--- | :--- | :--- | :--- | :--- |
| **Асинхронность** | Нет | Для сети — да | Только Direct I/O | **Полная** |
| **Переключение контекста** | На каждый вызов | На группу | На группу | **Минимально (или 0)** |
| **Копирование данных** | Да | Да | Да | **Zero-Copy** (6.x+) |
| **Сложность** | Низкая | Средняя | Средняя | Высокая |

## Ядерные параметры и ограничения

### Параметры загрузки ядра (boot parameters)

- **`io_uring.disabled=`**: Глобальное управление доступностью интерфейса.
    - `0` — разрешено всем (по умолчанию).
    - `1` — разрешено только привилегированным процессам (`CAP_SYS_ADMIN` или членам группы `kernel.io_uring_group`).
    - `2` — полностью запрещено.

    ```bash
    # /etc/default/grub
    GRUB_CMDLINE_LINUX_DEFAULT="... io_uring.disabled=1"
    update-grub
    ```

### Sysctl параметры

- **`kernel.io_uring_disabled`**: Эквивалент boot-параметра, управляемый через `/proc/sys`. Рекомендуется использовать `sysctl.d` для персистентности.

    ```bash
    # Проверка текущего значения
    sysctl kernel.io_uring_disabled

    # Временное отключение
    echo 1 | sudo tee /proc/sys/kernel/io_uring_disabled
    ```

- **`fs.aio-max-nr`** и **`fs.aio-nr`**: Глобальные лимиты на количество одновременно активных асинхронных операций. Хотя `io_uring` не использует POSIX AIO, эти параметры влияют на совместимость при использовании libaio параллельно.

- **`vm.max_map_count`**: При использовании больших колец или предварительно зарегистрированных буферов может потребоваться увеличение этого значения.

### Ограничения ресурсов

- Размер кольца ограничен `UINT32_MAX` (теоретически), но на практике полезный лимит — 1M–4M записей из-за потребления памяти и времени инициализации.
- Количество зарегистрированных файлов через `IORING_REGISTER_FILES` ограничено `RLIMIT_NOFILE` (если не установлен `IORING_SETUP_CLAMP`).
- В режиме SQPOLL ядерный поток потребляет CPU даже в простое. Для энергоэффективных систем лучше использовать стандартный режим с `io_uring_enter()`.

## Тюнинг и конфигурация

### Персистентная конфигурация через sysctl.d

```bash
# /etc/sysctl.d/99-io-uring.conf
kernel.io_uring_disabled = 0
```

Применение:
```bash
sudo sysctl --system
# → result: Applying /etc/sysctl.d/99-io-uring.conf ...
```

### Профили настройки

**Production (высоконагруженные серверы):**
```bash
# /etc/sysctl.d/99-io-uring-tuning.conf
kernel.io_uring_disabled = 0
vm.max_map_count = 524288
fs.file-max = 2000000
```

**Виртуализация (KVM/VMware):**
- Внутри ВМ используйте `virtio-scsi` или `virtio-blk` с `queue_size=256`.
- В качестве планировщика I/O гостевой ОС всегда `none` (см. [Планировщики ввода-вывода](./io_schedulers.md)).
- Избегайте SQPOLL в сильно oversubscribe-средах: поток будет конкурировать за CPU с другими ВМ.

**RT-системы:**
- Отключите SQPOLL или привяжите его к выделенному CPU через `sched_setaffinity`.
- Используйте `IORING_SETUP_IOPOLL` для активного опроса устройств вместо прерываний.
- Предпочитайте `IORING_SETUP_SQ_AFF` для привязки кольца к конкретному ядру.

**Development / Staging:**
- Полное отключение для изоляции:
    ```bash
    echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled
    ```

## Интеграция с systemd и cgroups

### systemd-сервисы

Начиная с systemd 250+, юниты могут явно запрашивать или запрещать `io_uring` через директиву `IOUring=`:

```ini
# /etc/systemd/system/nginx.service.d/override.conf
[Service]
IOUring=yes
IOWeight=50
IOSchedulingClass=best-effort
```

- **`IOUring=yes`**: Разрешает сервису использовать `io_uring`. По умолчанию — `auto` (разрешено, если `io_uring_disabled=0`).
- **`IOWeight=`**: Относительный вес в группе I/O cgroup (аналог `blkio.weight` для cgroups v1).
- **`IOSchedulingClass=`**: Класс планирования I/O (`real-time`, `best-effort`, `idle`).

Для принудительного отключения в контейнерах или песочницах:
```ini
[Service]
IOUring=no
```

### cgroups v2

cgroups v2 предоставляют единую иерархию для контроля ресурсов. Параметры I/O:

```bash
# Установка лимита скорости записи для группы
echo "wbps=10485760" | sudo tee /sys/fs/cgroup/system.slice/nginx.service/io.max

# Ограничение по задержке (требует поддержки в драйвере/устройстве)
echo "rt=125000" | sudo tee /sys/fs/cgroup/system.slice/nginx.service/io.latency

# Просмотр текущего состояния
cat /sys/fs/cgroup/system.slice/nginx.service/io.stat
# → sda 1048576 0 0 0 0 0 0 0 0
```

**Примечание:** `io_uring` генерирует запросы через стандартный блочный слой, поэтому `io.max` и `io.latency` cgroup v2 применяются к ним корректно. Исключение составляют только операции, не проходящие через блочный слой (чистый `SEND_ZC`/`RECV_ZC` для сетевых сокетов).

## Практические сценарии

### Системы с экстремальной нагрузкой

*   **Базы данных (ScyllaDB, PostgreSQL, Dragonfly)**: Использование `io_uring` с `SQPOLL` позволяет достигать 10M+ IOPS на современных NVMe-накопителях. PostgreSQL 18 поддерживает `io_uring` нативно через `io_method = io_uring` (сборка с `--with-liburing`, ядро 5.6+); при этом PostgreSQL читает через kernel page cache, а не в обход него — см. [Асинхронный ввод-вывод в PostgreSQL](../../../Databases/PostgreSQL/Operations/async_io.md).
*   **Сетевые прокси (QEMU, Nginx, Envoy)**: Асинхронная обработка сетевых соединений без накладных расходов `epoll` и лишних переключений контекста.
*   **User-space драйверы (ublk)**: Реализация блочных устройств в пространстве пользователя, не уступающих по производительности нативным драйверам ядра.

### Конфигурации для типовых рабочих нагрузок

**Базы данных (PostgreSQL / MySQL):**
- `O_DIRECT` (`libaio` или `io_uring` с `direct=1`) обходит page cache — применимо к движкам, поддерживающим direct I/O (например, MySQL InnoDB); PostgreSQL работает через buffered I/O.
- Зарегистрируйте файлы данных через `IORING_REGISTER_FILES` для снижения накладных расходов на поиск FD.
- Настройте `shared_buffers` и `work_mem` с учетом того, что PostgreSQL при `io_method = io_uring` читает через kernel page cache (buffered I/O), а не в обход него.
- Отключите `SQPOLL` для интерактивных транзакционных нагрузок, где важна низкая задержка при малой глубине очереди.

**Высоконагруженные веб-серверы:**
- Используйте `Multishot Accept` с пулом обработчиков.
- Предварительно регистрируйте пул буферов через `io_uring_register_buf_ring` для multishot receive.
- Отключайте `TCP_NODELAY` на уровне приложения, если пакетизация данных естественна для протокола.

**Журналирование и агрегация логов:**
- Для последовательной записи логов используйте `IORING_OP_WRITE_FIXED` с заранее зарегистрированным буфером.
- Размер блока должен соответствовать `recordsize` файловой системы (обычно 4K–128K).
- Избегайте `SQPOLL` — фоновые операции записи не требуют минимальной задержки, но важна энергоэффективность.

### Безопасность и ограничение доступа

Мощность `io_uring` создает широкую поверхность атаки, поэтому в 2025–2026 гг. стандартом стал жесткий контроль интерфейса.

*   **Ограничение через sysctl**:
    ```bash
    # /etc/sysctl.d/99-io-uring.conf
    # 0 - разрешено всем
    # 1 - разрешено только CAP_SYS_ADMIN (или группе kernel.io_uring_group)
    # 2 - полностью запрещено глобально
    kernel.io_uring_disabled = 1
    ```
*   **BPF-фильтрация опкодов**: (С ядра 6.12) Приложение может прикрепить BPF-фильтр к самому кольцу. Это позволяет ограничить список разрешенных операций (например, разрешить только `READ`/`WRITE` и запретить `OPENAT2`), создавая песочницу внутри `io_uring`.
*   **Seccomp**: Современные профили Docker и Kubernetes по умолчанию блокируют `io_uring` для непривилегированных контейнеров.

## Диагностика и мониторинг

### Просмотр состояния через /proc и /sys

```bash
# Проверка, включен ли io_uring в ядре
grep IO_URING /boot/config-$(uname -r)
# → CONFIG_IO_URING=y

# Глобальный лимит и использование
cat /proc/sys/fs/io_uring
# (формат зависит от версии ядра; обычно отсутствует как отдельный файл)

# Просмотр открытых io_uring-дескрипторов процесса
ls -la /proc/<PID>/fd | grep io_uring
# → /dev/null или anon_inode:io_uring

# Статистика процесса (общий I/O)
cat /proc/<PID>/io
# → rchar: 123456789, wchar: 987654321, syscr: 12345, syscw: 54321, ...
```

### Мониторинг через bpftrace

```bash
# Частота и длительность операций io_uring по опкодам
sudo bpftrace -e 'tracepoint:io_uring:io_uring_complete { @[args->opcode] = hist(args->res); }'

# Подсчет запросов, отправленных процессом
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_io_uring_enter { @[comm] = count(); }'

# Задержка между подачей и завершением
sudo bpftrace -e '
tracepoint:io_uring:io_uring_submit_sqe { @start[args->req] = nsecs; }
tracepoint:io_uring:io_uring_complete {
    $latency = nsecs - @start[args->req];
    @latency = hist($latency);
    delete(@start[args->req]);
}'
```

### Диагностика производительности

*   **`fio`**: Лучший инструмент для бенчмаркинга. Подробности см. в [Тестирование через fio](../../Diagnostics/Filesystem/fio.md).
    ```bash
    fio --name=test --ioengine=io_uring --iodepth=32 --direct=1 ...
    ```
*   **`perf`**: Профилирование накладных расходов.
    ```bash
    sudo perf stat -e syscalls:sys_enter_io_uring_enter,syscalls:sys_exit_io_uring_enter -a sleep 5
    ```

### Проактивный мониторинг

Для отслеживания `io_uring` в production добавьте в Prometheus Node Exporter конфигурацию сбора метрик через `bpftrace` или `systemtap`, либо используйте готовые eBPF-инструменты:

```bash
# Пример с bpftrace для вывода в формате, пригодном для парсинга
sudo bpftrace -e '
tracepoint:io_uring:io_uring_complete /args->res < 0/ {
    @errors[comm, args->res] = count();
}
' --output json
```

## Взаимодействие с подсистемами хранения

### Планировщики I/O и blk-mq

`io_uring` взаимодействует с планировщиком через стандартный блочный слой (`bio`). См. [Планировщики ввода-вывода](./io_schedulers.md) для выбора планировщика.

**Важно:** Для NVMe всегда используйте планировщик `none`. Дополнительные планировщики добавляют задержку, превышающую время отклика накопителя. Для SATA SSD используйте `mq-deadline` или `kyber`.

### NVMe и io_uring_cmd

Ядро 5.19+ поддерживает операцию `IORING_OP_URING_CMD`, позволяющую передавать команды напрямую NVMe-контроллеру из userspace (аналог `nvme_passthru`). Это исключает трансляцию блочного слоя и снижает задержку на 30–40%.

## Troubleshooting

### Типичные ошибки

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `IORING_SETUP_SQPOLL` возвращает `EINVAL` | Ядро собрано без `CONFIG_IO_URING` или версия < 5.1 | Обновите ядро; проверьте `grep CONFIG_IO_URING /boot/config-$(uname -r)` |
| Высокое потребление CPU при SQPOLL | Поток опроса SQ не засыпает, высокая частота опроса | Уменьшите `sq_thread_idle` через `io_uring_set_options()` или переключитесь на стандартный режим |
| `ECANCELED` в CQE | Запрос был отменен (например, при закрытии кольца) | Обработайте как штатное завершение; проверьте порядок завершения приложения |
| `ENOTSUP` при использовании `IORING_REGISTER_BUFFERS` | Ядро < 5.7 или недостаточно памяти | Используйте `IORING_REGISTER_BUFFERS` вместо устаревшего `IORING_SETUP_SQ_AFF` |
| `EAGAIN` при `io_uring_enter()` | Глубина очереди переполнена или кольцо не готово | Увеличьте `entries` при инициализации; проверьте `io_uring_submit()` |
| Нулевая или низкая производительность на NVMe | Используется планировщик `mq-deadline`/`bfq` или включен `libaio` fallback | Переключите планировщик на `none`; убедитесь, что `io_uring` действительно используется (strace) |
| Потеря пакетов в сетевом multishot | Буферы недостаточного размера или нет `IOSQE_BUFFER_SELECT` | Увеличьте размер буферного пула; проверьте флаги SQE |

### Диагностика с помощью strace

```bash
# Проверка, что процесс действительно использует io_uring
strace -e io_uring_enter,io_uring_register -p <PID>
# → io_uring_enter(4, 0, 0, NULL, NULL) = 0
```

### Анализ задержек через perf

```bash
sudo perf record -e io_uring:io_uring_complete -a sleep 10
sudo perf report --sort comm,pid
```

### Проверка использования через bpftrace (для невидимого I/O)

См. также [Невидимый ввод-вывод: почему iotop может не показывать виновника нагрузки](../../Diagnostics/Performance/DiskIO/invisible_io.md).

```bash
# Трассировка io_uring, если iotop не показывает активность
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_io_uring_enter { @[comm] = count(); }'
```

## Подсистемы хранения и ядро

### Взаимодействие с I/O планировщиками

`io_uring` использует стандартный путь `bio` → планировщик → драйвер устройства. Выбор планировщика влияет на задержку:

- **NVMe**: `none` (см. [Планировщики ввода-вывода](./io_schedulers.md))
- **SATA SSD**: `mq-deadline` или `kyber`
- **HDD**: `bfq` для интерактивности, но `io_uring` с `O_DIRECT` минимизирует влияние планировщика

### Дополнительные параметры настройки NVMe

```bash
# Проверка поддержки Hybrid Polling (снижает задержку на NVMe)
cat /sys/block/nvme0n1/queue/io_poll

# Включение опроса (если поддерживается драйвером)
echo 1 | sudo tee /sys/block/nvme0n1/queue/io_poll

# Увеличение глубины очереди
echo 1024 | sudo tee /sys/block/nvme0n1/queue/nr_requests
```

## Практические сценарии (расширенные)

### Бенчмаркинг и валидация

Для тестирования используйте `fio` с движком `io_uring`:

```bash
# Последовательная запись 1M блоков
fio --name=seq_write --rw=write --bs=1M --size=10G --filename=/dev/nvme0n1 \
    --ioengine=io_uring --direct=1 --group_reporting --numjobs=1

# Случайное чтение 4K с глубиной очереди 64
fio --name=rand_read --rw=randread --bs=4k --size=4G --filename=./testfile \
    --ioengine=io_uring --direct=1 --iodepth=64 --numjobs=4 --runtime=60 --time_based
```

Подробнее о параметрах и интерпретации результатов: [Тестирование через fio](../../Diagnostics/Filesystem/fio.md).

### Безопасность и ограничение доступа

*   **Ограничение через sysctl**:
    ```bash
    # /etc/sysctl.d/99-io-uring.conf
    # 0 - разрешено всем
    # 1 - разрешено только CAP_SYS_ADMIN (или группе kernel.io_uring_group)
    # 2 - полностью запрещено глобально
    kernel.io_uring_disabled = 1
    ```
*   **BPF-фильтрация опкодов**: (С ядра 6.12) Приложение может прикрепить BPF-фильтр к самому кольцу. Это позволяет ограничить список разрешенных операций (например, разрешить только `READ`/`WRITE` и запретить `OPENAT2`), создавая песочницу внутри `io_uring`.
*   **Seccomp**: Современные профили Docker и Kubernetes по умолчанию блокируют `io_uring` для непривилегированных контейнеров.

## Настройка и отладка

### Использование liburing

Для разработки рекомендуется использовать библиотеку **`liburing`**, которая скрывает сложности работы с барьерами памяти и обеспечивает стабильный API.

```c
#include <liburing.h>
#include <unistd.h>
#include <fcntl.h>
#include <string.h>
#include <stdio.h>

int main(void) {
    struct io_uring ring;
    struct io_uring_sqe *sqe;
    struct io_uring_cqe *cqe;
    char buf[4096];
    int fd;

    fd = open("/tmp/testfile", O_RDONLY);
    if (fd < 0) { perror("open"); return 1; }

    // Инициализация кольца на 32 запроса с поддержкой SQPOLL
    if (io_uring_queue_init(32, &ring, IORING_SETUP_SQPOLL) < 0) {
        perror("io_uring_queue_init");
        return 1;
    }

    // Получение свободного SQE
    sqe = io_uring_get_sqe(&ring);
    io_uring_prep_read(sqe, fd, buf, sizeof(buf), 0);
    io_uring_sqe_set_data(sqe, buf);

    // Подача запроса
    io_uring_submit(&ring);

    // Ожидание завершения
    io_uring_wait_cqe(&ring, &cqe);
    if (cqe->res > 0) {
        write(STDOUT_FILENO, buf, cqe->res);
    } else if (cqe->res < 0) {
        fprintf(stderr, "Read error: %s\n", strerror(-cqe->res));
    }

    io_uring_cqe_seen(&ring, cqe);
    io_uring_queue_exit(&ring);
    close(fd);
    return 0;
}
```

### Диагностика производительности

*   **`fio`**: Лучший инструмент для бенчмаркинга.
    ```bash
    fio --name=test --ioengine=io_uring --iodepth=32 --direct=1 ...
    ```
*   **`bpftrace`**: Для отслеживания задержек внутри ядра.
    ```bash
    # Отслеживание времени выполнения операций io_uring
    sudo bpftrace -e 'tracepoint:io_uring:io_uring_complete { @[args->opcode] = hist(args->res); }'
    ```

## Дополнительная информация

### Связанные темы

- **Мультиплексирование**: [I/O Multiplexing](../../../Networking/Concepts/io_multiplexing.md) — место `io_uring` в эволюции сетевых интерфейсов.
- **Интерфейсы ядра**: [Интерфейсы ядра Linux](./kernel_interfaces.md) — роль системных вызовов.
- **Планировщики**: [I/O Schedulers](./io_schedulers.md) — взаимодействие с очередями блочных устройств.
- **Бенчмаркинг**: [Тестирование через fio](../../Diagnostics/Filesystem/fio.md).
- **SSD Оптимизация**: [SSD: Burst I/O и деградация](./ssd_burst_io.md).
- **Синхронизация ядра**: [Синхронизация ядра Linux](./kernel_synchronization.md) — барьеры памяти и упорядочение, критичные для разделяемых буферов.
- **Sysctl**: [Sysctl: администрирование ядра через /proc/sys](./sysctl.md) — глобальная настройка параметров.
- **Невидимый I/O**: [Невидимый ввод-вывод](../../Diagnostics/Performance/DiskIO/invisible_io.md) — диагностика нагрузок, скрытых от `iotop`.

### Полезные ресурсы
- [Официальный репозиторий liburing](https://github.com/axboe/liburing)
- [io_uring Documentation (Kernel.org)](https://www.kernel.org/doc/html/latest/block/io_uring.html)
- [Lord of the I/O Rings](https://unixism.net/luring/) — детальное руководство по программированию.
