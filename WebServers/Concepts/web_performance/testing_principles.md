# Принципы тестирования производительности веб-приложений

**Актуально для:** Lighthouse CI 0.14+ / Chromium 120+ (CDP 1.3+) / Linux Kernel 5.15+ (tc/netem)

## Определения

**Синтетическое тестирование (Synthetic Testing / Lab Data)** — измерение производительности веб-приложения в изолированной, строго контролируемой аппаратной и сетевой среде (лабораторные данные). Применяется для регулярной валидации конфигураций, раннего выявления регрессий в CI/CD и детерминированного сравнения сборок без воздействия внешнего шума (сетевого джиттера, разнородности клиентских устройств). Инструменты: Lighthouse, WebPageTest, Chrome DevTools Protocol.

**Мониторинг реальных пользователей (Real User Monitoring, RUM / Field Data)** — пассивный сбор и агрегация метрик производительности непосредственно из браузеров реальных пользователей (полевые данные). Отражает фактический пользовательский опыт с учетом всего спектра клиентского оборудования, операционных систем, типов сетевого подключения и географической удаленности. Основные источники: Chrome User Experience Report (CrUX), библиотека `web-vitals`, внутренние коллекторы на базе OpenTelemetry / Beacon API.

**Серверный бенчмаркинг (Server-side Load / Stress Testing)** — генерация искусственного входящего HTTP/HTTPS-трафика на обратные прокси и бэкенды для определения пропускной способности (RPS), времени ответа сервера под нагрузкой и пределов насыщения системных ресурсов (CPU, RAM, диск, сокеты ядра). В отличие от синтетических тестов страниц, измеряет устойчивость инфраструктуры, а не скорость рендеринга в браузере. Детали: [Инструменты для бенчмаркинга веб-серверов](../../webserver_benchmarking.md).

**Baseline (Базовый уровень производительности)** — эталонный статистический профиль метрик стабильной версии приложения или серверной конфигурации, полученный в результате серии идентичных прогонов (обычно 5–9 тестов с расчетом медианы). Служит точкой отсчета для обнаружения деградации в последующих релизах.

**Регрессионное тестирование производительности (Performance Regression Testing)** — автоматизированный запуск тестов производительности при каждом изменении исходного кода или параметров инфраструктуры для подтверждения отсутствия деградации ключевых метрик относительно зафиксированного Baseline.

**Performance Budget (Бюджет производительности)** — декларативный набор предельно допустимых пороговых значений метрик (Core Web Vitals, TTFB) и физических объемов ресурсов (размеры бандлов JavaScript, CSS, изображений, шрифтов). Превышение бюджета на этапе автоматизированного тестирования приводит к остановке пайплайна (Quality Gate).

**Error Budget (Бюджет ошибок в SRE)** — допустимая доля отклонения от целевого уровня надежности и производительности ($100\% - \text{SLO}$), рассчитываемая за скользящий интервал (например, 28 дней). В контексте веб-производительности определяет долю запросов или синтетических проверок, которым разрешено не уложиться в целевые пороги.

**Burn Rate (Скорость выжигания бюджета)** — относительная скорость расходования бюджета ошибок. Значение $1.0$ означает, что при текущей скорости деградации весь бюджет будет исчерпан ровно к концу учетного интервала SLO; значение $14.4$ сигнализирует о риске выжигания бюджета за считанные часы (критический инцидент Sev1).

**Сетевой и процессорный троттлинг (Throttling)** — искусственное ограничение пропускной способности, задержки сети и вычислительной мощности CPU для имитации работы веб-приложения на мобильных или бюджетных устройствах:
*   *Browser-level Throttling (эмуляция в браузере)* — программная задержка передачи данных движком Chromium через CDP. Проста в настройке, но не учитывает особенности транспортного уровня TCP/QUIC.
*   *Packet-level Throttling (шейпинг на уровне ядра Linux)* — физическое моделирование RTT, джиттера и потерь пакетов с помощью подсистемы `tc netem`. Обеспечивает стопроцентную точность работы сетевого стека.

**Headless Testing (Тестирование в безголовом режиме)** — запуск браузера без графической подсистемы (X11/Wayland) на серверах и в CI-контейнерах. Современный режим Chromium (`--headless=new`) полностью эквивалентен GUI-версии по механизмам сетевого взаимодействия, парсинга DOM, компиляции JavaScript и выполнения протокола CDP. Детали: [Chrome DevTools для анализа производительности](./chrome_devtools.md).

**Waterfall (Водопадная диаграмма)** — графическая хронология жизненного цикла каждого HTTP-запроса страницы: разрешение DNS, TCP handshake, TLS handshake, TTFB (отправка запроса и ожидание ответа сервера) и Content Download (передача тела ресурса).

**SPOF (Single Point of Failure) веб-ресурсов** — внешняя зависимость (сторонний CDN со шрифтами, скрипт аналитики, рекламный пиксель), недоступность или длительная задержка ответа которой полностью блокирует отрисовку первого экрана (Critical Rendering Path) или парализует работу страницы.

**Coordinated Omission (Координированное упущение)** — методологический дефект генераторов нагрузки с закрытым циклом (Closed Loop), при котором зависание сервера на одном запросе блокирует отправку последующих запланированных запросов. Это приводит к искусственному занижению хвостовых перцентилей задержки (p95/p99) и маскировке реальной деградации.

---

## Основные концепции и архитектура

### Стратегия тестирования: Lab Data, Field Data и серверный бенчмаркинг

Полноценная стратегия обеспечения веб-производительности в SRE/DevOps объединяет три взаимодополняющих контура:

1.  **Lab Data (Синтетика):** работает в CI/CD пайплайнах и на регулярных синтетических зондах. Исключает внешний шум, позволяя строго локализовать регрессии в коде до выкатки на пользователей.
2.  **Field Data (RUM):** собирает фактические телеметрические данные из браузеров клиентов. Учитывает реальные распределения сетей, кэшей и слабых мобильных процессоров; является источником данных для поисковых алгоритмов Google (Core Web Vitals).
3.  **Server-side Benchmarking:** оценивает предельную производительность веб-серверов (Nginx, Angie, Envoy), балансировщиков и бэкендов в изолированном контуре сети датацентра.

