# Недоступность узла: Сетевые проблемы

Сетевая связность является фундаментом работоспособности узла Kubernetes. Сбои на этом уровне могут привести как к невозможности запуска отдельных подов, так и к полной изоляции узла от Control Plane. Данный файл является **SSoT для диагностики сетевых проблем, специфичных для недоступности узла** — общая диагностика узла описана в [Диагностика недоступности узла](./diagnostics.md), определения состояний — в [Определения](./definitions.md), MTU/VPN — в [MTU и VPN](../../../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md), CNI — в [CNI и kube-proxy](../../../Networking/Network/cni_kube_proxy_roles.md).

## Основные определения

**`NetworkUnavailable`** — состояние узла (условие `Ready=False` с причиной `NetworkUnavailable`), указывающее на критический сбой в работе CNI-плагина (Container Network Interface). В этом состоянии узел не может выделять IP-адреса подам, что блокирует их запуск.

**Node Unreachable (Network Partition)** — состояние (`Ready=Unknown`), при котором узел теряет связь с API-сервером на уровне инфраструктуры (L3). Причиной могут быть ошибки маршрутизации, блокировки на файрволах или переполнение системных таблиц ядра (conntrack/arp). Подробнее: [Определения](./definitions.md).

**Связь с Node Lease**: Современный механизм heartbeats (Lease API) крайне чувствителен к сетевым задержкам. Если пакеты Lease не доходят до API-сервера в течение `node-monitor-grace-period` (обычно 40с), узел помечается как `Unknown`.

### Классификация сетевых сбоев узла

| Категория | Симптомы | Типичные причины | Критичность |
| :--- | :--- | :--- | :--- |
| **CNI-плагин** | `NetworkUnavailable=True`, поды в `ContainerCreating` | Неверный CIDR, отсутствие конфигов, crash CNI DaemonSet | Critical |
| **kube-proxy** | Service ClusterIP недоступен, DNAT не работает | Повреждение правил iptables/nftables, зависание kube-proxy | High |
| **Conntrack** | Случайные таймауты DNS/HTTP, DROP в dmesg | Переполнение таблицы `nf_conntrack`, сломанные хвосты соединений | High |
| **MTU/Overlay** | Маленькие пакеты проходят, TCP/HTTP зависает | Несовпадение MTU в туннелях (VXLAN/IPIP), сломанный PMTUD | Medium |
| **DNS** | `no such host`, разрешение имен не работает | CoreDNS CrashLoopBackOff, `resolv.conf` на узле, NodeLocal DNSCache | High |
| **BGP/роутинг** | Поды изолированы между узлами, маршруты отсутствуют | Упала BGP-сессия (Calico), неверные static routes | Critical |
| **NetworkPolicy** | Поды не могут общаться, хотя сеть физически рабочая | Строгие правила egress/ingress, default-deny без исключений | Medium |
| **Файрвол** | Порт 6443/10250 недоступен, API-сервер не отвечает | Security Groups, iptables на хосте, ACL на сетевом оборудовании | Critical |

## Основные концепции

### Компоненты сетевой доступности

| Компонент | Роль в доступности | Диагностический фокус |
| :--- | :--- | :--- |
| **CNI Plugin** | L2/L3 связность подов | Наличие конфигов в `/etc/cni/net.d/`, статус бинарников и DaemonSet. |
| **kube-proxy** | Маршрутизация (Service IP) | Статус правил nftables/iptables/IPVS. В v1.31 поддерживает Graceful Termination. |
| **CoreDNS** | Разрешение имен | Доступность порта 53/UDP и работа Service Discovery. |
| **Conntrack** | Отслеживание соединений | Лимиты таблицы состояний в ядре Linux. |
| **Сетевые модули ядра** | Bridge, VXLAN, Geneve, nftables | Наличие загруженных модулей (`lsmod`), функциональность `nf_conntrack`. |

### Сетевые зависимости узла

| Зависимость | Проверка | Последствие сбоя |
| :--- | :--- | :--- |
| **Физическая сеть** | `ip link show`, `ethtool <iface>` | Полная изоляция, `Unknown` |
| **Шлюз по умолчанию** | `ip route show default` | Нет маршрута к Control Plane |
| **DNS-резолвер** | `cat /etc/resolv.conf`, `dig kubernetes.default` | Разрешение имён не работает, `ContainerCreating` |
| **Порт 6443 (API)** | `curl -sk https://<api>:6443/healthz` | Kubelet не может обновлять статус, `Unknown` |
| **Порт 10250 (kubelet)** | `curl -sk https://<node>:10250/healthz` | Control Plane не может работать с kubelet |
| **CNI DaemonSet** | `kubectl get pods -n kube-system -l k8s-app=<cni>` | `NetworkUnavailable`, поды не запускаются |
| **kube-proxy** | `kubectl get pods -n kube-system -l k8s-app=kube-proxy` | Service ClusterIP недоступен |

