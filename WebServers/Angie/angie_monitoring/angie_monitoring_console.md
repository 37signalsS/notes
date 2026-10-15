# Мониторинг Angie — Console Light и API

**Актуально для:** Angie 1.12.x

## Определения

**Angie Console Light** (также известный как **Console Lite**) — официальный встроенный веб-интерфейс для интерактивного мониторинга метрик Angie в режиме реального времени. Он представляет собой одностраничное веб-приложение (Single Page Application, SPA), визуализирующее данные из встроенного HTTP API, что позволяет дежурному инженеру или системному администратору оперативно оценивать состояние сервера, виртуальных хостов и групп бэкендов без развертывания тяжелых внешних систем сбора данных.

**HTTP API мониторинга** — программный REST-подобный интерфейс (модуль `ngx_http_api_module`), предоставляющий оперативную телеметрию сервера в формате JSON. Интерфейс возвращает иерархические структуры данных о входящих запросах, активных соединениях, состоянии и задержках апстримов, эффективности кэша, использовании зон разделяемой памяти и текущих конфигурационных файлах.

**Status Zone (Зона статуса)** — именованный сегмент разделяемой памяти (Shared Memory), выделяемый для хранения атомарных счетчиков и структур мониторинга. Директива `status_zone` активирует учет метрик для конкретных виртуальных серверов, локаций или L4-потоков (Stream).

**Shared Memory (Разделяемая память)** — область оперативной памяти, совместно используемая master-процессом и всеми рабочими процессами (worker processes) Angie. Служит фундаментом для сбора телеметрии: каждый воркер инкрементирует счетчики в общей памяти без межпроцессных блокировок операционной системы, обеспечивая целостную картину состояния сервера.

**Slab Allocator (Аллокатор slab)** — механизм управления разделяемой памятью в Angie, оперирующий страницами памяти и пулами фиксированных слотов (chunks). Выделяет память под структуры `status_zone`, `limit_req_zone`, `limit_conn_zone` и `upstream zone`. Исчерпание свободных слотов в slab-зоне приводит к ошибкам аллокации и потере возможности регистрации новых метрик.

**CORS (Cross-Origin Resource Sharing)** — стандарт безопасности веб-браузеров, регламентирующий выполнение запросов между различными источниками (Origin: протокол, домен, порт). Если статические файлы Console Light и эндпоинты API обслуживаются на разных портах или доменах, требуется явная передача CORS-заголовков (`Access-Control-Allow-Origin`), иначе браузер блокирует загрузку телеметрии.

**Polling Interval (Интервал опроса)** — период времени между последовательными фоновыми запросами Console Light к API для обновления дашборда. По умолчанию составляет приблизительно 1 секунду, обеспечивая отображение динамики метрик в режиме близком к реальному времени.

**Content Security Policy (CSP)** — заголовок HTTP-ответа (`Content-Security-Policy`), определяющий доверенные источники скриптов, стилей и сетевых подключений (`connect-src`). Защищает административный интерфейс мониторинга от межсайтового скриптинга (XSS) и подмены целевого API.

**SRE Golden Signals в веб-консоли** — ключевые метрики надежности сервиса, непосредственно отображаемые в интерфейсе: задержка (Latency — время ответа бэкендов в Upstreams), трафик (Traffic — RPS и объемы переданных байт в HTTP/Stream Zones), ошибки (Errors — частота кодов 4xx/5xx и недоступность пиров), насыщенность (Saturation — загрузка соединений и заполнение slab-зон памяти).

## Базовые концепции

### Архитектура взаимодействия компонентов

Console Light функционирует исключительно как клиентское приложение. Браузер загружает статические ресурсы (HTML, JavaScript, CSS) с веб-сервера Angie и инициирует циклический опрос локальных эндпоинтов API.

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                             Web Browser (Client)                            │
│  ┌────────────────────────┐                   ┌──────────────────────────┐  │
│  │   Console Light SPA    │──(Fetch API /)───>│  DOM Charts & Dashboards │  │
│  │   (HTML5, JS, CSS)     │                   │  (Near Real-Time Render) │  │
│  └────────────────────────┘                   └──────────────────────────┘  │
└──────────────────────▲──────────────────────────────│───────────────────────┘
                       │ 1. Load static files         │ 2. Polling loop (~1s)
                       │    (index.html, bundles)     │    GET /console/api/...
