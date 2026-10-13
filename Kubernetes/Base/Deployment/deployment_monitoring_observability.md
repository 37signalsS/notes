# Мониторинг и наблюдаемость Deployment

**Актуально для:** Kubernetes 1.30–1.32+, kube-state-metrics 2.x, Prometheus 2.x/3.x

Практическое руководство для инженеров DevOps, SRE и системных администраторов по мониторингу и наблюдаемости (observability) объектов Deployment в Kubernetes. Включает детальный разбор метрик контроллера kube-state-metrics, ресурсов cgroups v2/cAdvisor, промышленные правила PrometheusRule, расчет SLI/SLO, CLI-диагностику, трассировку, устранение неполадок сбора телеметрии и интеграцию проверок в CI/CD для on-premise и bare-metal инфраструктуры без привязки к проприетарным облачным сервисам.

## Предварительные требования (Prerequisites)

- Функционирующий кластер Kubernetes v1.30+ (vanilla/kubeadm/RKE2 на bare-metal или виртуальных машинах).
- Развернутый стек мониторинга на базе Prometheus v2.x/v3.x и Prometheus Operator (или kube-prometheus-stack).
- Установленный и доступный компонент `kube-state-metrics` (KSM) версии 2.9+ с включенным коллектором ресурсов `deployments`.
- Установленный CLI-клиент `kubectl` с правами оператора на чтение объектов `deployments`, `replicasets`, `pods`, `events` в целевых пространствах имен.
- Системные утилиты диагностики: `curl`, `jq`, `stern` (для multi-pod логирования), `promtool` (для валидации правил PromQL).
- Базовое понимание концепций и жизненного цикла [Deployment](./index.md), параметров [Манифеста Deployment](./deployment_manifest.md) и процедур [Устранения неполадок Deployment](./troubleshooting.md).

## 1. Определения

**Наблюдаемость Deployment (Deployment Observability)** — свойство системы, позволяющее судить о внутреннем состоянии, фазе жизненного цикла и качестве функционирования контроллера Deployment и его дочерних подов на основе внешних сигналов телеметрии: метрик состояния (KSM), аппаратных ресурсов (cAdvisor), логов приложений и распределенных трассировок.

**kube-state-metrics (KSM)** — специализированный сервис мониторинга, прослушивающий API-сервер Kubernetes и преобразующий состояние объектов кластера (желаемое vs фактическое количество реплик, статусы условий, генерации спецификации) в метрики Prometheus временных рядов с префиксом `kube_`.

**cAdvisor (Container Advisor)** — встроенный в Kubelet фоновый агент сбора аппаратных метрик работы контейнеров (CPU, память, диск, сеть) напрямую из иерархии Linux cgroups (в актуальных версиях — cgroups v2). Поставляет метрики с префиксом `container_`.

**observedGeneration** — счетчик версий спецификации в `status.observedGeneration`, который контроллер Deployment успел фактически обработать. Если `status.observedGeneration < metadata.generation`, контроллер еще не применил последние правки манифеста.

**Условия Deployment (Conditions)** — массив структур в `status.conditions`, отражающий качественные аспекты жизненного цикла:
- `Available` — развертывание имеет минимум требуемых доступных реплик (по умолчанию `> 0`, если `spec.replicas > 0`).
- `Progressing` — процесс обновления реплик продвигается вперед или успешно завершился. Если выставлен статус `False` с причиной `ProgressDeadlineExceeded`, процесс признан зависшим.
- `ReplicaFailure` — контроллер не может создать один или несколько дочерних подов (нехватка квот, ограничения прав, ошибки селектора).

**Зависшее развертывание (Stuck Rollout)** — состояние, при котором процесс RollingUpdate не может достичь желаемого числа готовых реплик в течение времени `spec.progressDeadlineSeconds`. Контроллер фиксирует состояние через условие `ProgressDeadlineExceeded`, но не выполняет автоматический откат самостоятельно, требуя вмешательства SRE-инженера или CI/CD-автоматизации.

**USE-метод (Utilization, Saturation, Errors)** — методология анализа инфраструктурных ресурсов контейнеров пода (утилизация CPU/памяти, насыщение в очередях троттлинга CFS, ошибки сброса страниц или OOM).

**RED-метод (Rate, Errors, Duration)** — методология мониторинга сервисов уровня приложения, развернутых в Deployment: интенсивность входящих запросов (Rate), частота ошибок HTTP 5xx / gRPC (Errors), длительность обработки запросов / задержка (Duration).

**Индикаторы и цели уровня обслуживания (SLI / SLO)** — формализованные метрики надежности сервиса:
- **SLI (Service Level Indicator)** — измеримое соотношение успешных событий к общему числу (например, процент доступных реплик Deployment или доля быстрых HTTP-ответов).
- **SLO (Service Level Objective)** — целевой ориентир надежности (например, 99.9% времени количество доступных реплик равно желаемому).

