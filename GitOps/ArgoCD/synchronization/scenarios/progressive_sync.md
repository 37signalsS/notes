# ArgoCD: Прогрессивная синхронизация (Progressive Sync)

См. также: [Синхронизация](../synchronization.md), [Концепции синхронизации](../concepts.md), [Окна синхронизации](./sync_windows.md).

## Определения

**Progressive Sync** — постепенное развёртывание на несколько кластеров с валидацией на каждом этапе. Доступно в ArgoCD v3.x.

## Практические сценарии

### Пример конфигурации ApplicationSet

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: progressive-app
  namespace: argocd
spec:
  generators:
  - clusters:
      selector:
        matchLabels:
          environment: production
  template:
    metadata:
      name: 'app-{{name}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/my-org/app.git
        targetRevision: HEAD
        path: manifests
      destination:
        server: '{{server}}'
        namespace: production
      syncPolicy:
        progressiveSync:
          maxUpdate: 1  # Максимум 1 кластер за раз
          steps:
          - maxUpdate: 1
            matchExpressions:
            - key: environment
              operator: In
              values: [staging]
          - maxUpdate: 2
            matchExpressions:
            - key: environment
              operator: In
              values: [production]
```

### Параметры progressiveSync

| Параметр | Описание |
| :--- | :--- |
| `maxUpdate` | Максимальное количество кластеров для обновления за раз |
| `steps` | Определяет последовательность развёртывания с фильтрами по labels |
| `matchExpressions` | Правила отбора кластеров для каждого этапа |

Подробнее: [Sync Waves и Hooks](./sync_waves_hooks.md), [Автоматическая синхронизация](./auto_sync.md).
