# MetalLB: Балансировщик нагрузки для Bare-metal

---

## Определения

**MetalLB** — это решение для балансировки нагрузки в bare-metal Kubernetes-кластерах, которое позволяет использовать сервисы типа `LoadBalancer` без интеграции с облачными провайдерами. MetalLB назначает сервисам внешние IP-адреса из заранее определенных пулов и анонсирует их в локальной сети.

**Speaker** — компонент MetalLB, работающий на каждом узле кластера в виде `DaemonSet`. Отвечает за анонсирование IP-адресов во внешней сети, используя протоколы L2 (Layer 2) — ARP (Address Resolution Protocol) / NDP (Neighbor Discovery Protocol) или BGP (Border Gateway Protocol). В современных версиях используется **FRR-K8s** (интеграция Free Range Routing для Kubernetes).

**Controller** — компонент MetalLB, работающий как `Deployment`. Отслеживает сервисы с типом `LoadBalancer` и назначает IP-адреса из пулов — **IPAddressPool**.

**FRR-K8s** — современный бэкенд на базе Free Range Routing, позволяющий MetalLB безопасно сосуществовать с другими BGP-компонентами (например, Cilium).

---

## Основные концепции

### Архитектура и компоненты

MetalLB состоит из двух основных компонентов, которые работают совместно для обеспечения внешнего доступа к сервисам:

**Controller** — центральный компонент, работающий как `Deployment` (обычно с одним репликой). Отвечает за:
- Отслеживание сервисов с типом `LoadBalancer` во всех пространствах имен
- Назначение IP-адресов из доступных пулов (`IPAddressPool`)
- Управление жизненным циклом выделенных IP (возврат в пул при удалении сервиса)
- Взаимодействие с API Kubernetes для обновления статуса сервиса

**Speaker** — компонент, работающий на каждом узле кластера в виде `DaemonSet`. Отвечает за:
- Анонсирование назначенных IP-адресов во внешней сети
- Взаимодействие с сетевым оборудованием через протоколы L2 (ARP/NDP) или BGP
- Мониторинг доступности узлов и перераспределение нагрузки при сбоях

### Использование FRR-K8s

Начиная с версии v0.15.0, MetalLB перешел на использование **FRR-K8s** в качестве основного бэкенда для BGP-функциональности. FRR-K8s — это обертка вокруг Free Range Routing (FRRouting), адаптированная для работы в Kubernetes.

**Преимущества FRR-K8s:**
- Безопасное сосуществование с другими BGP-компонентами (например, Cilium), разделяя с ними одну BGP-сессию
- Поддержка расширенных функций BGP: communities, multipath, graceful restart
- Возможность использования BFD для быстрого обнаружения отказов
- Изоляция BGP-процесса в отдельном поде, что повышает стабильность

### Режимы работы

MetalLB поддерживает два основных режима анонсирования IP-адресов. Выбор режима зависит от требований к производительности, отказоустойчивости и возможностей сетевого оборудования.

#### 1. Режим уровня 2 (Layer 2)

**Принцип работы:**
Один из узлов кластера становится "лидером" для конкретного IP-адреса сервиса. Выбор лидера происходит на основе хэша от имени сервиса и имени узла. Лидер отвечает на ARP-запросы (для IPv4) или NDP-сообщения (для IPv6), привязывая MAC-адрес своего сетевого интерфейса к виртуальному IP (VIP). Весь трафик для сервиса направляется на этот узел, который затем распределяет его по подам через `kube-proxy`.

**Отказоустойчивость:**
Если узел-лидер выходит из строя, остальные `speaker` обнаруживают это через gossip-протокол **memberlist** (MetalLB не использует VRRP) и перехватывают "лидерство" — выбор лидера детерминирован (хеш от имени узла и VIP). Для обновления ARP-таблиц клиентов отправляется GARP (Gratuitous ARP); типичное время переключения — около 10 секунд, зависит от того, как быстро клиент обновляет ARP-кэш.

**Ограничения:**
- Трафик ограничен пропускной способностью одного узла ("бутылочное горлышко")
- Переключение (failover) зависит от скорости обновления ARP-кэша на клиентах (обычно 10-30 секунд)
- Не подходит для высоконагруженных сервисов

**Когда использовать:**
- Простые конфигурации без BGP-оборудования
- Низкий и средний уровень трафика
- Тестовые и staging-среды

#### 2. Режим уровня 3 (BGP)

