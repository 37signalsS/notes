# Развертывание стека LGTM на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)** ← текущий
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**

## Определения

**Стек LGTM** — интегрированный набор компонентов наблюдаемости от Grafana Labs: **L**oki (логи), **G**rafana (визуализация), **T**empo (трассировки), **M**imir/Prometheus (метрики). В данном руководстве используется Prometheus из состава `kube-prometheus-stack` как упрощённая альтернатива Mimir для локальных окружений.

**kube-prometheus-stack** — Helm-чарт для развёртывания полноценной системы мониторинга на базе Prometheus в Kubernetes. Включает Prometheus Operator, Prometheus Server, Alertmanager, Grafana, Node Exporter и Kube-State-Metrics. Полная документация: **[kube-prometheus-stack](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md)**.

**Loki** — горизонтально масштабируемая система агрегации логов, использующая подход Prometheus для индексации метаданных (меток). Экономичное хранилище с языком запросов LogQL. Подробнее: **[Loki overview](../../../Loki/loki_overview.md)**.

**Tempo** — высокомасштабируемое распределённое хранилище трассировок с поддержкой OpenTelemetry, Jaeger, Zipkin. Использует TraceQL для запросов и интегрируется с Grafana. Подробнее: **[Tempo overview](../../../Tempo/index.md)**.

**Grafana** — платформа для визуализации и анализа данных, объединяющая метрики, логи и трейсы в едином интерфейсе с поддержкой кросс-сигнальной корреляции. Подробнее: **[Grafana overview](../../../Grafana/grafana_overview.md)**.

**Кросс-сигнальная корреляция** — возможность перехода между сигналами наблюдаемости:

- **Exemplars:** переход от метрик Prometheus к трассировкам Tempo по `trace_id`
- **Derived Fields:** извлечение `trace_id` из логов Loki и переход к трассировке
- **Traces to Logs:** поиск логов по времени и меткам спана

---

## Основные концепции

### Архитектура стека LGTM

```
┌─────────────────────────────────────────────────────────────────┐
│                        Minikube Cluster                         │
│                                                                 │
│  ┌─────────────────┐     ┌─────────────────┐     ┌───────────┐ │
│  │    Grafana      │     │    Prometheus   │     │Alertmanager│ │
│  │   (UI + DS)     │◀────│   (Metrics DB)  │     │           │ │
│  │                 │     │                 │     └───────────┘ │
│  │  ┌───────────┐  │     └────────┬────────┘                   │
│  │  │   Loki    │  │              │                            │
│  │  │  (Logs)   │  │              ▼                            │
│  │  └───────────┘  │     ┌─────────────────┐                   │
│  │  ┌───────────┐  │     │  Kube-State-    │                   │
│  │  │   Tempo   │  │     │    Metrics      │                   │
│  │  │ (Traces)  │  │     └─────────────────┘                   │
│  │  └───────────┘  │                                           │
│  └────────┬────────┘                                           │
│           │                                                     │
│           ▼                                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              Ingress Controller (nginx)                 │   │
│  │                                                         │   │
│  │  grafana.test → Grafana:3000 (TLS: grafana-tls)        │   │
│  │  loki.test    → Loki:3100    (TLS: loki-tls)           │   │
│  │  tempo.test   → Tempo:3200   (TLS: tempo-tls)          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Компоненты kube-prometheus-stack

| Компонент | Назначение | Тип workload | Порт |
| :--- | :--- | :--- | :--- |
| **Prometheus Server** | Сбор и хранение метрик | StatefulSet | 9090 |
| **Alertmanager** | Обработка и маршрутизация алертов | StatefulSet | 9093 |
| **Grafana** | Визуализация и дашборды | Deployment | 3000 |
| **Node Exporter** | Метрики хостов (CPU, memory, disk) | DaemonSet | 9100 |
| **Kube-State-Metrics** | Метрики объектов Kubernetes | Deployment | 8080 |
| **Prometheus Operator** | Управление стеком через CRD | Deployment | 8080 |

### Требования к ресурсам (Minikube)

| Компонент | CPU (request/limit) | Memory (request/limit) |
| :--- | :--- | :--- |
| **Prometheus Server** | 500m / 1000m | 512Mi / 2Gi |
| **Grafana** | 100m / 500m | 128Mi / 512Mi |
| **Alertmanager** | 100m / 200m | 128Mi / 256Mi |
| **Loki** | 100m / 500m | 128Mi / 512Mi |
| **Tempo** | 100m / 500m | 128Mi / 512Mi |

**Минимальные требования Minikube:** `--cpus 4 --memory 8192mb`

### Поток данных

1. **Метрики:** Node Exporter и Kube-State-Metrics собирают данные → Prometheus скрейпит цели → данные сохраняются в TSDB → Grafana запрашивает для визуализации
2. **Логи:** Приложения пишут логи → Loki собирает через Push API → логи сжимаются в чанки → Grafana запрашивает через LogQL
3. **Трассировки:** Приложения экспортируют трейсы → Tempo принимает по OTLP/Jaeger/Zipkin → трейсы сохраняются в object storage → Grafana отображает

---

## Практические сценарии

### Сценарий 1: Развёртывание Grafana, Prometheus и Alertmanager

**Цель:** Установить базовый стек мониторинга с преднастроенными data sources для Loki и Tempo.

#### Шаг 1: Создание namespace

```bash
kubectl create namespace monitoring
```

#### Шаг 2: Установка kube-prometheus-stack

Установите Prometheus, Alertmanager и Grafana с кастомной конфигурацией data sources:

```bash
# Установка kube-prometheus-stack
helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set grafana.enabled=true \
  --set grafana.ingress.enabled=true \
  --set grafana.ingress.hosts[0]=grafana.test \
  --set grafana.ingress.tls[0].hosts[0]=grafana.test \
  --set grafana.ingress.tls[0].secretName=grafana-tls \
  --set grafana.ingress.ingressClassName=nginx \
  --set grafana.adminPassword=prom-operator \
  -f - <<EOF
