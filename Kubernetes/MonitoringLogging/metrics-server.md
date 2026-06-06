# Metrics Server: Агрегатор метрик ресурсов

## Определения

**Metrics Server** — легковесный in-memory (работающий в оперативной памяти) агрегатор данных об использовании ресурсов в кластере Kubernetes. Собирает метрики CPU (Central Processing Unit) и RAM (Random Access Memory) с каждого узла через Summary API (Application Programming Interface) (`kubelet`), предоставляет их через Metrics API (`metrics.k8s.io`).

Не предназначен для долгосрочного хранения метрик и сложного анализа. Основная задача — предоставление актуальных данных о потреблении ресурсов для других компонентов Kubernetes.

## Основные концепции

### Назначение

**Включение `kubectl top`** — без Metrics Server команды `kubectl top nodes` и `kubectl top pods` не работают, так как запрашивают данные из Metrics API.

**Основа для автоскейлинга:**

- **Horizontal Pod Autoscaler (HPA)** использует данные Metrics Server для масштабирования количества подов в `Deployment`/`StatefulSet` на основе CPU/memory.
- **Vertical Pod Autoscaler (VPA)** использует метрики для рекомендации или автоматического изменения `requests` и `limits` контейнеров.

### Архитектура

- **Deployment** — развертывается как `Deployment` в namespace (пространстве имен) `kube-system`.
- **Сбор данных** — периодически опрашивает все `kubelet` в кластере.
- **API** — регистрируется в `kube-aggregator` как `APIService` с `v1beta1.metrics.k8s.io`.

## Практические сценарии

### Установка

Установка выполняется применением одного манифеста, который содержит все необходимые компоненты (`ServiceAccount`, `ClusterRole`, `Deployment`, `APIService` и др.).

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
# → serviceaccount/metrics-server created
# → clusterrole.rbac.authorization.k8s.io/system:aggregated-metrics-reader created
# → clusterrole.rbac.authorization.k8s.io/system:metrics-server created
# → rolebinding.rbac.authorization.k8s.io/metrics-server-auth-reader created
# → clusterrolebinding.rbac.authorization.k8s.io/metrics-server:system:auth-delegator created
# → clusterrolebinding.rbac.authorization.k8s.io/system:metrics-server created
# → service/metrics-server created
# → deployment.apps/metrics-server created
# → apiservice.apiregistration.k8s.io/v1beta1.metrics.k8s.io created
```

> **Примечание:** В некоторых случаях (например, в Minikube или при использовании самоподписанных сертификатов в кластере) может потребоваться модифицировать `Deployment` Metrics Server, добавив флаг `--kubelet-insecure-tls`, чтобы разрешить подключение к kubelet'ам без проверки TLS (Transport Layer Security) сертификата.

После установки убедитесь, что под `metrics-server` в `kube-system` namespace успешно запустился:

```bash
kubectl get pods -n kube-system | grep metrics-server
# → metrics-server-74c698c975-f86p9   1/1     Running   0          10s
```

### Использование `kubectl top`

Через несколько минут после установки Metrics Server начнет собирать данные.

**Просмотр потребления ресурсов узлами:**

```bash
kubectl top nodes
# → NAME        CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# → control-1   150m         7%     1400Mi          36%
# → worker-1    80m          4%     950Mi           24%
# → worker-2    110m         5%     1100Mi          28%
```

**Просмотр потребления ресурсов подами:**

```bash
# Поды во всех namespace'ах
kubectl top pods -A
# → NAMESPACE     NAME                              CPU(cores)   MEMORY(bytes)
# → kube-system   metrics-server-74c698c975-f86p9   2m           18Mi
# → default       my-app-abcdef-12345               15m          128Mi

# Поды в конкретном namespace
kubectl top pods -n default
# → NAME                      CPU(cores)   MEMORY(bytes)
# → openresty-deployment-xyz  1m           15Mi
# → my-app-abcdef-12345       15m          128Mi
```

## Дополнительная информация

**Отличие от Prometheus** — Metrics Server предоставляет только базовые метрики и не хранит историю. Для полноценного мониторинга, алертинга и визуализации исторических данных используется [Prometheus](../../Prometheus/overview.md). Оба компонента работают совместно.

[Официальный репозиторий](https://github.com/kubernetes-sigs/metrics-server)
