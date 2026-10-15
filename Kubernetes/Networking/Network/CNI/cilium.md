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
    - **L2 Mode:** Использует ARP/NDP-анонсы (NDP — начиная с Cilium 1.19). IP-адрес приземляется на одну из нод (выбор лидера через Kubernetes Lease). Ответ на ARP формируется eBPF-программой в TC-hook, минуя userspace. Подробнее: [Настройка Load Balancer (L2 Mode)](#настройка-load-balancer-l2-mode).
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

#### Путь пакета в native routing

При использовании native routing пакеты между подами на разных узлах проходят через стандартную таблицу маршрутизации ядра Linux без инкапсуляции:

1. Под на узле R1 отправляет пакет поду на узле R3. BPF Cilium на R1 видит, что Destination IP пода не принадлежит локальной подсети пода.
2. Пакет передаётся в стек Linux для маршрутизации. Согласно таблице маршрутизации, для достижения Pod CIDR узла R3 используется next-hop — IP-адрес узла R3.
3. Пакет arrives на узел R3. Маршрутизация ядра определяет, что пакет предназначен локальному узлу (под belongs to R3).
4. BPF Cilium на R3 доставляет пакет непосредственно в целевой под.

При таком подходе отсутствуют NAT и инкапсуляция, сохраняется нормальный MTU, а сетевые инструменты (tcpdump, DLP-системы) видят реальные IP-адреса подов без необходимости распаковки туннелей.

При выходе пакета из кластера (egress) поведение зависит от настроек SNAT/masquerade. Если `ipv4-native-routing-cidr` включает подсеть назначения, пакет уходит с реального IP пода; в противном случае применяется masquerade (SNAT на IP узла).

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

**Управление SNAT через ConfigMap:** При использовании native routing важно корректно настроить параметры маскарадинга в ConfigMap `cilium-config`. Параметр `ipv4-masquerade` (по умолчанию `true`) включает SNAT для исходящего трафика. Параметр `ipv4-native-routing-cidr` позволяет указать CIDR-диапазоны, для которых SNAT не применяется — поды сохраняют свои реальные IP-адреса при выходе в эти сети. Если внутренняя сеть организации не указана в `ipv4-native-routing-cidr`, пакеты из подов, направленные во внутреннюю сеть, будут натиться на IP узла, что может сломать работу корпоративных систем (DLP, фаерволы, мониторинг). Пример конфигурации:

```yaml
# В ConfigMap cilium-config
ipv4-masquerade: "true"
ipv4-native-routing-cidr: "10.244.0.0/16,192.168.2.0/24"
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

#### Анонсирование IP-адресов сервисов (LoadBalancer)

Помимо маршрутов к Pod CIDR, Cilium может анонсировать IP-адреса сервисов типа `LoadBalancer`. Для этого используется тот же ресурс `CiliumBGPAdvertisement`, но с типом анонса `Service` и селектором, указывающим, какие сервисы нужно анонсировать:

```yaml
apiVersion: cilium.io/v2
kind: CiliumBGPAdvertisement
metadata:
  name: service-ip-advert
  labels:
    advertise: "bgp"
spec:
  advertisements:
    - advertisementType: "Service"
      service:
        selector:
          matchLabels:
            bgp-speaker: "true"
        serviceTypes:
          - "LoadBalancer"
```

**Обязательность селектора (Cilium 1.16+):** Текущая версия Cilium требует явного указания селектора для анонса сервисов. Селектор сопоставляется с labels самого сервиса. Если селектор не указан, анонс не будет создан.

Для того чтобы сервис участвовал в BGP-анонсе, его необходимо пометить соответствующим label:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-app-lb
  namespace: production
  labels:
    bgp-speaker: "true"
spec:
  type: LoadBalancer
  selector:
    app: my-app
  ports:
    - port: 80
      targetPort: 8080
```

**Влияние `externalTrafficPolicy` на анонсы:**

Параметр `externalTrafficPolicy` в Service напрямую влияет, с каких узлов анонсируются маршруты:

- **`Cluster` (по умолчанию):** Cilium анонсирует IP-адрес сервиса со **всех** узлов, на которых работает BGP-спикер, независимо от того, есть ли на них локальные эндпоинты. Это приводит к избыточным маршрутам на роутере.
- **`Local`:** Анонс происходит **только** с тех узлов, где находятся локальные эндпоинты (поды) сервиса. Это сокращает количество маршрутов и позволяет маршрутизатору направлять трафик ближайшими путями.

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

##### Подготовка узлов

На всех узлах кластера, где должен работать BGP-спикер, добавляется label:

```bash
kubectl label node <node-name> cilium.io/bgp-speaker=true
```

В примере метки добавлены на все пять узлов (включая control-plane, которые одновременно являются worker-узлами).

##### Настройка BGP на MikroTik RouterOS

В качестве BGP-роутера использовался MikroTik RouterOS. Ниже приведены команды CLI для настройки:

```routeros
# Создание BGP-инстанса
/routing bgp instance add name=K8SBGP as=65001 router-id=192.168.2.189

# Добавление BGP-connection (слушаем все, анонсируем в main routing-table)
/routing bgp connection add \
  connect=yes \
  listen=yes \
  out.filter=K8S-route-filter \
  routing-table=main \
  local.address=192.168.2.0/24 \
  remote.address=192.168.2.189/32
```

Проверка сессий на MikroTik:

```routeros
# Статус BGP-сессий
/routing bgp session print

# Просмотр динамических маршрутов
/ip route print
```

После установки сессии (статус `established`) в таблице маршрутизации MikroTik появятся динамические маршруты (B) к Pod CIDR узлов кластера.

##### Проверка native routing внутри кластера

Для проверки, что native routing активен, выполните в поде Cilium:

```bash
kubectl exec -it -n kube-system ds/cilium -- cilium-dbg bgp
```

В выводе должна присутствовать строка `routing native: true`.

На каждом узле кластера в таблице маршрутизации должны присутствовать прямые записи к Pod CIDR других узлов:

```bash
# На узле R1 просмотр маршрутов к подсетям других узлов
ip route | grep 10.244
# → 10.244.2.0/24 via 192.168.2.132 dev eth0
# → 10.244.3.0/24 via 192.168.2.134 dev eth0
```

##### Верификация из локальной сети

После анонсирования маршрутов через BGP поды становятся доступными из локальной сети по их реальным IP-адресам:

```bash
# Пинг пода с рабочей станции в той же сети
ping 10.244.1.5

# Проверка HTTP-доступности
curl http://10.244.1.5:8080

# Трассировка маршрута
tracepath 10.244.1.5
```

Для принудительного добавления маршрута на клиентской машине (если роутер не анонсирует маршрут автоматически):

```bash
# Linux/macOS
sudo ip route add 10.244.0.0/16 via 192.168.2.189
```

#### Диагностика

```bash
# Проверка BGP-сессий
cilium bgp peers

# Просмотр per-node конфигурации
kubectl get ciliumbgpnodeconfig

# Статус BGP-инстанса на узле
kubectl describe ciliumbgpnodeconfig <node-name>

# Проверка, что native routing активен
kubectl exec -it -n kube-system ds/cilium -- cilium-dbg bgp
# → routing native: true

# Просмотр маршрутов на узле
ip route | grep <pod-cidr>
```

##### Проверка снаружи кластера

После успешного анонсирования BGP-маршрутов поды должны быть доступны из локальной сети:

```bash
# Пинг пода по реальному IP
ping 10.244.1.5

# Проверка HTTP
curl http://10.244.1.5:8080

# Трассировка
tracepath 10.244.1.5
```

##### Проверка на MikroTik

```routeros
# Статус BGP-сессий
/routing bgp session print
# → established

# Динамические маршруты
/ip route print
# → Dyn active B ... 10.244.1.0/24 via 192.168.2.131
```

##### Проверка ConfigMap

```bash
# Параметры маскарадинга
kubectl -n kube-system get configmap cilium-config -o jsonpath='{.data.ipv4-masquerade}'
kubectl -n kube-system get configmap cilium-config -o jsonpath='{.data.ipv4-native-routing-cidr}'
```

##### Hubble: наблюдение за трафиком

```bash
# Просмотр потоков к/от пода
hubble observe --pod <pod-name> -n <namespace> --follow

# Просмотр отброшенных пакетов
hubble observe --type drop --follow
```

### Настройка Load Balancer (L2 Mode)

**L2 Announcements** (Beta) — функция, которая делает сервисы типа `LoadBalancer` (и `externalIPs`) доступными во всей L2-сети bare-metal кластера: один из узлов отвечает на ARP/NDP-запросы за виртуальный IP сервиса своим MAC-адресом и выполняет балансировку трафика на входе в кластер (north/south load balancer). Преимущество перед NodePort: каждый сервис получает уникальный IP, поэтому сервисы могут использовать одинаковые порты (80/443), а при падении узла VIP мигрирует на другой узел и продолжает работать.

#### Как это работает (datapath)

Ответ на ARP формирует не ядро Linux и не userspace-процесс, а eBPF-программа Cilium, подцепленная к TC ingress hook физических интерфейсов:

```bash
# Программа cil_from_netdev подцеплена к ingress интерфейса
# direct-action = программа сама принимает решение о судьбе пакета
# not offloaded = программа не офлоадена в сетевую карту (таких NIC очень мало)
sudo tc filter show dev eth0 ingress
# → filter protocol all pref 1 bpf chain 0 handle 0x1 cil_from_netdev direct-action not offloaded
```

Путь ARP-запроса в datapath Cilium:

1. ARP-запрос перехватывается на TC hook (`cil_from_netdev`) — очень рано в сетевом пути, близко к сетевой карте.
2. Проверяется, включены ли L2 announcements (`enable_l2_announcements`). Если нет — пакет уходит дальше в сетевой стек, и ARP обрабатывает ядро Linux напрямую.
3. Проверяется «живость» Cilium Agent: агент периодически обновляет timestamp в BPF config map (`RUNTIME_CONFIG_AGENT_LIVENESS`). Если агент умер, а eBPF-программа осталась в ядре, datapath перестаёт отвечать и пропускает пакет дальше — защита от «зомби»-ответов при неработающем агенте.
4. Валидируется ARP-запрос, извлекаются ключевые поля (IP-адрес, индекс интерфейса).
5. Проверяется BPF map `cilium_l2_responder_v4` (ключ: `{ip4, ifindex}`): отвечаем ли мы за этот IP на этом интерфейсе.
6. Если да — ARP-ответ формируется **inplace**: в том же SKB подменяются поля (MAC-адреса, направление `EGRESS`), и пакет отправляется обратно в сетевой стек через redirect (`TC_ACT_REDIRECT`), минуя значительную часть стека Linux.

Такой путь быстрее классического (ядро → userspace → ядро): не выделяется дополнительная память, обработка происходит inplace, а пакет почти всегда укладывается в кэш CPU.

При захвате лизы новый лидер рассылает gratuitous ARP на всех сконфигурированных интерфейсах (по одному пакету на интерфейс) — клиенты, принимающие такие пакеты, сразу обновляют ARP-таблицы.

#### Включение и предварительные требования

```bash
helm upgrade --install cilium cilium/cilium \
  --namespace kube-system \
  --version 1.20.0 \
  --set kubeProxyReplacement=true \
  --set l2announcements.enabled=true \
  --set externalIPs.enabled=true   # только если анонсируются externalIPs
```

**Предварительные требования:**
- Включён `kubeProxyReplacement` — обязательное условие (без замены kube-proxy BPF-программы ARP-ответа не загружаются).
- Интерфейсы, на которых анонсируются IP, должны входить в `--devices` / Helm-опцию `devices`, если она задана явно.
- Для анонса `externalIPs` дополнительно требуется `externalIPs.enabled=true`.
- **sysctl на хостах:** на bare-metal требуется настроить `ip_forward` и `rp_filter` на узлах — иначе ответы на трафик могут отбрасываться из-за строгого обратного фильтра. Подробности: [Настройка sysctl на хостах](#настройка-sysctl-на-хостах).

#### Пул IP и политика анонсирования

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

Поля политики:
- `serviceSelector` — label selector сервисов. Если не указан, выбраны все сервисы. Сервис должен иметь неуказанный `loadBalancerClass` или `io.cilium/l2-announcer`. Специальные селекторы: `io.kubernetes.service.name` и `io.kubernetes.service.namespace` (матчат имя/namespace сервиса).
- `nodeSelector` — подмножество узлов-кандидатов. Лидер для сервиса выбирается среди них; он же становится north/south балансировщиком всего трафика сервиса.
- `interfaces` — список regex (golang-синтаксис), логика OR; по умолчанию — все интерфейсы. Это **не** механизм безопасности: сервис остаётся доступным и через неанонсированные интерфейсы (например, при hard-coded ARP-записях).
- `externalIPs` / `loadBalancerIPs` — какие IP анонсировать; оба по умолчанию `false`, поэтому рабочая политика должна включить хотя бы один.

Статус политики отражает ошибки конфигурации (например, пустой `values` у оператора `In`):

```bash
kubectl describe l2announcement policy1
# → Status: Conditions: Type: io.cilium/bad-service-selector, Status: True
```

#### Настройка sysctl на хостах

На bare-metal возвратный путь трафика часто ломается из-за настроек ядра Linux. Если Cilium анонсирует IP на одном интерфейсе, а основной маршрут выходит через другой, ядро может отбрасывать ответы на входящие пакеты.

**Обязательные настройки на каждом узле:**

```bash
cat <<'EOF' | sudo tee /etc/sysctl.d/99-cilium-l2.conf
net.ipv4.ip_forward=1
net.ipv4.conf.all.rp_filter=0
net.ipv4.conf.default.rp_filter=0
net.ipv4.conf.eth0.rp_filter=0
EOF
sudo sysctl --system
```

Пояснение параметров:

- **`net.ipv4.ip_forward=1`** — узел должен перенаправлять пакеты между физическим интерфейсом и подсетью кластера. Без этого ответы от подов не достигнут клиентов за пределами L2-сегмента.
- **`net.ipv4.conf.all.rp_filter=0`** и **`net.ipv4.conf.default.rp_filter=0`** — отключение строгого обратного фильтра (Reverse Path Forwarding). При `rp_filter=1` ядро проверяет, чтобы ответ выходил тем же интерфейсом, через который пришёл запрос; в bare-metal с асимметричной маршрутизацией это приводит к дропу валидных ответов.
- **`net.ipv4.conf.<iface>.rp_filter=0`** — пер-интерфейсный override для конкретного NIC, если анонс IP происходит на одном интерфейсе, а основной маршрут — через другой.

Если кластер использует несколько физических интерфейсов или VLAN, повторите `net.ipv4.conf.<iface>.rp_filter=0` для каждого соответствующего интерфейса.

> **Важно:** `rp_filter` вычисляется как максимум значения `all` и значения конкретного интерфейса. Установка `all.rp_filter=0` не гарантирует `iface.rp_filter=0` — проверяйте оба уровня: `sysctl net.ipv4.conf.all.rp_filter` и `sysctl net.ipv4.conf.<iface>.rp_filter`.

#### Фиксация IP для production-сервисов

IP-адрес, назначенный LoadBalancer-сервису из `CiliumLoadBalancerIPPool`, может меняться при пересоздании сервиса. Для production-нагрузок закрепляйте адрес, чтобы DNS, firewall-правила и NAT-трансляции работали с предсказуемым IP.

Поле `spec.loadBalancerIP` помечено как **устаревшее** начиная с k8s v1.24 (поддерживается, но может быть удалено). Современный способ запросить конкретный IP из пула Cilium — аннотация **`lbipam.cilium.io/ips`**:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: apisix
  namespace: ingress-apisix
  annotations:
    "lbipam.cilium.io/ips": "172.16.57.193"
spec:
  type: LoadBalancer
  ports:
    - port: 80
      targetPort: 80
  selector:
    app: apisix
```

Cilium выдаст запрошенный IP из пула или вернёт ошибку, если адрес уже занят. Аннотация `lbipam.cilium.io/ips` принимает список через запятую, что позволяет запрашивать несколько IP для dual-stack.

> **Примечание:** в старых версиях Cilium (≤1.13) аннотация называлась `io.cilium/lb-ipam-ips`. Не запрашивайте первый и последний IP из CIDR-блока пула — они зарезервированы под сетевой и широковещественные адреса.

#### Выбор лидера (Leader Election) и тюнинг failover

Хост хранит один MAC-адрес на IP (последний увиденный ответ), поэтому только один узел кластера может отвечать за конкретный сервисный IP. Каждый Cilium Agent участвует в выборе лидера для каждого сервиса через механизм Kubernetes **Lease** — first come, first serve (первый захвативший лизу получает её, что может давать асимметричное распределение трафика).

- Лизы создаются в namespace Cilium (обычно `kube-system`) с именами `cilium-l2announce-<namespace>-<service>`.
- `holderIdentity` — узел-лидер; если лидер не продлевает лизу в течение `leaseDurationSeconds`, выбирается новый.

```bash
kubectl -n kube-system get lease | grep cilium-l2announce
# → cilium-l2announce-default-deathstar   worker-node   2d20h
```

Тюнинг (Helm-опции):

| Параметр | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `l2announcements.leaseDuration` | `15s` | Значение `leaseDurationSeconds` создаваемых лиз; определяет, как долго лидер должен быть недоступен, прежде чем произойдёт failover. Должен быть >1s и больше `leaseRenewDeadline` |
| `l2announcements.leaseRenewDeadline` | `5s` | Интервал продления лизы лидером. Должен быть больше `leaseRetryPeriod` минимум на 20% |
| `l2announcements.leaseRetryPeriod` | `2s` | Пауза между попытками продления при ошибке. Должен быть меньше `leaseRenewDeadline` минимум на 20% |

Теоретическое окно failover: от `leaseDuration - leaseRenewDeadline` до `leaseDuration + leaseRenewDeadline`. Со значениями по умолчанию — **10–20 секунд**; при тюнинге (`leaseDuration=3s`, `leaseRenewDeadline=1s`, `leaseRetryPeriod=200ms`) — 2–4 секунды:

```bash
helm upgrade cilium cilium/cilium --version 1.20.0 \
  --namespace kube-system --reuse-values \
  --set l2announcements.enabled=true \
  --set kubeProxyReplacement=true \
  --set l2announcements.leaseDuration=3s \
  --set l2announcements.leaseRenewDeadline=1s \
  --set l2announcements.leaseRetryPeriod=200ms
```

**Trade-off:** чем быстрее детект падения, тем выше нагрузка на API server и CPU (каждый сервис — отдельная лиза и отдельный renew-запрос). Кластеры с небольшим числом сервисов могут позволить быстрый failover; крупным кластерам, возможно, придётся увеличить параметры.

**Механика failover:** узлы, участвующие в выборе, обнаруживают непродление лизы и запрашивают у API server статус нового держателя — проходит первый запрос, остальные отклоняются. Новый лидер рассылает gratuitous ARP. Клиенты, не принимающие gratuitous ARP (защита от ARP spoofing), переключатся только по истечении TTL своего ARP-кэша — их downtime будет больше настроенного окна.

#### Обслуживание узлов и предсказуемая доступность

Во время планового обслуживания (`kubectl drain`, перезагрузка) Cilium перестаёт анонсировать IP на узле, и сервис может стать недоступным до тех пор, пока другой узел не захватит лизу. Чтобы поведение было предсказуемым:

```bash
kubectl drain node-01 --ignore-daemonsets --delete-config=0 --delete-emptydir-data
# → node/node-01 cordoned
# → node/node-01 drained
sudo reboot
```

После перезагрузки Cilium должен автоматически возобновить анонс, если узел вернулся в лист узлов, соответствующий `nodeSelector` политики.

**Рекомендации для минимизации простоя:**

- **Один пул на кластер:** используйте единый `CiliumLoadBalancerIPPool` для всех узлов, чтобы любой из них мог взять IP на себя.
- **Фиксируйте IP для production-сервисов:** закрепляйте адрес через аннотацию `lbipam.cilium.io/ips` (см. [Фиксация IP для production-сервисов](#фиксация-ip-для-production-сервисов)).
- **Анонсы только рабочим узлам:** ограничьте `nodeSelector` политики метками `node-role.kubernetes.io/worker` — контроллеры не должны анонсировать VIP.
- **Уменьшите TTL ARP на upstream-оборудовании:** стандартный ARP cache timeout на роутерах 1–4 минуты; если оборудование позволяет, уменьшите его до 30–60 секунд для меньшего downtime при переключении.
- **Pod Disruption Budgets:** применяйте PDB к подам балансировщика/ингресса, чтобы Kubernetes не выгружал все реплики на одном узле одновременно.

#### Sizing client rate limit

Выбор лидера генерирует постоянный трафик к API server. Стандартный лимит клиента Cilium — **5 QPS / burst 10** — быстро достигается при L2 announcements, поэтому лимит нужно рассчитывать:

```
QPS = #services × (1 / leaseRenewDeadline)

# пример: 65 сервисов, leaseRenewDeadline = 2s
QPS = 65 × (1/2s) = 32.5 QPS
```

```bash
helm upgrade cilium cilium/cilium --version 1.20.0 \
  --namespace kube-system --reuse-values \
  --set l2announcements.enabled=true \
  --set k8sClientRateLimit.qps=33 \
  --set k8sClientRateLimit.burst=50
```

Burst ставят чуть выше расчётного значения, чтобы покрыть всплески от остальных фич Cilium. Симптом слишком низкого лимита в логах агента: `Waited for ... due to client-side throttling`, прерывистые ошибки продления лиз, частая смена лидеров.

#### Ограничения

- **Нет балансировки до кластера:** из-за механизма L3→L2-трансляции все ARP-запросы на конкретный IP приходят на одну ноду; балансировка начинается только внутри кластера.
- **Асимметричная загрузка:** механизма выравнивания нагрузки между нодами одной политики нет.
- **Несовместимость с `externalTrafficPolicy: Local`:** IP анонсируется на всех нодах, соответствующих policy, включая ноды без подов сервиса — трафик на такой ноде дропается. Используйте `externalTrafficPolicy: Cluster`.
- **IPv6/NDP:** поддержка NDP добавлена в Cilium 1.19; в более ранних версиях (≤1.18) работает только IPv4/ARP.

#### Диагностика

```bash
# 1. Фича включена и KPR активен?
kubectl -n kube-system exec ds/cilium -- cilium-dbg config --all | grep EnableL2Announcements
# → EnableL2Announcements             : true
kubectl -n kube-system exec ds/cilium -- cilium-dbg config --all | grep KubeProxyReplacement
# → KubeProxyReplacement              : true

# 2. Есть политика и лизы?
kubectl get CiliumL2AnnouncementPolicy
kubectl -n kube-system get lease | grep cilium-l2announce
# → cilium-l2announce-default-service-red   kind-worker   34s

# 3. Агент знает, что должен анонсировать (IP + интерфейс)?
kubectl -n kube-system exec ds/cilium -- cilium-dbg shell -- db/show l2-announce
# → # IP        NetworkInterface
# → 10.0.10.0   eth0

# 4. Устройство отобрано для анонсов (только Selected=true участвуют)?
kubectl -n kube-system exec ds/cilium -- cilium-dbg shell -- db/show devices

# 5. ARP отвечает? (arping из пода cilium-agent на том же L2-сегменте)
kubectl -n kube-system exec pod/cilium-z4ef7 -- sh -c 'apt update && apt install -y arping && arping -i eth0 10.0.10.0'
# → ARPING 10.0.10.0
# → 58 bytes from 02:42:ac:13:00:03 (10.0.10.0): index=0 time=11.772 usec

# 6. Счётчик ответов datapath: 0 = запрос не доходит до ноды; >0 = проблема на обратном пути
kubectl -n kube-system exec pod/cilium-vxz67 -- bpftool map dump pinned /sys/fs/bpf/tc/globals/cilium_l2_responder_v4
# → [{ "key": { "ip4": 655370, "ifindex": 50 }, "value": { "responses_sent": 20 } }]
```

# 7. sysctl на хостах: ip_forward включён, rp_filter отключён?
sysctl net.ipv4.ip_forward
# → net.ipv4.ip_forward = 1
sysctl net.ipv4.conf.all.rp_filter net.ipv4.conf.default.rp_filter
# → 0  0

# 8. ARP-кэш на клиенте: правильный MAC для VIP?
ip neigh show <vip>
# → <vip> dev eth0 lladdr 52:54:00:12:34:56 REACHABLE
```

Типчные ошибки:
- **RBAC:** при включении не через Helm-чарт агент не может создавать лизы — в логах `leases.coordination.k8s.io ... is forbidden`. Исправление: `kubectl edit clusterrole cilium` и добавление правил для `coordination.k8s.io/leases` (`create`, `get`, `update`, `list`, `delete`).
- **Устройство не в `devices`:** лиза есть, но IP отсутствует в `db/show l2-announce` — проверить regex в `interfaces` политики и Helm-опцию `devices`.
- **sysctl на хостах:** ответы на ARP приходят, но трафик не возвращается клиенту — проверить `ip_forward` и `rp_filter` на узлах (см. [Настройка sysctl на хостах](#настройка-sysctl-на-хостах)).
- **Клиент видит неправильный MAC:** один и тот же VIP анонсируют два узла — проверить отсутствие пересечений в `CiliumL2AnnouncementPolicy` и уникальность `CiliumLoadBalancerIPPool`. На клиенте: `ip neigh show <vip>`; на узлах: `tcpdump -nei eth0 arp or icmp`.
- **Сервис недоступен после reboot:** кластер восстановлен, но upstream-устройство хранит устаревшую ARP-запись со старым MAC — очистить ARP-кэш на роутере или клиенте (`ip neigh flush`, `arp -d <vip>`), либо уменьшить ARP cache timeout на upstream-оборудовании (см. [Обслуживание узлов](#обслуживание-узлов-и-предсказуемая-доступность)).
- **IP остаётся `pending`:** сервис не попадает под `serviceSelector` политики, либо в пуле нет свободных адресов — проверить `kubectl get svc <name> -o jsonpath='{.status.loadBalancer.ingress}'`, статус `CiliumLoadBalancerIPPool` и селекторы политики.

#### Известные проблемы: non-linear SKB (Talos)

На некоторых сочетаниях NIC + драйвер (впервые воспроизведено на Talos) ядро разбивает ARP-пакет на фрагменты: в linear-области SKB оказывается только 14 байт (Ethernet-заголовок), а остальное — в page-фрагментах. Внутренние функции обработки ARP (`lib/arp.h`) ожидают linearized packet, проверка границ данных не проходит, и L2 announcements перестаёт отвечать: лиза захвачена, `cilium-dbg statedb l2-announce` показывает IP, tcpdump видит запрос, но `responses_sent` в BPF map остаётся 0.

Исправление: PR cilium/cilium#41233 «bpf: add support for delinearized ARP packets» (автор vsinitsyn, вмержен в августе 2025, fixes #40419) — реализована функция `revalidate_data_arp_pull()`, линеаризующая ARP-пакет перед обработкой, аналогично IPv4/IPv6. В актуальных версиях Cilium (включая 1.20.x, scope этого файла) баг не воспроизводится.

**Урок:** eBPF-программы, работающие с пакетами, должны корректно обрабатывать non-linear SKB — иначе баг воспроизводится только на узком сочетании оборудования и ядра.

**Отладка в средах без shell (Talos):** приём, описанный в докладе (не верифицирован в официальной документации): модифицированный исходник eBPF-программы подкладывается в ConfigMap, который Cilium Agent подхватывает перед компиляцией при старте — так можно вставить print-выводы в datapath и увидеть реальное содержимое SKB.

Смежная фича: **L2 Pod Announcements** (включается отдельно: `l2podAnnouncements.enabled=true` + `l2podAnnouncements.interfacePattern`) анонсирует IP-адреса подов через gratuitous ARP — пока только для IPv4.

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

## Модель default-deny и allowlist с CiliumNetworkPolicy

### Принцип работы

CiliumNetworkPolicy реализует модель «запрет по умолчанию + разрешительный список» (default-deny + allowlist). Отличие от стандартного Kubernetes NetworkPolicy — семантика пустых правил:

- `endpointSelector: {}` выбирает все поды в namespace.
- `ingress: [{}]` — секция ingress содержит правило без `fromEndpoints` или `fromCIDR`. Пустое правило не соответствует ни одному источнику, поэтому **весь входящий трафик блокируется** (deny all).
- `egress: [{}]` аналогичным образом блокирует весь исходящий трафик.

В стандартном NetworkPolicy отсутствие секции `ingress`/`egress` означает «разрешить всё», а в CiliumNetworkPolicy — наличие секции с пустым правилом `{}` означает «ничего не разрешено».

> **Cilium v1.16+:** Появилось поле `enableDefaultDeny` (`spec.enableDefaultDeny.ingress`/`egress: true`). Традиционный подход с пустыми правилами (`ingress: [{}]`) также работает — endpoint переходит в режим default-deny, если его выбирает правило и содержит соответствующую секцию [Источник](https://docs.cilium.io/en/stable/security/policy/layer3/).

### default-deny для namespace

```yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: default-deny
  namespace: app
spec:
  description: "Default deny all ingress and egress"
  endpointSelector: {}
  ingress:
  - {}
  egress:
  - {}
```

После применения поды не смогут достучаться даже к DNS. Следующее правило исправляет это.

### Разрешить DNS

Без этого ломается service discovery — поды не стартуют из-за ошибок резолва DNS:

```yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: allow-dns
  namespace: app
spec:
  endpointSelector: {}
  egress:
  - toEndpoints:
    - matchLabels:
        "k8s:io.kubernetes.pod.namespace": kube-system
        "k8s:k8s-app": kube-dns
    toPorts:
    - ports:
      - port: "53"
        protocol: UDP
      - port: "53"
        protocol: TCP
```

### Разрешить ingress от ingress controller

```yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: allow-from-ingress
  namespace: app
spec:
  endpointSelector:
    matchLabels:
      app: my-service
  ingress:
  - fromEndpoints:
    - matchLabels:
        "k8s:io.kubernetes.pod.namespace": ingress-apisix
```

До `my-service` может достучаться только ingress-контроллер APISIX. Прямой трафик между подами из других неймспейсов заблокирован.

### Межсервисное взаимодействие

Frontend должен обращаться к backend только на порт 8080:

```yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: allow-frontend-to-backend
  namespace: app
spec:
  endpointSelector:
    matchLabels:
      app: backend
  ingress:
  - fromEndpoints:
    - matchLabels:
        app: frontend
    toPorts:
    - ports:
      - port: "8080"
        protocol: TCP
```

Только поды `frontend` и только порт 8080.

### Egress к базам данных

```yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: allow-backend-to-postgres
  namespace: app
spec:
  endpointSelector:
    matchLabels:
      app: backend
  egress:
  - toEndpoints:
    - matchLabels:
        "k8s:io.kubernetes.pod.namespace": databases
        "k8s:app": postgresql
    toPorts:
    - ports:
      - port: "5432"
        protocol: TCP
```

### Egress к внешним API через FQDN

```yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: allow-external-api
  namespace: app
spec:
  endpointSelector:
    matchLabels:
      app: my-service
  egress:
  - toFQDNs:
    - matchName: "api.stripe.com"
    - matchName: "api.sendgrid.com"
    - matchPattern: "*.s3.amazonaws.com"
    toPorts:
    - ports:
      - port: "443"
        protocol: TCP
```

Cilium резолвит FQDN на лету и обновляет eBPF-карты. Поды могут достучаться только до явно разрешённых внешних эндпоинтов.

### L7-политика для HTTP

Cilium применяет политику на уровне HTTP (L7), анализируя методы и пути. Детали реализации описаны в [Сетевая политика L7 (HTTP)](#сетевая-политика-l7-http). Пример egress-правила, ограничивающего запросы к `payment-service` только методом `POST` на путь `/api/v1/charge`:

```yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: allow-payment-charge
  namespace: app
spec:
  endpointSelector:
    matchLabels:
      app: my-service
  egress:
  - toEndpoints:
    - matchLabels:
        app: payment-service
    toPorts:
    - ports:
      - port: "8080"
        protocol: TCP
      rules:
        http:
        - method: "POST"
          path: "/api/v1/charge"
```

Попытка выполнить `GET /admin` будет отброшена на сетевом уровне, до того как запрос достигнет пода.

### Отладка через Hubble

```bash
# Все отброшенные соединения в неймспейсе
hubble observe --namespace dev --verdict DROPPED -f

# Трафик в реальном времени
hubble observe --namespace dev -f

# Потоки конкретного пода
hubble observe --pod dev/api-6d8b4c5f9-xk4qv -f

# Потоки на конкретный порт
hubble observe --namespace dev --port 5432 -f

# Что отбрасывается у конкретного пода
hubble observe --namespace app --from-pod app/my-service --verdict DROPPED
```

#### Чеклист отладки NetworkPolicy

1. **Что блокируется:** `hubble observe --verdict DROPPED` — просмотр отброшенных потоков в реальном времени
2. **Метки namespace:** `namespaceSelector` использует метки namespace, а не имя. Проверить: `kubectl get namespace --show-labels`
3. **Метки подов:** при неправильной метке политика не сработает. Проверить: `kubectl get pods -n <ns> --show-labels`
4. **DNS egress:** перед любыми FQDN-правилами явно разрешить порт 53 на kube-dns
5. **L7-правила:** требуют включённого HTTP-прокси Cilium (Envoy)

Hubble показывает под-источник, под-цель или FQDN, порт и политику с вердиктом `POLICY_DENIED`. Добавлять логирование в приложения не нужно.

### Постепенное внедрение (Policy Audit Mode)

Не применяйте default-deny к продакшен-неймспейсам сразу. Рабочий процесс:

1. **Включить Policy Audit Mode** на уровне демона — трафик разрешается, а нарушения логируются:

```bash
helm upgrade cilium cilium/cilium --version 1.20.0 \
  --namespace kube-system --reuse-values \
  --set policyAuditMode=true
```

Или через ConfigMap:

```bash
kubectl patch -n kube-system configmap cilium-config --type merge \
  --patch '{"data":{"policy-audit-mode":"true"}}'
kubectl rollout restart ds cilium -n kube-system
```

2. **Применить разрешающие правила** для каждого легитимного потока.
3. **Наблюдать за нарушениями** в Hubble:

```bash
hubble observe --namespace app --verdict DROPPED
```

4. **Повторять**, пока неожиданные дропы не исчезнут.
5. **Отключить Policy Audit Mode** и включить enforcement:

```bash
kubectl patch -n kube-system configmap cilium-config --type merge \
  --patch '{"data":{"policy-audit-mode":"false"}}'
kubectl rollout restart ds cilium -n kube-system
```

В режиме аудита трафик разрешается, а нарушения логируются как события `policy-verdict` с вердиктом `POLICY_DENIED`. Это позволяет проинвентаризировать потоки перед включением блокировки [Источник](https://docs.cilium.io/en/latest/security/policy-creation/).

---

## Стандартные NetworkPolicy для базовой изоляции

Cilium полностью поддерживает стандартные Kubernetes NetworkPolicy (API-группа `networking.k8s.io/v1`). Для базовой изоляции на уровне L3/L4 достаточно стандартных политик — `CiliumNetworkPolicy` требуется только для L7, FQDN и кластерных политик.

### Default Deny (стандартный NetworkPolicy)

Политика блокирует весь входящий трафик в namespace. Egress по умолчанию остаётся разрешённым:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: dev
spec:
  podSelector: {}
  policyTypes:
    - Ingress
```

Применяйте её в каждом прикладном namespace. После применения поды становятся изолированными — входящий трафик блокируется, пока не будет добавлено разрешающее правило.

Для полной изоляции (ingress + egress) добавьте `Egress` в `policyTypes`:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: dev
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
```

После полного default-deny обязательно добавьте явные egress-правила для DNS и других нужных сервисов.

### Метка `expose: "true"` для внешних сервисов

Сервисы, доступные извне (через ingress-контроллер), получают метку `expose: "true"`. Остальные поды остаются изолированными:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-apisix-ingress
  namespace: dev
spec:
  podSelector:
    matchLabels:
      expose: "true"
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-apisix
```

Только поды с меткой `expose: "true"` принимают трафик от ingress-контроллера APISIX в namespace `ingress-apisix`. Прямой трафик между подами из других namespace заблокирован.

### Межсервисное взаимодействие (стандартный NetworkPolicy)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backend
  namespace: dev
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: frontend
      ports:
        - port: 8080
          protocol: TCP
```

Frontend может обращаться к backend только на порт 8080. Любые другие поды или порты блокируются.

---

## Кластерная политика: CiliumClusterwideNetworkPolicy

`CiliumClusterwideNetworkPolicy (CCNP)` применяется ко всем подам в кластере без привязки к namespace. Вместо добавления правил в каждый namespace отдельно:

```yaml
apiVersion: cilium.io/v2
kind: CiliumClusterwideNetworkPolicy
metadata:
  name: allow-prometheus-scrape
spec:
  endpointSelector: {}
  ingress:
    - fromEndpoints:
        - matchLabels:
            "k8s:io.kubernetes.pod.namespace": observability
            app.kubernetes.io/name: prometheus
      toPorts:
        - ports:
            - port: "9090"
              protocol: TCP
            - port: "9100"
              protocol: TCP
            - port: "8080"
              protocol: TCP
```

Одна политика — и Prometheus собирает метрики со всех подов во всех namespace. Порты `9090` (Prometheus), `9100` (Node Exporter) и `8080` (приложения) открыты только для подов с метками `app.kubernetes.io/name: prometheus` в namespace `observability`.

Для управления CCNP используйте:

```bash
kubectl get ciliumclusterwidenetworkpolicy
kubectl describe ciliumclusterwidenetworkpolicy allow-prometheus-scrape
```

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
| **L2 announcements не отвечает на ARP** | Не включён kube-proxy replacement, политика не матчит устройства/сервисы, нет RBAC на leases или низкий `k8sClientRateLimit` | `cilium-dbg config --all \| grep EnableL2Announcements`; `bpftool map dump pinned /sys/fs/bpf/tc/globals/cilium_l2_responder_v4` (поле `responses_sent`) | Проверить `l2announcements.enabled=true`, селекторы политики, ClusterRole `cilium` на `coordination.k8s.io/leases`, лимит `k8sClientRateLimit` |

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

# Таблица балансировщика (VIP -> бэкенды) в datapath
cilium-dbg bpf lb list

# Таблица NAT в BPF (masquerade/SNAT)
cilium-dbg bpf nat list | head

# Трассировка политики по identity (allow/deny между identity)
cilium-dbg policy trace --src-identity <id> --dst-identity <id> --dport <port>

# Внутреннее состояние endpoint (identity, policy, BPF maps)
cilium-dbg endpoint get <id> -o json | jq '.status.policy'

# BGP пиры Cilium
cilium bgp peers

# ClusterMesh статус (межкластерная связность)
cilium clustermesh status --wait
```

### Hubble: расширенные запросы

```bash
# Потоки конкретного пода в реальном времени
hubble observe --pod <ns>/<pod> -f

# Только отклонённые соединения по всему кластеру
hubble observe --verdict DROPPED -f

# Потоки неймспейса за последние 5 минут
hubble observe --namespace <ns> --since 5m

# Потоки на конкретный порт
hubble observe --namespace <ns> --port 5432 -f

# TCP egress к FQDN (проверка egress-политики по DNS-имени)
hubble observe --protocol tcp --from-pod <ns>/<pod> --to-fqdn '*.example.com'

# Включить Hubble UI
cilium hubble enable --ui

# Статус Hubble relay и observer
hubble status
```

### Мониторинг агента и сетевых событий

```bash
# Дропы пакетов в реальном времени из dataplane Cilium
cilium monitor --type drop

# Подробное состояние агента (datapath, IPAM, BPF maps, контроллеры)
cilium status --verbose

# Тест связности кластера
cilium connectivity test
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
