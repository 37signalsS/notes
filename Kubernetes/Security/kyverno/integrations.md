# Интеграция Kyverno с инструментами безопасности

## Определения

**Falco** — инструмент runtime-безопасности на базе eBPF. Обнаруживает аномалии в поведении контейнеров (системные вызовы, сетевые соединения, доступ к файлам). Генерирует события безопасности, которые могут триггерить политики Kyverno.

**Trivy** — сканер уязвимостей для контейнеров, образов и IaC. Проверяет CVE в реестрах образов и файловых системах. Интегрируется с Kyverno через Policy Reporter для объединения результатов.

**kube-bench** — инструмент аудита конфигурации Kubernetes на соответствие CIS Benchmark. Проверяет параметры запуска компонентов (API-сервер, kubelet, etcd) на хостовых системах.

**Policy Reporter** — компонент для агрегации и визуализации результатов политик. Поддерживает плагины для Kyverno, Falco и Trivy через стандарт OpenReports.

---

## Архитектура интеграции

```text
┌─────────────────────────────────────────────────────────────────┐
│  Исходные данные (Data Sources)                                 │
│  ────────────────────────────────────────────────────────────  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Kyverno  │  │  Falco   │  │  Trivy   │  │kube-bench│       │
│  │ (Politik)│  │(Runtime) │  │  (CVE)   │  │  (CIS)   │       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
│       │              │              │              │             │
│       └──────────────┼──────────────┼──────────────┘             │
│                      ▼              ▼                           │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Policy Reporter Core (OpenReports)                     │   │
│  │  ────────────────────────────────────────────────────  │   │
│  │  • Нормализация данных (openreports.io)                 │   │
│  │  • Маршрутизация по Source (Kyverno/Falco/Trivy)        │   │
│  │  • Фильтрация и обогащение                              │   │
│  └──────────────────────────────────────────────────────────┘   │
│                      │                                          │
│       ┌──────────────┼──────────────┐                           │
│       ▼              ▼              ▼                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                     │
│  │ Web UI   │  │Prometheus│  │  Loki/   │                     │
│  │          │  │ Metrics  │  │  Grafana │                     │
│  └──────────┘  └──────────┘  └──────────┘                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Практические сценарии

### Сценарий 1: Интеграция Kyverno + Falco

**Цель:** Обнаружение runtime-инцидентов и блокировка подозрительных подов.

**Установка Falco:**

```bash
# Установка Falco через Helm
helm repo add falcosecurity https://falcosecurity.github.io/charts
helm install falco falcosecurity/falco \
  --namespace falco --create-namespace \
  --set driver.kind=modern_ebpf \
  --set falcosidekick.enabled=true \
  --set falcosidekick.config.slack.webhookurl="https://hooks.slack.com/..."

# Проверка работы
kubectl get pods -n falco
kubectl logs -n falco -l app.kubernetes.io/name=falco --tail=50
```

**Настройка Policy Reporter для Falco:**

```yaml
# policy-reporter-values.yaml
policyReporter:
  plugins:
    falco:
      enabled: true
      host: falco-falcosidekick.default.svc.cluster.local
      port: 2801
      # Фильтрация событий по severity
      severity:
        - emergency
        - critical
        - error

# Установка
helm install policy-reporter kyverno/policy-reporter \
  -n kyverno --values policy-reporter-values.yaml
```

**Пример политики, реагирующей на Falco-события:**

```yaml
apiVersion: v2.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: block-suspicious-syscalls
spec:
  validationActions: [Audit]  # Только аудит для начала
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods"]
  validations:
    # Проверка: нет привилегированных контейнеров
    - expression: "object.spec.containers.all(c, !has(c.securityContext.privileged) || !c.securityContext.privileged)"
      message: "Привилегированные контейнеры запрещены"
    # Проверка: нет hostPID
    - expression: "!has(object.spec.hostPID) || !object.spec.hostPID"
      message: "HostPID запрещен"
  # Обогащение через Falco (OpenReports)
  reporting:
    - plugin: falco
      severity: critical
