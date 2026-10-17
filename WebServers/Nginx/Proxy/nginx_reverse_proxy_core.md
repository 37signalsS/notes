# Архитектура и ядро HTTP Reverse Proxy в Nginx

**Актуально для:** Nginx 1.26+ (OSS/Plus) / Angie 1.6+

---

## 0. Декларация перекрытия (Overlap Declaration)

Настоящий документ является единым источником правды (SSoT) для базового L7 HTTP-проксирования (`ngx_http_proxy_module`) в Nginx:
- [nginx_proxy_redirects.md](./nginx_proxy_redirects.md) — рассматривает исключительно модификацию заголовков ответа бэкенда `Location` и `Refresh` (`proxy_redirect`), не затрагивая трансформацию входящих URI и заголовков запроса.
- [nginx_buffering_and_streaming.md](./nginx_buffering_and_streaming.md) — фокусируется на механике буферов оперативной памяти, сбросе на диск и SSE/стриминге.
- [nginx_l4_proxying.md](./nginx_l4_proxying.md) — посвящен L4 TCP/UDP проксированию в контексте `stream`.
- [Load_Balancing/practical_configuration.md](./Load_Balancing/practical_configuration.md) — рассматривает конфигурацию пулов серверов и алгоритмов распределения нагрузки.
- [Operations/nginx_troubleshooting.md](../Operations/nginx_troubleshooting.md) — охватывает общесистемную диагностику процессов и служб ОС.

---

## 1. Определения

- **Reverse Proxy (Обратный прокси-сервер)** — архитектурный компонент, принимающий входящие HTTP-запросы от клиентов и перенаправляющий их внутренним серверам приложений (upstream). Для клиента обратный прокси выступает конечной точкой, скрывая внутреннюю топологию сети.
- **Директива `proxy_pass`** — основная директива модуля `ngx_http_proxy_module`, задающая протокол, целевой адрес (IP, DNS-имя, пул `upstream` или Unix Domain Socket) и опциональный URI-путь для проксирования запроса.
- **Трансформация URI (URI Transformation)** — процесс модификации адресной строки запроса при передаче от Nginx к бэкенду, определяемый наличием или отсутствием URI-части (включая завершающий слэш `/`) в параметре `proxy_pass`.
- **Завершающий слэш (Trailing Slash)** — символ `/` в конце URL в директивах `location` и `proxy_pass`. Определяет, будет ли префикс `location` вырезан из пути или передан бэкенду в неизменном виде.
- **Уязвимость Off-by-slash (Path Traversal)** — уязвимость безопасности, возникающая при отсутствии завершающего слэша в префиксном `location` при наличии слэша в `proxy_pass`, позволяющая злоумышленнику обращаться к закрытым эндпоинтам бэкенда через относительные пути (`/api../admin`).
- **Наследование списочных директив (Array Directive Inheritance)** — правило вычисления параметров Nginx, согласно которому директивы типа `proxy_set_header` на дочернем уровне полностью перезаписывают (аннулируют) все одноименные директивы, объявленные на родительских уровнях (`http`, `server`).
- **Unix Domain Socket (UDS)** — механизм межпроцессного взаимодействия (IPC) в POSIX-системах, позволяющий Nginx обмениваться данными с локальными процессами приложений (Gunicorn, Uvicorn, PHP-FPM) через файл сокета в файловой системе без накладных расходов сетевого стека TCP/IP.
- **Куки-нормализация (`proxy_cookie_domain`, `proxy_cookie_path`, `proxy_cookie_flags`)** — механизм модификации параметров `Domain` и `Path`, а также принудительной установки защитных атрибутов (`Secure`, `HttpOnly`, `SameSite`) в заголовках ответа `Set-Cookie`, возвращаемых бэкендом.

---

## 2. Основные концепции и архитектура

### 2.1 Жизненный цикл проксируемого HTTP-запроса

При поступлении запроса Nginx выполняет конвейерную обработку по фазам ядра:

```text
Клиентский запрос (HTTP/1.1, HTTP/2, HTTP/3)
       │
       ▼
[NGX_HTTP_FIND_CONFIG_PHASE] ──► Выбор блока server и location
       │
       ▼
[NGX_HTTP_REWRITE_PHASE]     ──► rewrite / return / set
       │
       ▼
[NGX_HTTP_PRECONTENT_PHASE]  ──► mirror, limit_req, limit_conn
       │
       ▼
[NGX_HTTP_CONTENT_PHASE]     ──► Исполнение proxy_pass
       │
       ├─► 1. Трансформация URI согласно правилам proxy_pass
       ├─► 2. Формирование заголовков запроса (proxy_set_header)
       ├─► 3. Подключение к апстриму (TCP Handshake или UDS connect)
       ├─► 4. Передача тела запроса (буферизованная или потоковая)
       ├─► 5. Чтение и парсинг заголовков ответа бэкенда
       ├─► 6. Фильтрация заголовков (proxy_hide_header, proxy_cookie_*)
       └─► 7. Отправка ответа клиенту
```

---

### 2.2 Механика трансформации URI и правила завершающего слэша (Trailing Slash)

Поведение Nginx при формировании URI запроса к бэкенду строго подчиняется наличию **URI-части** в аргументе `proxy_pass`:

```text
Схема URL в proxy_pass:   http://upstream_name[:port] [ /uri_part ]
                                                    ▲
                                     наличие этой части меняет логику
```

#### Случай 1: `proxy_pass` БЕЗ URI-части (нет даже одиночного слэша после хоста)
```nginx
location /api/ {
    proxy_pass http://backend;
}
```
* **Правило:** Nginx передает входящий URI в апстрим **в исходном виде**, сохраняя оригинальную строку запроса `$request_uri` (включая аргументы):
  * Запрос клиента: `GET /api/v1/users?page=2`
  * Запрос к апстриму: `GET /api/v1/users?page=2`
* **Особенность:** Если в `location` выполнялась нормализация URI (например, раскодирование символов `%20`), директива `proxy_pass` без URI передает именно **необработанный** URI клиента.

#### Случай 2: `proxy_pass` С URI-частью (присутствует слэш или путь)
```nginx
location /api/ {
    proxy_pass http://backend/;
}
```
* **Правило:** Nginx сопоставляет префикс `location` и **заменяет** совпавшую часть URI на URI-часть из `proxy_pass`:
  * Совпавшая часть: `/api/`
  * URI из `proxy_pass`: `/`
  * Клиент: `GET /api/v1/users` → Апстрим: `GET /v1/users` (префикс `/api/` отрезан).
* **Пример со сменой префикса:**
  ```nginx
  location /service/ {
      proxy_pass http://backend/internal/v2/;
  }
  ```
  * Клиент: `GET /service/orders/10` → Апстрим: `GET /internal/v2/orders/10`.

#### Матрица вариантов формирования URI

| Конфигурация `location` | Директива `proxy_pass` | Запрос клиента | Запрос к апстриму | Пояснение |
| :--- | :--- | :--- | :--- | :--- |
| `location /api/` | `http://backend;` | `/api/v1/items` | `/api/v1/items` | URI передается без изменений |
| `location /api/` | `http://backend/;` | `/api/v1/items` | `/v1/items` | Префикс `/api/` заменен на `/` |
| `location /api/` | `http://backend/app/;` | `/api/v1/items` | `/app/v1/items` | Префикс `/api/` заменен на `/app/` |
| `location /api` | `http://backend/;` | `/api/items` | `//items` | Баг: слэш склеился в двойной слэш |
| `location /api` | `http://backend/;` | `/api_status` | `/_status` | **Off-by-slash:** опасная подмена префикса |

---

### 2.3 Критические ограничения и синтаксические исключения

#### 1. Запрет URI в регулярных выражениях
Если `location` объявлен с использованием регулярных выражений (`~` или `~*`), директива `proxy_pass` **не может содержать URI**:
```nginx
# ОШИБКА КОНФИГУРАЦИИ:
location ~* ^/api/(.*)$ {
    proxy_pass http://backend/$1; # ❌ Вызовет ошибку при nginx -t
}
```
* **Симптом в выводе `nginx -t`:**  
  `nginx: [emerg] "proxy_pass" cannot have URI part in location given by regular expression, or inside named location, or inside the "if" statement, or inside "limit_except" block in /etc/nginx/conf.d/app.conf:15`
* **Корректное решение:** Использование директивы `rewrite ... break`:
  ```nginx
  location ~* ^/api/(.*)$ {
      rewrite ^/api/(.*)$ /v2/$1 break;
      proxy_pass http://backend; # ✅ Корректно: proxy_pass без URI
  }
  ```

