# ArgoCD: Sync Waves и Hooks

> **SSoT:** Этот файл — основной источник истины для управления порядком синхронизации в ArgoCD.

## Определения

| Термин | Определение |
| :--- | :--- |
| **Sync Waves** | Механизм группировки ресурсов и применения в определённом порядке |
| **Hooks** | Ресурсы для выполнения действий до/во время/после синхронизации |

## Базовые концепции

### Sync Waves

**Sync Waves** — аннотация для группировки ресурсов и применения в определённом порядке.

Отрицательные волны применяются первыми, положительные — последними. По умолчанию все ресурсы в волне 0.

### Hooks

| Hook | Описание |
| :--- | :--- |
| `PreSync` | Выполняется перед синхронизацией (миграции БД, тесты) |
| `Sync` | Выполняется во время синхронизации |
| `PostSync` | Выполняется после синхронизации (уведомления, smoke-тесты) |
| `Skip` | Пропускается при синхронизации |

## Практические сценарии

### Sync Waves — пример применения

```yaml
# 1. CRD (wave -2)
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: mycrds.example.com
  annotations:
    argocd.argoproj.io/sync-wave: "-2"

# 2. Namespace (wave -1)
apiVersion: v1
kind: Namespace
metadata:
  name: my-app
  annotations:
    argocd.argoproj.io/sync-wave: "-1"

# 3. Deployment и Service (wave 0)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  annotations:
    argocd.argoproj.io/sync-wave: "0"

# 4. Ingress (wave 1)
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app-ingress
  annotations:
    argocd.argoproj.io/sync-wave: "1"
```

### PreSync Hook — пример миграции БД

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migration
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  template:
    spec:
      containers:
      - name: migration
        image: my-app:migration
        command: ["rails", "db:migrate"]
      restartPolicy: Never
  backoffLimit: 1
```

### Политики удаления Hooks

| Политика | Описание |
| :--- | :--- |
| `HookSucceeded` | Удалить после успешного выполнения |
| `HookFailed` | Удалить после неудачи |
| `BeforeHookCreation` | Удалить старый hook перед созданием нового |

## Дополнительная информация

### Ссылки

- **[Основные концепции синхронизации](../concepts.md)**
- **[Ручная синхронизация](./manual_sync.md)**
- **[Автоматическая синхронизация](./auto_sync.md)**
