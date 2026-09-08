# Вопросы по Kubernetes Networking для собеседований

## Определения

**Interview Questions** — подборка вопросов и ответов по сетевому стеку Kubernetes, предназначенная для подготовки к техническим собеседованиям на позиции DevOps/SRE/System Administrator.

---

## Блок 1: Основы контейнерного networking

### Как работает сеть в Kubernetes?

Kubernetes использует модель IP-per-Pod: каждый под получает уникальный IP-адрес в пределах кластера. Сетевая связность обеспечивается CNI-плагином (Calico, Cilium, Flannel), который настраивает veth-пары, маршрутизацию и IPAM (управление IP-адресами).

### Что такое veth pair?

Veth pair (Virtual Ethernet Pair) — виртуальный сетевой кабель в Linux. Один конец находится в namespace контейнера, другой — в namespace хоста (или bridge). Трафик, поступающий на один конец, мгновенно появляется на другом.

### Что такое network namespace?

Network namespace — изолированная область в ядре Linux, содержащая собственный набор сетевых интерфейсов, IP-адресов, таблиц маршрутизации и правил iptables/nftables. Каждый контейнер получает свой network namespace.

### Как пакет проходит от пода на другом узле до пода?

1. Пакет выходит из namespace пода через veth-пару на узел
2. CNI обрабатывает пакет (инкапсуляция VXLAN/Geneve или прямая маршрутизация)
3. Пакет маршрутизируется на целевой узел
4. На целевом узле CNI деинкапсулирует пакет и направляет его в namespace целевого пода

### В чем разница между Overlay и Native Routing?

| Overlay | Native Routing |
| :--- | :--- |
| Инкапсуляция пакетов (VXLAN/Geneve, +50 байт overhead) | Прямая маршрутизация без инкапсуляции |
| MTU = 1450 (при физическом 1500) | MTU = 1500 (полный) |
| Работает в любой L3-сети | Требует BGP или статических маршрутов |
| Проще в настройке | Производительнее (нет overhead CPU на инкапсуляцию) |

---

## Блок 2: kube-proxy и Service networking

### Какие режимы работы kube-proxy существуют?

- **iptables** — стандартный, цепочки правил O(n). Для кластеров <500 сервисов
- **IPVS** — хеш-таблицы O(1), множество алгоритмов балансировки. Для >500 сервисов
- **nftables** — modern replacement iptables (Kubernetes 1.31+), атомарные обновления
- **eBPF** — полная замена kube-proxy через Cilium/Calico eBPF. Максимальная производительность

### Как работает ClusterIP?

ClusterIP — виртуальный IP-адрес, привязанный к Service. kube-proxy на каждом узле настраивает правила DNAT, перенаправляющие трафик с ClusterIP на реальные IP-адреса подов-эндпоинтов. Балансировка выполняется случайным образом (iptables) или через алгоритмы IPVS.

### Что такое hairpin NAT?

Hairpin NAT позволяет поду обращаться к ClusterIP сервиса, в котором он участвует. Пакет от пода идет на ClusterIP, kube-proxy выполняет DNAT на IP другого пода (или того же), и ядро маршрутизирует трафик через loopback интерфейс.

### Как работает Session Affinity?

Session Affinity привязывает клиента к конкретному поду по Source IP. В iptables реализуется через запись в conntrack, в IPVS — через хеш-таблицу. Время жизни привязки определяется параметром `sessionAffinityConfig.clientIP.timeoutSeconds`.

### Что такое EndpointSlice?

EndpointSlice — масштабируемая альтернатива Endpoints. Разбивает большие списки эндпоинтов на несколько объектов (по умолчанию до 100 эндпоинтов на Slice). Снижает нагрузку на API-сервер и kube-proxy при частых обновлениях.

---

## Блок 3: NetworkPolicy

### Что такое NetworkPolicy?

NetworkPolicy — декларативный ресурс Kubernetes для управления сетевым трафиком на уровнях L3/L4 (IP/порты). Позволяет реализовать Zero Trust через изоляцию трафика между namespace, подами и CIDR.

