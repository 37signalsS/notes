# Nginx: отдача статических файлов

**Актуально для:** Nginx 1.26.x (Stable) / 1.27.x (Mainline)

---

## Определения

**Отдача статики (Static File Serving)** — передача неизменяемых файлов (HTML, CSS, JavaScript, изображений, шрифтов, медиафайлов, архивов) клиенту веб-сервером Nginx напрямую из файловой системы операционной системы без привлечения интерпретаторов и бэкенд-приложений (PHP, Python, Node.js, Go). Для SRE и системных администраторов это базовый режим работы, на котором достигается максимальная пропускная способность сервера (RPS) и минимальная задержка (latency) за счет системных вызовов ядра Linux.

**Директива `root`** — директива модуля `ngx_http_core_module`, устанавливающая базовый каталог файловой системы для поиска запрашиваемых ресурсов. Полный путь к файлу на накопителе формируется путем конкатенации значения `root` и нормализованного `$uri` входящего запроса: `путь = root + $uri`.

**Директива `alias`** — директива модуля `ngx_http_core_module`, подменяющая путь к файлу для конкретного блока `location`. В отличие от `root`, `alias` отбрасывает совпавшую часть URI из префикса `location` и заменяет ее указанным системным путем.

**Документный корень (Document Root)** — базовый системный путь к файлам виртуального хоста, рассчитываемый Nginx в переменной `$document_root`. Задается директивой `root` в контекстах `http`, `server` или `location` и наследуется дочерними блоками конфигурации.

**Off-by-slash** — критическая уязвимость конфигурации при использовании директивы `alias`, возникающая, когда префикс `location` не завершается слэшем, а путь в `alias` завершается (или наоборот). Приводит к несанкционированному чтению соседних файлов и каталогов файловой системы (Directory Traversal).

**Директива `index`** — директива модуля `ngx_http_index_module`, определяющая перечень индексных файлов, которые Nginx последовательно ищет при обращении к каталогу (URI, оканчивающемуся символом `/`). При нахождении файла выполняется внутренний редирект на его имя.

**Директива `autoindex`** — директива модуля `ngx_http_autoindex_module`, включающая автоматическую генерацию листинга файлов и подкаталогов директории при отсутствии индексного файла.

**Директива `try_files`** — директива модуля `ngx_http_core_module`, выполняющая каскадную проверку физического наличия файлов или директорий на диске в заданной последовательности. Если ни один файл не найден, выполняется финальное действие (внутренний редирект, переход в именованный `location` или возврат HTTP-кода ошибки).

**Zero-Copy (Нулевое копирование)** — системный механизм передачи данных из дискового кэша страниц ядра Linux (`page cache`) напрямую в буфер сетевого сокета через системный вызов `sendfile(2)`, полностью исключающий копирование байтов в память пользовательского пространства (userspace) процесса воркера Nginx и снижающий количество переключений контекста CPU.

**TCP Corking (`tcp_nopush`)** — механизм ядра Linux (`TCP_CORK`) и FreeBSD (`TCP_NOPUSH`), заставляющий сетевой стек накапливать заголовки HTTP-ответа и тело передаваемого через `sendfile` файла в единый полноразмерный сетевой кадр (MSS) перед отправкой в сеть.

**TCP No Delay (`tcp_nodelay`)** — управление алгоритмом Нагла (`TCP_NODELAY`), отключающее искусственную задержку отправки малых пакетов при передаче подтверждений (ACK). В Nginx работает согласованно с `tcp_nopush`, форсируя немедленный сброс последнего неполного пакета файла.

**Кэш дескрипторов файлов (`open_file_cache`)** — структура разделяемой памяти рабочего процесса Nginx, сохраняющая файловые дескрипторы открытых файлов, информацию о размере, времени последней модификации (mtime), существующих каталогах и ошибках поиска (`ENOENT`) для исключения повторных блокирующих вызовов `statx(2)` и `openat(2)`.

**Асинхронный ввод-вывод в пулах потоков (`aio threads`)** — механизм выноса блокирующих файловых операций чтения с диска в независимый пул системных потоков ОС (`thread_pool`), предотвращающий остановку неблокирующего цикла событий (Event Loop) рабочего процесса Nginx при промахах мимо кэша страниц ядра.

**Прямой ввод-вывод (`directio`)** — флаг системного вызова `openat(2)` (`O_DIRECT`), отключающий кэширование в оперативной памяти ядра (`page cache`) при чтении или записи файлов на накопитель. Применяется для исключения вымывания системного кэша при раздаче тяжелых файлов (видео, образы дисков, архивы).

**Статическое предварительное сжатие (`gzip_static` / `brotli_static`)** — отдача заранее сжатых архивов (`.gz` или `.br`), подготовленных на этапе сборки дистрибутива или публикации ассетов. Позволяет веб-серверу отдавать сжатые данные через `sendfile()` без затрат вычислительных ресурсов CPU на динамическое сжатие в реальном времени.

**Защищенная отдача файлов (`X-Accel-Redirect` / `internal`)** — архитектурный паттерн разграничения прав, при котором авторизацию и бизнес-логику проверки доступа выполняет бэкенд, после чего отправляет ответ с заголовком `X-Accel-Redirect: /protected/file.ext`. Nginx перехватывает этот ответ и осуществляет высокопроизводительную локальную отдачу из блока с директивой `internal`.

**HTTP Range Requests (Частичные запросы)** — механизм спецификации RFC 9110, позволяющий клиенту запросить один или несколько фрагментов файла с указанием байтовых диапазонов в заголовке `Range: bytes=start-end`. Nginx отвечает статусом `206 Partial Content`, обеспечивая докачку файлов и произвольную перемотку видео в плеерах.

**MIME-типы (Multipurpose Internet Mail Extensions)** — механизм сопоставления расширений файлов с типами медиаданных по стандарту IANA, передаваемый в заголовке `Content-Type`. Корректная конфигурация предотвращает искажение отображения стилей, скриптов и риск исполнения недоверенных файлов браузером (MIME-sniffing атаки).

**Директива `disable_symlinks`** — директива защиты от выхода за границы изолированного веб-каталога путем проверки символических ссылок при открытии файлов.

---

## Архитектура и базовые концепции

