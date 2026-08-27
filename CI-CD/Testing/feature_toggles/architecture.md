# Архитектура систем Feature Toggles

## Определения

**Архитектура Feature Toggles** — это комплексная инфраструктурная экосистема, обеспечивающая централизованное управление, безопасную доставку и высокопроизводительное вычисление состояний флагов функций в рантайме. Современная архитектура (2026+) ориентирована на минимизацию сетевых задержек, защиту персональных данных (PII) и полную интеграцию с процессами прогрессивной поставки (Progressive Delivery).

---

## Предварительные требования

### Инструментарий

| Компонент | Назначение | Минимальная версия |
| :--- | :--- | :--- |
| **FFaaS платформа** | Хранение и управление флагами (Unleash, Flipt, Flagsmith) | Unleash v5+ / Flipt v1.35+ |
| **OpenFeature SDK** | Унифицированный API для проверки флагов в коде | v0.4+ (Python/Go/Java/Node) |
| **flagd** | Локальный демон оценки флагов (OpenFeature) | v0.8+ |
| **OpenTelemetry Collector** | Сбор и передача телеметрии по состоянию флагов | v0.95+ |
| **Prometheus + Grafana** | Мониторинг использования флагов и их влияния на метрики | Prometheus v2.50+, Grafana v10+ |
| **Redis** | Кеш состояний флагов для Relay/Proxy | Redis v7+ |
| **PostgreSQL** | Хранилище конфигурации флагов (Unleash/Flipt) | PostgreSQL v15+ |
| **Kubernetes** (опционально) | Оркестрация Relay/Proxy и flagd sidecar | v1.28+ |

### Локальное окружение для тестирования

```bash
# Развертывание полного стека: FFaaS + Redis + PostgreSQL
git clone https://github.com/Unleash/unleash-docker.git
cd unleash-docker
docker compose up -d
# → Unleash: http://localhost:4242 (admin/unleash4all)
# → Redis: localhost:6379
# → PostgreSQL: localhost:5432

# Проверка доступности
curl -s http://localhost:4242/api/admin/user | jq '.user.permissions'
# → ["admin"]
```

### Базовые знания

Перед изучением архитектуры рекомендуется ознакомиться с:
- Общими принципами Feature Toggles ([Обзор](./overview.md))
- Классификацией флагов по типам ([Типы](./types.md))
- Паттернами программирования ([Реализация в коде](./implementation.md))

---

## Основные концепции

### Многоуровневая архитектура (2026+)

Современные системы управления флагами разделяются на независимые плоскости управления и исполнения, аналогично архитектуре Service Mesh.

```text
┌────────────────────────────────┐      ┌────────────────────────────────┐
│      ПЛОСКОСТЬ УПРАВЛЕНИЯ      │      │       СЛОЙ ХРАНЕНИЯ            │
│        (Control Plane)         │      │       (Storage Layer)          │
│ ┌────────────────────────────┐ │      │ ┌────────────────────────────┐ │
│ │  Admin UI / API / RBAC     │ │      │ │  PostgreSQL / Redis / S3   │ │
│ └──────────────┬─────────────┘ │      │ └──────────────┬─────────────┘ │
└────────────────┼───────────────┘      └────────────────┼───────────────┘
                 │                                       │
                 ▼                                       ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   ЦЕНТРАЛЬНЫЙ СЕРВЕР ВЫЧИСЛЕНИЙ (API)                  │
│   (Targeting Engine, Segment Manager, Audit Service, Event Stream)     │
└────────────────────────────────┬───────────────────────────────────────┘
                                 │
         ┌───────────────────────┴───────────────────────┐
         │                                               │
         ▼                                               ▼
┌──────────────────┐                           ┌──────────────────┐
│  RELAY / PROXY   │                           │  EDGE WORKERS    │
│ (Local caching,  │                           │ (WASM, Cloudflare│
│  PII Stripping)  │                           │  Logic at Edge)  │
└────────┬─────────┘                           └────────┬─────────┘
         │                                              │
         └───────────────────────┬──────────────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      УРОВЕНЬ ИСПОЛНЕНИЯ (SDK)                          │
│   ┌─────────────┐       ┌──────────────┐       ┌─────────────┐         │
│   │ OpenFeature │ ◄──── │  Evaluation  │ ◄──── │  App Logic  │         │
│   │   Wrapper   │       │    Engine    │       │  (Wrapped)  │         │
│   └─────────────┘       └──────────────┘       └─────────────┘         │
└────────────────────────────────────────────────────────────────────────┘
```

