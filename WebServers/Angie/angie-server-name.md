# Виртуальные хосты и server_name в Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

**Виртуальный хост (Virtual Host / Server Block)** — логическая единица конфигурации веб-сервера Angie (блок `server { ... }`), изолирующая обработку сетевых запросов для конкретного набора доменных имен, IP-адресов и портов на едином физическом сервере или экземпляре ОС.

**Директива `server_name`** — директива контекста `server`, определяющая список доменных имен, масок (wildcards) или регулярных выражений (PCRE), на основании которых входящий запрос привязывается к данному виртуальному серверу по значению HTTP-заголовка `Host` либо расширения TLS SNI (Server Name Indication).

**Параметр `default_server`** — флаг директивы `listen`, явно назначающий текущий блок `server` обработчиком по умолчанию для указанной комбинации `IP-адрес:порт`. К нему направляются все запросы, чье доменное имя не совпало ни с одним другим блоком `server_name` на этом сокете.

**Хэш-таблицы виртуальных хостов (`server_names_hash`)** — внутренние статические структуры данных ядра Angie, оптимизирующие поиск виртуального хоста в оперативной памяти. Управляются директивами `server_names_hash_bucket_size` и `server_names_hash_max_size`.

**Переменная `$host`** — нормализованное имя хоста в нижнем регистре. Извлекается из строки запроса (если передан абсолютный URI), либо из HTTP-заголовка `Host` (с отсечением порта), либо приравнивается к первичному `server_name` блока при отсутствии заголовка.

**Переменная `$http_host`** — точное строковое значение заголовка `Host`, отправленное клиентом в HTTP-запросе, включая номер порта (при его наличии).

**Переменная `$server_name`** — первичное (первое по списку) имя виртуального хоста из директивы `server_name` того блока, который был выбран для обработки запроса.

**Переменная `$ssl_server_name`** — доменное имя, переданное клиентским приложением на этапе TLS-рукопожатия в расширении Server Name Indication (SNI) сообщения `ClientHello`.

**Директива `ssl_reject_handshake`** — механизм принудительного разрыва TLS-соединения на этапе `ClientHello` без отправки серверного сертификата клиенту, если имя из SNI не обслуживается сервером.

**HTTP/2 Connection Coalescing** — поведение клиентов HTTP/2 и HTTP/3, при котором одно активное TLS-соединение повторно используется для запросов к разным доменным именам, если они резолвятся в один IP-адрес и покрываются одним TLS-сертификатом (SAN). При несоответствии конфигураций сервер возвращает статус `421 Misdirected Request`.

---

## Архитектура и принцип работы

### 1. Двухфазная маршрутизация входящего соединения

Маршрутизация входящего трафика в архитектуре Angie разделена на два уровня: сетевой (L4/TLS) и прикладной (L7 HTTP).

```
[ Входящее TCP/TLS/QUIC соединение ]
                 │
                 ▼
     [ 1. Анализ сокета (IP:Port) ]
     Сверка адреса и порта с директивами listen
                 │
        ┌────────┴────────┐
   (Чистый TCP)       (TLS / HTTPS)
        │                 │
        │                 ▼
        │        [ 2. Фаза TLS SNI ]
        │        Чтение имени из ClientHello.
        │        Выбор server-блока и сертификата.
        │        Если SNI неизвестен: default_server / ssl_reject_handshake.
        │                 │
        └────────┬────────┘
                 │
                 ▼
     [ 3. Фаза HTTP-парсинга ]
     Чтение заголовка Host и строки запроса.
     Повторный поиск server_name в хэш-таблицах сокета.
                 │
                 ▼
     [ 4. Выбор финального server-блока ]
     Маршрутизация в location и обработка запроса
```

