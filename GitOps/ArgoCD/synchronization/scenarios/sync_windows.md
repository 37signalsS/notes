# ArgoCD: Окна синхронизации (Sync Windows)

См. также: [Синхронизация](../synchronization.md), [Концепции синхронизации](../concepts.md), [Автоматическая синхронизация](./auto_sync.md).

## Определения

**Sync Windows** — механизм ограничения автоматической синхронизации по расписанию. Настраивается на уровне `AppProject`.

### Когда использовать

- Запрет деплоев в нерабочее время
- Code freeze в праздничные периоды
- Ограничение деплоев в часы пик

### Параметры Sync Window

| Параметр | Описание |
| :--- | :--- |
| `kind` | `allow` (разрешение) или `deny` (запрет) |
| `schedule` | Cron-выражение |
| `duration` | Длительность окна (например, `1h`, `168h`) |
| `timeZone` | Часовой пояс (например, `Europe/Moscow`) |
| `applications` | Список приложений или wildcard |
| `manualSync` | Разрешить ручную синхронизацию вне окна |

## Практические сценарии

### Пример конфигурации AppProject

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: production-apps
  namespace: argocd
spec:
  description: "Production приложения"
  sourceRepos:
  - 'https://github.com/my-org/production-repo.git'
  destinations:
  - namespace: 'prod'
    server: 'https://kubernetes.default.svc'
  
  syncWindows:
  # Разрешение: будни 9:00-18:00 MSK
  - kind: allow
    schedule: '0 9-18 * * 1-5'
    duration: 1h
    timeZone: "Europe/Moscow"
    applications:
    - '*-prod'
    manualSync: true  # Ручная синхронизация разрешена всегда
  
  # Запрет: с 25 декабря на неделю
  - kind: deny
    schedule: '0 0 25 12 *'
    duration: 168h  # 7 дней
    timeZone: "Europe/Moscow"
    applications:
    - '*-prod'
```

### Проверка активных окон

```bash
argocd proj get production-apps
```

Подробнее: [Прогрессивная синхронизация](./progressive_sync.md), [Sync Waves и Hooks](./sync_waves_hooks.md).