### Глубокие причины сетевых сбоев

1.  **Проблемы MTU (Maximum Transmission Unit)**:
    *   При использовании Overlay-сетей (VXLAN, IPIP) добавляется инкапсуляция (обычно 50 байт).
    *   Если физический MTU = 1500, MTU внутри туннеля должен быть **1450**.
    *   Симптом: мелкие пакеты (ping) проходят, большие (TCP/HTTP) — "виснут" или обрываются.
2.  **Переполнение таблиц Netfilter (Conntrack)**:
    *   При большом количестве соединений таблица `nf_conntrack` заполняется. Новые соединения (включая DNS и Lease heartbeats) отбрасываются.
    *   Диагностика: `dmesg | grep "conntrack table full"`.
3.  **Graceful Termination в kube-proxy (v1.31+)**:
    *   В v1.31 механизм корректного завершения соединений при удалении эндпоинтов стал стабильным. Некорректная настройка может привести к "зависшим" соединениям на узлах, находящихся в процессе обслуживания.
4.  **Конфликт CNI и файрвола**:
    *   Некоторые CNI (Calico сiptables) вносят правила в `nat` и `filter` таблицы. Конфликт с `.service` файрволом (`firewalld`, `ufw`) приводит к потере трафика. Рекомендуется использовать CNI с nftables-бэком или отключать файрвол на узлах кластера.

## Практические сценарии

### Сценарий 1: Состояние NetworkUnavailable=True

**Симптомы**: Узел `NotReady`, новые поды висят в `ContainerCreating`.

**Диагностика**:
```bash
# 1. Проверка conditions узла
kubectl describe node <node-name> | grep -A 5 "NetworkUnavailable"
# → NetworkUnavailable: True, Reason: CNIPluginNotReady, 
# →   Message: FlannelIsDown: Flannel does not have backend subnet for host 192.168.1.50

# 2. Проверка наличия конфигурации CNI на узле
ls -la /etc/cni/net.d/
# → total 8
# → drwxr-xr-x 2 root root 4096 Sep  4 17:30 .
# → -rw-r--r-- 1 root root  284 Sep  4 17:30 10-calico.conflist
# → -rw-r--r-- 1 root root   56 Sep  4 17:30 99-loopback.conf
# Если пусто → CNI не установлен

# 3. Проверка статуса CNI DaemonSet
kubectl get pods -n kube-system -l k8s-app=calico-node -o wide | grep <node-name>
# → NAME                    READY   STATUS    RESTARTS   AGE   IP            NODE
# → calico-node-xyz34       0/1     Error     5          10m   10.0.0.15     node-1

# 4. Просмотр логов CNI с ошибкой
kubectl logs -n kube-system calico-node-xyz34 --previous | tail -30
# → 2026-09-04T17:30:00Z [ERROR][56] felix/endpoint.go:561 Failed to set endpoint 
# →   to call_dataplane: error calling dataplane update: 
# →   command: ip route add 10.244.1.0/24 via 10.0.0.25 dev eth0 failed: 
# →   RTNETLINK answers: File exists

# 5. Проверка binaрников CNI на узле (если доступен SSH)
ls -la /opt/cni/bin/ | grep -E "calico|flannel|cilium"
# → -rwxr-xr-x 1 root root 12345678 Sep  4 17:30 calico-ipam
# → -rwxr-xr-x 1 root root  8765432 Sep  4 17:30 calico
# → -rwxr-xr-x 1 root root  5432109 Sep  4 17:30 flannel

# 6. Проверка Pod CIDR (должен совпадать с конфигурацией CNI)
kubectl get node <node-name> -o jsonpath='{.spec.podCIDR}'
# → 10.244.1.0/24
```

**Решение**:
```bash
# 1. Проверьте несоответствие pod-network-cidr в конфигурации CNI
# и в параметрах API-сервера (в manifest kube-apiserver):
# --pod-network-cidr=10.244.0.0/16

# 2. Перезапуск CNI DaemonSet (если поды в Error)
kubectl rollout restart daemonset -n kube-system calico-node
kubectl rollout status daemonset -n kube-system calico-node
# → Waiting for rollout to finish: 3 out of 3 updated pods are available...
# → daemonset "calico-node" successfully rolled out

# 3. Если CNI конфиг отсутствует — установите его заново
# (пример для Calico):
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.27/manifests/calico.yaml
```

---

### Сценарий 2: Проблемы MTU в Overlay-сетях

