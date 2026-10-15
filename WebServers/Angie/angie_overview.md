# Обзор Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

**Angie** — высокопроизводительный веб-сервер, обратный прокси-сервер (reverse proxy), почтовый прокси и балансировщик сетевой нагрузки (L4/L7) с открытым исходным кодом. Разработан компанией ООО «Веб-сервер» командой ключевых экс-разработчиков [Nginx](../Nginx/Core/nginx_overview.md). Включен в Единый реестр российских программ (запись № 17604).

**Drop-in замена** — архитектурное свойство Angie, позволяющее использовать его вместо Nginx без изменения структуры конфигурационных файлов, синтаксиса директив и логики обработки трафика.

**Angie PRO** — коммерческая редакция веб-сервера с расширенными возможностями: активный мониторинг бэкендов (Active Health Checks), изменение конфигурации групп серверов через REST API на лету (методы POST, PUT, DELETE), синхронизация разделяемой памяти между узлами кластера (Cluster Zone Sync) и интеграция с российскими СКЗИ (ГОСТ TLS).

**Процессная модель Master/Worker** — архитектура разделения привилегий и обязанностей: управляющий master-процесс работает с правами суперпользователя для открытия портов и управления конфигурацией, а непривилегированные worker-процессы изолированно обрабатывают клиентские сетевые соединения.

**Event Loop (на базе epoll/kqueue)** — асинхронный неблокирующий цикл обработки событий ввода-вывода ядра ОС, позволяющий одному рабочему процессу удерживать и обслуживать десятки тысяч одновременных сетевых соединений без накладных расходов на переключение контекста потоков.

**Shared Memory Zones (Зоны разделяемой памяти)** — сегменты оперативной памяти, выделяемые master-процессом через системные вызовы ядра (`shmget`/`mmap`) и доступные всем worker-процессам для синхронизации состояний (метрики `status_zone`, ограничения `limit_req_zone`, таблицы пиров `upstream zone` и кэш `proxy_cache_path keys_zone`) без межпроцессных блокировок.

**Status API и Visual Console (`angie-console-light`)** — встроенный в Angie механизм телеметрии в реальном времени: отдача структурированного JSON через модуль `api`, нативный экспорт в формате Prometheus без сторонних демонов-экспортеров и готовый легковесный веб-интерфейс мониторинга.

## Базовые концепции

### История, импортозамещение и позиционирование

*   **2022 год:** Создание форка на базе кодовой базы Nginx 1.23.1 для обеспечения технологического суверенитета, непрерывной поддержки и развития веб-технологий в РФ.
*   **Реестр российского ПО:** Программный комплекс Angie (включая редакции Open Source и PRO) официально внесен в Единый реестр российских программ для ЭВМ и баз данных (приказ Минцифры России, реестровая запись № 17604).
*   **Совместимость с ОС:** Полная поддержка отечественных дистрибутивов Linux (Astra Linux Special Edition с поддержкой режима замкнутой программной среды ЗПС/CSE, РЕД ОС, Альт Линукс), а также Enterprise Linux (AlmaLinux, Rocky Linux, RHEL) и Debian/Ubuntu.
*   **Изолированные контуры:** Возможность функционирования в полностью закрытых сегментах сети (air-gapped) без обращений к внешним серверам лицензий или внешним репозиториям.
*   **Модель релизов:** В проекте отсутствует разделение на ветки `mainline` и `stable`. Каждый публичный релиз проходит цикл регрессионного тестирования, является стабильным и готовым к эксплуатации в production. Релизный цикл — ежеквартальный. Текущая база — Nginx 1.27.x.

### Архитектура процессов и жизненный цикл

```
                       [ Master Process ] (root)
                      /        |        \
            Signal   /         |         \   Signal
           Control  /          |          \  Control
                   ▼           ▼           ▼
             [Worker 1]    [Worker 2]    [Worker N] (user: angie)
                 │             │             │
                 └──────┬──────┴──────┬──────┘
                        │             │
                        ▼             ▼
             [ Shared Memory Zones (shm) ]
             (status_zone, limit_req, proxy_cache, upstream)
                        ▲             ▲
                        │             │
                [Cache Manager] [Cache Loader]
```

1.  **Master-процесс (`/usr/sbin/angie`):**
    *   Запускается с правами `root`.
    *   Считывает и парсит конфигурационные файлы (`/etc/angie/angie.conf`).
    *   Создает и привязывает привилегированные сетевые сокеты (порты 80, 443).
    *   Выделяет разделяемую память (`shm`) под зоны состояния и кэша.
    *   Порождает и контролирует жизненный цикл worker-процессов.
    *   Обрабатывает POSIX-сигналы операционной системы (`HUP`, `USR1`, `USR2`, `WINCH`, `QUIT`, `TERM`).
