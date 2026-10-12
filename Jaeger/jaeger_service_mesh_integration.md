# Интеграция Jaeger с Service Mesh

**Актуально для:** Jaeger v2.x / Istio 1.22–1.25 / Linkerd 2.14–2.20 / Cilium 1.15–1.17 / Kubernetes 1.28–1.32

> **Статус:** Документация описывает интеграцию с **Jaeger v2** (архитектура Unified Binary на базе каркаса OpenTelemetry Collector). Классический Jaeger v1 достиг **EOL (End of Life)**. Все практические сценарии, архитектурные решения и конфигурации ориентированы на **on-premise и bare-metal инфраструктуру** (локальный Kubernetes-кластер, физические серверы, systemd, автономные балансировщики) без использования проприетарных облачных сервисов (AWS, GCP, Azure) и AI-инструментов.

**Интеграция Jaeger с Service Mesh** — это комплекс архитектурных и эксплуатационных практик по организации распределенной трассировки в микросервисных средах под управлением сервисных сеток (Istio, Linkerd, Cilium Service Mesh). В mesh-архитектуре прокси-слой перехватывает сетевой трафик и автоматически генерирует спаны клиентских и серверных сетевых взаимодействий. Это позволяет получить наблюдаемость (observability) L7-вызовов даже для приложений без встроенных SDK трассировки. 

Однако реализация полноценного сквозного мониторинга требует строгого согласования форматов распространения контекста (W3C Trace Context), настройки политик сэмплирования, подавления дублирующих спанов между прокси и кодом приложений, а также предотвращения сетевых петель телеметрии.

Смежные темы:
- Общий обзор концепций и терминологии: **[Обзор Jaeger](./jaeger_overview.md)**
- Архитектура коллектора и пайплайны Jaeger v2: **[Архитектура Jaeger](./jaeger_architecture.md)**
- Развертывание в Kubernetes: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**
- Сетевая настройка OTLP-приемников: **[Конфигурация OTLP для Jaeger](./jaeger_otlp_configuration.md)**
- Безопасность и харденинг mTLS: **[Безопасность и харденинг Jaeger](./jaeger_security_hardening.md)**
- Хранение трейсов в ClickHouse: **[Storage Deep Dive для Jaeger](./jaeger_storage_deep_dive.md)**
- Концепции Service Mesh: **[Service Mesh: основные концепции](../Service_Mesh/service_mesh_concepts.md)**
- Наблюдаемость в Istio: **[Наблюдаемость в Istio: Kiali, телеметрия и федерация идентичности](../Service_Mesh/istio_observability_and_tools.md)**
- Сравнение Service Mesh: **[Сравнение Istio и Linkerd](../Service_Mesh/istio_vs_linkerd.md)**

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Service Mesh** | Инфраструктурный слой управления сетевыми соединениями, безопасностью (mTLS), маршрутизацией и наблюдаемостью межсервисных коммуникаций в кластере |
| **Sidecar Proxy** | Архитектурный паттерн, при котором прокси-процесс (Envoy для Istio, `linkerd-proxy` для Linkerd) размещается в том же сетевом пространстве имен (Pod), что и контейнер приложения |
| **Ambient Mesh** | Архитектурная модель Istio без сайдкаров: разделение на безинвазивный L4 mTLS-туннель узла (Ztunnel) и выделенный L7-прокси уровня сервиса (Waypoint Proxy) |
| **Ztunnel (Zero Trust Tunnel)** | Компонент Istio Ambient, работающий в виде DaemonSet на каждом рабочем узле и обеспечивающий L4-шифрование mTLS (HBONE) без L7-парсинга протоколов |
| **Waypoint Proxy** | Выделенный Envoy-инстанс в Istio Ambient, разворачиваемый на уровне пространства имен или сервиса для обработки L7-трафика, политик безопасности и генерации спанов |
| **Telemetry API** | Декларативный CRD Kubernetes (`telemetry.istio.io/v1`), управляющий генерацией метрик, логов доступа и распределенных трасс в Istio |
| **Trace Context Propagation** | Механизм передачи идентификаторов сквозной транзакции (`trace_id`, `parent_span_id`, флаги сэмплирования) через HTTP-заголовки или метаданные gRPC |
| **W3C Trace Context** | Общепринятый индустриальный стандарт IETF/W3C, регламентирующий заголовки `traceparent` и `tracestate` |
| **B3 Propagation** | Исторический стандарт трассировки Zipkin (`X-B3-TraceId`, `X-B3-SpanId`, `X-B3-Sampled`), используемый в устаревших системах |
| **Baggage** | Механизм передачи произвольных пар ключ-значение (контекста транзакции, например `user_id`, `tenant_id`) через всю цепочку вызовов в заголовке `baggage` |
| **Span Kind** | Классификация спана по спецификации OpenTelemetry: `SERVER` (прием запроса), `CLIENT` (исходящий запрос), `INTERNAL` (внутренняя операция), `PRODUCER`/`CONSUMER` |
| **Telemetry Loop** | Аварийная ситуация, при которой трафик отправки спанов от прокси к Jaeger Collector перехватывается этим же прокси, вызывая бесконечную рекурсивную генерацию телеметрии |
| **Cilium Service Mesh** | Реализация сервисной сетки на базе eBPF в ядре Linux со встроенным Envoy DaemonSet для терминации L7-политик, Ingress и экспорт телеметрии без классических сайдкаров |
| **Hubble** | Подсистема наблюдаемости Cilium на базе eBPF, предоставляющая L3/L4/L7 аудит сетевых потоков с возможностью интеграции с OpenTelemetry |

---

## Базовые концепции и архитектура

### Архитектура трассировки в Service Mesh

