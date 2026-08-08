# Развертывание стека LGTM на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)** (текущий)
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**

---

## Определения

**Стек LGTM** — это интегрированное решение для реализации [наблюдаемости (observability)](../../../Concepts/Observability_and_Monitoring/observability_definitions.md) от Grafana Labs. Название образовано от первых букв компонентов: **L**oki (логи), **G**rafana (визуализация), **T**empo (трассировки), **M**imir (метрики). В данном руководстве для работы с метриками используется Prometheus как более легковесная альтернатива для Minikube.

**kube-prometheus-stack** — основной Helm-чарт для развертывания экосистемы мониторинга на базе Prometheus Operator в Kubernetes. Включает в себя Prometheus, Alertmanager, Grafana и набор экспортеров (Node Exporter, kube-state-metrics). Подробнее: **[kube-prometheus-stack: Обзор](../../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md)**.

**Loki** — система сбора и хранения логов, оптимизированная по стоимости за счет индексации только метаданных. Подробнее: **[Loki: Обзор](../../../Loki/loki_overview.md)**.

**Tempo** — высокомасштабируемое распределенное хранилище трассировок. Подробнее: **[Tempo: Обзор](../../../Tempo/index.md)**.

**Grafana** — универсальная платформа для визуализации всех типов сигналов телеметрии (метрики, логи, трейсы). Подробнее: **[Grafana: Обзор](../../../Grafana/grafana_overview.md)**.

**Alertmanager** — компонент для обработки алертов, отправляемых Prometheus, их группировки, дедупликации и маршрутизации в каналы уведомлений.

**Grafana Alloy** — универсальный агент (наследник Grafana Agent) для сбора и передачи телеметрии, рекомендуемый для современных инсталляций (2025–2026 гг.). Подробнее: **[Grafana Alloy: Обзор](../../../Grafana/grafana_alloy_overview.md)**.

**Кросс-сигнальная корреляция** — механизм связывания различных типов данных: переход от метрик к трассировкам (**Exemplars**), извлечение TraceID из логов (**Derived Fields**) и поиск логов, соответствующих конкретным спанам (**Traces to Logs**).

---

## Основные концепции

### Архитектура стека LGTM в Minikube

```text
┌───────────────────────────────────────────────────────────────────┐
│                        Minikube Cluster                           │
│                                                                   │
│  ┌──────────────────┐     ┌─────────────────┐     ┌───────────┐   │
│  │    Grafana       │     │    Prometheus   │     │Alertmanager│   │
│  │   (UI + DS)      │◀────│  (Metrics DB)   │◀────│ (Alerts)  │   │
│  │                  │     │   + Exemplars   │     └───────────┘   │
│  │  ┌────────────┐  │     └────────┬────────┘           ▲         │
│  │  │    Loki    │  │              │                    │         │
│  │  │   (Logs)   │  │              ▼                    │         │
│  │  └────────────┘  │     ┌─────────────────┐    ┌──────┴─────┐   │
│  │  ┌────────────┐  │     │  Kube-State-    │    │   Node     │   │
│  │  │    Tempo   │  │     │    Metrics      │    │ Exporter   │   │
│  │  │  (Traces)  │  │     └─────────────────┘    └────────────┘   │
│  └────────┬─────────┘                                             │
│           │                                                       │
│           ▼                                                       │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │               Ingress Controller (nginx)                  │   │
│  │                                                           │   │
│  │  grafana.test -> Grafana:3000 (TLS: grafana-tls)          │   │
│  │  loki.test    -> Loki:3100    (TLS: loki-tls)             │   │
│  │  tempo.test   -> Tempo:3200   (TLS: tempo-tls)            │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

### Состав и версии компонентов (на август 2026 г.)

| Компонент | Helm-чарт | Версия чарта | Репозиторий |
| :--- | :--- | :--- | :--- |
| **K8s Monitoring** | `kube-prometheus-stack` | 88.1.3 | `prometheus-community` |
| **Alertmanager** | (в составе стека) | 0.30.x | `prometheus-community` |
| **Kube-State-Metrics** | (в составе стека) | 2.15.x | `prometheus-community` |
| **Node Exporter** | (в составе стека) | 1.10.x | `prometheus-community` |
| **Loki** | `loki` | 18.7.1 | `oci://ghcr.io/grafana-community/helm-charts/loki` |
| **Tempo** (Monolithic) | `tempo` | 3.0.0 | `oci://ghcr.io/grafana-community/helm-charts/tempo` |
| **Grafana** | `grafana` (в составе стека) | 12.9.0 | `grafana` |

