# Grafana: Корреляция телеметрии — Exemplars, Trace-to-*, Correlations

**Актуально для:** Grafana 13.2.x / 12.x (LTS)

Практическое руководство по связыванию метрик, логов и трейсов в Grafana: exemplars на графиках, линковки trace→logs/metrics/profiles в настройках источников, correlations (запрос→запрос) в Explore и их провиженинг. Архитектура трейсинга — в `../Tempo/`, сборка телеметрии — `../OpenTelemetry/` и [Grafana Alloy](grafana_alloy_overview.md). Облачные и ИИ-функции не рассматриваются. Актуальная версия — Grafana 13.2.x, LTS — 12.4.x; 11.x — EOL (июнь 2026).

## Определения

- **Exemplar** — точка-метка на временном ряде, хранящая ссылку на конкретный трейс (обычно `trace_id`); позволяет от «всплеска на графике» перейти к конкретному запросу.
- **Exemplar storage** — хранилище exemplars в Prometheus (кольцевой буфер в памяти). В Prometheus 2.x и 3.x включается флагом `--enable-feature=exemplar-storage` (по умолчанию выключено); приложения должны передавать traceID в метрики через OpenTelemetry/клиентские библиотеки.
- **Trace-to-logs** — настройка источника данных Tempo, добавляющая из спана ссылку на логи этого запроса в Loki (или другой лог-источник).
- **Trace-to-metrics** — настройка источника Tempo, добавляющая из спана ссылки на метрики (span metrics) в Prometheus/Mimir.
- **Trace-to-profiles** — переход из спана к профилю в Grafana Pyroscope (Flame Graph) по pprof-меткам.
- **Service graph** — карта связей между сервисами, которая строится из span metrics (метрик, которые генерирует metrics-generator Tempo); отображается как нод-граф и требует метрик-источника в качестве цели.
- **Derived field** — вычисляемое поле в источнике Loki: значение извлекается из строки лога (regex) или из лейбла, и из него делается ссылка, например на Tempo по извлечённому traceID.
- **`matcherType`** (derived field) — тип извлечения значения: `regex` (по строке лога) или `label` (по имени лейбла; поддерживает regex по ключам лейблов, например `trace[_]?id`).
- **Correlation** — связь «источник A → источник B» в Explore: клик по полю результата открывает целевой источник с подставленным значением (макросы интерполяции `${__value.raw}`, `${__field.labels.*}`). Настраивается через UI/API или провиженинг.

## Базовые концепции

Зачем корреляция: при инциденте инженер двигается по цепочке «симптом → причина»: график (метрика) показывает всплеск ошибок → exemplar/trace-link открывает медленный или ошибочный трейс → из спанов переход в логи этого конкретного запроса. Без настроенных линковок этот путь выполняется вручную (копирование traceID между вкладками), что замедляет диагностику.

Как это устроено:

1. **Ссылки задаются в настройках источников данных**, а не в дашбордах — тогда работают во всех панелях и Explore автоматически. Провижинятся через `jsonData` источника (см. [Провиженинг](grafana_provisioning.md)).
2. Связь может быть **internal** (переход внутри Grafana в другой источник по `datasourceUid` — рекомендуемый способ) или **external** (URL с интерполяцией).
3. Для exemplars цепочка начинается на стороне приложения: инструментирование должно прокидывать traceID в метрики; иначе Grafana просто не покажет точки-exemplars.
4. Три группы линковок дополняют друг друга: **trace→signal** (настраиваются в источнике Tempo через блоки `tracesTo*`), **log → trace** (derived fields в источнике Loki) и **correlation** (произвольная связь запрос→запрос или внешний URL). Derived fields и Correlations не заменяют друг друга: первые решают частный случай «лог → трейс» одним regex, вторые — любые cross-source переходы.

Типовая топология связей: Prometheus ⇄ Tempo (exemplars и trace-to-metrics), Loki → Tempo (derived fields), Tempo → Loki/Prometheus/Pyroscope (trace-to-logs/metrics/profiles).

