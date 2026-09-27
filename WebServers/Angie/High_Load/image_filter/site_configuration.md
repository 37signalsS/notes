# Модуль image_filter в Angie: конфигурация фронтенда

## Определения

**Image Front (Фронтенд)** — высокопроизводительный прокси-сервер, выполняющий SSL/TLS termination, интеллектуальный выбор формата изображения, управление кэшем и защиту системы от перегрузок. Является единственным публичным интерфейсом между клиентами и внутренним конвейером обработки изображений.

**Адаптивная доставка (Adaptive Image Delivery)** — метод отдачи наиболее эффективного формата изображения (AVIF, WebP или HEIC) в зависимости от возможностей браузера, определяемых через заголовок `Accept`. Позволяет сократить вес страницы на 30–50% без потери визуального качества.

**Согласование контента (Content Negotiation)** — процесс выбора формата ответа на основе анализа заголовка `Accept` запроса. В Angie реализуется через директиву `map`, которая сопоставляет возможности клиента с суффиксом файла или параметрами конвертации.

**Ключ кэша (Cache Key)** — строковое значение, формируемое из переменных запроса, по которому Angie определяет уникальность объекта в кэше. При динамической трансформации в ключ ОБЯЗАТЕЛЬНО должны входить параметры ресайза, формат и качество сжатия.

**Отравление кэша (Cache Poisoning)** — ситуация, при которой в кэш попадает неверный объект (например, изображение в формате AVIF для клиента, поддерживающего только JPEG), из-за некорректного ключа кэша или отсутствия заголовка `Vary: Accept`.

**Thundering Herd (Эффект «стада бизонов»)** — одновременный наплыв множества запросов на один и тот же MISS-объект, что создает пиковую нагрузку на бэкенд. Для предотвращения используется `proxy_cache_lock`.

**Edge Server (Edge-узел)** — сервер, расположенный на границе сети (ближе к клиенту), отвечающий за SSL termination, ACL, WAF и кэширование. В контексте image_filter — это внешний фронтенд, принимающий запросы из интернета.

## Базовые концепции

### Логика выбора формата (Content Negotiation)

Для реализации адаптивности в Angie используется директива `map`, которая анализирует заголовок `Accept` и подготавливает переменные для маршрутизации. Это позволяет минимизировать объем передаваемого трафика без потери качества.

```nginx
# Определение оптимального формата на основе заголовка Accept
map $http_accept $img_suffix {
    "~*avif"  ".avif";
    "~*webp"  ".webp";
    "~*heic"  ".heic";
    default   "";
}

# Определение префикса для внутреннего проксирования к фильтру
map $http_accept $img_prefix {
    "~*avif"  "/convert/avif";
    "~*webp"  "/convert/webp";
    "~*heic"  "/convert/heic";
    default   "/resize";
}
```

#### Особенности заголовка Accept и q-values

Реальные браузеры отправляют сложные заголовки `Accept` с весами качества (q-values), например:
```
Accept: image/avif,image/webp,image/apng,image/*,*/*;q=0.8
```

Директива `map` в Angie обрабатывает такие заголовки последовательно сверху вниз. Первое совпадение определяет формат. Важные нюансы:
- **Safari 16+** отправляет `image/*` вместо `image/avif`, но не декодирует AVIF напрямую. Если в `map` стоит `~*avif` перед `default`, Safari получит AVIF, который не сможет отобразить. Для Safari используйте `map` с проверкой User-Agent в дополнение к `Accept` или ограничьте AVIF явными браузерами.
- **Chrome/Firefox** корректно указывают `image/avif` при поддержке.
- **Приоритет `webp` над `avif`:** Если вы хотите отдавать WebP вместо AVIF для определенных клиентов (например, из-за высокой нагрузки), поменяйте порядок строк в `map`.

### Значение заголовка Vary

При использовании адаптивной доставки по одному и тому же URL (например, `photo.jpg` может вернуть AVIF или WebP), необходимо обязательно добавлять заголовок `add_header Vary "Accept";`. Это критически важно для корректной работы промежуточных прокси-серверов и CDN, так как сообщает им, что содержимое ответа зависит от возможностей клиента.

**Проблема без Vary:**
1. Клиент A (Chrome, поддерживает AVIF) запрашивает изображение → получает AVIF.
2. CDN кэширует ответ под ключом `photo.jpg`.
3. Клиент B (Safari без AVIF) запрашивает то же изображение → CDN отдает AVIF из кэша → Safari не отображает изображение.

### Архитектура фронтенда и границы ответственности

Фронтенд является **единственным публичным интерфейсом** системы обработки изображений. Все остальные компоненты (внутренний фильтр, хранилище) изолированы от внешней сети.