1. **Фаза L4 (IP:Port):** При поступлении соединения ядро Angie сопоставляет локальный IP-адрес и порт сокета со всеми объявленными директивами `listen`. Выделяется изолированная группа виртуальных серверов, привязанных к данному сокету.
2. **Фаза TLS Handshake (SNI):** Для защищенных портов (`listen ... ssl`) Angie считывает поле SNI из пакета `ClientHello`. На этом этапе сервер должен предъявить сертификат:
   - Выполняется предварительный поиск виртуального сервера по SNI для выбора `ssl_certificate` и параметров шифрования.
   - Если совпадений нет, активируется `default_server`. Если в нем включена директива `ssl_reject_handshake on`, Angie прерывает соединение сигналом `TLS alert: unrecognized_name`, предотвращая утечку чужих сертификатов.
3. **Фаза L7 HTTP (Host Header):** После расшифровки трафика (или сразу при HTTP/1.x) Angie считывает HTTP-заголовок `Host`:
   - Выполняется финальный поиск виртуального хоста.
   - **Важная особенность:** Если клиент в TLS SNI передал `site-a.example.com`, а внутри HTTP-сессии отправил `Host: site-b.example.com` (ситуация Domain Fronting или Connection Coalescing), Angie перенаправит запрос в конфигурацию `site-b.example.com`, если оба блока размещены на одном сокете `IP:Port`.

---

### 2. Внутренний алгоритм поиска server_name в ядре Angie

При компиляции конфигурации мастер-процесс Angie строит для каждого прослушиваемого сокета (`ngx_http_conf_addr_t`) оптимизированные структуры данных.

Поиск виртуального хоста выполняется строго по следующему приоритету:

```
[ Запрос с именем хоста ]
          │
          ▼
1. Поиск точного совпадения (Exact Match Hash) ────[ Найдено ]──► ВЫБРАН ХОСТ
          │ (Нет)
          ▼
2. Поиск префиксного Wildcard (*.example.com)  ────[ Найдено ]──► ВЫБРАН ХОСТ
          │ (Нет)
          ▼
3. Поиск суффиксного Wildcard (mail.*)         ────[ Найдено ]──► ВЫБРАН ХОСТ
          │ (Нет)
          ▼
4. Последовательный перебор PCRE Regex (~^...) ────[ Найдено ]──► ВЫБРАН ХОСТ
          │ (Нет)
          ▼
5. default_server для данного IP:Port          ────────────────► ВЫБРАН ХОСТ
```

#### Этап 1: Точное совпадение (Exact Names Hash)
Имя ищется в статической хэш-таблице `ngx_hash_t`. Сложность поиска — $O(1)$. Поиск выполняется быстрее всех остальных методов, так как имя хэшируется целиком.

#### Этап 2: Префиксный Wildcard (`*.example.com`)
Используется хэш-таблица суффиксов `dns_wildcards_head`. Имя хоста разбивается на доменные сегменты справа налево (от TLD к поддоменам: `com` → `example` → `*`). Выбирается **наиболее специфичный (самый длинный)** шаблон. Например, для `app.dev.example.com` шаблон `*.dev.example.com` выиграет у `*.example.com`.

#### Этап 3: Суффиксный Wildcard (`www.example.*`)
Используется хэш-таблица префиксов `dns_wildcards_tail`. Имя хоста проверяется слева направо. Выбирается наиболее специфичный (самый длинный) шаблон.

#### Этап 4: Регулярные выражения (PCRE Regular Expressions)
Если хэш-таблицы не дали совпадения, управление передается массиву скомпилированных регулярных выражений (`ngx_http_regex_t`).
- Регулярные выражения проверяются **строго последовательно** сверху вниз по тексту конфигурации.
- Первое совпавшее регулярное выражение немедленно выигрывает; дальнейшая проверка останавливается.
- Если регулярное выражение содержит именованные (`(?<domain>...)`) или позиционные (`$1`, `$2`) захваты, соответствующие переменные создаются и становятся доступны внутри выбранного блока `server`.

