# Управление жизненным циклом Deployment

## 1. Определения

**Lifecycle Management** — управление жизненным циклом Deployment: создание, обновление, откат, пауза/возобновление и перезапуск.

Kubernetes использует механизм `Rolling Update` для плавного обновления подов без простоя приложения.

## 2. Базовые концепции

### 2.1. Иерархия объектов

`Deployment` → [`ReplicaSet`](../replicaset.md) → [`Pod`](../Pod/pod_overview.md)

При создании `Deployment` автоматически создает `ReplicaSet`, который управляет подами.

### 2.2. Что триггерит обновление

**Триггерят обновление** (создание нового ReplicaSet):

- Изменение образа контейнера в `spec.template.spec.containers[].image`
- Изменение переменных окружения в `spec.template`
- Изменение монтированных томов в `spec.template`
- Любые изменения в `spec.template` (шаблон пода)

**НЕ триггерят обновление** (поды не пересоздаются):

- Масштабирование (`spec.replicas`) — только добавляется или уменьшается количество подов
- Изменение метаданных Deployment (лейблы, аннотации самого Deployment)

### 2.3. Механизм обновления

При обновлении образа или конфигурации:

1. `Deployment` создает новый `ReplicaSet` с обновленным шаблоном.
2. Количество реплик нового `ReplicaSet` постепенно увеличивается.
3. Количество реплик старого `ReplicaSet` уменьшается.
4. Старый `ReplicaSet` сохраняется для возможности отката.

## 3. Практические сценарии

### 3.1. Создание и проверка

```bash
# Создать Deployment
kubectl apply -f nginx-deployment.yaml
# deployment.apps/nginx-deployment created

# Проверить иерархию объектов
kubectl get all -l app=nginx
# NAME                                    READY   STATUS    RESTARTS   AGE
# pod/nginx-deployment-5d59d67564-7wqgt   1/1     Running   0          15s
# pod/nginx-deployment-5d59d67564-8b9pw   1/1     Running   0          15s
# pod/nginx-deployment-5d59d67564-m2xvb   1/1     Running   0          15s
#
# NAME                               DESIRED   CURRENT   UP-TO-DATE   AVAILABLE   AGE
# deployment.apps/nginx-deployment   3         3         3            3           15s
#
# NAME                                          DESIRED   CURRENT   READY   AGE
# replicaset.apps/nginx-deployment-5d59d67564   3         3         3       15s
```

### 3.2. Обновление (Rolling Update)

```bash
# Обновить образ контейнера
kubectl set image deployment/nginx-deployment nginx=nginx:1.29.0 --record
# deployment.apps/nginx-deployment image updated

# Отследить статус в реальном времени
kubectl rollout status deployment/nginx-deployment
# Waiting for deployment "nginx-deployment" rollout to finish: 2 out of 3 new replicas have been updated...
# deployment "nginx-deployment" successfully rolled out

# Проверить историю ReplicaSet
kubectl get replicaset
# NAME                                     DESIRED   CURRENT   READY   AGE
# nginx-deployment-5d59d67564              0         0         0       5m
# nginx-deployment-new-version-86f596b6c   3         3         3       3m
```

### 3.3. Откат при неудачном обновлении

При обновлении на несуществующую версию (`nginx:1.11.1`):

```bash
kubectl set image deployment/nginx-deployment nginx=nginx:1.11.1
# deployment.apps/nginx-deployment image updated

# Проверить статус подов
kubectl get pods -l app=nginx
# NAME                                     READY   STATUS             RESTARTS   AGE
# nginx-deployment-new-version-86f596b6c-abcde   1/1     Running            0          8m
# nginx-deployment-new-version-86f596b6c-fghij   1/1     Running            0          8m
# nginx-deployment-failed-update-12345678-klmno   0/1     ImagePullBackOff   0          1m
```

**Важно:** Kubernetes НЕ выполняет автоматический откат при неудачном обновлении. Старые поды продолжают работать, трафик на них поступает. Откат нужно выполнить вручную.

