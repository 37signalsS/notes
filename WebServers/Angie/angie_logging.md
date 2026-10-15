# Логирование в Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

В веб-сервере Angie логирование является ключевым компонентом наблюдаемости (observability), аудита безопасности и устранения сбоев (troubleshooting). В отличие от классического [Nginx](../Nginx/Core/nginx_overview.md), Angie предоставляет расширенный набор возможностей управления журналами: нативный вывод `error_log` в формате JSON, фильтрацию сообщений по тегам и событиям, ограничение частоты записи сообщений об ошибках (`rate`), пользовательское форматирование времени (`time_format`), кольцевые буферы в памяти и логирование TLS-ключей.

*   **Лог доступа (`access_log`)**: Журнал учета каждого обработанного клиентского запроса (в HTTP) или сессии (в Stream/L4). Запись генерируется на заключительной фазе обработки запроса (`log`), когда сформирован ответ клиенту и подсчитаны метрики времени и объёма переданных данных.
*   **Лог ошибок (`error_log`)**: Журнал системных событий, предупреждений модулей, сетевых сбоев, ошибок конфигурации и диагностических сообщений разного уровня критичности.
*   **Фаза `log` (NGX_HTTP_LOG_PHASE)**: Внутренняя фаза конвейера обработки HTTP-запроса, вызываемая после закрытия соединения с клиентом или отправки последнего байта ответа. Гарантирует корректность переменных времени (`$request_time`, `$upstream_response_time`).
*   **Буферизация логов (`buffer=size`, `flush=time`)**: Механизм накопления записей в кольцевой памяти рабочего процесса перед вызовом системного вызова `write()`, существенно снижающий нагрузку на дисковую подсистему и процессор.
*   **Фильтрация и ограничение ошибок (`filter`, `rate`)**: Специализированные параметры Angie для директивы `error_log`, защищающие сервер от дискового переполнения (Disk DoS) при авариях и позволяющие изолировать сообщения конкретных модулей или запросов.
*   **Пользовательское форматирование времени (`time_format`)**: Директива Angie, создающая строковые переменные времени с произвольным шаблоном `strftime` и долями секунд.
*   **Кэш дескрипторов файлов логов (`open_log_file_cache`)**: Пул файловых дескрипторов для путей к логам, содержащих переменные, предотвращающий постоянные системные вызовы открытия и закрытия файлов.

---

## Базовые концепции и архитектура

### Архитектура подсистемы логирования в Angie

Логирование в Angie выполняется изолированно каждым рабочим процессом (worker process):

```
[Клиентский запрос] ───> [Обработка: find_config -> rewrite -> access -> content]
                                │
                         [Отправка ответа клиенту]
                                │
                         [Фаза NGX_HTTP_LOG_PHASE]
                                │
               ┌────────────────┴────────────────┐
               ▼                                 ▼
   [Проверка условия if=...]          [Формирование строки]
               │                                 │
     (0: отмена записи)                (log_format / escape=json)
                                                 │
                                       [Буфер памяти worker]
                                                 │
                                 ┌───────────────┴───────────────┐
                                 ▼                               ▼
                      (Буфер полон / flush)              (Прямой сброс)
                                 │                               │
                      [write() в файл/stdout]           [sendto() в syslog]
```

1. **Фаза выполнения**: Запись в `access_log` выполняется строго на фазе `log`. Если клиент разорвал соединение до получения ответа (код 499), запрос всё равно попадает в лог с фактически зафиксированными таймингами.
2. **Изоляция буферов**: Каждый worker-процесс выделяет собственный буфер памяти заданного размера. Буферы сбрасываются по достижении лимита байтов либо по таймауту `flush`.
3. **Обработка сигналов**: При получении сигнала `USR1` мастер-процесс Angie переоткрывает все файлы логов и отправляет команду воркерам сделать то же самое. Это предотвращает потерю дескрипторов при ротации.

---

### Лог доступа (`access_log`) и наследование контекстов

Директива `access_log` конфигурируется на уровнях `http`, `server`, `location`, а также внутри блоков `if` в location:

```nginx
access_log path [format [buffer=size] [gzip[=level]] [flush=time] [if=condition]];
access_log off;
```

#### Правило переопределения контекстов
Определение директивы `access_log` на более глубоком уровне (например, в `location`) **полностью отменяет** логирование, настроенное на родительских уровнях (`server` или `http`).
Если необходимо писать запрос одновременно в общий лог сервиса и в отдельный файл эндпоинта, все требуемые директивы `access_log` должны быть явно объявлены в данном контексте:

```nginx
http {
    log_format main '$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent';
    access_log /var/log/angie/access.log main;

    server {
        listen 80;
        server_name api.example.com;

        location /api/v1/ {
            # Переопределяет родительский access_log!
            # Запрос запишется ТОЛЬКО в api_access.log:
            access_log /var/log/angie/api_access.log main;
        }

        location /api/v2/ {
            # Запись одновременно в два файла:
            access_log /var/log/angie/access.log main;
            access_log /var/log/angie/api_v2_access.log main;
        }

        location /healthz {
            # Полное отключение записи для снижения шума
            access_log off;
        }
    }
}
```

