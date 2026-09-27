# Pushgateway

## Определения

**Pushgateway** — это специализированный сервис-посредник в экосистеме Prometheus, предназначенный для сбора и временного хранения метрик от кратковременных (ephemeral) процессов, batch-заданий или систем, находящихся за Firewall/NAT.

Начиная с версий **v1.9.0–v1.11.3 (2024–2025)**, Pushgateway стал ключевым звеном для интеграции с современными форматами данных, поддерживая нативные гистограммы и UTF-8 имена меток, что обеспечивает полную совместимость с [Prometheus 3.0](./overview.md) и OpenTelemetry.

| Характеристика | Значение |
| :--- | :--- |
| **Актуальная версия** | `v1.11.3` (на момент написания) |
| **Порт по умолчанию** | `9091` |
| **Форматы приема** | Prometheus Text, OpenMetrics, Protobuf |
| **Поддержка UTF-8** | Да (v1.11.0+, через флаг `--push.enable-utf8-names`) |
| **Native Histograms** | Да (v1.9.0+) |
| **Режим хранения** | Оперативная память с опциональным сбросом на диск (`--persistence.file`) |
| **Встроенная аутентификация** | Нет (требуется `--web.config.file` или внешний прокси) |

> **Важно:** Pushgateway предназначен ТОЛЬКО для кратковременных задач. Для долгоживущих сервисов используйте Pull-модель (эндпоинт `/metrics` на приложении) или OTLP.
>
> **Установка:** Детальные инструкции по развертыванию приведены в разделе **[Установка Pushgateway](./installation/pushgateway_installation.md)**.

## Основные концепции

### Принцип работы: Push-to-Pull Bridge

Pushgateway преобразует активную отправку данных (Push) в пассивное ожидание запроса (Pull):

1.  **Push:** Инструментированное приложение отправляет метрики через HTTP POST/PUT. Данные принимаются в форматах Protobuf или Text.
2.  **Aggregation/Persistence:** Pushgateway группирует метрики и сохраняет их в памяти. Если включен флаг `--persistence.file`, данные периодически сбрасываются на диск для выживания при перезапуске.
3.  **Pull (Scraping):** Prometheus опрашивает `/metrics` на Pushgateway, забирая все накопленные группы за один раз.

### Группировка и кодирование (Grouping Key)

Данные в хранилище разделены на «бакеты» по **Ключу группировки**. Это уникальный набор меток, идентифицирующий источник.

*   **Обязательная метка:** `job` (всегда должна присутствовать в URL).
*   **Дополнительные метки:** Любое количество пар `key/value` в пути URL.
*   **Base64 кодирование:** Если значение метки содержит спецсимволы (например, путь `/var/log`), используется формат `@base64`.
    *   *Пример:* `/metrics/job/backup/path@base64/L3Zhci9sb2c=`

### Метрики самомониторинга Pushgateway

Pushgateway автоматически экспонирует собственные метрики на эндпоинте `/metrics`:

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `pushgateway_build_info` | Gauge | Версия и информация о сборке. |
| `pushgateway_http_requests_total` | Counter | Количество HTTP-запросов по методам и кодам ответа. |
| `pushgateway_http_request_duration_seconds` | Histogram | Длительность обработки HTTP-запросов. |
| `pushgateway_persisted_strings_total` | Gauge | Количество строк, сохраненных на диск (при включенном persistence). |

Эти метрики позволяют мониторить сам Pushgateway. Для их сбора в `prometheus.yml` добавьте отдельный `job_name: 'pushgateway-self'` с `honor_labels: true`.

### Ресурсные характеристики

| Ресурс | Минимум | Рекомендуется | Примечание |
| :--- | :--- | :--- | :--- |
| **RAM** | 64 MiB | 128–256 MiB | Потребление растет с количеством уникальных `grouping keys` (~1–2 KB на группу). |
| **Диск** | 10 MiB | 1–5 GiB | Зависит от `--persistence.file` и частоты `--persistence.interval`. |
| **CPU** | Незначительный | 0.1–0.5 core | Нагрузка возникает при массовой отправке или частом скрейпинге. |

### Сетевая топология и Firewall/NAT

Pushgateway работает как приемный шлюз:

1.  **Входящий трафик (Push):** Приложения-отправители должны иметь TCP-доступ к порту `9091` Pushgateway. В конфигурациях с NAT/Firewall это означает, что Pushgateway должен быть доступен из внутренней сети, откуда запускаются задачи.
2.  **Исходящий трафик (Pull):** Prometheus Server должен иметь TCP-доступ к порту `9091` Pushgateway для сбора метрик.
3.  **Минимальные правила Firewall:**
    ```bash
    # Разрешить только доверенным отправителям (пример iptables)
    iptables -A INPUT -p tcp --dport 9091 -s 10.0.0.0/8 -j ACCEPT
    iptables -A INPUT -p tcp --dport 9091 -s 172.16.0.0/12 -j ACCEPT
    iptables -A INPUT -p tcp --dport 9091 -j DROP
    ```

### Современные возможности (v1.11+)

*   **Нативные гистограммы (Native Histograms):** Поддержка экспоненциальных бакетов без ручной настройки границ. Pushgateway корректно хранит и отдает их Prometheus 3.0.
*   **UTF-8 Имена (UTF-8 Names):** Позволяет использовать точки и пробелы в именах метрик (например, `http.server.duration`). Требуется запуск с флагом `--push.enable-utf8-names`.
*   **Metadata:** Поддержка передачи метаданных (HELP/TYPE) от клиентов к серверу Prometheus.

### Опасности и антипаттерны

Использование Pushgateway — это крайняя мера. Основные риски:

| Проблема | Описание | Последствия |
| :--- | :--- | :--- |
| **Устаревание (Staleness)** | Метрики не имеют встроенного TTL. Если процесс завершился с ошибкой и не отправил данные, в мониторинге останется «старое» значение. | Ложноположительные алерты или скрытые сбои. |
| **Слепое пятно `up`** | Метрика `up` показывает статус Pushgateway, а не вашей задачи. | Невозможно определить, жива ли Cron-задача, без дополнительных `timestamp` меток. |
| **Ресурсный голод** | Каждая группа меток занимает RAM. Большое количество уникальных `grouping keys` может привести к OOM. | Падение всей системы сбора для всех эфемерных задач. |
| **Отсутствие репликации** | Pushgateway — это singleton. При его падении новые метрики не принимаются, а не сброшенные на диск данные теряются. | Разрыв в мониторинге. |
| **Гоночный доступ (Race Condition)** | Несколько экземпляров задачи, запущенных одновременно, могут перезаписывать метрики друг друга при использовании одного и того же `grouping key`. | Потеря данных, некорректные алерты. |

### Выбор: Pushgateway или Textfile Collector

| Критерий | Pushgateway | Textfile Collector (node_exporter) |
| :--- | :--- | :--- |
| **Сетевая доступность** | Требует сетевого доступа к шлюзу | Достаточно записи в файл на локальной ФС |
| **Надежность доставки** | Зависит от доступности Pushgateway | Зависит от node_exporter |
| **Сетевая изоляция** | Подходит для систем за NAT/Firewall | Подходит для локальных скриптов |
| **Сложность** | Средняя (требует развертывания) | Низкая (часть node_exporter) |
| **Кардинальность** | Средняя (ограничена памятью шлюза) | Низкая (все метрики под одним job) |
| **Пример использования** | Batch-задачи в кластере, CI/CD пайплайны | Локальные cron-задачи на сервере |

## Практические сценарии

### Отправка метрик из скрипта (Bash)

Типовой сценарий для мониторинга CronJob. Используется метод **POST** для добавления данных в группу.

```bash
# Генерация метрик и отправка в Pushgateway
cat <<EOF | curl --data-binary @- http://localhost:9091/metrics/job/daily_backup/instance/app-server-01
# HELP backup_duration_seconds Длительность выполнения бэкапа.
# TYPE backup_duration_seconds gauge
backup_duration_seconds 154.5
# HELP backup_last_success_timestamp Время последнего успешного запуска (Unix timestamp).
# TYPE backup_last_success_timestamp gauge
backup_last_success_timestamp $(date +%s)
EOF
```

### Использование `pushadd` для счетчиков

Для метрик, которые должны расти (например, общее количество обработанных файлов за все запуски), используйте утилиту `pushadd`. Она добавляет значение к существующему, вместо перезаписи:

```bash
# Файлы, обработанные за этот запуск: 42
echo "backup_files_processed_total 42" | curl --data-binary @- \
  --request POST \
  --header "Content-Type: text/plain" \
  http://localhost:9091/metrics/job/backup_job/instance/app-server-01/pushadd
# → Метрика будет увеличена на 42
```

