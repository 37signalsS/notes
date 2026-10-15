# Web Vitals — ключевые метрики пользовательского опыта

**Актуально для:** Web Vitals (W3C WebPerf WG / Google CWV 2024–2026), web-vitals v4.x, Lighthouse 12/13+, Chrome 120+, Nginx 1.26+, Angie 1.4+ / 1.8+

## Определения

**Web Vitals** — открытая инициатива Google и W3C Web Performance Working Group по стандартизации единых измеримых метрик качества пользовательского опыта (User Experience) при загрузке, интерактивности и визуальном рендеринге веб-страниц.

**Core Web Vitals (CWV)** — подмножество метрик Web Vitals, выступающее ключевым критерием оценки качества взаимодействия со страницей (Page Experience). Включает три базовых показателя: **LCP**, **INP** и **CLS**. Для прохождения проверки (статус `Passed`) требуется одновременное непревышение порогов по 75-му перцентилю (p75) реальных пользователей.

**Largest Contentful Paint (LCP)** — время от начала навигации до завершения отрисовки самого крупного визуального блока (изображение, видео или текстовый элемент) в видимой области экрана (viewport). Оценивает воспринимаемую скорость загрузки основного содержимого.

**Interaction to Next Paint (INP)** — метрика отзывчивости интерфейса, оценивающая задержку между действием пользователя (клик, тап, нажатие клавиши) и отображением следующего обновленного кадра на экране. Начиная с марта 2024 года, INP полностью заменила устаревшую метрику FID (First Input Delay), оценивая все взаимодействия за сессию, а не только первое.

**Cumulative Layout Shift (CLS)** — показатель визуальной стабильности верстки, суммирующий баллы всех непреднамеренных сдвигов контента, произошедших без прямого взаимодействия пользователя в окне сессии (session window).

**Time to First Byte (TTFB)** — суммарное время от инициации запроса клиентом до получения первого байта ответа от веб-сервера. Включает DNS-резолвинг, TCP-рукопожатие, TLS-хэндшейк, сетевой RTT и серверную задержку генерации ответа.

**First Contentful Paint (FCP)** — время от начала загрузки до момента, когда браузер отрисовывает первый элемент DOM (текст, векторную графику или фоновое изображение).

**Total Blocking Time (TBT)** — суммарное время между FCP и Time to Interactive (TTI), в течение которого главный поток браузера (Main Thread) заблокирован выполнением задач длительностью более 50 мс. Служит лабораторным (Lab) эквивалентом полевой метрики INP.

**Speed Index (SI)** — синтетический показатель скорости визуального заполнения области просмотра в процессе загрузки страницы на основе покадрового анализа видеозаписи.

**Long Animation Frames (LoAF) API** — стандарт W3C и механизм браузера (начиная с Chrome 123+), пришедший на смену Long Tasks API. Позволяет точно атрибутировать задержки INP до конкретных скриптов, функций и этапов рендеринга (style/layout/paint).

**Real User Monitoring (RUM / Field Data)** — непрерывный мониторинг реального пользовательского опыта, собирающий телеметрию непосредственно из браузеров на различных устройствах, операционных системах и типах сетевого подключения.

**Lab Data (Лабораторные / Синтетические данные)** — детерминированные замеры производительности, выполняемые в изолированной контролируемой среде (Lighthouse, headless Chromium) с фиксированными параметрами сети и процессора.

**Chrome User Experience Report (CrUX)** — общедоступная база данных агрегированных полевых метрик реальных пользователей браузера Chrome за 28-дневное скользящее окно, служащая источником данных для алгоритмов Page Experience.

**SLI (Service Level Indicator)** — измеримый количественный показатель качества функционирования сервиса (например, доля запросов с LCP ≤ 2.5 с за 28 дней).

**SLO (Service Level Objective)** — целевой порог SLI, согласуемый как стандарт надежности системы (например, 99% всех пользовательских сессий соответствуют порогу LCP Good).

**Error Budget (Бюджет ошибок)** — допустимая доля сессий или запросов с нарушением SLO ($100\% - \text{SLO}$). Исчерпание бюджета служит инженерным триггером для остановки продуктовых релизов (Feature Freeze).

**Burn Rate** — относительная скорость расхода бюджета ошибок. Burn Rate = 1 означает равномерное исчерпание бюджета в течение запланированного окна (например, 28 дней); Burn Rate > 1 сигнализирует об ускоренной деградации.

**Early Hints (HTTP 103)** — предварительный статус-код HTTP (RFC 8297), возвращаемый веб-сервером клиенту со ссылками на критические ресурсы (`Link: <...>; rel=preload`) до завершения генерации основного тела документа бэкендом.

**Speculation Rules API** — программный JSON-интерфейс в HTML-документе, указывающий браузеру адреса для упреждающей предзагрузки (`prefetch`) или фонового рендеринга (`prerender`) страниц вероятного следующего перехода.

---

## Архитектура и основные концепции

### Метрики Core Web Vitals и их пороговые значения

