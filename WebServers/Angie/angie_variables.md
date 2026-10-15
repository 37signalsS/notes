# Переменные в Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

**Переменные (variables)** в Angie — механизм хранения, вычисления и передачи строковых данных внутри контекста обработки HTTP- и Stream-запросов. Переменные представляют собой именованные строковые сущности (начинающиеся с символа `$`), которые используются директивами ядра и модулей для маршрутизации трафика, динамического выбора бэкендов, формирования журналов, управления доступом и оптимизации кэширования.

Ключевые свойства переменных в архитектуре Angie:
*   **Тип данных:** Исключительно текстовые строки (`ngx_str_t`). Любые числовые метрики, IP-адреса и логические флаги представляются и обрабатываются как строки.
*   **Область видимости (Scope):** Время жизни переменной жестко привязано к жизненному циклу конкретного HTTP-запроса (`ngx_http_request_t`) или TCP/UDP-сессии (`ngx_stream_session_t`). Переменные не разделяются между параллельными запросами разных клиентов.
*   **Индексированные и неиндексированные переменные:**
    *   *Индексированные (`NGX_HTTP_VAR_INDEXED`):* Регистрируются на этапе парсинга конфигурации. Каждому запросу выделяется массив значений фиксированного размера (`r->variables`), доступ к элементам которого осуществляется по прямому индексу за $O(1)$.
    *   *Неиндексированные (динамические):* Вычисляются через поисковые хэндлеры при явном обращении по имени (например, префиксы `$http_*`, `$sent_http_*`, `$cookie_*`, `$arg_*`).
*   **Ленивые вычисления (Lazy Evaluation):** Переменная не вычисляется до тех пор, пока к ней не обратится директива в текущей фазе обработки запроса (например, `proxy_pass`, `if` или `log_format`). Если переменная не участвует в обработке, ее хэндлер не вызывается.
*   **Кэширование значений:** Результат первого вычисления переменной по умолчанию кэшируется в контексте запроса. Повторные чтения возвращают закэшированное значение без повторного вызова обработчика (за исключением переменных, помеченных флагами `nocacheable` или объявленных с параметром `volatile`).

---

## Архитектура и принцип работы

### Внутренний механизм работы переменных

В исходном коде Angie переменная описывается структурой `ngx_http_variable_t`. При старте или перезагрузке сервера (`angie -s reload`) компилятор конфигурации формирует глобальную хеш-таблицу переменных и массив индексов.

```
       Поступающий HTTP-запрос (ngx_http_request_t)
                         │
                         ▼
             Выделение пула r->pool
   Инициализация массива r->variables[n] (все значения uninitialized)
                         │
                         ▼
        Директива обращается к переменной $var
                         │
             Значение уже закэшировано?
                    ├── Да  ───► Возврат r->variables[idx].data
                    └── Нет ───► Вызов getter-хэндлера (get_handler)
                                        │
                                        ▼
                               Запись в r->variables[idx]
                               (если не задан NOCACHEABLE)
```

Флаги поведения переменных в ядре:
*   `NGX_HTTP_VAR_CHANGEABLE` — значение может быть изменено директивой `set`.
*   `NGX_HTTP_VAR_NOCACHEABLE` — запрет кэширования; хэндлер вызывается заново при каждом чтении (применяется для переменных времени, счетчиков и `map ... volatile`).
*   `NGX_HTTP_VAR_INDEXED` — переменная привязана к слоту массива в контексте запроса.

### Жизненный цикл и поведение при перенаправлениях

1.  **Основной запрос:** При создании запроса все слоты `r->variables` пусты (`not_found = 1` или `valid = 0`).
2.  **Внутренние перенаправления (`rewrite ... last`, `error_page`, `try_files`):** При переходе в новый `location` контекст запроса сохраняется. Если переменная уже была вычислена в предыдущем `location`, она **сохранит старое значение**, если только не объявлена с директивой `volatile` (актуально для `$uri`, переопределяемых через `map`).
3.  **Подзапросы (`subrequest`):** Модули вроде `auth_request` создают дочерние запросы со своим собственным массивом переменных, однако некоторые системные переменные наследуются из родительского контекста.
4.  **Управление памятью:** Строки пользовательских переменных аллоцируются в пуле памяти запроса (`r->pool`). Вся память автоматически освобождается ядром при завершении HTTP-транзакции без необходимости ручной сборки мусора.

### Фазы обработки и доступность переменных

Angie обрабатывает HTTP-запрос последовательно через 11 фаз:
1. `NGX_HTTP_POST_READ_PHASE` (чтение заголовков, доступны `$remote_addr`, `$http_*`)
2. `NGX_HTTP_SERVER_REWRITE_PHASE` (`rewrite` на уровне `server`)
3. `NGX_HTTP_FIND_CONFIG_PHASE` (поиск подходящего `location`)
4. `NGX_HTTP_REWRITE_PHASE` (`set`, `rewrite`, вычисление `map` в `location`)
5. `NGX_HTTP_POST_REWRITE_PHASE` (защита от зацикливания редиректов)
6. `NGX_HTTP_PREACCESS_PHASE` (`limit_req`, `limit_conn`)
7. `NGX_HTTP_ACCESS_PHASE` (`allow`, `deny`, `auth_basic`)
8. `NGX_HTTP_POST_ACCESS_PHASE` (проверка прав)
9. `NGX_HTTP_PRECONTENT_PHASE` (`mirror`, `try_files`)
10. `NGX_HTTP_CONTENT_PHASE` (`proxy_pass`, `fastcgi_pass`, генерация ответа)
11. `NGX_HTTP_LOG_PHASE` (запись в `access_log`, доступны метрики времени и апстримов)

