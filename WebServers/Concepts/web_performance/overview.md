# Оптимизация производительности веб-приложений: Обзор

## Определения

**Производительность веб-приложений (Web Performance)** — комплексная дисциплина, направленная на минимизацию времени доставки ресурсов, ускорение рендеринга и обеспечение мгновенной реакции на действия пользователя. В 2026 году производительность рассматривается не только как технический параметр, но и как критический фактор бизнес-успеха и экологической устойчивости (Carbon Intensity).

**Core Web Vitals** — стандартизированные метрики Google для оценки качества пользовательского опыта:
*   **LCP (Largest Contentful Paint):** Скорость загрузки основного контента. Порог «хорошо»: **< 2.5 с**.
*   **INP (Interaction to Next Paint):** Отзывчивость интерфейса (заменила FID в марте 2024). Порог «хорошо»: **< 200 мс**.
*   **CLS (Cumulative Layout Shift):** Визуальная стабильность. Порог «хорошо»: **< 0.1**.
*   *Подробнее:* [web_vitals.md](./web_vitals.md).

**RUM (Real User Monitoring)** — мониторинг реальных пользователей (полевые данные / Field Data). Сбор метрик непосредственно в браузерах посетителей на реальных устройствах и сетях. Противопоставляется **Lab Data** (лабораторные данные) — синтетическим тестам в контролируемой среде.

**TBT (Total Blocking Time)** — сумма периодов блокировки основного потока между FCP и достижением интерактивности. Коррелирует с INP в лабораторных тестах. Цель: **< 200 мс**.

**Early Hints (103)** — статус-код, позволяющий серверу отправить заголовки `Link` с критическими ресурсами до полной генерации HTML. Браузер начинает фоновую загрузку CSS, шрифтов и скриптов параллельно работе бэкенда.

**Speculation Rules API** — декларативный механизм браузера для фонового рендеринга (prerender) или предзагрузки (prefetch) страниц, на которые пользователь с высокой вероятностью перейдет. Пришел на смену классическому `<link rel="prefetch">` и `<link rel="prerender">`.

**Fetch Priority API** — программный контроль приоритета загрузки ресурсов через атрибут `fetchpriority`. `fetchpriority="high"` для LCP-изображения позволяет браузеру начать его загрузку раньше остальных ресурсов.

**Off-Main-Thread Architecture** — архитектурный подход, при котором тяжелые вычисления (парсинг, криптография, аналитика) выносятся из основного потока (Main Thread) в Web Workers. В 2026 году стандартные практики: Partytown для сторонних скриптов, `scheduler.yield()` для длинных задач.

## Основные концепции

### Архитектура уровней оптимизации

Веб-производительность оптимизируется на пяти уровнях:

| Уровень | Компонент | Оптимизация | Ответственный |
| :--- | :--- | :--- | :--- |
| **Клиент** | Браузер | Critical Rendering Path, Main Thread, Layout | Frontend |
| **Сеть** | CDN / Edge | TTL, TLS 1.3 0-RTT, HTTP/3, Early Hints | DevOps / SysAdmin |
| **Прокси** | Nginx / Angie | Сжатие, кэширование, заголовки | SysAdmin / DevOps |
| **Сервер** | Бэкенд | DB queries, кэширование, код | Backend |
| **Инфраструктура** | ОС / Сеть | TCP tuning, CPU, память, диски | SysAdmin |

### Жизненный цикл загрузки страницы

1. **DNS Lookup:** Разрешение домена в IP. Оптимизация: DNS Prefetch (`<link rel="dns-prefetch">`), кэширование на провайдерском уровне.
2. **TCP Handshake + TLS:** Установка соединения. Оптимизация: TLS 1.3 (1-RTT), 0-RTT для повторных посещений, session tickets, OCSP Stapling.
3. **TTFB (Time To First Byte):** Время до первого байта ответа. Зависит от производительности бэкенда, БД и сетевых задержек.
4. **Content Download:** Скачивание HTML, CSS, JS, медиа. Оптимизация: сжатие (Brotli/Zstd), HTTP/2/3 мультиплексирование, кэширование.
5. **Critical Rendering Path:** Построение DOM → CSSOM → Render Tree → Layout → Paint. Оптимизация: инлайн критического CSS, async/defer для JS, приоритизация LCP-ресурса.
6. **Interactive:** Достижение интерактивности. Оптимизация: code splitting, вынос в Web Workers, минимизация Long Tasks.

