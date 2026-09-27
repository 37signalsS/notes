# Textfile Collector — механизм сбора текстовых метрик

## Определения

**Textfile Collector** — встроенный модуль `node_exporter`, предназначенный для динамического расширения состава метрик через чтение локальных файлов формата `.prom`.

Этот механизм является индустриальным стандартом для:
- Сбора метрик из **периодических задач** (cron jobs, systemd timers).
- Интеграции с инструментами, не имеющими собственных экспортеров (например, локальные скрипты диагностики RAID, SMART).
- Передачи данных от legacy-систем через текстовые отчеты.

**См. также:** [Node Exporter — обзор](../node_exporter.md), [Формат экспозиции](../../concepts/metric_types/exposition_format.md).

## Предварительные требования

- **node_exporter** версии 1.6+ для поддержки всех типов метрик и флага `--collector.textfile.directory`.
- **Prometheus** версии 2.40+ для корректного парсинга нативных гистограмм и OpenMetrics-формата.
- Операционная система: Linux, BSD, macOS. Для Linux требуется systemd или cron для периодического запуска скриптов.
- Директория для `.prom` файлов должна находиться на той же файловой системе, что и процесс `node_exporter` (для атомарного `mv`).
- Права доступа:
  - Пользователь/сервис, генерирующий метрики — права на запись в директорию.
  - `node_exporter` — права только на чтение директории и файлов.
- Достаточное свободное место на диске для хранения `.prom` файлов (обычно десятки КБ).

## Основные концепции

### Принцип работы

1.  **Генерация:** Внешний процесс (скрипт на Bash, Python и т.д.) собирает данные и записывает их в текстовый файл.
2.  **Формат:** Файл должен иметь расширение `.prom` и соответствовать спецификации Prometheus Text или OpenMetrics.
3.  **Скрапинг:** При HTTP-запросе от Prometheus, `node_exporter` сканирует настроенную директорию, парсит все `.prom` файлы и объединяет (merge) их содержимое в общий HTTP-ответ.

### Формат и синтаксис файлов .prom

Каждый `.prom` файл состоит из блоков метрик. Каждая метрика может содержать необязательные строки `HELP` и `TYPE`, за которыми следуют одна или несколько строк с метриками.

**Базовый синтаксис:**
```text
# HELP metric_name Описание метрики на естественном языке
# TYPE metric_name gauge|counter|summary|histogram|untyped
metric_name{label="value"} numeric_value
```

**Требования к синтаксису:**
- Имя метрики соответствует регулярному выражению `[a-zA-Z_:][a-zA-Z0-9_:]*`.
- Лейблы заключаются в фигурные скобки `{}`, пары ключ-значение разделяются запятыми.
- Числовое значение может быть целым или с плавающей точкой.
- После числового значения не должно быть пробелов или дополнительных символов.
- Строки `HELP` и `TYPE` должны предшествовать всем метрикам с данным именем.
- Для Counter тип должен быть `counter`, для мгновенных значений — `gauge`, для распределений — `summary` или `histogram`.

**Пример корректного файла:**
```text
# HELP backup_last_success_timestamp_seconds Время последнего успешного бэкапа (Unix timestamp)
# TYPE backup_last_success_timestamp_seconds gauge
backup_last_success_timestamp_seconds 1726512000

# HELP backup_duration_seconds Длительность бэкапа в секундах
# TYPE backup_duration_seconds gauge
backup_duration_seconds 360.5

# HELP backup_size_bytes Размер бэкапа в байтах
# TYPE backup_size_bytes gauge
backup_size_bytes{volume="data"} 1073741824
backup_size_bytes{volume="logs"} 536870912
```

### Штрих-коды метрик (типы метрик)

Textfile Collector поддерживает все базовые типы метрик Prometheus:

- **Gauge:** Мгновенное числовое значение, которое может расти или убывать. Используется для температуры, использования памяти, количества открытых файлов.
- **Counter:** Монотонно растущее значение, сбрасываемое при перезапуске процесса. Используется для количества выполненных операций, ошибок, запросов.
- **Summary:** Распределение значений с подсчётом суммы и количества. Позволяет вычислить квантили на стороне Prometheus.
- **Histogram:** Наблюдаемые значения с фиксированными или экспоненциальными бакетами. Поддерживает нативные гистограммы в Prometheus 3.0+.
- **Untyped:** Если тип не указан, метрика считается нетипизированной. Рекомендуется всегда указывать тип для статической валидации.

### Поддержка Prometheus 3.0+

Начиная с Prometheus 3.0 и последних версий Node Exporter:
- **UTF-8:** В именах метрик и лейблов теперь можно использовать точки и расширенный набор символов, если они корректно экранированы в формате OpenMetrics.
- **Native Histograms:** Формат `.prom` поддерживает классические бакеты гистограмм, но для нативных (экспоненциальных) гистограмм рекомендуется использовать бинарные форматы или OTLP.
- **Stale маркеры:** Если метрика исчезла из `.prom` файла, `node_exporter` по умолчанию не отправляет stale-маркер. Для корректного исчезновения временного ряда добавьте метрику с тем же именем и значением `NaN`.

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

### Валидация

Перед размещением `.prom` файла в директории проверьте его корректность:

```bash
# Проверка синтаксиса конкретного файла
promtool check metrics /var/lib/node_exporter/textfile_metrics/backup.prom

# Проверка всех файлов в директории
find /var/lib/node_exporter/textfile_metrics -name '*.prom' -exec promtool check metrics {} +

# Проверка с учетом UTF-8
curl -H "Accept: text/plain; version=1.0.0; escaping=allow-utf-8" http://localhost:9100/metrics | promtool check metrics
```

**Ожидаемый вывод при успешной проверке:**
```text
SUCCESS: 3 metrics found
```

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

**Проверка:**
```bash
curl -s http://localhost:9100/metrics | grep backup_last_success_timestamp_seconds
# → backup_last_success_timestamp_seconds 1726512000
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

### Сценарий 4: Мониторинг SMART-параметров дисков

```bash
#!/bin/bash
SMART_SCRIPT="/usr/local/bin/smartctl-metrics.sh"
METRICS_FILE="/var/lib/node_exporter/textfile_metrics/smart.prom"
TMP_FILE="${METRICS_FILE}.tmp.$$"

# Получение списка дисков
DISKS=$(lsblk -dno NAME | grep -E '^sd|^nvme')

declare -A FAILING_DISKS
declare -A TEMP_DISKS

for disk in $DISKS; do
    # Проверка на отказы
    FAILING=$(smartctl -H /dev/$disk 2>/dev/null | grep -c "FAILING")
    if [ "$FAILING" -gt 0 ]; then
        FAILING_DISKS[$disk]=1
    fi

    # Температура
    TEMP=$(smartctl -A /dev/$disk 2>/dev/null | grep -i "temperature" | head -1 | awk '{print $10}')
    if [ -n "$TEMP" ]; then
        TEMP_DISKS[$disk]=$TEMP
    fi
done

{
    echo "# HELP node_smart_health_failed_binary Диск с FAILED статусом SMART (1 = да)"
    echo "# TYPE node_smart_health_failed_binary gauge"
    for disk in "${!FAILING_DISKS[@]}"; do
        echo "node_smart_health_failed_binary{device=\"/dev/$disk\"} 1"
    done

    echo "# HELP node_smart_temperature_celsius Температура диска по SMART"
    echo "# TYPE node_smart_temperature_celsius gauge"
    for disk in "${!TEMP_DISKS[@]}"; do
        echo "node_smart_temperature_celsius{device=\"/dev/$disk\"} ${TEMP_DISKS[$disk]}"
    done
} > "$TMP_FILE"

