# Вспомогательные HTTP-модули и внутренние директивы Angie

## Определения

**sub_filter** (`ngx_http_sub_module`) — фильтр, заменяющий в теле ответа (обычно HTML) одни строки на другие. Используется для подмены URL ассетов, вставки меток, модификации ответов бэкенда без изменения приложения.

**slice** (`ngx_http_slice_module`) — разбивает проксируемый ответ на фрагменты (срезы) фиксированного размера. Позволяет эффективно работать с рендж-запросами (видео, большие скачивания) и кэшировать любой участок большого файла независимо.

**split_clients** (`ngx_http_split_clients_module`) — распределяет трафик по проценту от хэша (по умолчанию от `$remote_addr`): классический механизм A/B-тестов и канареечной раскатки на уровне конфигурации.

**referer** (`ngx_http_referer_module`) — фильтр, пропускающий/блокирующий запросы по значению заголовка `Referer` (защита от прямой привязки изображений и «парсинга» ресурсов).

**gunzip** (`ngx_http_gunzip_module`) — модуль «на лету» распаковки `gzip`-ответов для клиентов, которые не поддерживают сжатие (редкие старые клиенты), когда бэкенд отдаёт только сжатый контент.

**servername hash (server_names_hash)** — хэш-таблицы, по которым Angie сопоставляет заголовок `Host` с блоками `server`/`server_name`. Размеры задаются `server_names_hash_max_size` и `server_names_hash_bucket_size`.

**map_hash** — хэш-таблицы для модуля `map` (`ngx_http_map_module`): отображение значений переменных (напр., по `$http_user_agent`). Задаются `map_hash_max_size` и `map_hash_bucket_size`.

**underscores_in_headers** — директива core-модуля, разрешающая (или запрещающая) наличие символа `_` в именах входящих заголовков (например, `X_Custom_Header`).

## Базовые концепции

### Группировка модулей

Все перечисленные модули входят в стандартную поставку Angie (собраны нативно, без установки отдельных пакетов). Они не меняют семантику обработки запросов в целом, а добавляют точечные «фильтры»/«хэндлеры»:

| Модуль | Уровень работы | Типичная задача |
| :--- | :--- | :--- |
| `sub_filter` | Body filter (ответ) | Подмена строк в HTML |
| `slice` | Обработка запроса/кэша | Фрагментация больших файлов |
| `split_clients` | Переменная (rewrite) | A/B-тесты, канарейки |
| `referer` | Access (по `Referer`) | Hotlink-защита |
| `gunzip` | Body filter (ответ) | Распаковка для старых клиентов |

### Хэш-таблицы и внутренние настройки

При большом количестве `server_name` (сотни виртуальных хостов) или больших данных в `map` хэш-таблица может не поместиться: Angie откажется запускаться с ошибкой вида *"could not build the server_names_hash, you should increase server_names_hash_bucket_size"*. Это не «баг», а признак недооценённых размеров таблиц. Подбираются по принципу «максимальная фактическая длина имени + запас».

Директива `underscores_in_headers` по умолчанию выключена (`off`): заголовки с подчёркиванием (`X_Custom`) будут проигнорированы и не попадут в `$http_x_custom`. Эта «защита от мусора» соответствует рекомендациям безопасности; включается только если нужный клиент реально присылает такие заголовки.

## Практические сценарии

### Сценарий 1: sub_filter — подмена URL ассетов в HTML

```nginx
location / {
    sub_filter '</head>' '<link rel="preload" href="/static/app.css" as="style"></head>';
    sub_filter_once on;                    # заменить только первое вхождение
    sub_filter_types text/html;           # только HTML (по умолчанию text/html)
}
```

Для подмены на всех поддерживаемых типах:

```nginx
sub_filter 'http://old-cdn.example.com' 'http://cdn.example.com';
sub_filter_once off;
```

### Сценарий 2: slice — проксирование и кэширование больших файлов

```nginx
slice             1m;                     # фрагменты по 1 МБ
proxy_cache_path  /var/cache/angie/slice keys_zone=slice:20m max_size=10g;

server {
    location ~ \.(mp4|zip)$ {
        slice 1m;
        proxy_cache slice;
        proxy_cache_valid 200 24h;
        proxy_set_header Range $slice_range;   # каждый фрагмент запрашивается отдельным Range
        proxy_pass http://files_backend;
    }
}
```

Благодаря `slice` кэшируются и отдаются только запрошенные диапазоны, а не весь файл (экономия диска и трафика при докачивании видео).

### Сценарий 3: split_clients — A/B-тест и канарейка

```nginx
split_clients "${remote_addr}" $ab_experiment {
    10%    "new-design";   # 10% пользователей видят новый дизайн
    *      "old-design";
}

server {
    location / {
        if ($ab_experiment = "new-design") {
            proxy_pass http://frontend_new;
        }
        proxy_pass http://frontend_old;
    }
}
```

Стабильность распределения обеспечивается хэшем исходной строки: один и тот же клиент всегда попадает в одну группу (пока не изменится переменная-источник).

### Сценарий 4: referer — защита от hotlink (запрет привязки изображений)

```nginx
location ~ \.(jpg|jpeg|png|gif|webp)$ {
    valid_referers none blocked server_names *.example.com;

    if ($invalid_referer) {
        return 403;
    }
    # или отдавать заглушку вместо картинки:
    # rewrite ^ /hotlink-placeholder.gif last;
}
```

