# ArgoCD: Автоматическая синхронизация (Auto-Sync)

> **SSoT:** Этот файл — основной источник истины для автоматической синхронизации ArgoCD.

## Определения

| Термин | Определение |
| :--- | :--- |
| **Auto-Sync** | Режим синхронизации, при котором ArgoCD автоматически применяет изменения из Git при их обнаружении |

## Базовые концепции

ArgoCD автоматически применяет изменения из Git при их обнаружении.

### Когда использовать

- Dev/Staging-окружения
- Приложения с высокой частотой развёртываний
- Команды с зрелыми CI/CD-процессами

### Ключевые параметры

| Параметр | Описание |
| :--- | :--- |
| `prune: true` | Автоматически удалять ресурсы, удалённые из Git |
| `selfHeal: true` | Автоматически исправлять ручные изменения в кластере |

## Практические сценарии

### Пример конфигурации

```yaml
spec:
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
    - ServerSideApply=true
    - PrunePropagationPolicy=foreground
    - PruneLast=true
    - RespectIgnoreDifferences=true
```

### Опции syncOptions

| Опция | Описание |
| :--- | :--- |
| `CreateNamespace=true` | Автоматически создавать целевой namespace |
| `ServerSideApply=true` | Использовать Server-Side Apply для обработки конфликтов |
| `PrunePropagationPolicy=foreground` | Ждать удаления ресурсов перед продолжением |
| `PruneLast=true` | Удалять ресурсы после применения остальных изменений |
| `RespectIgnoreDifferences=true` | Игнорировать указанные различия при синхронизации |

## Дополнительная информация

### Ссылки

- **[Основные концепции синхронизации](../concepts.md)**
- **[Ручная синхронизация](./manual_sync.md)**
- **[Sync Waves и Hooks](./sync_waves_hooks.md)**
- **[Окна синхронизации](./sync_windows.md)**