> **Критическое правило SRE:** Переменные, связанные с апстримами (`$upstream_response_time`, `$upstream_status`), недоступны в фазах `REWRITE` или `ACCESS`. Попытка использовать `$upstream_status` в `if` внутри `location` всегда вернет пустую строку, так как соединение с бэкендом еще не установлено.

---

## Каталог встроенных переменных

### Сетевые и соединительные переменные

| Переменная | Описание | Применение в SRE / DevOps |
| :--- | :--- | :--- |
| `$remote_addr` | Текстовый IPv4/IPv6-адрес клиента. | Логирование, аудит, ACL. |
| `$binary_remote_addr` | IP-адрес в бинарном представлении (4 байта для IPv4, 16 байт для IPv6). | Ключи для `limit_req_zone` и `limit_conn_zone` (экономит до 75% памяти RAM). |
| `$remote_port` | Порт клиента, с которого открыто TCP-соединение. | Трассировка NAT-трансляций и сетевой аудит. |
| `$server_addr` | IP-адрес сетевого интерфейса сервера, принявшего соединение. | Мульти-IP серверы, диагностика маршрутизации. |
| `$server_port` | Порт сервера, принявший соединение (например, 80 или 443). | Формирование редиректов, заголовков `X-Forwarded-Port`. |
| `$connection` | Порядковый номер TCP-соединения. | Корреляция запросов в рамках одной TCP-сессии. |
| `$connection_requests` | Текущее количество HTTP-запросов, переданных через данное TCP-соединение. | Оценка эффективности HTTP Keep-Alive пулов. |
| `$connection_time` | Общее время жизни TCP-соединения в секундах с миллисекундами. | Мониторинг длинных соединений (WebSockets, SSE). |
| `$connection_serial` | Уникальный серийный номер соединения в рамках рабочего процесса (Angie-only). | Трассировка клиентских сессий и дедупликация за L4 NAT. |

### Переменные HTTP-запроса и маршрутизации

| Переменная | Описание | Особенности обработки |
| :--- | :--- | :--- |
| `$request_uri` | Исходный, сырой URI запроса со всеми аргументами в точности, как передал клиент. | Не нормализуется, сохраняет URL-encoding (`%20`), не изменяется при `rewrite`. Рекомендуется для ключей кэша и аудита безопасности. |
| `$uri` / `$document_uri` | Текущий нормализованный путь без аргументов. | Проходит декодирование URL, нормализацию слэшей (`//` → `/`) и относительных путей (`/../`). Изменяется директивами `rewrite`. |
| `$args` / `$query_string` | Строка параметров запроса (все, что идет после знака `?`). | Может быть модифицирована вручную через `set $args`. |
| `$is_args` | Знак `?`, если в запросе переданы аргументы, либо пустая строка. | Построение динамических URI: `$uri$is_args$args`. |
| `$request_method` | Метод HTTP-запроса (`GET`, `POST`, `PUT`, `DELETE` и др.). | Фильтрация методов, маршрутизация API. |
| `$scheme` | Схема запроса (`http` или `https`). | Формирование абсолютных URL и редиректов. |
| `$server_protocol` | Версия протокола запроса (например, `HTTP/1.1`, `HTTP/2.0`, `HTTP/3.0`). | Мониторинг внедрения HTTP/2 и HTTP/3. |
| `$host` | Имя хоста. Приоритет: 1) хост из строки запроса; 2) заголовок `Host`; 3) директива `server_name`. | Безопасная маршрутизация `proxy_set_header Host $host`. |
| `$request_id` | Уникальный 16-байтный шестнадцатеричный идентификатор запроса (UUID-подобный). | Сквозная трассировка распределенных систем (`X-Request-ID`). |
| `$request_length` | Полный объем входящего запроса от клиента в байтах (включая заголовки и тело). | Анализ аномальных POST-запросов, защита от DoS. |

### Динамические переменные заголовков, аргументов и cookie

Ядро Angie автоматически трансформирует имена заголовков, параметров и cookie в имена переменных по следующим правилам:

1.  **Заголовки запроса (`$http_<name>`):** Имя заголовка приводится к нижнему регистру, дефисы заменяются на символы подчеркивания.
    *   `Authorization` → `$http_authorization`
    *   `X-Forwarded-For` → `$http_x_forwarded_for`
    *   `X-Real-IP` → `$http_x_real_ip`
