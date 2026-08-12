# Проверка работоспособности HA кластера Kubernetes

## Определения

**Верификация кластера (Cluster Verification)** — процесс комплексного тестирования всех подсистем Kubernetes (API, ETCD, CNI, DNS, Storage) после развертывания для подтверждения их готовности к промышленной эксплуатации.

**Control Plane HA** — конфигурация плоскости управления с избыточностью, где компоненты (apiserver, scheduler, controller-manager) запущены на нескольких узлах за балансировщиком нагрузки.

**CNI (Container Network Interface)** — сетевой плагин (Calico, Cilium, Flannel), отвечающий за выделение IP-адресов подам и обеспечение связности между ними.

**NodePort** — тип сервиса Kubernetes, открывающий определенный порт (30000–32767) на всех узлах кластера для внешнего доступа к приложению.

**IPVS (IP Virtual Server)** — высокопроизводительный транспортный балансировщик ядра Linux, рекомендуемый режим для `kube-proxy` в больших или высоконагруженных кластерах.

---

## Основные концепции

### Многоуровневая модель тестирования

Для Bare Metal HA кластера проверка не может ограничиваться командой `kubectl get nodes`. Необходимо пройти по всем уровням:

1.  **Слой инфраструктуры**: Проверка миграции Virtual IP (VIP) и работы локальных балансировщиков.
2.  **Слой хранения (Stateful)**: Проверка целостности и кворума `etcd`.
3.  **Слой управления (Control Plane)**: Проверка доступности API через VIP и индивидуальные эндпоинты.
4.  **Сетевой слой (L3/L4)**: Проверка инкапсуляции (VXLAN/IPIP), политик и DNS.
5.  **Слой ресурсов**: Валидация работы Metrics Server и планировщика (Scheduler).

### Критерии успешного прохождения (Health Check)

*   **Узлы**: Все узлы в статусе `Ready`. Версии `kubelet` и `containerd` соответствуют целевым.
*   **Системные компоненты**: Все статические поды (etcd, apiserver) и DaemonSets (kube-proxy, CNI) запущены.
*   **Отказоустойчивость**: Кластер сохраняет работоспособность при потере `(N-1)/2` узлов мастера.
*   **Связность**: Поды на разных узлах пингуют друг друга по IP и доменным именам.

---

## Практические сценарии

### Шаг 1: Базовая диагностика инфраструктуры

```bash
# 1. Проверка состояния узлов с расширенной информацией
kubectl get nodes -o wide

# Ожидаемый вывод (версия v1.35.x):
# NAME       STATUS   ROLES           AGE   VERSION   INTERNAL-IP    OS-IMAGE             KERNEL-VERSION
# master-1   Ready    control-plane   10m   v1.35.0   10.0.0.11      Ubuntu 24.04 LTS     6.8.0-xx
# master-2   Ready    control-plane   8m    v1.35.0   10.0.0.12      Ubuntu 24.04 LTS     6.8.0-xx
# master-3   Ready    control-plane   7m    v1.35.0   10.0.0.13      Ubuntu 24.04 LTS     6.8.0-xx
# worker-1   Ready    <none>          5m    v1.35.0   10.0.0.21      Ubuntu 24.04 LTS     6.8.0-xx

# 2. Проверка системных подов во всех пространствах имен
kubectl get pods -A -o wide | grep -v Running
# → Результат должен быть пустым (все в Running/Completed)

# 3. Проверка событий кластера на предмет ошибок
kubectl get events -A --sort-by='.lastTimestamp' | tail -n 20
```

### Шаг 2: Глубокая проверка etcd и кворума

Для HA-кластера состояние etcd является критическим фактором. Проверку нужно выполнять с использованием сертификатов.

```bash
# Определение псевдонима для удобства (выполнять на мастере)
export ETCDCTL_API=3
alias k-etcdctl='etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key'

# 1. Проверка статуса эндпоинтов (сверка ревизий)
sudo k-etcdctl endpoint status -w table

# Критично: RAFT TERM должен быть одинаковым, REVISION не должен сильно расходиться.

# 2. Проверка здоровья участников
sudo k-etcdctl endpoint health -w table

# 3. Проверка списка участников
sudo k-etcdctl member list -w table
```

### Шаг 3: Верификация IPVS и Kube-Proxy

Если кластер настроен в режиме IPVS, необходимо убедиться, что правила создаются корректно.

```bash
# Проверка режима работы kube-proxy в ConfigMap
kubectl describe configmap -n kube-system kube-proxy | grep mode
# → mode: "ipvs"

# Проверка виртуальных серверов на узле (требуется пакет ipvsadm)
sudo ipvsadm -Ln

# Ожидаемый вывод содержит VIP API-сервера и ClusterIP сервисов:
# Prot LocalAddress:Port Scheduler Flags
#   -> RemoteAddress:Port           Forward Weight ActiveConn InActConn
# TCP  10.96.0.1:443 rr
#   -> 10.0.0.11:6443               Masq    1      0          0
#   -> 10.0.0.12:6443               Masq    1      0          0
#   -> 10.0.0.13:6443               Masq    1      0          0
```

### Шаг 4: Развертывание и проверка тестового приложения

