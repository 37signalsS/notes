# Интеграция Grafana с Graphite и Collectd

> **ВНИМАНИЕ:** Graphite и Collectd считаются устаревшими компонентами. Для новых проектов настоятельно рекомендуется использовать современный стек на базе OpenTelemetry и Prometheus.
>
> - **Метрики:** [Prometheus](../Prometheus/overview.md) + [Grafana Alloy](./grafana_alloy_overview.md)
> - **Логи:** [Loki](../Loki/loki_overview.md) + Alloy
> - **Трассировки:** [Tempo](../Tempo/index.md)
>
> Данная документация сохранена исключительно для поддержки и миграции существующих систем. Актуальный статус стека и рекомендации по выводу из эксплуатации — в разделе «Актуальность и статус» ниже.

## Определения

**Grafana** — универсальная платформа для визуализации данных и построения аналитических панелей (дашбордов). В связке с Graphite выступает исключительно как клиент источника данных (Data Source) и не хранит метрики сама.

**Graphite** — система для сбора, хранения и визуализации временных рядов (time-series data). Архитектура включает три компонента:

- **Carbon** — высокопроизводительный сервис (демон), принимающий метрики по протоколам Line, Pickle или через StatsD и записывающий их в Whisper. Существует в нескольких вариантах: `carbon-cache` (приём + запись + отдача запросов), `carbon-relay` (маршрутизация, шардирование и репликация между нодами), `carbon-aggregator` (предварительная агрегация перед записью).
- **Whisper** — специализированная файловая база данных фиксированного размера (fixed-size), обеспечивающая предсказуемое потребление дискового пространства за счет понижения точности старых данных (downsampling). Каждый временной ряд — это отдельный файл `.wsp`.
- **Graphite-web** — веб-приложение и API для извлечения данных, обеспечивающее функции отрисовки и математической обработки графиков. Именно к его HTTP API (порт 80) обращается Grafana.

**Collectd** — легковесный системный агент для периодического сбора метрик производительности (CPU, RAM, дисковые операции, сетевой трафик) и их передачи в системы хранения. Работает по модели подключаемых плагинов: плагины чтения (`read`) собирают данные, плагины записи (`write`) отправляют их во внешние системы (в нашем случае — `write_graphite`).

**StatsD** — простой агрегатор метрик по протоколу UDP/TCP (порт 8125), часто поставляемый вместе с Graphite (образ `graphiteapp/graphite-statsd`). Удобен для отправки прикладных счётчиков и таймеров непосредственно из кода приложения.

**types.db** — текстовый файл Collectd, описывающий типы data source (например, `gauge`, `derive`, `counter`) и количество значений для каждой метрики. Определяет семантику значений, отправляемых плагином `write_graphite`.

## Базовые концепции

### Поток данных

Процесс мониторинга строится по следующей схеме:

1. **Сбор:** Служба `Collectd` на целевом хосте собирает показатели системы с помощью плагинов.
2. **Передача:** `Collectd` отправляет данные на входной порт `Carbon` (обычно TCP/UDP `2003`).
3. **Хранение:** `Carbon` сохраняет данные в файлы `.wsp` (Whisper).
4. **Запрос:** `Grafana` через свой источник данных (Data Source) обращается к API `Graphite-web`.
5. **Визуализация:** `Graphite-web` считывает данные из `Whisper`, применяет функции и передает их `Grafana` для отрисовки.

### Компоненты Graphite: демоны Carbon

Carbon — не один процесс, а набор взаимодействующих демонов, что важно понимать при масштабировании и отказоустойчивости:

- **carbon-cache** — основной приёмник. Слушает Line-протокол (`2003`), Pickle (`2004`) и отдаёт запросы на чтение через внутренний порт (`7002`). Метрики буферизуются в памяти (`MAX_CACHE_SIZE` в `carbon.conf`) и периодически сбрасываются в Whisper.
- **carbon-relay** — используется для шардирования (разные префиксы метрик → разным `carbon-cache`) и репликации (одна метрика → нескольким нодам). Позволяет строить отказоустойчивые кластеры Graphite.
- **carbon-aggregator** — стоит перед `carbon-cache` (порт `2023` по умолчанию) и预варительно агрегирует метрики (например, суммирует перцентили), снижая нагрузку на хранилище и кардинальность.

