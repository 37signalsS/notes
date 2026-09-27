# Архитектура систем Feature Toggles

## Определения

**Архитектура Feature Toggles** — комплексная инфраструктурная экосистема, обеспечивающая централизованное управление, безопасную доставку и высокопроизводительное вычисление состояний флагов функций в рантайме. Современная архитектура (2026+) ориентирована на минимизацию сетевых задержек, защиту персональных данных (PII) и полную интеграцию с процессами прогрессивной поставки (Progressive Delivery).

**FFaaS (Feature Flag as a Service)** — платформа управления флагами, предоставляющая Admin UI, API, Targeting Engine и Audit Service. Примеры self-hosted решений: Unleash, Flipt.

**flagd** — демон оценки флагов от OpenFeature, вычисляющий значение флага по правилам таргетинга и возвращающий результат по gRPC/HTTP. Обеспечивает оценку без сетевого вызова во внешнюю систему.

**Relay / Proxy Layer** — промежуточный слой кеширования и/или вычисления между SDK и Control Plane. Снижает нагрузку на FFaaS и обеспечивает PII Stripping.

**Evaluation Strategy** — метод вычисления значения флага: Local (в памяти процесса), Remote (на сервере), или Hybrid (комбинация).

**Bootstrap File** — локальный JSON-файл с последними известными состояниями флагов, используемый SDK при старте до установления соединения с сервером.

---

## Основные концепции

### Принципы архитектуры 2026+

Современная архитектура систем управления флагами строится на пяти ключевых принципах:

1.  **Vendor-Neutral API** — использование OpenFeature SDK позволяет абстрагироваться от конкретной FFaaS-платформы. Смена вендора (Unleash → Flipt → собственная реализация) не требует изменения кода приложения.
2.  **Local-First Evaluation** — вычисление происходит как можно ближе к приложению (в процессе или в flagd sidecar), обеспечивая `O(1)` производительность без внешних вызовов в hot path.
3.  **Privacy by Design** — PII Stripping выполняется на уровне Proxy до попадания контекста в FFaaS. Используется хеширование (SHA-256) вместо передачи raw-значений.
4.  **Fail-Safe by Default** — архитектура гарантирует работу приложения при полной недоступности системы флагов через Bootstrap File → In-Memory Cache → Hardcoded Defaults.
5.  **Observability-Native** — состояние флагов инжектируется в спаны OpenTelemetry, а метрики SDK экспортируются в Prometheus для построения дашбордов и алертинга.

### Многоуровневая архитектура

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                      УРОВЕНЬ ИСПОЛНЕНИЯ (SDK)                            │
│  ┌──────────────┐      ┌───────────────┐      ┌──────────────────────┐  │
│  │ OpenFeature  │◄────►│  Evaluation   │◄────►│     App Logic       │  │
│  │   Wrapper    │      │    Engine     │      │    (Wrapped)        │  │
│  └──────────────┘      └───────────────┘      └──────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │ gRPC/HTTP/SSE
                                    │
┌──────────────────────────────────────────────────────────────────────────┐
│                   СЛОЙ ПРОКСИРОВАНИЯ / КЕШИРОВАНИЯ                       │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  Relay / Proxy (flagd centralized / custom implementation)       │   │
│  │  • PII Stripping                                                 │   │
│  │  • Connection Offloading (1 connection to FFaaS per cluster)     │   │
│  │  • Local Evaluation Engine                                       │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │
┌──────────────────────────────────────────────────────────────────────────┐
│                   ЦЕНТРАЛЬНЫЙ СЕРВЕР ВЫЧИСЛЕНИЙ (API)                    │
│   (Targeting Engine, Segment Manager, Audit Service, Event Stream)       │
└──────────────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │
┌──────────────────────────────────────────────────────────────────────────┐
│      ПЛОСКОСТЬ УПРАВЛЕНИЯ (Control Plane) / СЛОЙ ХРАНЕНИЯ               │
│  ┌─────────────────────────┐            ┌────────────────────────────┐   │
│  │  Admin UI / API / RBAC  │            │  PostgreSQL / Redis / S3   │   │
│  └─────────────────────────┘            └────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

### Ключевые компоненты и их функции

#### 1. SDK (Evaluation Engine)

**Evaluation (Вычисление):** В 2026 году стандартом является OpenFeature SDK. Вычисление логики (таргетинг) происходит внутри процесса приложения, что дает `O(1)` производительность без внешних вызовов в hot path.

