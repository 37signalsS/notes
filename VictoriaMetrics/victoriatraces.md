# VictoriaTraces: хранение трейсов (pre-GA)

## Определения

**VictoriaTraces** — хранилище distributed-трейсов из экосистемы VictoriaMetrics, совместимое с API Tempo и Jaeger. Принимает данные по протоколу OpenTelemetry (OTLP). На 2026 год продукт находится в стадии перед официальным GA-релизом — использовать в проде с осторожностью и держать глаз на roadmap.

**VT component** — бинарник `victoria-traces` (single-node «VTSingle»); в кластерном варианте: `vtinsert`, `vtselect`, `vtstorage`.

**vtagent** — лёгкий агент для сбора/проксирования трейсов перед VictoriaTraces (как vmagent для метрик).

## Базовые концепции

### Основные API-точки (порт по умолчанию `10428`)

| Функция | Эндпоинт |
| :--- | :--- |
| OTLP/HTTP (приём трейсов) | `POST /insert/opentelemetry/v1/traces` |
| OTLP/gRPC (приём) | включается флагом `-otlpGRPCListenAddr` (например, `:4317`) |
| UI (VMUI) | `/select/vmui` |
| Jaeger Query Service (JSON API) | `/select/jaeger` |
| Tempo-совместимый API поиска | `/select/tempo/api/search`, `/api/traces/<traceID>`, `/api/tag` и др. |

### Место в стеке

```
HotROD / приложения → OTLP/HTTP (или gRPC) → vt (vtsingle) или vtagent → vtcluster
                                                │
Grafana (Jaeger datasource / Tempo datasource) ─┴── /select/jaeger, tempo API
```

## Практические сценарии

### 1. Быстрый старт single-node и приём OTLP/HTTP

```bash
# Запуск
victoria-traces -storageDataPath=/var/lib/victoria-traces

# Приём трейса (ОДИН JSON-объект в stdin)
curl -X POST -H 'Content-Type: application/json' --data-binary @- \
  http://localhost:10428/insert/opentelemetry/v1/traces <<'EOF'
{ "resourceSpans": [ ... ] }
EOF

# Или из контейнера HotROD:
docker run -p 8080-8083:8080-8083 --rm \
  --env OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://<host>:10428/insert/opentelemetry/v1/traces \
  jaegertracing/example-hotrod:latest all
```

### 2. OTLP/gRPC

```bash
victoria-traces -otlpGRPCListenAddr=:4317
# в Collector: otlp/with-tls endpoint=<host>:4317 + tls { cert_file, key_file }
```

### 3. Визуализация в Grafana

- Создайте **Jaeger** (или Tempo) datasource с URL вида `http://<victoria-traces>:10428/select/jaeger`.
- Или Tempo datasource, указывающий на `/select/tempo` API (search/tag/traces-by-id).

### 4. Клистер через оператор (CRD `VTCluster`)

```yaml
apiVersion: operator.victoriametrics.com/v1
kind: VTCluster
metadata:
  name: traces
spec:
  vtStorage:
    replicaCount: 3
  vtSelect:
    replicaCount: 2
  vtInsert:
    replicaCount: 2
```

Single-node — через `VTSingle`. Для быстрого старта также доступен Helm-чарт `victoria-traces-single` (`server.retentionPeriod`, `server.persistentVolume.size`).

## Валидация установки

```bash
curl -s http://localhost:10428/health
# → 200 OK

# Выполнить трейс-поиск через Tempo API
curl -s 'http://localhost:10428/select/tempo/api/search?limit=5' | jq .
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| 404 на /insert | Не тот порт/путь (частая путаница с 8538) | Обращаться на `:10428/insert/opentelemetry/v1/traces` |
| gRPC не принимается | Не включён `-otlpGRPCListenAddr` | Запустить с флагом (gRPC-приём выключен по умолчанию) |
| Спаны не видны в UI | Эндпоинт экспортера отличался | Проверить вывод OTLP-экспортера в логах vt; соотнести `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` |
| Jaeger datasource не показывает | Порт/путь datasource неверен | URL datasource `...:10428/select/jaeger` (Jaeger Query API) |
| Нет данных в Grafana | Ошибка синхронизации времени | Проверить в VMUI (`/select/vmui`) независимо от Grafana |

## Рекомендации по эксплуатации

- Следите за статусом продукта: до GA изменения API/данных не гарантированы — изолируйте на stage до официального релиза.
- Для приёма из многих источников используйте `vtagent` или общедоступный OpenTelemetry Collector, направляя его на `/insert/opentelemetry/v1/traces`.
- Retention задаётся как у метрик: `-retentionPeriod` / соответствующее поле StatefulSet.

## Ограничения и особые случаи

- Поддерживается OTLP (HTTP и gRPC), а не широкий спектр фоновых SDK-протоколов «из коробки» — перенаправляйте разнородные источники через Collector.
- Query API реализован в виде Tempo-/Jaeger-совместимых подмножеств — не все функции Tempo (например, traceQL) гарантированы.
- Pre-GA: не планируйте его как единственное хранилище для боевых трейсов без резервного сценария и проверки changelog.

## Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md) — позиция продукта в стеке;
- [vmauth](./vmauth_overview.md) — как прикрыть `/insert`/`/select`;
- [OpenTelemetry: обзор](../OpenTelemetry/opentelemetry_overview.md) — сбор и агрегация трейсов перед VictoriaTraces.