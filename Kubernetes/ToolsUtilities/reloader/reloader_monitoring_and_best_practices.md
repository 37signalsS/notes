# Reloader — Мониторинг, отладка и лучшие практики

## Определения

**Мониторинг Reloader** — совокупность методов и инструментов для наблюдения за состоянием контроллера, анализа метрик производительности и диагностики процессов автоматической перезагрузки рабочих нагрузок.

**Лучшие практики (Best Practices)** — набор рекомендованных конфигураций и архитектурных подходов, обеспечивающих стабильность, безопасность и предсказуемость работы Reloader в высоконагруженных Kubernetes-кластерах.

**Основной источник:** [Обзор и концепции Reloader](./reloader_overview.md)

---

## Основные концепции

### Точки доступа контроллера (Endpoints)

Reloader предоставляет стандартные HTTP-эндпоинты для проверки состояния и сбора данных. По умолчанию используется порт `9090`.

| Эндпоинт | Назначение | Описание |
| :--- | :--- | :--- |
| `/healthz` | Liveness Probe | Проверка жизнеспособности процесса |
| `/readyz` | Readiness Probe | Готовность контроллера к обработке событий API |
| `/metrics` | Prometheus Metrics | Экспорт технических метрик в формате OpenMetrics |

### Ключевые метрики производительности

Для версии v1.4.x (2026) рекомендуется отслеживать следующие показатели:

**Счётчики (Counters):**

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `reloader_success_reload_total` | Counter | Общее количество успешно инициированных Rolling Update |
| `reloader_failure_reload_total` | Counter | Количество отказов (ошибки RBAC, квоты, недоступность API) |
| `reloader_resource_watch_total` | Counter | Количество отслеживаемых объектов (ConfigMap/Secret) |
| `reloader_reconcile_total` | Counter | Общее количество операций согласования |
| `reloader_reconcile_errors_total` | Counter | Ошибки согласования |

**Метрики производительности (Histograms):**

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `reloader_reconcile_duration_seconds` | Histogram | Время выполнения одной операции согласования |
| `reloader_reload_duration_seconds` | Histogram | Время от обнаружения изменения до запуска Rolling Update |
| `reloader_event_processing_duration_seconds` | Histogram | Время обработки события API |

**Системные метрики (Gauges):**

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `workqueue_depth` | Gauge | Текущая глубина очереди задач |
| `workqueue_queue_duration_seconds` | Gauge | Время ожидания в очереди |
| `reloader_active_reconcile` | Gauge | Количество текущих операций согласования |
| `reloader_watched_resources` | Gauge | Количество отслеживаемых ресурсов |
| `reloader_ignored_resources` | Gauge | Количество игнорируемых ресурсов |

### Уровни логирования

Настройка через аргумент `--log-level`:

| Уровень | Описание | Когда использовать |
| :--- | :--- | :--- |
| `error` | Только критические ошибки | Production, минимальный шум |
| `warn` | Предупреждения | Production, мониторинг аномалий |
| `info` | Основные операции | **Рекомендуется для Production** |
| `debug` | Детальная трассировка | Отладка, Development |

**Пример вывода уровня `info`:**

```
level=info msg="Triggering rolling upgrade for Deployment 'app' in namespace 'prod'"
level=info msg="Successfully triggered rolling upgrade for Deployment 'app' in namespace 'prod'"
level=info msg="Watching resource ConfigMap in namespace 'prod'"
```

**Пример вывода уровня `debug`:**

```
level=debug msg="Processing event ADDED for ConfigMap 'app-config' in namespace 'prod'"
level=debug msg="Matching annotations for Deployment 'app': auto=true"
level=debug msg="Resource 'app-config' is referenced by Deployment 'app' via envFrom"
level=debug msg="Triggering rolling upgrade for Deployment 'app' in namespace 'prod'"
```

---

## Практические сценарии

### Сценарий 1: Базовая диагностика и проверка логов

При обнаружении того, что приложение не перезапустилось после изменения конфига:

