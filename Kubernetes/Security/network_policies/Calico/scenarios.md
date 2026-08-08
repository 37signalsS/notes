# Сценарии Calico: Распределенный файрвол и Zero-Trust

В данном разделе представлены практические примеры реализации сетевой защиты на уровнях узлов и кластера с использованием расширенных возможностей Calico. Настройка этих сценариев позволяет превратить кластер в среду с "нулевым доверием" (Zero-Trust).

> Основная документация и концепции: [Calico HostEndpoint и GlobalNetworkPolicy](./index.md)

## Определения

**Практический сценарий (Scenario)** — прикладная конфигурация ресурсов Calico (`HostEndpoint`, `GlobalNetworkPolicy`, `GlobalNetworkSet`), предназначенная для решения конкретных задач безопасности: от создания внешнего периметра до микросегментации приложений.

**Периметральный файрвол** — стратегия защиты, при которой фильтрация трафика происходит на физических интерфейсах узлов кластера еще до его попадания во внутреннюю сеть Kubernetes.

**Zero-Trust (Нулевое доверие)** — архитектурный подход, при котором ни одно сетевое соединение не считается доверенным по умолчанию. Доступ разрешается только на основе явных политик, проверяющих идентичность отправителя.

**Identity-based Security** — метод контроля доступа, использующий атрибуты идентичности (например, ServiceAccount) вместо нестабильных IP-адресов или меток подов.

## Основные концепции

Для успешной реализации сценариев необходимо понимание следующих механизмов:

* **HostEndpoint**: Ресурс, представляющий физический интерфейс узла. Позволяет применять политики к трафику, направленному на сам узел (SSH, Kubelet, NodePort).
* **preDNAT**: Фильтрация трафика до трансляции адресов (DNAT). Критично для защиты сервисов `NodePort`, так как позволяет видеть реальный IP источника.
* **Приоритет (Order)**: Параметр, определяющий последовательность применения политик. Меньшее значение означает более высокий приоритет.
* **Dataplane**: Слой обработки трафика. В актуальных версиях Calico (v3.29+) по умолчанию используется **nftables**, обеспечивающий более высокую производительность по сравнению с legacy `iptables`. Для максимальной производительности доступен режим **eBPF**.

*Подробное описание концепций: [Подробные определения Calico](./index.md)*

## Практические сценарии

### Сценарий 1: Базовая защита периметра кластера

**Задача:** Создать защитный контур на уровне узлов, который разрешает только доверенный трафик и блокирует всё остальное.

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

### Сценарий 2: Аудит и логирование заблокированного трафика

Использование действия `Log` позволяет анализировать попытки несанкционированного доступа без немедленного разрыва соединения (если стоит перед Deny).

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
```

### Сценарий 3: Группировка внешних сетей (GlobalNetworkSet)

**Задача:** Разрешить доступ к API-серверу только из доверенных офисных подсетей.

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

### Сценарий 4: Глобальный Default-Deny (Zero-Trust Baseline)

**Задача:** Запретить любое взаимодействие между подами во всех пространствах имен, если оно явно не разрешено. Это фундамент безопасности кластера.

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

### Сценарий 5: Безопасность на основе ServiceAccount

**Задача:** Разрешить доступ к базе данных только подам, использующим специфичный ServiceAccount, игнорируя их метки. Это предотвращает атаки через подмену меток (label spoofing).

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

### Сценарий 6: Защита DNS-трафика

**Задача:** При использовании Global Default-Deny необходимо явно разрешить доступ к DNS (CoreDNS), иначе поды не смогут разрешать имена сервисов.

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

### Сценарий 7: Управление доступом к внешним API (Egress)

**Задача:** Разрешить подам из namespace `payment` доступ только к API платежного шлюза, блокируя остальной интернет.

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

## Дополнительная информация

### Новые возможности (2024-2025)

*   **Интегрированный WAF**: Начиная с версий 2025 года, Calico поддерживает инспекцию L7 (WAF) непосредственно в Ingress-шлюзе, позволяя блокировать SQL-инъекции и XSS через тот же интерфейс политик.
*   **nftables Dataplane**: Переход на `nftables` значительно ускоряет обработку правил в кластерах с тысячами политик и подов.

### Связанные ресурсы

* **Подробные определения**: [Calico HostEndpoint и GlobalNetworkPolicy — Определения](./index.md)
* **Диагностика и команды**: [Операции Calico: Диагностика и обслуживание](./operations.md)
* **Лучшие практики**: [NetworkPolicy: Лучшие практики](../../../Networking/Network/NetworkPolicy/best_practices.md)
* **eBPF в Calico**: [Оптимизация сети через eBPF](../../../Networking/Network/CNI/ebpf.md)