**Симптомы**: Сеть кажется рабочей, но скачивание больших файлов или HTTPS-запросы внутри подов не работают. Симптомы идентичны=image-pull (см. [Сетевые проблемы при загрузке образов](../../PodImagePullErrors/network_issues.md)).

**Диагностика**:
```bash
# 1. Тест Path MTU Discovery (DF bit)
ping -M do -s 1472 <target-ip>
# → ping: local error: Message too long
# → PING 10.244.0.5: 1472 data bytes
# Если не проходит → MTU < 1500

# 2. Поиск реального MTU
ping -M do -s 1422 <target-ip>
# → PING 10.244.0.5: 1422 data bytes
# → 1430 bytes from 10.244.0.5: icmp_seq=1 ttl=64 time=0.5ms
# → Реальный MTU = 1422 + 28 = 1450 (стандарт для VXLAN)

# 3. Проверка MTU на интерфейсах узла
ip link show eth0 | grep mtu
# → 2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel
ip link show tunl0 | grep mtu 2>/dev/null
# → 5: tunl0: <NOARP,UP,LOWER_UP> mtu 1440 qdisc noqueue

# 4. Проверка MTU в конфиге CNI
kubectl get configmap -n kube-system <cni-config> -o yaml | grep -i mtu
# → data:
# →   mtu: "1440"

# 5. Проверка PMTUD через traceroute
traceroute -M do -p 443 -l 1472 <target-ip>
# → traceroute to 10.244.0.5, 30 hops max, 1472 byte packets
# → 1  * * *
# → Если зависает после первого хопа → MTU/fragmentation
```

**Решение**:
```bash
# 1. Установите корректный MTU в ConfigMap CNI
# Для VXLAN с физическим MTU 1500: MTU = 1500 - 50 = 1450
# Для IPIP с физическим MTU 1500: MTU = 1500 - 20 = 1480

# 2. После изменения MTU перезапустите CNI DaemonSet
kubectl rollout restart daemonset -n kube-system <cni-daemonset>

# 3. Проверка MSS clamping (для TCP через туннели)
iptables -t mangle -L -n | grep -i mss
# Если MSS не clamped → добавьте правило:
# iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
#   -j TCPMSS --clamp-mss-to-pmtu
```

---

### Сценарий 3: Переполнение таблицы Conntrack

**Симптомы**: Случайные таймауты соединений на высоконагруженных узлах. DNS не отвечает, HTTP-соединения обрываются. Nginx/Envoy логируют `upstream timed out`.

**Механизм**: Ядро Linux отслеживает каждое сетевое соединение в таблице `nf_conntrack`. При переполнении новые соединения отбрасываются с сообщением `nf_conntrack: table full, dropping packet`.

**Диагностика**:
```bash
# 1. Проверка текущего количества соединений и лимита
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max
# → net.netfilter.nf_conntrack_count = 1048576   ← текущее количество
# → net.netfilter.nf_conntrack_max = 1048576     ← лимит
# Если count == max → переполнение

# 2. Проверка в логах ядра
dmesg -T | grep -i "conntrack table full" | tail -5
# → [Thu Sep  4 17:30:00 2026] nf_conntrack: table full, dropping packet
# → [Thu Sep  4 17:30:01 2026] nf_conntrack: table full, dropping packet

# 3. Проверка протоколов, создающих больше всего записей
conntrack -L -o protocol | awk '{print $1}' | sort | uniq -c | sort -rn | head -5
# → 500000 tcp
# → 200000 udp
# → 100000 icmp

# 4. Проверка конкретных протоколов (TCP vs UDP vs ICMP)
conntrack -L -p tcp 2>/dev/null | wc -l
# → 500000   ← много TCP-соединений

# 5. Проверка count/max через /proc
cat /proc/sys/net/netfilter/nf_conntrack_count
# → 1048576
cat /proc/sys/net/netfilter/nf_conntrack_max
# → 1048576
```

**Решение**:
```bash
# 1. Увеличьте лимит (временно)
sysctl -w net.netfilter.nf_conntrack_max=2097152

# 2. Сделайте постоянным
echo "net.netfilter.nf_conntrack_max=2097152" >> /etc/sysctl.conf
sysctl -p

# 3. Увеличьте hashsize (для предотвращения коллизий)
echo "262144" > /sys/module/nf_conntrack/parameters/hashsize
echo "options nf_conntrack hashsize=262144" >> /etc/modprobe.d/nf_conntrack.conf

# 4. Уменьшите timeout для TCP-соединений (освобождает место быстрее)
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=3600
# По умолчанию 432000 сек (5 дней) — слишком долго для высоконагруженных кластеров

# 5. Если conntrack не нужен (Calico без kube-proxy, Cilium eBPF) — отключите:
# sysctl -w net.bridge.bridge-nf-call-iptables=0
# sysctl -w net.bridge.bridge-nf-call-ip6tables=0
```

