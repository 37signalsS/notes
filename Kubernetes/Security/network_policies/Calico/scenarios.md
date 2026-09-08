# Сценарии Calico: Распределенный файрвол и Zero-Trust

В данном разделе представлены практические примеры реализации сетевой защиты на уровнях узлов и кластера с использованием расширенных возможностей Calico. Настройка этих сценариев позволяет превратить кластер в среду с "нулевым доверием" (Zero-Trust).

> Основная документация и концепции: [Calico HostEndpoint и GlobalNetworkPolicy](./index.md)

## Определения

**Практический сценарий (Scenario)** — прикладная конфигурация ресурсов Calico (`HostEndpoint`, `GlobalNetworkPolicy`, `GlobalNetworkSet`, `NetworkPolicy`), предназначенная для решения конкретных задач безопасности: от создания внешнего периметра до микросегментации приложений.

**Периметральный файрвол** — стратегия защиты, при которой фильтрация трафика происходит на физических интерфейсах узлов кластера еще до его попадания во внутреннюю сеть Kubernetes.

**Zero-Trust (Нулевое доверие)** — архитектурный подход, при котором ни одно сетевое соединение не считается доверенным по умолчанию. Доступ разрешается только на основе явных политик, проверяющих идентичность отправителя.

**Identity-based Security** — метод контроля доступа, использующий атрибуты идентичности (например, ServiceAccount) вместо нестабильных IP-адресов или меток подов.

**Policy Tiers (Уровни политик)** — механизм группировки политик Calico по приоритетным уровням (например, `security`, `platform`, `application`). Политики в вышестоящих уровнях оцениваются раньше и не могут быть переопределены нижестоящими. Это позволяет администраторам задавать глобальные guardrails, которые приложение не может обойти.

## Основные концепции

Для успешной реализации сценариев необходимо понимание следующих механизмов:

* **HostEndpoint**: Ресурс, представляющий физический интерфейс узла. Позволяет применять политики к трафику, направленному на сам узел (SSH, Kubelet, NodePort).
* **preDNAT**: Фильтрация трафика до трансляции адресов (DNAT). Критично для защиты сервисов `NodePort`, так как позволяет видеть реальный IP источника.
* **Приоритет (Order)**: Параметр, определяющий последовательность применения политик. Меньшее значение означает более высокий приоритет.
* **Dataplane**: Слой обработки трафика. В актуальных версиях Calico (v3.29+) по умолчанию используется **nftables**, обеспечивающий более высокую производительность по сравнению с legacy `iptables`. Для максимальной производительности доступен режим **eBPF**.
* **NetworkPolicy vs GlobalNetworkPolicy**: Стандартная `NetworkPolicy` (Kubernetes API) применяется только в пределах одного namespace. `GlobalNetworkPolicy` (CRD Calico) — кластерного масштаба, поддерживает additional-параметры (`preDNAT`, `applyOnForward`, `order`, tiers). Используйте `GlobalNetworkPolicy` для кластерных правил и `NetworkPolicy` для изоляции конкретных приложений.

*Подробное описание концепций: [Подробные определения Calico](./index.md)*

## Предварительные требования

Перед реализацией любых сценариев убедитесь, что:

1. **Calico установлен и работает**:
```bash
# Проверка статуса подов Calico
kubectl get pods -n calico-system
# → Все поды в Running

# Проверка статуса узлов
kubectl get nodes
# → Все узлы в Ready
```

2. **calicoctl установлен**:
```bash
# Проверка наличия calicoctl
calicoctl version
# → Client Version:    v3.33.x
# → Cluster Version:   v3.33.x
```

3. **Доступ к Calico API**:
```bash
# Проверка доступа к CRD
calicoctl get ipamblocks
# → Список блоков IP (или пустой вывод)
```

> Установка Calico: [Установка CNI в HA кластере](../../../Installation/HA_Cluster_Bare_Metal/cni_installation.md)

### Порядок создания политик

При внедрении Zero-Trust соблюдайте последовательность:

1. **Разрешающие политики** (DNS, необходимый egress) — Order: 50-100
2. **Логирование** (аудит заблокированного трафика) — Order: 90-150
3. **Запрещающие политики** (default-deny) — Order: 2000

