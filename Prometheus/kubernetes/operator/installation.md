# Ручная установка Prometheus Operator

## Определения

**Ручная установка Prometheus Operator** — метод развертывания компонентов мониторинга с использованием «голых» манифестов Kubernetes (`kubectl apply`), без применения Helm. Данный подход обеспечивает максимальный контроль над каждым ресурсом, но требует самостоятельного управления RBAC, секретами и Admission Webhooks.

**Bundle (Бандл)** — консолидированный YAML-файл, содержащий описание Deployment оператора, ServiceAccount, ClusterRole и ClusterRoleBinding. Это основной файл для запуска логики контроллера.

**Admission Webhooks** — механизмы Kubernetes API (Validating/Mutating), используемые Оператором для проверки корректности CRD (например, синтаксиса правил в `PrometheusRule`) перед их фиксацией в `etcd`.

> **Рекомендация:** Используйте ручную установку при необходимости жесткого контроля версий, в Air-gapped средах или при интеграции с кастомными GitOps-платформами. В остальных случаях предпочтителен [Helm-чарт kube-prometheus-stack](../Kube_Prometheus_Stack_Helm/overview.md).

> **См. также:** [Концепции Prometheus Operator](./concepts.md), [ServiceMonitor CRD](./crd/servicemonitor.md), [RBAC в Kubernetes](../../Security/rbac/rbac_overview.md).

## Базовые концепции

### Состав ручной установки

Ручная установка подразумевает модульный подход. Вы сами выбираете, какие компоненты стека развертывать.

| Компонент | Манифест / Источник | Описание |
| :--- | :--- | :--- |
| **CRDs** | `example/prometheus-operator-crd/` | Регистрация типов объектов в API. |
| **Operator** | `bundle.yaml` | Ядро системы (контроллер + RBAC). |
| **Webhooks** | `admission-webhooks.yaml` | Валидация правил и конфигураций. |
| **Prometheus** | [Prometheus CRD](./crd/prometheus.md) | Сервер мониторинга с хранилищем TSDB. |
| **Prometheus Agent** | `PrometheusAgent` CRD | Легковесный сборщик метрик без TSDB. |
| **ScrapeConfig** | `ScrapeConfig` CRD | Современная замена `additionalScrapeConfigs`. |
| **Grafana** | [Grafana Integration](./grafana_integration.md) | Визуализация данных. |

### Источники манифестов

