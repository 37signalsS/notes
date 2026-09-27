# Выбор CNI и методы внешнего доступа в Kubernetes

## Определения

**CNI (Container Network Interface)** — стандарт интерфейса для организации сетевого взаимодействия контейнеров. Плагин CNI отвечает за выделение IP-адресов (IPAM) и обеспечение связности между подами на разных узлах кластера.

**MCS API (Multi-Cluster Services)** — стандарт Kubernetes (v1.30+) для обнаружения и взаимодействия сервисов между несколькими кластерами. Позволяет объединять эндпоинты в `ServiceImport` и `ServiceExport`, обеспечивая единое DNS-имя для распределенных нагрузок.

**IPv6 Dual-Stack** — режим работы, при котором подам и сервисам назначаются адреса обоих протоколов. В 2026 году является стандартом для Enterprise-решений из-за исчерпания IPv4-адресов в крупных Overlay-сетях.

**BGP (Border Gateway Protocol) Advertisement** — механизм, при котором CNI-плагин (Cilium, Calico) анонсирует IP-адреса сервисов или подов внешним маршрутизаторам. Это позволяет обращаться к ресурсам кластера напрямую из физической сети по кратчайшему пути (ECMP).

**L2 Announcement (ARP/NDP)** — метод анонсирования IP-адресов сервисов в локальной сети (L2-сегменте) через протоколы ARP (IPv4) или NDP (IPv6). Используется в Bare-metal средах (через MetalLB или встроенные функции Cilium) для реализации типа `LoadBalancer` без использования BGP.

**Direct Service Return (DSR)** — технология оптимизации L2/L3, при которой входящий трафик проходит через балансировщик, а ответ от пода направляется клиенту напрямую, минуя обратный проход через балансировщик. Снижает задержки и нагрузку на узлы балансировки.

**Gateway API** — современный стандарт Kubernetes (преемник Ingress), предоставляющий более гибкое и ролевое управление входящим трафиком (L4-L7), поддержку мультикластерности и расширенные функции балансировки.

**Topology Aware Routing** — механизм Kubernetes, позволяющий предпочитать эндпоинты в той же зоне доступности (Availability Zone), снижая задержки и исключая затраты на межзонный трафик.

**NodeLocal DNSCache** — оптимизационный DaemonSet, запускающий кэширующий DNS-агент на каждом узле. Снижает нагрузку на CoreDNS, минимизирует задержки и предотвращает race conditions в `nf_conntrack` при UDP-запросах.

**Proxy Protocol** — протокол (HAProxy), передающий исходный IP-адрес и порт клиента через LB на нижестоящий сервер. Актуален для MetalLB BGP и L2-режимов, а также для Gateway API контроллеров, работающих за внешним балансировщиком.

**BFD (Bidirectional Forwarding Detection)** — протокол быстрого обнаружения отказа линка. В связке с BGP обеспечивает переключение маршрутов за доли секунды, минуя стандартные таймеры BGP.

**Egress Gateway** — компонент (Service Mesh или CNI), принудительно направляющий весь исходящий трафик подов через фиксированные IP-адреса узлов-шлюзов для интеграции с внешними корпоративными фаерволами.

**NetworkPolicy** — декларативный ресурс Kubernetes для управления сетевыми политиками на L3/L4 (и L7 в расширенных реализациях). Позволяет реализовывать принцип Zero Trust через фильтрацию трафика между namespace, подами и CIDR.

**IPAM (IP Address Management)** — подсистема выделения и управления IP-адресами в CNI. Включает режимы: `host-local` (простой, без синхронизации), `cluster-pool` (CrashLoop-устойчивый), `eni` (облачный), `azure` (облачный).

**Overlay Network** — виртуальная сеть, инкапсулирующая пакеты подов в заголовки узла (VXLAN, Geneve, IPIP). Позволяет работать поверх любой L3-инфраструктуры, но добавляет overhead.

