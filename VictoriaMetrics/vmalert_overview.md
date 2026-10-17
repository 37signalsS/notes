# Обзор vmalert

**Актуально для:** VictoriaMetrics (vmalert) v1.154.0

## 1. Определения

**vmalert** — это высокопроизводительный компонент стека [VictoriaMetrics](./overview.md), предназначенный для выполнения правил алертинга и правил записи (recording rules). Он является полноценной заменой встроенного механизма правил Prometheus, полностью совместим с его синтаксисом и предлагает расширенные возможности масштабирования и интеграции.

`vmalert` лёгкий, не имеет внешних зависимостей и запускается как отдельный бинарник или контейнер (`victoriametrics/vmalert`).

## 2. Базовые концепции

`vmalert` периодически выполняет выражения, объявленные в **правилах** (`-rule`), против источника данных, заданного через `-datasource.url`. По результатам выполнения он отправляет оповещения в [Alertmanager](../Prometheus/alertmanager.md) (флаг `-notifier.url`) или записывает новые (агрегированные) метрики обратно через Remote Write (флаг `-remoteWrite.url`).

### Поддерживаемые источники данных и типы правил

Язык выражения `expr` определяется полем `type` на уровне группы правил (глобальный дефолт задаётся флагом `-rule.defaultRuleType`):