### Как работает Default Deny?

Default Deny — политика, которая запрещает весь трафик по умолчанию. Создается NetworkPolicy с пустым `podSelector: {}` и без правил ingress/egress. Все поды, попадающие под селектор, переходят в режим "запрещено всё, что не разрешено явно".

### Что такое AdminNetworkPolicy (ANP)?

AdminNetworkPolicy — ресурс, позволяющий администраторам кластера задавать глобальные правила безопасности, которые имеют более высокий приоритет и не могут быть переопределены разработчиками в неймспейсах.

### Поддерживает ли стандартная NetworkPolicy фильтрацию по DNS (FQDN)?

Нет, стандартная NetworkPolicy работает только на уровнях L3/L4 (IP/порты). Фильтрация по DNS-именам требует использования Service Mesh (Istio) или продвинутых CNI (Cilium).

### В чем разница между namespaceSelector и podSelector?

- `namespaceSelector` выбирает поды во всех неймспейсах с указанными метками
- `podSelector` выбирает поды только внутри того же неймспейса, где создана политика

### Что будет если удалить все NetworkPolicy из namespace?

Namespace вернется в режим Default Allow. Любой под сможет свободно взаимодействовать со всеми подами во всем кластере. Это критическая уязвимость безопасности.

### Что будет если `policyTypes` не указан, но `ingress`/`egress` определены?

Политика **не применяется**. Kubernetes игнорирует правила, если направление не включено в `policyTypes`. Это самая частая ошибка.

### Что будет если `ingress: []` с `policyTypes: [Ingress]`?

Default Deny для Ingress. Весь входящий трафик к подам будет заблокирован. Однако это работает аддитивно: если другая политика разрешает Ingress, трафик пройдет (логическое ИЛИ).

### Как работает conntrack с NetworkPolicy?

NetworkPolicy является **stateful**. Если Egress-трафик разрешен, ответный Ingress-трафик (return traffic) разрешается автоматически через conntrack. Не нужно создавать зеркальные правила для ответов.

### Почему `ipBlock` не работает для East-West трафика?

IP-адреса подов эфемерны и меняются при каждом перезапуске. `ipBlock` фиксирует CIDR, который не отражает текущие IP подов. Для East-West используйте `podSelector` + `namespaceSelector`.

### Как комбинируются `namespaceSelector` и `podSelector`?

В одном элементе массива `from` — логическое И. В разных элементах — логическое ИЛИ.

### Что будет если Default Deny Egress без DNS?

Поды не смогут разрешать DNS-имена. Всё, что использует Service Discovery, перестанет работать. Всегда создавайте разрешающую политику для DNS (порт 53) ПЕРЕД Default Deny Egress.

### Как отличить проблему NetworkPolicy от conntrack?

- `conntrack -S` — если много `dropped` по `nf_conntrack_full`, проблема в размере таблицы
- NetworkPolicy-проблемы проявляются как `connection timeout`
- conntrack-проблемы проявляются как `nf_conntrack: table full, dropping packet` в dmesg

### Как протестировать NetworkPolicy перед применением?

1. `kubectl apply --dry-run=client` — синтаксис
2. `kubectl exec -it <pod> -- curl -v <target>` — реальный тест
3. `hubble observe --verdict DROPPED` (Cilium) — визуализация
4. Audit mode (Cilium/Calico) — мониторинг без блокировки

---

## Блок 4: DNS в Kubernetes

### Как работает DNS в Kubernetes?

CoreDNS является внутренним DNS-сервером кластера. Он формирует FQDN для сервисов вида `<service-name>.<namespace>.svc.cluster.local` и подов через Headless Service. Поды используют DNS через ClusterIP сервис `kube-dns` (10.96.0.10 по умолчанию).

### Зачем нужен NodeLocal DNSCache?