## 2. Базовые концепции и архитектура

### Архитектурная модель сбора телеметрии Deployment

Мониторинг развертываний в Kubernetes строится на декомпозиции источников сигналов. Ни один отдельный компонент не дает полной картины: KSM ничего не знает о потреблении памяти процессом, а cAdvisor ничего не знает о фазах RollingUpdate.

```text
               +--------------------------------------------------------+
               |                   Kubernetes API-Server                |
               +--------------------------------------------------------+
                      | watch/list                              ^
                      v (Deployment status)                     | status update
               +----------------------+                 +--------------------+
               |  kube-state-metrics  |                 | Deployment         |
               |       (KSM)          |                 | Controller         |
               +----------------------+                 +--------------------+
                      |                                         |
     OpenMetrics      | scrape (:8080/metrics)                  | manages
     `kube_deployment_*`                                        v
                      v                                 +--------------------+
               +----------------------+                 |    ReplicaSet      |
               |      Prometheus      |                 +--------------------+
               +----------------------+                         | manages
                      ^                                         v
                      | scrape (:10250/metrics/cadvisor)+--------------------+
                      |                                 |       Pods         |
               +----------------------+                 |  (cgroups v2)      |
               |       Kubelet        |<----------------+--------------------+
               |     (cAdvisor)       |  cgroup counters (memory.current,
               +----------------------+                   cpu.stat, etc.)
```

### Жизненный цикл Deployment в метриках контроллера

Когда инженер или конвейер CI/CD применяет обновление спецификации (`metadata.generation` инкрементируется), контроллер проходит детерминированные состояния, отражаемые в числовых показателях KSM:

```text
[Изменение spec.template]
       |
       v
`metadata_generation` > `observed_generation` (контроллер видит дельту)
       |
       v
Контроллер выравнивает: `observed_generation` = `metadata_generation`
Создается новый ReplicaSet с хешем ревизии
       |
       v
Постепенный запуск новых подов:
  `replicas_updated` растет от 0 до `spec_replicas`
  `replicas` может кратковременно превышать `spec_replicas` (на величину `maxSurge`)
       |
       v
Прохождение Readiness Probe:
  `replicas_ready` растет
  `replicas_available` растет (с учетом `minReadySeconds`)
       |
       v
Вывод из эксплуатации старого ReplicaSet:
  `replicas_unavailable` = 0
  `replicas_updated` == `replicas_available` == `spec_replicas`
```

### Иерархия уровней наблюдаемости

Наблюдаемость строится снизу вверх по трем уровням изоляции:

| Уровень | Источник данных | Ключевые метрики | Зона ответственности |
| :--- | :--- | :--- | :--- |
| **Уровень контроллера (Orchestration)** | `kube-state-metrics` | `kube_deployment_status_replicas_*`, `kube_deployment_status_condition`, `kube_deployment_status_observed_generation` | Выявление зависших выкаток, дефицита реплик, рассинхронизации поколений |
| **Уровень контейнеров и подов (Resources)** | `cAdvisor` (встроен в Kubelet) | `container_memory_working_set_bytes`, `container_cpu_usage_seconds_total`, `container_cpu_cfs_throttled_periods_total` | Выявление рисков OOMKilled, троттлинга процессора, деградации cgroups |
| **Уровень прикладного сервиса (Workload)** | Приложение / Ingress / Envoy | `http_requests_total`, `http_request_duration_seconds`, gRPC status codes | Соответствие SLO, бизнес-метрики, процент ошибок 5xx, задержки p95/p99 |

### Корреляция сигналов наблюдаемости

Для расследования инцидентов сигналы обязаны иметь сквозные связующие идентификаторы:
1. **Метрики:** Prometheus скрейпит метрики приложения и KSM, сохраняя стандартные лейблы `namespace`, `deployment`, `pod`.
2. **Логи:** Агент сбора логов (Fluent Bit, Promtail, Vector) извлекает метаданные пода из `/var/log/pods/<namespace>_<pod>_<uid>/` и обогащает каждую строку полями `k8s.deployment.name`, `k8s.pod.name`.
3. **Трейсы:** Заголовки распределенной трассировки (`traceparent` по стандарту W3C Trace Context) передаются между сервисами и логируются в сообщениях об ошибках, позволяя по ID трейса найти релевантные строки лога и метрики конкретного экземпляра Deployment.

---

## 3. Практические сценарии и конфигурация

### Полный каталог метрик kube-state-metrics для Deployment

Следующие метрики генерируются коллектором KSM и служат основой для мониторинга:

| Метрика | Тип | Описание и применение |
| :--- | :--- | :--- |
| `kube_deployment_spec_replicas` | Gauge | Желаемое количество реплик из `spec.replicas`. Базовая линия для расчетов. |
| `kube_deployment_status_replicas` | Gauge | Фактическое количество созданных подов (включая старые и новые RS). |
| `kube_deployment_status_replicas_ready` | Gauge | Количество подов, успешно прошедших Readiness Probe. |
| `kube_deployment_status_replicas_available` | Gauge | Количество готовых подов, проработавших без падений не менее `minReadySeconds`. |
| `kube_deployment_status_replicas_unavailable` | Gauge | Количество подов, которые должны быть доступны, но еще не готовы или упали. |
| `kube_deployment_status_replicas_updated` | Gauge | Количество подов, использующих актуальный шаблон `spec.template`. |
| `kube_deployment_metadata_generation` | Gauge | Номер ревизии спецификации манифеста (`metadata.generation`). |
| `kube_deployment_status_observed_generation` | Gauge | Номер ревизии, обработанный контроллером (`status.observedGeneration`). |
| `kube_deployment_status_condition` | Gauge | Состояние условий (`condition="Available|Progressing|ReplicaFailure"`, `status="true|false|unknown"`). Равно 1 при совпадении. |
| `kube_deployment_spec_paused` | Gauge | Флаг паузы развертывания (`spec.paused`). 1 — выкатка приостановлена, 0 — активна. |
| `kube_deployment_labels` | Gauge | Экспортирует метки объекта Deployment для обогащения запросов PromQL через `group_left`. |

### Ключевые PromQL-запросы для мониторинга развертываний

#### 1. Дефицит доступных реплик

Разница между желаемым количеством и фактически доступными экземплярами:

```promql
# Разница между желаемыми и доступными репликами (дефицит емкости)
kube_deployment_spec_replicas{namespace="production"}
- kube_deployment_status_replicas_available{namespace="production"} > 0
```

#### 2. Зависший процесс обновления (Stuck Rollout)

Проверка признака превышения дедлайна прогресса (`ProgressDeadlineExceeded`):

```promql
# Rollout провалил прогресс по таймауту
kube_deployment_status_condition{condition="Progressing", status="false", reason="ProgressDeadlineExceeded"} == 1
```

#### 3. Необработанное изменение манифеста (Generation Lag)

Контроллер Deployment еще не приступил к обработке примененного манифеста (задержка Control Plane):

```promql
# Контроллер не успел применить конфигурацию
kube_deployment_metadata_generation != kube_deployment_status_observed_generation
```

#### 4. Процент завершения RollingUpdate

Доля обновленных подов относительно общего желаемого числа:

```promql
# Процент раскатки новой версии (от 0 до 100%)
(
  kube_deployment_status_replicas_updated
  /
  kube_deployment_spec_replicas
) * 100
```

#### 5. Использование памяти контейнерами относительно установленного лимита

Корректное сопоставление cAdvisor и KSM для исключения ложных тревог по кэшу файловой системы:

```promql
# Доля памяти Working Set от жесткого лимита (исключая системный page cache)
sum(container_memory_working_set_bytes{container!="", container!="POD"}) by (namespace, pod, container)
/
sum(kube_pod_container_resource_limits{resource="memory"}) by (namespace, pod, container)
```

---

### Промышленный манифест PrometheusRule для мониторинга Deployment

Ниже представлен манифест Custom Resource `PrometheusRule`, готовый к интеграции в стек Prometheus Operator. Правила содержат защиту от ложных срабатываний во время штатных выкаток через временные задержки `for`.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: deployment-observability-rules
  namespace: monitoring
  labels:
    role: alert-rules
    prometheus: k8s
