# Отчеты Kyverno (Policy Reports)

## Определения

**Отчет о политиках (Policy Report)** — структурированный Custom Resource (CR), содержащий результаты проверки ресурсов кластера на соответствие установленным правилам безопасности. На 2026 год в экосистеме Kyverno сосуществуют два основных стандарта отчетности:

1.  **Классический (`wgpolicyk8s.io`)**: Стандарт Kubernetes Policy Working Group. Используется для максимальной совместимости с внешними инструментами (например, Falco, Trivy).
2.  **Современный (`openreports.io`)**: Высокопроизводительный стандарт (Kyverno 1.15+), оптимизированный для CEL-политик. Снижает накладные расходы на хранение и обработку данных в 2–3 раза.

**Типы ресурсов отчетности:**
- **PolicyReport (polr)** — отчет по ресурсам внутри конкретного Namespace. Основной тип для отслеживания нарушений в рамках пространства имен.
- **ClusterPolicyReport (cpolr)** — глобальный отчет по ресурсам уровня кластера (Nodes, Namespaces, ClusterRoles, PersistentVolumes).
- **AdmissionReport (admr)** — эфемерный отчет, генерируемый синхронно в момент Admission-запроса. Предназначен для немедленной блокировки или уведомления пользователя в CLI/CI. Автоматически удаляется после обработки (TTL по умолчанию 10 минут).

---

## Основные концепции

### Архитектура Reports Server (v1.18+)

Для кластеров с высокой плотностью ресурсов (>10,000 объектов) хранение отчетов в `etcd` становится узким местом. Решением является перенос данных во внешнее хранилище.

| Компонент | Назначение |
| :--- | :--- |
| **Reports Controller** | Считывает результаты проверок и агрегирует их. Поддерживает etcd и внешнюю БД. |
| **API Aggregation Layer** | Позволяет `kubectl` запрашивать отчеты из внешней БД так, будто они находятся в K8s API. Прозрачно для клиента. |
| **PostgreSQL** | Рекомендуемое хранилище для промышленной эксплуатации. Поддерживает партиционирование по времени и Namespace. |

**Включение Reports Server в Helm:**
```yaml
# values.yaml (Kyverno Helm chart)
reportsController:
  reportsServer:
    enabled: true
    database:
      type: postgres
      host: postgres-ha.db-namespace.svc
      port: 5432
      name: kyverno_reports
      existingSecret: kyverno-db-creds  # Secret с ключами user/password
```

### Жизненный цикл и агрегация данных

Kyverno использует **инкрементальное обновление** отчетов:
1.  При изменении ресурса обновляется только соответствующая запись (Result) внутри `PolicyReport`.
2.  Результаты нескольких политик для одного объекта объединяются в одну структуру `scope`.
3.  **Принудительная очистка**: Если политика удаляется, контроллер отчетов запускает каскадное удаление всех связанных записей во всех отчетах.

**Источники данных для отчетов:**
- **Admission Scan**: Ресурс проверяется при создании/обновлении. Результат записывается в `PolicyReport` (namespace-scoped) или `ClusterPolicyReport` (cluster-scoped). Режим `Audit` — только запись; `Enforce` — запись + блокировка.
- **Background Scan**: Периодическая проверка существующих ресурсов. Интервал настраивается через `BACKGROUND_SCAN_INTERVAL` (по умолчанию 1 час). Результаты дополняют существующие `PolicyReport`.
- **Cleanup Scan**: Для `CleanupPolicy` — результат удаления ресурса записывается в отчет.

**Управление Cleanup Policy (внешнее хранилище):**
```yaml
reportsController:
  reportsServer:
    enabled: true
    database:
      type: postgres
      # ...
    cleanupPolicy:
      enabled: true
      # Удаление отчетов старше 30 дней
      interval: "720h"  # 30 дней
      # Удаление отчетов для удаленных Namespace
      deleteOrphanedReports: true
```

### API версии отчетов

