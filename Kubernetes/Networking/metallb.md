# MetalLB

## Определения

**MetalLB** — это решение для балансировки нагрузки в bare-metal Kubernetes-кластерах, которое позволяет использовать сервисы типа `LoadBalancer` без интеграции с облачными провайдерами. MetalLB назначает сервисам внешние IP-адреса из заранее определенных пулов и анонсирует их в локальной сети.

**Speaker** — компонент MetalLB, работающий на каждом узле кластера в виде `DaemonSet`. Отвечает за анонсирование IP-адресов во внешней сети, используя протоколы L2 (ARP/NDP) или BGP. В современных версиях используется **FRR (Free Range Routing)**.

**Controller** — компонент MetalLB, работающий как `Deployment`. Отслеживает сервисы с типом `LoadBalancer` и назначает IP-адреса из пулов (`IPAddressPool`).

## Основные концепции

### Режим FRR (Free Range Routing)

Начиная с версии v0.13.0, MetalLB использует FRR в качестве движка для управления протоколами маршрутизации. Это изменение унифицировало работу L2 и BGP режимов, повысило производительность и стабильность. Контейнер с FRR запускается внутри каждого `speaker`-пода.

### Режимы работы

MetalLB поддерживает два основных режима анонсирования IP-адресов:

#### 1. Режим L2 (Layer 2)

- **Принцип работы:** Один из узлов кластера становится "лидером" для конкретного IP-адреса сервиса. Этот узел отвечает на ARP-запросы (для IPv4) или NDP-сообщения (для IPv6), привязывая MAC-адрес своего сетевого интерфейса к виртуальному IP. Весь трафик для сервиса направляется на этот узел, который затем с помощью `kube-proxy` распределяет его по подам.
- **Отказоустойчивость:** Если узел-лидер выходит из строя, другой `speaker` на рабочем узле обнаруживает это и перехватывает "лидерство", отправляя в сеть GARP (Gratuitous ARP) для обновления ARP-таблиц на сетевых устройствах.

##### Ограничения режима L2

- **"Бутылочное горлышко" (Single-Node Bottleneck):** Весь трафик для одного IP-адреса проходит через один узел, что ограничивает максимальную пропускную способность скоростью сетевого интерфейса этого узла.
- **Медленное переключение (Slower Failover):** Процесс переключения на другой узел занимает несколько секунд, так как зависит от времени обновления ARP-таблиц на клиентах и сетевом оборудовании. На этот период возможна кратковременная потеря доступности сервиса.

#### 2. Режим L3 (Layer 3 - BGP)

**Принцип работы:** `Speaker` устанавливает BGP-сессии с пограничными маршрутизаторами. Каждый `speaker` анонсирует маршруты к IP-адресам сервисов на своём узле.

**Преимущества:**

- **Настоящая балансировка:** При использовании **ECMP (Equal-Cost Multi-Path)** трафик равномерно распределяется между узлами с подами сервиса
- **Быстрое переключение:** При сбое узла BGP-сессия разрывается, маршрутизатор мгновенно переключается на другие маршруты

**Требования:** Сетевое оборудование с поддержкой BGP.

## Практические сценарии

### Установка

**Предпосылки:**

Для `kube-proxy` в режиме `ipvs` (например, в `kubespray`) требуется `strictARP: true`:

```yaml
# k8s-cluster.yml в kubespray
kube_proxy_strict_arp: true
```

**Установка через манифест:**

```bash
# Создание namespace
kubectl create namespace metallb-system

# Применение манифеста (версию проверять в официальной документации)
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.14.5/config/manifests/metallb-native.yaml
```

> **Важно:** В версиях до v0.13.0 требовалось создавать `secret/memberlist` для шифрования gossip-трафика. С переходом на FRR этот шаг не нужен.

### Конфигурация (CRD)

#### IPAddressPool

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: default-pool
  namespace: metallb-system
spec:
  addresses:
  - 192.168.10.100-192.168.10.200
```

#### L2Advertisement

```yaml
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: default-l2-adv
  namespace: metallb-system
spec:
  ipAddressPools:
  - default-pool
```

#### BGPAdvertisement

```yaml
# BGP-пир (маршрутизатор)
apiVersion: metallb.io/v1beta2
kind: BGPPeer
metadata:
  name: my-router
  namespace: metallb-system
spec:
  myASN: 64512
  peerASN: 64512
  peerAddress: 192.168.10.1

# Анонсирование пулов
apiVersion: metallb.io/v1beta1
kind: BGPAdvertisement
metadata:
  name: default-bgp-adv
  namespace: metallb-system
spec:
  ipAddressPools:
  - default-pool
```

### Устаревшая конфигурация (ConfigMap)

> **ПРЕДУПРЕЖДЕНИЕ:** Метод использовался в версиях до **0.10.0** и является **устаревшим**.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  namespace: metallb-system
  name: config
data:
  config: |
    address-pools:
    - name: default
      protocol: layer2
      addresses:
      - 192.168.1.240-192.168.1.250
```

### Troubleshooting

#### Сервис в статусе PENDING

```bash
# Логи Controller
kubectl logs -n metallb-system -l app.kubernetes.io/component=controller

# Проверка CRD
kubectl get ipaddresspool,l2advertisement,bgpadvertisement -n metallb-system

# Проверка занятых IP
kubectl get svc --all-namespaces | grep LoadBalancer
```

**Причины:** исчерпан пул IP, некорректная связь CRD, IP занят другим сервисом.

#### Трафик не доходит до сервиса

```bash
# Логи Speaker
kubectl logs -n metallb-system -l app.kubernetes.io/component=speaker

# Логи FRR (для BGP)
kubectl logs -n metallb-system <speaker-pod-name> -c frr

# Проверка на маршрутизаторе
show arp
show ip bgp
```

**Специфическая проблема: Блокировка ARP между сегментами**
В некоторых корпоративных сетях ARP-ответы (анонсы MetalLB) не проходят между сегментами или блокируются политиками безопасности. Клиенты из других подсетей не видят виртуальный IP, так как их запросы остаются без ответа.

**Решение:**

1. Использование режима BGP (требует поддержки оборудованием).
2. Проксирование через внешний Nginx на NodePort с централизованным DNS. Подробнее см. в [Внешний доступ в Bare-metal через NodePort и Nginx](./Ingress/bare_metal_manual_proxy.md).

## Дополнительная информация

**Официальная документация:** [metallb.universe.tf](https://metallb.universe.tf/)