---

### Буферизация, сжатие и кэширование дескрипторов

#### Механизм буферизации (`buffer` и `flush`)
По умолчанию `access_log` записывает каждую строку синхронно через системный вызов `write()`. При нагрузке в десятки тысяч RPS постоянное переключение контекста ядра и блокировки I/O создают существенный оверхед.

Параметр `buffer=size` аккумулирует записи в памяти воркера:
* Размер буфера не может превышать атомарный размер записи для используемой файловой системы. Стандартные размеры: `32k`, `64k`, `128k`.
* Параметр `flush=time` задаёт гарантированное время, по истечении которого буфер будет сброшен на диск, даже если он не заполнился целиком.
* При штатном завершении воркера (`QUIT` или reload `HUP`) Angie принудительно сбрасывает накопленный буфер на диск. При аварийном завершении (`SIGKILL`) несохранённые данные теряются.

#### Сжатие логов "на лету" (`gzip`)
Параметр `gzip[=level]` активирует сжатие лога библиотекой zlib перед записью на диск:
* Использование `gzip` автоматически включает буферизацию (по умолчанию буфер равен 64 КБ).
* Уровень сжатия варьируется от 1 (минимальная нагрузка на CPU, быстро) до 9 (максимальное сжатие). Рекомендуемый уровень для production: `gzip=1` или `gzip=2`.
* Файл лога создаётся с расширением `.gz` и может читаться утилитами `zcat`, `zgrep`, `zless`.

#### Кэширование дескрипторов (`open_log_file_cache`)
Директива актуальна **исключительно для путей с переменными** (например, `/var/log/angie/$host-access.log`):
* Без кэширования: для каждого запроса Angie открывает файл (`open()`), производит запись и закрывает дескриптор (`close()`), вызывая катастрофическую деградацию дисковой подсистемы.
* С кэшированием: дескриптор сохраняется в пуле воркера до истечения времени неактивности. Для статических путей без переменных файлы открываются один раз при старте мастера и кэш не требуется.

```nginx
open_log_file_cache max=1000 inactive=30s min_uses=2 valid=1m;
```

---

### Лог ошибок (`error_log`) в Angie

Директива `error_log` конфигурируется в контекстах `main`, `http`, `mail`, `stream`, `server`, `location`.
Формат директивы:

```nginx
error_log file | stderr | syslog:... | memory:size [level] [format=json] [rate=number] [filter=...];
```

#### Уровни детализации (от критического к диагностическому)

| Уровень | Описание | Применение в SRE / Production |
| :--- | :--- | :--- |
| `emerg` | Аварийная ситуация, процесс неработоспособен | Критические сбои ОС, нехватка памяти ядра |
| `alert` | Требуется немедленное вмешательство администратора | Ошибки дескрипторов сокетов, сбои прав доступа |
| `crit` | Критическая ошибка, операция не выполнена | Сбои системных вызовов, переполнение буферов |
| `error` | Ошибка обработки запроса | Ошибки бэкендов 502/504, ошибки SSL-рукопожатий |
| `warn` | Предупреждение о нестандартной ситуации | Рекомендуемый уровень по умолчанию для production |
| `notice` | Штатное информационное событие | Перезагрузка конфигурации, события модуля ACME |
| `info` | Детальная справочная информация | Базовый аудит соединений (высокий объём I/O) |
| `debug` | Глубокий отладочный вывод | Только для поиска багов (требует сборки с debug) |

#### Ограничение скорости (rate)
Параметр `rate=number` (Angie-specific) задаёт максимальное количество сообщений в секунду, записываемых в данный файл лога. Все сообщения сверх лимита подавляются, а в лог выводится сводное уведомление о числе отброшенных записей. Это предотвращает исчерпание места на диске при шторме ошибок бэкенда. По умолчанию лимит составляет 1000 сообщений/сек.

```nginx
# Ограничить запись до 50 сообщений в секунду
error_log /var/log/angie/error.log warn rate=50;
```

#### Гранулярная фильтрация сообщений (filter)
Параметр `filter` (Angie-specific) фильтрует сообщения по префиксу или маске:
* `file`: фильтрация по имени исходного C-файла ядра Angie (например, `filter=file:ngx_http_upstream`).
* `event`: фильтрация по идентификатору внутреннего события (например, `filter=event:http.upstream.peer`).
* `tag`: фильтрация по тегу модуля (`http`, `stream`, `upstream`) или пользовательскому тегу (`error_log_user_tag`). Несколько тегов требуют совпадения всех условий.
* `message`: поиск подстроки, точного совпадения (`=`) или регулярного выражения (`~`) в теле ошибки.
* `logline`: поиск по всей результирующей строке сообщения.

