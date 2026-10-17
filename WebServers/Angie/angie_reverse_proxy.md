# Настройка Angie в роли обратного HTTP-прокси

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

**Обратный прокси-сервер (Reverse Proxy / Edge Gateway)** — промежуточный сетевой сервис, принимающий клиентские HTTP-запросы и маршрутизирующий их к одному или нескольким внутренним серверам приложений. В отличие от прямого (Forward) прокси, защищающего клиентов, обратный прокси защищает и изолирует инфраструктуру бэкендов, выступая единой точкой входа (Single Point of Entry).

**Апстрим / Бэкенд (Upstream / Origin Server)** — целевой сервер или пул серверов (сервисы приложений, базы данных, хранилища объектов), непосредственно выполняющий бизнес-логику и формирующий полезную нагрузку ответа.

**Терминация TLS (TLS Termination)** — процесс расшифровки входящего HTTPS-трафика на уровне прокси-сервера с последующей передачей запроса к бэкендам в открытом (HTTP) либо повторно зашифрованном (Re-encryption / mTLS) виде.

**Буферизация прокси (Proxy Buffering)** — механизм временного накопления данных запроса клиента или ответа бэкенда в оперативной памяти (или во временных файлах на диске) рабочего процесса Angie для согласования скоростей между медленными клиентами и быстрыми внутренними сервисами.

**Пул постоянных соединений (Upstream Keepalive)** — механизм повторного использования установленных TCP-соединений между прокси и бэкендами для исключения накладных расходов на постоянное трехстороннее рукопожатие TCP (3-way handshake) и TLS-согласование.

**Нормализация URI (URI Normalization & Transformation)** — процесс декодирования, устранения избыточных символов (`//`, `/./`, `/../`) и преобразования пути запроса перед передачей бэкенду в зависимости от синтаксиса директивы `proxy_pass`.

**Сквозные и Hop-by-hop заголовки (End-to-End vs Hop-by-Hop Headers)** — классификация HTTP-заголовков по стандарту RFC 7230 / RFC 9110. Сквозные заголовки передаются конечному получателю через цепочку прокси, а заголовки hop-by-hop (такие как `Connection`, `Keep-Alive`, `Upgrade`, `Transfer-Encoding`) относятся строго к текущему TCP-соединению и удаляются прокси-сервером.

## Базовые концепции

В веб-сервере Angie функциональность обратного прокси реализуется базовым модулем `ngx_http_proxy_module`. Он обеспечивает двустороннюю трансляцию протоколов, модификацию метаданных запросов и ответов, фильтрацию трафика и изоляцию внутренней топологии.

### Ключевые функции
1. **Терминация протоколов:** Прием внешнего клиентского трафика по современным протоколам (HTTP/3 на базе QUIC, HTTP/2, TLS 1.3) и трансляция запросов к бэкендам по оптимизированному HTTP/1.1 (или эксклюзивному для Angie HTTP/3).
2. **Балансировка и отказоустойчивость:** Автоматическое распределение запросов между узлами кластера, пассивный и активный мониторинг доступности серверов, прозрачный failover при сбоях.
3. **Изоляция и защита:** Сокрытие реальных IP-адресов, портов и внутренней топологии сети, фильтрация заголовков, ограничение частоты запросов (`limit_req`) и соединений (`limit_conn`).
4. **Сглаживание сетевой нагрузки:** Буферизация быстрых ответов бэкенда для медленных мобильных клиентов, защита бэкендов от медленных атак типа Slowloris и Slow POST.

### Минимальная конфигурация
```nginx
server {
    listen 80;
    server_name example.com;

    location / {
        # Пересылка входящих запросов на внутренний сокет приложения
        proxy_pass http://127.0.0.1:8080;
    }
}
```

### Неблокирующая архитектура и конечный автомат соединений
Angie использует событийно-ориентированную (event-driven) неблокирующую модель на базе системных вызовов `epoll` (Linux) или `kqueue` (BSD). При обработке прокси-запроса каждый воркер управляет двусторонней машиной состояний:
- **Клиентское плечо (Downstream):** TCP-сокет между клиентом и Angie. Воркер ожидает готовности сокета к чтению (EPOLLIN) для приема заголовков и тела запроса.
- **Внутреннее плечо (Upstream):** TCP/Unix/TLS-сокет между Angie и бэкендом. Воркер открывает неблокирующий сокет к бэкенду (или извлекает готовый из пула `keepalive`), передает запрос и переводит сокет в режим ожидания ответа.

Пока бэкенд выполняет вычисления или ожидает данных из базы, воркер Angie **не блокируется**. Он продолжает обслуживать тысячи других клиентских соединений, возвращаясь к сокету бэкенда только при возникновении события поступления данных от ядра ОС.

### Жизненный цикл HTTP-запроса
При работе в режиме обратного прокси запрос проходит 10 строго упорядоченных фаз:

```
[Клиент] ──(TCP/TLS)──► [Angie Worker] ──(HTTP/1.1 Keepalive)──► [Бэкенд]
                             │
     ┌───────────────────────┴───────────────────────┐
     ▼                                               ▼
[Буфер памяти (proxy_buffers)]             [Временный файл (proxy_temp)]
     │                                               │
     └───────────────────────┬───────────────────────┘
                             ▼
[Клиент] ◄──(HTTP/TLS)── [Angie Worker]
```

1. **Прием и валидация:** Воркер принимает TCP-соединение, при необходимости выполняет TLS-рукопожатие и парсит стартовую строку и заголовки HTTP-запроса.
2. **Конфигурационный роутинг:** Angie сопоставляет URI с наиболее специфичным блоком `location`.
3. **Проверка кэша:** При наличии директивы `proxy_cache` выполняется поиск в зоне разделяемой памяти ключей. При попадании (HIT) ответ отдается клиенту немедленно, минуя бэкенд (подробно: [Кэширование прокси в Angie](./angie-proxy-cache.md)).
4. **Обработка тела запроса:** Если включена буферизация запроса (`proxy_request_buffering on;`), Angie вычитывает тело запроса от клиента в память/диск до обращения к бэкенду. При отключении (`off`) — передача тела бэкенду начинается параллельно с его чтением от клиента.
5. **Выбор апстрима и установление соединения:** Модуль балансировки выбирает узел из группы `upstream`. Проверяется локальный пул `keepalive`: если есть свободный сокет — он переиспользуется, иначе инициируется неблокирующий `connect()`.
6. **Трансляция и отправка запроса:** Angie преобразует URI согласно правилам `proxy_pass`, заменяет hop-by-hop заголовки, добавляет служебные заголовки (`proxy_set_header`) и отправляет сформированный HTTP-запрос в сокет бэкенда.
7. **Ожидание ответа и failover:** Запускается таймер `proxy_read_timeout`. Если бэкенд разрывает соединение, падает по таймауту или возвращает статус из перечня `proxy_next_upstream`, Angie обращается к следующему серверу из группы.
8. **Чтение заголовков ответа:** Ответ бэкенда считывается в буфер `proxy_buffer_size`. Выполняется парсинг статуса ответа и HTTP-заголовков. При необходимости выполняется перезапись (`proxy_redirect`).
9. **Буферизация и передача тела:** При `proxy_buffering on;` Angie считывает тело ответа в пулы буферов `proxy_buffers`. При переполнении памяти излишки сбрасываются во временный файл (`proxy_temp_path`). По мере заполнения порции `proxy_busy_buffers_size` отправляются клиенту.
10. **Завершение транзакции:** Соединение с бэкендом либо возвращается в пул `keepalive`, либо закрывается (при `Connection: close`). Клиентское соединение переводится в режим ожидания следующего Keep-Alive запроса или закрывается.

