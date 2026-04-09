# Prometheus Operator Troubleshooting

## Definitions

**Troubleshooting Prometheus Operator** — процесс диагностики и устранения проблем в цикле reconciliation Operator'а, скрейпинге целей, отправке алертов и работе хранилища. Основные источники диагностической информации: логи Operator'а, статус Targets в Prometheus UI, события Kubernetes-объектов, метрики самого Operator'а.

> **SSoT по концепции Operator:** [Concepts](./concepts.md) — архитектура, CRD, принцип работы reconciliation.

## Basic Concepts

### Цикл reconciliation и точки отказа

Prometheus Operator работает по принципу контроллера Kubernetes: **Watch → Generate → Apply → Reload**. Сбой на любом этапе приводит к неработоспособности мониторинга.

| Этап | Симптом | Диагностика |
| :--- | :--- | :--- |
| **Watch** | CRD не обнаружены | `kubectl get crd \| grep monitoring.coreos.com` |
| **Generate** | Ошибка в конфигурации | Логи Operator: `config invalid` |
| **Apply** | RBAC error, Storage error | `kubectl describe pvc`, проверка ClusterRole |
| **Reload** | Цели не скрейпятся | Логи `prometheus-config-reloader`, `/targets` UI |

> **Подробнее:** [Prometheus CRD](./crd/prometheus.md), [ServiceMonitor](./crd/servicemonitor.md), [Alertmanager CRD](./crd/alertmanager.md).

### Основные метрики Operator

| Метрика | Описание |
| :--- | :--- |
| `prometheus_operator_reconcile_duration_seconds` | Длительность reconciliation |
| `prometheus_operator_reconcile_errors_total` | Ошибки reconciliation |
| `prometheus_operator_spec_replicas` | Количество реплик из spec |

