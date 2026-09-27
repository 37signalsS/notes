# Observability-Driven Testing

## Определения

**Observability-Driven Testing** — подход к тестированию, при котором метрики системы (latency, error rate, throughput) из внешних источников (Prometheus, Grafana) используются как автоматические gate-ы для деплоя. Система сама решает, безопасно ли продолжать rollout на основе поведения в продакшене.

**SLO-Based Gate** — автоматический блокиратор деплоя, основанный на Service Level Objectives. Если метрика отклоняется от SLO, деплой останавливается.

**Metric-Driven Canary Analysis** — анализ метрик canary-подов (новая версия) относительно baseline-подов (старая версия) для принятия решения о продолжении rollout.

**Progressive Delivery** — подход, при котором деплой происходит поэтапно с автоматической верификацией метрик на каждом шаге (canary → percent traffic → full rollout).

**Recording Rules** — предварительно вычисляемые Prometheus-запросы, сохраняемые как новые временные ряды. Ускоряют SLO-гейты и снижают нагрузку на Prometheus за счет кэширования тяжелых PromQL.

**Burn Rate** — скорость «сжигания» бюджета ошибок (error budget) относительно допустимого темпа. Используется для алертинга до исчерпания бюджета.

**Fail-Closed (Безопасный отказ)** — принцип гейтинга: при недоступности системы мониторинга, отсутствии данных или ошибке «судьи» раскатка останавливается, а не продолжается автоматически.

## Основные концепции и архитектура

### Как это работает

```text
Деплой → Canary (5% трафика) → Prometheus собирает метрики
                                     ↓
                             Prometheus query (PromQL)
                                     ↓
                          AnalysisTemplate / SLO Gate
                                     ↓
                     ┌───────────────────────────────┐
                     │ Метрики в пределах SLO?        │
                     │                               │
                     │  Да → Увеличить % трафика     │
                     │  Нет → Rollback               │
                     └───────────────────────────────┘
```

### Архитектура observability-driven pipeline

| Компонент | Роль | Особенности |
| :--- | :--- | :--- |
| **Prometheus** | Хранилище метрик | Scrape canary/baseline/stable с разными лейблами `version` |
| **Recording Rules** | Предвычисления | SLO-запросы, burn rate, p95/p99 ratio — кэшируются в TSDB |
| **Alertmanager** | Маршрутизация алертов | Делится на `oncall` (PagerDuty/OpsGenie) и `deployment-fail` (Slack/Email) |
| **Grafana** | Визуализация | Дашборды rollout'а: error rate, latency ratio, saturation, burn rate |
| **AnalysisTemplate / Canary CRD** | Автоматический судья | Argo Rollouts (v1.x) или Flagger (1.44.0, июль 2026) |
| **CI/CD Pipeline** | Оркестрация | GitHub Actions / GitLab CI / Jenkins / Ansible — запускает deploy, ждет гейт |
| **Secrets Manager** | Управление секретами | Хранит токены Prometheus, webhook'ов; CI runner получает через Vault/Age/SSM |

### Метрики для SLO Gate

| Метрика | Пример PromQL | Типичный порог |
| :--- | :--- | :--- |
| **Error Rate** | `sum(rate(http_requests_total{status=~"5.."}[5m]))` | < 1% |
| **p95 Latency** | `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))` | < 500ms |
| **Saturation (CPU)** | `avg(rate(container_cpu_usage_seconds_total[5m]))` | < 80% |
| **Saturation (Memory)** | `container_memory_working_set_bytes / container_spec_memory_limit_bytes` | < 85% |
| **Throughput** | `sum(rate(http_requests_total[5m]))` | > baseline * 0.9 |
| **Burn Rate** | `(error_budget_remaining / error_budget_total) < 0.5` | Срабатывает при быстром сжигании бюджета |

### Инструменты