### Конвейер обработки статики и `ngx_http_static_handler`

В архитектуре конвейера Nginx отдача статических файлов выполняется на 10-й фазе — **`NGX_HTTP_CONTENT_PHASE`**. Если в выбранном блоке `location` не определены модули генерации динамического контента или проксирования (`proxy_pass`, `fastcgi_pass`, `uwsgi_pass`, `return`), управление автоматически передается встроенному обработчику по умолчанию — **`ngx_http_static_handler`**.

```
[Клиентский запрос: GET /static/app.js]
               │
               ▼
[NGX_HTTP_FIND_CONFIG_PHASE] ──► Выбор location /static/
               │
[NGX_HTTP_ACCESS_PHASE]      ──► Проверка прав allow/deny, auth_basic
               │
[NGX_HTTP_PRECONTENT_PHASE]  ──► Выполнение try_files (если задан)
               │
[NGX_HTTP_CONTENT_PHASE]     ──► ngx_http_static_handler:
                                   ├─ 1. Формирование системного пути ($request_filename)
                                   ├─ 2. Поиск в open_file_cache (или statx/openat)
                                   ├─ 3. Проверка прав доступа к файлу
                                   ├─ 4. Проверка условных заголовков (If-Modified-Since, If-None-Match)
                                   │      └─► При совпадении: возврат 304 Not Modified
                                   ├─ 5. Проверка заголовка Range: bytes=...
                                   │      └─► При наличии: возврат 206 Partial Content
                                   └─ 6. Отдача тела через sendfile(2) / aio threads
```

`ngx_http_static_handler` выполняет полный цикл обслуживания:
1. Вычисляет полный путь к целевому файлу в переменной `$request_filename`.
2. Запрашивает статус дескриптора в `open_file_cache` либо производит системный вызов ядра `statx(2)` (или `stat(2)`).
3. При обнаружении каталога передает запрос модулю `ngx_http_index_module` или `ngx_http_autoindex_module`.
4. Сверяет валидационные заголовки клиента (`If-None-Match` с ETag файла, `If-Modified-Since` с mtime). При отсутствии изменений возвращает `304 Not Modified` без передачи тела.
5. При наличии заголовка `Range` обращается к `ngx_http_range_filter_module` для формирования частичного ответа со статусом `206 Partial Content`.
6. Передает тело файла клиенту через системный вызов `sendfile(2)` или пул потоков `aio threads`.

---

### Формирование путей: сопоставление `root` и `alias`

Понимание математики формирования путей к файлам на диске исключает 90% типичных ошибок конфигурации `404 Not Found`.

```
Формула root:  Путь на диске = [Значение root] + [Полный URI запроса]
Формула alias: Путь на диске = [Значение alias] + [URI запроса МИНУС Префикс location]
```

#### Принцип работы директивы `root`

Директива `root` допускается в контекстах `http`, `server`, `location` и `if in location`. Она сохраняет URI запроса целиком.

```nginx
server {
    server_name example.com;
    root /var/www/site;

    # Запрос: GET /images/logo.png
    # Путь:   /var/www/site + /images/logo.png = /var/www/site/images/logo.png
    location /images/ {
        # Наследует root /var/www/site
    }

    # Запрос: GET /docs/manual.pdf
    # Путь:   /srv/storage + /docs/manual.pdf = /srv/storage/docs/manual.pdf
    location /docs/ {
        root /srv/storage;
    }
}
```

#### Принцип работы директивы `alias`

Директива `alias` разрешена **исключительно внутри контекста `location`**. Она подменяет префикс совпадения на указанный каталог файловой системы.

```nginx
server {
    server_name example.com;
    root /var/www/site;

    # Запрос: GET /static-data/archive.tar.gz
    # Префикс location "/static-data/" отбрасывается.
    # Остаток URI: "archive.tar.gz"
    # Путь:   /mnt/storage/files/ + archive.tar.gz = /mnt/storage/files/archive.tar.gz
    location /static-data/ {
        alias /mnt/storage/files/;
    }
}
```

#### Директива `alias` с регулярными выражениями

Если директива `alias` применяется внутри блока `location`, заданного регулярным выражением (`~` или `~*`), Nginx **не может** автоматически вычислить вычитаемую часть URI. В такой конфигурации обязательно использовать именованные захваты (captures):

```nginx
# КОРРЕКТНО: использование именованного захвата (?<path>.*)
location ~* ^/download/(?<relpath>.+)$ {
    alias /var/data/storage/$relpath;
}

# ОШИБОЧНО: alias без захватов внутри regex-локейшена
# Приведет к непредсказуемой ошибке internal server error (500) или 404
location ~* ^/download/.*$ {
    alias /var/data/storage/; # ОШИБКА!
}
```

#### Уязвимость Off-by-slash в директиве `alias`

Классический дефект безопасности возникает при рассогласовании замыкающих слэшей:

```nginx
# УЯЗВИМАЯ КОНФИГУРАЦИЯ:
location /static {
    alias /var/www/app/static/;
}
```

**Механизм атаки:**
1. Префикс `location` задан как `/static` (без слэша).
2. Злоумышленник отправляет запрос: `GET /static../config/database.yml`.
3. Nginx отсекает префикс `/static`. Остаток пути: `../config/database.yml`.
4. Nginx соединяет путь `alias` и остаток: `/var/www/app/static/` + `../config/database.yml`.
5. Итоговый путь: `/var/www/app/config/database.yml`. Сервер отдает приватный конфигурационный файл за пределами публичной статики!

**Правило предотвращения:** Если `location` заканчивается символом слэша `/`, значение `alias` обязано заканчиваться слэшем `/`. Если префикс без слэша — используйте строгую директиву `root` либо добавьте слэш в оба параметра:

```nginx
# БЕЗОПАСНАЯ КОНФИГУРАЦИЯ:
location /static/ {
    alias /var/www/app/static/;
}
```

#### Сравнительная таблица `root` и `alias`

