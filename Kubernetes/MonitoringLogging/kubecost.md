# Kubecost: Управление затратами и FinOps в Kubernetes

## Определения

**Kubecost** — инструмент для мониторинга и оптимизации затрат в Kubernetes, обеспечивающий гранулярную видимость расходов в реальном времени на уровне пространств имен, деплойментов, подов и меток (labels). Работает как набор сервисов внутри кластера, интегрируясь с Prometheus для сбора метрик потребления ресурсов.

**OpenCost** — проект с открытым исходным кодом (CNCF sandbox), являющийся ядром (engine) для Kubecost. Он стандартизирует модель аллокации затрат в Kubernetes, предоставляя API для расчета стоимости ресурсов. OpenCost может использоваться как самостоятельно, так и в составе Kubecost для расширенной функциональности.

**FinOps (Cloud Financial Management)** — операционная модель и культурная практика, которая позволяет организациям получать максимальную выгоду от облака за счет объединения технологических, финансовых и бизнес-команд. В контексте Kubernetes FinOps фокусируется на управлении затратами на уровне кластера, команд и приложений.

**Cost Allocation (Аллокация затрат)** — процесс распределения общих расходов кластера (узлы, диски, балансировщики) между конкретными потребителями (командами, проектами, приложениями). Основывается на иерархии меток (labels) и пространствах имен (namespaces) для точной атрибуции расходов.

**Right-sizing (Оптимизация размеров)** — процесс подбора оптимальных `requests` и `limits` ресурсов или типов узлов под реальное потребление для снижения финансовых потерь без деградации производительности. Включает анализ исторических данных метрик и выдачу рекомендаций по оптимизации.

**Showback и Chargeback** — механизмы финансовой прозрачности. *Showback* — демонстрация расходов командам для осведомленности. *Chargeback* — фактическое распределение внутренних счетов между подразделениями для реализации перекрестного финансирования.

**Cluster Cost Rate (CCR)** — стоимость владения кластером в пересчете на единицу времени (обычно доллары в час). Используется для сравнения эффективности различных конфигураций кластеров и оценки экономического эффекта от оптимизаций.

**TCO (Total Cost of Ownership)** — полная стоимость владения, включающая капитальные затраты (оборудование), операционные расходы (электричество, охлаждение), стоимость труда и лицензий. Kubecost помогает рассчитать TCO для сравнения гибридных и локальных решений.

**Область применения:**
- Видимость затрат в реальном времени на уровне подов и команд
- Оптимизация ресурсов (right-sizing) на основе исторических данных
- Управление бюджетами и алертинг по превышению лимитов
- Showback/Chargeback для финансовой прозрачности
- Оценка TCO для сравнения инфраструктурных решений

## Основные концепции

### Архитектура и интеграция

Kubecost (и OpenCost) работает как набор сервисов внутри кластера и интегрируется с ключевыми компонентами инфраструктуры:

#### Компоненты Kubecost

| Компонент | Функция | Ресурсы |
|:---|:---|:---|
| **Cost Analyzer** | Основной движок для сбора и анализа данных о затратах | 0.5 CPU, 1GB RAM |
| **Cluster Controller** | Управление политиками оптимизации и автоматическими рекомендациями | 0.25 CPU, 512MB RAM |
| **Cluster Metrics** | Сбор и агрегация метрик потребления ресурсов | 0.25 CPU, 256MB RAM |
| **Network Costs** | Мониторинг сетевых расходов между узлами и зонами | 0.1 CPU, 128MB RAM |
| **GPU Metrics** | Трекинг использования GPU-инстансов | 0.1 CPU, 128MB RAM |

#### Схема потока данных

```
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                        │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │  Node 1   │  │  Node 2   │  │  Node 3   │  │  Node N   │  │
│  │  cAdvisor │  │  cAdvisor │  │  cAdvisor │  │  cAdvisor │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
│       │              │              │              │         │
│       └──────────────┴──────────────┴──────────────┘         │
│                            │                                 │
│                            ▼                                 │
│                   ┌────────────────┐                         │
│                   │  Prometheus     │                         │
│                   │  (Metrics DB)   │                         │
│                   └────────┬───────┘                         │
│                            │                                 │
│                            ▼                                 │
│                   ┌────────────────┐                         │
│                   │  Kubecost       │                         │
│                   │  Cost Analyzer  │                         │
│                   └────────┬───────┘                         │
│                            │                                 │
│                            ▼                                 │
│                   ┌────────────────┐                         │
│                   │  OpenCost API   │                         │
│                   │  (Cost Model)   │                         │
│                   └────────────────┘                         │
└─────────────────────────────────────────────────────────────┘
```