| Инструмент | Тип | Роль |
| :--- | :--- | :--- |
| **Prometheus** | Metrics backend | Источник метрик для анализа; recording rules, alerting |
| **Argo Rollouts** | Progressive delivery | AnalysisTemplate + PromQL; v1.x, CLI `kubectl argo rollouts` |
| **Flagger** | Progressive delivery | Canary + Prometheus analysis поверх Deployment; 1.44.0 (июль 2026), CRD `flagger.app/v1beta1` |
| **OpenTelemetry** | Tracing/Metrics | Телеметрия для анализа; корреляция trace_id → metrics |
| **Grafana** | Visualization | Дашборды для мониторинга canary; SLO burn rate, latency ratio |
| **Alertmanager** | Alerting | Маршрутизация алертов деплоя в oncall-каналы |
| **VictoriaMetrics** | Metrics backend | Совместимая замена Prometheus для on-prem; используется в `canary_monitoring_and_gating.md` |
| **kubectl** | CLI | Управление Rollout/Canary, просмотр AnalysisRun |

### Жизненный цикл observability-driven деплоя

1. **Deploy canary:** CI/CD пайплайн применяет canary-версию (Rollout или Flagger создает канареечные поды).
2. **Scrape:** Prometheus собирает метрики с лейблом `version="canary"` и `version="baseline"`.
3. **Analysis:** Argo Rollouts/Flagger запускает AnalysisTemplate с PromQL-запросами к Prometheus.
4. **Gate:** Если метрики в пределах SLO — увеличивается вес трафика; если нет — инициируется rollback.
5. **Alerting:** При деградации Alertmanager отправляет алерт в oncall-канал (Slack/Email/PagerDuty).
6. **Full rollout:** После успешного прохождения всех шагов canary становится stable.

### Интеграция с CI/CD

- **Stages:** visual tests и observability gates запускаются после deploy на staging или параллельно с E2E; блокируют merge в main.
- **Artifacts:** diff-изображения, HTML-отчеты и метрики анализа сохраняются как артефакты pipeline минимум 30 дней.
- **Branch protection:** observability-driven test job должен стоять в required checks для merge в защищённые бранчи.
- **Cache:** recording rules и baseline-метрики кэшируются между запусками для ускорения.

### Recording Rules для SLO Gate

Recording Rules предвычисляют тяжелые PromQL-запросы и хранят их как новые временные ряды. Это снижает нагрузку на Prometheus и ускоряет AnalysisTemplate.

```yaml
# prometheus/rules/canary_slo_rules.yml
groups:
  - name: canary_slo
    interval: 30s
    rules:
      - record: job:http_requests:rate5m
        expr: sum(rate(http_requests_total[5m])) by (job, version)

      - record: job:http_errors:rate5m
        expr: sum(rate(http_requests_total{status=~"5.."}[5m])) by (job, version)

      - record: job:error_rate:ratio
        expr: |
          job:http_errors:rate5m / job:http_requests:rate5m

      - record: job:latency_p95:ms
        expr: |
          histogram_quantile(0.95,
            sum(rate(http_request_duration_seconds_bucket[5m])) by (job, le)
          ) * 1000

      - record: job:latency_ratio:canary_vs_baseline
        expr: |
          (
            histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{version="canary"}[5m])) by (le))
            /
            histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{version="baseline"}[5m])) by (le))
          )

      - record: job:error_budget:remaining
        expr: |
          (1 - job:error_rate:ratio{version="canary"}) / (1 - 0.01)
```

**Валидация:** После применения правил Prometheus UI должен отображать новые ряды в разделе «Recording Rules». Проверка: `Prometheus UI → Status → Rules → canary_slo`.

### Alertmanager routing для deployment failures

```yaml
# alertmanager/alertmanager.yml
route:
  group_by: ['alertname', 'service', 'namespace']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'oncall'
  routes:
    - match:
        alertname: 'HighErrorRateDuringRollout'
      receiver: 'deployment-fail'
      continue: true
    - match:
        alertname: 'HighLatencyDuringRollout'
      receiver: 'deployment-fail'
      continue: true

receivers:
  - name: 'oncall'
    slack_configs:
      - api_url: '${SLACK_WEBHOOK_URL}'
        channel: '#oncall'
    pagerduty_configs:
      - service_key: '${PAGERDUTY_KEY}'

  - name: 'deployment-fail'
    slack_configs:
      - api_url: '${SLACK_WEBHOOK_URL}'
        channel: '#devops-deploys'
    email_configs:
      - to: 'devops@example.com'
        from: 'alertmanager@example.com'
        smarthost: 'smtp.example.com:587'
        auth_username: 'alertmanager'
        auth_password: '${SMTP_PASSWORD}'
```

