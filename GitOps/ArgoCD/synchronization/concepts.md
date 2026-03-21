# ArgoCD: Основные определения и концепции синхронизации

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

### Типы синхронизации

| Тип | Описание |
| :--- | :--- |
| **Manual Sync** | Ручная синхронизация — изменения применяются только после явного триггера |
| **Auto-Sync** | Автоматическая синхронизация — ArgoCD применяет изменения при обнаружении расхождений |
| **Progressive Sync** | Прогрессивная синхронизация — постепенное развёртывание с валидацией на каждом этапе |

### Ключевые параметры автоматической синхронизации

| Параметр | Описание |
| :--- | :--- |
| `prune: true` | Автоматически удалять ресурсы, удалённые из Git |
| `selfHeal: true` | Автоматически исправлять ручные изменения в кластере |

### Опции синхронизации (syncOptions)

| Опция | Описание |
| :--- | :--- |
| `CreateNamespace=true` | Автоматически создавать целевой namespace |
| `ServerSideApply=true` | Использовать Server-Side Apply для обработки конфликтов |
| `PrunePropagationPolicy=foreground` | Ждать удаления ресурсов перед продолжением |
| `PruneLast=true` | Удалять ресурсы после применения остальных изменений |
| `RespectIgnoreDifferences=true` | Игнорировать указанные различия при синхронизации |

## Дополнительная информация

### Ссылки

- **[Ручная синхронизация](./scenarios/manual_sync.md)**
- **[Автоматическая синхронизация](./scenarios/auto_sync.md)**
- **[Sync Waves и Hooks](./scenarios/sync_waves_hooks.md)**
- **[Окна синхронизации](./scenarios/sync_windows.md)**
- **[Прогрессивная синхронизация](./scenarios/progressive_sync.md)**
- **[Игнорирование различий](./ignore_differences.md)**
- **[Обзор ArgoCD](../argocd_overview.md)**
- **[Установка и настройка](../argocd_installation_and_setup.md)**