В распределенной системе под управлением Service Mesh сетевые пакеты между подами не передаются напрямую, а перехватываются сетевыми правилами `iptables` или eBPF-программами и перенаправляются через прокси-демоны.

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       Kubernetes Cluster (Bare-Metal)                           │
│                                                                                                  │
│   Pod: Service A (Client)                              Pod: Service B (Server)                   │
│ ┌─────────────────────────────────────────┐          ┌─────────────────────────────────────────┐ │
│ │ [App Container: Service A]              │          │ [App Container: Service B]              │ │
│ │   │                                     │          │   ▲                                     │ │
│ │   │ HTTP Request (injected traceparent) │          │   │ HTTP Request (forwarded traceparent)│ │
│ │   ▼                                     │          │   │                                     │ │
│ │ ┌─────────────────────────────────────┐ │          │ ┌─┴───────────────────────────────────┐ │ │
│ │ │ Sidecar Proxy (Envoy / linkerd)     │ │   mTLS   │ │ Sidecar Proxy (Envoy / linkerd)     │ │ │
│ │ │  - Client Span (egress)             │─┼──────────┼▶│  - Server Span (ingress)            │ │ │
│ │ └─┬───────────────────────────────────┘ │          │ └─┬───────────────────────────────────┘ │ │
│ └───┼─────────────────────────────────────┘          └───┼─────────────────────────────────────┘ │
│     │                                                    │                                       │
│     │ OTLP/gRPC (:4317)                                  │ OTLP/gRPC (:4317)                     │
│     ▼                                                    ▼                                       │
│ ┌──────────────────────────────────────────────────────────────────────────────────────────────┐ │
│ │                      Jaeger v2 Collector Cluster (OpenTelemetry Core)                        │ │
│ │  Receivers: otlp (gRPC :4317, HTTP :4318)                                                    │ │
│ │  Processors: memory_limiter ──▶ k8sattributes ──▶ batch                                      │ │
│ │  Exporters: jaeger_storage_exporter                                                          │ │
│ └──────────────────────────────────────────────┬───────────────────────────────────────────────┘ │
│                                                │ TCP Native (:9000)                              │
│                                                ▼                                                 │
│                        ┌───────────────────────────────────────────────┐                         │
│                        │       ClickHouse Cluster (On-Premise Storage) │                         │
│                        └───────────────────────────────────────────────┘                         │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### Иерархия спанов в транзакции Service Mesh
При вызове между двумя сервисами, работающими в сетке, формируется иерархия связанных спанов:
1. **Client App Span** *(опционально)*: создается OpenTelemetry SDK внутри приложения Service A перед отправкой сетевого вызова.
2. **Mesh Client Span (Egress)**: создается sidecar-прокси Service A в момент перехвата исходящего вызова к Service B. Фиксирует сетевую задержку, DNS-резолвинг, статус TLS и попытки повторов (retries).
3. **Mesh Server Span (Ingress)**: создается sidecar-прокси Service B в момент приема входящего сетевого соединения от Service A. Фиксирует время ожидания в очереди и mTLS-аутентификацию.
4. **Server App Span** *(опционально)*: создается OTel SDK внутри Service B при обработке бизнес-логики.

### Фундаментальное правило проброса контекста (Context Propagation)

> **Критическое замечание для SRE и разработчиков:**  
> Service Mesh **НЕ МОЖЕТ** автоматически связать входящий запрос к сервису с его исходящими запросами к нижележащим зависимостям!

Envoy и любой другой L7-прокси видит входящий HTTP-запрос и создает для него входящий спан (Server Span). Когда приложение выполняет вызов к базе данных или другому сервису, прокси видит этот вызов как совершенно независимый исходящий запрос (Client Span). 

Чтобы эти спаны объединились в единое дерево трейса в Jaeger, **код приложения обязан скопировать заголовки трассировки** из входящего HTTP-контекста во все свои исходящие HTTP/gRPC-запросы:

```
[Входящий HTTP] ──▶ Envoy Ingress ──▶ [Приложение] ──(Копирование заголовков)──▶ Envoy Egress ──▶ [Сеть]
   traceparent       (читает tp)      получает tp                                (читает tp)      traceparent
                                      вставляет tp в out-запрос
```

Если приложение не пробросит заголовок `traceparent`, исходящий запрос получит новый сгенерированный `trace_id`, и трейс в Jaeger окажется **разорванным на изолированные фрагменты**.

### Сравнительный анализ архитектур Service Mesh для Jaeger

| Критерий | Istio Sidecar | Istio Ambient Mesh | Linkerd Native Sidecar | Cilium Service Mesh |
| :--- | :--- | :--- | :--- | :--- |
| **Исполняемый компонент** | Envoy в поде приложения | Ztunnel (узловой) + Waypoint (Envoy) | `linkerd-proxy` (Rust микро-прокси) | Встроенный Envoy в Cilium DaemonSet / Node |
| **Где генерируются L7 спаны** | В поде каждого сервиса | Исключительно в Waypoint Proxy | В поде каждого сервиса | В узловом Envoy по правилам L7 Ingress/Policy |
| **Поддержка L4 спанов** | Нет (только метрики/логи) | TCP метрики через Ztunnel | TCP метрики соединения | L3/L4 потоки через Hubble / eBPF |
| **Протокол экспорта в Jaeger** | OTLP gRPC (нативно) | OTLP gRPC через Waypoint | OTLP gRPC / OpenCensus | OTLP gRPC через Envoy / Hubble exporter |
| **Оверхед по памяти на Pod** | 50–150 МБ RAM на под | **0 МБ** на под приложения | 15–35 МБ RAM на под | **0 МБ** на под приложения |
| **Сложность внедрения** | Низкая (инъекция аннотацией) | Средняя (настройка Gateway API) | Низкая (`linkerd.io/inject`) | Средняя (требует eBPF CNI + Envoy) |
| **Гибкость кастомизации тегов** | Высокая (Telemetry CRD) | Высокая (через Waypoint CRD) | Средняя (ограниченный набор тегов) | Высокая (Envoy Config / Cilium Envoy) |

### Форматы контекстной пропагации

