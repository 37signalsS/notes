# uWSGI, SCGI, WSGI, FastCGI: интерфейсы бэкендов

**Актуально для:** uWSGI 2.0.x, WSGI (PEP 3333), SCGI 1.7, FastCGI 1.0, Nginx 1.24+ / 1.26+, Angie 1.4+

---

## Определения

**WSGI (Web Server Gateway Interface)** — стандарт синхронного интерфейса между веб-сервером и приложением на языке Python ([PEP 3333](https://peps.python.org/pep-3333/)). Не является сетевым протоколом; представляет собой соглашение на уровне языка, где веб-сервер вызывает функцию приложения, передавая словарь переменных окружения `environ` и обратный вызов `start_response`.

**ASGI (Asynchronous Server Gateway Interface)** — преемник WSGI, ориентированный на асинхронную обработку запросов (`asyncio`), поддержку WebSockets, Server-Sent Events и HTTP/2. Поддерживается серверами Uvicorn, Hypercorn, Daphne.

**uWSGI** — модульный C-сервер приложений высокой производительности, реализующий сетевой протокол `uwsgi` и интерфейсы для Python (WSGI), Ruby (Rack), Perl (PSGI), PHP и других языков. Включает встроенные механизмы супервизора процессов, балансировки, очередей и кэширования.

**Протокол `uwsgi`** — бинарный сетевой протокол взаимодействия веб-сервера (Nginx, Angie, Apache) с сервером uWSGI. Характеризуется 4-байтным заголовком, передачей атрибутов в компактном виде (ключ-значение) и минимальными накладными расходами на сериализацию.

**SCGI (Simple Common Gateway Interface)** — текстовый протокол передачи запросов от веб-сервера к приложению по сетевому или UNIX-сокету (спецификация v1.7). Является упрощенной альтернативой FastCGI, использующей формат Netstrings для передачи заголовков без сложного бинарного мультиплексирования.

**FastCGI (Fast Common Gateway Interface)** — бинарный клиент-серверный протокол для взаимодействия веб-сервера с долгоживущими изолированными процессами приложений. Устраняет накладные расходы классического CGI на создание (`fork`/`exec`) отдельного процесса ОС на каждый HTTP-запрос.

**PHP-FPM (FastCGI Process Manager)** — специализированный менеджер пулов процессов PHP, реализующий спецификацию FastCGI.

**UNIX Domain Socket (UDS)** — механизм межпроцессного взаимодействия (IPC) в рамках одной операционной системы (семейство `AF_UNIX`), передающий байтовые потоки через кольцевые буферы ядра Linux без участия сетевого стека, контрольных сумм и сетевых адаптеров.

**Emperor Mode** — режим супервизора в uWSGI, при котором главный процесс («Император») сканирует каталог с файлами конфигурации и автоматически запускает, перезапускает или останавливает изолированные инстансы приложений («Вассалы»).

**Harakiri Mode** — защитный сторожевой таймер (watchdog) в uWSGI, который принудительно прерывает и перезапускает рабочий процесс, если время обработки запроса превысило заданный интервал.

---

## Основные концепции и архитектура

### Сравнительный анализ шлюзовых интерфейсов и протоколов

Для интеграции веб-серверов (Nginx, Angie, Apache) с языковыми бэкендами используются протоколы различного уровня абстракции:

```
[ HTTP/HTTPS Запрос от клиента ]
             │
             ▼
[ Reverse Proxy / Edge: Nginx / Angie / Apache ]
             │
   ┌─────────┼─────────────────────┬─────────────────────┐
   │         │                     │                     │
   │ uwsgi   │ FastCGI             │ SCGI                │ HTTP/1.1
   │ (бинарн)│ (бинарн)            │ (Netstrings)        │ (текстовый)
   ▼         ▼                     ▼                     ▼
[ uWSGI ]  [ PHP-FPM ]           [ SCGI Backend ]      [ Gunicorn / Node ]
   │ (PEP 3333)                    │                     │
   ▼                               ▼                     ▼
[ Python ] [ PHP App ]           [ C/Python App ]      [ WSGI/ASGI/JS ]
```

| Параметр | WSGI (PEP 3333) | Протокол `uwsgi` | FastCGI | SCGI | HTTP Reverse Proxy |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Уровень** | API языка (In-process) | Сетевой/IPC (L7 wire) | Сетевой/IPC (L7 wire) | Сетевой/IPC (L7 wire) | Сетевой/IPC (L7 wire) |
| **Формат данных** | Python Dict / Callables | Бинарный (4B заголовок) | Бинарный (8B фрейм) | Netstrings (текстовый) | Текстовый HTTP/1.1 |
| **Мультиплексирование**| Нет | Нет (1 запрос на сокет)| Поддерживается стандартом (на практике редко) | Нет | Да (HTTP/2) / Нет (HTTP/1.1) |
| **Оверхед на парсинг** | Нулевой (передача ссылок)| Минимальный (бинарный) | Низкий (бинарный) | Минимальный (strchr/len)| Средний (парсинг HTTP) |
| **Поддержка в Nginx** | Нет (нужен app-сервер) | Встроенный (`uwsgi_pass`) | Встроенный (`fastcgi_pass`)| Встроенный (`scgi_pass`) | Встроенный (`proxy_pass`) |
| **Основная ниша** | Соглашение Python | Python, Ruby, C++ | PHP (PHP-FPM), C/C++ | rTorrent, legacy Python | Node.js, Go, Java, ASGI |

---

### Структура пакетов и фреймов на уровне проводного протокола

#### 1. Бинарный протокол `uwsgi`

Каждый пакет uwsgi начинается с фиксированного 4-байтового заголовка:

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|   Modifier1   |         Datasize (16-bit LE)  |   Modifier2   |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
|          Payload: Key-Value словарь переменных окружения      |
|                                                               |
```

- **Modifier1 (1 байт):** определяет обработчик/плагин назначения внутри сервера uWSGI:
  - `0` — Python (WSGI-интерфейс);
  - `1` — Erlang;
  - `3` — Сырой режим (Raw / Reverse Proxy);
  - `5` — Perl (PSGI);
  - `6` — Lua;
  - `8` — Ruby (Rack);
  - `14` — PHP;
  - `18` — JVM;
  - `26` — CGI.
- **Datasize (2 байта, Little Endian):** размер полезной нагрузки блока переменных (максимум $65\,535$ байт на один блок). Если размер заголовков превышает 64 КБ, требуется фрагментация пакета.
- **Modifier2 (1 байт):** дополнительный флаг протокола (обычно `0`).
- **Полезная нагрузка (Payload):** последовательность пар `(ключ, значение)`. Каждая строка кодируется парой: 16-битная длина ключа (LE) + тело ключа + 16-битная длина значения (LE) + тело значения.
- **Тело запроса (Request Body):** передается следом за блоком переменных в виде сырого потока данных.

#### 2. Текстовый протокол SCGI

Формат сообщения SCGI состоит из заголовков, упакованных в формат **Netstring**, за которыми непосредственно следует тело запроса:

```
[Длина заголовков в байтах]:CONTENT_LENGTH\0<len>\0SCGI\01\0<Key>\0<Val>\0,[Тело запроса...]
```

Правила формирования:
1. Заголовки упаковываются в один блок, разделенный нулевыми байтами `\0`.
2. Первым заголовком обязательно идет `CONTENT_LENGTH`.
3. Вторым заголовком обязательно идет `SCGI` со значением `1`.
4. Длина полученного блока записывается в ASCII-цифрах, за которыми ставится двоеточие `:`, далее сам блок, завершающийся запятой `,`.
5. После запятой передается ровно `CONTENT_LENGTH` байт тела запроса.

Пример сообщения SCGI без тела:
```text
27:CONTENT_LENGTH\00\0SCGI\01\0,
```

#### 3. Бинарный протокол FastCGI

FastCGI передает данные дискретными записями с фиксированным 8-байтовым заголовком:

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|    Version    |     Type      |          RequestId            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|       ContentLength           | PaddingLength |    Reserved   |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
|        ContentData (ContentLength байт) + PaddingData         |
|                                                               |
```

- **Version (1 байт):** версия протокола (всегда `0x01`).
- **Type (1 байт):** тип записи:
  - `1` (`FCGI_BEGIN_REQUEST`) — открытие нового запроса;
  - `2` (`FCGI_ABORT_REQUEST`) — прерывание запроса сервером;
  - `3` (`FCGI_END_REQUEST`) — завершение обработки бэкендом;
  - `4` (`FCGI_PARAMS`) — поток переменных окружения;
  - `5` (`FCGI_STDIN`) — тело запроса;
  - `6` (`FCGI_STDOUT`) — тело ответа приложения;
  - `7` (`FCGI_STDERR`) — лог ошибок бэкенда.
- **RequestId (2 байта, Big Endian):** идентификатор запроса для мультиплексирования.
- **ContentLength (2 байта):** длина полезной нагрузки (до 65 535 байт).
- **PaddingLength (1 байт):** выравнивание по 8-байтовой границе.

#### 4. Стандарт WSGI (PEP 3333)

WSGI — это синхронный программный контракт в Python:

```python
def application(environ, start_response):
    # environ: словарь переменных CGI + метаданные WSGI
    status = '200 OK'
    response_headers = [
        ('Content-Type', 'text/plain; charset=utf-8'),
        ('Content-Length', '13')
    ]
    start_response(status, response_headers)
    return [b'Hello, World!']
```

Ограничения WSGI:
- 1 рабочий поток или процесс блокируется на время выполнения запроса.
- Медленные клиенты или длительные вычисления полностью утилизируют пул воркеров.
- Отсутствие стандартной обработки WebSockets и серверных событий (SSE).

---

### Архитектура uWSGI: Мастер, Воркеры и режим Emperor

Сервер uWSGI реализует трехуровневую иерархию управления процессами:

```
┌───────────────────────────────────────────────────────────────┐
│                     uWSGI Emperor (Супервизор)               │
│                     (Сканирует /etc/uwsgi/vassals)            │
└───────────────────────────────┬───────────────────────────────┘
                                │ fork() / exec()
        ┌───────────────────────┴───────────────────────┐
        ▼                                               ▼
┌───────────────────────────────┐       ┌───────────────────────────────┐
│   Vassal: App 1 (Master)      │       │   Vassal: App 2 (Master)      │
│   PID: 1010                   │       │   PID: 1020                   │
├───────────────────────────────┤       ├───────────────────────────────┤
│ ├── Worker 1 (req processing) │       │ ├── Worker 1 (req processing) │
│ ├── Worker 2 (req processing) │       │ ├── Worker 2 (req processing) │
│ ├── Spooler (async tasks)     │       │ └── Mules (background jobs)   │
│ └── Shared Cache (LRU shm)    │       │                               │
└───────────────────────────────┘       └───────────────────────────────┘
```

1. **Master Process:**
   - Открывает и слушает сокеты (`socket = ...`).
   - Отслеживает состояние рабочих процессов (`workers`) через обработку сигналов `SIGCHLD`.
   - Контролирует сторожевой таймер **Harakiri**.
   - Перезапускает воркеры при достижении лимитов по памяти (`reload-on-rss`) или числу запросов (`max-requests`).
   - Выполняет бесшовный перезапуск (Graceful Reload) без закрытия сокета.

2. **Workers (Рабочие процессы):**
   - Вызывают системный вызов `accept()` на общем дескрипторе сокета.
   - Исполняют код приложения (WSGI, Rack, PHP).
   - Могут работать в режиме мультипроцессинга (`processes = N`), мультипоточности (`threads = M`) или с корутинами (`gevent`, `asyncio`).

3. **Emperor и Vassals:**
   - Режим централизованного управления десятками сервисов.
   - Любой файл `.ini`, помещенный в каталог вассалов, запускает отдельный независимый инстанс приложения.
   - Команда `touch app.ini` инициирует плавный перезапуск конкретного вассала.
   - Удаление файла конфигурации корректно останавливает инстанс (`SIGQUIT`).

4. **Spooler, Mules и Cache:**
   - **Spooler:** встроенная очередь задач uWSGI. Задачи сохраняются в виде файлов на диске и обрабатываются выделенными процессами-спулерами.
   - **Mules:** фоновые изолированные воркеры, не привязанные к веб-запросам, для постоянных служебных циклов.
   - **Shared Cache:** разделяемая память (`mmap`/`shm`) с блокировками для организации быстрого LRU-кэша между всеми воркерами без обращения к Redis/Memcached.

---

### Межпроцессное взаимодействие: UNIX Domain Sockets vs TCP

Выбор между UNIX-сокетом (`AF_UNIX`) и TCP-сокетом (`AF_INET`, `127.0.0.1`) — фундаментальное решение при проектировании серверного узла:

```
UNIX Domain Socket:
[ Nginx ] ──( write to /run/app.sock )──► [ Linux Kernel Buffer ] ──( read )──► [ uWSGI Worker ]
  (Без сетевого стека, без фрагментации, без TCP handshake, права через файловую систему)

TCP Loopback Socket:
[ Nginx ] ──► [ TCP Stack ] ──► [ IP Stack ] ──► [ lo interface ] ──► [ TCP Stack ] ──► [ uWSGI ]
  (3-way handshake, расчет контрольных сумм, TIME_WAIT, эфемерные порты, TCP slow-start)
```

| Параметр | UNIX Domain Socket | TCP Socket (`127.0.0.1` / IP) |
| :--- | :--- | :--- |
| **Пропускная способность** | В 1.8–2.2 раза выше, чем loopback | Ниже из-за сетевого стека |
| **Задержка (Latency)** | Минимальная ($2\text{--}5\text{ мкс}$) | Выше ($15\text{--}40\text{ мкс}$) |
| **Сетевые накладные расходы** | Отсутствуют (чистое копирование страниц памяти в ядре) | Проверка контрольных сумм, TCP ack, framing |
| **Ограничения ресурсов** | Дескрипторы файлов (`nofile`), размер буфера сокета | Диапазон портов (`ip_local_port_range`), `TIME_WAIT` |
| **Контроль доступа** | Стандартные права Linux (`chmod`, `chown`, группы) | Файрвол (`iptables`/`nftables`), привязка к IP |
| **Масштабируемость** | Только локальный сервер | Возможность разнесения на удаленные хосты |

---

### Буферизация и управление памятью веб-сервера

Когда Nginx или Angie проксирует запрос к uWSGI/FastCGI/SCGI, по умолчанию включается **буферизация ответов**:
1. Веб-сервер максимально быстро вычитывает весь ответ из сокета бэкенда во внутренние буферы (`uwsgi_buffers`, `fastcgi_buffers`).
2. Как только ответ полностью прочитан, воркер uWSGI освобождается для следующего запроса.
3. Веб-сервер самостоятельно отдает данные медленному клиенту через интернет.
4. Если размер ответа превышает память буферов, избыток сбрасывается во временные файлы на диск (`uwsgi_temp_path`).

**Критическая точка отказа (Header Buffer Overflow):**
Заголовки ответа бэкенда (Set-Cookie, JWT, метаданные авторизации) должны полностью помещаться в один первичный буфер (`uwsgi_buffer_size`). Если размер заголовков превышает этот размер, Nginx аварийно разрывает соединение с ошибкой `502 Bad Gateway` (`upstream sent too big header while reading response header from upstream`).

---

## Практические сценарии и конфигурация

### Сценарий 1: Production-конфигурация uWSGI и Systemd Unit

Типовая конфигурация приложения Python/WSGI с защитой от утечек памяти, зависаний и контролем очереди.

Файл `/etc/uwsgi/apps-available/my_app.ini`:
```ini
[uwsgi]
# Базовые параметры окружения
project = my_app
base = /var/www/my_app

chdir = %(base)
home = %(base)/venv
module = wsgi:application

# Модель процессов (Prefork + Threads)
master = true
processes = 4
threads = 2
enable-threads = true

# Защита от утечек памяти и зависаний
max-requests = 5000
max-requests-delta = 500
reload-on-rss = 512
harakiri = 60
harakiri-verbose = true

# Сокет и сетевые параметры
socket = /run/uwsgi/%(project).sock
chmod-socket = 660
chown-socket = www-data:www-data
vacuum = true
die-on-term = true

# Буферы и очереди соединений
buffer-size = 32768
listen = 1024
thunder-lock = true

# Управление и мониторинг
master-fifo = /run/uwsgi/%(project).fifo
stats = /run/uwsgi/%(project)-stats.sock
chmod-stats = 660
chown-stats = www-data:www-data

# Логирование
logto = /var/log/uwsgi/%(project).log
log-x-forwarded-for = true
disable-logging = true
log-5xx = true
log-4xx = true
log-slow = 1000
```

Системный юнит `/etc/systemd/system/uwsgi-app.service`:
```ini
[Unit]
Description=uWSGI instance serving my_app
After=network.target

[Service]
Type=notify
User=www-data
Group=www-data
RuntimeDirectory=uwsgi
LogsDirectory=uwsgi
ExecStart=/usr/local/bin/uwsgi --ini /etc/uwsgi/apps-available/my_app.ini
ExecReload=/bin/sh -c 'echo r > /run/uwsgi/my_app.fifo'
ExecStop=/bin/sh -c 'echo q > /run/uwsgi/my_app.fifo'
Restart=on-failure
KillSignal=SIGQUIT
TimeoutStopSec=30
StandardError=journal
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

Применение и запуск:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now uwsgi-app.service
sudo systemctl status uwsgi-app.service
# → Active: active (running) since ...
```

---

### Сценарий 2: Режим Emperor и Vassals (Мультисервисная топология)

Конфигурация единого демона-супервизора для автоматического управления пулом микросервисов.

Конфигурация Emperor `/etc/uwsgi/emperor.ini`:
```ini
[uwsgi]
emperor = /etc/uwsgi/vassals
emperor-tyrant = false
cap = net_bind_service
master = true
vacuum = true

# Централизованный мониторинг состояния всех вассалов
emperor-stats-server = /run/uwsgi/emperor-stats.sock

# Автоматическое удаление сокетов при крахе вассала
emperor-on-demand-directory = /run/uwsgi/on-demand
```

Каталог вассалов формируется через символические ссылки:
```bash
sudo mkdir -p /etc/uwsgi/vassals
sudo ln -s /etc/uwsgi/apps-available/my_app.ini /etc/uwsgi/vassals/my_app.ini
```

Юнит Emperor `/etc/systemd/system/uwsgi-emperor.service`:
```ini
[Unit]
Description=uWSGI Emperor Service
After=network.target

[Service]
Type=notify
ExecStart=/usr/local/bin/uwsgi --ini /etc/uwsgi/emperor.ini
ExecReload=/bin/kill -HUP $MAINPID
ExecStop=/bin/kill -INT $MAINPID
Restart=always
RuntimeDirectory=uwsgi
KillMode=mixed
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

---

### Сценарий 3: Интеграция Nginx / Angie с uWSGI

Фрагмент конфигурации виртуального хоста Nginx/Angie (`/etc/nginx/sites-available/app.conf`):

```nginx
upstream uwsgi_app_cluster {
    server unix:/run/uwsgi/my_app.sock max_fails=3 fail_timeout=10s;
    # Для поддержания открытых соединений при использовании TCP:
    # server 127.0.0.1:8000 max_fails=3 fail_timeout=10s;
    # keepalive 32;
}

server {
    listen 80;
    server_name app.example.internal;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name app.example.internal;

    ssl_certificate     /etc/ssl/certs/app.example.internal.crt;
    ssl_certificate_key /etc/ssl/private/app.example.internal.key;

    # Статика отдается напрямую веб-сервером в обход бэкенда
    location /static/ {
        alias /var/www/my_app/static/;
        expires 30d;
        add_header Cache-Control "public, no-transform";
        access_log off;
    }

    # Проксирование в uWSGI
    location / {
        include uwsgi_params;
        uwsgi_pass uwsgi_app_cluster;

        # Таймауты согласованные с harakiri uWSGI (60s)
        uwsgi_read_timeout 65s;
        uwsgi_send_timeout 65s;
        uwsgi_connect_timeout 5s;

        # Размеры буферов для предотвращения ошибки "upstream sent too big header"
        uwsgi_buffer_size 32k;
        uwsgi_buffers 8 32k;
        uwsgi_busy_buffers_size 64k;
        uwsgi_temp_file_write_size 64k;

        # Передача метаданных протокола клиенту
        uwsgi_param HTTP_X_FORWARDED_PROTO $scheme;
        uwsgi_param HTTP_X_REAL_IP $remote_addr;
    }
}
```

Проверка конфигурации и перезагрузка:
```bash
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
sudo systemctl reload nginx
```

---

### Сценарий 4: Интеграция с протоколом SCGI

Протокол SCGI востребован в специализированных бэкендах, C-демонах и торрент-клиентах (rTorrent XML-RPC).

Конфигурация Nginx (`/etc/nginx/conf.d/scgi_service.conf`):
```nginx
server {
    listen 127.0.0.1:8080;
    server_name localhost;

    location /RPC2 {
        include scgi_params;
        scgi_pass 127.0.0.1:5000;

        scgi_read_timeout 60s;
        scgi_send_timeout 60s;
        scgi_connect_timeout 5s;

        # Тюнинг буферов SCGI
        scgi_buffer_size 16k;
        scgi_buffers 4 16k;
        scgi_busy_buffers_size 32k;

        # Ограничение доступа к системному RPC
        allow 127.0.0.1;
        deny all;
    }
}
```

Минимальный сервер на Python, реализующий прием SCGI без сторонних фреймворков:
```python
import socket

def handle_scgi(conn):
    data = b""
    while b':' not in data:
        chunk = conn.recv(16)
        if not chunk:
            return
        data += chunk
    
    length_str, rest = data.split(b':', 1)
    header_len = int(length_str)
    
    while len(rest) < header_len + 1:
        rest += conn.recv(header_len + 1 - len(rest))
    
    raw_headers = rest[:header_len]
    items = raw_headers.split(b'\x00')[:-1]
    headers = dict(zip(items[0::2], items[1::2]))
    
    content_length = int(headers.get(b'CONTENT_LENGTH', b'0'))
    body = rest[header_len+1:]
    while len(body) < content_length:
        body += conn.recv(content_length - len(body))
    
    response = (
        b"Status: 200 OK\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"SCGI Request Processed Successfully\n"
    )
    conn.sendall(response)
    conn.close()

if __name__ == '__main__':
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('127.0.0.1', 5000))
    s.listen(128)
    while True:
        client, _ = s.accept()
        handle_scgi(client)
```

---

### Сценарий 5: Zero-Downtime перезапуск через Master FIFO и Zerg Mode

В production-средах перезапуск приложения не должен обрывать текущие пользовательские соединения.

#### Вариант A: Перезагрузка по цепочке через Master FIFO (Chain Reload)

uWSGI поддерживает управление через именованный канал FIFO. Команда `c` (`chain reload`) перезапускает воркеры строго по очереди: следующий воркер стартует и начинает принимать трафик только после того, как предыдущий завершил инициализацию.

```bash
# Проверка наличия FIFO-канала
ls -l /run/uwsgi/my_app.fifo
# → prw-r--r-- 1 www-data www-data 0 Oct 15 10:00 /run/uwsgi/my_app.fifo

# Запуск поэтапного перезапуска воркеров без простоя
echo c > /run/uwsgi/my_app.fifo

# Мониторинг процесса перезагрузки в журнале
tail -f /var/log/uwsgi/my_app.log
# → ... chaining worker 1 (pid: 14022) to worker 2 ...
# → ... worker 1 ready! ...
```

#### Вариант B: Архитектура Zerg Mode (передача сокетов новому инстансу)

Zerg-режим позволяет новому мастер-процессу подключиться к уже открытому дескриптору сокета старого мастера через UNIX domain socket (используя `SCM_RIGHTS`):

1. В конфигурации вассала включается Zerg-сервер:
```ini
[uwsgi]
master = true
socket = /run/uwsgi/app.sock
zerg-server = /run/uwsgi/zerg.sock
```

2. При деплое новой версии кода запускается временный Zerg-клиент:
```bash
/usr/local/bin/uwsgi --zerg /run/uwsgi/zerg.sock --ini /etc/uwsgi/apps-available/my_app_v2.ini
```

3. Новый инстанс мгновенно перехватывает обработку новых входящих запросов из сокета `/run/uwsgi/app.sock`, после чего старый инстанс корректно завершается через `SIGQUIT`.

---

## Эксплуатация, команды и мониторинг

### Инспекция состояния через Stats Socket и `uwsgi-top`

Сервер uWSGI экспортирует полную внутреннюю телеметрию через UNIX-сокет статистики в формате JSON.

Установка и интерактивный просмотр:
```bash
# Установка утилиты мониторинга
pip install uwsgi-top

# Запуск интерактивного дашборда реального времени
uwsgi-top /run/uwsgi/my_app-stats.sock
```

Пример вывода `uwsgi-top`:
```text
uwsgi-2.0.26 - Thu Oct 15 10:20:00 2026 - req: 145020 - lq: 0 - tx: 42.1M
node: web-node-01 - cwd: /var/www/my_app - uid: 33 - gid: 33 - masterpid: 1010
 WID    %    PID  REQ  RPS  EXC  SIG  STATUS  AVG   RSS    VSZ   TX    RUN
   1  24.1  1012 36200 45    0    0   busy    12ms  180M   420M  10M   1
   2  26.0  1013 38100 48    1    0   busy    11ms  185M   425M  11M   1
   3   0.0  1014 34500  0    0    0   idle     0ms  175M   415M   9M   0
   4  25.2  1015 36220 46    0    0   busy    13ms  182M   422M  10M   1
```

Сбор метрик в сыром виде для интеграции со скриптами мониторинга:
```bash
# Запрос JSON-дампа через socat или nc
echo "" | nc -U /run/uwsgi/my_app-stats.sock | jq '{
    version: .version,
    listen_queue: .listen_queue,
    listen_queue_errors: .listen_queue_errors,
    workers: [.workers[] | {id: .id, pid: .pid, status: .status, requests: .requests, rss: .rss}]
}'
```

Ожидаемый ответ:
```json
{
  "version": "2.0.26",
  "listen_queue": 0,
  "listen_queue_errors": 0,
  "workers": [
    {
      "id": 1,
      "pid": 1012,
      "status": "busy",
      "requests": 36200,
      "rss": 188743680
    },
    {
      "id": 2,
      "pid": 1013,
      "status": "idle",
      "requests": 38100,
      "rss": 193986560
    }
  ]
}
```

---

### Управление процессами через Master FIFO и сигналы ОС

Команды управления, передаваемые в `master-fifo`:

| Команда | Синтаксис | Действие |
| :--- | :--- | :--- |
| **`c`** | `echo c > /run/uwsgi/app.fifo` | **Chain reload:** перезапуск воркеров строго по одному. |
| **`r`** | `echo r > /run/uwsgi/app.fifo` | **Graceful reload:** перезапуск всех воркеров с ожиданием завершения текущих запросов. |
| **`q`** | `echo q > /run/uwsgi/app.fifo` | **Graceful stop:** плавный останов всего инстанса. |
| **`+`** | `echo + > /run/uwsgi/app.fifo` | Динамически добавить 1 воркер в пул. |
| **`-`** | `echo - > /run/uwsgi/app.fifo` | Динамически удалить 1 воркер из пула. |
| **`p`** | `echo p > /run/uwsgi/app.fifo` | Пауза/снятие с паузы приема соединений вассалом. |

Управление через сигналы POSIX:
```bash
# Мягкий перезапуск воркеров (Reload)
kill -HUP $(cat /run/uwsgi/my_app.pid)

