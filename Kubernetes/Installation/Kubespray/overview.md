# Kubespray: Обзор

## Определения

**Kubespray** — проект с открытым исходным кодом для автоматизации установки и управления жизненным циклом кластеров Kubernetes с помощью [Ansible](../../../Ansible/ansible_introduction.md) и [kubeadm](../kubeadm/index.md).

**Принцип работы:** Kubespray автоматизирует выполнение команд `kubeadm` на всех хостах (control plane и worker узлах) через Ansible-плейбуки. Это позволяет декларативно описывать желаемое состояние кластера и применять его к целевым серверам.

## Основные концепции

### Ключевые возможности

| Возможность | Описание |
| :--- | :--- |
| **Автоматизация** | Полностью автоматизированное развертывание, масштабирование и обновление |
| **Гибкость** | Поддержка множества ОС: Ubuntu, CentOS, Rocky Linux, Debian, AlmaLinux |
| **Настраиваемость** | Настройка CNI, DNS, runtime-компонентов через переменные |
| **Отказоустойчивость (HA)** | Встроенная поддержка HA [Control Plane](../../Concepts/control_plane_architecture.md) и [etcd](../../Concepts/etcd_overview.md) |

### Поддерживаемые компоненты

* **CNI-плагины:** Calico, Cilium, Flannel, Weave Net. Подробнее: [CNI и kube-proxy: навигатор](../../Networking/Network/cni_kube_proxy_roles.md)
* **DNS-провайдеры:** [CoreDNS](../../Networking/dns_deep_dive.md), NodeLocal DNSCache
* **Container Runtime:** containerd (рекомендуется), CRI-O, Docker (устарел)
* **Ingress:** NGINX Ingress Controller
* **LoadBalancer:** [MetalLB](../../Networking/metallb.md) (для bare-metal)
* **Мониторинг:** Prometheus, Grafana (опционально)

### Особенности эксплуатации

| Аспект | Описание |
| :--- | :--- |
| **Скорость** | Применение изменений занимает 15+ минут (последовательное выполнение задач Ansible) |
| **Масштабируемость** | Оптимально для кластеров до 50–100 узлов без частых изменений конфигурации |
| **База на kubeadm** | Использует стандартный механизм `kubeadm`, обеспечивая предсказуемость результата |
| **Модульность** | Дополнительные компоненты (Ingress, мониторинг) можно устанавливать отдельно |
| **Обновления** | Плейбуки `upgrade-cluster.yml` позволяют проводить rolling-обновления узлов |

## Практические сценарии

| Сценарий | Файл |
| :--- | :--- |
| Развертывание кластера | **[Установка кластера](./kubespray_install/basic_concepts.md)** |
| Масштабирование и обновление | **[Управление кластером](./cluster_management.md)** |
| **HA-кластер (Keepalived + HAProxy)** | **[HA через Kubespray](./HA/index.md)** |
| **Offline-кластер (Air-gapped)** | **[Offline установка](./offline_installation/offline_definitions.md)** |
| Примеры конфигураций | **[Примеры](./examples.md)** |
| Альтернатива: ручная установка | **[kubeadm: Быстрый старт](../kubeadm/index.md)** |

## Дополнительная информация

См. также:

* [Ansible: Введение](../../../Ansible/ansible_introduction.md)
* [kubeadm: Быстрый старт](../kubeadm/index.md)
* [HA с kubeadm](../kubeadm/ha_concepts.md)
* [Control Plane: Архитектура](../../Concepts/control_plane_architecture.md)
* [etcd: Обзор](../../Concepts/etcd_overview.md)
* [CNI и kube-proxy](../../Networking/Network/cni_kube_proxy_roles.md)

Внешние ресурсы:

* [Официальный репозиторий](https://github.com/kubernetes-sigs/kubespray)
* [Документация Kubespray](https://kubespray.io/)
