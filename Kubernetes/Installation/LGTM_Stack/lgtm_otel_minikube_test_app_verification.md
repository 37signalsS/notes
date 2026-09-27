# Тестирование и верификация: LGTM Stack и OpenTelemetry на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)** (текущий)

---

## Перед началом работы

Данное руководство предполагает, что стек LGTM и OpenTelemetry уже развернуты. Перед продолжением убедитесь:

1. **Все компоненты работают:**
   ```bash
   kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus
   kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana
   kubectl get pods -n loki -app.kubernetes.io/name=loki
   kubectl get pods -n tempo -app.kubernetes.io/name=tempo
   kubectl get pods -n opentelemetry -app.kubernetes.io/name=opentelemetry-collector
   # → Expected: все поды в статусе Running, без CrashLoopBackOff
   ```

2. **Источники данных Grafana настроены:**
   ```bash
   kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80 &
   # Откройте http://localhost:3000 -> Configuration -> Data Sources
   # → Expected: Prometheus, Loki, Tempo присутствуют и помечены как Healthy
   ```

3. **OTel Collector доступен:**
   ```bash
   kubectl get svc -n opentelemetry
   # → Expected: сервис otel-collector с портами 4317 (gRPC), 4318 (HTTP), 8889 (metrics)
   ```

4. **Тестовое приложение доступно** (если планируется проверка с реальным приложением):
   ```bash
   kubectl get pods -l app=agent-example-app
   # → Expected: под в статусе Running
   ```

> **Важно:** Если какой-либо из компонентов не работает, вернитесь к предыдущим этапам руководства:
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**

---

## Назначение данного руководства

Данный файл является завершающим этапом серии руководств по развертыванию LGTM-стека на Minikube. Его цель — **верификация** (подтверждение работоспособности) уже развернутых компонентов, а не их настройка.

**Что проверяется:**
- Сквозная доставка данных от приложения через OTel Collector в Prometheus/Loki/Tempo.
- Корреляция между сигналами: Logs <-> Traces, Metrics -> Traces (Exemplars), Traces -> Logs.
- Генерация RED-метрик процессором `spanmetrics`.
- Наличие атрибутов ресурсов (pod name, namespace) во всех типах данных.

**Что НЕ проверяется в данном файле:**
- Настройка и конфигурация компонентов (см. предыдущие этапы).
- Производительность и нагрузочное тестирование.
- Production-сценарии (HA, распределенное хранилище, mTLS).

---

## Определения

**Автоматическая инструментация** — процесс внедрения механизмов сбора телеметрии (Tracer, Meter, Logger) в среду выполнения приложения без изменения его исходного кода. В Kubernetes реализуется через OpenTelemetry Operator и внедрение Sidecar или Init-контейнеров с агентами. Подробнее: **[Инструментация и SDK](../../../OpenTelemetry/instrumentation_sdk.md)**.

**Инъекция агента (Injection)** — механизм, при котором OpenTelemetry Operator автоматически добавляет необходимые переменные окружения и библиотеки (например, `opentelemetry-javaagent.jar`) в поды на основе аннотаций.

**Spanmetrics** — механизм генерации метрик (Request, Error, Duration — RED-метод) на основе данных трассировок непосредственно внутри OpenTelemetry Collector.

**Exemplars (Экземпляры)** — метаданные (например, TraceID), прикрепленные к конкретным точкам временных рядов в метриках. Позволяют осуществлять мгновенный переход от графиков (Prometheus) к соответствующим трассировкам (Tempo).

**Корреляция сигналов** — связывание метрик, логов и трассировок через общие идентификаторы (TraceID, SpanID) и атрибуты ресурсов. Подробнее: **[Архитектура и сигналы](../../../OpenTelemetry/architecture_signals.md)**.

---

## Основные концепции

### Схема взаимодействия компонентов