> Создание запрещающей политики до разрешающих приведет к потере сетевой связности. Восстановление потребует прямого доступа к узлам (SSH) или удаления политик через Kubernetes API.

## Практические сценарии

### Сценарий 1: Базовая защита периметра кластера

**Задача:** Создать защитный контур на уровне узлов, который разрешает только доверенный трафик и блокирует всё остальное.

**Когда использовать:** Защита control-plane узлов от внешних атак; фильтрация трафика на физических интерфейсах до попадания в поды.

#### Шаг 1: Определение HostEndpoint для сетевых интерфейсов узлов

```yaml
# host-endpoints.yaml
apiVersion: projectcalico.org/v3
kind: HostEndpoint
metadata:
  name: node-1-eth0
  labels:
    node-role: control-plane
    endpoint-type: cluster-perimeter
spec:
  interfaceName: eth0
  node: node-1.example.com
  expectedIPs: ["192.168.1.10"]
```

> **Примечание:** `node` должен точно соответствовать имени узла в Kubernetes (`kubectl get nodes`). `interfaceName` — имя физического интерфейса (`ip addr` для определения).

#### Шаг 2: Создание разрешающей политики (Высокий приоритет)

```yaml
# allow-cluster-internal.yaml
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: allow-cluster-internal
spec:
  order: 10
  selector: "endpoint-type == 'cluster-perimeter'"
  preDNAT: true
  applyOnForward: true
  types: [Ingress, Egress]
  egress:
    - action: Allow
  ingress:
    # Разрешить трафик между узлами кластера
    - action: Allow
      source:
        selector: "endpoint-type == 'cluster-perimeter'"
    # Разрешить трафик от подов (Pod CIDR)
    - action: Allow
      source:
        nets: ["10.244.0.0/16"]
```

#### Шаг 3: Создание запрещающей политики (Низкий приоритет)

```yaml
# default-deny-perimeter.yaml
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: default-deny-perimeter
spec:
  order: 100
  selector: "endpoint-type == 'cluster-perimeter'"
  preDNAT: true
  applyOnForward: true
  types: [Ingress]
  ingress:
    - action: Deny
```

#### Шаг 4: Применение и валидация

```bash
# Применение ресурсов
calicoctl apply -f host-endpoints.yaml
calicoctl apply -f allow-cluster-internal.yaml
calicoctl apply -f default-deny-perimeter.yaml

# Проверка примененных ресурсов
calicoctl get hostendpoint
# → node-1-eth0   node-1.example.com

calicoctl get globalnetworkpolicy
# → allow-cluster-internal    10
# → default-deny-perimeter    100

# Тест: под кластера должен иметь доступ к API-серверу
kubectl run test-pod --image=busybox --restart=Never -- wget -qO- --timeout=5 https://kubernetes.default.svc
# → successful

# Тест: внешний трафик к порту 22 должен быть заблокирован (если нет разрешающей политики)
# С другого хоста: curl -v telnet://192.168.1.10:22
# → connection refused / timeout
```

> **Откат:** Если политика заблокировала SSH, используйте `calicoctl delete globalnetworkpolicy default-deny-perimeter` через прямой доступ к узлу (консоль, IPMI) или Kubernetes API (если доступен).

### Сценарий 2: Аудит и логирование заблокированного трафика

Использование действия `Log` позволяет анализировать попытки несанкционированного доступа без немедленного разрыва соединения (если стоит перед Deny).

**Когда использовать:** Мониторинг подозрительной активности, сбор метрик для SIEM, аудит соответствия требованиям безопасности.

```yaml
# log-and-deny.yaml
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: log-security-events
spec:
  order: 90 # Приоритет выше, чем у default-deny
  selector: "endpoint-type == 'cluster-perimeter'"
  types: [Ingress]
  ingress:
    - action: Log
      log:
        logPrefix: "calico-drop:"
    - action: Deny
```

