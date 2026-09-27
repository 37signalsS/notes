# Мониторинг PHP-FPM

## Определения

**PHP-FPM (FastCGI Process Manager)** — альтернативная реализация PHP FastCGI с дополнительными функциями, предназначенная для высоконагруженных сайтов. Мониторинг PHP-FPM критичен для обеспечения стабильности веб-приложений, так как этот компонент является связующим звеном между веб-сервером (Nginx/Angie) и кодом приложения. PHP-FPM управляет пулом процессов-воркеров, каждый из которых является отдельным PHP-интерпретатором, способным обрабатывать один запрос за раз (или несколько в режиме multi-thread). В отличие от классического mod_php, FPM работает в отдельном процессе, что обеспечивает изоляцию, возможность перезапуска пула без остановки веб-сервера и детерминированное управление ресурсами.

**PHP-FPM Status Page** — встроенный механизм самодиагностики, предоставляющий информацию о текущем состоянии пулов процессов, очередях и детальную статистику по каждому воркеру. Статусная страница является стандартизированным интерфейсом, эндпоинт которого настраивается параметром `pm.status_path` в конфигурации пула. Получение статистики возможно в форматах: человекочитаемом (text/html), JSON, XML и начиная с PHP 8.1 — OpenMetrics.

**OpenMetrics (PHP 8.1+)** — стандарт формата метрик, поддерживаемый PHP-FPM нативно начиная с версии 8.1, что позволяет интегрировать его с Prometheus/Grafana без использования сторонних экспортеров. Формат OpenMetrics является открытым стандартом, разработанным как преемник Prometheus exposition format, и обеспечивает совместимость со множеством систем сбора метрик.

**PromQL (Prometheus Query Language)** — декларативный язык запросов для извлечения и манипуляции временными рядами в Prometheus. Используется для определения правил алертинга, выражений в дашбордах Grafana и логирования (LogQL в Loki). Понимание PromQL необходимо для создания эффективных алертов на основе метрик PHP-FPM.

**pm.max_spawn_rate (PHP 8.1+)** — параметр динамического менеджера процессов, определяющий максимальную скорость создания новых воркеров при всплесках трафика. Значение по умолчанию — 32 (ранее жестко закодировано). Позволяет быстрее адаптироваться к росту нагрузки без превышения лимитов создания процессов.

---

## Предварительные требования

### Программное обеспечение и версии

| Компонент | Минимальная версия | Рекомендуемая версия | Назначение |
| :--- | :--- | :--- | :--- |
| PHP-FPM | 7.4 | 8.3–8.4 | Обработка PHP-запросов |
| Nginx/Angie | 1.18 | 1.24+ / 1.5+ | Проксирование FastCGI |
| Prometheus | 2.20 | 2.45+ | Сбор и хранение метрик |
| php-fpm-exporter | — | 2.2+ (hipages) / 1.0+ (jensschulze) | Экспорт метрик для PHP < 8.1 |
| prometheus-phpfpm-exporter | — | 0.6.0+ | Пакетный экспортер (Debian/Ubuntu) |
| sysstat | — | 12+ | Утилита pidstat для диагностики |

### Инициализация окружения

Перед настройкой мониторинга убедитесь, что PHP-FPM корректно установлен и запущен:

```bash
# Проверка установки пакетов (Debian/Ubuntu)
dpkg -l | grep -E 'php-fpm|php8\.[34]-fpm'

# Проверка статуса службы
systemctl status php8.4-fpm --no-pager

# Ожидаемый вывод:
# ● php8.4-fpm.service - The PHP 8.4 FastCGI Process Manager
#      Loaded: loaded (/lib/systemd/system/php8.4-fpm.service; enabled)
#      Active: active (running) since ...
```

### Требования к ресурсам (базовые ориентиры)

| Метрика | Минимум | Рекомендация | Примечание |
| :--- | :--- | :--- | :--- |
| RAM на пул | 512 MiB | `pm.max_children × (32 MiB + средний RSS одного воркера)` | |
| Дескрипторы | 65535 | Настраивается через `worker_rlimit_nofile` (Nginx) и `rlimit_files` (PHP-FPM) | |
| inotify watchers | 8192 | При использовании OPcache и большого числа файлов | |

---

## Основные концепции

### Эшелонированный мониторинг

Эффективный мониторинг PHP-FPM строится на трех уровнях, каждый из которых закрывает определенный класс инцидентов:

1.  **Инфраструктурный (Blackbox):** Проверка доступности порта/сокета и времени ответа FastCGI. Реализуется внешними проверками из системы мониторинга (например, Blackbox Exporter) или скриптами, инициирующими тестовый запрос через FastCGI. Цель — выявить полный отказ или деградацию доступности без доступа к внутренней конфигурации приложения.
2.  **Внутренний (Whitebox):** Анализ страницы статуса (метрики пулов и воркеров). Предоставляет детальную информацию о состоянии воркеров, очередях и OPcache. Требует доступности эндпоинта статуса из системы мониторинга.
3.  **Системный (Sidecar/Node):** Мониторинг потребления CPU/RAM конкретными процессами `php-fpm` через системные утилиты (`pidstat`, `ps`, `top`) и экспортеры node_exporter. Нужен для корреляции проблем приложения с системными ресурсами и выявления узких мест на уровне ОС.

### Жизненный цикл запроса в PHP-FPM

Для корректной интерпретации метрик необходимо понимать путь запроса:

```
Клиент → Nginx (80/443) → FastCGI → PHP-FPM master process → воркер (idle → executing → idle)
                                                     ↓
                                                slowlog (при превышении лимита)
```

Мастер-процесс PHP-FPM слушает сокет (Unix или TCP), принимает соединения от веб-сервера и распределяет их между свободными воркерами. При использовании режима `pm = dynamic` мастер автоматически управляет числом воркеров в диапазоне `pm.min_spare_servers` – `pm.max_children`, создавая новые процессы при росте нагрузки и завершая избыточные в простое. Начиная с PHP 8.1, параметр `pm.max_spawn_rate` позволяет регулировать скорость создания новых воркеров, предотвращая thundering herd при резком всплеске трафика.

### Модели управления процессами (Process Management)

PHP-FPM поддерживает три модели, каждая из которых влияет на профиль мониторинга:

| Модель | `pm` | Поведение | Мониторинг |
| :--- | :--- | :--- | :--- |
| **Static** | `static` | Запускается ровно `pm.max_children` процессов. Простое предсказуемое потребление RAM. | Фокус на `active processes` и `slow requests`; `idle processes` всегда = 0. |
| **Dynamic** | `dynamic` | Мастер адаптирует число процессов: `pm.start_servers` при старте, поддерживает `pm.min_spare_servers` и `pm.max_spare_servers`. Начиная с PHP 8.1 — `pm.max_spawn_rate` регулирует скорость создания. | Важна метрика `idle processes` — её отсутствие при росте трафика сигнализирует о приближении к лимиту. |
| **Ondemand** | `ondemand` | Процессы создаются по требованию и завершаются после `pm.process_idle_timeout` секунд простоя. | Рост латентности при "холодном старте"; мониторинг `start since` для частых перезапусков. |

### Золотые сигналы SRE для PHP-FPM

*   **Latency:** Время обработки запроса (отслеживается через `slowlog` и метрики веб-сервера). Напрямую зависит от числа активных воркеров, OPcache hit rate и сложности PHP-кода.
*   **Traffic:** Количество принятых соединений (`accepted conn`). Позволяет строить baseline трафика и детектировать аномалии (резкое падение может означать проблемы с upstream; рост при постоянной латентности — увеличение нагрузки).
*   **Errors:** Ошибки конфигурации, таймауты и сегфолты (логи ошибок). Включают `child exit on signal 11 (SIGSEGV)` (некорректные расширения PHP), `NOTICE: message queue terminated` и ошибки инициализации пула.
*   **Saturation:** Длина очереди (`listen queue`) и достижение лимита воркеров (`max children reached`). Ключевые метрики для предотвращения каскадных отказов: рост очереди означает, что запросы ожидают освобождения воркера, и при продолжении роста Nginx вернет 502/504.

---

## Ключевые метрики

### 1. Насыщение и очереди (КРИТИЧЕСКОЕ)

Эти метрики определяют способность PHP-FPM обслуживать входящий трафик без потерь.

*   **`listen queue`**: Количество запросов, ожидающих в очереди на уровне сокета. Если > 0, приложение не справляется с нагрузкой. Параметр `listen.backlog` в конфигурации пула задает максимальный размер очереди ядра (по умолчанию 511 в Linux). При заполнении этой очереди новые соединения будут отклоняться, что приведет к ошибкам 502/504 на стороне Nginx.
*   **`max children reached`**: Счетчик того, сколько раз пул достигал лимита `pm.max_children`. Если значение растет, это прямой сигнал к увеличению лимита или оптимизации кода. Каждое превышение означает, что в момент пиковой нагрузки все воркеры были заняты и новый запрос был принудительно отложен в очередь.
*   **`listen queue len`**: Максимально допустимый размер очереди (backlog). При достижении этого лимита Nginx вернет `502 Bad Gateway` с ошибкой `connect() failed (111: Connection refused) while connecting to upstream`. Рекомендуется отслеживать отклонённые соединения в логах Nginx: `log_format upstream_time '$remote_addr - [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent" $request_time $upstream_response_time';`

