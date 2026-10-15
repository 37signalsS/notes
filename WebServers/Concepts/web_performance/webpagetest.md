# WebPageTest — инструмент синтетического тестирования производительности

**Актуально для:** WebPageTest Private Instance 2026.x / wptagent 2026.x / WebPageTest REST API v1

## Определения

**WebPageTest (WPT)** — модульная платформа для синтетического (лабораторного) тестирования веб-производительности в строго контролируемой аппаратной и сетевой среде. Позволяет развертывать изолированные локальные тестовые агенты (Private Instances), осуществлять глубокую покадровую трассировку отрисовки (Filmstrip), строить детальные водопадные диаграммы (Waterfall), эмулировать сетевые условия на уровне ядра ОС и инспектировать поведение браузера на реальном железе или в контейнерах.

**WPT Server** — центральный координационный сервис платформы (веб-интерфейс и REST API). Отвечает за прием заданий на тестирование, диспетчеризацию очередей по локациям и агентам, сбор и парсинг артефактов (HAR, дампы сетевых пакетов pcap, видеозаписи, JSON-результаты) и предоставление аналитического интерфейса.

**WPT Agent (`wptagent`)** — автономный агент исполнения тестов (реализован на Python 3). Опрашивает WPT Server по протоколу HTTP, забирает задание, запускает браузер (Chromium, Firefox) под управлением Chrome DevTools Protocol (CDP) или WebDriver в среде виртуального кадрового буфера (Xvfb), конфигурирует сетевой шейпинг на хосте или в контейнере, захватывает видео и передает результаты обратно на сервер.

**Traffic Shaping (формирование сетевого профиля на уровне пакетов)** — эмуляция пропускной способности, круговой задержки (RTT), джиттера и процента потери пакетов (Packet Loss Rate) средствами ядра ОС (в Linux — через стек `iproute2` и планировщик очередей `tc netem`). В отличие от прикладного троттлинга браузера, пакетный шейпинг воспроизводит реальное поведение протоколов TCP (включая переполнение окна перегрузки и повторную передачу сегментов) и UDP/QUIC (HTTP/3).

**Waterfall (Водопадная диаграмма)** — графическое представление сетевых запросов страницы по шкале времени с микросекундной разбивкой фаз каждого сокета: DNS Lookup, Initial Connection, SSL/TLS Handshake, TTFB (Time to First Byte) и Content Download.

**Filmstrip (Покадровая раскадровка)** — синхронизированная последовательность видеокадров загрузки страницы (со стандартным шагом 100 мс), сопоставленная по времени с сетевыми событиями водопадной диаграммы и метриками рендеринга.

**Speed Index (Индекс скорости)** — интегральная синтетическая метрика WebPageTest, выражающая среднее время визуального заполнения видимой области экрана (Above-the-Fold). Рассчитывается как площадь над кривой визуальной готовности (Visual Progress) от 0% до 100%.

**SPOF (Single Point of Failure / Единая точка отказа)** — внешний или внутренний критический ресурс (шрифт, блокирующий JavaScript-бандл, CDN-ресурс), задержка или недоступность которого полностью блокирует отрисовку страницы или выполнение основного функционала.

**No-Code Experiments** — механизм WPT для динамической модификации страницы «на лету» в процессе выполнения теста (блокировка доменов, подмена ресурсов, внедрение заголовков, инжекция атрибутов `fetchpriority` или `defer`) без необходимости внесения правок в код бэкенда или фронтенда.

**WPT Scripting** — декларативный скриптовый язык WebPageTest, предназначенный для автоматизации сложных многошаговых сценариев (Multi-step Transactions): прохождение сквозной авторизации, заполнение форм, добавление товаров в корзину, манипуляция куками, инжекция произвольных HTTP-заголовков и переопределение DNS-записей.

**Performance Budget (Бюджет производительности)** — набор формализованных ограничений на метрики скорости (TTFB, Speed Index, LCP) и размеры передаваемых ресурсов (объем JavaScript, CSS, шрифтов), нарушение которых автоматически приводит к завершению шага CI/CD с ошибкой.

---

## Основные концепции и архитектура

### Архитектура Private Instance (Server и Agent)

В инфраструктуре DevOps и системного администрирования WebPageTest развертывается изолированно (On-Premises / Bare-Metal) без обращения к внешним публичным сервисам. Это гарантирует безопасность корпоративных данных, доступ к закрытым контурам (Staging, Development) и детерминированную воспроизводимость замеров.

