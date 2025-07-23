# ReplicaSet

**ReplicaSet** — это объект Kubernetes, основная задача которого — поддерживать стабильное количество работающих экземпляров (реплик) пода. Он гарантирует, что указанное число подов всегда будет запущено.

**Важно:** На практике `ReplicaSet` редко используется напрямую. Вместо него следует использовать объект **`Deployment`**, который управляет `ReplicaSet`'ами и предоставляет декларативные обновления для подов, такие как `RollingUpdate`.

---

### Как это работает?

1.  Вы определяете `ReplicaSet`, указывая:
    *   `replicas`: Желаемое количество подов.
    *   `selector`: Как `ReplicaSet` находит поды, которыми он должен управлять (по меткам).
    *   `template`: Шаблон для создания новых подов, если их количество меньше желаемого.

2.  Контроллер `ReplicaSet` постоянно отслеживает количество подов, соответствующих селектору.
    *   Если подов меньше, чем `replicas`, он создает новые из шаблона.
    *   Если подов больше, он удаляет лишние.
    *   Если под, управляемый `ReplicaSet`, выходит из строя, контроллер автоматически создает замену.

---

### Пример манифеста

Этот манифест создает `ReplicaSet`, который будет поддерживать 3 реплики пода с Nginx.

```yaml
apiVersion: apps/v1
kind: ReplicaSet
metadata:
  name: nginx-replicaset
  labels:
    app: nginx
spec:
  replicas: 3
  selector:
    # Этот селектор должен соответствовать меткам в шаблоне пода
    matchLabels:
      app: nginx
  template:
    metadata:
      # Эти метки будут применены к каждому созданному поду
      labels:
        app: nginx
    spec:
      containers:
      - name: nginx
        image: nginx:latest
        ports:
        - containerPort: 80
```

### Команды для работы

```bash
# Применить манифест
kubectl apply -f replicaset.yaml

# Посмотреть статус
kubectl get replicaset nginx-replicaset

# Посмотреть поды, управляемые ReplicaSet
kubectl get pods --selector=app=nginx

# Динамически изменить количество реплик
kubectl scale replicaset nginx-replicaset --replicas=5

# Посмотреть подробную информацию
kubectl describe replicaset nginx-replicaset
```