2.  **Worker-процессы:**
    *   Запускаются от непривилегированного пользователя `angie`.
    *   Количество процессов задается директивой `worker_processes auto;` (рекомендуется равным числу физических ядер процессора).
    *   Каждый процесс выполняет независимый неблокирующий Event Loop, ожидая события сетевых сокетов через интерфейс `epoll` (Linux).
    *   Воркеры взаимодействуют друг с другом исключительно через сегменты разделяемой памяти.
3.  **Вспомогательные процессы кэширования:**
    *   **Cache Loader:** кратковременный процесс, запускаемый при старте сервера для считывания заголовков закэшированных файлов с диска и заполнения структур в `keys_zone`.
    *   **Cache Manager:** постоянный фоновый процесс, периодически освобождающий дисковое пространство кэша в соответствии с лимитами `max_size` и алгоритмом LRU (Least Recently Used).

### Асинхронный неблокирующий ввод-вывод и оптимизация ядра

*   **Мультиплексирование через `epoll`:** В отличие от традиционных серверов (где на каждое соединение создается поток ОС), Angie регистрирует файловые дескрипторы сокетов в `epoll`. Ядро Linux уведомляет процесс только о готовых к чтению или записи событиях, исключая холостой опрос.
*   **Zero-Copy передача (`sendfile`):** При отдаче статических файлов директива `sendfile on;` задействует системный вызов ядра, который передает данные напрямую из Page Cache ядра в сетевой буфер сокета, минуя копирование в user-space и снижая нагрузку на системную шину памяти.
*   **Сетевые флаги `tcp_nopush` и `tcp_nodelay`:** 
    *   `tcp_nopush on;` (активирует флаг сокета `TCP_CORK` в Linux) предписывает ядру упаковывать заголовки HTTP и начало файла в один максимальный TCP-пакет (MTU/MSS).
    *   `tcp_nodelay on;` отключает алгоритм Нагла (`TCP_NODELAY`), гарантируя немедленную отправку мелких пакетов (keepalive-запросы, API-ответы) без задержки в 200 мс.
*   **Slab Allocator в Shared Memory:** Для распределения памяти внутри зон (`zone`, `status_zone`, `limit_req_zone`) используется собственный slab-аллокатор Angie. Память нарезается на страницы фиксированного размера со слотами под однотипные структуры, что предотвращает фрагментацию памяти при миллионах транзакций.

### Сравнительный анализ: Angie OSS vs Nginx OSS vs Nginx Plus vs Angie PRO

| Возможность / Характеристика | Nginx Open Source | Nginx Plus (коммерческий) | Angie Open Source | Angie PRO (коммерческий) |
| :--- | :--- | :--- | :--- | :--- |
| **Лицензия** | 2-clause BSD | Коммерческая подписка | 2-clause BSD | Проприетарная коммерческая |
| **Реестр российского ПО** | Нет | Нет | **Да (№ 17604)** | **Да (№ 17604)** |
| **Встроенный JSON Status API** | Нет (только `stub_status`) | Да (`/api/`) | **Да (`api /status/;`)** | **Да (полный CRUD API)** |
| **Нативный экспорт в Prometheus** | Нет (нужен сторонний экспортер) | Да (модуль prometheus) | **Да (`prometheus all;`)** | **Да (`prometheus all;`)** |
| **Встроенная веб-панель (UI)** | Нет | Да (Dashboard) | **Да (`angie-console-light`)** | **Да (Console PRO)** |
| **Автоматизация ACME (TLS)** | Нет (нужен Certbot / acme.sh) | Нет (сторонние решения) | **Да (встроенный модуль `acme`)** | **Да (встроенный модуль `acme`)** |
| **Динамический DNS `resolve` в upstream** | Нет (только при старте) | Да | **Да (периодический опрос DNS)** | **Да** |
| **Управление upstream без reload** | Нет | Да (REST API) | Нет (только чтение API) | **Да (API `POST/PUT/DELETE`)** |
| **Active Health Checks (проверки бэкендов)** | Нет (только пассивные) | Да | Нет (пассивные `max_fails`) | **Да (директива `health_check`)** |
| **Алгоритм балансировки `least_time`** | Нет | Да | **Да (по времени ответа бэкенда)**| **Да** |
| **Плавный вывод бэкенда (`drain`)** | Нет | Да | **Да (`drain` режим серверов)** | **Да** |
| **Синхронизация зон кластера (Cluster Sync)** | Нет | Да (Cluster State Sharing) | Нет | **Да (модуль `cluster_zone_sync`)**|
| **DNS-over-HTTPS (DoH, RFC 8484)** | Нет | Нет | **Да (модуль `doh`)** | **Да (модуль `doh`)** |
| **Поддержка российских СКЗИ (ГОСТ TLS)** | Нет | Нет | Нет | **Да (КриптоПро, Рутокен)** |

### Иерархия контекстов конфигурации

Конфигурация Angie построена по принципу блочной вложенности:

*   **`main` (глобальный контекст):** верхний уровень конфигурации. Определяет базовые системные параметры: пользователя процессов (`user`), количество рабочих процессов (`worker_processes`), PID-файл (`pid`), ограничения файловых дескрипторов (`worker_rlimit_nofile`).
*   **`events`:** определяет модель сетевого взаимодействия воркеров: максимальное число одновременных клиентских соединений на воркер (`worker_connections`), метод обработки (`use epoll`).
*   **`http`:** глобальные параметры протокола HTTP/HTTPS: пулы бэкендов (`upstream`), общие параметры логирования, сжатия, кэширования и подгрузка виртуальных хостов (`include /etc/angie/conf.d/*.conf;`).
*   **`server` (внутри `http`):** объявление конкретного виртуального хоста (комбинация `listen` адреса/порта, `server_name` и сертификатов).
*   **`location` (внутри `server`):** правила маршрутизации и обработки конкретного URI-пути (локальная отдача статики, проксирование `proxy_pass`, ограничение доступа `allow`/`deny`).
*   **`stream`:** независимый от `http` контекст для балансировки и проксирования сетевого трафика транспортного уровня L4 (TCP и UDP), включая SNI-маршрутизацию и проксирование баз данных.

## Практические сценарии

### Сценарий 1: Базовый DevOps-каркас сервера с защитой и мониторингом

Минимальная отказоустойчивая конфигурация для размещения на bare-metal или виртуальной машине Linux. Включает правильное распределение ресурсов, защиту от мусорного трафика через `default_server`, отдачу статики и включение зоны метрик.

```nginx
# /etc/angie/angie.conf
user  angie;
worker_processes  auto;
worker_rlimit_nofile  65535;

error_log  /var/log/angie/error.log warn;
pid        /run/angie.pid;

events {
    worker_connections  8192;
    use epoll;
    multi_accept on;
}

http {
    include       /etc/angie/mime.types;
    default_type  application/octet-stream;

    # Оптимизация сетевого стека Linux
    sendfile        on;
    tcp_nopush      on;
    tcp_nodelay     on;
    keepalive_timeout  65;

    # Защита от раскрытия версии сервера в заголовках
    server_tokens  off;

    # Формат структурированных логов с таймингами бэкендов
    log_format combined_timing '$remote_addr - $remote_user [$time_local] '
                               '"$request" $status $body_bytes_sent '
                               '"$http_referer" "$http_user_agent" '
                               'rt=$request_time uct="$upstream_connect_time" '
                               'uht="$upstream_header_time" urt="$upstream_response_time"';

    access_log  /var/log/angie/access.log combined_timing;

    # Шаблон нативных метрик Prometheus из базовой поставки
    include  /etc/angie/prometheus_all.conf;

    # Заглушка default_server для отклонения запросов с неизвестным Host
    server {
        listen 80 default_server;
        listen 443 ssl default_server;
        server_name _;

        # Самоподписанный заглушечный сертификат для сброса соединений
        ssl_ciphers aNULL;
        ssl_certificate /etc/angie/dummy.crt;
        ssl_certificate_key /etc/angie/dummy.key;

        return 444;
    }

    # Подключение конфигурационных файлов виртуальных хостов
    include /etc/angie/conf.d/*.conf;
}

# Подключение L4 (TCP/UDP) конфигураций
stream {
    include /etc/angie/stream.d/*.conf;
}
```

Подробнее о минимальной конфигурации: **[Минимальная продакшен-конфигурация Angie](./angie-baseline-config.md)**.

### Сценарий 2: Эксплуатационный мониторинг: Status API, Prometheus и Web Console

Организация комплексной телеметрии для SRE-инженера: сбор счетчиков запросов по хостам через `status_zone`, выдача метрик для соскоба Prometheus и подключение веб-консоли управления.

```nginx
# /etc/angie/conf.d/management.conf
server {
    listen 127.0.0.1:8888;
    server_name localhost;

    # Доступ разрешен только доверенным администраторам и коллекторам метрик
    allow 127.0.0.1;
    allow 10.0.0.0/8;
    deny all;

    # 1. Встроенный REST API Angie
    location /status/ {
        api /status/;
        api_config_files off; # off предотвращает утечку паролей из конфигурации
    }

    # 2. Нативный эндпоинт метрик для Prometheus
    location /metrics {
        prometheus all;
    }

    # 3. Веб-консоль мониторинга (пакет angie-console-light)
    location /console/ {
        alias /usr/share/angie-console-light/html/;
        index index.html;
    }

    location /console/static/ {
        alias /usr/share/angie-console-light/html/static/;
    }
}
```

Для того чтобы хост собирал телеметрию, добавьте директиву `status_zone` в рабочий блок `server`:

```nginx
# /etc/angie/conf.d/app.conf
server {
    listen 80;
    server_name app.internal.domain;
    status_zone app_production;

    location / {
        proxy_pass http://backend_pool;
    }
}
```

