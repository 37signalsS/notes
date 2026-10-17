# Буферизация и стриминг в Nginx

**Актуально для:** Nginx 1.30.x (Stable) / 1.28.x / 1.31.x (Mainline), Angie 1.10+ / 1.12.x, Linux Kernel 5.15+ / 6.x

---

## Определения

**Буферизация ответа (Response Buffering)** — архитектурный механизм обратного прокси-сервера Nginx (модуль `ngx_http_proxy_module`), при котором Nginx полностью считывает ответ бэкенда в буферы оперативной памяти (а при их заполнении — во временный файл на диске) с максимальной скоростью сетевого интерфейса, и лишь затем последовательно передает данные клиенту со скоростью его подключения. Управляется директивами `proxy_buffering`, `proxy_buffer_size`, `proxy_buffers`, `proxy_busy_buffers_size`, `proxy_max_temp_file_size`.

**Буферизация запроса (Request Buffering)** — механизм предварительного приема тела клиентского запроса (POST, PUT, PATCH) во внутренние буферы Nginx или временный файл до открытия TCP-соединения и отправки запроса на бэкенд. Управляется директивами `proxy_request_buffering`, `client_body_buffer_size`, `client_body_temp_path` и `client_max_body_size`.

**Стриминг (Streaming / Потоковая передача)** — синхронная передача данных сквозь Nginx без их промежуточного накопления. Данные пересылаются клиенту немедленно по мере поступления байтов из сокета апстрима (для ответов) либо передаются на бэкенд синхронно по мере вычитывания от клиента (для потоковых загрузок). Критически необходим для Server-Sent Events (SSE), WebSockets, gRPC-стриминга, chunked transfer encoding и длительного экспорта данных.

**proxy_buffer_size** — размер первичного буфера оперативной памяти, выделяемого на каждое входящее прокси-соединение для считывания начальной части ответа бэкенда (HTTP-статуса и заголовков ответа). По умолчанию равен размеру одной страницы виртуальной памяти (4 КБ или 8 КБ в зависимости от архитектуры ОС).

**proxy_buffers** — пул буферов оперативной памяти фиксированного размера (задается в формате `число размер`), выделяемый для считывания тела ответа бэкенда для одного соединения. По умолчанию: `8 4k` (для 32-битных систем) или `8 8k` (для 64-битных систем x86-64).

**proxy_busy_buffers_size** — лимит суммарного объема буферов, которые могут находиться в состоянии отправки клиенту («заняты»), в то время как свободные буферы продолжают считывать последующие порции ответа из сокета бэкенда.

**proxy_max_temp_file_size** — максимальный размер временного файла на диске, в который Nginx сбрасывает тело ответа бэкенда при превышении объема памяти, выделенного через `proxy_buffers`. Значение по умолчанию: `1024m`. Установка в `0` полностью запрещает дисковый сброс ответов.

**proxy_temp_path** — каталог локальной файловой системы, в котором Nginx создает временные файлы для буферизации ответов апстрима, поддерживающий до трех уровней иерархии подкаталогов для исключения блокировок каталогов в файловых системах.

**client_body_buffer_size** — объем оперативной памяти, выделяемый для буферизации тела клиентского запроса до его сброса во временный файл в каталоге `client_body_temp_path`.

**X-Accel-Buffering** — управляющий HTTP-заголовок, передаваемый бэкендом в ответе Nginx (`X-Accel-Buffering: yes` или `X-Accel-Buffering: no`), позволяющий приложению динамически включать или отключать буферизацию ответа для конкретного HTTP-запроса без перезагрузки конфигурации прокси.

**TTFB (Time to First Byte)** — метрика сетевой задержки от момента отправки запроса клиентом до получения им первого байта тела ответа. Включение или отключение буферизации оказывает прямое влияние на значение TTFB.

---

## Основные концепции

### 1. Архитектура буферизации ответов

При работе Nginx в режиме Reverse Proxy поток данных между клиентом, прокси-сервером и бэкендом обрабатывается согласно следующей модели:

```text
                                [Буферизация включена: proxy_buffering on]
┌─────────┐      TCP (медленный канал)      ┌─────────────────────────┐      TCP (быстрый LAN)      ┌─────────┐
│ Клиент  │ ◄────────────────────────────── │  Nginx (Worker Process) │ ◄────────────────────────── │ Upstream│
└─────────┘     порции busy_buffers         │ ┌─────────────────────┐ │     максимальный вычит      └─────────┘
                                            │ │  proxy_buffer_size  │ │     (заголовки бэкенда)
                                            │ └──────────┬──────────┘ │
                                            │ ┌──────────▼──────────┐ │
                                            │ │    proxy_buffers    │ │ ──► переполнение ──► ┌────────────────┐
                                            │ └──────────┬──────────┘ │                       │proxy_temp_path │
                                            │ ┌──────────▼──────────┐ │                       │(диск / tmpfs)  │
                                            │ │busy_buffers_size    │ │                       └────────────────┘
                                            │ └─────────────────────┘ │
                                            └─────────────────────────┘

                                [Буферизация отключена: proxy_buffering off]
┌─────────┐                                 ┌─────────────────────────┐                             ┌─────────┐
│ Клиент  │ ◄══════════════════════════════ │  Nginx (Worker Process) │ ◄══════════════════════════ │ Upstream│
└─────────┘      синхронный поток байт      │   proxy_buffer_size     │     синхронный вычит        └─────────┘
                                            └─────────────────────────┘
```