---

### Сценарий 4: Узел в статусе Unknown (полная изоляция)

**Симптомы**: `Ready=Unknown`, SSH недоступен.

**Алгоритм действий**:
```bash
# 1. Проверка conditions узла
kubectl get node <node-name> -o jsonpath='{range .status.conditions[*]}{.type}={.status}{"\n"}{end}'
# → Ready=Unknown
# → MemoryPressure=False
# → DiskPressure=False
# → NetworkUnavailable=False   ← CNI работает, проблема на L3

# 2. Проверка последнего обновления Lease
kubectl get lease <node-name> -n kube-node-lease -o jsonpath='{.spec.renewTime}'
# → 2026-09-04T17:25:00Z   ← 10 минут назад → потеря связи

# 3. Проверка тайм-аутов
# Формула: node-monitor-grace-period = node-monitor-period × 2 + запас
# По умолчанию: 40 секунд

# 4. Проверка ACL/Security Groups (необходим SSH или IPMI)
# Разрешенные порты:
# - 6443 (TCP) — исходящий к API-серверу
# - 10250 (TCP) — входящий от Control Plane
# - 4789/UDP — VXLAN (Calico/Flannel)
# - 179/TCP — BGP (Calico)
# - 51820/UDP — WireGuard (если используется)

# 5. Проверка, есть ли маршруты к подам
ip route show | grep "10.244\|10.233"
# → 10.244.1.0/24 via 10.0.0.25 dev eth0 proto static
# Если маршрутов нет → проблема с CNI/роутингом
```

**Решение**:
1.  Проверьте статус ВМ/хоста (hardware reset, IPMI).
2.  Проверьте **Security Groups/Firewall**: разрешены порты 6443, 10250, VXLAN/BGP.
3.  Для BGP-сетей (Calico): проверьте статус пиринга (см. Сценарий 7).

---

### Сценарий 5: Сбои DNS на узле (CoreDNS / resolv.conf)

**Симптомы**: Поды не могут разрешать имена сервисов (`kubernetes.default`, `my-service.my-ns`). Ошибки `dial tcp: lookup my-service: no such host`.

**Причины**:
- CoreDNS CrashLoopBackOff (все поды DNS-сервера упали).
- `resolv.conf` на узле указывает на несуществующий DNS-сервер.
- NodeLocal DNSCache (DaemonSet) упал или некорректно настроен.
- NetworkPolicy блокирует доступ к CoreDNS (порты 53/TCP, 53/UDP).

**Диагностика**:
```bash
# 1. Проверка CoreDNS подов
kubectl get pods -n kube-system -l k8s-app=kube-dns -o wide | grep <node-name>
# → NAME                      READY   STATUS    RESTARTS   AGE   IP            NODE
# → coredns-abc123-x7y9z      1/1     Running   0          5d    10.233.0.10   node-2
# → coredns-abc123-def45      0/1     Error     3          10m   <none>        node-1  ← на проблемном узле

# 2. Просмотр логов CoreDNS с ошибкой
kubectl logs -n kube-system coredns-abc123-def45 --previous | tail -20
# → [ERROR] plugin/errors: 2 10.233.0.10:53: read udp 10.244.1.5:40123->10.233.0.10:53: i/o timeout
# → [PANIC] plugin/loop: Loop (127.0.0.1:60094 -> :53 -> :53) detected for zone ".",

# 3. Проверка resolv.conf на проблемном узле
cat /etc/resolv.conf
# → nameserver 10.233.0.10   ← ClusterIP CoreDNS
# → search default.svc.cluster.local svc.cluster.local cluster.local
# → ndots 5

# 4. Проверка NodeLocal DNSCache
kubectl get pods -n kube-system -l k8s-app=node-local-dns -o wide | grep <node-name>
# → NAME                     READY   STATUS    RESTARTS   AGE
# → node-local-dns-abc12     0/1     CrashLoopBackOff  5  10m

# 5. Тест резолва напрямую
kubectl run dns-test --image=busybox:1.36 --rm -it --restart=Never -- nslookup kubernetes.default
# → Server:    10.233.0.10
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.233.0.1

# 6. Проверка NetworkPolicy (если есть default-deny)
kubectl get networkpolicy -A | grep -i "deny\|default"
# → my-ns        deny-all   default-deny-egress
```

