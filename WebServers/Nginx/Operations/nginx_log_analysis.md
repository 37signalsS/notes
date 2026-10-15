# Анализ access-логов Nginx (GoAccess и CLI)

## Определения

**Access Log** — журнал доступа Nginx, где на каждый обработанный запрос записывается одна строка. Стандартный формат задаётся `log_format` и по умолчанию выглядит так:

```
127.0.0.1 - - [22/Sep/2026:14:23:11 +0000] "GET /api/users HTTP/1.1" 200 1234 "https://example.com/" "Mozilla/5.0 ..."
```

**GoAccess** — консольный анализатор логов с интерактивным интерфейсом (TUI) и генерацией HTML-отчётов. Отслеживает геолокацию, статусы, медленные URL, уникальных посетителей и латентность в реальном времени.

Анализ access-логов — базовая операционная дисциплина sysadmin/SRE: по логам определяют аномалии трафика, узкие места по статусам, источники 5xx, деградацию латентности и результаты rate limiting.

## Основные концепции

### Почему анализировать access-лог

- **Производительность:** медианы и перцентили `request_time`/`upstream_response_time` выявляют деградацию бэкенда.
- **Надёжность:** распределение по кодам `5xx`, `499` (клиент оборвал), `429` (rate limit) — первые признаки инцидента.
- **Безопасность:** сканирование, брутфорс-паттерны, подозрительные `User-Agent` и необычные гео.
- **Ёмкость:** топ URL и статических файлов показывает, что кэшировать и куда направлять CDN.

### Формат и поля

Для анализа через GoAccess/парсеры нужен **предсказуемый формат**. Два подхода:

1. **default (combined):** `$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent"`.
2. **JSON:** структурированный формат для ELK/Loki/скриптов (`log_format ... escape=json`).

Расширенный формат с метриками апстрима и времени ответа — для перцентилей и диагностики:

```nginx
log_format extended '$remote_addr - $remote_user [$time_local] '
                    '"$request" $status $body_bytes_sent '
                    '"$http_referer" "$http_user_agent" '
                    '"$http_x_forwarded_for" '
                    'rt=$request_time uct=$upstream_connect_time '
                    'urt=$upstream_response_time uaddr=$upstream_addr';
```

### Принцип работы GoAccess

- Парсит лог в реальном времени (tail) или статический файл.
- Определяет формат через `--log-format` или дефолтный `COMBINED`.
- В TUI/HTML показывает панели: Unique visitors, Requested files, Status codes, Referrer, OS/Browsers, Geo, Latency.
- Поддерживает последующие персистентные снимки (`--persist`, `--restore`).

## Практические сценарии

### Предварительные требования

```bash
# Debian/Ubuntu
sudo apt install goaccess

# RHEL/Rocky
sudo dnf install goaccess
```

### Сценарий 1: Быстрый просмотр реального времени (TUI)

```bash
goaccess /var/log/nginx/access.log --log-format=COMBINED
```

Если формат кастомный — укажите его:

```bash
goaccess /var/log/nginx/access.log \
  --log-format='%h %^[%d:%t %^] "%r" %s %b "%R" "%u"'
# → окно TUI с отчётом; [q] выход, [Tab] переключение панелей
```

### Сценарий 2: Генерация HTML-отчёта для команды (cron)

```bash
goaccess /var/log/nginx/access.log --log-format=COMBINED \
  -o /var/www/reports/nginx-report-$(date +%F).html \
  --real-time-html --ignore-crawlers
# → статический отчёт, доступный через любой веб-сервер
```

Для периодичности добавьте в `cron` (раз в сутки) и храните отчёты с ротацией.

### Сценарий 3: CLI-анализ без GoAccess (однострочники)

Когда нужен конкретный срез быстрее, чем открывать отчёт:

```bash
# Топ-10 самых медленных запросов (по времени ответа апстрима)
sort -k1,1 /dev/null; awk '{print $NF, $0}' /var/log/nginx/access.log | sort -rn | head -10

# Активные соединения (stub_status)
curl -s http://localhost/stub_status 2>/dev/null || curl -s http://localhost/nginx_status 2>/dev/null || echo "stub_status не настроен"

# Следить за access log
tail -f /var/log/nginx/access.log | awk '{print $1, $7, $9, $10}'

# Топ 10 запрашиваемых URL
awk '{print $7}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -10

# Топ 10 IP по числу запросов
awk '{print $1}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -10

# Запросы по коду ответа
awk '{print $9}' /var/log/nginx/access.log | sort | uniq -c | sort -rn

# RPS (запросы в секунду) по минутам
awk -v d="$(date '+%d/%b/%Y:%H:%M')" '$4 ~ d {n++} END {print n/60, "rps"} ' /var/log/nginx/access.log

# Топ 10 URL по объёму трафика
awk '{print $7, $10}' /var/log/nginx/access.log | awk '{size[$1]+=$2; n[$1]++} END {for (u in size) print size[u], n[u], u}' | sort -rn | head -10
```

