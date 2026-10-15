# Chrome DevTools для анализа производительности

**Актуально для:** Chrome / Chromium 120+ (CDP 1.3+)

## Определения

**Chrome DevTools** — встроенный в браузер Chromium набор инструментов разработчика и системного инженера. Позволяет исследовать поведение клиентского сетевого стека, профилировать рендеринг, анализировать распределение времени в Main Thread и инспектировать заголовки HTTP/2 и HTTP/3.

**Chrome DevTools Protocol (CDP)** — бинарный и текстовый (JSON-RPC 2.0 поверх WebSocket) протокол управления браузером на низком уровне. Обеспечивает программный сбор метрик, снятие дампов трассировки, эмуляцию сетевых профилей и автоматизированную генерацию HAR-файлов в CI/CD без графической оболочки.

**Headless Mode** — режим исполнения Chromium без графического сервера (X11/Wayland). Начиная с Chrome 112+ (актуальный режим `--headless=new`), запускает полноценный движок браузера со всеми возможностями DevTools, поддержкой WebGPU/WebGL (через программный рендеринг SwiftShader), печатью в PDF и сбором сетевых логов.

**Remote Debugging** — функционал Chromium, открывающий HTTP/WebSocket интерфейс для удаленного подключения к DevTools Backend. Позволяет подключать локальный GUI DevTools к браузеру, работающему на удаленном сервере или в изолированном Docker-контейнере.

**HAR (HTTP Archive)** — стандартизированный JSON-формат для экспорта структуры сетевых сессий. Содержит полные данные обо всех запросах: заголовки, куки, тайминги каждого этапа сокета (DNS, TCP, TLS, TTFB), размеры передаваемых данных и код ответа.

**Waterfall (Водопадная диаграмма)** — графическая хронология выполнения сетевых запросов страницы, отображающая зависимость ресурсов, параллелизм очередей браузера и фазы жизненного цикла соединений.

**Server-Timing** — стандартизированный HTTP-заголовок (`RFC Server-Timing`), транслирующий внутренние серверные метрики (длительность запросов к БД, обращения к кэшу, обработка в middleware) в клиентский браузер для отображения на вкладке Network.

**Лабораторные замеры (Synthetic / Lab Data)** — измерения производительности в строго контролируемой и воспроизводимой среде с фиксированными параметрами CPU и пропускной способности сети. В отличие от RUM (Real User Monitoring), синтетические замеры служат для раннего обнаружения регрессий до попадания кода к реальным пользователям.

---

## Основные концепции

### Архитектура Chrome DevTools и протокол CDP

DevTools построен по клиент-серверной архитектуре:

1. **Inspector (Frontend):** Web-приложение (HTML/TypeScript/CSS), отрисовывающее интерфейс панелей Network, Performance, Application, Console.
2. **Target (Backend):** Встроенный в процесс Chromium сервер отладки, экспортирующий API движков Blink и V8.
3. **Канал связи:** Сообщения в формате JSON-RPC 2.0 передаются по WebSocket-соединению (`ws://127.0.0.1:9222/devtools/page/<target_id>`).

```
+--------------------------------------------------------------+
|                     Chromium Process                         |
|  +---------------------+        +-------------------------+  |
|  | Blink Engine (DOM)  |        | V8 Engine (JS Execution)|  |
|  +----------+----------+        +------------+------------+  |
|             |                                |               |
|             +----------------+---------------+               |
|                              |                               |
|                  +-----------v-----------+                   |
|                  |  DevTools Backend     |                   |
|                  |  (CDP Domains Host)   |                   |
|                  +-----------+-----------+                   |
+------------------------------|-------------------------------+
                               | WebSocket (JSON-RPC 2.0)
                               | Port 9222
+------------------------------v-------------------------------+
|                      DevTools Client                         |
|  [ Chrome GUI (F12) / Puppeteer / Playwright / websocat ]    |
+--------------------------------------------------------------+
```