### Критический путь рендеринга (Critical Rendering Path)

Браузер последовательно строит видимые пиксели:

| Фаза | Описание | Ключевая оптимизация |
| :--- | :--- | :--- |
| **DOM** | Разбор HTML в объектную модель | Минимизация размера HTML, отложенный JS |
| **CSSOM** | Разбор CSS в объектную модель | Критический CSS, `media` атрибут |
| **Render Tree** | Объединение DOM + CSSOM | Устранение блокирующих ресурсов |
| **Layout** | Вычисление позиций и размеров | Избегание сложных селекторов, FOIT |
| **Paint** | Отрисовка пикселей | `font-display: swap`, оптимизация анимаций |

### Механизмы приоритизации ресурсов

**Fetch Priority API (2024+):**
*   `fetchpriority="high"` — повышает приоритет загрузки (LCP-изображение).
*   `fetchpriority="low"` — понижает приоритет (аналитика, чат).
*   `fetchpriority="auto"` — значение по умолчанию.

**Native Lazy Loading:**
*   `loading="lazy"` — отложенная загрузка для изображений и фреймов ниже первого экрана.
*   **Запрещено** для LCP-элемента — критическая ошибка.
*   `loading="eager"` — немедленная загрузка (значение по умолчанию).

**Resource Hints:**
*   `<link rel="dns-prefetch">` —提前DNS解析 (внешние домены).
*   `<link rel="preconnect">` —提前TCP/TLS握手 (критические внешние ресурсы).
*   `<link rel="preload">` — принудительная загрузка критического ресурса (шрифт, LCP-изображение).
*   **В 2026 году** `<link rel="prefetch">` и `<link rel="prerender">` активно заменяются на **Speculation Rules API**.

### Влияние на Web Vitals

*   **LCP:** Мгновенная отдача Hero-image из кэша исключает фазу загрузки по сети (выигрыш 500–2000 мс).
*   **INP:** Быстрая доставка JS-бандлов и шрифтов снижает блокировку Main Thread.
*   **CLS:** Кэширование критического CSS и шрифтов предотвращает "прыжки" контента.

## Практические сценарии

### Методология анализа производительности

**Данные двух типов:**
1.  **Полевые данные (RUM / Field Data):** Анализ реального опыта пользователей через Chrome User Experience Report (CrUX) или кастомные JS-агенты. Отражает влияние реальных устройств и сетевых условий.
2.  **Лабораторные данные (Lab Data):** Диагностика в контролируемой среде с эмуляцией устройств и троттлингом. Инструменты: [Chrome DevTools](./chrome_devtools.md) и [WebPageTest](./webpagetest.md).

**Стандартные профили троттлинга 2026:**
| Профиль | RTT | Downlink | Назначение |
| :--- | :--- | :--- | :--- |
| **Good 5G / Fiber** | < 20 мс | 100+ Mbps | Идеальные условия |
| **Fast 4G** | 40 мс | 9 Mbps | Городской мобильный интернет |
| **Slow 4G / 3G** | 150+ мс | 1.6 Mbps | Нестабильное покрытие, роуминг |

### Стратегия приоритизации (Impact vs Effort)

| Проблема | Метрика | Приоритет | Решение |
| :--- | :--- | :--- | :--- |
| Медленный TTFB | LCP, FCP | **Критический** | CDN, серверное кэширование, оптимизация запросов к БД |
| Блокирующий JS | INP, TBT | **Высокий** | Code splitting, `async/defer`, вынос в Web Workers |
| Нестабильная верстка | CLS | **Высокий** | Явные размеры для медиа (aspect-ratio), `font-display: swap` |
| Большой вес страницы | LCP, TTFB | **Средний** | Адаптивные изображения, Brotli/Zstd, удаление неиспользуемого кода |

### Сценарий: Диагностика TTFB через curl

Для понимания, на какой стороне (Back-end или Network) происходит задержка:

```bash
# Полный тайминг запроса
curl -o /dev/null -s -w "\
  DNS: %{time_namelookup}s\n\
  TCP: %{time_connect}s\n\
  TLS: %{time_appconnect}s\n\
  TTFB: %{time_starttransfer}s\n\
  Total: %{time_total}s\n" https://example.com/api/data
# → DNS: 0.012s
# → TCP: 0.045s
# → TLS: 0.078s
# → TTFB: 0.245s
# → Total: 0.312s

# Если TTFB > 500 мс — проблема на стороне бэкенда или БД
# Если TLS > 100 мс — требуется оптимизация TLS (OCSP Stapling, session tickets)
```

