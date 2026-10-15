# Мониторинг PHP-FPM

**Актуально для:** PHP 8.2 / 8.3 / 8.4, Prometheus 3.x, Linux kernel 6.x

## Определения

**PHP-FPM (FastCGI Process Manager)** — менеджер процессов FastCGI с расширенным функционалом управления пулами воркеров, предназначенный для обработки динамических PHP-запросов от веб-серверов (Nginx, Angie, Apache). В отличие от классического встраивания в веб-сервер, PHP-FPM функционирует как самостоятельный системный демон, изолируя выполнение прикладного кода, обеспечивая разграничение привилегий и адаптивное управление ресурсами операционной системы.

**PHP-FPM Status Page** — встроенный механизм самодиагностики пулов FPM, предоставляющий оперативную информацию о состоянии воркеров, системных очередях соединений и времени выполнения запросов. Эндпоинт настраивается директивой `pm.status_path` в конфигурации пула и поддерживает вывод в текстовом формате, JSON, XML и OpenMetrics.

**Scoreboard** — структура данных в разделяемой оперативной памяти (Shared Memory, `mmap`), используемая мастер-процессом PHP-FPM для отслеживания состояния каждого воркера в реальном времени. Воркеры атомарно обновляют свои слоты без блокировки соседних процессов, что обеспечивает минимальные накладные расходы при сборе телеметрии.

**OpenMetrics** — формат представления метрик, поддерживаемый PHP-FPM нативно начиная с версии 8.1 (через параметр `?openmetrics`), обеспечивающий совместимость с Prometheus без обязательного использования сторонних экспортеров.

**Listen Backlog (Listen Queue)** — системная очередь соединений на уровне сокета ядра Linux, ожидающих принятия (`accept()`) свободным воркером PHP-FPM. Максимальный размер ограничивается меньшим из двух параметров: `net.core.somaxconn` в ядре и `listen.backlog` в конфигурации пула.

**Slowlog** — встроенный механизм профилирования PHP-FPM, регистрирующий полный стек вызовов (PHP backtrace) для скриптов, чье время выполнения превысило значение параметра `request_slowlog_timeout`.

**pm.max_spawn_rate** — параметр пула PHP-FPM (введен в PHP 8.1), регулирующий максимальное число дочерних процессов, которое мастер-процесс может создавать за одну секунду при лавинообразном росте нагрузки (значение по умолчанию — 32).

**SRE Golden Signals для PHP-FPM** — четыре фундаментальные метрики работоспособности и производительности сервиса применительно к пулу воркеров:
*   *Latency* — длительность обработки FastCGI-запроса (`request duration` и Nginx `$upstream_response_time`).
*   *Traffic* — интенсивность входящих запросов (`accepted conn`).
*   *Errors* — фатальные ошибки PHP, аварийные завершения воркеров (SIGSEGV/SIGBUS) и возвращаемые веб-сервером коды 502/504.
*   *Saturation* — глубина очереди соединений (`listen queue`) и частота исчерпания пула (`max children reached`).

---

## Архитектура и основные концепции

### Жизненный цикл FastCGI-запроса

Для корректной интерпретации метрик необходимо учитывать путь прохождения запроса через компоненты веб-стека:

```
Клиент → Nginx/Angie (HTTP 80/443) 
           ↓ FastCGI binary protocol (Unix Domain Socket / TCP)
       Ядро Linux (Socket Listen Backlog)
           ↓ accept()
       PHP-FPM Master Process (управление процессами, Scoreboard)
           ↓ назначение задачи
       Воркер FPM (Idle → Running → Script Execution → Idle)
           ↓ медленный запрос (> request_slowlog_timeout)
       Запись стека в slowlog
           ↓ ответ веб-серверу
Клиент ← Nginx/Angie (HTTP 200/502/504)
```

Мастер-процесс PHP-FPM запускается с привилегиями `root`, открывает сокеты и порождает непривилегированные рабочие процессы (воркеры, например, `www-data`). Мастер не занимается прямой трансляцией контента запроса — соединения передаются воркерам, либо воркеры сами конкурируют за `accept()` на общем сокете ядра (в зависимости от архитектуры epoll/kqueue).

### Внутреннее устройство Scoreboard

PHP-FPM аллоцирует блок разделяемой памяти (`mmap`), разделенный на слоты по числу максимально возможных процессов (`pm.max_children`). Каждый слот содержит:
1.  Системный PID воркера.
2.  Текущий статус (`Idle`, `Running`, `Finishing`, `Reading`).
3.  Время старта и количество обработанных запросов.
4.  Продолжительность последнего запроса (`request duration`).
5.  Потребление процессорного времени (`last request cpu`) и пик памяти (`last request memory`).
6.  URI запроса и абсолютный путь к выполняемому файлу (`script`).

Когда поступает запрос к `/fpm-status`, воркер считывает состояние всех слотов Scoreboard и формирует отчет в запрошенном формате.

### Модели управления процессами (Process Management)

Выбранная директива `pm` напрямую определяет профиль мониторинга и критичность метрик:

