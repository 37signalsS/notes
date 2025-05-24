``` yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-configmap
data:
  CONFIG_FILE: |
    server {
        listen 80;
        server_name example.com;
        
        location / {
            root /usr/share/nginx/html;
            index index.html;
        }
    }
```

Том config создается из объекта configmap c именем my-configmap

CONFIG_FILE представляет собой многострочник - файл конфигурации nginx

В те контейнеры куда необходимо смонтировать тома добавляются с точкой монтирования(volumeMounts с указанием точки монтирования в поле mountPath)

Перед запуском подов необходимо применить манифест configmap

После монтирования configmap в примере ниже, будет потерян доступ к каталогу etc 

``` yaml
apiVersion: v1
kind: Pod
metadata:
  name: example-pod
spec:
  containers:
    - name: example-container
      image: nginx:latest
      volumeMounts:
        - name: config-volume
          mountPath: /etc/config
  volumes:
    - name: config-volume
      configMap:
        name: my-configmap
```