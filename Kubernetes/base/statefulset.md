# StatefulSet

**StatefulSet** — это объект Kubernetes, предназначенный для управления приложениями с состоянием (stateful applications). В отличие от [Deployment](./deployment_and_rolling_update.md), который рассматривает поды как взаимозаменяемые, StatefulSet предоставляет гарантии относительно порядка и уникальности своих подов.

Если нода стал notready то кубер не будет переносить под StatefulSet на другую ноду.

### Ключевые отличия от Deployment:

1.  **Стабильные, уникальные сетевые идентификаторы:**
    *   Каждый [под](./pod.md) в StatefulSet получает предсказуемое имя в формате <имя-StatefulSet>-<порядковый-номер> (например, web-0, web-1).
    *   Эти имена сохраняются при перезапуске и переносе подов.

2.  **Стабильные, постоянные хранилища:**
    *   Для каждого [пода](./pod.md) создается свой собственный [PersistentVolumeClaim](./pv_and_pvc.md) (PVC) на основе шаблона (`volumeClaimTemplates`).
    *   Этот PVC привязан к конкретному поду и сохраняется даже после его удаления и пересоздания.

3.  **Упорядоченное развертывание и масштабирование:**
    *   Поды создаются последовательно, один за другим (сначала `web-0`, потом `web-1` и т.д.). Следующий под не начнет создаваться, пока предыдущий не станет `Ready`.
    *   Удаление подов происходит в обратном порядке (сначала `web-n`, потом `web-n-1`).

Требует [Headless Service](./service.md#headless-service): Для обеспечения уникальных DNS-имен для каждого пода StatefulSet требует наличия Headless Service (сервис с `clusterIP: None`).

---

### Пример использования: Stateful-приложения (Kafka, базы данных)

`StatefulSet` является единственным правильным выбором для запуска приложений, которые требуют стабильного хранения данных и сетевой идентификации. Классический пример — **Apache Kafka**.

**Проблема:** Если развернуть Kafka с помощью `Deployment`, при любом рестарте пода (из-за сбоя ноды, обновления или масштабирования) он потеряет связь со своим диском (`PersistentVolume`). `Deployment` создает новый под как "чистый лист", без привязки к состоянию предыдущего. Это неминуемо приведет к **потере данных** в брокере Kafka. [PersistentVolume](./pv_and_pvc.md)

**Решение с `StatefulSet`:**

`StatefulSet` решает эту проблему, предоставляя каждому поду:
1.  **Стабильное имя**: `kafka-0`, `kafka-1`, и т.д.
2.  **Стабильный PVC**: Для `kafka-0` будет автоматически создан и привязан PVC `data-kafka-0`, для `kafka-1` — `data-kafka-1`.

При рестарте пода `kafka-0` (даже на другой ноде) `StatefulSet` гарантирует, что он будет снова подключен к своему уникальному PVC `data-kafka-0`, сохраняя все данные.

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
        image: nginx:1.28.0
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

### Headless Service для StatefulSet

Этот сервис необходим для того, чтобы у каждого пода был свой уникальный DNS-адрес в формате `<pod-name>.<service-name>.<namespace>.svc.cluster.local`.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: nginx-headless
spec:
  ports:
  - port: 80
    name: web
  clusterIP: None # Ключевой параметр для Headless Service
  selector:
    app: nginx # Должен соответствовать меткам подов
```

### Проверка работы

```bash
# Проверить поды (будут называться web-0, web-1, web-2)
kubectl get pods -l app=nginx

# Проверить PVC (будут называться www-web-0, www-web-1, www-web-2)
kubectl get pvc -l app=nginx

# Проверить DNS-записи внутри кластера
kubectl run -it --rm --image=busybox dns-test -- /bin/sh
# nslookup web-0.nginx-headless
```
