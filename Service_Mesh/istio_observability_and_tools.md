# Наблюдаемость в Istio: Kiali, телеметрия и федерация идентичности

**Актуально для:** Istio 1.31.x

## Определения

**Наблюдаемость (Observability)** в Istio — это совокупность инструментов и практик для глубокого анализа состояния сервисной сетки (Service Mesh), визуализации топологии трафика, мониторинга производительности и распределенной трассировки запросов. В 2026 году наблюдаемость строится на стандартах **OpenTelemetry** и **W3C Trace Context**, а конфигурация Waypoint Proxy использует **Gateway API**.

**Kiali** — центральная консоль управления и визуализации для Istio. Она предоставляет графическое представление графа зависимостей сервисов, отслеживает "золотые сигналы" (RPS, ошибки, задержки) и валидирует корректность конфигураций.

**Dex / Keycloak** — провайдеры идентификации (Identity Providers), использующие протокол **OIDC (OpenID Connect)** для организации безопасного ролевого доступа (RBAC) к инструментам мониторинга. Полноценный IAM-сервер на базе Keycloak рассмотрен отдельно: [Keycloak](../Security/Tools/keycloak_overview.md).

**Grafana Alloy** — универсальный коллектор телеметрии, заменяющий специализированные агенты (Promtail, Grafana Agent, tempo-query). В связке с Istio скрапит метрики Envoy с порта `15090/stats/prometheus` и метрики Istio-агента с порта `15020`.

---

## Основные концепции

### Стек наблюдаемости 2026 года

Современная архитектура мониторинга Istio (1.31.x) интегрируется со стеком **LGTM** (Loki, Grafana, Tempo, Mimir) через универсальный агент **Grafana Alloy**.

| Компонент | Роль | Примечание |
| :--- | :--- | :--- |
| **Prometheus / Mimir** | Сбор и хранение метрик. | Используется Kiali для отображения состояния здоровья (Health) сервисов. |
| **Grafana Tempo** | Распределенная трассировка (Tracing). | Заменяет Jaeger в большинстве современных инсталляций. Хранит данные в объектном хранилище. |
| **Grafana Loki** | Централизованный сбор логов. | Позволяет Kiali отображать логи Envoy напрямую в интерфейсе. |
| **Grafana Alloy** | Единый коллектор телеметрии. | Заменяет специализированные агенты. Скрапит метрики Envoy с порта `15090/stats/prometheus` (через `istio-proxy`). В Sidecar-модели дополнительно читает объединённые метрики Istio-агента с порту `15020`. |
| **Kiali (v2.28+)** | Визуализация и управление. | Поддерживает Ambient Mesh (Ztunnel/Waypoint), Gateway API, а также вкладку графического графа трафика. Актуальная ветка — 2.28 (июнь 2026). |

### Telemetry API (telemetry.istio.io)

В Istio 1.31.x настройка телеметрии централизована через ресурс **`Telemetry`** (API-группа `telemetry.istio.io/v1`). Он заменяет устаревшие пер-прокси аннотации и `MeshConfig`-фрагменты для метрик, логов и трейсов. Ресурс привязывается к workloads через `selector` или к мешу/неймспейсу как global/default:

| Поле | Назначение |
| :--- | :--- |
| `spec.metrics` | Кастомизация метрик (переопределение тегов, размера гистограмм). |
| `spec.accessLogging` | Включение/отключение access-логов Envoy и выбор провайдера (например, OpenTelemetry). |
| `spec.tracing` | Конфигурация трассировки: провайдер (OTLP/Stackdriver/Zipkin), `randomSamplingPercentage`, пользовательские теги. |

Пример ресурса, включающего access-логи и трассировку через OpenTelemetry для workloads с меткой `app=checkout`:

```yaml
apiVersion: telemetry.istio.io/v1
kind: Telemetry
metadata:
  name: checkout-otel
  namespace: checkout
spec:
  selector:
    matchLabels:
      app: checkout
  accessLogging:
  - providers:
    - name: otel
  tracing:
  - providers:
    - name: otel
    randomSamplingPercentage: 100
```

Провайдеры (`otel`, `prometheus` и др.) регистрируются в `istiod` через `meshConfig.extensionProviders` — там задаются endpoint и транспорт (gRPC `4317` / HTTP `4318`). Подробности протокола: [OTLP](../OpenTelemetry/otlp_protocol.md).

### Золотые сигналы SRE в Istio

Наблюдаемость в меше строится вокруг четырёх золотых сигналов (Golden Signals), каждый из которых имеет конкретные реализации в Istio:

| Сигнал | Istio-метрика | Источник | Порог (рекомендуемый) |
| :--- | :--- | :--- | :--- |
| **Traffic (Трафик)** | `istio_requests_total` | Envoy/Prometheus | Мониторинг RPS per service |
| **Errors (Ошибки)** | `istio_requests_total{response_code=~"5.."}` | Envoy/Prometheus | >1% доля 5xx → инцидент |
| **Latency (Задержка)** | `envoy_cluster_upstream_rq_time` | Envoy Admin API | P99 > 1s → алерт |
| **Saturation (Насыщение)** | `envoy_cluster_upstream_cx_active` | Envoy Admin API | >80% от `max_connections` |

В режиме Ambient Mesh:
- L4-сигналы собираются **Ztunnel** (метрики `istio_tcp_connections_opened_total`, `istio_tcp_sent_bytes_total`).
- L7-сигналы собираются **Waypoint Proxy** (стандартные Envoy-метрики).

### Envoy Admin Stats

Каждый прокси (sidecar, waypoint) exposes admin-интерфейс на порту `15000`. Статистика разделена на иерархические счётчики:

```bash
# Общая статистика по слушателям
kubectl exec -n <ns> <pod> -c istio-proxy -- curl -s 127.0.0.1:15000/stats | grep listener

# Статистика по конкретному кластеру (upstream-сервису)
kubectl exec -n <ns> <pod> -c istio-proxy -- curl -s 127.0.0.1:15000/stats | grep "cluster.outbound|8080||my-service"

# Пул соединений
kubectl exec -n <ns> <pod> -c istio-proxy -- curl -s 127.0.0.1:15000/stats | grep "cx_"
# → upstream_cx_total: 500
# → upstream_cx_active: 5
# → upstream_cx_connect_timeout: 3

# Гистограммы задержек (если включены в bootstrap)
kubectl exec -n <ns> <pod> -c istio-proxy -- curl -s "127.0.0.1:15000/stats?format=histogram" | grep "outbound|8080"
# → outbound|8080||my-service.prod.svc.cluster.local: P50=2ms,P99=15ms,P999=50ms
```

Ключевые счётчики:
- `upstream_rq_total` — общее количество запросов к upstream.
- `upstream_rq_5xx` — количество ответов 5xx.
- `upstream_cx_active` — активные соединения к upstream.
- `upstream_cx_connect_timeout` — количество таймаутов соединений.
- `downstream_cx_total` — входящие соединения.

### Визуализация трафика в Kiali

Kiali использует цветовую и символьную индикацию для быстрой диагностики:

- **Цвета ребер (Edges):**
  - **Зеленый:** успех (2xx/3xx).
  - **Оранжевый:** предупреждение (ошибки 4xx).
  - **Красный:** критическое состояние (ошибки 5xx > 5%).
- **Типы трафика (Ambient Mesh GA):**
  - **Синие линии:** трафик уровня L4, обрабатываемый **Ztunnel**. Важно: Ztunnel отчитывается о всех соединениях как о **TCP** (даже для HTTP), так как работает на L4.
  - **Зелёные линии:** трафик уровня L7, проходящий через **Waypoint Proxy** и отчитывающийся уже по реальному протоколу (HTTP).
  - **Двойные рёбра:** когда неймспейс находится в Ambient Mesh с включённым Waypoint, Ztunnel и Waypoint формируют раздельные отчёты — в графе появляются двойные рёбра между узлами. Панель инструментов `Traffic` позволяет отфильтровать граф по репортёру (Ztunnel/Waypoint) и протоколам.
  - **HBONE:** в Ambient вместо TCP поды используют защищённый протокол **HBONE** (HTTP-Based Overlay Network Environment) — прозрачно инкапсулируемый Ztunnel.
- **Безопасность:** иконка закрытого замка на линии трафика подтверждает активное **mTLS** соединение с проверкой сертификатов.

---

## Предпосылки

Перед настройкой наблюдаемости выполните проверку:

- **Istio 1.31.x** с включённым профилем `ambient` или `default` (+ `nativeSidecar: true` при использовании Native Sidecar Containers).
- **Kubernetes 1.32–1.37** (минимальная поддерживаемая версия — 1.32).
- **Prometheus Operator (kube-prometheus-stack v0.8.x+)** или **Mimir** для сбора метрик с `ServiceMonitor`/`PodMonitor`.
- **Kiali 2.28** (установлен через официальный Helm chart или Istio addon).
- **Grafana Tempo 3.1+** или **Jaeger v2** для сбора трейсов (OTLP gRPC `:4317`).
- **Grafana Loki 3.x+** для централизованного сбора логов.
- **Grafana Alloy 1.2+** или **OpenTelemetry Collector 0.120+** в роли коллектора телеметрии.
- **OIDC-провайдер** (Dex, Keycloak, или внешний IdP) с поддержкой Authorization Code Flow.
- **RBAC:** ServiceAccount Kiali с правами `clusterroles` для чтения `metrics`, `pods`, `services`, и `istio.io/*` CRDs.

