# Кэширование как инструмент веб-производительности

**Актуально для:** HTTP/1.1–HTTP/3 (RFC 9111, RFC 9211, RFC 9213) / Nginx 1.26+ / Angie 1.8+ / Varnish 7.x

## Определения

**Кэширование в веб-производительности** — стратегия сохранения копий сетевых ресурсов (HTML, CSS, JS, шрифты, изображения, API-ответы) на промежуточных узлах и клиентах для исключения повторных запросов по сети. Это ключевой метод оптимизации веб-производительности, позволяющий минимизировать сетевые задержки (Latency), сократить TTFB (Time to First Byte), снизить нагрузку на CPU/БД серверов Origin и ускорить рендеринг страниц (Core Web Vitals).

**HTTP Cache** — распределенный механизм кэширования, регламентируемый стандартом RFC 9111. Разделяется на:
- **Частный кэш (Private Cache):** расположен на стороне конечного клиента (браузер, мобильное приложение) и изолирован для одного пользователя.
- **Разделяемый кэш (Shared Cache):** обслуживает множество пользователей одновременно. Включает обратные прокси (Reverse Proxy), шлюзы балансировки (Ingress/Edge) и локальные корпоративные прокси (Forward Proxy).

**Reverse Proxy Cache** — кэш на уровне обратного прокси-сервера (Nginx, Angie, Varnish Cache, Envoy, Apache Traffic Server). Выполняет агрегацию запросов к бэкендам, сглаживает пики трафика, обеспечивает устойчивость при частичной деградации сервисов и защищает Origin от перегрузки.

**Private / On-Premise CDN (Edge Cache)** — распределенная сеть собственных или арендованных серверов (Points of Presence, PoP) на базе ПО обратного проксирования (Varnish/Angie/Nginx), доставляющая статический и динамический контент с минимальной сетевой задержкой в рамках контролируемой инфраструктуры.

**Cache Hit Ratio (CHR)** — базовый показатель эффективности кэша, отражающий процент запросов, обслуженных напрямую из кэша:
$$\text{CHR} = \frac{\text{Hits}}{\text{Hits} + \text{Misses}} \times 100\%$$
Целевой показатель для статических ассетов составляет >95%, для кэшируемых API — >75–85%.

**Byte Hit Ratio (BHR)** — доля сетевого трафика (в байтах), отданная из кэша без обращения к Origin. Критична для SRE при планировании пропускной способности каналов и дискового I/O при раздаче тяжелых файлов.

**Cache Stampede (Thundering Herd)** — лавинообразный наплыв сотен или тысяч параллельных запросов на Origin при истечении TTL популярного объекта. Все клиенты одновременно получают Cache Miss и вызывают перегрузку бэкенда.

**Cache Avalanche** — одновременное истечение времени жизни большого пула объектов (например, из-за одинакового фиксированного TTL), вызывающее резкий скачок нагрузки на дисковую подсистему и апстримы.

**Cache Penetration** — поток запросов к заведомо отсутствующим или сгенерированным ресурсам, которые не могут быть найдены в кэше и каждый раз пробивают его насквозь до базы данных или приложения.

**Cache Partitioning** — изоляция кэша в современных браузерах по составному ключу `(Top-level Site, Resource URL)`. Исключает возможность межсайтового отслеживания и разделения ресурсов сторонних доменов.

**Surrogate Keys (Cache Tags)** — механизм группировки кэшированных сущностей с помощью строковых меток (тегов) в заголовках ответов (например, `Surrogate-Key` или `Cache-Tags`), позволяющий выполнять мгновенную выборочную инвалидацию тысяч связанных URL одним действием.

**Microcaching** — архитектурный паттерн кратковременного (от 1 до 5 секунд) кэширования динамических ответов на стороне обратного прокси, защищающий приложение от перегрузок при всплесках нагрузки.

**Negative Caching** — сохранение в кэше ответов с кодами ошибок (404, 500, 502, 503) на небольшой интервал времени для защиты инфраструктуры от повторных ресурсоемких запросов.

## Архитектура и принцип работы

### Архитектура уровней кэширования

В веб-инфраструктуре кэширование организуется в виде эшелонированной иерархии:

```
[ Браузер клиента ]
    │  L1: Browser Cache (Disk/RAM) + Service Worker (Cache Storage)
    ▼
[ Сетевой периметр (DMZ / Edge PoP) ]
    │  L2: Edge Reverse Proxy (Varnish / Angie / Nginx)
    ▼
[ Балансировщик / API Gateway ]
    │  L3: Ingress Proxy Cache (Shared Memory + NVMe/Page Cache)
    ▼
[ Слой приложений (Origin) ]
    │  L4: In-Memory Object Cache (Redis / Memcached / Valkey)
    ▼
[ База данных / Файловое хранилище ]
       L5: Buffer Pool / Page Cache ОС / Shared Buffers
```

| Уровень | Размещение | Хранилище | Механизм управления | Ответственный |
| :--- | :--- | :--- | :--- | :--- |
| **Browser Cache** | Клиент | Диск / RAM браузера | Заголовки `Cache-Control`, `ETag`, `Last-Modified` | Frontend / SRE |
| **Service Worker** | Клиент | Cache Storage API / IndexedDB | Программный код Service Worker (offline-first, stale-while-revalidate) | Frontend |
| **Edge Cache (PoP)** | Входной периметр | RAM / NVMe / Linux Page Cache | `Surrogate-Control`, `s-maxage`, Varnish VCL / Angie | DevOps / SysAdmin |
| **Proxy Cache (Ingress)** | DMZ / Внутренняя сеть | Shared Memory (`keys_zone`) + Диск | Директивы `proxy_cache_*` (Nginx/Angie) | SysAdmin / SRE |
| **Application Cache** | Слой бэкенда | RAM (Key-Value кластеры) | Логика приложения (Cache-Aside, Write-Through) | Backend |