**Synchronization:** SDK поддерживает три протокола получения обновлений:
- **Polling** — HTTP GET с интервалом 30-60 секунд. Простой, но создает избыточную нагрузку.
- **SSE (Server-Sent Events)** — персистентное HTTP-соединение, обновления приходят по событию (<1с задержка). Рекомендуется для Production.
- **gRPC Streaming** — bidirectional streaming с минимальной задержкой. Для высоконагруженных систем.

#### 2. Relay / Proxy Layer

**Privacy Guard:** Слой проксирования удаляет или хеширует PII до того, как контекст пользователя попадет в FFaaS.

**Connection Offloading:** Прокси держит одно соединение с сервером, обслуживая тысячи инстансов приложения, снижая нагрузку на Control Plane.

**Local Evaluation:** Современные прокси (flagd) выполняют вычисление локально, полностью исключая необходимость выхода во внешнюю сеть для каждой проверки.

#### 3. flagd (OpenFeature Daemon)

**flagd** — демон оценки флагов, который вычисляет значение флага по правилам таргетинга и отдает результат по gRPC/HTTP. Локальный flagd рядом с приложением обеспечивает оценку без сетевого вызова во внешнюю систему.

```text
┌─────────────────────────────────────────────────────────────────────┐
│                     Pod (Kubernetes)                                │
│                                                                     │
│  ┌──────────────────┐           ┌──────────────────────────────┐    │
│  │  App Container  │           │  flagd Sidecar / Proxy       │    │
│  │                  │           │                              │    │
│  │  OpenFeature     │◄─────────►│  gRPC :8013 / HTTP :8014    │    │
│  │  SDK             │           │  Evaluation Engine           │    │
│  │                  │           │  Rules Cache                  │    │
│  └──────────────────┘           └──────────────┬───────────────┘    │
│                                                 │                   │
└─────────────────────────────────────────────────┼───────────────────┘
                                                  │
                                    ┌─────────────▼─────────────┐
                                    │  ConfigMap / HTTP API     │
                                    │  (источник правил)         │
                                    └───────────────────────────┘
```

**Режимы работы flagd:**

| Режим | Описание | Протокол | Применимость |
| :--- | :--- | :--- | :--- |
| **Sidecar** | flagd запущен в каждом Pod как sidecar-контейнер | gRPC/HTTP `localhost:8013` | Kubernetes, максимальная изоляция |
| **Centralized** | Один инстанс flagd обслуживает несколько подов | gRPC/HTTP через Service | Малые кластеры, dev-окружения |
| **Kubernetes Operator** | open-feature-operator управляет жизненным циклом flagd | CRD (`FlagSourceConfiguration`) | GitOps, декларативное управление |

### Методы вычисления флагов (Evaluation Strategies)

| Метод | Описание | Применимость | Риски |
| :--- | :--- | :--- | :--- |
| **Local Evaluation** | SDK скачивает Ruleset и вычисляет результат в памяти процесса. | Бэкенд-сервисы, высоконагруженные API. | Утечка правил сегментации (код видит всю логику). |
| **Remote Evaluation** | SDK отправляет контекст на сервер и получает только результат. | Клиентские приложения (JS, Mobile). | Сетевой latency, риск отказа API. |
| **Hybrid Evaluation** | Публичные правила локально, чувствительные — удаленно через Relay. | Корпоративные системы с высокими требованиями безопасности. | Усложнение конфигурации SDK. |

### Стратегии кеширования в SDK

| Стратегия | Описание | TTL | Использование памяти | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **In-Memory Cache** | Хранение Ruleset в памяти процесса | Зависит от протокола синхронизации | Низкая (<1MB) | По умолчанию для всех SDK |
| **Persistent Cache** | Запись Ruleset на диск (SQLite/JSON) | До перезапуска приложения | Средняя | Mobile/offline-приложения |
| **Bootstrap File** | Локальный JSON-файл с последними известными состояниями | До первого успешного обновления | Низкая | Fail-safe при недоступности сервера |
| **Distributed Cache** | Распределенный кеш (Redis) | Настроенный TTL | Средняя | Relay/Proxy, кластерные deployments |

**Порядок приоритетов при вычислении флага:**

```text
1. Hardcoded default (в коде приложения)
         ▼
2. Bootstrap File (локальный JSON)
         ▼
3. In-Memory Cache (Ruleset из памяти)
         ▼
4. Remote Server (FFaaS API / flagd gRPC)
```