┌──────────────────────┴──────────────────────────────▼───────────────────────┐
│                              Angie Server                                   │
│                                                                             │
│  ┌────────────────────────┐                   ┌──────────────────────────┐  │
│  │   Static File Engine   │                   │    ngx_http_api_module   │  │
│  │   alias /usr/share/... │                   │    api /status/;         │  │
│  └────────────────────────┘                   └─────────────┬────────────┘  │
│                                                             │               │
│                                            Reads metrics via│atomic ops     │
│                                                             ▼               │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                   Shared Memory (Slab Allocator)                      │  │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────────┐  │  │
│  │  │   status_zone    │  │  upstream zone   │  │ limit / cache zones │  │  │
│  │  └──────────────────┘  └──────────────────┘  └─────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                     ▲                                       ▲               │
│                     │ Writes atomic counters                │               │
│         ┌───────────┴───────────┐               ┌───────────┴───────────┐   │
│         │   Worker Process 1    │               │    Worker Process N   │   │
│         └───────────────────────┘               └───────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Жизненный цикл обработки запроса мониторинга:**
1. Браузер администратора обращается к локации интерфейса (например, `http://192.168.1.10:8888/console/`) и загружает статический файл `index.html` вместе со скомпилированными скриптами и стилями из каталога `/usr/share/angie-console-light/html/`.
2. Клиентский JavaScript инициализирует компоненты дашборда и запускает асинхронный цикл опроса (polling loop) со стандартным интервалом ~1 секунда.
3. Браузер параллельно выполняет HTTP GET-запросы к относительным эндпоинтам API: `/console/api/angie/`, `/console/api/connections/`, `/console/api/http/server_zones/`, `/console/api/http/upstreams/`, `/console/api/http/caches/` и `/console/api/slabs/`.
4. Рабочий процесс Angie, принявший запрос к `location /console/api/`, с помощью директивы `api /status/;` сопоставляет запрошенный URI с виртуальным деревом API модуля `ngx_http_api_module`.
5. Модуль API считывает текущие значения структур и счетчиков из разделяемой памяти, сериализует их в JSON и отправляет клиенту с заголовком `Content-Type: application/json`.
6. Frontend Console Light вычисляет производные показатели (текущий RPS, динамику ошибок, средний RTT) и перерисовывает элементы пользовательского интерфейса без перезагрузки страницы.

### Маршрутизация запросов и сопряжение со встроенным API

Ключевой задачей при интеграции Console Light является связывание статических файлов интерфейса и динамического обработчика API.

В архитектуре Angie директива `api [path];` работает аналогично директиве `alias`:
- Если задан параметр `path` (например, `api /status/;`), то префикс URI из окружающего блока `location` заменяется на указанный путь в виртуальном дереве API.
- Если клиент обращается по адресу `/console/api/http/server_zones/`, а в локации задано `location /console/api/ { api /status/; }`, запрос передается в узел `/status/http/server_zones/`.
- Размещение статики и вложенного эндпоинта API внутри единого блока `server` исключает необходимость отправки cross-origin запросов (CORS), повышая стабильность работы браузера и снижая накладные расходы на preflight-запросы `OPTIONS`.

### Структура интерфейса Console Light

Интерфейс структурирован по функциональным модулям, каждый из которых агрегирует телеметрию соответствующей подсистемы:

- **HTTP Zones:** подробный срез по виртуальным хостам и локациям: интенсивность входящих запросов, распределение ответов по статус-кодам (1xx, 2xx, 3xx, 4xx, 5xx), объемы принятого и отправленного сетевого трафика.
- **HTTP Upstreams:** состояние пулов серверов бэкенда: статус каждого пира (`up`, `down`, `unavail`), установленные веса, текущее число активных и inflight-соединений, время отклика (`response_time`), число зафиксированных сбоев (`fails`) и статистика пулов keepalive.
- **Caches:** эффективность использования дискового кэша (`proxy_cache`): распределение запросов по состояниям (`hit`, `miss`, `stale`, `updating`, `revalidated`, `expired`, `bypass`), текущий объем кэшированных данных и заполнение памяти ключей.
- **Shared Zones & Slabs:** диагностика slab-аллокатора разделяемой памяти: распределение страниц памяти, общее и свободное количество слотов, число отказов аллокации (fails).
- **Stream:** метрики подсистемы L4-проксирования (TCP и UDP): количество клиентских сессий, байты трафика, статусы доступности стрим-бэкендов.
- **Configs:** встроенный просмотрщик активных конфигурационных файлов, загруженных в память master-процессом (требует активации директивы `api_config_files on;`).

### Нагрузочная модель опроса (SRE-анализ)

Использование polling-модели с частотой 1 Гц накладывает определенные эксплуатационные ограничения, которые необходимо учитывать при проектировании инфраструктуры:

1. **Генерация локального трафика:** одна открытая вкладка браузера с Console Light генерирует от 5 до 10 запросов в секунду к внутреннему API. Если консоль открыта на мониторах дежурной смены у 10 инженеров, фоновая нагрузка на сервер составит 50–100 RPS.
2. **Накладные расходы на логирование:** если запросы к `/console/api/` записываются в стандартный `access.log`, файл журнала быстро заполняется служебным мусором, расходуя дисковый ввод-вывод (I/O). Для локации API обязательно требуется отключать логирование (`access_log off;`) или выносить его в отдельный кольцевой журнал.
3. **Keepalive-соединения браузера:** веб-браузер повторно использует постоянные TCP/TLS-соединения для циклического опроса API. Параметры `keepalive_requests` и `keepalive_timeout` на сервере мониторинга должны быть достаточными, чтобы предотвратить постоянное переустановление TCP-сессий (рекомендуется `keepalive_requests 10000;`).

### Эшелонированная безопасность плоскости управления

Консоль мониторинга предоставляет детальную информацию о внутренней структуре сервисов, конфигурационных путях, IP-адресах бэкендов и профиле трафика. Публичный доступ к этим данным создает критический вектор для сбора разведданных злоумышленниками.

**Принципы изоляции Management Plane:**
- **Сетевое разделение:** интерфейс мониторинга должен прослушивать выделенный локальный сокет (`127.0.0.1:8888`) либо изолированный интерфейс административной сети (Out-of-band / OAM VLAN), недоступный для клиентского сегмента.
- **Списки контроля доступа (L3/L4 ACL):** применение директив `allow` и `deny` на уровне блока `server` для фильтрации подсетей администраторов.
- **Криптографическая защита:** обязательное использование TLS при маршрутизации трафика через межсетевые экраны или корпоративный VPN.
- **Аутентификация:** ограничение доступа с помощью HTTP Basic Auth (`auth_basic`) с надежными хэшами паролей (bcrypt или SHA-512) либо интеграция с корпоративным SSO на внешнем шлюзе.
- **Защита заголовками:** изоляция веб-панели от встраивания во фреймы (`X-Frame-Options: DENY`) и строгое ограничение сетевых вызовов скрипта через директиву CSP `connect-src 'self'`.

