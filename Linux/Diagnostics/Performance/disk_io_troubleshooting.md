# Диагностика проблем дискового I/O в Linux

> **Примечание:** Данный файл является обзорным. Подробная информация декомпозирована на тематические заметки в директории [DiskIO/](./DiskIO/).

## Определения

- **I/O Wait (`wa`)**: Процент времени, в течение которого процессор простаивал, ожидая завершения операций ввода-вывода. Высокое значение указывает на bottleneck в дисковой подсистеме.
- **Uninterruptible Sleep (D-state)**: Состояние процесса, ожидающего завершения I/O операции. Процесс не может быть прерван сигналами, включая `SIGKILL`.
- **Dirty Pages (Грязные страницы)**: Страницы в оперативной памяти (page cache), которые были изменены, но ещё не записаны на диск.
- **Writeback**: Фоновый процесс записи dirty pages из кэша памяти на диск.
- **`kworker/u*:flush-*`**: Ядерные потоки, отвечающие за сброс dirty pages на блочные устройства (например, `flush-8:0` для `/dev/sda`, где 8:0 — мажорное:минорное число устройства).
- **Direct I/O**: Операции чтения/записи, минуя page cache ядра.
- **Block I/O**: Операции на уровне блочного устройства, видимые ядру.

## Основные концепции

### Ключевые темы диагностики

1. **[Низкий iowait при высокой задержке диска](./DiskIO/iowait_and_latency.md)** — почему `iowait` может вводить в заблуждение и какие метрики смотреть вместо него.

2. **[Невидимый I/O](./DiskIO/invisible_io.md)** — причины, по которым `iotop` может не показывать процесс-виновник.

3. **[Роль kworker/u*:flush-*](./DiskIO/kworker_flush.md)** — механизм работы фоновой записи dirty pages.

## Практические сценарии

### Быстрая диагностика

- **[Диагностический чеклист](./DiskIO/diagnostic_checklist.md)** — последовательность команд для выявления проблем I/O.
- **[Сценарии troubleshooting](./DiskIO/troubleshooting_scenarios.md)** — 7 практических сценариев с решениями.

### Инструменты

- **[Сравнение инструментов](./DiskIO/diagnostic_tools_comparison.md)** — таблица с преимуществами и недостатками каждого инструмента.
- **[Расшифровка /proc/diskstats](./DiskIO/proc_diskstats.md)** — детальное описание полей статистики устройств.

### Настройка

- **[Настройка writeback](./DiskIO/writeback_tuning.md)** — параметры ядра для tuning writeback.

## Дополнительная информация

- **[SSD: Burst I/O и деградация производительности](../../Core/kernel/ssd_burst_io.md)** — архитектура SSD, garbage collection, write amplification, queue depth
- **[I/O Schedulers](../../Core/kernel/io_schedulers.md)** — планировщики ввода-вывода
- **[Оптимизация производительности ФС](../../FileSystems/performance_tuning.md)** — mount-опции, read-ahead, barriers

## Дополнительная информация

Смежные области диагностики: оптимизация памяти ([performance tuning](../../Core/memory/performance_tuning.md), [кэширование и освобождение](../../Core/memory/caching_and_reclaiming.md)), диагностика [файловых систем и дискового пространства](../Filesystem/filesystem_and_disk_space_diagnostics.md), проверка [здоровья диска через SMART](../Hardware/smartctl/disk_health_check.md), [планировщики I/O](../../Core/kernel/io_schedulers.md), диагностика [disk bottleneck в БД](../../../Databases/db_disk_bottleneck_troubleshooting.md).

Инструменты: [`iotop`](../Filesystem/iotop.md), [`iostat`](../Filesystem/iostat.md), [`pidstat`](../Processes/pidstat.md), [`vmstat`](../Memory/vmstat.md).
