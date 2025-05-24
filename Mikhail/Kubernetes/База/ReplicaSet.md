Масштабирование приложение путем создания его реплик

spec.selector.matchLabels — указывает, что будут управляться поды с меткой app: my-app.

spec.template — шаблон для создания подов: metadata.labels — метки/имена, которые будут добавлены к подам.

``` yaml
apiVersion: apps/v1
kind: ReplicaSet
metadata:
  name: my-replicaset
  labels:
    app: my-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: my-app # Метки, которые должны соответствовать меткам в шаблоне Pod'а
  template:
    metadata:
      labels:
        app: my-app # Метки, которые будут добавлены к каждому созданному Pod'у
    spec:
      containers:
      - name: my-container
        image: nginx:latest
        ports:
        - containerPort: 80

```

Удалить все поды kubectl delete pod --all

Узнать сколько реплик у приложения kubectl get replicaset my-replicaset

Если создан под, и содержание его конфиг файла было измененно то изменения применяются при помощи kubectl apply -f replicaset.yaml

Динамическое масштабирование kubectl edit repicaset my-replicaset, откроется редактор где можно, например, изменить кол-во релик на 4 

Просмотр инфы об объекте в кубере kubectl describe replicaset my-replicaset