### Сценарий: Проверка заголовков производительности

```bash
# Проверка заголовков кэширования и сжатия
curl -sI https://example.com/style.css | grep -iE "cache-control|age|content-encoding|server|x-cache"
# → cache-control: public, max-age=31536000, immutable
# → content-encoding: br
# → age: 300
# → x-cache: HIT

# Проверка Early Hints (103)
curl -sI -H "Prefer: safe" https://example.com/ | head -5
# → HTTP/2 103
# → link: </css/main.css>; rel=preload; as=style, </fonts/main.woff2>; rel=preload; as=font; type=font/woff2; crossorigin

# Проверка Speculation Rules
curl -s https://example.com/ | grep -i speculation
# → <script type="speculationrules">
#     { "prefetch": [{ "source": "document", "where": { "href_matches": "/products/*" } }] }
#   </script>
```

### Сценарий: Интеграция Lighthouse CI в CI/CD

Для предотвращения регрессий производительности:

```bash
# Установка Lighthouse CI
npm install -g @lhci/cli

# Конфигурация порогов (.lighthouserc.js)
cat > .lighthouserc.js << 'EOF'
module.exports = {
  ci: {
    collect: {
      url: ['https://example.com/', 'https://example.com/products'],
      numberOfRuns: 3,
    },
    assert: {
      assertions: {
        'categories:performance': ['error', {minScore: 0.9}],
        'largest-contentful-paint': ['error', {maxNumericValue: 2500}],
        'interactive': ['error', {maxNumericValue: 200}],
      },
    },
  },
};
EOF

# Запуск в пайплайне
lhci collect --url=https://example.com/ && lhci assert
# → Collected 3 runs for https://example.com/
# → Performance: 0.92 (passed)
# → LCP: 1.8s (passed)
# → INP: 145ms (passed)
```

### Сценарий: Устойчивая производительность (Eco-performance)

В 2026 году оптимизация производительности напрямую связана с экологией. Быстрый код потребляет меньше циклов CPU, что снижает энергопотребление дата-центров и устройств пользователей. Цель DevOps-инженера — минимизировать «цифровой углеродный след» за счет исключения избыточных вычислений и неэффективной передачи данных.

## Операции и команды

### Диагностика через curl

```bash
# Полный тайминг запроса (TTFB, TLS, DNS)
curl -o /dev/null -s -w "\
  DNS: %{time_namelookup}s\n\
  TCP: %{time_connect}s\n\
  TLS: %{time_appconnect}s\n\
  TTFB: %{time_starttransfer}s\n\
  Total: %{time_total}s\n" https://example.com/
# → DNS: 0.012s
# → TCP: 0.045s
# → TLS: 0.078s
# → TTFB: 0.245s
# → Total: 0.312s

# Проверка заголовков производительности
curl -sI https://example.com/ | grep -iE "cache-control|content-encoding|x-cache|age|server-timing"
# → cache-control: public, max-age=31536000, immutable
# → content-encoding: br
# → x-cache: HIT
# → age: 300

# Проверка Early Hints
curl -sI -H "Prefer: safe" https://example.com/ | head -10
# → HTTP/2 103
# → link: </css/main.css>; rel=preload; as=style

# Проверка условного запроса (валидация кэша)
ETAG=$(curl -sI https://example.com/api/data | grep -i etag | tr -d '\r' | awk '{print $2}')
curl -sI -H "If-None-Match: $ETAG" https://example.com/api/data
# → HTTP/2 304 Not Modified
```

### Проверка поддержки HTTP/3

```bash
# Проверка через curl (требуется curl с поддержкой HTTP/3)
curl --http3-only -I https://example.com/ 2>&1 | head -5
# → HTTP/3 200
# → alt-svc: h3=":443"; ma=2592000

# Проверка через nghttp (специализированный клиент)
nghttp -nv https://example.com/ 2>&1 | head -10
# → [HTTP/3] 200 OK
# → [Header] content-encoding: br
```

### Локальный запуск Lighthouse CI

