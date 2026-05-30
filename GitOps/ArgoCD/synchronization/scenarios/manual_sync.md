# ArgoCD — ручная синхронизация

## Определения

**Manual Sync (ручная синхронизация)** — режим работы ArgoCD Application, при котором автоматическое применение изменений (Auto-Sync) отключено. ArgoCD отслеживает расхождения (drift) между Git и кластером, но требует явного подтверждения пользователя для их устранения.

## Базовые концепции

По умолчанию ArgoCD работает в режиме ручной синхронизации. Если секция `syncPolicy` в манифесте `Application` отсутствует, изменения в Git приведут к изменению статуса приложения на `OutOfSync`, но ресурсы в кластере затронуты не будут.

### Когда использовать

- **Production-окружения:** для предотвращения случайных или неконтролируемых изменений.
- **Сложные миграции:** когда требуется ручной контроль на каждом этапе развёртывания.
- **Compliance:** если регламенты требуют обязательного ручного одобрения (approval) перед внесением изменений в инфраструктуру.

## Практические сценарии

### Пример конфигурации Application

Для активации ручного режима достаточно не указывать `automated` в `syncPolicy` или полностью опустить эту секцию.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: manual-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/argoproj/argocd-example-apps.git
    path: guestbook
    targetRevision: HEAD
  destination:
    server: https://kubernetes.default.svc
    namespace: default
  # syncPolicy не указан — по умолчанию Manual
```

### Управление через CLI

Основные команды для работы с ручной синхронизацией:

```bash
# Проверка наличия расхождений (diff)
argocd app diff manual-app

# Запуск процесса синхронизации всех ресурсов
argocd app sync manual-app

# Синхронизация с конкретным коммитом или тегом
argocd app sync manual-app --revision v1.2.0

# Ожидание завершения синхронизации и перехода в Healthy
argocd app wait manual-app --sync --health
```

## Дополнительная информация

- **[Синхронизация ArgoCD](../../synchronization.md)** — общий обзор механизмов синхронизации.
- **[Автоматическая синхронизация](./auto_sync.md)** — настройка и параметры Auto-Sync.
- **[Sync Waves и Hooks](./sync_waves_hooks.md)** — управление порядком развёртывания ресурсов.