2.  **Заголовки ответа сервера (`$sent_http_<name>`):** Заголовки, отправляемые клиенту веб-сервером Angie.
    *   `Content-Type` → `$sent_http_content_type`
    *   `X-Cache-Status` → `$sent_http_x_cache_status`
3.  **Заголовки ответа бэкенда (`$upstream_http_<name>`):** Заголовки, возвращенные проксируемым сервером.
    *   `Set-Cookie` → `$upstream_http_set_cookie`
    *   `X-Accel-Expires` → `$upstream_http_x_accel_expires`
4.  **Cookie клиента (`$cookie_<name>`):** Доступ к значению конкретного cookie.
    *   Cookie `session_id=abc` → `$cookie_session_id` (значение: `abc`).
5.  **Аргументы строки запроса (`$arg_<name>`):** Доступ к конкретному параметру из query string.
    *   Запрос `/api?token=xyz&page=2` → `$arg_token` равен `xyz`, `$arg_page` равен `2`.

### Метрики времени и производительности (SRE Golden Signals)

Все временные метрики выражаются в секундах с миллисекундной точностью (формат `0.000`):

| Переменная | Описание интервала | Пороговые значения и диагностика |
| :--- | :--- | :--- |
| `$request_time` | Полное время обработки запроса с момента получения первых байтов от клиента до отправки последних байтов в TCP-сокет. | Если `$request_time` существенно больше `$upstream_response_time`, причина — медленный клиент или большой объем ответа. |
| `$upstream_connect_time` | Время установки сетевого соединения с бэкендом (TCP handshake + TLS handshake при наличии). | Рост метрики (>0.010–0.050s в локальной сети) указывает на насыщение очереди соединений (SYN backlog) или перегрузку CPU бэкенда. |
| `$upstream_header_time` | Время от отправки запроса в апстрим до получения первых байтов заголовков ответа (Time To First Byte — TTFB бэкенда). | Основной индикатор скорости работы приложения (обработка в коде/базе данных). |
| `$upstream_response_time` | Общее время от момента начала отправки запроса в апстрим до полного вычитывания тела ответа бэкенда. | Если апстримов было несколько (повторные попытки), значения разделяются запятыми: `0.050, 1.200`. |

### Переменные апстримов и балансировки

| Переменная | Описание | Формат значений |
| :--- | :--- | :--- |
| `$upstream_addr` | Сетевой адрес целевого сервера, обработавшего запрос. | `10.0.1.10:8080` (при повторах через `proxy_next_upstream`: `10.0.1.10:8080, 10.0.1.11:8080`). |
| `$upstream_status` | Код ответа HTTP от бэкенда. | `200` (при ошибках и ретраях: `502, 200`). |
| `$upstream_bytes_received` | Количество байтов, полученных от апстрима. | Число в байтах (для подсчета входящего трафика от бэкендов). |
| `$upstream_bytes_sent` | Количество байтов, отправленных в апстрим. | Число в байтах (объем запроса с телом). |
| `$upstream_cache_status` | Статус встроенного кэша Angie. | `HIT`, `MISS`, `BYPASS`, `EXPIRED`, `STALE`, `UPDATING`, `REVALIDATED`. |

### Переменные TLS / SSL и mTLS

| Переменная | Описание | Использование |
| :--- | :--- | :--- |
| `$ssl_protocol` | Версия TLS (`TLSv1.2`, `TLSv1.3`). | Мониторинг безопасности и устаревших протоколов. |
| `$ssl_cipher` | Имя используемого криптографического шифросьюта. | Аудит соответствия стандартам PCI-DSS / ГОСТ. |
| `$ssl_server_name` | Имя хоста, переданное клиентом в расширении SNI (Server Name Indication). | Динамическая загрузка SSL-сертификатов без перезагрузки сервера. |
| `$ssl_session_reused` | Статус переиспользования TLS-сессии (`.` — новая, `r` — переиспользована через session cache/tickets). | Оптимизация накладных расходов на TLS handshake. |
| `$ssl_client_verify` | Результат проверки клиентского сертификата при mTLS. | `SUCCESS`, `FAILED:reason`, `NONE`. |
| `$ssl_client_s_dn` | Полная строка Distinguished Name (DN) субъекта клиентского сертификата. | Авторизация систем и микросервисов в mTLS. |
| `$ssl_client_s_dn_cn` | Поле Common Name (CN) из сертификата клиента. | Извлечение идентификатора сервиса или пользователя. |
| `$ssl_client_i_dn` | Distinguished Name издателя (CA) клиентского сертификата. | Контроль цепочки доверия удостоверяющего центра. |
| `$ssl_client_serial` | Серийный номер сертификата клиента. | Аудит и сверка со списками отзыва (CRL). |
| `$ssl_client_v_remain` | Число дней до истечения срока действия клиентского сертификата. | Предупредительный SRE-мониторинг истекающих сертификатов. |
| `$ssl_client_fingerprint_sha256` | SHA-256 отпечаток сертификата клиента в шестнадцатеричном виде. | Безопасная привязка сессий (certificate pinning). |
| `$ssl_client_raw_cert` | Полное тело клиентского сертификата в формате PEM (однострочное с переносами). | Проброс сертификата в апстрим через заголовок `X-SSL-Cert`. |