```bash
# 1. Проверка состояния контроллера
kubectl get pods -n reloader-system -l app=reloader

# 2. Поиск события срабатывания в логах
kubectl logs -n reloader-system -l app=reloader | grep -i "triggering"
# → result: level=info msg="Triggering rolling upgrade for Deployment 'app' in namespace 'prod'"

# 3. Проверка последних событий Reloader
kubectl get events -n reloader-system --sort-by='.lastTimestamp' | tail -20

# 4. Проверка аннотаций целевого Deployment
kubectl get deployment <name> -n <namespace> -o jsonpath='{.metadata.annotations}' | jq .
```

### Сценарий 2: Тестирование прав RBAC (self-check)

Частая причина отказов (`failure_reload`) — нехватка прав в целевом пространстве имён:

```bash
# Может ли Reloader обновлять ресурсы в namespace 'business'?
kubectl auth can-i patch deployments --as=system:serviceaccount:reloader-system:reloader -n business
# → result: yes

# Может ли Reloader читать ConfigMap?
kubectl auth can-i get configmaps --as=system:serviceaccount:reloader-system:reloader -n business
# → result: yes

# Проверка ClusterRole (если используется)
kubectl auth can-i list deployments --as=system:serviceaccount:reloader-system:reloader --cluster-role
# → result: yes
```

### Сценарий 3: Отладка глобального игнорирования (v1.4.19+)

Если приложение помечено `reloader.stakater.com/ignore: "true"`, но всё равно перезапускается:

1.  Проверьте флаги запуска контроллера.
2.  Если установлен `--ignore-annotation=true`, Reloader будет игнорировать аннотацию `ignore` на ресурсах.
3.  В логах это будет отмечено как принудительное обновление по политике платформы.

```bash
# Проверка текущих флагов контроллера
kubectl get deployment reloader -n reloader-system -o jsonpath='{.spec.template.spec.containers[0].args}'
# → result: ["--reload-strategy=annotations","--log-level=info"]

# Проверка логов на принудительные обновления
kubectl logs -n reloader-system -l app=reloader | grep -i "ignore\|force"
```

### Сценарий 4: Диагностика Secrets Store CSI Driver

Если секреты ротируются во внешнем хранилище (Vault), но Reloader не реагирует:

```bash
# 1. Проверка наличия статусов CSI драйвера
kubectl get secretproviderclasspodstatuses -n <namespace>
# → result: Должен присутствовать статус, привязанный к вашему поду

# 2. Проверка статуса конкретного Pod
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.status.conditions[?(@.type=="Ready")].message}'

# 3. Проверка Secret, созданного CSI
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.metadata.labels}' | jq .

# 4. Проверка логов CSI-драйвера
kubectl logs -n kube-system -l app=secrets-store-csi-driver | grep -i "sync\|rotate"
```

### Сценарий 5: Проверка доступности метрик

```bash
# 1. Проверка Service
kubectl get svc -n reloader-system -l app=reloader

# 2. Прямой запрос к метрикам (port-forward)
kubectl port-forward svc/reloader -n reloader-system 9090:9090 &
curl -s http://localhost:9090/metrics | head -30

# 3. Проверка в Prometheus
# → result: В Prometheus должен появиться target с job="reloader"

# 4. Проверка количества отслеживаемых ресурсов
curl -s http://localhost:9090/metrics | grep reloader_watched_resources
# → result: reloader_watched_resources 42
```

### Сценарий 6: Диагностика несрабатывания перезапуска

Пошаговый чек-лист:

```bash
# 1. Проверка аннотаций на целевом ресурсе
kubectl get deployment <name> -n <namespace> -o jsonpath='{.metadata.annotations}' | jq .

# 2. Проверка ссылок на ConfigMap/Secret
kubectl get deployment <name> -n <namespace> -o jsonpath='{.spec.template.spec}' | jq '.containers[].envFrom, .containers[].volumeMounts, .volumes'

# 3. Проверка, что Reloader видит изменения
kubectl logs -n reloader-system -l app=reloader --tail=100 | grep -i "configmap\|secret"

# 4. Проверка RBAC
kubectl auth can-i patch deployments --as=system:serviceaccount:reloader-system:reloader -n <namespace>

# 5. Проверка лимитов ресурсов
kubectl describe deployment reloader -n reloader-system | grep -A5 "Limits\|Requests"
```

### Сценарий 7: Анализ частоты перезапусков

