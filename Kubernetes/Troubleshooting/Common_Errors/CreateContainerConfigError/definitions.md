# CreateContainerConfigError: Определения

## Definitions

**`CreateContainerConfigError`** — ошибка, возникающая до запуска контейнера, означающая, что `kubelet` не может создать конфигурацию контейнера из-за проблем с зависимостями (ConfigMap, Secret, Volume).

## Basic Concepts

### Workflow создания контейнера

```
Pod создан
    ↓
Scheduler выбирает узел
    ↓
Kubelet получает задачу
    ↓
Проверка зависимостей (ConfigMap, Secret, PV)
    ↓
❌ Зависимость не найдена → CreateContainerConfigError
    ↓
✅ Все зависимости есть → Create Container → Start
```

### Типы зависимостей

| Зависимость | Описание | Частая ошибка |
|-------------|----------|---------------|
| **ConfigMap** | Конфигурационные данные | `configmap "x" not found` |
| **Secret** | Секретные данные | `secret "x" not found` |
| **PersistentVolumeClaim** | Постоянное хранилище | `pvc "x" not found` |
| **Projected Volume** | Комбинация источников | `projected volume error` |
| **Downward API** | Метаданные пода | `downward API error` |

### Сравнение ошибок

| Ошибка | Когда возникает | Решение |
|--------|-----------------|---------|
| **CreateContainerConfigError** | До запуска, проблемы с зависимостями | Создать ConfigMap/Secret/PVC |
| **ImagePullBackOff** | До запуска, проблемы с образом | Исправить образ/imagePullSecrets |
| **CrashLoopBackOff** | После запуска, падение приложения | Исправить приложение/конфигурацию |

## Practical Scenarios

### Сценарий: Быстрая идентификация типа ошибки

```bash
# Шаг 1: Проверка статуса пода
kubectl get pod <pod-name> -n <namespace>

# Шаг 2: Детальная информация (раздел Events)
kubectl describe pod <pod-name> -n <namespace>

# Шаг 3: Поиск конкретной причины
kubectl describe pod <pod-name> -n <namespace> | grep -i "Error:"
```

**Результат** укажет на тип отсутствующей зависимости:

| Сообщение в Events | Тип зависимости | Ссылка на решение |
|--------------------|-----------------|-------------------|
| `configmap "x" not found` | ConfigMap | [configmap_issues.md](./configmap_issues.md) |
| `secret "x" not found` | Secret | [secret_issues.md](./secret_issues.md) |
| `persistentvolumeclaim "x" not found` | PVC | [pvc_issues.md](./pvc_issues.md) |
| `projected volume error` | Projected Volume | [volume_issues.md](./volume_issues.md) |

### Сценарий: Проверка ServiceAccount и RBAC

Если ConfigMap/Secret существуют, но ошибка сохраняется — возможна ограничение прав ServiceAccount.

```bash
# Проверка ServiceAccount пода
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.serviceAccountName}'

# Проверка прав доступа к Secret
kubectl auth can-i get secret/<secret-name> --as=system:serviceaccount:<namespace>:<sa-name> -n <namespace>

# Проверка прав доступа к ConfigMap
kubectl auth can-i get configmap/<configmap-name> --as=system:serviceaccount:<namespace>:<sa-name> -n <namespace>
```

Подробная диагностика RBAC: [rbac_issues.md](./rbac_issues.md).

## Additional Information

### Связь с Pod Lifecycle

`CreateContainerConfigError` возникает на этапе **Container Configuration** — до попытки запуска контейнера. Это отличает его от:

- `Pending` — Pod ещё не назначен на узел (Scheduling)
- `Waiting` — Pod на узле, но контейнер не запущен (сюда входит CreateContainerConfigError)
- `Running` — Контейнер запущен
- `Terminated` — Контейнер завершён

Подробнее: [Pod Lifecycle](../../../Base/Pod/pod_lifecycle_and_state.md).

### Автоматическое восстановление

Kubernetes периодически повторяет проверку зависимостей. При создании отсутствовавшего ресурса Pod перейдёт в `Running` автоматически (задержка ~10–30 сек). Ручной restart обычно не требуется.

### Связанные ресурсы

- Диагностика: [diagnostics.md](./diagnostics.md)
- ConfigMap: [configmap_issues.md](./configmap_issues.md)
- Secrets: [secret_issues.md](./secret_issues.md)
- PVC: [pvc_issues.md](./pvc_issues.md)
- Volume: [volume_issues.md](./volume_issues.md)
- RBAC: [rbac_issues.md](./rbac_issues.md)
- Профилактика: [prevention.md](./prevention.md)
- Обзор ошибки: [create_container_config_error.md](../create_container_config_error.md)
- Troubleshooting overview: [troubleshooting_overview.md](../../troubleshooting_overview.md)
