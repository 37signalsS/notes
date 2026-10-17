# VictoriaTraces: хранение трейсов (pre-GA)

**Актуально для:** VictoriaTraces v0.12.0

> **Статус:** продукт pre-GA. Перед GA по roadmap осталась финализация структуры данных и обещание обратной совместимости; Tempo API, web UI и vtagent позиционируются как MVP и дорабатываются до GA. Используйте в проде осознанно: изолируйте на stage, следите за changelog и не планируйте как единственное хранилище боевых трейсов без резервного сценария.

## Определения

**VictoriaTraces (VT)** — хранилище distributed-трейсов из экосистемы VictoriaMetrics: принимает trace spans по OTLP, хранит их как структурированные записи (построено на кодовой базе VictoriaLogs) и отдаёт через совместимые subsets Jaeger Query API и (experimental) Grafana Tempo API, а также через LogsQL. Одноимённый бинарник single-node режима — `victoria-traces` (в релизах — `victoria-traces-prod`), HTTP-порт по умолчанию `10428`.

**Trace span** — атомарное событие трейса (имя операции, длительность, атрибуты). Пара stream-полей в модели данных VT: `service.name` (из resource attributes) и `name` (имя span'а); остальные данные (trace_id, span_id, resource/scope/span attributes) хранятся как regular fields и ищутся по LogsQL.

**Компоненты кластерного режима:** `vtinsert` (приём и распределение spans **по trace ID** на storage-ноды через `/internal/insert`), `vtselect` (запросы к storage через `/internal/select/*`, агрегация), `vtstorage` (хранение и локальные запросы). Все три роли выполняет один бинарник `victoria-traces-prod`: роль определяется флагом `-storageNode` (задан — работает как insert/select, не задан — как storage, что эквивалентно single-node).

**vtagent** — агент приёма OTLP и remote-write трейсов в VictoriaTraces (`vtagent-prod` из архива `vtutils`): буферизует spans на диске при недоступности хранилища и умеет реплицировать их в несколько инстансов (множественные `-remoteWrite.url`).

**Per-day partition** — каталог данных за календарный день `YYYYMMDD` внутри `<-storageDataPath>/partitions/`; единица retention, бэкапа и ручного attach/detach.

## Базовые концепции

### Как это устроено

VT принимает spans OTLP, трансформирует их в лог-записи и строит индекс по trace ID (с окном флаша `-insert.indexFlushInterval`, по умолчанию 20s). Отсюда:

- линейное масштабирование по CPU/RAM/disk подобно VictoriaLogs, без внешнего объектного хранилища;
- тот же язык запросов, что и у VictoriaLogs, — LogsQL (`/select/logsql/query`);
- Jaeger/Tempo API — надстройка над LogsQL-выборкой (подмножества API, не полная эмуляция Tempo/Jaeger);
- заявленная эффективность: до ~3.7x меньше RAM и ~2.6x меньше CPU относительно Grafana Tempo (блог-бенчмарк вендора); сжатие spans — 10x и более.

### Компоненты и порты

| Компонент | Порт по умолчанию / в примерах | Назначение |
| :--- | :--- | :--- |
| Single-node (`victoria-traces`) | HTTP `:10428` | Всё в одном процессе: insert + select + storage |
| OTLP/gRPC | `:4317` (рекомендуемый; выключен, пока не задан `-otlpGRPCListenAddr`) | gRPC-приём spans (TraceService) |
| `vtagent` | пример `:10429` | Приём OTLP от SDK/Collector + remote write |
| `vtinsert` (кластер) | пример `:10481` | Приём OTLP, распределение по storage |
| `vtselect` (кластер) | пример `:10471` | Запросы, UI, Jaeger/Tempo API |
| `vtstorage` (кластер) | пример `:10491`, `:10492` | Хранение (по сути single-node инстансы) |

Порты кластерных компонентов — соглашение из quick start docs; назначайте свои через `-httpListenAddr`. Внутренняя коммуникация insert/select ↔ storage идёт по тому же `-httpListenAddr` storage-ноды (`/internal/insert`, `/internal/select/*`).

### Место в стеке

```
Приложения / OTel SDK ──OTLP (HTTP/gRPC)──┐
                                          ▼
OpenTelemetry Collector / vtagent ──► vtinsert ──/internal/insert──► vtstorage ×N
                                          │                                │
                                          ▼                                ▼
                              vtselect ◄──/internal/select/*───────────────┘
                                  │
        Grafana (Jaeger/Tempo datasource) / Jaeger UI / Web UI / vmalert (LogsQL)
        : /select/jaeger, /select/tempo, /select/vmui, /select/logsql/query
```

### Кластер: архитектура, дуальность, HA-правила

- **Дуальность:** любой `vtstorage` — это полноценный single-node VT (принимает OTLP и отвечает на `/select/*`); миграция с single на cluster — добавить существующий инстанс в `-storageNode` у `vtinsert`/`vtselect`.
- **Запись:** `vtinsert` распределяет spans равномерно по нодам **по trace ID**; при недоступности части `vtstorage` продолжает писать в доступные (запись не встаёт).
- **Чтение:** по умолчанию `vtselect` требует доступности **всех** нужных `vtstorage` иначе возвращает ошибку вместо неполного ответа; частичные ответы включаются флагом `-search.allowPartialResponse` (риск неполных данных — осознанный компромисс).
- **Репликации на уровне хранилища нет.** HA строится снаружи: шиппер (OTel Collector или vtagent с несколькими `-remoteWrite.url`) реплицирует один поток в 2+ инстанса/кластера, на пути чтения — vmauth/LB.
- Многоуровневые схемы: `vtinsert`/`vtselect` могут указывать в `-storageNode` другие insert/select-ноды верхнего уровня.

### Мультитенантность

Тенант — пара заголовков `AccountID` и `ProjectID` (32-bit unsigned, по умолчанию `0`), передаётся и при записи, и при запросе. Заголовки работают и на OTLP/gRPC (через HTTP-заголовки поверх HTTP/2). Overhead на тенанта низкий; **per-tenant авторизации нет** — разграничение делайте vmauth'ом ([vmauth_overview.md](./vmauth_overview.md)). В отличие от VictoriaMetrics cluster, URL'ы VT не содержат accountID-сегмент — tenant выбирается заголовком.

## Практические сценарии

### 1. Установка и быстрый старт (single-node)

```bash
# Релиз (пример v0.12.0): архив victoria-traces-<os>-<arch>-<ver>.tar.gz
curl -L -O https://github.com/VictoriaMetrics/VictoriaTraces/releases/download/v0.12.0/victoria-traces-linux-amd64-v0.12.0.tar.gz
tar xzf victoria-traces-linux-amd64-v0.12.0.tar.gz

# Запуск (HTTP :10428, данные в ./victoria-traces-data, retention 7d)
./victoria-traces-prod \
  -httpListenAddr=:10428 \
  -storageDataPath=/var/lib/victoria-traces \
  -retentionPeriod=7d

curl -s http://localhost:10428/health
# → 200 OK
```

Альтернативы: Docker-образы `victoriametrics/victoria-traces` (Docker Hub/Quay), Helm-чарты `victoria-traces-single`/`victoria-traces-cluster`/`victoria-traces-agent`, Operator-ресурсы `VTSingle`/`VTCluster`/`VTAgent`. Сборка из исходников — `make victoria-traces` в репозитории [VictoriaMetrics/VictoriaTraces](https://github.com/VictoriaMetrics/VictoriaTraces).

### 2. Приём OTLP/HTTP

HTTP-эндпоинт приёма: `POST /insert/opentelemetry/v1/traces`. Полезные query-аргументы/заголовки: `AccountID`/`ProjectID` (тенант), `extra_fields` / `VT-Extra-Fields` (дописать поля во все spans), `debug=1` / `VT-Debug: 1` (не сохранять, только залогировать вход).

Конфиг OpenTelemetry Collector (проверенная форма):

```yaml
exporters:
  otlphttp:
    traces_endpoint: http://victoria-traces:10428/insert/opentelemetry/v1/traces
    headers:
      VT-Extra-Fields: env=prod   # опционально: дописать поле в каждый span
```

Из приложения (SDK-направление, Go):

```go
traceExporter, err := otlptracehttp.New(ctx,
  otlptracehttp.WithEndpointURL("http://victoria-traces:10428/insert/opentelemetry/v1/traces"),
)
```

Готовый docker-compose демо с HotROD: [deployment/docker/compose-vt-single.yml](https://github.com/VictoriaMetrics/VictoriaTraces/blob/master/deployment/docker/compose-vt-single.yml).

### 3. Приём OTLP/gRPC

gRPC **выключен по умолчанию** и по умолчанию требует TLS (`-otlpGRPC.tls=true`) — одной команды `-otlpGRPCListenAddr=:4317` недостаточно, нужны сертификаты либо явный insecure:

```bash
# Вариант A: TLS (рекомендуется для прода)
./victoria-traces-prod \
  -otlpGRPCListenAddr=:4317 \
  -otlpGRPC.tlsCertFile=/etc/vt/tls.crt \
  -otlpGRPC.tlsKeyFile=/etc/vt/tls.key

# Вариант B: без TLS (только тест / закрытая сеть)
./victoria-traces-prod \
  -otlpGRPCListenAddr=:4317 \
  -otlpGRPC.tls=false
```

Конфиг Collector:

```yaml
exporters:
  otlp/without-tls:
    endpoint: victoria-traces:4317
    tls:
      insecure: true
    # или otlp/with-tls с tls.cert_file / tls.key_file
```

Сжатие gRPC-потока: `gzip` (по умолчанию), `snappy`, `zstd`, `none`.

### 4. Генерация тестовых данных (vtgen)

Для проверки ингеста/запросов без инструментированного приложения:

```bash
git clone https://github.com/VictoriaMetrics/VictoriaTraces.git
cd VictoriaTraces && make vtgen          # бинарник ./bin/vtgen
./bin/vtgen -addrs=http://localhost:10428/insert/opentelemetry/v1/traces
```

Диагностика приёма: флаг `-logIngestedRows` (лог каждого принятого span'а) и `-logNewStreams` (создание новых stream'ов — полезно ловить cardinality-взрывы).

### 5. Запросы: LogsQL, Jaeger API, Web UI

**LogsQL** (тот же API, что у VictoriaLogs):

```bash
# Количество spans за выбранный диапазон (limit/тенаут — параметры LogsQL)
curl -s http://localhost:10428/select/logsql/query \
  -d 'query=* | count()'

# Топ service.name по количеству spans
curl -s http://localhost:10428/select/logsql/query \
  -d 'query=* | top service.name 10'
```

**Jaeger API** (для Grafana Jaeger datasource / Jaeger UI) под префиксом `/select/jaeger`:

| Эндпоинт | Назначение |
| :--- | :--- |
| `/select/jaeger/api/services` | Список сервисов |
| `/select/jaeger/api/services/{service}/operations` | Span-имена сервиса |
| `/select/jaeger/api/traces?service=...&operation=...&tags=...&start=...&end=...&minDuration=...&maxDuration=...&limit=20` | Поиск трейсов (`tags` — JSON `{"key":"value"}`, значение с `~` — regex; start/end — unix microseconds) |
| `/select/jaeger/api/traces/{trace_id}` | Один трейс целиком |
| `/select/jaeger/api/dependencies` | Граф зависимостей сервисов (требует включённой background-задачи `-servicegraph.enableTask` на storage) |

VT расширяет фильтрацию `/api/traces` — теги матчатся не только по span attributes, но и по resource attributes и instrumentation scope attributes.

**Web UI**: `http://localhost:10428/select/vmui` — два режима в дропдауне слева сверху: Trace Explorer (условия или свободный LogsQL) и TraceID (трейс по ID). Песочница вендора: [play-vtraces.victoriametrics.com](https://play-vtraces.victoriametrics.com/).

**Tempo API (experimental, минимум v0.9.4)** под префиксом `/select/tempo`: `api/echo` (healthcheck datasource), `api/search` (поиск TraceQL-запросом `q=`), `api/v2/search/tags`, `api/v2/search/tag/{tag}/values`, `api/traces/{id}`, `api/v2/traces/{id}`, `api/metrics/query_range` (TraceQL metrics). Часть функций TraceQL и панелей Drilldown может работать не полностью — следите за changelog.

### 6. Визуализация в Grafana

- **Jaeger datasource** — базовый, полный путь интеграции: URL `http://<victoria-traces>:10428/select/jaeger` (кластер: `http://<vtselect>:10471/select/jaeger`).
- **Tempo datasource** (v0.9.4+) — для TraceQL и Grafana Traces Drilldown: URL `.../select/tempo`; Drilldown опирается на `/api/metrics/query_range`, интеграция experimental.
- Готовые дашборды мониторинга самого VT: Grafana.com [24136](https://grafana.com/grafana/dashboards/24136) (single) и [24134](https://grafana.com/grafana/dashboards/24134) (cluster).

### 7. Retention, диски, партиции, бэкап

- `-retentionPeriod` (по умолчанию `7d`, минимум `1d`, максимум `100y`): старые данные удаляются по дням; spans **вне retention отклоняются на приёме** — счётчик `vt_rows_dropped_total` + выборочный WARN в логах. Рекомендуемое правило: `rate(vt_rows_dropped_total[5m]) > 0`.
- Будущие метки времени: по умолчанию принимается до `now+2d`; шире — `-futureRetention=1y` и т.п.
- Retention по месту на диске (флаги взаимоисключающие): `-retention.maxDiskSpaceUsageBytes=100GiB` **или** `-retention.maxDiskUsagePercent=80`. VT всегда держит минимум последние 2 дня сверх лимита; время-based retention применяется независимо — чтобы чистить только по диску, ставьте `-retentionPeriod=100y`.
- Бэкап пер-дневных партиций (`<storageDataPath>/partitions/YYYYMMDD`): два прохода `rsync -avh --delete`, второй — после detach (см. ниже), либо согласованный снапшот диска; восстановление — rsync обратно + attach (или запуск при остановленном процессе, VT сам подхватит каталоги).
- Attach/detach партиций без остановки: `POST /internal/partition/attach?name=YYYYMMDD`, `POST /internal/partition/detach?name=YYYYMMDD` (детач ждёт завершения читающих запросов); защита — `-partitionManageAuthKey`. На этом строятся и multi-tier схемы NVMe→HDD.

### 8. Кластер на хостах (по мотивам quick start)

```bash
# Два vtstorage
./victoria-traces-prod -httpListenAddr=:10491 -storageDataPath=vt-data-1 &
./victoria-traces-prod -httpListenAddr=:10492 -storageDataPath=vt-data-2 &

# vtinsert и vtselect поверх них
./victoria-traces-prod -httpListenAddr=:10481 \
  -storageNode=localhost:10491,localhost:10492 &
./victoria-traces-prod -httpListenAddr=:10471 \
  -storageNode=localhost:10491,localhost:10492 &

# Приём и проверка
./bin/vtgen -addrs=http://localhost:10481/insert/opentelemetry/v1/traces
curl -s http://localhost:10471/select/logsql/query -d 'query=* | count()'
# Web UI кластера: http://localhost:10471/select/vmui/
```

Рекомендация docs: в проде не смешивать insert/select на одной ноде, чтобы тяжёлые запросы не конкурировали с приёмом. Тюнинг при необходимости: `-insert.concurrency` (по умолчанию 2), компрессия вставки/выборки отключается флагами `-insert.disableCompression` / `-select.disableCompression`.

### 9. Kubernetes: Operator и Helm

- Operator: CRD `VTSingle`, `VTCluster`, `VTAgent` (в [operator_overview.md](./operator_overview.md) отмечены как beta). Минимальный VTCluster (поля `insert`/`select`/`storage` — verified по API reference оператора):

```yaml
apiVersion: operator.victoriametrics.com/v1
kind: VTCluster
metadata:
  name: traces
spec:
  storage:
    replicaCount: 3
  select:
    replicaCount: 2
  insert:
    replicaCount: 2
```

- Helm (чарты репозитория VictoriaMetrics): `victoria-traces-single`, `victoria-traces-cluster`, `victoria-traces-agent`. Ключи values сверяйте с README конкретного чарта — schema меняется между версиями.

### 10. HA: репликация через vtagent или Collector

`vtagent` принимает OTLP (HTTP `:10429` в примере docs / gRPC через `-otlpGRPCListenAddr`) и шлёт spans в `insert/native`:

```bash
# Один агент → два хранилища: индивидуальные on-disk буферы на каждый URL
./vtagent-prod \
  -remoteWrite.url=http://vt-zone-a:10428/insert/native \
  -remoteWrite.url=http://vt-zone-b:10428/insert/native
```

`-remoteWrite.url` обязан заканчиваться на `/insert/native`; поддерживается DNS SRV (`http://srv+имя-записи/insert/native`). При недоступности remote storage spans буферизуются в `-remoteWrite.tmpDataPath` (лимит — `-remoteWrite.maxDiskUsagePerURL`, при переполнении выбрасываются самые старые) и досылаются после восстановления. Альтернатива — OTel Collector с fan-out на оба адреса. На пути чтения — vmauth с health-check'ом и переключением на живой кластер.

### 11. Мониторинг и алертинг VictoriaTraces

- Метрики компонента: `http://<host>:<port>/metrics` (Prometheus format); скрейп vmagent'ом/VM — по общей схеме из [vmagent_overview.md](./vmagent_overview.md).
- Дашборды Grafana: 24136 (single) / 24134 (cluster); правила алертов: [alerts-vtraces.yml](https://github.com/VictoriaMetrics/VictoriaTraces/blob/master/deployment/docker/rules/alerts-vtraces.yml) через vmalert.
- **Алертинг на сами трейсы** (vmalert v1.106.0+): vmalert ходит в stats API VT (`/select/logsql/stats_query`, `/select/logsql/stats_query_range`) как в Prometheus-compatible datasource, правила — LogsQL с `type: vlogs` на уровне группы:

```bash
./vmalert \
  -rule=traces.rules.yaml \
  -datasource.url=http://victoria-traces:10428 \
  -notifier.url=http://alertmanager:9093 \
  -remoteWrite.url=http://victoriametrics:8428
```

Подробности интеграции — в [vmalert_overview.md](./vmalert_overview.md); LogsQL — в [logsql_overview.md](./logsql_overview.md).

### 12. Безопасность доступа

- VT рассчитан на работу в защищённой сети; наружу (и для командного доступа) ставьте [vmauth](./vmauth_overview.md) или reverse proxy перед `/insert/*` и `/select/*` — у компонентов нет собственной пользовательской аутентификации (флаг `-httpAuth.username/-password` даёт только Basic Auth на весь HTTP).
- Внутренние эндпоинты закрывайте authKey'ами: `-forceFlushAuthKey`, `-forceMergeAuthKey`, `-partitionManageAuthKey` (переопределяют `-httpAuth.*`).
- Кластер: TLS на storage (`-tls` + сертификаты) и `-storageNode.tls` (+ опционально `-storageNode.username/password`) на insert/select; рекомендуется `-select.disable` на vtinsert и `-insert.disable` на vtselect, чтобы случайный запрос не ушёл не туда; mTLS — Enterprise.
- Скрытие чувствительных атрибутов отдельных пользователей: query-аргумент `hidden_fields_filters` (префиксы полей `resource_attr:`/`span_attr:`), навешивается прокси/Grafana-datasource'ом.
- Мультитенантность: маршрутизация по заголовкам через vmauth, т.к. сам VT tenant не авторизует.

### 13. Закрытие/апгрейд

Безопасный апгрейд/даунгрейд (если release notes не говорят иного): `SIGINT` → дождаться остановки → запустить новый бинарник. Данные переживают остановку: в `-storageDataPath` есть in-memory flush каждые 5s (`-inmemoryDataFlushInterval`) для переживания OOM/SIGKILL.

## Валидация

```bash
# 1. Health и метрики
curl -s http://localhost:10428/health
# → 200 OK
curl -s http://localhost:10428/metrics | head -n 2

# 2. Данные через LogsQL (после vtgen/инструментации)
curl -s http://localhost:10428/select/logsql/query -d 'query=* | count()'
# → JSON с числом spans

# 3. Jaeger API жив
curl -s http://localhost:10428/select/jaeger/api/services | jq '.data'
# → ["service-a", ...]

# 4. Tempo API (healthcheck datasource в Grafana делает то же самое)
curl -s http://localhost:10428/select/tempo/api/echo
# → 200 OK

# 5. Тенант по заголовку (возвращает данные тенанта 1, а не 0)
curl -s -H 'AccountID: 1' http://localhost:10428/select/logsql/query -d 'query=* | count()'

# 6. Web UI
# → открыть http://localhost:10428/select/vmui, выбрать time range «last 7 days», найти сгенерированные spans
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| 404 на `/insert/...` | Не тот порт; в кластере приём — на vtinsert (`:10481` в примере), не на vtselect | `POST http://<insert>:10481/insert/opentelemetry/v1/traces`; single — `:10428` |
| gRPC не принимает соединение | `-otlpGRPCListenAddr` не задан (gRPC выключен по умолчанию) | Запустить с `-otlpGRPCListenAddr=:4317` (+ TLS или `-otlpGRPC.tls=false`) |
| gRPC handshake падает | `-otlpGRPC.tls=true` по умолчанию, а сертификаты не указаны | Сертификаты (`-otlpGRPC.tlsCertFile/-tlsKeyFile`) или явный `-otlpGRPC.tls=false` |
| Spans отклонены, в логах WARN + растёт `vt_rows_dropped_total` | Метка времени вне retention или дальше `now+2d` | Проверить часы/таймзоны источника; расширить `-futureRetention`; настроить алерт `rate(vt_rows_dropped_total[5m]) > 0` |
| Трейс «принят», но не находится в Jaeger API ~30–60s | Индекс по trace ID флашится с задержкой (`-insert.indexFlushInterval` 20s) плюс `-search.latencyOffset` 30s | Ждать видимости ~1 минуту; уменьшать интервалы осторожно (нагрузка) |
| Пустой список services/operations у Jaeger API | Слишком узкий `-search.streamFieldsLookbehind` (по умолчанию 72h) или данные старше окна | Расширить lookbehind; проверить time range |
| Jaeger/Tempo поиск пуст при данных в UI | Окно `-search.fieldsLookbehind` (по умолчанию 2h) для тегов/attributes | Увеличить `-search.fieldsLookbehind` или сузить запрос известными полями |
| `502 Bad Gateway` с vtselect (кластер) | Одна из vtstorage недоступна, а partial responses выключены | Вернуть storage; либо осозненно включить `-search.allowPartialResponse` |
| Медленные запросы | Тяжёлые LogsQL/TraceQL; накопленные медленные — в логах | `-search.maxQueryDuration` (по умолчанию 30s), лимиты `-search.maxTraces`/`-search.maxTags`; slow-query логи `-search.logSlowQueryDuration` (5s) |
| Grafana datasource «Save & Test» падает | Неверный базовый URL | Jaeger: `.../select/jaeger`; Tempo: `.../select/tempo` (v0.9.4+); в кластере — на vtselect |
| Диск быстро заполняется | Нет ограничения по диску, retention велик | `-retention.maxDiskSpaceUsageBytes`/`-retention.maxDiskUsagePercent` (не вместе); `-retentionPeriod` |

## Рекомендации по эксплуатации

- До GA держите VT в контуре, где допустима миграция API/формата данных; фиксируйте версию и читайте release notes перед каждым апгрейдом.
- Прод-топология по умолчанию: OTel Collector (или vtagent) → vtinsert/vtselect (раздельно) → vtstorage; перед insert/select — vmauth; репликация — двумя независимыми кластерами через шиппер.
- Мониторьте сам VT: `/metrics` + дашборды 24136/24134 + алерты из alerts-vtraces.yml; отдельно — `vt_rows_dropped_total` (ошибки времени на приёме).
- Retention планируйте заранее (время + дисковые лимиты), бэкапы делайте per-partition rsync'ом по схеме из сценария 7; detach — только с `-partitionManageAuthKey`.
- Чувствительные атрибуты (токены в attributes) скрывайте через `hidden_fields_filters` на прокси, а не полагаясь на UI.
- Cardinality-гигиена тегов: stream-поля (`service.name`, `name`) — кардинально значимы; следите за `-logNewStreams`.

## Ограничения и особые случаи

- **Pre-GA:** структура данных ещё может измениться (roadmap до GA — финализация + обратная совместимость); Tempo API, Web UI и vtagent — MVP-качество, дорабатываются.
- Поддерживаемые протоколы приёма — OTLP (HTTP/gRPC). Прочие SDK-протоколы «из коробки» не поддерживаются — пропускайте через OTel Collector.
- Jaeger/Tempo API — совместимые **подмножества**: TraceQL работает (experimental, с v0.9.4), но отдельные функции и панели Traces Drilldown могут вести себя иначе, чем на нативном Tempo.
- `/select/jaeger/api/dependencies` требует включённой фоновой генерации service graph (`-servicegraph.enableTask=true` — только на single/vtstorage).
- VT не реплицирует данные сам: HA = внешняя репликация (Collector/vtagent) + vmauth на чтении; в кластере при недоступности части storage чтение по умолчанию падает с ошибкой, не отдавая часть данных.
- Пер-тенантной авторизации и собственного RBAC нет — только vmauth/прокси и заголовки `AccountID`/`ProjectID`.
- `hidden_fields_filters` прячет поля от выборки, но не заменяет шифрование на диске/в транзите.

## Дополнительная информация

### Ссылки

- [Документация VictoriaTraces](https://docs.victoriametrics.com/victoriatraces/) — install, cluster, data ingestion, querying;
- [Roadmap](https://docs.victoriametrics.com/victoriatraces/roadmap/) — что осталось до GA;
- [Релизы](https://github.com/VictoriaMetrics/VictoriaTraces/releases) — бинарники, vtutils, checksums;
- [Песочница VictoriaTraces](https://play-vtraces.victoriametrics.com/) — UI с демо-данными;
- [Блог: distributed tracing с подходом VictoriaLogs](https://victoriametrics.com/blog/dev-note-distributed-tracing-with-victorialogs/) — архитектурные мотивы и бенчмарки.

### См. также

- [VictoriaMetrics: обзор](./overview.md) — место VT в экосистеме;
- [VictoriaLogs / LogsQL](./logsql_overview.md) — язык запросов и модель данных (VT построен на той же базе);
- [vmauth](./vmauth_overview.md) — авторизация /insert и /select, балансировка HA-пары кластеров;
- [vmalert](./vmalert_overview.md) — алертинг на трейсы (`type: vlogs`, v1.106.0+);
- [vmagent](./vmagent_overview.md) — скрейп /metrics компонентов VT;
- [Operator](./operator_overview.md) — CRD VTSingle/VTCluster/VTAgent;
- [OpenTelemetry: обзор](../OpenTelemetry/opentelemetry_overview.md) — Collector/SDK перед VictoriaTraces.