**Принцип работы:**
`Speaker` устанавливает BGP-сессии с внешними маршрутизаторами. Каждый узел, на котором есть поды сервиса, анонсирует маршрут к IP-адресу сервиса. Маршрутизатор использует ECMP (Equal-Cost Multi-Path) для распределения трафика между всеми анонсирующими узлами.

**Преимущества:**
- Истинная балансировка трафика между всеми узлами через ECMP
- Отсутствие "бутылочного горлышка" одного узла
- Использование **BFD (Bidirectional Forwarding Detection)** позволяет добиться переключения маршрутов за доли секунды (обычно <1 секунда)
- Масштабируемость для высоконагруженных систем

**Требования:**
- Сетевое оборудование с поддержкой BGP
- Настройка BGP-сессий на маршрутизаторах
- Понимание работы BGP и маршрутизации

**Когда использовать:**
- Продакшн-среды с высокими требованиями к доступности
- Наличие BGP-оборудования
- Необходимость истинной балансировки между узлами

### Поддержка IPv6 и Dual-stack

MetalLB полностью поддерживает работу в сетях IPv4, IPv6 и Dual-stack. В режиме L2 используются протоколы ARP (IPv4) и NDP (IPv6). В режиме BGP анонсируются соответствующие семейства адресов. Сервисы могут получать адреса обоих семейств одновременно при наличии соответствующих пулов.

Для Dual-stack необходимо создать отдельные `IPAddressPool` для каждого семейства адресов и связать их с соответствующими `L2Advertisement` или `BGPAdvertisement`.

---

## Практические сценарии

### Предварительные требования

**Системные требования:**
- Kubernetes версия 1.13+ (рекомендуется 1.24+)
- Для режима L2: `kube-proxy` должен работать в режиме IPVS с включенным `strictARP`
- Для режима BGP: сетевое оборудование с поддержкой BGP

**Проверка режима kube-proxy:**

```bash
kubectl get configmap kube-proxy -n kube-system -o yaml | grep -i mode
# → mode: "ipvs" (рекомендуется) или "" (iptables)
```

### Установка

**Предпосылки для режима L2:**
Для корректной работы в режиме L2 (или если `kube-proxy` работает в режиме IPVS) необходимо включить `strictARP`. Без этой настройки `kube-proxy` будет отвечать на ARP-запросы для всех IP-адресов сервисов, что приведет к конфликту с MetalLB.

```bash
# Проверка текущего значения strictARP
kubectl get configmap kube-proxy -n kube-system -o yaml | grep strictARP

# Включение strictARP в kube-proxy
kubectl edit configmap -n kube-system kube-proxy
# Установить в секции data.config.conf:
#   ipvs:
#     strictARP: true
```

**После изменения strictARP необходимо перезапустить kube-proxy:**

```bash
kubectl rollout restart daemonset kube-proxy -n kube-system
```

**Установка через Helm (рекомендуется):**

```bash
# Добавление репозитория
helm repo add metallb https://metallb.github.io/metallb
helm repo update

# Установка с включенным FRR-K8s для поддержки BGP
helm install metallb metallb/metallb \
  --namespace metallb-system \
  --create-namespace \
  --set frrk8s.enabled=true

# Или установка только для L2-режима (без FRR-K8s)
helm install metallb metallb/metallb \
  --namespace metallb-system \
  --create-namespace
```

**Установка через манифесты (актуально для v0.16.x):**

```bash
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.16.1/config/manifests/metallb-native.yaml
```

**Проверка установки:**

```bash
# Проверка статуса подов
kubectl get pods -n metallb-system
# → NAME                                  READY   STATUS    RESTARTS   AGE
# → controller-7b8c9d6f4-xxxxx             1/1     Running   0          30s
# → speaker-xxxxx                          2/2     Running   0          30s (контейнеры speaker + frr)

# Проверка логов контроллера
kubectl logs -n metallb-system deployment/controller --tail=20
```

### Конфигурация через CRD

В современных версиях (v0.13.0+) настройка выполняется исключительно через Custom Resources. Конфигурация через ConfigMap удалена.

#### Пул адресов (IPAddressPool)

`IPAddressPool` определяет пул IP-адресов, из которых Controller назначает адреса сервисам.

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: main-pool
  namespace: metallb-system
