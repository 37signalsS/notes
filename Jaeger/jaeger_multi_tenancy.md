# Multi-tenancy и изоляция в Jaeger

**Актуально для:** Jaeger v2.x / OpenTelemetry Operator v0.118+ / Kubernetes 1.28–1.32 / ClickHouse 24.x–26.x

> **Статус:** Документация описывает архитектуру и эксплуатацию **Jaeger v2** (на базе кодовой базы OpenTelemetry Collector). В отличие от систем со встроенной мультитенантностью (таких как Grafana Tempo или Mimir с заголовком `X-Scope-OrgID`), в Jaeger изоляция реализуется на уровне инфраструктуры, конвейеров OpenTelemetry Collector (Namespace isolation, routing connectors, раздельные схемы хранения ClickHouse) и аутентифицирующих прокси-шлюзов. Рассматриваются исключительно on-premise и bare-metal сценарии без привязки к проприетарным облачным сервисам и без AI-компонентов.

**Multi-tenancy в Jaeger** — это архитектурный подход к размещению данных нескольких команд, проектов или контуров безопасности в общей инфраструктуре распределенной трассировки с обеспечением строгой изоляции данных, предотвращением взаимного влияния (noisy neighbor effect) и поддержкой раздельного учета затрат (chargeback/showback).

Общий обзор системы: **[Обзор Jaeger](./jaeger_overview.md)**.
Архитектура компонентов: **[Архитектура Jaeger](./jaeger_architecture.md)**.
Интеграция с Kubernetes: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**.
Хранилище данных: **[Storage Deep Dive для Jaeger](./jaeger_storage_deep_dive.md)**.
Безопасность и hardening: **[Security Hardening для Jaeger](./jaeger_security_hardening.md)**.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Multi-tenancy (Мультитенантность)** | Архитектурный паттерн, при котором единый комплекс сервисов трассировки обслуживает несколько независимых изолированных арендаторов (tenants) |
| **Tenant (Тенант)** | Логически изолированная единица (команда разработки, сервис, проект, окружение), владеющая своими спанами и трассами |
| **Namespace Isolation** | Изоляция на уровне пространств имен Kubernetes с разделением RBAC, ServiceAccount, ResourceQuota и NetworkPolicy |
| **Routing Connector / Processor** | Компонент конвейера OpenTelemetry Collector (`routing`), перенаправляющий потоки спанов в разные пайплайны и хранилища на основе метаданных, заголовков или атрибутов |
| **Storage-based Isolation** | Разделение данных тенантов на уровне бэкенда хранения (отдельные базы данных, таблицы или наборы индексов) |
| **Row-Level Security (RLS / Row Policy)** | Механизм СУБД (например, ClickHouse Row Policy), ограничивающий чтение строк таблицы в зависимости от роли или учетной записи пользователя |
| **Tenant Context / Header** | Идентификатор тенанта, передаваемый в HTTP/gRPC заголовках (например, `x-tenant-id`) или ресурсах OTLP (`tenant.id`, `service.namespace`) |
| **Noisy Neighbor Problem** | Ситуация, когда один тенант генерирует аномальный всплеск спанов и монополизирует CPU, RAM, очереди коллектора или I/O хранилища, деградируя обработку данных других тенантов |
| **Authenticating Reverse Proxy** | Шлюз безопасности (Nginx, Envoy, OAuth2-Proxy) перед Jaeger Query/UI, выполняющий аутентификацию и маршрутизацию запросов к интерфейсу соответствующего тенанта |
| **ResourceQuota & LimitRange** | Политики ядра Kubernetes, гарантирующие лимиты вычислительных ресурсов на уровне пространств имен во избежание захвата кластера одним тенантом |
| **Chargeback** | Финансово-технический механизм атрибуции фактических затрат инфраструктуры (диск, сеть, процессорное время) конкретным подразделениям |
| **Showback** | Аналитическая отчетность по потреблению ресурсов тенантами без прямого списания бюджета |
| **Cross-Tenant Trace Leakage** | Непреднамеренное раскрытие внутренней архитектуры, путей вызовов или секретов одного тенанта пользователям другого тенанта через связанные трассы |

---

## Базовые концепции и архитектура изоляции

### Специфика мультитенантности в Jaeger v2

Jaeger исторически проектировался как доверенная внутренняя система организации без встроенного концепта тенантных аккаунтов внутри Jaeger Query и Jaeger UI. В версии **Jaeger v2**, благодаря переходу на ядро OpenTelemetry Collector, механизмы мультитенантности выстраиваются на базе композиции стандартных компонентов:

```
                            [ Входящий трафик приложений ]
                                          │
            ┌─────────────────────────────┴─────────────────────────────┐
            ▼                                                           ▼
┌───────────────────────────────┐           ┌───────────────────────────────┐
│ Namespace: team-billing       │           │ Namespace: team-analytics     │
│ App Pods (OTel SDK)           │           │ App Pods (OTel SDK)           │
│ Header: x-tenant-id=billing   │           │ Header: x-tenant-id=analytics │
└───────────────┬───────────────┘           └───────────────┬───────────────┘
                │ OTLP:4317                                 │ OTLP:4317
                ▼                                           ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ Jaeger v2 Ingestion Gateway / Collectors                                  │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ OTLP Receiver (:4317 / :4318)                                       │  │
│  └──────────────────────────────────┬──────────────────────────────────┘  │
│                                     ▼                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ Processors: memory_limiter ──▶ transform/attributes                 │  │
│  └──────────────────────────────────┬──────────────────────────────────┘  │
│                                     ▼                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ Connector: routing (по x-tenant-id или tenant.id)                   │  │
│  └──────────────┬───────────────────────────────────────┬──────────────┘  │
│                 │                                       │                 │
│                 ▼                                       ▼                 │
│  ┌─────────────────────────────┐         ┌─────────────────────────────┐  │
│  │ Pipeline: traces/billing    │         │ Pipeline: traces/analytics  │  │
│  │ Exporter: storage/billing   │         │ Exporter: storage/analytics │  │
│  └──────────────┬──────────────┘         └──────────────┬──────────────┘  │
└─────────────────┼───────────────────────────────────────┼─────────────────┘
                  ▼                                       ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ ClickHouse Cluster (On-Premise Bare-Metal)                                │
│                                                                           │
│  ┌─────────────────────────────┐         ┌─────────────────────────────┐  │
│  │ Database: jaeger_billing    │         │ Database: jaeger_analytics  │  │
│  │ User: jaeger_query_billing  │         │ User: jaeger_query_analytics│  │
│  └──────────────┬──────────────┘         └──────────────┬──────────────┘  │
└─────────────────┼───────────────────────────────────────┼─────────────────┘
                  ▲                                       ▲
                  │                                       │
┌─────────────────┴─────────────┐         ┌───────────────┴─────────────────┐
│ Jaeger Query Pod (Billing)    │         │ Jaeger Query Pod (Analytics)    │
│ Namespace: tenant-billing     │         │ Namespace: tenant-analytics     │
└───────────────▲───────────────┘         └───────────────▲─────────────────┘
                │                                         │
┌───────────────┴─────────────────────────────────────────┴─────────────────┐
│ Ingress / Reverse Proxy (Nginx / Envoy) с mTLS / LDAP / Basic Auth        │
│ Маршрутизация инженеров к UI соответствующего тенанта                     │
└───────────────────────────────────────────────────────────────────────────┘
```

### Модели multi-tenancy

| Модель | Описание архитектуры | Степень изоляции | Сложность эксплуатации | Расход ресурсов | Риск Noisy Neighbor |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Dedicated Instances** | Независимый стек Jaeger (Collector, Query, Storage) на каждого тенанта | Абсолютная | Высокая (N стеков) | Высокий (минимальный оверхед N раз) | Отсутствует |
| **2. Routing + Storage Isolation** | Общий Ingestion Gateway; спаны маршрутизируются в отдельные БД/таблицы ClickHouse; отдельные Jaeger Query на тенанта | Высокая | Средняя | Средний (эффективное разделение I/O) | Низкий (на уровне БД квоты) |
| **3. Shared Storage + RLS** | Общий Collector и единая таблица ClickHouse с колонкой `tenant`; доступ ограничивается через Row Policies | Средняя | Средняя | Низкий | Высокий (тяжелый запрос влияет на всех) |
| **4. Namespace-based (K8s)** | Разделение коллекторов по неймспейсам K8s с отдельными ServiceAccount, NetworkPolicy и квотами | Высокая внутри K8s | Низкая/Средняя | Средний | Изолирован cgroups |

### Граничные контуры изоляции

При проектировании multi-tenant архитектуры трассировки SRE-инженер обязан контролировать пять плоскостей изоляции:

1. **Плоскость приема (Ingestion plane):** Защита портов OTLP (4317 gRPC, 4318 HTTP) с помощью NetworkPolicy, взаимного TLS (mTLS) и валидации метаданных. Неавторизованный сервис не должен иметь возможности отправить спаны с чужим `tenant.id`.
2. **Плоскость вычислений (Compute plane):** Ограничение CPU и RAM коллекторов через Kubernetes `resources.limits`, `ResourceQuota` и процессор `memory_limiter`. Если один тенант включил debug-трассировку на 100 000 спанов/сек, коллектор не должен уходить в OOMKilled для других потоков.
3. **Плоскость хранения (Storage plane):** Физическое разграничение директорий, баз данных или таблиц в ClickHouse. Назначение пользователям СУБД прав `GRANT SELECT, INSERT ON jaeger_<tenant>.*`.
4. **Плоскость чтения и визуализации (Query/UI plane):** Разделение инстансов `jaeger-query` либо их защита обратным прокси с принудительной проверкой прав и фильтрацией.
5. **Сетевая плоскость (Network plane):** Запрет межсетевого взаимодействия между неймспейсами через Kubernetes CNI (Calico/Cilium) NetworkPolicies.

---

## Практические сценарии

### Сценарий 1: Сетевая и ресурсная изоляция в Kubernetes (Namespace Isolation + NetworkPolicy)

**Ситуация:** В кластере Kubernetes необходимо изолировать контуры двух подразделений — `tenant-billing` и `tenant-auth`. Трассировочный трафик сервисов одного неймспейса не должен попадать в коллекторы другого, а коллекторы не должны выходить за рамки выделенных квот памяти и ядер.

#### Предусловия
- Кластер Kubernetes 1.28–1.32 с установленным CNI с поддержкой NetworkPolicy (Calico, Cilium).
- Установленный OpenTelemetry Operator v0.118+.
- Утилиты командной строки: `kubectl`, `curl`.

#### Пошаговое руководство

##### Шаг 1: Создание изолированных неймспейсов и ресурсных квот

```yaml
# manifests/01-namespaces-quotas.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: tenant-billing
  labels:
    tenant: billing
    monitoring-tier: gold
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: billing-tracing-quota
  namespace: tenant-billing
spec:
  hard:
    requests.cpu: "4"
    requests.memory: 8Gi
    limits.cpu: "8"
    limits.memory: 16Gi
    pods: "10"
---
apiVersion: v1
kind: LimitRange
metadata:
  name: billing-limit-range
  namespace: tenant-billing
spec:
  limits:
    - default:
        cpu: "1"
        memory: 2Gi
      defaultRequest:
        cpu: 500m
        memory: 1Gi
      type: Container
```