**Native Routing (Underlay)** — режим CNI, при котором поды получают реально маршрузируемые IP-адреса и общаются без инкапсуляции, используя стандартную таблицу маршрутизации ядра. Требует поддержки BGP или статических маршрутов на физическом оборудовании.

**kube-proxy-replacement** — режим работы CNI (Cilium, Calico eBPF), при котором стандартный `kube-proxy` полностью заменяется программами eBPF, исключая накладные расходы iptables/conntrack.

**hairpin NAT / hairpin mode** — механизм, позволяющий поду обращаться к ClusterIP сервиса, в котором он участвует, без потери пакета.

**MACVLAN / IPVLAN** — драйверы виртуализации сети в Docker/Linux, создающие несколько интерфейсов с отдельными MAC/IP на физическом NIC. Используются в высоконагруженных bare-metal сценариях вместо мостов.

**Multus CNI** — мета-CNI, позволяющий подам иметь несколько сетевых интерфейсов (например, один для стандартного кластерного трафика через Calico, второй для high-performance через SR-IOV).

---

## Основные концепции

### Критерии выбора CNI-плагина для производства

Выбор CNI влияет на производительность, безопасность (NetworkPolicy) и сложность эксплуатации кластера. При выборе для **production-сред** следует учитывать следующие факторы:

*   **Масштабируемость:** Способность плагина эффективно работать при росте количества узлов и сервисов в производственной среде.
*   **Безопасность:** Оценка функций безопасности, таких как встроенные NetworkPolicies, шифрование трафика и L7-инспекция.
*   **Простота использования:** Простота развертывания, настройки и обслуживания. Некоторые команды предпочитают простоту эксплуатации гибкости настроек.
*   **Поддержка сообщества:** Активное сообщество гарантирует непрерывное развитие, наличие документации и быструю помощь при возникновении проблем.
*   **Совместимость:** Соответствие плагина характеристикам ваших рабочих нагрузок и используемым средам исполнения.

| Плагин | Плюсы | Минусы | Лучшее применение | Overhead | Dual-Stack | eBPF-native |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Calico** | Масштабируемость, поддержка BGP и eBPF (на выбор). VPP-dataplane для экстремальных нагрузок. | Сложность настройки BGP-топологий. | Большие кластеры, гибридные сети. | Низкий (L3) / Средний (VXLAN) | Да (v1.20+) | Опционально |
| **Cilium** | eBPF-native, замена kube-proxy, L7-видимость (Hubble), встроенный Mesh. | Требование к ядру (5.10+). | High-load, Security-first, Kubernetes 1.30+. | Низкий (native) / Низкий (VXLAN) | Да (v1.12+) | Да |
| **Flannel** | Минимальный оверхед, простота. | Нет NetworkPolicies (нужен Canal). | Edge-вычисления, тестовые среды (<50 узлов). | Низкий | Нет | Нет |
| **Canal** | Политики Calico + простота Flannel. | Проект находится в режиме поддержки (Maintenance), уступает eBPF решениям. | Legacy-системы, где нужна совместимость. | Низкий | Ограниченно | Нет |
| **Weave** | Встроенное шифрование. | Проект практически не развивается (Archived status в 2026). Высокий оверхед на CPU. | Старые инсталляции (не рекомендуется для новых). | Высокий | Да | Нет |
| **AWS VPC CNI** | Нативная производительность ENI, поддержка Security Groups for Pods. | Лимиты по количеству IP на инстанс (требуется Prefix Delegation). | Amazon EKS. | Нет (native) | Ограниченно | Нет |
| **Azure CNI** | Интеграция с Azure VNet. | Лимиты IP/под, сложный DHCP. | AKS. | Нет (native) | Да | Нет |
| **SR-IOV CNI** | Прямой доступ к NIC, минимальный latency. | Сложность установки, требуется VT-d/IOMMU. | High-performance computing, NFV. | Минимальный | Нет | Нет |
| **Multus** | Мульти-сеть, SR-IOV + overlay вместе. | Сложность отладки, конфликты MAC. | Telecom, GPU workloads. | Зависит | Зависит | Зависит |

