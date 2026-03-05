# Практическое руководство по StatefulSet

## Сценарий использования: Stateful-приложения (Kafka, базы данных)

`StatefulSet` является единственным правильным выбором для запуска приложений, которые требуют стабильного хранения данных и сетевой идентификации. Классический пример — **Apache Kafka**.

**Проблема:** Если развернуть Kafka с помощью `Deployment`, при любом рестарте пода (из-за сбоя ноды, обновления или масштабирования) он потеряет связь со своим диском (`PersistentVolume`). `Deployment` создает новый под как "чистый лист", без привязки к состоянию предыдущего. Это неминуемо приведет к **потере данных** в брокере Kafka.

**Решение с `StatefulSet`:**

`StatefulSet` решает эту проблему, предоставляя каждому поду:

1. **Стабильное имя**: `kafka-0`, `kafka-1`, и т.д.
2. **Стабильный PVC**: Для `kafka-0` будет автоматически создан и привязан PVC `data-kafka-0`, для `kafka-1` — `data-kafka-1`.

При рестарте пода `kafka-0` (даже на другой ноде) `StatefulSet` гарантирует, что он будет снова подключен к своему уникальному PVC `data-kafka-0`, сохраняя все данные.

## Пример: Развертывание Nginx с StatefulSet

Развернем простое stateful-приложение на базе Nginx, где каждый экземпляр будет иметь свой собственный, постоянный `index.html`.

### Шаг 1: Создание Headless Service

Необходимо для присвоения подам уникальных DNS-имен в формате `<pod-name>.<service-name>.<namespace>.svc.cluster.local`.

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
        env: # Добавление переменных окружения
        - name: POD_IP # Название переменной окружения
          valueFrom:
            fieldRef:
              fieldPath: status.podIP # берет из описания пода IP и прокидывает его в контейнер как env

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

### Шаг 3: Проверка развертывания и состояния

**Применить манифесты:**

```bash
kubectl apply -f service-headless.yaml
kubectl apply -f statefulset.yaml
```

**Проверить поды и PVC:**

Поды (`my-app-0`, `my-app-1`) и PVC (`data-volume-my-app-0`, `data-volume-my-app-1`) будут созданы последовательно.

```bash
kubectl get pods,pvc -l app=my-stateful-app
```

**Записать уникальные данные в каждый под:**

```bash
kubectl exec my-app-0 -- /bin/sh -c 'echo "Hello from Pod 0" > /usr/share/nginx/html/index.html'
kubectl exec my-app-1 -- /bin/sh -c 'echo "Hello from Pod 1" > /usr/share/nginx/html/index.html'
```

**Проверить восстановление состояния:**

Удалим один из подов, чтобы увидеть, как `StatefulSet` его восстановит с тем же состоянием.

```bash
kubectl delete pod my-app-1
# ...подождите немного...
kubectl get pods # Убедитесь, что my-app-1 снова запущен
kubectl exec my-app-1 -- cat /usr/share/nginx/html/index.html
# Вывод должен быть: Hello from Pod 1
```

**Проверка DNS:**

```bash
kubectl run -it --rm --image=busybox dns-test -- /bin/sh

# Внутри dns-test пода:
# Запрос к сервису вернет IP обоих подов
nslookup my-app-headless

# Запрос к конкретному поду вернет его собственный IP
nslookup my-app-0.my-app-headless
```

### Шаг 4: Публикация конкретного пода StatefulSet

**Проблема:** Стабильное DNS-имя пода (например, `my-app-0.my-app-headless...`) доступно только внутри кластера. Вы не можете использовать это FQDN напрямую в `Ingress`, так как поле `service.name` ожидает имя сервиса, а не произвольное доменное имя.

**Решение:** Создать стандартный сервис типа `ClusterIP`, который будет нацелен только на один конкретный под `StatefulSet`. Это достигается с помощью метки `statefulset.kubernetes.io/pod-name`, которую Kubernetes автоматически добавляет к каждому поду.

**Пример:** Опубликуем под `my-app-0` через Ingress.

1. **Создаем сервис, нацеленный на `my-app-0`:**

    ```yaml
    # service-for-pod-0.yaml
    apiVersion: v1
    kind: Service
    metadata:
      name: my-app-0-service # Имя нового сервиса
    spec:
      selector:
        # Указываем метку, уникальную для пода my-app-0
        statefulset.kubernetes.io/pod-name: my-app-0
      ports:
        - protocol: TCP
          port: 80
          targetPort: 80
    ```

2. **Создаем `Ingress`, указывающий на этот сервис:**

    ```yaml
    # ingress-for-pod-0.yaml
    apiVersion: networking.k8s.io/v1
    kind: Ingress
    metadata:
      name: my-app-0-ingress
    spec:
      rules:
      - host: "app-0.example.com"
        http:
          paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: my-app-0-service # Ссылаемся на наш новый сервис
                port:
                  number: 80
    ```

После применения этих манифестов, трафик, приходящий на `app-0.example.com`, будет направлен через `Ingress` на `my-app-0-service` и далее только на под `my-app-0`.