При недоступности сервера флагов SDK последовательно спускается по этому списку, гарантируя что всегда есть значение для возврата.

---

## Практические сценарии

### Предварительные требования

#### Инструментарий

| Компонент | Назначение | Минимальная версия |
| :--- | :--- | :--- |
| **FFaaS платформа** | Хранение и управление флагами (Unleash, Flipt) | Unleash v5+ / Flipt v1.35+ |
| **OpenFeature SDK** | Унифицированный API для проверки флагов в коде | v0.4+ (Python/Go/Java/Node) |
| **flagd** | Локальный демон оценки флагов (OpenFeature) | v0.8+ |
| **OpenTelemetry Collector** | Сбор и передача телеметрии по состоянию флагов | v0.95+ |
| **Prometheus + Grafana** | Мониторинг использования флагов и их влияния на метрики | Prometheus v2.50+, Grafana v10+ |
| **Redis** | Кеш состояний флагов для Relay/Proxy | Redis v7+ |
| **PostgreSQL** | Хранилище конфигурации флагов (Unleash/Flipt) | PostgreSQL v15+ |
| **Kubernetes** (опционально) | Оркестрация Relay/Proxy и flagd sidecar | v1.28+ |

#### Локальное окружение для тестирования

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

### Развертывание flagd в Kubernetes

**Deployment flagd как centralized proxy:**

```yaml
# deployment-flagd.yaml
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

**Применение конфигурации:**

```bash
# Создание namespace
kubectl create namespace feature-flags

# Развертывание flagd
kubectl apply -f deployment-flagd.yaml

# Проверка статуса
kubectl get pods -n feature-flags
# → flagd-proxy-<hash>   2/2   Running   0   30s

# Проверка доступности gRPC
kubectl run -it --rm --image=busybox:1.36 --restart=Never grpc-test -- nslookup flagd-proxy.feature-flags.svc.cluster.local
# → Address: <cluster-ip>
```

### Конфигурация FlagSourceConfiguration (Kubernetes Operator)

```yaml
# flagsource-configuration.yaml
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

**Применение:**

```bash
kubectl apply -f flagsource-configuration.yaml

# Проверка статуса FlagSourceConfiguration
kubectl get flagsourceconfiguration -n billing
# → NAME                   AGE   READY   REASON
# → checkout-flagsource    10s   True    FlagSourceConfigurationReady

# Проверка метрик flagd
curl -s http://flagd-proxy.feature-flags.svc.cluster.local:8015/metrics | grep feature_flag
# → feature_flag_evaluations_total{flag="checkout-v3",value="true"} 1523
```

### Конфигурация SDK: примеры

**OpenFeature SDK (Python) с SSE:**

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
    cache_ttl=300,                 # 5 минут
    # Bootstrap: локальный файл с последними известными флагами
    bootstrap="/etc/feature-flags/bootstrap.json",
    bootstrap_override=False       # True = bootstrap перезаписывает Ruleset
))
```

**OpenFeature SDK (Go) с flagd sidecar:**

```go
package main

import (
    "log"
    "github.com/open-feature/go-sdk"
    "github.com/open-feature/go-sdk-contrib/providers/flagd"
)

func main() {
    provider, err := flagd.NewProvider(
        flagd.WithInProcessResolver("checkout-service", "localhost:8013"),
        flagd.WithLogger(log.New(os.Stderr, "", log.LstdFlags)),
    )
    if err != nil {
        log.Fatalf("Failed to create flagd provider: %v", err)
    }

    openfeature.SetProvider(provider)
    log.Println("Feature flags provider initialized successfully")
}
```

### Bootstrap File: реализация и сценарии использования

Bootstrap File — локальный JSON-файл с последним известным состоянием флагов. SDK читает его при старте до установления соединения с сервером.

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

**Генерация Bootstrap файла в CI/CD:**

```bash
#!/bin/bash
# scripts/generate-bootstrap.sh — генерация bootstrap.json из текущего состояния FFaaS
set -euo pipefail

UNLEASH_URL="${UNLEASH_URL:-http://localhost:4242}"
UNLEASH_TOKEN="${UNLEASH_TOKEN:-*:*.admin}"
BOOTSTRAP_PATH="${BOOTSTRAP_PATH:-/etc/feature-flags/bootstrap.json}"