```
                      +------------------------------------------+
                      |         WPT Server (Nginx / PHP)         |
                      |  - REST API (/runtest.php, /jsonResult)  |
                      |  - Очереди задач (Work Queues per Loc)   |
                      |  - Хранилище отчетов, HAR, pcap, video   |
                      +---------------------+--------------------+
                                            ▲
                     HTTP GET /work/getwork | HTTP POST /work/workdone
                                            ▼
                      +------------------------------------------+
                      |           WPT Agent (wptagent)           |
                      |  - Python 3 оркестратор                  |
                      |  - Диспетчер браузеров (CDP / WebDriver) |
                      |  - Виртуальный дисплей Xvfb              |
                      +--------+---------------------+-----------+
                               |                     |
              Linux tc netem / |                     | CDP (Port 9222) /
              iproute2         |                     | Video Capture
                               ▼                     ▼
             +-----------------------+     +--------------------+
             |  Сетевой стек хоста   |     |  Chromium / Firefox|
             | (Эмуляция RTT/Loss/BW)|     |  (Headless / Xvfb) |
             +-----------+-----------+     +---------+----------+
                         |                           |
                         +-------------+-------------+
                                       |
                                       ▼
                         +---------------------------+
                         |   Тестируемый веб-сервер  |
                         |     (Nginx / Backend)     |
                         +---------------------------+
```

Жизненный цикл выполнения теста в архитектуре Private Instance:

1. **Инициализация:** Клиент (CI/CD runner, скрипт мониторинга или инженер) отправляет HTTP POST запрос на эндпоинт WPT Server `/runtest.php` с параметрами тестирования (URL, локация, профиль сети, число прогонов).
2. **Постановка в очередь:** Сервер сохраняет конфигурацию теста в локальной очереди файловой системы для указанной локации (`location`).
3. **Опрос агентом:** Фоновый процесс `wptagent`, привязанный к данной локации, непрерывно опрашивает сервер через `GET /work/getwork.php`.
4. **Подготовка окружения:** Получив задачу, `wptagent`:
   - Настраивает виртуальный экран Xvfb с заданным экранным разрешением.
   - Конфигурирует параметры сетевого интерфейса через системную утилиту `tc` (Traffic Control).
   - Очищает кэш браузера, профиль пользователя и DNS-кэш операционной системы.
5. **Исполнение теста:** Агент запускает процесс браузера с флагом удаленной отладки по протоколу CDP, начинает запись видеопотока через `ffmpeg`, запускает перехват сырых сетевых пакетов через `tcpdump` (если активирован флаг `tcpdump=1`) и переходит по целевому URL.
6. **Сбор артефактов:** После стабилизации сетевой активности и выполнения условий окончания теста агент останавливает захват видео, рассчитывает покадровую готовность (Speed Index), собирает DevTools Trace, формирует файл HAR и упаковывает результаты в zip-архив.
7. **Отправка результатов:** Агент передает собранные данные обратно на сервер через `POST /work/workdone.php` и переходит в режим ожидания следующей задачи.

---

### Traffic Shaping на уровне ядра Linux (Packet-level vs Browser-level)

Принципиальное отличие WebPageTest от стандартного Chrome DevTools или Lighthouse заключается в физическом способе ограничения сети.

| Характеристика | Прикладной троттлинг (DevTools / Lighthouse) | Пакетный шейпинг WPT (`tc netem` + `ifb`) |
| :--- | :--- | :--- |
| **Уровень воздействия** | Прикладной уровень (L7, Chromium Network Stack) | Сетевой уровень ядра ОС (L3/L4, Linux qdisc) |
| **Сетевые протоколы** | Ограничивает только HTTP/1.1 и HTTP/2 внутри браузера | Формирует весь трафик: TCP, UDP/QUIC (HTTP/3), DNS, ICMP |
| **Эмуляция задержки (RTT)** | Задержка добавляется искусственно перед отдачей в JS | Задержка реализуется в очереди сетевого интерфейса ядра |
| **Потери пакетов (Packet Loss)** | Не поддерживаются (только задержка и ограничение полосы) | Физический сброс IP-пакетов с воспроизведением TCP Retransmit |
| **Сетевой джиттер (Jitter)** | Не моделируется | Точное статистическое распределение (Normal, Pareto) |
| **TCP Congestion Control** | Искажается (стек браузера не видит реального RTT) | Полноценная работа алгоритмов CUBIC, BBRv2/v3 в ядре |

Для реализации двунаправленного шейпинга (исходящий и входящий трафик) в Linux агент WPT использует связку корневой дисциплины очередей `netem` и виртуального промежуточного интерфейса IFB (Intermediate Functional Block):

- **Исходящий трафик (Egress):** Ограничивается непосредственно на физическом или виртуальном интерфейсе контейнера (`eth0`) через дисциплину очереди `tc qdisc add dev eth0 root netem delay ... rate ...`.
- **Входящий трафик (Ingress):** Перенаправляется с помощью фильтра `tc filter` на виртуальный интерфейс `ifb0`, к которому применяется зеркальная дисциплина очереди для входящего потока.
- Подробные параметры дисциплины `netem` документированы в руководстве [tc netem: эмуляция сетевых проблем](../../../Linux/Networking/Tools/iproute2/tc_netem.md), а особенности работы в изолированных контейнерах — в статье [шейпинг трафика в Docker](../../../Docker/Docker_network/docker_network_traffic_shaping.md).

---

### Ключевые метрики и анализ производительности