# Сброс статистики в лог
kill -USR1 $(cat /run/uwsgi/my_app.pid)

# Graceful останов (завершение обработки активных запросов)
kill -QUIT $(cat /run/uwsgi/my_app.pid)

# Жесткий немедленный останов (Brutal stop)
kill -INT $(cat /run/uwsgi/my_app.pid)
```

---

### Диагностика сокетов и очередей backlog

Проверка заполнения очереди `backlog` для выявления узких мест на уровне ядра:

```bash
# Проверка длины очереди входящих соединений UNIX-сокета
ss -xlp 'src = /run/uwsgi/my_app.sock'
```

Ожидаемый вывод:
```text
Netid  State   Recv-Q  Send-Q        Local Address:Port        Peer Address:Port  Process
u_str  LISTEN  0       1024    /run/uwsgi/my_app.sock 234125               * 0    users:(("uwsgi",pid=1010,fd=3))
```

- **Send-Q (1024):** максимально допустимый размер очереди сокета (`listen = 1024` в конфиге uWSGI).
- **Recv-Q (0):** текущее количество ожидающих соединений в очереди. Если значение `Recv-Q` приближается к `Send-Q` или равно ему — приложение не справляется с потоком входящих запросов, а новые соединения отвергаются.

Проверка системных дескрипторов сокета:
```bash
# Проверка процесса, удерживающего сокет
sudo lsof /run/uwsgi/my_app.sock
# → COMMAND  PID     USER   FD   TYPE             DEVICE SIZE/OFF    NODE NAME
# → uwsgi   1010 www-data    3u  unix 0x0000000000000000      0t0 234125 /run/uwsgi/my_app.sock
```

---

### Трассировка воркеров с помощью `strace`

Диагностика зависшего воркера uWSGI:
```bash
# Подключение к рабочему процессу по PID
sudo strace -tt -T -p 1012 -s 256
```

Типичный вывод при блокировке на чтении из базы данных:
```text
10:25:31.104231 recvfrom(7, 0x55e921, 16384, 0, NULL, NULL) = -1 EAGAIN (Resource temporarily unavailable) <0.000015>
10:25:31.104312 epoll_wait(4, [{events=EPOLLIN, data={u32=7, u64=7}}], 1, 5000) = 1 <4.981240>
10:25:36.085612 recvfrom(7, "SELECT * FROM orders WHERE ...", 16384, 0, NULL, NULL) = 512 <0.000045>
```

---

## Устранение неполадок

### Сводная матрица типовых неисправностей

| Симптом | Код ошибки / Лог | Корневая причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- | :--- |
| **Отказано в доступе к сокету** | `502 Bad Gateway`<br>`connect() to unix:... failed (13: Permission denied)` | Права на `.sock` не разрешают чтение/запись пользователю Nginx (`nginx`/`www-data`). | `ls -la /run/uwsgi/my_app.sock` | Задать `chmod-socket = 660`, `chown-socket = www-data:www-data`. |
| **Сокет не найден / Завис** | `502 Bad Gateway`<br>`connect() failed (111: Connection refused)` или `(2: No such file)` | Процесс uWSGI упал или завершился без удаления старого файла сокета. | `systemctl status uwsgi`<br>`ss -xlp` | Включить `vacuum = true` в `uwsgi.ini`, проверить `journalctl -u uwsgi`. |
| **Слишком большой заголовок ответа** | `502 Bad Gateway`<br>`upstream sent too big header while reading response header` | Размер Set-Cookie или JWT превысил `uwsgi_buffer_size` в Nginx или `buffer-size` в uWSGI. | Проверить размер заголовков через `curl -I`. | Увеличить `uwsgi_buffer_size 32k;` в Nginx и `buffer-size = 32768` в `uwsgi.ini`. |
| **Сработал сторожевой таймер** | `504 Gateway Timeout`<br>`*** HARAKIRI ON WORKER X (pid: Y) ***` | Обработка запроса воркером превысила лимит `harakiri = 60`. | Поиск маркеров `HARAKIRI` в логах uWSGI. | Оптимизировать медленные SQL-запросы, вынести тяжелые задачи в фоновый воркер/Celery. |
| **Очередь соединений переполнена** | `502 Bad Gateway` / Spikes Latency<br>`uwsgi_response_write_body_loop() timeout` | `Recv-Q` достигла лимита `listen` / `net.core.somaxconn`. | `ss -xlp 'src = /run/uwsgi/*.sock'` | Увеличить `net.core.somaxconn` до 4096 в `sysctl` и `listen = 4096` в `uwsgi.ini`. |
| **Аварийное завершение процесса (OOM)** | `502 Bad Gateway`<br>`kernel: Out of memory: Killed process (uwsgi)` | Рабочий процесс превысил лимит ОЗУ сервера или cgroup. | `dmesg -T \| grep -i oom` | Настроить `reload-on-rss = 512` и `max-requests = 5000` для утилизации фрагментации памяти. |
| **Взаимная блокировка потоков** | Воркеры перестают отвечать, CPU 0% | Python GIL заблокирован сторонним C-расширением при многопоточности без `enable-threads`. | Проверить стек потоков в GDB/py-spy. | Добавить директиву `enable-threads = true` в конфигурацию uWSGI. |

---

### Детальные сценарии диагностики

#### 1. Диагностика ошибки «upstream sent too big header»

**Симптом:** Пользователи получают `502 Bad Gateway` при попытке авторизации (OAuth2, SSO, большие сессионные Cookie).
В логе `/var/log/nginx/error.log`:
```text
2026/10/15 10:30:12 [error] 14210#14210: *84512 upstream sent too big header while reading response header from upstream, client: 192.0.2.10, server: app.example.internal, request: "POST /auth/callback HTTP/1.1", upstream: "uwsgi://unix:/run/uwsgi/my_app.sock:", host: "app.example.internal"
```

**Причина:** По умолчанию в Nginx размер буфера заголовка ответа upstream (`uwsgi_buffer_size`) равен размеру одной страницы памяти системы ($4\text{ КБ}$ или $8\text{ КБ}$). Если приложение отдает заголовки размером $9\text{ КБ}$, буфер переполняется. Одновременно в `uwsgi` по умолчанию размер пакета ограничен $4\,096$ байтами.

**Решение:**
1. В `/etc/nginx/sites-available/app.conf`:
```nginx
location / {
    include uwsgi_params;
    uwsgi_pass unix:/run/uwsgi/my_app.sock;
    uwsgi_buffer_size 32k;
    uwsgi_buffers 8 32k;
    uwsgi_busy_buffers_size 64k;
}
```
2. В `/etc/uwsgi/apps-available/my_app.ini`:
```ini
[uwsgi]
buffer-size = 32768
```
3. Перезагрузить сервисы:
```bash
sudo nginx -t && sudo systemctl reload nginx
echo r > /run/uwsgi/my_app.fifo
```

---

#### 2. Диагностика срабатывания Harakiri Watchdog

**Симптом:** Клиент получает `504 Gateway Timeout`. В логе `/var/log/uwsgi/my_app.log`:
```text
Thu Oct 15 10:35:00 2026 - *** HARAKIRI ON WORKER 2 (pid: 1013) ***
Thu Oct 15 10:35:00 2026 - HARAKIRI: -- unforgiving hard stack trace for worker 2 (pid: 1013) on signal 11 --
Thu Oct 15 10:35:00 2026 - [uWSGI worker 2] traceback:
  File "/var/www/my_app/views/reports.py", line 84, in generate_pdf
    time.sleep(120)