### Мониторинг Cron-задачи через systemd timer

Пример интеграции systemd timer с Pushgateway. Используйте `OnCalendar` для запуска и отправляйте метрики статуса:

```ini
# /etc/systemd/system/backup.service
[Unit]
Description=Database Backup

[Service]
Type=oneshot
ExecStart=/usr/local/bin/backup.sh
# Отправка результата в Pushgateway
ExecStopPost=/usr/local/bin/report_backup_status.sh
```

```bash
# /usr/local/bin/report_backup_status.sh
#!/bin/bash
STATUS=$EXIT_STATUS
END=$(date +%s)

cat <<EOF | curl --data-binary @- \
  http://localhost:9091/metrics/job/db_backup/instance/db-primary
# TYPE backup_status gauge
backup_status $STATUS
# TYPE backup_last_success_timestamp gauge
backup_last_success_timestamp $END
EOF
```

### Интеграция с Ansible

Пример отправки метрик из Ansible-плейбука через модуль `uri`:

```yaml
- name: Отправка метрик в Prometheus Pushgateway
  uri:
    url: "http://pushgateway:9091/metrics/job/ansible_deploy/instance/{{ inventory_hostname }}"
    method: PUT
    body: |
      # HELP deploy_status Статус деплоя (1 — успех)
      # TYPE deploy_status gauge
      deploy_status 1
      # HELP deploy_timestamp Время деплоя
      # TYPE deploy_timestamp gauge
      deploy_timestamp {{ ansible_date_time.epoch }}
    body_format: raw
    headers:
      Content-Type: text/plain
  delegate_to: localhost
```

### Решение проблемы Staleness (Очистка)

Поскольку Pushgateway хранит данные вечно, необходимо явно удалять их после завершения работы или при обнаружении устаревания.

**Вариант 1: Удаление после успешного завершения (Bash)**
```bash
# Выполнить задачу...
./my_backup.sh
# Если успех — удалить метрику об ошибке из шлюза
if [ $? -eq 0 ]; then
  curl -X DELETE http://localhost:9091/metrics/job/daily_backup/instance/app-server-01
fi
```

**Вариант 2: Использование `last_success_timestamp` в алерте**
Вместо того чтобы полагаться на отсутствие данных, проверяйте время последнего обновления:
`time() - backup_last_success_timestamp > 86400` — алерт, если бэкапа не было больше суток.

**Вариант 3: Периодическая очистка по TTL**
Для автоматической очистки устаревших метрик можно использовать cron-задачу, которая удаляет группы старше N дней через HTTP API:

```bash
# Удалить группу job=old_job, если она старше 7 дней
# Примечание: Pushgateway не имеет встроенного TTL, поэтому требуется внешний скрипт
# или использование Prometheus recording rules для детекции stale-данных
```

### Kubernetes CronJob с Pushgateway

Пример CronJob, отправляющего метрики статуса в Pushgateway:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: db-backup
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: backup-image:latest
            command: ["/bin/bash", "-c"]
            args:
            - |
              ./backup.sh
              STATUS=$?
              END=$(date +%s)
              cat <<EOF | curl --data-binary @- \
                http://pushgateway.monitoring.svc:9091/metrics/job=db_backup/instance=db-primary
              # TYPE backup_status gauge
              backup_status $STATUS
              # TYPE backup_last_success_timestamp gauge
              backup_last_success_timestamp $END
              EOF
            env:
            - name: PUSHGATEWAY_URL
              value: "http://pushgateway.monitoring.svc:9091"
          restartPolicy: OnFailure
```

### Настройка Prometheus (honor_labels)

Для корректного сбора данных в `prometheus.yml` **обязательно** установите `honor_labels: true`. Без этого Prometheus перепишет ваши метки своими (например, `job="pushgateway"`), что сделает невозможным фильтрацию по конкретным задачам.

```yaml
scrape_configs:
  - job_name: 'pushgateway'
    honor_labels: true
    static_configs:
      - targets: ['localhost:9091']
```

### Self-Monitoring: Мониторинг Pushgateway

Настройте отдельный `job` для мониторинга самого Pushgateway:

```yaml
scrape_configs:
  - job_name: 'pushgateway-self'
    honor_labels: true
    static_configs:
      - targets: ['pushgateway:9091']
