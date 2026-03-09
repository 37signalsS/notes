# Управление жизненным циклом Deployment

## Создание и проверка

```bash
# Создаем Deployment
kubectl apply -f nginx-deployment.yaml
# deployment.apps/nginx-deployment created

# Проверяем иерархию созданных объектов
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

Мы видим, что `Deployment` создал один `ReplicaSet`, который, в свою очередь, запустил три `Pod`.

## Обновление (Rolling Update)

Обновим версию Nginx с `1.28.0` до `1.29.0`. Это можно сделать, изменив файл манифеста и применив его снова, или с помощью императивной команды `kubectl set image`.

```bash
# Обновляем образ в контейнере 'nginx' деплоймента 'nginx-deployment'
kubectl set image deployment/nginx-deployment nginx=nginx:1.29.0 --record
# deployment.apps/nginx-deployment image updated

# Наблюдаем за процессом в реальном времени
kubectl rollout status deployment/nginx-deployment
# Waiting for deployment "nginx-deployment" rollout to finish: 2 out of 3 new replicas have been updated...
# deployment "nginx-deployment" successfully rolled out
```

Что произошло "под капотом":

1. `Deployment` создал **новый** `ReplicaSet` с обновленным шаблоном (`nginx:1.29.0`).
2. Он начал постепенно увеличивать количество реплик нового `ReplicaSet` и уменьшать количество реплик старого.
3. В результате поды заменялись один за другим без простоя приложения.

```bash
# Проверим, что старый ReplicaSet остался для истории
kubectl get replicaset
# NAME                                     DESIRED   CURRENT   READY   AGE
# nginx-deployment-5d59d67564              0         0         0       5m
# nginx-deployment-new-version-86f596b6c   3         3         3       3m
```

## Откат при неудачном обновлении

Попробуем обновиться на несуществующую версию `nginx:1.999.9`.

```bash
kubectl set image deployment/nginx-deployment nginx=nginx:1.999.9
# deployment.apps/nginx-deployment image updated
```

Смотрим, что происходит:

```bash
kubectl get pods -l app=nginx
# NAME                                     READY   STATUS             RESTARTS   AGE
# nginx-deployment-new-version-86f596b6c-abcde   1/1     Running            0          8m
# nginx-deployment-new-version-86f596b6c-fghij   1/1     Running            0          8m
# nginx-deployment-failed-update-12345678-klmno   0/1     ImagePullBackOff   0          1m
```

Kubernetes пытается создать новый под, но не может скачать образ, что приводит к статусу `ImagePullBackOff`. Старые поды при этом продолжают работать, обслуживая трафик.

### Диагностика

Используем `describe pod` для выяснения причины.

```bash
kubectl describe pod nginx-deployment-failed-update-12345678-klmno

# ... в секции Events ...
# Events:
#   Type     Reason     Age                From               Message
#   ----     ------     ----               ----               -------
#   Normal   Scheduled  <unknown>          default-scheduler  Successfully assigned default/nginx-pod to node-1
#   Normal   Pulling    24s (x4 over 90s)  kubelet, node-1    Pulling image "nginx:1.999.9"
#   Warning  Failed     23s (x4 over 89s)  kubelet, node-1    Failed to pull image "nginx:1.999.9": rpc error: code = Unknown desc = Error response from daemon: manifest for nginx:1.999.9 not found
#   Warning  Failed     23s (x4 over 89s)  kubelet, node-1    Error: ErrImagePull
#   Normal   BackOff    10s (x6 over 88s)  kubelet, node-1    Back-off pulling image "nginx:1.999.9"
#   Warning  Failed     10s (x6 over 88s)  kubelet, node-1    Error: ImagePullBackOff
```

События ясно показывают, что образ не найден.

### Откат

Отменим неудачное развертывание.

```bash
kubectl rollout undo deployment/nginx-deployment
# deployment.apps/nginx-deployment rolled back
```

`Deployment` удалит проблемный `ReplicaSet` и вернет предыдущий `ReplicaSet` в рабочее состояние.

## История ревизий и откат к конкретной версии

```bash
# Посмотрим историю изменений
# Флаг --record записывает команду в аннотацию 'change-cause'
kubectl rollout history deployment/nginx-deployment
# REVISION  CHANGE-CAUSE
# 1         kubectl apply --filename=nginx-deployment.yaml
# 2         kubectl set image deployment/nginx-deployment nginx=nginx:1.29.0 --record
# 3         kubectl set image deployment/nginx-deployment nginx=nginx:1.999.9

# Мы можем откатиться не только к предыдущей, но и к любой ревизии
kubectl rollout undo deployment/nginx-deployment --to-revision=1
```

## Дополнительные команды kubectl

### Пауза и возобновление развертывания

```bash
# Приостановить развертывание
kubectl rollout pause deployment/my-webapp

# После внесения всех изменений, возобновить
kubectl rollout resume deployment/my-webapp
```

Это полезно, чтобы применить несколько изменений в спецификации `Deployment` одним батчем, а не запускать обновление после каждого `kubectl edit` или `kubectl patch`.

### Принудительный перезапуск (рестарт)

```bash
# Элегантный способ перезапустить все поды в деплойменте
kubectl rollout restart deployment/my-webapp
```

Эта команда инициирует стандартный `Rolling Update`, не изменяя сам манифест. Это идеальный способ заставить поды подхватить изменения из [ConfigMap](../configmap.md) или [Secret](../secrets/secrets_basics.md). Команда также работает для [DaemonSet](../daemonset.md) и [StatefulSet](../statefulset.md).
