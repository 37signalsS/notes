# Minikube: практические сценарии

## Определения

**Minikube** — основной инструмент для локального запуска и управления однонодовым или многонодовым кластером **Kubernetes (K8s)**. Он автоматизирует создание среды (VM или контейнер) и первичную инициализацию компонентов Control Plane.

Подробные определения и описание архитектуры см. в **[Minikube: определения и концепции](./minikube_concepts.md)**.

---

## Базовые концепции

### Предварительные требования

Перед началом работы убедитесь, что система соответствует актуальным требованиям (на август 2026):

- **Аппаратные ресурсы:** минимум 2 ядра CPU и 4 ГБ RAM (рекомендуется 8 ГБ+). Подробнее см. в **[minikube_concepts.md](./minikube_concepts.md)**.
- **Драйвер:** на Linux и macOS рекомендуется использовать Docker.
- **Docker:** должен быть установлен из официальных репозиториев (не snap). См. **[Установка Docker на Ubuntu](../../../Docker/docker_install_ubuntu.md)**.

---

## Практические сценарии

### Установка Minikube

| ОС | Команда установки |
| :--- | :--- |
| **macOS (Homebrew)** | `brew install minikube` |
| **Linux (Binary)** | `curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64 && sudo install minikube-linux-amd64 /usr/local/bin/minikube` |
| **Windows (Chocolatey)** | `choco install minikube` |

**Проверка установки:** `minikube version`

---

### Запуск и базовая настройка

#### Запуск с параметрами по умолчанию
```bash
minikube start
```
При первом запуске Minikube автоматически выберет лучший доступный драйвер (обычно Docker) и скачает образ актуальной версии Kubernetes.

#### Настройка ресурсов и версии
Для специфических задач рекомендуется явно указывать ресурсы:
```bash
minikube start \
  --cpus=4 \
  --memory=8192mb \
  --disk-size=50g \
  --kubernetes-version=v1.36.0 \
  --container-runtime=containerd
```

#### Постоянная конфигурация
Чтобы не вводить параметры каждый раз, используйте `minikube config`:
```bash
# Установка драйвера по умолчанию
minikube config set driver docker

# Установка лимитов ресурсов
minikube config set cpus 4
minikube config set memory 8192
```

---

### Управление профилями (Profiles)

Профили позволяют запускать несколько изолированных кластеров.

```bash
# Запуск кластера для проекта "alpha"
minikube start -p alpha --nodes=2

# Переключение между профилями (изменение контекста kubectl)
minikube profile alpha

# Список всех профилей и их статус
minikube profile list
```

---

### Работа с сетью

#### Доступ к сервисам типа NodePort
```bash
# Экспонирование приложения
kubectl expose deployment my-app --type=NodePort --port=80

# Получение URL для доступа с хоста
minikube service my-app --url
```

#### Использование LoadBalancer (minikube tunnel)
Поскольку в локальной среде нет облачного балансировщика, внешний IP останется в состоянии `<pending>`. Для назначения IP запустите:
```bash
# Команда должна работать в отдельном терминале
minikube tunnel
```
После запуска туннеля `EXTERNAL-IP` в `kubectl get svc` сменится с `pending` на реальный IP (обычно `127.0.0.1` или IP из сети Docker).

#### Настройка Ingress
1.  Включите аддон: `minikube addons enable ingress`.
2.  Добавьте запись в `/etc/hosts`:
    ```text
    # IP можно узнать через minikube ip
    192.168.49.2  my-app.local
    ```
3.  Создайте ресурс Ingress, указывающий на ваш сервис.

#### Проброс портов (Port-forwarding)

Для временного доступа к поду или сервису без настройки Service/Ingress:

```bash
# Проброс порта 8080 локальной машины на порт 80 внутри пода
kubectl port-forward pod/my-pod 8080:80

# Проброс порта на Service (автоматический выбор активного пода)
kubectl port-forward svc/my-service 8080:80

# Проброс в фоновом режиме (с флагом --address для доступа извне localhost)
kubectl port-forward --address 0.0.0.0 svc/my-service 8080:80 &
```

