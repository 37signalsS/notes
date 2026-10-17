# Балансировка нагрузки Nginx и Angie: Sticky Sessions (Прилипание сессий)

**Актуально для:** Nginx 1.26+ (OSS/Plus) / Angie 1.6+

## Определения

**Sticky Sessions (Прилипание сессий, Session Affinity, Session Persistence)** — механизм распределения трафика, при котором обратный прокси-сервер гарантированно направляет все повторные запросы определенного клиента на один и тот же целевой бэкенд в течение срока жизни его сеанса. Применяется для stateful-приложений, хранящих контекст пользователя (авторизацию, кэш объектов, корзину) в локальной оперативной памяти конкретного инстанса.

**Cookie-based Affinity (Привязка по cookie)** — метод сессионной привязки, при котором балансировщик внедряет собственную HTTP-куку в ответ сервера (или считывает существующую) и использует ее значение для идентификации закрепленного бэкенда.

**Learn Mode (Режим обучения, Session Tracking)** — механизм глубокого отслеживания сессий, при котором балансировщик инспектирует заголовки ответа бэкенда (`Set-Cookie`), извлекает сгенерированный приложением идентификатор (например, `JSESSIONID`, `PHPSESSID`) и динамически сохраняет отображение «ID сессии → бэкенд» в разделяемой оперативной памяти (`shared memory`).

**Route-based Affinity (Маршрутизация по маршруту)** — метод диспетчеризации, при котором клиент или фронтенд явно передает идентификатор целевого сервера в URI-параметре, заголовке или теле запроса, а балансировщик сопоставляет его с параметром `route` в определении директивы `server`.

**Зона разделяемой памяти (Shared Memory Zone, `zone`)** — сегмент RAM, выделяемый master-процессом Nginx/Angie через системные вызовы `mmap()`/`shmget()`, доступный всем рабочим процессам (`worker processes`). Необходим для централизованного хранения таблиц соответствия сессий, счетчиков сбоев и состояний серверов.

**Консистентное хеширование (Consistent Hashing, Ketama)** — метод балансировки (`hash ... consistent`), при котором ключи запросов отображаются на фиксированное кольцо виртуальных слотов. Обеспечивает сохранение привязки подавляющего большинства сессий ($1 - 1/N$) при динамическом добавлении или выводе бэкенд-узлов из строя.

**Режим дренажа (Connection Draining, `drain`)** — состояние постепенного вывода бэкенда из эксплуатации, при котором сервер перестает принимать новые клиентские сессии, но продолжает бесперебойно обслуживать уже привязанные существующие sticky-сессии до их естественного завершения.

**Десинхронизация сессий (Session Thrashing / Session Hopping)** — дефект маршрутизации в многоузловых кластерах балансировки, при котором запросы одного и того же клиента поочередно попадают на разные бэкенды из-за отсутствия синхронизации сессионных таблиц между независимыми балансировщиками.

**Режим отказа от переключения (Strict Mode / `no_fallback`)** — директивное поведение балансировщика, запрещающее автоматический переброс клиента на резервный узел в случае аварии закрепленного бэкенда. Балансировщик немедленно возвращает HTTP-статус `502 Bad Gateway`, предотвращая рассинхронизацию stateful-данных в распределенной системе.

**Синхронизация состояния кластера (`zone_sync`)** — протокол межсерверной репликации разделяемой памяти в Nginx Plus и Angie, синхронизирующий таблицы sticky-сессий между несколькими физическими или виртуальными хостами балансировки по TCP.

**Перекос сессионной нагрузки (Session Skew)** — неравномерное распределение трафика по узлам upstream-пула, вызванное концентрацией активных долгоживущих сессий на ограниченном числе серверов либо балансировкой по общему IP-адресу через NAT.

---

## Основные концепции и архитектура

### Архитектурная модель: Master-Worker и привязка сессий

Nginx реализует неблокирующую событийно-ориентированную многопроцессную модель. Все рабочие процессы (`workers`) обрабатывают входящие сетевые сокеты параллельно. Для корректной маршрутизации сессионных запросов критически важен уровень разделения состояния:

```
БЕЗ ОБЩЕЙ ПАМЯТИ (Nginx OSS без сторонних модулей):
┌─────────────────────────┐         ┌─────────────────────────┐
│ Worker Process 1        │         │ Worker Process 2        │
│ Хеш-таблица ключей      │         │ Хеш-таблица ключей      │
│ (Локальна для воркера)  │         │ (Локальна для воркера)  │
└────────────┬────────────┘         └────────────┬────────────┘
             │                                   │
             ▼                                   ▼
    [ Входящий запрос ]                 [ Входящий запрос ]
    (Привязка гарантируется только детерминированными алгоритмами: ip_hash, hash consistent)

С ОБЩЕЙ ПАМЯТЬЮ (Angie / Nginx Plus / zone):
┌─────────────────────────┐         ┌─────────────────────────┐
│ Worker Process 1        │         │ Worker Process 2        │
└────────────┬────────────┘         └────────────┬────────────┘
             │                                   │
             └─────────────────┬─────────────────┘
                               ▼
        ┌───────────────────────────────────────────────┐
        │        Shared Memory Zone (`zone` 10M)        │
        │ ┌───────────────────────────────────────────┐ │
        │ │ Session ID Table (LRU-список):            │ │
        │ │ - 'sess_9f81a7'  → Backend 10.0.1.11:8080 │ │
        │ │ - 'sess_4b2c19'  → Backend 10.0.1.12:8080 │ │
        │ ├───────────────────────────────────────────┤ │
        │ │ Server Flags:                             │ │
        │ │ - Node 10.0.1.11: UP                      │ │
        │ │ - Node 10.0.1.12: DRAIN (допуск sticky)   │ │
        │ └───────────────────────────────────────────┘ │
        └───────────────────────────────────────────────┘
```

### Жизненный цикл sticky-запроса

Прохождение сетевого пакета через балансировщик зависит от выбранного метода и наличия сессионных маркеров:

```
[ Клиентский запрос ]
         │
         ▼
Проверка наличия сессионного маркера в запросе?
   ├── [ НЕТ (Первичный запрос) ] ──┐
   │                                ▼
   │                  Выбор бэкенда по базовому алгоритму
   │                  (Round Robin, Least Conn, Random)
   │                                │
   │                                ▼
   │                  Передача запроса на бэкенд
   │                                │
   │                                ▼
   │                  Формирование ответа бэкендом
   │                                │
   │         ┌──────────────────────┴──────────────────────┐
   │         ▼ (sticky cookie)                             ▼ (sticky learn)
   │    Nginx генерирует куку                          Nginx перехватывает Set-Cookie,
   │    и добавляет в Set-Cookie                       заносит пару ID→Server в zone
   │         │                                             │
   │         └──────────────────────┬──────────────────────┘
   │                                ▼
   │                    Возврат клиенту с кукой
   │
   └── [ ДА (Повторный запрос с Cookie / Route) ] ──┐
                                                    ▼
                                   Поиск сервера в zone / хэш-кольце
                                                    │
                   ┌────────────────────────────────┴────────────────────────────────┐
                   ▼ [ Сервер найден и UP/DRAIN ]                                    ▼ [ Сервер DOWN ]
          Отправка запроса на                                           Задан флаг strict / no_fallback?
          закрепленный бэкенд                                                ├── [ ДА ] ──→ 502 Bad Gateway
                                                                             └── [ НЕТ ] ─→ Переключение на другой узел
                                                                                            (Сброс старой сессии)
```

### Сравнительный анализ механизмов прилипания

| Метод | Платформа | Механизм привязки | Нагрузка на память балансировщика | Зависимость от бэкенда | Поведение при падении узла |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`sticky cookie`** | Plus / Angie | Балансировщик выставляет собственную куку с зашифрованным/явным ID узла | Минимальная ($O(1)$, не требует таблицы сессий) | Полностью автономен от приложения | Переключение на новый узел или `502` при `no_fallback` |
| **`sticky learn`** | Plus / Angie | Парсинг `Set-Cookie` ответа и сохранение связки `SessionID → Node` в RAM | Зависит от числа сессий (~150 байт на сессию в `zone`) | Требует генерации Cookie приложением | Переключение или `502`; запись удаляется по таймауту |
| **`sticky route`** | Plus / Angie | Чтение URI-параметра или заголовка по правилам `map` | Минимальная ($O(1)$) | Приложение или клиент должны проставлять route-ID | Переключение или `502` |
| **`hash ... consistent`** | Nginx OSS / Plus / Angie | Консистентное хеширование значения куки приложения (`$cookie_name`) | Фиксированная (память под Ketama-кольцо серверов) | Приложение должно генерировать Cookie | Рехеширование только $1/N$ сессий на соседние узлы |
| **`ip_hash`** | Nginx OSS / Plus / Angie | Хеширование IP-адреса клиента (/24 для IPv4, полный адрес для IPv6) | Минимальная ($O(1)$) | Не зависит от приложения | Перенаправление трафика клиента на другой узел |
| **`sticky-module-ng`** | Nginx OSS (сторонний модуль) | Внедрение куки с MD5/SHA1-хешем сокета бэкенда | Минимальная (stateless) | Полностью автономен | Переключение или `502` при флаге `no_fallback` |

### Проблема масштабирования и кластерной высокой доступности (HA)