Применение манифеста:
```bash
kubectl apply -f manifests/01-namespaces-quotas.yaml
# → namespace/tenant-billing created
# → resourcequota/billing-tracing-quota created
# → limitrange/billing-limit-range created
```

##### Шаг 2: RBAC с принципом наименьших привилегий

В отличие от небезопасных ClusterRoleBinding, права коллектора строго ограничиваются границами неймспейса через `Role` и `RoleBinding`:

```yaml
# manifests/02-rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: jaeger-collector-billing
  namespace: tenant-billing
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: jaeger-collector-local
  namespace: tenant-billing
rules:
  - apiGroups: [""]
    resources: ["endpoints", "services", "configmaps"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: jaeger-collector-binding
  namespace: tenant-billing
subjects:
  - kind: ServiceAccount
    name: jaeger-collector-billing
    namespace: tenant-billing
roleRef:
  kind: Role
  name: jaeger-collector-local
  apiGroup: rbac.authorization.k8s.io
```

Применение манифеста:
```bash
kubectl apply -f manifests/02-rbac.yaml
# → serviceaccount/jaeger-collector-billing created
# → role.rbac.authorization.k8s.io/jaeger-collector-local created
# → rolebinding.rbac.authorization.k8s.io/jaeger-collector-binding created
```

##### Шаг 3: Настройка NetworkPolicy для блокировки межтенантного доступа

```yaml
# manifests/03-network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: billing-tracing-isolation
  namespace: tenant-billing
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: jaeger-collector-billing
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Разрешаем входящий трафик OTLP только от приложений внутри этого же namespace
    - from:
        - podSelector:
            matchLabels:
              telemetry: enabled
      ports:
        - protocol: TCP
          port: 4317 # OTLP gRPC
        - protocol: TCP
          port: 4318 # OTLP HTTP
  egress:
    # Разрешаем отправку спанов во внешний/инфраструктурный ClickHouse
    - to:
        - ipBlock:
            cidr: 192.168.10.0/24
      ports:
        - protocol: TCP
          port: 9000 # ClickHouse native protocol
    # Разрешаем обращения к DNS кластера
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
```

Применение манифеста:
```bash
kubectl apply -f manifests/03-network-policy.yaml
# → networkpolicy.networking.k8s.io/billing-tracing-isolation created
```

##### Шаг 4: Развертывание изолированного Jaeger v2 Collector через OpenTelemetryCollector CR

```yaml
# manifests/04-otel-collector.yaml
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: jaeger-collector-billing
  namespace: tenant-billing
spec:
  serviceAccount: jaeger-collector-billing
  config:
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
          http:
            endpoint: 0.0.0.0:4318

    processors:
      memory_limiter:
        check_interval: 1s
        limit_percentage: 80
        spike_limit_percentage: 20
      batch:
        send_batch_size: 8192
        timeout: 1s
      attributes:
        actions:
          - key: tenant.id
            value: "billing"
            action: insert

    extensions:
      healthcheckv2:
        endpoint: 0.0.0.0:13133
      jaeger_storage:
        backends:
          billing_ch:
            clickhouse:
              endpoint: "tcp://192.168.10.50:9000"
              database: "jaeger_billing"
              username: "collector_billing"
              password: "SecureBillingPassword123!"

    exporters:
      jaeger_storage_exporter:
        trace_storage: billing_ch

    service:
      extensions: [healthcheckv2, jaeger_storage]
      pipelines:
        traces:
          receivers: [otlp]
          processors: [memory_limiter, attributes, batch]
          exporters: [jaeger_storage_exporter]
```

Применение манифеста:
```bash
kubectl apply -f manifests/04-otel-collector.yaml
# → opentelemetrycollector.opentelemetry.io/jaeger-collector-billing created
```

#### Валидация изоляции

1. Проверка успешного запуска коллектора:
```bash
kubectl get pods -n tenant-billing -l app.kubernetes.io/name=jaeger-collector-billing
# → NAME                                        READY   STATUS    RESTARTS   AGE
# → jaeger-collector-billing-collector-7f99b-x   1/1     Running   0          42s
```

2. Проверка доступности портов из авторизованного пода в неймспейсе `tenant-billing`:
```bash
kubectl run test-client --image=curlimages/curl --labels="telemetry=enabled" -n tenant-billing --rm -it --restart=Never -- curl -s -v http://jaeger-collector-billing-collector:4318/v1/traces
# → Connected to jaeger-collector-billing-collector (10.96.14.22) port 4318
# → HTTP/1.1 405 Method Not Allowed
```

3. Проверка блокировки доступа сетевой политикой из чужого неймспейса `default`:
```bash
kubectl run test-foreign --image=curlimages/curl -n default --rm -it --restart=Never -- curl --connect-timeout 3 http://jaeger-collector-billing-collector.tenant-billing:4318/v1/traces
# → curl: (28) Connection timed out after 3001 milliseconds
# → command terminated with exit code 28
```

---

### Сценарий 2: Маршрутизация OTLP-потоков по тенантам в Jaeger v2 (Routing Connector к изолированным базам ClickHouse)

