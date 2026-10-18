# Анализ access-логов Nginx (GoAccess и CLI)

**Актуально для:** Nginx 1.26+, GoAccess 1.9+, logrotate 3.20+

## Определения

**Access log (журнал доступа)** — системный журнал Nginx, в который записывается отдельная строка метаданных на каждый завершенный HTTP/HTTPS-запрос. Формируется в фазе `NGX_HTTP_LOG_PHASE` и настраивается директивами `log_format` и `access_log`.

**Error log (журнал ошибок)** — журнал системных событий веб-сервера, ошибок модулей, сбоев TLS-рукопожатий, аварийных завершений worker-процессов и проблем соединения с upstream-серверами. Настраивается директивой `error_log` и не зависит от формата access-лога.

**GoAccess** — высокопроизводительный потоковый анализатор веб-логов с открытым исходным кодом. Предоставляет интерактивный консольный интерфейс (TUI на базе `ncurses`) и генерирует веб-дашборды в формате HTML с обновлением данных в реальном времени через WebSocket.

**Combined Log Format (CLF)** — классический текстовый формат логов Nginx и Apache, включающий IP клиента, идентификатор, дату/время, строку запроса, HTTP-статус, размер ответа, `Referer` и `User-Agent`. Не содержит таймингов обработки и сведений об upstream.

**Structured Logging (NDJSON)** — представление каждой записи лога в виде отдельного валидного объекта JSON (Newline Delimited JSON) с экранированием символов (`escape=json`), что гарантирует машиночитаемость и исключает ошибки разбора регулярными выражениями.

**Timing Breakdown (декомпозиция времени)** — совокупность метрик задержки на различных этапах жизненного цикла HTTP-запроса (`$request_time`, `$upstream_connect_time`, `$upstream_header_time`, `$upstream_response_time`), позволяющая локализовать сетевые, серверные и клиентские узкие места.

**Unlinked open file descriptor (открытый дескриптор удаленного файла)** — состояние в ОС Linux, когда файл лога удален командой `rm`, но процесс Nginx продолжает удерживать его открытым. Пространство на диске не освобождается до отправки сигнала `USR1` или перезапуска процесса.

**Correlation ID (`$request_id`)** — уникальный 16-байтный шестнадцатеричный идентификатор запроса, генерируемый Nginx для сквозной трассировки транзакции между access-логом, error-логом и логами бэкенд-приложений.

---

## Основные концепции и архитектура

### Архитектура подсистемы логирования в Nginx

Запись в access-лог выполняется не в момент получения запроса, а на финальной стадии его жизненного цикла:

```text
[ Клиент ] ──── HTTP-запрос ────► [ Nginx Worker: TLS -> Routing -> Proxy ]
                                                  │
                                          [ Отправка ответа ]
                                                  │
                                          [ Фаза NGX_HTTP_LOG_PHASE ]
                                                  │
                                 ┌────────────────┴────────────────┐
                                 ▼                                 ▼
                        [ Проверка if=$condition ]        [ Формирование строки ]
                                 │                                 │
                         (0: пропуск записи)                       ▼
                                                        [ Буфер в памяти worker ]
                                                                   │
                                            ┌──────────────────────┴──────────────────────┐
                                            ▼                                             ▼
                                 [ Буфер полон / flush=5s ]                      [ Прямой сокет ]
                                            │ write(2)                                    │ sendto(2)
                                   [ Файл на диске ]                             [ Syslog UDP/UNIX ]
```

1. **Фаза исполнения (`NGX_HTTP_LOG_PHASE`):** Срабатывает строго после того, как последний байт ответа отправлен в сокет клиента, либо когда клиент оборвал соединение досрочно (код `499`). Это обеспечивает абсолютную точность подсчета переданных байт (`$body_bytes_sent`, `$bytes_sent`) и затраченного времени (`$request_time`).
2. **Изоляция буферов worker-процессов:** При включении буферизации (`buffer=64k`) каждый worker накапливает записи в своей независимой области памяти. Системный вызов `write(2)` инициируется только при заполнении буфера либо по тайм-ауту (`flush=5s`), что снижает I/O-нагрузку на диск в десятки раз.
3. **Условное логирование (`if=condition`):** Позволяет исключать из журнала синтетический трафик (проверки жизнеспособности health check от балансировщиков или Prometheus-экспортеров), снижая объем ненужных записей на 80–90%.

### Декомпозиция временных метрик

Для SRE и системных администраторов ключевой задачей анализа access-лога является локализация причин деградации латентности:

```text
[ Клиент ] ──────── TCP Handshake / TLS ────────► [ Nginx ] ────── TCP / TLS ──────► [ Upstream ]
    │                                                 │                                    │
    │── HTTP Request ────────────────────────────────►│ (Старт: $request_time)             │
    │                                                 │── Connect ($u_connect_time) ──────►│
    │                                                 │── Request Headers/Body ───────────►│
    │                                                 │                                    │ [ Обработка ]
    │                                                 │◄─ First Header Byte ($u_header_t) ─│ (TTFB бэкенда)
    │                                                 │◄─ Last Body Byte ($u_response_t) ──│
    │◄─ Response Headers/Body ────────────────────────│                                    │
    │◄─ Last Response Byte ───────────────────────────│ (Финиш: $request_time)
```

Семантика и взаимосвязь метрик:

| Поле в Nginx | Описание и измеряемый отрезок | Диагностический вывод при аномалии |
| :--- | :--- | :--- |
| `$request_time` | Полное время от чтения первого байта запроса от клиента до завершения передачи последнего байта ответа клиенту. Включает сетевую задержку клиента. | Если `$request_time` значительно выше `$upstream_response_time`, задержка вызвана медленным клиентом, потерей пакетов в сети или медленным чтением большого тела ответа. |
| `$upstream_connect_time` | Время установления соединения с upstream-сервером (TCP handshake, а при `proxy_pass https://` — также TLS handshake). | Рост значения (> 2–5 мс в локальной сети) указывает на перегрузку очереди бэкенда (`listen backlog`), нехватку worker-процессов приложения или исчерпание эфемерных портов. |
| `$upstream_header_time` | Время от отправки запроса upstream до получения первого байта заголовков ответа (серверный Time to First Byte — TTFB). | Показывает чистую длительность работы бэкенда (выполнение кода, запросы к СУБД, обращение к внешним микросервисам). |
| `$upstream_response_time` | Полное время взаимодействия с upstream: от установления соединения до вычитывания последнего байта тела ответа. | Несколько значений через запятую (например, `0.050, 1.200`) означают, что первый бэкенд вернул ошибку или тайм-аут, и Nginx выполнил retry на следующий upstream. |

### Архитектура и принцип работы GoAccess

GoAccess оптимизирован для работы в условиях ограниченных ресурсов сервера:

1. **In-Memory и On-Disk хранилище:** По умолчанию GoAccess строит хэш-таблицы в оперативной памяти (в среднем 120 КБ на 10 000 строк лога). Для работы с историческими терабайтными архивами поддерживается дисковая персистентность на базе B+Tree storage (`--persist` и `--restore`).
2. **Terminal UI (TUI):** Использует библиотеку `ncurses`, обеспечивая real-time мониторинг через SSH-сессию без необходимости поднимать графический стек или браузер.
3. **Real-Time WebSocket Server:** GoAccess содержит встроенный асинхронный сервер WebSocket (порт по умолчанию `7890`). При генерации HTML-дашборда с флагом `--real-time-html` браузер подключается к демону GoAccess, получая JSON-диффы новых строк лога в реальном времени.

### Механика ротации и сигналы ядра Linux

Файловые системы ext4/XFS идентифицируют открытые файлы по номеру `inode`, а не по пути в каталоге:

```text
1. Исходное состояние:
   Nginx Worker (fd 4) ────────► inode 892113 [ /var/log/nginx/access.log ]

2. logrotate переименовывает файл:
   Nginx Worker (fd 4) ────────► inode 892113 [ /var/log/nginx/access.log.1 ]

3. logrotate создает новый пустой файл:
   Новый файл на диске           inode 892550 [ /var/log/nginx/access.log ]
   (Nginx ВСЁ ЕЩЕ ПИШЕТ в старый inode 892113!)

4. postrotate отправляет сигнал kill -USR1:
   Master-процесс Nginx закрывает старый дескриптор и открывает путь заново:
   Nginx Worker (fd 4) ────────► inode 892550 [ /var/log/nginx/access.log ]
```

- Сигнал `USR1` заставляет master-процесс Nginx переоткрыть все открытые файлы логов и передать новые дескрипторы worker-процессам. В отличие от `HUP` (reload), сигнал `USR1` не перезапускает воркеры и не сбрасывает сетевые соединения.
- Удаление активного лога через `rm /var/log/nginx/access.log` удаляет имя файла из каталога, но `inode` остается активным. Пространство на диске остается занятым, пока Nginx не получит `USR1` или не будет перезапущен.

---

## Практические сценарии и конфигурация

### Предварительные требования и установка

Установка GoAccess и системных утилит в Linux-дистрибутивах:

```bash
# Debian / Ubuntu (из официального стабильного репозитория)
sudo apt update && sudo apt install -y goaccess jq datamash mmdb-bin
# → Набор пакетов успешно установлен

# RHEL / Rocky Linux / AlmaLinux
sudo dnf install -y epel-release
sudo dnf install -y goaccess jq datamash
# → Complete!

# Проверка версии GoAccess
goaccess --version
# → GoAccess - 1.9.3.
# → Config file: /etc/goaccess/goaccess.conf
```

### Настройка форматов логов в Nginx