FEATURES=$(curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_TOKEN" | \
  jq '[.features[] | select(.stages[]?.name == "production") | {
    name: .name,
    enabled: .stages[]?.enabled,
    variant: .variants[0].name
  }]')

echo "$FEATURES" | jq '.' > "$BOOTSTRAP_PATH"
echo "Bootstrap file generated: $BOOTSTRAP_PATH"
echo "Features count: $(echo "$FEATURES" | jq 'length')"
```

**CI/CD интеграция (GitLab CI):**

```yaml
# .gitlab-ci.yml
generate-bootstrap:
  stage: deploy
  image: curlimages/curl:latest
  script:
    - bash scripts/generate-bootstrap.sh
  artifacts:
    paths:
      - /etc/feature-flags/bootstrap.json
  only:
    - main
```

---

## Операции и команды

### Безопасность и отказоустойчивость

#### Защита плоскости управления

**RBAC & OIDC:** Доступ к переключению флагов в Production должен быть защищен через корпоративный IdP (Keycloak) с обязательным MFA.

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
# → {"id": 3, "name": "Release Manager", ...}

# Назначение роли пользователю
curl -s -X POST "$UNLEASH_URL/api/admin/projects/default/members" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "users": [{"id": 1, "roleId": 3}]
  }'
# → [{"id": 1, "name": "user@example.com", "role": "Release Manager"}]
```

**Four-Eyes Principle:** Критические операционные флаги (Kill Switch, Security Toggles) требуют аппрува от второго инженера или SRE через Change Request workflow.

**Настройка Change Request в Unleash:**

```bash
# Включение Change Request для Production
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
# → {"id": "default", "mode": "open", ...}
```

**Audit Trail:** Каждое изменение флага должно сопровождаться записью в неизменяемом логе (кто, когда, зачем, значение `old` vs `new`).

**Экспорт аудита в Loki:**

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
# → {"id": "audit-loki", "type": "webhook", ...}
```

#### Стратегии Fail-safe

Архитектура должна гарантировать работу приложения при полной недоступности FFaaS:

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
# scripts/failover-test.sh — проверка работы при недоступности FFaaS
set -euo pipefail

UNLEASH_SERVICE="${UNLEASH_SERVICE:-unleash}"
APP_URL="${APP_URL:-http://localhost:8080}"

echo "Stopping FFaaS..."
docker compose stop "$UNLEASH_SERVICE"
sleep 5

echo "Testing application without FFaaS..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$APP_URL/checkout")
if [ "$HTTP_CODE" = "200" ]; then
    echo "PASS: Application works without FFaaS (HTTP $HTTP_CODE)"
else
    echo "FAIL: Application returned HTTP $HTTP_CODE without FFaaS"
    exit 1
fi

echo "Restoring FFaaS..."
docker compose start "$UNLEASH_SERVICE"
sleep 3

echo "Verifying FFaaS is back..."
curl -s -o /dev/null -w "%{http_code}" "$UNLEASH_URL/api/admin/user"
# → 200
echo "PASS: FFaaS restored successfully"
```

### Наблюдаемость и мониторинг

#### Интеграция с OpenTelemetry

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

#### Настройка Prometheus для мониторинга флагов

**Метрики OpenFeature SDK (автоматически экспортируются):**

```yaml
# prometheus.yml: scrape config для flagd
scrape_configs:
  - job_name: 'flagd'
    static_configs:
      - targets: ['flagd-proxy.feature-flags.svc.cluster.local:8015']
    scrape_interval: 15s
    metrics_path: /metrics
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
          runbook_url: "https://wiki.internal/runbooks/flag-evaluation-errors"

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

      # Zombie-флаг: флаг не изменялся >30 дней
      - alert: ZombieFlagDetected
        expr: |
          (
            time() - (
              vector(flag_last_modified_timestamp_seconds{flag=~".+"}) * 1
            )
          ) > 2592000  # 30 дней в секундах
        for: 1h
        labels:
          severity: info
        annotations:
          summary: "Zombie-флаг: {{ $labels.flag }}"
          description: "Флаг не изменялся более 30 дней. Проверьте необходимость его удаления."
          runbook_url: "https://wiki.internal/runbooks/zombie-flag-cleanup"

      # Коллизия флагов: несколько флагов влияют на один ресурс
      - alert: FlagCollisionDetected
        expr: |
          count by (resource) (
            group(
              flag_resource_usage_total{resource=~".+"}
            ) > 1
          )
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Коллизия флагов на ресурсе {{ $labels.resource }}"
          description: "Несколько флагов влияют на один ресурс. Проверьте конфликты."
          runbook_url: "https://wiki.internal/runbooks/flag-collision"
```