#### Механизм сбора данных

1. **cAdvisor**: Собирает метрики потребления CPU, RAM, сети и диска для каждого пода и контейнера
2. **kube-state-metrics**: Предоставляет информацию о состоянии объектов Kubernetes (Deployments, Pods, Nodes)
3. **Prometheus**: Хранит метрики и предоставляет их для анализа Cost Analyzer
4. **Cost Analyzer**: Рассчитывает стоимость на основе метрик и ценовых конфигураций
5. **OpenCost API**: Предоставляет REST API для интеграции с внешними системами

#### Ценовые конфигурации

Kubecost поддерживает несколько источников цен:

| Источник | Описание | Использование |
|:---|:---|:---|
| **Cloud Billing API** | Автоматическое получение цен из AWS/Azure/GCP | Облачные кластеры |
| **Custom Pricing** | Ручная настройка цен для bare-metal | On-premise кластеры |
| **Spot Instances** | Автоматическое распознавание Spot-узлов | Оптимизация затрат |
| **Reserved Instances** | Учет RI и Savings Plans | Долгосрочные обязательства |

### Зачем нужен Kubecost в 2026 году?

В современных гибридных средах, при борьбе с **cluster sprawl** (разрастанием кластеров) и использовании ресурсоемких нагрузок, стандартных счетов облачных провайдеров недостаточно. Kubecost решает следующие задачи:

1. **Видимость в реальном времени**: Данные о расходах с точностью до минуты внутри кластера (счета провайдера не детализируют расходы по подам)
2. **Эффективность ресурсов**: Отслеживание использования дорогих ресурсов (GPU, премиальные инстансы), помогая выявить недоутилизированные инстансы
3. **Showback и Chargeback**: Механизмы финансовой прозрачности для команд и подразделений
4. **Governance и бюджетирование**: Установка лимитов на расходы (Budgets) для Namespace/команд с автоматическим алертингом
5. **Обоснование консолидации**: Сравнение стоимости владения множеством мелких кластеров с одним крупным мультитенантным кластером для оптимизации TCO

### Интеграция с Prometheus

Kubecost использует Prometheus как основное хранилище метрик потребления ресурсов. Интеграция включает:

**Метрики, собираемые Kubecost:**
| Метрика | Описание | Источник |
|:---|:---|:---|
| `container_cpu_usage_seconds_total` | Использование CPU контейнерами | cAdvisor |
| `container_memory_working_set_bytes` | Использование RAM контейнерами | cAdvisor |
| `node_cpu_seconds_total` | Использование CPU узлами | node-exporter |
| `node_memory_MemAvailable_bytes` | Доступная память узлов | node-exporter |
| `kube_pod_info` | Информация о подах | kube-state-metrics |
| `kube_node_info` | Информация об узлах | kube-state-metrics |

**Настройка интеграции с существующим Prometheus:**
```yaml
# values.yaml для Kubecost
global:
  prometheus:
    fqdn: "http://prometheus-operated.monitoring.svc:9090"
    enabled: false  # Отключаем встроенный Prometheus
    port: 9090

# Если Prometheus требует аутентификации
prometheus:
  basicAuth:
    username: "prometheus"
    password: "YOUR_PASSWORD"
```

**Примеры PromQL-запросов для анализа затрат:**
```promql
# Стоимость CPU по namespace за последний час
sum(rate(container_cpu_usage_seconds_total{namespace="production"}[1h])) * 30

# Стоимость RAM по deployment за последний день
sum(container_memory_working_set_bytes{namespace="production", deployment="api"}) / 1024 / 1024 / 1024 * 4

# Стоимость сети по узлу за последний час
sum(rate(container_network_receive_bytes_total{node="worker-1"}[1h])) / 1024 / 1024 * 0.01

# Стоимость GPU по namespace за последний час
sum(kubecost_container_gpu_utilization{namespace="ml-training"}) * 3.50
```

---

## Роль в мультитенантных средах

Kubecost — основной инструмент для реализации финансовой изоляции и прозрачности в общих кластерах.

### 1. Атрибуция затрат по меткам (Labels)