NodeLocal DNSCache — DaemonSet, кэширующий DNS-запросы на каждом узле. Решает проблемы:
- UDP race conditions в conntrack при перезапуске CoreDNS
- Снижает нагрузку на CoreDNS
- Уменьшает задержки DNS-запросов

### Что такое ndots:5 и как он влияет на DNS?

Параметр `ndots:5` в `/etc/resolv.conf` пода определяет, сколько точек должно быть в доменном имени для прямого запроса. Имена с менее чем 5 точками сначала ищутся с добавлением search domains кластера, что увеличивает количество DNS-запросов.

### Как CoreDNS обрабатывает внешние запросы?

CoreDNS пересылает внешние запросы (не.cluster.local) через плагин `forward` в upstream DNS-серверы, указанные в `/etc/resolv.conf` узла или настроенные через `stubDomains`.

---

## Блок 5: CNI и eBPF

### Какие CNI-плагины поддерживают NetworkPolicy?

- **Calico:** Полная поддержка Kubernetes NetworkPolicy + GlobalNetworkPolicy
- **Cilium:** Полная поддержка + расширенные CiliumNetworkPolicy (L7, FQDN)
- **Flannel:** Не поддерживает NetworkPolicy (требует Canal)
- **AWS VPC CNI / Azure CNI:** Используют Security Groups облачного провайдера

### Как eBPF заменяет kube-proxy?

eBPF-программы (Cilium, Calico eBPF) загружаются в ядро Linux и перехватывают трафик на ранних этапах (TC, XDP). Они реализуют балансировку, NAT и политики через BPF Maps с O(1) производительностью, полностью заменяя iptables/IPVS правила kube-proxy.

### Что такое Cilium Identity?

Cilium Identity — уникальный числовой идентификатор, присваиваемый группе подов с идентичным набором меток. Используется для сетевых политик вместо IP-адресов, что обеспечивает стабильность правил при пересоздании подов.

### В чем преимущество Cilium перед Calico?

- Встроенная L7-инспекция (HTTP, gRPC)
- Нативная замена kube-proxy (kube-proxy replacement)
- Hubble для сетевой видимости
- Bandwidth Manager для управления полосой пропускания
- Service Mesh без sidecar (Ambient через Ztunnel)

### Какой CNI выбрать для production?

| Сценарий | Рекомендация |
| :--- | :--- |
| Max производительность + L7 безопасность | Cilium (ядро 5.10+) |
| Кластер >1000 узлов, BGP | Calico |
| Простой edge / тесты (<50 узлов) | Flannel |
| Multi-NIC / SR-IOV для NFV | Multus + SR-IOV |

---

## Блок 6: Диагностика и troubleshooting

### Под не получает IP. Как диагностировать?

1. `kubectl describe pod <pod>` — проверить Events
2. `kubectl -n kube-system get pods -l k8s-app=cilium` — статус CNI
3. `kubectl -n kube-system logs -l k8s-app=cilium` — логи CNI
4. Проверить CIDR: `kubectl cluster-info dump | grep cluster-cidr`
5. Проверить IPAM пул

### DNS не работает внутри кластера. Как диагностировать?

1. `kubectl -n kube-system get pods -l k8s-app=kube-dns` — статус CoreDNS
2. `kubectl run debug --image=busybox --rm -it --restart=Never -- nslookup kubernetes.default` — тест DNS
3. `kubectl -n kube-system logs -l k8s-app=kube-dns` — логи CoreDNS
4. `cat /etc/resolv.conf` внутри пода — проверка nameserver
5. NetworkPolicy: разрешен ли egress на порт 53

### conntrack table full. Что делать?

```bash
# Проверка
sudo sysctl net.netfilter.nf_conntrack_count
sudo sysctl net.netfilter.nf_conntrack_max

# Решение
sudo sysctl -w net.netfilter.nf_conntrack_max=1048576
sudo sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=7200
```

### Как проверить MTU в поде?