#### Поведение при `proxy_buffering on;` (по умолчанию)
1. **Развязка по скорости (Speed Decoupling):** Nginx считывает ответ бэкенда с максимальной скоростью локальной сети (LAN/Loopback). Бэкенд генерирует ответ, передает его в сокет и немедленно завершает рабочий процесс/поток (PHP-FPM worker, Python WSGI worker, Go-горутину), освобождая системные ресурсы и пулы соединений к СУБД.
2. **Защита бэкендов от медленных клиентов (Slow Clients):** Если мобильный клиент с нестабильным 3G-соединением вычитывает 10 МБ ответа в течение 2 минут, этот медленный сокет держит Nginx (неблокирующий event-loop на `epoll`), а не рабочий поток дорогостоящего бэкенда.
3. **Конвейер буферов:**
   - Заголовки ответа бэкенда помещаются в `proxy_buffer_size`.
   - Тело ответа последовательно заполняет страницы оперативной памяти `proxy_buffers`.
   - Как только часть буферов готова к отправке, Nginx начинает отдавать клиенту порцию объемом до `proxy_busy_buffers_size`.
   - Если тело ответа превышает суммарную емкость `proxy_buffers`, оставшаяся часть записывается во временный файл в `proxy_temp_path` (порциями по `proxy_temp_file_write_size` до достижения `proxy_max_temp_file_size`).

#### Поведение при `proxy_buffering off;`
1. **Синхронная потоковая передача:** Nginx считывает из сокета бэкенда порцию данных размером не более `proxy_buffer_size` и немедленно отправляет ее в сокет клиента.
2. **Блокировка бэкенда медленным клиентом:** Если клиент перестает читать данные из сокета, окно TCP (`TCP receive window`) заполняется, ядро приостанавливает передачу, и бэкенд блокируется на системном вызове `write()`/`send()`.
3. **Минимизация TTFB:** Первый байт данных поступает клиенту мгновенно, не дожидаясь генерации остального тела ответа.

---

### 2. Архитектура буферизации запросов (`proxy_request_buffering`)

Директива `proxy_request_buffering` управляет тем, как Nginx передает тело клиентского HTTP-запроса (файловые загрузки, POST-запросы с большим JSON/XML) на бэкенд:

```text
[proxy_request_buffering on]
Client ──► (медленно шлет 500 МБ) ──► Nginx (накапливает в памяти/диске)
                                         │ (полное тело получено)
                                         ▼
                                      Nginx ──► (быстро передает) ──► Upstream

[proxy_request_buffering off]
Client ──► (шлет куски) ──► Nginx ──► (синхронно проксирует куски) ──► Upstream
```

| Параметр | `proxy_request_buffering on;` (дефолт) | `proxy_request_buffering off;` |
| :--- | :--- | :--- |
| **Связка клиент-бэкенд** | Полностью развязаны. Upstream вызывается только после полного получения тела запроса. | Жесткая связка. Соединение к бэкенду открывается до получения тела запроса. |
| **Защита от Slowloris/Slow POST** | Полная. Медленный клиент удерживает сокет Nginx, апстрим не задействован. | Отсутствует. Медленный аплоад удерживает воркер бэкенда на все время передачи. |
| **Отказоустойчивость (`proxy_next_upstream`)** | **Работает.** Если апстрим ответил ошибкой или разорвал связь, Nginx повторяет запрос на следующий сервер, так как тело сохранено. | **Не работает после старта передачи.** Если хотя бы один байт тела ушел в сокет апстрима, failover невозможен. |
| **Индикация прогресса (Upload Progress)** | Бэкенд не видит прогресс загрузки (получает сразу весь файл на 100%). | Бэкенд может считывать поток и отображать прогресс передачи в реальном времени. |
| **Задержка старта обработки** | Задержка равна времени полной передачи файла клиентом. | Минимальная. Бэкенд начинает парсинг потока с первого чанка. |
| **Хранилище тела** | `client_body_buffer_size` в RAM, свыше — во временные файлы `client_body_temp_path`. | Используется только `client_body_buffer_size` как промежуточный транзитный буфер. |

---

### 3. Математические ограничения и валидация конфигурации буферов

При настройке буферов в Nginx действуют строгие математические правила валидации. Нарушение этих правил приводит к ошибке синтаксиса на этапе `nginx -t`:

1. **Ограничение `proxy_busy_buffers_size`:**
   $$\text{proxy\_buffer\_size} \le \text{proxy\_busy\_buffers\_size} \le (N - 1) \times S$$
   где $N$ — количество буферов, а $S$ — размер одного буфера из директивы `proxy_buffers N S;`.
   - Если `proxy_busy_buffers_size` меньше `proxy_buffer_size` или размера одного буфера из `proxy_buffers`, Nginx выдаст фатальную ошибку:
     `"proxy_busy_buffers_size" must be equal to or greater than the maximum of the "proxy_buffer_size" and one of the "proxy_buffers"`
   - Если `proxy_busy_buffers_size` больше или равен суммарному размеру всех `proxy_buffers` минус один буфер, Nginx выдаст:
     `"proxy_busy_buffers_size" must be less than the size of all "proxy_buffers" minus one buffer`

2. **Ограничение `proxy_temp_file_write_size`:**
   $$\max(\text{proxy\_buffer\_size}, S) \le \text{proxy\_temp\_file\_write\_size} \le 2 \times \text{proxy\_busy\_buffers\_size}$$
   По умолчанию параметр равен $2 \times \text{proxy\_buffer\_size}$ (или $2 \times S$).

3. **Сводная таблица параметров директив:**

| Директива | Синтаксис | Значение по умолчанию | Контекст | Допустимость переменных |
| :--- | :--- | :--- | :--- | :--- |
| `proxy_buffering` | `on \| off` | `on` | `http`, `server`, `location` | **Нет** (только строгий литерал `on`/`off`) |
| `proxy_buffer_size` | `size` | `4k` (32-bit) / `8k` (64-bit) | `http`, `server`, `location` | Нет |
| `proxy_buffers` | `number size` | `8 4k` (32-bit) / `8 8k` (64-bit) | `http`, `server`, `location` | Нет |
| `proxy_busy_buffers_size` | `size` | $2 \times \text{proxy\_buffer\_size}$ (`8k`/`16k`) | `http`, `server`, `location` | Нет |
| `proxy_max_temp_file_size` | `size` | `1024m` | `http`, `server`, `location` | Нет |
| `proxy_temp_file_write_size` | `size` | $2 \times \text{proxy\_buffer\_size}$ (`8k`/`16k`) | `http`, `server`, `location` | Нет |
| `proxy_temp_path` | `path [level1 [level2 [level3]]]` | `proxy_temp` (путь сборки) | `http`, `server`, `location` | Нет |
| `proxy_request_buffering` | `on \| off` | `on` (с 1.7.11) | `http`, `server`, `location` | Нет |
| `client_body_buffer_size` | `size` | $2 \times \text{страница памяти}$ (`8k`/`16k`) | `http`, `server`, `location` | Нет |
| `client_body_temp_path` | `path [level1 [level2 [level3]]]` | `client_body_temp` | `http`, `server`, `location` | Нет |

> [!IMPORTANT]
> Директива `proxy_buffering` парсится Nginx через внутренний обработчик `ngx_conf_set_flag_slot` и принимает **исключительно литералы `on` или `off`**. Попытка передать переменную (например, `proxy_buffering $buffered;`) приведет к фатальной ошибке конфигурации: `invalid value "$buffered" in "proxy_buffering" directive, it must be "on" or "off"`. Динамическое переключение буферизации выполняется только через заголовок ответа `X-Accel-Buffering` либо разнесением по разным блокам `location`.

---

### 4. Взаимодействие с дисковой подсистемой и ядром Linux

При активной буферизации ответов объемом свыше размера `proxy_buffers` поведение сервера напрямую зависит от характеристик локальной системы:

1. **Дисковый I/O и износ накопителей:**
   - Сброс ответов во временные файлы создает нагрузку случайной записи (`write`) и последующего чтения (`read`) для отправки клиенту, после чего файл немедленно удаляется через `unlink()`.
   - В высоконагруженных окружениях со смешанным трафиком сброс буферов на обычные накопители вызывает задержки дискового ввода-вывода (IO wait spikes), деградируя производительность всего сервера.
2. **Иерархия каталогов (`level1 level2`):**
   - Указание уровней подкаталогов (например, `proxy_temp_path /var/cache/nginx/proxy_temp 1 2;`) распределяет временные файлы по двухуровневой структуре (например, `.../proxy_temp/7/42/0000012342`).
   - Это предотвращает деградацию производительности файловой системы (блокировки inode и каталогов ext4/xfs), когда в одной директории одновременно создаются десятки тысяч временных файлов.
3. **Размещение во временной памяти (`tmpfs`):**
   - Перенос каталога `proxy_temp_path` в оперативную память (`tmpfs`) исключает физический износ NVMe/SSD и предотвращает просадки по дисковому I/O.
