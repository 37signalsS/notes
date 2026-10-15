# CDN — Политики кэширования и инвалидации

## Определения

- **Кэширование в CDN**: Процесс сохранения копий контента на географически распределенных серверах (PoP) для ускорения доставки и снижения нагрузки на источник (Origin).
- **Инвалидация кэша (Cache Invalidation/Purge)**: Механизм принудительного удаления или пометки контента как «устаревшего» в кэше CDN, что заставляет сеть запросить свежую версию с исходного сервера.
- **Cache-Status (RFC 9211)**: Стандартный HTTP-заголовок, предоставляющий детальную информацию о том, как запрос был обработан кэшем (HIT, MISS, EXPIRED, STALE, BYPASS). В 2026 году заменил проприетарные заголовки вроде `X-Cache`.
- **CDN-Cache-Control (RFC 9213)**: Специализированный заголовок, позволяющий задавать политики кэширования специально для CDN-провайдеров, не влияя на поведение кэша в браузерах.
- **Surrogate Keys (Cache Tags)**: Метод логической группировки объектов в кэше с помощью меток (тегов) для их массовой инвалидации одним API-запросом.
- **Cache Key (Ключ кэша)**: Уникальный идентификатор ресурса в системе кэширования. Обычно формируется как хеш от URL, но может включать заголовки, куки и параметры запроса.
- **Origin Shielding**: Дополнительный уровень кэширования (Regional Tier) между пограничными узлами и источником, минимизирующий количество запросов к Origin при пропуске кэша (Cache Miss) на границе.
- **ETag (Entity Tag)**: Уникальный идентификатор конкретной версии ресурса, возвращаемый сервером в ответе. Используется для условных запросов (Conditional Requests) — кэш передаёт ETag обратно серверу через заголовок `If-None-Match` для проверки актуальности копии.
- **If-None-Match**: Заголовок HTTP-запроса, содержащий ETag, полученный ранее. Если сервер определяет, что ресурс не изменился, он возвращает `304 Not Modified` без тела ответа, что экономит пропускную способность и ускоряет обновление кэша.
- **If-Modified-Since**: Заголовок HTTP-запроса с датой последней модификации ресурса. Сервер проверяет, менялся ли файл после указанной даты, и возвращает `304 Not Modified` если нет.
- **Last-Modified**: Заголовок HTTP-ответа с датой последнего изменения ресурса. Считается «слабым» валидатором (RFC 9111), так как имеет точность до секунды.
- **Cache Busting**: Стратегия принудительного обновления кэша клиентов и CDN через изменение URL ресурса (хеш в имени файла, версионный суффикс) вместо инвалидации по заголовкам.
- **Negative Caching**: Кэширование ответов с кодами ошибок (404, 500) на короткий срок, чтобы не нагружать Origin повторными запросами к несуществующим или временно недоступным ресурсам.
- **Cache Stampede (Thundering Herd)**: Массовый одновременный запрос к Origin от множества CDN-узлов при истечении TTL популярного объекта. Решается через Origin Shield, `proxy_cache_lock`, `stale-while-revalidate`.
- **Cache Avalanche**: Ситуация, при которой одновременно истекает TTL у большого количества объектов, создавая пиковую нагрузку на Origin. Решается через джиттер (Jitter / Staggered TTL).
- **Cache Penetration**: Запросы к несуществующим объектам, которые никогда не попадают в кэш, нагружают Origin при каждом обращении. Решается через Negative Caching и Bloom Filters.
- **Cache Lock (Mutex)**: Механизм блокировки для предотвращения одновременного обращения к Origin от множества CDN-узлов при Cache Miss одного объекта. Первый запрос блокирует ключ, остальные получают ответ из кэша после его заполнения.
- **Cache Warming (Прогрев)**: Предварительное наполнение кэша популярными объектами до начала пикового трафика (после деплоя, миграции или инвалидации).
- **stale-if-error**: Директива `Cache-Control`, разрешающая CDN отдавать устаревший объект из кэша, если Origin вернул ошибку (5xx). Обеспечивает отказоустойчивость (Graceful Degradation).
- **must-revalidate**: Директива `Cache-Control`, запрещающая CDN отдавать устаревший контент. Кэш обязан выполнить валидацию на Origin перед выдачей ответа.
- **no-cache**: Директива `Cache-Control`, разрешающая кэширование объекта, но запрещающая его использование без предварительной валидации на Origin (обязательный `If-None-Match` или `If-Modified-Since`).
- **no-store**: Директива `Cache-Control`, полностью запрещающая сохранение объекта в кэше на любом уровне (CDN, браузер, прокси).

---

## Базовые концепции

### Иерархия управления кэшем

Современные CDN-платформы следуют строгой приоритетности инструкций (от высшего к низшему):
1. **Edge Rules (Панель управления)**: Глобальные правила провайдера, принудительно переопределяющие любые заголовки сервера.
2. **`CDN-Cache-Control`**: Инструкции, предназначенные исключительно для CDN. Позволяет установить TTL на границе выше, чем для браузеров.
3. **`Cache-Control` (директива `s-maxage`)**: Стандартная инструкция для разделяемых (shared) кэшей.
4. **`Cache-Control` (директива `max-age`)**: Общая инструкция для всех уровней кэширования.
5. **`Expires`**: Устаревший метод (HTTP/1.0), использующий абсолютную дату.

