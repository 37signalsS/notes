# PrometheusRule — Концепции (CRD)

## Определения

**`kind: PrometheusRule`** — Custom Resource Definition (CRD) в Prometheus Operator для декларативного описания правил оповещения (alerting rules) и правил записи (recording rules). Operator преобразует эти ресурсы в Kubernetes ConfigMap, которые автоматически монтируются в экземпляры Prometheus Server или PrometheusAgent.

**Reconciliation Loop в PrometheusRule CRD** — процесс, при котором Operator отслеживает изменения в объекте `PrometheusRule` и связанных селекторах, обеспечивая своевременное обновление сгенерированных ConfigMap и их распространение на целевые инстансы Prometheus.

**API version:** `monitoring.coreos.com/v1`

> **Справочная информация:** Подробное описание синтаксиса PromQL и логики вычислений приведено в файле [Правила Recording и Alerting](../../../rules.md).

## Базовые концепции

### Архитектура управления правилами

PrometheusRule CRD является декларативным описанием правил. Operator отслеживает изменения ресурса и автоматически преобразует его в ConfigMap:

1.  **Валидация:** Admission Webhook проверяет синтаксис YAML и PromQL. Если правила некорректны, создание ресурса отклоняется с детальной ошибкой.
2.  **Генерация ConfigMap:** Operator обнаруживает ресурс и создает ConfigMap в том же пространстве имен с именем `<metadata.name>`.
3.  **Выборка селекторами:** Целевые инстансы Prometheus подхватывают ConfigMap через `ruleSelector` и `ruleNamespaceSelector` в своей спецификации.
4.  **Монтирование:** Оператор обновляет `StatefulSet` Prometheus, добавляя путь к ConfigMap в аргументы запуска `--rules.files=/etc/prometheus/rules/.../*.yaml`.
5.  **Синхронизация:** Контейнер `prometheus-config-reloader` внутри пода отслеживает изменения в смонтированных файлах и инициирует HTTP-запрос к `/-/reload`.
6.  **Привязка (Binding):** Через подресурс `status` можно отследить, какие инстансы Prometheus в данный момент используют этот набор правил.

### Принцип работы и жизненный цикл

1.  **Декларация:** Пользователь создает объект `PrometheusRule`.
2.  **Валидация:** Admission Webhook проверяет синтаксис PromQL. Если правила некорректны, создание ресурса будет отклонено с ошибкой.
3.  **Агрегация:** Operator обнаруживает ресурс и создает ConfigMap в том же пространстве имен.
4.  **Монтирование:** Оператор обновляет `StatefulSet` Prometheus, добавляя путь к ConfigMap в аргументы запуска.
5.  **Синхронизация:** Контейнер `prometheus-config-reloader` внутри пода отслеживает изменения в смонтированных файлах и инициирует HTTP-запрос к `/-/reload`.
6.  **Привязка (Binding):** Через подресурс `status` можно отследить, какие именно инстансы Prometheus в данный момент используют этот набор правил.

### Селекторы и изоляция конфигурации

Выборка правил осуществляется через селекторы в спецификации Prometheus:

| Селектор | Тип ресурса | Назначение |
| :--- | :--- | :--- |
| **`ruleSelector`** | `PrometheusRule` | Фильтрует правила по меткам (labels). |
| **`ruleNamespaceSelector`** | `PrometheusRule` | Определяет, в каких неймспейсах искать правила (`any: true` для всех доступных). |

> **Ловушка «Пустого селектора»:** Если `ruleSelector: {}` — выбираются ВСЕ `PrometheusRule` во ВСЕХ namespace, разрешенных `ruleNamespaceSelector`. Это может привести к загрузке нежелательных правил. Для изоляции используйте явные `matchLabels`.

### Взаимосвязь ресурсов

| Ресурс | Роль | Описание |
| :--- | :--- | :--- |
| **PrometheusRule** | Правила | Декларативное описание alerting и recording rules. |
| **Prometheus** | Инфраструктура | Управляет скрейпингом, хранилищем и вычислением правил. |
| **ConfigMap** | Связующее звено | Operator преобразует PrometheusRule в ConfigMap. |
| **Alertmanager** | Доставка | Получает алерты от Prometheus и маршрутизирует их. |

### Подресурс `status` и `Bindings`

PrometheusRule имеет подресурс `status`, который содержит список привязок (`bindings`) — инстансов Prometheus, которые успешно загрузили данный набор правил:

