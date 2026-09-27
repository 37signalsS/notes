# Логирование веб-серверов

## Определения

**Access log (лог доступа)** — запись о каждом обработанном запросе: IP клиента, метод, URI, статус ответа, размер ответа, user-agent, время обработки.

**Error log (лог ошибок)** — запись о событиях, требующих внимания: ошибки конфигурации, сбои бэкендов, проблемы TLS, внутренние ошибки.

**Structured logging (структурированное логирование)** — формат логов в виде machine-readable записей (JSON), облегчающий поиск, фильтрацию и агрегацию.

**Log rotation (ротация логов)** — процесс автоматического архивирования и удаления старых лог-файлов для предотвращения заполнения диска.

**Centralized logging (централизованный сбор логов)** — архитектура, при которой логи со всех серверов собираются в единое хранилище для поиска, анализа и алертинга.

**Correlation ID** — уникальный идентификатор запроса, передаваемый через всю цепочку сервисов для связи логов разных компонентов.

**Log level (уровень логирования)** — классификация важности события: `debug`, `info`, `notice`, `warn`, `error`, `crit`, `alert`, `emerg`.

**Buffer** — промежуточный буфер для записи логов, снижающий количество операций ввода-вывода.

---

## Основные концепции

### Форматы access log

| Формат | Пример | Применение |
| :--- | :--- | :--- |
| **Common** | `127.0.0.1 - frank [10/Oct/2026:13:55:36 -0700] "GET /apache_pb.gif HTTP/1.0" 200 2326 "http://www.example.com/start.html" "Mozilla/4.08"` | Простой анализ, совместимость со старыми инструментами. |
| **Combined** | Common + `Referer` + `User-Agent`. | Стандартный формат для Nginx/Apache. |
| **JSON** | `{"remote_addr":"127.0.0.1","request":"GET / HTTP/1.1","status":200,"request_time":0.004}` | Centralized logging, ELK/Loki/OpenSearch. |

### Ротация логов

Ротация предотвращает заполнение диска и упрощает archival.

| Метод | Инструмент | Примечание |
| :--- | :--- | :--- |
| **logrotate** | system utility | Стандартный для Linux. Настраивается через `/etc/logrotate.d/`. |
| **Встроенная ротация** | Nginx/Angie (`max`, `use_dates`, `dynacache`) | Доступна в Nginx Plus и Angie. |
| **copytruncate** | logrotate | Без перезагрузки сервиса. Возможна потеря части логов. |
| **postrotate** | logrotate | Перезагрузка сервиса после ротации. Надежнее, чем `copytruncate`. |

### Централизованный сбор логов

| Инструмент | Роль | Применение |
| :--- | :--- | :--- |
| **Fluentd / Fluent Bit** | Collector / Forwarder | Сбор логов, enrichment, отправка в хранилище. |
| **Loki** | Хранилище и поиск | Экономичное хранение логов, Promtail как agent. |
| **ELK / OpenSearch** | Полный стек | Поиск, анализ, дашборды. Высокое потребление ресурсов. |
| **Promtail** | Agent для Loki | Сбор логов, парсинг, отправка в Loki. |
| **Vector** | High-performance collector | Современный замена Fluentd. |

### Correlation ID

Correlation ID связывает запрос на Edge с вызовами бэкендов.

**Поток:**
1. Edge-прокси (Nginx/HAProxy) генерирует или принимает `X-Request-ID` от клиента.
2. Прокси передает `X-Request-ID` в заголовке бэкенду.
3. Бэкенд включает `X-Request-ID` в свои логи.
4. При наличии цепочки сервисов каждый hop передавает `X-Request-ID` дальше.

---

## Практические сценарии

### Сценарий 1: Access + Error log в Nginx

```nginx
http {
    log_format main '$remote_addr - $remote_user [$time_local] '
                    '"$request" $status $body_bytes_sent '
                    '"$http_referer" "$http_user_agent" '
                    'rt=$request_time';

    access_log /var/log/nginx/access.log main buffer=32k flush=5s;
    error_log /var/log/nginx/error.log warn;

    server {
        listen 80;
        server_name example.com;

        location / {
            proxy_pass http://backend;
            proxy_set_header X-Request-ID $request_id;
        }
    }
}
```

**Ключевые моменты:**
- `buffer` и `flush` снижают количество операций ввода-вывода.
- `log_format` позволяет задавать произвольный формат.
- `$request_id` — встроенная переменная Nginx 1.11.0+ для генерации UUID.

### Сценарий 2: Access + Error log в Apache

```apacheconf
LogLevel warn
ErrorLogFormat "[%{u}t] [%l] [pid %P] %F: %E: [client %a] %M"
CustomLog /var/log/apache2/access.log combined env=!dontlog
ErrorLog /var/log/apache2/error.log
```

**Ключевые моменты:**
- `ErrorLogFormat` позволяет задавать произвольный формат логов ошибок.
- `env=!dontlog` позволяет исключать определенные запросы из access log.
- `LogLevel` задает минимальный уровень логирования (`debug` — самый подробный, `emerg` — только критические ошибки).

### Сценарий 3: Логирование в HAProxy

```haproxy
global
    log /dev/log local0 debug
    log-tag haproxy

defaults
    log global
    option httplog
    option dontlognull

frontend http_frontend
    bind *:80
    mode http
    default_backend http_backend

backend http_backend
    mode http
    balance roundrobin
    option forwardfor
    http-request add-header X-Request-ID %[uuid]
    server web01 192.168.1.10:8080 check
    server web02 192.168.1.11:8080 check
```