Провиженинг и API: настройки trace-to-* и derived fields задаются как блоки `jsonData` источника данных в файлах провижнинга; корреляции до недавнего времени настраивались только через UI/API, но также поддерживают провиженинг — секцией `correlations` в описании источника.

## Практические сценарии

### Предварительные требования

- Работающий Tempo и Loki как источники данных в Grafana (uid известны).
- Приложение инструментировано OpenTelemetry (traceID в логах и метриках); сборщик — Alloy/OTel Collector (см. `../OpenTelemetry/otlp_protocol.md`).
- Для trace-to-metrics/service graph — Tempo metrics-generator со span metrics, экспортируемыми в Prometheus/Mimir.
- Для trace-to-profiles — источник данных Grafana Pyroscope и включённый span profiling в Tempo.
- Права Editor/Admin на редактирование источников данных.

### Сценарий 1. Включить exemplars в Prometheus и увидеть их в Grafana

```bash
# 1. На стороне Prometheus: включить хранилище exemplars
# systemd: Environment="ARGS=--enable-feature=exemplar-storage" (или флаг в unit-файле)
curl -sS http://prometheus:9090/api/v1/status/flags | jq '.data.exemplar_storage'
# → "true"

# 2. Проверить наличие exemplars (пример для метрики с traceID)
curl -sS 'http://prometheus:9090/api/v1/query?query=http_server_request_duration_seconds_bucket' \
  | jq '.. | .exemplars? // empty' | head
# → массивы с traceID (если приложение их отдаёт)
```

Exemplar storage в Prometheus требует флага `--enable-feature=exemplar-storage` и в ветке 2.x, и в 3.x (сам по себе он не включается нативными гистограммами). Размер буфера задаётся в секции `storage.exemplars` (`max_exemplars`, по умолчанию 100000); экспорт в удалённое хранилище — только при `send_exemplars: true` и поддержке protobuf (подробности — [SSoT Prometheus](../Prometheus/concepts/exemplars.md)).

Линкуем Prometheus → Tempo (файл провижнинга):

```yaml
# provisioning/datasources/prometheus.yaml
apiVersion: 1
datasources:
  - name: prometheus-prod
    uid: prometheus-prod
    type: prometheus
    url: http://prometheus:9090
    jsonData:
      exemplarTraceIdDestinations:
        - datasourceUid: tempo          # uid источника Tempo
          name: TraceID                 # подпись линка
          urlDisplayLabel: "Открыть трейс"
```

После рестарта Grafana: открыть time series панель с данными этой метрики → на графике появляются ромбики-exemplars → клик открывает соответствующий трейс в Tempo. Если ромбиков нет — проблема на стороне приложения/сборщика, а не Grafana.

### Сценарий 2. Trace-to-Logs: из спана в логи (Tempo → Loki)

```yaml
# provisioning/datasources/tempo.yaml (фрагмент jsonData)
jsonData:
  tracesToLogsV2:
    datasourceUid: loki
    spanStartTimeShift: "-10m"     # расширяем окно поиска вокруг спана
    spanEndTimeShift: "10m"
    filterBySpanID: false
    filterByTraceID: true
    tags:
      - key: "service.name"        # тег спана → лейбл потока Loki
        value: "job"
  nodeGraph:
    enabled: true                  # нод-граф трейса (service graph / span metrics)
```

`tracesToLogsV2` — актуальная форма блока (вместо устаревшей `tracesToLogs`). Дополнительно можно задать собственный запрос к целевому источнику:

```yaml
    customQuery: true
    query: 'method="$${__span.tags.method}"'
```

Проверка: открыть любой трейс в Tempo → выбрать спан → кнопка «Logs for this span» открывает Loki с фильтром по traceID; строки логов содержат тот же traceID.

### Сценарий 3. Derived fields: из строки лога в трейс (Loki → Tempo)

```yaml
# provisioning/datasources/loki.yaml (фрагмент jsonData)
jsonData:
  derivedFields:
    - name: TraceID
      matcherType: regex              # regex (по строке) или label (по имени лейбла)
      matcherRegex: 'traceID=(\w+)'   # что вырезать из строки лога
      datasourceUid: tempo            # internal-линк
      url: "$${__value.raw}"          # экранирование $ обязательно в YAML провижининга
      urlDisplayLabel: "Открыть трейс"
```

