# Ingress — установка через Helm

## Определения

**Helm** — пакетный менеджер для Kubernetes, упрощающий установку и управление приложениями через чарты (наборы предварительно настроенных манифестов).

**Ingress-контроллер** — приложение, реализующее правила маршрутизации, описанные в объекте `Ingress`. Без установленного контроллера объект `Ingress` не функционирует. Подробнее: [Ingress — обзор и основные концепции](../overview.md).

## Основные концепции

### Преимущества установки через Helm

| Критерий | Helm | Манифест |
| :--- | :--- | :--- |
| **Управление версиями** | Встроенное (семантическая версионность) | Ручное отслеживание изменений |
| **Обновление** | `helm upgrade` с контролем отката | Ручное применение новых манифестов |
| **Кастомизация** | Параметры через `values.yaml` или `--set` | Прямое редактирование манифестов |
| **Откат** | `helm rollback` к предыдущей ревизии | Ручное применение старой версии |
| **Шаблоны** | Подстановка значений в шаблоны | Статические манифесты |

**Рекомендация:** Helm предпочтителен для стандартных развертываний в облачных средах. Манифесты используются при наличии специфических требований к инфраструктуре (bare-metal, air-gapped). Подробнее: [Ingress — установка через манифест (Bare-Metal)](./bare-metal-installation.md).

## Практические сценарии

### 1. Базовая установка

**Добавление репозитория:**

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update
```

**Установка с параметрами по умолчанию:**

```bash
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace
```

### 2. Установка с кастомными параметрами

```bash
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.priorityClassName=high-priority \
  --set controller.metrics.enabled=true \
  --set controller.admissionWebhooks.enabled=false \
  --set controller.ingressClassResource.name=system-ingress \
  --set controller.ingressClassResource.default=false \
  --set controller.service.type=NodePort \
  --version 4.10.0
```

**Параметры:**

- `controller.priorityClassName` — PriorityClass для подов контроллера (требуется предварительное создание)
- `controller.metrics.enabled` — включение метрик для Prometheus на порту 10254
- `controller.admissionWebhooks.enabled` — отключение валидации Ingress-ресурсов (полезно при нескольких контроллерах)
- `controller.ingressClassResource.name` — имя IngressClass (например, `system-ingress`)
- `controller.ingressClassResource.default` — установка класса по умолчанию (`false` для избежания конфликтов)
- `controller.service.type` — тип Service (`LoadBalancer`, `NodePort`, `ClusterIP`)
- `version` — версия чарта (проверяйте актуальность перед установкой)

### 3. Декларативная установка в K3s (HelmChart CRD)

K3s предоставляет CRD `HelmChart` для декларативного управления Helm-релизами как нативными объектами Kubernetes.

**Манифест HelmChart:**

```yaml
# ingress-nginx-chart.yaml
apiVersion: helm.cattle.io/v1
kind: HelmChart
metadata:
  name: nginx-ingress
  namespace: kube-system
spec:
  chart: ingress-nginx
  repo: https://kubernetes.github.io/ingress-nginx
  targetNamespace: ingress-nginx
  version: 4.10.0
  valuesContent: |-
    controller:
      priorityClassName: system-cluster-critical
      metrics:
        enabled: true
      admissionWebhooks:
        enabled: false
      ingressClassResource:
        name: system-ingress
        enabled: true
        default: false
        controllerValue: "k8s.io/system-ingress"
      service:
        type: NodePort
```

**Применение:**

```bash
kubectl apply -f ingress-nginx-chart.yaml
```

**Примечание о LoadBalancer в K3s:** K3s включает встроенный провайдер `LoadBalancer`. При создании сервиса этого типа K3s назначает IP-адреса всех узлов кластера. Для однонодовых кластеров доступ к Ingress-контроллеру осуществляется через IP единственной ноды.

### 4. Проверка установки

```bash
# Проверка подов
kubectl get pods -n ingress-nginx

# Проверка сервисов
kubectl get svc -n ingress-nginx

# Проверка IngressClass
kubectl get ingressclass

# Проверка релиза Helm
helm list -n ingress-nginx
```

### 5. Обновление и откат

**Обновление с новыми параметрами:**

```bash
helm upgrade ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --set controller.metrics.enabled=true \
  --set controller.service.type=LoadBalancer
```

**Откат к предыдущей ревизии:**

```bash
helm rollback ingress-nginx -n ingress-nginx
```

**Просмотр истории ревизий:**

```bash
helm history ingress-nginx -n ingress-nginx
```

## Дополнительная информация

### Смежные темы

- **[Ingress — обзор и основные концепции](../overview.md)** — базовые понятия маршрутизации и TLS.
- **[Ingress — установка через манифест (Bare-Metal)](./bare-metal-installation.md)** — установка для специализированных сред.
- **[Ingress-контроллеры — сравнение и выбор](../controllers_comparison.md)** — руководство по выбору решения.
- **[NodePort](../../Service/service_type_nodeport.md)** — подробное описание механизма работы и `externalTrafficPolicy`.
- **[Миграция с Ingress на Gateway API](../../gateway_api/migration.md)** — руководство по переходу на новую спецификацию.

Сообщество Kubernetes рекомендует переход на Gateway API — новую спецификацию для управления входящим трафиком. NGINX Ingress Controller продолжает поддерживаться, но новые функции разрабатываются в рамках Gateway API.