```nginx
# Запись только ошибок таймаутов апстримов
error_log /var/log/angie/upstream_timeouts.log warn filter=message:~"(timed out|upstream timed out)";
```

#### Нативный JSON для лога ошибок (`format=json`)
Angie умеет сериализовать события `error_log` в структурированный JSON без сторонних модулей. В объекте содержатся поля: `timestamp`, `level`, `pid`, `tid`, `message`, `tags`, а также контекст клиентского соединения (`client`, `server`, `request`), если ошибка возникла во время обслуживания HTTP-запроса.

```nginx
error_log /var/log/angie/error.json warn format=json;
```

#### Пользовательские теги (`error_log_user_tag`)
Позволяет присваивать запросам произвольную строковую метку в блоках `server` или `location`. Метка включается в текстовый лог (`tag: <name>`) и в массив `tags` JSON-лога, что позволяет фильтровать логи ошибок конкретных сервисов в отдельные файлы:

```nginx
location /payment/ {
    error_log_user_tag "payment_gateway";
    error_log /var/log/angie/payment_errors.log info filter=tag:payment_gateway;
}
```

#### Циклический буфер в памяти (`memory:size`)
Запись логов в кольцевой буфер RAM без дискового ввода-вывода. Позволяет организовать отладку без износа дисков и риска переполнения накопителя. Данные из буфера считываются через модуль Prometheus/Status API либо gdb. При рестарте данные сбрасываются.

```nginx
error_log memory:32m debug;
```

#### Логирование ключей сессий TLS (`ssl_keylog_file`)
Директива записывает симметричные секреты сессий TLS (Client Traffic Secret, Server Traffic Secret) в формате NSS Key Log. Это позволяет инженерам SRE расшифровывать дампы трафика в Wireshark и `tshark` для анализа проблем на прикладном уровне без раскрытия закрытого ключа сервера.

```nginx
ssl_keylog_file /var/log/angie/ssl_keys.log;
```

---

### Логирование в модуле Stream (L4 TCP/UDP)

В контексте `stream` Angie обрабатывает сырые сетевые соединения. Журналирование настраивается аналогично HTTP, но оперирует метриками транспортного уровня:

```nginx
stream {
    log_format l4_main '$remote_addr [$time_iso8601] $protocol $status '
                       'bytes_sent=$bytes_sent bytes_recv=$bytes_received '
                       'session_time=$session_time upstream=$upstream_addr '
                       'connect_time=$upstream_connect_time';

    access_log /var/log/angie/stream.log l4_main buffer=64k flush=5s;
}
```

---

### Сетевой транспорт логов: Syslog и стандартные потоки

#### Логирование в Syslog
Angie поддерживает прямую передачу логов через протокол Syslog (RFC 3164 / RFC 5424) без промежуточных файлов:
* Синтаксис: `syslog:server=address[,parameter=value]`.
* Поддерживаются адреса IPv4, IPv6, доменные имена и сокеты UNIX: `unix:/dev/log`.
* Транспорт по умолчанию для сетевых адресов — UDP/514.
* Параметры:
  * `facility=local0..local7` (по умолчанию `local7`).
  * `tag=string` (по умолчанию `angie`).
  * `severity=info..emerg` (для `access_log` по умолчанию `info`, для `error_log` наследуется уровень ошибки).
  * `nohostname` — отключает запись имени хоста в заголовок Syslog.

```nginx
access_log syslog:server=unix:/dev/log,facility=local7,tag=angie_access json_combined;
error_log syslog:server=192.168.10.50:514,facility=local6,tag=angie_error warn;
```

#### Стандартные потоки для контейнерных сред
В контейнерах (Docker, Podman, containerd) рабочие процессы Angie направляют логи в `/dev/stdout` и `/dev/stderr`. В официальных образах Angie файлы `/var/log/angie/access.log` и `error.log` предварительно слинкованы с этими псевдоустройствами.

---

## Практические сценарии

### Сценарий 1: Продакшен-конфигурация структурированного JSON-логирования

Стандартный текстовый формат требует сложных регулярных выражений при парсинге. Ниже представлена эталонная конфигурация JSON-лога доступа с безопасным экранированием спецсимволов (`escape=json`), сквозным идентификатором запроса (`$request_id`), метриками задержки апстрима и пользовательским форматированием времени высокой точности.

