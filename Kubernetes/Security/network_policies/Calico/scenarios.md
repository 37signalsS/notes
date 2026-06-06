# Сценарии Calico: Периметральный файрвол

В данном разделе представлены практические примеры реализации сетевой защиты на уровне узлов кластера с использованием расширенных возможностей Calico.

> Основная документация и концепции: [Calico HostEndpoint и GlobalNetworkPolicy](./index.md)

## Определения

**Calico Scenarios** — прикладные конфигурации ресурсов Calico (`HostEndpoint`, `GlobalNetworkPolicy`), предназначенные для решения конкретных задач безопасности, таких как создание внешнего периметра защиты или аудит трафика.

## Основные концепции

Для успешной реализации сценариев необходимо понимание следующих механизмов:

- **HostEndpoint**: Привязка политик к физическим интерфейсам узлов.
- **preDNAT**: Фильтрация трафика до трансляции адресов (критично для защиты NodePort).
- **Order (Приоритет)**: Порядок обработки правил в цепочке политик.

*Подробное описание концепций: [Calico HostEndpoint и GlobalNetworkPolicy — Основные концепции](./index.md#основные-концепции)*

## Практические сценарии

### Сценарий 1: Базовая защита периметра кластера

**Задача:** Создать защитный контур на уровне узлов, который разрешает только доверенный трафик и блокирует всё остальное.

#### Шаг 1: Определение HostEndpoint для сетевых интерфейсов узлов

Необходимо создать `HostEndpoint` для каждого интерфейса на каждом узле, который вы хотите защитить.

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

Эта политика разрешает легитимный внутренний трафик кластера.

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
    # Разрешить трафик между узлами
    - action: Allow
      source:
        selector: "endpoint-type == 'cluster-perimeter'"
    # Разрешить трафик от Pod'ов (используйте ваш Pod CIDR)
    - action: Allow
      source:
        nets: ["10.244.0.0/16"]
```

#### Шаг 3: Создание запрещающей политики (Низкий приоритет)

Политика `Default Deny` для периметра, которая сработает, если трафик не подошел ни под одно разрешающее правило.

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

Для анализа попыток вторжения или отладки политик можно использовать действие `Log`.

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

Просмотр логов: `journalctl -u calico-node -f | grep "calico-drop"` или в системном логе `/var/log/syslog`.

## Дополнительная информация

### Связанные ресурсы

- **Диагностика и команды**: [Операции Calico: Диагностика и обслуживание](./operations.md)
- **Общая сетевая безопасность**: [NetworkPolicy: Сетевая безопасность](../../network_policies.md)
- **Лучшие практики**: [NetworkPolicy: Лучшие практики](../../../Networking/Network/NetworkPolicy/best_practices.md)
