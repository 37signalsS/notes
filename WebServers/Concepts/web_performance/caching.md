# Кэширование как инструмент веб-производительности

## Определения

**Кэширование в веб-производительности** — стратегия снижения времени загрузки и минимизации сетевого трафика за счёт сохранения копий ресурсов (HTML, CSS, JS, изображения, шрифты) на промежуточных узлах. Это фундаментальный механизм оптимизации, позволяющий сократить время до отрисовки контента и снизить нагрузку на серверную инфраструктуру.

**HTTP Cache** — кэш, управляемый правилами RFC 9111 через заголовки `Cache-Control`, `ETag`, `Last-Modified`. Включает браузерный кэш (private) и разделяемые кэши (shared: CDN, обратный прокси).

**CDN (Content Delivery Network)** — распределённая сеть edge-серверов, кэширующая контент географически близко к пользователю. Управление TTL в CDN осуществляется через `s-maxage`, `CDN-Cache-Control` (RFC 9213), панель правил Edge.

**Reverse Proxy Cache** — кэш на уровне обратного прокси (Nginx, Angie, Varnish). Позволяет «срезать» запросы до бэкенда, агрегировать повторяющиеся запросы и защищать от пиковых нагрузок.

**Cache Hit Ratio (CHR)** — доля запросов, обслуженных из кэша. Рассчитывается как `Hits / (Hits + Misses) × 100`. Для статики целевой показатель >95%, для API >80%.

**Cache Stampede (Thundering Herd)** — эффект, при котором истечение TTL популярного объекта вызывает одновременную валидацию или запрос к Origin со стороны множества клиентов, перегружая инфраструктуру.

**Cache Partitioning** — партиционирование кэша браузером по двойному ключу `Top-level Site + Resource URL` (Chrome 111+, Safari 16.4+). Общие CDN-библиотеки кэшируются отдельно для каждого сайта.

**ARI (Automated Renewal Information)** — в контексте кэширования: механизм, при котором CDN или прокси может автоматически обновлять ресурс до истечения TTL на основе сигналов от Origin.

## Основные концепции

### Архитектура уровней кэширования

Веб-производительность использует пять уровней кэширования:

| Тип | Уровень | Хранилище | Управление |
| :--- | :--- | :--- | :--- |
| **Browser Cache** | Клиент | Диск / RAM | Заголовки `Cache-Control`, `ETag` |
| **Service Worker** | Клиент | Cache API / IndexedDB | Программный контроль (offline-first) |
| **Speculation Rules** | Клиент | Память браузера | Декларативный prerender/prefetch |
| **Proxy Cache** | Прокси | Диск / Shared Memory | `proxy_cache_*` (Nginx/Angie) |
| **CDN Cache** | Edge | Распределённая сеть PoP | Панель управления, `s-maxage` |

### Жизненный цикл объекта в кэше

1. **Запись (Store):** Клиент отправляет запрос. При отсутствии валидной копии запрос идёт к Origin.
2. **Формирование ключа (Key Generation):** CDN/прокси формирует уникальный ключ из `Method + URI + нормализованные заголовки`.
3. **Хранение (Retention):** Объект живёт в кэше в течение `max-age` (браузер) или `s-maxage` (CDN/прокси).
4. **Валидация (Validation):** При истечении TTL кэш отправляет условный запрос с `If-None-Match` / `If-Modified-Since`.
5. **Ответ Origin:** `304 Not Modified` (обновляется только `Age`) или `200 OK` (новое тело + новые валидаторы).
6. **Вытеснение (Eviction):** При превышении `max_size` или `inactive` кэш-менеджер удаляет старые записи по алгоритму LRU/LFU.

### Механизмы свежести и валидации

**Свежесть (Freshness):**
- `Cache-Control: max-age=<N>` — ресурс свежий N секунд.
- `Expires` — устаревший абсолютный заголовок, игнорируется при наличии `max-age`.
- `Age` — время пребывания в разделяемом кэше. Реальная свежесть: `max-age - Age`.
- **Эвристическое кэширование:** при отсутствии явных директив, но наличии `Last-Mified`, кэш сохраняет ресурс на 10% от интервала между датой генерации и последнего изменения (RFC 9111).

