# Exemplars и корреляция метрик с трейсами

> **См. также:** [HTTP API (Exemplars)](../prometheus_api.md), [Конфигурация](../configuration.md), [Native Histograms](./metric_types/histogram.md), [Корреляция в Grafana](../../Grafana/grafana_correlation_exemplars.md), [Mimir Exemplars](../../Mimir/mimir_native_histograms_exemplars.md).

## Определения

* **Exemplar** — точка-метка на временном ряде, хранящая ссылку на конкретный трейс (обычно `trace_id`). Позволяет перейти от всплеска на графике метрик к конкретному запросу в системе трассировки (Jaeger, Tempo).
* **Корреляция метрик и трейсов** — механизм связывания двух сигналов observability: метрики показывают симптом (всплеск задержки), трейсы — причину (конкретный медленный запрос).
* **Exemplar Storage** — хранилище exemplars в TSDB. В Prometheus v3.x включено по умолчанию при использовании нативных гистограмм. В v2.x требует флага `--enable-feature=exemplar-storage`.
* **Trace ID** — уникальный идентификатор распределенного трейса, передаваемый как значение метки в exemplar (например, `{trace_id="a1b2c3d4"}`).

## Основные концепции

### Зачем нужны exemplars

```
Метрика (Grafana) --> Exemplar (ссылка) --> Трейс (Tempo/Jaeger) --> Логи (Loki)
```

1. **Отладка всплесков:** При алерте на высокую задержку exemplar позволяет перейти к конкретному запросу, который вызвал всплеск.
2. **Root Cause Analysis:** Из трейса видно, какой именно спан (операция) был медленным.
3. **Связь с логами:** Из спана трейса можно перейти к логам этого конкретного запроса через Loki.

### Формат данных

Exemplars передаются в формате OpenMetrics:

```text
http_request_duration_seconds_bucket{le="0.5"} 12 # {trace_id="a1b2c3d4"} 0.452
http_request_duration_seconds_bucket{le="1"} 24 # {trace_id="e5f6g7h8"} 0.891
```

**Структура:**
- `#` — начало exemplar
- `{trace_id="..."}` — метки exemplar (ссылка на трейс)
- `0.452` — значение метрики в момент этого exemplar

### Конфигурация в Prometheus

**Предварительное требование.** Хранилище exemplars отключено по умолчанию и включается feature flag при запуске сервера:

```bash
prometheus --config.file=/etc/prometheus/prometheus.yml --enable-feature=exemplar-storage
```

Размер кольцевого буфера задаётся в секции верхнего уровня `storage` — **не** внутри `scrape_configs`:

```yaml
storage:
  exemplars:
    max_exemplars: 100000  # Размер буфера в памяти на все ряды

scrape_configs:
  - job_name: 'service-with-traces'
    scrape_native_histograms: true
```

**Ключевые параметры:**
- `max_exemplars`: Максимальное количество exemplars в кольцевом буфере, по умолчанию 100000. Буфер общий для всех рядов, а не выделяется на каждую метрику.
- Exemplar, содержащий только `trace_id`, занимает в этом буфере порядка 100 байт.
- При Remote Write exemplars отправляются только если `send_exemplars: true` и бэкенд поддерживает protobuf.

### Инструментация приложений

#### Go

```go
func recordRequest(method, code string, duration float64, traceID string) {
    nativeHistogram.WithLabelValues(method, code).Observe(duration,
        prometheus.WithExemplars(
            prometheus.Labels{"trace_id": traceID},
        ),
    )
}
```

#### Python

```python
histogram.labels(method="GET", code="200").observe(
    duration,
    exemplar={"trace_id": format(trace_id, '032x')}
)
```

### Интеграция с Grafana

Конфигурация datasource в Grafana для отображения exemplars:

```yaml
jsonData:
  exemplarTraceIdDestinations:
    - datasourceUid: tempo
      name: TraceID
      urlDisplayLabel: "Открыть трейс"
```