| Параметр / Поведение | Директива `root` | Директива `alias` |
| :--- | :--- | :--- |
| **Формирование пути** | Добавляет `$uri` целиком к базовому каталогу | Заменяет совпавший префикс `location` на путь |
| **Допустимые контексты** | `http`, `server`, `location`, `if in location` | Только `location` |
| **Наследование** | Наследуется дочерними блоками `server` и `location` | Не наследуется, действует локально |
| **Регулярные выражения** | Работает стандартно без специальных захватов | Требует явных именованных захватов (`?<name>`) |
| **Риск Off-by-slash** | Отсутствует (добавление полного URI безопасно) | Высокий при отсутствии замыкающего слэша |
| **Совместимость с `try_files`** | Полная, стабильная во всех версиях | Требует тщательной проверки пути во избежание сбоев |

---

### Индексные файлы и генерация листинга (`index` и `autoindex`)

Когда URI входящего запроса указывает на каталог (завершается символом слэша `/`), Nginx инициирует алгоритм поиска индексного файла модуля `ngx_http_index_module`.

```nginx
location / {
    root /var/www/html;
    index index.html index.htm;
}
```

**Алгоритм работы директивы `index`:**
1. Nginx последовательно проверяет файлы из списка в каталоге на диске (`/var/www/html/index.html`, затем `/var/www/html/index.htm`).
2. При обнаружении существующего файла Nginx выполняет **внутренний редирект** на URI файла (например, `/index.html`).
3. Запрос повторно проходит конвейер фаз с новым URI для поиска соответствующего `location`.
4. Если ни один индексный файл не найден:
   - При `autoindex off;` (по умолчанию) Nginx прерывает обработку со статусом **`403 Forbidden`**.
   - При `autoindex on;` Nginx генерирует динамический листинг содержимого каталога.

```nginx
location /repos/ {
    root /srv/mirrors;
    autoindex on;
    autoindex_exact_size off;  # Отображение размеров в КБ/МБ/ГБ вместо байтов
    autoindex_format html;     # Форматы: html, xml, json, jsonp
    autoindex_localtime on;    # Локальное время сервера вместо UTC
}
```

> [!WARNING]
> Директива `autoindex on;` в публичном доступе раскрывает структуру файловой системы, имена резервных копий и временных файлов. Она допускается исключительно во внутренних сетях, репозиториях артефактов и зеркалах загрузок.

---

### Каскадная проверка ресурсов: директива `try_files`

Директива `try_files` последовательно проверяет существование указанных элементов относительно текущих `root` или `alias`. Проверка осуществляется системным вызовом без генерации сетевых перенаправлений.

**Синтаксис:**
```nginx
try_files file ... uri;
try_files file ... =code;
```

**Элементы проверки:**
- `$uri` — проверка наличия конкретного файла.
- `$uri/` — проверка наличия каталога с проверкой директивы `index`.
- Именованный `location` (`@fallback`) — передача запроса в специальный блок без повторного сопоставления URI.
- Финальный URI — запуск внутреннего редиректа на указанный адрес.
- Финальный HTTP-статус (`=404`, `=503`) — немедленный возврат ответа с заданным кодом.

```nginx
# Архитектурный паттерн для SPA (React, Vue, Angular):
location / {
    root /var/www/frontend/dist;
    try_files $uri $uri/ /index.html;
}
```

В данном сценарии Nginx сначала ищет физический файл ассета (JS, CSS, PNG). Если путь не существует, проверяет директорию. Если ничего не найдено, выполняется внутренний редирект на `/index.html`, где роутинг перехватывается клиентским приложением.

---

### Системный ввод-вывод ядра Linux: Zero-Copy, Thread Pools и кэширование

Для системных администраторов и инженеров эксплуатации (SRE) предельная производительность отдачи статики заключается в правильном конфигурировании подсистемы ввода-вывода (I/O).

#### 1. Zero-Copy через системный вызов `sendfile(2)`

В классической схеме чтения/записи (`read`/`write`) данные с диска копируются в буфер пространства ядра (`page cache`), затем в буфер процесса Nginx в пространстве пользователя (`userspace`), а затем обратно в буфер сокета ядра (`socket buffer`). Это требует четырех переключений контекста CPU и двойного копирования байтов в ОЗУ.

При включенной директиве **`sendfile on;`** Nginx инициирует системный вызов ядра `sendfile(out_fd, in_fd, offset, count)`. Данные передаются напрямую из кэша страниц ядра в сетевой контроллер через дескрипторы сокета (DMA — Direct Memory Access). Копирование в пространство пользователя полностью устраняется.

```
Классический I/O:
Диск ──► Page Cache (Ядро) ──► Буфер Nginx (Userspace) ──► Сокет (Ядро) ──► Сеть
        [Контекст ядра]       [Контекст процесса]         [Контекст ядра]

Zero-Copy (sendfile):
Диск ──► Page Cache (Ядро) ──────────────────────────────► Сокет (Ядро) ──► Сеть
        [Контекст ядра (DMA)]
```

#### 2. Тандем `sendfile`, `tcp_nopush` и `tcp_nodelay`

- **`tcp_nopush on;`** (активен только вместе с `sendfile on;`): активирует опцию сокета `TCP_CORK` в Linux. Nginx удерживает пакеты в сетевом стеке, упаковывая заголовки HTTP и начальные блоки данных файла до достижения максимального размера сегмента (MSS = MTU - 40 байт заголовков TCP/IP). Это минимизирует накладные расходы на сетевые заголовки.
- **`tcp_nodelay on;`**: отключает алгоритм Нагла для поддержания минимального latency. При завершении передачи файла Nginx снимает `TCP_CORK`, и опция `TCP_NODELAY` обеспечивает мгновенную отправку завершающего неполного сетевого кадра без ожидания таймаута (200 мс).

#### 3. Асинхронный ввод-вывод и пулы потоков (`aio threads`)

Если запрошенный файл отсутствует в Page Cache (холодные данные на медленном диске), вызов `sendfile(2)` блокирует поток рабочего процесса Nginx до завершения считывания данных с диска. Поскольку воркер обрабатывает тысячи параллельных соединений в одном цикле событий (Event Loop), блокировка I/O приводит к резкому росту задержек (Latency Spikes) для всех клиентов.

Решение: компиляция Nginx с поддержкой потоков (`--with-threads`) и объявление пулов потоков:

```nginx
# В контексте main:
thread_pool io_pool threads=32 max_queue=65536;

http {
    # В контексте http, server или location:
    sendfile on;
    aio threads=io_pool;
    sendfile_max_chunk 512k;
}
```

