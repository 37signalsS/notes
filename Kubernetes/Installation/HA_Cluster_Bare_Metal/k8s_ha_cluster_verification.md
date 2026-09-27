# Проверка работоспособности HA кластера Kubernetes

## Определения

**Верификация кластера (Cluster Verification)** — процесс комплексного тестирования всех подсистем Kubernetes (API, etcd, CNI, DNS, Storage) после развертывания для подтверждения их готовности к промышленной эксплуатации.

**Control Plane HA** — конфигурация плоскости управления с избыточностью, где компоненты (apiserver, scheduler, controller-manager) запущены на нескольких узлах за балансировщиком нагрузки.

**CNI (Container Network Interface)** — сетевой плагин (Calico, Cilium, Flannel), отвечающий за выделение IP-адресов подам и обеспечение связности между ними.

**NodePort** — тип сервиса Kubernetes, открывающий определенный порт (30000–32767) на всех узлах кластера для внешнего доступа к приложению.

**IPVS (IP Virtual Server)** — высокопроизводительный транспортный балансировщик ядра Linux, рекомендуемый режим для `kube-proxy` в больших или высоконагруженных кластерах.

**Gratuitous ARP** — механизм уведомления сетевого оборудования о перемещении VIP на другой MAC-адрес. Используется Keepalived для обновления ARP-таблиц при failover.

**Split-Brain** — ситуация, при которой два узла кластера считают себя лидерами одновременно, что может привести к конфликтам записи данных. В Kubernetes предотвращается механизмом кворума etcd и настройками VRRP (nopreempt).

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

### Порядок верификации

Рекомендуемая последовательность проверок — от инфраструктуры к приложениям:

```
Инфраструктура → etcd → API → Сеть → DNS → Приложения → Failover-тесты
```

Каждый слой должен быть проверен до перехода к следующему. Это позволяет локализовать проблему на раннем этапе.

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

# 4. Проверка версий компонентов
kubectl version
# → Client Version и Server Version должны совпадать (допустимо ±1 минорная версия для kubectl)

kubectl get nodes -o custom-columns=NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion,OS:.status.nodeInfo.osImage,CR:.status.nodeInfo.containerRuntimeVersion
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
# → ENDPOINT              ID        VERSION   DB SIZE   IS LEADER   RAFT TERM   REVISION
# → https://127.0.0.1:2379  8e9a3...  3.5.12    45 MB     true        3           123456

# 2. Проверка здоровья участников
sudo k-etcdctl endpoint health -w table
# → Все эндпоинты должны быть Healthy

# 3. Проверка списка участников
sudo k-etcdctl member list -w table
# → Должно быть 3 участника для кворума 2
```

**Критерии здоровья etcd:**
- Все эндпоинты `Healthy`
- `RAFT TERM` одинаковый на всех узлах
- Разница `REVISION` между узлами не должна превышать 1000 (признак отставания репликации)
- `DB SIZE` должен быть примерно одинаковым

Подробнее об архитектуре etcd и операциях с ним: **[etcd — распределенное хранилище](../../Concepts/etcd_overview.md)**.

### Шаг 3: Верификация API-сервера и Control Plane

```bash
# 1. Проверка health-эндпоинтов API-сервера
kubectl get --raw='/livez?verbose'
# → [+]ok
# →[+]log
# →[+]ping

kubectl get --raw='/readyz?verbose'
# → [+]ok
# →[+]log
# →[+]ping

# 2. Проверка доступности API через VIP и индивидуальные эндпоинты
for ip in 10.0.0.11 10.0.0.12 10.0.0.13; do
  curl -k https://$ip:6443/readyz && echo "  <- $ip ok"
done
# → ok  <- 10.0.0.11 ok
# → ok  <- 10.0.0.12 ok
# → ok  <- 10.0.0.13 ok

# 3. Проверка лидерства scheduler и controller-manager (Lease)
kubectl get lease -n kube-system
# → NAME                      HOLDER             AGE
# → kube-controller-manager   master-1_xxx       10m
# → kube-scheduler            master-2_xxx       10m
# → holderIdentity показывает, какой экземпляр сейчас лидер