**Ситуация:** Имеется единая входная точка приема телеметрии (Gateway Collector), куда приложения разных команд отправляют OTLP-трафик с указанием HTTP-заголовка `x-tenant-id` или атрибута ресурса `tenant.id`. Необходимо автоматически маршрутизировать спаны в изолированные базы данных ClickHouse (`jaeger_billing` и `jaeger_analytics`), предотвращая смешивание данных.

#### Предусловия
- Кластер ClickHouse 24.x/26.x доступен по адресу `tcp://192.168.10.50:9000`.
- Jaeger v2 бинарный дистрибутив или OpenTelemetry Collector Contrib.

#### Пошаговое руководство

##### Шаг 1: Подготовка изолированных баз данных и прав доступа в ClickHouse

Выполняем SQL-скрипт инициализации через `clickhouse-client`:

```sql
-- Создание изолированных баз данных
CREATE DATABASE IF NOT EXISTS jaeger_billing;
CREATE DATABASE IF NOT EXISTS jaeger_analytics;
CREATE DATABASE IF NOT EXISTS jaeger_default;

-- Таблица спанов для контура billing
CREATE TABLE IF NOT EXISTS jaeger_billing.spans
(
    trace_id String,
    span_id String,
    operation_name String,
    start_time_ns UInt64,
    duration_ns UInt64,
    service_name String,
    tags Map(String, String),
    logs Array<JSON>,
    references Array<String>,
    process Array<String>,
    flags UInt32,
    PRIMARY KEY (trace_id, span_id)
)
ENGINE = MergeTree()
PARTITION BY toDate(fromUnixTimestamp64Nano(start_time_ns))
ORDER BY (service_name, operation_name, start_time_ns)
TTL toDateTime(start_time_ns / 1000000000) + INTERVAL 14 DAY
SETTINGS index_granularity = 8192;

-- Таблица спанов для контура analytics
CREATE TABLE IF NOT EXISTS jaeger_analytics.spans AS jaeger_billing.spans;
CREATE TABLE IF NOT EXISTS jaeger_default.spans AS jaeger_billing.spans;

-- Создание пользователей с изолированными правами
CREATE USER IF NOT EXISTS user_billing IDENTIFIED WITH sha256_password BY 'BillingSecretPass99!';
CREATE USER IF NOT EXISTS user_analytics IDENTIFIED WITH sha256_password BY 'AnalyticsSecretPass99!';

GRANT SELECT, INSERT ON jaeger_billing.* TO user_billing;
GRANT SELECT, INSERT ON jaeger_analytics.* TO user_analytics;
```

Применение через CLI:
```bash
clickhouse-client --host=192.168.10.50 --multiquery < /opt/jaeger/init_tenants.sql
# → Query id: c0487dfb-085f-402a-9214-41b9e0f631df
# → Ok.
```

##### Шаг 2: Конфигурация Jaeger v2 с Routing Connector

В файле конфигурации коллектора настраивается `connectors.routing`, который анализирует контекст запроса и передает батчи в соответствующий экспортёр:

```yaml
# /etc/jaeger/jaeger-v2-routing.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 80
    spike_limit_percentage: 20
  batch:
    send_batch_max_size: 4096
    timeout: 1s

connectors:
  routing:
    default_pipelines: [traces/default]
    error_mode: ignore
    table:
      - statement: route() where resource.attributes["tenant.id"] == "billing" or context["x-tenant-id"] == "billing"
        pipelines: [traces/billing]
      - statement: route() where resource.attributes["tenant.id"] == "analytics" or context["x-tenant-id"] == "analytics"
        pipelines: [traces/analytics]

extensions:
  healthcheckv2:
    endpoint: 0.0.0.0:13133
  jaeger_storage:
    backends:
      storage_billing:
        clickhouse:
          endpoint: "tcp://192.168.10.50:9000"
          database: "jaeger_billing"
          username: "user_billing"
          password: "BillingSecretPass99!"
      storage_analytics:
        clickhouse:
          endpoint: "tcp://192.168.10.50:9000"
          database: "jaeger_analytics"
          username: "user_analytics"
          password: "AnalyticsSecretPass99!"
      storage_default:
        clickhouse:
          endpoint: "tcp://192.168.10.50:9000"
          database: "jaeger_default"
          username: "default"
          password: ""

exporters:
  jaeger_storage_exporter/billing:
    trace_storage: storage_billing
  jaeger_storage_exporter/analytics:
    trace_storage: storage_analytics
  jaeger_storage_exporter/default:
    trace_storage: storage_default

service:
  extensions: [healthcheckv2, jaeger_storage]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter]
      exporters: [routing]
    traces/billing:
      receivers: [routing]
      processors: [batch]
      exporters: [jaeger_storage_exporter/billing]
    traces/analytics:
      receivers: [routing]
      processors: [batch]
      exporters: [jaeger_storage_exporter/analytics]
    traces/default:
      receivers: [routing]
      processors: [batch]
      exporters: [jaeger_storage_exporter/default]
```

Запуск сервиса:
```bash
jaeger-v2 --config /etc/jaeger/jaeger-v2-routing.yaml
# → 2026-10-12T14:38:00.104Z info service/service.go:168 Everything is ready. Begin running and processing data.
```

#### Валидация маршрутизации

1. Отправка тестового спана с заголовком тенанта `billing`:
```bash
curl -X POST http://127.0.0.1:4318/v1/traces \
  -H "Content-Type: application/json" \
  -H "x-tenant-id: billing" \
  -d '{
    "resourceSpans": [{
      "resource": {
        "attributes": [{"key": "service.name", "value": {"stringValue": "payment-api"}}]
      },
      "scopeSpans": [{
        "spans": [{
          "traceId": "5b8aa5a2d2c872e83297b31eee1416bd",
          "spanId": "eee1416bd0000001",
          "name": "ProcessPayment",
          "startTimeUnixNano": "1773489600000000000",
          "endTimeUnixNano": "1773489600500000000"
        }]
      }]
    }]
  }'
# → {"partialSuccess":{}}
```