### Ключевые компоненты и их функции

1.  **SDK (Evaluation Engine)**:
    *   **Evaluation (Вычисление)**: В 2026 году стандартом является **OpenFeature SDK**. Вычисление логики (таргетинг) происходит внутри процесса приложения, что дает `O(1)` производительность без внешних вызовов.
    *   **Synchronization**: SDK поддерживает постоянное соединение (gRPC/SSE) с Relay/API для получения диффов (изменений) правил.
2.  **Relay / Proxy Layer**:
    *   **Privacy Guard**: Слой проксирования удаляет или хеширует PII (Personally Identifiable Information) до того, как контекст пользователя попадет в облако внешнего вендора (Unleash/LaunchDarkly).
    *   **Connection Offloading**: Прокси держит одно соединение с сервером, обслуживая тысячи инстансов приложения, снижая нагрузку на Control Plane.
3.  **Edge / Global Layer**:
    *   Использование **WASM** на CDN-узлах позволяет выполнять сложные правила сегментации максимально близко к пользователю, минимизируя "мерцание" (flicker) интерфейса на фронтенде.

---

### Ключевой компонент: flagd (OpenFeature Daemon)

**flagd** — демон оценки флагов от OpenFeature, который вычисляет значение флага по правилам таргетинга и отдает результат по gRPC/HTTP. Локальный flagd рядом с приложением обеспечивает оценку без сетевого вызова во внешнюю систему.

```text
┌─────────────────────────────────────────────────────┐
│                     Pod (Kubernetes)                 │
│                                                     │
│  ┌──────────────────┐    ┌──────────────────────┐   │
│  │   App Container  │    │  flagd Sidecar       │   │
│  │                  │    │                      │   │
│  │  OpenFeature     │───▶│  gRPC :8013          │   │
│  │  SDK             │    │  Evaluation Engine   │   │
│  │                  │◀───│  Rules Cache         │   │
│  └──────────────────┘    └──────────┬───────────┘   │
│                                     │               │
└─────────────────────────────────────┼───────────────┘
                                      │
                          ┌───────────▼───────────┐
                          │  ConfigMap / HTTP API  │
                          │  (источник правил)     │
                          └───────────────────────┘
```

**Режимы работы flagd:**

| Режим | Описание | Протокол | Применимость |
| :--- | :--- | :--- | :--- |
| **Sidecar** | flagd запущен в каждом Pod как sidecar-контейнер | gRPC/HTTP `localhost:8013` | Kubernetes, максимальная изоляция |
| **Centralized** | Один инстанс flagd обслуживает несколько подов | gRPC/HTTP через Service | Малые кластеры, dev-окружения |
| **Kubernetes Operator** | open-feature-operator управляет жизненным циклом flagd | CRD (`FlagSourceConfiguration`) | GitOps, декларативное управление |

**Пример FlagSourceConfiguration (Kubernetes):**
```yaml
apiVersion: core.openfeature.dev/v1alpha1
kind: FlagSourceConfiguration
metadata:
  name: checkout-flagsource
  namespace: billing
spec:
  sources:
    - source: billing/checkout-flags       # namespace/name ConfigMap
      type: kubernetes
    - source: http://flags.internal/flags.json
      type: http
      interval: 10s                        # Интервал обновления правил
  defaultSyncProvider: kubernetes
  port: 8013                               # gRPC-порт flagd
  logLevel: info
  metricsPort: 8014                        # Метрики flagd для Prometheus
```

---

### Методы вычисления флагов (Evaluation Strategies)

| Метод | Описание | Применимость | Риски |
| :--- | :--- | :--- | :--- |
| **Local Evaluation** | SDK скачивает набор правил (Ruleset) и вычисляет результат в памяти процесса. | Бэкенд-сервисы, высоконагруженные API. | Утечка правил сегментации (код видит всю логику). |
| **Remote Evaluation** | SDK отправляет контекст (user_id, attributes) на сервер и получает только результат (true/false). | Клиентские приложения (JS, Mobile). | Сетевой latency, риск отказа API. |
| **Hybrid Evaluation** | Публичные правила вычисляются локально, чувствительные — удаленно через Relay. | Корпоративные системы с высокими требованиями безопасности. | Усложнение конфигурации SDK. |

