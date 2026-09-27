# Принципы тестирования производительности веб-приложений

## Определения

**Синтетическое тестирование (Synthetic Testing / Lab Data)** — оценка производительности в контролируемой, изолированной среде (лабораторные данные). Позволяет воспроизводимую проверку конфигураций, выявлять регрессии и сравнивать версии кода без влияния внешнего «шума». Основные инструменты: Lighthouse, WebPageTest, Chrome DevTools. Детали: [WebPageTest — инструмент синтетического тестирования](./webpagetest.md), [Chrome DevTools для анализа производительности](./chrome_devtools.md).

**Мониторинг реальных пользователей (Real User Monitoring, RUM / Field Data)** — сбор метрик непосредственно из браузеров реальных посетителей (полевые данные). Отражает реальный опыт с учетом разнообразия устройств, качества связи и географии. Основные источники: Chrome User Experience Report (CrUX), библиотека `web-vitals`, кастомные JS-агенты.

**Холодная загрузка (Cold Load)** — загрузка страницы при полностью очищенном кэше (браузера, DNS, сокетов). Критична для оценки первого впечатления нового пользователя.

**Тёплая загрузка (Warm Load)** — повторная загрузка с использованием ресурсов из локального кэша и Service Workers. Позволяет проверить эффективность политик кэширования и мультиплексирования HTTP/2/3.

**SPOF (Single Point of Failure)** — ресурс или домен (сторонний CDN со шрифтами, аналитика, рекламный скрипт), недоступность или задержка которого полностью блокирует отрисовку основного контента или критическую функциональность страницы.

**Baseline (Базовый показатель)** — медианное значение метрик производительности для стабильной версии, используемое как референс для сравнения при регрессионном тестировании. Определяется по серии из 5–9 прогонов на стабильном конфиге.

**Регрессионное тестирование (Regression Testing)** — повторный запуск тестов после изменений в коде или конфигурации для подтверждения, что производительность не деградировала относительно Baseline.

**Performance Budget (Бюджет производительности)** — максимально допустимые значения метрик и размеров ресурсов, при превышении которых сборка или деплой блокируется. В 2026 году стандартные пороги: LCP ≤ 2.5 с, INP ≤ 200 мс, CLS ≤ 0.1, JS ≤ 500 КБ, CSS ≤ 200 КБ.

**Error Budget (Бюджет ошибок)** — допустимая доля нарушений SLO (100% − SLO). В контексте тестирования: процент «плохих» прогонов, при котором релиз блокируется. При SLO 99% бюджет составляет 1%.

**Burn Rate (Скорость расхода бюджета)** — скорость, с которой расходуется Error Budget. В SRE-практике: если бюджет сжигается в 2× быстрее нормы — алерт sev2, в 10× — sev1.

**Waterfall (Водопадная диаграмма)** — графическая визуализация жизненного цикла каждого запроса: DNS, TCP, TLS, TTFB, Content Download. Ключевой инструмент диагностики узких мест. Цветовая кодика: DNS (тёмно-синий), Connect (оранжевый), SSL/TLS (фиолетовый), TTFB (светло-голубой), Content (синий).

**Headless Testing** — запуск браузера без графического интерфейса для автоматизированного тестирования в CI/CD. В 2026 году headless Chrome поддерживает все вкладки DevTools через CDP и `--remote-debugging-port`. Используется Puppeteer, Playwright.

**TBT (Total Blocking Time)** — сумма периодов блокировки основного потока между FCP и достижением интерактивности. Коррелирует с INP в лабораторных тестах. Цель: **< 200 мс**.

## Основные концепции / Архитектура / Методология

### Стратегия тестирования: Lab Data vs Field Data

Эффективная стратегия 2026 года требует комбинирования обоих подходов:
- **Lab Data:** используется для отладки и предотвращения регрессий в CI/CD. Показывает *потенциальную* скорость при контролируемых условиях.
- **Field Data:** используется для принятия бизнес-решений и оценки влияния на SEO (Core Web Vitals). Показывает *реальный* опыт.

| Характеристика | Полевые данные (RUM/CrUX) | Лабораторные данные (Lighthouse/WebPageTest) |
| :--- | :--- | :--- |
| **Источник** | Реальные пользователи (Chrome) | Имитация (контролируемая среда) |
| **SEO** | **Прямой фактор ранжирования** | Косвенно (инструмент отладки) |
| **Вариативность** | Высокая (зависит от сети/устройства) | Низкая (воспроизводимые условия) |
| **Охват** | Весь жизненный цикл (INP) | Начальная загрузка (TBT) |

