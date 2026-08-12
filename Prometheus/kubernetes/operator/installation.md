# Ручная установка Prometheus Operator

## Определения

**Ручная установка Prometheus Operator** — метод развертывания компонентов мониторинга с использованием «голых» манифестов Kubernetes (`kubectl apply`), без применения Helm. Данный подход обеспечивает максимальный контроль над каждым ресурсом, но требует самостоятельного управления RBAC, секретами и Admission Webhooks.

**Bundle (Бандл)** — консолидированный YAML-файл (обычно `bundle.yaml`), содержащий описание Deployment оператора, ServiceAccount, ClusterRole и ClusterRoleBinding. Это основной артефакт для запуска логики контроллера.

**CEL-валидация (Common Expression Language)** — механизм проверки ресурсов на стороне API-сервера Kubernetes (`x-kubernetes-validations`), внедренный в CRD оператора с версии v0.84+. Позволяет отклонять некорректные конфигурации (например, неверный формат URL или конфликтующие типы авторизации) мгновенно, до их обработки оператором.

**Admission Webhooks** — вспомогательные механизмы Kubernetes API (Validating/Mutating), используемые для глубокой проверки PromQL-выражений и структурной целостности правил алертинга.

> **Рекомендация:** Используйте ручную установку при необходимости жесткого контроля версий, в Air-gapped средах или при интеграции с кастомными GitOps-платформами. В остальных случаях предпочтителен [Helm-чарт kube-prometheus-stack](../Kube_Prometheus_Stack_Helm/overview.md).

> **Смотрите также:** [Концепции Prometheus Operator](./concepts.md), [ServiceMonitor CRD](./crd/servicemonitor.md), [RBAC в Kubernetes](../../Kubernetes/Security/rbac/rbac_overview.md).

## Базовые концепции

### Состав ручной установки

Ручная установка подразумевает модульный подход. Вы сами выбираете, какие компоненты стека развертывать.

| Компонент | Манифест / Источник | Описание |
| :--- | :--- | :--- |
| **CRDs** | `example/prometheus-operator-crd/` | Регистрация типов объектов в API. |
| **Operator** | `bundle.yaml` | Ядро системы (контроллер + RBAC). |
| **Webhooks** | `admission-webhooks.yaml` | Валидация правил и конфигураций. |
| **Prometheus** | [Prometheus CRD](./crd/prometheus.md) | Сервер мониторинга с хранилищем TSDB. |
| **Prometheus Agent** | `PrometheusAgent` CRD (v1alpha1) | Легковесный сборщик метрик без TSDB. |
| **ScrapeConfig** | `ScrapeConfig` CRD (v1alpha1) | Современная замена `additionalScrapeConfigs`. |
| **Grafana** | [Grafana Integration](./grafana_integration.md) | Визуализация данных. |

### Источники манифестов