В типовом образе `graphiteapp/graphite-statsd` уже запущены `carbon-cache`, `carbon-aggregator` и `carbon-relay` (через супервизор), а также StatsD.

### Формат хранения Whisper

Whisper — файловая БД фиксированного размера. Структура каждого файла задаётся набором *archive* (архивов), где каждый архив описывается точностью (precision) и глубиной хранения (retention):

- Точность определяет интервал между точками (например, `10s`).
- Длительность определяет, как долго архив хранится (например, `1d`).
- При переходе на более грубый архив старые точки агрегируются функцией из `storage-aggregation.conf` (по умолчанию `average`).
- Файл **не растёт** со временем: старые данные перезаписываются циклически. Это даёт предсказуемое потребление диска, но означает, что схему (retentions) нельзя просто изменить «на лету» — нужен `whisper-resize.py` или пересоздание файла.

Для инспекции и обслуживания Whisper используются утилиты: `whisper-info.py` (показать схему), `whisper-create.py` (создать файл), `whisper-resize.py` (изменить retentions), `whisper-dump.py` (сырой дамп).

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
- `scale(series, factor)` — умножение значений на коэффициент (перевод, например, байт в мегабайты).
- `perSecond(series)` — производная счётчика (rate) для `derive`/`counter` метрик.
- `keepLastValue(series)` / `transformNull(series, 0)` — борьба с разрывами и `null`.
- `consolidateBy(series, 'max')` — выбор функции агрегации при даунсэмплинге (важно, чтобы графики не «сглаживали» пиковые значения).
- `timeShift(series, '-1d')` — наложение данных за предыдущий период для сравнения.

### Архитектура Collectd и плагины

Collectd собирает данные через **плагины чтения** (`LoadPlugin cpu`, `memory`, `interface`, `load`, `disk`, `df`) и отправляет через **плагины записи** (`write_graphite`, `write_prometheus`, `network`). Глобальный параметр `Interval` (по умолчанию `10s`) задаёт частоту опроса всех read-плагинов — он должен совпадать с первым (самым точным) уровнем retention в Whisper, иначе графики будут «broken» (см. раздел устранения неполадок).

Плагин `write_graphite` преобразует имена метрик Collectd в иерархию Graphite. Ключевые параметры:

- `StoreRates true` — значения типов `derive`/`counter` отправляются как **скорость** (rate), а не сырой нарастающий счётчик. Для счётчиков (например, сетевые байты) это почти всегда желаемое поведение; при `false` Grafana придётся применять `perSecond()` вручную.
- `AlwaysAppendDS false` — не добавлять имя data source (например, `.value`) к имени метрики.
- `EscapeCharacter "_"` — символ для экранирования точек и спецсимволов в именах хостов/плагинов.
- `Prefix "collectd."` — общий префикс, облегчающий политику хранения и фильтрацию.
- `LogSendErrors true` — логировать ошибки отправки (критично для диагностики).

## Практические сценарии

### Предварительные требования

Перед развёртыванием убедитесь, что выполнены следующие условия:

- **Docker + Docker Compose** на хосте Graphite (версия Docker ≥ 20.10, Compose v2). Для Grafana используется образ `grafana/grafana:13.x` (актуальная линейка 13.2.x); для Graphite — `graphiteapp/graphite-statsd:1.1.10-1`.
- **Сеть:** хост(ы) с Collectd должны иметь TCP/UDP-доступ к порту `2003` хоста, где опубликован Carbon. Между Collectd и Graphite не должно быть stateful-файервола, режущего долгие соединения.
- **Порты:** `8080` (Graphite-web UI/API), `2003` (Carbon Line TCP+UDP), `2004` (Pickle), `8125` (StatsD UDP), `3000` (Grafana) должны быть свободны на хосте или корректно проброшены.
- **Диск:** под Whisper требуется выделенный том (объём зависит от числа метрик × retentions; см. расчёт в разделе Whisper).
- **Collectd** на целевых хостах: пакет `collectd` (Debian/Ubuntu — `apt`, RHEL — `yum`/`dnf`). Версия Collectd ≥ 5.4 (для `write_graphite`).
- **Время:** на всех хостах должен быть синхронизирован NTP — Graphite и Collectd работают с абсолютными метками времени; расхождение часовых поясов и времени ломает графики.