## Практические сценарии

### Предпосылки (Prerequisites)

Для развертывания Console Light и модуля API требуются:
- **Операционная система:** Linux (Debian 12, Ubuntu 22.04/24.04 LTS, RHEL 9 / AlmaLinux 9 / Rocky Linux 9).
- **Пакет веб-сервера:** установленный `angie` версии 1.12.x или выше.
- **Привилегии:** права суперпользователя (`sudo` или `root`) для установки пакетов и редактирования конфигураций.
- **Сетевой порт:** свободный TCP-порт для интерфейса управления (по умолчанию `8888/TCP`).
- **Брандмауэр:** настроенный межсетевой экран (`ufw` или `firewalld`), разрешающий входящие подключения к порту мониторинга только из доверенных подсетей.

### Сценарий 1: Установка пакета `angie-console-light`

Пакет `angie-console-light` содержит исключительно статическую сборку SPA-приложения и устанавливается из официального репозитория Angie.

```bash
# 1. Проверка наличия официального репозитория Angie в системе
# Для Debian/Ubuntu:
apt-cache policy angie-console-light
# → angie-console-light:
# →   Candidate: 1.3.0-1~noble
# →   Version table:
# →  *** 1.3.0-1~noble 500

# Для RHEL/AlmaLinux/Rocky Linux:
dnf info angie-console-light
# → Name         : angie-console-light
# → Version      : 1.3.0
# → Release      : 1.el9

# 2. Установка пакета консоли
# На Debian/Ubuntu:
sudo apt-get update
sudo apt-get install -y angie-console-light

# На RHEL/AlmaLinux/Rocky Linux:
sudo dnf install -y angie-console-light

# 3. Валидация установленных файлов статики
ls -la /usr/share/angie-console-light/html/
# → total 48
# → drwxr-xr-x 3 root root  4096 Oct 14 10:00 .
# → drwxr-xr-x 3 root root  4096 Oct 14 10:00 ..
# → -rw-r--r-- 1 root root  1240 Oct 14 10:00 index.html
# → drwxr-xr-x 5 root root  4096 Oct 14 10:00 static
```

**Особенности пакета:**
- Статические файлы размещаются в каталоге `/usr/share/angie-console-light/html/`.
- Пакет не создает виртуальных хостов и не модифицирует существующую конфигурацию Angie автоматически — настройка server-блока выполняется системным администратором вручную.

### Сценарий 2: Развертывание консоли на изолированном порту управления

Базовый сценарий развертывания выделяет отдельный сетевой порт для плоскости управления (Management Plane). Это полностью изолирует телеметрию от клиентского трафика и предотвращает влияние тяжелых запросов мониторинга на публичный пул соединений.

Создайте файл конфигурации `/etc/angie/http.d/management.conf`:

```nginx
server {
    listen 127.0.0.1:8888;
    listen 192.168.1.10:8888;
    server_name monitor.internal;

    # Списки доступа L3: разрешаем только локалхост и доверенную подсеть инженеров
    allow 127.0.0.1;
    allow 192.168.1.0/24;
    deny all;

    # Оптимизация постоянных соединений для активного опроса браузером
    keepalive_requests 10000;
    keepalive_timeout 75s;

    # Локация статических файлов Console Light
    location /console/ {
        alias /usr/share/angie-console-light/html/;
        index index.html;

        # Кэширование статических ассетов (JS/CSS) браузером
        location ~* /console/static/(.+\.(?:js|css|png|svg|ico|woff2?))$ {
            alias /usr/share/angie-console-light/html/static/$1;
            expires 7d;
            add_header Cache-Control "public, no-transform";
        }

        # Эндпоинт API для взаимодействия с SPA консоли
        location /console/api/ {
            api /status/;
            access_log off; # Отключаем логирование частого циклического опроса
        }
    }

    # Прямой защищенный эндпоинт API для внутренних скриптов и систем сбора
    location /status/ {
        api /status/;
        access_log off;
        allow 127.0.0.1;
        deny all;
    }

    # Редирект с корня на дашборд консоли
    location = / {
        return 301 /console/;
    }
}
```

**Валидация и ввод в эксплуатацию:**

```bash
# 1. Проверка синтаксиса конфигурации Angie
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# 2. Применение изменений без разрыва активных клиентских соединений
sudo angie -s reload

# 3. Проверка прослушивания порта управления
ss -tlnp | grep 8888
# → LISTEN 0 511 127.0.0.1:8888    0.0.0.0:* users:(("angie",pid=14201,fd=8),("angie",pid=14202,fd=8))
# → LISTEN 0 511 192.168.1.10:8888 0.0.0.0:* users:(("angie",pid=14201,fd=9),("angie",pid=14202,fd=9))

# 4. Проверка отдачи HTML-интерфейса консоли
curl -s -I http://127.0.0.1:8888/console/ | head -n 4
# → HTTP/1.1 200 OK
# → Server: Angie/1.12.3
# → Content-Type: text/html
# → Content-Length: 1240

# 5. Проверка сопряжения консоли с API через внутренний путь
curl -sf http://127.0.0.1:8888/console/api/angie/ | jq '{version: .version, generation: .generation}'
# → {
# →   "version": "1.12.3",
# →   "generation": 1
# → }
```

