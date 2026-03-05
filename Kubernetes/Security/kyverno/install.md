# Установка Kyverno

## Определения

**Kyverno** устанавливается в кластер Kubernetes через **Helm Chart** или YAML-манифесты. При установке разворачиваются 4 компонента для обработки политик, фоновых сканирований, отчетов и очистки ресурсов.

> **Официальная документация**: <https://kyverno.io/docs/installation/>

---

## Basic Concepts

### Компоненты Kyverno

| Компонент | Назначение | Критичность |
|-----------|------------|-------------|
| **Admission Controller** | Обработка mutating и validating admission webhook-запросов | **Критичен** — без него политики не применяются |
| **Background Controller** | Фоновое сканирование существующих ресурсов и генерация отчетов | Рекомендуется для аудита |
| **Cleanup Controller** | Удаление ресурсов по расписанию или условию | Опционально |
| **Reports Controller** | Генерация Policy Reports в формате Policy Report WG | Рекомендуется для интеграции с Policy Reporter |

### Требования

| Требование | Минимальные | Рекомендуемые |
|------------|-------------|---------------|
| Kubernetes | 1.23+ | 1.27+ |
| CPU | 2 cores | 4+ cores |
| Memory | 2 GB | 4+ GB |
| Helm | 3.9+ | 3.12+ |

---

## Practical Scenarios

### Установка через Helm

```bash
# Добавление репозитория
helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo update

# Установка в namespace kyverno
helm install kyverno kyverno/kyverno \
  --namespace kyverno \
  --create-namespace \
  --version 3.2.0 \
  --set admissionController.replicas=2 \
  --set backgroundController.replicas=2 \
  --set cleanupController.replicas=1 \
  --set reportsController.replicas=1
```

### Проверка установки

```bash
# Проверка подов
kubectl get pods -n kyverno

# Ожидаемый вывод:
# NAME                                            READY   STATUS    RESTARTS   AGE
# kyverno-admission-controller-5f8c9d7b9c-abc12   1/1     Running   0          5m
# kyverno-background-controller-6d9f8e7c8d-def34  1/1     Running   0          5m
# kyverno-cleanup-controller-7e8f9a0b1c-ghi56     1/1     Running   0          5m
# kyverno-reports-controller-8f9a0b1c2d-jkl78     1/1     Running   0          5m

# Проверка webhook-ов
kubectl get validatingwebhookconfiguration
kubectl get mutatingwebhookconfiguration

# Проверка CRD
kubectl get clusterpolicy
kubectl get policy
```

### Установка с Policy Reporter

```bash
# Установка Kyverno + Policy Reporter
helm install policy-reporter policy-reporter/policy-reporter \
  --namespace policy-reporter \
  --create-namespace \
  --set ui.enabled=true \
  --set ui.plugins.kyverno=true \
  --set metrics.enabled=true \
  --set prometheus.enabled=true
```

### Установка через Argo CD

При установке через Argo CD **обязательно** использовать server-side apply:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kyverno
  namespace: argocd
spec:
  syncPolicy:
    automated:
      applyServerSide: true  # Обязательно!
      # replace: true  # НЕ использовать!
  source:
    repoURL: https://kyverno.github.io/kyverno
    chart: kyverno
    targetRevision: 3.2.0
    helm:
      releaseName: kyverno
      values: |
        admissionController:
          replicas: 2
```

> **Важно**: Параметр `spec.syncPolicy.automated.replace: true` использовать **нельзя** — вызывает конфликты с webhook ([подробнее](./argo-cd.md)).

### Настройка Argo CD для работы с Kyverno

В `values.yaml` Argo CD указать:

```yaml
# resourceTrackingMethod: annotation — для избежания конфликта меток
resourceTrackingMethod: annotation

# controller.diff.serverSide: true — для корректного сравнения
controller:
  diff:
    serverSide: true

# ignoreAggregatedRoles: true — для игнорирования динамических ролей
resource:
  compare:
    ignoreAggregatedRoles: true
```

---

## Additional Information

### Aggregated Cluster Roles

По умолчанию Kyverno не имеет прав на создание некоторых ресурсов (например, `Secret`). Для расширения прав используются **Aggregated Cluster Roles** ([подробнее](./additional.md)).

**Пример для генерации Secret**:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  labels:
    kyverno.io/aggregate-to-background-controller: "true"
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["create", "update", "delete", "get", "list"]
```

### Troubleshooting

| Проблема | Решение |
|----------|---------|
| Webhook timeout | Увеличить `timeoutSeconds` в webhook configuration |
| Policies not applied | Проверить статус подов admission-controller |
| Reports not generated | Проверить права reports-controller |
| Argo CD infinite loop | Включить `server-side diff` и `IncludeMutationWebhook` |

### Удаление

```bash
# Удаление Helm release
helm uninstall kyverno -n kyverno

# Удаление namespace
kubectl delete namespace kyverno

# Удаление CRD (осторожно!)
kubectl delete crd clusterpolicies.kyverno.io
kubectl delete crd policies.kyverno.io
kubectl delete crd policyreports.wgpolicyk8s.io
kubectl delete crd clusterpolicyreports.wgpolicyk8s.io
```

> **Внимание**: Удаление CRD приведет к потере всех политик и отчетов!

### Связанные темы

- [Интеграция с Argo CD](./argo-cd.md) — настройка совместного использования
- [Aggregated Cluster Roles](./additional.md) — права для генерации ресурсов
- [Policy Reports](./reports.md) — отчеты о применении политик