### Протоколы синхронизации SDK с сервером флагов

SDK поддерживает три основных протокола получения обновлений. Выбор зависит от архитектуры и требований к задержке.

| Протокол | Механизм | Задержка обновления | Нагрузка на сеть | Применимость |
| :--- | :--- | :--- | :--- | :--- |
| **Polling** | HTTP GET с интервалом (`/api/client/features`) | Интервал polling (30-60с) | Высокая (много запросов) | Простые deployments, dev-окружения |
| **SSE (Server-Sent Events)** |ersistent HTTP-соединение, сервер отправляет события | Мгновенно (<1с) | Низкая (одно соединение) | Production, рекомендуемый |
| **gRPC Streaming** | Bidirectional streaming через gRPC | Мгновенно (<1с) | Минимальная | Высоконагруженные системы |

**Конфигурация SSE в Unleash SDK (Python):**
```python
from openfeature import api
from openfeature.contrib.provider.unleash import UnleashProvider

api.set_provider(UnleashProvider(
    url="https://ff-api.internal/api",
    app_name="checkout-service",
    # SSE streaming: обновления приходят по событию
    enable_sse=True,
    # Fallback на polling если SSE недоступен
    polling_interval=60,           # 60 секунд
    # Локальный кеш: оценка без сетевого вызова
    enable_local_cache=True,
    cache_ttl=300                  # 5 минут
))
```

**Конфигурация gRPC-синхронизации (Go):**
```go
// flagd sidecar: оценка через gRPC на localhost
provider, err := flagd.NewProvider(
    flagd.WithInProcessResolver("checkout-service", "localhost:8013"),
    flagd.WithLogger(logger),
)
if err != nil {
    log.Fatalf("Failed to create flagd provider: %v", err)
}
openfeature.SetProvider(provider)
```

---

### Стратегии кеширования в SDK

| Стратегия | Описание | TTL | Использование памяти | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **In-Memory Cache** | Хранение Ruleset в памяти процесса | Зависит от протокола синхронизации | Низкая (<1MB) | По умолчанию для всех SDK |
| **Persistent Cache** | Запись Ruleset на диск (SQLite/JSON) | До перезапуска приложения | Средняя | Mobile/offline-приложения |
| **Bootstrap File** | Локальный JSON-файл с последними известными состояниями | До первого успешного обновления | Низкая | Fail-safe при недоступности сервера |
| **Redis Cache** | Распределенный кеш через Redis | Настроенный TTL | Средняя | Relay/Proxy, кластерные deployments |

**Настройка Bootstrap File:**
```python
api.set_provider(UnleashProvider(
    url="https://ff-api.internal/api",
    app_name="checkout-service",
    # Bootstrap: локальный файл с последними известными флагами
    bootstrap="/etc/feature-flags/bootstrap.json",
    bootstrap_override=False  # True = bootstrap перезаписывает Ruleset
))
```

**Формат bootstrap.json:**
```json
{
  "features": [
    {
      "name": "new-checkout",
      "enabled": true,
      "variant": "variant-a"
    },
    {
      "name": "legacy-recommendations",
      "enabled": false,
      "variant": null
    }
  ]
}
```

---

## Безопасность и отказоустойчивость

### Защита плоскости управления

*   **RBAC & OIDC**: Доступ к переключению флагов в Production должен быть защищен через корпоративный IdP (Okta/Keycloak) с обязательным MFA.
*   **Four-eyes principle**: Критические флаги (Kill Switches, Security Toggles) требуют аппрува от второго инженера или SRE.
*   **Audit Trail**: Каждое изменение флага должно сопровождаться записью в неизменяемом логе (кто, когда, зачем, значение `old` vs `new`).

**Настройка RBAC в Unleash:**
```bash
# Создание роли "Release Manager" с правами только на release-флаги
curl -s -X POST "$UNLEASH_URL/api/admin/roles" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Release Manager",
    "description": "Управление release-флагами в Production",
    "type": "custom",
    "permissions": [
      {
        "name": "UPDATE_FEATURE",
        "environment": "production",
        "project": "default"
      }
    ]
  }'

# Назначение роли пользователю
curl -s -X POST "$UNLEASH_URL/api/admin/projects/default/members" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "users": [{"id": 1, "roleId": 3}]
  }'
```