Архитектура протокола разделена на функциональные домены (Domains):
- **Network:** Перехват событий сетевого стека (`Network.requestWillBeSent`, `Network.responseReceived`, `Network.loadingFinished`), установка блокировок (`Network.setBlockedURLs`) и эмуляция сетевых задержек (`Network.emulateNetworkConditions`).
- **Page:** Жизненный цикл документа (`Page.navigate`, `Page.loadEventFired`), создание скриншотов (`Page.captureScreenshot`) и печать (`Page.printToPDF`).
- **Performance / Tracing:** Запуск низкоуровневой трассировки подсистем Chromium (`Tracing.start`, `Tracing.end`), сбор метрик производительности (`Performance.getMetrics`).
- **HeapProfiler / Profiler:** Снятие дампов памяти V8 Heap Snapshot и замер процессорного времени JavaScript.
- **Emulation:** Управление CPU throttling (`Emulation.setCPUThrottlingRate`), размером экрана и Device Pixel Ratio.
- **Security:** Валидация сертификатов TLS, проверка смешанного содержимого (Mixed Content) и обработка ошибок рукопожатия.

---

### Механика сетевых таймингов Network Waterfall

Каждый сетевой ресурс, отображаемый на вкладке Network, проходит строгую последовательность фаз. Понимание этих фаз критично для SRE при расследовании задержек:

```
[ Request Queuing / Stalled ]
             │
             ▼
      [ DNS Lookup ]
             │
             ▼
    [ TCP Connection ]
             │
             ▼
    [ TLS Handshake ]
             │
             ▼
      [ Request Sent ]
             │
             ▼
[ Waiting for Server Response (TTFB) ]
             │
             ▼
    [ Content Download ]
```

1. **Queuing (Очередь):**
   - Запрос ожидает постановки в сетевой поток.
   - *Причина задержки в HTTP/1.1:* Превышен лимит браузера в 6 одновременных TCP-соединений на один домен (Origin).
   - *Причина в HTTP/2 и HTTP/3:* Высокоприоритетные запросы вытесняют низкоприоритетные при исчерпании лимита параллельных потоков (`SETTINGS_MAX_CONCURRENT_STREAMS`).
2. **Stalled (Зависание):**
   - Время от постановки запроса в очередь до фактического выделения сокета. Включает время на согласование прокси-соединений и выделение дискового дескриптора.
3. **DNS Lookup (Разрешение имен):**
   - Время обращения к локальному resolver или DNS-серверу. Для повторных соединений к уже разрешенному Origin равно 0 мс (берется из DNS-кэша браузера).
4. **Initial Connection (Установка TCP-соединения):**
   - Длительность 3-way handshake (SYN -> SYN-ACK -> ACK). Равна 1 RTT (Round Trip Time) между клиентом и ближайшим сетевым шлюзом/сервером.
5. **SSL / TLS Handshake:**
   - Согласование шифров и обмен ключами. Для TLS 1.2 занимает 2 RTT, для TLS 1.3 — 1 RTT (или 0-RTT при session resumption).
6. **Request Sent:**
   - Время физической записи байтов HTTP-запроса в сокет. Обычно составляет доли миллисекунды; рост указывает на отправку тяжелого POST-тела через канал с медленным Uplink.
7. **Waiting for server response (TTFB — Time to First Byte):**
   - Время от завершения отправки запроса до получения первого байта ответа.
   - *Состав TTFB:* Сетевая задержка до сервера + задержка на обратном прокси (Nginx/Angie/HAProxy) + время генерации страницы приложением/БД + сетевая задержка доставки первого пакета обратно.
8. **Content Download:**
   - Время выкачивания тела ответа из сокета. Зависит от пропускной способности канала (Bandwidth), включенного сжатия (Brotli/Zstd/Gzip) и размера ассета.

---

### Расшифровка бэкенд-таймингов через Server-Timing

Для разделения сетевого времени и реального времени обработки на бэкенде используется заголовок `Server-Timing`. Браузер Chromium автоматически парсит этот заголовок и визуализирует его на вкладке Network внутри вкладки **Timing**:

```http
HTTP/2 200 OK
content-type: text/html; charset=UTF-8
server-timing: cdn-cache;desc="HIT", edge;dur=4.2, app;dur=48.5, db;dur=22.1
```

В интерфейсе DevTools строка TTFB разделяется на сегменты: системный инженер сразу видит, сколько миллисекунд ушло на запрос к базе данных, сколько выполнялся код приложения и какую часть составила сетевая задержка.

---

### DevTools Network Throttling vs Traffic Control ОС

При проведении синтетических тестов важно понимать архитектурное ограничение встроенного троттлинга DevTools:

| Параметр | DevTools Throttling (CDP Emulation) | Эмуляция ядра Linux (`tc-netem`) |
| :--- | :--- | :--- |
| **Уровень работы** | Прикладной уровень (Application layer, HTTP-клиент Chromium) | Сетевой стек ядра (Network/Transport layer, qdisc) |
| **Реализация задержки** | Задержка передачи колбэков внутри event loop браузера | Буферизация и задержка IP-пакетов в кольцевом буфере |
| **Эмуляция Packet Loss** | **Не поддерживается** (только через обрыв потока) | **Поддерживается** реальный процент потери пакетов |
| **TCP Congestion Window** | Игнорируется (алгоритмы BBR/Cubic работают без учета дропов) | Корректно моделируется реакция алгоритма TCP на дропы |
| **HTTP/3 QUIC поведение** | Эмулируется приблизительно | Корректно тестирует восстановление UDP-потоков |
| **Назначение** | Быстрая предварительная отладка фронтенда | Достоверные SRE-бенчмарки и нагрузочное тестирование |

---

### Анализ Main Thread и метрик рендеринга

Вкладка **Performance** визуализирует загрузку главного потока рендеринга (Main Thread). Для SRE-инженера критичны следующие события:

- **Long Tasks (> 50 мс):** Неделимые блоки выполнения JavaScript. Если задача выполняется дольше 50 мс, страница перестает реагировать на ввод пользователя (клики, прокрутку), что напрямую ухудшает метрику **INP (Interaction to Next Paint)** и **TBT (Total Blocking Time)**.
- **Recalculate Styles & Layout (Reflow):** Вычисление геометрии и позиционирования DOM-элементов. Частые пересчеты макета приводят к проседанию FPS и нестабильности разметки (**CLS — Cumulative Layout Shift**).
- **Composite Layers & Paint:** Отрисовка пикселей на слоях графического процессора. Высокая нагрузка на фазе Paint часто вызвана тяжелыми CSS-фильтрами или непрерывной анимацией неаппаратных свойств.

---

## Практические сценарии

### Сценарий 1: Запуск Headless Chromium в Linux и Docker

На серверах без X-сервера Chromium требует строгого набора флагов для предотвращения падений из-за исчерпания разделяемой памяти и ограничений безопасности cgroups.

#### Подготовка окружения Debian/Ubuntu

```bash
# Установка зависимостей Chromium и утилит
sudo apt-get update && sudo apt-get install -y \
  chromium \
  chromium-common \
  dumb-init \
  fonts-liberation \
  libasound2t64 \
  libnspr4 \
  libnss3 \
  curl \
  jq

# Проверка версии установленного браузера
chromium --version
# → Chromium 128.0.6613.119 built on Debian 12
```

#### Запуск демона с безопасной изоляцией

```bash
# Запуск headless-процесса от непривилегированного пользователя
chromium \
  --headless=new \
  --remote-debugging-port=9222 \
  --remote-debugging-address=127.0.0.1 \
  --no-sandbox \
  --disable-gpu \
  --disable-dev-shm-usage \
  --user-data-dir=/tmp/chromium-profile \
  --no-first-run \
  --no-default-browser-check \
  about:blank &
CHROME_PID=$!

# Проверка доступности порта через ss
ss -tlnp | grep 9222
# → LISTEN 0 128 127.0.0.1:9222 users:(("chromium",pid=12345,fd=45))

# Запрос системной информации через HTTP API
curl -s http://127.0.0.1:9222/json/version | jq .
# → {
#     "Browser": "Chrome/128.0.6613.119",
#     "Protocol-Version": "1.3",
#     "User-Agent": "Mozilla/5.0 ... HeadlessChrome/128.0.6613.119 ...",
#     "V8-Version": "12.8.374.24",
#     "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/78a9c8b3-..."
#   }
```

#### Запуск в Docker-контейнере

```dockerfile
# Пример безопасного Dockerfile для Chromium Headless
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    fonts-noto-color-emoji \
    dumb-init \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Создание непривилегированного пользователя
RUN useradd -m -s /bin/bash chromeuser
USER chromeuser

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["chromium", \
     "--headless=new", \
     "--no-sandbox", \
     "--disable-dev-shm-usage", \
     "--disable-gpu", \
     "--remote-debugging-port=9222", \
     "--remote-debugging-address=0.0.0.0"]
```