**Ключевые моменты:**
- `option httplog` включает подробное HTTP-логирование.
- `option forwardfor` добавляет заголовок `X-Forwarded-For`.
- `%[uuid]` — функция HAProxy для генерации UUID.

### Сценарий 4: Логирование в Traefik

```yaml
log:
  level: INFO
  format: json
  filePath: /var/log/traefik/traefik.log

accessLog:
  format: json
  filePath: /var/log/traefik/access.log
  bufferingSize: 100
```

**Ключевые моменты:**
- Traefik по умолчанию пишет структурированные логи в JSON.
- `bufferingSize` задает размер буфера для access log.
- `filePath` — путь к файлу логов.

### Сценарий 5: Логирование в Angie

```nginx
log_format main '$remote_addr - $remote_user [$time_local] '
                '"$request" $status $body_bytes_sent '
                '"$http_referer" "$http_user_agent" '
                'rt=$request_time';

access_log /var/log/angie/access.log main buffer=32k flush=5s;
error_log /var/log/angie/error.log warn;
```

**Ключевые моменты:**
- Angie наследует синтаксис логирования от Nginx.
- Поддерживается встроенная ротация логов (`use_dates`, `max`).

### Сценарий 6: Ротация логов через logrotate

```
/var/log/nginx/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data adm
    sharedscripts
    postrotate
        if [ -f /var/run/nginx.pid ]; then
            kill -USR1 `cat /var/run/nginx.pid`
        fi
    endscript
}
```

**Ключевые моменты:**
- `daily` — ротация раз в день.
- `rotate 14` — хранение 14 архивов.
- `compress` — сжатие старых логов.
- `postrotate` — перезагрузка Nginx после ротации.

### Сценарий 7: Structured logging в Nginx (JSON)

```nginx
log_format json_combined escape=json
    '{'
        '"time":"$time_iso8601",'
        '"remote_addr":"$remote_addr",'
        '"request":"$request",'
        '"status":$status,'
        '"body_bytes_sent":$body_bytes_sent,'
        '"request_time":$request_time,'
        '"user_agent":"$http_user_agent",'
        '"referer":"$http_referer",'
        '"x_request_id":"$request_id"'
    '}';

access_log /var/log/nginx/access.json.json json_combined;
```

**Ключевые моменты:**
- `escape=json` экранирует специальные символы.
- `$request_id` — встроенная переменная для UUID.
- JSON-формат удобен для Elasticsearch и OpenSearch.

### Сценарий 8: Correlation ID в цепочке прокси

**Nginx (Edge):**
```nginx
log_format json_combined escape=json
    '{'
        '"x_request_id":"$request_id",'
        '"x_forwarded_for":"$proxy_add_x_forwarded_for",'
        '"remote_addr":"$remote_addr",'
        '"request":"$request",'
        '"status":$status'
    '}';

access_log /var/log/nginx/access.log json_combined;

server {
    listen 80;
    server_name example.com;

    location / {
        proxy_pass http://api_backend;
        proxy_set_header X-Request-ID $request_id;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

**Backend (Python/Flask):**
```python
import logging
from flask import Flask, request

app = Flask(__name__)

logging.basicConfig(
    format='%(message)s',
    level=logging.INFO
)
logger = logging.getLogger()

@app.before_request
def log_request():
    x_request_id = request.headers.get('X-Request-ID', '-')
    logger.info(
        '{"x_request_id":"%s","method":"%s","path":"%s"}',
        x_request_id, request.method, request.path
    )
```

**Ключевые моменты:**
- `$request_id` — встроенная переменная Nginx.
- `proxy_set_header` передает заголовок бэкенду.
- Бэкенд включает `X-Request-ID` в свои логи.

---

## Дополнительная информация

### Чек-лист настройки логирования

- [ ] **Access log:** формат `combined` или JSON, ротация раз в день, 14 архивов.
- [ ] **Error log:** уровень `warn` или `error`, ротация раз в день.
- [ ] **Buffer:** включен для access log, `flush=5s`.
- [ ] **Centralized logging:** Fluent Bit или Promtail отправляет логи в Loki или ELK.
- [ ] **Structured logging:** JSON для access и error логов.
- [ ] **Correlation ID:** `X-Request-ID` передается через всю цепочку.
- [ ] **Security:** логи не содержат паролей, секретов, cookies.
- [ ] **Monitoring:** алерты на рост 5xx, рост latency, ошибки TLS.

### См. также

- **[Наблюдаемость HTTP-сервисов](../../Networking/Protocols/HTTP/http_monitoring_observability.md) — RED method, Golden Signals.
- **[Webserver Troubleshooting](../../Concepts/webserver_troubleshooting.md) — методология диагностики.
- **[Runbooks и Incident Response](../../Concepts/runbooks_incident_response.md) — типовые сценарии инцидентов.
- **[Синтетический мониторинг](../../Concepts/synthetic_monitoring.md) — внешние probes.
- **[Webserver Logging Configuration](https://www.nginx.com/resources/wiki/start/topics/examples/full/) — примеры конфигурации Nginx.
- **[Apache Logging](https://httpd.apache.org/docs/2.4/logs.html) — документация Apache по логированию.
- **[HAProxy Logging](https://www.haproxy.org/doc/3.4/configuration.html#logging) — документация HAProxy по логированию.
- **[Fluentd](https://docs.fluentd.org/) — документация Fluentd.
- **[Loki](https://grafana.com/docs/loki/) — документация Loki.
- **[Promtail](https://grafana.com/docs/loki/clients/promtail/) — документация Promtail.