**Решение**:
```bash
# 1. Перезапуск CoreDNS
kubectl rollout restart deployment coredns -n kube-system
kubectl rollout status deployment coredns -n kube-system
# → deployment "coredns" successfully rolled out

# 2. Если проблема в resolv.conf на узле (указывает не на CoreDNS):
# Исправьте /etc/resolv.conf или через dhclient:
sudo chattr -i /etc/resolv.conf  # если файл защищен от записи
echo "nameserver 10.233.0.10" | sudo tee /etc/resolv.conf

# 3. Если NetworkPolicy блокирует DNS — добавьте исключение:
# apiVersion: networking.k8s.io/v1
# kind: NetworkPolicy
# metadata:
#   name: allow-dns
#   namespace: my-ns
# spec:
#   podSelector: {}
#   policyTypes:
#   - Egress
#   egress:
#   - to: []
#     ports:
#     - protocol: UDP
#       port: 53
#     - protocol: TCP
#       port: 53

# 4. Если NodeLocal DNSCache упал — проверьте Corefile
kubectl get configmap -n kube-system node-local-dns -o yaml
```

---

### Сценарий 6: Сбои kube-proxy (Service ClusterIP недоступен)

**Симптомы**: Pod не может достучаться до Service по ClusterIP, хотя Service существует и Endpoints есть. `curl http://my-service.my-ns:80` зависает.

**Причины**:
- kube-proxy упал или завис на узле.
- Правила iptables/nftables повреждены или не обновлены.
- IPVS таблица рассинхронизирована (при `--proxy-mode=ipvars`).
- Endpoints/EndpointSlice не обновлены (readinessProbe не проходит).

**Диагностика**:
```bash
# 1. Проверка kube-proxy подов
kubectl get pods -n kube-system -l k8s-app=kube-proxy -o wide | grep <node-name>
# → NAME                  READY   STATUS    RESTARTS   AGE
# → kube-proxy-abc12      1/1     Running   0          5d    node-1

# 2. Проверка IPVS таблицы (если используется)
ipvsadm -Ln | grep -A 2 "10.233.0."
# → TCP  10.233.0.1:80 rr
# →   -> 10.244.1.5:8080    Masq    1      0          0
# →   -> 10.244.2.8:8080    Masq    1      0          0

# 3. Проверка правил nftables (v1.31+)
nft list ruleset | grep -A 5 "KUBE-SVC"
# → table ip kube-proxy {
# →   chain KUBE-SVC-ABCDEF1234 {
# →     ip daddr 10.233.0.1 tcp dport 80 
# →     ct state new counter jump KUBE-SEP-1234
# →   }
# → }

# 4. Проверка Endpoints для Service
kubectl get endpoints my-service -n my-ns
# → NAME         ENDPOINTS                          AGE
# → my-service    10.244.1.5:8080,10.244.2.8:8080    5d
# Если ENDPOINTS пуст → readinessProbe не проходит

# 5. Проверка EndpointSlice (современный механизм)
kubectl get endpointslice -n my-ns -l kubernetes.io/service-name=my-service
# → NAME              ADDRESSTYPE   PORTS              ENDPOINTS                              AGE
# → my-service-abc12  IPv4         8080/TCP           10.244.1.5,10.244.2.8                  5d

# 6. Проверка, что kube-proxy обновил правила (логи)
kubectl logs -n kube-system kube-proxy-abc12 --since=5m | grep -i "sync\|iptables\|ipvs"
# → I0904 17:35:00.123456 123456 proxier.go:1500] Syncing iptables rules
# → I0904 17:35:00.654321 123456 proxier.go:1520] Finished syncing iptables rules in 521.654ms
```

**Решение**:
```bash
# 1. Перезапуск kube-proxy
kubectl rollout restart daemonset kube-proxy -n kube-system
kubectl rollout status daemonset kube-proxy -n kube-system

# 2. Принудительная синхронизация правил (kubectl proxy)
kubectl proxy &
curl -s http://localhost:8001/api/v1/namespaces/kube-system/pods/kube-proxy-abc12/exec \
  --restart --kube-proxy=true -p /bin/sh -- -c "iptables-restore < /etc/kubernetes/kube-proxy.conf"
# Или просто перезапустите под:
kubectl delete pod -n kube-system kube-proxy-abc12

# 3. Если kube-proxy в IPVS-режиме и таблица повреждена:
ipvsadm --clear
# kube-proxy автоматически пересоздаст правила

# 4. Если readinessProbe не проходит — проверьте healthcheck:
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[0].readinessProbe}'
```

---

### Сценарий 7: Сбои BGP-роутинга (Calico)

**Симптомы**: Поды на разных узлах не могут общаться друг с другом, хотя `NetworkUnavailable=False`. Поды на одном узле работают нормально.

**Механизм**: Calico в режиме BGP распространяет маршруты к подам через BGP-сессии между узлами. Если BGP-сессия падает, маршруты к подам на удаленных узлах становятся недоступными.

