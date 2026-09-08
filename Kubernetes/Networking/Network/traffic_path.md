# Путь трафика в Kubernetes

## Определения

**Путь трафика (Traffic Path)** — это сквозная последовательность сетевых узлов, интерфейсов и программных компонентов, через которые проходит пакет данных от инициатора запроса до целевого процесса в контейнере. Понимание этого пути критично для диагностики сетевых проблем, оптимизации производительности и проектирования отказоустойчивых архитектур.

**North-South трафик (Север-Юг)** — сетевые потоки, пересекающие периметр кластера. Включают входящие запросы от внешних пользователей (Ingress/Gateway) и исходящие запросы подов во внешние сети (Egress). Этот трафик проходит через внешние балансировщики, контроллеры Ingress/Gateway API и сетевой стек узла.

**East-West трафик (Восток-Запад)** — внутренние сетевые потоки между подами, сервисами или системными компонентами в рамках одного или нескольких кластеров. Составляет основную часть трафика в микросервисных архитектурах (80-90% от общего объема). Этот трафик никогда не покидает периметр кластера и обрабатывается исключительно CNI и kube-proxy.

**Gateway API** — эволюционный стандарт Kubernetes для управления трафиком на уровнях L4 и L7. В отличие от Ingress, Gateway API предоставляет ролевую модель (GatewayClass для провайдеров, Gateway для админов, HTTPRoute/TCPRoute для разработчиков) и нативную поддержку сложных сценариев (Canary, зеркалирование, фильтры). Стал основным стандартом для управления трафиком в 2025-2026 годах.

**ExternalTrafficPolicy** — критический параметр сервиса, определяющий логику обработки внешнего трафика на узле:
- **`Cluster`** (по умолчанию): трафик балансируется между всеми подами в кластере, что может привести к дополнительному «прыжку» (hop) между узлами и потере Source IP из-за SNAT.
- **`Local`**: трафик направляется только на поды, находящиеся на том же узле, где был принят пакет. Это сохраняет Source IP клиента и минимизирует задержки, но требует интеллектуальной балансировки на внешнем LB.

**InternalTrafficPolicy** — параметр сервиса (стабилен с v1.26), определяющий маршрутизацию внутреннего (East-West) трафика:
- **`Cluster`** (по умолчанию): трафик может маршрутизироваться между узлами для достижения любого эндпоинта.
- **`Local`**: трафик направляется только на локальные поды того же узла. Если локальных подов нет, соединение отбрасывается. Используется для сервисов, критичных к задержкам (database sidecars, кэши).

**Topology Aware Routing** — механизм оптимизации East-West трафика, при котором `kube-proxy` или CNI предпочитают эндпоинты в той же зоне доступности (Availability Zone), снижая задержки и исключая затраты на межзонный трафик. В 2026 году реализуется через поле `trafficDistribution` в Service (Superseded).

**conntrack (Connection Tracking)** — механизм ядро Linux, отслеживающий состояния активных сетевых соединений. Используется kube-proxy, IPVS и CNI для корректной маршрутизации ответного трафика, реализации Hairpin NAT, Session Affinity и Graceful Termination. Переполнение таблицы conntrack — одна из самых частых причин «молчаливых» падений сети в кластерах.

**Hairpin NAT** — механизм ядра Linux, позволяющий поду обращаться к ClusterIP сервиса, в котором он участвует, без потери пакета. Без Hairpin NAT пакет, отправленный подом на VIP и перенаправленный ядром обратно на IP того же пода, был бы отброшен. Реализуется через `kube-proxy` с настройкой `hairpin-mode: promiscuous-bridge`.

## Основные концепции

### Полный путь пакета (Визуальная схема)

Ниже представлена упрощенная ASCII-диаграмма пути пакета для двух основных сценариев:

#### Сценарий 1: North-South (внешний запрос → под)

```
Клиент (Internet)
    │
    │  DNS-резолвинг (FQDN → External LB IP)
    ▼
┌─────────────────────────┐
│  Внешний Load Balancer  │  (MetalLB / Cloud LB)
│  L4: VIP → NodePort     │  Health Checks → узлы
└────────────┬────────────┘
             │  TCP SYN → NodeIP:NodePort
             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                           УЗЕЛ (Node)                               │
│                                                                     │
│  ┌──────────────┐    ┌──────────────────────────────────────────┐   │
│  │  PREROUTING  │───▶│  kube-proxy / eBPF                        │   │
│  │  ( DNAT )    │    │  ClusterIP → PodIP (если Ingress → SVC)  │   │
│  └──────────────┘    └──────────────────┬───────────────────────┘   │
│                                          │                           │
│                                          ▼                           │
│                               ┌─────────────────┐                   │
│                               │  conntrack table │                   │
│                               │  (отслеживание)  │                   │
│                               └────────┬────────┘                   │
│                                        │                             │
│                                        ▼                             │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Routing Table (ip route) ──▶ CNI (veth pair / eBPF)         │   │
│  └──────────────────────────────────────┬───────────────────────┘   │
│                                         │                            │
│                                         ▼                            │
│                               ┌─────────────────┐                   │
│                               │  Pod Network NS  │                   │
│                               │  (eth0: PodIP)   │                   │
│                               └─────────────────┘                   │
└─────────────────────────────────────────────────────────────────────┘
```