```yaml
status:
  bindings:
    - namespace: monitoring
      name: main
    - namespace: monitoring
      name: tenant-a
```

Если список `bindings` пуст — правила не загружены ни одним инстансом. Проверьте `ruleSelector` в объекте Prometheus.

### Новые возможности (2025–2026)

*   **`keep_firing_for`**: Удерживает алерт в состоянии `firing` в течение заданного времени после прекращения условия. Это решает проблему «дребезга» (flapping) и предотвращает закрытие инцидентов при кратковременных просадках метрик.
*   **`query_offset`**: Смещает окно вычисления всей группы правил в прошлое. Необходимо для корректной работы с системами, имеющими задержку записи (Remote Write, Thanos). Требует Prometheus >= v2.53.0.
*   **`limit`**: Ограничивает количество генерируемых временных серий (для recording) или алертов (для alerting) одной группой. Защищает память Prometheus от взрывного роста кардинальности.
*   **`alert_limit`**: Ограничивает количество активных алертов, сгенерированных группой. Если лимит превышен, новые алерты создаваться не будут.
*   **UTF-8 Mode (Prometheus 3.0+)**: При включении `nameValidationScheme: utf8` в ресурсе Prometheus (версия 3.0+) можно использовать любые символы UTF-8 (точки, тире и др.) в именах метрик и лейблов. Это критично для нативной совместимости с OpenTelemetry.
*   **CEL-валидация:** На уровне CRD проверяются типы данных, обязательные поля и базовые ограничения (например, `limit > 0`).

## Практические сценарии

### Сценарий 1: Отказоустойчивый алерт с защитой от дребезга

Пример использования `keep_firing_for` для стабилизации состояния алерта в Alertmanager.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: critical-app-alerts
  labels:
    release: monitoring
spec:
  groups:
    - name: api-health
      rules:
        - alert: HighErrorRate
          expr: rate(http_requests_total{status=~"5.."}[5m]) > 1
          for: 5m
          keep_firing_for: 10m  # Алерт остается активным 10 минут после исправления
          labels:
            severity: critical
          annotations:
            summary: "Высокий уровень 5xx ошибок"
            description: "Текущее значение: {{ $value }}"
```

### Сценарий 2: Правила записи с компенсацией задержек (query_offset)

Использование `query_offset` для агрегации данных, которые приходят с лагом в 1-2 минуты.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: aggregation-rules
spec:
  groups:
    - name: global-stats
      interval: 1m
      query_offset: 2m  # Смещение вычислений на 2 минуты назад
      limit: 1000       # Ограничение: не более 1000 серий на группу
      rules:
        - record: job:request_duration_seconds:p95
          expr: histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, job))
```

### Сценарий 3: Поддержка имен в стиле OpenTelemetry (UTF-8)

При включении `nameValidationScheme: utf8` в ресурсе Prometheus (версия 3.0+).

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: otel-compat-rules
spec:
  groups:
    - name: otel-metrics
      rules:
        - alert: ServiceDown
          # Допустимы точки и спецсимволы в именах лейблов без экранирования
          expr: up{service.name="auth-provider", cloud.region="us-east-1"} == 0
          for: 2m
```

### Сценарий 4: Мультитенантность и изоляция правил через namespaceSelector

Конфигурация для разделения правил разных команд (tenants) через отдельные namespace и селекторы.

```yaml
# Namespace: tenant-a-alerts
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: tenant-a-sli-rules
  labels:
    tenant: a
spec:
  groups:
    - name: tenant-a-slo
      interval: 1m
      rules:
        - record: tenant_a:http_requests:rate5m
          expr: sum(rate(http_requests_total{namespace="tenant-a"}[5m]))
```

```yaml
# Namespace: monitoring
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: tenant-a
spec:
  ruleSelector:
    matchLabels:
      tenant: a
  ruleNamespaceSelector:
    matchNames:
      - tenant-a-alerts
```

### Сценарий 5: Безопасное хранение правил и RBAC

Создание отдельного ServiceAccount и прав для пользователя, который применяет правила через CI/CD.

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: prometheus-rule-applier
  namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: prometheus-rule-applier
  namespace: monitoring
rules:
  - apiGroups: ["monitoring.coreos.com"]
    resources: ["prometheusrules"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: prometheus-rule-applier
  namespace: monitoring
subjects:
  - kind: ServiceAccount
    name: prometheus-rule-applier
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: prometheus-rule-applier
```