spec:
  groups:
    - name: deployment.rules
      rules:
        # 1. Зависший Rollout (Критический)
        - alert: DeploymentRolloutStuck
          expr: |
            kube_deployment_status_condition{condition="Progressing", status="false", reason="ProgressDeadlineExceeded"} == 1
          for: 5m
          labels:
            severity: critical
            tier: workload
          annotations:
            summary: "Развертывание {{ $labels.namespace }}/{{ $labels.deployment }} зависло"
            description: "Rollout Deployment {{ $labels.deployment }} превысил progressDeadlineSeconds. Новые поды не могут стать Ready."
            runbook_url: "https://kb.local/runbooks/k8s/deployment-stuck"

        # 2. Недоступные реплики более 15 минут
        - alert: DeploymentReplicasUnavailable
          expr: |
            (
              kube_deployment_status_replicas_unavailable
              /
              kube_deployment_spec_replicas
            ) > 0.2
          for: 15m
          labels:
            severity: warning
            tier: workload
          annotations:
            summary: "Более 20% реплик Deployment {{ $labels.deployment }} недоступны"
            description: "В развертывании {{ $labels.namespace }}/{{ $labels.deployment }} недоступно {{ $value | humanizePercentage }} подов дольше 15 минут."
            runbook_url: "https://kb.local/runbooks/k8s/replicas-unavailable"

        # 3. Полный отказ развертывания (0 доступных реплик при желании > 0)
        - alert: DeploymentCompletelyDown
          expr: |
            kube_deployment_status_replicas_available == 0
            and
            kube_deployment_spec_replicas > 0
          for: 2m
          labels:
            severity: critical
            tier: workload
          annotations:
            summary: "Deployment {{ $labels.namespace }}/{{ $labels.deployment }} полностью недоступен"
            description: "Все реплики развертывания {{ $labels.deployment }} отсутствуют или не проходят пробы."
            runbook_url: "https://kb.local/runbooks/k8s/deployment-down"

        # 4. Рассинхронизация генерации (Control Plane lag)
        - alert: DeploymentGenerationMismatch
          expr: |
            kube_deployment_metadata_generation != kube_deployment_status_observed_generation
          for: 15m
          labels:
            severity: warning
            tier: control-plane
          annotations:
            summary: "Рассинхронизация поколения Deployment {{ $labels.deployment }}"
            description: "Контроллер не обработал обновление манифеста за 15 минут. Возможна перегрузка kube-controller-manager."
            runbook_url: "https://kb.local/runbooks/k8s/generation-mismatch"

        # 5. Опасное приближение к OOMKilled (Working Set > 85% от лимита)
        - alert: DeploymentPodMemoryNearLimit
          expr: |
            (
              sum(container_memory_working_set_bytes{container!="", container!="POD"}) by (namespace, pod, container)
              /
              sum(kube_pod_container_resource_limits{resource="memory"}) by (namespace, pod, container)
            ) > 0.85
          for: 5m
          labels:
            severity: warning
            tier: resources
          annotations:
            summary: "Контейнер {{ $labels.container }} в поде {{ $labels.pod }} близок к OOM"
            description: "Использование памяти Working Set достигло {{ $value | humanizePercentage }} от лимита в течение 5 минут."
            runbook_url: "https://kb.local/runbooks/k8s/pod-oom-risk"

        # 6. Жесткий CPU Throttling (> 40% квантов времени подавлено)
        - alert: DeploymentPodHighCPUThrottling
          expr: |
            (
              sum(rate(container_cpu_cfs_throttled_periods_total{container!="", container!="POD"}[5m])) by (namespace, pod, container)
              /
              sum(rate(container_cpu_cfs_periods_total{container!="", container!="POD"}[5m])) by (namespace, pod, container)
            ) > 0.40
          for: 10m
          labels:
            severity: warning
            tier: resources
          annotations:
            summary: "Высокий CPU Throttling в контейнере {{ $labels.container }}"
            description: "Контейнер пода {{ $labels.pod }} троттлится на {{ $value | humanizePercentage }}. Требуется пересмотр cpu limits."
            runbook_url: "https://kb.local/runbooks/k8s/cpu-throttling"
```

---

### SLI/SLO и мониторинг бюджета ошибок (Error Budget)

Для SRE-практики надежность развертывания выражается в формализованных метриках SLI.

#### 1. Deployment Availability SLI (Доступность реплик)

Доля времени в течение скользящего 30-дневного окна, когда сервис сохранял минимум требуемых доступных реплик:

```promql
# Availability SLI: доля времени, когда доступные реплики соответствовали желаемым
avg_over_time(
  (
    kube_deployment_status_replicas_available{namespace="production", deployment="api-gateway"}
    >=
    kube_deployment_spec_replicas{namespace="production", deployment="api-gateway"}
  )[30d:1m]
) * 100
```

Если целевое SLO составляет 99.5%, бюджет ошибок (Error Budget) равен 0.5% времени (примерно 3.6 часа деградации в месяц).

#### 2. Service Level Indicator времени выкатки (Rollout Duration SLI)

Метрика скорости применения изменений без деградации сервиса:

```promql
# Проверка: продолжается ли выкатка дольше 10 минут
(
  kube_deployment_status_replicas_updated{namespace="production", deployment="api-gateway"}
  !=
  kube_deployment_spec_replicas{namespace="production", deployment="api-gateway"}
)
```

---

### Мониторинг взаимодействия Deployment с HorizontalPodAutoscaler (HPA)

При подключении HPA объект Deployment не управляет числом реплик вручную — поле `spec.replicas` модифицируется контроллером HPA. В мониторинге необходимо контролировать насыщение границ.

#### Запрос: HPA уперся в максимальный лимит реплик

Если `current_replicas == max_replicas`, нагрузка продолжает расти, а масштабирование исчерпано:

```promql
# HPA достиг верхнего предела масштабирования
kube_horizontalpodautoscaler_status_current_replicas{namespace="production", horizontalpodautoscaler="api-gateway-hpa"}
==
kube_horizontalpodautoscaler_spec_max_replicas{namespace="production", horizontalpodautoscaler="api-gateway-hpa"}
```

#### Манифест HPA на базе метрик приложения (Prometheus Adapter / KEDA)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-gateway-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-gateway
  minReplicas: 3
  maxReplicas: 15
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "850"
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
```

---