grafana:
  additionalDataSources:
    - name: Loki
      type: loki
      access: proxy
      url: http://loki.loki:3100
      version: 1
      editable: true
      jsonData:
        derivedFields:
          - datasourceUid: tempo
            matcherRegex: "traceID=(\\w+)"
            name: TraceID
            url: '\${__value.raw}'
    - name: Tempo
      type: tempo
      access: proxy
      url: http://tempo.tempo:3200
      version: 1
      editable: true
      jsonData:
        httpHeaderName: "X-Scope-OrgID"
        httpHeaderValue: "tempo"
        serviceMap:
          datasourceUid: prometheus
        tracesToLogs:
          datasourceUid: loki
          filterByTraceID: true
          spanStartTimeShift: 1h
          spanEndTimeShift: 1h
          lokiSearch: true
        tracesToMetrics:
          datasourceUid: prometheus
          tags: '{job="agent-example-app"}'
          map:
            - operationName: "ping"
              spanKind: "server"
              metricQuery: 'sum(rate(traces_spanmetrics_latency_bucket{span_kind="server", service_name="agent-example-app", operation="ping", le="\$bucket"}[1m])) by (le)'
EOF
```

> **Примечание:** Data source Mimir закомментирован, так как в данном руководстве используется Prometheus из состава `kube-prometheus-stack`.

#### Шаг 3: Добавление записи в /etc/hosts

```bash
echo "$(minikube ip) grafana.test" | sudo tee -a /etc/hosts
```

#### Шаг 4: Получение пароля администратора Grafana

Пароль можно получить командой:

```bash
kubectl get secret --namespace monitoring prometheus-grafana \
  -o jsonpath="{.data.admin-password}" | base64 --decode ; echo
```

**По умолчанию:** `prom-operator` (указан в `--set grafana.adminPassword`)

#### Шаг 5: Проверка установки

```bash
# Проверка Pod
kubectl get pods -n monitoring

# Проверка сервисов
kubectl get svc -n monitoring

# Проверка Ingress
kubectl get ingress -n monitoring
```

**Ожидаемый результат:**

```
NAME                                              READY   STATUS    RESTARTS   AGE
prometheus-kube-prometheus-operator-xxxxx         1/1     Running   0          5m
prometheus-prometheus-kube-prometheus-xxxxx       1/1     Running   0          5m
prometheus-grafana-xxxxx                          1/1     Running   0          5m
prometheus-alertmanager-xxxxx                     1/1     Running   0          5m
```

---

### Сценарий 2: Развёртывание Loki и Tempo

**Цель:** Установить системы для сбора логов (Loki) и хранения трассировок (Tempo).

#### Шаг 1: Установка Loki

```bash
# Создание namespace
kubectl create namespace loki

# Установка Loki
helm upgrade --install loki grafana/loki \
  --namespace loki \
  --create-namespace \
  --set service.type=ClusterIP \
  --set service.port=3100 \
  --set ingress.enabled=true \
  --set ingress.host=loki.test \
  --set ingress.tls.enabled=true \
  --set ingress.tls.secretName=loki-tls \
  --set ingress.tls.issuerName=minikube-ca \
  --set ingress.tls.issuerKind=ClusterIssuer
```

#### Шаг 2: Установка Tempo

```bash
# Создание namespace
kubectl create namespace tempo

