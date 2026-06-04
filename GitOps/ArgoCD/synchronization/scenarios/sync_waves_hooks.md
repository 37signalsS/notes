# ArgoCD — Sync Waves и Hooks

## Определения

**Sync Waves (волны синхронизации)** — механизм ArgoCD, позволяющий группировать ресурсы и определять строгий порядок их применения в кластере.

**Hooks (хуки)** — специальные аннотации ресурсов, которые позволяют выполнять определенные действия на разных этапах жизненного цикла синхронизации (до, во время или после применения манифестов).

## Базовые концепции

### Порядок применения (Sync Waves)

ArgoCD использует аннотацию `argocd.argoproj.io/sync-wave` для управления последовательностью деплоя:

- Значение волны может быть любым целым числом (включая отрицательные).
- Ресурсы с меньшим значением волны применяются первыми.
- Контроллер переходит к следующей волне только после того, как все ресурсы текущей волны перешли в статус `Healthy`.
- По умолчанию все ресурсы относятся к волне `0`.

### Жизненный цикл (Hooks)

Хуки реализуются через аннотацию `argocd.argoproj.io/hook`. Основные типы:

- **PreSync:** запуск перед применением манифестов (например, подготовка схемы БД).
- **Sync:** запуск одновременно с основными ресурсами.
- **PostSync:** запуск после успешного завершения синхронизации (например, отправка уведомлений или smoke-тесты).
- **SyncFail:** запуск только в случае ошибки при синхронизации.
- **Skip:** ресурс будет пропущен при синхронизации.

## Практические сценарии

### Настройка Sync Waves

Пример разделения ресурсов на этапы подготовки и деплоя:

```yaml
# 1. Подготовка CRD (wave -2)
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: examples.custom.com
  annotations:
    argocd.argoproj.io/sync-wave: "-2"

# 2. Создание Namespace (wave -1)
apiVersion: v1
kind: Namespace
metadata:
  name: app-namespace
  annotations:
    argocd.argoproj.io/sync-wave: "-1"

# 3. Основные ресурсы (wave 0 - по умолчанию)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app-deployment
  namespace: app-namespace
```

### Использование Hooks для миграций

Пример запуска Job для миграции базы данных перед обновлением приложения:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: database-migration
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  template:
    spec:
      containers:
      - name: migrate
        image: backend:latest
        command: ["/app/migrate.sh"]
      restartPolicy: Never
```

### Политики удаления хуков

Аннотация `argocd.argoproj.io/hook-delete-policy` определяет, когда ArgoCD должен удалить ресурс хука:

- **HookSucceeded:** после успешного завершения.
- **HookFailed:** в случае ошибки выполнения.
- **BeforeHookCreation:** удаляет старый хук непосредственно перед созданием нового.

## Дополнительная информация

- **[Синхронизация ArgoCD](../../synchronization.md)** — общие принципы и политики синхронизации.
- **[Автоматическая синхронизация](./auto_sync.md)** — настройка Auto-Sync.
- **[Окна синхронизации](./sync_windows.md)** — временные ограничения на внесение изменений.
