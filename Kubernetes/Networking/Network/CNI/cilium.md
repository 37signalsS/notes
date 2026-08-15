# Cilium: Высокопроизводительный CNI на базе eBPF

---
**Надёжность:** 10 (SSoT + Проектный контекст 2026)
**Свежесть:** Актуально на август 2026 (Cilium v1.20.0)
---

## Определения

**Cilium** — это современный плагин интерфейса сетевой связности контейнеров (CNI), обеспечивающий сетевое взаимодействие, безопасность и наблюдаемость рабочих нагрузок. В основе Cilium лежит технология **eBPF** (Extended Berkeley Packet Filter), которая позволяет внедрять логику обработки пакетов напрямую в ядро Linux без изменения исходного кода ядра или приложений.

**kube-proxy-replacement** — режим работы Cilium, полностью заменяющий стандартный `kube-proxy`. В этом режиме балансировка трафика сервисов (ClusterIP, NodePort, LoadBalancer) выполняется через eBPF, что исключает накладные расходы на `iptables` и `conntrack`.

**Tetragon** — инструмент в экосистеме Cilium для обеспечения безопасности среды выполнения (Runtime Security) и глубокой наблюдаемости на базе eBPF. Позволяет отслеживать системные вызовы, доступ к файлам и выполнение процессов с минимальными накладными расходами.

**Cilium Identity** — уникальный числовой идентификатор, присваиваемый группе подов с идентичным набором меток (labels). Используется для реализации политик безопасности на основе логических ролей, а не эфемерных IP-адресов.

### Ключевые отличия и преимущества eBPF
В то время как другие решения CNI используют стандартный сетевой стек Linux `iptables` и сетевой экран, Cilium опирается на eBPF — высокоэффективную и программируемую структуру внутри ядра Linux. eBPF позволяет выполнять динамическую обработку пакетов без модификации ядра, что значительно повышает производительность сети для высоконагруженных систем.

Основные возможности Cilium:
*   **Безопасность с поддержкой API (L7):** Возможность определять политики безопасности на уровнях HTTP и API. Это обеспечивает детальный контроль над связью между микросервисами на основе семантики запросов.
*   **Встроенная балансировка нагрузки:** Распределение трафика между несколькими экземплярами службы, что повышает доступность.
*   **Прозрачное шифрование:** Автоматическое шифрование трафика между подами для обеспечения конфиденциальности.
*   **Видимость L7 (OSI):** Распределенная видимость на прикладном уровне, предоставляющая информацию о поведении микросервисов во всем кластере.
*   **Интеграция с Service Mesh:** Полная интеграция с Istio, расширяющая возможности наблюдаемости и контроля.
*   **Динамический сетевой граф:** Визуальное представление отношений и моделей связи между микросервисами в реальном времени.
*   **Контекстно-зависимая безопасность:** Определение политик на основе атрибутов сетевого и транспортного уровней.

## Основные концепции

### Архитектура

Cilium реализует распределенную архитектуру, состоящую из следующих компонентов:

- **Cilium Agent (DaemonSet):** Работает на каждом узле.
    - Управляет eBPF-программами и их загрузкой в ядро.
    - Отвечает за выделение IP-адресов (IPAM).
    - Реализует сетевые политики и балансировку.
- **Cilium Operator (Deployment):** Выполняет общекластерные задачи.
    - Распределяет пулы IP-адресов между узлами.
    - Очищает устаревшие ресурсы (CiliumIdentity, CiliumEndpoints).
    - Синхронизирует состояние между API Kubernetes и внутренними структурами Cilium.
- **Cilium Envoy:** Прокси-сервер (интегрирован или запущен как отдельный контейнер) для обработки трафика уровней L3-L7. Используется для инспекции HTTP/gRPC и реализации Service Mesh.
- **Ztunnel (Ambient Mode):** Легковесный прокси на каждом узле (появился в версии 1.17+), обеспечивающий прозрачный mTLS (Mutual TLS) и L4-авторизацию без использования sidecar-контейнеров.

### Ресурсы Custom Resource Definitions (CRD)

Cilium расширяет стандартный API Kubernetes для управления специфичными функциями:

- **CiliumEndpoint:** Отражает состояние сети конкретного пода (IP, MAC, Identity).
- **CiliumIdentity:** Уникальный числовой идентификатор группы подов с одинаковыми метками.
- **CiliumNode:** Данные об узле, включая подсети IPAM и ключи шифрования.
- **CiliumNetworkPolicy:** Расширенная версия NetworkPolicy с поддержкой L7 (HTTP, Kafka, DNS), FQDN-фильтрации и сущностей (Entities).
- **CiliumClusterwideNetworkPolicy:** Политики, применяемые ко всему кластеру (без привязки к Namespace).

