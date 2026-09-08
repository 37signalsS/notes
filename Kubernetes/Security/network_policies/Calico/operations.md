# Операции Calico: Диагностика, мониторинг и обслуживание

В данном разделе описаны процедуры проверки состояния, отладки и технического обслуживания сетевой инфраструктуры Calico. Основное внимание уделено современным режимам работы (eBPF, nftables), управлению IP-адресами (IPAM) и обеспечению безопасности узлов.

> Основная документация и концепции: [Calico HostEndpoint и GlobalNetworkPolicy](./index.md)

## Определения

**Calico Operations** — комплекс регламентированных процедур для обеспечения жизненного цикла сетевой подсистемы Calico, включающий мониторинг, резервное копирование и устранение инцидентов.

**Data Plane (Плоскость данных)** — механизм обработки пакетов на узлах. Calico поддерживает:
* **Standard (iptables)**: Традиционный режим, максимальная совместимость.
* **eBPF**: Высокопроизводительный режим, заменяющий kube-proxy.
* **nftables**: Современная альтернатива iptables (по умолчанию с v3.29+).
* **VPP**: Режим на основе векторной обработки пакетов (для специфичных высоконагруженных задач).

**IPAM (IP Address Management)** — подсистема управления пулами IP-адресов. Calico использует Block-Based IPAM для выделения блоков IP-адресов узлам (IP Pools и Blocks).

**WireGuard** — протокол шифрования трафика между узлами (Node-to-Node encryption), интегрированный в Calico.

**Failsafe Ports** — предопределенный список портов в `FelixConfiguration`, которые остаются открытыми даже при наличии блокирующих политик для предотвращения самоблокировки административного доступа (SSH, BGP, K8s API).

**Policy Tiers (Уровни политик)** — механизм группировки политик Calico по приоритетным уровням. Политики в вышестоящих уровнях оцениваются раньше и не могут быть переопределены нижестоящими.

**Typha** — промежуточный прокси-агент (fan-out proxy) для крупных кластеров (>50 узлов), снижающий нагрузку на Kubernetes API.

## Основные концепции

### Инструментарий и диагностические данные

1. **calicoctl**: Основная утилита для работы с объектами `projectcalico.org/v3`. Позволяет управлять ресурсами, недоступными через стандартный `kubectl`.
2. **Felix**: Агент на каждом узле (DaemonSet). Его состояние критично для применения политик. Felix экспортирует метрики в формате Prometheus.
3. **Typha**: Опциональный компонент-агрегатор для снижения нагрузки на Kubernetes API в больших кластерах (>50 узлов). Один экземпляр способен обслуживать до 200 узлов.
4. **BIRD (BGP Client)**: Демон маршрутизации, распространяющий маршруты между узлами по протоколу BGP.
5. **Confd**: Служба, мониторящая изменения конфигурации Calico и динамически обновляющая конфигурационные файлы BIRD.
6. **bpftool**: Системная утилита для инспекции BPF программ (требует `linux-tools-common`).

### Режимы Data Plane и их особенности

| Режим | Инструмент диагностики | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **Standard (iptables)** | `iptables-save`, `calicoctl node status` | Совместимость со старыми ядрами, предсказуемость | Линейный перебор правил O(N), снижение производительности при >1000 политик |
| **eBPF** | `bpftool`, `calico-node -bpf counters dump` | Высокая производительность, Source IP для NodePort, DSR | Требует ядро Linux 5.3+, смонтированную BPF FS |
| **nftables** | `nft list ruleset` | Современная альтернатива, лучшая производительность | Требует Calico v3.29+, Linux с поддержкой nftables (RHEL 9, Debian 12+) |
| **VPP** | `vppctl` | Максимальная производительность для высоконагруженных задач | Специфичные требования к ядру и конфигурации |

### Ключевые порты Calico