WebPageTest собирает исчерпывающий спектр метрик, разбивая жизненный цикл страницы на фундаментальные уровни:

```
[ Навигация ]
     │
     ├── 1. Сетевой транспорт (L4/L7)
     │     ├─ DNS Lookup (время резолва имени)
     │     ├─ Initial Connection (TCP SYN / SYN-ACK)
     │     ├─ SSL/TLS Handshake (согласование ключей и сертификатов)
     │     └─ Time to First Byte (TTFB, генерация ответа бэкендом)
     │
     ├── 2. Визуальный рендеринг (Filmstrip)
     │     ├─ Start Render (первое изменение пикселей на экране)
     │     ├─ First Contentful Paint (FCP, появление первого DOM-элемента)
     │     ├─ Speed Index (интеграл визуального заполнения области видимости)
     │     └─ Visually Complete (момент 100% готовности визуала Above-the-Fold)
     │
     └── 3. Интерактивность и стабильность (Core Web Vitals)
           ├─ Largest Contentful Paint (LCP, фазы: TTFB, Load Delay, Load, Render Delay)
           ├─ Total Blocking Time (TBT, сумма блокировок Main Thread > 50 мс)
           └─ Cumulative Layout Shift (CLS, сдвиги макета в процессе догрузки)
```

- **Расчет Speed Index:** Агент анализирует видеокадры, вычисляет визуальное отличие каждого кадра от финального состояния (через коэффициент гистограммы цвета) и интегрирует процент незавершенности по времени:
  $$\text{Speed Index} = \int_{0}^{T_{\text{end}}} (1 - \text{VisualProgress}(t)) \, dt$$
  Низкий Speed Index указывает на то, что контент появился на экране практически мгновенно, даже если фоновые скрипты продолжали загружаться.
- Взаимосвязь лабораторных метрик с реальным пользовательским опытом (RUM) детально описана в руководстве [метрики Core Web Vitals](./web_vitals.md).

---

### Методология многопрогонного тестирования (Multi-Run) и выбор медианы

Одиночный тест производительности в синтетической среде категорически не является репрезентативным из-за влияния внешних факторов:
- Вариативность задержек промежуточных сетевых маршрутизаторов (джиттер).
- Фоновая активность операционной системы хоста (сброс dirty pages, планировщик CPU, garbage collection).
- Специфика первого «холодного» старта процесса браузера.

**Золотой стандарт WPT:**
1. **Количество прогонов:** Минимум 5 прогонов (для повседневных CI/CD тестов) и 9 прогонов (для эталонных замеров и SRE-базовых линий).
2. **Выбор медианного замера:** WebPageTest автоматически ранжирует прогоны по значению первичной метрики (по умолчанию Speed Index или LCP) и выбирает строго **медианный замер** (`median run`). Метрики именно этого прогона берутся для формирования итогового отчета и валидации бюджетов.
3. **Разделение First View и Repeat View:**
   - **First View (Первый визит):** Тестирование с абсолютно чистым профилем браузера (кэш пуст, сокеты закрыты, DNS-кэш сброшен). Моделирует нового пользователя.
   - **Repeat View (Повторный визит):** Повторная загрузка того же URL без сброса браузерного контекста. Позволяет валидировать корректность заголовков кэширования (`Cache-Control`, `ETag`, `stale-while-revalidate`), работу Service Worker и повторное использование TLS-сессий.

---

## Практические сценарии и конфигурация

### Сценарий 1: Развертывание локального Private Instance через Docker Compose

Для создания полностью изолированного стенда тестирования на выделенном Linux-сервере используется связка официальных контейнеров сервера и агента с передачей привилегии `CAP_NET_ADMIN` для сетевого шейпинга.

#### 1. Подготовка конфигурации ядра Linux на хосте

Сетевой агент требует наличия модулей ядра `sch_netem` (эмуляция задержек и потерь) и `ifb` (промежуточный виртуальный интерфейс для входящего шейпинга):

```bash
# Загрузка необходимых модулей ядра
sudo modprobe sch_netem
sudo modprobe ifb numifbs=1

# Проверка загрузки модулей
lsmod | grep -E "sch_netem|ifb"
# → ifb                    24576  0
# → sch_netem              20480  0

# Автозагрузка при старте ОС
echo -e "sch_netem\nifb" | sudo tee /etc/modules-load.d/webpagetest.conf
# → sch_netem
# → ifb
```

#### 2. Конфигурация локаций сервера (`locations.ini`)

Создайте каталог проекта `/opt/webpagetest` и файл конфигурации очередей `/opt/webpagetest/config/locations.ini`:

```ini
[locations]
1=Local_Location
default=Local_Location

[Local_Location]
1=Local_Agent
label="Local On-Premises Testing Cluster"
default=Local_Agent

[Local_Agent]
browser=Chrome,Firefox
label="Local Dedicated Agent (Bare-Metal)"
; Секретный ключ для аутентификации агента на сервере
key=WptSecretAgentKey2026
```

#### 3. Файл оркестрации `docker-compose.yml`