При обращении к файлу Nginx проверяет наличие страниц в памяти. Если требуется дисковое чтение, задача вычитывания делегируется потоку из `thread_pool`, а воркер продолжает обрабатывать другие сетевые события.

#### 4. Прямой ввод-вывод (`directio`) и предотвращение вымывания кэша

Раздача файлов размером сотни мегабайт или гигабайт (видеоархивы, образы дисков) через стандартный `sendfile` приводит к вытеснению из `page cache` часто запрашиваемых мелких файлов (CSS, JS, иконки).

Директива **`directio`** принудительно открывает файлы с флагом `O_DIRECT`, минуя системный кэш страниц памяти:

```nginx
location /videos/ {
    root /var/storage;
    sendfile on;
    sendfile_max_chunk 512k;
    aio threads=io_pool;
    directio 8m; # Файлы от 8 МБ и выше читаются в обход page cache
}
```

Файлы меньше 8 МБ будут отдаваться с максимальной скоростью через `sendfile` из оперативной памяти, а тяжелые файлы пойдут через `directio` потоками `aio`, не засоряя оперативную память сервера.

#### 5. Кэширование файловых дескрипторов (`open_file_cache`)

При отдаче сотен тысяч мелких статических файлов в секунду до 30% времени CPU тратится на системные вызовы ядра `statx(2)`, `openat(2)` и `close(2)`.

Директива **`open_file_cache`** кэширует в оперативной памяти воркера:
- Открытые файловые дескрипторы.
- Информацию о размере файла и времени модификации (mtime).
- Существование целевых директорий.
- Негативные результаты поиска (ошибки `ENOENT` / `EACCES`).

```nginx
http {
    open_file_cache          max=20000 inactive=60s;
    open_file_cache_valid    30s;
    open_file_cache_min_uses 2;
    open_file_cache_errors   on;
}
```

- `max=20000` — максимальное количество элементов кэша на воркер. При переполнении устаревшие элементы вытесняются по алгоритму LRU.
- `inactive=60s` — время, после которого неиспользуемый файл удаляется из памяти.
- `open_file_cache_valid 30s` — интервал повторной валидации файла системным вызовом `statx` для обнаружения изменений на диске.
- `open_file_cache_min_uses 2` — файл попадает в кэш только после двух обращений за период `inactive`.
- `open_file_cache_errors on` — кэширует факты отсутствия файлов, защищая файловую подсистему от DoS-атак ботов, перебирающих несуществующие пути.

---

### Метаданные, MIME-типы и согласование контента

Веб-сервер обязан передавать корректный заголовок `Content-Type` на основе расширения запрашиваемого файла. За это отвечает модуль `ngx_http_core_module`.

```nginx
http {
    include       mime.types;
    default_type  application/octet-stream;
    charset       utf-8;
    charset_types text/css text/plain text/vnd.wap.wml application/javascript application/json application/rss+xml;
}
```

- **`include mime.types;`** — подключает стандартный файл сопоставлений (например, `.css` → `text/css`, `.js` → `application/javascript`, `.woff2` → `font/woff2`).
- **`default_type application/octet-stream;`** — резервный MIME-тип. Заставляет браузер скачивать неизвестный файл как бинарный поток, исключая выполнение потенциально опасного содержимого в контексте страницы.
- **`charset utf-8;`** — добавляет параметр кодировки `; charset=utf-8` в заголовок ответа для типов, перечисленных в `charset_types`.

#### Протокол частичных ответов (Byte-Range Requests)

Nginx из коробки поддерживает RFC 9110 для побайтовой отдачи ресурсов. При запросе файла клиентом Nginx возвращает заголовок `Accept-Ranges: bytes`.

Если клиент отправляет запрос с заголовком `Range: bytes=1048576-2097151`, Nginx:
1. Проверяет корректность диапазона.
2. Возвращает код **`206 Partial Content`**.
3. Устанавливает заголовок `Content-Range: bytes 1048576-2097151/52428800`.
4. Передает только запрошенный мегабайт данных.

Для защиты от атак типа «Range Amplification DoS» (когда злоумышленник запрашивает сотни фрагментов в одном заголовке, перегружая CPU и память ядра), используется директива:
```nginx
max_ranges 1; # Ограничивает число диапазонов в одном запросе
```

---

## Практические сценарии

### Сценарий 1: Высоконагруженный продакшен-сервер статического контента

Комплексная конфигурация для раздачи ассетов (CSS, JS, SVG, WebP, WOFF2) с использованием immutable-кэширования, Zero-Copy и заголовков безопасности.

```nginx
# /etc/nginx/conf.d/static_site.conf

server {
    listen 80;
    listen [::]:80;
    server_name static.example.local;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl fastopen=256;
    listen [::]:443 ssl fastopen=256;
    server_name static.example.local;

    ssl_certificate     /etc/ssl/certs/example_local.crt;
    ssl_certificate_key /etc/ssl/private/example_local.key;
    ssl_protocols       TLSv1.2 TLSv1.3;

    root /var/www/static_site/public;
    index index.html;

    # Защита от MIME-sniffing и Clickjacking на статических ресурсах
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;

    # Базовая обработка HTML-страниц (краткий кэш с обязательной валидацией)
    location / {
        try_files $uri $uri/ /index.html =404;
        add_header Cache-Control "no-cache, must-revalidate" always;
    }

    # Статические версионированные ассеты с хэшами в именах (Cache-Busting)
    # Использование ^~ отключает проверку регулярных выражений при совпадении префикса
    location ^~ /assets/ {
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        access_log off;
        log_not_found off;
    }

    # Шрифты: разрешение CORS для локальных веб-приложений
    location ~* \.(woff|woff2|ttf|eot)$ {
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header Access-Control-Allow-Origin "*" always;
        access_log off;
        log_not_found off;
    }

    # Запрет доступа к служебным файлам и репозиториям
    location ~ /\.(?!well-known) {
        deny all;
        access_log off;
        log_not_found off;
    }
}
```

---

### Сценарий 2: Single Page Application (SPA — React, Vue, Svelte)

Специфика SPA заключается в разделении обработки: статические файлы ассетов кэшируются на длительный срок, а главный файл `index.html` никогда не кэшируется браузером жестко, иначе клиенты не получат свежие бандлы после деплоя.

