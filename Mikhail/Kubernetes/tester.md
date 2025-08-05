# Развертывание Nginx в kind: полный и современный пример

Этот документ представляет собой полное пошаговое руководство по развертыванию веб-сервера Nginx в локальном Kubernetes-кластере, созданном с помощью `kind`. Манифесты демонстрируют совместное использование ключевых объектов Kubernetes и соответствуют современным практикам.

**Рассматриваемые объекты:**
*   `Deployment` для управления подами приложения.
*   `Service` для организации сетевого взаимодействия.
*   `Ingress` для предоставления доступа к приложению извне.
*   `ConfigMap` для инъекции конфигурационных файлов.
*   `PersistentVolumeClaim` для обеспечения постоянного хранения данных.

---

### 1. Конфигурация кластера `kind`

Сначала подготовим конфигурационный файл для `kind`, который создаст кластер с одним control-plane и двумя рабочими узлами. Мы также настроим проброс портов для Ingress-контроллера.

```yaml
# kind-config.yaml
apiVersion: kind.x-k8s.io/v1alpha4
kind: Cluster
nodes:
- role: control-plane
  # NOTE: Эта метка необходима для того, чтобы Ingress-контроллер мог корректно
  # размещаться на узлах control-plane в кластерах kind.
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        node-labels: "ingress-ready=true"
  # NOTE: Проброс портов с хост-машины в контейнер control-plane.
  # Позволяет получить доступ к Ingress-контроллеру извне кластера.
  extraPortMappings:
  - containerPort: 80
    hostPort: 80
    protocol: TCP
  - containerPort: 443
    hostPort: 443
    protocol: TCP
- role: worker
- role: worker
```

---

### 2. Манифесты Kubernetes

Все ресурсы для развертывания Nginx собраны в один файл `nginx-stack.yaml`. Ресурсы разделены с помощью `---` и снабжены комментариями.

```yaml
# nginx-stack.yaml

# --- ConfigMap для конфигурации Nginx ---
apiVersion: v1
kind: ConfigMap
metadata:
  name: nginx-config
  labels:
    app.kubernetes.io/name: nginx
    app.kubernetes.io/instance: my-nginx
data:
  # NOTE: Конфигурация Nginx по умолчанию. Может быть легко расширена.
  default.conf: |
    server {
        listen 80;
        server_name _;
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
  labels:
    app.kubernetes.io/name: nginx
    app.kubernetes.io/instance: my-nginx
spec:
  accessModes:
    # ReadWriteOnce означает, что том может быть смонтирован для чтения/записи только одним узлом.
    - ReadWriteOnce
  # NOTE: kind автоматически создает StorageClass с именем "standard".
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
    app.kubernetes.io/instance: my-nginx
spec:
  # NOTE: Установлена 1 реплика, т.к. PVC (ReadWriteOnce) может быть использован только одним подом.
  # Для масштабирования приложений с состоянием рекомендуется использовать StatefulSet.
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: nginx
      app.kubernetes.io/instance: my-nginx
  template:
    metadata:
      labels:
        app.kubernetes.io/name: nginx
        app.kubernetes.io/instance: my-nginx
    spec:
      containers:
        - name: nginx
          image: nginx:1.25.4 # Лучшая практика - использовать фиксированный тег образа.
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 80
          # NOTE: Probes — критически важный механизм для автоматического контроля состояния приложения.
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
          # NOTE: Requests и Limits гарантируют качество обслуживания (QoS) и стабильность кластера.
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
# --- Service (ClusterIP) для внутренней коммуникации ---
apiVersion: v1
kind: Service
metadata:
  name: nginx-service
  labels:
    app.kubernetes.io/name: nginx
    app.kubernetes.io/instance: my-nginx
spec:
  selector:
    app.kubernetes.io/name: nginx
    app.kubernetes.io/instance: my-nginx
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
  labels:
    app.kubernetes.io/name: nginx
    app.kubernetes.io/instance: my-nginx
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
    # NOTE(AI): Для production следует использовать более строгие политики, например, redirect-to-https
    nginx.ingress.kubernetes.io/ssl-redirect: "false"
spec:
  # NOTE: Указание ingressClassName является современной практикой.
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
    kind create cluster --config=kind-config.yaml --name nginx-test
    ```

2.  **Развернуть Ingress-контроллер NGINX для `kind`:**
    ```bash
    kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
    ```

3.  **Дождаться готовности Ingress-контроллера:**
    ```bash
    echo "⏳ Waiting for Ingress controller to be ready..."
    kubectl wait --namespace ingress-nginx \
      --for=condition=ready pod \
      --selector=app.kubernetes.io/component=controller \
      --timeout=120s
    echo "✅ Ingress controller is ready!"
    ```

4.  **Применить манифесты стека Nginx:**
    ```bash
    # Убедитесь, что файл nginx-stack.yaml находится в текущей директории
    kubectl apply -f nginx-stack.yaml
    ```

5.  **Проверить доступность через Ingress:**
    ```bash
    echo "⏳ Waiting for Nginx deployment to be available..."
    kubectl wait --for=condition=available deployment/nginx-deployment --timeout=60s
    echo "✅ Nginx is deployed!"

    # Вы должны получить стандартное приветствие Nginx
    curl http://localhost
    ```

6.  **(Опционально) Проверить работу PersistentVolume:*
    ```bash
    # Найти имя пода Nginx
    POD_NAME=$(kubectl get pods -l app.kubernetes.io/name=nginx -o jsonpath='{.items[0].metadata.name}')

    # Создать тестовый файл index.html внутри пода
    kubectl exec -it $POD_NAME -- bash -c 'echo "<h1>Hello from Persistent Volume!</h1>" > /usr/share/nginx/html/index.html'

    # Проверить снова. Теперь вы должны увидеть ваше сообщение.
    curl http://localhost
    ```

### 4. Очистка

Чтобы удалить все созданные ресурсы и кластер:
```bash
kind delete cluster --name nginx-test
```