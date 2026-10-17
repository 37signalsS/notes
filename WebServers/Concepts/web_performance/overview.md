# Оптимизация производительности веб-приложений: Обзор

**Актуально для:** Nginx 1.26+, Angie 1.4+ / 1.12.x, Linux Kernel 5.15+ / 6.x, HTTP/2 (RFC 9113), HTTP/3 (RFC 9114)

## Определения

- **Производительность веб-приложений (Web Performance)** — комплексная инженерная дисциплина, направленная на минимизацию задержек доставки ресурсов по сети, ускорение рендеринга страниц на стороне клиента и оптимизацию вычислительной утилизации инфраструктуры (ядро ОС, сетевые сокеты, обратные прокси и бэкенд-серверы).
- **Core Web Vitals (CWV)** — стандартизированные метрики качества пользовательского опыта, отражающие реальное восприятие скорости и стабильности веб-интерфейса:
  - **LCP (Largest Contentful Paint):** Скорость загрузки основного визуального блока (hero image, баннер, заголовок H1). Порог «хорошо»: **< 2.5 с**.
  - **INP (Interaction to Next Paint):** Отзывчивость интерфейса при взаимодействии пользователя со страницей (клик, тап, нажатие клавиши). Порог «хорошо»: **< 200 мс**.
  - **CLS (Cumulative Layout Shift):** Метрика визуальной стабильности верстки, оценивающая суммарный сдвиг элементов в процессе загрузки. Порог «хорошо»: **< 0.1**.
  - *Детальный разбор метрик:* [web_vitals.md](./web_vitals.md).
- **Time To First Byte (TTFB)** — суммарное время от момента инициации HTTP-запроса клиентом до получения первого байта тела ответа от сервера. Включает DNS-резолвинг, сетевой RTT, TCP/TLS-рукопожатие, ожидание в очереди прокси и генерацию ответа апстримом. Целевой показатель в локальной инфраструктуре: **< 200 мс** (для динамических ответов) и **< 50 мс** (для кэшированного контента).
- **RUM (Real User Monitoring / Field Data)** — мониторинг реальных пользователей (полевые данные), собирающий метрики непосредственно из браузеров посетителей на различных типах клиентских устройств и сетевых соединений. Противопоставляется **Lab Data** (лабораторные/синтетические данные) — тестам в строго контролируемой изолированной среде с эмуляцией задержек.
- **Total Blocking Time (TBT)** — суммарное время между первой отрисовкой контента (FCP) и переходом страницы в интерактивное состояние (TTI), когда главный поток браузера (Main Thread) заблокирован задачами длительностью свыше 50 мс. Лабораторный аналог метрики INP. Цель: **< 200 мс**.
- **Early Hints (HTTP 103)** — статус-код предварительного ответа сервера (RFC 8297), отправляющий клиенту заголовки `Link` с критическими ресурсами до завершения генерации основного HTML-документа бэкендом.
- **Speculation Rules API** — декларативный JSON-интерфейс в браузере для фонового предзагрузки (`prefetch`) или фонового рендеринга (`prerender`) страниц вероятного следующего перехода пользователя, заменивший устаревшие теги `<link rel="prefetch">` и `<link rel="prerender">`.
- **Fetch Priority API** — программное управление приоритетами очередей сетевого загрузчика браузера через атрибут `fetchpriority="high|low|auto"`.
- **Off-Main-Thread Architecture** — архитектурный паттерн выноса ресурсоемких вычислений (аналитика, криптография, разбор JSON/декодирование) из главного потока браузера в Web Workers с использованием API `scheduler.yield()`.
- **Cache Hit Ratio (CHR) и Offload Ratio** — фундаментальные показатели эффективности кэширования:
  - `Cache Hit Ratio = (Cache Hits / Total Requests) * 100%` — доля запросов, обслуженных из кэша;
  - `Offload Ratio = ((Origin Requests Without Cache - Origin Requests With Cache) / Origin Requests Without Cache) * 100%` — степень снижения нагрузки на бэкенд благодаря кэшированию и сжатию на уровне обратного прокси.
- **Zero-Copy I/O (`sendfile`, `splice`)** — механизм ядра Linux, позволяющий передавать байты файла с диска напрямую в сетевой сокет через page cache ядра без промежуточного копирования данных в адресное пространство пользовательского процесса (user-space), снижая контекстные переключения CPU и нагрузку на шину RAM.
- **Kernel TLS (kTLS)** — функциональность ядра Linux (начиная с версий 4.17+ / 5.x), обеспечивающая симметричное шифрование и дешифрование TLS-пакетов (AES-GCM, ChaCha20-Poly1305) на уровне ядра, что позволяет применять `sendfile()` для зашифрованных HTTPS-сессий.
- **Performance Budget (Бюджет производительности)** — набор жестких пороговых лимитов на размер передаваемых артефактов (JS, CSS, изображения), сетевые задержки (TTFB, LCP) и время блокировки потока, нарушение которых в CI/CD блокирует релиз.
- **Head-of-Line (HoL) Blocking** — явление задержки очереди запросов или пакетов из-за блокировки предшествующего элемента:
  - в HTTP/1.1 возникает на уровне очереди HTTP-запросов в одном TCP-соединении;
  - в HTTP/2 устранено на уровне HTTP-потоков за счет мультиплексирования, но сохраняется на уровне TCP-транспорта (потеря одного IP-пакета замораживает чтение всех потоков в сокете);
  - в HTTP/3 (QUIC поверх UDP) полностью устранено на транспортном уровне благодаря независимой обработке UDP-датаграмм для каждого потока.