### Формирование и нормализация ключа кэша (Cache Key)

Эффективность кэширования (Hit Ratio) напрямую зависит от единообразия ключей. Без нормализации один и тот же файл может кэшироваться многократно под разными ключами.

**Методы нормализации (Стандарт 2026):**
- **Query-параметры**: Сортировка параметров в алфавитном порядке и удаление маркетингового «мусора» (`utm_*`, `gclid`, `fbclid`).
- **Сжатие (Compression)**: Кэширование отдельных версий для `gzip`, `br` и `zstd` на основе заголовка `Accept-Encoding`.
- **Форматы изображений**: Использование заголовка `Vary: Accept` для отдачи AVIF или WebP при одинаковом URL.
- **Регистр и кодировка**: Приведение путей к нижнему регистру и нормализация Unicode.

**Влияние `Vary` на ключ кэша:**
- `Vary: Accept-Encoding` — CDN хранит отдельные версии для каждого типа сжатия.
- `Vary: Accept` — отдельные версии для JSON vs HTML vs изображений (AVIF/WebP/JPEG).
- `Vary: Cookie` — контент становится не кэшируемым для CDN (каждый пользователь уникален).
- `Vary: *` — фактически отключает кэширование.

### CDN-специфичные директивы Cache-Control

Ниже приведена таблица директив, которые наиболее актуальны при работе с CDN. Для полного обзора HTTP-кэширования см. [HTTP-кэширование](../Protocols/HTTP/http_caching.md).

| Директива | Кто использует | Описание | Пример |
| :--- | :--- | :--- | :--- |
| `s-maxage` | Shared (CDN/Proxy) | TTL для разделяемых кэшей. Переопределяет `max-age` для CDN. | `Cache-Control: public, s-maxage=3600, max-age=600` |
| `CDN-Cache-Control` | Только CDN | RFC 9213: инструкции исключительно для CDN, не затрагивает браузер. | `CDN-Cache-Control: s-maxage=86400` |
| `stale-while-revalidate` | CDN + Браузер | Отдать устаревший контент, пока в фоне идёт валидация (RFC 5861). | `Cache-Control: public, s-maxage=60, stale-while-revalidate=3600` |
| `stale-if-error` | CDN + Браузер | Отдать устаревший контент при ошибке Origin (5xx) (RFC 5861). | `Cache-Control: public, s-maxage=3600, stale-if-error=86400` |
| `immutable` | CDN + Браузер | Ресурс не изменится до истечения `max-age`. Исключает条件ные запросы. | `Cache-Control: public, max-age=31536000, immutable` |
| `no-cache` | Все уровни | Кэширование разрешено, но обязательна валидация перед каждым использованием. | `Cache-Control: no-cache` |
| `no-store` | Все уровни | Полный запрет на сохранение в кэше на любом уровне. | `Cache-Control: private, no-store` |
| `must-revalidate` | Все уровни | Запрет отдачи устаревшего контента. Кэш обязан выполнить валидацию. | `Cache-Control: public, max-age=3600, must-revalidate` |
| `proxy-revalidate` | Shared (CDN/Proxy) | Аналог `must-revalidate`, но только для разделяемых кэшей. | `Cache-Control: public, s-maxage=3600, proxy-revalidate` |
| `Surrogate-Key` | CDN (нестандартный) | Логические метки для массовой инвалидации (Surrogate Keys). | `Surrogate-Key: product_laptops brand_apple` |

**Пример: раздельное кэширование для CDN и браузера:**
```http
CDN-Cache-Control: s-maxage=86400, stale-while-revalidate=3600, stale-if-error=86400
Cache-Control: no-cache
# CDN кэширует на 24 часа с фоновым обновлением
# Браузер не кэширует, всегда проверяет актуальность
```

### Условные HTTP-запросы и валидация

Когда объект устаревает (TTL истёк), CDN или браузер обязан проверить его актуальность на Origin через **условный запрос** (Conditional Request). Это позволяет избежать передачи тела ответа, если ресурс не изменился.

**Механизм работы (RFC 9111):**

1. CDN отправляет на Origin HTTP-запрос с заголовком `If-None-Match` (ETag) или `If-Modified-Since` (дата).
2. Origin проверяет актуальность:
   - **Ресурс не изменился** → `304 Not Modified` (пустое тело, только заголовки). CDN обновляет `Age` и繼續 отдаёт кэшированную версию.
   - **Ресурс изменился** → `200 OK` с новым телом и новым `ETag`. CDN обновляет объект в кэше.