Оценка Core Web Vitals рассчитывается по 75-му перцентилю (p75) реальных пользовательских визитов за 28-дневный скользящий период. Все три ключевые метрики должны находиться в зоне «Хорошо» одновременно.

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                       CORE WEB VITALS (Пороги p75)                          │
├─────────────────────┬───────────────────────────┬───────────────────────────┤
│ Метрика             │ Хорошо (Good)             │ Плохо (Poor)              │
├─────────────────────┼───────────────────────────┼───────────────────────────┤
│ LCP (Загрузка)      │ ≤ 2.5 секунды             │ > 4.0 секунды             │
│ INP (Отзывчивость)  │ ≤ 200 миллисекунд         │ > 500 миллисекунд         │
│ CLS (Стабильность)  │ ≤ 0.10 балла              │ > 0.25 балла              │
└─────────────────────┴───────────────────────────┴───────────────────────────┘
```

#### Largest Contentful Paint (LCP)

LCP фиксирует момент, когда на экране отрисован самый масштабный блок контента в видимой области:
- Элементы `<img>` и встроенные в `<svg>` картинки `<image>`.
- Изображение постера для видео `<video poster="...">`.
- Элементы с фоновым изображением, загруженным через CSS `url()`.
- Блочные текстовые узлы (`<h1>`–`<h6>`, `<p>`, `<div>`).

##### Декомпозиция фаз LCP

Инженерная диагностика LCP разделяет метрику на четыре последовательные фазы:

```text
Запрос ───────────────► Первый байт ──────► Старт загрузки LCP ──► Загрузка завершена ──► Отрисовка
  │                          │                    │                      │                     │
  └──────── TTFB ────────────┴─ Load Delay ───────┴── Load Duration ─────┴── Render Delay ─────┘
  ◄──────────────────────────────────────── LCP ───────────────────────────────────────────────►
```

1. **Time to First Byte (TTFB) (цель: ≤ 40% от LCP, ≤ 800 мс в CrUX, < 200 мс в on-premise):**
   Время от клика до получения первого байта HTML-ответа. Напрямую зависит от сетевого RTT, скорости TLS-хэндшейка, эффективности обратного прокси (Nginx/Angie), кэширования и производительности бэкенда/СУБД.
2. **Resource Load Delay (задержка начала загрузки ресурса, цель: ≤ 10% от LCP):**
   Интервал между получением первого байта HTML и моментом, когда сетевой стек браузера начинает скачивать LCP-ресурс. Сокращается устранением блокирующего CSS/JS, отправкой `103 Early Hints` и выставлением атрибута `fetchpriority="high"`.
3. **Resource Load Duration (длительность скачивания ресурса, цель: ≤ 40% от LCP):**
   Время передачи байтов LCP-ресурса по сети. Оптимизируется сжатием (AVIF/WebP, Brotli/Zstandard), применением HTTP/2 и HTTP/3 (QUIC), тюнингом буферов сокетов ядра Linux и размещением кэширующих прокси ближе к клиентам.
4. **Element Render Delay (задержка отрисовки элемента, цель: ≤ 10% от LCP):**
   Время между завершением загрузки файла и его визуальным отображением на экране. Зависит от перегрузки главного потока процессора рендерингом стилей, веб-шрифтами и выполнением JavaScript.

#### Interaction to Next Paint (INP)

INP оценивает качество отклика страницы на действия пользователя в течение всей сессии. Фиксируются следующие типы взаимодействий:
- Клик мышью по интерактивному элементу.
- Касание сенсорного экрана (тап).
- Нажатие физической или экранной клавиши.

Не учитываются непрерывные взаимодействия: скроллинг страницы и перемещение курсора мыши.

##### Декомпозиция фаз INP

Каждое взаимодействие состоит из трех компонентов задержки:

```text
Событие ввода (Вход) ───────► Старт обработчика JS ───────► Конец обработчика ───────► Кадр на экране
       │                                │                                │                       │
       └──────── Input Delay ───────────┴──── Processing Duration ───────┴─ Presentation Delay ──┘
       ◄────────────────────────────────────── INP ──────────────────────────────────────────────►