spec:
  # Диапазоны адресов (CIDR или диапазон)
  addresses:
  - 192.168.10.100-192.168.10.200
  - 2001:db8::100/120  # IPv6 пул
  # Автоматическое назначение IP (по умолчанию true)
  autoAssign: true
  # Предотвращение назначения адресов из подсети сервисов (избегание конфликтов)
  avoidBuggyIPs: true  # Исключает .0 и .255 из диапазона
```

**Параметры:**
- `addresses`: список CIDR-нотаций или диапазонов IP-адресов
- `autoAssign`: если `true`, IP назначаются автоматически; если `false`, только по запросу через аннотацию
- `avoidBuggyIPs`: исключает адреса .0 и .255, которые могут вызывать проблемы на некотором оборудовании

#### Анонсирование уровня 2 (L2Advertisement)

`L2Advertisement` связывает пулы адресов с методом анонсирования L2.

```yaml
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: l2-adv
  namespace: metallb-system
spec:
  # Связанные пулы адресов
  ipAddressPools:
  - main-pool
  # Метки для выбора пулов
  ipAddressPoolsSelectors:
  - matchLabels:
      pool-type: production
  # Ограничение узлов, с которых идет анонс
  nodeSelectors:
  - matchLabels:
      kubernetes.io/hostname: worker-1
  # Интерфейсы для анонса (если не указано — все интерфейсы)
  interfaces:
  - eth0
```

#### Анонсирование BGP (GPGAdvertisement)

`BGPAdvertisement` связывает пулы адресов с методом анонсирования BGP.

```yaml
apiVersion: metallb.io/v1beta1
kind: BGPAdvertisement
metadata:
  name: bgp-adv
  namespace: metallb-system
spec:
  ipAddressPools:
  - main-pool
  # Агрегация маршрутов (уменьшает количество анонсов)
  aggregationLength: 32  # для IPv4
  aggregationLengthV6: 128  # для IPv6
  # BGP communities для маршрутов
  communities:
  - 64512:100
  # Local Preference (влияет на выбор маршрута)
  localPref: 100
```

#### Настройка BGP, BFD и Communities

**BGPPeer** — определяет BGP-соседа для установления сессии:

```yaml
apiVersion: metallb.io/v1beta2
kind: BGPPeer
metadata:
  name: edge-router
  namespace: metallb-system
spec:
  # Локальный AS (Autonomous System number)
  myASN: 64512
  # AS удаленного пира
  peerASN: 64512  # iBGP (тот же AS) или eBGP (разный AS)
  # Адрес удаленного пира
  peerAddress: 192.168.10.1
  # Использовать ли BFD для быстрого failover
  bfdProfile: fast-failover
  # Интерфейс для установления сессии
  # (если не указан — используется основной интерфейс узла)
  # sourceAddress: 192.168.10.100
  # Multihop (для eBGP через несколько хопов)
  # ebgpMultiHop: true
  # Router ID (для идентификации в BGP)
  # routerID: 192.168.10.100
```

**BFDProfile** — параметры протокола BFD для быстрого обнаружения отказов:

```yaml
apiVersion: metallb.io/v1beta1
kind: BFDProfile
metadata:
  name: fast-failover
  namespace: metallb-system
spec:
  # Интервал приема (мс)
  receiveInterval: 300
  # Интервал отправки (мс)
  transmitInterval: 300
  # Множитель обнаружения (количество пропущенных пакетов до объявления сбоя)
  detectMultiplier: 3
  # Echo-режим для дополнительной проверки
  # echoMode: true
  # Минимальный интервал принимаемых echo-пакетов
  # minimumTtl: 255
```

**Community** — определение BGP communities для фильтрации маршрутов:

```yaml
apiVersion: metallb.io/v1beta1
kind: Community
metadata:
  name: bgp-communities
  namespace: metallb-system
spec:
  communities:
  - name: internal-only
    value: 64512:100
  - name: no-export
    value: "65535:65281"  # NO_EXPORT community
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
  ports:
  - port: 80
    targetPort: 8080
  selector:
    app: my-app
```

#### Использование loadBalancerClass

Если в кластере установлено несколько решений для LoadBalancer (например, MetalLB и облачный провайдер), можно явно указать, какой из них должен обрабатывать сервис:

```yaml
spec:
  type: LoadBalancer
  loadBalancerClass: metallb.io/v1alpha1