```bash
# Запуск контейнера с увеличенным размером shm и защитой PID 1
docker run -d \
  --name chromium-headless \
  --init \
  --shm-size=2gb \
  -p 127.0.0.1:9222:9222 \
  chromium-headless:latest
# → 9b2d8e4f1a2c...
```

---

### Сценарий 2: Удаленная отладка через SSH-туннель

> [!WARNING]
> Никогда не публикуйте порт 9222 в открытый доступ сети (`0.0.0.0`). Доступ к CDP позволяет злоумышленнику читать локальные файлы сервера, перехватывать внутренний сетевой трафик и выполнять произвольный код через контекст браузера.

Для безопасного подключения используйте проброс портов через SSH:

```bash
# Выполняется на локальной рабочей станции
ssh -N -L 9222:127.0.0.1:9222 user@target-production-server.internal
```

1. Откройте локальный браузер Chrome.
2. Перейдите по адресу `chrome://inspect/#devices`.
3. В секции **Discover network targets** нажмите **Configure...**.
4. Добавьте адрес `127.0.0.1:9222` и нажмите **Done**.
5. В списке **Remote Target** появится список страниц, запущенных на удаленном сервере. Нажмите **inspect** для открытия полнофункциональной панели DevTools.

---

### Сценарий 3: Захват HAR-архива и сетевых таймингов в CI через CDP

Автоматизированный экспорт сессии в HAR-файл для анализа сетевых регрессий между релизами с использованием Playwright (Node.js или Python).

```python
# capture_har.py — скрипт автоматизированного сбора HAR
import asyncio
from playwright.async_api import async_playwright

async def run_har_audit(target_url: str, output_path: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )
        context = await browser.new_context(
            record_har_path=output_path,
            record_har_mode="full",
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()
        
        # Переход и ожидание завершения фоновых сетевых запросов
        response = await page.goto(target_url, wait_until="networkidle")
        status = response.status if response else 0
        print(f"Status Code: {status}")
        
        await context.close()
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_har_audit("https://example.com", "/tmp/session.har"))
```

```bash
# Запуск сбора
python3 capture_har.py
# → Status Code: 200

# Анализ полученного HAR через jq: подсчет запросов и суммарного трансфера
jq '{
  total_requests: (.log.entries | length),
  total_bytes: ([.log.entries[].response.bodySize] | add),
  status_codes: ([.log.entries[].response.status] | group_by(.) | map({status: .[0], count: length}))
}' /tmp/session.har
# → {
#     "total_requests": 28,
#     "total_bytes": 1458920,
#     "status_codes": [
#       { "status": 200, "count": 27 },
#       { "status": 304, "count": 1 }
#     ]
#   }
```

---

### Сценарий 4: Диагностика сетевых задержек: curl vs Chrome DevTools

Частая жалоба SRE: «curl показывает отклик 50 мс, а в браузере страница грузится 2 секунды». Для выявления расхождений используется детальная разбивка таймингов.

```bash
# Диагностика полного цикла сокета и TTFB через curl
curl -o /dev/null -s -w "\
  DNS Lookup:        %{time_namelookup}s\n\
  TCP Connect:       %{time_connect}s\n\
  TLS Handshake:     %{time_appconnect}s\n\
  Pre-transfer:      %{time_pretransfer}s\n\
  Time to First Byte:%{time_starttransfer}s\n\
  Total Time:        %{time_total}s\n\
  HTTP Code:         %{http_code}\n" https://example.com/api/v1/status
# → DNS Lookup:        0.004120s
# → TCP Connect:       0.021450s
# → TLS Handshake:     0.052180s
# → Pre-transfer:      0.052310s
# → Time to First Byte:0.185420s
# → Total Time:        0.186100s
# → HTTP Code:         200
```

Сравнение сопоставимых параметров:

| Фаза curl | Эквивалент в DevTools Waterfall | Что диагностировать при аномалии |
| :--- | :--- | :--- |
| `time_namelookup` | **DNS Lookup** | Локальный resolver (`/etc/resolv.conf`), DNS TTL |
| `time_connect - time_namelookup` | **Initial Connection (TCP)** | RTT сети, пропускная способность, задержки в маршруте |
| `time_appconnect - time_connect` | **SSL** | Версия протокола (TLS 1.3 быстрее), сертификатная цепочка |
| `time_starttransfer - time_pretransfer` | **Waiting for server response (TTFB)** | Время работы бэкенда, очередей веб-сервера или СУБД |
| `time_total - time_starttransfer` | **Content Download** | MTU/MSS, TCP Window scaling, размер тела ответа |
| *Отсутствует в curl* | **Queuing / Stalled** | Блокировка пула соединений браузера (лимит 6 сокетов) |
| *Отсутствует в curl* | **DOM Parsing / Execution** | Блокирующий JS/CSS в `<head>`, задержки в Main Thread |