```

1. **Input Delay (Задержка ввода):**
   Время ожидания события в очереди, пока главный поток занят выполнением других фоновых задач (парсинг скриптов, таймеры, аналитика).
2. **Processing Duration (Время обработки):**
   Суммарное процессорное время, затраченное на исполнение зарегистрированных обработчиков событий (`click`, `pointerup`, `keydown`).
3. **Presentation Delay (Задержка отображения):**
   Время, требуемое браузеру на перерасчет стилей (Recalculate Style), обновление макета (Layout), компоновку слоев (Compositing) и отрисовку пикселей в кадровый буфер GPU.

#### Cumulative Layout Shift (CLS)

CLS измеряет визуальную нестабильность верстки, подсчитывая сумму смещений элементов, возникших вне 500-миллисекундного окна после пользовательского взаимодействия.

##### Формула расчета смещения

$$\text{Layout Shift Score} = \text{Impact Fraction} \times \text{Distance Fraction}$$

- **Impact Fraction (Доля воздействия):** доля площади области просмотра (viewport), затронутая смещением нестабильного элемента (объединение видимых областей элемента до и после сдвига).
- **Distance Fraction (Доля расстояния):** максимальное расстояние, на которое сдвинулся элемент по вертикали или горизонтали, деленное на наибольший размер области просмотра.

Причины возникновения сдвигов верстки:
1. Загрузка изображений, баннеров и видео без явных атрибутов `width` и `height` или CSS `aspect-ratio`.
2. Подмена веб-шрифтов (FOUT — Flash of Unstyled Text / FOIT — Flash of Invisible Text) при несовпадении метрик локального и загружаемого шрифта.
3. Асинхронная вставка динамических блоков контента (уведомления, рекламные слоты) поверх существующего DOM-дерева.

### Вспомогательные и лабораторные метрики

| Метрика | Область | Целевой порог | Физический смысл | Взаимосвязь с CWV |
| :--- | :--- | :--- | :--- | :--- |
| **TTFB** | Field & Lab | < 800 мс (CrUX), < 200 мс (on-premise) | Время до первого байта | Фундамент LCP и FCP |
| **FCP** | Field & Lab | ≤ 1.8 с | Первая отрисовка любого элемента контента | Верхняя граница задержки старта рендера |
| **TBT** | Lab | ≤ 200 мс | Суммарное время блокировки Main Thread (> 50 мс) | Лабораторный коррелят полевой метрики INP |
| **Speed Index** | Lab | ≤ 3.4 с | Скорость заполнения видимой части контентом | Интегральный показатель визуального рендера |

### Расчет Performance Score в Lighthouse (версии 12/13+)

Лабораторный индекс производительности рассчитывается по логнормальной шкале распределения с весовыми коэффициентами:

| Метрика | Вес в оценке | Обоснование веса |
| :--- | :--- | :--- |
| **Total Blocking Time (TBT)** | **30%** | Прямой индикатор отзывчивости главного потока и эквивалент INP в лаборатории |
| **Largest Contentful Paint (LCP)** | **25%** | Индикатор восприятия скорости загрузки основного контента |
| **Cumulative Layout Shift (CLS)** | **25%** | Индикатор визуальной стабильности интерфейса |
| **First Contentful Paint (FCP)** | **10%** | Индикатор старта рендеринга страницы |
| **Speed Index (SI)** | **10%** | Оценка динамики визуального заполнения области просмотра |

### Архитектура уровней оптимизации Web Vitals

Оптимизация метрик охватывает пять инфраструктурных уровней:

```text
[ Клиент / Браузер ] ── Main Thread, LoAF, Critical Rendering Path, DOM
        │
        ▼ L4 Сеть (Сетевой стек ядра Linux)
[ Ядро ОС Linux ] ──── BBR Congestion Control, TCP Fast Open, TCP Window, initcwnd 16
        │
        ▼ L7 Транспорт и шифрование
[ Протоколы L7 ] ───── TLS 1.3 0-RTT, HTTP/2 Мультиплексирование, HTTP/3 (QUIC)
        │
        ▼ Обратный прокси (Nginx / Angie)
[ Reverse Proxy ] ──── Zero-Copy sendfile, Microcaching, Brotli/Zstd, Early Hints 103
        │
        ▼ Upstream и хранилище данных
[ Бэкенд и СУБД ] ──── Keepalive пулы, оптимизация SQL, быстрый TTFB (< 100 мс)
```

| Уровень стека | Точки воздействия | Влияние на Web Vitals | Ответственная роль |
| :--- | :--- | :--- | :--- |
| **Клиентский браузер** | Минимизация Long Tasks, разбивка бандлов, атрибут `fetchpriority`, явные размеры `<img>` | Снижение INP и CLS, устранение задержки LCP Render Delay | Frontend Engineer |
| **Транспорт L4 / Сеть** | Алгоритм BBR, `initcwnd 16`, `tcp_fastopen`, отключение slow-start after idle | Сокращение TTFB и LCP Load Duration на 20–40% | SysAdmin / Network Eng |
| **Протокол L7** | TLS 1.3 с Session Resumption, HTTP/2 и HTTP/3 с устранением HoL-блокировок | Ускорение параллельной доставки ресурсов LCP/CSS | DevOps / SysAdmin |
| **Обратный прокси** | Кэширование статики, Microcaching HTML, сжатие Brotli/Zstd, 103 Early Hints | Сокращение TTFB до < 50 мс, мгновенная отдача LCP-ресурсов | SRE / DevOps |
| **Бэкенд и СУБД** | Upstream keepalive пулы, кэширование запросов, устранение блокировок ввода-вывода | Снижение времени генерации документа (TTFB) | Backend / DBA |

---

## Практические сценарии и конфигурация

### Сценарий 1: Высокопроизводительный On-Premise сбор RUM-метрик без внешних SaaS

Сбор метрик строится на базе библиотеки `web-vitals` v4 на клиенте и выделенного легковесного эндпоинта на обратном прокси Nginx или Angie. Обратный прокси принимает маяки `navigator.sendBeacon` и сбрасывает их в буферизованный структурированный JSON-лог без обращения к бэкенду.

#### Клиентский агент отправки метрик

```javascript
// Инициализация сбора Core Web Vitals и отправки через Beacon API
import { onLCP, onINP, onCLS, onTTFB, onFCP } from 'web-vitals';

const RUM_ENDPOINT = '/rum-collect';