### 2. Состояние пула воркеров

*   **`active processes`**: Воркеры, выполняющие код в данный момент. Приближение к `max_children` вызывает рост Latency и заполнение очереди. Важно отслеживать не абсолютное значение, а динамику: резкий рост активных процессов при стабильном трафике означает, что запросы стали "тяжелее" (медленные SQL, внешние API).
*   **`idle processes`**: Воркеры в ожидании. Слишком большое число при `pm = dynamic` может указывать на избыточное потребление RAM в простое. При `pm = static` эта метрика всегда равна 0.
*   **`start since`**: Время работы мастера (в секундах). Частые перезапуски (значение сбрасывается) могут свидетельствовать о нестабильности (падениях процесса, OOM Killer, изменениях конфигурации). Для диагностики смотрите логи: `journalctl -u php8.4-fpm --since "1 hour ago"`.

### 3. Производительность и OPcache

*   **`slow requests`**: Количество запросов, превысивших `request_slowlog_timeout`. Рост метрики требует немедленного анализа `slowlog`. Slowlog содержит стек вызовов (backtrace) для каждого запроса, превысившего лимит, что позволяет быстро идентифицировать проблемный код без необходимости дебага в production.
*   **OPcache Hit Rate**: Процент попаданий в кэш скомпилированного байт-кода. Значение ниже 98% указывает на неэффективное использование памяти или слишком частую инвалидацию кэша. Низкий hit rate увеличивает нагрузку на CPU, так как PHP вынужден повторно компилировать скрипты на каждый запрос.
*   **OPcache Memory Usage**: Заполнение памяти для байт-кода. При 100% заполнении PHP перестает кэшировать новые файлы, что резко снижает производительность. Оптимальное значение — использование не более 80% выделенной памяти, чтобы оставить запас для динамических изменений кодовой базы.

### 4. Детальные метрики воркеров (Full Status)

При использовании `?full` доступны данные по каждому процессу:

*   **`last request memory`**: Потребление памяти последним запросом. Позволяет выявить «утечки» или тяжелые скрипты. Анализ тренда этого показателя по времени помогает обнаружить процессы, чье потребление RAM растет с каждым запросом (утечки в PHP-коде или расширениях).
*   **`last request cpu`**: Затраты процессорного времени. Позволяет идентифицировать "горячие" скрипты и оптимизировать алгоритмы.
*   **`request uri`**: Путь скрипта, вызвавшего нагрузку. Поле может быть пустым, если запрос завершился до записи метрики (например, при фатальной ошибке или превышении memory_limit).
*   **`script`**: Имя выполняемого скрипта (относительно `doc_root`). Используется для детализации в `full` режиме.

### 5. Метрики системного уровня

Помимо встроенной страницы статуса, критически важны метрики ОС, доступные через node_exporter:

*   **`node_memory_MemAvailable_bytes`**: Доступная память. Коррелирует с `idle processes` и `active processes`: рост процессов при стабильном трафике и падении доступной памяти указывает на утечки.
*   **`node_cpu_seconds_total`**: Загрузка CPU. Высокое значение `%system` при большом числе `active processes` может указывать на неоптимальный код или проблемы с OPcache.
*   **`node_filesystem_*`**: Использование диска. PHP-FPM пишет логи (error_log, slowlog) и может использовать временные файлы. Недостаток места приведет к невозможности записи логов.

---

## Практические сценарии

### Настройка безопасной страницы статуса

В 2026 году, после обнаружения **CVE-2026-6735**, критически важно ограничить доступ к странице статуса. Уязвимость (XSS через неправильную санитацию URL) позволяла удаленному злоумышленнику получить доступ к внутренним метрикам и потенциально раскрыть конфиденциальную информацию через межсайтовый скриптинг при просмотре статусной страницы аутентифицированным пользователем.

**1. В конфигурации пула (`www.conf` или отдельный pool-файл):**

```ini
[www]
user = www-data
group = www-data
listen = /run/php/php8.4-fpm.sock
listen.owner = www-data
listen.group = www-data
listen.mode = 0660

pm = dynamic
pm.max_children = 50
pm.start_servers = 5
pm.min_spare_servers = 5
pm.max_spare_servers = 35
pm.max_spawn_rate = 32

pm.status_path = /fpm-status
ping.path = /fpm-ping
ping.response = pong

request_slowlog_timeout = 5s
slowlog = /var/log/php8.4-fpm.slowlog

; Ограничение доступа: IP списком (в дополнение к веб-серверу)
; listen.allowed_clients = 127.0.0.1, 10.0.0.0/8
```