| Модель | Поведение воркеров | Особенности профиля метрик | Типичный сценарий использования |
| :--- | :--- | :--- | :--- |
| **`static`** | Запущено фиксированное число `pm.max_children`. | Метрика `idle processes` отображает свободный резерв; общее число процессов не меняется; минимальная латентность за счет отсутствия `fork()`. | Высоконагруженные production-сервисы с выделенным объемом RAM. |
| **`dynamic`** | Мастер динамически изменяет число воркеров в пределах от `pm.min_spare_servers` до `pm.max_children`. | Колебания `total processes`; при резких всплесках трафика метрика `max children reached` сигнализирует о нехватке лимита. | Универсальные веб-серверы с переменным трафиком. |
| **`ondemand`** | Воркеры создаются только при поступлении трафика и уничтожаются через `pm.process_idle_timeout`. | Высокая латентность первого запроса (cold start); частые колебания `start since` у дочерних процессов; экономия RAM при простое. | Shared-хостинги, вспомогательные dev/staging стенды. |

### Разбор ключевых метрик

#### 1. Очереди и насыщение (Saturation)
*   **`listen queue`**: Число запросов, ожидающих в очереди сокета ядра ОС, так как все воркеры заняты выполнением кода. В штатном режиме равно `0`. Значение `> 0` указывает на то, что производительность пула исчерпана.
*   **`listen queue len`**: Максимальный размер очереди backlog. Если `listen queue` достигает `listen queue len`, ядро перестает принимать новые TCP-соединения (отправляет RST или молча отбрасывает SYN-пакеты) либо отклоняет подключение к Unix-сокету с ошибкой `EAGAIN`/`ECONNREFUSED`. На стороне веб-сервера регистрируются ошибки `502 Bad Gateway` (`connect() to unix:/... failed (11: Resource temporarily unavailable)`).
*   **`max listen queue`**: Пиковое значение очереди, зафиксированное с момента старта пула.
*   **`max children reached`**: Счетчик (монотонно возрастающий), показывающий, сколько раз пул упирался в лимит `pm.max_children`. Ненулевой прирост счетчика означает, что входящие запросы принудительно задерживались в очереди.

#### 2. Состояние пула воркеров
*   **`active processes`**: Число воркеров, выполняющих PHP-код в текущий момент. Резкий скачок активных процессов при неизменном трафике указывает на замедление нижележащих сервисов (блокировки в базе данных, задержки сетевых API).
*   **`idle processes`**: Число свободных воркеров, готовых принять новый запрос.
*   **`total processes`**: Текущее суммарное количество процессов (`active + idle`).
*   **`max active processes`**: Максимальное число одновременно занятых воркеров с момента запуска.
*   **`start since`**: Время непрерывной работы мастер-процесса в секундах. Сброс этого значения свидетельствует о перезапуске службы, сбое или вмешательстве OOM Killer.

#### 3. Производительность и ресурсы
*   **`slow requests`**: Суммарное количество запросов, время обработки которых превысило `request_slowlog_timeout`.
*   **`memory peak`** (PHP 8.1+): Пиковое потребление памяти пулом (в байтах) с момента старта.

#### 4. Детальные метрики отдельных воркеров (`?full`)
*   **`request duration`**: Длительность обработки последнего запроса в микросекундах.
*   **`last request cpu`**: Доля процессорного времени (в процентах), затраченная на выполнение последнего запроса. Рассчитывается только после завершения запроса, поэтому для выполняющегося воркера равна `0`.
*   **`last request memory`**: Объем памяти в байтах, выделенный под последний запрос.
*   **`script`**: Полный путь к выполняемому PHP-скрипту на диске.

### Разграничение мониторинга: PHP-FPM и OPcache

Страница статуса PHP-FPM (`/fpm-status`) собирает исключительно метрики управления процессами и очередями FastCGI. **Метрики OPcache не входят в стандартный вывод `/fpm-status` и не отдаются через нативный OpenMetrics FPM.** 

OPcache является расширением ядра Zend Engine. Для мониторинга эффективности кэша байт-кода (Hit Rate, свободная память, число закэшированных файлов) требуется отдельный скрипт, вызывающий функцию `opcache_get_status()`, либо специализированный агент мониторинга. Попытка настроить поиск метрик OPcache в нативном выводе `/fpm-status` является грубой ошибкой конфигурации.

---

## Практические сценарии

### Сценарий 1: Предварительные требования и системные параметры ОС

Перед развертыванием мониторинга необходимо настроить лимиты ядра Linux, предотвращающие преждевременный отказ очереди сокетов.

**1. Проверка состояния служб и версий:**

```bash
# Проверка версии PHP-FPM
php-fpm8.4 -v
# → PHP 8.4.x (fpm-fcgi) (built: ...)

# Проверка статуса службы
systemctl is-active php8.4-fpm
# → active
```

**2. Настройка системного backlog в ядре Linux (`/etc/sysctl.d/99-php-fpm.conf`):**

По умолчанию значение `net.core.somaxconn` во многих дистрибутивах составляет 128 или 4096. Для серверов с высокой интенсивностью запросов увеличьте системный лимит:

```ini
# /etc/sysctl.d/99-php-fpm.conf
net.core.somaxconn = 65535
```

Применение параметров:

```bash
sudo sysctl -p /etc/sysctl.d/99-php-fpm.conf
# → net.core.somaxconn = 65535
```

---

### Сценарий 2: Настройка статусной страницы в пуле PHP-FPM

Страница статуса настраивается в файле пула (например, `/etc/php/8.4/fpm/pool.d/www.conf`).

> **Безопасность:** Страница статуса раскрывает внутренние системные пути скриптов, аргументы запросов, состояние процессов и имена пользователей HTTP-аутентификации (`PHP_AUTH_USER`). Доступ к ней должен быть строго ограничен локальным хостом или доверенной подсетью мониторинга.

```ini
; /etc/php/8.4/fpm/pool.d/www.conf
[www]
user = www-data
group = www-data

listen = /run/php/php8.4-fpm.sock
listen.owner = www-data
listen.group = www-data
listen.mode = 0660
listen.backlog = 65535

pm = dynamic
pm.max_children = 50
pm.start_servers = 5
pm.min_spare_servers = 5
pm.max_spare_servers = 35
pm.max_spawn_rate = 32

; Включение статусной страницы и проверки доступности (ping)
pm.status_path = /fpm-status
ping.path = /fpm-ping
ping.response = pong

; Трассировка медленных запросов
request_slowlog_timeout = 3s
request_slowlog_trace_depth = 50
slowlog = /var/log/php8.4-fpm.slowlog
```

Проверка конфигурации и перезагрузка:

```bash
sudo php-fpm8.4 -t
# → [15-Oct-2026 09:30:00] NOTICE: configuration file /etc/php/8.4/fpm/php-fpm.conf test is successful

sudo systemctl reload php8.4-fpm
```

---

### Сценарий 3: Проксирование статуса через веб-сервер (Nginx / Angie)

Для сбора метрик по протоколу HTTP необходимо настроить локальный виртуальный хост, проксирующий вызовы к FastCGI-сокету с ограничением прав доступа.

```nginx
# /etc/nginx/conf.d/php_status.conf (или /etc/angie/http.d/php_status.conf)
server {
    listen 127.0.0.1:8080;
    server_name localhost;

    # Отключение логирования служебных запросов мониторинга
    access_log off;

    location ~ ^/(fpm-status|fpm-ping)$ {
        allow 127.0.0.1;
        allow 10.0.0.0/8;
        deny all;

        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $fastcgi_script_name;
        fastcgi_pass unix:/run/php/php8.4-fpm.sock;
    }

    location / {
        return 404;
    }
}
```

Проверка и применение конфигурации веб-сервера:

```bash
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

sudo systemctl reload nginx
```

**Валидация доступа через HTTP:**

```bash
# Проверка ping-эндпоинта
curl -s http://127.0.0.1:8080/fpm-ping
# → pong

# Проверка текстового вывода статуса
curl -s http://127.0.0.1:8080/fpm-status
# → pool:                 www
# → process manager:      dynamic
# → start time:           15/Oct/2026:09:00:00 +0300
# → start since:          1800
# → accepted conn:        12500
# → listen queue:         0
# → max listen queue:     2
# → listen queue len:     65535
# → idle processes:       15
# → active processes:     2
# → total processes:      17
# → max active processes: 28
# → max children reached: 0
# → slow requests:        0

# Проверка вывода в формате JSON
curl -s "http://127.0.0.1:8080/fpm-status?json" | jq .
# → {
# →   "pool": "www",
# →   "process manager": "dynamic",
# →   "start since": 1800,
# →   "accepted conn": 12500,
# →   "listen queue": 0,
# →   "idle processes": 15,
# →   "active processes": 2,
# →   "total processes": 17
# → }
```

---

### Сценарий 4: Нативный сбор метрик в Prometheus (PHP 8.1+ OpenMetrics)

Начиная с версии PHP 8.1, PHP-FPM поддерживает нативный формат OpenMetrics при передаче параметра `?openmetrics`. Это позволяет собирать метрики напрямую через Prometheus без внешних экспортеров.

**Валидация формата OpenMetrics:**