### Жизненный цикл объекта в кэше

1. **Запрос и проверка ключа (Lookup):** Прокси вычисляет контрольную сумму ключа кэша (`Cache Key`) и выполняет поиск индекса в оперативной памяти (`keys_zone` в Nginx/Angie или hash-таблица Varnish).
2. **Промах (Cache Miss):** Если объект отсутствует или признан устаревшим (`EXPIRED`), запрос перенаправляется на Origin.
3. **Захват мьютекса (Locking):** При включенном `proxy_cache_lock` только один запрос уходит на апстрим; остальные запросы встают в очередь ожидания ответа.
4. **Сохранение (Store):** Ответ апстрима записывается во временный файл (`proxy_temp_path`), после чего атомарно перемещается в каталог кэша (`proxy_cache_path`), а метаданные добавляются в shared memory.
5. **Попадание (Cache Hit):** Объект считывается с диска через Linux Page Cache или напрямую из RAM и отдается клиенту с добавлением заголовков статуса (`X-Cache-Status: HIT`, `Age`).
6. **Валидация (Validation):** По истечении TTL прокси инициирует условный запрос к Origin (`If-None-Match` / `If-Modified-Since`). При ответе `304 Not Modified` обновляются метаданные без передачи тела; при `200 OK` объект перезаписывается.
7. **Вытеснение (Eviction):** Фоновый менеджер кэша (Cache Manager) удаляет наименее востребованные объекты по алгоритму LRU/LFU при исчерпании `max_size` или превышении тайм-аута неактивности `inactive`.
8. **Инвалидация (Purge/Ban):** Принудительное удаление объекта по API или CLI до истечения естественного TTL.

### Консистентное хэширование (Consistent Hashing) при балансировке кэширующих пулов

При масштабировании кэширующего слоя (пул серверов Varnish, Nginx/Angie с `proxy_cache` или кластеры in-memory кэшей) выбор алгоритма балансировки нагрузки критически важен для сохранения метрики **Cache Hit Ratio (CHR)**:

- **Проблема Round-Robin / Least_Conn:** Если входящие запросы к кластеру кэшей распределяются циклически или по числу активных соединений, повторные запросы одного и того же URL попадают на разные ноды. Каждый узел вынужден независимо выкачивать контент с Origin. В результате CHR стремится к нулю, а нагрузка на бэкенд возрастает пропорционально числу кэш-серверов.
- **Решение — Консистентное хэширование (Ketama Ring):**
  - Запрос привязывается к узлу на основе хэша от ключа ресурса: `hash $request_uri consistent;`.
  - Все запросы за конкретным URL строго направляются на один и тот же кэширующий сервер.
  - При отказе или плановом добавлении одной ноды в кластер из $N$ серверов перераспределяется только $1/N$ часть ключей кэша, в то время как остальные $(N-1)/N$ ключей продолжают попадать на свои прежние серверы без сброса кэша (предотвращение **Cache Avalanche**).
  - Подробный разбор алгоритма: [Алгоритмы балансировки нагрузки в Nginx](../../Nginx/Proxy/Load_Balancing/algorithms.md).

### Linux Page Cache и задержки сброса грязных страниц (Dirty Writeback Stalls)

При активном серверном кэшировании на диск (`proxy_cache` на SSD/NVMe) или сохранении тяжелых временных файлов буферизации обратный прокси непрерывно выполняет операции записи:

- **Механика проблемы:** Данные, записываемые процессом веб-сервера через системный вызов `write(2)`, не сбрасываются на накопитель немедленно, а накапливаются в оперативной памяти в виде «грязных» страниц (dirty pages) Page Cache ядра Linux.
- **Опасность завышенного `vm.dirty_ratio`:**
  - На серверах с большими объемами оперативной памяти (64–256 ГБ) стандартное значение `vm.dirty_ratio = 20` означает, что в памяти может накопиться до 12–50 ГБ не сброшенных на диск данных.
  - При достижении порога `vm.dirty_ratio` ядро Linux принудительно переводит процессы веб-сервера в режим синхронной записи (write throttling).
  - Воркеры Nginx/Angie блокируются в состоянии `D` (Uninterruptible Sleep), системные вызовы замирают, а TTFB запросов подскакивает с единиц миллисекунд до нескольких секунд.
- **Оптимальный тюнинг ядра для кэширующих прокси:**
  ```ini
  # /etc/sysctl.d/99-cache-writeback.conf
  # Фоновый сброс начинается при накоплении 5% dirty pages (не допуская лавины)
  vm.dirty_background_ratio = 5
  # Принудительная блокировка процессов наступает не позднее 10%
  vm.dirty_ratio = 10
  # Сброс старых страниц каждые 5 секунд
  vm.dirty_expire_centisecs = 500
  ```
  - Детальный разбор дискового I/O: [Настройка сброса грязных страниц (writeback)](../../../Linux/Diagnostics/Performance/DiskIO/writeback_tuning.md).

### Механизмы свежести и валидации по RFC 9111

#### Определение свежести (Freshness)