# 4. Проверка сертификатов
kubeadm certs check-expiration
# → Все сертификаты должны иметь срок действия > 30 дней
```

Подробнее об архитектуре Control Plane: **[Архитектура Control Plane](../../Concepts/control_plane_architecture.md)**.

### Шаг 4: Верификация IPVS и Kube-Proxy

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

# Проверка что kube-proxy работает на всех узлаh
kubectl get pods -n kube-system -l k8s-app=kube-proxy -o wide
# → Все поды должны быть Running и распределены по всем узлам
```

### Шаг 5: Развертывание и проверка тестового приложения

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
# → Проверить что поды распределены по разным узлам (NODE)

# Проверка доступа через NodePort на всех узлах по очереди
for IP in 10.0.0.21 10.0.0.22 10.0.0.11; do
  curl -s -o /dev/null -w "%{http_code} от $IP\n" http://$IP:30080
done
# → Ожидается: 200 от каждого IP

# Проверка доступа через ClusterIP
kubectl run curl-test --image=curlimages/curl:latest --restart=Never --rm -it -- \
  curl -s -o /dev/null -w "%{http_code}\n" http://k8s-verify-svc.default.svc.cluster.local
# → 200
```

### Шаг 6: Проверка сетевой изоляции и DNS

```bash
# 1. Проверка CoreDNS (разрешение имен)
kubectl run dns-test --image=busybox:1.36 --restart=Never --rm -it -- nslookup kubernetes.default
# → Должен вернуть IP 10.96.0.1

# 2. Проверка связности между подами (Pod-to-Pod)
POD_IP=$(kubectl get pods -l app=k8s-verify -o jsonpath='{.items[0].status.podIP}')
kubectl run ping-test --image=busybox:1.36 --restart=Never --rm -it -- ping -c 3 $POD_IP
# → Должен быть успешный ping

# 3. Проверка кросс-неймспейсов DNS
kubectl run dns-test2 --image=busybox:1.36 --restart=Never --rm -it -- \
  nslookup k8s-verify-svc.default.svc.cluster.local
# → Должен вернуть ClusterIP сервиса

# 4. Проверка Metrics Server (если установлен)
kubectl top nodes
# → Показания CPU и Memory для всех узлов

kubectl top pods -A
# → Показания для всех подов
```

### Шаг 7: Тестирование HA и Failover (Критический этап)

#### Тест 1: Переключение VIP API-сервера

```bash
# 1. Определение узла-владельца VIP
ip a | grep <VIP_ADDRESS>
# → inet 192.168.1.100/32 scope global eth0

# 2. Запуск непрерывного опроса API с внешней машины
while true; do kubectl get nodes > /dev/null && echo -n "." || echo -n "X"; sleep 1; done

# 3. Остановка Keepalived на мастере-владельце
sudo systemctl stop keepalived

# 4. Результат: Допускается 1-2 секунды задержки ("X"), после чего точки (".") должны возобновиться.
# VIP должен появиться на другом мастере.
```

#### Тест 2: Изоляция мастера (Split-brain check)

```bash
# 1. Отключите сеть на одном из мастеров (или выключите его)
# 2. Проверьте статус кластера etcd
sudo k-etcdctl member list -w table
# → Узел должен быть unreachable