Thu Oct 15 10:35:01 2026 - DAMN ! worker 2 (pid: 1013) died, scheduling a respawn...
Thu Oct 15 10:35:01 2026 - Respawned uWSGI worker 2 (new pid: 1089)
```

**Решение:**
1. Если операция генерации отчета легитимно долгая — ее необходимо вынести в асинхронную фоновую очередь (Celery, uWSGI Spooler).
2. Если длительность вызвана блокировкой внешнего вызова (БД, стороннее API) — установить таймауты внутри клиента Python (`requests.get(..., timeout=5)`).
3. При необходимости временно поднять порог `harakiri = 120` в `my_app.ini` и согласованный `uwsgi_read_timeout 125s;` в Nginx.

---

#### 3. Переполнение очереди входящих соединений ядра (Listen Queue Overflow)

**Симптом:** При резком росте трафика часть запросов падает с `502 Bad Gateway`, при этом утилизация CPU воркеров составляет менее 70%.

**Диагностика:**
```bash
# Проверка системных счетчиков отброшенных сокетов
netstat -s | grep -i listen
# → 14502 times the listen queue of a socket overflowed
# → 14502 SYNs to LISTEN sockets dropped
```

**Решение:**
1. Увеличить лимит слушающих очередей на уровне ядра Linux:
```bash
sudo sysctl -w net.core.somaxconn=4096
echo "net.core.somaxconn = 4096" | sudo tee -a /etc/sysctl.d/99-network-performance.conf
```
2. Увеличить размер очереди в uWSGI (`my_app.ini`):
```ini
[uwsgi]
listen = 4096
```
3. Перезапустить сервис:
```bash
sudo systemctl restart uwsgi-app.service
```

---

## Лучшие практики

1. **Разделение привилегий и права на сокеты:**
   Никогда не запускайте рабочие процессы приложений от пользователя `root`. Используйте выделенного пользователя приложения (`www-data` или `appuser`). Задавайте права сокета `chmod-socket = 660`, чтобы запись была доступна только веб-серверу и бэкенду, состоящим в одной группе.

2. **Обязательная очистка файловой системы (`vacuum = true`):**
   Всегда указывайте `vacuum = true` в конфигурации uWSGI. Это гарантирует удаление файлов сокетов (`.sock`), pid-файлов и каналов FIFO из файловой системы при штатной остановке сервиса, предотвращая возникновение ошибок `Address already in use` при повторном старте.

3. **Расчет количества воркеров и потоков:**
   - **Для CPU-bound задач (чистый Python, вычисления, сериализация JSON):**
     $$\text{processes} = \text{Количество доступных CPU Cores}$$
     $$\text{threads} = 1\text{--}2$$
     (Из-за Python GIL создание большого числа потоков на CPU-bound нагрузке увеличивает конкуренцию за блокировку).
   - **Для I/O-bound задач (сетевые запросы, обращение к СУБД, дисковые операции):**
     $$\text{processes} = 2 \times \text{CPU Cores}$$
     $$\text{threads} = 4\text{--}8$$
     Обязательно указать `enable-threads = true`.

4. **Защита от фрагментации памяти и утечек:**
   Интерпретатор CPython подвержен фрагментации кучи при длительной работе с разнородными объектами. Используйте комбинацию:
   ```ini
   max-requests = 5000
   max-requests-delta = 500
   reload-on-rss = 512
   ```
   Параметр `max-requests-delta` вводит случайную вариацию порога перезапуска между воркерами, предотвращая одновременный перезапуск всех процессов пула.

5. **Использование `die-on-term = true` под управлением Systemd:**
   По умолчанию uWSGI трактует сигнал `SIGTERM` как команду перезагрузки (Reload), а `SIGQUIT` — как завершение. Systemd при остановке сервиса по умолчанию отправляет `SIGTERM`. Без опции `die-on-term = true` сервис uWSGI вместо остановки будет уходить в бесконечный цикл перезагрузки до истечения `TimeoutStopSec`.

6. **Предотвращение Thundering Herd (`thunder-lock`):**
   При работе нескольких воркеров на общем слушающем сокете поступление входящего соединения может приводить к пробуждению всех спящих процессов ядра. На ядрах Linux 4.5+ uWSGI автоматически использует флаг `EPOLLEXCLUSIVE`. Для старых ядер или гетерогенных окружений явное включение `thunder-lock = true` исключает пики загрузки CPU на пустых соединениях.

---

## Дополнительная информация

- **[Nginx location: примеры интеграции](../Nginx/Core/Location/integration_examples.md)** — практические конфигурации директив `uwsgi_pass`, `fastcgi_pass`, `scgi_pass`, `proxy_pass`.
- **[Angie: FastCGI/PHP-FPM](../Angie/angie-fastcgi-php-fpm.md)** — архитектура и развертывание пулов PHP-FPM в веб-сервере Angie.
- **[PHP-FPM: тюнинг, мониторинг и эксплуатация](../PHP/php-fpm-tuning.md)** — формулы расчета процессов, стратегии `dynamic`/`ondemand` и тюнинг пулов.
- **[PHP-FPM мониторинг](../PHP/php-fpm-monitoring.md)** — сбор метрик через status page и экспорт в Prometheus.
- **[Apache: интеграция Python (mod_wsgi)](../Apache/apache-python-wsgi.md)** — развертывание Python в Apache HTTP Server через `mod_wsgi` и `mod_proxy_uwsgi`.
- **[Upstream Keepalive и Connection Pooling](./web_performance/upstream_keepalive_and_pooling.md)** — организация постоянных upstream-соединений к пулам бэкендов.
- **[Диагностика веб-серверов](./webserver_troubleshooting.md)** — общий алгоритм локализации и устранения аварий веб-серверов.
