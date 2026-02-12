# MetalLB

## Определения

**MetalLB** — система балансировки нагрузки для Kubernetes-кластеров, работающих в bare-metal окружениях. Реализует сервисы типа `LoadBalancer` без облачных провайдеров, назначая внешние IP-адреса и управляя трафиком на уровне L2 (ARP/NDP) или L3 ([BGP (Border Gateway Protocol): Обзор](../../../Networking/Protocols/bgp.md)).

**Speaker** — компонент MetalLB, запускаемый на каждом узле кластера (`DaemonSet`), который отвечает за анонсирование IP-адресов в сеть.

**Controller** — компонент MetalLB, который отслеживает создание сервисов типа `LoadBalancer` и назначает им IP-адреса из настроенных пулов.

## Базовые концепции

### Режим L2 (Уровень 2 — канальный)

— Назначает виртуальный IP (VIP) сервису типа `LoadBalancer`
— Отвечает на ARP-запросы (IPv4) или NDP-запросы (IPv6) для этого IP
— Трафик направляется на одну из нод кластера, которая затем распределяет его между подами
— Автоматическое аварийное переключение при выходе ноды из строя

### Режим L3 (Уровень 3 — сетевой)

— Устанавливает BGP-сессии с маршрутизаторами сети
— Анонсирует маршруты к виртуальным IP-адресам
— Трафик направляется напрямую на ноды с подами сервиса
— Поддерживает балансировку через ECMP (Equal-Cost Multi-Path)

## Практические сценарии

### Конфигурация для режима L2

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: default-pool
  namespace: metallb-system
spec:
  addresses:
  - 87.30.40.30-87.30.40.130

---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: default
  namespace: metallb-system
spec:
  ipAddressPools:
  - default-pool
```

### Конфигурация для режима L3 (BGP)

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: production-pool
  namespace: metallb-system
spec:
  addresses:
  - 97.54.23.100/32
  - 97.54.23.101/32

---
apiVersion: metallb.io/v1beta1
kind: BGPPeer
metadata:
  name: router1
  namespace: metallb-system
spec:
  myASN: 64500
  peerASN: 64501
  peerAddress: 97.54.23.1
  peerPort: 179

---
apiVersion: metallb.io/v1beta1
kind: BGPAdvertisement
metadata:
  name: production
  namespace: metallb-system
spec:
  ipAddressPools:
  - production-pool
```

### Использование с Service LoadBalancer

```yaml
apiVersion: v1
kind: Service
metadata:
  name: nginx-service
spec:
  selector:
    app: nginx
  ports:
  - port: 80
    targetPort: 80
  type: LoadBalancer
```

После применения MetalLB автоматически назначит IP из пула:

```bash
kubectl get svc nginx-service -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
# 87.30.40.30
```

### Интеграция с Kubespray

```yaml
# group_vars/k8s-cluster/addons.yml
metallb_enabled: true
metallb_speaker_enabled: true

metallb_config:
  address_pools:
    primary:
      ip_range:
        - "5.75.169.149/32"
        - "91.99.78.20/32"
```

## Дополнительная информация

* **Официальная документация:** [metallb.io](https://metallb.io/)
* **Service типа LoadBalancer:** подробнее о типе сервиса см. в [service_type_loadbalancer.md](../Service/service_type_loadbalancer.md)
* **BGP:** подробнее о протоколе см. в [bgp.md](../../../Networking/Protocols/bgp.md)
