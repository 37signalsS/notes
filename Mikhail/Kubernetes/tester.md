# Развертывание Nginx в kind: полный пример

Этот документ представляет собой полное пошаговое руководство по развертыванию веб-сервера Nginx в локальном Kubernetes-кластере, созданном с помощью `kind`.

Манифесты демонстрируют совместное использование ключевых объектов Kubernetes:
*   `Deployment` для управления подами приложения.
*   `Service` для организации сетевого взаимодействия.
*   `Ingress` для предоставления доступа к приложению извне.
*   `ConfigMap` для инъекции конфигурационных файлов.
*   `PersistentVolumeClaim` для обеспечения постоянного хранения данных.

---

### 1. Конфигурация кластера `kind`

Сначала подготовим конфигурационный файл для `kind`, который создаст кластер с одним control-plane и двумя рабочими узлами. Control-plane узел будет перенаправлять трафик с порта `8080` хост-машины на Ingress-контроллер внутри кластера.

```yaml
# kind-config.yaml
# API-версия v1alpha4 является актуальной для kind.
apiVersion: kind.x-k8s.io/v1alpha4
kind: Cluster
nodes:
- role: control-plane
  # Патч для kubeadm, добавляющий метку узлу.
  # Это необходимо для корректной работы Ingress-контроллера.
  kubeadmConfigPatches:
  - | 
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        node-labels: "ingress-ready=true"
  # Проброс порта 80 из контейнера control-plane на порт 8080 хоста.
  extraPortMappings:
  - containerPort: 80
    hostPort: 8080
    protocol: TCP
- role: worker
- role: worker
```

---

### 2. Манифесты Kubernetes

Все ресурсы для развертывания Nginx собраны в один файл `nginx-stack.yaml`.

```yaml
# nginx-stack.yaml

# --- ConfigMap для конфигурации Nginx ---
# Хранит конфигурационный файл Nginx, который будет смонтирован в поды.
apiVersion: v1
kind: ConfigMap
metadata:
  name: nginx-config
  labels:
    app.kubernetes.io/name: nginx
    app.kubernetes.io/instance: nginx
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
# Запрашивает постоянное хранилище для веб-контента Nginx.
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: nginx-pvc
  labels:
    app.kubernetes.io/name: nginx
    app.kubernetes.io/instance: nginx
spec:
  accessModes:
    - ReadWriteOnce # NOTE: Может быть смонтирован для чтения/записи только одним узлом.
  # kind автоматически создает StorageClass с именем "standard".
  # В облачных провайдерах здесь указывается нужный класс хранения (например, gp2, managed-premium).
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
  labels:
    app.kubernetes.io/name: nginx
    app.kubernetes.io/instance: nginx
spec:
  # NOTE(ИИ): Установлена 1 реплика, т.к. PVC (ReadWriteOnce) может быть использован только одним подом.
  # Для масштабирования приложений с состоянием рекомендуется использовать StatefulSet.
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: nginx
      app.kubernetes.io/instance: nginx
  template:
    metadata:
      labels:
        app.kubernetes.io/name: nginx
        app.kubernetes.io/instance: nginx
    spec:
      containers:
        - name: nginx
          image: nginx:1.25.4 # NOTE(ИИ): Использование фиксированной версии образа — лучшая практика.
          ports:
            - containerPort: 80
          # NOTE(ИИ): Probes — критически важный механизм для автоматического контроля состояния приложения.
          readinessProbe:
            httpGet:
              path: /
              port: 80
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /
              port: 80
            initialDelaySeconds: 15
            periodSeconds: 20
          # NOTE(ИИ): Requests и Limits гарантируют качество обслуживания (QoS) и стабильность кластера.
          resources:
            requests:
              cpu: "100m"
              memory: "128Mi"
            limits:
              cpu: "250m"
              memory: "256Mi"
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
# Предоставляет стабильную точку доступа (IP-адрес и DNS-имя) к подам Nginx внутри кластера.
apiVersion: v1
kind: Service
metadata:
  name: nginx-service
  labels:
    app.kubernetes.io/name: nginx
    app.kubernetes.io/instance: nginx
spec:
  selector:
    app.kubernetes.io/name: nginx
    app.kubernetes.io/instance: nginx
  ports:
    - protocol: TCP
      port: 80
      targetPort: 80
  type: ClusterIP
---
# --- Ingress для внешнего доступа ---
# Управляет внешним доступом к сервисам в кластере, обычно HTTP.
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: nginx-ingress
  labels:
    app.kubernetes.io/name: nginx
    app.kubernetes.io/instance: nginx
spec:
  # NOTE(ИИ): Указание ingressClassName является современной практикой.
  # Это позволяет точно выбрать контроллер, который будет обрабатывать данный Ingress.
  ingressClassName: nginx
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

2.  **Развернуть Ingress-контроллер NGINX для `kind`:**
    ```bash
    kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
    ```

3.  **Дождаться готовности Ingress-контроллера:**
    ```bash
    kubectl wait --namespace ingress-nginx \
      --for=condition=ready pod \
      --selector=app.kubernetes.io/component=controller \
      --timeout=120s
    ```

4.  **Применить манифесты стека Nginx:**
    ```bash
    # Убедитесь, что файл nginx-stack.yaml находится в текущей директории
    kubectl apply -f nginx-stack.yaml
    ```

5.  **Проверить доступность через Ingress:**
    ```bash
    # Вы должны получить стандартное приветствие Nginx
    curl http://localhost:8080
    ```

6.  **(Опционально) Проверить работу PersistentVolume:*
    ```bash
    # Найти имя пода Nginx
    POD_NAME=$(kubectl get pods -l app=nginx -o jsonpath='{.items[0].metadata.name}')

    # Создать тестовый файл index.html внутри пода
    kubectl exec -it $POD_NAME -- bash -c 'echo "<h1>Hello from Persistent Volume!</h1>" > /usr/share/nginx/html/index.html'

    # Проверить снова. Теперь вы должны увидеть ваше сообщение.
    curl http://localhost:8080
    ```