```text
+─────────────────────────────────────────────────────────────────────────────+
|                     КОНТУРЫ ТЕСТИРОВАНИЯ ПРОИЗВОДИТЕЛЬНОСТИ                 |
+─────────────────────────────────────────────────────────────────────────────+
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        ▼                              ▼                              ▼
+────────────────────────+ +────────────────────────+ +────────────────────────+
|   Server Benchmarking  | |   Synthetic / Lab      | |      Field Data / RUM  |
|  (wrk2, h2load, k6)    | | (Lighthouse, CDP, WPT) | | (web-vitals, RUM-агент)|
+────────────────────────+ +────────────────────────+ +────────────────────────+
| • Пропускная способность| | • Детерминированность  | | • Реальные пользователи|
| • RPS, насыщение CPU/FD| | • Блокировка в CI/CD   | | • Учет слабых устройств|
| • TTFB под нагрузкой   | | • Core Web Vitals (lab)| | • Валидация в продакшене|
| • Очереди соединений   | | • Контроль бандлов     | | • Влияние на SEO (CrUX)|
+────────────────────────+ +────────────────────────+ +────────────────────────+
```

| Параметр | Серверный бенчмаркинг | Лабораторные данные (Lab) | Полевые данные (RUM) |
| :--- | :--- | :--- | :--- |
| **Точка замера** | Сетевой сокет веб-сервера | Движок headless-браузера | Браузер реального клиента |
| **Воспроизводимость** | Высокая (в изолированной сети) | Максимальная (строгие лимиты) | Низкая (высокая дисперсия) |
| **Основной фокус** | Насыщение ядра, RPS, concurrency | Скорость рендеринга, вес ресурсов | Пользовательский опыт, конверсия |
| **Ключевые метрики** | RPS, Latency p99, Error Rate | LCP, TBT, CLS, размер бандлов | LCP, INP, CLS, TTFB p75 |
| **Этап внедрения** | Нагрузочные стенды, staging | CI/CD (Pull Requests), pre-release | Непрерывный мониторинг продакшена |

### Классификация тестов веб-производительности

1.  **Smoke Test (Дымовое тестирование производительности):**
    Экспресс-проверка после деплоя (длительность: 15–30 секунд). Задача: убедиться, что сервер отвечает с корректными заголовками сжатия (Brotli/Gzip/zstd), HTTP-статусом 200, HTTP/2 или HTTP/3, а базовый TTFB не превышает допустимый лимит (например, 300 мс).
2.  **Regression Test (Регрессионный тест производительности):**
    Запуск полного аудита Lighthouse CI на тестовом стенде при каждом PR. Оценивает влияние измененных стилей, скриптов и разметки на метрики Core Web Vitals и бюджеты размеров файлов относительно базовой ветки.
3.  **Soak Test (Тестирование на выносливость / стабильность):**
    Длительный прогон (от нескольких часов до суток) со стабильной умеренной нагрузкой. Направлен на выявление утечек памяти в Node.js/SSR-процессах, переполнения пулов Keepalive-соединений к базам данных и деградации кэширующих прокси.
4.  **Spike Test (Пиковое тестирование):**
    Кратковременная подача резкого всплеска запросов (в 3–5 раз выше штатного максимума). Проверяет устойчивость систем автодеградации, работу буферов очередей и корректность поведения Rate Limiter.
5.  **Fault-Injection & SPOF Test (Тестирование устойчивости к отказам):**
    Искусственная изоляция или замедление внешних доменов (шрифты, CDN, счетчики аналитики) через сетевые правила или CDP. Цель — гарантировать, что при тайм-ауте стороннего сервиса страница отобразит основной контент без зависания.

### Статистическая методология и обеспечение воспроизводимости

Синтетическое тестирование крайне подвержено сетевому и аппаратному шуму. Для получения достоверных результатов SRE-методология требует строгого соблюдения пяти правил:

1.  **Отказ от среднего арифметического в пользу перцентилей:**
    Среднее арифметическое маскирует катастрофические задержки («закон среднего»). Для фиксации Baseline используется **медиана (p50)** серии прогонов. Для полевых данных (RUM) индустриальным стандартом оценки Core Web Vitals является **75-й перцентиль (p75)**. Для серверных задержек используются **p95, p99 и p99.9**.
2.  **Серийность замеров (Sample Size):**
    Одиночный прогон не имеет статистической ценности. Стандарт для CI/CD — минимум **3–5 прогонов**. Для эталонной фиксации Baseline или публикации официальных бенчмарков — **7–9 прогонов**.
3.  **Исключение аномалий (Outlier Rejection):**
    При серии из $N$ прогонов отбрасываются максимальное и минимальное значения, а итоговая оценка строится по медианному значению оставшейся выборки.
4.  **Прогрев (Warmup Phase):**
    Первый запуск после развертывания сервиса или старта контейнера прогревает JIT-компилятор V8, буферный пул СУБД, кэши DNS и файловой системы ОС. Первый прогон по умолчанию помечается как Warmup и не включается в расчет Baseline.
5.  **Аппаратная изоляция CI-раннеров:**
    Тестирование на перегруженных общих runner-узлах с плавающим показателем CPU Steal (при виртуализации) порождает ложные срабатывания (Flaky Tests). Раннеры синтетического тестирования должны размещаться на выделенных bare-metal серверах или KVM-виртуальных машинах с жестко закрепленными ядрами CPU (`taskset` / `cpuset`).

### Эмуляция сетевых и аппаратных условий (Throttling)

Тестирование на высокопроизводительных серверах с 10-гигабитными сетевыми интерфейсами формирует ложное представление о реальной скорости приложения.

#### 1. Сетевой троттлинг: Browser-level vs Packet-level

```text
[ Browser-level Throttling (CDP) ]
  Приложение ──► [ Chromium Network Stack ] ── (Программная задержка в буфере) ──► eth0
  * Проблема: не моделирует сброс TCP-окна, retransmission timeout, потери пакетов QUIC.

[ Packet-level Throttling (Linux tc netem) ]
  Приложение ──► Chromium ──► Linux Kernel (TCP/IP / UDP) ──► [ qdisc netem ] ──► eth0
  * Полное соответствие реальной физике сети (джиттер, drop пакетов, буфер очереди).
```

