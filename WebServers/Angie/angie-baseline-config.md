# Минимальная продакшен-конфигурация Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

*   **Базовый продакшен-конфиг (Baseline Configuration)** — минимальный самодостаточный и безопасный каркас конфигурации веб-сервера для промышленной эксплуатации. Охватывает процессную модель (Master/Worker), сетевой стек ядра, модульную структуру каталогов, обработку виртуальных хостов по умолчанию, наблюдаемость и журналирование без преждевременного и рискованного тюнинга.
*   **Контексты конфигурации (Contexts)** — иерархические блоки директив в файлах конфигурации: глобальный (`main`), событийный (`events`), протокольный (`http`, `stream`) и уровни маршрутизации (`server`, `location`, `upstream`). Директивы обладают строгими правилами вложенности и наследования.
*   **Процессная модель Master/Worker** — архитектура разделения привилегий: привилегированный управляющий процесс (`master`, работает от `root`) открывает низкоуровневые порты (80, 443) и валидирует конфигурацию, а непривилегированные рабочие процессы (`worker`, работают от системного пользователя `angie`) изолированно обрабатывают сетевые соединения.
*   **Дескрипторы файлов (`nofile` / `worker_rlimit_nofile`)** — системный лимит ядра ОС на количество одновременно открытых файлов и сокетов процессом. Для сетевого сервера каждое клиентское соединение, открытый файл статики или соединение с бэкендом расходует минимум один файловый дескриптор.
*   **Виртуальный сервер по умолчанию (`default_server` / Catch-All)** — блок `server`, перехватывающий любые входящие HTTP/HTTPS-запросы, в которых заголовок `Host` или расширение TLS SNI не соответствуют ни одному явно объявленному домену.
*   **Сброс TLS-рукопожатия (`ssl_reject_handshake`)** — нативная директива Angie/Nginx, позволяющая отклонять установку защищенного соединения на этапе `ClientHello` без отправки сертификата по умолчанию при обращении сканеров к неизвестным или прямым IP-адресам.
*   **Зона статуса (`status_zone`)** — именованная область разделяемой памяти (Shared Memory) в Angie, аккумулирующая счетчики запросов, кодов ответов и байтов трафика для конкретного виртуального сервера или пути без блокировок рабочих процессов.
*   **Ротация журналов (Log Rotation / `SIGUSR1`)** — процедура переименования текущих файлов логов внешней утилитой (`logrotate`) с последующей отправкой сигнала `USR1` мастер-процессу для атомарного переоткрытия дескрипторов файлов без потери записей.
*   **Валидация конфигурации (`angie -t` / `angie -T`)** — процедура синтаксической и семантической проверки файлов конфигурации до их загрузки в рабочую память процесса.

---

## Базовые концепции и архитектура

### 1. Файловая структура каталога /etc/angie/

Промышленная эксплуатация Angie в среде системного администрирования требует четкой модульности: глобальные директивы сервера отделяются от настроек конкретных виртуальных хостов и апстримов:

```
/etc/angie/
├── angie.conf                  # Главный каркас (main, events, базовый http)
├── mime.types                  # Таблица сопоставления MIME-типов и расширений
├── conf.d/                     # Модульные конфигурации виртуальных хостов
│   ├── 00-default.conf         # Защитный catch-all сервер (порт 80 и 443)
│   ├── 10-upstreams.conf       # Пулы бэкендов (upstream)
│   └── example.com.conf        # Конфигурация конкретного сервиса
└── modules/                    # Каталог динамических модулей (.so)
```

Каталоги времени выполнения и журналов:
*   `/var/log/angie/` — каталоги журналов (`access.log`, `error.log`), доступные на запись пользователю `angie` и на чтение группе `adm`.
*   `/run/angie.pid` — PID-файл мастер-процесса, контролируемый systemd.
*   `/var/cache/angie/` — каталог для файловых кэшей (FastCGI, proxy cache) с правами владельца `angie:angie`.

---

### 2. Иерархия контекстов и модель наследования директив

Конфигурационный файл Angie представляет собой дерево вложенных контекстов:

```
[main] ─────────────────────> worker_processes, user, pid, error_log
  │
  ├── [events] ─────────────> worker_connections, use epoll, multi_accept
  │
  ├── [stream] ─────────────> L4-проксирование TCP/UDP (отдельный контекст)
  │
  └── [http] ───────────────> sendfile, tcp_nopush, log_format, timeouts
        │
        ├── [upstream] ─────> балансировка и пулы бэкендов
        │
        └── [server] ───────> listen, server_name, status_zone
              │
              └── [location]> try_files, proxy_pass, expires, root
```