Для глубокого анализа в конфигурацию `/etc/nginx/nginx.conf` добавляются два специализированных формата: расширенный текстовый (`extended`) и структурированный JSON (`json_analytics`).

```nginx
http {
    # 1. Условное логирование: исключение health-check запросов из access.log
    map $request_uri $loggable {
        ~/healthz        0;
        ~/ready          0;
        ~/nginx_status   0;
        default          1;
    }

    # 2. Расширенный текстовый формат с таймингами и upstream
    log_format extended '$remote_addr - $remote_user [$time_local] '
                        '"$request" $status $body_bytes_sent '
                        '"$http_referer" "$http_user_agent" '
                        '"$http_x_forwarded_for" '
                        'rt=$request_time uct=$upstream_connect_time '
                        'uht=$upstream_header_time urt=$upstream_response_time '
                        'uaddr=$upstream_addr ustatus=$upstream_status '
                        'cs=$upstream_cache_status req_id=$request_id';

    # 3. Структурированный JSON-формат для централизованных парсеров
    log_format json_analytics escape=json '{'
        '"timestamp":"$time_iso8601",'
        '"remote_addr":"$remote_addr",'
        '"request_id":"$request_id",'
        '"method":"$request_method",'
        '"uri":"$request_uri",'
        '"protocol":"$server_protocol",'
        '"status":$status,'
        '"bytes_sent":$bytes_sent,'
        '"body_bytes_sent":$body_bytes_sent,'
        '"request_time":$request_time,'
        '"upstream_connect_time":"$upstream_connect_time",'
        '"upstream_header_time":"$upstream_header_time",'
        '"upstream_response_time":"$upstream_response_time",'
        '"upstream_addr":"$upstream_addr",'
        '"upstream_status":"$upstream_status",'
        '"upstream_cache_status":"$upstream_cache_status",'
        '"http_referer":"$http_referer",'
        '"http_user_agent":"$http_user_agent",'
        '"http_x_forwarded_for":"$http_x_forwarded_for"'
    '}';

    # Применение с буферизацией в памяти и фильтрацией синтетических запросов
    access_log /var/log/nginx/access_extended.log extended buffer=64k flush=5s if=$loggable;
    access_log /var/log/nginx/access.json json_analytics buffer=64k flush=5s if=$loggable;
}
```

Проверка конфигурации и перечитывание без остановки сервиса:

```bash
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

sudo systemctl reload nginx
# → сервис успешно перечитал конфигурацию
```

---

### Сценарий 1: Интерактивный анализ в реальном времени через GoAccess (TUI)

Запуск интерактивного мониторинга стандартного Combined-лога через терминал:

```bash
goaccess /var/log/nginx/access.log --log-format=COMBINED
# → Открывается полноэкранный TUI-интерфейс
```

Управление в TUI:
- `F1` / `h`: Справка по горячим клавишам.
- `Tab` / `Shift+Tab`: Переключение между панелями (Dashboard, Visitors, Requests, 404s, OS, Browsers, Geo).
- `Enter` или `Пробел`: Развернуть выбранную панель для подробного просмотра всех строк.
- `0`–`9`: Быстрый переход к конкретному модулю/панели.
- `/`: Поиск по содержимому активной панели.
- `q`: Выход из утилиты.

Запуск потокового разбора в реальном времени (`tail -f`):

```bash
tail -n 1000 -f /var/log/nginx/access.log | goaccess --log-format=COMBINED -
# → TUI обновляется по мере поступления новых запросов
```

---

### Сценарий 2: Полноценный Real-time HTML-дашборд через WebSocket и systemd

Для непрерывного мониторинга логов без постоянного запуска CLI GoAccess разворачивается как фоновый демон с генерацией HTML и WebSocket-трансляцией.

#### 1. Создание каталога и запуск тестового отчета

```bash
sudo mkdir -p /var/www/html/reports
sudo goaccess /var/log/nginx/access.log \
  --log-format=COMBINED \
  -o /var/www/html/reports/index.html \
  --real-time-html \
  --addr=127.0.0.1 \
  --port=7890 \
  --daemonize
# → Daemonized GoAccess: PID 14205
```

#### 2. Создание systemd unit-файла `/etc/systemd/system/goaccess.service`

Для автоматического перезапуска и изоляции создайте сервис:

```ini
[Unit]
Description=GoAccess Real-Time Web Log Analyzer
After=network.target nginx.service
Requires=nginx.service

[Service]
Type=simple
User=www-data
Group=www-data
ExecStart=/usr/bin/goaccess /var/log/nginx/access.log \
    --log-format=COMBINED \
    -o /var/www/html/reports/index.html \
    --real-time-html \
    --addr=127.0.0.1 \
    --port=7890 \
    --persist \
    --db-path=/var/lib/goaccess
Restart=always
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

```bash
sudo mkdir -p /var/lib/goaccess && sudo chown -R www-data:www-data /var/lib/goaccess /var/www/html/reports
sudo systemctl daemon-reload
sudo systemctl enable --now goaccess.service
sudo systemctl status goaccess.service
# → Active: active (running) since Thu 2026-10-16 10:14:00 UTC; 5s ago
```

#### 3. Настройка Nginx с защитой отчета и проксированием WebSocket

```nginx
server {
    listen 80;
    server_name monitoring.internal;

    root /var/www/html/reports;
    index index.html;

    # Защита отчета базовой аутентификацией
    auth_basic "Restricted SRE Metrics";
    auth_basic_user_file /etc/nginx/.htpasswd;

    # Проксирование WebSocket-потока GoAccess
    location /ws {
        proxy_pass http://127.0.0.1:7890;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}
```

---

### Сценарий 3: Парсинг кастомного формата с таймингами в GoAccess

Дефолтный пресет `COMBINED` не учитывает `$request_time` и `$upstream_response_time`. Для анализа задержек в GoAccess задается явная строка формата.

Соответствие спецификаторов GoAccess:
- `%h` — `$remote_addr` (IP клиента)
- `%^` — игнорируемый токен/поле
- `%d` — дата, соответствующая `--date-format`
- `%t` — время, соответствующее `--time-format`
- `%r` — строка запроса (`$request`)
- `%s` — статус ответа (`$status`)
- `%b` — размер ответа (`$body_bytes_sent`)
- `%R` — заголовок `Referer`
- `%u` — заголовок `User-Agent`
- `%T` — время обработки в секундах с миллисекундами (`$request_time`)

Команда разбора расширенного лога:

```bash
goaccess /var/log/nginx/access_extended.log \
  --log-format='%h %^[%d:%t %^] "%r" %s %b "%R" "%u" "%^" rt=%T %^' \
  --date-format='%d/%b/%Y' \
  --time-format='%H:%M:%S'
# → Открывается TUI с активной панелью Time Taken (Latency Distribution)
```

Конфигурационный файл `/etc/goaccess/goaccess.conf` для постоянной фиксации настроек:

```ini
time-format %H:%M:%S
date-format %d/%b/%Y
log-format %h %^[%d:%t %^] "%r" %s %b "%R" "%u" "%^" rt=%T %^
ignore-crawlers true
```

---

### Сценарий 4: Оперативный SRE/CLI анализ без внешних утилит (awk, sed, sort, uniq, jq)

Когда инцидент происходит на удаленном хосте без предустановленного GoAccess, анализ выполняется стандартным набором утилит UNIX.

#### 1. Топ-10 атакующих/активных IP-адресов

```bash
awk '{print $1}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -10
# →   48291 192.168.1.105
# →   12402 10.0.4.12
# →    8910 172.16.88.2
# →    3100 192.168.1.44
```

#### 2. Распределение запросов по кодам HTTP-ответов

```bash
awk '{print $9}' /var/log/nginx/access.log | sort | uniq -c | sort -rn
# → 145021 200
# →  12400 304
# →   4120 404
# →   1890 502
# →    450 499
```

#### 3. Подсчет текущего RPS (запросов в секунду) по минутам

```bash
awk -F'[' '{print $2}' /var/log/nginx/access.log | awk -F':' '{print $1":"$2":"$3}' | uniq -c | awk '{print $2, "->", $1/60, "req/sec"}' | tail -5
# → 16/Oct/2026:10:11 -> 342.15 req/sec
# → 16/Oct/2026:10:12 -> 358.80 req/sec
# → 16/Oct/2026:10:13 -> 410.20 req/sec
# → 16/Oct/2026:10:14 -> 680.50 req/sec
# → 16/Oct/2026:10:15 -> 712.10 req/sec
```

#### 4. Расчет перцентилей задержки (p50, p90, p95, p99) на чистом awk

Вычисление квантилей времени ответа (`$request_time`) по структурированному JSON-логу:

```bash
grep -o '"request_time":[0-9.]*' /var/log/nginx/access.json | cut -d':' -f2 | sort -n | awk '
BEGIN { count = 0; }
{
    values[count++] = $1;
}
END {
    if (count == 0) { print "Нет данных"; exit; }
    p50 = values[int(count * 0.50)];
    p90 = values[int(count * 0.90)];
    p95 = values[int(count * 0.95)];
    p99 = values[int(count * 0.99)];
    printf "Total Requests: %d\n", count;
    printf "p50: %.3f s\np90: %.3f s\np95: %.3f s\np99: %.3f s\n", p50, p90, p95, p99;
}'
# → Total Requests: 84210
# → p50: 0.012 s
# → p90: 0.085 s
# → p95: 0.240 s
# → p99: 1.150 s
```

#### 5. Топ-10 самых медленных эндпоинтов (поиск узких мест бэкенда)

```bash
awk '{
    for(i=1; i<=NF; i++) {
        if ($i ~ /^rt=/) { split($i, a, "="); rt=a[2]; }
    }
    print rt, $7;
}' /var/log/nginx/access_extended.log | sort -rn | head -10
# → 4.821 /api/v1/export/orders
# → 3.910 /api/v1/reports/pdf
# → 2.850 /api/v1/search/aggregate
# → 2.410 /api/v1/users/bulk
```

#### 6. Трассировка сбоев и корреляция по `$request_id`

Если в логе зафиксирована 502-я ошибка, сквозной идентификатор позволяет найти точную причину в `error.log` Nginx и журналах приложения:

```bash
# 1. Извлечение request_id проблемного запроса с кодом 502
grep ' 502 ' /var/log/nginx/access_extended.log | tail -1 | grep -o 'req_id=[a-f0-9]*' | cut -d'=' -f2
# → a8f9c1b34e2098d71109bc44f123a9e1

# 2. Поиск соответствующей ошибки в error.log Nginx
grep 'a8f9c1b34e2098d71109bc44f123a9e1' /var/log/nginx/error.log
# → 2026/10/16 10:14:22 [error] 14211#14211: *894101 connect() failed (111: Connection refused) while connecting to upstream, client: 192.168.1.105, server: api.internal, request: "POST /api/v1/checkout HTTP/1.1", upstream: "http://127.0.0.1:8080/checkout", request_id: "a8f9c1b34e2098d71109bc44f123a9e1"
```

#### 7. Фильтрация и выборка ошибок через `jq`

```bash
jq -r 'select(.status >= 500) | [.timestamp, .status, .remote_addr, .upstream_response_time, .uri] | @tsv' /var/log/nginx/access.json | head -5
# → 2026-10-16T10:14:22+03:00	502	192.168.1.105	-	/api/v1/checkout
# → 2026-10-16T10:14:25+03:00	504	10.0.4.12	30.001	/api/v1/reports/generate
```

---

### Сценарий 5: Анализ сжатых архивных логов (`.gz`, `.zst`)

В production-средах ротированные логи архивируются. Для работы с ними без предварительной распаковки на диск используются утилиты потокового чтения:

```bash
# Поиск инцидентов во всех сжатых архивах gzip за прошлые дни
zgrep ' 500 ' /var/log/nginx/access.log.*.gz | awk '{print $7}' | sort | uniq -c | sort -rn | head -5
# →    142 /checkout/pay
# →     58 /auth/login
# →     12 /cart/add

# Потоковая передача сотен архивов напрямую в GoAccess
zcat /var/log/nginx/access.log.*.gz | goaccess --log-format=COMBINED -a -o /var/www/html/reports/historical.html
# → Сгенерирован суммарный исторический отчет

# Если используется сжатие Zstandard (.zst)
zstdcat /var/log/nginx/access.log.*.zst | awk '{print $9}' | sort | uniq -c
# →  890124 200
# →   12401 404
# →     311 500
```

---

### Сценарий 6: Продакшен-конфигурация logrotate

Для исключения переполнения диска и зависших файловых дескрипторов конфигурация `/etc/logrotate.d/nginx` настраивается следующим образом:

```text
/var/log/nginx/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data adm
    sharedscripts
    prerotate
        if [ -d /etc/logrotate.d/httpd-prerotate ]; then \
            run-parts /etc/logrotate.d/httpd-prerotate; \
        fi \
    endscript
    postrotate
        # Переоткрытие дескрипторов логов без рестарта воркеров
        [ -f /run/nginx.pid ] && kill -USR1 $(cat /run/nginx.pid)
    endscript
}
```

Ключевые директивы:
- `daily` + `rotate 14`: Хранение архивов за 14 дней с ежедневной ротацией.
- `compress` + `delaycompress`: Сжатие вчерашнего лога откладывается на следующий цикл, предотвращая сжатие файла, в который Nginx мог дописывать последние буферизованные строки.
- `sharedscripts`: Скрипт `postrotate` выполняется ровно один раз для всего набора совпавших логов, а не для каждого файла отдельно.
- `kill -USR1 $(cat /run/nginx.pid)`: Отправка сигнала переоткрытия дескрипторов.

Ручная проверка и отладка ротации:

```bash
# Тестовый сухой прогон (Dry Run)
sudo logrotate -d /etc/logrotate.d/nginx
# → reading config file /etc/logrotate.d/nginx
# → considering log /var/log/nginx/access.log
# → log does not need rotating (log has been already rotated)