- **BDP (Bandwidth-Delay Product) и алгоритмы контроля перегрузки (BBR)** — расчетный объем данных в сетевом канале (`Пропускная способность * RTT`), определяющий оптимальный размер буферов сокетов. Алгоритм BBR (Bottleneck Bandwidth and RTT) управляет окном отправки на основе непрерывного измерения физической емкости канала и минимальной задержки, исключая переполнение буферов сетевого оборудования (bufferbloat), присущее алгоритмам на основе потерь (CUBIC, Reno).
- **Cache Stampede (Thundering Herd)** — каскадный сбой инфраструктуры при одновременном обращении сотен параллельных запросов к ресурсу в момент истечения его TTL в кэше, вызывающий лавинообразную перегрузку CPU бэкенда и пула соединений СУБД.

## Основные концепции и архитектура

### Архитектура уровней оптимизации

Оптимизация производительности веб-приложений строится по сквозной многоуровневой модели:

```
[ Клиент / Браузер ] (DOM/CSSOM, Critical Rendering Path, Web Workers, CWV)
        │  ▲
        │  │ L4 Сеть: TCP/UDP, BBR, TLS 1.3 0-RTT, MTU/MSS
        ▼  │
[ Сетевой стек ядра Linux ] (qdisc fq, somaxconn, autotuning TCP-буферов, kTLS)
        │  ▲
        │  │ L7 Транспорт: HTTP/2 мультиплексирование, HTTP/3 (QUIC), epoll I/O
        ▼  │
[ Обратный прокси (Nginx / Angie) ] (Microcaching, Zstd/Brotli, proxy_cache_lock)
        │  ▲
        │  │ L7 Upstream: Keepalive connection pool, Unix Domain Sockets
        ▼  │
[ Бэкенд и СУБД ] (Пул процессов/горутин, индексы БД, query cache)
```

| Уровень | Компоненты | Ключевые механизмы оптимизации | Зона ответственности |
| :--- | :--- | :--- | :--- |
| **Клиент** | Браузер, JavaScript runtime | Critical Rendering Path, Main Thread offloading, Fetch Priority, Speculation Rules | Frontend / Client Eng |
| **Сетевой стек L4** | Ядро Linux, сетевые интерфейсы, netfilter | `somaxconn`, `tcp_max_syn_backlog`, BBR, TCP Fast Open, буферы `rmem`/`wmem`, kTLS | SysAdmin / SRE |
| **Транспорт L7** | TLS 1.3, HTTP/2, HTTP/3 (QUIC) | Сессионные тикеты, ALPN, сжатие заголовков HPACK/QPACK, устранение HoL-блокировок | DevOps / SysAdmin |
| **Обратный прокси** | Nginx, Angie | `epoll`, `sendfile`, `tcp_nopush`, `tcp_nodelay`, Microcaching, Zstd/Brotli, `stale-while-revalidate` | DevOps / SRE |
| **Апстрим и Бэкенд** | Приложения (Go, Python, Node, PHP-FPM), СУБД | Upstream Keepalive Connection Pools, Unix domain сокеты, оптимизация запросов, индексы | Backend / SRE |

### Жизненный цикл загрузки страницы и анатомия задержек

Полный цикл доставки веб-страницы клиенту состоит из последовательных этапов, каждый из которых диагностируется и оптимизируется независимо:

```
Клиент                                                          Сервер
  │─── DNS Lookup ───────────────────────────────────────────────>│ (Кэш resolver / dns-prefetch)
  │─── TCP SYN ──────────────────────────────────────────────────>│
  │<── TCP SYN-ACK ───────────────────────────────────────────────│ (1 RTT: TCP Handshake / TFO)
  │─── TCP ACK + TLS ClientHello ────────────────────────────────>│
  │<── TLS ServerHello + Finished ────────────────────────────────│ (1 RTT: TLS 1.3 Handshake)
  │─── HTTP GET Request ─────────────────────────────────────────>│
  │                                     [Обратный прокси]          │
  │                                     ├─ Cache Lookup (HIT?)    │ (0 мс при кэше)
  │                                     └─ Upstream dispatch      │
  │                                        ├─ Keepalive reuse     │
  │                                        └─ App/DB computation  │
  │<── HTTP Response (Первый байт / TTFB) ─────────────────────────│ (Суммарный TTFB)
  │<── HTTP Response Body (Content Download) ─────────────────────│ (Brotli/Zstd, TCP cwnd)
  │
[Браузер: Парсинг и рендеринг]
  ├── DOM Construction (Разбор HTML)
  ├── CSSOM Construction (Блокирующие CSS-файлы)
  ├── Render Tree (Объединение DOM + CSSOM)
  ├── Layout (Расчет геометрии и размеров)
  └── Paint & Composite (Отрисовка пикселей на экране) -> LCP
```

1. **DNS Lookup:** Разрешение доменного имени в IP-адрес. Устраняется локальным кэшированием resolver (`systemd-resolved`, `dnsmasq`), поддержанием актуальных TTL (от 300 до 3600 с) и подсказками `<link rel="dns-prefetch">`.
2. **TCP Handshake:** Классическое трехстороннее рукопожатие (SYN → SYN-ACK → ACK), занимающее 1 RTT. Оптимизируется включением TCP Fast Open (`tcp_fastopen`).
3. **TLS Handshake:** В протоколе TLS 1.3 занимает ровно 1 RTT, либо 0 RTT при повторном сессионном возобновлении (Session Resumption / 0-RTT tickets). Оптимизируется включением OCSP Stapling и сессионных тикетов.
4. **TTFB (Time To First Byte):** Время ожидания ответа. При кэш-промахе складывается из сетевого времени передачи запроса на сервер, задержки в очереди обратного прокси, времени передачи запроса на бэкенд по keepalive-пулу, выполнения логики приложения, запросов в СУБД и передачи первого пакета ответа клиенту.
5. **Content Download:** Передача тела ответа. Скорость определяется размером передаваемых данных (сжатие Brotli/Zstd/Gzip), текущим размером окна перегрузки TCP (`cwnd`) и пропускной способностью канала.
6. **Critical Rendering Path (Критический путь рендеринга):** Браузер парсит HTML в DOM, загружает и парсит блокирующие CSS в CSSOM, строит дерево отрисовки (Render Tree), рассчитывает координаты элементов (Layout) и отрисовывает пиксели (Paint).
7. **Интерактивность:** Выполнение JavaScript, связывание обработчиков событий (hydration/event binding) и освобождение главного потока (Main Thread) для достижения порога INP < 200 мс.