| Заголовок / Стандарт | Формат значения | Пример | Статус в Jaeger v2 |
| :--- | :--- | :--- | :--- |
| **W3C `traceparent`** | `version-trace_id-parent_id-flags` | `00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01` | **Основной стандарт по умолчанию** |
| **W3C `tracestate`** | Пары `vendor1=opaqueValue,vendor2=...` | `rojo=1,congo=2` | Поддерживается нативно |
| **W3C `baggage`** | Пары `key1=value1,key2=value2` | `userId=alice,dc=dc-north` | Пробрасывается и экспортируется в теги спана |
| **B3 Single** | `trace_id-span_id-sampled-parent_id` | `463ac35c9f6413ad-463ac35c9f6413ad-1` | Устарел; рекомендуется миграция |
| **B3 Multi** | Набор заголовков `X-B3-*` | `X-B3-TraceId`, `X-B3-SpanId`, `X-B3-Sampled` | Поддерживается для legacy-клиентов |
| **Jaeger Native** | `uber-trace-id` | `463ac35c9f6413ad:1:0:1` | Устарел (EOL) |

### Атрибуты, автоматически генерируемые Envoy в Jaeger

При интеграции с Jaeger через OpenTelemetry Provider Envoy заполняет спаны стандартизированными атрибутами:

```
http.method: "POST"
http.status_code: 200
http.url: "http://billing.internal:8080/api/v1/charge"
http.host: "billing.internal:8080"
user_agent: "Go-http-client/1.1"
net.peer.ip: "10.244.2.45"
net.peer.port: 8080
net.host.ip: "10.244.1.18"
response_flags: "-"
upstream_cluster: "outbound|8080||billing.default.svc.cluster.local"
```

При добавлении процессора `k8sattributes` в пайплайн Jaeger v2 спаны дополнительно обогащаются метаданными Kubernetes по IP-адресу:
- `k8s.namespace.name`
- `k8s.pod.name`
- `k8s.pod.uid`
- `k8s.node.name`

---

## Практические сценарии настройки

### Сценарий 1: Настройка Istio Sidecar с экспортом в Jaeger v2 через Telemetry API

**Контекст:** On-premise кластер Kubernetes. Установлен Istio 1.24+. Требуется настроить сквозную трассировку для всех рабочих нагрузок с прямой отправкой спанов по gRPC OTLP на порт `4317` инстанса Jaeger v2 Collector, развернутого в пространстве имен `jaeger-system`.

#### Шаг 1. Конфигурация Istio Control Plane (MeshConfig)

В современных версиях Istio (1.22–1.25) устаревшие параметры `meshConfig.defaultConfig.tracing` заменены на механизм `extensionProviders`. Зарегистрируйте OTLP-провайдер в манифесте `IstioOperator`:

```yaml
# istio-control-plane.yaml
apiVersion: install.istio.io/v1alpha1
kind: IstioOperator
metadata:
  name: istio-control-plane
  namespace: istio-system
spec:
  meshConfig:
    enableTracing: true
    extensionProviders:
      - name: jaeger-otlp-grpc
        opentelemetry:
          service: jaeger-collector.jaeger-system.svc.cluster.local
          port: 4317
          # Таймаут отправки пачки спанов из Envoy в коллектор
          timeout: 3s
          # Лимит размера буфера пакетов в памяти Envoy
          maxPathLength: 256
```

Примените изменения в control plane:
```bash
istioctl install -f istio-control-plane.yaml -y
# → ✔ Istio core installed
# → ✔ Istiod installed
# → ✔ Installation complete
```

#### Шаг 2. Создание ресурса Telemetry

Создайте кластерный или namespace-level ресурс `Telemetry`. Настройте 10% случайного сэмплирования, проброс кастомных тегов и заголовка версии клиента:

```yaml
# telemetry-global.yaml
apiVersion: telemetry.istio.io/v1
kind: Telemetry
metadata:
  name: global-mesh-tracing
  namespace: istio-system
spec:
  tracing:
    - providers:
        - name: jaeger-otlp-grpc
      # Процент сэмплирования для входящего немаркированного трафика
      randomSamplingPercentage: 10.0
      # Кастомные статические и динамические атрибуты спана
      customTags:
        infra_environment:
          literal:
            value: "baremetal-production"
        node_name:
          environment:
            name: "NODE_NAME"
            defaultValue: "unknown-worker"
        client_version:
          header:
            name: "x-client-version"
            defaultValue: "unversioned"
        trace_source:
          literal:
            value: "istio-envoy-sidecar"
```

Примените манифест:
```bash
kubectl apply -f telemetry-global.yaml
# → telemetry.telemetry.istio.io/global-mesh-tracing created
```

#### Шаг 3. Изоляция трафика телеметрии (Предотвращение Telemetry Loop)

Если коллектор Jaeger развернут в том же кластере, трафик телеметрии от Envoy к порту `4317` коллектора не должен перехватываться сайдкаром самого приложения или коллектора.

Добавьте аннотацию в Deployment приложений:
```yaml
metadata:
  annotations:
    traffic.sidecar.istio.io/excludeOutboundPorts: "4317,4318"
```

А для подов Jaeger v2 Collector полностью отключите инъекцию сайдкара:
```yaml
metadata:
  labels:
    sidecar.istio.io/inject: "false"
```

#### Шаг 4. Валидация и проверка

1. Выполните тестовый запрос через ingress-gateway или curl внутри пода:
```bash
kubectl exec -n default deploy/client-app -c app -- \
  curl -s -H "x-client-version: 2.4.1" http://server-app.default.svc.cluster.local:8080/api/v1/orders
# → {"status":"processed","order_id":"A-98124"}
```

2. Проверьте счетчики отправленных спанов в локальном админ-интерфейсе Envoy:
```bash
kubectl exec -n default deploy/client-app -c istio-proxy -- \
  curl -s 127.0.0.1:15000/stats | grep "tracing"
# → tracing.opentelemetry.spans_sent: 2
# → tracing.opentelemetry.reports_failed: 0
# → tracing.opentelemetry.reports_dropped: 0
```

