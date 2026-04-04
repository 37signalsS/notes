# Быстрый чеклист диагностики дискового I/O

## Определения

- **I/O Wait (`wa`)**: Процент времени, в течение которого CPU простаивает в ожидании завершения операций ввода-вывода. Высокое значение указывает на bottleneck в дисковой подсистеме.
- **Uninterruptible Sleep (D-state)**: Состояние процесса, ожидающего завершения I/O. Не прерывается сигналами, включая `SIGKILL`.
- **Dirty Pages**: Страницы в page cache, изменённые, но ещё не записанные на диск. Подробности — [Настройка writeback](./writeback_tuning.md).
- **Block I/O**: Операции на уровне блочного устройства, видимые ядру. Сравнение инструментов диагностики — [Сравнение инструментов](./diagnostic_tools_comparison.md).

## Основные концепции

### Последовательность диагностики

От общего к частному: обзор системы → статистика устройств → поиск процесса → файловые операции → детальная трассировка → аппаратная проверка.

## Практические сценарии

### Чеклист команд

```bash
# 1. Общий обзор I/O нагрузки на систему
vmstat 1
# Смотри:
#   bi/bo — блоки в секунду (чтение/запись)
#   wa (iowait %) — >20% указывает на bottleneck диска
#   si/so — swap I/O (если >0, нехватка RAM усугубляет I/O)

# 2. Статистика по каждому устройству
iostat -xz 1
# Смотри:
#   %util — утилизация устройства (близко к 100% — перегружен)
#   await — средняя задержка (мс); >20 мс (HDD) или >1 мс (SSD) — проблема
#   avgqu-sz — средняя очередь; >1-2 — запросы копятся
# Подробнее: [iostat — подробное описание](../../Filesystem/iostat.md)

# 3. I/O по процессам (интерактивно)
pidstat -d 1
# Смотри: kB_rd/s, kB_wr/s — чтение/запись по процессам
# Если сумма не сходится с vmstat — процесс не попадает в сэмпл
# Альтернатива: iotop -o (интерактивный, но пропускает короткие всплески)
# Подробнее: [pidstat](../../Processes/pidstat.md), [iotop](../../Filesystem/iotop.md)

# 4. Кто открывает/пишет файлы (все файловые операции)
sudo fatrace | head -50
# Показывает: процесс, PID, тип операции (OPEN, READ, WRITE, CLOSE), путь
# Полезно, когда iotop пуст, но диск загружен

# 5. Детальная трассировка каждого I/O-запроса к диску
sudo biosnoop | head -50
# Требует bcc-tools (bpfcc-tools). Показывает: процесс, PID, диск, тип, сектор, размер, задержку (LAT ms)
# Видны ядерные потоки kworker/u*:flush-* (запись dirty pages)
# Альтернатива: blktrace (сложнее, но полнее)

# 6. Проверка на открытые удалённые файлы (deleted files)
lsof +L1
# Файлы удалены, но удерживаются процессами — занимают место, не видны в df
# Частая причина «исчезновения» дискового пространства

# 7. Статистика I/O по cgroup (Docker, Kubernetes, systemd)
cat /sys/fs/cgroup/*/io.stat
# Для systemd: /sys/fs/cgroup/system.slice/<unit>/io.stat
# Показывает: rbytes, wbytes, rios, wios — байты и операции чтения/записи

# 8. Ошибки диска в ядре
dmesg | tail -100
# Ищи: "I/O error" (аппаратная ошибка), "timeout", "reset", "blocked for more than 120s"
# Также: journalctl -k --since "1 hour ago" | grep -iE "i/o|block"
# Далее: smartctl -a /dev/sdX — SMART-статус

# 9. Dirty pages в памяти — кэш записи
grep -E "Dirty|Writeback" /proc/meminfo
# Высокое значение (сотни МБ–ГБ) — ядро накопило много dirty pages, ждёт сброса
# Пороги: vm.dirty_ratio, vm.dirty_background_ratio
# Настройка: [Настройка writeback](./writeback_tuning.md)

# 10. Детальная статистика устройств (сырые данные, для скриптов)
cat /proc/diskstats
# 14 полей: reads completed, sectors read, time reading, writes completed, sectors written, time writing, io_ticks, weighted_io_ticks
# Поля 13-14 (io_ticks, weighted_io_ticks) — рост указывает на задержки
# Подробнее: [Расшифровка /proc/diskstats](./proc_diskstats.md)
```

## Дополнительная информация

Смежные темы: низкий [iowait при высокой задержке](./iowait_and_latency.md), [невидимый I/O](./invisible_io.md) (почему iotop пуст), роль [kworker/u*:flush-*](./kworker_flush.md), [7 практических сценариев](./troubleshooting_scenarios.md) с решениями, обзорная [диагностика I/O](../disk_io_troubleshooting.md).