### Сценарий 3: Защита консоли — TLS, Basic Auth и Content Security Policy

При необходимости доступа к дашборду через незащищенные каналы связи, корпоративный Wi-Fi или VPN-сеть обязательна настройка шифрования TLS, базовой аутентификации и защитных HTTP-заголовков.

```bash
# 1. Генерация файла учетных записей администраторов с хэшированием SHA-512 или bcrypt
# Используем встроенный openssl для создания безопасного хэша
PASS_HASH=$(openssl passwd -6 "SuperSecretAdminPass123!")
echo "ops_admin:${PASS_HASH}" | sudo tee /etc/angie/console.htpasswd
# Установка строгих прав доступа на файл паролей
sudo chmod 640 /etc/angie/console.htpasswd
sudo chown root:angie /etc/angie/console.htpasswd

# 2. Проверка содержимого файла учетных данных
head -n 1 /etc/angie/console.htpasswd
# → ops_admin:$6$rounds=5000$...
```

Конфигурация защищенного виртуального хоста `/etc/angie/http.d/secure_management.conf`:

```nginx
server {
    listen 192.168.1.10:8443 ssl;
    http2 on;
    server_name monitor.corp.local;

    # Параметры сертификата и ключа
    ssl_certificate     /etc/angie/ssl/monitor.crt;
    ssl_certificate_key /etc/angie/ssl/monitor.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5:!RC4;
    ssl_prefer_server_ciphers on;
    ssl_session_cache   shared:SSL_CONSOLE:2m;
    ssl_session_timeout 1h;

    # Списки доступа на уровне сети
    allow 192.168.1.0/24;
    allow 10.100.0.0/16;
    deny all;

    # Защитные HTTP-заголовки
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:;" always;

    # Базовая аутентификация для всех ресурсов сервера
    auth_basic "Restricted Angie Control Plane";
    auth_basic_user_file /etc/angie/console.htpasswd;

    location /console/ {
        alias /usr/share/angie-console-light/html/;
        index index.html;

        location /console/api/ {
            api /status/;
            access_log off;
        }
    }

    location = / {
        return 301 /console/;
    }
}
```

**Валидация безопасности:**

```bash
# 1. Запрос без аутентификации (ожидается 401 Unauthorized)
curl -s -I -k https://192.168.1.10:8443/console/ | head -n 3
# → HTTP/2 401
# → server: Angie/1.12.3
# → www-authenticate: Basic realm="Restricted Angie Control Plane"

# 2. Запрос с корректными учетными данными
curl -s -k -u "ops_admin:SuperSecretAdminPass123!" https://192.168.1.10:8443/console/api/angie/ | jq .version
# → "1.12.3"

# 3. Проверка блокировки неразрешенного IP (с тестового внешнего хоста)
curl -s -k https://192.168.1.10:8443/console/
# → <html>
# → <head><title>403 Forbidden</title></head>
# → ...
```

### Сценарий 4: Конфигурация комплексного мониторинга объектов Angie

Console Light может визуализировать только те компоненты Angie, для которых в оперативной памяти явно выделены сегменты зон статуса. Если директивы `status_zone` или `zone` опущены, вкладки интерфейса останутся пустыми.

Конфигурация инфраструктуры сервисов в `/etc/angie/angie.conf` и `/etc/angie/http.d/apps.conf`:

```nginx
http {
    # 1. Активация встроенного просмотрщика файлов конфигурации в консоли
    api_config_files on;

    # 2. Настройка зон кэширования для мониторинга Cache Hit Ratio
    proxy_cache_path /var/cache/angie/main 
                     levels=1:2 
                     keys_zone=cache_frontend:10m 
                     max_size=1g 
                     inactive=60m;

    # 3. Настройка зон лимитирования запросов и соединений
    limit_req_zone $binary_remote_addr zone=req_rate_limit:10m rate=100r/s;
    limit_conn_zone $binary_remote_addr zone=conn_concurrency_limit:10m;

    # 4. Пул бэкендов HTTP с обязательным объявлением разделяемой зоны
    upstream cluster_payment_api {
        zone cluster_payment_api 256k; # Размер зоны для хранения состояния пиров
        server 10.0.10.11:8080 weight=5 max_fails=3 fail_timeout=10s;
        server 10.0.10.12:8080 weight=5 max_fails=3 fail_timeout=10s;
        server 10.0.10.13:8080 backup;
        
        keepalive 32; # Пул постоянных соединений с бэкендами
    }

    # 5. Виртуальный хост с детализацией по серверу и локациям
    server {
        listen 80;
        server_name api.company.local;

        # Именованная зона статуса для всего виртуального хоста
        status_zone vhost_payment_frontend;

        location / {
            limit_req zone=req_rate_limit burst=20 nodelay;
            limit_conn conn_concurrency_limit 50;

            proxy_pass http://cluster_payment_api;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_http_version 1.1;
            proxy_set_header Connection "";

            proxy_cache cache_frontend;
            proxy_cache_valid 200 302 10m;
        }

        # Отдельная зона статуса для критической локации выгрузки отчетов
        location /reports/ {
            status_zone loc_payment_reports;
            proxy_pass http://cluster_payment_api;
        }
    }
}

# 6. Мониторинг L4 TCP/UDP стримов
stream {
    upstream pgsql_cluster {
        zone pgsql_cluster 128k;
        server 10.0.20.1:5432 weight=1;
        server 10.0.20.2:5432 weight=1;
    }

    server {
        listen 15432;
        status_zone stream_pgsql_proxy;
        proxy_pass pgsql_cluster;
    }
}
```

