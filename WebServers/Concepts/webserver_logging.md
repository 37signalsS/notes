# Логирование веб-серверов

**Актуально для:** Nginx 1.26+, Angie 1.8+, Apache HTTP Server 2.4.x, HAProxy 3.0+, Traefik 3.x, Vector 0.40+, logrotate 3.20+

## Определения

**Access log (журнал доступа)** — системный журнал веб-сервера или обратного прокси (Reverse Proxy), фиксирующий метаданные каждого завершенного клиентского HTTP/HTTPS-запроса: IP-адрес клиента, временную метку, HTTP-метод, URI, код ответа, размер переданных данных, `User-Agent`, `Referer`, задержки обработки (`request_time`, `upstream_response_time`).

**Error log (журнал ошибок)** — журнал системных событий, сетевых сбоев, предупреждений модулей, аварийных завершений worker-процессов, проблем TLS-рукопожатий и диагностических сообщений разного уровня критичности.

**Audit log (журнал аудита)** — специализированный журнал безопасности, фиксирующий факты аутентификации, изменения привилегий, заблокированные WAF-запросы и действия администраторов.

**Stream log (L4-логирование)** — журнал учета TCP/UDP-сессий на уровне транспортного уровня, регистрирующий IP-адреса и порты источника/назначения, длительность сессии, число переданных/принятых байтов и статус L4-соединения.

**Structured logging (структурированное логирование)** — метод записи событий в стандартизированном машиночитаемом формате (преимущественно JSON или NDJSON), где каждое поле обладает фиксированным именем и типизированным значением, что исключает необходимость нестабильного парсинга регулярными выражениями.

**Log rotation (ротация логов)** — автоматизированный процесс архивирования, сжатия, переименования и удаления устаревших файлов журналов по расписанию или по достижению лимита размера, предотвращающий переполнение диска.

**Unlinked open file descriptor (открытый дескриптор удалённого файла)** — состояние в ОС Linux, при котором файл журнала удалён из файловой системы (`rm`), но удерживается открытым файловым дескриптором работающего процесса веб-сервера. Дисковые блоки не освобождаются ядром до тех пор, пока процесс не закроет дескриптор или не перезапустится.

**Buffer (буфер записи)** — кольцевой буфер в оперативной памяти рабочего процесса для накопления строк журнала перед вызовом системного вызова `write(2)`, минимизирующий нагрузку на дисковую подсистему и исключающий блокировку Event Loop.

**Centralized logging (централизованный сбор логов)** — архитектура доставки логов с множества серверов через локальные агенты (Vector, Fluent Bit, Promtail) в единое on-premise хранилище (ClickHouse, Grafana Loki, OpenSearch) для долговременного хранения, агрегации и аналитики.

**Correlation ID / W3C Trace Context** — сквозные идентификаторы транзакции (`X-Request-ID`, заголовок `traceparent`), передаваемые через всю цепочку прокси и микросервисов для объединения распределённых записей логов в единый трейс.

**Log level (уровень важности)** — градация критичности событий по стандарту RFC 5424 / syslog: `debug`, `info`, `notice`, `warn`, `error`, `crit`, `alert`, `emerg`.

**Data Masking / Sanitization (маскирование данных)** — процедура очистки или хэширования конфиденциальных данных (паролей, токенов Authorization, Cookie, персональных данных) перед их сохранением в журнал.

---

## Основные концепции и архитектура

### Архитектура подсистемы логирования в веб-серверах

В асинхронных событийно-ориентированных серверах (Nginx, Angie, HAProxy) логирование вынесено на финальную фазу конвейера обработки запроса:

```text
[ Клиент ] ─── HTTP-запрос ───► [ Обработка: TLS -> Routing -> Proxy/FastCGI ]
                                                  │
                                          [ Отдача ответа ]
                                                  │
                                          [ Фаза LOG (NGX_HTTP_LOG_PHASE / Log State) ]
                                                  │
                                ┌─────────────────┴─────────────────┐
                                ▼                                   ▼
                       [ Проверка условий if= ]             [ Формирование записи ]
                                │                                   │ (escape=json / format)
                       (0: отмена записи)                           ▼
                                                        [ Буфер в памяти worker ]
                                                                    │
                                            ┌───────────────────────┴───────────────────────┐
                                            ▼                                               ▼
                                 [ Буфер полон / flush ]                           [ Прямой сброс ]
                                            │ (write(2))                                    │ (sendto(2))
                                   [ Файл /var/log/... ]                           [ UNIX / UDP Syslog ]
```

1. **Момент записи**: Запись в `access_log` создается строго **после** завершения передачи тела ответа клиенту или при обрыве соединения клиентом (код `499`). Это гарантирует точность таймингов (`$request_time`, `$bytes_sent`).
2. **Error log вне фаз**: В отличие от access-лога, сообщения в `error_log` пишутся синхронно в момент возникновения события на любой стадии обработки (при парсинге заголовков, ошибке резолвинга DNS, падении upstream).
3. **Изоляция буферов worker-процессов**: Каждый рабочий процесс владеет собственным буфером в оперативной памяти. Сброс на диск происходит либо при заполнении объема (`buffer=32k`), либо по истечении тайм-аута (`flush=5s`).

### Сравнение форматов журналов