#### Сценарий 2: East-West (под → под через Service)

```
Pod A (10.244.1.5)
    │
    │  curl http://my-service.default.svc.cluster.local:80
    │
    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  DNS-резолвинг (CoreDNS или NodeLocal DNSCache)                     │
│  my-service.default.svc.cluster.local → 10.96.0.20 (ClusterIP)     │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          УЗЕЛ A (Source Node)                        │
│                                                                     │
│  Pod A → eth0 ──▶ veth ──▶ Network Stack узла                       │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  kube-proxy (nftables/IPVS/eBPF)                             │   │
│  │  DNAT: 10.96.0.20:80 → 10.244.2.8:8080 (выбранный Pod B)    │   │
│  └──────────────────────────────────────┬───────────────────────┘   │
│                                         │                            │
│  ┌──────────────────────────────────────┼───────────────────────┐   │
│  │  CNI Routing: следующий хоп — узел B (192.168.1.20)          │   │
│  │  VXLAN encap (или native route) → отправка на узел B         │   │
│  └──────────────────────────────────────┼───────────────────────┘   │
└─────────────────────────────────────────┼───────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          УЗЕЛ B (Target Node)                        │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  CNI Decapsulation → Routing → veth → Pod Network NS         │   │
│  └──────────────────────────────────────┬───────────────────────┘   │
│                                         │                            │
│                                         ▼                            │
│                               ┌─────────────────┐                   │
│                               │  Pod B (10.244.2.8)                 │
│                               │  (eth0: 8080)    │                   │
│                               └─────────────────┘                   │
└─────────────────────────────────────────────────────────────────────┘
```

### Входящий трафик (North-South: Входящий путь)

Полный жизненный цикл внешнего HTTPS-запроса в современных кластерах (2026) описывается следующими этапами с обязательными контрольными точками:

1.  **DNS-резолвинг**: Клиент разрешает FQDN в IP-адрес внешнего балансировщика (Cloud LB или MetalLB).
    -   *Контрольная точка:* Соответствие A/AAAA-записей актуальному VIP балансировщика.
    -   *Деталь:* В bare-metal средах MetalLB анонсирует VIP через ARP (L2) или BGP (L3). При использовании BGP с ECMP трафик распределяется между несколькими узлами равномерно.
2.  **Внешний Load Balancer**: Принимает трафик и распределяет его по узлам кластера (обычно через NodePort) или напрямую на IP подов (при использовании облачных CNI).
    -   *Контрольная точка:* Проверка Health Check на уровне балансировщика (готовность узлов принимать трафик).
    -   *Деталь:* При `externalTrafficPolicy: Local` LB должен обладать интеллектуальную маршрутизацию — направлять трафик только на узлы, содержащие целевые поды. В противном случае часть запросов получит 503.
3.  **Gateway / Ingress Controller**: Пакет достигает точки входа L7. Контроллер выполняет:
    - Терминацию TLS (SSL Termination) и инспекцию трафика.
    - Сопоставление запроса с правилами маршрутизации (`HTTPRoute` / `Ingress`).
    - *Контрольная точка:* Валидность сертификатов и точность сопоставления путей (Path matching).
    -   *Деталь:* Современные контроллеры (Envoy Gateway, Cilium, Traefik) используют Gateway API и работают в User Space или через eBPF, минуя традиционный стек Netfilter.
4.  **Маршрутизация через Service и EndpointSlice**: Контроллер находит целевой Service и выбирает конкретный IP пода из актуального `EndpointSlice`.
    -   *Контрольная точка:* Соответствие селекторов Service меткам Pod. Наличие готовых (`Ready`) эндпоинтов.
    -   *Деталь:* EndpointSlice Controller автоматически обновляет список эндпоинтов, группируя их по 100 единиц. kube-proxy или eBPF CNI получает дельты изменений через watch API-сервера.
