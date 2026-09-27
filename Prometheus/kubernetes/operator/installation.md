# Ручная установка Prometheus Operator

## Определения

**Ручная установка Prometheus Operator** — метод развертывания компонентов мониторинга с использованием «голых» манифестов Kubernetes (`kubectl apply`), без применения Helm. Данный подход обеспечивает максимальный контроль над каждым ресурсом, но требует самостоятельного управления RBAC, секретами и Admission Webhooks.

**Bundle (Бандл)** — консолидированный YAML-файл (обычно `bundle.yaml`), содержащий описание Deployment оператора, ServiceAccount, ClusterRole и ClusterRoleBinding. Это основной артефакт для запуска логики контроллера.

**CEL-валидация (Common Expression Language)** — механизм проверки ресурсов на стороне API-сервера Kubernetes (`x-kubernetes-validations`), внедренный в CRD оператора с версии v0.84+. Позволяет отклонять некорректные конфигурации (например, неверный формат URL или конфликтующие типы авторизации) мгновенно, до их обработки оператором.

**Admission Webhooks** — вспомогательные механизмы Kubernetes API (Validating/Mutating), используемые для глубокой проверки PromQL-выражений и структурной целостности правил алертинга.

> **Рекомендация:** Используйте ручную установку при необходимости жесткого контроля версий, в Air-gapped средах или при интеграции с кастомными GitOps-платформами. В остальных случаях предпочтителен [Helm-чарт kube-prometheus-stack](../Kube_Prometheus_Stack_Helm/overview.md).

> **Смотрите также:** [Концепции Prometheus Operator](./concepts.md), [ServiceMonitor CRD](./crd/servicemonitor.md), [RBAC в Kubernetes](../../../Kubernetes/Security/rbac/rbac_overview.md).

## Базовые концепции

### Предварительные требования и проверки кластера

Перед установкой убедитесь, что кластер соответствует минимальным требованиям. Это предотвращает большинство ошибок на этапе применения манифестов.

```bash
# 1. Проверка версии kubectl (должна совпадать с версией API-сервера)
kubectl version --short
# → Client версия: v1.29+ , Server версия: v1.29+

# 2. Проверка доступных ресурсов (Operator требует ~200m CPU, 256Mi RAM)
kubectl top nodes
kubectl describe node <node-name> | grep -A 5 "Allocated resources"

# 3. Проверка отсутствия конфликтующих CRD monitoring.coreos.com
kubectl get crd | grep monitoring.coreos.com
# → Если вывод не пустой — удалите или обновите существующие CRD:
# kubectl delete crd <crd-name>

# 4. Проверка наличия CSI-драйвера для PVC (если планируется хранилище для Prometheus)
kubectl get storageclass
# → Должен быть хотя бы один StorageClass с ReclaimPolicy=Retain или Delete
```

**Минимальные требования к кластеру:**
- Kubernetes 1.29+ (для полной поддержки CEL-валидации)
- Доступный PersistentVolume для StatefulSet Prometheus (если используется)
- CSI-драйвер для динамического provisioning (рекомендуется)

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

### 4. Альтернативный метод: Kustomize

Вместо `sed` для переименования namespace в `bundle.yaml` можно использовать Kustomize. Этот метод более явный и удобен для GitOps-пайплайнов.

**Структура проекта:**
```
manual-install/
├── base/
│   ├── bundle.yaml
│   └── kustomization.yaml
└── overlays/
    └── monitoring/
        ├── kustomization.yaml
        └── namespace.yaml
```

**base/kustomization.yaml:**
```yaml
resources:
  - bundle.yaml
namespace: default
```

**overlays/monitoring/kustomization.yaml:**
```yaml
namespace: monitoring

resources:
  - ../../base
  - namespace.yaml

patches:
  - target:
      group: rbac.authorization.k8s.io
      version: v1
      kind: ClusterRoleBinding
    patch: |-
      - op: replace
        path: /subjects/0/namespace
        value: monitoring
```

**Применение:**
```bash
# Валидация перед применением (сухой запуск)
kubectl apply -k overlays/monitoring --dry-run=server

# Применение
kubectl apply -k overlays/monitoring
```

### 5. Создание инстансов различных типов

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

### 7. Мониторинг состояния Оператора

После установки критически важно настроить мониторинг для самого Оператора. Без этого вы не узнаете о проблемах с reconciliation или сбоях контроллера.

```bash
# 1. Создание ServiceMonitor для Оператора (если используется Prometheus Operator)
kubectl apply -f - <<EOF
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: prometheus-operator
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: prometheus-operator
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
EOF

# 2. Проверка, что таргеты появились в Prometheus UI
# → http://<prometheus>:9090/targets
# → Должен быть активен endpoint prometheus-operator.monitoring:8080/metrics

# 3. Проверка метрик Оператора
kubectl exec -n monitoring deploy/prometheus-operator -- \
  curl -s http://localhost:8080/metrics | grep -E "reconcile_errors|reconcile_duration"
```