```nginx
http {
    # 1. Формирование метки времени высокой точности с миллисекундами
    time_format $time_iso_ms "%Y-%m-%dT%H:%M:%S.%L%z";

    # 2. Определение структурированного формата JSON
    log_format json_analytics escape=json
    '{'
        '"timestamp":"$time_iso_ms",'
        '"request_id":"$request_id",'
        '"remote_addr":"$remote_addr",'
        '"remote_user":"$remote_user",'
        '"host":"$host",'
        '"method":"$request_method",'
        '"uri":"$request_uri",'
        '"protocol":"$server_protocol",'
        '"status":$status,'
        '"body_bytes_sent":$body_bytes_sent,'
        '"bytes_sent":$bytes_sent,'
        '"request_length":$request_length,'
        '"request_time":$request_time,'
        '"upstream_addr":"$upstream_addr",'
        '"upstream_status":"$upstream_status",'
        '"upstream_connect_time":"$upstream_connect_time",'
        '"upstream_header_time":"$upstream_header_time",'
        '"upstream_response_time":"$upstream_response_time",'
        '"upstream_cache_status":"$upstream_cache_status",'
        '"http_referrer":"$http_referer",'
        '"http_user_agent":"$http_user_agent",'
        '"ssl_protocol":"$ssl_protocol",'
        '"ssl_cipher":"$ssl_cipher"'
    '}';

    # 3. Применение с буферизацией и сбросом каждые 5 секунд
    access_log /var/log/angie/access.json json_analytics buffer=64k flush=5s;
}
```

Проверка синтаксиса и генерация тестовой записи:

```bash
# Проверка корректности конфигурации
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Перезагрузка воркеров без разрыва соединений
sudo systemctl reload angie

# Проверка валидности сформированного JSON
tail -n 1 /var/log/angie/access.json | jq .
# → {
# →   "timestamp": "2026-10-14T16:20:00.124+0300",
# →   "request_id": "c1a2e3f4b5c6d7e8a9b0c1d2e3f4a5b6",
# →   "remote_addr": "192.168.1.100",
# →   "remote_user": "",
# →   "host": "api.example.com",
# →   "method": "GET",
# →   "uri": "/api/v1/users",
# →   "protocol": "HTTP/1.1",
# →   "status": 200,
# →   "body_bytes_sent": 412,
# →   "bytes_sent": 680,
# →   "request_length": 245,
# →   "request_time": 0.015,
# →   "upstream_addr": "10.0.1.20:8080",
# →   "upstream_status": "200",
# →   "upstream_connect_time": "0.001",
# →   "upstream_header_time": "0.014",
# →   "upstream_response_time": "0.014",
# →   "upstream_cache_status": "MISS",
# →   "http_referrer": "",
# →   "http_user_agent": "curl/8.5.0",
# →   "ssl_protocol": "TLSv1.3",
# →   "ssl_cipher": "TLS_AES_256_GCM_SHA384"
# → }
```

---

### Сценарий 2: Продвинутая настройка `error_log` с JSON, rate limiting и фильтрацией

Разделение журналов ошибок по типам инцидентов, ограничение нагрузки на диск при падении бэкендов и экспорт в JSON.

```nginx
# Глобальный лог ошибок в JSON с ограничением до 100 сообщений/сек
error_log /var/log/angie/error.json warn format=json rate=100;

http {
    server {
        listen 443 ssl;
        server_name payments.example.com;

        # Изолированный лог для ошибок апстримов
        error_log /var/log/angie/upstream_errors.log warn filter=tag:upstream;

        # Лог только критических ошибок HTTP/2 и HTTP/3 протоколов
        error_log /var/log/angie/http2_http3_errors.log error filter=message:~"(h2|h3|QUIC)";

        location /charge {
            # Присвоение тега запросу для точечной фильтрации
            error_log_user_tag "payment_critical";

            # Сбор логов для финансового контура
            error_log /var/log/angie/payments_audit.log info filter=tag:payment_critical;
            
            proxy_pass http://backend_payment;
        }
    }
}
```

Проверка содержимого JSON-лога ошибок:

```bash
tail -n 1 /var/log/angie/error.json | jq .
# → {
# →   "timestamp": "2026-10-14T16:21:05.412+0300",
# →   "level": "error",
# →   "pid": 14210,
# →   "tid": 14210,
# →   "tags": ["http", "upstream"],
# →   "client": "192.168.1.55",
# →   "server": "payments.example.com",
# →   "request": "POST /charge HTTP/1.1",
# →   "message": "connect() to 10.0.1.25:8080 failed (111: Connection refused) while connecting to upstream"
# → }
```

---

### Сценарий 3: Условное логирование (подавление шума и фиксация аномалий)

Высоконагруженные балансировщики генерируют терабайты логов за счёт healthcheck-проверок и статики. С помощью директивы `map` и параметра `if=` в `access_log` настраивается селективное логирование.