```bash
curl -s "http://127.0.0.1:8080/fpm-status?openmetrics" | head -n 25
# → # HELP phpfpm_up PHP-FPM scrape status
# → # TYPE phpfpm_up gauge
# → phpfpm_up 1
# → # HELP phpfpm_start_since_seconds How long has the PHP-FPM process pool been running
# → # TYPE phpfpm_start_since_seconds gauge
# → phpfpm_start_since_seconds 1800
# → # HELP phpfpm_accepted_connections_total The number of requests accepted by the pool
# → # TYPE phpfpm_accepted_connections_total counter
# → phpfpm_accepted_connections_total 12500
# → # HELP phpfpm_listen_queue The number of requests in the queue of pending connections
# → # TYPE phpfpm_listen_queue gauge
# → phpfpm_listen_queue 0
# → # HELP phpfpm_listen_queue_length The size of the socket queue of pending connections
# → # TYPE phpfpm_listen_queue_length gauge
# → phpfpm_listen_queue_length 65535
# → # HELP phpfpm_idle_processes The number of idle processes
# → # TYPE phpfpm_idle_processes gauge
# → phpfpm_idle_processes 15
# → # HELP phpfpm_active_processes The number of active processes
# → # TYPE phpfpm_active_processes gauge
# → phpfpm_active_processes 2
# → # HELP phpfpm_total_processes The number of idle + active processes
# → # TYPE phpfpm_total_processes gauge
# → phpfpm_total_processes 17
# → # HELP phpfpm_max_children_reached_total The number of times the process limit has been reached
# → # TYPE phpfpm_max_children_reached_total counter
# → phpfpm_max_children_reached_total 0
```

**Конфигурация Prometheus (`/etc/prometheus/prometheus.yml`):**

```yaml
scrape_configs:
  - job_name: 'php-fpm-native'
    metrics_path: '/fpm-status'
    params:
      openmetrics: ['']
    static_configs:
      - targets: ['127.0.0.1:8080']
        labels:
          environment: 'production'
          service: 'php-fpm'
    scrape_interval: 15s
    scrape_timeout: 5s
```

---

### Сценарий 5: Сбор метрик без веб-сервера через `php-fpm_exporter`

Если веб-сервер не установлен на хосте (например, в изолированных окружениях) или требуется опрашивать Unix-сокет FastCGI напрямую, применяется утилита `php-fpm_exporter` (от `hipages`).

Экспортер подключается напрямую к FastCGI-сокету, эмулируя протокол FastCGI, и отдает метрики по HTTP на порту 9253.

**1. Установка бинарного файла:**

```bash
# Загрузка и распаковка релиза php-fpm_exporter
curl -sSL -O https://github.com/hipages/php-fpm_exporter/releases/download/v2.2.0/php-fpm_exporter_2.2.0_linux_amd64.tar.gz
tar -xzf php-fpm_exporter_2.2.0_linux_amd64.tar.gz
sudo mv php-fpm_exporter /usr/local/bin/
sudo chmod +x /usr/local/bin/php-fpm_exporter
```

**2. Создание системного сервиса systemd:**

```ini
# /etc/systemd/system/php-fpm-exporter.service
[Unit]
Description=PHP-FPM Prometheus Exporter
After=network.target php8.4-fpm.service
Wants=php8.4-fpm.service

[Service]
Type=simple
User=www-data
Group=www-data
ExecStart=/usr/local/bin/php-fpm_exporter server \
  --phpfpm.scrape-uri="unix:///run/php/php8.4-fpm.sock;/fpm-status" \
  --web.listen-address="127.0.0.1:9253" \
  --web.telemetry-path="/metrics"
Restart=always
RestartSec=5s
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

**3. Запуск и валидация сервиса:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now php-fpm-exporter
sudo systemctl status php-fpm-exporter --no-pager
# → Active: active (running)

# Проверка вывода метрик
curl -s http://127.0.0.1:9253/metrics | grep -E "php_fpm_up|php_fpm_active_processes"
# → # HELP php_fpm_active_processes number of active processes
# → # TYPE php_fpm_active_processes gauge
# → php_fpm_active_processes{pool="www"} 2
# → # HELP php_fpm_up able to contact php-fpm
# → # TYPE php_fpm_up gauge
# → php_fpm_up{pool="www"} 1
```

---

### Сценарий 6: Продакшен-правила алертинга PromQL

Ниже приведены проверенные правила для Prometheus Alertmanager, ориентированные на выявление реальных сбоев и насыщения ресурсов.

```yaml
# /etc/prometheus/rules/php_fpm_alerts.yml
groups:
  - name: php_fpm_alerts
    rules:
      - alert: PHPFPMDown
        expr: (phpfpm_up == 0) or (php_fpm_up == 0)
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "PHP-FPM пул недоступен"
          description: "PHP-FPM на инстансе {{ $labels.instance }} не отвечает на запросы проверки статуса более 1 минуты."

      - alert: PHPFPMListenQueueGrowing
        expr: (phpfpm_listen_queue > 0) or (php_fpm_listen_queue > 0)
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Очередь соединений PHP-FPM растет"
          description: "На инстансе {{ $labels.instance }} в очереди сокета находится {{ $value }} запросов. Воркеры не справляются с нагрузкой, возможны ошибки 502/504."

      - alert: PHPFPMMaxChildrenReached
        expr: (increase(phpfpm_max_children_reached_total[5m]) > 0) or (increase(php_fpm_max_children_reached[5m]) > 0)
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Достигнут лимит pm.max_children"
          description: "Пул {{ $labels.pool }} на инстансе {{ $labels.instance }} исчерпал лимит процессов {{ $value }} раз за 5 минут. Требуется тюнинг pm.max_children или устранение узких мест в коде."

      - alert: PHPFPMSlowRequestsSpike
        expr: (rate(phpfpm_slow_requests_total[5m]) > 1) or (rate(php_fpm_slow_requests[5m]) > 1)
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Всплеск медленных запросов PHP"
          description: "Частота медленных запросов на инстансе {{ $labels.instance }} превышает 1 за секунду. Проверьте slowlog."

      - alert: PHPFPMPoolSaturationHigh
        expr: |
          (
            phpfpm_active_processes / (phpfpm_total_processes > 0)
          ) > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокая утилизация пула PHP-FPM (>90%)"
          description: "Более 90% воркеров пула {{ $labels.pool }} заняты выполнением запросов более 5 минут непрерывно."
```