function sendMetricToCollector(metric) {
  const payload = JSON.stringify({
    name: metric.name,
    value: Math.round(metric.name === 'CLS' ? metric.value * 1000 : metric.value),
    rating: metric.rating, // 'good' | 'needs-improvement' | 'poor'
    delta: Math.round(metric.name === 'CLS' ? metric.delta * 1000 : metric.delta),
    id: metric.id,
    navigationType: metric.navigationType,
    page: window.location.pathname,
    connection: navigator.connection ? navigator.connection.effectiveType : 'unknown'
  });

  if (navigator.sendBeacon) {
    navigator.sendBeacon(RUM_ENDPOINT, payload);
  } else {
    fetch(RUM_ENDPOINT, {
      body: payload,
      method: 'POST',
      keepalive: true,
      headers: { 'Content-Type': 'application/json' }
    }).catch(() => {});
  }
}

// Регистрация метрик с передачей отчетов
onLCP(sendMetricToCollector);
onINP(sendMetricToCollector);
onCLS(sendMetricToCollector);
onTTFB(sendMetricToCollector);
onFCP(sendMetricToCollector);
```

#### Конфигурация Nginx/Angie для приёма RUM-логов

```nginx
# Определение структурированного формата RUM-лога
log_format rum_json escape=json '{'
    '"timestamp":"$time_iso8601",'
    '"remote_addr":"$remote_addr",'
    '"user_agent":"$http_user_agent",'
    '"request_method":"$request_method",'
    '"uri":"$uri",'
    '"status":$status,'
    '"request_time":$request_time,'
    '"rum_payload":"$request_body"'
'}';

server {
    listen 443 ssl http2;
    server_name example.internal;

    # Прием RUM-маяков с минимальным overhead
    location = /rum-collect {
        # Сброс тела запроса в память для записи в лог
        client_max_body_size 16k;
        client_body_buffer_size 16k;
        
        # Буферизованная запись для исключения задержек дискового I/O
        access_log /var/log/nginx/rum_access.json rum_json buffer=64k flush=5s;

        # Возврат мгновенного ответа без передачи на бэкенд
        return 204;
    }
}
```

*Собранные логи далее доставляются через on-premise сборщик (Vector, Promtail) в ClickHouse или VictoriaMetrics для построения графиков в Grafana.*

---

### Сценарий 2: Расчет SLI/SLO и Multi-Window Burn Rate алертинг в Prometheus

Определение порога качества фронтенда в соответствии с практиками SRE:

- **SLI:** Доля сессий с LCP ≤ 2.5 с, INP ≤ 200 мс и CLS ≤ 0.10.
- **SLO:** 99.0% всех сессий за скользящее 28-дневное окно соответствуют критерию Good.
- **Бюджет ошибок (Error Budget):** $1.0\% = 0.01$.

#### Prometheus Recording Rules

```yaml
# /etc/prometheus/rules/frontend_web_vitals_sli.yml
groups:
  - name: frontend_web_vitals_sli
    interval: 30s
    rules:
      # Доля успешных LCP за 28 дней и короткие окна
      - record: job:frontend_lcp_good_ratio:28d
        expr: >
          sum(rate(frontend_lcp_duration_seconds_bucket{le="2.5"}[28d]))
          /
          sum(rate(frontend_lcp_duration_seconds_count[28d]))

      - record: job:frontend_lcp_good_ratio:1h
        expr: >
          sum(rate(frontend_lcp_duration_seconds_bucket{le="2.5"}[1h]))
          /
          sum(rate(frontend_lcp_duration_seconds_count[1h]))

      - record: job:frontend_lcp_good_ratio:6h
        expr: >
          sum(rate(frontend_lcp_duration_seconds_bucket{le="2.5"}[6h]))
          /
          sum(rate(frontend_lcp_duration_seconds_count[6h]))

      # Расчет Multi-Window Burn Rate для LCP (SLO = 99%, порог ошибки = 0.01)
      - record: job:frontend_lcp_burn_rate:1h
        expr: (1 - job:frontend_lcp_good_ratio:1h) / (1 - 0.99)

      - record: job:frontend_lcp_burn_rate:6h
        expr: (1 - job:frontend_lcp_good_ratio:6h) / (1 - 0.99)
```

#### Alertmanager Rules (Multi-Window Multi-Burn-Rate)

```yaml
# /etc/prometheus/rules/frontend_web_vitals_alerts.yml
groups:
  - name: frontend_web_vitals_alerts
    rules:
      # Критический алерт Sev1: сжигание 2% бюджета за 1 час (Burn Rate > 14.4)
      - alert: FrontendLCPBudgetExhaustionSev1
        expr: >
          job:frontend_lcp_burn_rate:1h > 14.4
          and
          job:frontend_lcp_good_ratio:1h < 0.99
        for: 3m
        labels:
          severity: sev1
          tier: frontend
        annotations:
          summary: "Критическое сжигание бюджета ошибок LCP (Burn Rate: {{ $value | printf \"%.2f\" }})"
          description: "За последний час более 14.4% бюджета ошибок сожжено. Текущий LCP p75 критически превышен."
          runbook_url: "https://wiki.internal/sre/runbooks/lcp-degradation"

      # Предупреждающий алерт Sev2: сжигание 5% бюджета за 6 часов (Burn Rate > 6.0)
      - alert: FrontendLCPBudgetExhaustionSev2
        expr: >
          job:frontend_lcp_burn_rate:6h > 6.0
          and
          job:frontend_lcp_good_ratio:6h < 0.99
        for: 15m
        labels:
          severity: sev2
          tier: frontend
        annotations:
          summary: "Ускоренное сжигание бюджета ошибок LCP за 6 часов"
          description: "Burn Rate превышает норму в 6 раз. Риск исчерпания месячного SLO."
          runbook_url: "https://wiki.internal/sre/runbooks/lcp-degradation"