```nginx
# /etc/nginx/conf.d/spa_app.conf

server {
    listen 80;
    server_name app.example.local;
    root /var/www/spa_app/dist;

    # Отключение буферизации логов для оперативной диагностики
    access_log /var/log/nginx/spa_access.log combined;
    error_log  /var/log/nginx/spa_error.log warn;

    # Корневой локейшен: отдаем файл, директорию или сбрасываем роутинг на SPA entrypoint
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Файл index.html: строгий запрет на агрессивное клиентское кэширование
    location = /index.html {
        expires -1;
        add_header Cache-Control "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0" always;
        add_header Pragma "no-cache" always;
    }

    # Статика сборщика (Vite, Webpack, Rollup) с уникальными хэшами
    location ~* \.(?:css|js|mjs|wasm)$ {
        try_files $uri =404;
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        access_log off;
    }

    # Изображения и медиафайлы
    location ~* \.(?:ico|png|jpg|jpeg|gif|svg|webp|avif)$ {
        try_files $uri =404;
        expires 30d;
        add_header Cache-Control "public, max-age=2592000" always;
        access_log off;
    }
}
```

---

### Сценарий 3: Предварительное статическое сжатие (`gzip_static` и `brotli_static`)

Если файлы `.css.gz` / `.js.gz` и `.css.br` / `.js.br` генерируются на этапе CI/CD сборки, Nginx считывает готовые байты с диска и отправляет их напрямую в сеть через `sendfile()`.

```nginx
# /etc/nginx/conf.d/precompressed.conf

server {
    listen 80;
    server_name cdn.example.local;
    root /var/www/cdn/data;

    location / {
        # Включение отдачи готовых .gz файлов
        gzip_static on;

        # Включение отдачи готовых .br файлов (при сборке с ngx_brotli)
        # brotli_static on;

        # Информирование промежуточных прокси о вариативности сжатия
        gzip_vary on;

        # Если готового сжатого файла нет на диске, подключается динамическое сжатие:
        gzip on;
        gzip_types text/plain text/css application/javascript application/json image/svg+xml;
        gzip_comp_level 5;
        gzip_min_length 1024;

        try_files $uri =404;
    }
}
```

---

### Сценарий 4: Публичный или внутренний репозиторий файлов (`autoindex`)

Сценарий настройки внутреннего зеркала пакетов, дистрибутивов или бэкапов с кастомным оформлением и защитой ресурсов.

```nginx
# /etc/nginx/conf.d/repo_mirror.conf

server {
    listen 80;
    server_name mirror.internal.local;
    root /srv/repo;

    location /packages/ {
        # Активация генерации листинга
        autoindex on;
        autoindex_exact_size off; # Показ размера: "14M", "2.1G" вместо байтов
        autoindex_localtime on;   # Время файлов в локальной таймзоне сервера
        autoindex_format html;    # Допустимо: html, xml, json, jsonp

        # Ограничение пропускной способности для защиты канала сервера
        limit_rate_after 10m;     # Первые 10 МБ передаются на максимальной скорости
        limit_rate 2m;            # Далее скорость ограничивается 2 МБ/с на поток

        # Ограничение количества соединений с одного IP-адреса
        limit_conn addr_zone 5;

        # Запрет переопределения корневой директории через симлинки
        disable_symlinks on from=$document_root;
    }
}
```

---

### Сценарий 5: Раздача тяжелых файлов и потокового видео

Оптимизация параметров ядра, `directio` и пулов потоков для передачи файлов размером более 100 МБ без деградации кэша ОС.

```nginx
# В контексте main (/etc/nginx/nginx.conf):
# thread_pool media_pool threads=16 max_queue=8192;

# В контексте server (/etc/nginx/conf.d/media.conf):
server {
    listen 80;
    server_name media.example.local;
    root /mnt/storage/media;

    location /video/ {
        # Использование пула потоков для чтения с диска
        aio threads=media_pool;

        # Файлы от 4 МБ читаются через O_DIRECT в обход Page Cache
        directio 4m;

        # Ограничение чанка передачи sendfile для fair-play между воркерами
        sendfile on;
        sendfile_max_chunk 512k;

        # Ограничение числа диапазонов для предотвращения Range DoS
        max_ranges 1;

        # Кэширование информации о структуре дескрипторов
        open_file_cache max=5000 inactive=120s;
        open_file_cache_valid 60s;

        # Разрешение перемотки в HTML5 video плеерах
        add_header Accept-Ranges bytes;
    }
}
```

---

### Сценарий 6: Защищенная отдача файлов через `X-Accel-Redirect`

Бэкенд-сервис выполняет проверку прав пользователя, сессии или токена в базе данных, после чего делегирует отдачу тяжелого файла Nginx.

```nginx
# /etc/nginx/conf.d/secure_downloads.conf

server {
    listen 80;
    server_name files.example.local;

    # Точка входа для авторизации (например, FastAPI / Node.js / Go)
    location /download/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Защищенный каталог хранения файлов
    # Доступен ИСКЛЮЧИТЕЛЬНО для внутренних перенаправлений Nginx
    location /protected_files/ {
        internal;
        alias /var/data/private_storage/;

        # Защита от переопределения путей
        disable_symlinks on;

        # Принудительное скачивание в браузере с сохранением оригинального имени
        # (имя передается бэкендом в заголовке Content-Disposition)
        default_type application/octet-stream;
    }
}
```

**Пример ответа бэкенда (Python/FastAPI):**
```python
from fastapi import FastAPI, Response

app = FastAPI()


@app.get("/download/{file_id}")
def download_file(file_id: str):
  # 1. Проверка прав пользователя в БД ...
  # 2. Возврат заголовка для Nginx:
  response = Response()
  response.headers["X-Accel-Redirect"] = f"/protected_files/{file_id}.pdf"
  response.headers["Content-Disposition"] = (
      f'attachment; filename="report_{file_id}.pdf"'
  )
  response.headers["Content-Type"] = "application/pdf"
  return response
```

---

### Сценарий 7: Разделение статики по накопителям (NVMe SSD и HDD/NFS)

Организация многоуровневого хранения (Tiered Storage) на одном сервере.