## Практические сценарии

### Организация безопасного доступа к Kiali через OIDC (Dex)

В промышленной эксплуатации доступ к Kiali должен быть защищен внешним IdP. Сценарий включает публикацию через **Gateway API**.

#### 1. Публикация Kiali через шлюз (Gateway API)

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: mesh-observability
  namespace: istio-system
spec:
  gatewayClassName: istio
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs: [{name: kiali-cert}]
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: kiali-route
  namespace: istio-system
spec:
  parentRefs: [{name: mesh-observability}]
  rules:
  - backendRefs:
    - name: kiali
      port: 20001
```

#### 2. Конфигурация Kiali для интеграции с Dex

Настройка выполняется через Helm-чарт или ConfigMap.

```yaml
auth:
  strategy: openid
  openid:
    client_id: kiali-console
    issuer_uri: https://dex.example.com
    username_claim: email
    scopes: ["openid", "profile", "email", "groups"]
```

#### 3. Настройка Dex (статический клиент)

```yaml
staticClients:
- id: kiali-console
  redirectURIs:
  - 'https://kiali.example.com/api/auth/login/oidc/callback'
  name: 'Kiali Istio Console'
  secret: "${KIALI_OIDC_SECRET}"
```

#### 4. PKCE и безопасность токенов

Начиная с Kiali 2.21 (январь 2026) поток **OIDC Authorization Code** полностью поддерживает **PKCE** (Proof Key for Code Exchange) — расширение, защищающее код авторизации от перехвата даже при отсутствии `client_secret`. В Kiali PKCE включается автоматически при использовании OIDC без `client_secret` — отдельный флаг конфигурации не требуется. Рекомендации:

- В публичных средах (без доверенного `client_secret`) обязательно включайте PKCE.
- Для `client_secret` используйте только секреты и переменные окружения — не храните его в ConfigMap.
- Доступ к Kiali можно дополнительно ограничить через `AuthorizationPolicy` (например, доступ только для пользователей определённой группы из `groups`-claim).

### Диагностика Ambient Mesh через Kiali

В Kiali 2.x доступна вкладка **Ambient**, позволяющая визуализировать:
1.  **Ztunnel Layer:** какие поды охвачены L4-шифрованием.
2.  **Waypoint Proxies:** через какие инстансы проходит L7-маршрутизация.
3.  **Cross-cluster traffic:** отображение потоков между разными кластерами в федеративной сетке.

### Сценарий 1: Поиск и анализ медленных запросов через Envoy Stats

Используйте admin-интерфейс Envoy для поиска upstream-сервисов с задержкой выше порога:

```bash
# Получение гистограмм задержек для всех outbound-кластеров
kubectl exec -n <ns> <pod> -c istio-proxy -- curl -s "127.0.0.1:15000/stats?format=histogram" | grep "outbound" | grep -E "P99|P999"

# Фильтр по порогу (например, P99 > 50ms)
kubectl exec -n <ns> <pod> -c istio-proxy -- curl -s "127.0.0.1:15000/stats?format=histogram" | grep "outbound" | awk -F'[,:]' '{for(i=1;i<=NF;i++) if($i~/P99/) print}' | sort -t= -k2 -nr | head -10
```

### Сценарий 2: Настройка ServiceMonitor для Ztunnel

Ztunnel экспортирует метрики на порту `15020`. Для сбора метрик в Prometheus создайте `ServiceMonitor`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: ztunnel-metrics
  namespace: istio-system
spec:
  selector:
    matchLabels:
      app: ztunnel
  endpoints:
  - port: http-envoy-prometheus
    path: /metrics
    interval: 30s
    relabelings:
    - sourceLabels: [__meta_kubernetes_pod_node_name]
      targetLabel: node
```

### Сценарий 3: Настройка ServiceMonitor для Waypoint Proxy

Waypoint Proxy использует стандартный Envoy admin-порт `15000`. Для его мониторинга:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: waypoint-metrics
  namespace: my-app