### Критический путь рендеринга (Critical Rendering Path)

Браузер выполняет рендеринг строго поэтапно:

| Фаза | Описание | Инфраструктурная и серверная оптимизация |
| :--- | :--- | :--- |
| **DOM** | Парсинг потока байт HTML в узлы дерева документов | Потоковая отдача (Chunked Transfer), Early Hints (103), сжатие HTML (Zstd/Brotli) |
| **CSSOM** | Построение дерева стилей из CSS-файлов | Выделение Critical CSS, предзагрузка (`<link rel="preload">`), HTTP/2 Server Push (устарело) / Early Hints |
| **Render Tree** | Сопоставление видимых узлов DOM с правилами CSSOM | Исключение неиспользуемых селекторов, устранение блокирующего CSS |
| **Layout (Reflow)** | Вычисление точных координат и размеров блоков | Явное задание размеров (`width`, `height`, `aspect-ratio`) для медиа и контейнеров |
| **Paint & Composite** | Растеризация элементов и вывод слоев на GPU | Локальное кэширование WOFF2-шрифтов, `font-display: swap`, аппаратно-ускоренные трансформации |

### Эволюция транспортных протоколов: HTTP/1.1 vs HTTP/2 vs HTTP/3

Сетевой протокол напрямую определяет накладные расходы на передачу данных:

| Характеристика | HTTP/1.1 | HTTP/2 (RFC 9113) | HTTP/3 / QUIC (RFC 9114) |
| :--- | :--- | :--- | :--- |
| **Транспорт** | TCP | TCP | UDP (QUIC) |
| **Формат данных** | Текстовый | Бинарный (фреймы, потоки) | Бинарный (фреймы, потоки) |
| **Мультиплексирование** | Нет (ограничение 6 сокетов на хост) | Да (сотни потоков в одном TCP-соединении) | Да (независимые потоки в UDP) |
| **HoL Blocking (L7)** | Присутствует | Устранено | Устранено |
| **HoL Blocking (L4)** | Присутствует | Присутствует (потеря сегмента TCP блокирует сокет) | **Полностью устранено** |
| **Время установки сессии** | 2-3 RTT (TCP + TLS) | 2 RTT (TCP + TLS 1.3) / 1 RTT | **1 RTT (QUIC + TLS 1.3) / 0-RTT** |
| **Сжатие заголовков** | Отсутствует | HPACK (статическая/динамическая таблицы) | QPACK (устойчив к потере пакетов) |
| **Миграция соединения** | Разрыв при смене IP (Wi-Fi ↔ LTE) | Разрыв при смене IP | **Connection ID (сессия сохраняется бесшовно)** |

*Детальная архитектура и сравнительный анализ:* [http2_http3.md](./http2_http3.md).

### Механизмы приоритизации и управления загрузкой

1. **Fetch Priority API:**
   - Позволяет разработчикам и веб-серверам подсказывать браузеру реальную важность ресурсов.
   - `fetchpriority="high"` — назначается на ключевое LCP-изображение и критические шрифты;
   - `fetchpriority="low"` — назначается на второстепенную аналитику, скрипты трекинга, виджеты чатов;
   - `fetchpriority="auto"` — стандартная внутренняя эвристика браузера.
2. **Native Lazy Loading:**
   - `loading="lazy"` — отложенная загрузка изображений и `iframe` до момента их приближения к области видимости экрана (viewport).
   - **Критическое правило:** атрибут `loading="lazy"` строго запрещено использовать на LCP-элементе (Hero image), так как это искусственно откладывает его загрузку на 500–1500 мс и разрушает Core Web Vitals.
3. **Resource Hints:**
   - `<link rel="dns-prefetch">` — предварительное разрешение DNS (для внешних доменов).
   - `<link rel="preconnect">` — предварительное рукопожатие TCP и TLS (для критических внешних ресурсов).
   - `<link rel="preload">` — принудительная внеочередная загрузка критического ресурса (WOFF2-шрифт, LCP-изображение) с указанием типа `as="font|image|style"`.
4. **Speculation Rules API:**
   - Декларативная JSON-структура, позволяющая браузеру на основе пользовательских паттернов (наведение курсора, скролл к ссылке) выполнять бесшумный префетч или пререндер следующей страницы, обеспечивая мгновенный переход (0 мс Navigation Timing).

### Серверное кэширование и стратегии отдачи

Обратный прокси (Nginx/Angie) выступает первой линией обороны инфраструктуры:

1. **Микрокэширование (Microcaching):**
   - Кэширование динамических GET-ответов бэкенда на сверхкороткие интервалы (от 1 до 5 секунд).
   - Позволяет выдерживать всплески нагрузки (traffic spikes) до десятков тысяч RPS без деградации времени ответа базы данных.
2. **Асинхронная ревалидация (`stale-while-revalidate` / `stale-if-error`):**
   - Клиент мгновенно получает устаревший кэшированный ответ (`stale`), пока прокси в фоновом режиме отправляет запрос апстриму для обновления кэша.
   - Защищает от всплесков задержек при истечении TTL и обеспечивает отдачу контента даже при временном падении бэкенда (`proxy_cache_use_stale error timeout updating;`).