Биллинг в Kubernetes строится на основе иерархии меток. Kubecost позволяет группировать расходы по:

| Метка | Назначение | Пример использования |
|:---|:---|:---|
| `namespace` | Базовая единица аллокации | `production`, `staging`, `development` |
| `label:team` | Атрибуция конкретной инженерной команде | `team=backend`, `team=frontend` |
| `label:cost-centre` | Привязка расходов к бюджетному центру | `cost-centre=marketing`, `cost-centre=rnd` |
| `label:environment` | Разделение затрат на среды | `environment=prod`, `environment=dev` |
| `label:app` | Привязка к конкретному приложению | `app=api-gateway`, `app=payment-service` |

**Пример конфигурации атрибуции:**
```yaml
# Deployment с метками для атрибуции затрат
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-gateway
  namespace: production
  labels:
    team: backend
    cost-centre: rnd
    environment: prod
    app: api-gateway
spec:
  replicas: 3
  template:
    metadata:
      labels:
        team: backend
        cost-centre: rnd
        environment: prod
        app: api-gateway
```

### 2. Детекция «шумных соседей» по стоимости

Kubecost помогает выявить тенантов, чьи рабочие нагрузки приводят к непропорциональному росту общих расходов. Типичные причины:

| Проблема | Симптомы | Решение |
|:---|:---|:---|
| Отсутствие лимитов | Поды потребляют все ресурсы узла | Настройка ResourceQuota и LimitRange |
| Агрессивное масштабирование | Резкий рост числа подов | Ограничение maxReplicas в HPA |
| Утечки ресурсов | Постепенный рост потребления | Right-sizing и мониторинг |
| Неэффективные запросы | Высокие requests при низком usage | Рекомендации по оптимизации |

**Пример мониторинга «шумных соседей»:**
```promql
# Найти namespace с наибольшей стоимостью CPU за последний час
topk(10,
  sum(rate(container_cpu_usage_seconds_total[1h])) by (namespace) * 30
)

# Найти deployment с наибольшей стоимостью RAM за последний день
topk(10,
  sum(container_memory_working_set_bytes) by (namespace, deployment) / 1024 / 1024 / 1024 * 4
)

# Найти поды с высоким использованием CPU относительно requests
kube_pod_container_resource_requests{resource="cpu"} > 0
  and
rate(container_cpu_usage_seconds_total[5m]) / kube_pod_container_resource_requests{resource="cpu"} > 0.8
```

### 3. Бюджетирование и алертинг

Kubecost позволяет устанавливать лимиты на расходы и получать уведомления при их превышении.

**Настройка бюджетов через API:**
```bash
# Создание бюджета для namespace production на $1000 в месяц
curl -X POST http://localhost:9090/model/budget \
  -H "Content-Type: application/json" \
  -d '{
    "name": "production-budget",
    "namespace": "production",
    "monthlyBudget": 1000,
    "alertThreshold": 80,
    "recipients": ["ops@example.com"]
  }'

# Получение текущего бюджета
curl http://localhost:9090/model/budget?namespace=production

# Обновление бюджета
curl -X PUT http://localhost:9090/model/budget \
  -H "Content-Type: application/json" \
  -d '{
    "name": "production-budget",
    "namespace": "production",
    "monthlyBudget": 1500,
    "alertThreshold": 85,
    "recipients": ["ops@example.com", "finance@example.com"]
  }'
```

**Пример алерта в Prometheus для превышения бюджета:**
```yaml
groups:
- name: kubecost-budget-alerts
  rules:
  - alert: KubecostBudgetExceeded
    expr: |
      kubecost_namespace_cost_hourly{namespace="production"}
      * 24 * 30 > 1000
    for: 1h
    labels:
      severity: warning
    annotations:
      summary: "Превышен бюджет для namespace production"
      description: "Текущие расходы: ${{ $value | humanize }} в месяц (бюджет: $1000)"

  - alert: KubecostBudgetCritical
    expr: |
      kubecost_namespace_cost_hourly{namespace="production"}
      * 24 * 30 > 1200
    for: 30m
    labels:
      severity: critical
    annotations:
      summary: "Критическое превышение бюджета для namespace production"
      description: "Текущие расходы: ${{ $value | humanize }} в месяц (бюджет: $1000)"
```

### 4. Отчеты и дашборды

Kubecost предоставляет встроенные дашборды и API для генерации отчетов.