### Сетевые политики: Стандартные vs Расширенные

Cilium обеспечивает полную поддержку:
1.  **Стандартные NetworkPolicy Kubernetes:** Работают на уровнях L3/L4 (IP/порты, Label Selectors). Если секция `ingress` или `egress` пуста, по умолчанию применяется **Default Deny** для соответствующего направления.
2.  **CiliumNetworkPolicy (CNP):** Собственные CRD Cilium, расширяющие возможности до L7, фильтрации по именам (FQDN) и логическим сущностям кластера.

### Безопасность на основе идентификаторов (Security Identity)

В отличие от классических межсетевых экранов, использующих IP-адреса, Cilium использует метки (Labels).
- **Принцип:** Каждому набору меток присваивается уникальный ID.
- **Преимущество:** При пересоздании пода его IP может измениться, но если метки остались прежними, ID не меняется. Правила в eBPF проверяют именно ID, что работает значительно быстрее, чем проверка списков IP.

### Наблюдаемость (Hubble и Timescape)

**Hubble** — уровень наблюдения над Cilium, предоставляющий глубокую видимость трафика.

- **Hubble Relay:** Агрегирует данные со всех агентов кластера.
- **Hubble UI:** Графическая карта зависимостей сервисов в реальном времени.
- **Hubble Timescape (1.18+):** Платформа для хранения исторических данных о потоках (Flows), позволяющая проводить аудит безопасности и анализ инцидентов за прошедшие периоды.

### Расширенные сетевые возможности

- **ClusterMesh:** Объединение нескольких кластеров Kubernetes в единую плоскую сеть. Позволяет сервисам обращаться друг к другу по именам (Global Services) и обеспечивать отказоустойчивость. Начиная с v1.20 поддерживается стабильный MCS API.
- **Шифрование трафика:** Поддержка прозрачного шифрования через **WireGuard** (рекомендуется) или **IPsec**.
    - **WireGuard:** Использует UDP-порт `51871`. Требует ядро Linux 5.6+ или модуль `wireguard`.
    - **Область действия:** Шифруется трафик между узлами. Внутри одного узла (Pod-to-Pod на той же ноде) трафик по умолчанию **не шифруется**.
    - **Node-to-Node Encryption:** Дополнительный режим (`encryption.nodeEncryption=true`), позволяющий шифровать системный трафик хоста (kubelet, метрики).
    - **Deadlock Prevention:** По умолчанию шифрование отключено для трафика к Control Plane узлам, чтобы избежать блокировки при обновлении ключей через API-сервер.
- **BGP Control Plane:** Современная реализация BGP (заменяет старый BGP mode), позволяющая гибко анонсировать LoadBalancer IP и Pod CIDR внешним маршрутизаторам через `CiliumBGPPeeringPolicy`.
- **XDP Acceleration:** Возможность обработки пакетов на уровне драйвера сетевой карты (eXpress Data Path), что обеспечивает максимальную защиту от DDoS и минимальную задержку для NodePort-сервисов.
- **Load Balancer (L2 & BGP):** Нативная поддержка сервисов типа `LoadBalancer`, заменяющая сторонние решения (например, MetalLB).
    - **L2 Mode:** Использует ARP/NDP-анонсы. IP-адрес приземляется на одну из нод (выбор лидера через Kubernetes Lease).
- **Egress Gateway:** Маршрутизация исходящего трафика подов через фиксированные IP-адреса узлов (шлюзов) для интеграции с внешними корпоративными файрволами.
- **Bandwidth Manager:** Управление полосой пропускания и предотвращение эффекта "шумного соседа" через очереди ядра (EDT - Earliest Departure Time).

### Сетевая политика: Сущности (Entities)

Cilium позволяет определять правила доступа не только для подов, но и для логических сущностей кластера через `toEntities` или `fromEntities`.

**Основные сущности:**
- **host:** Сам узел, на котором запущен под.
- **remote-node:** Любой другой узел в кластере.
- **cluster:** Все поды внутри кластера.
- **world:** Любой трафик вне кластера (интернет).
- **health:** Трафик проверок состояния Cilium (health checks).

Пример разрешения доступа к локальному хосту:
```yaml
egress:
- toEntities:
  - host
```

### Cilium Service Mesh и Gateway API