5.  **Обработка на узле (Netfilter/eBPF)**: Пакет проходит через сетевой стек узла.
    -   В режиме **nftables** (v1.31+) пакет проходит через оптимизированные таблицы трансляции.
    -   В режиме **eBPF (Cilium)** пакет перехватывается на уровне драйвера сетевой карты и доставляется в под, минуя стек Netfilter.
    -   *Контрольная точка:* Проверка отсутствия дропов в `conntrack` и корректность правил SNAT/DNAT.
    -   *Деталь:* conntrack — критический компонент. При переполнении таблицы (`nf_conntrack_max`) новые соединения отбрасываются без логирования, что маскируется под проблемы приложения.
6.  **Доставка в Pod**: Пакет попадает в `network namespace` пода через `veth`-пару.
    -   *Контрольная точка:* Состояние `Readiness Probe` — если под не готов, он исключается из пути трафика до восстановления.
    -   *Деталь:* Veth-пара — это два связанных виртуальных интерфейса. Один находится в namespace пода (`eth0`), другой — в namespace хоста (`vethXXXX`). Пакет «проходит» через пару без реальной сетевой передачи.

### Graceful Termination: Жизненный цикл удаления пода

Когда под удаляется (масштабирование, обновление Deployment, ручное удаление), трафик должен быть плавно переключен на оставшиеся реплики:

1.  API-сервер помечает под как `Terminating`.
2.  **EndpointSlice Controller** немедленно удаляет IP пода из списка эндпоинтов.
3.  `kube-proxy` (или eBPF CNI) обновляет правила, прекращая направлять *новый* трафик на этот под.
4.  **Существующие соединения** остаются активными благодаря `conntrack`. TCP-сессии продолжают работать до завершения приложения или истечения `terminationGracePeriodSeconds`.
5.  Для предотвращения 502 ошибок рекомендуется использовать **`PreStop` хук** с задержкой 5-10 секунд, чтобы LB успел обновить список эндпоинтов:

```yaml
lifecycle:
  preStop:
    exec:
      command: ["sh", "-c", "sleep 10"]
terminationGracePeriodSeconds: 30
```

### Hairpin NAT: Под обращается к own Service

Сценарий: под обращается к ClusterIP сервиса, в котором он сам является эндпоинтом. Без Hairpin NAT пакет будет отброшен, так как DNAT направит его обратно на тот же IP.

**Как это работает:**
1. Pod A отправляет пакет на ClusterIP (10.96.0.20).
2. kube-proxy выполняет DNAT: ClusterIP → PodIP (10.244.1.5 — тот же Pod A).
3. Ядро Linux определяет, что целевой IP совпадает с исходным интерфейсом.
4. **Hairpin NAT** выполняет SNAT (меняет source на IP veth-моста), чтобы пакет вернулся через тот же интерфейс.
5. Pod A получает пакет как будто он пришел извне.

**Включение:**
```bash
# Проверка текущего hairpin-mode
kubectl get kubelet -o yaml | grep hairpin
# → hairpinMode: promiscuous-bridge

# Включение (если отключено)
# В KubeletConfiguration:
hairpinMode: promiscuous-bridge
```

**Диагностика:**
```bash
# Проверка hairpin-интерфейсов
ip link show | grep hairpin
# → vethXXXXXX@if2: <BROADCAST,MULTICAST,UP> master cni0 ...
```

### Обработка на узле: Сравнение механизмов

В 2026 году выбор механизма обработки трафика на узле определяет производительность и масштабируемость кластера.

| Механизм | Статус (2026) | Особенности | Преимущества |
| :--- | :--- | :--- | :--- |
| **iptables** | Legacy | Последовательный перебор правил ($O(n)$). | Совместимость со старым софтом. |
| **nftables** | Стандарт (v1.31+) | Двоичное дерево правил, атомарные обновления. | В 2-4 раза быстрее iptables в крупных кластерах. |
| **IPVS** | Стабильный | Использование хеш-таблиц для балансировки ($O(1)$). | Эффективен при >5000 сервисов. |
| **eBPF** | Рекомендуемый | Выполнение кода в ядре, обход netfilter. | Минимальный CPU overhead, глубокая наблюдаемость. |

### Сохранение Source IP клиента

Сохранение реального IP-адреса клиента критично для безопасности (WAF) и аналитики.

1.  **externalTrafficPolicy: Local**:
    - Пакет приходит на Node A. Если на Node A есть целевой под, Source IP сохраняется.
    - Если на Node A нет пода, пакет отбрасывается (что заставляет внешний LB переключиться на живые узлы).
    - *Риск:* «Перекос» нагрузки, если поды распределены неравномерно по узлам.