**Встроенные дашборды:**
| Дашборд | Назначение | Периодичность |
|:---|:---|:---|
| **Cluster Costs** | Общая стоимость кластера | Посекундно |
| **Namespace Costs** | Стоимость по пространствам имен | Поминутно |
| **Deployment Costs** | Стоимость по деплойментам | Поминутно |
| **Pod Costs** | Стоимость по подам | Поминутно |
| **Asset Costs** | Стоимость узлов и дисков | Почасово |

**API для генерации отчетов:**
```bash
# Отчет по стоимости namespace за последний месяц
curl "http://localhost:9090/model/allocation?window=1d&aggregate=namespace&namespace=production"

# Отчет по стоимости deployment за последний час
curl "http://localhost:9090/model/allocation?window=1h&aggregate=deployment&namespace=production"

# Отчет по стоимости пода за последний день
curl "http://localhost:9090/model/allocation?window=1d&aggregate=pod&namespace=production"

# Отчет по стоимости кластера за последнюю неделю
curl "http://localhost:9090/model/clusterCosts?window=7d"

# Экспорт отчета в JSON
curl "http://localhost:9090/model/allocation?window=1d&aggregate=namespace&format=json"
```

### 5. Интеграция с Grafana

Kubecost может быть интегрирован с Grafana для создания кастомных дашбордов.

**Настройка datasource в Grafana:**
```yaml
# configmap-grafana-datasources.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-datasources
  namespace: monitoring
data:
  datasources.yaml: |
    datasources:
    - name: Kubecost
      type: prometheus
      url: http://kubecost-prometheus-server.kubecost.svc:9090
      access: proxy
      isDefault: false
      jsonData:
        timeInterval: '60s'
```

**Пример запроса в Grafana:**
```promql
# Стоимость по namespace за последний час
sum(rate(container_cpu_usage_seconds_total{namespace="$namespace"}[1h])) * 30
+
sum(container_memory_working_set_bytes{namespace="$namespace"}) / 1024 / 1024 / 1024 * 4

# Стоимость по deployment за последний день
topk(10,
  sum(rate(container_cpu_usage_seconds_total{namespace="$namespace"}[1d])) by (deployment) * 30
  +
  sum(container_memory_working_set_bytes{namespace="$namespace"}) by (deployment) / 1024 / 1024 / 1024 * 4
)
```

---

## Практические сценарии

### 1. Мониторинг затрат на GPU и ресурсоемкие нагрузки

Поскольку GPU-инстансы являются самыми дорогими в кластере, их мониторинг критичен.

**Детекция простоя (Idle GPU):**
Kubecost подсвечивает узлы, где GPU зарезервированы, но не используются для вычислений (нет активных процессов CUDA).

**Пример мониторинга GPU:**
```promql
# Утилизация GPU по namespace за последний час
avg(kubecost_container_gpu_utilization{namespace="ml-training"}) by (namespace) * 100

# Стоимость GPU по namespace за последний день
sum(kubecost_container_gpu_utilization{namespace="ml-training"}) * 3.50 * 24

# Поды с низкой утилизацией GPU (potential idle)
kubecost_container_gpu_utilization{namespace="ml-training"} < 0.1
  and
kube_pod_container_resource_requests{resource="nvidia.com/gpu"} > 0
```

**Рекомендации по оптимизации GPU:**
| Проблема | Решение | Экономия |
|:---|:---|:---|
| Idle GPU | Использование GPU time-sharing или миграция | 30–50% |
| Oversized GPU | Переход с A100 на T4 для inference | 60–70% |
| Non-spot GPU | Использование Spot-инстансов для training | 60–80% |

### 2. Оптимизация ресурсов (Right-sizing)

Kubecost анализирует исторические данные метрик Prometheus и выдает конкретные рекомендации:

**Abandoned Workloads (Заброшенные нагрузки):**
Обнаружение подов, которые работают и потребляют ресурсы, но не принимают сетевой трафик.

```promql
# Найти поды с высоким потреблением CPU но низким сетевым трафиком
rate(container_cpu_usage_seconds_total[1h]) > 0.5
  and
rate(container_network_receive_bytes_total[1h]) < 1024
  and
rate(container_network_transmit_bytes_total[1h]) < 1024
```

**Over-provisioned Requests (Избыточные запросы):**
Рекомендации по уменьшению `requests`, если поды исторически используют менее 20% от запрошенного CPU/RAM.