В высоконагруженных инфраструктурах уровень балансировки строится из двух и более серверов Nginx/Angie, объединенных виртуальным IP-адресом (VIP через Keepalived / VRRP) или протоколом BGP (ECMP Anycast).

```
                      [ Сеть / Клиенты ]
                              │
               ┌──────────────┴──────────────┐
               ▼ (Anycast BGP / VRRP VIP)    ▼
     ┌───────────────────┐         ┌───────────────────┐
     │ Nginx Balancer 01 │         │ Nginx Balancer 02 │
     └─────────┬─────────┘         └─────────┬─────────┘
               │                             │
               │   zone_sync (TCP порт 9000) │
               │◄───────────────────────────►│
               │                             │
       ┌───────┴─────────────────────────────┴───────┐
       ▼                                             ▼
┌──────────────┐                             ┌──────────────┐
│ Backend Node │                             │ Backend Node │
│ 10.0.1.11    │                             │ 10.0.1.12    │
└──────────────┘                             └──────────────┘
```

1. **Stateless-подход (`sticky cookie`, `sticky route`, `hash consistent`):**
   - Значение куки содержит зашифрованный или хэшированный идентификатор бэкенда либо ключ для хэш-кольца.
   - Любой экземпляр Nginx в кластере вычисляет один и тот же целевой узел независимо от других балансировщиков. Межсерверная репликация оперативной памяти **не требуется**.
2. **Stateful-подход (`sticky learn`):**
   - Таблица сессий создается локально в оперативной памяти того инстанса Nginx, через который прошел первый ответ бэкенда.
   - Если последующий запрос клиента через Anycast/VRRP маршрутизируется на второй балансировщик, сессия теряется (Session Hopping), так как второй балансировщик не имеет записи в своей локальной `zone`.
   - **Решение:** включение модуля синхронизации кластерного состояния (`zone_sync` в Nginx Plus и Angie) через выделенный TCP-порт синхронизации.

---

## Практические сценарии

### Сценарий 1: Корпоративная настройка sticky cookie (Nginx Plus и Angie)

Сценарий обеспечивает создание балансировщиком собственной защищенной куки с ограничением области видимости и флагами безопасности `HttpOnly`, `Secure` и `SameSite=Lax`.

```nginx
# /etc/nginx/conf.d/upstream_sticky_cookie.conf

upstream enterprise_backend {
    # Зона разделяемой памяти для синхронизации статусов серверов между воркерами
    zone upstream_enterprise_zone 256k;

    # Бэкенд-серверы кластера
    server 10.0.1.11:8080 max_fails=3 fail_timeout=10s;
    server 10.0.1.12:8080 max_fails=3 fail_timeout=10s;
    server 10.0.1.13:8080 max_fails=3 fail_timeout=10s;

    # Сессионная привязка по куке srv_id
    sticky cookie srv_id 
        expires=2h 
        domain=app.company.local 
        path=/ 
        httponly 
        secure 
        samesite=lax;

    # Пул постоянных TCP-соединений к бэкендам
    keepalive 32;
    keepalive_requests 1000;
    keepalive_timeout 60s;
}

server {
    listen 443 ssl default_server;
    server_name app.company.local;

    ssl_certificate /etc/ssl/certs/app.company.local.crt;
    ssl_certificate_key /etc/ssl/private/app.company.local.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://enterprise_backend;

        # Обеспечение работы keepalive-пула
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        # Передача служебных заголовков
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Таймауты ожидания ответа
        proxy_connect_timeout 5s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }
}
```

**Проверка синтаксиса и тест работы:**

```bash
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

nginx -s reload
# → 2026/10/17 15:45:00 [notice] signal process started

# Первый запрос: получение Set-Cookie от Nginx
curl -k -I https://app.company.local/
# → HTTP/1.1 200 OK
# → Set-Cookie: srv_id=a8f5c1e2b3c4; Expires=Sat, 17-Oct-2026 17:45:00 GMT; Path=/; Domain=app.company.local; Secure; HttpOnly; SameSite=Lax
```

### Сценарий 2: Отслеживание сессий приложения через sticky learn и zone_sync

Используется в архитектурах Java (Tomcat / Spring) или PHP (PHP-FPM), где сессионные маркеры генерируются самим бэкендом (`JSESSIONID`, `PHPSESSID`). Таблица соответствий хранится в `zone` и реплицируется между балансировщиками через `zone_sync`.

```nginx
# /etc/nginx/conf.d/upstream_sticky_learn.conf

upstream java_app_cluster {
    # Зона состояния серверов
    zone java_cluster_zone 128k;

    server 10.0.2.11:8080 max_fails=2 fail_timeout=5s;
    server 10.0.2.12:8080 max_fails=2 fail_timeout=5s;

    # Обучение на куке приложения JSESSIONID
    sticky learn
        create=$upstream_cookie_jsessionid
        lookup=$cookie_jsessionid
        zone=java_sessions_table:16m
        timeout=30m
        sync;

    keepalive 16;
}

# Блок синхронизации памяти кластера (Stream-контекст в /etc/nginx/nginx.conf)
# stream {
#     server {
#         listen 10.0.0.1:9000;
#         zone_sync;
#         zone_sync_server 10.0.0.2:9000;
#     }
# }
```