Объект считается «свежим» (fresh), если его текущий возраст (`Age`) не превышает заданного времени жизни (`Freshness Lifetime`):
- `Cache-Control: max-age=<N>` — время свежести в секундах для частных и разделяемых кэшей.
- `Cache-Control: s-maxage=<N>` — приоритетное время свежести, предназначенное **исключительно для разделяемых кэшей** (reverse proxy, edge). Частные кэши браузеров игнорируют `s-maxage` и ориентируются на `max-age`.
- `Expires` — устаревший HTTP/1.0 заголовок с абсолютной датой по UTC. При наличии `max-age` или `s-maxage` заголовок `Expires` полностью игнорируется.
- `Age` — время в секундах, прошедшее с момента генерации или валидации ответа на Origin.
- **Остаточный срок жизни (Real TTL):**
  $$\text{Real\_TTL} = \text{max-age} - \text{Age}$$
- **Эвристическая свежесть (Heuristic Caching):** Если сервер не указал явных директив `Cache-Control` или `Expires`, но передал `Last-Modified`, кэш имеет право сохранить ответ на 10% от интервала между текущим временем и датой изменения:
  $$\text{Freshness} = (\text{Date} - \text{Last-Modified}) \times 0.1$$

#### Валидация устаревших данных (Conditional Requests)

Когда ресурс переходит в состояние `stale`, кэш выполняет проверку его актуальности на сервере:

- **Strong Validator (Сильный):** Побайтовое соответствие контента.
  - `ETag: "5d-68689769"` — строгий хэш тела ответа.
  - Клиент передает: `If-None-Match: "5d-68689769"`.
- **Weak Validator (Слабый):** Семантическая эквивалентность контента (допускаются незначительные расхождения, например, изменение даты генерации в футере или компрессия).
  - `ETag: W/"v1.2"` — слабый валидатор с префиксом `W/`.
  - `Last-Modified: Wed, 21 Oct 2026 07:28:00 GMT` — точность ограничена 1 секундой.
  - Клиент передает: `If-Modified-Since: Wed, 21 Oct 2026 07:28:00 GMT`.

> [!WARNING]
> **Потеря Strong ETag при динамической компрессии:** Если Nginx или Angie выполняет сжатие ответов «на лету» (Gzip, Brotli), сервер обязан модифицировать сильный ETag в слабый (`W/"..."`), поскольку сжатое тело побайтово отличается от исходного. Для сохранения сильных ETag и снижения нагрузки на CPU применяйте статическую прекомпрессию (`gzip_static on;`, `brotli_static on;`).

### Спецификация директив Cache-Control

| Директива | Область | Описание стандарта (RFC 9111, RFC 5861, RFC 9213) |
| :--- | :--- | :--- |
| `public` | Ответ | Разрешает кэширование любым промежуточным узлам (даже при наличии заголовка `Authorization`). |
| `private` | Ответ | Ресурс предназначен исключительно для одного пользователя. Разделяемые прокси кэшировать его **не имеют права**. |
| `no-cache` | Ответ / Запрос | Кэширование разрешено, но выдача из кэша запрещена без предварительной валидации (`If-None-Match`) на сервере. |
| `no-store` | Ответ / Запрос | Полный запрет на сохранение тела и заголовков ответа в любом энергонезависимом или разделяемом хранилище. |
| `max-age=<N>` | Ответ / Запрос | Время свежести ресурса в секундах. |
| `s-maxage=<N>` | Ответ | Переопределяет `max-age` для разделяемых кэшей (прокси/edge), не затрагивая браузер. |
| `immutable` | Ответ | Сообщает браузеру, что тело файла не изменится в течение всего `max-age`. Исключает условные запросы при перезагрузке (F5). |
| `must-revalidate` | Ответ | Запрещает отдачу устаревшего контента без связи с Origin (игнорирует желание клиента получить stale). |
| `proxy-revalidate` | Ответ | Аналог `must-revalidate`, действующий только на разделяемые кэши. |
| `stale-while-revalidate=<N>` | Ответ | Разрешает мгновенно отдать клиенту устаревший контент, одновременно запуская асинхронное фоновое обновление. |
| `stale-if-error=<N>` | Ответ | Разрешает отдавать устаревший кэш в течение N секунд при сбое или недоступности Origin (коды 500, 502, 503, 504). |

### Таргетированное управление: CDN-Cache-Control и Surrogate-Control

Стандарт **RFC 9213 (Targeted HTTP Cache-Control)** и спецификация **Surrogate-Control** позволяют четко разграничивать директивы для браузеров и промежуточных прокси:

```http
HTTP/1.1 200 OK
Content-Type: text/html; charset=UTF-8
Cache-Control: private, no-cache, no-store
CDN-Cache-Control: public, s-maxage=3600, stale-while-revalidate=60
Surrogate-Key: catalog_page category_laptops
```
В приведенном примере браузер клиента не сохранит страницу, в то время как пограничный обратный прокси сохранит ее на 1 час и привяжет к тегам инвалидации.

### Cache Key Engineering и нормализация

**Cache Key (Ключ кэша)** — уникальный хеш-идентификатор, по которому прокси определяет наличие копии в хранилище.

По умолчанию в Nginx/Angie ключ формируется как:
```nginx
proxy_cache_key "$scheme$proxy_host$request_uri";
```

#### Заголовок Vary и фрагментация кэша

Заголовок `Vary` указывает, какие заголовки входящего запроса должны стать частью Cache Key:
- `Vary: Accept-Encoding` — разделяет кэш на версии: `gzip`, `br`, `zstd`, `identity`. Это стандартное и безопасное поведение.
- `Vary: User-Agent` — **критическая ошибка конфигурации**. Из-за сотен тысяч вариаций User-Agent кэш распадается на уникальные копии, CHR падает до значений <5%, а дисковое пространство мгновенно переполняется.
- `Vary: Cookie` — фактически отключает разделяемый кэш для всех пользователей, у которых установлена хоть одна кука.
- `Vary: *` — делает каждый запрос уникальным, полностью блокируя кэширование по RFC 9111.