**Пример запроса с ETag:**
```http
# Первый запрос (Origin возвращает объект с ETag)
GET /api/products/123 HTTP/1.1
HTTP/1.1 200 OK
ETag: "6868976968.0"
Cache-Control: public, max-age=300

# Повторный запрос (CDN проверяет актуальность)
GET /api/products/123 HTTP/1.1
If-None-Match: "6868976968.0"
HTTP/1.1 304 Not Modified
# Тело не передаётся — экономия ~60-80% пропускной способности
```

**Strong vs Weak ETag:**
- **Strong (`"abc123"`)**: Гарантирует побайтовое совпадение контента. Используется для статических файлов.
- **Weak (`W/"abc123"`)**: Гарантирует семантическую эквивалентность. Допускает микро-изменения (дата в футере, комментарии в коде).

**Важно для CDN:** Директива `immutable` на_ORIGIN_ полностью исключает условные запросы на срок жизни `max-age`. Это критически важно для статики с хешированными именами файлов.

### Cache Busting

Cache Busting — это стратегия принудительного обновления кэша клиентов и CDN через изменение URL ресурса, а не через инвалидацию по заголовкам.

**Методы:**

| Метод | Описание | Пример URL | Сценарий |
| :--- | :--- | :--- | :--- |
| **Hash-имя файла** | Хеш содержимого встраивается в имя | `/static/app.a1b2c3.js` | Статика (CSS/JS) с сборщиками (Webpack, Vite) |
| **Query-параметр версии** | Версия в query string | `/api/data?v=2.1.0` | API-эндпоинты, файлы без сборщика |
| **Directory-based** | Версия в пути каталога | `/v2/static/style.css` | Мажорные версии API |
| **Purge API** | Программная инвалидация | — | Динамический контент, CMS |

**Когда использовать Cache Busting вместо Purge:**
- При наличии сборщика статики (Webpack, Vite, esbuild) — hash-имя файла является предпочтительным методом, так как не требует дополнительных API-вызовов.
- При отсутствии сборщика — query-параметр версии (`?v=123`) является наиболее простым решением.
- При работе с динамическим контентом (CMS, e-commerce) — Purge API или Surrogate Keys.

---

## Механизмы инвалидации

### 1. Мгновенная очистка (Purge)

Удаление конкретного объекта из всех PoP CDN-провайдера. Современные CDN (Cloudflare, Fastly) обеспечивают глобальную очистку за **<200 мс**.

**Типы Purge:**

| Тип | Описание | Пример API-запроса |
| :--- | :--- | :--- |
| **Single URL** | Удаление одного конкретного URL | `PURGE /images/photo.jpg` |
| **Wildcard** | Удаление по паттерну | `PURGE /static/css/*` |
| **Tag-Based** | Удаление по Surrogate Keys | `PURGE /tags/category_laptops` |
| **Host-Wide** | Удаление всего контента домена | `PURGE *` (для зоны) |

**Cloudflare Purge API — все типы:**
```bash
# Очистка конкретных URL
curl -X POST "https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache" \
  -H "Authorization: Bearer {api_token}" \
  -H "Content-Type: application/json" \
  --data '{"files":["https://example.com/index.html","https://example.com/style.css"]}'
# → {"result":{"purge_all":false,"purge_everything":false,"purge_urls":["https://example.com/index.html","https://example.com/style.css"]}}

# Очистка по тегам (Surrogate Keys)
curl -X POST "https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache" \
  -H "Authorization: Bearer {api_token}" \
  -H "Content-Type: application/json" \
  --data '{"tags":["product_laptops","brand_apple"]}'
# → {"result":{"purge_tags":["product_laptops","brand_apple"]}}

# Полная очистка кэша зоны (использовать осторожно!)
curl -X DELETE "https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache" \
  -H "Authorization: Bearer {api_token}" \
  --data '{"purge_everything":true}'
# → {"result":{"purge_everything":true}}
```

**Cloudflare DNS API (прокси и управление записями):**

Создание A-записи в режиме прокси (`proxied: true`) маршрутизирует трафик через сеть Cloudflare (CDN + WAF). Параметр `ttl: 1` означает автоопределение TTL — требуется, когда запись находится за прокси.

```bash
# Получить zone_id по домену
curl -sX GET "https://api.cloudflare.com/client/v4/zones?name=example.com" \
  -H "Authorization: Bearer {api_token}" \
  -H "Content-Type: application/json" | jq -r '.result[0].id'
# → 023e105f4ecef8ad8ca31a42bb512345

# Создать A-запись за прокси (proxied=true → трафик идёт через CDN Cloudflare)
curl -sX POST "https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records" \
  -H "Authorization: Bearer {api_token}" \
  -H 'Content-Type: application/json' \
  --data '{"type":"A","name":"<host>","content":"<ip>","proxied":true,"ttl":1}'
# → {"result":{"id":"...","name":"<host>","type":"A","content":"<ip>","proxied":true,"ttl":1}}

# Обновить существующую запись
curl -sX PUT "https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}" \
  -H "Authorization: Bearer {api_token}" \
  -H 'Content-Type: application/json' \
  --data '{"type":"A","name":"<host>","content":"<new_ip>","proxied":true,"ttl":1}'
# → {"result":{"id":"...","content":"<new_ip>","proxied":true}}

# Переключить запись из прокси в DNS-only (proxied: false)
curl -sX PUT "https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}" \
  -H "Authorization: Bearer {api_token}" \
  -H 'Content-Type: application/json' \
  --data '{"type":"A","name":"<host>","content":"<ip>","proxied":false,"ttl":300}'
# → {"result":{"id":"...","proxied":false}}
```