**Настройка Audit Trail (включение аудита):**
```bash
# Unleash: включение аудита изменений флагов
curl -s -X PUT "$UNLEASH_URL/api/admin/projects/default/settings" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "open",
    "changeRequestEnvironmentConfigs": [
      {
        "environment": "production",
        "requiredApprovals": 2,
        "requiresApproval": true
      }
    ]
  }'
```

**Экспорт аудита в Loki (webhook):**
```bash
# Unleash: настройка webhook для экспорта аудита
curl -s -X POST "$UNLEASH_URL/api/admin/projects/default/integrations" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "webhook",
    "provider": "custom",
    "description": "Audit export to Loki",
    "url": "http://loki.internal:3100/loki/api/v1/push",
    "events": ["feature-flag-updated", "feature-flag-created", "feature-flag-deleted"],
    "template": {
      "url": "http://loki.internal:3100/loki/api/v1/push",
      "body": "{\"streams\":[{\"stream\":{\"source\":\"unleash\",\"flag\":\"{{event.data.name}}\"},\"values\":[[\"{{event.createdAt}}\",\"{{event.type}} user={{event.createdBy}} old={{event.data.oldEnabled}} new={{event.data.newEnabled}}\"]]}]}"
    }
  }'
```

### Стратегии Fail-safe

Архитектура должна гарантировать работу приложения при полной недоступности системы флагов:

1.  **Bootstrap File**: При старте SDK может читать локальный JSON-файл с последними известными состояниями флагов.
2.  **Hardcoded Defaults**: Каждая проверка в коде обязана содержать fallback-значение.
3.  **Graceful Degradation**: При сбое FFaaS система переходит в режим "все новые фичи выключены, стабильное ядро работает".

**Реализация Fail-safe в коде:**
```python
from openfeature import api
from openfeature.contrib.provider.unleash import UnleashProvider
import logging

def init_feature_flags():
    """Инициализация с fail-safe fallback."""
    try:
        api.set_provider(UnleashProvider(
            url="https://ff-api.internal/api",
            app_name="checkout-service",
            bootstrap="/etc/feature-flags/bootstrap.json",
            connect_timeout=5,    # Таймаут подключения: 5 секунд
            read_timeout=3,       # Таймаут чтения: 3 секунды
        ))
        logging.info("Feature flags provider initialized successfully")
    except Exception as e:
        logging.warning(f"Failed to init feature flags provider: {e}")
        logging.warning("Using hardcoded defaults - all new features disabled")
        # SDK автоматически использует дефолтные значения при невозможности подключения
```

**Смок-тест Fail-safe:**
```bash
#!/bin/bash
# Проверка работы приложения при недоступности FFaaS
docker compose stop unleash  # Останавливаем сервер флагов
sleep 5

# Запрос к приложению — должно работать с fallback-значениями
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/checkout)
if [ "$HTTP_CODE" = "200" ]; then
    echo "PASS: Application works without FFaaS"
else
    echo "FAIL: Application returned $HTTP_CODE without FFaaS"
    exit 1
fi

docker compose start unleash  # Восстанавливаем сервер флагов
```

---

## Наблюдаемость и обратная связь (Observability)

Архитектура 2026 года неразрывно связана с **OpenTelemetry (OTel)**:

1.  **Evaluation Events**: SDK генерирует событие при каждой проверке флага. Это позволяет строить дашборды "Процент пользователей с фичей X".
2.  **Span Attributes**: Состояние флагов инжектируется в атрибуты спанов OTel. При анализе медленного запроса в Jaeger/Tempo видно, был ли в этот момент активен новый экспериментальный поисковый движок.
3.  **Metric-Driven Rollback**: Автоматизация (например, Argo Rollouts или кастомный контроллер) отслеживает Error Rate. Если флаг `feature-x` включен на 10% и ошибки выросли, автоматика через API Control Plane выключает флаг.

### Интеграция с OpenTelemetry

**Инъекция состояния флагов в спаны:**
```python
from openfeature import api
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

def process_checkout(user_id: str, cart_total: float):
    client = api.get_client()
    context = {"user_id": user_id, "cart_total": cart_total}

    with tracer.start_as_current_span("checkout_process") as span:
        is_modern_v3 = client.get_boolean_value("checkout-v3-enabled", False, context)

        # Инъекция состояния флага в спан
        span.set_attribute("feature_flag.checkout_v3", is_modern_v3)
        span.set_attribute("feature_flag.evaluation_time_ns", 
                          trace.get_current_span().get_span_context().trace_id)

        if is_modern_v3:
            return run_modern_workflow(user_id)
        return run_legacy_workflow(user_id)
```