```bash
# 1. Получение событий перезапусков за последний час
kubectl get events --field-selector reason=ReloaderTriggered --since=1h -n <namespace>

# 2. Подсчёт перезапусков по Deployment
kubectl get events --field-selector reason=ReloaderTriggered --since=24h -n <namespace> | \
  awk '{print $6}' | sort | uniq -c | sort -rn

# 3. Проверка через Prometheus (если настроен)
# sum(rate(reloader_success_reload_total[5m])) by (namespace, deployment)

# 4. Анализ времени между перезапусками
kubectl get events --field-selector reason=ReloaderTriggered --sort-by='.lastTimestamp' -n <namespace>
```

### Сценарий 8: Мониторинг здоровья контроллера

```bash
# 1. Проверка Liveness Probe
kubectl exec -it <reloader-pod> -n reloader-system -- wget -qO- http://localhost:9090/healthz
# → result: ok

# 2. Проверка Readiness Probe
kubectl exec -it <reloader-pod> -n reloader-system -- wget -qO- http://localhost:9090/readyz
# → result: ok

# 3. Проверка использования ресурсов
kubectl top pods -n reloader-system -l app=reloader

# 4. Проверка потребления памяти
kubectl exec -it <reloader-pod> -n reloader-system -- cat /proc/1/status | grep VmRSS
```

---

## Лучшие практики

### 1. Безопасность и изоляция

| Практика | Описание | Применение |
| :--- | :--- | :--- |
| **Scoped RBAC** | Использование `Role` вместо `ClusterRole` в мультитенантных кластерах | Рекомендуется для всех кластеров |
| **User Namespaces** | Включение `hostUsers: false` (v1.4+) для предотвращения атак на уровне ядра | Рекомендуется для Production |
| **NetworkPolicies** | Ограничение входящего трафика к порту `9090` | Рекомендуется для всех кластеров |
| **Security Context** | Запуск от непривилегированного пользователя (non-root) | Рекомендуется для Production |
| **ReadOnlyRootFS** | Только для чтения файловой системы контейнера | Рекомендуется для Production |

**Пример безопасного манифеста:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: reloader
  namespace: reloader-system
spec:
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 65534
        fsGroup: 65534
      containers:
        - name: reloader
          image: stakater/reloader:v1.4.19
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
            seccompProfile:
              type: RuntimeDefault
          resources:
            limits:
              cpu: 200m
              memory: 256Mi
            requests:
              cpu: 100m
              memory: 128Mi
```

### 2. Производительность в больших кластерах

| Практика | Описание | Оптимальные значения |
| :--- | :--- | :--- |
| **Namespace Selector** | Использование `--namespaces-to-select` или `--namespaces-to-ignore` | Уменьшает нагрузку на API Server |
| **Debounce** | Аннотация `pause-period` для группировки изменений | `1m` для Dev, `5m` для Production |
| **Resource Limits** | Ограничение CPU и RAM контроллера | `200m/256Mi` для <1000 ресурсов |
| **Replicas** | Запуск 2+ респлик для HA | 2 респлики для Production |

**Оптимальные настройки для разных размеров кластеров:**

| Размер | Ресурсы | Namespace Selector | Debounce | Реплики |
| :--- | :--- | :--- | :--- | :--- |
| **Малый** (<100 ресурсов) | 100m/128Mi | Не требуется | 0 | 1 |
| **Средний** (100-1000) | 200m/256Mi | `--namespaces-to-select` | 1m | 2 |
| **Большой** (1000-5000) | 500m/512Mi | `--namespaces-to-select` | 5m | 2 |
| **Очень большой** (>5000) | 1000m/1Gi | `--namespaces-to-ignore` | 15m | 3 |

### 3. GitOps-совместимость (ArgoCD / Flux)

| Практика | Описание | Применение |
| :--- | :--- | :--- |
| **Annotation Strategy** | Использование `--reload-strategy=annotations` | Рекомендуется для ArgoCD |
| **Ignore Differences** | Добавление `reloader.stakater.com/last-reloaded-from` в ignoreDifferences | Обязательно для ArgoCD |
| **Flux PostBuild** | Использование `postBuild.substituteFrom` для динамических переменных | Рекомендуется для Flux |

**ArgoCD Application:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/template/metadata/annotations/reloader.stakater.com~1last-reloaded-from
```