| Формат | Структура / Пример | Преимущества | Недостатки / Ограничения |
| :--- | :--- | :--- | :--- |
| **Common (CLF)** | `%h %l %u %t "%r" %>s %b`<br>`192.168.1.10 - - [15/Oct/2026:10:00:01 +0300] "GET /index.html HTTP/1.1" 200 4520` | Исторический стандарт, минимальный размер строки. | Отсутствуют `Referer`, `User-Agent`, тайминги и идентификаторы запросов. |
| **Combined** | Common + `"%{Referer}i" "%{User-agent}i"` | Стандарт по умолчанию в Nginx и Apache; читаем человеком. | Требует сложных регулярных выражений для парсинга; не типизирован. |
| **JSON (NDJSON)** | `{"time":"...","remote_ip":"...","status":200,"request_time":0.005,"trace_id":"..."}` | Прямой инжест в Vector, ClickHouse, Loki, OpenSearch; строгая схема полей. | Увеличенный размер файла (на 20–40% из-за ключей); требует экранирования спецсимволов. |
| **LTSV (Labeled Tab-Separated)** | `time:...\thost:...\treq:GET / HTTP/1.1\tstatus:200\truntime:0.005` | Простой парсинг через `cut`/`awk`, меньший оверхед по сравнению с JSON. | Меньшая экосистемная поддержка в готовых агентах сбора по сравнению с JSON. |

### Механизмы ввода-вывода (I/O) и влияние на производительность

Синхронная запись логов на диск создает узкое место в высоконагруженных системах:

1. **Блокирующий `write(2)`**: Если диск перегружен операциями ввода-вывода (I/O wait) или используется медленный сетевой диск (NFS), системный вызов `write(2)` без буферизации блокирует worker-процесс. Обработка всех остальных сетевых соединений в этом воркере останавливается.
2. **Буферизация в памяти (`buffer=size`, `flush=time`)**: В Nginx/Angie буфер накапливает логи в памяти воркера. Запись на диск выполняется крупными блоками, что снижает число системных вызовов в десятки раз.
3. **Асинхронная отправка по syslog**: Запись через сокет `/dev/log` (UNIX domain datagram socket) или localhost UDP исключает дисковый I/O из веб-сервера. Задержки ввода-вывода переносятся на специализированный системный демон (`rsyslog` или `syslog-ng`).

### Механика ротации логов и управление файловыми дескрипторами

Файловые системы Linux связывают открытый файл с номером `inode`, а не с путем к файлу:

```text
[ Исходное состояние ]
  Nginx worker (fd 5) ────────► inode 12345 ◄──────── Имя: /var/log/nginx/access.log

[ logrotate выполняет rename: access.log -> access.log.1 ]
  Nginx worker (fd 5) ────────► inode 12345 ◄──────── Имя: /var/log/nginx/access.log.1

[ logrotate создает новый пустой файл ]
  Новый файл на диске          inode 67890 ◄──────── Имя: /var/log/nginx/access.log
  * Nginx все еще пишет в inode 12345 (access.log.1)! *

[ postrotate отправляет kill -USR1 `cat /run/nginx.pid` ]
  Nginx закрывает fd 5, переоткрывает путь /var/log/nginx/access.log:
  Nginx worker (fd 5) ────────► inode 67890 ◄──────── Имя: /var/log/nginx/access.log
```

#### Сравнение стратегий ротации

| Стратегия | Механизм | Риски и особенности | Применение в SRE/DevOps |
| :--- | :--- | :--- | :--- |
| **create + postrotate (сигнал USR1)** | Атомарный `rename` файла, создание нового файла с нужными `chmod/chown`, отправка сигнала `USR1` мастер-процессу. | Минимальные. Воркеры атомарно переоткрывают дескрипторы по имени без перезапуска. | **Рекомендуемый стандарт** для Nginx, Angie, HAProxy. Нулевая потеря логов. |
| **copytruncate** | Содержимое активного файла копируется в архивный, затем активный файл усекается до 0 байт (`truncate`). | **Потеря данных:** запросы, записанные сервером в промежутке между копированием и truncate, безвозвратно теряются. Возможна блокировка I/O на больших файлах. | Допустимо **только** для сервисов, не поддерживающих переоткрытие логов по сигналам. |
| **Piped Logging (`rotatelogs`)** | Сервер пишет логи в stdin дочернего процесса (`rotatelogs` в Apache), который сам управляет файлами по таймеру или размеру. | Накладные расходы на межпроцессное взаимодействие (IPC pipe). Если процесс-ротатор падает, буфер пайпа переполняется и веб-сервер блокируется. | Стандарт для Apache HTTP Server при запрете перезагрузок. |
| **Встроенная ротация** | Сервер самостоятельно ротирует файлы по шаблону времени (доступно в Angie через `use_dates`, Nginx Plus). | Не требует внешнего `logrotate` и cron/systemd таймеров. | Локальные окружения, автономные инсталляции Angie. |

#### Проблема зависших дескрипторов `(deleted)`

Если администратор выполняет `rm /var/log/nginx/access.log`, запись из директории удаляется, но ссылка на `inode` в таблице открытых файлов процесса сохраняется:
- Утилита `du` сканирует дерево ФС и **не видит** удаленный файл.
- Утилита `df` опрашивает суперблок файловой системы и показывает, что **диск заполнен на 100%**.
- Освобождение дискового пространства происходит только после отправки сигнала `USR1` или перезапуска сервиса.

### Корреляция и распределенная трассировка

В современной сервисной архитектуре единичный запрос пользователя проходит через пограничный прокси (Edge Reverse Proxy), балансировщики и внутренние сервисы. Для сквозного аудита используются два стандарта:

1. **`X-Request-ID`**: Произвольный уникальный строковый UUID (например, `c83f12a4-4e2a-4c28-97a9-d65e714659b8`), генерируемый Edge-сервером или клиентом.
2. **W3C Trace Context (`traceparent`)**: Стандартизированный заголовок RFC W3C, состоящий из 4 полей через дефис:
   `version-trace_id-parent_id-trace_flags` (например: `00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01`).
   Позволяет сопоставлять логи веб-сервера со спанами систем APM и распределенной трассировки (Jaeger, Tempo).

### Маскирование конфиденциальных данных (Data Masking)

Согласно требованиям информационной безопасности и комплаенса (PCI DSS, GDPR), логи веб-серверов не должны содержать:
- Значения заголовков `Authorization` (Bearer токены, Basic Auth);
- Пароли и токены сессий в query-параметрах URL (`?token=secret&password=123`);
- Значения чувствительных Cookie (`session_id`, `jwt`);
- Номера банковских карт и персональные данные (ПДн).

Маскирование реализуется через директивы подстановки (`map` в Nginx/Angie, `Regex` в фильтрах коллекторов).

---

## Практические сценарии

### Предварительные требования

Для развертывания сценариев необходима операционная система семейства Linux (Debian 12+, Ubuntu 22.04/24.04+, RHEL 9+) с правами `sudo`, а также предустановленные пакеты:

```bash
# Проверка наличия веб-серверов и системных утилит
nginx -v 2>&1
# → nginx version: nginx/1.26.2

apache2 -v 2>&1 || httpd -v 2>&1
# → Server version: Apache/2.4.62 (Debian)

haproxy -v | head -n 1
# → HAProxy version 3.0.3-1 2026/07/15

logrotate --version | head -n 1
# → logrotate 3.21.0
```

---

### Сценарий 1: Высокопроизводительный структурированный JSON-лог в Nginx с буферизацией и Correlation ID

Настройка production-конфигурации Nginx с экранированием JSON (`escape=json`), сквозным идентификатором запроса `$request_id`, маскированием токенов и буферизацией сброса на диск.

```nginx
# /etc/nginx/nginx.conf
user www-data;
worker_processes auto;
pid /run/nginx.pid;

events {
    worker_connections 2048;
    use epoll;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # Маскирование: отсекаем чувствительные query string из переменной $request_uri
    map $request_uri $sanitized_request_uri {
        ~*(.*)(\?|&)(token|password|secret|api_key)=[^&]*(.*) $1$2$3=***REDACTED***$4;
        default $request_uri;
    }

    # Маскирование: проверяем заголовок Authorization
    map $http_authorization $sanitized_auth {
        "" "-";
        default "Bearer ***REDACTED***";
    }

    # Структурированный JSON-формат
    log_format json_analytics escape=json '{'
        '"timestamp":"$time_iso8601",'
        '"server_name":"$server_name",'
        '"remote_addr":"$remote_addr",'
        '"request_id":"$request_id",'
        '"traceparent":"$http_traceparent",'
        '"method":"$request_method",'
        '"uri":"$sanitized_request_uri",'
        '"status":$status,'
        '"bytes_sent":$bytes_sent,'
        '"body_bytes_sent":$body_bytes_sent,'
        '"request_time":$request_time,'
        '"upstream_connect_time":"$upstream_connect_time",'
        '"upstream_header_time":"$upstream_header_time",'
        '"upstream_response_time":"$upstream_response_time",'
        '"upstream_addr":"$upstream_addr",'
        '"upstream_status":"$upstream_status",'
        '"http_referrer":"$http_referer",'
        '"http_user_agent":"$http_user_agent",'
        '"authorization":"$sanitized_auth"'
    '}';

    # Буферизованный сброс логов: буфер 64 КБ, принудительный сброс каждые 5 секунд
    access_log /var/log/nginx/access.json json_analytics buffer=64k flush=5s;
    error_log /var/log/nginx/error.log warn;

    server {
        listen 80;
        server_name api.example.local;

        location / {
            proxy_pass http://127.0.0.1:8080;
            
            # Проброс X-Request-ID (если передан клиентом — сохраняем, иначе берем сгенерированный)
            proxy_set_header X-Request-ID $request_id;
            
            # Проброс заголовков реального IP
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
}
```

#### Проверка и валидация

```bash
# 1. Валидация синтаксиса конфигурации Nginx
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Применение конфигурации без разрыва соединений
sudo systemctl reload nginx

# 3. Выполнение тестового запроса с токеном в параметрах
curl -s -o /dev/null -H "traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01" \
     "http://127.0.0.1/?token=super_secret_admin_pass"

# 4. Проверка записи в логе (через 5 секунд после сброса буфера)
tail -n 1 /var/log/nginx/access.json | jq .
# → {
# →   "timestamp": "2026-10-15T10:05:22+03:00",
# →   "server_name": "api.example.local",
# →   "remote_addr": "127.0.0.1",
# →   "request_id": "7b5ef09214b64f33198031db2c68fa81",
# →   "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
# →   "method": "GET",
# →   "uri": "/?token=***REDACTED***",
# →   "status": 502,
# →   "bytes_sent": 173,
# →   "body_bytes_sent": 0,
# →   "request_time": 0.001,
# →   "upstream_connect_time": "0.001",
# →   "upstream_header_time": "-",
# →   "upstream_response_time": "0.001",
# →   "upstream_addr": "127.0.0.1:8080",
# →   "upstream_status": "502",
# →   "http_referrer": "",
# →   "http_user_agent": "curl/8.5.0",
# →   "authorization": "-"
# → }
```