**2. В конфигурации Nginx/Angie:**

```nginx
# Ограничение доступа по IP с отключением логирования
# для снижения нагрузки на диск и избежания утечки информации
location ~ ^/(fpm-status|fpm-ping)$ {
    access_log off;
    allow 127.0.0.1;
    allow 10.0.0.0/8;
    deny all;

    include fastcgi_params;
    fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    fastcgi_pass unix:/run/php/php8.4-fpm.sock;
}
```

**Валидация:**

```bash
# Проверка доступности только с разрешенного IP (localhost)
curl -s -o /dev/null -w "%{http_code}" http://localhost/fpm-status
# → 200

# Проверка блокировки с внешнего IP (должен вернуть 403)
curl -s -o /dev/null -w "%{http_code}" http://server-ip/fpm-status
# → 403
```

### Использование нативных метрик PHP 8.1+ (OpenMetrics)

Начиная с PHP 8.1, Prometheus может собирать данные напрямую без экспортера. Формат OpenMetrics добавляет метрики с типом `TYPE` и `HELP`, а также поддерживает текстовые экспозиции.

**Проверка формата OpenMetrics через curl:**

```bash
curl -s "http://localhost/fpm-status?openmetrics" | head -n 30
# → # HELP phpfpm_up PHP-FPM scrape status
# → # TYPE phpfpm_up gauge
# → phpfpm_up 1
# → # HELP phpfpm_listen_queue PHP-FPM listen queue length
# → # TYPE phpfpm_listen_queue gauge
# → phpfpm_listen_queue 0
```

**Получение детальной статистики по воркерам:**

```bash
curl -s "http://localhost/fpm-status?openmetrics&full" | grep -E "phpfpm_process|phpfpm_request"
# → # HELP phpfpm_process_last_request_memory_bytes Last request memory
# → # TYPE phpfpm_process_last_request_memory_bytes gauge
# → phpfpm_process_last_request_memory_bytes{pid="1234"} 524288
```

### Интеграция с Prometheus через экспортер

Для версий PHP < 8.1 используется `php-fpm-exporter`. Рекомендуется `hipages/php-fpm_exporter` (версия 2.2+, актуальная на 2022 год) или `jensschulze/php-fpm_exporter` (версия 1.0+, октябрь 2025). Экспортер опрашивает страницу статуса и преобразует данные в формат Prometheus.

**Пример запуска в Docker:**

```bash
docker run -d \
  --name phpfpm-exporter \
  -e PHP_FPM_SCRAPE_URI="unix:///run/php/php-fpm.sock;/fpm-status" \
  -p 9253:9253 \
  hipages/php-fpm_exporter:2.2
```

**Валидация работы экспортера:**

```bash
# Проверка endpoint метрик
curl -s http://localhost:9253/metrics | grep -E "phpfpm_up|phpfpm_listen_queue"
# → phpfpm_up 1
# → phpfpm_listen_queue 0
```

### Настройка systemd-сервиса для экспортера

В production-среде экспортер должен работать как systemd-сервис для гарантии автозапуска и перезапуска при сбое:

```ini
# /etc/systemd/system/php-fpm-exporter.service
[Unit]
Description=PHP-FPM Prometheus Exporter
After=network.target php8.4-fpm.service
Wants=php8.4-fpm.service

[Service]
Type=simple
User=prometheus
Group=prometheus
ExecStart=/usr/local/bin/php-fpm_exporter \
  --php-fpm-scrape-uri="unix:///run/php/php8.4-fpm.sock;/fpm-status"
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```bash
# Активация и проверка
sudo systemctl daemon-reload
sudo systemctl enable --now php-fpm-exporter
sudo systemctl status php-fpm-exporter --no-pager
# → Active: active (running)
```

### Конфигурация Prometheus (scrape config)

```yaml
# /etc/prometheus/prometheus.yml
scrape_configs:
  - job_name: 'php-fpm'
    static_configs:
      - targets: ['localhost:9253']
    scrape_interval: 15s
    scrape_timeout: 10s
