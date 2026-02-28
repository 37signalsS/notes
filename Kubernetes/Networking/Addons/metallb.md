# MetalLB

## Определения

**MetalLB** — система балансировки нагрузки для Kubernetes-кластеров, работающих в bare-metal окружениях. Реализует сервисы типа `LoadBalancer` без облачных провайдеров, назначая внешние IP-адреса и управляя трафиком на уровне L2 (ARP/NDP) или L3 ([BGP (Border Gateway Protocol): Обзор](../../../Networking/Protocols/bgp.md)).

**Speaker** — компонент MetalLB, запускаемый на каждом узле кластера (`DaemonSet`), который отвечает за анонсирование IP-адресов в сеть.

**Controller** — компонент MetalLB (`Deployment`), который отслеживает создание сервисов типа `LoadBalancer` и назначает им IP-адреса из настроенных пулов.

## Основные концепции

### Режим L2 (Уровень 2 — канальный)

- **Принцип работы:** Один из узлов в кластере "захватывает" IP-адрес сервиса и отвечает на ARP-запросы (IPv4) или NDP-запросы (IPv6) для этого IP. Весь трафик для сервиса изначально поступает на этот узел, который затем использует `kube-proxy` для распределения его между подами сервиса.
- **Отказоустойчивость:** При выходе из строя активного узла другой узел берет на себя ответственность за IP-адрес сервиса, обеспечивая автоматическое переключение.

#### Ограничения режима L2
- **"Бутылочное горлышко" (Single-Node Bottleneck):** Весь входящий трафик для одного сервиса проходит через один узел. Это может ограничить пропускную способность и создать единую точку отказа на уровне производительности.
- **Медленное переключение (Slow Failover):** Процесс переключения IP-адреса на другой узел после сбоя зависит от стандартных механизмов ARP и может занимать несколько секунд, что приводит к кратковременной недоступности сервиса.

### Режим L3 (Уровень 3 — сетевой)

— Устанавливает BGP-сессии с маршрутизаторами сети.
— Анонсирует маршруты к виртуальным IP-адресам.
— Трафик направляется напрямую на ноды с подами сервиса.
— Поддерживает балансировку через ECMP (Equal-Cost Multi-Path), что позволяет распределять трафик по нескольким узлам одновременно.

## Практические сценарии

### Установка

#### Предпосылки
- При использовании `kube-proxy` в режиме `ipvs` (например, в `kubespray`), необходимо установить параметр `strictARP: true` для корректной работы MetalLB.
  ```yaml
  # Файл k8s-cluster.yml в kubespray
  kube_proxy_strict_arp: true
  ```

#### Ручная установка
1.  **Создание Namespace:**
    ```bash
    kubectl create namespace metallb-system
    ```
2.  **Установка через манифест:**
    ```bash
    kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.13.7/config/manifests/metallb-native.yaml
    ```
    *Примечание: всегда проверяйте [официальную документацию](https://metallb.universe.tf/installation/) на предмет последней версии.*
3.  **Создание секрета для `memberlist`:** (Только для старых версий, для FRR-режима не требуется)
    Для обеспечения шифрования между `speaker` компонентами необходимо создать секрет.
    ```bash
    kubectl create secret generic -n metallb-system memberlist --from-literal=secretkey="$(openssl rand -base64 128)"
    ```

### Конфигурация (CRD-подход, современный)

Начиная с версии v0.10.0, MetalLB использует CRD для конфигурации.

#### Конфигурация для режима L2

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: default-pool
  namespace: metallb-system
spec:
  addresses:
  - 192.168.10.100-192.168.10.200

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

#### Конфигурация для режима L3 (BGP)

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: production-pool
  namespace: metallb-system
spec:
  addresses:
  - 172.16.100.0/24

---
apiVersion: metallb.io/v1beta1
kind: BGPPeer
metadata:
  name: router1
  namespace: metallb-system
spec:
  myASN: 64500
  peerASN: 64501
  peerAddress: 10.0.0.1
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

### Конфигурация (Устаревший подход через ConfigMap)
В версиях до 0.10.0 конфигурация осуществлялась через `ConfigMap`.

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
      - 192.168.1.200/32 # Указание одного IP
```

### Использование и расширенные настройки

#### Создание простого LoadBalancer сервиса
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
$ kubectl get svc nginx-service
NAME            TYPE           CLUSTER-IP      EXTERNAL-IP      PORT(S)        AGE
nginx-service   LoadBalancer   10.96.162.249   192.168.1.240    80:30953/TCP   15s
```

#### Запрос конкретного IP-адреса
Для назначения статического, предсказуемого IP-адреса используется поле `spec.loadBalancerIP`.
```yaml
apiVersion: v1
kind: Service
metadata:
  name: dns-service
spec:
  selector:
    app: dns
  ports:
  - port: 53
    targetPort: 53
    protocol: UDP
  type: LoadBalancer
  loadBalancerIP: 192.168.1.200 # IP должен входить в сконфигурированный пул
```

#### Отключение NodePort
По умолчанию для сервиса `LoadBalancer` также выделяется `NodePort`. Это можно отключить.
```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  selector:
    app: my-app
  ports:
  - port: 80
    targetPort: 9376
  type: LoadBalancer
  allocateLoadBalancerNodePorts: false # Отключает создание NodePort
```

## Траблшутинг

### Сервис не получает внешний IP (статус PENDING)
1.  **Проверьте логи Controller'а:**
    ```bash
    kubectl logs -n metallb-system -l app=metallb,component=controller
    ```
    Логи могут содержать информацию о том, почему IP не может быть назначен (например, пул исчерпан).

2.  **Проверьте конфигурацию пулов:** Убедитесь, что `IPAddressPool` и `L2Advertisement`/`BGPAdvertisement` созданы корректно и указывают друг на друга.

3.  **"Перехват" IP-адреса:** Распространенная проблема в тестовых средах. Если в кластере был создан другой сервис типа `LoadBalancer` (возможно, ошибочно или другим пользователем), он мог занять единственный доступный IP из пула. Проверьте все сервисы в кластере:
    ```bash
    kubectl get svc --all-namespaces | grep LoadBalancer
    ```

## Дополнительная информация

* **Официальная документация:** [metallb.io](https://metallb.io/)
* **Service типа LoadBalancer:** подробнее о типе сервиса см. в [service_type_loadbalancer.md](../Service/service_type_loadbalancer.md)
* **BGP:** подробнее о протоколе см. в [bgp.md](../../../Networking/Protocols/bgp.md)
