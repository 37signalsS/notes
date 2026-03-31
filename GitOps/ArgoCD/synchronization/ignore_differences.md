# ArgoCD: Игнорирование различий и принудительная синхронизация

См. также: [Синхронизация](../synchronization.md), [Концепции синхронизации](./concepts.md).

## Определения

**Ignore Differences** — механизм игнорирования определённых различий между Desired State и Live State. Используется для ресурсов, где допустим дрейф конфигурации (например, `replicas` для HPA).

**Force Sync** — принудительная синхронизация с игнорированием различий между состояниями.

## Базовые концепции

### Игнорирование различий (Ignore Differences)

Для ресурсов, где допустим дрейф (например, `replicas` для HPA), можно настроить игнорирование определённых полей.

### Принудительная синхронизация

Позволяет принудительно применить изменения, игнорируя различия между состояниями.

## Практические сценарии

### Пример ignoreDifferences

```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    jsonPointers:
    - /spec/replicas
  - group: autoscaling
    kind: HorizontalPodAutoscaler
    jqPathExpressions:
    - .spec.minReplicas
    - .spec.maxReplicas
```

### Команды принудительной синхронизации

```bash
# Принудительное применение (игнорируя различия)
argocd app sync my-app --force

# Пропуск проверки здоровья
argocd app sync my-app --skip-schema-validation
```

### Типы сравнения различий

| Тип | Описание |
| :--- | :--- |
| `jsonPointers` | JSON Pointer для точного пути в объекте |
| `jqPathExpressions` | jq-выражение для извлечения значения |

[Официальная документация по ignoreDifferences](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/).
