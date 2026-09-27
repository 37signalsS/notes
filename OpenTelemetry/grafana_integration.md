# OpenTelemetry: Интеграция с Grafana

## Определения

**Интеграция OpenTelemetry с Grafana** — это процесс настройки визуализации и анализа телеметрических данных, собранных с помощью OpenTelemetry, в системе мониторинга Grafana. Grafana поддерживает различные backend-системы для хранения данных OTel: Tempo для трассировок, Loki для логов, Prometheus/Mimir для метрик.

В 2026 году Grafana является центральным компонентом стека LGTM (Loki, Grafana, Tempo, Mimir), который обеспечивает полную наблюдаемость.

## Теоретический блок

### Архитектура интеграции

```text
Приложение (OTel SDK) → OTel Collector → Backend (Tempo/Loki/Prometheus)
                                                ↓
                                          Grafana (визуализация)
```

### Компоненты Grafana для OTel

| Компонент | Назначение | Протокол |
| :--- | :--- | :--- |
| **Tempo** | Хранение и запрос трассировок | OTLP, Jaeger, Zipkin |
| **Loki** | Хранение и запрос логов | OTLP, Push API |
| **Prometheus** | Хранение и запрос метрик | OTLP, Remote Write |
| **Mimir** | Масштабируемое хранилище метрик | Remote Write |

### Преимущества интеграции

- **Единый интерфейс** — все сигналы визуализируются в одном месте.
- **Корреляция сигналов** — возможность перехода между метриками, логами и трассировками.
- **Dashboards as Code** — управление дашбордами через код (Terraform, provisioning).
- **Алертинг** — настройка алертов на основе метрик OTel.

## Практические сценарии

### Сценарий 1: Отправка трассировок в Tempo

**Конфигурация OTel Collector:**

```yaml
exporters:
  otlp/tempo:
    endpoint: "tempo:4317"
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp/tempo]
```

**Настройка Tempo в Grafana:**

```yaml
# provisioning/datasources/tempo.yaml
apiVersion: 1
datasources:
  - name: Tempo
    type: tempo
    uid: tempo
    url: http://tempo:3100
    isDefault: true
    jsonData:
      tracesToLogsV2:
        datasourceUid: loki
        filterByTraceID: true
      serviceMap:
        datasourceUid: prometheus
      nodeGraph:
        enabled: true
```

### Сценарий 2: Отправка логов в Loki

**Конфигурация OTel Collector:**

```yaml
exporters:
  loki:
    endpoint: "http://loki:3100/loki/api/v1/push"

service:
  pipelines:
    logs:
      receivers: [otlp, filelog]
      processors: [memory_limiter, batch]
      exporters: [loki]
```

**Настройка Loki в Grafana:**

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
```

### Сценарий 3: Отправка метрик в Prometheus

**Конфигурация OTel Collector:**

```yaml
exporters:
  prometheus:
    endpoint: "0.0.0.0:8889"
    namespace: "otel"

service:
  pipelines:
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [prometheus]
```

**Настройка Prometheus в Grafana:**

```yaml
# provisioning/datasources/prometheus.yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    uid: prometheus
    url: http://prometheus:9090
    jsonData:
      exemplarTraceIdDestinations:
        - datasourceUid: tempo
          name: TraceID
```

### Сценарий 4: Корреляция сигналов

**Настройка exemplars в Prometheus → Tempo:**

```yaml
# В настройках Prometheus
otlp:
  promote_resource_attributes:
    - service.name

# В настройках Grafana Tempo
jsonData:
  tracesToMetrics:
    datasourceUid: prometheus
    queries:
      - name: "Request rate"
        query: "sum(rate(http_server_request_duration_seconds_count{$$__tags}[5m]))"
      - name: "Error rate"
        query: "sum(rate(http_server_request_duration_seconds_count{$$__tags,http_status_code=~\"5..\"}[5m]))"
```

### Сценарий 5: Дашборд для OTel метрик

**Пример панели для визуализации метрик OTel:**

```json
{
  "title": "OpenTelemetry Collector Metrics",
  "type": "timeseries",
  "targets": [
    {
      "expr": "rate(otelcol_receiver_accepted_spans_total[5m])",
      "legendFormat": "Accepted Spans - {{instance}}"
    },
    {
      "expr": "rate(otelcol_receiver_refused_spans_total[5m])",
      "legendFormat": "Refused Spans - {{instance}}"
    }
  ],
  "fieldConfig": {
    "defaults": {
      "unit": "short"
    }
  }
}
```

## Дополнительная информация

### Типичные проблемы и решение

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Grafana не видит Tempo** | Неверный URL или DNS | Проверить `http://tempo:3100` внутри Docker сети |
| **Нет корреляции traces↔logs** | Не настроены derived fields | Проверить настройки Loki в Grafana |
| **Exemplars не отображаются** | Приложение не передает traceID в метрики | Настроить OTel SDK для передачи exemplars |
| **Дашборды пустые** | Метрики не доходят до Prometheus | Проверить scrape конфигурацию и метрики Collector |

### Best Practices

1. **Используйте provisioning** — автоматизируйте настройку datasource в Grafana.
2. **Настройте корреляцию** — это ключевое преимущество Grafana.
3. **Используйте variables** — создавайте динамические дашборды с переменными.
4. **Экспортируйте дашборды** — храните дашборды как код в Git.
5. **Мониторьте саму Grafana** — используйте метрики Grafana для мониторинга производительности.

### Ссылки

- [Grafana OTel Documentation](https://grafana.com/docs/grafana/latest/datasources/opentelemetry/)
- [Grafana Tempo](https://grafana.com/docs/tempo/latest/)
- [Grafana Loki](https://grafana.com/docs/loki/latest/)
- [Grafana Provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