---

### Сценарий 2: Apache HTTP Server 2.4 — JSON CustomLog, ErrorLogFormat и piped-ротация

Настройка структурированного логирования в Apache с микросекундной детализацией времени (`%D`), фиксацией ID потока MPM (`%P:%T`) и непрерывной ротацией через `rotatelogs` без перезагрузки процессов.

```apacheconf
# /etc/apache2/conf-available/logging-production.conf (Debian/Ubuntu)
# или /etc/httpd/conf.d/logging-production.conf (RHEL)

# 1. Формат журнала ошибок с указанием модуля, файла и ID потока
LogLevel warn
ErrorLogFormat "[%{u}t] [%-m:%l] [pid %P:tid %T] %7F: %E: [client %a] %M% ,\ referer\ %{Referer}i"
ErrorLog "|/usr/bin/rotatelogs -l -f -c /var/log/apache2/error_%Y%m%d.log 86400"

# 2. Формат access log в виде строки JSON
# %D — задержка обработки запроса в микросекундах (10^-6 с)
# %{ms}T — задержка обработки запроса в миллисекундах
# %{X-Request-ID}i — заголовок сквозной корреляции
LogFormat "{\"timestamp\":\"%{%Y-%m-%dT%H:%M:%S}t.%{usec_frac}t%{%z}t\",\
\"client_ip\":\"%a\",\
\"server_name\":\"%v\",\
\"method\":\"%m\",\
\"uri\":\"%U\",\
\"query\":\"%q\",\
\"status\":%>s,\
\"bytes_sent\":%B,\
\"duration_us\":%D,\
\"handler\":\"%X\",\
\"request_id\":\"%{X-Request-ID}i\",\
\"user_agent\":\"%{User-Agent}i\",\
\"referer\":\"%{Referer}i\"}" apache_json

# 3. Исключение статических health check из журнала
SetEnvIf Request_URI "^/healthz$" dontlog

# 4. Ротация каждые 86400 секунд (сутки) с локальным временем (-l)
CustomLog "|/usr/bin/rotatelogs -l -f -c /var/log/apache2/access_%Y%m%d.json 86400" apache_json env=!dontlog
```

#### Проверка и валидация

```bash
# Проверка синтаксиса конфигурации Apache
sudo apachectl configtest
# → Syntax OK

# Включение модуля rotatelogs и перезагрузка конфигурации
sudo a2enconf logging-production
sudo systemctl reload apache2

# Тестовый запрос
curl -s -H "X-Request-ID: req-apache-test-001" "http://127.0.0.1/test-url?query=test"

# Чтение сформированного лога
tail -n 1 /var/log/apache2/access_$(date +%Y%m%d).json | jq .
# → {
# →   "timestamp": "2026-10-15T10:10:05.142098+0300",
# →   "client_ip": "127.0.0.1",
# →   "server_name": "default",
# →   "method": "GET",
# →   "uri": "/test-url",
# →   "query": "?query=test",
# →   "status": 404,
# →   "bytes_sent": 274,
# →   "duration_us": 1250,
# →   "handler": "+",
# →   "request_id": "req-apache-test-001",
# →   "user_agent": "curl/8.5.0",
# →   "referer": "-"
# → }
```

---

### Сценарий 3: HAProxy 3.0+ — Логирование через UNIX Domain Socket с кодами завершения сессии (%ts)

HAProxy не пишет логи напрямую в файлы по соображениям изоляции и производительности. Передача логов выполняется в локальный UNIX-сокет демона `rsyslog` или `systemd-journald`.

```haproxy
# /etc/haproxy/haproxy.cfg
global
    # Отправка логов в локальный сокет syslog
    log /dev/log local0 info
    log-tag haproxy-traffic
    maxconn 20000

defaults
    log global
    mode http
    
    # option httplog включает стандартный детализированный формат HTTP
    option httplog
    option dontlognull
    option log-health-checks
    timeout connect 5000ms
    timeout client  50000ms
    timeout server  50000ms

frontend http_in
    bind *:80
    
    # Генерация Correlation ID и добавление в заголовки
    unique-id-format %[uuid]
    unique-id-header X-Request-ID
    
    # Кастомный структурированный log-format для HTTP
    # %ts — флаги завершения сессии (Session termination flags)
    # %TR/%Tw/%Tc/%Tr/%Ta — детальная раскладка таймингов в миллисекундах
    log-format '{"timestamp":"%T","client_ip":"%ci","client_port":%cp,"frontend":"%ft","backend":"%b","server":"%s","status":%ST,"bytes_read":%B,"termination_flags":"%ts","time_req":%TR,"time_queue":%Tw,"time_connect":%Tc,"time_resp":%Tr,"time_total":%Ta,"request_id":"%ID","request":"%r"}'
    
    default_backend app_backends

backend app_backends
    balance roundrobin
    option forwardfor
    server node1 192.168.10.11:8080 check inter 2000ms rise 2 fall 3
    server node2 192.168.10.12:8080 check inter 2000ms rise 2 fall 3
```

#### Настройка rsyslog для приема логов HAProxy

```text
# /etc/rsyslog.d/49-haproxy.conf
$AddUnixListenSocket /dev/log

if $programname == 'haproxy-traffic' then {
    action(type="omfile" file="/var/log/haproxy/access.json" fileOwner="haproxy" fileGroup="adm" fileCreateMode="0640")
    stop
}
```

