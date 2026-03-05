# Устранение неполадок Prometheus Operator

## ServiceMonitor не работает

### Проверка ServiceMonitor

```bash
# Проверка существования ServiceMonitor
kubectl get servicemonitor -n monitoring

# Проверка конкретного ServiceMonitor
kubectl get servicemonitor my-app -n production -o yaml

# Проверка лейблов
kubectl get servicemonitor my-app -n production -o yaml | grep release
```

### Проверка лейблов

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

### Проверка Endpoints

```bash
# Проверка Endpoints сервиса
kubectl get endpoints -n production -l app=my-app

# Детальная информация
kubectl describe endpoints -n production -l app=my-app
```

### Логи Operator

```bash
# Логи Prometheus Operator
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator

# Логи config-reloader
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-config-reloader
```

## Prometheus не скрейпит цели

### Проверка статуса целей

```bash
# Через Prometheus UI
# Targets → проверить статус

# Через API
kubectl port-forward prometheus-main-0 -n monitoring 9090:9090
curl http://localhost:9090/api/v1/targets
```

### Проверка конфигурации

```bash
# Проверка сгенерированной конфигурации
kubectl get secret prometheus-main -n monitoring -o jsonpath='{.data.prometheus\.yaml}' | base64 -d

# Проверка правил
kubectl get prometheusrule -n monitoring
```

### Распространенные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Цель не найдена** | Неправильный селектор ServiceMonitor | Проверить `selector.matchLabels` |
| **Нет Endpoints** | Service не имеет pod'ов | Проверить `kubectl get endpoints` |
| **404 на /metrics** | Неправильный путь | Проверить `endpoints.path` |
| **Timeout** | Долгий ответ приложения | Увеличить `scrapeTimeout` |

## Alertmanager не отправляет алерты

### Проверка конфигурации

```bash
# Проверка Secret с конфигурацией
kubectl get secret alertmanager-main -n monitoring -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d
```

### Проверка получателей

```bash
# Логи Alertmanager
kubectl logs -n monitoring -l app.kubernetes.io/name=alertmanager

# Проверка кластера
kubectl exec -it alertmanager-main-0 -n monitoring -- wget -qO- http://localhost:9094/api/v2/status
```

### Проверка AlertmanagerConfig

```bash
# Проверка AlertmanagerConfig
kubectl get alertmanagerconfig -n monitoring

# Проверка селектора в Alertmanager
kubectl get alertmanager main -n monitoring -o yaml | grep -A5 configSelector
```

## Ошибки reconciliation

### Проверка статуса Operator

```bash
# Проверка подов Operator
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-operator

# Логи Operator
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator --tail=100
```

### Метрики Operator

```bash
# Длительность reconciliation
prometheus_operator_reconcile_duration_seconds

# Ошибки reconciliation
prometheus_operator_reconcile_errors_total
```

### Распространенные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **CRD not found** | CRD не установлены | `kubectl apply -f crd/` |
| **RBAC error** | Недостаточно прав | Проверить ClusterRole/Binding |
| **Config invalid** | Ошибка в конфигурации | Проверить YAML-синтаксис |
| **Storage error** | Проблема с PV | `kubectl describe pvc` |

## Проблемы с хранилищем

### Проверка PVC

```bash
# Проверка PVC
kubectl get pvc -n monitoring

# Детальная информация
kubectl describe pvc prometheus-main -n monitoring
```

### Проблемы с mount

```bash
# Проверка подов
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus

# События
kubectl describe pod prometheus-main-0 -n monitoring
```

## Диагностика через Prometheus UI

### Доступ к Prometheus

```bash
kubectl port-forward prometheus-main-0 -n monitoring 9090:9090
```

### Полезные endpoint'ы

| Endpoint | Описание |
| :--- | :--- |
| `/targets` | Статус целей скрейпинга |
| `/rules` | Правила алертинга |
| `/alerts` | Активные алерты |
| `/config` | Текущая конфигурация |
| `/service-discovery` | Service Discovery |

## Полезные запросы PromQL

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

## Связанные темы

* **[Concepts](./concepts.md)** — базовые концепции Operator
* **[Prometheus CRD](./crd/prometheus.md)** — описание Prometheus
* **[Alertmanager CRD](./crd/alertmanager.md)** — описание Alertmanager