**Валидация:** `amtool check-config alertmanager.yml`. Проверка доставки: `amtool alert add test alertname='TestDeployGate' --receiver deployment-fail`.

### Grafana dashboard для rollout monitoring

Минимальный набор панелей для дашборда canary-анализа:

| Панель | PromQL | Тип |
| :--- | :--- | :--- |
| **Error Rate (canary vs baseline)** | `job:error_rate:ratio{version=~"canary|baseline"}` | Graph (lines) |
| **p95 Latency ratio** | `job:latency_ratio:canary_vs_baseline` | Graph (threshold line at 1.1) |
| **Error Budget Remaining** | `job:error_budget:remaining{version="canary"}` | Gauge (0–100%) |
| **Request Rate** | `job:http_requests:rate5m{version=~"canary|baseline"}` | Graph |
| **Active Alerts** | `count(alertmanager_alerts{alertstate="firing"})` | Stat |
| **AnalysisRun status** | `argo_rollouts_analysis_status{rollout="my-app"}` | Table (если используется Argo Rollouts) |

## Практические сценарии

### Сценарий 1: Recording Rules + AnalysisTemplate (Argo Rollouts)

Recording Rules предвычисляют SLO-метрики. AnalysisTemplate ссылается на них вместо тяжелых inline-PromQL.

#### Шаг 1: Примените Recording Rules

```bash
# Копирование правил в Prometheus
kubectl create configmap canary-slo-rules \
  --from-file=prometheus/rules/canary_slo_rules.yml \
  -n monitoring

# Prometheus подхватит правила автоматически (если настроен --rules-file)
# Или через kube-prometheus-stack: prometheusRule в Helm values
```

**Валидация:**
```bash
# Проверка в Prometheus UI
curl -s "http://prometheus.monitoring:9090/api/v1/query?query=job:error_rate:ratio" \
  | jq '.data.result[] | {metric: .metric, value: .value[1]}'
```

#### Шаг 2: AnalysisTemplate, ссылающийся на Recording Rules

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: canary-slo-check
  namespace: my-app
spec:
  args:
    - name: service-name
  metrics:
    - name: error-rate
      interval: 1m
      count: 5
      successCondition: result[0] < 0.01
      failureLimit: 2
      provider:
        prometheus:
          address: http://prometheus.monitoring:9090
          query: |
            job:error_rate:ratio{job="{{args.service-name}}", version="canary"}

    - name: latency-p95-ratio
      interval: 1m
      count: 5
      successCondition: result[0] < 1.10
      failureLimit: 2
      provider:
        prometheus:
          address: http://prometheus.monitoring:9090
          query: |
            job:latency_ratio:canary_vs_baseline{job="{{args.service-name}}"}
```

#### Шаг 3: Rollout с AnalysisTemplate

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: my-app
  namespace: my-app
spec:
  replicas: 10
  strategy:
    canary:
      canaryService: my-app-canary
      stableService: my-app-stable
      analysis:
        templates:
          - templateName: canary-slo-check
      steps:
        - setWeight: 10
        - pause: { duration: 5m }
        - setWeight: 50
        - pause: { duration: 10m }
        - setWeight: 100
  selector:
    matchLabels: { app: my-app }
  template:
    metadata:
      labels: { app: my-app }
    spec:
      containers:
        - name: app
          image: registry.example.com/my-app:v2.1.0
          readinessProbe:
            httpGet: { path: /healthz, port: 8080 }
            initialDelaySeconds: 5
            periodSeconds: 10
```

**Валидация:**
```bash
kubectl argo rollouts get rollout my-app -n my-app --watch
# → Weight: 10   STEP: setWeight:10   DESIRED: 10 ...
# → ✔ Step: pause (5m)
# → Weight: 50   ... AnalysisRun my-app-... Successful
```

### Сценарий 2: Flagger поверх Deployment