```bash
# Сбор метрик для URL
lhci collect --url=https://example.com/ --numberOfRuns=3
# → Collected 3 runs for https://example.com/
# → Median LCP: 1.8s (Good)
# → Median INP: 145ms (Good)
# → Median CLS: 0.05 (Good)

# Проверка порогов
lhci assert
# → Performance: 0.92 (passed)
# → All thresholds passed
```

### Мониторинг RUM через Performance API

```javascript
// Встраивание в страницу для сбора метрик
import {onLCP, onINP, onCLS} from 'web-vitals';

onLCP((metric) => {
  console.log(`LCP: ${metric.value.toFixed(2)}ms (${metric.rating})`);
  // → LCP: 1800.50ms (good)
});

onINP((metric) => {
  console.log(`INP: ${metric.value.toFixed(2)}ms (${metric.rating})`);
  // → INP: 145.30ms (good)
});

onCLS((metric) => {
  console.log(`CLS: ${metric.value.toFixed(4)} (${metric.rating})`);
  // → CLS: 0.0500 (good)
});
```

## Диагностика ошибок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Высокий TTFB** | LCP > 2.5 с, медленный первый байт | `curl -o /dev/null -s -w "TTFB: %{time_starttransfer}s" URL` | Оптимизация запросов к БД, серверное кэширование, CDN |
| **Низкий Cache Hit Ratio** | Много `MISS` в заголовках, высокая нагрузка на Origin | `curl -sI URL \| grep -iE "x-cache\|age\|cache-control"` | Увеличить TTL, включить `stale-while-revalidate`, проверить Cache Key |
| **Нестабильный CLS** | Сдвиги макета > 0.1 | Chrome DevTools → Performance → Layout Shifts | Явные размеры для медиа (aspect-ratio), `font-display: swap`, резервирование места для рекламы |
| **Высокий INP** | Задержка реакции на действия > 200 мс | Chrome DevTools → Performance → Long Tasks | Code splitting, `async/defer`, вынос в Web Workers (Partytown) |
| **Высокий LCP** | Медленная загрузка основного контента > 2.5 с | Chrome DevTools → Network → фильтр по LCP | `fetchpriority="high"`, кэширование, сжатие, CDN |
| **Блокирующий JS** | TBT > 200 мс, белый экран | Chrome DevTools → Performance → Main Thread | `defer`/`async` для скриптов, динамический импорт, Web Workers |
| **Устаревший контент** | Пользователи видят старую версию | `curl -sI URL \| grep age` — возраст > `max-age` | Уменьшить TTL, настроить Purge API, использовать Cache Busting |
| **Cache Stampede** | Всплеск нагрузки на Origin | Мониторинг Origin (CPU, RPS) | Включить `proxy_cache_lock`, добавить Jitter TTL, настроить SWR |
| **Медленная инвалидация** | Контент обновляется через минуты | Проверить PoP географии | Перейти на Cache Busting или CDN с <200 мс инвалидацией |
| **Vary: * отключает кэш** | Все запросы проходят как MISS | `curl -sI URL \| grep -i vary` | Убрать `Vary: *`, использовать конкретные заголовки |

## Рекомендации

### Базовые правила

1.  **Приоритизируйте LCP-ресурс:** Используйте `fetchpriority="high"` для Hero-image, `preload` для критических шрифтов.
2.  **Минимизируйте Long Tasks:** Разделяйте задачи >50 мс с помощью `scheduler.yield()` или выносите в Web Workers.
3.  **Используйте `dns-prefetch` и `preconnect`:** Для третьих доменов (CDN, API, аналитика) чтобы сократить время установки соединения.
4.  **Версионируйте статику:** Используйте fingerprinting (хеш в имени файла) + `Cache-Control: public, max-age=31536000, immutable`.
5.  **Настройте `stale-while-revalidate` и `stale-if-error`:** Обеспечивают отзывчивость при обновлениях и отказоустойчивость при сбоях Origin.
6.  **Кэшируйте ошибки:** `proxy_cache_valid 404 10s;` защищает Origin от повторных запросов к несуществующим ресурсам.
7.  **Нормализуйте Cache Key:** Исключайте из ключа нерелевантные заголовки (Cookie, User-Agent), сортируйте query-параметры.
8.  **Валидируйте заголовки после деплоя:** Проверяйте, что пользователи видят актуальный контент, а метрики (CHR, TTFB) улучшились.
9.  **Интегрируйте Lighthouse CI в пайплайн:** Устанавливайте пороги для Core Web Vitals, предотвращайте регрессии.
10. **Мониторьте метрики:** Отслеживайте LCP, INP, CLS через RUM (CrUX или кастомные агенты) и синтетику.

