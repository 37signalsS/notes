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

### Архитектура eBPF в Cilium

Cilium использует несколько точек подключения (hooks) в сетевом стеке ядра Linux:

1.  **XDP (eXpress Data Path):** Обработка пакетов на уровне драйвера сетевой карты, до их поступления в стек TCP/IP. Используется для защиты от DDoS и высокопроизводительного Ingress.
2.  **TC (Traffic Control):** Гибкая точка для реализации NetworkPolicy и маршрутизации. Инспектирует пакеты на входе и выходе из veth-пары пода.
3.  **SOCKMAP/SOCKHASH:** «Сшивает» сокеты приложения и прокси (Envoy, Ztunnel) внутри ядра, минуя сетевой стек. Это снижает задержки на 15–20% и является ключевым компонентом Ambient Mesh.
4.  **LSM (Linux Security Modules):** Используется Tetragon для блокировки вредоносных действий (например, `execve` в недоверенном поде) на уровне ядра.

**BPF Maps** — структуры данных ядра для обмена информацией между eBPF-программами и пользовательским пространством. В Cilium BPF Maps хранят:
- Состояния соединений (connection tracking)
- Маршруты подов
- Политики безопасности
- Метрики и счетчики

**Механизмы совместимости:**
- **CO-RE (Compile Once – Run Everywhere):** Позволяет запускать одни eBPF-программы на разных версиях ядер без перекомпиляции.
- **BTF (BPF Type Format):** Необходим для CO-RE; обеспечивает переносимость программ между ядрами.

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
- **Native Routing и BGP Control Plane:** Режим `native-routing` исключает оверлейные туннели (VXLAN/Geneve), используя реальные IP-адреса подов и стандартную маршрутизацию ядра. Для анонсирования маршрутов во внешнюю сеть используется BGP Control Plane с CRD `CiliumBGPClusterConfig` (Cilium 1.16+). Подробнее: [Настройка native routing и BGP](#настройка-native-routing-и-bgp-control-plane).
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
- **L7 Load Balancing:** Балансировка на основе путей, заголовков и весов через встроенный Envoy. Практический пример автоматизации весов из CI-пайплайна: **[Canary в Push-модели](../../../../CI-CD/Deployment_Strategies/canary_deployment.md)**.
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

## Предварительные требования

### Аппаратные требования

- **Процессор:** x86_64 (Intel/AMD) или ARM64. Поддержка инструкций BMI/BMI2 желательна для JIT-компиляции eBPF.
- **Сеть:** NIC с драйверами, поддерживающими XDP-режим (для полной функциональности DDoS-защиты и Ingress-ускорения).
- **Память:** Минимум 4 GB RAM на узел; для кластеров >1000 подов рекомендуется 8+ GB (BPF Maps занимают невытесняемую память ядра).

### Программные требования

- **Ядро Linux:**
  - Минимум 5.10 для базового режима (kube-proxy replacement).
  - Минимум 6.1+ для полноценной работы LSM, Ring Buffer и современных хуков.
  - Рекомендуется 6.6+ LTS для production (стабильность BTF и CO-RE).
- **Конфигурация ядра:**
  ```bash
  # Проверка обязательных параметров
  zgrep CONFIG_BPF /boot/config-$(uname -r)
  # → CONFIG_BPF=y
  # → CONFIG_BPF_SYSCALL=y
  # → CONFIG_BPF_JIT=y
  # → CONFIG_DEBUG_INFO_BTF=y (требуется для CO-RE)
  ```
- **Файловая система BPF:**
  ```bash
  # Проверка монтирования bpffs
  mount | grep /sys/fs/bpf
  # → bpffs on /sys/fs/bpf type bpffs (rw,nosuid,nodev,noexec,relatime)

  # При отсутствии монтирования
  sudo mount -t bpf bpf /sys/fs/bpf
  ```
- **Kubernetes:** Версия 1.28+ (рекомендуется 1.30+ для полной поддержки Gateway API и MCS API).
- **Сетевые сервисы:** Отключение конфликтующих служб файервола (`ufw`, `firewalld`) и отключение swap.

### Проверка готовности узлов

```bash
# Версия ядра
uname -r
# → 6.1.0-18-amd64 (минимум 5.10)

# Наличие bpffs
mount | grep bpf

# Доступные хуки eBPF
sudo bpftool feature probe

# Проверка загрузки модулей ядра
lsmod | grep -E 'ip_vs|nf_conntrack'
```

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

### Настройка native routing и BGP Control Plane

#### Теория: overlay vs native routing

В стандартной конфигурации Cilium между узлами организуется оверлейная сеть (VXLAN или Geneve), инкапсулирующая трафик подов в UDP-пакеты узла. Альтернативой является **native routing** (нативная маршрутизация) — режим, при котором поды получают реально маршрутизируемые IP-адреса, а трафик между узлами передается без инкапсуляции, используя стандартную таблицу маршрутизации ядра Linux.

**Преимущества native routing:**
- Отсутствие инкапсуляции: нет накладных расходов (~50 байт на пакет), полный MTU 1500.
- Поды видны из физической сети напрямую по IP-адресу.
- Сохраняется Source IP подов при выходе во внешнюю сеть (без NAT/masquerade).
- Упрощается отладка: `tcpdump` на узлах видит реальные IP подов без распаковки туннелей.

**Ограничения native routing:**
- IP-адреса подов эфемерны: при пересоздании пода IP меняется. Для стабильного внешнего доступа используйте `StatefulSet` + Headless Service с корректной трансляцией DNS наружу.
- Требует BGP-совместимый маршрутизатор или статические маршруты в физической сети.
- Диапазоны Pod CIDR не должны пересекаться с существующими сетями организации.
- Параметр `autoDirectNodeRoutes=true` работает только когда все узлы находятся в одном L2-сегменте (одной подсети). При распределении кластера по нескольким подсетям этот параметр нужно отключить и использовать BGP для всей маршрутизации.

#### Конфигурация Helm

```yaml
# Режим native routing без оверлея
routingMode: native

# Автоматические маршруты между узлами (только для L2-сегмента)
autoDirectNodeRoutes: true

# Включение BGP Control Plane
bgpControlPlane:
  enabled: true

# Отключение masquerade для исходящего трафика (опционально)
bpf:
  masquerade: false
```

При распределении кластера по нескольким подсетям:

```yaml
routingMode: native
autoDirectNodeRoutes: false
bgpControlPlane:
  enabled: true
```

#### Режимы BGP

Для анонсирования маршрутов к Pod CIDR и сервисам внешним маршрутизаторам используется BGP. Cilium поддерживает два режима:

- **eBGP (External BGP):** Разные автономные системы (ASN) для кластера и роутера. Рекомендуется для production — не требует full-mesh между узлами, автоматически масштабируется при добавлении/удалении нод.
- **iBGP (Internal BGP):** Одна ASN для всего кластера. Требует full-mesh сессий между всеми узлами или использования Route Reflector, что усложняет эксплуатацию при росте кластера.

#### CRD для BGP Control Plane (Cilium 1.16+)

Начиная с Cilium 1.16, BGP управляется через декларативные ресурсы:

```yaml
# Переиспользуемый конфиг peered-параметров
apiVersion: cilium.io/v2
kind: CiliumBGPPeerConfig
metadata:
  name: standard-peer
spec:
  transport:
    peerPort: 179
  timers:
    holdTimeSeconds: 90
    keepAliveTimeSeconds: 30
    connectRetryTimeSeconds: 120
  gracefulRestart:
    enabled: true
    restartTimeSeconds: 120
  families:
    - afi: ipv4
      safi: unicast
      advertisements:
        matchLabels:
          advertise: "bgp"
```

```yaml
# Определение анонсируемых префиксов
apiVersion: cilium.io/v2
kind: CiliumBGPAdvertisement
metadata:
  name: pod-cidr-advert
  labels:
    advertise: "bgp"
spec:
  advertisements:
    - advertisementType: "PodCIDR"
```

```yaml
# Кластерная конфигурация BGP
apiVersion: cilium.io/v2
kind: CiliumBGPClusterConfig
metadata:
  name: cilium-bgp
spec:
  nodeSelector:
    matchLabels:
      bgp-speaker: "true"
  bgpInstances:
    - name: "instance-65001"
      localASN: 65001
      peers:
        - name: router-1
          peerASN: 65000
          peerAddress: "192.168.1.1"
          peerConfigRef:
            name: standard-peer
```

Cilium Operator автоматически создает per-node ресурс `CiliumBGPNodeConfig` для каждого узла, соответствующего `nodeSelector`.

#### Устаревший CRD (Cilium <1.16)

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

#### Топологии подключения

1. **Через внешний маршрутизатор (рекомендуется):** Узлы устанавливают eBGP-сессию только с роутером. При добавлении ноды достаточно пометить её label `bgp-speaker=true` — Cilium Operator автоматически создаст `CiliumBGPNodeConfig` и инициализирует сессию.
2. **Full mesh между узлами:** Все узлы устанавливают BGP-сессии друг с другом. Применимо для небольших кластеров (<10 узлов), не требует внешнего роутера.
3. **Статические маршруты:** Если BGP недоступен, маршруты к Pod CIDR можно прописать вручную на роутере. Это решение не масштабируется и требует ручного обновления при изменении топологии.

#### Пример тестового стенда

Конфигурация native routing тестировалась на стенде из пяти узлов Rocky Linux 10 (R1–R5), первые три — Control Plane. В качестве BGP-роутера использовался коммутатор MikroTik с операционной системой RouterOS:

- **Автономная система кластера:** 6501
- **Автономная система роутера (MikroTik):** 6520
- **Физическая сеть узлов:** `192.168.2.0/24` (все узлы в одном L2-сегменте)
- **Pod CIDR:** `10.244.0.0/16`
- **Service CIDR:** `10.96.0.0/12`
- **IP-пул для LoadBalancer-сервисов:** `192.168.2.0/24`

BGP работает по TCP на порту 179; требуется открыть доступ между узлами кластера и роутером.

#### Диагностика

```bash
# Проверка BGP-сессий
cilium bgp peers

# Просмотр per-node конфигурации
kubectl get ciliumbgpnodeconfig

# Статус BGP-инстанса на узле
kubectl describe ciliumbgpnodeconfig <node-name>
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

## Диагностика

### Типичные проблемы и решения

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Pod в статуse ContainerCreating** | BPF Maps исчерпаны или ядро не поддерживает eBPF | `dmesg \| grep -i bpf`; `cilium status --verbose` | Увеличить `bpf-map-dynamic-size-ratio`; проверить `CONFIG_BPF=y` |
| **Hubble не видит трафик** | Hubble отключен или буфер переполнен | `cilium status`; `hubble observe --type drop` | Проверить `hubble.enabled=true`; увеличить `hubble.buffer-max-size` |
| **Сервисы не разрешают имена** | DNS-прокси Cilium не перехватывает запросы | `cilium-dbg bpf ct list global`; логи `cilium-agent` | Проверить `coredns` аннотации; убедиться что `toFQDNs` политика разрешает DNS-egress |
| **Потеря связности после обновления** | Конфликт iptables и eBPF | `iptables-save \| grep -i kube`; `cilium status` | Использовать `kubeProxyReplacement=strict`; перезапустить DS |
| **Высокий CPU на узле** | Слишком много BPF Maps или churn сервисов | `top`/`htop`; `cilium bpf metrics list` | Настроить `bpf-map-dynamic-size-ratio`; уменьшить количество сервисов |
| **L7-политика не применяется** | Трафик идет через HTTPS или SNI mismatch | `hubble observe --verdict dropped`; `tcpdump` | Проверить SNI; для HTTPS требуется инспекция TLS или `matchName` в `toFQDNs` |

### Проверка состояния eBPF

```bash
# Список загруженных программ Cilium
sudo bpftool prog list | grep cilium

# Инспекция BPF Maps
sudo bpftool map list | grep cilium

# Метрики BPF Maps
cilium bpf metrics list

# Проверка connection tracking
cilium bpf ct list global
# → показывает таблицу отслеживания соединений
```

### Валидация установки

```bash
# Общий статус
cilium status
# → результат: KVStore: Ok, Kubernetes: Ok, Cilium: Ok, Hubble: Ok

# Проверка IPAM и маршрутизации
cilium status --verbose

# Просмотр всех Endpoint в кластере
kubectl get ciliumendpoints -A

# Проверка политик
kubectl get ciliumnetworkpolicy -A
```

## Рекомендации и очистка

### Best Practices

1. **Всегда используйте `kubeProxyReplacement=strict`:** Это гарантирует полное удаление kube-proxy и исключает конфликты между iptables и eBPF-программами.
2. **Настройте лимиты BPF Maps заранее:** В кластерах >500 узлов настройте `bpf-map-dynamic-size-ratio` до обновления production.
3. **Используйте WireGuard для шифрования:** Вместо IPsec — меньше overhead, проще эксплуатация.
4. **Включите Hubble в production:** Это первичный источник истины для диагностики сетевых проблем.
5. **Мониторинг:** Интегрируйте `cilium bpf metrics list` и `hubble observe` в ваши панели мониторинга (Prometheus/Grafana).
6. **Избегайте host-local IPAM без Integrated:** При сбое узла блок адресов остается зарезервированным. Используйте CRD/etcd для хранения состояния.

### Очистка среды

```bash
# Удаление политик Cilium
kubectl delete ciliumnetworkpolicy -A --all
kubectl delete ciliumclusterwidenetworkpolicy --all

# Удаление пулов IPAM
kubectl delete ciliumpodippools --all

# Полное удаление Cilium
helm uninstall cilium -n kube-system

# Очистка CRD Cilium (если не используются другие компоненты)
kubectl delete crd ciliumpodippools.cilium.io ciliumendpoints.cilium.io ...

# Очистка namespace
kubectl delete namespace kube-system --ignore-not-found=true
```

## Крайние случаи

1. **Исчерпание BPF Maps:** При росте количества сервисов (>5000) стандартные лимиты ядра могут быть исчерпаны. Настройте `bpf-map-dynamic-size-ratio` и мониторьте `cilium bpf metrics list`.
2. **MTU и фрагментация:** Для VXLAN/Geneve MTU должен быть уменьшен на 50 байт. Несоответствие MTU приводит к труднодиагностируемым проблемам с TLS-соединениями.
3. **Дублирование с kube-proxy:** Если `kubeProxyReplacement` не strict, iptables и eBPF могут конфликтовать. Всегда проверяйте отсутствие `kube-proxy` подов после установки.
4. **IPv6-only режим:** Cilium поддерживает IPv6, но требует полной поддержки IPv6 в инфраструктуре (CNI, BGP, DNS64/NAT64 для внешнего доступа).
5. **Режим `autoDirectNodeRoutes=true`:** Работает только в одном L2-сегменте. При распределении кластера по нескольким подсетям отключите его и используйте BGP.
6. **L7-фильтрация и HTTPS:** Без инспекции TLS Cilium видит только SNI. Для фильтрации по методам/путям требуется либо HTTP, либо `TLS Inspection` с доверенными сертификатами.
7. **Обновление ядра:** При обновлении ядра с BTF на версию без BTF eBPF-программы перестают работать. Всегда проверяйте `CONFIG_DEBUG_INFO_BTF=y` перед обновлением.

---

## См. также

- [Выбор CNI и режимы IPAM](./ipam.md) — подробное сравнение режимов выделения адресов.
- [eBPF в Kubernetes: Глубокое погружение](./ebpf.md) — технология, лежащая в основе Cilium.
- [Официальная документация Cilium](https://docs.cilium.io/) — первоисточник информации.

**[К списку разделов CNI](../cni_kube_proxy_roles.md)**
