# NetworkPolicy: Лучшие Практики и Дополнительная Информация

## Лучшие практики

* **Начинайте с "Default Deny":** Всегда начинайте с политики, которая блокирует весь трафик для неймспейса, а затем явно разрешайте необходимый.
* **Используйте `NamespaceSelector`:** Для контроля доступа между неймспейсами это надежнее, чем `ipBlock`.
* **Дисциплина меток:** `NetworkPolicy` сильно зависят от корректных меток. Поддерживайте строгую дисциплину маркировки.
* **Разрешайте системный трафик:** Всегда явно разрешайте Egress-трафик к DNS и API Server.
* **Тестируйте:** Используйте временные поды с `curl`, `netcat`, `dig` для проверки связности после применения политик.
* **Используйте логирование:** Некоторые CNI (например, Calico) позволяют логировать заблокированный трафик, что помогает при отладке.

## Дополнительные сведения

### Локальный трафик пода

**NetworkPolicy не ограничивает трафик между контейнерами внутри одного пода**. Они могут свободно общаться через loopback-интерфейс.

### Двусторонний трафик

Для подключения от пода А к поду Б необходимо разрешить трафик **и в `egress`-политике пода А, и в `ingress`-политике пода Б**.

### Диапазоны портов

Для указания диапазона портов можно использовать параметр `endPort`, который указывает конец диапазона включительно:

```yaml
ports:
- protocol: TCP
  port: 30000
  endPort: 30002
```

### Allow-all и Deny-all политики

**Явного правила "deny" в Kubernetes нет**, но можно достичь того же эффекта:

**Deny-all (запрет всего):**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  # ingress: [] — пустой список или отсутствие поля
```

**Разрешить всё (для override):**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-all
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - {} # Пустое правило разрешает весь трафик
```

**Нюанс:** Если `policyTypes` не указан:

* При наличии `ingress`-правил: автоматически добавляется `Ingress`
* При наличии `egress`-правил: автоматически добавляется `Egress`
* Если политик нет: политика не применяется

## Реализация сетевыми плагинами (CNI)

**Критически важно:** NetworkPolicy работает только при наличии CNI-плагина с поддержкой этой функциональности.

| CNI | Поддержка NetworkPolicy | Примечания |
|-----|------------------------|------------|
| **Calico** | ✅ Полная | Расширения: HostEndpoint, GlobalNetworkPolicy, логирование, ICMP |
| **Cilium** | ✅ Полная | Расширения: L7-политики, FQDN-фильтрация, eBPF |
| **Weave Net** | ✅ Полная | Базовая поддержка |
| **Flannel** | ❌ Нет | Только связность подов, без политик |
| **Kube-router** | ✅ Полная | На основе iptables |
| **Antrea** | ✅ Полная | На основе Open vSwitch |

### Стандартная vs расширенная функциональность

Все CNI с поддержкой NetworkPolicy реализуют **базовый стандарт** Kubernetes:

* Селекторы: `podSelector`, `namespaceSelector`, `ipBlock`
* Протоколы: TCP, UDP, SCTP
* policyTypes: Ingress, Egress

**Расширения CNI** (нестандартные, vendor-specific):

* **Calico:**
  * `HostEndpoint` — политики для интерфейсов нод
  * `GlobalNetworkPolicy` — кластерные политики вне namespace
  * `preDNAT` — фильтрация до NAT (для NodePort/LoadBalancer)
  * Логирование заблокированного трафика
  * Блокировка ICMP
* **Cilium:**
  * L7-политики (HTTP, gRPC, Kafka)
  * FQDN-фильтрация (DNS-based)
  * Identity-based политики

> **Важно:** Если вы используете Flannel и создадите NetworkPolicy, ограничения **не будут применены** — трафик продолжит проходить свободно. Требуется замена CNI на поддерживающий политики.

## Связанные темы

* [Сетевая модель Kubernetes](./network_overview.md)
* [Роль CNI и kube-proxy](./cni_kube_proxy_roles.md)
* [Calico HostEndpoint и GlobalNetworkPolicy](../../Security/network_policies/Calico/index.md)