```text
┌─────────────────────────────────────────────────────────────────┐
│                    Minikube Cluster                             │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Pod: agent-example-app                     │   │
│  │                                                         │   │
│  │  ┌─────────────────┐      ┌─────────────────────────┐  │   │
│  │  │  Application    │      │  OTel Java Agent        │  │   │
│  │  │  (Spring Boot)  │◀─────│  (v2.29.0)              │  │   │
│  │  │                 │      │                         │  │   │
│  │  │  /ping endpoint │      │  Auto-instrumentation   │  │   │
│  │  └────────┬────────┘      └─────────────────────────┘  │   │
│  │           │                                             │   │
│  │           │ OTLP/gRPC (Port 4317)                       │   │
│  └───────────┼─────────────────────────────────────────────┘   │
│              │                                                 │
│              ▼                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │           OTel Collector (v0.155.0)                     │   │
│  │                                                         │   │
│  │  Receivers: OTLP (gRPC/HTTP)                             │   │
│  │  Processors: batch, spanmetrics, resourcedetection      │   │
│  │  Exporters: Tempo (traces), Loki (logs), Prometheus     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Выбор метода верификации

Для подтверждения работоспособности стека необходимо проверить четыре ключевых аспекта:

1.  **Сквозная доставка (Delivery):** Попадание данных от приложения в соответствующие хранилища (Prometheus, Loki, Tempo).
2.  **Корреляция сигналов (Correlation):**
    *   **Logs -> Traces:** Переход из Loki в Tempo по TraceID.
    *   **Metrics -> Traces:** Переход от точек на графике Prometheus к трейсу Tempo (через **Exemplars**).
    *   **Traces -> Logs:** Поиск логов, относящихся к конкретному спану (через **Traces to Logs**).
3.  **Генерация производных данных (Derived Data):** Наличие RED-метрик, созданных процессором `spanmetrics`.
4.  **Атрибуты ресурсов (Resource Detection):** Наличие метаданных инфраструктуры (pod name, namespace, container name) во всех типах сигналов.

### Ключевые параметры OpenTelemetry Java Agent (v2.x+)

| Переменная | Значение для Minikube | Описание |
| :--- | :--- | :--- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector.opentelemetry:4317` | Адрес коллектора в кластере |
| `OTEL_SERVICE_NAME` | `agent-example-app` | Идентификатор сервиса в Tempo/Loki/Prometheus |
| `OTEL_METRICS_EXPORTER` | `otlp` | Протокол для передачи метрик |
| `OTEL_LOGS_EXPORTER` | `otlp` | Протокол для передачи логов (включено в v2.x) |
| `OTEL_RESOURCE_ATTRIBUTES` | `service.namespace=demo` | Дополнительные атрибуты ресурса |

---

## Практические сценарии

### Сценарий 1: Развертывание тестового приложения с автоинструментацией

**Цель:** Запустить приложение и убедиться, что OpenTelemetry Operator успешно внедрил агент.

#### Шаг 1: Сборка и публикация образа

Используется локальный реестр, развернутый на этапе подготовки.

```bash
# Сборка приложения (пример для Spring Boot)
./gradlew bootBuildImage --imageName=registry.test:30000/agent-example-app:latest
# → Expected: BUILD SUCCESSFUL в несколько минут

# Публикация в локальный реестр
docker push registry.test:30000/agent-example-app:latest
# → Expected: digest: sha256:...

# Валидация: образ доступен в реестре
curl -s http://registry.test:30000/v2/agent-example-app/tags/list
# → Expected: {"name":"agent-example-app","tags":["latest"]}
```

> **Примечание:** Если образ уже собран ранее, шаг сборки можно пропустить. Убедитесь, что образ доступен в реестре.

#### Шаг 2: Создание ресурса Instrumentation

Перед запуском приложения необходимо создать конфигурацию инструментации в пространстве имен приложения.

```bash
kubectl apply -f - <<EOF
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: java-instrumentation
  namespace: default
spec:
  exporter:
    endpoint: http://otel-collector.opentelemetry:4317
  java:
    image: ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-java:2.29.0
EOF
# → Expected: instrumentation.opentelemetry.io/java-instrumentation created

# Валидация: Instrumentation создан и готов
kubectl get instrumentation java-instrumentation -n default
# → Expected: java-instrumentation   ...   http://otel-collector.opentelemetry:4317
```

#### Шаг 3: Запуск приложения с аннотацией

