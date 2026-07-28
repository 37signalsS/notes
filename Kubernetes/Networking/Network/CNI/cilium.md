# Cilium: Высокопроизводительный CNI на базе eBPF

## Определения

**Cilium** — это современный плагин интерфейса сетевой связности контейнеров (CNI), обеспечивающий сетевое взаимодействие, безопасность и наблюдаемость рабочих нагрузок. В основе Cilium лежит технология **eBPF** (Extended Berkeley Packet Filter), которая позволяет внедрять логику обработки пакетов напрямую в ядро Linux без изменения исходного кода ядра или приложений.

**kube-proxy-replacement** — режим работы Cilium, полностью заменяющий стандартный `kube-proxy`. В этом режиме балансировка трафика сервисов (ClusterIP, NodePort, LoadBalancer) выполняется через eBPF, что исключает накладные расходы на `iptables` и `conntrack`.

### Ключевые отличия и преимущества eBPF
В отличие от большинства других CNI, использующих стандартный стек `iptables` и сетевой экран Linux, Cilium опирается на eBPF — высокоэффективную и программируемую структуру внутри ядра Linux. Это обеспечивает:
*   **Динамическая обработка пакетов:** Возможность изменять логику обработки трафика без модификации ядра или перезагрузки приложений.
*   **Безопасность с поддержкой API (L7):** Возможность определять политики безопасности на уровне HTTP, gRPC и других API-протоколов, обеспечивая гранулярный контроль на основе семантики запросов.
*   **Визуализация (Hubble):** Генерация динамического графа сетевых взаимодействий в реальном времени, что позволяет видеть зависимости между микросервисами на уровне API.
*   **Высокая производительность:** Эффективная работа в высоконагруженных системах за счет исключения линейного перебора правил `iptables`.

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
- **CiliumNetworkPolicy:** Расширенная версия NetworkPolicy с поддержкой L7 (HTTP, Kafka, DNS) и FQDN-фильтрации.
- **CiliumClusterwideNetworkPolicy:** Политики, применяемые ко всему кластеру (без привязки к Namespace).

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

- **ClusterMesh:** Объединение нескольких кластеров Kubernetes в единую плоскую сеть. Позволяет сервисам обращаться друг к другу по именам (Global Services) и обеспечивать отказоустойчивость.
- **Шифрование трафика:** Поддержка прозрачного шифрования "узел-узел" через **WireGuard** (рекомендуется за производительность) или **IPsec**.
- **Load Balancer (L2 & BGP):** Нативная поддержка сервисов типа `LoadBalancer`, заменяющая сторонние решения (например, MetalLB).
    - **L2 Mode:** Использует ARP-анонсы. IP-адрес приземляется на одну из нод (выбор лидера).
    - **BGP Mode:** Анонсирование маршрутов через протокол BGP, что позволяет распределять трафик между несколькими узлами (ECMP).
- **Egress Gateway:** Маршрутизация исходящего трафика подов через фиксированные IP-адреса узлов (шлюзов) для интеграции с внешними корпоративными файрволами.
- **Bandwidth Manager:** Управление полосой пропускания и предотвращение эффекта "шумного соседа" через очереди ядра (EDT - Earliest Departure Time).

### Cilium Service Mesh и Gateway API

Cilium поддерживает стандарт **Gateway API** и может работать в режиме Service Mesh без sidecar-контейнеров:
- **L7 Load Balancing:** Балансировка на основе путей, заголовков и весов через встроенный Envoy.
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
  --set kubeProxyReplacement=strict \
  --set k8sServiceHost=10.0.0.10 \
  --set k8sServicePort=6443 \
  --set l2announcements.enabled=true \
  --set externalIPs.enabled=true \
  --set gatewayAPI.enabled=true
```

**ВАЖНО:** После обновления конфигурации через Helm необходимо выполнить перезапуск Cilium Agent для применения изменений:
```bash
kubectl rollout restart ds cilium -n kube-system
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
  --version 1.19.6 \
  --set kubeProxyReplacement=strict \
  --set k8sServiceHost=10.0.0.10 \
  --set k8sServicePort=6443 \
  --set hubble.enabled=true \
  --set hubble.ui.enabled=true
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

Пример политики, разрешающей подам с меткой `app: my-app` доступ только к API GitHub:

```yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: "allow-github-api"
spec:
  endpointSelector:
    matchLabels:
      app: my-app
  egress:
  - toFQDNs:
    - matchName: "api.github.com"
  - toEndpoints:
    - matchLabels:
        "k8s:io.kubernetes.pod.namespace": kube-system
        "k8s:k8s-app": kube-dns
    toPorts:
    - ports:
      - port: "53"
        protocol: UDP
      rules:
        dns:
        - matchPattern: "*"
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

Наблюдение за отброшенными пакетами в реальном времени:
```bash
hubble observe --type drop --follow
# → результат: Jul 22 10:00:01.123: default/pod-a:1234 -> default/pod-b:80 policy-denied forward direction
```

---

## См. также

- [Выбор CNI и режимы IPAM](./ipam.md) — подробное сравнение режимов выделения адресов.
- [eBPF в Kubernetes: Глубокое погружение](./ebpf.md) — технология, лежащая в основе Cilium.
- [Официальная документация Cilium](https://docs.cilium.io/) — первоисточник информации.

**[К списку разделов CNI](../cni_kube_proxy_roles.md)**
