## Определения

- **SDN (Software-Defined Networking — Программно-определяемые сети)**: Архитектурный подход, при котором плоскость управления (**Control Plane**) отделяется от плоскости передачи данных (**Data Plane**) и централизуется. Это позволяет управлять сетью как единым программируемым ресурсом через абстракцию ПО.
- **Control Plane (Плоскость управления)**: Логика сети, отвечающая за принятие решений о том, куда должен быть направлен трафик (маршрутизация, политики безопасности). В SDN эта логика вынесена на отдельный контроллер или платформу.
- **Data Plane (Плоскость данных / Forwarding Plane)**: Уровень исполнения, который занимается непосредственной пересылкой пакетов на основе правил, полученных от Control Plane. Реализуется на коммутаторах, маршрутизаторах, vSwitch или SmartNIC.
- **Management Plane**: Интерфейс администрирования (SSH, REST API, GUI). Отвечает за мониторинг, аудит, логирование и начальную настройку Control Plane.
- **Northbound API**: Интерфейс «северного направления», через который прикладной уровень (orquestrators, сервисы безопасности, аналитика) управляет SDN-контроллером. Типичные реализации: REST, gRPC, GraphQL.
- **Southbound API**: Интерфейс «южного направления», через который SDN-контроллер управляет сетевыми устройствами и программирует Data Plane. Наиболее известные примеры: OpenFlow, P4Runtime, gNMI/gNOI, NETCONF/YANG.
- **IBN (Intent-Based Networking — Сети на основе намерений)**: Высшая ступень эволюции SDN, где система автоматически переводит высокоуровневые требования (например, «изолировать трафик бухгалтерии») в конкретные конфигурации и непрерывно проверяет их выполнение (闭环: Intent → Validation → Remediation).

---

## Основные концепции

### Эволюция:的传统 → SDN → IBN

| Поколение | Годы | Control Plane | Data Plane | Управление | Примеры |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Традиционная сеть** | до 2008 | Распределена (каждое устройство自主决策) | Аппаратная (ASIC) | CLI, SNMP | Cisco IOS, Juniper Junos |
| **SDN (начало)** | 2008–2015 | Централизованный контроллер | Аппаратная + виртуальная (OVS) | OpenFlow, REST API | OpenFlow 1.0, NOX, Floodlight |
| **SDN (Cloud)** | 2015–2022 | Оркестраторы (OpenStack Neutron, Kubernetes) | Виртуальная (OVS, eBPF) | NETCONF/YANG, gNMI | OVN, Antrea, Calico |
| **IBN** | 2020+ | Интент-движимый (ABAC, разрешение) | Гибридная (ASIC + SmartNIC) | GraphQL, Policy Engines | Cisco DNA Center, Apstra,edisys |

### Традиционная vs SDN

| Критерий | Традиционная сеть | SDN |
| :--- | :--- | :--- |
| **Control Plane** | Распределена на каждом устройстве | Централизованный контроллер (one source of truth) |
| **Программируемость** | Ограничена CLI/scripting | Полная (REST API, гранularные policy, intent) |
| **Агрегация трафика** | Статичная (VLAN, ACL) | Динамическая (microsegmentation, service chaining) |
| **Масштабируемость** | Линейная (новое устройство → ручная настройка) | Экспоненциальная (автоматическое развертывание через API) |
| **Техническая задолженность** | Высокая (ветки конфигов, ACL-штормы) | Низкая (программное управление, version control) |
| **Стоимость владения** | Низкая начальная, высокая операционная | Высокая начальная (инвестиции в инфраструктуру), низкая операционная |
| **Отказоустойчивость** | Локальная (HSRP/VRRP per device) | Глобальная (controller clustering, intent-based healing) |
| **Visibility** | Точечная (SNMP polls, CLI debug) | Полная (INT, flow analytics, topology maps) |

### Ключевые преимущества SDN