3. **Защита от лавины запросов (Cache Stampede / Thundering Herd):**
   - Использование директивы `proxy_cache_lock on;`: только один запрос отправляется на бэкенд для заполнения кэша, остальные ждут в очереди и затем обслуживаются из свежего кэша.
   - Использование `proxy_cache_lock_timeout` и `proxy_cache_lock_age` для предотвращения зависания при медленных ответах бэкенда.

*Детальная настройка директив кэширования:* [caching.md](./caching.md).

### Сжатие данных: Gzip, Brotli и Zstandard (Zstd)

Сжатие текстовых ресурсов (HTML, CSS, JS, SVG, JSON) снижает объем передаваемого трафика на 60–85%:

- **Gzip:** Универсальный стандарт (RFC 1952), поддерживается 100% клиентов. Оптимальный уровень сжатия на лету — 5–6 (уровни 7–9 дают прирост сжатия <2% при кратном росте нагрузки на CPU).
- **Brotli (`br`):** Стандарт сжатия (RFC 7932), превосходящий Gzip на 15–25% по коэффициенту сжатия текстовых ресурсов благодаря статическому словарю. Для сжатия на лету (on-the-fly) в Nginx/Angie используется уровень 4–5. Для предкомпрессии статических файлов в CI/CD используется максимальный уровень 11 (`brotli_static on;`).
- **Zstandard (`zstd`):** Современный стандарт (RFC 9659, поддерживается в Angie и современных браузерах на базе Chromium с 2024+ года). Обеспечивает коэффициент сжатия на уровне Brotli при скорости сжатия в 3–5 раз выше и скорости распаковки до 1.5 ГБ/с на ядро CPU.
- **Предварительное сжатие (Static Pre-compression):** Сжатие артефактов на этапе сборки/CI (`gzip_static on;`, `brotli_static on;`, `zstd_static on;`) полностью исключает затраты CPU веб-сервера на сжатие в runtime и позволяет задействовать `sendfile()`.

*Сравнение алгоритмов и конфигурация:* [server_compression.md](./server_compression.md).

### Взаимосвязь инфраструктурных метрик и Core Web Vitals

Инфраструктурные параметры напрямую формируют значения клиентских метрик:

| Инфраструктурный фактор | Влияние на клиентскую метрику | Механизм влияния |
| :--- | :--- | :--- |
| **Высокий TTFB (> 500 мс)** | Критическое ухудшение **LCP** и **FCP** | Браузер не может начать загрузку критических CSS/JS и изображений до получения HTML-документа |
| **Отсутствие Keepalive к апстриму** | Рост **TTFB** на величину RTT бэкенда | На каждый запрос тратится 1 RTT на TCP handshake + накладные расходы на аллокацию сокетов |
| **Динамическое сжатие на лету с высоким уровнем** | Рост **TTFB** и утилизации CPU сервера | Задержка буферизации ответа перед отдачей клиенту превышает выигрыш от сжатия |
| **Отсутствие кэширования статики (`immutable`)** | Ухудшение **LCP** при повторных визитах | Браузер отправляет условные запросы `304 Not Modified`, тратя сетевой RTT вместо мгновенного чтения из памяти/диска |
| **Нестабильные размеры контейнеров / шрифтов** | Ухудшение **CLS** (> 0.1) | Перерисовка геометрии страницы при подгрузке веб-шрифтов (FOUT/FOIT) и позднем рендеринге баннеров |
| **Блокирующий JavaScript в `<head>`** | Рост **TBT** и ухудшение **INP** (> 200 мс) | Парсер останавливается для загрузки и выполнения JS, блокируя главный поток интерфейса |

## Практические сценарии и конфигурация

### Сценарий 1: Углубленный сетевой анализ задержек и TTFB через curl

Для точной локализации узкого места (DNS, TCP, TLS, очередь прокси, бэкенд) используется детальное профилирование через `curl`:

```bash
# Создание шаблона формата таймингов
cat > /tmp/curl_format.txt << 'EOF'
     DNS Lookup:  %{time_namelookup}s\n
   TCP Handshake:  %{time_connect}s (разница: %{time_connect} - %{time_namelookup})\n
   TLS Handshake:  %{time_appconnect}s (разница: %{time_appconnect} - %{time_connect})\n
     Pretransfer:  %{time_pretransfer}s\n
Starttransfer (TTFB): %{time_starttransfer}s (время ожидания сервера: %{time_starttransfer} - %{time_pretransfer})\n
      Total Time:  %{time_total}s\n
        Size Downloaded: %{size_download} bytes\n
       HTTP Code:  %{http_code}\n
EOF

# Выполнение тестового запроса к эндпоинту
curl -w "@/tmp/curl_format.txt" -o /dev/null -s "https://example.com/api/v1/products"
# →      DNS Lookup:  0.012105s
# →    TCP Handshake:  0.034512s
# →    TLS Handshake:  0.068214s
# →      Pretransfer:  0.068289s
# → Starttransfer (TTFB): 0.185412s
# →       Total Time:  0.221540s
# →  Size Downloaded: 14520 bytes
# →        HTTP Code:  200
```

**Интерпретация результатов:**
- Если `DNS Lookup > 0.050s` — проблемы с DNS-резолвером или неэффективный TTL записей.
- Если `TCP Handshake > 0.050s` при локальном доступе — сетевая деградация канала или переполнение SYN-backlog на сервере.
- Если `TLS Handshake - TCP Handshake > 0.080s` — не оптимизирован TLS (отсутствует session resumption, не настроен OCSP Stapling, избыточная длина цепочки сертификатов).
- Если `Starttransfer - Pretransfer > 0.200s` — задержка вызвана выполнением запроса на бэкенде, очередью СУБД или блокировкой дискового ввода-вывода.