3. Проверьте поступление спанов через Query API Jaeger v2:
```bash
curl -s "http://jaeger-query.jaeger-system.svc.cluster.local:16686/api/traces?service=server-app.default&limit=1" | jq '.data[0].spans[] | {operationName, tags: [.tags[] | select(.key=="infra_environment" or .key=="client_version")]}'
```
Ожидаемый вывод:
```json
{
  "operationName": "server-app.default.svc.cluster.local:8080/*",
  "tags": [
    {
      "key": "infra_environment",
      "type": "string",
      "value": "baremetal-production"
    },
    {
      "key": "client_version",
      "type": "string",
      "value": "2.4.1"
    }
  ]
}
```

---

### Сценарий 2: Трассировка в Istio Ambient Mesh через Waypoint Proxy

**Контекст:** В кластере включен режим Istio Ambient. Рабочие узлы обслуживаются демоном `ztunnel`. Требуется включить детальную L7-трассировку без возврата к тяжелым sidecar-контейнерам в каждом поде.

#### Архитектурная особенность Ambient Mesh
- **Ztunnel (L4):** Осуществляет взаимную mTLS аутентификацию и L4-маршрутизацию на базе протокола HBONE (HTTP-Based Overlay Network Encapsulation). Ztunnel **не выполняет L7-парсинг HTTP-трафика** и не может модифицировать или считывать W3C `traceparent`.
- **Waypoint Proxy (L7):** Представляет собой специализированный Envoy-инстанс, разворачиваемый контроллером Istio по стандарту Kubernetes Gateway API. Waypoint выполняет авторизацию RBAC, аудит, L7-маршрутизацию и **генерирует детальные спаны трассировки**.

#### Шаг 1. Развертывание Waypoint Proxy для пространства имен

Создайте ресурс Gateway с классом `istio-waypoint` в целевом пространстве имен `fintech-apps`:

```yaml
# waypoint-gateway.yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: namespace-waypoint
  namespace: fintech-apps
  labels:
    istio.io/waypoint-for: all
spec:
  gatewayClassName: istio-waypoint
  listeners:
    - name: mesh
      port: 15008
      protocol: HBONE
```

Примените манифест и проверьте запуск пода Waypoint:
```bash
kubectl apply -f waypoint-gateway.yaml
# → gateway.gateway.networking.k8s.io/namespace-waypoint created

kubectl get pods -n fintech-apps -l gateway.networking.k8s.io/gateway-name=namespace-waypoint
# → NAME                                                  READY   STATUS    RESTARTS   AGE
# → namespace-waypoint-istio-waypoint-5f98c69784-xkz92   1/1     Running   0          42s
```

#### Шаг 2. Привязка пространства имен к Waypoint

Разметьте пространство имен меткой использования Waypoint-шлюза:
```bash
kubectl label namespace fintech-apps istio.io/use-waypoint=namespace-waypoint
# → namespace/fintech-apps labeled
```

#### Шаг 3. Конфигурация Telemetry CRD для Waypoint Proxy

Настройте генерацию спанов, применив Telemetry CRD непосредственно в пространстве имен `fintech-apps`:

```yaml
# telemetry-ambient.yaml
apiVersion: telemetry.istio.io/v1
kind: Telemetry
metadata:
  name: waypoint-tracing
  namespace: fintech-apps
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: namespace-waypoint
  tracing:
    - providers:
        - name: jaeger-otlp-grpc
      randomSamplingPercentage: 100.0
      customTags:
        mesh_architecture:
          literal:
            value: "istio-ambient-waypoint"
```

Примените манифест:
```bash
kubectl apply -f telemetry-ambient.yaml
# → telemetry.telemetry.istio.io/waypoint-tracing created
```

#### Шаг 4. Валидация трассировки Ambient

1. Отправьте L7-запрос к сервису, защищенному Waypoint:
```bash
kubectl exec -n default deploy/curl-test -- curl -s http://payment-service.fintech-apps.svc.cluster.local:8080/pay
# → {"status":"approved"}
```

2. Убедитесь, что спан сгенерирован шлюзом Waypoint:
```bash
kubectl logs -n fintech-apps deploy/namespace-waypoint-istio-waypoint -c istio-proxy --tail=20 | grep "traceparent"
```

3. В Jaeger UI найдите сервис `namespace-waypoint.fintech-apps` с тегом `mesh_architecture="istio-ambient-waypoint"`.

---

### Сценарий 3: Предотвращение дублирования спанов (Mesh + In-App OTel SDK)

**Проблема:**  
Если приложение уже инструментировано библиотекой OpenTelemetry SDK (например, Spring Boot Micrometer или Go OpenTelemetry SDK) и одновременно работает в Istio с включенной трассировкой, в Jaeger формируется визуальный мусор:
- Envoy создает серверный спан для входящего запроса.
- Приложение создает серверный спан для этого же запроса.
- При исходящем вызове приложение создает клиентский спан.
- Envoy создает еще один клиентский спан.
В результате один и тот же вызов представлен 4 спанами с практически одинаковым временем выполнения.

```
Без подавления дублей (4 спана на один вызов):
[Envoy Ingress: server]  ═════════════════════════════════════════════════ (102ms)
  └─ [App Ingress: server]   ═════════════════════════════════════════     (100ms)
       └─ [App Egress: client]    ═══════════════════════════════          (45ms)
            └─ [Envoy Egress: client] ══════════════════════════           (44ms)
```

#### Решение 1: Отключение генерации спанов прокси для инструментированных сервисов

Если приложение имеет качественную инструментацию уровня бизнес-логики, трассировку на уровне sidecar-прокси отключают через ресурс `Telemetry`, оставляя прокси только функцию прозрачного проброса заголовков:

```yaml
# disable-envoy-spans.yaml
apiVersion: telemetry.istio.io/v1
kind: Telemetry
metadata:
  name: disable-mesh-spans
  namespace: fintech-apps
spec:
  selector:
    matchLabels:
      app: payment-gateway # Применяется только к подам с in-app SDK
  tracing:
    - providers:
        - name: jaeger-otlp-grpc
      # Отключает создание и экспорт спанов данным Envoy-прокси
      disableSpanReporting: true
```

Примените конфигурацию:
```bash
kubectl apply -f disable-envoy-spans.yaml
# → telemetry.telemetry.istio.io/disable-mesh-spans created
```

#### Решение 2: Дедупликация и нормализация в конвейере Jaeger v2 Collector

Если отключить Envoy-трассировку невозможно (например, требуется контролировать задержку самого прокси), фильтрацию или склейку выполняют на уровне OpenTelemetry Collector в составе Jaeger v2 через процессор `filter` или трансформацию OTTL (OpenTelemetry Transformation Language):

```yaml
# jaeger-v2-collector-filter.yaml
processors:
  filter/drop_redundant_envoy:
    error_mode: ignore
    traces:
      span:
        # Отбросить исходящие клиентские спаны от Envoy, если сервис уже отдает App-спан
        - 'attributes["server"] == "envoy" and attributes["span.kind"] == "SpanKind.CLIENT" and resource.attributes["service.name"] == "payment-gateway"'

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, filter/drop_redundant_envoy, k8sattributes, batch]
      exporters: [jaeger_storage_exporter]
```

---

### Сценарий 4: Настройка трассировки в Linkerd 2.x с экспортом в Jaeger v2

**Контекст:** Сервисная сетка развернута на базе Linkerd 2.16+ (on-premise). Используются легковесные нативные микро-прокси `linkerd-proxy` на Rust. Необходимо настроить автоматический сбор сквозных трейсов с экспортом в централизованный Jaeger v2 Collector.

#### Шаг 1. Конфигурация Linkerd Control Plane

При установке или обновлении Linkerd через CLI задайте адрес OTLP-приемника Jaeger v2:

```bash
linkerd upgrade \
  --set "proxy.trace.collectorSvcAddr=jaeger-collector.jaeger-system.svc.cluster.local:4317" \
  --set "proxy.trace.collectorSvcAccount=jaeger-collector" \
  | kubectl apply -f -
# → configmap/linkerd-config replaced
# → deployment.apps/linkerd-destination replaced
```

#### Шаг 2. Разметка рабочей нагрузки (Workload Annotation)

Для включения отправки трейсов конкретным подом добавьте соответствующие аннотации в спецификацию Deployment:

```yaml
# linkerd-app.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: catalog-service
  namespace: store
spec:
  replicas: 2
  selector:
    matchLabels:
      app: catalog-service
  template:
    metadata:
      labels:
        app: catalog-service
      annotations:
        linkerd.io/inject: enabled
        # Указание адреса Jaeger v2 Collector для linkerd-proxy
        config.linkerd.io/trace-collector: "jaeger-collector.jaeger-system.svc.cluster.local:4317"
        # Процент сэмплирования (1 = 100%, 0.1 = 10%)
        config.alpha.linkerd.io/trace-sample-rate: "0.2"
    spec:
      containers:
        - name: app
          image: internal-registry.local/store/catalog:1.18.0
          ports:
            - containerPort: 8080
```

Примените манифест:
```bash
kubectl apply -f linkerd-app.yaml
# → deployment.apps/catalog-service configured
```

#### Шаг 3. Валидация интеграции Linkerd и Jaeger

1. Проверьте запуск `linkerd-proxy` и аргументы трассировки:
```bash
kubectl get pod -n store -l app=catalog-service -o jsonpath='{.items[0].spec.containers[?(@.name=="linkerd-proxy")].env[?(@.name=="LINKERD2_PROXY_TRACE_ATTRIBUTES_PATH")]}'
```

2. Отправьте тестовый запрос:
```bash
kubectl exec -n default deploy/curl-test -- curl -s http://catalog-service.store.svc.cluster.local:8080/products
# → [{"id":1,"name":"SSD 2TB"}]
```

3. Проверьте диагностику Linkerd:
```bash
linkerd diagnostics proxy-metrics -n store deploy/catalog-service | grep "trace_"
# → trace_spans_sent_total 4
# → trace_spans_failed_total 0
```

---

### Сценарий 5: Интеграция Cilium Service Mesh и Hubble с Jaeger v2

**Контекст:** Кластер использует Cilium CNI 1.16+ в режиме Service Mesh. Трафик маршрутизируется через встроенный узловой Envoy (Node-level Envoy). Требуется настроить экспорт L7 HTTP/gRPC спанов непосредственно в Jaeger v2.

#### Шаг 1. Включение Service Mesh и Envoy Tracing в Cilium

Обновите конфигурацию Helm для Cilium:

```bash
helm upgrade cilium cilium/cilium \
  --namespace kube-system \
  --reuse-values \
  --set serviceMesh.enabled=true \
  --set envoy.enabled=true \
  --set hubble.enabled=true \
  --set hubble.relay.enabled=true \
  --set hubble.openTelemetry.enabled=true \
  --set hubble.openTelemetry.collector.address="jaeger-collector.jaeger-system.svc.cluster.local:4317"
```

#### Шаг 2. Декларативная настройка CiliumClusterwideEnvoyConfig

Для включения генерации спанов трассировки на уровне встроенного Envoy создайте ресурс `CiliumClusterwideEnvoyConfig`:

```yaml
# cilium-envoy-tracing.yaml
apiVersion: cilium.io/v2
kind: CiliumClusterwideEnvoyConfig
metadata:
  name: global-envoy-tracing
spec:
  services:
    - name: api-gateway
      namespace: production
      ports: [80, 443]
  resources:
    - "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
      tracing:
        provider:
          name: envoy.tracers.opentelemetry
          typed_config:
            "@type": type.googleapis.com/envoy.config.trace.v3.OpenTelemetryConfig
            grpc_service:
              envoy_grpc:
                cluster_name: jaeger_collector_otlp
            service_name: cilium-ingress-envoy
```