# Принудительное выполнение ротации
sudo logrotate -f /etc/logrotate.d/nginx
# → ротация успешно выполнена
```

---

### Сценарий 7: Прямая отправка логов в syslog (rsyslog / syslog-ng)

В системах без локального сохранения логов на диск Nginx передает записи напрямую в локальный или сетевой демон логирования по протоколу Syslog:

```nginx
http {
    # Отправка логов в локальный сокет rsyslog через UNIX-домен
    access_log syslog:server=unix:/dev/log,facility=local7,tag=nginx_access,severity=info extended;
    error_log  syslog:server=unix:/dev/log,facility=local7,tag=nginx_error,severity=warn;

    # Альтернатива: отправка по UDP на локальный порт rsyslog/вектора (localhost:514)
    # access_log syslog:server=127.0.0.1:514,facility=local7,tag=nginx_access combined;
}
```

Настройка фильтрации в `/etc/rsyslog.d/40-nginx.conf`:

```text
# Фильтрация по тегу и сохранение в отдельный каталог
if ($programname == 'nginx_access') then {
    action(type="omfile" file="/var/log/rsyslog/nginx/access.log" flushOnTXEnd="off" ioBufferSize="64k")
    stop
}
if ($programname == 'nginx_error') then {
    action(type="omfile" file="/var/log/rsyslog/nginx/error.log")
    stop
}
```

```bash
sudo rsyslogd -N1
# → rsyslogd: version 8.2310.0, config validation run... SUCCESS