**Проверка видимости объектов в API и Console Light:**

```bash
# Применение обновленной структуры сервисов
sudo angie -s reload

# 1. Проверка регистрации HTTP зон статуса
curl -sf http://127.0.0.1:8888/status/http/server_zones/ | jq 'keys'
# → [
# →   "vhost_payment_frontend"
# → ]

# 2. Проверка регистрации локационной зоны
curl -sf http://127.0.0.1:8888/status/http/location_zones/ | jq 'keys'
# → [
# →   "loc_payment_reports"
# → ]

# 3. Проверка состояния пула серверов в апстриме
curl -sf http://127.0.0.1:8888/status/http/upstreams/cluster_payment_api/ | jq '.peers | keys'
# → [
# →   "10.0.10.11:8080",
# →   "10.0.10.12:8080",
# →   "10.0.10.13:8080"
# → ]

# 4. Проверка метрик кэша
curl -sf http://127.0.0.1:8888/status/http/caches/cache_frontend/ | jq '{size: .size, max_size: .max_size}'
# → {
# →   "size": 0,
# →   "max_size": 1073741824
# → }

# 5. Проверка стрим-зоны
curl -sf http://127.0.0.1:8888/status/stream/server_zones/ | jq 'keys'
# → [
# →   "stream_pgsql_proxy"
# → ]
```

### Сценарий 5: Развертывание за обратным прокси (Reverse Proxy / Bastion)

В корпоративных инфраструктурах доступ к дашбордам узлов Angie часто организуется через централизованный реверс-прокси или bastion-сервер. В этом случае Console Light должна отдаваться по вложенному префиксу (например, `/nodes/node01/console/`).

Конфигурация центрального шлюза проксирования:

```nginx
# Конфигурация на центральном шлюзе мониторинга (Gateway)
server {
    listen 443 ssl;
    server_name noc.corp.local;

    ssl_certificate     /etc/ssl/noc.crt;
    ssl_certificate_key /etc/ssl/noc.key;

    # Проксирование к локальной Console Light целевого узла node01
    location /nodes/node01/console/ {
        proxy_pass http://192.168.1.10:8888/console/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Буферизация и постоянные соединения к управляющему сокету
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_read_timeout 60s;
    }
}
```

**Особенности интеграции с шлюзом:**
- Обязательно соблюдайте парность замыкающих слэшей (`/nodes/node01/console/` → `...:8888/console/`), чтобы `proxy_pass` корректно выполнял нормализацию URI без подстановки паразитных путей.
- Так как JavaScript-код Console Light использует относительные ссылки для опроса API (`api/...`), запросы автоматически адресуются к `/nodes/node01/console/api/...`, прозрачно транслируясь шлюзом на узел Angie.

### Сценарий 6: Управление жизненным циклом через systemd и контроль версий конфигурации

В практике системного администрирования важно четко понимать разницу между операциями перезапуска (`systemctl restart`) и мягкой перезагрузки (`systemctl reload`):

1. **Мягкая перезагрузка (`reload` / `SIGHUP`):**
   - Содержимое разделяемой памяти (все счетчики запросов, байт, кодов ошибок в `status_zone`) **сохраняется**.
   - Поле `generation` в объекте `/status/angie/` инкрементируется на 1.
   - Master-процесс запускает новый пул worker-процессов с обновленными параметрами, а старые воркеры плавно завершают активные соединения (graceful shutdown).
2. **Полный перезапуск (`restart` / `SIGTERM` + `SIGSTART`):**
   - Все зоны разделяемой памяти полностью уничтожаются и аллоцируются заново.
   - Все накопленные исторические метрики с момента старта сбрасываются в ноль.
   - Значение `generation` сбрасывается в единицу (`1`).

```bash
# 1. Проверка текущего поколения конфигурации перед reload
curl -sf http://127.0.0.1:8888/status/angie/ | jq '{generation: .generation, load_time: .load_time}'
# → {
# →   "generation": 3,
# →   "load_time": "2026-10-14T08:30:00Z"
# → }

# 2. Выполнение безопасной перезагрузки через systemd
sudo systemctl reload angie

# 3. Валидация успешного перехода на новую ревизию
curl -sf http://127.0.0.1:8888/status/angie/ | jq '{generation: .generation, load_time: .load_time}'
# → {
# →   "generation": 4,
# →   "load_time": "2026-10-14T10:15:22Z"
# → }

# 4. Проверка отсутствия "зависших" старых воркеров (old worker process)
ps aux | grep "[a]ngie: worker process"
# → angie    15201  0.1  0.4  52340 34100 ?  S    10:15   0:00 angie: worker process
# → angie    15202  0.1  0.4  52340 34112 ?  S    10:15   0:00 angie: worker process
```

### Сценарий 7: Автоматизированный скрипт мониторинга доступности Console Light

Для интеграции узла в системы локального мониторинга (например, вызов через кастомный check-агент) используется скрипт валидации доступности как статических файлов консоли, так и работоспособности обработчика API.

