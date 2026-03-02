# Calico HostEndpoint и GlobalNetworkPolicy

> Основная документация: [NetworkPolicy](../network_policies.md)

## Определения

**HostEndpoint** — это ресурс Calico, который представляет один или несколько сетевых интерфейсов на узле Kubernetes. Применяя политики к `HostEndpoint`, можно создать **периметральный файрвол** для всего кластера, контролируя трафик, который входит на узлы и выходит с них, еще до того, как он достигнет подов.

## Основные концепции

### Поведение по умолчанию: Немедленный "Deny All"

> **Важно:** Как только вы создаете `HostEndpoint` для интерфейса, Calico немедленно применяет к этому интерфейсу правило **"запретить весь трафик" (`Deny All`)**. Любой трафик, который не разрешен явным образом в `GlobalNetworkPolicy`, будет заблокирован.

Это сделано для безопасности, но требует осторожности: сначала нужно создать разрешающие правила, и только потом применять `HostEndpoint`.

### Failsafe Ports (Защита от блокировки)

Чтобы администратор случайно не заблокировал себе доступ к кластеру, в Calico встроен механизм `Failsafe Ports`. По умолчанию он всегда оставляет открытыми критически важные порты, независимо от действующих политик:
*   **Входящие (Inbound):** SSH (22), BGP (179), Kubernetes API (6443), etcd (2379, 2380) и др.
*   **Исходящие (Outbound):** DNS (53), DHCP (67) и др.

Этот список можно кастомизировать или полностью отключить через конфигурацию компонента `Felix` (часть Calico).

### Политики `preDNAT`

Для эффективной фильтрации трафика, предназначенного для кластера, политики должны применяться **до того**, как сработает механизм `NAT` Kubernetes (например, для сервисов `NodePort` или `LoadBalancer`).

Для этого в `GlobalNetworkPolicy` используются два флага:
*   `preDNAT: true`: Указывает, что правила `ingress` (входящие) должны быть применены на раннем этапе в цепочке `iptables`, до `DNAT`.
*   `applyOnForward: true`: Указывает, что правила должны применяться также и к транзитному (forwarded) трафику, который предназначен для подов.

> **Ключевое изменение логики:** Когда вы используете `preDNAT: true`, стандартное поведение "запрещено, если не разрешено" меняется. Вам необходимо **явным образом** добавить в конце цепочки правил политику с `action: Deny`, чтобы заблокировать весь остальной трафик.

## Практический сценарий: Создание периметрального файрвола

**Задача:**
1.  Разрешить весь исходящий трафик.
2.  Разрешить входящий трафик от подов внутри кластера и между узлами кластера.
3.  Разрешить доступ к `LoadBalancer IP` и `Kubernetes API`.
4.  Запретить весь остальной входящий трафик.

### Шаг 1: Создание `HostEndpoint` для каждого узла

Создадим манифест `host-endpoints.yaml`, описывающий интерфейсы всех узлов кластера.

```yaml
# host-endpoints.yaml
apiVersion: projectcalico.org/v3
kind: HostEndpoint
metadata:
  name: control-node-1-ens160
  labels:
    node-role: control-plane
    # Общая метка для всех узлов кластера
    node-endpoint-type: home-cluster
spec:
  interfaceName: ens160
  node: control-node-1.example.local
  expectedIPs: ["192.168.218.171"]
---
apiVersion: projectcalico.org/v3
kind: HostEndpoint
metadata:
  name: worker-node-1-ens160
  labels:
    node-role: worker
    node-endpoint-type: home-cluster
spec:
  interfaceName: ens160
  node: worker-node-1.example.local
  expectedIPs: ["192.168.218.175"]
# ... и так далее для всех узлов
```
*   `labels`: Используются для выбора эндпоинтов в `GlobalNetworkPolicy`.
*   `interfaceName`: Имя реального сетевого интерфейса на узле.

### Шаг 2: Создание `GlobalNetworkPolicy`

Мы создадим две политики с разным `order` (приоритетом). Политики с меньшим `order` применяются раньше.

1.  **Разрешающие правила (order: 10):**

    ```yaml
    # allow-traffic-policy.yaml
    apiVersion: projectcalico.org/v3
    kind: GlobalNetworkPolicy
    metadata:
      name: allow-cluster-traffic
    spec:
      order: 10
      # Применяем к интерфейсам всех наших узлов
      selector: "has(node-endpoint-type)"
      preDNAT: true
      applyOnForward: true
      types:
        - Ingress
        - Egress

      # Разрешаем весь исходящий трафик
      egress:
        - action: Allow

      # Правила для входящего трафика
      ingress:
        # Разрешаем трафик от подов
        - action: Allow
          source:
            nets: ["10.233.0.0/16"] # Замените на ваш Pod CIDR
        # Разрешаем трафик между узлами кластера
        - action: Allow
          source:
            selector: "has(node-endpoint-type)"
        # Разрешаем доступ к Ingress (LoadBalancer IP)
        - action: Allow
          destination:
            nets: ["192.168.218.180/32"] # IP вашего Ingress
            ports: [80, 443]
        # Разрешаем доступ к Kubernetes API (через балансировщик)
        - action: Allow
          destination:
            nets: ["192.168.218.189/32"] # VIP для API
            ports: [7443]
    ```

2.  **Запрещающее правило (order: 20):**
    Эта политика сработает после разрешающей и заблокирует все, что не было разрешено ранее.

    ```yaml
    # default-deny-policy.yaml
    apiVersion: projectcalico.org/v3
    kind: GlobalNetworkPolicy
    metadata:
      name: default-deny
    spec:
      order: 20
      selector: "has(node-endpoint-type)"
      preDNAT: true
      applyOnForward: true
      types:
        - Ingress
      # Явно запрещаем весь остальной входящий трафик
      ingress:
        - action: Deny
    ```

### Шаг 3: Применение

```bash
kubectl apply -f allow-traffic-policy.yaml
kubectl apply -f default-deny-policy.yaml
kubectl apply -f host-endpoints.yaml
```

**Результат:** Трафик извне кластера (кроме разрешенных IP и портов) будет заблокирован на уровне интерфейсов узлов, обеспечивая надежную защиту периметра.

### Проблема с `NodePort`

Как было отмечено в исходном материале, на практике могут возникать сложности с фильтрацией трафика для сервисов типа `NodePort`. Даже при наличии запрещающих правил, трафик на `NodePort` может проходить из-за особенностей его реализации в `iptables` и порядка применения правил. Это требует дополнительного исследования и, возможно, более специфичных правил Calico или настроек на уровне ядра.