2.  **Proxy Protocol / HTTP Headers**:
    - Внешний LB передает Source IP в заголовке `X-Forwarded-For` или через `PROXY Protocol` (L4).
    - Gateway Controller считывает эти данные и передает приложению.
    - *Требование:* Gateway/Ingress должен быть настроен на доверие к заголовкам от LB.

### Внутреннее взаимодействие (East-West)

East-West трафик составляет основную часть сетевого взаимодействия в микросервисных архитектурах. Он делится на несколько подкатегорий:

#### 1. Внутри пода (Intra-Pod)

Контейнеры в составе одного пода общаются через `127.0.0.1` (localhost). Весь трафик остается внутри одного Network Namespace, не выходя в сеть. Это самый быстрый и безопасный способ взаимодействия — пакеты не покидают стек TCP/IP ядра и не проходят через сетевые интерфейсы.

**Использование:** Sidecar-контейнеры (Envoy, Nginx), шаринг данных между контейнерами.

#### 2. Pod-to-Pod (один узел / Intra-Node)

Когда поды находятся на одном хосте, CNI создает виртуальные пары интерфейсов (**veth-pairs**):
- Один конец (`eth0`) находится внутри namespace пода.
- Второй конец (`vethXXXX`) находится в namespace хоста.
- Связность обеспечивается либо через программный мост (`cni0`, `docker0`), либо через прямую маршрутизацию в стеке хоста.

**Путь пакета:**
```
Pod A (eth0) → vethXXXX → Bridge (cni0) → vethYYYY → Pod B (eth0)
```

**Особенности:**
- Отсутствие инкапсуляции (нет overhead VXLAN/Geneve).
- MTU подов = MTU узла (обычно 1500).
- Задержка < 0.1 мс (одно переключение контекста).

#### 3. Pod-to-Pod (разные узлы / Inter-Node)

Межузловой трафик — самый сложный сценарий. Реализуется CNI-плагинами одним из трех методов:

**Overlay (VXLAN/Geneve):**
- Пакет инкапсулируется в UDP-пакет узла.
- *Проблема MTU:* Инкапсуляция добавляет заголовок (обычно 50 байт для VXLAN). Если MTU узла — 1500, то MTU пода должен быть **1450**, чтобы избежать фрагментации.
- *Диагностика:* `ping -M do -s 1400 <pod-ip>` — если пакет проходит, MTU настроен корректно.

**Direct Routing (BGP/VPC):**
- Узлы знают маршруты к Pod CIDR друг друга напрямую.
- Пакеты передаются без инкапсуляции с максимальной скоростью.
- Требует BGP-совместимого маршрутизатора или статических маршрутов.
- Поды видны из физической сети напрямую по IP-адресу.

**eBPF-native (Cilium):**
- Трафик перехватывается на уровне драйвера сетевой карты.
- Полный обход стека Netfilter/iptables.
- Прямая доставка пакета в нужный интерфейс на основе Identity-based политик.

#### 4. Service-to-Service (через ClusterIP)

Самый распространенный сценарий East-West трафика:

1. **DNS-резолвинг:** Под A обращается к `my-service.default.svc.cluster.local`. CoreDNS (или NodeLocal DNSCache) возвращает ClusterIP (10.96.0.20).
2. **Перехват на уровне ядра:** Пакет с destination ClusterIP перехватывается kube-proxy (или eBPF).
3. **DNAT:** ClusterIP заменяется на реальный IP Pod B (10.244.2.8).
4. **Маршрутизация:** Если Pod B на другом узле — пакет инкапсулируется (VXLAN) или маршрутизируется напрямую (BGP).
5. **Доставка:** Пакет попадает в Pod B через veth-пару.

**Проблема gRPC/HTTP/2:** Из-за мультиплексирования HTTP/2 все запросы идут по одному TCP-соединению. kube-proxy (L4) выберет один под в начале сессии, и все последующие gRPC-вызовы уйдут на него, вызывая перекос нагрузки. Решение: балансировка L7 через Gateway API, Ingress Controller или Service Mesh.

#### 5. DNS-резолвинг: Путь DNS-запроса

DNS — критическая зависимость для Service Discovery. Каждый DNS-запрос проходит определенный путь:

```
Pod → /etc/resolv.conf (nameserver 10.96.0.10) → CoreDNS Service → CoreDNS Pod
```

**Проблема conntrack race:** При UDP-запросах к CoreDNS через ClusterIP возникает race condition в `nf_conntrack`. Если два одновременных UDP-запроса попадают в одну и ту же цепочку правил, один из них может получить задержку 1-5 секунд или NXDOMAIN.