```bash
kubectl run agent-example-app \
  --image=registry.test:30000/agent-example-app:latest \
  --port=8080 \
  --labels="app=agent-example-app" \
  --annotations='instrumentation.opentelemetry.io/inject-java: "true"'
# → Expected: pod/agent-example-app created

# Ожидание запуска пода
kubectl wait --for=condition=ready pod/agent-example-app --timeout=120s
# → Expected: pod/condition met

# Валидация: агент внедрен (проверка init-контейнера)
kubectl describe pod agent-example-app | grep -A 5 "Init Containers"
# → Expected: init-контейнер otel-agent с образом autoinstrumentation-java

# Валидация: агент запущен и экспортирует данные
kubectl logs agent-example-app -c otel-agent --tail=10
# → Expected: логи инициализации агента (OTEL_EXPORTER_OTLP_ENDPOINT и т.д.)
```

---

### Сценарий 2: Верификация данных в Grafana

**Цель:** Проверить наличие всех типов сигналов и их взаимосвязь.

#### Шаг 1: Генерация нагрузки

```bash
# Проброс порта для доступа к API
kubectl port-forward pod/agent-example-app 8080:8080 &
# → Expected: Forwarding from 127.0.0.1:8080 -> 8080

# Ожидание готовности приложения
sleep 5

# Цикл запросов для генерации данных
for i in {1..10}; do curl -s localhost:8080/ping; echo ""; sleep 1; done
# → Expected:.responses от приложения (например, "pong" или HTTP 200)

# Валидация: данные отправлены в коллектор
kubectl logs -n opentelemetry -l app.kubernetes.io/name=opentelemetry-collector --tail=20 | grep -i "export"
# → Expected: логи об успешной экспорт данных (traces, metrics)
```

#### Шаг 2: Проверка корреляции (Logs -> Traces)

1. Откройте Grafana (`http://grafana.test`) -> **Explore**.
2. Выберите источник данных **Loki**.
3. Выполните запрос: `{service_name="agent-example-app"}`.
   ```promql
   {service_name="agent-example-app"}
   ```
4. **Валидация:** Должны отобразиться строки логов с timestamp.
5. Разверните любую строку лога. В поле `traceID` должна быть активная ссылка.
6. Нажмите на ссылку `traceID` — справа откроется панель с деталями трассировки из **Tempo**.
   > **Ожидаемый результат:** Спанны отображаются с иерархией, duration, атрибутами.

#### Шаг 3: Проверка корреляции (Metrics -> Traces через Exemplars)

1. В Explore выберите источник данных **Prometheus**.
2. Включите опцию **Exemplars** в интерфейсе запросов (кнопка в правом верхнем углу панели).
3. Выполните запрос к метрике, сгенерированной `spanmetrics`:
   ```promql
   calls_total{service_name="agent-example-app"}
   ```
4. **Валидация:** На графике должны появиться отдельные точки (**Exemplars**) — маленькие ромбики или кружки.
5. При наведении на точку появится TraceID. Нажмите на него для перехода к трейсу.

> **Примечание:** Если Exemplars не отображаются, проверьте:
> - Включена ли опция Exemplars в интерфейсе запросов Prometheus.
> - Есть ли данные в метрике `calls_total` (выполните запрос без фильтров).
> - Настроен ли `spanmetrics` в OTel Collector (см. **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**).

#### Шаг 4: Проверка корреляции (Traces -> Logs)

1. В окне просмотра трассировки (**Tempo**) найдите любой спан.
2. Нажмите на иконку документа или кнопку **Logs for this span**.
3. **Валидация:** Grafana автоматически сформирует запрос к Loki с фильтрацией по TraceID и временному интервалу спана.
4. **Ожидаемый результат:** Отображаются логи, соответствующие выбранному спану, с выделенным TraceID.

#### Шаг 5: Верификация атрибутов ресурсов (Resource Detection)

1. В любом сигнале (лог, трейс или метрика) проверьте наличие меток:
   - `k8s.pod.name`
   - `k8s.namespace.name`
   - `k8s.node.name`
2. **Валидация:** Наличие этих меток подтверждает, что процессор `resourcedetection` успешно обогатил данные информацией из API Kubernetes.
3. Дополнительно проверьте атрибуты `service.name` и `service.namespace`:
   - Для логов: в Loki Explore выполните `{service_name="agent-example-app"}` и раскройте Labels.
   - Для трейсов: в Tempo выберите спан и посмотрите в секцию Resource.