### Настройка Prometheus для мониторинга флагов

**Метрики, предоставляемые OpenFeature SDK:**
```yaml
# Основные метрики OpenFeature SDK (автоматически экспортруются)
feature_flag_evaluations_total{flag="checkout-v3",value="true"}     # Счетчик оценок
feature_flag_evaluations_total{flag="checkout-v3",value="false"}
feature_flag_evaluation_duration_seconds_bucket{flag="checkout-v3"}  # Латентность оценки
feature_flag_evaluation_errors_total{flag="checkout-v3"}            # Ошибки оценки
```

**Правила алертинга:**
```yaml
# prometheus/rules/feature-flags.yml
groups:
  - name: feature-flags
    rules:
      # Высокая частота ошибок оценки флагов
      - alert: HighFlagEvaluationErrors
        expr: rate(feature_flag_evaluation_errors_total[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокая частота ошибок оценки флагов"
          description: "Флаг {{ $labels.flag }}: {{ $value }} ошибок/сек"

      # Медленная оценка флагов
      - alert: SlowFlagEvaluation
        expr: histogram_quantile(0.99, rate(feature_flag_evaluation_duration_seconds_bucket[5m])) > 0.01
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Медленная оценка флагов"
          description: "p99 латентность оценки {{ $labels.flag }}: {{ $value }}с"

      # Автоматическое отключение флага при высоком Error Rate
      - alert: FlagCausingErrors
        expr: |
          rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Флаг вызывает ошибки"
          description: "Error rate >5% — требуется проверка активных флагов"
          runbook_url: "https://wiki.internal/runbooks/flag-rollback"
```

### Метрика-управляемый откат (Metric-Driven Rollback)

**Реализация через Argo Rollouts + Alertmanager:**
```yaml
# Argo Rollouts: автоматический откат при превышении порога ошибок
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: checkout-service
spec:
  strategy:
    canary:
      steps:
        - setWeight: 10
        - pause: {duration: 5m}
        - setWeight: 50
        - pause: {duration: 10m}
        - setWeight: 100
      analysis:
        templates:
          - templateName: flag-health-check
        args:
          - name: flag-name
            value: checkout-v3-enabled
---
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: flag-health-check
spec:
  args:
    - name: flag-name
  metrics:
    - name: flag-error-rate
      interval: 1m
      count: 5
      successCondition: result[0] < 0.05
      provider:
        prometheus:
          address: http://prometheus.internal:9090
          query: |
            sum(rate(http_requests_total{service="checkout",status=~"5.."}[1m])) /
            sum(rate(http_requests_total{service="checkout"}[1m]))
```

**Автоматическое отключение через Alertmanager webhook:**
```yaml
# alertmanager.yml: webhook для автоматического отключения флага
receivers:
  - name: flag-rollback
    webhook_configs:
      - url: 'http://unleash-api.internal:4242/api/admin/projects/default/features/checkout-v3-enabled/environments/production/off'
        send_resolved: false
        http_config:
          authorization:
            type: Bearer
            credentials: $UNLEASH_ADMIN_TOKEN

route:
  routes:
    - match:
        alertname: FlagCausingErrors
      receiver: flag-rollback
```

---

## Bootstrap File: реализация и сценарии использования

Bootstrap File — это локальный JSON-файл, содержащий последнее известное состояние флагов. SDK читает его при старте до установления соединения с сервером флагов.

### Когда использовать Bootstrap

| Сценарий | Описание | Рекомендация |
| :--- | :--- | :--- |
| **Cold Start** | Приложение стартует, сервер флагов еще не доступен | Bootstrap обязателен |
| **Offline Mode** | Mobile/edge-приложения без сетевого доступа | Bootstrap + persistent cache |
| **Disaster Recovery** | Сервер флагов полностью недоступен | Bootstrap как последний рубеж обороны |
| **Development** | Локальная разработка без доступа к общей FFaaS | Bootstrap с dev-конфигурацией |

### Генерация Bootstrap файла (CI/CD)

