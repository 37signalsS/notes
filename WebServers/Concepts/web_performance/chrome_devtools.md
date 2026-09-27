# Chrome DevTools для анализа производительности

## Определения

**Chrome DevTools** — встроенный в браузер Chrome (и другие Chromium-браузеры: Edge, Brave, Opera) набор инструментов веб-разработчика. Является ключевым инструментом для глубокого анализа, профилирования и отладки производительности фронтенд-части веб-приложений.

**Chrome DevTools Protocol (CDP)** — протокол низкого уровня для управления Chromium. Позволяет автоматизировать браузер: захватывать трассировки, делать скриншоты, собирать метрики и управлять сетью без GUI. Используется Puppeteer, Playwright и кастомными CI-скриптами.

**Remote Debugging** — режим, при котором Chrome открывает порт для внешнего подключения. Позволяет подключаться к запущенному в headless-режиме экземпляру браузера через CDP для диагностики.

**Headless Mode** — запуск Chrome без графического интерфейса. В 2026 году headless Chrome поддерживает все вкладки DevTools (Network, Performance, Lighthouse) через CDP и `--remote-debugging-port`.

**HAR (HTTP Archive)** — формат для экспорта сетевых запросов. Используется для офлайн-анализа, сравнения версий и передачи данных между инструментами.

## Основные концепции

### Архитектура и принцип работы

DevTools состоит из двух частей:
1. **Frontend (Inspector)** — панель инструментов, открываемая в браузере (`F12`).
2. **Backend (Target)** — встроенный сервер в самом Chrome, принимающий команды по CDP на порту `9222` (при включенном remote debugging).

При обычном использовании обе части работают в одном процессе. При **remote debugging** backend доступен по сети, что позволяет:
- Подключаться к запущенному на сервере экземпляру Chrome из локального браузера.
- Собирать трассировки и HAR на production-подобном окружении без установки GUI.
- Интегрировать DevTools в CI-пайплайны через Puppeteer, Playwright или прямой CDP.

### Открытие и подготовка к диагностике

**Открытие:** `F12` или `Ctrl+Shift+I` (`Cmd+Opt+I` на macOS). Для профессионального тестирования:
- Использовать режим инкогнито (`Ctrl+Shift+N`) для исключения влияния расширений.
- Выносить DevTools в отдельное окно (`Undock into separate window`), чтобы область просмотра (viewport) соответствовала реальному устройству.
- Отключать кэш (чекбокс **Disable cache** во вкладке Network) для «холодного» визита.

### Мобильная эмуляция (Device Toolbar)

Инструмент имитации условий использования сайта конечными пользователями:
- **Выбор устройства:** Эмуляция конкретных моделей (iPhone, Pixel) или режим `Responsive`. Настройка DPR (Device Pixel Ratio).
- **CPU Throttling:** Искусственное замедление CPU (4x, 6x, 20x). Замедление 4–6x соответствует среднему Android-устройству.
- **Network Throttling:** Ограничение полосы и имитация задержек. Пресеты: Fast 4G, Slow 4G, 3G, Offline. Возможно создание пользовательских профилей с настройкой потери пакетов (Packet Loss).
- **Режимы:** `Offline` для тестирования PWA и Service Workers.

### Вкладка Network — анализ загрузки ресурсов

#### Базовые настройки и управление

- **Disable Cache:** Принудительное отключение кэша браузера. Обязательно для имитации «холодного» визита.
- **Preserve Log:** Сохранение истории запросов при переходах между страницами.
- **HAR:** Экспорт (`Export HAR...`) и импорт файлов HTTP Archive для совместной отладки или сравнения с WebPageTest.
- **Поиск (Ctrl+F):** Глобальный поиск подстроки во всех ресурсах (включая заголовки и тело ответа).

#### Фильтрация и параметры отображения