```

### Совместное использование IP (Service IP Sharing)

MetalLB позволяет нескольким сервисам использовать один и тот же IP-адрес. Это полезно, если ограничены в публичных IP или хотите объединить разные порты (например, 80 и 443) одного логического приложения под одним IP.

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
---
apiVersion: v1
kind: Service
metadata:
  name: web-https
  annotations:
    metallb.universe.tf/allow-shared-ip: "my-app"
spec:
  type: LoadBalancer
  ports:
  - name: https
    port: 443
    protocol: TCP
    targetPort: 443
  selector:
    app: my-app
```

### Политики трафика и Source IP

#### externalTrafficPolicy

Параметр `externalTrafficPolicy` определяет, как трафик распределяется после попадания на узел:

- **Cluster (по умолчанию):** Трафик распределяется между всеми узлами. Если на узле нет подов сервиса, запрос перенаправляется на другой узел. При этом происходит SNAT — подмена исходного IP-адреса на IP узла, что скрывает реальный IP клиента.
- **Local:** Трафик обрабатывается только на узлах, где есть поды сервиса. Это сохраняет реальный IP клиента, но может привести к неравномерному распределению нагрузки.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  type: LoadBalancer
  externalTrafficPolicy: Local  # Сохраняет Source IP
  healthCheckNodePort: 30000     # Автоматически назначается
  ports:
  - port: 80
    targetPort: 8080
  selector:
    app: my-app
```

**Рекомендации:**
- Используйте `Local`, когда важно сохранить IP клиента (логирование, аудит)
- В режиме L2 используйте `Local` для снижения межузлового трафика
- В режиме BGP с ECMP `Cluster` обеспечивает более равномерное распределение

### Мониторинг и метрики

MetalLB экспортирует метрики в формате Prometheus на порту `9128`.

**Основные метрики:**
- `metallb_allocator_addresses_in_use_total`: общее количество выделенных IP
- `metallb_allocator_addresses_total`: общее количество доступных IP в пулах
- `metallb_bgp_session_up`: статус BGP-сессий (0 — down, 1 — up)
- `metallb_speaker_announce_count`: счетчик анонсов, отправленных спикером

**Настройка ServiceMonitor для Prometheus Operator:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: metallb
  namespace: metallb-system
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: metallb
  endpoints:
  - port: metrics
    interval: 30s
```

### Валидация конфигурации

После применения конфигурации проверьте корректность настроек:

```bash
# Проверка статуса пулов
kubectl get ipaddresspool -n metallb-system
# → NAME         AUTO ASSIGN   AVOID BUGGY IPS   ADDRESSES
# → main-pool    true          true              192.168.10.100-192.168.10.200

# Проверка статуса анонсов
kubectl get l2advertisement -n metallb-system
kubectl get bgpadvertisement -n metallb-system

# Проверка статуса BGP-пиров
kubectl get bgppeer -n metallb-system

# Проверка выделенных IP для сервисов
kubectl get svc -A | grep LoadBalancer
```

---

## Устранение неисправностей

### Проверка состояния конфигурации

Новый ресурс `ConfigurationState` позволяет быстро найти ошибки в CRD:

```bash
kubectl get configurationstate -n metallb-system
# → NAME      STATUS   REASON
# → speaker   Valid    
# → controller Valid
```

### Диагностика сервиса

Если сервис висит в статусе `Pending` (внешний IP не назначен):

```bash
# Проверка событий сервиса
kubectl describe svc <service-name> -n <namespace>
# В секции Events будет указана причина, например:
#   "Failed to allocate IP from pool"
#   "No available IP addresses in pool"

# Проверка статуса сервиса
kubectl get svc <service-name> -n <namespace> -o yaml | grep -A 10 "status:"
```

### Распространенные проблемы и решения

#### Проблема: IP не назначен (статус Pending)

**Возможные причины:**

1. **MetalLB не установлен или не работает:**
   ```bash
   kubectl get pods -n metallb-system
   # Если подов нет — установить MetalLB
   ```

2. **Пул адресов исчерпан:**
   ```bash
   kubectl get ipaddresspool -n metallb-system -o yaml
   # Проверить доступные адреса
   
   kubectl logs -n metallb-system deployment/controller | grep "no available"
   # → E0101 12:00:00.000000       1 allocator.go:123] "no available IPs" pool=main-pool
   ```
   **Решение:** Расширить пул адресов или удалить неиспользуемые сервисы.

