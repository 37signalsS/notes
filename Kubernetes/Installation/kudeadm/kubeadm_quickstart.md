# Быстрый старт с kubeadm

## 1. Определения

| Термин | Описание |
| :--- | :--- |
| **kubeadm** | Официальный инструмент CLI для инициализации (bootstrapping) production-ready кластеров Kubernetes. Фокус на командах `init` и `join`. |
| **kubelet** | Агент, запускающийся на каждом узле кластера. См. [kubelet](../../Concepts/control_plane_architecture.md#kubelet). |
| **kubectl** | CLI-инструмент для взаимодействия с API-сервером Kubernetes и управления объектами кластера. |
| **Bootstrapping** | Процесс первоначальной загрузки кластера: развёртывание Control Plane, присоединение узлов, установка CNI. |
| **Control Plane** | Управляющая плоскость Kubernetes (API Server, etcd, Controller Manager, Scheduler). |
| **CNI (Container Network Interface)** | Сетевой плагин для обеспечения коммуникации между подами на разных узлах (Calico, Flannel, Cilium). |

## 2. Основные концепции

### 2.1. Жизненный цикл кластера с kubeadm

| Аспект | Описание |
| :--- | :--- |
| **В зоне ответственности** | Команды `init` (создание Control Plane), `join` (присоединение узлов), управление токенами, сертификатами, фичами. |
| **Вне зоны ответственности** | Подготовка инфраструктуры (ВМ, сеть), установка зависимостей (containerd, Docker), управление кластером после создания, установка CNI. |

### 2.2. Рабочий процесс

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ 1. Подготовка   │ →  │ 2. kubeadm init  │ →  │ 3. Установка    │ →  │ 4. kubeadm join │
│    узлов        │    │    (master)      │    │    CNI          │    │    (workers)    │
└─────────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
```

1. **Подготовка узлов**: Установка container runtime (containerd/Docker), `kubeadm`, `kubelet`, `kubectl` на всех узлах.
2. **Инициализация master**: `kubeadm init` развёртывает Control Plane как статические поды (`etcd`, `kube-apiserver`, `kube-controller-manager`, `kube-scheduler`).
3. **Установка CNI**: Без сетевого плагина поды не перейдут в статус `Ready`. Популярные варианты: [Calico](../../Networking/Network/cni_overview.md#calico), [Flannel](../../Networking/Network/cni_overview.md#flannel), [Cilium](../../Networking/Network/cni_overview.md#cilium).
4. **Присоединение workers**: `kubeadm join` с токеном подключает узлы к кластеру.

### 2.3. Версии Kubernetes

| Компонент | Версия | Поддерживаемые версии |
| :--- | :--- | :--- |
| **Kubernetes** | 1.33 | 1.31, 1.32, 1.33 |
| **kubeadm** | 1.33 | Соответствует версии K8s |
| **kubelet** | 1.33 | Соответствует версии K8s |
| **kubectl** | 1.33 | Совместим с ±1 версией API |

> **Важно:** `kubeadm` поддерживает установку только последних 3 версий Kubernetes. Проверка актуальной версии: [kubernetes.io/releases](https://kubernetes.io/releases/).

## 3. Практические сценарии

| Сценарий | Файл | Описание |
| :--- | :--- | :--- |
| **Одно-мастерный кластер** | [kubeadm_cluster_creation.md](./kubeadm_cluster_creation.md) | Базовая установка для dev/test сред. |
| **HA кластер (Keepalived + HAProxy)** | [kubeadm_ha_with_keepalived_haproxy.md](./kubeadm_ha_with_keepalived_haproxy.md) | Production-кластер с балансировкой API Server. |
| **Управление узлами** | [kubeadm_node_management.md](./kubeadm_node_management.md) | Добавление/удаление worker и control-plane узлов. |
| **Управление сертификатами** | [../../Operations/certificate_management.md](../../Operations/certificate_management.md) | Проверка и ротация сертификатов. |
| **Управление RKE кластером** | [kubeadm_rke_management.md](./kubeadm_rke_management.md) | Работа с кластерами, развёрнутыми через Rancher. |

## 4. Дополнительная информация

### 4.1. Связанные темы

* [Архитектура Control Plane](../../Concepts/control_plane_architecture.md)
* [Высокая доступность Kubernetes](../../Base/high_availability.md)
* **HA с Keepalived + HAProxy](./kubeadm_ha_with_keepalived_haproxy.md)** — подробное руководство по HA
* [Kubespray — автоматизация через Ansible](../Kubespray/overview.md)
* [HA кластер на bare metal](../HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md)
* **[kind](../kind_quickstart.md)** — локальные кластеры в Docker
* **[Talos](../local_cluster_with_talosctl.md)** — безопасная ОС для K8s

### 4.2. Ограничения kubeadm

* Не управляет инфраструктурой (ВМ, сеть, балансировщики).
* Не предоставляет механизм обновления версий K8s "в один клик" (требуется `kubeadm upgrade`).
* Требует ручной настройки HA для production.
* Сертификаты действительны 1 год (требуется ротация).

### 4.3. Альтернативы

| Инструмент | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Kubespray** | Ansible-плейбуки для развёртывания kubeadm | Production, много кластеров, декларативный подход. |
| **k3s** | Легковесный дистрибутив K8s от Rancher. Упакован в один бинарный файл. Заменяет etcd на SQLite (по умолчанию) и включает встроенный Ingress-контроллер (Traefik). | Edge, IoT, CI, локальная разработка. Среды с ограниченными ресурсами. Может работать на одном узле, совмещая Control Plane и worker. |
| **kind** | K8s в Docker-контейнерах | Локальная разработка, тестирование CI/CD. |
| **minikube** | Локальный K8s в ВМ/контейнере | Локальная разработка, обучение. |