Для команд, которые не хотят менять Deployment на Rollout. Flagger работает поверх существующего Deployment.

#### Установка Flagger

```bash
helm repo add flagger https://flagger.app
helm upgrade -i flagger flagger/flagger \
  --namespace flagger-system \
  --set meshProvider=gatewayapi:v1 \
  --set metricsServer=http://prometheus.monitoring:9090
# → flagger deployed
```

#### Canary CRD

```yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: my-app
  namespace: my-app
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  progressDeadlineSeconds: 600
  service:
    port: 8080
    hosts: ['api.example.com']
    gatewayRefs:
      - name: public-gateway
        namespace: gateway-system
  analysis:
    interval: 1m
    threshold: 5
    maxWeight: 50
    stepWeight: 10
    metrics:
      - name: request-success-rate
        thresholdRange: { min: 99 }
        interval: 1m
      - name: request-duration
        thresholdRange: { max: 500 }
        interval: 30s
    webhooks:
      - name: smoke-test
        type: pre-rollout
        url: http://flagger-loadtester.my-app/
        timeout: 60s
        metadata:
          type: bash
          cmd: 'curl -sf http://my-app-canary.my-app:8080/healthz'
```

### Сценарий 3: Кастомный «судья» (Judge) для on-prem / Bare Metal

В традиционной среде (Bare Metal / VM) роль Analysis Engine выполняет скрипт, запускаемый из CI/Ansible между шагами веса.

```python
#!/usr/bin/env python3
"""Canary judge для Bare Metal/VM. Запускается между шагами веса.
Возвращает exit code: 0=Pass, 1=Marginal(стоп), 2=Fail(откат)."""
import sys, json, urllib.request, urllib.parse

PROM = "http://victoria-metrics:8428"
APP  = "my-service"
WIN  = "[5m]"

def ratio(metric, op, thr):
    q = (
        f"("
        f"sum(rate({metric}{{app='{APP}',version='canary'}}{WIN}))"
        f" / sum(rate({metric}{{app='{APP}',version='canary',status=~'2..'}}{WIN}))"
        f")"
        f" / "
        f"("
        f"sum(rate({metric}{{app='{APP}',version='baseline'}}{WIN}))"
        f" / sum(rate({metric}{{app='{APP}',version='baseline',status=~'2..'}}{WIN}))"
        f")"
    )
    url = f"{PROM}/api/v1/query?query={urllib.parse.quote(q)}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            res = json.load(r)["data"]["result"]
    except Exception as e:
        print(f"JUDGE_ERROR: monitoring unavailable -> Fail-Closed ({e})")
        sys.exit(2)
    if not res:
        print("JUDGE_WARN: no data yet (low traffic) -> Marginal")
        sys.exit(1)
    val = float(res[0]["value"][1])
    print(f"{metric}: ratio={val:.3f} (gate {op} {thr})")
    if op == ">" and val > thr: return False
    if op == "<" and val < thr: return False
    return True

# Скоринг: Errors + Latency(p95) + Saturation
score = 0
total = 3

# 1) Errors: рост доли 5xx > 1% относительно baseline — провал
score += 1 if ratio("http_requests_total{status=~'5..'}", ">", 1.01) else 0

# 2) Latency p95 (относительное сравнение histogram_quantile)
lp = (
    f"(histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket"
    f"{{app='{APP}',version='canary'}}{WIN})) by (le)))"
    f"/(histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket"
    f"{{app='{APP}',version='baseline'}}{WIN})) by (le)))"
)
try:
    with urllib.request.urlopen(f"{PROM}/api/v1/query?query={urllib.parse.quote(lp)}", timeout=10) as r:
        lr = json.load(r)["data"]["result"]
    lat = float(lr[0]["value"][1]) if lr else 1.0
    print(f"latency_p95_ratio={lat:.3f} (gate > 1.10)")
    score += 1 if lat <= 1.10 else 0
except Exception as e:
    print(f"JUDGE_ERROR: latency query failed -> Fail-Closed ({e})")
    sys.exit(2)

# 3) Saturation: CPU < 80%
sat = ratio("container_cpu_usage_seconds_total", "<", 0.80)
score += 1 if sat else 0

print(f"SCORE: {score}/{total}")
if score == total:
    print("PASS: All SLO checks passed")
    sys.exit(0)
elif score >= total - 1:
    print("MARGINAL: stopping for manual review")
    sys.exit(1)
else:
    print("FAIL: Rollback triggered")
    sys.exit(2)
```

