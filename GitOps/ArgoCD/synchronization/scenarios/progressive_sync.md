# ArgoCD — прогрессивная синхронизация

## Определения

**Progressive Sync (прогрессивная синхронизация)** — стратегия развёртывания, позволяющая поэтапно обновлять группу кластеров, управляемых через `ApplicationSet`. Этот механизм обеспечивает контроль над радиусом поражения (blast radius) при внесении изменений в мультикластерные среды.

## Базовые концепции

Прогрессивная синхронизация была введена для решения проблемы одновременного обновления сотен кластеров, что могло привести к каскадным сбоям. Она позволяет выстраивать конвейер доставки (pipeline) непосредственно внутри ресурсов ArgoCD.

### Ключевые параметры

- **maxUpdate:** ограничивает количество кластеров, находящихся в процессе обновления одновременно. Может быть числом или процентом.
- **steps:** логические этапы развёртывания. ArgoCD переходит к следующему шагу только после успешного завершения и перехода в состояние `Healthy` всех приложений предыдущего шага.
- **matchExpressions:** мощный механизм селекторов для группировки кластеров по меткам (например, `env: dev`, `region: us-east`).

## Практические сценарии

### Пример конфигурации ApplicationSet

Данный пример демонстрирует двухэтапное развёртывание: сначала обновляется один кластер в окружении `staging`, затем — до двух кластеров в `production`.

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
          maxUpdate: 1
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

## Дополнительная информация

- **[Синхронизация ArgoCD](../../synchronization.md)** — обзор политик и механизмов сверки состояний.
- **[Автоматическая синхронизация](./auto_sync.md)** — принципы работы режима Auto-Sync.
- **[Sync Waves и Hooks](./sync_waves_hooks.md)** — управление порядком ресурсов внутри одного кластера.
