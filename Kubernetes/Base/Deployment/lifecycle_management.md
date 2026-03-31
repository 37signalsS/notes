# Управление жизненным циклом Deployment

## 1. Определения

**Lifecycle Management** — управление жизненным циклом Deployment: создание, обновление, откат, пауза/возобновление и перезапуск.

Kubernetes использует механизм `Rolling Update` для плавного обновления подов без простоя приложения.

## 2. Базовые концепции

### 2.1. Иерархия объектов

`Deployment` → [`ReplicaSet`](../replicaset.md) → [`Pod`](../Pod/pod_overview.md)

При создании `Deployment` автоматически создает `ReplicaSet`, который управляет подами.

### 2.2. Механизм обновления

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

При обновлении на несуществующую версию (`nginx:1.999.9`):

```bash
kubectl set image deployment/nginx-deployment nginx=nginx:1.999.9
# deployment.apps/nginx-deployment image updated

# Проверить статус подов
kubectl get pods -l app=nginx
# NAME                                     READY   STATUS             RESTARTS   AGE
# nginx-deployment-new-version-86f596b6c-abcde   1/1     Running            0          8m
# nginx-deployment-new-version-86f596b6c-fghij   1/1     Running            0          8m
# nginx-deployment-failed-update-12345678-klmno   0/1     ImagePullBackOff   0          1m
```

**Диагностика:**

```bash
kubectl describe pod nginx-deployment-failed-update-12345678-klmno

# Events:
#   Type     Reason     Age                From               Message
#   ----     ------     ----               ----               -------
#   Warning  Failed     23s (x4 over 89s)  kubelet, node-1    Failed to pull image "nginx:1.999.9": manifest not found
#   Warning  Failed     23s (x4 over 89s)  kubelet, node-1    Error: ErrImagePull
#   Normal   BackOff    10s (x6 over 88s)  kubelet, node-1    Back-off pulling image "nginx:1.999.9"
```

**Откат:**

```bash
kubectl rollout undo deployment/nginx-deployment
# deployment.apps/nginx-deployment rolled back
```

### 3.4. История ревизий и откат к конкретной версии

```bash
# Посмотреть историю изменений
kubectl rollout history deployment/nginx-deployment
# REVISION  CHANGE-CAUSE
# 1         kubectl apply --filename=nginx-deployment.yaml
# 2         kubectl set image deployment/nginx-deployment nginx=nginx:1.29.0 --record
# 3         kubectl set image deployment/nginx-deployment nginx=nginx:1.999.9

# Откат к конкретной ревизии
kubectl rollout undo deployment/nginx-deployment --to-revision=1
```

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

## 4. Дополнительная информация

### 4.1. Связанные темы

- Концепции Deployment: [deployment_concepts.md](./deployment_concepts.md)
- Манифест и лучшие практики: [deployment_manifest.md](./deployment_manifest.md)
- Стратегии развёртывания: [Rolling Update](../../../CI-CD/Deployment_Strategies/rolling_update.md)
- Откат и проверки здоровья: [Deployment Health Checks and Rollback](../../../CI-CD/Deployment_Strategies/deployment_health_checks_and_rollback.md)