mv "$TMP_FILE" "$METRICS_FILE"
```

### Сценарий 5: Мониторинг статуса systemd-сервисов

```bash
#!/bin/bash
METRICS_FILE="/var/lib/node_exporter/textfile_metrics/systemd_services.prom"
TMP_FILE="${METRICS_FILE}.tmp.$$"

# Список критичных сервисов
SERVICES=("nginx" "postgresql" "sshd")

{
    echo "# HELP node_systemd_service_active Статус активности сервиса (1 = активен)"
    echo "# TYPE node_systemd_service_active gauge"
    for svc in "${SERVICES[@]}"; do
        ACTIVE=$(systemctl is-active "$svc" 2>/dev/null)
        if [ "$ACTIVE" = "active" ]; then
            echo "node_systemd_service_active{service=\"$svc\"} 1"
        else
            echo "node_systemd_service_active{service=\"$svc\"} 0"
        fi
    done

    echo "# HELP node_systemd_service_last_run_seconds Время последнего запуска сервиса"
    echo "# TYPE node_systemd_service_last_run_seconds gauge"
    for svc in "${SERVICES[@]}"; do
        TIMESTAMP=$(systemctl show -p ActiveEnterTimestamp "$svc" 2>/dev/null | cut -d= -f2)
        if [ -n "$TIMESTAMP" ]; then
            EPOCH=$(date -d "$TIMESTAMP" +%s 2>/dev/null)
            if [ -n "$EPOCH" ]; then
                echo "node_systemd_service_last_run_seconds{service=\"$svc\"} $EPOCH"
            fi
        fi
    done
} > "$TMP_FILE"

mv "$TMP_FILE" "$METRICS_FILE"
```

### Сценарий 6: Мониторинг здоровья cron-задач

```bash
#!/bin/bash
METRICS_FILE="/var/lib/node_exporter/textfile_metrics/cron_health.prom"
TMP_FILE="${METRICS_FILE}.tmp.$$"
STATE_FILE="/var/lib/node_exporter/cron_health.state"
mkdir -p "$(dirname "$STATE_FILE")"

# Файлы-флаги, создаваемые последней задачей
declare -A JOB_LAST_RUN