| API Group | Версия | Ресурс | Статус |
| :--- | :--- | :--- | :--- |
| `wgpolicyk8s.io` | `v1` | PolicyReport, ClusterPolicyReport | Стабильный (GA) |
| `wgpolicyk8s.io` | `v1alpha2` | PolicyReport, ClusterPolicyReport | Устаревает |
| `openreports.io` | `v1alpha1` | PolicyReport, ClusterPolicyReport, AdmissionReport | Рекомендуется (Kyverno 1.15+) |

---

## Практические сценарии

### Полные YAML-манифесты

**PolicyReport (namespace-scoped):**
```yaml
apiVersion: wgpolicyk8s.io/v1
kind: PolicyReport
metadata:
  name: default-workload-policy-report
  namespace: default
  labels:
    app.kubernetes.io/managed-by: kyverno
    app.kubernetes.io/part-of: kyverno-reports
  annotations:
    kyverno.io/cluster: production
summary:
  pass: 45
  fail: 3
  warn: 0
  error: 0
  skip: 2
results:
  - policy: require-labels
    rule: check-app-label
    result: pass
    resource:
      apiVersion: apps/v1
      kind: Deployment
      name: nginx-deployment
      uid: "12345678-1234-1234-1234-123456789abc"
      namespace: default
    category: Best Practices
    severity: medium
  - policy: restrict-node-port
    rule: validate-service-type
    result: fail
    resource:
      apiVersion: v1
      kind: Service
      name: my-service
      uid: "87654321-4321-4321-4321-cba987654321"
      namespace: default
    message: "Service type NodePort is not allowed in production"
    category: Security
    severity: high
```

**ClusterPolicyReport (cluster-scoped):**
```yaml
apiVersion: wgpolicyk8s.io/v1
kind: ClusterPolicyReport
metadata:
  name: cluster-wide-security-report
  labels:
    app.kubernetes.io/managed-by: kyverno
summary:
  pass: 120
  fail: 8
  warn: 2
  error: 0
  skip: 5
results:
  - policy: restrict-privilege-escalation
    rule: validate-containers
    result: fail
    resource:
      apiVersion: apps/v1
      kind: Deployment
      name: risky-app
      uid: "11111111-2222-3333-4444-555555555555"
      namespace: production
    message: "Container allows privilege escalation"
    category: Security
    severity: critical
```

**AdmissionReport (ephemeral, openreports.io):**
```yaml
apiVersion: openreports.io/v1alpha1
kind: AdmissionReport
metadata:
  name: admr-12345-67890
  namespace: default
  labels:
    app.kubernetes.io/managed-by: kyverno
  ownerReferences:
    - apiVersion: v1
      kind: Pod
      name: test-pod
      uid: "aaaa-bbbb-cccc-dddd"
results:
  - source: kyverno
    policy: require-labels
    rule: check-app-label
    result: pass
    message: "Label 'app' is present"
    properties:
      engine: CEL
      expression: "has(object.metadata.labels.app)"
```

### Сравнение стандартов: OpenReports vs wgpolicyk8s

**Стандарт OpenReports (`v1alpha1`):**
```yaml
apiVersion: openreports.io/v1alpha1
kind: PolicyReport
results:
  - source: kyverno
    policy: restrict-node-port
    rule: check-service-type
    result: fail
    message: "Service type NodePort is not allowed"
    # Метаданные CEL для отладки
    properties:
      engine: CEL
      expression: "object.spec.type != 'NodePort'"
```

**Ключевое отличие**: OpenReports поддерживает расширенные метаданные (properties), что критично для отладки сложных CEL-выражений и интеграции с системами SIEM.

### Мониторинг через Prometheus

Kyverno предоставляет нативный экспорт метрик для Grafana. Основные показатели:

- `kyverno_policy_results_total`: Общее количество проверок (фильтры по `result`, `policy`, `severity`).
- `kyverno_report_changes_queue_size`: Размер очереди на запись отчетов (индикатор задержек Reports Server).
- `kyverno_admission_reports_created_total`: Интенсивность создания эфемерных отчетов.
- `kyverno_policy_report_results`: Текущее количество результатов в PolicyReport (полезно для алертов).