**Flux Kustomization:**

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: my-app
spec:
  postBuild:
    substituteFrom:
      - kind: ConfigMap
        name: cluster-config
```

### 4. Надёжность и отказоустойчивость

| Практика | Описание | Применение |
| :--- | :--- | :--- |
| **PodDisruptionBudget** | Минимум 1 реплика всегда доступна | Обязательно для Production |
| **Anti-Affinity** | Распределение реплик по нодам | Рекомендуется для Production |
| **Probes** | Liveness и Readiness пробы | Обязательно для всех контроллеров |
| **Resource Requests** | Гарантированные ресурсы | Обязательно для Production |

**Пример PodDisruptionBudget:**

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: reloader-pdb
  namespace: reloader-system
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: reloader
```

**Пример Anti-Affinity:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: reloader
  namespace: reloader-system
spec:
  replicas: 2
  template:
    spec:
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchExpressions:
                    - key: app
                      operator: In
                      values: ["reloader"]
                topologyKey: kubernetes.io/hostname
```

### 5. Логирование и аудит

| Практика | Описание | Применение |
| :--- | :--- | :--- |
| **Structured Logging** | Использование JSON-формата для парсинга | Рекомендуется для Production |
| **Log Rotation** | Настройка ротации логов в container runtime | Рекомендуется для всех контроллеров |
| **Audit Events** | Включение аудита Kubernetes API для отслеживания изменений | Рекомендуется для Production |
| **Correlation IDs** | Добавление уникальных идентификаторов для трассировки | Рекомендуется для больших кластеров |

**Пример JSON-логов:**

```json
{
  "level": "info",
  "ts": "2026-09-03T10:30:00Z",
  "msg": "Triggering rolling upgrade",
  "resource": "Deployment",
  "name": "app",
  "namespace": "prod",
  "configmaps": ["app-config"],
  "secrets": ["app-secrets"],
  "reason": "configmap-change"
}
```

### 6. Обновление и откат

| Практика | Описание | Применение |
| :--- | :--- | :--- |
| **Helm History** | Сохранение истории версий для отката | Обязательно для Production |
| **Canary Update** | Обновление одной реплики перед остальными | Рекомендуется для Production |
| **Health Checks** | Проверка состояния после обновления | Обязательно для Production |
| **Rollback Strategy** | План отката при проблемах | Обязательно для Production |

**Пример обновления через Helm:**

```bash
# Обновление с проверкой
helm upgrade reloader stakater/reloader \
  --namespace reloader-system \
  --reuse-values \
  --wait \
  --timeout 5m

# Проверка состояния
kubectl get pods -n reloader-system -l app=reloader
kubectl logs -n reloader-system -l app=reloader --tail=20