```

---

### Сценарий 3: Комплексный тюнинг Nginx и Angie для оптимизации Web Vitals

Конфигурация оптимизирует отдачу статики, сокращает сетевые задержки, включает HTTP/2 и HTTP/3, кэширует дескрипторы файлов и снижает TTFB за счет пулов постоянных соединений с бэкендом.

```nginx
# /etc/nginx/nginx.conf
user nginx;
worker_processes auto;
worker_rlimit_nofile 65535;

events {
    worker_connections 16384;
    use epoll;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # 1. Zero-Copy I/O и оптимизация отправки пакетов
    sendfile on;
    sendfile_max_chunk 512k;
    tcp_nopush on;
    tcp_nodelay on;

    # 2. Асинхронный дисковый ввод-вывод для тяжелой статики
    aio threads=default;
    directio 4m;

    # 3. Кэширование дескрипторов файлов в памяти воркера
    open_file_cache max=50000 inactive=60s;
    open_file_cache_valid 120s;
    open_file_cache_min_uses 2;
    open_file_cache_errors on;

    # 4. Сжатие Brotli и Gzip (включая предварительно сжатые ассеты)
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 5;
    gzip_min_length 256;
    gzip_types text/plain text/css application/javascript application/json image/svg+xml;
    gzip_static on; # Отдача .gz без затрат CPU

    # Если скомпилирован модуль ngx_brotli:
    # brotli on;
    # brotli_comp_level 5;
    # brotli_static on;
    # brotli_types text/plain text/css application/javascript application/json image/svg+xml;

    # 5. Пул Keepalive-соединений к апстримам для минимизации TTFB
    upstream backend_pool {
        server 127.0.0.1:8080 max_fails=3 fail_timeout=10s;
        keepalive 64;
        keepalive_requests 10000;
        keepalive_timeout 60s;
    }

    server {
        listen 443 ssl http2;
        # Для поддержки HTTP/3 (Angie или Nginx 1.25+ с quic):
        # listen 443 quic reuseport;
        # add_header Alt-Svc 'h3=":443"; ma=86400' always;

        server_name app.internal;

        # TLS 1.3 с минимизацией задержки рукопожатия
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
        ssl_prefer_server_ciphers off;
        ssl_session_cache shared:SSL:50m;
        ssl_session_timeout 1d;
        ssl_session_tickets on;

        # Отправка 103 Early Hints в Angie для предварительной загрузки стилей/шрифтов
        # early_hints on;

        # Проксирование на динамический бэкенд
        location / {
            proxy_pass http://backend_pool;
            proxy_http_version 1.1;
            proxy_set_header Connection ""; # Обязательно для активации keepalive
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

            # Буферизация для защиты бэкенда от медленных клиентов
            proxy_buffering on;
            proxy_buffer_size 8k;
            proxy_buffers 16 8k;
            proxy_busy_buffers_size 16k;

            # Защита от всплесков задержки при обновлении кэша
            # proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
        }

        # Оптимизированная отдача статики и веб-шрифтов (LCP / CLS)
        location ~* \.(css|js|woff2|avif|webp|png|jpg)$ {
            root /var/www/static;
            expires 365d;
            add_header Cache-Control "public, max-age=31536000, immutable" always;
            add_header Access-Control-Allow-Origin "*" always;
            access_log off;
        }
    }
}
```

---

### Сценарий 4: Системный сетевой тюнинг ядра Linux для низкой задержки (Sysctl и Initial Congestion Window)

Тюнинг сетевого стека Linux снижает сетевые задержки при первом обращении, предотвращает сбросы пакетов при всплесках трафика и обеспечивает высокую пропускную способность.

#### Конфигурация параметров ядра

```ini
# /etc/sysctl.d/99-web-vitals.conf

# 1. Размер очереди сокетов на уровне ядра (защита от SYN-дропов при всплесках)
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.core.netdev_max_backlog = 16384

# 2. Использование современного алгоритма контроля перегрузки BBR
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# 3. Устранение задержек повторного старта после простоя
net.ipv4.tcp_slow_start_after_idle = 0

# 4. Активация TCP Fast Open для клиента и сервера (код 3 = bidirectional)
net.ipv4.tcp_fastopen = 3

# 5. Повторное использование сокетов в состоянии TIME_WAIT
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15

# 6. Расширение диапазона эфемерных портов
net.ipv4.ip_local_port_range = 1024 65535

