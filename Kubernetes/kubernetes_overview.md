# Kubernetes: Обзор и решаемые проблемы

## Definitions

**Kubernetes** (K8s) — открытая платформа для автоматизации развёртывания, масштабирования и управления контейнеризированными приложениями. Оркестрирует контейнеры на кластере хостов, абстрагируя приложения от нижележащей инфраструктуры.

**Кластер Kubernetes** состоит из:
- **Control Plane** — плоскость управления, принимающая глобальные решения (планирование, состояние). Подробнее: [Архитектура Control Plane](./Concepts/control_plane_architecture.md).
- **Worker Nodes** — рабочие узлы, на которых запускаются приложения пользователей.

### Основные решаемые задачи

| # | Задача | Описание |
| :--- | :--- | :--- |
| 1 | **Масштабирование** | Горизонтальное/вертикальное масштабирование контейнеров на множестве хостов |
| 2 | **Балансировка нагрузки** | Автоматическое распределение трафика между подами |
| 3 | **Service Discovery** | Автоматическое обнаружение сервисов без жёсткого кодирования IP |
| 4 | **Self-healing** | Автоматический перезапуск упавших контейнеров, перенос на исправные узлы |
| 5 | **Rolling updates / Rollbacks** | Бесшовное обновление и откат версий приложений |
| 6 | **Управление ресурсами** | Распределение CPU, памяти между приложениями (Requests/Limits) |
| 7 | **Config & Secrets** | Безопасное хранение и предоставление конфигурации и секретов |
| 8 | **Мониторинг и логирование** | Интеграция с внешними системами наблюдения за кластером |
| 9 | **CI/CD** | Упрощение автоматизации непрерывной интеграции и доставки |
| 10 | **Vendor Lock-in reduction** | Абстракция от конкретного облачного провайдера через единый API |

## Basic Concepts

### Архитектура кластера

Кластер Kubernetes состоит из двух логических уровней:

#### Control Plane

«Мозг» кластера — принимает решения, хранит состояние, реагирует на события. Включает:

- **`kube-apiserver`** — единая точка входа для всех операций управления через API. Подробнее: [Архитектура Control Plane](./Concepts/control_plane_architecture.md).
- **`etcd`** — распределённое согласованное хранилище «ключ-значение», Single Source of Truth кластера. Подробнее: [Обзор etcd](./Concepts/etcd_overview.md).
- **`kube-scheduler`** — назначение подов на узлы на основе ресурсов и ограничений. Подробнее: [kube-scheduler](./Concepts/kube_scheduler.md).
- **`kube-controller-manager`** — запускает контроллеры, приводящие фактическое состояние к желаемому (reconciliation loop).

#### Worker Nodes

Узлы, на которых запускаются приложения:

- **`kubelet`** — агент на каждом узле, управляющий жизненным циклом подов через CRI. Подробнее: [Kubelet](./Concepts/kubelet.md).
- **`kube-proxy`** — сетевой прокси, реализующий абстракцию `Service` (L4). Подробнее: [CNI и kube-proxy](./Networking/Network/CNI/definitions.md).
- **Container Runtime (CRI)** — среда выполнения контейнеров (`containerd`, `CRI-O`), запускающая и управляющая контейнерами через CRI-интерфейс.
- **CNI (Container Network Interface)** — сетевые плагины (Calico, Cilium, Flannel), обеспечивающие связность подов и сетевые политики. Подробнее: [Сетевая модель](./Networking/Network/network_overview.md).

### Ключевые абстракции

| Абстракция | Назначение | SSoT-файл |
| :--- | :--- | :--- |
| **Pod** | Минимальная единица развёртывания — группа контейнеров с общим сетевым пространством и хранилищем | [Pod overview](./Base/Pod/pod_overview.md) |
| **Service** | Стабильная сетевая точка доступа к группе подов | [Сетевая модель](./Networking/Network/network_overview.md) |
| **Deployment** | Управление желаемым состоянием ReplicaSet и Pod | [control_plane_architecture](./Concepts/control_plane_architecture.md) |
| **Volume / PV / PVC** | Абстракция хранилища, CSI-плагины для внешних СХД | [CSI overview](./Storage/CSI/csi_overview.md) |
| **ConfigMap / Secret** | Управление конфигурацией и секретами | — |
| **Namespace** | Виртуальная изоляция групп ресурсов в кластере | [namespace](./Base/namespace.md) |

### Интерфейсы и стандарты

| Интерфейс | Описание | SSoT-файл |
| :--- | :--- | :--- |
| **CRI** | Container Runtime Interface — стандартизирует взаимодействие `kubelet` со средой выполнения контейнеров | [Kubelet](./Concepts/kubelet.md) |
| **CNI** | Container Network Interface — стандарт подключения сетевых плагинов | [CNI definitions](./Networking/Network/CNI/definitions.md) |
| **CSI** | Container Storage Interface — стандарт подключения систем хранения | [CSI overview](./Storage/CSI/csi_overview.md) |

### Kubernetes и CNCF

Kubernetes — флагманский проект [Cloud Native Computing Foundation (CNCF)](https://www.cncf.io/), некоммерческой организации под эгидой The Linux Foundation. Статус в CNCF гарантирует долгосрочную поддержку и открытое управление.

Сопутствующие проекты CNCF: `etcd` (хранилище), `Prometheus` (мониторинг), `Helm` (пакетный менеджер), `containerd` (среда выполнения).

## Practical Scenarios

### Жизненный цикл создания Pod

Полный пошаговый сценарий создания пода: `kubectl` → `kube-apiserver` → `etcd` → `kube-scheduler` → `kubelet` → Container Runtime.

Подробное описание: [Жизненный цикл Pod](./Concepts/control_plane_architecture.md#жизненный-цикл-создания-пода).

### Когда использовать Kubernetes

| Сценарий | Обоснование |
| :--- | :--- |
| Микросервисная архитектура с десятками/сотнями сервисов | Автоматическое масштабирование, self-healing, service discovery |
| Высокие требования к доступности (99.9%+) | Автоматический перезапуск, распределение по узлам, rolling updates |
| Мультиоблачные / гибридные развёртывания | Абстракция от инфраструктуры, единый API |
| Частые релизы (CI/CD) | Бесшовные обновления, откаты, Canary-развёртывание |

### Когда Kubernetes может быть избыточен

| Сценарий | Альтернатива |
| :--- | :--- |
| Монолитное приложение без планов декомпозиции | Виртуальная машина, Docker Compose |
| Небольшая команда, редкие релизы | PaaS (Heroku, Render), Docker Compose |
| Stateless-приложение с простой балансировкой | Облачный Load Balancer + VM/контейнеры без оркестрации |

## Additional Information

### Полезные ресурсы

Интерактивная карта экосистемы Cloud Native: [CNCF Landscape](https://landscape.cncf.io/) — поиск ПО по категориям.

Анализ зрелости технологий на основе данных от конечных пользователей: [CNCF Radar](https://radar.cncf.io/).

### Связанные темы

- HA-кластер на Bare Metal: [k8s_ha_cluster_overview.md](./Installation/HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md)
- Установка через kubeadm: [kubeadm index](./Installation/kubeadm/index.md)
- Minikube (локальный кластер): [minikube_practical_scenarios.md](./Installation/minikube/minikube_practical_scenarios.md)
- OpenShift (дистрибутив Red Hat): [openshift_overview.md](./openshift_overview.md)