> **Важно:** `proxied: true` требует `ttl: 1` (авто). При `proxied: false` (DNS-only) можно задать явный TTL (300, 3600 и т.д.).

**Fastly Purge API:**
```bash
# Очистка конкретного URL
curl -X PURGE "https://example.com/index.html" \
  -H "Fastly-Key: {api_token}"
# → 200 OK

# Очистка по Surrogate Key
curl -X POST "https://api.fastly.com/service/{service_id}/purge/product_laptops" \
  -H "Fastly-Key: {api_token}"
# → {"status":"ok","id":"..."
```

**AWS CloudFront Invalidation:**
```bash
# Создание инвалидации ( Wildcard )
aws cloudfront create-invalidation \
  --distribution-id E1234567890ABC \
  --paths "/static/*" "/images/*"
# → Invalidation ID: I1234567890ABC

# Проверка статуса инвалидации
aws cloudfront get-invalidation \
  --distribution-id E1234567890ABC \
  --id I1234567890ABC
# → Status: Completed
# Важно: CloudFront инвалидация занимает 5-15 минут (не <200 мс как у Cloudflare/Fastly)
```

### 2. Теговая инвалидация (Surrogate Keys)

Самый эффективный метод для сложных систем (E-commerce, СМИ, каталоги). Позволяет инвалидировать тысячи объектов одним API-запросом.

**Принцип работы:**
1. Сервер-источник прикрепляет к ответу заголовок `Surrogate-Key`:
   ```http
   HTTP/1.1 200 OK
   Surrogate-Key: product_laptops brand_apple category_electronics
   Cache-Control: public, max-age=300
   ```
2. CDN сохраняет связи между тегами и объектами в метаданных.
3. При изменении цены на все ноутбуки Apple отправляется один запрос:
   ```bash
   # Cloudflare
   curl -X POST "https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache" \
     -H "Authorization: Bearer {api_token}" \
     --data '{"tags":["product_laptops","brand_apple"]}'
   ```
4. Все страницы с тегами `product_laptops` И `brand_apple` инвалидируются мгновенно.

**Архитектурная схема:**
```
[Origin] --Surrogate-Key--> [CDN Edge Cache] <-- Purge API -- [Приложение/CI-CD]
                                   |
                          [Metadata Store]
                          тег -> [URL1, URL2, ...]
```

**Сравнение методов инвалидации по масштабу:**

| Метод | Количество объектов за 1 запрос | Задержка | Сложность реализации |
| :--- | :--- | :--- | :--- |
| **Single URL Purge** | 1 | <200 мс | Низкая |
| **Wildcard Purge** | 10-1000 | 1-5 мин | Средняя |
| **Tag-Based Purge** | 100-100000+ | <200 мс | Высокая |
| **Cache Busting** | ∞ (без запросов) | Мгновенно | Средняя (требует сборщик) |

### 3. Фоновое обновление (Stale-While-Revalidate)

Механизм (RFC 5861), позволяющий отдавать пользователю устаревший контент, пока CDN в фоновом режиме запрашивает обновление у Origin.

**Настройка:**
```http
Cache-Control: public, s-maxage=60, stale-while-revalidate=3600
```

**Результат:**
- **0-60 сек**: CDN отдаёт объект из кэша (HIT), TTL ещё не истёк.
- **60-3660 сек**: CDN отдаёт устаревший объект из кэша (STALE), параллельно выполняя валидацию на Origin. Пользователь получает ответ за 0 мс, кэш обновляется асинхронно.
- **>3660 сек**: Объект считается слишком старым, CDN обращается к Origin синхронно.

**Преимущества:**
- **Нулевая задержка для пользователя**: Ответ всегда приходит из ближайшего PoP.
- **Автоматическое обновление**: Кэш всегда стремится к актуальности, не требуя ручной инвалидации.
- **Защита от Thundering Herd**: При истечении `s-maxage` все CDN-узлы не обращаются к Origin одновременно.

### 4. Отказоустойчивость (stale-if-error)

Директива (RFC 5861), разрешающая CDN отдавать устаревший контент, если Origin вернул ошибку (5xx) или недоступен.

**Настройка:**
```http
Cache-Control: public, s-maxage=3600, stale-if-error=86400
```

**Сценарий:**
1. Origin возвращает ошибку 502 Bad Gateway (микросервис упал).
2. CDN проверяет кэш и находит устаревший объект (возраст < 86400 сек).
3. CDN отдаёт пользователю устаревший контент с заголовком `Cache-Status: stale; error=502`.
4. Пользователь видит контент (возможно, slightly outdated), а не страницу ошибки.