#### Нормализация запросов на обратном прокси

Для достижения максимального CHR (>90%) системный администратор должен нормализовать входящие запросы перед вычислением ключа:
1. **Сортировка параметров строки запроса:** `/items?sort=asc&page=1` и `/items?page=1&sort=asc` должны формировать единый ключ.
2. **Удаление аналитических меток:** вырезание маркетинговых параметров (`utm_source`, `utm_campaign`, `yclid`, `gclid`, `_openstat`), которые не влияют на тело ответа бэкенда.
3. **Нормализация кодировок сжатия:** приведение `Accept-Encoding` к единому каноническому виду (`br`, `gzip` или пусто).

### Взаимодействие с подсистемами Linux и хранилищем

1. **Разделяемая память (Shared Memory):**
   Nginx и Angie хранят дерево ключей (rbtree) и метаданные в оперативной памяти (`keys_zone`). Каждый ключ занимает около 128 байт памяти в 64-битной ОС. Зона размером 10 МБ вмещает около 80 000 активных ключей.
2. **Дисковая иерархия (`levels`):**
   Файлы кэша сохраняются с именами в виде MD5-хэша ключа. Параметр `levels=1:2` распределяет файлы по двухуровневой структуре подкаталогов (например, `/var/cache/nginx/c/29/b7f...29c`), предотвращая деградацию производительности файловой системы из-за огромного количества файлов в одном каталоге.
3. **Связка с Linux Page Cache:**
   Тела файлов кэша считываются через стандартные системные вызовы ядра. Если объем оперативной памяти сервера достаточен, часто запрашиваемые файлы оседают в Page Cache ОС, и реального чтения с физического диска (SSD/NVMe) не происходит.
4. **Холодный старт и Cache Loader:**
   При перезапуске Nginx процесс `cache loader` последовательно сканирует все каталоги кэша на диске для наполнения `keys_zone`. На хранилищах объемом >100 ГБ это вызывает шторм дискового ввода-вывода (IOPS). 
   *Решение в Angie 1.9+:* использование параметра `file=` в `proxy_cache_path` для сохранения и восстановления индекса кэша на диск в бинарном формате без полного сканирования.
5. **Оптимизация файловой системы:**
   Для каталогов кэша монтируйте файловые системы (ext4/XFS) с флагами `noatime,nodiratime`. Для микрокэша используйте `tmpfs` (RAM-диск).

### Влияние на Core Web Vitals

| Метрика | Влияние кэширования | Механизм оптимизации |
| :--- | :--- | :--- |
| **LCP (Largest Contentful Paint)** | Сокращение на 300–2500 мс | Мгновенная отдача LCP-изображения и критического CSS из кэша браузера или локального Edge-прокси исключает фазу ожидания генерации ответа Origin (TTFB < 50 мс). |
| **INP (Interaction to Next Paint)** | Снижение задержек на 50–300 мс | Предварительно кэшированные и сжатые JS-бандлы передаются и компилируются быстрее, уменьшая время блокировки Main Thread. |
| **CLS (Cumulative Layout Shift)** | Устранение сдвигов (CLS < 0.05) | Кэширование веб-шрифтов и CSS с `immutable` устраняет мерцание невидимого текста (FOIT) и появление несохраненного стиля (FOUT). |

## Практические сценарии и конфигурации

### Сценарий 1: Долгосрочное кэширование неизменяемой статики (Cache Busting)

Для статических файлов (JS, CSS, WOFF2, изображения), в имя которых встроен хэш содержимого (например, `main.a8f9b2c.js`). Браузер загружает файл ровно один раз и больше никогда не обращается к серверу за валидацией.

```nginx
# Конфигурация Nginx / Angie
server {
    listen 443 ssl default_server;
    server_name example.internal;

    # Статические ассеты с контентным хэшем в имени
    location ~* \.(?:css|js|woff2|avif|webp|png|jpg|svg)$ {
        root /var/www/static;
        try_files $uri =404;

        # Разрешить отдачу предварительно сжатых файлов
        gzip_static on;
        brotli_static on;

        # Запрет на передачу cookie для статики
        access_log off;
        log_not_found off;

        # Годовой срок жизни без повторной валидации
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        add_header X-Content-Type-Options "nosniff" always;
    }

    # HTML страницы (всегда требуют валидации)
    location / {
        root /var/www/html;
        try_files $uri $uri/ /index.html;

        # Браузер обязан проверить ETag перед показом
        add_header Cache-Control "public, no-cache" always;
    }
}
```

### Сценарий 2: Отказоустойчивое кэширование API с фоновым обновлением

Обеспечивает доступность сервиса при падении бэкендов и снижает TTFB до нуля за счет асинхронного обновления устаревших данных по RFC 5861.

```nginx
# Определение зоны кэша на уровне http {}
proxy_cache_path /var/cache/nginx/api_cache
                 levels=1:2
                 keys_zone=api_cache_zone:20m
                 max_size=5g
                 inactive=120m
                 use_temp_path=off;

server {
    listen 443 ssl;
    server_name api.example.internal;

    location /v1/products/ {
        proxy_pass http://backend_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;

        # Подключение зоны кэша
        proxy_cache api_cache_zone;
        proxy_cache_key "$scheme$request_method$host$uri$is_args$args";

        # Время жизни ответов
        proxy_cache_valid 200 302 10m;
        proxy_cache_valid 404 1m;

        # Защита от Stampede: только один запрос идет на бэкенд
        proxy_cache_lock on;
        proxy_cache_lock_timeout 5s;
        proxy_cache_lock_age 10s;

        # Фоновое обновление устаревшего контента
        proxy_cache_background_update on;

        # Отдача stale-ответов при ошибках или во время обновления
        proxy_cache_use_stale error timeout invalid_header updating
                              http_500 http_502 http_503 http_504 http_429;

        # Заголовки для отладки и стандартов
        add_header X-Cache-Status $upstream_cache_status always;
        add_header Cache-Control "public, max-age=60, stale-while-revalidate=600, stale-if-error=86400" always;
    }
}
```

