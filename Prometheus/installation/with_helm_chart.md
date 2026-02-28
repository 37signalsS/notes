# Установка Alertmanager с помощью Helm-чарта

Помимо [ручной установки](./alertmanager_installation.md) или развертывания в составе комплексного стека [kube-prometheus-stack](../Kubernetes/Kube_Prometheus_Stack_Helm/overview.md), **Alertmanager** можно установить как отдельный компонент с помощью официального или комьюнити Helm-чарта. Этот подход обеспечивает хороший баланс между простотой и гибкостью.

## 1. Контекст

Установка через Helm-чарт является предпочтительным методом для Kubernetes, так как позволяет:
-   Декларативно управлять конфигурацией через `values.yaml`.
-   Легко интегрироваться с системами GitOps (ArgoCD, Flux).
-   Автоматизировать управление сложными объектами Kubernetes (StatefulSet, Service, Ingress и т.д.).

## 2. Установка

### 2.1. Конфигурация (`values.yaml`)

Создайте файл `values.yaml` для настройки Alertmanager. Минимальная конфигурация включает определение `ingress` для доступа к веб-интерфейсу и базовую конфигурацию самого Alertmanager.

**Пример `my-values.yaml`:**
```yaml
# my-values.yaml

# Переопределяем имя, чтобы оно было короче и чище
nameOverride: alertmanager

# Настройка Ingress для доступа к UI
ingress:
  enabled: true
  ingressClassName: nginx
  hosts:
    - host: alertmanager.my-domain.com
      paths:
        - path: /
          pathType: ImplementationSpecific
  # tls:
  #   - secretName: alertmanager-tls
  #     hosts:
  #       - alertmanager.my-domain.com

# Базовая конфигурация Alertmanager
# Для начала достаточно простой заглушки, чтобы сервис запустился.
# В дальнейшем здесь настраиваются маршруты (routes) и получатели (receivers).
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

# Запросы и лимиты ресурсов
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 200m
    memory: 256Mi

# Настройка персистентности (опционально, но рекомендуется для production)
persistence:
  enabled: true
  size: 2Gi
```

### 2.2. Развертывание через GitOps (ArgoCD)

Наиболее удобный способ развертывания — использование ArgoCD. Создайте `Application` манифест, который будет ссылаться на Helm-чарт и ваш файл с конфигурацией.

**Пример `argocd-app-alertmanager.yaml`:**
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
    # Укажите репозиторий с чартом
    repoURL: 'https://prometheus-community.github.io/helm-charts'
    chart: alertmanager
    targetRevision: 'x.y.z' # Укажите версию чарта
    helm:
      # Ссылка на ваш файл values
      valuesFiles:
        - 'values.yaml'
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: monitoring # Неймспейс для установки
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```
После применения этого манифеста ArgoCD установит Alertmanager в ваш кластер с указанной конфигурацией. Веб-интерфейс будет доступен по адресу, определенному в `ingress`.
