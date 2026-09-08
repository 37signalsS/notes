# Диагностика сетевых проблем в Kubernetes

## Определения

**Network Troubleshooting** — систематический подход к выявлению и устранению сетевых проблем в кластере Kubernetes. Включает методологию пошаговой проверки от физического уровня до прикладного.

**Pod-to-Pod Connectivity** — способность подов на разных узлах обмениваться данными. Базовая проверка сетевой связности кластера.

**Service Connectivity** — доступность сервисов (ClusterIP, NodePort, LoadBalancer) из подов и внешних источников.

**DNS Resolution** — процесс преобразования доменных имен сервисов в IP-адреса через CoreDNS. Одна из самых частых причин сетевых проблем.

**CNI Health** — состояние плагина CNI (Calico, Cilium, Flannel), обеспечивающего сетевую связность. Проблемы CNI приводят к полной потере сети.

**conntrack Issues** — проблемы с таблицей отслеживания соединений ядра Linux. Проявляются как timeouts, connection refused или partial connectivity.

**MTU Mismatch** — несоответствие Maximum Transmission Unit на разных уровнях сети. Вызывает фрагментацию или потерю пакетов.

**Network Policy Deny** — блокировка трафика сетевыми политиками Kubernetes. Частая причина "невидимых" проблем с доступностью.

---

## Основные концепции

### Методология диагностики (Bottom-Up)

Систематический подход к диагностике сетевых проблем в Kubernetes:

```
1. Физический уровень (L1/L2)
   └─ Сетевые интерфейсы, MAC-адреса, ARP/NDP
2. Сетевой уровень (L3)
   └─ IP-адреса, маршрутизация, ICMP
3. Транспортный уровень (L4)
   └─ TCP/UDP порты, conntrack, NAT
4. Прикладной уровень (L7)
   └─ DNS, HTTP, gRPC
5. Kubernetes-специфичные проверки
   └─ Service, Endpoints, NetworkPolicy
```

### Быстрая диагностика (5 минут)

```bash
# 1. Статус узлов
kubectl get nodes -o wide

# 2. Статус подов в kube-system
kubectl -n kube-system get pods -o wide | grep -E 'coredns|kube-proxy|cilium|calico'

# 3. Быстрая проверка DNS
kubectl run debug --image=busybox --rm -it --restart=Never -- nslookup kubernetes.default

# 4. Проверка связности с сервисом
kubectl run debug --image=busybox --rm -it --restart=Never -- wget -qO- --timeout=5 http://kubernetes.default

# 5. Проверка сетевых политик
kubectl get networkpolicy -A
```

### Уровни проблем

| Уровень | Симптомы | Инструменты |
| :--- | :--- | :--- |
| **Физический (L1/L2)** | Потеря связи, ошибки CRC | `ip link`, `ethtool`, `dmesg` |
| **Сетевой (L3)** | Пинг работает, но сервисы недоступны | `ip route`, `traceroute`, `tcpdump` |
| **Транспортный (L4)** | TCP соединения устанавливаются, но данные не передаются | `conntrack`, `ss`, `netstat` |
| **Прикладной (L7)** | DNS работает, HTTP возвращает ошибки | `curl`, `dig`, `kubectl logs` |
| **Kubernetes** | Сервисы существуют, но нет эндпоинтов | `kubectl describe service`, `kubectl get endpoints` |

---

## Практические сценарии

### 1. Под подом нет IP-адреса

**Симптом:** Под в статусе `ContainerCreating`, нет IP.

**Диагностика:**
```bash
# Проверка событий пода
kubectl describe pod <pod-name> | grep -A 10 Events

# Проверка CNI плагина
kubectl -n kube-system get pods -l k8s-app=cilium
kubectl -n kube-system get pods -l k8s-app=calico

# Проверка логов CNI
kubectl -n kube-system logs -l k8s-app=cilium --tail=100

# Проверка CIDR
kubectl cluster-info dump | grep -i cluster-cidr
```

**Решение:**
1. Убедитесь, что CNI плагин работает и готов
2. Проверьте, что CIDR подов не пересекается с другими сетями
3. Проверьте, что IPAM пул не исчерпан

### 2. Под не может связаться с другим подом

**Симптом:** `ping` между подами на разных узлах не работает.