> **Подробнее:** общий синтаксис и ограничения `kubectl port-forward` описаны в **[Port-forward к подам и сервисам](../../../Kubernetes/Base/Pod/pod_practical_scenarios_commands.md#проброс-портов-port-forward)**.

---

### Работа с образами и файлами

#### Использование локальных образов (без Push)
Самый эффективный способ разработки — использование демона Minikube:
```bash
# Настройка текущей сессии терминала
eval $(minikube docker-env)

# Теперь docker build соберет образ сразу ВНУТРИ Minikube
docker build -t local-image:latest .

# В манифесте пода укажите imagePullPolicy: Never
```

#### Копирование файлов в контейнер
```bash
# Копирование файла в узел Minikube
minikube cp ./config.yaml /home/docker/config.yaml

# Копирование из узла на хост
minikube cp minikube:/var/log/syslog ./local_syslog.log
```

#### Монтирование директорий (Mount)
Для работы с большими объемами данных или кодом в реальном времени:
```bash
minikube mount /Users/user/project:/data/project
```
> **Внимание:** Процесс `mount` должен быть активен (не закрывайте терминал).

---

### ConfigMaps и Secrets

#### ConfigMaps

ConfigMaps хранят конфигурационные данные в виде пар ключ-значение. Из них можно создавать переменные окружения или файлы для подов.

**Создание из литералов:**

```bash
kubectl create configmap app-config \
  --from-literal=DATABASE_HOST=mysql \
  --from-literal=DATABASE_PORT=3306

kubectl get configmap app-config -o yaml
# → apiVersion: v1
# → kind: ConfigMap
# → metadata:
# →   name: app-config
# → data:
# →   DATABASE_HOST: mysql
# →   DATABASE_PORT: "3306"
```

**Создание из файла:**

```bash
# Создание конфигурационного файла
cat > config.properties <<EOF
log_level=info
max_connections=100
timeout=30
EOF

kubectl create configmap app-config --from-file=config.properties
```

**Использование в поде (переменные окружения):**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-configmap
spec:
  containers:
  - name: app
    image: nginx:1.27
    envFrom:
    - configMapRef:
        name: app-config
```

**Использование в поде (монтирование как файл):**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-configmap-file
spec:
  containers:
  - name: app
    image: nginx:1.27
    volumeMounts:
    - name: config-volume
      mountPath: /etc/config
  volumes:
  - name: config-volume
    configMap:
      name: app-config
```

#### Secrets

Secrets хранят конфиденциальные данные (пароли, токены, сертификаты). По умолчанию кодируются в base64.

**Создание Secret:**

```bash
kubectl create secret generic db-secret \
  --from-literal=username=admin \
  --from-literal=password='S3cr3tP@ss'

kubectl get secret db-secret -o yaml
# → apiVersion: v1
# → kind: Secret
# → metadata:
# →   name: db-secret
# → type: Opaque
# → data:
# →   password: UzNjcjN0UEBzcw==
# →   username: YWRtaW4=
```

**Использование Secret в поде:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-secret
spec:
  containers:
  - name: app
    image: nginx:1.27
    env:
    - name: DB_USERNAME
      valueFrom:
        secretKeyRef:
          name: db-secret
          key: username
    - name: DB_PASSWORD
      valueFrom:
        secretKeyRef:
          name: db-secret
          key: password
```

> **Подробнее:** управление секретами в Kubernetes описано в **[Создание Secret](../../../Kubernetes/Base/secrets/creating_secrets.md)**.

---

### Persistent Volumes и Storage

Minikube включает **storage-provisioner** (включён по умолчанию), автоматически создающий `PersistentVolume` типа `hostPath` при запросе `PersistentVolumeClaim`.

#### Просмотр StorageClass

```bash
kubectl get storageclass
# → NAME                 PROVISIONER                RECLAIMPOLICY   VOLUMEBINDINGMODE   AGE
# → standard (default)   k8s.io/minikube-hostpath   Delete          Immediate           5m
```

#### Создание PVC и проверка привязки

```yaml
# my-pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-data-pvc
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
  storageClassName: standard
```

```bash
kubectl apply -f my-pvc.yaml
kubectl get pvc my-data-pvc
# → NAME          STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# → my-data-pvc   Bound    pvc-abc123def456                           1Gi        RWO            standard       10s

kubectl get pv
# → NAME                                       CAPACITY   ACCESS MODES   RECLAIMPOLICY   STATUS   CLAIM                   STORAGECLASS   AGE
# → pvc-abc123def456                           1Gi        RWO            Delete          Bound    default/my-data-pvc     standard       30s
```

#### Использование PVC в поде

```yaml
# app-with-pvc.yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-storage
spec:
  containers:
  - name: app
    image: nginx:1.27
    volumeMounts:
    - name: data-volume
      mountPath: /usr/share/nginx/html
  volumes:
  - name: data-volume
    persistentVolumeClaim:
      claimName: my-data-pvc
```

```bash
kubectl apply -f app-with-pvc.yaml

# Проверка, что том смонтирован
kubectl exec app-with-storage -- ls -la /usr/share/nginx/html

# Запись данных (данные сохраняются даже после удаления пода)
kubectl exec app-with-storage -- sh -c 'echo "Hello from PV" > /usr/share/nginx/html/index.html'
kubectl exec app-with-storage -- cat /usr/share/nginx/html/index.html
# → Hello from PV
```

> **Важно:** При `minikube delete` все PV и данные удаляются безвозвратно. Для сохранения данных используйте `minikube mount` или копирование файлов перед удалением.

**Подробнее о PV и PVC:** см. **[Persistent Volumes и Persistent Volume Claims](../../../Kubernetes/Storage/pv_and_pvc.md)**.

---

### Аддоны и расширения

| Задача | Команда |
| :--- | :--- |
| **Список всех аддонов** | `minikube addons list` |
| **Мониторинг ресурсов** | `minikube addons enable metrics-server` |
| **Веб-интерфейс** | `minikube dashboard` |
| **Локальный реестр** | `minikube addons enable registry` |
| **Service Mesh** | `minikube addons enable istio` |

---

### Развортывание тестового приложения (полный цикл)

Полный пример развертывания веб-приложения с конфигурацией, сервисом и Ingress.

#### Шаг 1: Создание ConfigMap

```bash
kubectl create configmap nginx-config --from-literal=index.html='<html><body><h1>Hello from Minikube!</h1></body></html>'
```

#### Шаг 2: Развертывание Deployment

```yaml
# nginx-deployment.yaml
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
        image: nginx:1.27
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 200m
            memory: 256Mi
        volumeMounts:
        - name: config-volume
          mountPath: /usr/share/nginx/html
      volumes:
      - name: config-volume
        configMap:
          name: nginx-config
```

```bash
kubectl apply -f nginx-deployment.yaml

# Ожидание готовности подов
kubectl rollout status deployment/nginx-deployment
# → deployment "nginx-deployment" successfully rolled out

# Проверка подов
kubectl get pods -l app=nginx
# → NAME                                READY   STATUS    RESTARTS   AGE
# → nginx-deployment-6d4f5c5x7b-abc12   1/1     Running   0          30s
# → nginx-deployment-6d4f5c5x7b-def34   1/1     Running   0          30s
```

#### Шаг 3: Создание Service

```yaml
# nginx-service.yaml
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
  type: NodePort
```

```bash
kubectl apply -f nginx-service.yaml

# Получение URL для доступа
minikube service nginx-service --url
# → http://192.168.49.2:31234
```

#### Шаг 4: Настройка Ingress

```bash
# Включение аддона Ingress
minikube addons enable ingress

# Создание Ingress-ресурса
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: nginx-ingress
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  rules:
  - host: nginx.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: nginx-service
            port:
              number: 80
EOF
```

```bash
# Добавление записи в /etc/hosts (или C:\Windows\System32\drivers\etc\hosts)
MINIKUBE_IP=$(minikube ip)
echo "$MINIKUBE_IP nginx.local" | sudo tee -a /etc/hosts

# Проверка доступности
curl http://nginx.local
# → <html><body><h1>Hello from Minikube!</h1></body></html>
```

#### Шаг 5: Обновление и откат

```bash
# Обновление образа (rolling update)
kubectl set image deployment/nginx-deployment nginx=nginx:1.28

# Наблюдение за процессом обновления
kubectl rollout status deployment/nginx-deployment

# Просмотр истории ревизий
kubectl rollout history deployment/nginx-deployment
# → REVISION  CHANGE-CAUSE
# → 1         <none>
# → 2         <none>

# Откат к предыдущей версии
kubectl rollout undo deployment/nginx-deployment

# Откат к конкретной ревизии
kubectl rollout undo deployment/nginx-deployment --to-revision=1
```

---

### Многонодовые конфигурации (Multi-node)

Для тестирования планирования (scheduling) и отказоустойчивости:
```bash
# Запуск с 3 узлами
minikube start --nodes=3

# Добавление узла в работающий кластер
minikube node add --worker

# Удаление конкретного узла
minikube node remove minikube-m02
```

---

### Обслуживание и отладка

#### Остановка и удаление
```bash
# Остановка (состояние сохраняется)
minikube stop

# Полное удаление (все данные и тома будут стерты)
minikube delete --all --purge
```

#### Диагностика
- **Статус компонентов:** `minikube status`.
- **Логи запуска:** `minikube logs`.
- **Вход в консоль узла:** `minikube ssh`.
- **Проверка встроенного kubectl:** `minikube kubectl -- get pods`.

#### Диагностика подов

**Просмотр детальной информации о поде:**

```bash
# Описание пода (события, условия, конфигурация)
kubectl describe pod <pod-name>

# Проверка событий (почему pod не запускается)
kubectl get events --sort-by='.lastTimestamp'
kubectl get events --field-selector reason=FailedScheduling
```

**Просмотр логов:**

```bash
# Логи конкретного пода
kubectl logs <pod-name>

# Логи с таймстемпами
kubectl logs <pod-name> --timestamps

# Последние N строк
kubectl logs <pod-name> --tail=100

# Следить за логами в реальном времени
kubectl logs <pod-name> -f

# Логи предыдущего контейнера (если под перезапускался)
kubectl logs <pod-name> --previous

# Логи всех подов с лейблом
kubectl logs -l app=nginx --all-containers

# Логи конкретного контейнера в multi-container поде
kubectl logs <pod-name> -c <container-name>
```

**Выполнение команд внутри пода:**

```bash
# Интерактивная сессия
kubectl exec -it <pod-name> -- /bin/bash

# Выполнение одной команды
kubectl exec <pod-name> -- cat /etc/resolv.conf

# Выполнение команды в конкретном контейнере
kubectl exec -it <pod-name> -c <container-name> -- /bin/sh
```

#### Мониторинг ресурсов

Для использования `kubectl top` необходимо включить аддон **metrics-server**:

```bash
minikube addons enable metrics-server

# Проверка использования ресурсов подами
kubectl top pods
# → NAME                                CPU(cores)   MEMORY(bytes)
# → nginx-deployment-6d4f5c5x7b-abc12   2m           5Mi
# → nginx-deployment-6d4f5c5x7b-def34   2m           5Mi

# Проверка использования ресурсов узлами
kubectl top nodes
# → NAME       CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# → minikube   150m         3%     1024Mi          12%

# Детальная информация по конкретному поду
kubectl top pod <pod-name> --containers
```

> **Подробнее:** мониторинг и метрики описаны в **[Minikube: определения и концепции](./minikube_concepts.md#мониторинг-и-логирование)**.

---

### Helm в Minikube

**Helm** — пакетный менеджер для Kubernetes, упрощающий развертывание и управление приложениями через Charts.

#### Установка Helm

```bash
# macOS
brew install helm

# Linux
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Проверка установки
helm version
# → version.BuildInfo{Version:"v3.16.0", ...}
```

#### Базовые команды Helm

```bash
# Добавление репозитория
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Поиск доступных Charts
helm search repo prometheus

# Установка Chart (например, NGINX Ingress Controller)
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace

# Проверка установленных релизов
helm list -A
# → NAME            NAMESPACE       REVISION   UPDATED                                  STATUS     CHART                  APP VERSION
# → ingress-nginx   ingress-nginx   1          2026-08-15 10:30:00.123456 +0300 MSK    deployed   ingress-nginx-4.11.0   1.11.0

# Просмотр параметров Chart
helm show values ingress-nginx/ingress-nginx

# Обновление релиза
helm upgrade ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --set controller.replicaCount=2

# Откат к предыдущей версии
helm rollback ingress-nginx 1 --namespace ingress-nginx

# Удаление релиза
helm uninstall ingress-nginx --namespace ingress-nginx
```

> **Подробнее:** обзор Helm и его концепции описаны в **[Helm: Обзор](../../../Kubernetes/ToolsUtilities/Helm/helm_overview.md)**.

---

### Namespace и изоляция

**Namespace** — виртуальное разделение кластера, позволяющее изолировать ресурсы по группам (проекты, команды, окружения).

#### Управление Namespace

```bash
# Список всех Namespace
kubectl get namespaces
# → NAME              STATUS   AGE
# → default           Active   5m
# → kube-system       Active   5m
# → kube-public       Active   5m

# Создание нового Namespace
kubectl create namespace dev

# Создание из манифеста
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: staging
  labels:
    env: staging
EOF
```

#### Работа с Namespace

```bash
# Развертывание ресурса в конкретный Namespace
kubectl apply -f deployment.yaml -n dev

# Просмотр ресурсов в Namespace
kubectl get pods -n dev
kubectl get all -n kube-system

# Переключение контекста на Namespace (по умолчанию для всех команд)
kubectl config set-context --current --namespace=dev

# Проверка текущего Namespace
kubectl config view --minify | grep namespace
# →     namespace: dev
```

#### Изоляция ресурсов

```yaml
# LimitRange — ограничение ресурсов для подов в Namespace
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: dev
spec:
  limits:
  - default:
      cpu: 500m
      memory: 256Mi
    defaultRequest:
      cpu: 100m
      memory: 128Mi
    type: Container
```

```yaml
# ResourceQuota — общий лимит ресурсов для Namespace
apiVersion: v1
kind: ResourceQuota
metadata:
  name: dev-quota
  namespace: dev
spec:
  hard:
    requests.cpu: "4"
    requests.memory: 8Gi
    limits.cpu: "8"
    limits.memory: 16Gi
    pods: "20"
```

---

### Типичные ошибки и решения

| Проблема | Решение |
| :--- | :--- |
| **The "docker" driver should not be used with root privileges** | Не запускайте `minikube start` через `sudo`. Используйте обычного пользователя, состоящего в группе `docker`. |
| **Exiting due to GUEST_MISSING_CONN_TRACK** | Необходима установка `conntrack` на хосте (актуально для драйвера `none`). |
| **ImagePullBackOff** | Проверьте `imagePullPolicy`. Если используете `docker-env`, установите `Never`. |
| **Tunnels not working on macOS** | Убедитесь, что у `minikube tunnel` есть права администратора (запросит пароль). |
| **Insufficient memory** | Minikube требует минимум 2ГБ для K8s, но для аддонов (Istio, Ingress) нужно 8ГБ+. |
| **Pod stuck in Pending** | Проверьте ресурсы узла: `kubectl describe node minikube`. Увеличьте лимиты через `minikube start --memory --cpus`. |
| **kubectl: connection refused** | Minikube остановлен или не запущен. Выполните `minikube start` и проверьте контекст: `kubectl config current-context`. |
| **Error from server (NotFound)** | Ресурс не существует или находится в другом namespace. Проверьте: `kubectl get <resource> -A`. |

---

## Дополнительная информация

### См. также
- **[Minikube: определения и концепции](./minikube_concepts.md)** — архитектура, драйверы и теория.
- **[kubectl: установка](../kubectl_installation.md)** — подготовка основного инструмента управления.
- **[Persistent Volumes и Persistent Volume Claims](../../../Kubernetes/Storage/pv_and_pvc.md)** — управление хранилищем в Kubernetes.
- **[Helm: Обзор](../../../Kubernetes/ToolsUtilities/Helm/helm_overview.md)** — пакетный менеджер для Kubernetes.

### Полезные ссылки
- **Примеры манифестов:** [GitHub minikube/examples](https://github.com/kubernetes/minikube/tree/master/examples)
- **Troubleshooting guide:** [Official Docs](https://minikube.sigs.k8s.io/docs/handbook/debugging/)