```bash
# Валидация конфигурации HAProxy
haproxy -c -f /etc/haproxy/haproxy.cfg
# → Configuration file is valid

# Перезапуск rsyslog и перезагрузка HAProxy
sudo systemctl restart rsyslog
sudo systemctl reload haproxy
```

---

### Сценарий 4: Angie — Нативный JSON Error Log и встроенное управление журналами

Angie предоставляет расширенные возможности по сравнению с базовым Nginx: встроенный вывод `error_log` в формате JSON (`format=json`), фильтрацию событий и ограничение скорости записи логов ошибок (`rate`).

```nginx
# /etc/angie/angie.conf
user angie;
worker_processes auto;
pid /run/angie.pid;

# Нативный JSON для журнала ошибок (поддерживается в Angie 1.1+)
error_log /var/log/angie/error.json warn format=json;

events {
    worker_connections 2048;
}

http {
    include /etc/angie/mime.types;
    
    log_format angie_json escape=json '{'
        '"timestamp":"$time_iso8601",'
        '"client_ip":"$remote_addr",'
        '"status":$status,'
        '"request_time":$request_time,'
        '"upstream_time":"$upstream_response_time",'
        '"request_id":"$request_id"'
    '}';

    # access_log с нативной датой в имени файла (встроенная ротация без logrotate)
    access_log /var/log/angie/access_%Y%m%d.json angie_json buffer=32k flush=5s;

    server {
        listen 80;
        server_name angie.example.local;

        location / {
            return 200 '{"status":"ok","server":"angie"}';
        }
    }
}
```

---

### Сценарий 5: Traefik (Bare-metal) — JSON-логирование access и audit

Конфигурация статического файла Traefik для on-premise развертывания с ротацией буфера.

```yaml
# /etc/traefik/traefik.yml
global:
  checkNewVersion: false
  sendAnonymousUsage: false

log:
  level: INFO
  format: json
  filePath: /var/log/traefik/traefik.log

accessLog:
  filePath: /var/log/traefik/access.json
  format: json
  bufferingSize: 100 # Размер буфера в строках
  filters:
    statusCodes:
      - "200-299"
      - "400-599"
    retryAttempts: true
    minDuration: "10ms" # Логировать только запросы дольше 10 мс
  fields:
    defaultMode: keep
    names:
      ClientUsername: drop
    headers:
      defaultMode: drop
      names:
        User-Agent: keep
        Authorization: redact # Автоматическое маскирование
        X-Request-ID: keep
        traceparent: keep
```

---

### Сценарий 6: Промышленная ротация логов через logrotate (с защитой от race conditions)

Корректный сценарий ротации файлов журналов веб-серверов в Linux. Конфигурация предотвращает потерю данных, обеспечивает сжатие `gzip` с отсрочкой на 1 шаг (`delaycompress`) и безопасно отправляет сигнал `USR1` мастер-процессу.

```text
# /etc/logrotate.d/nginx
/var/log/nginx/*.log
/var/log/nginx/*.json {
    # 1. Интервал ротации: ежедневно
    daily
    
    # 2. Не возвращать ошибку при отсутствии файла
    missingok
    
    # 3. Хранить 14 ротированных копий (глубина 14 суток)
    rotate 14
    
    # 4. Сжимать архивные файлы алгоритмом gzip
    compress
    
    # 5. Отложить сжатие access.log.1 до следующего цикла ротации
    # Это гарантирует, что процессы, все еще сбрасывающие буферы, не пишут в gzip-файл
    delaycompress
    
    # 6. Не ротировать пустые файлы логов
    notifempty
    
    # 7. Создавать новый пустой файл с правами 0640, владелец www-data, группа adm
    create 0640 www-data adm
    
    # 8. Запустить postrotate один раз для всех обработанных файлов, а не для каждого отдельно
    sharedscripts
    
    # 9. Сигнал мастер-процессу Nginx на переоткрытие файловых дескрипторов
    postrotate
        if [ -f /run/nginx.pid ]; then
            kill -USR1 $(cat /run/nginx.pid 2>/dev/null) 2>/dev/null || true
        fi
    endscript
}
```

#### Проверка и тестовый запуск logrotate

```bash
# 1. Отладочный запуск (Dry-run): проверяет синтаксис и показывает планируемые действия без изменения файлов
sudo logrotate -d /etc/logrotate.d/nginx
# → reading config file /etc/logrotate.d/nginx
# → Handling 1 logs
# →   rotating pattern: /var/log/nginx/*.log /var/log/nginx/*.json  after 1 days (14 rotations)
# →   empty log files are not rotated, old logs are removed
# →   considering log /var/log/nginx/access.json
# →     log does not need rotating (log has been already rotated)

# 2. Принудительная ротация для тестирования сигналов и прав
sudo logrotate -f /etc/logrotate.d/nginx

# 3. Проверка статуса в базе данных logrotate
grep "nginx" /var/lib/logrotate/status || grep "nginx" /var/lib/logrotate.status
# → "/var/log/nginx/access.json" 2026-10-15-10:15:00
```

---

### Сценарий 7: Сквозная передача и логирование W3C Trace Context и X-Request-ID

Схема связывания клиентского запроса через Nginx Reverse Proxy в бэкенд на Python/FastAPI или Go.

#### Конфигурация Nginx (Edge)

