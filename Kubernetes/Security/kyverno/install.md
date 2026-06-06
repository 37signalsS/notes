# Установка Kyverno

## Определения

**Kyverno** устанавливается в кластер Kubernetes через **Helm** (менеджер пакетов для Kubernetes) или YAML-манифесты. При установке разворачиваются 4 компонента для обработки политик, фоновых сканирований, отчетов и очистки ресурсов.

> **Официальная документация**: <https://kyverno.io/docs/installation/>

---

## Основные концепции

### Компоненты Kyverno

| Компонент | Назначение | Критичность |
|-----------|------------|-------------|
| **Admission Controller** | Обработка mutating и validating admission webhook-запросов | **Критичен** — без него политики не применяются |
| **Background Controller** | Фоновое сканирование существующих ресурсов и генерация отчетов | Рекомендуется для аудита |
| **Cleanup Controller** | Удаление ресурсов по расписанию или условию | Опционально |
| **Reports Controller** | Генерация Policy Reports в формате Policy Report WG (Working Group) | Рекомендуется для интеграции с Policy Reporter |

### Требования

| Требование | Минимальные | Рекомендуемые |
|------------|-------------|---------------|
| Kubernetes | 1.23+ | 1.27+ |
| CPU (Central Processing Unit) | 2 ядра | 4+ ядер |
| Memory (Оперативная память) | 2 GB | 4+ GB |
| Helm | 3.9+ | 3.12+ |

---

## Практические сценарии

### Установка через Helm

```bash
# Добавление репозитория
helm repo add kyverno https://kyverno.github.io/kyverno/
# → "kyverno" has been added to your repositories

helm repo update
# → Hang tight while we grab the latest from your chart repositories...

# Установка в namespace kyverno
helm install kyverno kyverno/kyverno \
  --namespace kyverno \
  --create-namespace \
  --version 3.3.0 \
  --set admissionController.replicas=2 \
  --set backgroundController.replicas=2 \
  --set cleanupController.replicas=1 \
  --set reportsController.replicas=1
# → NAME: kyverno, STATUS: deployed
```

> **Примечание**: Версия чарта 3.3.0 соответствует Kyverno ~1.15. Актуальную версию проверяйте на [Artifact Hub](https://artifacthub.io/packages/helm/kyverno/kyverno).

### Проверка установки

```bash
# Проверка подов
kubectl get pods -n kyverno
# → NAME                                            READY   STATUS    RESTARTS   AGE
# → kyverno-admission-controller-5f8c9d7b9c-abc12   1/1     Running   0          5m
# → ...

# Проверка webhook-ов
kubectl get validatingwebhookconfiguration
kubectl get mutatingwebhookconfiguration

# Проверка CRD (Custom Resource Definition)
kubectl get clusterpolicy
kubectl get policy
```

### Установка с Policy Reporter

**Policy Reporter** предоставляет UI (User Interface, пользовательский интерфейс) для визуализации отчетов:

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

При развертывании через Argo CD **обязательно** использовать `server-side apply` для корректной обработки больших CRD:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kyverno
  namespace: argocd
spec:
  syncPolicy:
    automated:
      applyServerSide: true  # Обязательно для установки CRD
  source:
    repoURL: https://kyverno.github.io/kyverno
    chart: kyverno
    targetRevision: 3.3.0
    helm:
      releaseName: kyverno
      values: |
        admissionController:
          replicas: 2
```

> **Важно**: Глобальные настройки Argo CD для корректной работы с Kyverno (Server-side Diff, Resource Tracking) описаны в разделе **[Интеграция с Argo CD](./argo-cd.md)**.

---

## Дополнительная информация

### Управление правами

По умолчанию Kyverno не имеет прав на создание некоторых ресурсов (например, `Secret`). Для расширения прав используются **Aggregated Cluster Roles** ([подробнее](./additional.md)).

### Поиск и устранение неисправностей (Troubleshooting)

| Проблема | Решение |
|----------|---------|
| Webhook timeout | Увеличить `timeoutSeconds` в конфигурации webhook |
| Policies not applied | Проверить статус подов `admission-controller` и наличие лейбла `kyverno-skip-webhook` |
| Reports not generated | Проверить права `reports-controller` в ClusterRole |
| Argo CD infinite loop | Включить `server-side diff` ([подробнее в интеграции](./argo-cd.md)) |

### Удаление

```bash
# Удаление Helm release
helm uninstall kyverno -n kyverno

# Удаление namespace
kubectl delete namespace kyverno

# Удаление CRD (ВНИМАНИЕ: удалит все политики и отчеты)
kubectl delete crd clusterpolicies.kyverno.io
kubectl delete crd policies.kyverno.io
kubectl delete crd policyreports.wgpolicyk8s.io
kubectl delete crd clusterpolicyreports.wgpolicyk8s.io
```

### Связанные темы

- [Интеграция с Argo CD](./argo-cd.md) — детальная настройка совместной работы
- [Основные концепции](./concepts.md) — архитектура и принцип работы
- [Aggregated Cluster Roles](./additional.md) — управление правами доступа
- [Типы правил](./rules.md) — написание и применение политик