```nginx
# /etc/nginx/conf.d/storage_tiers.conf

server {
    listen 80;
    server_name portal.example.local;

    # Базовый корень веб-интерфейса на скоростном NVMe SSD
    root /opt/web/frontend;
    index index.html;

    # Горячие системные стили и скрипты (быстрый NVMe)
    location ^~ /ui-assets/ {
        alias /opt/web/frontend/assets/;
        expires 30d;
        open_file_cache max=10000 inactive=60s;
    }

    # Холодный файловый архив на массиве HDD (RAID/NFS)
    location ^~ /archives/ {
        alias /mnt/hdd_storage/archive_files/;
        sendfile on;
        sendfile_max_chunk 1m;
        aio threads=default;
        directio 16m;
    }
}
```

---

### Сценарий 8: Статическая страница обслуживания (Maintenance Mode)

Организация плавного вывода сервиса на плановые технические работы с отдачей статической HTML-страницы и возвратом корректного статуса `503 Service Unavailable` для поисковых систем.

```nginx
# /etc/nginx/conf.d/maintenance.conf

server {
    listen 80;
    server_name service.example.local;
    root /var/www/service/public;

    # Проверка наличия триггер-файла обслуживания
    if (-f /var/www/service/maintenance.enable) {
        return 503;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }

    # Обработка ошибки 503 и перенаправление на изолированную статику
    error_page 503 @maintenance;

    location @maintenance {
        root /var/www/service/errors;
        rewrite ^(.*)$ /maintenance.html break;
        internal;
        add_header Retry-After 3600 always;
    }
}
```

---

## Операции и команды

### Управление конфигурацией и процессами Nginx

```bash
# Валидация синтаксиса файлов конфигурации
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Просмотр полной собранной конфигурации со всеми include
nginx -T | grep -E "(root|alias|sendfile|open_file_cache)"
# → root /var/www/static_site/public;
# → sendfile on;

# Безопасная перезагрузка конфигурации без разрыва клиентских соединений (graceful reload)
nginx -s reload
# → (код возврата 0, процессы обновлены)

# Проверка статуса службы в systemd
systemctl status nginx --no-pager
# → Active: active (running) since Thu 2026-10-15 10:00:00 UTC; 1 day ago
```

---

### Управление правами доступа и файловой системой (Sysadmin)

Рабочие процессы Nginx (воркеры) запускаются от непривилегированного пользователя (обычно `www-data` в Debian/Ubuntu или `nginx` в RHEL/Rocky Linux). Они должны иметь права чтения (`r`) для файлов и права исполнения (`x`) для всех родительских каталогов пути.

```bash
# Определение пользователя, под которым работают воркеры Nginx
ps -ef | grep "nginx: worker process" | awk '{print $1}' | head -n 1
# → www-data

# Назначение владельца для дерева статических файлов
chown -R www-data:www-data /var/www/static_site

# Установка безопасных стандартных прав:
# Каталоги: 755 (rwxr-xr-x), Файлы: 644 (rw-r--r--)
find /var/www/static_site -type d -exec chmod 755 {} +
find /var/www/static_site -type f -exec chmod 644 {} +

# Запрет на запись для процесса веб-сервера (Read-Only Hardening для статики):
chmod -R u-w /var/www/static_site/public

# Проверка прав доступа по всей цепочке каталогов до файла (диагностика 403)
namei -l /var/www/static_site/public/assets/app.js
# → f: /var/www/static_site/public/assets/app.js
# → drwxr-xr-x root     root     /
# → drwxr-xr-x root     root     var
# → drwxr-xr-x root     root     www
# → drwxr-xr-x www-data www-data static_site
# → drwxr-xr-x www-data www-data public
# → drwxr-xr-x www-data www-data assets
# → -rw-r--r-- www-data www-data app.js

# Настройка списков контроля доступа POSIX ACL (для деплой-пользователя deployer)
setfacl -R -m u:deployer:rwx /var/www/static_site
setfacl -R -d -m u:deployer:rwx /var/www/static_site
getfacl /var/www/static_site/public
# → # file: var/www/static_site/public
# → # owner: www-data
# → # group: www-data
# → user::rwx
# → user:deployer:rwx
# → group::r-x
```

---

### Мандатный контроль доступа: SELinux и AppArmor

На серверах под управлением RHEL, Rocky Linux, AlmaLinux или Debian/Ubuntu со строгими профилями безопасности системные права POSIX недостаточны.

```bash
# 1. SELinux: Проверка текущего контекста безопасности файлов
ls -dZ /var/www/static_site/public
# → unconfined_u:object_r:default_t:s0 /var/www/static_site/public

# Внесение постоянной политики для веб-контента в базу данных SELinux
semanage fcontext -a -t httpd_sys_content_t "/var/www/static_site(/.*)?"

# Применение контекста ко всей иерархии каталогов
restorecon -Rv /var/www/static_site
# → Relabeled /var/www/static_site/public from default_t to httpd_sys_content_t

# Проверка логов блокировок SELinux (AVC denial)
ausearch -m avc -ts recent | grep nginx
# → (пусто при отсутствии блокировок)

# 2. AppArmor (Ubuntu/Debian): Проверка профиля службы Nginx
aa-status | grep nginx
# → /usr/sbin/nginx (enforce)
```

---

### Тестирование и валидация через `curl`

```bash
# 1. Проверка заголовков ответа и MIME-типа
curl -I -s https://static.example.local/assets/app.js
# → HTTP/1.1 200 OK
# → Server: nginx
# → Content-Type: application/javascript; charset=utf-8
# → Content-Length: 48210
# → Last-Modified: Wed, 14 Oct 2026 12:00:00 GMT
# → ETag: "68ee1c00-bc52"
# → Cache-Control: public, max-age=31536000, immutable
# → Accept-Ranges: bytes

# 2. Проверка валидации кэша (Conditional Request -> 304 Not Modified)
curl -I -H 'If-None-Match: "68ee1c00-bc52"' https://static.example.local/assets/app.js
# → HTTP/1.1 304 Not Modified
# → ETag: "68ee1c00-bc52"
# → Cache-Control: public, max-age=31536000, immutable

# 3. Проверка отдачи предварительно сжатого файла (gzip_static)
curl -I -H "Accept-Encoding: gzip" https://static.example.local/assets/app.js
# → HTTP/1.1 200 OK
# → Content-Type: application/javascript
# → Content-Encoding: gzip
# → Vary: Accept-Encoding

# 4. Проверка побайтового диапазона (Range Request -> 206 Partial Content)
curl -I -r 0-1023 https://static.example.local/video/sample.mp4
# → HTTP/1.1 206 Partial Content
# → Content-Range: bytes 0-1023/104857600
# → Content-Length: 1024

# 5. Проверка блокировки защищенного внутреннего каталога извне
curl -I https://files.example.local/protected_files/document.pdf
# → HTTP/1.1 404 Not Found
```