```nginx
http {
    # 1. Подавление логирования health check запросов
    map $request_uri $is_not_healthcheck {
        ~^/healthz    0;
        ~^/livez      0;
        ~^/readyz     0;
        default       1;
    }

    # 2. Логирование только медленных запросов (время ответа >= 1.000 секунды)
    map $request_time $is_slow_request {
        ~^[0-9]\.[0-9]+ 1; # Секунда и более
        default         0; # Менее одной секунды
    }

    # 3. Логирование только ошибок (4xx и 5xx)
    map $status $is_http_error {
        ~^[45]   1;
        default  0;
    }

    server {
        listen 80;
        server_name app.example.com;

        # Основной лог не содержит healthcheck
        access_log /var/log/angie/app_access.log extended if=$is_not_healthcheck buffer=32k flush=5s;

        # Выделенный журнал медленных транзакций для анализа SRE
        access_log /var/log/angie/slow_queries.log json_analytics if=$is_slow_request;

        # Выделенный журнал инцидентов (4xx, 5xx)
        access_log /var/log/angie/errors_access.log json_analytics if=$is_http_error;

        location /static/ {
            # Полное отключение логов для статических ассетов
            access_log off;
            expires 30d;
        }
    }
}
```

---

### Сценарий 4: Оптимизация логирования под экстремальные нагрузки (HighLoad)

При объёмах трафика свыше 50 000 RPS и динамическом распределении по виртуальным хостам дисковая подсистема испытывает предельные перегрузки.

```nginx
http {
    log_format perf_log '$remote_addr [$time_iso8601] "$request" '
                        '$status $body_bytes_sent rt=$request_time';

    # 1. Кэш дескрипторов файлов для путей с переменными
    # Хранит до 2000 дескрипторов, проверяет валидность раз в минуту
    open_log_file_cache max=2000 inactive=40s min_uses=3 valid=1m;

    server {
        listen 80;
        server_name ~^(?<domain>.+)\.example\.com$;

        # 2. Запись в динамический файл с буфером 128 КБ и gzip сжатием
        access_log /var/log/angie/hosts/$domain.log.gz perf_log buffer=128k gzip=1 flush=10s;
    }
}
```

Проверка создания сжатого файла лога:

```bash
ls -lh /var/log/angie/hosts/
# → -rw-r----- 1 angie adm 142K Oct 14 16:22 api.log.gz

# Чтение сжатого лога без предварительной распаковки
zcat /var/log/angie/hosts/api.log.gz | tail -n 2
# → 192.168.1.20 [2026-10-14T16:22:10+03:00] "GET /v1/ping HTTP/1.1" 200 15 rt=0.001
# → 192.168.1.21 [2026-10-14T16:22:11+03:00] "GET /v1/ping HTTP/1.1" 200 15 rt=0.001
```

---

### Сценарий 5: Логирование в модуле Stream (L4 TCP/UDP)

Настройка логирования для L4-балансировки кластера PostgreSQL или сервисов DNS.

```nginx
stream {
    log_format pg_stream '$remote_addr [$time_iso8601] '
                         'status=$status bytes_sent=$bytes_sent bytes_recv=$bytes_received '
                         'session_time=$session_time upstream=$upstream_addr '
                         'connect_time=$upstream_connect_time';

    server {
        listen 5432;
        proxy_pass postgres_backends;

        # Логирование завершенных TCP-сессий
        access_log /var/log/angie/postgres_stream.log pg_stream buffer=32k flush=5s;
    }
}
```

Пример записи в логе после завершения клиентской сессии к СУБД:

```bash
tail -n 1 /var/log/angie/postgres_stream.log
# → 192.168.1.50 [2026-10-14T16:23:01+03:00] status=200 bytes_sent=48210 bytes_recv=12400 session_time=12.450 upstream=10.0.2.15:5432 connect_time=0.002
```

---

### Сценарий 6: Автоматическая ротация логов через `logrotate`

В Angie по умолчанию отсутствует встроенный механизм ротации. Для предотвращения переполнения диска используется системный демон `logrotate`. Ротация должна быть атомарной и сопровождаться отправкой сигнала `USR1` мастер-процессу Angie.

Создайте конфигурационный файл `/etc/logrotate.d/angie`:

```
/var/log/angie/*.log
/var/log/angie/*.json
{
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 0640 angie adm
    sharedscripts
    postrotate
        if [ -f /run/angie.pid ]; then
            kill -USR1 $(cat /run/angie.pid)
        fi
    endscript
}
```

Пояснения директив:
* `daily` / `rotate 30` — ротация раз в сутки с глубиной хранения 30 дней.
* `compress` / `delaycompress` — сжатие gzip с откладыванием сжатия предыдущего лога на один цикл (чтобы процесс успел полностью закрыть старый дескриптор).
* `create 0640 angie adm` — создание нового файла с правами пользователя `angie` и группы `adm`.
* `sharedscripts` — скрипт `postrotate` выполнится один раз для всех файлов маски, а не для каждого отдельно.
* `kill -USR1 $(cat /run/angie.pid)` — команда переоткрытия дескрипторов. В Angie также поддерживается команда `angie -s reopen`.

Тестирование и проверка ротации:

```bash
# Тестовый прогон без реальной модификации файлов (dry-run)
sudo logrotate -d /etc/logrotate.d/angie
# → reading config file /etc/logrotate.d/angie
# → Allocating hash table for state file, count entries: 2
# → Handling 1 logs
# → rotating pattern: /var/log/angie/*.log /var/log/angie/*.json  after 1 days (30 rotations)
# → running postrotate script

# Принудительная немедленная ротация
sudo logrotate -f /etc/logrotate.d/angie
# → [OK]

# Проверка переоткрытия файлов (процесс должен писать в новый файл)
ls -la /var/log/angie/
# → -rw-r----- 1 angie adm   4210 Oct 14 16:25 access.log
# → -rw-r----- 1 angie adm 512300 Oct 14 16:24 access.log.1
```

---

### Сценарий 7: On-Prem контейнеры (Docker/Podman)

При развертывании Angie в локальном контейнере (Docker Compose, локальный Kubernetes без облачных провайдеров) логи должны транслироваться в стандартные потоки демона контейнеризации:

```nginx
# В конфигурации /etc/angie/angie.conf:
error_log /dev/stderr warn;

http {
    # Лог доступа направляется в stdout с небольшим буфером
    access_log /dev/stdout json_analytics buffer=16k flush=2s;
}
```

Проверка потока через CLI контейнера:

```bash
# Просмотр логов контейнера в реальном времени
docker logs -f --tail 50 angie-proxy
# → {"timestamp":"2026-10-14T16:25:01.001+0300","request_id":"...","status":200,"request_time":0.002}
```

---

### Сценарий 8: Прямая отправка логов в Syslog (rsyslog / syslog-ng)

Для централизованного аудита на выделенный локальный сервер rsyslog:

```nginx
http {
    # Отправка access-логов в syslog по UDP на локальный коллектор
    access_log syslog:server=192.168.10.15:514,facility=local7,tag=angie_prod,severity=info json_analytics buffer=32k flush=5s;

    # Отправка error-логов через локальный UNIX сокет
    error_log syslog:server=unix:/dev/log,facility=local6,tag=angie_err warn;
}
```

Конфигурация приемника на сервере rsyslog (`/etc/rsyslog.d/30-angie.conf`):

```ini
module(load="imudp")
input(type="imudp" port="514")

if $programname == 'angie_prod' then /var/log/remote/angie_access.log
& stop
```

Проверка сетевой доступности порта Syslog и работы конвейера:

```bash
# Проверка UDP порта коллектора
nc -zvu 192.168.10.15 514
# → Connection to 192.168.10.15 514 port [udp/syslog] succeeded!
```

---

### Анализ логов утилитами Linux (CLI Sysadmin Toolkit)

Быстрый анализ инцидентов на сервере без развертывания тяжелых стеков сбора:

```bash
# 1. Топ-10 клиентов по числу запросов
awk '{print $1}' /var/log/angie/access.log | sort | uniq -c | sort -rn | head -n 10
# → 15420 192.168.1.105
# →  8210 10.0.0.12
# →  3100 172.16.0.4

# 2. Распределение кодов ответов HTTP
awk '{print $9}' /var/log/angie/access.log | sort | uniq -c | sort -rn
# → 85400 200
# →  4200 304
# →  1200 404
# →   340 502
# →    52 504

# 3. Поиск запросов с кодом 502/504 в JSON-логе с помощью jq
jq -r 'select(.status >= 500) | [.timestamp, .status, .upstream_addr, .request_time, .uri] | @tsv' /var/log/angie/access.json | tail -n 5
# → 2026-10-14T16:26:10.112+0300	502	10.0.1.25:8080	0.002	/api/v1/checkout
# → 2026-10-14T16:26:12.441+0300	504	10.0.1.26:8080	60.001	/api/v1/reports

# 4. Расчет среднего времени ответа (latency) по логу JSON
jq -s 'map(.request_time) | add / length' /var/log/angie/access.json
# → 0.0452

# 5. Мониторинг лога ошибок в реальном времени с фильтрацией системных сбоев
tail -F /var/log/angie/error.log | grep --line-buffered -E "(emerg|alert|crit)"
```

---

## Операции и команды

Сводная таблица административных команд управления логированием Angie:

| Команда | Контекст выполнения | Назначение и ожидаемый результат |
| :--- | :--- | :--- |
| `sudo angie -t` | CLI / Root | Валидация синтаксиса конфигурации логирования |
| `sudo angie -s reload` | CLI / Root | Применение изменений в `log_format` без остановки сервера |
| `sudo angie -s reopen` | CLI / Root | Переоткрытие всех файлов логов (штатная ротация) |
| `sudo kill -USR1 $(cat /run/angie.pid)` | CLI / Shell | Системный сигнал переоткрытия дескрипторов логов |
| `sudo logrotate -d /etc/logrotate.d/angie` | CLI / Root | Тестирование конфигурации ротации без изменения файлов |
| `sudo logrotate -f /etc/logrotate.d/angie` | CLI / Root | Немедленная принудительная ротация всех логов |
| `zcat /var/log/angie/*.gz \| head` | CLI / Shell | Чтение сжатых ротированных логов на лету |
| `jq -C . /var/log/angie/access.json \| less -R` | CLI / Shell | Интерактивный просмотр JSON-логов с подсветкой синтаксиса |