| Порт | Протокол | Назначение | Компонент |
| :--- | :--- | :--- | :--- |
| 179 | TCP | BGP peerings | BIRD |
| 4789 | UDP | VXLAN инкапсуляция | Felix |
| 4789 | UDP | IPIP инкапсуляция | Felix |
| 51820 | UDP | WireGuard шифрование | WireGuard |
| 9091 | TCP | Prometheus метрики | Felix |
| 9093 | TCP | Prometheus.alertmanager | Typha (опционально) |

## Предварительные проверки

Перед диагностикой убедитесь, что Calico установлен корректно:

```bash
# Проверка статуса подов Calico
kubectl get pods -n calico-system
# → Все поды должны быть в статусе Running

# Проверка статуса узлов
kubectl get nodes
# → Все узлы в статусе Ready

# Проверка версии Calico
calicoctl version
# → Client Version:    v3.33.x
# → Cluster Version:   v3.33.x

# Проверка доступа к CRD
calicoctl get ippool
# → Список пулов IP-адресов

# Проверка BGP-сессий
calicoctl node status
# → Состояние BGP-сессий со всеми узлами
```

## Практические сценарии

### Диагностика в режиме eBPF

Если в кластере включен eBPF, стандартные правила `iptables` отсутствуют. Для отладки используйте внутренние команды контейнера `calico-node`:

```bash
# Проверка, что eBPF активен
kubectl logs -n calico-system ds/calico-node -c calico-node | grep "BPF enabled"
# → BPF program calico古镇 is loaded

# Дамп счетчиков eBPF (пакеты, сбросы, пропуски)
kubectl exec -it -n calico-system <calico-node-pod> -- calico-node -bpf counters dump
# → Active SimDs: 5
# → Packets passed: 123456
# → Bytes passed: 98765432

# Просмотр примененных политик к конкретному интерфейсу
kubectl exec -it -n calico-system <calico-node-pod> -- calico-node -bpf policy dump <iface-name> ingress
# → Policy: allow-unknown-dst
# → Rules: 1

# Проверка, что eBPF заменил kube-proxy
kubectl get configmap -n kube-system kube-proxy -o yaml | grep mode
# → mode: "calico" (или отсутствие kube-proxy подов)
```

### Диагностика в режиме nftables

В Calico v3.29+ по умолчанию используется nftables вместо iptables:

```bash
# Проверка правил nftables
nft list ruleset | grep cali
# → table ip calico { ... }

# Просмотр цепочек Calico
nft list chain ip calico cali-postrouting
# → chain cali-postrouting { ... }

# Проверка счетчиков пакетов
nft list ruleset | grep -A2 "counter"
# → counter cali-1234 { ... packets 1234 bytes 567890 }

# Сравнение с iptables (если используется legacy)
iptables-save -c -t filter | grep cali
# → Правила Calico в iptables (не должны присутствовать при nftables)
```

### Управление и очистка IPAM

Проблемы с "утечкой" IP-адресов (IP leaks) возникают при некорректном удалении узлов или сбоях в работе CNI:

```bash
# Проверка консистентности выделенных IP-адресов
calicoctl ipam check -o report.json
# → Successfully checked IPAM: 0 inconsistencies

# Освобождение неиспользуемых (утекших) адресов на основе отчета
calicoctl ipam release --from-report=report.json
# → Released 5 IP addresses from report

# Просмотр текущих блоков IP-адресов
calicoctl ipam show --show-blocks
# → IPv4 Pools
# →   CIDR: 10.244.0.0/16
# →   Allocations: 254/65536
# → IPv4 IPAM Blocks
# →   10.244.1.0/26: 16 IPs allocated (node: node-1)

# Просмотр использования пулов
calicoctl ipam show
# → IPv4 Pools
# →   CIDR: 10.244.0.0/16
# →   Allocations: 254/65536
```

> Дополнительно: [IPAM в Kubernetes](../../../Networking/Network/CNI/ipam.md)

### Мониторинг и метрики (Prometheus)

Для сбора метрик Felix и Typha необходимо включить их в конфигурации:

```bash
# Включение метрик Felix (по умолчанию порт 9091)
calicoctl patch felixconfiguration default --patch '{"spec": {"prometheusMetricsEnabled": true}}'
# → Successfully patched 1 resource

# Включение метрик Typha (если используется)
kubectl patch deployment calico-typha -n calico-system --type=merge -p '{"spec":{"template":{"spec":{"containers":[{"name":"calico-typha","ports":[{"name":"metrics","containerPort":9093}]}}]}}}'

# Проверка метрик с узла
curl http://localhost:9091/metrics
# → felix_active_local_endpoints 5
# → felix_cluster_num_policies 12
# → felix_execution_time_seconds 0.001234
# → wireguard_sent_bytes_total 123456

# Ключевые метрики для мониторинга:
# felix_active_local_endpoints - количество активных подов на узле
# felix_cluster_num_policies - количество политик в кластере
# felix_execution_time_seconds - время применения политик
# felix_go_goroutines - количество горутин Felix
# felix_cluster_num_hosts - количество узлов в кластере
```

### Резервное копирование ресурсов Calico

Рекомендуется регулярно экспортировать конфигурацию, которая не управляется через GitOps (например, динамические IPAM-блоки):

```bash
# Резервное копирование основных ресурсов
calicoctl get ippool -o yaml > calico-ippools.yaml
calicoctl get globalnetworkpolicy -o yaml > calico-gnp.yaml
calicoctl get hostendpoint -o yaml > calico-hep.yaml
calicoctl get bgpconfiguration -o yaml > calico-bgp.yaml
calicoctl get felixconfiguration -o yaml > calico-felix.yaml
calicoctl get bgppeer -o yaml > calico-bgppeer.yaml

# Резервное копирование всех ресурсов Calico
for resource in ippool globalnetworkpolicy hostendpoint bgpconfiguration felixconfiguration bgppeer globalnetworkset serviceaccount; do
  calicoctl get $resource -o yaml > "calico-$resource.yaml" 2>/dev/null
done

# Просмотр созданного бэкапа
ls -la calico-*.yaml
# → calico-bgp.yaml
# → calico-bgppeer.yaml
# → calico-felix.yaml
# → calico-globalnetworkpolicy.yaml
# → calico-ippool.yaml
```

### Проверка статуса WireGuard

Если включено шифрование, проверьте наличие публичных ключей у узлов:

```bash
# Проверка ключей на всех узлах
calicoctl get nodes -o wide
# → В выводе должен присутствовать столбец или поле с публичным ключом WireGuard

# Включение WireGuard (если не включен)
calicoctl patch felixconfiguration default --patch '{"spec": {"wireguardEnabled": true}}'
# → Successfully patched 1 resource

# Проверка шифрования через метрики
curl http://localhost:9091/metrics | grep wireguard
# → wireguard_sent_bytes_total 123456
# → wireguard_received_bytes_total 654321

# Проверка статуса WireGuard на узле
kubectl exec -n calico-system <calico-node-pod> -- wg show
# → interface: wireguard.cali
# →   public key: <key>
# →   private key: (hidden)
# →   listening port: 51820
```

### Проверка версий и совместимости

```bash
# Проверка версии Calico на всех узлах
kubectl get ds calico-node -n calico-system -o jsonpath='{.spec.template.spec.containers[0].image}'
# → docker.io/calico/node:v3.33.0

# Проверка версии ядра на узлах
uname -r
# → 5.15.0-78-generic (для eBPF требуется >=5.3)

# Проверка версии Kubernetes
kubectl version --short
# → Server Version: v1.29.3

# Проверка совместимости версий
# Calico v3.29+ поддерживает: Kubernetes 1.27-1.30
# Calico v3.28+ поддерживает: Kubernetes 1.26-1.29
```

### Диагностика DNS-резолвинга