Просмотр результатов логирования:
```bash
journalctl -u calico-node -f | grep "calico-drop"
# → calico-drop: IN=eth0 OUT= MAC=... SRC=192.168.1.50 DST=192.168.1.10 PROTO=TCP SPT=45678 DPT=22

# Для eBPF режима (логи в journald)
kubectl logs -n calico-system ds/calico-node -c calico-node --since=5m | grep "calico-drop"

# Проверка статистики логирования
calicoctl get globalnetworkpolicy log-security-events -o yaml | grep logPrefix
```

> **Оптимизация:** В кластерах с высоким трафиком логирование каждого заблокированного пакета может нагружать диск. Используйте `logPrefix` для быстрой фильтрации и настройте ротацию логов.

### Сценарий 3: Группировка внешних сетей (GlobalNetworkSet)

**Задача:** Разрешить доступ к API-серверу только из доверенных офисных подсетей.

**Когда использовать:** Ограничение доступа к control-plane, API и критичным сервисам по IP-адресам.

#### Шаг 1: Создание набора доверенных IP

```yaml
# trusted-office-networks.yaml
apiVersion: projectcalico.org/v3
kind: GlobalNetworkSet
metadata:
  name: trusted-office-networks
  labels:
    network-type: trusted
spec:
  nets:
    - 192.168.10.0/24
    - 10.0.50.0/24
```

#### Шаг 2: Применение политики доступа

```yaml
# restrict-api-access.yaml
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: restrict-api-access
spec:
  order: 20
  selector: "node-role == 'control-plane'"
  preDNAT: true
  types: [Ingress]
  ingress:
    - action: Allow
      protocol: TCP
      source:
        selector: "network-type == 'trusted'"
      destination:
        ports: [6443]
    - action: Deny
      protocol: TCP
      destination:
        ports: [6443]
```

#### Шаг 3: Валидация

```bash
calicoctl apply -f trusted-office-networks.yaml
calicoctl apply -f restrict-api-access.yaml

# Проверка GlobalNetworkSet
calicoctl get globalnetworkset
# → trusted-office-networks

# Тест: с доверенного IP (192.168.10.x)
curl -k https://192.168.1.10:6443/version
# → {"major":"1","minor":"34"...}

# Тест: с недоверенного IP
curl -k --connect-timeout 3 https://192.168.1.10:6443/version
# → connection refused
```

> **Примечание:** `GlobalNetworkSet` — только источник/получатель в правилах. Сам по себе он не блокирует трафик; блокировка осуществляется через `GlobalNetworkPolicy`.

### Сценарий 4: Глобальный Default-Deny (Zero-Trust Baseline)

**Задача:** Запретить любое взаимодействие между подами во всех пространствах имен, если оно явно не разрешено. Это фундамент безопасности кластера.

**Когда использовать:** Начальный этап внедрения Zero-Trust; сценарии, когда каждое приложение должно иметь явные разрешения на сетевое взаимодействие.

```yaml
# global-default-deny.yaml
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: global-default-deny
spec:
  order: 2000 # Очень низкий приоритет, применяется последним
  selector: "all()"
  types: [Ingress, Egress]
  ingress:
    - action: Deny
  egress:
    - action: Deny
```

> **Важно:** Применение этой политики без предварительно настроенных разрешающих правил (например, для DNS) приведет к полной остановке сетевого взаимодействия в кластере.

#### Порядок действий при внедрении Default-Deny

```bash
# 1. Сначала примените разрешающие политики (DNS, Health Checks)
calicoctl apply -f allow-dns.yaml

# 2. Затем примените default-deny
calicoctl apply -f global-default-deny.yaml

# 3. Проверьте, что поды могут разрешать DNS
kubectl run test-dns --image=busybox --restart=Never -- nslookup kubernetes.default
# → Server:    10.96.0.10
# → Name:      kubernetes.default.svc.cluster.local

# 4. Проверьте, что поды НЕ могут общаться между собой без явных правил
kubectl run test-pod-a --image=busybox --restart=Never -- wget -qO- --timeout=3 http://test-pod-b.default.svc
# → connection timed out
```

### Сценарий 5: Безопасность на основе ServiceAccount

**Задача:** Разрешить доступ к базе данных только подам, использующим специфичный ServiceAccount, игнорируя их метки. Это предотвращает атаки через подмену меток (label spoofing).