---

### Сценарий 7: Анализ slowlog и трассировка узких мест

Slowlog позволяет обнаружить медленные функции без интеграции сторонних APM-агентов.

**1. Просмотр последних записей slowlog:**

```bash
sudo tail -n 30 /var/log/php8.4-fpm.slowlog
```

Пример содержимого записи slowlog:

```
[15-Oct-2026 09:35:12]  [pool www] pid 14522
script_filename = /var/www/html/api/reports.php
[0x00007fa9b2014a20] sleep() /var/www/html/api/reports.php:45
[0x00007fa9b2014940] generate_pdf() /var/www/html/api/reports.php:112
[0x00007fa9b2014860] handle_request() /var/www/html/index.php:28
```

**2. Анализ наиболее часто встречающихся проблемных скриптов через CLI:**

```bash
# Подсчет топ-10 медленных скриптов
grep -oP 'script_filename = \K.*' /var/log/php8.4-fpm.slowlog | sort | uniq -c | sort -nr | head -n 10
# →   142 /var/www/html/api/reports.php
# →    56 /var/www/html/modules/catalog/export.php
# →    12 /var/www/html/auth/ldap.php
```

**3. Настройка ротации логов (`/etc/logrotate.d/php8.4-fpm`):**

Поскольку PHP-FPM держит файловые дескрипторы открытыми, ротация требует отправки сигнала `USR1` мастер-процессу для бесшовного переоткрытия файлов:

```conf
# /etc/logrotate.d/php8.4-fpm
/var/log/php8.4-fpm.log
/var/log/php8.4-fpm.slowlog {
    daily
    rotate 14
    missingok
    notifempty
    compress
    delaycompress
    sharedscripts
    postrotate
        /bin/kill -USR1 $(cat /run/php/php8.4-fpm.pid 2>/dev/null) 2>/dev/null || true
    endscript
}
```

---

### Сценарий 8: Диагностика утечек памяти и профилирование процессов

Если в мониторинге наблюдается постоянный рост используемой памяти хоста (`node_memory_MemAvailable_bytes` падает), необходимо идентифицировать ресурсоемкие воркеры.

**1. Профилирование воркеров FPM с помощью `pidstat`:**

```bash
# Мониторинг RSS памяти и page faults процессов php-fpm с интервалом 3 секунды
pidstat -r -C php-fpm 3 3
# → 09:40:00      UID       PID  minflt/s  majflt/s     VSZ     RSS   %MEM  Command
# → 09:40:03       33     14520     12.00      0.00  345200   78450   0.98  php-fpm
# → 09:40:03       33     14521     45.00      0.00  512400  210540   2.63  php-fpm
```

**2. Поиск воркера с максимальным потреблением памяти через `ps`:**

```bash
ps -o pid,user,%cpu,%mem,vsz,rss,args -C php-fpm8.4 --sort=-rss | head -n 10
# →   PID USER     %CPU %MEM    VSZ   RSS COMMAND
# → 14521 www-data  4.2  2.6 512400 210540 php-fpm: pool www
# → 14520 www-data  1.1  0.9 345200  78450 php-fpm: pool www
```

Если у отдельных процессов значение RSS непрерывно увеличивается без возврата к базовому уровню, в коде или подключенных C-расширениях присутствует утечка памяти.

---

## Операции и команды

Сводная таблица команд для повседневной эксплуатации и мониторинга PHP-FPM:

| Действие | Команда | Назначение / Ожидаемый результат |
| :--- | :--- | :--- |
| **Тест сокета через cgi-fcgi** | `SCRIPT_NAME=/fpm-ping SCRIPT_FILENAME=/fpm-ping REQUEST_METHOD=GET cgi-fcgi -bind -connect /run/php/php8.4-fpm.sock` | Прямая проверка сокета FastCGI без веб-сервера. Вывод: `pong`. |
| **JSON статус через cgi-fcgi** | `SCRIPT_NAME=/fpm-status SCRIPT_FILENAME=/fpm-status QUERY_STRING="json" REQUEST_METHOD=GET cgi-fcgi -bind -connect /run/php/php8.4-fpm.sock` | Получение JSON-статистики пула напрямую из сокета. |
| **OpenMetrics через cgi-fcgi** | `SCRIPT_NAME=/fpm-status SCRIPT_FILENAME=/fpm-status QUERY_STRING="openmetrics" REQUEST_METHOD=GET cgi-fcgi -bind -connect /run/php/php8.4-fpm.sock` | Получение метрик Prometheus напрямую из FastCGI-сокета. |
| **Проверка очереди сокета ядра** | `ss -l -x -p src /run/php/php8.4-fpm.sock` | Просмотр `Send-Q` (размер backlog) и `Recv-Q` (текущая длина очереди подключений). |
| **Синтаксический тест** | `php-fpm8.4 -t` | Проверка синтаксиса всех конфигурационных файлов FPM. |
| **Бесшовная перезагрузка** | `kill -USR2 $(cat /run/php/php8.4-fpm.pid)` или `systemctl reload php8.4-fpm` | Graceful reload: перечитывание конфигов и перезапуск воркеров без разрыва текущих сессий. |
| **Переоткрытие логов** | `kill -USR1 $(cat /run/php/php8.4-fpm.pid)` | Reopen log files после выполнения ротации файлов логов. |
| **Быстрая остановка** | `kill -QUIT $(cat /run/php/php8.4-fpm.pid)` | Graceful shutdown: завершение работы после обработки текущих запросов. |

