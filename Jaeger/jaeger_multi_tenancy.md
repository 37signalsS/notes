# Multi-tenancy и изоляция в Jaeger

> **Важно:** Документация описывает **Jaeger v2** (текущая версия).

**Multi-tenancy в Jaeger** — это архитектурный подход к размещению данных нескольких команд, окружений или бизнес-единиц в одной инфраструктуре Jaeger с гарантированной изоляцией. В enterprise-средах 2026 года Jaeger является shared-сервисом, и без multi-tenancy невозможно обеспечить безопасность, chargeback (атрибуцию затрат) и независимость команд. Подходы варьируются от namespace-based separation до полностью изолированных инстансов.

Общий обзор системы: **[Обзор Jaeger](./jaeger_overview.md)**.
Архитектура: **[Архитектура Jaeger](./jaeger_architecture.md)**.
Интеграция с Kubernetes: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Multi-tenancy (Мультитенантность)** | Архитектурный паттерн, при котором один экземпляр системы обслуживает несколько независимых tenants |
| **Tenant (Тенант)** | Команда, проект, окружение или бизнес-единица с изолированными данными |
| **Namespace Isolation** | Разделение данных по Kubernetes namespace'ам с отдельными RBAC и NetworkPolicy |
| **Shared Instance** | Один кластер Jaeger, обслуживающий всех tenants с изоляцией на уровне namespace/хранилища |
| **Dedicated Instance** | Отдельный кластер Jaeger для критичного tenant |
| **Chargeback** | Механизм атрибуции стоимости инфраструктуры (storage, compute) конкретным командам |
| **Showback** | Отчетность по использованию ресурсов без прямого списания затрат |

---

## Базовые концепции

### Модели multi-tenancy

| Модель | Описание | Изоляция | Стоимость | Сложность |
| :--- | :--- | :--- | :--- | :--- |
| **Namespace-based** | Разные команды → разные namespace'ы с общим Collector/Storage | Средняя (RBAC + NetworkPolicy) | Низкая | Средняя |
| **Storage-based** | Разные tenants → разные базы/индексы в одном ClickHouse/ES кластере | Высокая (отдельные таблицы/индексы) | Средняя | Средняя |
| **Dedicated per tenant** | Каждая команда получает свой инстанс Jaeger | Полная | Высокая | Высокая |
| **Shared with attributes** | Все данные в одном хранилище, изоляция через атрибут `tenant_id` | Низкая (фильтрация на уровне UI/API) | Минимальная | Низкая |

### Критерии выбора модели

| Критерий | Namespace-based | Storage-based | Dedicated | Shared with attributes |
| :--- | :--- | :--- | :--- | :--- |
| **Безопасность** | Средняя | Высокая | Полная | Низкая |
| **Стоимость** | Низкая | Средняя | Высокая | Минимальная |
| **Эксплуатация** | Простая | Средняя | Сложная | Простая |
| **SLA per tenant** | Общий | Частичный | Отдельный | Общий |
| **Совместимость с Jaeger v2** | Да | Да | Да | Да (с фильтрами) |

---

## Практические сценарии

### Сценарий 1: Namespace-based isolation

**Ситуация:** Необходимо изолировать данные команд `team-a` и `team-b` в одном кластере Jaeger.

```yaml
# Namespace для team-a
apiVersion: v1
kind: Namespace
metadata:
  name: team-a
  labels:
    team: team-a
    jaeger-tenant: "true"

---
# ServiceAccount с ограниченными правами
apiVersion: v1
kind: ServiceAccount
metadata:
  name: jaeger-collector
  namespace: team-a

---
# ClusterRole с доступом только к namespace team-a
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: jaeger-collector-team-a
rules:
  - apiGroups: [""]
    resources: ["pods", "namespaces", "events"]
    verbs: ["get", "watch", "list"]
    # Ограничение по namespace через ResourceFilter (если поддерживается)
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets"]
    verbs: ["get", "watch", "list"]

---
# ClusterRoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: jaeger-collector-team-a
subjects:
  - kind: ServiceAccount
    name: jaeger-collector
    namespace: team-a
roleRef:
  kind: ClusterRole
  name: jaeger-collector-team-a
  apiGroup: rbac.authorization.k8s.io

---
# NetworkPolicy для изоляции
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: team-a-jaeger-isolation
  namespace: team-a
spec:
  podSelector:
    matchLabels:
      app: jaeger
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              team: team-a
      ports:
        - protocol: TCP
          port: 4317
        - protocol: TCP
          port: 4318
        - protocol: TCP
          port: 16686
```

**Валидация:**

1. Применить ресурсы: `kubectl apply -f team-a-isolation.yaml`.
2. Проверить, что Collector запускается: `kubectl get pods -n team-a`.
3. Убедиться, что трафик из других namespace'ов блокируется: `kubectl exec -it test-pod -n team-b -- curl --connect-timeout 2 http://jaeger-collector.team-a:4317`.

