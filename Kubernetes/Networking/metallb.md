# MetalLB: Балансировщик нагрузки для Bare-metal

---

## Определения

**MetalLB** — это решение для балансировки нагрузки в bare-metal Kubernetes-кластерах, которое позволяет использовать сервисы типа `LoadBalancer` без интеграции с облачными провайдерами. MetalLB назначает сервисам внешние IP-адреса из заранее определенных пулов и анонсирует их в локальной сети.

**Speaker** — компонент MetalLB, работающий на каждом узле кластера в виде `DaemonSet`. Отвечает за анонсирование IP-адресов во внешней сети, используя протоколы L2 (Layer 2) — ARP (Address Resolution Protocol) / NDP (Neighbor Discovery Protocol) или BGP (Border Gateway Protocol). В современных версиях используется **FRR-K8s** (интеграция Free Range Routing для Kubernetes).

**Controller** — компонент MetalLB, работающий как `Deployment`. Отслеживает сервисы с типом `LoadBalancer` и назначает IP-адреса из пулов — **IPAddressPool**.

**FRR-K8s** — современный бэкенд на базе Free Range Routing, позволяющий MetalLB безопасно сосуществовать с другими BGP-компонентами (например, Cilium).

---

## Основные концепции

### Использование FRR-K8s

Начиная с версии v0.15.0, MetalLB перешел на использование **FRR-K8s** в качестве основного бэкенда. Это позволяет MetalLB сосуществовать с другими сетевыми компонентами (например, Cilium), которые также используют BGP, разделяя с ними одну BGP-сессию.

### Режимы работы

MetalLB поддерживает два основных режима анонсирования IP-адресов:

#### 1. Режим уровня 2 (Layer 2)

- **Принцип работы:** Один из узлов кластера становится "лидером" для конкретного IP-адреса сервиса. Этот узел отвечает на ARP-запросы (для IPv4) или NDP-сообщения (для IPv6), привязывая MAC-адрес своего сетевого интерфейса к виртуальному IP (VIP). Весь трафик для сервиса направляется на этот узел, который затем распределяет его по подам.
- **Отказоустойчивость:** Если узел-лидер выходит из строя, другой `speaker` на рабочем узле обнаруживает это и перехватывает "лидерство", отправляя в сеть GARP (Gratuitous ARP) для обновления ARP-таблиц.
- **Ограничения:** Трафик ограничен пропускной способностью одного узла ("бутылочное горлышко"). Переключение (failover) зависит от скорости обновления ARP-кэша на клиентах.

#### 2. Режим уровня 3 (BGP)

- **Принцип работы:** `Speaker` устанавливает BGP-сессии с внешними маршрутизаторами. Каждый узел анонсирует маршруты к IP-адресам сервисов.
- **Преимущества:** Поддержка ECMP (Equal-Cost Multi-Path) обеспечивает истинную балансировку трафика между всеми узлами. Использование **BFD (Bidirectional Forwarding Detection)** позволяет добиться переключения маршрутов за доли секунды.
- **Требования:** Сетевое оборудование с поддержкой BGP.

### Поддержка IPv6 и Dual-stack
MetalLB полностью поддерживает работу в сетях IPv4, IPv6 и Dual-stack. В режиме L2 используются протоколы ARP (IPv4) и NDP (IPv6). В режиме BGP анонсируются соответствующие семейства адресов. Сервисы могут получать адреса обоих семейств одновременно при наличии соответствующих пулов.

---

## Практические сценарии

### Установка

**Предпосылки:**
Для корректной работы в режиме L2 (или если `kube-proxy` работает в режиме IPVS) необходимо включить `strictARP`.

```bash
# Проверка и включение strictARP в kube-proxy
kubectl edit configmap -n kube-system kube-proxy
# Установить: strictARP: true
```

**Установка через Helm (рекомендуется):**

```bash
helm repo add metallb https://metallb.github.io/metallb
helm install metallb metallb/metallb --namespace metallb-system --create-namespace --set frrk8s.enabled=true
```

**Установка через манифесты (актуально для v0.16.x):**

```bash
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.16.1/config/manifests/metallb-native.yaml
```

### Конфигурация через CRD