---

### Сценарий 3: Проверка RED-метрик (Spanmetrics)

**Цель:** Убедиться, что коллектор корректно агрегирует трейсы в метрики производительности.

#### Шаг 1: Запрос метрик в Prometheus

Выполните следующие запросы для проверки RED-метрик (Requests, Errors, Duration):

1. **Rate (Requests):** количество запросов в секунду
   ```promql
   rate(calls_total{service_name="agent-example-app"}[5m])
   ```
   **Валидация:** Значение должно быть > 0 (если нагрузка генерировалась).

2. **Error Rate:** доля ошибочных запросов
   ```promql
   rate(calls_total{service_name="agent-example-app", status_code="STATUS_CODE_ERROR"}[5m])
   ```
   **Валидация:** Если приложение не генерирует ошибки, значение будет 0.

3. **Latency (P99):** 99-й перцентиль длительности
   ```promql
   histogram_quantile(0.99, sum by (le) (rate(duration_milliseconds_bucket{service_name="agent-example-app"}[5m])))
   ```
   **Валидация:** Значение должно быть в миллисекундах (например, 50-500ms).

4. **Общая проверка:** Убедитесь, что метрики содержат атрибуты:
   ```promql
   calls_total{service_name="agent-example-app"}[0s]
   ```
   **Валидация:** В списке меток должны присутствовать `operation_name`, `status_code`, `span_kind`.

#### Шаг 2: Проверка метрик через API Prometheus

Для автоматизированной проверки можно использовать API:

```bash
# Проброс порта Prometheus
kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090 &

# Запрос количества метрик spanmetrics
curl -s 'http://localhost:9090/api/v1/label/__name__/values' | jq '.data[] | select(startswith("calls_total") or startswith("duration_milliseconds"))'
# → Expected: calls_total, duration_milliseconds_bucket, duration_milliseconds_count, duration_milliseconds_sum

# Проверка наличия данных за последнюю минуту
curl -s 'http://localhost:9090/api/v1/query?query=calls_total{service_name="agent-example-app"}' | jq '.data.result | length'
# → Expected: число > 0 (количество time series)
```

---

### Сценарий 4: Проверка сетевой связности между компонентами

**Цель:** Убедиться, что все компоненты стека могут взаимодействовать друг с другом внутри кластера.

#### Шаг 1: Проверка доступности OTel Collector

```bash
# Из пода приложения
kubectl exec pod/agent-example-app -- wget -qO- http://otel-collector.opentelemetry:8888/metrics 2>/dev/null | head -5
# → Expected: метрики внутренних очередей коллектора (otlp_receiver_accepted_spans и т.д.)

# Если wget недоступен, используйте curl
kubectl exec pod/agent-example-app -- curl -s http://otel-collector.opentelemetry:4317 2>/dev/null || echo "gRPC endpoint (порядок ожидаемый)"
```

#### Шаг 2: Проверка доступности Loki

```bash
# Проверка готовности Loki
kubectl exec -n opentelemetry deploy/otel-collector -- wget -qO- http://loki.loki:3100/ready 2>/dev/null
# → Expected: ready

# Проверка API Loki
kubectl exec -n opentelemetry deploy/otel-collector -- wget -qO- "http://loki.loki:3100/loki/api/v1/labels" 2>/dev/null
# → Expected: {"status":"success","data":[]}
```

#### Шаг 3: Проверка доступности Tempo

```bash
# Проверка готовности Tempo
kubectl exec -n opentelemetry deploy/otel-collector -- wget -qO- http://tempo.tempo:3200/ready 2>/dev/null
# → Expected: ready

# Проверка API Tempo (поиск трейсов)
kubectl exec -n opentelemetry deploy/otel-collector -- wget -qO- "http://tempo.tempo:3200/api/traces?q=%7B%7D&limit=1" 2>/dev/null | head -3
# → Expected: {"meta":{"...},"traces":[...]}
```

#### Шаг 4: Проверка доступности Prometheus