spec:
  selector:
    matchLabels:
      gateway.networking.k8s.io/gateway-name: namespace-waypoint
  endpoints:
  - port: http-envoy-prometheus
    path: /stats/prometheus
    interval: 30s
```

### Сценарий 4: Создание базовых Prometheus Alerting Rules

Настройте алерты на основе golden signals:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: istio-golden-signals
  namespace: istio-system
spec:
  groups:
  - name: istio.alerts
    rules:
    - alert: IstioHighErrorRate
      expr: sum(rate(istio_requests_total{response_code=~"5.."}[5m])) / sum(rate(istio_requests_total[5m])) > 0.01
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Доля 5xx ошибок > 1% в {{ $labels.namespace }}/{{ $labels.destination_service_name }}"
    - alert: IstioHighLatency
      expr: histogram_quantile(0.99, sum(rate(envoy_cluster_upstream_rq_time_bucket[5m])) by (le, destination_service_name)) > 1000
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "P99 задержка > 1s для {{ $labels.destination_service_name }}"
    - alert: IstioNoHealthyUpstream
      expr: sum(rate(istio_requests_total{response_code="503"}[5m])) by (destination_service_name) > 0
      for: 2m
      labels:
        severity: critical
      annotations:
        summary: "503 ошибки для {{ $labels.destination_service_name }} — нет здоровых эндпоинтов"
    - alert: ZtunnelHighCPU
      expr: sum(rate(container_cpu_usage_seconds_total{pod=~"ztunnel-.*"}[5m])) by (node) > 0.5
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Высокий CPU Ztunnel на ноде {{ $labels.node }}"
    - alert: IstiodDown
      expr: up{job="istiod"} == 0
      for: 1m
      labels:
        severity: critical
      annotations:
        summary: "Istiod недоступен"
```

### Сценарий 5: Диагностика пропущенных трейсов (W3C Trace Context)

Если трейсы не появляются в Grafana Tempo:

```bash
# 1. Проверьте, что приложение пробрасывает заголовок traceparent
kubectl exec -n <ns> <pod> -c app -- curl -s -H "traceparent: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01" http://localhost:8080/api

# 2. Проверьте, что Telemetry ресурс включает tracing
kubectl get telemetry -n <ns> -o yaml | grep -A5 "tracing:"

# 3. Проверьте endpoint OTLP в istiod
kubectl get cm istio -n istio-system -o jsonpath='{.data.mesh}' | jq '.defaultConfig.extensionProviders'

# 4. Проверьте логи Envoy на предмет rejected spans
kubectl logs <pod> -c istio-proxy -n <ns> | grep -i "trace\|span\|otel"
```

### Сценарий 6: Проверка доставки OTLP endpoint'ов через istioctl

Убедитесь, что прокси знает о OTLP endpoint:

```bash
# Просмотр всех кластеров (включая OTLP)
istioctl proxy-config clusters deploy/<app> -n <ns> | grep -i otel
# → cluster.outbound|4317||otel-collector.monitoring.svc.cluster.local

# Проверка конфигурации tracing
istioctl proxy-config tracing deploy/<app> -n <ns>
# → Должен отображать провайдера otel с endpoint

# Проверка, что трейсы уходят
kubectl exec -n <ns> <pod> -c istio-proxy -- curl -s 127.0.0.1:15000/logging?level=trace | grep -i "trace"
```

### Сценарий 7: Оптимизация кардинальности метрик Istio

Высокая кардинальность (множество уникальных комбинаций labels) приводит к "explosion" метрик в Prometheus и падению производительности.

```bash
# 1. Проверьте топ метрик по cardinality
kubectl exec -n <ns> <pod> -c istio-proxy -- curl -s "127.0.0.1:15000/stats" | wc -l
# → Если > 10000 строк — кардинальность высокая

# 2. Отфильтруйте ненужные labels через Telemetry API
cat <<EOF | kubectl apply -f -
apiVersion: telemetry.istio.io/v1
kind: Telemetry
metadata:
  name: reduce-cardinality
  namespace: my-app
spec:
  selector:
    matchLabels:
      app: my-app
  metrics:
  - providers:
    - name: prometheus
    overrides:
      tags:
        source_cluster: REMOVE
        destination_cluster: REMOVE
EOF

# 3. Отключите health cache в Kiali для высоконагруженных кластеров
kubectl edit cm kiali -n istio-system
# → health_cache: false
```

### Сценарий 8: Мониторинг состояния istiod через ServiceMonitor

istiod экспортирует метрики на порту `15014`. Для мониторинга Control Plane:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: istiod-metrics
  namespace: istio-system