> **См. также:** [Concepts — Метрики для мониторинга](./concepts.md#метрики-для-мониторинга-operator), [High Availability](./high_availability.md).

## Practical Scenarios

### ServiceMonitor не работает

#### Проверка ServiceMonitor

```bash
# Проверка существования ServiceMonitor
kubectl get servicemonitor -n monitoring

# Проверка конкретного ServiceMonitor
kubectl get servicemonitor my-app -n production -o yaml

# Проверка лейблов
kubectl get servicemonitor my-app -n production -o yaml | grep release
```

#### Соответствие лейблов

ServiceMonitor должен иметь лейблы, которые соответствуют селектору в Prometheus CRD:

```yaml
# В Prometheus CRD
spec:
  serviceMonitorSelector:
    matchLabels:
      release: monitoring

# В ServiceMonitor
metadata:
  labels:
    release: monitoring  # Должно совпадать!
```

> **Детали:** [ServiceMonitor CRD — как работает](./crd/servicemonitor.md#как-работает-servicemonitor).

#### Проверка Endpoints

```bash
# Проверка Endpoints сервиса
kubectl get endpoints -n production -l app=my-app

# Детальная информация
kubectl describe endpoints -n production -l app=my-app
```

#### Логи Operator

```bash
# Логи Prometheus Operator
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator

# Логи config-reloader
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-config-reloader
```

### Prometheus не скрейпит цели

#### Проверка статуса целей

```bash
# Через Prometheus UI: http://<prometheus>:9090/targets

# Через API
kubectl port-forward prometheus-main-0 -n monitoring 9090:9090
curl http://localhost:9090/api/v1/targets
```

#### Проверка сгенерированной конфигурации

```bash
# Проверка сгенерированной конфигурации
kubectl get secret prometheus-main -n monitoring -o jsonpath='{.data.prometheus\.yaml}' | base64 -d

# Проверка правил
kubectl get prometheusrule -n monitoring
```

#### Распространённые проблемы скрейпинга

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Цель не найдена** | Неправильный селектор ServiceMonitor | Проверить `selector.matchLabels` |
| **Нет Endpoints** | Service не имеет pod'ов | Проверить `kubectl get endpoints` |
| **404 на /metrics** | Неправильный путь | Проверить `endpoints.path` |
| **Timeout** | Долгий ответ приложения | Увеличить `scrapeTimeout` |

### Alertmanager не отправляет алерты

#### Проверка конфигурации

```bash
# Проверка Secret с конфигурацией
kubectl get secret alertmanager-main -n monitoring -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d
```

#### Проверка получателей и кластера

```bash
# Логи Alertmanager
kubectl logs -n monitoring -l app.kubernetes.io/name=alertmanager

# Проверка кластера
kubectl exec -it alertmanager-main-0 -n monitoring -- wget -qO- http://localhost:9094/api/v2/status
```

#### Проверка AlertmanagerConfig

```bash
# Проверка AlertmanagerConfig
kubectl get alertmanagerconfig -n monitoring

# Проверка селектора в Alertmanager
kubectl get alertmanager main -n monitoring -o yaml | grep -A5 configSelector
```

> **Детали:** [AlertmanagerConfig CRD — селекторы](./crd/alertmanagerconfig.md#селектор-alertmanager).

### Ошибки reconciliation

#### Проверка статуса Operator

```bash
# Проверка подов Operator
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-operator

# Логи Operator
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator --tail=100
```

#### Распространённые ошибки reconciliation

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **CRD not found** | CRD не установлены | `kubectl apply -f crd/` |
| **RBAC error** | Недостаточно прав | Проверить ClusterRole/Binding |
| **Config invalid** | Ошибка в конфигурации | Проверить YAML-синтаксис |
| **Storage error** | Проблема с PV | `kubectl describe pvc` |

### Проблемы с хранилищем

#### Проверка PVC

```bash
# Проверка PVC
kubectl get pvc -n monitoring

# Детальная информация
kubectl describe pvc prometheus-main -n monitoring
```

#### Проблемы с mount

```bash
# Проверка подов
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus

# События
kubectl describe pod prometheus-main-0 -n monitoring
```

> **Детали:** [Prometheus CRD — хранилище](./crd/prometheus.md#хранилище).

### Диагностика через Prometheus UI

#### Доступ к Prometheus

```bash
kubectl port-forward prometheus-main-0 -n monitoring 9090:9090
```

#### Полезные endpoint'ы

| Endpoint | Описание |
| :--- | :--- |
| `/targets` | Статус целей скрейпинга |
| `/rules` | Правила алертинга |
| `/alerts` | Активные алерты |
| `/config` | Текущая конфигурация |
| `/service-discovery` | Service Discovery |

### Полезные запросы PromQL

```promql
# Цели вниз
up == 0

# Ошибки скрейпинга
rate(prometheus_target_scrapes_exceeded_sample_limit_total[5m])

# Ошибки reconciliation
rate(prometheus_operator_reconcile_errors_total[5m])

# Статус Alertmanager
alertmanager_cluster_members
```

## Additional Information

### Связанные компоненты

| Компонент | Описание | Файл |
|---|---|---|
| **Concepts** | Базовые концепции Operator | [Concepts](./concepts.md) |
| **Installation** | Ручная установка Operator | [Installation](./installation.md) |
| **High Availability** | HA Prometheus и Alertmanager | [High Availability](./high_availability.md) |
| **CRD Overview** | Описание всех CRD | [CRD directory](./crd/) |

### Рекомендации по отладке

1. **Всегда начинайте с логов Operator'а** — большинство проблем связаны с неправильной конфигурацией CRD
2. **Проверяйте лейблы** — несоответствие `serviceMonitorSelector` и меток ServiceMonitor — самая частая причина
3. **Используйте `kubectl describe`** — события Kubernetes содержат информацию о проблемах с PVC, RBAC, networking
4. **Мониторьте метрики reconciliation** — рост `reconcile_errors_total` сигнализирует о системных проблемах