### Примеры использования CLI-утилит

**1. Проверка состояния Unix-сокета ядра через `ss`:**

```bash
sudo ss -l -x -p src /run/php/php8.4-fpm.sock
# → Netid  State   Recv-Q  Send-Q   Local Address:Port   Peer Address:Port  Process
# → u_str  LISTEN  0       65535    /run/php/php8.4-fpm.sock 0           users:(("php-fpm8.4",pid=1230,fd=7))
```

В выводе `ss` для слушающего сокета:
*   `Send-Q` — максимально допустимый размер очереди соединений (`listen.backlog`).
*   `Recv-Q` — текущее количество подключений, находящихся в очереди ожидания. Если `Recv-Q > 0`, процессы не успевают забирать входящие соединения.

**2. Запрос статуса через утилиту `cgi-fcgi` (пакет `libfcgi-bin`):**

```bash
# Установка утилиты при необходимости: apt-get install -y libfcgi-bin
SCRIPT_NAME=/fpm-status SCRIPT_FILENAME=/fpm-status QUERY_STRING="json" REQUEST_METHOD=GET cgi-fcgi -bind -connect /run/php/php8.4-fpm.sock
# → X-Powered-By: PHP/8.4.x
# → Content-type: application/json
# → 
# → {"pool":"www","process manager":"dynamic","start since":1800,"accepted conn":12500,"listen queue":0,"idle processes":15,"active processes":2,"total processes":17}
```

---

## Диагностика и устранение неисправностей

### Сценарий 1: Пул переполнен (`max children reached` растет)

**Симптомы:**
*   Рост счетчика `max children reached` в метриках.
*   Увеличение времени ответа страниц, веб-сервер периодически возвращает ошибки 502/504.
*   В системном журнале PHP-FPM появляется сообщение:
    `WARNING: [pool www] server reached pm.max_children setting (50), consider raising it`

**Причины:**
1.  Лимит `pm.max_children` занижен относительно входящего трафика.
2.  Воркеры блокируются на долгих внешних операциях (запросы к медленной БД, сторонним HTTP API).
3.  Утечка памяти в PHP-приложении, приводящая к частой смене воркеров.

**Диагностика:**

```bash
# 1. Проверка текущего количества запущенных процессов пула
ps -C php-fpm8.4 --no-headers | wc -l
# → 51 (1 мастер + 50 воркеров)

# 2. Определение среднего объема оперативной памяти одного воркера под нагрузкой
ps -o rss -C php-fpm8.4 --no-headers | tail -n +2 | awk '{sum+=$1; count++} END {print "Avg RSS (MB):", sum/count/1024}'
# → Avg RSS (MB): 64.5

# 3. Расчет максимально допустимого pm.max_children по формуле:
# pm.max_children = (Доступная RAM под PHP-FPM) / (Средний RSS воркера)
# Пример: Для сервера с 4 ГБ выделенной памяти под PHP:
# (4096 МБ * 0.8) / 64.5 МБ ≈ 50
```

**Решение:**
1.  Если оперативная память свободна, увеличьте `pm.max_children` в `/etc/php/8.4/fpm/pool.d/www.conf`.
2.  Включите параметр `pm.max_requests = 1000`, чтобы предотвратить бесконечный рост процессов при утечках памяти.
3.  Ограничьте таймауты сетевых клиентов в PHP-коде (`default_socket_timeout = 5`).

---

### Сценарий 2: Рост очереди соединений (`listen queue > 0`)

**Симптомы:**
*   Метрика `listen queue` держится выше `0`.
*   Nginx возвращает ошибки `502 Bad Gateway`.
*   В `error.log` веб-сервера фиксируются сообщения:
    `connect() to unix:/run/php/php8.4-fpm.sock failed (11: Resource temporarily unavailable) while connecting to upstream`

**Причины:**
1.  Все воркеры заняты (`active processes == pm.max_children`), и новые соединения скапливаются в сокете.
2.  Размер `listen.backlog` меньше всплеска одновременных подключений.

**Диагностика:**