В современных версиях настройка выполняется исключительно через Custom Resources.

#### Пул адресов (IPAddressPool)

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

#### Анонсирование уровня 2 (L2Advertisement)

```yaml
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: l2-adv
  namespace: metallb-system
spec:
  ipAddressPools:
  - main-pool
  # Можно ограничить узлы, с которых идет анонс
  nodeSelectors:
  - matchLabels:
      kubernetes.io/hostname: worker-1
```

#### Настройка BGP, BFD и Communities

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

---
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
# BGP Communities для управления маршрутами на стороне роутера
apiVersion: metallb.io/v1beta1
kind: Community
metadata:
  name: bgp-communities
  namespace: metallb-system
spec:
  communities:
  - name: internal-only
    value: 64512:100
```

### Статические IP и выбор контроллера

#### Назначение конкретного IP (Static IP)

Поле `spec.loadBalancerIP` в Kubernetes объявлено устаревшим. MetalLB рекомендует использовать аннотацию `metallb.universe.tf/loadBalancerIPs`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: static-svc
  annotations:
    metallb.universe.tf/loadBalancerIPs: 192.168.10.50
spec:
  type: LoadBalancer
  # ...
```

#### Использование loadBalancerClass

Если в кластере установлено несколько решений для LoadBalancer (например, MetalLB и облачный провайдер), можно явно указать, какой из них должен обрабатывать сервис:

```yaml
spec:
  type: LoadBalancer
  loadBalancerClass: metallb.io/v1alpha1
```

### Совместное использование IP (Service IP Sharing)

MetalLB позволяет нескольким сервисам использовать один и тот же IP-адрес. Это полезно, если вы ограничены в публичных IP или хотите объединить разные порты (например, 80 и 443) одного логического приложения под одним IP.

Для этого добавьте аннотацию `metallb.universe.tf/allow-shared-ip` с одинаковым значением (ключом) на все нужные сервисы:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web-http
  annotations:
    metallb.universe.tf/allow-shared-ip: "my-app"
spec:
  type: LoadBalancer
  ports:
  - name: http
    port: 80
    protocol: TCP
    targetPort: 80
  selector:
    app: my-app
```

### Мониторинг и метрики
MetalLB экспортирует метрики в формате Prometheus на порту `9128`.
- `metallb_allocator_addresses_in_use_total`: общее количество выделенных IP.
- `metallb_bgp_session_up`: статус BGP-сессий (0 — down, 1 — up).
- `metallb_speaker_announce_count`: счетчик анонсов, отправленных спикером.

---

## Устранение неисправностей

### Проверка состояния конфигурации

Новый ресурс `ConfigurationState` позволяет быстро найти ошибки в CRD:

```bash
kubectl get configurationstate -n metallb-system
# → NAME      STATUS   REASON
# → speaker   Valid    
```

### Диагностика сервиса

Если сервис висит в статусе `PENDING`:

```bash
kubectl describe svc my-service
# В событиях (Events) будет указана причина, например: "Failed to allocate IP from pool"
```

### Просмотр логов анонсирования

```bash
# Логи спикера для конкретного узла
kubectl logs -n metallb-system -l app.kubernetes.io/component=speaker --tail=50
```

### Устаревшая конфигурация (ConfigMap)

Метод настройки через `ConfigMap` полностью **удален** начиная с версии v0.13.0. При обновлении со старых версий необходимо выполнить миграцию на CRD. MetalLB перестал поддерживать обратную совместимость с конфигурацией через ConfigMap, что требует переписывания всей логики на пулы (IPAddressPool) и анонсы (L2Advertisement/BGPAdvertisement).

---

## Дополнительная информация

- [Официальный сайт MetalLB](https://metallb.universe.tf/)
- [Репозиторий FRR-K8s](https://github.com/metallb/frr-k8s)
- [Сравнение режимов L2 и BGP](https://metallb.universe.tf/concepts/)

### См. также
- [BGP в сетях](../../Networking/Protocols/bgp.md)
- [Внешний доступ в Bare-metal кластеры](./Ingress/bare_metal_manual_proxy.md)
- [Настройка Cilium](./Network/CNI/cilium.md)