**Пример Prometheus alert rule:**
```yaml
groups:
  - name: kyverno-reports
    rules:
      - alert: KyvernoPolicyReportHighFailureRate
        expr: |
          sum(rate(kyverno_policy_results_total{result="fail"}[5m]))
          / sum(rate(kyverno_policy_results_total[5m])) > 0.1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High policy failure rate (>10%)"
          description: "Policy failure rate is {{ $value | humanizePercentage }}"

      - alert: KyvernoReportQueueBacklog
        expr: kyverno_report_changes_queue_size > 100
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Reports Server queue backlog"
          description: "Queue size is {{ $value }} - possible database latency"
```

### Командная строка: Глубокий анализ

```bash
# Получение списка всех ресурсов, проваливших проверку конкретной политики
kubectl get policyreports -A -o json | jq '.items[].results[] | select(.policy=="my-policy" and .result=="fail") | .resources[0].name'

# Сводная статистика нарушений в кластере
kubectl get clusterpolicyreports -o custom-columns=NAME:.metadata.name,PASS:.summary.pass,FAIL:.summary.fail,WARN:.summary.warn

# Фильтрация по severity
kubectl get polr -A -o json | jq '.items[].results[] | select(.result=="fail" and .severity=="high") | {policy: .policy, resource: .resources[0].name, namespace: .resources[0].namespace}'

# Количество нарушений по политикам (топ-10)
kubectl get polr -A -o json | jq '[.items[].results[] | select(.result=="fail")] | group_by(.policy) | map({policy: .[0].policy, count: length}) | sort_by(-.count)[:10]'

# Просмотр отчетов для конкретного Namespace
kubectl get polr -n <namespace> -o custom-columns=NAME:.metadata.name,PASS:.summary.pass,FAIL:.summary.fail

# Экспорт PolicyReport в JSON для анализа
kubectl get polr -A -o json > /tmp/policyreports-$(date +%Y%m%d).json

# Проверка отсутствия PolicyReport для Namespace (политика не работает)
kubectl get polr -n <namespace> --no-headers 2>/dev/null | wc -l
```

---

## Дополнительная информация

### Стратегия масштабирования PostgreSQL

При использовании внешнего хранилища для Reports Server:
1.  **Партиционирование**: Настраивайте таблицы по `namespace` или `creation_timestamp`.
2.  **Retention Policy**: Настраивайте TTL (Time To Live) для исторических данных. Стандартное время хранения для аудита — 30–90 дней.
3.  **Индексация**: Обязательные индексы по полям `policy`, `resource_uid` и `result`.

**Минимальная схема PostgreSQL для Reports Server:**
```sql
-- Таблица результатов проверок
CREATE TABLE policy_report_results (
    id SERIAL PRIMARY KEY,
    report_name VARCHAR(255) NOT NULL,
    report_namespace VARCHAR(255),
    report_kind VARCHAR(50) NOT NULL,  -- 'PolicyReport' или 'ClusterPolicyReport'
    policy_name VARCHAR(255) NOT NULL,
    rule_name VARCHAR(255) NOT NULL,
    result VARCHAR(20) NOT NULL,       -- 'pass', 'fail', 'warn', 'error', 'skip'
    severity VARCHAR(20),
    category VARCHAR(100),
    message TEXT,
    resource_api_version VARCHAR(50),
    resource_kind VARCHAR(50),
    resource_name VARCHAR(255),
    resource_uid VARCHAR(100),
    resource_namespace VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Индексы для быстрого поиска
CREATE INDEX idx_prr_policy ON policy_report_results(policy_name);
CREATE INDEX idx_prr_result ON policy_report_results(result);
CREATE INDEX idx_prr_resource ON policy_report_results(resource_uid);
CREATE INDEX idx_prr_namespace ON policy_report_results(report_namespace);
CREATE INDEX idx_prr_created ON policy_report_results(created_at);

-- Партиционирование по времени (опционально, для больших объемов)
CREATE TABLE policy_report_results_202601 PARTITION OF policy_report_results
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
```