**Ключевые правила наследования и переопределения:**
1.  **Одноуровневое наследование большинства параметров:** директивы вроде `root`, `client_max_body_size`, `access_log` наследуются из родительского блока в дочерний, если в дочернем они не объявлены явно.
2.  **Ловушка директивы `add_header`:** если на уровне `location` объявлена хотя бы одна директива `add_header`, абсолютно все директивы `add_header` с уровней `http` и `server` для этого запроса **игнорируются**. Базовые заголовки безопасности необходимо либо выносить в отдельный включаемый файл (`include /etc/angie/snippets/security-headers.conf;`), либо объявлять на уровне `server`.
3.  **Контекстное ограничение директивы `status_zone`:** в отличие от общих директив мониторинга, `status_zone` в Angie допустима только внутри контекстов `server`, `location` и `upstream` (в протоколах HTTP и Stream). Попытка указать `status_zone` напрямую внутри блока `http` приводит к ошибке синтаксиса `[emerg] "status_zone" directive is not allowed here`.

---

### 3. Процессная модель Master/Worker и системные лимиты (nofile)

Angie запускается в виде одного процесса `master` от пользователя `root` (необходимо для привязки сокетов к привилегированным портам 80/443 и управления файлами PID/логами) и нескольких непривилегированных процессов `worker`, выполняющих реальную обработку трафика:

```
                  ┌──────────────────────────────┐
                  │     Master Process (root)    │
                  │   - Чтение конфигурации      │
                  │   - Открытие портов 80, 443  │
                  │   - Управление worker-ами    │
                  └──────────────┬───────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Worker 1 (angie) │    │ Worker 2 (angie) │    │ Worker N (angie) │
│ - Epoll loop     │    │ - Epoll loop     │    │ - Epoll loop     │
│ - Обслуживание   │    │ - Обслуживание   │    │ - Обслуживание   │
│   клиентских TCP │    │   клиентских TCP │    │   клиентских TCP │
└──────────────────┘    └──────────────────┘    └──────────────────┘
```

**Расчет лимитов файловых дескрипторов:**
Каждому рабочему процессу требуется файловый дескриптор на каждое клиентское сетевое соединение. В случае обратного проксирования (Reverse Proxy) на один запрос расходуется:
*   1 дескриптор для входящего сокета от клиента;
*   1 дескриптор для исходящего сокета к бэкенду;
*   дескрипторы открытых файлов логов, дискового кэша или статики.

Следовательно, минимальный лимит `worker_rlimit_nofile` рассчитывается по формуле:
$$\text{worker\_rlimit\_nofile} \ge \text{worker\_connections} \times 2 + 1024$$

Для предотвращения падения воркеров с ошибкой `[alert] worker_connections exceeds open file resource limit` значение `worker_rlimit_nofile` задается на уровне `main` и синхронизируется с `LimitNOFILE` в сервисе systemd.

---

### 4. Сетевой стек и параметры оптимизации ввода-вывода (I/O)

В базовой продакшен-конфигурации Angie оптимизация I/O строится на стандартных неблокирующих возможностях ядра Linux без агрессивного овертюнинга:

1.  **`sendfile on;`** — активирует системный вызов `sendfile()`, позволяющий передавать байты статических файлов из кэша страниц ядра (Page Cache) напрямую в сокет сетевой карты без копирования данных в адресное пространство процесса (Zero-Copy).
2.  **`tcp_nopush on;`** — используется только совместно с `sendfile`. Заставляет ядро упаковывать заголовки HTTP-ответа и начало файла в один максимальный TCP-пакет (MTU), предотвращая сетевую фрагментацию.
3.  **`tcp_nodelay on;`** — отключает алгоритм Нагла (Nagle's algorithm) для активных соединений (`keepalive`). Применяется в блоке `http` для немедленной отправки небольших пакетов (JSON API, короткие ответы) без искусственной задержки в 200 мс.
4.  **`reset_timedout_connection on;`** — принудительно сбрасывает зависшие соединения по таймауту отправкой TCP RST вместо стандартного четырехстороннего закрытия FIN/ACK, мгновенно освобождая занятую память сокета в ядре.
5.  **Консервативные таймауты:** значения `client_header_timeout 15s;` и `client_body_timeout 15s;` защищают сервер от атак типа Slowloris, не создавая проблем для легитимных клиентов с мобильными сетями.

---

### 5. Базовая безопасность и защита периметра по умолчанию

*   **Сокрытие информации (`server_tokens off;`):** убирает номер версии Angie из заголовка `Server` и со стандартных страниц ошибок (404, 500, 502), усложняя автоматизированный сбор сведений об инфраструктуре.
*   **Изоляция пользователей:** рабочие процессы обязаны функционировать под выделенной системной учетной записью `angie`. Запуск воркеров от пользователя `root` или общего пользователя приложений категорически запрещен.
*   **Catch-All Server:** любой продакшен-хост непрерывно сканируется по IP-адресам ботнетами. Конфигурация обязана перехватывать запросы без корректного заголовка `Host` и отсекать их с кодом HTTP 444 (нестандартный код Nginx/Angie, немедленно разрывающий TCP-соединение без отправки данных) либо отклонять рукопожатие TLS через `ssl_reject_handshake on;`.

---

## Практические сценарии

### Сценарий 1: Модульный эталонный /etc/angie/angie.conf

Данный файл представляет собой эталонный корневой конфигурационный файл. Он содержит глобальные настройки процесса, событийную модель, общие параметры протокола HTTP, структурированные форматы логов и подключение модульных конфигураций виртуальных хостов из каталога `/etc/angie/conf.d/`.

```nginx
# /etc/angie/angie.conf
# ==============================================================================
# 1. ГЛОБАЛЬНЫЙ КОНТЕКСТ (MAIN)
# ==============================================================================

# Пользователь и группа для рабочих процессов
user  angie;

# Количество воркеров равно количеству доступных ядер CPU
worker_processes  auto;

# Привязка воркеров к ядрам CPU (предотвращает миграцию контекстов в планировщике ядра)
worker_cpu_affinity  auto;

# Лимит файловых дескрипторов на один рабочий процесс (должен согласовываться с systemd)
worker_rlimit_nofile  65535;

# Файл идентификатора мастер-процесса
pid        /run/angie.pid;

# Системный журнал ошибок (уровень warn оптимален для production)
error_log  /var/log/angie/error.log warn;

# Включение JIT-компиляции для регулярных выражений PCRE
pcre_jit   on;


# ==============================================================================
# 2. СОБЫТИЙНАЯ МОДЕЛЬ (EVENTS)
# ==============================================================================
events {
    # Максимальное число одновременных соединений на один worker-процесс
    worker_connections  4096;

    # Использование эффективного механизма мультиплексирования событий Linux
    use  epoll;

    # Прием всех поступивших в очередь соединений за одну итерацию epoll_wait
    multi_accept  on;
}


# ==============================================================================
# 3. HTTP КОНТЕКСТ (HTTP)
# ==============================================================================
http {
    # Сопоставление расширений файлов и MIME-типов
    include       /etc/angie/mime.types;
    default_type  application/octet-stream;

    # --------------------------------------------------------------------------
    # 3.1. Безопасность и сокрытие версии
    # --------------------------------------------------------------------------
    server_tokens  off;

    # Предотвращение передачи пустых и некорректных заголовков бэкендам
    ignore_invalid_headers  on;

    # Максимальный допустимый размер тела запроса клиента (защита от переполнения)
    client_max_body_size    16m;

    # --------------------------------------------------------------------------
    # 3.2. Оптимизация сетевого стека и ввода-вывода (I/O)
    # --------------------------------------------------------------------------
    sendfile        on;
    tcp_nopush      on;
    tcp_nodelay     on;

    # --------------------------------------------------------------------------
    # 3.3. Таймауты и управление соединениями
    # --------------------------------------------------------------------------
    keepalive_timeout           65s;
    keepalive_requests          1000;
    reset_timedout_connection   on;

    client_header_timeout       15s;
    client_body_timeout         15s;
    send_timeout                15s;

    # --------------------------------------------------------------------------
    # 3.4. Хэш-таблицы сервера
    # --------------------------------------------------------------------------
    types_hash_max_size          2048;
    server_names_hash_bucket_size 64;

    # --------------------------------------------------------------------------
    # 3.5. Форматирование журналов (Access Logs)
    # --------------------------------------------------------------------------
    # Стандартный текстовый формат для локальной диагностики
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for" '
                    'rt=$request_time uct="$upstream_connect_time" '
                    'uht="$upstream_header_time" urt="$upstream_response_time"';

    # Структурированный JSON-формат для SRE-сборщиков логов (Vector, Promtail, Filebeat)
    log_format json_combined escape=json '{'
        '"timestamp":"$time_iso8601",'
        '"client_ip":"$remote_addr",'
        '"vhost":"$host",'
        '"request_method":"$request_method",'
        '"request_uri":"$request_uri",'
        '"server_protocol":"$server_protocol",'
        '"status":$status,'
        '"body_bytes_sent":$body_bytes_sent,'
        '"request_time":$request_time,'
        '"upstream_connect_time":"$upstream_connect_time",'
        '"upstream_header_time":"$upstream_header_time",'
        '"upstream_response_time":"$upstream_response_time",'
        '"http_referrer":"$http_referer",'
        '"http_user_agent":"$http_user_agent"'
    '}';

    # Буферизованная запись лога доступа для снижения нагрузки на дисковый I/O
    access_log  /var/log/angie/access.log json_combined buffer=64k flush=5s;

    # --------------------------------------------------------------------------
    # 3.6. Подключение модульных виртуальных хостов и конфигураций
    # --------------------------------------------------------------------------
    include  /etc/angie/conf.d/*.conf;
}
```

---

### Сценарий 2: Защитный виртуальный хост по умолчанию (Default Server Catch-All)

Файл `/etc/angie/conf.d/00-default.conf` гарантирует, что любые запросы по неизвестным доменным именам, запросы с пустым заголовком `Host`, а также попытки прямого сканирования по публичному IP-адресу сервера мгновенно отклоняются без раскрытия сертификатов и без нагрузки на внутренние сервисы:

```nginx
# /etc/angie/conf.d/00-default.conf
# ==============================================================================
# СЕРВЕР ПО УМОЛЧАНИЮ (CATCH-ALL) ДЛЯ HTTP (ПОРТ 80)
# ==============================================================================
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    # Отключение логирования нелегитимного мусорного трафика ботов
    access_log off;
    log_not_found off;

    # Немедленный разрыв соединения без отправки HTTP-заголовков и тела
    return 444;
}

# ==============================================================================
# СЕРВЕР ПО УМОЛЧАНИЮ (CATCH-ALL) ДЛЯ HTTPS (ПОРТ 443)
# ==============================================================================
server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;

    # Завершение рукопожатия TLS на этапе ClientHello при неизвестном SNI
    ssl_reject_handshake on;

    access_log off;
    log_not_found off;
}
```

---

### Сценарий 3: Типовой виртуальный хост для статического контента и обратного прокси

Файл `/etc/angie/conf.d/example.com.conf` демонстрирует корректную организацию промышленного виртуального хоста: сбор метрик в `status_zone`, изоляция статики, кэширование и безопасное проксирование API к бэкенду.

```nginx
# /etc/angie/conf.d/example.com.conf

# Определение пула бэкендов приложения
upstream app_backend {
    zone app_backend_zone 256k;
    server 127.0.0.1:8080 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

server {
    listen 80;
    listen [::]:80;
    server_name example.com www.example.com;

    # Выделенная зона разделяемой памяти для сбора метрик SRE
    status_zone example_com;

    # Корневой каталог для статических файлов
    root /var/www/example.com/public;
    index index.html;

    # Базовые заголовки безопасности (объявлены на уровне server)
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Логирование конкретного виртуального хоста
    access_log /var/log/angie/example.com_access.log json_combined buffer=32k flush=5s;
    error_log  /var/log/angie/example.com_error.log warn;

    # Запрет доступа к скрытым системным файлам (.git, .env, .htaccess)
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }

    # Отключение логирования служебных файлов браузеров
    location = /favicon.ico {
        log_not_found off;
        access_log off;
    }

    location = /robots.txt {
        log_not_found off;
        access_log off;
    }

    # Эффективная отдача неизменяемой статики с длительным кэшированием браузером
    location /static/ {
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
        try_files $uri =404;
    }

    # Проксирование динамических вызовов API к локальному приложению
    location /api/ {
        proxy_pass http://app_backend;
        proxy_http_version 1.1;

        # Использование пула постоянных соединений keepalive к апстриму
        proxy_set_header Connection "";

        # Передача стандартных клиентских заголовков
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Разумные таймауты взаимодействия с бэкендом
        proxy_connect_timeout 5s;
        proxy_send_timeout    15s;
        proxy_read_timeout    15s;
    }

    # Маршрутизация Single Page Application (SPA) или стандартных файлов
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

---

### Сценарий 4: Системная интеграция: systemd override и ротация логов (logrotate)

В production-окружениях Linux параметры операционной системы должны быть согласованы с конфигурацией веб-сервера.

#### 1. Настройка лимитов службы systemd

По умолчанию системные ограничения systemd могут ограничивать процесс 1024 дескрипторами. Создайте drop-in конфигурацию переопределения лимитов:

```bash
# Создание каталога конфигурации переопределения юнита
sudo mkdir -p /etc/systemd/system/angie.service.d/

# Создание конфигурационного файла лимитов
sudo tee /etc/systemd/system/angie.service.d/override.conf << 'EOF'
[Service]
LimitNOFILE=65535
LimitNPROC=65535
TasksMax=infinity
EOF

# Перечитывание конфигурации systemd
sudo systemctl daemon-reload
# → (успешное применение без вывода)

# Перезапуск сервиса для применения новых системных лимитов
sudo systemctl restart angie
# → (сервис перезапущен)
```

Проверка фактически примененных лимитов работающего мастер-процесса:

```bash
cat /proc/$(cat /run/angie.pid)/limits | grep "Max open files"
# → Max open files            65535                65535                files
```

#### 2. Конфигурация ротации журналов logrotate

Для предотвращения переполнения дискового пространства создается правило `/etc/logrotate.d/angie`. Ротация использует сигнал `USR1`, при получении которого Angie закрывает старые дескрипторы и открывает новые файлы логов по их путям без перезагрузки процессов:

```bash
sudo tee /etc/logrotate.d/angie << 'EOF'
/var/log/angie/*.log {
    daily
    missingok
    rotate 14
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
EOF
```

Проверка корректности скрипта ротации в тестовом режиме:

```bash
sudo logrotate -d /etc/logrotate.d/angie
# → reading config file /etc/logrotate.d/angie
# → handling /var/log/angie/*.log
```

---

### Сценарий 5: Валидация конфигурации, инспекция дампа и автоматизация в CI/CD

В SRE-практике недопустимо применять изменения конфигурации без предварительного тестирования синтаксиса и зависимостей.

#### 1. Проверка синтаксиса и целостности дерева файлов

```bash
# Тестирование синтаксиса текущей конфигурации
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful
```

#### 2. Инспекция полного объединенного дампа (Pre-Flight Diff)

Команда `angie -T` считывает конфигурацию, раскрывает все директивы `include` и выводит полный итоговый текст. Это позволяет обнаружить дублирующиеся блоки `server`, конфликты директив или скрытые опечатки:

```bash
# Дамп всей конфигурации в единый временный файл
sudo angie -T > /tmp/angie_compiled.conf

# Проверка распределения директив listen и server_name
grep -n -E "listen|server_name|status_zone" /tmp/angie_compiled.conf
# → 68:        listen 80 default_server;
# → 69:        server_name _;
# → 78:        listen 80;
# → 80:        server_name example.com www.example.com;
# → 82:        status_zone example_com;
```

#### 3. Zero-Downtime Reload конфигурации

После подтверждения успешного теста синтаксиса конфигурация применяется без сброса соединений:

```bash
# Проверка и перезагрузка в одну команду (защита от применения сбойного конфига)
sudo angie -t && sudo systemctl reload angie
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful
```

#### 4. Проверка защитных механизмов baseline-конфигурации

```bash
# 1. Запрос к легитимному виртуальному хосту
curl -sI -H "Host: example.com" http://127.0.0.1/ | head -n 5
# → HTTP/1.1 200 OK
# → Server: Angie
# → Content-Type: text/html
# → X-Content-Type-Options: nosniff
# → X-Frame-Options: SAMEORIGIN

# 2. Запрос со сканированием по прямому IP-адресу (Catch-All с кодом 444)
curl -sI http://127.0.0.1/
# → curl: (52) Empty reply from server

# 3. Запрос с неизвестным или враждебным заголовком Host
curl -sI -H "Host: malicious-scanner.net" http://127.0.0.1/
# → curl: (52) Empty reply from server
```

---

## Операции и команды

Сводная таблица стандартных команд системного администратора для управления и аудита базовой конфигурации Angie:

| Задача / Операция | Команда | Ожидаемый результат / Примечание |
|:---|:---|:---|
| **Проверка синтаксиса** | `sudo angie -t` | Проверяет файлы, пути к сертификатам и выводит `syntax is ok` |
| **Тестирование файла вне `/etc`** | `sudo angie -t -c /path/to/test.conf` | Валидация перед подстановкой в продакшен или в CI-пайплайне |
| **Полный дамп конфигурации** | `sudo angie -T` | Разворачивает все `include` для аудита и грепа |
| **Вывод версии Angie** | `angie -v` | Выводит строку версии (например, `angie version: 1.12.0`) |
| **Вывод опций сборки** | `angie -V` | Список включенных модулей и путей к библиотекам OpenSSL/PCRE |
| **Статус сервиса в systemd** | `sudo systemctl status angie` | Просмотр состояния `active (running)`, времени аптайма и PID |
| **Безопасная перезагрузка** | `sudo systemctl reload angie` | Отправка `SIGHUP` мастер-процессу без разрыва соединений |
| **Ручная ротация логов** | `sudo kill -USR1 $(cat /run/angie.pid)` | Переоткрытие файлов логов без сброса активных сессий |
| **Аудит слушающих портов** | `sudo ss -tulpn \| grep angie` | Проверка привязки сокетов к адресам `0.0.0.0:80` и `0.0.0.0:443` |
| **Проверка лимита дескрипторов** | `cat /proc/$(pgrep -f "angie: master")/limits \| grep "open files"` | Проверка фактического `LimitNOFILE` мастер-процесса |
| **Просмотр дерева процессов** | `ps -ef --forest \| grep -E 'angie'` | Отображение иерархии `master process` и дочерних `worker process` |

---

## Диагностика и устранение неисправностей

### 1. Ошибка `[emerg] bind() to 0.0.0.0:80 failed (98: Address already in use)`

*   **Симптом:** Angie не запускается через `systemctl start angie`. В системном журнале `journalctl -u angie` фиксируется сообщение о занятом порту.
*   **Причина:** Порт 80 или 443 уже занят другим процессом (например, ранее установленным Apache, Nginx или зависшим старым экземпляром Angie).
*   **Диагностика:**
    ```bash
    sudo ss -tulpn | grep -E ':(80|443)'
    # → tcp   LISTEN 0 511 0.0.0.0:80  0.0.0.0:*  users:(("nginx",pid=1234,fd=6))
    ```
*   **Решение:** Остановите и отключите конфликтующий веб-сервер либо освободите порт:
    ```bash
    sudo systemctl stop nginx
    sudo systemctl disable nginx
    sudo systemctl start angie
    ```

---

### 2. Предупреждение `[alert] worker_connections exceeds open file resource limit: 1024`

*   **Симптом:** При старте или reload в `/var/log/angie/error.log` появляется предупреждение, и Angie принудительно уменьшает эффективное число соединений до текущего лимита `nofile` (обычно 1024).
*   **Причина:** Директива `worker_connections 4096;` требует больше дескрипторов, чем разрешено процессу ядром ОС или юнитом systemd.
*   **Диагностика:**
    ```bash
    cat /proc/$(cat /run/angie.pid)/limits | grep "Max open files"
    # → Max open files            1024                 1024                 files
    ```
*   **Решение:**
    1.  В корневом `/etc/angie/angie.conf` в секции `main` добавьте:
        ```nginx
        worker_rlimit_nofile 65535;
        ```
    2.  Настройте systemd drop-in юнит с директивой `LimitNOFILE=65535`, как описано в Сценарии 4, выполните `sudo systemctl daemon-reload` и перезапустите Angie.

---

### 3. Ошибка `open() "/var/www/..." failed (13: Permission denied)`

*   **Симптом:** Клиенты получают ошибку `403 Forbidden` при попытке загрузить статические файлы, хотя путь в директиве `root` указан верно.
*   **Причина:** Рабочий процесс Angie функционирует под системным пользователем `angie` и не имеет прав чтения (`r`) на запрашиваемый файл либо прав выполнения (`x`) на один из родительских каталогов пути.
*   **Диагностика:**
    ```bash
    # Проверка доступности файла от лица пользователя angie
    sudo -u angie test -r /var/www/example.com/public/index.html && echo "Доступен" || echo "Запрещен"
    # → Запрещен
    ```
*   **Решение:** Установите корректного владельца и права доступа на каталоги и файлы:
    ```bash
    sudo chown -R angie:angie /var/www/example.com/public
    sudo find /var/www/example.com/public -type d -exec chmod 755 {} +
    sudo find /var/www/example.com/public -type f -exec chmod 644 {} +
    ```

---

### 4. Ошибка `[emerg] "status_zone" directive is not allowed here`

*   **Симптом:** Команда `angie -t` завершается аварийно с ошибкой расположения директивы.
*   **Причина:** Директива `status_zone` была ошибочно помещена на глобальный уровень контекста `http`.
*   **Диагностика:**
    ```bash
    sudo angie -t
    # → angie: [emerg] "status_zone" directive is not allowed here in /etc/angie/angie.conf:59
    ```
*   **Решение:** Удалите `status_zone` из блока `http` в `/etc/angie/angie.conf` и переместите ее внутрь конкретных блоков `server { ... }` или `location { ... }` в файлах `/etc/angie/conf.d/*.conf`.

---

### 5. Ошибка `could not build server_names_hash, you should increase server_names_hash_bucket_size`

*   **Симптом:** При добавлении новых виртуальных хостов или использовании длинных доменных имен сервер отказывается перезагружаться.
*   **Причина:** Размера корзины хэш-таблицы имен серверов по умолчанию (32 или 64 байта) недостаточно для хранения длины доменов.
*   **Диагностика:** Ошибка проявляется при запуске `angie -t`.
*   **Решение:** В контексте `http` файла `/etc/angie/angie.conf` увеличьте размер корзины:
    ```nginx
    http {
        server_names_hash_bucket_size 128;
        ...
    }
    ```

---

### 6. Ошибка `a duplicate default server for 0.0.0.0:80`

*   **Симптом:** При тестировании конфигурации возникает ошибка: `[emerg] a duplicate default server for 0.0.0.0:80 in /etc/angie/conf.d/site.conf:2`.
*   **Причина:** Параметр `default_server` указан более чем в одном блоке `server` для одинаковой комбинации IP-адреса и порта.
*   **Диагностика:**
    ```bash
    grep -rn "default_server" /etc/angie/
    # → /etc/angie/conf.d/00-default.conf:5:    listen 80 default_server;
    # → /etc/angie/conf.d/site.conf:2:          listen 80 default_server;
    ```
*   **Решение:** Удалите параметр `default_server` из прикладного файла `site.conf`, оставив его исключительно в защитном заглушечном файле `00-default.conf`.

---

## Лучшие практики

1.  **Принцип детерминированного порядка загрузки (Lexicographical Include):**
    Используйте цифровые префиксы в именах файлов внутри `/etc/angie/conf.d/` (`00-default.conf`, `10-upstreams.conf`, `20-example.com.conf`). Символ подстановки `include conf.d/*.conf;` считывает файлы в лексикографическом порядке. Это гарантирует, что сервер по умолчанию всегда инициализируется первым.
2.  **Защита конфигурационных файлов и каталогов:**
    Конфигурация веб-сервера может содержать внутренние IP-адреса, пути и секретные ключи. Ограничьте права доступа к каталогу `/etc/angie`:
    ```bash
    sudo chown -R root:angie /etc/angie
    sudo chmod 750 /etc/angie
    sudo chmod 640 /etc/angie/angie.conf /etc/angie/conf.d/*.conf
    ```
3.  **Запрет жесткого размещения сайтов в основном `angie.conf`:**
    Файл `/etc/angie/angie.conf` должен служить исключительно платформенным каркасом. Никогда не размещайте рабочие блоки `server` прикладных доменов непосредственно в главном файле.
4.  **Атомарный пайплайн перезагрузки (Zero-Downtime Reload Pattern):**
    В скриптах автоматизации, деплоя и Ansible всегда объединяйте проверку синтаксиса с командой reload:
    ```bash
    sudo angie -t && sudo systemctl reload angie
    ```
    Если синтаксический тест завершается с ошибкой, команда `systemctl reload` не выполняется, и текущие рабочие процессы продолжают стабильно обслуживать пользователей на старой валидной ревизии.
5.  **Наблюдаемость из коробки (Baseline Observability):**
    Всегда присваивайте каждому виртуальному серверу уникальную зону `status_zone <name>;`. Это позволяет без дополнительных затрат подключить сбор метрик в Prometheus через нативный модуль `ngx_http_prometheus_module` или консоль управления Angie Console.
6.  **Управление версиями конфигурации (Infrastructure as Code):**
    Каталог `/etc/angie` должен быть инициализирован как локальный git-репозиторий или полностью управляться системой управления конфигурациями (Ansible, SaltStack) с обязательным прогоном `angie -t` на этапе валидации шаблона (`validate: 'angie -t -c %s'`).
7.  **CI/CD тестирование конфигураций перед деплоем:**
    Внедряйте автоматическую проверку пула конфигурационных файлов в пайплайнах (GitLab CI / GitHub Actions) в изолированном Docker-раннере. Для прохождения проверки синтаксиса генерируйте временные самоподписанные сертификаты-заглушки:
    ```yaml
    # Фрагмент .gitlab-ci.yml:
    test_angie_config:
      image: docker.angie.software/angie:1.12-alpine
      stage: test
      script:
        - mkdir -p /etc/angie/ssl
        - openssl req -x509 -nodes -days 1 -newkey rsa:2048 -keyout /etc/angie/ssl/dummy.key -out /etc/angie/ssl/dummy.crt -subj "/CN=test"
        - angie -t -c /builds/$CI_PROJECT_PATH/etc/angie/angie.conf
    ```
8.  **Харденинг процесса на уровне ОС (systemd Sandboxing):**
    Изолируйте сервис Angie от системных каталогов операционной системы с помощью drop-in файла `/etc/systemd/system/angie.service.d/hardening.conf` (`ProtectSystem=strict`, `ProtectHome=yes`, `NoNewPrivileges=yes`, `CapabilityBoundingSet=CAP_NET_BIND_SERVICE`). Подробный разбор и готовые манифесты: [Харденинг Nginx/Angie на уровне системы: systemd, SELinux, AppArmor](../Nginx/Security/nginx_systemd_selinux_hardening.md).

---

## Дополнительная информация

*   **Наследование заголовков безопасности:** При необходимости расширения заголовков в дочерних блоках `location` используйте директиву `include /etc/angie/snippets/security-headers.conf;`, чтобы не потерять общесерверные заголовки `X-Frame-Options` и `X-Content-Type-Options`.
*   **Переход на HTTPS:** При настройке защищенных соединений параметры TLS, протоколы HTTP/2 и HTTP/3, а также генерация сертификатов настраиваются в отдельных файлах виртуальных хостов с опорой на [Настройку TLS в Angie](./angie_tls_setup.md).
*   **Тюнинг производительности под высокие нагрузки:** При росте трафика свыше 10 000 RPS обратитесь к руководству [Оптимизация производительности Angie](./High_Load/performance_optimization.md) для настройки `SO_REUSEPORT`, kTLS, алгоритма TCP BBR и оптимизации буферов ядра.

---

## См. также

*   **[Обзор Angie](./angie_overview.md)** — архитектура, отличия от Nginx и ключевые возможности.
*   **[Установка Angie](./angie_installation.md)** — установка из официальных репозиториев для всех поддерживаемых дистрибутивов Linux.
*   **[Angie Ingress Controller в Kubernetes](./angie_ingress_controller.md)** — использование Angie в роли Ingress-шлюза на On-Premises кластерах.
*   **[Отказоустойчивость с BGP Anycast и ECMP](./angie_ha_with_bgp_anycast.md)** — построение горизонтально масштабируемого Active-Active кластера на базе BIRD 2 и сетевой фабрики.
*   **[Диагностика и устранение неисправностей Angie](./angie_troubleshooting.md)** — SRE-руководство по локализации сбоев, профилированию 100% CPU и анализу очередей ядра.
*   **[Виртуальные хосты и server_name в Angie](./angie-server-name.md)** — алгоритмы маршрутизации, маски (wildcards), регулярные выражения и SNI.
*   **[Graceful Reload и Binary Upgrade в Angie](./angie-graceful-reload.md)** — механизм смены поколений процессов и обновление бинарного файла без простоя.
*   **[Журналирование в Angie](./angie_logging.md)** — детальная настройка access/error логов, JSON-экранирование и фильтрация.
*   **[Заголовки безопасности в Angie](./angie-security-headers.md)** — политики HSTS, CSP, Referrer-Policy и нюансы наследования директивы `add_header`.
*   **[Настройка TLS в Angie](./angie_tls_setup.md)** — конфигурация SSL/TLS, шифронаборы, протоколы HTTP/2 и HTTP/3.
*   **[Оптимизация производительности Angie](./High_Load/performance_optimization.md)** — тонкая настройка ОС, планировщика ядра и очередей сокетов.
*   **[Мониторинг Angie — основные концепции](./angie_monitoring/angie_monitoring_concepts.md)** — зоны статуса, разделяемая память и внутренние счетчики.
*   **[Мониторинг Angie с помощью Prometheus](./angie_monitoring/angie_monitoring_prometheus.md)** — экспорт метрик в формате OpenMetrics.
*   **[Управление доступом в Angie](./angie_access_control.md)** — директивы allow/deny, базовая аутентификация и ограничение прав.
*   **[Миграция с Nginx на Angie](./migration_from_nginx.md)** — практические шаги бесшовного перехода с Nginx на Angie.
*   **[Харденинг Nginx/Angie на уровне системы](../Nginx/Security/nginx_systemd_selinux_hardening.md)** — системные директивы изоляции сервисов, Capabilities, SELinux и AppArmor.
*   **[Обзор Nginx](../Nginx/Core/nginx_overview.md)** — общая архитектура Nginx-совместимых веб-серверов.