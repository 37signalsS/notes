# Kubespray: Обзор

## Определения

**Kubespray** — проект с открытым исходным кодом под эгидой Kubernetes SIG Cluster Lifecycle, предназначенный для автоматизации развертывания и управления жизненным циклом кластеров Kubernetes (LCPM) в различных средах: bare metal, публичные и частные облака.

**Принцип работы:** инструмент использует мощь [Ansible](../../../Ansible/ansible_introduction.md) для декларативного описания конфигурации и [kubeadm](../kubeadm/index.md) для низкоуровневой инициализации компонентов кластера. Это позволяет стандартизировать процесс установки при сохранении высокой степени гибкости.

## Основные концепции

### Совместимость версий (2024–2025)

Kubespray поддерживает широкий диапазон версий Kubernetes. Ниже приведена матрица соответствия последних релизов:

| Версия Kubespray | Версия Kubernetes (Default) | Диапазон поддерживаемых версий K8s |
| :--- | :--- | :--- |
| **v2.29** | v1.32.x | v1.31 – v1.33 |
| **v2.28** | v1.31.x | v1.30 – v1.32 |
| **v2.27** | v1.30.x | v1.29 – v1.31 |
| **v2.26** | v1.29.x | v1.28 – v1.30 |
| **v2.25** | v1.28.x | v1.27 – v1.29 |

### Технические требования

*   **Машина управления (Control Node):** Ansible 2.14+, Python 3.10+.
*   **Целевые узлы (Target Nodes):**
    *   **ОС:** Ubuntu (22.04, 24.04), Debian 11/12, Rocky Linux 8/9, AlmaLinux 8/9, RHEL 8/9, Flatcar.
    *   **Память:** минимум 2 ГБ RAM (рекомендуется 4 ГБ+ для Control Plane).
    *   **Сеть:** IPv4 (Dual-stack IPv4/IPv6 поддерживается), доступ по SSH, отключенный SWAP.
    *   **Cgroups:** полная поддержка Cgroup v2 (стандарт для современных дистрибутивов).

### Поддерживаемые компоненты

| Компонент | Варианты реализации |
| :--- | :--- |
| **Container Runtime** | **containerd** (рекомендуется), CRI-O, Docker (deprecated) |
| **CNI-плагины** | Calico (default), **Cilium** (рекомендуется для eBPF), Flannel, Weave Net, Kube-OVN |
| **DNS** | [CoreDNS](../../Networking/dns_deep_dive.md), NodeLocal DNSCache |
| **HA (Control Plane)** | **Kube-Vip** (современный стандарт), Keepalived + HAProxy, External LB |
| **Ingress** | NGINX Ingress Controller (поддержка Gateway API в разработке) |
| **LoadBalancer** | [MetalLB](../../Networking/metallb.md) (для bare-metal), Kube-Vip |
| **Storage** | CSI-драйверы для AWS, Azure, GCP, OpenStack, vSphere, Ceph, Rook |

### Особенности эксплуатации

*   **Декларативность:** все настройки хранятся в `group_vars`, что позволяет версионировать конфигурацию кластера в Git (GitOps подход).
*   **Идемпотентность:** плейбуки гарантируют, что повторный запуск не приведет к нежелательным изменениям, если текущее состояние соответствует описанному.
*   **Масштабируемость:** оптимален для кластеров среднего размера (до 100-200 узлов). Для экстремально больших кластеров требуется оптимизация параметров запуска Ansible.
*   **Управление жизненным циклом:** отдельные плейбуки для добавления (`scale.yml`), удаления (`remove-node.yml`) узлов и бесшовного обновления (`upgrade-cluster.yml`).

## Практические сценарии

| Сценарий | Описание и ссылка |
| :--- | :--- |
| **Базовая установка** | Подготовка окружения, инвентаря и первый запуск: **[Установка кластера](./kubespray_install/basic_concepts.md)** |
| **Управление узлами** | Масштабирование, замена узлов и обновление версии: **[Управление кластером](./cluster_management.md)** |
| **Высокая доступность** | Настройка HA Control Plane через Kube-Vip или HAProxy: **[HA через Kubespray](./HA/index.md)** |
| **Offline (Air-gapped)** | Развертывание в изолированных сетях без доступа к интернету: **[Offline установка](./offline_installation/offline_definitions.md)** |
| **Примеры конфигураций** | Готовые наборы переменных для различных сценариев: **[Примеры](./examples.md)** |
| **Ручная альтернатива** | Если автоматизация Ansible не требуется: **[kubeadm: Быстрый старт](../kubeadm/index.md)** |

## Дополнительная информация

### См. также

*   [Ansible: Введение](../../../Ansible/ansible_introduction.md) — основы работы с инструментом автоматизации.
*   [kubeadm: Быстрый старт](../kubeadm/index.md) — базовый механизм, используемый Kubespray.
*   [HA с kubeadm](../kubeadm/ha_concepts.md) — концепции отказоустойчивости.
*   [Control Plane: Архитектура](../../Concepts/control_plane_architecture.md) — внутреннее устройство Kubernetes.
*   [etcd: Обзор](../../Concepts/etcd_overview.md) — работа распределенного хранилища.
*   [CNI и kube-proxy](../../Networking/Network/cni_kube_proxy_roles.md) — сетевая подсистема.

### Внешние ресурсы

*   [Официальный репозиторий GitHub](https://github.com/kubernetes-sigs/kubespray) — исходный код и issues.
*   [Документация Kubespray](https://kubespray.io/) — подробное описание всех переменных.
*   [Ansible Documentation](https://docs.ansible.com/) — справочник по модулям и синтаксису.
