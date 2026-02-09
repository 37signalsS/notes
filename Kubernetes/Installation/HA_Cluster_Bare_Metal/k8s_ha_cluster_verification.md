### 6. Проверка работоспособности кластера

Развернем тестовое приложение Nginx.

1. **Создайте манифест `nginx-test.yaml`:**

    ```yaml
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: nginx-deployment
      labels:
        app: nginx
    spec:
      replicas: 2
      selector:
        matchLabels:
          app: nginx
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
    ---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-service
    spec:
      type: NodePort
      selector:
        app: nginx
      ports:
        - protocol: TCP
          port: 80
          targetPort: 80
    ```

2. **Примените манифест и проверьте сервис:**

    ```bash
    kubectl apply -f nginx-test.yaml
    kubectl get service nginx-service
    ```

    Узнайте `NodePort` (порт вида `3xxxx`) и проверьте доступ по адресу `http://<IP-любого-воркера>:<NodePort>`.