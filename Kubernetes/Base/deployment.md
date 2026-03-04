# Deployment

## Определения

**Deployment** — это объект Kubernetes, который декларативно управляет жизненным циклом подов. Его основная задача — поддерживать заданное количество работающих экземпляров приложения (`replicas`) и обеспечивать их предсказуемое, контролируемое обновление.

Схема управления: Deployment → [ReplicaSet](#replicaset-двигатель-для-deployment) → [Pod](./Pod/pod_overview.md).

Когда вы создаете или обновляете `Deployment`, он создает новый `ReplicaSet`. Этот `ReplicaSet`, в свою очередь, запускает поды в соответствии с указанным шаблоном (`template`). Старый `ReplicaSet` сохраняется для возможности отката.

### ReplicaSet: Двигатель для Deployment

**[ReplicaSet](./replicaset.md)** — это объект Kubernetes, основная задача которого — гарантировать, что указанное количество идентичных подов (реплик) всегда будет запущено.

`Deployment` использует `ReplicaSet` для управления жизненным циклом подов. При каждом обновлении `Deployment` создает новый `ReplicaSet` и постепенно переводит на него поды, сохраняя старый `ReplicaSet` для возможности отката.

Такая схема позволяет `Deployment` выполнять декларативные обновления и откаты, получая при этом все преимущества `ReplicaSet` (например, самовосстановление подов). Подробнее см. в документе [ReplicaSet](./replicaset.md).

## Основные концепции

### Анатомия манифеста

- **`replicas`**: Указывает желаемое количество реплик (подов), которое Deployment должен постоянно поддерживать.

- **`selector`**: Определяет, как Deployment находит поды, которыми он должен управлять.
  **Важно:** Метки (labels) в `spec.selector.matchLabels` должны в точности совпадать с метками в `spec.template.metadata.labels`.

- **`template`**: Это шаблон (blueprint), по которому будут создаваться поды. Он содержит свою `metadata` и `spec` с описанием контейнеров.

- **`strategy`**: Задаёт стратегию обновления для подов.
  - **`type: RollingUpdate`**: Стратегия по умолчанию. Обновление происходит постепенно, под за подом, обеспечивая непрерывную работу приложения.
    - **`maxUnavailable`**: Допустимое количество подов, которые могут быть недоступны во время обновления.
    - **`maxSurge`**: Максимальное количество подов, которое может быть создано сверх желаемого числа `replicas`.
  - **`type: Recreate`**: Альтернативная стратегия, при которой Deployment сначала останавливает все старые поды и только потом запускает новые. **Это приводит к простою приложения.**

- **`revisionHistoryLimit`**: Сколько старых `ReplicaSet`'ов хранить для истории и отката. Предотвращает «захламление» кластера старыми версиями. **По умолчанию: 10**.

> **Совет:** Используйте YAML-anchors (`&` и `*`) для повторяющихся меток в манифесте, чтобы избежать дублирования и упростить обновление версий:

- **`progressDeadlineSeconds`**: Таймаут для развертывания. Если за это время новый `ReplicaSet` не станет доступным (например, из-за `CrashLoopBackOff` или ошибок `readinessProbe`), `Deployment` перестанет пытаться его развернуть. Его статус перейдет в состояние `Progressing=False` с причиной `ProgressDeadlineExceeded`, а сам `Deployment` будет считаться "деградировавшим" (`Degraded`).

### Стратегии обновления

#### Rolling Update (по умолчанию)

**Rolling Update** — это стратегия обновления, которая позволяет обновлять приложение без простоя. Она постепенно заменяет поды старой версии на поды новой, контролируя количество одновременно доступных и создаваемых экземпляров с помощью `maxSurge` и `maxUnavailable`.

**Сценарий:** У нас есть `replicas: 3`, `maxSurge: 1`, `maxUnavailable: 1`. Мы обновляем образ с `nginx:1.28.0` на `nginx:1.29.0`.

1. **Начало:** В кластере работают 3 пода со старой версией (v1).
2. **Шаг 1 (Surge):** Deployment создает 1 новый под (v2), так как `maxSurge: 1` позволяет иметь `3 + 1 = 4` пода одновременно.
3. **Ожидание:** Deployment ждет, пока новый под (v2) полностью запустится и пройдет проверку `readinessProbe`.
4. **Шаг 2 (Unavailable):** Как только новый под готов, Deployment удаляет 1 старый под (v1). В этот момент у нас 2 пода v1 и 1 под v2. Общее количество доступных подов не падает ниже `3 - 1 = 2`.
5. **Повторение:** Процесс повторяется, пока все реплики не будут обновлены до новой версии.

> **Примечание:** Для максимально плавного `Rolling Update` рекомендуется иметь как минимум две реплики сервиса. Это гарантирует, что даже при `maxUnavailable: 1` всегда будет доступен хотя бы один под.

#### Recreate

При этой стратегии Deployment сначала останавливает **все** старые поды и только потом запускает новые.

**Это приводит к простою (downtime)!**

Стратегия `Recreate` может использоваться если:

- Приложение не поддерживает работу двух версий параллельно.
- Потребление ресурсов не позволяет запускать новый под до остановки старого.

| Стратегия | Плюсы | Минусы | Когда выбирают |
| :--- | :--- | :--- | :--- |
| **`RollingUpdate`** | Минимальный или нулевой простой. | Требует совместимости версий. | Веб-сервисы, stateless-приложения, где важна непрерывность. |
| **`Recreate`** | Полностью атомарное обновление. | Приводит к простою приложения. | Несовместимые версии, миграции схем БД, монолиты. |

# Практические сценарии

## Пример манифеста

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-deployment
  labels:
    app: nginx
spec:
  replicas: 3
  revisionHistoryLimit: 3
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
      - name: nginx
        image: nginx:1.28.0 # Используйте конкретную версию, а не :latest
        ports:
        - containerPort: 80
        resources:
          requests:
            memory: "64Mi"
            cpu: "100m"
          limits:
            memory: "128Mi"
            cpu: "250m"
        readinessProbe:
          httpGet:
            path: /
            port: 80
          initialDelaySeconds: 5
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /
            port: 80
          initialDelaySeconds: 15
          periodSeconds: 20
```

## Управление жизненным циклом

### Шаг 1: Создание и проверка

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

### Шаг 2: Успешное обновление (Rolling Update)

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

### Шаг 3: Неудачное обновление и откат

Теперь попробуем обновиться на несуществующую версию `nginx:1.999.9`.

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

**Диагностика:**
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

**Откат:**
Отменим неудачное развертывание.

```bash
kubectl rollout undo deployment/nginx-deployment
# deployment.apps/nginx-deployment rolled back
```
`Deployment` удалит проблемный `ReplicaSet` и вернет предыдущий `ReplicaSet` в рабочее состояние.

### Шаг 4: Просмотр истории и откат к конкретной ревизии

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

## Дополнительные команды `kubectl`

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
Эта команда инициирует стандартный `Rolling Update`, не изменяя сам манифест. Это идеальный способ заставить поды подхватить изменения из [ConfigMap](./configmap.md) или [Secret](secrets/secrets_basics.md). Команда также работает для [DaemonSet](./daemonset.md) и [StatefulSet](./statefulset.md).

## Дополнительная информация

### Owner References

Каждый ресурс содержит поле `ownerReferences` в `metadata`, которое показывает связь "родитель-потомок":
- Pod → принадлежит ReplicaSet
- ReplicaSet → принадлежит Deployment

Это используется для каскадного удаления: при удалении `Deployment` автоматически удаляются связанные `ReplicaSet` и `Pod`.

## Лучшие практики

- **Всегда используйте `readinessProbe`:** Без него Kubernetes не знает, готов ли ваш под принимать трафик, что может привести к ошибкам у пользователей во время `Rolling Update`. Подробнее см. [Высокая доступность](./high_availability.md).
- **Используйте иммутабельные теги или digest для образов:** Никогда не используйте тег `:latest` в продакшене. Всегда указывайте конкретную версию (например, `nginx:1.28.0`) или `digest` (`sha256:...`).
- **Настройте `maxSurge` и `maxUnavailable`:**
  - `maxUnavailable: 0` — более безопасный вариант, гарантирующий отсутствие потери мощности, но требующий больше ресурсов (`maxSurge` должен быть > 0).
  - `maxSurge: 0` — экономит ресурсы, но может снизить производительность во время обновления.
- **Настройте авто-масштабирование:** Для динамического управления количеством реплик используйте [Horizontal Pod Autoscaler](../Autoscaling/overview_concepts.md).
- **Используйте `imagePullPolicy: IfNotPresent`:** Политика `Always` может привести к избыточной нагрузке на registry и проблемам с rate-лимитами, в то время как `IfNotPresent` является более предсказуемой для версионированных образов.
- **Продвинутые стратегии:** Для минимизации рисков при выкатке критичных изменений используйте [расширенные стратегии развертывания](../Operations/Advanced_Deployment_Strategies.md), такие как Blue/Green и Canary.

## Когда использовать Deployment vs StatefulSet

> Подробнее о различиях и особенностях работы с приложениями, требующими сохранения состояния, читайте в документе [StatefulSet](./statefulset.md).

## Связанные темы

-   [ConfigMap](./configmap.md) — внешняя конфигурация
-   [Secret](secrets/secrets_basics.md) — конфиденциальные данные
-   [StatefulSet](./statefulset.md) — управление stateful-приложениями
-   [Высокая доступность](./high_availability.md) — обеспечение отказоустойчивости
-   [Pod](./Pod/pod_overview.md) — базовый объект развертывания
-   [ReplicaSet](./replicaset.md) — управление репликами
-   [Horizontal Pod Autoscaler](../Autoscaling/overview_concepts.md) — автоматическое масштабирование
-   [Расширенные стратегии развертывания](../Operations/Advanced_Deployment_Strategies.md) — Blue/Green, Canary