**Ключевые метрики для алертинга:** см. полную таблицу в [Концепции Prometheus Operator — Мониторинг Оператора](./concepts.md#ключевые-метрики-мониторинга-оператора). Минимальный набор для пост-инсталляционной проверки:
| Метрика | Описание | Критический порог |
| :--- | :--- | :--- |
| `prometheus_operator_reconcile_errors_total` | Ошибки за цикл согласования | `> 0` в течение 5m |
| `prometheus_operator_reconcile_duration_seconds` | Длительность reconciliation | P99 > 30s |
| `prometheus_operator_workqueue_depth` | Глубина очереди работ | `> 100` |

### 8. Резервное копирование CRD и конфигураций

CRD являются частью состояния кластера. Их потеря приведет к невозможности управления Prometheus через Operator.

```bash
# 1. Экспорт всех CRD в файл
kubectl get crd -o yaml > prometheus-operator-crds-backup.yaml

# 2. Экспорт всех ресурсов Prometheus Operator
kubectl get prometheus,alertmanager,prometheusrule,servicemonitor,podmonitor,scrapeconfig,probe -A -o yaml > prometheus-operator-resources-backup.yaml

# 3. Проверка бэкапа
grep -c "kind: CustomResourceDefinition" prometheus-operator-crds-backup.yaml
# → Должно быть 10+ (все CRD мониторинга)
```

**Рекомендация:** Добавьте эти команды в cronjob или Git-репозиторий для версионирования.

### 9. Обновление и откат версии Operator

#### Сценарий: Обновление с v0.92.0 на v0.93.0

```bash
# 1. Проверка текущей версии
kubectl get deployment prometheus-operator -n monitoring -o jsonpath='{.spec.template.spec.containers[0].image}'
# → quay.io/prometheus-operator/prometheus-operator:v0.92.0

# 2. Проверка changelog и breaking changes
# Важно: проверьте release notes на предмет изменений в CRD

# 3. Обновление bundle.yaml (скачайте новую версию)
curl -sL https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.93.0/bundle.yaml | \
  sed 's/namespace: default/namespace: monitoring/g' | \
  kubectl apply -f -

# 4. Мониторинг обновления
kubectl rollout status deployment/prometheus-operator -n monitoring
# → deployment "prometheus-operator" successfully rolled out

# 5. Проверка reconciliation после обновления
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator --tail=50 | grep -i "reconcile"
# → Должны быть сообщения об успешной reconciliation

# 6. Валидация работоспособности (см. раздел 5)
```

#### Сценарий: Откат при проблемах

```bash
# 1. Откат Deployment к предыдущей версии
kubectl set image deployment/prometheus-operator \
  -n monitoring \
  prometheus-operator=quay.io/prometheus-operator/prometheus-operator:v0.92.0

# 2. Проверка статуса
kubectl rollout status deployment/prometheus-operator -n monitoring

# 3. Если откат не помог — полное удаление и переустановка
kubectl delete -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.92.0/bundle.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.92.0/bundle.yaml
```

### 10. Ограничения и крайние случаи

#### ARM64 и нестандартные архитектуры

```bash
# Проверка архитектуры нод
kubectl get nodes -o jsonpath='{.items[*].status.nodeInfo.architecture}'
# → amd64 / arm64

# Для arm64 используйте образы с суффиксом -arm64:
# quay.io/prometheus-operator/prometheus-operator:v0.92.0-arm64
```

В `bundle.yaml` замените теги образов на архитектурно-специфичные.

#### Ограничения ресурсов в namespace

```bash
# Создание ResourceQuota для предотвращения истощения ресурсов
kubectl apply -f - <<EOF
apiVersion: v1
kind: ResourceQuota
metadata:
  name: monitoring-quota
  namespace: monitoring
spec:
  hard:
    requests.cpu: "4"
    requests.memory: 8Gi
    limits.cpu: "8"
    limits.memory: 16Gi
    count/pods: "50"
EOF
```

#### Конфликт с GitOps-инструментами

Если используется ArgoCD или Flux, убедитесь, что `bundle.yaml` не содержит ресурсов, которыми управляет GitOps. Рекомендуется:
1. Создавать отдельный namespace для Operator
2. Отключать автоматический apply для этого namespace в GitOps
3. Использовать `kubectl apply` вручную или через CI

#### Проблемы с NetworkPolicy

```bash
# Проверка, что порт 9443 доступен для вебхука
kubectl get svc -n monitoring
# → Должен быть сервис с портом 443, перенаправляющим на 9443

# Если используется NetworkPolicy, добавьте правило:
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-webhook
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus-operator
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector: {}
    ports:
    - protocol: TCP
      port: 9443
EOF
```

### 11. Рекомендации по GitOps

Для интеграции с ArgoCD или Flux:

```yaml
# ArgoCD Application (фрагмент)
spec:
  destination:
    namespace: monitoring
  project: default
  source:
    path: overlays/monitoring
    repoURL: https://github.com/org/monitoring-manifests.git
  syncPolicy:
    automated:
      prune: false  # Отключено для Operator, чтобы не удалять при сбоях
    retry:
      limit: 3
```

**Важно:** Включите `SkipDryRunOnMissingResource=true` в sync options, если чарт создает CRD и ресурсы на их основе в одной транзакции.

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

> **Смотрите также:** [Troubleshooting](./troubleshooting.md), [High Availability](./high_availability.md), [Grafana Integration](./grafana_integration.md), [GitOps-интеграция](./gitops_integration.md).