**Важно:** `stale-if-error` является критически важной директивой для обеспечения отказоустойчивости. Без неё при падении Origin все пользователи увидят ошибку 502/503.

**Когда НЕ использовать:**
- Для данных, где актуальность критична (финансовые котировки, медицинские данные).
- Для приватного контента (личные кабинеты) — устаревший контент может содержать данные другого пользователя.

### 5. Принудительная валидация (must-revalidate)

Директива, запрещающая CDN отдавать устаревший контент даже при ошибке Origin.

**Настройка:**
```http
Cache-Control: public, max-age=3600, must-revalidate
```

**Сравнение с stale-if-error:**

| Директива | Поведение при ошибке Origin | Поведение при正常的 TTL |
| :--- | :--- | :--- |
| `stale-if-error=86400` | Отдать устаревший контент (до 86400 сек) | Отдать свежий контент |
| `must-revalidate` | Вернуть ошибку клиенту (502/503) | Отдать свежий контент |
| Нет директивы | Отдать устаревший контент (по умолчанию CDN) | Отдать свежий контент |

---

## Антипаттерны и проблемные сценарии

### Cache Stampede (Thundering Herd)

Массовый одновременный запрос к Origin от множества CDN-узлов при истечении TTL популярного объекта. Происходит, когда один объект становится «горячим» и его TTL истекает одновременно на всех PoP.

**Причины:**
- Один файл запрошен одновременно с разных PoP, TTL истекает в одно время.
- Массовая инвалидация (Wildcard Purge) сбрасывает кэш на всех узлах.
- Первый запрос после Deploys/Restart кэша.

**Решения:**

| Решение | Механизм | Реализация |
| :--- | :--- | :--- |
| **Origin Shield** | Промежуточный кэш между PoP и Origin | Включить Tiered Caching у CDN-провайдера |
| **proxy_cache_lock** | Блокировка ключа в кэше Nginx | `proxy_cache_lock on; proxy_cache_lock_timeout 5s;` |
| **stale-while-revalidate** | Фоновое обновление без блокировки | `Cache-Control: s-maxage=60, stale-while-revalidate=3600` |
| **Jitter TTL** | Случайное смещение TTL | `TTL = base_ttl + rand(0, 300)` |
| **Single-flight (Request Collapsing)** | Схлопывание запросов к одному ключу | Реализация на уровне приложения или CDN |

**Nginx: Защита от Thundering Herd через proxy_cache_lock:**
```nginx
proxy_cache_path /data/nginx/cache levels=1:2 keys_zone=static:10m max_size=1g;

location ~* \.(js|css|png|jpg)$ {
    proxy_cache static;
    proxy_cache_valid 200 1h;

    # Блокировка: только первый запрос идёт к Origin
    proxy_cache_lock on;
    # Таймаут блокировки: если Origin не ответил за 5 сек, разрешить параллельные запросы
    proxy_cache_lock_timeout 5s;
    # Отдавать stale пока идёт блокировка
    proxy_cache_use_stale updating;

    proxy_pass http://backend;
}
```

### Cache Avalanche (Лавина кэша)

Одновременное истечение TTL у миллионов ключей, например, если они были записаны одновременно при старте системы или после массовой инвалидации.

**Причина:** Если все объекты получили одинаковый TTL при деплое, они все истекут одновременно, создав пиковую нагрузку на Origin.

**Решение — Jitter (Staggered TTL):**
```python
import random

def get_ttl(base_ttl: int = 3600, jitter_range: int = 300) -> int:
    """Добавление случайного смещения к TTL для предотвращения Cache Avalanche."""
    return base_ttl + random.randint(-jitter_range, jitter_range)

# Пример: TTL = 3600 + random(-300, 300) = от 3300 до 3900 сек
# Объекты истекают в разное время, распределяя нагрузку
```

**Nginx: Jitter через переменную:**
```nginx
# Генерация случайного TTL (требует Lua-модуля или map)
set $ttl_jitter 3600;
# Основной TTL + случайное отклонение
proxy_cache_valid 200 $ttl_jitter;
```

### Cache Penetration (Проникновение в кэш)

Запросы к несуществующим объектам, которые никогда не попадают в кэш, нагружают Origin при каждом обращении. Распространенная атака: злоумышленник генерирует миллионы уникальных URL.

**Решения:**

| Решение | Механизрм | Эффективность |
| :--- | :--- | :--- |
| **Negative Caching** | Кэширование ответов 404 на короткий срок | Средняя (снижает нагрузку в N раз) |
| **Bloom Filter** | Быстрая проверка отсутствия ключа без обращения к БД | Высокая (ложноположительные ≤1%) |
| **Тихий 404** | Возврат пустого ответа с кодом 200 для несуществующих ресурсов | Низкая (риск SEO-проблем) |