---

### Трассировка системных вызовов и SRE-диагностика

Инструменты для анализа того, как рабочий процесс Nginx взаимодействует с ядром при отдаче файлов.

```bash
# Получение PID рабочего процесса Nginx
WORKER_PID=$(pgrep -f "nginx: worker process" | head -n 1)

# Трассировка вызовов открытия файлов и Zero-Copy
strace -p $WORKER_PID -e trace=openat,statx,sendfile64,close
# → openat(AT_FDCWD, "/var/www/static_site/public/assets/app.js", O_RDONLY|O_NONBLOCK) = 12
# → statx(12, "", AT_EMPTY_PATH, STATX_BASIC_STATS, {stx_size=48210, ...}) = 0
# → sendfile64(15, 12, [0], 48210) = 48210
# → close(12) = 0

# Просмотр открытых файловых дескрипторов воркера
ls -l /proc/$WORKER_PID/fd
# → lr-x------ 1 www-data www-data 64 Oct 16 12:00 12 -> /var/www/static_site/public/assets/app.js

# Проверка счетчика активных дескрипторов процесса
ls /proc/$WORKER_PID/fd | wc -l
# → 142

# Мониторинг дисковой утилизации и задержек ввода-вывода (IO latency)
iostat -xz 1 3
# → Device  r/s     w/s     rkB/s     wkB/s   await  %util
# → sda     120.00  10.00   6144.00   256.00  1.12   14.20

# Проверка использования оперативной памяти под кэш страниц ОС (Page Cache)
free -m
# →               total        used        free      shared  buff/cache   available
# → Mem:          32048        4120        2150         410       25778       27100
```

---

## Диагностика и устранение неполадок

### Таблица типичных неисправностей

| Симптом | Причина ошибки | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **`403 Forbidden`** на статический файл | Отсутствуют права на чтение файла (`r`) или права исполнения (`x`) на родительские каталоги | Проверить права утилитой `namei -l /path/to/file` | Установить права: каталоги `755`, файлы `644`. Владелец `www-data` |
| **`403 Forbidden`** при запросе каталога (`/`) | Запрошен каталог, индексный файл (`index.html`) отсутствует, а `autoindex off;` | Лог ошибки: `directory index of "/path/" is forbidden` | Создать `index.html` или явно включить `autoindex on;` для каталога |
| **`403 Forbidden`** при правильных POSIX-правах | Блокировка подсистемой SELinux или `disable_symlinks` | `ausearch -m avc -ts recent` или лог Nginx: `symbolic link not allowed` | Выполнить `restorecon -Rv /dir` или настроить `disable_symlinks off;` |
| **`404 Not Found`** при физическом наличии файла | 1. Неправильный выбор `root` vs `alias`.<br>2. Ошибка Off-by-slash.<br>3. Регистр букв (case-sensitive) | Вывести `$request_filename` через отладочный заголовок в `location` | Исправить слэши в `alias` либо сопоставить структуру каталогов с `root` |
| **`500 Internal Server Error`** при работе `try_files` | Цикл внутренних перенаправлений (превышение константы `NGX_HTTP_MAX_URI_CHANGES = 10`) | Лог ошибки: `rewrite or internal redirection cycle while internally redirecting to "/index.html"` | Проверить, что целевой файл fallback существует; не направлять fallback в тот же `try_files` |
| **Файл скачивается как бинарный вместо отображения** | Отсутствует сопоставление расширения в `mime.types` или отсутствует директива `include` | Заголовок `Content-Type: application/octet-stream` в ответе `curl -I` | Добавить `include mime.types;` в блок `http` и проверить расширение файла |
| **Старый контент отдается после деплоя** | 1. Агрессивное клиентское кэширование без Cache-Busting.<br>2. Активен `open_file_cache` | Проверить заголовок `ETag` и параметры `open_file_cache_valid` | Внедрить хэширование имен файлов в CI/CD; уменьшить `open_file_cache_valid` до `30s` |
| **Всплески задержек (Latency Spikes)** | Блокировка цикла событий воркера при чтении холодного файла с медленного диска | Высокий `iowait` CPU в `top`; зависания сетевых запросов | Настроить пул потоков `thread_pool default threads=32; aio threads;` |

---

### Диагностические процедуры и сценарии отладки

#### 1. Трассировка формирования системного пути `$request_filename`

Когда Nginx возвращает ошибку `404 Not Found`, самый быстрый способ локализовать проблему — увидеть, какой именно файл на накопителе пытается открыть сервер.

Временно добавьте тестовый заголовок в подозрительный блок `location`:

```nginx
location /static/ {
    alias /var/www/data/assets/;
    add_header X-Debug-Filename "$request_filename" always;
    add_header X-Debug-Root "$document_root" always;
    add_header X-Debug-URI "$uri" always;
}
```

Выполните тестовый запрос:
```bash
curl -I https://example.local/static/style.css
# → HTTP/1.1 404 Not Found
# → X-Debug-Filename: /var/www/data/assets/style.css
# → X-Debug-Root: /var/www/data/assets/
# → X-Debug-URI: /static/style.css
```
Если в `X-Debug-Filename` сформирован неверный путь (например, `/var/www/data/assets/static/style.css`), ошибка вызвана использованием `root` вместо `alias` либо неверным замыкающим слэшем.

#### 2. Анализ журнала ошибок Nginx

```bash
# Фильтрация ошибок файловой подсистемы в реальном времени
tail -n 50 -f /var/log/nginx/error.log | grep -E "(denied|failed|cycle)"
# → 2026/10/16 12:30:15 [error] 1420#1420: *1 open() "/var/www/html/test.png" failed (13: Permission denied), client: 192.168.1.10, server: example.com, request: "GET /test.png HTTP/1.1", host: "example.com"
```