**Когда использовать:** Микросегментация приложений; защита критичных сервисов (БД, очереди) от несанкционированного доступа; соответствие принципу least privilege.

```yaml
# restrict-by-service-account.yaml
apiVersion: projectcalico.org/v3
kind: NetworkPolicy
metadata:
  name: db-access-control
  namespace: production
spec:
  selector: "app == 'mongodb'"
  ingress:
    - action: Allow
      source:
        serviceAccount:
          selector: "role == 'backend-api'"
    - action: Deny
```

#### Валидация

```bash
kubectl apply -f restrict-by-service-account.yaml

# Проверка политик в namespace
kubectl get networkpolicy -n production
# → db-access-control

# Проверка через calicoctl
calicoctl get networkpolicy -n production
# → db-access-control

# Тест: под с ServiceAccount backend-api должен иметь доступ
kubectl run test-backend --image=mongo:7 --restart=Never -n production \
  --serviceaccount=backend-api -- mongosh --host mongodb --eval "db.adminCommand('ping')"
# → { "ok" : 1 }

# Тест: под без нужного ServiceAccount не должен иметь доступ
kubectl run test-untrusted --image=busybox --restart=Never -n production -- \
  wget -qO- --timeout=3 http://mongodb.production.svc:27017
# → connection timed out
```

> **Примечание:** Использование `serviceAccount` вместо `podSelector` обеспечивает более надежную безопасность, так как метки подов могут быть изменены после создания, а ServiceAccount привязан к RBAC и не может быть подменен.

### Сценарий 6: Защита DNS-трафика

**Задача:** При использовании Global Default-Deny необходимо явно разрешить доступ к DNS (CoreDNS), иначе поды не смогут разрешать имена сервисов.

**Когда использовать:** Обязательный первый шаг при внедрении Default-Deny; защита DNS от внешних атак.

```yaml
# allow-dns.yaml
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: allow-dns-global
spec:
  order: 50 # Высокий приоритет
  selector: "all()"
  types: [Egress]
  egress:
    - action: Allow
      protocol: UDP
      destination:
        selector: "k8s-app == 'kube-dns'"
        namespaceSelector: "kubernetes.io/metadata.name == 'kube-system'"
        ports: [53]
    - action: Allow
      protocol: TCP
      destination:
        selector: "k8s-app == 'kube-dns'"
        namespaceSelector: "kubernetes.io/metadata.name == 'kube-system'"
        ports: [53]
```

#### Валидация

```bash
calicoctl apply -f allow-dns.yaml

# Проверка доступности DNS
kubectl run dns-test --image=busybox --restart=Never -- nslookup kubernetes.default
# → Server:    10.96.0.10
# → Name:      kubernetes.default.svc.cluster.local

# Проверка DNS для внешних доменов (если egress не ограничен)
kubectl run dns-external --image=busybox --restart=Never -- nslookup google.com
# →成功 (if no egress deny policy applied)
```

> **Примечание:** DNS politique разрешает только UDP и TCP на порт 53 к CoreDNS. Если используется внешний DNS (например, через `dnsPolicy: None`), добавьте соответствующие правила.

### Сценарий 7: Управление доступом к внешним API (Egress)

**Задача:** Разрешить подам из namespace `payment` доступ только к API платежного шлюза, блокируя остальной интернет.

**Когда использовать:** Ограничение исходящего трафика подов; защита данных; соответствие требованиям PCI DSS.

```yaml
# restrict-egress-payment-gateway.yaml
apiVersion: projectcalico.org/v3
kind: NetworkPolicy
metadata:
  name: payment-egress-control
  namespace: payment
spec:
  selector: "app == 'payment-processor'"
  types: [Egress]
  egress:
    # Разрешить доступ к API Stripe (пример)
    - action: Allow
      destination:
        nets: ["3.18.0.0/16", "15.152.0.0/16"]
    # Разрешить внутренний DNS
    - action: Allow
      destination:
        selector: "k8s-app == 'kube-dns'"
        namespaceSelector: "kubernetes.io/metadata.name == 'kube-system'"
        ports: [53]
```

#### Валидация