### Механизм передачи URI в `proxy_pass` (правила слэша)
Поведение Angie при формировании пути запроса к бэкенду кардинально зависит от наличия URI-части в строке `proxy_pass`. Это один из самых критичных механизмов в системном администрировании.

#### 1. `proxy_pass` БЕЗ URI (слэш после хоста отсутствует)
Если директива содержит только протокол, хост и порт без завершающего слэша, исходный URI клиента передается на бэкенд **полностью без изменений** в том виде, в котором он поступил:
```nginx
location /api/ {
    # URI отсутствует: слэша после порта нет!
    proxy_pass http://127.0.0.1:8080;
}
# Запрос:  GET /api/v1/users?id=10
# Бэкенд:  GET /api/v1/users?id=10
```

#### 2. `proxy_pass` С URI (слэш или путь после хоста присутствует)
Если после хоста указан URI (даже если это всего один слэш `/`), Angie выполняет **нормализацию и замену префикса**: часть URI, совпавшая с префиксом `location`, заменяется на URI из директивы `proxy_pass`:
```nginx
location /api/ {
    # URI присутствует: указан одиночный слэш '/'
    proxy_pass http://127.0.0.1:8080/;
}
# Запрос:  GET /api/v1/users?id=10
# Префикс /api/ отрезается и заменяется на /
# Бэкенд:  GET /v1/users?id=10
```

Если указан путь с префиксом:
```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8080/internal-service/;
}
# Запрос:  GET /api/v1/users?id=10
# Префикс /api/ заменяется на /internal-service/
# Бэкенд:  GET /internal-service/v1/users?id=10
```

#### 3. Запрет URI в регулярных выражениях и именованных локациях
Если `location` задан регулярным выражением (`location ~ \.php$`), именованной локацией (`location @fallback`) или находится внутри блока `if`, указывать URI в `proxy_pass` **запрещено**:
```nginx
# ОШИБКА: Angie выдаст ошибку валидации синтаксиса при запуске:
# "proxy_pass cannot have URI part in location given by regular expression..."
location ~ ^/api/(.*)$ {
    proxy_pass http://127.0.0.1:8080/$1; # НЕЛЬЗЯ
}

# КОРРЕКТНО: Использовать директиву rewrite с флагом break:
location ~ ^/api/(.*)$ {
    rewrite ^/api/(.*)$ /$1 break;
    proxy_pass http://127.0.0.1:8080; # Без URI-части
}
```

### Архитектура буферизации: память vs временные файлы
Буферизация ответов управляется модулем через трехуровневую структуру памяти:

```
[Заголовки ответа бэкенда] ────────► proxy_buffer_size (1 буфер: 4k / 8k / 16k)
                                              │
[Тело ответа бэкенда]      ────────► proxy_buffers (N буферов: напр. 8 по 8k)
                                              │ (если превышен лимит памяти)
                                              ▼
                                     proxy_temp_path (сброс во временный файл на диске)
                                              │ (ограничение proxy_max_temp_file_size)
                                              ▼
[Передача клиенту]         ◄──────── proxy_busy_buffers_size (порции отправки)
```

1. **`proxy_buffer_size`:** Отдельный специализированный буфер. В него считывается первая часть ответа бэкенда — строка статуса и HTTP-заголовки. Если заголовки бэкенда (например, длинный `Set-Cookie` или крупный токен JWT/OAuth) превышают этот буфер, Angie немедленно возвращает клиенту ошибку `502 Bad Gateway` с сообщением в логе `upstream sent too big header`.
2. **`proxy_buffers`:** Задает количество и размер страниц памяти для тела ответа (например, `8 8k` = 64 КБ). Ответ удерживается в памяти и передается клиенту без обращения к диску.
3. **`proxy_busy_buffers_size`:** Ограничивает объем буферов, которые могут находиться в состоянии отправки клиенту, пока остальные буферы продолжают наполняться от бэкенда. Обычно выставляется в `2 * proxy_buffer_size`.
4. **`proxy_temp_path` и `proxy_max_temp_file_size`:** Если ответ превышает суммарный объем `proxy_buffers`, Angie начинает сохранять данные во временный файл. Параметр `proxy_max_temp_file_size` (по умолчанию 1024 МБ) ограничивает предельный размер такого файла. При значении `0` запись на диск полностью запрещается.

### Протокольная трансляция и Hop-by-Hop заголовки
По умолчанию модуль `ngx_http_proxy_module` работает по протоколу **HTTP/1.0** и отправляет бэкенду заголовок `Connection: close`. Это историческое поведение Nginx/Angie приводит к тому, что на каждый запрос открывается новое TCP-соединение, а Keep-Alive не работает.

Для перевода проксирования в полноценный HTTP/1.1 с повторным использованием соединений требуется явная декларация:
```nginx
proxy_http_version 1.1;
proxy_set_header Connection "";
```

**Очистка заголовков Hop-by-Hop (RFC 7230):**
Angie автоматически вырезает из клиентского запроса и ответа бэкенда заголовки, управляющие конкретным сетевым соединением:
- `Connection`
- `Keep-Alive`
- `Proxy-Authenticate`
- `Proxy-Authorization`
- `TE`
- `Trailers`
- `Transfer-Encoding`
- `Upgrade` (пропускается только при явной настройке проксирования WebSocket)

**HTTP/3 на бэкенд (Эксклюзивная функция Angie):**
Начиная с ранних версий Angie поддерживает проксирование трафика к апстриму по протоколу HTTP/3 поверх UDP/QUIC:
```nginx
location /quic-backend/ {
    proxy_pass https://backend_upstream;
    proxy_http_version 3.0;
}
```

## Практические сценарии

### Сценарий 1: Проброс клиентских метаданных и сквозных заголовков
Бэкенд должен получать реальную сетевую информацию об инициаторе запроса, а не IP-адрес самого балансировщика Angie.