Создаем полноценное приложение с проверками готовности (probes) для тестирования планировщика и сети.

#### Создание манифеста `verification-app.yaml`
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: k8s-verify
  namespace: default
spec:
  replicas: 3
  selector:
    matchLabels:
      app: k8s-verify
  template:
    metadata:
      labels:
        app: k8s-verify
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
              - key: app
                operator: In
                values:
                - k8s-verify
            topologyKey: "kubernetes.io/hostname"
      containers:
      - name: nginx
        image: nginx:1.27-alpine
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 200m
            memory: 256Mi
        livenessProbe:
          httpGet:
            path: /
            port: 80
          initialDelaySeconds: 5
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /
            port: 80
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: k8s-verify-svc
spec:
  type: NodePort
  selector:
    app: k8s-verify
  ports:
    - protocol: TCP
      port: 80
      targetPort: 80
      nodePort: 30080
```

#### Применение и тестирование доступа
```bash
# Применить манифест
kubectl apply -f verification-app.yaml

# Подождать запуск (все 3 реплики на разных узлах из-за AntiAffinity)
kubectl get pods -o wide -l app=k8s-verify

# Проверка доступа через NodePort на всех узлах по очереди
for IP in 10.0.0.21 10.0.0.22 10.0.0.11; do
  curl -s -o /dev/null -w "%{http_code} от $IP\n" http://$IP:30080
done
# → Ожидается: 200 от каждого IP
```

### Шаг 5: Проверка сетевой изоляции и DNS

```bash
# 1. Проверка CoreDNS (разрешение имен)
kubectl run dns-test --image=busybox:1.36 --restart=Never --rm -it -- nslookup kubernetes.default
# → Должен вернуть IP 10.96.0.1

# 2. Проверка связности между подами (Pod-to-Pod)
POD_IP=$(kubectl get pods -l app=k8s-verify -o jsonpath='{.items[0].status.podIP}')
kubectl run ping-test --image=busybox:1.36 --restart=Never --rm -it -- ping -c 3 $POD_IP

# 3. Проверка Metrics Server (если установлен)
kubectl top nodes
kubectl top pods -A
```

### Шаг 6: Тестирование HA и Failover (Критический этап)

#### Тест 1: Переключение VIP API-сервера
1.  Найдите узел-владелец VIP: `ip a | grep <VIP_ADDRESS>`
2.  Запустите непрерывный опрос API с внешней машины:
    ```bash
    while true; do kubectl get nodes > /dev/null && echo -n "." || echo -n "X"; sleep 1; done
    ```
3.  Остановите Keepalived на мастере-владельце: `sudo systemctl stop keepalived`
4.  **Результат**: Допускается 1-2 секунды задержки ("X"), после чего точки (".") должны возобновиться. VIP должен появиться на другом мастере.

#### Тест 2: Изоляция мастера (Split-brain check)
1.  Отключите сеть на одном из мастеров (или выключите его).
2.  Проверьте статус кластера etcd: `sudo k-etcdctl member list`. Узел должен быть `unreachable`.
3.  Убедитесь, что планировщик продолжает работать: удалите один под тестового приложения, он должен пересоздаться на другом узле.

---

## Дополнительная информация

### Чек-лист готовности к Production

- [ ] Все узлы `Ready`, время синхронизировано через `chrony`.
- [ ] `etcd` имеет 3 здоровых эндпоинта, разница в ревизиях < 1000.
- [ ] CoreDNS имеет минимум 2 реплики, развернутые на разных узлах.
- [ ] API-сервер доступен через VIP, балансировка HAProxy работает (проверить статистику на порту 9000, если включено).
- [ ] Подсеть подов (Pod CIDR) не пересекается с физической сетью.
- [ ] Логирование `kubelet` настроено без переполнения диска.

### Troubleshooting (Поиск и устранение неисправностей)

#### Проблема: Поды CoreDNS в статусе CrashLoopBackOff
**Причина**: Часто связано с зацикливанием DNS (loop). CoreDNS обнаруживает, что вышестоящий DNS — это он сам.
**Решение**: Проверьте `/etc/resolv.conf` на узлах. Если там указан `127.0.0.53`, настройте CoreDNS на использование другого upstream DNS (например, 8.8.8.8) через `kubectl edit configmap -n kube-system coredns`.
**Подробнее**: См. SSoT-файл **[Петли перенаправления DNS](../../../Networking/Protocols/DNS/dns_forwarding_loops.md)**.

#### Проблема: Error from server (Forbidden) при `kubectl top`
**Причина**: Metrics Server не может авторизоваться в Kubelet из-за сертификатов.
**Решение**: Добавьте в аргументы запуска Metrics Server:
`--kubelet-insecure-tls` и `--kubelet-preferred-address-types=InternalIP`.

### Интеграция с документацией

Данный файл завершает цикл установки HA кластера.
- Предыдущий этап: **[Присоединение узлов](./node_joining.md)**
- Теория отказоустойчивости: **[HA Concepts](../kubeadm/ha_concepts.md)**
- Диагностика сети: **[Network Troubleshooting](../../Networking/Network/network_troubleshooting.md)**
- Резервное копирование etcd: **[etcd Backup and Restore](../../Operations/etcd_backup_restore.md)**