#### Шаг 3. Валидация работы Cilium Envoy Tracing

1. Проверьте статус Cilium Service Mesh:
```bash
cilium service list
# → 1   10.96.0.10:53       ClusterIP   1/1 active   kube-system/kube-dns
# → 2   10.96.14.88:80      ClusterIP   2/2 active   production/api-gateway

cilium status | grep -i "service mesh"
# → Service Mesh:       OK (Envoy: OK)
```

2. Выполните запрос к эндпоинту и убедитесь в отправке спанов:
```bash
curl -I http://api.internal.local/orders
# → HTTP/1.1 200 OK
# → traceparent: 00-6a7f8b9c0d1e2f3a4b5c6d7e8f9a0b1c-1a2b3c4d5e6f7a8b-01
```

3. Проверьте экспорт в Jaeger через CLI:
```bash
hubble observe --protocol http --trace-id 6a7f8b9c0d1e2f3a4b5c6d7e8f9a0b1c
# → TIMESTAMP            SOURCE                 DESTINATION            TYPE   SUMMARY
# → Oct 12 15:10:01.124  10.244.1.15:48912     10.244.2.80:8080       L7     HTTP/1.1 200 OK (GET /orders) [trace_id=6a7f8b...]
```

---

### Сценарий 6: Production-конфигурация Jaeger v2 Collector для Service Mesh

Ниже представлен проверенный эталонный манифест конфигурации **Jaeger v2 Collector** на базе OpenTelemetry Collector. Конфигурация включает защиту от перегрузок по памяти (`memory_limiter`), обогащение контекстом метаданных Kubernetes (`k8sattributes`), эффективный батчинг и запись в on-premise ClickHouse-кластер.

```yaml
# jaeger-v2-mesh-collector.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: jaeger-v2-configuration
  namespace: jaeger-system
data:
  config.yaml: |
    service:
      extensions: [health_check, jaeger_storage]
      pipelines:
        traces:
          receivers: [otlp]
          processors: [memory_limiter, k8sattributes, batch]
          exporters: [jaeger_storage_exporter]
      telemetry:
        metrics:
          address: "0.0.0.0:8888"
        logs:
          level: "info"

    extensions:
      health_check:
        endpoint: "0.0.0.0:13133"
      
      jaeger_storage:
        backends:
          clickhouse_main:
            type: clickhouse
            clickhouse:
              endpoint: "tcp://clickhouse-cluster.database.svc.cluster.local:9000"
              database: "jaeger_mesh_traces"
              username: "jaeger_writer"
              password: "${env:CLICKHOUSE_PASSWORD}"
              connection_timeout: 5s
              cluster: "company_cluster"

    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: "0.0.0.0:4317"
            max_concurrent_streams: 1024
            max_recv_msg_size_mib: 16
            keepalive:
              server_parameters:
                max_connection_idle: 60s
                max_connection_age: 300s
                time: 30s
                timeout: 5s
          http:
            endpoint: "0.0.0.0:4318"

    processors:
      # Защита от OOM при всплесках трафика Service Mesh
      memory_limiter:
        check_interval: 1s
        limit_percentage: 80
        spike_limit_percentage: 20

      # Обогащение спанов именами подов, узлов и неймспейсов по IP-адресу
      k8sattributes:
        auth_type: "serviceAccount"
        passthrough: false
        filter:
          node_from_env_var: K8S_NODE_NAME
        extract:
          metadata:
            - k8s.pod.name
            - k8s.pod.uid
            - k8s.deployment.name
            - k8s.namespace.name
            - k8s.node.name
        pod_association:
          - sources:
              - from: resource_attribute
                name: k8s.pod.ip
          - sources:
              - from: connection

      # Оптимизация сетевых вставок в хранилище
      batch:
        send_batch_size: 8192
        timeout: 1s
        send_batch_max_size: 16384

    exporters:
      jaeger_storage_exporter:
        trace_storage: clickhouse_main
```

---

## Операции и диагностика

### Команды проверки состояния Service Mesh прокси

#### 1. Диагностика синхронизации Envoy и Istiod
```bash
# Проверка статуса синхронизации прокси со всеми подсистемами Istiod
istioctl proxy-status
# → NAME                                                  CDS        LDS        EDS        RDS        ISTIOD                      VERSION
# → client-app-579bc7584f-wlzf2.default                   SYNCED     SYNCED     SYNCED     SYNCED     istiod-7b98d45d8b-pxk6t     1.24.2
# → server-app-84c4789df9-j4k2m.default                   SYNCED     SYNCED     SYNCED     SYNCED     istiod-7b98d45d8b-pxk6t     1.24.2

# Валидация синтаксиса и совместимости ресурсов в кластере
istioctl analyze -n default
# → ✔ No validation issues found when analyzing namespace: default.
```

#### 2. Инспекция сгенерированного Bootstrap и Tracing-кластера в Envoy
```bash
# Проверка конфигурации кластера отправки трейсов
istioctl proxy-config cluster client-app-579bc7584f-wlzf2.default \
  --fqdn jaeger-collector.jaeger-system.svc.cluster.local
# → SERVICE FQDN                                                PORT     SUBSET     DIRECTION     TYPE
# → jaeger-collector.jaeger-system.svc.cluster.local           4317     -          outbound      EDS

# Проверка эндпоинтов коллектора, доступных сайдкару
istioctl proxy-config endpoints client-app-579bc7584f-wlzf2.default \
  --cluster "outbound|4317||jaeger-collector.jaeger-system.svc.cluster.local"
# → ENDPOINT              STATUS      OUTLIER CHECK     CLUSTER PRIORITY
# → 10.244.3.42:4317      HEALTHY     OK                0
# → 10.244.4.18:4317      HEALTHY     OK                0
```