```bash
kubectl apply -f restrict-egress-payment-gateway.yaml -n payment

# Проверка доступа к разрешенному API
kubectl exec -n payment <payment-pod> -- wget -qO- --timeout=5 https://api.stripe.com
# → successful (или ожидаемый HTTP response)

# Проверка блокировки остального интернета
kubectl exec -n payment <payment-pod> -- wget -qO- --timeout=3 https://google.com
# → connection timed out

# Проверка доступа к внутренним сервисам (если не разрешены отдельно)
kubectl exec -n payment <payment-pod> -- wget -qO- --timeout=3 http://other-service.default.svc
# → connection timed out
```

> **Примечание:** Для доступа к внутренним сервисам кластера (меж-namespace) потребуются дополнительные правила. DNS-трафик также должен быть разрешен отдельно.

### Сценарий 8: Микросегментация сервисов

**Задача:** Изолировать компоненты приложения друг от друга на уровне namespace, разрешая только необходимые межсервисные взаимодействия.

**Когда использовать:** Микросегментация в рамках одного namespace; реализация Zero-Trust между микросервисами; соответствие principle of least privilege.

```yaml
# microsegmentation-frontend-backend.yaml
apiVersion: projectcalico.org/v3
kind: NetworkPolicy
metadata:
  name: frontend-allow-backend
  namespace: production
spec:
  selector: "app == 'frontend'"
  types: [Egress]
  egress:
    # Разрешить доступ к backend API
    - action: Allow
      destination:
        selector: "app == 'backend'"
        ports: [8080]
    # Разрешить DNS
    - action: Allow
      destination:
        selector: "k8s-app == 'kube-dns'"
        namespaceSelector: "kubernetes.io/metadata.name == 'kube-system'"
        ports: [53]
---
# microsegmentation-backend-db.yaml
apiVersion: projectcalico.org/v3
kind: NetworkPolicy
metadata:
  name: backend-allow-db
  namespace: production
spec:
  selector: "app == 'backend'"
  types: [Egress]
  egress:
    # Разрешить доступ к MongoDB
    - action: Allow
      destination:
        selector: "app == 'mongodb'"
        ports: [27017]
    # Разрешить DNS
    - action: Allow
      destination:
        selector: "k8s-app == 'kube-dns'"
        namespaceSelector: "kubernetes.io/metadata.name == 'kube-system'"
        ports: [53]
```

#### Валидация

```bash
kubectl apply -f microsegmentation-frontend-backend.yaml -n production

# Тест: frontend -> backend (должен работать)
kubectl exec -n production <frontend-pod> -- wget -qO- --timeout=3 http://backend.production.svc:8080
# → successful

# Тест: frontend -> mongodb (не должен работать)
kubectl exec -n production <frontend-pod> -- wget -qO- --timeout=3 http://mongodb.production.svc:27017
# → connection timed out

# Тест: backend -> mongodb (должен работать)
kubectl exec -n production <backend-pod> -- mongosh --host mongodb --eval "db.adminCommand('ping')"
# → { "ok" : 1 }
```

### Сценарий 9: Защита namespace kube-system

**Задача:** Ограничить доступ к системному namespace `kube-system` только для авторизованных сервисов, предотвращая компрометацию критичных компонентов (etcd, API server, scheduler).

**Когда использовать:** Hardening кластера; защита control-plane компонентов от компрометированных подов; соответствие требованиям CIS Kubernetes Benchmark.

```yaml
# protect-kube-system.yaml
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: restrict-kube-system-access
spec:
  order: 100
  selector: "kubernetes.io/metadata.name == 'kube-system'"
  types: [Ingress]
  ingress:
    # Разрешить доступ от control-plane узлов
    - action: Allow
      source:
        selector: "node-role == 'control-plane'"
    # Разрешить доступ от monitoring (Prometheus)
    - action: Allow
      source:
        namespaceSelector: "kubernetes.io/metadata.name == 'monitoring'"
        selector: "app == 'prometheus'"
    # Запретить всё остальное
    - action: Deny
```

#### Валидация