```yaml
services:
  wpt-server:
    image: webpagetest/server:latest
    container_name: wpt-server
    restart: unless-stopped
    ports:
      - "8080:80"
    volumes:
      - /opt/webpagetest/config/locations.ini:/var/www/html/settings/locations.ini:ro
      - /opt/webpagetest/results:/var/www/html/results
      - /opt/webpagetest/logs:/var/www/html/logs
    environment:
      - TITLE=Private WebPageTest Instance
      - API_KEY=MasterWptApiKey2026

  wpt-agent:
    image: webpagetest/agent:latest
    container_name: wpt-agent
    restart: unless-stopped
    depends_on:
      - wpt-server
    cap_add:
      - NET_ADMIN
    shm_size: 2g
    volumes:
      - /dev/shm:/dev/shm
    environment:
      - SERVER_URL=http://wpt-server/work/
      - LOCATION=Local_Agent
      - KEY=WptSecretAgentKey2026
      - SHAPER=netem
      - EXTRA_ARGS=--xvfb
```

Запуск и проверка статуса инстанса:

```bash
cd /opt/webpagetest
docker compose up -d
# → [✓] Container wpt-server  Started
# → [✓] Container wpt-agent   Started

# Проверка логов подключения агента к серверу
docker logs wpt-agent 2>&1 | grep -i "polling"
# → Polling for work from http://wpt-server/work/ for location Local_Agent
```

---

### Сценарий 2: Конфигурация профилей сетевого шейпинга на Linux-агенте

Стандартные профили связности WPT определяют точные параметры пропускной способности, латентности и потерь. Агент использует значения из таблицы для настройки дисциплины `tc`:

| Профиль связности | Download (Kbps) | Upload (Kbps) | RTT Latency (мс) | Packet Loss (%) | Область применения |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Cable** | 50 000 | 10 000 | 28 | 0 | Оптоволоконные и кабельные сети ПК |
| **DSL** | 1 500 | 384 | 50 | 0 | Медленные широкополосные каналы |
| **4G (Good)** | 9 000 | 9 000 | 170 | 0 | Мобильный стандарт де-факто |
| **3G (Fast)** | 1 600 | 768 | 150 | 0 | Ограниченные мобильные сети |
| **3G (Slow)** | 400 | 400 | 400 | 0.5 | Экстремальные полевые условия |

Пример низкоуровневых команд, которые агент выполняет на сетевом интерфейсе `eth0` при выборе профиля **4G (9 Mbps, 170ms RTT)**:

```bash
# 1. Сброс существующих дисциплин очереди
sudo tc qdisc del dev eth0 root 2>/dev/null || true

# 2. Добавление netem с задержкой 85ms (половина от 170ms RTT на egress) и ограничением полосы 9Mbit
sudo tc qdisc add dev eth0 root handle 1: netem delay 85ms rate 9000kbit

# 3. Валидация примененных правил ядра
tc -s qdisc show dev eth0
# → qdisc netem 1: root refcnt 2 limit 1000 delay 85ms rate 9000Kbit
# → Sent 0 bytes 0 pkt (dropped 0, overlimits 0 requeues 0)
```

---

### Сценарий 3: WPT Scripting для сложных сценариев и SRE-диагностики

Язык сценариев WebPageTest позволяет воспроизводить поведение пользователя, обходить ограничения закрытых контуров и изолировать сетевые сбои.

#### 1. Авторизация и замер внутреннего интерфейса личного кабинета

```text
// Установка базовых параметров сессии
setEventName    Open_LoginPage
navigate        https://auth.internal.example.com/login

// Заполнение формы авторизации
setValue        id=login-username    sre-synthetic-user
setValue        id=login-password    SuperSecretPass2026
setEventName    Submit_Credentials
submitForm      id=auth-form

// Переход на критическую страницу с замером метрик
setEventName    Dashboard_View
navigate        https://app.internal.example.com/dashboard
```

#### 2. Переопределение DNS для предрелизного тестирования (Staging без изменения /etc/hosts)

Команда `setDns` принудительно направляет трафик на тестовый бэкенд, предотвращая утечку запросов на боевой кластер:

```text
// Направляем запросы к API на внутренний адрес тестового балансировщика
setDns          api.example.com    192.168.100.50
setDns          cdn.example.com    192.168.100.51

// Добавление заголовка для обхода rate-limit и CDN-кэша
addHeader       X-Internal-Synthetic-Test: WptRunner2026

navigate        https://api.example.com/checkout
```

#### 3. Тестирование единой точки отказа (SPOF Analysis)

Для оценки надежности архитектуры проверяется время рендеринга страницы при полной блокировке внешних зависимостей:

```text
// Полная блокировка доменов сторонней аналитики и внешних шрифтов
blockDomains    fonts.googleapis.com cdn.optimizely.com analytics.external.net

setEventName    SPOF_Validation
navigate        https://example.com/product/12345
```

---

### Сценарий 4: Интеграция в CI/CD пайплайн (Quality Gates и Performance Budgets)