### Сценарий 4: GitHub Actions — метрический gate

```yaml
name: Deploy with Observability Gate
on:
  push:
    branches: [main]

jobs:
  deploy-and-verify:
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v4

      - name: Configure credentials (локальный или self-hosted провайдер)
        run: |
          echo "${PROMETHEUS_TOKEN}" > /tmp/prometheus.token
          chmod 600 /tmp/prometheus.token

      - name: Deploy canary
        run: |
          kubectl apply -f k8s/canary.yaml
          kubectl argo rollouts promote my-app -n my-app --full || true
          sleep 60

      - name: Query Prometheus
        id: prom
        run: |
          ERROR_RATE=$(curl -s "${{ secrets.PROMETHEUS_URL }}/api/v1/query" \
            --data-urlencode "query=sum(rate(http_requests_total{service='my-app',status=~'5..'}[2m])) / sum(rate(http_requests_total{service='my-app'}[2m]))" \
            | jq -r '.data.result[0].value[1]')

          echo "error_rate=$ERROR_RATE" >> $GITHUB_OUTPUT

          if [ $(echo "$ERROR_RATE > 0.01" | bc -l) -eq 1 ]; then
            echo "FAIL: Error rate $ERROR_RATE exceeds threshold"
            kubectl argo rollouts abort my-app -n my-app
            exit 1
          fi

      - name: Full rollout
        if: success()
        run: kubectl set image deployment/my-app app=myapp:${{ github.sha }}
```

### Сценарий 5: GitLab CI — метрический gate

```yaml
deploy_and_verify:
  stage: deploy
  environment: production
  script:
    - kubectl apply -f k8s/canary.yaml
    - sleep 60

    - |
      ERROR_RATE=$(curl -s "$PROMETHEUS_URL/api/v1/query" \
        --data-urlencode "query=sum(rate(http_requests_total{service='my-app',status=~'5..'}[2m])) / sum(rate(http_requests_total{service='my-app'}[2m]))" \
        | jq -r '.data.result[0].value[1]')

      echo "Error rate: ${ERROR_RATE}"

      if [ $(echo "$ERROR_RATE > 0.01" | bc -l) -eq 1 ]; then
        echo "FAIL: Error rate ${ERROR_RATE} exceeds threshold"
        kubectl rollout undo deployment/my-app
        exit 1
      fi

    - kubectl set image deployment/my-app app=myapp:${CI_COMMIT_SHA}
  only:
    - main
```

### Сценарий 6: Ansible — кастомный judge для Bare Metal

```yaml
- name: Deploy canary to 10% of fleet
  hosts: app_servers
  serial: 2
  tasks:
    - name: Update package to canary version
      apt:
        name: myapp={{ canary_version }}
        state: present

    - name: Wait for stabilization
      wait_for:
        timeout: 60

    - name: Run observability judge
      command: /opt/scripts/canary_judge.py
      register: judge_result
      failed_when: judge_result.rc != 0

    - name: Abort if judge failed
      command: ansible-playbook rollback.yml
      when: judge_result.rc != 0
```

### Сценарий 7: Multi-cluster fleet rollout

Для fleet-деплоя (несколько кластеров/регионов) используйте federation или Thanos:

```yaml
# Thanos Querier агрегирует метрики из всех кластеров
# Prometheus в каждом кластере отправляет remote-write в Thanos Sidecar
# AnalysisTemplate query идет к единому Thanos Querier

provider:
  prometheus:
    address: http://thanos-querier.monitoring:9090
    query: |
      sum(rate(http_requests_total{version="canary",status=~"5.."}[5m]))
      /
      sum(rate(http_requests_total{version="canary"}[5m]))
```

**Валидация:** Проверьте, что Thanos Querier видит метрики из всех кластеров:
```bash
curl -s "http://thanos-querier.monitoring:9090/api/v1/query?query=up" \
  | jq '.data.result | length'
# → должно равняться количеству Prometheus инстансов
```