2. Проверка, что спан записан **только** в базу `jaeger_billing`:
```bash
clickhouse-client --host=192.168.10.50 --query "SELECT count() FROM jaeger_billing.spans WHERE trace_id = '5b8aa5a2d2c872e83297b31eee1416bd'"
# → 1

clickhouse-client --host=192.168.10.50 --query "SELECT count() FROM jaeger_analytics.spans WHERE trace_id = '5b8aa5a2d2c872e83297b31eee1416bd'"
# → 0
```

---

### Сценарий 3: Логическая изоляция в единой таблице через Row-Level Security (RLS) в ClickHouse

**Ситуация:** В целях минимизации оверхеда на поддержку сотен отдельных баз данных используется единая таблица `jaeger_v2.spans`. Доступ пользователей разных команд разграничивается с помощью политик уровня строк (Row Policies / RLS). Пользователь `query_team_a` при любых SQL-запросах (включая `SELECT *`) физически видит исключительно записи, помеченные `tenant = 'team-a'`.

#### Предусловия
- ClickHouse версии 24.x или выше с включенной поддержкой SQL-driven Access Control (`<local_directory>` в `config.xml`).
- Серверная учетная запись администратора ClickHouse.

#### Пошаговое руководство

##### Шаг 1: Создание общей таблицы с колонкой тенанта

```sql
CREATE DATABASE IF NOT EXISTS jaeger_shared;

CREATE TABLE IF NOT EXISTS jaeger_shared.spans
(
    trace_id String,
    span_id String,
    operation_name String,
    start_time_ns UInt64,
    duration_ns UInt64,
    service_name String,
    tenant LowCardinality(String),
    tags Map(String, String),
    logs Array<JSON>,
    references Array<String>,
    process Array<String>,
    flags UInt32,
    PRIMARY KEY (trace_id, span_id)
)
ENGINE = MergeTree()
PARTITION BY toDate(fromUnixTimestamp64Nano(start_time_ns))
ORDER BY (tenant, service_name, operation_name, start_time_ns)
TTL toDateTime(start_time_ns / 1000000000) + INTERVAL 7 DAY
SETTINGS index_granularity = 8192;
```

##### Шаг 2: Настройка ролей, пользователей и Row Policies

```sql
-- 1. Создаем роли для команд
CREATE ROLE IF NOT EXISTS role_team_a;
CREATE ROLE IF NOT EXISTS role_team_b;

-- 2. Выдаем базовые права чтения
GRANT SELECT ON jaeger_shared.spans TO role_team_a;
GRANT SELECT ON jaeger_shared.spans TO role_team_b;

-- 3. Назначаем Row Policy (фильтрация на уровне строк ядра ClickHouse)
CREATE ROW POLICY IF NOT EXISTS rls_team_a ON jaeger_shared.spans
    FOR SELECT USING tenant = 'team-a' TO role_team_a;

CREATE ROW POLICY IF NOT EXISTS rls_team_b ON jaeger_shared.spans
    FOR SELECT USING tenant = 'team-b' TO role_team_b;

-- 4. Создаем учетные записи для Jaeger Query инстансов команд
CREATE USER IF NOT EXISTS user_query_team_a IDENTIFIED WITH sha256_password BY 'QueryPassTeamA456!';
CREATE USER IF NOT EXISTS user_query_team_b IDENTIFIED WITH sha256_password BY 'QueryPassTeamB789!';

GRANT role_team_a TO user_query_team_a;
GRANT role_team_b TO user_query_team_b;
```

Применение:
```bash
clickhouse-client --host=192.168.10.50 --multiquery < /opt/jaeger/setup_rls.sql
# → Ok.
```

##### Шаг 3: Наполнение тестовыми данными

```sql
INSERT INTO jaeger_shared.spans (trace_id, span_id, operation_name, start_time_ns, service_name, tenant) VALUES
('tr001', 'sp001', 'GET /order', 1773489600000000000, 'order-svc', 'team-a'),
('tr002', 'sp002', 'POST /auth', 1773489601000000000, 'auth-svc', 'team-b');
```

#### Валидация Row Policy

1. Выполнение запроса от имени `user_query_team_a`:
```bash
clickhouse-client --host=192.168.10.50 --user=user_query_team_a --password='QueryPassTeamA456!' \
  --query "SELECT trace_id, service_name, tenant FROM jaeger_shared.spans"
# → tr001	order-svc	team-a
```

2. Выполнение запроса от имени `user_query_team_b`:
```bash
clickhouse-client --host=192.168.10.50 --user=user_query_team_b --password='QueryPassTeamB789!' \
  --query "SELECT trace_id, service_name, tenant FROM jaeger_shared.spans"
# → tr002	auth-svc	team-b
```
Пользователь `user_query_team_a` физически не может получить доступ к строкам `team-b`, даже выполняя прямой запрос без `WHERE`.

---

### Сценарий 4: Аутентифицирующий Reverse Proxy перед Jaeger UI/Query (Nginx / Basic Auth / mTLS)

**Ситуация:** Сервис `jaeger-query` не имеет встроенного механизма авторизации пользователей. Чтобы разработчики команды `team-a` не могли зайти в UI и просматривать трейсы команды `team-b`, перед инстансами Jaeger Query разворачивается реверс-прокси Nginx, выполняющий аутентификацию и перенаправление запросов на соответствующий backend.