### Сценарий 6: Валидация правил в CI/CD пайплайне

Интеграция `promtool check rules` в pipeline для предотвращения деплоя невалидных правил.

```bash
#!/bin/bash
set -euo pipefail

# 1. Проверка синтаксиса YAML и PromQL
echo "Validating PrometheusRule files..."
find ./rules -name '*.yaml' -exec promtool check rules {} +

# 2. Проверка через admission webhook (dry-run)
echo "Dry-run applying to cluster..."
kubectl apply --dry-run=server -f ./rules/prometheusrule.yaml

# 3. Проверка конфликтов имен алертов
echo "Checking for duplicate alert names..."
grep -h 'alert:' ./rules/*.yaml | sort | uniq -d
```

### Сценарий 7: Recording rules для capacity planning и агрегации

Использование recording rules для предварительного вычисления capacity metrics и сложных агрегаций.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: capacity-planning-rules
spec:
  groups:
    - name: node-capacity
      interval: 5m
      limit: 500
      rules:
        - record: node:disk_utilization:ratio
          expr: 1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})
        - record: node:memory_utilization:ratio
          expr: 1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)
    - name: cluster-aggregates
      interval: 1m
      rules:
        - record: cluster:cpu_usage:percent
          expr: sum(rate(node_cpu_seconds_total{mode!="idle"}[5m])) / sum(node_cpu_seconds_total) * 100
```

### Сценарий 8: Отказоустойчивость и предотвращение дублирования правил

Настройка уникальных имен и пространств имен для правил в HA-конфигурации, чтобы избежать дублирования алертов при использовании Thanos или Federation.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: cluster-wide-alerts
  namespace: monitoring
spec:
  groups:
    - name: infrastructure
      interval: 1m
      rules:
        - alert: NodeDown
          expr: up{job="node-exporter"} == 0
          for: 5m
          labels:
            severity: critical
            team: infrastructure
          annotations:
            summary: "Узел {{ $labels.instance }} недоступен"
            runbook_url: "https://wiki.internal/runbooks/node-down"
```

## Дополнительная информация

### Требования к правам (RBAC)

**ServiceAccount и Role для приложения правил через CI/CD:**

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: prometheus-rule-applier
  namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus-rule-viewer