```bash
#!/bin/bash
# Генерация bootstrap.json из текущего состояния FFaaS (часть CI-пайплайна)
FEATURES=$(curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" | \
  jq '[.features[] | select(.stages[]?.name == "production") | {
    name: .name,
    enabled: .stages[]?.enabled,
    variant: .variants[0].name
  }]')

echo "$FEATURES" | jq '.' > /etc/feature-flags/bootstrap.json
# → Файл используется SDK при старте приложения
```

### Порядок приоритетов при вычислении флага

```text
1. Hardcoded default (в коде приложения)
         ▼
2. Bootstrap File (локальный JSON)
         ▼
3. In-Memory Cache (Ruleset из памяти)
         ▼
4. Remote Server (FFaaS API / flagd gRPC)
```

При недоступности сервера флагов SDK последовательно спускается по этому списку, garantируя что всегда есть значение для возврата.

---

## Архитектура Relay/Proxy: детали реализации

### Relay vs Proxy: различия

| Характеристика | Relay (LaunchDarkly) | Proxy (собственная реализация) |
| :--- | :--- | :--- |
| **Роль** | Промежуточный кеш между SDK и Control Plane | Полноценный evaluation engine |
| **Вычисление** | Не вычисляет — только кеширует Ruleset | Вычисляет результат локально |
| **Протокол** | SSE/HTTP streaming от Control Plane | gRPC/HTTP от SDK |
| **PII Stripping** | Да, на уровне Proxy | Опционально |
| **Нагрузка на Control Plane** | Снижает (1 соединение на кластер) | Снижает (нет прямых соединений SDK) |

### Развертывание Proxy (Flagd в Kubernetes)

```yaml
# Deployment flagd как centralized proxy для dev-окружения
apiVersion: apps/v1
kind: Deployment
metadata:
  name: flagd-proxy
  namespace: feature-flags
spec:
  replicas: 2
  selector:
    matchLabels:
      app: flagd-proxy
  template:
    metadata:
      labels:
        app: flagd-proxy
    spec:
      containers:
        - name: flagd
          image: ghcr.io/open-feature/flagd:latest
          args:
            - start
            - --config
            - /etc/flagd/config.yaml
          ports:
            - containerPort: 8013    # gRPC
            - containerPort: 8014    # HTTP
            - containerPort: 8015    # Metrics
          volumeMounts:
            - name: config
              mountPath: /etc/flagd
          readinessProbe:
            grpc:
              port: 8013
            initialDelaySeconds: 5
          livenessProbe:
            grpc:
              port: 8013
            initialDelaySeconds: 10
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 256Mi
      volumes:
        - name: config
          configMap:
            name: flagd-config
---
# Service для доступа к flagd из других неймспейсов
apiVersion: v1
kind: Service
metadata:
  name: flagd-proxy
  namespace: feature-flags
spec:
  selector:
    app: flagd-proxy
  ports:
    - name: grpc
      port: 8013
      targetPort: 8013
    - name: http
      port: 8014
      targetPort: 8014
    - name: metrics
      port: 8015
      targetPort: 8015
```

### PII Stripping в Proxy

```python
# Пример Proxy, который удаляет PII перед отправкой в FFaaS
import hashlib
from fastapi import FastAPI, Request

app = FastAPI()

PII_FIELDS = ["email", "phone", "ip_address", "full_name"]

def strip_pii(context: dict) -> dict:
    """Удаление или хеширование PII из контекста пользователя."""
    cleaned = {}
    for key, value in context.items():
        if key in PII_FIELDS:
            # Хеширование PII вместо удаления (сохраняет консистентность)
            cleaned[key] = hashlib.sha256(str(value).encode()).hexdigest()[:16]
        else:
            cleaned[key] = value
    return cleaned

@app.post("/api/flags/evaluate")
async def evaluate_flag(request: Request):
    body = await request.json()
    cleaned_context = strip_pii(body.get("context", {}))
    # Отправка очищенного контекста в FFaaS
    result = await evaluate_in_ffaaS(body["flag_name"], cleaned_context)
    return {"value": result}
```

---

## Архитектура Edge Workers (WASM)

WASM-модули на CDN-узлах позволяют выполнять логику оценки флагов максимально близко к пользователю, минимизируя задержки и "мерцание" интерфейса.

### Принцип работы