## Операции и команды

### Argo Rollouts CLI

| Команда | Назначение |
| :--- | :--- |
| `kubectl argo rollouts get rollout <name> -n <ns> --watch` | Отслеживание статуса rollout'а в реальном времени |
| `kubectl argo rollouts abort <name> -n <ns>` | Принудительная остановка rollout'а |
| `kubectl argo rollouts undo <name> -n <ns>` | Откат к предыдущей версии |
| `kubectl argo rollouts undo <name> -n <ns> --to-revision=3` | Откат к конкретной ревизии |
| `kubectl argo rollouts promote <name> -n <ns>` | Ручное продвижение к следующему шагу |
| `kubectl argo rollouts promote <name> -n <ns> --full` | Полное продвижение до 100% |
| `kubectl argo rollouts restart <name> -n <ns>` | Перезапуск rollout'а |
| `kubectl argo rollouts list rollouts -n <ns>` | Список всех Rollout'ов в namespace |

### Flagger CLI

| Команда | Назначение |
| :--- | :--- |
| `kubectl get canary -n <ns>` | Список всех Canary CRD |
| `kubectl describe canary <name> -n <ns>` | Детали текущего анализа |
| `kubectl get events --field-selector reason=Canary` | События канарейки |
| `kubectl delete canary <name> -n <ns>` | Удаление Canary CRD (откат к stable) |

### Prometheus / VictoriaMetrics

| Команда | Назначение |
| :--- | :--- |
| `curl -s "http://prometheus:9090/api/v1/query?query=up"` | Проверка доступности Prometheus |
| `curl -s "http://prometheus:9090/api/v1/query?query=job:error_rate:ratio"` | Проверка recording rule |
| `amtool check-config alertmanager.yml` | Валидация конфигурации Alertmanager |
| `amtool alert add test --receiver oncall` | Тест отправки алерта |
| `amtool silence add --duration=1h alertname=HighErrorRate` | Временное подавление алерта |

### CI/CD: Bash-паттерны

```bash
# Проверка доступности Prometheus из CI runner
curl -s --max-time 5 "$PROMETHEUS_URL/api/v1/query?query=up" \
  | jq -e '.data.result | length > 0'

# Проверка recording rules
curl -s "$PROMETHEUS_URL/api/v1/query?query=job:error_rate:ratio{version=\"canary\"}" \
  | jq -e '.data.result | length > 0'

# Экспорт AnalysisRun статуса
kubectl argo rollouts get rollout my-app -n my-app -o json \
  | jq -r '.status.conditions[] | select(.type=="Progressing") | .reason'

# Проверка Alertmanager
curl -s "$ALERTMANAGER_URL/api/v1/alerts" \
  | jq '.data.alerts | length'

# Ожидание завершения rollout'а
kubectl argo rollouts get rollout my-app -n my-app -w \
  | grep -E "✔|degraded|failed"
```

### Jenkins: Pipeline