- **Централизация**: Глобальное видение топологии всей сети. Контроллер знает о всех устройствах, потоках и политиках одновременно.
- **Программируемость**: Возможность изменять поведение сети через код без физического доступа к портам. Версионирование конфигураций через Git.
- **Вендоронезависимость**: Использование стандартных протоколов для управления оборудованием разных производителей (OCP, ONF).
- **Автоматизация**: Ochestration-системы (OpenStack Neutron, Kubernetes CNI) управляют сетью через API, без ручного SSH к устройствам.
- **Наблюдаемость (Observability)**: Централизованный сбор метрик (flow statistics, INT, telemetry) позволяет видеть всю сеть в реальном времени.
- **Microsegmentation**: Полосная сегментация на уровне каждой ВМ/контейнера (Zero Trust East-West), недоступная в традиционных сетях.
- **Network Function Virtualization (NFV)**: Вынос сетевых функций (FW, LB, NAT) на виртуальные машины/контейнеры, управляемые SDN-контроллером.

### Уровни архитектуры SDN

```
┌─────────────────────────────────────────────────────────────┐
│                   APPLICATION LAYER                         │
│  (Network Apps: Security, Analytics, Orchestration, FW)     │
│           ↕ Northbound API (REST, gRPC, GraphQL)            │
├─────────────────────────────────────────────────────────────┤
│                     CONTROL LAYER                           │
│  (SDN Controllers: ONOS, OpenDaylight, OVN, Antrea)         │
│     ↕ Southbound API (OpenFlow, P4, gNMI, NETCONF/YANG)    │
├─────────────────────────────────────────────────────────────┤
│                 INFRASTRUCTURE LAYER                        │
│  (Physical Switches, Virtual Switches (OVS), SmartNICs,    │
│   eBPF programs, DPDK-accelerated vSwitch)                  │
└─────────────────────────────────────────────────────────────┘
```

#### Уровень приложений (Application Layer)
- **Сервисы безопасности**: Firewall, IDS/IPS, DDoS-защита, VPN.
- **Балансировка нагрузки (Load Balancing)**: Динамическое распределение трафика по серверам/контейнерам.
- **Аналитика и мониторинг**: Сбор и анализ flow data (NetFlow/IPFIX, INT), построение топологий, аномалий.
- **Оркестрация**: Автоматическое развертывание сетевых сервисов при масштабировании приложений (Kubernetes CNI, OpenStack Neutron).
- **Взаимодействие**: Через **Northbound API** (REST, gRPC, GraphQL) — приложения не знают о физической топологии.

#### Уровень управления (Control Layer)
- **SDN-контроллер**: Принимает решения о маршрутизации, политике безопасности, балансировке. Формирует глобальную модель сети (topology, flows, policies).
- **Рассмотрение ниже**: см. раздел «Контроллеры SDN (2026)».
- **Взаимодействие**: Через **Southbound API** — контроллер программирует Data Plane.

#### Уровень инфраструктуры (Infrastructure Layer)
- **Физические коммутаторы**: Bare-metal на базе чипов Broadcom (Memory/StrataXGS), Mellanox (Spectrum), Barefoot (Tofino).
- **Виртуальные коммутаторы**: OVS (Open vSwitch), VPP (Vector Packet Processing), eBPF/XDP (в ядре Linux).
- **SmartNIC / DPU**: Аппаратное ускорение: перенос OVS, IPsec, VXLAN на сетевую карту (NVIDIA BlueField, Intel IPU).
- **Взаимодействие**: Через **Southbound API** — коммутаторы接收и исполнение команд от контроллера.

### Southbound API: детали

| Протокол | Уровень | Описание | Когда использовать |
| :--- | :--- | :--- | :--- |
| **OpenFlow** | L2-L4 | Стандартный протокол управления таблицами потоков. Работает с match+action. | Для управления vSwitch (OVS) и bare-metal коммутаторами в гетерогенных средах. |
| **P4Runtime** | L2-L4+ | Протокол для управления программируемым Data Plane (ASIC/P4). | Для SmartNIC и white-box коммутаторов с пользовательским pipeline. |
| **gNMI/gNOI** | Configuration | Управление конфигурацией и инвентаризацией устройств. | Для автоматического provisioning и закрытия security vulnerabilities. |
| **NETCONF/YANG** | Configuration | Стандартная модель конфигурации (YANG) и транспорт (NETCONF). | Для работы с的传统 equipment (Cisco, Juniper) без замены ПО. |
| **gRPC/gNMI** | Telemetry | Стриминг телеметрии (streaming telemetry). | Для real-time мониторинга (sub-second intervals). |
| **BGP-LS** | topology | Распространение топологии через BGP (BGP-Link State). | Для интеграции SDN с传统 IP-сетями. |