**Docker Compose для локального тестирования Reports Server:**
```yaml
version: '3.8'
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: kyverno_reports
      POSTGRES_USER: kyverno
      POSTGRES_PASSWORD: changeme
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql

volumes:
  postgres_data:
```

### Миграция с wgpolicyk8s на openreports.io

При обновлении Kyverno до 1.15+ рекомендуется переход на стандарт `openreports.io`. Процесс миграции:

1. **Экспорт текущих данных:**
```bash
# Экспорт всех PolicyReport
kubectl get polr -A -o json > /tmp/polr-backup.json

# Экспорт всех ClusterPolicyReport
kubectl get cpolr -o json > /tmp/cpolr-backup.json
```

2. **Установка новой версии Kyverno с поддержкой openreports.io:**
```bash
helm upgrade kyverno kyverno/kyverno \
  --namespace kyverno \
  --reuse-values \
  --set reportsController.reportsServer.enabled=true
```

3. **Проверка миграции:**
```bash
# Новые отчеты создаются в формате openreports.io
kubectl get polr -A -o json | jq '.items[] | select(.apiVersion=="openreports.io/v1alpha1") | .metadata.name'

# Старые отчеты (wgpolicyk8s) сохраняются для обратной совместимости
kubectl get polr -A -o json | jq '.items[] | select(.apiVersion=="wgpolicyk8s.io/v1") | .metadata.name'
```

### Оптимизация и решение проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Дрейф отчетов** | Сбой контроллера в момент удаления ресурса. | Запустите разовое полное сканирование (`BACKGROUND_SCAN_INTERVAL`). |
| **Высокая нагрузка на API** | Слишком частая запись AdmissionReport. | Ограничьте ресурсы для сканирования через `match` или `exclude` в политиках. |
| **Отчеты не обновляются** | Отсутствие прав у `reports-controller`. | Проверьте агрегированные роли ([см. additional.md](./additional.md)). |
| **PolicyReport пустой** | Политика не имеет `Audit` в `validationActions`. | Добавьте `Audit` в `validationActions` или используйте CEL-политики. |
| **AdmissionReport не отображается** | Отчет эфемерный (TTL по умолчанию 10 минут). | Используйте `PolicyReport` для постоянного хранения или настройте TTL. |
| **PostgreSQL connection refused** | Неверные данные для подключения или Firewall. | Проверьте Secret `kyverno-db-creds` и доступность PostgreSQL. |
| **Reports Server не запускается** | Невалидный `existingSecret` или отсутствие БД. | Проверьте Secret с ключами `user`/`password` и доступность PostgreSQL. |
| **Высокое потребление памяти** | Большой объем PolicyReport в etcd (>10K записей). | Включите Reports Server с внешней PostgreSQL или увеличьте `resources.limits.memory`. |
| **Сбои при background scan** | Слишком много ресурсов для сканирования. | Исключите системные Namespace через `namespaceSelector` в политиках. |

### См. также
- [Визуализация отчетов в Policy Reporter](./reporter.md)
- [Интеграция с Argo CD: Health Checks для отчетов](./argo-cd.md)
- [Агрегированные роли и права контроллера отчетов](./additional.md)
- [Установка Kyverno: настройка Reports Server](./install.md)
- [Определения и концепции: режимы Audit/Enforce](./policies/definitions_and_concepts.md)
- [Сценарии: Automation & Compliance через PolicyReport](./Scenarios/automation_compliance.md)
- [Сценарии: Очистка и верификация через PolicyReport](./Scenarios/cleanup_verification.md)
- [Официальная спецификация OpenReports](https://openreports.io)
- [Официальная спецификация wgpolicyk8s](https://github.com/kubernetes-sigs/wg-policy-prototypes)