### Сценарий 2: Storage-based isolation (отдельные индексы ClickHouse)

**Ситуация:** Необходимо разделить данные по командам на уровне хранилища ClickHouse.

```sql
-- Создание отдельных баз данных для каждого tenant
CREATE DATABASE IF NOT EXISTS jaeger_team_a;
CREATE DATABASE IF NOT EXISTS jaeger_team_b;

-- Таблица для team-a
CREATE TABLE IF NOT EXISTS jaeger_team_a.spans
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
    tenant String DEFAULT 'team-a',
    PRIMARY KEY (trace_id, span_id, tenant)
)
ENGINE = MergeTree()
PARTITION BY toDate(fromUnixTimestamp64Nano(start_time_ns))
ORDER BY (tenant, service_name, operation_name, start_time_ns)
TTL start_time_ns + INTERVAL 7 DAY;

-- Индекс по tenant для быстрой фильтрации
CREATE INDEX idx_tenant ON jaeger_team_a.spans (tenant) TYPE bloom_filter GRANULARITY 4;
```

**Конфигурация Collector для tenant-based routing:**

```yaml
processors:
  attributes:
    actions:
      - key: tenant
        value: "team-a"
        action: insert

exporters:
  jaeger_storage_exporter:
    trace_storage:
      type: clickhouse
      options:
        clickhouse:
          endpoint: "tcp://clickhouse:9000"
          database: jaeger_team_a
```

### Сценарий 3: Chargeback и Showback

**Ситуация:** Необходимо рассчитать стоимость хранения трейсов для каждой команды.

```sql
-- ClickHouse: расчет объема данных по tenant
SELECT 
    tenant,
    count() as span_count,
    formatReadableSize(sum(bytesOnDisk)) as storage_size,
    min(start_time_ns) as earliest_span,
    max(start_time_ns) as latest_span
FROM jaeger_v2.spans
WHERE start_time_ns > now() - INTERVAL 30 DAY
GROUP BY tenant
ORDER BY span_count DESC;
```

**Prometheus-метрики для chargeback:**

```promql
# Объем данных по tenant (если хранится в атрибуте)
sum by (tenant) (rate(otelcol_exporter_sent_spans[1h]))

# Стоимость storage
sum by (tenant) (jaeger_storage_bytes_total{storage="clickhouse"}) * 0.02 / 1024^3
```

**Дашборд Grafana для chargeback:**

```json
{
  "dashboard": {
    "title": "Jaeger Chargeback by Team",
    "panels": [
      {
        "title": "Storage Usage per Tenant",
        "type": "graph",
        "targets": [
          {
            "expr": "sum by (tenant) (jaeger_storage_bytes_total)",
            "legendFormat": "{{tenant}}"
          }
        ]
      },
      {
        "title": "Spans per Second by Tenant",
        "type": "graph",
        "targets": [
          {
            "expr": "sum by (tenant) (rate(otelcol_exporter_sent_spans[5m]))",
            "legendFormat": "{{tenant}}"
          }
        ]
      }
    ]
  }
}
```

---

## Лучшие практики

1.  **Начинайте с namespace isolation:** Это минимальный viable approach для multi-tenancy в Kubernetes.
2.  **Используйте отдельные базы ClickHouse для критичных teams:** Namespace isolation не защищает от администратора БД.
3.  **Chargeback через метрики:** Включайте атрибут `tenant` в спаны и агрегируйте его в spanmetrics.
4.  **Shared Instance для dev/test:** Используйте общий инстанс для не-production окружений для снижения стоимости.
5.  **Dedicated Instance для compliance:** Если данные содержат PII или регулируются (GDPR, HIPAA), используйте dedicated инстанс.

---

## Очистка окружения

```bash
# Удаление namespace team-a
kubectl delete namespace team-a

# Удаление баз данных ClickHouse
clickhouse-client --query "DROP DATABASE IF EXISTS jaeger_team_a"
clickhouse-client --query "DROP DATABASE IF EXISTS jaeger_team_b"

# Очистка Docker
docker compose down -v
```

---

## Дополнительная информация

**Смежные темы:**

* RBAC и безопасность: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**
* High Availability: **[High Availability и DR](./jaeger_high_availability.md)**
* Capacity Planning: **[Capacity Planning для Jaeger](./jaeger_capacity_planning.md)**
* Kubernetes RBAC: **[RBAC в Kubernetes](../Kubernetes/Security/rbac/rbac_overview.md)**

### См. также

* [Jaeger Multi-tenancy Documentation](https://www.jaegertracing.io/docs/latest/multitenancy/)
* [OpenTelemetry Collector Resource Attributes](https://opentelemetry.io/docs/specs/semconv/resource/)