> **Примечание:** поля в `awk` зависят от `log_format`: `$9` — статус, `$7` — URI, `$10` — body bytes в стандартном combined-формате. Проверьте фактическую структуру строки перед использованием.

### Сценарий 4: JSON-формат для централизации (ELK/Loki/«Виктория»)

```nginx
log_format json_main escape=json
'{'
'"time":"$time_iso8601",'
'"remote_addr":"$remote_addr",'
'"request_id":"$request_id",'
'"method":"$request_method",'
'"uri":"$request_uri",'
'"status":$status,'
'"request_time":$request_time,'
'"upstream_response_time":$upstream_response_time,'
'"body_bytes_sent":$body_bytes_sent,'
'"referer":"$http_referer",'
'"user_agent":"$http_user_agent",'
'"x_forwarded_for":"$http_x_forwarded_for"'
'}';
access_log /var/log/nginx/access_json.log json_main;
```

Затем парсинг `jq`:

```bash
jq -r 'select(.status >= 500) | [.time, .uri, .upstream_response_time] | @tsv' /var/log/nginx/access_json.log | head
```

### Сценарий 5: Корреляция с логами бэкенда по request_id

Включив `$request_id` (уникальный ID запроса в Nginx), можно связывать access-лог с error-логами и логами приложения:

```nginx
log_format trace '$remote_addr - $request_id [$time_local] "$request" $status';
access_log /var/log/nginx/trace.log trace;
```

```bash
# Найти request_id проблемного запроса
rg 'HTTP/1.1" 502' /var/log/nginx/access.log | tail -1 | awk '{print $request_id_var}'
# Поиск этого request_id в error-логе Nginx
grep '<request_id>' /var/log/nginx/error.log
```

### Сценарий 6: Централизованный сбор логов (syslog / агенты)

В продакшене логи не живут на самом nginx-хосте: их передают в центральную систему (ELK/Loki/Vector). Два подхода:

1. **Прямая отправка в syslog** — `access_log`/`error_log` пишут сразу в удалённый rsyslog/syslog-ng (или локальный `unix:/dev/log`) без файлов и без необходимости в `logrotate`:

```nginx
http {
    # Access-лог — на удалённый сборщик по UDP:514
    access_log syslog:server=10.0.0.10:514,facility=local7,tag=nginx,severity=info combined;

    # Error-лог — отдельный tag для классификации на приёмнике
    error_log syslog:server=10.0.0.10:514,facility=local6,tag=nginx_error warn;
}
```

Синтаксис `syslog:server=...,facility=...,tag=...,severity=...` идентичен для Nginx OSS и [Angie](../../Angie/angie_logging.md). `severity` — фильтр снизу: сообщения ниже уровня (`debug`/`info`) не отправляются.

2. **JSON-логи + агент-сборщик** (рекомендуется) — Nginx пишет структурированный JSON в файл, а Vector/Promtail/Fluent Bit читает его и шлёт в хранилище. Так проще добавлять поля и парсить, а сам Nginx остаётся независимым от транспортной инфраструктуры.

```bash
# Приём на rsyslog-сервере (/etc/rsyslog.conf): включить UDP-модуль
module(load="imudp")
input(type="imudp" port="514")
local7.* /var/log/nginx/central.log
```

- **Буферизация:** для UDP-сокета syslog применяйте `buffer=32k flush=5s` — одной датаграммой уходит меньше пакетов (уменьшает потери и syscalls).
- **Потери:** UDP может терять датаграммы при переполнении очереди — критичные логи дублируйте отдельным Kafka/Vector-каналом.
- **Проверка приёмника:** `nc -zvu 10.0.0.10 514` (UDP-порт открыт); на сервере `tail -f /var/log/nginx/central.log`.
- Сбор и трансформацию (парсинг, нормализация, маршрутизация в ELK/Loki/ClickHouse) — см. [Централизация и облачные логи](../../../Linux/SystemAdministration/Logging/cloud_logging.md), агенты — [Vector](../../../Vector/vector_overview.md) и [Loki](../../../Loki/loki_overview.md).

## Операции и команды