---

## Практические сценарии

### 1. Конструктор переменных через модуль `map`

Директива `map` создает новую переменную, значение которой зависит от значений одной или нескольких входных переменных. Конструкция компилируется в эффективные статические хеш-таблицы при запуске сервера.

**Синтаксис:**
```nginx
map $source_variable $target_variable {
    [default value];
    [hostnames;]
    [volatile;]
    
    match_value   result_value;
    ~regex_match  result_value;
    include       /path/to/file.map;
}
```

#### Приоритет сопоставления значений внутри `map`
1. Точное строковое совпадение (без масок и регулярок).
2. Наиболее длинная маска в начале строки со звездочкой: `*.example.com` (требует директивы `hostnames;`).
3. Наиболее длинная маска в конце строки со звездочкой: `mail.*` (требует `hostnames;`).
4. Регулярные выражения (в порядке их следования в конфигурации):
   * `~` — с учетом регистра;
   * `~*` — без учета регистра.
5. Значение по умолчанию `default`.

#### Оптимизация хеш-таблиц `map`
При использовании тысяч записей в блоках `map` Angie на этапе старта строит хеш-таблицу. Если ключи не помещаются в стандартный размер бакета процессора, конфигурируются директивы:

```nginx
http {
    # Максимальный общий размер хеш-таблицы (по умолчанию 2048)
    map_hash_max_size 4096;
    
    # Размер бакета под длину ключа (32, 64 или 128 байт, выравнивание по строке кэша CPU)
    map_hash_bucket_size 64;
    
    map $http_user_agent $is_crawler {
        default                  0;
        "~*Googlebot"            1;
        "~*YandexBot"            1;
        "~*bingbot"              1;
        "~*AhrefsBot"            2;
    }
}
```

#### Внешние словари через `include`
Для поддержки больших белых списков или правил редиректов записи выносятся в отдельный файл:

Файл `/etc/angie/maps/redirects.map`:
```text
/legacy-portal/login.php    /auth/login;
/docs/v1/overview           /docs/v2/getting-started;
~^/catalog/category_([0-9]+)$ /shop/cat/$1;
```

Конфигурация Angie:
```nginx
http {
    map $uri $redirect_destination {
        default "";
        include /etc/angie/maps/redirects.map;
    }

    server {
        listen 80;
        server_name example.internal;

        if ($redirect_destination) {
            return 301 $redirect_destination;
        }

        location / {
            proxy_pass http://frontend_backend;
        }
    }
}
```

### 2. Параметр `volatile` и пересчет переменных при внутренних редиректах

По умолчанию Angie кэширует вычисленное значение переменной на все время обработки запроса. Если запрос претерпевает внутренний редирект (`rewrite ... last` или переход через `try_files`), нормализованный `$uri` меняется, но обычный `map` вернет **старое закэшированное значение**.

Параметр `volatile` отключает кэширование переменной и заставляет Angie пересчитывать выражение при каждом обращении:

```nginx
http {
    # Переменная $route_backend пересчитывается при каждом обращении
    map $uri $route_backend volatile {
        default          app_cluster;
        ~^/static/       static_storage;
        ~^/v2/api/       api_v2_cluster;
    }

    server {
        listen 8080;

        location /internal-rewrite/ {
            # Изменение URI на /v2/api/users
            rewrite ^/internal-rewrite/(.*)$ /v2/api/$1 last;
        }

        location / {
            # Без volatile здесь сохранилось бы значение по умолчанию "app_cluster",
            # так как первый расчет произошел до rewrite.
            # С volatile переменная пересчитается и примет значение "api_v2_cluster".
            proxy_pass http://$route_backend;
        }
    }
}
```

> **Предупреждение по производительности:** Использование `volatile` в часто вызываемых переменных повышает утилизацию CPU, так как модуль производит поиск по регулярным выражениям или хешу при каждом чтении переменной. Применяйте флаг только там, где логика обработки гарантированно изменяет входные параметры в процессе одного запроса.

### 3. A/B-тестирование и Canary-раскатка через `split_clients`

Модуль `ngx_http_split_clients_module` обеспечивает детерминированное процентное разделение аудитории на основе 32-битного алгоритма MurmurHash2. В отличие от генерации случайных чисел, хэш от неизменного ключа гарантирует, что конкретный пользователь всегда попадает в одну и ту же группу (Sticky Sessions).