#### 3. Чтение метрик трассировки через Envoy Admin API (:15000)
```bash
# Проверка количества успешно отправленных и отброшенных спанов
kubectl exec -n default deploy/client-app -c istio-proxy -- \
  curl -s 127.0.0.1:15000/stats | grep -E "tracing|jaeger"
# → tracing.opentelemetry.spans_sent: 18450
# → tracing.opentelemetry.reports_failed: 0
# → tracing.opentelemetry.reports_dropped: 0
# → cluster.outbound|4317||jaeger-collector.jaeger-system.svc.cluster.local.upstream_cx_active: 1
```

#### 4. Проверка заголовков W3C через `tcpdump` во фрейме пода
```bash
# Захват первых 10 HTTP-пакетов для проверки наличия traceparent
kubectl exec -n default deploy/server-app -c istio-proxy -- \
  tcpdump -vv -A -i eth0 'tcp port 8080 and (((ip[2:2] - ((ip[0]&0xf)<<2)) - ((tcp[12:1]&0xf0)>>2)) != 0)' -c 1 \
  | grep -i "traceparent"
# → traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
```

---

## Типичные проблемы и устранение неполадок

| Проблема | Причина сбоя | Метод диагностики | Способ решения |
| :--- | :--- | :--- | :--- |
| **Разорванные трейсы (Broken Traces)** | Приложение принимает входящий `traceparent`, но не копирует его в исходящие HTTP-вызовы к другим сервисам | В Jaeger UI один бизнес-процесс виден как несколько отдельных несвязанных трейсов с 1–2 спанами | Обновить клиентский HTTP-код приложения: настроить автоматический перенос заголовков или использовать OTel SDK HTTP Client Wrapper |
| **Всплеск счетчика `reports_failed`** | Envoy не может установить gRPC-соединение с Jaeger Collector (неверный порт, таймаут, сетевая политика) | `kubectl exec <pod> -c istio-proxy -- curl -s 127.0.0.1:15000/stats \| grep reports_failed` | Проверить доступность `jaeger-collector:4317`, проверить NetworkPolicy и таймаут в `extensionProviders` |
| **Сетевая петля (Telemetry Loop)** | Трафик отправки спанов от Envoy на порт 4317 перехватывается этим же сайдкаром и порождает новые спаны | Экспоненциальный рост нагрузки на CPU Envoy и коллектора; счетчики спанов лавинообразно растут | Добавить аннотацию `traffic.sidecar.istio.io/excludeOutboundPorts: "4317,4318"` или отключить инъекцию у коллектора |
| **Дублирование серверных и клиентских спанов** | И Envoy, и приложение через OTel SDK генерируют спаны для одного и того же вызова | В трейсе дублируются пары вызовов с одинаковыми таймингами | Применить Telemetry CR с `disableSpanReporting: true` для подов с полным SDK или настроить SpanProcessor фильтрации |
| **Ambient Ztunnel не генерирует L7 спаны** | Архитектурное ограничение: Ztunnel работает строго на L4 уровне и не парсит протоколы HTTP/gRPC | В Jaeger отсутствуют HTTP-спаны от подов в пространстве имен с Ambient | Развернуть L7 Waypoint Proxy (`istio-waypoint`) и связать его с пространством имен через `istio.io/use-waypoint` |
| **Отсутствие метаданных подов и нод в спанах** | В Jaeger v2 не настроен процессор `k8sattributes` или у ServiceAccount коллектора нет прав RBAC | В тегах спана отсутствуют поля `k8s.pod.name`, `k8s.namespace.name` | Добавить ClusterRole с правами `get`, `watch`, `list` на ресурсы `pods`, `namespaces`, `nodes` для Jaeger Collector |
| **Ошибки `GOAWAY` / разрыв gRPC стримов** | Рассогласование HTTP/2 Keepalive между Envoy и OTLP-приемником Jaeger Collector | В логах Jaeger v2: `transport: closing transport due to idleness` или `too_many_pings` | Согласовать параметры `keepalive.server_parameters` в приемнике OTLP Jaeger v2 и таймауты в `extensionProviders` |
| **Смещение таймингов спанов (Clock Skew)** | Дочерний спан начинается раньше родительского из-за рассинхронизации времени между серверами кластера | В Jaeger UI отображается предупреждение: "Clock skew adjustment detected" | Настроить и проверить службу синхронизации времени `chrony` / `ntpd` на всех физических серверах (bare-metal) |

### Детальный SRE-кейс: Расследование разорванных трейсов в Istio

#### Симптом
Пользователь выполняет операцию оформления заказа. В Jaeger UI трейс состоит всего из одного спана `istio-ingressgateway`. Вызовы между `order-service`, `payment-service` и `warehouse-service` отображаются как три независимых трейса с новыми `trace_id`.

#### Диагностика по шагам
1. Проверяем наличие исходящего заголовка `traceparent` на выходе из `order-service`:
```bash
kubectl exec -n default deploy/order-service -c istio-proxy -- \
  curl -s 127.0.0.1:15000/stats | grep "tracing.opentelemetry"
# → tracing.opentelemetry.spans_sent: 120
```
Сайдкар отправляет спаны, но `trace_id` не совпадает с входящим запросом.

2. Выполняем тестовый curl-запрос с явным заголовком `traceparent` и проверяем логи приложения:
```bash
curl -v -H "traceparent: 00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01" \
  http://ingress.internal.local/orders
```

3. Смотрим логи контейнера `order-service`:
```bash
kubectl logs -n default deploy/order-service -c app --tail=50 | grep -i "trace"
# → [INFO] Received order request. Forwarding to payment-service...
# → [DEBUG] Outgoing headers: map[Accept:[*/*] User-Agent:[Go-http-client/1.1]]
```
**Корень проблемы:** В исходящих заголовках HTTP-клиента отсутствует `traceparent`. Приложение отбросило входящие заголовки контекста.

