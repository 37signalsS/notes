# Textfile Collector — механизм сбора текстовых метрик

## Определения

**Textfile Collector** — встроенный модуль `node_exporter`, предназначенный для динамического расширения состава метрик через чтение локальных файлов формата `.prom`.

Этот механизм является стандартом для:
- Сбора метрик из **периодических задач** (cron jobs, systemd timers).
- Интеграции с инструментами, не имеющими встроенных экспортеров (например, локальные скрипты диагностики).
- Мониторинга состояния оборудования через вывод CLI-утилит.

**Reliability Score: 10** (Соответствует стабильному API `node_exporter` и стандартам OpenMetrics).

**См. также:** [Node Exporter — обзор](../node_exporter.md), [Формат экспозиции](../../concepts/metric_types/exposition_format.md).

## Основные концепции

### Принцип работы

1.  **Генерация:** Внешний процесс (скрипт) собирает данные и записывает их в текстовый файл.
2.  **Формат:** Файл должен иметь расширение `.prom` и соответствовать [спецификации Prometheus](../../concepts/metric_types/exposition_format.md).
3.  **Скрапинг:** При каждом HTTP-запросе от Prometheus, `node_exporter` сканирует директорию, парсит все `.prom` файлы и мерджит их содержимое в общий ответ.

### Активация и настройка

Модуль включается через флаг `--collector.textfile.directory`.

**В Linux (systemd):**
Отредактируйте `/etc/default/node_exporter`:
```bash
NODE_EXPORTER_OPTS="--collector.textfile.directory=/var/lib/node_exporter/textfile_metrics"
```

**В Docker:**
Необходимо пробросить директорию с метриками как Volume.
```yaml
services:
  node-exporter:
    image: prom/node-exporter:latest
    volumes:
      - /var/lib/node_exporter/textfile_metrics:/etc/node-exporter/textfile:ro
    command:
      - '--collector.textfile.directory=/etc/node-exporter/textfile'
```

## Практические сценарии

### Сценарий 1: Мониторинг бэкапов (Атомарная запись)

**Важно:** Всегда используйте `mv` для обновления файлов. Прямая запись через `>` или `>>` может привести к тому, что Prometheus прочитает наполовину записанный (битый) файл.

```bash
#!/bin/bash
METRICS_DIR="/var/lib/node_exporter/textfile_metrics"
TMP_FILE="/tmp/backup_status.prom.$$"

# Сбор данных
LAST_SUCCESS=$(date +%s)
echo "# HELP backup_last_success_timestamp_seconds Время последнего бэкапа" > "$TMP_FILE"
echo "# TYPE backup_last_success_timestamp_seconds gauge" >> "$TMP_FILE"
echo "backup_last_success_timestamp_seconds $LAST_SUCCESS" >> "$TMP_FILE"

# Атомарная замена
mv "$TMP_FILE" "$METRICS_DIR/backup.prom"
```

### Сценарий 2: Мониторинг SMART и RAID (CLI-адаптер)

Пример адаптации вывода утилиты для мониторинга износа SSD.

```bash
#!/bin/bash
VALUE=$(smartctl -A /dev/sda | grep "Percentage_Used" | awk '{print $4}')

echo "# HELP node_disk_percentage_used_total SSD Wear Leveling Percentage" > /var/lib/node_exporter/textfile_metrics/ssd_wear.prom
echo "node_disk_percentage_used_total{device=\"sda\"} $VALUE" >> /var/lib/node_exporter/textfile_metrics/ssd_wear.prom
```

### Сценарий 3: Использование временных меток (Timestamp)

Обычно Prometheus сам проставляет время скрапинга. Однако, для старых данных можно указать время их получения в файле (Unix ms).

```text
# Метрика собрана в прошлом
old_metric_value 42 1622548800000
```
*Примечание: Используйте это с осторожностью, так как это может вызвать проблемы с `stale data` при отображении.*

## Дополнительная информация

### Рекомендации и ограничения

1.  **Удаление файлов:** Если скрипт перестает работать, файл `.prom` остается в директории, и `node_exporter` продолжит отдавать **последнее записанное значение** (stale metrics). Используйте метрику `..._last_run_timestamp_seconds` для алертинга на «протухшие» данные.
2.  **Слияние (Merge):** Если одна и та же метрика с одинаковыми лейблами определена в двух разных файлах, `node_exporter` выдаст ошибку или дубликат. Следите за уникальностью имен файлов и метрик.
3.  **Производительность:** Не создавайте сотни мелких файлов. `node_exporter` перечитывает всю директорию при каждом запросе.

### Диагностика

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Метрик нет в выводе | Файл не имеет расширения `.prom` | Переименуйте файл. |
| Ошибка 500 на `/metrics` | Ошибка парсинга в одном из файлов | Проверьте формат через `promtool check metrics`. |
| Данные не меняются | Скрипт в cron падает | Проверьте `journalctl -u cron`. |

**См. также:**
- [Расширяемость — основные концепции](./concepts.md)
- [Клиентские библиотеки](./client_libraries.md) — для высоконагруженных систем.
- [Формат OpenMetrics](../../concepts/metric_types/exposition_format.md) — детали современного стандарта.