#### Decision Tree: выбор CNI

```
Нужен CNI для production-кластера?
├── Да, требуется максимальная производительность и безопасность L7
│   └── Выберите Cilium (ядро 5.10+, Kubernetes 1.28+)
├── Да, кластер >1000 узлов или требуется BGP без eBPF
│   └── Выберите Calico (BGP или VXLAN)
├── Да, simple edge или тестовая среда (<50 узлов)
│   └── Выберите Flannel (+ Canal для NetworkPolicy)
├── Да, требуется multi-NIC / SR-IOV для NFV
│   └── Выберите Multus + SR-IOV CNI
├── Нет, это облачный провайдер (EKS/AKS/GKE)
│   └── Используйте нативный CNI провайдера
└── Нет, legacy-система с ограниченным ядром
    └── Останьтесь на Calico iptables/nftables
```

#### Когда какой CNI выбирать:
- **Flannel:** Простое и легковесное решение, обычно используемое в небольших или тестовых кластерах. Использует оверлейную сеть (часто VXLAN) для обеспечения связности между узлами. Не поддерживает NetworkPolicies.
- **Calico:** Универсальный и высокопроизводительный плагин, известный своей масштабируемостью. Поддерживает различные топологии (BGP, VXLAN, IPIP), обеспечивает надежную защиту через NetworkPolicies и эффективную маршрутизацию.
- **Cilium:** Высоконагруженные системы, требования к глубокой наблюдаемости (Hubble) и замене `kube-proxy`.
- **AWS VPC CNI:** Специализированный плагин для EKS, использующий нативные возможности AWS VPC (ENI) для максимальной производительности и интеграции с Security Groups.
- **Azure CNI:** Аналогичное решение для AKS, интегрированное с Azure Virtual Network.

### Сравнение режимов работы CNI (Overlay vs Native Routing)

| Режим | Принцип | Преимущества | Недостатки | Использование |
| :--- | :--- | :--- | :--- | :--- |
| **Overlay (VXLAN/Geneve)** | Инкапсуляция пакетов подов в UDP-заголовок узла | Работает в любой L3-сети, изоляция, простота | Overhead ~50 байт, MTU 1450, дополнительная нагрузка на CPU | Тест/Dev, сети без BGP, гибридные облака |
| **Native Routing (BGP)** | Прямая маршрутизация реальных IP подов | Максимальная производительность, полный MTU 1500, видимость из физической сети | Требует BGP или статических маршрутов, пересечение CIDR невозможно | Production bare-metal, high-load |
| **IPIP** | Инкапсуляция IP в IP | Чуть выше производительность, чем VXLAN | Может блокироваться firewall'ами | Сети с фильтрацией UDP |

### Методы внешнего доступа

Для публикации приложений за пределами кластера используются четыре основных подхода:

| Метод | Уровень OSI | Реализация | Особенности | externalTrafficPolicy | Source IP |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **NodePort** | L4 | Порты 30000–32767 на каждом узле | Простота, высокий порт, нет выделенного IP | Поддерживается | Только с `Local` |
| **LoadBalancer** | L4 | MetalLB (L2/BGP) / Cilium LB / Облачный LB | Выделенный внешний IP, TCP/UDP | Поддерживается | Зависит от режима |
| **Ingress** | L7 | Traefik / NGINX Gateway Fabric / HAProxy | Маршрутизация по Host/Path, SSL-терминация | Настраивается в Service | Через X-Forwarded-For |
| **Gateway API** | L4-L7 | Envoy Gateway / Cilium / Istio | Ролевая модель, GAMMA, Direct Pod Targeting | Настраивается в Service | Через X-Forwarded-For или Proxy Protocol |

#### Decision Tree: внешний доступ в Bare-metal (on-prem)