```groovy
pipeline {
  agent any
  environment {
    PROMETHEUS = credentials('prometheus-url')
  }
  stages {
    stage('Deploy Canary') {
      steps {
        sh 'kubectl apply -f k8s/canary.yaml'
        sleep time: 60, unit: 'SECONDS'
      }
    }
    stage('Observability Gate') {
      steps {
        script {
          def response = sh(
            script: """curl -s "${PROMETHEUS}/api/v1/query" \
              --data-urlencode "query=sum(rate(http_requests_total{status=~'5..'}[2m])) / sum(rate(http_requests_total[2m]))" """,
            returnStdout: true
          )
          def errorRate = sh(
            script: "echo '${response}' | jq -r '.data.result[0].value[1]'",
            returnStdout: true
          ).trim()
          if (errorRate.toDouble() > 0.01) {
            error "FAIL: Error rate ${errorRate} exceeds threshold"
          }
        }
      }
    }
    stage('Full Rollout') {
      when { expression { currentBuild.result == null || currentBuild.result == 'SUCCESS' } }
      steps {
        sh 'kubectl set image deployment/my-app app=myapp:${BUILD_NUMBER}'
      }
    }
  }
}
```

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| AnalysisTemplate падает с `NaN` | Prometheus не имеет данных для запрошенного временного окна | Убедитесь, что scrape настроен; добавьте `successCondition: result[0] < 0.01 or absent(result[0])` |
| Canary analysis не запускается | Нет `analysis` в Rollout/Canary spec | Добавить секцию `analysis` с правильными `templates` |
| Prometheus query возвращает ошибку | Неверный PromQL или имя сервиса | Протестировать PromQL в Prometheus UI |
| Rollback происходит без причины | Слишком низкий `threshold` | Отрегулировать порог на основе реальных данных (используйте percentile, а не абсолютные значения) |
| Метрики не меняются после canary | Малый % трафика (5%) | Увеличить `setWeight` или увеличить `pause` duration; проверьте traffic routing |
| Flagger не находит метрику | Имя метрики не совпадает с настройкой | Проверить `request-success-rate` / `request-duration` в Flagger; убедитесь, что метрики экспортируются |
| Recording rule не применяется | Ошибка синтаксиса YAML или неправильное имя файла | `kubectl get prometheusrules -n monitoring`; проверьте логи Prometheus |
| Alertmanager не отправляет алерты | Ошибка в receiver (URL, токен) или подавление | Проверьте `amtool alert query`; проверьте `inhibit_rules` |
| CI runner не может подключиться к Prometheus | Сетевая политика / firewall / DNS | `curl -v` из runner'а; проверьте NetworkPolicy в Kubernetes |
| Burn rate растет, но error budget остаётся | Разный размер выборки (canary vs baseline) | Используйте relative comparison (ratio) вместо абсолютных порогов |
| Thanos Querier не видит метрики из кластера | Sidecar не отправляет remote-write | Проверьте `thanos_sidecar_sent_batch_bytes` и конфигурацию `remote_write` |
| AlertmanagerConfig не применяется | Пустой `alertmanagerConfigSelector` в Helm values | Добавьте `matchLabels` в `values.yaml` kube-prometheus-stack |
| Stale baseline (устаревшие эталоны) | Baseline не обновлялся после изменений в инфраструктуре | Перегенерируйте baseline через `--update-snapshots` в отдельном MR |

### Диагностика в CI/CD

```bash
# Проверка доступности Prometheus
curl -s --max-time 5 "http://prometheus.monitoring:9090/api/v1/query?query=up" \
  | jq '.data.result | length'

# Проверка Alertmanager
curl -s "http://alertmanager.monitoring:9093/api/v1/alerts" \
  | jq '.data.alerts | length'

# Проверка AnalysisRun статуса
kubectl argo rollouts get rollout my-app -n my-app -o jsonpath='{.status.conditions}'

# Проверка recording rules
curl -s "http://prometheus.monitoring:9090/api/v1/query?query=job:error_rate:ratio{version=\"canary\"}" \
  | jq '.data.result[] | {metric: .metric, value: .value[1]}'

# Smoke-test из runner'а
curl -s -o /dev/null -w "%{http_code}" http://my-app-canary.my-app:8080/healthz
```

## Best Practices

### Проектирование и стабильность

- **Docker-first для воспроизводимости:** Все тесты и анализ должны запускаться в идентичных Docker-образах. Никогда не смешивайте локальный Chrome/Chromium с CI.
- **Recording Rules для SLO:** Предвычисляйте burn rate, error budget и latency ratio. Это снижает нагрузку на Prometheus и ускоряет гейты.
- **Relative thresholds:** Используйте ratio (canary vs baseline) вместо абсолютных значений. Это исключает влияние фоновой нагрузки и сезонности.
- **Fail-Closed:** При недоступности мониторинга деплой должен останавливаться, а не продолжаться. Никогда не используйте `continue-on-error` для гейтов.
- **Warm-up period:** Добавляйте `initialDelay` (2–3 минуты) перед запуском AnalysisTemplate. Анализ, начатый до завершения прогрева (JIT-компиляция, прогрев кэшей), даёт ложные срабатывания.
- **Компоненты, а не страницы:** Визуальные и метрические тесты эффективнее на уровне Storybook или отдельных UI-библиотек. Это снижает шум от глобальных элементов.