### Развертывание стека через Docker Compose

Для быстрого развертывания используется официальный образ, объединяющий компоненты Graphite. Авторитетное руководство по запуску Grafana в Docker — [docker_compose_setup.md](./Installation/docker_compose_setup.md).

**Файл `docker-compose.yml`:**

```yaml
services:
  graphite:
    image: graphiteapp/graphite-statsd:1.1.10-1
    container_name: graphite
    restart: always
    ports:
      - "8080:80"       # Graphite Web UI / API
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

> **Внимание:** пароль `admin/admin` подходит только для локальной отладки. В проде задайте сильный пароль через секреты и ограничьте доступ к порту `3000` (см. раздел «Безопасность»).

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
# → 24/08/2026 12:00:00 :: carbon-cache (instances=1) started
```

### Настройка Collectd на целевом хосте

#### Установка

```bash
sudo apt update && sudo apt install collectd -y
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

Проверка конфигурации перед запуском (предотвращает ошибки парсинга):

```bash
collectd -T
# → вывод пустой при успехе, либо ошибка в конкретной строке
```

Перезапустите службу:

```bash
sudo systemctl restart collectd
sudo systemctl enable collectd
systemctl status collectd --no-pager | head -n 3
# → ● collectd.service - Statistics collection daemon
#      Active: active (running)
```

### Проверка сквозного конвейера (end-to-end)

После запуска Collectd и Graphite нужно убедиться, что данные реально дошли до Whisper и читаются Grafana.

1. **Статус агента Collectd** — ошибок отправки быть не должно:

```bash
journalctl -u collectd -n 20 --no-pager
# → ожидаем: отсутствие "write_graphite plugin: send failed" и прочих ошибок
```

2. **Отправка тестовой метрики** напрямую в Carbon (проверяет сеть и приёмник):

```bash
echo "collectd.test.metric 42 $(date +%s)" | nc -q1 127.0.0.1 2003
# → успех, если порт доступен (без вывода)
```

3. **Появление файла Whisper** — метрика должна материализоваться на диске:

```bash
docker exec graphite find /opt/graphite/storage/whisper -name 'collectd.*.wsp' | head
# → /opt/graphite/storage/whisper/collectd/test/metric.wsp
```

4. **Чтение через API Graphite-web** (проверяет хранение + отдачу):

```bash
curl -s "http://localhost:8080/render?target=collectd.*&format=json&from=-5min" | head -c 400
# → [{"target": "collectd.test.metric", "datapoints": [[42.0, 1692900000], ...]}]
```

5. **Проверка через Grafana API** (data source уже сконфигурирован, см. ниже):

```bash
curl -s -u admin:admin http://localhost:3000/api/datasources | head -c 300
# → [{"id":1,"name":"Graphite","type":"graphite", ...}]
```

### Настройка источника данных в Grafana

1. Войдите в Grafana (`http://localhost:3000`).
2. Перейдите в **Connections → Data sources**.
3. Нажмите **Add new data source** и выберите **Graphite**.
4. Укажите URL: `http://graphite:80`.
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

Проверка (StatD агрегирует и сбрасывает в Carbon раз в flush-интервал, по умолчанию 10s):

```bash
curl -s "http://localhost:8080/render?target=stats.*&format=json&from=-1min" | head -c 300
# → [{"target": "stats.orders.created", "datapoints": [[1.0, ...]]}]
```

## Дополнительная информация

### Управление хранением (Whisper)

#### Политики хранения (storage-schemas.conf)
Определяют точность и длительность хранения данных.
```ini
[collectd]
pattern = ^collectd\.
retentions = 10s:1d,1m:7d,10m:1y
# 10 сек точность на 1 день, 1 мин на 7 дней, 10 мин на 1 год
```