- **Типы ресурсов:** Doc (HTML), CSS, JS, Img, Font, Fetch/XHR, WS (WebSockets).
- **Priority (Приоритет):** Внутренний приоритет браузера (Highest, High, Medium, Low). Неправильное распределение (например, низкий приоритет для LCP-изображения) ухудшает Core Web Vitals.
- **Protocol (Протокол):** Идентификация версий: `h2` (HTTP/2), `h3` (HTTP/3), `http/1.1`.
- **Content Encoding (Сжатие):** Проверка работы сжатия на сервере (Brotli `br`, Gzip `gzip`, Zstd).
- **Shared Dictionaries:** В 2026 году панель отображает использование `Use-As-Dictionary` (RFC 9509) для оптимизации повторных загрузок.

#### Анализ Waterfall (Водопад)

Графическая визуализация жизненного цикла каждого запроса:
- **Queuing:** Время ожидания в очереди (особенно актуально для HTTP/1.1 из-за лимита в 6 соединений на домен).
- **DNS Lookup:** Время разрешения доменного имени.
- **Initial Connection / SSL:** Установка TCP-соединения и TLS-хендшейка.
- **TTFB (Time to First Byte):** Время от отправки запроса до получения первого байта ответа. Высокий TTFB указывает на проблемы на стороне сервера или базы данных.
- **Content Download:** Время физической передачи данных по сети.

#### Анализ размеров и таймингов

- **Transfer Size:** Объем данных, переданных в сжатом виде по сети.
- **Resource Size:** Реальный размер файла после распаковки браузером.
- **Waterfall Markers:** Цветные вертикальные линии: синяя — `DOMContentLoaded`, красная — `Load`. В новых версиях добавлены маркеры FCP и LCP.

#### Блокировка ресурсов (Network Request Blocking)

Доступна через меню `...` → `More Tools`. Позволяет блокировать отдельные файлы или домены (паттерны типа `*.doubleclick.net`). Основной метод тестирования **SPOF (Single Point of Failure)**.

### Вкладка Performance — профилирование производительности

Главный инструмент для анализа рендеринга и выполнения JavaScript в основном потоке (Main Thread).

#### Режимы записи

- **Reload:** Запись профиля при загрузке страницы с нуля.
- **Record (Ctrl+E):** Запись произвольного сценария (прокрутка, открытие модального окна).

#### Анализ основного потока и Flame Graph

Визуализация активности Main Thread с цветовой кодировкой:
- **Жёлтый:** Выполнение JavaScript (скриптинг).
- **Фиолетовый:** Расчет стилей (Recalculate Styles) и компоновка макета (Layout/Reflow).
- **Зелёный:** Отрисовка (Paint) и работа композитора (Composite Layers).
- **Серый:** Системные задачи и время простоя (Idle).

#### Метрики и диагностика

- **Long Tasks:** Задачи длительностью более 50 мс. Большое количество Long Tasks — прямой путь к плохим показателям TBT и INP.
- **Call Tree / Bottom-Up:** Списки функций, отсортированные по времени выполнения. **Self Time** — время внутри функции, **Total Time** — с учетом дочерних вызовов.
- **Interactions (Взаимодействия):** Дорожка для анализа **INP (Interaction to Next Paint)**. Позволяет увидеть задержку ввода, время обработки и задержку отрисовки ответа.
- **Live Metrics:** Панель реального времени, сравнивающая текущие показатели LCP, CLS и INP с полевыми данными CrUX для данного URL.

### Вкладка Application — хранилище и спекулятивная загрузка

- **Speculative Loads (Спекулятивные загрузки):** Раздел для отладки **Speculative Rules API**. Показывает статус пререндеринга (Prerender) и префетчинга (Prefetch) страниц, а также причины их возможной отмены.
- **Service Workers:** Отладка жизненного цикла, пуш-уведомлений и фоновой синхронизации.
- **Storage:** Управление Cookies, LocalStorage, IndexedDB и очистка всех данных (Clear site data).

### Вкладка Lighthouse — автоматический аудит

Инструмент для высокоуровневой оценки сайта по 100-балльной шкале.

- **Категории:** Performance, Accessibility, Best Practices, SEO, PWA.
- **Режимы:** `Navigation` (загрузка), `Timespan` (интервал взаимодействия), `Snapshot` (состояние).
- **Throttling (Троттлинг):**
  - **Simulated:** Математическая модель (быстро, но может ошибаться при сложных JS-зависимостях).
  - **DevTools (Throttling):** Реальное ограничение ресурсов (дольше, но точнее).
