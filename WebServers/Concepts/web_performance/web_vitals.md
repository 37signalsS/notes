# Web Vitals — ключевые метрики пользовательского опыта

## Определения

**Web Vitals** — инициатива Google по стандартизации ключевых метрик, отражающих качество пользовательского опыта при загрузке и взаимодействии с веб-страницей. В 2026 году метрики используются Google как фактор ранжирования в поисковой выдаче.

**Core Web Vitals (основные веб-метрики)** — подмножество Web Vitals, используемое Google в качестве основного сигнала Page Experience. Для прохождения порогов Core Web Vitals (CWV) по 75-му перцентилю требуется выполнение трех условий одновременно: LCP ≤ 2.5 с, INP ≤ 200 мс, CLS ≤ 0.1. Невыполнение хотя бы одной метрики disqualifies страницу из категории «прошедших проверку».

**RUM (Real User Monitoring)** — мониторинг реальных пользователей (полевые данные). Сбор метрик непосредственно в браузере клиента на реальных устройствах и сетях. Противопоставляет **Lab Data** (лабораторные данные) — синтетическим тестам в фиксированной среде.

**CrUX (Chrome User Experience Report)** — публичный набор данных о реальном опыте пользователей Chrome, выступающий источником полевых данных для PageSpeed Insights и Search Console.

**SLI (Service Level Indicator)** — измеримая метрика качества сервиса. В контексте Web Vitals: доля посещений с LCP < 2.5 с, доля посещений с INP < 200 мс, доля посещений с CLS < 0.1.

**SLO (Service Level Objective)** — целевое значение SLI за период. Пример: 99% запросов имеют LCP < 2.5 с за 28 дней.

**Error Budget (Бюджет ошибок)** — допустимая доля нарушений SLO (100% − SLO). При исчерпании бюджета команда переходит в режим стабилизации.

## Основные концепции

### Core Web Vitals: метрики и пороговые значения

#### Largest Contentful Paint (LCP — отрисовка самого крупного контента)

**Что измеряет:** время с начала загрузки страницы до момента отрисовки самого большого видимого элемента (изображения, видео или текстового блока) в области просмотра (viewport). Отражает воспринимаемую скорость загрузки основного содержимого.

**Пороговые значения (Google 2026):**

| Оценка | Значение |
| :--- | :--- |
| Хорошо | ≤ 2.5 с |
| Требует улучшения | 2.5 – 4.0 с |
| Плохо | > 4.0 с |

**Фазы LCP (диагностика Lighthouse 13+):**
Для глубокой отладки LCP разделяется на четыре части, сумма которых дает итоговое значение:
1. **TTFB (Time to First Byte):** время до получения первого байта HTML-ответа. Зависит от производительности сервера, БД и сетевых задержек.
2. **Resource Load Delay (задержка загрузки ресурса):** время между TTFB и началом загрузки LCP-ресурса. Оптимизируется через `fetchpriority="high"`, устранение блокирующего JS/CSS и использование Early Hints (103).
3. **Resource Load Duration (длительность загрузки):** время скачивания самого файла. Зависит от CDN, сжатия (Brotli/Zstandard) и протокола (HTTP/3).
4. **Element Render Delay (задержка отрисовки):** время от завершения загрузки файла до появления элемента на экране. Зависит от сложности DOM и нагрузки на основной поток (Main Thread).

**Техническая оптимизация на стороне инфраструктуры (DevOps/SRE/SysAdmin):**
- **TTFB < 800 мс:** настройка кэширования на прокси/CDN, оптимизация запросов к БД, использование keepalive-пулов к бэкенду.
- **Resource Load Delay:** отправка `103 Early Hints` для критических ресурсов, `fetchpriority="high"` для LCP-изображения.
- **Resource Load Duration:** CDN с edge-кэшированием, Brotli/Zstd сжатие, HTTP/3 (QUIC).
- **Element Render Delay:** минимизация блокирующего JS, Critical CSS инлайнинг, `font-display: swap`.

**Ключевые факторы влияния:** медленное время ответа сервера, ресурсы CSS и JavaScript, блокирующие рендеринг, отсутствие приоритезации (Fetch Priority), неоптимизированные изображения.