# Откат при проблемах
helm rollback reloader <revision> -n reloader-system
```

---

## Мониторинг через Prometheus и Grafana

Детальная настройка мониторинга, алертинга и визуализации вынесена в отдельный файл:

**→ [Reloader — Интеграция с Prometheus и Grafana](./reloader_prometheus_integration.md)**

Включает:
- ServiceMonitor конфигурации
- PrometheusRule (alerting и recording rules)
- Grafana Dashboard панели и queries
- Проверка работоспособности мониторинга

---

## SLI/SLO для Reloader как платформенного сервиса

### Определения

**SLI (Service Level Indicator)** — количественный показатель качества сервиса Reloader. Измеряется через Prometheus метрики.

**SLO (Service Level Objective)** — целевое значение SLI за определённый период. Нарушение SLO приводит к расходованию error budget.

### Ключевые SLI для Reloader

| SLI | Метрика | Формула | Описание |
| :--- | :--- | :--- | :--- |
| **Доступность контроллера** | `kube_deployment_status_replicas_available` | ratio of available/replicas | Контроллер должен быть доступен и обрабатывать события |
| **Успешность перезапусков** | `reloader_success_reload_total`, `reloader_failure_reload_total` | success / (success + failure) | Перезапуски должны завершаться успешно |
| **Латентность обнаружения** | `reloader_event_processing_duration_seconds` | p99 за окно | Время от изменения до начала обработки |
| **Латентность перезапуска** | `reloader_reconcile_duration_seconds` | p95 за окно | Время от обнаружения до patch Deployment |
| **Очередь задач** | `workqueue_depth` | avg за окно | Глубина очереди не должна расти бесконечно |

### Рекомендуемые SLO

| SLO | Целевое значение | Error Budget (30 дней) |
| :--- | :--- | :--- |
| Доступность контроллера | >= 99.9% | ~43 мин простоя |
| Успешность перезапусков | >= 99.5% | ~3.6 ч.failed restarts |
| Латентность обнаружения (p99) | < 5 сек | — |
| Латентность согласования (p95) | < 10 сек | — |
| Глубина очереди | < 50 элементов | — |

### Правила алертинга на SLO (Error Budget Burn Rate)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: reloader-slo-alerts
  namespace: reloader-system
  labels:
    release: prometheus-stack
spec:
  groups:
    - name: reloader-slo
      rules:
        # Быстрое выгорание (14.4x за 1 час) — критично
        - alert: ReloaderErrorBudgetBurnFast
          expr: |
            (
              rate(reloader_failure_reload_total[1h]) /
              rate(reloader_success_reload_total[1h])
            ) > (14.4 * 0.005)
          for: 2m
          labels:
            severity: critical
          annotations:
            summary: "Reloader: быстрое выгорание error budget"
            description: "Error budget будет исчерпан за < 2 дня при текущей скорости ошибок"

        # Медленное выгорание (6x за 3 дня) — предупреждение
        - alert: ReloaderErrorBudgetBurnSlow
          expr: |
            (
              rate(reloader_failure_reload_total[3d]) /
              rate(reloader_success_reload_total[3d])
            ) > (6 * 0.005)
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "Reloader: медленное выгорание error budget"
            description: "Error budget будет исчерпан за < 30 дней при текущей скорости ошибок"
```

---

## Observability beyond metrics (logs, traces, audit)

### Структурированное логирование

Reloader поддерживает JSON-формат логов через `--log-level=info`. Для интеграции с ELK/Loki:

```yaml
# Рекомендуемая конфигурация для production
args:
  - --log-level=info
  # Дляvelopment/debug:
  # - --log-level=debug
```

**Формат логов Reloader:**

```json
{
  "level": "info",
  "ts": "2026-09-10T10:30:00Z",
  "msg": "Triggering rolling upgrade",
  "resource": "Deployment",
  "name": "my-app",
  "namespace": "production",
  "configmaps": ["app-config"],
  "secrets": ["app-secrets"],
  "strategy": "annotations",
  "reason": "configmap-change"
}
```

**Корреляция с внешними системами:**

| Система | Интеграция | Формат |
| :--- | :--- | :--- |
| **Loki** | Сбор логов через Promtail/Alloy | JSON labels: `namespace`, `app`, `resource` |
| **ELK (Elasticsearch)** | Filebeat/Fluentd | Structured log с `trace_id` для корреляции |
| **Jaeger/Tempo** | Распределённая трассировка | Reloader не генерирует трейсы, но можно добавить через OTel SDK |

### Audit Trail для Compliance

Kubernetes API Server предоставляет аудит-логи для отслеживания всех patch-операций Reloader:

```yaml
# Audit Policy для фиксации действий Reloader
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
  # Логирование всех patch-операций к Deployment от Reloader
  - level: RequestResponse
    users: ["system:serviceaccount:reloader-system:reloader"]
    resources:
      - group: "apps"
        resources: ["deployments", "daemonsets", "statefulsets"]
    verbs: ["update", "patch"]

  # Логирование чтения Secret от Reloader
  - level: Metadata
    users: ["system:serviceaccount:reloader-system:reloader"]
    resources:
      - group: ""
        resources: ["secrets"]
    verbs: ["get", "list", "watch"]
```

**Проверка аудит-логов:**

```bash
# Найти все действия Reloader в аудит-логах
kubectl get --raw /audit/kubernetes.io/v1/events | \
  jq '.items[] | select(.user.username == "system:serviceaccount:reloader-system:reloader")' | \
  jq -r '[.verb, .objectRef.resource, .objectRef.namespace, .objectRef.name, .stageTimestamp] | @tsv'
```