#### Исправление
В исходном коде сервиса (на примере Go) добавляется передача контекста через `otelhttp` или ручное копирование заголовков:
```go
// Правильная передача контекста в исходящий HTTP-запрос:
req, _ := http.NewRequestWithContext(ctx, "POST", paymentURL, body)
otel.GetTextMapPropagator().Inject(ctx, propagation.HeaderCarrier(req.Header))
resp, err := httpClient.Do(req)
```
После деплоя обновленной версии `order-service` все 4 сервиса объединяются в единое дерево распределенного трейса.

---

## Лучшие практики SRE и DevOps

1. **Единый стандарт W3C Trace Context по всему периметру:**
   Исключите использование legacy-заголовков B3 (`X-B3-*`) и Jaeger Thrift (`uber-trace-id`). Настройте все сервисные сетки (Istio, Linkerd, Cilium) и библиотеки приложений на работу со стандартом W3C (`traceparent`, `tracestate`). Это предотвратит деградацию контекста при прохождении через гетерогенные прокси.

2. **Защита от сетевых петель телеметрии (Exclude Outbound Ports):**
   Всегда изолируйте порты экспорта телеметрии `4317` (gRPC) и `4318` (HTTP) от перехвата сайдкарами:
   ```yaml
   traffic.sidecar.istio.io/excludeOutboundPorts: "4317,4318"
   ```
   Отсутствие этой настройки может привести к лавинообразному зацикливанию сетевого трафика и отказу рабочих узлов кластера.

3. **Разумные политики сэмплирования (Adaptive / Head Sampling):**
   В высоконагруженных bare-metal кластерах (более 20 000 RPS) установка 100% сэмплирования в Service Mesh приведет к исчерпанию дисковой подсистемы и деградации производительности Envoy.
   - Используйте глобальный процент сэмплирования `1.0% – 5.0%` для рутинного 2xx-трафика.
   - Настройте гарантированное сохранение спанов с ошибками (5xx, таймауты) через хвостовое сэмплирование (Tail Sampling Processor) на уровне кластера коллекторов Jaeger v2 Gateway.

4. **Проброс контекста Baggage для мультитенантности:**
   Используйте W3C Baggage для передачи служебных метаданных (например, `tenant_id`, `environment`, `user_tier`) сквозь цепочку микросервисов. Настройте Envoy на копирование заголовка `baggage` в спаны через параметр `customTags`:
   ```yaml
   customTags:
     tenant_id:
       header:
         name: "baggage"
         defaultValue: "anonymous"
   ```

5. **Ограничение ресурсов и таймаутов буферов прокси:**
   Envoy буферизует спаны в оперативной памяти перед отправкой в коллектор. Задавайте жесткие лимиты памяти и короткие таймауты (`timeout: 2s`), чтобы временная недоступность Jaeger v2 Collector не приводила к росту задержки бизнес-вызовов и деградации памяти микросервисов.

6. **Синхронизация времени узлов (NTP / Chrony):**
   Распределенная трассировка критически зависит от синхронности системных часов. Обеспечьте расхождение времени между серверами кластера не более 1–2 миллисекунд с помощью локальных демонов `chrony`.

---

## Очистка окружения

Команды для безопасного и идемпотентного удаления тестовых ресурсов интеграции:

```bash
# Удаление глобальных и локальных ресурсов Telemetry в Istio
kubectl delete telemetry global-mesh-tracing -n istio-system --ignore-not-found=true
kubectl delete telemetry waypoint-tracing -n fintech-apps --ignore-not-found=true
kubectl delete telemetry disable-mesh-spans -n fintech-apps --ignore-not-found=true

# Удаление шлюза Waypoint (Ambient Mesh)
kubectl delete gateway namespace-waypoint -n fintech-apps --ignore-not-found=true
kubectl label namespace fintech-apps istio.io/use-waypoint- --ignore-not-found=true

# Удаление кастомных Envoy-конфигураций Cilium
kubectl delete ciliumclusterwideenvoyconfig global-envoy-tracing --ignore-not-found=true

# Удаление конфигураций и тестовых подов
kubectl delete -f jaeger-v2-mesh-collector.yaml -n jaeger-system --ignore-not-found=true
```

---

## Дополнительная информация

**Смежные материалы базы знаний:**
- Общие концепции и компоненты: **[Обзор Jaeger](./jaeger_overview.md)**
- Архитектура Unified Binary v2: **[Архитектура Jaeger](./jaeger_architecture.md)**
- Конфигурация OTLP-приемников: **[Конфигурация OTLP для Jaeger](./jaeger_otlp_configuration.md)**
- Тюнинг сетевой безопасности и TLS: **[Безопасность и харденинг Jaeger](./jaeger_security_hardening.md)**
- Развертывание в Kubernetes: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**
- Обзор наблюдаемости Istio: **[Наблюдаемость в Istio: Kiali, телеметрия и федерация идентичности](../Service_Mesh/istio_observability_and_tools.md)**
- Архитектурное сравнение сеток: **[Сравнение Istio и Linkerd](../Service_Mesh/istio_vs_linkerd.md)**
- Сетевые концепции сервисных сеток: **[Service Mesh: основные концепции](../Service_Mesh/service_mesh_concepts.md)**

### Официальные источники и документация

- [Istio Telemetry API Specification](https://istio.io/latest/docs/reference/config/telemetry/)
- [Istio OpenTelemetry Tracing Integration Guide](https://istio.io/latest/docs/tasks/observability/distributed-tracing/telemetry-api/)
- [Istio Ambient Mesh Observability Architecture](https://istio.io/latest/docs/ambient/overview/)
- [Linkerd Distributed Tracing with OpenTelemetry](https://linkerd.io/2.16/tasks/distributed-tracing/)
- [Cilium Service Mesh Envoy Tracing Documentation](https://docs.cilium.io/en/stable/network/servicemesh/)
- [W3C Trace Context Recommendation](https://www.w3.org/TR/trace-context/)