Официальные манифесты поддерживаются в репозитории [prometheus-operator/prometheus-operator](https://github.com/prometheus-operator/prometheus-operator). Основные пути в репозитории:
*   `/example/prometheus-operator-crd/` — папка со всеми определениями ресурсов.
*   `/bundle.yaml` — единый файл для быстрого запуска контроллера.
*   `/example/admission-webhook/` — примеры конфигурации вебхуков.

### Актуальные версии (Июль 2026)

| Параметр | Значение |
| :--- | :--- |
| **Версия Operator** | `v0.92.0` |
| **Минимальный Kubernetes** | `1.29+` |
| **API Version** | `monitoring.coreos.com/v1` |

## Практические сценарии

### 1. Порядок установки CRD (Critical Path)

Установка CRD должна быть выполнена **до** запуска самого Оператора. Порядок внутри папки не критичен, но рекомендуется устанавливать всё разом.

```bash
# Установка всех CRD v0.92.0
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.92.0/example/prometheus-operator-crd/

# Список установленных ресурсов для проверки:
# alertmanagerconfigs, alertmanagers, podmonitors, probes, prometheusagents,
# prometheuses, prometheusrules, scrapeconfigs, servicemonitors, thanosrulers
```

### 2. Развертывание Оператора и RBAC

Файл `bundle.yaml` по умолчанию использует namespace `default`. Для установки в `monitoring` требуется коррекция манифеста на лету.

```bash
# Создание namespace
kubectl create namespace monitoring

# Установка bundle с заменой namespace
curl -sL https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.92.0/bundle.yaml | \
sed 's/namespace: default/namespace: monitoring/g' | \
kubectl apply -f -
```

### 3. Настройка Admission Webhooks

Вебхуки необходимы для предотвращения применения «битых» правил алертинга, которые могут уронить Prometheus.

**Требования к TLS:**
Вебхук работает по HTTPS. У вас есть два пути:
1.  **cert-manager:** Автоматическая генерация и инъекция CA в `ValidatingWebhookConfiguration`.
2.  **Ручной TLS:** Создание секрета `prometheus-operator-admission-webhook-certs` с полями `tls.crt` и `tls.key`.

**Пример манифеста вебхука (фрагмент):**
```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: prometheus-operator-rules-validation
webhooks:
  - name: prometheusrulev1.monitoring.coreos.com
    clientConfig:
      service:
        name: prometheus-operator
        namespace: monitoring
        path: /admit-rules
```

### 4. Создание различных типов инстансов

#### Сценарий A: Стандартный Prometheus (Server)
```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  version: v3.12.0
  serviceAccountName: prometheus
  serviceMonitorSelector:
    matchLabels:
      release: monitoring
```

#### Сценарий B: Prometheus Agent Mode
```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusAgent
metadata:
  name: edge-collector
  namespace: edge
spec:
  replicas: 1
  remoteWrite:
    - url: http://central-vm-insert:8428/api/v1/write
  serviceMonitorSelector:
    matchLabels:
      app: collector
```

#### Сценарий C: Кастомный скрейпинг через ScrapeConfig
```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: external-api
  namespace: monitoring
spec:
  staticConfigs:
    - targets: ['api.external-service.com:443']
      labels:
        env: production
  scheme: https
```

### 5. Проверка состояния и верификация

```bash
# Проверка регистрации типов объектов
kubectl get crd | grep monitoring.coreos.com

# Проверка работоспособности пода оператора
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-operator

# Проверка логов на предмет ошибок reconciliation
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator
```

### 6. Полное удаление компонентов

```bash
# Удаление бандла (Оператор + RBAC)
kubectl delete -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.92.0/bundle.yaml

# Удаление CRD (ВНИМАНИЕ: удалит ВСЕ ресурсы Prometheus, правила и т.д.)
kubectl delete -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.92.0/example/prometheus-operator-crd/
```

## Дополнительная информация

### Справочник прав ClusterRole (RBAC)

Для полноценной работы (Service Discovery, управление ресурсами) Оператору и Prometheus требуются следующие права:

| Ресурс | Группа API | Глаголы (Verbs) | Зачем |
| :--- | :--- | :--- | :--- |
| `nodes`, `pods`, `services` | "" (core) | `get, list, watch` | Service Discovery целей |
| `endpoints`, `endpointslices`| "" / `discovery.k8s.io` | `get, list, watch` | Актуальные IP целей |
| `ingresses` | `networking.k8s.io` | `get, list, watch` | Discovery для Ingress-мониторинга |
| `configmaps`, `secrets` | "" (core) | `*` | Хранение конфигов и правил |
| `statefulsets` | `apps` | `*` | Управление инстансами Prometheus |
| `prometheuses`, `*monitors` | `monitoring.coreos.com` | `*` | Управление собственными CRD |

### Установка в изолированных средах (Air-gapped)

1.  **Зеркалирование образов:** Загрузите в локальный Registry:
    *   `quay.io/prometheus-operator/prometheus-operator:v0.92.0`
    *   `quay.io/prometheus-operator/prometheus-config-reloader:v0.92.0`
    *   Образы Prometheus и Alertmanager из манифестов.
2.  **Подготовка манифестов:** Скачайте `bundle.yaml` и `crd/`. Замените в `bundle.yaml` значения `image:` на ваши внутренние адреса (например, `harbor.internal/monitoring/...`).
3.  **Локальный Apply:** Скопируйте файлы на bastion-хост и выполните `kubectl apply -f .`.

### Типичные ошибки установки

*   **CRD mismatch:** Установка Оператора `v0.92` на CRD `v0.85`. Симптом: ошибки `unknown field` в логах.
*   **Webhook Timeout:** Порт 9443 (стандартный для вебхука Оператора) закрыт NetworkPolicy. Симптом: таймауты при создании `PrometheusRule`.
*   **RBAC для Prometheus:** Забыли создать `ClusterRole` для самого пода Prometheus. Симптом: 0 targets в UI при наличии `ServiceMonitor`.

> **См. также:** [Troubleshooting](./troubleshooting.md), [High Availability](./high_availability.md), [Grafana Integration](./grafana_integration.md).