### Northbound API: детали

| Интерфейс | Формат | Когда использовать | Примеры контроллеров |
| :--- | :--- | :--- | :--- |
| **REST API** | JSON/XML | Универсальный (web, scripts, CI/CD). | ONOS, OpenDaylight, Floodlight |
| **gRPC** | Protobuf | Высокая производительность, type-safety, streaming. | OVN (OVSDB), Antrea (K8s CRD), Cilium (eBPF) |
| **GraphQL** | JSON (query language) | Гибкие запросы (клиент запрашивает только нужные поля). | Apstra, Cisco ACI |
| **YANG/NETCONF** | XML | Интеграция с传统 NMS и OSS. | Cisco NSO, Juniper Junos Space |

### Контроллеры SDN (2026)

| Контроллер | Тип | Южный интерфейс | Особенности | Когда использовать |
| :--- | :--- | :--- | :--- | :--- |
| **ONOS** | Open-source | OpenFlow, gRPC, P4 | HA (cluster),istributed, модульная архитектура, BGP-LS. | Крупные операторы связи, 5G core. |
| **OpenDaylight (ODL)** | Open-source | NETCONF, OpenFlow, gRPC | Модульный (YANG models), интеграция с OpenStack. | Enterprise, NFV, телеком. |
| **OVN** | Open-source | OVSDB, OpenFlow | Автоматизация для KVM/OpenStack, logical switches/routers, ACL, DHCP. | OpenStack, K8s (через OVN-Kubernetes). |
| **Antrea** | Open-source (K8s) | OpenFlow (через OVS) | Kubernetes-native, NetworkPolicy enforcement, service load balancing. | Kubernetes CNI (CNCF). |
| **Cilium** | Open-source (K8s) | eBPF (не OpenFlow) | Ядро eBPF, L7-aware, DNS-aware, high-performance. | Kubernetes CNI (CNCF), cloud-native. |
| **Cisco ACI** | Коммерческий | OpFlex, gRPC | Policy-driven, APIC controller, leaf-spine. | Cisco-ориентированные дата-центры. |
| **Apstra (Juniper)** | Коммерческий | gNMI, NETCONF | Intent-based, intent-based networking (IBN). | Multi-vendor DC fabrics. |
| **Cisco DNA Center** | Коммерческий | NETCONF, gRPC | IBN, assurance, AI-driven analytics. | Cisco enterprise campuses. |

**Важно:** Cilium использует eBPF вместо OpenFlow — это следующий этап эволюции Data Plane, где пакеты обрабатываются в ядре Linux без переключения контекста.

### Современный ландшафт (2025–2026)

#### Дезагрегация сети (White-box и SONiC)

Тенденция разделения аппаратного и программного обеспечения (Disaggregation):
- **White-box коммутаторы**: «Чистое» железо на базе чипов Broadcom, Mellanox (Nvidia), Barefoot. Пример: EDGEcore, Delta Networks, Quanta.
- **Network OS (NOS)**: Открытые операционные системы:
    - **SONiC** (Software for Open Networking in the Cloud): Разработан Microsoft, используется в Azure, Amazon, Google. Поддержка multiple SDK (Broadcom, Mellanox, Barefoot).
    - **DANOS** (Dell): Модульная NOS для white-box.
    - **Stratum** (Open Networking Foundation): Минимальный Open vSwitch для P4-устройств.
- **Преимущества**: Снижение стоимости (в 2-3 раза дешевле branded), отсутствие вендор-локации, гибкость выбора NOS.

#### Эволюция Data Plane: SmartNIC и DPU