Для внешнего линка (без выбора внутреннего источника) задаётся полный URL, например к Jaeger:

```yaml
    - name: TraceID
      matcherRegex: 'traceID=(\w+)'
      url: 'http://jaeger:16686/trace/$${__value.raw}'
```

Проверка: в Explore выполнить `{job="myapp"} |= "traceID"` → у строк появился синий линк TraceID → клик открывает трейс в Tempo. Если линка нет — regex не совпадает с форматом лога (проверьте реальную строку). Internal-link в derived fields поддерживается только для источников трассировки.

### Сценарий 4. Trace-to-Metrics: из спана в метрики (Tempo → Prometheus)

Требует span metrics, которые считает metrics-generator Tempo и экспортирует в Prometheus/Mimir. Настройка в источнике Tempo:

```yaml
# provisioning/datasources/tempo.yaml (фрагмент jsonData)
jsonData:
  tracesToMetrics:
    datasourceUid: prometheus
    spanStartTimeShift: "-10m"
    spanEndTimeShift: "10m"
    tags:
      - key: "service.name"          # тег спана → лейбл метрики
        value: "service"
      - key: "job"
    queries:
      - name: "Задержка сервиса"
        query: 'sum(rate(traces_spanmetrics_latency_bucket{$$__tags}[5m]))'
      - name: "Ошибки по коду"
        query: 'sum(rate(traces_spanmetrics_calls_total{$$__tags, status_code="STATUS_CODE_ERROR"}[5m]))'
  serviceMap:
    datasourceUid: prometheus        # цель для service graph (span metrics)
```

Макрос `$$__tags` в провижнинге (в UI — `$__tags`) разворачивается в набор лейблов, собранных из блока `tags`. Проверка: открыть спан → вкладка «Metrics» → выполняются запросы к Prometheus с фильтрами по этому трейсу. Если ссылок нет — в Tempo не включён `metrics_generator` со `span_metrics` (см. `../Tempo/architecture_operations.md`).

### Сценарий 4а. Service graph из span metrics

```yaml
# provisioning/datasources/tempo.yaml (фрагмент jsonData)
jsonData:
  serviceMap:
    datasourceUid: prometheus
  nodeGraph:
    enabled: true
```

Service graph строится по метрикам `traces_service_graph_*`, которые генерирует metrics-generator и пишет в Prometheus. Без span metrics карта сервисов будет пустой; точка входа в неё — вкладка «Service Graph» в Explore/Tempo.

### Сценарий 5. Trace-to-Profiles: из спана в профиль (Tempo → Pyroscope)

```yaml
# provisioning/datasources/tempo.yaml (фрагмент jsonData)
jsonData:
  tracesToProfiles:
    datasourceUid: grafana-pyroscope-datasource
    tags:
      - key: "service.name"
        value: "service_name"
      - key: "host.name"
        value: "hostname"
    profileTypeId: "process_cpu:cpu:nanoseconds:cpu:nanoseconds"
```

Требует источник данных Grafana Pyroscope и сопоставления тегов спана с лейблами профиля. В Tempo для полноценной привязки к строкам кода включается span profiling (`span_profiling`), добавляющий pprof-лейблы в спаны. Проверка: открыть спан → ссылка на профиль открывает Flame Graph Pyroscope за окно спана.

### Сценарий 6. Correlations: произвольная связь запрос→запрос

Пример: из лога ошибки в Loki — к метрике ошибок сервиса в Prometheus. Корреляции определяются у **источника** (source); целью (target) может быть другой источник Grafana (`type: query`) или внешний URL (`type: external`).

Провиженинг (секция `correlations` в описании источника):