# Установка Tempo
helm upgrade --install tempo grafana/tempo \
  --namespace tempo \
  --create-namespace \
  --set service.type=ClusterIP \
  --set service.port=3200
```

> **Примечание:** Tempo не требует TLS для внутреннего взаимодействия. Для внешнего доступа можно включить Ingress аналогично Loki.

#### Шаг 3: Добавление записей в /etc/hosts

```bash
echo "$(minikube ip) loki.test" | sudo tee -a /etc/hosts
echo "$(minikube ip) tempo.test" | sudo tee -a /etc/hosts
```

#### Шаг 4: Проверка установки

```bash
# Проверка Loki
kubectl get pods -n loki
kubectl get ingress -n loki

# Проверка Tempo
kubectl get pods -n tempo
kubectl get svc -n tempo
```

---

## Дополнительная информация

### Troubleshooting

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Grafana Pod не запускается** | Недостаточно памяти | Увеличить лимиты: `--set grafana.resources.requests.memory=256Mi` |
| **Prometheus OOMKilled** | Мало памяти для TSDB | Увеличить `--set prometheus.prometheusSpec.resources.requests.memory=1Gi` |
| **Data source Loki не работает** | Loki недоступен | Проверить `kubectl get pods -n loki`, URL `http://loki.loki:3100` |
| **Нет корреляции Logs → Traces** | Неправильный `derivedFields` | Проверить `matcherRegex` и `datasourceUid` в конфигурации Grafana |
| **Tempo не принимает трейсы** | Неправильный endpoint | Проверить сервис `tempo.tempo:3200`, включить OTLP receiver |
| **Grafana недоступна по HTTPS** | TLS Secret не создан | Проверить `kubectl get secret grafana-tls -n monitoring` |

### Диагностика

```bash
# Логи компонентов
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana --tail=50
kubectl logs -n loki -l app.kubernetes.io/name=loki --tail=50
kubectl logs -n tempo -l app.kubernetes.io/name=tempo --tail=50

# Проверка data sources Grafana
kubectl get secret -n monitoring prometheus-grafana \
  -o jsonpath="{.data.datasources\.yaml}" | base64 -d

# Тестирование Loki
curl -k https://loki.test/loki/api/v1/labels

# Тестирование Tempo
curl -k http://tempo.tempo:3200/ready
```

### Ссылки на SSoT

- **Prometheus:**
  - **[kube-prometheus-stack overview](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md)**
  - **[Prometheus Operator CRD](../../Prometheus/kubernetes/operator/concepts.md)**
- **Loki:**
  - **[Loki overview](../../../Loki/loki_overview.md)**
  - **[LogQL](../../../Loki/loki_overview.md#Язык-запросов-LogQL)**
- **Tempo:**
  - **[Tempo overview](../../../Tempo/index.md)**
  - **[TraceQL](../../../Tempo/index.md)**
- **Grafana:**
  - **[Grafana overview](../../../Grafana/grafana_overview.md)**
  - **[Data sources](../../../Grafana/grafana_overview.md)**

### Безопасность

> **Внимание:** Данная конфигурация предназначена **только для локальных/тестовых окружений**.

| Аспект | Текущая конфигурация | Production-рекомендация |
| :--- | :--- | :--- |
| **TLS** | Самоподписанные сертификаты | Публичные сертификаты (Let's Encrypt) |
| **Аутентификация Grafana** | Базовая (admin/prom-operator) | OAuth2/OIDC, LDAP |
| **Хранение данных** | ephemeral (в Pod) | PersistentVolume, object storage (S3) |
| **Сетевая изоляция** | Отсутствует | NetworkPolicies, отдельные namespace |

### Альтернативы для production

| Компонент | Minikube (это руководство) | Production |
| :--- | :--- | :--- |
| **Метрики** | Prometheus (kube-prometheus-stack) | Grafana Mimir, VictoriaMetrics |
| **Логи** | Loki (single-binary) | Loki (микросервисы), Grafana Alloy |
| **Трассировки** | Tempo (single-binary) | Tempo (микросервисы), Jaeger v2 |
| **Агент** | Push API | Grafana Alloy, OTel Collector |
| **Хранилище** | ephemeral | S3, GCS, Azure Blob Storage |

### Ресурсы

- **[Artifact Hub: kube-prometheus-stack](https://artifacthub.io/packages/helm/prometheus-community/kube-prometheus-stack)**
- **[Grafana Helm Charts](https://grafana.github.io/helm-charts/)**
- **[Prometheus Community Helm Charts](https://prometheus-community.github.io/helm-charts/)**

---

**Навигация по руководству:**

- **[← Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
- **[Развертывание OpenTelemetry →](./lgtm_otel_minikube_opentelemetry_deployment.md)**