Стратегия SRE: Lab Data выявляет проблемы до деплоя, Field Data подтверждает их отсутствие в продакшене.

### Типы тестов и их назначение

**Smoke Test (Дымовой тест):** быстрая проверка после деплоя. Цель — убедиться, что страница загружается и основные метрики в пределах нормы. Время выполнения: 30–60 секунд. Инструменты: Lighthouse, curl.

**Regression Test (Регрессионный тест):** полная проверка метрик Core Web Vitals при каждом изменении кода или конфигурации. Время выполнения: 2–5 минут. Инструменты: Lighthouse CI, WebPageTest.

**Soak Test (Усталостное тестирование):** длительный мониторинг (от 1 часа) для выявления утечек памяти, деградации кэша и роста TTFB под стабильной нагрузкой. Инструменты: WebPageTest (серии прогонов), Prometheus + curl-скрипты.

**Spike Test (Пиковое тестирование):** проверка поведения при всплесках трафика. Цель — убедиться, что TTFB остается в пределах SLO при 2–3× росте RPS. Инструменты: `wrk`, `h2load`, `curl` в цикле.

### Методология тестирования

**Принципы:**
1. **Изоляция:** При локальном тестировании закрывать посторонние вкладки, мессенджеры и отключать расширения браузера (режим Incognito).
2. **Серийность:** Минимум 3–5 последовательных прогонов для одного условия. Медианное значение исключает аномальные выбросы.
3. **Статистическая значимость:** Использование медианы вместо среднего арифметического. Для ключевых метрик учитывать p75 (как Google для CWV).
4. **Контроль переменных:** Троттлинг, устройство и локация должны быть одинаковыми для сравниваемых прогонов.

### Эмуляция условий (Throttling)

Тестирование на мощных рабочих станциях без ограничений искажает реальную картину.

**Стандартные профили 2026:**

| Профиль | RTT | Downlink | Назначение |
| :--- | :--- | :--- | :--- |
| **Good 5G / Fiber** | < 20 мс | 100+ Mbps | Идеальные условия. |
| **Fast 4G** | 40 мс | 9 Mbps | Городской мобильный интернет. |
| **Slow 4G / 3G** | 150+ мс | 1.6 Mbps | Нестабильное покрытие, роуминг. |

**Уровни троттлинга:**
1. **Сетевой троттлинг (Network Throttling):**
   - **Browser-level (DevTools):** Имитация задержек на уровне прикладного уровня. Проста в использовании, но не учитывает особенности TCP/QUIC.
   - **Packet-level (WebPageTest):** Traffic Shaping на уровне сетевых пакетов. Максимально точно имитирует потерю пакетов и реальный RTT. Детали: [WebPageTest](./webpagetest.md).

2. **Процессорный троттлинг (CPU Throttling):**
   - Имитация бюджетных устройств путем замедления CPU в **4x** (средний сегмент) или **6x** (low-end). Критично для выявления проблем парсинга DOM и выполнения JavaScript, незаметных на десктопах.

### Профессиональная диагностика через Performance API

Современные браузеры предоставляют низкоуровневые данные через `window.performance`:
- **Navigation Timing API:** Точные метрики фаз (DNS lookup, TCP handshake, Request/Response time).
- **Resource Timing API:** Детальная информация о загрузке каждого ресурса.
- **User Timing API:** Возможность размечать пользовательские события в коде (`performance.mark()`), которые отображаются в профилировщике.

### Процессорный и сетевой троттлинг в CI/CD

Для автоматизированного тестирования в CI/CD используются headless-браузеры с программным троттлингом:
- **Lighthouse CI:** встроенный троттлинг (мобильный 4G preset). Достаточно для большинства сценариев.
- **Playwright / Puppeteer:** полный контроль над CDP. Возможность эмуляции геолокации, User-Agent, сетевых условий и CPU throttling на уровне Chromium.
- **WebPageTest API:** remote-тестирование на реальных устройствах в распределённой сети. Единственный инструмент с packet-level Traffic Shaping. Детали: [WebPageTest](./webpagetest.md).

### Повторяемость и воспроизводимость

