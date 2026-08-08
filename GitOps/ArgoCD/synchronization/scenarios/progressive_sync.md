# Argo CD — прогрессивная синхронизация (Rolling Sync)

> **Актуальность (2026):** В версии Argo CD v3.x прогрессивная синхронизация стала неотъемлемой частью контроллера **ApplicationSet**. Она позволяет управлять развертыванием приложений в масштабах сотен кластеров, обеспечивая безопасность через поэтапную раскатку и автоматическую блокировку при обнаружении деградации здоровья ресурсов.

## Определения

**Прогрессивная синхронизация (Progressive Sync)** — стратегия развертывания в рамках `ApplicationSet`, при которой обновления применяются к группам приложений последовательно, а не одновременно. 

**Rolling Sync** — конкретный алгоритм прогрессивной синхронизации, имитирующий поведение `RollingUpdate` в Kubernetes, но на уровне пар "Приложение-Кластер".

**Health Gating (Барьер здоровья)** — механизм контроля, который разрешает переход к следующему этапу (шагу) синхронизации только в том случае, если все приложения текущего этапа достигли статуса `Healthy`.

**Blast Radius (Радиус поражения)** — концепция ограничения масштаба потенциального сбоя. Прогрессивная синхронизация минимизирует этот радиус, обновляя сначала малую группу кластеров (Canary).

## Базовые концепции

### Механика работы Rolling Sync

При активации стратегии `RollingSync` в `ApplicationSet`, процесс синхронизации меняется фундаментально:

1.  **Оркестрация вместо автоматики:** Стандартный флаг `syncPolicy.automated` внутри шаблона приложения игнорируется. Решение о запуске синхронизации принимает контроллер `ApplicationSet`.
2.  **Группировка по шагам (Steps):** Весь набор генерируемых приложений разбивается на логические группы с помощью селекторов `matchExpressions`.
3.  **Контроль параллелизма (maxUpdate):** Параметр определяет, сколько приложений *внутри одного шага* могут находиться в процессе обновления одновременно. Может быть числом (например, `1`) или процентом (`10%`).
4.  **Остановка при сбое:** Если приложение переходит в статус `Degraded`, контроллер останавливает прогресс. Дальнейшие шаги не выполняются, пока проблема не будет устранена (или пока приложение не будет исключено из набора).

### Включение и настройка

В Argo CD v3.x функционал включен по умолчанию. Однако для тонкой настройки контроллера используются параметры в `argocd-cmd-params-cm`:

```yaml
data:
  # Интервал проверки здоровья приложений для прогрессивной синхронизации
  applicationsetcontroller.progressive.sync.requeue.interval.seconds: "30"
```

## Практические сценарии

### Сценарий 1: Глобальный Canary-пайплайн

Развертывание сначала в один контрольный кластер, затем в Staging, и только потом поэтапно в Production.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: global-app-rollout
spec:
  generators:
  - clusters: {} # Использовать все подключенные кластеры
  strategy:
    type: RollingSync
    rollingSync:
      steps:
        # Шаг 1: Один кластер для проверки (Canary)
        - matchExpressions:
            - key: environment
              operator: In
              values: [canary]
          maxUpdate: 1
        
        # Шаг 2: Все тестовые окружения (параллельно)
        - matchExpressions:
            - key: environment
              operator: In
              values: [staging]
          # maxUpdate не указан = 100%
          
        # Шаг 3: Весь Production (по 10% за раз)
        - matchExpressions:
            - key: environment
              operator: In
              values: [production]
          maxUpdate: 10%
  template:
    metadata:
      name: '{{name}}-service'
    spec:
      project: default
      source:
        repoURL: https://github.com/my-org/manifests.git
        targetRevision: HEAD
        path: app
      destination:
        server: '{{server}}'
        namespace: production
```

### Сценарий 2: Мультирегиональная раскатка

Последовательное обновление датацентров в разных регионах для минимизации рисков глобального простоя.

```yaml
rollingSync:
  steps:
    - matchExpressions:
        - key: region
          operator: In
          values: [eu-central-1, eu-west-1]
      maxUpdate: 1
    - matchExpressions:
        - key: region
          operator: In
          values: [us-east-1, us-west-2]
      maxUpdate: 1
```

### Сценарий 3: Использование Lua для кастомного здоровья

Если стандартных Health Checks Kubernetes недостаточно (например, для проверки прогрева кэша или состояния БД), используйте кастомные проверки в `argocd-cm`.

```yaml
data:
  resource.customizations.health.argoproj.io_Application: |
    hs = {}
    if obj.status ~= nil then
      if obj.status.health ~= nil then
        hs.status = obj.status.health.status
        hs.message = obj.status.health.message
      end
    end
    return hs
```

## Технический справочник

### Параметры RollingSync

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `matchExpressions` | List | Стандартные селекторы Kubernetes для фильтрации приложений. |
| `maxUpdate` | Int/String | Лимит одновременно обновляемых приложений (число или %). |
| `andOperator` | Boolean | (v3.2+) Если `true`, требует совпадения всех условий в шаге. |

## Дополнительная информация

### Важные нюансы
- **Зависимость от метаданных:** Прогрессивная синхронизация критически зависит от правильной разметки (labels) кластеров в Argo CD.
- **Прерывание:** Если вы вручную нажмете "Sync" на приложении, которое еще не подошло по очереди, оно будет синхронизировано, но это может нарушить логику `maxUpdate` текущего шага.

### См. также
- **[Синхронизация Argo CD: Обзор](../../synchronization.md)** — общие принципы.
- **[Автоматическая синхронизация](./auto_sync.md)** — стандартный режим деплоя.
- **[Волны и хуки](./sync_waves_hooks.md)** — управление порядком ресурсов внутри одного кластера.
- [Argo CD ApplicationSet: Rolling Sync Docs](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Progressive-Syncs/)
