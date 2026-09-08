# Визуализация и мониторинг: Policy Reporter

## Определения

**Policy Reporter** — специализированный инструмент для визуализации, агрегации и мониторинга отчетов безопасности в Kubernetes. Он преобразует декларативные данные из ресурсов `PolicyReport` ( Custom Resource) в интерактивные дашборды, формирует метрики для систем наблюдения (Prometheus/Grafana) и обеспечивает маршрутизацию уведомлений о нарушениях.

На 2026 год Policy Reporter является ключевым компонентом для реализации **Compliance-as-Code**, поддерживая стандарт **OpenReports**. Это позволяет объединять результаты проверок от различных движков (Kyverno, Falco, Trivy, Kube-bench) в единой консоли управления.

---

## Основные концепции

### Возможности и компоненты

| Компонент | Функциональное назначение |
| :--- | :--- |
| **Web UI** | Графический интерфейс для анализа текущего состояния безопасности и поиска нарушений. Поддерживает фильтрацию по namespace, policy, severity и status. |
| **Metrics Engine** | Генерация Prometheus-метрик для анализа трендов безопасности во времени. Отдельно от метрик Kyverno — специфичные для Policy Reporter. |
| **OpenReports Plugin** | Обеспечивает прием и нормализацию данных от сторонних сканеров (Falco, Trivy). Поддерживает формат `openreports.io`. |
| **High Availability (HA)** | Поддержка режима Active-Passive с Leader Election для предотвращения дублирования алертов. |
| **Target Routing** | Гибкая настройка получателей уведомлений (Slack, Telegram, Loki, Elasticsearch, S3, Webhook, MS Teams). |
| **Source** | Концепция, объединяющая данные из разных источников (Kyverno, Falco, Trivy) для маршрутизации и фильтрации. |
| **Filter / Prioritize** | Механизмы фильтрации результатов по severity, policy, namespace и маршрутизации в разные targets. |

### Модульная архитектура (OpenReports)

Процесс сбора и визуализации данных строится на принципе нормализации:

1.  **Сбор данных**: Плагины (Kyverno, Falco) отслеживают изменения соответствующих ресурсов в кластере.
2.  **Нормализация**: Данные приводятся к стандарту `openreports.io`, что позволяет корректно отображать специфические метаданные (например, уровни CVE от Trivy или системные вызовы от Falco).
3.  **Обработка**: Core-компонент применяет фильтры и правила маршрутизации.
4.  **Визуализация и алертинг**: Обновление UI и отправка событий в настроенные Targets.

### Архитектура компонентов и потоки данных

Policy Reporter работает как отдельный Helm-чарт (не входит в основной чарт Kyverno). Архитектура состоит из трех основных контейнеров:

| Контейнер | Роль | Порты |
| :--- | :--- | :--- |
| **core** | Основной обработчик: прием данных от Kyverno/Falco/Trivy, фильтрация, маршрутизация, отправка в targets. | 8080 (API), 2112 (metrics) |
| **ui** | Frontend: React-based веб-интерфейс для просмотра PolicyReport. | 8080 (UI) |
| **metrics** (встроенный в core) | Генерация Prometheus-метрик. Экспортирует `policyreport_results`, `clusterpolicyreport_results`. | 2112 |

**Поток данных:**

```
Kyverno Reports Controller ──┐
Falco (falco-plugin) ────────┼──▶ Policy Reporter Core ──┬──▶ Web UI
Trivy (trivy-plugin) ────────┘    │                       ├──▶ Prometheus Metrics
                                  │                       ├──▶ Slack/Telegram
                                  │                       ├──▶ Loki
                                  │                       ├──▶ Elasticsearch
                                  │                       ├──▶ S3/MinIO
                                  │                       └──▶ Webhook (custom)
                                  │
                                  └──▶ PolicyReport/ClusterPolicyReport (K8s API)
```

**Режимы развёртывания:**
- **In-Kubernetes (рекомендуется)**: Core + UI + Leader Election в Namespace `policy-reporter`.
- **Sidecar (Legacy)**: Внешний мониторинг PostgreSQL/MySQL для хранения результатов (устаревает).
- **Agent Mode**: Политики разворачиваются как DaemonSet на каждой ноде для локальной обработки (экспериментально).

---

## Практические сценарии

### 1. Промышленная установка через Helm

В 2026 году рекомендуется модульная установка с разделением компонентов для повышения безопасности.

```bash
# Добавление репозитория
helm repo add policy-reporter https://kyverno.github.io/policy-reporter
helm repo update

# Установка с HA и интеграцией Kyverno
helm install policy-reporter policy-reporter/policy-reporter \
  --namespace policy-reporter \
  --create-namespace \
  --set ui.enabled=true \
  --set plugin.kyverno.enabled=true \
  --set metrics.enabled=true \
  --set leaderElection.enabled=true \
  --set replicaCount=2
```