**Диагностика:**
```bash
# Пинг между подами на одном узле
kubectl run test1 --image=busybox --rm -it --restart=Never -- ping <pod-ip-on-same-node>

# Пинг между подами на разных узлах
kubectl run test2 --image=busybox --rm -it --restart=Never -- ping <pod-ip-on-different-node>

# Проверка маршрутизации на узле
ip route show | grep <pod-cidr>

# Проверка ARP-таблицы
arp -a | grep <pod-ip>
```

**Решение:**
1. Проверьте, что CNI правильно настраивает маршруты
2. Убедитесь, что файрвол не блокирует трафик между узлами
3. Проверьте MTU на всех интерфейсах

### 3. DNS не работает

**Симптом:** `nslookup` или `dig` возвращают ошибки.

**Диагностика:**
```bash
# Проверка CoreDNS подов
kubectl -n kube-system get pods -l k8s-app=kube-dns

# Проверка логов CoreDNS
kubectl -n kube-system logs -l k8s-app=kube-dns --tail=50

# Проверка DNS из пода
kubectl run debug --image=busybox --rm -it --restart=Never -- nslookup kubernetes.default

# Проверка resolv.conf в поде
kubectl run debug --image=busybox --rm -it --restart=Never -- cat /etc/resolv.conf

# Проверка Service ClusterIP для DNS
kubectl -n kube-system get svc kube-dns
```

**Решение:**
1. Убедитесь, что CoreDNS работает и проходит readiness probes
2. Проверьте, что NetworkPolicy разрешает DNS трафик (порт 53)
3. Установите NodeLocal DNSCache для кэширования

### 4. Service недоступен

**Симптом:** `curl` к Service ClusterIP возвращает ошибки.

**Диагностика:**
```bash
# Проверка Service
kubectl describe svc <service-name>

# Проверка Endpoints
kubectl get endpoints <service-name>

# Проверка readiness подов
kubectl get pods -l app=<app-label> -o wide

# Проверка правил kube-proxy
sudo iptables-save -t nat | grep KUBE-SVC | grep <service-cluster-ip>

# Проверка IPVS (если используется)
sudo ipvsadm -Ln | grep <service-cluster-ip>
```

**Решение:**
1. Убедитесь, что поды проходят readiness probes
2. Проверьте, что порты в Service совпадают с портами в подах
3. Проверьте, что labels в Service совпадают с labels подов

### 5. NetworkPolicy блокирует трафик

**Симптом:** Трафик блокируется, хотя политика разрешает.

**Диагностика:**
```bash
# Просмотр всех NetworkPolicy
kubectl get networkpolicy -A

# Описание конкретной политики
kubectl describe networkpolicy <policy-name> -n <namespace>

# Проверка, какие поды попадают под политику
kubectl get pods -l <selector-from-policy> -n <namespace>

# Проверка логов CNI (для детальной диагностики)
kubectl -n kube-system logs -l k8s-app=cilium | grep -i "policy"
```

**Решение:**
1. Убедитесь, что policyTypes включает Ingress/Egress
2. Проверьте, что podSelector правильно выбирает целевые поды
3. Проверьте, что namespaceSelector корректен

### 6..conntrack переполнен

**Симптом:** `nf_conntrack: table full, dropping packet` в dmesg.

**Диагностика:**
```bash
# Проверка текущего использования
sudo sysctl net.netfilter.nf_conntrack_count
sudo sysctl net.netfilter.nf_conntrack_max

# Проверка ошибок conntrack
dmesg | grep -i conntrack

# Просмотр активных соединений
sudo conntrack -L | wc -l
```

**Решение:**
```bash
# Увеличение лимита
sudo sysctl -w net.netfilter.nf_conntrack_max=1000000

# Уменьшение таймаутов
sudo sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=7200
sudo sysctl -w net.netfilter.nf_conntrack_tcp_timeout_time_wait=30

# Сохранение изменений
cat <<EOF | sudo tee /etc/sysctl.d/99-conntrack.conf
net.netfilter.nf_conntrack_max = 1000000
net.netfilter.nf_conntrack_tcp_timeout_established = 7200
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
EOF
sudo sysctl -p /etc/sysctl.d/99-conntrack.conf
```

### 7. MTU Mismatch

**Симптом:** Зависания при передаче больших файлов, работает `ping -s 1400`, не работает `ping -s 1472`.

