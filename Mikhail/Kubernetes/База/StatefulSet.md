# StatefulSet

**StatefulSet** — это объект Kubernetes, предназначенный для управления приложениями с состоянием (stateful applications). В отличие от `Deployment`, который рассматривает поды как взаимозаменяемые, `StatefulSet` предоставляет гарантии относительно порядка и уникальности своих подов.

Если нода стал notready то кубер не будет переносить под StatefulSet на другую ноду.

### Ключевые отличия от Deployment:

1.  **Стабильные, уникальные сетевые идентификаторы:**
    *   Каждый под в `StatefulSet` получает предсказуемое имя в формате `<имя-StatefulSet>-<порядковый-номер>` (например, `web-0`, `web-1`).
    *   Эти имена сохраняются при перезапуске и переносе подов.

2.  **Стабильные, постоянные хранилища:**
    *   Для каждого пода создается свой собственный `PersistentVolumeClaim` (PVC) на основе шаблона (`volumeClaimTemplates`).
    *   Этот PVC привязан к конкретному поду и сохраняется даже после его удаления и пересоздания.

3.  **Упорядоченное развертывание и масштабирование:**
    *   Поды создаются последовательно, один за другим (сначала `web-0`, потом `web-1` и т.д.). Следующий под не начнет создаваться, пока предыдущий не станет `Ready`.
    *   Удаление подов происходит в обратном порядке (сначала `web-n`, потом `web-n-1`).

4.  **Требует Headless Service:**
    *   Для обеспечения уникальных DNS-имен для каждого пода `StatefulSet` требует наличия `Headless Service` (сервис с `clusterIP: None`).

---

### Пример: StatefulSet для Nginx

Этот пример разворачивает `StatefulSet` с тремя репликами Nginx. Каждый под получит свое собственное хранилище размером 1 GiB.

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: web
spec:
  # serviceName должен соответствовать имени Headless Service
  serviceName: "nginx-headless"
  replicas: 3
  selector:
    matchLabels:
      app: nginx # Должен соответствовать меткам в шаблоне
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
      - name: nginx
        image: nginx:latest
        ports:
        - containerPort: 80
          name: web
        volumeMounts:
        - name: www          # Точка монтирования тома
          mountPath: /usr/share/nginx/html # Путь внутри контейнера
        env: # Добавление переменных окружения
        - name: POD_IP # Название переменной окружения
          valueFrom:
            fieldRef:
              fieldPath: status.podIP # берет из описания пода IP и прокидывает его в кнтейнер как env
  volumeClaimTemplates: # Шаблон PVC для каждого пода
  - metadata:
      name: www
    spec:
      accessModes: [ "ReadWriteOnce" ]
      storageClassName: "my-storage-class" # Укажите ваш StorageClass
      resources:
        requests:
          storage: 1Gi
```

**Важно:** При удалении `StatefulSet` связанные с ним PVC **не удаляются** автоматически. Это сделано для защиты данных. Их необходимо удалять вручную, если они больше не нужны.