# 7. Автонастройка буферов TCP для устранения бутылочных горлышек BDP
net.core.rmem_default = 262144
net.core.wmem_default = 262144
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
```

Применение настроек:
```bash
sudo sysctl --system
# → net.core.somaxconn = 65535
# → net.ipv4.tcp_congestion_control = bbr
# → net.ipv4.tcp_fastopen = 3
```

#### Настройка Initial Congestion Window (`initcwnd`)

По умолчанию в ядре Linux начальное окно передачи (`initcwnd`) равно 10 пакетам (~14.6 КБ). Увеличение до 16 пакетов позволяет передать критический CSS-бандл и начальный HTML за один RTT без ожидания подтверждения (ACK).

```bash
# Проверка текущих параметров шлюза по умолчанию
ip route show default
# → default via 192.168.1.1 dev eth0 proto dhcp metric 100

# Увеличение initcwnd и initrwnd до 16 пакетов
sudo ip route change default via 192.168.1.1 dev eth0 initcwnd 16 initrwnd 16

# Верификация применения
ip route show default
# → default via 192.168.1.1 dev eth0 proto dhcp metric 100 initcwnd 16 initrwnd 16
```

---

### Сценарий 5: Локальный CI/CD пайплайн тестирования Web Vitals (Lighthouse CI On-Premise)

Автоматизированный аудит запускается в локальном изолированном раннере с безголовым Chromium для верификации бюджета производительности перед деплоем.

#### Конфигурационный файл `.lighthouserc.js`

```javascript
// .lighthouserc.js
module.exports = {
  ci: {
    collect: {
      url: ['http://localhost:3000/', 'http://localhost:3000/catalog'],
      numberOfRuns: 3,
      settings: {
        chromeFlags: '--no-sandbox --headless --disable-gpu',
        throttlingMethod: 'simulate',
        throttling: {
          rttMs: 40,
          throughputKbps: 10240,
          cpuSlowdownMultiplier: 1,
        },
      },
    },
    assert: {
      assertions: {
        'categories:performance': ['error', { minScore: 0.90 }],
        'largest-contentful-paint': ['error', { maxNumericValue: 2500 }],
        'total-blocking-time': ['error', { maxNumericValue: 200 }],
        'cumulative-layout-shift': ['error', { maxNumericValue: 0.10 }],
        'first-contentful-paint': ['warn', { maxNumericValue: 1800 }],
      },
    },
    upload: {
      target: 'filesystem',
      outputDir: './lighthouse-reports',
    },
  },
};
```

#### Запуск проверки в CI/CD скрипте с блокировкой деплоя

```bash
#!/usr/bin/env bash
set -eo pipefail

echo "==> Запуск Lighthouse CI аудита..."
npx @lhci/cli collect --config=.lighthouserc.js

echo "==> Валидация Core Web Vitals порогов..."
npx @lhci/cli assert --config=.lighthouserc.js

echo "==> Проверка текущего RUM SLO в Prometheus перед релизом..."
PROMETHEUS_URL="http://prometheus.internal:9090"
SLO_RATIO=$(curl -s -G "${PROMETHEUS_URL}/api/v1/query" \
  --data-urlencode 'query=job:frontend_lcp_good_ratio:28d' \
  | jq -r '.data.result[0].value[1] // 0')

echo "Текущий 28-дневный LCP SLO: ${SLO_RATIO}"

# Проверка условия непревышения бюджета ошибок (SLO >= 0.99)
IS_SLO_MET=$(awk -v ratio="$SLO_RATIO" 'BEGIN { print (ratio >= 0.99) ? "true" : "false" }')

if [ "$IS_SLO_MET" != "true" ]; then
  echo "ОШИБКА: Бюджет ошибок исчерпан (SLO < 0.99). Релиз заблокирован согласно SRE-политике."
  exit 1
fi

echo "Все проверки пройдены успешно. Деплой разрешен."
```

---

## Операции и команды

### Декомпозиция сетевых фаз и TTFB через curl

```bash
# Диагностика сетевых задержек запроса к веб-серверу
curl -o /dev/null -s -w "\
  DNS Lookup:        %{time_namelookup}s\n\
  TCP Connect:       %{time_connect}s\n\
  TLS Handshake:     %{time_appconnect}s\n\
  Pre-transfer:      %{time_pretransfer}s\n\
  Time to First Byte (TTFB): %{time_starttransfer}s\n\
  Total Duration:    %{time_total}s\n\
  HTTP Code:         %{http_code}\n\
  Download Size:     %{size_download} bytes\n" \
  https://app.internal/api/catalog
# → DNS Lookup:        0.002s
# → TCP Connect:       0.015s
# → TLS Handshake:     0.038s
# → Pre-transfer:      0.038s
# → Time to First Byte (TTFB): 0.112s
# → Total Duration:    0.158s
# → HTTP Code:         200
# → Download Size:     14890 bytes
```

### Проверка заголовков кэширования, сжатия и протоколов

```bash
# Проверка заголовков кэширования и сжатия Brotli
curl -sI -H "Accept-Encoding: br, gzip" https://app.internal/static/app.bundle.js | grep -iE "cache-control|content-encoding|alt-svc|etag"
# → cache-control: public, max-age=31536000, immutable
# → content-encoding: br
# → etag: W/"661e7a2b-1f8a"
# → alt-svc: h3=":443"; ma=86400