Cilium поддерживает стандарт **Gateway API** (версия **1.6.1** в Cilium 1.20+) и может работать в режиме Service Mesh без sidecar-контейнеров:
- **L7 Load Balancing:** Балансировка на основе путей, заголовков и весов через встроенный Envoy.
- **L4 Acceleration (TCP/UDP):** В версии 1.20+ поддержка стабильного Gateway API v1.6 позволяет эффективно маршрутизировать TCP и UDP трафик через eBPF, минуя накладные расходы пользовательского пространства.
- **Включение:** Требует установки Gateway API CRDs и активации параметра `gatewayAPI.enabled=true` в Helm-чарте.
- **Mutual Auth (mTLS):** Автоматическое шифрование и проверка подлинности между подами на уровне ядра (через Ztunnel).
- **Прозрачный Ingress:** Замена стандартных Ingress-контроллеров высокопроизводительным решением на eBPF.

---

## Сравнение механизмов балансировки

| Механизм | Технология | Масштабируемость | Скорость обработки |
|----------|------------|------------------|--------------------|
| **IP tables** | Цепочки правил (линейно) | O(n) - падает при росте | Низкая (высокий CPU) |
| **IPVS** | Хэш-таблицы | O(1) | Средняя |
| **Cilium eBPF** | BPF Maps (прямой путь) | O(1) | Максимальная |

---

## Преимущества и недостатки

### Преимущества
- **Производительность:** Прямое управление пакетами в ядре минимизирует задержки.
- **Масштабируемость:** Эффективная работа в кластерах с тысячами узлов и десятками тысяч сервисов.
- **Безопасность:** Инспекция трафика до L7 и фильтрация по DNS-именам.
- **Экосистема:** Единое решение для CNI, Service Mesh, Ingress, LoadBalancer (L2/BGP) и шифрования.

### Недостатки
- **Требования к ядру:** Для полной функциональности (kube-proxy replacement, WireGuard) требуется ядро 5.10+ (рекомендуется 6.x для современных функций).
- **Сложность:** Глубокая отладка eBPF требует специфических навыков и инструментов (`cilium monitor`, `bpftool`).
- **Ресурсы:** BPF-карты потребляют фиксированный объем памяти в ядре.

---

## Практические сценарии

### Подготовка узлов

Для корректной работы Cilium 1.19+ на современных дистрибутивах (Ubuntu 22.04/24.04, RHEL 9):

1. **Отключение несовместимых служб:**
   ```bash
   sudo swapoff -a
   sudo systemctl stop ufw  # или firewalld
   ```

2. **Проверка версии ядра:**
   ```bash
   uname -r
   # → результат: 5.15.0-101-generic (минимум 5.10 для замены kube-proxy)
   ```

3. **Монтирование BPF FS (обычно делается автоматически):**
   ```bash
   sudo mount | grep /sys/fs/bpf
   # → результат: bpffs on /sys/fs/bpf type bpffs (rw,nosuid,nodev,noexec,relatime)
   ```

### Установка (Helm)

Рекомендуемый способ установки для production-сред — Helm.

```bash
helm upgrade --install cilium cilium/cilium \
  --namespace kube-system \
  --version 1.20.0 \
  --set kubeProxyReplacement=strict \
  --set k8sServiceHost=10.0.0.10 \
  --set k8sServicePort=6443 \
  --set l2announcements.enabled=true \
  --set externalIPs.enabled=true \
  --set gatewayAPI.enabled=true \
  --set bpf.masquerade=true
```

**ВАЖНО:** После обновления конфигурации через Helm необходимо выполнить перезапуск Cilium Agent для применения изменений:
```bash
kubectl rollout restart ds cilium -n kube-system
```

### Настройка BGP Control Plane

Для анонсирования маршрутов внешним устройствам используется `CiliumBGPPeeringPolicy`:

```yaml
apiVersion: "cilium.io/v2alpha1"
kind: CiliumBGPPeeringPolicy
metadata:
  name: "bgp-policy"
spec:
  nodeSelector:
    matchLabels:
      bgp-peering: "true"
  virtualRouters:
  - localASN: 64512
    exportPodCIDR: true
    neighbors:
    - peerAddress: "192.168.1.1/32"
      peerASN: 64512
```

### Настройка Load Balancer (L2 Mode)

Для работы сервисов типа `LoadBalancer` в L2-режиме необходимо создать два ресурса:

1. **Пул IP-адресов (`CiliumLoadBalancerIPPool`):**
   ```yaml
   apiVersion: "cilium.io/v2alpha1"
   kind: CiliumLoadBalancerIPPool
   metadata:
     name: "l2-pool"
   spec:
     blocks:
     - start: "192.168.1.180"
       stop: "192.168.1.190"
   ```