```nginx
# Определение надежного протокола за реверс-прокси
map $http_x_forwarded_proto $forwarded_proto {
    default $http_x_forwarded_proto;
    ""      $scheme;
}

server {
    listen 80;
    listen 443 ssl;
    server_name app.example.com;

    ssl_certificate     /etc/angie/ssl/app.example.com.crt;
    ssl_certificate_key /etc/angie/ssl/app.example.com.key;

    location / {
        proxy_pass http://backend_cluster;

        # 1. Сохранение оригинального имени виртуального хоста
        proxy_set_header Host $host;

        # 2. Непосредственный IP-адрес клиента (предыдущий хоп)
        proxy_set_header X-Real-IP $remote_addr;

        # 3. Полная цепочка IP-адресов через все промежуточные прокси
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # 4. Протокол клиента (http или https) для генерации корректных ссылок
        proxy_set_header X-Forwarded-Proto $forwarded_proto;

        # 5. Порт и хост для генерации внешних абсолютных редиректов бэкендом
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
    }
}
```

> **Важно:** При цепочке из нескольких прокси/WAF для правильного определения `$remote_addr` используйте модуль `ngx_http_realip_module` (`set_real_ip_from` и `real_ip_header`) — см. [Реальный IP клиента (Real-IP) и X-Forwarded-For](../../Networking/Protocols/HTTP/http_servers_proxies.md).

### Сценарий 2: Маршрутизация URI, префиксы и правила слэша
Типичная задача SRE — маршрутизация различных микросервисов под единым доменом с трансформацией или сохранением путей.

```nginx
server {
    listen 80;
    server_name api.example.com;

    # СИТУАЦИЯ А: Сервис ожидает запросы с сохранением префикса /auth/
    # Бэкенд получает: GET /auth/login
    location /auth/ {
        proxy_pass http://auth_service:8081; # Без слэша в конце!
    }

    # СИТУАЦИЯ Б: Сервис ожидает запросы без префикса /billing/
    # Запрос: GET /billing/invoices/10 -> Бэкенд получает: GET /invoices/10
    location /billing/ {
        proxy_pass http://billing_service:8082/; # С завершающим слэшем!
    }

    # СИТУАЦИЯ В: Регулярное выражение с изменением пути
    # Запрос: GET /v2/catalog/items -> Бэкенд получает: GET /api/v1/items
    location ~ ^/v2/catalog/(.*)$ {
        rewrite ^/v2/catalog/(.*)$ /api/v1/$1 break;
        proxy_pass http://catalog_service:8083; # proxy_pass строго без URI
    }
}
```

### Сценарий 3: Высокопроизводительный пул постоянных соединений (Upstream Keepalive)
Каждое новое TCP-соединение требует рукопожатия (1 RTT) и выделения сокета в ядре. Для высоконагруженных систем пул keepalive-соединений снижает задержку TTFB на 30–50% и предотвращает исчерпание эфемерных портов (`TIME_WAIT`).

```nginx
upstream backend_cluster {
    zone backend_cluster 256k;
    server 10.0.0.11:8080 max_fails=3 fail_timeout=10s;
    server 10.0.0.12:8080 max_fails=3 fail_timeout=10s;

    # Максимальное количество простаивающих keepalive-соединений НА ОДИН ВОРКЕР
    keepalive 64;

    # Максимальное количество запросов через одно соединение перед его ротацией
    keepalive_requests 10000;

    # Предельное время жизни соединения (защита от утечек памяти на бэкенде)
    keepalive_time 1h;

    # Таймаут простоя соединения в пуле
    keepalive_timeout 60s;
}

server {
    listen 80;
    server_name app.internal;

    location / {
        proxy_pass http://backend_cluster;

        # ОБЯЗАТЕЛЬНО для активации keepalive:
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

### Сценарий 4: Оптимизация буферизации ответов и защита дисковой подсистемы
В высоконагруженных API запись ответов бэкенда во временные файлы на диске создает паразитный I/O, увеличивает latency и изнашивает SSD.

```nginx
# Выделение RAM-диска (tmpfs) под временные буферы прокси
# /etc/fstab: tmpfs /var/cache/angie/proxy_temp tmpfs defaults,size=512M 0 0