### Сценарий 3: Микрокэширование динамических API (Microcaching)

Применяется для снятия пиковой нагрузки с высоконагруженных эндпоинтов каталогов, поиска и новостных лент. Кэширование всего на 1–2 секунды защищает бэкенд от падения при скачках до 20 000 RPS.

```nginx
# Зона кэша размещается в RAM через tmpfs для максимального IOPS
proxy_cache_path /dev/shm/nginx_microcache
                 levels=1:2
                 keys_zone=micro_zone:10m
                 max_size=500m
                 inactive=60s;

server {
    listen 80;
    server_name catalog.example.internal;

    # Логика обхода кэша для авторизованных пользователей
    set $bypass_cache 0;
    if ($http_authorization != "") {
        set $bypass_cache 1;
    }
    if ($cookie_session_id != "") {
        set $bypass_cache 1;
    }

    location /api/catalog {
        proxy_pass http://catalog_upstream;
        proxy_cache micro_zone;
        proxy_cache_key "$request_method$host$uri$is_args$args";

        # Микрокэш на 1 секунду
        proxy_cache_valid 200 1s;

        # Обход кэша при наличии пользовательской сессии
        proxy_cache_bypass $bypass_cache;
        proxy_no_cache $bypass_cache;

        proxy_cache_lock on;
        proxy_cache_lock_timeout 2s;

        add_header X-Microcache $upstream_cache_status always;
    }
}
```

### Сценарий 4: Нормализация сжатия и Cache Key (Vary: Accept-Encoding)

Предотвращает фрагментацию кэша из-за различий в строке `Accept-Encoding`, нормализуя ее до базовых значений, поддерживаемых бэкендом и сервером.

```nginx
# Нормализация Accept-Encoding на уровне map в http {}
map $http_accept_encoding $normalized_encoding {
    default        "";
    "~*zstd"       "zstd";
    "~*br"         "br";
    "~*gzip"       "gzip";
}

server {
    listen 443 ssl;
    server_name content.example.internal;

    location /assets/ {
        proxy_pass http://assets_upstream;

        # Передача на Origin уже нормализованного заголовка
        proxy_set_header Accept-Encoding $normalized_encoding;

        proxy_cache api_cache_zone;
        # Включение нормализованного типа сжатия в ключ
        proxy_cache_key "$scheme$host$uri$is_args$args|$normalized_encoding";

        proxy_cache_valid 200 24h;
        gzip_vary on;
        add_header Vary "Accept-Encoding" always;
        add_header X-Cache-Status $upstream_cache_status always;
    }
}
```

### Сценарий 5: Управляемая инвалидация кэша (Cache Purge & Ban)

#### Решение для Nginx (модуль ngx_cache_purge) и Angie

Очистка кэша по точному URL методом `PURGE` с ограничением доступа по IP-адресам администраторов и CI/CD:

```nginx
# Списочный доступ к выполнению PURGE
geo $purge_allowed {
    default         0;
    127.0.0.1       1;
    10.0.0.0/8      1;
    192.168.1.0/24  1;
}

server {
    listen 80;
    server_name cache.example.internal;

    location / {
        proxy_pass http://app_upstream;
        proxy_cache api_cache_zone;
        proxy_cache_key "$scheme$request_method$host$request_uri";

        # Включение purge по методу PURGE (поддерживается Angie и Nginx с ngx_cache_purge)
        proxy_cache_purge $purge_allowed;
    }
}
```

#### Решение для Varnish Cache (Теговая инвалидация Surrogate-Key / xkey)

В Varnish кэшированные объекты тегируются заголовком `Surrogate-Key` (или `xkey`), что позволяет сбрасывать целые категории страниц одним запросом:

```vcl
vcl 4.1;
import xkey;

acl purge_acl {
    "localhost";
    "10.0.0.0"/8;
}

sub vcl_recv {
    # Обработка инвалидации по тегу (BAN / PURGE)
    if (req.method == "PURGE") {
        if (!client.ip ~ purge_acl) {
            return (synth(403, "Forbidden"));
        }
        # Очистка по точному URL
        return (purge);
    }

    if (req.method == "BAN") {
        if (!client.ip ~ purge_acl) {
            return (synth(403, "Forbidden"));
        }
        # Инвалидация по тегу Surrogate-Key
        if (req.http.xkey-purge) {
            set req.http.n-gone = xkey.purge(req.http.xkey-purge);
            return (synth(200, "Purged " + req.http.n-gone + " objects"));
        }
        # Обычный бан по регулярному выражению URL
        ban("req.url ~ " + req.url);
        return (synth(200, "Banned"));
    }
}

sub vcl_backend_response {
    # Привязка xkey из заголовка ответа бэкенда
    if (beresp.http.Surrogate-Key) {
        set beresp.http.xkey = beresp.http.Surrogate-Key;
    }
    # Разрешить отдавать stale-контент в течение 1 часа при сбое
    set beresp.grace = 1h;
}

sub vcl_deliver {
    # Удаление служебных заголовков перед отдачей клиенту
    unset resp.http.xkey;
    unset resp.http.Surrogate-Key;
    if (obj.hits > 0) {
        set resp.http.X-Cache = "HIT";
    } else {
        set resp.http.X-Cache = "MISS";
    }
}
```