```nginx
# /etc/nginx/conf.d/upstream_tracing.conf
server {
    listen 80;
    server_name service.local;

    location /api/ {
        proxy_pass http://127.0.0.1:5000;
        
        # Если клиент не прислал X-Request-ID, используем внутренний $request_id Nginx
        proxy_set_header X-Request-ID $request_id;
        
        # Передаем входящий traceparent или генерируем синтетический
        proxy_set_header traceparent $http_traceparent;
        
        # Передаем оригинальные сетевые адреса
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

#### Код сервиса бэкенда (Python/FastAPI)

```python
# app.py — пример бэкенда, извлекающего сквозные идентификаторы для логирования
import logging
import json
from fastapi import FastAPI, Request, Response

app = FastAPI()

# Базовая настройка логирования в формате JSON
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        if hasattr(record, "traceparent"):
            log_entry["traceparent"] = record.traceparent
        return json.dumps(log_entry)

handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger = logging.getLogger("app")
logger.setLevel(logging.INFO)
logger.addHandler(handler)

@app.middleware("http")
async def trace_context_middleware(request: Request, call_next):
    # Извлечение заголовков трассировки от Nginx
    request_id = request.headers.get("X-Request-ID", "internal-generated")
    traceparent = request.headers.get("traceparent", "-")
    
    # Фиксация в логгере
    extra = {"request_id": request_id, "traceparent": traceparent}
    logger.info("Обработка входящего вызова API", extra=extra)
    
    response: Response = await call_next(request)
    # Возврат заголовка клиенту для отладки
    response.headers["X-Request-ID"] = request_id
    return response

@app.get("/api/v1/resource")
def get_resource():
    return {"status": "success", "data": [1, 2, 3]}
```

---

### Сценарий 8: Доставка логов через локальный агент Vector в ClickHouse (On-Premise)

Схема сбора локальных JSON access-логов Nginx агентом Vector без использования облачных компонентов.

```toml
# /etc/vector/vector.toml
[sources.nginx_access]
type = "file"
include = ["/var/log/nginx/access.json"]
read_from = "beginning"
ignore_older_secs = 86400

# Парсинг входной строки JSON
[transforms.parse_json]
type = "remap"
inputs = ["nginx_access"]
source = '''
. = parse_json!(string!(.message))
.service = "web-edge"
.environment = "production"
# Преобразование строки времени в timestamp
.timestamp = parse_timestamp!(.timestamp, "%Y-%m-%dT%H:%M:%S%:z")
'''

# Отправка структурированных записей в ClickHouse
[sinks.clickhouse_out]
type = "clickhouse"
inputs = ["parse_json"]
endpoint = "http://127.0.0.1:8123"
database = "logs"
table = "web_access_log"
skip_unknown_fields = true
auth.strategy = "basic"
auth.user = "vector_writer"
auth.password = "StrongLocalPassword123"

[sinks.clickhouse_out.buffer]
type = "memory"
max_events = 10000
when_full = "block"
```

#### Валидация работы пайплайна

```bash
# Проверка конфигурации Vector
vector validate /etc/vector/vector.toml
# → Validated /etc/vector/vector.toml

# Запуск агента Vector в режиме проверки вывода
vector top
```

---

## Операции и команды

Сводка практических команд системного администратора и инженера SRE для управления подсистемой логирования веб-серверов.

### Управление процессами и сигналами переоткрытия логов

```bash
# Отправка сигнала USR1 мастер-процессу Nginx для немедленного переоткрытия дескрипторов
sudo kill -USR1 $(cat /run/nginx.pid)
# → # Команда завершается без вывода; мастер отправляет команду всем воркерам

# Переоткрытие логов в Angie
sudo kill -USR1 $(cat /run/angie.pid)

# Переоткрытие логов в Apache HTTP Server (graceful сигнал без сброса активных сессий)
sudo apachectl -k graceful
# → # Сервер выполняет graceful reload и переоткрывает файлы CustomLog

# Перезапуск подсистемы сбора логов syslog без остановки веб-сервера
sudo systemctl reload rsyslog
```

### Диагностика удаленных и зависших файлов (Ghost Inodes)

```bash
# Поиск файлов с дескрипторами, удаленными из файловой системы, но удерживаемыми процессами
sudo lsof +L1
# → COMMAND   PID     USER   FD   TYPE DEVICE SIZE/OFF NLINK   NODE NAME
# → nginx   14220 www-data    5w   REG  254,1 52428800     0 852104 /var/log/nginx/access.log (deleted)

# Поиск процессов, удерживающих удаленные лог-файлы в каталоге /var/log
sudo lsof -nP | grep -E '/var/log.*\(deleted\)'
# → nginx   14221 www-data    4w      REG  254,1 104857600  852105 /var/log/nginx/access.json (deleted)

# Освобождение дискового пространства без рестарта веб-сервера: усечение через /proc
# (Применяется в экстренных случаях при переполнении диска до 100%)
sudo truncate -s 0 /proc/14221/fd/4
# → # Дисковые блоки мгновенно освобождаются ядром Linux
```

### Оперативный анализ логов в терминале (CLI)

```bash
# 1. Топ-10 клиентских IP-адресов по числу запросов (Combined log)
awk '{print $1}' /var/log/nginx/access.log | sort | uniq -c | sort -nr | head -n 10
# →  15420 192.168.1.105
# →   8210 10.0.4.12
# →   3401 172.16.20.88

# 2. Подсчет распределения HTTP-кодов ответов
awk '{print $9}' /var/log/nginx/access.log | sort | uniq -c | sort -nr
# → 125400 200
# →  14200 304
# →   3120 404
# →    420 502
# →     85 500