```bash
calicoctl apply -f protect-kube-system.yaml

# Проверка политики
calicoctl get globalnetworkpolicy restrict-kube-system-access

# Тест: под в kube-system не должен быть доступен из других namespace
kubectl run attacker --image=busybox --restart=Never -- \
  wget -qO- --timeout=3 http://kube-dns.kube-system.svc:53
# → connection timed out

# Тест: Prometheus должен иметь доступ
kubectl exec -n monitoring <prometheus-pod> -- wget -qO- --timeout=3 http://kube-dns.kube-system.svc:53
# → successful
```

### Сценарий 10: BGP-интеграция для bare-metal сред

**Задача:** Настроить обмен маршрутами между Calico и физическими маршрутизаторами для обеспечения маршрутизации подов без overlay-сети (VXLAN/IPIP).

**Когда использовать:** Bare-metal дата-центры с BGP-инфраструктурой; максимальная производительность сети (без overhead инкапсуляции); интеграция с существующей сетевой архитектурой.

#### Шаг 1: Настройка BGPConfiguration

```yaml
# bgp-configuration.yaml
apiVersion: projectcalico.org/v3
kind: BGPConfiguration
metadata:
  name: default
spec:
  logSeverityScreen: Info
  nodeToNodeMeshEnabled: true    # Full mesh между всеми узлами (до ~100 узлов)
  asNumber: 65100                 # AS номер кластера
```

#### Шаг 2: Настройка IPPool с BGP

```yaml
# bgp-ippool.yaml
apiVersion: projectcalico.org/v3
kind: IPPool
metadata:
  name: pod-cidr-bgp
spec:
  cidr: 10.244.0.0/16
  blockSize: 26
  encapsulation: None            # Без инкапсуляции (BGP маршрутизирует)
  natOutgoing: true
  nodeSelector: all()
```

#### Шаг 3: Настройка peering с физическим маршрутизатором

```yaml
# bgp-peer.yaml
apiVersion: projectcalico.org/v3
kind: BGPPeer
metadata:
  name: tor-router
spec:
  peerIP: 10.0.0.1              # IP физического маршрутизатора
  asNumber: 65000                # AS номер маршрутизатора
  nodeSelector: "rack == 'rack-1'"  # Только для узлов в rack-1
```

#### Валидация

```bash
calicoctl apply -f bgp-configuration.yaml
calicoctl apply -f bgp-ippool.yaml
calicoctl apply -f bgp-peer.yaml

# Проверка BGP-сессий
calicoctl node status
# → IPv4 BGP status
# +---------------+-------------------+-------+----------+---------------------------------------------+
# | PEER ADDRESS  |     PEER TYPE     | STATE |  SINCE   |                 INFO                        |
# +---------------+-------------------+-------+----------+---------------------------------------------+
# | 10.0.0.1      | Global            | up    | 10:00:00 | Established                                 |
# +---------------+-------------------+-------+----------+---------------------------------------------+

# Проверка маршрутов на узле
ip route | grep 10.244
# → 10.244.1.0/26 via 10.0.1.10 dev eth0 proto bird
# → 10.244.2.0/26 via 10.0.1.11 dev eth0 proto bird

# Проверка на маршрутизаторе (SSH)
show ip bgp neighbors 10.0.1.10 received-routes
# → Network          Next Hop            Metric LocPrf Weight Path
# → * 10.244.1.0/26  10.0.1.10                            0 65100 i
```

> **Примечание:** Для кластеров более 100 узлов включите `nodeToNodeMeshEnabled: false` и настройте route reflectors для масштабирования BGP.

### Сценарий 11: Egress Gateway для контроля исходящего трафика

**Задача:** Направить весь исходящий трафик подов через определенный узел (egress gateway) для централизованного контроля, аудита и NAT.

**Когда использовать:** Контроль исходящего трафика из кластера; аудит и логирование; работа с внешними сервисами, требующими фиксированных IP.

#### Шаг 1: Пометка узла как egress gateway

```bash
kubectl label nodes egress-node-1 node-role.kubernetes.io/egress-gateway=true
```

#### Шаг 2: Настройка IPPool с egress

```yaml
# egress-gateway-pool.yaml
apiVersion: projectcalico.org/v3
kind: IPPool
metadata:
  name: egress-pool
spec:
  cidr: 203.0.113.0/24          # Публичные IP для egress
  encapsulation: None
  natOutgoing: true
  nodeSelector: "node-role.kubernetes.io/eggress-gateway == 'true'"
```

