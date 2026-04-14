# Metrics Server

## Definitions

**Metrics Server** — легковесный in-memory агрегатор данных об использовании ресурсов в кластере Kubernetes. Собирает метрики CPU и RAM с каждого узла через Summary API (`kubelet`), предоставляет через Metrics API (`metrics.k8s.io`).

Не предназначен для долгосрочного хранения метрик и сложного анализа. Основная задача — предоставление актуальных данных о потреблении ресурсов для других компонентов Kubernetes.

## Basic Concepts

### Назначение

**Включение `kubectl top`** — без Metrics Server команды `kubectl top nodes` и `kubectl top pods` не работают, так как запрашивают данные из Metrics API.

**Основа для автоскейлинга:**

- **Horizontal Pod Autoscaler (HPA)** использует данные Metrics Server для масштабирования количества подов в `Deployment`/`StatefulSet` на основе CPU/memory.
- **Vertical Pod Autoscaler (VPA)** использует метрики для рекомендации или автоматического изменения `requests` и `limits` контейнеров.

### Архитектура

- **Deployment** — развертывается как `Deployment` в namespace `kube-system`.
- **Сбор данных** — периодически опрашивает все `kubelet` в кластере.
- **API** — регистрируется в `kube-aggregator` как `APIService` с `v1beta1.metrics.k8s.io`.

## Practical Scenarios

### Установка

Установка выполняется применением одного манифеста, который содержит все необходимые компоненты (`ServiceAccount`, `ClusterRole`, `Deployment`, `APIService` и др.).

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

> **Примечание:** В некоторых случаях (например, в Minikube или при использовании самоподписанных сертификатов в кластере) может потребоваться модифицировать `Deployment` Metrics Server, добавив флаг `--kubelet-insecure-tls`, чтобы разрешить подключение к kubelet'ам без проверки TLS-сертификата.

После установки убедитесь, что под `metrics-server` в `kube-system` namespace успешно запустился:

```bash
kubectl get pods -n kube-system | grep metrics-server
```

### Использование `kubectl top`

Через несколько минут после установки Metrics Server начнет собирать данные.

**Просмотр потребления ресурсов узлами:**

```bash
kubectl top nodes
```

**Вывод:**

```
NAME        CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
control-1   150m         7%     1400Mi          36%
worker-1    80m          4%     950Mi           24%
worker-2    110m         5%     1100Mi          28%
```

**Просмотр потребления ресурсов подами:**

```bash
# Поды во всех namespace'ах
kubectl top pods -A

# Поды в конкретном namespace
kubectl top pods -n default
```

**Вывод:**

```
NAME                      CPU(cores)   MEMORY(bytes)
openresty-deployment-xyz  1m           15Mi
my-app-abcdef-12345       15m          128Mi
```

## Additional Information

**Отличие от Prometheus** — Metrics Server предоставляет только базовые метрики и не хранит историю. Для полноценного мониторинга, алертинга и визуализации исторических данных используется [Prometheus](../../Prometheus/overview.md). Оба компонента работают совместно.

[Официальный репозиторий](https://github.com/kubernetes-sigs/metrics-server)