```

Пример алертов для Pushgateway:

```yaml
groups:
  - name: pushgateway_alerts
    rules:
      - alert: PushgatewayDown
        expr: up{job="pushgateway-self"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Pushgateway недоступен ({{ $labels.instance }})"
          description: "Экземпляр Pushgateway на {{ $labels.instance }} не отвечает более 1 минуты."

      - alert: PushgatewayHighMemoryUsage
        expr: pushgateway_persisted_strings_total > 10000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокое количество групп в Pushgateway ({{ $labels.instance }})"
          description: "Количество уникальных grouping keys превышает 10000. Проверьте cleanup-логику."

      - alert: PushgatewayRequestErrors
        expr: rate(pushgateway_http_requests_total{code=~"5.."}[5m]) > 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Ошибки 5xx на Pushgateway ({{ $labels.instance }})"
          description: "Pushgateway возвращает ошибки 5xx. Проверьте логи и ресурсы."
```

### Python-клиент для Pushgateway

Пример отправки метрик с использованием библиотеки `prometheus-client`:

```python
from prometheus_client import CollectorRegistry, Gauge, pushadd_to_gateway

registry = CollectorRegistry()
g = Gauge('backup_duration_seconds', 'Длительность бэкапа', registry=registry)
g.set(154.5)

pushadd_to_gateway('localhost:9091', job='daily_backup', registry=registry)
# → Метрика отправлена в Pushgateway
```

### Отправка метрик из PowerShell (Windows)

Для Windows-окружений (SRE в гетерогенных средах):

```powershell
$body = @"
# HELP backup_duration_seconds Длительность бэкапа
# TYPE backup_duration_seconds gauge
backup_duration_seconds 154.5
"@

Invoke-RestMethod -Uri "http://pushgateway:9091/metrics/job/windows_backup" `
  -Method Post -Body $body -ContentType "text/plain"
```

## Дополнительная информация

### Управление через HTTP API

| Метод | Путь | Описание |
| :--- | :--- | :--- |
| **POST** | `/metrics/job/<JOBNAME>[/<L>/<V>]` | **Добавляет** метрики. Если в группе уже есть метрики с другими именами, они сохраняются. |
| **PUT** | `/metrics/job/<JOBNAME>[/<L>/<V>]` | **Заменяет** всю группу. Все старые метрики в этой группе удаляются. |
| **DELETE** | `/metrics/job/<JOBNAME>[/<L>/<V>]` | **Удаляет** всю группа (бакет) целиком. |
| **PUT** | `/-/wipe` | Очистка всех данных (требует `--web.enable-admin-api`). |

### Проверка работоспособности HTTP API

```bash
# Проверка доступности
curl -s http://localhost:9091/metrics | head -n 5
# → # HELP pushgateway_build_info Build information

# Проверка отправки (POST)
echo "# TYPE test_metric gauge
test_metric 1" | curl --data-binary @- http://localhost:9091/metrics/job=test

# Проверка замены (PUT)
echo "# TYPE test_metric gauge
test_metric 2" | curl --data-binary @- --request PUT \
  http://localhost:9091/metrics/job=test

# Проверка удаления (DELETE)
curl -X DELETE http://localhost:9091/metrics/job=test
# → Метрика удалена
```

### Ключевые параметры запуска (Flags)

| Флаг | Описание |
| :--- | :--- |
| `--push.enable-utf8-names` | (v1.11+) Разрешает точки и спецсимволы в именах метрик. |
| `--persistence.file` | Путь к файлу для сохранения данных при перезапуске (`metrics.store`). |
| `--persistence.interval` | Частота сброса RAM на диск (по умолчанию 5m). |
| `--web.enable-admin-api` | Разрешает использование эндпоинта `/-/wipe` для очистки всех данных. |
| `--web.config.file` | Путь к файлу с настройками TLS и Basic Auth (см. [Безопасность](./security.md)). |
| `--web.listen-address` | Адрес и порт для прослушивания (по умолчанию `:9091`). |
| `--log.level` | Уровень логирования: `debug`, `info`, `warn`, `error`. |

### Настройка Basic Auth и TLS (встроенная)

Для защиты Pushgateway без внешнего прокси используйте `--web.config.file`:

```yaml
# /etc/pushgateway/web-config.yml
tls_server_config:
  cert_file: /etc/pushgateway/certs/server.crt
  key_file: /etc/pushgateway/certs/server.key

basic_auth_users:
  admin: "$2y$12$LQvPHiM/N.S.B.bcrypt.hash.here"
```

Запуск:
```bash
pushgateway --web.config.file=/etc/pushgateway/web-config.file
```

Валидация:
```bash
# Должен вернуть 401 без авторизации
curl -s -o /dev/null -w "%{http_code}" http://localhost:9091/metrics
# → 401

# Должен вернуть 200 с авторизацией
curl -u admin:password http://localhost:9091/metrics | head -n 3
# → # HELP pushgateway_build_info ...
```

### Troubleshooting: типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Метки `job` затираются | `honor_labels: false` в `prometheus.yml` | Установите `honor_labels: true`. |
| Ошибка 400 при отправке | Недопустимые имена меток или UTF-8 без флага | Добавьте `--push.enable-utf8-names`. |
| Данные исчезают после рестарта | Нет флага `--persistence.file` | Укажите путь к файлу хранения в параметрах запуска. |
| Память переполнена (OOM) | Накопление старых метрик без очистки | Реализуйте удаление через `DELETE` или TTL-скрипт. |
| `Connection refused` на 9091 | Сервис не запущен | `systemctl status pushgateway` / `docker ps` / `kubectl get pods`. |
| Метрики дублируются | Неправильный Grouping Key | Убедитесь, что `job` и дополнительные метки уникальны. |
| `stale nan` не работает | Метрика не имеет timestamp или использует старый client_golang | Обновите клиентскую библиотеку до версии с поддержкой stale markers. |
| Pushgateway не принимает POST на `/metrics` | Отсутствует `job` в URL | Используйте `/metrics/job/<JOBNAME>`. |

### Best Practices

1.  **Всегда используйте `job`:** Без `job` в URL Pushgateway вернет `400 Bad Request`.
2.  **Используйте `instance`:** Добавляйте `instance` для идентификации источника, особенно при наличии нескольких отправителей.
3.  **Очищайте после успеха:** Удаляйте метрики после успешного выполнения задачи (DELETE) или отправляйте `last_success_timestamp`.
4.  **Ограничьте `grouping keys`:** Не создавайте уникальные ключи для каждого запуска (например, с временной меткой в `instance`). Это приведет к OOM.
5.  **Мониторьте Pushgateway:** Настройте алерты на `up{job="pushgateway-self"}` и количество групп.
6.  **Используйте Persistence:** Для production включите `--persistence.file` для сохранения данных при рестарте.
7.  **Ограничьте сетевой доступ:** Разрешите порт `9091` только доверенным отправителям и Prometheus Server.

### Ограничения и Edge Cases

1.  **No TTL:** Pushgateway хранит данные бесконечно. При сбое отправителя данные остаются «вечными».
2.  **No Replication:** Нет встроенной репликации. Для HA требуется внешний балансировщик (не рекомендуется, так как данные не синхронизируются между инстансами).
3.  **Race Condition:** Параллельные задачи с одинаковым `grouping key` могут перезаписывать метрики друг друга.
4.  **Large Payloads:** Очень большие payload (>10 MB) могут вызвать таймауты или утечки памяти. Рекомендуется ограничивать размер тела запроса на стороне прокси.
5.  **Protobuf Format:** Поддержка Protobuf требует соответствующих заголовков (`Content-Type: application/vnd.google.protobuf`). Проверьте поддержку в вашей клиентской библиотеке.

### Связанные ресурсы

- **[Установка Pushgateway](./installation/pushgateway_installation.md)** — unit-файлы и Docker-контейнеры.
- **[Scrape-модель Prometheus](./overview.md)** — почему Pull лучше Push в большинстве случаев.
- **[Безопасность стека мониторинга](./security.md)** — как защитить Pushgateway от записи посторонними.
- **[Клиентские библиотеки](./Exporters/extensibility/client_libraries.md)** — нативная поддержка Pushgateway в Go, Python, Java.
- **[Textfile Collector](./Exporters/extensibility/textfile_collector.md)** — альтернатива Pushgateway для локальных скриптов.
- **[Типы метрик: Gauge](./concepts/metric_types/gauge.md)** — использование Gauge в пакетных задачах через Pushgateway.