- **Серии прогонов:** Минимум 3–5 последовательных тестов.
- **Медиана (Median):** Использование медианного значения вместо среднего арифметического позволяет исключить влияние аномальных выбросов.
- **Изоляция:** Использование чистого профиля браузера, отключение кэша (Disable cache), режим Incognito.
- **Фиксированные параметры:** Одинаковая локация, устройство, троттлинг-профиль для всех сравниваемых прогонов.

## Практические сценарии / Установка и настройка / Конфигурация

### Сценарий 1: Установка Baseline и определение порогов

**Цель:** определить референсные значения для ключевых метрик на стабильной версии.

1. **Подготовка окружения:**
   - Выберите 3–5 критических страниц (главная, каталог, корзина, checkout).
   - Закройте все посторонние приложения, отключите расширения браузера.
   - ИспользуйтеIncognito с отключенным кэшем.

2. **Запуск серии тестов:**
   ```bash
   # Установка Lighthouse CI
   npm install -g @lhci/cli

   # Серия из 5 прогонов для каждой страницы
   lhci collect --url=https://example.com/ --numberOfRuns=5
   # → Collected 5 runs for https://example.com/
   # → Median LCP: 1.8s (Good)
   # → Median INP: 145ms (Good)
   # → Median CLS: 0.05 (Good)
   ```

3. **Фиксация Baseline:**
   - Запишите медианные значения как Baseline в monitoring-систему (Prometheus, Grafana).
   - Установите пороги с запасом 20% для учета вариативности.

4. **Performance Budget:**
   ```yaml
   # .lighthouserc.js
   module.exports = {
     ci: {
       assert: {
         assertions: {
           'categories:performance': ['error', {minScore: 0.9}],
           'largest-contentful-paint': ['error', {maxNumericValue: 2500}],
           'interactive': ['error', {maxNumericValue: 200}],
           'cumulative-layout-shift': ['error', {maxNumericValue: 0.1}],
         },
       },
     },
   };
   ```

### Сценарий 2: Регрессионное тестирование в CI/CD (Lighthouse CI)

**Цель:** предотвратить попадание медленного кода в продакшн.

1. **Настройка пайплайна:**
   ```yaml
   # .github/workflows/performance.yml
   name: Performance Regression
   on: [pull_request]

   jobs:
     lighthouse:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - run: npm install -g @lhci/cli
         - run: lhci collect --url=https://staging.example.com/ --numberOfRuns=3
         - run: lhci assert
   ```

2. **Интерпретация результатов:**
   - `lhci assert` возвращает non-zero exit code при нарушении порогов — PR блокируется.
   - При падении метрики на 10–20% от Baseline — запросить анализ причины.
   - При изменении Baseline намеренно (оптимизация) — обновить Baseline после ручного подтверждения.

### Сценарий 3: Валидация после деплоя (Post-Deploy Verification)

**Цель:** подтвердить, что деплой не деградировал производительность.

1. **Автоматическая проверка через 5 минут после деплоя:**
   ```bash
   # Проверка TTFB
   TTFB=$(curl -o /dev/null -s -w "%{time_starttransfer}s" https://example.com/)
   echo "TTFB: ${TTFB}s"
   # → TTFB: 0.245s

   # Проверка заголовков
   curl -sI https://example.com/ | grep -iE "cache-control|content-encoding|server-timing|x-cache"
   # → cache-control: public, max-age=31536000, immutable
   # → content-encoding: br
   ```

2. **Сравнение с Baseline:**
   - Если TTFB вырос > 20% — проверить логи бэкенда и БД.
   - Если `x-cache` изменился с `HIT` на `MISS` — проверить конфигурацию кэширования.
   - Если `content-encoding` отсутствует — проверить модули сжатия на прокси.

3. **Synthetic-проверка:**
   - Запустить WebPageTest из локации, близкой к целевой аудитории.
   - Сравнить LCP, FCP, TTFB с Baseline.
   - Детали: [WebPageTest](./webpagetest.md).

### Сценарий 4: Тестирование SPOF (Single Point of Failure)

**Цель:** убедиться, что зависимость от сторонних ресурсов не блокирует отрисовку.