Подробнее:
*   **[Мониторинг Angie — основные концепции](./angie_monitoring/angie_monitoring_concepts.md)**
*   **[Мониторинг Angie — работа через API](./angie_monitoring/angie_monitoring_api.md)**
*   **[Нативный экспорт в Prometheus](./angie_monitoring/angie_monitoring_prometheus.md)**
*   **[Веб-консоль мониторинга](./angie_monitoring/angie_monitoring_console.md)**

### Сценарий 3: Балансировка нагрузки и вывод серверов на обслуживание (Drain)

Конфигурация пула бэкендов с использованием зон разделяемой памяти, алгоритма `least_time` и режима плавного вывода узлов из эксплуатации (`drain`):

```nginx
# /etc/angie/conf.d/upstream_app.conf
upstream backend_pool {
    # Зона разделяемой памяти обязательна для сбора метрик и динамики
    zone backend_pool_zone 256k;

    # Балансировка по наименьшему времени ответа бэкенда (заголовок + тело)
    least_time header;

    # Основные рабочие узлы
    server 10.10.1.11:8080 weight=5 max_conns=200 max_fails=3 fail_timeout=10s;
    server 10.10.1.12:8080 weight=5 max_conns=200 max_fails=3 fail_timeout=10s;

    # Узел, выводимый на регламентные работы (drain):
    # Принимает только запросы существующих клиентов с сессионной привязкой,
    # новые клиенты на этот сервер не направляются
    server 10.10.1.13:8080 drain;

    # Пул постоянных TCP-соединений к апстримам
    keepalive 64;
}

server {
    listen 80;
    server_name api.internal.domain;
    status_zone api_vhost;

    location / {
        proxy_pass http://backend_pool;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        proxy_connect_timeout 5s;
        proxy_read_timeout 60s;
        proxy_next_upstream error timeout http_502 http_503;
    }
}
```

Подробнее: **[Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)** и **[Динамические upstreams в Angie](./dynamic_upstreams.md)**.

### Сценарий 4: Автоматическое получение и ротация TLS-сертификатов (ACME)

В отличие от Nginx, требующего сторонних утилит (Certbot, `acme.sh`), Angie содержит встроенный клиент ACME (RFC 8555). Модуль самостоятельно выполняет валидацию HTTP-01 без прерывания трафика и автоматически обновляет сертификаты в памяти:

```nginx
# /etc/angie/conf.d/acme_app.conf
# 1. Объявление ACME-клиента на глобальном уровне HTTP
acme_client letsencrypt {
    directory https://acme-v02.api.letsencrypt.org/directory;
    account_key /etc/angie/acme_account.key;
    renew 30d; # Продлевать за 30 дней до окончания
}

# 2. Автоматический прием HTTP-01 проверок и редирект на HTTPS
server {
    listen 80;
    server_name example.com www.example.com;

    # Активация перехвата /.well-known/acme-challenge/ в ядре Angie
    acme letsencrypt;

    location / {
        return 301 https://$host$request_uri;
    }
}

# 3. Защищенный виртуальный хост с автоматическим управлением сертификатом
server {
    listen 443 ssl;
    server_name example.com www.example.com;
    status_zone example_https;

    # Angie автоматически выпускает сертификат и обновляет его без reload
    acme letsencrypt;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;

    location / {
        root /var/www/example;
        index index.html;
    }
}
```

Подробнее: **[Автоматические TLS-сертификаты в Angie: модуль ACME](./angie_acme_module.md)**.

## Операции и команды

### Управление сервисом через systemd

```bash
# Проверка текущего состояния демона Angie
sudo systemctl status angie
# → Active: active (running) since Tue 2026-10-14 12:00:00 MSK; 4h 12min ago
# → Main PID: 12345 (angie)
# → Tasks: 5 (limit: 38407)
# → Memory: 28.4M

# Включение автозапуска и запуск сервиса
sudo systemctl enable --now angie
# → Created symlink /etc/systemd/system/multi-user.target.wants/angie.service → /lib/systemd/system/angie.service.

# Плавное перечитывание конфигурации (graceful reload)
sudo systemctl reload angie
# → Job for angie.service succeeded.

# Перезапуск сервиса (с разрывом соединений)
sudo systemctl restart angie

# Просмотр системных журналов сервиса в реальном времени
sudo journalctl -u angie -f --no-tail
```

### Валидация и инспекция конфигурации

```bash
# 1. Экспресс-тестирование синтаксиса конфигурации
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# 2. Тестирование альтернативного файла конфигурации
sudo angie -t -c /etc/angie/angie.conf.staging
# → angie: the configuration file /etc/angie/angie.conf.staging syntax is ok
# → angie: configuration file /etc/angie/angie.conf.staging test is successful

# 3. Полный дамп всей загруженной конфигурации (включая все include)
sudo angie -T | grep -E 'server_name|listen|status_zone'
# → listen 80;
# → server_name example.com;
# → status_zone example_https;

# 4. Проверка скомпилированной версии и параметров сборки
sudo angie -V
# → angie version: angie/1.12.2 (nginx/1.27.3)
# → built by gcc 12.2.0 (Debian 12.2.0-14)
# → built with OpenSSL 3.0.11 19 Sep 2023
# → TLS SNI support enabled
# → configure arguments: --prefix=/etc/angie ... --with-http_api_module --with-http_prometheus_module
```