**Валидаторы:**
- **Strong ETag** — побайтовое совпадение (хэш контента). Пример: `ETag: "6868976968.0"`.
- **Weak ETag** — семантическое совпадение. Пример: `ETag: W/"v1.0"`. Используется при динамических элементах (дата в футере).
- **Last-Modified** — слабый валидатор, точность до секунды.

### Директивы Cache-Control

| Директива | Область | Описание |
| :--- | :--- | :--- |
| `public` | Ответ | Кэшируется любыми кэшами (браузер, CDN, прокси). |
| `private` | Ответ | Только для браузера. Разделяемые кэши обязаны игнорировать. |
| `no-cache` | Ответ | Кэшировать можно, но перед каждым использованием обязательна валидация. |
| `no-store` | Ответ | Полный запрет на сохранение в любом кэше. |
| `max-age=<N>` | Ответ | Время свежести в секундах. |
| `s-maxage=<N>` | Ответ | Аналог `max-age` только для разделяемых кэшей (CDN/прокси). |
| `stale-while-revalidate=<N>` | Ответ | Отдать устаревший контент, пока в фоне идёт обновление. |
| `stale-if-error=<N>` | Ответ | Отдать устаревший контент при ошибке Origin (5xx). |
| `immutable` | Ответ | Ресурс не изменится до истечения `max-age`. Исключает условные запросы при перезагрузке. |

### Заголовок Vary и ключ кэша

**Cache Key** — уникальная строка, по которой кэш находит ресурс. По умолчанию: `Method + URI`.

Заголовок **`Vary`** добавляет выбранные заголовки запроса в ключ кэша:
- `Vary: Accept-Encoding` — отдельные копии для `gzip`, `br`, несжатого.
- **Проблема:** нестандартные порядки заголовков (`gzip, deflate` vs `deflate, gzip`) создают разные ключи. Решение — нормализация на уровне CDN/прокси.
- `Vary: *` — фактически отключает кэширование.

### Партиционирование кэша браузера

С 2024–2026 годов Chrome, Safari и Firefox используют двойной ключ кэширования. Общие библиотеки с публичных CDN кэшируются отдельно для каждого сайта. Рекомендация для DevOps/SRE: размещать статику на собственном домене с `immutable` и fingerprinting, а не полагаться на общие CDN.

### Влияние на Web Vitals

- **LCP:** Мгновенная отдача Hero-image из кэша исключает фазу загрузки по сети (выигрыш 500–2000 мс).
- **INP:** Быстрая доставка JS-бандлов и шрифтов снижает блокировку Main Thread.
- **CLS:** Кэширование критического CSS и шрифтов предотвращает "прыжки" контента.

## Практические сценарии

### Сценарий 1: Вечное кэширование с Cache Busting

Для статических файлов (JS, CSS, изображения) с хэшем в имени:
- **Заголовок:** `Cache-Control: public, max-age=31536000, immutable`
- **Результат:** Браузер не проверяет файл на сервере в течение года. При обновлении кода меняется имя файла.

### Сценарий 2: Отказоустойчивый кэш (Resilient Cache)

Защита пользователя от временных сбоев бэкенда:
- **Заголовок:** `Cache-Control: max-age=3600, stale-if-error=86400`
- **Результат:** При недоступности сервера браузер использует кэшированную копию в течение суток.

### Сценарий 3: Защита от Cache Stampede (Thundering Herd)

Настройка Nginx/Angie при массовом запросе к некэшированному ресурсу:
- **Директивы:**
  - `proxy_cache_lock on;`
  - `proxy_cache_lock_timeout 5s;`
- **Результат:** Только первый запрос уходит на бэкенд, остальные ждут и получают ответ из кэша.

### Сценарий 4: Микрокэширование (Microcaching) для API