**Решение — NodeLocal DNSCache:**
- DaemonSet, запускающий кэширующий DNS-агент на каждом узле.
- DNS-запросы идут на локальный IP (169.254.20.10), а не на CoreDNS ClusterIP.
- Снижает нагрузку на CoreDNS и исключает conntrack race.
- Рекомендуется для всех production-кластеров.

```bash
# Установка NodeLocal DNSCache
kubectl apply -f https://raw.githubusercontent.com/kubernetes/kubernetes/refs/heads/master/cluster/addons/dns/nodelocaldns/nodelocaldns.yaml

# Проверка статуса
kubectl get daemonset -n kube-system node-local-dns
kubectl logs -n kube-system -l k8s-app=node-local-dns --tail=20
```

### Исходящий трафик (Egress)

Исходящий трафик — это пакеты, покидающие периметр кластера (под → внешний мир). Он обрабатывается на каждом узле через механизмы NAT и маршрутизации.

#### 1. SNAT на узле (Маскарадинг)

По умолчанию пакет пода при выходе за пределы кластера получает IP-адрес узла через механизм **masquerade** (SNAT). Это необходимо, потому что:
- Pod CIDR (например, 10.244.0.0/16) не маршрутизируется во внешней сети.
- Внешний роутер не знает, как вернуть пакет поду, если source IP — Pod IP.

**Как это работает:**
1. Pod отправляет пакет на внешний IP (например, 8.8.8.8).
2. Пакет проходит через таблицу маршрутизации узла.
3. Правила `POSTROUTING` в nftables/iptables выполняют SNAT: source IP заменяется на IP узла (например, 192.168.1.10).
4. Внешний сервер видит запрос от IP узла и отправляет ответ ему.
5. conntrack восстанавливает original Pod IP и перенаправляет ответ обратно поду.

**Ограничения:**
- Source IP пода скрыт — невозможно логировать реального клиента.
- Нагрузка на conntrack — каждое соединение требует записи.
- При массовом Egress-трафике узел может стать «бутылочным горлышком».

#### 2. Egress Gateway (Service Mesh)

Весь внешний трафик подов принудительно направляется на выделенные прокси-поды (Egress Gateway). Это позволяет:
- Использовать единый статический IP для внешних Firewall.
- Выполнять L7-фильтрацию (например, разрешить доступ только к `*.api.google.com`).
- Централизованно логировать весь исходящий трафик.
- Реализовать политики доступа на основе CIDR или FQDN.

**Конфигурация (Cilium Egress Gateway):**
```yaml
apiVersion: cilium.io/v2
kind: CiliumEgressGatewayPolicy
metadata:
  name: egress-to-internet
spec:
  selectors:
  - matchLabels:
      app: my-service
  egress:
  - identity: "reserved-world"
    CIDRSet:
    - "0.0.0.0/0"
  egressGateway:
    egressGatewayIP: 192.168.1.100
    nodeSelector:
      matchLabels:
        kubernetes.io/hostname: egress-node-1
```

#### 3. Cilium Egress Gateway (без sidecar)

Реализует выбор выходного IP на уровне eBPF без использования Sidecars, что значительно снижает задержки. В отличие от классических решений Service Mesh, Cilium Egress Gateway работает на уровне ядра и не требует запуска дополнительных прокси-контейнеров в каждом поде.

**Преимущества:**
- Минимальный overhead (обработка в ядре).
- Нативная поддержка Cilium NetworkPolicy (L3/L4/L7).
- Автоматическое переключение при отказе Egress Gateway узла.

#### 4. Исключения из SNAT (No-Masquerade)

В некоторых случаях SNAT нежелателен (например, для трафика внутри кластера или к известным сетям):

```bash
# Исключение Pod CIDR из masquerade
# В kube-proxy config:
masqueradeAll: false
masqueradeBit: 14
# --no-masquerade-cidr=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
```

В Cilium настройка `bpf.masquerade=true` использует eBPF для более эффективного маскарадинга без правил iptables.

## Диагностика и отладка

При возникновении проблем с трафиком необходимо использовать последовательный подход «снизу вверх» (от L2 до L7). Ниже приведен полный стек диагностики с реальными командами.

### Уровень 1: L2/L3 — Связность и маршрутизация

**Цель:** Убедиться, что пакеты физически доставляются от источника к назначению.