#### Этап 5: Сервер по умолчанию (`default_server`)
Если ни одно имя и ни одно регулярное выражение не совпали с запросом:
- Выбирается блок, помеченный параметром `default_server` в директиве `listen`.
- Если параметр `default_server` не указан явно ни в одном блоке для данного адреса/порта, обработчиком по умолчанию становится **первый по порядку чтения конфигурации** блок `server` с соответствующим `listen`.

---

### 3. Структура памяти и тюнинг хэш-таблиц (server_names_hash)

Для хранения точных имен и wildcard-шаблонов Angie выделяет статические хэш-таблицы при старте или перезагрузке (`reload`).

| Директива | Область | По умолчанию | Описание |
|:---|:---|:---|:---|
| `server_names_hash_bucket_size` | `http` | 32 / 64 / 128 байт | Размер корзины (bucket) хэш-таблицы. Должен быть равен или кратен размеру линии кэша процессора (L1/L2 Cache Line). |
| `server_names_hash_max_size` | `http` | 512 | Максимальный суммарный размер хэш-таблицы (количество корзин). |

```
+-----------------------------------------------------------------+
|               server_names_hash_bucket (64 байта)               |
+--------------------------------+--------------------------------+
| ngx_hash_elt_t (хеш, смещение) | Имя: "api.billing.example.com" |
+--------------------------------+--------------------------------+
| ngx_hash_elt_t (хеш, смещение) | Имя: "cdn.static.example.com"  |
+--------------------------------+--------------------------------+
| Указатель на следующий блок / NULL                              |
+-----------------------------------------------------------------+
```

#### Механика ошибок хэш-таблицы:
1. Если длина доменного имени превышает `server_names_hash_bucket_size` (с учетом служебных заголовков структуры ядра), Angie завершает валидацию конфигурации с ошибкой:
   ```text
   could not build the server_names_hash, you should increase server_names_hash_bucket_size: 64
   ```
2. Если в конфигурации объявлено несколько сотен или тысяч доменов и возникают коллизии хэшей, Angie пытается увеличить количество корзин вплоть до лимита `server_names_hash_max_size`. Если лимит исчерпан, запуск прерывается.
3. **Правило оптимизации под архитектуру CPU:** Значение `server_names_hash_bucket_size` всегда задается степенью двойки: `64` или `128`. На процессорах x86_64 и AArch64 размер кэш-линии равен 64 байтам. Выравнивание корзины по размеру кэш-линии гарантирует, что поиск хэш-элемента выполняется за одно обращение к оперативной памяти без штрафов межстрочного промаха кэша (Cache Miss).

---

### 4. Сравнение переменных маршрутизации: $host, $http_host, $server_name, $ssl_server_name

Понимание различий между переменными критично для исключения уязвимостей Host Header Injection, корректного кэширования и генерации редиректов.

| Параметр | `$host` | `$http_host` | `$server_name` | `$ssl_server_name` |
|:---|:---|:---|:---|:---|
| **Источник данных** | Заголовок `Host` или строка запроса (нормализованный) | Заголовок `Host` (сырой) | Директива `server_name` в конфиге | SNI из TLS ClientHello |
| **Регистр символов** | Всегда приведен к нижнему | Как передал клиент (может быть `ExAmPlE.cOm`) | Как задан в конфигурации | Как передал клиент в SNI |
| **Наличие порта** | **Всегда отсекается** (`example.com`) | **Сохраняется**, если был передан (`example.com:8443`) | Отсутствует | Отсутствует |
| **При отсутствии заголовка Host** | Принимает значение первичного `server_name` | Пустая строка (`""`) | Первичное имя выбранного блока | Домен из SNI (или пусто, если TLS без SNI / HTTP) |
| **Рекомендованное применение** | Внутренняя маршрутизация, `proxy_set_header Host $host;`, редиректы | Логирование клиентских заголовков | Идентификация виртуального сервера в логах, `fastcgi_param SERVER_NAME` | Проверка соответствия SNI и заголовка Host (Anti-Domain-Fronting) |