---

### Сценарий 5: Аудит SPOF и симуляция сбоев внешних сервисов

Падение внешних метрик, аналитики или шрифтов может заблокировать отрисовку страницы. Для проверки устойчивости инфраструктуры используется функционал **Network Request Blocking** (в GUI) или метод CDP `Network.setBlockedURLs`.

```bash
# Блокировка критичных доменов через CDP с помощью curl и websocat
# 1. Создаем новую вкладку
TARGET=$(curl -s -X PUT "http://127.0.0.1:9222/json/new?https://example.com" | jq -r .id)

# 2. Отправляем команды блокировки доменов аналитики и внешних шрифтов
websocat "ws://127.0.0.1:9222/devtools/page/$TARGET" <<'EOF'
{"id":1,"method":"Network.enable"}
{"id":2,"method":"Network.setBlockedURLs","params":{"urls":["*fonts.googleapis.com*","*analytics*"]}}
{"id":3,"method":"Page.navigate","params":{"url":"https://example.com"}}
EOF
# → {"id":1,"result":{}}
# → {"id":2,"result":{}}
# → {"method":"Network.requestWillBeSent", ...}
# → {"method":"Network.loadingFailed","params":{"blockedReason":"inspector", ...}}
```

**Критерий успешности:** Страница должна отобразить текстовый контент со системными шрифтами (FOUT/FOIT) без зависания основного интерфейса и без падения приложения.

---

### Сценарий 6: Валидация кэширования, сжатия и условных запросов

Проверка корректности выдачи заголовков прокси-сервером (Nginx/Angie):

```bash
# 1. Проверка алгоритма сжатия (Brotli vs Zstd vs Gzip)
curl -sI -H "Accept-Encoding: br, zstd, gzip" https://example.com/assets/app.js | grep -iE "content-encoding|vary|cache-control"
# → content-encoding: br
# → vary: Accept-Encoding
# → cache-control: public, max-age=31536000, immutable

# 2. Проверка валидации кэша через ETag (304 Not Modified)
ETAG=$(curl -sI https://example.com/assets/app.js | awk -F': ' '/[Ee][Tt][Aa][Gg]/ {print $2}' | tr -d '\r')
curl -sI -H "If-None-Match: $ETAG" https://example.com/assets/app.js | grep -E "HTTP/|ETag"
# → HTTP/2 304 Not Modified
# → etag: "66e2c3a1-1f48"

# 3. Проверка поведения stale-while-revalidate
curl -sI https://example.com/api/config | grep -i "cache-control"
# → cache-control: max-age=60, stale-while-revalidate=300
```

---

### Сценарий 7: Автоматизированный запуск Lighthouse CLI в CI/CD без облака

Для запуска синтетических аудитов на self-hosted runners используется утилита `lighthouse` с генерацией отчетов в форматах JSON и HTML.

#### Установка зависимостей в окружении сборщика

```bash
# Установка Lighthouse CLI локально через npm
npm install -g lighthouse

# Запуск аудита с бюджетами производительности
lighthouse https://example.com \
  --chrome-flags="--headless=new --no-sandbox --disable-dev-shm-usage --disable-gpu" \
  --output=json \
  --output=html \
  --output-path=/tmp/lighthouse-report \
  --only-categories=performance \
  --throttling-method=devtools \
  --throttling.rttMs=40 \
  --throttling.throughputKbps=10240
# → Report complete: /tmp/lighthouse-report.report.json
# → Report complete: /tmp/lighthouse-report.report.html
```

#### Парсинг ключевых метрик и валидация SLO