4. **Сокетные буферы ОС (`SO_RCVBUF` / `SO_SNDBUF`):**
   - Если буферы сокета Nginx меньше окна приема ядра (`net.ipv4.tcp_rmem`, `net.ipv4.tcp_wmem`), ядро начинает масштабировать TCP-окно, что при отключенной буферизации может приводить к микропаузам передачи.

---

### 5. Взаимосвязь с другими подсистемами Nginx

- **Серверное кэширование (`proxy_cache`):** Модуль кэширования функционально завязан на механизм буферизации. Если задано `proxy_buffering off;`, серверное кэширование **полностью отключается** (ответ отдается клиенту транзитом, переменная `$upstream_cache_status` остается пустой).
- **Отказоустойчивость (`proxy_next_upstream`):** Повторная отправка запроса на другой бэкенд при сбое возможна только до тех пор, пока клиенту не отправлен хотя бы один байт заголовка или тела ответа. При `proxy_buffering off;` данные сразу уходят в сокет клиента, поэтому при ошибке бэкенда в процессе передачи Nginx вынужден разорвать соединение с клиентом.
- **Динамическое сжатие (`gzip` / `brotli`):** Модули компрессии накапливают потоковые блоки данных для вычисления словарей сжатия. Если для SSE или WebSocket включен `gzip on;`, события будут задерживаться в буфере компрессора, даже если задано `proxy_buffering off;`. Для стриминговых эндпоинтов директива `gzip off;` строго обязательна.

---

## Практические сценарии

### Сценарий 1: Высоконагруженный API со сбалансированной буферизацией (Production REST/GraphQL)

Оптимизированная конфигурация для микросервисов, исключающая появление ошибок `upstream sent too big header` из-за крупных JWT/Set-Cookie и минимизирующая сброс типичных JSON-ответов на диск.

```nginx
# /etc/nginx/conf.d/api_upstream.conf

# Формат лога с раздельным учетом времени бэкенда и полной передачи клиенту
log_format api_performance '$remote_addr - [$time_local] "$request" '
                           'status=$status bytes=$body_bytes_sent '
                           'request_time=$request_time '
                           'upstream_response_time=$upstream_response_time '
                           'upstream_connect_time=$upstream_connect_time '
                           'upstream_header_time=$upstream_header_time '
                           'pipe=$pipe';

upstream backend_cluster {
    server 127.0.0.1:8081 max_fails=3 fail_timeout=10s;
    server 127.0.0.1:8082 max_fails=3 fail_timeout=10s;
    keepalive 64;
}

server {
    listen 80;
    server_name api.example.internal;

    access_log /var/log/nginx/api_access.log api_performance;
    error_log  /var/log/nginx/api_error.log warn;

    location /api/ {
        proxy_pass http://backend_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # Буферизация ответов
        proxy_buffering on;
        
        # 32k для заголовков (защита от больших Cookie, Header authorization, JWT)
        proxy_buffer_size 32k;
        
        # 16 буферов по 32k = 512k оперативной памяти под тело ответа
        proxy_buffers 16 32k;
        
        # Объем буфера, выдаваемого клиенту: 64k (должен быть >= 32k и <= 15 * 32k = 480k)
        proxy_busy_buffers_size 64k;
        
        # Порция единовременной записи во временный файл при превышении 512k
        proxy_temp_file_write_size 64k;
        
        # Максимальный размер временного файла на диске для ответа
        proxy_max_temp_file_size 256m;
        proxy_temp_path /var/cache/nginx/proxy_temp 1 2;

        # Таймауты ожидания ответа
        proxy_connect_timeout 5s;
        proxy_read_timeout 30s;
        proxy_send_timeout 30s;
    }
}
```

Проверка валидности конфигурации и ограничений буферов:

```bash
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
```

---

### Сценарий 2: Потоковая передача данных в реальном времени (Server-Sent Events / SSE)

Конфигурация для эндпоинтов реального времени (SSE, AI-генерации текста, котировок, метрик), требующая отключения всех промежуточных очередей и буферов.

```nginx
# /etc/nginx/conf.d/sse_streaming.conf

server {
    listen 80;
    server_name events.example.internal;

    location /events/ {
        proxy_pass http://127.0.0.1:9000;
        proxy_http_version 1.1;

        # Отключение буферизации прокси — данные транслируются сразу по поступлению
        proxy_buffering off;

        # Отключение серверного кэширования для динамического потока
        proxy_cache off;

        # Отключение сжатия gzip, предотвращающее задержку чанков в буфере архиватора
        gzip off;

        # Очистка заголовка Connection для стабильного HTTP/1.1 keepalive к бэкенду
        proxy_set_header Connection '';
        proxy_set_header Host $host;

        # Отключение буферизации чанков на стороне клиента
        proxy_set_header X-Accel-Buffering 'no';

        # Длительный таймаут чтения сокета для долгоживущих стримов
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

Тестирование стриминга без буферизации с помощью `curl`:

```bash
# Флаг -N (--no-buffer) заставляет curl выводить порции данных немедленно
curl -N -H "Accept: text/event-stream" http://events.example.internal/events/
# → data: {"timestamp": 1718000001, "event": "tick"}
# → data: {"timestamp": 1718000002, "event": "tick"}
```

---

### Сценарий 3: Потоковая загрузка больших файлов (`proxy_request_buffering off;`)

Сценарий для S3-совместимых хранилищ, медиасерверов и систем обработки видео, где загрузка файлов размером в гигабайты не должна накапливаться на диске Nginx.

```nginx
# /etc/nginx/conf.d/upload_streaming.conf

