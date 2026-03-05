# Ingress: Установка контроллера

## Установка Nginx Ingress Controller через Helm

Nginx Ingress Controller является одним из наиболее популярных ingress-контроллеров. Установка производится через официальный Helm-чарт.

### 1. Добавление репозитория

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update
```

### 2. Установка через Helm (пример с кастомными параметрами)

```bash
helm install ingress-nginx ingress-nginx/ingress-nginx
  --namespace ingress-nginx
  --create-namespace
  --set controller.priorityClassName=high-priority
  --set controller.metrics.enabled=true
  --set controller.admissionWebhooks.enabled=false
  --set controller.ingressClassResource.name=system-ingress
  --set controller.ingressClassResource.default=false
  --version 4.10.0 # Важно: Перед установкой проверьте актуальную версию чарта.
```

**Основные параметры:**

- `controller.priorityClassName`: PriorityClass для контроллера (требуется предварительное создание).
- `controller.metrics.enabled`: Включение метрик для Prometheus.
- `controller.admissionWebhooks.enabled`: Отключение валидации Ingress-ресурсов. Полезно, если в кластере планируется несколько Ingress-контроллеров.
- `controller.ingressClassResource.name`: Имя ресурса IngressClass, который будет создан (например, `system-ingress`).
- `controller.service.type`: Тип Service (по умолчанию `LoadBalancer`).

### 3. Проверка установки

```bash
kubectl get pods -n ingress-nginx
kubectl get svc -n ingress-nginx
```

---

## Декларативная установка в K3s (HelmChart CRD)

K3s включает в себя встроенный контроллер для развертывания Helm-чартов декларативно, с помощью CRD `HelmChart`. Это позволяет управлять Helm-релизами как нативными объектами Kubernetes.

Ниже приведен пример манифеста для установки Nginx Ingress Controller этим способом.

```yaml
# ingress-nginx-chart.yaml
apiVersion: helm.cattle.io/v1
kind: HelmChart
metadata:
  name: nginx-ingress
  namespace: kube-system # Чарт будет установлен в этот namespace
spec:
  chart: ingress-nginx
  repo: https://kubernetes.github.io/ingress-nginx
  targetNamespace: ingress-nginx # А сам контроллер развернется здесь
  version: 4.10.0 # Важно: Перед установкой проверьте актуальную версию чарта.
  valuesContent: |-
    controller:
      # Указываем высокий приоритет для подов контроллера
      priorityClassName: system-cluster-critical
      # Разрешаем сбор метрик для Prometheus
      metrics:
        enabled: true
      # Отключаем вебхуки, чтобы не мешать другим Ingress-контроллерам
      admissionWebhooks:
        enabled: false
      # Определяем кастомный IngressClass
      ingressClassResource:
        name: system-ingress
        enabled: true
        default: false
        controllerValue: "k8s.io/system-ingress"
```

**Примечание о LoadBalancer в K3s:**
В K3s встроен собственный провайдер сервисов типа `LoadBalancer`. При создании такого сервиса (что по умолчанию делает чарт Nginx Ingress), K3s назначает ему IP-адреса всех узлов кластера. Если у вас кластер из одной ноды, то для доступа к Ingress-контроллеру можно использовать IP-адрес этой ноды.

---

## Ссылки

- **[Практические сценарии настройки](../practical_scenarios.md)** — TLS, аннотации, маршрутизация
- **[Ingress overview](./ingress_overview.md)** — базовые концепции