*   **Browser-level (CDP / Lighthouse):** Управляется через команду `Network.emulateNetworkConditions`. Chromium искусственно задерживает вызовы `OnDataReceived`. Преимущество: не требует root-прав на сервере. Ограничение: непригодно для тестирования надежности транспорта HTTP/3 (QUIC) и TCP Congestion Control при потерях пакетов.
*   **Packet-level (`tc netem` ядра Linux):** Управляется системной утилитой `tc` подсистемы ядра `iproute2`. Моделирует реальные задержки передачи кадров, распределение задержек по закону Гаусса, дублирование и процент потерь пакетов. Детали: [tc netem — эмуляция сетевых проблем](../../../Linux/Networking/Tools/iproute2/tc_netem.md).

**Стандартные сетевые профили для синтетики:**

| Профиль | RTT (Latency) | Скорость Downlink | Скорость Uplink | Потери пакетов |
| :--- | :--- | :--- | :--- | :--- |
| **Fast 4G (Good Mobile)** | 40 мс | 9.0 Мбит/с | 1.5 Мбит/с | 0% |
| **Slow 4G / Public Wi-Fi** | 150 мс | 1.6 Мбит/с | 750 Кбит/с | 0.5% |
| **Lossy Mobile (Нестабильный)** | 200 мс | 1.0 Мбит/с | 500 Кбит/с | 2.0% |

#### 2. Процессорный троттлинг (CPU Throttling)

Современные десктопные процессоры выполняют компиляцию и выполнение JavaScript в 5–10 раз быстрее мобильных чипов начального и среднего сегмента.
*   **4x CPU Slowdown:** стандартный профиль Lighthouse для моделирования устройств среднего класса (Moto G power, популярные китайские SoC).
*   **6x CPU Slowdown:** стресс-профиль для моделирования low-end смартфонов. Позволяет мгновенно вскрыть неэффективные алгоритмы парсинга развесистого DOM, утечки при гидратации в React/Vue и длинные задачи (Long Tasks > 50 мс), приводящие к деградации метрики INP.

### Анатомия таймингов клиентского и сетевого жизненного цикла

Для выявления узких мест в архитектуре необходимо четко разграничивать фазы обслуживания запроса по стандарту W3C Navigation Timing Level 2:

```text
|<─────────────────────────────────── total_time ───────────────────────────────────>|
|-- DNS --|-- TCP --|-- TLS --|-- TTFB (Wait) --|-- Content Download --|-- Processing --|
^         ^         ^         ^                 ^                      ^                ^
startTime |         |         |                 |                      |                |
     domainLookup   connect   connectEnd   responseStart          responseEnd        loadEvent
```

*   **DNS Lookup (`domainLookupEnd - domainLookupStart`):** время резолвинга имени. В норме < 20 мс при прогретом кэше; > 100 мс указывает на проблемы с локальным DNS-резолвером или неэффективный TTL.
*   **TCP Handshake (`connectEnd - connectStart`):** длительность одного RTT до балансировщика.
*   **TLS Handshake (`connectEnd - secureConnectionStart`):** согласование шифров и обмен сертификатами (1 RTT в TLS 1.3, 2 RTT в TLS 1.2). Детали: [Оптимизация TLS](./tls_optimization.md).
*   **TTFB (Time to First Byte):** время от отправки HTTP-запроса до получения первого байта заголовков. Включает сетевую доставку до сервера, обработку в Nginx/Angie, задержку бэкенда и БД.
*   **Content Download (`responseEnd - responseStart`):** время передачи полезной нагрузки тела ответа. Зависит от пропускной способности канала, эффективности сжатия (Brotli/zstd) и размера ресурса. Детали: [Сжатие данных на веб-сервере](./server_compression.md).

### SRE-подход: Performance Budget, SLI/SLO и Burn Rate Error Budget

#### 1. Performance Budget в CI/CD

Бюджет фиксируется в репозитории как код (`.lighthouserc.js` или `budget.json`) и проверяется при сборке:
*   **Бюджет времени (Timing Budgets):** LCP ≤ 2500 мс, INP ≤ 200 мс, CLS ≤ 0.1, TTFB ≤ 600 мс.
*   **Бюджет веса (Size Budgets):** общий объем сжатого JavaScript ≤ 350 КБ, CSS ≤ 70 КБ, шрифты (WOFF2) ≤ 100 КБ, начальные изображения первого экрана ≤ 500 КБ.

#### 2. Математика Burn Rate для веб-производительности

Если целевой SLO доступности и скорости составляет $99\%$ «быстрых» запросов за окно в 28 дней, то допустимый бюджет ошибок:
$$\text{Error Budget} = 100\% - 99\% = 1\% = 0.01$$

Фактическая доля плохих запросов за расчетный интервал:
$$P_{\text{bad}} = \frac{N_{\text{slow}} + N_{\text{error}}}{N_{\text{total}}}$$

Скорость сжигания бюджета (Burn Rate):
$$\text{Burn Rate} = \frac{P_{\text{bad}}}{\text{Error Budget}} = \frac{P_{\text{bad}}}{0.01}$$

*   **Burn Rate = 1:** бюджет сжигается равномерно за 28 дней. Уровень тревоги: информирование.
*   **Burn Rate = 14.4 (1-часовое окно):** исчерпание $2\%$ всего бюджета за 1 час. Критический алерт (Sev1 / PagerDuty), требующий немедленного вмешательства инженера.
*   **Burn Rate = 6.0 (6-часовое окно):** исчерпание $5\%$ бюджета за 6 часов. Алерт средней важности (Sev2) в рабочий канал команды.

---

## Практические сценарии и конфигурация

### Сценарий 1: Установка Baseline и конфигурация Performance Budget в Lighthouse CI

**Цель:** детерминированно измерить текущие характеристики стабильного релиза, зафиксировать их как эталон (Baseline) и настроить пороговые проверки.

#### Шаг 1: Подготовка конфигурации `.lighthouserc.js`

Создайте файл конфигурации в корне фронтенд-проекта:

```javascript
// .lighthouserc.js
module.exports = {
  ci: {
    collect: {
      numberOfRuns: 5, // Серия из 5 прогонов для расчета медианы
      settings: {
        chromeFlags: '--no-sandbox --headless=new --disable-gpu --disable-dev-shm-usage',
        emulatedFormFactor: 'mobile',
        throttlingMethod: 'simulate',
        throttling: {
          rttMs: 150,
          throughputKbps: 1638.4, // 1.6 Mbps (Slow 4G)
          cpuSlowdownMultiplier: 4,
        },
      },
    },
    assert: {
      assertions: {
        // Абсолютные пороги Core Web Vitals
        'largest-contentful-paint': ['error', {maxNumericValue: 2500}],
        'cumulative-layout-shift': ['error', {maxNumericValue: 0.1}],
        'total-blocking-time': ['error', {maxNumericValue: 200}],
        // Пороги веса ресурсов (в байтах)
        'resource-summary:script:size': ['error', {maxNumericValue: 350000}],
        'resource-summary:stylesheet:size': ['error', {maxNumericValue: 70000}],
        'resource-summary:font:size': ['error', {maxNumericValue: 120000}],
        'resource-summary:document:size': ['error', {maxNumericValue: 30000}],
      },
    },
    upload: {
      target: 'filesystem',
      outputDir: './.lighthouseci-reports',
    },
  },
};
```

#### Шаг 2: Выполнение сбора и валидации

```bash
# Установка Lighthouse CI CLI локально или в контейнере
npm install -g @lhci/cli

# Сбор данных с прогревом и расчетом медианы
lhci collect --url=http://127.0.0.1:8080/
# → Started a web server on port ...
# → Running Lighthouse 5 time(s) on http://127.0.0.1:8080/
# → Run 1...done.
# → Run 2...done.
# → Run 3...done.
# → Run 4...done.
# → Run 5...done.
# → Done running Lighthouse!

# Проверка выполнения порогов бюджета
lhci assert
# → Checking assertions against 1 URL(s)...
# →   largest-contentful-paint value 1850ms <= 2500ms (PASSED)
# →   total-blocking-time value 110ms <= 200ms (PASSED)
# →   cumulative-layout-shift value 0.02 <= 0.1 (PASSED)
# → All assertions passed!
```

---

### Сценарий 2: Автоматизированный Quality Gate в CI/CD (GitLab CI / Docker runner)

**Цель:** предотвратить слияние кода, приводящего к деградации производительности фронтенда, на собственном self-hosted раннере.

#### Конфигурация `.gitlab-ci.yml`:

```yaml
stages:
  - test
  - performance

performance_gate:
  stage: performance
  image: node:22-bookworm-slim
  tags:
    - dedicated-baremetal # Выделенный раннер без CPU steal
  variables:
    CHROME_BIN: "/usr/bin/chromium"
  before_script:
    - apt-get update && apt-get install -y --no-install-recommends
        chromium
        fonts-liberation
        fonts-noto-color-emoji
        jq
        bc
        procps
    - rm -rf /var/lib/apt/lists/*
    - npm install -g @lhci/cli
  script:
    # 1. Запуск тестового сервера приложения в фоне
    - npm run preview -- --port 8080 &
    - sleep 5
    # 2. Сбор метрик текущей ветки
    - lhci collect --url=http://127.0.0.1:8080/ --numberOfRuns=3
    # 3. Проверка жестких порогов Quality Gate
    - lhci assert
    # 4. Проверка регрессии относительно Baseline текущего стабильного релиза
    - |
      CURR_LCP=$(jq '.[0].summary.lcp' .lighthouseci/manifest.json)
      BASE_LCP=$(jq '.lcp' infra/performance/baseline.json)
      echo "Current LCP: ${CURR_LCP}ms, Baseline LCP: ${BASE_LCP}ms"
      MAX_ALLOWED=$(echo "$BASE_LCP * 1.15" | bc -l)
      if (( $(echo "$CURR_LCP > $MAX_ALLOWED" | bc -l) )); then
        echo "ERROR: Performance regression detected! LCP increased by >15%."
        exit 1
      fi
  artifacts:
    when: always
    paths:
      - .lighthouseci/
    expire_in: 14 days
```

---

### Сценарий 3: Аппаратная и пакетная эмуляция сети через Linux tc netem

**Цель:** провести стресс-тестирование загрузки веб-страницы на уровне сетевого стека ядра Linux с эмуляцией потерь пакетов и джиттера без использования коммерческих SaaS.

#### Шаг 1: Активация дисциплины очереди netem на тестовом интерфейсе

```bash
# Проверка наличия модуля ядра
lsmod | grep sch_netem || sudo modprobe sch_netem

# Эмуляция 4G: задержка 80мс со случайным отклонением 15мс (нормальное распределение) и потерями 1%
sudo tc qdisc add dev eth0 root netem delay 80ms 15ms distribution normal loss 1.0%

# Проверка примененной конфигурации
tc -s qdisc show dev eth0
# → qdisc netem 8001: root refcnt 2 limit 1000 delay 80ms  15ms loss 1%
# →  Sent 104230 bytes 120 pkt (dropped 1, overlimits 0 requeues 0)
```

#### Шаг 2: Запуск синтетического теста страницы через headless Chrome

```bash
# Запуск теста с замером через curl в условиях деградировавшей сети
curl -o /dev/null -s -w "\
  DNS: %{time_namelookup}s\n\
  TCP: %{time_connect}s\n\
  TLS: %{time_appconnect}s\n\
  TTFB: %{time_starttransfer}s\n\
  Total: %{time_total}s\n" https://test.internal.infra/
# → DNS: 0.082s
# → TCP: 0.245s
# → TLS: 0.412s
# → TTFB: 0.589s
# → Total: 0.812s
```

#### Шаг 3: Гарантированная очистка сетевых правил

```bash
# Удаление qdisc netem и возврат интерфейса в штатный режим
sudo tc qdisc del dev eth0 root
tc qdisc show dev eth0
# → qdisc fq_codel 0: root refcnt 2 limit 10240p flows 1024 quantum 1514
```

---

### Сценарий 4: Пост-деплой верификация сетевого стека и кэширования через curl

**Цель:** автоматизировать проверку корректности работы прокси (Nginx/Angie) сразу после выкатки новой версии в продакшен.