**Обязательные функции фронтенда:**
- **SSL/TLS termination:** Дешифрование HTTPS, управление сертификатами, OCSP stapling.
- **ACL:** Ограничение доступа по IP,geo, WAF-правилам.
- **Content Negotiation:** Выбор формата через `map` на основе `Accept`.
- **Кэширование:** Хранение уже трансформированных результатов с корректным ключом.
- **Защита от DoS:** `limit_req`, `limit_conn`, `proxy_cache_lock`.
- **Мониторинг:** `status_zone`, логирование, метрики.

**Запрещено на фронтенде:**
- Прямой доступ к оригиналам изображений (все запросы к оригиналам должны идти через внутренний сервер).
- Выполнение `image_filter` на внешнем уровне (это приведет к блокировке воркеров и отказу в обслуживании для всех клиентов).

### Антипаттерн: кэширование до трансформации

Использование `image_filter` и `proxy_cache` в одном `location` является антипаттерном, так как Angie кэширует ответ *до* его модификации фильтром. Для кэширования именно **результата обработки** (например, уже сжатого AVIF) необходимо использовать двухслойную схему.

```
Клиент → [Фронтенд: SSL termination + ACL + Content Negotiation]
            ↓
            MISS → [Внутренний прокси: Трансформация]
                      ↓
                      [Хранилище: оригиналы]
                      ↓
                 [image_filter: Resize/Convert]
                      ↓
            HIT ← [Кэширование результата]
            ↓
        Клиент (AVIF/WebP/JPEG)
```

### Конструкция ключа кэша

Ключ кэша на фронтенде должен включать все параметры, влияющие на выходное изображение:

```nginx
# Корректный ключ для адаптивной доставки
proxy_cache_key "$scheme$request_method$host$uri$is_args$args$http_accept";
```

**Обязательные компоненты ключа:**
- `$scheme$request_method$host` — базовая часть для различения хостов и методов.
- `$uri` — путь к изображению.
- `$is_args$args` — параметры запроса (ширина, высота и т.д.).
- `$http_accept` — формат (AVIF/WebP/JPEG), определяемый через `map`.

**Опасности неполного ключа:**
- Без `$http_accept` в ключе первый запрос от AVIF-совместимого браузера заполнит кэш, и все последующие клиенты (включая Safari без AVIF) получат неправильный формат. Это **Cache Poisoning**.
- Без `$is_args$args` запросы с разными параметрами `w`/`h` будут кэшироваться под одним ключом.

### Защита от Thundering Herd

При массовом запросе одного и того же изображения (например, после публикации на главной странице) dozens воркеров одновременно могут отправить запрос к внутреннему фильтру. `proxy_cache_lock` решает эту проблему:

```nginx
# Первый запрос генерирует изображение, остальные ждут
proxy_cache_lock on;
proxy_cache_lock_timeout 5s;
proxy_cache_lock_age 10s;
```

Включение `proxy_cache_use_stale error timeout updating` позволяет отдавать старую версию из кэша, пока внутренний фильтр занят генерацией новой. Это радикально снижает Tail Latency.

### Фоллбэк-цепочка форматов

Для максимальной отказоустойчивости используйте `try_files` с проверкой нескольких вариантов формата:

```nginx
# Проверка: AVIF → WebP → HEIC → оригинал
location ~* ^/img/(?<w>\d+)x(?<h>\d+)/(?<file>.+)$ {
    try_files $uri$img_suffix $uri =404;
    add_header Vary "Accept";
    expires 30d;
}
```

## Практические сценарии

### Сценарий: Полнофункциональный фронтенд с кэшированием

Этот пример демонстрирует архитектурно верный подход к доставке изображений с использованием внутреннего сервера фильтрации. Ключевым моментом является включение формата в ключ кэша.

```nginx
server {
    listen 443 ssl http2;
    server_name images.example.com;

    # TLS 1.3 + современные шифры
    ssl_protocols TLSv1.3 TLSv1.2;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:50m;
    ssl_session_tickets off;
    ssl_stapling on;
    ssl_stapling_verify on;

    # HSTS (только для production)
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;

    # Мониторинг фронтенда
    status_zone image_frontend;

    # Основная локация для запросов
    location ~* ^/img/(?<w>\d+)x(?<h>\d+)/(?<file>.+)$ {
        add_header Vary "Accept";
        add_header X-Cache-Status $upstream_cache_status;

        # Ключ кэша ОБЯЗАТЕЛЬНО должен включать формат ($img_suffix)
        proxy_cache image_cache;
        proxy_cache_key "$scheme$request_method$host$uri$is_args$args$img_suffix";

        # Защита от эффекта "стада бизонов"
        proxy_cache_lock on;
        proxy_cache_lock_timeout 5s;

        # Фоновое обновление кэша
        proxy_cache_use_stale error timeout updating;
        proxy_cache_background_update on;

        # Таймауты для тяжелых операций
        proxy_connect_timeout 2s;
        proxy_send_timeout 5s;
        proxy_read_timeout 10s;

        # Проксирование на внутренний сервер (фильтр)
        proxy_pass http://unix:/var/run/angie_img_filter.sock:/img/$w/$h/$file;

        proxy_cache_valid 200 30d;
        expires 30d;
    }
}
```