**Диагностика:**
```bash
# Проверка MTU на интерфейсах
ip link show | grep -E 'mtu|state'

# Проверка MTU в поде
kubectl exec <pod-name> -- ip link show eth0

# Проверка Path MTU
ping -M do -s 1472 <destination-ip>
# → Если не проходит, MTU меньше 1500

# Проверка MTU VXLAN интерфейса
ip link show cilium_vxlan | grep mtu
```

**Решение:**
```bash
# Настройка MTU для VXLAN (Calico)
kubectl -n kube-system get configmap calico-config -o yaml | grep -i mtu

# Настройка MTU для Cilium
helm upgrade cilium cilium/cilium --set mtu=1450

# Или через ConfigMap
kubectl -n kube-system patch configmap calico-config --type merge -p '{"data":{"vxlan_mtu":"1450"}}'
```

### 8. Внешний доступ не работает

**Симптом:** Сервис типа `LoadBalancer` не получает внешний IP.

**Диагностика:**
```bash
# Проверка Service
kubectl describe svc <service-name>

# Проверка MetalLB (если используется)
kubectl -n metallb-system get pods
kubectl -n metallb-system get logs -l app.kubernetes.io/component=speaker

# Проверка BGP сессий (если BGP режим)
sudo journalctl -u metallb-speaker | grep -i bgp

# Проверка ARP
arp -a | grep <external-ip>
```

**Решение:**
1. Убедитесь, что MetalLB запущен и имеет достаточный пул IP
2. Проверьте, что NetworkPolicy разрешает входящий трафик
3. Проверьте, что файрвол не блокирует порты

### 9. Высокая задержка (Latency)

**Симптом:** Приложение работает медленно, таймауты.

**Диагностика:**
```bash
# Замер задержки между подами
kubectl run debug --image=busybox --rm -it --restart=Never -- ping -c 100 <target-ip>

# Проверка маршрута
traceroute <target-ip>

# Проверка qdisc (очередей)
tc qdisc show

# Проверка CPU на узле
top -bn1 | grep kube-proxy
```

**Решение:**
1. Убедитесь, что поды находятся в одной зоне доступности
2. Проверьте, что CNI не добавляет лишний overhead
3. Настройте topology-aware routing

---

## Диагностика и устранение неполадок

### Инструменты диагностики

| Инструмент | Назначение | Установка |
| :--- | :--- | :--- |
| `kubectl` | Управление кластером | Встроен в Kubernetes |
| `busybox` | Базовые проверки (ping, nslookup) | `kubectl run debug --image=busybox` |
| `nicolaka/netshoot` | Продвинутая диагностика | `kubectl run debug --image=nicolaka/netshoot` |
| `tcpdump` | Захват пакетов | `kubectl exec <pod> -- tcpdump -i eth0` |
| `conntrack` | Просмотр таблицы соединений | `sudo conntrack -L` |
| `hubble` | Видимость трафика Cilium | `hubble observe --pod <pod>` |
| `pwru` | Отслеживание пути пакета в ядре | `sudo pwru --filter-dst-port 80` |

### Типичные проблемы и решения

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Pod не получает IP** | CNI плагин не работает | `kubectl describe pod <pod>`; `kubectl logs -n kube-system -l k8s-app=cilium` | Проверить CNI; перезапустить DaemonSet |
| **DNS не резолвится** | CoreDNS упал или NetworkPolicy блокирует | `kubectl -n kube-system get pods -l k8s-app=kube-dns`; `nslookup kubernetes.default` | Перезапустить CoreDNS; добавить DNS egress правило |
| **Service ClusterIP не отвечает** | Нет эндпоинтов или kube-proxy не обновил правила | `kubectl get endpoints <svc>`; `iptables-save \| grep KUBE-SVC` | Проверить readiness probes; перезапустить kube-proxy |
| **Трафик между узлами не работает** | BGP не настроен или файрвол блокирует | `ip route show`; `telnet <other-node-ip> 179` | Настроить BGP; открыть порты |
| **conntrack table full** | Малый лимит conntrack | `dmesg \| grep conntrack`; `sysctl net.netfilter.nf_conntrack_max` | Увеличить `nf_conntrack_max` |
| **MTU mismatch** | Несоответствие MTU на интерфейсах | `ping -M do -s 1472 <ip>`; `ip link show` | Настроить MTU во всех компонентах |
| **NetworkPolicy блокирует** | Неверный селектор или отсутствует egress для DNS | `kubectl describe networkpolicy <name>` | Исправить селекторы; добавить DNS egress |

