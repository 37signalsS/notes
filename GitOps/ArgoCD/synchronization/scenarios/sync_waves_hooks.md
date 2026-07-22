# ArgoCD — волны синхронизации (Sync Waves) и хуки (Hooks)

## Определения

**Волны синхронизации (Sync Waves)** — механизм ArgoCD для управления строгим порядком применения ресурсов. Он позволяет группировать объекты и определять последовательность их деплоя на основе статуса здоровья (`Healthy`) предыдущей группы.

**Хуки (Hooks)** — специальные аннотации, позволяющие запускать скрипты или задачи (обычно Kubernetes Jobs) на разных этапах жизненного цикла синхронизации. Хуки не являются частью желаемого состояния приложения и считаются эфемерными ресурсами.

**Политики удаления хуков (Hook Delete Policies)** — настройки, определяющие момент автоматического удаления ресурсов хука после их выполнения.

## Базовые концепции

### Механика волн синхронизации

Управление осуществляется через аннотацию `argocd.argoproj.io/sync-wave`.

- **Порядок выполнения:** Ресурсы с меньшим числовым значением (включая отрицательные) применяются первыми.
- **Условие перехода (Health Gating):** ArgoCD переходит к следующей волне только тогда, когда все ресурсы текущей волны перешли в статус `Healthy`.
- **Значение по умолчанию:** Если аннотация отсутствует, ресурс относится к волне `0`.
- **Рекомендация (Sparse Numbering):** Используйте "разреженную" нумерацию (например, `-10`, `0`, `10`), чтобы иметь возможность добавлять промежуточные этапы без переписывания всех аннотаций.

### Жизненный цикл хуков

Хуки настраиваются через аннотацию `argocd.argoproj.io/hook`. Основные типы:

1.  **PreSync:** Запуск до применения основных манифестов. Идеально для миграций БД или очистки кеша.
2.  **Sync:** Запуск одновременно с основными ресурсами.
3.  **PostSync:** Запуск после успешного перехода всех ресурсов приложения в статус `Healthy`. Подходит для smoke-тестов или уведомлений.
4.  **SyncFail:** Запуск только в случае ошибки синхронизации. Используется для оповещения об инцидентах или очистки "зависших" ресурсов.
5.  **Skip:** Ресурс будет полностью проигнорирован в процессе синхронизации.

## Практические сценарии

### Сценарий 1: Сложная последовательность деплоя (Sync Waves)

Рекомендуемый паттерн для инфраструктурных приложений.

```yaml
# 1. Регистрация CRD (Волна -10)
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: myconfigs.example.com
  annotations:
    argocd.argoproj.io/sync-wave: "-10"

# 2. Создание Namespace и ConfigMap (Волна -5)
apiVersion: v1
kind: Namespace
metadata:
  name: my-app
  annotations:
    argocd.argoproj.io/sync-wave: "-5"

# 3. Основное приложение (Волна 0)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-server
  namespace: my-app
```

### Сценарий 2: Миграция БД и очистка (Hooks + Delete Policy)

Использование `BeforeHookCreation` гарантирует, что новая синхронизация удалит старую Job перед созданием новой, предотвращая конфликты имен.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: schema-migration
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation, HookSucceeded
spec:
  template:
    spec:
      containers:
      - name: migrate
        image: backend:latest
        command: ["/app/migrate.sh"]
      restartPolicy: Never
```

### Сценарий 3: Оповещение об ошибке (SyncFail)

Запуск задачи для отправки уведомления в Slack при сбое деплоя.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: failure-notification
  annotations:
    argocd.argoproj.io/hook: SyncFail
spec:
  template:
    spec:
      containers:
      - name: notify
        image: alpine
        command: ["sh", "-c", "curl -X POST -d 'Sync Failed' $SLACK_WEBHOOK"]
      restartPolicy: Never
```

## Дополнительная информация

### Важные нюансы
- **Health Checks для CRD:** По умолчанию ArgoCD считает Custom Resource здоровым сразу после создания. Для корректной работы волн с операторами необходимо настроить Lua-скрипты проверки здоровья в `argocd-cm`.
- **Таймауты:** Если хук (например, Job) выполняется слишком долго, синхронизация может быть прервана по таймауту.

### См. также
- **[Синхронизация ArgoCD](../../synchronization.md)** — общий обзор механизмов.
- **[Автоматическая синхронизация](./auto_sync.md)** — настройка параметров `automated` и `selfHeal`.
- **[Игнорирование различий](../ignore_differences.md)** — скрытие динамических полей из сверки.
- [ArgoCD Documentation: Resource Hooks](https://argo-cd.readthedocs.io/en/stable/user-guide/resource_hooks/)
