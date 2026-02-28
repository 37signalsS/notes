# Metrics Server

## 1. Определения

**Metrics Server** — это легковесный, запускаемый в памяти (in-memory) агрегатор данных об использовании ресурсов в кластере Kubernetes. Он собирает метрики (CPU и RAM) с каждого узла через Summary API, предоставляемый `kubelet`, и отдает их через официальный Metrics API (`metrics.k8s.io`).

Metrics Server не предназначен для долгосрочного хранения метрик и не предоставляет возможностей для сложного анализа. Его основная задача — предоставлять актуальные данные о потреблении ресурсов для других компонентов Kubernetes.

## 2. Основные концепции

### Назначение

1.  **Включение `kubectl top`**: Без Metrics Server команды `kubectl top nodes` и `kubectl top pods` не будут работать, так как они запрашивают данные именно из Metrics API.
2.  **Основа для автоскейлинга**:
    *   **Horizontal Pod Autoscaler (HPA)** использует данные Metrics Server для принятия решений о масштабировании количества подов в `Deployment` или `StatefulSet` на основе загрузки CPU или потребления памяти.
    *   **Vertical Pod Autoscaler (VPA)** также может использовать эти метрики для рекомендации или автоматического изменения `requests` и `limits` для контейнеров.

### Архитектура

*   **Deployment**: Metrics Server развертывается как `Deployment` в `kube-system` namespace.
*   **Сбор данных**: Периодически опрашивает все `kubelet`'ы в кластере для сбора метрик.
*   **API**: Регистрирует себя в `kube-aggregator` как `APIService`, предоставляющий `v1beta1.metrics.k8s.io`.

## 3. Практические сценарии

### 3.1. Установка

Установка выполняется применением одного манифеста, который содержит все необходимые компоненты (`ServiceAccount`, `ClusterRole`, `Deployment`, `APIService` и др.).

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

> **Примечание:** В некоторых случаях (например, в Minikube или при использовании самоподписанных сертификатов в кластере) может потребоваться модифицировать `Deployment` Metrics Server, добавив флаг `--kubelet-insecure-tls`, чтобы разрешить подключение к kubelet'ам без проверки TLS-сертификата.

После установки убедитесь, что под `metrics-server` в `kube-system` namespace успешно запустился:

```bash
kubectl get pods -n kube-system | grep metrics-server
```

### 3.2. Использование `kubectl top`

Через несколько минут после установки Metrics Server начнет собирать данные, и вы сможете использовать команду `kubectl top`.

*   **Просмотр потребления ресурсов узлами:**

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

*   **Просмотр потребления ресурсов подами:**

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

## 4. Дополнительная информация

*   **Отличие от Prometheus**: Metrics Server предоставляет только самые базовые метрики и не хранит историю. Для полноценного мониторинга, алертинга и визуализации исторических данных используется [Prometheus](../../Prometheus/prometheus_overview.md). Metrics Server и Prometheus могут и должны работать вместе.
*   [Официальный репозиторий](https://github.com/kubernetes-sigs/metrics-server)