```bash
# Извлечение численных значений Core Web Vitals через jq
jq '{
  performance_score: (.categories.performance.score * 100),
  LCP_sec: (.audits["largest-contentful-paint"].numericValue / 1000),
  TBT_ms: .audits["total-blocking-time"].numericValue,
  CLS: .audits["cumulative-layout-shift"].numericValue
}' /tmp/lighthouse-report.report.json
# → {
#     "performance_score": 96,
#     "LCP_sec": 1.42,
#     "TBT_ms": 45.0,
#     "CLS": 0.012
#   }

# Пример проверки порога в bash-скрипте CI
LCP=$(jq '.audits["largest-contentful-paint"].numericValue' /tmp/lighthouse-report.report.json)
if (( $(echo "$LCP > 2500" | bc -l) )); then
  echo "ОШИБКА: Превышен бюджет LCP (> 2.5 сек). Текущее значение: $LCP мс"
  exit 1
fi
```

---

### Сценарий 8: Профилирование Main Thread и захват трассировок через CDP

Снятие полного файла трассировки (Trace JSON) для последующего исследования узких мест в интерфейсе DevTools (`chrome://tracing` или вкладка **Performance**):

```python
# capture_trace.py — скрипт захвата системной трассировки
import asyncio
import json
from playwright.async_api import async_playwright

async def capture_performance_trace():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        page = await browser.new_page()
        cdp = await page.context.new_cdp_session(page)
        
        # Настройка категорий трассировки Chromium
        await cdp.send("Tracing.start", {
            "categories": "blink.user_timing,devtools.timeline,v8,disabled-by-default-devtools.timeline"
        })
        
        await page.goto("https://example.com", wait_until="networkidle")
        
        # Завершение сбора трассировки
        await cdp.send("Tracing.end")
        
        # Ожидание завершения и сохранение
        print("Трассировка успешно собрана")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(capture_performance_trace())
```

---

## Диагностика ошибок

| Симптом / Ошибка | Первопричина | Метод диагностики | Способ решения |
| :--- | :--- | :--- | :--- |
| **Crash с кодами `SIGBUS` / `SIGSEGV`** | Переполнение `/dev/shm` (по умолчанию в Docker всего 64 МБ). | `dmesg \| grep -E "chromium\|oom"`, логи контейнера. | Добавить флаг `--disable-dev-shm-usage` или запускать Docker с `--shm-size=2gb`. |
| **Падение с кодом `SIGKILL` (OOM)** | Процесс V8 превысил лимит памяти при обработке тяжелого DOM. | `grep -i oom /var/log/syslog`, `dmesg \| tail -20`. | Ограничить аппетит V8 флагом `--js-flags="--max-old-space-size=2048"` и добавить cgroup limits. |
| **Появление процессов-зомби (`<defunct>`)** | Отсутствие PID 1 init-процесса внутри Docker контейнера. | `ps aux \| grep "[c]hromium.*defunct"`. | Запускать контейнер с флагом `--init` или использовать утилиту `dumb-init` / `tini`. |
| **`Connection refused` на порту 9222** | Служба слушает только `127.0.0.1`, а запрос идет снаружи контейнера. | `ss -tlnp \| grep 9222`. | В изолированном контейнере указать `--remote-debugging-address=0.0.0.0` (не публиковать порт на хосте в Интернет!). |
| **Пустой скриншот или пустой PDF** | Рендеринг завершился до загрузки веб-шрифтов или стилей. | Проверка вывода консоли браузера через `Runtime.exceptionThrown`. | Добавить ожидание события `networkidle` или флага `document.fonts.ready`. В Linux установить пакет `fonts-liberation`. |
| **Ошибки `CERT_AUTHORITY_INVALID` на Staging** | Самоподписанный или внутренний корпоративный CA-сертификат. | `Security.securityStateChanged` в CDP или HTTP 0 status. | Добавить корневой CA в системное хранилище или передать флаг `--ignore-certificate-errors` (только для тестов!). |
| **Несоответствие TTFB в DevTools и curl** | Разница в переиспользовании соединений или блокировка пула. | Проверить фазу `Initial Connection` и `Queuing` в Waterfall. | Если TTFB высок только в браузере, проверить конкуренцию за сокеты (лимит 6 сокетов) и переключить сервер на HTTP/2 или HTTP/3. |
| **Отсутствие компрессии ответов** | Несовпадение заголовков `Accept-Encoding` или прокси вырезает заголовок. | `curl -sI -H "Accept-Encoding: gzip, br" URL \| grep -i content-encoding`. | Проверить директивы `gzip_proxied any;` и `brotli_types` в конфигурации веб-сервера. |
| **Кэш прокси не срабатывает (`MISS`)** | Заголовок `Vary: *` или динамические куки в ответе ассета. | `curl -sI URL \| grep -iE "x-cache\|set-cookie\|vary"`. | Настроить игнорирование `Set-Cookie` для статики (`proxy_ignore_headers Set-Cookie;`). |