**Диагностика**:
```bash
# 1. Проверка BGP-сессий (calico-node)
kubectl exec -n kube-system calico-node-xyz34 -- calicoctl node status
# → IPv4 BGP status
# +---------------+-------------------+-------+----------+-------------+
# | PEER ADDRESS  |     PEER TYPE     | STATE |  SINCE   |    INFO     |
# +---------------+-------------------+-------+----------+-------------+
# | 192.168.1.51  | global            | up    | 10:30:00 | Established |
# | 192.168.1.52  | global            | flood | 10:30:00 | Connect     |  ← НЕ Established
# +---------------+-------------------+-------+----------+-------------+
# Если STATE != Established → BGP-сессия упала

# 2. Проверка маршрутов в ядре
ip route show | grep "bird" | head -5
# → 10.244.2.0/24 via 192.168.1.51 dev eth0 proto bird
# → 10.244.3.0/24 via 192.168.1.52 dev eth0 proto bird
# Если маршрута нет → BGP не распространяет его

# 3. Проверка IP-in-IP туннеля (если используется)
ip tunnel show | grep tunl
# → tunl0: ip/ip remote any local any ttl inherit nopmtudisc
ip link show tunl0
# → 5: tunl0: <NOARP,UP,LOWER_UP> mtu 1440 qdisc noqueue state UNKNOWN

# 4. Проверка логов Calico BGP Daemon
kubectl logs -n kube-system calico-node-xyz34 | grep -i "bgp\|bird" | tail -10
# → 2026-09-04T17:35:00Z [INFO][56] felix/daemon.go:1200 BGP daemon status: up
# → 2026-09-04T17:35:00Z [ERROR][56] bgp/client.go:245 Failed to connect to 
# →   BGP peer 192.168.1.52:179: connection refused

# 5. Проверка порта BGP на удаленных узлах
nc -zv 192.168.1.52 179
# → Connection to 192.168.1.52 179 port [tcp/bgp] failed: Connection refused
# → Если connection refused → bird не запущен на удаленном узле
# → Если timeout → файрвол блокирует порт 179
```

**Решение**:
```bash
# 1. Проверьте, что bird запущен на всех узлах Calico
# (на каждом узле):
sudo systemctl status bird
# → bird.service - BGP daemon for Calico
# →   Active: active (running) since Thu 2026-09-04 17:30:00 UTC

# 2. Если порт 179 заблокирован файрволом:
sudo iptables -I INPUT -p tcp --dport 179 -j ACCEPT
sudo iptables -I OUTPUT -p tcp --dport 179 -j ACCEPT

# 3. Перезапуск BGP Daemon (на проблемном узле):
sudo systemctl restart bird

# 4. Если BGP не нужен (Calico Felix в режиме vxlan):
# Используйте IP-in-IP или VXLAN backend вместо BGP:
calicoctl patch felixConfiguration default --type merge \
  -p '{"spec":{"ipipEnabled":false,"vxlanEnabled":true}}'
```

---

### Сценарий 8: Сетевая политика (NetworkPolicy) блокирует узел

**Симптомы**: Поды не могут общаться с CoreDNS, API-сервером или другими подами, хотя физическая сеть работает. `kubectl exec` в под не работает.

**Причина**: Строгие правила NetworkPolicy (особенно `default-deny`) блокируют критический трафик: DNS (53/TCP, 53/UDP), API-сервер (6443), метрики (9090, 9100).

**Диагностика**:
```bash
# 1. Проверка NetworkPolicy в namespace пода
kubectl get networkpolicy -n my-ns
# → NAME              POD-SELECTOR   AGE
# → default-deny-eg   <none>         5d   ← блокирует весь egress

# 2. Просмотр правил конкретного NetworkPolicy
kubectl describe networkpolicy default-deny-eg -n my-ns
# → Spec:
# →   PodSelector: <none> (all pods in namespace)
# →   PolicyTypes:
# →   - Egress
# →   Ingress: <none>
# →   Egress: <none>   ← нет исключений = блокируется всё

# 3. Проверка, есть ли исключения для DNS
kubectl get networkpolicy -n my-ns -o yaml | grep -A 10 "ports:"
# →     ports:
# →     - protocol: TCP
# →       port: 443

# 4. Проверка доступа к DNS из пода
kubectl exec -n my-ns <pod> -- nslookup kubernetes.default
# → ** server can't find kubernetes.default: SERVFAIL
# → Если SERVFAIL или timeout → DNS заблокирован

# 5. Проверка, есть ли ClusterRole для NetworkPolicy
kubectl get clusterrole | grep -i "network"
# → admin                                 2026-09-04T17:30:00Z
# → calico-projectcalico.org              2026-09-04T17:30:00Z
```