**Nginx: Negative Caching (кэширование ошибок):**
```nginx
proxy_cache_path /data/nginx/cache levels=1:2 keys_zone=app:10m;

location / {
    proxy_cache app;

    # Кэширование ответов 404 на 10 секунд
    proxy_cache_valid 404 10s;
    # Кэширование ответов 500/502/503 на 1 секунду
    proxy_cache_valid 500 502 503 1s;
    # Не кэшировать ответы 301/302 (редиректы)
    proxy_cache_valid 301 302 0s;

    proxy_pass http://backend;
}
```

### Cache Lock (Mutex)

Механизм блокировки, предотвращающий одновременное обращение к Origin от множества CDN-узлов или прокси при Cache Miss одного объекта.

**Как работает:**
1. Первый запрос получает блокировку (Lock) на ключ кэша.
2. Остальные запросы к этому ключу получают ответ «подождите» или устаревший контент.
3. Первый запрос наполняет кэш, и все остальные получают данные из кэша.

**Nginx: proxy_cache_lock:**
```nginx
location /api/ {
    proxy_cache app_cache;

    # Включить блокировку (по умолчанию выключена)
    proxy_cache_lock on;

    # Время ожидания блокировки (по умолчанию 5 сек)
    proxy_cache_lock_timeout 5s;

    # Количество запросов, которые могут ожидать блокировки одновременно
    proxy_cache_lock_age 5s;

    # Отдавать stale пока идёт блокировка
    proxy_cache_use_stale updating;

    proxy_pass http://backend;
}
```

### Cache Warming (Прогрев кэша)

Предварительное наполнение кэша популярными объектами до начала пикового трафика.

**Когда необходим:**
- После Deploys/Restart кэша (весь кэш пуст).
- После массовой инвалидации (Wildcard Purge).
- При добавлении нового PoP (кэш на новом узле пуст).
- При запуске нового продукта/страницы.

**Методы прогрева:**

| Метод | Описание | Сложность | Эффективность |
| :--- | :--- | :--- | :--- |
| **Предварительная загрузка (Preload)** | Скрипт обращается к ресурсам перед пуском трафика | Низкая | Средняя |
| **Зеркалирование трафика (Shadow Traffic)** | Копия реального трафика на новый кэш | Высокая | Высокая |
| **Постепенный прогрев (Ramp-up)** | Постепенное увеличение трафика к новому кэшу | Средняя | Высокая |
| **Edge-функция для прогрева** | CDN Worker/Function, предзагружающий контент | Средняя | Высокая |

**Пример: скрипт прогрева через curl:**
```bash
#!/bin/bash
# warm_cache.sh — предварительная загрузка популярных страниц в CDN

URLS=(
  "https://example.com/"
  "https://example.com/products"
  "https://example.com/about"
  "https://example.com/api/catalog?limit=100"
  "https://example.com/images/hero.jpg"
)

echo "Прогрев кэша CDN..."
for url in "${URLS[@]}"; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$url")
  echo "  $url → $STATUS"
done
echo "Прогрев завершен."
```

---

## Безопасность и защита

### Защита от Cache Poisoning (Отравление кэша)

Атака, при которой злоумышленник заставляет CDN сохранить некорректный или вредоносный ответ (например, через манипуляцию заголовком `X-Forwarded-Host`).

**Меры защиты:**
- **Игнорирование нерелевантных заголовков**: Исключение из Cache Key всех заголовков, не влияющих на формирование контента.
- **Строгая нормализация входных данных**: Очистка URL и заголовков на уровне Edge перед формированием ключа.
- **Origin Verification**: Проверка сертификатов и использование защищенных туннелей между CDN и Origin.

**Пример: исключение нерелевантных заголовков из Cache Key (Cloudflare):**
```bash
# Включение Ignore Query String Order
curl -X PATCH "https://api.cloudflare.com/client/v4/zones/{zone_id}/cache/cache_keys" \
  -H "Authorization: Bearer {api_token}" \
  --data '{"query_string":{"sort":true,"ignore":true}}'
```

### Безопасность Origin

- **Signed URLs**: Генерация временных ссылок с криптографической подписью для доступа к приватному контенту. Ссылка содержит подпись и время истечения, CDN проверяет подпись перед отдачей.
- **IP Allowlisting**: Ограничение доступа к Origin-серверу только с IP-диапазонов CDN-провайдера.
- **Token-Based Auth**: Использование токенов авторизации (Bearer Token) для доступа к приватным API через CDN.

### Negative Caching и безопасность

Negative Caching (кэширование ответов с ошибками) является双重 edged мечом:
- **Положительный эффект**: Защита Origin от DoS-атак через генерацию миллиардов запросов к несуществующим URL.
- **Отрицательный эффект**: Злоумышленник может «заморозить» ошибку в кэше, скрыв реальную проблему с Origin.

**Рекомендация:** Устанавливайте короткий TTL для кэширования ошибок (10-60 сек) и комбинируйте с Rate Limiting.

---

## Практические сценарии (Best Practices 2026)