### Сценарий 6: Негативное кэширование и защита от Cache Penetration

Защищает бэкенд от сканеров уязвимостей и массовых запросов к несуществующим сущностям:

```nginx
server {
    listen 443 ssl;
    server_name api.example.internal;

    location /api/v1/users/ {
        proxy_pass http://user_service;
        proxy_cache api_cache_zone;
        proxy_cache_key "$scheme$host$request_uri";

        # Успешные ответы кэшируются на 5 минут
        proxy_cache_valid 200 5m;

        # 404 кэшируются на 30 секунд для предотвращения сканирования
        proxy_cache_valid 404 30s;

        # Серверные ошибки кэшируются на 5 секунд для снижения нагрузки при падении
        proxy_cache_valid 500 502 503 5s;

        # Не сохранять ответы, содержащие Set-Cookie
        proxy_ignore_headers Expires;
        add_header X-Cache-Status $upstream_cache_status always;
    }
}
```

## Операции и команды

### Диагностика заголовков и проверка статуса кэширования

```bash
# Получение полных заголовков ответа
curl -sI https://example.internal/assets/app.js
# → HTTP/2 200
# → content-type: application/javascript; charset=utf-8
# → date: Wed, 21 Oct 2026 10:00:00 GMT
# → cache-control: public, max-age=31536000, immutable
# → etag: "68689769-ab42"
# → age: 450
# → vary: Accept-Encoding
# → x-cache-status: HIT

# Проверка стандартизованного заголовка Cache-Status (RFC 9211)
curl -sI https://api.example.internal/v1/items/1 | grep -iE "cache-status|x-cache"
# → x-cache-status: HIT
# → cache-status: edge-proxy-01; hit; ttl=245

# Расчет остаточного времени жизни в кэше: Real TTL = max-age - Age
curl -sI https://example.internal/style.css | awk '
  tolower($1) ~ /^cache-control:/ { for (i=1;i<=NF;i++) if ($i ~ /max-age=/) { split($i,a,"[=,]"); ma=a[2] } }
  tolower($1) ~ /^age:/ { age=$2 }
  END { print "Остаточный TTL:", ma - age, "секунд" }'
# → Остаточный TTL: 3150 секунды
```

### Проверка механизмов условной валидации (304 Not Modified)

```bash
# Извлечение ETag из первого запроса
ETAG=$(curl -sI https://example.internal/index.html | grep -i '^etag:' | awk '{print $2}' | tr -d '\r')

# Выполнение условного запроса с If-None-Match
curl -sI -H "If-None-Match: $ETAG" https://example.internal/index.html
# → HTTP/2 304 Not Modified
# → date: Wed, 21 Oct 2026 10:05:00 GMT
# → etag: "68689769-ab42"
# → cache-control: public, no-cache

# Выполнение условного запроса по дате (If-Modified-Since)
curl -sI -H "If-Modified-Since: Wed, 21 Oct 2026 10:00:00 GMT" https://example.internal/index.html
# → HTTP/2 304 Not Modified
```

### Принудительная очистка кэша (Purge и Ban)

```bash
# Очистка одного ресурса на Nginx / Angie методом PURGE
curl -sI -X PURGE "http://127.0.0.1/api/v1/products/42"
# → HTTP/1.1 200 OK
# → Server: angie
# → Content-Type: text/html
# → Content-Length: 265
# → Successful purge

# Очистка ресурса в Varnish Cache через HTTP
curl -sI -X PURGE http://127.0.0.1/catalog/laptops
# → HTTP/1.1 200 Purged

# Массовая инвалидация по тегу Surrogate-Key (xkey) в Varnish
curl -sI -X BAN -H "xkey-purge: category_laptops" http://127.0.0.1/
# → HTTP/1.1 200 Purged 42 objects

# Инвалидация через CLI Varnish (бан по регулярному выражению)
varnishadm "ban req.url ~ ^/static/.*\.css$"
# → 200
```

### Мониторинг и аудит кэша в ОС Linux

```bash
# Проверка дискового объема каталога кэша
du -sh /var/cache/nginx/api_cache/
# → 2.4G    /var/cache/nginx/api_cache/

# Подсчет количества файлов в кэше
find /var/cache/nginx/api_cache/ -type f | wc -l
# → 38412

# Инспекция внутреннего состояния кэша в Angie через HTTP API
curl -s http://127.0.0.1/status/http/caches/api_cache_zone | jq .
# → {
# →   "size": 2576980377,
# →   "max_size": 5368709120,
# →   "cold": false,
# →   "hit": { "responses": 1845020, "bytes": 4892104512 },
# →   "miss": { "responses": 45210, "bytes": 120450123 },
# →   "expired": { "responses": 12104, "bytes": 32014520 }
# → }

# Расчет Cache Hit Ratio (CHR) в реальном времени из access log Nginx
tail -n 50000 /var/log/nginx/access.log | awk '{print $NF}' | sort | uniq -c | awk '
  /HIT/ {hit+=$1} /MISS/ {miss+=$1} /EXPIRED/ {exp+=$1} /BYPASS/ {byp+=$1}
  END {
    total = hit + miss + exp + byp;
    if (total > 0) printf "CHR: %.2f%% (HIT: %d, MISS: %d, EXPIRED: %d, BYPASS: %d)\n", (hit/total)*100, hit, miss, exp, byp
  }'
# → CHR: 94.12% (HIT: 47060, MISS: 1840, EXPIRED: 600, BYPASS: 500)

# Мониторинг статистики Varnish в реальном времени
varnishstat -1 -f MAIN.cache_hit,MAIN.cache_miss,MAIN.cache_hitpass
# → MAIN.cache_hit        1420950         0.00 Cache hits
# → MAIN.cache_miss         65402         0.00 Cache misses
# → MAIN.cache_hitpass       1200         0.00 Cache hits for pass
```