---

## Рекомендации

### Для DevOps, SRE и системных администраторов

1. **Безопасность удаленного порта отладки:**
   - Категорически запрещено привязывать порт `--remote-debugging-port=9222` к внешним публичным IP-адресам без авторизации. Доступ к CDP равносилен выполнению произвольных команд (RCE).
   - Всегда организуйте доступ к удаленным стендам через SSH Local Port Forwarding (`ssh -L 9222:127.0.0.1:9222`).

2. **Изоляция ресурсов в CI/CD:**
   - Headless Chromium является ресурсоемким приложением: для стабильной работы 1 экземпляра требуется минимум 2 vCPU и 2 ГБ RAM.
   - Всегда запускайте тесты в контейнерах с выделенным размером разделяемой памяти (`--shm-size=2gb`) и флагом `--disable-dev-shm-usage`.

3. **Разделение лабораторных замеров и сетевой реальности:**
   - Не используйте встроенный троттлинг DevTools для проверки поведения TCP/IP и QUIC на нестабильных каналах связи (с потерей пакетов). Для точного моделирования потерь используйте Linux `tc-netem` или аппаратные Traffic Shapers.
   - Для разделения задержек бэкенда и сети внедряйте заголовок `Server-Timing` во всех микросервисах и шлюзах API.

4. **Интеграция с мониторингом и версионирование:**
   - Сохраняйте сгенерированные HAR-файлы и отчеты Lighthouse как артефакты сборки CI. Это позволяет сопоставлять деградацию метрик со списком коммитов.
   - Коррелируйте метрики синтетических тестов (LCP, TTFB) с серверными логами Nginx/Angie (переменные `$request_time` и `$upstream_response_time`).

5. **Очистка временных файлов профиля:**
   - При запуске headless-браузера всегда указывайте уникальный `--user-data-dir` в директории `tmpfs` (RAM-диск) и обеспечивайте удаление профиля после завершения процесса во избежание засорения дискового пространства ноды CI.

---

## Дополнительная информация

### Связанные темы

*   [Обзор производительности веб-приложений](./overview.md) — базовые концепции и архитектура оптимизации.
*   [Ключевые метрики Core Web Vitals](./web_vitals.md) — детальный разбор метрик LCP, INP, CLS.
*   [Принципы и методология тестирования](./testing_principles.md) — синтетические vs реальные данные (RUM).
*   [Профессиональное тестирование в WebPageTest](./webpagetest.md) — глубокое тестирование с реальным traffic shaping.
*   [Работа с PageSpeed Insights](./pagespeed_insights.md) — полевые и лабораторные данные Google.
*   [Протоколы HTTP/2 и HTTP/3](./http2_http3.md) — мультиплексирование потоков и устранение Head-of-Line Blocking.
*   [Механизмы и стратегии кэширования](./caching.md) — настройка `Cache-Control`, ETag и валидации кэша.
*   [Оптимизация сжатия (Gzip, Brotli, Zstd)](./server_compression.md) — уменьшение объема передаваемых данных.
*   [SLO/SLI и RUM для фронтенда (SRE-практика)](../../../CI-CD/Frontend_CI_CD/frontend_slo_rum.md) — выстраивание мониторинга пользовательского опыта.
*   [Image Optimization Pipeline](./image_optimization_pipeline.md) — автоматическая оптимизация графики в пайплайнах.
*   [Structured Logging для Performance](./structured_logging_for_performance.md) — логирование таймингов на стороне сервера.

### Официальные ресурсы

*   [Chrome DevTools: Performance Overview](https://developer.chrome.com/docs/devtools/performance/)
*   [Chrome DevTools Protocol (CDP) Documentation](https://chromedevtools.github.io/devtools-protocol/)
*   [Chromium Headless Mode Documentation](https://developer.chrome.com/docs/chromium/new-headless)
*   [Lighthouse CLI Repository & Documentation](https://github.com/GoogleChrome/lighthouse)
*   [W3C Server-Timing Specification](https://www.w3.org/TR/server-timing/)