# 3. Фильтрация медленных запросов из JSON-лога через jq (время обработки > 1.5 сек)
jq -r 'select(.request_time > 1.5) | [.timestamp, .status, .request_time, .uri] | @tsv' /var/log/nginx/access.json
# → 2026-10-15T10:14:02+03:00	504	2.001	/api/v1/reports/export
# → 2026-10-15T10:14:15+03:00	200	1.854	/api/v1/catalog/search

# 4. Мониторинг логов в реальном времени с фильтрацией серверных ошибок (5xx)
tail -f /var/log/nginx/access.json | jq --unbuffered -r 'select(.status >= 500) | "\(.timestamp) [\(.status)] \(.uri) -> \(.upstream_addr) (\(.upstream_response_time)s)"'
# → 2026-10-15T10:15:30+03:00 [502] /api/checkout -> 127.0.0.1:8080 (0.002s)
```

### Выгрузка логов из systemd-journald

```bash
# Просмотр системных сообщений веб-сервера за последний час с уровнем важности от err до emerg
journalctl -u nginx --since "1 hour ago" -p err..emerg --no-pager
# → Oct 15 09:30:12 node01 nginx[14100]: 2026/10/15 09:30:12 [emerg] 14100#14100: bind() to 0.0.0.0:80 failed (98: Address already in use)

# Просмотр логов HAProxy в journalctl с форматированием в JSON
journalctl -u haproxy -o json-pretty -n 5
```

---

## Диагностика и устранение неполадок

| Симптом / Ошибка | Первопричина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| `df -h` показывает 100% заполнение `/var/log`, но `du -sh` показывает пустой каталог. | Файлы логов удалены администратором командой `rm`, но удерживаются открытыми процессами Nginx/Apache (`ghost inodes`). | `sudo lsof +L1`<br>`lsof -nP \| grep -i '(deleted)'` | Отправить сигнал переоткрытия дескрипторов: `kill -USR1 $(cat /run/nginx.pid)`. На будущее использовать `truncate -s 0` или штатный `logrotate`. |
| Внезапная деградация латентности веб-сервера (всплеск p99 latency), высокий `wa` (I/O wait) в `top`. | Синхронная запись логов без буферизации при пиковой нагрузке на диск или I/O stall. | `iostat -xz 1 5`<br>`pidstat -d 1 5 -p $(pgrep -d, nginx)` | Добавить параметры буферизации: `buffer=64k flush=5s` в директиву `access_log`. При критических нагрузках перевести логи на ramfs/tmpfs или вынести на отдельный физический диск. |
| Сборщик логов (Vector/Fluent Bit/Logstash) выдает ошибку `JSON parse error: invalid character`. | В лог попали неэкранированные спецсимволы (переводы строк `\n`, кавычки `"` в `User-Agent` или URI). | Проверить сырые строки лога: `grep -P '[\x00-\x1f]' /var/log/nginx/access.json` | Включить режим `escape=json` в директиве `log_format` Nginx/Angie. |
| Дублирование строк или обрыв записей в ротированных логах. | Использование директивы `copytruncate` в `logrotate` на высоконагруженном сервере. | Проверка `/etc/logrotate.d/*` на наличие директивы `copytruncate`. | Заменить `copytruncate` на связку `create` + `sharedscripts` + `postrotate (kill -USR1 ...)`. |
| Пропадание сообщений при доставке логов через UDP syslog (`/dev/log` переполнен). | Переполнение очереди сетевого сокета ядра из-за всплеска трафика или зависания демона rsyslog. | `netstat -su` (счетчик `packet receive errors`)<br>`journalctl -u rsyslog` | Увеличить размер сокетного буфера ядра: `sysctl -w net.core.rmem_default=262144`. Перевести отправку логов на локальный UNIX domain socket или TCP. |
| Ошибка `permission denied` при создании файлов логов после ротации. | Некорректные права или владелец в директиве `create` файла `logrotate`. | `ls -la /var/log/nginx/`<br>`namei -om /var/log/nginx/access.log` | Указать корректного пользователя и группу: `create 0640 www-data adm`. Проверить контекст SELinux: `restorecon -Rv /var/log/nginx`. |

---

## Рекомендации и Best Practices

### Архитектура дисковой подсистемы и производительность

1. **Обязательная буферизация access-логов**: В production-окружениях с нагрузкой более 200 RPS директива `access_log` обязана содержать параметры `buffer=32k flush=5s` (или `buffer=64k`). Это снижает нагрузку на дисковый контроллер на 80–90%.
2. **Изоляция раздела `/var/log`**: Каталог `/var/log` должен размещаться на отдельной партиции или LVM-томе файловой системы. Это исключает падение операционной системы (`Kernel Panic`, отказ записи в `/tmp` и `/var/run`) при случайном переполнении диска логами.
3. **Разделение уровней логирования**: Уровень `error_log` в production должен быть установлен в `warn` или `error`. Режим `info` и `debug` допустим только временно при диагностике конкретных инцидентов, так как он генерирует избыточный I/O оверхед.

### Стандартизация форматов и схемы данных

1. **Переход на Structured NDJSON**: Форматируйте `access_log` в виде строгого JSON. Это исключает потребность в громоздких регулярных выражениях на агентах сбора (Vector, Promtail), стабилизирует конвейер данных и уменьшает потребление CPU коллекторами.
2. **Использование стандарта RFC W3C Trace Context**: Для микросервисных приложений пробрасывайте заголовок `traceparent`. Это обеспечивает прозрачную интеграцию access-логов веб-сервера со спанами систем распределенной трассировки.
3. **Единые имена полей (Schema Governance)**: В масштабах инфраструктуры поддерживайте общие имена ключевых полей для всех веб-серверов:
   - Временная метка: `timestamp` (в формате ISO-8601 с таймзоной: `$time_iso8601`);
   - Сетевые адреса: `remote_addr`, `upstream_addr`;
   - Статусы: `status`, `upstream_status`;
   - Длительность: `request_time`, `upstream_response_time` (в секундах с плавающей точкой или микросекундах).