- **Opportunities:** Рекомендации по оптимизации (сжатие изображений, удаление неиспользуемого CSS).
- **Diagnostics:** Дополнительные сведения: критические цепочки запросов, размер DOM-дерева, время выполнения сторонних скриптов.

### Вкладка Recorder — автоматизация замеров

Позволяет записывать, воспроизводить и измерять производительность пользовательских сценариев (User Flows).

- **Запись:** Фиксация кликов, прокрутки и ввода данных.
- **Performance Trace:** Кнопка `Measure performance` запускает сценарий и автоматически переходит во вкладку Performance для детального анализа.
- **Экспорт:** Поддержка Puppeteer, Playwright и JSON для интеграции в CI-пайплайны.

### Дополнительные инструменты (More Tools)

#### Rendering (Отрисовка)

- **Layout Shift Regions:** Подсветка синим элементов, которые сдвигаются (причина высокого CLS).
- **Paint Flashing:** Зеленая подсветка областей, которые браузер перерисовывает в данный момент.
- **Frame Rendering Stats:** Оверлей с графиком FPS и использованием GPU памяти.
- **Core Web Vitals Overlay:** Плавающее окно с текущими значениями LCP/CLS/INP поверх страницы.

#### Coverage (Охват кода)

Анализ использования CSS и JS. Показывает, сколько байт кода было фактически выполнено.
- **Красные полоски:** Код не использовался на данной странице.
- **Применение:** Идентификация «мертвого» кода в бандлах и стилях фреймворков для настройки Code Splitting.

#### Memory (Память)

- **Heap Snapshot:** Снимок кучи для поиска утечек памяти. Сравнение двух снимков позволяет увидеть объекты, которые не были собраны Garbage Collector-ом.
- **Allocation Instrumentation:** Профилирование выделения памяти в реальном времени.

## Практические сценарии

### Сценарий: аудит критического пути рендеринга (CRP)

1. Откройте вкладку **Network**, установите **Disable Cache**.
2. Перезагрузите страницу и найдите ресурсы с приоритетом `Highest` (HTML, CSS в `<head>`).
3. Проверьте Waterfall на наличие больших пауз перед началом загрузки CSS.
4. Убедитесь, что JS-файлы в `<head>` имеют атрибуты `async` или `defer`, иначе они блокируют CRP (Waterfall покажет паузу в отрисовке до завершения загрузки JS).

### Сценарий: диагностика высокого INP (Interaction to Next Paint)

1. Во вкладке **Performance** включите **CPU Throttling 4x**.
2. Нажмите **Record**, выполните проблемное действие (например, открытие фильтров в каталоге).
3. Остановите запись. Найдите дорожку **Interactions**.
4. Кликните по красному блоку взаимодействия. В нижней панели изучите:
   - **Input Delay:** Время ожидания из-за занятости Main Thread другими задачами.
   - **Processing Duration:** Время выполнения вашего обработчика события.
   - **Presentation Delay:** Время, затраченное на отрисовку результата (Layout/Paint).

### Сценарий: поиск причин прыжков макета (CLS)

1. В панели **Rendering** включите **Layout Shift Regions**.
2. Взаимодействуйте со страницей (прокрутка, клики по табам).
3. При появлении синих вспышек зафиксируйте, какой элемент сдвигается.
4. В профиле **Performance** найдите событие `Layout Shift`, в блоке `Summary` будет указано значение сдвига и список виновных элементов (Nodes).

### Сценарий: отладка спекулятивной загрузки (Prerender)

1. Откройте вкладку **Application** → **Speculative Loads**.
2. Убедитесь, что правила (Rules) загружены корректно.
3. Наведите на ссылку, подпадающую под правила.
4. Проверьте статус в таблице: `Success` означает, что страница уже отрендерена в фоне и переход будет мгновенным.

### Сценарий: удаленная диагностика через Remote Debugging

