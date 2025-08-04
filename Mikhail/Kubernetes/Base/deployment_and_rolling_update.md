# Deployment и Rolling Update

## Что такое Deployment?

**Deployment** — это объект Kubernetes, который декларативно управляет жизненным циклом `Pod`-ов через `ReplicaSet`. Его основная задача — поддерживать заданное количество работающих экземпляров приложения и обеспечивать их плавное обновление.

Схема управления выглядит так: `Deployment` → `ReplicaSet` → `Pod`.

Когда вы создаете или обновляете `Deployment`, он создает новый `ReplicaSet`. Этот `ReplicaSet`, в свою очередь, запускает `Pod`-ы в соответствии с указанным шаблоном (`template`).

## Стратегия обновления: Rolling Update

**Rolling Update** — это стратегия обновления по умолчанию, которая позволяет обновлять приложение без простоя. Она постепенно заменяет `Pod`-ы старой версии на `Pod`-ы новой, контролируя количество одновременно доступных и создаваемых экземпляров.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-deployment
  labels:
    app: my-app
spec:
  replicas: 3
  # revisionHistoryLimit: 5 # Сохранять только 5 старых ReplicaSet'ов для истории и отката
  selector:
    matchLabels:
      app: my-app
  strategy:
    type: RollingUpdate
    rollingUpdate:
      # maxSurge: определяет, на сколько Pod'ов можно превысить желаемое число реплик.
      # Может быть числом (1) или процентом ("25%").
      maxSurge: 1

      # maxUnavailable: определяет, сколько Pod'ов может быть недоступно во время обновления.
      # Может быть числом (1) или процентом ("25%").
      maxUnavailable: 1
  template:
    metadata:
      labels:
        app: my-app
    spec:
#      revisionHistoryLimit: 5  # Сохранять только 5 старых ReplicaSet'ов
      containers:
      - name: my-container
        image: nginx:latest
        ports:
        - containerPort: 80
```

При обновлении (например, смена `image`), `Deployment` создаст новый `ReplicaSet`. Старый `ReplicaSet` будет сохранен для возможности отката. По умолчанию Kubernetes хранит историю из **10** старых `ReplicaSet`-ов. Это можно изменить с помощью поля `spec.revisionHistoryLimit`.

## Управление развертываниями

### Просмотр истории

Чтобы увидеть историю всех развертываний и их ревизий, используйте команду:

```bash
kubectl rollout history deployment my-deployment
```

### Откат изменений

Вы можете откатиться к предыдущей успешной версии:

```bash
# Откат к последней ревизии
kubectl rollout undo deployment my-deployment
```

Для отката к конкретной ревизии укажите ее номер с флагом `--to-revision`:

```bash
# Откат к ревизии номер 1
kubectl rollout undo deployment my-deployment --to-revision=1
```