```yaml
# provisioning/datasources/loki.yaml
apiVersion: 1
datasources:
  - name: Loki
    type: loki
    uid: loki
    url: http://loki:3100
    jsonData:
      derivedFields:
        - name: TraceID
          matcherRegex: 'traceID=(\w+)'
          datasourceUid: tempo
          url: '$${__value.raw}'
    correlations:
      - targetUID: prometheus
        label: "Метрики ошибок сервиса"
        description: "Prometheus: ошибки по сервису"
        type: query
        config:
          field: job                 # поле результата, от которого показывается линк
          target:
            expr: 'sum(rate(http_requests_total{job="$${__field.labels.job}"}[5m])) by (status)'
          transformations: []
```

Создание через HTTP API (source UID — в пути; эндпоинты с провиженингом и `/api/datasources/uid/...` остаются рабочими, но в Grafana 13 `/api` считается legacy в пользу `/apis`):

```bash
GRAFANA="https://grafana.example.internal"
LOKI_UID="loki"
PROM_UID="prometheus"

# POST /api/datasources/uid/:sourceUID/correlations
curl -sS -X POST "$GRAFANA/api/datasources/uid/$LOKI_UID/correlations" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "targetUID": "'"$PROM_UID"'",
    "label": "Метрики ошибок сервиса",
    "description": "Prometheus: ошибки по сервису",
    "type": "query",
    "config": {
      "field": "job",
      "target": {
        "expr": "sum(rate(http_requests_total{job=\"${__field.labels.job}\"}[5m])) by (status)"
      },
      "transformations": []
    }
  }'
# → {"message":"Correlation created","result":{"uid":"50xhMlg9k",...}}
```

Просмотр и удаление:

```bash
# Все корреляции (пагинация: page, limit; фильтр sourceUID повторяемый)
curl -sS "$GRAFANA/api/datasources/correlations?limit=100" \
  -H "Authorization: Bearer $TOKEN" \
  | jq '.[] | {sourceUID, targetUID, label, provisioned}'

# Корреляции конкретного источника
curl -sS "$GRAFANA/api/datasources/uid/$LOKI_UID/correlations" \
  -H "Authorization: Bearer $TOKEN" | jq .

# DELETE /api/datasources/uid/:sourceUID/correlations/:correlationUID
curl -sS -X DELETE "$GRAFANA/api/datasources/uid/$LOKI_UID/correlations/<correlationUID>" \
  -H "Authorization: Bearer $TOKEN"
# → {"message":"Correlation deleted"}
```

Проверка: Explore → Loki → навести курсор на лейбл `job` в результате → появляется ссылка «Метрики ошибок сервиса» → клик открывает Prometheus с выполненным выражением и подставленным значением.

### Сценарий 7. Сквозная проверка цепочки (e2e drill)

```bash
# 1. Сгенерировать нагрузку с трейсингом (тестовый эндпоинт)
for i in $(seq 1 20); do curl -sS http://app.example.internal/slow >/dev/null & done

# 2. В Grafana: Explore → Prometheus → rate(...) — виден всплеск + exemplars
# 3. Клик по exemplar → Tempo открылся на трейсе со slow-span
# 4. Из спана → «Logs for this span» → Loki показал строки этого запроса
```

Цепочка считается настроенной, когда все три перехода выполняются без ручного копирования ID.

## Дополнительная информация

### Рекомендации по эксплуатации

- Используйте только internal-линки (`datasourceUid`): external URL ломаются при переименованиях и не проверяют права.
- Задавайте линки trace-to-* и корреляции через файлы провижнинга — они часть MaC и переносятся между стендами.
- В провиженинге экранируйте `$` как `$$` (YAML использует `$` для переменных окружения): `$${__value.raw}`, `$${__field.labels.*}`, `$$__tags`.
- Единый формат traceID в логах приложений (например, `traceID=<32hex>`) упрощает derivedFields до одного regex.
- Не расширяйте окна `spanStart/EndTimeShift` без нужды — большие окна дают шумные выборки логов.
- Service graph и trace-to-metrics требуют span metrics из сборщика/Tempo metrics-generator — см. `../Tempo/architecture_operations.md`.
- Для корреляций определяйте цель (`targetUID`) и поле (`config.field`) так, чтобы макрос `${__field.labels.<name>}` существовал в результате исходного запроса.

### Типичные ошибки и их решение