**Параметры директивы:**
- `create`: переменная ответа бэкенда, откуда Nginx считывает новый токен (из `Set-Cookie`).
- `lookup`: переменная запроса клиента, по которой производится поиск существующего сопоставления (из `Cookie`).
- `zone`: имя и размер сегмента разделяемой памяти. 16 МБ вмещает ~100 000 активных записей.
- `timeout`: время отсутствия активности по сессии, по истечении которого запись освобождается по алгоритму LRU.
- `sync`: директива синхронизации таблицы через модуль `ngx_stream_zone_sync_module`.

### Сценарий 3: Маршрутизация по идентификатору в URL или заголовке (sticky route)

Применяется в распределенных системах, где клиент получает закрепленный узел при логине и передает его в URL-параметре или служебном заголовке `X-Server-Route`.

```nginx
# /etc/nginx/conf.d/upstream_sticky_route.conf

# Маппинг для извлечения идентификатора маршрута из URI или заголовка
map $http_x_server_route $route_from_header {
    default $http_x_server_route;
}

map $arg_route $route_token {
    default $arg_route;
    ""      $route_from_header;
}

upstream partitioned_backends {
    zone partitioned_zone 128k;

    # Явное назначение идентификаторов маршрута серверам
    server 10.0.3.11:8080 route=node_a max_fails=2 fail_timeout=10s;
    server 10.0.3.12:8080 route=node_b max_fails=2 fail_timeout=10s;
    server 10.0.3.13:8080 route=node_c max_fails=2 fail_timeout=10s;

    # Маршрутизация по вычисленному токену
    sticky route $route_token;

    keepalive 16;
}

server {
    listen 80;
    server_name route.company.local;

    location / {
        proxy_pass http://partitioned_backends;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
    }
}
```

**Проверка маршрутизации:**

```bash
# Запрос с указанием целевого узла в GET-параметре
curl -s http://route.company.local/?route=node_b | grep "Server-ID"
# → Server-ID: 10.0.3.12

# Запрос с указанием целевого узла в HTTP-заголовке
curl -s -H "X-Server-Route: node_a" http://route.company.local/ | grep "Server-ID"
# → Server-ID: 10.0.3.11
```

### Сценарий 4: Production-Grade Sticky Sessions в Nginx Open Source (OSS)

В открытой версии Nginx отсутствует нативная директива `sticky`. Использование чистого `hash $cookie_jsessionid consistent;` содержит критический дефект архитектуры: **при первом запросе клиента кука отсутствует (`""`), поэтому все новые пользователи попадают на один и тот же единственный бэкенд**, создавая лавинообразную перегрузку ("проблема холодного старта").

Решение уровня Senior DevOps/SRE: комбинирование директив `map` и `hash ... consistent`:

```nginx
# /etc/nginx/conf.d/oss_sticky_consistent_hash.conf

# Формирование ключа хеширования: если куки нет, хешируем по уникальному ID запроса или IP
map $cookie_APP_SESSION $sticky_distribution_key {
    default $cookie_APP_SESSION;
    # На первом запросе используем комбинацию IP и порта либо request_id для равномерного размазывания
    ""      $remote_addr;
}

upstream oss_stateful_cluster {
    # Консистентное хеширование по сбалансированному ключу
    hash $sticky_distribution_key consistent;

    server 10.0.4.11:8080 max_fails=3 fail_timeout=10s;
    server 10.0.4.12:8080 max_fails=3 fail_timeout=10s;
    server 10.0.4.13:8080 max_fails=3 fail_timeout=10s;

    keepalive 32;
}

server {
    listen 80;
    server_name oss-sticky.company.local;

    location / {
        proxy_pass http://oss_stateful_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # Отказоустойчивый переход при аварии сервера во время обработки
        proxy_next_upstream error timeout http_502 http_503;
        proxy_next_upstream_tries 2;
    }
}
```

### Сценарий 5: Использование стороннего динамического модуля nginx-sticky-module-ng (Nginx OSS)

Для систем на Nginx Open Source, требующих создания полноценных сессионных cookie без коммерческой лицензии, применяется проверенный динамический модуль `nginx-sticky-module-ng`.