#### 2. Запрет URI в именованных локейшенах (`location @name`)
Именованные локейшены, вызываемые через `error_page` или `try_files`, также не поддерживают URI в `proxy_pass`:
```nginx
location @fallback {
    proxy_pass http://backup_backend; # ✅ Корректно: строго без URI
}
```

#### 3. Взаимодействие `rewrite ... break` и `proxy_pass`
Если внутри `location` сработала директива `rewrite` с модификатором `break`, Nginx **полностью игнорирует любой URI-путь**, указанный в `proxy_pass`:
```nginx
location /legacy/ {
    rewrite ^/legacy/(.*)$ /modern/$1 break;
    proxy_pass http://backend/ignored_path/; # Путь /ignored_path/ будет проигнорирован!
}
```
Запрос `/legacy/item` уйдет на апстрим как `/modern/item`.

---

### 2.4 Анализ уязвимости Off-by-slash / Path Traversal

Архитектурная ошибка конфигурации возникает при несовпадении завершающих слэшей:
```nginx
# ДЕФЕКТНАЯ КОНФИГУРАЦИЯ (Off-by-slash):
location /v1 {
    proxy_pass http://backend_internal/;
}
```
* **Механика эксплуатации:**  
  Nginx сопоставляет префикс `/v1`. Строка `location` совпадает с запросом `/v1_admin` или `/v1../internal_status`.  
  Nginx отрезает совпавшую строку `/v1` и подставляет `/`:
  * Запрос клиента: `GET /v1../private/keys.json`
  * Преобразование: `/v1` отрезается → остается `../private/keys.json` → конкатенируется с `/`
  * Запрос к апстриму: `GET /../private/keys.json` (нормализуется бэкендом в `/private/keys.json`).
* **Правило предотвращения:**  
  Если завершающий слэш ставится в `proxy_pass`, он **обязан** присутствовать и в объявлении `location`:
  ```nginx
  location /v1/ {
      proxy_pass http://backend_internal/;
  }
  ```

---

### 2.5 Ловушка наследования заголовков (`proxy_set_header`)

Директива `proxy_set_header` является списочной (array directive).  
* **Правило ядра:** Дочерний контекст (`location`) наследует все директивы `proxy_set_header` с родительского уровня (`http` или `server`) **только в том случае, если на текущем уровне не объявлено ни одной директивы `proxy_set_header`**.
* **Следствие:** Если на уровне `server` объявлены критические заголовки `Host` и `X-Real-IP`, а в блоке `location` добавлен всего один кастомный заголовок:
  ```nginx
  http {
      # Родительские настройки:
      proxy_set_header Host $host;
      proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

      server {
          location /custom/ {
              # ЛОВУШКА: эта строка СТИРАЕТ Host, X-Real-IP и X-Forwarded-For!
              proxy_set_header X-Request-ID $request_id;
              proxy_pass http://app;
          }
      }
  }
  ```
  В результате апстрим для `/custom/` получает дефолтный `Host: app` (значение `$proxy_host`), а `X-Real-IP` теряется полностью.
* **Production-решение:** Создание файла `/etc/nginx/proxy_params` и его обязательное включение (`include proxy_params;`) во всех блоках `location`.

#### Различия переменных `$host`, `$http_host` и `$proxy_host`

| Переменная | Источник значения | Порт | Поведение при отсутствии заголовка `Host` | Рекомендуемое применение |
| :--- | :--- | :--- | :--- | :--- |
| **`$host`** | Имя хоста из строки запроса, либо заголовок `Host` клиента, либо `server_name` | **Отрезается** (всегда без `:порт`) | Подставляет дефолтный `server_name` | Стандартный Web/API трафик (рекомендуется) |
| **`$http_host`** | Сырой HTTP-заголовок `Host`, присланный клиентом | **Сохраняется** (например, `site.com:8443`) | Пустая строка (заголовок не передается) | Когда бэкенд формирует редиректы с учетом нестандартного внешнего порта |
| **`$proxy_host`** | Имя и порт целевого upstream из директивы `proxy_pass` | Содержит имя upstream (например, `backend_pool`) | Определяется параметром `proxy_pass` | Дефолтное значение Nginx при отсутствии `proxy_set_header Host` |