---

## Устранение неполадок

### Ошибка 1: `open() "/var/log/angie/error.log" failed (13: Permission denied)`

**Симптом:** Angie отказывается запускаться или перезагружаться. В терминале отображается:
```
angie: [emerg] open() "/var/log/angie/error.log" failed (13: Permission denied)
```

**Причина:** Неверный владелец директории логов или блокировка политиками SELinux / AppArmor.

**Диагностика:**
```bash
ls -ld /var/log/angie
# → drwxr-xr-x 2 root root 4096 Oct 14 15:00 /var/log/angie
```

**Решение:**
1. Назначить корректного системного владельца `angie:adm` (или `angie:angie` в зависимости от дистрибутива):
```bash
sudo chown -R angie:adm /var/log/angie
sudo chmod 750 /var/log/angie
```
2. В системах с SELinux (RHEL, Rocky, AlmaLinux) восстановить правильный контекст безопасности `httpd_log_t`:
```bash
sudo semanage fcontext -a -t httpd_log_t "/var/log/angie(/.*)?"
sudo restorecon -Rv /var/log/angie
# → Relabeled /var/log/angie from unconfined_u:object_r:var_log_t:s0 to unconfined_u:object_r:httpd_log_t:s0
```

---

### Ошибка 2: Логи после ротации не появляются в новом файле

**Симптом:** Файл `/var/log/angie/access.log` переименован утилитой ротации в `access.log.1`, создан новый пустой `access.log` с размером 0 байт, но размер нового файла не растет, а данные продолжают записываться в `access.log.1`.

**Причина:** Процесс Angie удерживает открытый файловый дескриптор (inode) старого файла, так как не был отправлен или не сработал сигнал `USR1`.

**Диагностика:**
```bash
# Проверка процесса, удерживающего дескриптор старого файла
sudo lsof +D /var/log/angie | grep deleted
# → angie   14212 angie    7w   REG  253,1 1542100 131254 /var/log/angie/access.log.1 (deleted)
```

**Решение:**
1. Проверить актуальный путь к PID-файлу Angie:
```bash
cat /run/angie.pid
# → 14209
```
2. Отправить сигнал переоткрытия дескрипторов вручную:
```bash
sudo kill -USR1 $(cat /run/angie.pid)
# либо
sudo angie -s reopen
```
3. Убедиться, что в `/etc/logrotate.d/angie` прописан корректный путь `/run/angie.pid`, а не устаревший `/var/run/angie.pid` без прав доступа.

---

### Ошибка 3: Переполнение дискового пространства из-за лавины логов

**Симптом:** Раздел `/var/log` заполнен на 100%. Сервис аварийно останавливается или блокирует прием соединений.

**Причина:** Включен уровень `debug` в production, либо при аварии бэкенда произошел шторм ошибок (Disk DoS).

**Диагностика:**
```bash
df -h /var/log
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda3        20G   20G     0 100% /var/log

# Определение файла-виновника
du -ah /var/log/angie | sort -rh | head -n 5
# → 18G    /var/log/angie/error.log
```

**Решение:**
1. **Не удалять файл через `rm`!** Если удалить файл командой `rm`, его дескриптор останется открытым в памяти воркера, и место на диске **не освободится** до перезапуска Angie.
2. Очистить файл на лету через обнуление (truncate):
```bash
sudo truncate -s 0 /var/log/angie/error.log
# Место освобождается немедленно:
df -h /var/log
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda3        20G  2.1G   18G  11% /var/log
```
3. Снизить уровень детализации в конфигурации до `warn` и ограничить скорость записи с помощью `rate`:
```nginx
error_log /var/log/angie/error.log warn rate=50;
```
4. В `/etc/logrotate.d/angie` добавить критерий ротации по объему:
```
maxsize 500M
```

---

### Ошибка 4: Нарушение структуры JSON из-за неэкранированных символов

**Симптом:** Агенты сбора логов (Vector, Promtail, Fluent Bit) выдают ошибки `JSON parse error: invalid character in string`.

**Причина:** Пользовательский заголовок (`User-Agent`, `Referer`, `Cookie`) содержит неэкранированные кавычки `"` или спецсимволы `\r`, `\n`.

**Диагностика:**
```bash
tail -n 20 /var/log/angie/access.json | jq .
# → parse error: Invalid escape at line 1, column 248
```

**Решение:** В определении `log_format` **обязательно** указывать параметр `escape=json`:

```nginx
# Корректное экранирование всех управляющих символов:
log_format json_secure escape=json
'{'
    '"time":"$time_iso8601",'
    '"user_agent":"$http_user_agent"'
'}';
```

---