### Автоматизированный гейтинг и откат в CI/CD

В конвейерах непрерывного развертывания (GitLab CI, Woodpecker, Jenkins) проверка успешности деплоя обязана включать как статус Kubernetes, так и валидацию прикладных метрик в Prometheus.

```bash
#!/usr/bin/env bash
set -euo pipefail

DEPLOYMENT_NAME="api-gateway"
NAMESPACE="production"
PROMETHEUS_URL="http://prometheus-operated.monitoring.svc.cluster.local:9090"
EVALUATION_WINDOW_SECONDS=180
MAX_ERROR_RATE=0.02 # 2% допустимых ошибок 5xx

echo "==> 1. Ожидание завершения RollingUpdate на уровне контроллера..."
if ! kubectl rollout status deployment/"${DEPLOYMENT_NAME}" -n "${NAMESPACE}" --timeout=300s; then
  echo "[-] Rollout завершился сбоем на уровне K8s! Выполняем аварийный откат..."
  kubectl rollout undo deployment/"${DEPLOYMENT_NAME}" -n "${NAMESPACE}"
  exit 1
fi

echo "[+] Rollout завершен. Ожидание прогрева трафика (${EVALUATION_WINDOW_SECONDS}s)..."
sleep "${EVALUATION_WINDOW_SECONDS}"

echo "==> 2. Запрос доли ошибок 5xx из Prometheus..."
QUERY="sum(rate(http_requests_total{namespace=\"${NAMESPACE}\",service=\"${DEPLOYMENT_NAME}\",status=~\"5..\"}[3m]))/sum(rate(http_requests_total{namespace=\"${NAMESPACE}\",service=\"${DEPLOYMENT_NAME}\"}[3m]))"

RESPONSE=$(curl -s -G --data-urlencode "query=${QUERY}" "${PROMETHEUS_URL}/api/v1/query")
ERROR_RATE=$(echo "${RESPONSE}" | jq -r '.data.result[0].value[1] // 0')

echo "[*] Текущий Error Rate: ${ERROR_RATE}"

# Сравнение через awk для работы с плавающей запятой без внешних утилит bc
IS_FAILED=$(awk -v err="${ERROR_RATE}" -v max="${MAX_ERROR_RATE}" 'BEGIN {print (err > max) ? 1 : 0}')

if [ "${IS_FAILED}" -eq 1 ]; then
  echo "[-] Error Rate (${ERROR_RATE}) превысил допустимый порог (${MAX_ERROR_RATE})!"
  echo "[-] Инициируем автоматический откат ревизии Deployment..."
  kubectl rollout undo deployment/"${DEPLOYMENT_NAME}" -n "${NAMESPACE}"
  kubectl rollout status deployment/"${DEPLOYMENT_NAME}" -n "${NAMESPACE}" --timeout=180s
  exit 1
fi

echo "[+] Проверка надежности успешно пройдена. Деплой утвержден."
```

---

### Логирование подов Deployment

Логи подов развертывания анализируются как локально через `kubectl`, так и через утилиты агрегации в реальном времени.

```bash
# Просмотр логов всех подов Deployment по селектору меток
kubectl logs -n production -l app.kubernetes.io/name=api-gateway --tail=50 --prefix=true

# Просмотр логов с фильтрацией только за последние 10 минут
kubectl logs -n production -l app.kubernetes.io/name=api-gateway --since=10m

# Просмотр логов предыдущего упавшего контейнера (при CrashLoopBackOff)
kubectl logs -n production -l app.kubernetes.io/name=api-gateway --previous --tail=100

# Мульти-под агрегация логов в реальном времени через stern с выделением цветов
stern api-gateway -n production --since 5m --exclude "healthz|readyz"
```

---

### Распределенная трассировка (Tracing) и сквозной контекст

В микросервисной архитектуре поды Deployment генерируют спаны трассировки. Для корреляции метрик с трейсами в OpenTelemetry используются стандартные семантические конвенции:

```yaml
# Фрагмент spec.template.spec.containers манифеста с переменными OpenTelemetry
env:
  - name: OTEL_SERVICE_NAME
    value: "api-gateway"
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: "http://otel-collector.monitoring.svc.cluster.local:4317"
  - name: OTEL_RESOURCE_ATTRIBUTES
    valueFrom:
      fieldRef:
        fieldPath: metadata.labels['app.kubernetes.io/version']
  - name: K8S_NODE_NAME
    valueFrom:
      fieldRef:
        fieldPath: spec.nodeName
  - name: K8S_POD_NAME
    valueFrom:
      fieldRef:
        fieldPath: metadata.name
  - name: K8S_NAMESPACE_NAME
    valueFrom:
      fieldRef:
        fieldPath: metadata.namespace
```

---

## 4. Операции и команды

### Инспекция статуса и телеметрии Deployment через kubectl

Проверка состояния контроллера и счетчиков реплик:

```bash
# Получение детального сводного статуса развертывания
kubectl get deployment api-gateway -n production -o wide
# → NAME          READY   UP-TO-DATE   AVAILABLE   AGE   CONTAINERS    IMAGES               SELECTOR
# → api-gateway   5/5     5            5           14d   api-gateway   registry.local/api:v1.4.0   app.kubernetes.io/name=api-gateway

# Проверка условий (Conditions) развертывания через jsonpath
kubectl get deployment api-gateway -n production -o jsonpath='{range .status.conditions[*]}{.type}{"\t"}{.status}{"\t"}{.reason}{"\t"}{.message}{"\n"}{end}'
# → Available	True	MinimumReplicasAvailable	Deployment has minimum availability.
# → Progressing	True	NewReplicaSetAvailable	ReplicaSet "api-gateway-5df679fbf9" has successfully progressed.

# Сравнение generation и observedGeneration для проверки лага Control Plane
kubectl get deployment api-gateway -n production -o jsonpath='{"spec.generation: "}{.metadata.generation}{"\nobservedGeneration: "}{.status.observedGeneration}{"\n"}'
# → spec.generation: 6
# → observedGeneration: 6

# Просмотр истории ревизий и аннотаций изменений
kubectl rollout history deployment/api-gateway -n production
# → deployment.apps/api-gateway
# → REVISION  CHANGE-CAUSE
# → 4         Release 1.3.8 - Hotfix
# → 5         Release 1.3.9 - Performance tuning
# → 6         Release 1.4.0 - Major update
```

### Проверка и валидация эндпоинта метрик KSM и Prometheus

Проверка доступности метрик KSM на узле или через port-forward:

```bash
# Проверка генерации метрик по конкретному деплойменту в kube-state-metrics
kubectl exec -n monitoring deploy/prometheus-k8s -c prometheus -- \
  curl -s "http://kube-state-metrics.monitoring.svc:8080/metrics" | grep 'kube_deployment_status_replicas{.*deployment="api-gateway"'
# → kube_deployment_status_replicas{deployment="api-gateway",namespace="production"} 5

# Быстрый тест вычисления PromQL-запроса через Prometheus API
curl -s -G "http://localhost:9090/api/v1/query" \
  --data-urlencode 'query=kube_deployment_status_replicas_available{deployment="api-gateway"}' | jq .
# → {
# →   "status": "success",
# →   "data": {
# →     "resultType": "vector",
# →     "result": [
# →       {
# →         "metric": {
# →           "deployment": "api-gateway",
# →           "namespace": "production"
# →         },
# →         "value": [
# →           1728835200,
# →           "5"
# →         ]
# →       }
# →     ]
# →   }
# → }
```

### Валидация правил алертинга через promtool

Проверка синтаксиса и корректности файла PrometheusRule перед применением в GitOps:

```bash
# Валидация синтаксиса и типов в правилах PromQL
promtool check rules deployment_rules.yaml
# → Checking deployment_rules.yaml
# →   SUCCESS: 6 rules found
```

---

## 5. Устранение неполадок (Troubleshooting)

### Сценарий 1: Ложные срабатывания (False Positives) алертов при штатном RollingUpdate

- **Симптом:** При каждой плановой выкатке новой версии в Alertmanager срабатывает алерт `DeploymentReplicasUnavailable` или `DeploymentReplicasMismatch`.
- **Причина:** Алерт настроен на моментальное выражение `kube_deployment_spec_replicas != kube_deployment_status_replicas_available` без временной выдержки (`for`) или с коротким интервалом (например, 1 минута). Во время RollingUpdate новые поды запускаются постепенно, а старые гасятся, что вызывает естественное временное колебание доступности в пределах `spec.strategy.rollingUpdate.maxUnavailable`.
- **Диагностика:**
  1. Проверьте параметры стратегии:
     ```bash
     kubectl get deployment api-gateway -n production -o jsonpath='{.spec.strategy.rollingUpdate}'
     # → {"maxSurge":"25%","maxUnavailable":"25%"}
     ```
  2. Оцените среднее время раскатки и готовности подов (`startupProbe` + `readinessProbe` + `minReadySeconds`).
- **Решение:**
  1. Настройте директиву `for: 15m` для предупреждающих алертов, чтобы штатный rollout не вызывал дежурного инженера.
  2. Используйте алерт на условие `ProgressDeadlineExceeded` вместо грубой проверки равенства реплик.

### Сценарий 2: Рассинхронизация observedGeneration и metadata.generation