### Сценарий 2: Анализ сетевых сокетов и TCP-метрик через `ss`

Инспекция состояния TCP-соединения позволяет выявить проблемы с окном перегрузки (`cwnd`), задержками RTT и ретрансмиссиями на сервере:

```bash
# Поиск сокетов веб-сервера с выводом внутренней статистики TCP
ss -tiem 'sport = :443 or sport = :80' | head -n 20
# → ESTAB  0  0  192.168.1.10:443  192.168.1.55:54321
# →   cubic wscale:7,7 rto:200 rtt:14.2/0.8 ato:40 mss:1460 rcvspace:14600 ssthresh:10 cwnd:10 retrans:0/1
```

**Ключевые параметры диагностики:**
- `rtt:14.2/0.8` — текущее время кругового обращения (RTT) 14.2 мс с вариацией 0.8 мс.
- `cwnd:10` — текущий размер окна перегрузки в пакетах (MSS). Если `cwnd` мал при высокой нагрузке, возможно соединение только что открылось (Slow Start) или произошла потеря пакетов.
- `retrans:0/1` — наличие повторных передач (packet loss). Если счетчик ретрансмиссий растет — канал перегружен либо настроены неверные размеры очередей сетевой карты (`txqueuelen`).
- `bbr` vs `cubic` — отображает активный алгоритм контроля перегрузки сокета.

### Сценарий 3: Производственная конфигурация Nginx/Angie для высокой производительности

Сбалансированная конфигурация обратного прокси, объединяющая оптимизацию ядра, кэширование, keepalive-пулы и сжатие:

```nginx
# Оптимизация рабочих процессов
user www-data;
worker_processes auto;
worker_cpu_affinity auto;
worker_rlimit_nofile 65535;
pcre_jit on;

events {
    worker_connections 16384;
    use epoll;
    multi_accept on;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    # Системный Zero-Copy ввод-вывод
    sendfile        on;
    tcp_nopush      on;
    tcp_nodelay     on;

    # Таймауты клиентских соединений
    keepalive_timeout   65s;
    keepalive_requests  1000;
    reset_timedout_connection on;
    client_body_timeout 15s;
    send_timeout        15s;

    # Путь и параметры зоны кэширования
    proxy_cache_path /var/cache/nginx/proxy
                     levels=1:2
                     keys_zone=PAGE_CACHE:32m
                     max_size=5g
                     inactive=60m
                     use_temp_path=off;

    # Пул постоянных соединений к бэкенду
    upstream backend_nodes {
        server 127.0.0.1:8080 max_fails=3 fail_timeout=10s;
        keepalive 64;
        keepalive_requests 1000;
        keepalive_time 1h;
        keepalive_timeout 60s;
    }

    # Настройки сжатия Gzip
    gzip on;
    gzip_comp_level 5;
    gzip_min_length 1024;
    gzip_proxied any;
    gzip_vary on;
    gzip_types text/plain text/css application/javascript application/json image/svg+xml;

    server {
        listen 443 ssl reuseport;
        server_name example.com;

        ssl_certificate     /etc/ssl/certs/example.com.crt;
        ssl_certificate_key /etc/ssl/private/example.com.key;
        ssl_protocols       TLSv1.2 TLSv1.3;
        ssl_session_cache   shared:SSL:20m;
        ssl_session_timeout 1d;
        ssl_session_tickets on;

        # Статический контент с предварительным сжатием и длительным TTL
        location ~* \.(css|js|woff2|png|jpg|svg)$ {
            root /var/www/static;
            gzip_static on;
            expires 1y;
            add_header Cache-Control "public, max-age=31536000, immutable";
            access_log off;
        }

        # Динамические API-запросы с микрокэшированием
        location /api/ {
            proxy_pass http://backend_nodes;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-For $remote_addr;

            # Микрокэширование и защита от лавины запросов
            proxy_cache PAGE_CACHE;
            proxy_cache_key "$request_method$scheme$host$request_uri";
            proxy_cache_valid 200 302 2s;
            proxy_cache_valid 404 10s;
            proxy_cache_lock on;
            proxy_cache_lock_timeout 5s;
            proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;

            add_header X-Cache-Status $upstream_cache_status always;
        }
    }
}
```

### Сценарий 4: Проверка заголовков производительности, Early Hints и условных запросов

Валидация корректности отдачи заголовков управления кэшем, сжатия и механизма 304 Not Modified:

```bash
# Проверка заголовков кэширования статики
curl -sI https://example.com/assets/main.css | grep -iE "cache-control|content-encoding|age|etag|x-cache"
# → cache-control: public, max-age=31536000, immutable
# → content-encoding: gzip
# → etag: "652a1b9f-14a0"
# → x-cache: HIT

# Проверка механизма условных запросов (HTTP 304)
ETAG=$(curl -sI https://example.com/assets/main.css | grep -i etag | tr -d '\r' | awk '{print $2}')
curl -sI -H "If-None-Match: $ETAG" https://example.com/assets/main.css | head -n 5
# → HTTP/2 304 Not Modified
# → etag: "652a1b9f-14a0"
# → cache-control: public, max-age=31536000, immutable

# Проверка Early Hints (HTTP 103)
curl -sI -H "Prefer: safe" https://example.com/ | head -n 5
# → HTTP/2 103 Early Hints
# → link: </assets/main.css>; rel=preload; as=style, </assets/fonts/inter.woff2>; rel=preload; as=font; type=font/woff2; crossorigin
```

### Сценарий 5: Автоматизация Performance Budget через Lighthouse CI в On-Premise CI/CD

