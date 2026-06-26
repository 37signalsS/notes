# Установка Alertmanager через Helm-чарт

## Определения

**Alertmanager** — компонент экосистемы Prometheus для обработки оповещений: дедупликация, группировка, маршрутизация, подавление. Полное руководство — [Alertmanager](../alertmanager.md).

**Helm** — менеджер пакетов для Kubernetes. Обзор — [Helm overview](../../../Kubernetes/ToolsUtilities/Helm/helm_overview.md).

**kube-prometheus-stack** — umbrella Helm-чарт для развёртывания полного стека мониторинга (Prometheus, Alertmanager, Grafana, Exporters). Обзор — [kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/overview.md).

## Основные концепции

### Отличие standalone-чарта от kube-prometheus-stack

| Параметр | `prometheus-community/alertmanager` | `kube-prometheus-stack` (subchart) |
|---|---|---|
| **Назначение** | Только Alertmanager в K8s | Полный стек мониторинга |
| **Управление** | Прямое через `values.yaml` чарта | Через `alertmanager.*` в umbrella-чарте |
| **Сценарий** | Alertmanager уже есть свой Prometheus | Новое развёртывание с нуля |
| **Service Discovery** | Требует ручной настройки в Prometheus | Автоматический через Prometheus Operator |

### Актуальные версии

| Параметр | Значение |
|---|---|
| **Репозиторий standalone** | `prometheus-community/alertmanager` |
| **Версия Alertmanager** | 0.31.0 (февраль 2026) |
| **Минимальный Kubernetes** | 1.21+ |

> **Важно:** Версии чарта и приложения могут отличаться. Проверяйте [Artifact Hub](https://artifacthub.io/packages/helm/prometheus-community/alertmanager).

### Преимущества установки через Helm

* **Декларативность:** Конфигурация в `values.yaml`
* **GitOps:** Интеграция с ArgoCD, Flux
* **Версионирование:** Откат к предыдущим версиям
* **Шаблоны:** Автоматизация сложных манифестов

## Практические сценарии

### Базовая установка (standalone чарт)

**1. Добавление репозитория:**

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
```

**2. Создание `values.yaml`:**

```yaml
nameOverride: alertmanager

# Ingress для доступа к UI
ingress:
  enabled: true
  ingressClassName: nginx
  hosts:
    - host: alertmanager.my-domain.com
      paths:
        - path: /
          pathType: ImplementationSpecific

# Конфигурация Alertmanager
config:
  global:
    resolve_timeout: 5m
  route:
    group_by: ['job']
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 12h
    receiver: 'null'
  receivers:
    - name: 'null'

# Ресурсы
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 200m
    memory: 256Mi

# Персистентность
persistence:
  enabled: true
  size: 2Gi
```

> Структура `config` идентична [alertmanager.yml](../alertmanager.md#конфигурация-alertmanageryml).

**3. Установка:**

```bash
helm install alertmanager prometheus-community/alertmanager \
  --namespace monitoring \
  --create-namespace \
  -f values.yaml
```

**4. Проверка:**

```bash
helm status alertmanager -n monitoring
kubectl get pods -n monitoring -l app.kubernetes.io/name=alertmanager
```

### Установка через GitOps (ArgoCD)

**Application манифест:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: alertmanager
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: 'https://prometheus-community.github.io/helm-charts'
    chart: alertmanager
    targetRevision: 'x.y.z'
    helm:
      valuesFiles:
        - 'values.yaml'
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: monitoring
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

### Интеграция с Prometheus

**В `prometheus.yml` укажите target Alertmanager:**

```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - 'alertmanager.monitoring.svc.cluster.local:9093'
```

> Для kube-prometheus-stack интеграция автоматическая — см. [Alertmanager config in kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/alertmanager_config.md).

### Проверка конфигурации

```bash
# Проверка синтаксиса внутри пода
kubectl exec -n monitoring deploy/alertmanager -- \
  amtool check-config /etc/alertmanager/alertmanager.yml

# Логи
kubectl logs -n monitoring -l app.kubernetes.io/name=alertmanager

# Статус релиза
helm status alertmanager -n monitoring
```

## Дополнительная информация

### Обновление чарта

```bash
helm repo update
helm upgrade alertmanager prometheus-community/alertmanager \
  --namespace monitoring \
  -f values.yaml

# Откат к предыдущей версии
helm rollback alertmanager -n monitoring
```

### Удаление

```bash
helm uninstall alertmanager -n monitoring
```

### См. также

Архитектура и конвейер обработки оповещений — [Alertmanager](../alertmanager.md). Бинарная установка и Docker — [Alertmanager installation — manual](./alertmanager_installation.md). Конфигурация Alertmanager в umbrella-чарте — [Alertmanager config in kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/alertmanager_config.md). Обзор всех способов установки — [Installation overview](./overview.md).