location /api/ {
    proxy_pass http://backend_cluster;

    # Включение буферизации ответа
    proxy_buffering on;

    # Размер буфера под заголовки ответа (увеличен до 16k под крупные JWT)
    proxy_buffer_size 16k;

    # 16 буферов по 16k = 256 КБ оперативной памяти на запрос под тело ответа
    proxy_buffers 16 16k;

    # Объем буферов, доступный для одновременной отправки клиенту
    proxy_busy_buffers_size 32k;

    # Каталог временных файлов с двухуровневой структурой
    proxy_temp_path /var/cache/angie/proxy_temp 1 2;

    # Максимальный размер временного файла на диске для одного ответа
    proxy_max_temp_file_size 64m;

    # Размер порции единовременной записи во временный файл
    proxy_temp_file_write_size 32k;
}
```

> **Совет SRE:** Для микросервисных JSON-API, где 99% ответов не превышают 64 КБ, задавайте `proxy_buffers 8 8k;` или `16 4k;`. Если запись на диск категорически недопустима, установите `proxy_max_temp_file_size 0;`. При этом при превышении буферов памяти Angie синхронизирует чтение от бэкенда со скоростью клиента.

Подробный разбор архитектуры потоковой передачи: [Буферизация и стриминг в Nginx и Angie](../Nginx/Proxy/nginx_buffering_and_streaming.md).

### Сценарий 5: Потоковая загрузка больших файлов без буферизации тела (Upload/S3)
При загрузке артефактов, образов Docker или медиафайлов размером в сотни мегабайт или гигабайты буферизация входящего тела (`proxy_request_buffering on;`) приводит к задержке: клиент загружает файл целиком в Angie, и только затем Angie пересылает его в хранилище.

```nginx
location /storage/upload/ {
    proxy_pass http://minio_or_s3_backend;

    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;

    # Отключение накопления тела запроса в Angie:
    # Данные сразу передаются на бэкенд по мере поступления от клиента
    proxy_request_buffering off;

    # Предельный размер загружаемого файла (0 = безлимитно)
    client_max_body_size 5g;

    # Таймаут между операциями чтения тела запроса от клиента
    client_body_timeout 120s;

    # Таймаут передачи запроса бэкенду
    proxy_send_timeout 120s;
    proxy_read_timeout 300s;
}
```

> **Предостережение SRE:** При `proxy_request_buffering off;` соединение бэкенда связывается напрямую с медленным клиентом. Для защиты бэкенда от исчерпания воркеров комбинируйте эту директиву с жесткими значениями `client_body_timeout` и выделяйте под загрузки изолированный пул серверов.

### Сценарий 6: Отказоустойчивость, таймауты и безопасный failover
Настройка повторных попыток при сетевых сбоях и обработка кодов 5xx.

```nginx
location /checkout/ {
    proxy_pass http://payment_backend;

    # Сетевые таймауты
    proxy_connect_timeout 2s;  # Быстрый фейл при недоступности TCP-порта
    proxy_send_timeout    5s;  # Таймаут отправки запроса
    proxy_read_timeout    10s; # Ожидание ответа бэкенда

    # Переключение на следующий узел при сетевых сбоях и ошибках сервиса
    proxy_next_upstream error timeout invalid_header http_502 http_503 http_504;

    # Лимит повторных попыток (первая попытка + 2 повтора = максимум 3 узла)
    proxy_next_upstream_tries 3;

    # Суммарный бюджет времени на все попытки обращения
    proxy_next_upstream_timeout 8s;
}
```

> [!CAUTION]
> **Опасность опции `non_idempotent`:**
> По умолчанию Angie **никогда не повторяет** запросы с неидемпотентными методами (`POST`, `LOCK`, `PATCH`), если тело запроса уже частично отправлено бэкенду.
> Если включить флаг `proxy_next_upstream ... non_idempotent;`, сетевой сбой во время обработки платежа или создания заказа приведет к повторной отправке запроса на соседний сервер и **повторному списанию средств** или дублированию записей в БД.
> Включать `non_idempotent` разрешено **только** в том случае, если приложение на бэкенде поддерживает сквозные ключи идемпотентности (`Idempotency-Key`).
> Подробнее о стратегиях балансировки: [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md).

### Сценарий 7: Защита внутреннего контура по TLS и взаимная аутентификация (mTLS)
Шлюз Angie принимает публичный трафик, расшифровывает его и обращается к изолированным бэкендам по защищенному внутреннему каналу с валидацией сертификатов или клиентской аутентификацией.

```nginx
location /secure-core/ {
    # Схема https активирует модуль proxy_ssl
    proxy_pass https://secure_backend_cluster;

    # 1. Передача SNI (Server Name Indication) на бэкенд (критично при виртуальном хостинге)
    proxy_ssl_server_name on;
    proxy_ssl_name core.internal.domain;

    # 2. Проверка валидности сертификата бэкенда доверенным CA
    proxy_ssl_verify on;
    proxy_ssl_verify_depth 2;
    proxy_ssl_trusted_certificate /etc/angie/pki/internal_ca.crt;

    # 3. Взаимная аутентификация (mTLS): передача сертификата прокси бэкенду
    proxy_ssl_certificate     /etc/angie/pki/proxy_client.crt;
    proxy_ssl_certificate_key /etc/angie/pki/proxy_client.key;

    # 4. Протоколы и шифры для внутреннего контура
    proxy_ssl_protocols TLSv1.3;
    proxy_ssl_session_reuse on;
}
```

Подробно о настройке TLS и сертификатов: [Настройка TLS в Angie](./angie_tls_setup.md) и [Клиентская аутентификация по сертификатам (mTLS) в Angie](./angie_client_cert_auth.md).

### Сценарий 8: Перехват ошибок бэкенда и аварийный fallback
Сокрытие технических стектрейсов бэкенда и отдача брендированных страниц или перенаправление запроса в резервный сервис.

```nginx
location / {
    proxy_pass http://primary_app;

    # Включение перехвата ответов бэкенда со статусами >= 300
    proxy_intercept_errors on;

    # Статическая аварийная страница для фатальных ошибок
    error_page 500 502 503 504 /static/error_50x.html;

    # Перенаправление 404 ошибок в специальную поисковую локацию
    error_page 404 = @fallback_search;
}

location = /static/error_50x.html {
    root /var/www/error_pages;
    internal;
}

location @fallback_search {
    proxy_pass http://archive_or_search_service;
    proxy_set_header Host $host;
}
```

### Сценарий 9: Корректировка редиректов апстрима и скрытие служебных заголовков
Бэкенды часто генерируют HTTP-редиректы (`Location: http://10.0.0.12:8080/login/`), указывая свой внутренний сетевой адрес или схему `http://` вместо внешнего `https://`. Директива `proxy_redirect` транслирует заголовок `Location` в публичный вид.

```nginx
location /app/ {
    proxy_pass http://10.0.0.12:8080/;

    # Перезапись внутреннего URL бэкенда на внешний публичный адрес
    # Заменяет http://10.0.0.12:8080/login/ на https://example.com/app/login/
    proxy_redirect http://10.0.0.12:8080/ https://example.com/app/;

    # Либо использование служебной формы default (автоматический расчет по location/proxy_pass)
    # proxy_redirect default;

    # Сокрытие версий и стеков бэкенда от сканеров безопасности
    proxy_hide_header X-Powered-By;
    proxy_hide_header Server;
    proxy_hide_header X-AspNet-Version;

    # Разрешение передачи кастомных служебных заголовков
    proxy_pass_header X-Request-ID;
}
```

Подробный разбор алгоритмов и тонкостей перезаписи: [Редиректы в Nginx и Angie: proxy_redirect](../Nginx/Proxy/nginx_proxy_redirects.md).

### Сценарий 10: Управление обрывами соединений клиентом (`proxy_ignore_client_abort`)
Если пользователь прервал загрузку страницы, закрыл вкладку браузера или потерял связь, Angie по умолчанию разрывает соединение с бэкендом и регистрирует в access-логе код **499 (Client Closed Request)**.

```nginx
# Обычные GET-запросы: отмена запроса полезна для разгрузки бэкенда
location /catalog/ {
    proxy_pass http://catalog_service;
    proxy_ignore_client_abort off; # Значение по умолчанию
}

# Критические финансовые операции и фоновые задачи:
# запрос к бэкенду ОБЯЗАН завершиться, даже если клиент отключился
location /api/v1/charge/ {
    proxy_pass http://billing_backend;
    proxy_ignore_client_abort on;
}
```

### Сценарий 11: Проксирование специализированных протоколов
Angie предоставляет специализированные директивы для долгоживущих соединений и современных бинарных протоколов:

- **WebSocket:** Требует явной передачи заголовков `Upgrade` и `Connection` при версии `proxy_http_version 1.1;`, а также увеличенного `proxy_read_timeout` (например, `3600s`).
- **Server-Sent Events (SSE):** Требует отключения буферизации `proxy_buffering off;` (или отправки бэкендом заголовка `X-Accel-Buffering: no`), чтобы события доставлялись клиенту мгновенно без задержек.
- **gRPC:** Проксируется через отдельный модуль `ngx_http_grpc_module` с помощью директивы `grpc_pass grpc://backend:50051;` поверх HTTP/2.

Полное руководство по настройке, handshake и оптимизации вынесено в специализированный документ: [WebSocket, SSE и gRPC в Angie](./angie-websocket-sse-grpc.md).

### Сценарий 12: Решение проблемы исчерпания портов (TIME_WAIT) и мульти-IP привязка через `proxy_bind`

В масштабных системах при проксировании десятков тысяч RPS на один IP-адрес upstream-сервера возникает исчерпание эфемерных портов (`EADDRNOTAVAIL: Cannot assign requested address`). Пул портов ядра Linux (`net.ipv4.ip_local_port_range`, ~60 000 сокетов) блокируется соединениями в состоянии `TIME_WAIT`.