Внедрение контроля бюджета производительности в локальный пайплайн сборки без использования облачных сервисов:

```bash
# 1. Установка Lighthouse CI CLI на сборочном сервере
npm install -g @lhci/cli

# 2. Создание файла конфигурации .lighthouserc.js
cat > .lighthouserc.js << 'EOF'
module.exports = {
  ci: {
    collect: {
      url: ['http://127.0.0.1:8080/', 'http://127.0.0.1:8080/catalog'],
      numberOfRuns: 3,
      settings: {
        chromeFlags: '--no-sandbox --headless --disable-gpu',
      },
    },
    assert: {
      assertions: {
        'categories:performance': ['error', { minScore: 0.90 }],
        'first-contentful-paint': ['error', { maxNumericValue: 1800 }],
        'largest-contentful-paint': ['error', { maxNumericValue: 2500 }],
        'cumulative-layout-shift': ['error', { maxNumericValue: 0.1 }],
        'total-blocking-time': ['error', { maxNumericValue: 200 }],
        'resource-summary:script:size': ['error', { maxNumericValue: 350000 }], // макс 350 КБ JS
      },
    },
  },
};
EOF

# 3. Выполнение сбора метрик и проверка бюджетов в пайплайне
lhci collect && lhci assert
# → Running Lighthouse 3 time(s) on http://127.0.0.1:8080/
# → Asserting thresholds...
# → ✅ categories:performance: 0.94 >= 0.90
# → ✅ largest-contentful-paint: 1920ms <= 2500ms
# → ✅ cumulative-layout-shift: 0.02 <= 0.1
# → All assertions passed successfully.
```

### Сценарий 6: Базовое нагрузочное тестирование и замер RPS через wrk

Оценка максимальной пропускной способности обратного прокси и распределения задержек (Latency Percentiles):

```bash
# 30-секундный тест с 4 потоками и 100 параллельными keepalive-соединениями
wrk -t4 -c100 -d30s --latency https://example.com/api/v1/products
# → Running 30s test @ https://example.com/api/v1/products
# →   4 threads and 100 connections
# →   Thread Stats   Avg      Stdev     Max   +/- Stdev
# →     Latency     4.12ms    1.85ms  45.10ms   89.12%
# →     Req/Sec     6.12k   450.20     7.80k    72.50%
# →   Latency Distribution
# →      50%    3.80ms
# →      75%    4.45ms
# →      90%    5.60ms
# →      99%   12.40ms
# →   734120 requests in 30.05s, 1.25GB read
# → Requests/sec:  24429.12
# → Transfer/sec:     42.59MB
```

## Операции и команды

Справочник практических команд для повседневной эксплуатации и аудита производительности:

### Диагностика сетевого стека и сокетов

```bash
# Проверка текущего алгоритма контроля перегрузки ядра Linux
sysctl net.ipv4.tcp_congestion_control
# → net.ipv4.tcp_congestion_control = bbr

# Проверка размера очереди ожидающих соединений (somaxconn)
sysctl net.core.somaxconn
# → net.core.somaxconn = 65535

# Просмотр статистики всех активных сокетов и буферов
ss -s
# → Total: 1250
# → TCP:   840 (estab 620, closed 120, orphaned 5, timewait 95)

# Мониторинг отброшенных пакетов из-за переполнения очередей backlog
netstat -s | grep -i "listen"
# → 0 times the listen queue of a socket overflowed
# → 0 SYNs to LISTEN sockets dropped
```

### Проверка протоколов HTTP/2, HTTP/3 и TLS через CLI

```bash
# Проверка поддержки HTTP/2 и ALPN через OpenSSL
openssl s_client -connect example.com:443 -alpn h2 -quiet < /dev/null
# → depth=2 C = US, O = Internet Security Research Group, CN = ISRG Root X1
# → ALPN protocol: h2

# Проверка поддержки HTTP/3 (QUIC) через curl
curl --http3-only -sI https://example.com/ | grep -iE "http|alt-svc"
# → HTTP/3 200
# → alt-svc: h3=":443"; ma=2592000

# Проверка времени сессионного возобновления (Session Resumption / Tickets)
openssl s_client -connect example.com:443 -reconnect -no_ssl2 < /dev/null 2>&1 | grep "Re-use"
# → Re-use session-id: YES
```

### Анализ логов производительности Nginx/Angie

```bash
# Вычисление среднего TTFB и перцентилей p90/p99 по access.log (формат JSON)
cat /var/log/nginx/access.json | jq -r '.upstream_response_time' | \
  awk '{
    if ($1 != "-") {
      a[i++] = $1; sum += $1;
    }
  } END {
    n = asort(a);
    print "Количество запросов: " n;
    print "Средний TTFB: " sum/n "s";
    print "p50: " a[int(n*0.50)] "s";
    print "p90: " a[int(n*0.90)] "s";
    print "p99: " a[int(n*0.99)] "s";
  }'
# → Количество запросов: 104520
# → Средний TTFB: 0.045s
# → p50: 0.012s
# → p90: 0.085s
# → p99: 0.240s

# Подсчет Cache Hit Ratio за последний час
cat /var/log/nginx/access.json | jq -r '.cache_status' | \
  awk '{
    total++;
    if ($1 == "HIT") hit++;
    if ($1 == "STALE") stale++;
  } END {
    printf "Hit Ratio: %.2f%%\n", ((hit + stale) / total) * 100;
  }'
# → Hit Ratio: 87.45%
```

## Диагностика и устранение неисправностей