```nginx
http {
    # Детерминированное разделение по IP-адресу или Cookie пользователя
    split_clients "${remote_addr}$http_user_agent" $canary_backend {
        5.0%     canary_upstream;   # 5% трафика на канареечный релиз
        15.0%    beta_upstream;     # 15% трафика на бета-версию
        *        stable_upstream;   # Остальные 80% на стабильную версию
    }

    upstream stable_upstream {
        server 10.10.1.11:8080 max_fails=3 fail_timeout=10s;
        server 10.10.1.12:8080 max_fails=3 fail_timeout=10s;
    }

    upstream canary_upstream {
        server 10.10.2.11:8080 max_fails=3 fail_timeout=10s;
    }

    upstream beta_upstream {
        server 10.10.3.11:8080 max_fails=3 fail_timeout=10s;
    }

    server {
        listen 80;
        server_name app.internal;

        location / {
            # Принудительный override через заголовок для инженеров QA
            set $target_pool $canary_backend;
            if ($http_x_force_canary = "true") {
                set $target_pool canary_upstream;
            }

            proxy_pass http://$target_pool;
            proxy_set_header Host $host;
            proxy_set_header X-Release-Group $target_pool;
        }
    }
}
```

*   Ключом распределения может выступать `$request_id` — в этом случае запросы распределяются равномерно и стохастически без привязки к сессии пользователя.
*   Знак `*` обязателен в конце списка процентов и обозначает оставшуюся долю трафика (до 100%).

### 4. Классификация адресов через `geo` и `geoip2`

Модуль `ngx_http_geo_module` строит префиксное дерево (Radix tree) подсетей в оперативной памяти, что обеспечивает время поиска $O(1)$ для миллионов IP-адресов.

```nginx
http {
    # Базовая классификация доверенных сетей
    geo $network_zone {
        default          public_internet;
        127.0.0.1/32     loopback;
        10.0.0.0/8       internal_datacenter;
        172.16.0.0/12    internal_vpn;
        192.168.0.0/16   office_lan;
    }

    # Чтение IP-адреса из кастомной переменной (например, за балансировщиком HAProxy)
    geo $realip_remote_addr $rate_limit_group {
        default          standard_clients;
        198.51.100.0/24  unthrottled_partners;
        203.0.113.50/32  blocked_bot;
    }

    # Маппинг для блокировки и rate-limiting
    map $rate_limit_group $limit_key {
        standard_clients      $binary_remote_addr;
        unthrottled_partners  "";                  # Пустой ключ отключает ограничение
        blocked_bot           $binary_remote_addr;
    }

    limit_req_zone $limit_key zone=api_throttle:10m rate=10r/s;

    server {
        listen 80;
        server_name api.internal;

        location / {
            if ($rate_limit_group = "blocked_bot") {
                return 403 "Access Denied by Security Policy\n";
            }

            limit_req zone=api_throttle burst=20 nodelay;
            proxy_pass http://api_backend;
        }
    }
}
```

### 5. Динамический `proxy_pass` и специфика работы с DNS (`resolver`)

Использование переменных в директиве `proxy_pass` кардинально меняет поведение ядра Angie:

1.  **Статический апстрим (`proxy_pass http://backend_pool;`):** Имена серверов резолвятся системным DNS **один раз** при старте или перезагрузке процесса.
2.  **Динамический адрес с переменной (`proxy_pass http://$target_host;`):** Angie производит runtime-резолвинг доменного имени через встроенный асинхронный DNS-клиент для каждого запроса.

> **Критическое требование DevOps:** При наличии переменной в адресе `proxy_pass` указание директивы `resolver` является **строго обязательным**. Без нее Angie завершит обработку запроса с ошибкой `502 Bad Gateway` (`no resolver defined to resolve ...`).

```nginx
http {
    # Валидация хостов через map для предотвращения атак Server-Side Request Forgery (SSRF)
    map $http_x_target_service $validated_target {
        default            "";
        "billing"          "billing.services.internal:8080";
        "inventory"        "inventory.services.internal:8080";
        "auth"             "auth.services.internal:8443";
    }

    server {
        listen 8080;
        server_name gateway.internal;

        # Указание внутренних DNS-серверов инфраструктуры
        # valid=30s задает время кэширования DNS ответов независимо от TTL зоны
        # ipv6=off предотвращает задержки при отсутствии AAAA записей в локальной сети
        resolver 10.0.0.2 10.0.0.3 valid=15s ipv6=off;
        resolver_timeout 3s;

        location /service/ {
            if ($validated_target = "") {
                return 400 "Invalid or unauthorized target service\n";
            }

            # Использование валидированной переменной в адресе бэкенда
            proxy_pass http://$validated_target;
            proxy_set_header Host $validated_target;
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_connect_timeout 2s;
            proxy_read_timeout 10s;
        }
    }
}
```

### 6. Динамическая загрузка SSL-сертификатов через `$ssl_server_name` и `ssl_certificate_cache`

Angie поддерживает подстановку переменных в директивы `ssl_certificate` и `ssl_certificate_key`. Это позволяет обслуживать миллионы доменных имен без предварительного создания сотен тысяч блоков `server` в файле конфигурации.

Для исключения блокирующего дискового ввода-вывода и тяжелого парсинга OpenSSL при каждом TLS handshake используется директива `ssl_certificate_cache`:

```nginx
http {
    # Кэширование до 10000 распарсенных SSL-сертификатов в оперативной памяти worker'ов
    # Неактивные сертификаты вытесняются по LRU через 2 часа
    ssl_certificate_cache max=10000 inactive=2h;

    # Валидация разрешенных доменов для предотвращения атак переполнения диска/кэша
    map $ssl_server_name $is_valid_domain {
        default          0;
        "~^[a-z0-9-]+\.example\.internal$" 1;
        "~^[a-z0-9-]+\.customer\.zone$"    1;
    }

    server {
        listen 443 ssl default_server;
        server_name _;

        # Отклонять TLS handshake при отсутствии совпадений в белом списке
        if ($is_valid_domain = 0) {
            return 444;
        }

        # Динамические пути к сертификатам на локальном хранилище
        ssl_certificate     /etc/angie/ssl/domains/$ssl_server_name/fullchain.pem;
        ssl_certificate_key /etc/angie/ssl/domains/$ssl_server_name/privkey.pem;

        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;

        location / {
            proxy_pass http://app_cluster;
        }
    }
}
```

### 7. Сквозная трассировка (Distributed Tracing) и структурированное JSON-логирование

Связывание логов Angie с трассировками Jaeger/OpenTelemetry в микросервисной архитектуре реализуется генерацией и пробросом `$request_id`:

```nginx
http {
    # Фильтрация технического трафика (health checks) из журналов access_log
    map $request_uri $is_loggable {
        ~^/healthz    0;
        ~^/metrics    0;
        default       1;
    }

    # Маскирование чувствительных данных заголовков Authorization в журналах
    map $http_authorization $sanitized_auth {
        default                  "***";
        ""                       "-";
    }

    # Маскирование сессионных cookie
    map $cookie_session_token $sanitized_session {
        default                  "PRESENT";
        ""                       "ABSENT";
    }

    log_format json_sre escape=json '{'
        '"timestamp":"$time_iso8601",'
        '"request_id":"$request_id",'
        '"client_ip":"$remote_addr",'
        '"http_host":"$host",'
        '"method":"$request_method",'
        '"uri":"$request_uri",'
        '"status":$status,'
        '"body_bytes_sent":$body_bytes_sent,'
        '"request_time":$request_time,'
        '"upstream_addr":"$upstream_addr",'
        '"upstream_status":"$upstream_status",'
        '"upstream_connect_time":"$upstream_connect_time",'
        '"upstream_header_time":"$upstream_header_time",'
        '"upstream_response_time":"$upstream_response_time",'
        '"auth":"$sanitized_auth",'
        '"session":"$sanitized_session"'
    '}';

    server {
        listen 80;
        server_name api.internal;

        # Условная запись логов
        access_log /var/log/angie/access.json.log json_sre if=$is_loggable;
        error_log  /var/log/angie/error.log warn;

        location / {
            # Генерация заголовка сквозной трассировки для бэкенда
            proxy_set_header X-Request-ID $request_id;
            
            # Возврат идентификатора клиенту для обращений в службу поддержки
            add_header X-Request-ID $request_id always;

            proxy_pass http://backend_pool;
        }
    }
}
```

---

## Операции и команды

### Синтаксическая проверка и отображение скомпилированных деревьев конфигурации

Перед применением новых переменных обязательно выполняется проверка синтаксиса:

```bash
# Проверка корректности синтаксиса и проверка хеш-таблиц (map, server_names)
angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Дамп полной активной конфигурации со всеми include и таблицами map
angie -T | grep -E "(map|split_clients|geo)" -A 10
```

### Диагностика подстановки переменных через HTTP-заголовки

Для верификации расчетных значений в тестовой среде создается отладочный блок `location`:

```nginx
location /debug-variables {
    add_header X-Debug-Remote-Addr       "$remote_addr" always;
    add_header X-Debug-Target-Upstream   "$route_backend" always;
    add_header X-Debug-Canary-Choice     "$canary_backend" always;
    add_header X-Debug-Request-Time      "$request_time" always;
    return 200 "Variables evaluated successfully\n";
}
```

Тестирование через `curl`:
```bash
curl -I http://127.0.0.1:8080/debug-variables
# → HTTP/1.1 200 OK
# → Server: Angie/1.12.0
# → X-Debug-Remote-Addr: 127.0.0.1
# → X-Debug-Target-Upstream: app_cluster
# → X-Debug-Canary-Choice: stable_upstream
# → X-Debug-Request-Time: 0.000
```

### Статистическая проверка распределения `split_clients`

Скрипт для проверки равномерности хэширования перед выкаткой в Production:

```bash
# Генерация 1000 тестовых запросов с имитацией различных IP-адресов
for i in {1..1000}; do
    curl -s -H "X-Forwarded-For: 192.168.1.$((RANDOM % 254 + 1))" \
         -I http://localhost:8080/ | grep "X-Release-Group:"
done | sort | uniq -c
# → 804 X-Release-Group: stable_upstream
# → 148 X-Release-Group: beta_upstream
# →  48 X-Release-Group: canary_upstream
```

### Проверка состояния кэша динамических SSL-сертификатов

```bash
# Проверка загрузки и срока действия клиентского сертификата через mTLS
curl -s --cacert /etc/angie/ssl/ca.crt \
     --cert /etc/angie/ssl/client.crt \
     --key /etc/angie/ssl/client.key \
     -I https://internal.service/healthz | grep -i "ssl-"
# → X-SSL-Client-Verify: SUCCESS
# → X-SSL-Client-Remain: 180
```