```bash
# Проверка доступности CoreDNS
kubectl get pods -n kube-system -l k8s-app=kube-dns
# → kube-dns-5d78c9869d-xyz12   3/3     Running

# Проверка DNS изнутри пода
kubectl run dns-test --image=busybox --restart=Never -- nslookup kubernetes.default
# → Server:    10.96.0.10
# → Name:      kubernetes.default.svc.cluster.local

# Проверка DNS-правил Calico
calicoctl get globalnetworkpolicy allow-dns-global -o yaml
# → Должно быть разрешено UDP/TCP порт 53 к CoreDNS

# Проверка DNS-трафика через nftables
nft list ruleset | grep -A5 "kube-dns"
# → Правила, разрешающие трафик к CoreDNS
```

### Диагностика NodePort и Ingress

```bash
# Проверка доступности NodePort
kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.spec.ports[0].nodePort}'
# → 30080

# Проверка через curl снаружи
curl -v http://<node-ip>:30080/healthz
# → HTTP/1.1 200 OK

# Проверка preDNAT политик
calicoctl get globalnetworkpolicy -o wide | grep preDNAT
# → pre-dnat-nginx    true    100

# Проверка IPVS (если используется)
ipvsadm -Ln | grep <nodeport>
# → TCP  192.168.1.10:30080 rr
```

### Диагностика межсервисного взаимодействия

```bash
# Проверка NetworkPolicy в namespace
kubectl get networkpolicy -n production
# → NAME              POD-SELECTOR   AGE
# → deny-all          <none>         5m
# → allow-frontend    app=frontend   3m

# Просмотр правил через calicoctl
calicoctl get networkpolicy -n production -o wide
# → NAME              ORDER   SELECTOR              AGE
# → deny-all          1000    all()                 5m
# → allow-frontend    10      app == 'frontend'     3m

# Тест связности между подами
kubectl exec -n production <frontend-pod> -- wget -qO- --timeout=3 http://backend.production.svc:8080
# → successful (или connection timeout при блокировке)

# Проверка DNS-резолвинга для сервисов
kubectl exec -n production <frontend-pod> -- nslookup backend.production.svc
# → Server:    10.96.0.10
# → Name:      backend.production.svc.cluster.local
```

## Устранение неисправностей (Troubleshooting)

### Расширенная таблица неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Потеря SSH-доступа** | HostEndpoint заблокировал порт 22 | Проверьте `FailsafePorts` в `FelixConfiguration` или создайте GlobalNetworkPolicy с разрешением порта 22. |
| **Timeout в eBPF режиме** | Ядро Linux < 5.3 или не смонтирована BPF FS | Убедитесь, что `/sys/fs/bpf` смонтирована на всех узлах. Проверьте версию ядра (`uname -r`). |
| **NodePort не работает** | Конфликт с kube-proxy или отсутствие `preDNAT` | В eBPF режиме Calico должен полностью заменять kube-proxy. В Standard режиме добавьте `preDNAT: true` в политику. |
| **Ошибка BGP (Connection Refused)** | Закрыт порт 179/TCP | Разрешите 179/TCP между всеми IP узлов. Проверьте статус: `calicoctl node status`. |
| **Несоответствие MTU** | Инкапсуляция (VXLAN/IPIP) | MTU в `FelixConfiguration` должен быть на 20-50 байт меньше физического интерфейса (например, 1450). |
| **Поды не могут резолвить DNS** | Отсутствуют правила egress для DNS | Добавьте GlobalNetworkPolicy, разрешающий UDP/TCP 53 к CoreDNS. |
| **Поды не могут общаться между собой** | Default-deny без разрешающих правил | Добавьте разрешающие NetworkPolicy для необходимых портов/протоколов. |
| **Felix не применяет политики** | Felix crashed или не запущен | Проверьте логи: `kubectl logs -n calico-system ds/calico-node -c calico-node`. |
| **IPAM исчерпан** | Все адреса в пуле выделены | Расширьте IPPool: `calicoctl apply -f <new-pool.yaml>` или очистите утекшие IP. |
| **BGP не устанавливает сессии** | Брандмауэр блокирует порт 179 | Проверьте firewall: `iptables -L -n | grep 179` или `nft list ruleset | grep 179`. |
| **WireGuard не шифрует трафик** | Ключи не сгенерированы | Проверьте: `calicoctl get nodes -o wide` (наличие публичного ключа). |
| **Высокая нагрузка на CPU** | Слишком много политик или подов | Оптимизируйте количество политик; включите Typha для кластеров >50 узлов. |
| **Потеря IP после перезапуска узла** | host-local IPAM без синхронизации | Переход на Integrated IPAM (etcd/CRD) для сохранения состояния. |