1. **Локальный метод (DevTools):**
   - Откройте DevTools → Network → правый клик → **Block request domain**.
   - Заблокируйте домен (например, `fonts.googleapis.com`).
   - Перезагрузите страницу и проверьте: не «зависла» ли она белым экраном до таймаута.
   - Детали: [Chrome DevTools](./chrome_devtools.md).

2. **Автоматизированный метод (WebPageTest):**
   - В Advanced Settings → Block укажите домен.
   - Запустите Side-by-Side сравнение.
   - Если `Start Render` увеличивается в 2–3 раза — ресурс является блокирующим.

### Сценарий 5: Мониторинг Burn Rate Error Budget

**Цель:** оперативно реагировать на деградацию производительности до исчерпания бюджета.

1. **Recording rules (Prometheus):**
   ```yaml
   - record: job:frontend_lcp_good_ratio
     expr: sum(rate(lcp_good[28d])) / sum(rate(lcp_total[28d]))

   - record: job:frontend_inp_good_ratio
     expr: sum(rate(inp_good[28d])) / sum(rate(inp_total[28d]))

   - record: job:frontend_cls_good_ratio
     expr: sum(rate(cls_good[28d])) / sum(rate(cls_total[28d]))
   ```

2. **Алертинг:**
   ```yaml
   - alert: FrontendLCPErrorBudgetBurn
     expr: job:frontend_lcp_good_ratio < 0.99
     for: 1h
     annotations:
       summary: "LCP SLO нарушен ({{ $value }})"
       severity: "sev2"

   - alert: FrontendINPErrorBudgetBurn
     expr: job:frontend_inp_good_ratio < 0.99
     for: 1h
     annotations:
       summary: "INP SLO нарушен ({{ $value }})"
       severity: "sev2"
   ```

3. **Burn Rate calculation:**
   - Burn Rate = (1 − actual_ratio) / (1 − SLO)
   - При Burn Rate > 1 (норма) — мониторинг.
   - При Burn Rate > 2 — алерт sev2.
   - При Burn Rate > 10 — алерт sev1, эскалация.

### Сценарий 6: Корреляция Lab и Field данных

**Цель:** связать лабораторные регрессии с реальным опытом пользователей.

1. **Сбор Lab Data:**
   - Запустите WebPageTest из локации, близкой к целевой аудитории.
   - Зафиксируйте медианные LCP, INP, CLS.

2. **Сбор Field Data:**
   - Через `web-vitals` отправляйте метрики в аналитику.
   - Через Prometheus Pushgateway или Grafana Faro визуализируйте p75.

3. **Сравнение:**
   - Если Lab LCP = 1.8s, а Field p75 LCP = 3.5s — проблема в сетевых условиях или кэшировании.
   - Если Lab INP = 120ms, а Field p75 INP = 350ms — проблема на специфичных устройствах или в сторонних скриптах.
   - Детали метрик: [Web Vitals](./web_vitals.md).

### Сценарий 7: Soak-тестирование под нагрузкой

**Цель:** выявить деградацию производительности при длительной нагрузке.

1. **Подготовка:**
   - Установите `wrk` или `h2load`.
   - Определите целевую нагрузку (например, 80% от пиковой).

2. **Запуск:**
   ```bash
   # HTTP/2 нагрузочное тестирование
   h2load -n 100000 -c 100 --warm-up-time 5 https://example.com/
   # → 100000 reqs, 100 concurrency, 12.5 MB total
   # → transferred: 1234 MB/s, RPS: 87654
   ```

3. **Мониторинг в реальном времени:**
   - TTFB через `curl` в цикле:
     ```bash
     while true; do
       TTFB=$(curl -o /dev/null -s -w "%{time_starttransfer}s" https://example.com/)
       echo "$(date): TTFB=${TTFB}s"
       sleep 10
     done
     ```
   - Алерт при TTFB > Baseline × 1.5.
   - Проверка логов Nginx/Angie на `upstream timed out`.

## Операции и команды

### Диагностика TTFB и таймингов через curl

```bash
# Полный тайминг запроса (DNS, TCP, TLS, TTFB, Total)
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

# Интерпретация:
# Если TTFB > 500 мс — проблема на стороне бэкенда или БД
# Если TLS > 100 мс — требуется оптимизация TLS (OCSP Stapling, session tickets)
# Детали: [Оптимизация TLS](./tls_optimization.md)
```

### Проверка заголовков производительности

