# Установка Kyverno

## Определения

**Установка Kyverno** — процесс развертывания компонентов управления политиками в кластер Kubernetes. В современной инфраструктуре (актуально на 2026 год, версия 1.18+) стандартом является установка через **Helm** в режиме высокой доступности (**High Availability, HA**) с использованием нативного движка **CEL (Common Expression Language)**.

---

## Основные концепции

### Компоненты системы

| Компонент | Назначение | Режим (HA) |
| :--- | :--- | :--- |
| **Admission Controller** | Основной движок: обработка мутаций, валидаций и верификаций образов. | 3 реплики |
| **Background Controller** | Применение политик к существующим ресурсам и управление генерацией. | 2 реплики |
| **Reports Controller** | Сбор и агрегация отчетов `PolicyReport`. Поддерживает внешние БД для масштабирования. | 2 реплики |
| **Cleanup Controller** | Автоматическое удаление ресурсов по расписанию (DeletingPolicy). | 2 реплики |

### Системные требования (Production-ready)

| Параметр | Минимальные | Рекомендуемые (1000+ подов) |
| :--- | :--- | :--- |
| Kubernetes | 1.27+ | 1.30+ |
| CPU | 2 ядра | 4+ ядра (суммарно на компоненты) |
| RAM | 2 GB | 8+ GB |
| Хранилище | Не требуется (etcd) | Внешняя БД (для масштабных отчетов) |

---

## Практические сценарии

### Промышленная установка через Helm (HA + CEL)

Для обеспечения отказоустойчивости рекомендуется использовать файл `values.yaml` с настройками распределения подов по узлам и зонам.

```bash
# Добавление и обновление репозитория
helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo update

# Установка с использованием конфигурационного файла
helm install kyverno kyverno/kyverno \
  --namespace kyverno \
  --create-namespace \
  --version 3.8.0 \
  -f values.yaml
```

**Пример оптимального `values.yaml` (v1.18):**
```yaml
admissionController:
  replicas: 3
  # Защита от удаления API-сервером при нехватке ресурсов
  priorityClassName: system-cluster-critical
  containerSecurityContext:
    allowPrivilegeEscalation: false
    capabilities: { drop: ["ALL"] }
    readOnlyRootFilesystem: true
    runAsNonRoot: true
  # Безопасность внешних вызовов (Защита от SSRF)
  externalHttp:
    allowedHosts: ["sigstore.dev", "api.github.com"]
    blockedHosts: ["169.254.169.254", "localhost"]

backgroundController:
  replicas: 2

reportsController:
  replicas: 2
  extraArgs:
    - --reportsChunkSize=1000 # Оптимизация памяти

webhooks:
  # Исключение критических пространств имен для предотвращения Deadlock
  namespaceSelector:
    matchExpressions:
      - key: kubernetes.io/metadata.name
        operator: NotIn
        values: ["kyverno", "kube-system", "monitoring"]
```

### Верификация установки

После завершения процесса установки необходимо убедиться в работоспособности всех контроллеров и вебхуков:

```bash
# 1. Проверка статуса подов
kubectl get pods -n kyverno -o wide
# → Все поды должны быть в статусе Running и распределены по разным узлам.

# 2. Проверка регистрации вебхуков в API-сервере
kubectl get mutatingwebhookconfigurations,validatingwebhookconfigurations -l app.kubernetes.io/instance=kyverno

# 3. Проверка установленных CRD
kubectl get crd | grep kyverno.io
```

### Развертывание через Argo CD (GitOps)

При установке через Argo CD критически важно использовать **Server-Side Apply (SSA)** для корректной обработки объемных CRD Kyverno.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kyverno-core
  namespace: argocd
spec:
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true # ОБЯЗАТЕЛЬНО для CRD
  source:
    repoURL: https://kyverno.github.io/kyverno
    chart: kyverno
    targetRevision: 3.8.0
    helm:
      values: |
        admissionController:
          replicas: 3
```
*Подробнее о специфических настройках дрифта и визуализации отчетов см. в разделе [Интеграция с Argo CD](./argo-cd.md).*

---

## Дополнительная информация

### Безопасность и права (RBAC)

По умолчанию Kyverno имеет ограниченные права. Если ваши политики должны создавать ресурсы (например, `NetworkPolicy` при создании `Namespace`), необходимо расширить права через **Aggregated Cluster Roles** ([подробнее](./additional.md)).

### Поиск и устранение неисправностей (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Deadlock при старте кластера** | Kyverno пытается проверить поды CNI/CSI, которые еще не запустились. | Добавьте метку `kyverno-skip-webhook=true` на системные Namespace или настройте `namespaceSelector` в Helm. |
| **Webhook timeout** | Высокая нагрузка или сетевые задержки. | Увеличить ресурсы CPU для `admissionController` или значение `timeoutSeconds` в настройках вебхука. |
| **CRD слишком велики для kubectl** | Лимит аннотации `last-applied-configuration`. | Всегда используйте флаг `--server-side` при применении манифестов вручную. |
| **Отчеты занимают слишком много места в etcd** | Большое количество ресурсов в кластере. | Включите агрегацию отчетов или настройте экспорт во внешнюю БД через `Reports Controller`. |

### Удаление Kyverno

При удалении важно соблюдать порядок, чтобы не оставить "висящих" вебхуков, которые заблокируют кластер.

1. Удалить все `ClusterPolicy` и `Policy`.
2. Выполнить `helm uninstall kyverno -n kyverno`.
3. Удалить CRD вручную (только если планируете полную очистку данных): `kubectl delete crd -l app.kubernetes.io/instance=kyverno`.

### См. также
- [Интеграция с Argo CD: Server-Side Diff и Health Checks](./argo-cd.md)
- [Основные концепции: Механизм Admission и CEL](./concepts.md)
- [Типы правил: написание эффективных политик](./rules.md)