Директива `proxy_bind` связывает исходящие TCP-соединения к апстримам с определенным локальным IP-адресом. За счет циклического выбора из пула локальных IP-адресов емкость сокетов увеличивается кратно количеству назначенных адресов ($N \times 60\,000$).

```nginx
# Определение пула локальных исходящих адресов на сетевом интерфейсе
split_clients $connection $egress_ip {
    33.3% 192.168.10.201;
    33.3% 192.168.10.202;
    *     192.168.10.203;
}

location /highload-api/ {
    proxy_pass http://backend_pool;
    proxy_http_version 1.1;
    proxy_set_header Connection "";

    # 1. Привязка к пулу локальных IP для преодоления лимита 64k сокетов:
    proxy_bind $egress_ip;

    # 2. Режим прозрачного проксирования (Transparent Proxy / TPROXY):
    # Позволяет отправлять пакеты к бэкенду с сохранением реального IP клиента на сетевом уровне L4.
    # Требует прав CAP_NET_RAW / CAP_NET_ADMIN и настройки таблиц маршрутизации ip rule / iptables:
    # proxy_bind $remote_addr transparent;
}
```

> **Совет SRE:** Для работы режима `transparent` рабочий процесс обязан запускаться с возможностями ядра `AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN` в systemd-юните, а на хосте бэкенда шлюзом по умолчанию (Default Gateway) должен быть указан сервер Angie, чтобы обратные TCP-пакеты возвращались через ту же точку маршрутизации.

## Операции и команды

Все команды верификации и администрирования выполняются системным инженером на хосте с Angie.

### Верификация синтаксиса и дамп активной конфигурации

```bash
# Проверка синтаксиса всех подключенных файлов конфигурации
angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Проверка альтернативного файла конфигурации перед деплоем
angie -t -c /etc/angie/angie.conf.staging
# → angie: configuration file /etc/angie/angie.conf.staging test is successful

# Дамп полной скомпилированной конфигурации и поиск блока proxy_pass
angie -T | grep -A 10 "location /api/"
# →     location /api/ {
# →         proxy_pass http://backend_cluster;
# →         proxy_http_version 1.1;
# →         proxy_set_header Connection "";
# →     }
```

### Диагностика проксирования и сквозных заголовков через curl

```bash
# Проверка ответа бэкенда через прокси с передачей трассировочных заголовков
curl -v -H "Host: example.com" -H "X-Real-IP: 203.0.113.195" http://127.0.0.1/api/health
# → * Connected to 127.0.0.1 (127.0.0.1) port 80
# → > GET /api/health HTTP/1.1
# → > Host: example.com
# → > X-Real-IP: 203.0.113.195
# → < HTTP/1.1 200 OK
# → < Server: Angie
# → < Content-Type: application/json

# Проверка передачи больших заголовков (проверка proxy_buffer_size)
curl -s -o /dev/null -w "%{http_code}\n" -H "Cookie: $(python3 -c 'print("a=" + "x"*8192)')" http://127.0.0.1/
# → 200
```

### Инспекция открытых TCP-сокетов и keepalive соединений

```bash
# Просмотр активных соединений воркеров Angie к бэкендам на порту 8080
ss -tan '( sport = :8080 or dport = :8080 )'
# → State      Recv-Q  Send-Q   Local Address:Port    Peer Address:Port
# → ESTAB      0       0        10.0.0.5:43210        10.0.0.11:8080
# → ESTAB      0       0        10.0.0.5:43212        10.0.0.12:8080

# Детальная статистика сокетов с метриками TCP-окна и RTT
ss -ti '( dport = :8080 )' | grep -E "ESTAB|rtt:"
# → ESTAB      0      0      10.0.0.5:43210      10.0.0.11:8080
# →  rtt:0.245/0.052 rcvspace:65536 ssthresh:10 cwnd:10
```

### Инспекция временных файлов буфера прокси на диске

```bash
# Поиск открытых временных файлов воркерами Angie
lsof -c angie | grep proxy_temp
# → angie   14820 angie    9u   REG  254,1  10485760  131075 /var/cache/angie/proxy_temp/1/00/0000000001 (deleted)

# Проверка занятого места в каталоге временных буферов
du -sh /var/cache/angie/proxy_temp
# → 24M    /var/cache/angie/proxy_temp

# Проверка свободных inodes на разделе кэша
df -i /var/cache/angie
# → Filesystem      Inodes  IUsed   IFree IUse% Mounted on
# → /dev/sdb1      3276800  12400 3264400    1% /var/cache/angie
```

### Мониторинг upstream через Status API Angie

```bash
# Получение списка серверов и их состояния в группе upstream
curl -s http://127.0.0.1:8888/api/status/http/upstreams/backend_cluster/ | jq '.peers[] | {server, state, active, requests, downtime}'
# → {
# →   "server": "10.0.0.11:8080",
# →   "state": "up",
# →   "active": 4,
# →   "requests": 142050,
# →   "downtime": 0
# → }
# → {
# →   "server": "10.0.0.12:8080",
# →   "state": "up",
# →   "active": 3,
# →   "requests": 141990,
# →   "downtime": 0
# → }

# Сбор агрегированных метрик ответов бэкендов (коды 2xx, 4xx, 5xx)
curl -s http://127.0.0.1:8888/api/status/http/upstreams/backend_cluster/ | jq '.responses'
# → {
# →   "1xx": 0,
# →   "2xx": 284000,
# →   "3xx": 12,
# →   "4xx": 24,
# →   "5xx": 4,
# →   "total": 284040
# → }
```

### Управление службой и перезагрузка без простоя (Graceful Reload)

```bash
# Применение обновленной конфигурации без сброса активных соединений
systemctl reload angie

# Проверка статуса сервиса
systemctl status angie --no-pager
# → ● angie.service - Angie - high performance web server
# →      Loaded: loaded (/lib/systemd/system/angie.service; enabled)
# →      Active: active (running) since Mon 2026-10-12 08:00:00 UTC; 2 days ago

# Просмотр свежих системных логов перезагрузки
journalctl -u angie -n 20 --no-pager
```

### Анализ задержек и кодов ошибок прокси в логах

```bash
# Поиск запросов, вызвавших ошибки 502, 503 или 504 за последний час
awk '$9 ~ /^(502|503|504)$/ {print $1, $4, $7, $9, "upstream:", $11, "latency:", $10}' /var/log/angie/access.log | tail -n 10
# → 192.0.2.45 [14/Oct/2026:14:20:11 /api/order 502 upstream: 10.0.0.11:8080 latency: 0.002
# → 192.0.2.89 [14/Oct/2026:14:22:04 /api/report 504 upstream: 10.0.0.12:8080 latency: 60.001

# Расчет 95-го перцентиля времени ответа апстрима ($10 в секундах)
awk '$10 != "-" {print $10}' /var/log/angie/access.log | sort -n | awk '{all[NR] = $1} END {print "p95 upstream latency:", all[int(NR*0.95)] "s"}'
# → p95 upstream latency: 0.145s
```