### Сценарий: Статическая раздача с фоллбэком

Используется, если оптимизированные версии уже существуют на диске (например, созданы через `proxy_store` на бэкенде или сторонним скриптом).

```nginx
server {
    listen 443 ssl http2;
    server_name static.example.com;

    ssl_protocols TLSv1.3 TLSv1.2;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;

    root /var/www/images/optimized;
    status_zone image_static_frontend;

    location ~* ^/img/(?<w>\d+)x(?<h>\d+)/(?<file>.+)$ {
        add_header Vary "Accept";
        # Последовательный поиск: .avif -> .webp -> .heic -> оригинал
        try_files $uri$img_suffix $uri =404;

        expires 365d;
        add_header Cache-Control "public, immutable";
    }
}
```

### Сценарий: ACL и изоляция сети

Ограничение доступа к фронтенду доверенными IP и защита внутреннего фильтра.

```nginx
server {
    listen 443 ssl http2;
    server_name images.example.com;

    # Ограничение по IP (WAF/Cloudflare IP ranges)
    include /etc/angie/conf.d/cloudflare-ips.conf;
    deny all;

    location / {
        proxy_pass http://internal_upstream;
    }
}

# Внутренний upstream — только для доверенных адресов
upstream internal_upstream {
    server 127.0.0.1:8081;
    server unix:/var/run/angie_img_filter.sock;
}
```

### Сценарий: Мониторинг фронтенда и алертинг

Включение `status_zone` позволяет отслеживать эффективность кэширования и защиту в реальном времени.

```nginx
# Фронтенд с API мониторинга
server {
    listen 127.0.0.1:8080;
    server_name localhost;

    location /status {
        api /status/;
        allow 127.0.0.1;
        deny all;
    }

    location /p8s {
        prometheus;
    }
}
```

**Ключевые метрики фронтенда:**
- **Hit Ratio:** Процент запросов, обслуженных из кэша. Для изображений целевое значение > 95%.
- **Bypass Rate:** Количество запросов, прошедших мимо кэша.
- **Stale Ratio:** Доля устаревшего контента в отдачах.
- **Bandwidth:** Объем отданного контента. Резкий рост может указывать на отравление кэша.

**Валидация:**
```bash
# Проверка статуса зоны фронтенда
curl -s http://127.0.0.1:8080/api/6/http/status_zones/image_frontend | jq '.responses | {time: .time, codes: .codes}'

# Проверка Prometheus-метрик
curl -s http://127.0.0.1:8080/p8s | grep -E "angie_zone|image_frontend"
```

### Сценарий: CI/CD валидация конфигурации

Скрипт для автоматической проверки конфигурации фронтенда перед деплоем.

```bash
#!/bin/bash
# validate-frontend.sh — CI/CD валидация конфигурации фронтенда
set -euo pipefail

CONF="/etc/angie/conf.d/image_frontend.conf"
AN_GIE_API="http://127.0.0.1:8080"
TEST_URL="https://images.example.com/resize/400x300/photo.jpg"

# 1. Синтаксис
angie -t -c /etc/angie/angie.conf

# 2. Проверка заголовка Vary
vary=$(curl -sI "$TEST_URL" | grep -i "^vary:" | awk '{print $2}' | tr -d '\r')
if [[ "$vary" != *"Accept"* ]]; then
    echo "FAIL: отсутствует Vary: Accept"
    exit 1
fi

# 3. Проверка кэширования
cache=$(curl -sI "$TEST_URL" -H "Accept: image/avif" | grep -i "^x-cache-status:" | awk '{print $2}' | tr -d '\r')
if [[ "$cache" != "MISS" && "$cache" != "HIT" ]]; then
    echo "FAIL: кэширование не работает (статус: $cache)"
    exit 1
fi

# 4. Проверка content negotiation
content_type=$(curl -sI "$TEST_URL" -H "Accept: image/avif" | grep -i "^content-type:" | awk '{print $2}' | tr -d '\r')
if [[ "$content_type" != "image/avif" ]]; then
    echo "FAIL: AVIF не отдается (Content-Type: $content_type)"
    exit 1
fi

# 5. Проверка метрик фронтенда
zone=$(curl -s "$AN_GIE_API/http/status_zones/image_frontend")
if [[ -z "$zone" ]]; then
    echo "FAIL: status_zone image_frontend не найдена"
    exit 1
fi

echo "PASS: валидация фронтенда успешна"
```

