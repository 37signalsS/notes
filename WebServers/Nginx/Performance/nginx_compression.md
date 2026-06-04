# Оптимизация сжатия в Nginx (Gzip, Brotli, ZSTD)

## Определения

**Сжатие данных** — это процесс уменьшения объема передаваемых данных, что напрямую влияет на скорость загрузки веб-страниц и экономию трафика. Это одна из ключевых техник в [общем руководстве по оптимизации производительности](../../Concepts/web_performance/overview.md).

Основные алгоритмы сжатия, используемые в Nginx:

* **Gzip** — проверенный временем и универсально поддерживаемый алгоритм сжатия.
* **Brotli** — современный алгоритм от Google, обеспечивающий более высокую степень сжатия по сравнению с Gzip.
* **ZSTD (Zstandard)** — алгоритм от Facebook, обеспечивающий высокую скорость сжатия и декомпрессии при хорошем коэффициенте сжатия.

## Основные концепции

В [Nginx](../Core/nginx_overview.md) существуют два основных подхода к сжатию, которые также применимы к его форку [Angie](../../Angie/angie_overview.md).

### Типы сжатия

1. **Динамическое сжатие (on-the-fly):** Контент сжимается веб-сервером непосредственно в момент запроса клиента.
    * **Плюсы:** Не требует предварительной подготовки файлов, всегда отдает актуальную версию.
    * **Минусы:** Потребляет ресурсы CPU (Central Processing Unit — центральный процессор) сервера на каждый запрос. Степень сжатия должна быть умеренной, чтобы не создавать излишнюю нагрузку. Является блокирующей операцией для воркера Nginx, что критично для HTTP/2 (HyperText Transfer Protocol version 2), где все запросы обрабатываются в рамках одного соединения. Это может привести к снижению RPS (Requests Per Second — запросов в секунду) и увеличению времени ответа.
2. **Статическое сжатие (pre-compressed):** Файлы сжимаются заранее (например, во время сборки проекта) и сохраняются рядом с оригиналом (`style.css.gz`, `script.js.br`). Веб-сервер отдает уже готовую версию.
    * **Плюсы:** Минимальная нагрузка на CPU (сжатие происходит один раз), можно использовать максимальную степень сжатия.
    * **Минусы:** Требует дополнительного этапа в процессе развертывания (CI/CD — Continuous Integration/Continuous Deployment).

Выбор подхода является компромиссом между нагрузкой на процессор и скоростью отдачи, что подробно описано в [тюнинге производительности Nginx](nginx_performance_tuning.md).

### Согласование контента (Content Negotiation)

Браузеры отправляют заголовок `Accept-Encoding` (например, `Accept-Encoding: gzip, deflate, br, zstd`), чтобы сообщить серверу о поддерживаемых алгоритмах. Nginx выбирает наиболее предпочтительный и отправляет ответ с заголовком `Content-Encoding` (например, `Content-Encoding: br`).

**Нюанс с HTTPS:** При использовании HTTPS (HyperText Transfer Protocol Secure) браузеры обычно поддерживают полный список алгоритмов. В незащищенных соединениях поддержка Brotli или ZSTD может отсутствовать.

## Практические сценарии

### Настройка Gzip

#### Динамическое сжатие Gzip

```nginx
server {
    # Включение динамического сжатия Gzip. В Angie — xip_on.
    gzip on;
    # Степень сжатия (1-9). Уровни 3-4 оптимальны для динамики.
    gzip_comp_level 3;
    # Отключение сжатия для устаревших версий Internet Explorer.
    gzip_disable "msie6";
    # MIME-типы (Multipurpose Internet Mail Extensions), подлежащие сжатию.
    gzip_types text/plain text/css application/json application/javascript application/x-javascript text/xml application/xml application/xml+rss text/javascript application/atom+xml application/rss+xml application/vnd.ms-fontobject application/x-font-ttf application/x-web-font application/x-font-opentype image/svg+xml;
    # Заголовок Vary: Accept-Encoding для корректного кэширования прокси-серверами.
    gzip_vary on;
    # Минимальный размер ответа (в байтах) для активации сжатия.
    gzip_min_length 1000;
    gzip_buffers 16 8k;
    gzip_http_version 1.1;
    gzip_proxied any;
}
```

#### Статическое сжатие Gzip

```nginx
server {
    location /static/ {
        # Отдача предварительно сжатых .gz файлов. В Angie — xip_static.
        gzip_static on;
    }
}
```

**Генерация файлов:**

```bash
# Использование zopfli для лучшего сжатия
zopfli -k -9 style.css
# -k: сохранить оригинал
# -9: максимальное сжатие
```

### Настройка Brotli

Требует модуля `ngx_brotli`. В Angie модуль часто предустановлен.

```nginx
server {
    brotli on;
    brotli_comp_level 5;
    brotli_types text/plain text/css application/json application/javascript application/x-javascript text/xml application/xml application/xml+rss text/javascript application/atom+xml application/rss+xml application/vnd.ms-fontobject application/x-font-ttf application/x-web-font application/x-font-opentype image/svg+xml;
    brotli_vary on;
    brotli_min_length 1000;

    # Статический режим (поиск файлов .br)
    brotli_static on;
}
```

### Настройка ZSTD

Требует модуля `ngx_http_zstd_filter_module`. Поддерживается современными браузерами (Chrome 123+, Edge).

```nginx
server {
    zstd on;
    zstd_comp_level 3; # От 1 до 22. 3-5 оптимально для динамики.
    zstd_types text/plain text/css application/json application/javascript application/x-javascript text/xml application/xml application/xml+rss text/javascript application/atom+xml application/rss+xml application/vnd.ms-fontobject application/x-font-ttf application/x-web-font application/x-font-opentype image/svg+xml;
    zstd_vary on;
    zstd_min_length 1000;

    zstd_static on;
}
```

## Дополнительная информация

### Сравнение алгоритмов

| Алгоритм | Степень сжатия | Скорость (динамика) | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Gzip** | Средняя | Средняя | Совместимость (Fallback) |
| **Brotli** | **Высокая** | Низкая (на высоких уровнях) | **Лучший для статики** |
| **ZSTD** | Высокая | **Очень высокая** | **Лучший для динамики (HTML, API)** |

**Оптимальная стратегия:**

1. **Для статики:** Предварительное сжатие Brotli (уровень 11).
2. **Для динамики:** ZSTD (уровни 4-5) или Brotli (уровни 4-5).
3. **Fallback:** Gzip для старых клиентов.

**Важно:** Если на сервере включены все три статических модуля (`gzip_static`, `brotli_static`, `zstd_static`), Nginx может отдать приоритет ZSTD перед Brotli, что не всегда выгодно по размеру файла. Рекомендуется не создавать `.zst` для статики, если есть `.br`.

### Инструменты тестирования

* **curl:** `curl -H "Accept-Encoding: br" -I https://example.com`
* **lzbench:** Тестирование скорости компрессии на реальных данных.
* **Браузерные DevTools:** Вкладка "Network", колонка "Content-Encoding".

### См. также

* [Тюнинг производительности Nginx](nginx_performance_tuning.md)
* [Обзор веб-сервера Angie](../../Angie/angie_overview.md)
* [Руководство по оптимизации Web Performance](../../Concepts/web_performance/overview.md)
