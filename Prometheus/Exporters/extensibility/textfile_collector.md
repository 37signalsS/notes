# Textfile Collector — механизм сбора текстовых метрик

## Определения

**Textfile Collector** — это встроенный модуль `node_exporter`, предназначенный для сбора произвольных метрик из текстовых файлов формата `.prom`.

Этот механизм идеально подходит для:

* Сбора метрик из периодических задач (cron jobs).
* Интеграции с системами, не имеющими собственного HTTP-интерфейса.
* Быстрого прототипирования мониторинга без написания полноценного экспортера.

Альтернативные подходы: [собственный экспортер](./custom_exporters.md) или прямая инструментация через [клиентские библиотеки](./client_libraries.md).

## Основные концепции

### Принцип работы

Процесс сбора метрик организован следующим образом:

1. Внешний агент (bash-скрипт, python-скрипт или приложение) генерирует данные.
2. Данные сохраняются в файл с расширением `.prom` в специально выделенную директорию.
3. `node_exporter` при каждом скрапинге сканирует эту директорию, считывает содержимое всех `.prom` файлов и включает их в общий вывод эндпоинта `/metrics`.

### Активация и настройка

Для включения модуля необходимо запустить `node_exporter` с флагом `--collector.textfile.directory`, указав путь к директории с метриками.

**Пример запуска:**

```bash
node_exporter --collector.textfile.directory=/var/lib/node_exporter/textfile_metrics
```

**Настройка через файл конфигурации (для систем на базе systemd):**
В файле `/etc/default/node_exporter` (или `/etc/sysconfig/node_exporter`):

```bash
NODE_EXPORTER_OPTS="--collector.textfile.directory=/var/lib/node_exporter/textfile_metrics"
```

### Формат `.prom` файлов

Файлы должны строго соответствовать [формату экспозиции](../../concepts/metric_types/exposition_format.md) Prometheus:

* Имя файла должно заканчиваться на `.prom`.
* Рекомендуется указывать метаданные `# HELP` и `# TYPE` для каждой метрики.
* Используйте `snake_case` для именования метрик.

**Пример корректного контента:**

```text
# HELP app_last_backup_timestamp_seconds Время последнего успешного бэкапа
# TYPE app_last_backup_timestamp_seconds gauge
app_last_backup_timestamp_seconds 1622548800
```

## Практические сценарии

### Сценарий 1: Мониторинг выполнения cron-задач

Самый распространенный способ — запись результата выполнения скрипта в файл.

```bash
#!/bin/bash
# Скрипт /usr/local/bin/backup_monitor.sh
METRIC_FILE="/var/lib/node_exporter/textfile_metrics/backup.prom"

if /usr/local/bin/run_backup.sh; then
    echo "app_backup_status 1" > "$METRIC_FILE"
else
    echo "app_backup_status 0" > "$METRIC_FILE"
fi
```

### Сценарий 2: Мониторинг срока действия SSL-сертификатов

```bash
#!/bin/bash
# Определение дней до истечения сертификата
DOMAIN="example.com"
EXPIRY_DATE=$(openssl x509 -enddate -noout -in /etc/ssl/certs/cert.pem | cut -d= -f2)
DAYS_LEFT=$(( ( $(date -d "$EXPIRY_DATE" +%s) - $(date +%s) ) / 86400 ))

echo "# HELP ssl_certificate_expiry_days Days remaining until SSL certificate expires" > /var/lib/node_exporter/textfile_metrics/ssl.prom
echo "# TYPE ssl_certificate_expiry_days gauge" >> /var/lib/node_exporter/textfile_metrics/ssl.prom
echo "ssl_certificate_expiry_days{domain=\"$DOMAIN\"} $DAYS_LEFT" >> /var/lib/node_exporter/textfile_metrics/ssl.prom
```

### Сценарий 3: Атомарная запись (Best Practice)

Чтобы `node_exporter` не прочитал частично записанный файл, используйте временные файлы и команду `mv`.

```bash
TMP_FILE="/tmp/metric.prom.$$"
FINAL_FILE="/var/lib/node_exporter/textfile_metrics/my_metric.prom"

echo "my_custom_metric 42" > "$TMP_FILE"
mv "$TMP_FILE" "$FINAL_FILE"
```

## Дополнительная информация

### Диагностика проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Метрики отсутствуют | Неверный путь к директории | Проверьте значение флага `--collector.textfile.directory` |
| Ошибки парсинга | Нарушение формата данных | Проверьте файл утилитой `promtool check metrics` |
| Данные не обновляются | Скрипт-генератор завершился с ошибкой | Проверьте логи выполнения скрипта (cron/journald) |

### См. также

* [Node Exporter — обзор](../node_exporter.md)
* [Расширяемость экспортеров — основные концепции](./concepts.md)
* [Создание собственных экспортеров](./custom_exporters.md)
* [Формат экспозиции](../../concepts/metric_types/exposition_format.md)
