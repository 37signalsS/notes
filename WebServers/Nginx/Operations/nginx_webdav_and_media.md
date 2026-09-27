# Утилитные модули Nginx: WebDAV, видео и SSI

## Определения

**ngx_http_dav_module** — модуль WebDAV (Web Distributed Authoring and Versioning) в комплекте Nginx. Даёт работу с методами `PUT`, `DELETE`, `MKCOL`, `COPY`, `MOVE` для организации web-хранилищ, синхронизации файлов и каталогов через протокол HTTP.

**ngx_http_mp4_module** / **ngx_http_flv_module** — модули потоковой отдачи видео: `mp4` отдаёт `.mp4` с поддержкой запросов фрагментов (seeking), `flv` — для `.flv`. Позволяют серверу обслуживать видео без конвертации в HLS/DASH на лёгких сценариях.

**SSI (Server Side Includes)** — директива `ssi on;`, подставляющая фрагменты в HTML на лету (`<!--# include file="header.html" -->`), без полноценного шаблонизатора.

**image_filter** — модуль динамической обработки изображений (resize, crop, rotate) на лету; разобран отдельно для Angie: [image_filter](../../Angie/High_Load/image_filter/overview.md).

## Основные концепции

### WebDAV в Nginx

- `dav_methods PUT DELETE MKCOL COPY MOVE;` — какие методы разрешены.
- `dav_access user:rw group:rw all:r;` — права на создаваемые объекты.
- `create_full_put_path on;` — создавать промежуточные каталоги при `PUT` на новый путь.
- Модуль **не включает** шифрование/авторизацию — всегда комбинируйте с `auth_basic`/`auth_request`/mTLS (см. [mTLS в Nginx](../Security/TLS_SSL/nginx_mtls_configuration.md)).
- Расширенный модуль **dav_ext** (`nginx-module-dav-ext`) добавляет `PROPFIND`-каталоги, `LOCK`/`UNLOCK` и `X-Alt-Namespace` — полноценный WebDAV для клиентов (ownCloud/Nextcloud Desktop, Windows WebDAV).

### Медиа-модули

- **mp4:** работает только с **faststart** `.mp4` (moov-атом в начале файла). Позволяет клиентской стороне ставить паузу/промотать без скачивания всего файла: Nginx разбивает файл по чанкам (`mdat`).
  - `mp4_start_key_frame on;` — начинать фрагмент с ключевого кадра.
  - `mp4_max_buffer_size;` — лимит буфера для moov-атома (обычно 16–32m).
- **flv:** статический модуль для `.flv`; используется редко (устаревающий формат).
- Оба модуля менее эффективны, чем специализированные стриминговые серверы (HLS/DASH, nginx-rtmp); для современного видео предпочитайте `nginx-rtmp` или отдельный стример.

### SSI

- `ssi on;` в `location`; подстановка `<!--# include virtual="/file" -->` во время обработки.
- Производительность ниже статики; применяется для простых макетов, «лёгкого» включения фрагментов без JS.

### sub_filter и манипуляция заголовками

`ngx_http_sub_module` подменяет строки в теле ответа на лету — полезен, когда бэкенд нельзя менять, а нужно поправить URL ассетов или вставить метку. Управление заголовками ответа идёт через `add_header`/`proxy_hide_header`/`proxy_pass_header`.

Ключевые директивы:

- `sub_filter <от> <к>;` — замена подстроки; `sub_filter_once on|off` — только первое вхождение или все; `sub_filter_types` — какие типы контента фильтровать (по умолчанию только `text/html`).
- `proxy_hide_header <name>` — скрыть заголовок бэкенда (например, `Server`, `X-Powered-By`).
- `proxy_pass_header <name>` — вернуть заголовок, скрытый наследованием.
- `add_header <name> <value> always;` — добавить заголовок (с `always` — и на ответах с ошибками).

Требует модуля `--with-http_sub_module` (обычно собран по умолчанию). Полный разбор — в [Утилитных модулях Angie](../../Angie/angie-http-utility-modules.md) и [Проксировании HTTP-сервисов](../../../Networking/Protocols/HTTP/http_servers_proxies.md).