### Интеграция с OpenTelemetry (Tracing)

Reloader нативно не поддерживает distributed tracing, но его можно интегрировать через:

1. **OTel Collector как sidecar** — сбор метрик Reloader через OTLP
2. **Custom Exporter** — экспорт событий перезапуска как spans в Jaeger/Tempo

```yaml
# Пример OTel Collector sidecar для Reloader
apiVersion: apps/v1
kind: Deployment
metadata:
  name: reloader
  namespace: reloader-system
spec:
  template:
    spec:
      containers:
        - name: reloader
          image: ghcr.io/stakater/reloader:v1.4.19
          ports:
            - containerPort: 9090
        - name: otel-collector
          image: otel/opentelemetry-collector-contrib:latest
          args:
            - --config=/etc/otelcol/config.yaml
          volumeMounts:
            - name: otel-config
              mountPath: /etc/otelcol
      volumes:
        - name: otel-config
          configMap:
            name: reloader-otel-config
```

---

## Диагностические команды

### Полный набор диагностики

```bash
# 1. Состояние контроллера
kubectl get pods -n reloader-system -l app=reloader -o wide

# 2. Ресурсы контроллера
kubectl top pods -n reloader-system -l app=reloader

# 3. Логи (последние 100 строк)
kubectl logs -n reloader-system -l app=reloader --tail=100

# 4. Аннотации контроллера
kubectl get deployment reloader -n reloader-system -o jsonpath='{.spec.template.metadata.annotations}' | jq .

# 5. Service и Endpoint
kubectl get svc -n reloader-system -l app=reloader
kubectl get endpoints -n reloader-system -l app=reloader

# 6. RBAC
kubectl auth can-i patch deployments --as=system:serviceaccount:reloader-system:reloader -n <namespace>

# 7. События
kubectl get events -n reloader-system --sort-by='.lastTimestamp' | tail -20

# 8. Метрики (port-forward)
kubectl port-forward svc/reloader -n reloader-system 9090:9090 &
curl -s http://localhost:9090/metrics | grep -E "^reloader_|^workqueue_"
```

### Быстрая проверка работоспособности

```bash
# Health checks
kubectl exec -it <reloader-pod> -n reloader-system -- wget -qO- http://localhost:9090/healthz
kubectl exec -it <reloader-pod> -n reloader-system -- wget -qO- http://localhost:9090/readyz

# Проверка конфигурации
kubectl get deployment reloader -n reloader-system -o jsonpath='{.spec.template.spec.containers[0].args}' | jq .

# Проверка версии
kubectl get deployment reloader -n reloader-system -o jsonpath='{.spec.template.spec.containers[0].image}'
```

---

## Чек-лист для Production

### Перед запуском

- [ ] Установлен PodDisruptionBudget (`minAvailable: 1`)
- [ ] Настроены ресурсы (CPU/RAM limits и requests)
- [ ] Включены Liveness и Readiness пробы
- [ ] Настроен anti-affinity для HA
- [ ] Включен `--reload-strategy=annotations` для GitOps
- [ ] Добавлена аннотация в `ignoreDifferences` ArgoCD
- [ ] Настроен ServiceMonitor для Prometheus
- [ ] Настроены alerting rules
- [ ] Включен structured logging
- [ ] Настроена ротация логов

### После запуска

- [ ] Проверены метрики в Prometheus
- [ ] Импортирован Grafana dashboard
- [ ] Проверены alerting rules
- [ ] Протестирован перезапуск при изменении ConfigMap
- [ ] Протестирован перезапуск при изменении Secret
- [ ] Проверены RBAC для целевых namespace
- [ ] Проверена доступность health check endpoints
- [ ] Документирован процесс отката

---

## См. также

- [Установка и настройка Reloader](./reloader_installation.md)
- [Практические сценарии использования](./reloader_usage_scenarios.md)
- [Интеграция с Prometheus и Grafana](./reloader_prometheus_integration.md)
- [Безопасность Reloader](./reloader_security.md)
- [Runbooks и реагирование на инциденты](./reloader_runbooks.md)
