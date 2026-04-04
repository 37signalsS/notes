# Невидимый I/O: почему iotop может не показывать виновника

## Definitions

- **Uninterruptible Sleep (D-state)**: Состояние процесса, ожидающего завершения I/O операции. Процесс не может быть прерван сигналами, включая `SIGKILL`.
- **Direct I/O**: Операции чтения/записи, минуя page cache ядра.
- **Block I/O**: Операции на уровне блочного устройства, видимые ядру.

## Basic Concepts

`iotop` снимает **моментальные снимки** состояния процессов. Процесс попадает в отчёт только если находится в состоянии I/O ожидания **в момент сэмпла**.

### Причины "невидимого" I/O

| Причина | Механизм | Как детектить |
| :--- | :--- | :--- |
| **Низкий iowait при высокой латентности** | CPU не ждёт активно, очередь на диске растёт | `iostat -x` (await, avgqu-sz) |
| **Короткие всплески** | Процесс не в D-state во время сэмпла | `pidstat -d 1`, `fatrace` |
| **Ядерные потоки (kworker)** | Запись от имени всех процессов | `biosnoop`, `/proc/meminfo` |
| **Direct I/O** | Минует page cache | `/proc/<pid>/io` |
| **Удалённые файлы** | Файл удалён, но открыт | `lsof +L1` |
| **cgroup limits** | Ограничение I/O на уровне cgroup | `/sys/fs/cgroup/*/io.stat` |
| **NFS/CIFS** | Сетевое хранилище | `nfsstat -m`, `mount` |
| **Swap I/O** | Страницы выгружаются в swap | `vmstat 1` (si/so) |
| **fsync/fdatasync** | Синхронный сброс на диск | `strace -e fsync -p <pid>` |

## Practical Scenarios

### Диагностика невидимого I/O

```bash
# Проверка задержек диска (альтернатива iowait)
iostat -x 1

# Поиск процессов с короткими всплесками I/O
pidstat -d 1

# Мониторинг файловых операций в реальном времени
sudo fatrace | head -50

# Проверка на открытые удалённые файлы
lsof +L1

# Детальная трассировка каждого I/O запроса
sudo biosnoop | head -50

# Статистика по cgroup
cat /sys/fs/cgroup/*/io.stat

# Проверка swap I/O
vmstat 1

# Трассировка системных вызовов fsync
strace -e fsync -p <pid>
```

## Additional Information

Смежные темы: [Низкий iowait при высокой задержке](./iowait_and_latency.md), [Роль kworker/u*:flush-*](./kworker_flush.md), [Диагностический чеклист I/O](./diagnostic_checklist.md), [`iotop` — подробное описание](../Filesystem/iotop.md), [`pidstat` — подробное описание](../Processes/pidstat.md).