#### Предусловия
- Nginx 1.24+ установлен на хосте/контейнере `192.168.10.60`.
- Запущены два локальных инстанса `jaeger-query`:
  - `jaeger-query-team-a` на порту `16686`
  - `jaeger-query-team-b` на порту `16687`

#### Пошаговое руководство

##### Шаг 1: Генерация паролей пользователей

```bash
mkdir -p /etc/nginx/auth
htpasswd -bc /etc/nginx/auth/.htpasswd_teama developer_a "SecretPassTeamA!"
# → Adding password for user developer_a

htpasswd -bc /etc/nginx/auth/.htpasswd_teamb developer_b "SecretPassTeamB!"
# → Adding password for user developer_b
```

##### Шаг 2: Конфигурация виртуального хоста Nginx

```nginx
# /etc/nginx/conf.d/jaeger-multi-tenant.conf
upstream jaeger_backend_team_a {
    server 127.0.0.1:16686;
    keepalive 16;
}

upstream jaeger_backend_team_b {
    server 127.0.0.1:16687;
    keepalive 16;
}

server {
    listen 443 ssl;
    server_name tracing.internal.corp;

    ssl_certificate /etc/nginx/ssl/tracing.crt;
    ssl_certificate_key /etc/nginx/ssl/tracing.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Точка входа для Team A
    location /team-a/ {
        auth_basic "Jaeger Tracing - Team A";
        auth_basic_user_file /etc/nginx/auth/.htpasswd_teama;

        proxy_pass http://jaeger_backend_team_a/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Prefix /team-a;
    }

    # Точка входа для Team B
    location /team-b/ {
        auth_basic "Jaeger Tracing - Team B";
        auth_basic_user_file /etc/nginx/auth/.htpasswd_teamb;

        proxy_pass http://jaeger_backend_team_b/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Prefix /team-b;
    }
}
```

Проверка конфигурации и перезагрузка Nginx:
```bash
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

systemctl reload nginx
# → systemctl reload nginx completed
```

#### Валидация доступа через прокси

1. Запрос инженера Team A с правильными учетными данными:
```bash
curl -s -k -u developer_a:SecretPassTeamA! https://tracing.internal.corp/team-a/api/services
# → {"data":["order-svc","payment-api"],"total":2,"limit":0,"offset":0,"errors":null}
```

2. Попытка инженера Team A получить доступ к UI Team B:
```bash
curl -s -k -u developer_a:SecretPassTeamA! -I https://tracing.internal.corp/team-b/api/services
# → HTTP/1.1 401 Unauthorized
# → WWW-Authenticate: Basic realm="Jaeger Tracing - Team B"
```

---

### Сценарий 5: Chargeback, Showback и мониторинг потребления ресурсов тенантами (SRE/FinOps)

**Ситуация:** SRE-команде требуется ежемесячно формировать отчет об объеме дискового пространства и сетевого трафика, потребляемого каждым тенантом, а также настроить алертинг на аномальные всплески генерации спанов.

#### Предусловия
- Сервер ClickHouse с таблицами спанов тенантов (`jaeger_billing.spans`, `jaeger_analytics.spans`).
- Prometheus 2.x/3.x, собирающий метрики с коллекторов.

#### Пошаговое руководство

##### Шаг 1: Расчет дискового пространства и коэффициента компрессии в ClickHouse

Для точного расчета затрат на дисковую подсистему опрашивается системная таблица `system.parts`:

```sql
SELECT
    database,
    table,
    sum(rows) AS total_spans,
    formatReadableSize(sum(bytes_on_disk)) AS disk_size_bytes,
    formatReadableSize(sum(data_uncompressed_bytes)) AS uncompressed_size,
    round(sum(data_uncompressed_bytes) / sum(bytes_on_disk), 2) AS compression_ratio
FROM system.parts
WHERE active AND database IN ('jaeger_billing', 'jaeger_analytics')
GROUP BY database, table
ORDER BY sum(bytes_on_disk) DESC;
```

Выполнение запроса:
```bash
clickhouse-client --host=192.168.10.50 --query "SELECT database, sum(rows), formatReadableSize(sum(bytes_on_disk)), round(sum(data_uncompressed_bytes) / sum(bytes_on_disk), 2) FROM system.parts WHERE active AND database IN ('jaeger_billing', 'jaeger_analytics') GROUP BY database"
# → jaeger_billing	148500200	12.45 GiB	6.82
# → jaeger_analytics	45200100	3.88 GiB	6.45
```

##### Шаг 2: Расчет стоимости инфраструктуры в скрипте Chargeback

```bash
cat << 'EOF' > /opt/jaeger/scripts/chargeback_calculator.sh
#!/usr/bin/env bash
set -euo pipefail

# Тариф за 1 ГБ хранения в месяц (в условных единицах или рублях)
STORAGE_COST_PER_GB_MONTH=15.0

echo "=== Отчет Chargeback по хранению трассировки ==="
clickhouse-client --host=192.168.10.50 --format=TabSeparated --query "
SELECT 
    database,
    round(sum(bytes_on_disk) / (1024*1024*1024), 2) AS gb_used,
    round((sum(bytes_on_disk) / (1024*1024*1024)) * ${STORAGE_COST_PER_GB_MONTH}, 2) AS total_cost_rub
FROM system.parts
WHERE active AND database LIKE 'jaeger_%'
GROUP BY database;
" | while read -r tenant gb cost; do
    echo "Тенант: ${tenant} | Занято: ${gb} GB | Стоимость за месяц: ${cost} RUB"
done
EOF

chmod +x /opt/jaeger/scripts/chargeback_calculator.sh
/opt/jaeger/scripts/chargeback_calculator.sh
# → === Отчет Chargeback по хранению трассировки ===
# → Тенант: jaeger_billing | Занято: 12.45 GB | Стоимость за месяц: 186.75 RUB
# → Тенант: jaeger_analytics | Занято: 3.88 GB | Стоимость за месяц: 58.20 RUB
```

