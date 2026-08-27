# Grafana: Корреляция телеметрии — Exemplars, Trace-to-*, Correlations

Практическое руководство по связыванию метрик, логов и трейсов в Grafana: exemplars на графиках, линковки trace→logs/metrics/profiles в настройках источников, correlations (запрос→запрос) в Explore. Архитектура трейсинга — в `../Tempo/`, сборка телеметрии — `../OpenTelemetry/` и [Graf Alloy](grafana_alloy_overview.md). Облачные и ИИ-функции не рассматриваются.

## Определения

- **Exemplar** — точка-метка на временном ряде, хранящая ссылку на конкретный трейс (обычно `TraceID`); позволяет от «всплеска на графике» перейти к конкретному запросу.
- **Exemplar storage** — экспериментальная фича Prometheus (`--enable-feature=exemplar-storage`) для хранения exemplars; приложения должны передавать traceID в метрики (через OpenTelemetry/клиентские библиотеки).
- **Trace-to-metrics / Trace-to-logs / Trace-to-profiles** — настройки источника данных Tempo, добавляющие ссылки из спана трейса к связанным данным.
- **Derived field** — вычисляемое поле в источнике Loki (regex по строке лога), из которого делается ссылка, например, на Tempo по извлечённому traceID.
- **Correlation** — связь «источник A → источник B» в Explore: клик по полю результата открывает целевой источник с подставленным значением (переменная интерполяции `${__value.raw}`, `${__field.labels.*}`).

## Базовые концепции

Зачем корреляция: при инциденте инженер двигается по цепочке «симптом → причина»: график (метрика) показывает всплеск ошибок → exemplar/trace-link открывает медленный или ошибочный трейс → из спанов переход в логи этого конкретного запроса. Без настроенных линковок этот путь выполняется вручную (копирование traceID между вкладками), что замедляет диагностику.

Как это устроено:

1. **Ссылки задаются в настройках источников данных**, а не в дашбордах — тогда работают во всех панелях и Explore автоматически. Провижинятся через `jsonData` источника (см. [Провиженинг](grafana_provisioning.md)).
2. Связь может быть **internal** (переход внутри Grafana в другой источник по `datasourceUid` — рекомендуемый способ) или **external** (URL с интерполяцией).
3. Для exemplars цепочка начинается на стороне приложения: инструментирование должно прокидывать traceID в метрики; иначе Grafana просто не покажет точки-exemplars.

Типовая топология связей: Prometheus ⇄ Tempo, Loki → Tempo (derived fields), Tempo → Loki/Prometheus/Pyroscope.

## Практические сценарии

### Предварительные требования

- Работающий Tempo и Loki как источники данных в Grafana (uid известны).
- Приложение инструментировано OpenTelemetry (traceID в логах и метриках); сборщик — Alloy/OTel Collector (см. `../OpenTelemetry/otlp_protocol.md`).
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
    enabled: true                  # service graph / нод-граф трейса
```

Проверка: открыть любой трейс в Tempo → выбрать спан → кнопка «Logs for this span» открывает Loki с фильтром по traceID; строки логов содержат тот же traceID.

### Сценарий 3. Derived fields: из строки лога в трейс (Loki → Tempo)

```yaml
# provisioning/datasources/loki.yaml (фрагмент jsonData)
jsonData:
  derivedFields:
    - name: TraceID
      matcherRegex: 'traceID=(\w+)'   # что вырезать из строки лога
      datasourceUid: tempo            # internal-линк
      url: "$${__value.raw}"          # экранирование $ обязательно в YAML провижининга
