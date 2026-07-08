# Kubernetes: Обзор и решаемые проблемы

## Определения

**Kubernetes** (K8s) — открытая платформа для автоматизации развёртывания, масштабирования и управления контейнеризированными приложениями. Оркестрирует контейнеры на кластере хостов, абстрагируя приложения от нижележащей инфраструктуры.

### Исторический контекст

Использование контейнеров опирается на механизмы изоляции ядра Linux: **cgroups** (контрольные группы) и **namespaces** (пространства имён).

- **2002–2009:** Формирование технологий изоляции в ядре Linux.
- **2014:** Популяризация контейнеров компанией **Docker**.
- **2014–2015:** Выход Kubernetes как инструмента для управления множеством контейнеров на группе узлов.

**Кластер Kubernetes** состоит из:

- **Control Plane** (панель управления) — принимает глобальные решения (планирование, состояние). Подробнее: [Архитектура Control Plane](./Concepts/control_plane_architecture.md).
- **Worker Nodes** (рабочие узлы) — узлы, на которых запускаются приложения пользователей.

### Основные решаемые задачи

Главная цель Kubernetes — автоматизация запуска и мониторинга контейнеров на большом количестве узлов.

| # | Задача | Описание |
| :--- | :--- | :--- |
| 1 | **Масштабирование** | Горизонтальное/вертикальное масштабирование контейнеров на множестве хостов |
| 2 | **Балансировка нагрузки** | Автоматическое распределение трафика между Pod |
| 3 | **Service Discovery** | Автоматическое обнаружение сервисов без жёсткого кодирования IP (Internet Protocol) |
| 4 | **Self-healing** | Автоматический перезапуск упавших контейнеров, перенос на исправные узлы |
| 5 | **Удобство управления** | Единая точка входа для управления группой узлов как единым целым |
| 6 | **Управление ресурсами** | Распределение CPU (Central Processing Unit), памяти между приложениями (Requests/Limits) |
| 7 | **Отказоустойчивость** | Автоматическое поддержание желаемого количества реплик приложения |

## Основные концепции

### Декларативный подход

Kubernetes ориентирован на **декларативную парадигму** управления.

- **Императивный подход:** отдача прямых команд («создай файл», «запусти контейнер»).
- **Декларативный подход:** описание **желаемого состояния** в виде спецификации (YAML/JSON). Kubernetes (контроллеры) самостоятельно приводит текущее состояние кластера к желаемому.

### Архитектура кластера

Кластер состоит из двух логических уровней:

#### Control Plane

«Мозг» кластера — принимает решения, хранит состояние, реагирует на события. Включает:

- **`kube-apiserver`** — единая точка входа (REST — Representational State Transfer API Gateway). Все взаимодействия идут через него. Подробнее: [Архитектура Control Plane](./Concepts/control_plane_architecture.md).
- **`etcd`** — согласованное KV (Key-Value) хранилище состояния. Единственный stateful-компонент. Подробнее: [Обзор etcd](./Concepts/etcd_overview.md).
- **`kube-scheduler`** — определяет, на каком узле запустить конкретный Pod. Подробнее: [kube-scheduler](./Concepts/kube_scheduler.md).
- **`kube-controller-manager`** — реализует логику приведения к желаемому состоянию через набор контроллеров. Подробнее: [Архитектура Control Plane](./Concepts/control_plane_architecture.md#kube-controller-manager-цикл-согласования).

#### Worker Nodes

Узлы, на которых запускаются приложения:

- **`kubelet`** — агент-резидент на каждом узле. Получает команды от API (Application Programming Interface) сервера и взаимодействует с Container Runtime. Подробнее: [Kubelet](./Concepts/kubelet.md).
- **`kube-proxy`** — сетевой агент, настраивающий правила маршрутизации на узле. Подробнее: [CNI и kube-proxy](./Networking/Network/CNI/definitions.md).
- **Container Runtime (CRI)** — среда выполнения (`containerd`, `CRI-O`). CRI (Container Runtime Interface) — стандарт взаимодействия. Docker как рантайм деприкейтирован.
- **CNI** (Container Network Interface) — сетевые плагины для обеспечения связности. Подробнее: [Сетевая модель](./Networking/Network/network_overview.md).

### Ключевые абстракции

| Абстракция | Назначение | Основной источник |
| :--- | :--- | :--- |
| **Pod** | Минимальная единица развёртывания — группа контейнеров с общим сетевым пространством | [Pod overview](./Base/Pod/pod_overview.md) |
| **Service** | Стабильная сетевая точка доступа к группе Pod | [Service overview](./Networking/Service/service_overview.md) |
| **Deployment** | Управление желаемым состоянием ReplicaSet и Pod | [Deployment overview](./Base/Deployment/index.md) |
| **Volume / PV / PVC** | Абстракция хранилища, CSI-плагины для внешних СХД | [CSI overview](./Storage/CSI/csi_overview.md) |
| **ConfigMap / Secret** | Управление конфигурацией и секретами | [ConfigMap](./Base/configmap.md) |
| **Namespace** | Виртуальная изоляция групп ресурсов в кластере | [Namespace](./Base/namespace.md) |

### Интерфейсы и стандарты

| Интерфейс | Описание | Основной источник |
| :--- | :--- | :--- |
| **CRI** | Container Runtime Interface — стандартизирует взаимодействие `kubelet` со средой выполнения | [Kubelet](./Concepts/kubelet.md) |
| **CNI** | Container Network Interface — стандарт подключения сетевых плагинов | [CNI definitions](./Networking/Network/CNI/definitions.md) |
| **CSI** | Container Storage Interface — стандарт подключения систем хранения | [CSI overview](./Storage/CSI/csi_overview.md) |

### Kubernetes и CNCF

Kubernetes — флагманский проект **CNCF** (Cloud Native Computing Foundation), некоммерческой организации под эгидой The Linux Foundation. Статус в CNCF гарантирует долгосрочную поддержку и открытое управление.

Сопутствующие проекты CNCF: `etcd` (хранилище), `Prometheus` (мониторинг), `Helm` (пакетный менеджер), `containerd` (среда выполнения).

## Практические сценарии

### Жизненный цикл создания Pod

Полный пошаговый сценарий создания: `kubectl` → `kube-apiserver` → `etcd` → `kube-scheduler` → `kubelet` → Container Runtime.

Подробное описание: [Жизненный цикл Pod](./Concepts/control_plane_architecture.md#жизненный-цикл-создания-пода).

### Когда использовать Kubernetes

- **Микросервисная архитектура:** автоматическое масштабирование, self-healing, service discovery.
- **Высокая доступность:** автоматический перезапуск, rolling updates.
- **Мультиоблачные развёртывания:** абстракция от инфраструктуры, единый API.
- **Частые релизы (CI/CD — Continuous Integration / Continuous Deployment):** бесшовные обновления, откаты.

### Когда Kubernetes может быть избыточен

- **Монолитное приложение:** без планов декомпозиции (Docker Compose достаточно).
- **Небольшая команда:** редкие релизы, отсутствие экспертизы.
- **Простые Stateless-приложения:** когда достаточно облачного балансировщика и VM (Virtual Machine).

### Способы развёртывания кластера

**Для разработки и тестирования:**

| Инструмент | Назначение | Особенность |
|:-----------|:-----------|:------------|
| **[minikube](./Installation/minikube/minikube_practical_scenarios.md)** | Локальная разработка | VM с полноценным K8s, встроенные аддоны |
| **[kind](./Installation/kind/kind_concepts.md)** | CI/CD, тестирование | K8s в Docker (контейнер внутри контейнера) |
| **[MicroK8s](./Installation/microk8s/microk8s_overview.md)** | Home lab, edge | Snap-пакет, встроенные аддоны |
| **[Talos Linux](./Installation/local_cluster_with_talosctl.md)** | Безопасные кластеры | Иммутабельная ОС, mTLS, нет SSH |

**Для production и home lab:**

| Инструмент | Назначение | Особенность |
|:-----------|:-----------|:------------|
| **[k3s](./Installation/k3s_dev_environment/k3s_architecture.md)** | Edge, IoT, слабые VPS | Один бинарник <100 МБ, ~512 МБ RAM |
| **[kubeadm](./Installation/kubeadm/index.md)** | Bare-metal, облачные VM | Официальный инструмент инициализации |
| **Managed Cloud (GKE, EKS, AKS, Yandex)** | Production в облаке | Control Plane управляется провайдером |

**Managed Kubernetes (облачные решения):**

Управляемые кластеры делегируют обслуживание Control Plane провайдеру: мастер-узлы, etcd, сертификаты, бэкапы. Зона ответственности пользователя — worker-ноды и деплой приложений.

Ключевые возможности:
- Автоматическое масштабирование worker-нод при росте нагрузки
- Автоматическое обновление версии Kubernetes
- Встроенная интеграция с облачными балансировщиками (Service Type LoadBalancer → внешний LB)
- Управляемое хранилище (PVC → облачный диск)
- Spot-инстансы для экономии — ноды могут быть выключены провайдером в любой момент; требуется минимум 2 реплики на разных нодах

**Экзотические варианты:**

- **NixOS:** декларативная ОС с пакетным менеджером Nix. Позволяет развернуть кластер через Nix-пакеты компонентов K8s по принципу infrastructure-as-code.
- **Kubespray:** набор Ansible-плейбуков на основе kubeadm для автоматизации жизненного цикла кластера. См. [Kubespray](./Installation/Kubespray/overview.md).

## Дополнительная информация

### Инструменты взаимодействия

Все взаимодействия с кластером сводятся к запросам к **kube-apiserver**.

| Инструмент | Тип | Назначение |
| :--- | :--- | :--- |
| **kubectl** | CLI (Command Line Interface) | Основной инструмент управления. |
| **Lens** | GUI (Graphical User Interface) | Графическая IDE для визуализации ресурсов. Подробнее: [Lens](./ToolsUtilities/lens/definitions_and_concepts.md). |
| **K9s** | TUI (Terminal User Interface) | Терминальный интерфейс для мониторинга. |

### Связанные темы

- [HA-кластер на Bare Metal](./Installation/HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md)
- [Установка через kubeadm](./Installation/kubeadm/index.md)
- [Minikube (локальный кластер)](./Installation/minikube/minikube_practical_scenarios.md)