Защита динамических API от пиковых нагрузок:
- **Nginx:** `proxy_cache_valid 200 1s;`
- **Angie:** `proxy_cache_valid 200 1s;`
- **Результат:** При 10 000 RPS бэкенд получает только 1 запрос в секунду.

### Сценарий 5: Кэширование с учётом компрессии (Vary: Accept-Encoding)

Правильная отдача сжатого контента (Brotli/Zstd) через кэширующий прокси:
- **Заголовок:** `Vary: Accept-Encoding`
- **Результат:** Кэш хранит разные копии для разных алгоритмов сжатия, предотвращая отдачу неподдерживаемого формата.

### Сценарий 6: Очистка кэша по Surrogate Keys (тегам)

Для массовой инвалидации в CDN:
- **Cloudflare API:**
  ```bash
  curl -X POST "https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/purge_cache" \
       -H "Authorization: Bearer {TOKEN}" \
       -H "Content-Type: application/json" \
       --data '{"tags":["product_laptops","brand_apple"]}'
  # → {"success":true,"errors":[],"messages":[],"result":{"id":"..."}}
  ```

### Сценарий 7: Инвалидация по URL (Cache Busting)

Альтернатива Purge API — изменение URL при изменении контента:
- **Методы:** Hash-имя файла (`style.abc123.css`), Query-параметр версии (`/api/data?v=2.1.0`), Directory-based (`/v2/static/style.css`).
- **Результат:** Исключается необходимость в инвалидации — старый URL остаётся в кэше, новые запросы идут по новому URL.

## Операции и команды

### Диагностика кэша через curl

```bash
# Получение заголовков кэширования
curl -sI https://example.com/style.css | grep -iE "cache-control|age|etag|vary|last-modified"
# → cache-control: public, max-age=31536000, immutable
# → age: 300
# → etag: "6868976968.0"
# → vary: Accept-Encoding

# Проверка условного запроса (валидация)
ETAG=$(curl -sI https://example.com/api/data | grep -i etag | tr -d '\r' | awk '{print $2}')
curl -sI -H "If-None-Match: $ETAG" https://example.com/api/data
# → HTTP/1.1 304 Not Modified

# Проверка реального TTL
# Real TTL = max-age - Age
curl -sI https://example.com/style.css | grep -iE "age|cache-control"
# → age: 300
# → cache-control: public, max-age=3600
# Реальный TTL = 3600 - 300 = 3300 сек
```

### Очистка кэша в Nginx/Angie

```bash
# Требуется модуль ngx_cache_purge
# Конфигурация location:
# location ~ /purge(/.*) {
#     proxy_cache_purge my_cache "$scheme$host$1";
# }

# Очистка конкретного URL
curl -X GET "http://localhost/purge/api/data"
# → 200 OK (если успешно)

# Проверка после purge
curl -sI "http://localhost/api/data" | grep -i age
# → age: 0 (кэш сброшен)
```

### Просмотр состояния кэша Nginx/Angie

```bash
# Статистика shared memory zone
curl http://localhost/status_cache
# → my_cache:
#     Size: 1.2G
#     Keys: 15234
#     Hit: 45230
#     Miss: 1234
#     Hit Ratio: 97.3%

# Проверка размера кэша на диске
du -sh /var/cache/nginx/proxy_cache/
# → 1.2G    /var/cache/nginx/proxy_cache/
```

### Очистка кэша CDN (Cloudflare)

```bash
# Очистка одного файла
curl -X POST "https://api.cloudflare.com/client/v4/zones/{ZONE_ID}/purge_cache" \
     -H "Authorization: Bearer {TOKEN}" \
     -H "Content-Type: application/json" \
     --data '{"files":["https://example.com/index.html"]}'
# → {"success":true,"errors":[],"messages":[],"result":{"id":"..."}}

# Проверка Age после purge
curl -sI https://example.com/index.html | grep -i age
# → age: 0
```

### Мониторинг метрик кэша