### Пошаговые алгоритмы диагностики

#### Алгоритм 1: Под не может выйти в интернет

```bash
# 1. Проверьте DNS-резолвинг
kubectl exec -n <ns> <pod> -- nslookup google.com
# → Если timeout: проверьте DNS-политики

# 2. Проверьте egress-политики
calicoctl get networkpolicy -n <ns> -o wide
# → Должна быть разрешающая egress-политика

# 3. Проверьте IP-маршрутизацию
kubectl exec -n <ns> <pod> -- ip route
# → Должен быть default route через cali* интерфейс

# 4. Проверьте NAT
iptables -t nat -L -n | grep MASQUERADE
# → Должно быть правило MASQUERADE для Pod CIDR

# 5. Проверьте connectivity до шлюза
kubectl exec -n <ns> <pod> -- ping -c 3 10.96.0.1 (CoreDNS IP)
```

#### Алгоритм 2: Под не может достичь другого пода

```bash
# 1. Проверьте DNS-резолвинг
kubectl exec -n <ns> <source-pod> -- nslookup <target-service>.<target-ns>.svc
# → Если не резолвится: проблема с DNS

# 2. Проверьте NetworkPolicy
kubectl get networkpolicy -n <target-ns>
# → Есть ли политика, разрешающая входящий трафик?

# 3. Проверьте GlobalNetworkPolicy
calicoctl get globalnetworkpolicy -o wide
# → Есть ли política, блокирующая трафик?

# 4. Проверьте IP-адрес целевого пода
kubectl get pod -n <target-ns> <target-pod> -o wide
# → Используйте IP для прямого теста

# 5. Проверьте доступность порта
kubectl exec -n <ns> <source-pod> -- curl -v http://<target-ip>:<port>
# → Если connection timeout: проблема с сетевыми правилами
```

#### Алгоритм 3: Felix не применяет политики

```bash
# 1. Проверьте статус Felix
kubectl get ds -n calico-system calico-node -o jsonpath='{.status.numberReady}'
# → Должно совпадать с numberDesired

# 2. Проверьте логи Felix
kubectl logs -n calico-system ds/calico-node -c calico-node --tail=50 | grep -i error
# → Ищите ошибки в применении правил

# 3. Проверьте конфигурацию Felix
calicoctl get felixconfiguration default -o yaml
# → Убедитесь, что prometheusMetricsEnabled: true

# 4. Проверьте Connectivity до API
kubectl exec -n calico-system <calico-node-pod> -- calicoctl node status
# → BGP сессии должны быть established

# 5. Перезапустите Felix (если необходимо)
kubectl rollout restart daemonset calico-node -n calico-system
```

### Интерпретация логов Felix

```bash
# Просмотр логов Felix
kubectl logs -n calico-system ds/calico-node -c calico-node --tail=100

# Ключевые сообщения об ошибках:
# → "Failed to apply policy" - ошибка применения политики
# → "IPAM allocation failed" - исчерпание пула IP
# → "BGP peer down" - разрыв BGP-сессии
# → "WireGuard handshake failed" - проблема с шифрованием

# Фильтрация по уровню логирования
kubectl logs -n calico-system ds/calico-node -c calico-node --tail=100 | grep -E "(ERROR|WARN)"

# Просмотр логов Typha (если используется)
kubectl logs -n calico-system deploy/calico-typha --tail=50
```

## Обновление и откат Calico

### Процедура обновления

> **Важно:** Перед обновлением создайте резервную копию всех ресурсов Calico.