3. **IP-адрес не принадлежит пулу:**
   ```bash
   # Проверка запрошенного IP через аннотацию
   kubectl get svc <service-name> -o yaml | grep loadBalancerIPs
   ```
   **Решение:** Убедиться, что запрошенный IP входит в диапазон пула.

4. **Пулы не связаны с анонсом:**
   ```bash
   kubectl get l2advertisement -n metallb-system -o yaml
   kubectl get bgpadvertisement -n metallb-system -o yaml
   ```
   **Решение:** Добавить связь пула с анонсом.

#### Проблема: BGP-сессия не устанавливается

```bash
# Проверка логов speaker
kubectl logs -n metallb-system -l app.kubernetes.io/component=speaker --tail=100

# Проверка статуса BGP-сессий через FRR
kubectl exec -n metallb-system -it <speaker-pod> -c frr -- vtysh -c "show ip bgp summary"

# Проверка конфигурации FRR
kubectl exec -n metallb-system -it <speaker-pod> -c frr -- vtysh -c "show running-config"
```

**Возможные причины:**
- Неправильный адрес пира или номер AS
- Блокировка TCP-порта 179 файрволом
- Отсутствие маршрута к пиру
- Несовпадение BFD-параметров

#### Проблема: Нет доступности сервиса извне

```bash
# Проверка ARP-таблиц (режим L2)
kubectl exec -n metallb-system -it <speaker-pod> -c frr -- ip neigh

# Проверка анонсируемых маршрутов (режим BGP)
kubectl exec -n metallb-system -it <speaker-pod> -c frr -- vtysh -c "show ip route"

# Проверка на узле
ip neigh | grep <service-ip>
ip route | grep <service-ip>
```

### Просмотр логов анонсирования

```bash
# Логи спикера для всех узлов
kubectl logs -n metallb-system -l app.kubernetes.io/component=speaker --tail=50

# Логи спикера для конкретного узла
kubectl logs -n metallb-system -l app.kubernetes.io/component=speaker \
  --field-selector spec.nodeName=worker-1 --tail=50

# Логи FRR (BGP-сессии)
kubectl logs -n metallb-system -l app.kubernetes.io/component=speaker \
  -c frr --tail=50

# Логи контроллера
kubectl logs -n metallb-system deployment/controller --tail=50
```

### Диагностика через FRR

Для глубокой диагностики BGP и сетевых проблем можно использовать FRR CLI:

```bash
# Подключение к FRR в поде speaker
kubectl exec -n metallb-system -it <speaker-pod> -c frr -- vtysh

# Полезные команды FRR:
# Просмотр BGP-сессий
show ip bgp summary

# Просмотр анонсируемых маршрутов
show ip bgp neighbors <peer-ip> advertised-routes

# Просмотр полученных маршрутов
show ip bgp neighbors <peer-ip> routes

# Просмотр маршрутной таблицы
show ip route

# Проверка BFD-сессий
show bfd peers
```

### Устаревшая конфигурация (ConfigMap)

Метод настройки через `ConfigMap` полностью **удален** начиная с версии v0.13.0. При обновлении со старых версий необходимо выполнить миграцию на CRD. MetalLB перестал поддерживать обратную совместимость с конфигурацией через ConfigMap, что требует переписывания всей логики на пулы (IPAddressPool) и анонсы (L2Advertisement/BGPAdvertisement).

**Миграция с ConfigMap на CRD:**

1. Извлеките конфигурацию из старого ConfigMap
2. Создайте соответствующие IPAddressPool и L2Advertisement/BGPAdvertisement
3. Удалите старый ConfigMap
4. Проверьте работоспособность сервисов

### Удаление MetalLB

Для корректного удаления MetalLB:

```bash
# Удаление через Helm
helm uninstall metallb -n metallb-system

# Или удаление манифестов
kubectl delete -f https://raw.githubusercontent.com/metallb/metallb/v0.16.1/config/manifests/metallb-native.yaml

# Удаление CRD (если больше не нужны)
kubectl delete crd ipaddresspools.metallb.io
kubectl delete crd l2advertisements.metallb.io
kubectl delete crd bgpadvertisements.metallb.io
kubectl delete crd bgppeers.metallb.io
kubectl delete crd bfdprofiles.metallb.io
kubectl delete crd communities.metallb.io

# Удаление namespace
kubectl delete namespace metallb-system
```

**Важно:** Перед удалением MetalLB убедитесь, что все сервисы типа LoadBalancer могут работать без него (переведены на другой тип или удалены).

---
## Безопасность