## Устранение неисправностей

### 1. Ошибка 502 Bad Gateway
**Причина:** Angie не может установить TCP-соединение с бэкендом, соединение сброшено бэкендом до передачи ответа, произошел сбой TLS-хэндшейка, либо бэкенд вернул пустой/невалидный HTTP-заголовок.

**Диагностика:**
```bash
# Поиск конкретной причины в журнале ошибок Angie
grep -E "502|connect\(\) failed|Connection refused|prematurely closed" /var/log/angie/error.log | tail -n 5
# → 2026/10/14 15:00:02 [error] 14820#14820: *120 connect() failed (111: Connection refused) while connecting to upstream, client: 198.51.100.10, server: app.example.com, request: "GET /api/v1 HTTP/1.1", upstream: "http://10.0.0.11:8080/api/v1"

# Проверка локального порта бэкенда
nc -zv 10.0.0.11 8080
# → nc: connect to 10.0.0.11 port 8080 (tcp) failed: Connection refused
```

**Решение:**
1. Если `Connection refused` (код 111): Процесс бэкенда остановлен, упал по OOM, либо слушает только интерфейс `127.0.0.1` вместо внешнего IP-адреса. Запустите сервис (`systemctl restart backend`) и проверьте сокеты `ss -tlnp | grep 8080`.
2. Если `upstream prematurely closed connection`: Процесс приложения упал (segfault / unhandled exception) непосредственно при получении запроса. Изучите логи приложения (stdout/stderr).
3. Если `SSL_do_handshake() failed`: Несовпадение протоколов/шифров между Angie и бэкендом или несовпадение имени хоста в SNI. Включите `proxy_ssl_server_name on;` и проверьте сертификат через `openssl s_client -connect 10.0.0.11:8443 -servername core.internal`.

### 2. Ошибка 504 Gateway Timeout
**Причина:** Бэкенд принял запрос, но не завершил обработку и не вернул данные в течение времени, заданного директивой `proxy_read_timeout` (по умолчанию 60 секунд), либо не ответил на SYN-пакет за время `proxy_connect_timeout`.

**Диагностика:**
```bash
# Поиск записей таймаута в error.log
grep "upstream timed out" /var/log/angie/error.log | tail -n 5
# → 2026/10/14 15:10:45 [error] 14820#14820: *145 upstream timed out (110: Connection timed out) while reading response header from upstream, client: 203.0.113.5, server: app.example.com, request: "POST /reports/generate HTTP/1.1", upstream: "http://10.0.0.12:8080/reports/generate"
```

**Решение:**
1. Для длительных операций (генерация тяжелых отчетов, выгрузки) точечно увеличьте таймаут в соответствующем `location`:
   ```nginx
   location /reports/ {
       proxy_pass http://backend_cluster;
       proxy_read_timeout 300s;
       proxy_send_timeout 300s;
   }
   ```
2. Если таймаут возникает на стандартных запросах: бэкенд заблокирован долгими транзакциями в СУБД, исчерпал пул соединений или находится под высокой нагрузкой CPU.

### 3. Ошибка 499 Client Closed Request
**Причина:** Клиент (браузер, мобильное приложение или внешний curl) разорвал HTTP/TCP-соединение до того, как Angie успела получить ответ от бэкенда и отправить его клиенту. Специфический статус Nginx/Angie (в RFC отсутствует).

**Диагностика:**
```bash
# Поиск запросов с кодом 499 и сравнение времени работы ($request_time)
awk '$9 == "499" {print $1, $7, "client wait time:", $10, "sec"}' /var/log/angie/access.log | tail -n 5
# → 198.51.100.20 /api/checkout client wait time: 5.002 sec
```

**Решение:**
1. Если время ожидания клиента составляет ровно 5.000s, 10.000s или 30.000s — у клиентской библиотеки или фронтенда сработал жесткий тайм-аут (HTTP client timeout). Оптимизируйте бэкенд, чтобы он отвечал быстрее клиентского таймаута.
2. Пользователь нажал кнопку отмены или ушел со страницы.
3. Если для транзакционных запросов критично, чтобы бэкенд обязательно завершил операцию даже при уходе клиента, включите `proxy_ignore_client_abort on;` (см. Сценарий 10).

### 4. Ошибка "upstream sent too big header while reading response header from upstream"
**Причина:** Суммарный размер стартовой строки и HTTP-заголовков ответа бэкенда превысил размер буфера `proxy_buffer_size`. Частая проблема при интеграции с OAuth2/OIDC, Keycloak или фреймворками, отдающими массивные cookies.

**Диагностика:**
```bash
grep "too big header" /var/log/angie/error.log
# → 2026/10/14 15:15:30 [error] 14820#14820: *180 upstream sent too big header while reading response header from upstream, client: 192.0.2.1, server: auth.example.com, request: "GET /oauth/callback HTTP/1.1", upstream: "http://10.0.0.15:8080/oauth/callback"
```

**Решение:**
Увеличьте размер стартового буфера в блоке `http`, `server` или `location`:
```nginx
location / {
    proxy_pass http://backend_cluster;
    # Увеличение размера стартового буфера заголовков с 4k/8k до 32k
    proxy_buffer_size 32k;
    proxy_buffers 8 32k;
    proxy_busy_buffers_size 64k;
}
```

### 5. Ошибка 500: Проблемы с каталогом временных файлов (Permission Denied)
**Причина:** При буферизации больших ответов Angie не может создать временный файл в каталоге `proxy_temp_path` из-за неверных прав доступа или владельца каталога.

**Диагностика:**
```bash
grep "open() .* failed" /var/log/angie/error.log
# → 2026/10/14 15:20:01 [crit] 14820#14820: *205 open() "/var/cache/angie/proxy_temp/1/00/0000000001" failed (13: Permission denied) while reading upstream, client: 203.0.113.1, server: app.example.com
```

**Решение:**
Скорректируйте права и владельца каталога под пользователя, от имени которого запущены рабочие процессы Angie (обычно `angie` или `nginx`):
```bash
chown -R angie:angie /var/cache/angie/proxy_temp
chmod 700 /var/cache/angie/proxy_temp
```

### 6. Искажение URI, потеря путей или двойные слэши в `proxy_pass`
**Причина:** Несоответствие завершающих слэшей между блоком `location` и строкой `proxy_pass`.

**Симптомы и исправление:**
- Проблема: Запрос `GET /api/users` превращается на бэкенде в `GET //users`.
  Конфигурация: `location /api/ { proxy_pass http://backend/; }` (клиент запросил без слэша).
  Решение: Добавьте перенаправление со слэшем либо используйте `proxy_pass http://backend;` без слэша.
- Проблема: Префикс не должен отрезаться, но пропадает.
  Было: `location /service { proxy_pass http://backend/; }`
  Стало: `location /service { proxy_pass http://backend; }`