```bash
#!/usr/bin/env bash
set -euo pipefail

TARGET_URL="https://example.com"
echo "=== 1. Проверка таймингов сетевого рукопожатия и TTFB ==="
curl -o /dev/null -s -w "\
  HTTP Code:     %{http_code}\n\
  DNS Lookup:    %{time_namelookup}s\n\
  TCP Connect:   %{time_connect}s\n\
  TLS Handshake: %{time_appconnect}s\n\
  Pre-transfer:  %{time_pretransfer}s\n\
  TTFB:          %{time_starttransfer}s\n\
  Total Time:    %{time_total}s\n\
  Size Download: %{size_download} bytes\n" "${TARGET_URL}/"

echo -e "\n=== 2. Проверка заголовков кэширования и сжатия ==="
curl -sI -H "Accept-Encoding: gzip, deflate, br, zstd" "${TARGET_URL}/assets/app.js" | \
  grep -iE "HTTP/|cache-control|content-encoding|etag|x-cache|server-timing"
# → HTTP/2 200
# → content-encoding: br
# → cache-control: public, max-age=31536000, immutable
# → etag: "66fc1234-a4b2"
# → x-cache: HIT
# → server-timing: app;dur=12.4, db;dur=3.1

echo -e "\n=== 3. Проверка поддержки HTTP/3 (QUIC) ==="
curl --http3-only -sI "${TARGET_URL}/" 2>&1 | head -n 3
# → HTTP/3 200
# → alt-svc: h3=":443"; ma=86400
```

---

### Сценарий 5: Тестирование SPOF и отказа сторонних зависимостей (Fault Injection)

**Цель:** проверить, не зависает ли рендеринг страницы при полной недоступности внешнего домена CDN со шрифтами или метриками.

#### Шаг 1: Скрипт проверки через Puppeteer / CDP

```javascript
// spof_test.js
const puppeteer = require('puppeteer');

(async () => {
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage();
  const client = await page.target().createCDPSession();

  // Активация домена Network в CDP
  await client.send('Network.enable');

  // Блокируем домен внешнего вендора (SPOF-кандидат)
  await client.send('Network.setBlockedURLs', {
    urls: ['*fonts.googleapis.com*', '*static.external-cdn.com*'],
  });

  const startTime = Date.now();
  await page.goto('http://127.0.0.1:8080/', {
    waitUntil: 'networkidle2',
    timeout: 10000,
  });
  const loadDuration = Date.now() - startTime;

  // Извлекаем LCP через PerformanceObserver
  const lcp = await page.evaluate(() => {
    return new Promise((resolve) => {
      new PerformanceObserver((entryList) => {
        const entries = entryList.getEntries();
        const lastEntry = entries[entries.length - 1];
        resolve(lastEntry.startTime);
      }).observe({type: 'largest-contentful-paint', buffered: true});
      setTimeout(() => resolve(null), 5000);
    });
  });

  console.log(`[SPOF Test] Load Time: ${loadDuration}ms, LCP: ${lcp}ms`);
  await browser.close();

  if (loadDuration > 5000 || !lcp) {
    console.error('CRITICAL: Page execution blocked by third-party SPOF dependency!');
    process.exit(1);
  }
  console.log('SUCCESS: Page remains resilient despite blocked external dependencies.');
})();
```

#### Запуск теста:

```bash
node spof_test.js
# → [SPOF Test] Load Time: 1240ms, LCP: 850.4ms
# → SUCCESS: Page remains resilient despite blocked external dependencies.
```

---

### Сценарий 6: Развертывание self-hosted сервера Lighthouse CI (LHCI Server)

**Цель:** организовать централизованное хранилище отчетов и автоматическое вычисление диффов между коммитами на собственной инфраструктуре без использования внешних облачных хранилищ.

#### Шаг 1: `docker-compose.yml` для LHCI Server на PostgreSQL

```yaml
version: '3.8'

services:
  lhci-db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: lhci
      POSTGRES_USER: lhci
      POSTGRES_PASSWORD: SecretLhciPassword123
    volumes:
      - lhci_pgdata:/var/lib/postgresql/data
    restart: unless-stopped

  lhci-server:
    image: patrickhulce/lhci-server:0.14.0
    ports:
      - "127.0.0.1:9001:9001"
    environment:
      LHCI_STORAGE__SQL_DIALECT: postgres
      LHCI_STORAGE__SQL_CONNECTION_URL: postgresql://lhci:SecretLhciPassword123@lhci-db:5432/lhci
    depends_on:
      - lhci-db
    restart: unless-stopped

volumes:
  lhci_pgdata:
```

#### Шаг 2: Отправка отчетов из CI в собственный сервер

```bash
# В пайплайне после прогона lhci collect
lhci upload \
  --target=lhci \
  --serverBaseUrl=http://lhci.internal.infra:9001/ \
  --token="lhci-project-build-token"
# → Uploading to http://lhci.internal.infra:9001/...
# → Saved LHR to storage
# → Performance: 94, Accessibility: 100, Best Practices: 96, SEO: 100
# → View documentation and diffs at: http://lhci.internal.infra:9001/app/projects/...
```

---

### Сценарий 7: Настройка Prometheus SLI/SLO и алертинга по Burn Rate

**Цель:** оперативно обнаруживать деградацию веб-производительности в продакшене до исчерпания месячного Error Budget.

#### Конфигурация Prometheus Recording & Alerting Rules (`web_perf_slo.yml`):