### Сетевая диагностика соединений и сокетов

```bash
# 1. Проверка прослушиваемых портов процессами Angie
sudo ss -tlnp | grep angie
# → LISTEN 0 511   0.0.0.0:80    0.0.0.0:*  users:(("angie",pid=12346,fd=6),("angie",pid=12345,fd=6))
# → LISTEN 0 511   0.0.0.0:443   0.0.0.0:*  users:(("angie",pid=12346,fd=7),("angie",pid=12345,fd=7))
# → LISTEN 0 128 127.0.0.1:8888  0.0.0.0:*  users:(("angie",pid=12346,fd=8),("angie",pid=12345,fd=8))

# 2. Сводная статистика сокетов в ядре Linux
ss -s
# → Total: 1240
# → TCP:   892 (estab 310, closed 412, orphaned 10, timewait 160)

# 3. Проверка переполнения очередей сокетов (drop count)
ss -ltni 'sport = :80 or sport = :443'
# → State  Recv-Q Send-Q Local Address:Port  Peer Address:Port
# → LISTEN 0      511          0.0.0.0:80         0.0.0.0:*     skmem:(r0,rb131072,t0,tb16384,f0,bl0) drops:0
```

### Мониторинг и эксплуатационные запросы через API

```bash
# 1. Получение общего статуса Angie (версия, аптайм, поколение)
curl -s http://127.0.0.1:8888/status/angie/ | jq '{version: .version, uptime: .uptime_sec, generation: .generation}'
# → {
# →   "version": "1.12.2",
# →   "uptime_sec": 15120,
# →   "generation": 3
# → }

# 2. Получение списка и статусов серверных зон (status_zone)
curl -s http://127.0.0.1:8888/status/http/server_zones/ | jq 'keys'
# → [
# →   "api_vhost",
# →   "app_production",
# →   "example_https"
# → ]

# 3. Проверка состояния бэкендов в группе upstream
curl -s http://127.0.0.1:8888/status/http/upstreams/backend_pool/ | jq '.peers[] | {server: .server, state: .state, active: .active, requests: .requests}'
# → {
# →   "server": "10.10.1.11:8080",
# →   "state": "up",
# →   "active": 4,
# →   "requests": 15420
# → }
# → {
# →   "server": "10.10.1.13:8080",
# →   "state": "drain",
# →   "active": 1,
# →   "requests": 3401
# → }

# 4. Проверка сбора метрик Prometheus
curl -s http://127.0.0.1:8888/metrics | grep -E '^angie_http_requests_total' | head -n 3
# → angie_http_requests_total{status_zone="app_production",code="200"} 14210
# → angie_http_requests_total{status_zone="app_production",code="404"} 12
# → angie_http_requests_total{status_zone="app_production",code="500"} 1
```

### Управление процессами через сигналы

Мастер-процесс Angie принимает стандартные POSIX-сигналы:

| Сигнал | Синтаксис | Действие |
| :--- | :--- | :--- |
| `HUP` | `kill -HUP $(cat /run/angie.pid)` | Graceful reload: чтение конфигурации, запуск новых воркеров, мягкая остановка старых. |
| `QUIT` | `kill -QUIT $(cat /run/angie.pid)` | Graceful shutdown: дождаться завершения обработки текущих клиентских запросов и завершиться. |
| `TERM` / `INT` | `kill -TERM $(cat /run/angie.pid)` | Fast shutdown: немедленное принудительное завершение всех процессов. |
| `USR1` | `kill -USR1 $(cat /run/angie.pid)` | Переоткрытие файлов логов (используется при выполнении `logrotate`). |
| `USR2` | `kill -USR2 $(cat /run/angie.pid)` | Запуск нового master-процесса с новым бинарником (первый шаг бинарного обновления). |
| `WINCH` | `kill -WINCH $(cat /run/angie.pid.oldbin)` | Остановка воркеров старого master-процесса (второй шаг бинарного обновления). |

> **Zero-Downtime обновление бинарного файла:** При обновлении версии пакета или замене исполняемого файла Angie позволяет обновиться на лету без разрыва клиентских TCP-соединений через связку сигналов `USR2` -> `WINCH` -> `QUIT`. Пошаговый сценарий и алгоритм отката детально задокументированы в руководстве: **[Graceful Reload и Binary Upgrade в Angie](./angie-graceful-reload.md)**.

## Устранение неисправностей

### 1. Конфликт сетевых портов при установке или миграции

**Симптомы:** Сервис `angie` не запускается. В выводе `systemctl status angie` или `/var/log/angie/error.log` фиксируется ошибка:
`[emerg] ... bind() to 0.0.0.0:80 failed (98: Address already in use)`

