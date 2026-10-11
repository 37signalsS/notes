# Grok и Dissect Patterns: Коллекция рецептов

**Актуально для:** Logstash 8.x/9.x, Elasticsearch 8.x/9.x (ingest processors), Filebeat 8.x/9.x

> Практические паттерны для парсинга логов в Logstash, ingest-пайплайнах Elasticsearch и Filebeat. Grok и Dissect выражения для типовых форматов.
>
> Связанные темы: Ingest Pipelines — [Ingest Pipelines](./Elasticsearch/elasticsearch_ingest_pipelines.md); Logstash — [Logstash Pipelines](./Logstash/logstash_pipelines.md).

## Определения

* **Grok** — структурирование строк через регулярные выражения с переиспользуемыми именованными паттернами (движок Oniguruma). Синтаксис: `%{PATTERN:field}`.
* **Dissect** — разбиение строки по фиксированным разделителям без регулярных выражений. Синтаксис: `%{field}`.
* **Pattern** — именованное регулярное выражение из библиотеки [logstash-patterns-core](https://github.com/logstash-plugins/logstash-patterns-core) (например, `%{TIMESTAMP_ISO8601}`).
* **ECS (Elastic Common Schema)** — соглашение об именах полей; grok-фильтр и grok-процессор выдают ECS-имена при `ecs_compatibility => "v1"`.
* **Composite pattern** — составной паттерн, собранный из других (например, `%{HTTPD_COMBINEDLOG}`).
* **Grok Debugger** — инструмент тестирования grok-выражений в Kibana (Dev Tools → Grok Debugger).

## Основные концепции

### Как работает grok

Grok компилирует шаблон в регулярное выражение: каждый `%{PATTERN:field}` заменяется определением паттерна, совпадение сохраняется в именованный capture. Важные свойства:

- **Совпадение не якорится неявно** — шаблон может матчить подстроку в любом месте значения. Для строгого соответствия строки якорите шаблон вручную: `^%{PATTERN}$`.
- **Жадность** — `%{DATA}` (`.*?`) захватывает минимум, `%{GREEDYDATA}` (`.*`) — максимум. Жадный паттерн в середине шаблона «съедает» всё до конца строки и ломает последующие поля.
- **Опциональные части** — оборачивайте в `(?:...)?`, иначе строка без этой части не заматчится.
- **Типы** — все захваты по умолчанию строки; числовые конверсии задаются суффиксом: `%{NUMBER:bytes:int}`, `%{NUMBER:ratio:float}`.

### Как работает dissect

Dissect разбивает строку за один проход: текст между `%{...}` — это разделитель (delimiter), который должен встретиться в строке буквально и в том же порядке. Свойства:

- **Строгость** — все разделители должны совпасть точно, включая количество пробелов. Паттерн `%{a} %{b}` (один пробел) не матчит строку с двумя пробелами — для этого есть модификатор `->`.
- **All-or-nothing** — если хотя бы один ключ не найден, вся диссекция считается неудачной, событие не модифицируется (Logstash ставит тег `_dissectfailure`).
- **Последнее поле** забирает остаток строки целиком.
- **Пробелы внутри значения** — поле захватывается до следующего разделителя, поэтому значение с пробелами матчится только если разделитель после него многосимвольный (например, `] ` или ` HTTP/`). Timestamp `Aug 23 10:30:00` нельзя захватить одним полем с одиночным пробелом-разделителем — разбейте на три поля.
- **Типы** — все значения строки; конверсии — отдельно (`convert_datatype` в Logstash, `convert`-процессор в Elasticsearch, суффикс `|integer` в Filebeat).

### Grok vs Dissect

| Критерий | Grok | Dissect |
|----------|------|---------|
| Скорость | Медленнее (регулярные выражения, возможен backtracking) | Значительно быстрее (один проход по разделителям) |
| Гибкость | Высокая (любые регулярные выражения) | Ограничена фиксированными разделителями |
| Фиксированный формат | Избыточен | Отлично |
| Вариативный формат, optional поля | Отлично | Плохо |
| Частичный матч | Возможен (якоря вручную) | Нет — либо всё, либо ничего |
| Читаемость | Хуже | Лучше |
| Конверсия типов | Встроенная (`:int`, `:float`) | Отдельным шагом |

Точные множители производительности зависят от шаблона и данных — официальная документация не приводит конкретных коэффициентов. Правило выбора: **«Dissect first, Grok last»** — разбирайте стабильную часть строки dissect-ом, grok применяйте только к неструктурированному остатку (методика и тюнинг — в [Logstash Pipelines](./Logstash/logstash_pipelines.md)).

## Основные паттерны grok

Полный набор встроенных паттернов (~200 в ~20 файлах) — в репозитории [logstash-patterns-core](https://github.com/logstash-plugins/logstash-patterns-core/tree/main/patterns). В Logstash доступны два набора: `legacy` (по умолчанию) и `ecs-v1` (при `ecs_compatibility => "v1"`).

### Общие

| Паттерн | Описание | Пример |
|---------|----------|--------|
| `%{WORD}` | Слово (`\b\w+\b`: буквы, цифры, `_`) | `hello123` |
| `%{NOTSPACE}` | Непробельные символы (`\S+`) | `hello-world` |
| `%{SPACE}` | Пробельные (`\s*`, включая пустую строку) | ` `, `\t` |
| `%{DATA}` | Любые символы, ленивые (`.*?`) | любой текст |
| `%{GREEDYDATA}` | Любые символы, жадные (`.*`) | любой текст |
| `%{INT}` | Целое со знаком | `42`, `-7` |
| `%{POSINT}` | Положительное целое | `42` |
| `%{NONNEGINT}` | Неотрицательное целое | `0`, `42` |
| `%{NUMBER}` | Число (целое или десятичное) | `42`, `3.14`, `.5` |
| `%{BASE10NUM}` | Десятичное число (основа для `%{NUMBER}`) | `3.14` |
| `%{BASE16NUM}` | Hex, опциональный префикс `0x` | `0xFF` |
| `%{USERNAME}` / `%{USER}` | Имя пользователя | `john.doe` |
| `%{EMAILADDRESS}` | Email | `user@example.com` |
| `%{UUID}` | UUID | `5f1d...-...` |
| `%{QUOTEDSTRING}` / `%{QS}` | Строка в кавычках `"..."`, `'...'`, `` `...` `` | `"hello world"` |

### Дата и время

| Паттерн | Описание | Пример |
|---------|----------|--------|
| `%{TIMESTAMP_ISO8601}` | ISO 8601 (timezone опционален) | `2026-08-23T10:30:00.000Z` |
| `%{DATE_US}` | Дата US | `08/23/2026` |
| `%{DATE_EU}` | Дата EU | `23.08.2026` |
| `%{DATE}` | `%{DATE_US}` или `%{DATE_EU}` — только числовые форматы | `08/23/2026` |
| `%{DATESTAMP}` | `%{DATE}[- ]%{TIME}` — числовая дата + время | `08/23/2026 10:30:00` |
| `%{TIME}` | Время (секунды опциональны) | `10:30:00` |
| `%{SYSLOGTIMESTAMP}` | Syslog-время | `Aug 23 10:30:00` |
| `%{HTTPDATE}` | HTTP-формат (access-логи) | `23/Aug/2026:10:30:00 +0000` |
| `%{HTTPDERROR_DATE}` | Apache error-лог | `Sun Aug 23 10:30:00 2026` |
| `%{MONTH}` / `%{MONTHNUM}` / `%{MONTHDAY}` | Месяц (имя / номер / день) | `Aug` / `08` / `23` |
| `%{DAY}` | День недели | `Sun`, `Monday` |
| `%{YEAR}` | Год (2 или 4 цифры) | `2026` |
| `%{HOUR}` / `%{MINUTE}` / `%{SECOND}` | Компоненты времени | `10` / `30` / `00` |
| `%{TZ}` | Часовой пояс | `UTC`, `MSK` |

Для даты с именем месяца (`Aug 23, 2026`) используйте `%{MONTH} %{MONTHDAY},? %{YEAR}` — встроенный `%{DATE}` такой формат не матчит. Для даты с годом первым (`2026/08/23`, формат nginx error-лога) используйте `%{YEAR}[/-]%{MONTHNUM}[/-]%{MONTHDAY}[- ]%{TIME}` — `%{DATESTAMP}` такой формат тоже не матчит.

### Сетевые данные

| Паттерн | Описание | Пример |
|---------|----------|--------|
| `%{IP}` | IPv4 или IPv6 | `192.168.1.1` |
| `%{IPV4}` / `%{IPV6}` | Конкретная версия | `192.168.1.1` / `2001:db8::1` |
| `%{IPORHOST}` | IP или hostname | `web01` |
| `%{HOSTNAME}` | Имя хоста | `server1.company.com` |
| `%{HOSTPORT}` | Хост:порт | `example.com:8080` |
| `%{MAC}` | MAC-адрес (Cisco/Windows/Common) | `00:11:22:33:44:55` |
| `%{PATH}` | Абсолютный Unix-/Windows-путь | `/var/log/nginx` |

### HTTP и Web

| Паттерн | Описание | Пример |
|---------|----------|--------|
| `%{URIPROTO}` | Протокол | `http`, `https` |
| `%{URIHOST}` | Host (порт опционален) | `example.com:8080` |
| `%{URIPATH}` | Путь | `/path/to` |
| `%{URIPARAM}` | Query string с `?` | `?q=1&b=2` |
| `%{URIPATHPARAM}` | Путь с параметрами | `/path?q=1` |
| `%{URI}` | Полный URI | `http://example.com/path` |

Паттерна `%{URIQUERY}` в стандартной библиотеке Logstash нет — query string покрывает `%{URIPARAM}`.

### Логи и Java

| Паттерн | Описание | Пример |
|---------|----------|--------|
| `%{LOGLEVEL}` | Уровень лога, регистронезависимый (Alert, Trace, Debug, Notice, Info, Warn, Error, Crit, Fatal, Severe, Emerg) | `ERROR`, `warn` |
| `%{SYSLOGFACILITY}` | Syslog priority `<facility.priority>` | `<34>` |
| `%{SYSLOGHOST}` | Syslog host (IP или hostname) | `server1` |
| `%{SYSLOGPROG}` | Program `[pid]` — захватывает поля `program` и `pid` | `sshd[1234]` |
| `%{PROG}` | Имя программы | `sshd` |
| `%{JAVACLASS}` | Java-класс | `com.example.Service` |
| `%{JAVAFILE}` | Java-файл (может содержать пробелы) | `Native Method` |
| `%{JAVAMETHOD}` | Java-метод (включая `<init>`) | `doGet` |
| `%{JAVASTACKTRACEPART}` | Строка Java stack trace | ` at com.example.Foo.bar(Foo.java:42)` |

`%{LOGLEVEL}` не включает уровень `LOG` PostgreSQL — для PostgreSQL-логов используйте `%{WORD:level}`.

### Составные (composite) паттерны

| Паттерн | Описание |
|---------|----------|
| `%{HTTPD_COMMONLOG}` | Apache/Nginx access log (common format) |
| `%{HTTPD_COMBINEDLOG}` | Apache/Nginx access log (combined: + referrer, user agent) |
| `%{COMMONAPACHELOG}` / `%{COMBINEDAPACHELOG}` | Deprecated алиасы `HTTPD_COMMONLOG` / `HTTPD_COMBINEDLOG` |
| `%{HTTPD20_ERRORLOG}` / `%{HTTPD24_ERRORLOG}` | Apache 2.0 / 2.4 error log |
| `%{HTTPD_ERRORLOG}` | Apache error log (2.0 или 2.4) |
| `%{SYSLOGBASE}` | RFC 3164: timestamp, host, program |
| `%{SYSLOGLINE}` | RFC 3164: полная строка с сообщением |
| `%{SYSLOG5424BASE}` / `%{SYSLOG5424LINE}` | RFC 5424: заголовок / полная строка (поддерживает `-`-placeholder и несколько SD-элементов) |
| `%{CATALINALOG}` | Tomcat catalina-лог |
| `%{TOMCATLOG}` | Tomcat-лог с уровнем и классом |

## Синтаксис dissect

### Модификаторы полей

Модификаторы всегда внутри `%{...}`:

| Модификатор | Название | Пример | Действие |
|-------------|----------|--------|----------|
| — | Normal field | `%{field}` | Значение сохраняется в поле |
| `?` | Named skip | `%{?ignored}` или `%{}` | Значение пропускается, не сохраняется |
| `+` | Append | `%{+field}` | Добавляется к предыдущему полю (через разделитель перед полем) |
| `+` с `/n` | Append с порядком | `%{+field/2} %{+field/1}` | Добавление в заданном порядке |
| `&` | Indirect (reference) | `%{&key}` | Значение сохраняется в поле, имя которого взято из значения `key` |
| `->` | Right padding | `%{field->}` | Игнорирует повторяющиеся символы справа от поля (выравнивание пробелами) |

Вложенные поля: `%{[parent][child]}`. Точка в ключе создаёт поле с точкой в имени — для вложенности используйте скобки. Append и indirect нельзя комбинировать (`%{+&x}` недопустимо).

Примеры (из официальной документации):

```
# Skip: приоритет не сохраняем, timestamp разбиваем по пробелам
<%{?priority}>%{month} %{day} %{time} %{hostname} %{program}: %{message}

# Append: "1 2 3 go" → a = "1 3 go", b = "2"
%{a} %{b} %{+a}

# Indirect: "error: some_error, some_description" → поле some_error = "some_description"
error: %{?err}, %{&err}

# Padding: "00000043 ViewReceive     machine-321" → function = "ViewReceive"
%{id} %{function->} %{server}
```

### Строгость разделителей

- Количество пробелов в разделителе должно совпадать точно; `->` справа от поля снимает это ограничение для выравнивания.
- Начиная с плагина dissect 1.1.1, несколько подряд идущих разделителей трактуются как пропущенные поля, а не как padding.
- В Logstash не используйте экранированный `\n` в значении `mapping` — он интерпретируется как два символа `\` + `n`; используйте реальный перенос строки в конфиге.

## Практические сценарии

### Nginx Access Log

**Формат:** `combined`

```
192.168.1.1 - - [23/Aug/2026:10:30:00 +0000] "GET /api/users HTTP/1.1" 200 1234 "https://example.com" "Mozilla/5.0" "10.0.0.1"
```

**Grok:**

```grok
%{IP:client_ip} %{USER:ident} %{USER:auth} \[%{HTTPDATE:timestamp}\] "%{WORD:method} %{URIPATHPARAM:request} HTTP/%{NUMBER:http_version}" %{INT:status} (?:%{INT:bytes}|-) %{QS:referrer} %{QS:user_agent} %{QS:forwarded_for}
```

`(?:%{INT:bytes}|-)` — nginx пишет `-` вместо размера, когда тело отсутствует; голый `%{INT:bytes}` на таком месте ломает весь шаблон. Однострочный эквивалент: `%{HTTPD_COMBINEDLOG}` (поля `clientip`, `ident`, `auth`, `timestamp`, `verb`, `request`, `httpversion`, `response`, `bytes`, `referrer`, `agent`).

**Dissect (быстрее; кавычки остаются в значениях):**

```
%{client_ip} %{ident} %{auth} [%{timestamp}] "%{method} %{request} HTTP/%{http_version}" %{status} %{bytes} %{referrer} %{user_agent} %{forwarded_for}
```

### Nginx Error Log

**Формат:**

```
2026/08/23 10:30:00 [error] 1234#0: *5678 connect() failed (111: Connection refused)
```

**Grok:**

```grok
%{YEAR}[/-]%{MONTHNUM}[/-]%{MONTHDAY}[- ]%{TIME:timestamp} \[%{LOGLEVEL:level}\] %{INT:pid}#%{INT:tid}: (?:\*%{INT:connection} )?%{GREEDYDATA:message}
```

Дата с годом первым (`2026/08/23`) не матчится `%{DATESTAMP}` — нужен явный шаблон выше. Блок `*5678` (connection ID) опционален: в строках вида `[notice] 1234#0: signal process started` его нет.

### Apache Access Log

**Формат:** `combined`

```
127.0.0.1 - frank [10/Oct/2000:13:55:36 -0700] "GET /apache_pb.gif HTTP/1.0" 200 2326 "http://www.example.com/start.html" "Mozilla/4.08"
```

**Grok:**

```grok
%{IP:client_ip} %{USER:ident} %{USER:auth} \[%{HTTPDATE:timestamp}\] "%{WORD:method} %{URIPATHPARAM:request} HTTP/%{NUMBER:http_version}" %{INT:status} (?:%{INT:bytes}|-) %{QS:referrer} %{QS:user_agent}
```

Однострочный эквивалент: `%{HTTPD_COMBINEDLOG}`.

### Apache Error Log

**Формат:**

```
[Sun Aug 23 10:30:00.000000 2026] [mpm_event:info] [pid 1234:tid 5678] AH00491: caught SIGTERM, shutting down
```

**Grok (встроенный составной паттерн):**

```grok
%{HTTPD24_ERRORLOG}
```

**Grok (ручной вариант для понимания):**

```grok
\[%{HTTPDERROR_DATE:timestamp}\] \[(?:%{WORD:module})?:%{LOGLEVEL:level}\] \[pid %{POSINT:pid}(:tid %{NUMBER:tid})?\] %{GREEDYDATA:message}
```

`%{HTTPDATE}` здесь не подходит — он матчит только формат `23/Aug/2026:10:30:00 +0000` из access-логов; для error-лога существует `%{HTTPDERROR_DATE}`.

### Syslog RFC 3164

**Формат:**

```
<34>Aug 23 10:30:00 server1 sshd[1234]: Failed password for root from 192.168.1.1 port 22 ssh2
```

**Grok:**

```grok
<%{POSINT:priority}>%{SYSLOGTIMESTAMP:timestamp} %{SYSLOGHOST:hostname} %{SYSLOGPROG:program}: %{GREEDYDATA:message}
```

`%{SYSLOGPROG}` дополнительно захватывает `pid` (здесь — `1234`). Составные аналоги: `%{SYSLOGBASE}` (без сообщения) и `%{SYSLOGLINE}` (полная строка).

**Dissect (timestamp разбивается на три поля — он содержит пробелы):**

```
<%{priority}>%{month} %{day} %{time} %{hostname} %{program}: %{message}
```

Поле `program` захватывает `sshd[1234]` целиком — для отделения pid нужен второй проход (dissect или grok).

### Syslog RFC 5424

**Формат:**

```
<165>1 2026-08-23T10:30:00.000Z server1 app 1234 ID47 [exampleSDID@32473 iut="3"] Application event
```

**Grok (встроенный составной паттерн):**

```grok
%{SYSLOG5424LINE}
```

Захватывает `syslog5424_pri`, `syslog5424_ver`, `syslog5424_ts`, `syslog5424_host`, `syslog5424_app`, `syslog5424_proc`, `syslog5424_msgid`, `syslog5424_sd`, `syslog5424_msg`. Корректно обрабатывает `-`-placeholder вместо пустых полей и несколько SD-элементов подряд (`[a][b]`).

**Grok (ручной вариант — только для одного SD-элемента):**

```grok
<%{POSINT:priority}>%{INT:version} %{TIMESTAMP_ISO8601:timestamp} %{HOSTNAME:hostname} %{NOTSPACE:appname} %{NOTSPACE:procid} %{NOTSPACE:msgid} \[%{DATA:structured_data}\] %{GREEDYDATA:message}
```

Ограничение ручного варианта: ленивый `%{DATA}` останавливается на первом `]`, поэтому строки с несколькими SD-элементами не матчатся — используйте `%{SYSLOG5424LINE}`.

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

JSON-логи парсите json-фильтром (или `decode_json_fields` в Filebeat), а не grok — это быстрее и надёжнее. `target` опционален: без него поля попадают в корень события.

### Application Log (Plain Text, Java)

**Формат:**

```
2026-08-23 10:30:00.123 [main] ERROR com.example.Service - Connection failed
```

**Grok:**

```grok
%{TIMESTAMP_ISO8601:timestamp} \[%{DATA:thread}\] %{LOGLEVEL:level} %{JAVACLASS:class} - %{GREEDYDATA:message}
```

### Docker Log

**Формат:** (json-file driver, «сырой» вывод)

```
2026-08-23T10:30:00.123456789Z stdout F 2026-08-23 10:30:00 INFO Application started
```

**Grok:**

```grok
%{TIMESTAMP_ISO8601:docker_timestamp} %{WORD:stream} %{WORD:flag} %{TIMESTAMP_ISO8601:timestamp} %{LOGLEVEL:level} %{GREEDYDATA:message}
```

### Kubernetes Log

**Формат:** (CNI-контейнерный вывод, klog)

```
2026-08-23T10:30:00.123456789Z stderr F I0823 10:30:00.123456       1 main.go:42] Starting server
```

**Grok (общий):**

```grok
%{TIMESTAMP_ISO8601:kube_timestamp} %{WORD:stream} %{WORD:flag} %{DATA:log_message}
```

**Grok (специфичный для klog):**

```grok
%{TIMESTAMP_ISO8601:kube_timestamp} %{WORD:stream} %{WORD:flag} %{WORD:severity}%{MONTHNUM2}%{MONTHDAY} %{TIME} %{INT:thread}\s+%{NOTSPACE:source}] %{GREEDYDATA:message}
```

### MySQL Slow Query Log

**Формат:** (многострочное событие — требуется multiline codec/parser)

```
# Time: 2026-08-23T10:30:00.123456Z
# User@Host: root[root] @ localhost [127.0.0.1]  Id:     1
# Query_time: 2.345678  Lock_time: 0.000123 Rows_sent: 1000  Rows_examined: 100000
SELECT * FROM users WHERE last_login > '2026-01-01';
```

**Grok:**

```grok
# Time: %{TIMESTAMP_ISO8601:timestamp}\n# User@Host: %{USER:user}\[%{USER:user}\] @ %{HOSTNAME:host} \[%{IP:ip}\]\s+Id:\s+%{INT:connection_id}\n# Query_time:\s+%{NUMBER:query_time}\s+Lock_time:\s+%{NUMBER:lock_time}\s+Rows_sent:\s+%{INT:rows_sent}\s+Rows_examined:\s+%{INT:rows_examined}\n%{GREEDYDATA:query}
```

Экранированный `\n` в конфиге Logstash интерпретируется как реальный перевод строки — шаблон работает только если всё событие уже склеено в одно значение `message` (multiline codec). Количество пробелов в исходнике варьируется, поэтому перед `%{INT}`/`%{NUMBER}` стоит `\s+`, а не фиксированные пробелы.

### PostgreSQL Log

**Формат:**

```
2026-08-23 10:30:00.123 UTC [1234] LOG:  duration: 2345.678 ms  statement: SELECT * FROM users;
```

**Grok:**

```grok
%{TIMESTAMP_ISO8601:timestamp} %{WORD:timezone} \[%{INT:pid}\] %{WORD:level}:  duration: %{NUMBER:duration_ms} ms  statement: %{GREEDYDATA:query}
```

Уровень `LOG` PostgreSQL не входит в `%{LOGLEVEL}` — поэтому `%{WORD:level}`. Уровни PostgreSQL: `DEBUG`, `INFO`, `NOTICE`, `WARNING`, `ERROR`, `LOG`, `FATAL`, `PANIC` (`NOTICE` в `%{LOGLEVEL}` входит, `LOG` — нет).

### Windows Event Log

**Формат:** (текстовый вид события, например из Winlogbeat; многострочное событие)

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

`%{LOGLEVEL}` регистронезависим и матчит `Error`. Для структурированного Windows Event Log предпочтительнее нативные поля Winlogbeat, а не разбор текста.

## Применение

### Logstash

```ruby
filter {
  # 1. Быстрый разбор стабильной части
  dissect {
    mapping => { "message" => "%{client_ip} %{ident} %{auth} [%{timestamp}] \"%{method} %{request} HTTP/%{http_version}\" %{status} %{bytes} %{referrer} %{user_agent}" }
    convert_datatype => { "status" => "int" "bytes" => "int" }
    tag_on_failure => ["_dissectfailure"]   # дефолтное значение
  }

  # 2. Grok только для остатка
  if [message] =~ /failed/ {
    grok {
      match => { "message" => "^%{TIMESTAMP_ISO8601:ts} %{LOGLEVEL:level} %{GREEDYDATA:msg}$" }
      tag_on_failure => ["_grokparsefailure"]  # дефолтное значение
    }
  }
}
```

Параметры grok-фильтра: `match` (hash field → pattern или массив паттернов), `patterns_dir` (массив каталогов с custom-паттернами), `ecs_compatibility` (`disabled` / `v1` / `v8`; дефолт зависит от версии Logstash), `timeout_millis` (лимит исполнения одного шаблона), `timeout_scope` (`event` / `pipeline`).

### Elasticsearch ingest pipeline

```json
PUT _ingest/pipeline/nginx-access
{
  "processors": [
    {
      "dissect": {
        "field": "message",
        "pattern": "%{client_ip} %{ident} %{auth} [%{timestamp}] \"%{method} %{request} HTTP/%{http_version}\" %{status} %{bytes} %{referrer} %{user_agent}"
      }
    },
    {
      "convert": {
        "field": "status",
        "type": "integer"
      }
    }
  ]
}
```

Grok-процессор: `field` и `patterns` (массив, пробуются по порядку, первый успех возвращается) обязательны; `pattern_definitions` переопределяет встроенные паттерны; `ecs_compatibility` (`disabled` / `v1`, дефолт `disabled`); `trace_match: true` добавляет `_ingest._grok_match_index` (индекс сработавшего паттерна); `validate_only: true` (GA с 9.4) проверяет совпадение без извлечения полей — удобно для тестов. Параметры обоих процессоров, отладочный лог и watchdog описаны в [Ingest Pipelines](./Elasticsearch/elasticsearch_ingest_pipelines.md).

### Filebeat

У Filebeat **нет grok-процессора** — grok-парсинг возможен только в Logstash или в ingest-пайплайне Elasticsearch. Dissect-процессор есть:

```yaml
processors:
- dissect:
    tokenizer: "%{client_ip} %{ident} %{auth} [%{timestamp}] \"%{method} %{request} HTTP/%{http_version}\" %{status} %{bytes} %{referrer} %{user_agent}"
    field: "message"
    target_prefix: ""        # "" — поля в корень; дефолт "dissect"
    trim: all                # none | left | right | all
    overwrite_keys: false    # true — перезаписывать существующие поля
    ignore_failure: false    # true — тихо восстанавливать событие при неудаче
```

Конверсия типов — суффикс после ключа: `%{bytes|integer}`, `%{ratio|float}`, `%{ip|ip}` (также `long`, `double`, `boolean`). Ключ не может содержать зарезервированные символы модификаторов: `/`, `,`, `&`, `+`, `#`, `?`. Если `target_prefix` уже существует в событии, процессор падает — либо предварительно удалите/переименуйте ключ, либо включите `overwrite_keys`.

### Custom patterns

**Logstash** — файл с определениями в каталоге, подключаемом через `patterns_dir`:

```bash
# /etc/logstash/patterns/nginx
NGINX_ERROR \[%{HTTPDERROR_DATE:timestamp}\] \[%{LOGLEVEL:level}\] %{INT:pid}#%{INT:tid}: %{GREEDYDATA:message}
```

```ruby
grok {
  patterns_dir => ["/etc/logstash/patterns"]
  match => { "message" => "%{NGINX_ERROR:nginx_error}" }
}
```

**Elasticsearch** — встроенные паттерны нельзя расширить файлами; переопределения задаются в процессоре:

```json
{
  "grok": {
    "field": "message",
    "patterns": ["%{MY_DATE:timestamp} %{LOGLEVEL:level} %{GREEDYDATA:message}"],
    "pattern_definitions": {
      "MY_DATE": "%{YEAR}-%{MONTHNUM}-%{MONTHDAY}[T ]%{HOUR}:?%{MINUTE}(?::?%{SECOND})?"
    }
  }
}
```

Список встроенных паттернов: `GET _ingest/processor/grok` (параметр `s` сортирует по имени).

## Валидация и отладка

1. **Grok Debugger в Kibana** — Dev Tools → Grok Debugger: вставьте sample data и паттерн, проверьте захваты.
2. **`_simulate` API** — тест процессора без индексации; с `verbose: true` видны промежуточные результаты каждого процессора (детали — в [Ingest Pipelines](./Elasticsearch/elasticsearch_ingest_pipelines.md)):

```json
POST _ingest/pipeline/_simulate
{
  "pipeline": { "processors": [ { "grok": { "field": "message", "patterns": ["%{HTTPD_COMBINEDLOG}"] } } ] },
  "docs": [ { "_index": "test", "_source": { "message": "127.0.0.1 - frank [10/Oct/2000:13:55:36 -0700] \"GET /apache_pb.gif HTTP/1.0\" 200 2326 \"http://www.example.com/start.html\" \"Mozilla/4.08\"" } } ]
}
```

3. **Logstash без инфраструктуры** — прогон одной строки через цепочку фильтров (полный пример — в [Logstash Pipelines](./Logstash/logstash_pipelines.md)):

```bash
echo '<тестовая строка>' | bin/logstash -e 'input { stdin{} } filter { ... } output { stdout { codec => rubydebug } }'
```

4. **`bin/logstash -t`** — проверяет только синтаксис конфигурации, но **не** корректность grok/dissect-шаблонов.

## Troubleshooting

| Симптом | Причина | Решение |
|---------|---------|---------|
| Тег `_grokparsefailure` | Шаблон не совпал со строкой | Sample data в Grok Debugger; проверьте optional-части `(?:...)?`, placeholders `-`, якоря `^...$` |
| Тег `_dissectfailure` | Разделитель не найден | Dissect строгий: проверьте точное число пробелов; для выравнивания — `->`; для пропускаемых значений — `%{?skip}` |
| Поля есть, но часть строки не разобрана | Жадный паттерн в середине (`%{GREEDYDATA}`) или нет якорей | Перенесите `%{GREEDYDATA}` в конец; якорите шаблон |
| Grok тормозит / watchdog | Катастрофический backtracking | Упростите вложенные кванторы; якоря; тестируйте на длинных строках (watchdog в ES — см. [Ingest Pipelines](./Elasticsearch/elasticsearch_ingest_pipelines.md)) |
| Все значения строковые | Ожидаемое поведение | Конверсия: `%{NUMBER:x:int}` (grok), `convert_datatype` (dissect, Logstash), `convert`-процессор (ES), `\|integer` (Filebeat) |
| Шаблон с `\n` не работает в dissect | Экранирование | В `mapping` Logstash используйте реальный перенос строки, не `\n` |
| Многострочные паттерны не матчатся | Событие не склеено | Multiline codec (Logstash) / multiline parser (Filebeat) — конфигурации: [Logstash multiline](./Logstash/logstash_inputs_outputs.md#многострочные-сообщения-multiline-codec) |
| `target_prefix` в Filebeat уже существует | Конфликт полей | `overwrite_keys: true` или предварительный `drop_fields`/`rename` |

## Best Practices

1. **Dissect first, Grok last** — dissect для стабильной части строки, grok только для остатка (производительность и методика — в [Logstash Pipelines](./Logstash/logstash_pipelines.md)).
2. **Предпочитайте составные паттерны** (`%{HTTPD_COMBINEDLOG}`, `%{SYSLOGLINE}`, `%{SYSLOG5424LINE}`) ручным — они покрывают edge-cases (placeholder `-`, опциональные блоки).
3. **Тестируйте на репрезентативных sample data** — включая строки с `-` вместо чисел, пустыми полями и аномально длинными значениями.
4. **Custom patterns** для повторяющихся выражений; в ES — `pattern_definitions`, в Logstash — `patterns_dir`.
5. **Fallback-паттерны** для неожиданных форматов — массив `patterns` в grok-процессоре пробует паттерны по порядку.
6. **Tag unmatched documents** для отладки (`_grokparsefailure` / `_dissectfailure` — дефолтные теги) и маршрутизируйте неудачные события в отдельный индекс/DLQ.
7. **Conditional parsing** — разные паттерны для разных типов логов:

```ruby
if [type] == "nginx" {
  grok { ... }
} else if [type] == "syslog" {
  grok { ... }
}
```

8. **Конвертируйте типы на этапе парсинга** — числовые поля как строки ломают агрегации и сортировку.

## См. также

* **[Ingest Pipelines](./Elasticsearch/elasticsearch_ingest_pipelines.md)** — grok и dissect процессоры в Elasticsearch, `_simulate`, watchdog.
* **[Logstash: Обзор](./Logstash/logstash_overview.md)** — grok, dissect фильтры в Logstash.
* **[Logstash: Конвейеры и фильтры](./Logstash/logstash_pipelines.md)** — оптимизация парсинга, Flow Metrics, отладка.
* **[Elasticsearch: Обзор](./Elasticsearch/elasticsearch_overview.md)** — архитектура и маппинг.
* **[Filebeat: Обзор](./filebeat_overview.md)** — parsers и processors в Filebeat.
* **[Kibana: Поиск и визуализация](./Kibana/kibana_search_and_visualization.md)** — Grok Debugger.
* Внешние источники: [grok filter plugin](https://github.com/logstash-plugins/logstash-filter-grok/blob/main/docs/index.asciidoc), [dissect filter plugin](https://www.elastic.co/docs/reference/logstash/plugins/plugins-filters-dissect), [grok processor](https://www.elastic.co/docs/reference/ingest-processor/grok-processor), [dissect processor](https://www.elastic.co/docs/reference/ingest-processor/dissect-processor), [Filebeat dissect processor](https://www.elastic.co/docs/reference/beats/filebeat/dissect), [logstash-patterns-core](https://github.com/logstash-plugins/logstash-patterns-core) (источники всех встроенных паттернов).