| Тип контента | Стратегия кэширования | Рекомендуемые заголовки |
| :--- | :--- | :--- |
| **Статика (Immutable)** | Максимальный TTL + Кэширование версий | `Cache-Control: public, max-age=31536000, immutable` |
| **Динамический HTML** | Короткий TTL + SWR | `CDN-Cache-Control: s-maxage=300, stale-while-revalidate=3600` |
| **API-ответы** | Теговое кэширование | `Cache-Control: no-cache`, `Surrogate-Key: user_id_123` |
| **Ошибки (4xx/5xx)** | Негативное кэширование | Кратковременное кэширование (10-60 сек) для защиты от DoS при сбоях бэкенда |
| **Приватный контент** | Запрет кэширования | `Cache-Control: private, no-store` |
| **Видео (VOD)** | Долгий TTL + SWR | `CDN-Cache-Control: s-maxage=86400, stale-while-revalidate=3600` |
| **Каталог товаров** | Теговое кэширование + короткий TTL | `CDN-Cache-Control: s-maxage=60`, `Surrogate-Key: category_{id}` |

### Интеграция с CI/CD

Автоматическая инвалидация кэша CDN — стандартная часть современных пайплайнов деплоя:

**Пример GitHub Actions (Cloudflare Purge):**
```yaml
# .github/workflows/deploy.yml
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to Origin
        run: echo "Deploying..."

      - name: Purge CDN Cache
        if: success()
        run: |
          curl -X POST "https://api.cloudflare.com/client/v4/zones/${{ secrets.CF_ZONE_ID }}/purge_cache" \
            -H "Authorization: Bearer ${{ secrets.CF_API_TOKEN }}" \
            -H "Content-Type: application/json" \
            --data '{"files":["https://example.com/*"]}'
        # → Очистка всего кэша после успешного деплоя
```

**Пример GitLab CI (Fastly Purge):**
```yaml
purge_cdn:
  stage: post-deploy
  script:
    - |
      curl -X PURGE "https://example.com/" \
        -H "Fastly-Key: ${FASTLY_API_TOKEN}"
      curl -X PURGE "https://example.com/api/catalog" \
        -H "Fastly-Key: ${FASTLY_API_TOKEN}"
  only:
    - main
```

---

## Мониторинг и отладка

### Стандартный заголовок Cache-Status (RFC 9211)

Детальный анализ работы кэша через заголовок `Cache-Status`:
```http
Cache-Status: Cloudflare-CDN; hit; ttl=345; key=a1b2c3d4; detail=mismatch-encoding
```

**Значения `Cache-Status`:**

| Значение | Описание | Действие |
| :--- | :--- | :--- |
| `hit` | Объект найден в кэше, TTL не истёк | Отдать из кэша |
| `miss` | Объект не найден в кэше | Запросить у Origin |
| `stale` | Объект в кэше, но TTL истёк | Валидация на Origin (или отдать если `stale-while-revalidate`) |
| `expired` | Объект в кэше, но помечен как удалённый | Запросить у Origin |
| `bypass` | Кэширование пропущено (по директиве `no-cache` или Edge Rule) | Запросить у Origin |
| `revalidated` | Объект устарел, но Origin подтвердил актуальность (`304 Not Modified`) | Отдать из кэша |
| `error` | Ошибка при обработке кэша | Запросить у Origin |
| `forward` | Запрос проксируется (не кэшируется) | Запросить у Origin |

### Ключевые метрики SRE

| Метрика | Описание | Целевое значение | Инструменты |
| :--- | :--- | :--- | :--- |
| **CHR (Cache Hit Ratio)** | Процент запросов, обслуженных из кэша | >98% (статика), >60% (динамика) | CDN Dashboard, Prometheus |
| **Origin Offload** | Процент трафика, НЕ дошедший до Origin | >95% | CDN Analytics |
| **Invalidation Latency** | Время между API-запросом на Purge и реальным удалением | <200 мс (Cloudflare, Fastly) | CDN API, мониторинг |
| **Thundering Herd Rate** | Количество одновременных запросов к Origin при Cache Miss | 0 (с Origin Shield) | Origin Monitoring |
| **TTFB (Time To First Byte)** | Время до получения первого байта | <50 мс (edge), <200 мс (origin) | Real User Monitoring (RUM) |
| **Error Rate (5xx)** | Доля серверных ошибок CDN | <0.01% | CDN Dashboard, APM |

### Диагностические команды

**Проверка статуса кэша:**
```bash
# Проверка Cache-Status и Age
curl -sD- https://example.com/static/app.js | grep -iE "cache-status|age|cache-control"
# → cache-status: hit; ttl=86400
# → age: 1234
# → cache-control: public, max-age=86400

# Проверка ETag и Last-Modified
curl -sD- https://example.com/api/products | grep -iE "etag|last-modified"
# → etag: "6868976968.0"
# → last-modified: Mon, 25 Aug 2025 10:00:00 GMT

# Проверка Surrogate Keys
curl -sD- https://example.com/product/123 | grep -i "surrogate-key"
# → surrogate-key: product_laptops brand_apple
```

