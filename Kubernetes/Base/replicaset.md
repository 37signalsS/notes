# ReplicaSet

**ReplicaSet** — это объект Kubernetes, который гарантирует, что указанное количество идентичных [Pod](./pod.md)-ов (реплик) всегда будет запущено.

> **Важно:** На практике `ReplicaSet` редко используется напрямую. Вместо него рекомендуется использовать [Deployment](./deployment_and_rolling_update.md), который управляет ReplicaSet-ами и предоставляет декларативные обновления, такие как RollingUpdate.

## Как это работает?

`ReplicaSet` работает на основе трех ключевых полей:

1.  **`replicas`**: Желаемое количество `Pod`-ов.
2.  **`selector`**: Метки, по которым `ReplicaSet` находит `Pod`-ы для управления.
3.  **`template`**: Шаблон для создания новых `Pod`-ов, если их количество меньше желаемого.

Контроллер `ReplicaSet` постоянно отслеживает количество подов, соответствующих селектору:

*   Если подов меньше, чем `replicas`, он создает новые из шаблона.
*   Если подов больше, он удаляет лишние.
*   Если под, управляемый `ReplicaSet`, выходит из строя, контроллер автоматически создает замену.

---

### Пример манифеста

Этот манифест создает `ReplicaSet`, который поддерживает 3 реплики `Pod`-а с Nginx.

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
        image: nginx:1.28.0
        ports:
        - containerPort: 80
```

## Команды для работы

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