```

### Ключевые алерты (PromQL)

#### 1. Пул переполнен (Critical)

```promql
phpfpm_max_children_reached_total > 0
```

**Дополнительное условие для снижения шума:**

```promql
increase(phpfpm_max_children_reached_total[5m]) > 0
```

Алерт срабатывает, если пул достигал лимита более 0 раз за 5 минут. Требует немедленного вмешательства — либо увеличение `pm.max_children`, либо оптимизация кода.

#### 2. Рост очереди запросов (Critical)

```promql
phpfpm_listen_queue > 0
```

Очередь > 0 означает, что запросы ожидают освобождения воркера. Если очередь растет или не опускается до 0 в течение нескольких минут, приложение не справляется с нагрузкой.

#### 3. Низкий Hit Rate OPcache (Warning)

```promql
(phpfpm_opcache_hits / (phpfpm_opcache_hits + phpfpm_opcache_misses)) < 0.98
```

Порог 98% является общепринятой рекомендацией. Для high-load систем допускается снижение до 95%, но при этом требуется обязательный анализ причин инвалидации кэша.

#### 4. Высокий `request_slowlog_timeout` (Warning)

```promql
increase(phpfpm_slow_requests_total[5m]) > 10
```

Количество slow-запросов больше 10 за 5 минут требует анализа slowlog.

#### 5. Отсутствие экспорта метрик (Critical)

```promql
up{job="php-fpm"} == 0
```

Отсутствие метрик от экспортера в течение 2 минут означает, что либо PHP-FPM упал, либо экспортер не может достучаться до статусной страницы.

### Диагностика утечек памяти (System Level)

Если мониторинг показывает рост `total processes` и RAM, используйте `pidstat` для поиска конкретного воркера:

```bash
# Мониторинг RSS памяти PHP-FPM воркеров каждые 5 секунд
pidstat -r -C php-fpm 5

# Ожидаемый вывод:
# 12:36:48     UID       RSS     VSZ    %MEM  Command
# 12:36:48    33    524288  4563216   2.15  php-fpm: pool www
# 12:36:53    33    524288  4563216   2.15  php-fpm: pool www
```

Для идентификации конкретного процесса по PID с анализом открытых файлов:

```bash
# Поиск PID с максимальным потреблением RSS
pgrep -a php-fpm | while read pid cmd; do
  rss=$(ps -p $pid -o rss=)
  echo "$rss $pid $cmd"
done | sort -nr | head -n 5
```

### Анализ Slowlog

Для анализа slowlog используйте `awk` для группировки по скрипту и `sort` для выявления самых частых проблем:

```bash
# Подсчет частоты slow-запросов по скрипту (последние 100 строк)
tail -n 100 /var/log/php8.4-fpm.slowlog | \
  grep -oP 'script_name = \K.*' | \
  sort | uniq -c | sort -nr | head -n 10