```bash
# Проверка текущей очереди ядра
ss -l -x src /run/php/php8.4-fpm.sock
# → Recv-Q: 145, Send-Q: 511
```

Если `Recv-Q` приближается к значению `Send-Q`, соединения отбрасываются операционной системой.

**Решение:**
1.  Увеличьте параметр `listen.backlog` в конфигурации пула до `65535` (или значения, согласованного с `net.core.somaxconn`).
2.  Увеличьте значение `net.core.somaxconn` в `/etc/sysctl.conf`.
3.  Устраните блокировки воркеров или масштабируйте пул на дополнительные серверы.

---

### Сценарий 3: Зависание воркеров и медленные запросы

**Симптомы:**
*   Метрика `slow requests` непрерывно растет.
*   Метрика `active processes` приближается к максимуму, но процессор хоста простаивает (высокий I/O wait или блокировки на сокетах).

**Диагностика:**

```bash
# 1. Проверка активных slow-запросов
tail -n 40 /var/log/php8.4-fpm.slowlog

# 2. Проверка зависших запросов через статус-страницу в full-режиме
curl -s "http://127.0.0.1:8080/fpm-status?full" | grep -B2 -A7 "state: Running"
# → pid:                  14525
# → state:                Running
# → request duration:     45210000 (45 секунд!)
# → request method:       POST
# → request uri:          /api/checkout
# → script:               /var/www/html/api/checkout.php
```

**Решение:**
1.  Настройте аварийный таймаут принудительного завершения зависших скриптов в конфигурации пула:
    ```ini
    request_terminate_timeout = 30s
    ```
2.  Установите лимит времени исполнения на уровне PHP-интерпретатора:
    ```ini
    php_admin_value[max_execution_time] = 30
    ```
3.  Оптимизируйте внешние блокирующие запросы (SQL-запросы, обращения к внешним API) с установкой жестких таймаутов на сокетах (`curl_setopt($ch, CURLOPT_TIMEOUT, 5)`).

---

### Сценарий 4: Аварийные перезапуски воркеров (SIGSEGV / OOM Killer)

**Симптомы:**
*   Метрика `start since` у процессов сбрасывается или скачкообразно меняются PID.
*   В логе веб-сервера: `recv() failed (104: Connection reset by peer) while reading response header from upstream`.

**Диагностика:**

```bash
# 1. Проверка сообщений OOM Killer в ядре Linux
sudo dmesg -T | grep -E -i "killed process|oom_reaper|php-fpm"
# → [Thu Oct 15 09:42:01 2026] Out of memory: Killed process 14521 (php-fpm8.4) total-vm:1048576kB, anon-rss:524288kB

# 2. Проверка падений воркеров по сигналам Segmentation Fault
sudo journalctl -u php8.4-fpm -n 50 --no-pager | grep -E "SIGSEGV|SIGBUS|child.*exited"
# → WARNING: [pool www] child 14522 exited on signal 11 (SIGSEGV) after 120.456789 seconds from start
```

**Решение:**
1.  **При OOM Killer:** 
    *   Уменьшите `pm.max_children`, ограничив общее потребление памяти.
    *   Настройте директиву `php_admin_value[memory_limit] = 256M` для отдельного запроса.
    *   Задайте жесткие ограничения в systemd unit через `MemoryMax=...`.
2.  **При SIGSEGV (сигнал 11):**
    *   Проверьте стек вызова через `coredumpctl`:
        ```bash
        coredumpctl list php-fpm8.4
        coredumpctl debug <PID>
        ```
    *   Проблема часто связана с битыми C-библиотеками или несовместимыми версиями расширений (imagick, xdebug, ffi, opcache). Отключите подозрительные модули в `/etc/php/8.4/mods-available/`.

---

### Сценарий 5: Статусная страница недоступна (502 / Permission Denied)

**Симптомы:**
*   При вызове `curl http://127.0.0.1:8080/fpm-status` возвращается `502 Bad Gateway` или `404 Not Found`.

**Диагностика:**

```bash
# 1. Проверка существования и прав сокета
ls -la /run/php/php8.4-fpm.sock
# → srw-rw---- 1 www-data www-data 0 Oct 15 09:00 /run/php/php8.4-fpm.sock

# 2. Проверка пользователя рабочего процесса веб-сервера
ps -o user,comm -C nginx
# → USER     COMMAND
# → root     nginx
# → www-data nginx
```

Если права сокета не позволяют процессу веб-сервера (`www-data`) читать и писать в сокет, возвращается `502 Bad Gateway` с записью `Permission denied`.

**Решение:**
1.  Убедитесь, что в конфигурации пула заданы параметры сокета:
    ```ini
    listen.owner = www-data
    listen.group = www-data
    listen.mode = 0660
    ```
2.  Убедитесь, что в блоке `location` веб-сервера передается правильный путь:
    ```nginx
    fastcgi_param SCRIPT_FILENAME $fastcgi_script_name;
    ```
    Если передать `$document_root$fastcgi_script_name`, а директории `/fpm-status` физически не существует на диске, PHP-FPM вернет `File not found` или `Primary script unknown`.