```bash
# Nginx/Angie — вывод X-Cache-Status
curl -sI https://example.com/api/data | grep -i x-cache-status
# → X-Cache-Status: HIT
# → X-Cache-Status: MISS
# → X-Cache-Status: BYPASS
# → X-Cache-Status: EXPIRED

# CDN — заголовок Cache-Status (RFC 9211)
curl -sI https://example.com/api/data | grep -i cache-status
# → cache-status: Cloudflare-CDN; hit; ttl=345
# → cache-status: Cloudflare-CDN; miss
```

### Управление кэшем через CLI (Nginx)

```bash
# Перезагрузка конфигурации кэша
nginx -t && systemctl reload nginx

# Принудительная инвалидация через ngx_cache_purge
curl -X PURGE "http://localhost/api/v1/users/123"
# → 200 OK

# Проверка статуса кэша (если настроен stub_status)
curl http://localhost/nginx_status
# → Active connections: 1
# → server accepts handled requests
# → 100 100 200
```

## Диагностика ошибок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Низкий Cache Hit Ratio** | Много `MISS` в `X-Cache-Status`, высокая нагрузка на Origin | `curl -sI URL \| grep -iE "cache-status\|age\|x-cache-status"` | Увеличить TTL, включить `stale-while-revalidate`, проверить Cache Key и `Vary` |
| **Stale Content** | Пользователи видят устаревший контент | `curl -sI URL \| grep age` — возраст превышает `max-age` | Уменьшить TTL, настроить SWR, использовать Purge API |
| **Cache Stampede** | Всплеск нагрузки на Origin после истечения TTL | Мониторинг Origin (CPU, RPS) | Включить `proxy_cache_lock`, добавить Jitter TTL, настроить `stale-while-revalidate` |
| **Incorrect Cache Key** | Один URL кэшируется под разными ключами | Проверить заголовок `Vary` и параметры запроса | Нормализовать query-параметры, унифицировать `Accept-Encoding` |
| **Cache Poisoning** | CDN отдает вредоносный контент | Проверить HTTP-заголовки ответа | Включить Strict URL Normalization, исключить нерелевантные заголовки из Cache Key |
| **Double Caching** | Обновление на CDN не доходит до браузера | Сравнить `max-age` в браузере и CDN | Использовать `s-maxage` для CDN, `max-age` для браузера |
| **Purge не работает** | Контент не обновляется после API-запроса | Проверить статус API-ответа, URL | Проверить права API, URL, повторить запрос |
| **Медленная инвалидация** | Контент обновляется через минуты | Проверить PoP географии | Перейти на Cache Busting или CDN с <200 мс инвалидацией |
| **Vary: * отключает кэш** | Все запросы проходят как MISS | `curl -sI URL \| grep -i vary` | Убрать `Vary: *`, использовать конкретные заголовки |

## Рекомендации

### Базовые правила

1. **Используйте `Cache-Control` вместо `Expires`:** `Expires` устарел и игнорируется при наличии `max-age`.
2. **Разделяйте TTL для браузера и CDN:** `max-age` для браузера (короткий), `s-maxage` для CDN (длинный).
3. **Версионируйте статику:** Используйте fingerprinting (хеш в имени файла) + `Cache-Control: public, max-age=31536000, immutable`.
4. **Обязательно добавляйте `Vary: Accept-Encoding`:** Без него кэш может отдать сжатый контент клиенту, который его не поддерживает.
5. **Используйте strong ETag для статики:** Это позволяет эффективно валидировать ресурсы без повторной передачи тела.
6. **Настройте `stale-while-revalidate` и `stale-if-error`:** Это обеспечивает отзывчивость при обновлениях и отказоустойчивость при сбоях Origin.
7. **Кэшируйте ошибки:** `proxy_cache_valid 404 10s;` защищает Origin от повторных запросов к несуществующим ресурсам.
8. **Нормализуйте Cache Key:** Исключайте из ключа нерелевантные заголовки (Cookie, User-Agent), сортируйте query-параметры.
9. **Избегайте `Cache-Control: no-store` для чувствительных данных там, где можно использовать `private`:** `no-store` полностью блокирует кэш, `private` разрешает кэширование только в браузере.
10. **Валидируйте заголовки после деплоя:** Проверяйте, что пользователи видят актуальный контент, а метрики (CHR, TTFB) улучшились.