---

### 2.6 Управление куками и сессиями бэкенда

Когда бэкенд работает за Reverse Proxy, его внутреннее доменное имя (`backend.internal`) и внутренний префикс (`/app/`) не совпадают с публичным адресом (`example.com/`). При отправке заголовка `Set-Cookie` браузер отклонит куки из-за несовпадения домена или пути.

Для нормализации применяются директивы:

```nginx
# 1. Переписывание домена куки
# Заменяет Domain=backend.internal на Domain=example.com
proxy_cookie_domain backend.internal example.com;
# Автоматическая замена любого домена бэкенда на имя текущего хоста:
proxy_cookie_domain ~\.internal$ $host;

# 2. Переписывание пути куки
# Заменяет Path=/app/ на Path=/
proxy_cookie_path /app/ /;

# 3. Принудительная установка флагов безопасности (Nginx 1.19.3+)
# Добавляет флаги Secure, HttpOnly и SameSite ко всем кукам от апстрима
proxy_cookie_flags ~ Secure HttpOnly SameSite=Lax;
```

---

### 2.7 Управление заголовками ответа бэкенда

#### Скрытие заголовков (`proxy_hide_header`)
По умолчанию Nginx автоматически удаляет из ответа бэкенда служебные заголовки `Date`, `Server`, `X-Pad` и `X-Accel-*`. Для маскировки информации о технологическом стеке бэкенда применяют явное скрытие:
```nginx
proxy_hide_header X-Powered-By;
proxy_hide_header X-AspNet-Version;
proxy_hide_header X-Runtime;
```

#### Принудительный проброс (`proxy_pass_header`)
Если требуется передать клиенту заголовок, который Nginx скрывает по умолчанию (например, заголовок `Server` оригинального бэкенда):
```nginx
proxy_pass_header Server;
proxy_pass_header Date;
```

#### Игнорирование управляющих заголовков бэкенда (`proxy_ignore_headers`)
Бэкенд может вернуть заголовки, запрещающие кэширование или буферизацию. Если Nginx обязан кэшировать ресурс независимо от решения приложения:
```nginx
# Заставляет Nginx кэшировать ответ даже при наличии Set-Cookie и Cache-Control: private
proxy_ignore_headers Cache-Control Expires Set-Cookie X-Accel-Buffering;
```

---

### 2.8 Проксирование на Unix Domain Sockets (UDS)

В архитектурах, где Nginx и сервер приложений (Gunicorn, Uvicorn, PHP-FPM, Puma) размещены на одном хосте (Bare-Metal или VM), использование Unix-сокетов предпочтительнее сетевого TCP-стека loopback (`127.0.0.1`):

```text
TCP Loopback:  Nginx ──► TCP SYN ──► IP стек ядра ──► TCP ACK ──► Socket Buffer ──► App
UDS:           Nginx ─────────────► Файловый дескриптор / буфер ядра ─────────────► App
```

* **Преимущества UDS:**
  * Отсутствие накладных расходов на расчет контрольных сумм TCP/IP и 3-way handshake.
  * Нулевой риск исчерпания эфемерных портов (`TIME_WAIT` saturation).
  * Прирост пропускной способности (throughput) на 15–25% при меньшей утилизации CPU.
* **Синтаксис обращения:**
  ```nginx
  # Проксирование на сокет без URI:
  proxy_pass http://unix:/run/gunicorn/app.sock;

  # Проксирование на сокет с заменой URI:
  proxy_pass http://unix:/run/gunicorn/app.sock:/api/;
  ```

---

### 2.9 Протоколы взаимодействия с бэкендами: HTTP/1.1, HTTP/2 и WebSocket

#### HTTP-версия к апстримам
* **Поведение по умолчанию:** Модуль `ngx_http_proxy_module` обращается к бэкенду по протоколу **HTTP/1.0** и выставляет заголовок `Connection: close`.
* **Требование для Keep-Alive и WebSocket:** Обязателен перевод на HTTP/1.1:
  ```nginx
  proxy_http_version 1.1;
  proxy_set_header Connection ""; # Очистка для keepalive-пулов
  ```
