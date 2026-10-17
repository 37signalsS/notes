# Нагрузочное тестирование с помощью Yandex.Tank и Taurus

**Актуально для:** Yandex.Tank 1.15.x (Python 3), Taurus 1.17.x, InfluxDB 1.x, Grafana 12.x

> **Статус:** Yandex.Tank (open-source) и Taurus (open-source) активно поддерживаются сообществом. Облачный сервис **Yandex Load Testing** (SaaS-надстройка над Yandex.Tank) прекратил существование 1 июля 2026 года — миграция на **k6** (см. [k6](./k6_load_testing.md)). Сам open-source Yandex.Tank и Taurus остаются работающими локальными инструментами для on-premise и CI/CD-интеграций.

## Определения

**Yandex.Tank** — open-source консольный генератор нагрузки (Python 3). Разработан и поддерживался Яндексом, используется в производстве для стресс- и нагрузочных тестов. Ключевая особенность — программное управление профилем нагрузки: поддержка автостопа (autostop), гибкая настройка деградации, сбор метрик через Telegraf и SSH-мониторинг целевого хоста.

**Taurus (bzt)** — open-source фреймворк-обёртка поверх разных генераторов (CLI: `bzt`), лицензия Apache 2.0. Позволяет **описывать тест в едином YAML** и запускать поверх JMeter, Gatling, Locust, k6, Selenium и Yandex.Tank. Актуальная версия 1.17.x (2026). Реализована на Python 3.

Любимый «prod»-стек в СНГ-продакшенах: **Taurus (YAML) + Yandex.Tank (генератор) + InfluxDB/Grafana (метрики)**.

## Основные концепции

### Архитектура Taurus

Taurus — обёртка, а не самостоятельный генератор. Работает так:

1. Читает сценарий — единый **YAML-файл** (или несколько конфигов), в котором объявлены: исполнитель (executor), нагрузки(шаги), метрики, ассерты, журналирование.
2. Транслирует его в конфиг конкретного генератора (например, JMeter) и запускает.
3. Собирает результаты в собственный формат и текущую метрику, отдаёт в указанные бэкенды (файл, InfluxDB, Grafana).

### YAML-конфигурация (ядро)

```yaml
execution:
- scenario: simple_load
  concurrency: 100         # активные виртуальные пользователи
  ramp-up: 1m
  hold-for: 5m
scenarios:
  simple_load:
    requests:
    - url: https://api.example.com/v1/resource
      method: GET
      think-time: 1s       # пауза между запросами
```

- `concurrency` — количество потоков.
- `ramp-up`, `hold-for`, `steps`, `throughput` — профиль нагрузки.
- Для точного RPS используется `throughput` (или `constant-arrival-rate` в k6 — см. [Методология](./performance_testing_methodology.md)).

### Профили нагрузки

Taurus поддерживает разные сценарии изменения нагрузки во времени:

- линейный ramp-up;
- `steps` — ступенчатая нагрузка для поиска точки деградации;
- паузы (`ramp`/`hold` и `dead` периоды);
- `rps-per-iteration` — RPS на итерацию.

### Генераторы (executors)

| Executor | Генератор | Когда применять |
| :--- | :--- | :--- |
| `jmeter` | Apache JMeter | Совместимость с существующими JMX-планами, корпоративный стандарт |
| `gatling` | Gatling (Scala) | Java/Scala-стек, код на Scala |
| `locust` | Locust (Python) | Python-стек, swarm-модель |
| `yandex-tank` | Yandex.Tank | Максимальный RPS с одного узла, стресс на HTTP |
| `k6` | k6 (Grafana) | Простой код, CI/CD |
| `selenium` | Selenium WebDriver | E2E сценарная нагрузка (не рекомендуется для load) |

### Yandex.Tank: генераторы внутри

Yandex.Tank использует сменные «генераторы трафика» (generators):

- **phantom** — default, низкоуровневый HTTP-генератор на C/C++: высокая производительность, поддержка pipelining, 100 000+ RPS с одного узла (по документации); для стресс-тестов. Не поддерживает HTTP/2.
- **pandora** — внешний Go-генератор, поддерживает HTTP/2; удобен для own-метрик и критериев через expvar.
- **jmeter** — как «внешний» генератор.
- **bfg** — Python-генератор для кастомных сценариев (HTTP/HTTPS, HTTP/2); позволяет писать сценарии нагрузки на Python.
- **firebat** — устаревший генератор на базе phantom (устраняется из поддержки).

