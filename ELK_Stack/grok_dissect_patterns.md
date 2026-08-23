# Grok и Dissect Patterns: Коллекция рецептов

> Практические паттерны для парсинга логов в Logstash и Ingest Pipelines. Grok и Dissect выражения для типовых форматов.
>
> Связанные темы: Ingest Pipelines — [Ingest Pipelines](./Elasticsearch/elasticsearch_ingest_pipelines.md); Logstash — [Logstash Pipelines](./Logstash/logstash_pipelines.md).

## Определения

* **Grok** — регулярные выражения для структурирования строк. Использует именованные паттерны.
* **Dissect** — шаблонное разбиение строк по разделителям (быстрее grok).
* **Pattern** — именованное регулярное выражение (например, `%{TIMESTAMP_ISO8601}`).
* **Grok Debugger** — инструмент для тестирования grok выражений.

## Основные Grok Patterns

### Базовые паттерны

| Паттерн | Описание | Пример |
|---------|----------|--------|
| `%{WORD}` | Слово (alphanumeric) | `hello123` |
| `%{NUMBER}` | Число | `42`, `3.14` |
| `%{INT}` | Целое число | `42` |
| `%{BASE10NUM}` | Decimal number | `3.14` |
| `%{BASE16NUM}` | Hex number | `0xFF` |
| `%{NOTSPACE}` | Любой символ кроме пробела | `hello-world` |
| `%{DATA}` | Любой символ (lazy) | любой текст |
| `%{GREEDYDATA}` | Любой символ (greedy) | любой текст |
| `%{SPACE}` | Пробельные символы | ` `, `\t` |

### Временные метки

| Паттерн | Описание | Пример |
|---------|----------|--------|
| `%{TIMESTAMP_ISO8601}` | ISO 8601 | `2026-08-23T10:30:00.000Z` |
| `%{DATE}` | Дата | `Aug 23, 2026` |
| `%{DATE_US}` | US формат | `08/23/2026` |
| `%{DATE_EU}` | EU формат | `23.08.2026` |
| `%{TIME}` | Время | `10:30:00` |

### Сетевые данные

| Паттерн | Описание | Пример |
|---------|----------|--------|
| `%{IP}` | IP адрес | `192.168.1.1` |
| `%{IPV4}` | IPv4 | `192.168.1.1` |
| `%{IPV6}` | IPv6 | `2001:db8::1` |
| `%{HOSTNAME}` | Имя хоста | `server1.company.com` |
| `%{URI}` | URI | `http://example.com/path` |
| `%{PATH}` | Путь | `/var/log/nginx` |
| `%{MAC}` | MAC адрес | `00:11:22:33:44:55` |

### HTTP и Web

| Паттерн | Описание | Пример |
|---------|----------|--------|
| `%{URIPROTO}` | Протокол | `http`, `https` |
| `%{URIHOST}` | Host | `example.com:8080` |
| `%{URIPATHPARAM}` | Путь с параметрами | `/path?q=1` |
| `%{URIPATH}` | Путь | `/path/to` |
| `%{URIQUERY}` | Query string | `?q=1&b=2` |

### Логи

| Паттерн | Описание | Пример |
|---------|----------|--------|
| `%{LOGLEVEL}` | Уровень лога | `ERROR`, `WARN`, `INFO` |
| `%{SYSLOGTIMESTAMP}` | Syslog timestamp | `Aug 23 10:30:00` |
| `%{SYSLOGHOST}` | Syslog host | `server1` |
| `%{SYSLOGPROG}` | Syslog program | `nginx[1234]` |

## Типовые форматы логов

### Nginx Access Log

**Формат:** `combined`

```
192.168.1.1 - - [23/Aug/2026:10:30:00 +0000] "GET /api/users HTTP/1.1" 200 1234 "https://example.com" "Mozilla/5.0" "10.0.0.1"
```

**Grok:**

```grok
%{IP:client_ip} %{USER:ident} %{USER:auth} \[%{HTTPDATE:timestamp}\] "%{WORD:method} %{URIPATHPARAM:request} HTTP/%{NUMBER:http_version}" %{INT:status} %{INT:bytes} %{QS:referrer} %{QS:user_agent} %{QS:forwarded_for}
```

**Dissect (быстрее):**

```
{%{client_ip}} {%{ident}} {%{auth}} [{%{timestamp}}] "%{method} %{request} HTTP/%{http_version}" %{status} %{bytes} %{referrer} %{user_agent} %{forwarded_for}
```