**Диагностика:**

```bash
# Выявление процесса, удерживающего порт 80 или 443
sudo ss -tlnp 'sport = :80 or sport = :443'
# → LISTEN 0 511 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=1120,fd=6))
```

**Решение:**
1. Если на сервере остался ранее установленный Nginx или Apache — остановите и отключите его автозапуск:
   ```bash
   sudo systemctl stop nginx && sudo systemctl disable nginx
   sudo systemctl start angie
   # → Проверка: sudo systemctl is-active angie
   # → active
   ```
2. При параллельной работе Angie и Nginx (на этапе плавной миграции) разнесите их по разным IP-адресам интерфейсов через директиву `listen <ip>:80;` вместо `listen 80;`.

### 2. Изменения конфигурации не применяются после reload

**Симптомы:** Команда `systemctl reload angie` завершается успешно, но новые маршруты, сертификаты или заголовки не отдаются клиентам.

**Диагностика:**

```bash
# 1. Проверка синтаксиса файла на предмет незамеченных предупреждений
sudo angie -t
# → angie: configuration file /etc/angie/angie.conf test is successful

# 2. Проверка активных процессов и номеров поколений (generation)
ps aux | grep "angie: worker process"
# → angie     12346  0.0  0.5 ... angie: worker process #1 (is shutting down)
# → angie     15410  0.0  0.5 ... angie: worker process #2

# 3. Запрос текущего поколения мастер-процесса через Status API
curl -s http://127.0.0.1:8888/status/angie/ | jq .generation
# → 2
```

**Решение:**
*   Если старый воркер завис в состоянии `(is shutting down)`, это означает, что клиенты удерживают открытые WebSocket, gRPC или бесконечные HTTP-соединения (SSE).
*   Задайте таймаут принудительного завершения старых воркеров в глобальном блоке `angie.conf`:
    ```nginx
    worker_shutdown_timeout 15s;
    ```
*   Убедитесь, что вы редактируете конфигурацию именно в `/etc/angie/`, а не в `/etc/nginx/`.

### 3. Ошибки 502 Bad Gateway / 504 Gateway Timeout на бэкенде

**Симптомы:** Клиенты получают HTTP 502 (Bad Gateway) или 504 (Gateway Timeout).

**Диагностика:**

```bash
# 1. Анализ журнала ошибок Angie
grep -E 'connect\(\) failed|upstream timed out' /var/log/angie/error.log | tail -n 5
# → [error] 12346#0: *105 connect() to 10.10.1.11:8080 failed (111: Connection refused) while connecting to upstream
# → [error] 12346#0: *106 upstream timed out (110: Connection timed out) while reading response header from upstream

# 2. Проверка состояния пиров через API
curl -s http://127.0.0.1:8888/status/http/upstreams/backend_pool/ | jq '.peers[] | {server: .server, state: .state, fails: .fails}'
# → {"server": "10.10.1.11:8080", "state": "unreachable", "fails": 3}

# 3. Прямая проверка сетевой доступности узла бэкенда с хоста Angie
curl -Iv --connect-timeout 2 http://10.10.1.11:8080/health
# → curl: (7) Failed to connect to 10.10.1.11 port 8080: Connection refused
```

**Решение:**
*   **При 502 (Connection refused):** Приложение на бэкенде упало, слушает только `127.0.0.1` вместо нужного сетевого интерфейса, либо сетевой экран (iptables/nftables) блокирует трафик с IP-адреса Angie.
*   **При 502 (Permission denied на unix-сокете):** Проверьте права на сокет (`/run/app.sock`). Пользователь `angie` должен иметь права чтения и записи (`rw`).
*   **При 504 (Gateway Timeout):** Бэкенд перегружен медленными SQL-запросами или внешними вызовами. Увеличьте таймауты в `location`:
    ```nginx
    proxy_connect_timeout 5s;
    proxy_read_timeout 120s;
    proxy_send_timeout 120s;
    ```

### 4. Исчерпание лимитов файловых дескрипторов и соединений

**Симптомы:** В `error.log` появляются критические сообщения:
`[alert] ... 8192 worker_connections are not enough` или
`[crit] ... open() failed (24: Too many open files)`

**Диагностика:**

```bash
# 1. Проверка текущих лимитов процесса master
cat /proc/$(cat /run/angie.pid)/limits | grep "Max open files"
# → Max open files            1024                 1024                 files

# 2. Проверка системного лимита дескрипторов ядра Linux
sysctl fs.file-max
# → fs.file-max = 2097152
```

**Решение:**
1. Увеличьте лимит открытых файлов для worker-процессов в `/etc/angie/angie.conf`:
   ```nginx
   worker_rlimit_nofile 65535;
   events {
       worker_connections 16384;
   }
   ```