```bash
kubectl exec <pod-name> -- ip link show eth0
# → MTU: 1450 (для VXLAN)

# Тест Path MTU
ping -M do -s 1472 <destination-ip>
```

### Как сохранить Source IP клиента?

Установить `externalTrafficPolicy: Local` в Service. Это предотвратит SNAT и сохранит реальный IP клиента. Используется для WAF, rate limiting и логирования.

---

## Блок 7: Продвинутые темы

### Как работает IPVS балансировка?

IPVS использует хеш-таблицы O(1) для хранения виртуальных серверов (VIP) и реальных серверов (backend Pod IPs). Поддерживает алгоритмы: rr (round robin), lc (least connections), sh (source hashing), sed (shortest expected delay), nq (never queue).

### Что такое DSR (Direct Service Return)?

DSR — технология, при которой входящий трафик проходит через балансировщик, а ответ от пода направляется клиенту напрямую, минуя обратный проход через балансировщик. Снижает нагрузку на LB и задержки. Поддерживается в Cilium.

### Как работает Graceful Termination в Kubernetes?

1. Pod получает сигнал SIGTERM
2. Pod переходит в статус Terminating
3. kube-proxy помечает pod как Weight: 0 в IPVS (новые соединения не направляются)
4. Активные соединения продолжают обслуживаться
5. По истечении `terminationGracePeriodSeconds` pod удаляется

### Что такое Topology Aware Routing?

Topology Aware Routing позволяет направлять трафик на эндпоинты в той же зоне доступности (Availability Zone). Настройки: `internalTrafficPolicy: Local` + `topologyKeys`. Снижает задержки и исключает межзонный трафик.

### В чем разница между Ingress и Gateway API?

| Ingress | Gateway API |
| :--- | :--- |
| Простой L7-роутинг | L4-L7, расширенная маршрутизация |
| Ограниченная модель безопасности | Ролевая модель (Infra/App Dev) |
| Аннотации для расширения | CRDs для расширения |
| Нет нативной поддержки TCP/UDP | Поддержка TCPRoute, UDPRoute |
| Legacy (рекомендуется Gateway API) | Стандарт Kubernetes (GA) |

### Когда использовать Service Mesh?

Service Mesh используется когда:
- Требуется mTLS между сервисами
- Нужна L7-видимость и маршрутизация
- Необходим circuit breaking, retry, rate limiting на уровне приложения
- Есть микросервисная архитектура с десятками сервисов

Для простых приложений (<10 сервисов) Service Mesh добавляет чрезмерный overhead.

---

## Блок 8: Производительность и оптимизация

### Как оптимизировать conntrack для высоконагруженных кластеров?

```bash
net.netfilter.nf_conntrack_max = 2097152
net.netfilter.nf_conntrack_tcp_timeout_established = 7200
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
net.netfilter.nf_conntrack_tcp_timeout_close_wait = 15
```

### Какой MTU использовать для VXLAN?

1450 байт (1500 - 50 байт overhead VXLAN). Несоответствие MTU приводит к фрагментации и проблемам с TLS-соединениями.

### Как снизить latency между подами?

1. Native routing вместо overlay (без инкапсуляции)
2. Topology Aware Routing (под在同一 зоне)
3. eBPF (Cilium) для обработки на уровне ядра
4. SOCKMAP для сшивания сокетов в ядре
5. NodeLocal DNSCache для DNS

### Какой CNI для максимальной производительности?

Cilium с native routing, eBPF kube-proxy replacement и BGP Control Plane. Обеспечивает O(1) балансировку, минимальный overhead и прямую маршрутизацию.

---

## См. также

- [kube-proxy](./kube-proxy.md) — детали режимов работы
- [NetworkPolicy](./network_policy.md) — сетевые политики
- [DNS в Kubernetes](./dns_deep_dive.md) — глубокое погружение
- [CNI и kube-proxy: роли](./cni_kube_proxy_roles.md) — взаимодействие компонентов

**[К списку разделов CNI](../cni_kube_proxy_roles.md)**