```bash
# Проверка кэширования, сжатия, Server-Timing
curl -sI https://example.com/style.css | grep -iE "cache-control|age|content-encoding|server-timing|x-cache"
# → cache-control: public, max-age=31536000, immutable
# → content-encoding: br
# → age: 300
# → x-cache: HIT
# → server-timing: db;dur=52.3, app;dur=27.2

# Проверка Early Hints (103)
curl -sI -H "Prefer: safe" https://example.com/ | head -5
# → HTTP/2 103
# → link: </css/main.css>; rel=preload; as=style

# Проверка HTTP/3 (QUIC)
curl --http3-only -I https://example.com/ 2>&1 | head -5
# → HTTP/3 200
# → alt-svc: h3=":443"; ma=2592000
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

# Экспорт отчета в HTML
lhci upload --target=trace=s3://bucket/lighthouse
```

### REST API WebPageTest

```bash
# Запуск теста (9 прогонов, 4G, локация Virginia)
curl -X POST "https://www.webpagetest.org/runtest.php?url=https://example.com&k=$API_KEY&f=json&runs=9&location=EC2:Virgin:4G" -o job.json
# → {"statusCode": 200, "data": {"testId": "240123_ABCDEF123", "ownerKey": "1234567890"}}

# Проверка статуса
TEST_ID=$(jq -r '.data.testId' job.json)
curl "https://www.webpagetest.org/testStatus.php?test=$TEST_ID&f=json"
# → {"statusCode": 200, "statusText": "Complete", "data": {"resultsUrl": "https://www.webpagetest.org/result/..."}}

# Получение метрик (JSON)
curl "https://www.webpagetest.org/jsonResult.php?test=$TEST_ID" | jq '.data.median.firstView'
# → {"TTFB": 245, "loadTime": 1820, "LCP": 1650, ...}
```

### Headless Chrome через CDP (Chrome DevTools Protocol)

```bash
# Запуск Chrome в headless с remote debugging
google-chrome --headless --remote-debugging-port=9222 --disable-gpu https://example.com &

# Получение Web Vitals через CDP
curl -s http://localhost:9222/json/list | jq '.[0].webSocketDebuggerUrl'
# → "ws://localhost:9222/devtools/page/..."

# Использование websocat для отправки команд
websocat "ws://localhost:9222/devtools/page/XXX" <<'EOF'
{"id": 1, "method": "Performance.getMetrics"}
EOF
# → {"id": 1, "result": {"metrics": [{"name": "LCP", "value": 1650}, ...]}}
```

### Сбор RUM-данных через Performance API (JavaScript)

```javascript
// Встраивание в страницу для сбора метрик в реальном времени
import {onLCP, onINP, onCLS} from 'web-vitals';

function sendToAnalytics({name, delta, id}) {
  const body = JSON.stringify({name, delta, id, url: location.href});
  (navigator.sendBeacon && navigator.sendBeacon('/analytics', body)) ||
  fetch('/analytics', {body, method: 'POST', keepalive: true});
}

onLCP(sendToAnalytics);
onINP(sendToAnalytics);
onCLS(sendToAnalytics);

// Ожидаемый вывод в консоли DevTools:
// → LCP: 1800.50ms (good)
// → INP: 145.30ms (good)
// → CLS: 0.0500 (good)
```

### Нагрузочное тестирование

```bash
# HTTP/2 нагрузочное тестирование (h2load)
h2load -n 10000 -c 100 --warm-up-time 2 https://example.com/
# → 10000 reqs, 100 concurrency, 12.5 MB total
# → transferred: 1234 MB/s, RPS: 87654

# Нагрузочное тестирование через wrk
wrk -t4 -c100 -d30s --latency https://example.com/
# → Latency 1.24ms, Requests/sec: 34567.89
# → 50% 1.18ms, 75% 1.45ms, 90% 1.89ms, 99% 2.34ms

# curl в цикле для мониторинга TTFB под нагрузкой
for i in $(seq 1 100); do
  curl -o /dev/null -s -w "TTFB: %{time_starttransfer}s\n" https://example.com/
  sleep 0.1
done | awk '/TTFB:/ {sum+=$2; count++} END {print "Avg TTFB:", sum/count "s"}'
# → Avg TTFB: 0.312s
```

## Диагностика ошибок

### Методология диагностики

При падении метрик в тестах используйте следующую последовательность:

1. **Проверка окружения:** Троттлинг корректно включен? Кэш отключен? Нет ли фоновых процессов?
2. **Валидация инструмента:** Lighthouse/WebPageTest/curl — какой инструмент показал деградацию? Перепроверьте вторым.
3. **Анализ Waterfall:** В каком этапе (DNS, TCP, TLS, TTFB, Content) происходит задержка?
4. **Сравнение с Baseline:** На сколько процентов метрика ниже Baseline? Это статистический шум или реальная регрессия?
5. **Изоляция переменных:** Что изменилось с последнего успешного прогона? Код? Конфигурация? Инфраструктура?
6. **Корреляция с Field Data:** Проблема видна реальным пользователям или только в синтетике?

### Типичные ошибки и решения

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Flaky-тесты** | Результаты одного и того же прогона отличаются > 10% | Повторите 5–9 раз, проверьте медиану | Увеличить количество прогонов, исключить фоновые процессы, использовать wireguard вместо WiFi |
| **Throttling не работает** | TTFB стабильно низкий, нет эмуляции медленной сети | Проверьте DevTools → Network → Throttling | Использовать WebPageTest (packet-level) или Playwright с CDP throttle |
| **LHCI assertion failure** | `largest-contentful-paint` падает на 10% | Запустите `lhci collect` локально, сравните с CI | Проверьте違い в окружении: CPU throttling, кэш, геолокация CI-раннера |
| **WebPageTest API timeout** | Тест висит в статусе `Running` > 10 минут | Проверьте `testStatus.php`, логи WPT | Уменьшить `runs` с 9 до 5, выбрать ближайшую локацию, проверить API key |
| **Headless Chrome отрисовывает иначе** | LCP/CLS в headless отличается от GUI на 20%+ | Сравните с обычным Chrome, проверьте DPR | Указать `--window-size=1920,1080`, `--force-device-scale-factor=1`, отключить `--disable-gpu` |
| **RUM данные не приходят** | Метрики не отображаются в аналитике | Проверьте Network → POST /analytics | Проверить CORS, `sendBeacon` поддержку, блокировщики рекламы |
| **Расхождение Lab/Field после деплоя** | Lighthouse показывает Good, а CrUX — Poor | Сравнить `content-length`, TTFB, кэш-заголовки | Проверить географию CDN, наличие `stale-while-revalidate`, конфигурацию `proxy_buffers` |
| **Высокий TTFB в CI** | TTFB 500–1000 мс против 200 мс в продакшене | Сравнить окружение: CI-раннер vs production | Использовать staging-окружение, близкое к production, или WebPageTest из внешней локации |
| **Нет LCP-элемента** | Lighthouse не идентифицирует LCP | Проверить DevTools → Performance → LCP marker | Убедиться, что LCP-элемент загружается в первые 2.5с, не добавлен динамически через JS |
| **Cache HIT в синтетике, MISS в Field** | `x-cache: HIT` в curl, пользователи жалуются на медленную загрузку | Проверить `Cache-Key`, `Vary`, Cookie | Убедиться, что Cache Key не включает User-Agent или Cookie, настроить `proxy_cache_key` |

## Рекомендации

### Чеклист SRE/SysAdmin для тестирования производительности

**Перед началом тестирования:**
- [ ] Выбрать репрезентативные URL (главная, каталог, корзина, API).
- [ ] Определить Baseline на стабильной версии (5–9 прогонов).
- [ ] Установить Performance Budget в `.lighthouserc.js` или `.wptrules.json`.
- [ ] Настроить SLO и Error Budget для LCP, INP, CLS (p75 за 28 дней).
- [ ] Выбрать троттлинг-профиль, соответствующий целевой аудитории.
- [ ] Отключить кэш браузера и расширения при локальном тестировании.

**Во время тестирования:**
- [ ] Запускать минимум 3–5 прогонов для каждого условия.
- [ ] Использовать медианное значение, исключать выбросы.
- [ ] Документировать параметры: локация, устройство, троттлинг, версия Lighthouse/WebPageTest.
- [ ] Сравнивать с Baseline, а не с абсолютьными порогами.

**После деплоя:**
- [ ] Запустить smoke-тест (Lighthouse) в CI/CD.
- [ ] Сравнить TTFB и заголовки с предыдущим деплоем через `curl`.
- [ ] Проверить Burn Rate Error Budget в Prometheus.
- [ ] Через 24 часа проверить Field Data (CrUX или кастомный RUM).