| Проблема | Симптом | Первичная диагностика | Корневая причина | Решение |
| :--- | :--- | :--- | :--- | :--- |
| **Высокий TTFB (> 500 мс)** | LCP > 2.5 с, задержка открытия страниц | `curl -w "@/tmp/curl_format.txt" -s -o /dev/null URL` | Медленные запросы к СУБД, блокировки I/O, отсутствие кэширования | Включить microcaching на прокси, оптимизировать индексы БД, настроить keepalive к апстримам |
| **Низкий Cache Hit Ratio (< 60%)** | Высокая загрузка CPU апстримов, статус `MISS` | `curl -sI URL \| grep -iE "x-cache\|age\|vary"` | Заголовки `Vary: *` или `Vary: User-Agent`, ненормализованный Cache Key, избыточные Cookies | Нормализовать `$request_uri`, удалить нерелевантные query-параметры из ключа, настроить `proxy_ignore_headers Cache-Control Set-Cookie;` |
| **Cache Stampede (Thundering herd)** | Всплески 502/504 Gateway Timeout при истечении TTL популярных страниц | Мониторинг очереди соединений к апстриму в момент инвалидации | Сотни одновременных запросов идут на бэкенд за одним и тем же ресурсом | Добавить директивы `proxy_cache_lock on;`, `proxy_cache_use_stale updating;` |
| **Высокий INP (> 200 мс)** | Зависания UI при кликах, плохой показатель в CrUX | Chrome DevTools → вкладка Performance → дорожка Main Thread (Long Tasks > 50 мс) | Монолитные скрипты в главном потоке, тяжелые вычисления, избыточный hydration | Разделение кода (code splitting), вынос фоновых задач в Web Workers, применение `scheduler.yield()` |
| **Нестабильный CLS (> 0.1)** | Прыгающие элементы страницы, смещение кнопок | Chrome DevTools → вкладка Rendering → Layout Shift Regions | Отсутствие `aspect-ratio` у картинок, поздняя вставка баннеров, мигание шрифтов (FOIT) | Задать явные CSS-атрибуты `width`/`height` для всех `<img>`, настроить `font-display: swap;`, резервировать место под динамические блоки |
| **Потери пакетов HTTP/3 (QUIC)** | Не устанавливается HTTP/3 соединение, откат к HTTP/2 | `curl --http3-only -sI URL`, проверка через `tcpdump -ni any udp port 443` | Блокировка UDP 443 на внешнем firewall, неверный MTU, переполнение буферов сокета UDP | Открыть UDP 443 на firewall, настроить буферы ядра `net.core.rmem_max = 16777216`, включить GSO (Generic Segmentation Offload) |
| **Истощение сокетов (TIME_WAIT)** | Ошибки `Cannot assign requested address` в логах Nginx | `ss -s`, проверка `netstat -an \| grep TIME_WAIT \| wc -l` | Закрытие соединений со стороны Nginx при отключенном keepalive к апстриму | Включить `upstream keepalive 64;`, задать `proxy_http_version 1.1;`, `proxy_set_header Connection "";` |
| **Bufferbloat / Всплески задержек p99** | Резкий рост latency под нагрузкой при свободном канале | `ping -c 100 -i 0.1 IP` параллельно с тестом `wrk` | Переполнение неконтролируемых сетевых буферов промежуточных маршрутизаторов | Переключить алгоритм контроля перегрузки на BBR: `sysctl -w net.ipv4.tcp_congestion_control=bbr` |

## Рекомендации и лучшие практики

### 1. Тюнинг сетевого стека Linux (sysctl)

Для серверов с высокой сетевой нагрузкой рекомендуются следующие параметры в `/etc/sysctl.d/99-web-performance.conf`:

```ini
# Максимальный размер очереди входящих соединений
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 3240000

# Автоматическая подстройка буферов сокетов TCP (min, default, max)
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216

# Алгоритм контроля перегрузки BBR и дисциплина очереди FQ
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# Включение TCP Fast Open (3 = включен для входящих и исходящих соединений)
net.ipv4.tcp_fastopen = 3

# Повторное использование сокетов в состоянии TIME_WAIT
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15

# Увеличение начального окна перегрузки (initcwnd) до 14-16 сегментов
# Настраивается через команду маршрутизации:
# ip route change default via <GATEWAY> dev eth0 initcwnd 16 initrwnd 16
```

### 2. Оптимизация обратного прокси (Nginx / Angie)

- **Worker affinity:** Обязательно фиксируйте рабочие процессы на ядрах CPU (`worker_cpu_affinity auto;`), чтобы исключить межъядерные переключения контекста и промахи кэша L1/L2/L3.
- **Upstream Connection Pooling:** Всегда поддерживайте открытый пул keepalive-соединений к бэкенду (`keepalive 64;`, `proxy_http_version 1.1;`). Без этого на каждый запрос к API тратится дополнительный TCP RTT.
- **Размер динамических TLS-буферов:** По умолчанию Nginx отправляет данные TLS-блоками по 16 КБ. Для ускорения TTFB уменьшайте `ssl_buffer_size 4k;` (или используйте динамические буферы в Angie), чтобы браузер мог начать рендеринг первого чанка без ожидания наполнения всего 16 КБ блока.
- **Kernel TLS:** На ядрах Linux 5.x+ включайте `ssl_conf_command Options KTLS;` для разгрузки CPU при раздаче тяжелой статики по HTTPS.

### 3. Кэширование и доставка статического контента

- **Неизменяемая статика:** Для всех версионированных артефактов (JS, CSS, шрифты с хешем в имени) задавайте `Cache-Control: public, max-age=31536000, immutable;`. Это исключает любые повторные валидационные запросы (304) со стороны браузера.
- **Предварительное сжатие:** Никогда не сжимайте тяжелые статические JS/CSS на лету в runtime. Выполняйте сжатие в Brotli/Gzip/Zstd на этапе CI/CD пайплайна и используйте `gzip_static on;` и `brotli_static on;`.
- **Защита от негативного кэширования:** Обязательно кэшируйте ответы 404/500 на короткий срок (`proxy_cache_valid 404 10s;`), чтобы случайный всплеск битых ссылок не перегружал приложение.