```bash
# 1. Проверка IP-адреса пода
kubectl get pod <pod-name> -o wide
# → видим IP пода и узел, на котором он запущен

# 2. Проверка маршрутов из пода
kubectl exec -it <pod> -- ip route
# → default via 10.244.0.1 dev eth0
# → 10.244.1.0/24 via 10.244.0.1 dev eth0  (маршрут к другому узлу)

# 3. Проверка connectivity до другого пода
kubectl exec -it <pod-a> -- ping -c 3 <pod-b-ip>
# → если нет ответа — проблема на L2/L3 (CNI, маршрутизация, MTU)

# 4. Проверка MTU (критично для Overlay)
kubectl exec -it <pod> -- ping -M do -s 1472 -c 2 <pod-b-ip>
# → если пакеты проходят — MTU корректен
# → если Fragmentation needed — MTU несоответствие

# 5. Проверка ARP-таблицы на узле
ip neigh show | grep <pod-ip>
# → должен показывать MAC-адрес veth-интерфейса

# 6. Проверка таблицы маршрутизации на узле
ip route show | grep <pod-cidr>
# → должен показывать route через vethXXX или vxlan
```

### Уровень 2: L4 — Service и EndpointSlice

**Цель:** Убедиться, что Service правильно резолвится и эндпоинты доступны.

```bash
# 1. Проверка Service
kubectl get svc <service-name>
# → CLUSTERIP, PORT(S), AGE

# 2. Проверка EndpointSlice (актуальные эндпоинты)
kubectl get endpointslice -l kubernetes.io/service-name=<svc-name>
# → должен содержать Ready адреса подов

# 3. Проверка DNS-резолвинга ClusterIP из пода
kubectl exec -it <pod> -- nslookup <service-name>.<namespace>.svc.cluster.local
# → Name:      <service-name>.<namespace>.svc.cluster.local
# → Address:   10.96.x.x

# 4. Проверка доступности Service по IP
kubectl exec -it <pod> -- curl -v http://<service-cluster-ip>:<port>
# → должен вернуть ответ от приложения

# 5. Проверка conntrack для конкретного соединения
kubectl exec -it <debug-pod> -- conntrack -L -p tcp --dport 80 | grep <pod-ip>
# → покажет активные соединения к поду
```

### Уровень 3: Netfilter/nftables/eBPF — Правила трансляции

**Цель:** Проверить, что правила DNAT/SNAT корректно программируются.

```bash
# 1. Проверка текущего режима kube-proxy
kubectl -n kube-system get configmap kube-proxy -o yaml | grep mode
# → mode: "nftables" (или "ipvs", "iptables")

# 2. Просмотр правил nftables (kube-proxy)
nft list table ip kube-proxy | head -n 30
# → показывает цепочки KUBE-SERVICES, KUBE-SVC-*, KUBE-SEP-*

# 3. Просмотр правил iptables (если режим iptables)
iptables -t nat -L KUBE-SERVICES -n | head -n 20
# → показывает правила DNAT для сервисов

# 4. Просмотр таблиц IPVS (если режим IPVS)
sudo ipvsadm -Ln
# → Prot LocalAddress:Port Scheduler Flags
# →   -> RemoteAddress:Port           Forward Weight ActiveConn InActConn

# 5. Проверка eBPF-программ (Cilium)
sudo bpftool prog list | grep cilium
# → список загруженных eBPF-программ

# 6. Просмотр BPF Maps (Cilium)
cilium bpf ct list global
# → таблица connection tracking
```

### Уровень 4: L7 — Прикладной уровень

**Цель:** Убедиться, что приложение корректно обрабатывает запросы.

```bash
# 1. Проверка HTTP-ответа через Service
kubectl exec -it <pod> -- curl -v http://<service>:<port>/healthz
# → HTTP/1.1 200 OK (или код ошибки)

# 2. Проверка заголовков
kubectl exec -it <pod> -- curl -I http://<service>:<port>
# → Content-Type, Server, и др.

# 3. Проверка TLS (если terminates на Ingress/Gateway)
kubectl exec -it <pod> -- curl -vk https://<external-host>/healthz
# → проверка сертификата и TLS-握手

# 4. Проверка через Ingress/Gateway
curl -H "Host: <hostname>" http://<ingress-ip>/path
# → должен вернуть ответ от приложения

# 5. Логи приложения
kubectl logs <pod> --tail=50
# → проверка ошибок на уровне приложения
```

### Глубокая трассировка через eBPF (pwru)

Инструмент `pwru` (Packet, Where aRe yoU?) позволяет увидеть, на какой функции ядра пакет был отброшен (drop):

```bash
# Установка pwru (требуется root на узле)
# Использование через Cilium:
kubectl debug node/<node> -it --image=quay.io/cilium/pwru:latest
# Внутри debug-контейнера:
pwru --pcap out.pcap "dst port 8080"

# Или через kubectl debug (Kubernetes 1.25+):
kubectl debug node/<node> --profile=sysadmin -it --image=nicolaka/netshoot
# Внутри контейнера:
pwru --filter-dst-port 80 --output-tuple
# → показывает функцию ядра (например, bpf_lxc_netpolicy), где произошел дроп
```