Автоматизация тестирования в пайплайнах GitLab CI / GitHub Actions блокирует выкатку релиза при деградации производительности.

#### Файл конфигурации бюджета `.wptrules.json`:

```json
{
  "median": {
    "firstView": {
      "SpeedIndex": 2000,
      "TTFB": 400,
      "chromeUserTiming.LargestContentfulPaint": 2500,
      "CumulativeLayoutShift": 0.05,
      "TotalBlockingTime": 200,
      "bytesIn": 1500000
    }
  }
}
```

#### Скрипт валидации качества в CI/CD (`wpt-quality-gate.sh`):

```bash
#!/usr/bin/env bash
set -euo pipefail

WPT_SERVER="http://wpt.internal.corp:8080"
API_KEY="MasterWptApiKey2026"
TARGET_URL="https://staging.example.com"
BUDGET_FILE=".wptrules.json"

echo "Запуск теста WebPageTest для: ${TARGET_URL}..."

# 1. Отправка задания на сервер
RUN_RESP=$(curl -s -X POST "${WPT_SERVER}/runtest.php" \
  -d "url=${TARGET_URL}" \
  -d "k=${API_KEY}" \
  -d "f=json" \
  -d "runs=5" \
  -d "fvonly=1" \
  -d "location=Local_Agent:Chrome.4G" \
  -d "video=1")

STATUS_CODE=$(echo "${RUN_RESP}" | jq -r '.statusCode')
if [ "${STATUS_CODE}" -ne 200 ]; then
  echo "Ошибка постановки задачи в очередь: $(echo "${RUN_RESP}" | jq -r '.statusText')"
  exit 1
fi

TEST_ID=$(echo "${RUN_RESP}" | jq -r '.data.testId')
echo "Тест запущен. ID: ${TEST_ID}"

# 2. Ожидание завершения выполнения теста (polling с таймаутом)
MAX_ATTEMPTS=60
SLEEP_INTERVAL=5
ATTEMPT=0

while [ "${ATTEMPT}" -lt "${MAX_ATTEMPTS}" ]; do
  STATUS_RESP=$(curl -s "${WPT_SERVER}/testStatus.php?test=${TEST_ID}&f=json")
  STATE=$(echo "${STATUS_RESP}" | jq -r '.data.statusCode')

  if [ "${STATE}" -eq 200 ]; then
    echo "Тест успешно завершен."
    break
  elif [ "${STATE}" -gt 200 ]; then
    echo "Ошибка выполнения теста на агенте: $(echo "${STATUS_RESP}" | jq -r '.data.statusText')"
    exit 1
  fi

  echo "Тест в процессе выполнения... (Попытка $((ATTEMPT + 1))/${MAX_ATTEMPTS})"
  sleep "${SLEEP_INTERVAL}"
  ATTEMPT=$((ATTEMPT + 1))
done

# 3. Извлечение результатов и валидация бюджетов
RESULT_JSON=$(curl -s "${WPT_SERVER}/jsonResult.php?test=${TEST_ID}")

SI=$(echo "${RESULT_JSON}" | jq -r '.data.median.firstView.SpeedIndex')
LCP=$(echo "${RESULT_JSON}" | jq -r '.data.median.firstView["chromeUserTiming.LargestContentfulPaint"] // .data.median.firstView.LCP')
TTFB=$(echo "${RESULT_JSON}" | jq -r '.data.median.firstView.TTFB')

MAX_SI=$(jq -r '.median.firstView.SpeedIndex' "${BUDGET_FILE}")
MAX_LCP=$(jq -r '.median.firstView["chromeUserTiming.LargestContentfulPaint"]' "${BUDGET_FILE}")

echo "Результаты замеров (Медиана):"
echo "  Speed Index: ${SI} ms (Лимит: ${MAX_SI} ms)"
echo "  LCP:         ${LCP} ms (Лимит: ${MAX_LCP} ms)"
echo "  TTFB:        ${TTFB} ms"

if [ "${SI}" -gt "${MAX_SI}" ] || [ "${LCP}" -gt "${MAX_LCP}" ]; then
  echo "ОШИБКА: Превышен бюджет производительности! Деплой заблокирован."
  exit 2
fi

echo "Все проверки успешно пройдены."
```

---

### Сценарий 5: Синтетический мониторинг SRE и экспорт метрик в Prometheus

Для непрерывного отслеживания деградации ключевых страниц инженеры SRE настраивают регулярный запуск тестов по расписанию через cron с последующей отправкой метрик в Prometheus Pushgateway.

#### Bash-скрипт сборщика метрик (`wpt-exporter.sh`):