#### Шаг 3: Направление трафика через egress

```yaml
# egress-route-policy.yaml
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: route-through-egress
spec:
  order: 500
  selector: "app == 'external-caller'"
  types: [Egress]
  egress:
    - action: Allow
      destination:
        nets: ["0.0.0.0/0"]
    # Трафик будет NAT через IP egress узла
```

> **Примечание:** Egress Gateway требует, чтобы у egress узла был доступ к внешней сети и он был настроен как шлюз (IP forwarding включен: `sysctl -w net.ipv4.ip_forward=1`).

### Сценарий 12: Откат и восстановление при ошибке политики

**Задача:** Быстро восстановить сетевую связность, если примененная политика заблокировала критичный трафик.

**Когда использовать:** Инциденты; ошибки при развертывании политик; потеря SSH-доступа к узлам.

#### Вариант 1: Удаление политики через Kubernetes API (если доступен)

```bash
# Если kubectl доступен (например, через bastion-хост)
kubectl delete globalnetworkpolicy --all
# Или удаление конкретной политики
kubectl delete globalnetworkpolicy default-deny-perimeter
```

#### Вариант 2: Удаление через calicoctl на узле (если SSH доступен)

```bash
# SSH на узел
ssh admin@192.168.1.10

# Удаление всех политик
sudo calicoctl delete globalnetworkpolicy --all

# Или удаление конкретной
sudo calicoctl delete globalnetworkpolicy default-deny-perimeter
```

#### Вариант 3: Сброс Felix (последнее средство)

```bash
# Остановка Felix для отключения всех правил
sudo calico-node -felix-live --shutdown

# Правила iptables/nftables будут очищены
# ПЕРЕЗАПУСТИТЕ calico-node для восстановления
sudo systemctl restart calico-node
```

> **Важно:** Вариант 3 приводит к полному отсутствию сетевых политик до перезапуска calico-node. Используйте только как последнее средство.

#### Проактивная защита: Dry-Run перед применением

```bash
# Просмотр политик, которые будут применены
calicoctl apply -f policy.yaml --dry-run

# Проверка воздействия на конкретный под
calicoctl get networkpolicy <policy-name> -o yaml | grep -A5 selector
```

## Дополнительная информация

### Новые возможности (2024-2025)

*   **nftables Dataplane**: Начиная с Calico v3.29, `nftables` используется по умолчанию. Обеспечивает лучшую производительность и совместимость с современными дистрибутивами Linux (RHEL 9, Debian 12+).
*   **Admin Network Policy (ANP)**: Поддержка стандартного Kubernetes API (v1alpha1+) для управления кластерными политиками безопасности с четким разделением ролей. ANP имеет приоритет над стандартными NetworkPolicy.

### Версионная совместимость

| Возможность | Минимальная версия Calico | Примечания |
| :--- | :--- | :--- |
| GlobalNetworkPolicy | v3.0+ | Базовая функциональность |
| HostEndpoint + preDNAT | v3.0+ | Требует Calico datastore или Kubernetes API |
| eBPF dataplane | v3.13+ | Требует ядро Linux 5.3+ |
| nftables dataplane | v3.29+ | По умолчанию с v3.29 |
| Policy Tiers | v3.7+ | Требует etcd datastore |
| WireGuard encryption | v3.13+ | Node-to-Node шифрование |
| Admin Network Policy | v3.25+ | Kubernetes API v1alpha1 |
| BGP peering | v3.0+ | Для bare-metal сценариев |

### Связанные ресурсы

* **Подробные определения**: [Calico HostEndpoint и GlobalNetworkPolicy — Определения](./index.md)
* **Диагностика и команды**: [Операции Calico: Диагностика и обслуживание](./operations.md)
* **Лучшие практики**: [NetworkPolicy: Лучшие практики](../../../Networking/Network/NetworkPolicy/best_practices.md)
* **eBPF в Calico**: [Оптимизация сети через eBPF](../../../Networking/Network/CNI/ebpf.md)
