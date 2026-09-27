# Буферизация и стриминг в Nginx

## Определения

**Буферизация ответа (response buffering)** — Nginx начинает отдавать ответ клиенту только после того, как получен весь ответ бэкенда (или заполнение одного буфера). Управляется семейством директив `proxy_buffering`, `proxy_buffer_size`, `proxy_buffers`, `proxy_busy_buffers_size`.

**Буферизация запроса (request buffering)** — Nginx сначала принимает всё тело запроса клиента (в память или временный файл), и только потом передаёт его апстриму. Управляется `proxy_request_buffering` и `client_body_buffer_size`.

**Стриминг** — передача данных потоком без полного накопления: когда бэкенд отдаёт длинный/бесконечный ответ (SSE, WebSocket, gRPC) или Nginx отдаёт большой файл, лишний буфер приводит к задержкам TTFB и росту памяти.

## Основные концепции

### Архитектура буферизации

Когда Nginx работает reverse proxy:

```text
client ──► nginx(proxy_buffer) ──► backend
           (память/файл)
```

- **Включённая буферизация:** ответ бэкенда копируется в буфер (память, при превышении — во временный файл), и лишь затем отдаётся клиенту. Плюс — клиент с медленным каналом не «душит» чтение от бэкенда; Nginx вычитывает ответ максимально быстро и освобождает апстрим.
- **Выключенная буферизация:** Nginx передаёт куски из сокета апстрима клиенту сразу по мере чтения.

### Ключевые директивы

| Директива | Назначение | Дефолт |
| :--- | :--- | :--- |
| `proxy_buffering on\|off;` | Включить/выключить буферизацию ответов | on |
| `proxy_buffer_size 8k;` | Размер старта ответа (заголовки + первые байты) | 8k |
| `proxy_buffers 8 8k;` | Кол-во и размер буферов для тела ответа | 8 8k |
| `proxy_busy_buffers_size 16k;` | Буфер, отдаваемый клиенту одновременно | 2×buffer_size |
| `proxy_max_temp_file_size 1024m;` | Предел записи ответа во временный файл | 1024m |
| `proxy_temp_path /var/cache/nginx/temp;` | Каталог временных файлов буфера | сборочный |
| `proxy_request_buffering on\|off;` | Буферизация тела запроса | on |
| `client_body_buffer_size 16k;` | Размер памяти для тела запроса до записи в файл | 2×page |
| `proxy_temp_file_write_size;` | Размер записи во временный файл | proxy_buffers×2 |

### Когда буферизация мешает

- **SSE (Server-Sent Events), WebSocket, gRPC-streaming:** бесконечный или долгий поток нельзя накапливать в буфере — иначе данные задерживаются, TTFB растёт, соединения забиваются. Для таких протоколов `proxy_buffering off;` обязателен.
- **Большие файлы:** с буферизацией — лишний диск(=временные файлы) и задержка; для раздачи файлов используются `sendfile` + `aio` + `directio` (см. отдачу статики).
- **Высокий TTFB у клиентов при slow-старте бэкенда:** `proxy_buffer_size` меньше, чем первые байты ответа от апстрима, вызывает ошибку `upstream sent too big header`.

### X-Accel-Buffering (заголовок от бэкенда)

Бэкенд может управлять буферизацией **без правки конфига Nginx**, отдавая заголовок `X-Accel-Buffering: no` (аналог `proxy_buffering off;` на конкретный ответ) или `yes`. Это удобно для стриминга из приложения: Nginx отдаёт поток сразу.

## Практические сценарии

### Сценарий 1: Reverse proxy с буферизацией по умолчанию (API)

Для обычных API буферизация полезна — она стабилизирует нагрузку на бэкенд:

```nginx
location /api/ {
    proxy_buffering on;
    proxy_buffer_size 16k;
    proxy_buffers 8 16k;
    proxy_busy_buffers_size 32k;
    proxy_pass http://api_backend;
}
```

Диагностика корректности размера заголовка:

```bash
# Если бэкенд шлёт большой заголовок — ошибка в error.log:
# "upstream sent too big header while reading response header from upstream"
grep "too big header" /var/log/nginx/error.log
```

### Сценарий 2: Стриминг SSE и WebSocket (без буферизации)

```nginx
location /events/ {
    proxy_buffering off;                 # поток отдаётся сразу
    proxy_cache off;                     # не кэшировать события
    proxy_set_header Connection '';
    proxy_http_version 1.1;
    proxy_read_timeout 3600s;            # долгоживущее соединение
    proxy_pass http://events_backend;
}
```

Проверка:

```bash
curl -N -H 'Accept: text/event-stream' http://example.com/events/
# → первые события должны приходить до завершения ответа (а не скопом в конце)
```

Протоколы и таймауты WebSocket/SSE/gRPC подробно разобраны в [Angie: WebSocket, SSE, gRPC](../../Angie/angie-websocket-sse-grpc.md) — директивы идентичны для Nginx.

### Сценарий 3: Streaming загрузок (большие файлы)

```nginx
location /downloads/ {
    proxy_buffering off;   # поток с бэкенда сразу клиенту
    proxy_request_buffering off;   # не накапливать тело больших POST/PUT
    sendfile on;
    proxy_pass http://files_backend;
}
```