* **Поддержка HTTP/2 к бэкендам:** Исторически Nginx поддерживал HTTP/2 только между клиентом и Nginx. Начиная с версии **Nginx 1.25.1+**, директива `proxy_http_version 2;` позволяет мультиплексировать запросы к бэкенду по HTTP/2 без промежуточного преобразования.

#### Проксирование WebSocket
Для установки соединения WebSocket клиент отправляет заголовки `Upgrade: websocket` и `Connection: Upgrade`. Для корректной трансляции используется связка с директивой `map`:
```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    location /ws/ {
        proxy_pass http://backend_ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        
        # Длительный таймаут тишины (иначе соединение закроется через 60 секунд)
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

---

### 2.10 SRE-модель таймаутов и анатомия ошибок 502 vs 504

```text
[Клиент] ───────────► Nginx ───────────► [Бэкенд]
                        │
    ├── proxy_connect_timeout ──┤ (до завершения TCP handshake)
    │                           │
    │                           ├── proxy_send_timeout ──► (отправка тела запроса)
    │                           │
    │                           ├── proxy_read_timeout ──► (ожидание данных ответа)
```

1. **`proxy_connect_timeout` (по умолчанию `60s`):**  
   Время на установку TCP-соединения с бэкендом (SYN → SYN-ACK). В проде значение выше `2-5s` недопустимо: если сервер недоступен, зависание на 60 секунд исчерпывает рабочие соединения Nginx.
2. **`proxy_read_timeout` (по умолчанию `60s`):**  
   Таймаут **между двумя последовательными операциями чтения** из сокета бэкенда (не общий лимит времени выполнения!). Если бэкенд не прислал ни одного байта в течение этого интервала — генерируется `504 Gateway Timeout`.
3. **`proxy_send_timeout` (по умолчанию `60s`):**  
   Таймаут **между двумя операциями записи** в сокет бэкенда при передаче тела клиентского запроса.

#### Различие ошибок 502 Bad Gateway и 504 Gateway Timeout

| Ошибка | Сообщение в `error.log` | Физическая причина на уровне ядра/приложения |
| :--- | :--- | :--- |
| **`502 Bad Gateway`** | `connect() failed (111: Connection refused)` | Сервис бэкенда не запущен, порт закрыт, процесс упал |
| **`502 Bad Gateway`** | `upstream prematurely closed connection` | Бэкенд аварийно завершился (SIGSEGV, OOM-killer) или сбросил сокет (TCP RST) |
| **`502 Bad Gateway`** | `upstream sent too big header` | Заголовки ответа бэкенда (большие cookies, JWT) превысили `proxy_buffer_size` |
| **`502 Bad Gateway`** | `upstream sent invalid header` | Приложение вернуло некорректный ответ (не HTTP-протокол, сырой traceback) |
| **`504 Gateway Timeout`**| `upstream timed out (110: Connection timed out) while connecting` | Сетевой blackhole, пакеты SYN отбрасываются файрволом/маршрутизатором |
| **`504 Gateway Timeout`**| `upstream timed out (110: Connection timed out) while reading` | Бэкенд завис (медленный SQL-запрос, deadlock) и превысил `proxy_read_timeout` |

---

## 3. Практические сценарии и конфигурация

### Сценарий 1: Эталонный файл `proxy_params` и защита от сброса заголовков

Создание единого базового шаблона `/etc/nginx/proxy_params`:

```nginx
# /etc/nginx/proxy_params
proxy_set_header Host              $host;
proxy_set_header X-Real-IP         $remote_addr;
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-Port  $server_port;

# Протокол взаимодействия и поддержка keepalive
proxy_http_version 1.1;
proxy_set_header Connection "";

# Безопасные production-таймауты
proxy_connect_timeout 3s;
proxy_send_timeout    30s;
proxy_read_timeout    30s;