# Ожидаемый вывод:
#     45 /var/www/html/api/users.php
#     12 /var/www/html/admin/reports.php
#      3 /var/www/html/cron/export.php
```

Для включения extended debug-информации в slowlog добавьте в `php.ini`:

```ini
slowlog = /var/log/php8.4-fpm.slowlog
request_slowlog_timeout = 5s
request_slowlog_trace_depth = 100
```

### Интеграция с Grafana

Для визуализации метрик PHP-FPM в Grafana рекомендуется использовать готовые дашборды:

*   **Kubernetes PHP-FPM** (ID: 4912) — дашборд для hipages php-fpm_exporter, подходит для базового мониторинга single/multi-pool.
*   **PHP FPM** (ID: 25149) — универсальный дашборд, совместимый с разными экспортерами.
*   **PHP Overview** (ID: 10169) — комплексный дашборд, включающий OPcache, PHP-FPM и метрики хоста.

При использовании нативных OpenMetrics метрик (PHP 8.1+) импортируйте дашборд, совместимый с OpenMetrics, или создайте панели на основе метрик `phpfpm_*`.

---

## Диагностика и устранение неисправностей

### Сценарий 1: Пул переполнен (`max children reached` растет)

**Причины:**
*   Недостаточное значение `pm.max_children` для текущей нагрузки.
*   Утечка памяти в PHP-коде: воркер потребляет все доступную RAM и завершается, освобождая место для нового процесса.
*   Блокирующие операции в коде (синхронные запросы к внешним API, долгие SQL-запросы без оптимизации).

**Диагностика:**
```bash
# 1. Проверка текущего значения max_children
grep 'pm.max_children' /etc/php/8.4/fpm/pool.d/*.conf
# → pm.max_children = 50

# 2. Проверка потребления RAM всеми процессами php-fpm
ps aux | grep php-fpm | awk '{sum+=$6} END {print "Total RSS (MB):", sum/1024}'
# → Total RSS (MB): 2456.5

# 3. Расчет доступного значения max_children (предполагая 4GB RAM на PHP-FPM)
# Максимум = (Доступная RAM × 0.8) / Средний RSS одного воркера
# Пример: (4096 × 0.8) / 52 = ~63 (при среднем RSS 52MB)
```

**Решение:**
1.  Увеличьте `pm.max_children` в конфигурации пула (с учетом доступной RAM).
2.  Настройте OPcache для снижения нагрузки на CPU.
3.  Проанализируйте slowlog для выявления долгих запросов.
4.  Внедрите кэширование (Redis/Memcached) для повторяющихся запросов к БД.

### Сценарий 2: Рост очереди (`listen queue` > 0)

**Причины:**
*   Внезапный всплеск трафика (DDOS, популярность поста, рассылка).
*   Один или несколько воркеров "зависли" на долгой операции.
*   Проблемы с базой данных: дедлоки, долгие запросы, исчерпание пула соединений.

**Диагностика:**
```bash
# 1. Проверка текущей очереди через статусную страницу
curl -s "http://localhost/fpm-status?json" | jq '.listen queue'
# → 12

# 2. Проверка состояния воркеров
curl -s "http://localhost/fpm-status?json" | jq '{
  active: ."active processes",
  idle: ."idle processes",
  total: ."active processes" + ."idle processes",
  max: ."max children reached"
}'
# → {"active": 50, "idle": 0, "total": 50, "max": 142}

# 3. Проверка медленных запросов
curl -s "http://localhost/fpm-status?json" | jq '."slow requests"'
# → 8
```

**Решение:**
1.  Краткосрочно: увеличение `pm.max_children` + добавление инстансов за балансировщиком.
2.  Долгосрочно: оптимизация кода, добавление кэширования, настройка пулов соединений БД.

### Сценарий 3: Низкий OPcache Hit Rate (< 98%)

**Причины:**
*   `opcache.memory_consumption` слишком мал для кодовой базы.
*   Частые деплои (инвалидация всего кэша при каждом деплое).
*   Использование слишком агрессивного `opcache.revalidate_freq` или `opcache.validate_timestamps=1` в production.
*   Динамические конфигурации (переопределение путей через `ini_set`) вызывают fragmentation кэша.

**Диагностика:**
```bash
# Проверка конфигурации OPcache
php -r 'echo "Memory used: " . round(php_ini_get_bytes("opcache.memory_consumption") * (opcache_get_status()["memory_usage"]["used_memory"] / opcache_get_status()["memory_usage"]["oom_restarts"]), 2) . " bytes\n";'
# Или через status page:
curl -s "http://localhost/fpm-status?openmetrics" | grep -E "phpfpm_opcache"
# → phpfpm_opcache_memory_usage_bytes 67108864
# → phpfpm_opcache_hits_total 15234523
# → phpfpm_opcache_misses_total 12456
```

**Решение:**
1.  Увеличьте `opcache.memory_consumption` до 128–256M (для средних приложений).
2.  Установите `opcache.validate_timestamps=0` в production и перезагружайте кэш через `opcache_reset()` после деплоя.
3.  Используйте `opcache.interned_strings_buffer=16` для снижения фрагментации.

### Сценарий 4: Частые перезапуски процесса (`start since` сбрасывается)

**Причины:**
*   OOM Killer завершает мастер-процесс или отдельные воркеры.
*   Необработанные фатальные ошибки в PHP-коде (Segmentation fault в расширениях).
*   Настройки `pm.max_requests` (каждый воркер завершается после N запросов).
*   Изменение конфигурации (reload).

**Диагностика:**
```bash
# 1. Проверка событий OOM Killer
sudo dmesg -T | grep -i "killed process" | tail -n 10
# → [Thu Sep 18 14:32:01 2026] Killed process 12345 (php-fpm: pool www) total-vm:524288kB

# 2. Проверка логов PHP-FPM на наличие падений
sudo journalctl -u php8.4-fpm --since "1 hour ago" | grep -E "segfault|signal|NOTICE"
# → NOTICE: ready to handle connections
# → NOTICE: systemd monitor interval set to 10000ms

# 3. Проверка значения pm.max_requests
grep 'pm.max_requests' /etc/php/8.4/fpm/pool.d/*.conf
# → pm.max_requests = 500
```

**Решение:**
1.  При OOM: увеличьте swap или RAM, снизьте `pm.max_children`.
2.  При SIGSEGV: обновите проблемное расширение PHP, проверьте `error_log` на предмет segmentation fault с указанием библиотеки.
3.  При `pm.max_requests`: увеличьте значение или отключите (`0`), если утечек памяти в коде нет.

### Сценарий 5: Статусная страница недоступна (502/504 от Nginx)

**Причины:**
*   Сокет не существует или имеет неправильные права.
*   PHP-FPM не запущен.
*   Nginx не может достучаться до сокета (неправильный путь в `fastcgi_pass`).

**Диагностика:**
```bash
# 1. Проверка существования сокета
ls -la /run/php/php8.4-fpm.sock
# → srw-rw---- 1 www-data www-data 0 Sep 20 12:00 /run/php/php8.4-fpm.sock

# 2. Проверка прав (Nginx worker должен иметь доступ к сокету)
sudo ss -xl | grep php
# → u_str  LISTEN 0      50      /run/php/php8.4-fpm.sock

# 3. Проверка FastCGI-параметров
sudo nginx -T | grep -A5 'fastcgi_pass'
# → fastcgi_pass unix:/run/php/php8.4-fpm.sock;

# 4. Проверка через FastCGI-клиент (не HTTP!)
echo -e "GET /index.php HTTP/1.0\r\n\r\n" | cgi-fcgi -bind -connect /run/php/php8.4-fpm.sock
```

**Решение:**
1.  Убедитесь, что пользователь, от которого работает Nginx worker (обычно `www-data`), входит в группу владельца сокета.
2.  Проверьте, что `listen.owner` и `listen.group` в конфигурации пула соответствуют ожиданиям Nginx.
3.  Перезапустите PHP-FPM после изменения конфигурации: `systemctl reload php8.4-fpm`.

---

## Рекомендации и передовые практики

### Тюнинг пула воркеров (SRE подход)

Расчет `pm.max_children` должен основываться на доступной RAM, а не на произвольных значениях:

```bash
# Получение среднего RSS одного воркера
ps -ylC php-fpm --sort=rss | tail -n +2 | awk '{print $8}' | \
  awk '{total+=$1; count++} END {print "Avg RSS (MB):", total/count/1024}'
# → Avg RSS (MB): 52.3

# Формула:
# pm.max_children = floor((Доступная RAM × 0.7) / Средний RSS)
# Пример: floor((4096 × 0.7) / 52.3) = 54
```

### Настройка OPcache для production

```ini
; /etc/php/8.4/fpm/conf.d/10-opcache.ini
opcache.enable=1
opcache.enable_cli=0
opcache.memory_consumption=256
opcache.interned_strings_buffer=16
opcache.max_accelerated_files=20000
opcache.validate_timestamps=0
opcache.revalidate_freq=60
opcache.save_comments=1
opcache.load_comments=1
```

`opcache.validate_timestamps=0` отключает проверку времени модификации файлов, что критично для производительности в production. После деплоя вызывайте `opcache_reset()` через веб-интерфейс или CLI для принудительной инвалидации кэша.

### Ограничение ресурсов (resource limiting)

Используйте `systemd` для ограничения ресурсов PHP-FPM:

```ini
# /etc/systemd/system/php8.4-fpm.service.d/override.conf
[Service]
MemoryMax=4G
CPUQuota=300%
TasksMax=80
LimitNOFILE=65535
```

`MemoryMax` предотвращает потребление всей доступной RAM, `CPUQuota` ограничивает долю CPU (300% = 3 ядра), `TasksMax` ограничивает общее число задач (воркеры + дочерние процессы).

### Безопасность статусной страницы

Помимо ограничения по IP, используйте следующие меры:

*   **Отключайте статусную страницу, если она не нужна:** закомментируйте `pm.status_path`.
*   **Используйте отдельный внутренний пул** для статусной страницы с `listen.allowed_clients = 127.0.0.1`.
*   **Включите `request_terminate_timeout`** для предотвращения зависших запросов:
    ```ini
    request_terminate_timeout = 30s
    ```
*   **Ограничьте `rlimit_cpu` и `rlimit_memory`** на уровне пула для защиты от злоупотребления:
    ```ini
    rlimit_cpu = 30
    rlimit_memory = 256M
    ```

### Ротация логов

PHP-FPM пишет три типа логов, каждый из которых требует отдельной политики ротации:

1.  **Error log** (`error_log`): системные ошибки и предупреждения. Ротация через `logrotate` или journald.
2.  **Slowlog** (`slowlog`): stack trace медленных запросов. Объем может быстро расти — требуется ограничение размера или ротация.
3.  **Access log** (если включен через `access.log` в FPM или на уровне Nginx): трафик запросов.

Пример конфигурации `logrotate` для slowlog:

```conf
# /etc/logrotate.d/php8.4-fpm-slowlog
/var/log/php8.4-fpm.slowlog {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    maxsize 100M
}
```

### Мониторинг через journald

Для сбора логов в centralized logging (ELK, Loki) настройте forwarding:

```bash
# Проверка настроек journald для PHP-FPM
sudo journalctl -u php8.4-fpm -n 20 --no-pager
```

Для отправки логов в Loki используйте `promtail` с фильтром по unit:

```yaml
# /etc/promtail/config.yml
scrape_configs:
  - job_name: systemd
    systemd_slices:
      - .target
    relabel_configs:
      - source_labels: [__systemd_unit]
        regex: php8.4-fpm
        action: keep
```

### Blackbox Exporter для инфраструктурного мониторинга

Для проверки доступности PHP-FPM извне используйте Blackbox Exporter:

```yaml
# /etc/prometheus/blackbox.yml
modules:
  http_fpm_status:
    prober: http
    timeout: 5s
    http:
      valid_http_versions: ["HTTP/1.0", "HTTP/1.1", "HTTP/2.0"]
      method: GET

# Prometheus scrape config:
scrape_configs:
  - job_name: 'blackbox-php-fpm'
    metrics_path: /probe
    params:
      module: [http_fpm_status]
    static_configs:
      - targets:
        - http://localhost/fpm-status
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox-exporter:9115
```

### Корреляция с метриками Nginx

Для полноценной картины коррелируйте метрики PHP-FPM с ошибками Nginx:

*   **502 Bad Gateway**: `listen queue` > 0, PHP-FPM не запущен, сокет недоступен.
*   **504 Gateway Timeout**: `slow requests` растет, `active processes` на максимуме, `request_slowlog_timeout` срабатывает.

Мониторинг должен включать обе стороны: метрики PHP-FPM и статусные коды из логов Nginx (`$status`, `$upstream_response_time`).

---

## Границы применимости и ограничения

### Ограничения статусной страницы

1.  **Метрики per-worker** доступны только в `?full` режиме и не поддерживают фильтрацию по пулу при множестве pools. При наличии 10+ пулов полный сбор метрик создает существенную нагрузку на мастер-процесс.
2.  **Исторические данные** статусная страница не хранит — это snapshot текущего состояния. Для трендового анализа необходима внешняя система сбора метрик (Prometheus, Zabbix).
3.  **Счетчики** (`max children reached`, `slow requests`, `accepted conn`) — монотонно возрастающие. Для расчета rate используйте `increase()` или `rate()` в PromQL.
4.  **PHP < 8.1**: Нативные метрики OpenMetrics отсутствуют. Экспортер является обязательным компонентом.

### Известные проблемы и их обходные пути

| Проблема | Версия PHP-FPM | Обходной путь |
| :--- | :--- | :--- |
| Утечка памяти в воркерах при использовании FFI | 8.0–8.2 | Ограничьте `pm.max_requests`, обновите до 8.3+ |
| Неверное значение `listen queue` при использовании systemd socket activation | 8.1–8.3 | Используйте Unix-сокет напрямую вместо socket activation |
| Отсутствие метрик OPcache в php-fpm-exporter v2.x | < 2.2 | Обновите экспортер до v2.2+ или используйте OpenMetrics (PHP 8.1+) |
| High cardinality labels в OpenMetrics (PID в label) | 8.1+ | Настройте relabeling в Prometheus для удаления PID-лейблов |

### Особенности работы с TCP-сокетами

При использовании TCP вместо Unix-сокетов (`listen = 127.0.0.1:9000`):

*   Добавьте overhead на сетевой стек (loopback).
*   Убедитесь, что `listen.allowed_clients` настроен для ограничения источников подключений.
*   При масштабировании на несколько нод TCP-сокет может использоваться для распределения нагрузки, но в этом случае требуется балансировщик с sticky-сессиями или настройка `ip_hash` в Nginx.

```ini
; Конфигурация для TCP-режима
[www]
listen = 127.0.0.1:9000
listen.allowed_clients = 127.0.0.1, ::1
```

---

## Дополнительная информация

### См. также
*   **[Тюнинг производительности Nginx](../Nginx/Performance/nginx_performance_tuning.md)**
*   **[Мониторинг кэширования Nginx](../Nginx/Performance/Caching/monitoring.md)**
*   **[Обзор методологий мониторинга (USE/RED)](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)**
*   **[Диагностика процессов в Linux](../../Linux/Diagnostics/Processes/pidstat.md)**
*   **[Диагностика веб-серверов (Troubleshooting)](../Concepts/webserver_troubleshooting.md)**
