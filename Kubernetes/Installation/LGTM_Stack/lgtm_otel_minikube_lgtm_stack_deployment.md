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

**kube-prometheus-stack** — основной Helm-чарт для развертывания экосистемы мониторинга на базе Prometheus Operator в Kubernetes. Подробнее: **[kube-prometheus-stack: Обзор](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md)**.

**Loki** — система сбора и хранения логов, оптимизированная по стоимости за счет индексации только метаданных. Подробнее: **[Loki: Обзор](../../../Loki/loki_overview.md)**.

**Tempo** — высокомасштабируемое распределенное хранилище трассировок. Подробнее: **[Tempo: Обзор](../../../Tempo/index.md)**.

**Grafana** — универсальная платформа для визуализации всех типов сигналов телеметрии (метрики, логи, трейсы). Подробнее: **[Grafana: Обзор](../../../Grafana/grafana_overview.md)**.

**Кросс-сигнальная корреляция** — механизм связывания различных типов данных: переход от метрик к трассировкам (**Exemplars**), извлечение TraceID из логов (**Derived Fields**) и поиск логов, соответствующих конкретным спанам (**Traces to Logs**).

---

## Основные концепции

### Архитектура стека LGTM в Minikube

```text
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

### Состав и версии компонентов (на июль 2026 г.)

| Компонент | Helm-чарт | Версия чарта | Репозиторий |
| :--- | :--- | :--- | :--- |
| **K8s Monitoring** | `kube-prometheus-stack` | 87.19.0 | `prometheus-community` |
| **Loki** | `loki` | 18.5.1 | `grafana-community` |
| **Tempo** | `tempo` | 2.2.2 | `grafana-community` |
| **Grafana** | `grafana` (в составе стека) | 12.8.0 | `grafana` |

### Ресурсные требования

Для стабильной работы всего стека на Minikube рекомендуются следующие параметры:

| Компонент | CPU (request/limit) | Memory (request/limit) |
| :--- | :--- | :--- |
| **Prometheus** | 200m / 1000m | 512Mi / 2Gi |
| **Grafana** | 100m / 500m | 256Mi / 512Mi |
| **Loki** | 100m / 500m | 256Mi / 512Mi |
| **Tempo** | 100m / 500m | 128Mi / 512Mi |

**Минимальные параметры Minikube:** `--cpus 4 --memory 8192mb`

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
  --version 87.19.0 \
  -f - <<EOF
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
      url: http://loki.loki:3100
      jsonData:
        derivedFields:
          - datasourceUid: tempo
            matcherRegex: "traceID=(\\\\w+)"
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

---

### Сценарий 2: Развертывание Loki и Tempo

**Цель:** Дополнить стек системами хранения логов и трассировок.

#### Шаг 1: Подготовка репозитория сообщества

С 2026 года OSS-чарты Loki и Tempo переехали в `grafana-community`.

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update
```

#### Шаг 2: Установка Loki

```bash
helm upgrade --install loki grafana-community/loki \
  --namespace loki \
  --create-namespace \
  --version 18.5.1 \
  --set service.port=3100 \
  --set ingress.enabled=true \
  --set ingress.hosts[0]=loki.test \
  --set ingress.annotations."cert-manager.io/cluster-issuer"=minikube-ca-issuer
```

#### Шаг 3: Установка Tempo

```bash
helm upgrade --install tempo grafana-community/tempo \
  --namespace tempo \
  --create-namespace \
  --version 2.2.2 \
  --set service.port=3200
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

### Устранение неисправностей

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Prometheus OOMKilled** | Высокая интенсивность метрик | Увеличить memory limits до 2.5Gi в values.yaml |
| **Loki 404/502 в Grafana** | Неверный внутренний URL | Проверить доступность: `http://loki.loki:3100` (формат `<svc>.<ns>:<port>`) |
| **Нет ссылок на трейсы в логах** | Ошибка в `matcherRegex` | Проверить экранирование обратных слешей в YAML-конфигурации (нужно `\\\\w+`) |
| **Ingress не работает** | Аддон nginx не включен | Выполнить `minikube addons enable ingress` |

### Диагностические команды

```bash
# Проверка статуса всех компонентов стека
kubectl get all -n monitoring
kubectl get all -n loki
kubectl get all -n tempo

# Просмотр логов Grafana для отладки Data Sources
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana --tail=100
```

### Связанные материалы SSoT

- **[kube-prometheus-stack: Конфигурация](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md)**
- **[Loki: Практические сценарии](../../../Loki/loki_overview.md)**
- **[Tempo: Операции и TraceQL](../../../Tempo/index.md)**
- **[Grafana: Визуализация](../../../Grafana/grafana_overview.md)**

### Безопасность и хранение данных

> **Внимание:** Текущая конфигурация использует эфемерное хранилище (emptyDir). После перезапуска Minikube данные будут потеряны.

| Аспект | Данное руководство | Production |
| :--- | :--- | :--- |
| **Persistence** | Отключена (emptyDir) | PersistentVolumes (SSD) или S3-бакеты |
| **Метрики** | Prometheus (single) | Grafana Mimir (Distributed) |
| **Auth** | Базовая (admin/pass) | OIDC (Keycloak, Okta, Google) |
| **Сбор данных** | Скрейпинг Prometheus | **[Grafana Alloy](../../../Grafana/grafana_alloy_overview.md)** |

---

**Навигация по руководству:**

- **[Предварительные требования](./lgtm_otel_minikube_prerequisites_environment.md)** (назад)
- **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)** (вперед)