### RBAC

MetalLB использует отдельные ServiceAccount для Controller и Speaker с минимально необходимыми правами:

- **Controller:** доступ к сервисам, пулам адресов, анонсам, событиям в пространстве имен `metallb-system`
- **Speaker:** доступ к узлам (nodes), сервисам, конфигурации MetalLB

Рекомендуется проверить права через:

```bash
kubectl describe clusterrole metallb-controller
kubectl describe clusterrole metallb-speaker
```

### Рекомендации по безопасности

1. **Ограничение доступа к namespace metallb-system:**
   ```bash
   # Запрет изменения конфигурации MetalLB для обычных пользователей
   kubectl create rolebinding metallb-admin \
     --clusterrole=admin \
     --group=system:masters \
     --namespace=metallb-system
   ```

2. **Использование аннотаций для контроля доступа:**
   - Ограничьте возможность назначения статических IP через RBAC на сервисы
   - Контролируйте использование `metallb.universe.tf/loadBalancerIPs`

3. **Задание минимальных привилегий для подов:**
   Speaker требует привилегированного доступа для работы с сетью. Не рекомендуется запускать Speaker с избыточными правами.

4. **Сетевая безопасность:**
   - Используйте BGP MD5-аутентификацию для защиты BGP-сессий
   - Применяйте prefix-lists на маршрутизаторах для фильтрации анонсируемых маршрутов

---

## Best Practices

### Выбор режима

| Критерий | L2 | BGP |
| :--- | :--- | :--- |
| Простота настройки | Высокая | Средняя |
| Производительность | Ограничена одним узлом | ECMP, масштабируемость |
| Время failover | 10-30 секунд | <1 секунда (с BFD) |
| Требования к оборудованию | Минимальные | BGP-маршрутизаторы |
| Рекомендуемое использование | Тестовые среды, малый трафик | Продакшн, высокие нагрузки |

### Рекомендации по конфигурации

1. **Разделяйте пулы по назначению:**
   ```yaml
   # Пул для production-сервисов
   - name: production-pool
     addresses:
     - 192.168.10.100-192.168.10.150
   
   # Пул для staging-сервисов
   - name: staging-pool
     addresses:
     - 192.168.10.151-192.168.10.200
   ```

2. **Используйте nodeSelectors для ограничения анонсов:**
   - Анонсируйте IP только с узлов, имеющих внешнее подключение
   - Исключите узлы без внешних сетевых интерфейсов

3. **Мониторинг и алертинг:**
   - Настройте алерты на `metallb_allocator_addresses_in_use_total` (при исчерпании пула)
   - Мониторьте `metallb_bgp_session_up` для контроля BGP-сессий

4. **Резервирование адресов:**
   - Оставляйте 10-20% пула свободным для масштабирования
   - Учитывайте адреса для системных сервисов (Ingress, Monitoring)

5. **Документирование пулов:**
   - Используйте аннотации и метки для описания назначения пулов
   - Ведите учет выделенных IP-адресов

### Обновление MetalLB

**Порядок обновления:**

1. Проверьте release notes на наличие breaking changes
2. Создайте бэкап текущей конфигурации:
   ```bash
   kubectl get ipaddresspool -n metallb-system -o yaml > metallb-backup.yaml
   kubectl get l2advertisement -n metallb-system -o yaml >> metallb-backup.yaml
   kubectl get bgpadvertisement -n metallb-system -o yaml >> metallb-backup.yaml
   kubectl get bgppeer -n metallb-system -o yaml >> metallb-backup.yaml
   ```
3. Обновите Helm chart или манифесты
4. Проверьте работоспособность сервисов после обновления

**Важно:** При обновлении с версий до v0.13.0 необходимо выполнить миграцию с ConfigMap на CRD.

---

## Дополнительная информация

- [Официальный сайт MetalLB](https://metallb.universe.tf/)
- [Репозиторий MetalLB на GitHub](https://github.com/metallb/metallb)
- [Репозиторий FRR-K8s](https://github.com/metallb/frr-k8s)
- [Сравнение режимов L2 и BGP](https://metallb.universe.tf/concepts/)

### См. также

- [BGP в сетях](../../Networking/Protocols/bgp.md)
- [Тип Service — LoadBalancer](../Service/service_type_loadbalancer.md)
- [Внешний доступ в Bare-metal кластеры](../../Installation/Kubespray/offline_installation/step5_metallb_ingress.md)