### Мониторинг Cilium/Hubble

```bash
# Наблюдение за всем трафиком конкретного пода
hubble observe --pod <pod-name> --follow

# Фильтрация по типу (drop, forward, denied)
hubble observe --type drop --follow

# Фильтрация по неймспейсу и поду
hubble observe -n <namespace> --pod <pod> --follow

# Просмотр последних N записей
hubble observe --last 20 --pod <pod-name>

# Проверка verdict (куда ушел пакет)
hubble observe --verdict DROPPED --follow
```

### Диагностика conntrack

conntrack — критический компонент. При его проблемах трафик «молча» падает:

```bash
# 1. Проверка использования conntrack
sudo conntrack -C
# → текущее количество записей
sudo sysctl net.netfilter.nf_conntrack_max
# → максимальный лимит

# 2. Статистика conntrack (важно для поиска проблем)
sudo conntrack -S
# → cpu=0 found=123456 invalid=789 lost=0 insert_failed=0
# → если lost > 0 или insert_failed > 0 — проблема с переполнением

# 3. Поиск соединений конкретного пода
sudo conntrack -L -p tcp --dport 80 | grep 10.244.1.5
# → покажет все активные TCP-соединения к поду

# 4. Очистка conntrack (при необходимости, например, после смены правил)
sudo conntrack -D -s 10.244.1.5
sudo conntrack -D -d 10.96.0.20
# → удаление записей для конкретного source/destination IP

# 5. Мониторинг переполнения в реальном времени
watch -n 1 "conntrack -C; sysctl net.netfilter.nf_conntrack_max"
# → если count приближается к max — проблема

# 6. Проверка таймаутов
sudo conntrack -L --timeout
# → покажет таймауты для разных протоколов
```

## Практические сценарии и типичные проблемы

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Connection Timeout (Межсетевой)** | MTU Mismatch в Overlay | `ping -M do -s 1472 <pod-ip>` — пакеты не проходят | Уменьшить MTU в CNI-конфигурации до 1450 (для VXLAN/Geneve). Убедиться, что MTU на физических узлах >= 1550 |
| **Wrong Source IP (Виден IP узла)** | `externalTrafficPolicy: Cluster` | `kubectl get svc <svc> -o yaml \| grep trafficPolicy` | Изменить на `Local` или включить PROXY Protocol на LB |
| **503 Service Unavailable** | Эндпоинты не прошли Readiness Probe | `kubectl get endpointslice -l kubernetes.io/service-name=<svc>` — нет Ready адресов | Проверить логи приложения и настройки `readinessProbe` в манифесте |
| **NXDOMAIN при обращении к SVC** | Перегрузка CoreDNS или conntrack race | `kubectl logs -n kube-system -l k8s-app=kube-dns` — проверить нагрузку | Установить NodeLocal DNSCache. Проверить `conntrack -S` |
| **Packet Drop (Silent)** | NetworkPolicy или некорректный SNAT | `hubble observe --type drop` или `conntrack -S` (проверить lost) | Проверить логи Cilium (`cilium monitor`) или `nft list ruleset` |
| **Timeout к конкретному Pod** | conntrack переполнен | `conntrack -C` vs `sysctl net.netfilter.nf_conntrack_max` | Увеличить `nf_conntrack_max` до 1M+. Добавить мониторинг |
| **502 Bad Gateway при удалении пода** | Нет Graceful Termination | `kubectl describe pod <pod>` — нет PreStop hooks | Добавить `preStop: sleep 10` и `terminationGracePeriodSeconds: 30` |
| **Трафик идет на один под (gRPC)** | L4-балансировка HTTP/2 | `ipvsadm -Ln` — все соединения на один backend | Использовать Gateway API или Service Mesh для L7-балансировки |
| **ARP-конфликт (VIP «плавает»)** | MetalLB strictARP отключен | `arping -D <vip>` — 여러 ответа | Включить `strictARP: true` в kube-proxy |
| **DNS не резолвится из пода** | CoreDNS down или NetworkPolicy блокирует | `kubectl get pods -n kube-system -l k8s-app=kube-dns` | Проверить NetworkPolicy для kube-dns. Проверить `kubectl logs -n kube-system -l k8s-app=kube-dns` |
| **Высокий CPU на kube-proxy** | Большой churn сервисов (iptables) | `top` — kube-proxy использует >30% CPU | Перейти на nftables (K8s 1.31+) или eBPF (Cilium) |
| **Внутриузловой трафик не шифруется** | WireGuard шифрует только inter-node | `cilium encrypt status` — только Node-level | Включить `encryption.nodeEncryption=true` для host-трафика |
| **Pod не получает IP** | IPAM исчерпан или CNI не работает | `kubectl describe pod <pod>` → Events: `Failed to allocate` | Расширить Pod CIDR. Проверить CNI (`kubectl get ds -n kube-system`) |
| **Сервисы не балансируются (IPVS)** | kube-proxy не обновил таблицы | `ipvsadm -Ln` — нет записей для сервиса | Проверить `syncPeriod`. Перезапустить `kubectl rollout restart ds/kube-proxy -n kube-system` |
| **Hairpin не работает** | hairpin-mode отключен | `kubectl exec -it <pod> -- curl <svc-clusterip>` — timeout | Включить `hairpinMode: promiscuous-bridge` в KubeletConfiguration |