---

### 5. Поведение директивы server_name_in_redirect

Директива определяет, какое имя хоста сервер будет использовать при формировании абсолютных редиректов (например, при обращении к каталогу без завершающего слеша `/admin` → `/admin/`):

```nginx
server_name_in_redirect off; # По умолчанию в современных версиях
```

- **`off` (рекомендуется):** Angie использует значение переменной `$host` (то есть имя, запрошенное клиентом). Пользователь остается на том домене, к которому обращался.
- **`on`:** Angie подставляет первое имя, указанное в директиве `server_name` текущего блока, независимо от того, через какой алиас или wildcard пришел клиент.

---

## Практические сценарии и конфигурация

### Сценарий 1: Защищенный сервер по умолчанию (Hardened Catch-All) для HTTP, HTTPS и HTTP/3

**Задача:** Заблокировать обращения напрямую по IP-адресу, нелегитимные сканеры уязвимостей и запросы с неизвестными доменными именами. Защитить инфраструктуру от утечки доменных имен через выдачу чужих TLS-сертификатов.

```nginx
# /etc/angie/http.d/00-default.conf

# 1. Обработчик по умолчанию для незашифрованного HTTP (порт 80)
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    # Запрет доступа без заголовка Host или по неизвестному имени
    # Код 444 немедленно закрывает TCP-соединение без отправки HTTP-ответа
    return 444;
}

# 2. Обработчик по умолчанию для TLS (порт 443 TCP) и QUIC/HTTP/3 (порт 443 UDP)
server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    listen 443 quic default_server;
    listen [::]:443 quic default_server;
    server_name _;

    # Разрыв рукопожатия TLS/QUIC без передачи сертификата клиенту
    ssl_reject_handshake on;

    # Фиктивные заглушки сертификатов на случай старых клиентов без поддержки SNI
    ssl_certificate     /etc/angie/ssl/dummy.crt;
    ssl_certificate_key /etc/angie/ssl/dummy.key;

    return 444;
}
```

Генерация самоподписанного фиктивного сертификата для заглушки (минимальный размер для экономии памяти):
```bash
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /etc/angie/ssl/dummy.key \
  -out /etc/angie/ssl/dummy.crt \
  -subj "/CN=unconfigured.local"
# → Generating a RSA private key
```

---

### Сценарий 2: Многодоменный хостинг с каноническими редиректами (SEO & FQDN Consolidation)

**Задача:** Обеспечить строгую канонизацию доменных имен. Все обращения по HTTP, а также через альтернативные домены (`example.org`, `example.net`) и поддомен `www.example.com` должны перенаправляться на единый канонический адрес `https://example.com` со статусом `301 Moved Permanently`.

```nginx
# /etc/angie/http.d/example.com.conf

# 1. Принудительный редирект всего незашифрованного трафика HTTP -> HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name example.com www.example.com example.org www.example.org example.net;

    # Сохраняем запрошенный Host и полный URI запроса
    return 301 https://$host$request_uri;
}

# 2. Редирект неканонических HTTPS-хостов на единый канонический домен
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name www.example.com example.org www.example.org example.net;

    ssl_certificate     /etc/angie/ssl/example.com_bundle.crt;
    ssl_certificate_key /etc/angie/ssl/example.com.key;

    # Принудительная склейка на основной домен
    return 301 https://example.com$request_uri;
}

# 3. Основной канонический виртуальный хост
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name example.com;

    ssl_certificate     /etc/angie/ssl/example.com_bundle.crt;
    ssl_certificate_key /etc/angie/ssl/example.com.key;

    root /var/www/example.com/public;
    index index.html index.htm;

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

---

### Сценарий 3: Динамическая маршрутизация Wildcard-поддоменов с регулярными выражениями

**Задача:** Реализовать мультиарендную систему (Multi-tenant), где каждый клиент получает поддомен вида `<tenant>.app.example.com`. Корневой каталог или бэкенд вычисляется динамически из имени хоста с валидацией имени для исключения атак обхода путей (Path Traversal).

```nginx
# /etc/angie/http.d/multitenant.conf

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;

    # Регулярное выражение с именованным захватом в переменную $tenant
    # Разрешены только символы a-z, цифры 0-9 и дефис длиной от 2 до 32 символов
    server_name ~^(?<tenant>[a-z0-9][a-z0-9\-]{1,31})\.app\.example\.com$;

    ssl_certificate     /etc/angie/ssl/wildcard.app.example.com.crt;
    ssl_certificate_key /etc/angie/ssl/wildcard.app.example.com.key;

    # Динамический выбор каталога на основе валидированной переменной
    root /var/www/tenants/$tenant/html;
    index index.html;

    access_log /var/log/angie/tenants_access.log combined;
    error_log  /var/log/angie/tenants_error.log warn;

    location / {
        # Если каталог тенанта отсутствует на диске — возврат 404
        try_files $uri $uri/ =404;
    }

    # Проксирование API запросов тенанта на локальный порт бэкенда
    location /api/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Tenant-ID $tenant;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