```promql
# Найти поды с высоким отношением requests к usage
kube_pod_container_resource_requests{resource="cpu"} > 0
  and
(rate(container_cpu_usage_seconds_total[1h]) / kube_pod_container_resource_requests{resource="cpu"}) < 0.2
```

**Пример автоматического right-sizing с VPA:**
```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: api-gateway-vpa
  namespace: production
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-gateway
  updatePolicy:
    updateMode: "Auto"
  resourcePolicy:
    containerPolicies:
    - containerName: api-gateway
      minAllowed:
        cpu: 100m
        memory: 128Mi
      maxAllowed:
        cpu: 2000m
        memory: 4Gi
      controlledResources: ["cpu", "memory"]
```

### 3. Настройка цен для Bare-Metal (On-Premise)

Если кластер находится в собственном ЦОД, интеграции с Cloud API нет. В этом случае настраиваются статические цены через файл конфигурации (Custom Pricing).

**Полная конфигурация для bare-metal:**
```yaml
# values-custom-pricing.yaml
kubecostProductConfigs:
  customPricesEnabled: true
  CPU: "0.031"              # Цена за 1 vCPU в час ($0.031 = ~$22/мес)
  RAM: "0.004"              # Цена за 1 GB RAM в час ($0.004 = ~$2.9/мес)
  storage: "0.0001"         # Цена за 1 GB хранилища в час
  GPU: "1.50"               # Цена за 1 GPU в час
  network: "0.01"           # Цена за 1 GB сетевого трафика

  # Скидки для不同 тиров узлов
  customPricingByNode:
    - nodeSelector:
        node-type: "standard"
      CPU: "0.031"
      RAM: "0.004"
    - nodeSelector:
        node-type: "high-memory"
      CPU: "0.045"
      RAM: "0.006"
    - nodeSelector:
        node-type: "gpu"
      GPU: "2.00"
```

**Расчет стоимости для on-premise:**
| Ресурс | Цена за час | Стоимость в месяц | Примечание |
|:---|:---|:---|:---|
| 1 vCPU | $0.031 | ~$22 | Стандартный тариф |
| 1 GB RAM | $0.004 | ~$2.9 | Стандартный тариф |
| 1 GPU (A100) | $1.50 | ~$1,080 | Премиум тариф |
| 1 GB хранилища | $0.0001 | ~$0.07 | SSD/NVMe |
| 1 GB сети | $0.01 | $0.01 | Исходящий трафик |

### 4. Установка через Helm с настройкой Retention

Рекомендуется устанавливать Kubecost, отключая встроенный Prometheus, если в кластере уже есть Kube-Prometheus-Stack, чтобы избежать дублирования метрик.

**Предварительные требования:**
- Kubernetes кластер версии 1.20+
- Helm 3.x установлен
- Доступ к кластеру через kubectl
- Prometheus уже развернут в кластере (опционально)

**Шаг 1: Подготовка репозитория**
```bash
helm repo add kubecost https://kubecost.github.io/cost-analyzer/
# → "kubecost" has been added to your repositories
helm repo update
# → ...Successfully got an update from the "kubecost" chart repository
```

**Шаг 2: Настройка и установка**
```bash
# Установка с интеграцией существующего Prometheus
helm install kubecost kubecost/cost-analyzer \
  --namespace kubecost \
  --create-namespace \
  --set global.prometheus.fqdn="http://prometheus-operated.monitoring.svc:9090" \
  --set global.prometheus.enabled=false \
  --set prometheusRule.enabled=true \
  --set kubecostToken="YOUR_TOKEN" \
  --set costAnalyzer.resources.requests.cpu=500m \
  --set costAnalyzer.resources.requests.memory=1Gi \
  --set costAnalyzer.resources.limits.cpu=1000m \
  --set costAnalyzer.resources.limits.memory=2Gi
# → NAME: kubecost
# → STATUS: deployed
```

**Шаг 3: Валидация установки**
```bash
# Проверка статуса подов
kubectl get pods -n kubecost
# → NAME                                        READY   STATUS    RESTARTS   AGE
# → kubecost-cost-analyzer-xxxxx                2/2     Running   0          5m
# → kubecost-prometheus-server-xxxxx            1/1     Running   0          5m

# Проверка доступности API
kubectl port-forward -n kubecost svc/kubecost-cost-analyzer 9090:9090 &
curl http://localhost:9090/model/healthz
# → {"healthy":true}

# Проверка метрик
curl "http://localhost:9090/model/clusterCosts?window=1h"
# → {"data":{"totalCost":12.34,"cpuCost":5.67,"ramCost":3.45,"storageCost":3.22}}
```