### 4. Наблюдаемость, SRE и CI/CD

- **Structured Logging:** Логируйте `$request_time`, `$upstream_response_time`, `$upstream_connect_time` и `$upstream_cache_status` в JSON-формате для мгновенного анализа перцентилей p95/p99 и алертинга.
- **Performance Budgets в CI:** Любой pull request должен проходить автоматизированную проверку через Lighthouse CI с жесткими пороговыми значениями (LCP ≤ 2.5 с, INP ≤ 200 мс, CLS ≤ 0.1).
- **SLO по Web Vitals:** Устанавливайте Service Level Objective для веб-сервисов: 75% пользователей (p75 по RUM/CrUX) должны находиться в зеленой зоне Core Web Vitals.

### 5. Чего делать нельзя (Антипаттерны)

- ❌ Не устанавливайте уровень сжатия Gzip выше 6 или Brotli выше 5 при сжатии на лету: прирост степени сжатия составит менее 1%, а нагрузка на CPU вырастет в 3–5 раз, задерживая отдачу первого байта.
- ❌ Не используйте `loading="lazy"` на первом экране (Hero image / баннер): это искусственно задерживает загрузку ключевого контента и ухудшает метрику LCP.
- ❌ Не отключайте `proxy_cache_lock` на нагруженных эндпоинтах: при истечении срока жизни кэша вы получите Cache Stampede и отказ базы данных.
- ❌ Не используйте директиву `Vary: *` или `Vary: User-Agent`: это фрагментирует или полностью отключает кэширование на стороне обратного прокси.

## Дополнительная информация

### Связанные файлы

- [Ключевые метрики Web Vitals](./web_vitals.md) — детальный разбор LCP, INP, CLS, FCP, TBT и формулы расчета.
- [Принципы тестирования производительности](./testing_principles.md) — различия RUM и Lab Data, Baseline, методология тестов.
- [Лучшие практики оптимизации](./best_practices.md) — детальное инженерное руководство по тюнингу инфраструктуры.
- [Настройка кэширования](./caching.md) — архитектура кэша Nginx/Angie, ключи, инвалидация и директивы.
- [Сжатие контента (Gzip, Brotli, ZSTD)](./server_compression.md) — детальное сравнение алгоритмов и практические конфиги.
- [Протоколы HTTP/2 и HTTP/3](./http2_http3.md) — архитектура бинарных потоков, QUIC поверх UDP и миграция сессий.
- [Оптимизация TLS](./tls_optimization.md) — TLS 1.3, 0-RTT, OCSP Stapling, kTLS и сессионные билеты.
- [Upstream Keepalive и Connection Pooling](./upstream_keepalive_and_pooling.md) — пулы постоянных соединений с бэкендами.
- [Structured Logging для Performance](./structured_logging_for_performance.md) — сбор и анализ таймингов в JSON-логах.
- [Инструменты анализа (Chrome DevTools)](./chrome_devtools.md) — методология поиска узких мест рендеринга.
- [WebPageTest — синтетическое тестирование](./webpagetest.md) — многопрогонное тестирование и водопадные диаграммы.
- [PageSpeed Insights и CrUX](./pagespeed_insights.md) — полевые данные Google и анализ реального опыта.
- [Image Optimization Pipeline](./image_optimization_pipeline.md) — пайплайны сборки и конвертации в WebP/AVIF.
- [Font Optimization Pipeline](./font_optimization_pipeline.md) — пайплайны сборки, сабсеттинг WOFF2, unicode-range и устранение FOUT/FOIT.
- [Circuit Breaker и деградация сервисов](./circuit_breaker_and_degradation.md) — защита от каскадных сбоев.
- [Health Checks и Readiness](./health_checks_and_readiness.md) — проактивный мониторинг жизнеспособности апстримов.
- [Zero-Downtime Deployment](./zero_downtime_deployment.md) — бесшовный перезапуск и ротация воркеров.

### RFC и спецификации

- **RFC 9110** — HTTP Semantics (базовая семантика протокола HTTP).
- **RFC 9111** — HTTP Caching (стандарт HTTP-кэширования, обновивший RFC 7234).
- **RFC 9113** — HTTP/2 (бинарное мультиплексирование потоков поверх TCP).
- **RFC 9114** — HTTP/3 (мультиплексирование потоков поверх протокола QUIC / UDP).
- **RFC 8297** — An HTTP Status Code for Indicating Hints (HTTP 103 Early Hints).
- **RFC 5861** — HTTP Cache-Control Extensions for Stale Content (`stale-while-revalidate`, `stale-if-error`).
- **RFC 9211** — The Cache-Status HTTP Response Header Field.
- **RFC 9659** — Zstandard Compression for HTTP (алгоритм Zstd для контента).

### Официальные ресурсы

- [Web.dev Performance Documentation](https://web.dev/performance/) — официальная база знаний Google по веб-производительности.
- [MDN Web Performance Guide](https://developer.mozilla.org/en-US/docs/Web/Performance) — спецификации браузерных API и метрик.
- [Nginx Documentation: Performance Tuning](https://nginx.org/en/docs/) — официальное руководство по настройке Nginx.
- [Angie Documentation](https://angie.software/en/) — документация по расширенным возможностям веб-сервера Angie (Zstd, HTTP/3, dynamic buffers).
- [Lighthouse CI Documentation](https://github.com/GoogleChrome/lighthouse-ci) — официальный репозиторий и документация инструмента автоматизации аудита.