Плоскость данных перемещается на хосты для разгрузки CPU:
- **SmartNIC / DPU (Data Processing Unit)**: Сетевые карты с собственными процессорами (Arm, FPGA) или specialized ASIC.
- **Offload**: Перенос обработки OpenFlow, VXLAN, IPsec/TLS с основного CPU на DPU. Это позволяет OVS работать на скоростях 200G+ без потери производительности приложений.
- **Примеры DPU**:
    - **NVIDIA BlueField-3/4**: ARM Cortex-A78AE cores, 400G, hardware offload для OVS, IPsec, VXLAN.
    - **Intel IPU (Infrastructure Processing Unit)**: Based on N3000, two 100G ports, OVS offload.
    - **AMD/Pensando**: DSC (Distributed Services Card) — hardware-accelerated services (NAT, FW, LB).
- **Отличие от SmartNIC**: DPU включает не только сетевую функцию, но и вычислительные ресурсы для управления виртуальными функциями (NFV) и оркестрации.

#### Программируемость и Наблюдаемость

- **P4 (Programming Protocol-independent Packet Processors)**: Позволяет программировать сам конвейер обработки пакетов в ASIC. Вместо фиксированного pipeline (как в OpenFlow) — полная гибкость: определение своих полей, своих стадий обработки.
- **INT (In-band Network Telemetry)**: Технология, позволяющая добавлять данные о состоянии коммутаторов (задержка в очередях, путь пакета) прямо в заголовки транзитных пакетов. Это дает «рентгеновское» зрение всей сети в реальном времени.
- **eBPF**: «Хостовый SDN». Используется в Kubernetes (Cilium) для высокоскоростной фильтрации и балансировки трафика внутри узла. Вместо OpenFlow — programmatic hooks в ядре Linux.

#### Segment Routing (SRv6) и Traffic Engineering

- **SRv6**: Маршрут задается в заголовке IPv6 в виде списка сегментов. Позволяет реализовать Traffic Engineering без RSVP-TE и MPLS, с централизованным управлением через SDN-контроллер.
- **Преимущества**: Упрощение протокольного стека (нет LDP/RSVP), полная интеграция с IPv6, гибкость политик.
- **Подробнее**: [SRv6 (Segment Routing over IPv6)](./srv6.md).

#### Overlay Networks: VXLAN и Geneve

- **VXLAN (Virtual eXtensible Local Area Network)**: Протокол инкапсуляции L2-кадров в UDP-пакеты (RFC 7348). Создает виртуальные L2-сегменты (VNI, 24-битный идентификатор, до 16M сегментов) поверх L3-сети. Основной протокол для overlay сетей в дата-центрах.
- **Geneve (Generic Network Virtualization Encapsulation)**: Современный протокол инкапсуляции (RFC 8926) с поддержкой переменных метаданных (TLV options). Более гибкий для NFV и telemetry, заменяет VXLAN.
- **Overhead**: 50-62 байт на пакет (IPv4 header + UDP + VXLAN/Geneve header). Требует MTU=1450 на подах при underlay MTU 1500.
- **Подробнее**: [VXLAN/Geneve (Overlay Networks)](./vxlan_geneve.md).

#### Proactive vs Reactive в Data Plane

| Модель | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Reactive** | Пакет не найден в таблице → Packet-In на контроллер → контроллер решает → Flow-Mod/_PACKET_OUT. | Dynamic environments, new flows (OpenFlow). |
| **Proactive** | Контроллер устанавливает правила заранее (до появления трафика). | Production networks, critical services, eBPF. |
| **Proactive + reactive** | Базовые правила proactive, динамические правила reactive. | Hybrid SDN (OVN, Cilium). |

**Производственная рекомендация:** В modern SDN (OVN, Cilium) используется **proactive flow installation** для baseline rules + reactive для dynamic adjustments. Чистый reactive (как в early OpenFlow) непригоден для production из-за латентности (1-5 мс на каждый новый поток).

#### eBPF и XDP (современный Data Plane)