Создайте исполняемый скрипт `/usr/local/bin/check_angie_console.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Конфигурация эндпоинтов проверки
BASE_URL="http://127.0.0.1:8888"
CONSOLE_URL="${BASE_URL}/console/"
API_URL="${BASE_URL}/console/api/angie/"
TIMEOUT=3

# 1. Проверка доступности статического интерфейса
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "${TIMEOUT}" "${CONSOLE_URL}" || echo "000")
if [[ "${HTTP_CODE}" != "200" ]]; then
    echo "CRITICAL: Console Light static UI is unavailable (HTTP ${HTTP_CODE})"
    exit 2
fi

# 2. Проверка доступности сопряженного API
API_PAYLOAD=$(curl -sf --max-time "${TIMEOUT}" "${API_URL}" 2>/dev/null || true)
if [[ -z "${API_PAYLOAD}" ]]; then
    echo "CRITICAL: Angie Monitoring API endpoint is unresponsive"
    exit 2
fi

# 3. Извлечение ключевых телеметрических параметров
VERSION=$(echo "${API_PAYLOAD}" | jq -r '.version // empty')
GENERATION=$(echo "${API_PAYLOAD}" | jq -r '.generation // empty')

if [[ -z "${VERSION}" || -z "${GENERATION}" ]]; then
    echo "WARNING: Received malformed JSON from API"
    exit 1
fi

echo "OK: Angie ${VERSION} healthy, Generation ${GENERATION}, UI and API operational"
exit 0
```

**Валидация скрипта:**

```bash
# Установка прав на исполнение
sudo chmod +x /usr/local/bin/check_angie_console.sh

# Ручной запуск теста
/usr/local/bin/check_angie_console.sh
# → OK: Angie 1.12.3 healthy, Generation 4, UI and API operational
```

## Операции и команды

### Эндпоинты API, опрашиваемые Console Light

В таблице приведен перечень эндпоинтов, к которым обращается фронтенд Console Light в цикле опроса:

| Эндпоинт в Console Light | Назначение в интерфейсе | Пример команды curl |
|:---|:---|:---|
| `/console/api/` | Корневой эндпоинт, проверка общего дерева API | `curl -sf http://127.0.0.1:8888/console/api/` |
| `/console/api/angie/` | Версия сервера, аптайм, поколение, конфигурационные файлы | `curl -sf http://127.0.0.1:8888/console/api/angie/` |
| `/console/api/connections/` | Глобальные соединения: accepted, dropped, active, idle | `curl -sf http://127.0.0.1:8888/console/api/connections/` |
| `/console/api/http/server_zones/` | Запросы, коды статусов (1xx-5xx), сетевой трафик по vhost | `curl -sf http://127.0.0.1:8888/console/api/http/server_zones/` |
| `/console/api/http/location_zones/` | Статистика по выделенным локационным зонам | `curl -sf http://127.0.0.1:8888/console/api/http/location_zones/` |
| `/console/api/http/upstreams/` | Состояние бэкендов, время отклика RTT, веса, сбои | `curl -sf http://127.0.0.1:8888/console/api/http/upstreams/` |
| `/console/api/http/caches/` | Статистика кэша: hit/miss/expired, объем занимаемого диска | `curl -sf http://127.0.0.1:8888/console/api/http/caches/` |
| `/console/api/slabs/` | Диагностика страниц и слотов slab-аллокатора памяти | `curl -sf http://127.0.0.1:8888/console/api/slabs/` |
| `/console/api/stream/server_zones/` | Метрики TCP/UDP стримов: соединения, сессии, байты | `curl -sf http://127.0.0.1:8888/console/api/stream/server_zones/` |

### SRE-команды оперативной диагностики

```bash
# 1. Быстрая проверка состояния сервера и ревизии конфигурации
curl -sf http://127.0.0.1:8888/status/angie/ | jq '{version, generation, address, load_time}'
# → {
# →   "version": "1.12.3",
# →   "generation": 4,
# →   "address": "127.0.0.1",
# →   "load_time": "2026-10-14T10:15:22Z"
# → }

# 2. Мгновенная фильтрация деградировавших или недоступных серверов в апстримах
curl -sf http://127.0.0.1:8888/status/http/upstreams/ | \
  jq 'to_entries[] | {upstream: .key, degraded: [.value.peers[] | select(.state != "up") | {server, state, fails}]}'
# → {
# →   "upstream": "cluster_payment_api",
# →   "degraded": []
# → }

# 3. Анализ задержек (Latency) бэкендов в миллисекундах
curl -sf http://127.0.0.1:8888/status/http/upstreams/cluster_payment_api/ | \
  jq '.peers[] | {server, response_time: .health.response_time, active_reqs: .selected.current}'
# → {
# →   "server": "10.0.10.11:8080",
# →   "response_time": 12,
# →   "active_reqs": 2
# → }

# 4. Проверка исчерпания памяти в slab-аллокаторе (поиск зон с отказами аллокации)
curl -sf http://127.0.0.1:8888/status/slabs/ | \
  jq 'to_entries[] | {zone: .key, fails: .value.pages.fails}'
# → {
# →   "zone": "cluster_payment_api",
# →   "fails": 0
# → }

# 5. Текущая насыщенность клиентскими соединениями
curl -sf http://127.0.0.1:8888/status/connections/ | jq .
# → {
# →   "accepted": 45120,
# →   "dropped": 0,
# →   "active": 14,
# →   "idle": 6
# → }

# 6. Проверка целостности и хеш-сумм статических файлов Console Light
sha256sum /usr/share/angie-console-light/html/index.html
# → a83ef63f8216...  /usr/share/angie-console-light/html/index.html
```

