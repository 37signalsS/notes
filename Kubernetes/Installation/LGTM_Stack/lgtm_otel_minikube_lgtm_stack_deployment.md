# Развертывание стека LGTM на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)** ← текущий
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**

## Определения

**Стек LGTM** — интегрированный набор компонентов [наблюдаемости](../../../Concepts/Observability_and_Monitoring/observability_definitions.md) от Grafana Labs: **L**oki (логи), **G**rafana (визуализация), **T**empo (трассировки), **M**imir/Prometheus (метрики). В данном руководстве используется Prometheus.

**kube-prometheus-stack** — Helm-чарт для развёртывания системы мониторинга на базе Prometheus в Kubernetes. Подробнее: **[kube-prometheus-stack overview](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md)**.

**Loki** — система агрегации логов с индексацией метаданных. Подробнее: **[Loki overview](../../../Loki/loki_overview.md)**.

**Tempo** — распределённое хранилище трассировок. Подробнее: **[Tempo overview](../../../Tempo/index.md)**.

**Grafana** — платформа визуализации и анализа данных. Подробнее: **[Grafana overview](../../../Grafana/grafana_overview.md)**.

**Кросс-сигнальная корреляция** — связывание сигналов: перехода от метрик к трассировкам (**Exemplars**), извлечение ID трассировки из логов (**Derived Fields**) и поиск логов по спанам (**Traces to Logs**).

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
│  │  grafana.test -> Grafana:3000 (TLS: grafana-tls)        │   │
│  │  loki.test    -> Loki:3100    (TLS: loki-tls)           │   │
│  │  tempo.test   -> Tempo:3200   (TLS: tempo-tls)          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Компоненты kube-prometheus-stack

| Компонент | Назначение | Тип workload |
| :--- | :--- | :--- |
| **Prometheus Server** | Сбор и хранение метрик | StatefulSet |
| **Alertmanager** | Маршрутизация алертов | StatefulSet |
| **Grafana** | Визуализация | Deployment |
| **Node Exporter** | Метрики хостов | DaemonSet |
| **Kube-State-Metrics** | Метрики объектов K8s | Deployment |
| **Prometheus Operator** | Управление через CRD | Deployment |

### Требования к ресурсам (Minikube)

| Компонент | CPU (request/limit) | Memory (request/limit) |
| :--- | :--- | :--- |
| **Prometheus** | 500m / 1000m | 512Mi / 2Gi |
| **Grafana** | 100m / 500m | 128Mi / 512Mi |
| **Loki** | 100m / 500m | 128Mi / 512Mi |
| **Tempo** | 100m / 500m | 128Mi / 512Mi |

**Минимальные требования кластера:** `--cpus 4 --memory 8192mb`

### Поток данных

1. **Метрики:** Экспортеры собирают данные → Prometheus скрейпит цели → данные в TSDB → Grafana визуализирует.
2. **Логи:** Приложения отправляют логи → Loki сохраняет чанки → Grafana запрашивает через LogQL.
3. **Трассировки:** Приложения экспортируют трейсы → Tempo принимает по OTLP → Grafana отображает.

---

## Практические сценарии

### Сценарий 1: Развёртывание Grafana, Prometheus и Alertmanager

**Цель:** Установить базовый стек мониторинга с преднастроенными data sources.

#### Шаг 1: Создание namespace

```bash
kubectl create namespace monitoring
```

#### Шаг 2: Установка kube-prometheus-stack

```bash
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
      url: http://loki.loki:3100
      jsonData:
        derivedFields:
          - datasourceUid: tempo
            matcherRegex: "traceID=(\\w+)"
            name: TraceID
            url: '\${__value.raw}'
    - name: Tempo
      type: tempo
      url: http://tempo.tempo:3200
      jsonData:
        serviceMap:
          datasourceUid: prometheus
        tracesToLogs:
          datasourceUid: loki
          filterByTraceID: true
          lokiSearch: true
        tracesToMetrics:
          datasourceUid: prometheus
          tags: '{job="agent-example-app"}'
EOF
```

#### Шаг 3: Настройка доступа

```bash
echo "$(minikube ip) grafana.test" | sudo tee -a /etc/hosts
```

#### Шаг 4: Проверка установки

```bash
# Пароль Grafana (по умолчанию prom-operator)
kubectl get secret --namespace monitoring prometheus-grafana \
  -o jsonpath="{.data.admin-password}" | base64 --decode ; echo

# Статус подов
kubectl get pods -n monitoring
```

---

### Сценарий 2: Развёртывание Loki и Tempo

**Цель:** Установить системы сбора логов и трассировок.

#### Шаг 1: Установка Loki

```bash
helm upgrade --install loki grafana/loki \
  --namespace loki \
  --create-namespace \
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
helm upgrade --install tempo grafana/tempo \
  --namespace tempo \
  --create-namespace \
  --set service.port=3200
```

#### Шаг 3: Настройка доступа

```bash
echo "$(minikube ip) loki.test" | sudo tee -a /etc/hosts
echo "$(minikube ip) tempo.test" | sudo tee -a /etc/hosts
```

---

## Дополнительная информация

### Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Pod в Pending** | Недостаточно памяти | Увеличить лимиты (requests.memory) |
| **Prometheus OOMKilled** | Мало памяти для TSDB | Увеличить лимиты до 2Gi |
| **Loki недоступен** | Ошибка URL | Проверить `http://loki.loki:3100` |
| **Нет корреляции** | Ошибка `derivedFields` | Проверить `matcherRegex` в Grafana |

### Диагностика

```bash
# Логи
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana --tail=50
kubectl logs -n loki -l app.kubernetes.io/name=loki --tail=50

# Проверка Ingress
kubectl get ingress -A
```

### Ссылки на SSoT

- **[kube-prometheus-stack](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md)**
- **[Loki overview](../../../Loki/loki_overview.md)**
- **[Tempo overview](../../../Tempo/index.md)**
- **[Grafana overview](../../../Grafana/grafana_overview.md)**

### Безопасность

> **Внимание:** Конфигурация только для тестовых окружений.

| Аспект | Конфигурация | Production |
| :--- | :--- | :--- |
| **TLS** | Самоподписанные | Let's Encrypt |
| **Аутентификация** | Базовая | OAuth2/OIDC |
| **Хранение** | Ephemeral | PersistentVolume / S3 |

### Альтернативы для production

| Компонент | Minikube | Production |
| :--- | :--- | :--- |
| **Метрики** | Prometheus | Grafana Mimir, VictoriaMetrics |
| **Логи** | Loki (single-binary) | Loki (микросервисы) |
| **Трассировки** | Tempo (single-binary) | Tempo (микросервисы) |
| **Хранилище** | ephemeral | S3, GCS, Azure Blob |