##### Шаг 3: Мониторинг входящего потока спанов в Prometheus (PromQL)

В Prometheus собираются метрики экспортеров и ресиверов OTel Collector:

```promql
# Скорость приема спанов в секунду по каждому тенанту
sum by (tenant) (rate(otelcol_receiver_accepted_spans[5m]))

# Количество сброшенных спанов из-за очередей или невалидного формата
sum by (tenant) (rate(otelcol_processor_dropped_spans[5m]))

# Использование памяти очередями отправки
sum by (exporter) (otelcol_exporter_queue_size)
```

##### Шаг 4: Alerting Rule при превышении квоты генерации спанов

```yaml
# /etc/prometheus/rules/jaeger_tenants.rules.yaml
groups:
  - name: jaeger_tenant_alerts
    rules:
      - alert: TenantSpanRateQuotaExceeded
        expr: sum by (tenant) (rate(otelcol_receiver_accepted_spans[5m])) > 15000
        for: 5m
        labels:
          severity: warning
          component: tracing
        annotations:
          summary: "Тенант {{ $labels.tenant }} превысил квоту трассировки"
          description: "Тенант {{ $labels.tenant }} генерирует {{ $value }} спанов/сек в течение последних 5 минут (лимит: 15000)."
```

Валидация синтаксиса правил:
```bash
promtool check rules /etc/prometheus/rules/jaeger_tenants.rules.yaml
# → Checking /etc/prometheus/rules/jaeger_tenants.rules.yaml
# →   SUCCESS: 1 rules found
```

---

## Операции и команды

Сводка регулярных команд обслуживания multi-tenant окружения:

| Задача | Команда | Ожидаемый результат / Примечание |
| :--- | :--- | :--- |
| **Проверка статуса баз тенантов** | `clickhouse-client --query "SHOW DATABASES LIKE 'jaeger_%'"` | `# → jaeger_analytics`<br>`# → jaeger_billing` |
| **Аудит дискового пространства** | `clickhouse-client --query "SELECT database, formatReadableSize(sum(bytes_on_disk)) FROM system.parts WHERE active GROUP BY database"` | Быстрый просмотр размера БД тенантов без блокировок |
| **Удаление данных тенанта (offboarding)** | `clickhouse-client --query "DROP DATABASE IF EXISTS jaeger_old_team"` | Полное удаление структуры и файлов тенанта с диска |
| **Сброс конкретной партиции (дня)** | `clickhouse-client --query "ALTER TABLE jaeger_billing.spans DROP PARTITION '2026-03-01'"` | Мгновенное удаление суточного среза данных |
| **Проверка сетевой изоляции K8s** | `kubectl get networkpolicies -n tenant-billing` | `# → NAME                       POD-SELECTOR`<br>`# → billing-tracing-isolation   app.kubernetes.io/name=...` |
| **Просмотр логов маршрутизации** | `kubectl logs -n tenant-billing -l app.kubernetes.io/name=jaeger-collector-billing --tail=50` | Проверка ошибок `routingconnector` или `storage_exporter` |
| **Проверка текущих соединений ClickHouse** | `clickhouse-client --query "SELECT user, count() FROM system.processes GROUP BY user"` | Контроль количества активных коннектов от каждого тенанта |

---

## Диагностика и устранение неполадок

### Сводная таблица типовых сбоев

| Симптом | Первопричина | Метод диагностики | Решение |
| :--- | :--- | :--- | :--- |
| **Спаны попадают в `jaeger_default`** | В запросе отсутствует заголовок `x-tenant-id` или атрибут `tenant.id` | Проверка метрик: `sum(rate(otelcol_exporter_sent_spans{exporter="jaeger_storage_exporter/default"}[5m]))` | Настроить OTel SDK в сервисах приложения для обязательной передачи атрибута ресурса `tenant.id` |
| **`failed to get trace storage: backend not found`** | Имя бэкенда в `exporters.jaeger_storage_exporter.trace_storage` не объявлено в `extensions.jaeger_storage.backends` | Поиск ошибки в логах коллектора при старте:<br>`journalctl -u jaeger -n 50 \| grep "trace storage"` | Синхронизировать идентификаторы бэкендов в секциях `backends:` и `trace_storage:` |
| **ClickHouse: `DB::Exception: Access denied`** | Учетная запись Jaeger Query не имеет прав `SELECT` на таблицу тенанта или нарушает Row Policy | Логи ClickHouse `/var/log/clickhouse-server/clickhouse-server.err.log` | Проверить `SHOW GRANTS FOR <user>` и назначить требуемые права на чтение |
| **`Connection timed out` на порту 4317** | NetworkPolicy блокирует OTLP-трафик из неймспейса приложения в неймспейс коллектора | Тест подключения через `kubectl run curl ...` | Добавить `podSelector` или `namespaceSelector` в секцию `ingress` сетевой политики |
| **Jaeger Collector уходит в OOMKilled** | Всплеск спанов одного тенанта исчерпал память коллектора (Noisy neighbor) | `kubectl describe pod <collector-pod> \| grep -i oom` | Настроить `memory_limiter` процессор и выставить жесткие `ResourceQuota` / `limits.memory` |
| **Трассировка обрывается между тенантами** | Контекст W3C TraceContext (`traceparent`) не передается при межсервисных сетевых вызовах | Поиск спанов с одинаковым TraceID в обеих базах | Проверить конфигурацию OTel Context Propagation (W3C) на межсервисных HTTP/gRPC клиентах |

