# Ingress — установка через Helm

> [!CAUTION]
> **Внимание (март 2026):** Проект `kubernetes/ingress-nginx` официально перешел в статус **End of Life (EOL — завершение жизненного цикла)**. Поддержка прекращена, патчи безопасности не выпускаются. Для новых инсталляций рекомендуется использовать **Traefik**, **NGINX Gateway Fabric** или другие решения на базе **Gateway API (Application Programming Interface)**.

## Определения

**Helm** — менеджер пакетов для Kubernetes, упрощающий установку и управление приложениями через чарты (Charts — наборы предварительно настроенных манифестов). Позволяет версионировать конфигурации и автоматизировать развертывание.

**Ingress-контроллер** — специализированное приложение, реализующее правила маршрутизации, описанные в объекте `Ingress`. Он работает как обратный прокси-сервер (Reverse Proxy), направляя внешний трафик к сервисам внутри кластера. Подробнее: **[Ingress — обзор и основные концепции](../overview.md)**.

## Основные концепции

### Преимущества установки через Helm

| Критерий | Helm | Манифесты (YAML) |
| :--- | :--- | :--- |
| **Управление версиями** | Встроенное (семантическая версионность чартов) | Ручное отслеживание через Git |
| **Обновление** | `helm upgrade` с контролем истории | `kubectl apply` с риском конфликтов |
| **Кастомизация** | Параметры через `values.yaml` или `--set` | Прямое редактирование файлов |
| **Откат** | `helm rollback` к конкретной ревизии | Повторное применение старых файлов |
| **Проверка (Dry-run)** | Встроенная валидация перед установкой | Ручная проверка манифестов |

**Рекомендация:** Использование Helm является стандартом для развертывания Ingress-контроллеров в облачных (Managed K8s) и гибридных средах. Прямая установка через манифесты используется преимущественно в изолированных (Air-gapped) сетях или при глубокой кастомизации под Bare-metal. Подробнее: **[Ingress — установка через манифест (Bare-Metal)](./bare-metal-installation.md)**.

---

## Практические сценарии

### 1. Базовая установка (Legacy Ingress-NGINX)

*Используйте этот метод только для поддержки существующих систем.*

**Добавление репозитория:**

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update
# → ...Successfully got an update from the "ingress-nginx" chart repository
```

**Установка с контролем завершения:**

```bash
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --wait \
  --timeout 5m
# → NAME: ingress-nginx
# → LAST DEPLOYED: Wed Jul 22 10:00:00 2026
# → NAMESPACE: ingress-nginx
# → STATUS: deployed
```

### 2. Установка через values.yaml (Best Practice)

Использование файла значений (Values file) предпочтительнее длинных команд с `--set`, так как файл можно хранить в системе контроля версий (Git).

**Создание файла `values-production.yaml`:**

```yaml
controller:
  # Приоритет запуска для критических компонентов
  priorityClassName: system-cluster-critical
  
  metrics:
    enabled: true # Включение экспортера для Prometheus
  
  admissionWebhooks:
    enabled: true # Валидация Ingress-ресурсов при создании
  
  ingressClassResource:
    name: nginx
    enabled: true
    default: true # Использовать этот класс по умолчанию
  
  service:
    type: LoadBalancer
    annotations:
      # Пример для AWS: использование NLB вместо классического ELB
      service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
```

**Применение конфигурации:**

```bash
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --values values-production.yaml \
  --wait \
  --atomic
```
*Флаг `--atomic` автоматически откатит изменения в случае ошибки при установке.*

### 3. Декларативная установка в K3s (HelmChart CRD)

K3s использует `Custom Resource Definition (CRD)` типа `HelmChart` для управления Helm-релизами через нативные манифесты Kubernetes.

**Манифест HelmChart:**

```yaml
# ingress-nginx-chart.yaml
apiVersion: helm.cattle.io/v1
kind: HelmChart
metadata:
  name: nginx-ingress
  namespace: kube-system # Место хранения самого ресурса HelmChart
spec:
  chart: ingress-nginx
  repo: https://kubernetes.github.io/ingress-nginx
  targetNamespace: ingress-nginx # Куда будет установлен контроллер
  version: 4.10.0
  valuesContent: |-
    controller:
      metrics:
        enabled: true
      service:
        type: NodePort # Стандарт для небольших K3s кластеров
```

### 4. Проверка состояния установки

```bash
# Список всех ресурсов в пространстве имен
kubectl get all -n ingress-nginx

# Проверка регистрации класса Ingress
kubectl get ingressclass
# → NAME    CONTROLLER             PARAMETERS   AGE
# → nginx   k8s.io/ingress-nginx   <none>       5m

# Проверка истории релизов Helm
helm history ingress-nginx -n ingress-nginx
```

---

## Дополнительная информация

### Устранение неполадок (Troubleshooting)

- **Pending LoadBalancer IP:** Если сервис остается в статусе `Pending`, проверьте наличие CCM (Cloud Controller Manager) в кластере или корректность аннотаций провайдера.
- **Webhook Connection Refused:** Часто возникает при использовании сетевых политик (NetworkPolicies), блокирующих трафик между API-сервером и вебхуком контроллера.

### Смежные темы

- **[Ingress-контроллеры — сравнение и выбор](../controllers_comparison.md)** — актуальный список альтернатив на 2026 год.
- **[Миграция с Ingress на Gateway API](../../gateway_api/migration.md)** — подробная инструкция по переходу с EOL-проектов.
- **[NodePort](../../Service/service_type_nodeport.md)** — использование типа сервиса NodePort при отсутствии LoadBalancer.
- **[Ingress — установка через манифест (Bare-Metal)](./bare-metal-installation.md)** — установка без использования Helm.

**Примечание:** Для современных инсталляций (2026+) рекомендуется рассматривать установку **Traefik** или **Envoy Gateway** через их официальные Helm-чарты, которые изначально спроектированы под поддержку Gateway API.