### Nginx Error Log

**Формат:**

```
2026/08/23 10:30:00 [error] 1234#0: *5678 connect() failed (111: Connection refused)
```

**Grok:**

```grok
%{DATESTAMP:timestamp} \[%{LOGLEVEL:level}\] %{INT:pid}#%{INT:tid}: \(%{INT:connection}\) %{GREEDYDATA:message}
```

### Apache Access Log

**Формат:** `combined`

```
127.0.0.1 - frank [10/Oct/2000:13:55:36 -0700] "GET /apache_pb.gif HTTP/1.0" 200 2326 "http://www.example.com/start.html" "Mozilla/4.08"
```

**Grok:**

```grok
%{IP:client_ip} %{USER:ident} %{USER:auth} \[%{HTTPDATE:timestamp}\] "%{WORD:method} %{URIPATHPARAM:request} HTTP/%{NUMBER:http_version}" %{INT:status} %{INT:bytes} %{QS:referrer} %{QS:user_agent}
```

### Apache Error Log

**Формат:**

```
[Sun Aug 23 10:30:00.000000 2026] [mpm_event:info] [pid 1234:tid 5678] AH00491: caught SIGTERM, shutting down
```

**Grok:**

```grok
\[%{HTTPDATE:timestamp}\] \[%{DATA:module}:%{LOGLEVEL:level}\] \[pid %{INT:pid}:tid %{INT:tid}\] %{GREEDYDATA:message}
```

### Syslog

**Формат:** RFC 3164

```
<34>Aug 23 10:30:00 server1 sshd[1234]: Failed password for root from 192.168.1.1 port 22 ssh2
```

**Grok:**

```grok
<%{POSINT:priority}>%{SYSLOGTIMESTAMP:timestamp} %{SYSLOGHOST:hostname} %{SYSLOGPROG:program}: %{GREEDYDATA:message}
```

**Dissect:**

```
<%{priority}>{%{timestamp}} %{hostname} %{program}: %{message}
```

### Syslog RFC 5424

**Формат:**

```
<165>1 2026-08-23T10:30:00.000Z server1 app 1234 ID47 [exampleSDID@32473 iut="3"] Application event
```

**Grok:**

```grok
<%{POSINT:priority}>%{INT:version} %{TIMESTAMP_ISO8601:timestamp} %{HOSTNAME:hostname} %{NOTSPACE:appname} %{NOTSPACE:procid} %{NOTSPACE:msgid} \[%{DATA:structured_data}\] %{GREEDYDATA:message}
```

### Application Log (JSON)

**Формат:**

```json
{"timestamp":"2026-08-23T10:30:00Z","level":"ERROR","message":"Connection failed","trace_id":"abc123"}
```

**Logstash filter:**

```ruby
json {
  source => "message"
  target => "parsed"
}
```

### Application Log (Plain Text)

**Формат:**

```
2026-08-23 10:30:00.123 [main] ERROR com.example.Service - Connection failed
```

**Grok:**

```grok
%{TIMESTAMP_ISO8601:timestamp} \[%{WORD:thread}\] %{LOGLEVEL:level} %{JAVACLASS:class} - %{GREEDYDATA:message}
```

### Docker Log

**Формат:**

```
2026-08-23T10:30:00.123456789Z stdout F 2026-08-23 10:30:00 INFO Application started
```

**Grok:**

```grok
%{TIMESTAMP_ISO8601:docker_timestamp} %{WORD:stream} %{WORD:flag} %{TIMESTAMP_ISO8601:timestamp} %{LOGLEVEL:level} %{GREEDYDATA:message}
```

### Kubernetes Log

**Формат:**

```
2026-08-23T10:30:00.123456789Z stderr F I0823 10:30:00.123456       1 main.go:42] Starting server
```

**Grok:**

```grok
%{TIMESTAMP_ISO8601:kube_timestamp} %{WORD:stream} %{WORD:flag} %{DATA:log_message}
```

### MySQL Slow Query Log

**Формат:**

```
# Time: 2026-08-23T10:30:00.123456Z
# User@Host: root[root] @ localhost [127.0.0.1]  Id:     1
# Query_time: 2.345678  Lock_time: 0.000123 Rows_sent: 1000  Rows_examined: 100000
SELECT * FROM users WHERE last_login > '2026-01-01';
```

**Grok:**