## Диагностика и устранение неполадок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Низкий Cache Hit Ratio (<80%)** | Высокий RPS на Origin, большинство запросов завершаются `MISS` или `BYPASS` | Проанализировать access log: `grep -i "MISS" /var/log/nginx/access.log \| head -n 30` | Нормализовать query-параметры (удалить `utm_*`), убрать случайные куки из Cache Key, проверить, не отдает ли Origin `Cache-Control: private` или `Set-Cookie`. |
| **Утечка персональных данных (Session Hijacking)** | Один пользователь видит профиль или корзину другого пользователя | Проверить заголовки ответов: `curl -sI URL \| grep -iE "set-cookie\|cache-control"` | **Критический инцидент.** Запретить кэширование при наличии заголовка `Set-Cookie` или `Authorization`. Настроить `proxy_cache_bypass $cookie_session`. Удалить скомпрометированный кэш (`rm -rf /var/cache/nginx/*`). |
| **Cache Stampede (Thundering Herd)** | При истечении TTL одного популярного URL CPU бэкенда подскакивает до 100%, сыпятся 502/504 ошибки | Мониторинг апстрима в момент сброса TTL, появление сотен параллельных `MISS` в логе | Включить `proxy_cache_lock on;`, `proxy_cache_lock_timeout 5s;`, активировать `proxy_cache_use_stale updating` и `proxy_cache_background_update on;`. |
| **Отдача устаревшего контента (Stale Data)** | Клиенты видят старые версии страниц после релиза или обновления в БД | Сравнить `Age` и `max-age`: `curl -sI URL \| grep -iE "age\|cache-control"` | Использовать Cache Busting (хэши в именах файлов). Для динамики настроить автоматическую отправку `PURGE` или `BAN` из CI/CD или обработчика очереди событий (CDC). |
| **Фрагментация ключей из-за `Vary`** | Один и тот же ресурс сохраняется на диске в десятках копий | `grep "Vary" /var/log/nginx/access.log`, проверить заголовки апстрима | Удалить `Vary: User-Agent` и `Vary: Cookie` на бэкенде. Оставить только `Vary: Accept-Encoding` и нормализовать его через директиву `map`. |
| **Деградация ETag при компрессии** | Условные запросы возвращают `200 OK` вместо `304 Not Modified`, трафик растет | `curl -sI URL` возвращает `ETag: W/"..."` вместо `ETag: "..."` | Nginx превращает сильный ETag в слабый при динамическом Gzip/Brotli. Перевести статические ресурсы на прекомпрессию на этапе сборки: `gzip_static on; brotli_static on;`. |
| **Кэш не сохраняется на диск (Всегда MISS)** | Директория кэша пуста, в логах фиксируется только статус `MISS` | Проверить права доступа: `ls -ld /var/cache/nginx/proxy_cache` и заголовки апстрима | 1) Дать права пользователю процесса (`chown -R nginx:nginx /var/cache/nginx`). 2) Проверить, не возвращает ли бэкенд `X-Accel-Expires: 0` или `Cache-Control: no-cache, no-store`. |
| **Исчерпание дискового пространства (Disk Full)** | Ошибки `[crit] pwrite() failed (28: No space left on device)` в error.log | `df -h /var/cache/nginx`, `du -sh /var/cache/nginx/*` | Задать лимит `max_size` в `proxy_cache_path`. Уменьшить параметр `inactive` (например, с `7d` до `12h`). Вынести кэш на отдельный логический том (LVM). |
| **Ошибка 403 Forbidden при вызове Purge** | Запрос `curl -X PURGE URL` возвращает `403 Forbidden` | Проверить директиву `geo $purge_allowed` или ACL в Varnish | Добавить IP-адрес вызывающего узла (раннера CI/CD или скрипта деплоя) в список разрешенных подсетей. |
| **Отравление кэша (Cache Poisoning)** | Кэш отдает неверные редиректы или сторонний контент | Проверить параметры ключа кэша и незащищенные входящие заголовки (`X-Forwarded-Host`) | Не включать невалидированные заголовки в Cache Key. Использовать строгую директиву `proxy_set_header Host $host;` вместо передачи произвольных клиентских заголовков. |

## Рекомендации

### Базовые правила

1. **Разделяйте политики для статики и динамики:**
   - Для статики с хэшами в именах: `Cache-Control: public, max-age=31536000, immutable`.
   - Для HTML документов: `Cache-Control: public, no-cache` (обязательная валидация ETag).
   - Для динамических API: короткий TTL + `stale-while-revalidate` или микрокэширование.
2. **Не используйте абсолютный заголовок `Expires`:**
   Он зависит от синхронизации системных часов клиента и сервера. Используйте относительный `Cache-Control: max-age`.
3. **Всегда передавайте `Vary: Accept-Encoding`:**
   Если контент сжимается, этот заголовок обязателен, чтобы промежуточные кэши не отдали Brotli/Zstd клиенту, поддерживающему только чистый текст.
4. **Очищайте ключ кэша от аналитического мусора:**
   Сортируйте GET-параметры и вырезайте `utm_*`, `gclid`, `fbclid`, `_openstat` на уровне обратного прокси.