| Команда | Назначение |
| :--- | :--- |
| `goaccess --help` | Все параметры формата/фильтров |
| `goaccess -f <file> --log-format=COMBINED` | Анализ статического файла |
| `goaccess -f <file> -o out.html --real-time-html` | Живой HTML-отчёт |
| `goaccess -f <file> --ignore-crawlers` | Исключить ботов/краулеров |
| `--invalid-requests=file` | Собрать нераспознанные строки в файл |
| `rg/wc -l access.log` | Счётчик строк и grep-фильтрация |
| `awk` / `sort` / `uniq` | Пайплайн агрегации |
| `nginx -s reopen` | Переоткрытие лог-файлов после ротации |

Ротация логов (должна вызывать `nginx -s reopen`):

```bash
# /etc/logrotate.d/nginx
/var/log/nginx/*.log {
    daily
    rotate 30
    compress
    missingok
    notifempty
    sharedscripts
    postrotate
        [ -f /run/nginx.pid ] && kill -USR1 $(cat /run/nginx.pid)
    endscript
}
```

## Устранение неполадок

### GoAccess: «Unable to parse» / все строки — invalid

**Причина:** формат не совпадает со стандартным; используется кастомный `log_format` или JSON.

**Решение:** укажите `--log-format` вручную; для JSON используйте `jq` или Filebeat/Loki-парсеры, а не GoAccess. Проверьте образец строки: `tail -1 /var/log/nginx/access.log`.

### В логе нет `upstream_response_time` / `request_id`

**Причина:** эти поля есть только в `$log_format`, где они объявлены, либо модуль (`ngx_http_upstream_module`) не включён.

**Решение:** добавьте поля в `log_format` и выполните `nginx -t && nginx -s reload`.

### Пустые ячейки Geo в GoAccess

**Причина:** нет базы геоданных (MaxMind), трафик за внутренним балансировщиком без `X-Forwarded-For`.

**Решение:** укажите `--geoip-database`; для реальных IP за прокси настройте `set_real_ip_from`/`real_ip_header` (см. [Практическая конфигурация балансировки](../Proxy/Load_Balancing/practical_configuration.md)) и логируйте `$http_x_forwarded_for`.

### Медленные запросы не всплывают в отчёте

**Причина:** дефолтный формат GoAccess не разбирает поля времени ответа.

**Решение:** используйте кастомный `--log-format` с `%R` (время ответа) и панель Responses/Latency, либо считайте перцентили awk-скриптом по `rt=`/`urt=`.

## Лучшие практики

- Логируйте `$request_time`, `$upstream_response_time`, `$upstream_addr`, `$upstream_cache_status` в кастомном формате — без них перцентилителях нельзя.
- Храните лог 30–90 дней с ротацией (`logrotate`) и `nginx -s reopen` в postrotate.
- **Никогда не анализируйте раздутый лог напрямую на проде:** копируйте на аналитический хост или читайте stream-момент (`tail -F`).
- Для аномалий статусов алертите на рост `5xx`/`429` по метрике из логов (Prometheus-экспортер или парсинг) — до анализа глазами.
- Пишите access-лог в JSON для централизации, а GoAccess оставляйте для быстрых локальных срезов.
- При использовании `syslog:`-транспорта убирайте файловые пути из `logrotate` для этих логов (ротация на стороне приёмника).
- Настраивайте **алерты на рост `429`/`5xx`** на метриках из централизованных логов, а не по файлам на каждом хосте.
- Периодически чистите старые отчёты и архивы: `/var/log/nginx` не должен расти бесконечно.

## Дополнительная информация

### Связанные темы

- **[Диагностика и устранение неисправностей Nginx](../Operations/nginx_troubleshooting.md)** — разбор типовых ошибок HTTP и методов диагностики.
- **[Наблюдаемость HTTP-сервисов](../../../Networking/Protocols/HTTP/http_monitoring_observability.md)** — метрики stub_status и exporter'ы.
- **[Мониторинг кэширования Nginx](../Performance/Caching/monitoring.md)** — JSON-логи, OpenTelemetry, Prometheus.

### См. также

- [Обзор Nginx](../Core/nginx_overview.md) — архитектура и роли Nginx.
- [Настройка мониторинга Nginx с VTS](../Operations/nginx_vts_monitoring_setup.md) — метрики в Prometheus/Grafana.
- [Логирование в Angie](../../Angie/angie_logging.md) — форматы, `error_log` JSON, syslog, ротация (директивы идентичны Nginx).
- [Централизация и облачные логи](../../../Linux/SystemAdministration/Logging/cloud_logging.md) — сбор, транспорт и хранение на уровне инфраструктуры.