```bash
# 1. Создание бэкапа
for resource in ippool globalnetworkpolicy hostendpoint bgpconfiguration felixconfiguration bgppeer; do
  calicoctl get $resource -o yaml > "backup-calico-$resource.yaml" 2>/dev/null
done

# 2. Проверка текущей версии
calicoctl version
# → Cluster Version:   v3.32.x

# 3. Обновление через Tigera Operator (рекомендуемый способ)
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/manifests/tigera-operator.yaml

# 4. Проверка статуса обновления
kubectl get tigerainstallations.operator.tigera.io default -o jsonpath='{.status.calicoVersion}'
# → v3.33.0

# 5. Проверка подов после обновления
kubectl get pods -n calico-system
# → Все поды должны быть Running с новой версией
```

### Откат Calico

```bash
# 1. Восстановление ресурсов из бэкапа
calicoctl apply -f backup-calico-ippool.yaml
calicoctl apply -f backup-calico-globalnetworkpolicy.yaml
# ... и так далее для всех ресурсов

# 2. Откат Tigera Operator (если обновляли через Operator)
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.32.0/manifests/tigera-operator.yaml

# 3. Проверка отката
calicoctl version
# → Cluster Version:   v3.32.x
```

## Лучшие практики

1. **Регулярный мониторинг**: Настройте Prometheus и Grafana для отслеживания метрик Felix и Typha.
2. **Логирование**: Централизуйте логи Calico через journald или fluentd.
3. **Резервное копирование**: Экспортируйте ресурсы Calico перед обновлениями.
4. **Версионирование**: Используйте GitOps для управления конфигурацией Calico.
5. **Тестирование**: Тестируйте политики в staging перед применением в production.
6. **Минимум политик**: Избегайте создания >10000 политик — это влияет на время применения.
7. **Использование tiers**: Разделяйте политики по уровням для лучшей организации.
8. **Мониторинг IPAM**: Регулярно проверяйте `calicoctl ipam show` для обнаружения утечек.
9. **Проверка версий**: Убедитесь, что версия Calico совместима с Kubernetes и ядром Linux.
10. **Документирование**: Ведите документацию по всем настроенным политикам и сценариям.

## Дополнительная информация

### Связанные ресурсы
* **Практические сценарии**: [Сценарии Calico: Периметральный файрвол](./scenarios.md)
* **Архитектура**: [Calico HostEndpoint и GlobalNetworkPolicy — Обзор](./index.md)
* **Сетевая модель K8s**: [Обзор сетевой модели Kubernetes](../../../Networking/Network/network_overview.md)
* **eBPF Технологии**: [eBPF в Kubernetes: Замена kube-proxy](../../../Networking/Network/CNI/ebpf.md)
* **IPAM Детали**: [IPAM (IP Address Management) в Kubernetes](../../../Networking/Network/CNI/ipam.md)
* **WireGuard настройка**: [VPN в контейнерах: WireGuard](../../../Networking/Tunnels/vpn_in_containers.md)

### Инструменты отладки (CLI)
* **calicoctl**: [Официальная документация calicoctl](https://docs.tigera.io/calico/latest/reference/calicoctl/)
* **bpftool**: Системная утилита для инспекции BPF программ (требует `linux-tools-common`)
* **nft**: Утилита для работы с nftables (требуется для Calico v3.29+)
* **wg**: Утилита WireGuard (для диагностики шифрования)

### Версионная совместимость

| Версия Calico | Поддерживаемые версии Kubernetes | Ядро Linux (мин.) | Примечания |
| :--- | :--- | :--- | :--- |
| v3.33.x | 1.27 - 1.30 | 4.15 (nftables: 5.10) | Актуальная версия |
| v3.32.x | 1.26 - 1.29 | 4.15 (eBPF: 5.3) | Стабильная версия |
| v3.29.x | 1.25 - 1.28 | 4.15 (nftables: 5.10) | Версия с nftables по умолчанию |
| v3.27.x | 1.24 - 1.27 | 4.15 | Последняя версия без nftables |