### Сценарий: Zero-downtime reload фронтенда

Процедура перезагрузки без прерывания текущих соединений.

```bash
# 1. Проверка конфигурации
sudo angie -t

# 2. Перезагрузка без прерывания соединений
sudo systemctl reload angie

# 3. Проверка нового воркера
ps aux | grep angie | wc -l
# → Должен увеличиться на 1 (новый мастер)

# 4. Проверка метрик
curl -s http://127.0.0.1:8080/api/6/http/status_zones/image_frontend | jq '.responses'
```

### Сценарий: Логирование с метриками кэша

Настройка access log для анализа поведения клиентов и эффективности кэширования.

```nginx
log_format cache_metrics '$remote_addr - $remote_user [$time_local] '
    '"$request" $status $body_bytes_sent '
    '"$http_referer" "$http_user_agent" '
    'cache=$upstream_cache_status '
    'format=$img_suffix '
    'latency=$request_time';

server {
    access_log /var/log/angie/images.access.log cache_metrics;

    location ~* ^/img/ {
        proxy_cache image_cache;
        proxy_cache_key "$scheme$request_method$host$uri$is_args$args$http_accept";

        add_header X-Cache-Status $upstream_cache_status always;
    }
}
```

**Валидация:**
```bash
# Анализ hit ratio за час
awk -F'cache=' '$2 ~ /HIT/ { hit++ } END { print "Hit ratio:", hit/NR }' /var/log/angie/images.access.log

# Самые популярные размеры
awk '{print $7}' /var/log/angie/images.access.log | grep -oE '[0-9]+x[0-9]+' | sort | uniq -c | sort -rn | head -10
```

### Сценарий: Health check и readiness probe

Настройка endpoints для проверки работоспособности фронтенда оркестратором или балансировщиком.

```nginx
server {
    listen 127.0.0.1:8081;
    server_name localhost;

    # Readiness probe: проверяет доступность кэша и внутреннего фильтра
    location /ready {
        access_log off;
        return 200 "ready\n";
        add_header Content-Type text/plain;
    }

    # Liveness probe: проверяет, что Angie отвечает
    location /health {
        access_log off;
        stub_status;
        allow 127.0.0.1;
        deny all;
    }
}
```

**Валидация:**
```bash
# Проверка readiness
curl -s http://127.0.0.1:8081/ready
# → ready

# Проверка liveness
curl -s http://127.0.0.1:8081/health
# → Active connections: 1 server accepts handled requests
# → 1 2 3
```

### Сценарий: Graceful Degradation при перегрузке фронтенда

Настройка поведения системы при превышении лимитов на фронтенде.

```nginx
http {
    # Ограничение запросов к тяжелым операциям
    limit_req_zone $binary_remote_addr zone=frontend_limit:10m rate=100r/s;

    server {
        listen 443 ssl http2;
        server_name images.example.com;

        location ~* ^/img/ {
            limit_req zone=frontend_limit burst=200 nodelay;
            limit_req_status 503;

            # При превышении лимита — статический placeholder
            error_page 503 = /static/placeholder.png;

            proxy_cache image_cache;
            proxy_cache_key "$scheme$request_method$host$uri$is_args$args$http_accept";
            proxy_pass http://unix:/var/run/angie_img_filter.sock:/img$uri;
        }

        # Fallback: placeholder
        location = /static/placeholder.png {
            internal;
            root /var/www/images/static;
            expires 1h;
        }
    }
}
```

**Валидация:**
```bash
# При превышении 100 r/s — 503, placeholder
ab -n 1000 -c 100 https://images.example.com/resize/400x300/photo.jpg
# grep "503" /var/log/angie/images.access.log
```

## Операции и команды

```bash
# Деплой/релиз: проверка синтаксиса + reload без простоя
sudo angie -t && sudo systemctl reload angie

# Нагрузочный прогон после изменений
ab -n 1000 -c 100 https://images.example.com/resize/400x300/photo.jpg
grep "503" /var/log/angie/images.access.log    # пусто — лимиты не срабатывают

# Проверка, что limit_req зона активна
curl -s http://127.0.0.1:8080/api/6/http/limit_reqs/image_ops/ | jq

# Проверка, что фронт кэширует адаптивные форматы
curl -sI -H "Accept: image/avif" https://images.example.com/resize/400x300/photo.jpg | grep X-Cache-Status
```

