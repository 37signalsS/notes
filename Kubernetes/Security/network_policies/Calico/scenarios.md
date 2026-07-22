# Сценарии Calico: Периметральный файрвол

В данном разделе представлены практические примеры реализации сетевой защиты на уровне узлов кластера с использованием расширенных возможностей Calico.

> Основная документация и концепции: [Calico HostEndpoint и GlobalNetworkPolicy](./index.md)

## Определения

**Практический сценарий (Scenario)** — прикладная конфигурация ресурсов Calico (`HostEndpoint`, `GlobalNetworkPolicy`, `GlobalNetworkSet`), предназначенная для решения конкретных задач безопасности, таких как создание внешнего периметра защиты или аудит трафика.

**Периметральный файрвол** — стратегия защиты, при которой фильтрация трафика происходит на физических интерфейсах узлов кластера еще до его попадания во внутреннюю сеть Kubernetes.

## Основные концепции

Для успешной реализации сценариев необходимо понимание следующих механизмов:

* **HostEndpoint**: Привязка политик к физическим интерфейсам узлов. Может создаваться вручную или автоматически через параметр `autoHostEndpoints` в `FelixConfiguration`.
* **preDNAT**: Фильтрация трафика до трансляции адресов (DNAT). Это критично для защиты сервисов типа `NodePort`.
* **Приоритет (Order)**: Определяет порядок применения политик. Политики с меньшим значением `order` обрабатываются первыми.

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

Использование действия `Log` позволяет анализировать попытки несанкционированного доступа.

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

## Дополнительная информация

### Связанные ресурсы

* **Подробные определения**: [Calico HostEndpoint и GlobalNetworkPolicy — Определения](./index.md)
* **Диагностика и команды**: [Операции Calico: Диагностика и обслуживание](./operations.md)
* **Лучшие практики**: [NetworkPolicy: Лучшие практики](../../../Networking/Network/NetworkPolicy/best_practices.md)