### Пошаговый алгоритм диагностики

При возникновении сетевой проблемы следуйте этому алгоритму:

```bash
# Шаг 1: Определите, на каком уровне проблема
kubectl exec -it <pod-a> -- ping -c 2 <pod-b-ip>
# → если нет ответа — проблема на L3 (CNI, маршрутизация)
# → если есть ответ — проблема на L4/L7

# Шаг 2: Проверьте Service
kubectl exec -it <pod-a> -- nslookup <service-name>
kubectl exec -it <pod-a> -- curl -v http://<service>:<port>

# Шаг 3: Проверьте эндпоинты
kubectl get endpointslice -l kubernetes.io/service-name=<svc-name>
# → если нет Ready — проблема с подами (readiness probe)

# Шаг 4: Проверьте conntrack
sudo conntrack -S
# → если lost > 0 — переполнение таблицы

# Шаг 5: Проверьте правила трансляции
nft list table ip kube-proxy | grep <service-clusterip>
# → должен показывать DNAT правила

# Шаг 6: Проверьте логи CNI (Cilium)
hubble observe --pod <pod-a> --type drop --follow
```

## Архитектурные рекомендации

1.  **Использование eBPF**: Для высоконагруженных систем (High Load) рекомендуется использовать Cilium в режиме замены `kube-proxy` для минимизации задержек и исключения проблем с масштабированием правил Netfilter. В 2026 году eBPF стал де-факто стандартом для production-кластеров.

2.  **Gateway API как стандарт**: Переходите на Gateway API для всех новых сервисов. Это обеспечит лучшую управляемость и готовность к будущим обновлениям Kubernetes. Ingress считается legacy-интерфейсом.

3.  **Конфигурация MTU**: В Overlay-средах всегда явно задавайте MTU для подов, чтобы избежать труднодиагностируемых проблем с обрывом TCP-сессий при передаче больших объемов данных. Для VXLAN/Geneve — MTU 1450 при физическом MTU 1500.

4.  **Локальность трафика**: Используйте `internalTrafficPolicy: Local` для сервисов, критичных к задержкам, чтобы трафик не покидал узел при наличии локального пода.

5.  **NodeLocal DNSCache**: Установите NodeLocal DNSCache для предотвращения conntrack race conditions при DNS-запросах и снижения нагрузки на CoreDNS. Это обязательно для production-кластеров.

6.  **Мониторинг conntrack**: Установите алерты на использование conntrack > 80% от максимума. Переполнение таблицы приводит к «молчаливым» потерям пакетов.

7.  **Graceful Termination**: Всегда настраивайте `preStop` хук с задержкой 5-10 секунд для предотвращения 502 ошибок при обновлении подов.

8.  **WireGuard для шифрования**: Используйте WireGuard (вместо IPsec) для прозрачного шифрования трафика между узлами. Меньше overhead, проще эксплуатация.

9.  **Conntrack Tuning**: В кластерах >10k подов настройте:
   ```bash
   net.netfilter.nf_conntrack_max = 1000000
   net.netfilter.nf_conntrack_tcp_timeout_established = 7200
   net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
   ```

10. **Избегайте пересечения CIDR**: `serviceCIDR`, `podCIDR` и `nodeNetwork` не должны пересекаться. Это критическая ошибка, приводящая к потере пакетов.

## Дополнительная информация

**См. также:**

- [Обзор сетевой модели Kubernetes](./network_overview.md) — базовые принципы и L2/L3 связность.
- [CNI и kube-proxy: роли](./cni_kube_proxy_roles.md) — детальное сравнение функций сетевых компонентов.
- [Cilium и eBPF](./CNI/cilium.md) — глубокое погружение в современную обработку пакетов.