### Автоматизация и CI/CD интеграция

#### Валидация флагов в CI-пайплайне

Автоматическая проверка naming conventions и состояния флагов должна выполняться на этапе `validate` CI-пайплайна. Подробный скрипт и конфигурация — в [Лучшие практики](./best_practices.md).

#### Автоматический откат через Alertmanager

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

### Безопасность: сетевые политики

**NetworkPolicy для flagd в Kubernetes:**

```yaml
# networkpolicy-flagd.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: flagd-allow
  namespace: feature-flags
spec:
  podSelector:
    matchLabels:
      app: flagd-proxy
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: billing
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: checkout
      ports:
        - protocol: TCP
          port: 8013
        - protocol: TCP
          port: 8014
  egress:
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - protocol: TCP
          port: 443  # FFaaS API
```

**Применение:**

```bash
kubectl apply -f networkpolicy-flagd.yaml
kubectl get networkpolicy -n feature-flags
# → NAME           AGE   POD-SELECTOR
# → flagd-allow   5s    app=flagd-proxy
```

---

## Типичные ошибки и диагностика

| Симптом | Вероятная причина | Диагностические действия | Решение |
| :--- | :--- | :--- | :--- |
| SDK не подключается к FFaaS | Сетевой firewall, неверный URL | `telnet ff-api.internal 4242` → проверить доступность; `curl -v $UNLEASH_URL/api/client/features` → проверить HTTP-ответ | Убедиться, что порт открыт между подом приложения и FFaaS; проверить DNS-резолв |
| Оценка флага возвращает дефолт | SDK не получил Ruleset, bootstrap отсутствует | `docker logs flagd-proxy` → проверить sync; `ls -la /etc/feature-flags/` → проверить наличие bootstrap.json | Убедиться, что bootstrap файл доступен; проверить права доступа к файлу |
| Флаг не обновляется в Runtime | SDK кеширует старый Ruleset | `tcpdump -i any port 8013` → проверить SSE/gRPC-соединение; проверить `cache_ttl` | Увеличить частоту polling или переключиться на SSE; проверить Health Check flagd |
| Высокий latency оценки флагов | Remote evaluation вместо local | `curl -w "@curl-format.txt" -o /dev/null -s $UNLEASH_URL/api/client/features` → замерить latency | Переключиться на local evaluation (SSE + in-memory cache); добавить flagd sidecar |
| Флаги различаются между средами | Ручное управление без GitOps | `diff <(curl -s prod-flags) <(curl -s staging-flags)` → найти расхождения | Декларативное управление через GitOps; diff флагов — часть ревью PR |
| Bootstrap не работает | Неверный формат JSON, отсутствие файла | `python -m json.tool /etc/feature-flags/bootstrap.json` → проверить формат | Использовать валидный JSON; убедиться, что volume mount корректен |
| flagd sidecar не стартует | Неверный образ, проблемы с health check | `kubectl describe pod <pod-name>` → проверить Events; `kubectl logs <pod-name> -c flagd` → проверить логи | Проверить версию образа; убедиться, что port 8013 доступен; проверить readinessProbe |
| PII утекает в FFaaS | Proxy не настроен на strip PII | `curl $UNLEASH_URL/api/admin/projects/default/features/flag-name` → проверить context в логах | Настроить PII Stripping в Proxy; использовать hashing вместо raw значений |
| Zombie-флаг мешает релизу | Устаревший флаг блокирует логику | `curl -s $UNLEASH_URL/api/admin/projects/default/features | jq '[.features[] | select(.stale)] | length'` → подсчитать | Удалить или обновить TTL; запустить cleanup-спринт |
| flagd OOMKill | Недостаточно ресурсов | `kubectl describe pod <pod-name> | grep -A5 "Last State"` → проверить причину завершения | Увеличить limits memory; настроить `cache_ttl` для уменьшения потребления |

### Disaster Recovery

#### Процедура восстановления при полном отказе FFaaS