2. **Политика анонсирования (`CiliumL2AnnouncementPolicy`):**
   ```yaml
   apiVersion: "cilium.io/v2alpha1"
   kind: CiliumL2AnnouncementPolicy
   metadata:
     name: "l2-policy"
   spec:
     interfaces:
     - ^eth[0-9]+
     externalIPs: true
     loadBalancerIPs: true
   ```

**Механизм выбора лидера:** Cilium использует объект `Lease` (Kind: `Lease` в `kube-system`) для определения узла, который будет отвечать на ARP-запросы для конкретного IP. По умолчанию интервал проверки (`leaseDuration`) составляет 15 секунд.

### Настройка Gateway API

1. **Установка CRD (Gateway API):**
   ```bash
   kubectl apply -f https://raw.githubusercontent.com/kubernetes-sigs/gateway-api/v1.1.0/config/crd/standard/gwapi-std-crds.yaml
   ```

2. **Gateway Class:**
   ```yaml
   apiVersion: gateway.networking.k8s.io/v1
   kind: GatewayClass
   metadata:
     name: cilium
   spec:
     controllerName: io.cilium/gateway-controller
   ```

3. **HTTP Route (Пример маршрутизации по хосту):**
   ```yaml
   apiVersion: gateway.networking.k8s.io/v1
   kind: HTTPRoute
   metadata:
     name: my-route
   spec:
     parentRefs:
     - name: my-gateway
     hostnames:
     - "test1.example.com"
     rules:
     - matches:
       - path:
           type: PathPrefix
           value: /
       backendRefs:
       - name: my-service
         port: 80
   ```

### Установка (Cilium CLI)

Самый простой способ базовой установки — использование официальной утилиты `cilium`:

```bash
# Установка Cilium с заменой kube-proxy и включенным Hubble
cilium install \
  --version 1.20.0 \
  --set kubeProxyReplacement=strict \
  --set k8sServiceHost=10.0.0.10 \
  --set k8sServicePort=6443 \
  --set hubble.enabled=true \
  --set hubble.ui.enabled=true
```

### Безопасность среды выполнения (Tetragon)

Tetragon позволяет отслеживать события безопасности на уровне ядра. Пример политики для отслеживания записи в чувствительные файлы:

```yaml
apiVersion: cilium.io/v1alpha1
kind: TracingPolicy
metadata:
  name: "monitor-etc-passwd"
spec:
  kprobes:
  - call: "vfs_write"
    syscall: false
    args:
    - index: 0
      type: "file"
    selectors:
    - matchPIDs:
      - operator: NotIn
        values:
        - 1
      matchArgs:
      - index: 0
        operator: "Prefix"
        values:
        - "/etc/passwd"
```

### Настройка шифрования (WireGuard)

Включение прозрачного шифрования для всего трафика между узлами:

```bash
cilium encryption enable --type wireguard
```

После этого проверьте статус шифрования:
```bash
cilium status | grep Encryption
# → результат: Encryption: WireGuard [Node: 10.0.0.1, Key: 1]
```

### Сетевая политика с FQDN

Использование IP-адресов для внешних ресурсов (например, GitHub или Google API) ненадежно, так как они часто меняются. Cilium позволяет создавать политики на основе полных доменных имен (**FQDN**).

Пример политики, разрешающей доступ только к `github.com` и требуемым DNS-запросам:

```yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: "allow-github-fqdn"
spec:
  endpointSelector:
    matchLabels:
      component: github
  egress:
  - toFQDNs:
    - matchPattern: "github.com"
  # Разрешение DNS-запросов (необходимо для работы FQDN)
  - toEndpoints:
    - matchLabels:
        "k8s:io.kubernetes.pod.namespace": kube-system
        "k8s:k8s-app": kube-dns
    toPorts:
    - ports:
      - port: "53"
        protocol: ANY
      rules:
        dns:
        - matchPattern: "*"
```

**Технические нюансы:**
*   **DNS Proxy:** Cilium перехватывает DNS-запросы и динамически обновляет список разрешенных IP-адресов для указанных FQDN.
*   **Обязательный Egress для DNS:** При использовании FQDN-политик НЕОБХОДИМО явно разрешить исходящий трафик к DNS-серверам (обычно `kube-dns` в `kube-system` на порт 53). Без этого под не сможет разрешить имя в IP, и политика заблокирует трафик.
*   **matchPattern:** Позволяет использовать подстановочные знаки (например, `*.github.com`), что упрощает управление правилами для сервисов с множеством поддоменов.

### Сетевая политика L7 (HTTP)

Cilium позволяет ограничивать трафик на прикладном уровне (Layer 7), анализируя HTTP-методы и пути. Это обеспечивает гранулярный контроль доступа между микросервисами.

