# Rolling Update — поэтапное обновление

## Определения

**Rolling Update (Поэтапное обновление)** — стратегия развертывания (**Deployment**), при которой экземпляры приложения (**Pods**, виртуальные машины, контейнеры) обновляются поочередно или небольшими группами. Новая версия постепенно заменяет старую, обеспечивая непрерывную доступность сервиса.

- **Нулевое время простоя (Zero Downtime)** — ключевая цель стратегии, достигаемая за счет того, что часть экземпляров всегда остается в рабочем состоянии и готова принимать трафик через балансировщик.
- **Радиус поражения (Blast Radius)** — при Rolling Update радиус поражения ограничен количеством одновременно обновляемых подов (контролируется `maxUnavailable`).
- **Ревизия (Revision)** — сохраненное состояние манифеста, позволяющее выполнить откат.

## Основные концепции

### Механизм работы в Kubernetes

На уровне Kubernetes Rolling Update управляется контроллером Deployment, который манипулирует объектами **ReplicaSet**:
1.  **Создание нового RS:** При изменении шаблона пода (`spec.template`) создается новый ReplicaSet (v2).
2.  **Поэтапное масштабирование:** Контроллер увеличивает количество реплик в RS v2 и одновременно уменьшает в RS v1, соблюдая ограничения `maxSurge` и `maxUnavailable`.
3.  **Проверка готовности:** Удаление пода из старого RS происходит только после того, как новый под из RS v2 успешно прошел **Readiness Probe**.

### Параметры управления в Kubernetes

| Параметр | Описание | Рекомендация (2026) |
| :--- | :--- | :--- |
| **`maxUnavailable`** | Макс. кол-во подов, недоступных при обновлении. | `0` для критических систем (сначала создать, потом удалить). |
| **`maxSurge`** | Макс. кол-во подов сверх `replicas`. | `25%` или `1-2` для средних нагрузок. |
| **`minReadySeconds`** | Время ожидания после `Ready`, перед тем как под считается рабочим. | `10-30s` для прогрева кэшей и JIT-компиляции. |
| **`progressDeadlineSeconds`** | Время ожидания прогресса до признания обновления зависшим. | `600` (10 минут) — стандарт для детекции сбоев. |
| **`revisionHistoryLimit`** | Кол-во старых ReplicaSet для отката. | `10` — оптимально для глубины истории. |

### Золотые сигналы (Golden Signals) при обновлении

При мониторинге Rolling Update критически важно отслеживать:
- **Errors (Ошибки):** Всплеск 5xx ошибок в момент ротации подов сигнализирует о проблемах в новой версии или некорректном Graceful Shutdown.
- **Latency (Задержки):** Рост времени ответа на новых подах может указывать на отсутствие прогрева кэшей.
- **Traffic (Трафик):** Неравномерное распределение нагрузки между v1 и v2 при использовании Sticky Sessions.

### Rolling Update vs In-Place Resize (Контекст 2026)

В 2026 году для ресурсоемких приложений (Java, ML) часто используется **In-Place Pod Vertical Scaling**.
- **Rolling Update:** Всегда пересоздает под (новый IP, пустые кэши).
- **In-Place Resize:** Обновляет ресурсы (CPU/RAM) работающего контейнера без перезапуска.
**Вывод:** Rolling Update остается единственным способом обновления *кода* или *конфигурации*, в то время как In-Place Resize предпочтителен для изменения лимитов ресурсов.

## Практические сценарии

### Продвинутый Kubernetes Deployment

Пример с использованием контрольных сумм конфигурации (автоматический триггер обновления) и тонкой настройкой ресурсов.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-api
spec:
  replicas: 5
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0 # Гарантируем отсутствие потери мощности
  template:
    metadata:
      annotations:
        # Автоматический перезапуск при изменении ConfigMap (стандарт Helm/Kustomize)
        checksum/config: ${CONFIG_CHECKSUM}
    spec:
      terminationGracePeriodSeconds: 60 # Время на завершение транзакций
      containers:
      - name: app
        image: my-repo/app:v2.1.0
        ports:
        - containerPort: 8080
        readinessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 15
          periodSeconds: 5
        resources:
          requests:
            cpu: "500m"
            memory: "1Gi"
```

### Rolling Update в StatefulSet (Partitioning)

В отличие от Deployment, StatefulSet обновляет поды в обратном порядке индексов (от N-1 до 0). Параметр `partition` позволяет реализовать Canary-стиль внутри Rolling Update.

```yaml
spec:
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      partition: 3 # Обновятся только поды с индексом >= 3
```

### Docker Swarm: Надежная раскатка

Настройка автоматического отката при сбое и контроля здоровья.

```yaml
services:
  worker:
    image: worker:latest
    deploy:
      replicas: 8
      update_config:
        parallelism: 2
        delay: 20s
        order: start-first     # Сначала поднять новый, потом гасить старый
        failure_action: rollback # АВТО-ОТКАТ при сбое healthcheck
        monitor: 30s           # Сколько следить за здоровьем после старта
        max_failure_ratio: 0.2 # Допустимый процент сбоев
```

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Rollout застрял (Stuck)** | Новые поды в `CrashLoopBackOff` или `Pending`. | Проверить `kubectl describe pod` и лимиты ресурсов. |
| **Ошибки 502/504 при деплое** | Короткий `terminationGracePeriod` или отсутствие обработки `SIGTERM`. | Увеличить время завершения и настроить перехват сигналов в приложении. |
| **Трафик на неготовую версию** | Отсутствие или неверная `readinessProbe`. | Настроить пробу, реально проверяющую готовность бизнес-логики. |
| **ImagePullBackOff** | Ошибка авторизации в Registry или опечатка в теге. | Проверить `imagePullSecrets` и существование образа. |
| **Нехватка ресурсов (Surge)** | `maxSurge` требует больше CPU/RAM, чем есть на нодах. | Уменьшить `maxSurge` или использовать `maxUnavailable: 25%`. |

## Дополнительная информация

### Лучшие практики

1. **Иммутабельность:** Никогда не используйте тег `:latest`. Обновление должно инициироваться сменой конкретной версии образа или хеша конфигурации.
2. **Expand and Contract:** При обновлении работают две версии приложения. База данных должна поддерживать обе схемы одновременно. Подробнее: **[Expand-Contract](../../Databases/Concepts/migrations/expand_contract.md)**.
3. **PDB (Pod Disruption Budget):** Не ограничивает Rolling Update напрямую, но важен для стабильности при одновременных работах на узлах. Подробнее: **[Pod Disruption Budget](../../Kubernetes/Autoscaling/pod_disruption_budget.md)**.

### Рекомендованные ссылки

- **[Сравнение стратегий развертывания](./comparison.md)** — выбор между Rolling Update, Blue-Green и Canary.
- **[Проверки здоровья и откат](./deployment_health_checks_and_rollback.md)** — автоматизация восстановления.
- **[Управление жизненным циклом Deployment](../../Kubernetes/Base/Deployment/lifecycle_management.md)** — глубокие детали ReplicaSet.
- **[Стратегии и модели развертывания](../Core_Concepts/deployment_strategies.md)** — архитектурный обзор.
