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

Полный процесс развёртывания включает 8 шагов. Детальные инструкции — в соответствующих руководствах:

1. **Подготовка узлов** — настройка ОС, cgroups, sysctl ([требования](./k8s_ha_environment_requirements.md), [подготовка](./k8s_ha_node_preparation.md))
2. **Установка containerd** — настройка CRI ([инструкция](./k8s_ha_component_installation.md))
3. **Установка kubeadm/kubelet/kubectl** — установка компонентов
4. **Настройка балансировщика** — Keepalived + HAProxy для VIP ([инструкция](../kubeadm/ha_keepalived_haproxy/ha_concepts.md))
5. **Инициализация первого мастера** — `kubeadm init` с `--control-plane-endpoint` ([инструкция](./control_plane_initialization.md))
6. **Установка CNI** — Calico или другой плагин ([инструкция](./cni_installation.md))
7. **Присоединение мастеров** — `kubeadm join` с `--control-plane` ([инструкция](./node_joining.md))
8. **Присоединение воркеров** — `kubeadm join` без дополнительных флагов

**Важно**: CIDR для подов и сервисов выбираются на шаге 5. Диапазоны не должны пересекаться с существующей инфраструктурой. Подробнее: [Выбор CIDR](./control_plane_initialization.md#выбор-cidr-для-подов-и-сервисов).

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

Подробнее: [Обслуживание узлов](../../Operations/node_maintenance.md).

---

## Дополнительная информация

### Отладка проблем HA

```bash
# Проверка статуса VIP (на любом узле с Keepalived)
ip addr show | grep <VIP>

# Проверка состояния Keepalived
systemctl status keepalived
journalctl -u keepalived -f

# Проверка HAProxy
systemctl status haproxy
echo "show stat" | socat /var/run/haproxy.sock stdio

# Проверка кворума etcd
etcdctl --endpoints=https://<VIP>:2379 endpoint health
etcdctl --endpoints=https://<VIP>:2379 member list

# Проверка статуса Control Plane
kubectl get --raw='/readyz?verbose'
kubectl get --raw='/healthz?verbose'
```

**Типичные проблемы:**

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `VIP не доступен` | Keepalived не запущен | `systemctl start keepalived` |
| `etcd lost quorum` | Отказ ≥2 мастеров | Восстановить узлы или форсировать кворум |
| `HAProxy 503` | Бэкенды недоступны | Проверить `kube-apiserver` на мастерах |
| `VRRP advertisement` | Блокировка firewall | Разрешить протокол 112 (VRRP) |

### Интеграция с документацией

Архитектура HA описана в этом файле. Требования к среде — в [environment requirements](./k8s_ha_environment_requirements.md), подготовка узлов — в [node preparation](./k8s_ha_node_preparation.md). Практические инструкции: [component installation](./k8s_ha_component_installation.md), [control plane initialization](./control_plane_initialization.md), [CNI installation](./cni_installation.md), [node joining](./node_joining.md), [cluster verification](./k8s_ha_cluster_verification.md). Теория: [HA overview](../../../Concepts/High_Availability/ha_overview.md), [Control Plane architecture](../../Concepts/control_plane_architecture.md), [etcd overview](../../Concepts/etcd_overview.md). Альтернативный подход: [Kubespray HA](../Kubespray/HA/index.md).