sudo systemctl restart rsyslog
# → служба rsyslog перезапущена
```

---

### Сценарий 8: Конвейер доставки структурированных логов через Vector (в ClickHouse / Loki)

В современных SRE-инфраструктурах логи доступа Nginx сбрасываются в формате `escape=json` (см. раздел «Настройка форматов логов в Nginx») и вычитываются локальным агентом **Vector** для обогащения и отправки в централизованные хранилища (ClickHouse, Loki, OpenSearch):

Конфигурация агента `/etc/vector/vector.yaml`:

```yaml
sources:
  nginx_access_logs:
    type: file
    include:
      - /var/log/nginx/access_json.log
    read_from: beginning

  nginx_error_logs:
    type: file
    include:
      - /var/log/nginx/error.log
    read_from: beginning

transforms:
  # Парсинг JSON access-лога и приведение типов данных
  parse_access_json:
    type: remap
    inputs:
      - nginx_access_logs
    source: |
      . = parse_json!(string!(.message))
      # Преобразование числовых полей
      .status = to_int!(.status)
      .request_time = to_float!(.request_time)
      .bytes_sent = to_int!(.bytes_sent)
      
      # Обработка upstream таймингов (если запрос не уходил в upstream, поле равно "-")
      if .upstream_response_time != "-" && .upstream_response_time != null {
        .upstream_response_time = to_float!(.upstream_response_time)
      } else {
        .upstream_response_time = 0.0
      }

  # Парсинг неструктурированного формата error.log Nginx регулярным выражением
  parse_error_log:
    type: remap
    inputs:
      - nginx_error_logs
    source: |
      # Паттерн: YYYY/MM/DD HH:MM:SS [level] pid#tid: *cid message, client: ...
      parsed, err = parse_regex(.message, r'^(?P<timestamp>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) \[(?P<level>\w+)\] (?P<pid>\d+)#(?P<tid>\d+): \*(?P<cid>\d+) (?P<msg>.*?), client: (?P<client>[^,]+), server: (?P<server>[^,]+), request: "(?P<request>[^"]+)"(?:, upstream: "(?P<upstream>[^"]+)")?')
      if err == null {
        . = merge(., parsed)
        del(.message)
      }

sinks:
  # Отправка структурированных логов в Loki
  to_loki:
    type: loki
    inputs:
      - parse_access_json
    endpoint: http://loki.infra.internal:3100
    encoding:
      codec: json
    labels:
      service: "nginx"
      status: "{{ status }}"
      host: "{{ host }}"

  # Для аналитики сверхвысокого RPS — прямая вставка в ClickHouse
  to_clickhouse:
    type: clickhouse
    inputs:
      - parse_access_json
    endpoint: http://clickhouse.infra.internal:8123
    database: logs
    table: nginx_access_log
    skip_unknown_fields: true