server {
    listen 80;
    server_name storage.example.internal;

    # Максимальный допустимый размер тела клиентского запроса
    client_max_body_size 10g;

    location /upload/ {
        proxy_pass http://127.0.0.1:9050;
        proxy_http_version 1.1;
        proxy_set_header Host $host;

        # Отключение буферизации запроса — тело стримится напрямую в сокет бэкенда
        proxy_request_buffering off;

        # Транзитный буфер в оперативной памяти для чтения порций тела
        client_body_buffer_size 128k;

        # Защита: тайм-аут между двумя последовательными операциями чтения от клиента
        client_body_timeout 60s;

        # Таймаут ожидания передачи данных на бэкенд
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;

        # Отключаем буферизацию ответа, если бэкенд сразу возвращает статус обработки
        proxy_buffering off;
    }
}
```

> [!WARNING]
> При `proxy_request_buffering off;` соединение с бэкендом удерживается на протяжении всего времени загрузки файла клиентом. Обязательно ограничивайте количество одновременных загрузок через `limit_conn` для предотвращения исчерпания пула соединений бэкенда медленными клиентами.

---

### Сценарий 4: Работа в оперативной памяти без сброса на диск (`proxy_max_temp_file_size 0;`)

Сценарий для высоконагруженных шлюзов с высокоскоростными SSD/NVMe, где дисковый I/O зарезервирован под базы данных или логирование, а промежуточные временные файлы Nginx не допускаются.

```nginx
# /etc/nginx/conf.d/memory_only_proxy.conf

server {
    listen 80;
    server_name inmemory.example.internal;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        proxy_buffering on;
        proxy_buffer_size 16k;
        proxy_buffers 32 16k;         # 512 КБ в памяти на соединение
        proxy_busy_buffers_size 32k;

        # Полный запрет сброса ответа бэкенда во временные файлы на диск
        proxy_max_temp_file_size 0;

        proxy_connect_timeout 2s;
        proxy_read_timeout 15s;
    }
}
```

*Механика поведения:* Если ответ бэкенда превышает 512 КБ (`proxy_buffers`), Nginx считывает первые 512 КБ, останавливает вычитку из сокета бэкенда и ждет, пока клиент прочитает данные из сокета Nginx. После освобождения части буферов Nginx вычитывает следующую порцию ответа. Upstream при этом притормаживается до скорости клиента.

---

### Сценарий 5: Стриминг gRPC-сервисов (`grpc_buffering off;`)

Для двунаправленного (bidirectional) или серверного (server-side) gRPC-стриминга используются директивы модуля `ngx_http_grpc_module`.

```nginx
# /etc/nginx/conf.d/grpc_streaming.conf

upstream grpc_cluster {
    server 127.0.0.1:50051;
    server 127.0.0.1:50052;
    keepalive 32;
}

server {
    listen 443 ssl http2;
    server_name grpc.example.internal;

    ssl_certificate     /etc/ssl/certs/grpc.crt;
    ssl_certificate_key /etc/ssl/private/grpc.key;

    location /routeguide.RouteGuide/ {
        grpc_pass grpc://grpc_cluster;

        # Размер буфера для чтения заголовков ответа gRPC
        grpc_buffer_size 16k;

        # Отключение буферизации ответов для мгновенной трансляции gRPC фреймов
        grpc_buffering off;

        # Таймауты между операциями в стриме
        grpc_read_timeout 1800s;
        grpc_send_timeout 1800s;
    }
}
```

---

### Сценарий 6: Динамическое управление со стороны бэкенда (`X-Accel-Buffering`)

Бэкенд-приложение может управлять буферизацией каждого конкретного HTTP-ответа, передавая специальный заголовок `X-Accel-Buffering`.

Пример генерации ответа бэкендом (Python / Go / PHP):
```http
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
Connection: keep-alive
```

Конфигурация Nginx:

```nginx
location /dynamic-service/ {
    proxy_pass http://app_cluster;
    proxy_buffering on; # По умолчанию буферизация включена для всего сервиса

    # Если бэкенд отдает "X-Accel-Buffering: no", Nginx отключает буферизацию для этого ответа.
    # Если требуется принудительно запретить бэкенду отключать буферизацию, раскомментируйте:
    # proxy_ignore_headers X-Accel-Buffering;
}
```

---

### Сценарий 7: Оптимизация временного хранилища на RAM-диске (`tmpfs`)

Для защиты физических накопителей от сотен мегабайт временных файлов `proxy_temp` системный администратор настраивает выделенный RAM-диск.

Монтирование `tmpfs` в Linux:

```bash
# Добавление точки монтирования в /etc/fstab
echo "tmpfs /var/cache/nginx/proxy_temp tmpfs defaults,noatime,mode=0700,uid=nginx,gid=nginx,size=1G 0 0" >> /etc/fstab
mkdir -p /var/cache/nginx/proxy_temp
mount /var/cache/nginx/proxy_temp
```

Конфигурация в Nginx:

```nginx
# В контексте http или server
proxy_temp_path /var/cache/nginx/proxy_temp 1 2;
proxy_max_temp_file_size 512m;
```

---

## Операции и команды

### 1. Синтаксическая валидация и проверка ограничений буферов

Всегда проверяйте конфигурацию перед перезагрузкой процесса:

```bash
# Проверка синтаксиса и математической корректности размеров буферов
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Безопасное применение конфигурации без разрыва соединений
systemctl reload nginx
```

### 2. Проверка стриминга и поведения буферизации через `curl`

```bash
# Проверка времени до первого байта (TTFB) и поведения чанков
curl -i -N -v --raw http://events.example.internal/events/
# → < HTTP/1.1 200 OK
# → < Transfer-Encoding: chunked
# → < Content-Type: text/event-stream
# → [данные поступают построчно без задержек]