```
Нужен внешний доступ в bare-metal кластер?
├── Нужен L7 (HTTP/HTTPS, gRPC, маршрутизация по хосту)?
│   ├── Gateway API CRDs установлены?
│   │   ├── Да → Используйте Gateway API (Envoy Gateway, Traefik v3, Cilium)
│   │   └── Нет → Используйте Ingress (Traefik/NGINX Gateway Fabric) или внешний прокси
├── Нужен L4 (TCP/UDP) с выделенным IP?
│   ├── Сетевое оборудование поддерживает BGP?
│   │   ├── Да → Используйте MetalLB BGP или Cilium BGP Control Plane
│   │   └── Нет → Используйте MetalLB L2
└── Простота критична, нет требований к L7?
    └── Используйте NodePort + внешний DNS/dnsmasq
```

---

## Практические сценарии

### Организация внешнего доступа в Bare-metal

В отсутствие облачного провайдера для реализации типа `LoadBalancer` используются два основных подхода:

1.  **Уровень L2 (ARP/NDP):**
    - **Решение:** MetalLB (рекомендуется) или Cilium (L2 Announcement).
    - **Принцип:** Один из узлов кластера "захватывает" внешний IP и отвечает на ARP-запросы.
    - **Плюсы:** Не требует настройки сетевого оборудования.
    - **Минусы:** Весь трафик идет через один узел (узкое место), переключение при отказе занимает время (зависит от ARP-кэша).

2.  **Уровень L3 (BGP):**
    - **Решение:** MetalLB + FRR-K8s или Cilium BGP Control Plane.
    - **Принцип:** Узлы устанавливают BGP-сессию с коммутатором (ToR) и анонсируют IP сервисов.
    - **Плюсы:** Балансировка трафика через ECMP (все узлы активны), мгновенный failover с BFD.
    - **Минусы:** Требует поддержки BGP на сетевом оборудовании.

#### Сравнение MetalLB vs Cilium LB

| Критерий | MetalLB | Cilium LB |
| :--- | :--- | :--- |
| **Архитектура** | Отдельный Controller + Speaker (DaemonSet) | Встроен в Cilium Agent |
| **BGP Backend** | FRR-K8s (рекомендуется) | Встроенный BGP Control Plane (Cilium 1.16+) |
| **L2 Announcement** | Да (ARP/NDP) | Да (встроенный) |
| **DSR** | Нет (трафик всегда через лидера/ECMP) | Да (опционально) |
| **Интеграция с NetworkPolicy** | Зависит от CNI (Calico/Cilium) | Нативная (eBPF) |
| **Сложность** | Средняя | Высокая (требует Cilium) |

### Оптимизация трафика: externalTrafficPolicy

Настройка `externalTrafficPolicy` в объекте Service критична для производительности и аудита:

- **`Cluster` (по умолчанию):** Трафик может пересылаться между узлами. Происходит SNAT, скрывающий IP клиента.
- **`Local`:** Трафик обрабатывается только на узлах, где есть поды сервиса.
    - **Сохраняется Source IP клиента.**
    - **Исключается лишний сетевой переход (hop).**
    - Рекомендуется для Ingress-контроллеров и высоконагруженных систем.

**Важно:** `externalTrafficPolicy: Local` требует, чтобы на каждом узле был хотя бы один готовый (Ready) под. В противном случае внешний балансировщик получит 503. Для LoadBalancer в Kubernetes 1.30+ поле `status.loadBalancer.ingress.ipMode` позволяет корректно маршрутизировать hairpin-трафик.

**Влияние `externalTrafficPolicy` на BGP-анонсы (Cilium/MetalLB):**

При использовании BGP для анонса IP-адресов сервисов значение `externalTrafficPolicy` определяет, с каких узлов будут анонсироваться маршруты:

- **`Cluster`:** Анонс происходит со **всех** узлов кластера, где работает BGP-спикер (Cilium Agent или MetalLB Speaker), даже если на узле нет локальных эндпоинтов сервиса. На роутере появляются избыточные маршруты к одному и тому же IP через все узлы.
- **`Local`:** Анонс происходит **только** с узлов, где находятся локальные эндпоинты (поды) сервиса. Это сокращает количество маршрутов в таблице роутера и исключает "пустые" переходы.

**ECMP на маршрутизаторе:**

Для балансировки трафика между несколькими равными по стоимости маршрутами (ECMP — Equal-Cost Multi-Path) необходимо включить соответствующую функцию на внешнем маршрутизаторе. На MikroTik RouterOS это параметр `multipath` в конфигурации BGP-инстанса:

```routeros
# Включение ECMP (multipath) в BGP-инстансе
/routing bgp instance set K8SBGP multipath=yes
```

После включения `multipath` маршрутизатор начинает распределять трафик между всеми активными маршрутами к одному и тому же IP-адресу. Для ограничения максимального количества параллельных маршрутов используется параметр `nexthop-group-limit` (или аналог в конкретной прошивке). Если на узле кластера только один под, но маршрут анонсируется со всех пяти узлов, ECMP распределит трафик равномерно между всеми пятью узлами, даже если только на одном из них есть целевой под. Поэтому сочетание `externalTrafficPolicy: Local` с ECMP дает оптимальную балансировку: маршруты анонсируются только с релевантных узлов, а роутер распределяет трафик между ними.

### Оптимизация трафика: Topology Aware Routing

Topology Aware Routing (`internalTrafficPolicy: Local` + `topologyKeys`) позволяет направлять трафик на эндпоинты в той же зоне:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: topology-aware-svc
spec:
  selector:
    app: my-app
  ports:
  - port: 80
    targetPort: 8080
  internalTrafficPolicy: Local
  topologyKeys:
  - "topology.kubernetes.io/zone"
  - "topology.kubernetes.io/region"
```

**Принцип работы:**
1. `internalTrafficPolicy: Local` ограничивает маршрутизацию только локальными эндпоинтами.
2. `topologyKeys` задает приоритет зон. Если в зоне нет эндпоинтов, трафик уходит в другие зоны.
3. Снижает задержки и исключает оплату межзонного трафика в облаках.

### Оптимизация DNS: NodeLocal DNSCache

Для production-кластеров критично развернуть NodeLocal DNSCache:

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/kubernetes/refs/heads/master/cluster/addons/dns/nodelocaldns/nodelocaldns.yaml
```

**Проблема, которую решает:** UDP-запросы к CoreDNS проходят через `nf_conntrack`. При высокой частоте запросов или при перезапуске CoreDNS возникает race condition (задержка 1–5 секунд или NXDOMAIN). NodeLocal DNSCache кэширует DNS локально на узле, снижая нагрузку на CoreDNS и исключая conntrack для большинства запросов.

### Оптимизация Source IP: Proxy Protocol

Для сохранения реального IP клиента через MetalLB BGP или внешний прокси используйте Proxy Protocol:

**Настройка MetalLB (через BGP Peer):**
```yaml
apiVersion: metallb.io/v1beta2
kind: BGPPeer
metadata:
  name: edge-router
  namespace: metallb-system
spec:
  myASN: 64512
  peerASN: 64512
  peerAddress: 192.168.10.1
  bfdProfile: fast-failover
```

**Настройка Ingress/Gateway контроллера (Traefik пример):**
```yaml
# values.yaml для Traefik
service:
  annotations:
    metallb.universe.tf/loadBalancerIPs: 192.168.10.50
providers:
  kubernetesGateway:
    externalTrafficPolicy: Local
  kubernetesCRD:
    externalTrafficPolicy: Local
```

### Использование Direct Service Return (DSR)

DSR полезен для приложений с асимметричным трафиком (небольшой запрос, огромный ответ, например, видеостриминг):