```bash
#!/bin/bash
# scripts/dr-ffaas-restore.sh — Disaster Recovery для FFaaS
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backup/feature-flags}"
RESTORE_DIR="${RESTORE_DIR:-/etc/feature-flags}"

echo "=== Disaster Recovery: Feature Flags ==="

# 1. Остановка приложения
echo "[1/5] Stopping application..."
kubectl scale deployment checkout-service --replicas=0 -n billing

# 2. Экспорт текущего состояния флагов (если FFaaS частично доступен)
echo "[2/5] Exporting current flag state..."
curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" | \
  jq '.' > "$BACKUP_DIR/flags-export-$(date +%Y%m%d-%H%M%S).json"

# 3. Генерация Bootstrap File из последнего бэкапа
echo "[3/5] Generating Bootstrap File..."
cp "$BACKUP_DIR/bootstrap-latest.json" "$RESTORE_DIR/bootstrap.json"

# 4. Перезапуск приложения с Bootstrap
echo "[4/5] Restarting application with Bootstrap..."
kubectl scale deployment checkout-service --replicas=3 -n billing
kubectl rollout status deployment/checkout-service -n billing --timeout=5m

# 5. Валидация
echo "[5/5] Validating application health..."
kubectl get pods -n billing -l app=checkout-service
# → NAME                                  READY   STATUS    RESTARTS   AGE
# → checkout-service-<hash>               1/1     Running   0          30s

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://checkout-service.billing.svc.cluster.local/health")
if [ "$HTTP_CODE" = "200" ]; then
    echo "PASS: Application recovered successfully"
else
    echo "FAIL: Application health check returned HTTP $HTTP_CODE"
    exit 1
fi

echo "=== Disaster Recovery completed ==="
```

---

## Best Practices

### Архитектурные принципы

1.  **Single Source of Truth:** FFaaS-платформа является единственным источником истины для состояний флагов. Локальный кеш (Bootstrap, In-Memory) — только fallback.
2.  **Local Evaluation by Default:** Вычисление должно происходить локально (SDK или flagd). Remote evaluation только для чувствительных правил.
3.  **Fail-Safe Defaults:** Для новых фич по умолчанию `False`. Для Kill Switch — `True` (фича активна, пока мониторинг не скажет обратное).
4.  **Network Partition Tolerance:** Архитектура должна учитывать разделение сети между приложением и FFaaS. Bootstrap File — обязательный компонент.
5.  **Observability-First:** Каждый критический флаг должен иметь:
    - Дашборд в Grafana с ошибками и латентностью
    - Алерт в Prometheus при превышении порога
    - Runbook с инструкциями по откату

### Операционная модель (SRE/DevOps)

1.  **Ownership:** У каждого флага должен быть Owner (команда) и TTL (срок жизни).
2.  **Four-Eyes Principle:** Изменение критических операционных флагов в Production требует подтверждения от второго инженера или SRE.
3.  **Automated Cleanup:** Ночные джобы CI/CD выполняют автоматический аудит: флаги без изменений >14 дней блокируют мерж новых PR.
4.  **Capacity Planning:** Мониторинг потребления ресурсов flagd (CPU, Memory). Типичные лимиты: 100m CPU, 128Mi Memory на инстанс.
5.  **Change Management:** Все изменения флагов в Production фиксируются в Audit Log и проходят через Change Request workflow.

### Безопасность

1.  **PII Protection:** Контекст пользователя не должен содержать raw PII в FFaaS. Используйте хеширование (SHA-256) или удаление полей.
2.  **Network Segmentation:** flagd и FFaaS должны быть в отдельных namespace с NetworkPolicy, разрешающей только необходимые порты.
3.  **mTLS between Services:** flagd ↔ Application и flagd ↔ FFaaS должны использовать взаимное TLS для аутентификации.
4.  **Secrets Management:** Токены доступа к FFaaS хранятся в Vault или Kubernetes Secrets, не в конфигах или окружении.

---

## Дополнительная информация

### Внутренние ресурсы

- **[Обзор Feature Toggles](./overview.md)** — концептуальная база, Deploy vs Release.
- **[Лучшие практики](./best_practices.md)** — гигиена, naming conventions, жизненный цикл.
- **[Антипаттерны](./antipatterns.md)** — типичные ошибки архитектуры флагов.

### Внешние ресурсы

- [OpenFeature Specification](https://openfeature.dev/specification/) — промышленный стандарт управления флагами.
- [flagd Documentation](https://docs.openfeature.dev/docs/understanding-feature-timing/flagd) — демон оценки флагов от OpenFeature.
- [Trunk Based Development](https://trunkbaseddevelopment.com/feature-flags/) — роль флагов в CI/CD.
