# Высокая доступность Kubernetes на Bare-Metal: Обзор

## Определения

**Bare-Metal** — физические серверы без гипервизора. Обеспечивают максимальную производительность, но требуют ручного управления инфраструктурой и отказами.

**kubeadm** — официальный инструмент для bootstrapping production-ready кластеров Kubernetes. Фокус на командах `init` и `join`. Подробнее: [kubeadm quickstart](../kubeadm/ha_keepalived_haproxy/index.md).

**containerd** — высокоуровневая CRI-совместимая среда выполнения контейнеров. Проект CNCF, стандарт для Kubernetes. Подробнее: [Альтернативные среды выполнения](../../../Docker/alternative_runtimes_and_tools.md).

**Высокая доступность (High-Availability, HA)** — свойство системы непрерывно выполнять функции при отказах компонентов. Достигается дублированием Control Plane и использованием балансировщика. Базовые концепции: [HA Overview](../../../Concepts/High_Availability/ha_overview.md).

**CRI (Container Runtime Interface)** — API Kubernetes для взаимодействия `kubelet` со средами выполнения (`containerd`, `CRI-O`). Спецификация: [CRI и OCI](../../../Docker/alternative_runtimes_and_tools.md#стандарты-cri-и-oci).

**Control Plane Endpoint** — стабильная точка входа (VIP:PORT или DNS) для доступа к API-серверу через балансировщик нагрузки.

---

## Основные концепции

### Архитектура HA кластера

Для bare-metal используется схема **stacked Control Plane**: `etcd` и компоненты Control Plane размещаются на одних узлах.

#### Ключевые компоненты

1. **Балансировщик нагрузки (L4 Load Balancer)**
   - Распределяет TCP-трафик на порт `6443` между всеми `kube-apiserver`
   - Примеры: HAProxy, Nginx, F5, облачные NLB
   - Должен быть отказоустойчивым (например, связка Keepalived + HAProxy)
   - Подробнее: [Keepalived + HAProxy для HA](../kubeadm/ha_keepalived_haproxy/index.md)

2. **Виртуальный IP (VIP)**
   - "Плавающий" IP, не привязанный к одному серверу
   - Мигрирует между узлами при отказе (протокол VRRP через Keepalived)
   - Все клиенты (`kubectl`, `kubelet`, `kubeadm join`) используют VIP

3. **Control Plane Nodes (мастер-узлы)**
   - Минимум **3 узла** для кворума etcd
   - Нечётное количество: 3, 5, 7 (требование алгоритма Raft)
   - Каждый запускает: `etcd`, `kube-apiserver`, `kube-controller-manager`, `kube-scheduler`

4. **Worker Nodes (рабочие узлы)**
   - Подключаются через VIP к Control Plane
   - Запускают пользовательские workload в подах

### Топологии Control Plane

| Топология | Описание | Применение |
| :--- | :--- | :--- |
| **Stacked etcd** | `etcd` на тех же узлах, что и Control Plane | Стандарт для kubeadm, меньше серверов |
| **External etcd** | `etcd` на выделенных узлах | Production с высокими требованиями |

Подробнее: [Архитектура Control Plane](../../Concepts/control_plane_architecture.md), [etcd overview](../../Concepts/etcd_overview.md).

### Почему 3 мастер-узла?

- **Кворум etcd**: `(N/2) + 1` — большинство для записи
- **3 узла**: переживают отказ 1 узла
- **5 узлов**: переживают отказ 2 узлов
- **Чётное число**: не добавляет отказоустойчивости, но требует больше ресурсов

---

## Практические сценарии

### Этапы развёртывания HA кластера

1. **Подготовка узлов** — настройка ОС, cgroups, sysctl на всех узлах
2. **Установка containerd** — настройка CRI для Kubernetes
3. **Установка kubeadm/kubelet/kubectl** — установка компонентов на всех узлах
4. **Настройка балансировщика** — Keepalived + HAProxy для VIP
5. **Инициализация первого мастера** — `kubeadm init` с `--control-plane-endpoint`
6. **Установка CNI** — Calico или другой плагин для сети подов
7. **Присоединение мастеров** — `kubeadm join` с `--control-plane`
8. **Присоединение воркеров** — `kubeadm join` без дополнительных флагов

Подробнее: [Node Preparation](./k8s_ha_node_preparation.md), [Control Plane & CNI](./k8s_ha_control_plane_and_cni.md).

### Выбор CIDR для подов и сервисов

При инициализации кластера необходимо выбрать диапазоны IP-адресов, **не пересекающиеся** с существующей инфраструктурой:

| Параметр | Назначение | Рекомендуемые значения | Примечание |
| :--- | :--- | :--- | :--- |
| `--pod-network-cidr` | IP-адреса для подов | `100.64.0.0/16`, `10.244.0.0/16` | Должен совпадать с настройками CNI |
| `--service-cidr` | IP-адреса для сервисов | `100.65.0.0/16`, `10.96.0.0/12` | По умолчанию `10.96.0.0/12` |

> **Важно**: Изменение CIDR после инициализации невозможно без полной пересоздания кластера.

### Сценарий 1: Отказ одного мастер-узла

1. Keepalived обнаруживает отказ через VRRP heartbeat
2. VIP мигрирует на резервный узел (MASTER → BACKUP)
3. HAProxy исключает отказавший узел из ротации (health check)
4. `kubelet` на worker-узлах переподключается к новому MASTER
5. `etcd` сохраняет кворум (2 из 3), запись продолжается

### Сценарий 2: Плановое обслуживание

1. Дренаж узла: `kubectl drain <node> --ignore-daemonsets`
2. Остановка сервисов на узле
3. Обновление/ремонт
4. Возврат в кластер: `kubectl uncordon <node>`

Подробнее: [Обслуживание узлов](../../Maintenance/node_maintenance.md).

---

## Дополнительная информация

### Связанные документы

- **Требования**: [Environment Requirements](./k8s_ha_environment_requirements.md)
- **Подготовка**: [Node Preparation](./k8s_ha_node_preparation.md)
- **Установка**: [Component Installation](./k8s_ha_component_installation.md)
- **Control Plane**: [Control Plane & CNI](./k8s_ha_control_plane_and_cni.md)
- **Проверка**: [Cluster Verification](./k8s_ha_cluster_verification.md)
- **Альтернатива**: [Kubespray HA](../Kubespray/HA/index.md)
- **Keepalived + HAProxy**: [HA с kubeadm](../kubeadm/ha_keepalived_haproxy/index.md)
- **Теория HA**: [High Availability Overview](../../../Concepts/High_Availability/ha_overview.md)
- **Control Plane**: [Архитектура](../../Concepts/control_plane_architecture.md)
- **etcd**: [Обзор](../../Concepts/etcd_overview.md)

### Надежность

| Компонент | Confidence |
| :--- | :--- |
| Архитектура HA | Этот файл | 10 |
| Балансировка | [kubeadm_ha_with_keepalived_haproxy/index.md](../kubeadm/ha_keepalived_haproxy/index.md) | 10 |
| etcd кворум | [etcd_overview.md](../../Concepts/etcd_overview.md) | 10 |