## Устранение неполадок

| Признак неисправности | Вероятная причина | Метод диагностики | Способ устранения |
|:---|:---|:---|:---|
| **Интерфейс открывается, но все графики и таблицы пусты (Spinning loader)** | Нарушена маршрутизация между SPA и API, либо опечатка в пути директивы `api`. | Открыть DevTools браузера (F12) → вкладка Network. Проверить HTTP-статусы вызовов к `/console/api/...`. | Убедитесь, что внутри блока `location /console/` объявлена вложенная локация `location /console/api/ { api /status/; }`. Проверьте вызов API локально через `curl`. |
| **Ошибка 403 Forbidden при обращении к `/console/`** | Сработали сетевые ограничения директив `allow`/`deny` либо отсутствуют права чтения файлов. | Проверить IP-адрес клиента и лог ошибок: `grep "access forbidden by rule" /var/log/angie/error.log`. | Добавьте IP клиента или подсеть в список `allow`. Проверьте права на каталог: `sudo chmod -R 755 /usr/share/angie-console-light/html/`. |
| **Ошибка 404 Not Found при обращении к `/console/api/...`** | Отсутствует завершающий слэш в объявлении `location` или директиве `api`. | Запустить `curl -v http://127.0.0.1:8888/console/api/angie/`. Проверить соответствие префиксов. | Проверьте, что пути объявлены со слэшами: `location /console/api/` и `api /status/;`. |
| **Вкладка Upstreams пуста, хотя бэкенды функционируют** | В блоке `upstream` не объявлена директива `zone` в разделяемой памяти. | Проверить файл конфигурации апстрима: `grep -E "upstream|zone" /etc/angie/http.d/*.conf`. | Добавьте директиву `zone <name> 128k;` внутрь каждого блока `upstream`. Выполните `angie -s reload`. |
| **Вкладка Configs выдает ошибку или пустой экран** | Директива `api_config_files` отключена (по умолчанию `off`). | Выполнить: `curl -sf http://127.0.0.1:8888/status/angie/config_files/`. | В контексте `http` пропишите `api_config_files on;` и перезагрузите конфигурацию (`angie -s reload`). |
| **Ошибка CORS (`Cross-Origin Request Blocked`) в консоли браузера** | Console Light открыта на одном домене/порту, а запросы к API направляются на другой без CORS-заголовков. | Проверить консоль браузера на наличие ошибки: `blocked by CORS policy: No 'Access-Control-Allow-Origin' header`. | Настройте обслуживание статики и API внутри единого `server` блока либо добавьте заголовок `add_header Access-Control-Allow-Origin "*";` в локацию API. |
| **Ошибка 500 Internal Server Error при запросах к API** | Исчерпана разделяемая память в одной из зон статуса (Slab exhaustion). | Проверить системный лог: `grep "cannot allocate memory in shared memory zone" /var/log/angie/error.log`. | Увеличьте размер зоны в конфигурации (например, с `64k` до `512k` или `1m`) и выполните `systemctl restart angie`. |
| **Высокая утилизация диска (I/O) из-за постоянного поллинга** | Запросы от открытых вкладок браузера записываются в общий `access.log`. | Выполнить `tail -f /var/log/angie/access.log \| grep "/console/api/"`. | Добавьте директиву `access_log off;` внутрь локаций `/console/api/` и `/status/`. |
| **Счетчики метрик внезапно обнулились** | Сервис был перезапущен через `restart`, а не `reload`. | Проверить поле `load_time` и `generation` в `/status/angie/`, а также аптайм systemd: `systemctl status angie`. | Помните, что разделяемая память существует только в RAM. Для применения конфигураций используйте исключительно `systemctl reload angie`. |

## Лучшие практики

### Безопасность

1. **Никогда не публикуйте порт консоли в Internet:**
   Используйте связывание только с локальными адресами loopback (`127.0.0.1:8888`) либо с внутренними приватными сетевыми интерфейсами (VLAN управления). Для доступа извне используйте SSH-туннелирование:
   ```bash
   ssh -L 8888:127.0.0.1:8888 user@bastion-host.corp.local
   ```
2. **Многоуровневая авторизация:**
   Совмещайте фильтрацию по IP (`allow 10.0.0.0/8; deny all;`) с обязательной аутентификацией `auth_basic`. При создании паролей применяйте современные алгоритмы хэширования (`openssl passwd -6` или `htpasswd -B`), избегая устаревшего формата crypt.
3. **Строгая политика CSP и изоляция фреймов:**
   Всегда добавляйте заголовок `X-Frame-Options: DENY` для исключения атак Clickjacking и ограничивайте директиву `connect-src` в Content Security Policy только текущим доверенным источником (`'self'`).
4. **Контроль директивы `api_config_files`:**
   Включение `api_config_files on;` делает все пароли к базам данных, API-ключи и сертификаты, прописанные в конфигурациях Angie, доступными через веб-интерфейс. Включайте эту опцию только при строгой изоляции интерфейса управления.

### Производительность и сайзинг

1. **Расчет размеров разделяемой памяти:**
   - Для зон `upstream`: базовая рекомендация — 64 КБ на каждые 30–50 серверов в пуле. При использовании динамических весов, таймингов и проверок доступности выделяйте 256 КБ – 1 МБ.
   - Для зон `status_zone`: зона размером 1 МБ способна хранить статистику для сотен виртуальных хостов и локаций.