#### Interaction to Next Paint (INP — взаимодействие до следующей отрисовки)

**Что измеряет:** задержку между действием пользователя (клик, тап, нажатие клавиши) и следующим визуальным обновлением интерфейса. В отличие от FID (First Input Delay), INP учитывает все взаимодействия за сеанс, фиксируя худший результат. INP полностью заменил метрику FID в марте 2024 года.

**Пороговые значения:**

| Оценка | Значение |
| :--- | :--- |
| Хорошо | < 200 мс |
| Требует улучшения | 200 – 500 мс |
| Плохо | > 500 мс |

**Техническая оптимизация на стороне инфраструктуры:**
- **Серверная часть:** снижение TTFB напрямую уменьшает задержку до начала обработки JS.
- **Доставка ресурсов:** минимизация размера JS-бандлов (tree-shaking, code splitting), отложенная загрузка не критичного кода.
- **Кэширование:** кэширование JS-бандлов в браузере и CDN для повторных визитов.
- **Off-Main-Thread Architecture:** вынос тяжелых вычислений в Web Workers, использование `scheduler.yield()`.

**Ключевые факторы влияния:** длинные задачи JavaScript (Long Tasks > 50 мс), перегрузка основного потока сторонними скриптами, сложные вычисления стилей и макета.

#### Cumulative Layout Shift (CLS — совокупное смещение макета)

**Что измеряет:** визуальную стабильность. Суммирует баллы всех непредвиденных сдвигов контента, которые не вызваны прямым действием пользователя в течение 500 мс.

**Пороговые значения:**

| Оценка | Значение |
| :--- | :--- |
| Хорошо | < 0.1 |
| Требует улучшения | 0.1 – 0.25 |
| Плохо | > 0.25 |

**Техническая оптимизация на стороне инфраструктуры:**
- **Шрифты:** кэширование шрифтов в CDN, использование `font-display: swap` с fallback-шрифтом.
- **Медиаконтент:** резервирование места через `aspect-ratio` CSS, явные `width` и `height` для `<img>` и `<video>`.
- **Динамический контент:** кэширование骨架-страниц (shell) через Service Worker, `stale-while-revalidate` для HTML.
- **Реклама и виджеты:** Platzhalter (placeholders) с фиксированными размерами для рекламных слотов.

**Ключевые факторы влияния:** динамически загружаемые изображения без размеров, веб-шрифты с FOIT, внезапно появляющийся контент (реклама, уведомления).

### Дополнительные лабораторные метрики

*   **First Contentful Paint (FCP):** время до появления на экране первого элемента контента. Цель: **< 1.8 с**.
*   **Total Blocking Time (TBT):** сумма периодов блокировки основного потока между FCP и моментом достижения интерактивности. Напрямую коррелирует с INP в лабораторных тестах. Цель: **< 200 мс**.
*   **Speed Index:** скорость визуального заполнения страницы (на основе анализа видеоряда).

### Оценка производительности (Performance Score)

Рассчитывается Lighthouse 13+ как взвешенная сумма метрик. Распределение весов:

| Метрика | Вес | Обоснование |
| :--- | :--- | :--- |
| **LCP** | 22% | Критично для восприятия загрузки. |
| **INP** | 22% | Критично для восприятия отзывчивости. |
| **TBT** | 15% | Прокси-метрика для интерактивности. |
| **CLS** | 15% | Критично для визуальной стабильности. |
| **FCP** | 10% | Базовый индикатор начала загрузки. |
| **Speed Index** | 10% | Визуальный прогресс. |

### Архитектура уровней оптимизации

Веб-производительность оптимизируется на пяти уровнях:

| Уровень | Компонент | Оптимизация | Ответственный |
| :--- | :--- | :--- | :--- |
| **Клиент** | Браузер | Critical Rendering Path, Main Thread, Layout | Frontend |
| **Сеть** | CDN / Edge | TTL, TLS 1.3 0-RTT, HTTP/3, Early Hints | DevOps / SysAdmin |
| **Прокси** | Nginx / Angie | Сжатие, кэширование, заголовки, буферизация | SysAdmin / DevOps |
| **Сервер** | Бэкенд | DB queries, кэширование, код | Backend |
| **Инфраструктура** | ОС / Сеть | TCP tuning, CPU, память, диски | SysAdmin |

