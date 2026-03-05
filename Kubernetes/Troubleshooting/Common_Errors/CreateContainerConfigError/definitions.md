# CreateContainerConfigError: Определения

## Определения

**`CreateContainerConfigError`** — ошибка, возникающая до запуска контейнера, означающая, что `kubelet` не может создать конфигурацию контейнера из-за проблем с зависимостями (ConfigMap, Secret, Volume).

> - ConfigMap: [`../../../Base/configmap.md`](../../../Base/configmap.md)
> - Secrets: [`../../../Base/secrets/external_managers.md`](../../../Base/secrets/external_managers.md)
> - Volumes: [`../../../Base/Pod/pod_volumes.md`](../../../Base/Pod/pod_volumes.md)
> - PVC/PV: [`../../../Storage/pv_and_pvc.md`](../../../Storage/pv_and_pvc.md)
> - RBAC: [`../../../Security/rbac/rbac_overview.md`](../../../Security/rbac/rbac_overview.md)

## Основные концепции

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