### 5. Интеграция с Karpenter

В связке с **[Karpenter](../Autoscaling/Karpenter/overview.md)**, Kubecost помогает измерить экономический эффект от перехода на «group-less» автомасштабирование. Karpenter динамически заказывает оптимальные узлы (включая Spot), а Kubecost валидирует, насколько упала стоимость 1 часа работы кластера (`cluster run rate`) после внедрения.

**Методика сравнения:**
1. **До внедрения Karpenter**: Зафиксировать стоимость кластера за 7 дней (baseline)
2. **После внедрения Karpenter**: Сравнить стоимость за следующие 7 дней
3. **Расчет экономии**: `(baseline - current) / baseline * 100%`

**Пример PromQL для сравнения:**
```promql
# Стоимость кластера за последний час (Karpenter)
sum(kubecost_cluster_costs_hourly) * 24

# Стоимость кластера за последний час (до Karpenter)
sum(kubecost_cluster_costs_hourly{cluster="old-cluster"}) * 24

# Экономия в процентах
(1 - (
  sum(kubecost_cluster_costs_hourly{cluster="new-cluster"})
  / sum(kubecost_cluster_costs_hourly{cluster="old-cluster"})
)) * 100
```

### 6. Диагностика и устранение неполадок

**Типичные ошибки и их решения:**

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `No data available` | Prometheus недоступен | Проверьте `global.prometheus.fqdn` в values.yaml |
| `Cost data not accurate` | Неправильные цены | Проверьте `kubecostProductConfigs` в values.yaml |
| `GPU metrics missing` | Отсутствует GPU exporter | Установите `nvidia-device-plugin` |
| `High memory usage` | Слишком много метрик | Уменьшите retention или отключите неиспользуемые коллекторы |
| `API timeout` | Перегрузка Cost Analyzer | Увеличьте ресурсы или количество реплик |

**Диагностические команды:**
```bash
# Проверка логов Cost Analyzer
kubectl logs -n kubecost -l app=kubecost-cost-analyzer --tail=100

# Проверка доступности Prometheus
kubectl exec -it -n kubecost deploy/kubecost-cost-analyzer -- \
  curl -s http://prometheus-operated.monitoring.svc:9090/api/v1/status/config

# Проверка использования ресурсов
kubectl top pods -n kubecost

# Проверка конфигурации
kubectl get configmap -n kubecost kubecost-cost-analyzer-config -o yaml

# Принудительное обновление данных
kubectl exec -it -n kubecost deploy/kubecost-cost-analyzer -- \
  curl -X POST http://localhost:9090/model/refresh
```

### 7. Оптимизация производительности Kubecost

**Рекомендации по ресурсам:**

| Компонент | CPU Request | CPU Limit | Memory Request | Memory Limit |
|:---|:---|:---|:---|:---|
| Cost Analyzer | 500m | 1000m | 1Gi | 2Gi |
| Cluster Controller | 250m | 500m | 512Mi | 1Gi |
| Cluster Metrics | 250m | 500m | 256Mi | 512Mi |

**Оптимизация retention:**
```yaml
# values.yaml
kubecostProductConfigs:
  # Уменьшение retention для экономии места
  prometheus:
    retention: "15d"  # По умолчанию 30d

  # Отключение неиспользуемых метрик
  metrics:
    disabled:
      - "container_network_*"
      - "container_fs_*"
```

**Масштабирование:**
```yaml
# values.yaml для больших кластеров (>1000 подов)
costAnalyzer:
  replicas: 2
  resources:
    requests:
      cpu: 1000m
      memory: 2Gi
    limits:
      cpu: 2000m
      memory: 4Gi

  # Балансировка нагрузки
  service:
    type: ClusterIP
    annotations:
      service.kubernetes.io/topology-aware-hints: "auto"
```

## Дополнительная информация

### Безопасность и RBAC

Kubecost предоставляет ролевую модель доступа для управления просмотром и редактированием данных о затратах.

**Роли по умолчанию:**
| Роль | Описание | Доступ |
|:---|:---|:---|
| `readonly` | Просмотр данных о затратах | Чтение всех отчетов |
| `editor` | Редактирование конфигураций | Чтение + запись budgets |
| `admin` | Полный доступ | Управление пользователями и настройками |