#### Агрегация данных (storage-aggregation.conf)
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
- `xFilesFactor`: минимальная доля заполненных данных для записи агрегата (0.5 = 50%).
- `aggregationMethod`: среднее (`average`), сумма (`sum`), минимум, максимум.

Применение изменений: файлы `storage-schemas.conf` и `storage-aggregation.conf` лежат в `/opt/graphite/conf` (в Docker — смонтированный том `graphite_conf`). После правки **новые** метрики используют новую схему автоматически; для уже существующих файлов `.wsp` схема не меняется сама — требуется `whisper-resize.py` или удаление старых файлов. Carbon перечитывает конфиг при `SIGHUP` (`docker kill -s HUP graphite`) либо перезапуске контейнера.

Оценка диска: для одной метрики с `retentions = 10s:1d,1m:7d,10m:1y` размер файла ≈ `8640*12 + 10080*24 + 52560*12` байт (по ~12 байт на точку) — десятки–сотни КБ. При тысячах метрик это быстро растёт до десятков ГБ, поэтому число метрик и глубину retention нужно планировать заранее.

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Нет данных в Grafana** | `Collectd` не может подключиться | Проверьте `journalctl -u collectd`. Убедитесь, что порт 2003 открыт. |
| **Пустые списки метрик** | Ошибка Carbon или права доступа | Проверьте логи: `docker logs graphite`. Проверьте директорию `/opt/graphite/storage/whisper`. |
| **"Broken" графики** | Несовпадение интервалов | Интервал `collectd` (Interval в конфиге) должен совпадать с первым уровнем retention. |
| **`send failed` в логах Collectd** | Carbon недоступен / не слушает 2003 | `docker logs graphite \| grep -i 'line receiver'`; проверьте, что порт `2003` проброшен и не занят. |
| **Отказ запуска Collectd** | Синтаксическая ошибка в конфиге | `collectd -T` покажет строку с ошибкой; исправьте и перезапустите. |
| **Permission denied при записи в Whisper** | Неверный владелец тома | В контейнере Whisper пишет пользователь `graphite` (uid 990/997). Проверьте права смонтированного `graphite_data`. |
| **Графики «сглажены», пиков не видно** | consolidation `average` на грубом архиве | В запросе добавьте `consolidateBy(series, 'max')` или уменьшите окно просмотра. |
| **Тегированные запросы пусты** | Graphite < 1.1.0 или теги не отправлялись | Убедитесь, что версия ≥ 1.1.0 и имена метрик содержат `;key=value`. |
| **Расхождение времени на графиках** | Разный часовой пояс / нет NTP | Graphite хранит UTC; выставьте часовой пояс в настройках дашборда Grafana, синхронизируйте NTP на хостах. |
| **Высокое потребление памяти carbon-cache** | Большой `MAX_CACHE_SIZE` | Ограничьте кэш в `/opt/graphite/conf/carbon.conf` (`MAX_CACHE_SIZE = 1000000`, `CACHE_TIMEOUT`). |

### Безопасность

- **Отсутствие аутентификации:** Протокол Carbon (порт 2003) не имеет встроенной проверки подлинности. Используйте сетевые экраны (firewall) для ограничения доступа.
- **Безопасность API:** Ограничьте доступ к порту 80 (Graphite-web), разрешив запросы только от IP-адреса Grafana.
- **Пароль Grafana:** не используйте `admin/admin` в проде; задайте надёжный пароль через переменные окружения/секреты и отключите публичную регистрацию (`GF_USERS_ALLOW_SIGN_UP=false`).
- **StatsD (8125):** принимет метрики от любого, кто имеет сетевой доступ — ограничьте порт на уровне хоста/сети, иначе возможен спам-инъекцией метрик.
- **Шифрование в пути:** для удалённых хостов Terminate TLS перед Graphite-web (reverse proxy) и используйте VPN/тоннель для порта 2003, так как Carbon передаёт данные в открытом виде.

### Рекомендации по эксплуатации