### Оптимальные стратегии тестирования

**Frequency (Частота):**
- **Smoke-тесты:** при каждом деплое (PR).
- **Regression-тесты:** при каждом merge в main.
- **Полные регрессионные прогоны:** nightly, на staging.
- **Soak-тесты:** weekly, на продакшене в часы минимальной нагрузки.

**Tool Selection (Выбор инструмента):**
- **Локальная отладка:** Chrome DevTools (Flame Chart, Network).
- **CI/CD:** Lighthouse CI (быстрый, детерминированный).
- **Глубокая диагностика:** WebPageTest (packet-level, реальные устройства).
- **Мониторинг:** RUM через `web-vitals` + Prometheus/Grafana.
- **Стресс-тестирование:** `wrk`, `h2load`.

### Мониторинг и алертинг

**SLO-based алертинг:**
- Используйте перцентили (p75, как Google), а не средние значения.
- Burn Rate Alerting: алерты на скорости расхода бюджета, а не на абсолютных значениях.
- Мульти-оконный алертинг: длинное окно (28 дней) + короткое (1 час) для снижения шума.
- Runbook для каждого алерта с шагами проверки кэша, CDN и Origin.

**Performance Budget enforcement:**
- Блокируйте сборку при превышении лимитов в CI/CD.
- Отдельный бюджет для JS/CSS/медиа-размеров.
- Автоматическое создание issue при падении метрики на 10%+ от Baseline.

### Откат и бэкап результатов

- Сохраняйте историю Lighthouse-отчетов (HTML + JSON) в S3 или артефактах CI.
- При проблемах с тестом (flaky, внешний сбой) — используйте последний успешный Baseline как fallback.
- Не удаляйте старые Baseline: они нужны для анализа трендов.

### Производительность диагностических инструментов

| Инструмент | Скорость | Точность | Назначение |
| :--- | :--- | :--- | :--- |
| **curl** | < 1 сек | Высокая (TTFB, заголовки) | Быстрая проверка после деплоя |
| **Lighthouse CI** | 30–60 сек | Высокая (Lab Data) | CI/CD, regression testing |
| **Chrome DevTools** | Интерактивный | Высокая (локальная отладка) | Разработка, Flame Chart, Network |
| **WebPageTest** | 2–5 минут | Максимальная (реальные устройства) | Глубокая диагностика, SPOF |
| **wrk / h2load** | < 1 сек | Средняя (RPS, TTFB под нагрузкой) | Стресс-тестирование |

### Работа с flaky-тестами

- **Причины:** фоновые процессы ОС, вариативность сети, блокировщики рекламы, A/B-эксперименты на сайте.
- **Меры:**
  1. Увеличить количество прогонов до 9 (WebPageTest) или 5 (Lighthouse).
  2. Использовать медианное значение.
  3. Исключить переменные: одинаковый троттлинг, отключить кэш, использовать изолированное окружение.
  4. Если тест остаётся flaky — добавить в исключения CI с комментарием, но вернуться к нему через 1 неделю.

## Дополнительная информация

### См. также

- **[Web Vitals — ключевые метрики](./web_vitals.md)** — детальный разбор LCP, INP, CLS, SLO/SLI, Prometheus-алертинг.
- **[Оптимизация производительности: Обзор](./overview.md)** — архитектура уровней оптимизации, Lifecycle загрузки, методология анализа.
- **[Инструментарий Chrome DevTools](./chrome_devtools.md)** — вкладки Network и Performance, CDP, HAR, headless-режим.
- **[WebPageTest — инструмент синтетического тестирования](./webpagetest.md)** — REST API, Traffic Shaping, SPOF, No-Code Experiments.
- **[Лучшие практики оптимизации](./best_practices.md)** — Performance Budget, кэширование, троттлинг, RUM.
- **[Оптимизация TLS](./tls_optimization.md)** — TTFB breakdown, OCSP Stapling, 0-RTT, kTLS.
- [Zero-Downtime Deployment](./zero_downtime_deployment.md) — деплой без прерывания обслуживания.
- [Structured Logging для Performance](./structured_logging_for_performance.md) — анализ логов для performance.
- [Image Optimization Pipeline](./image_optimization_pipeline.md) — CI/CD и AVIF/WebP.