5. **Предотвращайте утечку заголовка `Set-Cookie`:**
   Если ответ кэшируется на прокси, директива `proxy_hide_header Set-Cookie;` обязательна, чтобы кука сессии одного пользователя не разошлась остальным.
6. **Кэшируйте негативные ответы:**
   Директива `proxy_cache_valid 404 30s;` защищает бэкенд от сканирования и ошибок опечаток пользователей.

### Для DevOps / SRE / SysAdmin

1. **Тюнинг дисковой подсистемы под кэш:**
   - Каталоги кэша должны размещаться на быстрых NVMe накопителях или tmpfs (для микрокэша).
   - Файловые системы должны монтироваться с опциями `noatime,nodiratime`.
   - Устанавливайте `use_temp_path=off` в `proxy_cache_path`, чтобы запись временного файла и его перемещение в кэш происходили внутри одной файловой системы без лишнего копирования между дисками.
2. **Ограничение размеров и ротация:**
   - Всегда задавайте явный `max_size` в конфигурации кэша, оставляя запас минимум в 20–25% свободного пространства на томе для временных файлов.
   - Настраивайте параметр `inactive`, отсекающий редко запрашиваемые объекты быстрее, чем закончится их номинальный TTL.
3. **Мониторинг и алертинг (Observability):**
   - Выводите `$upstream_cache_status` в логи веб-сервера структурированным JSON-форматом.
   - Настройте Prometheus-экспортер (Angie built-in `/status/prometheus` или `nginx-prometheus-exporter`) и отслеживайте:
     - `Cache Hit Ratio < 85%` (предупреждение о деградации).
     - Резкий рост статусов `EXPIRED` или `UPDATING` (сигнал о всплеске Stampede).
     - Заполнение диска кэша `> 85%`.
4. **Прогрев кэша (Cache Warming):**
   - После перезапуска сервисов или деплоя нового релиза запускайте прогревочные скрипты (через список URL из `sitemap.xml` или топ-1000 запросов из логов за прошлый день), чтобы пользователи не испытывали задержек холодного старта.
5. **Интеграция инвалидации в CI/CD:**
   - Автоматизируйте сброс кэша по тегам (`Surrogate-Key`) или конкретным маршрутам в пайплайнах деплоя после обновления версий бэкенда.
6. **Защита от шторма при рестарте (Angie):**
   - В высоконагруженных системах используйте Angie с параметром `file=` в `proxy_cache_path`, чтобы исключить этап длительного сканирования диска Cache Loader при перезагрузке процесса.

## Дополнительная информация

### Связанные файлы

- [HTTP-кэширование: Механизмы и управление](../../../Networking/Protocols/HTTP/http_caching.md) — фундаментальные стандарты RFC 9111, условные запросы, ETag, Range-запросы.
- [Кэширование: Обзор](../../../Concepts/Caching/caching_overview.md) — уровни кэширования в архитектуре, аппаратные компромиссы, Redis/Memcached.
- [Паттерны кэширования](../../../Concepts/Caching/caching_patterns.md) — Cache-aside, Read-through, Write-through, Write-back, CDC.
- [Серверное кэширование в Nginx](../../Nginx/Performance/Caching/proxy_caching.md) — глубокая настройка `proxy_cache_*`, ключи, уровни каталогов, Page Cache.
- [Клиентское кэширование в Nginx](../../Nginx/Performance/Caching/client_caching.md) — директивы `expires`, генерация `Cache-Control`, ETag для статики.
- [Микрокэширование в Nginx](../../Nginx/Performance/Caching/microcaching.md) — тонкости настройки краткосрочного кэширования для динамических сервисов.
- [Мониторинг кэширования в Nginx](../../Nginx/Performance/Caching/monitoring.md) — аудит метрик кэша, разбор `$upstream_cache_status`, интеграция с Prometheus.
- [Кэширование в Apache](../../Apache/apache_caching.md) — модули `mod_cache`, `mod_cache_disk`, `mod_socache`.
- [Оптимизация производительности веб-приложений: Обзор](./overview.md) — комплексный обзор ускорения веб-систем.
- [Компрессия контента на веб-сервере](./server_compression.md) — gzip, brotli, zstd, статическое сжатие и влияние на ETag.
- [Web Vitals](./web_vitals.md) — метрики LCP, INP, CLS и методы их улучшения.
- [Circuit Breaker и Degradation](./circuit_breaker_and_degradation.md) — отдача stale-кэша при деградации upstream.
- [Structured Logging для Performance](./structured_logging_for_performance.md) — протоколирование метрик кэша в access logs.

### RFC и спецификации

- **RFC 9111** — HTTP Caching (актуальный базовый стандарт, заменивший RFC 7234).
- **RFC 9211** — The Cache-Status HTTP Response Header.
- **RFC 9213** — Targeted HTTP Cache-Control (стандарт заголовков целевого кэширования).
- **RFC 5861** — HTTP Cache-Control Extensions for Stale Content (`stale-while-revalidate`, `stale-if-error`).
- **RFC 7232** — HTTP/1.1 Conditional Requests (валидаторы `ETag`, `If-None-Match`, `Last-Modified`).

### Официальные ресурсы

- [Nginx Documentation: Module ngx_http_proxy_module (proxy_cache)](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_cache)
- [Angie Documentation: Кэширование проксированных ответов](https://angie.software/ru/configuration/http/proxy_cache/)
- [Varnish Cache Documentation: HTTP Caching Concepts & VCL Guide](https://varnish-cache.org/docs/)
- [MDN Web Docs: HTTP Caching](https://developer.mozilla.org/en-US/docs/Web/HTTP/Caching)