**Решение**:
```yaml
# Добавьте исключение для DNS в NetworkPolicy:
# apiVersion: networking.k8s.io/v1
# kind: NetworkPolicy
# metadata:
#   name: allow-dns
#   namespace: my-ns
# spec:
#   podSelector: {}
#   policyTypes:
#   - Egress
#   egress:
#   - to: []     # любые адреса
#     ports:
#     - protocol: UDP
#       port: 53
#     - protocol: TCP
#       port: 53
#   - to: []     # CoreDNS ClusterIP
#     ports:
#     - protocol: TCP
#       port: 53
```

```bash
# Применение исправления:
kubectl apply -f allow-dns-networkpolicy.yaml

# Проверка доступа к DNS:
kubectl exec -n my-ns <pod> -- nslookup kubernetes.default
# → Server:    10.233.0.10
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.233.0.1
```

---

### Сценарий 9: Конфликт CNI и файрвола (firewalld / ufw)

**Симптомы**: После включения `firewalld` или `ufw` на узле CNI-плагин (Calico/Flannel) перестает работать, поды теряют связность. `NetworkUnavailable=True`.

**Причина**: CNI-плагины (особенно Calico в режиме iptables) управляют правилами `nat` и `filter` таблицы. Файрвол (`firewalld`, `ufw`) может сбросить или блокировать эти правила при перезапуске или обновлении.

**Диагностика**:
```bash
# 1. Проверка статуса файрвола
sudo systemctl status firewalld
# → firewalld.service - firewalld - dynamic firewall daemon
# →   Active: active (running) since Thu 2026-09-04 17:30:00 UTC

# 2. Проверка правил iptables (должны содержать CNI-цепочки)
iptables -L -n | grep -i "calico\|flannel\|CNI"
# → Chain cali-FORWARD (1 references)
# → target     prot opt source               destination
# → DROP       all  --  0.0.0.0/0            0.0.0.0/0

# 3. Если файрвол сбросил правила CNI:
sudo iptables -L -n | grep -c "calico"
# → 0   ← нет калибровочных правил = конфликт

# 4. Проверка логов CNI на ошибки iptables
kubectl logs -n kube-system calico-node-xyz34 | grep -i "iptables\|nftables" | tail -5
# → [ERROR] felix/iptables.go:426 Failed to update iptables: 
# →   exit status 4: Another app is currently holding the xtables lock.
```

**Решение**:
```bash
# 1. Отключите файрвол (рекомендуется в кластерах):
sudo systemctl stop firewalld
sudo systemctl disable firewalld

# 2. Или добавьте исключения для CNI (firewalld):
sudo firewall-cmd --permanent --add-interface=cali+
sudo firewall-cmd --permanent --add-port=4789/udp   # VXLAN
sudo firewall-cmd --permanent --add-port=179/tcp    # BGP
sudo firewall-cmd --reload

# 3. Или добавьте исключения для CNI (ufw):
sudo ufw allow from 10.244.0.0/16     # Pod CIDR
sudo ufw allow from 10.233.0.0/16     # Service CIDR
sudo ufw allow 4789/udp                # VXLAN
sudo ufw allow 179/tcp                 # BGP

# 4. Восстановление правил CNI:
# Calico:
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.27/manifests/calico.yaml
# Flannel:
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml
```

---

### Сценарий 10: Проблемы с Network Namespace (netns)

**Симптомы**: Под имеет IP-адрес, но не может отправлять/получать пакеты. `ping` внутри пода не работает, хотя CNI报告显示 allocation.

**Причина**: Сетевое пространство имен пода (netns) повреждено или не подключено к bridge/veth. Типичные причины: crash containerd, ошибки CNI при создании пода, повреждение veth-пары.

**Диагностика**:
```bash
# 1. Проверка netns пода
# Найти PID пода:
PID=$(kubectl get pod <pod> -n <ns> -o jsonpath='{.status.containerStatuses[0].state.running.containerID}' | cut -d'/' -f3)
ls -la /proc/$PID/ns/net
# → lrwxrwxrwx 1 root root 0 Sep  4 17:30 40 -> 'net:[4026532009]'

# 2. Проверка veth-интерфейсов в netns
nsenter -t $PID -n ip addr
# → 1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN
# → 2: eth0@if15: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1440 qdisc noqueue state UP
# →     inet 10.244.1.5/24 brd 10.244.1.255 scope global eth0
# Если нет `eth0` → netns поврежден

# 3. Проверка veth-пары на хосте
ip link show | grep veth | head -5
# → 15: veth cali12345@if14: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1440

# 4. Проверка маршрута в netns
nsenter -t $PID -n ip route
# → default via 10.244.1.1 dev eth0
# → 10.244.0.0/16 via 10.244.1.1 dev eth0

# 5. Проверка ARP-таблицы
nsenter -t $PID -n arp -n
# → ? (10.244.1.1) at [incomplete] on eth0
# Если `[incomplete]` → проблема с L2-связностью
```