- **eBPF**: Программы, загружаемые в ядро Linux, выполняющие packet processing на уровне hooks (XDP, TC). Заменяет OpenFlow для cloud-native networking.
- **XDP (eXpress Data Path)**: Самый ранний hook в сетевом стеке (до sk_buff allocation). Proactive модель: программа загружается один раз и выполняется на каждом пакете.
- **Производительность**: ~24Mpps на ядро (XDP) vs ~1Mpps (iptables) vs ~5Mpps (OVS + kernel).
- **Подробнее**: [eBPF/XDP](./ebpf_xdp.md).

---

## Практические сценарии

### 1. Микросегментация и Zero Trust

Использование SDN для создания «файрвола вокруг каждой ВМ/контейнера». Политики применяются на уровне vSwitch (OVS) или eBPF, блокируя любой неразрешенный трафик внутри дата-центра (East-West).

**Реализация на OVN (OpenStack/Kubernetes):**
```bash
# Создание izoliruyushchey policy в OVN (через neutron CLI или OVN Northbound DB)
# Пример: разрешить доступ к порту 80 только из подсети 10.0.0.0/24
ovn-nbctl acl-add sw0 to-lport 1002 "ip4.src == 10.0.0.0/24 && tcp.dst == 80" allow
ovn-nbctl acl-add sw0 to-lport 1001 "ip4" drop

# Просмотр ACL в OVN
ovn-nbctl acl-list sw0
# → to-lport 1002 (priority 1002): ip4.src == 10.0.0.0/24 && tcp.dst == 80, action=allow
# → to-lport 1001 (priority 1001): ip4, action=drop

# Проверка соответствующих OpenFlow-правил
ovs-ofctl dump-flows br-int | grep "priority=1002"
# → cookie=0x0, table=8, priority=1002,tcp,nw_src=10.0.0.0/24,tp_dst=80 actions=accept
```

**Реализация на Cilium (eBPF, Kubernetes):**
```bash
# NetworkPolicy для разрешения доступа к порту 80 только из特定 namespace
cat <<EOF | kubectl apply -f -
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: api-server
  namespace: production
spec:
  endpointSelector:
    matchLabels:
      app: api-server
  ingress:
  - fromEndpoints:
    - matchLabels:
        "k8s:io.kubernetes.pod.namespace": frontend
    toPorts:
    - ports:
      - port: "80"
        protocol: TCP
EOF

# Проверка сгенерированных eBPF-программ
kubectl -n kube-system exec -it <cilium-pod> -- cilium bpf policy list
# → Endpoint: 123456
# → Ingress: allow from 10.0.1.0/24 to port 80/tcp
```

**Edge case:** При масштабировании (>10k подов) políticas хранятся в eBPF map (Cilium) или OVN NB DB. Для предотвращения DoS на controller — rate-limit API requests и асинхронное обновление политик.

### 2. Service Mesh как расширение SDN

Service Mesh (Istio, Linkerd) можно рассматривать как SDN на уровне L7. Sidecar-прокси выступают в роли Data Plane, а управляющий слой Mesh — в роли Control Plane.

**Istio architecture (SDN-аналогия):**
```
┌─────────────────────────────────────────────────────────────┐
│                   CONTROL PLANE (istiod)                     │
│  - Pilot: 发送配置到 sidecars                               │
│  - Citadel: mTLS сертификаты                                │
│  - Galley: Конфигурация (K8s CRD)                           │
├─────────────────────────────────────────────────────────────┤
│                   DATA PLANE (Envoy sidecars)               │
│  - Каждый под получает sidecar proxy                        │
│  - L7 routing, retry, timeout, circuit breaking             │
│  - mTLS, JWT validation, rate-limiting                      │
└─────────────────────────────────────────────────────────────┘
```

**Практический пример (Istio + OpenFlow):**
```bash
# Установка Istio с включением OpenFlow-aware load balancing
istioctl install --set profile=default \
  --set meshConfig.enableAutoMtls=true \
  --set values.global.proxy.resources.requests.cpu=100m

# Проверка sidecar injection
kubectl get namespace -L istio-injection
# → production   istio-injection=enabled

# Создание VirtualService для route splitting (SDN-стиль)
cat <<EOF | kubectl apply -f -
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: api
spec:
  hosts:
  - api.production.svc.cluster.local
  http:
  - route:
    - destination:
        host: api
        subset: v1
      weight: 90
    - destination:
        host: api
        subset: v2
      weight: 10
EOF
```