1. Клиент отправляет запрос на VIP балансировщика.
2. Балансировщик пересылает пакет на под без изменения Source IP.
3. Под отвечает **напрямую клиенту**, указывая в качестве адреса отправителя VIP балансировщика.

Для работы DSR в Cilium необходимо включить параметр:
```bash
# При установке через Helm
--set loadBalancer.dsr.enabled=true
```

### Практика: MetalLB (L2-режим)

```bash
# Установка через Helm (рекомендуется)
helm repo add metallb https://metallb.github.io/metallb
helm install metallb metallb/metallb \
  --namespace metallb-system --create-namespace \
  --set frrk8s.enabled=true

# Применение CRD
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.16.1/config/manifests/metallb-native.yaml
```

**Пул адресов (IPAddressPool):**
```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: main-pool
  namespace: metallb-system
spec:
  addresses:
  - 192.168.10.100-192.168.10.200
  - 2001:db8::100/120
```

**Анонсирование L2:**
```yaml
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: l2-adv
  namespace: metallb-system
spec:
  ipAddressPools:
  - main-pool
```

**Проверка:**
```bash
kubectl apply -f https://k8s.io/examples/admin/dns/dnsutils.yaml
kubectl expose deployment dnsutils --port=8080 --type=LoadBalancer
kubectl get svc dnsutils
# → EXTERNAL-IP: 192.168.10.100

# Проверка ARP-анонса
arp -a | grep 192.168.10.100
```

### Практика: MetalLB (BGP-режим)

```yaml
# BFD Profile для быстрого failover
apiVersion: metallb.io/v1beta1
kind: BFDProfile
metadata:
  name: fast-failover
  namespace: metallb-system
spec:
  receiveInterval: 300
  transmitInterval: 300
  detectMultiplier: 3
---
# BGP Peer
apiVersion: metallb.io/v1beta2
kind: BGPPeer
metadata:
  name: edge-router
  namespace: metallb-system
spec:
  myASN: 64512
  peerASN: 64512
  peerAddress: 192.168.10.1
  bfdProfile: fast-failover
---
# BGPAdvertisement
apiVersion: metallb.io/v1beta1
kind: BGPAdvertisement
metadata:
  name: bgp-adv
  namespace: metallb-system
spec:
  ipAddressPools:
  - main-pool
  communities:
  - 64512:100
```

**Диагностика:**
```bash
# Проверка BGP-сессий (через FRR-K8s)
kubectl logs -n metallb-system -l app.kubernetes.io/component=speaker | grep -i bgp

# Проверка соседства
kubectl get configurationstate -n metallb-system
```

### Практика: Gateway API (Envoy Gateway)

```bash
# 1. Установка Gateway API CRDs
kubectl apply -f https://raw.githubusercontent.com/kubernetes-sigs/gateway-api/v1.1.0/config/crd/standard/gwapi-std-crds.yaml

# 2. Установка Envoy Gateway
helm install eg oci://docker.io/envoyproxy/gateway-helm --version v1.6.0 -n envoy-gateway-system --create-namespace

# 3. Создание GatewayClass
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: eg
spec:
  controllerName: gateway.envoyproxy.io/gateway-class/v1
  parametersRef:
    group: gateway.envoyproxy.io
    kind: EnvoyProxy
    name: default
EOF

# 4. Создание Gateway
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: eg
  namespace: default
spec:
  gatewayClassName: eg
  listeners:
  - name: http
    protocol: HTTP
    port: 80
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: my-tls-secret
EOF

# 5. HTTPRoute
kubectl apply -f - <<EOF
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-app
  namespace: default
spec:
  parentRefs:
  - name: eg
    namespace: default
  hostnames:
  - "app.example.com"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: my-service
      port: 8080
EOF
```

**Проверка через Status Conditions:**
```bash
kubectl get gateway,httproute,gatewayclass -A
# Проверка статусов:
# Accepted: True
# Programmed: True
# ResolvedRefs: True
```