```yaml
groups:
  - name: WebPerformanceSLO
    rules:
      # 1. Доля быстрых запросов (LCP < 2.5s) за 1 час и 6 часов
      - record: job:frontend_lcp_good_ratio:1h
        expr: |
          sum(rate(frontend_rum_lcp_seconds_bucket{le="2.5"}[1h]))
          /
          sum(rate(frontend_rum_lcp_seconds_count[1h]))

      - record: job:frontend_lcp_good_ratio:6h
        expr: |
          sum(rate(frontend_rum_lcp_seconds_bucket{le="2.5"}[6h]))
          /
          sum(rate(frontend_rum_lcp_seconds_count[6h]))

      # 2. Вычисление Burn Rate при SLO = 99% (Error Budget = 0.01)
      - record: job:frontend_lcp_burn_rate:1h
        expr: (1 - job:frontend_lcp_good_ratio:1h) / 0.01

      - record: job:frontend_lcp_burn_rate:6h
        expr: (1 - job:frontend_lcp_good_ratio:6h) / 0.01

      # 3. Алерты Multi-Window Multi-Burn-Rate
      - alert: FrontendLCPCriticalBurnRate
        expr: |
          job:frontend_lcp_burn_rate:1h > 14.4
          and
          job:frontend_lcp_burn_rate:6h > 6.0
        for: 2m
        labels:
          severity: critical
          team: frontend-sre
        annotations:
          summary: "Критическое выжигание бюджета ошибок LCP (Burn Rate > 14.4)"
          description: "При текущей задержке 2% месячного бюджета LCP сгорит за 1 час. Текущий 1h Burn Rate: {{ $value }}."

      - alert: FrontendLCPWarningBurnRate
        expr: job:frontend_lcp_burn_rate:6h > 6.0
        for: 15m
        labels:
          severity: warning
          team: frontend-sre
        annotations:
          summary: "Повышенное выжигание бюджета ошибок LCP (Burn Rate > 6.0)"
          description: "5% месячного бюджета LCP сгорает за 6 часов. Требуется анализ логов бэкенда и CDN."
```

---

### Сценарий 8: Нагрузочное тестирование HTTP/2 и HTTP/3 с устранением Coordinated Omission

**Цель:** оценить поведение обратного прокси под нагрузкой по протоколам HTTP/2 и HTTP/3 без искажения хвостовых перцентилей задержки.

#### Шаг 1: Запуск h2load (HTTP/2 мультиплексирование)

```bash
# 100 000 запросов, 100 одновременных TCP-клиентов, до 10 мультиплексированных стримов на соединение
h2load -n 100000 -c 100 -m 10 --warm-up-time 5 https://example.com/
# → starting benchmark...
# → progress: 50% of requests done
# → finished in 1.42s, 70422.53 req/s, 95.84MB/s
# → requests: 100000 total, 100000 started, 100000 done, 100000 succeeded, 0 failed, 0 errored, 0 timeout
# → status codes: 100000 2xx, 0 3xx, 0 4xx, 0 5xx
# → traffic: 136.21MB (142823450) total, 1.25MB (1310000) headers, 134.12MB (140634210) data
# → time for request:
# →   min: 520us, max: 28.4ms, mean: 1.34ms, sd: 850us
# → time to first byte:
# →   min: 1.12ms, max: 29.1ms, mean: 1.95ms, sd: 910us
```

#### Шаг 2: Запуск wrk2 с открытым циклом (Constant Arrival Rate)

В отличие от стандартного `wrk`, утилита `wrk2` исключает ошибку Coordinated Omission, генерируя запросы со строго заданной частотой:

```bash
# Тест с фиксированной частотой 5000 RPS в течение 60 секунд на 4 потока ядра
wrk -t4 -c200 -d60s -R5000 --latency https://example.com/api/v1/health
# → Running 1m test @ https://example.com/api/v1/health
# →   4 threads and 200 connections
# →   Latency Distribution (HdrHistogram - Corrected for Coordinated Omission)
# →      50.000%    1.42ms
# →      75.000%    2.15ms
# →      90.000%    3.89ms
# →      99.000%    8.12ms
# →      99.900%   18.45ms
# →      99.990%   45.20ms
# →   300000 requests in 1.00m, 75.32MB read
# → Requests/sec:   5000.08
```

---

## Операции и команды

### Прецизионная диагностика сетевых фаз через curl

Форматированный вывод временных меток каждого этапа соединения:

```bash
curl -o /dev/null -s -w "\
  DNS Resolution:   %{time_namelookup}s\n\
  TCP Connect:      %{time_connect}s\n\
  TLS Handshake:    %{time_appconnect}s\n\
  Pre-transfer:     %{time_pretransfer}s\n\
  Start Transfer:   %{time_starttransfer}s (TTFB)\n\
  Total Duration:   %{time_total}s\n\
  HTTP Status:      %{http_code}\n\
  Remote IP:        %{remote_ip}:%{remote_port}\n" https://example.com/
# → DNS Resolution:   0.015s
# → TCP Connect:      0.042s
# → TLS Handshake:    0.078s
# → Pre-transfer:     0.079s
# → Start Transfer:   0.198s (TTFB)
# → Total Duration:   0.245s
# → HTTP Status:      200
# → Remote IP:        192.0.2.1:443
```

Интерпретация отклонений:
*   `time_namelookup > 0.05s`: медленный DNS-резолвинг; проверить `/etc/resolv.conf`, внедрить локальный кэширующий DNS (systemd-resolved, dnsmasq).
*   `time_connect - time_namelookup > 0.05s`: сетевой пинг (RTT) высок; проверить маршрутизацию до датацентра.
*   `time_appconnect - time_connect > 0.10s`: задержка в TLS-рукопожатии; проверить размер цепочки сертификатов, включить OCSP Stapling и Session Resumption.
*   `time_starttransfer - time_pretransfer > 0.30s`: бэкенд долго формирует ответ; оптимизировать серверный код, запросы к БД или настроить `proxy_cache`.

### Управление сетевым шейпингом Linux tc netem

```bash
# 1. Добавить задержку 100 мс и джиттер 20 мс
sudo tc qdisc add dev eth0 root netem delay 100ms 20ms

# 2. Добавить 2% потерь пакетов с корреляцией 25% (пакетный берст)
sudo tc qdisc change dev eth0 root netem delay 100ms 20ms loss 2% 25%

# 3. Добавить повреждение пакетов (bit corruption 0.1%)
sudo tc qdisc change dev eth0 root netem delay 100ms loss 2% corrupt 0.1%

# 4. Просмотр текущей статистики сброшенных и задержанных пакетов
tc -s qdisc show dev eth0
# → qdisc netem 8001: root refcnt 2 limit 1000 delay 100ms loss 2% corrupt 0.1%
# →  Sent 541230 bytes 450 pkt (dropped 9, overlimits 0 requeues 0)

# 5. Полный сброс правил шейпинга
sudo tc qdisc del dev eth0 root
```