# Замер времени получения заголовков и полного тела
curl -o /dev/null -s -w 'TTFB: %{time_starttransfer}s | Total: %{time_total}s\n' http://api.example.internal/api/items
# → TTFB: 0.042s | Total: 0.125s
```

### 3. Мониторинг временных файлов и дескрипторов

```bash
# Просмотр открытых временных файлов воркерами Nginx
lsof -c nginx | grep -E 'proxy_temp|client_body'
# → nginx 14502 nginx    9u   REG   0,45  10485760  28914 /var/cache/nginx/proxy_temp/3/12/0000001234 (deleted)

# Проверка занимаемого дискового пространства временными файлами
du -sh /var/cache/nginx/proxy_temp /var/lib/nginx/body
# → 14M    /var/cache/nginx/proxy_temp
# → 0B     /var/lib/nginx/body
```

### 4. Профилирование дисковой активности буферизации

```bash
# Мониторинг нагрузки на дисковое устройство, где расположен proxy_temp_path
iostat -xz 1
# → Device    r/s     w/s     rkB/s     wkB/s  %util
# → nvme0n1  0.00  124.00      0.00  15872.00   8.50
```

### 5. Анализ состояния сокетов и буферов ядра

```bash
# Просмотр очередей приема и отправки сокетов Nginx
ss -tnpi '( sport = :80 or sport = :443 )'
# → State    Recv-Q Send-Q  Local Address:Port   Peer Address:Port
# → ESTAB    0      131072  10.0.0.1:80          192.168.1.50:54321
# →   cubic wscale:7,7 rto:200 rtt:1.2/0.4 ato:40 cwnd:10 ssthresh:7
```

---

## Устранение неполадок

### 1. `upstream sent too big header while reading response header from upstream`

**Симптом:** Клиент получает `502 Bad Gateway`. В файле `error.log` фиксируется ошибка:
```text
[error] 14210#14210: *84512 upstream sent too big header while reading response header from upstream, client: 192.168.1.10, server: api.example.com, request: "GET /api/user/profile HTTP/1.1", upstream: "http://127.0.0.1:8081/api/user/profile"
```

**Причина:** Суммарный размер HTTP-заголовков бэкенда (большие заголовки `Set-Cookie`, крупные токены авторизации JWT, длинный `Location`) превысил размер буфера `proxy_buffer_size`.

**Решение:**
1. Увеличьте `proxy_buffer_size` до 16k, 32k или 64k.
2. Скорректируйте `proxy_busy_buffers_size`, чтобы он удовлетворял правилу: $\text{proxy\_busy\_buffers\_size} \ge \text{proxy\_buffer\_size}$.

```nginx
location /api/ {
    proxy_pass http://backend_cluster;
    proxy_buffer_size 32k;
    proxy_buffers 8 32k;
    proxy_busy_buffers_size 64k;
}
```

---

### 2. Предупреждение `an upstream response is buffered to a temporary file`

**Симптом:** В `error.log` появляется предупреждение уровня `warn`:
```text
[warn] 14210#14210: *98213 an upstream response is buffered to a temporary file /var/cache/nginx/proxy_temp/4/18/0000003184 while reading upstream, client: 10.10.1.25, server: api.example.com, request: "GET /reports/export HTTP/1.1", upstream: "http://127.0.0.1:8081/reports/export"
```

**Причина:** Ответ бэкенда превысил суммарный объем буферов оперативной памяти `proxy_buffers` (например, ответ размером 4 МБ при пуле буферов `8 64k = 512k`). Nginx был вынужден сбросить излишек на диск.

**Решение:**
1. Если это штатный эндпоинт экспорта отчетов или медиафайлов — отключите буферизацию в целевом `location`: `proxy_buffering off;`.
2. Если ответы регулярно немного превышают пул буферов — увеличьте количество буферов: `proxy_buffers 16 64k;` (1 МБ) и `proxy_busy_buffers_size 128k;`.
3. Для защиты диска перенесите `proxy_temp_path` в `tmpfs` либо задайте `proxy_max_temp_file_size 0;` (если приемлемо торможение бэкенда до скорости клиента).

---

### 3. Ошибка `open() "/var/cache/nginx/proxy_temp/..." failed (13: Permission denied)`

**Симптом:** Ошибка `502 Bad Gateway` при попытке буферизации крупного ответа на диск:
```text
[crit] 14210#14210: *100412 open() "/var/cache/nginx/proxy_temp/1/02/0000001021" failed (13: Permission denied) while reading upstream
```

**Причина:** Некорректные права доступа к каталогу `proxy_temp_path`. Воркер Nginx работает от непривилегированного пользователя (`nginx` или `www-data`), а каталог принадлежит пользователю `root`.

**Решение:**

```bash
# Определение пользователя рабочих процессов
grep -E '^user ' /etc/nginx/nginx.conf
# → user nginx;