```nginx
# /etc/nginx/nginx.conf (в начале файла конфигурации)
# load_module modules/ngx_http_sticky_module.so;

upstream third_party_sticky_pool {
    server 10.0.5.11:8080;
    server 10.0.5.12:8080;

    # Синтаксис директивы стороннего модуля:
    # name: имя cookie (по умолчанию route)
    # hash: алгоритм хеширования (index, md5, sha1)
    # no_fallback: при падении сервера возвращать 502 вместо сброса на другой узел
    sticky name=CUSTOM_ROUTE 
           domain=company.local 
           path=/ 
           expires=1h 
           hash=sha1 
           no_fallback;

    keepalive 16;
}
```

### Сценарий 6: Плавный вывод бэкенда на обслуживание (Connection Draining)

При плановом обновлении версии приложения на бэкенде недопустимо грубо обрывать сессии клиентов. Включение режима `drain` позволяет серверу дообслужить текущих пользователей, не принимая новых.

#### Вариант А: Статическая конфигурация (Nginx Plus / Angie)

```nginx
upstream maintenance_cluster {
    zone maint_zone 128k;

    # Сервер переведен в режим обслуживания: новые клиенты не назначаются, старые обслуживаются
    server 10.0.6.11:8080 drain;
    server 10.0.6.12:8080;
    server 10.0.6.13:8080;

    sticky cookie srv_id expires=1h domain=.company.local path=/;
}
```

#### Вариант Б: Динамическое управление через REST API без reload (Angie / Nginx Plus)

```bash
# 1. Просмотр текущего статуса серверов в пуле maintenance_cluster
curl -s http://127.0.0.1:8000/api/http/upstreams/maintenance_cluster/servers | jq .

# 2. Перевод сервера с индексом 0 (10.0.6.11:8080) в режим DRAIN на лету
curl -X PATCH \
     -H "Content-Type: application/json" \
     -d '{"drain": true}' \
     http://127.0.0.1:8000/api/http/upstreams/maintenance_cluster/servers/0
# → {"id":0,"server":"10.0.6.11:8080","weight":1,"max_conns":0,"max_fails":1,"fail_timeout":"10s","backup":false,"down":false,"drain":true}

# 3. Мониторинг убывания активных сессий на выводимом узле
watch -n 1 'curl -s http://127.0.0.1:8000/api/http/upstreams/maintenance_cluster/servers/0 | jq "{server, active: .active, requests: .requests}"'

# 4. Возврат сервера в штатный режим после завершения регламентных работ
curl -X PATCH \
     -H "Content-Type: application/json" \
     -d '{"drain": false}' \
     http://127.0.0.1:8000/api/http/upstreams/maintenance_cluster/servers/0
# → {"id":0,"server":"10.0.6.11:8080", ... ,"drain":false}
```

### Сценарий 7: SRE-наблюдаемость и логирование эффективности Sticky Sessions

Для мониторинга качества работы сессионной привязки в структурированный журнал доступа Nginx добавляются переменные состояния сессии, адреса фактического бэкенда и сетевые задержки.

```nginx
# /etc/nginx/conf.d/sticky_monitoring.conf

# Формат лога с отслеживанием статуса сессионной липкости
# В Angie поддерживается специализированная переменная $upstream_sticky_status (HIT, MISS, NEW, BYPASS)
log_format sticky_analytics escape=json '{'
    '"time_local":"$time_iso8601",'
    '"remote_addr":"$remote_addr",'
    '"request_method":"$request_method",'
    '"request_uri":"$request_uri",'
    '"status":$status,'
    '"upstream_addr":"$upstream_addr",'
    '"upstream_status":"$upstream_status",'
    '"upstream_connect_time":"$upstream_connect_time",'
    '"upstream_response_time":"$upstream_response_time",'
    '"sticky_cookie_val":"$cookie_srv_id",'
    '"sticky_status":"$upstream_sticky_status"'
'}';

server {
    listen 80;
    server_name monitoring.company.local;

    access_log /var/log/nginx/sticky_access.log sticky_analytics;

    location / {
        proxy_pass http://enterprise_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

---

## Операции и команды

### Валидация конфигурации и безопасная перезагрузка

```bash
# 1. Проверка синтаксиса и целостности всех конфигурационных файлов
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Вывод полной итоговой конфигурации с раскрытием всех include-директив
nginx -T | grep -A 15 "sticky"

# 3. Грациозная перезагрузка конфигурации (Master передает сигнал воркерам без сброса TCP-сокетов)
nginx -s reload
# → 2026/10/17 15:50:12 [notice] signal process started
```

### Тестирование сессионной привязки и отказоустойчивости утилитой curl

```bash
# Шаг 1: Выполнение первого запроса с сохранением полученных кук в jar-файл
curl -k -i -s -c /tmp/cookie_jar.txt https://app.company.local/api/whoami | grep -i "Set-Cookie"
# → Set-Cookie: srv_id=node_01_hash; Path=/; Domain=app.company.local; Secure; HttpOnly; SameSite=Lax