- **Симптом:** Алерт `DeploymentGenerationMismatch` активен дольше 15 минут, `kubectl apply` отработал успешно, но поды не обновляются.
- **Причина:** Контроллер `kube-controller-manager` перегружен (rate limiting запросов к API-серверу, задержки etcd, подвисание реконсилятора) либо манифест был поставлен на паузу (`spec.paused: true`).
- **Диагностика:**
  1. Проверьте флаг паузы:
     ```bash
     kubectl get deployment api-gateway -n production -o jsonpath='{.spec.paused}'
     # → true
     ```
  2. Если паузы нет, проверьте метрику очереди контроллера:
     ```promql
     workqueue_queue_duration_seconds_bucket{name="deployment"}
     ```
  3. Проверьте логи `kube-controller-manager`:
     ```bash
     kubectl logs -n kube-system -l component=kube-controller-manager --tail=100 | grep -E "api-gateway|error"
     ```
- **Решение:**
  1. Если развертывание на паузе — снимите паузу:
     ```bash
     kubectl rollout resume deployment/api-gateway -n production
     # → deployment.apps/api-gateway resumed
     ```
  2. Если проблема в контроллере — проверьте загрузку CPU/etcd на master-узлах.

### Сценарий 3: Отсутствие метрик kube_deployment_* в Prometheus

- **Симптом:** Grafana дашборд показывает `No Data`, запросы `kube_deployment_*` возвращают пустой результат.
- **Причина:**
  1. RBAC-права сервисного аккаунта `kube-state-metrics` не позволяют выполнять `watch/list` для `apps/v1/deployments`.
  2. KSM запущен с флагом `--metric-allowlist`, в который не включены деплойменты.
  3. Prometheus не находит PodMonitor/ServiceMonitor из-за несовпадающих меток селектора.
- **Диагностика:**
  1. Проверьте статус скрейпа в Prometheus:
     ```promql
     up{job="kube-state-metrics"} == 1
     ```
  2. Проверьте логи KSM на наличие ошибок RBAC:
     ```bash
     kubectl logs -n monitoring -l app.kubernetes.io/name=kube-state-metrics --tail=100 | grep -i "forbidden"
     ```
- **Решение:**
  1. Проверьте `ClusterRole` KSM: объект обязан содержать права:
     ```yaml
     - apiGroups: ["apps"]
       resources: ["deployments", "replicasets"]
       verbs: ["list", "watch"]
     ```
  2. Убедитесь, что `ServiceMonitor` содержит метку, совпадающую с `serviceMonitorSelector` инстанса Prometheus (например, `release: prometheus`).

### Сценарий 4: Ошибки вычисления утилизации памяти и скрытый OOM

- **Симптом:** Алерт по памяти срабатывает на 100%, но системный OOM-killer не убивает контейнер, либо наоборот — контейнер получает `OOMKilled` (Exit Code 137), хотя алерт молчал.
- **Причина:** Использование метрики `container_memory_usage_bytes` вместо `container_memory_working_set_bytes`. В Linux `memory_usage_bytes` включает в себя файловый кэш (page cache), который ядро может сбросить при нехватке памяти. Ядро убивает процесс только тогда, когда лимит превышает Working Set (`memory.current - inactive_file`).
- **Диагностика:**
  1. Сравните значения метрик в PromQL:
     ```promql
     container_memory_usage_bytes{pod="api-gateway-xxx"}
     container_memory_working_set_bytes{pod="api-gateway-xxx"}
     ```
- **Решение:**
  1. Все правила мониторинга памяти для Kubernetes-подов обязаны использовать исключительно `container_memory_working_set_bytes`.

### Сценарий 5: Скрытый троттлинг CPU при низкой средней утилизации контейнера

- **Симптом:** Приложение отвечает с высокой задержкой (latency spikes p99), при этом загрузка процессора `rate(container_cpu_usage_seconds_total[5m])` показывает всего 30–40% от `resources.limits.cpu`.
- **Причина:** Микроберсты нагрузки (microbursts). Ядро Linux выделяет CFS-квоту окнами по 100ms (`cfs_period_us`). Если многопоточный процесс исчерпывает выделенные 100ms за первые 15ms окна, остальные 85ms он полностью блокируется планировщиком ядра, что драматически увеличивает задержку, но не отражается на усредненных графиках.
- **Диагностика:**
  1. Проверьте процент подавленных периодов:
     ```promql
     rate(container_cpu_cfs_throttled_periods_total{container="api-gateway"}[5m])
     /
     rate(container_cpu_cfs_periods_total{container="api-gateway"}[5m])
     ```
- **Решение:**
  1. Увеличьте `limits.cpu` либо удалите жесткий CPU Limit, оставив только `requests.cpu` (рекомендация для latency-sensitive сервисов).

### Сценарий 6: Шторм алертов (Alert Storm) при массовом рестарте подов

- **Симптом:** При обновлении ноды или массовом перезапуске кластера инженеры получают сотни уведомлений в мессенджеры по каждому поду в отдельности.
- **Причина:** Не настроена группировка алертов в конфигурации `Alertmanager`.
- **Решение:**
  1. В `alertmanager.yaml` настройте группировку по пространству имен и имени деплоймента:
     ```yaml
     route:
       group_by: ['alertname', 'namespace', 'deployment']
       group_wait: 30s
       group_interval: 5m
       repeat_interval: 4h
     ```