## Практические сценарии

### Сбор данных в продуктивной среде (RUM)

Использование библиотеки `web-vitals` для отправки данных в собственную аналитику:

```javascript
import {onLCP, onINP, onCLS} from 'web-vitals';

function sendToAnalytics({name, delta, id}) {
  const body = JSON.stringify({name, delta, id});
  // Использование sendBeacon для надежной отправки при закрытии страницы
  (navigator.sendBeacon && navigator.sendBeacon('/analytics', body)) ||
  fetch('/analytics', {body, method: 'POST', keepalive: true});
}

onLCP(sendToAnalytics);
onINP(sendToAnalytics);
onCLS(sendToAnalytics);
```

### SLO/SLI для Web Vitals (SRE-практика)

Определение SLI и SLO на основе Web Vitals:

```yaml
# SLI: доля LCP < 2.5s за 28 дней
# SLO: 99% запросов соответствуют порогу
# Error Budget: 1% (при SLO 99%)

# Recording rules для Prometheus
- record: job:frontend_lcp_good_ratio
  expr: sum(rate(lcp_good[28d])) / sum(rate(lcp_total[28d]))

- record: job:frontend_inp_good_ratio
  expr: sum(rate(inp_good[28d])) / sum(rate(inp_total[28d]))

- record: job:frontend_cls_good_ratio
  expr: sum(rate(cls_good[28d])) / sum(rate(cls_total[28d]))
```

### Burn Rate: математика и multi-window алертинг

Burn Rate — скорость расхода Error Budget относительно нормы. Формула:

```
Burn Rate = (1 - actual_ratio) / (1 - SLO)
```

Где:
- `actual_ratio` — текущее значение SLI (например, доля LCP < 2.5с).
- `SLO` — целевое значение SLO (например, 0.99 для 99%).

Пример: при SLO = 99% и actual_ratio = 0.97:
```
Burn Rate = (1 - 0.97) / (1 - 0.99) = 0.03 / 0.01 = 3
```

Интерпретация:
- **Burn Rate = 1** — бюджет расходуется в норме.
- **Burn Rate > 1** — бюджет расходуется быстрее нормы.
- **Burn Rate > 2** — алерт sev2 (быстрое сжигание).
- **Burn Rate > 10** — алерт sev1 (критическое сжигание).

### Multi-window алертинг

Для снижения шума используются два окна:
1. **Длинное окно (28 дней):** Обнаруживает постепенную деградацию.
2. **Короткое окно (1 час):** Обнаруживает резкие падения (инциденты).

Пример Prometheus recording rules:

```yaml
# Burn Rate за 1 час
- record: job:frontend_lcp_error_budget_burn_rate_1h
  expr: (1 - job:frontend_lcp_good_ratio) / (1 - 0.99)

# Burn Rate за 28 дней
- record: job:frontend_lcp_error_budget_burn_rate_28d
  expr: (1 - job:frontend_lcp_good_ratio) / (1 - 0.99)
```

Пример алертов:

```yaml
# Sev2: быстрый burn rate
- alert: FrontendLCPErrorBudgetBurnFast
  expr: job:frontend_lcp_error_budget_burn_rate_1h > 3
  for: 1h
  labels:
    severity: sev2
  annotations:
    summary: "LCP бюджет сжигается быстро ({{ $value }})"

# Sev1: критический burn rate
- alert: FrontendLCPErrorBudgetBurnCritical
  expr: job:frontend_lcp_error_budget_burn_rate_1h > 10
  for: 30m
  labels:
    severity: sev1
  annotations:
    summary: "LCP бюджет сжигается критически быстро ({{ $value }})"
```

### Алертинг при расходе бюджета (Prometheus / Alertmanager)

