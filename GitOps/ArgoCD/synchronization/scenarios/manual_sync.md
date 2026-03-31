# ArgoCD: Ручная синхронизация (Manual Sync)

См. также: [Синхронизация](../synchronization.md), [Концепции синхронизации](../concepts.md), [Автоматическая синхронизация](./auto_sync.md).

## Определения

**Manual Sync** — режим синхронизации, при котором ArgoCD обнаруживает расхождение, но не применяет изменения автоматически.

## Базовые концепции

**Поведение по умолчанию.** ArgoCD обнаруживает расхождение и показывает статус `OutOfSync`, но не применяет изменения автоматически.

### Когда использовать

- Production-окружения с требованием ручного подтверждения
- Критичные изменения, требующие проверки
- Окружения с compliance-требованиями

## Практические сценарии

### Пример конфигурации

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://git.example.com/repo.git
    path: my-app
    targetRevision: HEAD
  destination:
    server: https://kubernetes.default.svc
    namespace: my-app
  # syncPolicy не указан — Manual по умолчанию
```

### Команды CLI

```bash
# Просмотр различий
argocd app diff my-app

# Запуск синхронизации
argocd app sync my-app

# Синхронизация с конкретной ревизией
argocd app sync my-app --revision abc123

# Ожидание завершения
argocd app wait my-app --sync --health
```

Подробнее: [Sync Waves и Hooks](./sync_waves_hooks.md), [Окна синхронизации](./sync_windows.md).