### Для DevOps/SRE/SysAdmin

- **Offload Ratio:** Процент запросов, обработанных кэшем. Рост Offload напрямую снижает затраты на инфраструктуру и нагрузку на Origin.
- **Cache Purging в CI/CD:** Интегрируйте очистку кэша в пайплайн после деплоя фронтенда. Используйте Purge API или Cache Busting.
- **Мониторинг кэша:** Отслеживайте `X-Cache-Status`, `Age`, `Cache-Status`. Алерты при `Hit Ratio < 80%` или `Age > s-maxage`.
- **Cache Warming:** После перезапуска прокси/CDN наполняйте кэш популярными ресурсами (bulk load через `curl` или инструменты CDN).
- **Мониторинг негативного кэширования:** Убедитесь, что 404/5xx кэшируются на короткий срок, чтобы защитить Origin от DoS.
- **Использование CDN-Cache-Control:** Разделяйте политики для браузера и CDN, когда `s-maxage` недостаточно (RFC 9213).
- **Проверка нормализации Vary:** Убедитесь, что CDN/прокси нормализуют заголовки `Accept-Encoding` перед формированием ключа кэша.
- **Ограничение размера кэша:** Устанавливайте `max_size` и `inactive` для предотвращения заполнения диска. Мониторьте использование диска через `du -sh`.
- **Аудит кэширования:** Регулярно проверяйте заголовки ответов через `curl -sI` на разных endpointах.

## Дополнительная информация

### Связанные файлы

- [HTTP-кэширование: Механизмы и управление](../../../Networking/Protocols/HTTP/http_caching.md) — RFC 9111, валидация, Cache-Control, ETag, Range-запросы.
- [Кэширование: Обзор](../../../Concepts/Caching/caching_overview.md) — типы архитектур, метрики, Redis/Memcached, TTL, инвалидация.
- [Паттерны кэширования](../../../Concepts/Caching/caching_patterns.md) — Cache-aside, Read-through, Write-through, Write-back, CDC.
- [Политики кэширования и инвалидация в CDN](../../../Networking/CDN/cdn_caching_and_invalidation.md) — CDN-специфичные директивы, Purge API, Surrogate Keys.
- [Клиентское кэширование в Nginx](../../Nginx/Performance/Caching/client_caching.md) — настройка заголовков в конфиге Nginx.
- [Кэширование прокси в Nginx](../../Nginx/Performance/Caching/proxy_caching.md) — `proxy_cache_*` директивы, зоны, ключи.
- [Web Vitals](./web_vitals.md) — влияние кэширования на LCP, INP, CLS.
- [Upstream Keepalive и Connection Pooling](./upstream_keepalive_and_pooling.md) — пул соединений с бэкендом.
- [Circuit Breaker и Degradation](./circuit_breaker_and_degradation.md) — fallback на кэш при ошибках.
- [Zero-Downtime Deployment](./zero_downtime_deployment.md) — cache warming после reload.
- [Structured Logging для Performance](./structured_logging_for_performance.md) — аудит кэша через логи.

### RFC и спецификации

- **RFC 9111** — HTTP-кэширование (обновлённый RFC 7234).
- **RFC 9211** — Cache-Status заголовок.
- **RFC 9213** — CDN-Cache-Control заголовок.
- **RFC 5861** — `stale-while-revalidate`, `stale-if-error`.
- **RFC 9773** — ARI (Automated Renewal Information) — механизм ускоренного обновления сертификатов, адаптированный для CDN-инвалидации.

### Официальные ресурсы

- [Nginx Proxy Cache](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_cache)
- [Angie Cache](https://angie.software/en/advanced/http.html#proxy_cache)
- [MDN: Cache-Control](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Cache-Control)
- [Web.dev: Caching](https://web.dev/caching/)