### Ресурсные требования

Для стабильной работы всего стека на Minikube рекомендуются следующие параметры:

| Компонент | CPU (request/limit) | Memory (request/limit) |
| :--- | :--- | :--- |
| **Prometheus** | 200m / 1000m | 512Mi / 2Gi |
| **Grafana** | 100m / 500m | 256Mi / 512Mi |
| **Loki** | 100m / 500m | 256Mi / 512Mi |
| **Tempo** | 100m / 500m | 128Mi / 512Mi |

**Минимальные параметры Minikube:** `--cpus 4 --memory 8192mb`. Для полноценного использования с распределенным Tempo и Loki рекомендуется `--memory 12288mb`.

---

## Практические сценарии

### Сценарий 1: Развертывание ядра мониторинга (Prometheus + Grafana)

**Цель:** Установить Prometheus Operator и Grafana с преднастроенными источниками данных и корреляцией.

#### Шаг 1: Подготовка репозиториев

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
```

#### Шаг 2: Установка kube-prometheus-stack

```bash
helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --version 88.1.3 \
  -f - <<EOF
prometheus:
  prometheusSpec:
    enableFeatures:
      - exemplars
      - otlp-write-receiver
    retention: 2d
    storageSpec:
      volumeClaimTemplate:
        spec:
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 5Gi

grafana:
  enabled: true
  adminPassword: prom-operator
  ingress:
    enabled: true
    ingressClassName: nginx
    hosts:
      - grafana.test
    tls:
      - secretName: grafana-tls
        hosts:
          - grafana.test
  additionalDataSources:
    - name: Loki
      type: loki
      uid: loki
      url: http://loki.loki:3100
      jsonData:
        derivedFields:
          - datasourceUid: tempo
            matcherRegex: "traceID=(\\\\w+)"
            name: TraceID
            url: '\${__value.raw}'
    - name: Tempo
      type: tempo
      uid: tempo
      url: http://tempo.tempo:3200
      jsonData:
        serviceMap:
          datasourceUid: prometheus
        nodeGraph:
          enabled: true
        tracesToLogs:
          datasourceUid: loki
          filterByTraceID: true
          lokiSearch: true
        tracesToMetrics:
          datasourceUid: prometheus
          tags: '{job="agent-example-app"}'
        lokiSearch:
          datasourceUid: loki
    - name: Prometheus
      type: prometheus
      uid: prometheus
      url: http://prometheus-operated.monitoring:9090
      jsonData:
        exemplars:
          - datasourceUid: tempo
            internal: true
EOF
```

> **Примечание:** Включение `exemplars` позволяет переходить от точек на графиках метрик сразу к соответствующим трассировкам в Tempo при наличии TraceID в метках метрик (что делает OTel Collector). `otlp-write-receiver` позволяет Prometheus принимать метрики по протоколу OTLP напрямую.

---

### Сценарий 2: Развертывание Loki и Tempo с использованием OCI

**Цель:** Дополнить стек современными версиями систем хранения логов и трассировок.

#### Шаг 1: Установка Loki (OCI)

```bash
helm upgrade --install loki oci://ghcr.io/grafana-community/helm-charts/loki \
  --namespace loki \
  --create-namespace \
  --version 18.7.1 \
  -f - <<EOF
loki:
  auth_enabled: false
  commonConfig:
    replication_factor: 1
  storage:
    type: 'filesystem'
singleBinary:
  replicas: 1
read:
  replicas: 0
write:
  replicas: 0
backend:
  replicas: 0
gateway:
  enabled: true
  ingress:
    enabled: true
    hosts:
      - host: loki.test
        paths:
          - path: /
            pathType: Prefix