---

## 6. Лучшие практики (Best Practices)

### Стандартизация меток (Labeling Schema)

Для бесшовной связи между метриками KSM, cAdvisor, логами и трассировками каждый Deployment обязан содержать стандартные метки Kubernetes SIG:

```yaml
metadata:
  labels:
    app.kubernetes.io/name: "api-gateway"
    app.kubernetes.io/instance: "api-gateway-prod"
    app.kubernetes.io/version: "v1.4.0"
    app.kubernetes.io/component: "backend"
    app.kubernetes.io/part-of: "billing-platform"
    app.kubernetes.io/managed-by: "gitops"
spec:
  template:
    metadata:
      labels:
        app.kubernetes.io/name: "api-gateway"
        app.kubernetes.io/instance: "api-gateway-prod"
        app.kubernetes.io/version: "v1.4.0"
```

### Оптимизация интервалов скрейпинга (Scrape & Evaluation Intervals)

1. **Scrape Interval KSM:** 15–30 секунд. Установка интервала менее 15 секунд создает избыточную нагрузку на API-сервер Kubernetes при частых обновлениях объектов.
2. **Evaluation Interval для правил правил/алертов:** 15–30 секунд.
3. **Минимальное окно `rate()`:** Окно усреднения в PromQL должно быть не менее 4x интервалов скрейпинга (например, при скрейпе 15s используйте `[1m]`, для стабильности — `[2m]` или `[5m]`).

### Предотвращение деградации при раскатке через Graceful Shutdown

Во время RollingUpdate старые поды выводятся из балансировки. Чтобы исключить ошибки 502/504 Bad Gateway на Ingress-контроллере:
1. Задайте `preStop` hook с паузой `sleep 10–15`, чтобы iptables/IPVS и EndpointSlice успели синхронизироваться до отправки `SIGTERM` приложению.
2. Установите `terminationGracePeriodSeconds: 60`.

```yaml
spec:
  template:
    spec:
      terminationGracePeriodSeconds: 60
      containers:
        - name: app
          lifecycle:
            preStop:
              exec:
                command: ["/bin/sh", "-c", "sleep 15"]
```

### Оформление дашборда Grafana для инженеров SRE/DevOps

Эффективный дашборд наблюдаемости Deployment делится на четыре логических ряда (Rows):
1. **Row 1 — Rollout & Orchestration:**
   - Stat: Статус текущей выкатки (`Progressing`, `Available`).
   - Graph: Желаемые vs Доступные vs Обновленные реплики.
   - Table: Недавние события (Kubernetes Events: `ScalingReplicaSet`, `FailedCreate`).
2. **Row 2 — Workload Golden Signals (RED):**
   - Graph: Request Rate (RPS по версиям / подам).
   - Graph: Error Rate (доля кодов 5xx).
   - Graph: Latency p50, p95, p99.
3. **Row 3 — Resource Saturation (USE):**
   - Graph: CPU Usage vs Request vs Limit.
   - Graph: CPU Throttling (% времени).
   - Graph: Memory Working Set vs Limit.
4. **Row 4 — Pod Lifecycle:**
   - Graph: Количество перезапусков контейнеров (`kube_pod_container_status_restarts_total`).
   - Stat: Текущее число подов в состояниях `Pending`, `CrashLoopBackOff`.

---

## 7. Дополнительная информация

### См. также
- [Deployment — Базовый обзор](./index.md) — фундаментальные концепции и структура контроллера.
- [Манифест Deployment и лучшие практики](./deployment_manifest.md) — эталонные production-манифесты и безопасность.
- [Устранение неполадок Deployment](./troubleshooting.md) — системная методология диагностики зависших выкаток.
- [Продвинутые сценарии диагностики Deployment](./advanced_troubleshooting_scenarios.md) — разбор глубоких инцидентов ядра Linux, cgroups и сети.
- [Progressive Delivery для Deployment](./progressive_delivery.md) — интеграция с канареечными контроллерами и анализ метрик.
- [Архитектура наблюдаемости в Kubernetes](../../MonitoringLogging/kubernetes-monitoring-logging-architecture.md) — общая архитектура сбора метрик, логов и трейсов.
- [Алерты для Kubernetes в Grafana Alerting](../../../Grafana/alerting/kubernetes_alerts.md) — промышленная база правил оповещения для кластера.
- [Horizontal Pod Autoscaler (HPA)](../../Autoscaling/HPA/index.md) — настройка и мониторинг автомасштабирования.
- [Концепции SRE: надежность, метрики и бюджет ошибок](../../../Concepts/sre_concepts_main.md) — теория SLI, SLO, SLA и Error Budget.
- [Мониторинг при Canary-развертывании](../../../CI-CD/Deployment_Strategies/canary_monitoring_and_gating.md) — статистический анализ метрик canary vs baseline.