**Настройка RBAC через ConfigMap:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: kubecost-rbac
  namespace: kubecost
data:
  rbac.yaml: |
    roles:
    - name: readonly
      rules:
      - apiGroups: [""]
        resources: ["namespaces", "pods", "nodes"]
        verbs: ["get", "list", "watch"]
      - apiGroups: ["kubecost.com"]
        resources: ["costallocations", "budgets"]
        verbs: ["get", "list"]

    - name: editor
      rules:
      - apiGroups: ["kubecost.com"]
        resources: ["costallocations", "budgets"]
        verbs: ["get", "list", "create", "update", "delete"]

    - name: admin
      rules:
      - apiGroups: ["*"]
        resources: ["*"]
        verbs: ["*"]
```

**Интеграция с OIDC/SSO:**
```yaml
# values.yaml
kubecostProductConfigs:
  auth:
    enabled: true
    oidc:
      enabled: true
      issuerURL: "https://auth.example.com"
      clientID: "kubecost"
      clientSecret: "YOUR_CLIENT_SECRET"
      redirectURI: "http://kubecost.example.com/callback"
      scopes:
        - openid
        - profile
        - email
```

### Высокая доступность (HA) для on-premise

Для обеспечения отказоустойчивости Kubecost в локальных кластерах:

**Режим 1: ReplicaSet с общим хранилищем**
```yaml
# values.yaml
costAnalyzer:
  replicas: 2
  resources:
    requests:
      cpu: 500m
      memory: 1Gi

  # Общее хранилище для данных
  persistence:
    enabled: true
    storageClass: "nfs-client"
    size: 50Gi
```

**Режим 2: Кластер с внешним балансировщиком**
- Используйте StatefulSet с отдельными PersistentVolume для каждого реплики
- Настройте DNS round-robin или внешний балансировщик
- Cost Analyzer подключается к ближайшему реплике

**Пример StatefulSet для HA:**
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: kubecost-cost-analyzer
  namespace: kubecost
spec:
  serviceName: kubecost-cost-analyzer
  replicas: 2
  selector:
    matchLabels:
      app: kubecost-cost-analyzer
  template:
    metadata:
      labels:
        app: kubecost-cost-analyzer
    spec:
      containers:
      - name: cost-analyzer
        image: kubecost/cost-analyzer:latest
        ports:
        - containerPort: 9090
        volumeMounts:
        - name: data
          mountPath: /var/lib/kubecost
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: "nfs-client"
      resources:
        requests:
          storage: 50Gi
```

### Резервное копирование и восстановление

**Бэкап конфигурации Kubecost:**
```bash
# Экспорт конфигурации
kubectl get configmap -n kubecost kubecost-cost-analyzer-config -o yaml > kubecost-config-backup.yaml

# Бэкап budgets
curl http://localhost:9090/model/budget > kubecost-budgets-backup.json

# Бэкап пользователей
curl http://localhost:9090/model/users > kubecost-users-backup.json
```

**Восстановление после сбоя:**
1. Восстановите конфигурацию: `kubectl apply -f kubecost-config-backup.yaml`
2. Перезапустите Cost Analyzer: `kubectl rollout restart deployment kubecost-cost-analyzer -n kubecost`
3. Восстановите budgets: `curl -X POST http://localhost:9090/model/budget -d @kubecost-budgets-backup.json`

### Требования к сети

**Порты Kubecost:**
| Порт | Протокол | Назначение |
|:---|:---|:---|
| 9090 | TCP | Web UI и API |
| 9003 | TCP | Metrics exporter |
| 9001 | TCP | Cluster Controller |

**Рекомендации по полосе пропускания:**
- Cost Analyzer → Prometheus: 10–100 Kbps (зависит от количества метрик)
- Cost Analyzer → Internet: 100–500 Kbps (для обновлений)
- Рекомендуется выделить отдельный VLAN для мониторинга

### Масштабирование

**Пороговые значения для масштабирования:**

| Метрика | Порог | Действие |
|:---|:---|:---|
| CPU Cost Analyzer | >70%持续 5 минут | Увеличьте ресурсы или добавьте реплики |
| Memory Cost Analyzer | >80% | Увеличьте limits.memory |
| API latency | >1s | Оптимизируйте retention или отключите метрики |
| Количество подов | >1000 | Рассмотрите федеративный подход |