EOF
```

#### Шаг 2: Установка Tempo (OCI)

Для Minikube рекомендуется использовать монолитную версию Tempo (`tempo`), а не распределенную (`tempo-distributed`), для экономии ресурсов.

```bash
helm upgrade --install tempo oci://ghcr.io/grafana-community/helm-charts/tempo \
  --namespace tempo \
  --create-namespace \
  --version 3.0.0 \
  --set tempo.storage.trace.backend=local \
  --set tempo.resources.requests.cpu=100m \
  --set tempo.resources.requests.memory=128Mi
```

---

### Сценарий 3: Настройка доступа и проверка корреляции

#### Шаг 1: Настройка локального DNS

```bash
echo "$(minikube ip) grafana.test" | sudo tee -a /etc/hosts
echo "$(minikube ip) loki.test" | sudo tee -a /etc/hosts
```

#### Шаг 2: Валидация Data Sources

1. Зайти в Grafana (`grafana.test`, логин `admin`, пароль `prom-operator`).
2. Перейти в **Connections -> Data Sources**.
3. Нажать **Save & Test** для Loki и Tempo.
4. Убедиться, что в настройках Loki включены **Derived Fields** для связи с Tempo.

---

## Дополнительная информация

### Настройка персистентности (Persistence)

По умолчанию данные хранятся в эфемерных томах. Для сохранения данных при перезагрузке Minikube используйте `hostPath` или локальный `StorageClass`.

```yaml
# Пример включения persistence для Prometheus
prometheus:
  prometheusSpec:
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: standard
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 10Gi
```

### Устранение неисправностей

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Prometheus OOMKilled** | Высокая интенсивность метрик | Увеличить memory limits до 2.5Gi в values.yaml |
| **Loki 404/502 в Grafana** | Неверный внутренний URL | Проверить доступность: `http://loki.loki:3100` (формат `<svc>.<ns>:<port>`) |
| **Нет ссылок на трейсы в логах** | Ошибка в `matcherRegex` | Проверить экранирование обратных слешей в YAML (нужно `\\\\w+`) |
| **Exemplars не отображаются** | `enableFeatures` не включен | Убедиться, что в конфигурации Prometheus есть `- exemplars` |
| **Ingress не работает** | Аддон nginx не включен | Выполнить `minikube addons enable ingress` |
| **Alertmanager не шлет алерты** | Ошибка маршрутизации | Проверить `kubectl logs` пода Alertmanager и `ConfigMap` |

### Диагностические команды

```bash
# Проверка статуса всех компонентов стека
kubectl get all -n monitoring
kubectl get all -n loki
kubectl get all -n tempo

# Проверка включенных фич в Prometheus
kubectl get prometheus -n monitoring -o yaml | grep enableFeatures -A 3

# Просмотр логов Grafana для отладки Data Sources
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana --tail=100
```

### См. также
- **[Grafana Alloy: Современный агент для LGTM](../../../Grafana/grafana_alloy_overview.md)**
- **[OpenTelemetry: Интеграция с LGTM](../../../OpenTelemetry/opentelemetry_overview.md)**
- **[Kube-Prometheus-Stack: Продвинутая настройка](../../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md)**

### Связанные материалы SSoT

- **[kube-prometheus-stack: Конфигурация](../../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md)**
- **[Loki: Практические сценарии](../../../Loki/loki_overview.md)**
- **[Tempo: Операции и TraceQL](../../../Tempo/index.md)**
- **[Grafana: Визуализация](../../../Grafana/grafana_overview.md)**

### Безопасность и хранение данных

> **Внимание:** Текущая конфигурация в базовом варианте использует эфемерное хранилище (emptyDir). После перезапуска Minikube данные будут потеряны, если не настроена персистентность.

| Аспект | Данное руководство | Production |
| :--- | :--- | :--- |
| **Persistence** | Отключена по умолчанию | PersistentVolumes (SSD) или S3-бакеты |
| **Метрики** | Prometheus (single) | Grafana Mimir (Distributed) |
| **Auth** | Базовая (admin/pass) | OIDC (Keycloak, Okta, Google) |
| **Сбор данных** | Скрейпинг Prometheus | **[Grafana Alloy](../../../Grafana/grafana_alloy_overview.md)** |

---

**Навигация по руководству:**

- **[Предварительные требования](./lgtm_otel_minikube_prerequisites_environment.md)** (назад)
- **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)** (вперед)