### Сценарий 4: Массовый виртуальный хостинг и тюнинг хэш-таблиц

**Задача:** Конфигурация Angie для обслуживания сотен виртуальных хостов с длинными FQDN без ошибок при перезагрузке и с минимальным потреблением ресурсов CPU.

```nginx
# /etc/angie/angie.conf

user www-data;
worker_processes auto;
worker_rlimit_nofile 65535;
pid /run/angie.pid;

events {
    worker_connections 8192;
    use epoll;
    multi_accept on;
}

http {
    include /etc/angie/mime.types;
    default_type application/octet-stream;

    # Оптимизация хэш-таблиц виртуальных имен под размер L1/L2 cache line (64 байта)
    # 128 байт позволяет размещать FQDN длиной до 110-120 символов без ошибок
    server_names_hash_bucket_size 128;
    server_names_hash_max_size 4096;

    # Отключение подстановки server_name в редиректах
    server_name_in_redirect off;

    # Строгий запрет невалидных заголовков (защита от Smuggling и Injection)
    ignore_invalid_headers on;

    # Подключение модульных файлов виртуальных хостов
    include /etc/angie/http.d/*.conf;
}
```

---

### Сценарий 5: Защита от Domain Fronting и атак на заголовок Host

**Задача:** В защищенных корпоративных периметрах предотвратить эксплуатацию несоответствия между именем SNI в TLS-рукопожатии и заголовком `Host` в HTTP-запросе, а также предотвратить атаки отравления кэша (Host Header Poisoning).

```nginx
# /etc/angie/http.d/secure-api.conf

# Сопоставление SNI и Host для выявления Domain Fronting
map "$ssl_server_name:$host" $fronting_violation {
    default 0;
    # Если SNI присутствует и не совпадает со значением $host
    "~^(.+):\1$" 0; # Имена идентичны — легитимно
    "~^:"        0; # Не-TLS запрос (пустой SNI)
    "~^.+"       1; # Несовпадение SNI и Host — подозрение на атаку
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name api.internal.corp;

    ssl_certificate     /etc/angie/ssl/api.internal.corp.crt;
    ssl_certificate_key /etc/angie/ssl/api.internal.corp.key;

    # Проверка на Domain Fronting
    if ($fronting_violation) {
        # 421 Misdirected Request сигнализирует клиенту о неверном сервере назначения
        return 421 "Misdirected Request: SNI and Host header mismatch\n";
    }

    location / {
        proxy_pass http://127.0.0.1:9000;
        
        # Безопасная передача заголовка Host: используем нормализованный $host
        # Категорически запрещено использовать непроверенный $http_host
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## Операции и администрирование

### 1. Верификация конфигурации и аудит виртуальных хостов

```bash
# Проверка синтаксиса всех файлов конфигурации
angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Просмотр полной собранной конфигурации с фильтрацией по server_name и listen
angie -T | grep -E "^\s*(server_name|listen|default_server)\b"
# → listen 80 default_server;
# → server_name _;
# → listen 443 ssl;
# → server_name example.com www.example.com;