### Безопасность и соответствие нормативам (Compliance)

1. **Маскирование чувствительных параметров**: Исключайте из access-логов авторизационные токены, пароли и куки. Для Nginx используйте директивы `map` для отсечения `?token=...` из `$request_uri`.
2. **Ограничение прав доступа**: Файлы журналов должны создаваться с правами не выше `0640` (чтение владельцем и группой аудита): `create 0640 www-data adm`. Запрещен доступ к чтению логов для пользователей категории `others` (`chmod o-rwx`).
3. **Запрет отдачи логов через веб**: Убедитесь, что конфигурация веб-сервера исключает возможность запросить файлы журналов напрямую через HTTP:
   ```nginx
   location ~* \.(log|json)$ {
       deny all;
       return 404;
   }
   ```

### Политики хранения (Retention) и мониторинг

1. **Двухфазная ротация (`delaycompress`)**: При настройке `logrotate` всегда используйте `delaycompress`. Сжатие вчерашнего лога выполняется только на следующие сутки, что гарантирует сохранность записей от worker-процессов, медленно закрывающих старые дескрипторы.
2. **Алертинг на аномалии в логах**: Настройте в системе мониторинга триггеры на основе метрик из логов:
   - Резкий рост доли кодов `5xx` (> 1% от общего трафика);
   - Увеличение перцентиля задержки `$request_time` (p95 > 500 мс, p99 > 2 с);
   - Появление аварийных ошибок `[emerg]` и `[alert]` в `error.log`.

---

## Дополнительная информация

### Чек-лист готовности подсистемы логирования к Production

- [ ] **Формат access-лога**: Настроен структурированный JSON с директивой экранирования `escape=json`.
- [ ] **Буферизация**: Параметры `buffer=size` и `flush=time` активированы для всех активных виртуальных хостов.
- [ ] **Уровень error log**: Установлен в `warn` или `error`.
- [ ] **Ротация logrotate**: Настроена ежедневная ротация с хранением не менее 14 копий, опцией `delaycompress` и безопасным скриптом `kill -USR1`.
- [ ] **Проверка отладочного запуска**: Команда `sudo logrotate -d /etc/logrotate.d/<service>` выполнена без ошибок синтаксиса.
- [ ] **Изоляция хранилища**: Каталог `/var/log` вынесен на отдельный дисковый раздел или LVM-том.
- [ ] **Права доступа**: Права на файлы логов ограничены маской `0640`, владелец сервисный (`www-data:adm`).
- [ ] **Корреляция**: Настроена генерация и проброс `X-Request-ID` и W3C `traceparent` на upstream-бэкенды.
- [ ] **Безопасность (Sanitization)**: Реализовано маскирование паролей, токенов и чувствительных данных в URI и заголовках.
- [ ] **Централизованный сбор**: Локальный агент (Vector / Fluent Bit) успешно доставляет записи в on-premise хранилище (ClickHouse / Loki).

### См. также

- **[Structured Logging и анализ для веб-производительности](./web_performance/structured_logging_for_performance.md)** — глубокая декомпозиция таймингов, сетевые метрики ядра Linux и архитектура ClickHouse.
- **[Анализ access-логов Nginx через GoAccess и CLI](../Nginx/Operations/nginx_log_analysis.md)** — интерактивный анализ трафика в терминале и построение TUI-дашбордов.
- **[Логирование в Angie](../Angie/angie_logging.md)** — нативный JSON в error_log, директивы фильтрации и ограничения скорости записи ошибок.
- **[Мониторинг HAProxy](./haproxy_monitoring.md)** — метрики PROMEX, Runtime API и расшифровка кодов завершения сессий.
- **[Диагностика веб-серверов (Troubleshooting)](./webserver_troubleshooting.md)** — пошаговая методология локализации аварий и сбоев.
- **[Runbooks и реагирование на инциденты](./runbooks_incident_response.md)** — типовые сценарии восстановления при переполнении дисков и сбоях upstream.
- **[Системная ротация логов (logrotate)](../../Linux/SystemAdministration/Logging/logrotate.md)** — исчерпывающее руководство по параметрам logrotate и системным вызовам в Linux.
- **[Архитектура и настройка rsyslog](../../Linux/SystemAdministration/Logging/rsyslog.md)** — прием и маршрутизация логов через UNIX-сокеты и сетевые протоколы.
- **[Обзор Vector](../../Vector/vector_overview.md)** — высокопроизводительный локальный агент доставки и трансформации логов.
- **[Стек Grafana Loki](../../Loki/loki_overview.md)** — масштабируемое хранение структурированных и неструктурированных логов.
- **[Официальная документация Nginx по модулю ngx_http_log_module](https://nginx.org/en/docs/http/ngx_http_log_module.html)** — синтаксис директив и переменные.
- **[Официальная документация Apache по логированию](https://httpd.apache.org/docs/2.4/logs.html)** — конфигурация LogFormat и CustomLog.
- **[Официальная документация HAProxy по логированию](https://docs.haproxy.org/3.0/configuration.html#8)** — форматирование и параметры syslog.
