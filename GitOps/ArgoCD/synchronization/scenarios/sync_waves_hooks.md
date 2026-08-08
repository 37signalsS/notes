# Argo CD — волны синхронизации (Sync Waves) и хуки (Hooks)

> **Актуальность (2026):** В версии Argo CD v3.x механизмы волн и хуков были дополнены поддержкой фаз удаления (**PreDelete**, **PostDelete**), что позволяет безопасно очищать внешние ресурсы (БД, DNS, облачные балансировщики). Использование волн в сочетании с кастомными Health Checks на Lua стало стандартом для управления жизненным циклом сложных инфраструктурных стеков.

## Определения

**Волны синхронизации (Sync Waves)** — механизм Argo CD для управления строгим порядком применения и обновления ресурсов. Позволяет группировать объекты в последовательные этапы, где переход к следующему этапу возможен только после достижения статуса `Healthy` всеми ресурсами текущего.

**Хуки (Hooks)** — специальные аннотации, позволяющие запускать эфемерные задачи (обычно Kubernetes Jobs) на ключевых этапах жизненного цикла синхронизации или удаления приложения.

**Health Gating (Барьер здоровья)** — принцип работы волн синхронизации, при котором контроллер блокирует выполнение следующей волны до тех пор, пока текущая не будет признана полностью работоспособной.

**Hook Delete Policies** — настройки, определяющие условия автоматической очистки ресурсов хука (например, после успешного завершения или перед началом новой синхронизации).

## Базовые концепции

### Механика волн синхронизации

Управление осуществляется через аннотацию `argocd.argoproj.io/sync-wave`.

- **Порядок выполнения:** Ресурсы с наименьшим числовым значением (например, `-10`) применяются первыми.
- **Диапазон:** Поддерживаются любые целые числа.
- **Значение по умолчанию:** `0`.
- **Sparse Numbering (Разреженная нумерация):** Рекомендуется использовать шаг (например, `-10`, `0`, `10`), чтобы иметь возможность вставить промежуточные ресурсы без изменения всего набора манифестов.

### Жизненный цикл хуков

Хуки настраиваются через аннотацию `argocd.argoproj.io/hook`. 

| Фаза | Описание | Применение |
| :--- | :--- | :--- |
| **PreSync** | Перед применением основных ресурсов. | Миграции БД, проверка зависимостей. |
| **Sync** | В процессе применения ресурсов. | Редкие случаи специфичной оркестрации. |
| **Skip** | Пропуск ресурса. | Исключение метаданных из GitOps-цикла. |
| **PostSync** | После того как все ресурсы стали `Healthy`. | Smoke-тесты, очистка кеша CDN. |
| **SyncFail** | Только при ошибке синхронизации. | Оповещения в Slack, сбор логов сбоя. |
| **PreDelete** | (v3.3+) Перед удалением ресурсов. | Снапшоты БД, отзыв сертификатов. |
| **PostDelete** | (v3.3+) После завершения удаления. | Удаление записей в DNS, очистка S3. |

## Практические сценарии

### Сценарий 1: Инфраструктурная пирамида (Sync Waves)

Обеспечение готовности базы до запуска приложения.

```yaml
# 1. Приоритетный ресурс (Namespace) - Волна -10
apiVersion: v1
kind: Namespace
metadata:
  name: my-stack
  annotations:
    argocd.argoproj.io/sync-wave: "-10"

# 2. Инфраструктура (ConfigMaps, Secrets, Operator CRs) - Волна -5
apiVersion: v1
kind: ConfigMap
metadata:
  name: db-config
  namespace: my-stack
  annotations:
    argocd.argoproj.io/sync-wave: "-5"

# 3. Приложение (Deployment, Service) - Волна 0 (Default)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-server
  namespace: my-stack
```

### Сценарий 2: Миграция базы данных с безопасной очисткой

Использование политики `BeforeHookCreation` гарантирует отсутствие конфликтов имен Job при перезапусках.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation, HookSucceeded
spec:
  template:
    spec:
      containers:
      - name: migrate
        image: migrations-tool:v2.4
        envFrom: [{configMapRef: {name: db-config}}]
      restartPolicy: Never
```

### Сценарий 3: Кастомный Health Check для операторов (Lua)

По умолчанию Argo CD считает CRD здоровым сразу после создания. Для работы волн с операторами (например, Postgres Operator) добавьте скрипт в `argocd-cm`.

```yaml
data:
  resource.customizations.health.acid.zalan.do_Postgresql: |
    hs = {}
    if obj.status ~= nil then
      if obj.status.PostgresClusterStatus == "Running" then
        hs.status = "Healthy"
        hs.message = "Cluster is running"
        return hs
      end
    end
    hs.status = "Progressing"
    hs.message = "Waiting for cluster"
    return hs
```

## Технический справочник

### Политики удаления хуков (`hook-delete-policy`)

- **HookSucceeded:** Удалить, если Job завершился успешно.
- **HookFailed:** Удалить, если Job завершился с ошибкой (редко используется в целях отладки).
- **BeforeHookCreation:** (Рекомендуется) Удалить старый ресурс перед созданием нового.

### Тюнинг таймаутов

Если хук (например, долгая миграция) превышает время ожидания, синхронизация прерывается. Настройте таймауты в `argocd-cm`:
```yaml
data:
  controller.repo.server.timeout.seconds: "120"
```

## Дополнительная информация

### См. также
- **[Синхронизация Argo CD: Обзор](../../synchronization.md)** — механизмы и фазы.
- **[Автоматическая синхронизация](./auto_sync.md)** — использование волн в авто-деплое.
- **[Диагностика Argo CD](../argocd_troubleshooting_and_monitoring.md)** — поиск причин зависания хуков.

### Ссылки
- [Argo CD Documentation: Resource Hooks](https://argo-cd.readthedocs.io/en/stable/user-guide/resource_hooks/)
- [Sync Waves Official Guide](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-waves/)