# Вывод всех уникальных сконфигурированных доменов в алфавитном порядке
angie -T | awk '/server_name/ {for (i=2; i<=NF; i++) {sub(/;/, "", $i); if ($i != "" && $i != "_") print $i}}' | sort -u
# → admin.example.com
# → api.example.com
# → example.com
# → www.example.com
```

### 2. Тестирование логики маршрутизации с помощью curl

Для отладки выбора виртуального хоста используются параметры `--resolve` (принудительный DNS-роутинг на локальный IP) и явное указание заголовка `Host`.

```bash
# 1. Тестирование отсечения запроса по прямому IP-адресу (проверка default_server)
curl -v http://127.0.0.1/
# → * Connected to 127.0.0.1 (127.0.0.1) port 80
# → > GET / HTTP/1.1
# → > Host: 127.0.0.1
# → * Empty reply from server
# → * Connection #0 to host 127.0.0.1 left intact
# → curl: (52) Empty reply from server (код 444)

# 2. Тестирование сброса TLS без передачи сертификата (ssl_reject_handshake)
curl -v https://127.0.0.1/ --resolve 127.0.0.1:443:127.0.0.1
# → * OpenSSL SSL_connect: SSL_ERROR_SYSCALL in connection to 127.0.0.1:443
# → curl: (35) OpenSSL/3.x: error:0A000458:SSL routines::tlsv1 unrecognized name alert

# 3. Проверка попадания запроса в целевой виртуальный хост
curl -k -sI https://example.com/ --resolve example.com:443:127.0.0.1 | grep -iE "(HTTP/|server:|location:)"
# → HTTP/2 200
# → server: Angie

# 4. Проверка работы канонического редиректа с www на основной домен
curl -sI -H "Host: www.example.com" http://127.0.0.1/ | grep -iE "(HTTP/|location:)"
# → HTTP/1.1 301 Moved Permanently
# → location: https://www.example.com/
```

### 3. Диагностика хэш-таблиц и выделенной памяти

```bash
# Проверка использования виртуальной памяти процессом Angie master/worker
pmap -x $(pgrep -f "angie: worker process" | head -n 1) | grep -E "total|heap"
# → total kB          145248   34120   22400