```

**Настройка алертов:**

```yaml
# prometheus-rules.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: kyverno-falco-alerts
spec:
  groups:
    - name: kyverno-falco
      rules:
        - alert: FalcoCriticalEvent
          expr: |
            sum(increase(falco_events_total{priority="critical"}[5m])) > 0
          for: 0m
          labels:
            severity: critical
          annotations:
            summary: "Falco обнаружил критичное событие"
            description: "{{ $labels.rule }} - {{ $labels.output }}"

        - alert: KyvernoPolicyViolation
          expr: |
            sum(increase(kyverno_policy_results_total{result="fail"}[5m])) > 5
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Большое количество нарушений политик"
            description: "{{ $value }} нарушений за 5 минут"
```

### Сценарий 2: Интеграция Kyverno + Trivy

**Цель:** Автоматическая блокировка подов с критичными CVE.

**Установка Trivy Operator:**

```bash
# Установка Trivy Operator
helm repo add aquasecurity https://aquasecurity.github.io/helm-charts/
helm install trivy-operator aquasecurity/trivy-operator \
  --namespace trivy-system --create-namespace \
  --set trivy.severity="HIGH,CRITICAL" \
  --set operator.scanJobTimeout=10m

# Проверка сканирования
kubectl get vulnerabilityreports -A
kubectl get configauditreports -A
```

**Настройка Policy Reporter для Trivy:**

```yaml
# policy-reporter-values.yaml
policyReporter:
  plugins:
    trivy:
      enabled: true
      host: trivy-operator.trivy-system.svc.cluster.local
      port: 8080
      # Фильтрация по severity
      severity:
        - CRITICAL
        - HIGH
```

**Политика блокировки подов с критичными CVE:**

```yaml
apiVersion: v2.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: block-critical-cve
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods"]
  variables:
    - name: "criticalCVEs"
      expression: |
        globalContext.trivyReports.exists(r, r.results.exists(res, 
          res.severity == "CRITICAL" && res.fixedVersion == ""))
  validations:
    - expression: "!variables.criticalCVEs"
      message: "Под содержит критичные CVE без исправлений"
  globalContext:
    apiCalls:
      - name: "trivyReports"
        urlPath: "/apis/aquasecurity.github.io/v1alpha1/vulnerabilityreports"
        jmesPath: "items[].report.results[]"
```

**Интеграция с Admission Review:**

```yaml
# Автоматическое добавление метаданных о CVE в Pod
apiVersion: v2.kyverno.io/v1
kind: MutatingPolicy
metadata:
  name: enrich-pod-with-cve-info
spec:
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE"]
        resources: ["pods"]
  mutations:
    - patchType: JSONPatch
      jsonPatch:
        expression: |
          [{"op": "add", "path": "/metadata/labels/trivy-scan", "value": "pending"},
           {"op": "add", "path": "/metadata/annotations/trivy\\.security\\.io/scan-time", "value": string(time.now)}]
```

### Сценарий 3: Интеграция Kyverno + kube-bench

**Цель:** Проверка соответствия инфраструктуры CIS Benchmark и блокировка подов на небезопасных нодах.

**Установка kube-bench:**

```bash
# Запуск как Job
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: kube-bench
  namespace: kube-system
spec:
  template:
    spec:
      hostPID: true
      containers:
        - name: kube-bench
          image: docker.io/aquasec/kube-bench:latest
          command: ["kube-bench", "run", "--targets", "node,policies"]
          volumeMounts:
            - name: var-lib-kubelet
              mountPath: /var/lib/kubelet
              readOnly: true
            - name: etc-kubernetes
              mountPath: /etc/kubernetes
              readOnly: true
      restartPolicy: Never
      volumes:
        - name: var-lib-kubelet
          hostPath:
            path: /var/lib/kubelet
        - name: etc-kubernetes
          hostPath:
            path: /etc/kubernetes
EOF

# Просмотр результатов
kubectl logs job/kube-bench -n kube-system
```

**Настройка CronJob для регулярного аудита:**

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: kube-bench-audit
  namespace: kube-system
spec:
  schedule: "0 2 * * *"  # Ежедневно в 2:00
  jobTemplate:
    spec:
      template:
        spec:
          hostPID: true
          containers:
            - name: kube-bench
              image: docker.io/aquasec/kube-bench:latest
              command: ["kube-bench", "run", "--json", "--outputfile", "/results/bench.json"]
              volumeMounts:
                - name: results
                  mountPath: /results
                - name: var-lib-kubelet
                  mountPath: /var/lib/kubelet
                  readOnly: true
          restartPolicy: OnFailure
          volumes:
            - name: results
              emptyDir: {}
            - name: var-lib-kubelet
              hostPath:
                path: /var/lib/kubelet
```