```bash
#!/usr/bin/env bash
set -euo pipefail

WPT_SERVER="http://wpt.internal.corp:8080"
PUSHGATEWAY="http://pushgateway.internal.corp:9091"
JOB_NAME="synthetic_webpagetest"
TARGET_URL="https://example.com"

# Запуск теста с профилем 4G
RESP=$(curl -s -X POST "${WPT_SERVER}/runtest.php" \
  -d "url=${TARGET_URL}" \
  -d "f=json" \
  -d "runs=3" \
  -d "fvonly=1" \
  -d "location=Local_Agent:Chrome.4G")

TEST_ID=$(echo "${RESP}" | jq -r '.data.testId')

# Ожидание готовности
while true; do
  STATUS=$(curl -s "${WPT_SERVER}/testStatus.php?test=${TEST_ID}&f=json" | jq -r '.data.statusCode')
  [ "${STATUS}" -eq 200 ] && break
  sleep 10
done

# Извлечение метрик
DATA=$(curl -s "${WPT_SERVER}/jsonResult.php?test=${TEST_ID}")

SPEED_INDEX=$(echo "${DATA}" | jq -r '.data.median.firstView.SpeedIndex')
TTFB=$(echo "${DATA}" | jq -r '.data.median.firstView.TTFB')
LCP=$(echo "${DATA}" | jq -r '.data.median.firstView["chromeUserTiming.LargestContentfulPaint"] // .data.median.firstView.LCP')
CLS=$(echo "${DATA}" | jq -r '.data.median.firstView.CumulativeLayoutShift')
BYTES_TOTAL=$(echo "${DATA}" | jq -r '.data.median.firstView.bytesIn')

# Формирование и отправка метрик в Prometheus Pushgateway
cat <<EOF | curl --data-binary @- "${PUSHGATEWAY}/metrics/job/${JOB_NAME}/instance/production-frontend"
# HELP wpt_speed_index_ms Медианный Speed Index в миллисекундах
# TYPE wpt_speed_index_ms gauge
wpt_speed_index_ms{url="${TARGET_URL}",profile="4G"} ${SPEED_INDEX}

# HELP wpt_ttfb_ms Время до первого байта (TTFB)
# TYPE wpt_ttfb_ms gauge
wpt_ttfb_ms{url="${TARGET_URL}",profile="4G"} ${TTFB}

# HELP wpt_lcp_ms Largest Contentful Paint в миллисекундах
# TYPE wpt_lcp_ms gauge
wpt_lcp_ms{url="${TARGET_URL}",profile="4G"} ${LCP}

# HELP wpt_cls Cumulative Layout Shift
# TYPE wpt_cls gauge
wpt_cls{url="${TARGET_URL}",profile="4G"} ${CLS}

# HELP wpt_bytes_total Суммарный объем переданных данных
# TYPE wpt_bytes_total gauge
wpt_bytes_total{url="${TARGET_URL}",profile="4G"} ${BYTES_TOTAL}
EOF
```

#### Правило алертинга Prometheus Alertmanager (`webpagetest_alerts.yml`):

```yaml
groups:
  - name: webpagetest_synthetic_alerts
    rules:
      - alert: SyntheticSpeedIndexDegradation
        expr: wpt_speed_index_ms{profile="4G"} > 3000
        for: 30m
        labels:
          severity: warning
          team: sre-frontend
        annotations:
          summary: "Деградация скорости отрисовки интерфейса (Speed Index > 3000ms)"
          description: "Синтетический замер WebPageTest зафиксировал Speed Index {{ $value }}ms для URL {{ $labels.url }}."

      - alert: SyntheticTTFBSlowdown
        expr: wpt_ttfb_ms > 600
        for: 15m
        labels:
          severity: critical
          team: web-platform
        annotations:
          summary: "Критический рост TTFB на Origin сервере"
          description: "Синтетический TTFB превысил 600ms (текущее: {{ $value }}ms). Возможна деградация бэкенда или перегрузка кэша."
```

---

## Операции и команды

### REST API WebPageTest

#### 1. Запуск теста через REST API

```bash
# Комплексный запуск теста с сетевым профилем, сбором pcap и трассировки
curl -s -X POST "http://127.0.0.1:8080/runtest.php" \
  -d "url=https://example.com" \
  -d "k=MasterWptApiKey2026" \
  -d "f=json" \
  -d "runs=5" \
  -d "fvonly=1" \
  -d "location=Local_Agent:Chrome.4G" \
  -d "video=1" \
  -d "tcpdump=1" \
  -d "timeline=1" \
  -d "ignoreSSL=1" \
  -o test_run.json

# Просмотр полученного идентификатора
jq '.data | {testId, userUrl, jsonUrl}' test_run.json
# → {
# →   "testId": "261014_AA_1A2B3C",
# →   "userUrl": "https://example.com",
# →   "jsonUrl": "http://127.0.0.1:8080/jsonResult.php?test=261014_AA_1A2B3C"
# → }
```

#### 2. Опрос статуса выполнения

```bash
# Проверка текущей стадии выполнения задачи
curl -s "http://127.0.0.1:8080/testStatus.php?test=261014_AA_1A2B3C&f=json" | jq '.data'
# → {
# →   "statusCode": 200,
# →   "statusText": "Test Complete",
# →   "testId": "261014_AA_1A2B3C",
# →   "runs": 5,
# →   "completedRuns": 5
# → }
```