### HTTP API для exemplars

```bash
# Запрос exemplars для конкретной метрики
curl 'http://localhost:9090/api/v1/exemplars?match[]={__name__="http_request_duration_seconds"}'
```

### Remote Write и exemplars

| Параметр | По умолчанию | Описание |
|:---|:---|:---|
| `send_exemplars` | `false` | Включает отправку exemplars вместе с метриками |

**Важно:** При Remote Write exemplars отправляются только если бэкенд поддерживает protobuf и флаг `send_exemplars: true`.

### Ограничения и особенности

1. **Память:** Exemplars хранятся в отдельном блоке Head в TSDB и потребляют дополнительную память. При высокой кардинальности снизьте `max_exemplars`.
2. **Совместимость:** Не все LTS поддерживают exemplars. Проверьте поддержку в документации вашего хранилища.
3. **Sampling:** Если приложение отправляет не все трейсы (sampling), не все запросы будут иметь exemplars.
4. **Retention:** Время хранения exemplars зависит от retention TSDB и LTS.

## Практические примеры

### Полный цикл: метрика -> exemplar -> трейс -> логи

```bash
# 1. Сгенерировать нагрузку с трейсингом
for i in $(seq 1 20); do
  curl -sS http://app.example.internal/slow >/dev/null &
done

# 2. В Grafana: Explore -> Prometheus -> rate(...)
#    Виден всплеск + exemplars (ромбики на графике)

# 3. Клик по exemplar -> Tempo открылся на трейсе со slow-span

# 4. Из спана -> "Logs for this span" -> Loki показал строки этого запроса
```

### Конфигурация Docker Compose

```yaml
services:
  prometheus:
    image: prom/prometheus:v3.1.0
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--enable-feature=exemplar-storage'
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml

  tempo:
    image: grafana/tempo:2.6.0
    command: ['-config.file=/etc/tempo/config.yaml']

  grafana:
    image: grafana/grafana:11.4.0
    environment:
      - GF_DATASOURCES_DEFAULT_NAME=Prometheus
    volumes:
      - ./datasources.yml:/etc/grafana/provisioning/datasources/datasources.yml
```

### Конфигурация Grafana datasource

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    jsonData:
      exemplarTraceIdDestinations:
        - datasourceUid: tempo
          name: traceID
          urlDisplayLabel: "Open Trace"
  - name: Tempo
    type: tempo
    uid: tempo
    url: http://tempo:3200
```

### Диагностика проблем

| Симптом | Причина | Решение |
|:---|:---|:---|
| Ромбиков exemplars нет на графике | Приложение не отдаёт exemplars / выключен exemplar-storage | Проверить `/api/v1/status/flags`, инструментацию приложения |
| Линк есть, трейс "Not found" | Tempo хранит ограниченное окно / sampling отсёк трейс | Сверить retention Tempo и стратегию sampling |
| Grafana не показывает Exemplars | `exemplar-storage` не включен (v2.x) | Добавить `--enable-feature=exemplar-storage` или перейти на v3.x |
| Высокое потребление памяти | Слишком высокий `max_exemplars` при высокой кардинальности | Снизить `max_exemplars` или использовать `metric_relabel_configs` |

## Дополнительная информация

* **HTTP API:** [HTTP API Prometheus (Exemplars)](../prometheus_api.md)
* **Конфигурация:** [Конфигурация Prometheus](../configuration.md)
* **Native Histograms:** [Histogram](./metric_types/histogram.md)
* **Grafana корреляция:** [Корреляция метрик и трейсов](../../Grafana/grafana_correlation_exemplars.md)
* **Mimir + Exemplars:** [Native Histograms и Exemplars](../../Mimir/mimir_native_histograms_exemplars.md)
* **OpenTelemetry:** [Архитектура сигналов](../../OpenTelemetry/architecture_signals.md)
* **Клиентские библиотеки:** [Client Libraries](../Exporters/extensibility/client_libraries.md)