rules:
  - apiGroups: ["monitoring.coreos.com"]
    resources: ["prometheusrules"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: prometheus-rule-viewer
subjects:
  - kind: ServiceAccount
    name: prometheus-rule-applier
    namespace: monitoring
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: prometheus-rule-viewer
```

**Права для Prometheus Server (читает PrometheusRule):**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus-k8s-rules
rules:
  - apiGroups: ["monitoring.coreos.com"]
    resources: ["prometheusrules"]
    verbs: ["get", "list", "watch"]
```

> **Примечание:** При использовании Helm-чарта `kube-prometheus-stack` RBAC создается автоматически. Для ручного деплоя или кастомных манифестов — создавайте объекты явно.

### Основные параметры спецификации

| Параметр | Описание | Особенности |
| :--- | :--- | :--- |
| **`groups[].name`** | Имя группы правил. | Должно быть уникальным в пределах ресурса. |
| **`groups[].interval`** | Частота вычисления группы. | Если не задан, используется `evaluationInterval` из Prometheus. |
| **`groups[].query_offset`** | Временное смещение. | Минимизирует "дыры" при Remote Write. Требует Prometheus >= v2.53.0. |
| **`groups[].limit`** | Лимит рядов/алертов. | Предотвращает OOM при ошибках в селекторах. |
| **`groups[].rules[].record`** | Имя создаваемой метрики. | Для recording rules. Должно быть валидным именем метрики. |
| **`groups[].rules[].alert`** | Имя алерта. | Для alerting rules. Уникально в пределах инстанса. |
| **`groups[].rules[].expr`** | PromQL-выражение. | Основная логика правила. Валидируется при создании. |
| **`groups[].rules[].for`** | Время ожидания перед firing. | Фильтрует пики. Рекомендуется `for >= 3 * scrape_interval`. |
| **`groups[].rules[].keep_firing_for`** | Удержание состояния. | Параметр уровня конкретного правила. |
| **`groups[].rules[].labels`** | Дополнительные метки. | Используются для маршрутизации и фильтрации. |
| **`groups[].rules[].annotations`** | Метаданные алерта. | Описание, ссылки на runbook, шаблоны. |
| **`groups[].partial_response_strategy`** | Стратегия при частичном ответе. | Используется в Thanos Ruler (`warn` или `abort`). |
| **`groups[].rules[].alert_limit`** | Лимит алертов на правило. | Защита от взрывного роста алертов. |

### Ограничения и крайние случаи

1.  **Лимит размера ConfigMap (1MB):** Итоговый ConfigMap с правилами ограничен 1 MiB (ограничение etcd). При превышении Operator вернет ошибку. Решение: разбиение на несколько `PrometheusRule` по namespace или командам.
2.  **Пустой селектор vs жесткий фильтр:** `ruleSelector: {}` в Prometheus выбирает ВСЕ правила во всех разрешенных namespace. Это может привести к загрузке нежелательных правил. Используйте явные `matchLabels` для изоляции.
3.  **CEL-валидация:** CEL-выражения проверяют только синтаксис, но не семантику PromQL. Например, невалидный PromQL в `expr` будет принят CRD, но отклонен при вычислении.
4.  **Ограничение `limit`:** Если `groups[].limit` превышен, ВСЕ recording rules в группе падают с ошибкой. Алерты при превышении `alert_limit` создаваться не будут (логируется ошибка).
5.  **Зависимость от evaluation_interval:** Если `groups[].interval` не задан, используется глобальный `evaluation_interval` из Prometheus. Несоответствие интервалов между группами может привести к гонкам данных при использовании recording rules между группами.
6.  **Имена правил:** Имена `record` и `alert` должны быть уникальными в пределах инстанса Prometheus. Дублирование имен приводит к неопределенному поведению.
7.  **UTF-8 Mode:** При включении `nameValidationScheme: utf8` в Prometheus 3.0+ можно использовать точки и спецсимволы в именах метрик, но старые дашборды и алерты могут не поддерживать такой синтаксис.
8.  **Горячая перезагрузка:** Изменения в PrometheusRule применяются с задержкой до 60-90 секунд (время обнаружения изменений ConfigMap контейнером config-reloader).

### Валидация работоспособности

После создания или обновления ресурса `PrometheusRule` выполните проверки:

```bash
# 1. Проверка статуса ресурса и условий
kubectl get prometheusrule critical-app-alerts -n monitoring -o yaml

# 2. Проверка привязок (Bindings)
kubectl get prometheusrule critical-app-alerts -n monitoring -o jsonpath='{.status.bindings[*].name}'

# 3. Проверка сгенерированного ConfigMap
kubectl get configmap critical-app-alerts -n monitoring -o yaml

# 4. Проверка логов Operator на предмет ошибок reconciliation
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator --tail=100 | grep -i "prometheusrule" | tail -20

# 5. Проверка логов config-reloader
kubectl logs -n monitoring prometheus-main-0 -c config-reloader --tail=50

# 6. Проверка загрузки правил в Prometheus UI
kubectl port-forward -n monitoring svc/prometheus-main 9090:9090
curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[] | select(.name == "api-health")'
```

### Типичные проблемы и устранение неполадок

#### Проблема 1: PrometheusRule не загружается в Prometheus

*   **Причина:** Несовпадение лейблов между `ruleSelector` в объекте Prometheus и `labels` в PrometheusRule.
*   **Диагностика:**
    ```bash
    kubectl get prometheusrule --all-namespaces -o wide | grep release
    kubectl get prometheus main -n monitoring -o yaml | grep -A5 ruleSelector
    ```
*   **Решение:** Добавьте соответствующий лейбл в `PrometheusRule.metadata.labels` или измените `ruleSelector` в объекте Prometheus.

#### Проблема 2: Алерт не срабатывает

*   **Причина:** Ошибка в PromQL, неверный `for`/`keep_firing_for`, или метрика отсутствует.
*   **Диагностика:**
    ```bash
    # Проверка синтаксиса PromQL
    promtool check rules prometheusrule.yaml

    # Проверка метрики
    kubectl exec -n monitoring prometheus-main-0 -- wget -qO- 'http://localhost:9090/api/v1/query?query=rate(http_requests_total[5m])' | jq .
    ```
*   **Решение:** Исправьте PromQL, проверьте наличие метрик, настройте `for` и `keep_firing_for`.

#### Проблема 3: Дублирование алертов

*   **Причина:** Несколько инстансов Prometheus загружают один и тот же PrometheusRule (например, в HA-паре без Thanos).
*   **Диагностика:**
    ```bash
    curl -s http://localhost:9090/api/v1/alerts | jq '.data.alerts[] | select(.labels.alertname == "HighErrorRate")'
    ```
*   **Решение:** Используйте `external_labels` для дедупликации или настройте Alertmanager `group_by` для объединения алертов.

#### Проблема 4: ConfigMap превысил лимит 1MB

*   **Причина:** Слишком большое количество правил или большие аннотации.
*   **Диагностика:**
    ```bash
    kubectl get configmap critical-app-alerts -n monitoring -o jsonpath='{.data.*}' | wc -c
    ```
*   **Решение:** Разбейте правила на несколько `PrometheusRule` по namespace или функциональному назначению.

#### Проблема 5: Правила не обновляются после изменения

*   **Причина:** Config-reloader не обнаружил изменения или произошла ошибка перезагрузки.
*   **Диагностика:**
    ```bash
    kubectl logs -n monitoring prometheus-main-0 -c config-reloader --tail=50
    ```
*   **Решение:** Проверьте права доступа к ConfigMap, убедитесь в отсутствии ошибок синтаксиса.

#### Проблема 6: Recording rule создает метрику с неверным именем

*   **Причина:** Использование невалидных символов в имени `record` или конфликт с существующими метриками.
*   **Диагностика:**
    ```bash
    kubectl exec -n monitoring prometheus-main-0 -- wget -qO- 'http://localhost:9090/api/v1/label/__name__/values' | jq '.data[] | select(startswith("job:request_duration"))'
    ```
*   **Решение:** Используйте префикс с названием команды/сервиса (например, `team:metric:operations`), проверьте уникальность имени.

### Лучшие практики

1.  **Фиксируйте имена и версии:** Используйте осмысленные имена для `PrometheusRule`, указывающие на команду/сервис (например, `team-api-sli-rules`).
2.  **Группируйте логически:** Размещайте связанные правила (recording + зависимые alerting) в одной группе для гарантии порядка вычисления.
3.  **Разделяйте по namespace:** Используйте отдельные namespace для разных команд/tenant'ов, чтобы избежать пересечения селекторов.
4.  **Используйте `for` и `keep_firing_for`:** Всегда добавляйте `for: 3m` минимум для фильтрации шума. Используйте `keep_firing_for` для предотвращения преждевременного закрытия инцидентов.
5.  **Храните в Git:** Все правила должны находиться в репозитории и доставляться через CI/CD. Это обеспечивает аудит и возможность отката.
6.  **Тестируйте перед деплоем:** Используйте `promtool check rules` и dry-run в CI пайплайне.
7.  **Именуйте recording rules по стандарту:** Используйте паттерн `level:metric:operations` (например, `job:http_requests:rate5m`).
8.  **Ограничивайте кардинальность:** Используйте `groups[].limit` для защиты от взрывного роста серий при опечатках в селекторах.
9.  **Используйте `query_offset` для Remote Write:** При интеграции с Thanos или Remote Write добавляйте `query_offset` для компенсации задержки доставки данных.
10. **Мониторьте мета-мониторинг:** Настройте алерты на `prometheus_rule_group_last_duration_seconds` и `prometheus_rule_evaluation_failures_total` для отслеживания здоровья самих правил.
11. **Используйте `alert_limit`:** Для критически важных сервисов ограничьте количество алертов, чтобы предотвратить Alertstorm при массовом отказе.
12. **Синхронизируйте интервалы:** Если recording rule из одной группы используется в alerting rule другой группы — синхронизируйте их `interval`, чтобы избежать гонок данных.

### См. также

*   **[Prometheus CRD](./prometheus.md)** — настройка селекторов и схем валидации имен.
*   **[Alertmanager CRD](./alertmanager.md)** — маршрутизация уведомлений.
*   **[Promtool и лучшие практики](../../../promtool_and_best_practices.md)** — рекомендации по написанию эффективных правил.
*   **[Правила Recording и Alerting](../../../rules.md)** — теория и синтаксис PromQL для правил.

### См. также (внешние)

* [Prometheus Rule Specification (Official)](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
* [Prometheus Operator API Documentation (v1)](https://prometheus-operator.dev/docs/operator/api/#monitoring.coreos.com/v1.PrometheusRule)