### Алгоритм диагностики

```
Проблема с сетью в Kubernetes
│
├─ Пинг между подами работает?
│   ├─ Да → Проблема на L4/L7
│   │   ├─ DNS работает? → Проверить Service/Endpoints
│   │   └─ DNS не работает → Проверить CoreDNS, NetworkPolicy
│   └─ Нет → Проблема на L3
│       ├─ Пинг на одном узле работает? → Проблема между узлами
│       └─ Пинг на одном узле не работает → Проблема CNI
│
├─ Service доступен?
│   ├─ Да → Проблема с внешним доступом
│   └─ Нет → Проверить эндпоинты, readiness probes
│
└─ External LB работает?
    ├─ Да → Проблема с Ingress/ateway API
    └─ Нет → Проверить MetalLB/BGP, файрвол
```

---

## Рекомендации и очистка

### Рекомендации для production

1. **Настройте мониторинг:** Используйте Prometheus с алертами на:
   - `kube_pod_status_ready` — не готовые поды
   - `kube_service_status_load_balancer` — проблемы с LB
   - `coredns_dns_requests_total` — ошибки DNS

2. **Установите NodeLocal DNSCache:** Снижает нагрузку на CoreDNS и решает проблемы с UDP conntrack

3. **Используйте NetworkPolicy по умолчанию:** Default Deny для каждого namespace

4. **Включите Hubble (Cilium):** Глубокая видимость сетевого трафика

5. **Настройте Graceful Termination:** `terminationGracePeriodSeconds` и PreStop hooks

6. **Регулярно проверяйте conntrack:** Алерты на 80% использования `nf_conntrack_max`

7. **Документируйте CIDR:** Ведите реестр podCIDR, serviceCIDR, nodeNetwork

### Очистка среды

```bash
# Удаление тестовых подов
kubectl delete pod debug --ignore-not-found

# Очистка conntrack (если нужно)
sudo conntrack -F

# Удаление временных правил
sudo iptables-save | grep -v KUBE | sudo iptables-restore

# Сброс статистики IPVS
sudo ipvsadm --clear
```

---

## Крайние случаи и ограничения

1. **Split-brain при сете:** Если сеть между узлами разорвана, но сами узлы работают, могут возникать проблемы с кворумом etcd и переключением лидерства.

2. **Race conditions в conntrack:** При одновременном создании множества соединений могут возникать конфликты в таблице conntrack. Используйте NodeLocal DNSCache для DNS.

3. **Проблемы с hairpin NAT:** Если под обращается к своему же сервису, это может вызывать проблемы с маршрутизацией. Проверяйте `hairpin-mode` в kube-proxy.

4. **Ограничения MTU в оверлеях:** VXLAN добавляет 50 байт оверхеда. При MTU 1500 реальный MTU пода будет 1450. Несоответствие приводит к фрагментации.

5. **Конфликты IPAM:** При использовании разных CNI (миграция) могут возникать конфликты IP-адресов. Всегда проверяйте CIDR перед миграцией.

6. **Проблемы с dual-stack:** IPv6 может работать некорректно, если CNI или kube-proxy не поддерживают dual-stack. Проверяйте `ipFamilyPolicy` в Service.

---

## Дополнительные сведения

### Чек-лист перед продакшеном

- [ ] CNI плагин работает и готов
- [ ] CoreDNS работает и проходит readiness probes
- [ ] NetworkPolicy настроен для каждого namespace
- [ ] MetalLB/BGP работает для внешнего доступа
- [ ] conntrack оптимизирован (таймауты, лимиты)
- [ ] MTU согласован на всех интерфейсах
- [ ] NodeLocal DNSCache установлен
- [ ] Graceful Termination настроен для приложений
- [ ] Мониторинг и алерты настроены

### См. также

- [kube-proxy](./kube-proxy.md) — режимы работы и диагностика
- [CNI и kube-proxy: роли](./cni_kube_proxy_roles.md) — взаимодействие компонентов
- [NetworkPolicy](./network_policy.md) — сетевые политики
- [DNS в Kubernetes](./dns_deep_dive.md) — глубокое погружение в DNS

**[К списку разделов CNI](../cni_kube_proxy_roles.md)**
