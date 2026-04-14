# HA кластер Kubernetes: Требования к среде

## Определения

**HA кластер** — отказоустойчивый кластер с несколькими узлами Control Plane, устраняющий единую точку отказа. Архитектура: [HA Cluster Overview](./k8s_ha_cluster_overview.md).

**Control Plane** — плоскость управления Kubernetes: `etcd`, `kube-apiserver`, `kube-controller-manager`, `kube-scheduler`. Подробнее: [Control Plane Architecture](../../Concepts/control_plane_architecture.md).

**CNI (Container Network Interface)** — стандартный плагин для сетевой связности подов между узлами.

---

## Основные концепции

### Аппаратные требования

#### Control Plane узлы (мастеры)

| Ресурс | Минимум | Рекомендация | Примечание |
| :--- | :--- | :--- | :--- |
| **CPU** | 2 ядра | 4+ ядра | Для production — 8+ ядер |
| **RAM** | 2 ГБ | 8+ ГБ | etcd чувствителен к памяти |
| **Disk** | 20 ГБ | 50+ ГБ SSD | etcd требует быстрых дисков |
| **Network** | 1 Гбит/с | 10 Гбит/с | Низкая задержка между мастер-узлами |

**Количество узлов**: 3, 5 или 7 (нечётное для кворума etcd).

#### Worker узлы

| Ресурс | Минимум | Рекомендация | Примечание |
| :--- | :--- | :--- | :--- |
| **CPU** | 2 ядра | 4+ ядра | Зависит от workload |
| **RAM** | 4 ГБ | 8+ ГБ | Для production — 16+ ГБ |
| **Disk** | 20 ГБ | 50+ ГБ SSD | Зависит от требований приложений |
| **Network** | 1 Гбит/с | 10 Гбит/с | Для high-throughput приложений |

#### Балансировщик нагрузки

- **Отдельный узел** или **встроенный** на мастер-узлах (Keepalived + HAProxy)
- **CPU**: 1+ ядро
- **RAM**: 512 МБ+
- **Network**: Статический IP, доступный всем узлам

Подробнее: [Keepalived + HAProxy](../kubeadm/ha_concepts.md).

---

## Практические сценарии

### Программные требования

#### Операционная система

| ОС | Статус | Версия |
| :--- | :--- | :--- |
| **Ubuntu** | Рекомендуется | 22.04 LTS, 24.04 LTS |
| **Debian** | Поддерживается | 11, 12 |
| **CentOS/RHEL** | Поддерживается | 8, 9 |
| **AlmaLinux/Rocky** | Поддерживается | 8, 9 |

**Требования к ОС**:

- Ядро Linux 4.15+ (рекомендуется 5.4+)
- systemd (cgroups v2 для Kubernetes 1.24+)
- Контейнерная среда: `containerd` 1.6+ или `CRI-O`

#### Сетевые требования

**Порты Control Plane**:

| Порт | Протокол | Направление | Назначение |
| :--- | :--- | :--- | :--- |
| 6443 | TCP | Все → Control Plane | Kubernetes API |
| 2379-2380 | TCP | Control Plane ↔ etcd | etcd клиентский и пиринг |
| 10250 | TCP | Control Plane → Nodes | Kubelet API |
| 10251 | TCP | Локально | kube-scheduler healthz |
| 10252 | TCP | Локально | kube-controller-manager healthz |

**Порты Worker Nodes**:

| Порт | Протокол | Направление | Назначение |
| :--- | :--- | :--- | :--- |
| 10250 | TCP | Control Plane → Nodes | Kubelet API |
| 30000-32767 | TCP/UDP | Внешние → Nodes | NodePort Services |

**CNI (Calico пример)**:

| Порт | Протокол | Направление | Назначение |
| :--- | :--- | :--- | :--- |
| 179 | TCP | Nodes ↔ Nodes | BGP пиринг (Calico) |
| 5473 | TCP | Nodes ↔ Nodes | Calico healthz |

Полный список: [Kubernetes Ports and Protocols](https://kubernetes.io/docs/reference/ports-and-protocols/).

#### Подсеть для подов (Pod Network CIDR)

- **Рекомендуемый диапазон**: `192.168.0.0/16` или `10.244.0.0/16`
- **Не должен пересекаться** с:
  - Физической сетью дата-центра
  - Service CIDR (по умолчанию `10.96.0.0/12`)
  - Docker bridge (если используется `172.17.0.0/16`)

---

## Дополнительная информация

### Предварительные требования

**SSH-доступ** с правами `sudo` на все узлы. **Статические IP-адреса** для всех серверов. **DNS или `/etc/hosts`** — разрешение имён между узлами. **Доступ в интернет** или локальный mirror для пакетов Kubernetes. **Временная синхронизация** (NTP/chrony) — критично для etcd.

### Актуальность версий

**Kubernetes** — актуальная версия 1.35 (проверить на [kubernetes.io/releases](https://kubernetes.io/releases/)). **containerd** — 1.6+ совместим с K8s 1.24–1.35. **Calico** — v3.31.x поддерживает K8s 1.29–1.31 (проверить [матрицу совместимости](https://docs.tigera.io/calico/latest/about/supported-releases)). Версии требуют периодической проверки из-за политики N-2 поддержки.

### Интеграция с документацией

Требования к среде — **шаг 1** перед [подготовкой узлов](./k8s_ha_node_preparation.md). Архитектура HA описана в [обзоре кластера](./k8s_ha_cluster_overview.md), теория Control Plane — в [Control Plane architecture](../../Concepts/control_plane_architecture.md), балансировщик — в [Keepalived + HAProxy](../kubeadm/ha_concepts.md), порты — в [Kubernetes Ports and Protocols](https://kubernetes.io/docs/reference/ports-and-protocols/), CNI — в [CNI definitions](../../Networking/Network/CNI/definitions.md).