Позволяет подключаться к Chrome на удаленном сервере или в контейнере:

```bash
# Запуск Chrome с открытым портом отладки
google-chrome \
  --headless \
  --remote-debugging-port=9222 \
  --no-sandbox \
  --disable-gpu \
  --enable-logging \
  --v=1 \
  https://example.com &
# → Chrome запущен в headless-режиме, CDP доступен на порту 9222

# Проверка доступности
curl -s http://localhost:9222/json/version | jq .
# → {
#     "Browser": "Chrome/125.0.6422.60",
#     "Protocol-Version": "1.3",
#     "User-Agent": "..."
#   }

# Получение списка открытых страниц (targets)
curl -s http://localhost:9222/json/list | jq .
# → [
#     {
#       "id": "E7F7...",
#       "title": "Example Domain",
#       "type": "page",
#       "url": "https://example.com/"
#     }
#   ]
```

### Сценарий: сбор HAR и трассировки через CDP

```bash
# Запуск Chrome с предустановленным HAR-export
google-chrome \
  --headless \
  --remote-debugging-port=9222 \
  --dump-dom \
  https://example.com > /tmp/example.html

# Получение HAR через CDP WebSocket (требуется websocat или wscat)
websocat "ws://localhost:9222/devtools/page/E7F7..." <<'EOF'
{"id":1,"method":"Network.enable"}
{"id":2,"method":"Page.navigate","params":{"url":"https://example.com"}}
{"id":3,"method":"Network.getResponseBody","params":{"requestId":"..."}}
EOF

# Альтернатива: экспорт через DevTools GUI
# Network → Export HAR... → сохранить как example.har
```

### Сценарий: Headless Lighthouse в CI

```bash
# Установка Lighthouse
npm install -g lighthouse

# Запуск в headless-режиме через Chrome
lighthouse https://example.com \
  --chrome-flags="--headless --no-sandbox --disable-gpu" \
  --output=json \
  --output-path=/tmp/lighthouse-report.json \
  --preset=desktop \
  --throttling-method=simulate
# → Generated report /tmp/lighthouse-report.json

# Чтение ключевых метрик
jq '.audits.largest-contentful-paint.displayValue' /tmp/lighthouse-report.json
# → "2.5 s"
```

### Сценарий: скриншоты и PDF в headless-режиме

```bash
# Полный страничный скриншот
google-chrome \
  --headless \
  --screenshot=/tmp/screenshot.png \
  --window-size=1440,900 \
  https://example.com
# → Файл /tmp/screenshot.png сохранен

# PDF-отчет
google-chrome \
  --headless \
  --print-to-pdf=/tmp/page.pdf \
  --print-to-pdf-no-header \
  https://example.com/report
# → Файл /tmp/page.pdf сохранен

# Проверка размера PDF (не должен быть пустым)
ls -lh /tmp/page.pdf
# → -rw-r--r-- 1 mac wheel 245K Sep 23 12:34 /tmp/page.pdf
```

### Сценарий: сбор трассировки производительности через CDP

```bash
# Запуск Chrome с remote debugging
google-chrome \
  --headless \
  --remote-debugging-port=9222 \
  --no-sandbox \
  https://example.com &
CHROME_PID=$!

# Получение ID target-а
TARGET_ID=$(curl -s http://localhost:9222/json/list | jq -r '.[0].id')

# Запись трассировки (через websocat или python websockets)
# Пример на Python с playwright (рекомендуется для CI):
python3 -c "
import asyncio
from playwright.async_api import async_playwright

async def capture_trace():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1440, 'height': 900},
            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        )
        page = await context.new_page()
        await page.route('**/*', lambda route: route.continue_())
        await page.set_viewport_size({'width': 1440, 'height': 900})
        await page.goto('https://example.com', wait_until='networkidle')
        
        # Включение трейсинга
        client = await page.context.new_cdp_session(page)
        await client.send('Tracing.start', {
            'categories': 'blink,cc,devtools.timeline,disabled-by-default-devtools.timeline'
        })
        await page.reload(wait_until='networkidle')
        await client.send('Tracing.end')
        trace = await client.send('Tracing.requestMemoryDump')
        
        # Сохранение trace.json
        import json
        with open('/tmp/trace.json', 'w') as f:
            json.dump(trace, f)
        
        await browser.close()

asyncio.run(capture_trace())
"
# → Trace сохранен в /tmp/trace.json

# Остановка Chrome
kill $CHROME_PID
```