# Восстановление прав на каталоги временных файлов
chown -R nginx:nginx /var/cache/nginx/proxy_temp
chmod 700 /var/cache/nginx/proxy_temp
```

---

### 4. Задержка доставки событий, пачечный вывод и высокий TTFB в SSE/WebSocket

**Симптом:** При подключении к потоковому эндпоинту Server-Sent Events клиент не получает данные в реальном времени; события приходят пачками по 4–8 КБ либо только после закрытия соединения.

**Причины:**
1. Включена буферизация ответа (`proxy_buffering on;`).
2. Включено динамическое сжатие (`gzip on;`), накапливающее блоки перед отправкой.
3. Отсутствует очистка заголовка `Connection`, из-за чего соединение закрывается по таймауту.

**Решение:**

```nginx
location /sse/ {
    proxy_pass http://sse_backend;
    proxy_http_version 1.1;
    proxy_set_header Connection '';

    # Отключаем буферизацию и сжатие
    proxy_buffering off;
    proxy_cache off;
    gzip off;

    # Увеличиваем таймаут удержания сокета
    proxy_read_timeout 3600s;
}
```

---

### 5. `client prematurely closed connection while reading client request body`

**Симптом:** Ошибка `499` или `408` в `access.log` при потоковой загрузке файлов:
```text
[info] 14210#14210: *12041 client prematurely closed connection while reading client request body, client: 198.51.100.2
```

**Причина:** Клиент с медленным или нестабильным соединением не уложился в `client_body_timeout` (по умолчанию 60 секунд) между двумя последовательными операциями чтения при `proxy_request_buffering off;`.

**Решение:** Увеличьте `client_body_timeout`:

```nginx
location /upload/ {
    proxy_pass http://upload_service;
    proxy_request_buffering off;
    client_body_timeout 120s;
    client_max_body_size 5g;
}
```

---

### 6. Сбой отказоустойчивости бэкенда (`proxy_next_upstream` не срабатывает)

**Симптом:** При падении одного из серверов в `upstream` запрос завершается ошибкой `502` вместо переключения на резервный узел.

**Причина:** Была отключена буферизация (`proxy_buffering off;` или `proxy_request_buffering off;`). Если Nginx уже начал отправлять тело клиенту или передавать тело запроса на первый сервер, повторная отправка запроса на другой узел (`proxy_next_upstream`) запрещена протоколом HTTP для исключения дублирования операций.

**Решение:** Для эндпоинтов, требующих высокой доступности и повторных попыток (`idempotent requests`), держите буферизацию включенной: `proxy_buffering on;` и `proxy_request_buffering on;`.

---

### 7. Ошибка синтаксиса: `"proxy_busy_buffers_size" must be less than the size of all "proxy_buffers" minus one buffer`

**Симптом:** При выполнении `nginx -t` выводится ошибка:
```text
nginx: [emerg] "proxy_busy_buffers_size" must be less than the size of all "proxy_buffers" minus one buffer in /etc/nginx/conf.d/api.conf:24
```

**Причина:** В конфигурации задано, например: `proxy_buffers 4 16k;` (всего 64k) и `proxy_busy_buffers_size 64k;`. По правилам Nginx максимальный размер занятых буферов обязан быть строго меньше суммарного объема за вычетом одного буфера: $(4 - 1) \times 16k = 48k$.

**Решение:** Установите `proxy_busy_buffers_size 32k;` (или `48k;`).

---

## Лучшие практики

1. **Оставляйте буферизацию ответов включенной по умолчанию:**
   - Буферизация защищает ресурсы бэкендов от медленных каналов связи клиентов.
   - Отключайте буферизацию (`proxy_buffering off;`) строго точечно внутри выделенных блоков `location` (для SSE, WebSocket, непрерывного экспорта файлов или gRPC).

2. **Расчет сайзинга буферов (Capacity Planning):**
   - Устанавливайте `proxy_buffer_size` исходя из 99-го перцентиля размера заголовков бэкенда (стандартный оптимум для JWT и Cookies — `16k` или `32k`).
   - Рассчитывайте `proxy_buffers` так, чтобы 95% типичных ответов бэкенда помещались в оперативную память без сброса на диск (например, `8 16k` = 128k или `16 32k` = 512k).
   - Учитывайте потребление оперативной памяти: при 10 000 одновременных активных соединений с буферами по 512 КБ максимальный теоретический расход RAM составит около 5 ГБ.

3. **Соблюдайте формулу для `proxy_busy_buffers_size`:**
   - Рекомендуемое значение: $2 \times \text{размер одного буфера}$ (например, при `proxy_buffers 8 16k;` задавайте `proxy_busy_buffers_size 32k;`).

4. **Защита дисковой подсистемы от деградации IOPS:**
   - В высоконагруженных системах обязательно выносите `proxy_temp_path` на RAM-диск (`tmpfs`) с ограничением по квоте.
   - Используйте двухуровневую иерархию подкаталогов: `proxy_temp_path /var/cache/nginx/proxy_temp 1 2;`.
   - Задавайте разумный предел `proxy_max_temp_file_size` (например, `256m` или `512m`), чтобы аномально большой ответ бэкенда не забил дисковый раздел.

5. **Обеспечение безопасности при загрузке данных (`proxy_request_buffering`):**
   - Оставляйте `proxy_request_buffering on;` для стандартных форм и публичных API для защиты от атак Slowloris / Slow POST.
   - Отключайте буферизацию запросов (`proxy_request_buffering off;`) только для специализированных эндпоинтов загрузки крупных файлов, обязательно комбинируя это с директивами ограничения соединений (`limit_conn`) и жесткими таймаутами `client_body_timeout`.

6. **Управление стримингом из приложения (`X-Accel-Buffering`):**
   - Вместо жесткого разнесения по префиксам URI в Nginx используйте отдачу заголовка `X-Accel-Buffering: no` непосредственно из бэкенд-сервиса, когда он переходит в потоковый режим.

---

## Дополнительная информация

### Взаимосвязи в базе знаний

- **[Архитектура и ядро HTTP Reverse Proxy](./nginx_reverse_proxy_core.md)** — фундаментальные правила `proxy_pass`, трансформация URI, сброс наследования заголовков, куки и UDS.
- **[Разделение трафика и теневое зеркалирование](./nginx_traffic_mirroring_and_splitting.md)** — канареечные релизы (`split_clients`) и теневой трафик (`mirror`).
- **[Практическая конфигурация балансировки](./Load_Balancing/practical_configuration.md)** — реализация балансировки нагрузки upstream, пулы `keepalive` и тайм-ауты соединений.
- **[Обзор концепций балансировки L7](./Load_Balancing/overview_concepts.md)** — архитектура обработки запросов на прикладном уровне L7 и жизненный цикл соединений.
- **[Проверка состояния и мониторинг балансировки](./Load_Balancing/health_checks_and_monitoring.md)** — поведение директивы `proxy_next_upstream` и влияние буферизации на отказоустойчивость.
- **[Серверное кэширование (Proxy Cache)](../Performance/Caching/proxy_caching.md)** — влияние `proxy_buffering` на работу кэша и алгоритмы хранения ответов.
- **[Оптимизация производительности Nginx](../Performance/nginx_performance_tuning.md)** — тюнинг параметров ядра Linux (`epoll`, TCP-буферы, сокеты) и воркеров Nginx.
- **[Сжатие данных (Gzip и Brotli)](../Performance/nginx_compression.md)** — правила взаимодействия динамического сжатия со стриминговыми протоколами.
- **[Отдача статических файлов](../Core/Location/serving_files.md)** — механизмы `sendfile`, `aio` и `directio` для передачи файлов с диска без проксирования.
- **[Диагностика и устранение неполадок Nginx](../Operations/nginx_troubleshooting.md)** — общая диагностика ошибок 502, 504 и таймаутов проксирования.
- **[Анализ логов Nginx](../Operations/nginx_log_analysis.md)** — разбор сетевых метрик `$upstream_response_time`, `$request_time` и кодов ответов.
- **[Angie: WebSocket, SSE, gRPC](../../Angie/angie-websocket-sse-grpc.md)** — настройка протоколов реального времени и потоковой передачи в сервере Angie.
- **[Angie: Reverse Proxy](../../Angie/angie_reverse_proxy.md)** — особенности архитектуры обратного прокси и потоковой отдачи в Angie.