**Важно:** Istio работает на L7 (HTTP/gRPC), в то время как OpenFlow/OVN — на L3/L4. Это комплементарные технологии: OpenFlow управляет сетевой топологией, Istio — application traffic management.

### 3. Облачные сети (VPC)

Вся сетевая инфраструктура AWS/GCP/Yandex Cloud — это гигантский SDN. Пользователь создает подсети и правила через API, а контроллер программирует виртуальные коммутаторы на гипервизорах.

**AWS VPC (как SDN):**
- **Data Plane**: Эластичные сетевые интерфейсы (ENI), VPC Peering, Transit Gateway. Каждый хостип Telnet运行在 гипервизорах Nitro.
- **Control Plane**: AWS VPC API (create-subnet, create-security-group) → AWS controllers программируют Nitro cards.
- **Протокол**: AWS использует proprietary protocols (не OpenFlow), но концептуально это SDN.

**Yandex Cloud VPC (пример API):**
```bash
# Создание VPC через Yandex Cloud CLI
yc vpc network create --name prod-network --description "Production VPC"
# → id: enp1234567890abcdef

yc vpc subnet create --name prod-subnet-a \
  --network-id enp1234567890abcdef \
  --zone ru-central1-a \
  --range 10.0.1.0/24
# → id: e9br1234567890abcdef

# Создание security group (аналог firewall rules в SDN)
yc vpc security-group create --name prod-sg \
  --network-id enp1234567890abcdef \
  --direction ingress \
  --protocol TCP \
  --port 443 \
  --source-range 0.0.0.0/0
```

### 4. Деплой OVN для виртуальных сетей

OVN (Open Virtual Network) — компонент OVS, реализующий логические сети (logical switches/routers) для OpenStack/Kubernetes. Автоматически транслирует логические правила в OpenFlow.

**Пример: создание логической сети в OVN (standalone):**
```bash
# Создание логического коммутатора
ovn-nbctl ls-add ls-web

# Создание логических портов
ovn-nbctl lsp-add ls-web web-port1
ovn-nbctl lsp-add ls-web web-port2

# Настройка MAC и IP для порта
ovn-nbctl lsp-set-addresses web-port1 "00:11:22:33:44:55 10.0.1.10"
ovn-nbctl lsp-set-addresses web-port2 "00:11:22:33:44:66 10.0.1.11"

# Создание логического маршрутизатора
ovn-nbctl lr-add lr-core

# Подключение логического маршрутизатора к коммутатору
ovn-nbctl lrp-add lr-core ls-web 00:11:22:33:44:01 10.0.1.1/24

# Добавление маршрута по умолчанию
ovn-nbctl lr-route-add lr-core 0.0.0.0/0 10.0.1.1

# Просмотр топологии
ovn-nbctl show
# → switch <ls-web> (UUID: ...)
# →   port web-port1, addresses: [00:11:22:33:44:55 10.0.1.10]
# →   port web-port2, addresses: [00:11:22:33:44:66 10.0.1.11]
# → router <lr-core> (UUID: ...)
# →   port lr-core-ls-web, mac: 00:11:22:33:44:01, networks: [10.0.1.1/24]

# Проверка соответствующих OpenFlow-правил (на каждом OVS)
ovs-ofctl dump-flows br-int | grep "table=0"
# → cookie=0x0, table=0, priority=100,icmp,reg14=0x1,nw_src=10.0.1.10 ...
```

### 5. Интеграция Proxmox SDN с OVN

Proxmox VE 9.x использует OVN как backend для SDN-зон. Это позволяет управлять логическими сетями через веб-интерфейс Proxmox.

**Создание VXLAN-зоны в Proxmox:**
```bash
# CLI-команды (эквивалент веб-интерфейса)
# Создание VNId (VXLAN Network Identifier)
pvesh create /sdn/zones/vxlan/vxlan1 \
  --vnet prod-vxlan \
  --zone prod-zone \
  --peers "10.0.0.1,10.0.0.2,10.0.0.3"

# Применение SDN-конфигурации (обновляет all nodes)
pvesh create /sdn/controllers/apply

# Проверка созданных интерфейсов
ip -d link show type vxlan
# → vxlan1: <BROADCAST,MULTICAST,UP,LOWER_UP> ...
#     vxlan id 100 local 10.0.0.1 dstport 4789 ...
```

