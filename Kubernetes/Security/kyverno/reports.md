# Policy Reports (Отчеты) Kyverno

## Определения

**Policy Report** — стандартизированный формат отчетов о применении политик, разработанный **Policy Report Working Group** (WG Policy K8s).

**Типы отчетов**:
- **PolicyReport** — namespace-scoped ресурс, создается для политик типа `Policy`
- **ClusterPolicyReport** — cluster-scoped ресурс, создается для политик типа `ClusterPolicy`

> **Основной файл:** Это основной файл по отчетам Kyverno. Другие источники ссылаются на эту документацию.

---

## Basic Concepts

### Как работают отчеты

| Характеристика | Описание |
|----------------|----------|
| **Создание** | Автоматически при создании/обновлении ресурсов, к которым применяются политики |
| **Хранение** | В **etcd** как обычные Kubernetes-ресурсы (отдельная БД не требуется) |
| **Удаление** | При удалении ресурса соответствующая запись удаляется из отчета |
| **Историчность** | Отчеты отражают **текущее состояние**, историческая информация не сохраняется |
| **Формат** | Стандарт **Policy Report WG** — универсальный формат для policy-движков |

### Структура отчета

```yaml
apiVersion: wgpolicyk8s.io/v1alpha2
kind: PolicyReport
metadata:
  name: policyreport
  namespace: default
scope:
  apiVersion: v1
  kind: Namespace
  name: default
results:
  - category: security
    message: "Container must run as non-root user"
    policy: require-run-as-non-root
    result: fail
    resource: pod/my-app
    rule: run-as-non-root
    severity: high
    timestamp:
      nanos: 0
      seconds: 1678901234
summary:
  error: 0
  fail: 3
  pass: 15
  skip: 0
  warn: 1
```

### Поля результата

| Поле | Описание | Пример |
|------|----------|--------|
| `category` | Категория политики | `security`, `best-practices`, `compliance` |
| `message` | Сообщение о результате | "Container must run as non-root" |
| `policy` | Имя примененной политики | `require-run-as-non-root` |
| `result` | Статус результата | `pass`, `fail`, `warn`, `skip`, `error` |
| `resource` | Ресурс, к которому применена политика | `pod/my-app` |
| `rule` | Имя правила в политике | `run-as-non-root` |
| `severity` | Критичность нарушения | `low`, `medium`, `high`, `critical` |

### Статусы результатов (result)

| Статус | Описание | Когда присваивается |
|--------|----------|---------------------|
| **pass** | Ресурс прошел проверку | Политика выполнена успешно |
| **fail** | Ресурс не прошел проверку | Политика запретила ресурс |
| **warn** | Предупреждение | Режим `audit` или аннотация `warn` |
| **skip** | Политика не выполнялась | Сработал `policy exception` или не подошел `match` |
| **error** | Ошибка обработки | Внутренняя ошибка Kyverno |

---

## Practical Scenarios

### Просмотр отчетов

```bash
# Список Policy Reports в namespace
kubectl get policyreports -n <namespace>

# Список ClusterPolicyReports
kubectl get clusterpolicyreports

# Детальная информация
kubectl describe policyreport <name> -n <namespace>

# Отчеты с нарушениями
kubectl get policyreports -n <namespace> -o jsonpath='{range .items[?(@.summary.fail>0)]}{"Namespace: "}{.metadata.namespace}{" - Fail: "}{.summary.fail}{"\n"}{end}'

# Экспорт в YAML
kubectl get policyreport <name> -n <namespace> -o yaml
```

### Пример: Поиск всех нарушений

```bash
# Все fail-результаты в кластере
kubectl get clusterpolicyreports -o jsonpath='{range .items[*].results[?(@.result=="fail")]}{"Policy: "}{.policy}{" Resource: "}{.resource}{" Message: "}{.message}{"\n"}{end}'
```

### Пример: Dashboard запросы

```bash
# Количество нарушений по политикам
kubectl get clusterpolicyreports -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.summary.fail}{"\n"}{end}' | sort -k2 -nr

# Ресурсы с наибольшим количеством нарушений
kubectl get policyreports --all-namespaces -o jsonpath='{range .items[*].results[?(@.result=="fail")]}{.resource}{"\n"}{end}' | sort | uniq -c | sort -nr | head -10
```

### Интеграция с Prometheus

Policy Reporter экспортирует метрики:

```prometheus
# Количество результатов по статусам
policy_report_result_total{result="fail", policy="require-run-as-non-root"}
policy_report_result_total{result="pass", policy="require-run-as-non-root"}

# Сводка по namespace
policy_report_summary_fail{namespace="default"}
policy_report_summary_pass{namespace="default"}
```

### Пример Grafana Dashboard

```json
{
  "panels": [
    {
      "title": "Policy Violations Over Time",
      "targets": [
        {
          "expr": "rate(policy_report_result_total{result=\"fail\"}[5m])",
          "legendFormat": "{{policy}}"
        }
      ]
    },
    {
      "title": "Pass/Fail Ratio",
      "targets": [
        {
          "expr": "sum(policy_report_result_total{result=\"pass\"}) / sum(policy_report_result_total{result=\"fail\"})",
          "legendFormat": "Ratio"
        }
      ]
    }
  ]
}
```

---

## Additional Information

### Аннотации для настройки поведения

| Аннотация | Значение | Описание |
|-----------|----------|----------|
| `policies.kyverno.io/validation-failure-action` | `enforce`, `audit`, `warn` | Режим применения политики |
| `policies.kyverno.io/title` | Заголовок | Отображаемое имя политики |
| `policies.kyverno.io/category` | Категория | Группа политик (security, best-practices) |
| `policies.kyverno.io/severity` | `low`, `medium`, `high`, `critical` | Критичность нарушения |
| `policies.kyverno.io/description` | Описание | Подробное описание политики |

### Пример политики с аннотациями

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-run-as-non-root
  annotations:
    policies.kyverno.io/title: Require Non-Root User
    policies.kyverno.io/category: Security
    policies.kyverno.io/severity: high
    policies.kyverno.io/description: >-
      Containers must run as non-root user to reduce attack surface.
spec:
  validationFailureAction: Enforce
  background: true
  rules:
    - name: run-as-non-root
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "Container must run as non-root user"
        pattern:
          spec:
            securityContext:
              runAsNonRoot: true
```

### Ограничения

- Отчеты хранятся в etcd — при большом количестве ресурсов возможен рост占用
- Историческая информация не сохраняется — только текущее состояние
- При удалении политики отчеты не удаляются автоматически

### Связанные темы

- [Background Scans](./background.md) — фоновое сканирование для отчетов
- [Policy Reporter](./reporter.md) — Web UI и метрики для отчетов
- [Написание политик](./policies.md) — создание политик с аннотациями