### Автоматизация сборки и проверок через Lighthouse CI CLI

```bash
# Запуск сбора данных с указанием пути к Chromium
lhci collect \
  --chromePath="/usr/bin/chromium" \
  --url=http://staging.internal.infra/ \
  --numberOfRuns=3

# Локальная проверка по утверждениям бюджета
lhci assert --config=.lighthouserc.js

# Запуск встроенного веб-интерфейса для визуального просмотра результатов прогона
lhci open
# → Opening HTML report in browser...
```

### Запуск Headless Chromium и взаимодействие через CDP

```bash
# Запуск Chromium в режиме headless с прослушиванием порта отладки на localhost
chromium \
  --headless=new \
  --remote-debugging-port=9222 \
  --no-sandbox \
  --disable-gpu \
  --disable-dev-shm-usage \
  --window-size=1920,1080 \
  about:blank &
# → DevTools listening on ws://127.0.0.1:9222/devtools/browser/abc-123

# Проверка доступности targets через HTTP API
curl -s http://127.0.0.1:9222/json/version | jq .
# → {
# →   "Browser": "Chrome/124.0.6367.60",
# →   "Protocol-Version": "1.3",
# →   "User-Agent": "Mozilla/5.0 ...",
# →   "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/abc-123"
# → }
```

---

## Диагностика и устранение неполадок

### Методология локализации регрессий производительности

При срабатывании алертов или падении Quality Gate в CI/CD локализация выполняется по цепочке:

```text
[ Падение Quality Gate / Alert ]
               │
               ▼
   1. Валидация окружения CI
      (Нет ли CPU Steal? Достаточно ли RAM/shm? Изолирован ли раннер?)
               │
               ▼
   2. Сетевая изоляция vs Код
      (Вырос TTFB или вырос вес бандла? Замер через curl -w)
        ┌──────┴──────┐
        ▼             ▼
   [TTFB вырос]    [TTFB в норме, упал LCP/INP]
        │             │
        │             ▼
        │        3. Анализ Waterfall и Main Thread
        │           (Проверить размер JS/CSS, сторонние шрифты, блокирующий рендеринг)
        ▼
   4. Трассировка бэкенда
      (Проверить access-лог: $upstream_response_time, $request_time, медленные SQL-запросы)
```

### Типичные проблемы, диагностика и решения

| Симптом | Вероятная причина | Метод диагностики | Решение |
| :--- | :--- | :--- | :--- |
| **Flaky-тесты в CI/CD (разброс > 20% между прогонами)** | Общий виртуальный раннер (высокий CPU Steal), фоновая активность соседей | Команда `top` / `vmstat 1` на хосте; проверка поля `%st` (steal time) | Перенести раннеры синтетики на выделенные (dedicated) bare-metal ноды или KVM с pinned CPU. Увеличить `numberOfRuns` до 5 и брать медиану. |
| **Падение Chromium в Docker с ошибкой `Target closed` / `SIGBUS`** | Нехватка разделяемой памяти `/dev/shm` (по умолчанию в Docker 64 МБ) | Проверить логи: `Crashpad: Out of memory in /dev/shm` | Запускать Docker с флагом `--shm-size=2gb` или передавать аргумент Chromium `--disable-dev-shm-usage`. |
| **Смещение верстки (высокий CLS) только в CI-контейнере** | Отсутствие системных шрифтов в минимальном Docker-образе (fallback на стандартные) | Сравнить скриншоты Headless и GUI; проверить `page.screenshot()` | Установить пакеты шрифтов в контейнер: `apt-get install -y fonts-liberation fonts-noto`. |
| **Ошибка 429 Too Many Requests / Блокировка WAF при тестировании** | Модуль `limit_req` на Nginx/Angie или WAF блокирует частые синтетические запросы | Изучить `access.log` и `error.log` обратного прокси; код 429 или 403 | Настроить обход лимитера по выделенному заголовку или IP-адресу доверенного раннера через директиву `geo` / `map`. |
| **После сбоя CI-пайплайна сеть раннера остается замедленной** | Скрипт упал до выполнения команды очистки `tc qdisc del` | Команда `tc qdisc show dev eth0` показывает наличие активного `netem` | Обернуть вызовы в `trap 'sudo tc qdisc del dev eth0 root 2>/dev/null || true' EXIT` в bash-скриптах CI. |
| **Синтетика показывает Cache HIT, а реальные пользователи — медленный TTFB** | Синтетический тест запрашивает один URL, маскируя отсутствие кэша для разных User-Agent/кук | Анализ `$upstream_cache_status` в access-логах для реальных пользователей | Проверить `proxy_cache_key`: исключить уникальные Cookie и заголовки `User-Agent`, если они не влияют на контент. |
| **Занижение хвостовых задержек (p99) при нагрузочных тестах** | Ошибка Coordinated Omission в утилите генерации трафика (wrk, ab) | Сравнить результаты `wrk` и `wrk2 -R <rps>` | Использовать генераторы с моделью открытого цикла (Open Loop): `wrk2`, `vegeta`, `k6` (arrival-rate). |
| **RUM-метрики не поступают от клиентов на сервер сбора** | Блокировка запросов расширениями (AdBlock, uBlock) или ошибки CORS в Beacon API | Проверить Network tab в DevTools браузера; проверить статус `/analytics` | Использовать same-origin эндпоинт обратного прокси (например, `/api/v1/telemetry`) вместо отдельного домена. |
| **Lighthouse сообщает: `Unable to detect LCP element`** | LCP-элемент вставляется через клиентский JavaScript с задержкой более 5 секунд | Открыть отчет Lighthouse; раздел "View Trace" | Добавить SSR/SSG для критического контента первого экрана или использовать `fetchpriority="high"`. |

---

## Рекомендации и лучшие практики

### Чеклист SRE и системного администратора

#### 1. Подготовка инфраструктуры тестирования (Pre-test)
- [ ] Раннеры синтетического тестирования размещены на изолированных хостах с нулевым CPU Steal.
- [ ] В Docker-контейнерах раннеров размер `/dev/shm` увеличен минимум до 2 ГБ.
- [ ] Установлен пакет системных шрифтов (`fonts-liberation`, `fonts-noto`) для устранения артефактов рендеринга текста.
- [ ] На обратном прокси (Nginx/Angie) настроен доверенный белый список для IP-адресов CI-раннеров, исключающий срабатывание `limit_req` и WAF.
- [ ] Зафиксирован Baseline стабильного релиза (серия из 5–9 прогонов с медианой).

