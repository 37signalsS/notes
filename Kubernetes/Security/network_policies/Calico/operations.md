# Операции Calico: Диагностика, мониторинг и обслуживание

В данном разделе описаны процедуры проверки состояния, отладки и технического обслуживания сетевой инфраструктуры Calico. Основное внимание уделено современным режимам работы (eBPF), управлению IP-адресами (IPAM) и обеспечению безопасности узлов.

> Основная документация и концепции: [Calico HostEndpoint и GlobalNetworkPolicy](./index.md)

## Определения

**Calico Operations** — комплекс регламентированных процедур для обеспечения жизненного цикла сетевой подсистемы Calico, включающий мониторинг, резервное копирование и устранение инцидентов.

**Data Plane (Плоскость данных)** — механизм обработки пакетов на узлах. Calico поддерживает:
* **Standard (iptables)**: Традиционный режим.
* **eBPF**: Высокопроизводительный режим, заменяющий kube-proxy.
* **VPP**: Режим на основе векторной обработки пакетов (для специфичных высоконагруженных задач).

**IPAM (IP Address Management)** — подсистема управления пулами IP-адресов. Calico использует собственные механизмы для выделения блоков IP-адресов узлам (IP Pools и Blocks).

**WireGuard** — протокол шифрования трафика между узлами (Node-to-Node encryption), интегрированный в Calico.

**Failsafe Ports** — предопределенный список портов в `FelixConfiguration`, которые остаются открытыми даже при наличии блокирующих политик для предотвращения самоблокировки административного доступа (SSH, BGP, K8s API).

## Основные концепции

### Инструментарий и диагностические данные

1. **calicoctl**: Основная утилита для работы с объектами `projectcalico.org/v3`. Позволяет управлять ресурсами, недоступными через стандартный `kubectl`.
2. **Felix**: Агент на каждом узле. Его состояние критично для применения политик. Felix экспортирует метрики в формате Prometheus.
3. **Typha**: Опциональный компонент-агрегатор для снижения нагрузки на Kubernetes API в больших кластерах (>50 узлов).
4. **BGP (Border Gateway Protocol)**: Используется для распространения маршрутов между узлами в режиме Standard. В режиме eBPF может быть опциональным.

### Режимы Data Plane и их особенности

| Режим | Инструмент диагностики | Преимущества |
| :--- | :--- | :--- |
| **Standard** | `iptables-save`, `calicoctl node status` | Совместимость со старыми ядрами, предсказуемость. |
| **eBPF** | `bpftool`, `calico-node -bpf counters dump` | Высокая производительность, сохранение Source IP для NodePort, Direct Server Return (DSR). |
| **nftables** | `nft list ruleset` | Поддержка в новых дистрибутивах Linux (Debian 12+, RHEL 9+). |

## Практические сценарии

### Диагностика в режиме eBPF

Если в кластере включен eBPF, стандартные правила `iptables` отсутствуют. Для отладки используйте внутренние команды контейнера `calico-node`:

```bash
# Проверка, что eBPF активен
kubectl logs -n calico-system ds/calico-node -c calico-node | grep "BPF enabled"

# Дамп счетчиков eBPF (пакеты, сбросы, пропуски)
kubectl exec -it -n calico-system <calico-node-pod> -- calico-node -bpf counters dump

# Просмотр примененных политик к конкретному интерфейсу
kubectl exec -it -n calico-system <calico-node-pod> -- calico-node -bpf policy dump <iface-name> ingress
```

### Управление и очистка IPAM

Проблемы с "утечкой" IP-адресов (IP leaks) возникают при некорректном удалении узлов или сбоях в работе CNI.

```bash
# Проверка консистентности выделенных IP-адресов
calicoctl ipam check -o report.json

# Освобождение неиспользуемых (утекших) адресов на основе отчета
calicoctl ipam release --from-report=report.json

# Просмотр текущих блоков IP-адресов
calicoctl ipam show --show-blocks
```

### Мониторинг и метрики (Prometheus)

Для сбора метрик Felix и Typha необходимо включить их в конфигурации:

```bash
# Включение метрик Felix (по умолчанию порт 9091)
calicoctl patch felixconfiguration default --patch '{"spec": {"prometheusMetricsEnabled": true}}'

# Проверка метрик с узла
curl http://localhost:9091/metrics
# → Ожидаемые метрики: felix_active_local_endpoints, felix_execution_time_seconds
```

### Резервное копирование ресурсов Calico

Рекомендуется регулярно экспортировать конфигурацию, которая не управляется через GitOps (например, динамические IPAM-блоки):

```bash
# Резервное копирование основных ресурсов
calicoctl get ippool -o yaml > calico-ippools.yaml
calicoctl get globalnetworkpolicy -o yaml > calico-gnp.yaml
calicoctl get hostendpoint -o yaml > calico-hep.yaml
```

### Проверка статуса WireGuard

Если включено шифрование, проверьте наличие публичных ключей у узлов:

```bash
# Проверка ключей на всех узлах
calicoctl get nodes -o wide
# → В выводе должен присутствовать столбец или поле с публичным ключом WireGuard

# Проверка трафика через метрики
# В Prometheus ищите: wireguard_sent_bytes_total
```

## Устранение неисправностей (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Потеря SSH-доступа** | HostEndpoint заблокировал порт 22 | Проверьте `FailsafePorts` в `FelixConfiguration` или создайте GlobalNetworkPolicy с разрешением порта 22. |
| **Timeout в eBPF режиме** | Ядро Linux < 5.3 или не смонтирована BPF FS | Убедитесь, что `/sys/fs/bpf` смонтирована на всех узлах. Проверьте версию ядра (`uname -r`). |
| **NodePort не работает** | Конфликт с kube-proxy или отсутствие `preDNAT` | В eBPF режиме Calico должен полностью заменять kube-proxy. В Standard режиме добавьте `preDNAT: true` в политику. |
| **Ошибка BGP (Connection Refused)** | Закрыт порт 179/TCP | Разрешите 179/TCP между всеми IP узлов. Проверьте статус: `calicoctl node status`. |
| **Несоответствие MTU** | Инкапсуляция (VXLAN/IPIP) | MTU в `FelixConfiguration` должен быть на 20-50 байт меньше физического интерфейса (например, 1450). |

## Дополнительная информация

### Связанные ресурсы
* **Практические сценарии**: [Сценарии Calico: Периметральный файрвол](./scenarios.md).
* **Архитектура**: [Calico HostEndpoint и GlobalNetworkPolicy — Обзор](./index.md).
* **Сетевая модель K8s**: [Обзор сетевой модели Kubernetes](../../../Networking/Network/network_overview.md).
* **eBPF Технологии**: [eBPF в Kubernetes: Замена kube-proxy](../../../Networking/Network/CNI/ebpf.md).
* **IPAM Детали**: [IPAM (IP Address Management) в Kubernetes](../../../Networking/Network/CNI/ipam.md).

### Инструменты отладки (CLI)
* **calicoctl**: [Официальная документация calicoctl](https://docs.tigera.io/calico/latest/reference/calicoctl/).
* **bpftool**: Системная утилита для инспекции BPF программ (требует `linux-tools-common`).