# Бесшовная перезагрузка конфигурации (graceful reload) без разрыва соединений
systemctl reload angie
# → Процесс master перечитывает конфигурацию, создает новые хэш-таблицы и плавно заменяет воркеры.
```

---

## Диагностика и устранение неисправностей (Troubleshooting)

### Таблица типовых неисправностей

| Симптом | Первопричина | Диагностика | Решение |
|:---|:---|:---|:---|
| **Ошибка при запуске:** `could not build the server_names_hash, you should increase server_names_hash_bucket_size: 64` | Одно из доменных имен длиннее размера корзины (bucket) хэш-таблицы либо возникли множественные коллизии. | Запустить `angie -t`. Найти длинные домены: `angie -T \| grep server_name`. | В блоке `http {}` увеличить директиву `server_names_hash_bucket_size 128;`. Если доменов более 1000 — увеличить `server_names_hash_max_size 4096;`. |
| **Предупреждение при старте:** `conflicting server name "example.com" on 0.0.0.0:80, ignored` | Имя `example.com` указано в двух или более независимых блоках `server` на одинаковом порту. | `angie -T \| grep -n "example.com"` покажет номера строк дублирующихся объявлений. | Оставить домен только в одном блоке `server`. Дублирующий блок удалить или переименовать. |
| **Запрос попадает не в тот виртуальный хост** | Не задан явный `default_server`, либо запрос обработан первым по списку блоком `server`. | Проверить первый объявленный блок в конфигурации через `angie -T`. | Явно объявить блок с `listen 80 default_server;` и `listen 443 ssl default_server;` в самом начале (`00-default.conf`). |
| **Ошибка TLS:** `SSL_ERROR_UNRECOGNIZED_NAME_ALERT` | Клиент запросил имя по TLS, которое отсутствует в конфигурации, при активном `ssl_reject_handshake on`. | Сравнить запрашиваемое клиентом имя SNI со списком `server_name` в блоках с `listen 443 ssl`. | Добавить запрашиваемый домен в целевой виртуальный хост и выпустить валидный сертификат. |
| **Браузер показывает чужой TLS-сертификат** | Запрос отправлен без SNI (старый клиент), либо запрошен неизвестный домен, а на дефолтном сервере висит первый попавшийся сертификат. | Выполнить: `openssl s_client -connect IP:443 -servername unknown.domain`. | Настроить заглушечный `default_server` с `ssl_reject_handshake on;`. |
| **Wildcard `*.example.com` не перехватывает корневой домен** | По стандарту RFC маска `*.domain` соответствует поддоменам (`sub.domain`), но не соответствует самому `domain`. | Проверить синтаксис директивы: `server_name *.example.com;`. | Использовать конструкцию `server_name example.com *.example.com;` либо краткую нотацию `.example.com;`. |
| **Регулярное выражение в server_name не срабатывает** | Пропущен обязательный префикс `~`, не экранированы точки, либо выше объявлен перехватывающий wildcard. | Проверить порядок блоков в `angie -T`. Проверить регулярное выражение через `pcretest` или `pcre2test`. | Добавить `~`, экранировать точки (`~^api\d+\.example\.com$`), разместить специфичный regex выше общих. |
| **Ошибка HTTP `421 Misdirected Request`** | Браузер по HTTP/2 повторно использовал существующее TLS-соединение для другого хоста (Connection Coalescing), но сервер требует изоляции. | Проверить сертификат: содержит ли он оба домена в Subject Alternative Name (SAN). Проверить логи на код 421. | Разнести сайты на разные IP-адреса, либо разделить SAN-сертификаты, либо согласовать конфигурацию виртуальных хостов. |

---

### Пошаговая отладка маршрутизации через расширенный лог-формат

Для точного определения того, какой именно виртуальный хост выбрал Angie и по какой причине, в секцию `http` добавляется отладочный формат логирования:

```nginx
# /etc/angie/angie.conf

http {
    log_format vhost_debug '$remote_addr - $remote_user [$time_local] '
                           '"$request" $status $body_bytes_sent '
                           'Host:"$host" (raw:"$http_host") '
                           'Matched_vhost:"$server_name" '
                           'TLS_SNI:"$ssl_server_name" '
                           'Req_Time:$request_time Connection_Reqs:$connection_requests';

    access_log /var/log/angie/access_debug.log vhost_debug;
}
```

Анализ лога в реальном времени:
```bash
tail -f /var/log/angie/access_debug.log
# Пример вывода при корректном запросе:
# 192.168.1.50 - - [14/Oct/2026:21:05:12 +0300] "GET / HTTP/2.0" 200 4521 Host:"example.com" (raw:"example.com") Matched_vhost:"example.com" TLS_SNI:"example.com" Req_Time:0.002 Connection_Reqs:1