- **Фиксируйте версии** образов (`graphiteapp/graphite-statsd:1.1.10-1`, `grafana/grafana:13.x`) — обновления меняют поведение схем хранения и функций.
- **Выносите хранилище отдельным томом** (`graphite_data`) и регулярно бэкапьте каталог `whisper` (он является базой целиком).
- **Мониторьте сам Graphite:** Carbon отдаёт свои метрики (`carbon.agents.*`, `carbon.cache.*`), добавьте их в Grafana, чтобы видеть переполнение кэша и отставание записи.
- **Конфигурируйте data source через provisioning** (см. [grafana_provisioning.md](./grafana_provisioning.md)) вместо ручной настройки UI — воспроизводимость и контроль версий.
- **Кардинальность:** избегайте высококардинальных тегов (например, `user_id` в имени метрики) — Whisper плохо масштабируется на миллионы рядов; для этого нужен Prometheus/Mimir.
- **Очистка:** для вывода стека остановите контейнеры (`docker compose down`) и при необходимости удалите тома (`docker volume rm graphite_data graphite_conf grafana_data`); данные Whisper без бэкапа восстановлению не подлежат.

### Ограничения и особые случаи

- **Схема Whisper неизменяема «на лету»:** изменение `retentions` для уже существующей метрики требует `whisper-resize.py` или пересоздания файла; иначе новые точки пишутся по старой схеме.
- **Потеря данных при UDP:** отправка метрик по UDP (`Protocol "udp"`) не гарантирует доставку — при перегрузке сети точки теряются. Для надёжности используйте TCP.
- **Устаревание (legacy):** Graphite находится в режиме ограниченного сопровождения; новые возможности (теги, функции) появляются редко. Для зелёного поля используйте Prometheus + Mimir/Thanos.
- **Только агрегация по времени:** Graphite не умеет агрегировать по произвольным лейблам так же гибко, как PromQL; сложные запросы «по всем хостам с тегом X» ограничены моделью тегов 1.1.x.
- **Фиксированный размер файла:** предсказуемость диска оборачивается тем, что старые данные безвозвратно перезаписываются при даунсэмплинге — «детальную» историю вернуть нельзя.
- **Кардинальность:** Whisper плохо переносит миллионы уникальных имён метрик; при росте числа рядов переходите на Prometheus-совместимое хранилище.

### Миграция на современный стек

План перехода:
1. **Параллельный запуск:** Установите [Grafana Alloy](./grafana_alloy_overview.md).
2. **Сбор метрик:** Используйте в Alloy компонент `prometheus.exporter.unix`.
3. **Хранение:** Направьте Alloy в [Mimir](../Mimir/mimir_overview.md) или Prometheus.
4. **Конвертация:** Перепишите Graphite-запросы на PromQL.
5. **Вывод из эксплуатации:** Отключите Graphite после проверки данных.

Пример сопоставления запросов при миграции:

| Graphite | PromQL (Alloy → Mimir) |
| :--- | :--- |
| `sumSeries(collectd.*.cpu.usage.user)` | `sum(collectd_cpu_usage_user)` |
| `perSecond(collectd.*.interface.if_octets.rx)` | `rate(collectd_interface_if_octets_rx[1m])` |
| `aliasByNode(collectd.*.load.load, 1)` | `label_replace(collectd_load_load, "host", "$1", "instance", "(.+)")` |
| `movingAverage(series, "10min")` | `avg_over_time(series[10m])` |

> **Важно:** сами исторические данные Whisper в Prometheus/Mimir напрямую не переносятся (нет штатного импортёра Graphite→TSDB). Мигрируются дашборды, алерты и конвейер сбора; историю при необходимости оставляют рядом на只读 Graphite до истечения retention.

### Актуальность и статус

Стек Graphite + Collectd является **legacy**: проект Graphite развивается медленно (стабильная линейка 1.1.x, образ `1.1.10`), Collectd — зрелый, но не получает новых возможностей интеграций. Для новых систем единой рекомендацией остаётся Prometheus + Grafana Alloy + Mimir (см. раздел «Миграция»). Документ поддерживается для сопровождения существующих инсталляций; при обнаружении EOL официальных релизов добавляется предупреждение в начало файла (см. баннер выше).

### См. также

- [Источники данных Grafana](./grafana_datasources.md)
- [Grafana Alloy — обзор и миграция](./grafana_alloy_overview.md)
- [Mimir: хранение метрик](../Mimir/mimir_overview.md)