### Управление версиями и baselines

- **Версионируйте baselines:** При использовании Git LFS каждая ветка имеет свои baselines. При слиянии MR обновляйте baselines в том же PR.
- **Осознанное обновление:** Обновляйте скриншоты только через `--update-snapshots` или `backstop approve` в отдельном коммите/MR с код-ревью.
- **Retention:** Настройте удаление старых артефактов в CI (обычно 30–90 дней). Для Git LFS используйте `git lfs prune` на runner'е.

### CI/CD оркестрация и инфраструктура

- **Runner isolation:** Выделяйте dedicated runner'ы для visual и observability tests. Генерация скриншотов и анализ метрик требовательны к CPU и RAM; shared runner'ы страдают от noisy neighbors.
- **Secrets management:** Токены для Prometheus, Alertmanager webhook'ов храните в CI secrets (GitLab CI variables, GitHub Secrets, Vault). Не коммитьте credentials в репозиторий.
- **RBAC:** CI runner'ы должны иметь минимальные права: read на Prometheus API, write на Alertmanager (только для тестовых алертов), deploy на целевые namespace.
- **Network policies:** В Kubernetes ограничьте доступ к Prometheus и Alertmanager только CI-runner'ам иApplication pods. Отключите анонимный доступ.
- **Caching:** Кэшируйте `node_modules` и baseline-метрики между запусками для ускорения. В GitHub Actions используйте `actions/cache@v4`; в GitLab — `cache:`.
- **Quality gates:** Observability-driven test job должен стоять перед deploy в staging/production. Настройте branch protection: merge в main блокируется при падении gates.

### Observability и отладка

- **Burn rate alerts:** Используйте burn rate вместо абсолютных порогов. Burn rate показывает скорость сжигания error budget и позволяет реагировать до исчерпания бюджета.
- **Grafana annotations:** Добавляйте annotations в дашборд на каждый deploy (commit, author, rollout name). Это упрощает корреляцию аномалий с релизами.
- **Debug artifacts:** При падении сохраняйте stderr от AnalysisTemplate, логи Prometheus и скриншоты failed-тестов.
- **Reproducibility:** Воспроизведите падение локально в том же Docker-образе: `docker run --rm -v $(pwd):/work mcr.microsoft.com/playwright:v1.49.0-noble npx playwright test --grep "failing test" --headed`.
- **Multi-cluster consistency:** Для fleet-деплоя используйте единый Thanos Querier или VictoriaMetrics Cluster. Убедитесь, что recording rules идентичны во всех кластерах.

### Безопасность

- **Авторизация в Prometheus:** Включите basic auth или token-based auth. Отключите анонимный доступ.
- **HTTPS:** Используйте TLS для Prometheus и Alertmanager URL в production.
- **Secrets rotation:** Регулярно ротируйте токены доступа к Prometheus и Alertmanager. Храните их в секрет-менеджере (Vault, Age, SSM, Kubernetes Secrets с encryption at rest).
- **Audit:** Включите audit log в Prometheus и Alertmanager для отслеживания кто и когда меняет правила или silence.

## Дополнительная информация

### См. также

* **[Канареечный деплой: мониторинг](../../CI-CD/Deployment_Strategies/canary_monitoring_and_gating.md)** — AnalysisTemplate, PromQL, gate.
* **[Прогрессивная доставка в GitOps](../../GitOps/Concepts/progressive_delivery_gitops.md)** — Argo Rollouts, Flagger, Prometheus.
* **[Smoke Testing](./smoke_testing.md)** — post-deploy verification.

### Внешние ресурсы

- [Argo Rollouts Analysis](https://argo-rollouts.readthedocs.io/en/stable/features/analysis/) — AnalysisTemplate.
- [Flagger Canary](https://docs.flagger.app/) — progressive delivery с Flagger.
- [Prometheus Querying](https://prometheus.io/docs/prometheus/latest/querying/) — PromQL.
- [Prometheus Recording Rules](https://prometheus.io/docs/prometheus/latest/configuration/recording_rules/) — предвычисления.