2. Увеличьте лимиты systemd для юнита `angie.service`:
   ```bash
   sudo systemctl edit angie
   ```
   Добавьте блок:
   ```ini
   [Service]
   LimitNOFILE=65535
   ```
   Примените изменения:
   ```bash
   sudo systemctl daemon-reload && sudo systemctl restart angie
   ```

### 5. Логи не пишутся в новые файлы после ротации (logrotate)

**Симптомы:** Утилита `logrotate` сжала старые логи (появились `access.log.1.gz`), но новые записи продолжают писаться в переименованный старый файл дескриптора либо файл `access.log` остается пустым (размер 0 байт).

**Диагностика:**

```bash
# Проверка открытия файла логов процессами Angie
lsof -p $(cat /run/angie.pid) | grep log
# → angie 12345 root 2w REG 254,1 0 131075 /var/log/angie/access.log (deleted)
```

**Решение:**
Angie держит дескрипторы открытых файлов логов и требует явного сигнала `USR1` для переоткрытия файлов после перемещения. Проверьте конфигурационный файл ротации `/etc/logrotate.d/angie`:

```text
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
```

Проверьте выполнение ротации вручную:
```bash
sudo logrotate -f /etc/logrotate.d/angie
# → Проверка переоткрытия:
kill -USR1 $(cat /run/angie.pid)
```

Подробнее: **[Логирование в Angie](./angie_logging.md)**.

## Лучшие практики

### Структурирование конфигурации в продакшене

*   **Модульность через каталоги:** Никогда не объединяйте виртуальные хосты в один файл `angie.conf`. Используйте каталоги:
    *   `/etc/angie/conf.d/*.conf` — конфигурации виртуальных хостов HTTP/HTTPS.
    *   `/etc/angie/stream.d/*.conf` — конфигурации L4 TCP/UDP проксирования.
    *   `/etc/angie/snippets/` — переиспользуемые фрагменты настроек (заголовки безопасности, параметры SSL, настройки upstream).
*   **Контроль версий и автоматическая проверка:** Храните конфигурацию `/etc/angie` в системе Git. Включайте обязательную валидацию `angie -t` в pre-commit хуки и CI/CD пайплайны перед доставкой на серверы.
*   **Явное именование зон:** Всегда указывайте уникальные имена для зон разделяемой памяти: `status_zone <domain>_zone;`, `zone <upstream_name>_zone 512k;`. Это упрощает фильтрацию метрик в Prometheus и дашбордах Grafana.

### Hardening и безопасность для Sysadmin/DevOps

*   **Непривилегированный запуск:** Рабочие процессы должны выполняться исключительно от системного пользователя `angie`. Директива `user angie;` обязательна в `main`-контексте.
*   **Сокрытие версии ПО:** Директива `server_tokens off;` отключает вывод версии сервера в заголовке ответа `Server` и на страницах стандартных ошибок (404, 502, 500).
*   **Изоляция административных эндпоинтов:** Блоки с директивами `api`, `prometheus` и статической консолью `angie-console-light` должны быть привязаны к `127.0.0.1` или внутреннему VPN/management-интерфейсу с жестким ограничением `allow <ip>; deny all;`.
*   **Отклонение некорректных хостов:** Блок `server` с `listen 80 default_server; server_name _; return 444;` пресекает попытки сканирования периметра по прямому обращению к IP-адресу без указания зарегистрированного доменного имени.

### Тюнинг ядра Linux под высокие сетевые нагрузки

Для обеспечения надежной работы Angie под нагрузкой на физических серверах и виртуальных машинах настройте параметры сетевого стека ядра Linux в `/etc/sysctl.d/99-angie-performance.conf`:

```ini
# Максимальный размер очереди не принятых соединений (backlog сокета)
net.core.somaxconn = 65535

# Максимальное количество соединений в очереди SYN_RECV
net.ipv4.tcp_max_syn_backlog = 65535

# Диапазон локальных эфемерных портов для исходящих соединений к бэкендам
net.ipv4.ip_local_port_range = 1024 65535

# Повторное использование TCP-сокетов в состоянии TIME_WAIT для исходящих подключений
net.ipv4.tcp_tw_reuse = 1

# Максимальное число файловых дескрипторов в операционной системе
fs.file-max = 2097152

# Увеличение размеров буферов сокетов для передачи тяжелого контента
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
```

Примените параметры ядра:
```bash
sudo sysctl --system
# → net.core.somaxconn = 65535
# → net.ipv4.tcp_max_syn_backlog = 65535
# → net.ipv4.ip_local_port_range = 1024 65535
# → net.ipv4.tcp_tw_reuse = 1
# → fs.file-max = 2097152
```

### SRE & Эксплуатация