Для отдачи файлов с диска без прокси — `sendfile`/`aio`/`directio` + `open_file_cache` (см. [Отдача статики](../Core/Location/serving_files.md)).

### Сценарий 4: Буферизация запроса (защита от медленного боди / подкачки диска)

По умолчанию тело запроса буферизуется: медленное тело клиента не держит апстрим, а при превышении `client_body_buffer_size` — сбрасывается во временный файл.

```nginx
location /upload/ {
    client_body_buffer_size 1m;
    client_body_timeout 30s;
    proxy_request_buffering on;
    proxy_max_temp_file_size 0;   # не использовать диск для тела (строго в памяти)
    proxy_pass http://upload_backend;
}
```

**Предостережение:** `proxy_request_buffering off;` включает передачу тела по мере поступления — для UPLOAD это уменьшает задержку у клиента, но связывает апстрим с медленным клиентом и увеличивает риск hold-open (медленный UPLOAD-атаки). Для безопасности комбинируйте с `client_body_timeout`.

### Сценарий 5: Гибкое управление через X-Accel-Buffering и признак протокола

Nginx может отключать буферизацию **выборочно** по типу ответа через `map`:

```nginx
map $http_accept $buffered {
    default        on;
    "~text/event-stream" off;
}

server {
    location / {
        proxy_buffering $buffered;   # Nginx 1.27+ позволяет переменный параметр
        proxy_pass http://app;
    }
}
```

Если версия Nginx жестко не поддерживает переменное значение `proxy_buffering` — используйте раздельные location или `X-Accel-Buffering` от бэкенда.

## Операции и команды

| Команда/Директива | Назначение |
| :--- | :--- |
| `proxy_buffering` / `proxy_request_buffering` | Вкл/выкл буферизацию от/к бэкенду |
| `proxy_buffer_size` | Размер первого буфера (заголовок ответа) |
| `proxy_buffers` / `proxy_busy_buffers_size` | Буферы тела и буфер выдачи клиенту |
| `proxy_max_temp_file_size` / `proxy_temp_path` | Предел и путь временных файлов |
| `X-Accel-Buffering: no\|yes` | Управление от бэкенда без правки конфига |
| `du -sh /var/cache/nginx/temp` | Контроль временных файлов буфера |
| `ss -tnp \| grep nginx` | Состояние соединений при стриминге |

Диагностика объёма временных файлов при активной буферизации:

```bash
watch -n1 'ls -la /var/cache/nginx/temp | wc -l'
```

## Устранение неполадок

### `upstream sent too big header`

**Причина:** `proxy_buffer_size` меньше размера ответа из заголовка апстрима (см. Cookies, большой `Location`, JWT в заголовке).

**Решение:** увеличить `proxy_buffer_size` (например, 16k/32k); при необходимости `proxy_buffers`.

### SSE/WebSocket: данные приходят пачками только в конце / TTFB высокий

**Причина:** буферизация включена и поток накапливается.

**Решение:** `proxy_buffering off;` для таких location; для событий убедитесь в `Content-Type: text/event-stream` и `Cache-Control: no-cache`.

### Диск забит временными файлами буфера (proxy_temp)

**Причина:** большие ответы > памяти буферов записываются на диск.

**Решение:** увеличьте `proxy_buffers`/`proxy_buffer_size` для контента среднего размера; для стриминга — `proxy_buffering off;` Наблюдайте `proxy_max_temp_file_size`.

### Медленный клиент «держит» апстрим при `proxy_buffering off`

**Причина:** при выключенной буферизации Nginx связан с клиентом и апстримом синхронно.

**Решение:** используйте буферизацию для обычного контента, оставайтесь стриминг только там, где это необходимо; задавайте разумные таймауты (`proxy_read_timeout`, `send_timeout`).

## Лучшие практики

- **По умолчанию оставляйте буферизацию включённой** — она защищает апстрим от медленных клиентов и стабилизирует throughput.
- **Отключайте только для потоковых протоколов** (SSE/WS/gRPC) и больших файлов.
- Следите за `too big header` — это частая причина неожиданных 502.
- Для стриминга из приложения применяйте `X-Accel-Buffering: no` вместо глобального выключения.
- Большие uploads буферизуйте в память/диск с таймаутом — это защита от медленного-вытечения ресурсов.
- Комбинируйте с таймаутами: `proxy_read_timeout`, `proxy_send_timeout`, `send_timeout`, `client_body_timeout`.

## Дополнительная информация

### Взаимосвязи

- **[Angie: WebSocket, SSE, gRPC](../../Angie/angie-websocket-sse-grpc.md)** — протоколы стриминга, таймауты, buffers в Angie (директивы совместимы с Nginx).
- **[Отдача статических файлов](../Core/Location/serving_files.md)** — sendfile/AIO/DirectIO/zero-copy для нативных файлов.
- **[Практическая конфигурация балансировки](../Proxy/Load_Balancing/practical_configuration.md)** — управления потоком данных в L7-балансировке.

### См. также

- [Обзор концепций балансировки L7](../Proxy/Load_Balancing/overview_concepts.md) — buffering на уровне L7.