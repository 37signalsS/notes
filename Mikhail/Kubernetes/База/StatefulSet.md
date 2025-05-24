Позволяет запускает группу подов но:

- гарантирует их уникальность(если нода стал notready то кубер не будет переносить под StatefulSet на другую ноду)
- гарантирует их последовательность(запускаются по порядку и строго по одному с нулевого пода, удаляться поду будут с конца)

При удалении  StatefulSet не удаляет PVC

``` yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: web
spec:
  serviceName: "nginx" # Обязательное поле, указывает на Headless Service
  replicas: 3         # Количество реплик
  selector:
    matchLabels:
      app: nginx       # Метка для выбора подов
  template:
    metadata:
      labels:
        app: nginx     # Метка, которая будет применена к подам
    spec:
      containers:
      - name: nginx
        image: nginx:1.23.4 # Используемый образ контейнера
        ports:
        - containerPort: 80 # Порт, на котором работает Nginx
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
      accessModes: [ "ReadWriteOnce" ] # Режим доступа к хранилищу
      resources:
        requests:
          storage: 1Gi # Размер запрашиваемого хранилища
```