```

---

## Операции и команды

Сводная таблица параметров и команд анализа логов:

| Команда / Параметр | Описание и назначение |
| :--- | :--- |
| `goaccess -f <file> --log-format=COMBINED` | Анализ статического лог-файла в интерактивном консольном TUI. |
| `goaccess -f <file> -o report.html` | Однократная генерация статического HTML-отчета. |
| `goaccess -f <file> -o report.html --real-time-html --port=7890` | Запуск сервера отчетов с передачей динамических обновлений по WebSocket. |
| `--persist` и `--restore` | Сохранение промежуточных агрегатов на диск и их чтение при последующих запусках. |
| `--db-path=<dir>` | Указание директории для файлов постоянного хранения GoAccess. |
| `--invalid-requests=<file>` | Запись строк, которые не подошли под шаблон `--log-format`, в отдельный файл для отладки. |
| `--ignore-crawlers` | Фильтрация популярных поисковых ботов (Google, Yandex, Bing) из статистики. |
| `--exclude-ip=<ip/subnet>` | Исключение трафика внутренних балансировщиков или мониторинга. |
| `nginx -s reopen` | Переоткрытие файлов логов без перезапуска worker-процессов (эквивалент `kill -USR1`). |
| `lsof +L1` / `lsof \| grep deleted` | Поиск дескрипторов удаленных логов, удерживающих место на диске. |

---

## Устранение неполадок

### 1. GoAccess: «Token doesn't match specifier» / 100% нераспознанных строк

**Симптомы:** При запуске GoAccess завершается с ошибкой `Parsed 0 lines` или `Format Errors - 100%`.  
**Причина:** Шаблон в `--log-format` не совпадает с фактической структурой строки в файле лога (например, в Nginx используется кастомный формат с таймингами, а GoAccess запущен с `--log-format=COMBINED`).  
**Решение:**
1. Просмотрите первую строку лога:
   ```bash
   head -n 1 /var/log/nginx/access.log
   # → 192.168.1.10 - - [16/Oct/2026:10:14:02 +0300] "GET /api HTTP/1.1" 200 120 "-" "curl/7.88.1" rt=0.002
   ```
2. Запустите GoAccess с опцией сбора битых строк:
   ```bash
   goaccess /var/log/nginx/access.log --log-format=COMBINED --invalid-requests=/tmp/bad_lines.log
   cat /tmp/bad_lines.log | head -n 3
   # → Показывает конкретные несовпадающие токены
   ```
3. Составьте явный шаблон, сопоставив каждое поле со спецификатором (см. Сценарий 3).

---

### 2. WebSocket: «WebSocket connection failed» в браузере

**Симптомы:** HTML-отчет GoAccess загружается, но статус обновления в шапке показывает `Disconnected`, консоль браузера выдает `WebSocket connection to 'ws://...:7890/' failed`.  
**Причина:** Порт 7890 заблокирован локальным межсетевым экраном (`ufw`/`firewalld`), демон слушает только `127.0.0.1`, либо доступ к отчету идет по HTTPS, а браузер блокирует небезопасный `ws://` (Mixed Content).  
**Решение:**
1. Проверьте статус сокета GoAccess на сервере:
   ```bash
   ss -tulpn | grep 7890
   # → tcp LISTEN 0 128 127.0.0.1:7890 users:(("goaccess",pid=14205,fd=4))
   ```
2. При использовании SSL/TLS настройте проксирование WebSocket внутри Nginx (см. Сценарий 2) и укажите `--ws-url=wss://monitoring.internal/ws` при запуске GoAccess.

---

### 3. Утечка места на диске («Unlinked open file descriptor»)

**Симптомы:** Команда `df -h` рапортует 100% заполнение раздела `/var/log`, а утилита `du -sh /var/log/*` показывает, что суммарный объем файлов не превышает нескольких сотен мегабайт.  
**Причина:** Лог-файл был удален администратором командой `rm /var/log/nginx/access.log` вместо ротации. Процесс Nginx удерживает открытый файловый дескриптор, и ядро Linux не освобождает блоки файловой системы.  
**Решение:**
1. Найдите удерживающие дескрипторы процессы:
   ```bash
   sudo lsof +L1 | grep nginx
   # → nginx 14210 www-data 4w REG 253,1 42949672960 0 892113 /var/log/nginx/access.log (deleted)
   ```
2. Отправьте Nginx сигнал переоткрытия дескрипторов:
   ```bash
   sudo nginx -s reopen
   # → Nginx освобождает удаленный inode 892113
   ```
3. Проверьте доступное пространство на разделе:
   ```bash
   df -h /var/log
   # → /dev/vda2   50G   4.2G   43G   9% /var/log
   ```

---

### 4. В логах отсутствуют данные апстрима (`$upstream_*` содержат дефисы `-`)

**Симптомы:** В колонках `$upstream_addr`, `$upstream_response_time`, `$upstream_status` записываются дефисы `-`.  
**Причина:** 
- Запрос был обработан локально Nginx без проксирования (раздача статических файлов, ответ из модуля `return`, перенаправление `rewrite`).
- Ответ был полностью взят из кэша Nginx (`$upstream_cache_status: HIT`).
- Клиент оборвал TCP-соединение до того, как Nginx успел отправить запрос на upstream-сервер (статус `400` или `499`).  
**Решение:** Это штатное поведение Nginx. Для проверки проксируемых запросов фильтруйте записи с ненулевым адресом: `awk '$NF != "-" {print $0}'`.

---

### 5. Высокий `$request_time` при низком `$upstream_response_time`