```

Проверка: в Explore выполнить `{job="myapp"} |= "traceID"` → у строк появился синий линк TraceID → клик открывает трейс в Tempo. Если линка нет — regex не совпадает с форматом лога (проверьте реальную строку).

### Сценарий 4. Correlations: произвольная связь запрос→запрос

Пример: из лога ошибки в Loki — к метрике ошибок сервиса в Prometheus.

```bash
curl -sS -X POST "$GRAFANA/api/datasources/correlations/<loki-uid>" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "targetUID": "<prometheus-uid>",
    "label": "Метрики ошибок сервиса",
    "config": {
      "type": "query",
      "target": {
        "expr": "sum(rate(http_requests_total{job=\"${__field.labels.job}\"}[5m])) by (status)"
      },
      "transformations": []
    }
  }'
# → {"message":"Correlation created","id":...}
```

Проверка: Explore → Loki → навести курсор на лейбл `job` в результате → появится линк «Метрики ошибок сервиса» → клик открывает Prometheus с выполненным выражением и подставленным значением.

Управление списком:

```bash
curl -sS "$GRAFANA/api/datasources/correlations" -H "Authorization: Bearer $TOKEN" | jq '.correlations[] | {sourceUID, targetUID, label}'
curl -sS -X DELETE "$GRAFANA/api/datasources/correlations/<loki-uid>/<corr-id>" -H "Authorization: Bearer $TOKEN"
```

### Сценарий 5. Сквозная проверка цепочки (e2e drill)

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
- Задавайте линки через файлы провижнинга — они часть MaC и переносятся между стендами.
- Единый формат traceID в логах приложений (например, `traceID=<32hex>`) упрощает derivedFields до одного regex.
- Не расширяйте окна `spanStart/EndTimeShift` без нужды — большие окна дают шумные выборки логов.
- Service graph требует данных из сборщика (span metrics) — см. `../Tempo/architecture_operations.md`.

### Типичные ошибки и их решение

| Симптом | Причина | Решение |
| --- | --- | --- |
| Ромбиков exemplars нет на графике | Приложение не отдаёт exemplars / выключен `exemplar-storage` | Проверить `/api/v1/status/flags`, инструментацию приложения |
| Линк есть, трейс «Not found» | Tempo хранит ограниченное окно / sampling отсёк трейс | Сверить retention Tempo и стратегию sampling |
| Derived field не появляется | Regex не совпадает / ошибка YAML (`$$` vs `$`) | Экранировать `$${__value.raw}` в провижининге, проверить regex на живой строке |
| Correlation открывается пустой | Неверные переменные интерполяции в target | Проверить имя лейбла (`${__field.labels.job}` существует в результате?) |
| Переход из спана даёт чужие логи | `filterByTraceID: false` и широкий сдвиг времени | Включить фильтр по traceID, сузить окно |

### Ограничения и особые случаи

- Exemplars поддерживаются не всеми типами панелей — рассчитывайте на time series; в таблицах/стат-панелях их нет.
- Хранение exemplars в Prometheus увеличивает потребление памяти; объём обычно невелик (ограничен на сторону), но мониторьте.
- Correlations настраиваются API/UI — файлового провижнинга нет (на момент 13.x); фиксируйте их скриптами в Git.
- Линки работают только там, где пользователь имеет права на целевой источник (RBAC применяется как обычно).

### Очистка и откат изменений

- Отключение exemplar-линка: убрать блок `exemplarTraceIdDestinations` из файла провижнинга и рестарт.
- Удаление correlation: `DELETE /api/datasources/correlations/{sourceUID}/{id}`.
- Выключение `--enable-feature=exemplar-storage` безопасно: данные exemplars перестают записываться, метрики не затрагиваются.

### Актуальность и статус

Exemplars и trace-to-logs стабильно работают в 11.x–13.x (`tracesToLogsV2` — актуальная форма настроек вместо устаревшей `tracesToLogs`). Correlations GA начиная с 10.x, API стабилен.

### Связанные темы

- [Источники данных](grafana_datasources.md)
- [Провиженинг](grafana_provisioning.md)
- [Grafana Alloy — обзор](grafana_alloy_overview.md)
- `../Tempo/architecture_operations.md` — хранение, sampling, span metrics
- `../Loki/loki_overview.md` — LogQL и архитектура Loki