---

## Дополнительная информация

### Сравнение Ingress и Gateway API

Gateway API разделяет ответственность между тремя ролями:
1.  **Infrastructure Provider:** Управляет классами шлюзов (`GatewayClass`).
2.  **Cluster Operator:** Управляет точками входа (`Gateway`).
3.  **Application Developer:** Управляет правилами маршрутизации (`HTTPRoute`, `TCPRoute`).

Это позволяет избежать монолитных и перегруженных конфигураций Ingress в больших организациях.

### Troubleshooting: распространенные проблемы внешнего доступа

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **IP не назначается LoadBalancer** | Пулы IPAddressPool исчерпаны или перекрываются | `kubectl describe svc <svc>` → Events | Увеличить пул; проверить отсутствие пересечений CIDR |
| **502/503 при BGP** | BFD не настроен, маршрут не появился | `kubectl get configurationstate -n metallb-system` | Добавить BFDProfile; проверить BGP-сессию на роутере |
| **Source IP клиента скрыт** | `externalTrafficPolicy: Cluster` или нет Proxy Protocol | `kubectl get svc <svc> -o yaml` | Установить `externalTrafficPolicy: Local`; включить Proxy Protocol |
| **DNS-запросы падают** | Перегрузка CoreDNS или conntrack race | `kubectl logs -n kube-system -l k8s-app=kube-dns` | Установить NodeLocal DNSCache; увеличить `nf_conntrack_max` |
| **BGP не поднимается** | ASN mismatch, ACL, порт 179 закрыт | `kubectl logs -n metallb-system -l app.kubernetes.io/component=speaker` | Проверить ASN на роутере; открыть TCP/179 между узлами и роутером |
| **ARP-флуд (L2-режим)** | Несколько speakers отвечают на один VIP | `tcpdump -i eth0 arp` | Проверить `strictARP: true` в kube-proxy; убедиться в Lease-механизме |
| **Gateway API route не работает** | GatewayClass не принят или ReferenceGrant отсутствует | `kubectl describe gateway <gw>`; `kubectl get referencegrant` | Убедиться, что контроллер установлен; создать ReferenceGrant для кросс-namespace ссылок |
| **Hairpin не работает** | Отсутствует `hairpin-mode` или `externalTrafficPolicy` | `kubectl exec -it <pod> -- curl <svc-clusterip>` | Включить `hairpin-mode=promiscuous-bridge` в kubelet; установить `externalTrafficPolicy: Local` |

### NetworkPolicy в контексте выбора CNI

Не все CNI реализуют NetworkPolicy одинаково:

- **Calico:** Полная поддержка Kubernetes NetworkPolicy + расширенные `GlobalNetworkPolicy` (L3/L4) и `NetworkSet` для групп CIDR.
- **Cilium:** Полная поддержка стандартных NetworkPolicy + `CiliumNetworkPolicy` (L7, FQDN, Entities).
- **Flannel:** Не реализует NetworkPolicy сам; требует Canal (Calico policy + Flannel datapath).
- **AWS VPC CNI / Azure CNI:** Используют Security Groups / Network Policies облачного провайдера, ограничивая гибкость внутри кластера.

**Рекомендация:** Если Zero Trust является требованием, выбирайте Calico или Cilium.

### См. также

- [Cilium: Высокопроизводительный CNI](./cilium.md) — детали реализации eBPF.
- [Gateway API: Концепции](../../gateway_api/definitions.md) — современный стандарт доступа.
- [MetalLB: Балансировщик для Bare-metal](../../metallb.md) — L2/BGP в on-premise.
- [CNI и kube-proxy: взаимодействие](../cni_kube_proxy_roles.md) — разделение ответственности.
- [Путь трафика в Kubernetes](../traffic_path.md) — схемы North-South и East-West.

**[К списку разделов CNI](../cni_kube_proxy_roles.md)**