### Для DevOps/SRE/SysAdmin

*   **Offload Ratio:** Процент запросов, обработанных кэшем/CDN. Рост Offload напрямую снижает затраты на инфраструктуру.
*   **Диагностика TTFB:** Используйте `curl -w` для разбивки тайминга (DNS, TCP, TLS, TTFB). Высокий TTFB (>500 мс) — проблема бэкенда или БД.
*   **Мониторинг кэша:** Отслеживайте `X-Cache-Status`, `Age`, `Cache-Status`. Алерты при `Hit Ratio < 80%` или `Age > s-maxage`.
*   **Cache Warming:** После перезапуска прокси/CDN наполняйте кэш популярными ресурсами (bulk load через `curl`).
*   **Мониторинг негативного кэширования:** Убедитесь, что 404/5xx кэшируются на короткий срок, чтобы защитить Origin от DoS.
*   **Ограничение размера кэша:** Устанавливайте `max_size` и `inactive` для предотвращения заполнения диска.
*   **Валидация заголовков:** Проверяйте `Cache-Control`, `Content-Encoding`, `Vary` после деплоя через `curl -sI`.
*   **Аудит производительности:** Регулярно запускайте Lighthouse CI в пайплайне, анализируйте тренды метрик.
*   **TCP Tuning:** Настройте `initcwnd` на 14 KB, включите `tcp_fastopen` для снижения задержки рукопожатия.

## Дополнительная информация

### Связанные файлы

*   [Ключевые метрики Web Vitals](./web_vitals.md) — детальный разбор LCP, INP, CLS, FCP, TBT.
*   [Принципы тестирования производительности](./testing_principles.md) — разница между RUM и синтетикой, методология.
*   [Лучшие практики оптимизации](./best_practices.md) — пошаговое руководство по оптимизации.
*   [Настройка кэширования](./caching.md) — уровни и стратегии инвалидации.
*   [Сжатие контента (Gzip, Brotli, ZSTD)](./server_compression.md) — настройка и сравнение алгоритмов.
*   [Протоколы HTTP/2 и HTTP/3](./http2_http3.md) — архитектура QUIC и бинарных потоков.
*   [Оптимизация TLS](./tls_optimization.md) — OCSP Stapling, 0-RTT, session tickets.
*   [Инструменты анализа (DevTools, PageSpeed)](./chrome_devtools.md) — методология поиска узких мест.
*   [Upstream Keepalive и Connection Pooling](./upstream_keepalive_and_pooling.md) — пул соединений с бэкендом.
*   [Zero-Downtime Deployment](./zero_downtime_deployment.md) — graceful reload и worker_shutdown_timeout.
*   [Circuit Breaker и Degradation](./circuit_breaker_and_degradation.md) — отказоустойчивость и fallback.
*   [Health Checks и Readiness](./health_checks_and_readiness.md) — proactive обнаружение сбоев.
*   [Image Optimization Pipeline](./image_optimization_pipeline.md) — CI/CD и AVIF/WebP.
*   [Structured Logging для Performance](./structured_logging_for_performance.md) — логи и анализ.

### RFC и спецификации

*   **RFC 9111** — HTTP-кэширование (обновлённый RFC 7234).
*   **RFC 9211** — Cache-Status заголовок.
*   **RFC 9213** — CDN-Cache-Control заголовок.
*   **RFC 5861** — `stale-while-revalidate`, `stale-if-error`.
*   **RFC 9509** — Use-As-Dictionary (Shared Dictionaries) для сжатия дельт.
*   **RFC 9659** — Zstandard (Zstd) сжатие для HTTP.

### Официальные ресурсы

*   [Web.dev: Performance](https://web.dev/performance/)
*   [MDN: Web Performance](https://developer.mozilla.org/en-US/docs/Web/Performance)
*   [Chrome DevTools: Performance](https://developer.chrome.com/docs/devtools/performance/)
*   [PageSpeed Insights](https://pagespeed.web.dev/)
*   [Lighthouse CI](https://github.com/GoogleChrome/lighthouse-ci)
