# CNI и kube-proxy: Навигатор

**CNI (Container Network Interface)** и **kube-proxy** — два фундаментальных компонента сетевой модели Kubernetes, обеспечивающих связность подов и абстракцию сервисов.

## Определения

**CNI** — стандартный интерфейс для подключения контейнеров к сети. Отвечает за выделение IP-адресов подам и маршрутизацию трафика между узлами (L2/L3).

**kube-proxy** — сетевой прокси на каждом узле. Реализует абстракцию `Service` через управление правилами в ядре Linux (iptables/IPVS), обеспечивая балансировку нагрузки на уровне L4.

* *Подробные определения и разделение ролей: [CNI и kube-proxy: определения](./CNI/definitions.md)*

## Основные концепции

### Разделение ответственности

| Компонент | Уровень OSI | Задача |
|-----------|-------------|--------|
| **CNI** | L2/L3 | IP-связность Pod-to-Pod, маршрутизация между узлами |
| **kube-proxy** | L4 | Абстракция Service, балансировка трафика Service-to-Pod |

CNI создаёт IP-связность на уровнях L2/L3. `kube-proxy` использует эту связность для предоставления абстракции `Service` и балансировки на уровне L4.

* *Детальное описание: [Разделение ролей CNI и kube-proxy](./CNI/definitions.md#разделение-ролей-cni-flannel-calico-и-kube-proxy)*

### Режимы работы kube-proxy

| Режим | Производительность | Сценарий |
|-------|-------------------|----------|
| **iptables** | O(n) | Кластеры до 1000 сервисов |
| **ipvs** | O(1) | Крупные кластеры (>1000 сервисов) |
| **userspace** | Низкая | Legacy-кластеры |
| **eBPF** | Ядерная | Calico/Cilium с заменой kube-proxy |

* *Подробный обзор IPVS: [IPVS в Kubernetes](./CNI/ipvs.md)*
* *Замена kube-proxy через eBPF: [Решения на базе eBPF](./CNI/ebpf.md)*

## Практические сценарии

### Выбор CNI-плагина

| Плагин | NetworkPolicy | Производительность | Замена kube-proxy |
|--------|---------------|-------------------|-------------------|
| **Flannel** | Нет | Средняя (overlay) | Нет |
| **Calico** | Да | Высокая (BGP) | Нет |
| **Calico (eBPF)** | Да | Очень высокая | Да |
| **Cilium** | Да | Очень высокая | Да |

* *Сравнение и рекомендации: [Выбор CNI и внешние типы доступа](./CNI/selection_and_external_access.md#выбор-cni-плагина)*

### Управление IP-адресами (IPAM)

| Тип IPAM | Описание |
|----------|----------|
| **host-local** | Стандартный механизм Kubernetes, файлы на диске узла |
| **calico-ipam** | Интегрированный в Calico, гибкое управление блоками |
| **dual-stack** | Одновременная поддержка IPv4 и IPv6 |

* *Детали IPAM: [IPAM в CNI](./CNI/ipam.md)*

### Внешний доступ к сервисам

| Метод | Описание |
|-------|----------|
| **NodePort** | Порт на каждой ноде (development) |
| **LoadBalancer** | Внешний балансировщик (production в облаке) |
| **Ingress** | L7-маршрутизация HTTP/HTTPS |
| **IP Advertisement** | Анонсирование ClusterIP через BGP (bare-metal) |

* *DSR через eBPF и IP Advertisement: [Внешние типы доступа](./CNI/selection_and_external_access.md#внешние-типы-доступа-в-kubernetes)*

## Дополнительные сведения

### Диагностика

```bash
# Проверка режима kube-proxy
kubectl -n kube-system get configmap kube-proxy -o yaml | grep mode

# Проверка правил IPVS
ipvsadm -Ln

# Проверка подов CNI
kubectl get pods -n kube-system -l k8s-app=calico-node
```

### Связанные темы

* Сетевая модель Kubernetes — [Обзор сетевой модели](./network_overview.md)
* Фильтрация трафика между подами — [NetworkPolicy](./NetworkPolicy/network_policy.md)
* Абстракция Service — [Обзор Service](../Service/service_overview.md)
* Путь трафика от Ingress до Pod — [Путь трафика в Kubernetes](./traffic_path.md)