**Расширенный `values.yaml` для промышленной эксплуатации:**

```yaml
# Основные настройки
replicaCount: 2
leaderElection:
  enabled: true
  # ИспользуетLEASE в Namespace policy-reporter

# Плагин Kyverno ( основной источник данных)
plugin:
  kyverno:
    enabled: true
    # KyvernoReports API endpoint
    # По умолчанию: http://kyverno-reports-controller.kyverno.svc:8080

# Плагин Falco (runtime-инциденты)
plugin:
  falco:
    enabled: true
    # Требует Falco Sidekick или Falco Exporter
    endpoint: "http://falco-sidekick.default.svc:9001"

# Плагин Trivy (CVE)
plugin:
  trivy:
    enabled: true
    # Требует Trivy Operator или Trivy DB
    endpoint: "http://trivy-operator.trivy-system.svc:4954"

# Web UI
ui:
  enabled: true
  replicaCount: 1
  # Ограничение ресурсов
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 200m
      memory: 256Mi

# Prometheus метрики
metrics:
  enabled: true
  serviceMonitor:
    enabled: true
    namespace: monitoring
    interval: 30s
  # Дополнительные метрики (custom)
  customLabels:
    team: "security"

# Высокая доступность
highAvailability:
  enabled: true
  # Anti-Affinity для распределения по нодам
  affinity:
    podAntiAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 100
          podAffinityTerm:
            labelSelector:
              matchLabels:
                app.kubernetes.io/name: policy-reporter
            topologyKey: kubernetes.io/hostname
```

### 2. Настройка безопасности UI (Ingress + BasicAuth)

Для защиты доступа к дашборду рекомендуется использовать Ingress-контроллер с аутентификацией.

**Конфигурация Ingress в `values.yaml`**:
```yaml
ui:
  ingress:
    enabled: true
    annotations:
      kubernetes.io/ingress.class: nginx
      nginx.ingress.kubernetes.io/auth-type: basic
      nginx.ingress.kubernetes.io/auth-secret: basic-auth-secret
    hosts:
      - host: policy-reporter.example.org
        paths:
          - path: /
            pathType: ImplementationSpecific
```

### 3. Интеграция Falco и Trivy (OpenReports)

Для объединения runtime-событий Falco и результатов сканирования Trivy в Policy Reporter необходимо включить соответствующие адаптеры.

**Настройка плагинов**:
```yaml
plugin:
  falco:
    enabled: true
  trivy:
    enabled: true
# После включения Policy Reporter начнет отображать CVE и runtime-инциденты в общем списке.
```

### 4. Маршрутизация уведомлений (Slack и Loki)

Пример настройки `values.yaml` для разделения потоков данных: критические алерты в Slack, все события — в Loki.

```yaml
target:
  slack:
    enabled: true
    webhook: "https://hooks.slack.com/services/..."
    minimumPriority: "critical"
  loki:
    enabled: true
    host: "http://loki-gateway.monitoring.svc:3100"
    minimumPriority: "warning"
    # Добавление кастомных лейблов для Loki
    customLabels:
      cluster: "prod-cluster-01"
```

### 5. Маршрутизация в Elasticsearch

Для централизованного поиска и анализа нарушений в Kibana.

```yaml
target:
  elasticsearch:
    enabled: true
    host: "https://elasticsearch.logging.svc:9200"
    index: "policy-reports"
    minimumPriority: "warning"
    # Аутентификация
    username: "policy-reporter"
    password: "${ELASTICSEARCH_PASSWORD}"
    # TLS
    skipTLSVerify: false
    # ILM (Index Lifecycle Management)
    indexLifetime: "30d"
```

### 6. Маршрутизация в S3/MinIO

Для долгосрочного хранения аудиторских отчетов и compliance.

```yaml
target:
  s3:
    enabled: true
    endpoint: "https://s3.example.com"
    bucket: "security-audit-reports"
    prefix: "kyverno/"
    accessKeyId: "${AWS_ACCESS_KEY_ID}"
    secretAccessKey: "${AWS_SECRET_ACCESS_KEY}"
    region: "us-east-1"
    minimumPriority: "critical"
    # Формат файла: JSON
    format: "json"
```

### 7. Маршрутизация в Telegram

Для моментальных уведомлений команде безопасности.

```yaml
target:
  telegram:
    enabled: true
    token: "${TELEGRAM_BOT_TOKEN}"
    chatId: "-1001234567890"
    minimumPriority: "critical"
    # Формат сообщения
    message: |
      Security Alert: {{ .Policy }} - {{ .Resource }}
      Severity: {{ .Severity }}
      Namespace: {{ .Namespace }}
      Message: {{ .Message }}
```

