# Установка Alertmanager с помощью Helm-чарта

## Определения

**Alertmanager** — компонент экосистемы Prometheus для обработки оповещений: дедупликация, группировка, маршрутизация.

**Helm** — менеджер пакетов для Kubernetes, упрощающий развертывание приложений через чарты.

> **См. также:** [Alertmanager](../alertmanager.md), [Helm](../../Kubernetes/MonitoringLogging/EFK/fluentbit/fluentbit_configuration.md).

## Основные концепции

### Актуальная версия чарта

| Параметр | Значение |
|---|---|
| **Репозиторий** | `prometheus-community/alertmanager` |
| **Последняя версия** | Проверьте на [Artifact Hub](https://artifacthub.io/packages/helm/prometheus-community/alertmanager) |
| **Версия Alertmanager** | 0.31.0 (февраль 2026) |

> **Важно:** Версии чарта и приложения могут отличаться. Проверяйте [официальный репозиторий](https://github.com/prometheus-community/helm-charts).

### Преимущества установки через Helm

* **Декларативность:** Конфигурация в `values.yaml`
* **GitOps:** Интеграция с ArgoCD, Flux
* **Версионирование:** Откат к предыдущим версиям
* **Шаблоны:** Автоматизация сложных манифестов

## Практические сценарии

### Базовая установка

**1. Добавление репозитория:**

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
```

**2. Создание `values.yaml`:**

```yaml
# values.yaml
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
    targetRevision: 'x.y.z'  # Укажите версию чарта
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

**Применение:**

```bash
kubectl apply -f argocd-app-alertmanager.yaml
```

### Продвинутая конфигурация

**Настройка Slack-уведомлений:**

```yaml
config:
  global:
    slack_api_url: 'https://hooks.slack.com/services/XXX/YYY/ZZZ'
  route:
    group_by: ['alertname', 'severity']
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 4h
    receiver: 'slack-notifications'
    routes:
      - match:
          severity: critical
        receiver: 'slack-critical'
  receivers:
    - name: 'slack-notifications'
      slack_configs:
        - channel: '#monitoring'
          send_resolved: true
    - name: 'slack-critical'
      slack_configs:
        - channel: '#alerts-critical'
          send_resolved: true
```

**Настройка Email-уведомлений:**

```yaml
config:
  global:
    smtp_smarthost: 'smtp.example.com:587'
    smtp_from: 'alertmanager@example.com'
    smtp_auth_username: 'alertmanager@example.com'
    smtp_auth_password: 'password'
  route:
    receiver: 'email-receiver'
  receivers:
    - name: 'email-receiver'
      email_configs:
        - to: 'team@example.com'
          send_resolved: true
```

> **См. также:** [Alertmanager — конфигурация](../alertmanager.md).

### Интеграция с Prometheus

**Добавьте в `values.yaml` Prometheus:**

```yaml
# Для kube-prometheus-stack
alertmanager:
  enabled: true
  config:
    global:
      resolve_timeout: 5m
    route:
      receiver: 'slack-notifications'
    receivers:
      - name: 'slack-notifications'
        slack_configs:
          - channel: '#monitoring'
```

**Или вручную в `prometheus.yml`:**

```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - 'alertmanager.monitoring.svc.cluster.local:9093'
```

## Дополнительная информация

### Проверка состояния

```bash
# Статус релиза
helm status alertmanager -n monitoring

# Логи
kubectl logs -n monitoring -l app.kubernetes.io/name=alertmanager

# Проверка конфигурации
kubectl exec -n monitoring deploy/alertmanager -- amtool check-config /etc/alertmanager/alertmanager.yml
```

### Обновление

```bash
# Обновление чарта
helm repo update
helm upgrade alertmanager prometheus-community/alertmanager \
  --namespace monitoring \
  -f values.yaml

# Откат
helm rollback alertmanager -n monitoring
```

### Удаление

```bash
helm uninstall alertmanager -n monitoring
```

### Связанные темы

* [Alertmanager](../alertmanager.md) — полное руководство
* [Alertmanager installation](./alertmanager_installation.md) — ручная установка
* [Kube-Prometheus-Stack](../../Linux/Networking/Services/BIND/overview.md) — полный стек
* [Rules](../rules.md) — создание правил алертинга