### 7. Бэкенд возвращает внутренний IP в редиректе (утечка инфраструктуры)
**Причина:** Приложение возвращает заголовок `Location: http://10.0.0.11:8080/dashboard/`, и пользователь перенаправляется на недоступный внутренний IP.

**Решение:**
Настройте трансляцию заголовка `Location` через `proxy_redirect`:
```nginx
location / {
    proxy_pass http://10.0.0.11:8080;
    proxy_redirect http://10.0.0.11:8080/ https://$host/;
}
```

### 8. Ошибка 503 Service Unavailable
**Причина:** В группе `upstream` нет активных серверов: все узлы помечены как неработоспособные (FAILED/DOWN), либо превышен лимит параллельных соединений `max_conns`.

**Диагностика:**
```bash
grep "no live upstreams" /var/log/angie/error.log
# → 2026/10/14 15:30:12 [error] 14820#14820: *310 no live upstreams while connecting to upstream, client: 198.51.100.99, server: app.example.com
```

**Решение:**
1. Проверьте доступность узлов бэкенда.
2. Проверьте параметры `max_fails` и `fail_timeout` в блоке `upstream`. При жестких проверках одиночный сетевой сбой может вывести узел из ротации.
3. При использовании модуля активных проверок Angie (`health_check` / `upstream_probe`) проверьте, отвечает ли контрольный эндпоинт приложения статусом `200 OK`.

## Лучшие практики

### Производственный чек-лист настройки обратного прокси

1. **Keepalive к бэкендам обязателен:**
   Всегда объявляйте блок `keepalive` в `upstream` и добавляйте директивы `proxy_http_version 1.1;` и `proxy_set_header Connection "";` в блоках `location`. Это снижает сетевые задержки и нагрузку на стек TCP ядра.
2. **Защита от зацикливания и бесконечных повторов:**
   Никогда не оставляйте директиву `proxy_next_upstream_tries` без ограничений. Стандартное правило SRE: число попыток равно 2 или 3, а `proxy_next_upstream_timeout` составляет не более 50% от суммарного клиентского таймаута.
3. **Безопасность идемпотентности:**
   Ни при каких обстоятельствах не включайте флаг `non_idempotent` в `proxy_next_upstream`, если бэкенд не гарантирует дедупликацию запросов через заголовки `Idempotency-Key`.
4. **Оптимизация дискового I/O временных буферов:**
   Размещайте каталог `proxy_temp_path` в оперативной памяти через `tmpfs` (`/var/cache/angie/proxy_temp`), чтобы исключить деградацию производительности дисков при пиковых нагрузках.
5. **Сокрытие служебных данных инфраструктуры:**
   Всегда очищайте заголовки `Server`, `X-Powered-By`, `X-AspNet-Version` и другие маркеры платформы через `proxy_hide_header`.
6. **Корректная обработка клиентских метаданных:**
   Используйте связку `$host`, `$remote_addr`, `$proxy_add_x_forwarded_for` и `$scheme`. Если перед Angie работают внешние CDN или балансировщики L4, используйте `ngx_http_realip_module` для извлечения настоящего IP клиента.
7. **Контроль размеров тела запроса:**
   Ограничивайте директиву `client_max_body_size` минимально необходимым значением на уровне каждого конкретного `location` (например, 1 МБ для API и 50 МБ для загрузки документов), чтобы исключить DoS-атаки переполнением диска.
8. **Защита от Path Traversal при передаче URI:**
   Никогда не используйте конструкцию `proxy_pass http://backend$uri;`. Переменная `$uri` нормализуется и декодируется ядром Angie, что позволяет обойти проверки безопасности приложения с помощью URL-encoded последовательностей обхода каталогов (`%2e%2e%2f`). Всегда используйте `proxy_pass http://backend$request_uri;` либо форму без указания URI: `proxy_pass http://backend;`.
9. **Защита от спуфинга Real-IP на внешнем периметре:**
   На самом первом входном прокси (Edge/DMZ), принимающем запросы из открытой сети, заголовок `X-Forwarded-For` **обязан принудительно перезаписываться**: `proxy_set_header X-Forwarded-For $remote_addr;`. Использование директивы `$proxy_add_x_forwarded_for` на внешнем шлюзе позволяет злоумышленнику передать поддельный заголовок `X-Forwarded-For: 127.0.0.1` и обойти внутренние списки контроля доступа (IP ACL). Дополнять цепочку через `$proxy_add_x_forwarded_for` разрешено только на внутренних прокси за доверенными балансировщиками.

### Золотые сигналы SRE для мониторинга прокси

| Метрика | Переменная в логе / Метрика Status API | Сигнал тревоги (Threshold) | Действие инженера |
| :--- | :--- | :--- | :--- |
| **Ошибки 502/503** | `$upstream_status` / `responses.5xx` | > 0.1% от общего трафика | Проверить здоровье процессов приложений, сокеты, OOM |
| **Ошибки 504** | `$upstream_status` / `responses.504` | > 0.05% от общего трафика | Проверить медленные запросы в СУБД, деградацию бэкенда |
| **Ошибки 499** | `$status` (499) | Рост при стабильных 200 OK | Клиенты отваливаются по своему таймауту; оптимизировать TTFB |
| **Latency p95/p99**| `$upstream_response_time` | Превышение SLA (напр. > 500ms) | Профилирование узких мест на уровне сервиса бэкенда |
| **Сетевая задержка**| `$upstream_connect_time` | > 5ms в локальной сети | Перегрузка сетевых интерфейсов, очереди SYN, сбои TCP |
| **Дисковый буфер** | Размер файлов в `proxy_temp_path` | > 0 байт на постоянной основе | Недостаточный размер `proxy_buffers`; тюнинг памяти под трафик |

## Дополнительная информация

### Справочник ключевых директив `ngx_http_proxy_module`

