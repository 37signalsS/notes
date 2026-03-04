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

Подробнее: [Keepalived + HAProxy](../kudeadm/kubeadm_ha_with_keepalived_haproxy.md).

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

1. **SSH-доступ** с правами `sudo` на все узлы
2. **Статические IP-адреса** для всех серверов
3. **DNS или `/etc/hosts`** — разрешение имён между узлами
4. **Доступ в интернет** или локальный mirror для пакетов Kubernetes
5. **Временная синхронизация** (NTP/chrony) — критично для etcd

### Проверка совместимости версий

| Компонент | Версия в файлах | Актуальность | Примечание |
| :--- | :--- | :--- | :--- |
| **Kubernetes** | 1.34 | ⚠️ Проверить | На март 2026 — уточнить актуальность |
| **containerd** | 1.6+ | ✅ | Совместим с K8s 1.24-1.34 |
| **Calico** | v3.31.0 | ⚠️ Проверить | Поддерживает K8s 1.28-1.32 |

> **Важно**: Версии указаны на момент создания документации. Проверяйте совместимость в официальной документации перед установкой.

### Связанные документы

- **Обзор HA**: [HA Cluster Overview](./k8s_ha_cluster_overview.md)
- **Подготовка узлов**: [Node Preparation](./k8s_ha_node_preparation.md)
- **Установка компонентов**: [Component Installation](./k8s_ha_component_installation.md)
- **Порты**: [Kubernetes Ports](https://kubernetes.io/docs/reference/ports-and-protocols/)
- **CNI**: [CNI Plugins](../../Networking/Network/cni_overview.md)

### Надежность

| Раздел | SSoT | Confidence |
| :--- | :--- | :--- |
| Аппаратные требования | Этот файл | 9 |
| Сетевые требования | Этот файл + официалка | 10 |
| Версии компонентов | Требует проверки | 7 |