### Каналы данных и бэкенды

Результаты теста Taurus отправляет в:

- **InfluxDB** — с метриками теста (RPS, latency, errors) и служебной информацией; Taurus добавляет тег `application` при настройке `applications:`.
- **Grafana** — дашборды на данные InfluxDB.
- **Файлы** — csv/jtl для последующей обработки.
- **Overload** — сервис аналитики результатов Yandex.Tank (отключён вместе с Yandex Load Testing в 2026 г.). Актуальная альтернатива — Loki/Grafana или собственная push-модель в InfluxDB.

## Практические сценарии

### Сценарий 1: Установка

```bash
# Taurus (Python) — любой менеджер, лучше в venv
python3 -m venv .venv && source .venv/bin/activate
pip install bzt

# Yandex.Tank (для прямых прогонов)
pip install yandex-tank
```

### Сценарий 2: Запуск простого теста

```yaml
# perf-test.yml
execution:
- scenario: order_flow
  concurrency: 50
  ramp-up: 30s
  hold-for: 2m
scenarios:
  order_flow:
    requests:
    - url: /api/v1/orders
      method: POST
      headers:
        Content-Type: application/json
      body: '{"user": 123}'
    - url: /api/v1/orders/123/status
      method: GET
settings:
  artifacts-dir: ./artifacts
```

```bash
bzt perf-test.yml   # вывод прогресса в консоль + отчёт в artifacts/
```

После прогона в `artifacts/` появятся `*.log`, результаты и CSV с агрегированными метриками.

### Сценарий 3: Metrics Query — критерии PASS/FAIL

Taurus умеет проверять перцентили прямо в конфиге:

```yaml
execution:
- scenario: api
  concurrency: 200
  hold-for: 3m
scenarios:
  api:
    requests:
    - url: /health
reporting:
- module: final-stats
  summary: true
  percentiles: [90, 95, 99]
  algorithms: [avg, stdev, percentiles]
  strict-interpretation: true
  fail:                      # критерии провала теста
  - condition: percentile-90 > 800ms
  - condition: failures > 1%
```

Проверка критериев происходит после окончания прогона.

### Сценарий 4: Комбинированный тест JMeter + Taurus

Если уже есть JMX-планы, их можно запускать через Taurus, расширяя YAML:

```yaml
execution:
- executor: jmeter
  scenario: legacy_flow
scenarios:
  legacy_flow:
    script: /tests/plan.jmx
    variables:
      threads: 100
modules:
  jmeter:
    path: /opt/apache-jmeter-5.6.3/bin/jmeter
```

### Сценарий 5: Мониторинг через InfluxDB + Grafana

```yaml
modules:
  influxdb-reporter:
    host: influxdb
    port: 8086
    database: loadtest
    username: tank
    password: tank
reporting:
- influxdb-reporter
```

В Grafana подключить источник InfluxDB и импортировать дашборд Taurus — метрики RPS, latency, errors по времени теста.

### Примечание про Yandex Load Testing (SaaS)