#### 3. Извлечение сводных метрик через `jq`

```bash
# Получение ключевых метрик медианного прогона (First View)
curl -s "http://127.0.0.1:8080/jsonResult.php?test=261014_AA_1A2B3C" | jq '.data.median.firstView | {
  URL: .URL,
  TTFB: .TTFB,
  StartRender: .render,
  SpeedIndex: .SpeedIndex,
  LCP: (.["chromeUserTiming.LargestContentfulPaint"] // .LCP),
  TBT: .TotalBlockingTime,
  CLS: .CumulativeLayoutShift,
  Requests: .requestsDoc,
  TotalBytes: .bytesIn
}'
# → {
# →   "URL": "https://example.com",
# →   "TTFB": 142,
# →   "StartRender": 800,
# →   "SpeedIndex": 1245,
# →   "LCP": 1620,
# →   "TBT": 45,
# →   "CLS": 0.012,
# →   "Requests": 24,
# →   "TotalBytes": 612450
# → }
```

#### 4. Скачивание дампов сетевых пакетов (pcap) и HAR-архива

```bash
# Скачивание стандартизированного HAR-файла
curl -s "http://127.0.0.1:8080/export.php?test=261014_AA_1A2B3C&f=har" -o result.har

# Скачивание файла дампа трафика tcpdump первого прогона
curl -s "http://127.0.0.1:8080/getgzip.php?test=261014_AA_1A2B3C&file=1_tcpdump.cap" -o run1.pcap

# Анализ захваченного трафика через tshark в терминале
tshark -r run1.pcap -q -z io,stat,1
# → 0.000-1.000s: Frames: 142 Bytes: 114520
# → 1.000-2.000s: Frames: 85  Bytes: 62410
```

---

### Управление локальным агентом WPT (`wptagent`)

При развертывании агента на физическом сервере без Docker запуск осуществляется напрямую через CLI:

```bash
# Запуск wptagent с поддержкой шейпинга netem, Xvfb и Chromium
python3 /opt/wptagent/wptagent.py \
  --server "http://127.0.0.1:8080/work/" \
  --location "Local_Agent" \
  --key "WptSecretAgentKey2026" \
  --shaper netem \
  --xvfb \
  --browser chrome \
  --debug
# → 20:26:10.123 - Starting new worker
# → 20:26:10.150 - Screen resolution: 1920x1080x24
# → 20:26:10.200 - Checking rate-limiting support (netem)... OK
# → 20:26:10.300 - Polling for work from http://127.0.0.1:8080/work/
```

---

## Диагностика и устранение неполадок

| Неисправность | Вероятная причина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **Агент не забирает задачи из очереди** | Несовпадение идентификатора локации (`LOCATION`) или ключа (`key`) между сервером и агентом | Проверить логи агента: `docker logs wpt-agent` на предмет `404 Not Found` или `Invalid Key` | Убедиться, что секция в `locations.ini` строго совпадает с переменной окружения `LOCATION` и секретом `KEY` |
| **Ошибка шейпинга `RTNETLINK answers: Operation not permitted`** | Контейнер запущен без привилегии `CAP_NET_ADMIN` либо не загружен модуль `sch_netem` на хосте | Выполнить в контейнере: `docker exec -it wpt-agent tc qdisc show` | Добавить `cap_add: [NET_ADMIN]` в `docker-compose.yml` и выполнить `modprobe sch_netem ifb` на хосте |
| **Сбой браузера: `Chrome crashed / Target closed`** | Переполнение общего сегмента памяти `/dev/shm` при тяжелом рендеринге DOM | Проверить объем памяти: `df -h /dev/shm` внутри контейнера агента | Установить `shm_size: 2g` в параметрах контейнера или смонтировать хостовый `/dev/shm:/dev/shm` |
| **Ошибки SSL при проверке внутренних сервисов** | Внутренний корпоративный CA не добавлен в доверенное хранилище агента | В логе теста: `net::ERR_CERT_AUTHORITY_INVALID` | Передать параметр `ignoreSSL=1` при запуске теста через API либо смонтировать сертификат CA в `/usr/local/share/ca-certificates` |
| **Пустой Filmstrip / отсутствие видеозаписи** | Сбой процесса `ffmpeg` или некорректно заданное разрешение виртуального экрана Xvfb | Проверить наличие `ffmpeg` в контейнере: `which ffmpeg` и логи Xvfb в `/tmp` | Установить пакет `ffmpeg`, проверить переменную `EXTRA_ARGS=--xvfb` и параметры разрешения экрана |
| **Высокая нестабильность метрик между прогонами** | Аппаратный шум на хосте (CPU Steal Time в виртуальных машинах, dynamic frequency scaling) | Запустить мониторинг на хосте: `mpstat -P ALL 1` во время выполнения теста | Привязать процесс контейнера к изолированным ядрам CPU через `--cpuset-cpus`, отключить CPU Frequency Governor (`performance`) |
| **Зависание теста на этапе WPT Script** | Не найден DOM-элемент для шага `click` или `submitForm`, таймаут ожидания | Просмотреть консольные логи скрипта в отчете WPT | Добавить шаг `sleep 2` перед кликом, проверить корректность селекторов через Chrome DevTools |
| **Переполнение дискового пространства сервера** | Накопление сырых видеокадров, дампов pcap и trace в директории `results/` | Проверить размер каталога: `du -sh /var/www/html/results` | Настроить cron-задачу ротации и удаления старых тестов (`find /var/www/html/results -type d -mtime +14 -exec rm -rf {} +`) |