# Проверка отправки 103 Early Hints
curl -sI -H "Prefer: safe" https://app.internal/ | head -n 8
# → HTTP/2 103
# → link: </static/main.css>; rel=preload; as=style
# → link: </static/fonts/inter.woff2>; rel=preload; as=font; type=font/woff2; crossorigin
```

### Анализ перцентилей TTFB и времени запроса из access-логов Nginx

```bash
# Вычисление p50, p95 и p99 для $request_time из структурированного лога
awk '{print $NF}' /var/log/nginx/access_timing.log | sort -n | awk '
  BEGIN { c = 0 }
  { a[c++] = $1 }
  END {
    print "p50: " a[int(c * 0.50)] "s"
    print "p75: " a[int(c * 0.75)] "s"
    print "p95: " a[int(c * 0.95)] "s"
    print "p99: " a[int(c * 0.99)] "s"
  }'
# → p50: 0.045s
# → p75: 0.082s
# → p95: 0.210s
# → p99: 0.485s
```

### Проверка работоспособности HTTP/3

```bash
# Запрос по HTTP/3 через curl (при поддержке библиотеки ngtcp2/quiche)
curl --http3-only -sI https://app.internal/ | head -n 4
# → HTTP/3 200
# → content-type: text/html; charset=UTF-8
# → server: nginx
# → alt-svc: h3=":443"; ma=86400
```

---

## Диагностика и устранение неполадок

| Проблема / Метрика | Симптом | Метод диагностики | Корневая причина | Инженерное решение (DevOps / SRE) |
| :--- | :--- | :--- | :--- | :--- |
| **Высокий LCP (> 2.5 с)** | LCP-изображение появляется с задержкой 3–5 секунд | Chrome DevTools → вкладка Performance / Network | 1. Высокий TTFB бэкенда.<br>2. Картинка не приоритизирована.<br>3. Блокирующий CSS/JS | 1. Настроить Microcaching на Nginx/Angie.<br>2. Добавить `fetchpriority="high"` и `preload`.<br>3. Включить 103 Early Hints |
| **Высокий INP (> 200 мс)** | Задержка интерфейса на клики и нажатия клавиш | Профилирование Long Tasks и LoAF API в DevTools | Длительные JS-задачи (> 50 мс) блокируют Main Thread | 1. Code splitting и отложенная загрузка скриптов.<br>2. Вынос вычислений в Web Workers.<br>3. Использование `scheduler.yield()` |
| **Нестабильный CLS (> 0.10)** | Сдвиг текста и кнопок при загрузке страницы | DevTools Performance → дорожка Layout Shifts | 1. Шрифты переключаются с задержкой.<br>2. Изображения без `width`/`height` | 1. Применить `font-display: swap` с точным fallback.<br>2. Добавить `aspect-ratio` в CSS для медиа |
| **Высокий TTFB (> 800 мс)** | curl показывает `time_starttransfer > 0.8s` | `curl -w` тайминг breakdown; логи `$upstream_header_time` | 1. Медленные SQL-запросы.<br>2. Отсутствие upstream keepalive.<br>3. Сетевой RTT | 1. Включить `keepalive` в блоке `upstream`.<br>2. Оптимизировать СУБД/индексы.<br>3. Перенести кэш на обратный прокси |
| **Высокий TBT (> 200 мс)** | Долгая блокировка потока в Lighthouse | Lighthouse CI отчёт → вкладка Diagnostics | Монолитный JS-бандл парсится и компилируется целиком | 1. Разбить бандлы по маршрутам.<br>2. Исключить неиспользуемый JS (`tree-shaking`).<br>3. Включить сжатие Brotli |
| **Падение Cache Hit Ratio** | Всплеск нагрузки на бэкенд, рост TTFB | Анализ `$upstream_cache_status` в access-логах | 1. Нестабильный Cache Key.<br>2. Заголовок `Vary: *`.<br>3. Cookie в запросах статики | 1. Нормализовать `$request_uri` в ключе кэша.<br>2. Удалить заголовок `Vary: *`.<br>3. Убрать `Set-Cookie` для статики |
| **Cache Stampede (Thundering Herd)** | Лавинообразный рост CPU при истечении TTL кэша | Мониторинг RPS апстрима в момент сброса кэша | Сотни параллельных запросов идут к бэкенду за одним ресурсом | Включить `proxy_cache_lock on;` и `proxy_cache_use_stale updating;` |
| **Сжатие не применяется** | Текстовые файлы отдаются с `Content-Encoding: identity` | `curl -sI -H "Accept-Encoding: gzip, br"` | 1. Размер файла меньше `gzip_min_length`.<br>2. Отсутствует MIME-тип в `gzip_types` | 1. Добавить `application/javascript`, `image/svg+xml` в `gzip_types`.<br>2. Проверить `gzip_proxied any;` |

---

## Рекомендации и лучшие практики

### Практики для DevOps, SRE и системных администраторов

1. **Ориентируйтесь исключительно на перцентили (p75, p95, p99):** Средние значения скрывают проблемы у клиентов со слабыми сетями и медленными устройствами.
2. **Внедряйте Zero-Overhead RUM:** Прием телеметрии через `sendBeacon` в Nginx/Angie без проксирования на бэкенд позволяет обрабатывать десятки тысяч событий в секунду без деградации инфраструктуры.
3. **Автоматизируйте Performance Gates в CI/CD:** Ни один коммит не должен попадать в продуктив при превышении порогов Lighthouse CI (LCP > 2.5 с, TBT > 200 мс, CLS > 0.10).
4. **Обеспечивайте сквозной Upstream Keepalive:** Отсутствие директивы `keepalive` в блоке `upstream` заставляет прокси открывать новое TCP-соединение на каждый запрос, добавляя 2–5 мс сетевого оверхеда на каждый вызов API.
5. **Используйте предварительное сжатие статики (Pre-compressed assets):** Генерируйте `.br` и `.gz` файлы на этапе сборки CI/CD и отдавайте их директивами `brotli_static on;` и `gzip_static on;`, экономя процессорные циклы веб-сервера.
6. **Настраивайте размер Initial Congestion Window (`initcwnd 16`):** Это гарантирует передачу критических стилей и HTML за 1 сетевой RTT.
7. **Контролируйте кэширование статики через `immutable`:** Всегда передавайте `Cache-Control: public, max-age=31536000, immutable` для файлов с хэшем в имени (fingerprint).

### Антипаттерны (Anti-Patterns)

- **Ленивая загрузка (Lazy Loading) для LCP-изображения:** Использование атрибута `loading="lazy"` на главном баннере или hero-изображении искусственно задерживает начало его загрузки браузером, приводя к деградации LCP на 1–3 секунды.
- **Ориентация исключительно на лабораторные данные:** Синтетические тесты не воспроизводят реальный спектр задержек сотовых сетей, фоновые вкладки и старые мобильные процессоры.
- **Отсутствие резервирования размеров под динамический контент:** Вставка баннеров и асинхронных фреймов без фиксированных CSS-рамок гарантированно ломает CLS.
- **Мониторинг Web Vitals без разделения типов устройств:** Показатели на Desktop и Mobile имеют кардинально разное распределение. Агрегация «в одну кучу» искажает реальное состояние дел.

---

## Дополнительная информация

### Сравнение полевых и лабораторных данных (Field vs Lab)

```text
┌────────────────────────┬───────────────────────────────────┬───────────────────────────────────┐
│ Параметр               │ Полевые данные (RUM / CrUX)       │ Лабораторные данные (Lighthouse)  │
├────────────────────────┼───────────────────────────────────┼───────────────────────────────────┤
│ Источник               │ Реальные пользователи             │ Изолированный безголовый браузер  │
│ Влияние на SEO         │ Официальный фактор ранжирования   │ Косвенное (инструмент валидации)  │
│ Окружение              │ Разнородные устройства и сети     │ Фиксированный троттлинг CPU/Сети  │
│ Интерактивность        │ Метрика INP (все клики за сессию) │ Метрика TBT (прокси-индикатор)    │
│ Стабильность условий   │ Высокая дисперсия (шум)           │ 100% воспроизводимость условий    │
│ Окно наблюдения        │ 28-дневное скользящее окно        │ Моментальный точечный срез        │
└────────────────────────┴───────────────────────────────────┴───────────────────────────────────┘
```

### Спецификации и стандарты RFC

- **RFC 9111** — HTTP Caching (актуальный стандарт кэширования в HTTP).
- **RFC 8297** — An HTTP Status Code for Indicating Hints (HTTP 103 Early Hints).
- **RFC 9113** — HTTP/2 (мультиплексирование, приоритизация потоков, сжатие заголовков HPACK).
- **RFC 9114** — HTTP/3 (HTTP поверх транспорта QUIC/UDP, устранение Head-of-Line блокировок).
- **RFC 9211** — The Cache-Status HTTP Response Header.
- **RFC 9213** — Targeted HTTP Cache-Control Headers (`CDN-Cache-Control`).
- **RFC 5861** — HTTP Cache-Control Extensions for Stale Content (`stale-while-revalidate`, `stale-if-error`).
- **RFC 9509** — Use-As-Dictionary HTTP Header Format (Shared Dictionaries).
- **RFC 9659** — Zstandard Compression and the application/zstd Media Type.

### Связанные разделы базы знаний

- [Обзор производительности веб-приложений](./overview.md)
- [Лучшие практики веб-производительности](./best_practices.md)
- [Работа с PageSpeed Insights](./pagespeed_insights.md)
- [Кэширование и Web Vitals](./caching.md)
- [Принципы тестирования производительности](./testing_principles.md)
- [Протоколы HTTP/2 и HTTP/3](./http2_http3.md)
- [Оптимизация TLS/SSL](./tls_optimization.md)
- [Сжатие на стороне веб-сервера](./server_compression.md)
- [Structured Logging для веб-производительности](./structured_logging_for_performance.md)
- [Upstream Keepalive и Connection Pooling](./upstream_keepalive_and_pooling.md)
- [Диагностика в Chrome DevTools](./chrome_devtools.md)
- [SLO/SLI и RUM для фронтенда](../../../CI-CD/Frontend_CI_CD/frontend_slo_rum.md)
- [Оптимизация производительности Nginx](../../Nginx/Performance/nginx_performance_tuning.md)
- [Оптимизация сжатия в Nginx](../../Nginx/Performance/nginx_compression.md)
- [Концепции SRE и управление надежностью](../../../Concepts/sre_concepts_main.md)