`blocked` учитывает запросы без `Referer` или с повреждённым (например, из-за privacy-браузеров) — отключать осторожно. **Внимание:** защита по `Referer` — не гарантия безопасности (заголовок подделывается), это скорее анти-паразитный фильтр.

### Сценарий 5: gunzip — отдача сжатого контента старым клиентам

```nginx
server {
    gunzip on;                    # распаковывать, если клиент не умеет gzip
    gunzip_buffers 32 4k;

    location /archive/ {
        gzip_static on;           # отдавать пред-сжатые .gz, если они есть
        gzip on;                  # (для клиентов, поддерживающих gzip)
    }
}
```

Требуется, чтобы бэкенд отдавал `Content-Encoding: gzip` и при этом клиент не указывал `Accept-Encoding: gzip` (например, древний робот). В современных окружениях `gunzip` почти не нужен, но эпизодически востребован при поддержке легаси-клиентов.

### Сценарий 6: Крупные server_names_hash / map_hash

```nginx
http {
    server_names_hash_bucket_size  64;
    server_names_hash_max_size     1024;

    map_hash_bucket_size           64;
    map_hash_max_size              2048;

    map $http_user_agent $is_bot {
        default  0;
        ~*bot     1;
    }
}
```

Начните с `server_names_hash_bucket_size 64` (кратно размеру строки процессора, обычно 32/64) — это исправляет большинство стартовых ошибок запуска.

### Сценарий 7: underscores_in_headers — приём кастомных заголовков

```nginx
http {
    underscores_in_headers on;   # разрешить X_CUSTOM_HEADER и т.п.
    # off (по умолчанию) — такие заголовки игнорируются
}
```

Включать только при реальной необходимости (интеграции, присылающие подчёркнутые заголовки). В противном случае оставляйте `off` из соображений безопасности и единообразия.

## Операции и команды

### Верификация доступности модуля

```bash
angie -V 2>&1 | grep -oE "http_sub|http_slice|http_split_clients|http_referer|http_gunzip"
```

### Проверка конфигурации

```bash
sudo angie -t
sudo systemctl reload angie
```

### Проверка работы проброса виртуальных хостов

```bash
# Какой server_name подхватит запрос?
curl -sI -H "Host: example.com" http://127.0.0.1/
# Проверка хэша (в логах при большой конфигурации)
grep -i "hash\|server_names" /var/log/angie/error.log | tail -n 20
```

### Проверка split_clients распределения

```bash
for i in $(seq 1 100); do
  curl -s -o /dev/null -w "%{http_code}\n" -H "Host: ab.example.com" http://127.0.0.1/ -H "X-Client: ip-$i";
done | sort | uniq -c
```

## Устранение неисправностей

### Ошибка "could not build the server_names_hash"

**Причина:** размера хэша не хватает для всех `server_name`.
**Решение:** увеличить `server_names_hash_bucket_size`/`server_names_hash_max_size` (см. Сценарий 6).

### sub_filter не срабатывает

**Причина:** контент не `text/html` (или другой тип вне `sub_filter_types`), либо `sub_filter_once off` не задан там, где нужно множественное совпадение.
**Решение:** проверить `Content-Type` ответа и расширить `sub_filter_types`.

### split_clients даёт «грязное» распределение

**Причина:** источник хэша меняется между запросами (например, `$http_user_agent`, если клиент меняет UA) или хэшируется не тот ключ.
**Решение:** стабилизировать источник (`$remote_addr`, `$binary_remote_addr`, id сессии).

### Заголовок X_Custom не доходит до бэкенда

**Причина:** `underscores_in_headers` выключено (для имён с `_`).
**Решение:** включить `underscores_in_headers on;` (или переименовать заголовок без подчёркиваний).

## Лучшие практики

1. **Не полагайтесь на `referer` как на защиту:** это UX-фильтр, а не механизм безопасности.
2. **`slice` — только для больших потоковых файлов:** для обычных страниц он добавляет лишние подзапросы.
3. **A/B и канарейки делайте через `split_clients`** от стабильного ключа, а не через `map` от случайных переменных.
4. **Хэш-таблицы задавайте кратно размеру строки CPU** (32/64 байта) и с запасом.
5. **`underscores_in_headers` держите `off`** по умолчанию; переключайте точечно под конкретную интеграцию.
6. **`gunzip` включайте только при легаси-клиентах** — для большинства трафика он избыточен.
7. **Пишите тесты на конфигурацию каждого модуля** в CI (см. раздел «Операции»).

## Дополнительная информация

- Общие директивы `server`/`location`, порядок матчинга — [Директивы location в Angie](./angie_location_directives.md).
- A/B-нагрузка в балансировке (Canary на upstream-уровне) — [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md).
- Сжатие (gzip/brotli/zstd) и `gzip_static` в деталях — [Оптимизация сжатия в Nginx](../Nginx/Performance/nginx_compression.md).
- Хранение/отдача статических файлов (`autoindex`, `index`, `charset`) — [Отдача файлов (serving_files)](../Nginx/Core/Location/serving_files.md).
- Официальная документация: [sub_filter, slice, split_clients, referer, gunzip (nginx.org)](https://nginx.org/en/docs/http/), а также [документация модулей Angie](https://en.angie.software/angie/docs/configuration/).

## См. также

- [Директивы location в Angie](./angie_location_directives.md)
- [Оптимизация сжатия в Nginx](../Nginx/Performance/nginx_compression.md)
- [Отдача файлов (serving_files)](../Nginx/Core/Location/serving_files.md)
- [Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)