---

## Рекомендации и Best Practices

### Методология измерений для SRE

1. **Изоляция аппаратной среды:** Развертывайте агенты WPT на выделенных серверах (Bare-Metal). В виртуализованных средах (KVM/VMware) исключите переподписку ресурсов (CPU Overcommit) и отключите режим энергосбережения ядер процессора (`cpupower frequency-set -g performance`).
2. **Минимальная выборка 5–9 прогонов:** Никогда не принимайте архитектурных решений на основе одиночного замера. Случайный джиттер сокета или сброс кэша могут исказить TTFB и Speed Index на 30–50%.
3. **Разделение очередей тестирования:** Создавайте в `locations.ini` отдельные пулы агентов:
   - *Пул CI/CD:* Для быстрой валидации пул-реквестов (профиль Cable, 3–5 прогонов).
   - *Пул SRE-мониторинга:* Для глубокого синтетического мониторинга (профиль 4G, 9 прогонов, сбор pcap и видео).

### Безопасность и эксплуатация Private Instance

1. **Защита от SSRF (Server-Side Request Forgery):** WPT Agent имеет доступ ко всей внутренней подсети, в которой он запущен. Настройте межсетевой экран (`iptables` / `nftables`), запретив агенту доступ к служебным адресам локальной инфраструктуры (порты баз данных, сервисы управления гипервизорами).
2. **Ограничение доступа к `runtest.php`:** Сервер WebPageTest не имеет встроенной системы разграничения прав для конечных пользователей. Ограничивайте доступ к веб-интерфейсу и API с помощью директив Nginx `allow / deny` по белым спискам IP и обязательного параметра `API_KEY`.
3. **Санация учетных данных в WPT Scripts:** При использовании скриптов с авторизацией создавайте выделенных тестовых пользователей в контурах с минимальными правами доступа (Read-Only) и исключайте хранение паролей в публичных репозиториях.
4. **Управление жизненным циклом артефактов (Retention Policy):** Файлы видеозаписей и pcap-дампы страниц с тяжелым контентом занимают от 50 до 200 МБ на один прогон. Настройте ночную очистку старых директорий тестов через системный планировщик `systemd.timer` или `cron`:

```bash
# Добавление правила очистки результатов старше 14 дней в crontab
echo "0 3 * * * find /opt/webpagetest/results -mindepth 2 -maxdepth 2 -type d -mtime +14 -exec rm -rf {} +" | sudo crontab -
```

---

## Дополнительная информация

### Спецификации и репозитории

- **Репозиторий WPT Server:** [WPO-Foundation/webpagetest](https://github.com/WPO-Foundation/webpagetest) — официальный исходный код сервера и веб-интерфейса.
- **Репозиторий WPT Agent:** [WPO-Foundation/wptagent](https://github.com/WPO-Foundation/wptagent) — агент тестирования на Python 3 для Linux, Windows и macOS.
- **Документация WPT Scripting:** [Спецификация скриптов WebPageTest](https://docs.webpagetest.org/scripting/) — синтаксис директив и примеры сценариев.

### См. также

- **[Принципы тестирования производительности](./testing_principles.md)** — сравнительный анализ синтетических замеров (Lighthouse, WPT, curl) и архитектура сбора артефактов.
- **[Метрики Core Web Vitals](./web_vitals.md)** — детальный разбор LCP, INP, CLS, декомпозиция фаз загрузки и методы мониторинга.
- **[Chrome DevTools для анализа производительности](./chrome_devtools.md)** — архитектура Chrome DevTools Protocol (CDP), Remote Debugging и дампы Tracing.
- **[PageSpeed Insights и CrUX](./pagespeed_insights.md)** — соотношение полевых данных (RUM / Field Data) и синтетических тестов (Lab Data).
- **[Structured Logging для веб-производительности](./structured_logging_for_performance.md)** — сквозная трассировка сетевых задержек на прокси и бэкенде.
- **[tc netem: эмуляция сетевых проблем](../../../Linux/Networking/Tools/iproute2/tc_netem.md)** — детальная настройка очередей ядра Linux для эмуляции задержек, джиттера и потерь.
- **[Шейпинг трафика в Docker](../../../Docker/Docker_network/docker_network_traffic_shaping.md)** — управление сетевыми очередями контейнеров через `tc` и veth-пары.
- **[Обзор оптимизации веб-производительности](./overview.md)** — общая концепция многоуровневой оптимизации веб-систем.