2. **Оптимизация пулов keepalive:**
   Поскольку браузер производит постоянные вызовы каждые ~1 секунду, задавайте `keepalive_requests 10000;` и `keepalive_timeout 75s;` на управляющем виртуальном хосте. Это снижает потребление CPU на повторные TCP- и TLS-рукопожатия.
3. **Отключение журнала доступа (Logging Overhead):**
   Обязательно отключайте логирование в локациях обслуживания API (`access_log off;`). Непрерывная запись 10–50 RPS служебного поллинга не несет диагностической ценности, но расходует ресурс накопителей (SSD endurance) и раздувает логи.

### Эксплуатация и SRE

1. **Отслеживание ревизий через `generation`:**
   При анализе инцидентов сопоставляйте значение поля `generation` в `/status/angie/` с записями в журнале изменений (Git commit log или журнал автоматизации Ansible). Это позволяет однозначно подтвердить, какая именно конфигурация была активна в момент деградации.
2. **Контроль задержек и насыщения:**
   Используйте вкладку **HTTP Upstreams** для оценки задержек бэкендов в реальном времени. Если среднее время `response_time` растет при неизменном RPS, проблема локализуется в коде бэкенда или на уровне базы данных, а не на балансировщике.
3. **Плавная перезагрузка конфигурации:**
   Перед выполнением reload всегда проверяйте синтаксис: `sudo angie -t`. Применяйте изменения командой `sudo angie -s reload` (или `systemctl reload angie`). Это предотвратит сброс собранной статистики в разделяемой памяти.

### Очистка и восстановление

1. **Восстановление статики Console Light:**
   Поскольку статические файлы не содержат изменяемого состояния, в случае их повреждения достаточно переустановить соответствующий системный пакет:
   ```bash
   # Debian/Ubuntu:
   sudo apt-get install --reinstall -y angie-console-light

   # RHEL/AlmaLinux:
   sudo dnf reinstall -y angie-console-light
   ```
2. **Удаление тестовых учетных записей:**
   Регулярно проводите аудит файла `/etc/angie/console.htpasswd`. При компрометации пароля удалите пользователя командой:
   ```bash
   sudo sed -i '/^test_user:/d' /etc/angie/console.htpasswd
   ```

## Дополнительная информация

### Сравнение инструментов мониторинга

| Критерий | Angie Console Light / API | Prometheus + Grafana | Stub Status (`stub_status`) |
|:---|:---|:---|:---|
| **Интервал обновления** | Около 1 секунды (Near Real-Time) | 15–60 секунд (Интервал скрапинга) | По запросу (ручной опрос) |
| **Глубина истории** | Отсутствует (только текущее состояние) | Недели, месяцы, годы | Отсутствует |
| **Масштаб охвата** | Один конкретный экземпляр Angie | Вся инфраструктура и кластеры | Один экземпляр |
| **Алертинг** | Отсутствует (только визуальный контроль) | Нативный через Alertmanager | Отсутствует |
| **Влияние на систему** | Минимальное (опрос разделяемой памяти) | Зависит от объема метрик и частоты | Минимальное |
| **Основная цель** | Оперативная отладка, валидация reload | Тренды, Capacity Planning, SLA/SLO | Простейший healthcheck контейнера |

### Отличия от коммерческой версии Angie Pro Console

В коммерческой версии (Angie PRO) веб-консоль мониторинга базируется на расширенном модуле `ngx_http_console_module` и поддерживает **режим управления (Write Mode)**:
- **Динамическое управление серверами:** изменение весов бэкендов, вывод серверов в обслуживание (`down`) или плавный вывод с дообслуживанием активных сессий (`drain`) напрямую из браузера через API без reload.
- **Визуализация перцентилей задержек:** графики распределения квантилей времени отклика бэкендов (P50, P90, P99).
- **Сброс статистики:** очистка счетчиков выбранных зон статуса на лету без перезапуска процессов.
- **Управление KV-хранилищами:** интерактивный просмотр и редактирование данных в Key-Value зонах.

В открытой версии Angie (Open Source) консоль функционирует строго в режиме **Read-Only**, предоставляя визуализацию состояния без возможности модификации параметров сервера из браузера.

### Ограничения Console Light

1. **Отсутствие долговременного хранения:** данные не персистентны. При перезапуске сервиса (`restart`) или перезагрузке операционной системы счетчики обнуляются.
2. **Локальный контекст:** панель визуализирует метрики только одного хоста, на котором запущена. Для кластерного мониторинга парка серверов необходимо использовать нативный экспорт метрик в Prometheus.
3. **Зависимость от браузера:** интерфейс требует поддержки современных возможностей JavaScript (Fetch API, ES6). Работа в текстовых консольных браузерах (`curl`, `elinks`) не поддерживается.

---

**См. также:**

- [Основные концепции мониторинга](./angie_monitoring_concepts.md) — обзор архитектуры телеметрии, разделяемой памяти и способов сбора метрик
- [Работа с конфигурацией через API](./angie_monitoring_api.md) — исчерпывающий справочник по дереву JSON, эндпоинтам и параметрам модуля `ngx_http_api_module`
- [Интеграция с Prometheus](./angie_monitoring_prometheus.md) — настройка нативного экспорта метрик для централизованного мониторинга и алертинга
- [Пользовательские метрики](./angie_monitoring_custom_metrics.md) — расчет специфических бизнес-метрик и счетчиков с помощью `metric_zone`
- [Возможности Angie Pro](./angie_monitoring_pro.md) — расширенные механизмы управления бэкендами, перцентили и коммерческие функции