Код ошибки ядра в скобках указывает на физическую причину:
- `(13: Permission denied)` — не хватает прав на файл или промежуточный каталог для пользователя `www-data`.
- `(2: No such file or directory)` — файла не существует по пути, вычисленному Nginx.
- `(20: Not a directory)` — часть пути, ожидаемая как каталог, является обычным файлом.

---

## Лучшие практики

### Производительность (Performance)

1. **Используйте модификатор `^~` для статических блоков.** Если статика расположена в выделенных каталогах (`/assets/`, `/static/`, `/media/`), объявляйте их как `location ^~ /assets/`. Это останавливает дальнейший поиск регулярных выражений при совпадении самого длинного префикса, существенно экономя процессорное время CPU на каждом запросе.
2. **Включайте связку сетевого ввода-вывода ядра.** Конфигурация по умолчанию для продакшена:
   ```nginx
   sendfile            on;
   sendfile_max_chunk  512k;
   tcp_nopush          on;
   tcp_nodelay         on;
   ```
3. **Используйте пулы потоков для дискового ввода-вывода.** На серверах с гибридными или сетевыми дисками выносите блокирующие операции в потоки (`aio threads=default;`), предотвращая деградацию времени отклика сервера.
4. **Настраивайте `open_file_cache`.** Для сайтов с числом статических файлов свыше 1000 кэширование дескрипторов снижает число системных вызовов к ядру на 20–30%.
5. **Применяйте предварительное сжатие в CI/CD.** Заменяйте динамическое сжатие на лету отдачей pre-compressed файлов (`gzip_static on;` и `brotli_static on;`). Это освобождает ядра CPU для обработки логики приложений и SSL-хэндшейков.

### Безопасность (Security)

1. **Защищайте директиву `alias` от Off-by-slash.** Всегда проверяйте, чтобы префикс `location` и путь `alias` синхронно заканчивались символом `/`.
2. **Блокируйте скрытые файлы и пути систем контроля версий.** Запрещайте доступ ко всем файлам, начинающимся с точки:
   ```nginx
   location ~ /\.(?!well-known) {
       deny all;
       access_log off;
       log_not_found off;
   }
   ```
3. **Запрещайте выход за пределы корня через симлинки.** В каталогах, куда возможна загрузка пользовательских файлов, включайте:
   ```nginx
   disable_symlinks on from=$document_root;
   ```
4. **Изолируйте защищенные файлы директивой `internal;`.** Пути для скачивания конфиденциальных отчетов, чеков и личных документов никогда не должны быть открыты для прямого обращения из интернета. Используйте архитектуру `X-Accel-Redirect`.
5. **Запрещайте исполнение скриптов в каталогах статики.** Если директория содержит пользовательские загрузки (`/uploads/`), исключайте проксирование или запуск PHP/CGI внутри нее:
   ```nginx
   location ^~ /uploads/ {
       root /var/www/app;
       # Запрет обработки любых интерпретируемых расширений
       location ~* \.(php|pl|py|jsp|sh|cgi)$ {
           deny all;
       }
   }
   ```
6. **Защита от хотлинкинга (Anti-Hotlinking).** Предотвращайте кражу медиаконтента сторонними ресурсами:
   ```nginx
   location ~* \.(jpg|jpeg|png|gif|webp)$ {
       valid_referers none blocked server_names *.example.local;
       if ($invalid_referer) {
           return 403;
       }
   }
   ```

### Эксплуатация (SRE и Sysadmin)

1. **Принцип наименьших привилегий для файлов.** Процесс веб-сервера должен иметь права только на чтение (`r-x` для директорий, `r--` для файлов). Ни при каких обстоятельствах каталог со статикой не должен иметь прав записи (`w`) для пользователя `www-data` или `nginx`.
2. **Стратегия кэширования Cache-Busting.** Настраивайте раздельную политику:
   - Хэшированные ассеты (`app.a1b2c3.js`): `Cache-Control: public, max-age=31536000, immutable`.
   - Входные точки (`index.html`): `Cache-Control: no-cache`.
3. **Оптимизация логирования статики.** При высоких нагрузках логирование каждого запроса картинки или скрипта перегружает диск. Используйте буферизацию логов или отключайте логирование валидных запросов:
   ```nginx
   access_log /var/log/nginx/static.access.log combined buffer=64k flush=5m;
   # Либо для иконок и ассетов:
   # access_log off;
   # log_not_found off;
   ```
4. **Контроль системных лимитов.** Убедитесь, что в systemd-юните `/etc/systemd/system/nginx.service.d/override.conf` установлен лимит дескрипторов:
   ```ini
   [Service]
   LimitNOFILE=65535
   ```

---

## Дополнительная информация

### Связанные темы в базе знаний

- **[Директива location: основы и приоритеты](./basics.md)** — архитектура префиксного дерева (Trie), правила и приоритеты сопоставления URI.
- **[Nginx location: лучшие практики и отладка](./best_practices.md)** — практические паттерны построения плоских конфигураций и техники отладки.
- **[Nginx: внутренняя маршрутизация](./internal_routing.md)** — механизмы `internal`, `ngx_http_internal_redirect`, именованные locations и архитектура `X-Accel-Redirect`.
- **[Перенаправления и перезапись URI в Nginx](../nginx_rewrite_rules_and_try_files.md)** — фазы rewrite, директивы `try_files`, `return` и переменные `$uri`, `$request_uri`.
- **[Клиентское кэширование в Nginx и Angie](../../Performance/Caching/client_caching.md)** — управление клиентскими заголовками `Cache-Control`, `expires`, ETag и условными запросами.
- **[Оптимизация производительности Nginx](../../Performance/nginx_performance_tuning.md)** — системные параметры ядра Linux, тюнинг сокетов и сетевого стека.
- **[Оптимизация сжатия в Nginx](../../Performance/nginx_compression.md)** — детальная настройка модулей сжатия Gzip, Brotli и Zstandard.
- **[Диагностика и устранение неполадок Nginx](../../Operations/nginx_troubleshooting.md)** — системные коды ошибок, анализ дампов и решение инцидентов.
