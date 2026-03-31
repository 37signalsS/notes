# Kubernetes Deployment: Концепции

## 1. Определения

**Deployment** — объект Kubernetes для декларативного управления жизненным циклом подов. Основная задача — поддержание заданного количества работающих экземпляров приложения (`replicas`) и обеспечение предсказуемого, контролируемого обновления.

**Схема управления:** `Deployment` → [`ReplicaSet`](../replicaset.md) → [`Pod`](../Pod/pod_overview.md)

При создании или обновлении `Deployment` создает новый `ReplicaSet`, который запускает поды согласно шаблону (`template`). Старый `ReplicaSet` сохраняется для возможности отката.

## 2. Базовые концепции

### 2.1. Анатомия манифеста

**`replicas`** — желаемое количество реплик (подов), которое `Deployment` должен поддерживать.

**`selector`** — определяет, как `Deployment` находит управляемые поды.

> **Важно:** Метки в `spec.selector.matchLabels` должны точно совпадать с метками в `spec.template.metadata.labels`.

**`template`** — шаблон для создания подов. Содержит `metadata` и `spec` с описанием контейнеров.

**`strategy`** — стратегия обновления подов:

| Стратегия | Описание | Когда использовать |
| :--- | :--- | :--- |
| **`RollingUpdate`** (по умолчанию) | Постепенное обновление под за подом без простоя | Веб-сервисы, stateless-приложения |
| **`Recreate`** | Остановка всех старых подов → запуск новых | Несовместимые версии, миграции БД, монолиты |

Детальное описание стратегий — в [Rolling Update](../../../CI-CD/Deployment_Strategies/rolling_update.md) и [Deployment Strategies](../../../CI-CD/Core_Concepts/deployment_strategies.md).

**`revisionHistoryLimit`** — количество старых `ReplicaSet` для истории и отката. Предотвращает «захламление» кластера. **По умолчанию: 10**.

**`progressDeadlineSeconds`** — таймаут развертывания. Если новый `ReplicaSet` не станет доступным за это время (например, из-за `CrashLoopBackOff` или ошибок `readinessProbe`), `Deployment` перейдет в состояние `Progressing=False` с причиной `ProgressDeadlineExceeded`.

> **Совет:** Используйте YAML-anchors (`&` и `*`) для повторяющихся меток в манифесте, чтобы избежать дублирования.

### 2.2. Owner References

Каждый ресурс содержит поле `ownerReferences` в `metadata`, определяющее связь «родитель-потомок»:

- `Pod` → принадлежит `ReplicaSet`
- `ReplicaSet` → принадлежит `Deployment`

Это используется для каскадного удаления: при удалении `Deployment` автоматически удаляются связанные `ReplicaSet` и `Pod`.

## 3. Практические сценарии

### 3.1. Rolling Update (по умолчанию)

Стратегия по умолчанию для `Deployment`. Детальное описание — в [Rolling Update](../../../CI-CD/Deployment_Strategies/rolling_update.md).

**Параметры управления:**

- **`maxUnavailable`** — допустимое количество недоступных подов во время обновления.
- **`maxSurge`** — максимальное количество подов сверх желаемого числа `replicas`.

**Сценарий:** `replicas: 3`, `maxSurge: 1`, `maxUnavailable: 1`, обновление с `nginx:1.28.0` на `nginx:1.29.0`:

1. Создание 1 нового пода (v2) → 4 пода.
2. Ожидание `readinessProbe`.
3. Удаление 1 старого пода (v1) → 3 пода.
4. Повторение до полного обновления.

> **Примечание:** Для плавного обновления рекомендуется минимум 2 реплики — при `maxUnavailable: 1` всегда останется доступен хотя бы один под.

### 3.2. Recreate

Сначала останавливаются **все** старые поды, потом запускаются новые.

**Приводит к простою (downtime)!**

Используется когда:

- Приложение не поддерживает работу двух версий параллельно.
- Потребление ресурсов не позволяет запускать новый под до остановки старого.

### 3.3. Сравнение стратегий

| Стратегия | Плюсы | Минусы | Когда выбирают |
| :--- | :--- | :--- | :--- |
| **`RollingUpdate`** | Минимальный или нулевой простой. | Требует совместимости версий. | Веб-сервисы, stateless-приложения, где важна непрерывность. |
| **`Recreate`** | Полностью атомарное обновление. | Приводит к простою приложения. | Несовместимые версии, миграции схем БД, монолиты. |

Полное сравнение стратегий развертывания — в [Comparison of Deployment Strategies](../../../CI-CD/Deployment_Strategies/comparison.md).

## 4. Дополнительная информация

### 4.1. Связанные темы

- Управление жизненным циклом: [lifecycle_management.md](./lifecycle_management.md)
- Пример манифеста и лучшие практики: [deployment_manifest.md](./deployment_manifest.md)
- Внешняя конфигурация: [`ConfigMap`](../configmap.md), [`Secret`](../secrets/secrets_basics.md)
- Stateful-приложения: [`StatefulSet`](../statefulset.md)
- Отказоустойчивость: [`Высокая доступность`](../high_availability.md)
- Автомасштабирование: [`Horizontal Pod Autoscaler`](../../Autoscaling/overview_concepts.md)

### 4.2. Расширенные стратегии развертывания

Для production-развертываний с повышенными требованиями к надежности рассмотрите:

- [Blue-Green Deployment](../../../CI-CD/Deployment_Strategies/blue_green_deployment.md)
- [Canary Deployment](../../../CI-CD/Deployment_Strategies/canary_deployment.md)
- [Deployment Health Checks and Rollback](../../../CI-CD/Deployment_Strategies/deployment_health_checks_and_rollback.md)