**Решение**:
```bash
# 1. Перезапуск пода (самый простой способ)
kubectl delete pod <pod> -n <ns>
# Kubernetes пересоздаст под с новым netns

# 2. Если netns поврежден — проверьте containerd
sudo crictl pods | grep <pod-name>
# → POD ID              CREATED             STATE               NAME
# → abc123def456         10 minutes ago     Ready               my-pod
# Если STATE != Ready → перезапустите containerd
sudo systemctl restart containerd

# 3. Проверка bridge (cali*/flannel*)
brctl show
# → bridge name    bridge id               STP enabled     interfaces
# → docker0        8000.0242ac110002       no
# → If docker0 нет или interfaces пуст → bridge не работает
```

## Мониторинг и алертинг

### Метрики сети (Prometheus)

| Метрика | Описание | Типичный порог алерта |
| :--- | :--- | :--- |
| `nf_conntrack_entries` | Количество записей conntrack | > 90% от `nf_conntrack_max` |
| `nf_conntrack_entries_used` | Использование conntrack (в%) | > 80%持续 |
| `node_network_receive_errs_total` | Ошибки приема пакетов (interface) | > 0持续 5 минут |
| `node_network_transmit_errs_total` | Ошибки отправки пакетов | > 0持续 5 минут |
| `node_network_receive_drop_total` | DROP на приеме (interface) | > 100/sec持续 |
| `kube_proxy_sync_proxy_rules_duration_seconds` | Время синхронизации правил kube-proxy | > 5 сек持续 |
| `kube_proxy_sync_proxy_rules_total` | Синхронизации kube-proxy (rate) | rate = 0持续 10 минут |

### Примеры алертов (PrometheusRule)

```yaml
groups:
  - name: node-network-health
    rules:
      # Conntrack переполняется
      - alert: NodeConntrackAlmostFull
        expr: >
          (node_nf_conntrack_entries / node_nf_conntrack_entries_limit) > 0.85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Conntrack на {{ $labels.instance }} заполнен на > 85%"
          description: "Текущее использование: {{ $value | humanizePercentage }}"

      # Ошибки сети на интерфейсе
      - alert: NodeNetworkReceiveErrors
        expr: rate(node_network_receive_errs_total[5m]) > 0
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Ошибки приема пакетов на {{ $labels.instance }} ({{ $labels.device }})"
          description: "Частота ошибок: {{ $value }}/сек"

      # kube-proxy не синхронизирует правила
      - alert: KubeProxySyncStalled
        expr: rate(kube_proxy_sync_proxy_rules_total[10m]) == 0
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "kube-proxy на {{ $labels.instance }} не синхронизирует правила"
          description: "kube-proxy не обновлял правила > 10 минут"

      # CoreDNS не отвечает
      - alert: CoreDNSUnhealthy
        expr: absent(up{job="kube-dns"} == 1)
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "CoreDNS не отвечает"
          description: "Все поды CoreDNS недоступны"
```

## Рекомендации по мониторингу

1. **Настройте алерт на conntrack** — переполнение таблицы приводит к случайным таймаутам, которые сложно отследить.
2. **Мониторьте ошибки сетевых интерфейсов** — `receive_errs` и `transmit_errs` указывают на аппаратные проблемы или перегрузку.
3. **Отслеживание kube-proxy** — его зависание приводит к немедленному отказу Service.
4. **CoreDNS** — его недоступность блокирует все DNS-резолвы в кластере.

---

## Дополнительная информация

- **[Диагностика MTU и PMTUD](../../../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — глубокая теория фрагментации.
- **[CNI и kube-proxy: роли](../../../Networking/Network/cni_kube_proxy_roles.md)** — сравнение nftables, iptables и IPVS.
- **[IPVS: тюнинг Conntrack](../../../Networking/Network/CNI/ipvs.md)** — оптимизация для высоких нагрузок.
- **[Сетевые проблемы при загрузке образов](../../PodImagePullErrors/network_issues.md)** — MTU/TLS в контексте Image Pull.
- **[Диагностика недоступности узла](./diagnostics.md)** — общие шаги проверки (SSH, kubectl debug).
- **[Taints и выселение](./taints_and_eviction.md)** — автоматическое перенос при сетевой изоляции.
- **[Определения](./definitions.md)** — базовые термины и состояния узлов.