spec:
  selector:
    matchLabels:
      app: istiod
  endpoints:
  - port: http-monitoring
    path: /metrics
    interval: 30s
```

### Сценарий 9: Проверка работы W3C Trace Context

Убедитесь, что заголовки `traceparent` и `tracestate` пробрасываются между сервисами:

```bash
# Отправка запроса с явным traceparent
TRACE_ID="0af7651916cd43dd8448eb211c80319c"
PARENT_ID="b7ad6b7169203331"
curl -v -H "traceparent: 00-$TRACE_ID-$PARENT_ID-01" http://my-app.prod/api

# Проверка, что Envoy принял и распространил trace
kubectl logs <pod> -c istio-proxy -n prod | grep -i "traceparent\|tracestate"
```

### Сценарий 10: Безопасный сбор метрик через mTLS (Istio 1.31+)

Начиная с Istio 1.31, встроены переменные окружения для mTLS-защищённых портов метрик. Это устраняет необходимость в обходных ServiceEntry/VirtualService-конфигурациях для older версий.

**Порты:**
- `ENVOY_SECURE_METRICS_PORT` (15091) — mTLS listener для Envoy-only stats (порт 15090)
- `ENVOY_SECURE_MERGED_METRICS_PORT` (15092) — mTLS listener для объединённых метрик (порт 15020, включая app и agent stats)

#### Шаг 1. Настройка mTLS-портов в proxyMetadata

```yaml
# istio-secure-metrics.yaml
apiVersion: install.istio.io/v1alpha1
kind: IstioOperator
spec:
  meshConfig:
    defaultConfig:
      proxyMetadata:
        ENVOY_SECURE_METRICS_PORT: "15091"
        ENVOY_SECURE_MERGED_METRICS_PORT: "15092"
        METRICS_LOCALHOST_ACCESS_ONLY: "true"
  components:
    ingressGateways:
    - name: istio-ingressgateway
      enabled: true
      k8s:
        podAnnotations:
          prometheus.istio.io/secure-port: "15092"
          prometheus.io/path: "/stats/prometheus"
```

```bash
istioctl install -f istio-secure-metrics.yaml -y
# → ✔ Installation complete
```

#### Шаг 2. Проверка mTLS-портов

```bash
# Проверка, что прокси знает о mTLS listeners
kubectl get pods -n default -l app=httpbin -o jsonpath='{.items[0].metadata.annotations}' | jq '.["prometheus.istio.io/secure-port"]'

# Проверка mTLS-ручки через curl с сертификатами Istio
POD_IP=$(kubectl get pods -n default -l app=httpbin -o jsonpath='{.items[0].status.podIP}')
kubectl exec -n istio-system deploy/prometheus -c istio-proxy -- \
  curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
  --cacert /etc/istio-certs/root-cert.pem \
  --cert /etc/istio-certs/cert-chain.pem \
  --key /etc/istio-certs/key.pem \
  --insecure \
  https://$POD_IP:15092/stats/prometheus
# → 200
```

#### Шаг 3. Настройка Prometheus scrape job с mTLS

```yaml
# prometheus-secure-scrape.yaml
scrape_configs:
- job_name: 'istio-secure-merged-metrics'
  metrics_path: '/stats/prometheus'
  scheme: https
  tls_config:
    ca_file: /etc/istio-certs/root-cert.pem
    cert_file: /etc/istio-certs/cert-chain.pem
    key_file: /etc/istio-certs/key.pem
    insecure_skip_verify: true
  kubernetes_sd_configs:
  - role: pod
  relabel_configs:
  - source_labels: [__meta_kubernetes_pod_annotation_prometheus_istio_io_secure_port]
    action: keep
    regex: .+
  - source_labels: [__meta_kubernetes_pod_ip, __meta_kubernetes_pod_annotation_prometheus_istio_io_secure_port]
    action: replace
    target_label: __address__
    regex: (.+);(.+)
    replacement: $1:$2
```

#### Шаг 4. Multi-target scraping (Istio 1.31+)

```yaml
# Поддержка нескольких application-metrics endpoint'ов на одном поде
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  template:
    metadata:
      annotations:
        prometheus.istio.io/scrape-targets: "8080:/metrics,9090:/internal/metrics"
```

```bash
# Проверка, что оба endpoint'а скрапятся
kubectl exec -n istio-system deploy/prometheus -c istio-proxy -- \
  curl -s 127.0.0.1:15000/stats | grep "my-app.*scrape"
