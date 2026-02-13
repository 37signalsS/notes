# ArgoCD: Синхронизация и ее Политики

Синхронизация в ArgoCD — это ключевой процесс, который приводит состояние вашего Kubernetes-кластера в соответствие с конфигурацией, описанной в Git-репозитории.

## Определения

- **Синхронизация (Synchronization)**: Процесс анализа и применения изменений из Git в кластер. Цель — устранить расхождения между желаемым и реальным состоянием.
- **Desired State (Желаемое состояние)**: Конфигурация, описанная в манифестах (YAML, Helm, Kustomize) в Git-репозитории. Это "источник истины".
- **Live State (Реальное состояние)**: Фактическое состояние объектов, работающих в Kubernetes-кластере.
- **OutOfSync**: Статус, который присваивается приложению, если его `Live State` не соответствует `Desired State`.

## Основные концепции

### Цикл Сверки (Reconciliation Loop)

ArgoCD Application Controller с заданной периодичностью (по умолчанию 3 минуты) или по триггеру (webhook, ручной refresh):
1.  Клонирует Git-репозиторий.
2.  Рендерит манифесты (например, обрабатывает Helm-шаблон).
3.  Сравнивает результат с `Live State` в кластере.
4.  Если обнаружено расхождение, приложение получает статус `OutOfSync`.

### Статусы Приложения

ArgoCD отслеживает два независимых статуса:
- **Sync Status**: Показывает, соответствует ли `Live State` состоянию `Desired State`. Значения: `Synced`, `OutOfSync`.
- **Health Status**: Показывает состояние здоровья задеплоенных ресурсов. Значения: `Healthy`, `Progressing`, `Degraded`, `Suspended`, `Missing`.

## Практические сценарии

Политика синхронизации определяется в секции `syncPolicy` манифеста `Application`.

### Сценарий 1: Ручная синхронизация (Manual Sync)

Это поведение по умолчанию. ArgoCD обнаружит расхождение и покажет статус `OutOfSync`, но не будет предпринимать никаких действий. Оператор должен вручную нажать кнопку "Sync" в интерфейсе.

**Когда использовать**: Для критичных production-окружений, где каждое изменение должно проходить дополнительную проверку человеком.

```yaml
# syncPolicy не указан, используется Manual по умолчанию
spec:
  project: default
  source:
    repoURL: https://git.example.com/repo.git
    path: my-app
    targetRevision: HEAD
  destination:
    server: https://kubernetes.default.svc
    namespace: my-app
```

### Сценарий 2: Автоматическая синхронизация (Auto-Sync)

В этом режиме ArgoCD автоматически применяет изменения из Git, как только они обнаруживаются.

**Когда использовать**: Для dev/staging окружений или для приложений, где скорость доставки важнее ручного контроля.

Ключевые параметры `automated`:
- `prune: true`: Автоматически удалять ресурсы, которые были удалены из Git.
- `selfHeal: true`: Автоматически исправлять "дрейф" — ручные изменения, сделанные в кластере в обход Git.

```yaml
spec:
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true # Автоматически создавать namespace
      - ServerSideApply=true # Использовать Server-Side Apply для лучшей обработки конфликтов
```

### Сценарий 3: Управление порядком и хуками (Sync Waves & Hooks)

Иногда ресурсы нужно создавать в определенном порядке (например, CRD, затем сам ресурс).
- **Sync Waves**: Аннотация `argocd.argoproj.io/sync-wave: "N"` позволяет группировать ресурсы. ArgoCD сначала применит ресурсы с меньшим `N`.
- **Hooks**: Аннотации `PreSync`, `Sync`, `PostSync` позволяют запускать Jobs или другие ресурсы до, во время или после синхронизации для выполнения миграций, тестов и т.д.

```yaml
# Этот Job запустится перед синхронизацией
apiVersion: batch/v1
kind: Job
metadata:
  name: pre-sync-job
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
```

### Сценарий 4: Ограничение авто-синхронизации (Sync Windows)

Для предотвращения нежелательных изменений в определенное время (например, в часы пиковой нагрузки или во время code freeze) используются окна синхронизации. Они настраиваются на уровне `AppProject`.

**Когда использовать**: В production-окружениях, чтобы запретить автоматические деплои по ночам или в праздники.

```yaml
# Пример AppProject с окнами синхронизации
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: production-apps
spec:
  # ...
  syncWindows:
  # Разрешаем авто-синк только в рабочие часы
  - kind: allow
    schedule: '0 9-18 * * 1-5' # 9:00-18:00 по будням
    duration: 1h
    timeZone: "Europe/Moscow"
  # Запрещаем авто-синк в конце года
  - kind: deny
    schedule: '0 0 25 12 *' # с 25 декабря
    duration: 168h # на неделю
```

## Дополнительная информация

- **[Обзор ArgoCD](./argocd_overview.md)**: Введение в ArgoCD и его архитектуру.
- **Официальная документация**: [Sync Policies and Options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)