### Сценарий: диагностика утечек памяти через heap snapshots

```bash
# Открытие страницы в headless Chrome
google-chrome \
  --headless \
  --remote-debugging-port=9222 \
  --no-sandbox \
  --disable-gpu \
  https://example.com/app &
CHROME_PID=$!

# Ожидание загрузки
sleep 5

# Получение первого снапшота через CDP
python3 -c "
import asyncio
from playwright.async_api import async_playwright

async def capture_heap():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto('https://example.com/app', wait_until='networkidle')
        
        client = await page.context.new_cdp_session(page)
        await client.send('HeapProfiler.enable')
        snapshot1 = await client.send('HeapProfiler.takeHeapSnapshot')
        
        with open('/tmp/heap-before.json', 'w') as f:
            f.write(snapshot1)
        
        # Выполнение действия, которое может вызвать утечку
        await page.click('button.load-more')
        await page.wait_for_timeout(5000)
        
        snapshot2 = await client.send('HeapProfiler.takeHeapSnapshot')
        with open('/tmp/heap-after.json', 'w') as f:
            f.write(snapshot2)
        
        await browser.close()

asyncio.run(capture_heap())
"
# → Снапшоты сохранены в /tmp/heap-before.json и /tmp/heap-after.json

kill $CHROME_PID
```

### Сценарий: отладка SPOF (Single Point of Failure)

1. Используйте функцию **Network Request Blocking** в DevTools.
2. Заблокируйте домены внешних ресурсов (например, `fonts.googleapis.com`).
3. Перезагрузите страницу и проверьте: не «зависла» ли она белым экраном до таймаута (30+ секунд).
4. **Решение:** Настройка локального хостинга критичных ресурсов или использование `font-display: swap`.

## Операции и команды

### Запуск headless Chrome с remote debugging

```bash
# Базовая команда для CI/серверов
google-chrome \
  --headless \
  --remote-debugging-port=9222 \
  --no-sandbox \
  --disable-gpu \
  --disable-dev-shm-usage \
  --enable-logging \
  --v=1 \
  --user-data-dir=/tmp/chrome-profile \
  https://example.com &
# → Chrome запущен в headless-режиме

# Проверка доступности CDP
curl -s http://localhost:9222/json/version | jq '.Browser'
# → "Chrome/125.0.6422.60"
```

### Получение списка открытых target-ов

```bash
# Список всех открытых страниц и воркеров
curl -s http://localhost:9222/json/list | jq '.[] | {id, title, type, url}'
# → {
#     "id": "E7F7...",
#     "title": "Example Domain",
#     "type": "page",
#     "url": "https://example.com/"
#   }
```

### Экспорт HAR через DevTools Protocol

```bash
# Использование playwright для HAR
python3 -c "
import asyncio
from playwright.async_api import async_playwright

async def export_har():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            record_har_path='/tmp/example.har',
            record_har_mode='minimal'
        )
        page = await context.new_page()
        await page.goto('https://example.com', wait_until='networkidle')
        await context.close()
        await browser.close()

asyncio.run(export_har())
"
# → HAR сохранен в /tmp/example.har

# Проверка HAR (размер, наличие запросов)
ls -lh /tmp/example.har
# → -rw-r--r-- 1 mac wheel 45K Sep 23 12:34 /tmp/example.har
jq '.["log"].entries | length' /tmp/example.har
# → 42
```

### Сбор метрик Core Web Vitals через CDP