Бывший облачный сервис **Yandex Load Testing** (надстройка над Yandex.Tank, интеграция с Яндекс.Облаком) **выведен из эксплуатации с 1 июля 2026 года**. Официальная рекомендация миграции — **k6** (см. [Нагрузочное тестирование с помощью k6](./k6_load_testing.md)). Сам open-source **Yandex.Tank и Taurus остаются рабочими** локальными инструментами, однако для продакшн-платформ нагруза «как сервис» сейчас выгоднее строить на k6/kubernetes или Locust/kubernetes.

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Cannot find generator` | Не установлен executor (gatling/locust/jmeter) | `pip install bzt[extra]` или установить генератор отдельно |
| Резкий рост RPS сразу | Нет ramp-up, phantom разгоняется агрессивно | Задать `ramp-up` в профиле; исключить `hold-for` без паузы |
| отставание от in-clock сета | Драйвер через HTTP, задержки сети | Использовать `.hdr`-драйвер, `connections-per-host` |
| influxdb: connection refused | Не создана БД/порт слушает локально | Создать БД `loadtest` заранее, проверить `bind-address` |
| teardown не выполняется | Ошибка в YAML до стадии teardown | Проверить синтаксис через внешний валидатор YAML (например, `yamllint`); Taurus не имеет встроенной команды валидации конфига |
| Большой расход памяти Taurus | Долгий тест с большим artifacts | Включить модуль `resource-check` с `mem_limit`; ограничить `check-interval`; ротировать `artifacts-dir` между прогоны |

## Лучшие практики

### Архитектура и запуск

- **Разделяйте генератор и измеритель.** Запускать Yandex.Tank/Taurus на том же хосте, что и тестируемый сервис, создаёт ложный бутылочный колпачок (конкуренция за CPU, сеть, память). Генератор — на выделенном хосте или в отдельном контейнере/Docker-сети.
- **Phantom для пика:** используйте `phantom` для тестов до 100 000+ RPS с одного узла, включая HTTP pipelining. Для HTTP/2 — `pandora`.
- **Ramp-up обязателен:** всегда задавайте `ramp-up` — резкий старт Phantom без разгона приводит к искусственным задержкам и преждевременному срабатыванию autostop.
- **Autostop (автостоп):** используйте встроенный autostop для экономии времени — останавливайте тест, когда SRE-критерии (SLA) нарушаются (error rate > N%, latency > N ms).

### Мониторинг и метрики

- **Telegraf + SSH:** Yandex.Tank собирает системные метрики целевого хоста через Telegraf по SSH. Это позволяет коррелировать нагрузку с CPU, memory, disk I/O на сервере-источнике.
- **InfluxDB + Grafana:** настраивайте постоянный дашборд с метриками RPS, latency (p50/p95/p99), error rate, а также системными метриками хоста.
- **Prometheus:** Taurus не имеет встроенного Prometheus-модуля. Для интеграции используйте InfluxDB reporter (InfluxDB поддерживает scrape Prometheus-метрик) или экспортируйте `final-stats` в XML/JUnit-формат для последующей обработки в Prometheus.

### SRE-интеграция

- **Error budget:** используйте результаты нагрузочных тестов для установки SLO/SLI на задержки и ошибки. Autostop в Taurus позволяет остановить тест, когда budget истек.
- **Burn rate:** для CI/CD-интеграции ограничьте длительность `hold-for` (5–10 минут) — полные стресс-тесты (hours) допускаются только в off-hours.
- **Baseline:** фиксируйте `merged.yml` и `bzt.log` в артефактах CI для сравнения с последующими прогонами.

### Управление артефактами (Cleanup)

- **Ротация `artifacts-dir`:** Taurus сохраняет всё в `artifacts/<timestamp>/`. Автоматизируйте очистку старых артефактов (`find artifacts/ -mtime +7 -delete`).
- **Логи:** для долгих тестов включайте `settings: verbose: false` и используйте `tail -f bzt.log` для мониторинга, а не вывод в консоль.
- **Контейнеры:** если используете Docker-образ `direvius/yandex-tank`, останавливайте контейнеры после прогона (`docker rm -f <container>`).

### Edge Cases

- **HTTP/2:** `phantom` не поддерживает HTTP/2 — используйте `pandora`.
- **SSL/TLS:** для тестов с клиентскими сертификатами используйте опции `ssl:`, `client_certificate:`, `client_key:` в конфиге phantom.
- **AMMO-форматы:** Yandex.Tank поддерживает URI-style, URI+POST-style, request-style, а также `access.log`-формат. Выбор формата влияет на производительность генератора.

## Дополнительная информация

### См. также

- **[Методология тестирования производительности](./performance_testing_methodology.md)** — профили нагрузки, персоналии, работа с NFR.
- **[Нагрузочное тестирование с помощью Apache JMeter](./jmeter_load_testing.md)** — executor `jmeter` внутри Taurus.
- **[Нагрузочное тестирование с помощью k6](./k6_load_testing.md)** — современный стек (рекомендуется для новых систем и миграции с Yandex Load Testing).

### Внешние ресурсы

- [Taurus (bzt) на GitHub](https://github.com/Blazemeter/taurus) — исходный код, скачивание, документация.
- [Yandex.Tank на GitHub](https://github.com/yandex/yandex-tank) — исходный код генератора.
- [Документация Yandex.Tank](https://yandextank.readthedocs.io/en/latest/) — официальная документация.