```text
Пользователь → CDN-узел (Cloudflare/Fastly)
                      │
                      ▼
              WASM Module (Feature Flag Evaluation)
                      │
                      ▼
              Правила флагов (KV Storage / durable objects)
                      │
                      ▼
              HTML/JS с 적용ленными флагами
```

### Пример WASM-модуля для оценки флагов

```rust
// Простой WASM-модуль для оценки percentage-based флагов
use wasm_bindgen::prelude::*;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Deserialize)]
struct FlagConfig {
    enabled: bool,
    percentage: u32,
    variants: HashMap<String, String>,
}

#[derive(Serialize)]
struct EvaluationResult {
    value: bool,
    variant: Option<String>,
}

#[wasm_bindgen]
pub fn evaluate_flag(config_json: &str, user_id: &str) -> String {
    let config: FlagConfig = serde_json::from_str(config_json).unwrap();
    
    if !config.enabled {
        return serde_json::to_string(&EvaluationResult {
            value: false,
            variant: None,
        }).unwrap();
    }
    
    // Детерминированное хеширование user_id для percentage-based распределения
    let hash = simple_hash(user_id);
    let bucket = hash % 100;
    
    let enabled = bucket < config.percentage;
    let variant = if enabled {
        Some("enabled".to_string())
    } else {
        Some("disabled".to_string())
    };
    
    serde_json::to_string(&EvaluationResult {
        value: enabled,
        variant,
    }).unwrap()
}

fn simple_hash(input: &str) -> u32 {
    let mut hash: u32 = 5381;
    for byte in input.bytes() {
        hash = hash.wrapping_mul(33).wrapping_add(byte as u32);
    }
    hash
}
```

### Интеграция WASM с CDN

```javascript
// Cloudflare Worker: использование WASM для оценки флагов
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const userId = getCookie(request, 'user_id') || 'anonymous';
    
    // Загрузка WASM-модуля
    const wasmModule = await env.FF_WASM;
    
    // Получение конфигурации флагов из KV Storage
    const flagsConfig = await env.FLAGS_KV.get('flags', { type: 'json' });
    
    // Оценка флагов через WASM
    const results = {};
    for (const [flagName, config] of Object.entries(flagsConfig)) {
      const result = wasmModule.evaluate_flag(
        JSON.stringify(config), 
        userId
      );
      results[flagName] = JSON.parse(result);
    }
    
    // Вставка результатов в HTML
    const response = await fetch('https://origin.example.com/index.html');
    let html = await response.text();
    html = html.replace('<!-- FEATURE_FLAGS -->', 
      `<script>window.__FEATURE_FLAGS__ = ${JSON.stringify(results)};</script>`);
    
    return new Response(html, {
      headers: { 'Content-Type': 'text/html' }
    });
  }
};
```

---

## Типичные ошибки и диагностика (Troubleshooting)

| Симптом | Вероятная причина | Диагностические действия | Решение |
| :--- | :--- | :--- | :--- |
| SDK не подключается к FFaaS | Сетевой firewall, неверный URL | `telnet ff-api.internal 4242` → проверить доступность; `curl -v $UNLEASH_URL/api/client/features` → проверить HTTP-ответ | Убедиться, что порт 4242 открыт между подом приложения и FFaaS; проверить DNS-резолв |
| Оценка флага возвращает дефолт | SDK не получил Ruleset, bootstrap отсутствует | `docker logs flagd-proxy` → проверить sync; проверить наличие bootstrap.json | Убедиться, что bootstrap файл доступен в контейнере; проверить права доступа к файлу |
| Флаг не обновляется в Runtime | SDK кеширует старый Ruleset | `tcpdump -i any port 8013` → проверить SSE/gRPC-соединение; проверить `cache_ttl` | Увеличить частоту polling или переключиться на SSE; проверить Health Check flagd |
| Высокий latency оценки флагов | Remote evaluation вместо local | `curl -w "@curl-format.txt" -o /dev/null -s $UNLEASH_URL/api/client/features` → замерить latency | Переключиться на local evaluation (SSE + in-memory cache); добавить flagd sidecar |
| Флаги различаются между средами | Ручное управление без GitOps | `diff <(curl -s prod-flags) <(curl -s staging-flags)` → найти расхождения | Декларативное управление через GitOps; diff флагов — часть ревью PR |
| Bootstrap не работает | Неверный формат JSON, отсутствие файла | `python -m json.tool /etc/feature-flags/bootstrap.json` → проверить формат; `ls -la /etc/feature-flags/` → проверить наличие | Использовать валидный JSON; убедиться, что volume mount корректен |
| flagd sidecar не стартует | Неверный образ, проблемы с health check | `kubectl describe pod <pod-name>` → проверить Events; `kubectl logs <pod-name> -c flagd` → проверить логи | Проверить версию образа; убедиться, что port 8013 доступен; проверить readinessProbe |
| PII утекает в FFaaS | Proxy не настроен на strip PII | `curl $UNLEASH_URL/api/admin/projects/default/features/flag-name` → проверить context в логах | Настроить PII Stripping в Proxy; использовать hashing вместо raw значений |

