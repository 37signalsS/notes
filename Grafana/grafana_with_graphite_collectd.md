# Интеграция Grafana с Graphite и Collectd

**Актуально для:** Graphite 1.1.x (образ `graphiteapp/graphite-statsd` `1.1.10-5`), Collectd 5.x, Grafana 13.x / 12.x (LTS)

> **Статус (legacy):** Graphite и Collectd — зрелые, но не получающие активного развития компоненты. Для новых проектов используйте современный стек на базе OpenTelemetry и Prometheus.
>
> - **Метрики:** [Prometheus](../Prometheus/overview.md) + [Grafana Alloy](./grafana_alloy_overview.md)
> - **Логи:** [Loki](../Loki/loki_overview.md) + Alloy
> - **Трассировки:** [Tempo](../Tempo/index.md)
>
> Данная документация сохранена для сопровождения и миграции существующих инсталляций (включая on-premise без выхода в интернет). План перехода — в разделе [Миграция на современный стек](#миграция-на-современный-стек).

## Определения

**Grafana** — универсальная платформа для визуализации данных и построения аналитических панелей (дашбордов). В связке с Graphite выступает исключительно как клиент источника данных (Data Source) и не хранит метрики сама.

**Graphite** — система для сбора, хранения и визуализации временных рядов (time-series data). Архитектура включает три компонента:

- **Carbon** — высокопроизводительный сервис (демон), принимающий метрики по протоколам Line, Pickle или через StatsD и записывающий их в Whisper. Существует в нескольких вариантах: `carbon-cache` (приём + запись + отдача запросов), `carbon-relay` (маршрутизация, шардирование и репликация между нодами), `carbon-aggregator` (предварительная агрегация перед записью).
- **Whisper** — специализированная файловая база данных фиксированного размера (fixed-size), обеспечивающая предсказуемое потребление дискового пространства за счет понижения точности старых данных (downsampling). Каждый временной ряд — это отдельный файл `.wsp`.
- **Graphite-web** — веб-приложение и API для извлечения данных, обеспечивающее функции отрисовки и математической обработки графиков. Именно к его HTTP API (порт 80 внутри официального образа) обращается Grafana.

**Collectd** — легковесный системный агент для периодического сбора метрик производительности (CPU, RAM, дисковые операции, сетевой трафик) и их передачи в системы хранения. Работает по модели подключаемых плагинов: плагины чтения (`read`) собирают данные, плагины записи (`write`) отправляют их во внешние системы (в нашем случае — `write_graphite`).

**StatsD** — простой агрегатор метрик по протоколу UDP/TCP (порт 8125), часто поставляемый вместе с Graphite (образ `graphiteapp/graphite-statsd`). Удобен для отправки прикладных счётчиков и таймеров непосредственно из кода приложения.

**types.db** — текстовый файл Collectd, описывающий типы data source (например, `gauge`, `derive`, `counter`) и количество значений для каждой метрики. Определяет семантику значений, отправляемых плагином `write_graphite`. Путь по умолчанию — `/usr/share/collectd/types.db` (Debian/Ubuntu).

## Базовые концепции

### Поток данных

Процесс мониторинга строится по следующей схеме:

1. **Сбор:** Служба `Collectd` на целевом хосте собирает показатели системы с помощью плагинов.
2. **Передача:** `Collectd` отправляет данные на входной порт `Carbon` (обычно TCP/UDP `2003`).
3. **Хранение:** `Carbon` сохраняет данные в файлы `.wsp` (Whisper).
4. **Запрос:** `Grafana` через свой источник данных (Data Source) обращается к API `Graphite-web`.
5. **Визуализация:** `Graphite-web` считывает данные из `Whisper`, применяет функции и передает их `Grafana` для отрисовки.

### Компоненты Graphite: демоны Carbon

Каждый демон Carbon управляется своей секцией в `carbon.conf`: `carbon-cache` — секцией `[cache]`, `carbon-relay` — `[relay]`, `carbon-aggregator` — `[aggregator]`.

- **`carbon-cache`** — принимает метрики, буферизует их в памяти и записывает в Whisper. Слушает Line Receiver (порт `2003` TCP/UDP) и Pickle Receiver (порт `2004`). Ключевые параметры `[cache]`: `LINE_RECEIVER_PORT`, `PICKLE_RECEIVER_PORT`, `MAX_CACHE_SIZE` (предел буфера в памяти), `MAX_UPDATES_PER_SECOND` и `CACHE_QUERY_INTERVAL` (интервал сброса кэша на диск).
- **`carbon-relay`** — маршрутизация по хостам-назначениям (`DESTINATIONS` в секции `[relay]`), шардирование по метрикам (правила в `relay-rules.conf`) и репликация одной метрики на несколько бэкендов. Слушает порт `2013` (Line) / `2014` (Pickle).
- **`carbon-aggregator`** — предварительная агрегация метрик перед записью по правилам `aggregation-rules.conf`; слушает Line Receiver на порту `2023` и Pickle на `2024`.

В типовом образе `graphiteapp/graphite-statsd` уже запущены `carbon-cache`, `carbon-aggregator` и `carbon-relay` (через супервизор), а также StatsD.

### Формат хранения Whisper

Whisper — файловая БД фиксированного размера. Структура каждого файла задаётся набором *archive* (архивов), где каждый архив описывается точностью (precision) и глубиной хранения (retention):

- Точность определяет интервал между точками (например, `10s`).
- Длительность определяет, как долго архив хранится (например, `1d`).
- При переходе на более грубый архив старые точки агрегируются функцией из `storage-aggregation.conf` (по умолчанию `average`).
- Файл **не растёт** со временем: старые данные перезаписываются циклически. Это даёт предсказуемое потребление диска, но означает, что схему (retentions) нельзя просто изменить «на лету» — нужен `whisper-resize.py` или пересоздание файла.

Для инспекции и обслуживания Whisper используются утилиты: `whisper-info.py` (показать схему), `whisper-create.py` (создать файл), `whisper-resize.py` (изменить retentions), `whisper-dump.py` (сырой дамп), `whisper-set-aggregation-method.py` (сменить метод агрегации в существующем файле).

### Иерархия метрик и теги

Традиционно Graphite использует иерархическую структуру имен, разделенных точками:
`servers.web-01.cpu.usage.user`

Начиная с версии **1.1.0**, Graphite поддерживает **теги** (tags), что приближает его к многомерной модели Prometheus:
`seriesByTag('name=cpu.usage', 'server=web-01', 'type=user')`

Теги задаются при отправке метрики через запятую: `cpu.usage;server=web-01;type=user 42 1692900000`. Источник данных Graphite в Grafana поддерживает теги (функции `tagValues`, `seriesByTag`, автодополнение по тегам), но это требует Graphite ≥ 1.1.0 и корректной отправки тегированных имён.

### Функции обработки

Graphite-web предоставляет сотни встроенных функций для манипуляции данными на лету:
- `aliasByNode(series, node)` — переименование серии по части пути.
- `summarize(series, interval, function)` — агрегация данных за период.
- `movingAverage(series, window)` — сглаживание графиков.
- `asPercent(series1, series2)` — расчет процентного соотношения.
- `sumSeries(*)` — суммирование нескольких рядов (аналог `sum()` в PromQL).
- `scale(series, factor)` — умножение значений на коэффициент (перевод, например, ticks в проценты).
- `perSecond(series)` — вычисление скорости по нарастающему счётчику (аналог `rate()` в PromQL).
- `derivative(series)` — производная ряда (по разнице соседних точек).
- `consolidateBy(series, 'max')` — задаёт функцию консолидации при downsampling.
- `groupByNode(series, node, callback)` — группировка серий по узлу пути с агрегацией callback-функцией.
- `highestMax(series, N)` / `lowestAverage(series, N)` — отбор топ-N серий.
- `nonNegativeDerivative(series)` — производная с игнорированием сбросов счётчика.
- `transformNull(series, value)` — подстановка значения вместо `null` (например, `0`).

### Collectd: модель плагинов и write_graphite

Collectd работает по модели подключаемых плагинов: плагины чтения (`cpu`, `memory`, `load`, `interface`, `disk`, `df`, …) собирают значения, плагины записи (`write_graphite`, `write_tsdb`, `write_prometheus`, …) отправляют их во внешние системы. Глобальный параметр `Interval` задаёт частоту вызовов read-плагинов для всех метрик сразу; он должен совпадать с самым точным уровнем retention в Whisper, иначе в графиках появятся разрывы (см. раздел [Устранение неполадок](#устранение-неполадок)).

```conf
# Минимальный набор плагинов чтения системных метрик
LoadPlugin cpu
LoadPlugin memory
LoadPlugin load
LoadPlugin interface
LoadPlugin disk
LoadPlugin df

# Отправка собранных значений в Graphite
LoadPlugin write_graphite
```

Ключевые параметры плагина `write_graphite` (в `<Plugin write_graphite>`):

| Параметр | Назначение |
| :--- | :--- |
| `Host`, `Port` | Адрес и порт Carbon Line Receiver (обычно `2003`). |
| `Protocol` | `tcp` (по умолчанию с 5.4) или `udp`. TCP надёжнее. |
| `Prefix` | Общий префикс метрик, например `collectd.` — упрощает retention-политики и фильтрацию. |
| `StoreRates` | При `true` значения типов `derive`/`counter` отправляются как скорость (rate), а не сырой нарастающий счётчик. |
| `AlwaysAppendDS` | При `true` к имени добавляется имя data source (например, `.value`). |
| `EscapeCharacter` | Символ (обычно `_`) для замены точек и пробелов в именах хостов/инстансов. |
| `SeparateInstances` | При `true` имя инстанса выносится отдельным узлом в иерархии (например, `cpu-0`). |
| `UseTags` | При `true` метрики отправляются в формате тегов Graphite (`name;key=value`); требует Graphite ≥ 1.1.0. |
| `Postfix` | Строка, добавляемая в конец имени метрики. |
| `ReconnectInterval` | Интервал (в секундах) перед повторным подключением при обрыве связи с Carbon. |
| `LogSendErrors` | Логировать ошибки отправки — критично для диагностики. |

Collectd эволюционирует инкрементально: `write_graphite` появился в **5.1**, поддержка `Protocol "udp"` добавлена в **5.4**. Использовать имеет смысл только актуальную ветку **5.12.x**.

### Конфигурационные файлы Carbon

Все конфигурационные файлы Carbon лежат в `GRAPHITE_CONF_DIR` (в официальном образе — `/opt/graphite/conf`). При установке из исходников рядом лежат шаблоны `*.conf.example`, которые нужно скопировать без суффикса; в официальном образе рабочие `*.conf` уже присутствуют.

| Файл | Что задаёт | Перечитывается на лету |
| :--- | :--- | :--- |
| `carbon.conf` | Настройки демонов: секции `[cache]`, `[relay]`, `[aggregator]` (порты, кэш, `DESTINATIONS` и т.д.). | Требует рестарта демона. |
| `storage-schemas.conf` | Retention-схемы: сопоставление имён метрик (regex) с набором `retentions`. Первое совпадение выигрывает; применяется в момент создания `.wsp`. | Нет (только для новых файлов). |
| `storage-aggregation.conf` | `xFilesFactor` (по умолчанию `0.5`) и `aggregationMethod` (по умолчанию `average`) для downsampling. | Нет (только для новых файлов). |
| `relay-rules.conf` | Правила маршрутизации `carbon-relay`: `pattern` → `servers`. Обязательна секция по умолчанию. | Нет. |
| `aggregation-rules.conf` | Правила `carbon-aggregator`: `output_template (frequency) = method input_pattern`, где `method` — `sum` или `avg`. | Да (автоматически). |
| `rewrite-rules.conf` | Переименование метрик регулярными выражениями в секциях `[pre]` и `[post]`. | Да (для aggregator). |
| `whitelist.conf`, `blacklist.conf` | Белые/чёрные списки метрик (включаются `USE_WHITELIST` в `carbon.conf`); защищают от шума и высококардинальных «мусорных» рядов. | — |

## Практические сценарии

### Предварительные требования

Перед развёртыванием убедитесь, что выполнены следующие условия:

- **Docker + Docker Compose** на хосте Graphite (версия Docker ≥ 20.10, Compose v2). Для Grafana используется образ `grafana/grafana:13.x` (актуальная линейка 13.2.x); для Graphite — `graphiteapp/graphite-statsd:1.1.10-5`.
- **Сеть:** хост(ы) с Collectd должны иметь TCP/UDP-доступ к порту `2003` хоста, где опубликован Carbon. Между Collectd и Graphite не должно быть stateful-файервола, режущего долгие соединения.
- **Порты:** `8080` (Graphite-web UI/API), `2003` (Carbon Line TCP+UDP), `2004` (Pickle), `8125` (StatsD UDP), `3000` (Grafana) должны быть свободны на хосте или корректно проброшены. Внутри официального образа Graphite-web обслуживается nginx на порту `80`, поэтому публикуется как `8080:80`.
- **Диск:** под Whisper требуется выделенный том (объём зависит от числа метрик × retentions; см. расчёт в разделе [Эксплуатация Whisper](#эксплуатация-whisper-и-планирование-хранения)).
- **Collectd** на целевых хостах: пакет `collectd` (Debian/Ubuntu — `apt`, RHEL — `dnf`/`yum` с подключённым EPEL). Минимальная версия — 5.1 (появление `write_graphite`); рекомендуется актуальная ветка 5.12.x.
- **Время:** на всех хостах должен быть синхронизирован NTP — Graphite и Collectd работают с абсолютными метками времени; расхождение часовых поясов и времени ломает графики.

### Развёртывание стека через Docker Compose

Для быстрого развертывания используется официальный образ, объединяющий компоненты Graphite. Авторитетное руководство по запуску Grafana в Docker — [docker_compose_setup.md](./Installation/docker_compose_setup.md).

**Файл `docker-compose.yml`:**

```yaml
services:
  graphite:
    image: graphiteapp/graphite-statsd:1.1.10-5
    container_name: graphite
    restart: always
    ports:
      - "8080:80"       # Graphite Web UI / API (nginx на :80 внутри)
      - "2003:2003"     # Carbon Line Receiver (TCP)
      - "2003:2003/udp" # Carbon Line Receiver (UDP)
      - "2004:2004"     # Carbon Pickle Receiver
      - "8125:8125/udp" # StatsD UDP
    volumes:
      - graphite_data:/opt/graphite/storage
      - graphite_conf:/opt/graphite/conf

  grafana:
    image: grafana/grafana:13.x
    container_name: grafana
    restart: always
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_USERS_ALLOW_SIGN_UP=false
    depends_on:
      - graphite

volumes:
  graphite_data:
  graphite_conf:
  grafana_data:
```

> **Внимание:** пароль `admin/admin` подходит только для локальной отладки. В проде задайте сильный пароль через секреты и ограничьте доступ к порту `3000` (см. раздел [Безопасность](#безопасность)).

> Том `graphite_conf` при первом запуске автоматически наполняется содержимым `/opt/graphite/conf` из образа (так работает пустой named volume в Docker), поэтому шаблоны `*.conf` уже на месте — их можно править прямо в томе.

Запуск и проверка поднятия Graphite:

```bash
docker compose up -d
# → Creating graphite ... done
# → Creating grafana ... done

docker ps --filter name=graphite --format '{{.Names}} {{.Status}}'
# → graphite Up 12 seconds

curl -sI http://localhost:8080 | head -n 1
# → HTTP/1.1 200 OK

docker logs graphite 2>&1 | grep -iE 'carbon-cache|listening on' | head
# → carbon-cache (instances=1) started
```

### Настройка Collectd на целевом хосте

#### Установка

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install collectd -y
# RHEL/CentOS (пакет в EPEL)
sudo dnf install epel-release -y && sudo dnf install collectd -y
```

#### Базовый конфигурационный файл

Отредактируйте `/etc/collectd/collectd.conf`. Минимально рабочий пример с плагинами системных метрик и отправкой в Graphite:

```conf
# Глобальная частота опроса — должна совпадать с первым уровнем retention Whisper (10s)
Interval 10

LoadPlugin cpu
LoadPlugin memory
LoadPlugin load
LoadPlugin interface
LoadPlugin disk
LoadPlugin df
LoadPlugin write_graphite

<Plugin write_graphite>
  <Node "graphite_server">
    Host "192.168.1.100"
    Port "2003"
    Protocol "tcp"
    LogSendErrors true
    Prefix "collectd."
    StoreRates true
    AlwaysAppendDS false
    EscapeCharacter "_"
  </Node>
</Plugin>
```

> `Host` должен указывать на адрес, на котором опубликован порт `2003` Graphite (в Docker-сценарии выше — внешний IP/хостнейм Docker-хоста или `127.0.0.1`, если Collectd стоит на той же машине, где поднят контейнер).

Проверка конфигурации:

```bash
sudo collectd -T
# → пустой вывод = конфиг корректен; иначе будет указана строка с ошибкой
```

Перезапуск и проверка статуса:

```bash
sudo systemctl restart collectd
systemctl status collectd --no-pager | head -n 3
# → Active: active (running)
```

### Проверка сквозного конвейера (end-to-end)

После запуска имеет смысл вручную проверить путь метрики от отправки до Grafana:

```bash
# 1. Отправка синтетической метрики в Carbon (Line Protocol)
echo "test.metric 42 $(date +%s)" | nc -q1 127.0.0.1 2003

# 2. Проверка, что Carbon создал файл Whisper
docker exec graphite find /opt/graphite/storage/whisper -name 'test*.wsp'
# → /opt/graphite/storage/whisper/test/metric.wsp

# 3. Запрос данных через Graphite-web API
curl -s 'http://localhost:8080/render?target=test.metric&format=json&from=-5min'
# → [{"target": "test.metric", "datapoints": [[42.0, 1692900000]]}]
```

Если метрика видна в `/render`, значит связка Collectd/Carbon/Whisper/Graphite-web работает, и можно строить панель в Grafana.

### Настройка источника данных в Grafana

1. Войдите в Grafana (`http://localhost:3000`).
2. Перейдите в **Connections → Data sources**.
3. Нажмите **Add new data source** и выберите **Graphite**.
4. Укажите URL: `http://graphite:80` (имя сервиса из `docker compose`).
5. В поле **Version** выберите версию (например, `1.1.x`).
6. Нажмите **Save & test**.

Ожидаемый результат: `Data source is working` (Grafana проверяет доступность `/render` и `/metrics/find`). Если Grafana и Graphite в одном Docker Compose, имя хоста `graphite` резолвится через внутреннюю сеть Compose.

Пример запроса на панели (использует функции обработки из раздела выше):

```
aliasByNode(scale(collectd.*.cpu.usage.user, 0.01), 1)
```

Этот запрос берёт `user`-время CPU во всех хостах, переводит ticks в проценты (`scale` на 0.01) и подписывает линии именем хоста (`aliasByNode(..., 1)`).

Альтернатива — декларативное подключение источника через provisioning (см. [grafana_provisioning.md](./grafana_provisioning.md)):

```yaml
apiVersion: 1
datasources:
  - name: Graphite
    type: graphite
    access: proxy
    url: http://graphite:80
    jsonData:
      graphiteVersion: "1.1"
```

### Сбор прикладных метрик через StatsD

Помимо системных метрик Collectd, приложение может отправлять бизнес-счётчики напрямую в StatsD (порт `8125`), что полезно для событий, не привязанных к опросу по интервалу.

```bash
# counters: increment
echo "orders.created:1|c" | nc -q1 -u 127.0.0.1 8125
# timers: значение в миллисекундах
echo "orders.latency:120|ms" | nc -q1 -u 127.0.0.1 8125
# gauges: абсолютное значение
echo "queue.size:42|g" | nc -q1 -u 127.0.0.1 8125
```

Проверка (StatsD агрегирует и сбрасывает в Carbon раз в flush-интервал, по умолчанию 10s):

```bash
curl -s "http://localhost:8080/render?target=stats.*&format=json&from=-1min" | head -c 300
# → [{"target": "stats.orders.created", "datapoints": [[1.0, ...]]}]
```

### Масштабирование и отказоустойчивость

При росте числа метрик один `carbon-cache` перестаёт справляться, а один узел становится точкой отказа. Стандартная схема масштабирования Graphite:

1. **Fan-out записи через `carbon-relay`.** Несколько `carbon-cache` за одним `carbon-relay`; секция `[relay]` в `carbon.conf` задаёт `DESTINATIONS = <host>:<port>` (порт Pickle `2004` целевых кэшей), а `relay-rules.conf` распределяет метрики по узлам по regex. Коллекторы (Collectd/StatsD) отправляют метрики на `relay`, а не напрямую в кэш.
2. **Репликация.** В `relay-rules.conf` одна и та же метрика может быть отправлена на несколько серверов одновременно (`servers = hostA, hostB`) — это даёт горячий резерв, но удваивает объём записи и требует, чтобы Grafana могла запрашивать оба кэша.
3. **Горизонтальное масштабирование чтения.** `graphite-web` — stateless-слой запросов поверх общего хранилища Whisper; его можно запускать в нескольких экземплярах за балансировщиком (типовая связка — nginx + gunicorn, по умолчанию gunicorn слушает `127.0.0.1:8080`). Все экземпляры должны видеть один и тот же каталог `/opt/graphite/storage/whisper` (общая ФС/NFS).
4. **Pre-aggregation.** `carbon-aggregator` через `aggregation-rules.conf` заранее суммирует/усредняет метрики, снижая нагрузку на чтение и объём хранения.

> Graphite хранит данные на локальной файловой системе, поэтому полноценный HA требует либо репликации на уровне `carbon-relay`, либо общего хранилища. Это принципиально слабее репликации Prometheus/Mimir — ещё одна причина планировать миграцию.

## Эксплуатация Whisper и планирование хранения

### Политики хранения (storage-schemas.conf)

Определяют точность и длительность хранения данных. Секции применяются сверху вниз, выигрывает первое совпадение `pattern`; retention фиксируется в момент создания `.wsp`.

```ini
[collectd]
pattern = ^collectd\.
retentions = 10s:1d,1m:7d,10m:1y
# 10 сек точность на 1 день, 1 мин на 7 дней, 10 мин на 1 год
```

Правило записи: `frequency:history`, где `history` можно задавать суффиксами `s`, `m`, `h`, `d`, `w`, `y`. Уровни перечисляются от самого точного к самому грубому.

### Агрегация данных (storage-aggregation.conf)

Определяет способ вычисления значений при переходе на менее точный уровень (downsampling).

```ini
[min]
pattern = \.min$
xFilesFactor = 0.1
aggregationMethod = min

[default_average]
pattern = .*
xFilesFactor = 0.5
aggregationMethod = average
```

- `xFilesFactor`: минимальная доля непустых слотов предыдущего уровня, необходимая для вычисления агрегата (по умолчанию 0.5 = 50%).
- `aggregationMethod`: метод агрегации — `average` (по умолчанию), `sum`, `min`, `max`, `last`.

Применение изменений: файлы `storage-schemas.conf` и `storage-aggregation.conf` лежат в `/opt/graphite/conf` (в Docker — смонтированный том `graphite_conf`). Изменения влияют только на **новые** `.wsp`-файлы; для уже существующих нужен `whisper-resize.py` (смена retentions) или `whisper-set-aggregation-method.py` (смена метода агрегации). `carbon-aggregator`, напротив, перечитывает `aggregation-rules.conf` и `rewrite-rules.conf` автоматически.

### Расчёт объёма

Каждая точка Whisper занимает 12 байт (8 байт значение + 4 байта метка времени). Объём одного `.wsp` приблизительно равен сумме по архивам:

```
size ≈ Σ (history_seconds / frequency_seconds × 12) байт
```

Для схемы `10s:1d,1m:7d,10m:1y` это `8640×12 + 10080×12 + 52560×12 ≈ 0.9 МБ` на один ряд. Умножив на число рядов, легко получить требуемый объём тома. Дополнительно к тому же добавляются накладные расходы файловой системы (каждый `.wsp` — отдельный файл: при сотнях тысяч рядов нужен раздел с большим `inode`-лимитом и `noatime`).

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Метрики не появляются в Grafana | Collectd не может подключиться к Carbon | Проверьте `journalctl -u collectd`; убедитесь, что порт `2003` открыт, а `Host`/`Port` в `write_graphite` указаны верно. |
| `send failed` в логах Collectd | Carbon недоступен или не слушает `2003` | `docker logs graphite \| grep -i 'line receiver'`; проверьте, что порт `2003` проброшен и не занят. |
| Отказ запуска Collectd | Синтаксическая ошибка в конфиге | `sudo collectd -T` покажет строку с ошибкой; исправьте и перезапустите. |
| `Data source is working`, но графики пусты | Неверный target или нет данных за период | Проверьте `curl …/render?target=…`; сверьте имя метрики с `metrics/find` (учтите `Prefix` и `EscapeCharacter`). |
| Пустые списки метрик | Ошибка Carbon или права доступа | Проверьте `docker logs graphite` и каталог `/opt/graphite/storage/whisper`. |
| Permission denied при записи в Whisper | Неверный владелец тома | Whisper пишет пользователь `graphite` внутри контейнера; проверьте права смонтированного `graphite_data`. |
| «Broken»/разрывы на графиках | Несовпадение `Interval` Collectd и точности первого архива Whisper | Приведите `Interval` к значению первого retention (например, `10s`). |
| Графики «сглажены», пиков не видно | consolidation `average` на грубом архиве | В запросе добавьте `consolidateBy(series, 'max')` или уменьшите окно просмотра. |
| Тегированные запросы пусты | Graphite < 1.1.0 или теги не отправлялись | Убедитесь, что версия ≥ 1.1.0 и имена метрик содержат `;key=value`. |
| Расхождение времени на графиках | Разный часовой пояс / нет NTP | Graphite хранит UTC; выставьте часовой пояс дашборда в Grafana, синхронизируйте NTP на хостах. |
| Высокая нагрузка на CPU/I/O и память `carbon-cache` | Большой кэш или высокий поток метрик | Настройте `MAX_CACHE_SIZE` и `MAX_UPDATES_PER_SECOND`, `USE_FLOW_CONTROL`, ограничьте кардинальность и `whitelist.conf`. |
| Данные в Whisper «застыли» на точке | Проблемы с retention/агрегацией | Проверьте `whisper-info.py`; при необходимости `whisper-resize.py` / `whisper-set-aggregation-method.py`. |
| Медленный рендеринг при большом периоде | Downsampling выполняет `graphite-web` на лету | Добавьте предварительную агрегацию (`carbon-aggregator`) или кэш запросов. |
| Дублирование или потеря метрик в кластере | Неверные `DESTINATIONS`/`relay-rules.conf` | Проверьте `[relay]` в `carbon.conf` и соответствие правил фактической топологии. |

## Безопасность

- **Отсутствие аутентификации:** протокол Carbon (порт `2003`) не имеет встроенной проверки подлинности. Используйте сетевые экраны (firewall) для ограничения доступа.
- **Безопасность API:** ограничьте доступ к Graphite-web (порт `80`), разрешив запросы только от IP-адреса Grafana.
- **Пароль Grafana:** не используйте `admin/admin` в проде; задайте надёжный пароль через переменные окружения/секреты и отключите публичную регистрацию (`GF_USERS_ALLOW_SIGN_UP=false`).
- **StatsD (8125):** принимает метрики от любого, кто имеет сетевой доступ — ограничьте порт на уровне хоста/сети, иначе возможна инъекция мусорных метрик.
- **Шифрование в пути:** для удалённых хостов терминируйте TLS перед Graphite-web (reverse proxy) и используйте VPN/тоннель для порта `2003`, так как Carbon передаёт данные в открытом виде.
- **Изоляция портов:** публикуйте наружу только `8080` (API) и `2003` (приём метрик от доверенной сети); `2004`, `8125`, `8126`, `7002` (внутренние порты демонов) держите во внутренней сети Docker.

## Рекомендации по эксплуатации

- **Планируйте retention и объём заранее:** Whisper не сжимает и не перестраивает файлы автоматически — схему задают до первой записи метрики, а пересоздание сотен тысяч `.wsp` дорого.
- **Фиксируйте версии образов** (`graphiteapp/graphite-statsd:1.1.10-5`, `grafana/grafana:13.x`) — обновления меняют поведение схем хранения и функций.
- **Выносите хранилище отдельным томом** (`graphite_data`) и регулярно бэкапьте каталог `whisper` (он является базой целиком). Для согласованного бэкапа останавливайте `carbon-cache` либо снимайте снапшот файловой системы.
- **Мониторьте сам Graphite:** Carbon отдаёт свои метрики (`carbon.agents.*`, `carbon.cache.*`), добавьте их в Grafana, чтобы видеть переполнение кэша и отставание записи.
- **Конфигурируйте data source через provisioning** (см. [grafana_provisioning.md](./grafana_provisioning.md)) вместо ручной настройки UI — воспроизводимость и контроль версий.
- **Ограничивайте кардинальность:** избегайте высококардинальных тегов (например, `user_id` или `request_id` в имени метрики) — Whisper плохо масштабируется на миллионы рядов.
- **Очистка:** для вывода стека остановите контейнеры (`docker compose down`) и при необходимости удалите тома (`docker volume rm graphite_data graphite_conf grafana_data`); данные Whisper без бэкапа восстановлению не подлежат.

## Ограничения и особые случаи

- **Схема Whisper неизменяема «на лету»:** изменение `retentions` для уже существующей метрики требует `whisper-resize.py` или пересоздания файла; иначе новые точки пишутся по старой схеме.
- **Потеря данных при UDP:** отправка метрик по UDP (`Protocol "udp"`) не гарантирует доставку — при перегрузке сети точки теряются. Для надёжности используйте TCP.
- **Фиксированный размер файла:** предсказуемость диска оборачивается тем, что старые данные безвозвратно перезаписываются при downsampling — «детальную» историю вернуть нельзя.
- **Кардинальность:** Whisper плохо переносит миллионы уникальных имён метрик; при росте числа рядов переходите на Prometheus-совместимое хранилище.
- **Агрегация ограничена:** Graphite не умеет агрегировать по произвольным лейблам так же гибко, как PromQL; сложные запросы «по всем хостам с тегом X» ограничены моделью тегов 1.1.x.
- **Нет встроенного алертинга:** у Carbon/Graphite-web нет собственного движка алертов. Пороговые правила настраиваются на стороне Grafana (Alerting) поверх запросов к источнику данных Graphite либо внешними системами через API.
- **Режим сопровождения:** Graphite развивается медленно (стабильная ветка 1.1.x), Collectd получает только точечные исправления. Новый функционал и масштабируемость обеспечивает стек Prometheus-совместимых хранилищ.

## Миграция на современный стек

План перехода:

1. **Параллельный запуск:** установите [Grafana Alloy](./grafana_alloy_overview.md) рядом с Collectd, не отключая текущий сбор.
2. **Сбор метрик.** Варианты:
   - установить [Grafana Alloy](./grafana_alloy_overview.md) и задействовать компонент `prometheus.exporter.unix` для системных метрик хоста;
   - либо перевести сам Collectd на плагин `write_prometheus` (HTTP-endpoint, который скребёт Prometheus/Alloy).
3. **Хранение.** Направьте метрики в [Prometheus](../Prometheus/overview.md) или в долговременное хранилище [Mimir](../Mimir/mimir_overview.md).
4. **Конвертация дашбордов и алертов:** перепишите Graphite-запросы на PromQL.
5. **Переключение источников** в Grafana и **вывод из эксплуатации** Graphite после проверки.

Пример сопоставления запросов при миграции:

| Graphite | PromQL (Alloy → Mimir) |
| :--- | :--- |
| `sumSeries(collectd.*.cpu.usage.user)` | `sum(collectd_cpu_usage_user)` |
| `perSecond(collectd.*.interface.if_octets.rx)` | `rate(collectd_interface_if_octets_rx[1m])` |
| `aliasByNode(collectd.*.load.load, 1)` | `label_replace(collectd_load_load, "host", "$1", "instance", "(.+)")` |
| `movingAverage(series, "10min")` | `avg_over_time(series[10m])` |

> **Важно:** сами исторические данные Whisper в Prometheus/Mimir напрямую не переносятся (нет штатного импортёра Graphite→TSDB). Мигрируются дашборды, алерты и конвейер сбора; историю при необходимости оставляют рядом на read-only Graphite до истечения retention.

## Дополнительная информация

- Официальная документация Graphite — [graphite.readthedocs.io](https://graphite.readthedocs.io/en/stable/): разделы по Carbon, Whisper и функциям обработки.
- **Диагностические утилиты Whisper** (пакет `whisper`): `whisper-info.py` (схема файла), `whisper-dump.py` (сырые данные), `whisper-resize.py` (смена retentions), `whisper-set-aggregation-method.py` (смена метода агрегации).
- **Каталоги в образе:** метрики — `/opt/graphite/storage/whisper`, конфигурация — `/opt/graphite/conf`, логи — `/opt/graphite/storage/log`.

### См. также

- [Источники данных Grafana](./grafana_datasources.md)
- [Grafana Alloy — обзор и миграция](./grafana_alloy_overview.md)
- [Mimir: хранение метрик](../Mimir/mimir_overview.md)
- [Prometheus: обзор](../Prometheus/overview.md)
