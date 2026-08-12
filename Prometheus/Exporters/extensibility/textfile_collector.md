# Textfile Collector — механизм сбора текстовых метрик

## Определения

**Textfile Collector** — встроенный модуль `node_exporter`, предназначенный для динамического расширения состава метрик через чтение локальных файлов формата `.prom`.

Этот механизм является индустриальным стандартом для:
- Сбора метрик из **периодических задач** (cron jobs, systemd timers).
- Интеграции с инструментами, не имеющими собственных экспортеров (например, локальные скрипты диагностики RAID, SMART).
- Передачи данных от legacy-систем через текстовые отчеты.

**См. также:** [Node Exporter — обзор](../node_exporter.md), [Формат экспозиции](../../concepts/metric_types/exposition_format.md).

## Основные концепции

### Принцип работы

1.  **Генерация:** Внешний процесс (скрипт на Bash, Python и т.д.) собирает данные и записывает их в текстовый файл.
2.  **Формат:** Файл должен иметь расширение `.prom` и соответствовать спецификации Prometheus Text или OpenMetrics.
3.  **Скрапинг:** При HTTP-запросе от Prometheus, `node_exporter` сканирует настроенную директорию, парсит все `.prom` файлы и объединяет (merge) их содержимое в общий HTTP-ответ.

### Активация и настройка

Модуль активируется через флаг `--collector.textfile.directory`.

**В Linux (systemd):**
Настройка через файл параметров (обычно `/etc/default/node_exporter` или `/etc/sysconfig/node_exporter`):
```bash
NODE_EXPORTER_OPTS="--collector.textfile.directory=/var/lib/node_exporter/textfile_metrics"
```

**В Docker:**
Необходимо пробросить директорию с метриками как том (volume) с правами только на чтение (`ro`) для экспортера.
```yaml
services:
  node-exporter:
    image: prom/node-exporter:latest
    volumes:
      - /var/lib/node_exporter/textfile_metrics:/etc/node-exporter/textfile:ro
    command:
      - '--collector.textfile.directory=/etc/node-exporter/textfile'
```

### Поддержка Prometheus 3.0+

Начиная с Prometheus 3.0 и последних версий Node Exporter:
*   **UTF-8:** В именах метрик и лейблов теперь можно использовать точки и расширенный набор символов, если они корректно экранированы в формате OpenMetrics.
*   **Native Histograms:** Формат `.prom` поддерживает классические бакеты гистограмм, но для нативных (экспоненциальных) гистограмм рекомендуется использовать бинарные форматы или OTLP.

## Практические сценарии

### Сценарий 1: Атомарная запись метрик

**Критическое правило:** Никогда не записывайте данные напрямую в итоговый `.prom` файл через перенаправление `>` или `>>`. Если Prometheus выполнит скрапинг в момент записи, он получит битые данные.

**Правильный алгоритм (Bash):**
```bash
#!/bin/bash
METRICS_DIR="/var/lib/node_exporter/textfile_metrics"
TMP_FILE="/tmp/backup_status.prom.$$"

# Сбор данных
LAST_SUCCESS=$(date +%s)
{
    echo "# HELP backup_last_success_timestamp_seconds Время последнего успешного бэкапа (Unix timestamp)"
    echo "# TYPE backup_last_success_timestamp_seconds gauge"
    echo "backup_last_success_timestamp_seconds $LAST_SUCCESS"
} > "$TMP_FILE"

# Атомарная замена файла через mv (переименование в пределах одной ФС атомарно)
mv "$TMP_FILE" "$METRICS_DIR/backup.prom"
```

### Сценарий 2: Мониторинг состояния RAID (MegaCLI)

Преобразование вывода специализированной утилиты в формат метрик.

```bash
#!/bin/bash
# Получение количества деградировавших дисков
DEGRADED_COUNT=$(/opt/MegaRAID/MegaCli/MegaCli64 -AdpAllInfo -aAll | grep "Degraded" | awk '{print $3}')

METRIC_FILE="/var/lib/node_exporter/textfile_metrics/raid.prom"

echo "# HELP node_raid_degraded_drives_count Количество деградировавших дисков в RAID" > "${METRIC_FILE}.tmp"
echo "# TYPE node_raid_degraded_drives_count gauge" >> "${METRIC_FILE}.tmp"
echo "node_raid_degraded_drives_count $DEGRADED_COUNT" >> "${METRIC_FILE}.tmp"

mv "${METRIC_FILE}.tmp" "$METRIC_FILE"
```

### Сценарий 3: Борьба с «протуханием» данных (Stale Metrics)

Textfile Collector — это пассивный сборщик. Если ваш скрипт упадет, в директории останется старый файл с устаревшим значением `1`, и Prometheus будет считать, что всё в порядке.

**Решение:** Всегда добавляйте метрику времени последнего запуска скрипта.

```bash
# Внутри скрипта
echo "myapp_backup_last_run_seconds $(date +%s)" >> "$TMP_FILE"
```
**Алерт в Prometheus:**
```promql
# Если скрипт не запускался более 25 часов (для ежедневных задач)
time() - myapp_backup_last_run_seconds > 90000
```

## Дополнительная информация

### Рекомендации и ограничения

1.  **Уникальность:** Имена метрик должны быть уникальными во всей директории. Если два файла содержат одну и ту же метрику с одинаковыми лейблами, Node Exporter выдаст ошибку парсинга.
2.  **Производительность:** Node Exporter перечитывает и парсит **все** файлы при каждом скрапинге. Не храните там тысячи файлов или файлы размером в десятки мегабайт.
3.  **Безопасность:** Директория с метриками должна быть доступна на запись только тем пользователям/сервисам, которые генерируют метрики. Node Exporter должен иметь доступ только на чтение.

### Диагностика

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Метрик нет в `/metrics` | Файл не имеет расширения `.prom` | Убедитесь, что расширение строго `.prom`. |
| Ошибка парсинга | Нарушен синтаксис (например, нет пробела после значения) | Проверьте файл: `promtool check metrics < file.prom`. |
| Метрика `node_textfile_scrape_error` равна `1` | Ошибка доступа или битый файл | Проверьте права доступа и логи Node Exporter. |
| Дубликаты меток | Одинаковые метрики в разных файлах | Распределите метрики по уникальным именам или добавьте различающие лейблы. |

**См. также:**
- [Расширяемость — основные концепции](./concepts.md)
- [Создание собственных экспортеров](./custom_exporters.md) — если логика слишком сложна для bash-скрипта.
- [Формат OpenMetrics](../../concepts/metric_types/exposition_format.md) — детали современного стандарта разметки.