---

## Устранение неисправностей

### 1. Ошибка переполнения хеш-таблиц `map_hash`

**Симптом:** При запуске или перезагрузке `angie -t` возвращает ошибку:
```
[emerg] could not build optimal map_hash, you should increase either map_hash_max_size: 2048 or map_hash_bucket_size: 64
```

**Причина:** Большое количество записей в блоках `map` либо длина строк-ключей превышает размер процессорного бакета кэш-памяти (по умолчанию 64 байта на архитектурах x86_64).

**Решение:** Увеличить лимиты в контексте `http`:
```nginx
http {
    map_hash_max_size 8192;
    map_hash_bucket_size 128;
}
```

### 2. Ошибка резолвинга DNS при динамическом `proxy_pass`

**Симптом:** При обращении к локации клиент получает `502 Bad Gateway`. В файле `/var/log/angie/error.log` фиксируется запись:
```
[error] 12345#12345: no resolver defined to resolve app-service.internal, client: 10.0.1.5, server: api.internal, request: "GET /service/users HTTP/1.1", host: "api.internal"
```

**Причина:** В директиве `proxy_pass http://$variable;` используется переменная, но на уровне `http` или `server` не задан системный `resolver`.

**Решение:** Добавить адреса локальных DNS-серверов с указанием интервала валидации и таймаута:
```nginx
server {
    resolver 127.0.0.1 10.0.0.2 valid=30s ipv6=off;
    resolver_timeout 5s;
    
    location / {
        proxy_pass http://$backend_host;
    }
}
```

### 3. Значение переменной не обновляется после внутренней перезаписи URI

**Симптом:** Переменная `$mapped_val`, созданная на основе `$uri`, содержит старое значение после срабатывания `rewrite ^ /new_path last;`.

**Причина:** Ядро Angie закэшировало вычисленное значение `$mapped_val` при первом чтении в начальной фазе запроса.

**Решение:** Добавить параметр `volatile` в объявление `map`:
```nginx
map $uri $mapped_val volatile {
    default     default_backend;
    /new_path   updated_backend;
}
```

### 4. Некорректный IP-адрес клиента (`$remote_addr` указывает на балансировщик)

**Симптом:** В журнале доступа и механизмах rate-limiting все клиенты блокируются скопом, так как `$remote_addr` равен адресу L4/L7 балансировщика (например, HAProxy или Keepalived VIP: `10.0.0.1`).

**Причина:** Модуль `ngx_http_realip_module` не сконфигурирован для обработки доверенных заголовков проксирования.

**Решение:** Настроить модуль реального IP в блоке `http`:
```nginx
http {
    # Доверенные IP-адреса локальных балансировщиков нагрузки
    set_real_ip_from 10.0.0.0/8;
    set_real_ip_from 172.16.0.0/12;
    
    # Заголовок, содержащий реальный IP клиента
    real_ip_header X-Forwarded-For;
    
    # Игнорировать промежуточные доверенные прокси из цепочки
    real_ip_recursive on;
}
```
После настройки `$remote_addr` будет содержать реальный адрес клиента, а `$realip_remote_addr` сохранит сетевой адрес балансировщика.

### 5. Директива `if` внутри `location` ломает вычисление переменных

**Симптом:** При использовании директивы `if` переменные модулей проксирования сбрасываются либо возвращаются ошибки `404 Not Found`.

**Причина:** Архитектурная особенность "If is Evil" в Nginx/Angie. Блок `if` внутри `location` создает анонимный вложенный контекст конфигурации. Директивы фазы `content` (например, `proxy_pass`) внутри вложенного блока могут не унаследовать обработчики родителя.

**Решение:** Избегать директив `if` внутри `location` для проверки переменных. Заменять их конструкциями модуля `map`:
```nginx
# Плохо (создает скрытый контекст, возможны баги наследования):
location /download {
    if ($http_x_special_auth = "") {
        return 403;
    }
    proxy_pass http://storage_backend;
}

# Рекомендуется (чистая логика на уровне http):
map $http_x_special_auth $access_forbidden {
    ""      1;
    default 0;
}

server {
    location /download {
        if ($access_forbidden) {
            return 403;
        }
        proxy_pass http://storage_backend;
    }
}
```

---

## Лучшие практики

### Производительность и ресурсы

1.  **Приоритет `map` над серией `set` и `if`:** Конструкция `map` вычисляется по хеш-таблице за $O(1)$, в то время как каскад директив `if` выполняется последовательно процессорными инструкциями на каждый запрос, создавая накладные расходы на ветвление.
2.  **Экономия памяти через `$binary_remote_addr`:** Для shared-memory зон (`limit_req_zone`, `limit_conn_zone`) используйте исключительно бинарный формат IP-адреса. Это сокращает потребление памяти с 32–64 байт до 4 байт на клиента в зоне IPv4.
3.  **Осторожность с флагом `volatile`:** Включайте `volatile` только для переменных, значения которых физически изменяются в пределах одного запроса при перенаправлениях. Избыточный `volatile` увеличивает нагрузку на CPU при формировании логов и проверке условий.
4.  **Кэширование динамических сертификатов:** При использовании переменных в `ssl_certificate` всегда задавайте директиву `ssl_certificate_cache` с адекватным размером пула под количество активных доменов.