```yaml
# Алерт: LCP бюджет сжигается быстрее нормы
- alert: FrontendLCPErrorBudgetBurn
  expr: job:frontend_lcp_good_ratio < 0.99   # SLO 99%
  for: 1h
  annotations:
    summary: "LCP SLO нарушен ({{ $value }})"
    runbook_url: "https://wiki.internal/runbooks/web-vitals-lcp"
    severity: "sev2"

- alert: FrontendINPErrorBudgetBurn
  expr: job:frontend_inp_good_ratio < 0.99
  for: 1h
  annotations:
    summary: "INP SLO нарушен ({{ $value }})"
    runbook_url: "https://wiki.internal/runbooks/web-vitals-inp"
    severity: "sev2"

- alert: FrontendCLSErrorBudgetBurn
  expr: job:frontend_cls_good_ratio < 0.99
  for: 1h
  annotations:
    summary: "CLS SLO нарушен ({{ $value }})"
    runbook_url: "https://wiki.internal/runbooks/web-vitals-cls"
    severity: "sev3"
```

### Блокировка релиза при исчерпании бюджета (CI/CD)

```bash
# Перед деплоем проверяем текущий SLO
SLO_OK=$(curl -s "$PROMETHEUS/api/v1/query?query=job:frontend_lcp_good_ratio" | jq '.data.result[0].value[1] | tonumber > 0.99')
if [ "$SLO_OK" != "true" ]; then echo "Error budget exhausted — deploy blocked"; exit 1; fi
```

### Диагностика в Chrome DevTools

1.  **LCP Discovery:** во вкладке Performance (режим Insights) отображается, был ли LCP-элемент в исходном HTML или добавлен динамически.
2.  **CLS Culprits:** список конкретных DOM-элементов, вызвавших сдвиг, с указанием балла каждого сдвига.
3.  **Long Tasks:** визуализация задач, блокирующих основной поток (Main Thread), для отладки INP. Помечаются красным углом в профиле производительности.

### Приоритизация улучшений

| Проблема | Влияние | Приоритет |
| :--- | :--- | :--- |
| LCP > 2.5 с | Скорость загрузки основного контента | Критический |
| INP > 200 мс | Отзывчивость интерфейса | Критический |
| CLS > 0.1 | Стабильность макета | Высокий |
| TBT > 200 мс | Блокировка основного потока | Средний |

## Для DevOps/SRE/SysAdmin

### Мониторинг и алертинг

Web Vitals в контексте SRE — это SLI для фронтенда. Ключевые принципы:

1. **Используйте перцентили:** всегда ориентируйтесь на p75 (как Google), p95, p99. Средние значения бесполезны для SRE.
2. **Burn Rate Alerting:** алерты строятся на скорости расхода бюджета, а не на абсолютном значении.
3. **Runbook для каждого алерта:** каждый критический алерт по Web Vitals должен содержать ссылку на актуальный Runbook.
4. **Мульти-оконный алертинг:** сочетание длинного окна (28 дней) и короткого (1 час) для снижения шума.

### Тюнинг Nginx/Angie для Web Vitals

**Ключевые директивы, влияющие на Web Vitals:**

```nginx
http {
    # LCP: Zero-Copy для статики
    sendfile on;
    sendfile_max_chunk 512k;
    tcp_nopush on;

    # LCP/INP: асинхронный дисковый I/O
    aio threads=default;

    # LCP: кэширование дескрипторов
    open_file_cache max=10000 inactive=20s;
    open_file_cache_valid 30s;
    open_file_cache_min_uses 2;
    open_file_cache_errors on;

    # INP/CLS: Keepalive к бэкенду
    upstream backend {
        server 10.0.0.1:8080;
        keepalive 32;
        keepalive_timeout 60s;
        keepalive_requests 1000;
    }

    server {
        listen 443 ssl http2;

        location / {
            proxy_pass http://backend;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_buffering on;
            proxy_buffer_size 16k;
            proxy_buffers 8 16k;
        }

        # LCP: кэширование статики
        location ~* \.(jpg|jpeg|png|gif|ico|css|js|woff2)$ {
            expires 365d;
            add_header Cache-Control "public, immutable" always;
            add_header Vary "Accept-Encoding" always;
        }
    }
}
```

### TCP Tuning для низкой задержки