# Буферизация заголовков
proxy_buffer_size          16k;
proxy_buffers              8 16k;
proxy_busy_buffers_size    32k;
```

Подключение в виртуальном хосте:

```nginx
# /etc/nginx/conf.d/api_service.conf
server {
    listen 80;
    server_name api.example.com;

    location / {
        include proxy_params;
        
        # Добавление специфичного заголовка БЕЗ потери базовых (они подтянуты через include)
        proxy_set_header X-Request-Start $msec;
        
        proxy_pass http://10.0.1.20:8080;
    }
}
```

---

### Сценарий 2: API Gateway с вырезанием префикса (Strip Prefix) без уязвимости Off-by-slash

Маршрутизация микросервисов со сменой префикса пути:

```nginx
# /etc/nginx/conf.d/gateway.conf
upstream users_service {
    server 10.0.2.11:8000 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

upstream orders_service {
    server 10.0.2.12:8000 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

server {
    listen 443 ssl;
    server_name api.company.internal;

    ssl_certificate     /etc/nginx/ssl/api.crt;
    ssl_certificate_key /etc/nginx/ssl/api.key;

    # Срезаем префикс /api/v1/users/ -> запрос уходит в корень бэкенда /
    # ОБЯЗАТЕЛЬНО: завершающий слэш в location И завершающий слэш в proxy_pass!
    location /api/v1/users/ {
        include proxy_params;
        proxy_pass http://users_service/;
    }

    # Срезаем префикс /api/v1/orders/ -> запрос уходит как /v2/orders/
    location /api/v1/orders/ {
        include proxy_params;
        proxy_pass http://orders_service/v2/orders/;
    }

    # Запрет ненормализованных запросов для блокировки Path Traversal
    location = /api/v1/users {
        return 301 /api/v1/users/;
    }
}
```

---

### Сценарий 3: Высокопроизводительное проксирование на Unix Domain Socket (UDS)

Связка с приложением Python/Gunicorn на одном сервере:

```nginx
# /etc/nginx/conf.d/gunicorn_app.conf
upstream gunicorn_pool {
    # Подключение к Unix-сокету
    server unix:/run/gunicorn/app.sock fail_timeout=0;
    keepalive 16;
}

server {
    listen 80;
    server_name app.internal;

    location / {
        include proxy_params;
        
        # Передача запроса на сокет
        proxy_pass http://gunicorn_pool;
        
        # Перехват системных ошибок сокета
        proxy_next_upstream error timeout invalid_header;
    }
}
```

**Права доступа и безопасность сокета в Linux:**
Каталог `/run/gunicorn/` должен принадлежать группе веб-сервера (`www-data` или `nginx`):
```bash
sudo mkdir -p /run/gunicorn
sudo chown -R gunicorn:www-data /run/gunicorn
sudo chmod 770 /run/gunicorn
```

---

### Сценарий 4: Нормализация и защита Cookies для Multi-Tenant и Legacy-систем

Когда бэкенд ставит куку на внутренний домен или устаревший путь:

```nginx
# /etc/nginx/conf.d/legacy_portal.conf
server {
    listen 443 ssl;
    server_name portal.company.com;

    ssl_certificate     /etc/nginx/ssl/portal.crt;
    ssl_certificate_key /etc/nginx/ssl/portal.key;

    location /legacy/ {
        include proxy_params;
        proxy_pass http://192.168.10.50:8080/portal/;

        # 1. Замена внутреннего домена бэкенда на публичный FQDN
        proxy_cookie_domain 192.168.10.50 portal.company.com;
        proxy_cookie_domain legacy.internal portal.company.com;

        # 2. Замена внутреннего пути приложения /portal/ на внешний /legacy/
        proxy_cookie_path /portal/ /legacy/;

        # 3. Принудительное внедрение защитных флагов безопасности
        proxy_cookie_flags ~ Secure HttpOnly SameSite=Strict;
    }
}
```

---

### Сценарий 5: Полнофункциональное проксирование WebSocket с защитой от тайм-аута

```nginx
# /etc/nginx/conf.d/websocket.conf
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

upstream ws_cluster {
    server 10.0.5.21:9001;
    server 10.0.5.22:9001;
    keepalive 64;
}

server {
    listen 443 ssl;
    server_name chat.company.com;

    ssl_certificate     /etc/nginx/ssl/chat.crt;
    ssl_certificate_key /etc/nginx/ssl/chat.key;

    location /socket.io/ {
        include proxy_params;
        proxy_pass http://ws_cluster;

        # Активация механизмов HTTP Upgrade
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        # Отключение буферизации для мгновенной доставки фреймов
        proxy_buffering off;

        # Увеличение таймаута ожидания активности до 2 часов (7200s)
        proxy_read_timeout 7200s;
        proxy_send_timeout 7200s;
    }
}
```

---

### Сценарий 6: Маскировка заголовков и изоляция метаданных инфраструктуры

```nginx
# /etc/nginx/conf.d/hardened_api.conf
server {
    listen 80;
    server_name secure-api.company.com;

    location / {
        include proxy_params;
        proxy_pass http://10.0.3.15:8080;

        # Скрытие технологического стека бэкенда
        proxy_hide_header X-Powered-By;
        proxy_hide_header Server;
        proxy_hide_header X-AspNet-Version;
        proxy_hide_header X-Generated-By;

        # Игнорирование директив бэкенда, ломающих буферизацию
        proxy_ignore_headers X-Accel-Buffering;

        # Очистка входящих авторизационных заголовков, которые клиент не имеет права слать
        proxy_set_header X-Admin-Role "";
        proxy_set_header X-User-Internal-ID "";
    }
}
```

---

## 4. Операции и команды

### 1. Синтаксическая валидация и поиск ошибок `proxy_pass`

```bash
# Тестирование синтаксиса на наличие конфликтов URI в regex location
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Проверка результирующей конфигурации и директив proxy_pass
sudo nginx -T | grep -E "(proxy_pass|proxy_set_header|proxy_cookie)"
# → proxy_set_header Host $host;
# → proxy_pass http://backend_pool/;
```

### 2. Тестирование передачи заголовков и URI с помощью `curl`

```bash
# 1. Проверка заголовков ответа бэкенда и редиректов Location
curl -sI https://api.company.com/api/v1/users/
# → HTTP/1.1 200 OK
# → Server: nginx
# → Date: Fri, 17 Oct 2026 21:00:00 GMT
# → Content-Type: application/json

# 2. Проверка заголовка Set-Cookie на наличие добавленных флагов Secure и SameSite
curl -sI https://portal.company.com/legacy/login | grep -i "set-cookie"
# → set-cookie: session_id=abc123xyz; Path=/legacy/; Domain=portal.company.com; Secure; HttpOnly; SameSite=Strict

# 3. Трассировка времени установки соединения и ответа бэкенда
curl -w "Connect: %{time_connect}s | TTFB: %{time_starttransfer}s | Total: %{time_total}s\n" \
     -o /dev/null -s https://api.company.com/api/v1/users/
# → Connect: 0.002s | TTFB: 0.045s | Total: 0.048s
```

### 3. Диагностика сокетов и сетевых дескрипторов

```bash
# Проверка доступности и прав доступа к Unix Domain Socket
ls -la /run/gunicorn/app.sock
# → srw-rw---- 1 gunicorn www-data 0 Oct 17 21:10 /run/gunicorn/app.sock

# Мониторинг очереди соединений к сокету
sudo ss -xl | grep app.sock
# → u_str LISTEN 0 128 /run/gunicorn/app.sock 12345 * 0

# Просмотр соединений воркеров Nginx к портам апстрима
sudo ss -tnp | grep 8080
# → ESTAB 0 0 10.0.1.5:45210 10.0.1.20:8080 users:(("nginx",pid=1420,fd=12))
```

---

## 5. Устранение неполадок (Troubleshooting)

### Матрица типовых инцидентов и ошибок

| Ошибка в логе / Код | Первопричина | Метод локализации | Способ устранения |
| :--- | :--- | :--- | :--- |
| **`[emerg] "proxy_pass" cannot have URI part in location given by regular expression`** | В блоке `location ~ ...` директива `proxy_pass` содержит слэш или путь | `sudo nginx -t` указывает на номер строки | Удалить URI из `proxy_pass`, при необходимости использовать `rewrite ^/api/(.*)$ /target/$1 break;` |
| **`502 Bad Gateway (13: Permission denied)`** | Воркер Nginx не имеет прав на чтение/запись в файл Unix Domain Socket | `grep -E "Permission denied.*\.sock" /var/log/nginx/error.log` | Добавить пользователя `nginx`/`www-data` в группу сокета: `usermod -aG gunicorn www-data`; выставить `chmod 660` |
| **`502 Bad Gateway (2: No such file or directory)`** | Файл UDS не существует или изолирован systemd `PrivateTmp=true` | `ls -la /run/app.sock`; проверка `systemctl cat app.service` | Перенести сокет из `/tmp/` в каталог `/run/app/`; убедиться, что приложение стартовало |
| **`502 Bad Gateway (upstream sent too big header)`** | Размер кук или JWT-токенов бэкенда превысил первичный буфер | `grep "too big header" /var/log/nginx/error.log` | Увеличить размер буфера заголовков: `proxy_buffer_size 16k; proxy_busy_buffers_size 32k;` |
| **`504 Gateway Timeout (110: Connection timed out)`** | Превышен `proxy_connect_timeout` (сеть) или `proxy_read_timeout` (медленный запрос) | Декомпозиция в логе: `$upstream_connect_time` vs `$upstream_response_time` | Оптимизировать запрос в БД; при длительной выгрузке точечно поднять `proxy_read_timeout` |
| **WebSocket обрывается ровно через 60 секунд** | Отсутствует трафик в канале, сработал дефолтный `proxy_read_timeout 60s` | Таймстамп обрыва в access-логе: ровно 60 секунд после последнего пакета | Добавить в `location` WebSocket: `proxy_read_timeout 3600s;`; настроить ping/pong в приложении |
| **Потеря заголовков `X-Real-IP` и `Host`** | В дочернем `location` объявлен локальный `proxy_set_header`, сбросивший наследование | В дампе `nginx -T` проверить родительские и дочерние заголовки | Вынести базовые заголовки в `/etc/nginx/proxy_params` и добавить `include proxy_params;` |
| **Куки авторизации не сохраняются в браузере** | Несовпадение домена (`Domain`) или пути (`Path`) между бэкендом и публичным сайтом | `curl -sI https://site/login` → сравнить `Set-Cookie` с текущим URL | Добавить `proxy_cookie_domain` и `proxy_cookie_path` в блок `location` |

---

## 6. Лучшие практики (Best Practices)

1. **Всегда используйте файл `proxy_params`:** Никогда не дублируйте директивы `proxy_set_header` вручную по локейшенам. Используйте общий `include proxy_params;`, чтобы избежать случайного аннулирования заголовков авторизации и реального IP.
2. **Контролируйте слэши:** Если префикс вырезается, следите за наличием завершающего слэша в обоих местах: `location /api/ { proxy_pass http://backend/; }`. Никогда не оставляйте `location /api` со слэшем в `proxy_pass` во избежание уязвимости Off-by-slash.
3. **Очищайте недоверенные заголовки:** Если внутренняя сеть доверяет заголовкам типа `X-User-Role` или `X-Internal-Secret`, всегда принудительно обнуляйте их перед отправкой (`proxy_set_header X-User-Role "";`), чтобы исключить спуфинг внешними клиентами.
4. **Адаптируйте таймауты под профиль трафика:**
   * Web/API: `proxy_connect_timeout 2s; proxy_read_timeout 15s;`
   * WebSocket/SSE: `proxy_read_timeout 3600s;`
   * Тяжелые отчеты/экспорт: изолируйте в отдельный `location` с персональным увеличенным таймаутом.
5. **Используйте UDS на локальных хостах:** При совместном размещении веб-сервера и бэкенда на одной машине применяйте Unix Domain Sockets для экономии CPU и исключения `TIME_WAIT`.

---

## 7. Дополнительная информация

### Внутренние ссылки
- [Практическая конфигурация балансировки нагрузки](./Load_Balancing/practical_configuration.md) — upstream-пулы, keepalive-соединения, failover.
- [Редиректы в Nginx](./nginx_proxy_redirects.md) — детальная настройка директивы `proxy_redirect`.
- [Буферизация и стриминг в Nginx](./nginx_buffering_and_streaming.md) — управление памятью и диском при проксировании.
- [L4-проксирование (TCP/UDP)](./nginx_l4_proxying.md) — проксирование сокетов в модуле `stream`.
- [Диагностика и устранение неисправностей Nginx](../Operations/nginx_troubleshooting.md) — решение системных инцидентов и анализ аварийных дампов памяти.
- [Внутренняя маршрутизация в Nginx](../Core/Location/internal_routing.md) — механизмы `internal`, подзапросы и `X-Accel-Redirect`.

### Внешние авторитетные источники
- [Официальная документация модуля ngx_http_proxy_module](https://nginx.org/ru/docs/http/ngx_http_proxy_module.html)
- [Nginx Reverse Proxy Documentation](https://docs.nginx.com/nginx/admin-guide/web-server/reverse-proxy/)