# Пример вывода при атаке или сканировании по IP:
# 203.0.113.19 - - [14/Oct/2026:21:05:18 +0300] "GET / HTTP/1.1" 444 0 Host:"203.0.113.10" (raw:"203.0.113.10") Matched_vhost:"_" TLS_SNI:"" Req_Time:0.000 Connection_Reqs:1
```

---

## Лучшие практики (Best Practices)

1. **Всегда объявляйте явный `default_server` для каждого прослушиваемого сокета:**
   - Никогда не полагайтесь на порядок чтения конфигурационных файлов при выборе сервера по умолчанию.
   - Именуйте файл с сервером по умолчанию так, чтобы он считывался первым (например, `00-default.conf`).
   - Для блокировки паразитного трафика возвращайте код `444` и включайте `ssl_reject_handshake on`.

2. **Выравнивайте корзины хэш-таблиц по кэш-линиям CPU:**
   - Значения `server_names_hash_bucket_size` должны быть строго степенями двойки: `64` или `128`.
   - Не завышайте `server_names_hash_max_size` без необходимости: значение `4096` покрывает потребности большинства инсталляций без раздувания Resident Set Size (RSS) процесса.

3. **Отдавайте приоритет точным именам и wildcard перед регулярными выражениями:**
   - Поиск по точным именам и wildcard выполняется за $O(1)$ через скомпилированные хэш-таблицы ядра.
   - Регулярные выражения (`~^...`) вычисляются последовательно через вызовы библиотеки PCRE, потребляя такты CPU на каждый запрос при высоких нагрузках (10 000+ RPS).

4. **Используйте `$host`, а не `$http_host` в директивах `proxy_set_header`:**
   - Конструкция `proxy_set_header Host $host;` гарантирует нормализацию имени, отсечение нестандартных портов и защиту нижележащих бэкендов от атак типа Host Header Poisoning и манипуляций с кэшем.

5. **Стандартизируйте имена виртуальных хостов в коде и каталогах:**
   - Первое имя в директиве `server_name` всегда должно быть основным каноническим доменом сервиса, так как именно оно попадает в переменную `$server_name` и используется в диагностике.
   - Называйте файлы виртуальных хостов по их основному домену: `/etc/angie/http.d/api.example.com.conf`.

6. **Учитывайте особенности HTTP/2 и HTTP/3 Connection Coalescing:**
   - Если два виртуальных хоста требуют принципиально разной изоляции (например, публичный веб-сайт и внутренняя панель управления), не объединяйте их в один SAN-сертификат на одном IP-адресе, чтобы предотвратить непреднамеренное переиспользование TLS-соединений.

---

## Связанные материалы

*   [Настройка TLS в Angie](file:///c:/Users/Elise/notes/WebServers/Angie/angie_tls_setup.md) — углубленное конфигурирование протоколов TLS 1.3, QUIC, OCSP Stapling и кэширования сертификатов.
*   [Минимальная продакшен-конфигурация Angie](file:///c:/Users/Elise/notes/WebServers/Angie/angie-baseline-config.md) — готовый эталонный каркас веб-сервера для развертывания в production.
*   [Вспомогательные HTTP-модули Angie](file:///c:/Users/Elise/notes/WebServers/Angie/angie-http-utility-modules.md) — детальное описание структур хэширования `server_names_hash`, `map_hash` и `types_hash`.
*   [Переменные в Angie](file:///c:/Users/Elise/notes/WebServers/Angie/angie_variables.md) — полный справочник переменных ядра, включая `$host`, `$server_name`, `$ssl_server_name`.
*   [Редиректы и перезапись URL в Angie](file:///c:/Users/Elise/notes/WebServers/Angie/angie_redirects_and_rewrites.md) — правила канонизации доменов, директива `return` и редиректы HTTP→HTTPS.
*   [Конфигурация реверс-прокси в Angie](file:///c:/Users/Elise/notes/WebServers/Angie/angie_reverse_proxy.md) — безопасная передача заголовков `Host` на бэкенды.
*   [Модуль ACME в Angie](file:///c:/Users/Elise/notes/WebServers/Angie/angie_acme_module.md) — автоматический выпуск и привязка TLS-сертификатов к доменам из `server_name`.
*   [Бесшовная перезагрузка конфигурации в Angie](file:///c:/Users/Elise/notes/WebServers/Angie/angie-graceful-reload.md) — процедура обновления виртуальных хостов без потери клиентского трафика.