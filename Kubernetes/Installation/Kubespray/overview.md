# Kubespray: Обзор

## 1. Определения

**Kubespray** — проект с открытым исходным кодом для автоматизации установки и управления жизненным циклом кластеров Kubernetes с помощью [Ansible](../../../Ansible/ansible_introduction.md) и [kubeadm](../kubeadm/ha_keepalived_haproxy/index.md).

**Принцип работы:** Kubespray автоматизирует выполнение команд `kubeadm` на всех хостах (control plane и worker узлах) через Ansible-плейбуки. Это позволяет декларативно описывать желаемое состояние кластера и применять его к целевым серверам.

## 2. Основные концепции

### Ключевые возможности

| Возможность | Описание |
| :--- | :--- |
| **Автоматизация** | Полностью автоматизированное развертывание, масштабирование и обновление |
| **Гибкость** | Поддержка множества ОС: Ubuntu, CentOS, Rocky Linux, Debian, AlmaLinux |
| **Настраиваемость** | Настройка CNI, DNS, runtime-компонентов через переменные |
| **Отказоустойчивость (HA)** | Встроенная поддержка HA [Control Plane](../../Concepts/control_plane_architecture.md) и [etcd](../../Concepts/etcd_overview.md) |

### Поддерживаемые компоненты

* **CNI-плагины:** Calico, Cilium, Flannel, Weave Net. *Подробнее: [CNI и kube-proxy: навигатор](../../Networking/Network/cni_kube_proxy_roles.md)*
* **DNS-провайдеры:** [CoreDNS](../../Networking/dns_deep_dive.md), NodeLocal DNSCache.
* **Container Runtime:** containerd (рекомендуется), CRI-O, Docker (устарел).
* **Ingress:** NGINX Ingress Controller.
* **LoadBalancer:** MetalLB (для bare-metal).
* **Мониторинг:** Prometheus, Grafana (опционально).

### Недостатки и рекомендации

| Аспект | Описание |
| :--- | :--- |
| **Скорость** | Применение изменений занимает 15+ минут («можно пойти пить чай») |
| **Идеальный сценарий** | Небольшие кластеры (до 20–50 узлов) без частых изменений конфигурации |
| **Обертка над kubeadm** | Надёжность и предсказуемость, но ценой скорости. После установки возможно управление через `kubeadm` |
| **Дополнения** | Ingress, мониторинг и другие аддоны рекомендуется устанавливать отдельно |
| **Обновления** | Плейбуки `upgrade-cluster.yml` и `scale.yml` выполняются последовательно на каждом узле |

## 3. Практические сценарии

| Сценарий | Файл |
| :--- | :--- |
| Развертывание кластера | **[Установка кластера](./kubespray_install/basic_concepts.md)** |
| Масштабирование и обновление | **[Управление кластером](./cluster_management.md)** |
| **HA-кластер (Keepalived + HAProxy)** | **[HA через Kubespray](./HA/index.md)** |
| **Offline-кластер (Air-gapped)** | **[Offline установка](./offline_installation/offline_definitions.md)** |
| Примеры конфигураций | **[Примеры](./examples.md)** |
| Альтернатива: ручная установка | **[kubeadm: Быстрый старт](../kubeadm/ha_keepalived_haproxy/index.md)** |

## 4. Дополнительная информация

См. также: [Ansible: Введение](../../../Ansible/ansible_introduction.md), [kubeadm: Быстрый старт](../kubeadm/ha_keepalived_haproxy/index.md), [HA с kubeadm](../kubeadm/ha_keepalived_haproxy/ha_concepts.md), [Control Plane: Архитектура](../../Concepts/control_plane_architecture.md), [etcd: Обзор](../../Concepts/etcd_overview.md), [kind](../kind/kind_concepts.md), [Talos](../local_cluster_with_talosctl.md).

Внешние ресурсы: [официальный репозиторий](https://github.com/kubernetes-sigs/kubespray), [документация Kubespray](https://kubespray.io/).