**Рекомендации по масштабированию:**
- До 500 подов: 1 Cost Analyzer (0.5 CPU, 1GB RAM)
- 500–2000 подов: 2 Cost Analyzer (1 CPU, 2GB RAM каждый)
- Более 2000 подов: федеративный подход с отдельными Kubecost на кластер

### Интерфейсы управления

**CLI-команды для управления Kubecost:**
```bash
# Проверка статуса Kubecost
kubectl get pods -n kubecost

# Просмотр логов Cost Analyzer
kubectl logs -n kubecost -l app=kubecost-cost-analyzer --tail=100

# Проверка конфигурации
kubectl get configmap -n kubecost kubecost-cost-analyzer-config -o yaml

# Принудительное обновление данных
kubectl exec -it -n kubecost deploy/kubecost-cost-analyzer -- \
  curl -X POST http://localhost:9090/model/refresh

# Проверка доступности API
kubectl exec -it -n kubecost deploy/kubecost-cost-analyzer -- \
  curl -s http://localhost:9090/model/healthz
```

**API-эндпоинты:**
```bash
# Здоровье Kubecost
curl http://localhost:9090/model/healthz

# Стоимость кластера за последний час
curl "http://localhost:9090/model/clusterCosts?window=1h"

# Стоимость по namespace за последний день
curl "http://localhost:9090/model/allocation?window=1d&aggregate=namespace"

# Стоимость по deployment за последний час
curl "http://localhost:9090/model/allocation?window=1h&aggregate=deployment"

# Список budgets
curl http://localhost:9090/model/budget

# Создание бюджета
curl -X POST http://localhost:9090/model/budget \
  -H "Content-Type: application/json" \
  -d '{
    "name": "production-budget",
    "namespace": "production",
    "monthlyBudget": 1000,
    "alertThreshold": 80
  }'
```

### Устранение неполадок

**Диагностические команды:**
```bash
# Проверка состояния Kubecost
kubectl get pods -n kubecost
kubectl describe pod -n kubecost <pod-name>

# Проверка логов
kubectl logs -n kubecost <pod-name> --tail=100 --previous

# Проверка использования ресурсов
kubectl top pods -n kubecost

# Проверка сетевой доступности
kubectl exec -it -n kubecost <pod-name> -- curl -s http://localhost:9090/model/healthz

# Проверка конфигурации
kubectl exec -it -n kubecost <pod-name> -- cat /etc/kubecost/config.yaml
```

**Частые проблемы и решения:**

| Симптом | Вероятная причина | Решение |
|:---|:---|:---|
| Kubecost не запускается | Недостаточно ресурсов | Увеличьте limits в values.yaml |
| Метрики отсутствуют | Prometheus недоступен | Проверьте `global.prometheus.fqdn` |
| Высокое потребление CPU | Слишком много метрик | Уменьшите retention или отключите метрики |
| Дашборды пустые | Проблемы с аутентификацией | Проверьте `kubecostToken` в values.yaml |
| Алерты не отправляются | Ошибка в конфигурации | Проверьте `prometheusRule.enabled` |

### Интеграция с OpenCost API

Kubecost предоставляет REST API на основе OpenCost для интеграции с внешними системами.

**Примеры использования API:**
```python
import requests

# Получение стоимости namespace
response = requests.get(
    "http://kubecost:9090/model/allocation",
    params={
        "window": "1d",
        "aggregate": "namespace",
        "namespace": "production"
    }
)
data = response.json()
print(f"Стоимость production: ${data['data']['totalCost']:.2f}")

# Получение списка budgets
response = requests.get("http://kubecost:9090/model/budget")
budgets = response.json()
for budget in budgets['data']:
    print(f"{budget['name']}: ${budget['monthlyBudget']}/мес")
```

### Смежные темы

- **[Monitoring and Logging Architecture](./kubernetes-monitoring-logging-architecture.md)** — архитектура мониторинга в Kubernetes
- **[Karpenter](../Autoscaling/Karpenter/overview.md)** — автоматическое масштабирование узлов
- **[Prometheus Operator](../../Prometheus/kubernetes/overview.md)** — источник данных телеметрии для Kubecost
- **[Metrics Server](./metrics-server.md)** — базовая агрегация метрик
- **[FinOps Foundation (CNCF)](https://www.finops.org/)** — лучшие практики управления облачными финансами и фреймворки