### 6. Отладка Southbound API

**Проверка состояния OpenFlow-канала:**
```bash
# Состояние OVS и его контроллера
ovs-vsctl show
# → Bridge "br-int"
# →     Controller "br-int"
# →         target: "ssl:10.0.0.100:6653"
# →         is_connected: true
# →         role: master

# Просмотр статистики OpenFlow
ovs-ofctl dump-aggregate br-int
# → Flow count: 12345
# → Packet count: 9876543
# → Byte count: 12345678901

# Проверка OFPMP_TABLE (для поиска table overflow)
ovs-ofctl dump-tables br-int
# → table=0: active=1000 lookups=9876543 matched=98765 overflow=0
# → table=1: active=500 lookups=1234567 matched=12345 overflow=0

# Проверка OFPMP_PORT (для поиска errors)
ovs-ofctl dump-ports br-int
# → port 1: rx pkts=12345678 bytes=18517500000 tx pkts=12000000 bytes=18000000000 ...
# →        rx errors=0 tx errors=0
```

---

## Ограничения и угрозы

### Технические ограничения

1.  **Single Point of Failure (SPOF)**: Если SDN-контроллер недоступен, коммутаторы продолжают работать с текущими правилами, но новые политики не применяются. Решение: Controller clustering (ONOS, ODL), HA через Role Request.
2.  **Пропускная способность Southbound API**: Контроллер должен обрабатывать Packet-In от всех коммутаторов. При большом количестве device (>1000) возникает bottleneck. Решение: иерархические контроллеры, hardware offload (SmartNIC).
3.  **Консистентность распределенной state**: В cluster из multiple controllers нужно обеспечить eventually consistent view topology. Решение: Raft/Paxos consensus (ONOS), но с задержкой синхронизации.
4.  **Scale**: Управление millions of flows через один контроллер нереально. Решение: distributed controllers, proactive flow installation, hierarchical SDN.
5.  **Legacy equipment**: Традиционные коммутаторы поддерживают только NETCONF/YANG (не OpenFlow). Решение: гибридный подход (NETCONF для legacy, OpenFlow/P4 для modern).

### Угрозы безопасности

| Угроза | Описание | Митигация |
| :--- | :--- | :--- |
| **DoS on Controller** | Перегрузка Packet-In запросами от compromised hosts | Rate-limiting на коммутаторах, Rate-limiting на Packet-In. |
| **Controller Impersonation** | Злоумышленник подключается как «второй контроллер» | TLS с mutual authentication, certificate pinning. |
| **Man-in-the-Middle on Southbound** | Перехват/изменение OpenFlow команд | TLS (ssl: на OVS), IPsec для gNMI. |
| **Flow Table Poisoning** | Некорректные правила блокируют легитимный трафик | ACL на контроллере, validation rules, Flow-Mod rate-limiting. |
| **Lateral Movement** | Использование SDN для перемещения между сетевыми сегментами | Microsegmentation (Zero Trust), Intent-based policies. |
| **Controller Logic Bugs** | Ошибка в controller code может отключить всю сеть | Canary deployments, staged rollouts, A/B testing policies. |

### Edge cases

- **Pipeline loops**: В OpenFlow таблицы могут образовывать циклы (goto-table A → goto-table B → goto-table A). Это запрещено спецификацией (таблицы обрабатываются только в возрастающем порядке), но может возникнуть при неправильной конфигурации OVN. Проверка: `ovn-trace` + `ofproto/trace`.
- **MTU mismatch**: VXLAN/Geneve overlay добавляют заголовки (50-62 байт), уменьшающие MTU. Если underlying сеть не поддерживает jumbo frames (>1500), возникает fragmentation. Решение: MTU=1450 для подов, PMTUD.
- **ARP/ND suppression в overlay**: В больших VXLAN сетях broadcast storm от ARP может исчерпать ресурсы VTEP. Решение: ARP suppression (OVN, Antrea), Distributed ARP via BGP EVPN.
- **Controller split-brain**: В cluster из 3+ controllers, если network partition разделяет cluster, могут возникнуть два MASTER-контроллера. Решение: fencing (power off для isolated partitions), STONITH.