```bash
# Проверка Prometheus (из пода OTel Collector)
kubectl exec -n opentelemetry deploy/otel-collector -- wget -qO- http://prometheus-operated.monitoring:9090/-/healthy 2>/dev/null
# → Expected: Prometheus Server is Healthy.

# Проверка API Prometheus
kubectl exec -n opentelemetry deploy/otel-collector -- wget -qO- "http://prometheus-operated.monitoring:9090/api/v1/label/__name__/values" 2>/dev/null | head -5
# → Expected: {"status":"success","data":[...]}
```

---

## Дополнительная информация

### Устранение неисправностей

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Нет агента в поде** | Ошибка аннотации или Instrumentation | Проверить `kubectl get instrumentation`. Проверить `kubectl describe pod` (секция Init-контейнеров). |
| **Нет Exemplars в Prometheus** | Фича не включена в Prometheus | Проверить наличие `- exemplars` в `enableFeatures` в конфигурации Prometheus. |
| **Нет TraceID в логах** | Неверный формат логов приложения | Убедиться, что используется OTLP логгер и Java Agent v2.x. |
| **Collector: Context deadline exceeded** | Сетевая изоляция | Проверить NetworkPolicies и доступность порта 4317 в пространстве имен `opentelemetry`. |
| **Spanmetrics пустые** | Ошибка в пайплайне коллектора | Проверить `service.pipelines.metrics.processors`, должен содержать `spanmetrics`. |
| **Loki: циклическая ошибка push** | Loki не готов или неверный endpoint | Проверить `kubectl logs -n loki -l app.kubernetes.io/name=loki | grep -i error`. Убедиться, что Loki на порту 3100. |
| **Tempo: нет трейсов** | Неверный endpoint экспортера OTLP | Проверить `tempo.tempo:4317` в конфигурации Collector. Tempo должен быть в статусе `ready`. |
| **Grafana не показывает DataSource** | Сервис DataSource недоступен | Проверить DNS: `kubectl exec -n monitoring deploy/monitoring-grafana -- nslookup loki.loki`. |
| **Агент CrashLoopBackOff** | Несовместимость версий агента и ОС | Проверить `kubectl logs <pod> -c otel-agent`. Убедиться, что образ `autoinstrumentation-java:2.29.0` совместим с JDK приложения. |
| **Метрики spanmetrics дублируются** | Несколько экземпляров spanmetrics | Проверить, что `spanmetrics` определен только в одном pipeline (traces). |
| **Нет логов в Loki** | OTel Collector не экспортирует логи | Проверить pipeline `logs` в Collector: `processors` должен содержать `batch`, `exporters` — `loki`. |
| **Port-forward не работает** | Под перезапущен илипорт занят | Проверить `kubectl get pod <pod>`. Убить старый port-forward (`kill %1`) и перезапустить. |

### Диагностические команды

```bash
# Просмотр логов автоматической инструментации (агента)
kubectl logs agent-example-app -c otel-agent

# Проверка экспорта данных в коллекторе (поиск ошибок экспорта)
kubectl logs -n opentelemetry -l app.kubernetes.io/name=opentelemetry-collector --tail=100 | grep -i error

# Проверка наличия эндпоинтов для скрейпинга метрик
kubectl get endpoints -n monitoring

# Проверка ресурсов OTel (Instrumentation, Collector)
kubectl get otelcol,instrumentation -A

# Проверка метрик коллектора (длина очередей, батчи)
kubectl port-forward -n opentelemetry svc/otel-collector 8888:8888
# curl -s http://localhost:8888/metrics | grep -E "otelcol_receiver_accepted|otelcol_exporter_sent"

# Проверка готовности всех компонентов стека
for ns in monitoring loki tempo opentelemetry; do
  echo "=== Namespace: $ns ==="
  kubectl get pods -n $ns -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,READY:.status.conditions[?(@.type=="Ready")].status
done

# Проверка использования ресурсов
kubectl top pods -A --sort-by=memory | head -20

# Проверка событий ошибок в кластере
kubectl get events -A --field-selector type=Warning --sort-by='.lastTimestamp' | tail -20

# Проверка PVC (если настроена персистентность)
kubectl get pvc -A

# Проверка DNS-разрешения внутри пода
kubectl exec pod/agent-example-app -- nslookup otel-collector.opentelemetry.svc.cluster.local
```

### Ограничения и известные проблемы