# Шаг 2: Просмотр содержимого сохраненного файла кук
cat /tmp/cookie_jar.txt
# → app.company.local   FALSE   /   TRUE    1792243200  srv_id  node_01_hash

# Шаг 3: Выполнение серии из 10 повторных запросов с передачей сохраненного cookie
for i in {1..10}; do
    curl -k -s -b /tmp/cookie_jar.txt https://app.company.local/api/whoami | jq -r .handled_by
done | sort | uniq -c
# →     10 10.0.1.11:8080
# (Все 10 запросов гарантированно направлены на закрепленный узел)

# Шаг 4: Тестирование отказоустойчивости (Failover)
# Имитируем падение закрепленного бэкенда 10.0.1.11
ssh node-01 "systemctl stop backend-app"

# Запрос с прежней кукой в режиме без strict/no_fallback
curl -k -s -b /tmp/cookie_jar.txt https://app.company.local/api/whoami | jq -r .handled_by
# → 10.0.1.12:8080
# (Nginx прозрачно перенаправил запрос на живой узел 10.0.1.12)

# Запрос с прежней кукой при включенном strict/no_fallback
curl -k -i -s -b /tmp/cookie_jar.txt https://app.company.local/api/whoami | head -n 1
# → HTTP/1.1 502 Bad Gateway
```

### SRE-команды анализа журналов и метрик

```bash
# 1. Расчет коэффициента перекоса (Session Skew) по бэкендам за последний час
awk '{print $NF}' /var/log/nginx/access.log | cut -d: -f1 | sort | uniq -c | awk '
{
    count[NR] = $1;
    server[NR] = $2;
    total += $1;
}
END {
    avg = total / NR;
    printf "=== Анализ распределения нагрузки (Total: %d, Avg: %.1f) ===\n", total, avg;
    for (i = 1; i <= NR; i++) {
        dev = ((count[i] - avg) / avg) * 100;
        printf "Сервер %-15s: %8d запросов (%+6.1f%% от среднего)\n", server[i], count[i], dev;
    }
}'

# 2. Подсчет соотношения статусов sticky-сессий (Angie лог)
grep -o '"sticky_status":"[^"]*"' /var/log/nginx/sticky_access.log | sort | uniq -c | sort -rn
# → 45210 "sticky_status":"HIT"
# →  8450 "sticky_status":"NEW"
# →   312 "sticky_status":"MISS"

# 3. Выявление 502/504 ошибок, связанных с привязанными сессиями при отказе серверов
awk -F'"' '$10 ~ /^(502|504)$/ {print $0}' /var/log/nginx/access.log | tail -n 20

# 4. Проверка ошибок нехватки памяти под сессионную зону в error.log
grep -i "could not allocate shared memory" /var/log/nginx/error.log
# → 2026/10/17 15:52:00 [alert] 1234#1234: could not allocate shared memory in sticky learn "java_sessions_table"
```

---

## Диагностика и устранение неполадок

### Матрица типичных сбоев

| Симптом | Корневая причина (Root Cause) | Метод подтверждения / Диагностика | Решение (Remediation) |
| :--- | :--- | :--- | :--- |
| **`502 Bad Gateway` при обращении клиентов** | Сервер, к которому привязан клиент, упал, а в конфигурации задан `strict` или `no_fallback` | `curl -v -b "srv_id=..." https://...`<br>Поиск `502` в access.log | Если потеря сессии допустима — отключить `strict`/`no_fallback`. Проверить доступность бэкенда (`systemctl status`). Настроить адекватные `max_fails` и `fail_timeout`. |
| **Сессия не удерживается, клиент «прыгает» по серверам** | 1. Браузер отклоняет Cookie из-за `Secure` при обращении по HTTP.<br>2. Несовпадение домена (`domain`) или пути (`path`).<br>3. Кластер из нескольких Nginx без `zone_sync`. | Инспекция заголовков через `curl -I`. Проверка `Storage -> Cookies` в браузере. Анализ логов обоих балансировщиков. | Выставлять флаг `secure` только при работе по HTTPS. Задать `path=/`. Для `learn` в кластере настроить `zone_sync` или перейти на `sticky cookie`. |
| **Катастрофический перекос нагрузки (Session Skew > 80%)** | 1. Балансировка Nginx OSS по `ip_hash`, когда тысячи клиентов идут через единый корпоративный прокси/NAT.<br>2. Использование `hash $cookie` без fallback на пустую куку. | Команда анализа распределения `awk` по логам. Проверка поля `$remote_addr`. | 1. Заменить `ip_hash` на `hash $sticky_distribution_key consistent` со fallback через `map`.<br>2. Использовать `sticky cookie`. |
| **Alert: `could not allocate shared memory`** | Сегмент `zone` в директиве `sticky learn` переполнен, а старые сессии не успевают вытесняться | Поиск строки в `/var/log/nginx/error.log` | Увеличить размер зоны (`zone=...:64m`). Уменьшить `timeout` неактивных сессий (например, с `2h` до `30m`). |
| **Потеря сессий всеми пользователями при reload/restart** | Таблица сессий находится только в RAM и сбрасывается при рестарте службы Nginx | Проверка времени перезапуска процесса `ps aux \| grep nginx` | В Nginx Plus/Angie использовать сохранение состояния upstream: директива `state /var/lib/nginx/state/upstream.conf;`. |
| **Частый сброс сессий при масштабировании пула** | В Nginx OSS используется `hash` без ключевого слова `consistent` | Анализ конфигурации upstream на отсутствие `consistent` | Добавить флаг `consistent` к директиве `hash` для использования консистентного кольца Ketama. |
| **Сброс сессий при междоменных переходах** | В куке выставлен строгий атрибут `SameSite=Strict`, блокирующий отправку куки при внешних редиректах | Анализ заголовка `Set-Cookie` в ответе сервера | Смягчить политику безопасности до `SameSite=Lax`. |