## Практические сценарии

### Предварительные требования

```bash
# Модули собираются в Nginx из исходников:
# --with-http_dav_module --with-http_mp4_module --with-http_flv_module --with-http_ssi_module
nginx -V 2>&1 | grep -o 'with-http_[a-z_]*'
# → --with-http_dav_module (если собран)
```

### Сценарий 1: Простое WebDAV-хранилище с авторизацией

```nginx
location /dav/ {
    auth_basic "WebDAV";
    auth_basic_user_file /etc/nginx/.htpasswd;

    dav_methods PUT DELETE MKCOL COPY MOVE;
    dav_access user:rw group:rw all:r;
    create_full_put_path on;
    client_max_body_size 1g;
    autoindex on;

    root /var/www/dav;
}
```

Проверка:

```bash
curl -u user:pass -X MKCOL http://example.com/dav/newdir/
curl -u user:pass -T file.txt http://example.com/dav/
curl -u user:pass -I http://example.com/dav/file.txt
# → HTTP/1.1 200 OK
```

### Сценарий 2: Full WebDAV через dav_ext (PROPFIND/LOCK)

```bash
# Установка модуля dav-ext (пример для Debian)
sudo apt install -y libnginx-mod-http-dav-ext
```

```nginx
location /nextcloud-dav/ {
    auth_basic "DAV";
    auth_basic_user_file /etc/nginx/.htpasswd;
    client_max_body_size 0;              # лимит не ограничивает webdav
    dav_methods PUT DELETE MKCOL COPY MOVE;
    dav_ext_methods PROPFIND OPTIONS LOCK UNLOCK;
    dav_ext_lock_zone zone=davlock:10m;
    dav_access user:rw group:rw all:r;
    create_full_put_path on;
}
```

> Для **Nextcloud** используйте официальные инструкции: Nginx отдаёт `location /remote.php`, а WebDAV включается приложением; `dav_ext` нужен только при автозагрузке файлов через WebDAV-клиенты. Протокол подробнее: [WebDAV на Linux](../../../Linux/Networking/Services/webdav/webdav_overview.md).

### Сценарий 3: Отдача MP4 с поддержкой seeking

```nginx
location /videos/ {
    root /srv/media;
    mp4;
    mp4_start_key_frame on;
    mp4_max_buffer_size 32m;
    limit_rate_after 20m;
    limit_rate 2m;      # ограничение полосы от видеосервера
}
```

Проверка (запрос фрагмента):

```bash
curl "http://example.com/videos/movie.mp4?start=120&end=130" -o part.mp4
# → Ожидаем успешный ответ 200 и вывод только запрошенных кадров
```

### Сценарий 4: SSI-включение фрагментов

```nginx
location /pages/ {
    root /srv/www;
    ssi on;
    ssi_types text/html;
}
```

```html
<!-- /srv/www/pages/index.html -->
<html><body>
<!--# include file="/fragments/header.html" -->
<!--# include virtual="/api/blocks/menu" -->
</body></html>
```

### Сценарий 5: sub_filter — подмена URL ассетов в HTML

Бэкенд отдаёт абсолютные URL на старый домен; Nginx переписывает их в ответе, не трогая приложение:

```nginx
location / {
    proxy_pass http://backend;

    sub_filter 'http://old-static.example.com' 'https://cdn.example.com';
    sub_filter_once off;                # заменить все вхождения
    sub_filter_types text/html;         # только HTML (по умолчанию text/html)

    proxy_hide_header X-Powered-By;     # скрыть лишние заголовки бэкенда
    add_header X-Upstream-Host $upstream_addr always;
}
```

Проверка:

```bash
curl -s http://example.com/ | grep -o 'cdn.example.com' | wc -l
# → число заменённых вхождений; если 0 — проверьте Content-Type ответа
```

## Операции и команды