| Симптом | Причина | Решение |
| --- | --- | --- |
| Ромбиков exemplars нет на графике | Приложение не отдаёт exemplars / выключен `exemplar-storage` | Проверить `/api/v1/status/flags`, инструментацию приложения |
| Линк есть, трейс «Not found» | Tempo хранит ограниченное окно / sampling отсёк трейс | Сверить retention Tempo и стратегию sampling |
| Derived field не появляется | Regex не совпадает / ошибка YAML (`$$` vs `$`) | Экранировать `$${__value.raw}` в провиженинге, проверить regex на живой строке |
| Correlation открывается пустой | Неверные переменные интерполяции в target | Проверить имя лейбла (`${__field.labels.job}` существует в результате?) |
| Correlation не создаётся (404/403) | Неверный `sourceUID` в пути / источник провиженин и read-only | Указать `POST /api/datasources/uid/:sourceUID/correlations`, проверить права |
| Переход из спана даёт чужие логи | `filterByTraceID: false` и широкий сдвиг времени | Включить фильтр по traceID, сузить окно |
| Вкладка Metrics у спана пустая | В Tempo не включены span metrics | Включить `metrics_generator` со `span_metrics`, проверить target Prometheus |
| Пустой Service Graph | Нет метрик `traces_service_graph_*` в Prometheus | Настроить `serviceMap.datasourceUid`, включить span metrics |
| Trace-to-profiles не открывается | Нет источника Pyroscope / не включён span profiling | Добавить datasource Pyroscope, включить `span_profiling` в Tempo |

### Ограничения и особые случаи

- Exemplars поддерживаются не всеми типами панелей — рассчитывайте на time series; в таблицах/стат-панелях их нет.
- Хранение exemplars в Prometheus увеличивает потребление памяти; объём ограничен кольцевым буфером (`max_exemplars`), но при высокой кардинальности его стоит мониторить.
- Internal-линк derived field поддерживает только tracing-источники; `matcherType: label` извлекает значение из имени лейбла (regex по ключам, например `trace[_]?id`).
- trace-to-profiles требует источник Grafana Pyroscope; это отдельный продукт, не входящий в стек LGTM по умолчанию.
- Корреляции настраиваются через UI, провиженинг и API; `provisioned: true` означает управление из файла (изменения через UI для таких корреляций недоступны). Legacy-роуты `/api/datasources/...` в Grafana 13 помечены как deprecated в пользу `/apis`.
- Линки работают только там, где пользователь имеет права на целевой источник (RBAC применяется как обычно).

### Очистка и откат изменений

- Отключение exemplar-линка: убрать блок `exemplarTraceIdDestinations` из файла провижнинга и рестарт.
- Отключение trace-to-лог/метрик/профилей: удалить соответствующие блоки `tracesToLogsV2`/`tracesToMetrics`/`tracesToProfiles` и рестарт.
- Удаление корреляции: убрать запись из секции `correlations` файла провижнинга либо `DELETE /api/datasources/uid/:sourceUID/correlations/:correlationUID`.
- Выключение `--enable-feature=exemplar-storage` безопасно: данные exemplars перестают записываться, метрики не затрагиваются.

### Связанные темы

- [Источники данных](./grafana_datasources.md) — SSoT настройки и провижнинга источников.
- [Провиженинг](./grafana_provisioning.md) — файлы провижнинга Grafana.
- [Дашборды](./grafana-dashboards.md) — data links и переменные панелей.
- [Корреляция метрик и трейсов (Prometheus)](../Prometheus/concepts/exemplars.md) — exemplars и exemplar storage на стороне Prometheus.
- [Native Histograms и Exemplars (Mimir)](../Mimir/mimir_native_histograms_exemplars.md) — долговременное хранение exemplars.
- [Архитектура и операции Tempo](../Tempo/architecture_operations.md) — span metrics, metrics-generator, span profiling.
- [Интеграция OpenTelemetry с Grafana](../OpenTelemetry/grafana_integration.md) — сборка сигналов OTel.
- [Grafana Alloy](./grafana_alloy_overview.md) — сборщик телеметрии.