### Диагностические сценарии

#### Диагностика переполнения Shared Memory Zone

При переполнении памяти таблицы сессий `sticky learn` балансировщик прекращает запоминать новые сессии, что приводит к нарушению логики stateful-приложений:

```bash
# 1. Поиск критических событий распределения памяти
grep -E "could not allocate|no memory" /var/log/nginx/error.log

# 2. Проверка утилизации зон памяти через статусную панель или API Angie
curl -s http://127.0.0.1:8000/api/http/zones | jq .

# 3. Расчет требуемого объема памяти:
# Формула: Записи = Память_байт / ~160 байт
# 1 МБ ~ 6 500 одновременных сессий
# 16 МБ ~ 100 000 одновременных сессий
# 64 МБ ~ 400 000 одновременных сессий
```

#### Диагностика отсутствия передачи Cookie браузером

Если Nginx отдает `Set-Cookie`, но браузер в последующих запросах не включает заголовок `Cookie`:

```bash
# Тест 1: Проверка атрибута Secure при тестировании без валидного HTTPS
curl -k -I https://app.company.local/ | grep -i "set-cookie"
# Если в ответе присутствует "Secure", а тестирование идет по незащищенному каналу HTTP, браузер отклонит куку

# Тест 2: Проверка атрибута Domain
# Если Domain=.app.company.local, а запрос отправлен на http://company.local, кука не применится
```

---

## Лучшие практики

### Архитектура и планирование емкости

1. **Формула расчета разделяемой памяти для `sticky learn`:**
   Каждая активная сессия в разделяемой памяти требует структуру связного списка LRU, хеш-таблицы и буфер строковых значений. 
   $$\text{RAM}_{\text{bytes}} \approx N_{\text{sessions}} \times (S_{\text{overhead}} + L_{\text{cookie}} + L_{\text{ip\_port}})$$
   - Средний оверхед ядра Nginx/Angie на одну запись: $\approx 128 - 160$ байт.
   - Для пула на $100\,000$ одновременных активных пользователей минимальный размер зоны составляет:
     $$100\,000 \times 160 \text{ байт} = 16\,000\,000 \text{ байт} \approx 16\text{ МБ}$$
   - Рекомендуется закладывать двукратный запас по емкости (`zone=sessions:32m`), чтобы исключить преждевременное LRU-вытеснение активных сессий при пиках трафика.

2. **Приоритет Stateless-архитектуры над Sticky:**
   Sticky Sessions нарушают равномерность утилизации вычислительных ресурсов кластера и усложняют автомасштабирование. 
   - **Инженерная рекомендация:** использовать Sticky Sessions как временную переходную меру для легаси-приложений. Для современных сервисов сессионные данные необходимо выносить во внешние распределенные хранилища in-memory (Redis, KeyDB, Dragonfly) с репликацией Sentinel/Cluster, что позволяет перевести балансировщик на абсолютно stateless алгоритмы `least_conn` или `random two`.

3. **Синхронизация Keepalive и Sticky:**
   Привязка сессии логически изолирована от физических сокетов. Обязательно настраивайте `keepalive` в блоке `upstream` совместно со sticky-сессиями:
   ```nginx
   upstream app_pool {
       zone app_pool_zone 128k;
       server 10.0.1.11:8080;
       server 10.0.1.12:8080;
       sticky cookie srv_id;
       keepalive 32;
   }
   ```
   Это снижает задержку на TCP/TLS-рукопожатия между Nginx и целевым бэкендом, даже когда клиент выполняет разнесенные во времени запросы.

### Безопасность

