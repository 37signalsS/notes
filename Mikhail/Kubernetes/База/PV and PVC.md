PV - постоянный том на котором хранятся данные(хранит идентификаторы диска, путь к каталогу в ФС)

SC - определяет класс хранилища и параметры provisioner'а (тип диска, политики шифрования, зонирование).  StorageClass используется для динамического создания PersistentVolume (PV) на основе запросов PersistentVolumeClaim (PVC).

PVC - запрос на резервирование постоянного тома(хранит размер и SC)
 
PV Provisioners - отвечает за динамическое создание PV на основе запросов PVC. 

``` yaml
---
# 1. StorageClass
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: my-storage-class
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: WaitForFirstConsumer # создание связки PV and PVC только при появлении нагрузки(пока поду не потребуется PVC)
---
# 2. PersistentVolume (PV)
apiVersion: v1
kind: PersistentVolume
metadata:
  name: my-pv
  labels:
    type: local
spec:
  capacity:
    storage: 1Gi
  volumeMode: Filesystem
  accessModes:
    - ReadWriteOnce # или ReadWriteMany, если необходимо
  storageClassName: my-storage-class
  persistentVolumeReclaimPolicy: Delete # что будет происходить с PV после удаления PVC
  local: # позволяет обращаться к Фс хостовой машины, не умеют в переезд
    path: /mnt
  nodeAffinity:
    required:
      nodeSelectorTerms:
        - matchExpressions:
            - key: kubernetes.io/hostname
              operator: In
              values:
                - my-node-name  # имя узла к ФС которого мы хотим подключиться 
---
# 3. PersistentVolumeClaim (PVC)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-pvc
spec:
  accessModes:
    - ReadWriteOnce # исклюзивный доступ к диску, ReadWriteMany - множественный доступ к диску
  storageClassName: my-storage-class
  resources:
    requests:
      storage: 1Gi
---
# 4. ConfigMap с многострочным значением
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-config
data:
  app.conf: |
    server {
        listen 80;
        server_name example.com;
        
        location / {
            root /usr/share/nginx/html;
            index index.html;
        }
    }
---
# 5. Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-deployment
spec:
  replicas: 2
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      containers:
        - name: my-container
          image: nginx:latest
          ports:
            - containerPort: 80
          volumeMounts:
            # Монтируем ConfigMap как том для конфигурационных файлов
            - name: config-volume
              mountPath: /etc/nginx/conf.d
            # Монтируем PVC как том для хранения данных (например, HTML файлов)
            - name: data
              mountPath: /data
      volumes:
        - name: config-volume 
          configMap:
            name: my-config
        - name: data-volume
          persistentVolumeClaim:
            claimName: my-pvc
---
# 6. Service для доступа к Deployment
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  selector:
    app: my-app
  ports:
    - protocol: TCP
      port: 80
      targetPort: 80
  type: ClusterIP
---
# 7. Ingress для внешнего доступа к сервису
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-ingress
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  rules:
    - host: example.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: my-service
                port:
                  number: 80

```

Отключение или добавление инстансов - kubectl scale deployment имядеплоймента --replicas=0(0-остановка deployment, 2 - две реплики)