# Управление жизненным циклом Deployment

## Определения

**Lifecycle Management** — управление жизненным циклом Deployment, включающее процессы создания, обновления конфигурации, отката к стабильным версиям, а также оперативное управление (пауза, перезапуск).

Общие концепции и стратегии обновления описаны в основном разделе: **[Kubernetes Deployment](./index.md)**.

## Базовые концепции

### Иерархия объектов

`Deployment` → [`ReplicaSet`](../replicaset.md) → [`Pod`](../Pod/pod_overview.md)

Deployment не управляет подами напрямую. Он управляет наборами реплик (`ReplicaSet`), которые, в свою очередь, обеспечивают работу нужного количества подов. При обновлении Deployment создаёт новый `ReplicaSet` и постепенно переносит нагрузку на него.

### Триггеры обновления

Обновление (rollout) запускается автоматически только при изменении шаблона пода (`spec.template`).

- **Что инициирует обновление:**
  - Изменение образа контейнера (`image`).
  - Обновление переменных окружения (`env`).
  - Изменение конфигурации томов (`volumes`).
  - Редактирование лимитов или запросов ресурсов (`resources`).
- **Что НЕ инициирует обновление:**
  - Масштабирование (`spec.replicas`) — изменяется только количество подов в текущем `ReplicaSet`.
  - Изменение метаданных самого Deployment (лейблы или аннотации вне `spec.template`).

## Практические сценарии

### Создание и проверка статуса

```bash
# Применение манифеста
kubectl apply -f nginx-deployment.yaml
# → deployment.apps/nginx-deployment created

# Обновление образа (инициирует rollout)
kubectl set image deployment/nginx-deployment nginx=nginx:1.29.0
# → deployment.apps/nginx-deployment image updated

# Просмотр статуса развертывания
kubectl rollout status deployment/nginx-deployment
# → Waiting for deployment "nginx-deployment" rollout to finish: 0 of 3 updated replicas are available...
# → deployment "nginx-deployment" successfully rolled out
```

### Диагностика при сбоях обновления

Если обновление зависло (например, из-за ошибки `ImagePullBackOff` или неудачных проб), Kubernetes не выполняет откат автоматически. Старые поды продолжают работать, пока новые не станут `Ready`.

**Алгоритм диагностики:**

1. Проверить события Deployment: `kubectl describe deployment <name>`
2. Проверить состояние подов: `kubectl get pods -l app=<label>`
3. Проверить ошибки конкретного пода: `kubectl describe pod <pod-name>`

### Управление историей ревизий

Каждое обновление шаблона создает новую ревизию. Количество хранимых ревизий определяется параметром `revisionHistoryLimit` (по умолчанию 10).

```bash
# Просмотр списка ревизий
kubectl rollout history deployment/nginx-deployment
# → deployment.apps/nginx-deployment 
# → REVISION  CHANGE-CAUSE
# → 1         <none>
# → 2         Обновление образа до v1.29.0

# Просмотр деталей конкретной ревизии
kubectl rollout history deployment/nginx-deployment --revision=2
# → deployment.apps/nginx-deployment with revision #2
# → Pod Template: ...

# Откат к предыдущей стабильной версии (активирует предыдущий ReplicaSet)
kubectl rollout undo deployment/nginx-deployment
# → deployment.apps/nginx-deployment rolled back

# Откат к конкретной ревизии из истории
kubectl rollout undo deployment/nginx-deployment --to-revision=1
# → deployment.apps/nginx-deployment rolled back
```

### Документирование изменений (change-cause)

Для понимания причин изменений в истории ревизий используется аннотация `kubernetes.io/change-cause`.

**Способы установки:**

- Через аннотацию в манифесте (рекомендуется):

  ```yaml
  metadata:
    annotations:
      kubernetes.io/change-cause: "Обновление образа до v1.29.0"
  ```

- Через CLI после обновления:

  ```bash
  kubectl annotate deployment/nginx-deployment kubernetes.io/change-cause="Исправление переменных окружения"
  # → deployment.apps/nginx-deployment annotated
  ```

### Оперативное управление

- **Пауза и возобновление:** позволяет внести серию изменений в конфигурацию, не запуская обновление после каждой правки.

  ```bash
  kubectl rollout pause deployment/nginx-deployment
  # → deployment.apps/nginx-deployment paused
  
  # ... внесение правок (set image, set resources) ...
  
  kubectl rollout resume deployment/nginx-deployment
  # → deployment.apps/nginx-deployment resumed
  ```

- **Принудительный перезапуск:** используется для пересоздания подов без изменения манифеста (например, для подтягивания обновленных данных из `Secret` или `ConfigMap`).

  ```bash
  kubectl rollout restart deployment/nginx-deployment
  # → deployment.apps/nginx-deployment restarted
  ```

### Экспорт и очистка манифеста

Для получения чистого манифеста текущего состояния без системных полей:

```bash
kubectl get deployment nginx-deployment -o yaml > deployment.yaml
```

**Важно:** Перед повторным использованием удалите из файла блоки `status`, а также поля `uid`, `resourceVersion` и `creationTimestamp` в `metadata`.

## Дополнительная информация

### Анализ ReplicaSet

Команда `kubectl get rs` позволяет увидеть, как Deployment распределяет нагрузку между версиями:

| Поле | Описание |
| :--- | :--- |
| **DESIRED** | Целевое количество подов для данной ревизии |
| **CURRENT** | Фактическое количество созданных подов |
| **READY** | Количество подов, готовых принимать трафик |

Имя `ReplicaSet` содержит уникальный хэш шаблона пода. Если хэш совпадает с одной из старых ревизий, Deployment масштабирует существующий `ReplicaSet` вместо создания нового.

### См. также

- [Kubernetes Deployment](./index.md)
- [Манифест и лучшие практики](./deployment_manifest.md)
- [Deployment Health Checks and Rollback](../../../CI-CD/Deployment_Strategies/deployment_health_checks_and_rollback.md)