**Симптомы:** Запрос длится 5–10 секунд (`rt=7.420`), в то время как бэкенд ответил за 15 миллисекунд (`urt=0.015`).  
**Причина:** 
- Медленный клиент (мобильная сеть с высоким RTT и потерей пакетов), медленно вычитывающий тело ответа.
- Клиент отправляет большой объем данных (POST/PUT файлов) на медленной скорости загрузки при включенной буферизации `client_body_buffer_size`.
- Включен лимит скорости `limit_rate` на стороне Nginx.  
**Решение:** Проверьте сетевые метрики TCP-соединения через переменную `$tcpinfo_rtt` и сопоставьте размер ответа (`$body_bytes_sent`). Если задержка на медленных клиентах мешает бэкендам, настройте `proxy_buffering on;` для развязки бэкенда и клиента.

---

### 6. Искажение колонок в `awk` из-за пробелов в `$request` или `User-Agent`

**Симптомы:** Скрипты на `awk` с разделителем по умолчанию (пробел) смещают номера полей, если клиент прислал пробелы внутри URI или нестандартный User-Agent.  
**Причина:** Пробел внутри `"GET /path with space HTTP/1.1"` разбивает поле `$7` на несколько фрагментов.  
**Решение:**
1. Используйте разбор JSON-логов утилитой `jq`, где каждое поле типизировано и защищено от искажений.
2. Для текстовых логов используйте разбор регулярными выражениями или `gawk` с `FPAT`:
   ```bash
   awk -v FPAT='([^ ]+)|(\"[^\"]+\")|(\\[[^\\]]+\\])' '{print $1, $4, $7}' /var/log/nginx/access.log | head -3
   # → Корректно извлекает IP, дату и HTTP-статус без смещения колонок
   ```

---

## Лучшие практики

1. **Всегда включайте `$request_time` и `$upstream_response_time`:** Стандартный Combined-формат недостаточен для SRE-эксплуатации. Без таймингов апстрима невозможно различить сетевые сбои клиентов и зависание бэкенда.
2. **Используйте буферизацию записи логов в production:** Параметры `buffer=64k flush=5s` устраняют дисковые блокировки при кратковременных всплесках нагрузки (RPS spikes).
3. **Фильтруйте синтетические проверки жизнеспособности:** Применяйте директиву `if=$loggable` на базе блока `map`, чтобы миллионы запросов `/healthz` не вытесняли ценные данные из дисковых буферов и кэшей ОС.
4. **Защищайте веб-дашборды GoAccess:** Не открывайте порт WebSocket (`7890`) в публичный интернет. Заворачивайте трафик через Nginx Reverse Proxy с обязательной аутентификацией (`auth_basic`) и TLS-шифрованием (`wss://`).
5. **Используйте `escape=json` для машиночитаемых журналов:** Это предотвращает инъекции управляющих символов и гарантирует корректную работу локальных коллекторов (Vector, Promtail, Filebeat).
6. **Никогда не удаляйте логи через `rm` на работающем сервере:** Для принудительной очистки используйте `> /var/log/nginx/access.log` (усечение без смены inode) либо штатный запуск `logrotate -f /etc/logrotate.d/nginx`.
7. **Разделяйте журналы по виртуальным хостам (`server`):** Ведение отдельных access-логов для API, статики и панели управления снижает шум при расследовании точечных инцидентов.
8. **Автоматизируйте оповещения по кодам `5xx` и `429`:** Анализ логов через CLI незаменим при расследовании, но первичное обнаружение аномалий должно базироваться на системных метриках и алертинге.

---

## Дополнительная информация

### Связанные темы в базе знаний

- **[Диагностика и устранение неисправностей Nginx](./nginx_troubleshooting.md)** — системная методология выявления сбоев, анализ кодов 502/504 и восстановление работоспособности.
- **[Обзор Nginx](../Core/nginx_overview.md)** — архитектура master/worker процессов, Event Loop и модель обработки соединений.
- **[Настройка мониторинга Nginx с VTS](./nginx_vts_monitoring_setup.md)** — экспорт метрик трафика, задержек и статусов в Prometheus без парсинга текстовых файлов.
- **[Практическая конфигурация балансировки нагрузки](../Proxy/Load_Balancing/practical_configuration.md)** — пулы `upstream`, keepalive-соединения и обработка ошибок бэкендов.
- **[Логирование веб-серверов](../../Concepts/webserver_logging.md)** — концептуальная архитектура подсистем логирования Nginx, Angie, Apache и HAProxy.
- **[Structured Logging и анализ для веб-производительности](../../Concepts/web_performance/structured_logging_for_performance.md)** — детальный анализ перцентилей задержек, метрик ядра `$tcpinfo_*` и оптимизация Event Loop.
- **[logrotate: Ротация и сжатие логов](../../../Linux/SystemAdministration/Logging/logrotate.md)** — системные механизмы управления жизненным циклом логов, параметры сжатия и сигналы ядра.
- **[rsyslog: Фильтрация и пересылка логов](../../../Linux/SystemAdministration/Logging/rsyslog.md)** — сбор системных логов через сокеты и централизованная доставка по сети.
- **[Логирование в Angie](../../Angie/angie_logging.md)** — расширенные возможности логирования (JSON в error_log, встроенный мониторинг).