| Ограничение | Описание | Обходной путь |
| :--- | :--- | :--- |
| **Только Java-приложения** | Демонстрация использует Java Agent v2.29.0 | Для Python/Node.js/.NET см. **[Инструментация и SDK](../../../OpenTelemetry/instrumentation_sdk.md)** |
| **Single-binary Tempo** | Нет распределенного хранения трейсов | Для production использовать Tempo Distributed |
| **Эфемерные данные** | Данные теряются при перезапуске Minikube | Настроить Persistence в **[развертывании стека](./lgtm_otel_minikube_lgtm_stack_deployment.md)** |
| **100% сэмплирование** | Все трейсы сохраняются (высокая нагрузка) | Для production включить tail-based sampling в OTel Collector |
| **Нет межсервисной корреляции** | Демонстрируется только один сервис | Для полной корреляции развернуть 2+ сервиса с общей трассировкой |

**Известные проблемы:**

1. **Задержка появления метрик:** После первого запроса метрики spanmetrics появляются в Prometheus через 15-30 секунд (задержка scrape + process_time).

2. **Loki: ошибка push при высокой нагрузке:** При одновременном отправлении >1000 строк/сек Loki может временно отклонять запросы. Решение: увеличить `-- distributors.rate-limit` в конфигурации Loki.

3. **Instrumentation и namespace:** Ресурс `Instrumentation` должен находиться в том же namespace, что и приложение, или быть доступен через RBAC.

4. **Конфликт портов:** Если OTel Collector уже использует порт 4317, другие компоненты не могут занять этот порт в той же network namespace.

### Лучшие практики тестирования

1. **Генерируйте достаточно данных:** Минимум 20-50 запросов для стабильных метрик spanmetrics. Один запрос не даст репрезентативных данных.

2. **Ждите Propagation:** После генерации данных ждите 30-60 секунд перед проверкой в Grafana (задержка scrape + обработка).

3. **Используйте API вместо UI:** Для автоматизации проверок используйте API Prometheus/Loki/Tempo вместо ручного UI.

4. **Проверяйте поэтапно:** Сначала убедитесь в доставке данных (Metrics/Logs/Traces по отдельности), затем проверяйте корреляцию.

5. **Фиксируйте окружение:** Перед тестированием сделайте снимок состояния (`kubectl get all -A > before-test.txt`), чтобы можно было откатить изменения.

6. **Очищайте данные между тестами:** Если проводите несколько итераций, очищайте старые данные, чтобы избежать путаницы.

### Очистка тестовых данных

Для удаления только тестового приложения (без удаления стека):

```bash
# Удаление тестового приложения
kubectl delete pod agent-example-app

# Удаление Instrumentation
kubectl delete instrumentation java-instrumentation -n default

# Очистка данных в Prometheus (метрики spanmetrics)
# Метрики автоматически удалятся по истечении retention (по умолчанию 15 дней)

# Очистка логов в Loki
# Логи автоматически удалятся по истечении retention (по умолчанию 7 дней)

# Проверка удаления
kubectl get pods -l app=agent-example-app
# → Expected: No resources found

kubectl get instrumentation -n default
# → Expected: No resources found
```

> **Примечание:** Удаление тестового приложения не влияет на работоспособность стека LGTM и OTel Collector.

### См. также
- **[OpenTelemetry: Инструментация и SDK](../../../OpenTelemetry/instrumentation_sdk.md)** — глубокое погружение в настройку агентов.
- **[Grafana: Визуализация и корреляция](../../../Grafana/grafana_overview.md)** — работа с дашбордами и источниками данных.
- **[Архитектура наблюдаемости: RED-метод](../../../Concepts/Observability_and_Monitoring/observability_definitions.md)** — теоретические основы метрик.

### Связанные материалы SSoT

- **[OpenTelemetry: Инструментация и SDK](../../../OpenTelemetry/instrumentation_sdk.md)**
- **[Архитектура и сигналы](../../../OpenTelemetry/architecture_signals.md)**
- **[Grafana: Обзор](../../../Grafana/grafana_overview.md)**

---

**Навигация по руководству:**

- **[Предварительные требования](./lgtm_otel_minikube_prerequisites_environment.md)** (назад)
- **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)** (назад)
- **[Production Hardening](./lgtm_production_hardening.md)** (вперед)