### 8. Маршрутизация в Microsoft Teams

Для интеграции с корпоративными системами уведомлений.

```yaml
target:
  teams:
    enabled: true
    webhook: "https://outlook.office.com/webhook/..."
    minimumPriority: "warning"
    # Шаблон карточки Teams
    template: |
      {
        "@type": "MessageCard",
        "summary": "Security Policy Violation",
        "sections": [{
          "activityTitle": "{{ .Policy }}",
          "facts": [
            {"name": "Resource", "value": "{{ .Resource }}"},
            {"name": "Severity", "value": "{{ .Severity }}"},
            {"name": "Message", "value": "{{ .Message }}"}
          ]
        }]
      }
```

### 9. Фильтрация и Prioritize

Механизм фильтрации позволяет направлять события разных severity в разные targets.

```yaml
# Фильтрация по namespace
filter:
  # Исключить системные namespace из всех targets
  namespaces:
    exclude:
      - kube-system
      - kube-public
      - kube-node-lease
      - policy-reporter

# Prioritize: маршрутизация по severity
prioritize:
  # Критические алерты → Slack + Telegram
  critical:
    targets:
      - slack
      - telegram
  # Warning → Loki + Elasticsearch
  warning:
    targets:
      - loki
      - elasticsearch
  # Info → только Loki
  info:
    targets:
      - loki
```

---

## Дополнительная информация

### Метрики Prometheus (Policy Reporter)

Policy Reporter генерирует собственные метрики (отдельно от метрик Kyverno). Основные метрики:

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `policyreport_results` | Gauge | Текущее количество результатов в PolicyReport по policy/result/severity/category. |
| `clusterpolicyreport_results` | Gauge | То же для ClusterPolicyReport. |
| `policyreport_results_created` | Gauge | Время создания PolicyReport (Unix timestamp). |
| `policyreport_summary` | Gauge | Сводка pass/fail/warn/error/skip по namespace/policy. |

**Примеры PromQL-запросов:**

```promql
# Общее количество нарушений (fail) по namespace
sum by (namespace) (policyreport_results{result="fail"})

# Количество нарушений по severity
sum by (severity) (policyreport_results{result="fail"})

# Процент pass от общего количества проверок
sum(policyreport_results{result="pass"}) / sum(policyreport_results) * 100

# Количество PolicyReport с критическими нарушениями
count(policyreport_results{result="fail", severity="critical"} > 0)

# Нарушения по policy (топ-10)
topk(10, sum by (policy) (policyreport_results{result="fail"}))

# ClusterPolicyReport: нарушения по category
sum by (category) (clusterpolicyreport_results{result="fail"})
```

**Настройка ServiceMonitor для Policy Reporter:**

```yaml
# values.yaml
metrics:
  enabled: true
  serviceMonitor:
    enabled: true
    namespace: monitoring
    interval: 30s
    labels:
      release: prometheus  # Для autodiscovery Prometheus Operator
```

**Пример Alerting Rules:**

```yaml
groups:
  - name: policy-reporter
    rules:
      - alert: HighPolicyViolationRate
        expr: |
          sum(rate(policyreport_results{result="fail"}[5m]))
          / sum(rate(policyreport_results[5m])) > 0.1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High policy violation rate"
          description: >-
            {{ $value | humanizePercentage }} of policy checks are failing
            in namespace {{ $labels.namespace }}.

      - alert: CriticalPolicyViolation
        expr: policyreport_results{result="fail", severity="critical"} > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Critical policy violation detected"
          description: >-
            Policy {{ $labels.policy }} has critical violations
            for resource {{ $labels.resource }}.
```

### Безопасность развёртывания (Security Hardening)

В промышленной эксплуатации Policy Reporter должен быть защищен как любой компонент инфраструктуры безопасности.

**NetworkPolicy (ограничение сетевого доступа):**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: policy-reporter-netpol
  namespace: policy-reporter
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: policy-reporter
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Только из Prometheus (метрики)
    - from:
        - namespaceSelector:
            matchLabels:
              name: monitoring
      ports:
        - port: 2112
          protocol: TCP
    # Только из Ingress Controller (UI)
    - from:
        - namespaceSelector:
            matchLabels:
              name: ingress-nginx
      ports:
        - port: 8080
          protocol: TCP
  egress:
    # DNS
    - to: []
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
    # Kyverno Reports Controller
    - to:
        - namespaceSelector:
            matchLabels:
              name: kyverno
      ports:
        - port: 8080
          protocol: TCP
    # Loki (target)
    - to:
        - namespaceSelector:
            matchLabels:
              name: monitoring
      ports:
        - port: 3100
          protocol: TCP