*   **Четыре золотых сигнала SRE (Golden Signals):**
    *   **Latency (Задержка):** отслеживайте метрики времени ответа бэкенда через `$upstream_response_time` в логах и модуль `metrics` (гистограммы времени ответа).
    *   **Traffic (Трафик):** мониторьте суммарный RPS через счетчики `status_zone` (`requests`).
    *   **Errors (Ошибки):** настраивайте алерты на долю кодов ответов 5xx (`responses.5xx / requests > 0.01`).
    *   **Saturation (Насыщенность):** контролируйте утилизацию активных соединений относительно `worker_connections` и доступную память в `zone`.
*   **Использование пула Keepalive к апстримам:** Всегда настраивайте директиву `keepalive 32;` (или выше) в блоках `upstream`, а также проксируйте заголовки `proxy_http_version 1.1;` и `proxy_set_header Connection "";`. Это устраняет постоянное рукопожатие TCP (TCP 3-way handshake) и экономит миллисекунды задержки при каждом обращении к приложению.
*   **Бесшовный вывод узлов из ротации:** При проведении регламентных работ на серверах приложений используйте параметр `drain` у директивы `server` в блоке `upstream`. Это позволяет текущим пользователям завершить оформление заказов и сессий на обслуживаемом сервере, пока новый трафик перераспределяется на соседние бэкенды.

## Дополнительная информация

### Сравнение путей Angie и Nginx

Для системных администраторов и инженеров DevOps при параллельной установке или миграции:

| Компонент / Ресурс | Путь в Angie | Путь в Nginx |
| :--- | :--- | :--- |
| Главный конфигурационный файл | `/etc/angie/angie.conf` | `/etc/nginx/nginx.conf` |
| Каталог конфигураций HTTP | `/etc/angie/conf.d/` | `/etc/nginx/conf.d/` |
| Каталог конфигураций Stream (L4) | `/etc/angie/stream.d/` | `/etc/nginx/stream.d/` |
| Динамические модули | `/usr/lib/angie/modules/` | `/usr/lib/nginx/modules/` |
| Исполняемый файл | `/usr/sbin/angie` | `/usr/sbin/nginx` |
| Журналы доступа и ошибок | `/var/log/angie/` | `/var/log/nginx/` |
| Каталог кэша прокси | `/var/cache/angie/` | `/var/cache/nginx/` |
| PID-файл мастер-процесса | `/run/angie.pid` | `/run/nginx.pid` |
| Хранилище сертификатов ACME | `/var/lib/angie/acme/` | Не поддерживается нативно |
| Системный юнит systemd | `/lib/systemd/system/angie.service` | `/lib/systemd/system/nginx.service` |

### См. также

*   **[Установка Angie](./angie_installation.md)** — пакетная установка для Linux-дистрибутивов, сборка модулей, ЗПС.
*   **[Миграция с Nginx на Angie](./migration_from_nginx.md)** — практическое руководство по переносу настроек без простоя.
*   **[Graceful Reload и Binary Upgrade](./angie-graceful-reload.md)** — детальный разбор сигналов и процедура обновления исполняемого файла без разрыва соединений.
*   **[Минимальная продакшен-конфигурация](./angie-baseline-config.md)** — базовый эталон настройки рабочего веб-сервера.
*   **[Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)** — алгоритмы балансировки, веса, session persistence.
*   **[L4 балансировка и проксирование (Stream)](./l4_balancing_and_proxying.md)** — TCP/UDP проксирование, SNI-маршрутизация.
*   **[Динамические upstreams в Angie](./dynamic_upstreams.md)** — автоматическое управление пулом серверов и Service Discovery.
*   **[Мониторинг Angie — основные концепции](./angie_monitoring/angie_monitoring_concepts.md)** — архитектура сбора телеметрии.
*   **[Мониторинг Angie — работа через API](./angie_monitoring/angie_monitoring_api.md)** — использование REST API и структуры JSON.
*   **[Нативный экспорт в Prometheus](./angie_monitoring/angie_monitoring_prometheus.md)** — шаблоны метрик и интеграция с Prometheus/Grafana.
*   **[Веб-консоль мониторинга](./angie_monitoring/angie_monitoring_console.md)** — развертывание и настройка `angie-console-light`.
*   **[Автоматические TLS-сертификаты: модуль ACME](./angie_acme_module.md)** — автоматизация выпуска и ротации сертификатов Let's Encrypt.
*   **[Логирование в Angie](./angie_logging.md)** — расширенные форматы логов, ротация и буферизация.
*   **[Настройка TLS в Angie](./angie_tls_setup.md)** — протоколы TLS 1.2/1.3, современные шифры, OCSP stapling.
*   **[Настройка Angie для высоких нагрузок](./High_Load/index.md)** — архитектурные паттерны масштабирования под экстремальный RPS.
*   **[DNS over HTTPS (DoH) в Angie](./angie_doh_module.md)** — настройка DoH-резолвера и криптографическая безопасность DNS.
*   **[Контроль доступа в Angie](./angie_access_control.md)** — фильтрация по IP, базовая аутентификация, subrequest auth.
*   **[Обзор Nginx](../Nginx/Core/nginx_overview.md)** — базовая архитектура и концепции Nginx.