```bash
# /etc/sysctl.d/99-web-vitals.conf
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 16384
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_tw_reuse = 1
net.ipv4.ip_local_port_range = 1024 65535
net.ipv4.tcp_fin_timeout = 30
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_slow_start_after_idle = 0
net.core.rmem_default = 262144
net.core.wmem_default = 262144
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
```

```bash
# Применение
sysctl --system
sysctl net.core.somaxconn
# → net.core.somaxconn = 65535
```

### Service Worker стратегии для Web Vitals

**Cache-first для статики (LCP, CLS):**
```javascript
const CACHE_NAME = 'static-v1';
const STATIC_ASSETS = [
  '/',
  '/styles/main.css',
  '/scripts/main.js',
  '/fonts/inter.woff2',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.destination === 'document') {
    // Network-first для HTML
    event.respondWith(
      fetch(event.request).catch(() => caches.match('/'))
    );
  } else {
    // Cache-first для статики
    event.respondWith(
      caches.match(event.request).then((cached) => cached || fetch(event.request))
    );
  }
});
```

**Stale-while-revalidate для API (INP):**
```javascript
self.addEventListener('fetch', (event) => {
  if (event.request.url.includes('/api/')) {
    event.respondWith(
      caches.open('api-cache').then((cache) => {
        return cache.match(event.request).then((cached) => {
          const fetchPromise = fetch(event.request).then((response) => {
            cache.put(event.request, response.clone());
            return response;
          });
          return cached || fetchPromise;
        });
      })
    );
  }
});
```

### Интеграция Lighthouse CI в пайплайн

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

## Операции и команды

### Диагностика TTFB через curl

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

### Проверка заголовков производительности

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

## Диагностика ошибок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Высокий LCP** | LCP > 2.5 с, медленная загрузка основного контента | Chrome DevTools → Network → фильтр по LCP | `fetchpriority="high"`, кэширование, сжатие, CDN |
| **Высокий INP** | Задержка реакции на действия > 200 мс | Chrome DevTools → Performance → Long Tasks | Code splitting, `async/defer`, вынос в Web Workers |
| **Нестабильный CLS** | Сдвиги макета > 0.1 | Chrome DevTools → Performance → Layout Shifts | Явные размеры для медиа, `font-display: swap`, резервирование места |
| **Высокий TTFB** | LCP > 2.5 с, медленный первый байт | `curl -o /dev/null -s -w "TTFB: %{time_starttransfer}s" URL` | Оптимизация запросов к БД, серверное кэширование, CDN |
| **Блокирующий JS** | TBT > 200 мс, белый экран | Chrome DevTools → Performance → Main Thread | `defer`/`async` для скриптов, динамический импорт, Web Workers |
| **Высокий TBT** | Суммарная блокировка > 200 мс | Lighthouse → TBT metric | Разделение длинных задач, `scheduler.yield()` |
| **Низкий Cache Hit Ratio** | Много `MISS` в заголовках, высокая нагрузка на Origin | `curl -sI URL | grep -iE "x-cache\|age\|cache-control"` | Увеличить TTL, включить `stale-while-revalidate`, проверить Cache Key |
| **Устаревший контент** | Пользователи видят старую версию | `curl -sI URL | grep age` — возраст > `max-age` | Уменьшить TTL, настроить Purge API, использовать Cache Busting |
| **Cache Stampede** | Всплеск нагрузки на Origin | Мониторинг Origin (CPU, RPS) | Включить `proxy_cache_lock`, добавить Jitter TTL, настроить SWR |
| **Vary: * отключает кэш** | Все запросы проходят как MISS | `curl -sI URL | grep -i vary` | Убрать `Vary: *`, использовать конкретные заголовки |

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
*   **Мониторинг RUM:** Отслеживайте p75 LCP, INP, CLS через Prometheus/Grafana. Настройте алерты на Burn Rate.
*   **SLO-based deploy:** Блокируйте релиз при исчерпании Error Budget по Web Vitals.

## Дополнительная информация

### Сравнение полевых и лабораторных данных (Field vs Lab)