1. **Защита топологии инфраструктуры (Anti-Information Disclosure):**
   Никогда не используйте реальные IP-адреса или имена хостов в значениях sticky cookie. 
   - В Nginx Plus и Angie значение куки по умолчанию генерируется в виде шестнадцатеричного хеша.
   - В сторонних модулях и `sticky route` применяйте абстрактные токены (`node_a`, `node_b`) либо алгоритмы шифрования с секретом (`secret / hmac`), чтобы злоумышленник не мог составить карту внутренней локальной сети.

2. **Обязательные флаги защиты Cookie:**
   Сессионная кука балансировщика должна быть защищена на уровне браузера:
   - `httponly`: предотвращает хищение идентификатора через XSS-атаки с помощью JavaScript (`document.cookie`).
   - `secure`: гарантирует передачу куки исключительно по шифрованному каналу TLS/HTTPS, исключая перехват в открытых Wi-Fi/Ethernet-сетях (Man-in-the-Middle).
   - `samesite=lax` или `samesite=strict`: защищает пользователя от межсайтовой подделки запроса (CSRF). Для стандартных приложений оптимален режим `lax`.

3. **Защита от таргетированного DoS через Route Poisoning:**
   При использовании `sticky route` злоумышленник может слать миллионы запросов с жестко заданным заголовком `X-Server-Route: node_a`, стремясь перегрузить конкретный инстанс. Обязательно сопровождайте маршрутизацию жесткими лимитами скорости (`limit_req_zone`).

### Эксплуатация (SRE)

1. **Контроль коэффициента перекоса (Session Skew):**
   Настройте в Prometheus / VictoriaMetrics сбор метрик распределения запросов по upstream-узлам. Если отношение максимального числа запросов к минимальному в пуле превышает $1.5$ (перекос более $30\%$), необходимо:
   - Проверить наличие бот-трафика или поисковых роботов с единых IP-адресов.
   - Проверить корректность времени жизни куки (`expires`).
   - Для Nginx OSS — убедиться в наличии директивы `consistent` в `hash`.

2. **Регламент вывода серверов в регламентное обслуживание:**
   При выполнении Rolling Update для stateful-приложений:
   1. Перевести узел в режим `drain` (через API или конфигурацию).
   2. Выждать интервал таймаута сессии (`timeout` или `expires`), чтобы активные пользователи завершили работу.
   3. Убедиться через API, что счетчик `active connections` узла равен нулю.
   4. Остановить приложение, накатить обновление и запустить сервис.
   5. Снять флаг `drain`.

3. **Интеграция с проверками доступности (Health Checks):**
   Сочетайте sticky-сессии с активными проверками доступности (`health_check` в Plus/Angie):
   ```nginx
   location / {
       proxy_pass http://enterprise_backend;
       health_check interval=2s fails=2 passes=2 uri=/healthz;
   }
   ```
   При падении бэкенда Nginx снимет трафик с узла до того, как клиент столкнется с таймаутом соединения.

---

## Дополнительная информация

### Связанные документы

- **[Обзор и концепции балансировки](./overview_concepts.md)** — архитектура upstream, зоны разделяемой памяти и обработка трафика.
- **[Алгоритмы балансировки](./algorithms.md)** — детальный разбор циклических, адаптивных и хеширующих методов (`least_conn`, `least_time`, `hash consistent`, `random two`).
- **[Практическая конфигурация балансировки](./practical_configuration.md)** — типовые production-конфигурации, управление буферизацией, пулы `keepalive` и переключение сбоев `proxy_next_upstream`.
- **[Проверки доступности и мониторинг](./health_checks_and_monitoring.md)** — настройка активных и пассивных проверок работоспособности узлов upstream.
- **[Дополнительная информация и сравнение](./additional_info_and_comparisons.md)** — глубокое сравнение функционала Nginx Open Source, Nginx Plus и Angie.

### Инженерные примечания

- **Несовместимость директив:** В рамках одного блока `upstream` директива `sticky` взаимно исключает использование алгоритмов `ip_hash`, `hash`, `least_conn` и `random`. При объявлении `sticky` базовым алгоритмом распределения новых (первичных) сессий становится взвешенный Round Robin.
- **Ограничения Nginx Open Source:** В Nginx OSS отсутствует встроенная поддержка директивы `sticky` и механизма `drain`. Полноценная сессионная привязка в OSS достигается либо через консистентное хеширование (`hash $var consistent;` с fallback через `map`), либо компиляцией со сторонним динамическим модулем `nginx-sticky-module-ng`.
- **Синхронизация памяти в Angie и Nginx Plus:** Для обеспечения бесшовной сессионной привязки в кластерах с несколькими балансировщиками (VRRP / BGP Anycast) при использовании `sticky learn` обязательно настраивается модуль репликации оперативной памяти `zone_sync` в блоке `stream`.