---

## Ограничения и особые случаи (Edge Cases)

### Когда Feature Toggles НЕ подходят

- **Простые CRUD-приложения** без альтернативных веток логики — Overhead от инфраструктуры флагов не окупается.
- **Критические пути с нулевой толерантностью к latency** — каждая проверка флага добавляет вычисления (хотя и `O(1)` при локальном вычислении). В high-frequency trading или real-time bidding этот overhead может быть неприемлем.
- **Замена системы авторизации** — флаги не предназначены для обеспечения безопасности. Злоумышленник может подменить контекст на клиенте.

### Архитектурные ограничения

- **Комбинаторный взрыв:** 10 независимых бинарных флагов дают 1024 состояния системы. Необходимо ограничивать количество одновременно активных релизных флагов на сервис (типично: 5-10).
- **Глобальные побочные эффекты:** Если два флага влияют на один глобальный ресурс (переменную окружения, запись в БД) в несовместимых режимах — возникает коллизия. Требуется группировка флагов по доменам и конфликт-тестирование.
- **Миграции БД:** Флаги не должны управлять структурой таблиц. Попытка изменять схему БД внутри логических условий флага приводит к разрыву между состоянием кода и схемы.

### Edge Cases в Production

- **Одновременное включение нескольких экспериментов:** Если два A/B-теста затрагивают один и тот же UI-компонент, результаты могут быть искажены. Необходимо выявлять пересечения и запускать их последовательно или исключать пересекающуюся аудиторию.
- **Кэширование на CDN/Браузере:** Если флаг определяет видимость элемента UI, а страница кэшируется CDN или браузером, пользователь может видеть устаревшее состояние. Решение: не кэшировать страницы с активными флагами или добавлять `Cache-Control: no-cache` для путей с флагами.
- **Offline-режим (Mobile):** При отсутствии сети SDK не может получить обновленное значение флага. Используйте bootstrap-файл (последнее известное состояние) или hardcoded fallback.
- **WASM без KeyValue Storage:** Если CDN не поддерживает KV Storage (например, простой CDN без durable objects), правила флагов необходимо инлайнить в WASM-модуль при сборке — это делает обновление правил невозможным без пересборки модуля.
- **flagd sidecar restart loop:** При частых рестартах flagd (вследствие OOM или liveness probe failure) приложение теряет доступ к локальному evaluation engine и переключается на удаленный сервер — это увеличивает latency и создает нагрузку на FFaaS. Мониторьте потребление памяти flagd и настраивайте appropriate resource limits.

---

## Дополнительная информация

### Внутренние ресурсы
- **[Обзор Feature Toggles](./overview.md)** — парадигма Deploy vs Release.
- **[Типы Feature Toggles](./types.md)** — классификация по времени жизни.
- **[Реализация в коде](./implementation.md)** — использование паттерна Wrapper и OpenFeature.
- **[Лучшие практики](./best_practices.md)** — гигиена и жизненный цикл.
- **[Feature Flags в GitOps](../../GitOps/Concepts/feature_flags_gitops.md)** — декларативное управление флагами через Git, flagd + open-feature-operator.
- **[Антипаттерны](./antipatterns.md)** — типичные ошибки архитектуры флагов.

### Внешние ресурсы
- [OpenFeature Specification](https://openfeature.dev/docs/reference/intro) — промышленный стандарт.
- [flagd Documentation](https://docs.openfeature.dev/docs/understanding-feature-timing/flagd) — демон оценки флагов от OpenFeature.
- [LaunchDarkly Relay Proxy](https://docs.launchdarkly.com/home/relay-proxy) — архитектура безопасного проксирования.