```

**Pod Security Standards:**

```yaml
# Ограничение привилегий пода
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  fsGroup: 1000
  seccompProfile:
    type: RuntimeDefault

# readOnlyRootFilesystem (требует tmpfs для /tmp)
volumeMounts:
  - name: tmp
    mountPath: /tmp

volumes:
  - name: tmp
    emptyDir:
      sizeLimit: 100Mi
```

### Резервное копирование и восстановление

**Резервное копирование конфигурации:**

```bash
# Экспорт values.yaml и всех релизов
helm get values policy-reporter -n policy-reporter > policy-reporter-values.yaml
helm list -n policy-reporter -o yaml > policy-reporter-releases.yaml

# Резервное копирование Leader Election ConfigMap
kubectl get configmap -n policy-reporter -l app.kubernetes.io/name=policy-reporter \
  -o yaml > policy-reporter-leader.yaml
```

**Восстановление:**

```bash
# Восстановление из backup
helm upgrade policy-reporter policy-reporter/policy-reporter \
  -n policy-reporter \
  -f policy-reporter-values.yaml

# Принудительное переключение Leader (при необходимости)
kubectl delete configmap -n policy-reporter policy-reporter-leader-election
# Новые поды перезапустят election
```

### Обновление (Upgrade)

```bash
# Обновление репозитория
helm repo update

# Проверка доступных версий
helm search repo policy-reporter/policy-reporter

# Обновление с сохранением values
helm upgrade policy-reporter policy-reporter/policy-reporter \
  -n policy-reporter \
  -f policy-reporter-values.yaml \
  --reuse-values

# Проверка после обновления
kubectl get pods -n policy-reporter
helm test policy-reporter -n policy-reporter
```

### Поиск и устранение неисправностей (Troubleshooting)

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **UI пустой** | Плагин не активирован или нет прав RBAC. | Проверьте `plugin.<name>.enabled` и наличие ClusterRole `policy-reporter:viewer`. |
| **Дубли алертов** | Отключен Leader Election в HA-режиме. | Убедитесь, что `leaderElection.enabled=true` и只有一个 под elected. |
| **Нет данных в Loki** | Ошибка авторизации или сетевой доступ. | Проверьте логи пода `policy-reporter` на наличие 401/403 ошибок; убедитесь что NetworkPolicy разрешает egress на порт 3100. |
| **Метрики не обновляются** | ServiceMonitor не настроен или Prometheus не scrape. | Проверьте `kubectl get servicemonitor -n monitoring`; убедитесь что labels совпадают с Prometheus operator. |
| **Высокое потребление RAM** | Большое количество PolicyReport в памяти. | Увеличьте `resources.limits.memory`; настройте фильтрацию namespace через `filter.namespaces.exclude`. |
| **"no such host" при отправке в Slack** | DNS-резолвинг не работает внутри пода. | Проверьте CoreDNS; убедитесь что NetworkPolicy разрешает DNS-трафик (порт 53). |
| **PolicyReport не создается** | Reports Controller не работает или нет RBAC. | Проверьте `kubectl get pods -n kyverno`; убедитесь что ServiceAccount `kyverno-reports-controller` имеет доступ к policyreport. |
| **UI отображает "Loading" бесконечно** | Core API недоступен или network issue. | Проверьте логи core-контейнера; убедитесь что порт 8080 доступен из UI-под. |

### Производительность и лимиты

| Аспект | Рекомендация | Примечание |
| :--- | :--- | :--- |
| **Память (RAM)** | 256 MB - 1 GB | Зависит от количества `PolicyReport` в памяти. При >1000 PolicyReport увеличьте до 1 GB. |
| **Процессор (CPU)** | 200m - 500m | Основная нагрузка приходится на парсинг JSON/YAML. При активном target routing увеличьте до 500m. |
| **Кэширование** | Включено по умолчанию | Снижает нагрузку на API-сервер K8s. Отключение не рекомендуется. |
| **ReplicaCount** | 2 (HA) | Для HA необходим Leader Election и Pod Anti-Affinity. Без HA — 1 replica достаточно. |
| **Rate Limiting** | Рекомендуется для targets | Настройка `rateLimit` в target предотвращает спам при mass-violations. |
| **Очередь сообщений** | Internal queue (bounded) | При перегрузке core отбрасывает события (не блокирует). Мониторьте метрику `policyreporter_target_send_errors_total`. |

### См. также
- [Отчеты Kyverno и стандарты PolicyReport](./reports.md)
- [Интеграция Kyverno с Argo CD](./argo-cd.md)
- [Установка и настройка Kyverno (Prometheus metrics)](./install.md)