| Директива | Контекст | Значение по умолчанию | Назначение |
| :--- | :--- | :--- | :--- |
| `proxy_pass URL;` | `location`, `if in location`, `limit_except` | — | Задает протокол и адрес проксируемого сервера (домен, IP, Unix-сокет или upstream-группу). |
| `proxy_http_version 1.0 \| 1.1 \| 3.0;` | `http`, `server`, `location` | `1.0` | Версия протокола HTTP для соединения с бэкендом (3.0 — уникальная возможность Angie). |
| `proxy_set_header field value;` | `http`, `server`, `location` | `Host $proxy_host; Connection close;` | Переопределяет или добавляет заголовок запроса, передаваемый бэкенду. |
| `proxy_buffering on \| off;` | `http`, `server`, `location` | `on` | Включает/выключает буферизацию ответа бэкенда в Angie. |
| `proxy_buffer_size size;` | `http`, `server`, `location` | `4k \| 8k` | Размер буфера для чтения стартовой строки и заголовков ответа бэкенда. |
| `proxy_buffers number size;` | `http`, `server`, `location` | `8 4k \| 8 8k` | Количество и размер буферов для чтения тела ответа одного соединения. |
| `proxy_busy_buffers_size size;` | `http`, `server`, `location` | `2 * buffer_size` | Максимальный размер буферов, доступных для единовременной отправки клиенту. |
| `proxy_temp_path path [level1...];` | `http`, `server`, `location` | `proxy_temp` | Каталог для временных файлов при переполнении буферов памяти. |
| `proxy_max_temp_file_size size;` | `http`, `server`, `location` | `1024m` | Предельный объем временного файла ответа на диске (0 — запрет записи на диск). |
| `proxy_request_buffering on \| off;` | `http`, `server`, `location` | `on` | Включает/выключает буферизацию тела клиентского запроса до отправки на бэкенд. |
| `proxy_connect_timeout time;` | `http`, `server`, `location` | `60s` | Таймаут на установление TCP/TLS-соединения с бэкендом. |
| `proxy_send_timeout time;` | `http`, `server`, `location` | `60s` | Таймаут передачи запроса бэкенду (между двумя операциями записи). |
| `proxy_read_timeout time;` | `http`, `server`, `location` | `60s` | Таймаут ожидания ответа от бэкенда (между двумя операциями чтения). |
| `proxy_next_upstream ...;` | `http`, `server`, `location` | `error timeout` | Условия, при которых запрос перенаправляется на следующий сервер группы. |
| `proxy_next_upstream_tries num;` | `http`, `server`, `location` | `0` (не ограничено) | Предельное число попыток обращения к серверам группы upstream. |
| `proxy_next_upstream_timeout time;` | `http`, `server`, `location` | `0` (не ограничено) | Суммарное время, отведенное на все попытки failover. |
| `proxy_intercept_errors on \| off;` | `http`, `server`, `location` | `off` | Перехват ответов бэкенда со статусом >= 300 для обработки через `error_page`. |
| `proxy_redirect default \| off \| redirect replacement;` | `http`, `server`, `location` | `default` | Переписывает URL в заголовках `Location` и `Refresh` ответа бэкенда. |
| `proxy_ignore_client_abort on \| off;` | `http`, `server`, `location` | `off` | Не сбрасывать соединение с бэкендом, если клиент разорвал соединение. |
| `proxy_hide_header name;` | `http`, `server`, `location` | — | Запрещает передачу указанного заголовка из ответа бэкенда клиенту. |
| `proxy_pass_header name;` | `http`, `server`, `location` | — | Разрешает передачу скрытых по умолчанию заголовков бэкенда клиенту. |

### Сравнение сетевых таймаутов проксирования

| Директива | Фаза запроса | Рекомендуемое SRE-значение | Поведение при срабатывании |
| :--- | :--- | :--- | :--- |
| `proxy_connect_timeout` | Установление TCP-хэндшейка и TLS-сессии с бэкендом. | 2s – 5s | Возврат ошибки 502 или переход к следующему бэкенду. |
| `proxy_send_timeout` | Отправка тела запроса в сокет бэкенда (пауза между двумя операциями записи). | 10s – 30s | Разрыв соединения, возврат 504 или failover. |
| `proxy_read_timeout` | Ожидание ответа от бэкенда (пауза между двумя операциями чтения). | 15s – 60s (для API); 300s+ (для отчетов) | Возврат ошибки 504 Gateway Timeout. |

### Ключевые переменные мониторинга и логирования
Для включения в директиву `log_format` в блоке `http`:
- `$upstream_addr` — сетевой адрес (IP:порт или Unix-сокет) серверов, к которым обращался Angie. При повторных попытках содержит список через запятую (например, `10.0.0.11:8080, 10.0.0.12:8080`).
- `$upstream_status` — HTTP-статусы ответов, полученные от каждого опрошенного бэкенда (например, `502, 200`).
- `$upstream_response_time` — время обработки запроса бэкендом в секундах с точностью до миллисекунд.
- `$upstream_connect_time` — время, затраченное на установление TCP/TLS-соединения с бэкендом.
- `$upstream_header_time` — время от начала запроса до получения первого байта заголовка ответа бэкенда (чистый TTFB бэкенда).
- `$upstream_bytes_received` — количество байт, полученных от апстрима.
- `$upstream_cache_status` — статус кэша (`HIT`, `MISS`, `BYPASS`, `EXPIRED`, `STALE`, `UPDATING`, `REVALIDATED`).

## См. также

- **[Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)** — алгоритмы балансировки (round-robin, least_conn, least_time, hash), веса, sticky-сессии и активный мониторинг серверов.
- **[WebSocket, SSE и gRPC в Angie](./angie-websocket-sse-grpc.md)** — проксирование двунаправленных и потоковых соединений, gRPC поверх HTTP/2, Upgrade-хэндшейк.
- **[Кэширование прокси в Angie (Proxy Cache)](./angie-proxy-cache.md)** — кэширование ответов бэкенда, нативный purge, зоны в памяти и персистентность.
- **[Настройка TLS в Angie](./angie_tls_setup.md)** — терминация HTTPS, сертификаты, OCSP stapling и производительность TLS.
- **[Клиентская аутентификация по сертификатам (mTLS) в Angie](./angie_client_cert_auth.md)** — взаимная TLS-аутентификация с бэкендами и клиентами.
- **[Динамические апстримы в Angie](./dynamic_upstreams.md)** — Service Discovery, интеграция с DNS SRV и Docker без перезагрузки воркеров.
- **[Зеркалирование трафика в Angie (Mirror)](./angie-traffic-mirroring.md)** — дублирование продакшен-трафика на тестовые стенды без влияния на основной ответ.
- **[Логирование в Angie](./angie_logging.md)** — настройка структурированных логов JSON, upstream-метрик и ротации.
- **[Оптимизация производительности в High Load](./High_Load/performance_optimization.md)** — тюнинг параметров ядра Linux, сокетов, воркеров и epoll.
- **[Защита от DoS-атак в Angie](./High_Load/dos_protection.md)** — ограничение частоты запросов (`limit_req`) и соединений (`limit_conn`).
- **[Редиректы в Nginx и Angie: proxy_redirect](../Nginx/Proxy/nginx_proxy_redirects.md)** — детальный разбор директивы `proxy_redirect`, регулярных выражений и заголовка `Location`.
- **[Буферизация и стриминг в Nginx и Angie](../Nginx/Proxy/nginx_buffering_and_streaming.md)** — детальная теория буферизации ответов и потоковой передачи данных.
- **[Реальный IP клиента (Real-IP) и X-Forwarded-For](../../Networking/Protocols/HTTP/http_servers_proxies.md)** — корректное извлечение клиентских адресов через цепочки прокси.
- **[Безопасность HTTP в продакшене](../../Networking/Protocols/HTTP/http_security_hardening.md)** — hardening HTTP-серверов, защита от HTTP Request Smuggling и security-заголовки.