При сбое обновления Kubernetes останавливает масштабирование новых подов. Поведение зависит от параметров стратегии (`maxUnavailable`, `maxSurge`). Если новый под не проходит `readinessProbe` или не может запуститься (`ImagePullBackOff`, `CrashLoopBackOff`), Deployment переходит в состояние `Progressing=False` с причиной `ProgressDeadlineExceeded` (по истечении `progressDeadlineSeconds`, по умолчанию 600 секунд).

**Диагностика:**

```bash
kubectl describe pod nginx-deployment-failed-update-12345678-klmno

# Events:
#   Type     Reason     Age                From               Message
#   ----     ------     ----               ----               -------
#   Warning  Failed     23s (x4 over 89s)  kubelet, node-1    Failed to pull image "nginx:1.11.1": manifest not found
#   Warning  Failed     23s (x4 over 89s)  kubelet, node-1    Error: ErrImagePull
#   Normal   BackOff    10s (x6 over 88s)  kubelet, node-1    Back-off pulling image "nginx:1.11.1"
```

Также полезна команда `kubectl describe deployment/<name>` — раздел Events показывает последовательность действий: масштабирование старых и новых ReplicaSet, ошибки, таймауты.

Просмотр статуса обновления:

```bash
kubectl rollout status deployment/nginx-deployment
# Ожидание завершения обновления...
# Вечное ожидание при невалидном образе — требуется ручной откат
```

**Откат к предыдущей версии:**

```bash
kubectl rollout undo deployment/nginx-deployment
# deployment.apps/nginx-deployment rolled back
```

> **Примечание:** При откате **не создаётся новый** `ReplicaSet` — Kubernetes масштабирует **старый** `ReplicaSet` с предыдущей рабочей версией. Старый ReplicaSet сохраняется и продолжает работать. Если удалить старый ReplicaSet вручную, возможность отката к этой версии теряется.

> **Инкремент ревизий:** Каждая операция отката создаёт новую запись в истории ревизий с увеличенным номером. Если у вас были ревизии 1 и 2, после отката с ревизии 2 на 1 появится ревизия 3 (содержимое идентично ревизии 1).

### 3.4. История ревизий и откат к конкретной версии

**Что создаёт новую ревизию:**

- Изменение образа контейнера (`spec.template.spec.containers[].image`)
- Изменение переменных окружения в `spec.template`
- Изменение монтированных томов в `spec.template`
- Любые изменения в `spec.template` (шаблон пода)

**НЕ создаёт новую ревизию:**

- Масштабирование (`spec.replicas`) — изменение количества реплик не записывается в историю
- Изменение метаданных самого Deployment (лейблы, аннотации вне шаблона)

```bash
# Посмотреть историю изменений
kubectl rollout history deployment/nginx-deployment
# REVISION  CHANGE-CAUSE
# 1         kubectl apply --filename=nginx-deployment.yaml
# 2         kubectl set image deployment/nginx-deployment nginx=nginx:1.29.0 --record
# 3         kubectl set image deployment/nginx-deployment nginx=nginx:1.999.9

# Детальный просмотр конкретной ревизии
kubectl rollout history deployment/nginx-deployment --revision=2
# Pod Template:
#   Labels:       app=nginx
#                 pod-template-hash=5d59d67564
#   Annotations:  kubernetes.io/change-cause: kubectl set image deployment/nginx-deployment nginx=nginx:1.29.0 --record
#   Containers:
#    nginx:
#     Image:      nginx:1.29.0
#     Port:       80/TCP
#     Environment: <none>
#     Mounts:      <none>

# Откат к конкретной ревизии
kubectl rollout undo deployment/nginx-deployment --to-revision=1
```

**Откат к нерабочей версии:** По умолчанию `rollout undo` откатывает к предыдущей рабочей версии. Если требуется откатиться к конкретной (возможно нерабочей) ревизии, используйте флаг `--to-revision`:

```bash
# Откат к нерабочей ревизии 2 (с невалидным образом)
kubectl rollout undo deployment/nginx-deployment --to-revision=2
# deployment.apps/nginx-deployment rolled back

# Результат: поды с невалидным образом начнут создаваться,
# Deployment зависнет в состоянии обновления — требуется диагностика
```

Это полезно для тестирования: можно намеренно откатиться к проблемной версии для воспроизведения и отладки issues.

**Аннотация `change-cause`:** Для документирования изменений используется аннотация `kubernetes.io/change-cause`. Она отображается в колонке `CHANGE-CAUSE` вывода `rollout history`.

Способы установки:

```bash
# 1. Флаг --record при выполнении команды (устаревший, но работающий)
kubectl set image deployment/nginx-deployment nginx=nginx:1.29.0 --record

# 2. Явная аннотация объекта
kubectl annotate deployment/nginx-deployment kubernetes.io/change-cause="Обновление до nginx 1.29.0"

# 3. Через манифест (рекомендуемый способ)
# metadata:
#   annotations:
#     kubernetes.io/change-cause: "Обновление до nginx 1.29.0"
```

> **Примечание:** Флаг `--record` считается deprecated в новых версиях Kubernetes. Рекомендуется использовать `kubectl annotate` или указывать аннотацию в манифесте.

### 3.5. Пауза и возобновление развертывания

```bash
# Приостановить развертывание
kubectl rollout pause deployment/my-webapp

# Внести несколько изменений в манифест
kubectl edit deployment/my-webapp
# ... изменения ...

# Возобновить развертывание
kubectl rollout resume deployment/my-webapp
```

Полезно для применения нескольких изменений одним батчем без запуска обновления после каждого изменения.

### 3.6. Принудительный перезапуск

```bash
# Перезапустить все поды в Deployment
kubectl rollout restart deployment/my-webapp
```

Инициирует стандартный `Rolling Update` без изменения манифеста. Используется для применения изменений из [`ConfigMap`](../configmap.md) или [`Secret`](../secrets/secrets_basics.md).

Команда также работает для [`DaemonSet`](../daemonset.md) и [`StatefulSet`](../statefulset.md).

### 3.7. Экспорт манифеста из кластера

Для получения актуального манифеста Deployment из кластера:

```bash
# Вывести Deployment в YAML-файл
kubectl get deployment <deployment-name> -o yaml > deployment.yaml
```

**Важно:** Перед повторным применением нужно удалить служебные поля:

- `status` — текущее состояние (генерируется контроллером)
- `metadata.uid`, `metadata.resourceVersion`, `metadata.creationTimestamp` — системные метаданные
- `metadata.annotations` — аннотации контроллера (кроме тех, что заданы вручную)

После очистки файл можно использовать для версионирования и повторного применения через `kubectl apply -f deployment.yaml`.

### 3.8. Просмотр ReplicaSet

Команда `kubectl get rs` отображает состояние ReplicaSet, управляемых Deployment:

```bash
kubectl get rs
# NAME                              DESIRED   CURRENT   READY   AGE
# nginx-deployment-5d59d67564       3         3         3       5m
# nginx-deployment-7f8b9c6d5e       0         0         0       2m
```

| Поле | Описание |
| :--- | :--- |
| **DESIRED** | Желаемое количество реплик, указанное в spec Deployment |
| **CURRENT** | Фактическое количество запущенных реплик на текущий момент |
| **READY** | Количество реплик, прошедших readinessProbe и готовых принимать трафик |
| **AGE** | Время жизни ReplicaSet |

Имя каждого ReplicaSet содержит хэш (`5d59d67564`), обеспечивающий уникальность. При каждом обновлении Deployment создаётся новый ReplicaSet с уникальным хэшем.

## 4. Дополнительная информация

### 4.1. См. также

- Концепции Deployment: [deployment_concepts.md](./deployment_concepts.md)
- Манифест и лучшие практики: [deployment_manifest.md](./deployment_manifest.md)
- Стратегии развёртывания и откат: [Deployment Health Checks and Rollback](../../../CI-CD/Deployment_Strategies/deployment_health_checks_and_rollback.md)
