Более продвинутый способ обновления - добавление Rollingupdate(в данном случае при обновлении образа мы указываем что можно отключить одну старую версию приложения и запустить одну новую, соотношение запуска/приостановления приложений можно укзывать в %)

``` yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-deployment
  labels:
    app: my-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: my-app
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1 # Максимум 1 дополнительный Pod может быть создан сверх желаемого количества
      maxUnavailable: 1 # Максимум 1 старый Pod может быть временно недоступен
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

В случае описанном выше при выполнении kubectl get pod, rs, de, можно проследить след. логику: деплоймент как родительский процесс создал дочерний процесс replicaset который в свою очередь создал поды 

Deployment управляет ReplicaSet'ами, а ReplicaSet управляет Pod'ами.

Если применить выше описанный yaml файл то создаться новый ReplicaSet, а старый сохраниться и его deployment оставляет как бэкап, максимум таких бэкапов по дефолту может быть до 10

Восстановление из ReplicaSet предоставляемых deployment 

``` sh
kubectl rollout undo deployment my-deployment
```
в данном случае будет использован последний бэкап,с флагом --to-revision=1 уже будет выбран позапрошлый бэкап

История изменений Deployment-ов 

``` sh
kubectl rollout history deployment my-deployment
```