```grok
# Time: %{TIMESTAMP_ISO8601:timestamp}\n# User@Host: %{USER:user}\[%{USER:user}\] @ %{HOSTNAME:host} \[%{IP:ip}\]  Id:     %{INT:connection_id}\n# Query_time: %{NUMBER:query_time}  Lock_time: %{NUMBER:lock_time} Rows_sent: %{INT:rows_sent}  Rows_examined: %{INT:rows_examined}\n%{GREEDYDATA:query}
```

### PostgreSQL Log

**Формат:**

```
2026-08-23 10:30:00.123 UTC [1234] LOG:  duration: 2345.678 ms  statement: SELECT * FROM users;
```

**Grok:**

```grok
%{TIMESTAMP_ISO8601:timestamp} %{WORD:timezone} \[%{INT:pid}\] %{LOGLEVEL:level}:  duration: %{NUMBER:duration_ms} ms  statement: %{GREEDYDATA:query}
```

### Windows Event Log

**Формат:**

```
Log Name: Application
Source: Application Error
Event ID: 1000
Level: Error
User: N/A
Message: Faulting application name: myapp.exe
```

**Grok:**

```grok
Log Name: %{DATA:log_name}\nSource: %{DATA:source}\nEvent ID: %{INT:event_id}\nLevel: %{LOGLEVEL:level}\nUser: %{DATA:user}\nMessage: %{GREEDYDATA:message}
```

## Dissect: Продвинутые паттерны

### Скобки и специальные символы

```
# Если поле содержит разделитель, используйте skiptags
Message: [client=192.168.1.1] [server=web01] error occurred

{%+client} ] [{%+server}] %{message}
```

### Pad для выравнивания

```
# Pad заполняет пробелами для фиксированной ширины
%{?ignored}        # skip (не сохранять)
%{+field}          # append к предыдущему полю
```

## Custom Patterns

### Создание custom patterns

```bash
# patterns/custom
NGINX_ERROR \[%{DATA:timestamp}\] \[%{LOGLEVEL:level}\] %{INT:pid}#%{INT:tid}: %{GREEDYDATA:message}
```

**Использование:**

```ruby
grok {
  patterns_dir => ["/etc/logstash/patterns"]
  match => { "message" => "%{NGINX_ERROR:nginx_error}" }
}
```

## Grok vs Dissect

### Сравнение

| Критерий | Grok | Dissect |
|----------|------|---------|
| Скорость | Медленнее | В 10-100 раз быстрее |
| Гибкость | Высокая | Ограничена |
| Фиксированный формат | Плохо | Отлично |
| Вариативный формат | Отлично | Плохо |
| Readability | Хуже | Лучше |
| Регулярные выражения | Да | Нет |

### Когда использовать

**Dissect:**
- Фиксированный формат с разделителями
- Syslog, CSV, key-value
- Высокая производительность важна

**Grok:**
- Вариативный формат
- Сложные строки с optional полями
- Нужны регулярные выражения

## Отладка Grok

### Kibana Grok Debugger

1. Перейти в **Dev Tools > Grok Debugger**
2. Ввести sample data
3. Ввести grok pattern
4. Проверить результат

### Logstash для отладки

```ruby
output {
  stdout {
    codec => rubydebug
  }
}
```

## Best Practices

1. **Используйте Dissect** где возможно — значительный performance boost
2. **Тестируйте patterns** с разными sample data
3. **Используйте custom patterns** для повторяющихся выражений
4. **fallback patterns** — обрабатывайте неожиданные форматы
5. **Tag unmatched documents** для отладки:

```ruby
grok {
  match => { "message" => "%{PATTERN}" }
  tag_on_failure => ["_grok_parse_failure"]
}
```

6. **Conditional parsing** — разные patterns для разных типов логов:

```ruby
if [type] == "nginx" {
  grok { ... }
} else if [type] == "syslog" {
  grok { ... }
}
```

## См. также

* **[Ingest Pipelines](../Elasticsearch/elasticsearch_ingest_pipelines.md)** — grok processor в Elasticsearch.
* **[Logstash: Обзор](../Logstash/logstash_overview.md)** — grok, dissect фильтры в Logstash.
* **[Logstash: Конвейеры и фильтры](../Logstash/logstash_pipelines.md)** — оптимизация парсинга.
* **[Elasticsearch: Обзор](../Elasticsearch/elasticsearch_overview.md)** — архитектура и маппинг.
* **[Filebeat: Обзор](../filebeat_overview.md)** — parsers в Filebeat.
* **[Kibana: Поиск и визуализация](../Kibana/kibana_search_and_visualization.md)** — Grok Debugger.
