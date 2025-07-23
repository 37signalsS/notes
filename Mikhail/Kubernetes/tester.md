# Пример: Полный стек развертывания Nginx в kind

Этот файл содержит полный набор манифестов Kubernetes для развертывания веб-сервера Nginx в локальном кластере, созданном с помощью `kind`. Манифесты демонстрируют использование `Deployment`, `Service`, `Ingress`, `ConfigMap` и `PersistentVolume`.

---

### 1. Конфигурация кластера `kind`

Создает кластер с одним control-plane узлом и двумя рабочими узлами. Control-plane узел настроен для приема трафика Ingress на порту `8080` хост-машины.

```yaml
# kind-config.yaml
apiVersion: kind.x-k8s.io/v1alpha4
kind: Cluster
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        node-labels: "ingress-ready=true"
  extraPortMappings:
  - containerPort: 80
    hostPort: 8080
    protocol: TCP
- role: worker
- role: worker
```

---

### 2. Манифесты Kubernetes

Все последующие ресурсы можно сохранить в один файл (например, `nginx-deployment.yaml`) и применить одной командой.

```yaml
# nginx-deployment.yaml

# --- ConfigMap для конфигурации Nginx ---
apiVersion: v1
kind: ConfigMap
metadata:
  name: nginx-config
data:
  default.conf: |
    server {
        listen 80;
        server_name localhost;
        location / {
            root /usr/share/nginx/html;
            index index.html;
        }
    }

---
# --- PersistentVolumeClaim для хранения данных ---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: nginx-pvc
spec:
  accessModes:
    - ReadWriteOnce
  # Для kind требуется StorageClass по умолчанию, который он создает сам.
  # В реальном кластере здесь может быть имя вашего StorageClass.
  storageClassName: standard
  resources:
    requests:
      storage: 1Gi

---
# --- Deployment для запуска подов Nginx ---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-deployment
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
          volumeMounts:
            - name: config-volume
              mountPath: /etc/nginx/conf.d
            - name: data-volume
              mountPath: /usr/share/nginx/html
      volumes:
        - name: config-volume
          configMap:
            name: nginx-config
        - name: data-volume
          persistentVolumeClaim:
            claimName: nginx-pvc

---
# --- Service для внутренней коммуникации ---
apiVersion: v1
kind: Service
metadata:
  name: nginx-service
spec:
  selector:
    app: nginx
  ports:
    - protocol: TCP
      port: 80
      targetPort: 80
  type: ClusterIP

---
# --- Ingress для внешнего доступа ---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: nginx-ingress
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  rules:
    - http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: nginx-service
                port:
                  number: 80
```

---

### 3. Команды для развертывания

1.  **Создать кластер `kind`:**
    ```bash
    kind create cluster --config=kind-config.yaml
    ```

2.  **Развернуть Ingress-контроллер для `kind`:**
    ```bash
    kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
    ```

3.  **Подождать, пока Ingress-контроллер будет готов:**
    ```bash
    kubectl wait --namespace ingress-nginx \
      --for=condition=ready pod \
      --selector=app.kubernetes.io/component=controller \
      --timeout=90s
    ```

4.  **Применить манифесты Nginx:**
    ```bash
    kubectl apply -f nginx-deployment.yaml
    ```

5.  **Проверить доступность:**
    ```bash
    # Ответ должен быть "Welcome to nginx!"
    curl http://localhost:8080
    ```

6.  **(Опционально) Создать файл `index.html` для проверки PV:**
    ```bash
    # Найти имя одного из подов Nginx
    POD_NAME=$(kubectl get pods -l app=nginx -o jsonpath='{.items[0].metadata.name}')

    # Создать файл внутри пода
    kubectl exec -it $POD_NAME -- bash -c 'echo "<h1>Hello from Persistent Volume!</h1>" > /usr/share/nginx/html/index.html'

    # Проверить снова
    curl http://localhost:8080
    ```