# → Видны метрики с обоих портов
```

#### Шаг 5. Очистка

```bash
# Деактивация secure metrics и возврат к plaintext
kubectl annotate pods -n default -l app=httpbin \
  prometheus.istio.io/secure-port- \
  prometheus.istio.io/secure-envoy-port- \
  prometheus.io/path- \
  --overwrite
# → Удалите proxyMetadata ENVOY_SECURE_* и METRICS_LOCALHOST_ACCESS_ONLY из IstioOperator
```

---

## Операции и команды

### Команды проверки

| Команда | Назначение |
| :--- | :--- |
| **`istioctl proxy-status`** | Проверка синхронизации xDS (CDS/LDS/EDS/RDS) между istiod и прокси. |
| **`istioctl proxy-config clusters deploy/<name> -n <ns>`** | Просмотр upstream-кластеров (включая OTLP, внешние сервисы). |
| **`istioctl proxy-config listeners deploy/<name> -n <ns>`** | Просмотр слушателей и filter chains. |
| **`istioctl proxy-config routes deploy/<name> -n <ns>`** | Проверка активных маршрутов и таймаутов. |
| **`istioctl proxy-config secret deploy/<name> -n <ns>`** | Просмотр сертификатов mTLS и их срока действия. |
| **`kubectl logs <pod> -c istio-proxy`** | Логи Envoy (access-логи, ошибки фильтров). |
| **`istioctl analyze -A`** | Автоматический анализ конфликтов в конфигурации меша. |
| **`istioctl dashboard kiali`** | Открыть консоль Kiali в браузере (port-forward + UI). |
| **`istioctl dashboard jaeger`** | Открыть UI Jaeger для трассировки. Требует установленного Jaeger; в большинстве современных инсталляций Jaeger заменён на Tempo (см. раздел «Компоненты»). |
| **`kubectl top pods -n istio-system -l app=ztunnel`** | Использование ресурсов Ztunnel по нодам. |

### Интерпретация логов Envoy

Access-лог Envoy содержит следующие поля:

| Поле | Значение |
| :--- | :--- |
| `method` | HTTP-метод (GET, POST) |
| `path` | URI запроса |
| `upstream_cluster` | Имя кластера (сервиса назначения) |
| `upstream_host` | Эндпоинт (IP:port), к которому был направлен запрос |
| `response_code` | HTTP-код ответа (200, 503, 502 и т.д.) |
| `duration` | Время обработки в миллисекундах |
| `x_forwarded_for` | Исходный IP клиента (если прошёл через ingress) |

Типовые паттерны в логах:
- `upstream_reset_overflow` — исчерпан лимит соединений (`max_requests_per_connection`).
- `upstream_rq_retry` — ретрай запроса к upstream.
- `access_logs` — отсутствие записи означает, что `Telemetry` ресурс не настроен или `accessLogging` отключен.

## Устранение неполадок

### Типичные ошибки и устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Метрики Envoy не появляются в Prometheus** | PodMonitor/Servicemonitor отсутствует или порт/путь указаны неверно | Проверьте, что PodMonitor выбирает поды по метке `istio-injection=enabled`; порт `15090`, путь `/stats/prometheus`. |
| **Access-логи не пишутся** | Telemetry API не настроен или `accessLogging` отключен | Примените ресурс `Telemetry` с `accessLogging`; проверьте `kubectl logs -c istio-proxy`. |
| **Трейсы не доставляются в Tempo** | OTLP endpoint неверен или `randomSamplingPercentage` = 0 | Проверьте `meshConfig.extensionProviders`; убедитесь, что `Telemetry.tracing` настроен с ненулевым семплированием. |
| **Граф Kiali пустой или устаревший** | Health cache отключен или Kiali не может достучаться до istiod | Проверьте ServiceAccount Kiali; убедитесь, что `kiali_health_status` включен (opt-in с 2.24). |
| **Высокая кардинальность метрик** | Слишком много labels в метриках Envoy | Используйте `Telemetry.metrics.overrides.tags` для удаления лишних тегов (`source_cluster`, `destination_cluster`). |
| **OTLP endpoint недоступен** | Сетевая разрыв между прокси и коллектором | Проверьте `istioctl proxy-config clusters`; убедитесь, что Service/Endpoints OTLP коллектора существует. |
| **Ztunnel метрики не собираются** | ServiceMonitor отсутствует или порт неправильный | Ztunnel экспортирует на порту `15020`; убедитесь, что ServiceMonitor указывает правильный порт и путь `/metrics`. |
| **Waypoint метрики отсутствуют** | Waypoint не развёрнут или ServiceMonitor не настроен | `istioctl waypoint list -n <ns>`; создайте ServiceMonitor для label `gateway.networking.k8s.io/gateway-name`. |
| **Health cache Kiali не обновляется** | Нет прав на чтение метрик или кэш отключен | Проверьте RBAC Kiali; для высококардинальных кластеров оставьте кэш отключенным. |
| **Сертификат истёк, алерты не сработали** | Blackbox exporter или alerting rule не настроен | Добавьте правило `IstioCertificateExpiry` с порогом 7 дней до истечения. |

---

## Лучшие практики эксплуатации

1.  **Scraping метрик:** используйте **PodMonitor** (Prometheus Operator) с портом `15090` и путём `/stats/prometheus` для Envoy-метрик; для метрик Istio-агента — порт `15020`. В моделях без sidecar (Ambient) метрики собираются напрямую с Ztunnel (`istio_tcp_*`). Для продакшена используйте mTLS-порты (`15091`/`15092`, см. Сценарий 10).
2.  **Ресурсные лимиты:** для мешей с количеством сервисов > 500 выделите Kiali не менее 2 CPU и 2GB RAM для эффективной обработки графа топологии. Начиная с Kiali 2.22+ включите health cache (`kiali_health_status`) — для инсталляций с высокой кардинальностью метрик оставляйте его отключённым (opt-in с 2.24).
3.  **Health Validation:** регулярно проверяйте вкладку **Istio Config** в Kiali — она подсвечивает ошибки в Gateway API (например, конфликтующие `HTTPRoute`).
4.  **Распределенная трассировка:** убедитесь, что ваше приложение пробрасывает заголовок `traceparent` (стандарт **W3C Trace Context**, используется по умолчанию) — `b3` (Zipkin) применяется только в legacy-инсталляциях. Иначе меш не сможет связать спаны в единый трейс.
5.  **Ambient-наблюдаемость:** в Ambient используйте L4-метрики Ztunnel (`istio_tcp_connections_opened_total`, `istio_tcp_sent_bytes_total`) для базового мониторинга соединений и телеграммы L7 через Waypoint — HTTP-метрики генерируются только там.
6.  **PodMonitor для всех компонентов:** настраивайте ServiceMonitor/PodMonitor не только для Envoy, но и для istiod (`15014`), Ztunnel (`15020`) и Waypoint (`15000`).
7.  **Health cache Kiali:** для кластеров с < 500 сервисов включите `kiali_health_status` для снижения нагрузки на Prometheus. Для высококардинальных кластеров оставьте отключенным.
8.  **Sampling трейсов:** настройте `randomSamplingPercentage` в `Telemetry` ресурсе. Для продакшена рекомендуется 0.1–1%; для staging можно оставить 100%.
9.  **Алерты на golden signals:** создайте PrometheusRule на основе SRE golden signals (Traffic, Errors, Latency, Saturation) для каждого ключевого сервиса.
10. **Ограничение кардинальности:** используйте `Telemetry.metrics.overrides.tags` для удаления избыточных labels (`source_cluster`, `destination_cluster`, `reporter`).
11. **Хранение логов:** настройте Loki с retention policy (например, 30 дней для продакшена) и лимитами на объём стека.
12. **Безопасность observability stack:** ограничьте доступ к Kiali через `AuthorizationPolicy` и `NetworkPolicy`; Grafana и Tempo должны находиться в отдельном неймспейсе `monitoring`.

## Очистка окружения

Команды для безопасного удаления наблюдательных ресурсов:

```bash
# 1. Удаление ресурсов Telemetry
kubectl delete telemetry checkout-otel -n checkout --ignore-not-found=true
kubectl delete telemetry global-mesh-tracing -n istio-system --ignore-not-found=true
kubectl delete telemetry waypoint-tracing -n fintech-apps --ignore-not-found=true
kubectl delete telemetry disable-mesh-spans -n fintech-apps --ignore-not-found=true
kubectl delete telemetry reduce-cardinality -n my-app --ignore-not-found=true