## Устранение неисправностей (Troubleshooting)

| Симптом | Причина | Решение |
|:---|:---|:---|
| 503 под нагрузкой (placeholder) | `limit_req` срабатывает на легитимном трафике | Поднять `rate`/`burst`; проверить, что здоровые клиенты не задеваются |
| Разные браузеры получают разный формат | `$http_accept` не в кэш-ключе | Добавить `$http_accept` в `proxy_cache_key` (см. Доп. информацию) |
| Сонированный контент после изменения оригинала | Нет инвалидации кэша | Уменьшить TTL, настроить purge или `proxy_cache_use_stale` |
| Placeholder долго не заменяется настоящей картинкой | `@empty` fallback кэшируется слишком долго | Убрать `expires`/сократить TTL для fallback-места |

## Лучшие практики

1.  **Адаптивная раздача** требует `Vary: Accept` + `$http_accept` в ключе кэша — без этого кэш ядовит.
2.  **`proxy_cache_use_stale error timeout updating;`** снижает время ответа, отдавая старое, пока генерируется новое (см. Доп. информацию).
3.  **`status_zone` на фронте** — следить за `Cache Hit Ratio` (в Angie Pro — на дашборде Console).
4.  **Лимит запросов + placeholder** = защита от CPU DoS без «чёрной страницы» для клиентов: троттлинг, а не отказ сервиса.

## Дополнительная информация

### Оптимизация и мониторинг кэша

- **Ключ кэша (proxy_cache_key):** Отсутствие `$http_accept` в ключе приведет к «отравлению» кэша: если первым запросит AVIF-совместимый браузер, этот файл будет отдан всем последующим клиентам, включая те, что не поддерживают AVIF.
- **Старые копии (proxy_cache_use_stale):** Рекомендуется настройка `proxy_cache_use_stale error timeout updating;`. Это позволяет отдавать старую версию изображения из кэша, пока внутренний фильтр занят генерацией новой, что радикально снижает время ответа для пользователя.
- **Аналитика (status_zone):** Включение `status_zone` на уровне фронтенда позволяет отслеживать `Cache Hit Ratio`. В Angie Pro эти данные можно визуализировать на дашборде для контроля эффективности адаптивной доставки.

### Безопасность и целостность

Использование параметров размера напрямую из URL без проверки создает риск CPU DoS-атак. Обязательно ограничивайте допустимые комбинации размеров или используйте модуль `secure_link` для проверки подписи запроса. Подробности в разделе [безопасности](./security.md).

### Типовые проблемы фронтенда и решения

| Проблема | Симптом | Причина | Решение |
|:---------|:--------|:--------|:--------|
| Отравление кэша | Safari получает AVIF | Отсутствует `Vary: Accept` или `$http_accept` в ключе | Добавить заголовок и расширить ключ |
| Низкий Hit Ratio | >50% MISS | Слишком короткий `inactive` или некорректный ключ | Проверить ключ, увеличить `inactive` |
| Долгий холодный старт | Angie долго запускается | Отсутствует `file=` в `proxy_cache_path` | Настроить Persistence (см. [кэширование](./caching.md)) |
| TLS handshake failures | 525, SSL errors | Неверные шифры или истекший сертификат | Проверить `ssl_protocols`, `ssl_ciphers`, срок действия cert |
| Отказ внутреннего фильтра | 502 Bad Gateway | Внутренний сервер недоступен | Проверить socket, `limit_req`, ресурсы бэкенда |
| High Latency на фронтенде | P95 > 1s | Утизация CPU фронтенда или проблемы с сетью | Проверить `mpstat`, `ss -s`, network throughput |

### Очистка и откат конфигурации

```bash
# Перед изменением конфигурации создайте бэкап
cp /etc/angie/conf.d/image_frontend.conf /etc/angie/conf.d/image_frontend.conf.bak

# Если новая конфигурация вызывает проблемы, верните бэкап
cp /etc/angie/conf.d/image_frontend.conf.bak /etc/angie/conf.d/image_frontend.conf
angie -t && systemctl reload angie

# Очистка кэша при необходимости
curl -X PURGE https://images.example.com/resize/400x300/photo.jpg
```

### См. также

- [Безопасность и защита от DoS](./security.md)
- [Конфигурация внутреннего фильтра](./filter_configuration.md)
- [Стратегии кэширования](./caching.md)