### Ошибка 5: Потери или задержки сообщений при буферизации

**Симптом:** При отправке тестового запроса строка не появляется в `access.log` немедленно при использовании `tail -f`.

**Причина:** Включен параметр `buffer=...`, и буфер воркера ещё не заполнен.

**Решение:**
1. Для диагностики в development-окружении отключить буферизацию либо задать минимальный таймер сброса:
```nginx
access_log /var/log/angie/access.log json_analytics buffer=4k flush=1s;
```
2. Понимать поведение: буферизация не теряет данные, а сбрасывает их пачками по таймауту `flush` или при завершении процесса.

---

## Лучшие практики (DevOps / SRE / Sysadmin)

1.  **Всегда использовать `escape=json` для структурированных логов**: Без экранирования спецсимволов в заголовках `User-Agent` и URL пайплайны централизованного сбора логов будут аварийно отбрасывать события.
2.  **Защита диска параметром `rate=` в `error_log`**: В production всегда ограничивайте частоту записи ошибок (`rate=100` или `rate=50`), чтобы избежать переполнения диска и деградации производительности ядра ОС при авариях бэкендов.
3.  **Обязательная буферизация на высоких нагрузках**: Директива `access_log ... buffer=64k flush=5s` сокращает количество системных вызовов `write()` на порядки, снижая загрузку CPU и I/O wait.
4.  **Маскирование конфиденциальных данных (PII/Security)**: Никогда не логируйте пароли, токены сессий и заголовки `Authorization` в открытом виде. Используйте директиву `map` для их маскирования:
    ```nginx
    map $http_authorization $masked_auth {
        ""          "";
        default     "Bearer [REDACTED]";
    }
    ```
5.  **Фильтрация синтетического шума**: Отключайте логирование для статических файлов (`access_log off;`) и подавляйте запись служебных проверок доступности (`healthz`/`livez`) через `if=...`.
6.  **Корректная ротация через `kill -USR1`**: Настройте `logrotate` с вызовом `kill -USR1 $(cat /run/angie.pid)` и правами `0640 angie adm`. Не используйте директиву `copytruncate` без крайней необходимости, так как она приводит к кратковременной потере строк лога в момент копирования.
7.  **Использование `open_log_file_cache` при динамических путях**: Если имя лог-файла содержит переменные (например, `$host.log`), обязательно включайте кэш дескрипторов, иначе на каждый запрос будет выполняться два системных вызова ядра (`open` и `close`).
8.  **Алертинг по метрикам заполнения диска**: Настраивайте алерты в мониторинге на 75-80% заполнения раздела `/var/log` до того, как раздел переполнится полностью.

---

## Дополнительная информация

### Взаимодействие с системными компонентами

*   **Системы централизованного сбора логов**: Для потоковой доставки структурированных JSON-логов Angie на локальные хранилища данных (ClickHouse, Elasticsearch) рекомендуется использовать легковесные локальные агенты:
    *   [Vector](../../Vector/vector_overview.md) — высокопроизводительный агент маршрутизации и трансформации данных.
    *   [Fluent Bit](../../Linux/SystemAdministration/Logging/fluent_bit.md) — минималистичный сборщик с встроенным парсером JSON.
    *   [Grafana Loki](../../Loki/loki_overview.md) — система хранения и индексации логов по метаданным.
*   **Системные сервисы ротации и логирования**:
    *   [logrotate](../../Linux/SystemAdministration/Logging/logrotate.md) — детальная архитектура жизненного цикла ротации и сжатия.
    *   [rsyslog](../../Linux/SystemAdministration/Logging/rsyslog.md) — настройка локальных и сетевых сокетов Syslog.
    *   [Маскирование PII](../../Linux/SystemAdministration/Logging/pii_masking.md) — принципы защиты чувствительных данных в журналах.

---

### См. также

*   [Архитектура и обзор Angie](./angie_overview.md) — базовые принципы функционирования сервера.
*   [Установка и базовая настройка Angie](./angie_installation.md) — структура каталогов, системные пользователи и права.
*   [Переменные в Angie](./angie_variables.md) — полный справочник переменных запросов, апстримов и времени.
*   [L4 балансировка и проксирование (модуль Stream)](./l4_balancing_and_proxying.md) — параметры и переменные сессий TCP/UDP.
*   [Graceful Reload и Binary Upgrade](./angie-graceful-reload.md) — работа сигналов сервера (`USR1`, `HUP`, `QUIT`).
*   [Мониторинг Angie](./angie_monitoring/angie_monitoring_concepts.md) — Status API, консоль и метрики Prometheus.
*   [Анализ access-логов Nginx/Angie](../Nginx/Operations/nginx_log_analysis.md) — консольный анализ с помощью GoAccess и конвейеров CLI.
*   [Диагностика и устранение неисправностей](../Nginx/Operations/nginx_troubleshooting.md) — типовые коды ошибок и сбои бэкендов.