---

## Типичные ошибки и troubleshooting

| Проблема | Симптомы | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Controller unreachable** | `ovs-vsctl get controller br-int is_connected=false` | `tcpdump -i any port 6653`; `nc -zv <controller-ip> 6653` | Проверить firewall (6653/tcp), IP контроллера, TLS certificates. |
| **Flow table overflow** | `ovs-ofctl dump-tables` → `overflow=N` (N>0) | `ovs-ofctl dump-flows br-int \| wc -l` (подсчет правил) | Увеличить idle-timeout, агрессивное удаление старых правил, hardware offload. |
| **Packet-In storm** | CPU на контроллере 100%, increased latency | `ovs-ofctl dump-flows br-int \| grep "controller"` | Добавить table-miss entry с `actions=drop` или `actions=NORMAL`. |
| **MTU fragmentation** | TCP retransmits, slow performance | `ping -M do -s 1472 <remote-ip>` (проверка MTU) | Set MTU=1450 на подах, jumbo frames в underlying network. |
| **OVSDB disconnect** | `ovs-vsctl show` → `ovsdb-server not connected` | `ovs-appctl vlog/set db:dbg`; `systemctl status ovsdb-server` | Проверить OVSDB socket (`/var/run/openvswitch/db.sock`), restart OVSDB. |
| **OVN NB DB sync** | `ovn-nbctl show` shows different data on different nodes | `ovn-nbctl --db=northbound,nb1,nb2,nb3 show` | Ensure all OVN NB DB servers are in same Raft cluster (`ovn-nbctl dbcluster show`). |

---

## Дополнительная информация

**Связанные темы:**
- **[OpenFlow](./openflow.md)** — глубокое погружение в базовый протокол управления.
- **[NetFlow/IPFIX](./netflow.md)** — сбор статистики и телеметрии (Data Plane monitoring).
- **[eBPF/XDP](./ebpf_xdp.md)** — современный Data Plane на базе eBPF.
- **[Kubernetes CNI](./kubernetes_cni.md)** — сравнение CNI-плагинов (Calico, Cilium, Antrea, Flannel).
- **[VXLAN/Geneve (Overlay Networks)](./vxlan_geneve.md)** —.overlay инкапсуляция.
- **[BGP EVPN](./bgp_evpn.md)** — control-plane learning для VXLAN fabrics.
- **[SRv6 (Segment Routing)](./srv6.md)** — Traffic Engineering без MPLS.
- **[SD-WAN](./sd_wan.md)** — software-defined wide area networking.
- **[Network Automation](./network_automation.md)** — Ansible/Nornir/Terraform для SDN.
- **[VPP (Vector Packet Processing)](./vpp.md)** — high-perf Userspace packet processing.
- **[Multi-cluster Networking](./multi_cluster_networking.md)** — Cilium Cluster Mesh, Istio multi-cluster.
- **[Network Verification](./network_verification.md)** — Batfish, IPFabric, NetBox.
- **[Containerlab](./containerlab.md)** — lab environment для SDN testing.
- **[Open vSwitch (OVS)](../../ServicesAndTools/open_vswitch.md)** — программная реализация SDN-коммутатора и OVN.
- **[DPDK (Data Plane Development Kit)](../dpdk/dpdk_overview.md)** — ускорение обработки пакетов в Userspace.
- **[Proxmox SDN](../../Proxmox/proxmox_networking.md)** — практическое применение SDN в виртуализации (VXLAN zones, OVN).
- **[Zero Trust](../Concepts/zero_trust_overview.md)** — концепция, реализуемая через SDN microsegmentation.
- **[Cloud Networking](../Concepts/cloud_networking.md)** — виртуализированные сети в IaaS/PaaS.