### Диагностический рабочий процесс: Расследование сбоя маршрутизации

```
[Спаны тенанта не появляются в UI]
                │
                ▼
1. Проверка сетевого уровня: доходят ли спаны до коллектора?
   `kubectl logs -l app=jaeger-collector --tail=100 | grep -i "otlp"`
   ├── Нет ──▶ Проверить NetworkPolicy, DNS и Service endpoints (:4317/:4318)
   └── Да  ──▶ Переход к шагу 2
                │
                ▼
2. Проверка заголовков и атрибутов: содержит ли спан tenant-маркер?
   Включить debug-экспортер: `exporters: [debug: {verbosity: detailed}]`
   ├── Нет ──▶ Исправить конфигурацию приложения (OTEL_RESOURCE_ATTRIBUTES="tenant.id=billing")
   └── Да  ──▶ Переход к шагу 3
                │
                ▼
3. Проверка Routing Connector: срабатывает ли условие таблицы?
   Проверить метрики `otelcol_connector_routing_matched_spans`
   ├── Ошибка синтаксиса ──▶ Исправить выражение `statement: route() where ...`
   └── Успешно            ──▶ Переход к шагу 4
                │
                ▼
4. Проверка хранилища: принимает ли ClickHouse данные?
   `clickhouse-client --query "SELECT count() FROM jaeger_<tenant>.spans"`
   ├── 0 строк ──▶ Проверить права пользователя ClickHouse и сетевой доступ к порту 9000
   └── Данные есть ──▶ Проверить настройки подключения инстанса Jaeger Query
```

---

## Лучшие практики

1. **Изолируйте критичные контуры на уровне баз данных:** Для сред с жесткими требованиями безопасности (PCI-DSS, персональные данные) применяйте раздельные базы данных ClickHouse (`jaeger_<tenant>`) с уникальными пользователями и паролями.
2. **Всегда настраивайте `memory_limiter`:** В multi-tenant коллекторах процессор `memory_limiter` является первой линией защиты от сбоя всего кластера при аномальном поведении одного тенанта.
3. **Используйте `LowCardinality` для тенантных колонок:** Если используется общая таблица ClickHouse с RLS, колонка `tenant` обязательно должна иметь тип `LowCardinality(String)` для ускорения фильтрации и минимизации размера индекса.
4. **Контролируйте размер очередей отправки:** В `jaeger_storage_exporter` ограничивайте параметры `queue_size` (например, 2000–5000), чтобы не буферизировать чрезмерные объемы данных в RAM при сбоях БД.
5. **Разделяйте retention-периоды:** Для тестовых сред (dev/stage) задавайте TTL в 2–3 дня, а для production — 14–30 дней, экономя дисковые массивы.
6. **Автоматизируйте учет затрат:** Внедрите регулярный сбор метрик дискового использования из ClickHouse `system.parts` для формирования прозрачной отчетности руководству и продуктовым командам.

---

## Очистка окружения

Команды удаления созданных тестовых ресурсов:

```bash
# 1. Удаление ресурсов Kubernetes
kubectl delete namespace tenant-billing --timeout=60s
# → namespace "tenant-billing" deleted

# 2. Удаление тестовых баз данных в ClickHouse
clickhouse-client --host=192.168.10.50 --multiquery << 'EOF'
DROP DATABASE IF EXISTS jaeger_billing;
DROP DATABASE IF EXISTS jaeger_analytics;
DROP DATABASE IF EXISTS jaeger_default;
DROP DATABASE IF EXISTS jaeger_shared;
DROP USER IF EXISTS user_billing;
DROP USER IF EXISTS user_analytics;
DROP USER IF EXISTS user_query_team_a;
DROP USER IF EXISTS user_query_team_b;
DROP ROLE IF EXISTS role_team_a;
DROP ROLE IF EXISTS role_team_b;
EOF
# → Ok.

# 3. Остановка локального процесса Nginx / Jaeger
systemctl stop nginx || true
pkill -f jaeger-v2 || true
```

---

## Дополнительная информация

**Смежные материалы базы знаний:**
* Архитектурные принципы Jaeger v2: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Развертывание и контроллеры в K8s: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**
* Устройство и оптимизация ClickHouse для трейсов: **[Storage Deep Dive для Jaeger](./jaeger_storage_deep_dive.md)**
* Защита инфраструктуры и mTLS: **[Security Hardening для Jaeger](./jaeger_security_hardening.md)**
* Расчет ресурсов и объемов данных: **[Capacity Planning для Jaeger](./jaeger_capacity_planning.md)**
* Управление доступом в Kubernetes: **[Обзор управления доступом на основе ролей (RBAC)](../Kubernetes/Security/rbac/rbac_overview.md)**
* Управление доступом и RLS в ClickHouse: **[ClickHouse — Безопасность и управление доступом](../Databases/ClickHouse/clickhouse-security.md)**

### См. также
* [Официальная документация Jaeger v2](https://www.jaegertracing.io/docs/latest/)
* [OpenTelemetry Collector Routing Connector](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/connector/routingconnector)
* [ClickHouse Row-Level Security Documentation](https://clickhouse.com/docs/en/sql-reference/statements/create/row-policy)