# 3. Убедитесь, что планировщик продолжает работать
kubectl delete pod -l app=k8s-verify
kubectl get pods -l app=k8s-verify -w
# → Поды должны пересоздаться на других узлах
```

#### Тест 3: Проверка Gratuitous ARP (опционально)

```bash
# На узле, где запущен tcpdump
sudo tcpdump -i eth0 -n arp
# → При failover должны появиться Gratuitous ARP пакеты
# → arp who-has 192.168.1.100 tell 192.168.1.11
```

Подробнее о настройке Keepalived и HAProxy: **[HA API-сервера с Keepalived и HAProxy](../kubeadm/ha_concepts.md)**.

---

## Дополнительная информация

### Чек-лист готовности к Production

- [ ] Все узлы `Ready`, время синхронизировано через `chrony`.
- [ ] `etcd` имеет 3 здоровых эндпоинта, разница в ревизиях < 1000.
- [ ] CoreDNS имеет минимум 2 реплики, развернутые на разных узлах.
- [ ] API-сервер доступен через VIP, балансировка HAProxy работает (проверить статистику на порту 9000, если включено).
- [ ] Подсеть подов (Pod CIDR) не пересекается с физической сетью.
- [ ] Логирование `kubelet` настроено без переполнения диска.
- [ ] Сертификаты имеют срок действия > 30 дней.
- [ ] IPVS правила создаются корректно (при использовании режима IPVS).
- [ ] Тестовое приложение успешно проходит все проверки доступности.
- [ ] Failover-тесты пройдены успешно (VIP мигрирует, поды пересоздаются).

**Day-2 (подробности в [Day-2 Operations](./k8s_ha_bare_metal_day2_operations.md)):**
- [ ] MetalLB + Ingress-контроллер установлены и работают.
- [ ] Prometheus/Grafana установлены, ключевые алерты настроены.
- [ ] Бэкапы etcd работают по расписанию.
- [ ] ResourceQuota/LimitRange установлены для production namespace.
- [ ] Pod Security Admission включен.

### Troubleshooting (Поиск и устранение неисправностей)

#### Проблема: Поды CoreDNS в статусе CrashLoopBackOff
**Причина**: Часто связано с зацикливанием DNS (loop). CoreDNS обнаруживает, что вышестоящий DNS — это он сам.
**Решение**: Проверьте `/etc/resolv.conf` на узлах. Если там указан `127.0.0.53`, настройте CoreDNS на использование другого upstream DNS (например, 8.8.8.8) через `kubectl edit configmap -n kube-system coredns`.
**Подробнее**: См. **[Петли перенаправления DNS](../../../Networking/Protocols/DNS/dns_forwarding_loops.md)**.

#### Проблема: Error from server (Forbidden) при `kubectl top`
**Причина**: Metrics Server не может авторизоваться в Kubelet из-за сертификатов.
**Решение**: Добавьте в аргументы запуска Metrics Server:
`--kubelet-insecure-tls` и `--kubelet-preferred-address-types=InternalIP`.

#### Проблема: etcd теряет кворум
**Симптомы**: `etcdserver: no leader`, ошибки записи, `kubectl get` частично работает.
**Диагностика**:
```bash
sudo k-etcdctl endpoint status -w table
# → Проверить IS LEADER — должен быть ровно один true
# → Проверить RAFT TERM — должен быть одинаковым
```
**Решение**: Восстановление из снапшота или добавление недостающих узлов.
**Подробнее**: **[Высокая доступность в Kubernetes](../../Base/high_availability.md)**.

#### Проблема: VIP не мигрирует при отказе мастера
**Симптомы**: После остановки Keepalived на мастере, API недоступен.
**Диагностика**:
```bash
# Проверка состояния Keepalived на всех мастерах
sudo systemctl status keepalived
# Проверка логов
sudo journalctl -u keepalived -f
# Проверка VRRP-пакетов
sudo tcpdump -i eth0 -n vrrp
```
**Типичные причины**:
- VRRP-пакеты блокируются firewall
- Неправильная настройка `unicast_peer` в Unicast-режиме
- `nopreempt` включен, но приоритеты настроены неверно

#### Проблема: Поды не планируются на узлы
**Симптомы**: Поды зависают в статусе `Pending`.
**Диагностика**:
```bash
kubectl describe pod <pod-name> | grep -A10 Events
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
kubectl top nodes
```
**Типичные причины**:
- Все узлы имеют taints без соответствующих tolerations
- Ресурсов на узлах недостаточно (memory/CPU pressure)
- Планировщик не запущен или не healthy

### Интеграция с документацией

Данный файл завершает цикл установки HA кластера.
- Предыдущий этап: **[Присоединение узлов](./node_joining.md)**
- Теория отказоустойчивости: **[Высокая доступность в Kubernetes](../../Base/high_availability.md)**
- Архитектура Control Plane: **[Архитектура Control Plane](../../Concepts/control_plane_architecture.md)**
- Настройка Keepalived/HAProxy: **[HA API-сервера с Keepalived и HAProxy](../kubeadm/ha_concepts.md)**
- Диагностика сети: **[Порядок диагностики сети](../../../Linux/Networking/network_troubleshooting_order.md)**
- Резервное копирование etcd: **[Стратегии резервного копирования](../../Operations/backup-strategies.md)**
- Day-2 эксплуатация: **[Внешний доступ, мониторинг, обновления](./k8s_ha_bare_metal_day2_operations.md)**
