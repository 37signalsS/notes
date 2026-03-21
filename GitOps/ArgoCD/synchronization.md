# ArgoCD: Синхронизация и её политики

## Определения

| Термин | Определение |
| :--- | :--- |
| **Синхронизация (Synchronization)** | Процесс приведения состояния Kubernetes-кластера в соответствие с конфигурацией из Git-репозитория |
| **Desired State** | Желаемое состояние, описанное в манифестах (YAML, Helm, Kustomize) в Git |
| **Live State** | Фактическое состояние объектов в Kubernetes-кластере |
| **OutOfSync** | Статус приложения при расхождении `Live State` и `Desired State` |
| **Sync Status** | Соответствие состояния кластера Git: `Synced` или `OutOfSync` |
| **Health Status** | Состояние здоровья ресурсов: `Healthy`, `Progressing`, `Degraded`, `Suspended`, `Missing` |

## Базовые концепции

### Цикл сверки (Reconciliation Loop)

ArgoCD Application Controller с заданной периодичностью (по умолчанию 3 минуты) или по триггеру (webhook, manual refresh):

1. Клонирует Git-репозиторий
2. Рендерит манифесты (Helm-шаблон, Kustomize, plain YAML)
3. Сравнивает результат с `Live State` в кластере
4. При расхождении присваивает статус `OutOfSync`

### Политики синхронизации

Определяются в секции `syncPolicy` манифеста `Application`:

```yaml
spec:
  syncPolicy:
    automated:
      prune: true      # Удалять ресурсы, отсутствующие в Git
      selfHeal: true   # Исправлять дрейф конфигурации
    syncOptions:
    - CreateNamespace=true
    - ServerSideApply=true
    - PrunePropagationPolicy=foreground
    - PruneLast=true
```

## Сценарии синхронизации

| Сценарий | Описание |
| :--- | :--- |
| **[Ручная синхронизация](./synchronization/scenarios/manual_sync.md)** | Изменения применяются только после явного триггера |
| **[Автоматическая синхронизация](./synchronization/scenarios/auto_sync.md)** | ArgoCD применяет изменения при обнаружении расхождений |
| **[Sync Waves и Hooks](./synchronization/scenarios/sync_waves_hooks.md)** | Управление порядком синхронизации ресурсов |
| **[Окна синхронизации](./synchronization/scenarios/sync_windows.md)** | Ограничение синхронизации по расписанию |
| **[Прогрессивная синхронизация](./synchronization/scenarios/progressive_sync.md)** | Постепенное развёртывание с валидацией (v3.x) |

## Дополнительная информация

### Расширенные возможности

| Тема | Описание |
| :--- | :--- |
| **[Игнорирование различий](./synchronization/ignore_differences.md)** | Игнорирование дрейфа и принудительная синхронизация |

### Ссылки

- **[Обзор ArgoCD](./argocd_overview.md)**
- **[Установка и настройка](./argocd_installation_and_setup.md)**
- **[Официальная документация](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)**
