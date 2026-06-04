# ArgoCD — игнорирование различий и принудительная синхронизация

## Определения

**Ignore Differences** — механизм ArgoCD, позволяющий игнорировать расхождения между желаемым состоянием (Git) и фактическим состоянием (кластер) для конкретных полей ресурсов.

**Force Sync** — режим синхронизации, при котором ArgoCD принудительно применяет манифесты, даже если возникают конфликты или ошибки валидации, которые обычно блокируют процесс.

## Базовые концепции

### Игнорирование различий (Ignore Differences)

Используется в случаях, когда определённые поля ресурсов управляются внешними контроллерами или изменяются динамически в кластере, и эти изменения не должны приводить к статусу `OutOfSync`.

Типичные примеры:

- Поле `replicas` при использовании Horizontal Pod Autoscaler (HPA).
- Метаданные (labels, annotations), добавляемые облачными провайдерами или сервисными сетками (Service Mesh).
- Специфические поля в CRD (например, сертификаты).

### Параметр RespectIgnoreDifferences

При использовании автоматической синхронизации (`automated sync`), ArgoCD по умолчанию может игнорировать настройки `ignoreDifferences` при принятии решения о запуске цикла синхронизации. Чтобы ArgoCD учитывал эти настройки и не запускал синхронизацию при изменениях в игнорируемых полях, необходимо включить опцию `RespectIgnoreDifferences=true` в `syncOptions`.

### Принудительная синхронизация (Force Sync)

Опция `--force` (или `force: true` в API) заставляет ArgoCD использовать `kubectl apply --force`. Это может быть необходимо, если:

- Ресурс застрял в состоянии ошибки.
- Произошёл критический конфликт полей.
- Требуется пересоздание ресурса "на лету".

## Практические сценарии

### Конфигурация ignoreDifferences

Настройка выполняется в секции `spec` ресурса `Application`. Можно использовать `jsonPointers` или `jqPathExpressions`.

```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    jsonPointers:
    - /spec/replicas # Игнорировать количество реплик (для HPA)
  - group: autoscaling
    kind: HorizontalPodAutoscaler
    jqPathExpressions:
    - .spec.minReplicas
    - .spec.maxReplicas
```

### Настройка в syncOptions

Для корректной работы с автоматической синхронизацией:

```yaml
spec:
  syncPolicy:
    automated:
      selfHeal: true
    syncOptions:
    - RespectIgnoreDifferences=true
```

### Команды CLI

Принудительная синхронизация через `argocd`:

```bash
# Принудительная синхронизация приложения
argocd app sync my-app --force

# Синхронизация с пропуском валидации схемы (аналог --validate=false)
argocd app sync my-app --skip-schema-validation
```

## Дополнительная информация

- **[Синхронизация ArgoCD](../synchronization.md)** — общий обзор политик синхронизации.
- **[Автоматическая синхронизация](./scenarios/auto_sync.md)** — настройка автоматического применения изменений.
- **[Ручная синхронизация](./scenarios/manual_sync.md)** — порядок ручного подтверждения изменений.
- [Официальная документация ArgoCD по Sync Options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)