```bash
# Включение отслеживания метрик через CDP
python3 -c "
import asyncio
from playwright.async_api import async_playwright

async def capture_vitals():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto('https://example.com', wait_until='networkidle')
        
        client = await page.context.new_cdp_session(page)
        
        # Включение отслеживания
        await client.send('Page.enable')
        await client.send('Performance.enable')
        
        # Получение метрик
        metrics = await client.send('Performance.getMetrics')
        for metric in metrics['metrics']:
            if metric['name'] in ['LCP', 'CLS', 'FCP', 'FID', 'INP']:
                print(f\"{metric['name']}: {metric['value']:.3f}\")
        
        await browser.close()

asyncio.run(capture_vitals())
"
# → LCP: 1.234
# → CLS: 0.045
# → FCP: 0.890
```

### Генерация скриншотов в CI

```bash
# Скриншот всего viewport
google-chrome \
  --headless \
  --screenshot=/tmp/full.png \
  --window-size=1440,900 \
  https://example.com
# → /tmp/full.png

# Скриншот конкретного элемента через CDP
python3 -c "
import asyncio
from playwright.async_api import async_playwright

async def screenshot_element():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1440, 'height': 900})
        await page.goto('https://example.com', wait_until='networkidle')
        await page.locator('header.hero').screenshot(path='/tmp/hero.png')
        print('Hero screenshot saved')
        await browser.close()

asyncio.run(screenshot_element())
"
# → Hero screenshot saved
```

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

## Диагностика ошибок

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Высокий LCP** | LCP > 2.5 с, медленная загрузка основного контента | Chrome DevTools → Network → фильтр по LCP | `fetchpriority="high"`, кэширование, сжатие, CDN |
| **Высокий INP** | Задержка реакции на действия > 200 мс | Chrome DevTools → Performance → Long Tasks | Code splitting, `async/defer`, вынос в Web Workers |
| **Нестабильный CLS** | Сдвиги макета > 0.1 | Chrome DevTools → Performance → Layout Shifts | `aspect-ratio`, размеры изображений, `font-display: swap` |
| **Высокий TTFB** | LCP > 2.5 с, медленный первый байт | `curl -o /dev/null -s -w "TTFB: %{time_starttransfer}s" URL` | Оптимизация запросов к БД, кэширование, CDN |
| **Блокирующий JS** | TBT > 200 мс, белый экран | Chrome DevTools → Performance → Main Thread | `defer`/`async` для скриптов, динамический импорт, Web Workers |
| **Высокий TBT** | Суммарная блокировка > 200 мс | Lighthouse → TBT metric | Разделение длинных задач, `scheduler.yield()` |
| **Низкий Cache Hit Ratio** | Много `MISS` в заголовках, высокая нагрузка на Origin | `curl -sI URL | grep -iE "x-cache\|age\|cache-control"` | Увеличить TTL, включить `stale-while-revalidate`, проверить Cache Key |
| **Устаревший контент** | Пользователи видят старую версию | `curl -sI URL | grep age` — возраст > `max-age` | Уменьшить TTL, настроить Purge API, использовать Cache Busting |
| **Cache Stampede** | Всплеск нагрузки на Origin | Мониторинг Origin (CPU, RPS) | Включить `proxy_cache_lock`, добавить Jitter TTL, настроить SWR |
| **Vary: * отключает кэш** | Все запросы проходят как MISS | `curl -sI URL | grep -i vary` | Убрать `Vary: *`, использовать конкретные заголовки |
| **Chrome OOM / Crash** | Headless Chrome падает с `SIGKILL` | `dmesg | grep -i oom`, логи Chrome (`chrome_debug.log`) | Увеличить `--js-flags="--max-old-space-size=4096"`, проверить `--disable-dev-shm-usage` |
| **CDP не отвечает** | `connection refused` на порту 9222 | `ss -tlnp | grep 9222`, логи Chrome | Проверить, что `--remote-debugging-port` указан, Chrome не запущен без флага |
| **Пустой HAR** | Экспортированный HAR содержит 0 запросов | Проверить `Network.enable` в CDP, режим записи | Убедиться, что запись включена ДО навигации |
| **Trace не записывается** | `Tracing.end` возвращает пустой файл | Проверить категории трейсинга, права на запись | Использовать валидные категории: `blink,cc,devtools.timeline` |
| **Скриншот пустой / белый** | Headless скриншот — белый экран | `--disable-gpu`, `--no-sandbox`, `--disable-dev-shm-usage` | Добавить задержку перед скриншотом, убедиться что страница загрузилась |