# Сбор информации о последних запусках
for job_file in /var/lib/node_exporter/cron_state/*; do
    [ -f "$job_file" ] || continue
    job_name=$(basename "$job_file")
    mtime=$(stat -c %Y "$job_file" 2>/dev/null)
    JOB_LAST_RUN[$job_name]=$mtime
done

NOW=$(date +%s)

{
    echo "# HELP node_cron_job_last_run_seconds Время последнего успешного запуска cron-задачи"
    echo "# TYPE node_cron_job_last_run_seconds gauge"
    for job in "${!JOB_LAST_RUN[@]}"; do
        echo "node_cron_job_last_run_seconds{job=\"$job\"} ${JOB_LAST_RUN[$job]}"
    done

    echo "# HELP node_cron_job_overdue_binary Cron-задача не запускалась более 2x интервала (1 = просрочена)"
    echo "# TYPE node_cron_job_overdue_binary gauge"
    for job in "${!JOB_LAST_RUN[@]}"; do
        last_run=${JOB_LAST_RUN[$job]}
        age=$((NOW - last_run))
        # Предполагаемый интервал задачи: 3600 сек (1 час) по умолчанию
        interval=3600
        if [ "$age" -gt $((interval * 2)) ]; then
            echo "node_cron_job_overdue_binary{job=\"$job\"} 1"
        else
            echo "node_cron_job_overdue_binary{job=\"$job\"} 0"
        fi
    done
} > "$TMP_FILE"

mv "$TMP_FILE" "$METRICS_FILE"
```

### Сценарий 7: Мониторинг выполнения бэкапов

```bash
#!/bin/bash
METRICS_FILE="/var/lib/node_exporter/textfile_metrics/backup.prom"
TMP_FILE="${METRICS_FILE}.tmp.$$"
STATE_DIR="/var/lib/backup_monitoring"
mkdir -p "$STATE_DIR"

NOW=$(date +%s)

# Проверка последнего успешного бэкапа (pg_dump)
PG_BACKUP_FILE="$STATE_DIR/pg_last_success"
if [ -f "$PG_BACKUP_FILE" ]; then
    PG_LAST=$(cat "$PG_BACKUP_FILE")
else
    PG_LAST=0
fi

# Проверка последнего successful rsync-бэкапа
RSYNC_BACKUP_FILE="$STATE_DIR/rsync_last_success"
if [ -f "$RSYNC_BACKUP_FILE" ]; then
    RSYNC_LAST=$(cat "$RSYNC_BACKUP_FILE")
else
    RSYNC_LAST=0
fi

# Проверка размера последнего бэкапа
BACKUP_SIZE_FILE="$STATE_DIR/last_backup_size"
if [ -f "$BACKUP_SIZE_FILE" ]; then
    BACKUP_SIZE=$(cat "$BACKUP_SIZE_FILE")
else
    BACKUP_SIZE=0
fi

# Проверка кода возврата последнего borg-бэкапа
BORG_EXIT_FILE="$STATE_DIR/borg_last_exit"
if [ -f "$BORG_EXIT_FILE" ]; then
    BORG_EXIT=$(cat "$BORG_EXIT_FILE")
else
    BORG_EXIT=0
fi

{
    echo "# HELP backup_last_success_timestamp_seconds Время последнего успешного бэкапа"
    echo "# TYPE backup_last_success_timestamp_seconds gauge"
    echo "backup_last_success_timestamp_seconds{type=\"pg_dump\"} $PG_LAST"
    echo "backup_last_success_timestamp_seconds{type=\"rsync\"} $RSYNC_LAST"

    echo "# HELP backup_size_bytes Размер последнего бэкапа"
    echo "# TYPE backup_size_bytes gauge"
    echo "backup_size_bytes{type=\"pg_dump\"} $BACKUP_SIZE"

    echo "# HELP backup_last_run_seconds Время последнего запуска скрипта мониторинга"
    echo "# TYPE backup_last_run_seconds gauge"
    echo "backup_last_run_seconds $NOW"

    echo "# HELP backup_exit_code Код возврата последнего бэкапа"
    echo "# TYPE backup_exit_code gauge"
    echo "backup_exit_code{type=\"borg\"} $BORG_EXIT"
} > "$TMP_FILE"

mv "$TMP_FILE" "$METRICS_FILE"
```

**Скрипт-обёртка для pg_dump с записью метрик:**

```bash
#!/bin/bash
STATE_DIR="/var/lib/backup_monitoring"
mkdir -p "$STATE_DIR"

BACKUP_PATH="/backups/pg_$(date +%Y%m%d_%H%M%S).sql.gz"

if pg_dumpall | gzip > "$BACKUP_PATH" 2>/dev/null; then
    echo $(date +%s) > "$STATE_DIR/pg_last_success"
    stat -c %s "$BACKUP_PATH" > "$STATE_DIR/last_backup_size"
    echo "0" > "$STATE_DIR/borg_last_exit"
else
    echo "1" > "$STATE_DIR/borg_last_exit"
fi
```

**Алерты в Prometheus:**

```yaml
groups:
  - name: backup_alerts
    rules:
      # Бэкап не выполнялся более 25 часов (ежедневный)
      - alert: BackupMissing
        expr: time() - backup_last_success_timestamp_seconds{type="pg_dump"} > 90000
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Бэкап PostgreSQL не выполнялся более 25 часов"
          description: "Последний успешный бэкап: {{ $value | humanizeTimestamp }}."

      # Бэкап завершился с ошибкой
      - alert: BackupFailed
        expr: backup_exit_code != 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Бэкап завершился с ошибкой"
          description: "Код возврата: {{ $value }}."

      # Размер бэкапа резко уменьшился (>50% от предыдущего)
      - alert: BackupSizeAnomaly
        expr: backup_size_bytes < (backup_size_bytes offset 1d) * 0.5
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Размер бэкапа значительно уменьшился"
          description: "Текущий: {{ $value | humanize1024 }}B."
```

### Сценарий 8: Мониторинг заполнения файловых систем

```bash
#!/bin/bash
METRICS_FILE="/var/lib/node_exporter/textfile_metrics/disk_usage.prom"
TMP_FILE="${METRICS_FILE}.tmp.$$"

# Монтирования для мониторинга
MOUNTS=("/" "/var" "/home" "/tmp")

{
    echo "# HELP node_filesystem_usage_pct Процент использования файловой системы (0-100)"
    echo "# TYPE node_filesystem_usage_pct gauge"
    for mount in "${MOUNTS[@]}"; do
        if [ -d "$mount" ]; then
            usage=$(df -h "$mount" 2>/dev/null | awk 'NR==2 {gsub(/%/,""); print $5}')
            if [ -n "$usage" ]; then
                echo "node_filesystem_usage_pct{mountpoint=\"$mount\"} $usage"
            fi
        fi
    done

    echo "# HELP node_filesystem_inode_usage_pct Процент использования inodes (0-100)"
    echo "# TYPE node_filesystem_inode_usage_pct gauge"
    for mount in "${MOUNTS[@]}"; do
        if [ -d "$mount" ]; then
            inode_usage=$(df -i "$mount" 2>/dev/null | awk 'NR==2 {gsub(/%/,""); print $5}')
            if [ -n "$inode_usage" ]; then
                echo "node_filesystem_inode_usage_pct{mountpoint=\"$mount\"} $inode_usage"
            fi
        fi
    done
} > "$TMP_FILE"

mv "$TMP_FILE" "$METRICS_FILE"
```

## Рекомендации и ограничения

1.  **Уникальность:** Имена метрик должны быть уникальными во всей директории. Если два файла содержат одну и ту же метрику с одинаковыми лейблами, Node Exporter выдаст ошибку парсинга.
2.  **Производительность:** Node Exporter перечитывает и парсит **все** файлы при каждом скрапинге. Не храните там тысячи файлов или файлы размером в десятки мегабайт.
3.  **Безопасность:** Директория с метриками должна быть доступна на запись только тем пользователям/сервисам, которые генерируют метрики. Node Exporter должен иметь доступ только на чтение.
4.  **Однократная запись:** Не записывайте в один `.prom` файл из нескольких скриптов одновременно. Используйте отдельные файлы или файловые блокировки (`flock`).
5.  **Rotate и очистка:** Если скрипт периодически перезаписывает файл, убедитесь, что старая версия не остаётся в директории. Используйте атомарный `mv` из временного файла.

## Типичные ошибки и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Метрик нет в `/metrics` | Файл не имеет расширения `.prom` | Убедитесь, что расширение строго `.prom`. |
| Ошибка парсинга | Нарушен синтаксис (например, нет пробела после значения) | Проверьте файл: `promtool check metrics < file.prom`. |
| Метрика `node_textfile_scrape_error` равна `1` | Ошибка доступа или битый файл | Проверьте права доступа и логи Node Exporter. |
| Дубликаты меток | Одинаковые метрики в разных файлах | Распределите метрики по уникальным именам или добавьте различающие лейблы. |
| Атомарная запись не работает | TMP файл создаётся на другой ФС | Убедитесь, что `TMP_FILE` находится на той же ФС, что и целевая директория. Используйте `mktemp --tmpdir=/var/lib/node_exporter/textfile_metrics`. |
| Старые значения после падения скрипта | Скрипт упал до атомарного `mv` | Реализуйте метрику `last_run_timestamp` и алерт на её просрочку. |
| Высокая нагрузка при скрапинге | Слишком много или слишком большие `.prom` файлы | Ограничьте количество файлов (<100) и размер (<10 КБ каждый). |
| Метрики исчезают после обновления файла | Node Exporter кэширует файлы | Убедитесь, что используется версия node_exporter 1.6+. Перезапустите node_exporter при смене директории. |

## Лучшие практики

- **Разделение ответственности:** Один `.prom` файл = одна задача/скрипт. Не смешивайте метрики от разных источников в одном файле.
- **Мониторинг мониторинга:** Всегда экспортируйте метрику времени последнего запуска скрипта и настраивайте алерт на её просрочку.
- **Имена лейблов:** Используйте осмысленные, но короткие имена лейблов. Избегайте высококардинальных лейблов (например, `filename`, `pid`, `user_id`).
- **Единицы измерения:** В имени метрики указывайте единицу измерения через суффикс `_seconds`, `_bytes`, `_total`, `_percent`. Это упрощает создание дашбордов и PromQL-запросов.
- **Документация:** Добавляйте `# HELP` для каждой метрики. Это облегчает понимание назначения метрики другим членам команды.
- **Права доступа:**
  - Директория с метриками: `drwxr-xr-x root:root` или `drwxr-x--- prometheus:prometheus`.
  - Файлы `.prom`: `-rw-r--r-- root:root` или `-rw-r--r-- prometheus:prometheus`.
  - Скрипты-генераторы: запускаются от отдельного пользователя (например, `backup`), которому разрешена запись в директорию.
- **Rotate логов:** Если скрипт генерирует логи, настраивайте их ротацию отдельно, чтобы они не заполнили диск, на котором находится директория с `.prom` файлами.
- **systemd-таймеры вместо cron:** Для сервисов, управляемых systemd, используйте `.timer` вместо `cron`. Это обеспечивает лучшую интеграцию с логированием (`journalctl`) и управление зависимостями.

## Особенности и граничные случаи

### Атомарность записи
- `mv` атомарно подменяет файл только в пределах одной файловой системы. Не используйте `mv` между разными разделами или смонтированными директориями.
- Для дополнительной защиты используйте `flock` для предотвращения параллельного запуска скрипта:
  ```bash
  (
    flock -x 200
    # ... генерация метрик ...
  ) 200>/var/run/my-metrics-script.lock
  ```

### Stale маркеры
- Textfile Collector не отправляет stale-маркеры автоматически при удалении метрики из `.prom` файла.
- Для явного указания, что метрика устарела, добавьте строку с тем же именем метрики и значением `NaN`:
  ```text
  my_metric_name NaN
  ```
- Prometheus 2.0+ корректно обработает `NaN` и удалит временной ряд через `stale` маркер.

### Обработка ошибок в скриптах
- Если скрипт завершается с ненулевым кодом возврата, cron/systemd может отправить уведомление администратору.
- Никогда не оставляйте старый `.prom` файл после ошибки скрипта. Лучше записать нулевые/безопасные значения и метку ошибки:
  ```bash
  # В случае ошибки
  echo "my_metric_error_binary 1" >> "$TMP_FILE"
  ```

### Нативная гистограмма в .prom формате
- Формат `.prom` поддерживает только классические гистограммы с явными бакетами.
- Для нативных гистограмм используйте бинарный формат exposition или OTLP.
- Если требуется высокая детализация распределений, рассмотрите отдельный экспортер вместо textfile collector.

### Кодировка файлов
- Все `.prom` файлы должны быть в кодировке UTF-8 без BOM.
- Символы, отличные от ASCII, допустимы в значениях лейблов только при использовании OpenMetrics-формата и соответствующих настроек Prometheus.

### Размер директории
- Node Exporter читает **все** файлы в директории при каждом запросе `/metrics`.
- Рекомендуемое количество файлов: <100.
- Рекомендуемый размер одного файла: <10 КБ.
- Если требуется больше метрик, рассмотрите кастомный экспортер.

## Валидация и проверка работоспособности

### Проверка доступности метрик
```bash
# Проверка, что метрики доступны на эндпоинте node_exporter
curl -s http://localhost:9100/metrics | grep -E "backup_|node_raid_|smart_"

# Проверка конкретной метрики
curl -s http://localhost:9100/metrics | grep backup_last_success_timestamp_seconds

# Проверка на наличие ошибок парсинга
curl -s http://localhost:9100/metrics | grep node_textfile_scrape_error
# Должно возвращать 0
```

### Проверка целостности файла
```bash
# Валидация синтаксиса
promtool check metrics /var/lib/node_exporter/textfile_metrics/backup.prom

# Проверка всех файлов в директории
for f in /var/lib/node_exporter/textfile_metrics/*.prom; do
    echo "Проверка $f..."
    promtool check metrics "$f"
done
```

### Проверка в Prometheus
```promql
# Последнее значение метрики
backup_last_success_timestamp_seconds

# Проверка, что метрика обновляется (изменяется за последний час)
changes(backup_last_success_timestamp_seconds[1h]) > 0

# Проверка, что метрика не устарела (например, для ежедневного бэкапа)
time() - backup_last_success_timestamp_seconds < 86400
```

## Визуализация

### Grafana — дашборд Node Exporter

Используйте готовые дашборды:
- **Node Exporter Full:** `1860` — общий дашборд с системными метриками.
- **Node Exporter Dedicated:** `11074` — расширенный дашборд с детализацией по дискам, сетевой статистике и ресурсам.

**Рекомендации по панелям для textfile metrics:**
- **Gauge панель:** Для отображения статуса RAID, SMART, systemd-сервисов.
- **Gauge (с прогресс-баром):** Для процента использования диска или inodes.
- **Stat панель:** Для отображения времени последнего успешного запуска скрипта.
- **Alert list:** Для интеграции с алертами Prometheus на просроченные метрики.

## Справочник

### Команды promtool для Textfile Collector

```bash
# Проверка одного файла
promtool check metrics /var/lib/node_exporter/textfile_metrics/example.prom

# Проверка всех файлов в директории
find /var/lib/node_exporter/textfile_metrics -name '*.prom' -exec promtool check metrics {} +

# Проверка с выводом имени файла и ошибок
for f in /var/lib/node_exporter/textfile_metrics/*.prom; do
    echo "=== $f ==="
    promtool check metrics "$f" || echo "ОШИБКА в $f"
done
```

### Переменные окружения node_exporter

| Переменная | Описание |
| :--- | :--- |
| `--collector.textfile.directory` | Путь к директории с `.prom` файлами |
| `--collector.textfile.directory.include` | Regexp для фильтрации файлов (по умолчанию `.*\.prom`) |
| `--collector.textfile.directory.include-whitespace-in-regexp` | Разрешить пробелы в regexp |

### Ссылки

- [Официальная документация Node Exporter — Textfile Collector](https://prometheus.io/docs/guides/node-exporter/#textfile-collector)
- [Формат OpenMetrics](https://github.com/OpenObservability/OpenMetrics/blob/main/specification/OpenMetrics.md)
- [Prometheus Text Format](https://prometheus.io/docs/instrumenting/exposition_formats/#text-format-details)

**См. также:**
- [Тестирование экспортеров](./exporter_testing.md) — валидация .prom файлов и smoke-тесты.
- [Надежность экспортеров](./exporter_reliability.md) — metamonitoring и алерты на stale данные.
- [Расширяемость — основные концепции](./concepts.md)
- [Создание собственных экспортеров](./custom_exporters.md) — если логика слишком сложна для bash-скрипта.
- [Формат экспозиции](../../concepts/metric_types/exposition_format.md) — детали современного стандарта разметки.
