# Руководство: Развертывание приложений с состоянием (Stateful)

Этот документ — пошаговое руководство по развертыванию приложений, требующих сохранения состояния (например, баз данных), в Kubernetes. 

## Проблема: Почему Deployment не подходит?

Стандартный объект [Deployment](./deployment_and_rolling_update.md) обращается с подами как со взаимозаменяемыми и не имеющими состояния "копиями". При перезапуске или переносе пода он может получить новый IP-адрес, новое имя и, что самое важное, **потерять связь со своим хранилищем**. Для веб-сервера это нормально, но для базы данных — катастрофа, равносильная потере всех данных.

## Решение: Компоненты для Stateful-приложений

Для правильного развертывания приложений с состоянием используется комбинация из четырех ключевых компонентов:

1.  **`StatefulSet`**: Главный оркестратор. В отличие от `Deployment`, он предоставляет подам стабильные имена и привязывает их к конкретным дискам.
2.  **`PersistentVolumeClaim` (PVC)**: "Запрос" пода на выделение диска. `StatefulSet` автоматически создает уникальный PVC для каждого своего пода.
3.  **`PersistentVolume` (PV)**: Физический "кусок" хранилища в кластере (NFS, Ceph, диск облачного провайдера), который удовлетворяет запрос PVC.
4.  **`Headless Service`**: Специальный тип [сервиса](./service.md), который обеспечивает каждому поду стабильное и уникальное DNS-имя внутри кластера.

---

## Пошаговый пример

Развернем простое stateful-приложение на базе Nginx, где каждый экземпляр будет иметь свой собственный, постоянный `index.html`.

### Шаг 1: Создание Headless Service

Это необходимо для того, чтобы `StatefulSet` мог присвоить подам уникальные DNS-имена.

```yaml
# service-headless.yaml
apiVersion: v1
kind: Service
metadata:
  name: my-app-headless
spec:
  clusterIP: None # <-- Ключевой параметр, делающий сервис "безголовым"
  selector:
    app: my-stateful-app # Должен соответствовать меткам подов
  ports:
  - port: 80
    name: web
```

### Шаг 2: Создание StatefulSet

Это основной манифест, который связывает все воедино.

```yaml
# statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: my-app
spec:
  # serviceName должен соответствовать имени Headless Service
  serviceName: "my-app-headless"
  replicas: 2
  selector:
    matchLabels:
      app: my-stateful-app # Должен соответствовать меткам в шаблоне
  template: # Шаблон для создания подов
    metadata:
      labels:
        app: my-stateful-app
    spec:
      containers:
      - name: nginx
        image: nginx:1.25.5
        ports:
        - containerPort: 80
          name: web
        volumeMounts:
        - name: data-volume # Имя, которое будет связано с PVC
          mountPath: /usr/share/nginx/html # Путь монтирования внутри контейнера

  # Шаблон для автоматического создания PVC для каждого пода
  volumeClaimTemplates:
  - metadata:
      name: data-volume # Имя PVC
    spec:
      accessModes: [ "ReadWriteOnce" ]
      # storageClassName: "your-storage-class" # Укажите ваш StorageClass
      resources:
        requests:
          storage: 1Gi # Размер диска для каждого пода
```

### Что здесь происходит?

1.  **`replicas: 2`**: Kubernetes создаст 2 пода: `my-app-0` и `my-app-1`.
2.  **`volumeClaimTemplates`**: Для каждого пода будет автоматически создан свой `PersistentVolumeClaim`.
    *   Под `my-app-0` получит PVC с именем `data-volume-my-app-0`.
    *   Под `my-app-1` получит PVC с именем `data-volume-my-app-1`.
3.  **Связь:** Kubernetes гарантирует, что под `my-app-0` **всегда** будет подключен к своему PVC `data-volume-my-app-0`, даже если он будет перезапущен на другой ноде.

---

## Проверка и управление

```bash
# 1. Применить манифесты
kubectl apply -f service-headless.yaml
kubectl apply -f statefulset.yaml

# 2. Проверить поды (будут называться my-app-0, my-app-1)
# Поды создаются строго по одному!
kubectl get pods -l app=my-stateful-app

# 3. Проверить PVC (будут называться data-volume-my-app-0, ...)
kubectl get pvc -l app=my-stateful-app

# 4. Запишем уникальные данные в каждый под
kubectl exec my-app-0 -- /bin/sh -c 'echo "Hello from Pod 0" > /usr/share/nginx/html/index.html'
kubectl exec my-app-1 -- /bin/sh -c 'echo "Hello from Pod 1" > /usr/share/nginx/html/index.html'

# 5. Удалим один из подов, чтобы увидеть, как StatefulSet его восстановит
kubectl delete pod my-app-1

# ...подождите немного...

# 6. Проверьте, что под восстановился и его данные на месте!
kubectl get pods # Убедитесь, что my-app-1 снова запущен
kubectl exec my-app-1 -- cat /usr/share/nginx/html/index.html
# Вывод должен быть: Hello from Pod 1
```

Этот пример наглядно демонстрирует, как `StatefulSet` обеспечивает стабильность и сохранность данных для каждого экземпляра приложения.