# 2. Удаление ServiceMonitor и PrometheusRule
kubectl delete servicemonitor ztunnel-metrics -n istio-system --ignore-not-found=true
kubectl delete servicemonitor waypoint-metrics -n my-app --ignore-not-found=true
kubectl delete servicemonitor istiod-metrics -n istio-system --ignore-not-found=true
kubectl delete prometheusrule istio-golden-signals -n istio-system --ignore-not-found=true

# 3. Удаление шлюзов и HTTPRoute для Kiali
kubectl delete gateway mesh-observability -n istio-system --ignore-not-found=true
kubectl delete httproute kiali-route -n istio-system --ignore-not-found=true

# 4. Удаление Waypoint Gateway и метки
kubectl delete gateway namespace-waypoint -n fintech-apps --ignore-not-found=true
kubectl label namespace fintech-apps istio.io/use-waypoint- --ignore-not-found=true

# 5. Отключение secure metrics (Istio 1.31+)
kubectl annotate pods -n default -l app=httpbin \
  prometheus.istio.io/secure-port- \
  prometheus.istio.io/secure-envoy-port- \
  prometheus.io/path- \
  --overwrite
# → Затем удалите ENVOY_SECURE_* и METRICS_LOCALHOST_ACCESS_ONLY из IstioOperator
```

---

## Дополнительная информация

### Интеграция с Grafana Tempo и TraceQL

В 2026 году Kiali поддерживает глубокую интеграцию с Tempo (включая актуальную ветку **Tempo 3.1** с архитектурой Decoupled Read/Write Path). При просмотре графа трафика можно кликнуть на ребро и мгновенно перейти к списку трейсов, отфильтрованных по **TraceQL** (например, запросы с задержкой > 500мс).

```bash
# Пример запроса TraceQL, генерируемого Kiali
{ .service.name = "catalog-v1" && .duration > 500ms }
```

Особенности интеграции в 2026:

- **Trace overlay в Kiali (2.25+, май 2026):** при клике на ребро графа Kiali запрашивает Tempo по TraceQL-выражению и накладывает трейсы на граф — видно, через какие сервисы прошёл запрос и где возникла задержка.
- **Traces Drilldown в Grafana:** альтернативный способ работы с трейсами без TraceQL — UI-инструмент для поточечного анализа latency и ошибок; сгенерированные в нём запросы можно дорабатывать вручную.
- Tempo принимает трейсы по **OTLP** (gRPC/HTTP) — в связке с Istio трафик доставляется через Envoy/Ztunnel, а контекст распространяется заголовками **W3C Trace Context** (`traceparent`).

Подробнее об архитектуре Tempo: [Grafana Tempo: распределённая трассировка](../Tempo/index.md).

### Операционные аспекты (2026)

1.  **Sidecar Tax (Налог на сайдкар):** даже с оптимизациями добавление прокси увеличивает задержку. В 2026 году это решается через переход на **Ambient Mesh** (Ztunnel + Waypoint) или использование **eBPF-акселерации** (SOCKMAP-обход TCP/IP-стека ядра для локальных соединений; эффективность зависит от нагрузки и стека).
2.  **Ресурсное планирование:** прокси потребляют память и CPU. В Sidecar-модели это может составлять до 10–15% ресурсов кластера. Ambient Mesh снижает этот показатель до 1–3%.
3.  **Управление сертификатами:** ротация сертификатов mTLS происходит автоматически (обычно раз в 24 часа), что исключает риски простоя из-за истечения срока действия.
4.  **Планирование емкости провайдеров (Capacity Planning):** в мультикластерных конфигурациях важно учитывать overhead Control Plane (например, Istiod) и резервировать ресурсы для распределенной трассировки.
5.  **Совместимость с существующими сервисами:** при интеграции mesh с устаревшими системами (VM, внешние базы данных) настройте исключения из mTLS/проксирования через `ServiceEntry` (Istio) или явные политики, чтобы не потерять связность.

### Актуальность и ссылки

- **Istio 1.31.x:** стандарт для современного Service Mesh (Kubernetes 1.32–1.37); телеметрия настраивается через Telemetry API.
- **Kiali 2.28:** основной инструмент визуализации; полная поддержка Ambient Mesh, Gateway API, OIDC PKCE и Trace overlay (2.25+).
- **OpenTelemetry:** OTLP — единый протокол для метрик, логов и трейсов; Grafana Alloy — рекомендуемый коллектор в стеке LGTM.

**См. также:**
- [Основные концепции Service Mesh](./service_mesh_concepts.md)
- [Архитектура Istio и режим Ambient](./istio_architecture.md)
- [Прокси Sidecar: реализации и сценарии](./proxy_sidecar.md)
- [Политики безопасности Istio](./istio-security-policies.md)
- [Ограничение скорости (Rate Limiting) в Istio](./istio_rate_limiting.md)
- [Grafana Tempo: распределённая трассировка](../Tempo/index.md)

Документация: [Kiali Official Documentation](https://kiali.io/docs/), [Istio Observability Guide](https://istio.io/latest/docs/tasks/observability/).
