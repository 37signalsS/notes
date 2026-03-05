# Проверка работоспособности HA кластера Kubernetes

## Определения

**Cluster Verification** — процесс проверки корректности установки и функционирования всех компонентов кластера Kubernetes после развёртывания.

**Control Plane** — плоскость управления: `etcd`, `kube-apiserver`, `kube-controller-manager`, `kube-scheduler`.

**CNI (Container Network Interface)** — плагин сетевой связности подов между узлами.

**NodePort** — тип Service для доступа к подам извне кластера через порт на каждом узле.

---

## Основные концепции

### Уровни проверки

1. **Базовая проверка** — узлы и системные поды
2. **Функциональная проверка** — развёртывание тестового приложения
3. **HA проверка** — отказоустойчивость Control Plane
4. **Сетевая проверка** — связность подов и сервисов

### Критерии успешной проверки

- Все узлы в статусе `Ready`
- Все системные поды в статусе `Running`
- Тестовое приложение доступно через NodePort
- VIP мигрирует при отказе мастера

---

## Практические сценарии

### Шаг 1: Базовая проверка кластера

```bash
# Проверка состояния узлов (все должны быть Ready)
kubectl get nodes

# Ожидаемый вывод:
# NAME         STATUS   ROLES           AGE   VERSION
# master-1     Ready    control-plane   10m   v1.34.0
# master-2     Ready    control-plane   8m    v1.34.0
# master-3     Ready    control-plane   7m    v1.34.0
# worker-1     Ready    <none>          5m    v1.34.0
# worker-2     Ready    <none>          5m    v1.34.0

# Проверка системных подов
kubectl get pods -n kube-system

# Ожидаемый статус: все поды Running
# calico-node-xxxxx          1/1     Running
# coreDNS-xxxxxxxxxx         1/1     Running
# etcd-master-1              1/1     Running
# kube-apiserver-master-1    1/1     Running
# kube-controller-manager    1/1     Running
# kube-proxy-xxxxx           1/1     Running
# kube-scheduler             1/1     Running
```

### Шаг 2: Проверка компонентов Control Plane

```bash
# Проверка подов etcd (должно быть 3 для HA)
kubectl get pods -n kube-system -l component=etcd

# Проверка подов kube-apiserver
kubectl get pods -n kube-system -l component=kube-apiserver

# Проверка kube-controller-manager
kubectl get pods -n kube-system -l component=kube-controller-manager

# Проверка kube-scheduler
kubectl get pods -n kube-system -l component=kube-scheduler

# Проверка CNI подов (Calico пример)
kubectl get pods -n kube-system -l k8s-app=calico-node
```

### Шаг 3: Развёртывание тестового приложения

#### Создание манифеста

```yaml
# nginx-test.yaml
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
        resources:
          requests:
            memory: "64Mi"
            cpu: "100m"
          limits:
            memory: "128Mi"
            cpu: "200m"
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

#### Применение и проверка

```bash
# Применить манифест
kubectl apply -f nginx-test.yaml

# Проверка Deployment
kubectl get deployment nginx-deployment

# Проверка Pod
kubectl get pods -l app=nginx

# Проверка Service (узнать NodePort)
kubectl get service nginx-service

# Ожидаемый вывод:
# NAME            TYPE       CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
# nginx-service   NodePort   10.96.xxx.xxx   <none>        80:3xxxx/TCP   1m
```

#### Доступ к приложению

```bash
# Узнать NodePort (порт вида 3xxxx)
NODE_PORT=$(kubectl get service nginx-service -o jsonpath='{.spec.ports[0].nodePort}')

# Проверить доступ через любого воркера
WORKER_IP="<IP-любого-воркера>"
curl http://${WORKER_IP}:${NODE_PORT}

# Ожидаемый ответ: HTML-страница Nginx
```

### Шаг 4: Проверка отказоустойчивости (HA Verification)

#### Проверка VIP (Keepalived)

```bash
# На любом мастер-узле: проверить наличие VIP
ip a | grep <VIP_ADDRESS>

# Остановить keepalived на текущем MASTER
sudo systemctl stop keepalived

# VIP должен мигрировать на другой узел
# Проверить на резервном мастере:
ip a | grep <VIP_ADDRESS>
```

#### Проверка доступности API при отказе мастера

```bash
# Во время отказа одного мастера проверить доступность API
kubectl get nodes
kubectl get pods -n kube-system

# Все команды должны выполняться без ошибок
# API доступен через балансировщик (VIP)
```

#### Проверка etcd кворума

```bash
# Проверка статуса etcd кластера
# Выполняется на любом мастере с доступом к etcd
ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key \
  endpoint status -w=table

# Ожидаемый результат: 3 из 3 узлов здоровы
```

### Шаг 5: Проверка сетевой связности

```bash
# Создать тестовый под для проверки сети
kubectl run test-pod --image=busybox --rm -it --restart=Never -- ping -c 4 kubernetes.default

# Проверка DNS разрешения
kubectl run test-dns --image=busybox --rm -it --restart=Never -- nslookup kubernetes.default

# Проверка связности между подами
kubectl run test-curl --image=curlimages/curl --rm -it --restart=Never -- \
  curl http://nginx-service.default.svc.cluster.local
```

---

## Дополнительная информация

### Чек-лист успешной проверки

- [ ] Все узлы в статусе `Ready`
- [ ] Все системные поды в статусе `Running`
- [ ] 3 мастера (etcd, apiserver) работают
- [ ] CNI поды активны
- [ ] Тестовое приложение доступно через NodePort
- [ ] VIP мигрирует при отказе мастера
- [ ] API доступен после отказа мастера
- [ ] etcd сохраняет кворум

### Troubleshooting

#### Узлы не Ready

```bash
# Проверка статуса kubelet
sudo systemctl status kubelet

# Проверка логов kubelet
sudo journalctl -u kubelet -f

# Проверка конфигурации kubelet
cat /var/lib/kubelet/config.yaml
```

#### Поды не запускаются

```bash
# Описание пода с ошибками
kubectl describe pod -n kube-system <pod-name>

# Проверка логов
kubectl logs -n kube-system <pod-name>

# Проверка событий кластера
kubectl get events --sort-by='.lastTimestamp'
```

#### CNI не работает

```bash
# Проверка подов CNI
kubectl get pods -n kube-system -l k8s-app=calico-node

# Пересоздание подов CNI
kubectl delete pod -n kube-system -l k8s-app=calico-node

# Проверка логов Calico
kubectl logs -n kube-system -l k8s-app=calico-node
```

### Связанные документы

- **Обзор HA**: [HA Cluster Overview](./k8s_ha_cluster_overview.md)
- **Control Plane**: [Control Plane & CNI](./k8s_ha_control_plane_and_cni.md)
- **High Availability**: [HA Overview](../../../Concepts/High_Availability/ha_overview.md)
- **Troubleshooting**: [Common Errors](../../Troubleshooting/Common_Errors/overview.md)
- **Monitoring**: [Prometheus](../../Prometheus/prometheus_overview.md)

### Надежность

| Раздел | Confidence |
| :--- | :--- |
| Базовая проверка | Этот файл | 10 |
| Проверка HA | Этот файл + [kubeadm_ha_with_keepalived_haproxy.md](../kudeadm/kubeadm_ha_with_keepalived_haproxy.md) | 10 |
| Проверка etcd | [etcd_overview.md](../../Concepts/etcd_overview.md) | 10 |
| Сетевая проверка | [CNI Overview](../../Networking/Network/cni_overview.md) | 10 |