#### Ограничение TLS/HTTPS
**Важно:** При использовании протокола HTTPS трафик зашифрован. Это означает, что Cilium (без настройки инспекции TLS или терминирования) видит только хост (через SNI), но не может анализировать HTTP-заголовки, методы (GET/POST) или пути (`/test`). L7-фильтрация по методам и путям эффективна только для незашифрованного HTTP-трафика или при наличии расширенной конфигурации проксирования.

#### Пример: Разрешение только POST-запросов на конкретный путь

Задача: разрешить входящие соединения только для POST-запросов по пути `/test`.

```yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: "test-http-post"
  namespace: cilium-test
spec:
  endpointSelector:
    matchLabels:
      app.kubernetes.io/name: http-server
  ingress:
  - fromEndpoints:
    - matchLabels:
        "k8s:io.kubernetes.pod.namespace": cilium-test
    toPorts:
    - ports:
      - port: "8080"
        protocol: TCP
      rules:
        http:
        - method: "POST"
          path: "/test"
```

#### Полный сценарий тестирования L7-правил

Для проверки политики можно развернуть тестовый HTTP-сервер и клиент:

1.  **Сервер (Echo):**
    ```yaml
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: test-http-server
      namespace: cilium-test
    spec:
      replicas: 1
      selector:
        matchLabels:
          app.kubernetes.io/name: http-server
      template:
        metadata:
          labels:
            app.kubernetes.io/name: http-server
        spec:
          containers:
          - name: http
            image: mendhak/http-https-echo
            ports:
            - containerPort: 8080
    ```

2.  **Клиент (Curl loop):**
    ```bash
    kubectl run test-http-post -n cilium-test --image=curlimages/curl -- \
      /bin/sh -c "while true; do curl --fail -X POST http://test-http-server:8080/test -I --connect-timeout 5; sleep 1; done"
    ```

В результате применения политики, клиент сможет успешно выполнять только POST-запросы на `/test`. Любые другие методы (GET, PUT) или пути будут блокироваться прокси-уровнем Cilium (Envoy), возвращая ошибку доступа (обычно 403 Forbidden).

---

## Дополнительная информация

### Проверка состояния

```bash
# Общий статус
cilium status
# → результат: KVStore: Ok, Kubernetes: Ok, Cilium: Ok, Hubble: Ok

# Проверка IPAM и маршрутизации
cilium status --verbose

# Просмотр всех Endpoint в кластере
kubectl get ciliumendpoints -A
```

### Работа с Hubble CLI

Hubble позволяет отслеживать вердикт (verdict) для каждого пакета: `forwarded`, `dropped` или `denied` (блокировка политикой).

```bash
# Наблюдение за отброшенными пакетами в реальном времени
hubble observe --type drop --follow

# Фильтрация по конкретному поду и неймспейсу
hubble observe --pod my-app-pod -n default --follow

# Поиск блокировок политиками (Policy Denied)
hubble observe --verdict dropped --follow

# Просмотр последних 5 записей для конкретного IP
hubble observe --last 5 --ip 10.0.1.5
```

**Отладка шифрования:**
Для проверки статуса WireGuard на конкретном агенте:
```bash
kubectl -n kube-system exec -it ds/cilium -- cilium-dbg encrypt status
# → результат: Encryption: WireGuard, Interface: cilium_wg0, Peers: 4
```

### Тюнинг производительности и лимиты

1. **BPF Map Limits:** В крупных кластерах (>1000 сервисов) стандартных лимитов BPF-карт может быть недостаточно. Настройка `bpf-map-dynamic-size-ratio` позволяет Cilium автоматически масштабировать карты в зависимости от RAM узла.
2. **MTU и фрагментация:** Для VXLAN MTU должен быть на 50 байт меньше физического (1450 при стандартном 1500). Для Geneve — также 50 байт. Несоответствие MTU приводит к труднодиагностируемым проблемам с установкой TLS-соединений.
3. **Direct Routing:** Если инфраструктура поддерживает BGP, использование `native-routing` вместо `overlay` значительно снижает нагрузку на CPU (до 15-20% на пакет) за счет отсутствия инкапсуляции.

---

## См. также

- [Выбор CNI и режимы IPAM](./ipam.md) — подробное сравнение режимов выделения адресов.
- [eBPF в Kubernetes: Глубокое погружение](./ebpf.md) — технология, лежащая в основе Cilium.
- [Официальная документация Cilium](https://docs.cilium.io/) — первоисточник информации.

**[К списку разделов CNI](../cni_kube_proxy_roles.md)**