Официальные манифесты поддерживаются в репозитории [prometheus-operator/prometheus-operator](https://github.com/prometheus-operator/prometheus-operator). Основные пути в репозитории:
*   `/example/prometheus-operator-crd/` — папка со всеми определениями ресурсов.
*   `/bundle.yaml` — единый файл для быстрого запуска контроллера в namespace `default`.
*   `/example/admission-webhook/` — примеры конфигурации вебхуков.

### Актуальные версии (Июль 2026)

| Параметр | Значение | Примечание |
| :--- | :--- | :--- |
| **Версия Operator** | `v0.92.0` | Стабильный релиз 2026 года. |
| **Минимальный Kubernetes** | `1.29+` | Рекомендуется для полной поддержки CEL. |
| **API Version** | `monitoring.coreos.com/v1` | Актуальная версия API. |

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

Файл `bundle.yaml` по умолчанию использует namespace `default`. Для установки в `monitoring` требуется коррекция манифеста (особенно `ClusterRoleBinding`) через Kustomize или `sed`.

```bash
# Создание namespace
kubectl create namespace monitoring

# Установка bundle с заменой namespace
curl -sL https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.92.0/bundle.yaml | \
sed 's/namespace: default/namespace: monitoring/g' | \
kubectl apply -f -
```

### 3. Настройка Admission Webhooks

Вебхуки необходимы для предотвращения применения «битых» правил алертинга. С 2026 года часть проверок перенесена в CEL, но структурная валидация PromQL все еще требует вебхука.

**Требования к TLS:**
Вебхук работает по HTTPS. Рекомендуемые способы управления сертификатами:
1.  **cert-manager:** Автоматическая генерация и инъекция CA в `ValidatingWebhookConfiguration` через аннотацию `cert-manager.io/inject-ca-from`.
2.  **Ручной TLS:** Создание секрета `prometheus-operator-admission-webhook-certs` с полями `tls.crt` и `tls.key`.

### 4. Создание инстансов различных типов

#### Сценарий A: Стандартный Prometheus Server (v3.x)
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
  # Включение нативного OTLP ресивера (Prometheus 3.0+)
  enableOTLPReceiver: true
```

#### Сценарий B: Prometheus Agent Mode
```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: PrometheusAgent
metadata:
  name: edge-collector
  namespace: edge
spec:
  replicas: 1
  remoteWrite:
    - url: http://central-storage:8428/api/v1/write
  serviceMonitorSelector:
    matchLabels:
      app: collector
```

### 5. Проверка состояния и верификация

```bash
# 1. Ожидание готовности пода оператора
kubectl wait --for=condition=Ready pods -n monitoring -l app.kubernetes.io/name=prometheus-operator

# 2. Проверка логов на предмет ошибок reconciliation
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator

# 3. Проверка статуса CEL-валидации (ошибки вернутся сразу в kubectl apply)
# Пример: попытка создать ScrapeConfig с отрицательным интервалом
```

### 6. Полное удаление компонентов

```bash
# Удаление бандла (Оператор + RBAC)
kubectl delete -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.92.0/bundle.yaml

# Удаление CRD (ВНИМАНИЕ: удалит ВСЕ ресурсы Prometheus, правила и данные!)
kubectl delete -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.92.0/example/prometheus-operator-crd/
```

## Дополнительная информация

### Справочник прав ClusterRole (RBAC)

Для полноценной работы (Service Discovery, управление ресурсами) Оператору и Prometheus требуются следующие права:

| Ресурс | Группа API | Глаголы (Verbs) | Зачем |
| :--- | :--- | :--- | :--- |
| `nodes`, `pods`, `services` | "" (core) | `get, list, watch` | Service Discovery целей |
| `endpoints`, `endpointslices`| "" / `discovery.k8s.io` | `get, list, watch` | Актуальные IP целей (преимущественно EndpointSlice) |
| `ingresses` | `networking.k8s.io` | `get, list, watch` | Discovery для Ingress-мониторинга |
| `configmaps`, `secrets` | "" (core) | `*` | Хранение конфигов и правил |
| `statefulsets` | `apps` | `*` | Управление инстансами Prometheus |
| `prometheuses`, `*monitors` | `monitoring.coreos.com` | `*` | Управление собственными CRD |

### Установка в изолированных средах (Air-gapped)

1.  **Зеркалирование образов:** Загрузите в локальный Registry:
    *   `quay.io/prometheus-operator/prometheus-operator:v0.92.0`
    *   `quay.io/prometheus-operator/prometheus-config-reloader:v0.92.0`
2.  **Подготовка манифестов:** Скачайте `bundle.yaml` и `crd/`. Замените в `bundle.yaml` значения `image:` на внутренние адреса (например, `harbor.corp.local/monitoring/...`).
3.  **Локальный Apply:** Скопируйте файлы на bastion-хост и выполните `kubectl apply -f .`.

### Типичные ошибки установки

*   **CRD mismatch:** Установка Оператора `v0.92` на CRD `v0.85`. Симптом: ошибки `unknown field` в логах из-за новых полей CEL-валидации.
*   **Webhook Timeout:** Порт 9443 закрыт NetworkPolicy. Симптом: таймауты при создании `PrometheusRule`.
*   **RBAC для Prometheus:** Если забыли создать `ClusterRole` для инстанса Prometheus, в UI будет 0 targets при наличии ресурсов мониторинга.

> **Смотрите также:** [Troubleshooting](./troubleshooting.md), [High Availability](./high_availability.md), [Grafana Integration](./grafana_integration.md).