**Проверка условного запроса (Conditional Request):**
```bash
# Получить ETag
ETAG=$(curl -sI https://example.com/api/data | grep -i etag | tr -d '\r' | awk '{print $2}')
echo "ETag: $ETAG"
# → ETag: "abc123"

# Проверить, изменился ли ресурс
curl -sI -H "If-None-Match: $ETAG" https://example.com/api/data | head -1
# → HTTP/1.1 304 Not Modified  (ресурс не изменился)
# → HTTP/1.1 200 OK            (ресурс изменился)
```

**Проверка TTL и свежести:**
```bash
# Вычислить реальный возраст объекта
curl -sI https://example.com/style.css | grep -iE "age|cache-control"
# → age: 300
# → cache-control: public, max-age=3600
# → Реальный TTL = 3600 - 300 = 3300 сек (объект ещё «свежий»)

# Проверить stale-if-error
curl -sI https://example.com/api/status | grep -i "stale-if-error"
# → cache-control: public, max-age=300, stale-if-error=86400
```

---

## Типичные ошибки и их решение

### Проблемы с кэшированием

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Низкий Cache Hit Ratio** | Много `MISS` в `Cache-Status`, высокая нагрузка на Origin | `curl -sI URL \| grep cache-status` | Проверить Cache Key, увеличить TTL, включить tiered caching |
| **Stale Content** | Пользователи видят устаревший контент | `curl -sI URL \| grep age` | Уменьшить TTL, настроить SWR, использовать Purge API |
| **Thundering Herd** | Всплеск нагрузки на Origin после TTL | Мониторинг Origin (CPU, RPS) | Включить Origin Shield, proxy_cache_lock, SWR |
| **Incorrect Cache Key** | Один URL кэшируется под разными ключами | Проверить `Vary`-заголовки | Нормализовать query-параметры, проверить Accept-Encoding |
| **Cache Poisoning** | CDN отдает вредоносный контент | Проверить HTTP-заголовки ответа | Включить Origin Verification, очищать URL |
| **Double Caching** | Обновление на CDN не доходит до пользователя | Сравнить `max-age` в браузере и CDN | Использовать `s-maxage` для CDN, `max-age` для браузера |

### Проблемы с инвалидацией

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **Purge не работает** | Контент не обновляется после API-запроса | Неправильный URL, таймаут, проблемы с API | Проверить статус API-ответа, проверить URL, повторить запрос |
| **Медленная инвалидация** | Контент обновляется через минуты, а не мгновенно | Провайдер не гарантирует <200 мс | Перейти на Fastly/Cloudflare или увеличить TTL |
| **Инвалидация не доходит до всех PoP** | Часть пользователей видит старый контент | Локальная проблема PoP, проблема с маршрутизацией | Проверить географию PoP, повторить Purge |
| **Wildcard Purge перегружает Origin** | Высокая нагрузка после Wildcard Purge | Все PoP одновременно запрашивают контент | Использовать Tiered Caching, уменьшатьWildcard |

### Проблемы с безопасностью

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **Cache Poisoning** | Вредоносный контент в кэше | Манипуляция заголовками | Очистить URL, включить Origin Verification |
| **Negative Caching DoS** | Замороженные ошибки в кэше | Короткий TTL для ошибок | Увеличить TTL, комбинировать с Rate Limiting |
| **Signed URL Leak** | Подписанные ссылки доступны посторонним | Публикация URL в открытом доступе | Уменьшить TTL Signed URLs, добавить IP-ограничения |

---

## Дополнительная информация

### Сравнение CDN-провайдеров по функционалу кэширования

| Функция | Cloudflare | Fastly | Akamai | CloudFront |
| :--- | :--- | :--- | :--- | :--- |
| **Purge Latency** | <200 мс | <150 мс | 5-10 сек | 5-15 мин |
| **Tag-Based Purge** | Да | Да (Surrogate Keys) | Да (Fast Purge) | Нет (только URL/Wildcard) |
| **Cache Lock** | Автоматически | Автоматически | Автоматически | Ручная настройка |
| **SWR** | Да | Да | Да | Да |
| **stale-if-error** | Да | Да | Да | Да |
| **Tiered Caching** | Smart Tiered | Да | Да (Встроенный) | Ограниченный |
| **Cache API** | REST + GraphQL | REST + ABI | REST + Reporting | REST |

### Связанные темы

- **[Обзор CDN](cdn_overview.md)** — архитектура и принципы работы сети доставки контента.
- **[Общие концепции кэширования](../../Concepts/Caching/caching_overview.md)** — метрики, проблемы (Stampede, Avalanche, Penetration) и паттерны кэширования.
- **[Паттерны кэширования](../../Concepts/Caching/caching_patterns.md)** — Cache-aside, Read-through, Write-through и стратегии инвалидации через CDC.
- **[HTTP-кэширование](../Protocols/HTTP/http_caching.md)** — заголовки Cache-Control, ETag, Conditional Requests и нормализация ключа кэша.
- **[Граничные вычисления (Edge Computing)](../../Concepts/edge_computing_overview.md)** — выполнение кода на узлах CDN.