**Политика блокировки подов на небезопасных нодах:**

```yaml
apiVersion: v2.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: check-node-compliance
spec:
  validationActions: [Audit]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE"]
        resources: ["pods"]
  variables:
    - name: "nodeCompliance"
      expression: |
        globalContext.kubeBenchResults.items.exists(r, 
          r.node == object.spec.nodeName && r.passed == false)
  validations:
    - expression: "!variables.nodeCompliance"
      message: "Нода не прошла CIS Benchmark проверку"
  globalContext:
    apiCalls:
      - name: "kubeBenchResults"
        urlPath: "/apis/v1/namespaces/kube-system/configmaps/kube-bench-results"
        jmesPath: "data.results"
```

### Сценарий 4: Единая панель мониторинга (Dashboard)

**Настройка Grafana для агрегации данных:**

```yaml
# docker-compose.yml (локальная разработка)
version: '3.8'
services:
  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    volumes:
      - grafana-data:/var/lib/grafana
      - ./dashboards:/etc/grafana/provisioning/dashboards
      - ./datasources:/etc/grafana/provisioning/datasources

  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml

  loki:
    image: grafana/loki:latest
    ports:
      - "3100:3100"

volumes:
  grafana-data:
```

**Дашборд для Kyverno + Falco + Trivy:**

```json
{
  "dashboard": {
    "title": "Security Overview",
    "panels": [
      {
        "title": "Kyverno Policy Violations",
        "type": "graph",
        "targets": [{
          "expr": "sum(kyverno_policy_results_total{result='fail'}) by (policy)"
        }]
      },
      {
        "title": "Falco Critical Events",
        "type": "graph",
        "targets": [{
          "expr": "sum(falco_events_total{priority='critical'}) by (rule)"
        }]
      },
      {
        "title": "Trivy CVE Distribution",
        "type": "piechart",
        "targets": [{
          "expr": "sum(trivy_vulnerabilities_total) by (severity)"
        }]
      },
      {
        "title": "kube-bench CIS Compliance",
        "type": "stat",
        "targets": [{
          "expr": "sum(kube_bench_results_total{result='pass'}) / sum(kube_bench_results_total) * 100"
        }]
      }
    ]
  }
}
```

---

## Дополнительная информация

### Настройка OpenReports

```yaml
# openreports-config.yaml
apiVersion: config.openreports.io/v1alpha1
kind: Configuration
metadata:
  name: openreports-config
  namespace: openreports
sources:
  - name: kyverno
    type: kyverno
    enabled: true
  - name: falco
    type: falco
    enabled: true
    config:
      endpoint: "http://falco-falcosidekick:2801"
  - name: trivy
    type: trivy
    enabled: true
    config:
      endpoint: "http://trivy-operator:8080"
targets:
  - name: prometheus
    type: prometheus
    enabled: true
  - name: grafana
    type: grafana
    enabled: true
```

### Troubleshooting интеграции

```bash
# Проверка подключения Falco к Policy Reporter
kubectl logs -n kyverno -l app.kubernetes.io/name=policy-reporter | grep -i falco

# Проверка подключения Trivy
kubectl logs -n kyverno -l app.kubernetes.io/name=policy-reporter | grep -i trivy

# Проверка OpenReports плагинов
kubectl get openreports -A
kubectl describe openreports kyverno-openreports -n openreports

# Просмотр метрик Policy Reporter
kubectl port-forward -n kyverno svc/policy-reporter-metrics 8081:8081
curl http://localhost:8081/metrics | grep policy_reporter
```

### См. также
- [Diagnostika](./troubleshooting.md) — методология поиска проблем интеграции
- [Policy Reporter](./reporter.md) — настройка агрегации данных
- [Falco](../../../Security/Tools/falco.md) — детали работы Falco
- [Trivy](../../../Security/Tools/trivy.md) — сканирование уязвимостей
- [kube-bench](../../kube-bench.md) — аудит CIS Benchmark