---

## Рекомендации и передовые практики

### Методология расчета емкости пула (SRE-подход)

Конфигурация параметров менеджера процессов должна рассчитываться математически на основе замеров реального потребления памяти, а не эмпирических догадок.

```
Доступная RAM = Всего RAM на сервере - RAM ядра и ОС - RAM буферов и кэшей БД
pm.max_children = floor(Доступная RAM / Средний RSS одного воркера под нагрузкой)
```

**Рекомендуемые пропорции для `pm = dynamic`:**
*   `pm.max_children`: расчетное значение по формуле емкости.
*   `pm.start_servers`: 20–25% от `pm.max_children`.
*   `pm.min_spare_servers`: 10–15% от `pm.max_children` (гарантирует немедленный ответ при поступлении запроса).
*   `pm.max_spare_servers`: 25–35% от `pm.max_children`.
*   `pm.max_requests`: от 500 до 2000 (перезапуск процесса после обработки N запросов сбрасывает фрагментированную память и минимизирует скрытые утечки).

### Изоляция ресурсов через systemd

Для предотвращения деградации операционной системы при сбоях в PHP-приложении используйте механизмы cgroups v2 через systemd override:

```bash
sudo systemctl edit php8.4-fpm
```

Внесите параметры ограничений:

```ini
# /etc/systemd/system/php8.4-fpm.service.d/override.conf
[Service]
# Жесткий лимит памяти на службу (OOM на уровне cgroup)
MemoryMax=3.5G
MemoryHigh=3.0G

# Ограничение CPU (300% = эквивалент 3 полных ядер)
CPUQuota=300%

# Ограничение числа системных процессов (защита от fork-бомб)
TasksMax=120

# Лимит файловых дескрипторов
LimitNOFILE=65535

# Перезапуск службы при аварийном падении
Restart=always
RestartSec=3s
```

Примените изменения:

```bash
sudo systemctl daemon-reload
sudo systemctl restart php8.4-fpm
```

---

## Границы применимости и эксплуатационные ограничения

### Ограничения встроенной страницы статуса

1.  **Отсутствие исторических данных:** Страница `/fpm-status` возвращает мгновенный срез (snapshot) текущего состояния. Для трендового анализа, расчета перцентилей и построения графиков необходимо сохранять метрики в Prometheus.
2.  **Накладные расходы режима `?full`:** Запрос полной детализации (`/fpm-status?full`) заставляет FPM последовательно сканировать все слоты Scoreboard, собирая информацию о строках URI и путях к файлам. В пулах с `pm.max_children > 200` частый опрос в режиме `full` создает паразитные блокировки и повышенную нагрузку на CPU. Рекомендуется опрашивать краткий статус (`/fpm-status`) с интервалом 15 секунд, а `?full` запрашивать вручную только в процессе расследования инцидентов.
3.  **Многопуловые конфигурации (Multi-pool):** Каждый пул FPM изолирован и имеет собственный путь статуса (`pm.status_path`). Для серверов с несколькими пулами необходимо настраивать опрос каждого эндпоинта отдельно (например, `/fpm-status-www`, `/fpm-status-api`).
4.  **Unix Domain Socket vs TCP Socket:**
    *   *Unix Domain Socket (`unix:/run/php/php8.4-fpm.sock`)*: обеспечивает максимальную пропускную способность, минимальные задержки (отсутствие накладных расходов сетевого стека) и безопасный контроль доступа через права файловой системы Linux.
    *   *TCP Socket (`127.0.0.1:9000`)*: создает дополнительный оверхед на loopback-интерфейс ядра, расходует локальные порты (риск исчерпания ephemeral ports при high load), но позволяет размещать веб-сервер и PHP-FPM на разных хостах.

---

## Дополнительная информация

### См. также

*   **[Тюнинг и эксплуатация PHP-FPM](./php-fpm-tuning.md)** — расчет параметров менеджеров процессов, тонкая настройка конфигураций пула.
*   **[FastCGI и PHP-FPM в Angie](../Angie/angie-fastcgi-php-fpm.md)** — архитектура взаимодействия веб-сервера с FastCGI и сценарии балансировки.
*   **[Оптимизация производительности Nginx](../Nginx/Performance/nginx_performance_tuning.md)** — настройка буферов, соединений и параметров ядра для высоконагруженных прокси.
*   **[Мониторинг кэширования в Nginx и Angie](../Nginx/Performance/Caching/monitoring.md)** — сбор метрик эффективности FastCGI кэша (`X-Cache-Status`).
*   **[Методологии мониторинга (USE/RED/Four Golden Signals)](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)** — теоретические основы построения наблюдаемости распределенных систем.
*   **[Утилита `pidstat`](../../Linux/Diagnostics/Processes/pidstat.md)** — детальный анализ процессорных ресурсов и памяти на уровне конкретных PID.
*   **[Диагностика веб-серверов (Troubleshooting)](../Concepts/webserver_troubleshooting.md)** — систематический поиск причин ошибок 502, 504 и таймаутов FastCGI.
