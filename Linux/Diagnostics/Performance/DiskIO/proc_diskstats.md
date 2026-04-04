# Расшифровка /proc/diskstats

## Definitions

- **`/proc/diskstats`**: Псевдофайл ядра, содержащий детальную статистику операций ввода-вывода для всех блочных устройств.

## Basic Concepts

### Формат данных

Каждая строка соответствует одному блочному устройству и содержит 14 полей.

### Расшифровка полей

| Поле | Название | Описание |
| :--- | :--- | :--- |
| 1 | Major number | Мажорный номер устройства |
| 2 | Minor number | Минорный номер устройства |
| 3 | Device name | Имя устройства (sda, nvme0n1) |
| 4 | Reads completed | Всего операций чтения |
| 5 | Reads merged | Слитые операции чтения |
| 6 | Sectors read | Прочитано секторов |
| 7 | Time spent reading (ms) | Время на чтение |
| 8 | Writes completed | Всего операций записи |
| 9 | Writes merged | Слитые операции записи |
| 10 | Sectors written | Записано секторов |
| 11 | Time spent writing (ms) | Время на запись |
| 12 | I/O in progress | Текущие операции I/O |
| 13 | Time spent doing I/O (ms) | Общее время I/O |
| 14 | Weighted I/O time (ms) | Взвешенное время I/O |

## Practical Scenarios

### Чтение статистики

```bash
# Просмотр всей статистики
cat /proc/diskstats

# Статистика для конкретного устройства
grep sda /proc/diskstats

# Мониторинг в реальном времени (разница между снимками)
watch -n1 'cat /proc/diskstats'
```

### Анализ задержек

Рост полей 7 (Time spent reading) и 11 (Time spent writing) указывает на увеличение задержек устройства.

Поле 14 (Weighted I/O time) — взвешенное значение, где более длительные операции имеют больший вес.

> **Совет:** Для мониторинга в реальном времени используйте `iostat -x`, а `/proc/diskstats` — для кастомных скриптов и исторического анализа.

### Пример парсинга для скриптов

```bash
# Извлечение статистики для sda
awk '$3 == "sda" {print "Reads:", $4, "Writes:", $8, "IO_ticks:", $13}' /proc/diskstats
```

## Additional Information

Смежные темы: [Диагностический чеклист I/O](./diagnostic_checklist.md), [`iostat` — подробное описание](../../Filesystem/iostat.md).