#### 2. Проведение тестов и контроль регрессий (In-pipeline)
- [ ] В пайплайне настроена серия минимум из 3 прогонов с выбором медианного результата.
- [ ] Установлен Performance Budget на критические метрики: LCP ≤ 2.5 с, CLS ≤ 0.1, TBT ≤ 200 мс.
- [ ] Настроен контроль веса критических ресурсов (JS-бандлы ≤ 350 КБ, CSS ≤ 70 КБ).
- [ ] Реализован автоматический откат или блокировка слияния ветки при превышении порога Baseline более чем на 10–15%.

#### 3. Мониторинг продакшена после деплоя (Post-deploy)
- [ ] Выполнен автоматический дымовой тест сетевых таймингов и заголовков сжатия через `curl`.
- [ ] Настроены Prometheus Recording Rules для расчета доли успешных запросов по Web Vitals за окна 1 час и 6 часов.
- [ ] Активированы Alertmanager-правила Multi-Window Multi-Burn-Rate для предотвращения исчерпания месячного бюджета ошибок.
- [ ] Настроена панель в Grafana для сопоставления серверных таймингов (`$upstream_response_time`, `$request_time`) с клиентскими данными RUM.

### Безопасность и изоляция при синтетическом тестировании

1.  **Авторизованный обход Rate Limiter:**
    Для предотвращения блокировок синтетических тестов защитными механизмами сервера используйте секретный заголовок, валидируемый веб-сервером:
    ```nginx
    # Пример конфигурации Nginx/Angie
    map $http_x_synthetic_probe $is_trusted_probe {
        default 0;
        "SecretProbeTokenValue2026" 1;
    }

    server {
        location / {
            # Применение лимита только если запрос не от синтетического зонда
            limit_req zone=one burst=20 nodelay if=$is_not_trusted;
            proxy_pass http://backend;
        }
    }
    ```
2.  **Изоляция тестового трафика от бизнес-аналитики:**
    Синтетические браузеры обязаны передавать флаг в заголовке `User-Agent` (например, `CustomSyntheticBot/1.0`) или куку `is_synthetic=1`. Это позволяет исключить технические вызовы из маркетинговых счетчиков и финансовых отчетов.
3.  **Защита от отказа в обслуживании (DoS):**
    Нагрузочное тестирование (`h2load`, `wrk2`) разрешено проводить **исключительно** на изолированных staging-окружениях или в специально отведенные технологические окна с предварительным уведомлением дежурной смены SRE.

### Сравнение диагностических инструментов

| Инструмент | Уровень абстракции | Точность сетевого стека | Нагрузка на CPU | Основное назначение |
| :--- | :--- | :--- | :--- | :--- |
| **curl** | Транспортный сокет (L4–L7) | Высокая (точные микросекундные замеры) | Минимальная | Пост-деплой валидация, проверка TLS/TTFB/HTTP3 |
| **Lighthouse CI** | Браузерный движок (Chromium) | Средняя (программный троттлинг) | Высокая (рендеринг страницы) | CI/CD Quality Gates, аудит Core Web Vitals и бандлов |
| **WebPageTest (Private)** | Реальные ОС и устройства | Максимальная (аппаратный шейпинг) | Выделенные ноды | Комплексный глубокий аудит, покадровая раскадровка (Filmstrip) |
| **h2load** | Протокольный генератор (H2/H3)| Высокая (мультиплексирование потоков) | Средняя | Тестирование пропускной способности обратного прокси |
| **wrk2** | Нагрузочный сокет с HdrHistogram | Высокая (Open Loop модель) | Низкая / средняя | Поиск задержек (Tail Latency) без Coordinated Omission |

### Архитектура хранения артефактов и отчетов

*   **Self-hosted LHCI Server:** рекомендуется развертывать в виде внутреннего сервиса на базе Docker с базой данных PostgreSQL. Хранит историю всех сборок, строит графики трендов и обеспечивает авторизованный доступ через токены проектов.
*   **Локальное файловое хранилище / MinIO:** сохранение HTML-отчетов трассировки (Chrome Trace) и HAR-архивов в локальное S3-совместимое объектное хранилище (MinIO) или как артефакты CI-системы (GitLab / Jenkins) со сроком удержания (Retention Policy) 14–30 дней.

---

## Дополнительная информация

### См. также

- **[Web Vitals — ключевые метрики пользовательского опыта](./web_vitals.md)** — детальный разбор LCP, INP, CLS, методология RUM и Prometheus-алертинг.
- **[Chrome DevTools для анализа производительности](./chrome_devtools.md)** — архитектура CDP, удаленная отладка, дампы Tracing и HAR.
- **[WebPageTest — инструмент синтетического тестирования](./webpagetest.md)** — глубокая диагностика, No-Code эксперименты и раскадровка загрузки.
- **[Structured Logging и анализ для веб-производительности](./structured_logging_for_performance.md)** — декомпозиция времени ответа на прокси, тайминги сокетов ядра и экспорт метрик.
- **[Оптимизация производительности: Обзор](./overview.md)** — уровни веб-оптимизации, жизненный цикл соединений и общая методология.
- **[Инструменты для бенчмаркинга веб-серверов](../../webserver_benchmarking.md)** — методология нагрузочного тестирования HTTP-серверов, wrk, wrk2, h2load и настройка sysctl.
- **[tc netem: Эмуляция сетевых проблем](../../../Linux/Networking/Tools/iproute2/tc_netem.md)** — параметры задержек, потерь и джиттера в ядре Linux.
- **[Специфические задачи Frontend CI/CD](../../../CI-CD/Frontend_CI_CD/frontend_pipeline_specifics.md)** — интеграция LHCI, бюджетов размеров бандлов и Quality Gates.
- **[Методология тестирования производительности](../../../Testing/performance_testing_methodology.md)** — концепции нагрузочного тестирования, Coordinated Omission и модели открытого/закрытого цикла.
