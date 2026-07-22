# ArgoCD — прогрессивная синхронизация (Rolling Sync)

## Определения

**Прогрессивная синхронизация (Progressive Sync / Rolling Sync)** — стратегия развёртывания в рамках `ApplicationSet`, которая позволяет поэтапно обновлять группы приложений в нескольких кластерах. Вместо одновременного применения изменений ко всей инфраструктуре, ArgoCD выполняет обновление по заданным шагам, дожидаясь успешного завершения каждого этапа.

**RollingSync Strategy** — современный механизм ArgoCD (v2.5+), который управляет порядком синхронизации приложений. Он автоматически инициирует `Sync` для объектов со статусом `OutOfSync`, соблюдая очередность и ограничения по количеству одновременно обновляемых ресурсов.

**Health Gating (Проверка здоровья)** — принцип блокировки прогресса развёртывания. ArgoCD переходит к следующему шагу только тогда, когда все приложения текущего шага перешли в состояние `Healthy`.

## Базовые концепции

### Механика работы RollingSync

При использовании стратегии `RollingSync` контроллер `ApplicationSet` берет на себя роль оркестратора:
1.  **Отключение Auto-Sync:** При активации этой стратегии стандартная политика `syncPolicy.automated` внутри шаблона приложения игнорируется или отключается, чтобы контроллер мог управлять моментом запуска синхронизации.
2.  **Анализ шагов (Steps):** Контроллер сопоставляет приложения с правилами `matchExpressions` в каждом шаге.
3.  **Ограничение параллелизма (maxUpdate):** Параметр `maxUpdate` определяет, сколько приложений внутри одного шага могут обновляться одновременно. Это может быть фиксированное число или процент (например, `20%`).
4.  **Контроль состояния:** Если хотя бы одно приложение на текущем этапе переходит в состояние `Degraded`, развёртывание останавливается, предотвращая дальнейшее распространение ошибки (blast radius).

### Включение функционала

На текущий момент (2024–2025 гг.) прогрессивная синхронизация часто требует явного включения через параметры контроллера `ApplicationSet`.

**В ConfigMap `argocd-cmd-params-cm`:**
```yaml
data:
  applicationsetcontroller.enable.progressive.syncs: "true"
```

## Практические сценарии

### Сценарий 1: Многоэтапный деплой (Canary -> Staging -> Prod)

Классический паттерн для минимизации рисков при обновлении глобальной инфраструктуры.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: multi-stage-rollout
spec:
  generators:
  - clusters: {} # Генератор для всех подключенных кластеров
  strategy:
    type: RollingSync
    rollingSync:
      steps:
        # Шаг 1: Канареечный деплой в один тестовый кластер
        - matchExpressions:
            - key: env
              operator: In
              values: [canary]
          maxUpdate: 1
        
        # Шаг 2: Обновление всех staging-окружений параллельно
        - matchExpressions:
            - key: env
              operator: In
              values: [staging]
          # maxUpdate не указан — обновляются все сразу (100%)
          
        # Шаг 3: Поэтапное обновление Production (по 20% кластеров за раз)
        - matchExpressions:
            - key: env
              operator: In
              values: [prod]
          maxUpdate: 20%
  template:
    metadata:
      name: '{{name}}-app'
      labels:
        env: '{{metadata.labels.env}}' # Метка из метаданных кластера
    spec:
      project: default
      source:
        repoURL: https://github.com/org/repo.git
        targetRevision: HEAD
        path: manifests
      destination:
        server: '{{server}}'
        namespace: apps
```

### Сценарий 2: Использование matchExpressions для регионов

Позволяет обновлять кластеры группами по географическому признаку.

```yaml
rollingSync:
  steps:
    - matchExpressions:
        - key: region
          operator: In
          values: [eu-central-1, eu-west-1]
      maxUpdate: 50%
    - matchExpressions:
        - key: region
          operator: In
          values: [us-east-1, us-west-2]
      maxUpdate: 1
```

## Дополнительная информация

### Важные нюансы
- **Зависимость от меток:** Убедитесь, что метки в `matchExpressions` точно соответствуют меткам на кластерах или в генераторе `ApplicationSet`.
- **Кастомные проверки здоровья:** Если стандартных проверок K8s недостаточно, настройте Lua-скрипты в `argocd-cm` для корректного определения статуса `Healthy`.

### См. также
- **[Синхронизация ArgoCD](../../synchronization.md)** — общий обзор механизмов.
- **[Автоматическая синхронизация](./auto_sync.md)** — описание стандартного режима Auto-Sync.
- **[Sync Waves и Hooks](./sync_waves_hooks.md)** — управление порядком ресурсов внутри одного кластера.
- [ArgoCD Documentation: Progressive Syncs](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Progressive-Syncs/)