## Рекомендации

### Для DevOps/SRE/SysAdmin

*   **Remote Debugging в CI:** Используйте `--remote-debugging-port` для подключения к headless Chrome в пайплайне. Это позволяет подключаться к упавшему сбору для live-диагностики.
*   **Диагностика TTFB:** Используйте `curl -w` для разбивки тайминга (DNS, TCP, TLS, TTFB). Высокий TTFB (>500 мс) — проблема бэкенда или БД.
*   **Мониторинг кэша:** Отслеживайте `X-Cache-Status`, `Age`, `Cache-Status`. Алерты при `Hit Ratio < 80%` или `Age > s-maxage`.
*   **Cache Warming:** После перезапуска прокси/CDN наполняйте кэш популярными ресурсами (bulk load через `curl`).
*   **Аудит заголовков:** Проверяйте `Cache-Control`, `Content-Encoding`, `Vary` после деплоя через `curl -sI`.
*   **Аудит производительности:** Регулярно запускайте Lighthouse CI в пайплайне, анализируйте тренды метрик.
*   **HAR-архивация:** Сохраняйте HAR-файлы для каждого деплоя. Это позволяет сравнивать производительность между версиями и быстро находить регрессии.
*   **Trace в артефактах CI:** Сохраняйте `.json` трейсы как артефакты сборки. Их можно открыть в DevTools позже для глубокого анализа.
*   **Headless Chrome в контейнерах:** Используйте флаги `--no-sandbox`, `--disable-dev-shm-usage` (для Docker), `--disable-gpu`. Устанавливайте лимиты памяти (например, `--js-flags="--max-old-space-size=4096"`).
*   **Корреляция с серверными метриками:** Сопоставляйте Long Tasks в DevTools с пиками CPU/RAM на сервере ( Grafana + Prometheus). Высокая активность в профиле DevTools при низкой нагрузке на сервер указывает на проблему в бэкенде или ORM.
*   **Валидация после деплоя:** Проверяйте, что пользователи видят актуальный контент, а метрики (CHR, TTFB) улучшились.
*   **Мониторинг RUM:** Отслеживайте p75 LCP, INP, CLS через Prometheus/Grafana. Настройте алерты на Burn Rate.

## Дополнительная информация

### Связанные темы

*   [Обзор производительности веб-приложений](./overview.md).
*   [Ключевые метрики Core Web Vitals](./web_vitals.md).
*   [Принципы и методология тестирования](./testing_principles.md).
*   [Работа с PageSpeed Insights](./pagespeed_insights.md).
*   [Профессиональное тестирование в WebPageTest](./webpagetest.md).
*   [Лучшие практики оптимизации](./best_practices.md).
*   [Механизмы и стратегии кэширования](./caching.md).
*   [Протоколы HTTP/2 и HTTP/3](./http2_http3.md).
*   [Оптимизация сжатия (Gzip, Brotli, Zstd)](./server_compression.md).
*   [SLO/SLI и RUM для фронтенда (SRE-практика)](../CI-CD/Frontend_CI_CD/frontend_slo_rum.md).
*   [Zero-Downtime Deployment](./zero_downtime_deployment.md) — деплой без прерывания обслуживания.
*   [Image Optimization Pipeline](./image_optimization_pipeline.md) — AVIF/WebP и CI/CD.
*   [Structured Logging для Performance](./structured_logging_for_performance.md) — логи и анализ.

### Официальные ресурсы

*   [Chrome DevTools: Performance](https://developer.chrome.com/docs/devtools/performance/)
*   [Chrome DevTools Protocol (CDP)](https://chromedevtools.github.io/devtools-protocol/)
*   [Puppeteer Documentation](https://pptr.dev/)
*   [Playwright Documentation](https://playwright.dev/)
*   [Lighthouse CI](https://github.com/GoogleChrome/lighthouse-ci)