| Характеристика | Полевые данные (RUM/CrUX) | Лабораторные данные (Lighthouse) |
| :--- | :--- | :--- |
| **Источник** | Реальные пользователи (Chrome) | Имитация (контролируемая среда) |
| **SEO** | **Прямой фактор ранжирования** | Косвенно (инструмент отладки) |
| **Вариативность** | Высокая (зависит от сети/устройства) | Низкая (воспроизводимые условия) |
| **Охват** | Весь жизненный цикл (INP) | Начальная загрузка (TBT) |

### Рекомендации 2026 года

*   **Page Experience:** Google использует мобильные данные CrUX как первичный фактор для mobile-first индексации. Все три метрики (LCP, INP, CLS) должны проходить порог одновременно.
*   **75-й перцентиль:** Оценка строится по 75-му перцентилю реальных посещений за скользящее окно 28 дней. Даже если медианные значения хороши, деградация нижнего квартиля disqualifies страницу.
*   **Speculation Rules API:** использование правил пререндеринга позволяет достичь LCP в **0 мс**, так как страница уже готова к показу в памяти браузера.
*   **Fetch Priority:** атрибут `fetchpriority="high"` для LCP-изображения — стандарт де-факто. Использование `loading="lazy"` для LCP-элемента — критическая ошибка.
*   **Shared Dictionaries (RFC 9509):** механизм сжатия дельт при обновлении SPA-приложений, радикально снижающий объем передаваемых данных.
*   **HTTP/3 (QUIC):** устранение блокировки очереди (HOL Blocking) на уровне транспорта, снижение задержки handshake.

### Связанные разделы

- [Обзор производительности веб-приложений](./overview.md)
- [Лучшие практики оптимизации](./best_practices.md)
- [Работа с PageSpeed Insights](./pagespeed_insights.md)
- [Кэширование и Web Vitals](./caching.md)
- [Тестирование производительности](./testing_principles.md)
- [SLO/SLI и RUM для фронтенда (SRE-практика)](../CI-CD/Frontend_CI_CD/frontend_slo_rum.md)
- [Оптимизация Nginx](../../WebServers/Nginx/Performance/nginx_performance_tuning.md)
- [Оптимизация сжатия в Nginx](../../WebServers/Nginx/Performance/nginx_compression.md)
- [Концепции SRE](../../Concepts/sre_concepts_main.md)
- [Upstream Keepalive и Connection Pooling](./upstream_keepalive_and_pooling.md) — пул соединений с бэкендом.
- [Zero-Downtime Deployment](./zero_downtime_deployment.md) — graceful reload и worker_shutdown_timeout.
- [Circuit Breaker и Degradation](./circuit_breaker_and_degradation.md) — отказоустойчивость и fallback.
- [Health Checks и Readiness](./health_checks_and_readiness.md) — proactive обнаружение сбоев.
- [Image Optimization Pipeline](./image_optimization_pipeline.md) — CI/CD и AVIF/WebP.
- [Structured Logging для Performance](./structured_logging_for_performance.md) — логи и анализ.

### RFC и спецификации

*   **RFC 9111** — HTTP-кэширование (обновлённый RFC 7234).
*   **RFC 9211** — Cache-Status заголовок.
*   **RFC 9213** — CDN-Cache-Control заголовок.
*   **RFC 5861** — `stale-while-revalidate`, `stale-if-error`.
*   **RFC 9509** — Use-As-Dictionary (Shared Dictionaries) для сжатия дельт.
*   **RFC 9659** — Zstandard (Zstd) сжатие для HTTP.
*   **RFC 9218** — Extensible Prioritization (Fetch Priority API).

### Официальные ресурсы

*   [Web.dev: Core Web Vitals](https://web.dev/core-web-vitals/)
*   [MDN: Web Performance](https://developer.mozilla.org/en-US/docs/Web/Performance)
*   [Chrome DevTools: Performance](https://developer.chrome.com/docs/devtools/performance/)
*   [PageSpeed Insights](https://pagespeed.web.dev/)
*   [Lighthouse CI](https://github.com/GoogleChrome/lighthouse-ci)
*   [web-vitals library](https://github.com/GoogleChrome/web-vitals)