### Информационная безопасность

1.  **Защита от SSRF при динамическом проксировании:** Никогда не передавайте непроверенные пользовательские заголовки напрямую в `proxy_pass http://$http_host;`. Используйте жесткий белый список через `map`, возвращающий код `400` или дефолтный адрес для неизвестных значений.
2.  **Маскирование секретных данных в логах:** Всегда санитизируйте заголовки `Authorization`, `Proxy-Authorization`, `Cookie` и аргументы вроде `?token=` перед записью в долговременные журналы (ELK/ClickHouse).
3.  **Нормализация путей:** Для разграничения прав доступа используйте нормализованную переменную `$uri` либо проверяйте `$request_uri` с осторожностью, помня, что `$request_uri` может содержать обходы вида `/v1/..;/admin`.

### Эксплуатация и SRE

1.  **Унификация сквозных идентификаторов:** Генерируйте `$request_id` на входном пограничном прокси (Ingress/Edge) и передавайте его вниз по цепочке микросервисов в неизменном виде.
2.  **Анализ задержек в логах:** Включайте триаду времени `$upstream_connect_time`, `$upstream_header_time` и `$upstream_response_time` в основной формат логов для быстрого разграничения сетевых проблем и деградации производительности БД.
3.  **Фильтрация Health Checks:** Исключайте периодические запросы систем мониторинга (`/healthz`, `/metrics`, Keepalived checks) из файлов `access_log` с помощью конструкции `access_log ... if=$is_loggable;`, чтобы предотвратить преждевременный износ дисков (IOPS throttling) на высоконагруженных узлах.

---

## Дополнительная информация

### Экранирование знака доллара (`$`)

В директивах Angie, поддерживающих строковую интерполяцию, символ `$` автоматически распознается как начало имени переменной. Если требуется вставить литеральный символ доллара (например, в заголовки ответов или параметры подстановки), используется служебная переменная через `geo` или `map`:

```nginx
http {
    # Создание переменной, содержащей литеральный знак доллара
    geo $dollar {
        default "$";
    }

    server {
        listen 80;
        server_name shop.internal;

        location /price {
            # Выведет заголовок: X-Price: 150$
            add_header X-Price "150$dollar" always;
            return 200 "Price: 150$dollar\n";
        }
    }
}
```

### Отличия переменных Angie от Nginx Open Source

| Возможность | Nginx OSS | Angie | Преимущество Angie в эксплуатации |
| :--- | :--- | :--- | :--- |
| **`ssl_certificate_cache`** | Отсутствует (доступно только в Nginx Plus) | Поддерживается нативно в базовой версии | Высокопроизводительное динамическое обслуживание TLS для сотен тысяч доменов без reload. |
| **`$connection_serial`** | Отсутствует | Поддерживается | Упрощенный трекинг сессий клиентов за L4 NAT и балансировщиками без сложных скриптов. |
| **Модуль метрик (`metric_zone`)** | Отсутствует | Включен в базовую поставку (HTTP с 1.6.0, Stream с 1.7.0) | Прямой сбор метрик и счетчиков по значениям любых переменных без сторонних экспортеров. |
| **Переменные ACME** | Отсутствуют | Поддерживаются в модуле ACME | Автоматическое получение и ротация сертификатов Let's Encrypt / Vault с доступом к статусам через переменные. |

---

## См. также

*   [Перенаправления и перезапись URI в Angie](./angie_redirects_and_rewrites.md) — директивы `rewrite`, `return`, флаги `last`/`break` и интеграция с `map`.
*   [Логирование в Angie](./angie_logging.md) — полная настройка форматов логов, условная запись и JSON.
*   [Обратное проксирование в Angie](./angie_reverse_proxy.md) — архитектура передачи заголовков, тайм-ауты и настройка `proxy_pass`.
*   [Взаимная аутентификация клиентов (mTLS) в Angie](./angie_client_cert_auth.md) — полный справочник переменных `ssl_client_*`.
*   [Вспомогательные HTTP-модули Angie](./angie-http-utility-modules.md) — детальный разбор модулей `split_clients`, `slice`, `sub_filter`.
*   [Мониторинг: пользовательские метрики](./angie_monitoring/angie_monitoring_custom_metrics.md) — агрегация переменных в зонах разделяемой памяти `metric_zone`.
*   [Базовая настройка Angie](./angie-baseline-config.md) — эталонная конфигурация для серверов под высокой нагрузкой.
*   [Динамические апстримы в Angie](./dynamic_upstreams.md) — работа с `resolver` и динамическим DNS-резолвингом.
*   [Canary Deployment](../../CI-CD/Deployment_Strategies/canary_deployment.md) — архитектура канареечных релизов и разделение трафика.