| Команда/Директива | Назначение |
| :--- | :--- |
| `nginx -V \| grep with-http` | Проверка скомпилированных модулей |
| `curl -X MKCOL` / `-T file` / `-X DELETE` | Тест методов WebDAV |
| `dav_methods` / `dav_access` / `create_full_put_path` | Настройка WebDAV |
| `dav_ext_methods` / `dav_ext_lock_zone` | Расширенные WebDAV (dav_ext) |
| `mp4` / `mp4_start_key_frame` / `mp4_max_buffer_size` | Настройка MP4 |
| `ssi on` / `ssi_types` | Server Side Includes |
| `sub_filter` / `sub_filter_once` / `sub_filter_types` | Подмена строк в теле ответа |
| `proxy_hide_header` / `proxy_pass_header` / `add_header ... always` | Управление заголовками ответа |
| `curl "...?start=&end="` | Загрузка фрагмента видео |

## Устранение неполадок

### `405 Method Not Allowed` для PUT/MKCOL

**Причина:** метод не включён в `dav_methods`, либо WebDAV-локация конфликтует с другим `location` (regex перехватывает запрос).

**Решение:** добавьте методы в `dav_methods`; проверьте порядок `location` (regex-локации имеют приоритет).

### Nextcloud/ownCloud: «Ошибка WebDAV PROPFIND»

**Причина:** нет поддержки `PROPFIND`/`LOCK` (нужен dav_ext), либо `location` перехватывает `/remote.php`.

**Решение:** включите `dav_ext_methods`; изучите официальную конфигурацию для `/remote.php` и `client_max_body_size 0`.

### Видео не мотается (нет seeking) в MP4

**Причина:** файл не в faststart-формате (moov-атом в конце) — Nginx не может выдать начало фрагмента.

**Решение:** пересоберите файл: `ffmpeg -i in.mp4 -c copy -movflags +faststart out.mp4`.

### Модуль не найден (`unknown directive "mp4"`)

**Причина:** модуль не собран/не загружен.

**Решение:** пересоберите Nginx с `--with-http_mp4_module` либо добавьте пакетный модуль; для динамических `.so` — `load_module`.

### sub_filter не срабатывает

**Причина:** `Content-Type` ответа не входит в `sub_filter_types` (по умолчанию только `text/html`), либо совпадений нет из-за регистра/пробелов.

**Решение:** проверьте заголовок ответа `curl -sI`, расширьте `sub_filter_types` при необходимости, используйте `sub_filter_once off` для множественных вхождений.

## Лучшие практики

- WebDAV в публичном интернете — **только с авторизацией и TLS** (BasicAuth поверх HTTPS, либо mTLS для automation).
- Для больших файлов задавайте `client_max_body_size` и следите за `limit_rate`, чтобы один клиент не забрал всю полосу.
- Видео для prod-стриминга лучше отдавать через HLS/DASH (nginx-rtmp), а mp4-модуль использовать для простых лендингов/превью.
- SSI применяйте ограниченно: производительность ниже, чем статика, и сложнее кэширование (включает фрагменты на каждый запрос).
- Подсчитывайте использование диска для WebDAV-каталогов и медиа в мониторинге; включайте `autoindex` только в контролируемых зонах.

## Дополнительная информация

### Взаимосвязи

- **[image_filter в Angie](../../Angie/High_Load/image_filter/overview.md)** — динамическая обработка изображений (resize, crop) на лету.
- **[WebDAV-протокол](../../../Linux/Networking/Services/webdav/webdav_overview.md)** — клиентская часть и настройка совместимости.
- **[mTLS в Nginx](../Security/TLS_SSL/nginx_mtls_configuration.md)** — защита WebDAV клиентскими сертификатами.
- **[Утилитные модули Angie](../../Angie/angie-http-utility-modules.md)** — `sub_filter`, `slice`, `split_clients`, `referer`, `gunzip`.
- **[Проксирование HTTP-сервисов](../../../Networking/Protocols/HTTP/http_servers_proxies.md)** — наследование заголовков и `proxy_hide_header`/`proxy_pass_header`.