| Тип | Язык запросов | Источник данных |
| :--- | :--- | :--- |
| `prometheus` (default) | PromQL / MetricsQL | VictoriaMetrics (single/cluster), Prometheus и другие Prometheus-совместимые хранилища |
| `vlogs` | LogsQL | логи [VictoriaLogs](https://docs.victoriametrics.com/victorialogs/), трейсы [VictoriaTraces](https://docs.victoriametrics.com/victoriatraces/) |
| `graphite` | Graphite | Graphite-совместимые хранилища |

`vmalert` работает только с одним `-datasource.url`. Для одновременного использования метрик и логов используется [vmauth](https://docs.victoriametrics.com/vmauth/) с маршрутизацией запросов по пути (`/api/v1/query*` → VictoriaMetrics, `/select/logsql/*` → VictoriaLogs/VictoriaTraces).

### Параметры групп правил

Каждая группа правил поддерживает следующие параметры (часть наследуется из глобальных флагов `-rule.*` и `-evaluationInterval`):

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| `name` | Имя группы. Должно быть уникально в пределах файла. | — |
| `interval` | Как часто выполнять правила в группе. | `-evaluationInterval` |
| `eval_offset` | Смещение времени оценки в диапазоне `[0...interval]`. Позволяет выстраивать [цепочки групп](./vmalert_rules_management_with_manifests.md#chaining-групп-зависимости) (chaining groups) — когда результаты recording rules одной группы должны быть доступны для следующей. Поддерживает отрицательные значения (начиная с v1.113.0). | `0` |
| `eval_delay` | Корректировка параметра `time` для компенсации задержки данных от источника. По умолчанию наследуется из `-rule.evalDelay` (30s). Не применяется к группам с `eval_offset` (начиная с v1.102.0). | `-rule.evalDelay` |
| `limit` | Максимальное количество алертов или записей, которые одно правило в группе может произвести. При превышении правило помечается ошибкой, и все результаты отбрасываются. `0` — без ограничения (начиная с v1.96.0). | `-rule.resultsLimit` |
| `concurrency` | Количество правил, выполняемых одновременно внутри группы. Увеличение concurrency может ускорить оценку группы (измеряется через `vmalert_iteration_duration_seconds`). | `1` |
| `eval_alignment` | Выравнивание времени оценки на границу `interval` вместо фактического времени. Включено по умолчанию для предсказуемых результатов, совпадающих с графиками в Grafana/vmui (начиная с v1.95). | `true` |
| `type` | Переопределяет тип expression для всех правил в группе (`prometheus`, `vlogs`, `graphite`). | `-rule.defaultRuleType` |
| `params` | HTTP-параметры URL, применяемые к запросам к datasource для всех правил в группе. | — |
| `headers` | HTTP-заголовки, применяемые к запросам к datasource. Имеют приоритет над `-datasource.headers`. | — |
| `notifier_headers` | HTTP-заголовки, применяемые к уведомлениям, отправляемым notifiers. Имеют приоритет над заголовками в notifier config. | — |
| `labels` | Метки, добавляемые к каждому правилу в группе. Имеют приоритет над внешними метками (`-external.label`). | — |
| `debug` | Включить debug-логирование для всех правил в группе (начиная с v1.117.0). | `false` |

### Ключевые функции

- **Выполнение правил алертинга** — запрашивает данные из источника, оценивает условия и генерирует алерты. Поддерживает сложные условия благодаря MetricsQL/LogsQL.
- **Выполнение правил записи (recording rules)** — позволяет предварительно вычислять сложные запросы и сохранять их как новые метрики. Это критично для ускорения тяжёлых дашбордов в Grafana и для агрегации данных с высокой точностью из хранилища с коротким сроком хранения в долгосрочное хранилище.
- **Интеграция с VictoriaLogs и VictoriaTraces** — поддержка алертинга на основе логов (LogsQL, `type: vlogs`) с версии `v1.106.0` также работает с трейсами VictoriaTraces.
- **Сохранение состояния (Stateful Alerting)** — `vmalert` может сохранять состояние алертов (Pending/Firing) в удалённое хранилище через Remote Write. Это позволяет не терять историю алертов при перезапуске компонента.
- **Поддержка множества источников и нотификаторов** — может работать с несколькими источниками данных (через vmauth) и отправлять уведомления в несколько кластеров Alertmanager (несколько флагов `-notifier.url` или через [конфигурационный файл нотификатора](#notifier-configuration-file)).
- **Шаблонизация аннотаций** — расширенная поддержка Go-templates с дополнительными функциями (`now`, `query`, `label`, `humanize`, `toTime`, `parseDuration`, `parseDurationTime`, `formatTime` и т. д.). Поддерживаются [переиспользуемые шаблоны](https://docs.victoriametrics.com/victoriametrics/vmalert/#reusable-templates) через флаг `-rule.templates`.
- **Relabeling** — поддержка переименования и фильтрации меток (labels) как для алертов перед отправкой, так и для записываемых метрик.
- **Hot reload** — обновление конфигурации без простоя через сигнал SIGHUP или HTTP-эндпоинт `/-/reload` (может быть защищён флагом `-reloadAuthKey`).
- **Гибкая загрузка правил** — `-rule` принимает пути, wildcard-шаблоны, рекурсивные маски, HTTP URL; для Enterprise-версии дополнительно доступны S3 и GCS.
- **Валидация** — дубликаты правил (одинаковые `name` + `expr` + labels в одной группе) запрещены; проверка синтаксиса выполняется через `vmalert-tool unittest`.
- **Определение never-firing алертов** — начиная с v1.91.0, `vmalert` может обнаружить правила, чьи выражения не совпадают ни с одной временной серией в runtime (метрика `vmalert_alerting_rules_last_evaluation_series_fetched`).

### Отличие от Alertmanager

Важно понимать различие в ролях:

| Компонент | Назначение | Пример |
| :--- | :--- | :--- |
| **`vmalert`** | **Генерирует** алерты (логика "когда бить тревогу"): выполняет запросы к БД, оценивает условия и формирует алерты | `IF rate(errors) > 5 THEN fire alert` |
| **`Alertmanager`** | **Обрабатывает** алерты (маршрутизация, дедупликация, группировка, нотификации) | Группировка 100 алертов в одно письмо в Slack |

`vmalert` — это "движок" выполнения логики, который делает запросы к БД, в то время как Alertmanager — система управления уведомлениями. Зоны ответственности не пересекаются.

### Ограничения

- Выполнение правил внутри группы происходит **последовательно** (по умолчанию `concurrency: 1`), но запись результатов в удалённое хранилище — **асинхронно**. Поэтому в рекурсивных сценариях, когда результат одного recording rule переиспользуется в следующем, полагаться на цепочку нельзя — используйте механизм **chaining groups** (группы с `eval_offset`) либо перестраивайте запросы.
- Выполнение запросов к источнику идёт по сети, поэтому существует риск сетевых сбоев — пороговые значения срабатываний следует проектировать с учётом возможных ошибок запросов.
- Для корректного backfilling правил с *кастомным* time filter (LogsQL) поддержка ещё не реализована.
- Replay (backfill) поддерживает только тип datasource `prometheus`. Graphite engine не поддерживается. Функция `query` в шаблонах отключена в replay-режиме.
- Для записи состояния алертов (`-remoteWrite.url`) и `-remoteRead.url` должно быть **одновременно** настроено оба флага.

## 3. Практические сценарии

### Пример конфигурации правил алертинга

Файл правил `alert-rules.yaml`:

```yaml
groups:
  - name: node-alerts
    interval: 30s  # Как часто выполнять правила
    rules:
      - alert: HighCpuUsage
        expr: 100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 85
        for: 5m
        labels:
          severity: warning
          team: infrastructure
        annotations:
          summary: "High CPU usage on {{ $labels.instance }}"
          description: "CPU usage is above 85% for more than 5 minutes on {{ $labels.instance }}. Current value: {{ $value }}%"

      - alert: HighMemoryUsage
        expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100 > 90
        for: 5m
        keep_firing_for: 30m  # Продолжать fires после разрешения на 30 минут
        labels:
          severity: critical
        annotations:
          summary: "High memory usage on {{ $labels.instance }}"
          description: "Memory usage is above 90% for more than 5 minutes. Current value: {{ $value }}%"

      - alert: DiskSpaceLow
        expr: (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100 < 10
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Low disk space on {{ $labels.instance }}"
          description: "Disk space is below 10% on {{ $labels.instance }}. Current value: {{ $value }}%"
```

> Примечание: для каждого правила в `expr` используется MetricsQL/PromQL, `for` задаёт минимальную длительность непрерывного отклонения для перехода в состояние Firing, `keep_firing_for` задерживает разрешение алерта после возврата в норму, а `annotations` поддерживают Go-шаблоны (`$labels`, `$value`, функции `printf`, `humanize`, `query` и др.).

### Пример алертинга на основе логов (VictoriaLogs)

Для правил на основе LogsQL на **уровне группы** обязательно указать `type: vlogs`, иначе выражение будет проверено как PromQL и не запустится. Правило срабатывает, когда в логах сервиса `auth` за 5 минут на одном поде появилось более 10 ошибок:

```yaml
groups:
  - name: log-alerts
    type: vlogs  # Обязательно для LogsQL
    interval: 1m
    rules:
      - alert: AuthServiceHighErrorRate
        expr: '{env=prod} status:in(error,warn) | stats by (k8s.pod.name) count() | filter count:>10'
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate in logs for {{ index $labels "k8s.pod.name" }}"
          description: "Found more than 10 errors in auth service logs within last 5 minutes."
```

В LogsQL-выражениях (`type: vlogs`) обязательно наличие `stats pipe` для агрегации и `filter pipe`, чтобы отфильтровать результат по порогу. По умолчанию `vmalert` сам добавляет ко времени фильтр `_time: <group_interval>` — указывать его в выражении не нужно (можно для переопределения). См. также [Alerting with Logs](https://docs.victoriametrics.com/victorialogs/vmalert/).

### Пример правил записи (recording rules)

Recording rules полезны для предварительного вычисления сложных запросов:

```yaml
groups:
  - name: rec
    interval: 1m
    rules:
      # Предварительный расчет среднего CPU usage по кластеру (MetricsQL)
      - record: cluster:node_cpu:avg_rate5m
        expr: avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))
      # Расчет процента использования памяти
      - record: node:memory_usage_percent:ratio
        expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100
```

### Replay API: Пересчёт исторических данных

Уникальная функция `vmalert` — **backfilling (aka replay)**: позволяет выполнить правила на исторических данных. Это полезно, если вы создали новое правило записи и хотите заполнить историю метрики за прошлый месяц.

Запуск отдельного процесса пересчёта:

```bash
vmalert -rule=rules.yaml \
  -replay.timeFrom=2024-01-01T00:00:00Z \
  -replay.timeTo=2024-01-31T23:59:59Z \
  -datasource.url=http://victoriametrics:8428 \
  -remoteWrite.url=http://victoriametrics:8428
```

Дополнительные флаги replay:

| Флаг | Описание |
| :--- | :--- |
| `-replay.maxDatapointsPerQuery` | Максимальное количество точек данных на один запрос. Влияет на максимальный диапазон времени для одного `/query_range` запроса. |
| `-replay.ruleRetryAttempts` | Количество попыток повторного выполнения правила при ошибке datasource перед сдачей. |
| `-replay.rulesDelay` | Задержка между последовательным выполнением правил. Важна для цепочек правил. Должна быть >= `-remoteWrite.flushInterval`. При `=0` правила в группе выполняются параллельно согласно `concurrency`. |
| `-replay.ruleEvaluationConcurrency` | Максимальное количество одновременных `/query_range` запросов при replay recording/alerting rules с `for=0`. По умолчанию `1`. |
| `-replay.disableProgressBar` | Отключить прогресс-бар. Может генерировать много лог-записей, не в стандартном формате логгера. |

> **Важно:** vmalert автоматически отправляет `nocache=1` параметр для предотвращения загрязнения кэша и нежелательной корректировки границ временного диапазона во время backfilling.

Ограничения backfill:
- Не поддерживается для правил с кастомным time filter в LogsQL (и добавить её невозможно — см. выше).
- Не поддерживается Graphite engine.
- Функция `query` в шаблонах отключена.
- `limit` группы не влияет на replay.
- `keep_firing_for` не применяется во время replay.
- При backfill результат складывается с уже существующими данными.
- В replay-режиме группы выполняются последовательно в определённом порядке. Внутри каждой группы правила также выполняются последовательно, независимо от `concurrency`.

### Пример запуска vmalert

#### Локальный запуск (с сохранением состояния)

```bash
vmalert \
  -datasource.url=http://localhost:8428 \
  -notifier.url=http://localhost:9093 \
  -remoteWrite.url=http://localhost:8428 \
  -remoteRead.url=http://localhost:8428 \
  -rule=/path/to/rules/*.yaml
```
*Флаг `-remoteWrite.url` включает сохранение состояния алертов в саму VictoriaMetrics.*

#### HA vmalert

Для высокой доступности запустите несколько одинаково настроенных `vmalert` инстансов. Все они будут выполнять одни и те же правила, сохранять состояние и результаты в те же destinations, и отправлять алерты на все сконфигурированные Alertmanager.

```bash
vmalert \
  -rule=rules.yml \
  -datasource.url=http://victoriametrics:8428 \
  -remoteWrite.url=http://victoriametrics:8428 \
  -remoteRead.url=http://victoriametrics:8428 \
  -notifier.url=http://alertmanager1:9093 \
  -notifier.url=http://alertmanagerN:9093
```

Для избежания дублирования результатов recording rules и состояния алертов в VictoriaMetrics настройте [deduplication](https://docs.victoriametrics.com/victoriametrics/single-server-victoriametrics/#deduplication):

```bash
# Флаг устанавливается на стороне VictoriaMetrics (vmstorage/vmselect/vmsingle)
-dedup.minScrapeInterval=30s  # Должен быть равен -evaluationInterval vmalert
```

Если группы правил имеют разные `interval`, установите `-dedup.minScrapeInterval` равным наибольшему значению `interval`.

> **Важно:** каждому инстансу `vmalert` в HA-конфигурации задаётся уникальный `-external.label` (например, `replica=instance-1`), чтобы логирование и отправка уведомлений не дублировались. Если метка результата правила конфликтует с `-external.label`, `vmalert` автоматически переименовывает конфликтующую метку с префиксом `exported_`.

#### Деплой на bare-metal (systemd)

Для production-эксплуатации на физических серверах или VM без оркестратора:

```bash
# Создание пользователя и директорий
sudo useradd --system --no-create-home --shell /usr/sbin/nologin vmalert
sudo mkdir -p /etc/vmalert /var/lib/vmalert /var/log/vmalert
sudo chown -R vmalert:vmalert /etc/vmalert /var/lib/vmalert /var/log/vmalert
```

Скачайте бинарный файл:

```bash
VL_VERSION="v1.154.0"
wget -O /tmp/vmalert.tar.gz \
  "https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/${VL_VERSION}/vmalert-${VL_VERSION}-linux-amd64.tar.gz"
sudo tar -xzf /tmp/vmalert.tar.gz -C /usr/local/bin/
sudo chmod +x /usr/local/bin/vmalert
```

Файл `/etc/systemd/system/vmalert.service`:

```ini
[Unit]
Description=VictoriaMetrics Alert
Documentation=https://docs.victoriametrics.com/vmalert/
After=network.target

[Service]
User=vmalert
Group=vmalert
Type=simple
ExecStart=/usr/local/bin/vmalert \
  -datasource.url=http://localhost:8428 \
  -notifier.url=http://localhost:9093 \
  -remoteWrite.url=http://localhost:8428 \
  -remoteRead.url=http://localhost:8428 \
  -rule=/etc/vmalert/rules/*.yaml \
  -httpListenAddr=:8880 \
  -loggerTimezone=UTC \
  -remoteWrite.maxQueueSize=10000 \
  -datasource.queryTimeout=1m
Restart=always
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

Активация и запуск:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vmalert
sudo systemctl status vmalert
# → active (running)
```

Проверка:

```bash
# Проверка health endpoint
curl -s http://localhost:8880/-/healthy
# → OK

# Проверка правил
curl -s http://localhost:8880/api/v1/rules | jq '.data.groups[].name'
# → "node-alerts"
```

#### Контейнер (Docker)

```bash
docker run -d --name vmalert \
  --memory=4g \
  --cpus=4 \
  --ulimit nofile=65535:65535 \
  -p 8880:8880 \
  -v /etc/vmalert/rules:/rules \
  victoriametrics/vmalert:v1.154.0 \
  -datasource.url=http://victoriametrics:8428 \
  -notifier.url=http://alertmanager:9093 \
  -remoteWrite.url=http://victoriametrics:8428 \
  -remoteRead.url=http://victoriametrics:8428 \
  -rule=/rules/*.yaml
```

#### Kubernetes (фрагмент Deployment)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vmalert
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: vmalert
          # Рекомендуется использовать LTS версию или последнюю стабильную
          image: victoriametrics/vmalert:v1.154.0
          args:
            - -datasource.url=http://vmstorage.monitoring.svc:8428
            - -notifier.url=http://alertmanager.monitoring.svc:9093
            - -remoteWrite.url=http://vmstorage.monitoring.svc:8428
            - -remoteRead.url=http://vmstorage.monitoring.svc:8428
            - -rule=/config/rules/*.yaml
            - -httpListenAddr=:8080
            - -external.label=replica=$(POD_NAME)  # чтобы отличать инстансы при HA
          ports:
            - containerPort: 8080
              name: http
```

При запуске нескольких реплик `vmalert` (HA) каждому инстансу задаётся уникальный `-external.label` (например, `replica=instance-1`), чтобы логирование и отправка уведомлений не дублировались.

#### Топология: несколько remote writes

Для записи результатов правил в несколько destinations используйте [vmagent](https://docs.victoriametrics.com/victoriametrics/vmagent/) как fan-out proxy. `vmalert` настраивается на запись в `vmagent`, а `vmagent` — на рассылку во все destinations. Это также обеспечивает [data persisting при недоступности хранилища](https://docs.victoriametrics.com/victoriametrics/vmagent/#replication-and-high-availability).

### Сохранение и восстановление состояния алертов

Каждый процесс `vmalert` хранит состояние алертов в памяти. Для восстановления при рестарте используются два флага:

- `-remoteWrite.url` — URL, куда сохраняется состояние в виде временных серий `ALERTS` и `ALERTS_FOR_STATE` через Remote Write;
- `-remoteRead.url` — URL (MetricsQL-совместимый, VictoriaMetrics или vmselect), откуда при старте восстанавливается состояние по серии `ALERTS_FOR_STATE`.

Восстановление происходит **только один раз при старте** (не при hot reload). Если серии отсутствуют, не обновлялись дольше `-remoteRead.lookback` (по умолчанию 1 час) или не соответствуют текущей конфигурации правил — восстановление не выполнится. Успешно восстановленные правила помечаются меткой `restored` в веб-UI.

### Управление конфигурацией

#### Hot reload

`vmalert` поддерживает «горячее» обновление конфигурации без перезапуска:

- сигнал `SIGHUP` процессу `vmalert`;
- GET-запрос к эндпоинту `/-/reload` (может быть защищён флагом `-reloadAuthKey`);
- флаг `-configCheckInterval` для периодической проверки изменений конфигурации.

При reload `vmalert` перечитывает конфигурацию, заданную флагами `-rule`, `-rule.templates` и `-notifier.config`. Если конфигурация изменилась — обновляет внутренние состояния, логирует событие, устанавливает `vmalert_config_last_reload_successful=1`. Если загрузка или парсинг не удался — логирует ошибку, устанавливает `vmalert_config_last_reload_successful=0` и продолжает работу с предыдущей конфигурацией.

#### Notifier configuration file

Дополнительно к флагу `-notifier.url` можно настроить notifiers через конфигурационный файл (`-notifier.config`). Файл поддерживает:

- **static_configs** — статический список URL нотификаторов;
- **consul_sd_configs** — discovery через [Consul](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#consul_sd_config);
- **dns_sd_configs** — discovery через [DNS](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#dns_sd_config).

Пример `notifier.yaml`:

```yaml
static_configs:
  - targets:
      - 'http://alertmanager:9093/test/api/v2/alerts'
      - 'https://alertmanager:9093/api/v2/alerts'
      - localhost:9093

consul_sd_configs:
  - server: localhost:8500
    services:
      - alertmanager

dns_sd_configs:
  - names:
      - my.domain.com
    type: 'A'
    port: 9093
```

Список сконфигурированных или обнаруженных нотификаторов доступен через [веб-UI](#веб-эндпоинты) и эндпоинт `/api/v1/notifiers`. Если Alertmanager работает в cluster mode, все его URL должны быть доступны во время discovery для обеспечения [high availability](https://github.com/prometheus/alertmanager#high-availability).

#### Переиспользуемые шаблоны

Для переиспользования шаблонов в аннотациях используйте флаг `-rule.templates` (поддерживает wildcard):

```bash
vmalert -rule.templates=/etc/vmalert/templates/*.tmpl
```

## 4. Требования к окружению

### Операционная система

`vmalert` доступен для Linux (amd64, arm64) и macOS (amd64). Для production эксплуатации рекомендуется Linux-based ОС с актуальным LTS-ядром.

### Аппаратные требования

| Сценарий | CPU | RAM | Диск | Сеть |
| :--- | :--- | :--- | :--- | :--- |
| **Малая нагрузка** (< 5000 активных алертов, < 50 recording rules) | 2 ядра | 2 GB | 20 GB SSD | 10 MB/s |
| **Средняя нагрузка** (5K–50K алертов, 50–500 recording rules) | 4–8 ядер | 4–8 GB | 50 GB SSD | 50 MB/s |
| **Высокая нагрузка** (> 50K алертов, сложный MetricsQL) | 8+ ядер | 8+ GB | 100+ GB SSD | 100+ MB/s |

Для HA-развёртывания с несколькими репликами ресурсы умножаются на количество реплик.

### Программные зависимости

- Для запуска бинарного файла: никаких внешних зависимостей не требуется.
- Для контейнеризации: Docker, Podman или containerd.
- Для интеграции с Alertmanager: работающий инстанс Alertmanager (порт `9093`).
- Для хранения состояния: VictoriaMetrics (single/cluster) с поддержкой Remote Write/Read.
- Для enterprise-функций (mTLS, object storage rules, clusterMode): Enterprise-бинарник с [лицензией](https://docs.victoriametrics.com/victoriametrics/enterprise/).

### Сетевые порты

| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| `8880` | HTTP | Веб-UI, `/api/v1/rules`, `/api/v1/alerts`, `/-/reload` |
| `9093` | HTTP | Alertmanager (внешний) |
| `8428` | HTTP | VictoriaMetrics (datasource, remote write/read) |

### Хранение

- **Тип диска:** SSD или NVMe рекомендуется для production.
- **Размер:** Зависит от количества правил и интервала оценки. Состояние алертов (`ALERTS_FOR_STATE`) хранится в VictoriaMetrics, поэтому учтите её retention.
- **Ротация логов:** логи `vmalert` могут занимать десятки MB в день — настройте ротацию через `logrotate`.

## 5. Валидация установки

### Health checks

```bash
# Проверка доступности HTTP-эндпоинта
curl -s http://localhost:8880/-/healthy
# → OK

# Проверка readiness
curl -s http://localhost:8880/-/ready
# → OK

# Проверка конфигурации reload
curl -s http://localhost:8880/metrics | grep vmalert_config_last_reload_successful
# → vmalert_config_last_reload_successful 1

# Проверка метрик самомониторинга (vmalert скрещивается vmagent/Prometheus)
# Метрика up{job="vmalert"} означает, что процесс доступен для скрейпа
curl -s "http://vmagent:8420/api/v1/query?query=up{job=\"vmalert\"}" | jq '.data.result[0].value[1]'
# → "1"
```

### Верификация данных

```bash
# Проверить, что правила загружены
curl -s http://localhost:8880/api/v1/rules | jq '.data.groups[].name'
# → "node-alerts"

# Проверить, что запросы выполняются (в логах)
journalctl -u vmalert -f | grep "successfully evaluated rule group"
# → ... successfully evaluated rule group "node-alerts" ...
```

## 6. Операции и команды

### Веб-эндпоинты

`vmalert` запускает веб-сервер (по умолчанию на порту **`8880`**, переопределяется через `-httpListenAddr`). Интеграция с `vmui` двухсторонняя: вкладка Alerting в vmui появляется, когда vmsingle/vmselect настроен флагом `-vmalert.proxyURL=http://vmalert:8880` (проксирование `/api/v1/rules` и т.п. — см. [vmui_overview.md](./vmui_overview.md)); ссылки из алертов на графики vmui строятся флагами vmalert `-external.url` и `-external.alert.source`.

| Эндпоинт | Назначение |
| :--- | :--- |
| `http://<vmalert-addr>` | Веб-UI |
| `http://<vmalert-addr>/api/v1/rules` | Список групп правил и их состояние. Поддерживает параметры `datasource_type`, `search`, `group_limit`, `page_num`. |
| `http://<vmalert-addr>/api/v1/alerts` | Список активных алертов (Firing/Pending) с метками. Поддерживает параметры `datasource_type`, `rule_group[]`, `file[]`, `match[]`. |
| `http://<vmalert-addr>/api/v1/notifiers` | Список всех доступных нотификаторов |
| `http://<vmalert-addr>/vmalert/rule` | Страница правил в веб-UI |
| `http://<vmalert-addr>/vmalert/alert` | Страница алертов в веб-UI |
| `http://<vmalert-addr>/vmalert/api/v1/rule?group_id=<id>` | Статус правила в JSON |
| `http://<vmalert-addr>/vmalert/api/v1/alert?group_id=<id>&alert_id=<id>` | Статус алерта в JSON |
| `http://<vmalert-addr>/vmalert/api/v1/group?group_id=<id>` | Статус группы в JSON (используется как источник в AlertManager) |
| `http://<vmalert-addr>/metrics` | Внутренние метрики компонента (формат Prometheus) |
| `http://<vmalert-addr>/-/reload` | «Горячее» обновление конфигурации без рестарта |
| `http://<vmalert-addr>/-/healthy` | Health check |
| `http://<vmalert-addr>/-/ready` | Readiness check |
| `http://<vmalert-addr>/debug/pprof/heap` | Memory profile (сбор через `curl .../heap > mem.pprof`) |
| `http://<vmalert-addr>/debug/pprof/profile` | CPU profile (ждёт 30s перед возвратом) |

### Ключевые флаги

| Флаг | Описание | Рекомендация |
| :--- | :--- | :--- |
| `-datasource.url` | URL источника метрик (VictoriaMetrics, vmselect, Prometheus) | Обязательно |
| `-notifier.url` | URL Alertmanager (можно указывать несколько для HA) | Обязательно для alerting rules |
| `-remoteWrite.url` | URL для записи состояния алертов и recording rules | Обязательно для recording rules и state persistence |
| `-remoteRead.url` | URL для восстановления состояния алертов при старте | Обязательно для state recovery |
| `-rule` | Путь, wildcard или HTTP URL к файлам правил (S3/GCS в Enterprise) | Обязательно |
| `-evaluationInterval` | Глобальный интервал оценки правил | `30s` для метрик, `1m`–`5m` для логов |
| `-datasource.queryTimeout` | Таймаут запросов к источнику | `30s`–`1m` для сложных запросов |
| `-datasource.queryStep` | Шаг (`step`) для instant query. Должен быть ≥2× разрешения серии | `5m` по умолчанию |
| `-rule.evalDelay` | Задержка `time` для компенсации задержки данных (должна ≈ `-search.latencyOffset` в VictoriaMetrics) | `30s` по умолчанию |
| `-remoteWrite.maxQueueSize` | Размер очереди Remote Write | `10000` (по умолчанию) |
| `-remoteWrite.maxBatchSize` | Размер батча для Remote Write | `1000`–`5000` |
| `-remoteWrite.concurrency` | Количество одновременных запросов Remote Write | — |
| `-remoteWrite.flushInterval` | Интервал flush для Remote Write | Должен быть ≤ `-replay.rulesDelay` при backfill |
| `-httpListenAddr` | Адрес HTTP-сервера | `:8880` (изменить при конфликте) |
| `-httpAuth.username` / `-httpAuth.password` | Basic Auth для HTTP-порта | — |
| `-reloadAuthKey` | Auth key для эндпоинта `/-/reload` | Защита hot reload |
| `-configCheckInterval` | Интервал периодической проверки изменений конфигурации | Альтернатива file-наблюдателю |
| `-rule.stripFilePath` (v1.143.0) | Удаление путей к файлам правил из логов/UI/метрик | Включить в production |
| `-external.label` | Внешние метки (например, `replica=a` для HA) | Обязательно для HA |
| `-external.url` | Внешний URL для генерации ссылок на алерты | — |
| `-external.alert.source` | Шаблон ссылки на источник алерта | — |
| `-rule.templates` | Пути к файлам переиспользуемых шаблонов | Для сложных анотаций |
| `-rule.defaultRuleType` | Тип правил по умолчанию (`prometheus`, `vlogs`, `graphite`) | — |
| `-datasource.appendTypePrefix` | Добавлять префикс пути на основе типа datasource | Для смешанных Graphite+Prometheus |

## 7. Безопасность

### Аутентификация и авторизация

`vmalert` поддерживает базовую аутентификацию своего HTTP-порта (`-httpAuth.username`/`-httpAuth.password`) и TLS (`-tls*`, `-mtls` в Enterprise) — этого недостаточно для разграничения прав. Для полноценной авторизации используйте один из подходов:

1. **vmauth** — прокси входит в стек VictoriaMetrics, поддерживает Basic Auth, JWT, OIDC и ACL по путям запроса.
2. **Обратный прокси (Nginx/Traefik)** — TLS-терминация и Basic Auth перед `vmalert`.
3. **Firewall** — ограничьте доступ к порту `8880` только адресами систем мониторинга и bastion-хостов.

Пример Nginx-конфигурации:

```nginx
server {
    listen 8443 ssl;
    server_name vmalert.internal;

    ssl_certificate     /etc/nginx/tls/vmalert.crt;
    ssl_certificate_key /etc/nginx/tls/vmalert.key;

    location / {
        auth_basic "VictoriaMetrics Alert";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://127.0.0.1:8880;
        proxy_set_header Host $host;
    }
}
```

### Шифрование трафика

- **Источник данных (`-datasource.url`):** используйте `https://` и настраивайте доверенные сертификаты. Для самоподписанных сертификатов используйте флаг `-datasource.tlsInsecureSkipVerify` (только для тестовых сред).
- **Remote Write/Read:** по умолчанию поддерживает TLS при использовании `https://` URL.
- **Alertmanager (`-notifier.url`):** если Alertmanager имеет TLS, используйте `https://` и соответствующие флаги.
- **mTLS (Enterprise):** флаги `-tls` и `-mtls` включают взаимную TLS-аутентификацию для входящих запросов на `-httpListenAddr`. Сертификаты проверяются через системный TLS Root CA или `-mtlsCAFile`.

### Аудит и самомониторинг

Включите аудит запросов к источнику данных через логи VictoriaMetrics/vmselect. Для самомониторинга `vmalert` используйте рекомендованные [alert rules от команды VictoriaMetrics](https://github.com/VictoriaMetrics/VictoriaMetrics/blob/master/deployment/docker/rules/alerts-vmalert.yml):

```bash
# Скопировать официальные алерты для vmalert
curl -sL https://raw.githubusercontent.com/VictoriaMetrics/VictoriaMetrics/master/deployment/docker/rules/alerts-vmalert.yml
```

Ключевые метрики для мониторинга:

| Метрика | Описание | Порог |
| :--- | :--- | :--- |
| `up{job="vmalert"}` | Доступен ли процесс | `== 0` → процесс недоступен |
| `vmalert_config_last_reload_successful` | Успешность последней hot-reload конфигурации | `!= 1` → reload провален |
| `vmalert_alerting_rules_errors_total` | Ошибки выполнения alerting rules | `increase(...[5m]) > 0` |
| `vmalert_recording_rules_errors_total` | Ошибки выполнения recording rules | `increase(...[5m]) > 0` |
| `vmalert_remotewrite_errors_total` | Ошибки записи в remote storage | `increase(...[5m]) > 0` |
| `vmalert_alerts_send_errors_total` | Ошибки отправки в Alertmanager | `increase(...[5m]) > 0` |
| `vmalert_iteration_missed_total` | Пропущенные итерации оценки | `increase(...[5m]) > 0` |
| `vmalert_iteration_reset_total` | Сбросы итераций (clock drift) | `increase(...[5m]) > 0` |
| `vmalert_remotewrite_dropped_rows_total` | Отброшенные записи в remote write | `increase(...[5m]) > 0` |
| `vmalert_alerting_rules_last_evaluation_series_fetched` | Количество series, совпадающих с выражением | `== 0` → never-firing alert |
| `vmalert_rule_group_last_duration_seconds` | Время выполнения группы правил | сравнить с `interval` |

## 8. Процедура обновления и отката

### Обновление бинарного файла (bare-metal)

```bash
# 1. Остановка сервиса
sudo systemctl stop vmalert

# 2. Бэкап конфигурации
sudo cp -r /etc/vmalert /etc/vmalert.bak.$(date +%Y%m%d)

# 3. Загрузка новой версии
VL_NEW="v1.154.0"
wget -O /tmp/vmalert.tar.gz \
  "https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/${VL_NEW}/vmalert-${VL_NEW}-linux-amd64.tar.gz"
sudo tar -xzf /tmp/vmalert.tar.gz -C /usr/local/bin/
sudo chmod +x /usr/local/bin/vmalert

# 4. Валидация конфигурации (если доступен vmalert-tool)
vmalert-tool unittest --files=/etc/vmalert/rules/*.yaml
# → SUCCESS

# 5. Запуск
sudo systemctl start vmalert
sudo systemctl status vmalert
# → active (running)

# 6. Проверка reload конфигурации
curl -s http://localhost:8880/metrics | grep vmalert_config_last_reload_successful
# → vmalert_config_last_reload_successful 1
```

### Откат

При проблемах с новой версией:

```bash
# 1. Остановка
sudo systemctl stop vmalert

# 2. Возврат предыдущей версии (если сохранили бин)
sudo cp /usr/local/bin/vmalert /usr/local/bin/vmalert.new
sudo cp /path/to/previous/vmalert /usr/local/bin/vmalert

# 3. Или восстановление конфигурации
sudo rm -rf /etc/vmalert
sudo cp -r /etc/vmalert.bak.20260920 /etc/vmalert

# 4. Запуск
sudo systemctl start vmalert
```

### Обновление в Docker

```bash
# 1. Остановка старого контейнера
docker stop vmalert && docker rm vmalert

# 2. Загрузка нового образа
docker pull victoriametrics/vmalert:v1.154.0

# 3. Запуск с той же конфигурацией
docker run -d --name vmalert \
  -p 8880:8880 \
  -v /etc/vmalert/rules:/rules \
  victoriametrics/vmalert:v1.154.0 \
  -datasource.url=http://victoriametrics:8428 \
  -notifier.url=http://alertmanager:9093 \
  -remoteWrite.url=http://victoriametrics:8428 \
  -remoteRead.url=http://victoriametrics:8428 \
  -rule=/rules/*.yaml
```

### Проверка после обновления

```bash
# Проверка версии через метрики
curl -s http://localhost:8880/metrics | grep vmalert_build_info
# → vmalert_build_info{version="v1.154.0",...} 1

# Проверка загрузки правил
curl -s http://localhost:8880/api/v1/rules | jq '.data.groups | length'

# Проверка active alerts
curl -s http://localhost:8880/api/v1/alerts | jq '.data.alerts | length'
```

## 9. Отладка и устранение неисполнимостей

### Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Правила не отображаются в UI | `-rule` указывает на неверный путь | Проверить `ls /etc/vmalert/rules/*.yaml` и права доступа |
| Ошибка в MetricsQL/LogsQL | Синтаксическая ошибка или неверный `type` группы | Убедиться в `type: vlogs` для LogsQL; запустить `vmalert-tool unittest` |
| LogsQL-правило молчит | Пропущен `stats`-пайп или `filter`-пайп в `expr` | Добавить обязательные пайпы; проверить time filter |
| Запрос зависает | Слишком сложный запрос или таймаут | Увеличить `-datasource.queryTimeout` или упростить expr |
| Восстановление состояния не сработало | Серия `ALERTS_FOR_STATE` устарела | Настроить `-remoteRead.lookback` (по умолчанию 1h) |
| Дубли уведомлений | Несколько реплик без `-external.label` | Задать уникальный label для каждого инстанса |
| `/-/reload` возвращает 401 | Защищён флагом `-reloadAuthKey` | Добавить `?authKey=<key>` к запросу или убрать флаг |
| Алерты не доставляются в Alertmanager | Alertmanager недоступен или неверный URL | Проверить `-notifier.url` и доступность Alertmanager |
| `result contains metrics with the same labelset` | Коллизия time series (например, `__name__` в `expr`) | Использовать [label_replace](https://docs.victoriametrics.com/victoriametrics/metricsql/#label_replace) для устранения конфликтов |

### Общие рекомендации (Common mistakes)

- **Интервал ≥ разрешения серии:** всегда задавайте `interval` группы **≥** [разрешения временных серий](https://docs.victoriametrics.com/victoriametrics/keyconcepts/#time-series-resolution) datasource.
- **Step и data delay:** `vmalert` выполняет [instant queries](https://docs.victoriametrics.com/victoriametrics/keyconcepts/#instant-query) с параметром `step`, который по умолчанию равен `-datasource.queryStep` (5m). Если разрешение серии `>=5m`, запрос может вернуть пустые данные. Установите `-datasource.queryStep` в **≥2×** разрешения серии. Шаг также можно задавать per-group через `params`.
- **Lookbehind window:** не пропускайте `[lookbehind-window]` в rollup-функциях (например, `rate(errors_total[5m])`). Убедитесь, что он **≥2×** частоте скрейпа.
- **Chaining rules:** если rule B использует результат rule A, убедитесь, что rule A оценивается с `interval < 5m` (или `< -datasource.queryStep`). Используйте [chaining groups](./vmalert_rules_management_with_manifests.md#chaining-групп-зависимости) с `eval_offset`.
- **Dynamic labels:** не задавайте динамические значения (вроде `$value`) в `labels` — это ломает отслеживание состояния алерта. Добавляйте их в `annotations`.
- **Data delay:** если данные могут задерживаться дольше `30s`, увеличьте `-rule.evalDelay` (должен быть ≈ `-search.latencyOffset` в VictoriaMetrics).

### Состояние правил (Rule state)

`vmalert` хранит последние `-rule.updateEntriesLimit` записей (или `update_entries_limit` per-rule) для каждого правила. Их можно увидеть в веб-UI:

1. Откройте вкладку `Groups`
2. Найдите нужную группу и правило
3. Нажмите `Details` и изучите секцию `Last N updates`

Каждая запись содержит: время выполнения, timestamps запроса, количество series (возвращено/просчитано), длительность и cURL-пример запроса.

Метрика `vmalert_recording_rules_last_evaluation_samples` показывает количество series, возвращённых recording rules. Алерт для обнаружения нулевых результатов:

```yaml
- alert: RecordingRulesNoData
  expr: vmalert_recording_rules_last_evaluation_samples < 1
  annotations:
    summary: "Recording rule {{ $labels.recording }} ({{ $labels.group }}) produces no data"
```

### Состояние алертов (Alert state)

- Алерты с `for: 0` (или не задан) срабатывают **немедленно**.
- Алерты с `for > 0` срабатывают **только после нескольких последовательных оценок**, если выражение истинно каждый раз.
- Если оценка возвращает ошибку (datasource недоступен), состояние алерта не меняется.
- Если хотя бы одна оценка возвращает пустые данные, состояние `for` сбрасывается.
- Состояние отслеживается отдельно для каждой time series.

### Data delay

Data delay — одна из самых распростепленных проблем при работе с правилами.

`vmalert` выполняет правила в определённые timestamps и ожидает, что данные уже доступны в `-datasource.url` **в момент оценки**. Недавно записанные sample в VictoriaMetrics становятся видимыми для запросов не сразу — задержка до `30s` (флаг `-search.latencyOffset` в vmselect/vmsingle). Флаг `-rule.evalDelay` по умолчанию также установлен в `30s` для компенсации.

Если данные задерживаются дольше `30s` (буферизация, очередь, сетевые задержки), увеличьте `-rule.evalDelay` соответственно.

### Flapping alerts

Переходящие алерты (flapping) — алерты, которые слишком часто переключаются из inactive в firing.

Выявить переходы за 24 часа:

```promql
max(changes(vmalert_alerts_firing[24h])) by(group, alertname) > 0
```

Как уменьшить вероятность flapping:
1. Установите `for` значительно больше `scrape_interval`.
2. Установите `[lookbehind-window]` в rollup-выражениях **≥2×** `scrape_interval`.
3. Используйте `keep_firing_for` для задержки разрешения алерта.
4. Учитывайте [data delay](#data-delay) в выражениях.
5. Пересмотрите пороги на основе исторических данных.

### Silences и подавление шума

`vmalert` сам алерты не подавляет — он только оценивает правила и отправляет результат нотификатору. Всё подавление шума выполняется ниже по конвейеру:

- **Silences в Alertmanager** — временная заглушка по меткам на время работ или инцидента: [Заглушки (Silences): практические рекомендации](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md#заглушки-silences-практические-рекомендации), управление через CLI — [Alertmanager: Управление через CLI (amtool)](../Prometheus/alertmanager.md#управление-через-cli-amtool).
- **Mute Timings / Maintenance Windows** — регулярные окна тишины по расписанию: [Alertmanager: Mute Timings и Maintenance Windows](../Prometheus/alertmanager.md#mute-timings-и-maintenance-windows); в Grafana-алертинге — [Grafana: Mute Timing для плановых работ](../Grafana/alerting/best_practices.md#сценарий-2-mute-timing-для-плановых-работ-и-active-time-interval).
- **Долгосрочное подавление** (правило перестало быть актуальным) — правка самого правила или группы и hot reload: `curl -X POST http://vmalert:8880/-/reload` перечитывает `-rule`, `-rule.templates` и `-notifier.config` (см. [Hot reload](#hot-reload)), не требуя рестарта.
- **HA-дубли** — между репликами `vmalert` дедупликация делается `-external.label` на стороне vmalert плюс поддержка дедупликации на стороне Alertmanager: [HA vmalert](#ha-vmalert).

Связанные разделы: [Flapping alerts](#flapping-alerts) и [Data delay](#data-delay) — как не плодить лишние срабатывания; подавление и маршрутизация шума в целом — [Grafana: Стратегии подавления и маршрутизации](../Grafana/alerting/best_practices.md#стратегии-подавления-и-маршрутизации).

### Never-firing alerts

Начиная с v1.91.0, `vmalert` может обнаружить [правила](https://github.com/VictoriaMetrics/VictoriaMetrics/issues/4039), чьи выражения не совпадают ни с одной time series (опечатка в селекторе, неверный `job` и т.д.). Такие правила помечаются специальной иконкой в UI и экспортируются через метрику `vmalert_alerting_rules_last_evaluation_series_fetched`. Для обнаружения:

```promql
max(vmalert_alerting_rules_last_evaluation_series_fetched) by(group, alertname) == 0
```

Если метрика возвращает `-1`, функция не поддерживается datasource (старые версии VictoriaMetrics).

### Debug mode

Начиная с v1.116.0 (per-rule) и v1.117.0 (per-group), можно включить `debug: true` в конфигурации правила или группы. `vmalert` начнёт выводить дополнительные логи:

```
2026-08-20T08:22:29.468Z    info    VictoriaMetrics/app/vmalert/rule/alerting.go:273    DEBUG alerting rule "alerts-health.yml":"ServiceDown" at 2026-08-20T08:21:00Z: query returned 2 series (elapsed: 2.055916ms)
2026-08-20T08:22:29.469Z    info    VictoriaMetrics/app/vmalert/rule/alerting.go:273    DEBUG alerting rule "alerts-health.yml":"ServiceDown" at 2026-08-20T08:21:00Z: alert 4671711516378822929 {alertname="ServiceDown"} PENDING => FIRING: 1m0s since becoming active
```

Убедитесь, что уровень логов `-loggerLevel=INFO`. Чувствительные данные (пароли, токены) удаляются из логов.

### Профилирование

`vmalert` предоставляет [Go pprof](https://go.dev/blog/pprof) эндпоинты:

```bash
# Memory profile
curl http://0.0.0.0:8880/debug/pprof/heap > mem.pprof

# CPU profile (ждёт 30 секунд)
curl http://0.0.0.0:8880/debug/pprof/profile > cpu.pprof

# Анализ
go tool pprof mem.pprof
go tool pprof cpu.pprof
```

Профили безопасны для передачи — они не содержат чувствительной информации.

### Диагностические команды

```bash
# Проверка статуса сервиса (systemd)
sudo systemctl status vmalert
journalctl -u vmalert -n 100 --no-pager

# Проверка ресурсов
ps aux | grep vmalert
cat /proc/$(pgrep -f vmalert)/limits | grep "open files"
# → Max open files            65535                65535                files

# Проверка диска
df -h /var/lib/vmalert

# Проверка загрузки правил
curl -s http://localhost:8880/api/v1/rules | jq '.data.groups[].name'

# Проверка active alerts
curl -s http://localhost:8880/api/v1/alerts | jq '.data.alerts[] | {name: .labels.alertname, status: .status}'

# Валидация всех правил на синтетических данных (CI/CD)
vmalert-tool unittest --files=/etc/vmalert/rules/*.yaml

# Проверка Remote Write/Read connectivity
curl -s http://localhost:8880/metrics | grep -E "vmalert_remotewrite|vmalert_config_last_reload"

# Валидация конфигурации без запуска (dry run)
vmalert -rule=/etc/vmalert/rules/*.yaml -dryRun
```

## 10. Лучшие практики

### Resource Limits и планирование

- **Memory:** выделяйте не менее 4 GB RAM для средних нагрузок. При >100K правил рассмотрите 8+ GB.
- **CPU:** vmalert CPU-bound при сложных MetricsQL запросах. Мониторьте `vmalert_rule_group_last_duration_seconds` и сравнивайте с `interval`.
- **Диск:** для state persistence нужен минимальный объём, так как состояние хранится в VictoriaMetrics. Однако логи `vmalert` могут занимать десятки MB в день — настройте ротацию через `logrotate`.
- **LimitNOFILE:** установите `65535` (или выше) для предотвращения ошибок "too many open files".

Ограничение ресурсов через systemd:

```ini
[Service]
MemoryMax=4G
MemoryHigh=3G
CPUQuota=400%
LimitNOFILE=65535
OOMScoreAdjust=-500
```

Ограничение через Docker:

```bash
docker run -d --name vmalert \
  --memory=4g --cpus=4 --ulimit nofile=65535:65535 \
  -p 8880:8880 \
  victoriametrics/vmalert:v1.154.0 \
  -datasource.url=http://victoriametrics:8428 \
  -notifier.url=http://alertmanager:9093 \
  -remoteWrite.url=http://victoriametrics:8428 \
  -remoteRead.url=http://victoriametrics:8428 \
  -rule=/rules/*.yaml
```

### Тюнинг производительности

| Параметр | Рекомендация |
| :--- | :--- |
| `-datasource.queryTimeout` | `30s`–`1m` для сложных запросов |
| `-datasource.queryStep` | ≥2× разрешения серии данных |
| `-remoteWrite.maxQueueSize` | `10000` (увеличить при высокой нагрузке) |
| `-remoteWrite.maxBatchSize` | `1000`–`5000` |
| `concurrency` (в группе) | Увеличить при долгих оценках (>50 правил в группе) |
| `interval` | `30s` для метрик, `1m`–`5m` для логов |

Рекомендации:
- **Снизьте частоту оценки для LogsQL-правил:** запросы к логам ресурсоёмкие. Используйте `interval: 1m`–`5m`.
- **Ограничьте количество правил в одной группе:** при >100 rules в группе время evaluation может превысить `interval`.
- **Используйте recording rules** для предварительного вычисления сложных MetricsQL-запросов, которые переиспользуются в 3+ алертах или дэшбордах.

### Безопасность

- Никогда не открывайте порт `8880` в интернет без reverse proxy с аутентификацией.
- Используйте TLS для соединений с источником данных, Alertmanager и remote storage.
- Ограничьте `-datasource.url` минимально необходимыми правами (read-only для источников).
- Включите `-rule.stripFilePath` для удаления путей к файлам из логов и UI.
- Регулярно обновляйте `vmalert` до последних патчей безопасности (LTS-версии).

### Процедура обновления

1. Остановка сервиса.
2. Бэкап конфигурации (`/etc/vmalert`).
3. Обновление бинарного файла или образа.
4. Валидация конфигурации через `vmalert-tool unittest`.
5. Запуск и проверка `/-/healthy`, `/api/v1/rules`, `vmalert_config_last_reload_successful`.
6. Мониторинг в течение 15–30 минут (проверка `vmalert_remotewrite_errors_total`, `vmalert_iteration_missed_total`, `vmalert_rule_group_last_duration_seconds`).

### Очистка и обслуживание

- **Ротация логов:** настройте `logrotate` для `/var/log/vmalert/*.log` (если используется файловый логгер).
- **Очистка старых правил:** удаляйте неиспользуемые YAML/VMRule-файлы.
- **Аудит recording rules:** периодически проверяйте, какие pre-computed метрики используются. Удаляйте неиспользуемые.
- **Мониторинг самомониторинга:** используйте [официальные алерты vmalert](https://github.com/VictoriaMetrics/VictoriaMetrics/blob/master/deployment/docker/rules/alerts-vmalert.yml) и [дашборд Grafana](https://grafana.com/grafana/dashboards/14950).

## 11. FAQ

**Q: Какой `interval` выбрать для правил алертинга?**
A: Для метрик infrastructure (`node_cpu`, `node_memory`) используйте `30s`. Для бизнес-метрик и логов — `1m`–`5m`. Чем ниже interval, тем выше нагрузка на источник данных и `vmalert`.

**Q: Нужно ли использовать recording rules для простых запросов?**
A: Нет. Recording rules целесообразны для сложных aggregations (`rate()`, `histogram_quantile`), которые переиспользуются в 3+ алертах или дэшбордах.

**Q: Что происходит при перезапуске Alertmanager?**
A: `vmalert` повторно отправит алерты в новый инстанс Alertmanager. Для подавления дублей используйте `-external.label` и настройте Alertmanager на дедупликацию.

**Q: Как откатить изменение правила без перезапуска?**
A: Используйте `/-/reload` (или SIGHUP) после отката файла правил. При использовании Kubernetes/VMRule оператор применит изменения автоматически.

**Q: Можно ли использовать один `vmalert` и для метрик, и для логов?**
A: Да, через [vmauth](https://docs.victoriametrics.com/vmauth/) с маршрутизацией по пути запроса. Альтернатива — запуск отдельных инстансов `vmalert` под каждый тип правил.

**Q: Где хранится состояние алертов?**
A: В памяти процесса. Для персистентности используйте `-remoteWrite.url` (сохранение) и `-remoteRead.url` (восстановление).

**Q: Как мониторить сам `vmalert`?**
A: Используйте эндпоинт `/metrics` (скрейпится через vmagent/Prometheus) и официальные алерты из [alerts-vmalert.yml](https://github.com/VictoriaMetrics/VictoriaMetrics/blob/master/deployment/docker/rules/alerts-vmalert.yml). Ключевые метрики: `up{job="vmalert"}`, `vmalert_config_last_reload_successful`, `vmalert_alerting_rules_errors_total`, `vmalert_recording_rules_errors_total`, `vmalert_remotewrite_errors_total`, `vmalert_iteration_missed_total`, `vmalert_rule_group_last_duration_seconds`. Используйте [дашборд Grafana](https://grafana.com/grafana/dashboards/14950).

**Q: Что такое vmalert-tool и зачем он нужен?**
A: Это CLI-утилита для валидации синтаксиса и unit-тестирования правил на синтетических данных. Команда `vmalert-tool unittest --files=<path>` выполняет unit-тесты в формате, совместимом с Prometheus. Обязательна для CI/CD пайплайнов.

**Q: Поддерживает ли `vmalert` multi-tenancy?**
A: В Enterprise-версии да (`-clusterMode=true` + поле `tenant` в правилах). В Community — нет встроенного механизма, используйте отдельные инстансы `vmalert` с разными `-datasource.url`.

**Q: Как vmalert работает в режиме HA?**
A: Запустите несколько одинаково настроенных инстансов с уникальными `-external.label=replica=<id>`. Настройте [deduplication](https://docs.victoriametrics.com/victoriametrics/single-server-victoriametrics/#deduplication) на стороне VictoriaMetrics (`-dedup.minScrapeInterval` = `interval` vmalert). Alertmanager сам дедуплицирует алерты с одинаковыми метками.

**Q: Можно ли использовать vmalert с Graphite?**
A: Да, задайте `-rule.defaultRuleType=graphite` или `type: graphite` на уровне группы. vmalert отправляет запросы к `<-datasource.url>/render?format=json`.

## 12. Дополнительная информация

- **VMUI (Alerting Tab):** современный способ визуализации алертов `vmalert` доступен напрямую в UI VictoriaMetrics (с v1.125.0).
- **vmalert-tool:** утилита для валидации синтаксиса и unit-тестирования правил ([документация](https://docs.victoriametrics.com/vmalert-tool/)). Команда `vmalert-tool unittest --files=<path>`. Добавляйте в CI/CD перед деплоем.
- **vmauth:** позволяет направлять запросы vmalert на разные хранилища (метрики/логи/трейсы) по пути запроса (`/api/v1/query*` vs `/select/logsql/*`). Подробнее — [vmauth_overview.md](./vmauth_overview.md).
- **VictoriaMetrics Operator:** для декларативного управления правилами в Kubernetes через CRD `VMRule`/`VMAlert` — см. [vmalert_rules_management_with_manifests.md](./vmalert_rules_management_with_manifests.md).
- **Hot reload:** поддерживается через SIGHUP, `/-/reload` (защищён `-reloadAuthKey`) или `-configCheckInterval`.
- **Графики состояния алертов:** для исторического анализа запросов `ALERTS` и `ALERTS_FOR_STATE` используйте [дашборд alert-statistics](https://github.com/VictoriaMetrics/VictoriaMetrics/blob/master/dashboards/alert-statistics.json).

Официальная документация: [vmalert docs](https://docs.victoriametrics.com/vmalert/), [vmalert-tool](https://docs.victoriametrics.com/vmalert-tool/), [Alerting with VictoriaLogs](https://docs.victoriametrics.com/victorialogs/vmalert/), [Alerting with VictoriaTraces](https://docs.victoriametrics.com/victoriatraces/vmalert/).